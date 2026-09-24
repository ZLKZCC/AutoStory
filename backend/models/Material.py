from models.Base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String


class Material(Base):
    __tablename__ = "material"

    id: Mapped[int] = mapped_column(primary_key=True,comment="素材库id")
    material_name: Mapped[str] = mapped_column(String(50),comment="素材库名")
    description: Mapped[str] = mapped_column(String(255),comment="素材库描述")