from langchain_core.tools import tool

from agent.subagents.analysis import analyze
from agent.subagents.assignment import Assignment
from agent.subagents.summary import summarize
from agent.subagents.writing import revise, write


@tool(parse_docstring=True)
async def invoke_writing_agent(
    target: str,
    must_include: list[str] = [],
    style: str = "自然、克制、有画面感",
    material: str = "",
) -> str:
    """唤起写作子 agent 撰写小说正文。你（主 agent）负责拆清楚目标与要点，正文交给它写。
    产出文本由你转给用户；用户确认后你须调 save_chapter 落库——正文不进库=没干完。

    任务书填写要点：
    - target 写清本章要推进什么（情节点/转折/人物动作），越具体越好；
    - must_include 提炼用户的硬性要求（伏笔/人物/道具/不许出现的剧情）；
    - style 优先查 search_experience 拿用户偏好，再据本章情绪调整；
    - material 裁剪前情摘要（不是全文）+ 相关角色当前阶段 profile，别整章塞进去。

    Args:
        target: 本章写作目标与情节点,需写清楚要推进什么
        must_include: 必须包含的要点列表,可选,如伏笔、人物、道具等
        style: 文风要求,可选,如"冷峻简练""日常幽默"
        material: 可参考的写作素材,可选,如设定细节、前文摘要

    Returns:
        写作子 agent 产出的正文章节文本。
    """
    return await write(Assignment(
        target=target, must_include=must_include, style=style, material=material,
    ))


@tool(parse_docstring=True)
async def invoke_revise_agent(original: str, instruction: str) -> str:
    """唤起写作子agent修改/润色已有稿子。instruction 写清改什么，要求最小改动。

    Args:
        original: 待修改的原始稿子全文
        instruction: 修改要求,写清要改什么、改到什么程度,尽量最小改动

    Returns:
        修改后的章节文本。
    """
    return await revise(original, instruction)


@tool(parse_docstring=True)
async def invoke_analysis_agent(
    text: str,
    focus: str,
    aspects: list[str] = [],
) -> str:
    """唤起分析子agent对文本/情节/人物做分析。只出结论与依据，不改稿。

    Args:
        text: 待分析的原文,如章节正文、大纲、角色卡等
        focus: 分析主问题,如"本章节奏是否拖沓""人物动机是否成立"
        aspects: 可选细分维度,如 节奏/伏笔/逻辑/人物弧光,不传则由子agent自行规划

    Returns:
        分析结论(逐条 + 置信度 + 可执行建议)。
    """
    return await analyze(text, focus, aspects or None)


@tool(parse_docstring=True)
async def invoke_summary_agent(
    texts: list[str],
    kind: str = "chat",
    previous: str = "",
) -> str:
    """唤起总结子agent压缩/合并文本。轮内压缩由主图内部直接调用,不需要你（主agent）转发。

    Args:
        texts: 待总结的内容片段列表
        kind: 摘要类型,取值 chapter(章节摘要)/chat(对话压缩)/merge(摘要合并),默认chat
        previous: 旧摘要,merge类必传,用于与新内容融合

    Returns:
        摘要文本。
    """
    return await summarize(texts, previous=previous, kind=kind)


TOOLS = [invoke_writing_agent, invoke_revise_agent, invoke_analysis_agent, invoke_summary_agent]

DISPLAY = {
    "invoke_writing_agent": "唤起写作子agent",
    "invoke_revise_agent": "唤起改稿子agent",
    "invoke_analysis_agent": "唤起分析子agent",
    "invoke_summary_agent": "唤起总结子agent",
}
