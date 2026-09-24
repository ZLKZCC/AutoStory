"""gpu.py — GPU 闸状态查询（统一排队可见性）

合成有声书 / 角色音色生成 / 旁白试听都过 utils.gpu_gate 这一把闸；本路由
只读闸门快照，供前端在 GPU 类请求等待期间显示「排队中（前方 N 个）」。
"""
from fastapi import APIRouter

from utils.gpu_gate import gpu_gate

router = APIRouter(prefix="/autostory/gpu", tags=["gpu"])


@router.get("/status")
async def gpu_status():
    """当前 GPU 闸快照：transient=在跑瞬态任务数，waiting=排队等闸任务数"""
    return {"data": gpu_gate.stats()}
