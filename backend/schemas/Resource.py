from pydantic import BaseModel, Field, ConfigDict


class ResourceBase(BaseModel):
    """Resource 基础信息"""
    Audio_name: str = Field(..., description="音频名字")
    description: str = Field("", description="描述")
    # 模型字段名为 audio_type，from_attributes 按别名取值，序列化仍输出 audiotype
    audiotype: str = Field("sfx", validation_alias="audio_type", description="音频种类描述")
    model_config = ConfigDict(from_attributes=True)

class ResourceNoCreate(ResourceBase):
    """Resource 安全信息 (不包含路径)"""
    path: str = Field("", description="音频路径")

class ResourceDetail(ResourceBase):
    """Resource 完整信息"""
    id: int = Field(..., description="音频id")
    path: str = Field(..., description="音频路径")

class ResourceNoPath(ResourceBase):
    """Resource 安全信息 (不包含路径)"""
    id: int = Field(..., description="音频id")
