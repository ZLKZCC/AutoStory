"""角色域：查询角色/名册 + 新建/更新/删除角色与阶段（写入带人审）。

对齐 REST 层 routers/character.py、characterstage.py 的级联口径：
- 删除角色：阶段实体+角色-阶段映射清理 → 映射兜底 → 角色实体 → 项目-角色映射 → 阶段音频文件清理
- 删除阶段：角色-阶段映射 → 阶段实体 → 音频文件清理
- chapter_index 全程 0-based（与 Chapter.chapter_index 同口径，-1=未绑定/已删章），
  与模型注释及 shift/reset 系列 CRUD 一致。
- 语音生成（GPU 后台任务）保留在 REST 层，不做成 agent 工具；工具只写 voice_description。
"""
from typing import Annotated

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import InjectedToolCallId, ToolException, tool

from config.db_conf import AsyncSessionLocal
from crud import Character, CharacterStage, Project
from agent.tools.approval import request_approval
from agent.tools.common import current_project
from utils.common import rm_characters

# 工具层入参名 → DB 列名。age_Description 大写 D 是历史命名：
# update 走 hasattr 判断，传小写 age_description 会被静默跳过（原实现就踩了这个坑）
STAGE_FIELD_MAP = {
    "alias_name": "alias_name",
    "gender": "gender",
    "age_description": "age_Description",
    "appearance_description": "appearance_description",
    "profile": "profile",
    "voice_description": "voice_description",
    "chapter_index": "chapter_index",
}


def _stage_chapter_label(idx: int) -> str:
    return "未绑定/已删章" if idx < 0 else f"第{idx + 1}章"


@tool(parse_docstring=True)
async def get_characters(character_name: str, config: RunnableConfig = None) -> str:
    """查询角色（支持部分匹配）。传角色名返回命中角色的完整角色卡与阶段列表
    （阶段名/别名/起始章/简介）；传空字符串返回全员名册（名字/性别/定位/阶段数）。
    想知道某个角色是谁、有哪些阶段、各阶段从第几章开始，或需要角色名单时用。

    Args:
        character_name: 角色名，支持部分匹配；传空字符串则列出全部角色

    Returns:
        角色卡+阶段列表或全员名册；查询失败抛 ToolException。
    """
    project_id = current_project(config)
    if not project_id:
        raise ToolException("无法确定当前项目 ID，请确认会话已关联作品后再查询角色")

    try:
        async with AsyncSessionLocal() as db:
            chars, _ = await Character.get_characters_by_paginated(db, project_id, 0, 1000)
            if not chars:
                return "该项目还没有任何角色，可用 create_character 新建"

            if character_name.strip():
                hits = [c for c in chars if character_name in (c.character_name or "")]
                if not hits:
                    names = "、".join(c.character_name for c in chars[:20])
                    return f"没有名字含「{character_name}」的角色（现有：{names}）"
                blocks = []
                for c in hits:
                    stage_ids = await Character.get_stage_ids_by_character_id(db, c.id)
                    stages = await CharacterStage.get_stages_by_ids(db, list(stage_ids)) if stage_ids else []
                    stage_lines = "\n".join(
                        f" · {s.stage_name}（别名: {s.alias_name or '无'}，起始章: {_stage_chapter_label(s.chapter_index)}）"
                        f"｜{s.profile[:80] or '无简介'}"
                        for s in sorted(stages, key=lambda x: x.chapter_index)
                    ) or " （无阶段）"
                    blocks.append(
                        f"角色「{c.character_name}」 性别: {c.gender or '未设'} 定位: {c.role or '未设'}\n{stage_lines}"
                    )
                return "\n\n".join(blocks)

            # 名册模式：映射表一次查全，避免逐角色 N 次查询
            mappings = await Character.get_character_stage_mappings(db, [c.id for c in chars])
            count_of: dict = {}
            for m in mappings:
                count_of[m.character_id] = count_of.get(m.character_id, 0) + 1
            lines = [
                f" · {c.character_name}（性别: {c.gender or '未设'}，定位: {c.role or '未设'}，阶段数: {count_of.get(c.id, 0)}）"
                for c in chars
            ]
            return f"共 {len(chars)} 个角色：\n" + "\n".join(lines)
    except Exception as e:
        raise ToolException(f"查询角色失败：{e}") from e


