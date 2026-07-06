"""PaperSpec - 论文规格模型.

描述用户对论文的具体要求和约束，作为 Agent 规划的输入。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class PaperType(str, Enum):
    """论文类型枚举."""

    JOURNAL = "journal"
    CONFERENCE = "conference"
    THESIS = "thesis"
    REPORT = "report"
    REVIEW = "review"
    PREPRINT = "preprint"


class CitationStyle(str, Enum):
    """引用格式枚举."""

    APA = "apa"
    MLA = "mla"
    CHICAGO = "chicago"
    IEEE = "ieee"
    ACM = "acm"
    GB_T7714 = "gb_t7714"


class Language(str, Enum):
    """论文语言枚举."""

    ENGLISH = "en"
    CHINESE = "zh"


class PaperSpec(BaseModel):
    """论文规格.

    定义用户对论文的要求，包括主题、类型、格式、约束等。

    Attributes:
        topic: 论文主题/研究方向.
        paper_type: 论文类型.
        language: 论文语言.
        target_venue: 目标期刊/会议名称.
        word_count: 目标字数.
        citation_style: 引用格式.
        outline: 用户提供的大纲（可选）.
        references: 用户提供的参考文献（可选）.
        constraints: 额外约束和要求.
        description: 用户的详细描述.
    """

    topic: str = ""
    paper_type: PaperType = PaperType.JOURNAL
    language: Language = Language.ENGLISH
    target_venue: Optional[str] = None
    word_count: Optional[int] = None
    citation_style: CitationStyle = CitationStyle.APA
    outline: Optional[str] = None
    references: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "topic": "Large Language Models in Scientific Discovery",
                    "paper_type": "journal",
                    "language": "en",
                    "word_count": 8000,
                    "citation_style": "apa",
                    "description": "A survey of how LLMs are being used to accelerate scientific research.",
                }
            ]
        }
