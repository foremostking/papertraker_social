"""NCPSSD - 国家哲学社会科学文献中心检索引擎.

国家哲学社会科学文献中心（ncpssd.org）是由中国社会科学院牵头建设的
免费学术文献资源平台，收录 10,000,000+ 篇中文学术论文。

特点：
- 完全免费，无需登录或 API Key
- 覆盖哲学、经济学、法学、教育学等人文社科全领域
- 支持期刊论文、学位论文检索
- 数据来源权威（CASS 建设）

API 端点（通过分析 articlelist.js 发现）：
- POST /searchHandler/search - 检索论文（返回 JSON）
- POST /searchHandler/solrseachfacet - 分组统计

检索参数格式（Solr 查询语法，字段名基于 articlelist.js 源码分析）：
- IKET=关键词   关键词检索（不能加引号）
- IKTE="关键词"  题名检索（加引号做精确短语匹配）
- IKSE=关键词   精确主题检索（不能加引号）
- IKST=关键词   主题检索（较宽泛，会分词）
- 日期: DATE=[2020-01-01T00:00:00Z TO 2025-12-31T23:59:59Z]

Usage:
    engine = NCPSSDEngine()
    result = await engine.search("地方政府债务", limit=20)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from scholarpilot.utils.network import configure_no_proxy


logger = logging.getLogger(__name__)


# ===== 数据模型 =====

@dataclass
class NCPSSDPaper:
    """NCPSSD 检索结果中的单篇论文。"""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: str = ""
    month: str = ""
    issue: str = ""  # 期号
    doi: str = ""
    keywords: list[str] = field(default_factory=list)
    abstract: str = ""
    fund: str = ""  # 基金项目
    url: str = ""
    paper_type: str = ""  # 文献类型
    page_range: str = ""  # 页码范围
    download_count: int = 0
    read_count: int = 0
    source: str = "ncpssd"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "journal": self.journal,
            "year": self.year,
            "month": self.month,
            "issue": self.issue,
            "doi": self.doi,
            "keywords": self.keywords,
            "abstract": self.abstract,
            "fund": self.fund,
            "url": self.url,
            "paper_type": self.paper_type,
            "page_range": self.page_range,
            "download_count": self.download_count,
            "read_count": self.read_count,
            "source": self.source,
        }


@dataclass
class NCPSSDSearchResult:
    """NCPSSD 检索结果。"""

    query: str = ""
    total_count: int = 0
    papers: list[NCPSSDPaper] = field(default_factory=list)
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
        }


# ===== NCPSSD 检索引擎 =====

class NCPSSDEngine:
    """国家哲学社会科学文献中心检索引擎.

    通过 ncpssd.org 的 /searchHandler/search API 检索中文学术论文。
    该平台完全免费，无需登录或 API Key。

    检索流程：
    1. 访问文章列表页建立 Session（获取 Cookie）
    2. POST 检索条件到 /searchHandler/search
    3. 解析 JSON 结果

    检索语法（Solr 格式，字段名基于 articlelist.js 源码分析）：
    - IKET=关键词   关键词检索（不能加引号，加引号返回0）
    - IKTE="关键词"  题名检索（加引号做精确短语匹配，避免分词）
    - IKSE=关键词   精确主题检索（不能加引号）
    - IKST=关键词   主题检索（较宽泛，会分词）
    - 支持 AND/OR 逻辑组合
    - 日期格式: DATE=[2020-01-01T00:00:00Z TO 2025-12-31T23:59:59Z]

    Usage:
        engine = NCPSSDEngine()
        result = await engine.search("地方政府债务", limit=20)
        for paper in result.papers:
            print(paper.title, paper.authors, paper.journal)
    """

    # NCPSSD API 端点
    BASE_URL = "https://www.ncpssd.org"
    ARTICLELIST_URL = "https://www.ncpssd.org/Literature/articlelist"
    SEARCH_API_URL = "https://www.ncpssd.org/searchHandler/search"
    FACET_API_URL = "https://www.ncpssd.org/searchHandler/solrseachfacet"
    ARTICLE_INFO_URL = "https://www.ncpssd.org/Literature/secure/articleinfo"

    # 默认排序（按时间降序）
    DEFAULT_SORT = "synUpdateType|DESC,date|DESC,ik_subject|DESC,id|DESC"

    # User-Agent 池
    _USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    ]

    def __init__(self, timeout: int = 30) -> None:
        """初始化 NCPSSD 检索引擎.

        Args:
            timeout: 请求超时秒数。
        """
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._session_initialized = False

    def _get_random_ua(self) -> str:
        """随机选择 User-Agent."""
        import random
        return random.choice(self._USER_AGENTS)

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端（带 Cookie Jar 自动管理）."""
        if self._client is None or self._client.is_closed:
            configure_no_proxy()
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": self._get_random_ua(),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Referer": self.BASE_URL,
                },
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                follow_redirects=True,
                proxy=None,
                trust_env=False,
            )
        return self._client

    async def _ensure_session(self) -> bool:
        """建立 NCPSSD Session.

        访问文章列表页获取必要的 Cookie 和 Session 信息。

        Returns:
            True 如果 Session 建立成功。
        """
        if self._session_initialized:
            return True

        client = await self._get_client()

        try:
            # 访问首页建立 Session
            response = await client.get(self.BASE_URL)
            logger.debug(f"NCPSSD homepage status: {response.status_code}")

            # 访问文章列表页（空搜索）建立完整 Session
            await asyncio.sleep(0.3)
            response = await client.get(self.ARTICLELIST_URL, params={
                "sType": "0",
                "search": "",
                "nav": "0",
            })
            logger.debug(f"NCPSSD articlelist page status: {response.status_code}")

            # 检查是否获取到 Session Cookie
            cookies = dict(client.cookies)
            logger.debug(f"NCPSSD cookies: {list(cookies.keys())}")

            import random
            await asyncio.sleep(random.uniform(0.3, 0.8))

            self._session_initialized = True
            logger.info("NCPSSD Session established")
            return True

        except Exception as e:
            logger.error(f"Failed to establish NCPSSD session: {e}")
            return False

    @staticmethod
    def _escape_solr(text: str) -> str:
        """转义 Solr 特殊字符.

        Solr 中以下字符有特殊含义，需要反斜杠转义。
        不转义引号（引号用于短语匹配）。
        """
        # 只转义真正会破坏查询的字符
        # 对于中文关键词，这些字符极少出现，但仍然需要处理
        special_chars = '(){}[]^~*?:\\/+-'
        result = text
        for char in special_chars:
            result = result.replace(char, f'\\{char}')
        return result

    @staticmethod
    def build_query(
        topic: str,
        region: str = "",
        content: str = "",
    ) -> str:
        """构建 NCPSSD Solr 检索式.

        基于 articlelist.js 源码分析和 API 实测确定的最佳查询格式：

        字段名（来源：articlelist.js result_Search() 函数）：
        - IKET: 关键词检索（不加引号，加引号返回0）
        - IKTE: 题名检索（加引号做精确短语匹配，避免分词导致过多结果）
        - IKSE: 精确主题检索（不加引号，加引号返回0）
        - IKST: 主题检索（较宽泛，会分词，不加引号）

        实测结论（probe_ncpssd_v3.py）：
        - IKET=地方债务 → 15 results ✅（精确）
        - IKTE=地方债务 → 118K results（太宽泛，分词匹配）
        - IKTE="地方债务" → 332 results ✅（短语匹配）
        - IKSE=地方债务 → 16 results ✅（精确）
        - OR + 括号在正确字段名下完全可用 ✅

        Args:
            topic: 核心主题（如"地方政府债务"）。
            region: 研究区域（如"中国"），不参与NCPSSD查询（跨字段AND不可靠）。
            content: 研究内容（如"空间溢出"），不参与NCPSSD查询。

        Returns:
            Solr 查询字符串。
        """
        if not topic:
            return ""

        # 转义主搜索词
        escaped_topic = NCPSSDEngine._escape_solr(topic)

        # 构建多字段 OR 查询
        # IKET/IKSE 不加引号（实测加引号返回0）
        # IKTE 加引号（精确短语匹配，避免分词）
        or_parts = [
            f"IKET={escaped_topic}",
            f'IKTE="{escaped_topic}"',
            f"IKSE={escaped_topic}",
        ]
        query = f"({' OR '.join(or_parts)})"

        return query

    @staticmethod
    def build_query_with_date(
        topic: str,
        region: str = "",
        content: str = "",
        year_start: str = "",
        year_end: str = "",
    ) -> str:
        """构建带日期范围的 NCPSSD Solr 检索式.

        Args:
            topic: 核心主题。
            region: 研究区域。
            content: 研究内容。
            year_start: 起始年份（如 "2020"）。
            year_end: 结束年份（如 "2025"）。

        Returns:
            Solr 查询字符串。
        """
        query = NCPSSDEngine.build_query(topic, region, content)

        if not query:
            return ""

        if year_start or year_end:
            # 日期格式来自 articlelist.js: DATE=[yyyy-MM-ddThh:mm:ssZ TO yyyy-MM-ddThh:mm:ssZ]
            start = f"{year_start}-01-01T00:00:00Z" if year_start else "*"
            end = f"{year_end}-12-31T23:59:59Z" if year_end else "*"
            query = f'{query} AND DATE=[{start} TO {end}]'

        return query

    async def search(
        self,
        query: str,
        limit: int = 20,
        page: int = 1,
        year_start: str = "",
        year_end: str = "",
        sort: str = "",
    ) -> NCPSSDSearchResult:
        """执行 NCPSSD 检索.

        Args:
            query: 检索词或 Solr 查询式。如果是纯文本，会自动构建查询式。
            limit: 返回数量。
            page: 页码（从1开始）。
            year_start: 起始年份。
            year_end: 结束年份。
            sort: 排序方式（如不提供则使用默认排序）。

        Returns:
            NCPSSDSearchResult: 检索结果。
        """
        await self._ensure_session()
        client = await self._get_client()

        # 如果是纯文本（不包含 Solr 字段前缀），自动构建查询式
        # 检测已构建的 Solr 查询（包含已知的正确字段名）
        has_solr_field = any(
            f in query for f in ["IKET=", "IKTE=", "IKSE=", "IKST="]
        )
        if not has_solr_field:
            solr_query = self.build_query_with_date(
                topic=query,
                year_start=year_start,
                year_end=year_end,
            )
        else:
            solr_query = query
            # 已有查询式但仍需添加日期过滤（避免遗漏日期条件）
            if (year_start or year_end) and "DATE=" not in solr_query:
                start = f"{year_start}-01-01T00:00:00Z" if year_start else "*"
                end = f"{year_end}-12-31T23:59:59Z" if year_end else "*"
                solr_query = f'{solr_query} AND DATE=[{start} TO {end}]'

        if not sort:
            sort = self.DEFAULT_SORT

        try:
            # 构建表单数据（NCPSSD 使用 form-encoded POST）
            form_data = {
                "search": solr_query,
                "pageNum": str(page),
                "pageSize": str(min(limit, 50)),  # NCPSSD 每页最多50条
                "sort": sort,
                "sType": "0",
                "ajaxKeys": "",
                "customShowCondition": "",
            }

            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "*/*",
                "Referer": f"{self.ARTICLELIST_URL}?sType=0",
            }

            response = await client.post(
                self.SEARCH_API_URL,
                data=form_data,
                headers=headers,
            )
            response.raise_for_status()

            result = self._parse_json_response(response, query)
            result.raw_response = response.text[:5000]

            logger.info(
                f"NCPSSD search '{query}': {result.total_count} total, "
                f"{len(result.papers)} returned"
            )
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"NCPSSD API error: {e.response.status_code} - {e}")
            result = NCPSSDSearchResult(query=query)
            result.raw_response = e.response.text[:500] if e.response.text else ""
            return result
        except Exception as e:
            logger.error(f"NCPSSD search failed: {e}")
            return NCPSSDSearchResult(query=query, total_count=0)

    def _parse_json_response(
        self, response: httpx.Response, query: str
    ) -> NCPSSDSearchResult:
        """解析 NCPSSD API 的 JSON 响应.

        NCPSSD 的 /searchHandler/search 返回 JSON 格式：
        {
            "data": {
                "total": 123,
                "rows": [
                    {
                        "ik_title": "论文标题",
                        "ik_creator": "作者;作者2",
                        "cbw_name": "期刊名",
                        "years": "2024",
                        "month": "01",
                        "num": "第3期",
                        "remark": "摘要",
                        "ik_subject": "关键词1;关键词2",
                        "imburse": "基金项目",
                        "data_id": "数据ID",
                        "type": "中文期刊文章",
                        "encryptedUrl": "加密URL",
                        ...
                    }
                ]
            }
        }
        """
        result = NCPSSDSearchResult(query=query)

        try:
            data = response.json()

            if not isinstance(data, dict):
                logger.warning("NCPSSD response is not a dict")
                return result

            # 提取数据部分
            inner_data = data.get("data", data)

            if not inner_data or not isinstance(inner_data, dict):
                logger.warning("NCPSSD response has no 'data' field")
                return result

            # 提取总数
            result.total_count = int(inner_data.get("total", 0))

            # 解析论文列表
            rows = inner_data.get("rows", inner_data.get("result", []))

            if not rows or not isinstance(rows, list):
                logger.debug(f"NCPSSD: no rows in response, total={result.total_count}")
                return result

            for row in rows:
                paper = self._parse_paper_from_json(row)
                if paper.title:
                    result.papers.append(paper)

            logger.debug(
                f"NCPSSD parsed: {result.total_count} total, "
                f"{len(result.papers)} papers"
            )

        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            logger.error(f"NCPSSD JSON parse error: {e}")
            # 保存原始响应用于调试
            result.raw_response = response.text[:5000]

        return result

    @staticmethod
    def _strip_html(text: str) -> str:
        """去除 Solr 高亮 HTML 标记.

        NCPSSD 返回的标题等字段包含 <font color='red'><b>关键词</b></font> 格式的高亮标记。
        """
        if not text:
            return ""
        # 去除所有 HTML 标签
        clean = re.sub(r'<[^>]+>', '', str(text))
        # 去除 HTML 实体
        clean = clean.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        return clean.strip()

    def _parse_paper_from_json(self, item: dict[str, Any]) -> NCPSSDPaper:
        """从 JSON 数据解析单篇论文.

        NCPSSD 返回的字段名使用 Solr 命名规范：
        - ik_title: 标题
        - ik_creator: 作者（分号分隔）
        - cbw_name: 期刊名
        - years: 年份
        - month: 月份
        - num: 期号
        - remark: 摘要
        - ik_subject: 关键词（分号分隔）
        - imburse: 基金项目
        - data_id: 数据ID
        - type: 文献类型
        - encryptedUrl: 加密的详情页URL
        - beginpage/endpage: 起止页码
        - pagecount: 总页数
        """
        paper = NCPSSDPaper()

        # 标题（去除 Solr 高亮 HTML 标记）
        title = item.get("ik_title", item.get("title", ""))
        paper.title = self._strip_html(title) if title else ""

        # 作者（分号分隔）
        creators = item.get("ik_creator", item.get("creator", ""))
        if isinstance(creators, str):
            # 去除 Solr 高亮标记 [xxx]
            creators = re.sub(r'\[[^\]]*\]', '', creators)
            paper.authors = [
                a.strip() for a in creators.split(";") if a.strip()
            ]
        elif isinstance(creators, list):
            paper.authors = [str(a).strip() for a in creators if a]

        # 期刊名（去除可能的 HTML 标记）
        paper.journal = self._strip_html(
            item.get("cbw_name", item.get("journal", ""))
        )

        # 年份
        year = item.get("years", item.get("year", ""))
        paper.year = str(year).strip() if year else ""

        # 月份
        month = item.get("month", "")
        paper.month = str(month).strip() if month else ""

        # 期号
        num = item.get("num", "")
        if num and num != "暂无":
            paper.issue = str(num).strip()

        # 摘要
        remark = item.get("remark", item.get("abstract", ""))
        if remark and remark != "暂无" and str(remark).strip():
            paper.abstract = str(remark).strip()

        # 关键词（分号分隔，可能带 Solr 高亮标记）
        keywords = item.get("ik_subject", item.get("keywords", ""))
        if isinstance(keywords, str):
            # 去除 Solr 高亮标记
            keywords = re.sub(r'\[[^\]]*\]', '', keywords)
            paper.keywords = [
                k.strip() for k in keywords.split(";") if k.strip()
            ]
        elif isinstance(keywords, list):
            paper.keywords = [str(k).strip() for k in keywords if k]

        # 基金项目
        fund = item.get("imburse", "")
        if fund and fund != "暂无" and str(fund).strip():
            paper.fund = str(fund).strip()

        # 文献类型
        paper.paper_type = str(item.get("type", "")).strip()

        # 页码范围
        begin = item.get("beginpage", "")
        end = item.get("endpage", "")
        if begin and end and begin != "暂无":
            paper.page_range = f"{begin}-{end}"

        # 详情页 URL
        encrypted_url = item.get("encryptedUrl", "")
        if encrypted_url:
            paper.url = f"{self.ARTICLE_INFO_URL}?params={encrypted_url}"

        # 下载和阅读次数（如果有）
        paper.download_count = int(item.get("downCount", 0) or 0)
        paper.read_count = int(item.get("readCount", 0) or 0)

        return paper

    async def get_facet(
        self,
        query: str,
        field: str = "years",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """获取分组统计数据.

        Args:
            query: Solr 查询式。
            field: 分组字段（years=年份, creators=作者, cbw_name=期刊,
                    keyword_s=关键词, type=类型）。
            limit: 返回组数。

        Returns:
            分组统计列表，每项包含 value 和 count。
        """
        await self._ensure_session()
        client = await self._get_client()

        try:
            form_data = {
                "search": query,
                "filed": field,
                "limit": str(limit),
            }

            response = await client.post(
                self.FACET_API_URL,
                data=json.dumps(form_data),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.ARTICLELIST_URL,
                },
            )
            response.raise_for_status()

            data = response.json()
            facets = data.get("data", [])

            return [
                {"value": f.get("value", ""), "count": f.get("count", 0)}
                for f in facets
            ]

        except Exception as e:
            logger.error(f"NCPSSD facet failed: {e}")
            return []

    async def close(self) -> None:
        """关闭 HTTP 客户端."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
