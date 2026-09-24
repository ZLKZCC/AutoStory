from typing import Dict, Any
from config.db_conf import get_db
from crud import ChatRecord, Project
from sqlalchemy.ext.asyncio import AsyncSession
from schemas.ChatRecord import ChatRecordCreate, ChatRecordDetail
from fastapi import APIRouter, Depends, Query, Path, HTTPException, Body
from utils.run_manager import run_gate


router = APIRouter(prefix="/autostory/chatrecord", tags=["chatrecord"])


@router.get("/chatrecords")
async def get_chatrecords(
        project_id: int = Query(..., description="项目ID"),
        page: int = Query(..., gt=0),
        pagesize: int = Query(10, gt=0),
        db: AsyncSession = Depends(get_db)
):
    """
    获取指定项目下的聊天记录列表（分页）+ 项目级 token 总账。

    - terminated 补全：无活跃 run 时，把"应用关闭导致 run 中断"幸存的
      tool_call 行（缺 result）就地补全落库（run 在飞则跳过，result 马上就到）。
    - tokens_used / context_window：Project 行上的总账（run 收尾更新），
      前端刷新后圆环立即有数（与 done 信封 / context_size 三出口同源）。
    """
    # 无活跃 run（含人审 awaiting）才做 terminated 兜底补全
    if not run_gate.is_active(project_id):
        try:
            await ChatRecord.backfill_terminated_tool_calls(db, project_id)
            # 未决 interrupt / audiobook 镜像行一并置终止：重开后不再走 payload 恢复链
            # 复活可操作卡（用户决策 2026-09-22：聊天已结束，卡就应该是终止态）
            await ChatRecord.terminate_unresolved_mirrors(db, project_id)
        except Exception:
            pass  # 补全失败不阻塞历史返回

    offset = (page - 1) * pagesize
    chats, total = await ChatRecord.get_chatrecords_by_paginated(
        db, project_id, offset, pagesize
    )

    has_more = (offset + len(chats)) < total

    chats = [ChatRecordDetail.model_validate(chat) for chat in chats]

    # 项目级 token 总账（run 收尾 done 时写入；无 run 时为 0，前端不覆盖默认）
    tokens_used = 0
    context_window = 0
    project = await Project.get_project_by_id(db, project_id)
    if project is not None:
        tokens_used = int(getattr(project, "tokens_used", 0) or 0)
        context_window = int(getattr(project, "context_window", 0) or 0)

    return {
        "data": {
            "List": chats,
            "Total": total,
            "More": has_more,
            "tokens_used": tokens_used,
            "context_window": context_window,
        }
    }


@router.post("/add_chatrecord")
async def add_chatrecord(
        project_id: int = Query(..., description="所属项目ID"),
        chat: ChatRecordCreate = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """
    创建新聊天记录，并建立与项目的关联
    """
    new_chat = await ChatRecord.add_chatrecord_by_model(db, chat)
    await Project.add_project_chat(db, project_id, new_chat.id)

    return {
        "data": {
            "ChatRecord": new_chat,
            "Resp": "创建成功"
        }
    }


@router.get("/{chat_id}")
async def get_chatrecord(
        chat_id: int = Path(..., description="聊天记录ID"),
        db: AsyncSession = Depends(get_db)
):
    """
    获取聊天记录详情
    """
    chat = await ChatRecord.get_chatrecord_by_id(db, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="聊天记录不存在")

    return {
        "data": {
            "ChatRecord": ChatRecordDetail.model_validate(chat)
        }
    }


@router.put("/{chat_id}")
async def update_chatrecord(
        chat_id: int = Path(..., description="聊天记录ID"),
        update_data: Dict[str, Any] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """
    更新聊天记录信息（支持部分更新）
    """
    if not update_data:
        raise HTTPException(status_code=400, detail="请求体不能为空")

    updated_chat = await ChatRecord.update_chatrecord(db, chat_id, update_data)
    if not updated_chat:
        raise HTTPException(status_code=404, detail="聊天记录不存在")

    return {
        "data": {
            "ChatRecord": updated_chat,
            "Resp": "更新成功"
        }
    }


@router.delete("/{chat_id}")
async def delete_chatrecord(
        chat_id: int = Path(..., description="聊天记录ID"),
        db: AsyncSession = Depends(get_db)
):
    """
    删除单条聊天记录，同时清理关联关系
    """
    await Project.remove_project_chat(db, chat_id)

    success = await ChatRecord.delete_chatrecord(db, chat_id)

    if not success:
        raise HTTPException(status_code=404, detail="聊天记录不存在或已删除")

    return {
        "data": {
            "Resp": "删除成功"
        }
    }
