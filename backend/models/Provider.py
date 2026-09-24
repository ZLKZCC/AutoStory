from models.Base import Base
from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column



class Provider(Base):
    __tablename__ = "provideer"

    id: Mapped[int] = mapped_column(primary_key=True,comment="书籍id")
    provider_name: Mapped[str] = mapped_column(String(255), comment="供应商名字")
    kind: Mapped[str] = mapped_column(String(255), comment="厂商预设id（openai/anthropic/gemini/zhipu/qwen/ollama/custom等，前端LLM_PRESETS的id）")
    api_url: Mapped[str] = mapped_column(String(255), comment="api")
    api_key: Mapped[str] = mapped_column(String(255), comment="apikey")
    model_id: Mapped[str] = mapped_column(String(50),comment="模型名")
    context_length: Mapped[int] = mapped_column(Integer,comment="模型上下文")
    active: Mapped[bool] = mapped_column(Boolean,default=False,insert_default=False,comment="是否激活")