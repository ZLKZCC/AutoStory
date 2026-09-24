from models.Base import Base
from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column




class ChatRecord(Base):
    __tablename__ = "chatrecord"

    id: Mapped[int] = mapped_column(primary_key=True,comment="聊天消息id")
    role: Mapped[str] = mapped_column(String(20),comment="角色")
    content: Mapped[str] = mapped_column(String(20000),comment="内容")
    timestamp: Mapped[datetime] = mapped_column(DateTime,comment="时间戳")
    type: Mapped[str] = mapped_column(String(100),comment="种类")
    extra: Mapped[str] = mapped_column(String(100),comment="call_id")