@tool(parse_docstring=True)
async def create_character(
    character_name: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    gender: str = "",
    role: str = "",
    config: RunnableConfig = None,
) -> str:
    """新建角色（需用户确认）。创作中需要新人物登场时用。
    会先弹人审卡片，用户同意后写入：角色实体 + 项目-角色映射（与 REST 层 add_character 同两步）。

    Args:
        character_name: 角色名
        gender: 性别,可选
        role: 主角，配角，反派，龙套，其他

    Returns:
        创建结果（含新角色 id），用户拒绝或修改则返回对应提示。
    """
    project_id = current_project(config)
    if not character_name.strip():
        return "创建失败：character_name 不能为空，请给出角色名后重试"

    payload = {
        "entity": "characters", "action": "create",
        "summary": f"新建角色「{character_name}」",
        "draft": {"character_name": character_name, "gender": gender, "role": role},
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return f"已放弃新建角色「{character_name}」"
    d = {**payload["draft"], **answer.get("edited", {})}
    if not str(d.get("character_name") or "").strip():
        return "创建失败：编辑后的角色名为空"

    try:
        async with AsyncSessionLocal() as db:
            obj = await Character.add_character(db, d["character_name"], d.get("gender", ""), d.get("role", ""))
            await Project.add_project_character(db, project_id, obj.id)
    except Exception as e:
        raise ToolException(f"新建角色落库失败：{e}") from e
    return f"角色「{d['character_name']}」已创建（id={obj.id}）"


@tool(parse_docstring=True)
async def create_stage(
    character_name: str,
    stage_name: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    alias_name: str = "",
    gender: str = "",
    chapter_index: int = 0,
    age_description: str = "",
    appearance_description: str = "",
    profile: str = "",
    voice_description: str = "",
    config: RunnableConfig = None,
) -> str:
    """为已有角色新建一个阶段（需用户确认）。角色状态变化（成长/黑化/换身份）时用。
    会先弹人审卡片，用户同意后写入：阶段实体 + 角色-阶段关联（与 REST 层同两步）。

    Args:
        character_name: 角色名,支持部分匹配,需角色已存在
        stage_name: 阶段名
        alias_name: 别名,可选
        gender: 该阶段性别,可选
        chapter_index: 该阶段起始的章节索引,0-based(第1章填0,与 get_chapter_summaries 同口径;-1 表示暂不绑定章节),默认0
        age_description: 年龄段描述,可选
        appearance_description: 外貌描述,可选
        profile: 阶段简介,可选
        voice_description: 音色描述,可选,用于后续 TTS 配音(音色文件生成走前端,工具只存描述)

    Returns:
        阶段创建与关联结果（含 stage_id），角色不存在或用户拒绝时返回对应提示。
    """
    project_id = current_project(config)
    if not stage_name.strip():
        return "创建失败：stage_name 不能为空"

    try:
        async with AsyncSessionLocal() as db:
            chars, _ = await Character.get_characters_by_paginated(db, project_id, 0, 1000)
    except Exception as e:
        raise ToolException(f"查询角色失败：{e}") from e
    target = next((c for c in chars if character_name in (c.character_name or "")), None)
    if target is None:
        return f"没找到角色「{character_name}」，请先用 get_characters 核对或用 create_character 创建"

    payload = {
        "entity": "characters", "action": "add_stage",
        "summary": f"为「{target.character_name}」添加阶段「{stage_name}」",
        "draft": {
            "stage_name": stage_name, "alias_name": alias_name, "gender": gender,
            "chapter_index": chapter_index, "age_description": age_description,
            "appearance_description": appearance_description, "profile": profile,
            "voice_description": voice_description,
        },
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return f"已放弃为「{target.character_name}」添加阶段"
    d = {**payload["draft"], **answer.get("edited", {})}

    ci = d.get("chapter_index", 0)
    if not isinstance(ci, int):
        try:
            ci = int(ci)
        except (TypeError, ValueError):
            return f"创建失败：chapter_index 需要整数（0-based 章索引，-1=不绑定），收到：{ci!r}"
    if ci < -1:
        return f"创建失败：chapter_index 非法（须 ≥ -1），收到：{ci}"

    try:
        async with AsyncSessionLocal() as db:
            # 审批等待期间角色可能被删，重读确认
            char = await Character.get_character_by_id(db, target.id)
            if char is None:
                return f"角色「{target.character_name}」已被删除，阶段未创建"
            # 实体创建（注意 age_Description 大写 D 是 CRUD 形参名）→ 关联（Character/CharacterStage
            # 各有一个 add_character_stage：前者建映射、后者建实体，勿混）
            stage = await CharacterStage.add_character_stage(
                db,
                stage_name=str(d.get("stage_name") or stage_name),
                alias_name=d.get("alias_name", ""),
                gender=d.get("gender", ""),
                chapter_index=ci,
                age_Description=d.get("age_description", ""),
                appearance_description=d.get("appearance_description", ""),
                profile=d.get("profile", ""),
                voice_description=d.get("voice_description", ""),
                voice_path="",
            )
            await Character.add_character_stage(db, char.id, stage.id)
    except Exception as e:
        raise ToolException(f"新建阶段落库失败：{e}") from e
    return (f"阶段「{stage.stage_name}」已创建并关联到「{char.character_name}」"
            f"（stage_id={stage.id}，起始章: {_stage_chapter_label(ci)}）")


@tool(parse_docstring=True)
async def update_character(
    character_name: str,
    field: str,
    new_value: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig = None,
) -> str:
    """更新角色信息（需用户确认）。field 可选：gender / role（character_name 本身不可改）。
    会先弹人审卡片，用户同意后写入。

    Args:
        character_name: 角色名,支持部分匹配,需角色已存在
        field: 要更新的字段,取值 gender 或 role
        new_value: 字段的新值

    Returns:
        更新结果描述；字段不合法、角色不存在或用户拒绝时返回对应提示。
    """
    ALLOWED = {"gender", "role"}
    if field not in ALLOWED:
        return f"只能更新 {'/'.join(sorted(ALLOWED))}，收到: {field}"

    project_id = current_project(config)
    try:
        async with AsyncSessionLocal() as db:
            chars, _ = await Character.get_characters_by_paginated(db, project_id, 0, 1000)
    except Exception as e:
        raise ToolException(f"查询角色失败：{e}") from e
    target = next((c for c in chars if character_name in (c.character_name or "")), None)
    if target is None:
        return f"没找到角色「{character_name}」"

    payload = {
        "entity": "characters", "action": "update",
        "summary": f"更新角色「{target.character_name}」的 {field} → {new_value}",
        "draft": {"character_id": target.id, "field": field, "new_value": new_value},
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return f"已放弃更新「{target.character_name}」"
    d = {**payload["draft"], **answer.get("edited", {})}
    if d.get("field") not in ALLOWED:
        return f"编辑后的字段非法：{d.get('field')!r}（只允许 {'/'.join(sorted(ALLOWED))}）"

    try:
        async with AsyncSessionLocal() as db:
            char = await Character.get_character_by_id(db, d["character_id"])
            if char is None:
                return "该角色已被删除，无需更新"
            await Character.update_character(db, char.id, {d["field"]: d["new_value"]})
    except Exception as e:
        raise ToolException(f"更新角色落库失败：{e}") from e
    return f"「{char.character_name}」的 {d['field']} 已更新为「{d['new_value']}」"


@tool(parse_docstring=True)
async def update_stage(
    character_name: str,
    stage_name: str,
    field: str,
    new_value: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig = None,
) -> str:
    """更新角色某阶段的字段（需用户确认）。field 可选：alias_name / gender /
    age_description / appearance_description / profile / voice_description / chapter_index。
    会先弹人审卡片，用户同意后写入。

    Args:
        character_name: 角色名,支持部分匹配
        stage_name: 阶段名,支持部分匹配
        field: 字段名,见上
        new_value: 新值；chapter_index 传 0-based 章节索引的数字（第1章为 0，-1=不绑定）

    Returns:
        更新结果；字段不合法、角色/阶段不存在或用户拒绝时返回对应提示。
    """
    if field not in STAGE_FIELD_MAP:
        return f"阶段可更新字段: {'/'.join(STAGE_FIELD_MAP)}，收到: {field}"

    project_id = current_project(config)
    try:
        async with AsyncSessionLocal() as db:
            chars, _ = await Character.get_characters_by_paginated(db, project_id, 0, 1000)
    except Exception as e:
        raise ToolException(f"查询角色失败：{e}") from e
    target = next((c for c in chars if character_name in (c.character_name or "")), None)
    if target is None:
        return f"没找到角色「{character_name}」"

    try:
        async with AsyncSessionLocal() as db:
            stage_ids = await Character.get_stage_ids_by_character_id(db, target.id)
            stages = await CharacterStage.get_stages_by_ids(db, list(stage_ids)) if stage_ids else []
    except Exception as e:
        raise ToolException(f"查询阶段失败：{e}") from e
    stage = next((s for s in stages if stage_name in (s.stage_name or "")), None)
    if stage is None:
        return f"角色「{target.character_name}」没有名字含「{stage_name}」的阶段"

    payload = {
        "entity": "characters", "action": "update_stage",
        "summary": f"更新「{target.character_name}」阶段「{stage.stage_name}」的 {field}",
        "draft": {"stage_id": stage.id, "field": field, "new_value": new_value},
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return "已放弃更新阶段"
    d = {**payload["draft"], **answer.get("edited", {})}
    if d.get("field") not in STAGE_FIELD_MAP:
        return f"编辑后的字段非法：{d.get('field')!r}"

    val = d["new_value"]
    if d["field"] == "chapter_index":
        try:
            val = int(val)
        except (TypeError, ValueError):
            return f"chapter_index 需要整数（0-based 章索引，-1=不绑定），收到：{val!r}"
        if val < -1:
            return f"chapter_index 非法（须 ≥ -1），收到：{val}"

    try:
        async with AsyncSessionLocal() as db:
            row = await CharacterStage.get_character_stage_by_id(db, d["stage_id"])
            if row is None:
                return "该阶段已被删除，无需更新"
            # 关键：按 STAGE_FIELD_MAP 换算成 DB 列名（age_Description 大写 D），
            # 直接传小写会被 update 的 hasattr 检查静默跳过
            await CharacterStage.update_character_stage(db, row.id, {STAGE_FIELD_MAP[d["field"]]: val})
    except Exception as e:
        raise ToolException(f"更新阶段落库失败：{e}") from e
    return f"「{target.character_name}」阶段「{row.stage_name}」的 {d['field']} 已更新"


@tool(parse_docstring=True)
async def delete_character(
    character_name: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig = None,
) -> str:
    """删除角色及其全部阶段（需用户确认，不可逆）。删除会连带清理：角色-阶段映射、
    阶段实体、项目-角色映射，以及各阶段的参考音频文件。会先弹人审卡片，用户同意后执行。

    Args:
        character_name: 角色名,支持部分匹配,需角色已存在

    Returns:
        删除结果；角色不存在或用户拒绝时返回对应提示。
    """
    project_id = current_project(config)
    try:
        async with AsyncSessionLocal() as db:
            chars, _ = await Character.get_characters_by_paginated(db, project_id, 0, 1000)
    except Exception as e:
        raise ToolException(f"查询角色失败：{e}") from e
    target = next((c for c in chars if character_name in (c.character_name or "")), None)
    if target is None:
        return f"没找到角色「{character_name}」（可能已删除，可用 get_characters 核对）"

    try:
        async with AsyncSessionLocal() as db:
            stage_ids = await Character.get_stage_ids_by_character_id(db, target.id)
    except Exception as e:
        raise ToolException(f"查询角色阶段失败：{e}") from e

    payload = {
        "entity": "characters", "action": "delete",
        "summary": f"删除角色「{target.character_name}」及其 {len(stage_ids)} 个阶段（不可逆）",
        "draft": {"character_id": target.id, "character_name": target.character_name},
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return f"已放弃删除角色「{character_name}」"

    # 落库（与 REST 层 delete_character 同序；CRUD 多处内部 commit，非整体事务，与路由现状一致）：
    # 阶段实体+映射 → 映射兜底 → 角色实体 → 项目-角色映射（router 漏了这步，这里补上防脏映射）
    try:
        async with AsyncSessionLocal() as db:
            char = await Character.get_character_by_id(db, target.id)
            if char is None:
                return "该角色已被删除，无需重复操作"
            stage_ids = await Character.get_stage_ids_by_character_id(db, target.id)  # 重取，审批期间可能有新增
            await CharacterStage.delete_stages_by_character(db, target.id)
            await Character.remove_character_stage_by_character(db, target.id)
            await Character.delete_character(db, target.id)
            await Project.remove_project_character(db, target.id)
    except Exception as e:
        raise ToolException(f"删除角色落库失败：{e}") from e

    # 外部清理：各阶段音频目录；失败不回滚 DB，可手动清理
    if stage_ids:
        try:
            await rm_characters(stage_ids)
        except Exception as e:
            raise ToolException(f"阶段音频文件清理失败（数据已删，可手动清理目录）：{e}") from e
    return f"角色「{target.character_name}」及其 {len(stage_ids)} 个阶段已删除，音频文件已清理"


@tool(parse_docstring=True)
async def delete_stage(
    character_name: str,
    stage_name: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig = None,
) -> str:
    """删除角色的某个阶段（需用户确认，不可逆）。删除会连带清理角色-阶段映射与该阶段音频文件；
    角色本身不受影响。会先弹人审卡片，用户同意后执行。

    Args:
        character_name: 角色名,支持部分匹配
        stage_name: 阶段名,支持部分匹配

    Returns:
        删除结果；角色/阶段不存在或用户拒绝时返回对应提示。
    """
    project_id = current_project(config)
    try:
        async with AsyncSessionLocal() as db:
            chars, _ = await Character.get_characters_by_paginated(db, project_id, 0, 1000)
            target = next((c for c in chars if character_name in (c.character_name or "")), None)
            if target is None:
                return f"没找到角色「{character_name}」"
            stage_ids = await Character.get_stage_ids_by_character_id(db, target.id)
            stages = await CharacterStage.get_stages_by_ids(db, list(stage_ids)) if stage_ids else []
    except Exception as e:
        raise ToolException(f"查询角色/阶段失败：{e}") from e
    stage = next((s for s in stages if stage_name in (s.stage_name or "")), None)
    if stage is None:
        return f"角色「{character_name}」没有名字含「{stage_name}」的阶段"

    payload = {
        "entity": "characters", "action": "delete_stage",
        "summary": f"删除「{target.character_name}」的阶段「{stage.stage_name}」（不可逆）",
        "draft": {"stage_id": stage.id, "stage_name": stage.stage_name},
    }
    answer = request_approval(payload, tool_call_id)
    if not answer.get("approved"):
        return "已放弃删除阶段"

    # 落库（与 REST 层 delete_character_stage 同序）：角色-阶段映射 → 阶段实体
    try:
        async with AsyncSessionLocal() as db:
            row = await CharacterStage.get_character_stage_by_id(db, stage.id)
            if row is None:
                return "该阶段已被删除，无需重复操作"
            await Character.remove_character_stage(db, row.id)
            await CharacterStage.delete_character_stage(db, row.id)
    except Exception as e:
        raise ToolException(f"删除阶段落库失败：{e}") from e

    try:
        await rm_characters([row.id])
    except Exception as e:
        raise ToolException(f"阶段音频文件清理失败（数据已删，可手动清理目录）：{e}") from e
    return f"阶段「{row.stage_name}」已从「{target.character_name}」删除"


TOOLS = [get_characters, create_character, create_stage, update_character, update_stage, delete_character, delete_stage]

DISPLAY = {
    "get_characters": "查询角色/名册",
    "create_character": "新建角色",
    "create_stage": "新建阶段",
    "update_character": "更新角色",
    "update_stage": "更新阶段",
    "delete_character": "删除角色",
    "delete_stage": "删除阶段",
}
