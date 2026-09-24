from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from models.CharacterStage import CharacterStage
from sqlalchemy import select, func, delete, and_, update, case
from models.Character import CharacterCharacterStage
from schemas.CharacterStage import CharacterStageCreate


async def add_character_stage(
        db: AsyncSession,
        stage_name: str,
        alias_name: str,
        gender: str,
        chapter_index: int,
        age_Description: str,
        appearance_description: str,
        profile: str,
        voice_description: str,
        voice_path: str
):
    """创建新角色阶段"""
    db_obj = CharacterStage(
        stage_name=stage_name,
        alias_name=alias_name,
        gender=gender,
        chapter_index=chapter_index,
        age_Description=age_Description,
        appearance_description=appearance_description,
        profile=profile,
        voice_description=voice_description,
        voice_path=voice_path
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def add_character_stage_by_model(
        db: AsyncSession,
        stage: CharacterStageCreate,
):
    """通过模型创建新角色阶段"""
    db_obj = CharacterStage(**stage.model_dump())
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_character_stage_by_id(db: AsyncSession, stage_id: int):
    """根据ID获取阶段详情"""
    stmt = select(CharacterStage).where(CharacterStage.id == stage_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_stages_by_character_paginated(
        db: AsyncSession,
        character_id: int,
        offset: int = 0,
        limit: int = 10
):
    """
    根据character_id获取相应的分页阶段数据
    通过 CharacterCharacterStage 映射表进行 Join 查询
    """
    # 1. 统计该角色关联的阶段总数
    count_stmt = (
        select(func.count(CharacterStage.id))
        .join(CharacterCharacterStage, CharacterStage.id == CharacterCharacterStage.characterstage_id)
        .where(CharacterCharacterStage.character_id == character_id)
    )
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    # 2. 获取分页列表
    list_stmt = (
        select(CharacterStage)
        .join(CharacterCharacterStage, CharacterStage.id == CharacterCharacterStage.characterstage_id)
        .where(CharacterCharacterStage.character_id == character_id)
        .order_by(CharacterStage.id.desc())
        .offset(offset)
        .limit(limit)
    )
    list_result = await db.execute(list_stmt)
    stages = list_result.scalars().all()

    return stages, total


async def update_character_stage(
        db: AsyncSession,
        stage_id: int,
        update_data: Dict[str, Any]
):
    """更新角色阶段信息"""
    stmt = select(CharacterStage).where(CharacterStage.id == stage_id)
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


async def delete_character_stage(db: AsyncSession, stage_id: int):
    """删除单个角色阶段"""
    stmt = delete(CharacterStage).where(CharacterStage.id == stage_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def delete_stages_by_character(
        db: AsyncSession,
        character_id: int
):
    """
    根据character_id删除对应的所有characterstage
    策略：
    1. 删除 CharacterStage 表中对应的记录（使用 EXISTS 关联映射表）
    2. 删除 CharacterCharacterStage 映射表中的记录，防止脏数据
    """
    # 1. 删除 CharacterStage 记录
    delete_stage_stmt = (
        delete(CharacterStage)
        .where(
            select(CharacterCharacterStage.characterstage_id)
            .where(
                and_(
                    CharacterCharacterStage.characterstage_id == CharacterStage.id,
                    CharacterCharacterStage.character_id == character_id
                )
            )
            .exists()
        )
    )
    await db.execute(delete_stage_stmt)

    # 2. 删除映射表记录
    delete_mapping_stmt = (
        delete(CharacterCharacterStage)
        .where(CharacterCharacterStage.character_id == character_id)
    )
    await db.execute(delete_mapping_stmt)

    # 注意：根据参考代码习惯，此处未 commit，由路由层统一控制事务

async def shift_stage_chapter_indexes(
    db: AsyncSession,
    character_ids: List[int],
    start_index: int,
    delta: int
):
    """指定角色集合中，绑定章节号 >= start_index（0-based，与 Chapter.chapter_index 同口径）的阶段整体平移 delta。

    -1（未绑定/已删章）小于任何 >= 0 的阈值，天然不被波及。
    （插入 delta=+1 / 删除 delta=-1；不提交，由调用方控制事务）
    """
    if not character_ids:
        return
    stmt = (
        update(CharacterStage)
        .values(chapter_index=CharacterStage.chapter_index + delta)
        .where(CharacterStage.chapter_index >= start_index)
        .where(
            select(CharacterCharacterStage.characterstage_id)
            .where(and_(
                CharacterCharacterStage.characterstage_id == CharacterStage.id,
                CharacterCharacterStage.character_id.in_(character_ids)
            )).exists()
        )
    )
    await db.execute(stmt)


async def reset_chapter_index_by_characters(
    db: AsyncSession,
    character_ids: List[int],
    chapter_index: int
):
    """把绑定在 0-based 第 chapter_index 章上的阶段置 -1（该章被删）。

    必须先于 shift 调用（reset 后这些行已为 -1，shift 不会再碰到）；
    若先 shift，被删章后面的阶段会左移落到 chapter_index 上被误清。
    不提交，由调用方控制事务。
    """
    if not character_ids:
        return 0
    stmt = (
        update(CharacterStage)
        .values(chapter_index=-1)
        .where(CharacterStage.chapter_index == chapter_index)
        .where(
            select(CharacterCharacterStage.characterstage_id)
            .where(and_(
                CharacterCharacterStage.characterstage_id == CharacterStage.id,
                CharacterCharacterStage.character_id.in_(character_ids)
            )).exists()
        )
    )
    result = await db.execute(stmt)
    return result.rowcount


async def reset_chapter_indexes_by_characters(
    db: AsyncSession,
    character_ids: List[int],
    chapter_indexes: List[int],
):
    """批量版：把绑定到给定 0-based 章号集合上的阶段置 -1。不提交。"""
    if not character_ids or not chapter_indexes:
        return
    stmt = (
        update(CharacterStage)
        .values(chapter_index=-1)
        .where(CharacterStage.chapter_index.in_(chapter_indexes))
        .where(
            select(CharacterCharacterStage.characterstage_id)
            .where(and_(
                CharacterCharacterStage.characterstage_id == CharacterStage.id,
                CharacterCharacterStage.character_id.in_(character_ids),
            )).exists()
        )
    )
    await db.execute(stmt)


async def remap_stage_chapter_indexes(
    db: AsyncSession,
    character_ids: List[int],
    index_map: Dict[int, int],
):
    """按 old→new 章号映射（两端均 0-based）批量改写绑定。

    CASE 单语句按原值判定，无交叉覆盖；不提交，由调用方控制事务。
    """
    if not character_ids or not index_map:
        return
    stmt = (
        update(CharacterStage)
        .values(chapter_index=case(
            *[
                (CharacterStage.chapter_index == old, new)
                for old, new in index_map.items()
            ]
        ))
        .where(CharacterStage.chapter_index.in_(list(index_map.keys())))
        .where(
            select(CharacterCharacterStage.characterstage_id)
            .where(and_(
                CharacterCharacterStage.characterstage_id == CharacterStage.id,
                CharacterCharacterStage.character_id.in_(character_ids)
            )).exists()
        )
    )
    await db.execute(stmt)

async def delete_stages_by_characters(
        db: AsyncSession,
        character_ids: List[int]
):
    """
    根据character_ids批量删除对应的所有characterstage
    策略：使用 EXISTS 配合 IN，避免生成巨大的 ID 列表
    """
    if not character_ids:
        return

    # 1. 批量删除 CharacterStage
    delete_stage_stmt = (
        delete(CharacterStage)
        .where(
            select(CharacterCharacterStage.characterstage_id)
            .where(
                and_(
                    CharacterCharacterStage.characterstage_id == CharacterStage.id,
                    CharacterCharacterStage.character_id.in_(character_ids)
                )
            )
            .exists()
        )
    )
    await db.execute(delete_stage_stmt)

    # 2. 批量删除映射表
    delete_mapping_stmt = (
        delete(CharacterCharacterStage)
        .where(CharacterCharacterStage.character_id.in_(character_ids))
    )
    await db.execute(delete_mapping_stmt)

async def get_stages_by_ids(db: AsyncSession, stage_ids: List[int]):
    """根据ID列表批量获取角色阶段"""
    if not stage_ids:
        return []
    stmt = select(CharacterStage).where(CharacterStage.id.in_(stage_ids))
    result = await db.execute(stmt)
    return result.scalars().all()


