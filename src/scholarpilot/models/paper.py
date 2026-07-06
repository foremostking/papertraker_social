"""Paper 数据模型.

描述一篇完整论文的结构和内容。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class PaperStatus(str, Enum):
    """论文状态枚举."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    UNDER_REVIEW = "under_review"
    REVISING = "revising"
    COMPLETED = "completed"


class Section(BaseModel):
    """论文章节.

    Attributes:
        title: 章节标题.
        heading_level: 标题层级（1-6）.
        content: 章节正文内容（Markdown 格式）.
        order: 章节顺序.
        subsections: 子章节列表.
    """

    title: str
    heading_level: int = Field(default=1, ge=1, le=6)
    content: str = ""
    order: int = 0
    subsections: list[Section] = Field(default_factory=list)

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "title": "Introduction",
                    "heading_level": 1,
                    "content": "This paper explores...",
                    "order": 1,
                }
            ]
        }


class Reference(BaseModel):
    """参考文献条目.

    Attributes:
        key: 引用键（如 "smith2024"）.
        title: 文献标题.
        authors: 作者列表.
        year: 发表年份.
        source: 来源（期刊名/会议名/URL）.
        doi: DOI 标识符.
        abstract: 摘要.
        ref_type: 文献类型.
    """

    key: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    source: str = ""
    doi: Optional[str] = None
    abstract: str = ""
    ref_type: str = "article"  # article, book, conference, preprint, etc.


class Paper(BaseModel):
    """完整论文模型.

    Attributes:
        title: 论文标题.
        abstract: 摘要.
        authors: 作者列表.
        keywords: 关键词列表.
        sections: 章节列表.
        references: 参考文献列表.
        status: 当前状态.
        created_at: 创建时间.
        updated_at: 更新时间.
        metadata: 额外元数据.
    """

    title: str = ""
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    status: PaperStatus = PaperStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)
