from typing import Dict, Any
from pathlib import Path as FilePath
import asyncio
import mimetypes
import uuid
from config.store import conf
from config.db_conf import get_db, AsyncSessionLocal
from crud import Character, CharacterStage
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse
from utils.voicegenerator import probe_device, VoiceGenerator, DEFAULT_REF_TEXT
from utils.common import generate_voice_name, rm_characters, rm_dir
from utils.gpu_gate import gpu_gate, VRAM_TTS
from fastapi import APIRouter, Depends, Query, Path, HTTPException, Body
from schemas.CharacterStage import CharacterStageCreate, CharacterStageDetail

router = APIRouter(prefix="/autostory/characterstage", tags=["characterstage"])

# ── 语音生成后台任务（单任务串行，参考素材导入的任务字典模式） ──
# status：queued（GPU 闸排队中，可能被合成/试听占着）→ processing（获闸推理中）→ done/error
VOICE_TASKS: Dict[str, dict] = {}


async def _run_voice_task(task_id: str, stage_id: int, voice_description: str):
    """后台执行参考音色生成：executor 桥接同步推理，完成后独立 session 写库"""
    try:
        character_stage_dir = conf.CHARACTER_DIR / f"characterstage_{stage_id}"
        character_stage_dir.mkdir(parents=True, exist_ok=True)
        voice_path = character_stage_dir / generate_voice_name()

        def _design_voice():
            # 探测（含重试）→ 独立实例 → 用完即释放
            device = probe_device("voice_design")
            gen = VoiceGenerator(device=device)
            try:
                gen.design_voice(
                    voice_description + "。说话时请以正常语速，不慢不急。",
                    DEFAULT_REF_TEXT,
                    output_path=voice_path,
                )
            finally:
                gen.release()

        loop = asyncio.get_running_loop()
        # voice_design 模型 ~4.2GB，经全局 GPU 闸放行（与有声书合成共用一把闸，防并发撞 OOM）
        async with gpu_gate.reserve(VRAM_TTS):
            VOICE_TASKS[task_id]["status"] = "processing"  # 获得闸才转推理中（之前是排队）
            await loop.run_in_executor(None, _design_voice)

        async with AsyncSessionLocal() as db:
            await CharacterStage.update_character_stage(db, stage_id, {
                "voice_description": voice_description,
                "voice_path": str(voice_path),
            })

        VOICE_TASKS[task_id]["status"] = "done"
    except Exception as e:
        VOICE_TASKS[task_id]["status"] = "error"
        VOICE_TASKS[task_id]["error"] = str(e)
    finally:
        VOICE_TASKS[task_id]["stage_id"] = stage_id


@router.post("/generatevoice/{character_stage_id}")
async def generate_voice(
        character_stage_id: int = Path(...),
        voice_description: str = Body(..., embed=True),
        db: AsyncSession = Depends(get_db)
):
    """发起参考音色生成后台任务（TTS 推理串行，同一时刻仅一个任务）"""
    stage = await CharacterStage.get_character_stage_by_id(db, character_stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail="阶段不存在")

    if not voice_description or not voice_description.strip():
        raise HTTPException(status_code=400, detail="声音描述不能为空")

    for task in VOICE_TASKS.values():
        if task["status"] in ("queued", "processing"):
            raise HTTPException(status_code=409, detail="已有音声生成任务进行中，请稍后再试")

    task_id = uuid.uuid4().hex[:16]
    VOICE_TASKS[task_id] = {"status": "queued", "stage_id": character_stage_id, "error": None}
    asyncio.get_running_loop().create_task(
        _run_voice_task(task_id, character_stage_id, voice_description.strip())
    )

    return {"data": {"TaskId": task_id, "Resp": "音色生成任务已创建"}}


@router.get("/voicegenerating")
async def get_voice_generating_status():
    """查询当前音色生成任务状态（前端轮询）。
    Status 区分 queued（GPU 闸排队中）/ processing（推理中）；Queue 是闸上
    快照计数（transient 在跑 / waiting 排队），供前端显示「前方还有 N 个」。"""
    queue = gpu_gate.stats()
    current = next(
        (t for t in VOICE_TASKS.values() if t["status"] in ("queued", "processing")),
        None,
    )
    if current:
        return {"data": {
            "Generating": True, "StageId": current["stage_id"],
            "Status": current["status"], "Error": None, "Queue": queue,
        }}

    last_done = next(
        (t for t in reversed(list(VOICE_TASKS.values())) if t["status"] in ("done", "error")),
        None,
    )
    return {
        "data": {
            "Generating": False,
            "StageId": last_done["stage_id"] if last_done else None,
            "Status": None,
            "Error": last_done["error"] if last_done else None,
            "Queue": queue,
        }
    }


