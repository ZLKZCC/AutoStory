import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.AudioBookScript import AudioBookScript as AudioBookScriptModel
from config.db_conf import AsyncSessionLocal
from config.store import conf
from crud import AudioBookScript, Character, CharacterStage, Project
from crud.AudioBookScript import replace_script_audios
from crud.Chapter import get_chapter_by_id
from crud.Character import (
    get_characterid_by_project,
    get_characters_by_ids,
    get_character_stage_mappings,
)
from crud.CharacterStage import get_stages_by_ids
from utils.audiobook.schemas import (
    AudioScript,
    MappingTable,
    NewCharacterProposal,
    strip_alias_decor,
)


# ══════════════ payload 缓存层（stage_payload：AI 轨续跑省请求用） ══════════════
NARRATOR_SAMPLE_DEFAULT = "夜色渐深，风穿过山谷，故事从这里开始。"
def _load_payload(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def load_stage(db: AsyncSession, script_id: int) -> dict:
    """读 stage_payload（会话内）。"""
    row = await AudioBookScript.get_script_by_id(db, script_id)
    return _load_payload(row.stage_payload) if row else {}


async def merge_stage_payload(db: AsyncSession, script_id: int, patch: dict) -> None:
    """把 patch 合进 stage_payload（保留其它 key）。"""
    row = await AudioBookScript.get_script_by_id(db, script_id)
    if row is None:
        return
    payload = _load_payload(row.stage_payload)
    payload.update(patch)
    await AudioBookScript.update_script(db, script_id, {
        "stage_payload": json.dumps(payload, ensure_ascii=False, default=str),
    })


async def save_stage(db: AsyncSession, script_id: int, key: str, data) -> None:
    """单 key 便捷写入（= merge_stage_payload({key: data})）。"""
    await merge_stage_payload(db, script_id, {key: data})


async def load_stage_detached(script_id: int) -> dict:
    """脱离请求生命周期读 stage_payload（AI 轨 run_pipeline 用）。"""
    async with AsyncSessionLocal() as db:
        return await load_stage(db, script_id)


async def save_stage_detached(script_id: int, key: str, data) -> None:
    """脱离请求生命周期写 stage_payload（AI 轨 @task 内用，自带提交）。"""
    async with AsyncSessionLocal() as db:
        await save_stage(db, script_id, key, data)
        await db.commit()


# ══════════════ 行生命周期（步骤1） ══════════════

async def ensure_draft(project_id: int, chapter_id: int) -> tuple[int, bool]:
    """建/复用脚本行（面板步骤1、AI 新建轨共用）。返回 (script_id, resumed)。

    - 复用规则：同章最近一个「未完成」行（audio_path 为空）；
      有成品音频的行不复用——再发起是一次新成品。
    - resumed：该行是否已有进度（正式字段非空或 payload 非空）。
      AI 轨以它决定从头（先弹命名卡）还是 infer_resume 接断点；面板轨直接读 state。
    """
    async with AsyncSessionLocal() as db:
        chapter = await get_chapter_by_id(db, chapter_id)
        if chapter is None:
            return 0, False
        stmt = (
            select(AudioBookScriptModel)
            .where(AudioBookScriptModel.chapter_id == chapter_id,
                   AudioBookScriptModel.audio_path == "")
            .order_by(AudioBookScriptModel.id.desc())
            .limit(1)
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            progressed = bool(
                existing.mapping or existing.script_path
                or existing.narrator_desc or _load_payload(existing.stage_payload)
            )
            return existing.id, progressed
        row = await AudioBookScript.add_audio_book_script(
            db, f"{chapter.chapter_title}_有声书", project_id, chapter_id, "", "")
        return row.id, False


async def load_row(script_id: int) -> dict:
    """脚本行快照（脱离请求生命周期）：正式字段 + 映射音频 ids + payload。
    会话关闭后不碰 ORM 行；行不存在返回 {}。AI 轨与 finalize_audio 共用。"""
    async with AsyncSessionLocal() as db:
        row = await AudioBookScript.get_script_by_id(db, script_id)
        if row is None:
            return {}
        chapter = await get_chapter_by_id(db, row.chapter_id)
        audio_ids = await AudioBookScript.get_audio_ids_by_script(db, script_id)
        return {
            "id": row.id,
            "project_id": row.project_id,
            "chapter_id": row.chapter_id,
            "chapter_index": chapter.chapter_index if chapter else 0,
            "chapter_title": chapter.chapter_title if chapter else "",
            "name": row.name or "",
            "script_path": row.script_path or "",
            "audio_path": row.audio_path or "",
            "mapping": row.mapping or "",
            "narrator_desc": row.narrator_desc or "",
            "narrator_text": row.narrator_text or "",
            "audio_ids": list(audio_ids),
            "payload": _load_payload(row.stage_payload),
        }


# ══════════════ 正式字段写入（步骤 2/5/6/7/8/9） ══════════════

async def write_name(db: AsyncSession, script_id: int, name: str) -> None:
    """步骤2：命名确认。顺带在 payload 记 named 标记——ensure_draft 用它区分
    「只有默认名的半新行」和「全新行」，避免续跑时重问命名。"""
    await AudioBookScript.update_script(db, script_id, {"name": name})
    await merge_stage_payload(db, script_id, {"named": True})


async def write_mapping(db: AsyncSession, script_id: int, mapping: MappingTable) -> None:
    """步骤5：连线确认后的最终版落 mapping 列。
    重合成/恢复判定只认这里——不再等步骤8顺带回写（旧实现的断点洞）。"""
    await AudioBookScript.update_script(db, script_id, {
        "mapping": json.dumps(mapping.model_dump(), ensure_ascii=False),
    })


async def write_narrator(db: AsyncSession, script_id: int,
                         narrator_desc: str, narrator_text: str = "") -> None:
    """步骤7：旁白音色描述 + 试听文本一起落。
    narrator_text 是旁白试听缓存 key 的另一半（get_narrator_preview 按
    (narrator_desc, narrator_text) 查缓存），必须与生成试听时的文本一致。"""
    await AudioBookScript.update_script(db, script_id, {
        "narrator_desc": narrator_desc,
        "narrator_text": narrator_text,
    })


async def write_audio_mapping(db: AsyncSession, script_id: int, audio_ids) -> list[int]:
    """步骤6：脚本 ↔ 音频资源映射，整体替换、幂等；返回最终 id 列表（去重保序）。"""
    return await replace_script_audios(db, script_id, list(audio_ids or []))


async def read_audio_mapping(db: AsyncSession, script_id: int) -> list[int]:
    return await AudioBookScript.get_audio_ids_by_script(db, script_id)


async def write_script_artifacts(db: AsyncSession, script_id: int, script: AudioScript) -> str:
    """步骤8：脚本 JSON 落盘 + script_path + overview 进 payload。返回文件路径。
    重生成时旧脚本文件一并删（uuid 文件名，不清理会堆积）。
    mapping 不在这里写——步骤5确认时已落列。"""
    row = await AudioBookScript.get_script_by_id(db, script_id)
    if row is None:
        raise ValueError(f"脚本行 {script_id} 不存在")
    chapter_dir = conf.SCRIPT_DIR / f"chapter_{row.chapter_id}"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    file_path = chapter_dir / f"script_{uuid.uuid4().hex}.json"
    file_path.write_text(
        json.dumps(script.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    old = row.script_path
    await AudioBookScript.update_script(db, script_id, {"script_path": str(file_path)})
    await merge_stage_payload(db, script_id, {"script_overview": _script_overview(script)})
    if old and old != str(file_path):
        Path(old).unlink(missing_ok=True)  # 旧脚本文件清理（文件缺失不报错）
    return str(file_path)


async def write_audio_done(db: AsyncSession, script_id: int,
                           audio_path: str, warnings: list) -> None:
    """步骤9：成品音频路径 + warnings 进 payload（由 synthesize.finalize_audio 调）。"""
    await AudioBookScript.update_script(db, script_id, {"audio_path": audio_path})
    await merge_stage_payload(db, script_id, {"warnings": warnings or []})


def _script_overview(script: AudioScript) -> dict:
    segs = script.segments or []
    return {
        "segments": len(segs),
        "speakers": sorted({s.speaker or "" for s in segs}),
        "bgm": len(script.bgm_tracks or []),
        "sfx": len(script.sfx_tracks or []),
        "warnings": (script.metadata.warnings if script.metadata else []) or [],
    }


# ══════════════ 步骤4 确认落库（新建角色 + 补音色；两轨共用） ══════════════

async def apply_proposal(
    db: AsyncSession,
    project_id: int,
    proposal: NewCharacterProposal,
) -> list[dict]:
    """确认后的提案 → 落库。返回 [{character_id, stage_id, character_name}]（前端刷新用）。
    一个角色可能有多个阶段草稿——每个阶段独立建行。不 commit，由调用方统一提交。"""
    created = []
    for draft in proposal.new_characters:
        obj = await Character.add_character(
            db, draft.character_name, draft.gender, draft.role)
        await Project.add_project_character(db, project_id, obj.id)
        for stage in draft.stages:
            # 建阶段行：CharacterStage.add_character_stage，参数是阶段各字段
            st = await CharacterStage.add_character_stage(
                db, stage.stage_name, stage.alias_name, stage.gender,
                stage.chapter_index, stage.age_Description,
                stage.appearance_description, stage.profile,
                stage.voice_description,
                "",  # voice_path 空，步骤9 合成后回写
            )
            # 角色↔阶段关联落一行：Character.add_character_stage
            # 注意与上面同名方法区分：Character 下是"关联"，CharacterStage 下是"建行"
            await Character.add_character_stage(db, obj.id, st.id)
            created.append({
                "character_id": obj.id,
                "stage_id": st.id,
                "character_name": draft.character_name,
            })
    return created


async def apply_voice_supplements(db: AsyncSession, supplements) -> int:
    """把提案里为已有阶段补的 voice_description 写回 characterstage。
    只写非空描述、且 stage_id 有效的；返回实际写入条数。不 commit。"""
    n = 0
    for s in supplements or []:
        sid = getattr(s, "stage_id", None)
        desc = (getattr(s, "voice_description", "") or "").strip()
        if sid and desc:
            await CharacterStage.update_character_stage(db, sid, {"voice_description": desc})
            n += 1
    return n


# ══════════════ 步骤5 → 步骤8 角色卡组装 ══════════════

async def build_character_cards(db: AsyncSession, mapping: MappingTable) -> dict:
    """映射确认后 → 角色卡 {角色名: 阶段精要}。
    提取侧名字为准（AudioScript 的 speaker 就是这些名字），内容取被连线角色的设定字段。"""
    stage_ids = [e.stage_id for e in mapping.entries]
    stages = await get_stages_by_ids(db, stage_ids) if stage_ids else []
    stage_map = {s.id: s for s in stages}
    cards = {}
    for e in mapping.entries:
        s = stage_map.get(e.stage_id)
        if s is None:
            continue
        parts = []
        if s.age_Description:
            parts.append(s.age_Description[:60])
        if s.appearance_description:
            parts.append(s.appearance_description[:100])
        if s.profile:
            parts.append(s.profile[:100])
        if s.voice_description:
            parts.append(f"音色: {s.voice_description[:100]}")
        cards[strip_alias_decor(e.extracted_name)] = "；".join(parts) or "（无设定）"
    return cards


# ══════════════ 阶段清单组装（步骤 4/5 的 LLM 输入，两轨共用） ══════════════

async def assemble_catalog(db: AsyncSession, project_id: int, chapter_index: int) -> list:
    """库内本章可用角色阶段合集。
    chapter_index 是章节表 0-based 序号，stage.chapter_index 是 1-based「第几章」；
    换算成第几章再比，否则本章（尤其第 1 章 index=0）新建的阶段会被误过滤光。"""
    chapter_no = chapter_index + 1
    character_ids = await get_characterid_by_project(db, project_id)
    characters = await get_characters_by_ids(db, character_ids)
    name_of = {c.id: c.character_name for c in characters}
    mappings = await get_character_stage_mappings(db, character_ids)
    stage_ids = [m.characterstage_id for m in mappings]
    stages = await get_stages_by_ids(db, stage_ids) if stage_ids else []
    by_id = {s.id: s for s in stages}
    catalog = []
    for m in mappings:
        stage = by_id.get(m.characterstage_id)
        if stage is None or stage.chapter_index > chapter_no:
            continue
        catalog.append({
            "character_id": m.character_id,
            "character_name": name_of.get(m.character_id, "?"),
            "stage_id": stage.id,
            "stage_name": stage.stage_name,
            "chapter_index": stage.chapter_index,
            "profile": stage.profile or "",
            "voice_description": stage.voice_description or "",
        })
    return catalog


# ══════════════ 恢复推断（两轨共用的唯一判定） ══════════════

def infer_resume(row: dict, payload: dict | None = None) -> dict:
    """按正式字段反推恢复点。返回 {"step", "stage"}，step = 下一个该执行的步骤
    （编号 = 面板步骤：2 命名 3 提取 4 提案 5 配对 6 音频 7 旁白 8 脚本 9 合成）。

    - mapping 为空 ⇒ 步骤 3-5 必须重走（提取/提案没有正式字段可依）；
      stage_payload 里剩什么决定重走的起始子步：有 extraction → 从提案起，
      有 proposal 未确认 → 直接弹提案卡，proposal 已确认 → 直接进配对预填，
      有 mapping_preview → 直接弹配对卡，每种都少烧一截 LLM 请求。
    - stage_payload 缺失/损坏只影响"少烧请求"，不影响正确性：全部从头走也对。
    """
    payload = payload if payload is not None else (row.get("payload") or {})
    if (row.get("audio_path") or "").strip():
        return {"step": 9, "stage": "done"}
    if (row.get("script_path") or "").strip():
        return {"step": 9, "stage": "synthesize"}
    if (row.get("narrator_desc") or "").strip():
        return {"step": 8, "stage": "script"}
    if (row.get("mapping") or "").strip():
        return {"step": 6, "stage": "audio_mapping"}
    # ── mapping 为空：步骤 3-5 重走，按 payload 缓存决定起始子步 ──
    if payload.get("mapping_preview"):
        return {"step": 5, "stage": "mapping_confirm"}    # 预填已在：直接弹配对卡
    if payload.get("proposal_confirmed"):
        return {"step": 5, "stage": "mapping_generate"}   # 提案已确认：跳过提案步，直接进配对预填
    if payload.get("proposal"):
        return {"step": 4, "stage": "proposal_confirm"}   # 提案已生成未确认：直接弹提案卡
    if payload.get("extraction"):
        return {"step": 4, "stage": "proposal_generate"}  # 提取已在：跳过提取，直接出提案
    return {"step": 3, "stage": "extract"}


# ══════════════ 面板状态读取（routers 的 state 端点直接用） ══════════════

async def read_panel_state(db: AsyncSession, script_id: int) -> dict:
    """面板 9 步的当前状态：恢复点 + 各步产物，前端据此直接跳到对应步骤页。"""
    row = await AudioBookScript.get_script_by_id(db, script_id)
    if row is None:
        raise ValueError(f"脚本行 {script_id} 不存在")
    chapter = await get_chapter_by_id(db, row.chapter_id)
    payload = _load_payload(row.stage_payload)
    resume = infer_resume({
        "audio_path": row.audio_path,
        "script_path": row.script_path,
        "narrator_desc": row.narrator_desc,
        "mapping": row.mapping,
    }, payload)
    audio_ids = await AudioBookScript.get_audio_ids_by_script(db, script_id)
    return {
        "script_id": row.id,
        "project_id": row.project_id,
        "chapter_id": row.chapter_id,
        "chapter_index": chapter.chapter_index if chapter else 0,
        "chapter_title": chapter.chapter_title if chapter else "",
        "name": row.name or "",
        "step": resume["step"],
        "stage": resume["stage"],
        "done": bool((row.audio_path or "").strip()),
        "mapping": json.loads(row.mapping) if row.mapping else None,
        "mapping_preview": payload.get("mapping_preview"),
        "audio_ids": list(audio_ids),
        "narrator_desc": row.narrator_desc or "",
        "narrator_text": row.narrator_text or "",
        "script_path": row.script_path or "",
        "audio_path": row.audio_path or "",
        "extraction": payload.get("extraction"),
        "proposal": payload.get("proposal"),
        "warnings": payload.get("warnings") or [],
    }


# ══════════════ 步骤9 音色回写 ══════════════

async def write_voice_path(db: AsyncSession, stage_id: int, path: str) -> None:
    """合成中现设计的参考音固化到 characterstage.voice_path（下次复用免重设计）。"""
    await CharacterStage.update_character_stage(db, stage_id, {"voice_path": path})
