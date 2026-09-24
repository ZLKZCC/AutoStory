import re
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class ExtractedCharacter(BaseModel):
    name: str = Field(..., description="角色名（章节原文中最常用的称呼）")
    aliases: List[str] = Field(default_factory=list, description="其他称呼/别名")
    evidence: str = Field(..., description="出场证据：摘原文一句含该角色的话")
    scene_hint: str = Field("", description="该角色在本章的场景梗概，30字内")
    voice_hint: str = Field("", description="根据原文推断的音色印象（性别/年龄/气质），20字内")


class ChapterCharacterExtraction(BaseModel):
    characters: List[ExtractedCharacter] = Field(..., description="本章出现的全部说话角色，旁白不算")


class StageDraft(BaseModel):
    stage_name: str = Field(..., description="阶段名（如：青年期/黑化后）")
    alias_name: str = Field("", description="阶段别名")
    gender: str = Field("", description="性别")
    chapter_index: int = Field(..., ge=1, description="该阶段开始的章节号")
    age_Description: str = Field("", description="年龄描述（如：二十出头）")
    appearance_description: str = Field("", description="外貌描述")
    profile: str = Field("", description="性格侧写")
    voice_description: str = Field("", description="音色描述（为 TTS 生成参考）")


class NewCharacterDraft(BaseModel):
    character_name: str = Field(..., description="角色名")
    gender: str = Field("", description="性别")
    role: str = Field("", description="定位（主角/配角/路人）")
    reason: str = Field("", description="为什么需要新建（库里匹配不到的说明）；前端编辑提案后可留空")
    stages: List[StageDraft] = Field(..., min_length=1, description="该角色的阶段，至少一个（本章状态）")


class VoiceSupplement(BaseModel):
    """为"已有但缺音色描述"的角色阶段补一条 voice_description（提案阶段顺势补，合成时才好 design 音色）"""

    stage_id: int = Field(..., description="需补音色描述的已有角色阶段 id")
    character_name: str = Field("", description="角色名（展示用）")
    stage_name: str = Field("", description="阶段名（展示用）")
    voice_description: str = Field("", description="补充的音色描述（性别+年龄段+气质，供 TTS 音色设计参考）")


class NewCharacterProposal(BaseModel):
    new_characters: List[NewCharacterDraft] = Field(default_factory=list, description="需要新建的角色；全部能匹配到的老角色则此列表为空")
    voice_supplements: List[VoiceSupplement] = Field(default_factory=list, description="为 catalog 里 voice_description 为空的已有阶段补的音色描述；无则留空")


class MappingEntry(BaseModel):
    extracted_name: str = Field(..., description="步骤3提取出的角色名")
    character_id: int = Field(..., description="映射到的角色库 id")
    stage_id: int = Field(..., description="映射到的角色阶段 id")
    confidence: float = Field(0.5, ge=0, le=1, description="匹配置信度")
    reason: str = Field("", description="匹配理由（同名/别名/场景吻合…）")


class MappingTable(BaseModel):
    entries: List[MappingEntry] = Field(default_factory=list, description="每个提取角色一行；步骤5用户连完线后此表覆盖 LLM 预填")


class Segment(BaseModel):
    index: int = Field(..., ge=0, description="段序号，从0连续递增")
    speaker: str = Field(..., description="说话人：旁白 或 角色名（只能是提供的名单内的名字）")
    text: str = Field(..., description="这一段的话。按自然朗读节奏分段：一段=一口气能念完的完整话语，"
                                       "在自然停顿处断段，交替对话拆成相邻段；"
                                       "不要把语意未完的半句切成两段，也不要把多句并成超长段")
    emotion: str = Field("", description="情绪（如：低沉/轻快/激动），可空")
    pause_after_sec: float = Field(0.8, ge=0, le=10, description="该段说完后停顿秒数；0=紧接下段（抢话/打断）")
    overlap_prev_sec: float = Field(0, ge=0, le=5, description="与上一段音频重叠秒数，默认0；仅旁白未尽人声已起的特殊场景用")


class BGMTrack(BaseModel):
    audio_id: int = Field(..., description="BGM 的 Resource.id（只能用提供的清单内的 id）")
    start_segment: int = Field(..., ge=0, description="起始段序号（含）")
    end_segment: int = Field(..., ge=0, description="结束段序号（含）")
    volume: float = Field(0.3, ge=0, le=1, description="音量（0-1）")
    fade_in_sec: float = Field(1.0, ge=0, le=10, description="淡入秒数")
    fade_out_sec: float = Field(2.0, ge=0, le=10, description="淡出秒数")

    @model_validator(mode="after")
    def _order(self):
        if self.end_segment < self.start_segment:
            raise ValueError(f"BGM track: end_segment({self.end_segment}) < start_segment({self.start_segment})")
        return self


class SFXTrack(BaseModel):
    audio_id: int = Field(..., description="SFX 的 Resource.id（只能用提供的清单内的 id）")
    segment: int = Field(..., ge=0, description="在第几段的位置触发")
    volume: float = Field(0.6, ge=0, le=1, description="音量（0-1）")


