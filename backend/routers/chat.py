from datetime import datetime
import json
import logging
from typing import Dict, Any

from langchain_core.messages.utils import count_tokens_approximately

from config.db_conf import get_db
from crud import Summary, ChatRecord, Project, Provider
from sse_starlette import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from schemas.ChatRecord import ChatRecordCreate
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from utils.context import build_context
from utils.run_manager import run_gate, stream_wrapper
from agent.config.graph import main_graph
from agent.config.streaming import agent_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/autostory/chat", tags=["chat"])


@router.post("/sendmessage")
async def sendmessage(
        messageinfo: Dict[str, Any] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """发送新消息（单 run 闸 + build_context + stream_wrapper）"""
    project_id = messageinfo.get("project_id")
    user_content = messageinfo.get("content", "")

    # 触发溯源：记录每次 sendmessage 的到达时刻与内容摘要（排查"未见过的自动发送"）
    logger.warning("[sendmessage] project=%s len=%d head=%r", project_id, len(user_content or ""), (user_content or "")[:50])

    if not project_id or not user_content:
        raise HTTPException(status_code=400, detail="缺少项目ID或内容")

    # 单轮字数限制：超长截断（前端 maxlength=8000 已限制，此处兜底防绕过）
    provider = await Provider.get_active_provider(db)
    if count_tokens_approximately(user_content) > provider.context_length * 0.2:
        user_content = user_content[:int(provider.context_length * 0.1)]+"..."+ user_content[int(provider.context_length * 0.1):]

    # 1. 单 run 闸（含 awaiting_input 占坑）
    if run_gate.is_active(project_id):
        raise HTTPException(status_code=409, detail="该项目有正在进行的对话")

    # 2. 用户消息落库（路由同步 commit，任何崩溃幸存）
    user_record = await ChatRecord.add_chatrecord_by_model(db, ChatRecordCreate(
        role="user", content=user_content, timestamp=datetime.now(), type="message"
    ))
    await Project.add_project_chat(db, project_id, user_record.id)
    await db.commit()

    # 3. build_context（项目摘要 + 对话摘要 + 摘要终点后的原生消息）
    ctx = await build_context(db, project_id)

    # 4. thread_id per-turn 唯一（interrupt 恢复时复用）
    thread_id = f"project_{project_id}_{user_record.id}"

    # 5. 注册 run
    run_gate.register(project_id, thread_id)

    # 6. SSE 信封流（wrapper 消费 run_agent_stream，转发 + 最小单元落库）
    return EventSourceResponse(stream_wrapper(
        project_id, thread_id,
        ctx["summary"], ctx["project_summary"], ctx["messages"], user_content,
        project_name=ctx.get("project_name", ""),
        project_description=ctx.get("project_description", ""),
    ))


@router.post("/resume")
async def resume_chat(
        resume_info: Dict[str, Any] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """恢复中断的 run（同 thread_id 续跑暂停的图，Command(resume=...)）

    resume 协议按身份认卡（call_id + action），不按位置猜：
    - 用户回答的是哪张卡，就恢复哪张卡对应的 thread、核对图当前挂着的中断确是它才放行；
    - 对不上（残留旧卡 / 重复 resume / 已被处理）即废信，干净退回，绝不动别的中断；
    - claim_resume 原子认领把"同项目单 run 闸"一致地应用到 resume，挡住并发 resume 打在同一 checkpoint。

    支持 reload 恢复：后端重启后 运行闸 内存清空，但 checkpointer 里图状态仍在，
    从镜像记录 content 里取 _thread_id 重建 运行闸，让 resume 能真正续跑。
    """
    project_id = resume_info.get("project_id")
    resume_value = resume_info.get("resume_value")
    resume_call_id = resume_info.get("call_id") or ""
    resume_action = resume_info.get("action")

    # 触发溯源：记录每次 /resume 的到达时刻、身份与闸状态（排查"未见过的自动 resume"，
    # 与前端控制台 [resume] 调用栈对照即可定位触发者）
    logger.warning(
        "[resume] project=%s call_id=%s action=%s is_active=%s is_awaiting=%s resume_value=%s",
        project_id, resume_call_id, resume_action,
        run_gate.is_active(project_id) if project_id else None,
        run_gate.is_awaiting(project_id) if project_id else None,
        list(resume_value.keys()) if isinstance(resume_value, dict) else type(resume_value).__name__,
    )

    if not project_id:
        raise HTTPException(status_code=400, detail="缺少项目ID")

    # reload 恢复：内存无 run → 按身份找回未处理镜像重建 运行闸（无 call_id 退回按最近一条）
    if not run_gate.is_active(project_id):
        record = (
            await ChatRecord.get_unresolved_mirror_by_identity(db, project_id, resume_call_id, resume_action)
            if resume_call_id
            else await ChatRecord.get_latest_unresolved_mirror(db, project_id)
        )
        if record:
            try:
                payload = json.loads(record.content)
                thread_id = payload.get("_thread_id")
                if thread_id:
                    run_gate.register(project_id, thread_id)
                    run_gate.set_awaiting(project_id, True)
            except Exception:
                pass  # 镜像 content 损坏，无法恢复

    # 原子认领：run 状态机 parked(awaiting) → streaming(running)，resume 仅可从 parked 出发。
    # 认领失败＝无等待中的 run，或已有流在飞（并发/重复 resume）——单 run 闸一致地拦下。
    thread_id = run_gate.claim_resume(project_id)
    if not thread_id:
        logger.warning(
            "[resume] 409 无可认领的等待 run｜project_id=%s｜is_active=%s｜is_awaiting=%s｜"
            "run_thread_id=%s｜call_id=%s｜action=%s",
            project_id, run_gate.is_active(project_id), run_gate.is_awaiting(project_id),
            run_gate.get_thread_id(project_id), resume_call_id, resume_action,
        )
        raise HTTPException(status_code=409, detail="没有等待输入的 run，且无法从历史恢复")

    # 身份核对：图当前真正挂着的中断必须与本次回答的卡一致（call_id + action）
    if resume_call_id:
        graph = await main_graph.get()
        state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        pending = agent_stream.collect_interrupts(state)

        def _identity_match(intr) -> bool:
            v = intr.value if isinstance(intr.value, dict) else {}
            if v.get("call_id") != resume_call_id:
                return False
            # 次级身份：有声书中断带 subtype（新词汇）、写入工具带 action（旧词汇），同认
            if resume_action is not None and v.get("action") != resume_action and v.get("subtype") != resume_action:
                return False
            return True

        if not any(_identity_match(i) for i in pending):
            if not pending:
                # 图根本没在等（已跑完/已推进）→ 释放占闸，别留死 run 卡住后续 /send
                run_gate.force_unregister(project_id)
            else:
                # 图挂在别的中断上 → 本次是残留旧卡/重复 resume：退回认领，正确那张卡仍可被回答
                run_gate.set_awaiting(project_id, True)
            logger.warning(
                "[resume] 409 身份不匹配｜project_id=%s｜call_id=%s｜action=%s｜pending=%s",
                project_id, resume_call_id, resume_action,
                [(i.value or {}).get("call_id") if isinstance(i.value, dict) else None for i in pending],
            )
            raise HTTPException(status_code=409, detail="该卡片已失效或与当前等待的中断不匹配")

    # 不在这里标记镜像 resolved：交给 stream_wrapper 在「图确实消费了本次 resume、开始产出」后按身份标。
    # 否则一旦在"标记 resolved"与"图真正续跑"之间被打断，会留下「镜像已 resolved + 图仍 park」矛盾态 → 无法恢复。
    return EventSourceResponse(stream_wrapper(
        project_id, thread_id, resume_value=resume_value,
        resume_call_id=resume_call_id, resume_action=resume_action,
    ))


@router.post("/cancel")
async def cancel_chat(
        cancel_info: Dict[str, Any] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """取消活跃 run / 释放 awaiting_input 占闸"""
    project_id = cancel_info.get("project_id")

    if not project_id:
        raise HTTPException(status_code=400, detail="缺少项目ID")

    if not run_gate.is_active(project_id):
        raise HTTPException(status_code=404, detail="没有活跃的 run")

    # cancel 语义 = 用户放弃人审 → 标记镜像记录为 rejected/reverted
    await ChatRecord.mark_awaiting_resolved(db, project_id, False)
    await db.commit()

    run_gate.force_unregister(project_id)
    return {"status": "cancelled"}


@router.get("/context_size")
async def context_size(
        project_id: int = Query(..., description="项目id"),
        draft: str = Query("", description="输入框当前草稿（可选）"),
        db: AsyncSession = Depends(get_db),
):
    """当前上下文的精确 token 占用 + 窗口（供前端打开/切换对话时即时显示准确值）。

    前端原先用"消息字数 × 系数"粗估，漏算 system_prompt（人设 + 项目摘要 + 历史摘要）与
    工具定义，圆环系统性偏低、要等一轮 done 才跳准。这里复用 build_context +
    render_system_prompt + main_graph.count_state_tokens，与真实新一轮 / done 信封同口径算精确值。

    口径说明（重要）：build_context 会排除"最后一条用户消息"（防当前轮预知），
    所以历史里最后那条 Human 若就是用户刚发出、还没得到回复的那条，它是真实
    "下一轮要送进 LLM 的量"的一部分，必须补回来。draft 是用户还没发送的输入框内容，
    也一并以 HumanMessage 计入（与发送后 build_context 因排除而当轮不计相抵消）。
    """
    from agent.prompts import render_system_prompt
    from agent.models.loader import get_context_window
    from langchain_core.messages import HumanMessage

    ctx = await build_context(db, project_id)
    system_prompt = render_system_prompt(
        summary=ctx["summary"],
        project_summary=ctx["project_summary"],
        project_name=ctx["project_name"],
        project_description=ctx["project_description"],
    )
    messages = list(ctx["messages"])
    # 补回被 build_context 排除的"悬空末条用户消息"（发了还没回，属下一轮上下文）
    pending_user = await ChatRecord.get_pending_human_tail(db, project_id)
    if pending_user:
        messages.append(HumanMessage(
            content=pending_user.content,
            additional_kwargs={"record_id": pending_user.id},
        ))
    # 输入框草稿：发送后会被 build_context 排除，故此处与"发送后当轮"数字一致
    if draft and draft.strip():
        messages.append(HumanMessage(content=draft))
    tokens_used = main_graph.count_state_tokens(messages, system_prompt)
    window = await get_context_window("chat")
    return {"tokens_used": tokens_used, "context_window": window}
