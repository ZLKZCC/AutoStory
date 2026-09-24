import json
from pathlib import Path

from langgraph.config import get_stream_writer
from langgraph.func import task

from agent.tools.approval import request_approval
from config.db_conf import AsyncSessionLocal
from crud.Chapter import get_chapter_by_id
from crud.Resource import get_resource_by_ids
from utils.audiobook.llm import LLMStepFailed, llm_draft, llm_extract, llm_map, llm_script
from utils.audiobook.persist import (
    NARRATOR_SAMPLE_DEFAULT,
    apply_proposal,
    apply_voice_supplements,
    assemble_catalog,
    build_character_cards,
    ensure_draft,
    infer_resume,
    load_row,
    load_stage_detached,
    save_stage,
    save_stage_detached,
    write_audio_mapping,
    write_mapping,
    write_name,
    write_narrator,
    write_script_artifacts,
)
from utils.audiobook.schemas import (
    AudioScript,
    ChapterCharacterExtraction,
    MappingTable,
    NewCharacterProposal,
)
from utils.audiobook.synthesize import finalize_audio

# 旁白音色预设（仅 agent 这条路给选项；向导/面板定位是手动填，不提供预设）
# label 是给用户点的短名，desc 是真正喂给 TTS 音色设计的描述文本
NARRATOR_VOICE_PRESETS = [
    {"label": "沉稳男声", "desc": "低沉平稳的中年男声，语速适中，适合正剧、悬疑旁白"},
    {"label": "温和女声", "desc": "柔和亲切的女声，语速偏慢，适合情感、日常向"},
    {"label": "清亮少年", "desc": "明快有活力的少年音，适合轻小说、冒险"},
    {"label": "沧桑老者", "desc": "沙哑缓慢的老年男声，适合历史、评书、寓言"},
    {"label": "冷静解说", "desc": "克制中性的解说腔，咬字清晰，适合科普、纪实"},
]


# ── 基础设施 ──────────────────────────────────────────────────────────────

def progress(phase: str, detail: str, call_id: str, **extra) -> None:
    """进度事件（custom 通道 → 卡片原地更新）。writer 同步调用；
    data["type"] 必带（信封类型从这里读，custom 流无事件名）。
    extra 透传 script_id / audio_path / warnings。"""
    writer = get_stream_writer()
    data = {"type": "audiobook_progress", "entity": "audiobook",
            "phase": phase, "detail": detail, "call_id": call_id}
    data.update(extra)
    writer(data)


def parse_answer(answer) -> tuple:
    """统一 answer 协议 → (decision, feedback, edited)。坏形状按放弃兜底。"""
    if not isinstance(answer, dict) or "approved" not in answer:
        return "abort", "", {}
    if answer.get("approved"):
        return "confirm", "", (answer.get("edited") or {})
    if answer.get("feedback"):
        return "feedback", str(answer["feedback"]), {}
    return "abort", "", {}


def done_text(audio_path: str, warnings: list) -> str:
    text = f"有声书已生成：{audio_path}"
    return text + (f"（警告 {len(warnings)} 条）" if warnings else "")


def read_script_file(script_path: str):
    """读脚本 JSON（不存在/坏文件返回 None，由调用方兜底）。"""
    if not script_path:
        return None
    try:
        return AudioScript.model_validate(
            json.loads(Path(script_path).read_text(encoding="utf-8")))
    except Exception:
        return None


# ── 人审卡 payload（entity=audiobook，前端渲成有声书审核卡）──────────────
# 协议词汇：subtype = naming/proposal/mapping/narrator/script（与 9 步架构、
# 前端 components/audiobook/types.ts 的 AudiobookSubtype 同源）。
# entity/call_id 属信封外层（行 type/extra 列）；业务数据（script_id 等）留在 payload。

def naming_gate(script_id: int, chapter_title: str, current: str, call_id: str) -> dict:
    """步骤2 命名卡：先定本次有声书的名字，再做后面的一切。"""
    return {
        "entity": "audiobook",
        "subtype": "naming",
        "call_id": call_id,
        "script_id": script_id,
        "summary": f"为章节「{chapter_title}」的有声书命名（将作为音频成品的名字）",
        "current": current or f"{chapter_title}_有声书",
    }


