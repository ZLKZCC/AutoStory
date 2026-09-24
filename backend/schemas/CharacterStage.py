from pydantic import BaseModel, Field, ConfigDict


class CharacterStageBase(BaseModel):
    stage_name: str = Field("", description="阶段描述")
    alias_name: str = Field("", description="角色别名")
    gender: str = Field("", description="角色性别")
    chapter_index: int = Field(-1, description="阶段起始章节号(1-based 第几章;-1=章节已删/未绑定)")
    age_Description: str = Field("", description="角色年龄描述")
    appearance_description: str = Field("", description="角色外观描述")
    profile: str = Field("", description="角色侧写")
    voice_description: str = Field("", description="角色音色描述")
    voice_path: str = Field("", description="角色参考音频")

    model_config = ConfigDict(from_attributes=True)

class CharacterStageCreate(CharacterStageBase):
    pass



class CharacterStageDetail(CharacterStageBase):
    id: int = Field(..., description="角色阶段id")
