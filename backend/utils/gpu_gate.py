import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

_GB = 1024 ** 3

# ── 可调参数（需按真机 GPU 校准；下面给实测/保守默认值）──
SAFETY_FRACTION = 0.98        # 预算 = 总显存 × 此系数（留给系统/显示/碎片/估算误差）
MAX_CONCURRENT = 4            # 硬性并发上限：显存再富余也不超此数（CPU/内存/磁盘/稳定性都有限）
VRAM_TTS = int(4.5 * _GB)     # Qwen3-TTS 单模型占用（base/custom_voice/voice_design 实测各 ~4.2GB；
                              # 合成内部串行两趟、任一时刻只驻一个，故按单模型 + 余量估）
VRAM_EMBED = int(2.5 * _GB)   # bge-m3 常驻占用（init_vector 加载后长期驻留）


class _GpuGate:
    def __init__(self):
        self._budget: int | None = None    # 显存预算（字节）；None=未探测
        self._unlimited = False            # CPU / 无 CUDA / 探测失败 → 不按显存限流（仍受 MAX_CONCURRENT）
        self._committed = 0                # 已放行任务的显存占用累计（含常驻）
        self._transient = 0                # 当前在跑的瞬态任务数（常驻不计入并发名额）
        self._waiting = 0                  # 正在排队等闸的任务数（stats 暴露给前端"排队中"提示）
        self._cond = asyncio.Condition()

    def _ensure_budget(self) -> None:
        """延迟探测显存预算（只探一次）。"""
        if self._budget is not None or self._unlimited:
            return
        try:
            import torch
            if torch.cuda.is_available():
                total = torch.cuda.get_device_properties(0).total_memory
                self._budget = int(total * SAFETY_FRACTION)
                logger.warning(
                    "[gpu_gate] CUDA 总显存 %.1fGB → 预算 %.1fGB，并发上限 %d",
                    total / _GB, self._budget / _GB, MAX_CONCURRENT,
                )
            else:
                self._unlimited = True
                logger.warning("[gpu_gate] 无 CUDA（CPU 推理）→ 不按显存限流，仅受并发上限 %d 约束", MAX_CONCURRENT)
        except Exception as e:
            self._unlimited = True
            logger.warning("[gpu_gate] 显存探测失败（%s）→ 不按显存限流", e)

    def _admit(self, need: int) -> bool:
        """是否可放行一个占用 need 的瞬态任务。"""
        # 安全阀：没有瞬态任务在跑 → 放行这一个（哪怕超预算），保证必需的大任务不被饿死
        if self._transient == 0:
            return True
        if self._transient >= MAX_CONCURRENT:
            return False
        if self._unlimited:
            return True
        return self._committed + need <= self._budget

    def would_wait(self, need: int) -> bool:
        """同步预判：现在申请 need 是否要排队（供上层发"排队中"提示）。尽力而为、不精确、不占位。"""
        self._ensure_budget()
        return not self._admit(need)

    async def acquire(self, need: int, permanent: bool = False) -> None:
        self._ensure_budget()
        async with self._cond:
            if not self._admit(need):
                # 需要排队：先登记等待计数再阻塞（finally 归还，获闸/取消都不泄漏）
                self._waiting += 1
                try:
                    await self._cond.wait_for(lambda: self._admit(need))
                finally:
                    self._waiting -= 1
            self._committed += need
            if not permanent:
                self._transient += 1

    async def release(self, need: int) -> None:
        async with self._cond:
            self._committed -= need
            self._transient -= 1
            self._cond.notify_all()

    @asynccontextmanager
    async def reserve(self, need: int):
        """瞬态占用：进入时申请、退出时释放（异常也释放）。用于合成/音色设计等一次性 GPU 任务。"""
        await self.acquire(need)
        try:
            yield
        finally:
            await self.release(need)

    async def reserve_permanent(self, need: int) -> None:
        """常驻占用：申请后不释放、不占瞬态并发名额。用于 bge-m3 这类进程生命周期内长期驻留的模型。"""
        await self.acquire(need, permanent=True)

    def stats(self) -> dict:
        """当前闸门状态（诊断/日志用；GET /autostory/gpu/status 也走这里）。"""
        return {
            "budget_gb": (self._budget / _GB) if self._budget else None,
            "unlimited": self._unlimited,
            "committed_gb": self._committed / _GB,
            "transient": self._transient,
            "waiting": self._waiting,
            "max_concurrent": MAX_CONCURRENT,
        }


# 进程级单例：所有 GPU 推理入口共用这一把闸
gpu_gate = _GpuGate()