def proposal_gate(script_id: int, proposal: dict, catalog: list, call_id: str) -> dict:
    drafts = len(proposal.get("new_characters") or [])
    supplements = len(proposal.get("voice_supplements") or [])
    bits = []
    if drafts:
        bits.append(f"{drafts} 个还没建档的人物待确认新建")
    if supplements:
        bits.append(f"{supplements} 个已有角色缺音色描述、建议补上")
    return {
        "entity": "audiobook",
        "subtype": "proposal",
        "call_id": call_id,
        "script_id": script_id,
        "summary": "本章：" + "；".join(bits),
        "proposal": proposal,
        "stage_catalog": catalog,
    }


def mapping_gate(script_id: int, mapping: dict, catalog: list, summary: str, call_id: str) -> dict:
    return {
        "entity": "audiobook",
        "subtype": "mapping",
        "call_id": call_id,
        "script_id": script_id,
        "summary": summary,
        "mapping": mapping,
        "stage_catalog": catalog,
    }


def script_gate(script_id: int, script: AudioScript, call_id: str) -> dict:
    segments = script.segments or []
    speakers = sorted({s.speaker or "" for s in segments})
    return {
        "entity": "audiobook",
        "subtype": "script",
        "call_id": call_id,
        "script_id": script_id,
        "summary": f"已把本章改编成 {len(segments)} 段有声书脚本（{len(speakers)} 位说话人，"
                   f"BGM {len(script.bgm_tracks or [])} 轨），确认后开始合成",
        "script_overview": {
            "segments": len(segments),
            "speakers": speakers,
            "bgm": len(script.bgm_tracks or []),
            "sfx": len(script.sfx_tracks or []),
            "warnings": (script.metadata.warnings if script.metadata else []) or [],
        },
        "preview": [
            {"i": i, "speaker": s.speaker or "", "text": (s.text or "")[:40]}
            for i, s in enumerate(segments[:12])
        ],
    }


def narrator_gate(script_id: int, current: str, call_id: str) -> dict:
    return {
        "entity": "audiobook",
        "subtype": "narrator",
        "call_id": call_id,
        "script_id": script_id,
        "summary": "选择旁白（念叙述部分）的声音，可选预设或自己描述",
        "presets": NARRATOR_VOICE_PRESETS,
        "narrator_desc": current,
    }


# ── LLM 步骤的 @task 包装：LLM 生成 + 中间产物落库走 checkpoint ───────────
# resume 重放时已完成的 task 直接取回（不重跑 LLM、不重复落库）；
# 被打回（feedback）的那次是新 task 调用，才真正再走一遍 LLM。

@task
async def _extract_task(script_id: int, title: str, content: str) -> dict:
    extraction = await llm_extract(title, content)
    dump = extraction.model_dump()
    await save_stage_detached(script_id, "extraction", dump)
    return dump


@task
async def _proposal_task(script_id: int, chapter_index: int,
                         catalog: list, characters: list, feedback: str) -> dict:
    proposal_model = await llm_draft(chapter_index, catalog, characters)
    if feedback:
        merged = proposal_model.model_dump()
        merged["feedback_ack"] = feedback
        proposal_model = NewCharacterProposal.model_validate(merged)
    dump = proposal_model.model_dump()
    await save_stage_detached(script_id, "proposal", dump)
    return dump


@task
async def _mapping_task(script_id: int, catalog: list, characters: list, feedback: str) -> dict:
    mapping_model = await llm_map(catalog, characters)
    if feedback:
        merged = mapping_model.model_dump()
        merged["feedback_ack"] = feedback
        mapping_model = MappingTable.model_validate(merged)
    dump = mapping_model.model_dump()
    await save_stage_detached(script_id, "mapping_preview", dump)
    return dump


@task
async def _script_task(script_id: int, title: str, content: str,
                       mapping: MappingTable, cards: dict, audio_catalog: list) -> str:
    script = await llm_script(title, content, cards, audio_catalog)
    async with AsyncSessionLocal() as db:
        path = await write_script_artifacts(db, script_id, script)
        await db.commit()
    return path


# ── 驱动：一个大函数，步骤按序直排，恢复点由产物反推 ──────────────────────

