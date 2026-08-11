"""政策/制度搜索引擎 — 多维度政策检索.

支持的政策数据库：
1. cei（中国经济信息网）：直连访问，支持关键词+栏目+排序+时间范围组合筛选
   - 政策实践维度：宏观频道、行业频道、区域频道（政策落地、实施案例、新闻动态）
   - 政策分析维度：宏观频道（政策解读、专家评论、形势分析）
2. drcnet（国研网）：VPN访问，AI语义搜索 + 政策法规子库
   - 政策分析维度：智库报告、政策评估
3. pkulaw（北大法宝）：VPN访问，法律法规专门库
   - 政策文本维度：法律条文、规范性文件

搜索结果按维度标注：
- policy_text: 政策文本（法规、通知、意见等原文）
- policy_practice: 政策实践（实施案例、试点报道、新闻动态）
- policy_analysis: 政策分析（解读、评估、学术研究）

每个数据库搜索失败时捕获异常并降级，不影响其他数据库。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
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

    # CEI 直连地址（不需要VPN）
    CEI_BASE = "https://www.cei.cn"
    CEI_SEARCH_URL = f"{CEI_BASE}/d/search/highSearch.action"
    CEI_SEARCH_PAGE = f"{CEI_BASE}/d/search/toSearch.action"

    # CEI 栏目ID映射
    CEI_COLUMNS = {
        "all": ("", "所有频道"),
        "macro": ("4028c7ca-37115425-0137-11559cf9-0003", "宏观频道"),
        "finance": ("4028c7ca-37115425-0137-11559d28-0005", "金融频道"),
        "international": ("4028c7ca-37115425-0137-11559dd3-000b", "国际频道"),
        "regional": ("4028c7ca-37115425-0137-11559db4-0009", "区域频道"),
        "industry": ("4028c7ca-37115425-0137-11559d66-0007", "行业频道"),
    }

    # CEI 排序方式
    CEI_SORT = {
        "relevance": "dft",       # 相关度
        "date": "createtime",     # 日期
    }

    # VPN 数据库配置（需要EasyConnect VPN）
    VPN_DATABASES = {
        "drcnet": {
            "name": "国务院发展研究中心数据库",
            "vpn_host": "edu-drcnet-com-cn",
            "search_path": "/search/searchAC.aspx?fields={keyword}",
            "ai_search_path": "/reportapi/aiSearch",
            "dimension": "policy_analysis",
        },
        "pkulaw": {
            "name": "北大法宝",
            "vpn_host": "www-pkulaw-com",
            "search_path": "/law/chl?Keywords={keyword}&SearchKeywordType=Title&MatchType=Fuzzy",
            "dimension": "policy_text",
        },
        "ydyl_drc": {
            "name": "一带一路研究与决策支撑平台",
            "vpn_host": "ydyl-drcnet-com-cn",
            "search_path": "/search?keyword={keyword}",
            "dimension": "policy_analysis",
        },
    }

    # 政策文本关键词（用于自动标注维度）
    POLICY_TEXT_KEYWORDS = [
        "法", "条例", "规定", "办法", "通知", "意见", "决定", "方案",
        "规划", "纲要", "准则", "规则", "细则", "公告", "命令", "批复",
        "政府工作报告", "预算报告", "决算报告",
    ]

    # 政策实践关键词
    POLICY_PRACTICE_KEYWORDS = [
        "实施", "试点", "案例", "实践", "落地", "推进", "出台",
        "启动", "开展", "探索", "改革", "创新", "成效", "经验",
        "地方", "区域", "省份", "城市",
    ]

    # 政策分析关键词
    POLICY_ANALYSIS_KEYWORDS = [
        "分析", "研究", "评估", "解读", "评论", "思考", "探讨",
        "路径", "方向", "趋势", "展望", "比较", "借鉴", "启示",
        "挑战", "问题", "对策", "建议",
    ]

    HTTP_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    def __init__(self, rag: Any = None, extra_databases: dict[str, dict] | None = None) -> None:
        """初始化搜索引擎.

        Args:
            rag: DatabaseRAG 实例（可选，用于查询数据库覆盖信息）。
            extra_databases: 额外VPN数据库配置字典，格式与 VPN_DATABASES 一致。
                key 为数据库标识，value 含 name/vpn_host/search_path/dimension。
                由 DatabaseSelector 推荐生成，会与内置 VPN_DATABASES 合并。
        """
        self.rag = rag
        self._timeout = 20.0
        self._cei_session_cookie: str | None = None
        self._extra_databases = extra_databases or {}
        self._vpn_cookie: str | None = None  # VPN TWFID Cookie 缓存

    async def _get_vpn_cookie(self) -> str:
        """获取 VPN TWFID Cookie（带缓存）.

        首次调用时从 VPNSessionManager 获取，后续复用缓存。
        Cookie 过期后自动刷新。

        Returns:
            Cookie 字符串，无 VPN 时返回空字符串.
        """
        if self._vpn_cookie is None:
            try:
                from scholarpilot.utils.vpn import get_vpn_session_manager
                mgr = get_vpn_session_manager()
                self._vpn_cookie = await mgr.get_cookie_header()
            except Exception as e:
                logger.debug(f"获取 VPN Cookie 失败: {e}")
                self._vpn_cookie = ""
        return self._vpn_cookie or ""

    def _get_all_vpn_databases(self) -> dict[str, dict]:
        """获取合并后的全部VPN数据库配置."""
        return {**self.VPN_DATABASES, **self._extra_databases}

    # ═══════════════════════════════════════════════════════════════════
    #  公开接口
    # ═══════════════════════════════════════════════════════════════════

    async def search(
        self, keywords: list[str], max_results: int = 20
    ) -> list[dict[str, Any]]:
        """多维度政策搜索.

        搜索策略：
        1. CEI直连搜索（所有频道 + 宏观频道），按相关度和日期两种排序
        2. VPN数据库搜索（drcnet/pkulaw），作为补充

        Args:
            keywords: 搜索关键词列表。
            max_results: 最大返回结果数。

        Returns:
            搜索结果列表，每条含 title/source/date/summary/url/dimension/database。
            dimension 取值: policy_text | policy_practice | policy_analysis
        """
        all_results: list[dict[str, Any]] = []
        seen_titles: set[str] = set()

        # ── 1. CEI 直连搜索（优先，最可靠）──────────────────────────
        # 计算近5年日期范围
        now = datetime.now()
        b_date = (now - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
        e_date = now.strftime("%Y-%m-%d")

        for kw in keywords:
            if len(all_results) >= max_results:
                break

            # 1a. 所有频道 + 相关度排序（覆盖面最广）
            try:
                results = await self._search_cei(
                    keyword=kw,
                    column_key="all",
                    sort="relevance",
                    b_date=b_date,
                    e_date=e_date,
                )
                for r in results:
                    title = r.get("title", "")
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_results.append(r)
                        if len(all_results) >= max_results:
                            break
            except Exception as e:
                logger.warning(f"CEI搜索失败[all/relevance/{kw}]: {e}")

            # 1b. 宏观频道 + 日期排序（获取最新政策动态）
            if len(all_results) < max_results:
                try:
                    results = await self._search_cei(
                        keyword=kw,
                        column_key="macro",
                        sort="date",
                        b_date=b_date,
                        e_date=e_date,
                    )
                    for r in results:
                        title = r.get("title", "")
                        if title and title not in seen_titles:
                            seen_titles.add(title)
                            all_results.append(r)
                            if len(all_results) >= max_results:
                                break
                except Exception as e:
                    logger.warning(f"CEI搜索失败[macro/date/{kw}]: {e}")

        # ── 2. VPN数据库搜索（补充，含内置+推荐）────────────────
        all_vpn = self._get_all_vpn_databases()
        if len(all_results) < max_results:
            for db_key, db_config in all_vpn.items():
                if len(all_results) >= max_results:
                    break
                for kw in keywords:
                    if len(all_results) >= max_results:
                        break
                    try:
                        results = await self._search_vpn_database(db_key, db_config, kw)
                        for r in results:
                            title = r.get("title", "")
                            if title and title not in seen_titles:
                                seen_titles.add(title)
                                all_results.append(r)
                                if len(all_results) >= max_results:
                                    break
                    except Exception as e:
                        vpn_name = db_config.get("name", db_key)
                        logger.debug(f"VPN数据库搜索失败 [{vpn_name}/{kw}]: {e}")

        # ── 3. 为所有结果标注维度 ──────────────────────────────────
        for r in all_results:
            if "dimension" not in r or not r["dimension"]:
                r["dimension"] = self._tag_dimension(r)

        logger.info(
            f"政策搜索完成: {len(keywords)} 个关键词, {len(all_results)} 条结果"
        )
        return all_results

    # ═══════════════════════════════════════════════════════════════════
    #  CEI 直连搜索
    # ═══════════════════════════════════════════════════════════════════

    async def _search_cei(
        self,
        keyword: str,
        column_key: str = "all",
        sort: str = "relevance",
        b_date: str = "",
        e_date: str = "",
        max_pages: int = 2,
    ) -> list[dict[str, Any]]:
        """搜索CEI数据库（直连www.cei.cn，不需要VPN）.

        Args:
            keyword: 搜索关键词。
            column_key: 栏目key（all/macro/finance/international/regional/industry）。
            sort: 排序方式（relevance/date）。
            b_date: 起始日期（YYYY-MM-DD，空字符串表示不限）。
            e_date: 结束日期（YYYY-MM-DD，空字符串表示不限）。
            max_pages: 最大翻页数（每页10条）。

        Returns:
            搜索结果列表。
        """
        column_id, column_name = self.CEI_COLUMNS.get(
            column_key, self.CEI_COLUMNS["all"]
        )
        sort_value = self.CEI_SORT.get(sort, self.CEI_SORT["relevance"])

        all_results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=self._timeout,
            verify=False,
            trust_env=False,
            follow_redirects=True,
        ) as client:
            # 先访问搜索页获取session cookie
            try:
                await client.get(self.CEI_SEARCH_PAGE, headers=self.HTTP_HEADERS)
            except Exception:
                pass  # cookie获取失败也能搜索

            # 搜索多页
            for page_idx in range(max_pages):
                cursor = page_idx * 10
                params = {
                    "keywords": keyword,
                    "columnId": column_id,
                    "columntype": "",
                    "sort": sort_value,
                    "coulnmName": column_name,
                }
                if b_date:
                    params["b_date"] = b_date
                if e_date:
                    params["e_date"] = e_date
                if cursor > 0:
                    params["cursor"] = str(cursor)

                try:
                    resp = await client.post(
                        self.CEI_SEARCH_URL,
                        data=params,
                        headers={
                            **self.HTTP_HEADERS,
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Referer": self.CEI_SEARCH_PAGE,
                        },
                    )
                    if resp.status_code != 200:
                        logger.debug(f"CEI返回 {resp.status_code}")
                        break

                    results = self._parse_cei_results(
                        resp.text, keyword, column_name
                    )
                    if not results:
                        break  # 没有更多结果

                    all_results.extend(results)

                    # 检查是否还有更多页
                    page_match = re.search(
                        r'第(\d+)页/共(\d+)页', resp.text
                    )
                    if page_match:
                        current_page = int(page_match.group(1))
                        total_pages = int(page_match.group(2))
                        if current_page >= total_pages:
                            break

                except Exception as e:
                    logger.debug(f"CEI搜索异常[page={page_idx}]: {e}")
                    break

        return all_results

    def _parse_cei_results(
        self, html: str, keyword: str, column_name: str
    ) -> list[dict[str, Any]]:
        """解析CEI搜索结果HTML.

        CEI结果结构:
        <div class="search_list"><ul>
          <li>
            <strong>1.<a href="URL">标题</a><span>日期</span></strong>
            <p><a href="URL">[摘要] 摘要内容</a>
            <p class="search_list_time"><em><a href="URL">全文</a></em>
          </li>
        </ul></div>
        """
        results: list[dict[str, Any]] = []

        # 提取 search_list 区域
        list_match = re.search(
            r'<div class="search_list">\s*<ul>(.*?)</ul>',
            html, re.DOTALL
        )
        if not list_match:
            return []

        list_html = list_match.group(1)

        # 提取每个 <li> 条目
        items = re.findall(r'<li[^>]*>(.*?)</li>', list_html, re.DOTALL)
        for item in items:
            result = self._parse_cei_item(item, keyword, channel_name=column_name)
            if result:
                results.append(result)

        return results

    def _parse_cei_item(
        self, item_html: str, keyword: str, channel_name: str = ""
    ) -> dict[str, Any] | None:
        """解析单条CEI搜索结果."""
        # 提取标题和URL（在 <strong> 内的 <a> 标签）
        title_match = re.search(
            r'<strong>\s*\d+\.\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            item_html, re.DOTALL
        )
        if not title_match:
            return None

        url = title_match.group(1).strip()
        # 清理标题中的HTML标签（如 <font color="red">关键词</font>）
        title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()

        if len(title) < 4:
            return None

        # 提取日期（在 <span> 标签中）
        date_match = re.search(
            r'<span>(20\d{2}[-/]\d{1,2}[-/]\d{1,2})</span>',
            item_html
        )
        date = date_match.group(1) if date_match else ""

        # 提取摘要（[摘要] 后的内容）
        summary = ""
        summary_match = re.search(
            r'\[摘要\]\s*(.*?)(?:</a>|$)',
            item_html, re.DOTALL
        )
        if summary_match:
            summary = re.sub(r'<[^>]+>', '', summary_match.group(1)).strip()
            # 截断过长摘要
            if len(summary) > 300:
                summary = summary[:300] + "..."

        # 构建完整URL
        if url.startswith("//"):
            url = f"https:{url}"
        elif url.startswith("/"):
            url = f"{self.CEI_BASE}{url}"

        return {
            "title": title,
            "source": f"中国经济信息网-{channel_name}" if channel_name else "中国经济信息网",
            "date": date,
            "url": url,
            "summary": summary,
            "keyword": keyword,
            "database": "cei",
            "dimension": "",  # 后续统一标注
        }

    # ═══════════════════════════════════════════════════════════════════
    #  VPN 数据库搜索（drcnet/pkulaw/ydyl_drc）
    # ═══════════════════════════════════════════════════════════════════

    def _build_vpn_url(self, db_config: dict, keyword: str) -> str | None:
        """构建 VPN 搜索 URL.

        Args:
            db_config: 数据库配置字典（含 vpn_host/search_path）。
            keyword: 搜索关键词。
        """
        host = db_config["vpn_host"]
        path = db_config["search_path"].format(keyword=quote(keyword, safe=""))
        return f"http://{host}{self.VPN_BASE}{path}"

    async def _search_vpn_database(
        self, db_key: str, db_config: dict, keyword: str
    ) -> list[dict[str, Any]]:
        """搜索单个VPN数据库.

        Args:
            db_key: 数据库标识键。
            db_config: 数据库配置字典（含 name/vpn_host/search_path/dimension）。
            keyword: 搜索关键词。
        """
        url = self._build_vpn_url(db_config, keyword)
        if not url:
            return []

        db_name = db_config["name"]
        dimension = db_config.get("dimension", "")

        # 获取 VPN TWFID Cookie
        vpn_cookie = await self._get_vpn_cookie()

        headers = dict(self.HTTP_HEADERS)
        if vpn_cookie:
            headers["Cookie"] = vpn_cookie

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                verify=False,
                trust_env=False,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    logger.debug(f"{db_name} 返回 {resp.status_code}")
                    return []

                # 检查是否是VPN认证重定向页面
                if "vpn.lzufe.edu.cn:8444/portal" in resp.text:
                    logger.debug(f"{db_name} 需要VPN认证，跳过")
                    return []

                return self._parse_vpn_html_results(
                    resp.text, db_key, db_name, keyword, dimension, db_config
                )
        except Exception as e:
            logger.debug(f"{db_name} 搜索异常: {e}")
            return []

    def _parse_vpn_html_results(
        self,
        html: str,
        db_key: str,
        db_name: str,
        keyword: str,
        dimension: str = "",
        db_config: dict | None = None,
    ) -> list[dict[str, Any]]:
        """解析VPN数据库HTML搜索结果（通用正则提取）."""
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
                    "关于我们", "联系方式", "网站地图", "高级查询",
                ]
            ):
                continue
            if len(title) < 4:
                continue

            # 构建完整 URL
            if url.startswith("/"):
                vpn_host = (db_config or {}).get("vpn_host", "")
                url = f"http://{vpn_host}{self.VPN_BASE}{url}"
            elif not url.startswith("http"):
                continue

            # 尝试提取日期
            date_match = re.search(
                r"(20\d{2}[-/年]\d{1,2}[-/月]\d{1,2})",
                html[match.end():match.end() + 500]
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
                "dimension": dimension,
            })

        return results[:10]

    # ═══════════════════════════════════════════════════════════════════
    #  多维度标注
    # ═══════════════════════════════════════════════════════════════════

    def _tag_dimension(self, result: dict[str, Any]) -> str:
        """根据标题和摘要内容自动标注政策维度.

        采用评分制：计算三个维度的得分，取最高分。
        - policy_text: 政策文本（法规、通知、意见等原文）
        - policy_practice: 政策实践（实施案例、试点报道、新闻动态）
        - policy_analysis: 政策分析（解读、评估、学术研究）

        特殊规则：
        - 标题以"法/条例/规定/办法"结尾 → 强信号 policy_text (+3)
        - 标题含地方名称+出台/实施/试点 → 强信号 policy_practice (+3)
        """
        title = result.get("title", "")
        summary = result.get("summary", "")
        combined = f"{title} {summary}"

        scores = {"policy_text": 0, "policy_practice": 0, "policy_analysis": 0}

        # ── 强信号：标题以法规文件类型词结尾 ──
        for kw in ["法", "条例", "规定", "办法", "细则", "准则", "规则"]:
            if title.endswith(kw):
                scores["policy_text"] += 3
                break

        # ── 强信号：标题含地方名称 + 实践动作 ──
        local_indicators = ["省", "市", "县", "区", "州", "自治区"]
        practice_verbs = ["出台", "实施", "试点", "启动", "开展", "落地"]
        has_local = any(loc in title for loc in local_indicators)
        has_practice_verb = any(v in title for v in practice_verbs)
        if has_local and has_practice_verb:
            scores["policy_practice"] += 3

        # ── 普通关键词评分 ──
        for kw in self.POLICY_TEXT_KEYWORDS:
            if kw in title:
                scores["policy_text"] += 1
        for kw in self.POLICY_PRACTICE_KEYWORDS:
            if kw in combined:
                scores["policy_practice"] += 1
        for kw in self.POLICY_ANALYSIS_KEYWORDS:
            if kw in combined:
                scores["policy_analysis"] += 1

        # ── 选取得分最高的维度 ──
        max_dim = max(scores, key=scores.get)
        if scores[max_dim] > 0:
            return max_dim

        # ── 默认维度（基于数据库来源）──
        db = result.get("database", "")
        if db == "pkulaw":
            return "policy_text"
        if db == "drcnet":
            return "policy_analysis"
        return "policy_practice"

    # ═══════════════════════════════════════════════════════════════════
    #  结果分组（供LLM写作时按维度引用）
    # ═══════════════════════════════════════════════════════════════════

    def group_by_dimension(
        self, results: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """将搜索结果按维度分组.

        Returns:
            {
                "policy_text": [...],      # 政策文本
                "policy_practice": [...],  # 政策实践
                "policy_analysis": [...],  # 政策分析
            }
        """
        groups: dict[str, list[dict[str, Any]]] = {
            "policy_text": [],
            "policy_practice": [],
            "policy_analysis": [],
        }
        for r in results:
            dim = r.get("dimension", "policy_practice")
            if dim not in groups:
                dim = "policy_practice"
            groups[dim].append(r)
        return groups

    @staticmethod
    def convert_database_configs(
        db_configs: list[Any],
    ) -> dict[str, dict]:
        """将 DatabaseConfig 对象列表转换为 VPN 数据库配置字典.

        从 DatabaseSelector.recommend_for_policy_search() 返回的
        DatabaseConfig 对象中提取 VPN 搜索所需字段，转换为与
        VPN_DATABASES 兼容的字典格式。

        Args:
            db_configs: DatabaseConfig 对象列表。

        Returns:
            VPN 数据库配置字典，key 为数据库标识，value 为:
            {name, vpn_host, search_path, dimension}
            仅包含 access_method 为 vpn_url_rewrite 或 browser 的数据库。
        """
        from urllib.parse import urlparse as _urlparse

        result: dict[str, dict] = {}
        # 子分类到维度的映射
        subcat_to_dimension = {
            "policy_text": "policy_text",
            "policy_practice": "policy_practice",
            "policy_analysis": "policy_analysis",
        }
        # 已内置的数据库 key，避免重复添加
        builtin_keys = {"drcnet", "pkulaw", "ydyl_drc"}

        for db in db_configs:
            if db.key in builtin_keys:
                continue  # 跳过已内置的数据库
            if db.integration_status != "integrated":
                continue  # 跳过未集成的数据库
            if db.access_method not in ("vpn_url_rewrite", "browser"):
                continue  # 仅支持 VPN 或浏览器访问

            # 从 vpn_url 提取 vpn_host
            vpn_url = getattr(db, "vpn_url", "")
            vpn_host = ""
            if vpn_url:
                parsed = _urlparse(vpn_url)
                vpn_host = parsed.netloc or parsed.path.split("/")[0]
                # 去除端口号（VPN_BASE 统一追加）
                vpn_host = vpn_host.rsplit(":", 1)[0]

            # 从 search_url_template 提取 search_path
            search_path = getattr(db, "search_url_template", "")
            if not search_path:
                search_path = "/search?keyword={keyword}"

            # 维度映射
            subcat = getattr(db, "research_subcategory", "")
            dimension = subcat_to_dimension.get(subcat, "policy_practice")

            result[db.key] = {
                "name": db.name,
                "vpn_host": vpn_host,
                "search_path": search_path,
                "dimension": dimension,
            }

        return result
