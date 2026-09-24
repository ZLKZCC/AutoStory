"""章节域：查询章节 / 检索前文 / 保存新章 / 更新章节（写入带人审 + 向量化 + 摘要联动）"""
from typing import Optional, Annotated

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool

from config.db_conf import AsyncSessionLocal
from crud import Chapter, Project, Volume, CharacterStage, Character, AudioBookScript
from crud.CHROMA_chapters import search_chapter_segments, rebuild_chapter_segments, delete_chapter_segments_by_chapter
from schemas.Chapter import ChapterCreate
from utils.common import rm_scripts
from utils.content_format import content_to_html
from agent.tools.approval import request_approval
from agent.tools.common import current_project


@tool(parse_docstring=True)
async def get_chapter_part(
    config: RunnableConfig,
    chapter_index: int,
) -> str:
    """查询章节内容，正文仅获取前1万字。chapter_index 为第几章减去1，也就是0-base

    Args:
        chapter_index: 章节索引,可选,注索引加1即第几章;不传返回列表

    Returns:
        (章号/标题/正文片段)
    """
    project_id = current_project(config)
    async with AsyncSessionLocal() as db:
        chapter = await Chapter.get_chapter_by_index_project_id(db, project_id, chapter_index)
        if not chapter:
            return f"项目{project_id}没有第{chapter_index+1}章节"

    return (
        f"第{chapter_index+1}章「{chapter.chapter_title}」\n"
        f"正文（仅显示前1w字,因此可能不完整）:[{chapter.chapter_content[:10000]}]"
    )

@tool(parse_docstring=True)
async def get_chapter_whole(
    config: RunnableConfig,
    chapter_index: int,
) -> str:
    """查询完整章节内容。chapter_index 为第几章减去1，也就是0-base

    Args:
        chapter_index: 章节索引,可选,注索引加1即第几章;不传返回列表

    Returns:
        (章号/标题/正文)
    """
    project_id = current_project(config)
    async with AsyncSessionLocal() as db:
        chapter = await Chapter.get_chapter_by_index_project_id(db, project_id, chapter_index)
        if not chapter:
            return f"项目{project_id}没有第{chapter_index+1}章节"

    return (
        f"第{chapter_index+1}章「{chapter.chapter_title}」\n"
        f"正文（仅显示前1w字,因此可能不完整）:[{chapter.chapter_content}]"
    )

@tool(parse_docstring=True)
async def get_chapter_summaries(
    config: RunnableConfig,
    start_index: Optional[int] = None,
    end_index: Optional[int] = None,
) -> str:
    """批量取章节摘要。

    Args:
        start_index: 起始章节索引(0-based,含),可选
        end_index: 结束章节索引(0-based,含),可选

    Returns:
        按章号排列的「第N章 标题：摘要」清单；范围或预算所限会说明省略了多少章。摘要可能标注滞后。
    """
    project_id = current_project(config)
    async with AsyncSessionLocal() as db:
        chapters = await Chapter.get_chapter_by_index_range(db, project_id, start_index, end_index)

    if not chapters:
        return f"范围 [{start_index}, {end_index}] 内没有章节。"

    chapters.sort(key=lambda c: c.chapter_index)
    lines, used, omitted = [], 0, 0
    for ch in chapters:
        summary = (ch.chapter_summary or "").strip()
        line = f"第{ch.chapter_index + 1}章 {ch.chapter_title.strip()}：{summary or '（暂无摘要）'}"
        # 摘要滞后 = 正文有实质变更且晚于摘要生成时间（口径见 Chapter 模型注释）
        if ch.content_updated_at and (not ch.summary_generated_at or ch.summary_generated_at < ch.content_updated_at):
            line += " [摘要滞后]"
        if lines and used + len(line) > 20000:  # 单次返回字符预算，超出整章省略
            omitted += 1
        else:
            lines.append(line)
            used += len(line)

    header = f"章节摘要，共{len(chapters)}章"
    if start_index is not None or end_index is not None:
        header += f"（仅范围 [{start_index}, {end_index}]，范围外未列出）"
    if omitted:
        header += f"，因长度预算省略{omitted}章，请缩小范围分批获取"

    return header + "：\n" + "\n".join(lines)



