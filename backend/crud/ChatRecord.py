from datetime import datetime
from typing import Any, Dict, List
import json
from models.Project import Projectchat
from models.ChatRecord import ChatRecord
from schemas.ChatRecord import ChatRecordCreate
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, func, select, and_


async def add_chatrecord(
    db: AsyncSession,
    role: str,
    content: str,
    type: str,
    timestamp: Any,
    extra: str = ""
):
    """
    创建新聊天消息（extra = 行协议外层的 call_id，tool_call/audiobook 行用）
    """
    db_obj = ChatRecord(
        role=role,
        content=content,
        timestamp=timestamp,
        type=type,
        extra=extra
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def add_chatrecord_by_model(
    db: AsyncSession,
    chatrecord: ChatRecordCreate
):
    """
    创建新聊天消息
    """
    db_obj = ChatRecord(**chatrecord.model_dump())
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_chatrecords_by_paginated(
    db: AsyncSession,
    project_id: int,
    offset: int = 0,
    limit: int = 10
):
    """
    通过映射表获取指定项目下的所有聊天消息（支持分页和全量）
    性能优化：使用 Join 一次性查询，按时间正序（最早在前，最新在后——
    聊天界面自上而下阅读，与 build_context 拉历史时的排序一致）
    """
    # 获取该项目的关联聊天消息总数
    count_stmt = (
        select(func.count(ChatRecord.id))
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(Projectchat.project_id == project_id)
    )
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    # 获取聊天消息列表（正序：最早在前，最新在后）
    # 排序必须带唯一 tiebreaker（id）：Windows 下 datetime.now() 分辨率粗（~15ms），
    # 一轮里连着插入的多条记录 timestamp 常相等；只按 timestamp 排则相等项顺序不稳定，
    # OFFSET/LIMIT 翻页时同一条可能落在相邻两页 → 前端顶部懒加载 prepend 出现"重复一轮"。
    # timestamp 相同则按自增 id（=插入先后）定序，得到全序、分页确定、不再重叠。
    list_stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(Projectchat.project_id == project_id)
        .order_by(ChatRecord.timestamp.asc(), ChatRecord.id.asc())
        .offset(offset)
        .limit(limit)
    )
    list_result = await db.execute(list_stmt)
    chatrecords = list_result.scalars().all()

    return chatrecords, total


