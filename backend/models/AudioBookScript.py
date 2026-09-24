from typing import List

from models.Base import Base
from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

class AudioBookScript(Base):
    __tablename__ = "audiobookscript"

    id: Mapped[int] = mapped_column(primary_key=True,comment="脚本id")
    name: Mapped[str] = mapped_column(String(255),comment="脚本名")
    project_id: Mapped[int] = mapped_column(Integer,comment="项目id")
    chapter_id: Mapped[int] = mapped_column(Integer,comment="章节id")
    script_path: Mapped[str] = mapped_column(String(255), default="", comment="脚本文件路径")
    audio_path: Mapped[str] = mapped_column(String(255), default="", comment="音频文件路径")
    mapping: Mapped[str] = mapped_column(Text, default="", comment="角色映射JSON：章中角色名→角色阶段id（确认后的最终版，重合成用）")
    narrator_desc: Mapped[str] = mapped_column(Text, default="", comment="旁白音色描述（重合成用或者查询用）")
    narrator_text: Mapped[str] = mapped_column(Text, default="", comment="旁白文字描述（重合成用或者查询用）")
    stage_payload: Mapped[str] = mapped_column(Text, default="", comment="各步中间产物JSON（提取/提案/映射表/脚本概览），供断点续跑时直接渲染卡片")

class AudioBookScripAudio(Base):
    __tablename__ = "audiobookscriptaudio"
    id: Mapped[int] = mapped_column(primary_key=True, comment="映射id")
    script_id: Mapped[int] = mapped_column(Integer, index=True, comment="脚本id")
    audio_id: Mapped[int] = mapped_column(Integer, index=True, comment="音频资源id")

    __table_args__ = (
        UniqueConstraint("script_id", "audio_id", name="uq_script_audio"),
    )
