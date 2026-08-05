"""中文文献检索数据模型.

定义中文多源检索（CNKI + 万方 + NCPSSD）的统一数据模型。
检索编排逻辑已合并到 LiteratureSearchManager（见 search.py，
ADR-004 检索层合并）。

数据模型说明：
- UnifiedChinesePaper: 统一中文论文格式（CNKI/万方/NCPSSD 通用）
- ChineseSearchResult: 统一中文检索结果（含三源计数与合并论文）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scholarpilot.mcp.servers.cnki import CNKISearchResult
from scholarpilot.mcp.servers.ncpssd import NCPSSDSearchResult
from scholarpilot.mcp.servers.wanfang import WanfangSearchResult


@dataclass
class UnifiedChinesePaper:
    """统一的中文论文数据模型.

    无论来自 CNKI、万方还是 NCPSSD，都转换为统一格式。
    """

    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    doi: str = ""
    url: str = ""
    source: str = ""  # "cnki" / "wanfang" / "ncpssd"
    cited_count: int = 0
    download_count: int = 0
    fund: str = ""
    # 万方扩展字段(其他源为空)
    paper_type: str = ""  # 期刊论文/学位论文/会议论文
    institution: str = ""  # 作者机构
    degree_level: str = ""  # 学位论文级别(硕士/博士)
    core_tags: list[str] = field(default_factory=list)  # 核心期刊标签
    issue: str = ""
    page_range: str = ""
    language: str = ""
    issn: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "journal": self.journal,
            "year": self.year,
            "abstract": self.abstract,
            "keywords": self.keywords,
            "doi": self.doi,
            "url": self.url,
            "source": self.source,
            "cited_count": self.cited_count,
            "download_count": self.download_count,
            "fund": self.fund,
            "paper_type": self.paper_type,
            "institution": self.institution,
            "degree_level": self.degree_level,
            "core_tags": self.core_tags,
            "issue": self.issue,
            "page_range": self.page_range,
            "language": self.language,
            "issn": self.issn,
        }


@dataclass
class ChineseSearchResult:
    """统一中文检索结果。"""

    query: str = ""
    cnki_count: int = 0  # CNKI 检索到的总数
    wanfang_count: int = 0  # 万方检索到的总数
    ncpssd_count: int = 0  # NCPSSD 检索到的总数
    papers: list[UnifiedChinesePaper] = field(default_factory=list)
    cnki_result: CNKISearchResult | None = None
    wanfang_result: WanfangSearchResult | None = None
    ncpssd_result: NCPSSDSearchResult | None = None

    @property
    def total_count(self) -> int:
        """总匹配数（CNKI + 万方 + NCPSSD）。"""
        return self.cnki_count + self.wanfang_count + self.ncpssd_count

    @property
    def returned_count(self) -> int:
        """实际返回的论文数。"""
        return len(self.papers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "cnki_count": self.cnki_count,
            "wanfang_count": self.wanfang_count,
            "ncpssd_count": self.ncpssd_count,
            "total_count": self.total_count,
            "returned_count": self.returned_count,
            "papers": [p.to_dict() for p in self.papers],
        }