async def get_chatrecord_by_id(db: AsyncSession, chat_id: int):
    """
    根据ID获取聊天消息详情
    """
    stmt = select(ChatRecord).where(ChatRecord.id == chat_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_chatrecord(
    db: AsyncSession,
    chat_id: int,
    update_data: Dict[str, Any]
):
    """
    更新聊天消息信息
    """
    stmt = select(ChatRecord).where(ChatRecord.id == chat_id)
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


async def delete_chatrecord(db: AsyncSession, chat_id: int):
    """
    删除聊天消息
    """
    stmt = delete(ChatRecord).where(ChatRecord.id == chat_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def delete_chatrecords_by_project(
        db: AsyncSession,
        project_id: int
):
    """
    高效删除指定项目下的所有聊天（无外键环境）

    策略：
    1. 使用 EXISTS 代替 IN，避免生成巨大的 ID 列表，减少内存消耗。
    2. 手动清理映射表，防止产生脏数据。
    """
    delete_chatrecord_stmt = (
        delete(ChatRecord)
        .where(
            select(Projectchat.chat_id)
            .where(
                and_(
                    Projectchat.chat_id == ChatRecord.id,
                    Projectchat.project_id == project_id
                )
            )
            .exists()
        )
    )
    await db.execute(delete_chatrecord_stmt)

    delete_mapping_stmt = (
        delete(Projectchat)
        .where(Projectchat.project_id == project_id)
    )
    await db.execute(delete_mapping_stmt)

async def delete_chatrecords_by_projects(
        db: AsyncSession,
        project_ids: List[int]  # 改为 List
):
    """
    批量删除指定项目下的所有聊天
    """
    if not project_ids:
        return

    # 1. 删除 ChatRecord
    # 逻辑：在 Projectchat 中能找到对应 project_id (IN 列表) 的记录，就删除该 ChatRecord
    delete_chat_stmt = (
        delete(ChatRecord)
        .where(
            select(Projectchat.chat_id)
            .where(
                and_(
                    Projectchat.chat_id == ChatRecord.id,
                    # 使用 in_ 批量匹配
                    Projectchat.project_id.in_(project_ids)
                )
            )
            .exists()
        )
    )
    await db.execute(delete_chat_stmt)

    # 2. 删除 Projectchat 映射表
    delete_mapping_stmt = (
        delete(Projectchat)
        .where(Projectchat.project_id.in_(project_ids)) # 使用 in_ 批量匹配
    )
    await db.execute(delete_mapping_stmt)


async def update_chatrecord_and_clear_future(
        db: AsyncSession,
        chat_id: int,
        update_data: Dict[str, Any]
):
    """
    更新聊天记录，并删除同一项目下时间戳晚于该记录的所有后续记录。

    流程：
    1. 获取当前记录的时间戳。
    2. 通过映射表查找该记录所属的项目ID。
    3. 更新当前记录。
    4. 查找同一项目下时间戳更新的记录ID列表。
    5. 删除映射表中的关联。
    6. 删除聊天记录。
    """
    stmt = select(ChatRecord).where(ChatRecord.id == chat_id)
    result = await db.execute(stmt)
    db_obj = result.scalar_one_or_none()

    if not db_obj:
        return None

    current_timestamp = db_obj.timestamp

    stmt_proj = select(Projectchat.project_id).where(Projectchat.chat_id == chat_id)
    result_proj = await db.execute(stmt_proj)
    project_id = result_proj.scalar_one_or_none()

    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)

    if project_id:
        stmt_future_ids = (
            select(ChatRecord.id)
            .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
            .where(
                and_(
                    Projectchat.project_id == project_id,
                    ChatRecord.timestamp > current_timestamp
                )
            )
        )

        result_future = await db.execute(stmt_future_ids)
        future_ids = result_future.scalars().all()

        if future_ids:
            stmt_del_map = delete(Projectchat).where(Projectchat.chat_id.in_(future_ids))
            await db.execute(stmt_del_map)

            stmt_del_rec = delete(ChatRecord).where(ChatRecord.id.in_(future_ids))
            await db.execute(stmt_del_rec)

    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_chatrecords_after_timestamp(
        db: AsyncSession,
        project_id: int,
        timestamp: datetime
):
    """
    获取指定项目下，时间戳晚于指定时间的所有聊天记录（时间正序）
    用于获取摘要之后的增量对话
    """
    stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(Projectchat.project_id == project_id)
        .where(ChatRecord.timestamp > timestamp)
        .order_by(ChatRecord.timestamp.asc(), ChatRecord.id.asc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_recent_chatrecords(
        db: AsyncSession,
        project_id: int,
        limit: int = 20
):
    """
    获取指定项目下最近的N条聊天记录（时间正序返回）
    用于没有摘要时获取全量上下文
    """
    subquery = (
        select(ChatRecord.id)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(Projectchat.project_id == project_id)
        .order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc())
        .limit(limit)
    ).subquery()

    stmt = (
        select(ChatRecord)
        .where(ChatRecord.id.in_(select(subquery)))
        .order_by(ChatRecord.timestamp.asc(), ChatRecord.id.asc())
    )

    result = await db.execute(stmt)
    return result.scalars().all()


async def get_records_for_context(
        db: AsyncSession,
        project_id: int,
        summary_end_timestamp: datetime = None,
        hard_limit: int = 50,
        exclude_record_id: int = None  # 新增：需要排除的记录ID
):
    stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(Projectchat.project_id == project_id)
    )

    if summary_end_timestamp:
        stmt = stmt.where(ChatRecord.timestamp > summary_end_timestamp)

    # 排除当前正在处理的记录，防止上下文"预知"当前问题
    if exclude_record_id:
        stmt = stmt.where(ChatRecord.id != exclude_record_id)

    # 窗口语义：摘要点之后的【最近 N 条】。先 desc+limit 取最近，再 reversed 还原时序
    # （若改回 asc+limit 会取到最旧 N 条，恰好截掉最该看见的近期上下文）。
    stmt = stmt.order_by(ChatRecord.timestamp.desc()).limit(hard_limit)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return list(reversed(rows))


