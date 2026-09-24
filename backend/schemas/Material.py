from pydantic import BaseModel, Field, ConfigDict


class MaterialBase(BaseModel):
    """Material 基础信息"""
    material_name: str = Field(..., description="素材库名")
    description: str = Field("", description="素材库描述")
    model_config = ConfigDict(from_attributes=True)


class MaterialDetail(MaterialBase):
    """Material 完整信息"""
    id: int = Field(..., description="素材库id")
