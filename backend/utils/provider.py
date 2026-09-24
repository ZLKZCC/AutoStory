import httpx
from typing import Any, Dict, Optional



_TIMEOUT = 15.0
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_URL_PRESETS = [
    ("api.deepseek.com", "deepseek"),
    ("api.openai.com", "openai"),
    ("api.anthropic.com", "anthropic"),
    ("bigmodel.cn", "zhipu"),
    ("dashscope.aliyuncs.com", "qwen"),
    ("api.moonshot.cn", "moonshot"),
    ("lingyiwanwu.com", "yi"),
    ("api.minimax.chat", "minimax"),
    ("volces.com", "volcengine"),
    ("generativelanguage.googleapis.com", "gemini"),
    ("api.mistral.ai", "mistral"),
    ("api.x.ai", "xai"),
    ("openrouter.ai", "openrouter"),
    ("localhost:11434", "ollama"),
    ("127.0.0.1:11434", "ollama"),
]

def _ok(models) -> Dict[str, Any]:
    return {"success": True, "models": sorted(set(models))}

def _fail(error: str) -> Dict[str, Any]:
    return {"success": False, "error": error}

# ── 基础请求 ──────────────────────────────

async def _get_json(url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

# ── 各接口形态的探测实现 ──────────────────────────────

async def _probe_openai_compatible(api_url: str, api_key: str) -> Dict[str, Any]:
    """OpenAI 兼容端点：GET {base_url}/models，Bearer 鉴权，响应 {data: [{id}]}"""
    url = f"{api_url.rstrip('/')}/models"
    payload = await _get_json(url, headers={"Authorization": f"Bearer {api_key or 'none'}"})
    return _ok(m["id"] for m in payload.get("data", []) if m.get("id"))

async def _probe_anthropic(api_url: str, api_key: str) -> Dict[str, Any]:
    """Anthropic 原生端点：GET {base}/v1/models（base_url 剥掉前端预设带的 /v1 后缀），
    x-api-key 鉴权，响应 {data: [{id}]}"""
    base = api_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    payload = await _get_json(
        f"{base}/v1/models",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        params={"limit": 100},
    )
    return _ok(m["id"] for m in payload.get("data", []) if m.get("id"))

async def _probe_ollama(api_url: str) -> Dict[str, Any]:
    """Ollama 原生端点：GET {host}/api/tags，无鉴权，响应 {models: [{name}]}
    （预设存裸 host，客户端 ChatOllama 也吃同形态）"""
    url = f"{api_url.rstrip('/')}/api/tags"
    payload = await _get_json(url, headers={})
    return _ok(m["name"] for m in payload.get("models", []) if m.get("name"))

async def _probe_gemini(api_key: str) -> Dict[str, Any]:
    """Gemini 原生端点：GET /v1beta/models，x-goog-api-key 鉴权；
    只保留支持 generateContent 的模型，名称形如 models/gemini-2.0-flash"""
    payload = await _get_json(
        f"{_GEMINI_BASE}/models",
        headers={"x-goog-api-key": api_key},
        params={"pageSize": 200},
    )
    models = []
    for m in payload.get("models", []):
        if "generateContent" in (m.get("supportedGenerationMethods") or []):
            name = m.get("name", "")
            if name.startswith("models/"):
                name = name[len("models/"):]
            if name:
                models.append(name)
    return _ok(models)




def infer_provider(api_url: str) -> str:
    """按 base_url 域名特征推断前端预设 id，未命中按 custom（OpenAI 兼容）处理"""
    url = (api_url or "").lower()
    for host, preset_id in _URL_PRESETS:
        if host in url:
            return preset_id
    return "custom"

# ── 异常翻译 ──────────────────────────────

def _status_error(e: httpx.HTTPStatusError) -> str:
    code = e.response.status_code
    # Gemini 无效 key 返回 400，OpenAI/Anthropic 返回 401/403
    if code in (400, 401, 403):
        return "API Key 无效或未授权"
    if code == 404:
        return "该服务不提供模型列表接口（/models）"
    return f"服务端错误（HTTP {code}）"

# ── 主入口：按前端预设逐家分发 ──────────────────────────────

async def probe_provider(provider: str, api_url: str, api_key: str) -> Dict[str, Any]:
    """按前端 LLM_PRESETS 预设 id 分发探测，统一返回 {success, error?, models?}"""
    if not provider:
        provider = infer_provider(api_url)
    try:
        # ── OpenAI 兼容系（GET {base_url}/models + Bearer 鉴权）──
        if provider == "deepseek":       # DeepSeek 官方
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "openai":         # OpenAI 官方
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "zhipu":          # 智谱 GLM
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "qwen":           # 通义千问 DashScope 兼容模式
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "moonshot":       # Kimi
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "yi":             # 零一万物
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "minimax":        # MiniMax
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "volcengine":     # 火山方舟
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "mistral":        # Mistral
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "xai":            # xAI Grok
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "openrouter":     # OpenRouter 聚合
            return await _probe_openai_compatible(api_url, api_key)
        if provider == "custom":         # 自定义地址，按 OpenAI 兼容尝试
            return await _probe_openai_compatible(api_url, api_key)

        # ── 原生接口系 ──
        if provider == "anthropic":      # Anthropic Messages 原生
            return await _probe_anthropic(api_url, api_key)
        if provider == "gemini":         # Google 原生，忽略自定义地址
            return await _probe_gemini(api_key)
        if provider == "ollama":         # 本地服务，原生 /api/tags（预设存裸 host）
            return await _probe_ollama(api_url)

        # 未知预设 id：按 OpenAI 兼容兜底
        return await _probe_openai_compatible(api_url, api_key)
    except httpx.TimeoutException:
        return _fail("连接超时，请检查网络或服务地址")
    except httpx.ConnectError:
        return _fail("无法连接服务地址，请检查 Base URL 与网络")
    except httpx.HTTPStatusError as e:
        return _fail(_status_error(e))
    except Exception as e:
        return _fail(f"测试失败: {e}")