async def get_pending_human_tail(db: AsyncSession, project_id: int):
    """取该项目最近一条 type=message 的记录，仅当它是 Human 时返回（否则 None）。

    build_context(exclude_record_id=…) 会排除"当前正在处理"的那条记录防预知，
    但 /context_size 是"打开对话时"查询，此时用户刚发、AI 还没回，最后一条正是
    那条 Human —— 它属于"下一轮真实要送进 LLM 的量"，算上下文占用时必须补回来。
    若最后一条已是 assistant（本轮已答完），则历史完整，无需补。
    """
    stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(and_(
            Projectchat.project_id == project_id,
            ChatRecord.type == "message",
        ))
        .order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    last = result.scalars().first()
    if last and last.role in ("user", "Human"):   # "Human" 为合并前旧库行
        return last
    return None


# ── 镜像行统一解析（两套行协议） ─────────────────────────────
# interrupt 行（写入工具人审）：call_id / action / resolved 全在 content JSON 内。
# audiobook 行（新行协议）：call_id 在行 extra 列，subtype 在 content，
#   终态标记为 content.final（confirmed/reverted/failed/terminated），无 resolved。
# 两套协议的"身份/终态"由此组辅助函数统一读取，四个镜像函数共用。

def _mirror_payload(record) -> dict | None:
    """镜像行 content JSON → dict；损坏/非 dict 返回 None。"""
    try:
        payload = json.loads(record.content)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _mirror_call_id(record, payload: dict) -> str:
    """镜像行的 call_id：audiobook 行在 extra 列，interrupt 行在 content 内。"""
    if record.type == "audiobook":
        return (record.extra or "").strip()
    return str(payload.get("call_id") or "")


def _mirror_action(record, payload: dict) -> str | None:
    """镜像行的次级身份：audiobook 行 = subtype，interrupt 行 = action。"""
    if record.type == "audiobook":
        return payload.get("subtype")
    return payload.get("action")


def _mirror_is_resolved(record, payload: dict) -> bool:
    """镜像行是否已处理：audiobook 看 final，interrupt 看 resolved。"""
    if record.type == "audiobook":
        return bool(payload.get("final"))
    return bool(payload.get("resolved"))


def _mirror_mark(record, payload: dict, approved: bool) -> None:
    """就地写终态标记（不 commit，调用方负责）：audiobook 写 final，interrupt 写 resolved。"""
    if record.type == "audiobook":
        payload["final"] = "confirmed" if approved else "reverted"
    else:
        payload["resolved"] = True
        payload["resolved_as"] = "approved" if approved else "rejected"
    record.content = json.dumps(payload, ensure_ascii=False, default=str)


async def terminate_unresolved_mirrors(db: AsyncSession, project_id: int) -> int:
    """无活跃 run 时把该项目全部未终态镜像行就地标为 terminated。

    用户决策（2026-09-22）：应用重开后未决的 interrupt / audiobook 卡不再走镜像恢复链
    （payload 复活可操作卡不符合"聊天已结束"的逻辑），一律置终止。
    audiobook 行写 final=terminated，interrupt 行写 resolved + resolved_as=terminated。

    Returns:
        标记的行数
    """
    stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(and_(
            Projectchat.project_id == project_id,
            ChatRecord.type.in_(["interrupt", "audiobook"]),
        ))
        .order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    count = 0
    for record in result.scalars().all():
        payload = _mirror_payload(record)
        if payload is None:
            continue
        if _mirror_is_resolved(record, payload):
            continue
        if record.type == "audiobook":
            payload["final"] = "terminated"
        else:
            payload["resolved"] = True
            payload["resolved_as"] = "terminated"
        record.content = json.dumps(payload, ensure_ascii=False, default=str)
        count += 1
    if count:
        await db.commit()
    return count


async def mark_awaiting_resolved(
        db: AsyncSession,
        project_id: int,
        approved: bool
):
    """resume / cancel 时标记最近的 awaiting_input 镜像记录为已处理。

    找该项目最近一条 type IN (interrupt, audiobook) 的记录，
    audiobook 行写 final（confirmed/reverted），interrupt 行写 resolved + resolved_as。
    前端 dbToMessage 解析到终态即显示 confirmed/reverted（只读）。
    找不到记录（如 cancel 活跃 run 但无 awaiting）静默返回。
    """
    stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(and_(
            Projectchat.project_id == project_id,
            ChatRecord.type.in_(["interrupt", "audiobook"]),
        ))
        .order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        return
    payload = _mirror_payload(record)
    if payload is None:
        return
    try:
        _mirror_mark(record, payload, approved)
        await db.commit()
    except Exception:
        pass  # 解析失败不阻塞 resume/cancel 主流程


