from typing import Optional
from datetime import datetime
from models.Base import Base
from sqlalchemy import String, Integer, DATETIME, func
from sqlalchemy.orm import Mapped, mapped_column



class Chapter(Base):
    __tablename__ = "chapter"

    id: Mapped[int] = mapped_column(primary_key=True,comment="章节id")
    chapter_title: Mapped[str] = mapped_column(String(255),comment="章节标题")
    chapter_index: Mapped[int] = mapped_column(Integer,comment="章节索引")
    chapter_content: Mapped[str] = mapped_column(String(30000),comment="章节内容")
    chapter_summary: Mapped[str] = mapped_column(String(1000),comment="章节摘要总结")
    # 陈旧检测：content_updated_at 仅在正文真变时顶新；summary_generated_at 在写入本章摘要时顶新。
    # 摘要落后于正文（summary_generated_at < content_updated_at）即视为陈旧，触发懒重算 + 向上级联。
    # 不用 Base.update_time（行级、写摘要本身也会顶新 → 假陈旧）。
    content_updated_at: Mapped[Optional[datetime]] = mapped_column(DATETIME, nullable=True, comment="正文最近实质变更时间")
    summary_generated_at: Mapped[Optional[datetime]] = mapped_column(DATETIME, nullable=True, comment="本章摘要生成时间")

    @property
    def word_count(self) -> int:
        """正文字数（= chapter_content 字符长度，口径与前端 getChapter/saveChapter 一致）。
        非数据库列；供列表接口 Chaptershot 带出，前端左树无需打开章节即可显示字数。"""
        return len(self.chapter_content or "")
