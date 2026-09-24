import asyncio
import json
import threading
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import PrivateAttr


# ── 消息转换：LangChain ⇄ zai（OpenAI wire 格式） ──────────────

def message_to_dict(m: BaseMessage) -> dict:
    if isinstance(m, HumanMessage):
        return {"role": "user", "content": m.content}
    if isinstance(m, SystemMessage):
        return {"role": "system", "content": m.content}
    if isinstance(m, ToolMessage):
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    if isinstance(m, AIMessage):
        # GLM 要求：纯 tool_calls 的 assistant 消息 content 为 None 而非空串
        d: Dict[str, Any] = {"role": "assistant", "content": m.content or None}
        if m.tool_calls:
            d["tool_calls"] = [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"],
                              "arguments": tc["args"] if isinstance(tc["args"], str)
                              else json.dumps(tc["args"], ensure_ascii=False)}}
                for tc in m.tool_calls
            ]
        return d
    raise TypeError(f"不支持的消息类型: {type(m).__name__}")


def parse_tool_arguments(raw: str) -> dict:
    """流式/非流式 tool_call 的 arguments（JSON 字符串）→ dict，坏 JSON 兜底"""
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {"_raw_arguments": raw}


def response_to_ai_message(msg: Any) -> AIMessage:
    """zai CompletionMessage → AIMessage（含 tool_calls / reasoning_content）"""
    tool_calls = [
        {"id": tc.id, "name": tc.function.name, "type": "tool_call",
         "args": parse_tool_arguments(tc.function.arguments)}
        for tc in (getattr(msg, "tool_calls", None) or [])
    ]
    add_kwargs: Dict[str, Any] = {}
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        add_kwargs["reasoning_content"] = reasoning
    return AIMessage(content=msg.content or "", tool_calls=tool_calls,
                     additional_kwargs=add_kwargs)


def delta_to_chunk(delta: Any) -> Optional[AIMessageChunk]:
    """流式 delta → AIMessageChunk；tool_calls 用 tool_call_chunks 增量（消费端 + 合并）"""
    pieces: List[AIMessageChunk] = []
    if getattr(delta, "content", None):
        pieces.append(AIMessageChunk(content=delta.content))
    reasoning = getattr(delta, "reasoning_content", None)
    if reasoning:
        pieces.append(AIMessageChunk(content="",
                                     additional_kwargs={"reasoning_content": reasoning}))
    tcs = getattr(delta, "tool_calls", None) or []
    if tcs:
        chunks: List[Dict[str, Any]] = []
        for tc in tcs:
            c: Dict[str, Any] = {"index": tc.index}
            if tc.id:
                c["id"] = tc.id
            if tc.function:
                if tc.function.name:
                    c["name"] = tc.function.name
                if tc.function.arguments:
                    c["args"] = tc.function.arguments
            chunks.append(c)
        pieces.append(AIMessageChunk(content="", tool_call_chunks=chunks))
    if not pieces:
        return None
    out = pieces[0]
    for p in pieces[1:]:
        out = out + p
    return out


# ── ChatZhipuAI ───────────────────────────────────────────────

class ChatZhipuAI(BaseChatModel):
    """智谱 GLM。支持流式、工具调用、思考模式（reasoning_content 透传）"""

    model: str = "glm-4.6"
    api_key: Optional[str] = None
    base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    temperature: Optional[float] = 0.7  # None=推理/思考模型不传（服务端拒收）；否则 0.0~2.0
    max_tokens: Optional[int] = None
    thinking_enabled: bool = False     # 显式开 GLM 思考模式（不传时按模型默认）

    _client: Any = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "zhipu-glm"

    @property
    def lc_secrets(self) -> Dict[str, str]:
        return {"api_key": "ZHIPUAI_API_KEY"}

    def get_client(self) -> Any:
        """懒加载：zai-sdk 未装时类定义不受影响，实例化调用才报错（显式失败）"""
        if self._client is None:
            from zai import ZhipuAiClient
            self._client = ZhipuAiClient(api_key=self.api_key,
                                         base_url=self.base_url)
        return self._client

    def build_payload(self, messages: List[dict], **kwargs) -> dict:
        payload: Dict[str, Any] = {"model": self.model, "messages": messages}
        if self.temperature is not None:      # None=推理模型不传 temperature（服务端拒收）
            payload["temperature"] = self.temperature
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        if self.thinking_enabled:
            payload["thinking"] = {"type": "enabled"}
        payload.update(kwargs)      # bind_tools 绑定的 tools / tool_choice 从这里进
        return {k: v for k, v in payload.items() if v is not None}

    # ── 同步 ──
    def _generate(self, messages: List[BaseMessage], stop=None,
                  run_manager: Optional[CallbackManagerForLLMRun] = None,
                  **kwargs) -> ChatResult:
        payload = self.build_payload([message_to_dict(m) for m in messages], stop=stop, **kwargs)
        resp = self.get_client().chat.completions.create(**payload)
        return ChatResult(generations=[
            ChatGeneration(message=response_to_ai_message(resp.choices[0].message))
        ])

    # ── 异步：无 async SDK，to_thread 桥接 ──
    async def _agenerate(self, messages: List[BaseMessage], stop=None,
                         run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
                         **kwargs) -> ChatResult:
        # run_manager 不透传：Async 管理器与 _generate 的同步参数类型不符，
        # 且 _generate 未用回调；公开层 ainvoke 自己管理回调生命周期
        return await asyncio.to_thread(self._generate, messages, stop, None, **kwargs)

    # ── 流式：守护线程生产，Queue 送回事件循环 ──
    async def _astream(self, messages: List[BaseMessage], stop=None,
                       run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
                       **kwargs):
        payload = self.build_payload([message_to_dict(m) for m in messages],
                                     stream=True, stop=stop, **kwargs)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _produce() -> None:
            try:
                for chunk in self.get_client().chat.completions.create(**payload):
                    piece = None
                    if chunk.choices:
                        piece = delta_to_chunk(chunk.choices[0].delta)
                    if piece is not None:
                        loop.call_soon_threadsafe(queue.put_nowait, piece)
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except Exception as e:    # 生产线程任何异常送回异步侧抛出
                loop.call_soon_threadsafe(queue.put_nowait, e)

        threading.Thread(target=_produce, daemon=True).start()
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            # 1.x 契约：_astream 产出 ChatGenerationChunk（公开 astream 读 chunk.message
            # 补 id / 发回调 / yield），裸 AIMessageChunk 会在包装层炸 AttributeError
            gen = ChatGenerationChunk(message=item)
            if run_manager and item.content:
                await run_manager.on_llm_new_token(item.content, chunk=gen)
            yield gen

    def bind_tools(self, tools, **kwargs):
        formatted = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=formatted, **kwargs)

    def with_structured_output(self, schema, **kwargs):
        """结构化输出（function-calling 通道）。

        GLM 无 json_schema response_format，故 method 等参数一律忽略，
        走 bind_tools + 解析 tool_call 的统一路径（agent.models.structured）。
        kwargs 吞掉是为了兼容调用方传 method="json_schema" 不报错。
        """
        from agent.models.structured import structured_model
        return structured_model(self, schema)
