from typing import Annotated
from langchain_core.runnables import RunnableConfig
from agent.subagents.summary import summarize
from agent.tools.approval import request_approval
from agent.tools.common import current_project
from config.db_conf import AsyncSessionLocal
from config.store import DEFAULT_CONTEXT_WINDOW
from crud import Volume, Chapter, CharacterStage, Character, AudioBookScript, Project
from datetime import datetime
from langchain_core.messages import HumanMessage, trim_messages
from langchain_core.tools import ToolException, tool, InjectedToolCallId

from crud.CHROMA_chapters import delete_chapter_segments_by_chapter
from utils.common import rm_scripts


@tool(parse_docstring=True)
async def list_volumes(config: RunnableConfig) -> str:
    """查询作品的分卷：卷数、每卷章节范围与章数、卷摘要全文。
    卷摘要缺失时会即时兜底：拉取卷内各章摘要 → trim_messages 裁剪进上下文预算
    （context 的 0.8）→ summarize(kind="volume") 汇总，并回写卷表，下次直接命中。
    了解长篇结构、按卷取摘要前先看这条。

    Args:


    Returns:
        分卷清单（每卷一行 + 摘要全文缩进）；无卷返回提示。
        失败（读库、摘要生成、回写等）时抛 ToolException，由 agent 层接住重试。
    """
    project_id = current_project(config)
    if not project_id:
        raise ToolException("无法确定当前项目 ID，请确认会话已关联作品后再查询分卷")

    # —— 读卷 + 章节摘要行（轻量行查询，不拉每章正文）——
    try:
        async with AsyncSessionLocal() as db:
            vols = await Volume.get_volumes_by_project(db, project_id)
            chapter_rows = await Chapter.get_chapter_summary_rows(db, project_id)
    except Exception as e:
        raise ToolException(f"读取分卷或章节摘要失败：{e}") from e

    if not vols:
        return f"作品 {project_id} 还没有分卷"

    # —— 上下文预算：context 的 0.8，多卷缺摘要共享、逐次扣减 ——
    if not isinstance(DEFAULT_CONTEXT_WINDOW, (int, float)) or DEFAULT_CONTEXT_WINDOW <= 0:
        raise ToolException(f"上下文预算 DEFAULT_CONTEXT_WINDOW={DEFAULT_CONTEXT_WINDOW!r} 非法，无法计算裁剪上限")
    remaining = int(DEFAULT_CONTEXT_WINDOW * 0.8)

    todo = [v for v in vols if v.chapter_start >= 0 and not (v.summary or "").strip()]
    generated: dict[int, str] = {}
    no_source: set[int] = set()
    budget_exhausted = False

    for v in todo:
        rows = [r for r in chapter_rows if v.chapter_start <= r.chapter_index <= v.chapter_end]
        texts = [
            f"第{r.chapter_index + 1}章「{r.chapter_title}」：{r.chapter_summary or '（本章暂无摘要）'}"
            for r in rows
        ]
        if not texts:
            no_source.add(v.id)
            continue
        if remaining <= 0:
            budget_exhausted = True
            continue
        try:
            kept = trim_messages(
                [HumanMessage(t) for t in texts],
                max_tokens=remaining,
                token_counter=lambda ms: sum(len(m.content) for m in ms),  # 近似：1 字 ≈ 1 token
                strategy="last",   # 超预算保尾部（贴近当前剧情）；要保开头改 "first"
                start_on="human",
            )
        except Exception as e:
            raise ToolException(f"第{v.volume_index + 1}卷的章节摘要裁剪失败：{e}") from e
        if not kept:
            no_source.add(v.id)
            continue
        used = sum(len(m.content) for m in kept)
        try:
            summary = await summarize([m.content for m in kept], kind="volume")
        except Exception as e:
            raise ToolException(f"第{v.volume_index + 1}卷的卷摘要生成失败：{e}") from e
        generated[v.id] = summary
        remaining -= used

    # —— 回写卷表：下次调用直接命中，不再重复烧 LLM ——
    if generated:
        try:
            async with AsyncSessionLocal() as db:
                rows = await Volume.get_volumes_by_project(db, project_id)
                for row in rows:
                    if row.id in generated:
                        row.summary = generated[row.id]
                        row.summary_generated_at = datetime.now()
                await db.commit()
        except Exception as e:
            raise ToolException(f"卷摘要回写失败（摘要已生成但未持久化，下次会重算）：{e}") from e

    # —— 组装输出 ——
    lines = []
    for v in vols:
        if v.chapter_start < 0:
            lines.append(f"第{v.volume_index + 1}卷「{v.name or '未命名'}」｜空壳（暂无章节）")
            continue
        count = v.chapter_end - v.chapter_start + 1
        head = (f"第{v.volume_index + 1}卷「{v.name or '未命名'}」｜"
                f"第{v.chapter_start + 1}–{v.chapter_end + 1}章（共{count}章）")
        summary = generated.get(v.id) or (v.summary or "").strip()
        if summary:
            tag = "（本次即时生成并已回写）" if v.id in generated else ""
            lines.append(f"{head}{tag}\n  卷摘要：{summary}")
        elif v.id in no_source:
            lines.append(f"{head}\n  卷摘要：（暂无——卷内还没有可汇总的章节摘要）")
        elif budget_exhausted:
            lines.append(f"{head}\n  卷摘要：（上下文预算不足，未生成）")
        else:
            lines.append(f"{head}\n  卷摘要：（生成失败，稍后重试或等后台级联补齐）")
    return f"共 {len(vols)} 卷：\n" + "\n".join(lines)



