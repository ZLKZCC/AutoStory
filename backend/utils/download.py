import asyncio
import os
import re
import ssl
import json
import time
import shutil
import random
import threading
from functools import partial
from http.client import IncompleteRead
from operator import itemgetter
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modelscope import snapshot_download

from config.store import (
    DOWNLOAD_SOURCES,
    MODEL_DIR_MAP,
    MODEL_REGISTRY,
    MODELSCOPE_REPO_MAP,
    conf,
)

class DownloadAborted(Exception):
    """中止信号（所有前端 WS 断开）：不重试、不切源，直接退出并清理"""

# =========================================================
# 常量配置
# =========================================================
# 反爬/限流重试：403/429 多为限流或 CDN 签名过期，等待后重试通常可恢复；5xx 为服务端临时故障
_RETRYABLE_HTTP_CODES = {403, 408, 429, 500, 502, 503, 504}
_DOWNLOAD_MAX_RETRIES = 5
_LIST_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # 指数退避基数（2/4/8/16s + 随机抖动）

# 并发与请求节流：多仓库同时下载时压制瞬时请求密度
_DOWNLOAD_CONCURRENCY = 2  # 同时下载的模型数上限，其余排队 pending
_API_MIN_INTERVAL = 1.0    # 全局 API/文件请求发起的最小间隔（秒）
_USER_AGENT = "AutoStory/0.1.0"

# 源测速排序缓存：无可达源时用短缓存，网络恢复后尽快重测
_SOURCE_CACHE_TTL = 60.0
_SOURCE_FAIL_CACHE_TTL = 15.0

# 本地清单：持久化在模型目录中（含源头与文件字节数），判定离线可用
_MANIFEST_FILENAME = ".manifest.json"
_UNREACHABLE_RETRY_INTERVAL = 60.0  # 全源不可达后的重试间隔（防止 WS 每秒推送反复打源）

# 清单比对白名单：HF/ModelScope 仓库文件集不同（git 元数据、README 配图、onnx 备份等），
# 这些非运行文件不参与比对，否则跨源下载后会被永久误判为缺失
_JUNK_MANIFEST_TOP_DIRS = {"imgs", "images", "examples", "onnx", "openvino"}
_JUNK_MANIFEST_SUFFIXES = (".gitattributes", ".gitignore", ".ds_store", ".md",
                           ".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf")
# 字节数校验只对大文件（权重）做：小配置文件在两源可能是不同版本，只查存在性
_MANIFEST_SIZE_CHECK_MIN = 1024 * 1024

# =========================================================
# 模块级运行状态
# =========================================================
_download_progress: Dict[str, Dict[str, Any]] = {}  # mid → 进度字典
_download_lock = threading.Lock()
_download_semaphore = threading.Semaphore(_DOWNLOAD_CONCURRENCY)
_api_rate_lock = threading.Lock()
_last_api_request = 0.0

_ws_clients_lock = threading.Lock()
_ws_client_count = 0
_abort_event = threading.Event()

_source_candidates_lock = threading.Lock()
_source_candidates_cache: List[Tuple[str, bool]] = []
_source_candidates_ts = 0.0

_unreachable_ts: Dict[str, float] = {}  # mid → 判定为全源不可达的时间（短缓存重试间隔）
_errored_models: set = set()  # mid → 本会话真报错的模型：ensure 不再自动拉起，等用户显式重试

# =========================================================
# 中止控制（前端失联等场景）
# =========================================================
def register_ws_client():
    """前端 WS 接入：计数 +1 并清除中止标记"""
    global _ws_client_count
    with _ws_clients_lock:
        _ws_client_count += 1
        _abort_event.clear()

def unregister_ws_client():
    """前端 WS 断开：计数 -1；归零即所有前端失联，置中止标记"""
    global _ws_client_count
    with _ws_clients_lock:
        _ws_client_count = max(0, _ws_client_count - 1)
        if _ws_client_count > 0:
            return
        _abort_event.set()
        with _download_lock:
            has_active = any(p.get("status") in ("running", "pending")
                             for p in _download_progress.values())
    if has_active:
        print("[download] 所有前端连接已断开，中止下载任务")

