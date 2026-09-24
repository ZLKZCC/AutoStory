from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from agent.models.loader import get_chat_model
from agent.config.settings import settings
from agent.subagents.assignment import Assignment, render_assignment

# 未收敛兜底：不返回最后一轮 content（那可能是检索工具的 ToolMessage 原文、
# 会被主 agent 误当成分析/正文结论）；给明确的非空信号，让主 agent 知道这次委派没成。
UNCONVERGED_NOTICE = (
    "（子agent经多轮检索仍未收敛，本次无有效结论；"
    "请缩小任务范围或改由主 agent 直接处理，不要原样重复委派）"
)

NO_CONTENT_NOTICE = "（子agent未产出有效内容）"


def content_to_text(content) -> str:
    """把模型返回的 content 统一抽成纯文本（兼容多模态：str 直接返回，list 块取各 text 拼接）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return "" if content is None else str(content)


async def build_tool_messages(tool_calls: list, tools: list) -> list[ToolMessage]:
    """执行模型请求的 tool_calls，逐条包成 ToolMessage 喂回（未知工具、执行异常都转成文本）。"""
    tool_by_name = {tool.name: tool for tool in tools}
    messages = []
    for call in tool_calls:
        name = call.get("name", "")
        args = call.get("args", {}) or {}
        tool = tool_by_name.get(name)
        if tool is None:
            content = f"（未知工具：{name}）"
        else:
            try:
                content = await tool.ainvoke(args)
            except Exception as exc:
                content = f"（工具 {name} 执行出错：{exc}）"
        messages.append(ToolMessage(content=str(content), tool_call_id=call.get("id", "")))
    return messages


async def invoke_with_tools(
    messages: list,
    tools: list,
    purpose: str = "writer",
) -> str:
    """
    工具化子agent底层执行器：预组装 messages + tools → 多轮 ainvoke → 最终文本

    工作方式：
    1. model.bind_tools(tools)（tools 为空则退化成普通 model）
    2. 循环 ainvoke：若 response 有 tool_calls → 执行工具 → ToolMessage 喂回 → 继续；
       无 tool_calls → 返回 content
    3. 中间所有 AIMessage(tool_calls) 与 ToolMessage 都**不**回传调用方，只取最终 content
    4. settings.max_tool_iter 兜底：超过仍没收敛，返回明确的非空"未收敛"信号（不抛错、也不返回空/检索原文，
       避免主 agent 误判"子agent没给东西"而反复重唤、白白烧额度）

    messages:  预组装的初始消息列表（SystemMessage + HumanMessage 等）
    tools:     BaseTool 列表（@tool 装饰）；为空则单次 ainvoke（向后兼容）
    purpose:   模型档位（writer/pipeline/summarize，见 loader.get_chat_model）
    """
    model = await get_chat_model(purpose)
    bound = model.bind_tools(tools) if tools else model

    # 复制初始消息，循环中追加；不修改调用方的 list
    conversation = list(messages)

    for _ in range(settings.max_tool_iter):
        response = await bound.ainvoke(conversation)
        conversation.append(response)

        # 无 tool_calls = 模型给出最终文本，结束
        if not response.tool_calls:
            text = content_to_text(response.content).strip()
            return text or NO_CONTENT_NOTICE

        conversation.extend(await build_tool_messages(response.tool_calls, tools))

    return UNCONVERGED_NOTICE


async def invoke_subagent_with_tools(
    persona: str,
    assignment: Assignment,
    tools: list,
    purpose: str = "writer",
) -> str:
    """
    工具化子agent入口：persona + 任务书 + tools → 最终文本

    persona:    子agent人设（subagents/prompts.py，含【知识库】工具使用指引）
    assignment: 任务书（主agent调用方组装）
    tools:      该子agent专属的检索工具列表（writing→kb_/analysis→an_/summary→sm_）
    purpose:    模型档位
    """
    messages = [
        SystemMessage(persona),
        HumanMessage(render_assignment(assignment)),
    ]
    return await invoke_with_tools(messages, tools, purpose)
