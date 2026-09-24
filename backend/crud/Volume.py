from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func

from models.Project import Projectchapter
from models.Volume import Volume
from models.Chapter import Chapter


async def add_volume(
    db: AsyncSession,
    project_id: int,
    volume_index: int,
    name: str = "",
    chapter_start: int = 0,
    chapter_end: int = 0,
    summary: str = "",
    summary_generated_at: Optional[datetime] = None
) -> Volume:
    """新建一卷"""
    db_obj = Volume(
        project_id=project_id,
        volume_index=volume_index,
        name=name,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        summary=summary,
        summary_generated_at=summary_generated_at,
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_volumes_by_project(db: AsyncSession, project_id: int) -> List[Volume]:
    """按卷序号返回项目全部卷"""
    stmt = (
        select(Volume)
        .where(Volume.project_id == project_id)
        .order_by(Volume.volume_index)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_volume_by_id(db: AsyncSession, volume_id: int) -> Optional[Volume]:
    stmt = select(Volume).where(Volume.id == volume_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_volume(
        db: AsyncSession, volume_id: int, update_data: Dict[str, Any]
) -> Optional[Volume]:
    stmt = select(Volume).where(Volume.id == volume_id)
    result = await db.execute(stmt)
    db_obj = result.scalar_one_or_none()
    if not db_obj:
        return None

    # 特殊处理 summary 字段的更新
    if "summary" in update_data:
        new_summary_value = update_data.pop("summary")
        if new_summary_value != db_obj.summary:
            # summary 发生变化时，标记为已生成
            update_data["summary"] = new_summary_value
            db_obj.summary = new_summary_value
            db_obj.summary_generated_at = datetime.now()
        else:
            # 如果 summary 没有实际变化，恢复回 update_data 供其他逻辑使用
            update_data["summary"] = new_summary_value
    else:
        # 如果没有 explicit 更新 summary，但存在需要清除摘要的情况
        # 例如更新了 chapter_start 或 chapter_end 等可能影响摘要有效性的字段
        pass

    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)

    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def delete_volume(db: AsyncSession, volume_id: int) -> bool:
    """删除单卷（不提交，由调用方控制事务）"""
    result = await db.execute(delete(Volume).where(Volume.id == volume_id))
    return result.rowcount > 0


async def replace_volumes(
    db: AsyncSession, project_id: int, specs: List[Dict[str, Any]]
) -> List[Volume]:
    """按给定卷规格重建项目的整套卷边界（先清空后重建）。

    specs: [{volume_index, name, chapter_start, chapter_end}, ...]
    重建时保留旧卷摘要：按 volume_index 对齐，命中则沿用 summary/summary_generated_at，
    避免每次章节增删都把已有卷摘要清空重算。
    """
    old = {v.volume_index: v for v in await get_volumes_by_project(db, project_id)}
    await db.execute(delete(Volume).where(Volume.project_id == project_id))

    created: List[Volume] = []
    for spec in specs:
        vidx = spec.get("volume_index", 0)
        prev = old.get(vidx)
        db_obj = Volume(
            project_id=project_id,
            volume_index=vidx,
            name=spec.get("name", "") or "",
            chapter_start=spec.get("chapter_start", 0),
            chapter_end=spec.get("chapter_end", 0),
            summary=(prev.summary if prev else "") or "",
            summary_generated_at=(prev.summary_generated_at if prev else None),
        )
        db.add(db_obj)
        created.append(db_obj)
    await db.commit()
    for obj in created:
        await db.refresh(obj)
    return created


async def delete_volumes_by_project(db: AsyncSession, project_id: int) -> None:
    """删除项目全部卷（不提交，由调用方控制事务，与 delete_chapters_by_project 一致）"""
    await db.execute(delete(Volume).where(Volume.project_id == project_id))


async def delete_volumes_by_projects(db: AsyncSession, project_ids: List[int]) -> None:
    """批量删除多个项目的全部卷（不提交，由调用方统一控制事务）"""
    if not project_ids:
        return
    await db.execute(delete(Volume).where(Volume.project_id.in_(project_ids)))


async def get_volumes_by_project_with_stats(
    db: AsyncSession,
    project_id: int
) -> List[dict]:
    """
    获取项目下全部卷（附带实际章节数 + 总字数）

    Returns:
        [{volume_detail + chapter_count + total_word_count}, ...]
    """
    volumes = await get_volumes_by_project(db, project_id)
    results = []
    for v in volumes:
        # 空壳卷（[-1,-1]）无章节；正常卷按区间聚合实际行数与字数
        # （不用区间算术：区间尾可能超过当前实际章数，字数也只能真算）
        if v.chapter_start >= 0 and v.chapter_end >= v.chapter_start:
            row = (await db.execute(
                select(
                    func.count(Chapter.id),
                    func.coalesce(func.sum(func.length(Chapter.chapter_content)), 0),
                )
                .join(Projectchapter, Projectchapter.chapter_id == Chapter.id)
                .where(Projectchapter.project_id == project_id)
                .where(Chapter.chapter_index >= v.chapter_start)
                .where(Chapter.chapter_index <= v.chapter_end)
            )).one()
            count, words = int(row[0]), int(row[1])
        else:
            count, words = 0, 0

        result = {
            **v.__dict__,
            "chapter_count": count,
            "total_word_count": words,
        }
        results.append(result)

    return results


async def update_volumes_on_inserted_chapter(
    db: AsyncSession, project_id: int, inserted_index: int, target_volume_id: int
) -> Optional[int]:
    """插入章节后同步分卷边界（不提交）。新章必归 target_volume_id：
    非空卷 end+1 吸收、空壳物化为 [i, i]；插入点之后的其余非空卷整体右移。
    本系统不存在"未指定卷"的插入。返回吸收卷 id；target 非法返回 None。
    """
    volumes = (
        await db.execute(
            select(Volume)
            .where(Volume.project_id == project_id)
            .order_by(Volume.volume_index)
        )
    ).scalars().all()

    absorbed = _apply_chapter_insert(list(volumes), inserted_index, target_volume_id)
    await db.flush()
    return absorbed


async def update_volumes_on_deleted_chapter(db: AsyncSession, project_id: int, deleted_index: int) -> List[int]:
    """删除章节后同步分卷边界（不提交，由调用方控制事务）。

    与旧版差别：卷不再被删除——区间塌缩的卷置为 [-1,-1] 空壳保留，
    volume_index 不变。返回因本次删除变空的卷 id 列表。
    """
    volumes = (
        await db.execute(
            select(Volume)
            .where(Volume.project_id == project_id)
            .order_by(Volume.volume_index)
        )
    ).scalars().all()

    emptied = _apply_chapter_delete(list(volumes), deleted_index)
    await db.flush()
    return emptied

# ---------- 书末追加（改写：跳过空壳） ----------
async def _extend_volume_on_appended_chapter(
    db: AsyncSession, project_id: int, volume: Optional["Volume"]
) -> Optional[int]:
    """公共核心：往指定卷末尾插入新章（不提交），返回新章应落的 chapter_index。

    非空卷：插入点 = 卷尾 + 1。空壳 [-1,-1]：按相邻非空卷定位——前面最近非空卷
    的卷尾 + 1，否则后面最近非空卷的卷首，全壳则书末（无章节时为 0）。
    边界同步统一走 update_volumes_on_inserted_chapter（target 必填）。
    """
    if volume is None:
        return None

    if volume.chapter_end >= 0:
        insert_index = volume.chapter_end + 1
    else:
        volumes = (
            await db.execute(
                select(Volume)
                .where(Volume.project_id == project_id)
                .order_by(Volume.volume_index)
            )
        ).scalars().all()
        prev_end, next_start, seen_target = None, None, False
        for v in volumes:
            if v.chapter_end < 0:
                seen_target = seen_target or v.id == volume.id
                continue
            if seen_target:
                next_start = v.chapter_start
                break
            prev_end = v.chapter_end
        if prev_end is not None:
            insert_index = prev_end + 1
        elif next_start is not None:
            insert_index = next_start
        else:  # 全是空壳：新章落书末（count 为 0 时即落 0）
            count = (await db.execute(
                select(func.count(Projectchapter.chapter_id))
                .where(Projectchapter.project_id == project_id)
            )).scalar() or 0
            insert_index = count

    await update_volumes_on_inserted_chapter(db, project_id, insert_index, volume.id)
    return insert_index
async def extend_volume_on_appended_chapter_by_id(
    db: AsyncSession, project_id: int, volume_id: int
) -> Optional[int]:
    """新章插到指定卷（按卷 id）末尾（不提交）。返回新章应落的 chapter_index；
    卷不存在或不属于该项目时返回 None。空壳卷会被物化为 [i, i] 单章区间。
    """
    volume = (await db.execute(
        select(Volume).where(Volume.id == volume_id, Volume.project_id == project_id)
    )).scalar_one_or_none()
    return await _extend_volume_on_appended_chapter(db, project_id, volume)

async def extend_volume_on_appended_chapter_by_index(
    db: AsyncSession, project_id: int, volume_index: int
) -> Optional[int]:
    """同 by_id 版本，按卷序号定位目标卷。"""
    volume = (await db.execute(
        select(Volume).where(
            Volume.project_id == project_id, Volume.volume_index == volume_index
        )
    )).scalar_one_or_none()
    return await _extend_volume_on_appended_chapter(db, project_id, volume)

def _apply_chapter_delete(vols, d: int) -> List[int]:
    """在内存卷列表上模拟「删除位置 d 的章节」。返回因此变空的卷 id。

    - 完全在 d 之前的卷：不动
    - 包含 d 的卷：end -= 1，摘要陈旧
    - 完全在 d 之后的卷：整体左移（成员集合未变，摘要不清）
    - 区间塌缩的卷：置为 [-1,-1] 空卷壳保留（不删除、volume_index 不变）
    """
    emptied = []
    for v in vols:
        if v.chapter_end >= d:
            contained = v.chapter_start <= d
            v.chapter_end -= 1
            if v.chapter_start > d:
                v.chapter_start -= 1
            if contained:
                v.summary = ""
                v.summary_generated_at = datetime.now()
        if v.chapter_start >= 0 and v.chapter_start > v.chapter_end:
            v.chapter_start = -1
            v.chapter_end = -1
            v.summary = ""
            v.summary_generated_at = datetime.now()
            emptied.append(v.id)
    return emptied

async def get_volume_id_by_chapter_index(
    db: AsyncSession, project_id: int, chapter_index: int
) -> Optional[int]:
    """返回包含章节位置 chapter_index 的卷 id（按卷序取第一个），无则 None。
    insert_chapter 定位锚点卷用：新章与锚点章节同卷。"""
    return (
        await db.execute(
            select(Volume.id)
            .where(
                Volume.project_id == project_id,
                Volume.chapter_start <= chapter_index,
                Volume.chapter_end >= chapter_index,
            )
            .order_by(Volume.volume_index)
            .limit(1)
        )
    ).scalar_one_or_none()

def _find_absorbing_volume_id(vols, i: int) -> Optional[int]:
    """在内存卷列表上定位位置 i 的锚点卷（reorder 回放用）。

    优先：区间严格包含 i 的卷（i 处有章节，新章插在它前面 → 与它同卷）；
    退化：i 为某卷卷尾+1 的追加槽/书末槽（start <= i <= end+1）→ 该卷。
    均无 → i 落洞（数据异常），返回 None。
    """
    for v in vols:
        if v.chapter_end >= 0 and v.chapter_start <= i <= v.chapter_end:
            return v.id
    for v in vols:
        if v.chapter_end >= 0 and v.chapter_start <= i <= v.chapter_end + 1:
            return v.id
    return None

def _apply_chapter_insert(vols, i: int, target_id: int) -> Optional[int]:
    """在内存卷列表上模拟「在位置 i 插入章节，新章归 target_id 卷」。返回吸收卷 id。

    - 目标为非空卷（调用方保证 i ∈ [chapter_start, chapter_end + 1]）→ end + 1 吸收
    - 目标为空壳 [-1,-1] → 物化为 [i, i]
    - 其余非空卷在插入点之后（含正好顶在插入点且已有卷承接新章）→ 整体右移
    - 非目标空壳：旁路
    - 吸收卷摘要作废（清空 + 顶新 summary_generated_at；壳可能带塌缩残留旧摘要）
    """
    absorbed = None
    seen_nonempty = False
    for v in vols:
        if v.chapter_end < 0:
            if v.id == target_id:
                v.chapter_start, v.chapter_end = i, i
                v.summary = ""
                v.summary_generated_at = datetime.now()
                absorbed = v.id
                seen_nonempty = True  # 新章已被承接：后续顶在 i 的卷应右移
            continue
        if v.id == target_id:
            v.chapter_end += 1
            v.summary = ""
            v.summary_generated_at = datetime.now()
            absorbed = v.id
        elif i < v.chapter_start or (i == v.chapter_start and seen_nonempty):
            v.chapter_start += 1
            v.chapter_end += 1
        seen_nonempty = True
    return absorbed

# ---------- 重排分解 + 回放（新增） ----------

def _detect_single_move(old_order: List[int], new_order: List[int]) -> Optional[Tuple[int, int, int]]:
    """若 new_order 可由 old_order 抽出一章再插入得到，返回 (chapter_id, 旧位, 新位)。

    多个候选都成立时（如相邻两章互换），取 new_order 中最靠前的候选；
    需要精确定夺时由前端显式传 moved_chapter_id。
    """
    pos_old = {cid: k for k, cid in enumerate(old_order)}
    for j, cid in enumerate(new_order):
        k = pos_old[cid]
        if k == j:
            continue
        if old_order[:k] + old_order[k + 1:] == new_order[:j] + new_order[j + 1:]:
            return cid, k, j
    return None


def _compute_reorder_moves(
    old_index_of: Dict[int, int],
    ordered_ids: List[int],
    moved_chapter_id: Optional[int],
) -> List[Tuple[int, int]]:
    """把一次终态重排分解为「先删后插」序列 [(删除位置, 插入位置), ...]。

    - 显式传 moved_chapter_id → 单步移动，卷语义与单章拖拽完全一致
    - 否则自动识别单章移动；识别不出（多章同时变化）→ 按终态从左到右
      选择排序式分解逐章回放，每一步都满足卷不变式
    """
    old_order = sorted(ordered_ids, key=lambda cid: old_index_of[cid])
    if old_order == ordered_ids:
        return []

    if moved_chapter_id is not None and moved_chapter_id in old_index_of:
        a = old_index_of[moved_chapter_id]
        b = ordered_ids.index(moved_chapter_id)
        if a != b:
            return [(a, b)]

    hit = _detect_single_move(old_order, ordered_ids)
    if hit:
        return [(hit[1], hit[2])]

    moves: List[Tuple[int, int]] = []
    order = old_order[:]
    for target, cid in enumerate(ordered_ids):
        if order[target] == cid:
            continue
        cur = order.index(cid)
        order.pop(cur)
        order.insert(target, cid)
        moves.append((cur, target))
    return moves


async def sync_volumes_on_reorder(
    db: AsyncSession,
    project_id: int,
    ordered_ids: List[int],
    old_index_of: Dict[int, int],
    moved_chapter_id: Optional[int] = None,
) -> None:
    """终态重排的卷边界同步（不提交）。

    把重排分解为逐章「先删后插」，在内存卷列表上依次回放后一次落库；
    每步插入都显式定位锚点卷，不存在"未指定卷"的插入。
    跨卷移动使源卷唯一章节迁出 → 源卷塌缩为 [-1,-1] 空壳保留。
    """
    moves = _compute_reorder_moves(old_index_of, ordered_ids, moved_chapter_id)
    if not moves:
        return

    volumes = (
        await db.execute(
            select(Volume)
            .where(Volume.project_id == project_id)
            .order_by(Volume.volume_index)
        )
    ).scalars().all()
    if not volumes:
        return

    for del_pos, ins_pos in moves:
        _apply_chapter_delete(volumes, del_pos)
        target_id = _find_absorbing_volume_id(volumes, ins_pos)
        if target_id is not None:  # 落洞：跳过，与旧版"无人吸收"一致，不放大脏数据
            _apply_chapter_insert(volumes, ins_pos, target_id)
    await db.flush()

async def update_volumes_on_deleted_chapter_range(
    db: AsyncSession, project_id: int, start: int, end: int
) -> List[int]:
    """连续删除章节区间 [start, end]（0-based 闭区间）后的卷边界同步（不提交）。

    等价于对位置 start 连续执行 (end - start + 1) 次单章删除回放：
    - 目标区间所在卷逐次收缩，最终塌缩为 [-1,-1] 空壳（是否删行由调用方决定）
    - 其后所有非空卷整体左移区间长度，成员集合不变、摘要不清
    - 已有的 [-1,-1] 空壳完全旁路（-1 不会被 >= start 命中）
    """
    volumes = (
        await db.execute(
            select(Volume)
            .where(Volume.project_id == project_id)
            .order_by(Volume.volume_index)
        )
    ).scalars().all()

    emptied: List[int] = []
    for _ in range(end - start + 1):
        emptied.extend(_apply_chapter_delete(volumes, start))
    await db.flush()
    return emptied

