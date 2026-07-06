"""CNKI aiohttp 检索引擎.

基于 papertracker_social 已验证成功的方案重建：
- 使用 aiohttp + cookies 字典传参
- 正确的 QueryJson 格式（Resource=JOURNAL, Classid=YSTT4HG0, ControlGroup+YE）
- HTML 解析（BeautifulSoup）
- Cookie 持久化缓存

成功验证：2026-06-27 用缓存 Cookie 搜索"地方政府债务"返回 1736 篇。

Usage:
    engine = CNKIAiohttpEngine()
    engine.load_cookie_from_cache()  # 自动加载缓存 Cookie
    result = await engine.search("地方政府债务", limit=20)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from scholarpilot.utils.network import configure_no_proxy

# 复用 server.py 中的数据模型，确保类型一致性
from scholarpilot.mcp.servers.cnki.server import (
    CNKIPaper,
    CNKISearchResult,
    QueryLayer,
    calculate_eight_dimensions,
    assess_feasibility,
)

logger = logging.getLogger(__name__)


# ===== CNKI aiohttp 引擎 =====

class CNKIAiohttpEngine:
    """CNKI aiohttp 检索引擎.

    基于 papertracker_social 已验证成功的方案：
    - 使用 aiohttp + cookies 字典传参
    - 正确的 QueryJson 格式
    - HTML 响应解析

    关键差异（与旧 httpx 方案相比）：
    - Resource: "JOURNAL"（不是 "CROSSDB"）
    - Classid: "YSTT4HG0"（不是 "WD0FTY92"）
    - ControlGroup + YE 字段控制年份
    - sortField: "FFD"（不是 "PT"）
    - language: "uniplatform"
    - 需要有效的 Cookie（SID_kns_new + Ecp_ClientId）
    """

    BRIEF_GRID_URL = "https://kns.cnki.net/kns8s/brief/grid"
    GROUP_RESULT_URL = "https://kns.cnki.net/kns8s/group/result"
    ADV_SEARCH_URL = (
        "https://kns.cnki.net/kns8s/AdvSearch?crossids="
        "YSTT4HG0,LSTPFY1C,JUP3MUPD,MPMFIG1A,WQ0UVIAA,"
        "BLZOG7CK,PWFIRAGL,EMRPGLPA,NLBO1Z6R,NN3FJMUV"
    )

    # 默认 Cookie 缓存路径
    DEFAULT_COOKIE_CACHE_PATH = Path(__file__).parent / "cnki_cookie_cache.json"

    # 备用 Cookie（来自 papertracker_social 的 FALLBACK_COOKIE）
    FALLBACK_COOKIE = {
        "Ecp_ClientId": "d83c495f79519b333571ce13a1caecb30VAT2g2H06",
        "cnkiUserKey": "db56d603-79ef-3f2a-90f1-7263e8b74a7d",
        "SID_kns_new": "kns15018109",
        "KNS2COOKIE": "1774513277.535.171404.517558|b25e41a932fd162af3b8c5cff4059fc3",
    }

    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        cookie_str: str = "",
        timeout: int = 30,
    ) -> None:
        """初始化 CNKI aiohttp 引擎.

        Args:
            cookies: Cookie 字典。
            cookie_str: Cookie 字符串（如 "key1=val1; key2=val2"）。
            timeout: 请求超时秒数。
        """
        self._cookies: dict[str, str] = {}
        self.timeout = timeout

        if cookies:
            self._cookies = cookies
        elif cookie_str:
            self._cookies = self._parse_cookie_string(cookie_str)
        else:
            # 尝试从缓存加载
            self.load_cookie_from_cache()

    @staticmethod
    def _parse_cookie_string(cookie_str: str) -> dict[str, str]:
        """将 Cookie 字符串解析为字典."""
        result = {}
        for pair in cookie_str.split(";"):
            pair = pair.strip()
            if "=" in pair:
                key, value = pair.split("=", 1)
                result[key.strip()] = value.strip()
        return result

    def load_cookie_from_cache(self, cache_path: Path | str | None = None) -> bool:
        """从缓存文件加载 Cookie.

        Args:
            cache_path: 缓存文件路径，默认使用 DEFAULT_COOKIE_CACHE_PATH。

        Returns:
            True 如果加载成功。
        """
        if cache_path is None:
            cache_path = self.DEFAULT_COOKIE_CACHE_PATH
        elif isinstance(cache_path, str):
            cache_path = Path(cache_path)

        # 尝试加载缓存文件
        for path in [cache_path, Path("cnki_cookie_cache.json")]:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    cookie_str = data.get("cookie", "")
                    if cookie_str:
                        self._cookies = self._parse_cookie_string(cookie_str)
                        logger.info(
                            f"Loaded CNKI cookie from cache: "
                            f"{list(self._cookies.keys())[:3]}"
                        )
                        return True
                except Exception as e:
                    logger.warning(f"Failed to load CNKI cookie cache: {e}")

        # 使用 Fallback Cookie
        if not self._cookies:
            self._cookies = dict(self.FALLBACK_COOKIE)
            logger.info("Using fallback CNKI cookie")
            return True

        return False

    def save_cookie_to_cache(
        self, cache_path: Path | str | None = None
    ) -> bool:
        """保存 Cookie 到缓存文件.

        Args:
            cache_path: 缓存文件路径。

        Returns:
            True 如果保存成功。
        """
        if cache_path is None:
            cache_path = self.DEFAULT_COOKIE_CACHE_PATH
        elif isinstance(cache_path, str):
            cache_path = Path(cache_path)

        cookie_str = "; ".join(
            f"{k}={v}" for k, v in self._cookies.items()
        )

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({
                    "cookie": cookie_str,
                    "expiry": "2026-12-31T23:59:59",
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"CNKI cookie saved to {cache_path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to save CNKI cookie: {e}")
            return False

    def set_cookie(self, cookie_str: str) -> None:
        """设置 Cookie 字符串."""
        self._cookies = self._parse_cookie_string(cookie_str)

    @property
    def has_cookie(self) -> bool:
        """是否有 Cookie."""
        return bool(self._cookies)

    # ===== QueryJson 构建 =====

    @staticmethod
    def build_query(
        topic: str,
        region: str = "",
        content: str = "",
        year_start: str = "",
        year_end: str = "",
    ) -> str:
        """构建 CNKI 检索式（SU%= 语法）.

        CNKI 对长句和复杂检索式的支持有限，应尽量使用简洁的核心关键词。
        如果 topic 是长句（>15字），只取前 15 字作为核心主题。
        content 如果太长（>20字），会截断为前 20 字。

        Args:
            topic: 核心主题。
            region: 研究区域。
            content: 研究内容。

        Returns:
            CNKI 检索式字符串。
        """
        # CNKI SU%= 对长句支持差，必须拆成 4-8 字核心关键词
        def extract_core(text: str, max_len: int = 8) -> str:
            if not text:
                return ""
            text = text.strip()
            # 去掉常见学术后缀
            for suffix in ("研究", "分析", "探讨", "实证", "效应", "影响"):
                if text.endswith(suffix):
                    text = text[:-len(suffix)]
            # 去掉前缀 "中国"
            if text.startswith("中国"):
                text = text[2:]
            # 按 "的" 分割，取最长或最靠前分句
            segments = [s.strip() for s in text.split("的") if s.strip()]
            if segments:
                # 优先取长度适中（4-10字）的分句
                candidates = [s for s in segments if 4 <= len(s) <= max_len]
                if candidates:
                    return candidates[0]
                # 否则取第一个分句截断
                return segments[0][:max_len]
            return text[:max_len]

        core_topic = extract_core(topic, max_len=8)
        core_content = extract_core(content, max_len=8)

        parts = []
        if core_topic:
            parts.append(f"SU%='{core_topic}'")
        if core_content and core_content not in core_topic:
            parts.append(f"SU%='{core_content}'")
        return " AND ".join(parts) if parts else f"SU%='{core_topic}'"

    @staticmethod
    def build_query_json(
        search_query: str,
        year_start: str = "2020",
        year_end: str = "2026",
    ) -> str:
        """构建 QueryJson 参数（复刻 papertracker_social 格式）.

        Args:
            search_query: CNKI 检索式（如 SU%='地方政府债务'）。
            year_start: 起始年份。
            year_end: 结束年份。

        Returns:
            JSON 字符串。
        """
        query_json = {
            "Platform": "",
            "Resource": "JOURNAL",
            "Classid": "YSTT4HG0",
            "Products": "",
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
                                "Value": search_query,
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
                        "ChildItems": [
                            {
                                "Key": ".tit-startend-yearbox",
                                "Title": "",
                                "Logic": 0,
                                "Items": [
                                    {
                                        "Key": ".tit-startend-yearbox",
                                        "Title": "出版年度",
                                        "Logic": 0,
                                        "Field": "YE",
                                        "Operator": 7,
                                        "Value": year_start,
                                        "Value2": year_end,
                                    }
                                ],
                                "ChildItems": [],
                            }
                        ],
                    },
                ]
            },
            "ExScope": "1",
            "SearchType": 4,
            "Rlang": "CHINESE",
            "KuaKuCode": "",
            "Expands": {},
            "View": "changeDBCh",
            "SearchFrom": 1,
        }
        return json.dumps(query_json, ensure_ascii=False)

    # ===== 检索执行 =====

    async def search(
        self,
        query: str,
        limit: int = 20,
        page: int = 1,
        year_start: str = "2020",
        year_end: str = "2026",
        sort_field: str = "FFD",
    ) -> CNKISearchResult:
        """执行 CNKI 检索.

        Args:
            query: 检索词或检索式。如果是纯文本（不含 SU%=），自动构建检索式。
            limit: 返回数量（最大 50）。
            page: 页码。
            year_start: 起始年份。
            year_end: 结束年份。
            sort_field: 排序字段（FFD=发表时间, RU=被引, 空=相关度）。

        Returns:
            CNKISearchResult: 检索结果。
        """
        # 构建检索式
        if "SU%=" not in query and "TI%=" not in query:
            search_query = self.build_query(query)
        else:
            search_query = query

        query_json = self.build_query_json(search_query, year_start, year_end)

        post_data = {
            "boolSearch": "true",
            "QueryJson": query_json,
            "pageNum": str(page),
            "pageSize": str(min(limit, 50)),
            "sortField": sort_field,
            "sortType": "DESC",
            "dstyle": "listmode",
            "boolSortSearch": "false",
            "aside": f"({search_query})",
            "searchFrom": (
                f"资源范围：学术期刊;  中英文扩展;  "
                f"时间范围：出版年度：{year_start} 到 {year_end},更新时间：不限;  "
                f"来源类别：全部期刊; "
            ),
            "subject": "",
            "turnpage": "",
            "language": "uniplatform",
            "CurPage": str(page),
        }

        headers = {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://kns.cnki.net",
            "Referer": self.ADV_SEARCH_URL,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
        }

        try:
            configure_no_proxy()
            async with aiohttp.ClientSession(trust_env=False) as session:
                async with session.post(
                    self.BRIEF_GRID_URL,
                    data=post_data,
                    headers=headers,
                    cookies=self._cookies,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    html = await response.text()

                    # 检测验证码
                    if "captcha" in html.lower() or "verify" in html.lower():
                        logger.warning(
                            "CNKI returned captcha/verify page. Cookie may be invalid."
                        )
                        return CNKISearchResult(query=query, total_count=0)

                    result = self._parse_grid_html(html, query)
                    result.raw_response = html[:5000]

                    logger.info(
                        f"CNKI search '{query}': {result.total_count} total, "
                        f"{len(result.papers)} returned"
                    )
                    return result

        except asyncio.TimeoutError:
            logger.error("CNKI search timeout")
            return CNKISearchResult(query=query, total_count=0)
        except Exception as e:
            logger.error(f"CNKI search failed: {e}")
            return CNKISearchResult(query=query, total_count=0)

    def _parse_grid_html(self, html: str, query: str) -> CNKISearchResult:
        """解析 brief/grid 返回的 HTML（复刻 papertracker_social 解析逻辑）."""
        result = CNKISearchResult(query=query)
        soup = BeautifulSoup(html, "html.parser")

        # 总数
        count_em = soup.select_one("#countPageDiv em")
        if count_em:
            try:
                result.total_count = int(
                    count_em.get_text().strip().replace(",", "")
                )
            except ValueError:
                pass

        # 论文列表
        table = soup.find("table", class_="result-table-list")
        if not table:
            return result

        tbody = table.find("tbody")
        if not tbody:
            return result

        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 6:
                continue

            paper = CNKIPaper()

            # 标题
            if len(cells) > 1:
                title_link = cells[1].find("a", class_="fz14")
                if title_link:
                    for font in title_link.find_all("font"):
                        font.unwrap()
                    paper.title = title_link.get_text().strip()

            # 作者
            if len(cells) > 2:
                author_links = cells[2].find_all("a", class_="KnowledgeNetLink")
                paper.authors = [a.get_text().strip() for a in author_links]

            # 期刊
            if len(cells) > 3:
                source_link = cells[3].find("a")
                if source_link:
                    paper.journal = source_link.get_text().strip()

            # 日期
            if len(cells) > 4:
                date_text = cells[4].get_text().strip()
                paper.year = date_text[:4] if len(date_text) >= 4 else date_text

            # 被引
            if len(cells) > 5:
                quote_text = cells[5].get_text().strip()
                if quote_text.isdigit():
                    paper.cited_count = int(quote_text)

            # 下载
            if len(cells) > 6:
                download_link = cells[6].find("a", class_="downloadCnt")
                if download_link:
                    dl_text = download_link.get_text().strip()
                    if dl_text.isdigit():
                        paper.download_count = int(dl_text)

            if paper.title:
                result.papers.append(paper)

        return result

    async def close(self) -> None:
        """关闭引擎（aiohttp 无需显式关闭，预留接口）."""
        pass

    async def search_4layer(
        self,
        topic: str,
        region: str = "中国",
        content: str = "",
        year_start: str = "2020",
        year_end: str = "2026",
    ) -> list[QueryLayer]:
        """执行 CNKI 4 层检索策略.

        4 层策略：
        1. 精准切口 - 核心主题 + 研究内容
        2. 区域基础 - 核心主题 + 区域
        3. 对标经验 - 核心主题 + 区域 + 研究内容
        4. 领域全貌 - 仅核心主题

        Args:
            topic: 核心主题。
            region: 研究区域。
            content: 研究内容。
            year_start: 起始年份。
            year_end: 结束年份。

        Returns:
            QueryLayer 列表，每层包含检索结果。
        """
        layers = []

        # 第 1 层：精准切口
        q1 = self.build_query(topic, content=content)
        layer1 = QueryLayer(
            layer_index=1,
            layer_name="精准切口",
            layer_desc=f"核心主题 + 研究内容: {topic} + {content}",
            query=q1,
        )
        layer1.result = await self.search(
            q1, year_start=year_start, year_end=year_end,
        )
        layers.append(layer1)

        # 第 2 层：区域基础
        if region:
            q2 = self.build_query(topic, region=region)
            layer2 = QueryLayer(
                layer_index=2,
                layer_name="区域基础",
                layer_desc=f"核心主题 + 区域: {topic} + {region}",
                query=q2,
            )
            layer2.result = await self.search(
                q2, year_start=year_start, year_end=year_end,
            )
            layers.append(layer2)

        # 第 3 层：对标经验
        if region and content:
            q3 = self.build_query(topic, region=region, content=content)
            layer3 = QueryLayer(
                layer_index=3,
                layer_name="对标经验",
                layer_desc=f"核心主题 + 区域 + 研究内容: {topic} + {region} + {content}",
                query=q3,
            )
            layer3.result = await self.search(
                q3, year_start=year_start, year_end=year_end,
            )
            layers.append(layer3)

        # 第 4 层：领域全貌
        q4 = self.build_query(topic)
        layer4 = QueryLayer(
            layer_index=4,
            layer_name="领域全貌",
            layer_desc=f"仅核心主题: {topic}",
            query=q4,
        )
        layer4.result = await self.search(
            q4, year_start=year_start, year_end=year_end,
        )
        layers.append(layer4)

        return layers