import io
import json
import math
import re
import sqlite3
import uuid
import asyncio
from pathlib import Path
from types import SimpleNamespace

from pydub import AudioSegment

from config.db_conf import AsyncSessionLocal
from config.store import conf
from crud.CharacterStage import get_stages_by_ids
from utils.voicegenerator import VoiceGenerator, probe_device, DEFAULT_REF_TEXT
from utils.audiobook.schemas import AudioScript, MappingTable
from utils.audiobook.persist import load_row, write_audio_done, write_voice_path

TTS_SAMPLE_RATE = 24000
DEFAULT_CHUNK = 400


def _volume_to_db(volume: float) -> float:
    """0-1 线性音量 → dB"""
    if volume <= 0:
        return -120.0
    return 20 * math.log10(volume)


def _split_long_text(text: str, chunk: int = DEFAULT_CHUNK) -> list[str]:
    """
    按句切长文本（。！？…换行为界），单块不超 chunk 字
    正常流程不触发（LLM 生成段限 20-80 字），仅用户手改 script 加长时兜底；
    单句自身超 chunk（无句读长句）按 chunk 硬切，避免整句绕过限制
    """
    out, buf = [], ""
    for s in re.split(r"(?<=[。！？…\n])", text):
        if len(s) > chunk:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(s[i:i + chunk] for i in range(0, len(s), chunk))
            continue
        if len(buf) + len(s) > chunk and buf:
            out.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        out.append(buf)
    return out


def _resolve_voices(stages_by_name: dict) -> tuple[dict, list[tuple[int, str]], list[str]]:
    """阶段一：预解析所有 speaker 的音色 → wav 路径。
    voice_path 存在 → 复用；否则统一开一个 voice_design 实例依次 design 落盘。
    关键设计（避免 GPU 显存争用）：
    voice_design 模型与 base 模型各约 4.7GB，单 GPU（8GB）装不下同时存在。
    若每 speaker 各开一个 voice_design 短实例 + gen.register(base)，
    第一次 register 后 base 已占 4.7GB，第二次 design 兜底再分配 4.7GB 时
    总计 9.4GB > 8GB → "GPU 空闲不足" 失败。
    做法：此阶段统一处理所有 design 兜底，**base 还没加载**；voice_design 实例
    design 完所有需要 design 的 speaker 后立即 release；之后才进入阶段二
    加载 base + register。两阶段互斥，永不共存。
    返回:
      resolved:     {speaker: (wav_path, ref_text)} —— 全部 speaker 的最终 wav + ref_text
      voice_writes: [(stage_id, wav_path)] —— 新 design 出的需要回写
      warnings:     提示文本（复用/已设计并固化）
    """
    resolved: dict[str, tuple[str, str]] = {}
    voice_writes: list[tuple[int, str]] = []
    warnings: list[str] = []
    design_pending: list[tuple[str, object]] = []

    for name, stage in stages_by_name.items():
        if stage.voice_path and Path(stage.voice_path).exists():
            resolved[name] = (stage.voice_path, DEFAULT_REF_TEXT)
            warnings.append(f"[voice] {name}: 复用 {stage.voice_path}")
        else:
            design_pending.append((name, stage))

    # 一次性 design 所有需要 design 的 speaker（共用一个 voice_design 实例）
    if design_pending:
        device = probe_device("voice_design")
        dgen = VoiceGenerator(device=device)
        try:
            for name, stage in design_pending:
                desc = (stage.voice_description
                        or f"{stage.gender or '中性'}，{stage.age_Description or '成年'}")
                wavs, sr = dgen.design_voice(desc, DEFAULT_REF_TEXT)
                if not wavs:
                    raise RuntimeError(f"{name} 音色设计失败（voice_design 未返回音频）")
                # 落盘（目录约定 data/characters/characterstage_{id}/）
                stage_dir = conf.CHARACTER_DIR / f"characterstage_{stage.id}"
                stage_dir.mkdir(parents=True, exist_ok=True)
                wav_path = stage_dir / f"voice_{uuid.uuid4().hex[:12]}.wav"
                import soundfile as sf
                sf.write(wav_path, wavs[0], sr)
                resolved[name] = (str(wav_path), DEFAULT_REF_TEXT)
                voice_writes.append((stage.id, str(wav_path)))
                warnings.append(f"[voice] {name}: 已设计并固化 {wav_path}")
        finally:
            dgen.release()  # 阶段一末尾释放 voice_design，给阶段二的 base 让显存

    return resolved, voice_writes, warnings


