"""研究域：项目素材 / 全局素材库 / 写作经验 / 联网搜索 / 网页深读（全读，无写入）

素材与知识是同一域：material(SQL 素材库容器) → knowledges(Chroma 内容切片向量)；
Projectknowledge(SQL) 是用户为某个项目手挂的素材引用（内容原文快照）。
"""
import asyncio
import re
from typing import Optional, Literal, List

import httpx
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from config.db_conf import AsyncSessionLocal
from crud.Material import get_materials_paginated
from crud.Project import get_project_knowledges
from crud.CHROMA_knowledges import (
    search_knowledge_segments,
    get_knowledge_stats,
    list_knowledge_documents,
)

from agent.tools.common import current_project


# web_search 的时效参数 → DuckDuckGo 的 time 取值（None = 不限）
TIME_RANGE_MAP = {"any": None, "day": "d", "week": "w", "month": "m", "year": "y"}


@tool(parse_docstring=True)
async def get_project_materials(config: RunnableConfig) -> str:
    """取用户为当前项目挂载的素材原文（前端素材面板手挂的引用，属用户指定，优先级最高）。
    定设定/写作前先查这条：这是用户特意为本项目挑的资料，比全库检索更贴合当前作品。

    Args:


    Returns:
        项目挂载素材的原文清单（每条截断展示）；未挂载任何素材时返回提示语。
    """
    project_id = current_project(config)
    async with AsyncSessionLocal() as db:
        refs = await get_project_knowledges(db, project_id)
    if not refs:
        return "本项目未挂载素材"
    blocks = []
    for i, r in enumerate(refs, 1):
        text = (r.knowledge or "").strip()
        blocks.append(f"【用户指定 {i}】{text[:800]}")
    return "\n\n".join(blocks)


@tool(parse_docstring=True)
async def list_material_libraries() -> str:
    """列出全局素材库地图（每个库的名称/描述/文档清单/切片数）。
    不确定有哪些素材、或想按某个库/某篇文档精准检索时，先用这条看清结构，再用 search_materials 缩小范围。

    Args:


    Returns:
        每个素材库的 id、名称、描述、切片总数、文档数与库内文档名清单；尚无素材库时返回提示语。
    """
    async with AsyncSessionLocal() as db:
        mats, total = await get_materials_paginated(db, offset=0, limit=200)
    if not mats:
        return "尚无素材库"
    stats = await get_knowledge_stats()
    lines = [f"共 {total} 个素材库："]
    for m in mats:
        st = stats.get(m.id, {})
        lines.append(
            f"\n· [id={m.id}] {m.material_name}"
            f"（切片 {st.get('chunk_count', 0)} / 文档 {st.get('knowledge_count', 0)}）"
        )
        if m.description:
            lines.append(f"  描述：{m.description}")
        # 文档名清单（按切片数倒序）：供 search_materials 的 knowledge_name 精准过滤
        docs = await list_knowledge_documents(m.id)
        if docs:
            names = "、".join(
                f"{d['knowledge_name']}({d['chunk_count']})" for d in docs[:30]
            )
            lines.append(f"  文档：{names}")
    return "\n".join(lines)


@tool(parse_docstring=True)
async def search_materials(
    queries: List[str],
    top_k: int = 5,
    material_id: Optional[int] = None,
    knowledge_name: Optional[str] = None,
) -> str:
    """在全局素材库中语义检索内容切片（设定集/资料/范文）。需要查设定细节或参考资料时用。
    支持一次给多个不同角度的 query（结果自动合并去重）；可先 list_material_libraries 看清结构，
    再用 material_id / knowledge_name 精准缩小范围，也可都不传做全库盲搜。

    Args:
        queries: 检索语句列表,可一次给多个不同角度的query,结果合并去重
        top_k: 命中条数,默认5
        material_id: 素材库id,可选,限定在某素材库内检索,为空则全库
        knowledge_name: 素材名(文档名),可选,限定在某篇文档内检索,为空则不限

    Returns:
        命中的素材片段列表（来源库/文档 + 相关度 + 正文摘要），无命中时返回提示语。
    """
    qs = [q for q in (queries or []) if q and q.strip()]
    if not qs:
        return "（未提供检索语句）"
    results = await search_knowledge_segments(
        query_texts=qs, material_id=material_id, knowledge_name=knowledge_name,
        top_k=top_k * 2, page=1, page_size=top_k,
    )
    rows = results.get("List", [])
    if not rows:
        return "素材库无命中"
    lines = []
    for r in rows[:top_k]:
        src = f"{r.get('material_name', '')}/{r.get('knowledge_name', '')}"
        score = r.get("score")
        score_str = f"（相关度 {score:.2f}）" if isinstance(score, (int, float)) else ""
        lines.append(f"[{src}]{score_str} {r.get('content', '')[:300]}")
    return "\n\n".join(lines)