@tool(parse_docstring=True)
async def get_volume(
    volume_index: int,
    config: RunnableConfig,
) -> str:
    """查询单个分卷的详情（按卷级索引）：卷名、章节范围、章数、卷摘要全文。
    摘要缺失时即时兜底：拉取卷内各章摘要 → trim_messages 裁剪进上下文预算（context 的 0.8）→
    summarize(kind="volume") 汇总并回写卷表，下次直接命中。
    看整体卷结构用 list_volumes，逐章摘要用 get_chapter_summaries。

    Args:
        volume_index: 卷级索引，0-based（第1卷=0）

    Returns:
        卷详情；查询/生成失败抛 ToolException，卷不存在返回提示。
    """
    project_id = current_project(config)
    if not project_id:
        raise ToolException("无法确定当前项目 ID，请确认会话已关联作品后再查询分卷")

    try:
        async with AsyncSessionLocal() as db:
            vols = await Volume.get_volumes_by_project(db, project_id)
            chapter_rows = await Chapter.get_chapter_summary_rows(db, project_id)
    except Exception as e:
        raise ToolException(f"读取卷/章节数据失败：{e}") from e

    vol = next((v for v in vols if v.volume_index == volume_index), None)
    if vol is None:
        valid = "/".join(str(v.volume_index) for v in vols) or "无"
        return f"卷索引 {volume_index} 不存在（可用：{valid}），请先用 list_volumes 查看"

    if vol.chapter_start < 0:
        return f"第{volume_index + 1}卷「{vol.name or '未命名'}」：空壳卷（暂无章节，新章加入时自动落入本卷）"

    count = vol.chapter_end - vol.chapter_start + 1
    rows = [r for r in chapter_rows if vol.chapter_start <= r.chapter_index <= vol.chapter_end]

    summary = (vol.summary or "").strip()
    generated = False
    if not summary and rows:
        if not isinstance(DEFAULT_CONTEXT_WINDOW, (int, float)) or DEFAULT_CONTEXT_WINDOW <= 0:
            raise ToolException(f"上下文预算 DEFAULT_CONTEXT_WINDOW={DEFAULT_CONTEXT_WINDOW!r} 非法，无法计算裁剪上限")
        texts = [
            f"第{r.chapter_index + 1}章「{r.chapter_title}」：{r.chapter_summary or '（本章暂无摘要）'}"
            for r in rows
        ]
        try:
            kept = trim_messages(
                [HumanMessage(t) for t in texts],
                max_tokens=int(DEFAULT_CONTEXT_WINDOW * 0.8),
                token_counter=lambda ms: sum(len(m.content) for m in ms),  # 近似：1 字 ≈ 1 token
                strategy="last",
                start_on="human",
            )
        except Exception as e:
            raise ToolException(f"卷内章节摘要裁剪失败：{e}") from e
        if kept:
            try:
                summary = await summarize([m.content for m in kept], kind="volume")
            except Exception as e:
                raise ToolException(f"卷摘要生成失败：{e}") from e
            generated = True
            try:
                async with AsyncSessionLocal() as db:
                    row = await Volume.get_volume_by_id(db, vol.id)
                    if row:
                        row.summary = summary
                        row.summary_generated_at = datetime.now()
                    await db.commit()
            except Exception as e:
                raise ToolException(f"卷摘要回写失败（摘要已生成但未持久化，下次会重算）：{e}") from e

    head = (f"第{volume_index + 1}卷「{vol.name or '未命名'}」｜"
            f"第{vol.chapter_start + 1}–{vol.chapter_end + 1}章（共{count}章）")
    if summary:
        tag = "（本次即时生成并已回写）" if generated else ""
        return f"{head}{tag}\n  卷摘要：{summary}"
    return f"{head}\n  卷摘要：（暂无——卷内还没有可汇总的章节摘要）"

