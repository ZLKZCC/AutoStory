from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.message import RemoveMessage
from agent.prompts import render_system_prompt
from agent.config.settings import settings
from agent.state import AgentState
from agent.subagents.summary import summarize
from config.store import DEFAULT_CONTEXT_WINDOW
from config.db_conf import AsyncSessionLocal
from crud import Summary as SummaryCrud


def truncate_text(content, limit: int = 1000) -> str:
    """content 可能是 str 或 content block 列表，统一转文本再按长度截断。"""
    if isinstance(content, list):
        text = "\n".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    else:
        text = str(content)
    return text[:limit] + "..." if len(text) > limit else text

def collect_digest_input(messages: list) -> tuple[list, list]:
    contents = []
    record_ids = []
    for message in messages:
        content = message.content
        if message.type == "tool":
            content = truncate_text(content)
        contents.append(content)
        record_id = (message.additional_kwargs or {}).get("record_id")
        if record_id:
            record_ids.append(record_id)
    return contents, record_ids


async def save_summary(digest: str, record_ids: list,
                       config: RunnableConfig) -> None:
    """落 DB：写 Summary(chatcontext=digest) + SummaryChatRecord 映射；失败不阻塞图执行。"""
    # project_id 由 streaming 层注入 config.configurable，不再放 AgentState
    project_id = (config or {}).get("configurable", {}).get("project_id")
    if not (project_id and record_ids):
        return
    try:
        async with AsyncSessionLocal() as db:
            latest = await SummaryCrud.get_latest_summary_by_project(db, project_id)
            next_index = (latest.index + 1) if latest else 1
            new_summary = await SummaryCrud.add_summary(db, project_id, digest, next_index)
            await SummaryCrud.add_summary_chat_records_batch(db, new_summary.id, record_ids)
    except Exception:
        pass  # 落库失败不阻塞图执行；digest 仍随 state 流转


async def compress_node(state: AgentState, config: RunnableConfig):
    """轮内压缩（摘要落 DB）。

    - 阈值触发（settings.compress_ratio=0.7）：消息 token 达窗口 70% 即压
    - 调 summarize 子agent（kind=merge 增量合并旧摘要，对应 RunningSummary 模式）
    - 从被摘要消息收集 record_id，写 Summary + SummaryChatRecord 映射
    - 落库失败不阻塞图执行；digest 仍随 state 流转
    - summarize 是稳定接口预留：未来子agent 工具化后此处改 create_agent.stream()
    """
    messages = state["messages"]
    window = state.get("context_window") or DEFAULT_CONTEXT_WINDOW

    if count_tokens_approximately(state.get("system_prompt")+messages) >= window * settings.compress_ratio:
        digest = state.get("summary", "")
        messages = trim_messages(messages,max_token=window*0.8,token_counter="approximate",strategy="last",)
        dropped = messages[:-settings.keep_tail]
        contents, record_ids = collect_digest_input(dropped)
        digest = await summarize(contents, digest, kind="merge")
        await save_summary(digest, record_ids, config)

        return {"summary": digest,
                "system_prompt": render_system_prompt(
                    summary=digest,
                    project_summary=state.get("project_summary", ""),
                    project_name=state.get("project_name", ""),
                    project_description=state.get("project_description", ""),
                ),
                "messages": [RemoveMessage(id=m.id) for m in dropped]}
