from typing import Any, Dict, List
from models.Material import Material
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

async def add_material(
    db: AsyncSession,
    material_name: str,
    description: str,
):
    """
    创建素材库
    """
    db_obj = Material(
        material_name=material_name,
        description=description
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_materials_paginated(
    db: AsyncSession,
    offset: int = 0,
    limit: int = 10,
    search: str = "",
    sort: str = "updated"
):
    """
    分页获取素材库列表（支持名称模糊搜索与排序），并返回总数
    """
    # 获取总数
    count_stmt = select(func.count(Material.id))
    if search:
        count_stmt = count_stmt.where(Material.material_name.like(f"%{search}%"))
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    # 排序：name 按名称正序，created/updated 按时间倒序
    order_columns = {
        "name": Material.material_name.asc(),
        "created": Material.create_time.desc()
    }
    order_by = order_columns.get(sort, Material.update_time.desc())

    list_stmt = (
        select(Material)
        .order_by(order_by)
        .offset(offset)
        .limit(limit)
    )
    if search:
        list_stmt = list_stmt.where(Material.material_name.like(f"%{search}%"))
    list_result = await db.execute(list_stmt)
    materials = list_result.scalars().all()

    return materials, total

async def get_material_by_id(db: AsyncSession, material_id: int):
    """
    根据ID获取素材库详情
    """
    stmt = select(Material).where(Material.id == material_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def update_material(
    db: AsyncSession,
    material_id: int,
    update_data: Dict[str, Any]
):
    """
    更新素材库信息
    """
    stmt = select(Material).where(Material.id == material_id)
    result = await db.execute(stmt)
    db_obj = result.scalar_one_or_none()

    if not db_obj:
        return None

    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)

    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def delete_material(db: AsyncSession, material_id: int):
    """
    删除素材库
    """
    stmt = delete(Material).where(Material.id == material_id)
    await db.execute(stmt)

async def batch_delete_materials(db: AsyncSession, material_ids: List[int]) -> int:
    """
    批量删除素材库，返回实际删除条数
    """
    if not material_ids:
        return 0

    stmt = delete(Material).where(Material.id.in_(material_ids))
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount