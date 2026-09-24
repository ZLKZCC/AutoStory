import asyncio

from langchain_core.messages import HumanMessage, SystemMessage

from agent.models.loader import get_chat_model
from agent.models.structured import structured_model
from utils.audiobook.schemas import (
    AudioScript,
    ChapterCharacterExtraction,
    MappingTable,
    NewCharacterProposal,
    lint_script,
    strip_alias_decor,
)


class LLMStepFailed(Exception):
    """重试耗尽（调用方按兜底矩阵降级）"""

    def __init__(self, step: str, retries: int, cause: Exception):
        self.step, self.retries, self.cause = step, retries, cause
        super().__init__(f"[{step}] {retries} 次重试后仍失败: {cause}")


async def _structured_retry(step: str, schema, prompt: list, retries: int = 3):
    """结构化调用 + 重试（网络/解析/校验同通道）
    统一走 structured_model（function-calling 通道），不再用各厂商 with_structured_output：
    智谱未实现/通义拒 method kwarg/仅 OpenAI 系支持 json_schema——四档差异在统一层抹平。
    单次调用 180s 超时：LLM 端挂起（连接建立但不返回）时若不设超时，
    run_pipeline 卡死 → 图流不结束 → awaiting_input 永不发出，前端无限转圈。
    """
    model = await get_chat_model("pipeline")
    structured = structured_model(model, schema)
    last_err: Exception | None = None
    for i in range(retries):
        try:
            return await asyncio.wait_for(structured.ainvoke(prompt), timeout=180)
        except Exception as e:
            last_err = e
            print(f"[audiobook:{step}] 第{i + 1}次失败: {type(e).__name__}: {e}")
            if i < retries - 1:
                await asyncio.sleep(2 ** i)
    raise LLMStepFailed(step, retries, last_err)


# ══════════════ 步骤3 提取 ══════════════

EXTRACT_SYSTEM = """你是小说文本分析器。从章节正文中提取全部说话角色。
铁律：
1. 只提取真实出场、有台词或明确参与情节的角色；纯提名的传说人物不算。
2. 旁白不算角色。
3. evidence 必须摘原文原句，不许改写。
4. 同一人多种称呼合并为一个角色（别名进 aliases，name 用最常用称呼）。"""


def build_extract_prompt(chapter_title: str, chapter_content: str) -> list:
    truncated = chapter_content[:8000]
    note = f"\n（正文共{len(chapter_content)}字，此处截取前8000字）" if len(chapter_content) > 8000 else ""
    return [
        SystemMessage(EXTRACT_SYSTEM),
        HumanMessage(f"## 章节标题\n{chapter_title}\n\n## 正文\n{truncated}{note}\n\n"
                     f"提取本章出现的全部角色。"),
    ]


# ══════════════ 步骤4 提案 ══════════════

DRAFT_SYSTEM = """你是角色库管理助手。对照「库里已有的角色阶段」与「本章提取出的角色」，
判断哪些提取角色在库里找不到归属、需要新建；并给库里缺音色描述的已有阶段补上音色描述。
铁律：
1. 名字相同或别名相同 → 已存在，不进新建列表。
2. 名字不同但场景/侧写高度吻合 → 也算已存在（交给映射步骤去连）。
3. 只有确实对不上号的才进 new_characters。
4. 新建角色必须带至少一个 stages（本章状态的阶段），voice_description 尽量具体
   （性别+年龄段+气质，如「青年男声，清亮偏脆，语速偏快」）。
5. 角色卡清单里标了「缺音色描述」的已有阶段：据其性别/年龄/侧写 + 本章基调，拟一条具体的
   voice_description 放进 voice_supplements（务必带上该阶段的 stage_id）；不缺的不要动、不要重复补。"""


def _render_stage_catalog(stages) -> str:
    """角色阶段合集 → 文本清单（给 LLM：stage_id + 名字 + 阶段 + 起始章 + 侧写 + 音色描述状态）"""
    lines = []
    for s in stages:
        vd = (s.get("voice_description") or "").strip()
        voice = f"音色: {vd[:40]}" if vd else "缺音色描述（需在 voice_supplements 补，带 stage_id）"
        lines.append(
            f"· [stage_id={s['stage_id']}] {s['character_name']}｜阶段「{s['stage_name']}」"
            f"(第{s['chapter_index']}章起)｜{s.get('profile', '')[:40]}｜{voice}"
        )
    return "\n".join(lines) or "（库里没有本章可用的角色阶段）"


def _render_extracted(extracted) -> str:
    # 调用方传入的是角色列表（extraction.characters）；兼容直接传提取对象的情况
    chars = getattr(extracted, "characters", extracted)
    lines = []
    for c in chars:
        alias = f"｜别名: {'、'.join(c.aliases)}" if c.aliases else ""
        lines.append(f"· 名字: {c.name}{alias}｜场景: {c.scene_hint}｜音色印象: {c.voice_hint}")
    return "\n".join(lines) or "（本章无提取角色）"


def build_draft_prompt(chapter_index: int, stage_catalog: list, extracted) -> list:
    # chapter_index 是章节表的 0-based 序号；给 LLM 看的是「第几章」，+1 转 1-based，
    # 与阶段表口径一致（也避免 LLM 给新阶段填出 chapter_index=0 违反 ge=1）
    return [
        SystemMessage(DRAFT_SYSTEM),
        HumanMessage(f"## 当前是第 {chapter_index + 1} 章\n\n"
                     f"## 库中本章可用角色阶段\n{_render_stage_catalog(stage_catalog)}\n\n"
                     f"## 本章提取出的角色\n{_render_extracted(extracted)}\n\n"
                     f"做两件事：① 哪些提取角色需要新建？都已有归属则 new_characters 留空。"
                     f"② 上面标「缺音色描述」的已有阶段，各拟一条 voice_description 放进 voice_supplements（带 stage_id）。"),
    ]


# ══════════════ 步骤5 映射 ══════════════

MAP_SYSTEM = """你是角色匹配器。为每个提取角色找到最贴合的库内角色阶段（character_id + stage_id）。
铁律：
1. 每个提取角色都要给一行 entry，确信不存在归属的也指向最接近的（confidence 填低）。
2. 一个阶段可以被多个提取角色共用（不同称呼指同一人时）。
3. confidence: 同名/别名直接命中 ≥0.9；场景吻合 0.5-0.8；仅类型相似 0.2-0.4。
4. reason 写匹配依据一句话。"""


def build_map_prompt(stage_catalog: list, extracted) -> list:
    """注意：此处的 stage_catalog 带 character_id/stage_id（映射需要），其余渲染同步骤4"""
    lines = []
    for s in stage_catalog:
        lines.append(
            f"· {s['character_name']}｜阶段「{s['stage_name']}」"
            f"[character_id={s['character_id']}, stage_id={s['stage_id']}]"
            f"(第{s['chapter_index']}章起)｜{s.get('profile', '')[:40]}"
        )
    # 预拼好再进 f-string：f-string 表达式里写 '\n'.join 在 py<3.12 是语法错误
    catalog_text = "\n".join(lines) or "（空）"
    return [
        SystemMessage(MAP_SYSTEM),
        HumanMessage(f"## 库中本章可用角色阶段\n{catalog_text}\n\n"
                     f"## 本章提取出的角色\n{_render_extracted(extracted)}\n\n"
                     f"给出映射表。"),
    ]


# ══════════════ 步骤8 脚本 ══════════════

SCRIPT_SYSTEM = """你是广播剧编排师。把章节正文改编为有声书分段脚本。
铁律：
1. segments 覆盖全部正文内容，按剧情顺序，index 从 0 连续递增。
2. 一段 = 一个人的一段连续话语。交替对话必须拆成相邻段（speaker 轮换）。
3. 按自然朗读节奏分段：一段 = 朗读时一口气能说完、说完自然换气停顿的完整话语。
   以句号/问号/感叹号为基本断段点；一个人的长台词在自然停顿处（语义完整的
   句读边界）拆成相邻段（speaker 相同、index 递增）。
   禁止：把语意未完的半句话切成两段；把好几句话并成一口气念不完的超长段
   （TTS 单次合成有长度上限，超长段韵律会崩坏）。
4. 打断/抢话用 pause_after_sec=0 表达；被截断的话在 text 里用破折号「——」结尾。
5. speaker 只能用提供的角色卡名单（含旁白）。
6. 对话用正文原句，旁白可适度压缩，但不删情节点。
7. BGM/SFX 只能用提供清单内的 audio_id；BGM 用 start_segment/end_segment 区间铺底，
   SFX 用 segment 定位到段。
8. 停顿默认 0.8 秒；紧凑场景减小，留白场景加大。"""


def _render_character_cards(cards: dict) -> str:
    """角色卡 {名字: 阶段精要文本}——步骤5连线确认后由 persist.build_character_cards 组装"""
    return "\n".join(f"· {name}：{info}" for name, info in cards.items()) or "（无角色）"


def _render_audio_catalog(audios) -> str:
    lines = []
    for a in audios:
        lines.append(f"· audio_id={a['id']} [{a['type']}] {a['name']}：{a.get('description', '')[:60]}")
    return "\n".join(lines) or "（无音频资源）"


def build_script_prompt(chapter_title: str, chapter_content: str,
                        character_cards: dict, audio_catalog: list) -> list:
    return [
        SystemMessage(SCRIPT_SYSTEM),
        HumanMessage(f"## 章节标题\n{chapter_title}\n\n"
                     f"## 角色卡\n{_render_character_cards(character_cards)}\n\n"
                     f"## 可用音频（BGM/SFX）\n{_render_audio_catalog(audio_catalog)}\n\n"
                     f"## 正文（全文）\n{chapter_content}\n\n"
                     f"输出完整分段脚本。"),
    ]


# ══════════════ 四个步骤入口 ══════════════

async def llm_extract(chapter_title: str, chapter_content: str) -> ChapterCharacterExtraction:
    prompt = build_extract_prompt(chapter_title, chapter_content)
    return await _structured_retry("extract", ChapterCharacterExtraction, prompt)


async def llm_draft(chapter_index: int, stage_catalog: list, extracted) -> NewCharacterProposal:
    """stage_catalog: [{character_name, stage_name, chapter_index, profile, voice_description, ...}]"""
    prompt = build_draft_prompt(chapter_index, stage_catalog, extracted)
    return await _structured_retry("draft", NewCharacterProposal, prompt)


async def llm_map(stage_catalog: list, extracted) -> MappingTable:
    """stage_catalog 带 character_id/stage_id（映射渲染需要）"""
    prompt = build_map_prompt(stage_catalog, extracted)
    table = await _structured_retry("map", MappingTable, prompt)
    # extracted_name 规整为裸名：LLM 常把渲染出的"名字（别名: …）"整串抄进来，
    # 会让下游角色卡/白名单/合成音色表都带装饰名，而脚本 speaker 用裸名 → lint 不匹配、
    # 合成时 name2stage 找不到音色（KeyError）→ 整段静音。统一在源头剥成裸名。
    for e in table.entries:
        e.extracted_name = strip_alias_decor(e.extracted_name)
    return table


async def llm_script(chapter_title: str, chapter_content: str,
                     character_cards: dict, audio_catalog: list) -> AudioScript:
    """结构重试 3 次（_structured_retry） + lint 重试 1 次（带具体警告作为修正指令）"""
    prompt = build_script_prompt(chapter_title, chapter_content, character_cards, audio_catalog)
    script = await _structured_retry("script", AudioScript, prompt)
    allowed_speakers = {"旁白", *character_cards.keys()}
    allowed_audio_ids = {a["id"] for a in audio_catalog}
    warnings = lint_script(script, allowed_speakers, allowed_audio_ids)
    if warnings:
        script.metadata.warnings = warnings  # 修正失败也要带着警告落盘
        print(f"[audiobook:script] lint 警告 {len(warnings)} 条，带反馈重试一次: {warnings[:3]}")
        fix_note = "\n".join(f"- {w}" for w in warnings)
        corrected_prompt = list(prompt) + [HumanMessage(
            f"你上一版有以下问题，逐条修正后重新输出完整脚本：\n{fix_note}"
        )] + [prompt[-1]]  # 保持正文输入在末位
        try:
            script = await _structured_retry("script_fix", AudioScript, corrected_prompt)
        except LLMStepFailed:
            print("[audiobook:script] lint 修正重试失败，采用带警告的上一版")
        else:
            warnings = lint_script(script, allowed_speakers, allowed_audio_ids)
            script.metadata.warnings = warnings
    return script
