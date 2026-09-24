from typing import List, Dict, Any

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.AudioBookScript import AudioBookScript, AudioBookScripAudio
from schemas.AudioBookScript import AudioBookScriptCreate


async def add_audio_book_script(
    db: AsyncSession,
    name: str,
    project_id: int,
    chapter_id: int,
    script_path: str,
    audio_path: str,
):
    """创建新的音频脚本记录"""
    db_obj = AudioBookScript(
        name=name,
        project_id=project_id,
        chapter_id=chapter_id,
        script_path=script_path,
        audio_path=audio_path,
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_or_create_script_draft(
    db: AsyncSession,
    project_id: int,
    chapter_id: int,
    name: str,
):
    """发起有声书即建行（草稿），同章节复用最近一行"""
    stmt = (
        select(AudioBookScript)
        .where(AudioBookScript.chapter_id == chapter_id)
        .order_by(AudioBookScript.id.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    db_obj = AudioBookScript(name=name, project_id=project_id, chapter_id=chapter_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def add_audio_book_script_by_model(db: AsyncSession, audioscript: AudioBookScriptCreate):
    """按 schema 创建脚本记录"""
    db_obj = AudioBookScript(**audioscript.model_dump())
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_scripts_by_chapter(
    db: AsyncSession, chapter_id: int, offset: int = 0, limit: int = 10
):
    """获取指定章节下的脚本列表（支持分页）"""
    count_stmt = select(func.count(AudioBookScript.id)).where(
        AudioBookScript.chapter_id == chapter_id
    )
    total = (await db.execute(count_stmt)).scalar()

    list_stmt = (
        select(AudioBookScript)
        .where(AudioBookScript.chapter_id == chapter_id)
        .order_by(AudioBookScript.id)
        .offset(offset)
        .limit(limit)
    )
    scripts = (await db.execute(list_stmt)).scalars().all()
    return scripts, total


async def get_scripts_by_project(
    db: AsyncSession, project_id: int, offset: int = 0, limit: int = 100
):
    """获取指定项目下全部章节的脚本列表（支持分页）"""
    count_stmt = select(func.count(AudioBookScript.id)).where(
        AudioBookScript.project_id == project_id
    )
    total = (await db.execute(count_stmt)).scalar()

    list_stmt = (
        select(AudioBookScript)
        .where(AudioBookScript.project_id == project_id)
        .order_by(AudioBookScript.id)
        .offset(offset)
        .limit(limit)
    )
    scripts = (await db.execute(list_stmt)).scalars().all()
    return scripts, total


async def get_paths_by_script_ids(
    db: AsyncSession, script_ids: List[int], offset: int = 0, limit: int = 10
):
    """批量取脚本的脚本/音频路径"""
    stmt = (
        select(AudioBookScript.script_path, AudioBookScript.audio_path)
        .where(AudioBookScript.id.in_(script_ids))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.all()


async def get_script_by_id(db: AsyncSession, script_id: int):
    """根据ID获取脚本详情"""
    stmt = select(AudioBookScript).where(AudioBookScript.id == script_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_script(db: AsyncSession, script_id: int, update_data: Dict[str, Any]):
    """更新脚本信息"""
    stmt = select(AudioBookScript).where(AudioBookScript.id == script_id)
    result = await db.execute(stmt)
    db_obj = result.scalar_one_or_none()
    if not db_obj:
        return None
    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


# ==================== 脚本-音频映射（重写重点） ====================

async def get_mappings_by_script(db: AsyncSession, script_id: int) -> List[AudioBookScripAudio]:
    """获取脚本下全部映射行"""
    stmt = (
        select(AudioBookScripAudio)
        .where(AudioBookScripAudio.script_id == script_id)
        .order_by(AudioBookScripAudio.id)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_audio_ids_by_script(db: AsyncSession, script_id: int) -> List[int]:
    """获取脚本已映射的音频资源 id 列表"""
    stmt = select(AudioBookScripAudio.audio_id).where(AudioBookScripAudio.script_id == script_id)
    return (await db.execute(stmt)).scalars().all()


async def add_audiobook_audio(db: AsyncSession, script_id: int, audio_id: int):
    """添加映射（幂等：重复添加直接返回已有映射，配合唯一约束）"""
    stmt = select(AudioBookScripAudio).where(
        AudioBookScripAudio.script_id == script_id,
        AudioBookScripAudio.audio_id == audio_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    db_obj = AudioBookScripAudio(script_id=script_id, audio_id=audio_id)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def replace_script_audios(db: AsyncSession, script_id: int, audio_ids: List[int]) -> List[int]:
    """整体替换脚本的映射（先清后插，向导'确认映射'一次性提交用）"""
    await db.execute(
        delete(AudioBookScripAudio).where(AudioBookScripAudio.script_id == script_id)
    )
    if audio_ids:
        unique_ids = list(dict.fromkeys(audio_ids))  # 去重保序
        db.add_all(
            [AudioBookScripAudio(script_id=script_id, audio_id=aid) for aid in unique_ids]
        )
    await db.commit()
    return await get_audio_ids_by_script(db, script_id)


async def remove_audiobook_audio(db: AsyncSession, script_id: int, audio_id: int) -> bool:
    """删除单条映射
    FIX: 原实现 delete(AudioBookScript) 表对象写错，会误删脚本主表且没有 commit
    """
    stmt = delete(AudioBookScripAudio).where(
        AudioBookScripAudio.script_id == script_id,
        AudioBookScripAudio.audio_id == audio_id,
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


# ==================== 级联删除（脚本删除时同步删映射） ====================

async def delete_audio_book_script(db: AsyncSession, script_id: int) -> bool:
    """删除单个脚本及其映射（同一事务提交）
    FIX: 原实现映射条件用的是 AudioBookScripAudio.id == script_id，应为 script_id 列
    """
    await db.execute(
        delete(AudioBookScripAudio).where(AudioBookScripAudio.script_id == script_id)
    )
    result = await db.execute(
        delete(AudioBookScript).where(AudioBookScript.id == script_id)
    )
    await db.commit()
    return result.rowcount > 0


async def delete_audio_book_scripts(db: AsyncSession, script_ids: List[int]) -> bool:
    """批量删除脚本及其映射"""
    if not script_ids:
        return False
    await db.execute(
        delete(AudioBookScripAudio).where(AudioBookScripAudio.script_id.in_(script_ids))
    )
    result = await db.execute(
        delete(AudioBookScript).where(AudioBookScript.id.in_(script_ids))
    )
    await db.commit()
    return result.rowcount > 0


async def delete_scripts_by_chapter(db: AsyncSession, chapter_id: int):
    """级联删除指定章节下的所有脚本及映射（不提交，由调用方统一 commit）"""
    script_ids = (
        await db.execute(
            select(AudioBookScript.id).where(AudioBookScript.chapter_id == chapter_id)
        )
    ).scalars().all()
    if not script_ids:
        return
    await db.execute(
        delete(AudioBookScripAudio).where(AudioBookScripAudio.script_id.in_(script_ids))
    )
    await db.execute(
        delete(AudioBookScript).where(AudioBookScript.chapter_id == chapter_id)
    )


async def delete_scripts_by_project(db: AsyncSession, project_id: int):
    """级联删除指定项目下的所有脚本及映射（不提交，由调用方统一 commit）"""
    script_ids = (
        await db.execute(
            select(AudioBookScript.id).where(AudioBookScript.project_id == project_id)
        )
    ).scalars().all()
    if not script_ids:
        return
    await db.execute(
        delete(AudioBookScripAudio).where(AudioBookScripAudio.script_id.in_(script_ids))
    )
    await db.execute(
        delete(AudioBookScript).where(AudioBookScript.project_id == project_id)
    )


async def delete_scripts_by_projects(db: AsyncSession, project_ids: List[int]):
    """批量级联删除多个项目下的脚本及映射（不提交，由调用方统一 commit）"""
    if not project_ids:
        return
    script_ids = (
        await db.execute(
            select(AudioBookScript.id).where(AudioBookScript.project_id.in_(project_ids))
        )
    ).scalars().all()
    if not script_ids:
        return
    await db.execute(
        delete(AudioBookScripAudio).where(AudioBookScripAudio.script_id.in_(script_ids))
    )
    await db.execute(
        delete(AudioBookScript).where(AudioBookScript.project_id.in_(project_ids))
    )
