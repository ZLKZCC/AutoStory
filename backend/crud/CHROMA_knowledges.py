import asyncio
from typing import List, Dict, Any, Optional, Union
from config.store import conf
from config import db_conf

COLLECTION_NAME = conf.CHROMA_COLLECTION[1]

def _get_collection():
    """
    获取素材库向量集合（embedding 模型通过模块属性动态取，
    避免 from-import 拿到 init_vector 赋值前的 None 快照）
    """
    return db_conf.chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=db_conf._embed_model
    )

def _sync_get_next_chunk_id(
        material_id: int,
        knowledge_name: str
) -> int:
    """
    同步方法：查询素材（素材库id + 素材名）下的下一个可用 chunk_id
    """
    collection = _get_collection()

    existing = collection.get(
        where={
            "$and": [
                {"material_id": material_id},
                {"knowledge_name": knowledge_name}
            ]
        },
        include=["metadatas"]
    )

    # 取已有最大 chunk_id 续号，保证删除部分片段后重新插入也不会产生重复
    existing_metas = existing.get("metadatas") or []
    return max(
        (meta["chunk_id"] for meta in existing_metas if meta),
        default=-1
    ) + 1

def _sync_add_knowledge_segments(
        material_id: int,
        material_name: str,
        knowledge_name: str,
        contents: List[str],
        start_chunk_id: Optional[int] = None
):
    """
    同步方法：批量插入知识片段，chunk_id 自动续号；
    start_chunk_id 用于导入任务分批写入时免重复查询起始编号
    """
    collection = _get_collection()

    # 未指定起始编号时自查最大 chunk_id 续号
    next_chunk_id = (
        start_chunk_id
        if start_chunk_id is not None
        else _sync_get_next_chunk_id(material_id, knowledge_name)
    )

    ids = []
    metadatas = []

    # 构建 ChromaDB 需要的数据格式
    for content in contents:
        # 拼接唯一ID，格式：素材库id_素材名_chunkid
        ids.append(f"{material_id}_{knowledge_name}_{next_chunk_id}")
        metadatas.append({
            "material_id": material_id,
            "material_name": material_name,
            "knowledge_name": knowledge_name,
            "chunk_id": next_chunk_id
        })
        next_chunk_id += 1

    # 大批量分批入库，控制单次事务规模，embedding 批推理与 sqlite 写入都更平滑
    BATCH_SIZE = 500
    for i in range(0, len(contents), BATCH_SIZE):
        collection.add(
            documents=contents[i:i + BATCH_SIZE],
            metadatas=metadatas[i:i + BATCH_SIZE],
            ids=ids[i:i + BATCH_SIZE]
        )

def _sync_search_knowledge_segments(
        query_texts: List[str],
        material_id: Optional[int],
        knowledge_name: Optional[str],
        top_k: int,
        page: int,
        page_size: int
) -> Dict[str, Any]:
    """
    同步方法：语义匹配查询，多 query 结果合并去重，返回完整切片信息
    """
    # 空 query 列表不触发底层 embedding 计算，直接返回空结果
    if not query_texts:
        return {"List": [], "Total": 0}

    collection = _get_collection()

    # 组合过滤条件（素材库id / 素材名），全部为与关系；无条件则全库检索
    conditions = []
    if material_id is not None:
        conditions.append({"material_id": material_id})
    if knowledge_name is not None:
        conditions.append({"knowledge_name": knowledge_name})
    if not conditions:
        where = None
    elif len(conditions) == 1:
        where = conditions[0]
    else:
        where = {"$and": conditions}

    # 多 query 合并为一次调用：Chroma 原生支持批量查询，结果按 query 分组返回
    results = collection.query(
        query_texts=query_texts,
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"]
    )

    # 合并各组结果：按 doc_id 去重，保留最小距离（最相似的一次命中）
    merged: Dict[str, Dict[str, Any]] = {}
    for group_ids, group_docs, group_metas, group_dists in zip(
            results.get("ids") or [],
            results.get("documents") or [],
            results.get("metadatas") or [],
            results.get("distances") or []):
        for doc_id, doc, meta, dist in zip(group_ids, group_docs, group_metas, group_dists):
            if doc_id not in merged or dist < merged[doc_id]["distance"]:
                merged[doc_id] = {
                    "id": doc_id,
                    "content": doc,
                    "distance": dist,
                    "metadata": meta or {}
                }

    # 按距离升序排序（越相似越靠前），截取 top_k 后再分页
    ranked = sorted(merged.values(), key=lambda item: item["distance"])[:top_k]
    total = len(ranked)
    start = (page - 1) * page_size

    # 距离转相关度（余弦距离 0~2 → score 0~1，越大越相关）
    entries = [
        {
            "id": item["id"],
            "material_id": item["metadata"].get("material_id"),
            "material_name": item["metadata"].get("material_name", ""),
            "knowledge_name": item["metadata"].get("knowledge_name", ""),
            "chunk_id": item["metadata"].get("chunk_id", 0),
            "content": item["content"],
            "score": max(0.0, 1.0 - item["distance"])
        }
        for item in ranked[start:start + page_size]
    ]

    return {"List": entries, "Total": total}

