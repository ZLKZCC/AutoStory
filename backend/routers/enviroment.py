import asyncio
from pathlib import Path

from config.db_conf import init_vector
from config.store import MODEL_REGISTRY, MODEL_DIR_MAP, conf
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from utils.download import (
    check_model_ready,
    clean_model_temp_artifacts,
    ensure_downloads_started,
    get_prepare_status,
    is_all_settled,
    register_ws_client,
    retry_failed_models,
    unregister_ws_client, get_folder_size,
)

router = APIRouter(prefix="/autostory/environment", tags=["environment"])

@router.websocket("/sync_model")
async def sync_environment_ws(websocket: WebSocket):
    """WebSocket 接口（仅负责模型同步）：
    - 连接建立时登记客户端并触发一次下载调度（幂等）
    - 每秒推送一次 {"data": PrepareItem[]}；源暂不可达按 pending 推送（非终态，不触发跳转），
      循环内每 5 秒幂等重拉下载调度，网络恢复后自动续下
    - 所有模型达到终态（done / error）后主动关闭连接
    - 连接关闭时注销客户端、自检清理临时残留；所有前端失联时下载任务自动中止并清理"""

    await websocket.accept()
    register_ws_client()
    try:
        # 重连/下载进行中时 ensure 返回 None，落 settle 分支迭代会炸
        missing_models = ensure_downloads_started() or []
        ensure_tick = 0
        while True:
            status = get_prepare_status()
            await websocket.send_json({"data": status})
            if is_all_settled(status):
                for model in missing_models:
                    if model["name"] == "bge-m3":
                        await init_vector()
                break
            ensure_tick += 1
            if ensure_tick % 5 == 0:
                # unreachable → pending 属网络暂态：定期幂等拉起，
                # 网络恢复后重新测到 missing 的模型由此续下，直到下好
                started = await asyncio.to_thread(ensure_downloads_started)
                if started:
                    known = {m["name"] for m in missing_models}
                    missing_models.extend(m for m in started if m["name"] not in known)
            await asyncio.sleep(1)
        await websocket.close(code=1000)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        # 正常关闭与失联都走这里：归零即中止下载；清理仅作用于判定 ready 的模型，
        # 清不掉也不影响判定（比对只查清单内文件）
        unregister_ws_client()
        await asyncio.to_thread(clean_model_temp_artifacts)

@router.post("/retry_failed")
async def retry_failed():
    """显式重试本会话报错的模型（修好磁盘/网络后由用户触发；失败不自动重试，错误已在前端展示）"""
    retried = await asyncio.to_thread(retry_failed_models)
    return {"retried": retried}

@router.get("/check_models")
async def check_models():
    """获取所有模型的实际信息（无参数）：
    - id/name/description/category/size 取自 MODEL_REGISTRY
    - exists 走判定链：本地清单优先离线比对，无本地清单时多源拉取取差异最小并持久化"""
    items = []
    for model in MODEL_REGISTRY:
        model_dir_val = MODEL_DIR_MAP[model["id"]]
        model_dir = getattr(conf, model_dir_val)
        size = await get_folder_size(model_dir)
        items.append({
            "id": model["id"],
            "name": model["name"],
            "description": model["description"],
            "category": model["category"],
            "size": size,
            "exists": check_model_ready(model) == "ready",
        })
    return {"items": items}