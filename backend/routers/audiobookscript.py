import asyncio
import io
import json
import mimetypes
from pathlib import Path as FilePath
from typing import Dict, List, Tuple

import soundfile as sf
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette import EventSourceResponse
from starlette.responses import FileResponse, Response

from config.db_conf import get_db
from config.store import conf
from crud import AudioBookScript, Chapter, Resource
from schemas.AudioBookScript import (
    AudioBookScriptCreate,
    AudioBookScriptDetail,
    AudioBookScriptUpdate, PanelCreateBody, PanelNameBody, PanelProposalConfirmBody, PanelMappingConfirmBody,
    PanelAudiosBody, PanelNarratorBody,
)
from utils.audiobook.llm import (
    LLMStepFailed,
    llm_draft,
    llm_extract,
    llm_map,
    llm_script,
)
from utils.audiobook.persist import (
    apply_proposal,
    apply_voice_supplements,
    assemble_catalog,
    build_character_cards,
    ensure_draft,
    load_stage,
    read_panel_state,
    save_stage,
    write_audio_mapping,
    write_mapping,
    write_name,
    write_narrator,
    write_script_artifacts, NARRATOR_SAMPLE_DEFAULT,
)
from utils.audiobook.schemas import (
    ChapterCharacterExtraction,
    MappingTable,
    NewCharacterProposal,
    strip_alias_decor,
)
from utils.audiobook.synthesize import finalize_audio
from utils.common import (
    generate_script_name,
    read_json_file,
    remove_file,
    remove_files,
    save_json_file,
)
from utils.voicegenerator import VoiceGenerator, probe_device

router = APIRouter(prefix="/autostory/audiobookscript", tags=["audiobookscript"])



# ══════════════ 旁白试听缓存（不落盘，仅内存；key = (声音描述, 试听文本)）══════════════

NARRATOR_PREVIEW_CACHE: Dict[Tuple[str, str], bytes] = {}
NARRATOR_PREVIEW_CACHE_LIMIT = 8
# 正在生成的试听任务（key → asyncio.Task）：同 key 复用同一任务，客户端断开不中止生成
NARRATOR_PREVIEW_TASKS: Dict[Tuple[str, str], "asyncio.Task[bytes]"] = {}


def _synthesize_narrator_wav(voice_desc: str, sample_text: str) -> bytes:
    """同步合成试听音频并序列化为 wav 字节（executor 中执行）"""
    device = probe_device("voice_design")
    gen = VoiceGenerator(device=device)
    try:
        wavs, sr = gen.design_voice(voice_desc, sample_text)
    finally:
        gen.release()
    if not wavs:
        raise ValueError("TTS 未返回音频")
    buf = io.BytesIO()
    sf.write(buf, wavs[0], sr, format="WAV")
    return buf.getvalue()


async def _run_narrator_preview_task(key: Tuple[str, str]) -> bytes:
    """试听生成任务（asyncio.Task，独立于请求生命周期）：完成后自行写缓存并移出任务表
    ——即使所有等待的请求都断开，生成也照常收尾，之后的同 key 请求直接命中缓存。
    经全局 GPU 闸放行：试听走 voice_design（~4.2GB），与有声书合成、角色音色设计
    共用同一把闸、统一排队。闸只加在此异步入口，_synthesize_narrator_wav 内部的
    probe_device 保持不变（探真实空闲显存、兜外部占用），不与本闸嵌套。"""
    try:
        from utils.gpu_gate import gpu_gate, VRAM_TTS

        loop = asyncio.get_running_loop()
        async with gpu_gate.reserve(VRAM_TTS):
            audio = await loop.run_in_executor(
                None, _synthesize_narrator_wav, key[0], key[1])
        NARRATOR_PREVIEW_CACHE[key] = audio
        while len(NARRATOR_PREVIEW_CACHE) > NARRATOR_PREVIEW_CACHE_LIMIT:
            NARRATOR_PREVIEW_CACHE.pop(next(iter(NARRATOR_PREVIEW_CACHE)))
        return audio
    finally:
        # 同步摘除即可：pop 出的是本任务自己，await 它 = "Task cannot await on itself"
        NARRATOR_PREVIEW_TASKS.pop(key, None)


