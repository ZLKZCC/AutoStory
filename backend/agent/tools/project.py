"""项目设定域：查询项目概览/大纲/世界线 + 保存大纲/世界线 + 重算项目摘要/描述（带人审）。

对齐 REST 层 routers/project.py：
- 大纲/世界线保存：落库（CRUD update_project 联动顶 concept_updated_at / worldline_updated_at）。
  全局概要随之变陈旧，由下轮上下文构建（build_context）的懒重算或 save_project_meta 按需重算，
  不在此触发后台任务（refresh_summaries / touch_project_setting 已废弃）。
- save_project_meta：走 regenerate_project_meta 的完整方案——先按 project_id 做陈旧判定
  （大纲/世界线/卷摘要任一晚于概要生成时间即需更新），需要时把大纲、世界线、章节清单、
  旧摘要/旧描述交给 LLM 结构化重算（输入裁剪由 regenerate_project_meta 内部完成），
  弹人审卡片展示草稿，确认后写库并同步 AgentState。
- 工具成功后通过 Command 更新 AgentState.project_summary / project_description，
  本轮对话即刻生效（需要 langgraph 较新版本支持 Command 作为工具返回值）。
"""
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import InjectedToolCallId, ToolException, tool
from langgraph.types import Command

from config.db_conf import AsyncSessionLocal
from crud import Project, Volume, Chapter
from utils.content_format import (
    build_outline_data,
    build_worldline_data,
    outline_to_text,
    worldline_to_text,
)

from agent.tools.approval import request_approval
from agent.tools.common import current_project
from utils.context import regenerate_project_meta


@tool(parse_docstring=True)
async def get_project(config: RunnableConfig) -> str:
    """查询项目概览：名称、描述、章节数、角色数、分卷数，以及大纲/世界线是否已设置、全局概要是否滞后。
    了解作品全貌、定方向前先查这条。需要大纲或世界线的具体内容时，分别用 get_outline / get_worldline，
    分卷明细用 list_volumes。

    Args:


    Returns:
        项目概览；项目不存在返回提示，查询失败抛 ToolException。
    """
    project_id = current_project(config)
    if not project_id:
        raise ToolException("无法确定当前项目 ID，请确认会话已关联作品后再查询")

    try:
        async with AsyncSessionLocal() as db:
            proj = await Project.get_project_by_id(db, project_id)
            if proj is None:
                return f"项目 {project_id} 不存在"
            ch = (await Project.get_chapter_counts(db, [project_id])).get(project_id, 0)
            ca = (await Project.get_character_counts(db, [project_id])).get(project_id, 0)
            volumes = await Volume.get_volumes_by_project(db, project_id)
    except Exception as e:
        raise ToolException(f"查询项目失败：{e}") from e

    # "已设置"要看是否真有内容：空 OutlineData（无 outline_html/global_notes/sections）、
    # 空壳 WorldlineData（各世界线 nodes 全空）都算未设置，免得误导 agent 以为有内容
    concept = proj.concept
    if isinstance(concept, dict):
        outline_set = any(concept.values())
    else:
        outline_set = bool(concept)
    wl = proj.worldline
    if isinstance(wl, dict) and isinstance(wl.get("worldlines"), list):
        worldline_set = any(
            (w.get("nodes") or []) for w in wl["worldlines"] if isinstance(w, dict)
        )
    else:
        worldline_set = bool(wl)

    # 全局概要陈旧判定，与 build_context / save_project_meta 同口径，另加"卷摘要晚于全局概要"一项
    # （Volume 模型注释口径：落后于设定或任一卷摘要即陈旧）。属性均为已加载列值，session 关闭后可读
    su = proj.summary_generated_at
    stale = (
        (proj.concept_updated_at and (su is None or proj.concept_updated_at > su))
        or (proj.worldline_updated_at and (su is None or proj.worldline_updated_at > su))
        or any(
            v.summary_generated_at and (su is None or v.summary_generated_at > su)
            for v in volumes
            if v.chapter_start >= 0
        )
    )
    return "\n".join([
        f"项目「{proj.project_name}」",
        f"描述: {proj.description or '（未填）'}",
        f"章节数: {ch}，角色数: {ca}" + (f"，分卷数: {len(volumes)}" if volumes else ""),
        f"大纲: {'已设置（用 get_outline 查看正文）' if outline_set else '未设置'}",
        f"世界线: {'已设置（用 get_worldline 查看节点与关系）' if worldline_set else '未设置'}",
        f"全局概要: {'可能滞后（设定或卷摘要有更新尚未汇总，可用 save_project_meta 立即重算）；要准确前情用 get_chapter_summaries / search_chapters' if stale else '最新'}",
    ])


