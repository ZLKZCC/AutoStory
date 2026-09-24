from datetime import datetime

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from pydantic import BaseModel
import json
import re
from typing import Optional
from config.store import DEFAULT_CONTEXT_WINDOW
from crud import ChatRecord, Project, Summary, Chapter
from utils.content_format import outline_to_text, worldline_to_text
from agent.models.loader import get_chat_model, get_context_window
from agent.models.structured import structured_model


class ProjectMeta(BaseModel):
    """project_summary / project_description 结构化输出约束。"""
    project_summary: str
    project_description: str




def trim_to_budget(
    text: str,
    max_tokens: int,
    head_ratio: float = 0.4,
    middle_note: Optional[str] = None,
) -> str:
    """超预算时"保头保尾、删中间"截断，按 LLM 特性尽量保留有效信息。

    策略依据：
    1. 注意力 U 形：模型对上下文首尾的利用效率远高于中段 → 删中间损失最小；
    2. 生成强依赖紧邻前缀：结尾的悬念/最新剧情权重最高，开头承载人物与设定 → 两头都要保；
    3. 半句话会污染理解：所有切口对齐到整段 / 整句 / 标点边界；
    4. 不连续文本直接拼接会诱发模型脑补过渡 → 中间显式插入省略标记或摘要。

    Args:
        max_tokens:  截断结果的 token 预算（近似计数）。
        head_ratio:  头部预算占比。续写下一章用 0.3（结尾更重要）；全章总结用 0.45~0.5。
        middle_note: 塞进省略区的替代文本（如 chapter_summary），None 则用纯省略标记。
    """
    # ---------- 0. 预算内：原样返回 ----------
    if count_tokens_approximately(text) <= max_tokens:
        return text

    SENT = r'[^。！？!?…\n]+[。！？!?…；;]*["”』」）]*'   # 中文整句切分
    PUNCT = "，。！？；、…"                              # 字符级兜底时切口对齐的标点

    # ---------- 1. 中段摘要限长：最多占预算一半，超长按整句截短 ----------
    note = middle_note
    if note:
        note_budget = max(1, max_tokens // 2)
        if count_tokens_approximately(note) > note_budget:
            kept, used = "", 0
            for sent in re.findall(SENT, note):
                t = count_tokens_approximately(sent)
                if used + t > note_budget:
                    break
                kept, used = kept + sent, used + t
            note = kept or note[: len(note) // 2]        # 单句都超预算 → 粗暴砍半

    # ---------- 2. 预算分配：扣除摘要与省略标记（约 32 token 余量）后按比例分给头/尾 ----------
    budget = max_tokens - 32 - (count_tokens_approximately(note) if note else 0)
    keep_tail = budget > 0
    if not keep_tail:
        budget = max_tokens                             # 预算小到放不下"头+标记+尾"结构：退化为纯头部截断
    head_budget = budget if not keep_tail else max(1, int(budget * head_ratio))
    tail_budget = budget - head_budget

    paras = text.split("\n")                            # 段落粒度优先，保持结构完整
    n = len(paras)

    # ---------- 3. 头部：整段 → 整句 → 字符二分，三级降级装填 ----------
    head_parts, used, i = [], 0, 0
    while i < n:
        para = paras[i]
        t = count_tokens_approximately(para)
        if used + t <= head_budget:                     # 整段放得下 → 直接装
            head_parts.append(para)
            used += t
            i += 1
            continue
        remain = head_budget - used                     # 整段放不下 → 句级前缀
        kept, used_s = "", 0
        for sent in re.findall(SENT, para):
            st = count_tokens_approximately(sent)
            if used_s + st > remain:
                break
            kept, used_s = kept + sent, used_s + st
        if not kept:                                    # 单句都超 → 二分找最大可放前缀
            lo, hi = 0, len(para)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if count_tokens_approximately(para[:mid]) <= remain:
                    lo = mid
                else:
                    hi = mid - 1
            cut = max(para.rfind(p, 0, lo) for p in PUNCT)   # 切口尽量对齐标点
            kept = para[: cut + 1] if cut >= lo * 0.6 else para[:lo]
        if kept:
            head_parts.append(kept)
            i += 1                                      # 该段已部分消费，尾部不可复用
        break                                           # 头部预算用尽

    # ---------- 4. 尾部：从最后一段往前整段装（保证原文结尾完整），同样三级降级 ----------
    tail_parts, used, j = [], 0, n - 1
    while keep_tail and j >= i:
        para = paras[j]
        t = count_tokens_approximately(para)
        if used + t <= tail_budget:
            tail_parts.insert(0, para)
            used += t
            j -= 1
            continue
        remain = tail_budget - used
        kept, used_s = "", 0
        for sent in reversed(re.findall(SENT, para)):   # 从段尾往前按句装
            st = count_tokens_approximately(sent)
            if used_s + st > remain:
                break
            kept, used_s = sent + kept, used_s + st
        if not kept:                                    # 二分找最小可用起点
            lo, hi = 0, len(para)
            while lo < hi:
                mid = (lo + hi) // 2
                if count_tokens_approximately(para[mid:]) <= remain:
                    hi = mid
                else:
                    lo = mid + 1
            cut = min((p for p in (para.find(c, lo) for c in PUNCT) if p >= lo), default=-1)
            # 起点向后蹭到最近标点（≤20 字且不超预算），避免从半句中间开始
            if cut != -1 and cut - lo <= 20 and count_tokens_approximately(para[cut + 1:]) <= remain:
                kept = para[cut + 1:]
            else:
                kept = para[lo:]
        if kept:
            tail_parts.insert(0, kept)
        break

    # ---------- 5. 拼接：头 +（摘要 / 省略标记）+ 尾 ----------
    if not keep_tail:                                   # 退化模式：只保头，无标记
        return "\n".join(head_parts).strip()

    omitted_chars = sum(len(p) for p in paras[i:j])     # 中间被丢弃的字数（约数）
    marker = (f"\n\n{note}\n\n" if note else
              f"\n\n【……中间约 {omitted_chars} 字已省略，上文与下文剧情不连续……】\n\n")
    return ("\n".join(head_parts) + marker + "\n".join(tail_parts)).strip()


async def regenerate_project_meta(
    concept_text: str,
    worldline_text: str,
    contents_text: str,
    original_summary: str,
    original_description: str,
    supplement_texts: Optional[list[str]] = None,
) -> tuple[str, str]:
    """用激活 LLM，把设定/章节/补充材料/旧概要裁到上下文预算内，再生成新的 project_summary + project_description。
    失败（无激活模型 / 解析异常）回退原值，不阻塞主流程。

    supplement_texts: 额外补充材料（各条可自带"【补充·xx】"来源标签），如最新正文片段、
    与作者讨论形成的创作共识。有则从 concept/worldline 两个最大槽位各匀出 7.5% 预算
    平摊给补充材料（0.35/0.35 → 0.275/0.275），其余来源额度不变。

    快速路径：所有输入（含补充材料与旧值）总字数 ≤ 5000 时，不调用 LLM（连
    get_context_window 也省掉），直接把旧概要/补充材料/大纲/世界线/章节清单拼成新
    project_summary（3000 字内，超出时按各段原始占比等比裁剪），description 沿用
    旧值，为空时取概要文本开头兜底。
    """
    supp_items = [t for t in (supplement_texts or []) if t and t.strip()]

    # ---- 快速路径：输入总量 ≤ 5000 字，直接组装，跳过 LLM 与模型查询 ----
    input_total = sum(
        len(t or "")
        for t in (concept_text, worldline_text, contents_text,
                  original_summary, original_description, *supp_items)
    )
    if input_total <= 5000:
        # 没有任何新内容可融合时，旧值原样返回，避免无意义的重新包装
        if not any(t and t.strip() for t in (concept_text, worldline_text, contents_text, *supp_items)):
            return (original_summary or "")[:3000], (original_description or "")[:255]

        # 按 旧概要 → 补充材料(最新事实) → 大纲 → 世界线 → 章节清单 的顺序拼接
        sections: list[tuple[str, str]] = []
        if original_summary and original_summary.strip():
            sections.append(("故事概要", original_summary.strip()))
        for t in supp_items:
            sections.append(("补充材料", t.strip()))
        if concept_text and concept_text.strip():
            sections.append(("大纲", concept_text.strip()))
        if worldline_text and worldline_text.strip():
            sections.append(("世界线", worldline_text.strip()))
        if contents_text and contents_text.strip():
            sections.append(("章节清单", contents_text.strip()))

        # 扣除各段标签/换行的固定开销后，按原始占比等比分配 3000 字预算；
        # 总量本身没超限时 scale >= 1，不会裁剪任何内容
        total = sum(len(text) for _, text in sections)
        scale = min(1.0, (3000 - 12 * len(sections)) / total)

        parts: list[str] = []
        for label, text in sections:
            if scale < 1.0:
                text = trim_to_budget(text, max(1, int(len(text) * scale)))
            parts.append(f"【{label}】\n{text}")
        summary = "\n\n".join(parts)[:3000]

        # description：优先沿用旧值；首次生成时用概要文本开头兜底（去掉段标签）
        description = (original_description or "").strip()
        if not description:
            fallback = (original_summary or "").strip() or summary.split("\n", 1)[-1]
            description = fallback[:255]

        print(f"[build_context] 输入总量 {input_total} ≤ 5000 字，"
              f"快速组装 project_summary/description，跳过 LLM")
        return summary, description[:255]

    # ---- LLM 重算路径 ----
    try:
        window = await get_context_window("chat")
    except Exception:
        window = DEFAULT_CONTEXT_WINDOW  # 无激活模型时的保守默认窗口

    # 输入预算取窗口一半，给系统提示与输出留空间；各来源按重要度分额度
    budget = int(window * 0.5)
    if supp_items:
        concept_text = trim_to_budget(concept_text, int(budget * 0.275))
        worldline_text = trim_to_budget(worldline_text, int(budget * 0.275))
        per_supp = max(1, int(budget * 0.15) // len(supp_items))
        supplements_text = "\n\n".join(trim_to_budget(t, per_supp) for t in supp_items)
    else:
        concept_text = trim_to_budget(concept_text, int(budget * 0.35))
        worldline_text = trim_to_budget(worldline_text, int(budget * 0.35))
        supplements_text = ""
    contents_text = trim_to_budget(contents_text, int(budget * 0.15))
    original_summary = trim_to_budget(original_summary, int(budget * 0.10))
    original_description = trim_to_budget(original_description, int(budget * 0.05))

    supplement_section = (
        f"\n[补充材料（最新事实，优先级高于旧概要）]\n{supplements_text}\n\n"
        if supplements_text else ""
    )
    try:
        model = await get_chat_model("chat")
        structured = structured_model(model, ProjectMeta)
        messages = [
            {"role": "system", "content": (
                "你是小说作品的设定整理助手。根据资料生成两份结构化元信息：\n"
                "1. project_summary：全作品故事概要，融合大纲、世界线、章节清单与旧概要"
                "（如有[补充材料]，将其视作最新事实优先融入，与旧设定冲突时以补充材料为准），"
                "定方向、抓主线，3000 字内。\n"
                "2. project_description：项目的一句话/段简介，面向读者，255 字内。\n"
                "只输出结构化结果，不要额外说明。"
            )},
            {"role": "user", "content": (
                f"[大纲]\n{concept_text}\n\n"
                f"[世界线]\n{worldline_text}\n\n"
                f"[章节清单]\n{contents_text}\n\n"
                f"{supplement_section}"
                f"[旧 project_summary]\n{original_summary}\n\n"
                f"[旧 project_description]\n{original_description}\n"
            )},
        ]
        result = await structured.ainvoke(messages)
        summary = (result.project_summary or original_summary)[:3000]
        description = (result.project_description or original_description)[:255]
        return summary, description
    except Exception as e:
        print(f"[build_context] 重算 project_summary/description 失败，沿用原值: "
              f"{type(e).__name__}: {e}")
        return original_summary, original_description


async def build_context(db, project_id) -> dict:
    project = await Project.get_project_by_id(db, project_id)
    summary_text = ""
    project_summary = ""
    project_name = ""
    project_description = ""
    messages = []
    if project:
        project_name = getattr(project, "project_name", "") or ""
        original_summary = getattr(project, "Project_summary", "") or ""
        original_description = getattr(project, "description", "") or ""

        concept_text = outline_to_text(project.concept) if project.concept else ""
        worldline_text = worldline_to_text(project.worldline) if project.worldline else ""

        chapters = await Chapter.get_chapter_times_by_project(db, project.id)
        contents = [f"第{ch[2] + 1}章:{ch[1]}" for ch in chapters if ch[1]]
        contents_text = "\n".join(contents)

        # 大纲/世界线自上次生成概要后有变更 → 重算并写回；否则沿用现状，避免每轮空烧 LLM。
        # 不把 description 变更列为触发条件：description 本身就是 project_description，
        # 列入会令「改描述→下一轮即被覆盖」形成死循环；原 description 仍作为 LLM 输入来源之一。
        stale = (
            (project.concept_updated_at
             and (project.summary_generated_at is None
                  or project.concept_updated_at > project.summary_generated_at))
            or (project.worldline_updated_at
                and (project.summary_generated_at is None
                     or project.worldline_updated_at > project.summary_generated_at))
        )
        if stale:
            project_summary, project_description = await regenerate_project_meta(
                concept_text, worldline_text, contents_text,
                original_summary, original_description)
            await Project.update_project(db, project.id, {
                "Project_summary": project_summary,
                "description": project_description,
                "description_updated_at": datetime.now(),
                "summary_generated_at": datetime.now(),
            })
        else:
            project_summary = original_summary
            project_description = original_description

        summary = await Summary.get_latest_summary_by_project(db, project.id)
        summary_text = summary.chatcontext if summary else ""

        chats = await ChatRecord.get_records_for_context(db, project.id, hard_limit=20)
        for chat in chats:
            if chat.role in ("user", "Human"):   # "Human" 为合并前旧库行
                messages.append(HumanMessage(content=chat.content))
            elif chat.role == "assistant":
                if chat.type == "message":
                    messages.append(AIMessage(content=chat.content))
                elif chat.type == "tool_call":
                    # 工具行回放成 AIMessage(tool_calls) + ToolMessage(result) 对：
                    # 忠实还原当时的调用（LLM 能看到自己调过什么、拿到了什么）。
                    # 孤儿 ToolMessage 会因缺前驱 AIMessage 被模型端校验拒绝，必须成对。
                    try:
                        row = json.loads(chat.content)
                    except Exception:
                        row = None
                    if isinstance(row, dict) and (chat.extra or "").strip():
                        messages.append(AIMessage(
                            content="",
                            tool_calls=[{
                                "name": row.get("tool") or "tool",
                                "args": row.get("arguments") or {},
                                "id": chat.extra,
                                "type": "tool_call",
                            }],
                        ))
                        messages.append(ToolMessage(
                            content=str(row.get("result") or ""),
                            tool_call_id=chat.extra,
                        ))
                # interrupt / audiobook 镜像行是人审卡，不是对话内容 → 不进 LLM 上下文

    return {
        "summary": summary_text,
        "project_summary": project_summary,
        "project_name": project_name,
        "project_description": project_description,
        "project_id": project_id,
        "messages": messages,
    }
