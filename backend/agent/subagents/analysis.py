from agent.subagents.assignment import Assignment
from agent.subagents.base import invoke_subagent_with_tools
from agent.subagents.prompts import ANALYST_PERSONA
from agent.tools.kb.analysis import TOOLS as ANALYSIS_KB_TOOLS


async def analyze(text: str, focus: str, aspects: list[str] | None = None) -> str:
    """
    分析输入文本。

    text:    待分析的原文（章节/大纲/角色卡/情节链等）
    focus:   分析主问题，如"本章节奏是否拖沓""人物动机是否成立"
    aspects: 可选细分维度（如：节奏/伏笔/逻辑/人物弧光），不传则由子agent自行规划
    """
    assignment = Assignment(
        target=f"分析以下文本。主问题：{focus}",
        must_include=aspects or [],
        style="结论先行，证据在后",
        material=f"【待分析文本】\n{text[:8000]}",
    )
    return await invoke_subagent_with_tools(
        ANALYST_PERSONA, assignment, ANALYSIS_KB_TOOLS, purpose="pipeline"
    )
