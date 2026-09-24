from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_config
from langgraph.errors import GraphInterrupt
from langgraph.func import task

from agent.config.tools import registry
from agent.state import AgentState


def last_tool_call_message(state: AgentState):
    """最近一条带 tool_calls 的 AIMessage（act 节点与路由共用）。"""
    for message in reversed(state["messages"]):
        if isinstance(message, AIMessage) and message.tool_calls:
            return message
    return None


async def invoke_tool(tool, call: dict, config) -> ToolMessage:
    """执行单个工具调用：异常按语义落成 ToolMessage，GraphInterrupt 放行。

    ainvoke(tool_call) 已返回 ToolMessage（含注入的 call_id / status），非 ToolMessage 时兜底包一层。
    """
    try:
        result = await tool.ainvoke(call, config)
        return result if isinstance(result, ToolMessage) else ToolMessage(
            content=str(result), tool_call_id=call["id"], name=call["name"],
        )
    except GraphInterrupt:
        raise   # 中断控制流必须放行，让图 park
    except Exception as exc:
        return ToolMessage(
            content=f"{type(exc).__name__}: {exc}",
            tool_call_id=call["id"], name=call["name"], status="error",
        )


@task
async def run_tool(call: dict) -> ToolMessage:
    """执行单个工具调用（写入工具内部的人审 interrupt 也在其中）。

    project_id 由 streaming 层放进 config.configurable，工具经 RunnableConfig 自取，
    不经过图 state、也不经过模型。call 是确定值，task 缓存键因此稳定。
    """
    tool = registry.by_name.get(call["name"])
    if tool is None:
        return ToolMessage(
            content=f"未知工具：{call['name']}", tool_call_id=call["id"], status="error",
        )
    return await invoke_tool(tool, call, get_config())


async def act_node(state: AgentState):
    """串行执行本轮全部 tool_calls；写入工具走到人审时在此 park。"""
    ai_message = last_tool_call_message(state)
    if ai_message is None:
        return {}

    messages: list = []
    for call in ai_message.tool_calls:
        messages.append(await run_tool(call))
    return {"messages": messages} if messages else {}
