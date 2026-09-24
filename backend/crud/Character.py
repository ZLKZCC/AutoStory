from models.Character import Character, CharacterCharacterStage
from models.Project import Projectcharacter
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_
from schemas.Character import CharacterCreate


async def add_character(
    db: AsyncSession,
    character_name: str,
    gender: str,
    role: str,
):
    """
    创建新角色
    """
    db_obj = Character(
        character_name=character_name,
        gender=gender,
        role=role,
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def add_character_by_model(
    db: AsyncSession,
    character: CharacterCreate,
):
    """
    创建新角色
    """
    db_obj = Character(**character.model_dump())
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_character_counts(db: AsyncSession, project_ids: List[int]):
    """
    批量获取指定项目的角色数量

    Args:
        db: 数据库会话
        project_ids: 项目ID列表

    Returns:
        Dict[int, int]: 键为项目ID，值为对应的角色数量 (没有记录的项目默认为0)
    """
    if not project_ids:
        return {}

    # 初始化结果字典，默认为0
    counts = {pid: 0 for pid in project_ids}

    # 使用 GROUP BY 一次性统计所有项目的数量
    stmt = (
        select(Projectcharacter.project_id, func.count(Projectcharacter.id))
        .where(Projectcharacter.project_id.in_(project_ids))
        .group_by(Projectcharacter.project_id)
    )

    result = await db.execute(stmt)
    for project_id, count in result.all():
        counts[project_id] = count

    return counts

async def get_characterid_by_project(db: AsyncSession, project_id: int):
    """
    获取项目下的所有章节id
    """
    stmt = select(Projectcharacter.character_id).where(Projectcharacter.project_id == project_id)
    result = await db.execute(stmt)
    characterids = result.scalars().all()
    return characterids

async def get_characterid_by_projects(db: AsyncSession, project_ids: List[int]):
    """
    获取项目下的所有章节id
    """
    stmt = select(Projectcharacter.character_id).where(Projectcharacter.project_id.in_(project_ids))
    result = await db.execute(stmt)
    characterids = result.scalars().all()
    return characterids

async def get_characters_by_paginated(
    db: AsyncSession,
    project_id: int,
    offset: int = 0,
    limit: int = 10
):
    """
    通过映射表获取指定项目下的所有角色（支持分页和全量）
    性能优化：使用 Join 一次性查询
    """
    # 获取该项目的关联角色总数
    count_stmt = (
        select(func.count(Character.id))
        .join(Projectcharacter, Character.id == Projectcharacter.character_id)
        .where(Projectcharacter.project_id == project_id)
    )
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    # 获取角色列表
    list_stmt = (
        select(Character)
        .join(Projectcharacter, Character.id == Projectcharacter.character_id)
        .where(Projectcharacter.project_id == project_id)
        .order_by(Character.id.desc())
        .offset(offset)
        .limit(limit)
    )
    list_result = await db.execute(list_stmt)
    characters = list_result.scalars().all()

    return characters, total


async def get_character_by_id(db: AsyncSession, character_id: int):
    """
    根据ID获取角色详情
    """
    stmt = select(Character).where(Character.id == character_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_character(
    db: AsyncSession,
    character_id: int,
    update_data: Dict[str, Any]
):
    """
    更新角色信息
    """
    stmt = select(Character).where(Character.id == character_id)
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


async def delete_character(db: AsyncSession, character_id: int):
    """
    删除角色
    """
    stmt = delete(Character).where(Character.id == character_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0

async def delete_characters_by_project(
        db: AsyncSession,
        project_id: int
):
    """
    高效删除指定项目下的所有人物（无外键环境）

    策略：
    1. 使用 EXISTS 代替 IN，避免生成巨大的 ID 列表，减少内存消耗。
    2. 手动清理映射表，防止产生脏数据。
    """
    delete_character_stmt = (
        delete(Character)
        .where(
            select(Projectcharacter.character_id)
            .where(
                and_(
                    Projectcharacter.character_id == Character.id,
                    Projectcharacter.project_id == project_id
                )
            )
            .exists()
        )
    )
    await db.execute(delete_character_stmt)

    delete_mapping_stmt = (
        delete(Projectcharacter)
        .where(Projectcharacter.project_id == project_id)
    )
    await db.execute(delete_mapping_stmt)

async def delete_characters_by_projects(
        db: AsyncSession,
        project_ids: List[int]
):
    """
    批量高效删除指定项目下的所有人物（无外键环境）

    策略：
    1. 使用 EXISTS 配合 IN，避免生成巨大的 ID 列表，减少内存消耗。
    2. 手动清理映射表，防止产生脏数据。
    3. 注意：此处移除了 commit，由调用方（路由层）统一控制事务。
    """
    if not project_ids:
        return

    # 1. 删除 Character
    # 只要 Character 的 ID 存在于 Projectcharacter 表中，且对应的 project_id 在输入列表中，就删除
    delete_character_stmt = (
        delete(Character)
        .where(
            select(Projectcharacter.character_id)
            .where(
                and_(
                    Projectcharacter.character_id == Character.id,
                    # 使用 .in_() 进行批量匹配
                    Projectcharacter.project_id.in_(project_ids)
                )
            )
            .exists()
        )
    )
    await db.execute(delete_character_stmt)

    # 2. 删除映射表 Projectcharacter
    delete_mapping_stmt = (
        delete(Projectcharacter)
        .where(Projectcharacter.project_id.in_(project_ids))
    )
    await db.execute(delete_mapping_stmt)

async def add_character_stage(
    db: AsyncSession,
    character_id: int,
    characterstage_id: int
):
    """添加角色-阶段关联"""
    db_obj = CharacterCharacterStage(
        character_id=character_id,
        characterstage_id=characterstage_id
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def remove_character_stage(
    db: AsyncSession,
    characterstage_id: int
):
    """
    删除角色-阶段关联
    """
    stmt = delete(CharacterCharacterStage).where(
        CharacterCharacterStage.characterstage_id == characterstage_id
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0

async def remove_character_stage_by_character(
    db: AsyncSession,
    character_id: int
):
    """
    删除角色-阶段关联
    """
    stmt = delete(CharacterCharacterStage).where(
        CharacterCharacterStage.character_id== character_id
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def get_stage_ids_by_character_id(
        db: AsyncSession,
        character_id: int
):
    """
    根据character_ids列表获取所有关联的characterstage_id列表
    """
    stmt = (
        select(CharacterCharacterStage.characterstage_id)
        .where(CharacterCharacterStage.character_id == character_id)
        .distinct()
    )

    result = await db.execute(stmt)

    character_stage_ids = result.scalars().all()
    return character_stage_ids

async def get_stage_ids_by_character_ids(
        db: AsyncSession,
        character_ids: List[int]
):
    """
    根据character_ids列表获取所有关联的characterstage_id列表
    """
    if not character_ids:
        return []

    # 查询映射表，筛选 character_id 在列表中的记录
    stmt = (
        select(CharacterCharacterStage.characterstage_id)
        .where(CharacterCharacterStage.character_id.in_(character_ids))
        .distinct()
    )

    result = await db.execute(stmt)

    character_stage_ids = result.scalars().all()
    return character_stage_ids

async def get_characters_by_ids(db: AsyncSession, character_ids: List[int]):
    """根据ID列表批量获取角色"""
    if not character_ids:
        return []
    stmt = select(Character).where(Character.id.in_(character_ids))
    result = await db.execute(stmt)
    return result.scalars().all()

async def get_character_stage_mappings(db: AsyncSession, character_ids: List[int]):
    """获取角色-阶段的映射关系列表"""
    if not character_ids:
        return []
    stmt = select(CharacterCharacterStage).where(CharacterCharacterStage.character_id.in_(character_ids))
    result = await db.execute(stmt)
    return result.scalars().all()


