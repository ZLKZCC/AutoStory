from typing import Optional
from datetime import datetime
from models.Base import Base
from sqlalchemy import String, Integer, DATETIME
from sqlalchemy.orm import Mapped, mapped_column


class Volume(Base):
    """分卷：章节按卷分桶，卷摘要（≤2000字）向上汇聚成全局概要。

    卷边界用 chapter_index 闭区间 [chapter_start, chapter_end]（0-based）表达，
    章节归属某卷 = 其 chapter_index 落在区间内。卷摘要落后于卷内任一章摘要即陈旧。
    """
    __tablename__ = "volume"

    id: Mapped[int] = mapped_column(primary_key=True, comment="分卷id")
    project_id: Mapped[int] = mapped_column(Integer, comment="项目id")
    volume_index: Mapped[int] = mapped_column(Integer, default=0, comment="卷序号（0-based）")
    name: Mapped[str] = mapped_column(String(255), default="", comment="卷名")
    chapter_start: Mapped[int] = mapped_column(Integer, default=0, comment="起始章节索引（含，0-based）")
    chapter_end: Mapped[int] = mapped_column(Integer, default=0, comment="结束章节索引（含，0-based）")
    summary: Mapped[str] = mapped_column(String(2000), default="", comment="卷摘要")
    summary_generated_at: Mapped[Optional[datetime]] = mapped_column(DATETIME, nullable=True, comment="卷摘要生成时间")
