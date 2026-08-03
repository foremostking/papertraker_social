"""VPN数据库统一访问层.

提供对VPN可达数据库的编程访问，包括：
1. 英文文献数据库的VPN代理URL构建（ScienceDirect/Springer/EBSCO/Emerald）
2. EPS统计数据API引擎（sid参数认证）
3. 统一的数据库搜索接口

注意：VPN URL重写格式为 {域名点改短横}-s.vpn.lzufe.edu.cn:8118/
例如: www.sciencedirect.com → www-sciencedirect-com-s.vpn.lzufe.edu.cn:8118

Usage:
    from scholarpilot.skills.vpn_database_access import VpnDatabaseAccess, build_vpn_url

    async with VpnDatabaseAccess() as vda:
        # 1. 列出可用数据库
        dbs = vda.list_databases()

        # 2. 搜索英文文献
        results = await vda.search_english_literature("machine learning")

        # 3. 获取EPS统计数据
        await vda.eps_login()
        indicators = await vda.eps_search_indicators("GDP")
"""

import re
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "DatabaseConfig",
    "VpnDatabaseAccess",
    "build_vpn_url",
    "DATABASES",
    "VPN_HOST_TEMPLATE",
]

VPN_HOST_TEMPLATE = "{domain}-s.vpn.lzufe.edu.cn:8118"


def build_vpn_url(original_url: str) -> str:
    """将原始数据库URL转换为VPN代理URL.

    示例:
        https://www.sciencedirect.com/search?query=AI
        → http://www-sciencedirect-com-s.vpn.lzufe.edu.cn:8118/search?query=AI

    Args:
        original_url: 原始数据库URL（含http/https协议）.

    Returns:
        VPN代理URL。若无法解析原始URL，则原样返回.
    """
    match = re.match(r'https?://([^/]+)(/.*)?', original_url)
    if not match:
        return original_url
    domain = match.group(1)
    path = match.group(2) or ""
    # 域名中的点改为短横
    vpn_domain = domain.replace(".", "-")
    vpn_host = VPN_HOST_TEMPLATE.format(domain=vpn_domain)
    return f"http://{vpn_host}{path}"


@dataclass
class DatabaseConfig:
    """数据库访问配置."""

    key: str
    name: str
    platform: str
    original_url: str
    vpn_url: str
    access_method: str  # "vpn_url_rewrite" | "eps_api" | "browser"
    api_base: str = ""
    search_url_template: str = ""  # URL搜索模板，{keyword}占位

    @property
    def vpn_domain(self) -> str:
        """从vpn_url中提取VPN域名（含端口）.

        例如: http://www-sciencedirect-com-s.vpn.lzufe.edu.cn:8118/
        → www-sciencedirect-com-s.vpn.lzufe.edu.cn:8118
        """
        # vpn_url 形如 http://host:port/path
        parsed = urlparse(self.vpn_url)
        host = parsed.netloc or parsed.path.split("/")[0]
        return host


# 预配置的数据库列表
DATABASES: dict[str, DatabaseConfig] = {
    "sciencedirect": DatabaseConfig(
        key="sciencedirect",
        name="ScienceDirect",
        platform="SCIENCEDIRECT",
        original_url="https://www.sciencedirect.com/",
        vpn_url=build_vpn_url("https://www.sciencedirect.com/"),
        access_method="vpn_url_rewrite",
        search_url_template="/search?query={keyword}&show=25",
    ),
    "springer": DatabaseConfig(
        key="springer",
        name="Springer电子期刊",
        platform="SPRINGER",
        original_url="https://link.springer.com/",
        vpn_url=build_vpn_url("https://link.springer.com/"),
        access_method="vpn_url_rewrite",
        search_url_template="/search?query={keyword}&showAll=false",
    ),
    "ebsco": DatabaseConfig(
        key="ebsco",
        name="EBSCO商管财经",
        platform="EBSCO",
        original_url="http://search.ebscohost.com/",
        vpn_url=build_vpn_url("http://search.ebscohost.com/"),
        access_method="browser",  # 需要浏览器自动化
    ),
    "emerald": DatabaseConfig(
        key="emerald",
        name="Emerald",
        platform="EMERALD",
        original_url="https://www.emerald.com/",
        vpn_url=build_vpn_url("https://www.emerald.com/"),
        access_method="vpn_url_rewrite",
        search_url_template="/search?q={keyword}",
    ),
    "eps": DatabaseConfig(
        key="eps",
        name="EPS全球统计数据/分析平台",
        platform="EPS",
        original_url="https://www.epsnet.com.cn/",
        vpn_url=build_vpn_url("https://www.epsnet.com.cn/"),
        access_method="eps_api",
        api_base="https://www.epsnet.com.cn",
    ),
}


