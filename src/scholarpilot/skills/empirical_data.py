"""实证数据搜索引擎 — 两层架构统一接口.

Layer 1（直连层）：HTTP 抓取国家统计局、财政部、一带一路数据库等公开数据源
Layer 2（VPN 层）：EPS API + HTTP 抓取 CNRDS/CSMAR 等 VPN 数据库，VPN 断开时自动降级

统一接口: search(keywords, max_results) → 返回指标名称、数值、来源、URL
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


class EmpiricalDataEngine:
    """实证数据搜索引擎.

    Usage::
        engine = EmpiricalDataEngine()
        results = await engine.search(["GDP", "财政收入"], max_results=20)
        for r in results:
            print(f"{r['name']} — {r['source']} — {r['url']}")

    两层架构：
    - Layer 1: 直连数据库（无需 VPN），始终可用
    - Layer 2: VPN 数据库，VPN 连通时激活，断开时自动跳过
    """

    # ── HTTP 公共配置 ──────────────────────────────────────────
    HTTP_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    VPN_BASE = "-s.vpn.lzufe.edu.cn:8118"

    # ═══════════════════════════════════════════════════════════════
    #  Layer 1: 直连数据库配置（无需 VPN）
    # ═══════════════════════════════════════════════════════════════

    DIRECT_DATABASES: dict[str, dict] = {
        "nbs": {
            "name": "国家统计局",
            "search_url": "https://data.stats.gov.cn/easyquery.htm",
            "method": "POST",
            "subcategory": "public_data",
            "description": "国家统计局官方数据查询平台，含 GDP/CPI/人口/就业等宏观指标",
        },
        "mof": {
            "name": "财政部",
            "search_url": "https://www.mof.gov.cn/zhengwuxinxi/caizhengshuju/",
            "method": "GET",
            "subcategory": "public_data",
            "description": "财政部财政数据，含财政收入/支出/债务/转移支付等",
        },
        "ydyl_database": {
            "name": "一带一路数据库",
            "search_url": "https://www.ydylcn.com/skwx_ydyl/sublibrary?SiteID=1&ID=8721",
            "method": "GET",
            "subcategory": "regional_data",
            "description": "一带一路沿线国家经贸数据、投资数据",
        },
    }

    # ═══════════════════════════════════════════════════════════════
    #  Layer 2: VPN 数据库配置（VPN 连通时激活）
    # ═══════════════════════════════════════════════════════════════

    VPN_DATABASES: dict[str, dict] = {
        "eps": {
            "name": "EPS全球统计数据/分析平台",
            "api_base": "https://www.epsnet.com.cn",
            "subcategory": "macro_economy",
            "access_type": "api",  # api | scrape
            "description": "全球宏观统计数据，含 GDP/贸易/财政/金融等",
        },
        "cnrds": {
            "name": "中国研究数据服务平台CNRDS",
            "vpn_host": "www-cnrds-com",
            "subcategory": "microenterprise",
            "access_type": "scrape",
            "search_path": "/Home/Search?keyword={keyword}",
            "description": "上市公司财务数据、公司治理、专利数据等",
        },
        "weiguan": {
            "name": "中国微观经济数据查询系统",
            "vpn_host": "microdata-sozdata-com",
            "subcategory": "microenterprise",
            "access_type": "scrape",
            "search_path": "/search?keyword={keyword}",
            "description": "企业微观数据、工业普查数据",
        },
        "huanqiu_caijing": {
            "name": "环球财经数据平台",
            "vpn_host": "gf-harborn-cn",
            "real_domain": "https://gf.harborn.cn",
            "auth_key": "huanqiu",
            "platform": "harborn",
            "subcategory": "macro_economy",
            "access_type": "api",
            "search_path": "/index",
            "description": "全球财经数据、宏观经济指标",
        },
        "quyu_yanjiu": {
            "name": "中国区域研究数据支撑平台",
            "vpn_host": "cnrrd-sozdata-com",
            "subcategory": "regional_data",
            "access_type": "scrape",
            "search_path": "/#/search?keyword={keyword}",
            "description": "省市县区域经济数据、县域统计",
        },
        "huanghe": {
            "name": "黄河流域发展数据库",
            "vpn_host": "yrb-harborn-cn",
            "real_domain": "https://yrb.harborn.cn",
            "auth_key": "huanghe",
            "platform": "harborn",
            "subcategory": "regional_data",
            "access_type": "api",
            "search_path": "/index",
            "description": "黄河流域生态经济数据",
        },
        "csmar": {
            "name": "国泰安CSMAR数据库",
            "vpn_host": "data-csmar-com",
            "subcategory": "microenterprise",
            "access_type": "scrape",
            "search_path": "/",
            "description": "上市公司财务、股票交易、治理结构数据",
        },
        "resset": {
            "name": "锐思RESSET金融研究数据库",
            "vpn_host": "db-resset-com",
            "subcategory": "financial_market",
            "access_type": "scrape",
            "search_path": "/",
            "description": "股票、债券、基金、期货等金融数据",
        },
        "cnki_data": {
            "name": "中国经济社会大数据研究平台",
            "vpn_host": "data-cnki-net",
            "subcategory": "macro_economy",
            "access_type": "scrape",
            "search_path": "/",
            "description": "CNKI统计数据、年鉴数据",
        },
    }

    # ═══════════════════════════════════════════════════════════════
    #  初始化
    # ═══════════════════════════════════════════════════════════════

    def __init__(self, timeout: int = 30, project_root: str = "."):
        self._timeout = timeout
        self._project_root = project_root
        self._client: httpx.AsyncClient | None = None
        self._eps_sid: str | None = None
        self._vpn_available: bool | None = None  # None = 未检测
        self._auth_mgr: Any = None  # AuthManager，延迟初始化

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建httpx异步客户端.

        自动注入 VPN TWFID Cookie 用于 *.vpn.lzufe.edu.cn 资源访问。
        获取 TWFID 后同步到 AuthManager，统一管理 VPN 层 + 数据库层认证。
        """
        # 首次访问时获取 VPN Cookie
        if not hasattr(self, '_vpn_cookie') or self._vpn_cookie is None:
            self._vpn_cookie = None
            try:
                from scholarpilot.utils.vpn import get_vpn_session_manager
                mgr = get_vpn_session_manager()
                self._vpn_cookie = await mgr.get_cookie_header()
                # 同步 TWFID 到 AuthManager，统一管理
                twfid = await mgr.get_twfid()
                if twfid:
                    auth_mgr = self._get_auth_manager()
                    if auth_mgr and not auth_mgr.get_twfid():
                        auth_mgr.save_twfid(twfid)
                        logger.debug("TWFID 已同步到 AuthManager")
            except Exception as e:
                logger.debug(f"获取 VPN Cookie 失败: {e}")

        headers = dict(self.HTTP_HEADERS)
        if self._vpn_cookie:
            headers["Cookie"] = self._vpn_cookie

        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                verify=False,
                trust_env=False,
                proxy=None,
                headers=headers,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    # ═══════════════════════════════════════════════════════════════
    #  VPN 可用性检测
    # ═══════════════════════════════════════════════════════════════

    async def _check_vpn(self) -> bool:
        """检测 VPN 隧道是否连通（缓存结果）."""
        if self._vpn_available is not None:
            return self._vpn_available

        client = await self._get_client()
        try:
            # 访问一个轻量 VPN 检测 URL
            test_url = f"http://www-cnrds-com{self.VPN_BASE}/"
            resp = await client.get(test_url)
            self._vpn_available = (
                resp.status_code == 200
                and "vpn.lzufe.edu.cn:8444/portal" not in resp.text
            )
        except Exception:
            self._vpn_available = False

        logger.info(f"VPN 可用性: {self._vpn_available}")
        return self._vpn_available

    # ═══════════════════════════════════════════════════════════════
    #  统一搜索接口
    # ═══════════════════════════════════════════════════════════════

    async def search(
        self,
        keywords: list[str],
        max_results: int = 20,
        subcategory_filter: str = "",
        use_vpn: bool = True,
    ) -> list[dict[str, Any]]:
        """统一搜索实证数据指标.

        搜索策略：
        1. Layer 1（直连）：始终执行，搜索 NBS/MOF/YDYL
        2. Layer 2（VPN）：仅在 VPN 可用时执行，搜索 EPS/CNRDS/CSMAR 等

        Args:
            keywords: 搜索关键词列表（如 ["GDP", "财政收入", "碳排放"]）。
            max_results: 最大返回结果数。
            subcategory_filter: 子分类筛选（macro_economy/microenterprise/regional_data/financial_market/public_data）。
            use_vpn: 是否尝试 VPN 层。

        Returns:
            搜索结果列表，每项含:
            {name, source, subcategory, url, description, access_type}
        """
        all_results: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        # ── Layer 1: 直连搜索 ────────────────────────────────
        for db_key, db_cfg in self.DIRECT_DATABASES.items():
            if subcategory_filter and db_cfg["subcategory"] != subcategory_filter:
                continue
            if len(all_results) >= max_results:
                break
            for kw in keywords:
                if len(all_results) >= max_results:
                    break
                try:
                    results = await self._search_direct(db_key, db_cfg, kw)
                    for r in results:
                        name = r.get("name", "")
                        if name and name not in seen_names:
                            seen_names.add(name)
                            all_results.append(r)
                except Exception as e:
                    logger.debug(f"直连搜索失败 [{db_key}/{kw}]: {e}")

        # ── Layer 2: 隧道直连搜索（harborn 平台，真实域名 + token） ───
        # harborn 平台通过 EasyConnect 隧道直连真实域名，不需要 TWFID
        for db_key, db_cfg in self.VPN_DATABASES.items():
            if db_cfg.get("platform") != "harborn":
                continue
            if subcategory_filter and db_cfg["subcategory"] != subcategory_filter:
                continue
            if len(all_results) >= max_results:
                break
            for kw in keywords:
                if len(all_results) >= max_results:
                    break
                try:
                    results = await self._search_harborn(db_key, db_cfg, kw)
                    for r in results:
                        name = r.get("name", "")
                        if name and name not in seen_names:
                            seen_names.add(name)
                            all_results.append(r)
                except Exception as e:
                    logger.debug(f"harborn搜索失败 [{db_key}/{kw}]: {e}")

        # ── Layer 3: VPN 代理搜索（需要 TWFID） ────────────────
        if use_vpn and await self._check_vpn():
            for db_key, db_cfg in self.VPN_DATABASES.items():
                # 跳过已处理的 harborn 平台
                if db_cfg.get("platform") == "harborn":
                    continue
                if subcategory_filter and db_cfg["subcategory"] != subcategory_filter:
                    continue
                if len(all_results) >= max_results:
                    break
                for kw in keywords:
                    if len(all_results) >= max_results:
                        break
                    try:
                        if db_cfg["access_type"] == "api":
                            results = await self._search_eps_api(kw)
                        else:
                            results = await self._search_vpn_scrape(db_key, db_cfg, kw)
                        for r in results:
                            name = r.get("name", "")
                            if name and name not in seen_names:
                                seen_names.add(name)
                                all_results.append(r)
                    except Exception as e:
                        logger.debug(f"VPN搜索失败 [{db_key}/{kw}]: {e}")

        logger.info(
            f"实证数据搜索完成: {len(keywords)} 关键词, "
            f"{len(all_results)} 条结果 (直连+VPN)"
        )
        return all_results

    # ═══════════════════════════════════════════════════════════════
    #  Layer 1: 直连数据库搜索
    # ═══════════════════════════════════════════════════════════════

    async def _search_direct(
        self, db_key: str, db_cfg: dict, keyword: str
    ) -> list[dict[str, Any]]:
        """搜索直连数据库."""
        if db_key == "nbs":
            return await self._search_nbs(keyword)
        elif db_key == "mof":
            return await self._search_mof(keyword)
        elif db_key == "ydyl_database":
            return await self._search_ydyl(keyword)
        return []

    async def _search_nbs(self, keyword: str) -> list[dict[str, Any]]:
        """搜索国家统计局数据.

        NBS API: https://data.stats.gov.cn/easyquery.htm
        POST 请求，参数: dbcode=fsnd, id=指标编码, wd=关键词, m=QueryData
        """
        results: list[dict[str, Any]] = []
        client = await self._get_client()

        try:
            # 尝试搜索指标
            params = {
                "m": "QueryData",
                "dbcode": "fsnd",
                "rowcode": "zb",
                "colcode": "sj",
                "wds": "[]",
                "dfwds": '[{"wdcode":"zb","valuecode":"' + keyword + '"}]',
            }
            resp = await client.get(
                "https://data.stats.gov.cn/easyquery.htm",
                params=params,
                headers=self.HTTP_HEADERS,
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data.get("returncode") == 200:
                        for row in data.get("returndata", {}).get("datanodes", [])[:10]:
                            name = row.get("wds", [{}])[0].get("valuecode", "")
                            if name:
                                results.append({
                                    "name": name,
                                    "source": "国家统计局",
                                    "subcategory": "public_data",
                                    "url": f"https://data.stats.gov.cn/easyquery.htm?cn=E0103",
                                    "description": "国家统计局官方数据",
                                    "access_type": "direct",
                                })
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"NBS搜索异常: {e}")

        return results

    async def _search_mof(self, keyword: str) -> list[dict[str, Any]]:
        """搜索财政部财政数据.

        财政部网站搜索: https://www.mof.gov.cn/zhengwuxinxi/caizhengshuju/
        从页面中提取数据链接和标题。
        """
        results: list[dict[str, Any]] = []
        client = await self._get_client()

        try:
            resp = await client.get(
                "https://www.mof.gov.cn/zhengwuxinxi/caizhengshuju/",
                headers=self.HTTP_HEADERS,
            )
            if resp.status_code == 200:
                # 提取包含关键词的链接
                pattern = re.compile(
                    rf'<a[^>]*href="([^"]*)"[^>]*>([^<]*{re.escape(keyword)}[^<]*)</a>',
                    re.IGNORECASE,
                )
                for match in pattern.finditer(resp.text)[:10]:
                    href = match.group(1).strip()
                    title = match.group(2).strip()
                    if len(title) < 4:
                        continue
                    url = href if href.startswith("http") else f"https://www.mof.gov.cn{href}"
                    results.append({
                        "name": title,
                        "source": "财政部",
                        "subcategory": "public_data",
                        "url": url,
                        "description": "财政数据",
                        "access_type": "direct",
                    })
        except Exception as e:
            logger.debug(f"MOF搜索异常: {e}")

        return results

    async def _search_ydyl(self, keyword: str) -> list[dict[str, Any]]:
        """搜索一带一路数据库."""
        from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess

        results: list[dict[str, Any]] = []
        try:
            vpn = VpnDatabaseAccess()
            raw = await vpn.search_database("ydyl_database", keyword)
            for r in raw[:10]:
                results.append({
                    "name": r.get("title", ""),
                    "source": "一带一路数据库",
                    "subcategory": "regional_data",
                    "url": r.get("url", ""),
                    "description": r.get("summary", ""),
                    "access_type": "direct",
                })
            await vpn.close()
        except Exception as e:
            logger.debug(f"一带一路搜索异常: {e}")

        return results

    # ═══════════════════════════════════════════════════════════════
    #  Layer 2: VPN 数据库搜索
    # ═══════════════════════════════════════════════════════════════

    async def _search_eps_api(self, keyword: str) -> list[dict[str, Any]]:
        """通过 EPS API 搜索指标."""
        results: list[dict[str, Any]] = []

        if not await self._eps_ensure_login():
            return results

        # 获取立方体树并搜索
        try:
            indicators = await self._eps_get_indicators(keyword)
            for ind in indicators:
                results.append({
                    "name": ind.get("name", ""),
                    "source": "EPS全球统计数据",
                    "subcategory": "macro_economy",
                    "url": f"https://www.epsnet.com.cn/index.html#/Data?cubeId={ind.get('cube_id', '')}",
                    "description": f"EPS指标: {ind.get('path', '')}",
                    "access_type": "api",
                    "cube_id": ind.get("cube_id", ""),
                })
        except Exception as e:
            logger.debug(f"EPS API搜索异常: {e}")

        return results

    async def _eps_ensure_login(self) -> bool:
        """确保 EPS 已登录（获取 sid）."""
        if self._eps_sid:
            return True

        from scholarpilot.skills.vpn_database_access import build_vpn_url

        client = await self._get_client()
        try:
            eps_vpn_url = build_vpn_url("https://www.epsnet.com.cn/")
            resp = await client.get(eps_vpn_url)
            if resp.status_code == 200:
                sid_match = re.search(r'sid["\s:=]+([a-f0-9]{32})', resp.text)
                if sid_match:
                    self._eps_sid = sid_match.group(1)
                    logger.info(f"EPS登录成功，sid: {self._eps_sid[:8]}...")
                    return True
                if "sid" in resp.cookies:
                    self._eps_sid = resp.cookies["sid"]
                    return True
        except Exception as e:
            logger.warning(f"EPS登录失败: {e}")
        return False

    async def _eps_get_indicators(self, keyword: str) -> list[dict]:
        """获取 EPS 指标列表."""
        from scholarpilot.skills.vpn_database_access import build_vpn_url

        results: list[dict] = []
        client = await self._get_client()

        # 获取立方体树
        cube_api = build_vpn_url("https://www.epsnet.com.cn/api/cube/getCubeTree")
        try:
            resp = await client.get(cube_api, params={"sid": self._eps_sid})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    cube_tree = data.get("data", {}).get("children", [])
                    self._search_in_cube_tree(cube_tree, keyword, results)
        except Exception as e:
            logger.debug(f"EPS立方体树获取失败: {e}")

        return results[:20]

    def _search_in_cube_tree(
        self, nodes: list[dict], keyword: str, results: list[dict], depth: int = 0
    ):
        """递归搜索 EPS 立方体树."""
        for node in nodes:
            name = node.get("name", "")
            if keyword.lower() in name.lower():
                results.append({
                    "name": name,
                    "cube_id": node.get("id", ""),
                    "path": node.get("path", ""),
                    "type": node.get("type", ""),
                })
            children = node.get("children", [])
            if children and depth < 3:
                self._search_in_cube_tree(children, keyword, results, depth + 1)

    # ═══════════════════════════════════════════════════════════════
    #  Layer 2: harborn 平台 API 搜索（真实域名 + Bearer token）
    # ═══════════════════════════════════════════════════════════════

    def _get_auth_manager(self):
        """延迟初始化 AuthManager."""
        if self._auth_mgr is None:
            try:
                from scholarpilot.skills.auth_manager import get_auth_manager
                self._auth_mgr = get_auth_manager(self._project_root)
            except Exception as e:
                logger.warning(f"AuthManager 初始化失败: {e}")
        return self._auth_mgr

    async def _search_harborn(
        self, db_key: str, db_cfg: dict, keyword: str
    ) -> list[dict[str, Any]]:
        """搜索 harborn 平台数据库（环球财经/黄河流域）.

        通过 EasyConnect 隧道直连真实域名（gf.harborn.cn / yrb.harborn.cn），
        使用持久化的 Bearer token 认证，不依赖 VPN 代理地址或 TWFID。
        """
        results: list[dict[str, Any]] = []

        # 获取持久化的认证凭据
        auth_key = db_cfg.get("auth_key", db_key)
        auth_mgr = self._get_auth_manager()
        if auth_mgr is None:
            logger.warning(f"AuthManager 不可用，跳过 {db_key}")
            return results

        cred = await auth_mgr.get_valid_credentials(auth_key)
        if cred is None:
            logger.warning(
                f"凭据缺失或过期: {auth_key}。请重新登录提取 token。\n"
                f"{auth_mgr.get_login_guide(auth_key)}"
            )
            return results

        base_url = db_cfg["real_domain"]
        headers = {
            **self.HTTP_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Authorization": cred.bearer_header,
        }

        client = await self._get_client()

        if db_key == "huanqiu_caijing":
            # 环球财经：搜索论文 + 指标分类
            results = await self._search_harborn_huanqiu(
                client, base_url, headers, keyword, db_cfg
            )
        elif db_key == "huanghe":
            # 黄河流域：全类型搜索
            results = await self._search_harborn_huanghe(
                client, base_url, headers, keyword, db_cfg
            )

        return results

    async def _search_harborn_huanqiu(
        self, client: httpx.AsyncClient, base_url: str,
        headers: dict, keyword: str, db_cfg: dict
    ) -> list[dict[str, Any]]:
        """搜索环球财经数据平台."""
        results: list[dict[str, Any]] = []

        # 1. 搜索论文（POST /hqcj/statistic/papers）
        #    注意: searchName 必须放在 query param 中才能生效，
        #    放在 JSON body 中会被忽略（返回全量未过滤结果）。
        try:
            resp = await client.post(
                f"{base_url}/hqcj/statistic/papers",
                params={"year": "", "searchName": keyword, "pageNo": 0, "pageSize": 10},
                json={},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0 and data.get("data"):
                    for item in data["data"].get("results", [])[:10]:
                        results.append({
                            "name": item.get("title", ""),
                            "source": db_cfg["name"],
                            "subcategory": db_cfg["subcategory"],
                            "url": f"{base_url}/#/paper/detail?id={item.get('id', '')}",
                            "description": item.get("summary", "")[:200],
                            "access_type": "api",
                        })
        except Exception as e:
            logger.debug(f"环球论文搜索异常: {e}")

        # 2. 获取指标分类（匹配关键词）
        try:
            resp = await client.get(
                f"{base_url}/hqcj/home/homeCjIndicatorCategorys",
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0 and data.get("data"):
                    for item in data["data"]:
                        name = item.get("subName", "")
                        if keyword.lower() in name.lower():
                            results.append({
                                "name": name,
                                "source": db_cfg["name"],
                                "subcategory": db_cfg["subcategory"],
                                "url": f"{base_url}/#/data",
                                "description": f"指标分类: {item.get('categoryName', '')}",
                                "access_type": "api",
                            })
        except Exception as e:
            logger.debug(f"环球指标搜索异常: {e}")

        return results

    async def _search_harborn_huanghe(
        self, client: httpx.AsyncClient, base_url: str,
        headers: dict, keyword: str, db_cfg: dict
    ) -> list[dict[str, Any]]:
        """搜索黄河流域发展数据库."""
        results: list[dict[str, Any]] = []

        # 1. 全类型搜索（POST /api/hhly/search/all）
        try:
            resp = await client.post(
                f"{base_url}/api/hhly/search/all",
                json={
                    "type": 100,  # 全部类型
                    "keyword": keyword,
                    "way": 1,
                    "pageNo": 0,
                    "pageSize": 10,
                },
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 200 and data.get("data"):
                    # 解析搜索结果
                    results_data = data["data"]
                    # 检查是否有 results 字段
                    if isinstance(results_data, dict):
                        for item in results_data.get("results", [])[:10]:
                            results.append({
                                "name": item.get("title", ""),
                                "source": db_cfg["name"],
                                "subcategory": db_cfg["subcategory"],
                                "url": f"{base_url}/#/detail?id={item.get('id', '')}",
                                "description": item.get("summary", "")[:200],
                                "access_type": "api",
                            })
        except Exception as e:
            logger.debug(f"黄河搜索异常: {e}")

        # 2. 获取指标分类（匹配关键词）
        try:
            resp = await client.get(
                f"{base_url}/hhly/home/homeIndicatorCategorys",
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0 and data.get("data"):
                    for item in data["data"]:
                        name = item.get("subName", "")
                        if keyword.lower() in name.lower():
                            results.append({
                                "name": name,
                                "source": db_cfg["name"],
                                "subcategory": db_cfg["subcategory"],
                                "url": f"{base_url}/#/data",
                                "description": f"指标分类: {item.get('categoryName', '')}",
                                "access_type": "api",
                            })
        except Exception as e:
            logger.debug(f"黄河指标搜索异常: {e}")

        return results

    # ═══════════════════════════════════════════════════════════════
    #  Layer 3: VPN 代理搜索（需要 TWFID + 数据库 cookies）
    # ═══════════════════════════════════════════════════════════════

    # AuthManager 中 VPN 代理数据库键名与 VPN_DATABASES 键的映射
    VPN_DB_AUTH_KEY_MAP: dict[str, str] = {
        "cnki_data": "cnki_data",
        "weiguan": "weiguan",
        "quyu_yanjiu": "quyu",
        "cnrds": "cnrds",
        "csmar": "csmar",
        "resset": "resset",
    }

    def _get_vpn_db_headers(self, db_key: str) -> dict[str, str]:
        """构建 VPN 代理数据库的请求头（TWFID + 数据库 cookies 组合）.

        此前 _search_vpn_scrape 只注入 TWFID，数据库级 cookies
        (SF_cookie_413/SESSION/JSESSIONID 等) 从未注入，
        导致 CNKI/微观/区域 等库搜索时缺少应用层认证。

        Returns:
            含组合 Cookie 的 headers 字典.
        """
        headers = dict(self.HTTP_HEADERS)
        auth_mgr = self._get_auth_manager()
        if auth_mgr is None:
            # AuthManager 不可用，回退到 client 级 TWFID
            if self._vpn_cookie:
                headers["Cookie"] = self._vpn_cookie
            return headers

        auth_key = self.VPN_DB_AUTH_KEY_MAP.get(db_key, db_key)
        combined_cookie = auth_mgr.build_vpn_cookie_header(auth_key)
        if combined_cookie:
            headers["Cookie"] = combined_cookie
        elif self._vpn_cookie:
            headers["Cookie"] = self._vpn_cookie
        else:
            logger.debug(f"VPN 代理数据库 {db_key} 无可用 Cookie")
        return headers

    async def _refresh_twfid_and_save(self) -> str | None:
        """强制刷新 TWFID 并保存到 AuthManager.

        当 VPN 代理请求返回登录重定向时调用此方法：
        1. 调用 VPNSessionManager 强制刷新 TWFID
        2. 保存新 TWFID 到 AuthManager
        3. 重建 httpx 客户端以使用新 Cookie

        Returns:
            新的 TWFID 值，失败返回 None.
        """
        try:
            from scholarpilot.utils.vpn import get_vpn_session_manager
            mgr = get_vpn_session_manager()
            new_cookie = await mgr.get_cookie_header(force_refresh=True)
            new_twfid = await mgr.get_twfid()
            if new_twfid:
                auth_mgr = self._get_auth_manager()
                if auth_mgr:
                    auth_mgr.save_twfid(new_twfid)
                # 重建客户端以使用新 Cookie
                self._vpn_cookie = new_cookie
                if self._client and not self._client.is_closed:
                    await self._client.aclose()
                self._client = None
                logger.info(f"TWFID 已刷新并保存 (值={new_twfid[:12]}...)")
                return new_twfid
            else:
                logger.warning("TWFID 刷新失败：VPNSessionManager 未返回有效值")
                return None
        except Exception as e:
            logger.warning(f"TWFID 刷新异常: {e}")
            return None

    # 登录重定向检测标识
    VPN_LOGIN_REDIRECT_MARKER = "vpn.lzufe.edu.cn:8444/portal"

    async def _search_vpn_scrape(
        self, db_key: str, db_cfg: dict, keyword: str
    ) -> list[dict[str, Any]]:
        """通过 VPN HTTP 抓取搜索数据库.

        认证链路: TWFID (VPN 代理层) + 数据库 cookies (应用层)
        自动刷新: 检测到登录重定向时，刷新 TWFID 并重试一次。
        """
        results: list[dict[str, Any]] = []

        # 跳过非 scrape 类型（如 api 类型数据库使用独立搜索方法）
        if db_cfg.get("access_type") != "scrape":
            return results
        vpn_host = db_cfg.get("vpn_host")
        if not vpn_host:
            return results

        client = await self._get_client()
        search_path = db_cfg["search_path"].format(keyword=quote(keyword, safe=""))
        url = f"http://{vpn_host}{self.VPN_BASE}{search_path}"

        # 构建组合 Cookie 头: TWFID + 数据库级 cookies
        db_headers = self._get_vpn_db_headers(db_key)

        try:
            resp = await client.get(url, headers=db_headers)

            # 自动刷新: 检测到 VPN 登录重定向 → 刷新 TWFID → 重试一次
            if resp.status_code != 200 or self.VPN_LOGIN_REDIRECT_MARKER in resp.text:
                logger.info(f"VPN 代理请求触发登录重定向 [{db_key}]，尝试刷新 TWFID...")
                new_twfid = await self._refresh_twfid_and_save()
                if new_twfid:
                    client = await self._get_client()  # 重建后的客户端
                    db_headers = self._get_vpn_db_headers(db_key)  # 重建后的组合 Cookie
                    resp = await client.get(url, headers=db_headers)

            if resp.status_code != 200:
                return results
            if self.VPN_LOGIN_REDIRECT_MARKER in resp.text:
                logger.warning(
                    f"VPN 代理数据库 {db_key} 认证失败: TWFID 刷新后仍被重定向。"
                    f"请检查数据库 cookies 是否已过期: "
                    f"{self._get_auth_manager().get_login_guide(db_key) if self._get_auth_manager() else ''}"
                )
                return results

            # 通用 HTML 解析
            title_pattern = re.compile(
                r'<a[^>]*href="([^"]*)"[^>]*>([^<]{4,100})</a>',
                re.IGNORECASE,
            )
            for match in title_pattern.finditer(resp.text):
                href = match.group(1).strip()
                title = match.group(2).strip()

                # 过滤导航
                if any(s in title.lower() for s in [
                    "首页", "登录", "注册", "更多", "返回", "下一页", "上一页",
                    "关于我们", "联系方式", "网站地图",
                ]):
                    continue
                if len(title) < 4:
                    continue

                full_url = href
                if href.startswith("/"):
                    full_url = f"http://{vpn_host}{self.VPN_BASE}{href}"
                elif not href.startswith("http"):
                    continue

                results.append({
                    "name": title,
                    "source": db_cfg["name"],
                    "subcategory": db_cfg["subcategory"],
                    "url": full_url,
                    "description": db_cfg.get("description", ""),
                    "access_type": "vpn_scrape",
                })

        except Exception as e:
            logger.debug(f"VPN抓取异常 [{db_key}]: {e}")

        return results[:10]

    # ═══════════════════════════════════════════════════════════════
    #  辅助方法
    # ═══════════════════════════════════════════════════════════════

    def get_database_summary(self) -> dict[str, Any]:
        """获取数据库状态摘要."""
        direct_count = len(self.DIRECT_DATABASES)
        vpn_count = len(self.VPN_DATABASES)
        return {
            "total": direct_count + vpn_count,
            "direct_available": direct_count,
            "vpn_total": vpn_count,
            "vpn_available": self._vpn_available,
            "direct_dbs": [
                {"key": k, "name": v["name"], "subcategory": v["subcategory"]}
                for k, v in self.DIRECT_DATABASES.items()
            ],
            "vpn_dbs": [
                {"key": k, "name": v["name"], "subcategory": v["subcategory"]}
                for k, v in self.VPN_DATABASES.items()
            ],
        }

    def format_results(self, results: list[dict[str, Any]]) -> str:
        """格式化搜索结果为 Markdown."""
        if not results:
            return "（未找到匹配的实证数据指标）"

        lines = ["## 实证数据搜索结果\n"]
        subcat_labels = {
            "macro_economy": "宏观经济",
            "microenterprise": "微观企业",
            "regional_data": "区域数据",
            "financial_market": "金融市场",
            "public_data": "公开数据",
        }

        # 按子分类分组
        grouped: dict[str, list[dict]] = {}
        for r in results:
            sc = r.get("subcategory", "other")
            grouped.setdefault(sc, []).append(r)

        for sc, items in grouped.items():
            label = subcat_labels.get(sc, sc)
            lines.append(f"### {label}（{len(items)} 条）")
            for item in items:
                access = "API" if item.get("access_type") == "api" else "网页"
                lines.append(
                    f"- **{item['name']}** — {item['source']} [{access}]\n"
                    f"  {item.get('description', '')}\n"
                    f"  <{item.get('url', '')}>"
                )
            lines.append("")

        return "\n".join(lines)