def _sync_get_knowledge_segments(
        material_id: Optional[int],
        knowledge_name: Optional[str],
        chunk_id: Optional[int],
        page: int,
        page_size: int
) -> Dict[str, Any]:
    """
    同步方法：精确查找，素材库id / 素材名 / chunkid 任意组合过滤，返回完整切片信息
    """
    collection = _get_collection()

    # 组合 where 条件，全部为与关系
    conditions = []
    if material_id is not None:
        conditions.append({"material_id": material_id})
    if knowledge_name is not None:
        conditions.append({"knowledge_name": knowledge_name})
    if chunk_id is not None:
        conditions.append({"chunk_id": chunk_id})

    if not conditions:
        where = None
    elif len(conditions) == 1:
        where = conditions[0]
    else:
        where = {"$and": conditions}

    # 总数只数 ids（每条仅一个短字符串），无过滤时 count() 直接读元数据计数
    if where is None:
        total = collection.count()
    else:
        total = len(collection.get(where=where, include=[]).get("ids") or [])

    # 当页数据在库内用 limit/offset 切页，只拉回本页文本，避免全量 documents 进内存
    page_data = collection.get(
        where=where,
        limit=page_size,
        offset=(page - 1) * page_size,
        include=["documents", "metadatas"]
    )

    entries = [
        {
            "id": doc_id,
            "material_id": (meta or {}).get("material_id"),
            "knowledge_name": (meta or {}).get("knowledge_name", ""),
            "chunk_id": (meta or {}).get("chunk_id", 0),
            "content": doc
        }
        for doc_id, doc, meta in zip(
            page_data.get("ids") or [],
            page_data.get("documents") or [],
            page_data.get("metadatas") or [])
    ]

    return {"List": entries, "Total": total}

def _sync_list_knowledge_documents(
        material_id: int
) -> List[Dict[str, Any]]:
    """
    同步方法：素材列表聚合，按素材名分组统计切片数与字数
    """
    collection = _get_collection()

    # 单素材库量级下一次拉全量内存聚合（单用户场景，几千 chunk 约数 MB）
    existing = collection.get(
        where={"material_id": material_id},
        include=["documents", "metadatas"]
    )

    # 按素材名聚合：切片数 + 字数
    stats: Dict[str, Dict[str, Any]] = {}
    for doc, meta in zip(
            existing.get("documents") or [],
            existing.get("metadatas") or []):
        name = (meta or {}).get("knowledge_name", "")
        if name not in stats:
            stats[name] = {
                "id": f"{material_id}_{name}",
                "material_id": material_id,
                "knowledge_name": name,
                "chunk_count": 0,
                "word_count": 0
            }
        stats[name]["chunk_count"] += 1
        stats[name]["word_count"] += len(doc)

    # 按切片数倒序，内容多的素材排前面
    return sorted(stats.values(), key=lambda item: item["chunk_count"], reverse=True)

def _sync_get_knowledge_stats() -> Dict[int, Dict[str, int]]:
    """
    同步方法：全部素材库的向量统计（素材数与切片数），供素材库列表页一次拉取
    """
    collection = _get_collection()

    # 一次拉全库 metadata（不拉文本），内存按 material_id 聚合
    existing = collection.get(include=["metadatas"])

    stats: Dict[int, Dict[str, int]] = {}
    knowledge_names: Dict[int, set] = {}
    for meta in existing.get("metadatas") or []:
        if not meta:
            continue
        mid = meta.get("material_id")
        if mid is None:
            continue
        if mid not in stats:
            stats[mid] = {"chunk_count": 0, "knowledge_count": 0}
            knowledge_names[mid] = set()
        stats[mid]["chunk_count"] += 1
        knowledge_names[mid].add(meta.get("knowledge_name", ""))

    for mid, names in knowledge_names.items():
        stats[mid]["knowledge_count"] = len(names)

    return stats

def _sync_delete_knowledge_segments_by_material(
        material_id: int
):
    """
    同步方法：删除指定素材库下的所有片段
    """
    collection = _get_collection()

    # 利用元数据过滤，删除该 material_id 下的所有数据
    collection.delete(
        where={"material_id": material_id}
    )

