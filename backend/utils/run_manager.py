import json
import asyncio
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

from agent.config.streaming import agent_stream
from config.db_conf import AsyncSessionLocal
from crud import ChatRecord, Project
from schemas.ChatRecord import ChatRecordCreate


class RunGate:
    """同项目单 run 闸：一个项目同一时刻只能有一个 run 在跑。

    runs[project_id] = {thread_id, awaiting}：
    - awaiting=False → run 正在流式产出（占闸）
    - awaiting=True  → run 停在人审中断上，占闸不放，直到 resume 或 cancel
    不落 DB：这是纯运行时状态，进程重启即清空（由镜像记录重建）。
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "init"):
            return
        self.init = True
        self.runs = {}

    def is_active(self, project_id: int) -> bool:
        return project_id in self.runs

    def is_awaiting(self, project_id: int) -> bool:
        run = self.runs.get(project_id)
        return bool(run and run.get("awaiting"))

    def set_awaiting(self, project_id: int, awaiting: bool):
        run = self.runs.get(project_id)
        if run:
            run["awaiting"] = awaiting

    def register(self, project_id: int, thread_id: str):
        self.runs[project_id] = {"thread_id": thread_id, "awaiting": False}


    def claim_resume(self, project_id: int) -> Optional[str]:
        """把 run 从"等待人审(awaiting)"原子认领为"正在续跑(streaming)"。

        仅当 run 存在且 awaiting=True 时：置 awaiting=False 并返回 thread_id（认领成功）；
        否则返回 None（无等待中的 run，或已有流在飞）。
        run 的状态机是 parked(awaiting) → streaming(running)，resume 是从 parked 出发的合法转换；
        两个 resume 并发时只有一个能赢得这次转换（asyncio 单线程内检查+置位之间无 await，故原子），
        挡住并发/重复 resume 同时打在同一个 checkpoint 上、搅乱中断序列。
        """
        run = self.runs.get(project_id)
        if run and run.get("awaiting"):
            run["awaiting"] = False
            return run["thread_id"]
        return None

    def get_thread_id(self, project_id: int) -> Optional[str]:
        run = self.runs.get(project_id)
        return run["thread_id"] if run else None

    def unregister(self, project_id: int):
        # awaiting_input 的 run 保持注册（占闸直到 resume/cancel）
        run = self.runs.get(project_id)
        if run and run.get("awaiting"):
            return
        self.runs.pop(project_id, None)

    def force_unregister(self, project_id: int):
        """cancel 时强制清闸（即使 awaiting）"""
        self.runs.pop(project_id, None)


class TurnLog:
    """每线程的落库账本：跨 resume 请求存活，本轮 done/error 时清空。

    一个 thread 可能被多个流消费（首次 send + 多次 resume），这些状态必须跨流累积：
    - pending_tools：tool_call 先到、result 后到，先暂存调用信息，等 result 回来配对落库
    - logged_calls ：本轮已落库的 call_id，resume 重放 act 重发同一 ToolMessage 时据此跳过
    清空时机：done（本轮跑完）/ error（本轮终止）——都用 drop(thread_id)。
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "init"):
            return
        self.init = True
        self.turns = {}

    def open(self, thread_id: str) -> dict:
        turn = self.turns.get(thread_id)
        if turn is None:
            turn = {"pending_tools": {}, "logged_calls": set()}
            self.turns[thread_id] = turn
        return turn

    def drop(self, thread_id: str):
        self.turns.pop(thread_id, None)


run_gate = RunGate()
turn_log = TurnLog()


# ── 最小单元落库 ──────────────────────────────────────────
async def insert_message(project_id: int, role: str, content: str, record_type: str,
                         extra: str = ""):
    """最小单元完成时一次 INSERT（无占位、无增量 UPDATE，status 纯运行时）。
    extra = 行协议外层的 call_id（tool_call/audiobook 行；message/interrupt 行空串）"""
    async with AsyncSessionLocal() as db:
        try:
            record_create = ChatRecordCreate(
                role=role,
                content=content,
                timestamp=datetime.now(),
                type=record_type,
                extra=extra,
            )
            new_record = await ChatRecord.add_chatrecord_by_model(db, record_create)
            await Project.add_project_chat(db, project_id, new_record.id)
            await db.commit()
        except Exception:
            await db.rollback()


