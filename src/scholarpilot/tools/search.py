"""统一文献检索管理器.

整合 CNKI、Semantic Scholar 和 arXiv 三个检索引擎，
提供统一的检索接口，自动调度多源检索。

Usage:
    manager = LiteratureSearchManager(
        cnki_cookie="...",
        ss_api_key="...",
    )
    results = await manager.search_all(
        topic="地方政府债务",
        region="中国",
        content="空间溢出",
        year_start="2015",
        year_end="2024",
    )
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from scholarpilot.mcp.servers.cnki import CNKISearchResult, CNKIPaper
from scholarpilot.mcp.servers.semantic_scholar import (
    SemanticScholarEngine,
    SSSearchResult,
    SSPaper,
)
from scholarpilot.mcp.servers.arxiv import ArxivEngine, ArxivSearchResult, ArxivPaper
from scholarpilot.tools.chinese_search import (
    ChineseLiteratureManager,
    ChineseSearchResult,
    UnifiedChinesePaper,
)

logger = logging.getLogger(__name__)


@dataclass
class UnifiedPaper:
    """统一的论文数据模型.

    整合来自不同源的论文数据，统一字段。
    """

    source: str = ""  # cnki / semantic_scholar / arxiv
    title: str = ""
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    venue: str = ""  # 期刊/来源
    citation_count: int = 0
    url: str = ""
    doi: str = ""
    arxiv_id: str = ""
    keywords: list[str] = field(default_factory=list)
    language: str = ""  # zh / en
    raw: dict[str, Any] = field(default_factory=dict)  # 原始数据

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "citation_count": self.citation_count,
            "url": self.url,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "keywords": self.keywords,
            "language": self.language,
        }


@dataclass
class UnifiedSearchResult:
    """多源统一检索结果."""

    topic: str = ""
    chinese_result: Optional[ChineseSearchResult] = None  # 中文文献（CNKI+NCPSSD）
    ss_result: Optional[SSSearchResult] = None
    arxiv_result: Optional[ArxivSearchResult] = None
    all_papers: list[UnifiedPaper] = field(default_factory=list)
    total_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "chinese": self.chinese_result.to_dict() if self.chinese_result else None,
            "semantic_scholar": self.ss_result.to_dict() if self.ss_result else None,
            "arxiv": self.arxiv_result.to_dict() if self.arxiv_result else None,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.all_papers],
        }


class LiteratureSearchManager:
    """统一文献检索管理器.

    整合 CNKI、Semantic Scholar 和 arXiv 三个引擎，
    提供统一的检索接口。

    对于英文文献源（Semantic Scholar、arXiv），自动将中文主题翻译为英文。
    内置财政学/经济学常见术语中英映射表，也支持传入英文主题。

    Usage:
        manager = LiteratureSearchManager(
            cnki_cookie="your_cookie",
            ss_api_key="your_key",
        )
        results = await manager.search_all(
            topic="地方政府债务",
            region="中国",
            content="空间溢出",
            year_start="2015",
            year_end="2024",
        )
    """

    # 财政学/经济学常见术语中英映射表
    TERM_MAP: dict[str, str] = {
        # 核心概念
        "地方政府债务": "local government debt",
        "政府债务": "government debt",
        "债务风险": "debt risk",
        "财政风险": "fiscal risk",
        "财政政策": "fiscal policy",
        "财政分权": "fiscal decentralization",
        "财政支出": "fiscal expenditure",
        "财政收入": "fiscal revenue",
        "税收": "taxation",
        "税制改革": "tax reform",
        "预算": "budget",
        "预算绩效": "budget performance",
        "零基预算": "zero-based budgeting",
        "转移支付": "transfer payment",
        "土地财政": "land finance",
        "城投债": "urban investment bond",
        "专项债": "special purpose bond",
        "隐性债务": "implicit debt",
        "债务置换": "debt swap",
        # 区域/对象
        "中国": "China",
        "省级": "provincial",
        "市级": "municipal",
        "县级": "county-level",
        "地方政府": "local government",
        "中央政府": "central government",
        # 研究内容/方法
        "空间溢出": "spatial spillover",
        "溢出效应": "spillover effect",
        "经济增长": "economic growth",
        "高质量发展": "high-quality development",
        "实证": "empirical",
        "面板数据": "panel data",
        "空间计量": "spatial econometrics",
        "双重差分": "difference-in-differences",
        "工具变量": "instrumental variable",
        "固定效应": "fixed effects",
        "随机效应": "random effects",
        # 宏观经济
        "通货膨胀": "inflation",
        "货币政策": "monetary policy",
        "汇率": "exchange rate",
        "贸易": "trade",
        "消费": "consumption",
        "投资": "investment",
        "就业": "employment",
        "收入分配": "income distribution",
        "共同富裕": "common prosperity",
        # 公共管理
        "公共服务": "public service",
        "环境治理": "environmental governance",
        "碳中和": "carbon neutrality",
        "数字化转型": "digital transformation",
    }

    def __init__(
        self,
        cnki_cookie: str = "",
        ss_api_key: str = "",
        use_playwright: bool = False,
        timeout: int = 30,
    ) -> None:
        """初始化统一文献检索管理器.

        Args:
            cnki_cookie: CNKI 登录 Cookie（可选）。
            ss_api_key: Semantic Scholar API Key。
            use_playwright: 是否启用 Playwright CNKI 增强（需安装 playwright）。
            timeout: 请求超时秒数。
        """
        # 中文文献：ChineseLiteratureManager（NCPSSD + CNKI 多源降级）
        self.chinese_manager = ChineseLiteratureManager(
            cnki_cookie=cnki_cookie,
            use_playwright=use_playwright,
            timeout=timeout,
        )
        self.ss_engine = SemanticScholarEngine(api_key=ss_api_key, timeout=timeout)
        self.arxiv_engine = ArxivEngine(timeout=timeout)

    def _translate_to_english(self, text: str) -> str:
        """将中文术语翻译为英文（基于术语映射表）.

        对于映射表中已有的术语，直接替换。对于未映射的中文，
        保留原文（Semantic Scholar 也能处理部分中文搜索）。

        Args:
            text: 中文文本。

        Returns:
            英文搜索词。
        """
        result = text
        # 按中文短语长度降序排列，避免短词先替换导致长词匹配失败
        sorted_terms = sorted(self.TERM_MAP.keys(), key=len, reverse=True)
        for cn_term, en_term in self.TERM_MAP.items():
            if cn_term in result:
                result = result.replace(cn_term, en_term)

        # 清理多余空格
        result = " ".join(result.split())
        return result

    async def close(self) -> None:
        """关闭所有引擎."""
        await self.chinese_manager.close()
        await self.ss_engine.close()
        await self.arxiv_engine.close()

    async def search_all(
        self,
        topic: str,
        region: str = "中国",
        content: str = "",
        year_start: str = "2015",
        year_end: str = "2024",
        max_per_source: int = 20,
        include_arxiv: bool = True,
    ) -> UnifiedSearchResult:
        """执行多源统一检索.

        同时检索 CNKI（中文）、Semantic Scholar（英文）和 arXiv（预印本），
        并将结果整合为统一的论文列表。

        Args:
            topic: 核心主题（中文，如"地方政府债务"）。
            region: 研究区域。
            content: 研究内容。
            year_start: 起始年份。
            year_end: 结束年份。
            max_per_source: 每个数据源的最大返回数。
            include_arxiv: 是否检索 arXiv。

        Returns:
            UnifiedSearchResult: 统一检索结果。
        """
        result = UnifiedSearchResult(topic=topic)

        # 并行检索中文文献（NCPSSD+CNKI）和 Semantic Scholar
        # arXiv 需要串行（3秒间隔限制），放在后面
        tasks = [
            self._search_chinese(topic, region, content, year_start, year_end, max_per_source),
            self._search_semantic_scholar(topic, region, content, year_start, year_end, max_per_source),
        ]

        chinese_result, ss_result = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理中文文献结果
        if isinstance(chinese_result, Exception):
            logger.error(f"Chinese literature search error: {chinese_result}")
            result.chinese_result = ChineseSearchResult(query=topic)
        else:
            result.chinese_result = chinese_result

        # 处理 Semantic Scholar 结果
        if isinstance(ss_result, Exception):
            logger.error(f"Semantic Scholar search error: {ss_result}")
            result.ss_result = SSSearchResult(query=topic, total_count=0)
        else:
            result.ss_result = ss_result

        # 串行检索 arXiv
        if include_arxiv:
            arxiv_result = await self._search_arxiv(topic, content, max_per_source)
            result.arxiv_result = arxiv_result

        # 整合所有论文
        result.all_papers = self._merge_papers(result)
        result.total_count = len(result.all_papers)

        return result

    async def _search_chinese(
        self, topic: str, region: str, content: str,
        year_start: str, year_end: str, max_results: int,
    ) -> ChineseSearchResult:
        """执行中文文献检索（NCPSSD + CNKI 多源降级）.

        使用 ChineseLiteratureManager 并行检索 NCPSSD（免费、稳定）
        和 CNKI（可选 Playwright 增强），自动合并去重。
        """
        return await self.chinese_manager.search(
            topic=topic,
            region=region,
            content=content,
            year_start=year_start,
            year_end=year_end,
            max_per_source=max_results,
        )

    async def _search_semantic_scholar(
        self, topic: str, region: str, content: str,
        year_start: str, year_end: str, max_results: int,
    ) -> SSSearchResult:
        """执行 Semantic Scholar 检索.

        自动将中文主题翻译为英文，因为 Semantic Scholar 主要是英文文献库。
        """
        # 翻译为英文
        en_topic = self._translate_to_english(topic)
        en_region = self._translate_to_english(region)
        en_content = self._translate_to_english(content)

        query = SemanticScholarEngine.build_query_from_topic(
            topic=en_topic, region=en_region, content=en_content,
        )
        year_filter = f"{year_start}-{year_end}" if year_start and year_end else ""

        return await self.ss_engine.search(
            query=query,
            limit=max_results,
            year=year_filter,
            fields_of_study="Economics",
        )

    async def _search_arxiv(
        self, topic: str, content: str, max_results: int,
    ) -> ArxivSearchResult:
        """执行 arXiv 检索.

        自动将中文主题翻译为英文，因为 arXiv 主要是英文预印本库。
        """
        # 翻译为英文
        en_topic = self._translate_to_english(topic)

        # 构建 arXiv 查询串（使用经济学分类）
        query = ArxivEngine.build_query(
            all_fields=en_topic,
            category="econ.GN",  # General Economics
        )

        if not query:
            query = f"all:{en_topic}"

        return await self.arxiv_engine.search(
            search_query=query,
            max_results=max_results,
            sort_by="submittedDate",
        )

    def _merge_papers(self, result: UnifiedSearchResult) -> list[UnifiedPaper]:
        """整合来自不同源的论文为统一列表."""
        papers: list[UnifiedPaper] = []

        # 中文文献（NCPSSD + CNKI 合并后的结果）
        if result.chinese_result:
            for p in result.chinese_result.papers:
                papers.append(UnifiedPaper(
                    source=p.source,  # "cnki" 或 "ncpssd"
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=p.year,
                    venue=p.journal,
                    url=p.url,
                    doi=p.doi,
                    keywords=p.keywords,
                    citation_count=p.cited_count,
                    language="zh",
                    raw=p.to_dict(),
                ))

        # Semantic Scholar 论文
        if result.ss_result:
            for p in result.ss_result.papers:
                papers.append(UnifiedPaper(
                    source="semantic_scholar",
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=str(p.year) if p.year else "",
                    venue=p.venue or p.journal_name,
                    citation_count=p.citation_count,
                    url=p.url,
                    doi=p.doi,
                    arxiv_id=p.arxiv_id,
                    keywords=p.fields_of_study,
                    language="en",
                    raw=p.to_dict(),
                ))

        # arXiv 论文
        if result.arxiv_result:
            for p in result.arxiv_result.papers:
                papers.append(UnifiedPaper(
                    source="arxiv",
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=p.published[:4] if p.published else "",
                    venue=p.primary_category,
                    url=p.abs_url,
                    doi=p.doi,
                    arxiv_id=p.arxiv_id,
                    keywords=p.categories,
                    language="en",
                    raw=p.to_dict(),
                ))

        return papers

    def format_papers_for_display(self, papers: list[UnifiedPaper], max_display: int = 30) -> str:
        """格式化论文列表用于显示."""
        lines = []

        # 按来源分组
        cnki_papers = [p for p in papers if p.source == "cnki"]
        ncpssd_papers = [p for p in papers if p.source == "ncpssd"]
        ss_papers = [p for p in papers if p.source == "semantic_scholar"]
        arxiv_papers = [p for p in papers if p.source == "arxiv"]

        if cnki_papers:
            lines.append(f"\n### CNKI 中文文献 ({len(cnki_papers)} 篇)")
            for i, p in enumerate(cnki_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year})")

        if ncpssd_papers:
            lines.append(f"\n### NCPSSD 中文文献 ({len(ncpssd_papers)} 篇)")
            for i, p in enumerate(ncpssd_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year})")

        if ss_papers:
            lines.append(f"\n### Semantic Scholar 英文文献 ({len(ss_papers)} 篇)")
            for i, p in enumerate(ss_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                cited = f" [cited: {p.citation_count}]" if p.citation_count else ""
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year}){cited}")

        if arxiv_papers:
            lines.append(f"\n### arXiv 预印本 ({len(arxiv_papers)} 篇)")
            for i, p in enumerate(arxiv_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                arxiv_id = f" [{p.arxiv_id}]" if p.arxiv_id else ""
                lines.append(f"{i+1}. {p.title} - {authors} ({p.year}){arxiv_id}")

        return "\n".join(lines) if lines else "暂无检索结果"
