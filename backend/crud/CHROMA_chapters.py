import re
import asyncio
from config.store import conf
from typing import List, Dict, Any
from config import db_conf
from config.db_conf import chroma_client

COLLECTION_NAME = conf.CHROMA_COLLECTION[0]

def _sync_add_chapter_segments(
        project_id: str,
        chapter_id: str,
        contents: List[str],
        segment_indices: List[int]
):
    """
    同步方法：批量插入章节片段
    """
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=db_conf._embed_model
    )

    ids = []
    metadatas = []

    # 构建 ChromaDB 需要的数据格式
    for i, content in enumerate(contents):
        s_idx = segment_indices[i]
        # 拼接唯一ID，格式：projectID_chapterID_segmentIndex
        doc_id = f"{project_id}_{chapter_id}_{s_idx}"

        ids.append(doc_id)
        metadatas.append({
            "project_id": project_id,
            "chapter_id": chapter_id,
            "segment_index": s_idx
        })

    # 执行插入
    collection.add(
        documents=contents,
        metadatas=metadatas,
        ids=ids
    )


def _sync_search_chapter_segments(
        project_id: str,
        query_text: str,
        n_results: int
) -> Dict[str, Any]:
    """
    同步方法：Top-K 相似度查询
    """
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=db_conf._embed_model
    )

    # 执行查询，使用 where 过滤 project_id
    results = collection.query(
        query_texts=[query_text],
        n_results=n_results,
        where={"project_id": project_id}
    )
    return results

def _sync_delete_project_segments(
        project_id: str
):
    """
    同步方法：删除指定项目下的所有片段
    """
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=db_conf._embed_model
    )

    # 利用元数据过滤，删除该 project_id 下的所有数据
    collection.delete(
        where={"project_id": project_id}
    )

def _sync_delete_projects_segments(
        project_ids: List[str]
):
    """
    同步方法：批量删除多个项目下的所有片段
    """
    if not project_ids:
        return

    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=db_conf._embed_model
    )

    # 使用 $in 操作符进行批量删除
    collection.delete(
        where={"project_id": {"$in": project_ids}}
    )

def _sync_delete_chapter_segments(
        chapter_id: str
):
    """
    同步方法：删除指定章节下的所有片段
    """
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=db_conf._embed_model
    )

    # 利用元数据过滤，删除该 chapter_id 下的所有数据
    collection.delete(
        where={"chapter_id": chapter_id}
    )


async def add_chapter_segments(
        project_id: str,
        chapter_id: str,
        contents: List[str],
        segment_indices: List[int]
):
    """
    异步入口：批量插入章节片段

    Args:
        project_id (str): 项目ID
        chapter_id (str): 章节ID
        contents (List[str]): 片段内容列表
        segment_indices (List[int]): 对应的片段索引列表
    """
    if len(contents) != len(segment_indices):
        raise ValueError("内容列表和索引列表长度不一致")

    loop = asyncio.get_event_loop()
    # 按照示例风格，参数依次传入
    await loop.run_in_executor(
        None,
        _sync_add_chapter_segments,
        project_id,
        chapter_id,
        contents,
        segment_indices
    )

async def search_chapter_segments(
        project_id: str,
        query_text: str,
        top_k: int = 5
) -> Dict[str, Any]:
    """
    异步入口：Top-K 相似度查询

    Args:
        project_id (str): 项目ID，用于过滤数据
        query_text (str): 查询文本
        top_k (int): 返回的前 K 个最相似结果

    Returns:
        Dict[str, Any]: 查询结果
    """
    loop = asyncio.get_event_loop()
    # 按照示例风格，参数依次传入
    return await loop.run_in_executor(
        None,
        _sync_search_chapter_segments,
        project_id,
        query_text,
        top_k
    )

async def delete_chapter_segments_by_project(
        project_id: str
):
    """
    异步入口：删除指定项目下的所有片段

    Args:
        project_id (str): 项目ID
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _sync_delete_project_segments,
        project_id
    )

async def delete_chapter_segments_by_projects(
        project_ids: List[str]
):
    """
    异步入口：批量删除多个项目下的所有片段

    Args:
        project_ids (List[str]): 项目ID列表
    """
    if not project_ids:
        return

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _sync_delete_projects_segments,
        project_ids
    )

async def delete_chapter_segments_by_chapter(
        chapter_id: str
):
    """
    异步入口：删除指定章节下的所有片段

    Args:
        chapter_id (str): 章节ID
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _sync_delete_chapter_segments,
        chapter_id
    )


# ── 语义切分与重建（写入侧：保存章节时调用） ──────────────────

def split_chapter_segments(
        text: str,
        min_seg: int = 60,
        max_seg: int = 600,
) -> List[str]:
    """
    章节正文语义切分（同步纯函数，无 IO）：
    空行 → 单换行 → 句号 三级边界；过短片段并入前段、超长块按句贪婪拼接
    """
    if not text or not text.strip():
        return []

    # 一级：空行切块（场景/情节的自然分界）
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]

    # 二级：超长块按单换行预切，仍超长的按句号切
    pieces: List[str] = []
    for block in blocks:
        if len(block) <= max_seg:
            pieces.append(block)
            continue
        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            if len(line) <= max_seg:
                pieces.append(line)
                continue
            # 三级：句号边界贪婪拼接
            buf = ""
            for sent in re.split(r"(?<=[。！？!?])", line):
                if buf and len(buf) + len(sent) > max_seg:
                    pieces.append(buf)
                    buf = sent
                else:
                    buf += sent
            if buf:
                pieces.append(buf)

    # 收尾：过短片段向前并入（保持段序，语义连贯）
    merged: List[str] = []
    for piece in pieces:
        if merged and len(piece) < min_seg:
            merged[-1] = merged[-1] + "\n" + piece
        else:
            merged.append(piece)

    return merged


async def rebuild_chapter_segments(
        project_id: str,
        chapter_id: str,
        chapter_text: str,
) -> int:
    """
    章节向量重建（写入侧唯一入口，幂等）：
    删旧段落 → 切分 → 批量写入。返回段落数（0 = 正文为空，等价清空）

    Args:
        project_id (str): 项目ID
        chapter_id (str): 章节ID
        chapter_text (str): 章节正文全文
    """
    await delete_chapter_segments_by_chapter(chapter_id)
    contents = split_chapter_segments(chapter_text)
    if not contents:
        return 0
    await add_chapter_segments(
        project_id, chapter_id, contents,
        list(range(1, len(contents) + 1)),
    )
    return len(contents)
