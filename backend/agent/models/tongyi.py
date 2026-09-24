import asyncio
import json
import threading
from typing import Any, Dict, List, Optional

import requests
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


GENERATION_PATHS = [
    "/api/v1/services/aigc/text-generation/generation",
    "/api/v1/services/aigc/multimodal-generation/generation",
]

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com"



def message_to_dict(m: BaseMessage) -> dict:
    if isinstance(m, HumanMessage):
        return {"role": "user", "content": m.content}
    if isinstance(m, SystemMessage):
        return {"role": "system", "content": m.content}
    if isinstance(m, ToolMessage):
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    if isinstance(m, AIMessage):
        d: Dict[str, Any] = {"role": "assistant", "content": m.content or ""}
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
    """tool_call arguments（JSON 字符串）→ dict，坏 JSON 兜底"""
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {"_raw_arguments": raw}


def flatten_content(content: Any) -> str:
    """multimodal path 返回 content 为 [{"text": "..."}] 列表，展平为纯字符串"""
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content
            if isinstance(p, dict) and p.get("text")
        )
    return content or ""


def response_to_ai_message(resp_json: dict) -> AIMessage:
    """DashScope 原生响应 → AIMessage（含 tool_calls / reasoning_content）"""
    output = resp_json.get("output", {}) or {}
    choices = output.get("choices") or []
    if not choices:
        return AIMessage(content="")
    msg = choices[0].get("message", {}) or {}
    content = flatten_content(msg.get("content"))
    tool_calls = [
        {"id": tc.get("id", ""), "name": tc.get("function", {}).get("name", ""),
         "type": "tool_call",
         "args": parse_tool_arguments(tc.get("function", {}).get("arguments", ""))}
        for tc in (msg.get("tool_calls") or [])
    ]
    add_kwargs: Dict[str, Any] = {}
    reasoning = msg.get("reasoning_content")
    if reasoning:
        add_kwargs["reasoning_content"] = reasoning
    return AIMessage(content=content, tool_calls=tool_calls,
                     additional_kwargs=add_kwargs)


def delta_to_chunk(delta: dict) -> Optional[AIMessageChunk]:
    """流式 delta → AIMessageChunk；原生流式的 choices[].message 即增量内容"""
    content = flatten_content(delta.get("content"))
    pieces: List[AIMessageChunk] = []
    if content:
        pieces.append(AIMessageChunk(content=content))
    reasoning = delta.get("reasoning_content")
    if reasoning:
        pieces.append(AIMessageChunk(content="",
                                     additional_kwargs={"reasoning_content": reasoning}))
    tcs = delta.get("tool_calls") or []
    if tcs:
        chunks: List[Dict[str, Any]] = []
        for tc in tcs:
            c: Dict[str, Any] = {"index": tc.get("index", 0)}
            if tc.get("id"):
                c["id"] = tc["id"]
            func = tc.get("function", {}) or {}
            if func.get("name"):
                c["name"] = func["name"]
            if func.get("arguments"):
                c["args"] = func["arguments"]
            chunks.append(c)
        pieces.append(AIMessageChunk(content="", tool_call_chunks=chunks))
    if not pieces:
        return None
    out = pieces[0]
    for p in pieces[1:]:
        out = out + p
    return out


def is_url_error(resp_json: dict) -> bool:
    """DashScope 的 url error：模型绑定在另一条 generation path"""
    code = str(resp_json.get("code", ""))
    message = resp_json.get("message", "")
    return code == "InvalidParameter" and "url error" in message


# ── ChatTongyiAI ───────────────────────────────────────────────

