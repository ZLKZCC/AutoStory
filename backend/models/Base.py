from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    create_time: Mapped[datetime] = mapped_column(DateTime,default=func.now(),insert_default=func.now(), comment="创建时间")
    update_time: Mapped[datetime] = mapped_column(DateTime,default=func.now(),insert_default=func.now(),onupdate=func.now(),comment="更新时间")

