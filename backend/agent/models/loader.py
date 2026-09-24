import re

from langchain.chat_models import init_chat_model
from sqlalchemy import select

from config.db_conf import AsyncSessionLocal
from models.Provider import Provider
from utils.crypto import decrypt_text
from config.store import get_model_context_window

NATIVE_PROVIDERS = {
    "anthropic": "anthropic",
    "gemini": "google_genai",    # langchain 里叫 google_genai 不是 google
    "deepseek": "deepseek",
    "ollama": "ollama",
    "mistral": "mistralai",     # id 是 mistralai 不是 mistral
    "xai": "xai",
    "openrouter": "openrouter",
}

REASONING_PATTERN = re.compile(
    r"\b(o1|o3|o4)\w*"            # OpenAI o1/o3/o4-mini 等（前缀锚到字母避免误伤）
    r"|kimi-k3"                    # Moonshot kimi-k3
    r"|deepseek?-?r1"             # DeepSeek-R1 / deepseek-r1
    r"|qwq"                        # Qwen qwq
    r"|-reasoning"                 # qwen-reasoning / *-reasoning
    r"|glm-?z1",                   # 智谱 glm-z1（思考模型）
    re.IGNORECASE,
)


def temperature_kwargs(model_id: str) -> dict:
    """推理模型不传 temperature（服务端拒收 → 400）；普通模型传 0.7。

    返回 {"temperature": None}（推理）或 {"temperature": 0.7}（普通）：
    - init_chat_model / ChatOpenAI：temperature=None → 不发给 API
    - ChatZhipuAI：temperature 为 Optional，payload 过滤 None（见 zhipu.py）
    - ChatTongyi：temperature 为 Optional，None 不发
    """
    if REASONING_PATTERN.search(model_id or ""):
        return {"temperature": None}
    return {"temperature": 0.7}


# ── URL 嗅探：以 api_url 反映真实意图，kind 仅作后备 ──────────────
# 用户填 kind 是简化标注，但实际意图看 api_url：
#   - kind="qwen" + url=compatible-mode 端点 → 想走 OpenAI 兼容路径
#   - kind="custom" + url=dashscope 域 → 其实是通义
#   - kind="zhipu" + url=空 → 走智谱默认端点
# url 嗅探成功就以 url 为准；嗅探不出回退 kind。
def sniff_route(api_url: str) -> str | None:
    """通过 api_url 嗅探真实路由标识。返回 None 表示 url 无可辨识线索（回退 kind）。

    返回的是路由标识（可能不同于 kind 的简化标注）：
      qwen_native   — DashScope 原生 API（走自研 ChatTongyiAI + path 候选遍历）
      qwen_compat   — DashScope OpenAI 兼容端点（走标准 OpenAI 路径）
      zhipu         — 智谱 bigmodel.cn（走自研 ChatZhipuAI）
      anthropic/gemini/deepseek/openrouter/xai/mistral — 原生档
      moonshot/yi/minimax/volcengine — OpenAI 兼容档（厂商自家端点）
    """
    if not api_url:
        return None
    u = api_url.lower()
    # DashScope：compatible-mode 是 OpenAI 兼容端点，否则走原生 API + path 遍历
    if "dashscope" in u:
        return "qwen_compat" if "compatible-mode" in u else "qwen_native"
    # 百炼专属端点（ws-xxx.maas.aliyuncs.com）同为 DashScope 原生协议，域名却不含
    # "dashscope" 字样；漏嗅探会走 OpenAI 兜底拼出不存在的 /api/v1/chat/completions → 404
    if "maas.aliyuncs.com" in u:
        return "qwen_compat" if "compatible-mode" in u else "qwen_native"
    if "bigmodel" in u:
        return "zhipu"
    if "anthropic" in u:
        return "anthropic"
    if "generativelanguage.googleapis" in u or "googleapis.com" in u:
        return "gemini"
    if "api.deepseek.com" in u or "deepseek.com" in u:
        return "deepseek"
    if "api.moonshot.cn" in u or "moonshot.cn" in u:
        return "moonshot"
    if "lingyiwanwu" in u:
        return "yi"
    if "minimaxi" in u or "minimax.chat" in u:
        return "minimax"
    if "volces" in u:
        return "volcengine"
    if "openrouter.ai" in u:
        return "openrouter"
    if "api.x.ai" in u or "x.ai" in u:
        return "xai"
    if "api.mistral.ai" in u or "mistral.ai" in u:
        return "mistral"
    return None


