"""ChinaXiv 预印本检索引擎实现.

通过 Web 抓取 chinaxiv.org 检索中文学术预印本。
平台无官方 API，使用 HTML 解析提取数据。

检索端点: GET https://chinaxiv.org/user/search.htm
参数:
    - word: 关键词
    - pageId: 页码（从1开始）
    - sortField: 排序字段（time/click/download）
    - type=filter&filterField=year&value=YYYY: 年份过滤

响应: 服务端渲染 HTML，需用 BeautifulSoup 解析
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote, urljoin

import aiohttp
from bs4 import BeautifulSoup

from scholarpilot.utils.network import configure_no_proxy

logger = logging.getLogger(__name__)

# ===== 常量 =====

CHINAXIV_BASE = "https://chinaxiv.org"
CHINAXIV_SEARCH_URL = f"{CHINAXIV_BASE}/user/search.htm"
CHINAXIV_HOME_URL = f"{CHINAXIV_BASE}/"

# 请求间隔（秒），避免触发反爬
REQUEST_INTERVAL = 3.0

# 浏览器 User-Agent（保持与最新 Chrome 版本一致）
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36"
)


@dataclass
class ChinaXivPaper:
    """ChinaXiv 预印本数据模型."""

    chinaxiv_id: str = ""  # 如 ChinaXiv:202607.00267
    title: str = ""
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    submit_date: str = ""  # 提交日期
    subject: str = ""  # 学科分类
    keywords: list[str] = field(default_factory=list)
    doi: str = ""
    click_count: int = 0  # 点击量
    download_count: int = 0  # 下载量
    comment_count: int = 0  # 评论数
    pdf_url: str = ""  # 全文下载链接
    page_url: str = ""  # 详情页链接
    source: str = "chinaxiv"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chinaxiv_id": self.chinaxiv_id,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "year": self.year,
            "submit_date": self.submit_date,
            "subject": self.subject,
            "keywords": self.keywords,
            "doi": self.doi,
            "click_count": self.click_count,
            "download_count": self.download_count,
            "comment_count": self.comment_count,
            "pdf_url": self.pdf_url,
            "page_url": self.page_url,
            "source": self.source,
        }


@dataclass
class ChinaXivSearchResult:
    """ChinaXiv 检索结果."""

    query: str = ""
    total_count: int = 0
    papers: list[ChinaXivPaper] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
            "error": self.error,
        }


class ChinaXivEngine:
    """ChinaXiv 预印本检索引擎.

    通过 Web 抓取检索中文学术预印本。
    无需认证，但需控制请求频率避免反爬。

    Usage:
        engine = ChinaXivEngine()
        result = await engine.search("财政政策", limit=20)
    """

    def __init__(self, timeout: int = 30) -> None:
        """初始化 ChinaXiv 检索引擎.

        Args:
            timeout: 请求超时秒数.
        """
        self.timeout = timeout
        self._client: Optional[aiohttp.ClientSession] = None
        self._last_request_time: float = 0.0
        self._session_initialized: bool = False

    @property
    def is_available(self) -> bool:
        """引擎是否可用（ChinaXiv 免费开放，始终可用）."""
        return True

    async def _get_client(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 客户端."""
        if self._client is None or self._client.closed:
            configure_no_proxy()
            headers = {
                "User-Agent": BROWSER_UA,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Referer": CHINAXIV_BASE,
            }
            # 使用 cookie jar 持久化会话
            jar = aiohttp.CookieJar(unsafe=True)
            self._client = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                trust_env=False,
                cookie_jar=jar,
            )
        return self._client

    async def _ensure_session(self) -> None:
        """确保 Session 已建立（访问首页获取 Cookie）."""
        if self._session_initialized:
            return

        client = await self._get_client()
        try:
            async with client.get(
                CHINAXIV_HOME_URL, allow_redirects=True
            ) as resp:
                logger.debug(
                    f"ChinaXiv session init: HTTP {resp.status}"
                )
            self._session_initialized = True
        except Exception as e:
            logger.warning(f"ChinaXiv session init failed (non-fatal): {e}")
            self._session_initialized = True

    async def _wait_rate_limit(self) -> None:
        """等待请求间隔，避免触发反爬."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < REQUEST_INTERVAL:
            wait = REQUEST_INTERVAL - elapsed
            logger.debug(f"Rate limit: waiting {wait:.1f}s")
            await asyncio.sleep(wait)
        self._last_request_time = asyncio.get_event_loop().time()

    async def close(self) -> None:
        """关闭 HTTP 客户端."""
        if self._client and not self._client.closed:
            await self._client.close()
            self._client = None

    async def search(
        self,
        query: str,
        limit: int = 20,
        year_start: str = "",
        year_end: str = "",
        subject: str = "",
    ) -> ChinaXivSearchResult:
        """执行 ChinaXiv 检索.

        Args:
            query: 检索关键词（中文）.
            limit: 返回数量上限.
            year_start: 起始年份.
            year_end: 结束年份.
            subject: 学科分类过滤.

        Returns:
            ChinaXivSearchResult: 检索结果.
        """
        if not query:
            return ChinaXivSearchResult(query=query, error="Empty query")

        result = ChinaXivSearchResult(query=query)

        # 会话预热：先访问首页获取 Cookie，避免 403
        await self._ensure_session()

        client = await self._get_client()

        # 计算需要检索的页数（每页10条）
        pages_needed = (limit + 9) // 10
        collected = 0

        for page_num in range(1, pages_needed + 1):
            if collected >= limit:
                break

            await self._wait_rate_limit()

            # 构建查询参数
            params: dict[str, str] = {
                "word": query,
                "pageId": str(page_num),
                "sortField": "time",
            }

            # 年份过滤
            if year_start:
                params["type"] = "filter"
                params["filterField"] = "year"
                params["value"] = year_start

            try:
                async with client.get(
                    CHINAXIV_SEARCH_URL,
                    params=params,
                    allow_redirects=True,
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"ChinaXiv search page {page_num}: HTTP {resp.status}"
                        )
                        if resp.status == 403:
                            result.error = "Anti-scraping triggered, try later"
                            break
                        continue

                    html = await resp.text()

                    # 检查反爬
                    if "访问异常" in html or "暂时受到限制" in html:
                        result.error = "Anti-scraping triggered, try later"
                        logger.warning("ChinaXiv anti-scraping detected")
                        break

                    # 解析 HTML
                    papers, total = self._parse_search_page(html)

                    if page_num == 1:
                        result.total_count = total

                    for paper in papers:
                        if collected >= limit:
                            break
                        result.papers.append(paper)
                        collected += 1

                    # 如果当前页没有结果，停止翻页
                    if not papers:
                        break

            except asyncio.TimeoutError:
                logger.warning(f"ChinaXiv search page {page_num}: timeout")
                if page_num == 1:
                    result.error = "Request timeout"
                break
            except Exception as e:
                logger.error(f"ChinaXiv search page {page_num} failed: {e}")
                if page_num == 1:
                    result.error = str(e)
                break

        logger.info(
            f"ChinaXiv search '{query}': "
            f"{result.total_count} total, {len(result.papers)} returned"
        )
        return result

    def _parse_search_page(self, html: str) -> tuple[list[ChinaXivPaper], int]:
        """解析检索结果 HTML 页面.

        Args:
            html: HTML 页面内容.

        Returns:
            (论文列表, 总结果数).
        """
        papers: list[ChinaXivPaper] = []
        total_count = 0

        soup = BeautifulSoup(html, "html.parser")

        # 提取总数
        # 页面通常有 "共找到 XXX 条结果" 或类似文本
        total_text = soup.find(string=re.compile(r"共\s*\d+\s*条"))
        if total_text:
            match = re.search(r"(\d+)", total_text)
            if match:
                total_count = int(match.group(1))

        # 解析论文列表项
        # ChinaXiv 搜索结果的列表项通常在特定的容器中
        # 尝试多种选择器以适应页面结构变化
        items = self._find_paper_items(soup)

        for item in items:
            paper = self._parse_paper_item(item)
            if paper.title:
                papers.append(paper)

        # 如果没有找到总数，用当前页结果数估算
        if total_count == 0 and papers:
            total_count = len(papers)

        return papers, total_count

    def _find_paper_items(self, soup: BeautifulSoup) -> list:
        """查找论文列表项元素.

        尝试多种 CSS 选择器以适应 ChinaXiv 页面结构.
        """
        # 尝试常见的选择器
        selectors = [
            # 常见的列表项选择器
            "div.list-item",
            "div.search-result-item",
            "div.paper-item",
            "li.list-group-item",
            "div.result-item",
            # ChinaXiv 特定选择器
            "div.row.facility-list > div",
            "div.article-list > div",
            # 通用回退
            "div[class*='item']",
        ]

        for selector in selectors:
            items = soup.select(selector)
            if items and len(items) > 0:
                # 验证是否包含论文标题
                for item in items:
                    if item.find("a", href=True) or item.find("h3") or item.find("h4"):
                        return items

        # 最后回退：查找所有包含链接的 div
        all_divs = soup.find_all("div")
        result_divs = []
        for div in all_divs:
            # 查找包含 ChinaXiv ID 或标题链接的 div
            link = div.find("a", href=re.compile(r"/abs/|/detail/|/paper"))
            if link and link.get_text(strip=True):
                result_divs.append(div)

        return result_divs

    def _parse_paper_item(self, item) -> ChinaXivPaper:
        """解析单个论文列表项.

        Args:
            item: BeautifulSoup 元素.

        Returns:
            ChinaXivPaper: 解析出的论文数据.
        """
        paper = ChinaXivPaper()

        # 提取标题和链接
        title_link = item.find("a", href=True)
        if title_link:
            paper.title = title_link.get_text(strip=True)
            href = title_link.get("href", "")
            if href:
                paper.page_url = urljoin(CHINAXIV_BASE, href)

                # 从链接中提取 ChinaXiv ID
                id_match = re.search(r"(ChinaXiv:\d{4}\.\d+)", href)
                if not id_match:
                    id_match = re.search(r"(\d{4}\.\d+)", href)
                if id_match:
                    paper.chinaxiv_id = (
                        f"ChinaXiv:{id_match.group(1)}"
                        if not id_match.group(0).startswith("ChinaXiv")
                        else id_match.group(0)
                    )

        # 如果没有找到标题链接，尝试 h3/h4
        if not paper.title:
            heading = item.find(["h3", "h4", "h5"])
            if heading:
                paper.title = heading.get_text(strip=True)

        # 提取作者
        # 通常在特定 class 或文本模式中
        author_text = ""
        for span in item.find_all("span"):
            text = span.get_text(strip=True)
            if "作者" in text or "作 者" in text:
                author_text = text.replace("作者", "").replace("作 者", "").strip("：: ")
                break
            # 检查是否是作者列表（通常以逗号分隔的中文名）
            if re.match(r"^[\u4e00-\u9fa5]{2,4}[,，\s]", text):
                author_text = text
                break

        if author_text:
            # 分割作者名
            paper.authors = [
                a.strip() for a in re.split(r"[,，;；\s]+", author_text) if a.strip()
            ]

        # 提取学科分类
        subject_text = ""
        for span in item.find_all(["span", "div", "p"]):
            text = span.get_text(strip=True)
            if "学科" in text or "分类" in text:
                subject_text = text.replace("学科", "").replace("分类", "").strip("：: ")
                paper.subject = subject_text
                break

        # 提取日期
        for span in item.find_all(["span", "time", "div"]):
            text = span.get_text(strip=True)
            # 匹配日期格式：2024-01-15 或 2024.01 或 2024年
            date_match = re.search(r"(\d{4}[-./年]\d{1,2}[-./月]?\d{0,2}日?)", text)
            if date_match:
                paper.submit_date = date_match.group(1)
                paper.year = date_match.group(1)[:4]
                break

        # 提取点击量、下载量
        stats_text = item.get_text()
        click_match = re.search(r"点击[：:]\s*(\d+)", stats_text)
        if click_match:
            paper.click_count = int(click_match.group(1))

        download_match = re.search(r"下载[：:]\s*(\d+)", stats_text)
        if download_match:
            paper.download_count = int(download_match.group(1))

        comment_match = re.search(r"评论[：:]\s*(\d+)", stats_text)
        if comment_match:
            paper.comment_count = int(comment_match.group(1))

        # 提取 PDF 下载链接
        pdf_link = item.find("a", href=re.compile(r"\.pdf|download", re.I))
        if pdf_link:
            paper.pdf_url = urljoin(CHINAXIV_BASE, pdf_link.get("href", ""))

        return paper

    async def get_paper_detail(self, page_url: str) -> ChinaXivPaper:
        """获取论文详情页的完整信息（摘要、关键词等）.

        Args:
            page_url: 论文详情页 URL.

        Returns:
            ChinaXivPaper: 包含完整信息的论文数据.
        """
        await self._wait_rate_limit()
        client = await self._get_client()

        paper = ChinaXivPaper(page_url=page_url)

        try:
            async with client.get(page_url, allow_redirects=True) as resp:
                if resp.status != 200:
                    paper.title = f"Failed to fetch (HTTP {resp.status})"
                    return paper

                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # 标题
                title_tag = soup.find(["h1", "h2", "h3"], class_=re.compile(r"title", re.I))
                if title_tag:
                    paper.title = title_tag.get_text(strip=True)

                # 摘要
                abstract_tag = soup.find(
                    ["div", "p", "span"],
                    class_=re.compile(r"abstract", re.I),
                )
                if abstract_tag:
                    paper.abstract = abstract_tag.get_text(strip=True)

                # 关键词
                kw_tag = soup.find(
                    ["div", "p", "span"],
                    class_=re.compile(r"keyword", re.I),
                )
                if kw_tag:
                    kw_text = kw_tag.get_text(strip=True)
                    kw_text = re.sub(r"关键词[：:]", "", kw_text)
                    paper.keywords = [
                        k.strip() for k in re.split(r"[;；,，]", kw_text) if k.strip()
                    ]

                # DOI
                doi_tag = soup.find(string=re.compile(r"10\.\d{4,}/"))
                if doi_tag:
                    doi_match = re.search(r"(10\.\d{4,}/\S+)", doi_tag)
                    if doi_match:
                        paper.doi = doi_match.group(1).strip()

                # PDF 链接
                pdf_link = soup.find("a", href=re.compile(r"\.pdf|download", re.I))
                if pdf_link:
                    paper.pdf_url = urljoin(CHINAXIV_BASE, pdf_link.get("href", ""))

        except Exception as e:
            logger.error(f"ChinaXiv detail fetch failed: {e}")
            paper.title = f"Error: {e}"

        return paper
