"""agent/tools/audiobook.py — 有声书域工具

两个流程入口 + 两个查询：
- audiobook_create   新建有声书（章节 → 9 步）；同章有进行中的行自动断点续跑
- audiobook_continue 从已有 script_id 续跑/重合成（面板与 AI 轨产物互认：
  正式字段非空 = 该步已通过，恢复判定唯一入口 utils/audiobook/persist.infer_resume）
- get_audio_resources     查 BGM/SFX 资源（audiobook_create 的 audio_ids 取值来源）
- get_audiobook_scripts   查已有有声书（audiobook_continue 的 script_id 取值来源）

管线本体在 agent/audiobook_pipeline.py:run_pipeline——本文件只做工具薄壳：
project_id 从 config 读出，call_id 由框架注入。
对 LLM 一律暴露 chapter_index（0-based 序号，与 get_audiobook_scripts 同口径），
壳内经 get_chapter_index_map 换算成 chapter_id 再进管线——两个口径不混出（历史教训：
LLM 会把序号当 id 传，命中错误章节的断点行，出现"直接跳旁白、命名不问"）。
"""
from typing import Annotated, List, Optional

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool

from agent.audiobook_pipeline import run_pipeline
from agent.tools.common import current_project


@tool(parse_docstring=True)
async def audiobook_create(
    chapter_index: int,
    tool_call_id: Annotated[str, InjectedToolCallId],
    audio_ids: Optional[List[int]] = None,
    narrator_desc: str = "",
    config: RunnableConfig = None,
) -> str:
    """把指定章节制作成有声书（新流程）。步骤：确认命名 → 提取出场人物 → 新建提案审核 →
    角色配对确认 → 音频映射 → 旁白音色确认 → 生成本章脚本 → 合成最终音频，
    人审处暂停等待用户在聊天卡片上操作。
    同章节已有进行中的有声书时自动从断点继续（已确认的步骤不重做、不重烧请求）；
    已有成品的章节再调用会作为一次新发起（新成品）。可与其他工具同轮调用，各自独立推进。

    Args:
        chapter_index: 章节序号，0 起（第 3 章传 2；与 get_audiobook_scripts 同口径）。
            不要使用数据库章节 id——用户说"第几章"时序号即章节顺序号减一
        audio_ids: 选用的背景音乐/音效资源id列表，可选，取值来自 get_audio_resources。
            不传或传空则不配 BGM/SFX（之后可在面板步骤6补映射）
        narrator_desc: 旁白音色描述，可选，如"中年男声，沉稳"；留空则由用户在卡片上选

    Returns:
        成品音频路径，或放弃/失败的原因。
    """
    from config.db_conf import AsyncSessionLocal
    from crud.Chapter import get_chapter_index_map

    project_id = current_project(config)
    async with AsyncSessionLocal() as db:
        idx_to_id, _ = await get_chapter_index_map(db, project_id)
    chapter_id = idx_to_id.get(chapter_index)
    if chapter_id is None:
        return (f"项目里没有第 {chapter_index + 1} 章"
                f"（chapter_index={chapter_index}），未发起有声书")
    return await run_pipeline(
        project_id,
        chapter_id=chapter_id,
        audio_ids=audio_ids,          # 原样透传：None=不配（保留已有），[]=显式清空
        narrator_desc=narrator_desc,
        call_id=tool_call_id,
    )


@tool(parse_docstring=True)
async def audiobook_continue(
    script_id: int,
    tool_call_id: Annotated[str, InjectedToolCallId],
    narrator_desc: str = "",
    config: RunnableConfig = None,
) -> str:
    """从已有的有声书（script_id）继续制作或重合成。此前中断/被打回的有声书从断点续跑
    （已确认的产物不重做、不重烧请求）；已有脚本未合成的直接进入合成；
    已有成品的返回成品信息（想出新一版可直接重合成）。script_id 取值来自 get_audiobook_scripts。

    Args:
        script_id: 有声书脚本id（get_audiobook_scripts 返回的 [id]）
        narrator_desc: 旁白音色描述，可选；仅当该有声书尚未确认旁白时作为默认值

    Returns:
        成品音频路径，或放弃/失败的原因。
    """
    return await run_pipeline(
        current_project(config),
        script_id=script_id,
        narrator_desc=narrator_desc,
        call_id=tool_call_id,
    )


