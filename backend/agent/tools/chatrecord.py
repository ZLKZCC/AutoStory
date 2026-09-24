"""agent/tools/chat_search.py — 聊天记忆模糊搜索（AI 自查关键记忆）

独立工具模块，导出 TOOLS / DISPLAY 供工具注册表聚合：
    from agent.tools.chat_search import TOOLS as CHAT_SEARCH_TOOLS
    from agent.tools.chat_search import DISPLAY as CHAT_SEARCH_DISPLAY
    TOOLS.extend(CHAT_SEARCH_TOOLS)
    DISPLAY.update(CHAT_SEARCH_DISPLAY)

依赖：crud/ChatRecord.py 的 search_chatrecords（模糊查询 CRUD，须已存在；
返回 {"total", "newest_timestamp", "matches": [{"record", "rank"}]}，
rank = 该条在整个对话流中距最新的位次，1 = 最新一条）。

场景：用户提到"之前说过 / 上次定了 / 我们讨论过"而模型拿不准具体内容时，
先用本工具按关键词找回历史对话再回答，避免凭空编造。
每条结果带四样定位信息：精确时间（年-月-日 时:分:秒）、
距最新一条对话的时间差（天/小时/分钟/秒智能取单位，大单位后带小单位补精度）、
距最新聊天记录的条数（整个对话流中的位次，与聊天界面看到的流一致）、
说话人与类型标签，按时间从新到旧排列。
"""
from datetime import timedelta

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from agent.tools.common import current_project

_SNIPPET_LEN = 300  # 每条摘录最大长度（镜像行 content 是整张卡的 JSON，必须截断防刷屏）
_MAX_LIMIT = 20     # 单次返回条数上限


def _format_time_diff(delta: timedelta) -> str:
    """时间差 → 智能单位：≥1 天用天、≥1 小时用小时、≥1 分钟用分钟、否则秒；
    大单位后带一个非零的小单位补精度（如 2 天 3 小时 / 7 小时 12 分钟 / 5 分钟 40 秒）"""
    seconds = max(0, int(delta.total_seconds()))  # 负值（并发写入/时钟偏差）按 0 兜底
    if seconds >= 86400:
        d, rem = divmod(seconds, 86400)
        h = rem // 3600
        return f"{d} 天" + (f" {h} 小时" if h else "")
    if seconds >= 3600:
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        return f"{h} 小时" + (f" {m} 分钟" if m else "")
    if seconds >= 60:
        m, s = divmod(seconds, 60)
        return f"{m} 分钟" + (f" {s} 秒" if s else "")
    return f"{seconds} 秒"


@tool(parse_docstring=True)
async def search_chat_history(
    keyword: str,
    limit: int = 5,
    chat_type: str = "",
    config: RunnableConfig = None,
) -> str:
    """在当前项目的聊天历史中模糊搜索关键词，找回此前聊过的关键信息（自查记忆用）。
    用户提到"之前说过 / 上次定了 / 我们讨论过"而你拿不准具体内容时，先用本工具搜索再回答，
    不要凭空编造历史。每条结果带精确时间、距最新对话的时间差（按天/小时/分钟/秒智能取单位）、
    以及距最新聊天记录的条数，用于判断这条记忆的新旧。

    Args:
        keyword: 搜索关键词，按字面子串匹配聊天内容（非正则，% _ 不作通配符）
        limit: 最多返回条数，默认 5，最大 20
        chat_type: 可选，按记录类型过滤；留空搜全部类型

    Returns:
        命中条数及每条详情（精确时间、距最新对话的时间差与条数、说话人、内容摘录），
        按时间从新到旧排列；无命中时返回提示。
    """
    from config.db_conf import AsyncSessionLocal
    from crud.ChatRecord import search_chatrecords

    kw = (keyword or "").strip()
    if not kw:
        return "关键词为空，无法搜索聊天历史"
    try:
        limit = max(1, min(int(limit), _MAX_LIMIT))
    except (TypeError, ValueError):
        limit = 5

    project_id = current_project(config)
    async with AsyncSessionLocal() as db:
        result = await search_chatrecords(
            db, project_id, kw, limit=limit, chat_type=(chat_type or "").strip() or None)

    if result["total"] == 0:
        return "该项目还没有任何聊天记录"
    matches = result["matches"]
    if not matches:
        return (f"没有找到包含「{kw}」的聊天"
                f"（项目现有 {result['total']} 条聊天，可换个关键词再试）")

    newest_ts = result["newest_timestamp"]
    lines = []
    for m in matches:
        r = m["record"]
        ts = r.timestamp
        when = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "时间未知"
        rank = m["rank"]
        if rank == 1:
            pos = "这是最新一条对话"
        elif rank > 1:
            # 时间差口径：相对【最新一条聊天】，不是相对当前时刻——
            # 服务跨天重启后"距今多久"会失真，相对最新一条才是对话内的真实新旧
            diff = _format_time_diff(newest_ts - ts) if (newest_ts and ts) else "时间差未知"
            pos = f"距最新对话 {diff}（{rank - 1} 条之前）"
        else:
            pos = "刚写入（位次待定）"  # rank=-1：快照之后并发新写入的行，罕见
        role = "用户" if (r.role or "").lower() in ("user", "human") else "AI"
        rtype = r.type or "message"
        tag = "" if rtype == "message" else f"［{rtype}］"
        snippet = " ".join((r.content or "").split())  # 压平换行/连续空白
        if len(snippet) > _SNIPPET_LEN:
            snippet = snippet[:_SNIPPET_LEN] + "…"
        lines.append(f"· [{when}] {pos}｜{role}{tag}：{snippet}")

    head = f"找到 {len(lines)} 条包含「{kw}」的聊天（按时间从新到旧）："
    if len(matches) == limit:
        head += f"\n（已达单次返回上限 {limit} 条，可换更具体的关键词缩小范围）"
    return head + "\n" + "\n".join(lines)


TOOLS = [search_chat_history]

DISPLAY = {
    "search_chat_history": "搜聊天记忆",
}