async def run_pipeline(project_id: int, chapter_id: int | None = None,
                       audio_ids=None, narrator_desc: str = "",
                       call_id: str = "", script_id: int | None = None) -> str:
    """按序推进一次有声书流程，人审处停在 request_approval 等裁决。

    两个入口：
    - 新建轨：传 chapter_id（+ 可选 audio_ids / narrator_desc）；
      同章未完成行自动复用断点续跑，已完成行复用不到（ensure_draft 保证）。
    - 续跑轨：传 script_id（面板/AI 轨产物互认，正式字段非空即跳过）。
    """
    # ── 定位脚本行 ──────────────────────────────────────────────
    if script_id:
        row = await load_row(script_id)
        if not row:
            return f"有声书 {script_id} 不存在，无法继续"
    else:
        if not chapter_id:
            return "缺少 chapter_id 参数，未发起有声书"
        script_id, resumed = await ensure_draft(project_id, chapter_id)
        if not script_id:
            return f"章节 {chapter_id} 不存在，未发起有声书"
        row = await load_row(script_id)
        if not row:
            return "有声书脚本行已不存在，流程中止"

    # ── 完成品短路：再调一次只报成品（重合成走面板 /panel/{id}/synthesize）──
    if (row["audio_path"] or "").strip():
        return done_text(row["audio_path"], row["payload"].get("warnings") or [])

    payload = row["payload"]
    chapter_index = row["chapter_index"]
    resume = infer_resume(row, payload)
    # 命名未确认（named 标记缺失）→ 先补命名卡；面板命过名的行自动跳过
    step = 2 if not payload.get("named") else resume["step"]
    progress("prepare",
             f"有声书「{row['name']}」流程就绪（从步骤{step}开始）" if step != 2
             else f"有声书「{row['name']}」流程就绪，请先命名",
             call_id)

    # ── 步骤2：命名 ────────────────────────────────────────────
    if step <= 2:
        title = row["chapter_title"] or f"第 {chapter_index + 1} 章"
        progress("naming", "请为本次有声书命名", call_id)
        answer = request_approval(naming_gate(script_id, title, row["name"], call_id))
        decision, _fb, edited = parse_answer(answer)
        if decision == "abort":
            return "用户放弃有声书流程"
        name = str(edited.get("name") or row["name"] or f"{title}_有声书").strip()
        async with AsyncSessionLocal() as db:
            await write_name(db, script_id, name)  # 落 name + payload.named 标记
            await db.commit()
        row["name"] = name
        payload["named"] = True
        progress("naming", f"本次有声书定名：{name}", call_id)
        step = resume["step"]  # 续跑行可能已推进到 4/5/6…，重算恢复点接上

    # ── 步骤3：通读本章、提取出场人物 ──────────────────────────
    if step <= 3:
        if payload.get("extraction"):
            extraction_dict = payload["extraction"]  # 断点缓存：不重烧 LLM
            progress("extract", "复用已提取的角色清单", call_id)
        else:
            async with AsyncSessionLocal() as db:
                chapter = await get_chapter_by_id(db, row["chapter_id"])
            if chapter is None:
                return "章节不存在，流程中止"
            if not (chapter.chapter_content or "").strip():
                return "章节正文为空，无法提取角色"
            progress("extract", "正在通读本章、提取出场人物…", call_id)
            try:
                extraction_dict = await _extract_task(script_id, chapter.chapter_title,
                                                      chapter.chapter_content or "")
            except LLMStepFailed as e:
                return f"角色提取失败（{e}）；产物已保留，稍后可重新发起续跑"
            progress("extract",
                     f"提取到 {len(extraction_dict.get('characters') or [])} 个人物", call_id)
        step = 4
    else:
        extraction_dict = payload.get("extraction") or {}

    # 步骤 4/5 的输入：characters 一律以 extraction 为准（刚提取/断点缓存同源）
    characters = ChapterCharacterExtraction.model_validate(
        extraction_dict or {"characters": []}).characters

    # ── 步骤4：比对角色库、整理新建提案 → 人审 → 确认落库 ──────
    if step <= 4:
        feedback = ""
        # 断点缓存：proposal 已生成且未确认 → 直接弹卡，不重烧 LLM
        proposal = payload["proposal"] if (
            payload.get("proposal") and not payload.get("proposal_confirmed")) else None
        while True:
            async with AsyncSessionLocal() as db:
                catalog = await assemble_catalog(db, project_id, chapter_index)
            if proposal is None:
                progress("proposal", "正在比对角色库、整理需要新建的人物…", call_id)
                try:
                    proposal = await _proposal_task(script_id, chapter_index,
                                                    catalog, characters, feedback)
                    print("走到1")
                except LLMStepFailed as e:
                    print("走到2")
                    return f"提案生成失败（{e}）；产物已保留，稍后可重新发起续跑"
            if not (proposal.get("new_characters") or proposal.get("voice_supplements")):
                break  # 无可审内容：跳过提案卡
            # 人审在 task 之外：park 时不连累 LLM/落库重放
            print("走到3")
            answer = request_approval(proposal_gate(script_id, proposal, catalog, call_id))
            print("走到4")
            decision, fb, edited = parse_answer(answer)
            print(answer)
            if decision == "abort":
                return "用户放弃有声书流程"
            if decision == "feedback":
                feedback = fb
                proposal = None  # 打回重提：新的 task 调用才真正重走一遍 LLM
                continue
            if edited.get("proposal"):
                proposal = {**proposal, **(edited["proposal"] or {})}
            break  # 提案已确认

        # 确认 → 新角色落库 + 为已有阶段补音色描述 + 标记 confirmed（同一事务）
        async with AsyncSessionLocal() as db:
            parsed = NewCharacterProposal.model_validate(proposal)
            created = await apply_proposal(db, project_id, parsed)
            supplemented = await apply_voice_supplements(db, parsed.voice_supplements)
            await save_stage(db, script_id, "proposal", proposal)  # 确认版回写（可能被编辑过）
            await save_stage(db, script_id, "proposal_confirmed", True)
            await db.commit()
        bits = []
        if created:
            bits.append(f"新建 {len(created)} 个角色")
        if supplemented:
            bits.append(f"补了 {supplemented} 处音色描述")
        progress("proposal", "、".join(bits) if bits else "提案已确认", call_id)
        step = 5

    # ── 步骤5：人物 ↔ 已有角色阶段配对 → 人审 → 确认落 mapping 列 ──
    if step <= 5:
        feedback = ""
        notice = ""
        # 断点缓存：mapping_preview 已生成 → 直接弹配对卡
        mapping = payload.get("mapping_preview") or None
        while True:
            async with AsyncSessionLocal() as db:
                catalog = await assemble_catalog(db, project_id, chapter_index)
            if mapping is None:
                progress("mapping", "正在把本章人物与作品里已有的角色配对…", call_id)
                try:
                    mapping = await _mapping_task(script_id, catalog, characters, feedback)
                except LLMStepFailed as e:
                    return f"配对预填失败（{e}）；产物已保留，稍后可重新发起续跑"
            entries = list(mapping.get("entries") or [])
            summary = notice or f"本章提取到 {len(entries)} 个人物，请把它们和作品里已有的角色配对"
            answer = request_approval(mapping_gate(script_id, mapping, catalog, summary, call_id))
            decision, fb, edited = parse_answer(answer)
            if decision == "abort":
                return "用户放弃有声书流程"
            if decision == "feedback":
                feedback = fb
                notice = "已按反馈重新配对，请再确认"
                mapping = None  # 打回重配：新的 task 调用才真正重走 LLM
                continue
            if edited.get("entries"):
                mapping = {"entries": edited["entries"]}
            if (mapping.get("entries")
                    and all(e.get("stage_id") is not None for e in mapping["entries"])):
                break  # 全部配上了才放行（空配对不允许——合成会退化成全旁白音色）
            notice = "还有人物没配上角色，请全部配对后再确认"
            feedback = notice
            mapping = None  # 未全部配对：重走预填再弹卡

        # 确认 → 落正式 mapping 列（恢复判定锚点！）+ 留渲染镜像（同一事务）
        table = MappingTable.model_validate(mapping)
        async with AsyncSessionLocal() as db:
            await write_mapping(db, script_id, table)
            await save_stage(db, script_id, "mapping_preview", table.model_dump())
            await db.commit()
        progress("mapping", f"已确认 {len(table.entries)} 条配对", call_id)
        step = 6

    # ── 步骤6：已有音频 ↔ 有声书映射（AudioBookScripAudio，幂等）──
    if step <= 6:
        if audio_ids is not None:
            # 新建轨显式传入（可为空 = 不配 BGM/SFX）；整体替换、幂等
            async with AsyncSessionLocal() as db:
                final_ids = await write_audio_mapping(db, script_id, audio_ids)
                await db.commit()
            row["audio_ids"] = final_ids
            progress("audio", f"已映射 {len(final_ids)} 条音频资源", call_id)
        else:
            # 续跑轨不传 → 尊重已有映射（面板步骤6 配过的不动）
            progress("audio", f"沿用已映射的 {len(row['audio_ids'])} 条音频资源", call_id)
        step = 7

    # ── 步骤7：旁白音色 → 人审 → 确认落 narrator_desc + narrator_text ──
    if step <= 7:
        current = (row["narrator_desc"] or narrator_desc or "").strip()
        answer = request_approval(narrator_gate(script_id, current, call_id))
        decision, _fb, edited = parse_answer(answer)
        if decision == "abort":
            return "用户放弃有声书流程"
        desc = str(edited.get("narrator_desc") or current or "").strip()
        if not desc:
            return "未提供旁白音色描述，流程中止（可在面板步骤7补）"
        # 试听文本用统一默认句：与 routers.get_narrator_preview 的兜底 key 一致，
        # 面板"查询旁白试听"接口对 AI 轨产物也能命中缓存
        async with AsyncSessionLocal() as db:
            await write_narrator(db, script_id, desc, NARRATOR_SAMPLE_DEFAULT)
            await db.commit()
        row["narrator_desc"] = desc
        progress("narrator", f"旁白音色已确认：{desc}", call_id)
        step = 8

    # ── 步骤8：组角色卡 → 生成本章有声书脚本 → 人审 ────────────
    if step <= 8:
        async with AsyncSessionLocal() as db:
            chapter = await get_chapter_by_id(db, row["chapter_id"])
        if chapter is None:
            return "章节不存在，流程中止"
        if not (chapter.chapter_content or "").strip():
            return "章节正文为空，无法生成脚本"
        if not (row["mapping"] or "").strip():
            return "没有配对结果（步骤5），无法生成脚本"

        mapping = MappingTable.model_validate(json.loads(row["mapping"]))
        async with AsyncSessionLocal() as db:
            cards = await build_character_cards(db, mapping)
            resources = (await get_resource_by_ids(db, row["audio_ids"])
                         if row["audio_ids"] else [])
        audio_catalog = [
            {"id": r.id, "type": r.audio_type, "name": r.Audio_name,
             "description": r.description or ""}
            for r in resources
        ]
        while True:
            progress("script", "正在把本章改编成有声书脚本…", call_id)
            try:
                script_path = await _script_task(
                    script_id, chapter.chapter_title, chapter.chapter_content or "",
                    mapping, cards, audio_catalog)
            except LLMStepFailed as e:
                return f"脚本生成失败（{e}）；产物已保留，稍后可重新发起续跑"
            script_obj = read_script_file(script_path)
            if script_obj is None:
                return "脚本文件不存在，无法继续（请重新发起）"
            progress("script", "脚本已生成，请审核", call_id)
            answer = request_approval(script_gate(script_id, script_obj, call_id))
            decision, fb, _edited = parse_answer(answer)
            if decision == "abort":
                return "用户放弃有声书流程"
            if decision == "feedback":
                continue  # 打回重编：新的 task 调用才真正重走 LLM（全新重编）
            break
        step = 9

    # ── 步骤9：合成（finalize_audio 唯一入口，与面板/重合成同路）──
    progress("synthesize", "正在设计音色、逐段合成音频…", call_id)
    result = await finalize_audio(
        script_id,
        on_wait=lambda: progress(
            "synthesize", "排队中：前面还有音频在合成，等显存空出来就开始…", call_id),
    )
    progress("done", f"已生成：{Path(result['audio_path']).name}", call_id,
             warnings=result["warnings"], script_id=script_id,
             audio_path=result["audio_path"])
    return done_text(result["audio_path"], result["warnings"])