def _sync_delete_knowledge_segments_by_knowledge_name(
        material_id: int,
        knowledge_name: str
):
    """
    同步方法：删除指定素材（素材库id + 素材名）下的所有片段
    """
    collection = _get_collection()

    collection.delete(
        where={
            "$and": [
                {"material_id": material_id},
                {"knowledge_name": knowledge_name}
            ]
        }
    )

async def get_next_chunk_id(
        material_id: int,
        knowledge_name: str
) -> int:
    """
    异步入口：查询素材下的下一个可用 chunk_id

    Args:
        material_id (int): 素材库id（material表主键）
        knowledge_name (str): 素材名
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _sync_get_next_chunk_id,
        material_id,
        knowledge_name
    )

async def add_knowledge_segments(
        material_id: int,
        material_name: str,
        knowledge_name: str,
        contents: List[str],
        start_chunk_id: Optional[int] = None
):
    """
    异步入口：批量插入知识片段

    Args:
        material_id (int): 素材库id（material表主键）
        material_name (str): 素材库名（material表material_name）
        knowledge_name (str): 素材名（用户上传时自带）
        contents (List[str]): 片段内容列表，chunk_id 自动生成
        start_chunk_id (Optional[int]): 起始编号，导入任务分批写入时传入免重复查询
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _sync_add_knowledge_segments,
        material_id,
        material_name,
        knowledge_name,
        contents,
        start_chunk_id
    )

async def search_knowledge_segments(
        query_texts: Union[str, List[str]],
        material_id: Optional[int] = None,
        knowledge_name: Optional[str] = None,
        top_k: int = 5,
        page: int = 1,
        page_size: int = 20
) -> Dict[str, Any]:
    """
    异步入口：语义匹配查询，支持多 query 结果合并

    Args:
        query_texts (Union[str, List[str]]): 查询文本，单个或多个
        material_id (Optional[int]): 素材库id，传入则限定在该素材库内搜索
        knowledge_name (Optional[str]): 素材名，传入则限定在该文档内搜索；与 material_id 同时给出为与关系
        top_k (int): 合并去重后保留的最相似结果数量
        page (int): 页码，从 1 开始
        page_size (int): 每页数量

    Returns:
        Dict[str, Any]: {"List": 切片信息列表, "Total": 结果总数}
    """
    if isinstance(query_texts, str):
        query_texts = [query_texts]

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _sync_search_knowledge_segments,
        query_texts,
        material_id,
        knowledge_name,
        top_k,
        page,
        page_size
    )

async def get_knowledge_segments(
        material_id: Optional[int] = None,
        knowledge_name: Optional[str] = None,
        chunk_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20
) -> Dict[str, Any]:
    """
    异步入口：精确查找，条件之间为与关系，chunk_id 需配合素材库id和素材名唯一定位

    Args:
        material_id (Optional[int]): 素材库id
        knowledge_name (Optional[str]): 素材名
        chunk_id (Optional[int]): 片段id
        page (int): 页码，从 1 开始
        page_size (int): 每页数量

    Returns:
        Dict[str, Any]: {"List": 切片信息列表, "Total": 结果总数}
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _sync_get_knowledge_segments,
        material_id,
        knowledge_name,
        chunk_id,
        page,
        page_size
    )

async def list_knowledge_documents(
        material_id: int
) -> List[Dict[str, Any]]:
    """
    异步入口：素材列表聚合（按素材名分组的切片数与字数）

    Args:
        material_id (int): 素材库id

    Returns:
        List[Dict[str, Any]]: [{id, material_id, knowledge_name, chunk_count, word_count}]
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _sync_list_knowledge_documents,
        material_id
    )

async def get_knowledge_stats() -> Dict[int, Dict[str, int]]:
    """
    异步入口：全部素材库的向量统计

    Returns:
        Dict[int, Dict[str, int]]: {素材库id: {chunk_count, knowledge_count}}
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _sync_get_knowledge_stats
    )

async def delete_knowledge_segments_by_material(
        material_id: int
):
    """
    异步入口：删除指定素材库下的所有片段

    Args:
        material_id (int): 素材库id
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _sync_delete_knowledge_segments_by_material,
        material_id
    )

async def delete_knowledge_segments_by_knowledge_name(
        material_id: int,
        knowledge_name: str
):
    """
    异步入口：删除指定素材（素材库id + 素材名）下的所有片段

    Args:
        material_id (int): 素材库id
        knowledge_name (str): 素材名
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _sync_delete_knowledge_segments_by_knowledge_name,
        material_id,
        knowledge_name
    )