def _gen_segment(gen, seg, use_emotion: bool, failed: list, err_samples: list):
    """生成单段音频（长文按句切分逐块合成再拼）。
    use_emotion=True → 带 seg.emotion 走 custom_voice；False → 不带情绪走 base 克隆。
    失败不静默吞：落 1s 静音占位 + 把真实异常收进 err_samples
    （旧代码吞异常→整本静音还查不出原因）。
    """
    audio = AudioSegment.empty()
    for sub in _split_long_text(seg.text):
        try:
            audio += gen.generate(seg.speaker, sub,
                                  emotion=(seg.emotion if use_emotion else None),
                                  return_type="pydub")
        except Exception as e:
            failed.append(seg.index)
            if len(err_samples) < 3:
                err_samples.append(f"段{seg.index}[{seg.speaker}]: {type(e).__name__}: {e}")
            audio += AudioSegment.silent(duration=1000)
    return audio


def _gen_io_narration(gen, part: str, cfg, warnings: list):
    """片头/片尾旁白（无情绪，走 base 克隆路）；返回 AudioSegment 或 None（未启用/无文本/失败）"""
    if not cfg.enabled or not cfg.text:
        return None
    try:
        return gen.generate("旁白", cfg.text, return_type="pydub")
    except Exception as e:
        warnings.append(f"{part} 旁白合成失败({type(e).__name__}: {e})，使用静音")
        return None


