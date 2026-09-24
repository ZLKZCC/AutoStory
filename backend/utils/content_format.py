import re
import json
import html as _html
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ── 世界线可视化默认值（与前端 WorkbenchCanvas.loadWorldlines 的兜底一致，
#    保证落库数据与前端首次渲染呈现相同，避免二次跳变）──
DEFAULT_NODE_COLOR = "#f59e0b"
DEFAULT_TEXT_COLOR = "#3d2e24"
DEFAULT_FONT_SIZE = 14
DEFAULT_FONT_WEIGHT = "600"
DEFAULT_FONT_STYLE = "normal"
DEFAULT_ARROW_TYPE = "unidirectional-right"
_NODE_X_GAP = 240
_NODE_Y_GAP = 150

# 行内标记：先转义正文，再套标签（标签是转义后插入的字面量，不会被二次转义）
_INLINE_RULES = [
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)"), r"<em>\1</em>"),
    (re.compile(r"~~(.+?)~~"), r"<s>\1</s>"),
    (re.compile(r"`([^`\n]+?)`"), r"<code>\1</code>"),
]

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_UL_RE = re.compile(r"^[-*+]\s+")
_OL_RE = re.compile(r"^\d+[.)]\s+")


def _inline(text: str) -> str:
    """行内文本 → HTML：转义特殊字符后套用粗体/斜体/删除线/行内码。"""
    esc = _html.escape(text, quote=False)
    for pat, repl in _INLINE_RULES:
        esc = pat.sub(repl, esc)
    return esc


def to_tiptap_html(text: str) -> str:
    """纯文本 / markdown → TipTap 富文本 HTML。

    支持：# ~ ### 标题、- * + 无序列表、1. 有序列表、> 引用、空行分段、
    行内 **粗体** *斜体* ~~删除~~ `码`；段内单换行转 <br> 软换行。
    已是 HTML（去空白后以 < 开头）则原样透传，避免二次包裹。
    """
    if not text or not text.strip():
        return ""
    if text.strip().startswith("<"):
        return text

    blocks: List[str] = []
    para: List[str] = []

    def flush_para() -> None:
        if para:
            blocks.append("<p>" + "<br>".join(_inline(x) for x in para) + "</p>")
            para.clear()

    lines = text.split("\n")
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if not s:
            flush_para()
            i += 1
            continue

        m = _HEADING_RE.match(s)
        if m:
            flush_para()
            level = len(m.group(1))
            blocks.append(f"<h{level}>" + _inline(m.group(2)) + f"</h{level}>")
            i += 1
            continue

        if s.startswith(">"):
            flush_para()
            quote: List[str] = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^>\s?", "", lines[i].strip()))
                i += 1
            body = "<br>".join(_inline(q) for q in quote)
            blocks.append(f"<blockquote><p>{body}</p></blockquote>")
            continue

        if _UL_RE.match(s):
            flush_para()
            items: List[str] = []
            while i < n and _UL_RE.match(lines[i].strip()):
                items.append(_UL_RE.sub("", lines[i].strip(), count=1))
                i += 1
            lis = "".join(f"<li><p>{_inline(it)}</p></li>" for it in items)
            blocks.append(f"<ul>{lis}</ul>")
            continue

        if _OL_RE.match(s):
            flush_para()
            items = []
            while i < n and _OL_RE.match(lines[i].strip()):
                items.append(_OL_RE.sub("", lines[i].strip(), count=1))
                i += 1
            lis = "".join(f"<li><p>{_inline(it)}</p></li>" for it in items)
            blocks.append(f"<ol>{lis}</ol>")
            continue

        para.append(s)
        i += 1

    flush_para()
    return "".join(blocks)


