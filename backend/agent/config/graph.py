import asyncio

from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph import StateGraph, START, END

from agent.config.checkpoints import checkpoints
from agent.config.settings import settings
from agent.config.tools import registry
from agent.nodes.act import act_node
from agent.nodes.compress import compress_node
from agent.nodes.context import context_node
from agent.nodes.think import think_node
from agent.state import AgentState
from config.store import DEFAULT_CONTEXT_WINDOW


class MainGraph:
    """进程级主图单例。

    实例化只装配工具表（便宜，进程内一次）；编译产物惰性生成并缓存。
    """

    instance = None

    def __new__(cls):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        if getattr(self, "initialized", False):
            return                  # 重复 MainGraph() 不重建工具表与锁（单例只装配一次）
        self.initialized = True
        self.tools = registry.all     # 全量工具表（registry 装配一次，各处共用同一份）
        self.compiled = None
        self.lock = asyncio.Lock()

    # ── token 口径：压缩触发 + 前端圆环共用 ──

    def count_state_tokens(self, messages: list, system_prompt: list | None = None) -> int:
        """统一 token 估算口径。

        真实送进 LLM 的上下文 = system_prompt（人设 + 项目摘要 + 历史摘要，是 AgentState 的
        独立字段、不在 messages 里）+ messages（历史 + 本轮，含回放的 tool_call 对）+ 工具定义。
        三者都计入，才是 ContextRing 该显示的"已用上下文"、也是判断是否触顶该压缩的正确依据
        （此前只数 messages + 工具、漏算 system_prompt → 显示与压缩阈值都系统性偏低）。
        """
        all_messages = list(system_prompt or []) + list(messages or [])
        return count_tokens_approximately(all_messages, chars_per_token=settings.chars_per_token,
                                          tools=self.tools)

    def route_after_act(self, state: AgentState) -> str:
        """act 后判断：本轮上下文（含 system_prompt）超阈值则进 compress 压缩，否则回 think 继续。"""
        window = state.get("context_window") or DEFAULT_CONTEXT_WINDOW
        used = self.count_state_tokens(state["messages"], state.get("system_prompt"))
        return "compress" if used >= window * settings.compress_ratio else "think"

    def route_after_think(self, state: AgentState) -> str:
        """无调用 → END；其余全部进 act —— 有声书也是其中一个工具。

        早前有声书单独走「think → 子图节点」，代价是本轮一起发出的其它工具调用会被填
        「已跳过」。现在它就在 act 里：管线每个步骤与每处人审各自包成 `@task`，resume 重放
        时已完成的任务命中缓存、未完成的那个才真跑。关键点见 `agent/audiobook_pipeline.py`
        的说明 —— 管线必须按**固定顺序**推进，跳步会让 task 的调用序号错位。
        """
        last = state["messages"][-1]
        calls = getattr(last, "tool_calls", None) or []
        if not calls:
            return END
        return "act"

    # ── 装配 ──

    def build(self, checkpointer=None):
        """纯同步组装。checkpointer 可注入（测试传 InMemorySaver），缺省走持久层。

        act 单节点串行执行本轮全部工具：写入工具的人审、有声书的四处审核都在其内部 park，
        靠各自包成 `@task` 保证重放时不重复执行、且每张卡拿到自己的裁决值。
        """
        graph = StateGraph(AgentState)
        graph.add_node("context", context_node)
        graph.add_node("think", think_node)
        graph.add_node("act", act_node)
        graph.add_node("compress", compress_node)

        graph.add_edge(START, "context")
        # context 出口与 act 出口共用同一阈值判定（超阈值进 compress，否则回 think）
        graph.add_conditional_edges("context", self.route_after_act)
        graph.add_conditional_edges("think", self.route_after_think)
        graph.add_conditional_edges("act", self.route_after_act)
        graph.add_edge("compress", "think")
        return graph.compile(checkpointer=checkpointer)

    async def get(self):
        """唯一运行时入口：进程级单例，与 streaming / 路由共享同一张图。"""
        if self.compiled is None:
            async with self.lock:
                if self.compiled is None:
                    self.compiled = self.build(await checkpoints.get())
        return self.compiled


main_graph = MainGraph()