class ChatTongyiAI(BaseChatModel):
    """通义千问。DashScope 原生 API + path 候选遍历。

    支持流式、工具调用、思考模式（reasoning_content 透传）。
    解决 langchain_community ChatTongyi 固定走 text-generation path
    导致部分模型 url error 的问题（自研封装遍历两条 path）。
    """

    model: str = "qwen-plus"
    api_key: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    temperature: Optional[float] = 0.7   # None=推理模型不传
    top_p: float = 0.8
    max_tokens: Optional[int] = None
    request_timeout: int = 60

    _generation_path: str = PrivateAttr(default=GENERATION_PATHS[0])

    @property
    def _llm_type(self) -> str:
        return "tongyi-qwen"

    @property
    def lc_secrets(self) -> Dict[str, str]:
        return {"api_key": "DASHSCOPE_API_KEY"}

    # ── 请求构造 ──

    def request_headers(self, stream: bool = False) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if stream:
            h["Accept"] = "text/event-stream"
            h["X-DashScope-SSE"] = "enable"
            h["X-Accel-Buffering"] = "no"
        return h

    def build_body(self, messages: List[dict], **kwargs) -> dict:
        """构造 DashScope 原生请求体（input.messages + parameters）"""
        params: Dict[str, Any] = {"result_format": "message"}
        if self.temperature is not None:
            params["temperature"] = self.temperature
        params["top_p"] = self.top_p
        if self.max_tokens:
            params["max_tokens"] = self.max_tokens
        # bind_tools 绑定的 tools / tool_choice 从 kwargs 进
        if kwargs.get("tools"):
            params["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice") is not None:
            params["tool_choice"] = kwargs["tool_choice"]
        # 其余 kwargs 透传（stop 等）
        for k in ("stop", "seed", "top_k", "repetition_penalty", "presence_penalty"):
            v = kwargs.get(k)
            if v is not None:
                params[k] = v
        return {
            "model": self.model,
            "input": {"messages": messages},
            "parameters": {k: v for k, v in params.items() if v is not None},
        }

    # ── path 候选遍历 ──

    def candidate_paths(self) -> list:
        """当前 path 优先，其余候选跟后（url error 时切换）"""
        others = [p for p in GENERATION_PATHS if p != self._generation_path]
        return [self._generation_path, *others]

    def build_url(self, path: str) -> str:
        """拼接 base_url + path，自适应消除重复的 /api/v1 前缀。

        DashScope SDK 官方推荐的 base_http_api_url 形态是
        'https://dashscope.aliyuncs.com/api/v1'（带 /api/v1 后缀），
        而完整请求 URL 是 'https://dashscope.aliyuncs.com/api/v1/services/aigc/...'
        （即 base_url 已含 /api/v1，path 只需 /services/aigc/...）。

        本封装把 path 一律写成 '/api/v1/services/aigc/...' 形态，
        在拼接时若 base_url 末尾已是 /api/v1，path 去掉 /api/v1 前缀避免重复。
        这样用户在 Provider 表填哪种形态都对（带 /api/v1 或不带）。
        """
        b = (self.base_url or DEFAULT_BASE_URL).rstrip("/")
        if b.endswith("/api/v1"):
            return b + path[len("/api/v1"):]
        return b + path

    def post_request(self, body: dict, stream: bool = False):
        """调 DashScope 原生 API，path 候选遍历（url error 切换并缓存）"""
        headers = self.request_headers(stream=stream)
        last_err: Any = None
        for path in self.candidate_paths():
            url = self.build_url(path)
            try:
                resp = requests.post(url, json=body, headers=headers,
                                     stream=stream, timeout=self.request_timeout)
            except requests.RequestException as e:
                last_err = e
                continue
            if resp.status_code != 200:
                try:
                    err_json = resp.json()
                except Exception:
                    err_json = {}
                if is_url_error(err_json):
                    last_err = err_json
                    continue    # 模型在另一条 path，切换
                raise RuntimeError(
                    f"DashScope API error: {resp.status_code} - {resp.text[:500]}")
            self._generation_path = path   # 缓存成功的 path
            return resp
        raise RuntimeError(
            f"DashScope 所有 generation path 均失败，最后错误: {last_err}")

    # ── 同步 ──

    def _generate(self, messages: List[BaseMessage], stop=None,
                  run_manager: Optional[CallbackManagerForLLMRun] = None,
                  **kwargs) -> ChatResult:
        body = self.build_body([message_to_dict(m) for m in messages], stop=stop, **kwargs)
        resp = self.post_request(body, stream=False)
        return ChatResult(generations=[
            ChatGeneration(message=response_to_ai_message(resp.json()))
        ])

    # ── 异步：to_thread 桥接（与 zhipu.py 同模式）──

    async def _agenerate(self, messages: List[BaseMessage], stop=None,
                         run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
                         **kwargs) -> ChatResult:
        return await asyncio.to_thread(self._generate, messages, stop, None, **kwargs)

    # ── 流式：守护线程生产，Queue 送回事件循环 ──

    async def _astream(self, messages: List[BaseMessage], stop=None,
                       run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
                       **kwargs):
        body = self.build_body([message_to_dict(m) for m in messages],
                               stop=stop, **kwargs)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _produce() -> None:
            try:
                resp = self.post_request(body, stream=True)
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        raw = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    # 流中错误（200 SSE 带 {code, message}）
                    if raw.get("code"):
                        raise RuntimeError(
                            f"DashScope stream error: {raw.get('code')} - {raw.get('message')}")
                    output = raw.get("output", {}) or {}
                    choices = output.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("message", {}) or {}   # 原生流式用 message
                    piece = delta_to_chunk(delta)
                    if piece is not None:
                        loop.call_soon_threadsafe(queue.put_nowait, piece)
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, e)

        threading.Thread(target=_produce, daemon=True).start()
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            gen = ChatGenerationChunk(message=item)
            if run_manager and item.content:
                await run_manager.on_llm_new_token(item.content, chunk=gen)
            yield gen

    # ── 工具 / 结构化（与 zhipu.py 同模式）──

    def bind_tools(self, tools, **kwargs):
        formatted = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=formatted, **kwargs)

    def with_structured_output(self, schema, **kwargs):
        """结构化输出（function-calling 通道）。

        委托 agent.models.structured 统一层（bind_tools + 解析 tool_call）。
        kwargs 吞掉是为了兼容调用方传 method="json_schema" 不报错。
        """
        from agent.models.structured import structured_model
        return structured_model(self, schema)
