from typing import Dict, Any, List, Optional
from config.db_conf import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from crud import Chapter, Project, Character, CharacterStage, AudioBookScript, Volume
from crud.CHROMA_chapters import delete_chapter_segments_by_chapter, rebuild_chapter_segments
from schemas.Chapter import Chaptershot, ChapterCreate, ChapterDetail
from fastapi import APIRouter, Depends, Query, Path, HTTPException, Body
from utils.common import rm_scripts

router = APIRouter(prefix="/autostory/chapter",tags=["chapter"])

@router.get("/chapters")
async def get_chapters(project_id:int = Query(...), page:int = Query(...,gt=0),pagesize:int = Query(10,gt=0),db:AsyncSession = Depends(get_db)):
    offset = (page - 1) * pagesize
    chapters, total = await Chapter.get_chapters_paginated(db,project_id,offset,pagesize)
    has_more = (offset+len(chapters)) < total
    chapters = [Chaptershot.model_validate(chapter) for chapter in chapters]
    return {
        "data":{
            "List": chapters,
            "Total": total,
            "More": has_more
        }
    }

@router.post("/add_chapter")
async def add_chapter(
    volume_id: int = Query(..., description="目标分卷 ID（新章插入该卷末尾）"),
    project_id: int = Query(..., description="项目 ID"),
    chapter: ChapterCreate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """在指定分卷末尾新增一章：该卷后面还有章节/分卷时，序号整体后移一位保持对齐"""
    insert_index = await Volume.extend_volume_on_appended_chapter_by_id(db, project_id, volume_id)
    if insert_index is None:
        raise HTTPException(status_code=404, detail="目标分卷不存在、不属于该项目或为空壳卷")

    # 数据防线：正常数据下卷尾槽位必有章节，卷尾+1 不会越过章节总数；越过说明卷边界异常
    _, count = await Chapter.get_chapters_paginated(db, project_id)
    if insert_index > count:
        raise HTTPException(status_code=400, detail="目标分卷边界异常：卷尾超出章节总数")

    # 插入点起的章节与角色阶段整体右移（目标卷是书末最后一卷时这里是空操作）
    await Chapter.shift_chapter_indexes(db, project_id, insert_index, 1)
    character_ids = await Character.get_characterid_by_project(db, project_id)
    await CharacterStage.shift_stage_chapter_indexes(db, character_ids, insert_index, 1)

    chapter.chapter_index = insert_index
    new_chapter = await Chapter.add_chapter_by_model(db, chapter)
    await Project.add_project_chapter(db, project_id, new_chapter.id)
    await db.commit()
    # 章节向量重建（正文非空才建索引；SQL 先落，向量后建，失败可重建）
    if new_chapter.chapter_content and new_chapter.chapter_content.strip():
        await rebuild_chapter_segments(
            str(project_id), str(new_chapter.id), new_chapter.chapter_content)

    return {"data": {"Chapter": new_chapter, "Resp": "创建成功"}}

@router.post("/insert_chapter")
async def insert_chapter(
    project_id: int = Query(..., description="项目 ID"),
    target_chapter_id: int = Query(..., description="目标章节 ID（在其前/后插入）"),
    position: str = Query("after", description="插入位置：before / after"),
    chapter: ChapterCreate = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """在指定章节前/后插入一章：同项目后续章节与角色阶段序号整体后移，保持对齐；
    新章归属锚点章节所在的分卷"""
    if position not in ("before", "after"):
        raise HTTPException(status_code=400, detail="position 只能是 before 或 after")

    target = await Chapter.get_chapter_by_id(db, target_chapter_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标章节不存在")

    # 锚点章节必须属于该项目（卷按 project_id + chapter_index 定位，跨项目会错位）
    if await Project.get_project_by_chapterid(db, target_chapter_id) != project_id:
        raise HTTPException(status_code=400, detail="目标章节不属于该项目")

    insert_index = target.chapter_index if position == "before" else target.chapter_index + 1

    # 锚点卷定位：新章与锚点章节同卷，不存在"未指定卷"的插入
    target_volume_id = await Volume.get_volume_id_by_chapter_index(db, project_id, target.chapter_index)
    if target_volume_id is None:
        raise HTTPException(status_code=404, detail="目标章节未落入任何分卷，无法定位插入卷")

    await Chapter.shift_chapter_indexes(db, project_id, insert_index, 1)
    character_ids = await Character.get_characterid_by_project(db, project_id)
    await CharacterStage.shift_stage_chapter_indexes(db, character_ids, insert_index, 1)

    chapter.chapter_index = insert_index
    new_chapter = await Chapter.add_chapter_by_model(db, chapter)
    await Project.add_project_chapter(db, project_id, new_chapter.id)
    await Volume.update_volumes_on_inserted_chapter(db, project_id, insert_index, target_volume_id)
    await db.commit()

    # 章节向量重建（正文非空才建索引）
    if new_chapter.chapter_content and new_chapter.chapter_content.strip():
        await rebuild_chapter_segments(
            str(project_id), str(new_chapter.id), new_chapter.chapter_content)

    return {
        "data": {
            "Chapter": new_chapter,
            "Resp": "插入成功"
        }
    }

@router.put("/reorder")
async def reorder_chapters(
    project_id: int = Query(..., description="项目ID"),
    chapter_ids: List[int] = Body(..., embed=True, description="按新顺序排列的章节ID列表（终态提交，幂等）"),
    moved_chapter_id: Optional[int] = Body(None, description="本次拖动的章节ID（可选；卷级拖拽建议传，精确定夺边界归属）"),
    db: AsyncSession = Depends(get_db),
):
    """拖拽排序终态提交：重排章节序号 + 角色阶段映射同步 + 卷边界回放同步。

    卷语义：章节必落于卷内；跨卷移动使源卷唯一章节迁出时，源卷塌缩为
    [-1,-1] 空壳保留（不删除、volume_index 不变）；单卷单章移动无任何变化。
    无卷项目只做前两项。
    """
    current_ids = await Chapter.get_chapterid_by_project(db, project_id)
    if len(chapter_ids) != len(current_ids) or set(chapter_ids) != set(current_ids):
        raise HTTPException(status_code=400, detail="章节ID列表与项目实际章节不一致")

    if len(chapter_ids) <= 1:
        # 唯一章节（唯一卷唯一章）：移动无意义
        return {"data": {"Resp": "顺序已更新"}}

    # 轻量两列映射即可（旧版全量加载章节 ORM 含正文，白拖慢 reorder）
    old_index_of = await Chapter.get_chapter_index_map_by_project(db, project_id)

    try:
        # 1) 章节序号：终态 CASE 重排（幂等）
        await Chapter.reorder_chapter_indexes(db, chapter_ids)

        # 2) 角色阶段：旧→新映射同步（章节 0-based，阶段 1-based，两端 +1）
        character_ids = await Character.get_characterid_by_project(db, project_id)
        await CharacterStage.remap_stage_chapter_indexes(
            db, character_ids,
            {old_index_of[cid] + 1: new_idx + 1
             for new_idx, cid in enumerate(chapter_ids)
             if old_index_of[cid] != new_idx},
        )

        # 3) 卷边界：分解为先删后插并回放（无卷时内部直接跳过）
        await Volume.sync_volumes_on_reorder(
            db, project_id, chapter_ids, old_index_of, moved_chapter_id
        )

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {"data": {"Resp": "顺序已更新"}}

@router.get("/{chapter_id}")
async def get_chapter(chapter_id:int = Path(...),db:AsyncSession = Depends(get_db)):
    chapter = await Chapter.get_chapter_by_id(db,chapter_id)
    return {
        "data":{
            "Chapter": ChapterDetail.model_validate(chapter),
        }
    }

@router.put("/{chapter_id}")
async def update_chapter(chapter_id: int = Path(...),update_data: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    if not update_data:
        raise HTTPException(status_code=400, detail="请求体不能为空")
    old = await Chapter.get_chapter_by_id(db, chapter_id)
    updated_chapter = await Chapter.update_chapter(db,chapter_id,update_data)
    if not updated_chapter:
        raise HTTPException(status_code=404, detail="项目不存在")
    await db.commit()
    # 正文真变才重建向量（改标题等其它字段不触发，避免整章重嵌入）
    if "chapter_content" in update_data and old and (old.chapter_content or "") != (update_data["chapter_content"] or ""):
        project_id = await Project.get_project_by_chapterid(db, chapter_id)
        await rebuild_chapter_segments(str(project_id), str(chapter_id), update_data["chapter_content"] or "")

    return updated_chapter

@router.delete("/{chapter_id}")
async def delete_chapter(chapter_id:int = Path(...),db:AsyncSession = Depends(get_db)):
    project_id = await Project.get_project_by_chapterid(db,chapter_id)
    chapter_index = await Chapter.get_chapter_index_by_id(db,chapter_id)
    character_ids = await Character.get_characterid_by_project(db,project_id)
    await CharacterStage.reset_chapter_index_by_characters(db,character_ids,chapter_index)
    await CharacterStage.shift_stage_chapter_indexes(db,character_ids,chapter_index,-1)
    await AudioBookScript.delete_scripts_by_chapter(db,chapter_id)
    await Volume.update_volumes_on_deleted_chapter(db,project_id,chapter_index)
    await Chapter.delete_chapter(db,chapter_id)
    # 章节表：被删章之后的所有章节序号前移 -1
    await Chapter.shift_chapter_indexes(db,project_id,chapter_index,-1)
    await Project.remove_project_chapter(db,chapter_id)
    await db.commit()
    await delete_chapter_segments_by_chapter(str(chapter_id))
    await rm_scripts([chapter_id])

    return {
        "data":{
            "Resp":"删除成功"
        }
    }






