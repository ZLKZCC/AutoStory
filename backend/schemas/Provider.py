from pydantic import BaseModel, Field, ConfigDict


class ProviderBase(BaseModel):
    """Provider 基础信息"""
    provider_name: str = Field(..., description="供应商名字")
    kind: str = Field(..., description="厂商预设id（openai/anthropic/gemini/zhipu/qwen/ollama/custom等）")
    model_id: str = Field(..., description="模型名")
    context_length: int = Field(0, description="模型上下文")
    active: bool = Field(False,description="是否激活")
    model_config = ConfigDict(from_attributes=True)

class ProviderCreate(ProviderBase):
    api_url: str = Field(..., description="api")
    api_key: str = Field(..., description="apikey")

class ProviderDetail(ProviderBase):
    """Provider 完整信息 (包含敏感 API 配置)"""
    id: int = Field(..., description="书籍id")
    api_url: str = Field(..., description="api")
    api_key: str = Field(..., description="apikey")

class ProviderSafe(ProviderBase):
    """Provider 安全信息 (不包含 API 配置)"""
    id: int = Field(..., description="书籍id")