async def mark_mirror_resolved(project_id: int, approved: bool, call_id: str = "", action: str = None):
    """把本次 resume 消费掉的那张 awaiting 镜像标 resolved（前端 reload 后据此显示 confirmed/reverted）。

    按身份 (call_id + action) 精确标记被回答的那一张，不再"取最近一条"误标其它未处理镜像。
    调用时机 = 图确凿消费了本次 resume 的两个稳定点：done（本轮跑完）或 awaiting_input
    （越过旧中断挂上新中断）——中途断连 / error 不标，保留未决镜像供 resume 恢复链重试续跑。
    无 call_id（向后兼容）时退回按最近一条标记。
    """
    async with AsyncSessionLocal() as db:
        if call_id:
            await ChatRecord.mark_mirror_resolved_by_identity(db, project_id, call_id, action, approved)
        else:
            await ChatRecord.mark_awaiting_resolved(db, project_id, approved)


def sse_event(payload: dict) -> dict:
    """返回 dict（非 str），交由 EventSourceResponse 的 ensure_bytes 负责 SSE 格式化。
    若返回 str，ensure_bytes 会走 ServerSentEvent(str).encode() 把已格式化的文本当 data 值
    再包一层，前端收到 'data: data:{...}' 非法 JSON → handleEnvelope 永不触发。"""
    return {"data": json.dumps(payload, ensure_ascii=False, default=str)}


