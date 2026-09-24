from typing import Any, Dict, List

from models.AudioBookScript import AudioBookScripAudio
from models.Resource import Resource
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession



async def add_resource(
    db: AsyncSession,
    audio_name: str,
    description: str,
    path: str,
    audiotype: str,
):
    """创建新音频资源"""
    db_obj = Resource(
        Audio_name=audio_name,
        description=description,
        path=path,
        audio_type=audiotype,
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_resources_paginated(
    db: AsyncSession,
    audiotype: str,
    offset: int = 0,
    limit: int = 10,
):
    """分页获取音频资源列表
    FIX: 原实现 total 未按 audiotype 过滤，筛选时总数永远返回全表数量
    """
    count_stmt = select(func.count(Resource.id))
    list_stmt = select(Resource).order_by(Resource.id.desc())
    if audiotype:
        cond = Resource.audio_type == audiotype
        count_stmt = count_stmt.where(cond)
        list_stmt = list_stmt.where(cond)

    total = (await db.execute(count_stmt)).scalar()
    resources = (await db.execute(list_stmt.offset(offset).limit(limit))).scalars().all()
    return resources, total


async def get_resource_by_id(db: AsyncSession, resource_id: int):
    """根据ID获取音频资源详情"""
    stmt = select(Resource).where(Resource.id == resource_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_resource_by_ids(db: AsyncSession, resource_ids: List[int]):
    """根据ID批量获取音频资源详情"""
    stmt = select(Resource).where(Resource.id.in_(resource_ids))
    return (await db.execute(stmt)).scalars().all()


async def update_resource(
    db: AsyncSession,
    resource_id: int,
    update_data: Dict[str, Any],
):
    """更新音频资源信息"""
    stmt = select(Resource).where(Resource.id == resource_id)
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

async def get_resources_by_script(db: AsyncSession, script_id: int):
    """获取脚本已映射的全部音频资源
    FIX: 原实现把 execute 的 Result 对象直接塞进 in_()，且 is None 判断永远不成立
    """
    stmt = (
        select(Resource)
        .join(AudioBookScripAudio, AudioBookScripAudio.audio_id == Resource.id)
        .where(AudioBookScripAudio.script_id == script_id)
        .order_by(AudioBookScripAudio.id)  # 按映射顺序返回
    )
    return (await db.execute(stmt)).scalars().all()


async def get_script_ids_by_audio(db: AsyncSession, audio_id: int):
    """新增：查询某音频被哪些脚本引用（删除资源前可用于提示）"""
    stmt = select(AudioBookScripAudio.script_id).where(
        AudioBookScripAudio.audio_id == audio_id
    )
    return (await db.execute(stmt)).scalars().all()

async def delete_mapping_by_id(db: AsyncSession, audio_id: int):
    stmt = delete(AudioBookScripAudio).where(AudioBookScripAudio.audio_id == audio_id)
    await db.execute(stmt)


async def delete_mapping_by_ids(db: AsyncSession, audio_ids: List[int]):
    if not audio_ids:
        return
    stmt = delete(AudioBookScripAudio).where(AudioBookScripAudio.audio_id.in_(audio_ids))
    await db.execute(stmt)

async def delete_resource(db: AsyncSession, resource_id: int):
    """删除音频资源（不 commit，调用方与映射删除同事务提交）"""
    stmt = delete(Resource).where(Resource.id == resource_id)
    await db.execute(stmt)


async def delete_resources(db: AsyncSession, resource_ids: List[int]):
    """批量删除音频资源（不 commit，调用方与映射删除同事务提交）"""
    stmt = delete(Resource).where(Resource.id.in_(resource_ids))
    await db.execute(stmt)

