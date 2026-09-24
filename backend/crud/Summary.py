from models.Summary import Summary
from typing import Any, Dict, List
from models.ChatRecord import ChatRecord
from sqlalchemy import delete, func, select, insert
from models.Summary import SummaryChatRecord
from sqlalchemy.ext.asyncio import AsyncSession

async def add_summary(
        db: AsyncSession,
        project_id: int,
        chatcontext: str,
        index: int
):
    db_obj = Summary(
        project_id=project_id,
        chatcontext=chatcontext,
        index=index
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_summaries_paginated(
        db: AsyncSession,
        offset: int = 0,
        limit: int = 10
):
    count_stmt = select(func.count(Summary.id))
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    list_stmt = (
        select(Summary)
        .order_by(Summary.index.desc())
        .offset(offset)
        .limit(limit)
    )
    list_result = await db.execute(list_stmt)
    summaries = list_result.scalars().all()
    return summaries, total


async def get_summary_by_id(db: AsyncSession, summary_id: int):
    stmt = select(Summary).where(Summary.id == summary_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_summary(
        db: AsyncSession,
        summary_id: int,
        update_data: Dict[str, Any]
):
    stmt = select(Summary).where(Summary.id == summary_id)
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

async def get_latest_summary_by_project(
    db: AsyncSession,
    project_id: int
):
    """
    获取指定项目最新的摘要记录
    """
    stmt = (
        select(Summary)
        .where(Summary.project_id == project_id)
        .order_by(Summary.index.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_summary_end_timestamp(
    db: AsyncSession,
    summary_id: int
):
    """
    获取某个摘要关联的聊天记录中最大的时间戳
    即：该摘要覆盖到了哪个时间点
    """
    stmt = (
        select(func.max(ChatRecord.timestamp))
        .select_from(SummaryChatRecord)
        .join(ChatRecord, SummaryChatRecord.chatrecord_id == ChatRecord.id)
        .where(SummaryChatRecord.summary_id == summary_id)
    )
    result = await db.execute(stmt)
    return result.scalar()

async def add_summary_chat_record(
        db: AsyncSession,
        summary_id: int,
        chatrecord_id: int
):
    """添加单个摘要-聊天记录关联"""
    db_obj = SummaryChatRecord(summary_id=summary_id, chatrecord_id=chatrecord_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def add_summary_chat_records_batch(
        db: AsyncSession,
        summary_id: int,
        chatrecord_ids: List[int]
):
    """批量添加摘要-聊天记录关联"""
    if not chatrecord_ids:
        return
    values = [{"summary_id": summary_id, "chatrecord_id": cid} for cid in chatrecord_ids]
    stmt = insert(SummaryChatRecord).values(values)
    await db.execute(stmt)
    await db.commit()


async def delete_summary_chat_record_by_summary(
        db: AsyncSession,
        summary_id: int
):
    """删除指定摘要的所有关联"""
    stmt = delete(SummaryChatRecord).where(SummaryChatRecord.summary_id == summary_id)
    await db.execute(stmt)


async def delete_summary_chat_record_by_chatrecord(
        db: AsyncSession,
        chatrecord_id: int
):
    """删除指定聊天记录的所有关联"""
    stmt = delete(SummaryChatRecord).where(SummaryChatRecord.chatrecord_id == chatrecord_id)
    await db.execute(stmt)


async def delete_summary_chat_record_by_chatrecords(
        db: AsyncSession,
        chatrecord_ids: List[int]
):
    """批量删除聊天记录的关联"""
    if not chatrecord_ids:
        return
    stmt = delete(SummaryChatRecord).where(SummaryChatRecord.chatrecord_id.in_(chatrecord_ids))
    await db.execute(stmt)


# ------------------ 删除逻辑 (更新) ------------------

async def delete_summary(db: AsyncSession, summary_id: int):
    """删除摘要，并同时清理关联映射"""
    await delete_summary_chat_record_by_summary(db, summary_id)

    stmt = delete(Summary).where(Summary.id == summary_id)
    result = await db.execute(stmt)

    await db.commit()
    return result.rowcount > 0


async def delete_summaries_by_chatrecord_id(
        db: AsyncSession,
        chatrecord_id: int
):
    """
    根据聊天记录ID查找并删除关联的摘要及其映射
    逻辑：
    1. 查询 summarychatrecord 表，找到该 chatrecord_id 对应的所有 summary_id。
    2. 删除这些 summary_id 在映射表中的所有记录。
    3. 删除 summary 表中的记录。
    """
    stmt_select_ids = (
        select(SummaryChatRecord.summary_id)
        .where(SummaryChatRecord.chatrecord_id == chatrecord_id)
    )
    result = await db.execute(stmt_select_ids)
    summary_ids = result.scalars().all()

    if not summary_ids:
        return

    stmt_del_map = (
        delete(SummaryChatRecord)
        .where(SummaryChatRecord.summary_id.in_(summary_ids))
    )
    await db.execute(stmt_del_map)

    stmt_del_summary = (
        delete(Summary)
        .where(Summary.id.in_(summary_ids))
    )
    await db.execute(stmt_del_summary)

    await db.commit()


async def delete_summaries_from_record(
        db: AsyncSession,
        project_id: int,
        chatrecord_id: int,
):
    """
    编辑/重发场景：删除覆盖该记录及其后内容的所有摘要（按 index 链）。

    summaries 按 index 单调递增形成链（compress.py: next_index = latest.index + 1）。
    编辑点 R 锚定的摘要及其所有后续摘要都因内容变更而失效，必须一并删除；
    否则 latest 指向悬空摘要 → get_summary_end_timestamp 的 join 落空 → 上下文污染。

    比 timestamp 方案更稳：update_chatrecord_and_clear_future 已删后续记录及其
    Projectchat 映射，到本函数时基于 join 的 end_timestamp 已失效；index 链与
    记录/映射存在与否无关，顺序无关。
    """
    # 1. 找到映射到该记录的摘要 index（取最小，作为失效链头）
    stmt_idx = (
        select(Summary.index)
        .join(SummaryChatRecord, SummaryChatRecord.summary_id == Summary.id)
        .where(SummaryChatRecord.chatrecord_id == chatrecord_id)
        .where(Summary.project_id == project_id)
    )
    res = await db.execute(stmt_idx)
    indices = res.scalars().all()
    if not indices:
        # 记录不在任何摘要映射中（处于最新摘要之后的原文区）→ 无摘要失效
        return
    min_idx = min(indices)

    # 2. 删该项目下所有 index >= min_idx 的摘要及其映射
    stmt_ids = select(Summary.id).where(
        Summary.project_id == project_id,
        Summary.index >= min_idx,
    )
    res_ids = await db.execute(stmt_ids)
    summary_ids = res_ids.scalars().all()
    if not summary_ids:
        return

    await db.execute(
        delete(SummaryChatRecord).where(SummaryChatRecord.summary_id.in_(summary_ids))
    )
    await db.execute(delete(Summary).where(Summary.id.in_(summary_ids)))
    await db.commit()


async def delete_summary_by_project(
        db: AsyncSession,
        project_id: int
):
    """删除指定项目下的摘要记录及其映射"""
    stmt_ids = select(Summary.id).where(Summary.project_id == project_id)
    result_ids = await db.execute(stmt_ids)
    summary_ids = result_ids.scalars().all()

    if summary_ids:
        # 2. 删除映射表
        stmt_del_map = delete(SummaryChatRecord).where(SummaryChatRecord.summary_id.in_(summary_ids))
        await db.execute(stmt_del_map)

    # 3. 删除摘要
    stmt = delete(Summary).where(Summary.project_id == project_id)
    await db.execute(stmt)


async def delete_summary_by_projects(
        db: AsyncSession,
        project_ids: List[int]
):
    """批量删除指定项目下的摘要记录及其映射"""
    if not project_ids:
        return

    stmt_ids = select(Summary.id).where(Summary.project_id.in_(project_ids))
    result_ids = await db.execute(stmt_ids)
    summary_ids = result_ids.scalars().all()

    if summary_ids:
        stmt_del_map = delete(SummaryChatRecord).where(SummaryChatRecord.summary_id.in_(summary_ids))
        await db.execute(stmt_del_map)

    stmt = delete(Summary).where(Summary.project_id.in_(project_ids))
    await db.execute(stmt)
