from datetime import datetime

from models.Chapter import Chapter
from typing import Dict, Any, List, Tuple, Optional
from schemas.Chapter import ChapterCreate
from models.Project import Projectchapter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_, update, case




async def add_chapter(
    db: AsyncSession,
    chapter_title: str,
    chapter_index: int,
    chapter_content: str,
    chapter_summary: str = ""
):
    """
    创建新章节
    """
    db_obj = Chapter(
        chapter_title=chapter_title,
        chapter_index=chapter_index,
        chapter_content=chapter_content,
        chapter_summary=chapter_summary,
        content_updated_at=datetime.now(),  # ✨ NEW: 设置内容更新时间
        summary_generated_at=datetime.now()  # ✨ NEW: 摘要未生成
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def add_chapter_by_model(
    db: AsyncSession,
    chapter: ChapterCreate,
):
    """
    创建新章节
    """
    # 如果传入的 chapter_content 非空 → 更新 content_updated_at
    now = datetime.now()
    db_obj = Chapter(
        **chapter.model_dump(),
        content_updated_at=now if (chapter.chapter_content and chapter.chapter_content.strip()) else None,
        summary_generated_at=datetime.now()  # ✨ NEW: 明确设置为 None
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_chapterid_by_project(db: AsyncSession, project_id: int):
    """
    获取项目下的所有章节id
    """
    stmt = select(Projectchapter.chapter_id).where(Projectchapter.project_id == project_id)
    result = await db.execute(stmt)
    chapterids = result.scalars().all()
    return chapterids

async def get_chapterid_by_projects(db: AsyncSession, project_ids: List[int]):
    """
    批量获取指定项目列表下的所有章节id
    """
    if not project_ids:
        return []

    stmt = select(Projectchapter.chapter_id).where(Projectchapter.project_id.in_(project_ids))

    result = await db.execute(stmt)
    chapter_ids = result.scalars().all()
    return chapter_ids

async def get_chapter_counts(db: AsyncSession, project_ids: List[int]):
    """
    批量获取指定项目的章节数量

    Args:
        db: 数据库会话
        project_ids: 项目ID列表

    Returns:
        Dict[int, int]: 键为项目ID，值为对应的章节数量 (没有记录的项目默认为0)
    """
    if not project_ids:
        return {}

    # 初始化结果字典，默认为0
    counts = {pid: 0 for pid in project_ids}

    # 使用 GROUP BY 一次性统计所有项目的数量
    stmt = (
        select(Projectchapter.project_id, func.count(Projectchapter.id))
        .where(Projectchapter.project_id.in_(project_ids))
        .group_by(Projectchapter.project_id)
    )

    result = await db.execute(stmt)
    for project_id, count in result.all():
        counts[project_id] = count

    return counts

async def get_chapters_paginated(
    db: AsyncSession,
    project_id: int,
    offset: int = 0,
    limit: int = 10
):
    """
    分页获取指定项目下的章节列表，并返回总数
    """
    # 1. 获取该项目的关联章节总数
    count_stmt = (
        select(func.count(Chapter.id))
        .join(Projectchapter, Chapter.id == Projectchapter.chapter_id)
        .where(Projectchapter.project_id == project_id)
    )
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    # 2. 获取章节列表
    # 使用 Join 关联映射表，过滤出属于该项目的章节
    list_stmt = (
        select(Chapter)
        .join(Projectchapter, Chapter.id == Projectchapter.chapter_id)
        .where(Projectchapter.project_id == project_id)
        .order_by(Chapter.chapter_index) # 按索引排序
        .offset(offset)
        .limit(limit)
    )
    list_result = await db.execute(list_stmt)
    chapters = list_result.scalars().all()

    return chapters, total


async def get_chapter_by_id(db: AsyncSession, chapter_id: int):
    """
    根据ID获取章节详情
    """
    stmt = select(Chapter).where(Chapter.id == chapter_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_chapter_summary_rows(db: AsyncSession, project_id: int):
    """
    只取章节的摘要相关列（不拉正文），按 chapter_index 升序。

    长篇下批量取摘要/扫陈旧用：避免为了几行摘要把每章 3 万字正文全load进内存。
    返回 Row 列表，字段：id / chapter_index / chapter_title / chapter_summary /
    content_updated_at / summary_generated_at。
    """
    stmt = (
        select(
            Chapter.id,
            Chapter.chapter_index,
            Chapter.chapter_title,
            Chapter.chapter_summary,
            Chapter.content_updated_at,
            Chapter.summary_generated_at,
        )
        .join(Projectchapter, Chapter.id == Projectchapter.chapter_id)
        .where(Projectchapter.project_id == project_id)
        .order_by(Chapter.chapter_index)
    )
    result = await db.execute(stmt)
    return result.all()


async def get_chapter_by_index_project_id(db: AsyncSession, project_id: int, chapter_index: int):
    """
    通过 project_id 和 chapter_index 查找对应的 chapter。

    Args:
        db: async session
        project_id: 项目 ID
        chapter_index: 章节索引

    Returns:
        Chapter 对象或 None
    """
    stmt = (
        select(Chapter)
        .join(Projectchapter, Chapter.id == Projectchapter.chapter_id)
        .where(
            Projectchapter.project_id == project_id,
            Chapter.chapter_index == chapter_index
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_chapter_index_by_id(db: AsyncSession, chapter_id: int):
    """
    根据ID获取章节详情
    """
    stmt = select(Chapter.chapter_index).where(Chapter.id == chapter_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def shift_chapter_indexes(
        db: AsyncSession,
        project_id: int,
        start_index: int,
        delta: int
):
    """
    同项目内 chapter_index >= start_index 的章节序号整体平移 delta
    （插入章节时 +1 / 删除章节时 -1；不提交，由调用方控制事务）
    """
    stmt = (
        update(Chapter)
        .values(chapter_index=Chapter.chapter_index + delta)
        .where(Chapter.chapter_index >= start_index)
        .where(
            select(Projectchapter.chapter_id)
            .where(
                and_(
                    Projectchapter.chapter_id == Chapter.id,
                    Projectchapter.project_id == project_id
                )
            )
            .exists()
        )
    )
    await db.execute(stmt)


async def get_chapter_index_map_by_project(db: AsyncSession, project_id: int) -> Dict[int, int]:
    """
    获取项目全量章节的 id → chapter_index 轻量映射（只查两列，不加载正文）
    """
    stmt = (
        select(Chapter.id, Chapter.chapter_index)
        .join(Projectchapter, Chapter.id == Projectchapter.chapter_id)
        .where(Projectchapter.project_id == project_id)
    )
    result = await db.execute(stmt)
    return {cid: idx for cid, idx in result.all()}

async def reorder_chapter_indexes(
        db: AsyncSession,
        ordered_ids: List[int]
):
    """
    按给定章节 ID 顺序把对应章节的 chapter_index 重排为 0..n-1
    （单条 CASE UPDATE；不提交，由调用方控制事务）
    """
    if not ordered_ids:
        return
    stmt = (
        update(Chapter)
        .values(chapter_index=case(
            *[(Chapter.id == cid, idx) for idx, cid in enumerate(ordered_ids)]
        ))
        .where(Chapter.id.in_(ordered_ids))
    )
    await db.execute(stmt)

async def update_chapter(
    db: AsyncSession,
    chapter_id: int,
    update_data: Dict[str, Any]
):
    """
    更新章节信息
    """
    stmt = select(Chapter).where(Chapter.id == chapter_id)
    result = await db.execute(stmt)
    db_obj = result.scalar_one_or_none()

    if not db_obj:
        return None

    # ✨ 如果只更新了 chapter_content，没有传 chapter_summary，
    #    则自动截取 chapter_content 前 800 字作为 chapter_summary
    if (
        "chapter_content" in update_data
        and update_data.get("chapter_content")
        and "chapter_summary" not in update_data
    ):
        content = update_data["chapter_content"]
        update_data["chapter_summary"] = content[:800]

    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)
            # 如果更新了 chapter_content → 更新时间戳
            if field == "chapter_content" and value:
                db_obj.content_updated_at = datetime.now()
            if field == "chapter_summary" and value:
                db_obj.summary_generated_at = datetime.now()

    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def delete_chapter(db: AsyncSession, chapter_id: int):
    """
    删除章节
    """
    stmt = delete(Chapter).where(Chapter.id == chapter_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def delete_chapters_by_project(
        db: AsyncSession,
        project_id: int
):
    """
    高效删除指定项目下的所有章节（无外键环境）

    策略：
    1. 使用 EXISTS 代替 IN，避免生成巨大的 ID 列表，减少内存消耗。
    2. 手动清理映射表，防止产生脏数据。
    """
    delete_chapter_stmt = (
        delete(Chapter)
        .where(
            select(Projectchapter.chapter_id)
            .where(
                and_(
                    Projectchapter.chapter_id == Chapter.id,
                    Projectchapter.project_id == project_id
                )
            )
            .exists()
        )
    )
    await db.execute(delete_chapter_stmt)

    delete_mapping_stmt = (
        delete(Projectchapter)
        .where(Projectchapter.project_id == project_id)
    )
    await db.execute(delete_mapping_stmt)

async def delete_chapters_by_projects(
        db: AsyncSession,
        project_ids: List[int]
):
    """
    批量高效删除指定项目下的所有章节（无外键环境）

    策略：
    1. 使用 EXISTS 配合 IN，避免生成巨大的 ID 列表，减少内存消耗。
    2. 手动清理映射表，防止产生脏数据。
    3. 注意：此处移除了 commit，由调用方（路由层）统一控制事务。
    """
    if not project_ids:
        return

    # 1. 删除 Chapter
    # 只要 Chapter 的 ID 存在于 Projectchapter 表中，且对应的 project_id 在输入列表中，就删除
    delete_chapter_stmt = (
        delete(Chapter)
        .where(
            select(Projectchapter.chapter_id)
            .where(
                and_(
                    Projectchapter.chapter_id == Chapter.id,
                    # 使用 .in_() 进行批量匹配
                    Projectchapter.project_id.in_(project_ids)
                )
            )
            .exists()
        )
    )
    await db.execute(delete_chapter_stmt)

    # 2. 删除映射表
    delete_mapping_stmt = (
        delete(Projectchapter)
        .where(Projectchapter.project_id.in_(project_ids))
    )
    await db.execute(delete_mapping_stmt)

async def get_chapter_index_map(db: AsyncSession, project_id: int):
    """轻量章节映射，返回 (chapter_index→id, id→chapter_index)。
    只取 id / chapter_index 两列，不加载 chapter_content（每章 3 万字），
    避免为拿个映射把整个项目的正文拉进内存。"""
    stmt = (
        select(Chapter.id, Chapter.chapter_index)
        .join(Projectchapter, Projectchapter.chapter_id == Chapter.id)
        .where(Projectchapter.project_id == project_id)
    )
    rows = (await db.execute(stmt)).all()
    return ({idx: cid for cid, idx in rows}, {cid: idx for cid, idx in rows})
async def get_chapter_times_by_project(
    db: AsyncSession,
    project_id: int,
) -> List[Tuple[int, Optional[str], int, Optional[datetime]]]:
    """查询指定项目下所有章节的时间信息。

    返回 [(chapter_id, chapter_summary, chapter_index, time)]，按 chapter_index 升序。
    其中 time = max(content_updated_at, summary_generated_at)：
      - 两者都有值 → 取较大者；
      - 只有一个有值 → 取该值；
      - 都为 NULL  → time 为 None（章节从未写过正文/摘要）。
    """
    stmt = (
        select(
            Chapter.id,
            Chapter.chapter_summary,
            Chapter.chapter_index,
            Chapter.content_updated_at,
            Chapter.summary_generated_at,
        )
        .join(Projectchapter, Projectchapter.chapter_id == Chapter.id)
        .where(Projectchapter.project_id == project_id)
        .order_by(Chapter.chapter_index.asc())
    )
    rows =(await db.execute(stmt)).all()

    result: List[Tuple[int, Optional[str], int, Optional[datetime]]] = []
    for chapter_id, summary, chapter_index, content_at, summary_at in rows:
        times = [t for t in (content_at, summary_at) if t is not None]
        result.append((chapter_id, summary, chapter_index, max(times) if times else None))
    return result

async def get_chapter_briefs_by_index_range(
    db: AsyncSession,
    project_id: int,
    start: int,
    end: int,
) -> List[dict]:
    """取 [start, end]（0-based 闭区间）章节的列表字段（id/索引/标题/字数），不加载正文。

    目录树 / 卷章节分页用。word_count = 正文字符长度（HTML 口径，与前端
    getChapter/saveChapter 一致）；sqlite length() 按字符计，对中文友好。"""
    stmt = (
        select(
            Chapter.id,
            Chapter.chapter_index,
            Chapter.chapter_title,
            func.coalesce(func.length(Chapter.chapter_content), 0),
        )
        .join(Projectchapter, Projectchapter.chapter_id == Chapter.id)
        .where(Projectchapter.project_id == project_id)
        .where(Chapter.chapter_index >= start)
        .where(Chapter.chapter_index <= end)
        .order_by(Chapter.chapter_index)
    )
    result = await db.execute(stmt)
    return [
        {"id": r[0], "chapter_index": r[1], "title": r[2], "word_count": int(r[3])}
        for r in result.all()
    ]


async def get_chapter_ids_by_index_range(
    db: AsyncSession,
    project_id: int,
    start: int,
    end: int
) -> List[int]:
    """取项目内 chapter_index 落在 [start, end]（0-based 闭区间）的章节 id，按索引升序。

    只取 id 列不加载正文，供整卷删除等批量级联清理用。
    """
    stmt = (
        select(Chapter.id)
        .join(Projectchapter, Projectchapter.chapter_id == Chapter.id)
        .where(Projectchapter.project_id == project_id)
        .where(Chapter.chapter_index >= start)
        .where(Chapter.chapter_index <= end)
        .order_by(Chapter.chapter_index)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())

async def get_chapter_by_index_range(
    db: AsyncSession,
    project_id: int,
    start: int | None,
    end: int | None,
) -> List[Chapter]:
    """取项目内 chapter_index 落在 [start, end]（0-based 闭区间）的章节，按索引升序。

    start / end 传 None 表示该侧不设限（get_chapter_summaries 不传范围取全部时用）；
    其余调用方（整卷删除等批量级联清理）传具体值，行为不变。
    """
    stmt = (
        select(Chapter)
        .join(Projectchapter, Projectchapter.chapter_id == Chapter.id)
        .where(Projectchapter.project_id == project_id)
    )
    if start is not None:
        stmt = stmt.where(Chapter.chapter_index >= start)
    if end is not None:
        stmt = stmt.where(Chapter.chapter_index <= end)
    stmt = stmt.order_by(Chapter.chapter_index)
    result = await db.execute(stmt)
    return list(result.scalars().all())

async def delete_chapters_by_ids(db: AsyncSession, chapter_ids: List[int]) -> int:
    """按 id 批量删除章节行（不提交，由调用方控制事务；映射表由调用方另行清理）"""
    if not chapter_ids:
        return 0
    result = await db.execute(delete(Chapter).where(Chapter.id.in_(chapter_ids)))
    return result.rowcount