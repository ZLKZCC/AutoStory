from schemas.Project import ProjectCreate
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, delete
from models.Project import Project, Projectchapter, Projectcharacter, Projectchat, Projectknowledge
from models.Volume import Volume


async def create_project(
        db: AsyncSession,
        project_name: str,
        description: str,
        project_summary: str = "",
        concept: Optional[Dict] = None,
        worldline: Optional[Dict] = None
):
    """
    创建新项目
    """
    now = datetime.now()
    db_obj = Project(
        project_name=project_name,
        description=description,
        Project_summary=project_summary,
        concept=concept or {},
        worldline=worldline or {},
        concept_updated_at=now if concept else None,
        worldline_updated_at=now if worldline else None,
        summary_generated_at=None  # ✨ NEW: 全局概要未生成
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def create_project_by_model(
        db: AsyncSession,
        project: ProjectCreate,
):
    """
    创建新项目
    """
    # 根据传入的数据判断是否更新时间戳
    now = datetime.now()
    concept = project.concept or None
    worldline = project.worldline or None
    db_obj = Project(
        **project.model_dump(),
        concept_updated_at=now if concept else None,
        worldline_updated_at=now if worldline else None,
        summary_generated_at=None  # ✨ NEW: 全局概要未生成
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_projects_paginated(
        db: AsyncSession,
        offset: int = 0,
        limit: int = 10
):
    """
    分页获取项目列表，并返回总数
    性能优化：使用 count(*) 获取总数，只查询必要的字段
    """
    # 获取总数
    count_stmt = select(func.count(Project.id))
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    # 获取列表，按激活时间倒序排列（通常最近在使用的在前面）
    list_stmt = (
        select(Project)
        .order_by(Project.activetime.desc())
        .offset(offset)
        .limit(limit)
    )
    list_result = await db.execute(list_stmt)
    projects = list_result.scalars().all()

    return projects, total


async def get_project_by_id(db: AsyncSession, project_id: int):
    """
    根据ID获取项目详情
    """
    stmt = select(Project).where(Project.id == project_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_project_by_chapterid(db: AsyncSession, chapter_id: int):
    """
    根据ID获取项目详情
    """
    stmt = select(Projectchapter.project_id).where(Projectchapter.chapter_id == chapter_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_project(
    db: AsyncSession,
    project_id: int,
    update_data: Dict[str, Any]
):
    """
    更新项目信息。
    时间戳统一由本层联动维护，调用方只传业务字段、不显式传时间戳：
    - concept / worldline 非空更新 → concept_updated_at / worldline_updated_at
    - description 更新（含置空）  → description_updated_at
    - Project_summary 更新        → summary_generated_at（手写与后台重算的概要都视为"已生成"）
    """
    # 先查询对象是否存在 (为了后续 refresh，如果不需返回对象可直接用 update statement)
    stmt = select(Project).where(Project.id == project_id)
    result = await db.execute(stmt)
    db_obj = result.scalar_one_or_none()

    if not db_obj:
        return None

    now = datetime.now()
    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)
            # concept/worldline 仅真值更新才顶时间（空壳/置 None 不算设定变更）；
            # description/Project_summary 只要字段出现就顶——写入即变更，置空也是内容现状
            if field == "concept" and value:
                db_obj.concept_updated_at = now
            elif field == "worldline" and value:
                db_obj.worldline_updated_at = now
            elif field == "description":
                db_obj.description_updated_at = now
            elif field == "Project_summary":
                db_obj.summary_generated_at = now

    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def delete_project(db: AsyncSession, project_id: int):
    """
    删除项目
    性能优化：直接执行 DELETE 语句，无需先 SELECT
    """
    stmt = delete(Project).where(Project.id == project_id)
    await db.execute(stmt)

    stmt = delete(Projectchapter).where(Projectchapter.project_id == project_id)
    await db.execute(stmt)

    stmt = delete(Projectcharacter).where(Projectcharacter.project_id == project_id)
    await db.execute(stmt)

    stmt = delete(Projectchat).where(Projectchat.project_id == project_id)
    await db.execute(stmt)
    
    # ✨ 新增：级联删除卷
    stmt = delete(Volume).where(Volume.project_id == project_id)
    await db.execute(stmt)

async def delete_projects(
        db: AsyncSession,
        project_ids: List[int]
):
    """
    批量删除项目
    性能优化：直接执行 DELETE 语句，无需先 SELECT
    注意：不在此处 commit，由调用方统一提交
    """
    if not project_ids:
        return

    stmt = delete(Project).where(Project.id.in_(project_ids))
    await db.execute(stmt)

    stmt = delete(Projectchapter).where(Projectchapter.project_id.in_(project_ids))
    await db.execute(stmt)

    stmt = delete(Projectcharacter).where(Projectcharacter.project_id.in_(project_ids))
    await db.execute(stmt)

    stmt = delete(Projectchat).where(Projectchat.project_id.in_(project_ids))
    await db.execute(stmt)
    
    # ✨ 新增：级联删除卷
    stmt = delete(Volume).where(Volume.project_id.in_(project_ids))
    await db.execute(stmt)


async def add_project_chapter(
    db: AsyncSession,
    project_id: int,
    chapter_id: int
) -> Projectchapter:
    """添加项目-章节关联"""
    db_obj = Projectchapter(project_id=project_id, chapter_id=chapter_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_chapter_counts(db: AsyncSession,project_ids: List[int]):
    if not project_ids:
        return {}

    stmt = (
        select(
            Projectchapter.project_id,
            func.count(Projectchapter.id).label("cnt"),
        )
        .where(Projectchapter.project_id.in_(project_ids))
        .group_by(Projectchapter.project_id)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return {project_id: count for project_id, count in rows}

async def remove_project_chapter(
    db: AsyncSession,
    chapter_id: int
) -> bool:
    """删除项目-章节关联"""
    stmt = delete(Projectchapter).where(
            Projectchapter.chapter_id == chapter_id
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def add_project_character(
    db: AsyncSession,
    project_id: int,
    character_id: int
) -> Projectcharacter:
    """添加项目-角色关联"""
    db_obj = Projectcharacter(project_id=project_id, character_id=character_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_character_counts(db: AsyncSession,project_ids: List[int]):
    if not project_ids:
        return {}

    stmt = (
        select(
            Projectcharacter.project_id,
            func.count(Projectcharacter.id).label("cnt"),
        )
        .where(Projectcharacter.project_id.in_(project_ids))
        .group_by(Projectcharacter.project_id)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return {project_id: count for project_id, count in rows}

async def remove_project_character(
    db: AsyncSession,
    character_id: int
) -> bool:
    """删除项目-角色关联"""
    stmt = delete(Projectcharacter).where(
            Projectcharacter.character_id == character_id
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def add_project_chat(
    db: AsyncSession,
    project_id: int,
    chat_id: int
) -> Projectchat:
    """添加项目-聊天关联"""
    db_obj = Projectchat(project_id=project_id, chat_id=chat_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def remove_project_chat(
    db: AsyncSession,
    chat_id: int
) -> bool:
    """删除项目-聊天关联"""
    stmt = delete(Projectchat).where(
            Projectchat.chat_id == chat_id
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def get_project_knowledges(
        db: AsyncSession,
        project_id: int
) -> List[Projectknowledge]:
    """获取项目引用的素材列表"""
    stmt = select(Projectknowledge).where(Projectknowledge.project_id == project_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())

async def add_project_knowledge(
        db: AsyncSession,
        project_id: int,
        knowledge: str
) -> Projectknowledge:
    """添加项目-素材映射（传入项目id与素材内容）"""
    db_obj = Projectknowledge(project_id=project_id, knowledge=knowledge)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def delete_project_knowledge(
        db: AsyncSession,
        knowledge_id: int
) -> bool:
    """删除项目-素材映射（通过项目素材映射id）"""
    stmt = delete(Projectknowledge).where(Projectknowledge.id == knowledge_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0

async def delete_project_knowledge_by_content(
        db: AsyncSession,
        project_id: int,
        knowledge: str
) -> bool:
    """删除项目-素材映射（通过项目id与素材内容精确匹配）"""
    stmt = delete(Projectknowledge).where(
        Projectknowledge.project_id == project_id,
        Projectknowledge.knowledge == knowledge
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def delete_project_knowledge_by_projectid(
        db: AsyncSession,
        project_id: int
) -> bool:
    """删除项目-素材映射（通过项目素材映射id）"""
    stmt = delete(Projectknowledge).where(Projectknowledge.project_id == project_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0

async def delete_project_knowledge_by_projectids(
        db: AsyncSession,
        project_ids: List[int]
) -> bool:
    """删除项目-素材映射（通过项目素材映射id）"""
    stmt = delete(Projectknowledge).where(Projectknowledge.project_id.in_(project_ids))
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0

async def remove_project_chapters(db: AsyncSession, chapter_ids: List[int]) -> int:
    """批量删除项目-章节映射（不提交，由调用方控制事务）"""
    if not chapter_ids:
        return 0
    result = await db.execute(
        delete(Projectchapter).where(Projectchapter.chapter_id.in_(chapter_ids))
    )
    return result.rowcount