class IntroOutro(BaseModel):
    enabled: bool = Field(False, description="是否启用片头/片尾")
    text: str = Field("", description="片头/片尾旁白词")
    audio_id: Optional[int] = Field(None, description="衬底 BGM 的 Resource.id")
    duration_sec: float = Field(5.0, gt=0, le=30, description="时长（秒）")
    fade_in_sec: float = Field(1.0, ge=0)
    fade_out_sec: float = Field(1.0, ge=0)


class ScriptMeta(BaseModel):
    """生成上下文存档（不发给 LLM 做约束，纯记录）"""

    character_cards: dict = Field(default_factory=dict, description="角色卡快照 {名字: 阶段精要}")
    mapping_snapshot: List[MappingEntry] = Field(default_factory=list, description="本次映射快照")
    warnings: List[str] = Field(default_factory=list, description="lint 警告")


class AudioScript(BaseModel):
    segments: List[Segment] = Field(..., min_length=1, description="正文段落序列，按剧情顺序")
    intro: IntroOutro = Field(default_factory=IntroOutro, description="片头")
    outro: IntroOutro = Field(default_factory=IntroOutro, description="片尾")
    bgm_tracks: List[BGMTrack] = Field(default_factory=list, description="背景音乐轨")
    sfx_tracks: List[SFXTrack] = Field(default_factory=list, description="音效轨")
    metadata: ScriptMeta = Field(default_factory=ScriptMeta, description="元信息")

    @model_validator(mode="after")
    def _index_continuous(self):
        idx = [s.index for s in self.segments]
        if idx != list(range(len(self.segments))):
            raise ValueError(f"segment index 必须从0连续递增，得到: {idx[:10]}")
        # bgm/sfx 引用的段号不越界
        n = len(self.segments) - 1
        for t in self.bgm_tracks:
            if t.end_segment > n:
                raise ValueError(f"BGM end_segment({t.end_segment}) 超出最大段号({n})")
        for t in self.sfx_tracks:
            if t.segment > n:
                raise ValueError(f"SFX segment({t.segment}) 超出最大段号({n})")
        return self


# ── 启发式层（Pydantic 管不了的，llm 层在 retry 前手动调）────
# LLM 常把渲染出的"名字（别名: …）"整串抄进 extracted_name / speaker，
# 导致角色卡、白名单、合成音色表都带装饰名，而脚本 speaker 用裸名 → lint 不匹配、
# 合成找不到音色。统一在源头剥成裸名。
_ALIAS_DECOR_RE = re.compile(r"[（(]\s*别名\s*[:：][^）)]*[）)]\s*$")


def strip_alias_decor(name: str) -> str:
    """剥掉角色名尾部的"（别名: …）"装饰，回到裸名（全/半角括号都认）。"""
    return _ALIAS_DECOR_RE.sub("", (name or "")).strip()


_MULTI_SPEAKER_PATTERNS = [
    re.compile(r"[“”『「][^”』」]{1,40}[”』」].{0,6}[道说喊叫问][：:]"),
    re.compile(r"\S{1,8}道："),
    re.compile(r"[“”].{0,60}[”].{0,20}[“].{0,60}[”]"),  # 一段两组引号
]


def lint_script(script: AudioScript, allowed_speakers: set[str], allowed_audio_ids: set[int]) -> list[str]:
    """
    返回警告列表（空 = 干净）。检查：
    1. speaker 白名单；2. audio_id 白名单；3. 混段（一段多人说话）；4. 空 text
    speaker 与白名单都先剥"（别名: …）"装饰再比，避免因装饰名/裸名不一致误报。
    """
    warnings: list[str] = []
    allowed_norm = {strip_alias_decor(s) for s in allowed_speakers}
    for seg in script.segments:
        if strip_alias_decor(seg.speaker) not in allowed_norm:
            warnings.append(f"段{seg.index}: speaker '{seg.speaker}' 不在名单 {sorted(allowed_speakers)}")
        if not seg.text.strip():
            warnings.append(f"段{seg.index}: text 为空")
        for pat in _MULTI_SPEAKER_PATTERNS:
            if pat.search(seg.text):
                warnings.append(f"段{seg.index}: 疑似多人混在同一段（应拆成相邻段）")
                break
    for t in script.bgm_tracks:
        if t.audio_id not in allowed_audio_ids:
            warnings.append(f"BGM audio_id {t.audio_id} 不在清单")
    for t in script.sfx_tracks:
        if t.audio_id not in allowed_audio_ids:
            warnings.append(f"SFX audio_id {t.audio_id} 不在清单")
    if script.intro.enabled and script.intro.audio_id and script.intro.audio_id not in allowed_audio_ids:
        warnings.append("intro.audio_id 不在清单")
    if script.outro.enabled and script.outro.audio_id and script.outro.audio_id not in allowed_audio_ids:
        warnings.append("outro.audio_id 不在清单")
    return warnings
