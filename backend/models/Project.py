from typing import Optional
from models.Base import Base
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, JSON, Integer, DATETIME, func



class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True,comment="项目id")
    project_name: Mapped[str] = mapped_column(String(50),comment="项目名")
    description: Mapped[str] = mapped_column(String(255),comment="项目描述")
    Project_summary: Mapped[str] = mapped_column(String(3000),comment="项目全局故事概要")
    concept: Mapped[Optional[dict]] = mapped_column(JSON, default=dict,comment="项目大纲")
    worldline: Mapped[Optional[dict]] = mapped_column(JSON, default=dict,comment="项目世界线")
    activetime: Mapped[datetime] = mapped_column(DATETIME,default=func.now(),insert_default=func.now(),comment="激活时间")
    # 陈旧检测：concept/worldline 仅在显式改动时顶新对应时间；summary_generated_at 在写入全局概要时顶新。
    # 全局概要落后于设定或任一卷摘要即视为陈旧，触发懒重算。description 仅显式改、不参与级联。
    concept_updated_at: Mapped[Optional[datetime]] = mapped_column(DATETIME, nullable=True, comment="大纲最近变更时间")
    worldline_updated_at: Mapped[Optional[datetime]] = mapped_column(DATETIME, nullable=True, comment="世界线最近变更时间")
    description_updated_at: Mapped[Optional[datetime]] = mapped_column(DATETIME, nullable=True, comment="描述生成时间")
    summary_generated_at: Mapped[Optional[datetime]] = mapped_column(DATETIME, nullable=True, comment="全局概要生成时间")
    # token 总账（项目级）：run 收尾（done 信封）时写入本轮精确占用 + 窗口，
    # history / context_size / done 三出口同源，整页刷新后圆环立即有数
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0", comment="最近一轮完成时的上下文占用")
    context_window: Mapped[int] = mapped_column(Integer, default=0, server_default="0", comment="最近一轮完成时的上下文窗口")

class Projectchapter(Base):
    __tablename__ = "projectchapter"

    id: Mapped[int] = mapped_column(primary_key=True,comment="项目章节映射id")
    project_id: Mapped[int] = mapped_column(Integer,comment="项目id")
    chapter_id: Mapped[int] = mapped_column(Integer,comment="章节id")

class Projectcharacter(Base):
    __tablename__ = "projectcharacter"

    id: Mapped[int] = mapped_column(primary_key=True,comment="项目角色映射id")
    project_id: Mapped[int] = mapped_column(Integer,comment="项目id")
    character_id: Mapped[int] = mapped_column(Integer,comment="角色id")

class Projectchat(Base):
    __tablename__ = "projectchat"

    id: Mapped[int] = mapped_column(primary_key=True,comment="项目消息映射id")
    project_id: Mapped[int] = mapped_column(Integer,comment="项目id")
    chat_id: Mapped[int] = mapped_column(Integer,comment="聊天消息id")

class Projectknowledge(Base):
    __tablename__ = "Projectknowledge"

    id: Mapped[int] = mapped_column(primary_key=True,comment="项目素材映射id")
    project_id: Mapped[int] = mapped_column(Integer,comment="项目id")
    knowledge: Mapped[str] = mapped_column(String(1500),comment="素材内容")