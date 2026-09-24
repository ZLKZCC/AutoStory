from agent.models.loader import get_chat_model, get_context_window
from agent.state import AgentState
from agent.config.tools import registry


async def think_node(state: AgentState):
    """请求模型产出下一轮 AIMessage，并把生效的上下文窗口写回 state。

    工具按全业务域装配：只读域(project/chapter-读/research/audiobook-读/delegation)
    + 写入人审域(project-写/chapter-写/character-写)；主 agent 不亲自写长文。
    """
    model = await get_chat_model("chat")
    bound = model.bind_tools(registry.all) if registry.all else model
    ai_message = await bound.ainvoke(state["system_prompt"] + state["messages"])
    window = state.get("context_window") or await get_context_window("chat")
    return {"messages": [ai_message], "context_window": window}
