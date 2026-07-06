"""统一中文文献检索管理器.

实现三层检索：
1. 主层：NCPSSD（国家哲社文献中心，完全免费，无需登录）
2. CNKI：aiohttp 引擎（基于 papertracker_social 已验证方案，需有效 Cookie）
3. 兜底：NCPSSD 始终可用，确保中文文献检索不为空

2026-06-27 实测：CNKI 返回 1736 篇（"地方政府债务"），NCPSSD 返回 703 篇。

Usage:
    manager = ChineseLiteratureManager()
    results = await manager.search("地方政府债务", year_start="2020", year_end="2025")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from scholarpilot.mcp.servers.cnki import (
    CNKIAiohttpEngine,
    CNKIPaper,
    CNKISearchResult,
    QueryLayer,
)
from scholarpilot.mcp.servers.ncpssd import (
    NCPSSDEngine,
    NCPSSDPaper,
    NCPSSDSearchResult,
)

logger = logging.getLogger(__name__)


@dataclass
class UnifiedChinesePaper:
    """统一的中文论文数据模型.

    无论来自 CNKI 还是 NCPSSD，都转换为统一格式。
    """

    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    doi: str = ""
    url: str = ""
    source: str = ""  # "cnki" or "ncpssd"
    cited_count: int = 0
    download_count: int = 0
    fund: str = ""

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
        }


@dataclass
class ChineseSearchResult:
    """统一中文检索结果。"""

    query: str = ""
    cnki_count: int = 0  # CNKI 检索到的总数
    ncpssd_count: int = 0  # NCPSSD 检索到的总数
    papers: list[UnifiedChinesePaper] = field(default_factory=list)
    cnki_result: CNKISearchResult | None = None
    ncpssd_result: NCPSSDSearchResult | None = None

    @property
    def total_count(self) -> int:
        """总匹配数（CNKI + NCPSSD）。"""
        return self.cnki_count + self.ncpssd_count

    @property
    def returned_count(self) -> int:
        """实际返回的论文数。"""
        return len(self.papers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "cnki_count": self.cnki_count,
            "ncpssd_count": self.ncpssd_count,
            "total_count": self.total_count,
            "returned_count": self.returned_count,
            "papers": [p.to_dict() for p in self.papers],
        }


class ChineseLiteratureManager:
    """统一中文文献检索管理器.

    实现双源检索，确保中文文献检索始终有结果。

    检索策略：
    1. NCPSSD（国家哲社文献中心）- 始终使用，免费、稳定、政府背书
    2. CNKI aiohttp 引擎 - 基于 papertracker_social 已验证方案，需有效 Cookie

    所有数据源并行检索，结果合并去重。

    Usage:
        manager = ChineseLiteratureManager()
        result = await manager.search(
            topic="地方政府债务",
            year_start="2020",
            year_end="2025",
        )
        print(f"共找到 {result.total_count} 篇中文文献")
    """

    def __init__(
        self,
        cnki_cookie: str = "",
        cnki_proxy_url: str = "",
        use_playwright: bool = False,
        timeout: int = 30,
    ) -> None:
        """初始化中文文献检索管理器.

        Args:
            cnki_cookie: CNKI 登录 Cookie 字符串（可选）。
                         如不提供，自动从缓存文件加载或使用 Fallback Cookie。
            cnki_proxy_url: 保留参数（不再使用）。
            use_playwright: 保留参数（不再使用，aiohttp 引擎已替代）。
            timeout: 请求超时秒数。
        """
        self.cnki_engine = CNKIAiohttpEngine(
            cookie_str=cnki_cookie,
            timeout=timeout,
        )
        self.ncpssd_engine = NCPSSDEngine(timeout=timeout)

        # 保留 Playwright 兼容（不再使用）
        self._playwright_engine = None

        if cnki_cookie:
            self.cnki_engine.set_cookie(cnki_cookie)
            logger.info("CNKI aiohttp engine initialized with custom cookie")
        elif self.cnki_engine.has_cookie:
            logger.info(
                f"CNKI aiohttp engine initialized with cached cookie "
                f"({list(self.cnki_engine._cookies.keys())[:3]})"
            )

    async def search(
        self,
        topic: str,
        region: str = "",
        content: str = "",
        year_start: str = "",
        year_end: str = "",
        max_per_source: int = 50,
    ) -> ChineseSearchResult:
        """执行多源中文文献检索.

        同时检索 CNKI（aiohttp）和 NCPSSD，合并去重结果。

        Args:
            topic: 核心主题（如"地方政府债务"）。
            region: 研究区域（如"中国"、"甘肃省"）。
            content: 研究内容（如"风险溢出"）。
            year_start: 起始年份。
            year_end: 结束年份。
            max_per_source: 每个数据源最大返回数。

        Returns:
            ChineseSearchResult: 合并后的检索结果。
        """
        result = ChineseSearchResult(query=f"{topic} {region} {content}".strip())

        # 构建检索词
        cnki_query = CNKIAiohttpEngine.build_query(topic, region, content)
        ncpssd_query = NCPSSDEngine.build_query(topic, region, content)

        logger.info(f"Chinese search: CNKI(aiohttp)='{cnki_query}', NCPSSD='{ncpssd_query}'")

        ys = year_start or "2020"
        ye = year_end or "2026"

        # 并行检索 CNKI + NCPSSD
        tasks = [
            self.cnki_engine.search(
                cnki_query, limit=max_per_source,
                year_start=ys, year_end=ye,
            ),
            self.ncpssd_engine.search(
                ncpssd_query, limit=max_per_source,
                year_start=year_start, year_end=year_end,
            ),
        ]
        cnki_result_raw, ncpssd_result_raw = await asyncio.gather(
            *tasks, return_exceptions=True,
        )

        # 处理 CNKI 结果
        if isinstance(cnki_result_raw, Exception):
            logger.warning(f"CNKI search failed: {cnki_result_raw}")
            result.cnki_result = CNKISearchResult(query=cnki_query, total_count=0)
        elif not isinstance(cnki_result_raw, CNKISearchResult):
            result.cnki_result = CNKISearchResult(query=cnki_query, total_count=0)
        else:
            result.cnki_result = cnki_result_raw
        result.cnki_count = result.cnki_result.total_count

        # 处理 NCPSSD 结果
        if isinstance(ncpssd_result_raw, Exception):
            logger.warning(f"NCPSSD search failed: {ncpssd_result_raw}")
            result.ncpssd_result = NCPSSDSearchResult(query=ncpssd_query, total_count=0)
        elif not isinstance(ncpssd_result_raw, NCPSSDSearchResult):
            result.ncpssd_result = NCPSSDSearchResult(query=ncpssd_query, total_count=0)
        else:
            result.ncpssd_result = ncpssd_result_raw
        result.ncpssd_count = result.ncpssd_result.total_count

        # 合并去重
        result.papers = self._merge_and_dedup(
            cnki_papers=result.cnki_result.papers,
            ncpssd_papers=result.ncpssd_result.papers,
        )

        logger.info(
            f"Chinese search complete: CNKI={result.cnki_count}, "
            f"NCPSSD={result.ncpssd_count}, merged={len(result.papers)}"
        )

        return result

    @staticmethod
    def _normalize_title(title: str) -> str:
        """标准化标题用于去重比较。"""
        import re
        # 去除所有标点符号和空格
        return re.sub(r"[\s\W_]+", "", title).lower()

    def _merge_and_dedup(
        self,
        cnki_papers: list[CNKIPaper],
        ncpssd_papers: list[NCPSSDPaper],
    ) -> list[UnifiedChinesePaper]:
        """合并两个数据源的论文并去重.

        去重策略：基于标题相似度（去除标点符号后完全匹配）。
        如果 CNKI 有重复，保留 CNKI 版本（数据更丰富）。
        """
        unified: list[UnifiedChinesePaper] = []
        seen_titles: set[str] = set()

        # 先添加 CNKI 论文（数据更丰富，优先级高）
        for paper in cnki_papers:
            if not paper.title:
                continue
            normalized = self._normalize_title(paper.title)
            if normalized in seen_titles:
                continue
            seen_titles.add(normalized)

            unified.append(UnifiedChinesePaper(
                title=paper.title,
                authors=paper.authors,
                journal=paper.journal,
                year=paper.year,
                abstract=paper.abstract,
                keywords=paper.keywords,
                url=paper.url,
                source="cnki",
                cited_count=paper.cited_count,
                download_count=paper.download_count,
                fund=paper.fund,
            ))

        # 再添加 NCPSSD 论文（跳过与 CNKI 重复的）
        for paper in ncpssd_papers:
            if not paper.title:
                continue
            normalized = self._normalize_title(paper.title)
            if normalized in seen_titles:
                continue
            seen_titles.add(normalized)

            unified.append(UnifiedChinesePaper(
                title=paper.title,
                authors=paper.authors,
                journal=paper.journal,
                year=paper.year,
                abstract=paper.abstract,
                keywords=paper.keywords,
                doi=paper.doi,
                url=paper.url,
                source="ncpssd",
            ))

        return unified

    def format_papers_for_display(
        self,
        papers: list[UnifiedChinesePaper],
        max_display: int = 20,
    ) -> str:
        """格式化论文列表用于显示。"""
        if not papers:
            return "暂无中文文献检索结果"

        lines = [f"共找到 {len(papers)} 篇中文文献:\n"]

        # 按来源分组
        cnki_papers = [p for p in papers if p.source == "cnki"]
        ncpssd_papers = [p for p in papers if p.source == "ncpssd"]

        if cnki_papers:
            lines.append(f"\n### CNKI 知网 ({len(cnki_papers)} 篇)")
            for i, paper in enumerate(cnki_papers[:max_display]):
                authors = ", ".join(paper.authors[:3]) if paper.authors else "N/A"
                cited = f" [引用:{paper.cited_count}]" if paper.cited_count else ""
                lines.append(
                    f"{i+1}. {paper.title} - {authors} "
                    f"({paper.journal}, {paper.year}){cited}"
                )

        if ncpssd_papers:
            lines.append(f"\n### 国家哲社文献中心 ({len(ncpssd_papers)} 篇)")
            for i, paper in enumerate(ncpssd_papers[:max_display]):
                authors = ", ".join(paper.authors[:3]) if paper.authors else "N/A"
                lines.append(
                    f"{i+1}. {paper.title} - {authors} "
                    f"({paper.journal}, {paper.year})"
                )

        return "\n".join(lines)

    async def close(self) -> None:
        """关闭所有引擎。"""
        await self.cnki_engine.close()
        await self.ncpssd_engine.close()

    async def search_4layer(
        self,
        topic: str,
        region: str = "中国",
        content: str = "",
        year_start: str = "2015",
        year_end: str = "2024",
    ) -> list[ChineseSearchResult]:
        """执行 CNKI 4层检索策略 + NCPSSD 补充.

        对 CNKI 生成 4 层检索策略（精准切口→区域基础→对标经验→领域全貌），
        每层检索后用 NCPSSD 补充结果。

        Args:
            topic: 核心主题。
            region: 研究区域。
            content: 研究内容。
            year_start: 起始年份。
            year_end: 结束年份。

        Returns:
            4 层检索结果列表。
        """
        # 使用 aiohttp 引擎的 4 层检索
        layers = await self.cnki_engine.search_4layer(
            topic=topic,
            region=region,
            content=content,
            year_start=year_start,
            year_end=year_end,
        )

        results: list[ChineseSearchResult] = []

        for layer in layers:
            # 每层用 NCPSSD 补充
            ncpssd_query = NCPSSDEngine.build_query(topic, region, content)
            ncpssd_result = await self.ncpssd_engine.search(
                ncpssd_query,
                limit=10,
                year_start=year_start,
                year_end=year_end,
            )

            cr = ChineseSearchResult(query=layer.query)
            cr.cnki_result = layer.result
            cr.cnki_count = layer.result.total_count if layer.result else 0
            cr.ncpssd_result = ncpssd_result
            cr.ncpssd_count = ncpssd_result.total_count
            cr.papers = self._merge_and_dedup(
                cnki_papers=layer.result.papers if layer.result else [],
                ncpssd_papers=ncpssd_result.papers,
            )
            results.append(cr)

            await asyncio.sleep(0.3)

        return results