async def _get_or_create_narrator_audio(key: Tuple[str, str]) -> bytes:
    """试听音频获取（缓存 + 任务复用）：缓存命中直接返回；同 key 已有生成任务挂上去等；
    都没有才创建任务。客户端断开只是放弃等待，任务继续跑完并落缓存。"""
    audio = NARRATOR_PREVIEW_CACHE.get(key)
    if audio is not None:
        return audio
    task = NARRATOR_PREVIEW_TASKS.get(key)
    if task is None:
        task = asyncio.get_running_loop().create_task(_run_narrator_preview_task(key))
        NARRATOR_PREVIEW_TASKS[key] = task
        # 所有等待者都断开时替任务消化异常，避免 "exception was never retrieved" 警告
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
    return await task


# ══════════════ 小工具 ══════════════

async def _get_row_or_404(db: AsyncSession, script_id: int):
    row = await AudioBookScript.get_script_by_id(db, script_id)
    if not row:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return row


async def _get_chapter_or_400(db: AsyncSession, chapter_id: int):
    chapter = await Chapter.get_chapter_by_id(db, chapter_id)
    if not chapter:
        raise HTTPException(status_code=400, detail="章节不存在")
    return chapter


# ══════════════ 步骤1：选章节建行 / 全局状态 ══════════════

