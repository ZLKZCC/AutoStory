import asyncio
from config.db_conf import get_db
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from utils.common import rm_scripts, rm_characters
from utils.knowledge_import import _parse_file
from schemas.Project import ProjectCreate, ProjectDetail
from fastapi import APIRouter, Depends, Query, Body, HTTPException, Path, File, UploadFile
from crud.CHROMA_chapters import delete_chapter_segments_by_project, delete_chapter_segments_by_projects
from crud import Project, Chapter, Character, ChatRecord, Summary, AudioBookScript, CharacterStage, Volume


router = APIRouter(prefix="/autostory/project",tags=["project"])

@router.get("/projects")
async def get_projects(page:int = Query(...,gt=0),pagesize:int = Query(10,gt=0),db:AsyncSession = Depends(get_db)):
    offset = (page - 1) * pagesize
    projects, total = await Project.get_projects_paginated(db,offset,pagesize)
    has_more = (offset+len(projects)) < total
    project_ids = [p.id for p in projects]
    projects = [ProjectDetail.model_validate(p) for p in projects]
    chapter_counts = await Chapter.get_chapter_counts(db,project_ids)
    character_counts = await Character.get_character_counts(db,project_ids)
    return {
        "data":{
            "List": projects,
            "Chaptercount": chapter_counts,
            "Charactercount": character_counts,
            "More": has_more
        }
    }

@router.post("/create_project")
async def create_projects(project:ProjectCreate,db:AsyncSession = Depends(get_db)):
    project = await Project.create_project_by_model(db,project)
    return {
        "data":{
            "Project": project,
            "Resp": "创建成功"
        }
    }

@router.post("/parse_files")
async def parse_files(files:List[UploadFile] = File(...)):
    """
    解析上传附件为纯文本（悬浮助理附件解析用），复用素材导入的解析逻辑
    """
    loop = asyncio.get_event_loop()
    texts = []
    for f in files:
        raw = await f.read()
        text = await loop.run_in_executor(None, _parse_file, f.filename, raw)
        texts.append(text)
    return {
        "data":{
            "Content": "\n\n".join(t for t in texts if t.strip())
        }
    }

@router.get("/{project_id}/concept")
async def get_project_concept(project_id:int = Path(...),db:AsyncSession = Depends(get_db)):
    project = await Project.get_project_by_id(db,project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "data":{
            "Concept": project.concept
        }
    }

@router.put("/{project_id}/concept")
async def update_project_concept(project_id:int = Path(...),concept:Dict[str,Any] = Body(...),db:AsyncSession = Depends(get_db)):
    updated_project = await Project.update_project(db,project_id,{"concept": concept})
    if not updated_project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "data":{
            "Concept": updated_project.concept,
            "Resp": "更新成功"
        }
    }

@router.get("/{project_id}/worldline")
async def get_project_worldline(project_id:int = Path(...),db:AsyncSession = Depends(get_db)):
    project = await Project.get_project_by_id(db,project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "data":{
            "Worldline": project.worldline
        }
    }

@router.put("/{project_id}/worldline")
async def update_project_worldline(project_id:int = Path(...),worldline:Dict[str,Any] = Body(...),db:AsyncSession = Depends(get_db)):
    updated_project = await Project.update_project(db,project_id,{"worldline": worldline})
    if not updated_project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "data":{
            "Worldline": updated_project.worldline,
            "Resp": "更新成功"
        }
    }

