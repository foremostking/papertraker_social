"""政策/制度搜索引擎 — 从 VPN 政策数据库检索政策法规.

支持的政策数据库（按优先级）：
1. drcnet（国研网）：AI 语义搜索 + 政策法规子库，覆盖最全
2. pkulaw（北大法宝）：法律法规专门库，URL 参数搜索
3. ydyl_drc（一带一路研究平台）：URL 参数搜索
4. ydylcn（一带一路数据库）：URL 参数搜索

每个数据库搜索失败时捕获异常并降级，不影响其他数据库。
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


class PolicySearchEngine:
    """政策/制度搜索引擎.

    Usage::
        engine = PolicySearchEngine(rag)
        results = await engine.search(["地方政府债务", "专项债"], max_results=20)
    """

    # VPN URL 前缀模板
    VPN_BASE = "-s.vpn.lzufe.edu.cn:8118"

    # 数据库配置
    DATABASES = {
        "drcnet": {
            "name": "国务院发展研究中心数据库",
            "vpn_host": "edu-drcnet-com-cn",
            "search_path": "/search/searchAC.aspx?fields={keyword}",
            "ai_search_path": "/reportapi/aiSearch",
        },
        "pkulaw": {
            "name": "北大法宝",
            "vpn_host": "www-pkulaw-com",
            "search_path": "/law/chl?Keywords={keyword}&SearchKeywordType=Title&MatchType=Fuzzy",
        },
        "ydyl_drc": {
            "name": "一带一路研究与决策支撑平台",
            "vpn_host": "ydyl-drcnet-com-cn",
            "search_path": "/search?keyword={keyword}",
        },
    }

    def __init__(self, rag: Any = None) -> None:
        """初始化搜索引擎.

        Args:
            rag: DatabaseRAG 实例（可选，用于查询数据库覆盖信息）。
        """
        self.rag = rag
        self._timeout = 15.0

    def _build_vpn_url(self, db_key: str, keyword: str) -> str | None:
        """构建 VPN 搜索 URL."""
        db = self.DATABASES.get(db_key)
        if not db:
            return None
        host = db["vpn_host"]
        path = db["search_path"].format(keyword=quote(keyword, safe=""))
        return f"http://{host}{self.VPN_BASE}{path}"

    async def search(
        self, keywords: list[str], max_results: int = 20
    ) -> list[dict[str, Any]]:
        """多数据库政策搜索.

        Args:
            keywords: 搜索关键词列表。
            max_results: 最大返回结果数。

        Returns:
            搜索结果列表，每条含 title/source/date/summary/url。
        """
        all_results: list[dict[str, Any]] = []
        seen_titles: set[str] = set()

        for db_key in self.DATABASES:
            if len(all_results) >= max_results:
                break
            for kw in keywords:
                if len(all_results) >= max_results:
                    break
                try:
                    results = await self._search_database(db_key, kw)
                    for r in results:
                        title = r.get("title", "")
                        if title and title not in seen_titles:
                            seen_titles.add(title)
                            all_results.append(r)
                            if len(all_results) >= max_results:
                                break
                except Exception as e:
                    logger.warning(f"政策搜索失败 [{db_key}/{kw}]: {e}")

        logger.info(f"政策搜索完成: {len(keywords)} 个关键词, {len(all_results)} 条结果")
        return all_results

    async def _search_database(
        self, db_key: str, keyword: str
    ) -> list[dict[str, Any]]:
        """搜索单个数据库."""
        url = self._build_vpn_url(db_key, keyword)
        if not url:
            return []

        db_name = self.DATABASES[db_key]["name"]

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                verify=False,
                trust_env=False,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug(f"{db_name} 返回 {resp.status_code}")
                    return []

                # 解析 HTML 结果
                return self._parse_html_results(resp.text, db_key, db_name, keyword)
        except Exception as e:
            logger.debug(f"{db_name} 搜索异常: {e}")
            return []

    def _parse_html_results(
        self, html: str, db_key: str, db_name: str, keyword: str
    ) -> list[dict[str, Any]]:
        """解析 HTML 搜索结果（正则提取，不依赖 BeautifulSoup）."""
        results: list[dict[str, Any]] = []

        # 通用标题提取：匹配 <a ...>标题</a> 中的文本
        title_pattern = re.compile(
            r'<a[^>]*href="([^"]*)"[^>]*>([^<]{4,100})</a>',
            re.IGNORECASE,
        )

        for match in title_pattern.finditer(html):
            url = match.group(1).strip()
            title = match.group(2).strip()

            # 过滤导航链接和无意义文本
            if any(
                skip in title.lower()
                for skip in [
                    "首页", "登录", "注册", "更多", "返回", "下一页", "上一页",
                    "关于我们", "联系方式", "网站地图",
                ]
            ):
                continue
            if len(title) < 4:
                continue

            # 构建完整 URL
            if url.startswith("/"):
                db = self.DATABASES.get(db_key, {})
                url = f"http://{db.get('vpn_host', '')}{self.VPN_BASE}{url}"
            elif not url.startswith("http"):
                continue

            # 尝试提取日期（格式：YYYY-MM-DD 或 YYYY年MM月DD日）
            date_match = re.search(
                r"(20\d{2}[-/年]\d{1,2}[-/月]\d{1,2})", html[match.end():match.end()+500]
            )
            date = date_match.group(1) if date_match else ""

            results.append({
                "title": title,
                "source": db_name,
                "date": date,
                "url": url,
                "summary": "",
                "keyword": keyword,
                "database": db_key,
            })

        return results[:10]  # 每个数据库每个关键词最多返回10条
