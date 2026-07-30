"""PubScholar OA 资源检索引擎实现.

通过 PubScholar REST API 检索开放获取学术资源。
API 采用 SHA1 签名认证机制（逆向自前端 JS）。

检索端点: POST https://pubscholar.cn/hky/open/resources/api/v1/articles
认证: SHA1([secretKey, timestamp, nonce].sort().join(""))

请求体:
{
    "page": 1,
    "size": 20,
    "order_field": "relevance",
    "order_direction": "desc",
    "query": "财政政策",
    "lang": "zh",
    "strategy": "default"
}

响应:
{
    "code": 200,
    "data": {
        "total": 1234,
        "list": [{ "title": "...", "authors": [...], ... }]
    }
}
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import string
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from scholarpilot.utils.network import configure_no_proxy

logger = logging.getLogger(__name__)

# ===== 常量 =====

PUBSCHOLAR_BASE = "https://pubscholar.cn"
PUBSCHOLAR_SEARCH_API = f"{PUBSCHOLAR_BASE}/hky/open/resources/api/v1/articles"

# API 签名密钥（逆向自前端 JS）
# 注意：此密钥可能随平台更新而失效，需做好异常降级
PUBSCHOLAR_SECRET_KEY = "6m6pingbinwaktg227gngifoocrfbo95"

# 请求间隔（秒）
REQUEST_INTERVAL = 0.5


@dataclass
class PubScholarPaper:
    """PubScholar 论文数据模型."""

    paper_id: str = ""
    title: str = ""
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    publish_date: str = ""
    source: str = ""  # 来源期刊
    doi: str = ""
    keywords: list[str] = field(default_factory=list)
    cite_count: int = 0
    download_url: str = ""
    page_url: str = ""
    language: str = ""  # zh / en
    paper_type: str = ""  # article / thesis
    source_name: str = "pubscholar"

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "year": self.year,
            "publish_date": self.publish_date,
            "source": self.source,
            "doi": self.doi,
            "keywords": self.keywords,
            "cite_count": self.cite_count,
            "download_url": self.download_url,
            "page_url": self.page_url,
            "language": self.language,
            "paper_type": self.paper_type,
            "source_name": self.source_name,
        }


@dataclass
class PubScholarSearchResult:
    """PubScholar 检索结果."""

    query: str = ""
    total_count: int = 0
    papers: list[PubScholarPaper] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
            "error": self.error,
        }


class PubScholarEngine:
    """PubScholar OA 资源检索引擎.

    通过 REST API 检索开放获取学术资源。
    使用 SHA1 签名认证，无需账号登录。

    Usage:
        engine = PubScholarEngine()
        result = await engine.search("财政政策", limit=20)
    """

    def __init__(
        self,
        secret_key: str = PUBSCHOLAR_SECRET_KEY,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """初始化 PubScholar 检索引擎.

        Args:
            secret_key: API 签名密钥（逆向自前端 JS）.
            timeout: 请求超时秒数.
            max_retries: 最大重试次数.
        """
        self.secret_key = secret_key
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None
        self._last_request_time: float = 0.0
        # 403 权限失效后标记为不可用，避免后续请求浪费
        self._permission_revoked: bool = False

    @property
    def is_available(self) -> bool:
        """引擎是否可用。403 权限失效后返回 False."""
        return not self._permission_revoked

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端."""
        if self._client is None or self._client.is_closed:
            configure_no_proxy()
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Referer": PUBSCHOLAR_BASE,
                    "Origin": PUBSCHOLAR_BASE,
                },
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                proxy=None,
                trust_env=False,
            )
        return self._client

    def _generate_signature(self) -> tuple[str, str, str]:
        """生成 API 签名.

        签名算法: SHA1([secretKey, timestamp, nonce].sort().join(""))

        Returns:
            (timestamp, nonce, signature) 三元组.
        """
        timestamp = str(int(time.time() * 1000))
        nonce = "".join(random.choices(string.ascii_letters + string.digits, k=16))

        # 关键：三个值排序后拼接，再 SHA1
        raw = sorted([self.secret_key, timestamp, nonce])
        sign_str = "".join(raw)
        signature = hashlib.sha1(sign_str.encode("utf-8")).hexdigest()

        return timestamp, nonce, signature

    async def _wait_rate_limit(self) -> None:
        """等待请求间隔."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < REQUEST_INTERVAL:
            await asyncio.sleep(REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    async def close(self) -> None:
        """关闭 HTTP 客户端."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def search(
        self,
        query: str,
        limit: int = 20,
        lang: str = "zh",
        sort: str = "relevance",
    ) -> PubScholarSearchResult:
        """执行 PubScholar 检索.

        Args:
            query: 检索关键词（中英文均可）.
            limit: 返回数量上限.
            lang: 检索语言（zh/en）.
            sort: 排序方式（relevance/date/cite）.

        Returns:
            PubScholarSearchResult: 检索结果.
        """
        if not query:
            return PubScholarSearchResult(query=query, error="Empty query")

        # 权限已失效，直接返回空结果
        if self._permission_revoked:
            logger.warning(
                "PubScholar API permission revoked, skipping search. "
                "OA 资源检索不可用，建议使用 arXiv/ChinaXiv 替代。"
            )
            return PubScholarSearchResult(
                query=query, error="API permission revoked (403)"
            )

        await self._wait_rate_limit()
        client = await self._get_client()

        # 生成分页参数
        size = min(limit, 50)
        page = 1

        # 生成签名
        timestamp, nonce, signature = self._generate_signature()

        # 构建请求头
        headers = {
            "nonce": nonce,
            "timestamp": timestamp,
            "signature": signature,
            "x-finger": "scholarpilot_default",
        }

        # 构建请求体
        payload: dict[str, Any] = {
            "page": page,
            "size": size,
            "order_field": sort,
            "order_direction": "desc",
            "user_id": "",
            "lang": lang,
            "query": query,
            "strategy": "default",
        }

        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = await client.post(
                    PUBSCHOLAR_SEARCH_API,
                    json=payload,
                    headers=headers,
                )

                # 429 限流
                if resp.status_code == 429:
                    wait = 3 * (attempt + 1)
                    logger.warning(
                        f"PubScholar 429 rate limited, waiting {wait}s "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(wait)
                        # 重新生成签名
                        timestamp, nonce, signature = self._generate_signature()
                        headers["nonce"] = nonce
                        headers["timestamp"] = timestamp
                        headers["signature"] = signature
                        continue

                resp.raise_for_status()
                data = resp.json()

                return self._parse_response(data, query)

            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code
                logger.error(
                    f"PubScholar API error: {status} - "
                    f"{e.response.text[:200]}"
                )
                # 403 是权限失效，不重试，标记引擎不可用
                if status == 403:
                    self._permission_revoked = True
                    logger.warning(
                        "PubScholar API permission revoked (403). "
                        "Engine disabled. OA 资源检索不可用，"
                        "建议使用 arXiv/ChinaXiv 替代。"
                    )
                    return PubScholarSearchResult(
                        query=query,
                        error="API permission revoked (403). "
                              "第三方应用独立请求时无此操作权限。",
                    )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))

            except Exception as e:
                last_error = e
                logger.error(f"PubScholar search failed: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))

        return PubScholarSearchResult(
            query=query,
            error=f"Search failed after {self.max_retries} retries: {last_error}",
        )

    def _parse_response(
        self,
        data: dict[str, Any],
        query: str,
    ) -> PubScholarSearchResult:
        """解析 API 响应.

        响应结构:
        {
            "code": 200,
            "message": "success",
            "data": {
                "total": 1234,
                "page": 1,
                "size": 20,
                "list": [...]
            }
        }
        """
        result = PubScholarSearchResult(query=query)

        # 检查响应码
        code = data.get("code", 0)
        if code != 200:
            result.error = data.get("message", f"API error: code={code}")
            logger.warning(f"PubScholar API returned code={code}: {result.error}")
            return result

        # 提取数据
        data_body = data.get("data", {})
        if not isinstance(data_body, dict):
            result.error = "Invalid response format: data is not a dict"
            return result

        result.total_count = data_body.get("total", 0)

        papers_list = data_body.get("list", [])
        if not isinstance(papers_list, list):
            result.error = "Invalid response format: list is not an array"
            return result

        for record in papers_list:
            if not isinstance(record, dict):
                continue
            paper = self._parse_record(record)
            if paper.title:
                result.papers.append(paper)

        logger.info(
            f"PubScholar search '{query}': "
            f"{result.total_count} total, {len(result.papers)} returned"
        )
        return result

    def _parse_record(self, record: dict[str, Any]) -> PubScholarPaper:
        """解析单条论文记录."""
        paper = PubScholarPaper()

        # ID
        paper.paper_id = str(record.get("id", record.get("paper_id", "")))

        # 标题
        paper.title = record.get("title", record.get("name", ""))

        # 摘要
        paper.abstract = record.get("abstract", record.get("summary", ""))

        # 作者
        authors = record.get("authors", record.get("author_list", []))
        if isinstance(authors, list):
            paper.authors = [str(a) for a in authors if a]
        elif isinstance(authors, str):
            paper.authors = [a.strip() for a in authors.split(",") if a.strip()]

        # 年份和日期
        paper.publish_date = record.get("publish_date", record.get("pub_date", ""))
        paper.year = record.get("year", "")
        if not paper.year and paper.publish_date:
            # 从日期中提取年份
            if len(paper.publish_date) >= 4:
                paper.year = paper.publish_date[:4]

        # 来源
        paper.source = record.get("source", record.get("journal", record.get("venue", "")))

        # DOI
        paper.doi = record.get("doi", "")

        # 关键词
        keywords = record.get("keywords", record.get("keyword_list", []))
        if isinstance(keywords, list):
            paper.keywords = [str(k) for k in keywords if k]
        elif isinstance(keywords, str):
            paper.keywords = [k.strip() for k in keywords.split(";") if k.strip()]

        # 被引次数
        paper.cite_count = int(record.get("cite_count", record.get("citation_count", 0)) or 0)

        # 下载链接
        paper.download_url = record.get("download_url", record.get("pdf_url", ""))

        # 详情页链接
        paper.page_url = record.get("url", record.get("page_url", ""))
        if not paper.page_url and paper.paper_id:
            paper.page_url = f"{PUBSCHOLAR_BASE}/article/{paper.paper_id}"

        # 语言
        paper.language = record.get("lang", record.get("language", ""))

        # 论文类型
        paper.paper_type = record.get("type", record.get("paper_type", ""))

        return paper