# ── 信封流消费 wrapper ─────────────────────────────────────
async def stream_wrapper(
    project_id: int,
    thread_id: str,
    summary: str = "",
    project_summary: str = "",
    history_messages: list = None,
    user_text: str = "",
    resume_value: Any = None,
    resume_call_id: str = "",
    resume_action: str = None,
    project_name: str = "",
    project_description: str = "",
) -> AsyncGenerator[str, None]:
    """
    消费 agent_stream.run 信封流（初始 / resume 两模式共用）：
    - 初始模式（resume_value=None）：传 build_context 的 messages + summary + project_name/description
    - resume 模式（resume_value 非空）：同 thread_id 续跑暂停的图（人审 resume）
    - 转发 SSE 给前端（打字机效果归前端侧）
    - 最小单元完成时一次 INSERT（message 段完成 / tool_call result 返回时）
    - done 收尾：注销闸 + 把本轮 token 占用/窗口写回项目行（总账，history 三出口同源）
    - error 收尾注销闸；awaiting_input 保持注册占闸
    - 断连（消费者停止迭代）→ finally unregister（awaiting 保留占闸）
    """
    text_buffer: list[str] = []
    text_started = False
    is_resume = resume_value is not None
    mirror_resolved = False
    resume_approved = bool(resume_value.get("approved")) if isinstance(resume_value, dict) else False
    turn = turn_log.open(thread_id)

    try:
        async for env in agent_stream.run(
            project_id, thread_id, summary, project_summary,
            history_messages or [], user_text, resume_value=resume_value,
            project_name=project_name, project_description=project_description,
        ):
            etype = env["type"]
            data = env.get("data", {})

            if etype == "token":
                text = data.get("text", "")
                if text:
                    text_buffer.append(text)
                    text_started = True
                    yield sse_event(env)  # 透传 streaming.py 原始嵌套 envelope

            elif etype == "tool_call":
                # 文本段结束（工具调用打断文本流）→ 先落库当前文本段
                if text_started and text_buffer:
                    full = "".join(text_buffer)
                    if full.strip():
                        await insert_message(project_id, "assistant", full, "message")
                    text_buffer = []
                    text_started = False
                # 缓存 tool_call，等 result 回来再落库完整行
                turn["pending_tools"][data.get("call_id", "")] = {
                    "tool": data.get("tool", ""),
                    "display_name": data.get("display_name", data.get("tool", "")),
                    "arguments": data.get("arguments", {}),
                }
                yield sse_event(env)  # 透传

            elif etype == "tool_result":
                call_id = data.get("call_id", "")
                if call_id and call_id in turn["logged_calls"]:
                    # resume 重放 act 会重发同一 ToolMessage：本轮已落过该 call_id 的 tool 行 → 跳过 INSERT 防重复；
                    # 仍透传给前端（前端按 call_id 翻卡，幂等无害）
                    yield sse_event(env)
                    continue
                pending = turn["pending_tools"].pop(call_id, {})
                tool_row = {
                    "tool": pending.get("tool", ""),
                    "display_name": pending.get("display_name", ""),
                    "arguments": pending.get("arguments", {}),
                    "result": data.get("result", ""),
                    "error": data.get("error"),
                }
                await insert_message(
                    project_id, "assistant",
                    json.dumps(tool_row, ensure_ascii=False),
                    "tool_call",
                    extra=call_id,          # 行协议外层：call_id 落 extra 列
                )
                if call_id:
                    turn["logged_calls"].add(call_id)
                yield sse_event(env)  # 透传

            elif etype == "done":
                # 镜像标记（resume 轮）：本轮跑完 = resume 已被图确凿消费，此刻才标 resolved。
                # 不在首个信封时标（旧做法缺陷）：首信封 ≠ 跑完，中途断连后闸被 finally 释放、
                # 镜像却已标 → 重试 resume 时 409 无可认领、镜像恢复也找不到未决行，卡片卡死。
                if is_resume and not mirror_resolved:
                    mirror_resolved = True
                    try:
                        await mark_mirror_resolved(project_id, resume_approved, resume_call_id, resume_action)
                    except Exception:
                        pass  # 标记失败不阻断 done 透传（刷新后卡片回 awaiting，可再 resume）
                # 最后的文本段落库
                if text_started and text_buffer:
                    full = "".join(text_buffer)
                    if full.strip():
                        await insert_message(project_id, "assistant", full, "message")
                # token 总账：done 收尾把本轮精确占用 + 窗口写回项目行
                # （history / context_size / done 三出口同源，刷新后圆环立即有数）
                tokens_used = data.get("tokens_used")
                window = data.get("context_window")
                if isinstance(tokens_used, int) and isinstance(window, int) and window > 0:
                    try:
                        async with AsyncSessionLocal() as db:
                            await Project.update_project(db, project_id, {
                                "tokens_used": tokens_used,
                                "context_window": window,
                            })
                    except Exception:
                        pass  # 总账写失败不影响主流程（下轮 done 会再写）
                turn_log.drop(thread_id)   # 本轮结束，清理跨流落库状态
                yield sse_event(env)  # 透传

            elif etype == "error":
                turn_log.drop(thread_id)   # 本轮终止，清理跨流落库状态
                yield sse_event(env)  # 透传

            elif etype == "awaiting_input":
                run_gate.set_awaiting(project_id, True)
                # 镜像标记（resume 轮）：图确凿越过旧中断、挂上新中断 = 旧卡已被消费。
                # 必须在写新镜像行之前标：同一工具链的旧/新卡共享 call_id（action 不同），
                # 先写后标会把按身份匹配的新行一并标掉。
                if is_resume and not mirror_resolved:
                    mirror_resolved = True
                    try:
                        await mark_mirror_resolved(project_id, resume_approved, resume_call_id, resume_action)
                    except Exception:
                        pass  # 标记失败不阻断中断透传
                # 中断前若有未落库的叙述文本（如有声书路由前 agent 说的话，无 tool_call 触发 flush），
                # 先落库，避免这段叙述丢失、reload 后不显示
                if text_started and text_buffer:
                    full = "".join(text_buffer)
                    if full.strip():
                        await insert_message(project_id, "assistant", full, "message")
                    text_buffer = []
                    text_started = False
                # 镜像落库：reload 后前端 dbToMessage 映射回 interrupt/audiobook 卡
                # （和 tool_call 同层：role=assistant, type 区分, content 存 JSON）
                # 关键：payload 里加 _thread_id，让后端重启后能从镜像记录恢复 checkpointer 续跑
                payload = data.get("payload", {})
                entity = payload.get("entity", "") if isinstance(payload, dict) else ""
                if entity == "audiobook" and isinstance(payload, dict) and payload.get("subtype"):
                    # ── audiobook 行协议：content = {subtype, summary, script_id, payload(业务), _thread_id}，
                    #    call_id → 行 extra 列（content 内不重复）；entity → 行 type 列已表达。
                    #    proposal/mapping 镜像落 slim（只存 stage_catalog，全文回放时从脚本行
                    #    stage_payload 拉，前端 loadHistoryInto 补全）；naming/narrator/script 保留全量。
                    subtype = payload.get("subtype", "")
                    slim_keys = ("stage_catalog",) if subtype in ("proposal", "mapping") else None
                    if subtype == "naming":
                        business_keys = ("current",)
                    elif subtype == "narrator":
                        business_keys = ("presets", "narrator_desc")
                    elif subtype == "script":
                        business_keys = ("script_overview", "preview")
                    else:
                        business_keys = slim_keys
                    envelope_keys = {"entity", "subtype", "call_id", "script_id",
                                     "summary", "phase", "action"}
                    if business_keys is None:
                        business = {k: v for k, v in payload.items()
                                    if k not in envelope_keys}
                    else:
                        business = {k: payload[k] for k in business_keys if k in payload}
                    row_content = {
                        "subtype": subtype,
                        "summary": payload.get("summary", ""),
                        "payload": business,
                        "_thread_id": thread_id,
                    }
                    if payload.get("script_id"):
                        row_content["script_id"] = payload["script_id"]
                    try:
                        await insert_message(
                            project_id, "assistant",
                            json.dumps(row_content, ensure_ascii=False, default=str),
                            "audiobook",
                            extra=str(payload.get("call_id") or ""),
                        )
                    except Exception:
                        pass
                elif entity:
                    # ── interrupt 行（写入工具人审）：协议不变，call_id/resolved 在 content 内
                    try:
                        payload_with_thread = {
                            **payload,
                            "_thread_id": thread_id,
                        } if isinstance(payload, dict) else {"_thread_id": thread_id}
                        await insert_message(
                            project_id, "assistant",
                            json.dumps(payload_with_thread, ensure_ascii=False, default=str),
                            "interrupt",
                        )
                    except Exception:
                        pass
                yield sse_event(env)  # 透传
            else:
                # custom 事件（audiobook_progress / 未来自定义类型）原样透传。
                # done 是瞬态事件不落库会丢（F5 后完成卡退回 awaiting），
                # 故 done 额外落一条镜像，前端回放据此还原完成卡 + 播放直链。
                if etype == "audiobook_progress" and data.get("phase") == "done":
                    call_id = data.get("call_id", "")
                    if call_id:
                        # 行协议：content = {subtype:"done", final:"confirmed", summary, script_id,
                        # warnings, _thread_id}；call_id → 行 extra 列；不落 audio_path
                        # （播放走 script_id 直链，getAudioScriptAudioUrl）
                        done_row = {
                            "subtype": "done",
                            "final": "confirmed",
                            "summary": data.get("detail", ""),
                            "warnings": data.get("warnings") or [],
                            "_thread_id": thread_id,
                        }
                        if data.get("script_id"):
                            done_row["script_id"] = data.get("script_id")
                        try:
                            await insert_message(
                                project_id, "assistant",
                                json.dumps(done_row, ensure_ascii=False, default=str),
                                "audiobook",
                                extra=str(call_id),
                            )
                        except Exception:
                            pass
                yield sse_event(env)

    except asyncio.CancelledError:
        # 断连取消：未完成段内存 buffer 丢弃，已完成段已在库
        raise
    finally:
        run_gate.unregister(project_id)