async def get_latest_unresolved_mirror(
        db: AsyncSession,
        project_id: int,
):
    """reload 恢复用：找该项目最近一条未标记终态的镜像记录。

    场景：后端重启后 RunManager 内存清空，但 checkpointer 里图状态仍在。
    从镜像记录 content 里取 _thread_id 重建 RunManager，让 resume 能真正续跑。

    Returns:
        ChatRecord 或 None（无未标记记录 / 解析失败）
    """
    stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(and_(
            Projectchat.project_id == project_id,
            ChatRecord.type.in_(["interrupt", "audiobook"]),
        ))
        .order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc())
        .limit(20)
    )
    result = await db.execute(stmt)
    # 终态标记在 content JSON 内、非独立列，只能取出最近若干条逐条判：
    # 返回第一条「未终态且带 _thread_id」的（只取最近一条会被已终态的新记录挡住旧的未处理镜像）
    for record in result.scalars().all():
        payload = _mirror_payload(record)
        if payload is None:
            continue  # content 损坏，跳过
        if not _mirror_is_resolved(record, payload) and payload.get("_thread_id"):
            return record
    return None


async def get_unresolved_mirror_by_identity(
        db: AsyncSession,
        project_id: int,
        call_id: str,
        action: str = None,
):
    """按身份 (call_id + action) 找该项目最近一条未终态的镜像记录。

    resume 协议按身份认卡而非按位置猜：用户回答的是哪张卡（call_id + 次级身份唯一确定，
    写入工具各 tool_call 有独立 call_id；有声书五处人审共享 call_id 靠 subtype 区分），
    就恢复哪张卡对应的 thread_id，杜绝"最近一条"在多写入/残留旧卡时张冠李戴。

    Args:
        call_id: 被回答的中断的 call_id（audiobook 行在 extra 列、interrupt 行在 content 内）
        action: 中断的次级身份（audiobook = subtype；interrupt = action）；
                None 时只按 call_id 匹配（写入工具 call_id 已唯一）

    Returns:
        ChatRecord 或 None（无匹配 / 解析失败）
    """
    if not call_id:
        return None
    stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(and_(
            Projectchat.project_id == project_id,
            ChatRecord.type.in_(["interrupt", "audiobook"]),
        ))
        .order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc())
        .limit(20)
    )
    result = await db.execute(stmt)
    for record in result.scalars().all():
        payload = _mirror_payload(record)
        if payload is None:
            continue
        if _mirror_is_resolved(record, payload):
            continue
        if _mirror_call_id(record, payload) != call_id:
            continue
        if action is not None and _mirror_action(record, payload) != action:
            continue
        if payload.get("_thread_id"):
            return record
    return None


async def mark_mirror_resolved_by_identity(
        db: AsyncSession,
        project_id: int,
        call_id: str,
        action: str = None,
        approved: bool = False,
) -> bool:
    """按身份 (call_id + action) 精确标记被本次 resume 消费的那一条镜像为已处理。

    只标"用户实际回答、图也确实越过"的那一张，不再"取最近一条"误标其它未处理镜像。
    前端 dbToMessage 解析到终态即显示 confirmed/reverted（只读）。

    Returns:
        是否命中并标记了一条记录
    """
    if not call_id:
        return False
    stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(and_(
            Projectchat.project_id == project_id,
            ChatRecord.type.in_(["interrupt", "audiobook"]),
        ))
        .order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc())
        .limit(20)
    )
    result = await db.execute(stmt)
    for record in result.scalars().all():
        payload = _mirror_payload(record)
        if payload is None:
            continue
        if _mirror_is_resolved(record, payload):
            continue
        if _mirror_call_id(record, payload) != call_id:
            continue
        if action is not None and _mirror_action(record, payload) != action:
            continue
        _mirror_mark(record, payload, approved)
        await db.commit()
        return True
    return False