@router.get("/{project_id}/volumes")
async def get_project_volumes(project_id:int = Path(...),db:AsyncSession = Depends(get_db)):
    """分卷清单（前端大纲界面卷可视化用）：卷序、卷名、覆盖章节区间(0-based)、卷摘要"""
    project = await Project.get_project_by_id(db,project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    vols = await Volume.get_volumes_by_project(db, project_id)
    return {
        "data":{
            "List": [
                {
                    "id": v.id, "volume_index": v.volume_index, "name": v.name or "",
                    "chapter_start": v.chapter_start, "chapter_end": v.chapter_end,
                    "summary": v.summary or "",
                } for v in vols
            ]
        }
    }

@router.get("/{project_id}")
async def get_project(project_id:int = Path(...),db:AsyncSession = Depends(get_db)):
    project = await Project.get_project_by_id(db,project_id)
    project = ProjectDetail.model_validate(project)
    return {
        "data":{
            "Project": project,
        }
    }

@router.put("/{project_id}")
async def update_project(project_id: int = Path(...),update_data: Dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    if not update_data:
        raise HTTPException(status_code=400, detail="请求体不能为空")
    updated_project = await Project.update_project(db,project_id,update_data)
    if not updated_project:
        raise HTTPException(status_code=404, detail="项目不存在")

    return updated_project

@router.delete("/projects")
async def delete_projects(project_ids:List[int] = Query(...),db:AsyncSession = Depends(get_db)):
    chapterids = await Chapter.get_chapterid_by_projects(db,project_ids)
    characterids = await Character.get_characterid_by_projects(db,project_ids)
    characterstageids= await Character.get_stage_ids_by_character_ids(db,characterids)


    await AudioBookScript.delete_scripts_by_projects(db,project_ids)
    await Chapter.delete_chapters_by_projects(db,project_ids)
    await Volume.delete_volumes_by_projects(db,project_ids)
    await CharacterStage.delete_stages_by_characters(db,characterids)
    await Character.delete_characters_by_projects(db,project_ids)
    await ChatRecord.delete_chatrecords_by_projects(db,project_ids)
    await Summary.delete_summary_by_projects(db,project_ids)
    await Project.delete_project_knowledge_by_projectids(db,project_ids)
    await Project.delete_projects(db,project_ids)
    await db.commit()
    await delete_chapter_segments_by_projects([str(pid) for pid in project_ids])

    await rm_scripts(chapterids)
    await rm_characters(characterstageids)

    return {
        "data":{
            "Resp":"删除成功"
        }
    }

@router.delete("/{project_id}")
async def delete_project(project_id:int = Path(...),db:AsyncSession = Depends(get_db)):
    chapterids = await Chapter.get_chapterid_by_project(db, project_id)
    characterids = await Character.get_characterid_by_project(db, project_id)
    characterstageids= await Character.get_stage_ids_by_character_ids(db,characterids)

    await AudioBookScript.delete_scripts_by_project(db, project_id)
    await Chapter.delete_chapters_by_project(db, project_id)
    await Volume.delete_volumes_by_project(db, project_id)
    await CharacterStage.delete_stages_by_characters(db,characterids)
    await Character.delete_characters_by_project(db, project_id)
    await ChatRecord.delete_chatrecords_by_project(db, project_id)
    await Summary.delete_summary_by_project(db, project_id)
    await Project.delete_project_knowledge_by_projectid(db, project_id)
    await Project.delete_project(db, project_id)
    await db.commit()
    await delete_chapter_segments_by_project(str(project_id))

    await rm_scripts(chapterids)
    await rm_characters(characterstageids)

    return {
        "data":{
            "Resp":"删除成功"
        }
    }

@router.get("/klproject/{project_id}")
async def get_project_knowledges(
        project_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    """获取项目引用的素材列表（knowledge 字段即素材内容文本）"""
    project = await Project.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    knowledges = await Project.get_project_knowledges(db, project.id)

    return {
        "data": {
            "List": [{"id": k.id, "content": k.knowledge} for k in knowledges],
            "Total": len(knowledges)
        }
    }


@router.post("/klproject/{project_id}")
async def add_project_knowledge(
        project_id: int = Path(...),
        content: str = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """添加单条项目素材引用（body 传素材内容文本）"""
    project = await Project.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="素材内容不能为空")

    db_obj = await Project.add_project_knowledge(db, project.id, content)

    return {"data": {"Knowledge": {"id": db_obj.id, "content": db_obj.knowledge}, "Resp": "素材引用已添加"}}


@router.delete("/klproject/{project_id}")
async def remove_project_knowledge(
        project_id: int = Path(...),
        content: str = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """删除单条项目素材引用（body 传素材内容文本，按内容精确匹配）"""
    project = await Project.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    deleted = await Project.delete_project_knowledge_by_content(db, project.id, content)
    if not deleted:
        raise HTTPException(status_code=404, detail="素材引用不存在")

    return {"data": {"Resp": "素材引用已删除"}}