@tool(parse_docstring=True)
async def search_chapters(config: RunnableConfig, query: str, top_k: int = 5) -> str:
    """在前文章节中语义检索片段。用户问「之前哪里提到过 X」「某情节在第几章」时用。
    返回带章节定位的原文片段。

    Args:
        query: 检索语句
        top_k: 片段数,默认5

    Returns:
        带章节定位的原文片段列表，无命中返回「（无命中）」。
    """
    project_id = current_project(config)
    results = await search_chapter_segments(str(project_id), query, top_k)
    ids, docs, metas, dists = results["ids"][0], results["documents"][0], \
        results["metadatas"][0], results["distances"][0]
    lines = []
    for doc_id, doc, meta, dist in zip(ids, docs, metas, dists):
        meta_str = "，".join(f"{k}={v}" for k, v in (meta or {}).items())
        lines.append(f"[{doc_id}] {meta_str}\n{doc}")
    return "\n\n".join(lines[:top_k]) or "（无命中）"


@tool(parse_docstring=True)
async def save_chapter(
    chapter_title: str,
    chapter_content: str,
    volume_index: int,
    tool_call_id: Annotated[str, InjectedToolCallId],
    chapter_summary: str = "",
    config: RunnableConfig = None,
) -> str:
    """保存新章节（写作子 agent 产出后用）。会弹人审卡片，确认后落库：
    章节表 + 项目映射 + 向量化 + 章节摘要 + 项目概要联动。这是写作产出入库的唯一入口——
    正文不进库=没干完，后续有声书 / 前文检索都依赖此步。
    新章插入 volume_index 指定卷的末尾；该卷之后还有章节/分卷时序号整体后移。

    Args:
        chapter_title: 章节标题
        chapter_content: 章节正文全文,纯文本或markdown(空行分段/#标题/-列表/**加粗**),落库前自动转前端富文本HTML
        volume_index: 目标卷序号（0-based），新章插到该卷末尾
        chapter_summary: 章节摘要,需要根据这次的章节正文全文内容来填

    Returns:
        保存结果（含新章节 id 与章号）；用户拒绝则放弃。
    """
    project_id = current_project(config)

    # 目标卷预检：人审卡片弹出前先确认卷存在，别让用户确认完才发现写不进
    async with AsyncSessionLocal() as db:
        volumes = await Volume.get_volumes_by_project(db, project_id)
    if not any(v.volume_index == volume_index for v in volumes):
        valid = "/".join(str(v.volume_index) for v in volumes) or "无"
        return f"保存失败：卷序号 {volume_index} 不存在（可用：{valid}），请修正后重试"

    payload = {
        "entity": "chapters", "action": "create",
        "summary": f"新建章节「{chapter_title}」（{len(chapter_content)}字）",
        "draft": {
            "chapter_title": chapter_title,
            "chapter_content": chapter_content,
            "chapter_summary": chapter_summary,
        },
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return "已放弃保存章节"
    d = {**payload["draft"], **answer.get("edited", {})}

    # 正文规范化：落库存 TipTap HTML（前端富文本直接渲染，保留分段/标题/列表），
    # 向量化与摘要用纯文本（不让 HTML 标签污染 embedding）
    html_content, plain_content = content_to_html(d["chapter_content"])

    async with AsyncSessionLocal() as db:
        # 定位插入点并同步卷边界：目标卷吸收新章（空壳物化为 [i,i]），其后各卷右移（flush 不提交）
        insert_index = await Volume.extend_volume_on_appended_chapter_by_index(db, project_id, volume_index)
        if insert_index is None:  # 预检后理论不可达，兜底
            return f"保存失败：卷序号 {volume_index} 不存在"

        # 数据防线：与 add_chapter 路由同口径，卷边界异常时拒绝而不是写出错位数据
        _, count = await Chapter.get_chapters_paginated(db, project_id)
        if insert_index > count:
            return f"保存失败：卷 {volume_index} 边界异常（卷尾 {insert_index} 超出章节总数 {count}）"

        # 插入点起的章节与角色阶段整体右移（目标卷是书末卷时为空操作）
        await Chapter.shift_chapter_indexes(db, project_id, insert_index, 1)
        character_ids = await Character.get_characterid_by_project(db, project_id)
        await CharacterStage.shift_stage_chapter_indexes(db, character_ids, insert_index, 1)

        chap = ChapterCreate(
            chapter_title=d["chapter_title"],
            chapter_content=html_content,
            chapter_index=insert_index,
            chapter_summary=d.get("chapter_summary", ""),
        )
        new = await Chapter.add_chapter_by_model(db, chap)  # 内部 commit：卷边界与右移一并落库
        await Project.add_project_chapter(db, project_id, new.id)
        await db.commit()

    # 向量化（正文非空才建索引）；摘要走后台防抖级联（不阻塞本轮）
    if plain_content and plain_content.strip():
        await rebuild_chapter_segments(str(project_id), str(new.id), plain_content)

    return f"章节「{new.chapter_title}」已保存（id={new.id}，第{new.chapter_index + 1}章，落入卷{volume_index}末尾），摘要与项目概要正在刷新"


@tool(parse_docstring=True)
async def update_chapter(
    chapter_index: int,
    chapter_content: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    chapter_title: str = "",
    chapter_summary: str = "",
    config: RunnableConfig = None,
) -> str:
    """更新已有章节正文/标题/摘要（改稿后用）。会弹人审卡片，确认后落库：
    正文真变才重建向量 + 置陈旧标记（章节摘要、卷/项目概要由后台防抖级联刷新）；
    仅改标题/摘要不触发重建。章节序号不变，不涉及分卷调整。

    Args:
        chapter_index: 章节索引，0-base，第几章减1
        chapter_content: 新正文全文,纯文本或markdown(空行分段/#标题/-列表/**加粗**),落库前自动转前端富文本HTML
        chapter_title: 新标题,可选,留空不改标题
        chapter_summary: 章节摘要,需要根据这次的章节正文全文内容来填;留空则不更新摘要(正文有变时后台会自动重算)

    Returns:
        更新结果；用户拒绝则放弃。
    """
    project_id = current_project(config)

    # 前置定位：project_id + chapter_index 唯一确定章节；卡片弹出前确认存在，
    # 顺便留下旧值做"真变更"比对
    async with AsyncSessionLocal() as db:
        target = await Chapter.get_chapter_by_index_project_id(db, project_id, chapter_index)
        if not target:
            return f"更新失败：第{chapter_index + 1}章不存在，请先用 get_chapter_summaries 核对章号"
        old_html, old_title = target.chapter_content or "", target.chapter_title

    payload = {
        "entity": "chapters", "action": "update",
        "summary": f"更新第{chapter_index + 1}章「{old_title}」（新稿 {len(chapter_content)}字）",
        "draft": {
            "chapter_content": chapter_content,
            **({"chapter_title": chapter_title} if chapter_title else {}),
            **({"chapter_summary": chapter_summary} if chapter_summary else {}),
        },
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return "已放弃更新章节"
    d = {**payload["draft"], **answer.get("edited", {})}

    # 正文规范化：落库存 TipTap HTML，向量化/摘要用纯文本（不污染 embedding）
    html_content, plain_content = content_to_html(d.get("chapter_content", ""))

    # 只落真变的字段：Chapter.update_chapter 见到 chapter_content 就顶 content_updated_at，
    # 原样回传未变正文会造成假陈旧 → 白白触发整条摘要级联重算
    update_data = {}
    if html_content != old_html:
        update_data["chapter_content"] = html_content
    if d.get("chapter_title") and d["chapter_title"] != old_title:
        update_data["chapter_title"] = d["chapter_title"]
    if d.get("chapter_summary"):
        update_data["chapter_summary"] = d["chapter_summary"]

    if not update_data:
        return f"第{chapter_index + 1}章内容无变化，未做更新"

    async with AsyncSessionLocal() as db:
        await Chapter.update_chapter(db, target.id, update_data)  # 内部 commit；真变字段会正确顶新时间戳

    # 正文真变才重建向量（与 REST 层口径一致，按落库的 HTML 比较）；摘要级联走后台防抖，不阻塞本轮
    if "chapter_content" in update_data and plain_content and plain_content.strip():
        await rebuild_chapter_segments(str(project_id), str(target.id), plain_content)

    name_map = {"chapter_content": "正文", "chapter_title": "标题", "chapter_summary": "摘要"}
    changed = "、".join(name_map[k] for k in update_data)
    suffix = "，摘要与项目概要正在刷新" if "chapter_content" in update_data else ""
    return f"第{chapter_index + 1}章「{update_data.get('chapter_title', old_title)}」已更新（改动：{changed}）{suffix}"



@tool(parse_docstring=True)
async def delete_chapter(
    chapter_index: int,
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig,
) -> str:
    """删除章节（需用户确认）。按章号定位，连带清理：角色阶段绑定、音频脚本、
    分卷边界（所在卷区间收缩、塌缩为空壳、后卷左移）、项目映射、向量索引，
    后续章号整体 -1 平移。会先弹人审卡片，用户同意后执行删除。

    Args:
        chapter_index: 要删除的章节索引，0-base，第几章减1

    Returns:
        删除结果；章节不存在或用户拒绝时返回对应提示。
    """
    project_id = current_project(config)

    # 前置定位：卡片弹出前确认章节存在，取真实行 id 与标题（卡片文案、后续级联都以它为基准）
    async with AsyncSessionLocal() as db:
        chap = await Chapter.get_chapter_by_index_project_id(db, project_id, chapter_index)
    if chap is None:
        # 已被删过（含重放）或章号写错
        return f"删除失败：第{chapter_index + 1}章不存在，请先用 get_chapter_summaries 核对章号"

    payload = {
        "entity": "chapters", "action": "delete",
        "summary": f"删除章节「{chap.chapter_title}」（第{chap.chapter_index + 1}章）",
        "draft": {"chapter_id": chap.id, "chapter_title": chap.chapter_title},
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return "已放弃删除章节"

    chapter_id = chap.id
    # 落库（与 REST 层同序）：角色阶段 → 音频脚本 → 卷边界 → 章节行 → 序号平移 → 项目映射
    async with AsyncSessionLocal() as db:
        character_ids = await Character.get_characterid_by_project(db, project_id)
        # 绑定在被删章上的阶段置 -1，其后阶段整体 -1（reset 在前，避免被平移二次命中）
        await CharacterStage.reset_chapter_index_by_characters(db, character_ids, chapter_index)
        await CharacterStage.shift_stage_chapter_indexes(db, character_ids, chapter_index, -1)
        await AudioBookScript.delete_scripts_by_chapter(db, chapter_id)
        # 卷边界：所在卷收缩，塌缩则置 [-1,-1] 空壳保留，后卷左移
        await Volume.update_volumes_on_deleted_chapter(db, project_id, chapter_index)
        await Chapter.delete_chapter(db, chapter_id)  # 内部 commit：以上级联一并落库
        # 后续章节序号 -1（shift 不提交，由调用方控制事务）
        await Chapter.shift_chapter_indexes(db, project_id, chapter_index, -1)
        await Project.remove_project_chapter(db, chapter_id)
        await db.commit()

    # 外部存储清理：DB 落定之后做，失败只损失索引/脚本，可重建，不回滚 DB
    await delete_chapter_segments_by_chapter(str(chapter_id))
    await rm_scripts([chapter_id])

    return f"第{chapter_index + 1}章「{chap.chapter_title}」已删除，后续章号已平移，向量与音频脚本已清理"


TOOLS = [
    get_chapter_part,
    get_chapter_whole,
    get_chapter_summaries,
    search_chapters,
    save_chapter,
    update_chapter,
    delete_chapter,
]

DISPLAY = {
    "get_chapter_part": "查询章节部分正文",
    "get_chapter_whole": "查询章节完整正文",
    "get_chapter_summaries": "批量取章节摘要",
    "search_chapters": "检索前文相关内容",
    "save_chapter": "新建章节",
    "update_chapter": "更新已有章节",
    "delete_chapter": "删除章节",
}
