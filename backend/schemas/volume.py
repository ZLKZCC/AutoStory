from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional


# ── 卷基础信息 ─────────────────────────────────
class VolumeBase(BaseModel):
    """卷基类（共享字段）"""
    volume_index: int = Field(..., ge=0, description="卷序号 (从 0 开始)")
    name: str = Field(..., min_length=1, max_length=100, description="卷名")
    summary: str = Field("", max_length=2000, description="卷摘要")


class VolumeCreate(VolumeBase):
    """创建卷请求体"""
    project_id: int = Field(..., gt=0, description="项目 ID")
    chapter_start: int = Field(..., ge=-1, description="起始章节索引 (0-based)")
    chapter_end: int = Field(..., ge=-1, description="结束章节索引 (0-based)")
    
    @field_validator('chapter_end')
    @classmethod
    def validate_chapter_order(cls, v, info):
        if 'chapter_start' in info.data and v < info.data['chapter_start']:
            raise ValueError("结束章节索引不能小于起始章节索引")
        return v


class VolumeUpdate(BaseModel):
    """更新卷请求体"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="卷名")
    summary: Optional[str] = Field(None, max_length=2000, description="卷摘要")
    # chapter_start/end 不允许修改（已创建的卷边界应保持稳定）


# ── 卷详情响应 ─────────────────────────────────
class VolumeDetail(VolumeBase):
    """卷详情"""
    id: int = Field(..., gt=0, description="分卷 ID")
    project_id: int = Field(..., gt=0, description="项目 ID")
    # ge=-1：空壳卷（[-1,-1] 占位，章节入卷时物化）是合法落库状态，须与 VolumeCreate 同口径
    chapter_start: int = Field(..., ge=-1, description="起始章节索引 (0-based)")
    chapter_end: int = Field(..., ge=-1, description="结束章节索引 (0-based)")
    summary_generated_at: Optional[datetime] = Field(None, description="摘要生成时间")
    
    class Config:
        from_attributes = True


class VolumeWithStats(VolumeDetail):
    """卷详情 + 统计信息"""
    chapter_count: int = Field(..., ge=0, description="卷内章节数量")
    total_word_count: int = Field(..., ge=0, description="卷内总字数")
