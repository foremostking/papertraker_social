"""CNKI Playwright 检索引擎（降级备选，默认不启用）.

使用 Playwright 无头浏览器绕过 CNKI 反爬虫机制。
核心原理：通过 page.evaluate() 在浏览器上下文内执行 fetch 请求，
所有 Cookie 和安全头自动附带，无需手动管理。

> **降级说明（ADR-002）**：本引擎不再作为默认路径导出，仅在 aiohttp
> 通路被 CAPTCHA 频繁拦截时按需 `try: from .playwright_engine import ...`
> 作为验证码兜底插件启用。默认不 import、不实例化。

技术来源：
- papertracker_social/cnki_cssci_fetcher_anti_detection.py 的 page.evaluate() 技术
- papertraker_20260124/cnki_retrieval.py 的 QueryJson 格式

安装依赖：
    pip install playwright
    playwright install chromium

Usage:
    engine = CNKIPlaywrightEngine()
    await engine.init()
    result = await engine.search("地方政府债务", limit=20)
    await engine.close()
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CNKIPlaywrightPaper:
    """CNKI Playwright 检索结果中的单篇论文。"""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: str = ""
    issue: str = ""
    url: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    fund: str = ""
    cited_count: int = 0
    download_count: int = 0
    source: str = "cnki"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "journal": self.journal,
            "year": self.year,
            "issue": self.issue,
            "url": self.url,
            "abstract": self.abstract,
            "keywords": self.keywords,
            "fund": self.fund,
            "cited_count": self.cited_count,
            "download_count": self.download_count,
            "source": self.source,
        }


@dataclass
class CNKIPlaywrightResult:
    """CNKI Playwright 检索结果。"""

    query: str = ""
    total_count: int = 0
    papers: list[CNKIPlaywrightPaper] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
        }


class CNKIPlaywrightEngine:
    """CNKI Playwright 检索引擎.

    使用 Playwright 无头浏览器访问 CNKI，绕过反爬虫机制。
    核心技术：page.evaluate() 在浏览器上下文内执行 fetch 请求。

    优势：
    - 无需手动管理 Cookie（浏览器自动处理）
    - 绕过 JavaScript 反爬虫检测
    - 所有安全头自动附带

    限制：
    - 需要 Playwright 和 Chromium
    - 比 httpx 慢（需要启动浏览器）
    """

    # CNKI URL
    ADV_SEARCH_URL = "https://kns.cnki.net/kns8s/AdvSearch"
    GRID_URL = "https://kns.cnki.net/kns8s/brief/grid"
    SEARCH_HANDLER_URL = "https://kns.cnki.net/kns8s/brief/search"
    DEFAULT_CROSSIDS = "YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV"

    # 反检测 JavaScript
    _ANTI_DETECT_JS = """
    // 隐藏 webdriver 标记
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    
    // 模拟真实浏览器插件
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });
    
    // 模拟真实浏览器语言
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en'],
    });
    """

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._page = None
        self._browser = None
        self._playwright = None
        self._initialized = False

    async def init(self) -> bool:
        """初始化 Playwright 浏览器并访问 CNKI 高级检索页面.

        Returns:
            True 如果初始化成功。
        """
        if self._initialized:
            return True

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "Playwright 未安装。请运行: pip install playwright && playwright install chromium"
            )
            return False

        try:
            self._playwright = await async_playwright().start()

            # 使用完整 Chromium（channel="chromium"），而非 headless shell
            # headless shell 需要单独下载，完整 Chromium 已随 playwright install chromium 安装
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                channel="chromium",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                viewport={"width": 1920, "height": 1080},
            )

            # 注入反检测脚本
            await context.add_init_script(self._ANTI_DETECT_JS)

            self._page = await context.new_page()

            # 访问高级检索页面建立 Session
            await self._page.goto(
                f"{self.ADV_SEARCH_URL}?crossids={self.DEFAULT_CROSSIDS}",
                wait_until="domcontentloaded",
                timeout=30000,
            )

            # 等待页面加载完成
            await asyncio.sleep(2)

            self._initialized = True
            logger.info("CNKI Playwright engine initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize CNKI Playwright engine: {e}")
            await self.close()
            return False

    async def close(self) -> None:
        """关闭浏览器和 Playwright。"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._page = None
        self._initialized = False

    def _build_query_json(
        self,
        query: str,
        source_categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """构建 CNKI QueryJson 格式.

        基于 papertraker_20260124/cnki_retrieval.py 的格式。
        支持来源类别筛选（通过 ControlGroup 的 .extend-tit-checklist 子项）。
        """
        # 如果是纯文本，转换为主题搜索
        if "SU%=" not in query and "TI%=" not in query:
            search_value = f"SU%='{query}'"
        else:
            search_value = query

        # ControlGroup 子项
        control_children: list[dict[str, Any]] = []

        # 来源类别筛选
        if source_categories:
            from scholarpilot.mcp.servers.cnki.aiohttp_engine import (
                SOURCE_CATEGORY_MAPPING,
            )
            source_items = []
            for cat in source_categories:
                mapping = SOURCE_CATEGORY_MAPPING.get(cat)
                if mapping:
                    source_items.append({
                        "Key": 0,
                        "Title": mapping["Title"],
                        "Logic": 1,
                        "Field": mapping["Field"],
                        "Operator": "DEFAULT",
                        "Value": mapping["Value"],
                        "Value2": "",
                    })
            if source_items:
                control_children.append({
                    "Key": ".extend-tit-checklist",
                    "Title": "",
                    "Logic": 0,
                    "Items": source_items,
                    "ChildItems": [],
                })

        return {
            "Platform": "",
            "DBCode": "CFLS",
            "Resource": "CROSSDB",
            "Classid": "WD0FTY92",
            "Products": "CFLS",
            "QNode": {
                "QGroup": [
                    {
                        "Key": "Subject",
                        "Title": "",
                        "Logic": 0,
                        "Items": [
                            {
                                "Key": "Expert",
                                "Title": "",
                                "Logic": 0,
                                "Field": "EXPERT",
                                "Operator": 0,
                                "Value": search_value,
                                "Value2": "",
                            }
                        ],
                        "ChildItems": [],
                    },
                    {
                        "Key": "ControlGroup",
                        "Title": "",
                        "Logic": 0,
                        "Items": [],
                        "ChildItems": control_children,
                    },
                ]
            },
            "ExScope": "1",
            "SearchType": 4,
            "Rlang": "CHINESE",
            "KuaKuCode": "YSTT4HG0,LSTPFY1C,JUP3MUPD,MPMFIG1A,WQ0UVIAA,BLZOG7CK,PWFIRAGL,EMRPGLPA,NLBO1Z6R,NN3FJMUV",
            "Expands": {},
            "View": "changeDBCh",
            "SearchFrom": 1,
        }

    async def search(
        self,
        query: str,
        limit: int = 20,
        page: int = 1,
        sort_field: str = "PT",
        source_categories: list[str] | None = None,
    ) -> CNKIPlaywrightResult:
        """通过浏览器内 fetch 执行 CNKI 检索.

        使用 page.evaluate() 在浏览器上下文内执行 fetch 请求，
        所有 Cookie 和安全头自动附带。

        Args:
            query: 检索词或 CNKI 检索式。
            limit: 返回数量。
            page: 页码。
            sort_field: 排序字段（PT=发表时间, RU=被引, TR=相关度）。
            source_categories: 来源类别列表（如 ["SCI","北大核心","CSSCI"]）。

        Returns:
            CNKIPlaywrightResult: 检索结果。
        """
        if not self._initialized:
            ok = await self.init()
            if not ok:
                return CNKIPlaywrightResult(query=query, total_count=0)

        logger.info(
            "[CNKI Playwright search] 检索参数: query='%s', page=%d, limit=%d, "
            "sort=%s, source_categories=%s",
            query, page, limit, sort_field, source_categories,
        )

        query_json = self._build_query_json(query, source_categories)
        query_json_str = json.dumps(query_json, ensure_ascii=False)
        logger.debug("[CNKI Playwright search] 构建的 QueryJson: %s", query_json_str)

        # 打印 QueryJson 关键结构（DEBUG 级别），便于排查来源类别筛选是否正确
        try:
            cg = next(
                (g for g in query_json["QNode"]["QGroup"]
                 if g.get("Key") == "ControlGroup"),
                None,
            )
            logger.debug(
                "[CNKI Playwright search] QGroup 数量: %d, 各组 Key: %s",
                len(query_json["QNode"]["QGroup"]),
                [g.get("Key") for g in query_json["QNode"]["QGroup"]],
            )
            if cg:
                children = cg.get("ChildItems", [])
                logger.debug(
                    "[CNKI Playwright search] ControlGroup ChildItems 数量: %d",
                    len(children),
                )
                for i, child in enumerate(children):
                    items = child.get("Items", [])
                    if child.get("Key") == ".extend-tit-checklist":
                        logger.info(
                            "[CNKI Playwright search] 来源类别筛选: %d 个类别, "
                            "titles=%s, fields=%s",
                            len(items),
                            [it.get("Title", "") for it in items],
                            [f"{it.get('Field','')}={it.get('Value','')}"
                             for it in items],
                        )
                    else:
                        logger.debug(
                            "[CNKI Playwright search] ControlGroup child[%d] "
                            "Key='%s', items=%d",
                            i, child.get("Key"), len(items),
                        )
        except (KeyError, TypeError) as e:
            logger.warning("[CNKI Playwright search] QueryJson 解析失败: %s", e)

        logger.info(
            "[CNKI Playwright search] 发送请求: gridUrl=%s, pageNum=%s, "
            "pageSize=%s, sortField=%s",
            self.GRID_URL, page, min(limit, 50), sort_field,
        )

        # 检测是否被重定向到验证码页面
        current_url = self._page.url
        if "captcha" in current_url or "verify" in current_url:
            logger.warning(
                f"CNKI 重定向到验证码页面: {current_url}. "
                "需要人工处理验证码或使用已登录的 Cookie。"
            )
            # 尝试等待并重新访问高级检索页
            try:
                await self._page.goto(
                    f"{self.ADV_SEARCH_URL}?crossids={self.DEFAULT_CROSSIDS}",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await asyncio.sleep(3)
            except Exception:
                pass

        # 在浏览器上下文内执行搜索
        # 使用 JSON 序列化传参，避免中文在 JS 模板字符串中引发语法错误
        search_params = {
            "queryJson": query_json_str,
            "aside": query,
            "searchHandlerUrl": self.SEARCH_HANDLER_URL,
            "gridUrl": self.GRID_URL,
            "pageNum": str(page),
            "pageSize": str(min(limit, 50)),
            "sortField": sort_field,
        }

        search_js = """
        async (params) => {
            // 步骤1：提交搜索条件
            const searchFormData = new URLSearchParams({
                'boolSearch': 'true',
                'QueryJson': params.queryJson,
                'pageNum': '1',
                'pageSize': '1',
                'sortField': '',
                'sortType': '',
                'dstyle': 'listmode',
                'boolSortSearch': 'false',
                'aside': params.aside,
                'searchFrom': '资源范围：学术期刊;  中英文扩展;  时间范围：更新时间：不限;  来源类别：全部期刊; ',
                'subject': '',
                'turnpage': '',
                'language': '',
                'uniplatform': 'NZKPT',
                'CurPage': '1'
            });

            const searchResp = await fetch(params.searchHandlerUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: searchFormData.toString(),
                credentials: 'include'
            });

            // 步骤2：获取搜索结果
            const gridFormData = new URLSearchParams({
                'boolSearch': 'true',
                'QueryJson': params.queryJson,
                'pageNum': params.pageNum,
                'pageSize': params.pageSize,
                'sortField': params.sortField,
                'sortType': 'DESC',
                'dstyle': 'listmode',
                'boolSortSearch': 'false',
                'aside': params.aside,
                'searchFrom': '资源范围：学术期刊;  中英文扩展;  时间范围：更新时间：不限;  来源类别：全部期刊; ',
                'subject': '',
                'turnpage': '',
                'language': '',
                'uniplatform': 'NZKPT',
                'CurPage': params.pageNum
            });

            const gridResp = await fetch(params.gridUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: gridFormData.toString(),
                credentials: 'include'
            });

            const text = await gridResp.text();
            return text;
        }
        """

        try:
            result_text = await self._page.evaluate(search_js, search_params)
            logger.info(
                "[CNKI Playwright search] 响应: HTML 长度=%d",
                len(result_text or ""),
            )

            if not result_text:
                logger.warning("CNKI Playwright search returned empty response")
                return CNKIPlaywrightResult(query=query, total_count=0)

            # CNKI grid 接口返回 HTML 格式的结果
            result = self._parse_grid_html(result_text, query)
            logger.info(
                "[CNKI Playwright search] 检索完成: query='%s', "
                "total_count=%d, returned=%d",
                query, result.total_count, len(result.papers),
            )
            return result

        except Exception as e:
            logger.error(f"CNKI Playwright search failed: {e}")
            return CNKIPlaywrightResult(query=query, total_count=0)

    def _parse_grid_html(self, html: str, query: str) -> CNKIPlaywrightResult:
        """解析 CNKI grid 接口返回的 HTML 结果.

        CNKI kns8s grid 接口返回包含结果列表的 HTML 片段，
        每条结果是一个 <tr> 行。
        """
        result = CNKIPlaywrightResult(query=query)

        # 提取总数
        # CNKI 在 HTML 中嵌入 resultcount
        count_match = re.search(r'resultcount["\s:=]+(\d+)', html, re.IGNORECASE)
        if count_match:
            result.total_count = int(count_match.group(1))

        # 解析每条结果（<tr> 行）
        # CNKI grid 返回的 HTML 包含 <tr> 行，每行是一篇论文
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)

        for row_html in rows:
            paper = self._parse_row_html(row_html)
            if paper.title:
                result.papers.append(paper)

        logger.info(
            f"CNKI Playwright search '{query}': "
            f"{result.total_count} total, {len(result.papers)} returned"
        )
        return result

    def _parse_row_html(self, row_html: str) -> CNKIPlaywrightPaper:
        """解析单行 HTML 提取论文信息."""
        paper = CNKIPlaywrightPaper()

        # 标题（在 <a> 标签内）
        title_match = re.search(
            r'<a[^>]*class="fz14"[^>]*>(.*?)</a>', row_html, re.DOTALL
        )
        if not title_match:
            title_match = re.search(
                r'<a[^>]*onclick="[^"]*"[^>]*>(.*?)</a>', row_html, re.DOTALL
            )
        if title_match:
            paper.title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

        # 作者（在 <a class="author" > 或 <td> 内）
        author_matches = re.findall(
            r'<a[^>]*class="author"[^>]*>(.*?)</a>', row_html, re.DOTALL
        )
        if not author_matches:
            # 备用：查找 data-author 属性
            author_matches = re.findall(
                r'data-author="([^"]*)"', row_html
            )
        paper.authors = [
            re.sub(r'<[^>]+>', '', a).strip()
            for a in author_matches
            if re.sub(r'<[^>]+>', '', a).strip()
        ]

        # 来源/期刊
        source_match = re.search(
            r'<a[^>]*target="_blank"[^>]*>(.*?)</a>', row_html, re.DOTALL
        )
        if source_match:
            paper.journal = re.sub(r'<[^>]+>', '', source_match.group(1)).strip()

        # 日期
        date_match = re.search(r'(\d{4})[-/](\d{2})?', row_html)
        if date_match:
            paper.year = date_match.group(1)
            if date_match.group(2):
                paper.issue = date_match.group(2)

        # 下载链接
        download_match = re.search(
            r'href="(/kns8s/defaultresult/index\?[^"]*)"', row_html
        )
        if download_match:
            paper.url = f"https://kns.cnki.net{download_match.group(1)}"

        # 被引量
        cited_match = re.search(r'被引[:：]*(\d+)', row_html)
        if cited_match:
            paper.cited_count = int(cited_match.group(1))

        # 下载量
        dl_match = re.search(r'下载[:：]*(\d+)', row_html)
        if dl_match:
            paper.download_count = int(dl_match.group(1))

        return paper
