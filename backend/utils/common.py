import json
import shutil
import asyncio
import uuid
from pathlib import Path
from config.store import conf
from typing import Dict, List
from fastapi import UploadFile




def generate_script_name():
    return uuid.uuid4().hex + ".json"

def generate_voice_name():
    return uuid.uuid4().hex + ".wav"

def generate_audio_name():
    return uuid.uuid4().hex + ".wav"

def write_sync(file_path,data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def read_sync(fp: Path):
    with open(fp, 'r', encoding='utf-8') as f:
        return json.load(f)

async def rm_dir(dir_path: Path):
    """异步删除目录"""
    if dir_path.exists() and dir_path.is_dir():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, shutil.rmtree, dir_path)

async def rm_scripts(chapter_ids: List[int]):
    """批量删除脚本目录"""
    task_list = []
    for chapter_id in chapter_ids:
        sub_dir = f"chapter_{chapter_id}"
        dir_path = conf.SCRIPT_DIR / sub_dir
        task_list.append(rm_dir(dir_path))
    if task_list:
        await asyncio.gather(*task_list)

async def rm_characters(character_stage_ids: List[int]):
    """批量删除角色阶段目录"""
    task_list = []
    for character_stage_id in character_stage_ids:
        sub_dir = f"characterstage_{character_stage_id}"
        dir_path = conf.CHARACTER_DIR / sub_dir
        task_list.append(rm_dir(dir_path))
    if task_list:
        await asyncio.gather(*task_list)

async def save_upload_file(upload_file: UploadFile, destination: Path):
    """异步保存上传文件"""
    loop = asyncio.get_running_loop()
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = await upload_file.read()
    # 使用 lambda 包装写入操作
    await loop.run_in_executor(None, lambda p=destination, c=content: p.write_bytes(c))



async def read_json_file(file_path: Path) -> Dict:
    """
    异步读取JSON文件
    """
    loop = asyncio.get_running_loop()
    # 在默认的线程池执行器中运行同步读取函数
    return await loop.run_in_executor(None, read_sync, file_path)

async def save_json_file(file_path: Path, data: Dict):
    """异步保存JSON文件"""
    loop = asyncio.get_running_loop()
    # 目录不存在时先创建（与 save_upload_file 同一约定）
    file_path.parent.mkdir(parents=True, exist_ok=True)
    await loop.run_in_executor(None, write_sync,file_path,data)

async def remove_file(file_path: Path):
    """异步删除单个文件"""
    if isinstance(file_path,str):
        file_path = Path(file_path)
    if file_path.exists() and file_path.is_file():
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, file_path.unlink)

async def remove_files(file_paths: List[Path]):
    """批量删除脚本目录"""
    task_list = []
    for path in file_paths:
        task_list.append(remove_file(path))
    if task_list:
        await asyncio.gather(*task_list)
