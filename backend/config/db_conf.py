import asyncio
import chromadb

from models.Base import Base
import models.Volume  # noqa: F401  注册 volume 表到 Base.metadata（无路由直接引用时也能被 create_all 建出）
from config.store import conf
from utils.embedding import EmbeddingModel
from crud.Userpreference import get_or_create_userpreference
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlalchemy import text

async_engine = create_async_engine(
    conf.ASYNC_DATABASE_URL,
    echo=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

chroma_client = chromadb.PersistentClient(conf.CHROMA_DB_URL)
# 写作/分析/总结三知识库独立 db（与业务库 chapters/knowledges/experience 物理隔离）
chroma_kb_client = chromadb.PersistentClient(conf.CHROMA_KB_DB_URL)

_embed_model = None



async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_database():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 历史遗留列 storyChange_Summary 的幂等清理：
    # 新库 create_all 不建该列；旧库执行删列，失败说明已删或不存在，忽略即可。
    async with async_engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE summary DROP COLUMN storyChange_Summary"))
        except Exception:
            pass

    # 有声书流程状态列的幂等补齐：
    # 项目无迁移机制，已有库 create_all 不会补新列，逐列 ALTER 兜底（失败=已存在，忽略）。
    for col, ddl in (
        ("status", "VARCHAR(32) DEFAULT 'draft'"),
        ("mapping", "TEXT DEFAULT ''"),
        ("narrator_desc", "TEXT DEFAULT ''"),
        ("audio_ids", "TEXT DEFAULT ''"),
        ("stage_payload", "TEXT DEFAULT ''"),
        ("runner", "VARCHAR(16) DEFAULT 'graph'"),
        ("error", "TEXT DEFAULT ''"),
    ):
        async with async_engine.begin() as conn:
            try:
                await conn.execute(text(f"ALTER TABLE audiobookscript ADD COLUMN {col} {ddl}"))
            except Exception:
                pass

    # userpreference 为单例表：建表后确保默认记录存在
    async with AsyncSessionLocal() as session:
        await get_or_create_userpreference(session)

async def init_vector():
    global _embed_model
    try:
        _embed_model = EmbeddingModel(model_path=conf.VECTOR_MODEL_DIR)
        # bge-m3 常驻显存：一次性计入全局 GPU 闸预算、长期不释放（不占瞬态并发名额），
        # 后续 TTS 合成/音色设计申请时预算已扣除这块常驻，不会高估可用显存
        from utils.gpu_gate import gpu_gate, VRAM_EMBED
        await gpu_gate.reserve_permanent(VRAM_EMBED)
        loop = asyncio.get_event_loop()
        tasks = []
        for db_name in conf.CHROMA_COLLECTION:
            tasks.append(loop.run_in_executor(None,chroma_client.get_or_create_collection,db_name,None,None,None,_embed_model))
        # 三知识库 collection（kb.db 内）共享同一 bge-m3 嵌入模型
        for kb_name in conf.CHROMA_KB_COLLECTION:
            tasks.append(loop.run_in_executor(None,chroma_kb_client.get_or_create_collection,kb_name,None,None,None,_embed_model))
        await asyncio.gather(*tasks)
    except Exception as e:
        print(e)
        print("chromadb初始化失败")
