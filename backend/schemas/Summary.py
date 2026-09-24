from pydantic import BaseModel, Field, ConfigDict


class SummaryBase(BaseModel):
    project_id: int = Field(..., description="项目id")
    chatcontext: str = Field(..., description="聊天上下文摘要")
    index: int = Field(..., description="排序索引")
    model_config = ConfigDict(from_attributes=True)

class SummaryCreate(SummaryBase):
    pass

class SummaryDetail(SummaryBase):
    id: int = Field(..., description="摘要id")