class VpnDatabaseAccess:
    """VPN数据库统一访问层.

    提供对VPN可达数据库的编程访问。
    英文文献数据库通过VPN代理URL重写访问；
    EPS统计数据通过API访问。
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._eps_sid: str | None = None  # EPS会话ID

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建httpx异步客户端."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                verify=False,  # VPN代理可能使用自签名证书
            )
        return self._client

    async def close(self):
        """关闭HTTP客户端."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    def get_database(self, key: str) -> DatabaseConfig | None:
        """获取数据库配置.

        Args:
            key: 数据库标识（如"sciencedirect"）.

        Returns:
            DatabaseConfig实例，若不存在返回None.
        """
        return DATABASES.get(key)

    def list_databases(self) -> list[DatabaseConfig]:
        """列出所有可用数据库.

        Returns:
            DatabaseConfig列表.
        """
        return list(DATABASES.values())

    def get_search_url(self, db_key: str, keyword: str) -> str | None:
        """获取VPN数据库的搜索URL.

        对于vpn_url_rewrite类型的数据库，构建完整的VPN搜索URL。
        对于browser类型的数据库，返回VPN基础URL（需浏览器自动化）。

        Args:
            db_key: 数据库标识.
            keyword: 搜索关键词.

        Returns:
            搜索URL字符串，或None.
        """
        db = DATABASES.get(db_key)
        if not db:
            return None
        if db.access_method == "vpn_url_rewrite" and db.search_url_template:
            search_path = db.search_url_template.format(keyword=keyword)
            return f"http://{db.vpn_domain}{search_path}"
        elif db.access_method == "browser":
            return db.vpn_url
        return None

    async def search_english_literature(
        self,
        keyword: str,
        sources: list[str] | None = None,
    ) -> list[dict]:
        """通过VPN代理搜索英文文献.

        对ScienceDirect/Springer/Emerald等数据库发起HTTP搜索请求。
        注意：这些数据库返回的是HTML页面，解析结果有限。
        建议优先使用OpenAlex/Semantic Scholar API获取元数据，
        此方法主要用于获取全文PDF链接。

        Args:
            keyword: 搜索关键词（英文）.
            sources: 数据库列表，默认["sciencedirect", "springer", "emerald"].

        Returns:
            搜索结果列表，每项含title/url/database字段.
        """
        if sources is None:
            sources = ["sciencedirect", "springer", "emerald"]

        results = []
        client = await self._get_client()

        for source in sources:
            db = DATABASES.get(source)
            if not db or db.access_method != "vpn_url_rewrite":
                continue
            try:
                search_path = db.search_url_template.format(keyword=keyword)
                url = f"http://{db.vpn_domain}{search_path}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    # 简单提取搜索结果链接
                    # 注意：完整解析需要BeautifulSoup，这里仅提取基本链接
                    links = re.findall(
                        r'href="(/[^"]*(?:article|chapter|book)[^"]*)"',
                        resp.text,
                    )
                    for link in links[:10]:  # 每个源最多10条
                        full_url = f"http://{db.vpn_domain}{link}"
                        results.append({
                            "url": full_url,
                            "database": db.name,
                            "access": "vpn_full_text",
                        })
                    logger.info(
                        f"VPN搜索 {db.name}: 找到 {len(links[:10])} 条结果"
                    )
            except Exception as e:
                logger.warning(f"VPN搜索 {db.name} 失败: {e}")
                continue

        return results

    async def get_fulltext_pdf_url(self, article_url: str) -> str | None:
        """获取文章的VPN全文PDF链接.

        给定文章页面URL，尝试提取PDF下载链接。
        需要通过VPN代理访问。

        Args:
            article_url: 文章页面URL（原始URL或VPN URL）.

        Returns:
            PDF的VPN下载URL，或None.
        """
        # 如果是原始URL，转换为VPN URL
        if "vpn.lzufe.edu.cn" not in article_url:
            article_url = build_vpn_url(article_url)

        client = await self._get_client()
        try:
            resp = await client.get(article_url)
            if resp.status_code == 200:
                # 查找PDF链接
                pdf_links = re.findall(
                    r'href="(/[^"]*\.pdf[^"]*)"',
                    resp.text,
                    re.IGNORECASE,
                )
                if pdf_links:
                    # 转换为VPN URL
                    domain_part = article_url.split("/")[2]  # 获取VPN域名
                    return f"http://{domain_part}{pdf_links[0]}"
        except Exception as e:
            logger.warning(f"获取PDF链接失败: {e}")
        return None

    # ===== EPS 统计数据 API =====

    async def eps_login(self) -> str | None:
        """EPS平台登录，获取sid（会话ID）.

        EPS通过sid参数即可调用API，无需显式CARSI登录。
        通过VPN访问EPS首页，从响应中提取sid。

        Returns:
            sid字符串，或None（失败时）.
        """
        client = await self._get_client()
        try:
            # 通过VPN访问EPS首页
            eps_vpn_url = build_vpn_url("https://www.epsnet.com.cn/")
            resp = await client.get(eps_vpn_url)
            if resp.status_code == 200:
                # 从HTML中提取sid
                sid_match = re.search(r'sid["\s:=]+([a-f0-9]{32})', resp.text)
                if sid_match:
                    self._eps_sid = sid_match.group(1)
                    logger.info(f"EPS登录成功，sid: {self._eps_sid[:8]}...")
                    return self._eps_sid
                # 从Cookie提取
                if "sid" in resp.cookies:
                    self._eps_sid = resp.cookies["sid"]
                    logger.info(
                        f"EPS登录成功(Cookie)，sid: {self._eps_sid[:8]}..."
                    )
                    return self._eps_sid
        except Exception as e:
            logger.warning(f"EPS登录失败: {e}")
        return None

    async def eps_get_cube_tree(self) -> list[dict]:
        """获取EPS数据立方体树结构.

        Returns:
            数据立方体列表，每项含cubeId/name/children等字段.
        """
        if not self._eps_sid:
            sid = await self.eps_login()
            if not sid:
                return []

        client = await self._get_client()
        eps_api = build_vpn_url("https://www.epsnet.com.cn/api/cube/getCubeTree")
        try:
            resp = await client.get(eps_api, params={"sid": self._eps_sid})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {}).get("children", [])
        except Exception as e:
            logger.warning(f"EPS获取立方体树失败: {e}")
        return []

    async def eps_search_indicators(self, keyword: str) -> list[dict]:
        """搜索EPS统计指标.

        Args:
            keyword: 指标关键词（如"GDP""财政收入"）.

        Returns:
            匹配的指标列表，每项含cubeId/dimensionId/memberId/name等字段.
        """
        cube_tree = await self.eps_get_cube_tree()
        results = []

        def search_in_tree(nodes, depth=0):
            for node in nodes:
                name = node.get("name", "")
                if keyword.lower() in name.lower():
                    results.append({
                        "cube_id": node.get("id", ""),
                        "name": name,
                        "path": node.get("path", ""),
                        "type": node.get("type", ""),
                    })
                children = node.get("children", [])
                if children and depth < 3:
                    search_in_tree(children, depth + 1)

        search_in_tree(cube_tree)
        return results[:20]  # 最多返回20条

    async def eps_get_data(
        self,
        cube_id: str,
        dimensions: dict | None = None,
    ) -> dict | None:
        """获取EPS数据立方体数据.

        Args:
            cube_id: 数据立方体ID.
            dimensions: 维度筛选，如{"region": ["北京", "上海"], "year": ["2020", "2021"]}.

        Returns:
            数据字典，含行列标签和数值.
        """
        if not self._eps_sid:
            sid = await self.eps_login()
            if not sid:
                return None

        client = await self._get_client()
        eps_api = build_vpn_url("https://www.epsnet.com.cn/api/cube/getData")

        payload = {
            "sid": self._eps_sid,
            "cubeId": cube_id,
        }
        if dimensions:
            payload.update(dimensions)

        try:
            resp = await client.post(eps_api, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {})
        except Exception as e:
            logger.warning(f"EPS获取数据失败: {e}")
        return None