@router.post("/panel/create")
async def panel_create(body: PanelCreateBody, db: AsyncSession = Depends(get_db)):
    """面板入口：为章节建/复用脚本行。同章已有未完成行则复用（resumed=True），
    已完成（audio_path 非空）的行不复用——再发起是一次新成品。"""
    chapter = await Chapter.get_chapter_by_id(db, body.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    script_id, resumed = await ensure_draft(body.project_id, body.chapter_id)
    if not script_id:
        raise HTTPException(status_code=400, detail="建行失败")
    try:
        state = await read_panel_state(db, script_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"data": {"script_id": script_id, "resumed": resumed, **state}}


@router.get("/panel/{script_id}/state")
async def panel_state(script_id: int = Path(..., description="脚本id"),
                      db: AsyncSession = Depends(get_db)):
    """面板恢复：前端拿 step/stage 直接跳到对应步骤页；各步产物一并带回。"""
    try:
        state = await read_panel_state(db, script_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"data": state}


# ══════════════ 步骤2：命名 ══════════════

@router.put("/panel/{script_id}/name")
async def panel_set_name(script_id: int, body: PanelNameBody,
                         db: AsyncSession = Depends(get_db)):
    await _get_row_or_404(db, script_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名称不能为空")
    await write_name(db, script_id, name)  # 同时在 payload 记 named 标记
    await db.commit()
    return {"data": {"Resp": "ok", "name": name}}


# ══════════════ 步骤3：提取出场人物 ══════════════

@router.post("/panel/{script_id}/extract")
async def panel_extract(script_id: int,
                        refresh: bool = Query(False, description="True 强制重新提取（重烧 LLM）"),
                        db: AsyncSession = Depends(get_db)):
    """通读本章提取出场人物。结果只进 payload 缓存层（供 4/5 与 AI 续跑复用），
    没有正式字段——mapping 空时本步总可重做。默认命中缓存直接返回。"""
    row = await _get_row_or_404(db, script_id)
    payload = await load_stage(db, script_id)
    if payload.get("extraction") and not refresh:
        return {"data": {"characters": payload["extraction"].get("characters", []), "cached": True}}
    chapter = await _get_chapter_or_400(db, row.chapter_id)
    if not (chapter.chapter_content or "").strip():
        raise HTTPException(status_code=400, detail="章节正文为空，无法提取角色")
    try:
        extraction = await llm_extract(chapter.chapter_title, chapter.chapter_content or "")
    except LLMStepFailed as e:
        raise HTTPException(status_code=502, detail=f"角色提取失败：{e}")
    dump = extraction.model_dump()
    await save_stage(db, script_id, "extraction", dump)
    await db.commit()
    return {"data": {"characters": dump["characters"], "cached": False}}


# ══════════════ 步骤4：新建提案（生成 / 确认落库）══════════════

async def _load_extraction_or_400(db: AsyncSession, script_id: int) -> ChapterCharacterExtraction:
    payload = await load_stage(db, script_id)
    if not payload.get("extraction"):
        raise HTTPException(status_code=400, detail="尚未提取出场人物，请先完成步骤3")
    return ChapterCharacterExtraction.model_validate(payload["extraction"])


@router.post("/panel/{script_id}/proposal")
async def panel_proposal(script_id: int,
                         refresh: bool = Query(False, description="True 强制重新生成"),
                         db: AsyncSession = Depends(get_db)):
    """比对角色库生成新建提案（LLM 预填）。命中 payload 缓存直接返回；
    重新生成会把 proposal_confirmed 置回 False（新提案需重新确认）。"""
    row = await _get_row_or_404(db, script_id)
    payload = await load_stage(db, script_id)
    if payload.get("proposal") and not refresh:
        return {"data": {"proposal": payload["proposal"], "cached": True}}
    extraction = await _load_extraction_or_400(db, script_id)
    chapter = await _get_chapter_or_400(db, row.chapter_id)
    catalog = await assemble_catalog(db, row.project_id, chapter.chapter_index)
    try:
        proposal = await llm_draft(chapter.chapter_index, catalog, extraction.characters)
    except LLMStepFailed as e:
        raise HTTPException(status_code=502, detail=f"提案生成失败：{e}")
    dump = proposal.model_dump()
    await save_stage(db, script_id, "proposal", dump)
    await save_stage(db, script_id, "proposal_confirmed", False)
    await db.commit()
    return {"data": {"proposal": dump, "cached": False}}


@router.post("/panel/{script_id}/proposal/confirm")
async def panel_proposal_confirm(script_id: int, body: PanelProposalConfirmBody,
                                 db: AsyncSession = Depends(get_db)):
    """提案确认：新建角色/阶段/关联落角色库，补音色描述写回 characterstage。
    幂等保护：已确认过再提交会 400（重做请先 /proposal?refresh=true 重新生成）。"""
    row = await _get_row_or_404(db, script_id)
    payload = await load_stage(db, script_id)
    if payload.get("proposal_confirmed"):
        raise HTTPException(status_code=400, detail="提案已确认过，请勿重复提交（重做请先重新生成提案）")
    proposal = NewCharacterProposal.model_validate(body.proposal)
    created = await apply_proposal(db, row.project_id, proposal)
    supplemented = await apply_voice_supplements(db, proposal.voice_supplements)
    # 确认版（可能被前端改过）回写 payload：AI 续跑拿到的是确认版，不再弹提案卡
    await save_stage(db, script_id, "proposal", proposal.model_dump())
    await save_stage(db, script_id, "proposal_confirmed", True)
    await db.commit()
    return {"data": {"created": created, "supplemented": supplemented}}


# ══════════════ 步骤5：人物 ↔ 角色阶段配对连线 ══════════════

@router.get("/panel/{script_id}/catalog")
async def panel_catalog(script_id: int, db: AsyncSession = Depends(get_db)):
    """库内本章可用角色阶段清单（连线 UI 的右侧列）。纯 DB 查询，不烧 LLM。"""
    row = await _get_row_or_404(db, script_id)
    chapter = await _get_chapter_or_400(db, row.chapter_id)
    catalog = await assemble_catalog(db, row.project_id, chapter.chapter_index)
    return {"data": {"catalog": catalog}}


@router.post("/panel/{script_id}/mapping/suggest")
async def panel_mapping_suggest(script_id: int,
                                refresh: bool = Query(False, description="True 强制重新预填"),
                                db: AsyncSession = Depends(get_db)):
    """LLM 预填映射表（连线 UI 的默认连线）。命中缓存直接返回。"""
    row = await _get_row_or_404(db, script_id)
    payload = await load_stage(db, script_id)
    if payload.get("mapping_preview") and not refresh:
        return {"data": {"mapping": payload["mapping_preview"], "cached": True}}
    extraction = await _load_extraction_or_400(db, script_id)
    chapter = await _get_chapter_or_400(db, row.chapter_id)
    catalog = await assemble_catalog(db, row.project_id, chapter.chapter_index)
    try:
        table = await llm_map(catalog, extraction.characters)
    except LLMStepFailed as e:
        raise HTTPException(status_code=502, detail=f"映射预填失败：{e}")
    dump = table.model_dump()
    await save_stage(db, script_id, "mapping_preview", dump)
    await db.commit()
    return {"data": {"mapping": dump, "catalog": catalog, "cached": False}}


@router.put("/panel/{script_id}/mapping")
async def panel_mapping_confirm(script_id: int, body: PanelMappingConfirmBody,
                                db: AsyncSession = Depends(get_db)):
    """步骤5确认：连线结果落 mapping 列（恢复判定锚点——重合成/续跑只认它）。
    覆盖检查：步骤3提取出的每个角色都必须有连线，否则合成时该角色退化为旁白音色。"""
    await _get_row_or_404(db, script_id)
    if not body.entries:
        raise HTTPException(status_code=400, detail="连线为空，请先完成配对")
    table = MappingTable.model_validate({"entries": body.entries})
    payload = await load_stage(db, script_id)
    if payload.get("extraction"):
        extracted_names = {strip_alias_decor(c["name"]) for c in payload["extraction"].get("characters", [])}
        mapped_names = {strip_alias_decor(e.get("extracted_name", "")) for e in body.entries}
        missing = sorted(extracted_names - mapped_names)
        if missing:
            raise HTTPException(status_code=400, detail=f"还有角色未配对：{missing}")
    await write_mapping(db, script_id, table)  # 落正式列
    await save_stage(db, script_id, "mapping_preview", table.model_dump())  # 留渲染镜像
    await db.commit()
    return {"data": {"Resp": "ok"}}


# ══════════════ 步骤6：已有音频 ↔ 有声书映射（AudioBookScripAudio）══════════════

@router.get("/panel/{script_id}/audios")
async def panel_get_audios(script_id: int, db: AsyncSession = Depends(get_db)):
    """当前脚本已映射的音频资源明细（候选清单走资源管理路由的分页接口）。"""
    await _get_row_or_404(db, script_id)
    audio_ids = await AudioBookScript.get_audio_ids_by_script(db, script_id)
    resources = await Resource.get_resource_by_ids(db, audio_ids) if audio_ids else []
    return {"data": {
        "audio_ids": audio_ids,
        "resources": [
            {"id": r.id, "name": r.Audio_name, "type": r.audio_type,
             "description": r.description or "", "path": r.path}
            for r in resources
        ],
    }}


@router.put("/panel/{script_id}/audios")
async def panel_set_audios(script_id: int, body: PanelAudiosBody,
                           db: AsyncSession = Depends(get_db)):
    """整体替换脚本↔音频映射（幂等，先清后插去重保序）。可重复调用重选。"""
    await _get_row_or_404(db, script_id)
    ids = await write_audio_mapping(db, script_id, body.audio_ids)
    await db.commit()
    return {"data": {"audio_ids": ids}}


# ══════════════ 步骤7：旁白音色 ══════════════

@router.put("/panel/{script_id}/narrator")
async def panel_set_narrator(script_id: int, body: PanelNarratorBody,
                             db: AsyncSession = Depends(get_db)):
    """旁白确认：音色描述 + 试听文本一起落库。narrator_text 是试听缓存 key 的另一半，
    必须与前端调 /narrator_preview 生成试听时传的文本一致，get_narrator_preview 才查得到。"""
    await _get_row_or_404(db, script_id)
    desc = body.narrator_desc.strip()
    if not desc:
        raise HTTPException(status_code=400, detail="旁白音色描述不能为空")
    text = body.narrator_text.strip() or NARRATOR_SAMPLE_DEFAULT
    await write_narrator(db, script_id, desc, text)
    await db.commit()
    return {"data": {"Resp": "ok"}}


@router.post("/narrator_preview")
async def narrator_preview(
    voice_desc: str = Body(..., embed=True, description="旁白声音描述"),
    sample_text: str = Body(..., embed=True, description="试听文本"),
):
    """旁白试听生成：按声音描述把试听文本合成一段音频。
    不落盘，仅内存缓存（key = 声音描述 + 试听文本）；同 key 生成中复用同一任务
    （客户端断开不中止，再点不重复生成）。经全局 GPU 闸排队放行。"""
    desc = voice_desc.strip()
    text = sample_text.strip()
    if not desc:
        raise HTTPException(status_code=400, detail="声音描述不能为空")
    if not text:
        raise HTTPException(status_code=400, detail="试听文本不能为空")
    key = (desc, text)
    try:
        audio = await _get_or_create_narrator_audio(key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"旁白试听生成失败: {e}")
    return Response(content=audio, media_type="audio/wav")


@router.post("/get_narrator_preview")
async def get_narrator_preview(
    script_id: int = Body(..., embed=True, description="脚本id"),
    db: AsyncSession = Depends(get_db),
):
    """旁白试听查询（纯查，绝不触发生成）：
    表里 narrator_desc 空 → 步骤7未完成，没有；非空 → 按 (narrator_desc, narrator_text)
    查缓存；缓存 miss（没试听过/服务重启过）→ 没有。"""
    row = await _get_row_or_404(db, script_id)
    desc = (row.narrator_desc or "").strip()
    if not desc:
        raise HTTPException(status_code=404, detail="该脚本尚未确认旁白音色（步骤7）")
    text = (row.narrator_text or "").strip() or NARRATOR_SAMPLE_DEFAULT
    audio = NARRATOR_PREVIEW_CACHE.get((desc, text))
    if audio is None:
        raise HTTPException(status_code=404,
                            detail="旁白试听缓存不存在（未试听过或服务已重启），请先调 /narrator_preview 生成")
    return Response(content=audio, media_type="audio/wav")


# ══════════════ 步骤8：生成本章有声书脚本 ══════════════

@router.post("/panel/{script_id}/script")
async def panel_gen_script(script_id: int, db: AsyncSession = Depends(get_db)):
    """凭 mapping 列 + 已映射音频 + 章节正文 → llm_script → 脚本落盘 + script_path。
    可重复调用重新生成（旧脚本文件自动清理）。前置：步骤5（mapping 列非空）。"""
    row = await _get_row_or_404(db, script_id)
    if not (row.mapping or "").strip():
        raise HTTPException(status_code=400, detail="尚未完成人物配对（步骤5），无法生成脚本")
    mapping = MappingTable.model_validate(json.loads(row.mapping))
    chapter = await _get_chapter_or_400(db, row.chapter_id)
    if not (chapter.chapter_content or "").strip():
        raise HTTPException(status_code=400, detail="章节正文为空，无法生成脚本")
    cards = await build_character_cards(db, mapping)
    audio_ids = await AudioBookScript.get_audio_ids_by_script(db, script_id)
    resources = await Resource.get_resource_by_ids(db, audio_ids) if audio_ids else []
    audio_catalog = [
        {"id": r.id, "type": r.audio_type, "name": r.Audio_name, "description": r.description or ""}
        for r in resources
    ]
    try:
        script = await llm_script(chapter.chapter_title, chapter.chapter_content or "",
                                  cards, audio_catalog)
    except LLMStepFailed as e:
        raise HTTPException(status_code=502, detail=f"脚本生成失败：{e}")
    path = await write_script_artifacts(db, script_id, script)
    await db.commit()
    segs = script.segments
    overview = {
        "segments": len(segs),
        "speakers": sorted({s.speaker or "" for s in segs}),
        "bgm": len(script.bgm_tracks),
        "sfx": len(script.sfx_tracks),
        "warnings": script.metadata.warnings,
    }
    return {"data": {"script_path": path, "overview": overview}}


# ══════════════ 步骤9：合成最终音频（首次/重合成同一入口，SSE 进度流）══════════════

class _SynthTask:
    """一路合成的事件流：append-only 事件历史，订阅者按下标回放 + 事件唤醒。

    事件只在事件循环线程追加（on_wait 直接调用，on_progress 经 call_soon_threadsafe
    桥回循环线程），无锁安全；订阅者断开即弃，合成任务本身不受影响。"""

    def __init__(self, script_id: int):
        self.script_id = script_id
        self.events: list[dict] = []
        self.finished = False
        self._wakeups: set[asyncio.Event] = set()

    def emit(self, ev: dict) -> None:
        self.events.append(ev)
        for flag in self._wakeups:
            flag.set()

    def finish(self, ev: dict) -> None:
        self.events.append(ev)
        self.finished = True
        for flag in self._wakeups:
            flag.set()

    async def subscribe(self):
        """产出全部事件直到收尾（done/error）。clear 先于重查下标：append 与
        唤醒之间的窗口不会漏事件（唤醒旗标被清后，重查 len 仍能看到新事件）"""
        idx, wake = 0, asyncio.Event()
        self._wakeups.add(wake)
        try:
            while True:
                wake.clear()
                while idx < len(self.events):
                    yield self.events[idx]
                    idx += 1
                if self.finished:
                    return
                await wake.wait()
        finally:
            self._wakeups.discard(wake)


_SYNTH_TASKS: dict[int, _SynthTask] = {}   # script_id → 在跑的合成任务
_SYNTH_BG: set[asyncio.Task] = set()       # 后台任务强引用（防 GC 中途回收）


async def _run_synth(task: _SynthTask) -> None:
    """后台合成任务：跑完（成/败）发收尾事件并从注册表摘除——之后再来就是新的幂等重合成"""
    try:
        result = await finalize_audio(
            task.script_id,
            on_wait=lambda: task.emit({"type": "queued"}),
            on_progress=lambda done, total, phase:
                task.emit({"type": "progress", "done": done, "total": total, "phase": phase}),
        )
        task.finish({"type": "done", **result})
    except Exception as e:
        task.finish({"type": "error", "detail": str(e)})
    finally:
        _SYNTH_TASKS.pop(task.script_id, None)


@router.get("/panel/{script_id}/synthesize/stream")
async def panel_synthesize_stream(script_id: int = Path(..., description="脚本id")):
    """凭行上正式产物（script_path + mapping + narrator_desc）直出成品音频。
    面板首次合成、重合成同一入口（幂等，覆盖旧成品）；AI 轨合成走 finalize_audio 直调。

    SSE 事件流（EventSourceResponse 自带 15s ping 保活）：
    - queued：GPU 忙需排队（would_wait 预判，阻塞前发一次）
    - progress：分段进度 {done, total, phase}（phase ∈ resolve/plain/emotional/mix）
    - done：{audio_path, warnings} 成品落库
    - error：{detail} 失败真因

    同一 script 至多一路在跑：已有在跑的 → 本次连接附着回放续看，绝不并发二跑；
    客户端断开只断 SSE，后台任务继续跑完落库，重进面板再点「合成」即从头回放进度。"""
    task = _SYNTH_TASKS.get(script_id)
    if task is None:
        task = _SynthTask(script_id)
        _SYNTH_TASKS[script_id] = task
        bg = asyncio.create_task(_run_synth(task))
        _SYNTH_BG.add(bg)
        bg.add_done_callback(_SYNTH_BG.discard)

    async def gen():
        async for ev in task.subscribe():
            yield {"data": json.dumps(ev, ensure_ascii=False)}

    return EventSourceResponse(gen())


# ══════════════ 脚本 CRUD（保留接口）══════════════

@router.post("/new")
async def new_script(audiobookscriptcreate: AudioBookScriptCreate,
                     db: AsyncSession = Depends(get_db)):
    """旧入口保留：直接建一行（不建空脚本文件——script_path 必须留空，
    否则恢复判定会误判为"脚本已生成"；步骤8 生成时才落文件）。面板请用 /panel/create。"""
    chapter = await Chapter.get_chapter_by_id(db, audiobookscriptcreate.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    row = await AudioBookScript.add_audio_book_script(
        db=db,
        name=audiobookscriptcreate.name,
        project_id=audiobookscriptcreate.project_id,
        chapter_id=audiobookscriptcreate.chapter_id,
        script_path="",
        audio_path="",
    )
    return {"data": {"Resp": "创建成功", "script_id": row.id}}


@router.post("/copy/{script_id}")
async def copy_script(script_id: int = Path(..., description="脚本ID"),
                      db: AsyncSession = Depends(get_db)):
    """复制脚本：脚本文件 + mapping + 旁白描述一并复制，audio_path 留空
    ——副本可独立走步骤9重合成（换旁白/换音频映射后出不同成品），不必重走 3-8。"""
    source = await _get_row_or_404(db, script_id)
    script_content = {}
    if source.script_path and FilePath(source.script_path).is_file():
        script_content = await read_json_file(FilePath(source.script_path))
    new_path = conf.SCRIPT_DIR / f"chapter_{source.chapter_id}" / generate_script_name()
    await save_json_file(new_path, script_content)
    row = await AudioBookScript.add_audio_book_script(
        db=db,
        name=f"{source.name}_副本",
        project_id=source.project_id,
        chapter_id=source.chapter_id,
        script_path=str(new_path),
        audio_path="",
    )
    await AudioBookScript.update_script(db, row.id, {
        "mapping": source.mapping or "",
        "narrator_desc": source.narrator_desc or "",
        "narrator_text": source.narrator_text or "",
    })
    await db.commit()
    return {"data": {"Resp": "脚本复制成功", "script_id": row.id}}


@router.put("/script/{script_id}")
async def update_script_content(
    script_id: int = Path(..., description="脚本ID"),
    payload: AudioBookScriptUpdate = Body(..., description="脚本名与编排内容"),
    db: AsyncSession = Depends(get_db),
):
    """人工改脚本：更新脚本名并覆写编排 JSON 文件（步骤8 产物的人工修正通道）"""
    script = await _get_row_or_404(db, script_id)
    if not payload.name or not payload.name.strip():
        raise HTTPException(status_code=400, detail="脚本名不能为空")
    if script.script_path:
        await save_json_file(FilePath(script.script_path), payload.script_content)
        await AudioBookScript.update_script(db, script_id, {"name": payload.name.strip()})
    else:
        # 尚无脚本文件（步骤8 未跑过的人工建行）时落新文件并锚 script_path
        file_path = conf.SCRIPT_DIR / f"chapter_{script.chapter_id}" / generate_script_name()
        await save_json_file(file_path, payload.script_content)
        await AudioBookScript.update_script(
            db, script_id, {"name": payload.name.strip(), "script_path": str(file_path)})
    await db.commit()
    return {"data": {"Resp": "保存成功"}}


@router.get("/project_scripts")
async def get_project_scripts(
    project_id: int = Query(..., description="项目ID"),
    page: int = Query(1, gt=0),
    pagesize: int = Query(100, gt=0),
    db: AsyncSession = Depends(get_db),
):
    """获取项目下全部章节的脚本列表（有声书全局管理视图，跨章节）"""
    offset = (page - 1) * pagesize
    scripts, total = await AudioBookScript.get_scripts_by_project(db, project_id, offset, pagesize)
    has_more = (offset + len(scripts)) < total
    return {"data": {
        "List": [AudioBookScriptDetail.model_validate(s) for s in scripts],
        "Total": total,
        "More": has_more,
    }}


@router.get("/scripts")
async def get_scripts(
    chapter_id: int = Query(..., description="章节ID"),
    page: int = Query(1, gt=0),
    pagesize: int = Query(10, gt=0),
    db: AsyncSession = Depends(get_db),
):
    """获取指定章节的脚本列表"""
    offset = (page - 1) * pagesize
    scripts, total = await AudioBookScript.get_scripts_by_chapter(db, chapter_id, offset, pagesize)
    has_more = (offset + len(scripts)) < total
    return {"data": {
        "List": [AudioBookScriptDetail.model_validate(s) for s in scripts],
        "Total": total,
        "More": has_more,
    }}


@router.get("/script/{script_id}/content")
async def get_script_content(script_id: int = Path(..., description="脚本ID"),
                             db: AsyncSession = Depends(get_db)):
    """读取脚本 JSON 内容（步骤8 产物，供前端预览与编辑）"""
    script = await _get_row_or_404(db, script_id)
    if not script.script_path or not FilePath(script.script_path).is_file():
        raise HTTPException(status_code=404, detail="脚本文件不存在")
    content = await read_json_file(FilePath(script.script_path))
    return {"data": {"Content": content}}


@router.get("/audio/{script_id}")
async def get_script_audio(script_id: int = Path(..., description="脚本ID"),
                           db: AsyncSession = Depends(get_db)):
    """流式返回成品音频（供前端 <audio> 播放，支持 Range 拖动进度）"""
    script = await _get_row_or_404(db, script_id)
    if not script.audio_path or not FilePath(script.audio_path).is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在")
    file_path = FilePath(script.audio_path)
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type=mimetypes.guess_type(file_path.name)[0] or "audio/mpeg",
    )


@router.delete("/audio/{script_id}")
async def delete_audio_only(script_id: int = Path(..., description="脚本ID"),
                            db: AsyncSession = Depends(get_db)):
    """删除成品音频文件并清空 audio_path（脚本记录保留；audio_path 清空后
    恢复判定自动退回步骤9待合成态）"""
    script = await _get_row_or_404(db, script_id)
    if script.audio_path:
        await remove_file(script.audio_path)
    await AudioBookScript.update_script(db, script_id, {"audio_path": ""})
    await db.commit()
    return {"data": {"Resp": "音频删除成功"}}


@router.delete("/script/{script_id}")
async def delete_script(script_id: int = Path(..., description="脚本ID"),
                        db: AsyncSession = Depends(get_db)):
    """删除单个脚本（级联删音频映射行 + 物理文件）"""
    script = await _get_row_or_404(db, script_id)
    await AudioBookScript.delete_audio_book_script(db, script_id)
    if script.script_path:
        await remove_file(script.script_path)
    if script.audio_path:
        await remove_file(script.audio_path)
    return {"data": {"Resp": "删除成功"}}


@router.delete("/scripts")
async def delete_scripts(scripts_ids: List[int] = Query(..., description="脚本ID列表"),
                         db: AsyncSession = Depends(get_db)):
    """批量删除脚本（按脚本 id；级联删映射行 + 物理文件。
    FIX: 原实现 description 写成"章节ID列表"，实际行为一直是脚本 id，按行为修正注释）"""
    paths = await AudioBookScript.get_paths_by_script_ids(db, scripts_ids)
    scripts_path, audios_path = [], []
    for script_path, audio_path in paths:
        if script_path:
            scripts_path.append(script_path)
        if audio_path:
            audios_path.append(audio_path)
    await AudioBookScript.delete_audio_book_scripts(db, scripts_ids)
    await remove_files(scripts_path)
    await remove_files(audios_path)
    return {"data": {"Resp": "批量删除成功"}}
