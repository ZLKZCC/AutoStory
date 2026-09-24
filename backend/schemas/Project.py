from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class ProjectBase(BaseModel):
    project_name: str = Field(..., description="项目名")
    description: str = Field(default="", description="项目描述")
    Project_summary: str = Field(default="", description="项目对话消息总结")
    concept: Optional[dict] = Field(default=None, description="项目大纲")
    worldline: Optional[dict] = Field(default=None, description="项目世界线")
    model_config = ConfigDict(from_attributes=True)

class ProjectCreate(ProjectBase):
    pass

class ProjectDetail(ProjectBase):
    id: int = Field(..., description="项目id")
    activetime: datetime = Field(..., description="激活时间")