async def backfill_terminated_tool_calls(
        db: AsyncSession,
        project_id: int,
        scan_limit: int = 100,
) -> int:
    """terminated 补全：应用关闭导致 run 中断时，tool_call 行缺 result 的就地补全落库。

    行协议上 tool_call 行在 result 返回时才 INSERT，正常必有 result；缺 result 只会
    出现在"insert 竞态/异常路径幸存"的行上。此处仅做兜底补全（result = 中断说明），
    供历史回放显示"应用关闭，流程已中断"。必须由调用方保证项目无活跃 run
    （run 闸不活跃）才可执行——在飞工具的 result 马上就到，不能抢跑。

    Returns:
        补全的行数
    """
    stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(and_(
            Projectchat.project_id == project_id,
            ChatRecord.type == "tool_call",
        ))
        .order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc())
        .limit(scan_limit)
    )
    result = await db.execute(stmt)
    patched = 0
    for record in result.scalars().all():
        payload = _mirror_payload(record)
        if payload is None:
            continue
        if payload.get("result") or payload.get("error"):
            continue  # 结果齐备，无需补全
        payload["result"] = "应用关闭，流程已中断（可重新发起）"
        payload["terminated"] = True
        record.content = json.dumps(payload, ensure_ascii=False, default=str)
        patched += 1
    if patched:
        await db.commit()
    return patched


async def search_chatrecords(
    db: AsyncSession,
    project_id: int,
    keyword: str,
    limit: int = 20,
    chat_type: str | None = None,
):
    """模糊搜索项目内聊天记录（content 字面子串匹配，时间新→旧取前 limit 条）。

    返回 {
      "total":            项目聊天总条数（含全部类型），
      "newest_timestamp": 最新一条记录的 timestamp（无记录时 None），
      "matches":          [{"record": ChatRecord, "rank": 全项目第几新(1=最新)}, ...]
    }

    rank 语义：在【整个对话流】里从最新往前数第几条（1 = 就是最新一条），
    不是"在命中结果里排第几"。做法：先按与分页接口完全一致的排序
    （timestamp desc, id desc——tiebreaker 必须带，Windows 下 now() 分辨率粗，
    一轮多条 timestamp 常相等，否则位次不稳定）拉全项目 id 快照定位每条命中
    的位次；再单独查命中行。两次简单查询，不依赖窗口函数，SQLite 版本无要求；
    桌面应用单项目聊天量级下 id 快照内存开销可忽略。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"total": 0, "newest_timestamp": None, "matches": []}

    # 1) 全项目 id 快照（新→旧）：总条数 / 最新时间 / 每条命中的"距最新条数"都从这里来
    snap_stmt = (
        select(ChatRecord.id, ChatRecord.timestamp)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(Projectchat.project_id == project_id)
        .order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc())
    )
    snapshot = (await db.execute(snap_stmt)).all()
    if not snapshot:
        return {"total": 0, "newest_timestamp": None, "matches": []}
    total = len(snapshot)
    newest_ts = snapshot[0].timestamp
    rank_of = {cid: i for i, (cid, _ts) in enumerate(snapshot)}  # 0-based，最新一条 = 0

    # 2) 命中行：contains → LIKE '%kw%'，autoescape=True 把关键词当字面量
    #   （用户输入的 % _ 不作通配符；SQLite LIKE 对 ASCII 不区分大小写，中文无影响）
    stmt = (
        select(ChatRecord)
        .join(Projectchat, ChatRecord.id == Projectchat.chat_id)
        .where(Projectchat.project_id == project_id)
        .where(ChatRecord.content.contains(keyword, autoescape=True))
    )
    if chat_type:
        stmt = stmt.where(ChatRecord.type == chat_type)
    stmt = stmt.order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc()).limit(limit)
    matched = (await db.execute(stmt)).scalars().all()

    matches = []
    for r in matched:
        idx = rank_of.get(r.id)
        # idx None = 快照之后并发新写入的行（罕见）：位次标 -1，调用方兜底展示
        matches.append({"record": r, "rank": (idx + 1) if idx is not None else -1})
    return {"total": total, "newest_timestamp": newest_ts, "matches": matches}


