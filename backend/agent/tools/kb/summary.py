from typing import Optional

from langchain_core.tools import tool

from crud.CHROMA_kb import search_keyword, search_semantic, get_by_id, list_by_category

LIB = "summary"


@tool(parse_docstring=True)
async def sm_search_keyword(query: str, category: Optional[str] = None, top_k: int = 10) -> str:
    """关键词检索：在 name/keywords/category 三个字段做字面包含匹配。知道精确卡点词（"纪要""抽取式""防幻觉"）时用。

    Args:
        query: 关键词，如"纪要""抽取式""防幻觉"
        category: 可选分类名先过滤再匹配
        top_k: 返回的最大条目数，默认 10

    Returns:
        命中条目清单（sm_id + name + category + keywords），无命中返回"（无命中）"
    """
    hits = await search_keyword(LIB, query, category, top_k)
    if not hits:
        return "（无命中）"
    lines = [f"[{h['id']}] {h['name']}｜{h['category']}｜{h['keywords']}" for h in hits]
    return "\n".join(lines)


@tool(parse_docstring=True)
async def sm_search_semantic(query: str, category: Optional[str] = None, top_k: int = 5) -> str:
    """语义检索：对 content+examples 做稠密向量召回。只有模糊问题（"怎么防止总结漏掉关键信息"）时用。

    Args:
        query: 自然语言提问
        category: 可选分类名先过滤再召回
        top_k: 返回的最大条目数，默认 5

    Returns:
        命中条目清单（sm_id + name + category + keywords + score），无命中返回"（无命中）"
    """
    hits = await search_semantic(LIB, query, category, top_k)
    if not hits:
        return "（无命中）"
    lines = [f"[{h['id']}] {h['name']}｜{h['category']}｜{h['keywords']}｜相似度 {h['score']:.2f}" for h in hits]
    return "\n".join(lines)


@tool(parse_docstring=True)
async def sm_get(sm_id: str) -> str:
    """按编号取单条整块：含 content（定义→操作步骤→判据红线→出处）与 examples（总结示范）。编号来自检索结果或 related 字段。

    Args:
        sm_id: 编号 SM-XXX，如"SM-001"

    Returns:
        整块条目（id+name+category+origin_ref+keywords+related+content+examples），无该编号返回"（无此条目）"
    """
    entry = await get_by_id(LIB, sm_id)
    if not entry:
        return "（无此条目）"
    lines = [
        f"编号：{entry['id']}",
        f"名称：{entry['name']}",
        f"所属分类：{entry['category']}",
        f"原笔记编号：{entry['origin_ref']}",
        f"检索关键词：{entry['keywords']}",
        f"关联知识点：{entry['related']}",
        "",
        "【知识内容】",
        entry['content'] or "（空）",
        "",
        "【案例】",
        entry['examples'] or "（无独立案例区）",
    ]
    return "\n".join(lines)


@tool(parse_docstring=True)
async def sm_list_category(category: str) -> str:
    """列出某分类全部条目清单。已知分类要批量取时用。

    Args:
        category: 分类名。合法取值：总纲与总结流程、对话总结、文章总结、场景差异策略、质量与防失真、产出格式模板

    Returns:
        条目清单（id+name+keywords），无该分类或分类为空返回"（无此分类或分类为空）"
    """

    entries = await list_by_category(LIB, category)
    if not entries:
        return "（无此分类或分类为空）"
    lines = [f"[{e['id']}] {e['name']}｜{e['keywords']}" for e in entries]
    return "\n".join(lines)


TOOLS = [sm_search_keyword, sm_search_semantic, sm_get, sm_list_category]

DISPLAY = {
    "sm_search_keyword": "总结库-关键词检索",
    "sm_search_semantic": "总结库-语义检索",
    "sm_get": "总结库-取条目",
    "sm_list_category": "总结库-列分类",
}
