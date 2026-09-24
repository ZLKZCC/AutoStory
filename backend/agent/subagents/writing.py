from agent.subagents.assignment import Assignment
from agent.subagents.base import invoke_subagent_with_tools
from agent.subagents.prompts import WRITER_PERSONA
from agent.tools.kb.writing import TOOLS as WRITING_KB_TOOLS


async def write(assignment: Assignment) -> str:
    """写正文：任务书 → 产出（lint 打回 ≤2 次）"""
    return await invoke_subagent_with_tools(
        WRITER_PERSONA, assignment, WRITING_KB_TOOLS, purpose="writer"
    )


async def revise(original: str, instruction: str) -> str:
    """改稿：保风格、遵指令、最小改动"""
    revision = Assignment(
        target=f"修改以下稿子。指令：{instruction}。原则：保持原文风格，最小改动，只改指令涉及处。",
        material=f"【原稿】\n{original[:8000]}",
    )
    return await write(revision)
