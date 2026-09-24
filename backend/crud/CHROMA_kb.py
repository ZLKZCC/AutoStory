import asyncio
from typing import List, Dict, Any, Optional

from config.store import conf
from config import db_conf

# 三库 collection 名与各自 id 字段值的格式（前缀）
COLLECTIONS = {
    "writing": {"name": conf.CHROMA_KB_COLLECTION[0], "id_prefix": "KP", "id_field": "kp_id"},
    "analysis": {"name": conf.CHROMA_KB_COLLECTION[1], "id_prefix": "AN", "id_field": "an_id"},
    "summary": {"name": conf.CHROMA_KB_COLLECTION[2], "id_prefix": "SM", "id_field": "sm_id"},
}


def _get_collection(lib: str):
    """按库代号（writing/analysis/summary）取 collection。

    embedding 模型通过模块属性动态取，避免 from-import 拿到 init_vector 赋值前的 None 快照。
    """
    spec = COLLECTIONS.get(lib)
    if not spec:
        raise ValueError(f"未知知识库代号：{lib}（合法取值：writing/analysis/summary）")
    return db_conf.chroma_kb_client.get_or_create_collection(
        name=spec["name"],
        embedding_function=db_conf._embed_model
    )


# ── 同步底层（executors 内调用） ─────────────────────────────

def _sync_search_keyword(lib: str, query: str, category: Optional[str], top_k: int) -> List[Dict[str, Any]]:
    """关键词检索：对 name/keywords/category 做字面包含匹配。

    三库条目数 ≤200，全量拉 metadatas 内存匹配无性能压力；
    比起依赖 chroma where_document $contains 子串匹配（只能搜 documents），
    内存匹配可同时搜 name/keywords/category 三个字段，更贴合 SKILL 设计。
    """
    collection = _get_collection(lib)
    existing = collection.get(include=["metadatas"])
    metas = existing.get("metadatas") or []
    ids = existing.get("ids") or []

    q = (query or "").strip()
    cat = (category or "").strip() if category else ""
    if not q and not cat:
        return []

    hits: List[Dict[str, Any]] = []
    for doc_id, meta in zip(ids, metas):
        if not meta:
            continue
        # category 过滤先做（一级过滤）
        if cat and meta.get("category", "") != cat:
            continue
        name = meta.get("name", "")
        keywords = meta.get("keywords", "")
        meta_cat = meta.get("category", "")
        # 字面包含匹配（大小写不敏感）
        hay = f"{name} {keywords} {meta_cat}".lower()
        if q and q.lower() in hay:
            hits.append({
                "id": meta.get("id", doc_id),
                "name": name,
                "category": meta_cat,
                "keywords": keywords,
            })
    return hits[:top_k] if top_k > 0 else hits


def _sync_search_semantic(lib: str, query: str, category: Optional[str], top_k: int) -> List[Dict[str, Any]]:
    """语义检索：对 content+examples 做稠密向量召回（chroma 原生 query）。

    documents 字段在导入时已合并 content+examples 全文，向量召回即同时覆盖两区。
    传 category 时用 where 过滤先做一级分类。
    """
    collection = _get_collection(lib)
    where = {"category": category} if category else None
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"]
    )
    out: List[Dict[str, Any]] = []
    for doc_id, doc, meta, dist in zip(
            (results.get("ids") or [[]])[0],
            (results.get("documents") or [[]])[0],
            (results.get("metadatas") or [[]])[0],
            (results.get("distances") or [[]])[0]):
        out.append({
            "id": (meta or {}).get("id", doc_id),
            "name": (meta or {}).get("name", ""),
            "category": (meta or {}).get("category", ""),
            "keywords": (meta or {}).get("keywords", ""),
            "score": max(0.0, 1.0 - dist),
        })
    return out


def _sync_get_by_id(lib: str, kp_id: str) -> Optional[Dict[str, Any]]:
    """按编号整块提取：返回 id/name/category/origin_ref/keywords/related/content/examples 全字段。

    content/examples 已合并存 documents；get_by_id 拆回两段返回。
    """
    collection = _get_collection(lib)
    # ids 用入库时的 kp_id 唯一标识（见 import_kb.py）
    result = collection.get(ids=[kp_id], include=["documents", "metadatas"])
    ids = result.get("ids") or []
    docs = result.get("documents") or []
    metas = result.get("metadatas") or []
    if not ids:
        return None
    doc = docs[0] if docs else ""
    meta = metas[0] or {}
    # 拆回 content + examples（导入时用 "\n\n【案例】\n" 连接）
    parts = doc.split("\n\n【案例】\n", 1)
    content = parts[0] if parts else ""
    examples = parts[1] if len(parts) > 1 else ""
    return {
        "id": meta.get("id", ids[0]),
        "name": meta.get("name", ""),
        "category": meta.get("category", ""),
        "origin_ref": meta.get("origin_ref", ""),
        "keywords": meta.get("keywords", ""),
        "related": meta.get("related", ""),
        "content": content,
        "examples": examples,
    }


def _sync_list_by_category(lib: str, category: str) -> List[Dict[str, Any]]:
    """按分类名列出该分类全部条目清单（仅 id/name/category/keywords，不返回全文）。"""
    collection = _get_collection(lib)
    result = collection.get(
        where={"category": category},
        include=["metadatas"]
    )
    out: List[Dict[str, Any]] = []
    for doc_id, meta in zip(result.get("ids") or [], result.get("metadatas") or []):
        if not meta:
            continue
        out.append({
            "id": meta.get("id", doc_id),
            "name": meta.get("name", ""),
            "category": meta.get("category", ""),
            "keywords": meta.get("keywords", ""),
        })
    return out


def _sync_count(lib: str) -> int:
    """库内条目数（导入脚本验证用）"""
    return _get_collection(lib).count()


# ── 异步入口（runtime 调用） ──────────────────────────────

async def search_keyword(lib: str, query: str, category: Optional[str] = None, top_k: int = 10) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_search_keyword, lib, query, category, top_k)


async def search_semantic(lib: str, query: str, category: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_search_semantic, lib, query, category, top_k)


async def get_by_id(lib: str, kp_id: str) -> Optional[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_get_by_id, lib, kp_id)


async def list_by_category(lib: str, category: str) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_list_by_category, lib, category)


async def count(lib: str) -> int:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_count, lib)
