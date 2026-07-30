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
from scholarpilot.mcp.servers.wos import WoSEngine, WoSSearchResult, WoSPaper
from scholarpilot.mcp.servers.chinaxiv import ChinaXivEngine, ChinaXivSearchResult, ChinaXivPaper
from scholarpilot.mcp.servers.pubscholar import PubScholarEngine, PubScholarSearchResult, PubScholarPaper
from scholarpilot.tools.chinese_search import (
    ChineseLiteratureManager,
    ChineseSearchResult,
    UnifiedChinesePaper,
)
from scholarpilot.utils.vpn import VPNStatus

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
    chinese_result: Optional[ChineseSearchResult] = None  # 中文文献（CNKI+万方+NCPSSD）
    ss_result: Optional[SSSearchResult] = None
    arxiv_result: Optional[ArxivSearchResult] = None
    wos_result: Optional[WoSSearchResult] = None  # Web of Science（VPN/Session）
    chinaxiv_result: Optional[ChinaXivSearchResult] = None  # ChinaXiv 预印本
    pubscholar_result: Optional[PubScholarSearchResult] = None  # PubScholar OA
    all_papers: list[UnifiedPaper] = field(default_factory=list)
    total_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "chinese": self.chinese_result.to_dict() if self.chinese_result else None,
            "semantic_scholar": self.ss_result.to_dict() if self.ss_result else None,
            "arxiv": self.arxiv_result.to_dict() if self.arxiv_result else None,
            "wos": self.wos_result.to_dict() if self.wos_result else None,
            "chinaxiv": self.chinaxiv_result.to_dict() if self.chinaxiv_result else None,
            "pubscholar": self.pubscholar_result.to_dict() if self.pubscholar_result else None,
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
        wos_api_key: str = "",
        wos_sid: str = "",
        use_playwright: bool = False,
        timeout: int = 30,
        vpn_status: Optional[VPNStatus] = None,
    ) -> None:
        """初始化统一文献检索管理器.

        Args:
            cnki_cookie: CNKI 登录 Cookie（可选）。
            ss_api_key: Semantic Scholar API Key。
            wos_api_key: Web of Science Clarivate API Key（可选，优先使用）。
            wos_sid: WoS Session ID（从浏览器登录获取，可选）。
            use_playwright: 是否启用 Playwright CNKI 增强（需安装 playwright）。
            timeout: 请求超时秒数。
            vpn_status: VPN 连接状态。传入已检测的 VPNStatus，
                        CNKI 和万方将使用机构 IP 认证模式。
                        如不传入，需在调用 search_all 前手动设置。
        """
        # 中文文献：ChineseLiteratureManager（NCPSSD + CNKI + 万方 多源降级）
        # 传入 vpn_status 启用 CNKI/万方 机构 IP 认证
        self.chinese_manager = ChineseLiteratureManager(
            cnki_cookie=cnki_cookie,
            use_playwright=use_playwright,
            timeout=timeout,
            vpn_status=vpn_status,
        )
        self.ss_engine = SemanticScholarEngine(api_key=ss_api_key, timeout=timeout)
        self.arxiv_engine = ArxivEngine(timeout=timeout)
        # WoS 引擎：双模式（API Key 优先，其次 SID）
        self.wos_engine = WoSEngine(
            api_key=wos_api_key,
            sid=wos_sid,
            timeout=timeout,
        )
        # ChinaXiv 预印本引擎（免费，无需认证）
        self.chinaxiv_engine = ChinaXivEngine(timeout=timeout)
        # PubScholar OA 引擎（免费，SHA1 签名认证）
        self.pubscholar_engine = PubScholarEngine(timeout=timeout)

        # 保存 VPN 状态
        self.vpn_status = vpn_status

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
        await self.wos_engine.close()
        await self.chinaxiv_engine.close()
        await self.pubscholar_engine.close()

    async def search_all(
        self,
        topic: str,
        region: str = "中国",
        content: str = "",
        year_start: str = "2015",
        year_end: str = "2024",
        max_per_source: int = 20,
        include_arxiv: bool = True,
        include_wos: bool = True,
        include_oa: bool = True,
    ) -> UnifiedSearchResult:
        """执行多源统一检索.

        同时检索中文文献（CNKI+万方+NCPSSD）、Semantic Scholar、
        Web of Science（如已配置）、ChinaXiv、PubScholar 和 arXiv，
        并将结果整合为统一的论文列表。

        Args:
            topic: 核心主题（中文，如"地方政府债务"）。
            region: 研究区域。
            content: 研究内容。
            year_start: 起始年份。
            year_end: 结束年份。
            max_per_source: 每个数据源的最大返回数。
            include_arxiv: 是否检索 arXiv。
            include_wos: 是否检索 Web of Science（需配置 API Key 或 SID）。
            include_oa: 是否检索 OA 源（ChinaXiv + PubScholar）。

        Returns:
            UnifiedSearchResult: 统一检索结果。
        """
        result = UnifiedSearchResult(topic=topic)

        # 构建并行检索任务（arXiv 串行，因为3秒间隔限制）
        task_names: list[str] = ["chinese", "ss"]
        task_coros: list = [
            self._search_chinese(topic, region, content, year_start, year_end, max_per_source),
            self._search_semantic_scholar(topic, region, content, year_start, year_end, max_per_source),
        ]

        # WoS 仅在引擎可用时加入
        if include_wos and self.wos_engine.is_available:
            task_names.append("wos")
            task_coros.append(self._search_wos(topic, region, content, year_start, year_end, max_per_source))

        # OA 源（ChinaXiv + PubScholar）
        if include_oa:
            task_names.append("chinaxiv")
            task_coros.append(self._search_chinaxiv(topic, year_start, year_end, max_per_source))
            task_names.append("pubscholar")
            task_coros.append(self._search_pubscholar(topic, max_per_source))

        # 并行执行所有任务
        task_results = await asyncio.gather(*task_coros, return_exceptions=True)

        # 按名称处理结果
        for name, res in zip(task_names, task_results):
            if name == "chinese":
                if isinstance(res, Exception):
                    logger.error(f"Chinese literature search error: {res}")
                    result.chinese_result = ChineseSearchResult(query=topic)
                else:
                    result.chinese_result = res
            elif name == "ss":
                if isinstance(res, Exception):
                    logger.error(f"Semantic Scholar search error: {res}")
                    result.ss_result = SSSearchResult(query=topic, total_count=0)
                else:
                    result.ss_result = res
            elif name == "wos":
                if isinstance(res, Exception):
                    logger.error(f"WoS search error: {res}")
                    result.wos_result = WoSSearchResult(query=topic, error=str(res))
                else:
                    result.wos_result = res
            elif name == "chinaxiv":
                if isinstance(res, Exception):
                    logger.error(f"ChinaXiv search error: {res}")
                    result.chinaxiv_result = ChinaXivSearchResult(query=topic, error=str(res))
                else:
                    result.chinaxiv_result = res
            elif name == "pubscholar":
                if isinstance(res, Exception):
                    logger.error(f"PubScholar search error: {res}")
                    result.pubscholar_result = PubScholarSearchResult(query=topic, error=str(res))
                else:
                    result.pubscholar_result = res

        # 串行检索 arXiv（3秒间隔限制）
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

    async def _search_wos(
        self, topic: str, region: str, content: str,
        year_start: str, year_end: str, max_results: int,
    ) -> WoSSearchResult:
        """执行 Web of Science 检索.

        自动将中文主题翻译为英文，因为 WoS 主要是英文文献库。
        使用 WoS 查询语言 (WQL) 构建检索式。
        """
        # 翻译为英文
        en_topic = self._translate_to_english(topic)
        en_region = self._translate_to_english(region)
        en_content = self._translate_to_english(content)

        # 构建 WoS 查询式
        query = WoSEngine.build_query_from_topic(
            topic=en_topic,
            region=en_region,
            content=en_content,
            year_start=year_start,
            year_end=year_end,
        )

        return await self.wos_engine.search(
            query=query,
            limit=max_results,
        )

    async def _search_chinaxiv(
        self, topic: str, year_start: str, year_end: str, max_results: int,
    ) -> ChinaXivSearchResult:
        """执行 ChinaXiv 预印本检索.

        ChinaXiv 是中科院预印本平台，主要收录中文预印本。
        使用原始中文关键词检索。
        """
        return await self.chinaxiv_engine.search(
            query=topic,
            limit=max_results,
            year_start=year_start,
            year_end=year_end,
        )

    async def _search_pubscholar(
        self, topic: str, max_results: int,
    ) -> PubScholarSearchResult:
        """执行 PubScholar OA 资源检索.

        PubScholar 是公共学术 OA 平台，支持中英文检索。
        使用原始中文关键词检索。
        """
        return await self.pubscholar_engine.search(
            query=topic,
            limit=max_results,
            lang="zh",
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

        # Web of Science 论文
        if result.wos_result:
            for p in result.wos_result.papers:
                papers.append(UnifiedPaper(
                    source="wos",
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=str(p.year) if p.year else "",
                    venue=p.journal,
                    citation_count=p.cited_by_count,
                    url=p.url,
                    doi=p.doi,
                    keywords=p.keywords + p.keywords_plus,
                    language="en",
                    raw=p.to_dict(),
                ))

        # ChinaXiv 预印本
        if result.chinaxiv_result:
            for p in result.chinaxiv_result.papers:
                papers.append(UnifiedPaper(
                    source="chinaxiv",
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=p.year,
                    venue=p.subject,
                    url=p.page_url,
                    doi=p.doi,
                    keywords=p.keywords,
                    language="zh",
                    raw=p.to_dict(),
                ))

        # PubScholar OA 论文
        if result.pubscholar_result:
            for p in result.pubscholar_result.papers:
                papers.append(UnifiedPaper(
                    source="pubscholar",
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=p.year,
                    venue=p.source,
                    citation_count=p.cite_count,
                    url=p.page_url,
                    doi=p.doi,
                    keywords=p.keywords,
                    language=p.language or "zh",
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
        wos_papers = [p for p in papers if p.source == "wos"]
        chinaxiv_papers = [p for p in papers if p.source == "chinaxiv"]
        pubscholar_papers = [p for p in papers if p.source == "pubscholar"]

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

        if wos_papers:
            lines.append(f"\n### Web of Science ({len(wos_papers)} 篇)")
            for i, p in enumerate(wos_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                cited = f" [cited: {p.citation_count}]" if p.citation_count else ""
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year}){cited}")

        if chinaxiv_papers:
            lines.append(f"\n### ChinaXiv 预印本 ({len(chinaxiv_papers)} 篇)")
            for i, p in enumerate(chinaxiv_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year})")

        if pubscholar_papers:
            lines.append(f"\n### PubScholar OA ({len(pubscholar_papers)} 篇)")
            for i, p in enumerate(pubscholar_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                cited = f" [cited: {p.citation_count}]" if p.citation_count else ""
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year}){cited}")

        return "\n".join(lines) if lines else "暂无检索结果"
