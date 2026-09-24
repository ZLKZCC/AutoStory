from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command

from agent.config.checkpoints import checkpoints
from agent.config.graph import main_graph
from agent.config.tools import registry
from config.store import DEFAULT_CONTEXT_WINDOW


class EnvelopeFactory:
    """信封工厂：一个流持有一个实例，seq 自增，统一产出 {type, seq, data}。"""

    def __init__(self) -> None:
        self.seq = 0

    def make(self, event_type: str, data: dict) -> dict:
        self.seq += 1
        return {"type": event_type, "seq": self.seq, "data": data}


class AgentStream:
    """图执行 → SSE 信封流。"""

    instance = None

    def __new__(cls):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    @staticmethod
    def to_jsonable(value: Any) -> Any:
        """粗暴可序列化：dict/list 递归，其余 str()。"""
        if isinstance(value, dict):
            return {key: AgentStream.to_jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [AgentStream.to_jsonable(item) for item in value]
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        return str(value)

    @staticmethod
    def collect_interrupts(state) -> list:
        """收集图当前待处理的中断。
        @task（act 内工具 / 有声书管线）的 interrupt 挂嵌套 task（state.tasks[*].tasks），
        递归一层收集。"""
        found = []
        for task in getattr(state, "tasks", []) or []:
            found.extend(task.interrupts or [])
            for sub_task in getattr(task, "tasks", None) or []:
                found.extend(sub_task.interrupts or [])
        return found

    async def run(
        self,
        project_id: int,
        thread_id: str,
        summary: str,
        project_summary: str,
        history_messages: list,
        user_text: str,
        resume_value: Any = None,
        project_name: str = "",
        project_description: str = "",
    ) -> AsyncGenerator[dict, None]:

        graph = await main_graph.get()
        # project_id 注入 config.configurable：工具（经 RunnableConfig）与 compress/save_summary
        # 都从这取当前项目，不再放 AgentState；resume 每轮重新传 config，值全程稳定
        config = {"configurable": {"thread_id": thread_id, "project_id": project_id}}
        envelope = EnvelopeFactory()
        final_text: list[str] = []
        pending_break = False  # 已发 tool_call → 下一段 think 叙述前补空行，防多轮文本粘连
        done_sent = False
        pre_interrupt_ids = set()  # 恢复前 pending 的中断 id（收尾过滤刚被消费的残留用）
        if resume_value is not None:
            astream_input = Command(resume=resume_value)

            try:
                pre_state = await graph.aget_state(config)
                pre_interrupt_ids = {
                    getattr(item, "id", None)
                    for item in self.collect_interrupts(pre_state)
                    if getattr(item, "id", None)
                }
            except Exception:
                pre_interrupt_ids = set()
        else:
            astream_input = {
                "messages": [*history_messages, ("user", user_text)],
                "project_name": project_name,
                "project_description": project_description,
                "summary": summary,
                "project_summary": project_summary,
            }

        try:
            # 无子图架构（astream 未传 subgraphs=True）：多模式产出为 (mode, payload) 二元组，
            # 三元解包会在首个事件上直接 ValueError（agent/test.py 已验证产出格式）。
            async for mode, payload in graph.astream(
                astream_input,
                config,
                stream_mode=["messages", "updates", "custom"],
            ):
                if mode == "messages":
                    chunk, meta = payload
                    node = meta.get("langgraph_node", "")
                    text = chunk.content if isinstance(chunk.content, str) else ""
                    # 完整 AIMessage（on_chat_model_end）在 chunk 流后重发一次：
                    # 已有增量则跳过（去重）；无增量的非流式模型才整条发
                    if isinstance(chunk, AIMessage) and not isinstance(chunk, AIMessageChunk):
                        if final_text:
                            continue
                    # 只有 think（主 agent 叙述）算聊天正文；act 内 @task 跑的工具 /
                    # 有声书管线 LLM 的 node 标签为 "act"，不作为正文转发
                    if text and node in ("think", ""):
                        # 工具调用后的新一轮叙述：与上一段 think 文本间补空行。
                        # UI 流式时有工具卡片视觉分隔，但 done.content 拼接后历史回放会粘连；
                        # 模型过渡语常已自带 \n 结尾（deepseek 习惯），尾部已是换行就不补，避免双重空行
                        if pending_break and final_text and not "".join(final_text[-3:]).endswith("\n"):
                            final_text.append("\n\n")
                            yield envelope.make("token", {"text": "\n\n"})
                        pending_break = False
                        final_text.append(text)
                        yield envelope.make("token", {"text": text})

                elif mode == "updates":
                    # payload 是 {node_name: update_dict}（并行节点可多键）
                    for node, update in payload.items():
                        # task 级更新：act 里每个工具调用包成一个 task，完成即单独冒泡，
                        # 此时 payload 直接是 ToolMessage。据此即时发 tool_result，
                        # 不必等 act 整体跑完（写入人审可能让它再 park 好几轮）。
                        if isinstance(update, ToolMessage):
                            yield envelope.make("tool_result", {
                                "call_id": update.tool_call_id,
                                "result": str(update.content)[:4000],
                                "error": None if update.status != "error" else str(update.content),
                            })
                            continue
                        # LangGraph 中断时 updates 流会混入 {"__interrupt__": (Interrupt(...),)}
                        # —— value 是 Interrupt tuple 而非节点输出 dict，直接 .get 会炸
                        # （AttributeError: 'tuple' object has no attribute 'get'）。
                        # 中断信息由下方 aget_state + collect_interrupts 统一转 awaiting_input，
                        # 直接跳过非 dict 条目（同时兼容其他内部条目）。
                        if not isinstance(update, dict):
                            continue
                        for message in update.get("messages", []):
                            if isinstance(message, ToolMessage):
                                if node == "act":
                                    continue   # act 的工具结果已随各 task 实时发出，勿重发
                                yield envelope.make("tool_result", {
                                    "call_id": message.tool_call_id,
                                    "result": str(message.content)[:4000],
                                    "error": None if message.status != "error" else str(message.content),
                                })
                            else:
                                for call in getattr(message, "tool_calls", None) or []:
                                    yield envelope.make("tool_call", {
                                        "call_id": call["id"],
                                        "tool": call["name"],
                                        "display_name": registry.display_name(call["name"]),
                                        "arguments": self.to_jsonable(call["args"]),
                                    })
                                    pending_break = True

                elif mode == "custom":
                    # writer(data) 只送 data 无事件名 → 发送方约定 data["type"]。
                    # act 内有声书管线 @task 用 get_stream_writer() 发的 _progress
                    # （audiobook_progress）正是要转发的，全部透传。
                    data = dict(payload)
                    event_type = data.pop("type", None) or "custom"
                    yield envelope.make(event_type, self.to_jsonable(data))

            # ── 中断检查：图暂停则补 awaiting_input（递归收集子图嵌套 task）──
            state = await graph.aget_state(config)
            pending = self.collect_interrupts(state)

            for interrupt_item in pending:
                yield envelope.make("awaiting_input", {
                    "prompt": "等待用户操作",
                    "payload": self.to_jsonable(interrupt_item.value),
                })
            # 图真正跑完 = 无下一步节点 且 无待处理中断。
            # 多个写入工具同轮时中断逐个 resolve，每次 resume 后 state.next 可能已空但仍有 pending 中断，
            # 此时绝不能判完成，否则会提前发 done 并删掉 checkpoint，后续中断无法 resume（写入丢失）。
            if not state.next and not pending:
                # 累计已用 token（截止本轮结束：system_prompt + history + 本轮 + 工具定义，与压缩触发同口径）
                tokens_used = main_graph.count_state_tokens(
                    state.values.get("messages", []) or [], state.values.get("system_prompt")
                )
                # 上下文窗口（think 节点写入 state；缺省回退 DEFAULT_CONTEXT_WINDOW）——
                # 前端圆环分母单一事实来源：随活动模型的 context_length 自动变
                window = state.values.get("context_window") or DEFAULT_CONTEXT_WINDOW
                yield envelope.make("done", {
                    "content": "".join(final_text),
                    "tokens_used": tokens_used,
                    "context_window": window,
                })
                done_sent = True
                # 单轮正常走完：删除该 thread 的 checkpoint（中断/异常路径保留以便恢复）
                try:
                    await checkpoints.delete_thread(config["configurable"]["thread_id"])
                except Exception:
                    pass

        except Exception as exc:
            yield envelope.make("error", {"message": f"{type(exc).__name__}: {exc}"})

        finally:
            if not done_sent:
                # 异常路径已发 error；中断路径上文已发 awaiting_input 且 state.next 非空
                pass


agent_stream = AgentStream()
