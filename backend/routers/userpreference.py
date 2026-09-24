from crud import Userpreference
from typing import Dict, Any
from config.db_conf import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, Body

router = APIRouter(prefix="/autostory/userpreference", tags=["userpreference"])


@router.get("/current")
async def get_current_userpreference(
        db: AsyncSession = Depends(get_db)
):
    """获取单例用户偏好（启动时已确保存在，此处兜底懒创建）"""
    pref = await Userpreference.get_or_create_userpreference(db)

    return {
        "data": {
            "Preference": {
                "id": pref.id,
                "chunk_model": pref.chunk_model,
                "chunk_size": pref.chunk_size,
                "overlap_size": pref.overlap_size
            }
        }
    }


@router.put("/current")
async def update_current_userpreference(
        update_data: Dict[str, Any] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """更新单例用户偏好（仅 chunk_model / chunk_size / overlap_size 三字段，忽略其余键）"""
    fields = {"chunk_model", "chunk_size", "overlap_size"}
    update = {k: v for k, v in update_data.items() if k in fields}

    pref = await Userpreference.update_current_userpreference(db, update)

    return {
        "data": {
            "Preference": {
                "id": pref.id,
                "chunk_model": pref.chunk_model,
                "chunk_size": pref.chunk_size,
                "overlap_size": pref.overlap_size
            },
            "Resp": "偏好已更新"
        }
    }
