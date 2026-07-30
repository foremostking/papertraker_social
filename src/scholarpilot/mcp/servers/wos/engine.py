"""Web of Science 检索引擎实现.

双模式架构：
1. 官方 REST API（WoSLite）: https://api.clarivate.com/api/woslite
   - 需要 API Key (X-ApiKey header)
   - GET 请求，返回 JSON
   - 适用于有 Clarivate API 订阅的机构

2. Web Session API: https://webofscience.clarivate.cn/api/wosnx/core/
   - 需要浏览器登录后的 SID (X-1P-WOS-SID header)
   - POST 请求，返回 JSON
   - 适用于通过 VPN/Shibboleth 登录的用户
   - SID 获取方法：浏览器登录 WoS → DevTools → Application → Session Storage → 查找 SID

WoS 查询语言 (WQL) 示例：
- TS=(fiscal policy)             主题搜索
- TS=(fiscal policy) AND PY=2020-2025  主题+年份
- TI=(government debt)           标题搜索
- AU=(Zhang Wei) AND SO=(Economics)  作者+期刊

API 响应结构（官方 API）：
{
  "QueryResult": {"RecordsFound": 1234},
  "Records": {
    "records": [
      {
        "UID": "WOS:000123456789",
        "title": {"value": "Paper Title"},
        "authors": {"authors": [{"full_name": "Author Name"}]},
        "source": {"title": {"value": "Journal Name"}, "year": 2024},
        "abstract": {"value": "Abstract text"},
        "doi": {"value": "10.1234/xxx"},
        "cited_by_count": 42,
        ...
      }
    ]
  }
}

API 响应结构（Session API /api/wosnx/core/runQuerySearch）：
返回 JSON 数组，每条记录包含：
- uid: WoS ID
- title: 标题
- authors: 作者列表
- source: 期刊信息
- pub_info: 出版信息
- abstract: 摘要
- total_citations: 被引次数
- doi: DOI
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import httpx

from scholarpilot.utils.network import configure_no_proxy

logger = logging.getLogger(__name__)

# ===== API 端点 =====

# 官方 WoSLite REST API
WOS_API_BASE = "https://api.clarivate.com/api/woslite"

# Web Session API (通过 VPN/浏览器登录)
WOS_WEB_BASE = "https://webofscience.clarivate.cn"
WOS_WEB_SEARCH_API = f"{WOS_WEB_BASE}/api/wosnx/core/runQuerySearch"
WOS_WEB_RECORDS_API = f"{WOS_WEB_BASE}/api/wosnx/core/runQueryGetRecordsStream"
WOS_WEB_FULL_RECORD_API = f"{WOS_WEB_BASE}/api/wosnx/core/getFullRecordByQueryId"

# WoS 数据库 ID
WOS_DATABASE_ID = "WOK"  # Web of Knowledge (含 SCI/SSCI/AHCI)

# 默认检索字段
DEFAULT_FIELDS = ",".join([
    "UID",
    "title",
    "authors",
    "source",
    "abstract",
    "doi",
    "cited_by_count",
    "publication_info",
    "keywords",
    "categories",
    "open_access",
])


class WoSAccessMode(Enum):
    """WoS 访问模式."""

    NONE = "none"  # 无可用访问方式
    API_KEY = "api_key"  # 官方 REST API
    SESSION = "session"  # Web Session API (SID)
    VPN_SESSION = "vpn_session"  # VPN + Session (自动检测)


# ===== 数据模型 =====


@dataclass
class WoSPaper:
    """Web of Science 论文数据模型."""

    uid: str = ""  # WoS Unique Identifier (UT)
    title: str = ""
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    journal: str = ""  # 期刊/来源
    volume: str = ""
    issue: str = ""
    page_range: str = ""
    doi: str = ""
    keywords: list[str] = field(default_factory=list)
    keywords_plus: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)  # WoS 学科分类
    cited_by_count: int = 0
    is_open_access: bool = False
    oa_url: str = ""
    document_type: str = ""  # Article/Review/Proceedings Paper
    language: str = ""
    url: str = ""
    source: str = "wos"

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "volume": self.volume,
            "issue": self.issue,
            "page_range": self.page_range,
            "doi": self.doi,
            "keywords": self.keywords,
            "keywords_plus": self.keywords_plus,
            "categories": self.categories,
            "cited_by_count": self.cited_by_count,
            "is_open_access": self.is_open_access,
            "oa_url": self.oa_url,
            "document_type": self.document_type,
            "language": self.language,
            "url": self.url,
            "source": self.source,
        }


@dataclass
class WoSSearchResult:
    """WoS 检索结果."""

    query: str = ""
    total_count: int = 0
    papers: list[WoSPaper] = field(default_factory=list)
    access_mode: str = "none"
    query_id: str = ""  # Session 模式下的查询 ID
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
            "access_mode": self.access_mode,
            "query_id": self.query_id,
            "error": self.error,
        }


# ===== WoS 查询语言构建器 =====


class WoSQueryBuilder:
    """WoS 查询语言 (WQL) 构建器.

    WoS 使用字段前缀 + 布尔运算的查询语法：
    - TS=(topic)        主题搜索（标题+摘要+关键词）
    - TI=(title)        标题搜索
    - AU=(author)       作者搜索
    - SO=(source)       期刊搜索
    - PY=year-year      年份范围
    - AND/OR/NOT        布尔运算
    """

    @staticmethod
    def build_topic_query(
        topic: str,
        year_start: str = "",
        year_end: str = "",
    ) -> str:
        """构建主题检索式.

        Args:
            topic: 检索主题（英文关键词）.
            year_start: 起始年份.
            year_end: 结束年份.

        Returns:
            WoS 查询字符串，如 "TS=(fiscal policy) AND PY=2020-2025".
        """
        parts: list[str] = []

        if topic:
            # 主题搜索，使用括号包裹
            parts.append(f"TS=({topic})")

        if year_start and year_end:
            parts.append(f"PY={year_start}-{year_end}")
        elif year_start:
            parts.append(f"PY={year_start}-")
        elif year_end:
            parts.append(f"PY=-{year_end}")

        return " AND ".join(parts) if parts else ""

    @staticmethod
    def build_advanced_query(
        topic: str = "",
        title: str = "",
        author: str = "",
        journal: str = "",
        year_start: str = "",
        year_end: str = "",
        doi: str = "",
    ) -> str:
        """构建高级检索式.

        Args:
            topic: 主题关键词.
            title: 标题关键词.
            author: 作者名.
            journal: 期刊名.
            year_start: 起始年份.
            year_end: 结束年份.
            doi: DOI.

        Returns:
            WoS 查询字符串.
        """
        parts: list[str] = []

        if topic:
            parts.append(f"TS=({topic})")
        if title:
            parts.append(f"TI=({title})")
        if author:
            parts.append(f"AU=({author})")
        if journal:
            parts.append(f"SO=({journal})")
        if doi:
            parts.append(f"DO=({doi})")

        if year_start and year_end:
            parts.append(f"PY={year_start}-{year_end}")
        elif year_start:
            parts.append(f"PY={year_start}-")

        return " AND ".join(parts) if parts else ""


# ===== WoS 检索引擎 =====


class WoSEngine:
    """Web of Science 检索引擎.

    支持双模式访问：
    1. 官方 REST API（需 API Key）
    2. Web Session API（需 SID，从浏览器登录获取）

    自动选择可用模式：API Key 优先，其次 SID。

    Usage:
        # 官方 API 模式
        engine = WoSEngine(api_key="your_key")
        result = await engine.search("fiscal policy", limit=20)

        # Session 模式
        engine = WoSEngine(sid="your_sid_from_browser")
        result = await engine.search("fiscal policy", limit=20)

        # 自动检测模式
        engine = WoSEngine(api_key=settings.wos_api_key, sid=settings.wos_sid)
        result = await engine.search("fiscal policy", limit=20)
    """

    def __init__(
        self,
        api_key: str = "",
        sid: str = "",
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """初始化 WoS 检索引擎.

        Args:
            api_key: Clarivate API Key（可选，优先使用）.
            sid: WoS Session ID（从浏览器登录获取，可选）.
            timeout: 请求超时秒数.
            max_retries: 最大重试次数.
        """
        self.api_key = api_key
        self.sid = sid
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None
        self._session_initialized = False

        # 确定访问模式
        if api_key:
            self.access_mode = WoSAccessMode.API_KEY
            logger.info("WoS engine initialized with API Key mode")
        elif sid:
            self.access_mode = WoSAccessMode.SESSION
            logger.info("WoS engine initialized with Session (SID) mode")
        else:
            self.access_mode = WoSAccessMode.NONE
            logger.warning(
                "WoS engine initialized without API Key or SID. "
                "Search will return empty results. "
                "Configure SCHOLAR_WOS_API_KEY or SCHOLAR_WOS_SID to enable."
            )

    @property
    def is_available(self) -> bool:
        """引擎是否可用（有有效的访问方式）."""
        return self.access_mode != WoSAccessMode.NONE

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端."""
        if self._client is None or self._client.is_closed:
            configure_no_proxy()

            headers: dict[str, str] = {
                "User-Agent": "ScholarPilot/0.1.0 (Academic Research Tool)",
                "Accept": "application/json",
            }

            # 根据模式设置不同的 headers
            if self.access_mode == WoSAccessMode.API_KEY:
                headers["X-ApiKey"] = self.api_key
            elif self.access_mode == WoSAccessMode.SESSION:
                headers["X-1P-WOS-SID"] = self.sid
                headers["Content-Type"] = "application/json"
                # 浏览器 UA（Session 模式需要）
                headers["User-Agent"] = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
                headers["Accept-Language"] = "zh-CN,zh;q=0.9,en;q=0.8"
                headers["Referer"] = f"{WOS_WEB_BASE}/wos/woscc/basic-search"

            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                proxy=None,
                trust_env=False,
            )

        return self._client

    async def _ensure_web_session(self) -> bool:
        """确保 Web Session 已建立（Session 模式）.

        访问 WoS 首页获取必要的 cookies（如 Cloudflare token）.

        Returns:
            True 如果 session 建立成功.
        """
        if self.access_mode != WoSAccessMode.SESSION:
            return False

        if self._session_initialized:
            return True

        client = await self._get_client()

        try:
            # 访问 WoS 首页建立 session（获取 Cloudflare cookies）
            resp = await client.get(f"{WOS_WEB_BASE}/wos/woscc/basic-search")
            if resp.status_code == 200:
                self._session_initialized = True
                logger.debug("WoS web session established")
                return True
            else:
                logger.warning(f"WoS session setup failed: HTTP {resp.status_code}")
                return False
        except Exception as e:
            logger.warning(f"WoS session setup error: {e}")
            return False

    async def close(self) -> None:
        """关闭 HTTP 客户端."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ===== 检索方法 =====

    async def search(
        self,
        query: str,
        limit: int = 20,
        year_start: str = "",
        year_end: str = "",
        sort: str = "relevance",
    ) -> WoSSearchResult:
        """执行 WoS 检索.

        自动选择可用的访问模式（API Key 优先，其次 SID）.

        Args:
            query: 检索词或 WoS 查询式.
                   纯文本会自动构建为 TS=(query) 格式.
            limit: 返回数量.
            year_start: 起始年份（如 "2020"）.
            year_end: 结束年份（如 "2025"）.
            sort: 排序方式 (relevance/date/citations).

        Returns:
            WoSSearchResult: 检索结果.
        """
        if not self.is_available:
            return WoSSearchResult(
                query=query,
                error="WoS engine not configured. Set SCHOLAR_WOS_API_KEY or SCHOLAR_WOS_SID.",
            )

        # 构建 WoS 查询式
        wos_query = self._build_query(query, year_start, year_end)
        if not wos_query:
            return WoSSearchResult(query=query, error="Empty query")

        logger.info(f"WoS search: query='{wos_query}', mode={self.access_mode.value}")

        # 根据模式选择检索方法
        if self.access_mode == WoSAccessMode.API_KEY:
            return await self._search_via_api(wos_query, query, limit)
        elif self.access_mode == WoSAccessMode.SESSION:
            return await self._search_via_session(wos_query, query, limit)
        else:
            return WoSSearchResult(query=query, error="No available access mode")

    async def _search_via_api(
        self,
        wos_query: str,
        original_query: str,
        limit: int,
    ) -> WoSSearchResult:
        """通过官方 REST API 检索.

        GET https://api.clarivate.com/api/woslite
        ?databaseId=WOK&usrQuery=TS=(fiscal policy)&count=20&firstRecord=1
        """
        client = await self._get_client()

        params: dict[str, Any] = {
            "databaseId": WOS_DATABASE_ID,
            "usrQuery": wos_query,
            "count": min(limit, 100),
            "firstRecord": 1,
        }

        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = await client.get(WOS_API_BASE, params=params)

                # 429 限流
                if resp.status_code == 429:
                    wait = 5 * (attempt + 1)
                    logger.warning(
                        f"WoS API 429 rate limited, waiting {wait}s "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(wait)
                        continue

                resp.raise_for_status()
                data = resp.json()

                return self._parse_api_response(data, original_query)

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.error(
                    f"WoS API error: {e.response.status_code} - "
                    f"{e.response.text[:200]}"
                )
                if e.response.status_code == 401:
                    return WoSSearchResult(
                        query=original_query,
                        error="Invalid API Key. Check SCHOLAR_WOS_API_KEY.",
                    )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))

            except Exception as e:
                last_error = e
                logger.error(f"WoS API search failed: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))

        return WoSSearchResult(
            query=original_query,
            error=f"Search failed after {self.max_retries} retries: {last_error}",
        )

    async def _search_via_session(
        self,
        wos_query: str,
        original_query: str,
        limit: int,
    ) -> WoSSearchResult:
        """通过 Web Session API 检索.

        POST https://webofscience.clarivate.cn/api/wosnx/core/runQuerySearch
        Body: {
            "databaseId": "WOK",
            "userQuery": "TS=(fiscal policy)",
            "retrieveParameters": {
                "firstRecord": 1,
                "count": 50,
                "sortField": ...
            }
        }

        响应: JSON 数组，包含查询结果或错误信息
        [{"id":0,"key":"queryId","payload":"xxx"}, ...]
        """
        await self._ensure_web_session()
        client = await self._get_client()

        # 构建请求体
        payload: dict[str, Any] = {
            "databaseId": WOS_DATABASE_ID,
            "userQuery": wos_query,
            "retrieveParameters": {
                "firstRecord": 1,
                "count": min(limit, 50),
                "sortField": [
                    {"name": "Published.BiblioYear", "sort": "D"}
                ],
            },
            "isFullRecord": False,
            "linksOnly": False,
            "additionalFields": {
                "fields": [
                    "fullRecord",
                ],
            },
        }

        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = await client.post(WOS_WEB_SEARCH_API, json=payload)

                resp.raise_for_status()

                # Session API 返回 JSON 数组
                data = resp.json()

                # 检查错误
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("key") == "error":
                            error_payload = item.get("payload", "")
                            if "sessionNotFound" in str(error_payload):
                                return WoSSearchResult(
                                    query=original_query,
                                    error=(
                                        "WoS session expired. Please re-login to WoS "
                                        "in your browser and update SCHOLAR_WOS_SID."
                                    ),
                                )
                            return WoSSearchResult(
                                query=original_query,
                                error=f"WoS API error: {error_payload}",
                            )

                # 解析正常响应
                return self._parse_session_response(data, original_query)

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.error(
                    f"WoS Session API error: {e.response.status_code} - "
                    f"{e.response.text[:200]}"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))

            except Exception as e:
                last_error = e
                logger.error(f"WoS Session search failed: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))

        return WoSSearchResult(
            query=original_query,
            error=f"Search failed after {self.max_retries} retries: {last_error}",
        )

    # ===== 响应解析 =====

    def _parse_api_response(
        self,
        data: dict[str, Any],
        query: str,
    ) -> WoSSearchResult:
        """解析官方 REST API 响应.

        响应结构:
        {
            "QueryResult": {"RecordsFound": 1234, ...},
            "Records": {"records": [...]}
        }
        """
        result = WoSSearchResult(query=query, access_mode="api_key")

        # 总数
        query_result = data.get("QueryResult", {})
        result.total_count = query_result.get("RecordsFound", 0)

        # 论文列表
        records_data = data.get("Records", {})
        records = records_data.get("records", [])

        for record in records:
            paper = self._parse_api_record(record)
            if paper.title:
                result.papers.append(paper)

        logger.info(
            f"WoS API search '{query}': "
            f"{result.total_count} total, {len(result.papers)} returned"
        )
        return result

    def _parse_api_record(self, record: dict[str, Any]) -> WoSPaper:
        """解析官方 API 的单条论文记录."""
        paper = WoSPaper()

        # UID
        paper.uid = record.get("UID", "")

        # 标题
        title_data = record.get("title", {})
        if isinstance(title_data, dict):
            paper.title = title_data.get("value", "")
        elif isinstance(title_data, str):
            paper.title = title_data

        # 摘要
        abstract_data = record.get("abstract", {})
        if isinstance(abstract_data, dict):
            paper.abstract = abstract_data.get("value", "")
        elif isinstance(abstract_data, str):
            paper.abstract = abstract_data

        # 作者
        authors_data = record.get("authors", {})
        if isinstance(authors_data, dict):
            for author in authors_data.get("authors", []):
                name = author.get("full_name", "") or author.get("display_name", "")
                if name:
                    paper.authors.append(name)
        elif isinstance(authors_data, list):
            for author in authors_data:
                if isinstance(author, dict):
                    name = author.get("full_name", "") or author.get("display_name", "")
                else:
                    name = str(author)
                if name:
                    paper.authors.append(name)

        # 来源（期刊）
        source_data = record.get("source", {})
        if isinstance(source_data, dict):
            title_src = source_data.get("title", {})
            if isinstance(title_src, dict):
                paper.journal = title_src.get("value", "")
            elif isinstance(title_src, str):
                paper.journal = title_src

            paper.volume = source_data.get("volume", "")
            paper.issue = source_data.get("issue", "")

            page_data = source_data.get("page", {})
            if isinstance(page_data, dict):
                begin = page_data.get("begin", "")
                end = page_data.get("end", "")
                if begin and end:
                    paper.page_range = f"{begin}-{end}"
                elif begin:
                    paper.page_range = begin

            # 年份
            year = source_data.get("year")
            if year:
                paper.year = int(year) if isinstance(year, (int, str)) else None

        # DOI
        doi_data = record.get("doi", {})
        if isinstance(doi_data, dict):
            paper.doi = doi_data.get("value", "")
        elif isinstance(doi_data, str):
            paper.doi = doi_data

        # 关键词
        keywords_data = record.get("keywords", {})
        if isinstance(keywords_data, dict):
            paper.keywords = keywords_data.get("keywords", [])
            paper.keywords_plus = keywords_data.get("keywords_plus", [])

        # 学科分类
        categories_data = record.get("categories", {})
        if isinstance(categories_data, dict):
            for cat in categories_data.get("categories", []):
                name = cat.get("name", "") or cat.get("heading", "")
                if name:
                    paper.categories.append(name)

        # 被引次数
        metrics = record.get("cited_by_count", 0)
        if isinstance(metrics, dict):
            paper.cited_by_count = metrics.get("count", 0)
        else:
            paper.cited_by_count = int(metrics or 0)

        # 开放获取
        oa_data = record.get("open_access", {})
        if isinstance(oa_data, dict):
            paper.is_open_access = oa_data.get("is_oa", False)
            paper.oa_url = oa_data.get("oa_url", "")

        # 文档类型
        doctype_data = record.get("document_type", {})
        if isinstance(doctype_data, dict):
            doctypes = doctype_data.get("document_types", [])
            if doctypes:
                paper.document_type = doctypes[0]
        elif isinstance(doctype_data, list) and doctype_data:
            paper.document_type = str(doctype_data[0])

        # 语言
        lang_data = record.get("language", {})
        if isinstance(lang_data, dict):
            paper.language = lang_data.get("value", "")
        elif isinstance(lang_data, str):
            paper.language = lang_data

        # URL
        paper.url = f"{WOS_WEB_BASE}/wos/woscc/full-record/{paper.uid}"

        return paper

    def _parse_session_response(
        self,
        data: Any,
        query: str,
    ) -> WoSSearchResult:
        """解析 Web Session API 响应.

        Session API 返回 JSON 数组，格式可能为：
        [
            {"id":0,"key":"queryId","payload":"xxx"},
            {"id":1,"key":"records","payload":{"records":[...], "total":123}},
            ...
        ]

        或直接返回记录列表.
        """
        result = WoSSearchResult(query=query, access_mode="session")

        if isinstance(data, list):
            # 遍历查找 queryId 和 records
            for item in data:
                if not isinstance(item, dict):
                    continue

                key = item.get("key", "")
                payload = item.get("payload", "")

                if key == "queryId":
                    result.query_id = str(payload)

                elif key == "records" or key == "Records":
                    # payload 可能是 dict 或 list
                    if isinstance(payload, dict):
                        result.total_count = payload.get("total", 0) or payload.get("RecordsFound", 0)
                        records = payload.get("records", payload.get("Records", []))
                        for record in records:
                            paper = self._parse_session_record(record)
                            if paper.title:
                                result.papers.append(paper)
                    elif isinstance(payload, list):
                        result.total_count = len(payload)
                        for record in payload:
                            paper = self._parse_session_record(record)
                            if paper.title:
                                result.papers.append(paper)

                elif key == "total" or key == "RecordsFound":
                    result.total_count = int(payload or 0)

                elif key == "FullRecordData" or key == "fullRecord":
                    # 完整记录数据
                    if isinstance(payload, list):
                        for record in payload:
                            paper = self._parse_session_record(record)
                            if paper.title:
                                result.papers.append(paper)

        elif isinstance(data, dict):
            # 直接返回字典
            result.total_count = data.get("total", 0) or data.get("RecordsFound", 0)
            records = data.get("records", data.get("Records", data.get("data", [])))
            for record in records:
                paper = self._parse_session_record(record)
                if paper.title:
                    result.papers.append(paper)

        # 如果没有找到记录但 total > 0，可能需要额外调用获取记录
        if not result.papers and result.total_count > 0 and result.query_id:
            logger.info(
                f"WoS search returned {result.total_count} results but no records. "
                f"Query ID: {result.query_id}. May need to fetch records separately."
            )

        logger.info(
            f"WoS Session search '{query}': "
            f"{result.total_count} total, {len(result.papers)} returned"
        )
        return result

    def _parse_session_record(self, record: dict[str, Any]) -> WoSPaper:
        """解析 Session API 的单条论文记录.

        Session API 的记录格式与官方 API 略有不同，
        字段名可能使用 camelCase 或不同结构.
        """
        paper = WoSPaper()

        # UID / UT
        paper.uid = record.get("uid", record.get("UID", record.get("UT", "")))

        # 标题
        title_data = record.get("title", record.get("Title", {}))
        if isinstance(title_data, dict):
            paper.title = title_data.get("value", title_data.get("Value", ""))
        elif isinstance(title_data, str):
            paper.title = title_data

        # 摘要
        abstract_data = record.get("abstract", record.get("Abstract", {}))
        if isinstance(abstract_data, dict):
            paper.abstract = abstract_data.get("value", abstract_data.get("Value", ""))
        elif isinstance(abstract_data, str):
            paper.abstract = abstract_data

        # 作者
        authors_data = record.get("authors", record.get("Authors", {}))
        if isinstance(authors_data, dict):
            for author in authors_data.get("authors", authors_data.get("Authors", [])):
                name = (
                    author.get("full_name", "")
                    or author.get("fullName", "")
                    or author.get("display_name", "")
                    or author.get("DisplayName", "")
                )
                if name:
                    paper.authors.append(name)
        elif isinstance(authors_data, list):
            for author in authors_data:
                if isinstance(author, dict):
                    name = (
                        author.get("full_name", "")
                        or author.get("fullName", "")
                        or author.get("display_name", "")
                    )
                else:
                    name = str(author)
                if name:
                    paper.authors.append(name)

        # 来源
        source_data = record.get("source", record.get("Source", {}))
        if isinstance(source_data, dict):
            title_src = source_data.get("title", source_data.get("Title", {}))
            if isinstance(title_src, dict):
                paper.journal = title_src.get("value", title_src.get("Value", ""))
            elif isinstance(title_src, str):
                paper.journal = title_src

            paper.volume = source_data.get("volume", source_data.get("Volume", ""))
            paper.issue = source_data.get("issue", source_data.get("Issue", ""))

            # 年份
            year = source_data.get("year", source_data.get("Year"))
            if year:
                try:
                    paper.year = int(year)
                except (ValueError, TypeError):
                    paper.year = None

            # 页码
            page_data = source_data.get("page", source_data.get("Page", {}))
            if isinstance(page_data, dict):
                begin = page_data.get("begin", page_data.get("Begin", ""))
                end = page_data.get("end", page_data.get("End", ""))
                if begin and end:
                    paper.page_range = f"{begin}-{end}"

        # 出版信息 (备选字段)
        if not paper.year:
            pub_info = record.get("pub_info", record.get("pubInfo", {}))
            if isinstance(pub_info, dict):
                year = pub_info.get("pubyear", pub_info.get("year"))
                if year:
                    try:
                        paper.year = int(year)
                    except (ValueError, TypeError):
                        pass

        # DOI
        doi_data = record.get("doi", record.get("DOI", {}))
        if isinstance(doi_data, dict):
            paper.doi = doi_data.get("value", doi_data.get("Value", ""))
        elif isinstance(doi_data, str):
            paper.doi = doi_data

        # 关键词
        keywords_data = record.get("keywords", record.get("Keywords", {}))
        if isinstance(keywords_data, dict):
            paper.keywords = keywords_data.get("keywords", keywords_data.get("Keywords", []))
        elif isinstance(keywords_data, list):
            paper.keywords = [str(k) for k in keywords_data]

        # 被引次数
        cited = record.get("cited_by_count", record.get("total_citations", record.get("citedRefCount", 0)))
        paper.cited_by_count = int(cited or 0)

        # 文档类型
        doctype = record.get("document_type", record.get("doctype", ""))
        if isinstance(doctype, str):
            paper.document_type = doctype
        elif isinstance(doctype, list) and doctype:
            paper.document_type = str(doctype[0])

        # URL
        if paper.uid:
            paper.url = f"{WOS_WEB_BASE}/wos/woscc/full-record/{paper.uid}"

        return paper

    # ===== 辅助方法 =====

    def _build_query(
        self,
        query: str,
        year_start: str = "",
        year_end: str = "",
    ) -> str:
        """构建 WoS 查询式.

        如果 query 已包含 WoS 字段前缀（TS=/TI=/AU= 等），直接使用.
        否则自动构建为 TS=(query) 格式.

        Args:
            query: 检索词或已有查询式.
            year_start: 起始年份.
            year_end: 结束年份.

        Returns:
            WoS 查询字符串.
        """
        # 检查是否已包含 WoS 字段前缀
        has_field_prefix = any(
            f in query for f in ["TS=", "TI=", "AU=", "SO=", "PY=", "DO=", "UT=", "AI="]
        )

        if has_field_prefix:
            # 已有查询式，直接使用
            wos_query = query
        else:
            # 纯文本，构建为 TS 查询
            wos_query = WoSQueryBuilder.build_topic_query(
                topic=query,
                year_start=year_start,
                year_end=year_end,
            )

        return wos_query

    @staticmethod
    def build_query_from_topic(
        topic: str,
        region: str = "",
        content: str = "",
        year_start: str = "",
        year_end: str = "",
    ) -> str:
        """基于研究主题构建 WoS 查询式.

        Args:
            topic: 核心主题（英文）.
            region: 研究区域（英文，如 "China"）.
            content: 研究内容（英文，如 "spatial spillover"）.
            year_start: 起始年份.
            year_end: 结束年份.

        Returns:
            WoS 查询字符串.
        """
        # 组合主题词
        parts = [topic]
        if region:
            parts.append(region)
        if content:
            parts.append(content)

        topic_str = " ".join(p.strip() for p in parts if p and p.strip())
        return WoSQueryBuilder.build_topic_query(
            topic=topic_str,
            year_start=year_start,
            year_end=year_end,
        )
