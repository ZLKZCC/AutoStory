from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ChapterBase(BaseModel):
    chapter_title: str = Field(..., description="章节标题")
    chapter_index: int = Field(-1, description="章节索引")
    chapter_summary: str = Field("", description="章节摘要总结")
    model_config = ConfigDict(from_attributes=True)

class ChapterCreate(BaseModel):
    chapter_title: str = Field(..., description="章节标题")
    chapter_index: int = Field(-1, description="章节索引")
    chapter_summary: str = Field("", description="章节摘要总结")
    chapter_content: str = Field("", description="章节内容")
    model_config = ConfigDict(from_attributes=True)

class Chaptershot(ChapterBase):
    id: int = Field(..., description="章节id")
    # 正文最近实质变更时间：列表带上它，前端据此判断某章正文是否被 agent 改过，
    # 只失效"变新"的那章本地正文缓存（选中章重拉），避免全量重拉所有正文。
    content_updated_at: Optional[datetime] = Field(None, description="正文最近实质变更时间")
    # 真实字数（取自模型 word_count 属性）：列表带上它，前端左树无需打开章节即可显示字数
    word_count: int = Field(0, description="正文字数")
class ChapterDetail(ChapterBase):
    id: int = Field(..., description="章节id")
    chapter_content: str = Field("", description="章节内容")
