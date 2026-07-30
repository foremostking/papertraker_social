"""Semantic Scholar 检索引擎.

通过 Semantic Scholar Academic Graph API 检索英文学术文献。
API 文档: https://api.semanticscholar.org/api-docs/graph

特点:
    - 2.14亿篇论文的全学科覆盖
    - 富字段返回（tldr AI摘要、citationCount、openAccessPdf等）
    - JSON 格式，易于解析
    - 支持 API Key 认证（推荐，1 RPS 稳定速率）
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from scholarpilot.utils.network import configure_no_proxy

logger = logging.getLogger(__name__)

# API 端点
SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1"
SEARCH_URL = f"{SEMANTIC_SCHOLAR_BASE}/paper/search"
BATCH_URL = f"{SEMANTIC_SCHOLAR_BASE}/paper/batch"

# 默认返回字段
DEFAULT_FIELDS = ",".join([
    "paperId",
    "title",
    "abstract",
    "year",
    "venue",
    "publicationVenue",
    "authors",
    "citationCount",
    "referenceCount",
    "influentialCitationCount",
    "isOpenAccess",
    "openAccessPdf",
    "fieldsOfStudy",
    "publicationTypes",
    "journal",
    "externalIds",
    "tldr",
    "url",
])


@dataclass
class SSPaper:
    """Semantic Scholar 论文数据模型."""

    paper_id: str = ""
    title: str = ""
    abstract: str = ""
    year: Optional[int] = None
    venue: str = ""
    authors: list[str] = field(default_factory=list)
    citation_count: int = 0
    reference_count: int = 0
    influential_citation_count: int = 0
    is_open_access: bool = False
    open_access_pdf_url: str = ""
    fields_of_study: list[str] = field(default_factory=list)
    publication_types: list[str] = field(default_factory=list)
    journal_name: str = ""
    journal_volume: str = ""
    journal_pages: str = ""
    doi: str = ""
    arxiv_id: str = ""
    tldr: str = ""  # AI 生成的单句摘要
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "abstract": self.abstract,
            "year": self.year,
            "venue": self.venue,
            "authors": self.authors,
            "citation_count": self.citation_count,
            "reference_count": self.reference_count,
            "influential_citation_count": self.influential_citation_count,
            "is_open_access": self.is_open_access,
            "open_access_pdf_url": self.open_access_pdf_url,
            "fields_of_study": self.fields_of_study,
            "publication_types": self.publication_types,
            "journal_name": self.journal_name,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "tldr": self.tldr,
            "url": self.url,
        }

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> SSPaper:
        """从 API 响应字典构建 SSPaper."""
        paper = cls()
        paper.paper_id = data.get("paperId", "")
        paper.title = data.get("title", "")
        paper.abstract = data.get("abstract", "") or ""
        paper.year = data.get("year")
        paper.venue = data.get("venue", "") or ""

        # 作者
        authors_data = data.get("authors", [])
        paper.authors = [a.get("name", "") for a in authors_data if a.get("name")]

        # 引用统计
        paper.citation_count = data.get("citationCount", 0) or 0
        paper.reference_count = data.get("referenceCount", 0) or 0
        paper.influential_citation_count = data.get("influentialCitationCount", 0) or 0

        # 开放获取
        paper.is_open_access = data.get("isOpenAccess", False) or False
        oap = data.get("openAccessPdf")
        paper.open_access_pdf_url = oap.get("url", "") if oap else ""

        # 学科分类
        paper.fields_of_study = data.get("fieldsOfStudy", []) or []
        paper.publication_types = data.get("publicationTypes", []) or []

        # 期刊信息
        journal = data.get("journal")
        if journal:
            paper.journal_name = journal.get("name", "") or ""
            paper.journal_volume = journal.get("volume", "") or ""
            paper.journal_pages = journal.get("pages", "") or ""

        # 外部 ID
        ext_ids = data.get("externalIds", {}) or {}
        paper.doi = ext_ids.get("DOI", "") or ""
        paper.arxiv_id = ext_ids.get("ArXiv", "") or ""

        # AI 摘要
        tldr = data.get("tldr")
        if tldr:
            paper.tldr = tldr.get("text", "") or ""

        paper.url = data.get("url", "") or ""

        return paper


@dataclass
class SSSearchResult:
    """Semantic Scholar 检索结果."""

    query: str = ""
    total_count: int = 0
    papers: list[SSPaper] = field(default_factory=list)
    offset: int = 0
    next_offset: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
            "offset": self.offset,
        }


class SemanticScholarEngine:
    """Semantic Scholar 检索引擎.

    通过 Academic Graph API 检索英文学术文献。

    Usage:
        engine = SemanticScholarEngine(api_key="your_key")
        result = await engine.search("fiscal policy economic growth", limit=20)
        for paper in result.papers:
            print(f"{paper.title} ({paper.year}) - cited by {paper.citation_count}")
    """

    def __init__(
        self,
        api_key: str = "",
        timeout: int = 30,
    ) -> None:
        """初始化 Semantic Scholar 检索引擎.

        Args:
            api_key: API Key（推荐申请，获得稳定 1 RPS）。
                     申请地址: https://www.semanticscholar.org/product/api#api-key-form
            timeout: 请求超时秒数。
        """
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        if not api_key:
            logger.warning(
                "Semantic Scholar API Key 未配置 (SCHOLAR_SS_API_KEY)。"
                "无 Key 时共享 IP 限流严重 (100次/5分钟)，"
                "建议申请免费 Key: "
                "https://www.semanticscholar.org/product/api#api-key-form"
            )

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端."""
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": "ScholarPilot/0.1.0 (Academic Research Tool)",
                "Accept": "application/json",
            }
            if self.api_key:
                headers["x-api-key"] = self.api_key

            configure_no_proxy()
            self._client = httpx.AsyncClient(
                headers=headers,
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

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        year: str = "",
        fields_of_study: str = "",
        open_access_only: bool = False,
        fields: str = DEFAULT_FIELDS,
        max_retries: int = 5,
    ) -> SSSearchResult:
        """搜索论文.

        内置 429 限流重试机制：遇到 429 时自动等待后重试。
        无 API Key 时使用指数退避（5s→10s→20s→30s→60s）。

        Args:
            query: 纯文本搜索词（不支持特殊语法，连字符用空格替代）。
            limit: 返回数量（最大100）。
            offset: 分页偏移量。
            year: 年份过滤，如 "2020-2023" 或 "2024"。
            fields_of_study: 学科过滤，逗号分隔，如 "Economics,Political Science"。
            open_access_only: 仅返回有开放获取 PDF 的论文。
            fields: 返回字段列表。
            max_retries: 429 限流时最大重试次数。

        Returns:
            SSSearchResult: 检索结果。
        """
        client = await self._get_client()

        params: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
            "offset": offset,
            "fields": fields,
        }

        if year:
            params["year"] = year
        if fields_of_study:
            params["fieldsOfStudy"] = fields_of_study
        if open_access_only:
            params["openAccessPdf"] = ""

        import asyncio as _asyncio

        for attempt in range(max_retries + 1):
            try:
                response = await client.get(SEARCH_URL, params=params)

                # 429 限流：等待后重试
                if response.status_code == 429:
                    # 有 API Key 时使用 Retry-After 头，无 Key 时指数退避
                    if self.api_key:
                        retry_after = int(response.headers.get("Retry-After", "5"))
                    else:
                        # 无 Key 时指数退避: 5, 10, 20, 30, 60 秒
                        backoff_schedule = [5, 10, 20, 30, 60]
                        retry_after = backoff_schedule[
                            min(attempt, len(backoff_schedule) - 1)
                        ]
                    logger.warning(
                        f"Semantic Scholar 429 rate limited, "
                        f"waiting {retry_after}s (attempt {attempt + 1}/{max_retries + 1})"
                    )
                    if attempt < max_retries:
                        await _asyncio.sleep(retry_after)
                        continue

                response.raise_for_status()
                data = response.json()

                result = SSSearchResult(
                    query=query,
                    total_count=data.get("total", 0),
                    offset=offset,
                )

                # 解析论文列表
                for paper_data in data.get("data", []):
                    paper = SSPaper.from_api_response(paper_data)
                    result.papers.append(paper)

                # 分页信息
                if data.get("next"):
                    result.next_offset = data["next"]

                logger.info(
                    f"Semantic Scholar search '{query}': "
                    f"{result.total_count} total, {len(result.papers)} returned"
                )
                return result

            except httpx.HTTPStatusError as e:
                logger.error(f"Semantic Scholar API error: {e.response.status_code} - {e}")
                return SSSearchResult(query=query, total_count=0)
            except Exception as e:
                logger.error(f"Semantic Scholar search failed: {e}")
                return SSSearchResult(query=query, total_count=0)

        # 所有重试用尽
        logger.error(f"Semantic Scholar search exhausted {max_retries + 1} retries")
        return SSSearchResult(query=query, total_count=0)

    async def get_paper(self, paper_id: str, fields: str = DEFAULT_FIELDS) -> SSPaper | None:
        """获取单篇论文详情.

        Args:
            paper_id: 论文 ID（paperId, ARXIV:xxx, DOI:xxx 等）。
            fields: 返回字段。

        Returns:
            SSPaper 或 None。
        """
        client = await self._get_client()
        url = f"{SEMANTIC_SCHOLAR_BASE}/paper/{paper_id}"

        try:
            response = await client.get(url, params={"fields": fields})
            response.raise_for_status()
            data = response.json()
            return SSPaper.from_api_response(data)
        except Exception as e:
            logger.error(f"Failed to get paper {paper_id}: {e}")
            return None

    async def get_batch(
        self,
        paper_ids: list[str],
        fields: str = DEFAULT_FIELDS,
    ) -> list[SSPaper]:
        """批量获取论文详情.

        Args:
            paper_ids: 论文 ID 列表（最多500个）。
            fields: 返回字段。

        Returns:
            SSPaper 列表。
        """
        if not paper_ids:
            return []

        client = await self._get_client()
        # 分批处理，每批最多500
        all_papers: list[SSPaper] = []

        for i in range(0, len(paper_ids), 500):
            batch = paper_ids[i:i + 500]
            try:
                response = await client.post(
                    f"{BATCH_URL}?fields={fields}",
                    json={"ids": batch},
                )
                response.raise_for_status()
                data = response.json()

                for paper_data in data:
                    if paper_data:  # API 可能返回 null
                        all_papers.append(SSPaper.from_api_response(paper_data))

            except Exception as e:
                logger.error(f"Batch fetch failed: {e}")

        return all_papers

    async def get_citations(
        self,
        paper_id: str,
        limit: int = 100,
        offset: int = 0,
        fields: str = DEFAULT_FIELDS,
        max_retries: int = 3,
    ) -> list[SSPaper]:
        """获取引用了指定论文的文献列表（反向引用追踪）.

        Semantic Scholar citations 端点返回引用该论文的所有文献。
        用于文献订阅功能中的"引用追踪"策略。

        API: GET /paper/{paper_id}/citations
        响应中每条记录包含 citingPaper 字段（被引用的论文信息）。

        Args:
            paper_id: 论文 ID（paperId, DOI:xxx, ARXIV:xxx 等）。
            limit: 返回数量（最大 1000）。
            offset: 分页偏移。
            fields: 返回字段（自动添加 citingPaper. 前缀）。
            max_retries: 429 限流时最大重试次数。

        Returns:
            引用该论文的 SSPaper 列表。
        """
        client = await self._get_client()
        url = f"{SEMANTIC_SCHOLAR_BASE}/paper/{paper_id}/citations"

        # citations 端点的 fields 需要加 citingPaper. 前缀
        citing_fields = ",".join(f"citingPaper.{f}" for f in fields.split(","))

        params: dict[str, Any] = {
            "limit": min(limit, 1000),
            "offset": offset,
            "fields": citing_fields,
        }

        import asyncio as _asyncio

        for attempt in range(max_retries + 1):
            try:
                response = await client.get(url, params=params)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "5"))
                    logger.warning(
                        f"Semantic Scholar 429 rate limited (citations), "
                        f"waiting {retry_after}s (attempt {attempt + 1}/{max_retries + 1})"
                    )
                    if attempt < max_retries:
                        await _asyncio.sleep(retry_after)
                        continue

                response.raise_for_status()
                data = response.json()

                papers: list[SSPaper] = []
                for item in data.get("data", []):
                    citing_paper_data = item.get("citingPaper")
                    if citing_paper_data and citing_paper_data.get("paperId"):
                        papers.append(SSPaper.from_api_response(citing_paper_data))

                logger.info(
                    f"Semantic Scholar citations for {paper_id}: "
                    f"{data.get('total', len(papers))} total, {len(papers)} returned"
                )
                return papers

            except httpx.HTTPStatusError as e:
                logger.error(f"Semantic Scholar citations API error: {e.response.status_code} - {e}")
                return []
            except Exception as e:
                logger.error(f"Failed to get citations for {paper_id}: {e}")
                return []

        logger.error(f"Semantic Scholar citations exhausted {max_retries + 1} retries")
        return []

    async def get_references(
        self,
        paper_id: str,
        limit: int = 100,
        offset: int = 0,
        fields: str = DEFAULT_FIELDS,
        max_retries: int = 3,
    ) -> list[SSPaper]:
        """获取指定论文引用的文献列表（正向引用追踪）.

        API: GET /paper/{paper_id}/references
        响应中每条记录包含 citedPaper 字段。

        Args:
            paper_id: 论文 ID。
            limit: 返回数量（最大 1000）。
            offset: 分页偏移。
            fields: 返回字段（自动添加 citedPaper. 前缀）。
            max_retries: 429 限流时最大重试次数。

        Returns:
            被该论文引用的 SSPaper 列表。
        """
        client = await self._get_client()
        url = f"{SEMANTIC_SCHOLAR_BASE}/paper/{paper_id}/references"

        cited_fields = ",".join(f"citedPaper.{f}" for f in fields.split(","))

        params: dict[str, Any] = {
            "limit": min(limit, 1000),
            "offset": offset,
            "fields": cited_fields,
        }

        import asyncio as _asyncio

        for attempt in range(max_retries + 1):
            try:
                response = await client.get(url, params=params)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "5"))
                    logger.warning(
                        f"Semantic Scholar 429 rate limited (references), "
                        f"waiting {retry_after}s (attempt {attempt + 1}/{max_retries + 1})"
                    )
                    if attempt < max_retries:
                        await _asyncio.sleep(retry_after)
                        continue

                response.raise_for_status()
                data = response.json()

                papers: list[SSPaper] = []
                for item in data.get("data", []):
                    cited_paper_data = item.get("citedPaper")
                    if cited_paper_data and cited_paper_data.get("paperId"):
                        papers.append(SSPaper.from_api_response(cited_paper_data))

                logger.info(
                    f"Semantic Scholar references for {paper_id}: "
                    f"{data.get('total', len(papers))} total, {len(papers)} returned"
                )
                return papers

            except httpx.HTTPStatusError as e:
                logger.error(f"Semantic Scholar references API error: {e.response.status_code} - {e}")
                return []
            except Exception as e:
                logger.error(f"Failed to get references for {paper_id}: {e}")
                return []

        return []

    @staticmethod
    def build_query_from_topic(
        topic: str,
        region: str = "",
        content: str = "",
        language: str = "english",
    ) -> str:
        """基于研究主题构建 Semantic Scholar 搜索词.

        Semantic Scholar 不支持特殊搜索语法，使用纯文本。
        连字符需要替换为空格。

        Args:
            topic: 核心主题（如 "government debt"）。
            region: 区域（如 "China"）。
            content: 研究内容（如 "spatial spillover"）。
            language: 语言。

        Returns:
            搜索词字符串。
        """
        parts = [topic]
        if region:
            parts.append(region)
        if content:
            parts.append(content)

        query = " ".join(parts)
        # 替换连字符为空格（API 要求）
        query = query.replace("-", " ")
        return query.strip()