def resolve_route(kind: str, api_url: str) -> str:
    """综合 kind 与 api_url 给出真实路由标识。url 优先（反映真实意图），否则回退 kind。

    kind 仍是用户在前端的简化标注，但当 url 提供了线索时以 url 为准——
    用户在 Provider 表里填的 api_url 才是实际请求入口，反映真实意图。
    """
    return sniff_route(api_url) or kind


async def get_active_provider() -> Provider:
    """取 Provider 表 active 行（get_chat_model / get_context_window 共用）"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Provider).where(Provider.active == True)  # noqa: E712
        )).scalar_one_or_none()
        if row is None:
            pass
            #raise RuntimeError("没有激活的 LLM 供应商，请先在前端设置页配置并激活")
        return row


async def get_chat_model(purpose: str = "chat"):
    """
    取当前激活供应商的模型实例

    purpose: chat（主图）/ writer（写作子调用）/ pipeline（结构化/压缩）
    三档当前同源（Provider 表暂无用途字段）

    路由逻辑：url 嗅探优先（反映真实意图），kind 仅作后备。详见 resolve_route。
    """

    row = await get_active_provider()

    api_key = decrypt_text(row.api_key)
    kind = resolve_route(row.kind, row.api_url)    # url 优先，无线索回退 kind


    if kind == "zhipu":
        from agent.models.zhipu import ChatZhipuAI
        return ChatZhipuAI(model=row.model_id, api_key=api_key,
                           base_url=row.api_url, **temperature_kwargs(row.model_id))


    if kind == "qwen" or kind == "qwen_native":
        from agent.models.tongyi import ChatTongyiAI
        base = row.api_url or "https://dashscope.aliyuncs.com"
        # request_timeout=600：长章节脚本生成一次要几分钟，默认 60s 会在 HTTP 层先超时
        return ChatTongyiAI(model=row.model_id, api_key=api_key,
                            base_url=base, request_timeout=600,
                            **temperature_kwargs(row.model_id))


    if kind == "qwen_compat":
        return init_chat_model(row.model_id, model_provider="openai",
                               api_key=api_key, base_url=row.api_url,
                               **temperature_kwargs(row.model_id))

    # ── 原生集成档 ──
    if kind == "anthropic":
        return init_chat_model(row.model_id, model_provider="anthropic",
                               api_key=api_key, base_url=row.api_url,
                               **temperature_kwargs(row.model_id))
    if kind == "ollama":
        return init_chat_model(row.model_id, model_provider="ollama",
                               base_url=row.api_url, **temperature_kwargs(row.model_id))
    if kind == "gemini":
        return init_chat_model(row.model_id, model_provider="google_genai",
                               api_key=api_key, **temperature_kwargs(row.model_id))
    if kind == "deepseek":
        return init_chat_model(row.model_id, model_provider="deepseek",
                               api_key=api_key, base_url=row.api_url,
                               **temperature_kwargs(row.model_id))
    if kind == "openai":
        return init_chat_model(row.model_id, model_provider="openai",
                               api_key=api_key, base_url=row.api_url,
                               **temperature_kwargs(row.model_id))
    if kind in NATIVE_PROVIDERS:
        return init_chat_model(row.model_id, model_provider=NATIVE_PROVIDERS[kind],
                               api_key=api_key, **temperature_kwargs(row.model_id))

    return init_chat_model(row.model_id, model_provider="openai",
                           api_key=api_key, base_url=row.api_url,
                           **temperature_kwargs(row.model_id))


async def get_context_window(purpose: str = "chat") -> int:
    """
    当前激活模型的上下文窗口 token 数

    Provider.context_length 有值（用户显式配置）优先；
    否则走 config.store.get_model_context_window：注册表精确 → 最长前缀 → DEFAULT_CONTEXT_WINDOW
    """
    row = await get_active_provider()
    if row:
        if row.context_length and row.context_length > 0:
            return int(row.context_length)

        return get_model_context_window(row.model_id)
    else:
        return 0