def _check_abort():
    """下载热路径检查点；中止时抛 DownloadAborted"""
    if _abort_event.is_set():
        raise DownloadAborted()

# =========================================================
# 进度管理
# =========================================================
def get_progress() -> Dict[str, Dict[str, Any]]:
    with _download_lock:
        return dict(_download_progress)

def _update_progress(model_id: str, **kwargs):
    with _download_lock:
        _download_progress.setdefault(model_id, {}).update(kwargs)

# =========================================================
# 网络请求节流与重试
# =========================================================
def _throttle_api_request():
    """全局请求节流：任意两次请求发起之间至少间隔 _API_MIN_INTERVAL，
    多仓库并发下载时避免瞬时请求过于密集触发反爬"""
    global _last_api_request
    with _api_rate_lock:
        wait = _API_MIN_INTERVAL - (time.time() - _last_api_request)
        if wait > 0:
            time.sleep(wait)
        _last_api_request = time.time()

def _is_retryable_error(exc: Exception) -> bool:
    """URLError / 连接重置 / 超时等网络抖动均归 OSError；IncompleteRead 为中途断流"""
    if isinstance(exc, HTTPError):
        return exc.code in _RETRYABLE_HTTP_CODES
    return isinstance(exc, (OSError, IncompleteRead))

def _run_with_retry(action: Callable, description: str, max_retries: int,
                    abortable: bool = True, model_id: Optional[str] = None) -> Any:
    """指数退避重试包装（清单拉取 / 文件下载 / ModelScope SDK 共用）：
    - abortable=False 用于无 WS 连接的判定路径（清单拉取），不受中止信号影响
    - model_id 给定时，等待期间清零速度以维持 running 状态
    - 不可重试异常与重试耗尽直接抛出；中止信号直通"""
    for attempt in range(max_retries):
        if abortable:
            _check_abort()
        try:
            return action()
        except DownloadAborted:
            raise
        except Exception as e:
            if not _is_retryable_error(e) or attempt == max_retries - 1:
                raise
            delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
            print(f"[download] {description}失败({e})，{delay:.0f}s 后重试 {attempt + 2}/{max_retries}")
            if model_id:
                _update_progress(model_id, speed_bps=0)
            time.sleep(delay)
    raise RuntimeError(f"{description}重试次数耗尽")

