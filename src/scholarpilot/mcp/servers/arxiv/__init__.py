"""arXiv 检索引擎.

通过 arXiv API 检索预印本论文。
API 文档: https://info.arxiv.org/help/api/user-manual.html

特点:
    - 覆盖物理、数学、计算机科学、经济学等预印本
    - 支持字段前缀搜索语法（ti:, au:, abs:, cat: 等）
    - 支持布尔运算（AND, OR, ANDNOT）
    - 返回 Atom 1.0 XML 格式
    - 无需 API Key，但速率限制严格（每3秒最多1请求）

重要: 必须遵守 arXiv 的速率限制——连续请求之间至少间隔3秒。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx

from scholarpilot.utils.network import configure_no_proxy

logger = logging.getLogger(__name__)

# API 端点（使用 HTTPS，避免 VPN/代理对 HTTP 的拦截）
ARXIV_BASE = "https://export.arxiv.org/api/query"

# XML 命名空间
NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# arXiv 分类（经济学相关）
ECON_CATEGORIES = {
    "econ.GN": "General Economics",
    "econ.EM": "Econometrics",
    "econ.TH": "Theoretical Economics",
}


@dataclass
class ArxivPaper:
    """arXiv 论文数据模型."""

    arxiv_id: str = ""
    title: str = ""
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    published: str = ""  # ISO 日期
    updated: str = ""
    categories: list[str] = field(default_factory=list)
    primary_category: str = ""
    comment: str = ""
    journal_ref: str = ""
    doi: str = ""
    pdf_url: str = ""
    abs_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "published": self.published,
            "updated": self.updated,
            "categories": self.categories,
            "primary_category": self.primary_category,
            "comment": self.comment,
            "journal_ref": self.journal_ref,
            "doi": self.doi,
            "pdf_url": self.pdf_url,
            "abs_url": self.abs_url,
        }


@dataclass
class ArxivSearchResult:
    """arXiv 检索结果."""

    query: str = ""
    total_count: int = 0
    papers: list[ArxivPaper] = field(default_factory=list)
    start_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
            "start_index": self.start_index,
        }


class ArxivEngine:
    """arXiv 检索引擎.

    通过 arXiv API 检索预印本论文。

    重要: arXiv API 速率限制为每3秒1请求，本引擎已内置3秒间隔。

    Usage:
        engine = ArxivEngine()
        result = await engine.search("ti:government debt AND abs:fiscal", max_results=20)
        for paper in result.papers:
            print(f"{paper.title} ({paper.published[:4]}) - {paper.arxiv_id}")
    """

    def __init__(self, timeout: int = 30) -> None:
        """初始化 arXiv 检索引擎.

        Args:
            timeout: 请求超时秒数。
        """
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端."""
        if self._client is None or self._client.is_closed:
            configure_no_proxy()
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": "ScholarPilot/0.1.0 (Academic Research Tool)",
                    "Accept": "application/atom+xml",
                },
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                proxy=None,
                trust_env=False,
            )
        return self._client

    async def close(self) -> None:
        """关闭 HTTP 客户端."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _respect_rate_limit(self) -> None:
        """遵守 arXiv API 速率限制（每3秒1请求）."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < 3.0:
            wait = 3.0 - elapsed
            logger.debug(f"Rate limiting: waiting {wait:.1f}s")
            await asyncio.sleep(wait)
        self._last_request_time = asyncio.get_event_loop().time()

    async def search(
        self,
        search_query: str,
        max_results: int = 20,
        start: int = 0,
        sort_by: str = "relevance",
        sort_order: str = "descending",
    ) -> ArxivSearchResult:
        """搜索 arXiv 论文.

        Args:
            search_query: 搜索查询串，支持字段前缀语法。
                          如 "ti:government debt AND abs:fiscal"
                          字段: ti(标题), au(作者), abs(摘要), cat(分类), all(所有)
                          布尔: AND, OR, ANDNOT
            max_results: 返回数量（最大2000）。
            start: 起始索引。
            sort_by: 排序方式 (relevance/lastUpdatedDate/submittedDate)。
            sort_order: 排序顺序 (ascending/descending)。

        Returns:
            ArxivSearchResult: 检索结果。
        """
        await self._respect_rate_limit()

        client = await self._get_client()

        params = {
            "search_query": search_query,
            "start": str(start),
            "max_results": str(min(max_results, 2000)),
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }

        try:
            response = await client.get(ARXIV_BASE, params=params)
            response.raise_for_status()

            result = self._parse_atom_response(response.text, search_query)
            logger.info(
                f"arXiv search '{search_query}': "
                f"{result.total_count} total, {len(result.papers)} returned"
            )
            return result

        except Exception as e:
            logger.error(f"arXiv search failed: {e}")
            return ArxivSearchResult(query=search_query, total_count=0)

    async def get_paper(self, arxiv_id: str) -> ArxivPaper | None:
        """获取单篇 arXiv 论文.

        Args:
            arxiv_id: arXiv 论文 ID（如 "2401.12345" 或 "2401.12345v1"）。

        Returns:
            ArxivPaper 或 None。
        """
        await self._respect_rate_limit()

        client = await self._get_client()
        params = {"id_list": arxiv_id}

        try:
            response = await client.get(ARXIV_BASE, params=params)
            response.raise_for_status()
            result = self._parse_atom_response(response.text, arxiv_id)
            if result.papers:
                return result.papers[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get arXiv paper {arxiv_id}: {e}")
            return None

    def _parse_atom_response(self, xml_text: str, query: str) -> ArxivSearchResult:
        """解析 arXiv API 返回的 Atom XML.

        Args:
            xml_text: XML 响应文本。
            query: 原始查询串（用于记录）。

        Returns:
            ArxivSearchResult: 解析后的检索结果。
        """
        result = ArxivSearchResult(query=query)

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"Failed to parse arXiv XML: {e}")
            return result

        # OpenSearch 元数据
        total_elem = root.find("opensearch:totalResults", NAMESPACES)
        if total_elem is not None:
            result.total_count = int(total_elem.text or "0")

        start_elem = root.find("opensearch:startIndex", NAMESPACES)
        if start_elem is not None:
            result.start_index = int(start_elem.text or "0")

        # 解析论文条目
        entries = root.findall("atom:entry", NAMESPACES)
        for entry in entries:
            paper = self._parse_entry(entry)
            if paper:
                result.papers.append(paper)

        return result

    def _parse_entry(self, entry: ET.Element) -> ArxivPaper | None:
        """解析单个 entry 元素."""
        paper = ArxivPaper()

        # ID（格式: http://arxiv.org/abs/2401.12345v1）
        id_elem = entry.find("atom:id", NAMESPACES)
        if id_elem is not None and id_elem.text:
            id_text = id_elem.text.strip()
            paper.abs_url = id_text
            # 提取 arXiv ID
            match = re.search(r"abs/(.+)$", id_text)
            if match:
                paper.arxiv_id = match.group(1)

        # 标题
        title_elem = entry.find("atom:title", NAMESPACES)
        if title_elem is not None and title_elem.text:
            paper.title = " ".join(title_elem.text.split())  # 清理空白

        # 摘要
        summary_elem = entry.find("atom:summary", NAMESPACES)
        if summary_elem is not None and summary_elem.text:
            paper.abstract = " ".join(summary_elem.text.split())

        # 作者
        authors = entry.findall("atom:author", NAMESPACES)
        for author in authors:
            name_elem = author.find("atom:name", NAMESPACES)
            if name_elem is not None and name_elem.text:
                paper.authors.append(name_elem.text.strip())

        # 发布日期
        published_elem = entry.find("atom:published", NAMESPACES)
        if published_elem is not None and published_elem.text:
            paper.published = published_elem.text.strip()

        # 更新日期
        updated_elem = entry.find("atom:updated", NAMESPACES)
        if updated_elem is not None and updated_elem.text:
            paper.updated = updated_elem.text.strip()

        # 分类
        categories = entry.findall("atom:category", NAMESPACES)
        for cat in categories:
            term = cat.get("term", "")
            if term:
                paper.categories.append(term)

        # 主要分类（arXiv 扩展）
        primary_cat = entry.find("arxiv:primary_category", NAMESPACES)
        if primary_cat is not None:
            paper.primary_category = primary_cat.get("term", "")

        # 评论
        comment_elem = entry.find("arxiv:comment", NAMESPACES)
        if comment_elem is not None and comment_elem.text:
            paper.comment = comment_elem.text.strip()

        # 期刊引用
        journal_elem = entry.find("arxiv:journal_ref", NAMESPACES)
        if journal_elem is not None and journal_elem.text:
            paper.journal_ref = journal_elem.text.strip()

        # DOI
        doi_elem = entry.find("arxiv:doi", NAMESPACES)
        if doi_elem is not None and doi_elem.text:
            paper.doi = doi_elem.text.strip()

        # PDF 链接
        links = entry.findall("atom:link", NAMESPACES)
        for link in links:
            if link.get("title") == "pdf":
                paper.pdf_url = link.get("href", "")
                break

        if not paper.title:
            return None

        return paper

    @staticmethod
    def build_query(
        title: str = "",
        author: str = "",
        abstract: str = "",
        category: str = "",
        all_fields: str = "",
    ) -> str:
        """构建 arXiv 搜索查询串.

        使用字段前缀语法和布尔运算。

        Args:
            title: 标题关键词。
            author: 作者关键词。
            abstract: 摘要关键词。
            category: arXiv 分类（如 "econ.EM"）。
            all_fields: 所有字段关键词。

        Returns:
            arXiv 搜索查询串。

        Example:
            >>> ArxivEngine.build_query(title="government debt", abstract="fiscal")
            'ti:government debt AND abs:fiscal'
            >>> ArxivEngine.build_query(category="econ.EM")
            'cat:econ.EM'
        """
        parts: list[str] = []

        if title:
            # 短语用双引号
            if " " in title:
                parts.append(f'ti:"{title}"')
            else:
                parts.append(f"ti:{title}")

        if author:
            parts.append(f"au:{author}")

        if abstract:
            if " " in abstract:
                parts.append(f'abs:"{abstract}"')
            else:
                parts.append(f"abs:{abstract}")

        if category:
            parts.append(f"cat:{category}")

        if all_fields:
            if " " in all_fields:
                parts.append(f'all:"{all_fields}"')
            else:
                parts.append(f"all:{all_fields}")

        return " AND ".join(parts) if parts else ""
