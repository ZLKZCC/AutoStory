import asyncio

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from config.store import conf


class CheckpointStore:
    """checkpoint 持久层单例。"""

    instance = None

    # 清理辅助表名（不同 langgraph-checkpoint-sqlite 版本表名不同，全枚举兜底）
    CLEANUP_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes", "writes")

    def __new__(cls):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        if getattr(self, "initialized", False):
            return                  # 重复 CheckpointStore() 不重建连接与锁
        self.initialized = True
        self.saver = None
        self.context = None
        self.lock = asyncio.Lock()

    async def get(self) -> AsyncSqliteSaver:
        """取 saver（进程级单例，主图与子图共用；首次调用建立连接）。"""
        if self.saver is None:
            async with self.lock:
                if self.saver is None:
                    self.context = AsyncSqliteSaver.from_conn_string(conf.AGENT_URL)
                    self.saver = await self.context.__aenter__()
        return self.saver

    @staticmethod
    def tail_number(thread_id: str) -> int:
        """取 thread_id 尾号（用户消息 record_id）；非数字返回 -1（排序时排最后）。"""
        suffix = thread_id.rsplit("_", 1)[-1]
        return int(suffix) if suffix.isdigit() else -1

    async def delete_thread(self, thread_id: str) -> None:
        """
        删除某 thread 的 checkpoint（单轮正常走完时调用）。

        生命周期约定（2026-09-13 与用户确认）：
        - 单轮正常结束（图跑完、无 interrupt、无异常）→ 删除，不留痕；
        - 中断 / 异常 → 保留，以便后续断点恢复。
        子agent不持久化、不走 checkpoint，与这里无关。
        """
        saver = await self.get()
        # 优先走 saver 原生接口
        try:
            await saver.adelete_thread(thread_id)
            return
        except AttributeError:
            pass
        # 退化：手写 sqlite 删（覆盖不同版本的表名）
        conn = getattr(saver, "conn", None)
        if conn is None:
            return
        for table in self.CLEANUP_TABLES:
            try:
                await conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
            except Exception:
                pass
        await conn.commit()

    async def find_latest_thread(self, project_id: int) -> "str | None":
        """找该项目最新一个"可 continue"的未完成 thread（thread_id 形如 project_{pid}_{record_id}）。

        单轮正常走完会删 checkpoint；人审中断的轮次必须走 /resume（图挂在 interrupt() 上，
        要传用户裁决值），也不能 continue。故只认：有 checkpoint、且 writes 表无 __interrupt__
        挂起记录的 thread——即"被断连/异常取消、停在普通节点"的轮次。没有则返回 None。
        """
        saver = await self.get()
        conn = getattr(saver, "conn", None)
        if conn is None:
            return None
        # LIKE 里 _ 是单字符通配符，显式转义防止 project_11 误配 project_1x
        pattern = f"project_{project_id}\\_%"
        cursor = await conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE ? ESCAPE '\\'",
            (pattern,),
        )
        candidates = [row[0] for row in await cursor.fetchall()]
        # 按尾号（用户消息 record_id）降序逐个检查，第一个"无挂起中断"的即目标
        for thread_id in sorted(candidates, key=self.tail_number, reverse=True):
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM writes WHERE thread_id = ? AND channel = '__interrupt__'",
                (thread_id,),
            )
            (interrupt_count,) = await cursor.fetchone()
            if interrupt_count == 0:
                return thread_id
        return None


checkpoints = CheckpointStore()
