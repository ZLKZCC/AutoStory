from crud import Material, Userpreference
from typing import Dict, Any, List, Optional
from config.db_conf import get_db
from schemas.Material import MaterialDetail
from crud.CHROMA_knowledges import (
    list_knowledge_documents,
    get_knowledge_segments,
    search_knowledge_segments,
    delete_knowledge_segments_by_material,
    delete_knowledge_segments_by_knowledge_name,
    get_knowledge_stats
)
from utils.knowledge_import import (
    create_import_task,
    get_import_progress
)
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, Query, Path, Body, HTTPException, File, UploadFile, Form

router = APIRouter(prefix="/autostory/material", tags=["material"])


def _material_info(db_obj, stat: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """
    素材库 ORM 对象转前端视图（时间戳转 unix 秒，附带向量统计）
    """
    stat = stat or {}
    return {
        "id": db_obj.id,
        "name": db_obj.material_name,
        "description": db_obj.description,
        "created_at": int(db_obj.create_time.timestamp()),
        "updated_at": int(db_obj.update_time.timestamp()),
        "knowledge_count": stat.get("knowledge_count", 0),
        "chunk_count": stat.get("chunk_count", 0)
    }


@router.get("/materials")
async def get_materials(
        page: int = Query(1, gt=0),
        pagesize: int = Query(1000, gt=0),
        search: str = Query(""),
        sort: str = Query("updated"),
        db: AsyncSession = Depends(get_db)
):
    """获取素材库列表（名称模糊搜索 + 排序 + 向量统计）"""
    offset = (page - 1) * pagesize
    materials, total = await Material.get_materials_paginated(db, offset, pagesize, search=search, sort=sort)

    # 一次拉全库向量统计，避免逐库查询
    stats = await get_knowledge_stats()

    return {
        "data": {
            "List": [_material_info(m, stats.get(m.id)) for m in materials],
            "Total": total
        }
    }


@router.post("/create_material")
async def create_material(
        material_name: str = Body(...),
        description: str = Body(""),
        db: AsyncSession = Depends(get_db)
):
    """创建素材库"""
    db_obj = await Material.add_material(db, material_name=material_name, description=description)

    return {"data": {"Material": _material_info(db_obj), "Resp": "创建成功"}}


@router.post("/batch_delete_materials")
async def batch_delete_materials(
        material_ids: List[int] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """批量删除素材库（级联删除向量库内全部片段）"""
    if not material_ids:
        return {"data": {"Resp": "删除条目不能为空"}}

    count = await Material.batch_delete_materials(db, material_ids)

    # 级联清理各素材库的向量数据
    for material_id in material_ids:
        await delete_knowledge_segments_by_material(material_id)

    return {"data": {"Resp": f"已删除 {count} 个素材库"}}


@router.post("/search")
async def search_material_knowledge_global(
        search_data: Dict[str, Any] = Body(...)
):
    """全局语义搜索：跨全部素材库的多 query 匹配"""
    query = search_data.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")

    result = await search_knowledge_segments(
        query,
        top_k=search_data.get("top_k", 20),
        page=search_data.get("page", 1),
        page_size=search_data.get("page_size", 20)
    )

    return {"data": result}


@router.get("/import-progress/{task_id}")
async def get_import_progress_api(
        task_id: str = Path(...)
):
    """查询导入任务进度（前端轮询）"""
    progress = get_import_progress(task_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")

    return {"data": {"Progress": progress}}


@router.get("/{material_id}")
async def get_material(
        material_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    """获取素材库详情（含向量统计）"""
    db_obj = await Material.get_material_by_id(db, material_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="素材库不存在")

    stats = await get_knowledge_stats()

    return {"data": {"Material": _material_info(db_obj, stats.get(material_id))}}


@router.put("/{material_id}")
async def update_material(
        material_id: int = Path(...),
        update_data: Dict[str, Any] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """更新素材库信息"""
    if not update_data:
        raise HTTPException(status_code=400, detail="请求体不能为空")

    db_obj = await Material.update_material(db, material_id, update_data)
    if not db_obj:
        raise HTTPException(status_code=404, detail="素材库不存在")

    return {"data": {"Material": MaterialDetail.model_validate(db_obj), "Resp": "更新成功"}}


@router.delete("/delete_material/{material_id}")
async def delete_material(
        material_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    """删除单个素材库（级联删除向量库内全部片段）"""
    db_obj = await Material.get_material_by_id(db, material_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="素材库不存在")

    await Material.delete_material(db, material_id)
    await db.commit()

    # 级联清理该素材库的向量数据
    await delete_knowledge_segments_by_material(material_id)

    return {"data": {"Resp": "删除成功"}}


@router.get("/{material_id}/knowledges")
async def list_material_knowledges(
        material_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    """获取素材库下的素材列表（按素材名聚合切片数与字数）"""
    db_obj = await Material.get_material_by_id(db, material_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="素材库不存在")

    documents = await list_knowledge_documents(material_id)

    return {"data": {"List": documents, "Total": len(documents)}}


@router.delete("/{material_id}/knowledges")
async def delete_material_knowledge(
        material_id: int = Path(...),
        knowledge_name: str = Query(...),
        db: AsyncSession = Depends(get_db)
):
    """删除指定素材（素材库id + 素材名）的全部切片"""
    db_obj = await Material.get_material_by_id(db, material_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="素材库不存在")

    await delete_knowledge_segments_by_knowledge_name(material_id, knowledge_name)

    return {"data": {"Resp": "素材已删除"}}


@router.get("/{material_id}/chunks")
async def list_material_chunks(
        material_id: int = Path(...),
        knowledge_name: str = Query(...),
        page: int = Query(1, gt=0),
        pagesize: int = Query(1000, gt=0),
        db: AsyncSession = Depends(get_db)
):
    """获取指定素材的切片列表（精确查找，分页）"""
    db_obj = await Material.get_material_by_id(db, material_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="素材库不存在")

    result = await get_knowledge_segments(
        material_id=material_id,
        knowledge_name=knowledge_name,
        page=page,
        page_size=pagesize
    )

    return {"data": result}


@router.post("/{material_id}/search")
async def search_material_knowledge(
        material_id: int = Path(...),
        search_data: Dict[str, Any] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """素材库内语义搜索：多 query 匹配合并"""
    db_obj = await Material.get_material_by_id(db, material_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="素材库不存在")

    query = search_data.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")

    result = await search_knowledge_segments(
        query,
        material_id=material_id,
        top_k=search_data.get("top_k", 20),
        page=search_data.get("page", 1),
        page_size=search_data.get("page_size", 20)
    )

    return {"data": result}


@router.post("/{material_id}/import")
async def import_material_files(
        material_id: int = Path(...),
        files: List[UploadFile] = File(...),
        knowledge_names: Optional[List[str]] = Form(None),
        db: AsyncSession = Depends(get_db)
):
    """导入素材文件（后台任务：解析 → 切片 → 向量化入库，进度轮询）"""
    db_obj = await Material.get_material_by_id(db, material_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="素材库不存在")

    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")

    # 组装 (素材名, 文件名, 文件字节)：素材名优先用前端传入，缺省用文件名去扩展名
    file_items = []
    for i, f in enumerate(files):
        knowledge_name = (
            knowledge_names[i]
            if knowledge_names and i < len(knowledge_names) and knowledge_names[i]
            else f.filename.rsplit(".", 1)[0]
        )
        raw = await f.read()
        file_items.append((knowledge_name, f.filename, raw))

    # 切片配置取当前用户偏好（chunk_model=False 时不切片，整篇入库）
    pref = await Userpreference.get_or_create_userpreference(db)
    task_id = create_import_task(
        material_id,
        db_obj.material_name,
        file_items,
        chunk_model=pref.chunk_model,
        chunk_size=pref.chunk_size,
        overlap=pref.overlap_size
    )

    return {"data": {"TaskId": task_id, "Total": len(file_items), "Resp": "导入任务已创建"}}


