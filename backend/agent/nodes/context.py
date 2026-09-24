from langchain_core.runnables import RunnableConfig
from agent.prompts import render_system_prompt
from agent.state import AgentState

async def context_node(state: AgentState, config: RunnableConfig):
    """每轮入口：渲染 system_prompt（人设 + 项目摘要 + 历史摘要）写入 state。
    近窗工具调用不在此注入——build_context 已把 tool_call 对回放进 messages。"""
    system_prompt = render_system_prompt(
        summary=state.get("summary", ""),
        project_summary=state.get("project_summary", ""),
        project_name=state.get("project_name", ""),
        project_description=state.get("project_description", ""),
    )
    return {"system_prompt": system_prompt}
