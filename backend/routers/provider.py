from crud import Provider
from typing import Dict, Any, List
from config.db_conf import get_db
from utils.provider import probe_provider
from config.store import get_model_context_window
from sqlalchemy.ext.asyncio import AsyncSession
from utils.crypto import encrypt_text, decrypt_text
from schemas.Provider import ProviderCreate, ProviderDetail
from fastapi import APIRouter, Depends, Query, Body, Path, HTTPException




router = APIRouter(prefix="/autostory/provider", tags=["provider"])

@router.get("/providers")
async def get_providers(
        page: int = Query(1, gt=0),
        pagesize: int = Query(10, gt=0),
        db: AsyncSession = Depends(get_db)
):
    offset = (page - 1) * pagesize
    providers, total = await Provider.get_providers_paginated(db, offset, pagesize)
    has_more = (offset + len(providers)) < total

    providers_detail = [ProviderDetail.model_validate(p) for p in providers]
    for d in providers_detail:
        d.api_key = decrypt_text(d.api_key)
    return {
        "data": {
            "List": providers_detail,
            "Total": total,
            "More": has_more
        }
    }


@router.post("/create_provider")
async def create_provider(
        provider: ProviderCreate,
        db: AsyncSession = Depends(get_db)
):
    # 校验与修正上下文长度
    if not provider.context_length or provider.context_length == 0:
        # 注册表查询：精确 → 最长前缀（覆盖 -flash 等变体）→ 兜底默认
        provider.context_length = get_model_context_window(provider.model_id)

    provider.api_key = encrypt_text(provider.api_key)

    new_provider = await Provider.create_provider_by_model(db,provider)

    return {
        "data": {
            "Provider": ProviderDetail.model_validate(new_provider),
            "Resp": "创建成功"
        }
    }


@router.get("/{provider_id}")
async def get_provider(
        provider_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    provider = await Provider.get_provider_by_id(db, provider_id)
    detail = ProviderDetail.model_validate(provider)
    detail.api_key = decrypt_text(detail.api_key)
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")

    return {
        "data": {
            "Provider": detail
        }
    }


@router.put("/{provider_id}")
async def update_provider(
        provider_id: int = Path(...),
        update_data: Dict[str, Any] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    if not update_data:
        raise HTTPException(status_code=400, detail="请求体不能为空")

    # 如果更新涉及 model_id 且 context_length 为 0 或未传，尝试修正
    if "model_id" in update_data and not update_data.get("context_length"):
        update_data["context_length"] = get_model_context_window(update_data["model_id"])
    if "api_key" in update_data:
        update_data["api_key"] = encrypt_text(update_data["api_key"])

    updated_provider = await Provider.update_provider(db, provider_id, update_data)
    detail = ProviderDetail.model_validate(updated_provider)
    detail.api_key = decrypt_text(detail.api_key)

    if not updated_provider:
        raise HTTPException(status_code=404, detail="供应商不存在")

    return {
        "data": {
            "Provider": detail,
            "Resp": "更新成功"
        }
    }


@router.delete("/{provider_id}")
async def delete_provider(
        provider_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    success = await Provider.delete_provider(db, provider_id)
    if not success:
        raise HTTPException(status_code=404, detail="供应商不存在")

    return {
        "data": {
            "Resp": "删除成功"
        }
    }

@router.post("/batch-delete")
async def delete_providers(
        provider_ids: List[int] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    if not provider_ids:
        raise HTTPException(status_code=400, detail="provider_ids 不能为空")
    deleted = await Provider.batch_delete_providers(db, provider_ids)
    return {
        "data": {
            "Deleted": deleted,
            "Resp": "批量删除成功"
        }
    }

@router.post("/test")
async def test_provider(data: Dict[str, Any] = Body(...)):
    """测试供应商是否可用（列表行内按钮：连通性 + 凭据校验，不消耗对话 token）。
    provider 为前端预设 id，缺省时按 base_url 特征推断。"""
    if not data.get("api_url") or not data.get("api_key"):
        raise HTTPException(status_code=400, detail="api_url 与 api_key 不能为空")
    return {"data": await probe_provider(data.get("provider") or "", data["api_url"], data["api_key"])}

@router.post("/test-connection")
async def test_connection(data: Dict[str, Any] = Body(...)):
    """测试连接并获取可用模型列表（添加供应商弹窗：成功后用模型列表填充选择框）。
    provider 为前端预设 id，缺省时按 base_url 特征推断。"""
    if not data.get("api_url") or not data.get("api_key"):
        raise HTTPException(status_code=400, detail="api_url 与 api_key 不能为空")
    return {"data": await probe_provider(data.get("provider") or "", data["api_url"], data["api_key"])}


@router.get("/activate/{provider_id}")
async def activate_provider(
        provider_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    provider = await Provider.set_default_provider(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")

    return {
        "data": {
            "Provider": ProviderDetail.model_validate(provider),
            "Resp": "设置成功"
        }
    }

