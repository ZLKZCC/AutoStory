import mimetypes

from starlette.responses import FileResponse

from config.store import conf
from typing import List, Optional
from config.db_conf import get_db
from crud import Resource, AudioBookScript
from pathlib import Path as FilePath
from schemas.Resource import ResourceDetail
from sqlalchemy.ext.asyncio import AsyncSession
from utils.common import save_upload_file, remove_file
from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, Path, Body, HTTPException


router = APIRouter(prefix="/autostory/resource", tags=["resource"])


@router.post("/add_resource")
async def add_resource(
        audio_name: str = Form(...),
        description: str = Form(""),
        audiotype: str = Form(...),
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db)
):
    """添加单个资源（含文件上传）"""
    print(audiotype)
    db_obj = await Resource.add_resource(
        db, audio_name=audio_name, description=description, path="",audiotype=audiotype
    )

    safe_name = "".join(c for c in audio_name if c.isalnum() or c in (' ', '_', '-'))
    suffix = FilePath(file.filename).suffix if file.filename else ".mp3"
    filename = f"{safe_name}_{db_obj.id}{suffix}"
    file_path = conf.RESOURCE_DIR / filename

    try:
        await save_upload_file(file, file_path)
    except Exception:
        await Resource.delete_resource(db, db_obj.id)
        await db.commit()
        raise

    await Resource.update_resource(db, db_obj.id, {"path": str(file_path)})

    return {"data": {"Resource": ResourceDetail.model_validate(db_obj), "Resp": "创建成功"}}


@router.put("/update_resource/{audio_id}")
async def update_resource(
        audio_id: int = Path(...),
        audio_name: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        file: Optional[UploadFile] = File(None),
        db: AsyncSession = Depends(get_db)
):
    """更新资源信息（支持更换音频文件）"""
    db_obj = await Resource.get_resource_by_id(db, audio_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="资源不存在")

    update_data = {}
    if audio_name is not None:
        update_data["Audio_name"] = audio_name
    if description is not None:
        update_data["description"] = description

    if file:
        if db_obj.path:
            await remove_file(db_obj.path)

        final_name = audio_name if audio_name else db_obj.Audio_name
        safe_name = "".join(c for c in final_name if c.isalnum() or c in (' ', '_', '-'))
        suffix = FilePath(file.filename).suffix if file.filename else ".mp3"
        filename = f"{safe_name}_{audio_id}{suffix}"
        new_path = conf.RESOURCE_DIR / filename

        await save_upload_file(file, new_path)
        update_data["path"] = str(new_path)

    if update_data:
        await Resource.update_resource(db, audio_id, update_data)

    return {"data": {"Resource": ResourceDetail.model_validate(db_obj), "Resp": "更新成功"}}

@router.get("/file/{audio_id}")
async def get_resource_file(
        audio_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    """流式返回音频文件（供前端 <audio> 播放，支持 Range 断点/拖动进度）"""
    db_obj = await Resource.get_resource_by_id(db, audio_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="资源不存在")

    file_path = FilePath(db_obj.path)
    if not db_obj.path or not file_path.is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在")

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type=mimetypes.guess_type(file_path.name)[0] or "audio/mpeg",
    )


@router.delete("/delete_resource/{audio_id}")
async def delete_resource(
        audio_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    """删除单个资源"""

    db_obj = await Resource.get_resource_by_id(db, audio_id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="资源不存在")

    await Resource.delete_mapping_by_id(db,audio_id)
    await Resource.delete_resource(db, audio_id)
    await db.commit()
    #    避免文件已不存在时抛 500（此时库已删成功）
    try:
        if db_obj.path:
            await remove_file(db_obj.path)
    except Exception as e:
        print(f"remove file failed: {e}")

    return {"data": {"Resp": "删除成功"}}


@router.post("/batch_delete_resources")
async def batch_delete_resources(
        audio_ids: List[int] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """批量删除资源"""
    print(audio_ids)
    if not audio_ids:
        return {"data": {"Resp": "删除条目不能为空"}}


    res = await Resource.get_resource_by_ids(db, audio_ids)
    await Resource.delete_mapping_by_ids(db, audio_ids)
    await Resource.delete_resources(db, audio_ids)
    await db.commit()
    for audio in res:
        #    避免文件已不存在时抛 500（此时库已删成功）
        try:
            if audio.path:
                await remove_file(audio.path)
        except Exception as e:
            print(f"remove file failed: {e}")  # 建议换成 logger

    return {"data": {"Resp": "批量删除成功"}}


@router.get("/script/{script_id}")
async def get_project_resources(
        script_id: int = Path(..., description="脚本id"),
        db: AsyncSession = Depends(get_db)
):
    """获取项目已映射的全部音频资源（不分页，供有声书编排向导勾选）"""
    resources = await Resource.get_resources_by_script(db, script_id)
    return {"data": {"List": [ResourceDetail.model_validate(r) for r in resources]}}

@router.get("/resources")
async def get_resources(
        audiotype: str = Query(""),
        page: int = Query(1, gt=0),
        pagesize: int = Query(10, gt=0),
        db: AsyncSession = Depends(get_db)
):
    """获取分页资源列表"""
    offset = (page - 1) * pagesize
    resources, total = await Resource.get_resources_paginated(db, audiotype, offset, pagesize)

    return {
        "data": {
            "List": [ResourceDetail.model_validate(r) for r in resources],
            "Total": total
        }
    }


@router.post("/add_mapping")
async def add_mapping(
        script_id: int = Body(...),
        audio_id: int = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """添加项目-音频映射"""
    res = await Resource.get_resource_by_id(db, audio_id)
    if not res:
        raise HTTPException(status_code=404, detail="音频资源不存在")

    # 检查项目是否存在
    abs = await AudioBookScript.get_script_by_id(db, script_id)
    if not abs:
        raise HTTPException(status_code=404, detail="脚本不存在")

    await AudioBookScript.add_audiobook_audio(db, script_id, audio_id)

    return {"data": {"Resp": "映射添加成功"}}


@router.delete("/remove_mapping")
async def remove_mapping(
        script_id: int = Query(...),
        audio_id: int = Query(...),
        db: AsyncSession = Depends(get_db)
):
    """删除指定项目下的指定音频映射"""

    deleted = await AudioBookScript.remove_audiobook_audio(db, script_id, audio_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="映射不存在")

    return {"data": {"Resp": "映射删除成功"}}

@router.post("/set_mapping")
async def set_mapping(
    script_id: int = Body(...),
    audio_ids: List[int] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """以本次提交为准，整体替换脚本的音频映射"""
    saved = await AudioBookScript.replace_script_audios(db, script_id, audio_ids)
    return {"data": {"List": saved, "Resp": "映射已更新"}}