@tool(parse_docstring=True)
async def create_volume(
    name: str,
    chapter_start: int,
    chapter_end: int,
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig,
) -> str:
    """新建一卷（需用户确认）。手动指定本卷覆盖的章节范围，追加到卷序末尾，
    不改动现有卷边界、不平移章节序号。两种模式：
    1. 常规卷：chapter_start/chapter_end 为 0-based 章节索引（第1章=0，含两端），
       不得与现有卷重叠，且范围须落在已有章节总数内；
    2. 空壳卷：chapter_start = chapter_end = -1，表示"暂无章节的卷"，
       之后新章经 save_chapter/add_chapter 落入该卷时自动物化为本卷首章。
    整套卷结构重建用 set_volumes。

    Args:
        name: 卷名
        chapter_start: 起始章节索引，0-based；传 -1 表示空壳卷
        chapter_end: 结束章节索引，0-based 含端点；空壳卷须同为 -1

    Returns:
        创建结果；参数非法/范围冲突返回提示，库操作失败抛 ToolException。
    """
    project_id = current_project(config)

    shell = (chapter_start == -1 and chapter_end == -1)
    if not shell and (chapter_start < 0 or chapter_end < chapter_start):
        return "chapter_start/chapter_end 非法：须为 0-based 整数且 start ≤ end；空壳卷须传 -1/-1"

    payload = {
        "entity": "volumes", "action": "create",
        "summary": (f"创建空壳卷「{name}」" if shell
                    else f"创建卷「{name}」（第{chapter_start + 1}–{chapter_end + 1}章）"),
        "draft": {"name": name, "chapter_start": chapter_start, "chapter_end": chapter_end},
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return "已放弃创建卷"
    edited = answer.get("edited") or {}
    name = str(edited.get("name") or name)
    chapter_start = edited.get("chapter_start", chapter_start)
    chapter_end = edited.get("chapter_end", chapter_end)
    shell = (chapter_start == -1 and chapter_end == -1)

    # 审批等待期间卷可能变动，且 edited 可能改了范围 → 重校验后再落库
    try:
        async with AsyncSessionLocal() as db:
            vols = await Volume.get_volumes_by_project(db, project_id)
    except Exception as e:
        raise ToolException(f"读取现有分卷失败：{e}") from e

    if not shell:
        if chapter_start < 0 or chapter_end < chapter_start:
            return "编辑后的章节范围仍非法（须为 0-based 整数且 start ≤ end）"
        for v in vols:
            if v.chapter_end < 0:  # 空壳不占章节位，跳过（REST 版会误报冲突）
                continue
            if not (chapter_end < v.chapter_start or chapter_start > v.chapter_end):
                return (f"范围 [{chapter_start}:{chapter_end}] 与第{v.volume_index + 1}卷"
                        f"「{v.name}」[{v.chapter_start}:{v.chapter_end}] 重叠，请调整")
        try:
            async with AsyncSessionLocal() as db:
                _, total = await Chapter.get_chapters_paginated(db, project_id)
        except Exception as e:
            raise ToolException(f"查询章节总数失败：{e}") from e
        if chapter_end >= total:
            return (f"范围超出已有章节数（共 {total} 章，最大章索引 {total - 1}）；"
                    f"请调整范围，或先创建章节，或改用空壳卷（-1/-1）待新章落入")

    volume_index = max((v.volume_index for v in vols), default=-1) + 1
    try:
        async with AsyncSessionLocal() as db:
            vol = await Volume.add_volume(
                db=db, project_id=project_id, volume_index=volume_index, name=name,
                chapter_start=chapter_start, chapter_end=chapter_end,
                summary="", summary_generated_at=None,
            )
    except Exception as e:
        raise ToolException(f"创建分卷落库失败：{e}") from e

    if shell:
        return f"空壳卷{volume_index + 1}「{name}」已创建，新章加入时将自动落入本卷"
    return f"卷{volume_index + 1}「{name}」已创建（第{chapter_start + 1}–{chapter_end + 1}章），卷摘要正在后台刷新"

@tool(parse_docstring=True)
async def delete_volume(
    volume_index: int,
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig,
) -> str:
    """删除一卷（需用户确认，不可逆）。常规卷：卷内全部章节一并删除，级联清理
    角色阶段绑定、音频脚本、向量索引、项目映射；后续章号整体前移，后卷整体左移、
    卷序号压实。空壳卷（无章节）：仅删除卷行本身。

    Args:
        volume_index: 要删除的卷级索引，0-based（第1卷=0）

    Returns:
        删除结果；用户拒绝/卷不存在返回提示，落库或外部清理失败抛 ToolException。
    """
    project_id = current_project(config)

    try:
        async with AsyncSessionLocal() as db:
            vols = await Volume.get_volumes_by_project(db, project_id)
    except Exception as e:
        raise ToolException(f"读取分卷失败：{e}") from e

    vol = next((v for v in vols if v.volume_index == volume_index), None)
    if vol is None:
        valid = "/".join(str(v.volume_index) for v in vols) or "无"
        return f"卷索引 {volume_index} 不存在（可用：{valid}），请先用 list_volumes 查看"

    shell = vol.chapter_start < 0
    if shell:
        summary_line = f"删除空壳卷{volume_index + 1}「{vol.name or '未命名'}」（无章节，仅删卷行）"
    else:
        count = vol.chapter_end - vol.chapter_start + 1
        summary_line = (f"删除第{volume_index + 1}卷「{vol.name or '未命名'}」及其"
                        f"第{vol.chapter_start + 1}–{vol.chapter_end + 1}章（共{count}章，不可逆）")
    answer = request_approval(
        {"entity": "volumes", "action": "delete", "summary": summary_line,
         "draft": {"volume_id": vol.id, "name": vol.name,
                   "chapter_start": vol.chapter_start, "chapter_end": vol.chapter_end}},
        tool_call_id,
    )
    if not answer.get("approved"):
        return "已放弃删除卷"

    # 审批等待期间可能已变动，重读最新行
    try:
        async with AsyncSessionLocal() as db:
            vol = await Volume.get_volume_by_id(db, vol.id)
    except Exception as e:
        raise ToolException(f"重读分卷失败：{e}") from e
    if vol is None:
        return "该卷已被删除，无需重复操作"

    chapter_ids = []
    if vol.chapter_start >= 0:
        try:
            async with AsyncSessionLocal() as db:
                chapter_ids = await Chapter.get_chapter_ids_by_index_range(
                    db, project_id, vol.chapter_start, vol.chapter_end)
        except Exception as e:
            raise ToolException(f"查询卷内章节失败：{e}") from e

    # 落库（与 REST 层同序，失败整体回滚不留半删状态）
    try:
        async with AsyncSessionLocal() as db:
            if vol.chapter_start >= 0:
                s, e_idx = vol.chapter_start, vol.chapter_end
                n = e_idx - s + 1
                character_ids = await Character.get_characterid_by_project(db, project_id)
                if character_ids:
                    await CharacterStage.reset_chapter_indexes_by_characters(
                        db, character_ids, list(range(s, e_idx + 1)))
                    await CharacterStage.shift_stage_chapter_indexes(db, character_ids, e_idx + 1, -n)
                for cid in chapter_ids:
                    await AudioBookScript.delete_scripts_by_chapter(db, cid)
                # 卷边界：目标卷逐次收缩至塌缩，后卷整体左移 n
                await Volume.update_volumes_on_deleted_chapter_range(db, project_id, s, e_idx)
                await Chapter.delete_chapters_by_ids(db, chapter_ids)
                await Chapter.shift_chapter_indexes(db, project_id, e_idx + 1, -n)
                await Project.remove_project_chapters(db, chapter_ids)
            await Volume.delete_volume(db, vol.id)
            # 压实卷序号（删行留洞会影响 replace_volumes 按 volume_index 对齐摘要）
            remaining = await Volume.get_volumes_by_project(db, project_id)
            for i, v in enumerate(remaining):
                v.volume_index = i
            await db.commit()
    except Exception as e:
        raise ToolException(f"删除分卷落库失败（已回滚，数据未变）：{e}") from e

    # 外部存储清理：DB 落定之后做，失败只损失索引/脚本，可重建，不回滚 DB
    for cid in chapter_ids:
        try:
            await delete_chapter_segments_by_chapter(str(cid))
        except Exception as e:
            raise ToolException(f"章节 {cid} 向量索引清理失败（可重建，不影响数据）：{e}") from e
    if chapter_ids:
        try:
            await rm_scripts(chapter_ids)
        except Exception as e:
            raise ToolException(f"音频脚本清理失败（可重建，不影响数据）：{e}") from e

    if shell:
        return f"空壳卷「{vol.name or '未命名'}」已删除"
    return (f"卷「{vol.name or '未命名'}」及其 {len(chapter_ids)} 章已删除，"
            f"后续章号已前移、后卷已左移，向量与音频脚本已清理")



TOOLS = [
    list_volumes,
    get_volume,
    create_volume,
    delete_volume,
]

DISPLAY = {
    "list_volumes": "查询全部分卷",
    "get_volume": "查询指定分卷详情",
    "create_volume": "新建分卷",
    "delete_volume": "删除分卷",
}