def synthesize_audio(script: AudioScript, stages_by_name: dict,
                     on_progress=None) -> tuple[bytes, list[str], list[tuple[int, str]]]:
    """
    核心合成（同步；stages_by_name = {speaker: stage ORM 行}）
    on_progress(done, total, phase)：分段进度回调（phase ∈ resolve/plain/emotional/mix），
    供上层推实时进度；只报状态不参与流程，不传则零开销。
    返回 (mp3 bytes, warnings, voice_writes)：
      - warnings 含失败段号（用户可回改重合成）
      - voice_writes = [(stage_id, wav_path)]，async 调用方逐条调 persist.write_voice_path 回写

    串行多模型架构（8GB 单卡装不下两个 ~4.2GB 模型，三者从不同时驻留）：
    1. 预解析音色：voice_path 复用 / 没有就用 voice_design 现造参考音落盘（voice_design 用完即释放）
    2. 趟一：加载 base → register 提取各说话人指纹 → 无情绪段 + 片头/片尾旁白走 base 克隆 → 卸载 base
    3. 趟二：加载 custom_voice → 带情绪段用 register 存下的指纹生成（不需 base）→ 释放
    最后按段序拼接、混 BGM/SFX、接片头片尾、导出 mp3。
    """
    warnings: list[str] = list(script.metadata.warnings)
    failed: list[int] = []

    # 分段进度（趟一无情绪段 + 趟二带情绪段累计计入 done；intro/outro 不计）
    total = len(script.segments)
    done = 0

    def _p(phase: str) -> None:
        if on_progress is not None:
            on_progress(done, total, phase)

    # ── 阶段一：预解析所有 speaker 音色（voice_design 实例，用完释放）──
    _p("resolve")
    resolved, voice_writes, voice_warnings = _resolve_voices(stages_by_name)
    warnings.extend(voice_warnings)

    # ── 阶段二：两趟合成（base 与 custom_voice 各 ~4.2GB，8GB 单卡装不下两个 → 串行，用完一个卸一个）──
    gen = VoiceGenerator(device=probe_device("base"))
    try:
        # register 需 base 提取说话人指纹（create_voice_clone_prompt），指纹存进 gen._prompts，
        # 之后即便卸掉 base，趟二的 custom_voice 仍能用这份指纹（纯数据，不依赖 base 驻留）。
        for name, (wav_path, ref_text) in resolved.items():
            gen.register(name, wav_path, ref_text)

        segs = script.segments
        seg_audio: list = [None] * len(segs)
        err_samples: list[str] = []
        plain_idx = [i for i, s in enumerate(segs) if not s.emotion]
        emotional_idx = [i for i, s in enumerate(segs) if s.emotion]

        # 趟一（base 独占 GPU）：无情绪段 + 片头/片尾旁白，全走 base 克隆
        for i in plain_idx:
            seg_audio[i] = _gen_segment(gen, segs[i], False, failed, err_samples)
            done += 1
            _p("plain")
        intro_narr = _gen_io_narration(gen, "片头", script.intro, warnings)
        outro_narr = _gen_io_narration(gen, "片尾", script.outro, warnings)

        # 趟二（custom_voice 独占 GPU）：带情绪段。先卸 base 腾显存，两模型永不同时驻留。
        if emotional_idx:
            gen.unload("base")
        for i in emotional_idx:
            seg_audio[i] = _gen_segment(gen, segs[i], True, failed, err_samples)
            done += 1
            _p("emotional")

        # ── 按段序拼接 + 段间停顿 ──
        _p("mix")
        voice_track = AudioSegment.empty()
        seg_durations: list[int] = []  # 每段时长（ms，含 pause）
        for i, s in enumerate(segs):
            a = seg_audio[i] if seg_audio[i] is not None else AudioSegment.silent(duration=1000)
            pause_ms = int(s.pause_after_sec * 1000)
            if pause_ms > 0:
                a = a + AudioSegment.silent(duration=pause_ms)
            seg_durations.append(len(a))
            voice_track += a
        voice_track = voice_track.set_frame_rate(TTS_SAMPLE_RATE)

        # ── 段坐标 → 时间偏移，混 BGM/SFX ──
        starts = [sum(seg_durations[:i]) for i in range(len(seg_durations))]  # 每段起点 ms
        for track in script.bgm_tracks:
            audio = _load_resource(track.audio_id)
            if audio is None:
                warnings.append(f"BGM {track.audio_id} 加载失败，跳过")
                continue
            audio = (audio.set_frame_rate(TTS_SAMPLE_RATE)
                     .apply_gain(_volume_to_db(track.volume)))
            start_ms = starts[track.start_segment]
            end_ms = starts[track.end_segment] + seg_durations[track.end_segment]
            span_ms = end_ms - start_ms
            looped = (audio * (span_ms // len(audio) + 1))[:span_ms]
            if track.fade_in_sec > 0:
                looped = looped.fade_in(int(track.fade_in_sec * 1000))
            if track.fade_out_sec > 0:
                looped = looped.fade_out(int(track.fade_out_sec * 1000))
            voice_track = voice_track.overlay(looped, position=start_ms)

        for track in script.sfx_tracks:
            audio = _load_resource(track.audio_id)
            if audio is None:
                warnings.append(f"SFX {track.audio_id} 加载失败，跳过")
                continue
            audio = (audio.set_frame_rate(TTS_SAMPLE_RATE)
                     .apply_gain(_volume_to_db(track.volume)))
            voice_track = voice_track.overlay(audio, position=starts[track.segment])

        # ── intro/outro（旁白已在趟一用 base 念好，这里只补齐时长/衬底 BGM/淡入淡出）──
        final = voice_track
        for is_intro, cfg, narr in ((True, script.intro, intro_narr), (False, script.outro, outro_narr)):
            if not cfg.enabled:
                continue
            piece = AudioSegment.silent(duration=int(cfg.duration_sec * 1000))
            if narr is not None:
                piece = narr + AudioSegment.silent(
                    duration=max(0, int(cfg.duration_sec * 1000) - len(narr)))
            if cfg.audio_id:
                bgm = _load_resource(cfg.audio_id)
                if bgm is not None:
                    bgm = (bgm.set_frame_rate(TTS_SAMPLE_RATE)
                           .apply_gain(_volume_to_db(0.3))[:len(piece)])
                    piece = piece.overlay(bgm)
            piece = piece.fade_in(int(cfg.fade_in_sec * 1000)).fade_out(int(cfg.fade_out_sec * 1000))
            final = (piece + final) if is_intro else (final + piece)

        final = final.set_frame_rate(TTS_SAMPLE_RATE)

        if failed:
            warnings.append(f"失败段（静音占位，可改文重合成）: {sorted(set(failed))}")
        if err_samples:
            warnings.append("合成失败真因样本: " + " | ".join(err_samples))

        # 导出 mp3 到 bytes
        buf = io.BytesIO()
        final.export(buf, format="mp3")
        return buf.getvalue(), warnings, voice_writes
    finally:
        gen.release()


async def synthesize_audio_async(script: AudioScript, stages_by_name: dict,
                                 on_wait=None, on_progress=None) -> tuple[bytes, list[str], list[tuple[int, str]]]:
    """synthesize_audio 的异步入口（面板 / AI 轨 / 重合成共用）：
    经全局 GPU 闸放行后放线程池跑。闸按显存预算限流：8GB 单卡同时只放行一路合成，
    大显存卡可并行多路（受 MAX_CONCURRENT 封顶），杜绝两路合成同时压上各自 ~4.2GB
    模型撞 OOM。on_wait：确需排队时在阻塞前回调一次，供上层发"排队中"进度提示
    （不排队则不回调）。on_progress：分段进度回调，由线程池线程触发——此处经
    call_soon_threadsafe 桥回事件循环线程再回调，上层可安全操作 asyncio 对象。"""
    from utils.gpu_gate import gpu_gate, VRAM_TTS

    if on_wait is not None and gpu_gate.would_wait(VRAM_TTS):
        on_wait()
    if on_progress is None:
        progress_cb = None
    else:
        loop = asyncio.get_running_loop()

        def progress_cb(done: int, total: int, phase: str) -> None:
            loop.call_soon_threadsafe(on_progress, done, total, phase)

    async with gpu_gate.reserve(VRAM_TTS):
        return await asyncio.to_thread(synthesize_audio, script, stages_by_name,
                                       on_progress=progress_cb)


def _load_resource(audio_id: int) -> AudioSegment | None:
    """Resource.id → AudioSegment（同步直查 sqlite；合成在 executor 同步世界，不走 async session）"""
    db_path = conf.DATA_DIR / "autostory.db"
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT path FROM resource WHERE id = ?", (audio_id,)).fetchone()
        if not row or not row[0]:
            return None
        p = Path(row[0])
        if not p.exists():
            return None
        return AudioSegment.from_file(p)
    except Exception:
        return None
    finally:
        conn.close()


# ══════════════ 步骤9 唯一入口 ══════════════

async def finalize_audio(script_id: int, on_wait=None, on_progress=None) -> dict:
    """有声书合成唯一入口（面板合成 / AI 轨合成 / 重合成三方共用，幂等）。

    从脚本行读取已确认产物（script_path / mapping / narrator_desc）→ 组 name2stage →
    synthesize_audio_async（经全局 GPU 闸排队）→ 落盘 mp3（覆盖旧成品）→
    回写 audio_path / 角色音色 wav / warnings。返回 {"audio_path", "warnings"}。
    on_wait / on_progress 透传给合成层（排队提示 / 分段进度，见 synthesize_audio_async）。

    前置缺失抛 ValueError（路由层转 400；AI 轨直接把文案返回给用户）：
    - 脚本行不存在 / 脚本文件缺失 → 步骤8 未完成
    - mapping 为空 → 步骤5 未完成（配对没确认，合成出来全是旁白音色，产物是错的）
    """
    row = await load_row(script_id)
    if not row:
        raise ValueError("有声书脚本行不存在")
    if not row["script_path"] or not Path(row["script_path"]).is_file():
        raise ValueError("脚本文件不存在，请先完成步骤8（生成脚本）")

    # mapping 列是步骤5确认后的最终版（重合成只认它）；旧数据兜底读 payload 缓存
    mapping_raw = row["mapping"] or row["payload"].get("mapping_preview")
    if not mapping_raw:
        raise ValueError("没有配对结果，请先完成步骤5（人物配对连线）")
    mapping_data = json.loads(mapping_raw) if isinstance(mapping_raw, str) else mapping_raw
    mapping = MappingTable.model_validate(mapping_data)

    script = AudioScript.model_validate(
        json.loads(Path(row["script_path"]).read_text(encoding="utf-8")))
    narrator_desc = (row["narrator_desc"] or "").strip()

    # mapping.entries → name2stage。IN 查询返回顺序不保证与 entries 一致、
    # 重复 stage_id 只回一行 → 不能 zip，按 id 索引后逐 entry 组装，音色才不会串角色
    stage_ids = [e.stage_id for e in mapping.entries if e.stage_id]
    async with AsyncSessionLocal() as db:
        stages = await get_stages_by_ids(db, stage_ids) if stage_ids else []
    stage_by_id = {s.id: s for s in stages}
    name2stage: dict = {}
    for e in mapping.entries:
        s = stage_by_id.get(e.stage_id)
        if s is None:
            continue
        name2stage[e.extracted_name] = SimpleNamespace(
            id=s.id,
            voice_path=s.voice_path or "",
            voice_description=s.voice_description or "",
            gender=s.gender or "中性",
            age_Description=s.age_Description or "成年",
            profile=s.profile or "",
            appearance_description=s.appearance_description or "",
        )
    # 「旁白」占位条目：intro/outro 与叙述段的音色来源（id=-1，回写时跳过）
    name2stage.setdefault("旁白", SimpleNamespace(
        id=-1, voice_path="", voice_description=narrator_desc,
        gender="中性", age_Description="成年",
        profile=narrator_desc, appearance_description=""))

    audio_bytes, warnings, voice_writes = await synthesize_audio_async(
        script, name2stage, on_wait=on_wait, on_progress=on_progress)

    # 旧成品先删（uuid 文件名，不清理会堆积），新 mp3 落在脚本文件旁
    if row["audio_path"]:
        Path(row["audio_path"]).unlink(missing_ok=True)
    out_path = Path(row["script_path"]).parent / f"audio_{uuid.uuid4().hex}.mp3"
    out_path.write_bytes(audio_bytes)

    async with AsyncSessionLocal() as db:
        for stage_id, wav_path in voice_writes:
            if stage_id < 0:  # 占位 stage（旁白）不回写
                continue
            await write_voice_path(db, stage_id, wav_path)
        await write_audio_done(db, script_id, str(out_path), warnings)
        await db.commit()

    return {"audio_path": str(out_path), "warnings": warnings}
