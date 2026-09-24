"""卷 (Volume) CRUD 路由"""
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query, Path, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession

from config.db_conf import get_db
from crud import Volume, Project, Chapter, Character, CharacterStage, AudioBookScript
from crud.CHROMA_chapters import delete_chapter_segments_by_chapter
from schemas.volume import VolumeCreate, VolumeDetail, VolumeUpdate
from utils.common import rm_scripts

router = APIRouter(prefix="/autostory/volume", tags=["volume"])


@router.post("")
async def create_volume(
    volume: VolumeCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    创建新卷（手动指定章节范围）
    
    校验：
    1. 项目存在
    2. 与现有卷无重叠
    """
    # 1. 检查项目存在
    project = await Project.get_project_by_id(db, volume.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 2. 拉现有卷：重叠校验 + volume_index 分配都要用
    volumes = await Volume.get_volumes_by_project(db, volume.project_id)

    # 空壳卷（[-1,-1]）没有实际章节，永不真重叠：新建空壳直接放行，
    # 已有空壳也不参与重叠校验（否则空壳区间相等会被误判 400）
    new_is_shell = volume.chapter_start < 0 or volume.chapter_end < volume.chapter_start
    if not new_is_shell:
        for v in volumes:
            if v.chapter_start < 0 or v.chapter_end < v.chapter_start:
                continue
            if not (volume.chapter_end < v.chapter_start or volume.chapter_start > v.chapter_end):
                raise HTTPException(
                    status_code=400,
                    detail=f"卷范围 [{volume.chapter_start}:{volume.chapter_end}] 与卷'{v.name}'重叠"
                )

    # 4. 创建卷
    max_index = max((v.volume_index for v in volumes), default=-1) + 1

    volume = await Volume.add_volume(
        db=db,
        project_id=volume.project_id,
        volume_index=max_index,
        name=volume.name,
        chapter_start=volume.chapter_start,
        chapter_end=volume.chapter_end,
        summary="",
        summary_generated_at=None
    )

    # 返回体带统计：空壳必 0/0；带区间时按卷内实际章节算，
    # 前端目录树/卷卡不必等 include_stats 刷新
    if new_is_shell:
        chapter_count, total_word_count = 0, 0
    else:
        briefs = await Chapter.get_chapter_briefs_by_index_range(
            db, volume.project_id, volume.chapter_start, volume.chapter_end
        )
        chapter_count = len(briefs)
        total_word_count = sum(b["word_count"] for b in briefs)
    return {"data": {
        **VolumeDetail.model_validate(volume).model_dump(),
        "chapter_count": chapter_count,
        "total_word_count": total_word_count,
    }}


@router.get("/project/{project_id}")
async def list_volumes(
    project_id: int = Path(..., description="项目 ID"),
    include_stats: bool = Query(False, description="是否包含章节统计信息"),
    db: AsyncSession = Depends(get_db)
):
    """获取项目下全部卷（可选包含章节数 + 字数统计）"""
    if include_stats:
        volumes_stats = await Volume.get_volumes_by_project_with_stats(db, project_id)
        return {"data": volumes_stats}
    
    volumes = await Volume.get_volumes_by_project(db, project_id)
    return {"data": [VolumeDetail.model_validate(v) for v in volumes]}


@router.get("/{volume_id}")
async def get_volume_detail(
    volume_id: int = Path(..., description="卷 ID"),
    db: AsyncSession = Depends(get_db)
):
    """获取单个卷详情"""
    volume = await Volume.get_volume_by_id(db, volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="卷不存在")
    
    return {"data": VolumeDetail.model_validate(volume)}


@router.put("/{volume_id}")
async def update_volume(
    volume_id: int,
    payload: VolumeUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新卷信息（名称、摘要）"""
    volume = await Volume.get_volume_by_id(db, volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="卷不存在")
    
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    result = await Volume.update_volume(db, volume_id, update_data)
    
    return {"data": VolumeDetail.model_validate(result)}


@router.delete("/{volume_id}")
async def delete_volume(
    volume_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除卷：卷内章节一并删除；角色阶段、卷边界、项目映射同步调整。

    口径全 0-based：卷区间 [chapter_start, chapter_end] 与 Chapter.chapter_index 同口径。
    空卷壳（[-1,-1]）没有章节，仅删行。
    """
    volume = await Volume.get_volume_by_id(db, volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="卷不存在")

    project_id = volume.project_id
    deleted_chapter_ids = []

    try:
        # 非空卷才需要级联；空壳直接删行
        if volume.chapter_start >= 0 and volume.chapter_end >= volume.chapter_start:
            s, e = volume.chapter_start, volume.chapter_end
            n = e - s + 1
            deleted_chapter_ids = await Chapter.get_chapter_ids_by_index_range(db, project_id, s, e)

            # 1) 角色阶段：绑定在 [s, e] 上的置 -1（0-based 直通），其后（>= e+1）整体 -n
            character_ids = await Character.get_characterid_by_project(db, project_id)
            if character_ids:
                await CharacterStage.reset_chapter_indexes_by_characters(
                    db, character_ids, list(range(s, e + 1)))
                await CharacterStage.shift_stage_chapter_indexes(db, character_ids, e + 1, -n)

            # 2) 音频脚本（DB 内）
            for cid in deleted_chapter_ids:
                await AudioBookScript.delete_scripts_by_chapter(db, cid)

            # 3) 卷边界：对位置 s 连续回放 n 次单章删除（目标卷塌缩为 [-1,-1]，后卷整体左移 n）
            await Volume.update_volumes_on_deleted_chapter_range(db, project_id, s, e)

            # 4) 章节行与索引：删行 → 后续章节整体 -n → 移除项目映射
            await Chapter.delete_chapters_by_ids(db, deleted_chapter_ids)
            await Chapter.shift_chapter_indexes(db, project_id, e + 1, -n)
            await Project.remove_project_chapters(db, deleted_chapter_ids)

        # 5) 删卷行
        await Volume.delete_volume(db, volume_id)

        # 6) 压实卷序号（删行后留洞会影响 replace_volumes 按 volume_index 对齐摘要）；
        #    若前端依赖卷序号绝对稳定可去掉这段
        volumes = await Volume.get_volumes_by_project(db, project_id)
        for i, v in enumerate(volumes):
            v.volume_index = i

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # 7) 外部存储清理：commit 之后做，失败只损失索引可重建，不回滚 DB
    for cid in deleted_chapter_ids:
        await delete_chapter_segments_by_chapter(str(cid))
    if deleted_chapter_ids:
        await rm_scripts(deleted_chapter_ids)

    return {
        "data": {
            "Resp": "删除成功",
            "deleted_chapter_count": len(deleted_chapter_ids),
        }
    }


# ── 卷内章节管理 ──────────────────────────────────────────────

@router.get("/{volume_id}/chapters")
async def list_volume_chapters(
    volume_id: int = Path(..., description="卷 ID"),
    page: int = Query(1, gt=0, description="页码"),
    pagesize: int = Query(50, gt=0, description="每页数量"),
    db: AsyncSession = Depends(get_db)
):
    """
    获取某卷内的章节列表（分页）：列表字段（id / 索引 / 标题 / 字数），不含正文。
    字段名对齐前端 ChapterInfo（title / word_count）。
    """
    volume = await Volume.get_volume_by_id(db, volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="卷不存在")

    # 空壳卷（[-1,-1]）没有章节
    if volume.chapter_start < 0 or volume.chapter_end < volume.chapter_start:
        return {"data": {"List": [], "Total": 0, "More": False}}

    # 按卷区间直查（0-based 闭区间）。旧实现先按项目分页再过滤，
    # 跨卷翻页会丢章且 More/Total 口径全错
    briefs = await Chapter.get_chapter_briefs_by_index_range(
        db, volume.project_id, volume.chapter_start, volume.chapter_end
    )
    offset = (page - 1) * pagesize
    page_items = briefs[offset:offset + pagesize]
    return {
        "data": {
            "List": page_items,
            "Total": len(briefs),
            "More": offset + pagesize < len(briefs),
        }
    }