@tool(parse_docstring=True)
async def get_outline(config: RunnableConfig) -> str:
    """查询项目大纲正文（纯文本/markdown，已剥离富文本标签）。改大纲前先读现状，别凭空覆盖丢失原内容；
    读到的正文可直接作为 save_outline 的 outline 入参，在其基础上新增/修改。

    Args:


    Returns:
        大纲正文纯文本；未设置返回提示，查询失败抛 ToolException。
    """
    project_id = current_project(config)
    if not project_id:
        raise ToolException("无法确定当前项目 ID，请确认会话已关联作品后再查询")

    try:
        async with AsyncSessionLocal() as db:
            proj = await Project.get_project_by_id(db, project_id)
    except Exception as e:
        raise ToolException(f"查询项目失败：{e}") from e
    if proj is None:
        return f"项目 {project_id} 不存在"
    if not proj.concept:
        return "大纲未设置；可用 save_outline 保存（与用户确认内容后写入）"
    try:
        return outline_to_text(proj.concept)
    except Exception as e:
        raise ToolException(f"大纲文本化失败：{e}") from e


@tool(parse_docstring=True)
async def get_worldline(config: RunnableConfig) -> str:
    """查询项目世界线（节点清单 + 关系清单的语义文本，不含坐标/配色）。改世界线前先读现状；
    读到的节点/关系可映射为 save_worldline 的 nodes/edges 结构，在其基础上增改。

    Args:


    Returns:
        世界线的节点与关系文本；未设置返回提示，查询失败抛 ToolException。
    """
    project_id = current_project(config)
    if not project_id:
        raise ToolException("无法确定当前项目 ID，请确认会话已关联作品后再查询")

    try:
        async with AsyncSessionLocal() as db:
            proj = await Project.get_project_by_id(db, project_id)
    except Exception as e:
        raise ToolException(f"查询项目失败：{e}") from e
    if proj is None:
        return f"项目 {project_id} 不存在"
    if not proj.worldline:
        return "世界线未设置；可用 save_worldline 保存（与用户确认结构后写入）"
    try:
        return worldline_to_text(proj.worldline)
    except Exception as e:
        raise ToolException(f"世界线文本化失败：{e}") from e


