"""CNKI MCP Server.

将 CNKI 检索能力封装为 MCP Server，供 Scholar Agent 通过 MCP 协议调用。
提炼了旧代码（papertraker_20260124）的核心检索算法，
包括 4 层检索策略、分组统计等。

Usage:
    # 作为独立 MCP Server 运行
    python -m scholarpilot.mcp.servers.cnki.server

    # 在 Scholar Agent 中通过 MCP Client 连接
    # 见 scholarpilot.mcp.client.MCPClientManager
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


# ===== 数据模型 =====

@dataclass
class CNKIPaper:
    """CNKI 检索结果中的单篇论文。"""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: str = ""
    source: str = ""  # 期刊/学位论文/会议等
    fund: str = ""  # 基金资助
    cited_count: int = 0
    download_count: int = 0
    url: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "journal": self.journal,
            "year": self.year,
            "source": self.source,
            "fund": self.fund,
            "cited_count": self.cited_count,
            "download_count": self.download_count,
            "url": self.url,
            "abstract": self.abstract,
            "keywords": self.keywords,
        }


@dataclass
class CNKISearchResult:
    """CNKI 检索结果。"""

    query: str = ""
    total_count: int = 0
    papers: list[CNKIPaper] = field(default_factory=list)
    group_stats: dict[str, Any] = field(default_factory=dict)  # 分组统计
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
            "group_stats": self.group_stats,
        }


@dataclass
class QueryLayer:
    """单层检索式。"""

    layer: int
    description: str
    query: str  # CNKI 检索语法
    purpose: str


# ===== CNKI 检索引擎 =====

class CNKIEngine:
    """CNKI 检索引擎核心.

    实现了完整的 kns8s 检索流程：
    1. 访问高级检索页面建立 Session（自动获取匿名 Cookie）
    2. 提交检索条件，获取搜索结果列表
    3. 解析 HTML 提取论文信息
    4. 获取分组统计数据

    支持三种检索模式：
    - 自动匿名检索（默认，无需配置，可获取部分结果）
    - Cookie 登录检索（配置 cookie 参数，可获取完整结果）
    - 代理 API 检索（配置 proxy_url 参数，通过第三方代理访问）

    Usage:
        # 匿名检索（开箱即用）
        engine = CNKIEngine()
        result = await engine.search("地方政府债务")

        # 带 Cookie 检索（获取更完整结果）
        engine = CNKIEngine(cookie="your_cnki_cookie")
        result = await engine.search("地方政府债务")
    """

    # CNKI API 端点
    GRID_URL = "https://kns.cnki.net/kns8s/brief/grid"
    GROUP_URL = "https://kns.cnki.net/kns8s/group/singleresult"
    VISUAL_GROUP_URL = "https://kns.cnki.net/kns8s/visual/getgroupdata"
    ADV_SEARCH_URL = "https://kns.cnki.net/kns8s/AdvSearch"
    DEFAULT_SEARCH_URL = "https://kns.cnki.net/kns8s/defaultresult/index"
    SEARCH_HANDLER_URL = "https://kns.cnki.net/kns8s/brief/search"

    # 默认跨库代码（总库）
    DEFAULT_CROSSIDS = "YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV"

    # User-Agent 轮换池（模拟不同浏览器）
    _USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    ]

    def __init__(
        self,
        cookie: str = "",
        proxy_url: str = "",
        timeout: int = 30,
    ) -> None:
        """初始化 CNKI 检索引擎.

        Args:
            cookie: CNKI 登录 Cookie（机构账号或个人账号）。如不提供，
                    引擎会自动尝试匿名检索（可获取部分结果）。
            proxy_url: 代理 API 地址（如 wxtsg.top），可选。
            timeout: 请求超时秒数。
        """
        self.cookie = cookie
        self.proxy_url = proxy_url
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._session_initialized = False  # 是否已建立 Session
        self._search_token: str = ""  # 从搜索页面提取的 token

    def _get_random_ua(self) -> str:
        """随机选择 User-Agent."""
        import random
        return random.choice(self._USER_AGENTS)

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端（带 Cookie Jar 自动管理会话）."""
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": self._get_random_ua(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Origin": "https://kns.cnki.net",
                "Referer": "https://kns.cnki.net/kns8s/AdvSearch",
            }
            if self.cookie:
                headers["Cookie"] = self.cookie

            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                follow_redirects=True,
                # 关键：启用 Cookie Jar，自动保存和发送 Cookie
                # 这样匿名访问时获取的 Session Cookie 会被自动保存
            )
        return self._client

    async def _ensure_session(self) -> bool:
        """确保已建立 CNKI Session.

        CNKI 的 kns8s 接口需要先访问搜索页面获取 Session Cookie，
        然后才能检索。本方法自动完成这一步骤。

        Returns:
            True 如果 Session 建立成功。
        """
        if self._session_initialized:
            return True

        client = await self._get_client()

        try:
            # 步骤1：访问高级检索页面，获取 Session Cookie
            adv_url = f"{self.ADV_SEARCH_URL}?crossids={self.DEFAULT_CROSSIDS}"
            response = await client.get(adv_url, headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
            })
            logger.debug(f"AdvSearch page status: {response.status_code}")

            # 步骤2：尝试从页面提取搜索 token（如有）
            # CNKI 可能在页面中嵌入 token 或搜索参数
            token_match = re.search(
                r"name=['\"](?P<name>cnkiToken|__RequestVerificationToken)['\"]\s+value=['\"](?P<value>[^'\"]+)['\"]",
                response.text,
            )
            if token_match:
                self._search_token = token_match.group("value")
                logger.debug(f"Extracted search token: {self._search_token[:20]}...")

            # 随机延迟，模拟人类操作
            import random
            await asyncio.sleep(random.uniform(0.5, 1.5))

            self._session_initialized = True
            logger.info("CNKI Session established successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to establish CNKI session: {e}")
            return False

    async def close(self) -> None:
        """关闭 HTTP 客户端."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 20,
        sort_field: str = "PT",  # PT=发表时间, RU=被引, TR=相关度
    ) -> CNKISearchResult:
        """执行 CNKI 检索.

        完整的 kns8s 检索流程：
        1. 确保 Session 已建立（自动访问 AdvSearch 页面获取 Cookie）
        2. 提交检索条件到 grid 接口
        3. 解析 HTML 结果
        4. 获取分组统计

        Args:
            query: CNKI 检索式（如 SU%=财政+AND+SU%=债务），或纯文本关键词。
            page: 页码（从1开始）。
            page_size: 每页结果数。
            sort_field: 排序字段。

        Returns:
            CNKISearchResult: 检索结果。
        """
        # 如果是代理模式，走代理 URL
        if self.proxy_url:
            return await self._search_via_proxy(query, page, page_size)

        # 确保 Session 已建立
        session_ok = await self._ensure_session()
        if not session_ok:
            logger.warning("CNKI session not established, trying direct search anyway")

        client = await self._get_client()

        # 构建 kns8s 检索参数
        # CNKI kns8s 使用 form-encoded POST 请求
        search_data = self._build_search_form(
            query=query,
            page=page,
            page_size=page_size,
            sort_field=sort_field,
        )

        try:
            import random

            # 步骤1：先提交搜索条件到 search handler
            search_headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.ADV_SEARCH_URL}?crossids={self.DEFAULT_CROSSIDS}",
                "Accept": "*/*",
            }

            await client.post(
                self.SEARCH_HANDLER_URL,
                data=search_data,
                headers=search_headers,
            )
            await asyncio.sleep(random.uniform(0.3, 0.8))

            # 步骤2：请求结果列表
            grid_params = {
                "page": str(page),
                "pagesize": str(page_size),
                "sorttype": sort_field,
                "sortfield": "",
                "relycount": "0",
                "classtype": "",
                "displaymode": "1",
            }

            response = await client.post(
                self.GRID_URL,
                data={**search_data, **grid_params},
                headers=search_headers,
            )
            response.raise_for_status()

            result = self._parse_search_results(response.text, query)
            result.raw_response = response.text

            # 如果没结果，尝试备用解析方式（可能返回 JSON）
            if result.total_count == 0 and not result.papers:
                result = self._parse_search_results_v2(response, query)

            # 获取分组统计
            if result.total_count > 0 or result.papers:
                group_stats = await self._get_group_stats(search_data)
                result.group_stats = group_stats

            logger.info(
                f"CNKI search '{query}': {result.total_count} total, "
                f"{len(result.papers)} returned"
            )
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"CNKI API error: {e.response.status_code} - {e}")
            return CNKISearchResult(query=query, total_count=0)
        except Exception as e:
            logger.error(f"CNKI search failed: {e}")
            return CNKISearchResult(query=query, total_count=0)

    def _build_search_form(
        self,
        query: str,
        page: int = 1,
        page_size: int = 20,
        sort_field: str = "PT",
    ) -> dict[str, str]:
        """构建 CNKI kns8s 检索表单数据.

        CNKI 的 kns8s 接口使用特定的表单字段格式，
        包括跨库代码、检索条件、排序参数等。

        Args:
            query: 检索式或关键词。
            page: 页码。
            page_size: 每页结果数。
            sort_field: 排序字段。

        Returns:
            表单数据字典。
        """
        # 如果 query 是 CNKI 检索式（如 SU%=xxx），提取关键词
        # 否则直接作为主题搜索词
        if "SU%=" in query:
            # 提取 SU%= 后的关键词
            keywords = re.findall(r"SU%=([^\s]+(?:\s+[^\s]+)*?)(?:\s+AND\s+|$)", query)
            search_term = " ".join(keywords) if keywords else query
        else:
            search_term = query

        # 提取年份限制
        year_match = re.search(r"YE\s*(?:BETWEEN\s+(\d+)\s+AND\s+(\d+)|>=(\d+)|<=(\d+))", query)
        year_start = ""
        year_end = ""
        if year_match:
            year_start = year_match.group(1) or year_match.group(3) or ""
            year_end = year_match.group(2) or year_match.group(4) or ""

        form_data = {
            # 检索条件
            "txt_1_sel": "SU%",  # 主题字段
            "txt_1_value": search_term,
            "txt_1_relation": "#DIFFTEXT",
            "txt_1_special": "=",
            # 跨库选择
            "db_prefix": "CFLS",
            "db_special": "CFLS",
            # 排序和分页
            "page": str(page),
            "pagesize": str(page_size),
            "sorttype": sort_field,
            "sortfield": "",
            "relycount": "0",
            "classtype": "",
            "displaymode": "1",
            # 搜索范围
            "boolsearch": "true",
            "aggregatenew": "true",
            "clusterfilter": "",
            " cladictparam": "",
            "catalogsparam": "",
            "leftsearchflag": "",
        }

        if self._search_token:
            form_data["token"] = self._search_token

        return form_data

    def _parse_search_results_v2(
        self, response: httpx.Response, query: str
    ) -> CNKISearchResult:
        """解析 CNKI 检索结果（备用方式：处理 JSON/混合格式）.

        CNKI kns8s 的 grid 接口可能返回 JSON 或 HTML，
        本方法处理各种可能的响应格式。

        Args:
            response: HTTP 响应对象。
            query: 原始查询词。

        Returns:
            CNKISearchResult: 解析结果。
        """
        result = CNKISearchResult(query=query)
        result.raw_response = response.text

        # 尝试 JSON 解析
        try:
            data = response.json()

            # kns8s grid 可能返回 {"resultTable": "<html>...", "count": 123}
            if isinstance(data, dict):
                # 提取总数
                count = data.get("count", 0)
                if count:
                    result.total_count = int(count)

                # 结果可能在 resultTable 字段中（HTML 片段）
                html_content = data.get("resultTable", "")
                if html_content:
                    parsed = self._parse_search_results(html_content, query)
                    if parsed.papers:
                        result.papers = parsed.papers
                    if parsed.total_count > 0:
                        result.total_count = parsed.total_count

                logger.debug(
                    f"CNKI v2 parse: {result.total_count} total, "
                    f"{len(result.papers)} papers"
                )

        except (json.JSONDecodeError, ValueError):
            # 不是 JSON，回退到 HTML 解析
            result = self._parse_search_results(response.text, query)

        return result

    async def _search_via_proxy(
        self, query: str, page: int, page_size: int
    ) -> CNKISearchResult:
        """通过代理 API 检索 CNKI.

        Args:
            query: 检索式。
            page: 页码。
            page_size: 每页结果数。

        Returns:
            CNKISearchResult: 检索结果。
        """
        client = await self._get_client()

        try:
            params = {
                "query": query,
                "page": str(page),
                "pagesize": str(page_size),
            }
            response = await client.get(self.proxy_url, params=params)
            response.raise_for_status()

            if response.headers.get("content-type", "").startswith("application/json"):
                data = response.json()
                result = CNKISearchResult(query=query)
                result.total_count = data.get("total", 0)
                for item in data.get("papers", []):
                    result.papers.append(CNKIPaper(
                        title=item.get("title", ""),
                        authors=item.get("authors", []),
                        journal=item.get("journal", ""),
                        year=item.get("year", ""),
                        url=item.get("url", ""),
                        cited_count=item.get("cited_count", 0),
                    ))
                return result
            else:
                return self._parse_search_results(response.text, query)

        except Exception as e:
            logger.error(f"CNKI proxy search failed: {e}")
            return CNKISearchResult(query=query, total_count=0)

    async def _get_group_stats(self, search_params: dict) -> dict[str, Any]:
        """获取分组统计数据.

        返回各维度统计：期刊分布、年度分布、学科分布等。
        """
        client = await self._get_client()
        stats: dict[str, Any] = {}

        # 获取分组统计
        group_types = {
            "journal": "PT",  # 期刊分布
            "year": "YE",     # 年度分布
            "subject": "SS",   # 学科分布
            "fund": "FT",      # 基金分布
            "institution": "RT", # 机构分布
        }

        for name, group_code in group_types.items():
            try:
                params = {**search_params, "groupcode": group_code}
                response = await client.post(self.GROUP_URL, data=params)
                if response.status_code == 200:
                    parsed = self._parse_group_result(response.text)
                    if parsed:
                        stats[name] = parsed
            except Exception as e:
                logger.debug(f"Failed to get {name} stats: {e}")

        return stats

    def _parse_search_results(self, html: str, query: str) -> CNKISearchResult:
        """解析 CNKI 检索结果 HTML.

        提取论文标题、作者、期刊、年份等信息。
        """
        result = CNKISearchResult(query=query)

        # 提取总数
        total_match = re.search(r"共找到\s*(\d+)\s*条结果", html)
        if total_match:
            result.total_count = int(total_match.group(1))
        else:
            # 尝试其他格式
            total_match = re.search(r"em class=['\"]total['\"]>\s*(\d+)", html)
            if total_match:
                result.total_count = int(total_match.group(1))

        # 解析论文列表（CNKI 的 HTML 表格结构）
        # 每条结果在 <tr> 标签中
        rows = re.findall(r"<tr[^>]*class=['\"]result-table-list[^'\"]*['\"][^>]*>(.*?)</tr>", html, re.DOTALL)

        for row_html in rows:
            paper = CNKIPaper()

            # 标题
            title_match = re.search(
                r"<a[^>]*class=['\"]fz14['\"][^>]*>(.*?)</a>", row_html, re.DOTALL
            )
            if title_match:
                paper.title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()

            # 作者
            author_match = re.search(
                r"<td[^>]*class=['\"]author['\"][^>]*>(.*?)</td>", row_html, re.DOTALL
            )
            if author_match:
                authors_text = re.sub(r"<[^>]+>", "", author_match.group(1)).strip()
                paper.authors = [a.strip() for a in authors_text.split(";") if a.strip()]

            # 来源（期刊）
            source_match = re.search(
                r"<a[^>]*class=['\"]KnowledgeNet['\"][^>]*>(.*?)</a>", row_html, re.DOTALL
            )
            if source_match:
                paper.journal = re.sub(r"<[^>]+>", "", source_match.group(1)).strip()
                paper.source = "journal"

            # 年份
            date_match = re.search(r"(\d{4})\s*(?:年|\.|-)", row_html)
            if date_match:
                paper.year = date_match.group(1)

            # URL
            url_match = re.search(r"href=['\"]([^'\"]*detail[^'\"]*)['\"]", row_html)
            if url_match:
                url = url_match.group(1)
                if not url.startswith("http"):
                    url = "https://kns.cnki.net" + url
                paper.url = url

            if paper.title:
                result.papers.append(paper)

        return result

    def _parse_group_result(self, html: str) -> list[dict[str, Any]]:
        """解析分组统计结果 HTML."""
        groups = []
        items = re.findall(
            r"<li[^>]*>(.*?)</li>", html, re.DOTALL
        )
        for item in items:
            name_match = re.search(
                r"<a[^>]*>(.*?)</a>", item, re.DOTALL
            )
            count_match = re.search(r"(\d[\d,]*)\s*篇?", item)
            if name_match and count_match:
                name = re.sub(r"<[^>]+>", "", name_match.group(1)).strip()
                count = int(count_match.group(1).replace(",", ""))
                groups.append({"name": name, "count": count})
        return groups

    @staticmethod
    def build_query(
        topic: str,
        region: str = "",
        content: str = "",
        year_start: str = "",
        year_end: str = "",
    ) -> str:
        """构建 CNKI 检索式.

        Args:
            topic: 核心主题（如"地方政府债务"）。
            region: 区域/对象（如"甘肃省"，可选）。
            content: 研究内容（如"风险溢出"，可选）。
            year_start: 起始年份。
            year_end: 结束年份。

        Returns:
            CNKI 检索式字符串。

        Example:
            >>> CNKIEngine.build_query("地方政府债务", "中国", "空间溢出", "2015", "2023")
            'SU%=地方政府债务 AND SU%=中国 AND SU%=空间溢出 AND YE BETWEEN 2015 AND 2023'
        """
        parts: list[str] = []

        if topic:
            parts.append(f"SU%={topic}")
        if region:
            parts.append(f"SU%={region}")
        if content:
            parts.append(f"SU%={content}")

        if year_start and year_end:
            parts.append(f"YE BETWEEN {year_start} AND {year_end}")
        elif year_start:
            parts.append(f"YE>={year_start}")
        elif year_end:
            parts.append(f"YE<={year_end}")

        return " AND ".join(parts) if parts else topic

    @staticmethod
    def generate_4layer_queries(
        topic: str,
        region: str = "中国",
        content: str = "",
        year_start: str = "2015",
        year_end: str = "2024",
    ) -> list[QueryLayer]:
        """生成 4 层检索策略.

        提炼自 papertraker_20260124 的 query_generator.py 核心算法：
        - 层1：主题+区域+内容+年份（精准切口）
        - 层2：主题+区域+年份（区域基础）
        - 层3：主题+对标区域+年份（对标经验）
        - 层4：主题+年份（领域全貌）

        Args:
            topic: 核心主题。
            region: 研究区域。
            content: 研究内容。
            year_start: 起始年份。
            year_end: 结束年份。

        Returns:
            4 层检索式列表。
        """
        layers: list[QueryLayer] = []

        # 层1：精准切口
        q1 = CNKIEngine.build_query(topic, region, content, year_start, year_end)
        layers.append(QueryLayer(
            layer=1,
            description="精准切口（主题+区域+内容+年份）",
            query=q1,
            purpose=f"精准定位 {region} {topic} {content} 的现有研究",
        ))

        # 层2：区域基础
        q2 = CNKIEngine.build_query(topic, region, "", year_start, year_end)
        layers.append(QueryLayer(
            layer=2,
            description="区域基础（主题+区域+年份）",
            query=q2,
            purpose=f"了解 {region} {topic} 的整体研究基础",
        ))

        # 层3：对标经验（使用"中国"作为更宽区域）
        benchmark_region = "中国" if region != "中国" else ""
        q3 = CNKIEngine.build_query(topic, benchmark_region, content, year_start, year_end)
        layers.append(QueryLayer(
            layer=3,
            description="对标经验（主题+全国+内容+年份）",
            query=q3,
            purpose="寻找全国范围内的同类研究作为对标",
        ))

        # 层4：领域全貌
        q4 = CNKIEngine.build_query(topic, "", "", year_start, year_end)
        layers.append(QueryLayer(
            layer=4,
            description="领域全貌（主题+年份）",
            query=q4,
            purpose=f"了解 {topic} 领域的整体发展态势",
        ))

        return layers


# ===== 8 维统计分析 =====

def calculate_eight_dimensions(
    layer_results: list[CNKISearchResult],
) -> dict[str, Any]:
    """计算 8 维统计数据.

    提炼自 papertraker_20260124 的 statistics_collector.py 核心算法。
    基于 4 层检索结果计算 8 个维度的统计数据。

    8 个维度：
    1. 文献总量（各层结果数）
    2. 核心刊占比（CSSCI/北大核心占比）
    3. 年度趋势（近3年占比，判断上升/稳定/下降）
    4. 学科对口度（相关学科占比）
    5. 研究层次（期刊/学位/会议占比）
    6. 关键词分布（高频关键词）
    7. 期刊来源（Top期刊）
    8. 竞争程度（基于总量和趋势的综合评估）

    Args:
        layer_results: 4 层检索结果列表。

    Returns:
        8 维统计数据字典。
    """
    stats: dict[str, Any] = {}

    # 1. 文献总量
    layer_counts = [r.total_count for r in layer_results]
    stats["literature_volume"] = {
        "layer1_precise": layer_counts[0] if len(layer_counts) > 0 else 0,
        "layer2_regional": layer_counts[1] if len(layer_counts) > 1 else 0,
        "layer3_benchmark": layer_counts[2] if len(layer_counts) > 2 else 0,
        "layer4_overall": layer_counts[3] if len(layer_counts) > 3 else 0,
        "total": sum(layer_counts),
    }

    # 2. 核心刊占比（从分组统计获取）
    all_papers: list[CNKIPaper] = []
    for r in layer_results:
        all_papers.extend(r.papers)

    core_journals = []
    for p in all_papers:
        # 简单判断：CSSCI/北大核心/SCI 标记
        if any(kw in p.source.upper() for kw in ["CSSCI", "北大核心", "SCI", "EI", "CSCD"]):
            core_journals.append(p)

    stats["core_journal_ratio"] = {
        "core_count": len(core_journals),
        "total_count": len(all_papers),
        "ratio": len(core_journals) / len(all_papers) if all_papers else 0,
    }

    # 3. 年度趋势
    year_dist: dict[str, int] = {}
    for p in all_papers:
        if p.year:
            year_dist[p.year] = year_dist.get(p.year, 0) + 1

    sorted_years = sorted(year_dist.keys(), reverse=True)
    recent_3_years = sum(year_dist[y] for y in sorted_years[:3] if y)
    total_with_year = sum(year_dist.values())
    recent_ratio = recent_3_years / total_with_year if total_with_year > 0 else 0
    trend = "rising" if recent_ratio > 0.5 else "stable"
    stats["year_trend"] = {
        "distribution": year_dist,
        "recent_3_years_ratio": recent_ratio,
        "trend": trend,
    }

    # 4. 学科对口度
    subject_stats: dict[str, int] = {}
    for r in layer_results:
        subjects = r.group_stats.get("subject", [])
        for s in subjects:
            subject_stats[s["name"]] = subject_stats.get(s["name"], 0) + s["count"]

    stats["subject_relevance"] = {
        "top_subjects": sorted(subject_stats.items(), key=lambda x: x[1], reverse=True)[:10],
    }

    # 5. 期刊来源分布
    journal_dist: dict[str, int] = {}
    for p in all_papers:
        if p.journal:
            journal_dist[p.journal] = journal_dist.get(p.journal, 0) + 1

    stats["journal_distribution"] = {
        "top_journals": sorted(journal_dist.items(), key=lambda x: x[1], reverse=True)[:10],
        "unique_journals": len(journal_dist),
    }

    # 6. 基金资助
    fund_stats: dict[str, int] = {}
    for r in layer_results:
        funds = r.group_stats.get("fund", [])
        for f in funds:
            fund_stats[f["name"]] = fund_stats.get(f["name"], 0) + f["count"]

    stats["fund_support"] = {
        "top_funds": sorted(fund_stats.items(), key=lambda x: x[1], reverse=True)[:10],
        "funded_ratio": len(fund_stats) / len(all_papers) if all_papers else 0,
    }

    # 7. 机构分布
    institution_stats: dict[str, int] = {}
    for r in layer_results:
        institutions = r.group_stats.get("institution", [])
        for inst in institutions:
            institution_stats[inst["name"]] = institution_stats.get(inst["name"], 0) + inst["count"]

    stats["institution_distribution"] = {
        "top_institutions": sorted(institution_stats.items(), key=lambda x: x[1], reverse=True)[:10],
    }

    # 8. 竞争程度评估（基于近 7 年文献总量，匹配经济学引用半衰期 4.2 年）
    total = stats["literature_volume"]["total"]
    trend = stats["year_trend"]["trend"]
    if total > 700:
        competition = "red_ocean"  # 红海：近 7 年 >700 篇
    elif total > 150:
        competition = "moderate"  # 中等
    elif total > 30:
        competition = "blue_ocean"  # 蓝海
    else:
        competition = "cold_spot"  # 冷门

    stats["competition_level"] = {
        "total_literature": total,
        "trend": trend,
        "level": competition,
        "assessment": {
            "red_ocean": "竞争激烈，需差异化切入",
            "moderate": "竞争适中，有发展空间",
            "blue_ocean": "蓝海领域，机会较大",
            "cold_spot": "冷门方向，需谨慎评估",
        }.get(competition, ""),
    }

    return stats


# ===== 可行性判定 =====

def assess_feasibility(
    eight_dim_stats: dict[str, Any],
    research_type: str = "empirical",
) -> dict[str, Any]:
    """基于 8 维统计进行选题可行性判定.

    提炼自 papertraker_20260124 的 feasibility_analyzer.py 核心规则。

    Args:
        eight_dim_stats: 8 维统计数据。
        research_type: 研究类型（empirical/ theoretical/ case_study/ review）。

    Returns:
        可行性判定结果。
    """
    total = eight_dim_stats.get("literature_volume", {}).get("total", 0)
    competition = eight_dim_stats.get("competition_level", {}).get("level", "moderate")
    trend = eight_dim_stats.get("year_trend", {}).get("trend", "stable")
    core_ratio = eight_dim_stats.get("core_journal_ratio", {}).get("ratio", 0)

    # 判定逻辑
    if competition == "blue_ocean" and trend == "rising":
        verdict = "high_quality_gap"
        confidence = 0.85
        reasoning = "蓝海领域且呈上升趋势，存在高质量研究空白，适合切入。"
    elif competition == "blue_ocean":
        verdict = "emerging_field"
        confidence = 0.7
        reasoning = "蓝海领域，研究尚少，但趋势不够明确，需进一步验证。"
    elif competition == "red_ocean" and trend == "rising":
        verdict = "competitive_hot"
        confidence = 0.5
        reasoning = "红海但仍在上升，需找到差异化切口才有机会。"
    elif competition == "red_ocean":
        verdict = "saturated"
        confidence = 0.3
        reasoning = "领域饱和且无增长趋势，发表难度大。"
    elif competition == "cold_spot":
        verdict = "cold_spot"
        confidence = 0.4
        reasoning = "文献极少，可能是冷门方向，需确认是否真有研究价值。"
    else:
        verdict = "moderate"
        confidence = 0.6
        reasoning = "竞争适中，有机会但需找准角度。"

    return {
        "verdict": verdict,
        "confidence": confidence,
        "reasoning": reasoning,
        "competition_level": competition,
        "trend": trend,
        "total_literature": total,
        "core_journal_ratio": core_ratio,
        "recommendation": {
            "high_quality_gap": "强烈推荐！领域空白且趋势向好，抓紧推进。",
            "emerging_field": "推荐，但需更多文献验证方向。",
            "competitive_hot": "需找到差异化切入点，建议聚焦细分领域。",
            "saturated": "不建议直接进入，考虑换角度或区域。",
            "cold_spot": "谨慎推进，需确认文献少的真实原因。",
            "moderate": "可以做，但需精心设计研究方案。",
        }.get(verdict, ""),
    }
