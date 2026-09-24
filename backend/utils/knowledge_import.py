import asyncio
import uuid
from typing import Dict, Any, List, Optional, Tuple

from crud.CHROMA_knowledges import (
    get_next_chunk_id,
    add_knowledge_segments
)

# 导入任务进度注册表：task_id -> 进度快照（单用户内存态，随进程存活）
IMPORT_TASKS: Dict[str, Dict[str, Any]] = {}

# 全局导入锁：串行化向量库写入，避免 Chroma sqlite 并发写锁竞争
_import_lock = asyncio.Lock()

# 每批入库的切片数：批太小轮询开销大，批太大进度更新不及时
CHUNK_BATCH = 32

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = (".txt", ".md", ".docx")


def _decode_text(raw: bytes) -> str:
    """
    解码文本：中文小说 txt 常见 GBK 编码，utf-8 失败时回退
    """
    for encoding in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    # 兜底：忽略非法字符
    return raw.decode("utf-8", errors="ignore")


def _parse_docx(raw: bytes) -> str:
    """
    解析 docx 正文：依赖 python-docx，未安装时给出明确错误
    """
    import io
    try:
        from docx import Document
    except ImportError:
        raise ValueError("docx 文件解析需要安装 python-docx（pip install python-docx）")

    document = Document(io.BytesIO(raw))
    return "\n".join(p.text for p in document.paragraphs)


def _parse_file(filename: str, raw: bytes) -> str:
    """
    同步解析文件内容为纯文本
    """
    lower = filename.lower()
    if lower.endswith(SUPPORTED_EXTENSIONS[:2]):
        return _decode_text(raw)
    if lower.endswith(".docx"):
        return _parse_docx(raw)
    raise ValueError(f"不支持的文件类型：{filename}（支持 {', '.join(SUPPORTED_EXTENSIONS)}）")


def _split_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    同步切片：滑动窗口按字符切，步长 = chunk_size - overlap
    """
    text = text.strip()
    if not text:
        return []

    step = max(1, chunk_size - overlap)
    chunks = []
    start = 0
    while start < len(text):
        piece = text[start:start + chunk_size].strip()
        if piece:
            chunks.append(piece)
        # 剩余不足一个完整窗口时结束
        if start + chunk_size >= len(text):
            break
        start += step
    return chunks


def _split_paragraphs(text: str, filename: str) -> List[str]:
    """
    非切片模式：按段落切分，一段一条

    各文件类型的段落来源：
    - txt：连续换行（含 \r\n / \n）分隔的段落
    - md：同 txt（解析前已保留原文，空行是自然的段落边界）
    - docx：_parse_docx 已按段落 join("\n")，每行即一个段落

    过滤纯空白段（空行、仅空格/全角空格）；保留段内原有的单换行（软换行不拆段）。
    """
    # 统一换行符后按连续换行（至少一个 \n）切：单个 \n 在 txt 里通常是同段换行，
    # 但 docx 已把每个段落转成独立行，此处按行切即可覆盖两类来源
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    paragraphs = []
    for line in lines:
        para = line.strip()
        if para:
            paragraphs.append(para)
    return paragraphs


def create_import_task(
        material_id: int,
        material_name: str,
        files: List[Tuple[str, str, bytes]],
        chunk_model: bool = True,
        chunk_size: int = 400,
        overlap: int = 200
) -> str:
    """
    创建导入任务并后台执行

    Args:
        material_id (int): 素材库id
        material_name (str): 素材库名
        files (List[Tuple[str, str, bytes]]): (素材名, 文件名, 文件字节) 列表
        chunk_model (bool): 切片模式（False 时按段落切分，一段一条）
        chunk_size (int): 切片大小
        overlap (int): 切片重合大小

    Returns:
        str: task_id，用于轮询进度
    """
    task_id = uuid.uuid4().hex[:16]
    IMPORT_TASKS[task_id] = {
        "status": "processing",
        "total_files": len(files),
        "processed_files": 0,
        "current_file": "",
        "progress": 0,
        "imported": 0,
        "error": None
    }

    asyncio.get_event_loop().create_task(
        _run_import_task(task_id, material_id, material_name, files, chunk_model, chunk_size, overlap)
    )
    return task_id


def get_import_progress(task_id: str) -> Optional[Dict[str, Any]]:
    """
    查询导入任务进度快照
    """
    return IMPORT_TASKS.get(task_id)


async def _run_import_task(
    task_id: str,
    material_id: int,
    material_name: str,
    files: List[Tuple[str, str, bytes]],
    chunk_model: bool,
    chunk_size: int,
    overlap: int
):
    """
    导入任务主体：逐文件 解析 → 切片（按当前模式）→ 分批入库，实时更新进度
    """
    task = IMPORT_TASKS[task_id]
    loop = asyncio.get_event_loop()

    try:
        # 锁内串行处理，保证向量库写入互斥
        async with _import_lock:
            for file_index, (knowledge_name, filename, raw) in enumerate(files):
                task["current_file"] = filename

                # 解析在 executor 中执行，不阻塞事件循环
                text = await loop.run_in_executor(None, _parse_file, filename, raw)

                # 切片模式：滑动窗口切片；非切片模式：按段落切分，一段一条
                if chunk_model:
                    chunks = await loop.run_in_executor(
                        None, _split_text, text, chunk_size, overlap
                    )
                else:
                    chunks = await loop.run_in_executor(
                        None, _split_paragraphs, text, filename
                    )

                # 起始编号一次查询，后续批次递增传递
                next_chunk_id = await get_next_chunk_id(material_id, knowledge_name)
                total_batches = (len(chunks) + CHUNK_BATCH - 1) // CHUNK_BATCH

                for batch_index in range(total_batches):
                    batch = chunks[batch_index * CHUNK_BATCH:(batch_index + 1) * CHUNK_BATCH]
                    await add_knowledge_segments(
                        material_id,
                        material_name,
                        knowledge_name,
                        batch,
                        start_chunk_id=next_chunk_id
                    )
                    next_chunk_id += len(batch)

                    # 进度 = 已完成文件数 + 当前文件内批次占比，折算为总量百分比
                    file_progress = (batch_index + 1) / max(1, total_batches)
                    task["progress"] = int(
                        (file_index + file_progress) / task["total_files"] * 100
                    )

                task["processed_files"] += 1
                task["imported"] += len(chunks)

            task["status"] = "completed"
            task["progress"] = 100
            task["current_file"] = ""
    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)