# =========================================================
# 通用工具
# =========================================================
def _make_ssl_context() -> ssl.SSLContext:
    """下载源均为公开 CDN，跳过证书校验避免部分镜像站证书异常"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def _get_model_dir(mid: str):
    """模型目录：优先取 conf 显式配置，否则 MODELS_DIR/<id>"""
    dir_attr = MODEL_DIR_MAP.get(mid)
    return getattr(conf, dir_attr, None) if dir_attr else (conf.MODELS_DIR / mid)

def _get_repo_for_source(model: Dict, source: Dict) -> str:
    """按源类型解析仓库名：HF 用 repo 配置，ModelScope 用映射表"""
    mid = model['id']
    repo = model.get("repo", f"BAAI/{mid}")
    if source["type"] != "huggingface":
        repo = MODELSCOPE_REPO_MAP.get(mid) or repo
    return repo

def _parse_size_str(size_str: str) -> int:
    """registry size 字符串（如 '~2.2 GB'）转字节数"""
    if not size_str:
        return 0
    m = re.match(r'~?\s*([\d.]+)\s*(TB|GB|MB|KB|B)', size_str, re.IGNORECASE)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2).upper()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
    return int(val * multipliers.get(unit, 1))

def _format_speed(bps: float) -> str:
    if bps <= 0:
        return ""
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(bps) < 1024:
            return f"{bps:.1f} {unit}/s"
        bps /= 1024
    return f"{bps:.1f} TB/s"

def _get_dir_size(path: str) -> int:
    total = 0
    if not os.path.exists(path):
        return 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total

def _rmtree_force(path: str) -> bool:
    """强制删除目录：Windows 下文件句柄可能被占用（杀毒/索引扫描），
    rmtree 中途失败会留下半删状态；失败时重试一次，仍失败则自底向上
    逐文件删除（被占用文件跳过，残留待下次中止/下载时再清）"""
    for _ in range(2):
        try:
            shutil.rmtree(path)
            return True
        except OSError as e:
            print(f"[download] 目录删除失败({e})，重试...")
            time.sleep(0.5)
    for root, dirs, files in os.walk(path, topdown=False):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except OSError:
                pass
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass
    return not os.path.exists(path)

def _clean_temp_artifacts(model_dir: str):
    """清理下载 SDK 的临时残留（._____temp 目录 / .tmp 文件）：
    仅在模型判定 ready 后调用；判定比对只查清单内文件，
    多余文件不影响结果，清不掉也无害"""
    temp_dir = os.path.join(model_dir, "._____temp")
    if os.path.isdir(temp_dir):
        _rmtree_force(temp_dir)
    for root, _, files in os.walk(model_dir):
        for f in files:
            if f.endswith(".tmp"):
                try:
                    os.remove(os.path.join(root, f))
                except OSError:
                    pass

# =========================================================
# 下载源测速与候选
# =========================================================
def _measure_source_speed(source_key: str) -> float:
    """实测源可达性与速度（bytes/s，不可达为 0）：HF 系用小文件测真实下载速度；
    ModelScope 改用仓库元数据接口验证连通性（文件下载 API 不稳定，
    容易超时/404 被误判为不可达）"""
    source = DOWNLOAD_SOURCES.get(source_key)
    if not source:
        return 0
    if source["type"] == "huggingface":
        test_url = f"{source['base_url']}/BAAI/bge-m3/resolve/main/config.json"
    else:
        repo = MODELSCOPE_REPO_MAP.get("bge-m3", "Xorbits/bge-m3")
        test_url = f"{source['base_url']}/api/v1/models/{repo}"
    try:
        req = Request(test_url, headers={"User-Agent": _USER_AGENT})
        _throttle_api_request()
        start = time.time()
        urlopen(req, timeout=10, context=_make_ssl_context()).read(32 * 1024)
        return 32 * 1024 / (time.time() - start)
    except Exception:
        return 0

def get_source_candidates() -> List[Tuple[str, bool]]:
    """源候选（测速降序）：实测可达（速度>0）的源在前；测速失败的源不剔除、
    按配置顺序垫底作备胎（可能只是瞬时抖动），切换到备胎时会先快速复测，
    不可达立即跳过，不在死源上浪费时间。
    返回 (source_key, verified) 列表；缓存有效期见 _SOURCE_CACHE_TTL / _SOURCE_FAIL_CACHE_TTL"""
    global _source_candidates_cache, _source_candidates_ts
    with _source_candidates_lock:
        cache_alive = _source_candidates_cache and time.time() - _source_candidates_ts < (
            _SOURCE_CACHE_TTL if any(v for _, v in _source_candidates_cache)
            else _SOURCE_FAIL_CACHE_TTL)
        if cache_alive:
            return list(_source_candidates_cache)
    measured = [(key, _measure_source_speed(key)) for key in DOWNLOAD_SOURCES]
    measured.sort(key=itemgetter(1), reverse=True)  # 稳定排序：速度=0 保持配置顺序垫底
    ranked = [(key, speed > 0) for key, speed in measured]
    with _source_candidates_lock:
        _source_candidates_cache = ranked
        _source_candidates_ts = time.time()
    return list(ranked)

# =========================================================
# 仓库清单拉取（云端）
# =========================================================
def _list_repo_files_once(source: Dict, repo: str) -> Dict[str, int]:
    """单次拉取仓库文件清单及各文件大小（bytes）：
    HF 系 ?blobs=true 使 LFS 大文件（safetensors 等）也带 size；
    ModelScope Recursive=true 列全部，目录条目 Size=0 被过滤"""
    _throttle_api_request()
    if source["type"] == "huggingface":
        req = Request(f"{source['base_url']}/api/models/{repo}?blobs=true",
                      headers={"User-Agent": _USER_AGENT})
        with urlopen(req, timeout=15, context=_make_ssl_context()) as resp:
            data = json.load(resp)
        return {s["rfilename"]: int(s.get("size") or 0)
                for s in data.get("siblings", [])}
    req = Request(f"{source['base_url']}/api/v1/models/{repo}/repo/files?Recursive=true",
                  headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=15, context=_make_ssl_context()) as resp:
        data = json.load(resp)
    return {x["Path"]: int(x.get("Size") or 0)
            for x in data.get("Data", {}).get("Files", []) if x.get("Size")}

def _list_repo_files(source: Dict, repo: str) -> Dict[str, int]:
    """拉取仓库实时文件清单（云端更新无需改本地配置）；失败返回空 dict 由调用方回退。
    不受中止信号影响：清单拉取是轻量 API 调用，且需在无 WS 连接的判定路径下工作"""
    try:
        return _run_with_retry(partial(_list_repo_files_once, source, repo),
                               "清单拉取", _LIST_MAX_RETRIES, abortable=False)
    except Exception:
        return {}

# =========================================================
# 本地清单持久化
# =========================================================
def _load_local_manifest(model_dir) -> Optional[Dict[str, int]]:
    """读取模型目录中的本地清单（文件名 → 字节数）；不存在或损坏返回 None"""
    path = os.path.join(str(model_dir), _MANIFEST_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {fname: int(fsize) for fname, fsize in data.get("files", {}).items()}
    except (OSError, ValueError, TypeError):
        return None

def _save_local_manifest(model_dir, source_key: str, manifest: Dict[str, int]):
    """把源清单持久化到模型目录（标明源头），后续判定离线可用"""
    path = os.path.join(str(model_dir), _MANIFEST_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"source": source_key, "files": manifest}, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[download] 本地清单写入失败({e})")

def _fetch_source_manifests(model: Dict) -> Dict[str, Dict[str, int]]:
    """从各可达源拉取清单并过滤杂项：连不上/返回不了的源直接跳过，
    只保留能返回结果的源（key → 过滤后清单）"""
    result: Dict[str, Dict[str, int]] = {}
    for source_key, verified in get_source_candidates():
        if not verified:
            continue
        source = DOWNLOAD_SOURCES[source_key]
        raw = _list_repo_files(source, _get_repo_for_source(model, source))
        if raw:
            result[source_key] = {f: s for f, s in raw.items() if _is_manifest_entry_needed(f)}
    return result

def _manifest_diff_count(manifest: Dict[str, int], model_dir) -> int:
    """清单与本地目录的差异度：缺失文件数 + 大文件（≥1MB）大小不符数。
    目录里多出的文件不算差异（临时残留/缓存文件不影响判定）"""
    diff = 0
    for fname, fsize in manifest.items():
        fpath = os.path.join(str(model_dir), fname)
        if not os.path.exists(fpath):
            diff += 1
        elif fsize >= _MANIFEST_SIZE_CHECK_MIN and os.path.getsize(fpath) != fsize:
            diff += 1
    return diff

# =========================================================
# 就绪判定
# =========================================================
def check_model_ready(model: Dict) -> str:
    """模型就绪检查，返回三态：
    - ready: 清单内文件全部存在且大小一致（本地多出的文件不影响）
    - missing: 有缺失/大小不符，需要下载
    - unreachable: 本地无清单且所有源均拉不到清单，无法判定
    判定链：读本地 .manifest.json → 无则从各源拉清单（取与本地差异最小的一版）
    持久化为本地清单 → 比对"""
    mid = model['id']
    model_dir = _get_model_dir(mid)
    if not model_dir or not os.path.isdir(str(model_dir)):
        return "missing"
    manifest = _load_local_manifest(model_dir)
    if manifest is None:
        # 上次判定全源不可达且未到重试间隔：不反复打源
        if time.time() - _unreachable_ts.get(mid, 0) < _UNREACHABLE_RETRY_INTERVAL:
            return "unreachable"
        source_manifests = _fetch_source_manifests(model)
        if not source_manifests:
            _unreachable_ts[mid] = time.time()
            return "unreachable"
        _unreachable_ts.pop(mid, None)
        # 取与本地差异最小的一版作为该模型的清单并持久化
        best_key: Optional[str] = None
        best_diff = -1
        for source_key, source_manifest in source_manifests.items():
            diff = _manifest_diff_count(source_manifest, model_dir)
            if best_key is None or diff < best_diff:
                best_key, best_diff = source_key, diff
        manifest = source_manifests[best_key]
        _save_local_manifest(model_dir, best_key, manifest)
    return "ready" if _manifest_diff_count(manifest, model_dir) == 0 else "missing"

def get_missing_models() -> List[Dict[str, Any]]:
    """检查缺失模型：走 check_model_ready 判定链，
    返回缺失/无法判定列表（每项 status: missing=需下载 / unreachable=所有源不可达）"""
    missing: List[Dict[str, Any]] = []
    for model in MODEL_REGISTRY:
        state = check_model_ready(model)
        if state == "ready":
            continue
        missing.append({
            "id": model["id"],
            "name": model.get("name", model["id"]),
            "size": model.get("size", ""),
            "dir": str(_get_model_dir(model["id"]) or ""),
            "status": state,
        })
    return missing

# =========================================================
# 文件下载（HF 系直连）
# =========================================================
def _download_file_once(url: str, dest: str, model_id: str, completed: int, total: int) -> int:
    """单次文件下载：tmp 断点续传（Range 请求），0.5s 窗口报进度与速度"""
    tmp_path = dest + ".tmp"
    resume = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
    headers = {"User-Agent": _USER_AGENT}
    if resume > 0:
        headers["Range"] = f"bytes={resume}-"
    _throttle_api_request()
    resp = urlopen(Request(url, headers=headers), timeout=60, context=_make_ssl_context())
    mode = "ab" if resume > 0 and resp.getcode() == 206 else "wb"
    if mode == "wb":
        resume = 0  # 服务端不支持 Range，从头覆盖下载

    downloaded = resume
    window_bytes = 0
    last_time = time.time()
    with open(tmp_path, mode) as f:
        while chunk := resp.read(256 * 1024):
            _check_abort()
            f.write(chunk)
            downloaded += len(chunk)
            window_bytes += len(chunk)
            now = time.time()
            if now - last_time >= 0.5:
                elapsed = now - last_time
                # 速度 = 窗口内实际累计字节 / 窗口时长（固定按单个 chunk 算会在快网络严重失真）
                bps = window_bytes / elapsed if elapsed > 0 else 0
                overall = completed + downloaded
                progress_val = int((overall / total) * 100) if total else 0
                # 封顶 99：100 只由 done 状态写入，避免总量偏差导致提前满格
                _update_progress(model_id, progress=min(progress_val, 99),
                                 downloaded_bytes=overall, speed_bps=bps)
                last_time = now
                window_bytes = 0

    if os.path.exists(dest):
        os.remove(dest)
    os.rename(tmp_path, dest)
    return downloaded

def _download_file(url: str, dest: str, model_id: str, completed: int, total: int) -> int:
    """单文件下载：tmp 断点续传保证重试不重复下载已下字节"""
    return _run_with_retry(partial(_download_file_once, url, dest, model_id, completed, total),
                           f"{model_id} 下载", _DOWNLOAD_MAX_RETRIES, model_id=model_id)

# =========================================================
# 模型下载（ModelScope SDK）
# =========================================================
def _snapshot_with_retry(repo: str, model_dir: str, model_id: str):
    """ModelScope SDK 全量下载 + 重试（SDK 未安装时 ImportError 由上层切源）"""
    _run_with_retry(partial(snapshot_download, repo, local_dir=model_dir),
                    f"{model_id} ModelScope 下载", _DOWNLOAD_MAX_RETRIES, model_id=model_id)

def _monitor_dir_progress(model_id: str, model_dir: str, total_size: int, stop: threading.Event):
    """轮询目录已下字节数，按清单总量报进度与速度（ModelScope SDK 下载用）"""
    last_size = 0
    last_time = time.time()
    while not stop.wait(1.0):
        actual = _get_dir_size(model_dir)
        now = time.time()
        bps = (actual - last_size) / (now - last_time) if now > last_time else 0
        if total_size > 0:
            _update_progress(model_id, progress=min(int(actual / total_size * 100), 99),
                             downloaded_bytes=actual, speed_bps=max(bps, 0))
        last_size = actual
        last_time = now

# =========================================================
# 单模型下载编排
# =========================================================
def _download_from_huggingface(model: Dict, source: Dict, repo: str,
                               repo_files: Dict[str, int], total_size: int):
    """HF 系逐文件下载：已完整存在的文件直接跳过（重启/切源不重下）；
    清单拉取失败时回退 required_files（fsize=0 只查存在性）"""
    mid = model['id']
    model_dir = str(_get_model_dir(mid))
    files = repo_files or {f: 0 for f in model.get("required_files", [])}
    completed = 0
    for fname, fsize in files.items():
        dest = os.path.join(model_dir, fname)
        os.makedirs(os.path.dirname(dest), exist_ok=True)  # 清单含子目录文件
        if fsize and os.path.exists(dest) and os.path.getsize(dest) == fsize:
            completed += fsize
            _update_progress(mid, progress=int(completed / total_size * 100) if total_size else 0)
            continue
        url = f"{source['base_url']}/{repo}/resolve/main/{fname}"
        completed += _download_file(url, dest, mid, completed, total_size)

def _download_from_modelscope(model_id: str, repo: str, model_dir: str, total_size: int):
    """ModelScope 官方 SDK 全量下载（自带断点续传），监控线程按已下字节/清单总量报进度"""
    stop = threading.Event()
    monitor = threading.Thread(target=_monitor_dir_progress,
                               args=(model_id, model_dir, total_size, stop), daemon=True)
    monitor.start()
    try:
        _snapshot_with_retry(repo, model_dir, model_id)
    finally:
        stop.set()

def _download_model_with_source(model: Dict, source_key: str, verified: bool):
    """在指定源上下载单个模型（失败向上抛，由调度层切换源）：
    拉取云端清单 → 过滤杂项 → 下载开始即持久化为本地清单（中断后可离线判定）→ 分发下载"""
    mid = model['id']
    _check_abort()
    # 备胎源（测速未通过）先快速复测，仍不可达立即跳过，不在死源上浪费时间
    if not verified and _measure_source_speed(source_key) <= 0:
        raise RuntimeError(f"源 {source_key} 复测不可达，跳过")
    source = DOWNLOAD_SOURCES[source_key]
    repo = _get_repo_for_source(model, source)
    model_dir = _get_model_dir(mid)
    os.makedirs(model_dir, exist_ok=True)
    # 云端实时清单驱动：下载列表与总量均不写死本地，仓库更新自动跟随
    repo_files = _list_repo_files(source, repo)
    repo_files = {f: s for f, s in repo_files.items() if _is_manifest_entry_needed(f)}
    if repo_files:
        _save_local_manifest(model_dir, source_key, repo_files)
    total_size = sum(repo_files.values()) or _parse_size_str(model.get("size", "0"))
    if source["type"] == "huggingface":
        _download_from_huggingface(model, source, repo, repo_files, total_size)
    else:
        _download_from_modelscope(mid, repo, str(model_dir), total_size)

# =========================================================
# 下载调度
# =========================================================
def _abort_cleanup(mid: str):
    """中止善后：清空未完成目录（半成品不留，重连后重新下载），
    并清除进度记录使状态回到 pending"""
    model_dir = _get_model_dir(mid)
    if model_dir and os.path.isdir(str(model_dir)):
        if _rmtree_force(str(model_dir)):
            print(f"[download] {mid} 已中止，清空未完成目录 {model_dir}")
    with _download_lock:
        _download_progress.pop(mid, None)

def _try_download_sources(model: Dict, preferred_source: Optional[str]) -> Optional[Exception]:
    """依次尝试候选源（指定源置顶、可达源优先、备胎源先复测）：
    返回 None 表示成功，否则返回最后一个异常供调用方展示"""
    tried: set = set()
    last_error: Optional[Exception] = None
    while True:
        _check_abort()
        candidates = [(key, verified) for key, verified in get_source_candidates()
                      if key not in tried]
        if preferred_source and preferred_source in DOWNLOAD_SOURCES \
                and preferred_source not in tried:
            candidates = [(preferred_source, True)] + [c for c in candidates if c[0] != preferred_source]
        if not candidates:
            return last_error or RuntimeError("没有配置任何可用的下载源")
        source_key, verified = candidates[0]
        tried.add(source_key)
        try:
            _download_model_with_source(model, source_key, verified)
            return None
        except DownloadAborted:
            raise
        except ImportError:
            print(f"[download] {model['id']} 源 {source_key} 不可用（SDK 未安装），切换下一个源")
        except Exception as e:
            last_error = e
            print(f"[download] {model['id']} 源 {source_key} 失败({e})，切换下一个源")

def _download_thread_task(model: Dict, preferred_source: Optional[str] = None):
    """单模型下载线程：排队等全局槽位 → 依次尝试候选源 → 成功置 done / 全败置 error；
    中止信号触发则退出并清理未完成目录"""
    mid = model['id']
    _update_progress(mid, status="pending", speed_bps=0)
    try:
        with _download_semaphore:  # 并发上限 + 请求节流共同压制瞬时请求密度
            _check_abort()
            _update_progress(mid, status="running", progress=0, speed_bps=0)
            last_error = _try_download_sources(model, preferred_source)
    except DownloadAborted:
        # done 已提前返回，走到这里的都是半成品：清空目录并回退 pending
        _abort_cleanup(mid)
        return
    if last_error:
        error = str(last_error) if last_error else "所有下载源均不可用"
        _update_progress(mid, status="error", progress=0, speed_bps=0, error=error)
        with _download_lock:
            _errored_models.add(mid)  # 记入会话报错名单：停止自动重试，错误交由前端展示
    else:
        _update_progress(mid, status="done", progress=100, speed_bps=0)
        with _download_lock:
            _errored_models.discard(mid)

def start_download(model_id: str, source_key: Optional[str] = None, force: bool = False) -> str:
    """启动单模型下载线程；防止重复启动（含排队中的 pending）；
    force=True 复活本会话已报错的模型（仅限用户显式重试入口）"""
    model = next((m for m in MODEL_REGISTRY if m['id'] == model_id), None)
    if not model:
        return "model_not_found"
    if get_progress().get(model_id, {}).get("status") in ("running", "pending"):
        return "already_downloading"
    if force:
        with _download_lock:
            _errored_models.discard(model_id)
    threading.Thread(target=_download_thread_task, args=(model, source_key), daemon=True).start()
    return "started"

# =========================================================
# 对外状态接口（供 WebSocket / HTTP 使用）
# =========================================================
def get_prepare_status() -> List[Dict[str, Any]]:
    """输出与前端 PrepareItem 对齐的模型状态数组，供 WebSocket 每秒推送：
    - ready 且无进行中任务 → done
    - unreachable → pending（源暂不可达属网络暂态，60s 自动重测；不设终态、不触发跳转，
      网络恢复后由 WS 循环里的 ensure_downloads_started 拉起下载）
    - 其余以任务状态为准（running / pending / error）"""
    progress_map = get_progress()
    states = {m['id']: m.get("status", "missing") for m in get_missing_models()}
    items: List[Dict[str, Any]] = []
    for model in MODEL_REGISTRY:
        mid = model['id']
        name = model.get("name", mid)
        p = progress_map.get(mid, {})
        state = states.get(mid, "ready")
        if state == "unreachable":
            items.append({"name": name, "progress": 0, "speed": "",
                          "status": "pending", "error": "下载源暂时不可达，等待网络恢复..."})
            continue
        if state == "ready" and p.get("status") not in ("running", "pending"):
            items.append({"name": name, "progress": 100, "speed": "", "status": "done"})
            continue
        item: Dict[str, Any] = {
            "name": name,
            "progress": p.get("progress", 0),
            "speed": _format_speed(p.get("speed_bps", 0)),
            "status": p.get("status", "pending"),
        }
        if item["status"] == "error" and "error" in p:
            item["error"] = p["error"]
        items.append(item)
    return items

def is_all_settled(items: Optional[List[Dict[str, Any]]] = None) -> bool:
    """是否所有模型达到终态；error 也视为终态，避免 WebSocket 死循环"""
    if items is None:
        items = get_prepare_status()

    return all(item["status"] in ("done", "error") for item in items)

def ensure_downloads_started():
    """若有缺失模型且当前无任务在跑，则自动触发下载（幂等）；
    unreachable 不启动（源不可达，下载必然失败）；
    本会话已报错的模型不自动拉起——错误已爆给前端，反复重试无意义，等用户显式重试"""
    progress_map = get_progress()
    if any(p.get("status") in ("running", "pending") for p in progress_map.values()):
        return
    with _download_lock:
        errored = set(_errored_models)
    missing_models = get_missing_models()
    for m in missing_models:
        if m.get("status") == "missing" and m['id'] not in errored:
            start_download(m['id'])

    return missing_models

def retry_failed_models() -> List[str]:
    """用户显式重试入口：复活本会话所有报错任务重新下载，返回已重启的模型 id"""
    retried = []
    for mid, p in get_progress().items():
        if p.get("status") == "error" and start_download(mid, force=True) == "started":
            retried.append(mid)
    return retried

def clean_model_temp_artifacts():
    """自检清理已完成模型的下载临时残留（._____temp / .tmp）：
    仅处理判定 ready 的模型——未完成模型的半截是续传资产，保留。
    判定比对只查清单内文件，清不掉也不影响正确性"""
    for model in MODEL_REGISTRY:
        if check_model_ready(model) != "ready":
            continue
        model_dir = _get_model_dir(model["id"])
        if model_dir and os.path.isdir(str(model_dir)):
            _clean_temp_artifacts(str(model_dir))

def _is_manifest_entry_needed(fname: str) -> bool:
    """清单条目是否参与比对（剔除仓库杂项）"""
    base = fname.lower()
    if base.endswith(_JUNK_MANIFEST_SUFFIXES):
        return False
    return base.split("/")[0] not in _JUNK_MANIFEST_TOP_DIRS

def _human_readable_size(num_bytes):
    """将字节数转换为易读的字符串，自动选择合适的单位"""
    if num_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while num_bytes >= 1024 and i < len(units) - 1:
        num_bytes /= 1024.0
        i += 1
    return f"{num_bytes:.2f} {units[i]}"

def _calc_sync(folder_path, exclude_paths, exclude_names):
    total = 0
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            abs_path = os.path.abspath(file_path)
            # 跳过排除的文件（按文件名或绝对路径）
            if abs_path in exclude_paths or file in exclude_names:
                continue
            try:
                total += os.path.getsize(file_path)
            except OSError:
                # 忽略无法读取的文件
                continue
    return _human_readable_size(total)

async def get_folder_size(folder_path, exclude_files=None):
    """
    异步计算文件夹总大小（递归包含所有子文件夹中的文件）。

    :param folder_path: 要计算的文件夹路径
    :param exclude_files: 要排除的文件列表，元素可以是文件名（如 'temp.txt'）
                          或绝对路径（如 '/home/user/temp.txt'）
    :return: 总大小（字节）
    """
    if exclude_files is None:
        exclude_files = [_MANIFEST_FILENAME]

    # 预处理排除列表：分别存储文件名和绝对路径
    exclude_names = set()
    exclude_paths = set()
    for item in exclude_files:
        if os.path.isabs(item):
            exclude_paths.add(os.path.normpath(item))
        else:
            exclude_names.add(os.path.basename(item))

    # 在线程池中执行阻塞操作
    return await asyncio.to_thread(_calc_sync,folder_path,exclude_paths,exclude_names)