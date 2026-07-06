"""OpenAlex 检索引擎.

通过 OpenAlex API 检索英文学术文献。
API 文档: https://docs.openalex.org/api-entities/works

特点:
    - 2.4亿篇论文的全学科覆盖（Microsoft Academic Graph 继承者）
    - 完全免费，无需 API Key（推荐邮箱用于 polite pool）
    - 支持 search + filter 组合检索
    - 返回引用关系、作者、期刊、DOI、OA PDF 等富字段
    - 无反爬限制，稳定可靠
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
OPENALEX_BASE = "https://api.openalex.org"
WORKS_URL = f"{OPENALEX_BASE}/works"

# 默认返回字段（通过 select 参数指定，减少传输量）
DEFAULT_SELECT = ",".join([
    "id",
    "doi",
    "title",
    "display_name",
    "publication_year",
    "publication_date",
    "abstract_inverted_index",
    "authorships",
    "cited_by_count",
    "referenced_works_count",
    "open_access",
    "primary_location",
    "best_oa_location",
    "concepts",
    "topics",
    "keywords",
    "language",
    "type",
    "biblio",
])


@dataclass
class OpenAlexPaper:
    """OpenAlex 论文数据模型."""

    work_id: str = ""  # OpenAlex ID (如 W2741809807)
    title: str = ""
    abstract: str = ""  # 从 inverted index 还原
    year: Optional[int] = None
    publication_date: str = ""
    authors: list[str] = field(default_factory=list)
    author_institutions: list[str] = field(default_factory=list)
    cited_by_count: int = 0
    referenced_works_count: int = 0
    is_open_access: bool = False
    oa_url: str = ""
    oa_pdf_url: str = ""
    primary_venue: str = ""  # 期刊或会议名
    primary_venue_type: str = ""  # journal/conference/repository
    doi: str = ""
    concepts: list[str] = field(default_factory=list)  # 学科概念
    topics: list[str] = field(default_factory=list)  # 主题
    keywords: list[str] = field(default_factory=list)
    language: str = ""
    work_type: str = ""  # article/review/book-chapter
    biblio_volume: str = ""
    biblio_issue: str = ""
    biblio_first_page: str = ""
    biblio_last_page: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_id": self.work_id,
            "title": self.title,
            "abstract": self.abstract,
            "year": self.year,
            "authors": self.authors,
            "cited_by_count": self.cited_by_count,
            "is_open_access": self.is_open_access,
            "oa_pdf_url": self.oa_pdf_url,
            "primary_venue": self.primary_venue,
            "doi": self.doi,
            "concepts": self.concepts,
            "work_type": self.work_type,
            "url": self.url,
        }

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> OpenAlexPaper:
        """从 OpenAlex API 响应构建 OpenAlexPaper."""
        paper = cls()
        paper.work_id = data.get("id", "").replace("https://openalex.org/", "")
        paper.title = data.get("display_name", "") or data.get("title", "") or ""
        paper.year = data.get("publication_year")
        paper.publication_date = data.get("publication_date", "") or ""

        # 从 inverted index 还原摘要
        inv_idx = data.get("abstract_inverted_index")
        if inv_idx:
            paper.abstract = _reconstruct_abstract(inv_idx)

        # 作者和机构
        authorships = data.get("authorships", [])
        for a in authorships:
            author = a.get("author", {})
            name = author.get("display_name", "")
            if name:
                paper.authors.append(name)
            institutions = a.get("institutions", [])
            for inst in institutions:
                inst_name = inst.get("display_name", "")
                if inst_name and inst_name not in paper.author_institutions:
                    paper.author_institutions.append(inst_name)

        # 引用统计
        paper.cited_by_count = data.get("cited_by_count", 0) or 0
        paper.referenced_works_count = data.get("referenced_works_count", 0) or 0

        # 开放获取
        oa = data.get("open_access", {})
        if oa:
            paper.is_open_access = oa.get("is_oa", False) or False
            paper.oa_url = oa.get("oa_url", "") or ""

        # 最佳 OA 位置
        best_oa = data.get("best_oa_location")
        if best_oa:
            paper.oa_pdf_url = best_oa.get("pdf_url", "") or ""

        # 主要发表位置
        primary_loc = data.get("primary_location")
        if primary_loc:
            source = primary_loc.get("source", {})
            if source:
                paper.primary_venue = source.get("display_name", "") or ""
                paper.primary_venue_type = source.get("type", "") or ""

        # DOI
        doi = data.get("doi", "")
        if doi:
            paper.doi = doi.replace("https://doi.org/", "")

        # 概念和主题
        concepts = data.get("concepts", [])
        paper.concepts = [c.get("display_name", "") for c in concepts[:10] if c.get("display_name")]
        topics = data.get("topics", [])
        paper.topics = [t.get("display_name", "") for t in topics[:5] if t.get("display_name")]
        keywords = data.get("keywords", [])
        paper.keywords = [k.get("display_name", "") for k in keywords[:5] if k.get("display_name")]

        paper.language = data.get("language", "") or ""
        paper.work_type = data.get("type", "") or ""

        # 书目信息
        biblio = data.get("biblio", {})
        if biblio:
            paper.biblio_volume = biblio.get("volume", "") or ""
            paper.biblio_issue = biblio.get("issue", "") or ""
            paper.biblio_first_page = biblio.get("first_page", "") or ""
            paper.biblio_last_page = biblio.get("last_page", "") or ""

        paper.url = data.get("id", "") or ""
        return paper


def _reconstruct_abstract(inv_idx: dict[str, list[int]]) -> str:
    """从 OpenAlex 的 inverted index 还原摘要文本.

    Args:
        inv_idx: {"word": [pos1, pos2], ...}

    Returns:
        还原后的摘要字符串.
    """
    if not inv_idx:
        return ""
    # 构建位置→词的映射
    pos_word: dict[int, str] = {}
    for word, positions in inv_idx.items():
        for pos in positions:
            pos_word[pos] = word
    # 按位置排序拼接
    max_pos = max(pos_word.keys()) if pos_word else 0
    words = [pos_word.get(i, "") for i in range(max_pos + 1)]
    return " ".join(w for w in words if w)


@dataclass
class OpenAlexSearchResult:
    """OpenAlex 检索结果."""

    query: str = ""
    total_count: int = 0
    papers: list[OpenAlexPaper] = field(default_factory=list)
    page: int = 1
    per_page: int = 25

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
            "page": self.page,
            "per_page": self.per_page,
        }


class OpenAlexEngine:
    """OpenAlex 检索引擎.

    通过 OpenAlex API 检索英文学术文献，无需 API Key。

    Usage:
        engine = OpenAlexEngine(mailto="your@email.com")
        result = await engine.search("fiscal policy economic growth", limit=20)
        for paper in result.papers:
            print(f"{paper.title} ({paper.year}) - cited by {paper.cited_by_count}")
    """

    def __init__(
        self,
        mailto: str = "",
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """初始化 OpenAlex 检索引擎.

        Args:
            mailto: 联系邮箱（推荐，进入 polite pool 获得更高速率）.
            mailto: 联系邮箱（推荐，进入 polite pool 获得更高速率）.
            timeout: 请求超时秒数.
            max_retries: 最大重试次数.
        """
        self.mailto = mailto
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端."""
        if self._client is None or self._client.is_closed:
            configure_no_proxy()
            headers = {
                "User-Agent": f"ScholarPilot/0.1.0 (Academic Research Tool{f'; mailto:{self.mailto}' if self.mailto else ''})",
                "Accept": "application/json",
            }
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                proxy=None,
                trust_env=False,
            )
        return self._client

    @staticmethod
    def build_query(topic: str, region: str = "", content: str = "") -> str:
        """构建 OpenAlex 检索查询.

        OpenAlex 的 search 参数会在标题、摘要、全文中搜索，
        不需要复杂的查询语法，直接用关键词即可。

        Args:
            topic: 核心主题（英文）.
            region: 研究区域（英文）.
            content: 研究内容（英文）.

        Returns:
            搜索查询字符串.
        """
        parts = [p.strip() for p in [topic, region, content] if p and p.strip()]
        return " ".join(parts)

    @staticmethod
    def build_filter(
        year_start: str = "",
        year_end: str = "",
        is_oa: bool = False,
        has_abstract: bool = False,
        work_type: str = "",
    ) -> str:
        """构建 OpenAlex 过滤器.

        Args:
            year_start: 起始年份.
            year_end: 结束年份.
            is_oa: 是否仅返回开放获取论文.
            has_abstract: 是否仅返回有摘要的论文.
            work_type: 论文类型（article/review/book-chapter）.

        Returns:
            过滤器字符串，如 "publication_year:2019-2026,is_oa:true".
        """
        filters = []
        if year_start and year_end:
            filters.append(f"from_publication_date:{year_start}-01-01")
            filters.append(f"to_publication_date:{year_end}-12-31")
        elif year_start:
            filters.append(f"from_publication_date:{year_start}-01-01")
        if is_oa:
            filters.append("is_oa:true")
        if has_abstract:
            filters.append("has_abstract:true")
        if work_type:
            filters.append(f"type:{work_type}")
        return ",".join(filters)

    async def search(
        self,
        query: str,
        limit: int = 25,
        year_start: str = "",
        year_end: str = "",
        is_oa: bool = False,
        has_abstract: bool = False,
        work_type: str = "",
        sort: str = "relevance_score:desc",
    ) -> OpenAlexSearchResult:
        """检索 OpenAlex 文献.

        Args:
            query: 搜索查询字符串.
            limit: 返回论文数量（最大 200）.
            year_start: 起始年份.
            year_end: 结束年份.
            is_oa: 是否仅返回开放获取论文.
            has_abstract: 是否仅返回有摘要的论文.
            work_type: 论文类型.
            sort: 排序方式（relevance_score:desc / cited_by_count:desc / publication_date:desc）.

        Returns:
            OpenAlexSearchResult 对象.
        """
        client = await self._get_client()
        limit = min(limit, 200)  # OpenAlex 单次最多 200 条

        params: dict[str, Any] = {
            "search": query,
            "per-page": limit,
            "select": DEFAULT_SELECT,
        }

        # 构建过滤器
        filters = self.build_filter(
            year_start=year_start,
            year_end=year_end,
            is_oa=is_oa,
            has_abstract=has_abstract,
            work_type=work_type,
        )
        if filters:
            params["filter"] = filters

        if sort:
            params["sort"] = sort

        logger.info(f"OpenAlex 搜索: query={query}, limit={limit}, filters={filters}")

        # 重试机制
        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = await client.get(WORKS_URL, params=params)
                if resp.status_code == 429:
                    wait = 3 * (attempt + 1)
                    logger.warning(f"OpenAlex 429 rate limited, waiting {wait}s (attempt {attempt+1}/{self.max_retries})")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()

                total = data.get("meta", {}).get("count", 0)
                results = data.get("results", [])
                papers = [OpenAlexPaper.from_api_response(r) for r in results]

                return OpenAlexSearchResult(
                    query=query,
                    total_count=total,
                    papers=papers,
                    page=1,
                    per_page=limit,
                )

            except Exception as e:
                last_error = e
                logger.warning(f"OpenAlex 搜索失败 (attempt {attempt+1}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))

        # 所有重试失败
        logger.error(f"OpenAlex 搜索最终失败: {last_error}")
        return OpenAlexSearchResult(query=query, total_count=0, papers=[])

    async def get_citing_works(
        self,
        work_id: str,
        limit: int = 25,
        sort: str = "publication_date:desc",
    ) -> OpenAlexSearchResult:
        """获取引用了指定论文的文献列表（反向引用追踪）.

        OpenAlex 支持通过 filter=cites:W2741809807 查询引用该论文的所有文献。
        用于文献订阅功能中的"引用追踪"策略。

        API: GET /works?filter=cites:W2741809807
        注意: work_id 需要是 OpenAlex ID 格式（如 W2741809807），
        如果传入带 https://openalex.org/ 前缀的完整 URL，会自动去除。

        Args:
            work_id: OpenAlex Work ID（如 W2741809807）。
            limit: 返回数量（最大 200）。
            sort: 排序方式（publication_date:desc / cited_by_count:desc）。

        Returns:
            OpenAlexSearchResult: 引用该论文的文献列表。
        """
        client = await self._get_client()
        limit = min(limit, 200)

        # 规范化 work_id（去除 URL 前缀）
        clean_id = work_id.replace("https://openalex.org/", "").strip()

        params: dict[str, Any] = {
            "filter": f"cites:{clean_id}",
            "per-page": limit,
            "select": DEFAULT_SELECT,
        }

        if sort:
            params["sort"] = sort

        logger.info(f"OpenAlex citing works: work_id={clean_id}, limit={limit}")

        # 重试机制
        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = await client.get(WORKS_URL, params=params)
                if resp.status_code == 429:
                    wait = 3 * (attempt + 1)
                    logger.warning(f"OpenAlex 429 rate limited, waiting {wait}s (attempt {attempt+1}/{self.max_retries})")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()

                total = data.get("meta", {}).get("count", 0)
                results = data.get("results", [])
                papers = [OpenAlexPaper.from_api_response(r) for r in results]

                logger.info(
                    f"OpenAlex citing works for {clean_id}: "
                    f"{total} total, {len(papers)} returned"
                )
                return OpenAlexSearchResult(
                    query=f"cites:{clean_id}",
                    total_count=total,
                    papers=papers,
                    page=1,
                    per_page=limit,
                )

            except Exception as e:
                last_error = e
                logger.warning(f"OpenAlex citing works failed (attempt {attempt+1}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))

        logger.error(f"OpenAlex citing works final failure: {last_error}")
        return OpenAlexSearchResult(query=f"cites:{clean_id}", total_count=0, papers=[])

    async def get_referenced_works(
        self,
        work_id: str,
        limit: int = 25,
    ) -> OpenAlexSearchResult:
        """获取指定论文引用的文献列表（正向引用追踪）.

        通过 OpenAlex 的 referenced_works 字段批量查询。
        需要先获取该论文的 referenced_works 列表，再批量查询。

        Args:
            work_id: OpenAlex Work ID。
            limit: 返回数量。

        Returns:
            OpenAlexSearchResult: 被该论文引用的文献列表。
        """
        client = await self._get_client()
        clean_id = work_id.replace("https://openalex.org/", "").strip()

        # 先获取该论文的 referenced_works 列表
        try:
            resp = await client.get(
                f"{WORKS_URL}/{clean_id}",
                params={"select": "referenced_works"},
            )
            resp.raise_for_status()
            data = resp.json()
            ref_ids = data.get("referenced_works", [])

            if not ref_ids:
                return OpenAlexSearchResult(query=f"refs:{clean_id}", total_count=0, papers=[])

            # 截取 limit 数量的引用 ID
            ref_ids = ref_ids[:min(limit, 200)]

            # 批量查询：使用 filter=openalex:W123|W456|...
            filter_value = "|".join(
                rid.replace("https://openalex.org/", "") for rid in ref_ids
            )

            params: dict[str, Any] = {
                "filter": f"openalex:{filter_value}",
                "per-page": len(ref_ids),
                "select": DEFAULT_SELECT,
            }

            resp = await client.get(WORKS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            papers = [OpenAlexPaper.from_api_response(r) for r in results]

            return OpenAlexSearchResult(
                query=f"refs:{clean_id}",
                total_count=len(ref_ids),
                papers=papers,
                page=1,
                per_page=len(papers),
            )

        except Exception as e:
            logger.error(f"OpenAlex get_referenced_works failed: {e}")
            return OpenAlexSearchResult(query=f"refs:{clean_id}", total_count=0, papers=[])

    async def close(self) -> None:
        """关闭 HTTP 客户端."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


__all__ = ["OpenAlexEngine", "OpenAlexPaper", "OpenAlexSearchResult"]
