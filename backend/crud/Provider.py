from typing import Any, Dict, List
from models.Provider import Provider
from schemas.Provider import ProviderCreate
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, func, select, update





async def create_provider(
    db: AsyncSession,
    provider_name: str,
    kind: str,
    api_url: str,
    api_key: str,
    model_id: str,
    context_length: int
):
    """
    创建新供应商配置
    """
    db_obj = Provider(
        provider_name=provider_name,
        kind=kind,
        api_url=api_url,
        api_key=api_key,
        model_id=model_id,
        context_length=context_length
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def create_provider_by_model(
    db: AsyncSession,
    provider: ProviderCreate,
):
    """
    创建新供应商配置；若新建即设为默认（active=True），先把其他 active=True 的取消，
    保证全局只有一个默认供应商（与 set_default_provider 同样的约束）。
    """
    if provider.active:
        clear_stmt = (
            update(Provider)
            .where(Provider.active == True)
            .values(active=False)
        )
        await db.execute(clear_stmt)

    db_obj = Provider(**provider.model_dump())
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_active_provider(db: AsyncSession):
    row = (await db.execute(
        select(Provider).where(Provider.active == True)  # noqa: E712
    )).scalar_one_or_none()
    if row is None:
        raise RuntimeError("没有激活的 LLM 供应商，请先在前端设置页配置并激活")
    return row

async def get_providers_paginated(
    db: AsyncSession,
    offset: int = 0,
    limit: int = 10
):
    """
    分页获取供应商列表，并返回总数
    """
    # 获取总数
    count_stmt = select(func.count(Provider.id))
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    # 获取列表，按主键倒序排列
    list_stmt = (
        select(Provider)
        .order_by(Provider.active.desc(), Provider.id)
        .offset(offset)
        .limit(limit)
    )
    list_result = await db.execute(list_stmt)
    providers = list_result.scalars().all()

    return providers, total


async def get_provider_by_id(db: AsyncSession, provider_id: int):
    """
    根据ID获取供应商详情
    """
    stmt = select(Provider).where(Provider.id == provider_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_provider(
    db: AsyncSession,
    provider_id: int,
    update_data: Dict[str, Any]
):
    """
    更新供应商信息；若本次将 active 改为 True 且原本不是默认，
    先取消其余 active=True 的记录，保证全局只有一个默认供应商
    （与 set_default_provider / create_provider_by_model 同样的约束）。
    """
    stmt = select(Provider).where(Provider.id == provider_id)
    result = await db.execute(stmt)
    db_obj = result.scalar_one_or_none()

    if not db_obj:
        return None

    # 严格判 True（避免 truthy 值误触）；且目标原本非默认才需清理其他
    if update_data.get("active") is True and not db_obj.active:
        clear_stmt = (
            update(Provider)
            .where(Provider.active == True, Provider.id != provider_id)
            .values(active=False)
        )
        await db.execute(clear_stmt)

    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)

    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def delete_provider(db: AsyncSession, provider_id: int):
    """
    删除供应商配置
    """
    stmt = delete(Provider).where(Provider.id == provider_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0

async def set_default_provider(
        db: AsyncSession,
        provider_id: int,
):
    """
    设置指定供应商为默认，其余默认供应商取消默认
    """
    # 校验目标供应商是否存在
    stmt = select(Provider).where(Provider.id == provider_id)
    result = await db.execute(stmt)
    db_obj = result.scalar_one_or_none()
    if not db_obj:
        return None

    # 取消其余默认供应商
    clear_stmt = (
        update(Provider)
        .where(Provider.active == True, Provider.id != provider_id)
        .values(active=False)
    )
    await db.execute(clear_stmt)

    # 设置目标供应商为默认
    db_obj.active = True
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def batch_delete_providers(
        db: AsyncSession,
        provider_ids: List[int],
):
    """
    批量删除指定 id 列表的供应商
    """
    stmt = delete(Provider).where(Provider.id.in_(provider_ids))
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount
