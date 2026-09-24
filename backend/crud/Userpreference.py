from typing import Any, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models.Userpreference import Userpreference


async def get_or_create_userpreference(db: AsyncSession) -> Userpreference:
    """
    获取单例偏好记录（首条），不存在时创建默认记录
    """
    stmt = select(Userpreference).order_by(Userpreference.id).limit(1)
    result = await db.execute(stmt)
    db_obj = result.scalar_one_or_none()

    if db_obj:
        return db_obj

    db_obj = Userpreference(
        description="",
        chunk_model=True,
        chunk_size=400,
        overlap_size=200
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def update_current_userpreference(
    db: AsyncSession,
    update_data: Dict[str, Any]
):
    """
    更新单例偏好记录（不存在时先创建默认记录再更新）
    """
    db_obj = await get_or_create_userpreference(db)

    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)

    await db.commit()
    await db.refresh(db_obj)
    return db_obj
