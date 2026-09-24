from pydantic import BaseModel, Field, ConfigDict


class AudioBookScripAudioBase(BaseModel):
    audio_id: int = Field(..., description="选中的配乐/音效资源 id")
    model_config = ConfigDict(from_attributes=True)


class AudioBookScripAudioCreate(AudioBookScripAudioBase):
    script_id: int = Field(..., description="所属脚本 id（audiobookscript.id）")


class AudioBookScripAudioDetail(AudioBookScripAudioBase):
    id: int = Field(..., description="关联行主键")
    script_id: int = Field(..., description="所属脚本 id")


# ── AudioBookScript：脚本主表 ──────────────────────────────

class AudioBookScriptBase(BaseModel):
    name: str = Field(..., description="脚本名")
    project_id: int = Field(..., description="项目id")
    chapter_id: int = Field(..., description="章节id")
    model_config = ConfigDict(from_attributes=True)


class AudioBookScriptCreate(AudioBookScriptBase):
    script_path: str = Field("", description="脚本路径")
    audio_path: str = Field("", description="音频路径")
    mapping: str = Field("", description="角色映射JSON：章中角色名→角色阶段id（确认后的最终版，重合成用）")
    narrator_desc: str = Field("", description="旁白音色描述（重合成用）")
    stage_payload: str = Field("", description="各步中间产物JSON（提取/提案/映射表/脚本概览）")


class AudioBookScriptUpdate(BaseModel):
    """保存修改：更新脚本名与编排 JSON 内容（内容写 script_path 文件，不改表列）"""
    name: str = Field(..., description="脚本名")
    script_content: dict = Field(..., description="编排 JSON 内容")


class AudioBookScriptDetail(AudioBookScriptBase):
    id: int = Field(..., description="脚本id")
    script_path: str = Field("", description="脚本文件路径（空 = 尚未生成）")
    audio_path: str = Field("", description="音频文件路径（空 = 尚未生成音频）")
    mapping: str = Field("", description="角色映射JSON（重合成用）")
    narrator_desc: str = Field("", description="旁白音色描述（重合成用）")
    stage_payload: str = Field("", description="各步中间产物JSON（断点续跑渲染卡片用）")
    audio_ids: list[int] = Field(default_factory=list,
        description="选中配乐资源 id 列表（由 audiobookscriptaudio 表聚合，路由填充）")

class PanelCreateBody(BaseModel):
    project_id: int = Field(..., description="项目id")
    chapter_id: int = Field(..., description="章节id")


class PanelNameBody(BaseModel):
    name: str = Field(..., description="本次有声书的名字")


class PanelProposalConfirmBody(BaseModel):
    """前端可编辑后的提案整体提交（new_characters / voice_supplements 均可增删改）"""
    proposal: dict = Field(..., description="NewCharacterProposal 结构的提案 JSON")


class PanelMappingConfirmBody(BaseModel):
    entries: list[dict] = Field(..., description="连线结果：[{extracted_name, character_id, stage_id, confidence?, reason?}]")


class PanelAudiosBody(BaseModel):
    audio_ids: list[int] = Field(default_factory=list, description="选用的 BGM/SFX 资源 id（整体替换）")


class PanelNarratorBody(BaseModel):
    narrator_desc: str = Field(..., description="旁白音色描述（TTS 音色设计输入）")
    narrator_text: str = Field("", description="试听文本；留空用默认句。必须与生成试听时的文本一致，否则查不到缓存")