def query_experience_sync(query: str, top_k: int) -> dict:
    """经验库的同步查询实现（Chroma 属阻塞 IO，交给 run_in_executor 执行）。"""
    from config.db_conf import chroma_client, _embed_model

    collection = chroma_client.get_or_create_collection(
        "experience", embedding_function=_embed_model
    )
    return collection.query(query_texts=[query], n_results=top_k)


@tool(parse_docstring=True)
async def search_experience(query: str, top_k: int = 5) -> str:
    """检索历史写作经验（用户偏好、改稿记录、文风要点）。
    派写作任务定文风前优先查这条拿用户偏好；写前查「用户之前嫌弃过什么写法」也用。

    Args:
        query: 检索语句
        top_k: 经验条数,默认5

    Returns:
        命中的写作经验片段列表（doc_id + 元信息 + 正文），无命中返回「（无命中）」。
    """
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, query_experience_sync, query, top_k)
    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]
    lines = []
    for doc_id, doc, meta, dist in zip(ids, docs, metas, dists):
        meta_str = "，".join(f"{k}={v}" for k, v in (meta or {}).items())
        lines.append(f"[{doc_id}] {meta_str}\n{doc}")
    return "\n\n".join(lines[:top_k]) or "（无命中）"


@tool(parse_docstring=True)
async def web_search(
    query: str,
    max_results: int = 5,
    time_range: Literal["any", "day", "week", "month", "year"] = "any",
    region: str = "wt-wt",
) -> str:
    """联网搜索写作资料：历史年代细节、地理常识、职业工作方式、物品价格等。
    派活前需要查外部资料时用。返回若干条「标题: 摘要」。需要深入某个结果时用 web_fetch。

    Args:
        query: 检索语句
        max_results: 条数,默认5,过多会干扰判断
        time_range: 时效 any/day/week/month/year,默认 any
        region: 区域,默认 wt-wt(全球);中文资料可用 cn-zh

    Returns:
        若干「标题: 摘要」;搜索不可用时返回失败提示。
    """
    from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

    try:
        wrapper = DuckDuckGoSearchAPIWrapper(
            region=region, time=TIME_RANGE_MAP.get(time_range),
            max_results=max_results, source="text",
        )
        results = wrapper.results(query, max_results=max_results, source="text")
        if not results:
            return "（无搜索结果）"
        lines = [
            f"· {r.get('title', '')}: {r.get('snippet', '')[:200]}\n  {r.get('link', '')}"
            for r in results[:max_results]
        ]
        return "\n\n".join(lines)[:2000]
    except Exception as e:
        return (
            f"搜索暂不可用（{type(e).__name__}）。"
            "请告知用户联网搜索失败，或基于已有知识谨慎作答并注明未查证。"
        )


@tool(parse_docstring=True)
async def web_fetch(url: str) -> str:
    """抓取网页正文。拿到搜索结果的链接后需要读全文细节时用。
    返回剥离标签的正文文本（截断 6000 字）。

    Args:
        url: 要抓取的网页完整 URL

    Returns:
        剥离脚本、样式、块级标签后的正文纯文本,最多 6000 字;失败返回提示。
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            resp.raise_for_status()
    except Exception as e:
        return f"抓取失败: {type(e).__name__}: {e}"

    ctype = resp.headers.get("content-type", "")
    if "text/html" not in ctype and "text/plain" not in ctype:
        return f"（该 URL 返回 {ctype or '未知类型'}，非网页正文，建议换用其他来源）"

    html = resp.text
    html = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=re.I)
    html = re.sub(r"<(p|div|br|li|h[1-6])[^>]*>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text[:6000] or "（页面无可提取正文，可能是纯脚本渲染页）"


TOOLS = [get_project_materials, list_material_libraries, search_materials, search_experience, web_search, web_fetch]

DISPLAY = {
    "get_project_materials": "查项目素材",
    "list_material_libraries": "列素材库",
    "search_materials": "检索素材库",
    "search_experience": "检索写作经验",
    "web_search": "联网搜索",
    "web_fetch": "网页深读",
}