def strip_html(markup: str) -> str:
    """HTML → 纯文本（用于向量化 / 摘要，避免标签污染 embedding）。"""
    if not markup:
        return ""
    txt = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", markup, flags=re.I)
    txt = re.sub(r"<br\s*/?>", "\n", txt, flags=re.I)
    txt = re.sub(r"<li[^>]*>", "· ", txt, flags=re.I)
    txt = re.sub(r"</(p|h[1-6]|li|blockquote|div|tr)>", "\n", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = _html.unescape(txt)
    txt = re.sub(r"[ \t]{2,}", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def content_to_html(raw: str) -> tuple[str, str]:
    """写入工具的正文规范化：返回 (落库用 HTML, 向量化/摘要用纯文本)。

    agent 通常产纯文本/markdown → 转 HTML 落库，纯文本原样用于向量/摘要；
    若 agent 直接产 HTML → 原样落库，剥标签得纯文本用于向量/摘要。
    """
    raw = raw or ""
    html_text = to_tiptap_html(raw)
    plain = raw if not raw.strip().startswith("<") else strip_html(raw)
    return html_text, plain


def build_outline_data(text: str) -> Dict[str, Any]:
    """大纲正文（文本/markdown）→ OutlineData。

    前端优先渲染 outline_html；global_notes 存原始纯文本作降级来源；sections 留空
    （前端按 outline_html 呈现，用户后续在编辑器内的改动会自行补 sections/outline_html）。
    """
    text = text or ""
    return {
        "sections": [],
        "global_notes": text if not text.strip().startswith("<") else strip_html(text),
        "outline_html": to_tiptap_html(text),
    }


def _layout_nodes(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
    """按关系分层自动布局（就地写 x/y）：左→右按最长路径分层，同层竖向居中。

    无关系的孤立节点各占一层；成环 / 不可达节点回退按序号分层，避免全部叠在原点。
    """
    if not nodes:
        return
    idx = {nd["id"]: i for i, nd in enumerate(nodes)}
    adj: List[List[int]] = [[] for _ in nodes]
    indeg = [0] * len(nodes)
    for e in edges:
        a, b = idx.get(e["from"]), idx.get(e["to"])
        if a is None or b is None or a == b:
            continue
        adj[a].append(b)
        indeg[b] += 1

    layer = [0] * len(nodes)
    work = indeg[:]
    q = deque(i for i in range(len(nodes)) if work[i] == 0)
    visited = set()
    while q:
        u = q.popleft()
        visited.add(u)
        for v in adj[u]:
            if layer[v] < layer[u] + 1:
                layer[v] = layer[u] + 1
            work[v] -= 1
            if work[v] == 0:
                q.append(v)
    # 环中未被拓扑访问到的节点：按序号给层，保证不重叠
    for i in range(len(nodes)):
        if i not in visited:
            layer[i] = i

    by_layer: Dict[int, List[int]] = {}
    for i in range(len(nodes)):
        by_layer.setdefault(layer[i], []).append(i)
    for layer_no, members in by_layer.items():
        mid = (len(members) - 1) / 2
        for row, ni in enumerate(members):
            nodes[ni]["x"] = layer_no * _NODE_X_GAP
            nodes[ni]["y"] = round((row - mid) * _NODE_Y_GAP, 2)


def build_worldline_data(spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """世界线语义结构 → WorldlineData（单条主线，自动补 id / 坐标 / 默认样式 / 时间戳）。

    spec 期望形态（agent 只需产语义，可视化字段可全缺省）：
      {
        "name": 世界线名(可选),
        "description": 描述(可选),
        "nodes": [{"id"?, "title", "description"?}, ...],
        "edges": [{"from", "to", "label"?, "arrowType"?}, ...]
      }
    edges 的 from/to 可用节点 id、节点标题、或节点序号（1 基/0 基）引用；悬空 / 自环边丢弃。
    """
    spec = spec or {}
    raw_nodes = spec.get("nodes") or []
    raw_edges = spec.get("edges") or []

    nodes: List[Dict[str, Any]] = []
    ref: Dict[str, str] = {}   # 端点引用（原始id/标题/序号）→ 规范 id
    taken: set = set()
    for i, nd in enumerate(raw_nodes):
        nd = nd or {}
        raw_id = nd.get("id")
        nid = str(raw_id).strip() if raw_id else f"node-{i + 1}"
        base, k = nid, 1
        while nid in taken:
            k += 1
            nid = f"{base}-{k}"
        taken.add(nid)
        title = str(nd.get("title") or f"节点 {i + 1}")
        nodes.append({
            "id": nid,
            "title": title,
            "description": str(nd.get("description") or ""),
            "color": nd.get("color") or DEFAULT_NODE_COLOR,
            "textColor": nd.get("textColor") or DEFAULT_TEXT_COLOR,
            "fontSize": nd.get("fontSize") or DEFAULT_FONT_SIZE,
            "fontWeight": nd.get("fontWeight") or DEFAULT_FONT_WEIGHT,
            "fontStyle": nd.get("fontStyle") or DEFAULT_FONT_STYLE,
            "x": 0,
            "y": 0,
        })
        if raw_id:
            ref.setdefault(str(raw_id).strip(), nid)
        ref.setdefault(title, nid)
        ref.setdefault(str(i + 1), nid)
        ref.setdefault(str(i), nid)
        ref.setdefault(nid, nid)

    edges: List[Dict[str, Any]] = []
    edge_ids: set = set()
    for i, e in enumerate(raw_edges):
        e = e or {}
        frm = ref.get(str(e.get("from", "")).strip())
        to = ref.get(str(e.get("to", "")).strip())
        if not frm or not to or frm == to:
            continue   # 悬空 / 自环边丢弃（前端持久化时也会过滤）
        eid = str(e.get("id")).strip() if e.get("id") else f"edge-{i + 1}"
        base, k = eid, 1
        while eid in edge_ids:
            k += 1
            eid = f"{base}-{k}"
        edge_ids.add(eid)
        edges.append({
            "id": eid,
            "from": frm,
            "to": to,
            "label": str(e.get("label") or ""),
            "arrowType": e.get("arrowType") or DEFAULT_ARROW_TYPE,
        })

    _layout_nodes(nodes, edges)

    now = datetime.now(timezone.utc).isoformat()
    worldline = {
        "id": "wl_main",
        "name": spec.get("name") or "主线",
        "description": spec.get("description") or "",
        "parent_branch": None,
        "branch_point_chapter": None,
        "chapters": [],
        "created_at": now,
        "updated_at": now,
        "nodes": nodes,
        "edges": edges,
    }
    return {"worldlines": [worldline], "active": "wl_main"}


# 箭头形态（与前端世界线可视化的 arrowType 一致）
_ARROW_TEXT = {
    "unidirectional-right": "-->",
    "unidirectional-left": "<--",
    "bidirectional": "<-->",
    "undirected": "---",
}


def outline_to_text(concept: Any) -> str:
    """OutlineData → 纯文本/markdown（供 agent 读现状，剥离 outline_html 标签）。

    优先 outline_html 剥标签；否则拼 global_notes + sections（标题作 ## 小标题）。
    历史遗留的自由 dict（非 OutlineData 形态）回退 JSON 原文，避免读不出。
    """
    if not concept:
        return "（未设置大纲）"
    if isinstance(concept, dict):
        # 非 OutlineData 形态（历史遗留的自由 dict，如 {主线,核心冲突,分卷}）→ JSON 原文兜底，不丢内容
        if not any(k in concept for k in ("outline_html", "global_notes", "sections")):
            return json.dumps(concept, ensure_ascii=False)
        html_text = concept.get("outline_html")
        if html_text:
            txt = strip_html(html_text)
            if txt:
                return txt
        parts: List[str] = []
        if concept.get("global_notes"):
            parts.append(str(concept["global_notes"]))
        for s in concept.get("sections") or []:
            if not isinstance(s, dict):
                continue
            title = s.get("title")
            content = s.get("content") or ""
            if title:
                parts.append(f"## {title}")
            if content:
                parts.append(
                    strip_html(content) if str(content).strip().startswith("<") else str(content)
                )
        if parts:
            return "\n\n".join(parts)
        return "（大纲为空）"
    return json.dumps(concept, ensure_ascii=False)


def worldline_to_text(wl_data: Any) -> str:
    """WorldlineData → 语义文本摘要（节点清单 + 关系清单，不含坐标/配色，供 agent 读现状）。

    历史遗留的自由 dict（非 WorldlineData 形态）回退 JSON 原文。
    """
    if not wl_data:
        return "（未设置世界线）"
    worldlines = wl_data.get("worldlines") if isinstance(wl_data, dict) else None
    if not worldlines:
        return json.dumps(wl_data, ensure_ascii=False)

    blocks: List[str] = []
    for wl in worldlines:
        if not isinstance(wl, dict):
            continue
        name = wl.get("name") or "主线"
        nodes = wl.get("nodes") or []
        edges = wl.get("edges") or []
        lines = [f"[世界线: {name}]"]
        if wl.get("description"):
            lines.append(f"描述: {wl['description']}")
        if not nodes:
            lines.append("(空)")
            blocks.append("\n".join(lines))
            continue
        id_to_idx = {nd.get("id"): i + 1 for i, nd in enumerate(nodes) if isinstance(nd, dict)}
        lines.append("")
        lines.append("## 节点")
        for i, nd in enumerate(nodes, 1):
            if not isinstance(nd, dict):
                continue
            title = str(nd.get("title") or "").strip()
            desc = str(nd.get("description") or "").strip()
            lines.append(f"({i}) {title} | {desc}" if desc else f"({i}) {title}")
        if edges:
            lines.append("")
            lines.append("## 关系")
            for e in edges:
                if not isinstance(e, dict):
                    continue
                fi = id_to_idx.get(e.get("from"), "?")
                ti = id_to_idx.get(e.get("to"), "?")
                label = str(e.get("label") or "").strip()
                arrow = _ARROW_TEXT.get(e.get("arrowType") or "unidirectional-right", "-->")
                lines.append(
                    f"({fi}) --[{label}]{arrow} ({ti})" if label else f"({fi}) {arrow} ({ti})"
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "（未设置世界线）"
