from models.Base import Base
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column


class Summary(Base):
    __tablename__ = "summary"

    id: Mapped[int] = mapped_column(primary_key=True,comment="摘要id")
    project_id: Mapped[str] = mapped_column(Integer,comment="项目id")
    chatcontext: Mapped[str] = mapped_column(String(1000),comment="聊天上下文摘要")
    index: Mapped[int] = mapped_column(Integer,comment="排序索引")


class SummaryChatRecord(Base):
    __tablename__ = "summarychatrecord"

    id: Mapped[int] = mapped_column(primary_key=True, comment="映射id")
    summary_id: Mapped[int] = mapped_column(Integer, comment="摘要id")
    chatrecord_id: Mapped[int] = mapped_column(Integer, comment="聊天记录id")