@tool(parse_docstring=True)
async def save_outline(
    outline: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig = None,
) -> str:
    """保存/更新项目大纲（需用户确认）。outline 传大纲正文，纯文本或 markdown
    （# 小标题组织主线/核心冲突/分卷/人物关系，- 列表，**加粗**，空行分段）。
    落库前自动封装成前端富文本大纲（OutlineData，转 TipTap HTML）。会先弹人审卡片，确认后写入。
    写入后项目概要自动标记为待刷新（下轮上下文构建时懒重算；要立即重算用 save_project_meta）。

    Args:
        outline: 大纲正文,纯文本或markdown,后端自动封装成前端富文本大纲结构

    Returns:
        保存结果；用户拒绝则放弃。
    """
    project_id = current_project(config)
    if not str(outline or "").strip():
        return "保存失败：outline 不能为空；请先 get_outline 读现状，在其基础上修改"

    payload = {
        "entity": "outline", "action": "update",
        "summary": "更新项目大纲",
        "draft": {"outline": outline},
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return "已放弃更新大纲"
    text = answer.get("edited", {}).get("outline", outline)
    if not str(text or "").strip():
        return "保存失败：编辑后的大纲为空"

    concept = build_outline_data(text)
    try:
        async with AsyncSessionLocal() as db:
            proj = await Project.get_project_by_id(db, project_id)
            if proj is None:
                return f"项目 {project_id} 不存在"
            # concept_updated_at 由 CRUD update_project 联动顶新 → 全局概要自动变陈旧，
            # 由 build_context 下轮懒重算或 save_project_meta 重算，此处不再触发后台任务
            await Project.update_project(db, project_id, {"concept": concept})
    except Exception as e:
        raise ToolException(f"保存大纲落库失败：{e}") from e
    return "项目大纲已保存，项目概要已标记待刷新（下轮自动重算，或用 save_project_meta 立即重算）"


@tool(parse_docstring=True)
async def save_worldline(
    worldline: dict,
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig = None,
) -> str:
    """保存/更新项目世界线（需用户确认）。worldline 只需传语义结构，落库前自动补全前端可视化字段
    （节点坐标按关系分层布局、默认配色、缺失 id 与时间戳），封装成 WorldlineData。
    会先弹人审卡片，用户确认后写入。写入后项目概要自动标记为待刷新
    （下轮上下文构建时懒重算；要立即重算用 save_project_meta）。
    worldline 形态（nodes 的 title 必填；edges 的 from/to 用节点 id、标题或序号引用）：
    {"name": 世界线名(可选), "description": 描述(可选),
     "nodes": [{"id": 稳定标识(建议给,供边引用), "title": 节点标题, "description": 节点描述(可选)}],
     "edges": [{"from": 起点, "to": 终点, "label": 关系描述(可选),
                "arrowType": unidirectional-right/unidirectional-left/bidirectional/undirected(可选)}]}

    Args:
        worldline: 世界线语义结构,JSON dict,含 nodes(title必填) 与 edges(from/to 引用节点),坐标与样式后端自动补

    Returns:
        保存结果；用户拒绝则放弃。
    """
    project_id = current_project(config)

    payload = {
        "entity": "worldlines", "action": "update",
        "summary": "更新项目世界线",
        "draft": {"worldline": worldline},
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return "已放弃更新世界线"
    edited = (answer.get("edited") or {}).get("worldline")
    # 顶层浅合并：用户编辑是整结构替换语义，浅合并足够；若前端卡片做局部编辑需换深合并
    spec = {**(worldline or {}), **(edited or {})}
    wl_data = build_worldline_data(spec)
    try:
        async with AsyncSessionLocal() as db:
            proj = await Project.get_project_by_id(db, project_id)
            if proj is None:
                return f"项目 {project_id} 不存在"
            # worldline_updated_at 由 CRUD update_project 联动顶新 → 全局概要自动变陈旧，
            # 由 build_context 下轮懒重算或 save_project_meta 重算，此处不再触发后台任务
            await Project.update_project(db, project_id, {"worldline": wl_data})
    except Exception as e:
        raise ToolException(f"保存世界线落库失败：{e}") from e
    return "项目世界线已保存，项目概要已标记待刷新（下轮自动重算，或用 save_project_meta 立即重算）"


@tool(parse_docstring=True)
async def save_project_meta(
    tool_call_id: Annotated[str, InjectedToolCallId],
    force: bool = False,
    work_contents: list[str] | None = None,
    chat_contents: list[str] | None = None,
    config: RunnableConfig = None,
) -> Command:
    """重算项目全局摘要（project_summary）与项目描述（project_description）（需用户确认）。
    按当前项目 ID 判定是否需要更新：大纲、世界线、卷摘要任一晚于概要生成时间即陈旧；
    陈旧（或 force=true）时走 regenerate_project_meta 方案——大纲、世界线、章节清单、旧摘要/旧描述
    自动取自数据库并按上下文预算裁剪，work_contents / chat_contents 作为补充材料一并融入
    （补充材料视作最新事实，与旧设定冲突时以补充材料为准），LLM 结构化重算后弹人审卡片
    展示草稿（可编辑），确认后写库（对应时间戳由 CRUD 联动顶新）并同步 AgentState。
    不陈旧且未 force 时直接返回"无需更新"，不烧 LLM、不使用补充材料。

    Args:
        force: 跳过陈旧判定强制重算,用户明确要求重写概要/描述时传 true
        work_contents: 作品内容补充,可选,字符串列表;传数据库静态来源（大纲/世界线/章节清单/旧摘要）
            之外、但应反映进概要的内容,如代表性章节正文片段（用 get_chapter_whole 取）、
            刚定稿的最新章节概要等;每条长度不限（内部自动裁剪）,最多 10 条,超出忽略
        chat_contents: 聊天内容补充,可选,字符串列表;传与用户讨论形成、尚未落进大纲/世界线的
            创作共识与方向决定（如"结局改为悲剧""新增复仇支线""主角中期黑化"）,最多 10 条

    Returns:
        Command：含给模型的工具消息与 AgentState 状态更新。
    """
    project_id = current_project(config)

    def _no_tool_msg(content: str) -> Command:
        # 失败/放弃路径也要回 Command：工具声明返回 Command 后，裸 str 会被 ToolNode 拒收
        return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id, status="error")]})

    if not project_id:
        return _no_tool_msg("无法确定当前项目 ID，请确认会话已关联作品后再重算")

    # —— 入参规整：宽容单个字符串误传；剔除空条目；条数截到上限 ——
    if isinstance(work_contents, str):
        work_contents = [work_contents]
    if isinstance(chat_contents, str):
        chat_contents = [chat_contents]
    if work_contents is not None and not isinstance(work_contents, list):
        return _no_tool_msg("work_contents 需为字符串列表（或单个字符串），请修正后重试")
    if chat_contents is not None and not isinstance(chat_contents, list):
        return _no_tool_msg("chat_contents 需为字符串列表（或单个字符串），请修正后重试")
    work_raw = [str(t).strip() for t in (work_contents or []) if t and str(t).strip()]
    chat_raw = [str(t).strip() for t in (chat_contents or []) if t and str(t).strip()]
    work_items, chat_items = work_raw[:10], chat_raw[:10]

    # —— 陈旧判定 + 取材（与 build_context 同口径，另含卷摘要项）；只读操作，先于审批执行 ——
    try:
        async with AsyncSessionLocal() as db:
            proj = await Project.get_project_by_id(db, project_id)
            if proj is None:
                return _no_tool_msg(f"项目 {project_id} 不存在")
            su = proj.summary_generated_at
            stale = (
                (proj.concept_updated_at and (su is None or proj.concept_updated_at > su))
                or (proj.worldline_updated_at and (su is None or proj.worldline_updated_at > su))
                or any(
                    v.summary_generated_at and (su is None or v.summary_generated_at > su)
                    for v in await Volume.get_volumes_by_project(db, project_id)
                    if v.chapter_start >= 0
                )
            )
            original_summary = proj.Project_summary or ""
            original_description = proj.description or ""
            concept_text = outline_to_text(proj.concept) if proj.concept else ""
            worldline_text = worldline_to_text(proj.worldline) if proj.worldline else ""
            chapters = await Chapter.get_chapter_times_by_project(db, project_id)
    except Exception as e:
        raise ToolException(f"读取项目数据失败：{e}") from e

    if not stale and not force:
        extra = "（传入的补充材料未使用：不强制重算时不会触发重算）" if (work_items or chat_items) else ""
        return _no_tool_msg(
            f"全局概要与描述均为最新（设定与卷摘要都没有晚于概要生成时间），无需重算{extra}；"
            "用户明确要求重写时传 force=true"
        )

    # —— regenerate_project_meta 方案：内部裁剪各来源到窗口预算、结构化输出、失败回退原值 ——
    # 补充材料带来源标签，让重算模型能区分"作品事实"与"作者共识"两类新增信息
    supplements = (
        [f"【补充·作品内容】\n{t}" for t in work_items]
        + [f"【补充·聊天内容】\n{t}" for t in chat_items]
    )
    contents_text = "\n".join(f"第{ch[2] + 1}章:{ch[1]}" for ch in chapters if ch[1])
    try:
        new_summary, new_desc = await regenerate_project_meta(
            concept_text, worldline_text, contents_text,
            original_summary, original_description,
            supplement_texts=supplements,
        )
    except Exception as e:
        raise ToolException(f"项目摘要/描述重算失败：{e}") from e
    # regenerate_project_meta 失败时静默回退原值——用相等性探测，如回退则只刷新时间戳清陈旧标记
    fell_back = (new_summary == original_summary and new_desc == original_description)

    bits = ["重算项目全局摘要与描述"]
    if not stale:
        bits.append("（强制）")
    if work_items or chat_items:
        bits.append(f"｜补充材料：作品 {len(work_items)} 条、聊天 {len(chat_items)} 条")
    payload = {
        "entity": "project_meta", "action": "regenerate",
        "summary": "".join(bits),
        "draft": {"project_summary": new_summary, "project_description": new_desc},
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return _no_tool_msg("已放弃重算项目摘要/描述")

    edited = answer.get("edited") or {}
    # 编辑为空串视为"该字段不更新"，而非清空（清空会污染陈旧判定）
    final_summary = str(edited["project_summary"]).strip() if "project_summary" in edited else new_summary.strip()
    final_desc = str(edited["project_description"]).strip() if "project_description" in edited else new_desc.strip()

    update_data: dict[str, Any] = {}
    if final_summary:
        # summary_generated_at 由 CRUD update_project 联动顶新，此处不显式传
        update_data["Project_summary"] = final_summary
    if final_desc:
        # description_updated_at 由 CRUD update_project 联动顶新，此处不显式传
        update_data["description"] = final_desc
    if not update_data:
        return _no_tool_msg("编辑后摘要与描述均为空，未做更新")

    try:
        async with AsyncSessionLocal() as db:
            updated = await Project.update_project(db, project_id, update_data)
    except Exception as e:
        raise ToolException(f"项目元信息落库失败：{e}") from e
    if updated is None:
        return _no_tool_msg(f"项目 {project_id} 不存在（可能在确认期间被删除）")

    note = "（重算失败已沿用原值，仅刷新时间戳清除陈旧标记）" if fell_back else ""
    state_update: dict[str, Any] = {
        "messages": [ToolMessage(
            content=f"项目摘要与描述已重算并保存{note}，AgentState 已同步",
            tool_call_id=tool_call_id,
        )],
    }
    if final_summary:
        state_update["project_summary"] = final_summary
    if final_desc:
        state_update["project_description"] = final_desc
    return Command(update=state_update)


TOOLS = [get_project, get_outline, get_worldline, save_outline, save_worldline, save_project_meta]

DISPLAY = {
    "get_project": "查询当前作品",
    "get_outline": "查询大纲",
    "get_worldline": "查询世界线",
    "save_outline": "保存大纲",
    "save_worldline": "保存世界线",
    "save_project_meta": "更新项目摘要/描述",
}
