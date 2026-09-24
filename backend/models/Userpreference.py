from models.Base import Base
from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column



class Userpreference(Base):
    __tablename__ = "userpreference"

    id: Mapped[int] = mapped_column(primary_key=True,comment="用户偏好记录id")
    description: Mapped[str] = mapped_column(String(5000),comment="用户偏好")
    chunk_model: Mapped[bool] = mapped_column(Boolean,default=True,comment="切片模式")
    chunk_size: Mapped[int] = mapped_column(Integer,default=400,comment="切片大小")
    overlap_size: Mapped[int] = mapped_column(Integer,default=200,comment="重合大小")