@router.get("/voice/{character_stage_id}")
async def get_stage_voice_file(
        character_stage_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    """流式返回阶段参考音频（供前端 <audio> 播放）"""
    stage = await CharacterStage.get_character_stage_by_id(db, character_stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail="阶段不存在")

    if not stage.voice_path:
        raise HTTPException(status_code=404, detail="该阶段尚未生成参考音频")

    file_path = FilePath(stage.voice_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在")

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type=mimetypes.guess_type(file_path.name)[0] or "audio/wav",
    )


@router.delete("/voice/{character_stage_id}")
async def delete_stage_voice(
        character_stage_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    """删除阶段参考音频（清空描述与路径，并删除音频目录）"""
    stage = await CharacterStage.get_character_stage_by_id(db, character_stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail="阶段不存在")

    if not stage.voice_path:
        raise HTTPException(status_code=404, detail="该阶段没有参考音频")

    await CharacterStage.update_character_stage(db, character_stage_id, {
        "voice_description": "",
        "voice_path": "",
    })

    # 清理该阶段的音频目录（characterstage_{id}/ 下只有生成的音频）
    await rm_dir(conf.CHARACTER_DIR / f"characterstage_{character_stage_id}")

    return {"data": {"Resp": "参考音频已删除"}}


@router.get("/characterstages")
async def get_character_stages(
        character_id: int = Query(..., description="角色ID"),
        page: int = Query(..., gt=0),
        pagesize: int = Query(10, gt=0),
        db: AsyncSession = Depends(get_db)
):
    """
    获取指定角色下的阶段列表（分页）
    """
    offset = (page - 1) * pagesize
    stages, total = await CharacterStage.get_stages_by_character_paginated(
        db, character_id, offset, pagesize
    )
    has_more = (offset + len(stages)) < total


    stages = [CharacterStageDetail.model_validate(stage) for stage in stages]

    return {
        "data": {
            "List": stages,
            "Total": total,
            "More": has_more
        }
    }


@router.post("/add_characterstage")
async def add_character_stage(
        character_id: int = Query(..., description="所属角色ID"),
        stage: CharacterStageCreate = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """
    创建新角色阶段，并建立与角色的关联
    """
    new_stage = await CharacterStage.add_character_stage_by_model(db, stage)
    await Character.add_character_stage(db, character_id, new_stage.id)

    return {
        "data": {
            "CharacterStage": new_stage,
            "Resp": "创建成功"
        }
    }


@router.get("/{stage_id}")
async def get_character_stage(
        stage_id: int = Path(..., description="阶段ID"),
        db: AsyncSession = Depends(get_db)
):
    """
    获取阶段详情
    """
    stage = await CharacterStage.get_character_stage_by_id(db, stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail="阶段不存在")

    return {
        "data": {
            "CharacterStage": CharacterStageDetail.model_validate(stage)
        }
    }


@router.put("/{stage_id}")
async def update_character_stage(
        stage_id: int = Path(..., description="阶段ID"),
        update_data: Dict[str, Any] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    """
    更新阶段信息（支持部分更新）
    """
    if not update_data:
        raise HTTPException(status_code=400, detail="请求体不能为空")

    updated_stage = await CharacterStage.update_character_stage(db, stage_id, update_data)
    if not updated_stage:
        raise HTTPException(status_code=404, detail="阶段不存在")

    return {
        "data": {
            "CharacterStage": updated_stage,
            "Resp": "更新成功"
        }
    }

@router.delete("/{stage_id}")
async def delete_character_stage(
        stage_id: int = Path(..., description="阶段ID"),
        db: AsyncSession = Depends(get_db)
):
    """
    删除单个阶段，同时清理关联关系
    """
    await Character.remove_character_stage(db, stage_id)
    success = await CharacterStage.delete_character_stage(db, stage_id)
    await rm_characters([stage_id])
    if not success:
        raise HTTPException(status_code=404, detail="阶段不存在或已删除")

    return {
        "data": {
            "Resp": "删除成功"
        }
    }