@tool(parse_docstring=True)
async def get_audio_resources(
    resource_type: str = "",
    config: RunnableConfig = None,
) -> str:
    """查询已注册的音频资源（BGM/SFX）。为章节配乐、找音效时用，返回音频清单与描述。
    有声书 audio_ids 参数的取值从这里来。

    Args:
        resource_type: 音频类型,可选,取值 bgm 或 sfx,为空返回全部类型

    Returns:
        音频总数、过滤后的条数，以及音频清单（id、名称、类型、描述），为空返回提示。
    """
    from config.db_conf import AsyncSessionLocal
    from crud.Resource import get_resources_paginated

    async with AsyncSessionLocal() as db:
        res, total = await get_resources_paginated(db, "", 0, 200)
    if not res:
        return "音频资源库为空"
    rows = [r for r in res if not resource_type or resource_type.lower() in (r.audio_type or "").lower()]
    body = "\n".join(
        f"· [{r.id}] {r.Audio_name}（{r.audio_type}）{r.description or ''}"
        for r in rows[:30]
    )
    return f"共 {total} 条音频，过滤后 {len(rows)} 条：\n{body}"


@tool(parse_docstring=True)
async def get_audiobook_scripts(
    config: RunnableConfig,
    chapter_index: Optional[int] = None,
) -> str:
    """查询已有的有声书编排。用户提到之前生成过/想复用/想继续做有声书时用，
    返回的 [id] 即 audiobook_continue 的 script_id。chapter_index 可选，传了只返回该章的编排。

    Args:
        chapter_index: 章节索引，可选；索引加 1 即第几章（查第 3 章传 2）。传了按章过滤。

    Returns:
        编排总数与编排清单（id、所属章节号、名称、状态）；条数多时只列前若干条，
        可再传 chapter_index 分章查看。无编排或该章无编排时返回提示。
    """
    from config.db_conf import AsyncSessionLocal
    from crud.AudioBookScript import get_scripts_by_project
    from crud.Chapter import get_chapter_index_map

    project_id = current_project(config)
    PAGE_SIZE = 100
    MAX_ROWS = 2000
    MAX_PAGES = 50
    MAX_LINES = 60

    async with AsyncSessionLocal() as db:
        # ---- 1. 分页拉取。total 只作参考，终止以"空页 / 短页且凑够数 / 硬上限"为准 ----
        scripts, total, offset, pages = [], 0, 0, 0
        while len(scripts) < MAX_ROWS and pages < MAX_PAGES:
            page, total = await get_scripts_by_project(db, project_id, offset, PAGE_SIZE)
            pages += 1
            if not page:
                break  # 空页 = 真到底（比 total 可信）
            scripts.extend(page)
            offset += len(page)  # 按实际返回数推进，兼容 limit 被内部截小
            if len(page) < PAGE_SIZE and len(scripts) >= total:
                break  # 不满一页且总数已凑齐 = 自然收尾
        maybe_more = pages >= MAX_PAGES or len(scripts) >= MAX_ROWS

        if not scripts:
            return "该项目的有声书编排为空"

        # ---- 2. 章节映射：轻量查询只取 id + chapter_index 两列，不碰 3 万字正文 ----
        idx_to_id, id_to_idx = await get_chapter_index_map(db, project_id)

    # ---- 3. 按章过滤（映射查一次，不在循环里反复查）----
    if chapter_index is not None:
        target_id = idx_to_id.get(chapter_index)
        if target_id is None:
            return f"项目里没有第 {chapter_index + 1} 章（chapter_index={chapter_index}）"
        scripts = [s for s in scripts if getattr(s, "chapter_id", None) == target_id]
        if not scripts:
            return f"第 {chapter_index + 1} 章还没有有声书编排（该项目其他章共约 {total} 条）"

    # ---- 4. 按章节序排序后组装输出 ----
    entries = []
    for s in scripts:
        idx = id_to_idx.get(getattr(s, "chapter_id", None))
        key = idx if idx is not None else 10 ** 9  # 悬空章节排最后
        label = f"第{idx + 1}章" if idx is not None else f"章节id={getattr(s, 'chapter_id', '?')}"
        state = "已有成品" if (getattr(s, "audio_path", "") or "").strip() else "进行中/待合成"
        entries.append((key, s.id, f"· [{s.id}] {label}｜{s.name}｜{state}"))
    entries.sort()

    lines = [e[2] for e in entries]
    shown = "\n".join(lines[:MAX_LINES])
    omitted = len(lines) - MAX_LINES
    scope = f"第 {chapter_index + 1} 章的" if chapter_index is not None else "项目的"
    count = f"至少 {len(scripts)} 条" if maybe_more else f"共 {len(scripts)} 条"
    msg = f"{scope}有声书编排{count}：\n{shown}"
    if omitted > 0:
        msg += f"\n……另有 {omitted} 条未列出，可传 chapter_index 分章查看"
    if maybe_more:
        msg += f"\n（条数较多，仅加载前 {len(scripts)} 条）"
    return msg


TOOLS = [audiobook_create, audiobook_continue, get_audio_resources, get_audiobook_scripts]

DISPLAY = {
    "audiobook_create": "创建有声书",
    "audiobook_continue": "继续有声书",
    "get_audio_resources": "查音频资源",
    "get_audiobook_scripts": "查有声书编排",
}
