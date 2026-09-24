from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class CharacterBase(BaseModel):
    character_name: str = Field(..., description="角色名")
    gender: str = Field(..., description="角色性别")
    role: str = Field(..., description="角色类型")
    model_config = ConfigDict(from_attributes=True)

class CharacterDetail(CharacterBase):
    id: int = Field(..., description="角色id")

class CharacterCreate(CharacterBase):
    pass
