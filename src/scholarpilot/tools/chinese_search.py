"""统一中文文献检索管理器.

实现三源并行检索：
1. CNKI：aiohttp 引擎（基于 papertracker_social 已验证方案，需有效 Cookie 或 VPN 机构 IP）
2. 万方数据：gRPC-Web 引擎（通过逆向分析 API 协议，覆盖期刊/学位/会议论文）
3. NCPSSD：国家哲社文献中心（完全免费，无需登录，政府背书，兜底保障）

三源互补优势：
- CNKI：期刊论文覆盖最全，被引数据丰富
- 万方：学位论文、会议论文覆盖更全，核心期刊标签
- NCPSSD：免费开放，稳定性高，兜底保障

2026-07-30 实测：
- CNKI 返回 1736 篇（"地方政府债务"）
- 万方返回 45058 篇（"财政政策"），20 篇/页
- NCPSSD 返回 703 篇

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
from scholarpilot.mcp.servers.wanfang import (
    WanfangEngine,
    WanfangPaper,
    WanfangSearchResult,
)
from scholarpilot.utils.vpn import VPNStatus

logger = logging.getLogger(__name__)


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


class ChineseLiteratureManager:
    """统一中文文献检索管理器.

    实现三源并行检索，确保中文文献检索覆盖面最广且始终有结果。

    检索策略：
    1. CNKI aiohttp 引擎 - 期刊论文覆盖最全，需有效 Cookie 或 VPN 机构 IP
    2. 万方 gRPC-Web 引擎 - 学位论文/会议论文覆盖更全，核心期刊标签
    3. NCPSSD - 国家哲社文献中心，免费、稳定、政府背书，兜底保障

    所有数据源并行检索，结果合并去重。
    优先级：CNKI > 万方 > NCPSSD（CNKI 数据最丰富，优先保留）

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
        vpn_status: VPNStatus | None = None,
    ) -> None:
        """初始化中文文献检索管理器.

        Args:
            cnki_cookie: CNKI 登录 Cookie 字符串（可选）。
                         如不提供，自动从缓存文件加载或使用 Fallback Cookie。
            cnki_proxy_url: 保留参数（不再使用）。
            use_playwright: 保留参数（不再使用，aiohttp 引擎已替代）。
            timeout: 请求超时秒数。
            vpn_status: VPN 连接状态。VPN 连接时,
                        CNKI 和万方均使用机构 IP 认证模式。
        """
        # 判断 CNKI 是否可通过 VPN 机构 IP 认证
        cnki_vpn_mode = (
            vpn_status is not None
            and vpn_status.connected
            and "cnki" in vpn_status.accessible_databases
        )

        # 判断万方是否可通过 VPN 机构 IP 认证
        wanfang_vpn_mode = (
            vpn_status is not None
            and vpn_status.connected
            and "wanfang" in vpn_status.accessible_databases
        )

        self.cnki_engine = CNKIAiohttpEngine(
            cookie_str=cnki_cookie,
            timeout=timeout,
            vpn_mode=cnki_vpn_mode,
        )
        self.wanfang_engine = WanfangEngine(
            timeout=timeout,
            vpn_mode=wanfang_vpn_mode,
        )
        self.ncpssd_engine = NCPSSDEngine(timeout=timeout)

        # 保留 Playwright 兼容（不再使用）
        self._playwright_engine = None

        # VPN 状态记录
        self.vpn_status = vpn_status

        if cnki_vpn_mode:
            logger.info("CNKI engine in VPN mode (institutional IP auth)")
        elif cnki_cookie:
            self.cnki_engine.set_cookie(cnki_cookie)
            logger.info("CNKI aiohttp engine initialized with custom cookie")
        elif self.cnki_engine.has_cookie:
            logger.info(
                f"CNKI aiohttp engine initialized with cached cookie "
                f"({list(self.cnki_engine._cookies.keys())[:3]})"
            )

        if wanfang_vpn_mode:
            logger.info("Wanfang engine in VPN mode (institutional IP auth)")
        else:
            logger.info("Wanfang engine initialized (public access mode)")

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

        同时检索 CNKI、万方和 NCPSSD，合并去重结果。

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
        wanfang_query = WanfangEngine.build_query(topic, region, content)
        ncpssd_query = NCPSSDEngine.build_query(topic, region, content)

        logger.info(
            f"Chinese search: CNKI='{cnki_query}', "
            f"Wanfang='{wanfang_query}', NCPSSD='{ncpssd_query}'"
        )

        ys = year_start or "2020"
        ye = year_end or "2026"

        # 并行检索 CNKI + 万方 + NCPSSD
        tasks = [
            self.cnki_engine.search(
                cnki_query, limit=max_per_source,
                year_start=ys, year_end=ye,
            ),
            self.wanfang_engine.search(
                wanfang_query, limit=min(max_per_source, 20),
                year_start=ys, year_end=ye,
            ),
            self.ncpssd_engine.search(
                ncpssd_query, limit=max_per_source,
                year_start=year_start, year_end=year_end,
            ),
        ]
        cnki_result_raw, wanfang_result_raw, ncpssd_result_raw = await asyncio.gather(
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

        # 处理万方结果
        if isinstance(wanfang_result_raw, Exception):
            logger.warning(f"Wanfang search failed: {wanfang_result_raw}")
            result.wanfang_result = WanfangSearchResult(query=wanfang_query, total_count=0)
        elif not isinstance(wanfang_result_raw, WanfangSearchResult):
            result.wanfang_result = WanfangSearchResult(query=wanfang_query, total_count=0)
        else:
            result.wanfang_result = wanfang_result_raw
        result.wanfang_count = result.wanfang_result.total_count

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
            wanfang_papers=result.wanfang_result.papers,
            ncpssd_papers=result.ncpssd_result.papers,
        )

        logger.info(
            f"Chinese search complete: CNKI={result.cnki_count}, "
            f"Wanfang={result.wanfang_count}, NCPSSD={result.ncpssd_count}, "
            f"merged={len(result.papers)}"
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
        wanfang_papers: list[WanfangPaper],
        ncpssd_papers: list[NCPSSDPaper],
    ) -> list[UnifiedChinesePaper]:
        """合并三个数据源的论文并去重.

        去重策略：基于标题相似度（去除标点符号后完全匹配）。
        优先级：CNKI > 万方 > NCPSSD（CNKI 数据最丰富，优先保留）。
        万方论文携带扩展字段（paper_type, institution, core_tags 等）。
        """
        unified: list[UnifiedChinesePaper] = []
        seen_titles: set[str] = set()

        # 1. 先添加 CNKI 论文（数据最丰富，优先级最高）
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

        # 2. 添加万方论文（跳过与 CNKI 重复的，携带扩展字段）
        for paper in wanfang_papers:
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
                source="wanfang",
                cited_count=paper.cited_count,
                download_count=paper.download_count,
                paper_type=paper.paper_type,
                institution=paper.institution,
                degree_level=paper.degree_level,
                core_tags=paper.core_tags,
                issue=paper.issue,
                page_range=paper.page_range,
                language=paper.language,
                issn=paper.issn,
            ))

        # 3. 添加 NCPSSD 论文（跳过与前两源重复的，兜底补充）
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
        wanfang_papers = [p for p in papers if p.source == "wanfang"]
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

        if wanfang_papers:
            lines.append(f"\n### 万方数据 ({len(wanfang_papers)} 篇)")
            for i, paper in enumerate(wanfang_papers[:max_display]):
                authors = ", ".join(paper.authors[:3]) if paper.authors else "N/A"
                ptype = f" [{paper.paper_type}]" if paper.paper_type else ""
                cited = f" [引用:{paper.cited_count}]" if paper.cited_count else ""
                lines.append(
                    f"{i+1}. {paper.title} - {authors} "
                    f"({paper.journal}, {paper.year}){ptype}{cited}"
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
        await self.wanfang_engine.close()
        await self.ncpssd_engine.close()

    async def search_4layer(
        self,
        topic: str,
        region: str = "中国",
        content: str = "",
        year_start: str = "2015",
        year_end: str = "2024",
    ) -> list[ChineseSearchResult]:
        """执行 CNKI 4层检索策略 + 万方/NCPSSD 补充.

        对 CNKI 生成 4 层检索策略（精准切口→区域基础→对标经验→领域全貌），
        每层检索后用万方和 NCPSSD 补充结果。

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
            # 每层用万方和 NCPSSD 并行补充
            wanfang_query = WanfangEngine.build_query(topic, region, content)
            ncpssd_query = NCPSSDEngine.build_query(topic, region, content)

            wanfang_result, ncpssd_result = await asyncio.gather(
                self.wanfang_engine.search(
                    wanfang_query,
                    limit=20,
                    year_start=year_start,
                    year_end=year_end,
                ),
                self.ncpssd_engine.search(
                    ncpssd_query,
                    limit=10,
                    year_start=year_start,
                    year_end=year_end,
                ),
                return_exceptions=True,
            )

            # 处理万方结果
            if isinstance(wanfang_result, Exception):
                logger.warning(f"Wanfang search failed in 4layer: {wanfang_result}")
                wanfang_result = WanfangSearchResult(query=wanfang_query, total_count=0)

            # 处理 NCPSSD 结果
            if isinstance(ncpssd_result, Exception):
                logger.warning(f"NCPSSD search failed in 4layer: {ncpssd_result}")
                ncpssd_result = NCPSSDSearchResult(query=ncpssd_query, total_count=0)

            cr = ChineseSearchResult(query=layer.query)
            cr.cnki_result = layer.result
            cr.cnki_count = layer.result.total_count if layer.result else 0
            cr.wanfang_result = wanfang_result
            cr.wanfang_count = wanfang_result.total_count
            cr.ncpssd_result = ncpssd_result
            cr.ncpssd_count = ncpssd_result.total_count
            cr.papers = self._merge_and_dedup(
                cnki_papers=layer.result.papers if layer.result else [],
                wanfang_papers=wanfang_result.papers,
                ncpssd_papers=ncpssd_result.papers,
            )
            results.append(cr)

            await asyncio.sleep(0.3)

        return results
