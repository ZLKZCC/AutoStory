from typing import Optional
from models.Base import Base
from sqlalchemy import String, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column


class CharacterStage(Base):
    __tablename__ = "characterstage"

    id: Mapped[int] = mapped_column(primary_key=True,comment="角色阶段id")
    stage_name: Mapped[str] = mapped_column(String(255),comment="阶段描述")
    alias_name: Mapped[str] = mapped_column(String(255),comment="角色别名")
    gender: Mapped[str] = mapped_column(String(255),comment="角色性别")
    chapter_index: Mapped[int] = mapped_column(Integer,comment="阶段起始章节号(0-based 第几章;-1=章节已删/未绑定)")
    age_Description: Mapped[str] = mapped_column(String(255),comment="角色年龄描述")
    appearance_description: Mapped[str] = mapped_column(String(255),comment="角色外观描述")
    profile: Mapped[str] = mapped_column(String(255),comment="角色侧写")
    voice_description: Mapped[str] = mapped_column(String(500),comment="角色音色描述")
    voice_path: Mapped[str] = mapped_column(String(500),comment="角色参考音频")