from models.Base import Base
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column



class Resource(Base):
    __tablename__ = "resource"

    id: Mapped[int] = mapped_column(primary_key=True,comment="音频id")
    Audio_name: Mapped[str] = mapped_column(String(255),comment="音频名字")
    description: Mapped[str] = mapped_column(String(255),comment="描述")
    path: Mapped[str] = mapped_column(String(255),comment="音频路径")

    audio_type: Mapped[str] = mapped_column(String(255),comment="音频种类")

