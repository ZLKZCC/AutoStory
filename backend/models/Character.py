from models.Base import Base
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column


class Character(Base):
    __tablename__ = "character"

    id: Mapped[int] = mapped_column(primary_key=True,comment="角色id")
    character_name: Mapped[str] = mapped_column(String(255),comment="角色名")
    gender: Mapped[str] = mapped_column(String(255),comment="角色性别")
    role: Mapped[str] = mapped_column(String(255),comment="角色类型")

class CharacterCharacterStage(Base):
    __tablename__ = "charactercharacterstage"

    id: Mapped[int] = mapped_column(primary_key=True,comment="映射id")
    character_id: Mapped[int] = mapped_column(Integer,comment="角色id")
    characterstage_id: Mapped[int] = mapped_column(Integer,comment="角色阶段id")

