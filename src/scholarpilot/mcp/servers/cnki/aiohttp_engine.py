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


def _urlencode_body(payload: dict[str, str]) -> str:
    """将参数字典序列化为 CNKI 接受的原始表单体.

    与已验证的 httpx 直连方案保持一致的编码：QueryJson 内中文不预编码
    （CNKI 该接口对 aiohttp 默认 urlencode 编码不兼容，会报
    "pageSize 校验失败"）。直接用 "k=v&k=v" 原始拼接，保留 UTF-8 中文。
    """
    return "&".join(f"{k}={v}" for k, v in payload.items())


# ===== CNKI 来源类别映射 =====
# 来源: papertracker_rich/literature_fetcher/engines/cnki.py 已验证的映射
# CNKI 高级检索页面 "来源类别" 复选框对应的 QueryJson 字段
SOURCE_CATEGORY_MAPPING: dict[str, dict[str, str]] = {
    "SCI":    {"Field": "SI",   "Value": "Y",    "Title": "SCI来源期刊"},
    "EI":     {"Field": "EI",   "Value": "Y",    "Title": "EI来源期刊"},
    "北大核心": {"Field": "HX",  "Value": "Y",    "Title": "北大核心"},
    "CSSCI":  {"Field": "CSI",  "Value": "Y",    "Title": "CSSCI"},
    "CSCD":   {"Field": "CSD",  "Value": "Y",    "Title": "CSCD"},
    "AMI":    {"Field": "AMI",  "Value": "P13",  "Title": "AMI"},
    "WJCI":   {"Field": "LYBSM","Value": "P12",  "Title": "WJCI"},
}

# 默认核心期刊来源类别（用户指定的7类）
DEFAULT_SOURCE_CATEGORIES: list[str] = [
    "SCI", "北大核心", "CSSCI", "EI", "CSCD", "AMI", "WJCI",
]

# CNKI 学术期刊库 productStr (来源: 浏览器真实检索请求实测, 2026-08-27)
CNKI_JOURNAL_PRODUCT_STR = (
    "YSTT4HG0,LSTPFY1C,RMJLXHZ3,JQIRZIYA,EMRPGLPA,J708GVCE,JUP3MUPD,"
    "1UR4K4HZ,BPBAFJ5S,MPMFIG1A,WQ0UVIAA,NB3BWEHK,XVLO76FD,HR1YT1Z9,"
    "BLZOG7CK,PWFIRAGL,NN3FJMUV,NLBO1Z6R,"
)


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

    来源类别筛选：
    - 通过 ControlGroup 的 ".extend-tit-checklist" 子项实现
    - 每个来源类别是一个独立 Item，Logic=1（OR 关系）
    - 支持的类别: SCI/EI/北大核心/CSSCI/CSCD/AMI/WJCI
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
        vpn_mode: bool = False,
    ) -> None:
        """初始化 CNKI aiohttp 引擎.

        Args:
            cookies: Cookie 字典。
            cookie_str: Cookie 字符串（如 "key1=val1; key2=val2"）。
            timeout: 请求超时秒数。
            vpn_mode: VPN 机构访问模式。启用后通过 VPN 代理主机访问
                      CNKI，并加载已验证的机构窄 Cookie 集合 + 实时 TWFID。
        """
        self._cookies: dict[str, str] = {}
        self.timeout = timeout
        self.vpn_mode = vpn_mode
        self._lib_checked: bool = False  # 统一入口本次进程是否已探活

        # URL 主机：VPN 模式切到机构代理主机
        self._brief_grid_url = self.BRIEF_GRID_URL
        self._adv_search_url = self.ADV_SEARCH_URL
        self._group_result_url = self.GROUP_RESULT_URL

        if vpn_mode:
            # VPN 模式: 机构代理主机 + 已验证窄 Cookie 集合(TWFID合并)
            # 优先加载 .scholar/empirical_auth.json 中 cnki_vpn 凭据，
            # 缺失时回退到 FALLBACK_COOKIE + 实时 TWFID。
            from scholarpilot.skills.vpn_database_access import build_vpn_url
            self._brief_grid_url = build_vpn_url(self.BRIEF_GRID_URL)
            self._adv_search_url = build_vpn_url(self.ADV_SEARCH_URL)
            self._group_result_url = build_vpn_url(self.GROUP_RESULT_URL)
            self._cookies = self._load_vpn_credential()
            logger.info(
                "CNKI engine in VPN mode: host=%s, cookie_keys=%s",
                self.host, list(self._cookies.keys()),
            )
        elif cookies:
            self._cookies = cookies
        elif cookie_str:
            self._cookies = self._parse_cookie_string(cookie_str)
        else:
            # 尝试从缓存加载
            self.load_cookie_from_cache()

    # ===== VPN 凭据加载 =====

    @property
    def host(self) -> str:
        """当前使用的服务主机（含协议）."""
        match = re.match(r"https?://[^/]+", self._brief_grid_url)
        return match.group(0) if match else "https://kns.cnki.net"

    @staticmethod
    def _find_project_root() -> Path | None:
        """向上定位含 .scholar/empirical_auth.json 的项目根目录."""
        candidates = [
            Path.cwd(),
            Path(__file__).resolve().parent,
        ]
        # 从包路径向上逐级探测
        p = Path(__file__).resolve()
        for _ in range(8):
            p = p.parent
            if p.joinpath(".scholar").exists():
                candidates.append(p)
        seen: set[Path] = set()
        for cand in candidates:
            cand = cand.resolve()
            if cand in seen:
                continue
            seen.add(cand)
            auth = cand / ".scholar" / "empirical_auth.json"
            if auth.exists():
                return cand
        return None

    def _load_vpn_credential(self) -> dict[str, str]:
        """加载已验证的 CNKI VPN 窄 Cookie 集合 + 实时 TWFID.

        优先从 .scholar/empirical_auth.json 的 cnki_vpn 项读取；
        若 ECAgent 可用则读取实时 TWFID 并覆盖。均不可用时回退 FALLBACK_COOKIE。
        """
        cookies: dict[str, str] = {}

        project_root = self._find_project_root()
        auth_path = (
            project_root / ".scholar" / "empirical_auth.json"
            if project_root else None
        )
        if auth_path and auth_path.exists():
            try:
                data = json.loads(auth_path.read_text(encoding="utf-8"))
                entry = data.get("databases", {}).get("cnki_vpn") or data.get("cnki_vpn")
                if entry:
                    cookies = dict(entry.get("cookies", {}))
                    logger.info(
                        "Loaded CNKI VPN credential from %s: %s",
                        auth_path.name, list(cookies.keys()),
                    )
            except Exception as e:
                logger.warning(f"Failed to load CNKI VPN credential: {e}")

        if not cookies:
            # 回退到 FALLBACK_COOKIE（客户端标识）
            cookies = dict(self.FALLBACK_COOKIE)
            logger.info("Using fallback CNKI VPN cookie (no stored credential)")

        # 合并实时 TWFID（VPN 网关会话凭证，代理层必需）
        try:
            from scholarpilot.utils.browser_auth_refresher import (
                BrowserAuthRefresher,
            )
            twfid = BrowserAuthRefresher().read_realtime_twfid()
            if twfid:
                cookies["TWFID"] = twfid
                logger.info("Merged real-time TWFID into CNKI VPN cookie")
        except Exception as e:
            logger.warning(f"Failed to merge real-time TWFID: {e}")

        return cookies

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

    # ===== 检索式构建 =====

    # CNKI 专业检索字段代码（参考 CNKI 检索手册 1.2.5.2）
    FIELD_CODES = {
        "SU": "主题", "TI": "题名", "KY": "关键词", "AB": "摘要",
        "FT": "全文", "AU": "作者", "FI": "第一责任人", "RP": "通讯作者",
        "AF": "机构", "JN": "文献来源", "RF": "参考文献", "YE": "年",
        "FU": "基金", "CLC": "分类号", "SN": "ISSN", "CN": "统一刊号",
        "IB": "ISBN", "CF": "被引频次",
    }

    @staticmethod
    def build_query(
        topic: str,
        region: str = "",
        content: str = "",
        year_start: str = "",
        year_end: str = "",
    ) -> str:
        """构建 CNKI 专业检索式.

        根据 CNKI 检索手册（1.2.5），使用专业检索语法：
        - SU %= '关键词'  主题相关匹配（推荐）
        - AU = '作者名'   作者精确匹配
        - KY = '关键词'   关键词精确匹配
        - TI % '篇名'    篇名模糊匹配
        - YE BETWEEN('2022','2023')  年份范围
        - CF > 0         被引频次筛选
        - 字段间用 AND/OR/NOT 连接
        - 同字段内用 *（与）/ +（或）/ -（非）组合

        Args:
            topic: 核心主题。
            region: 研究区域。
            content: 研究内容。
            year_start: 起始年份（可选，也可在 search 方法中指定）。
            year_end: 结束年份。

        Returns:
            CNKI 检索式字符串，如 "SU %= '数字经济' AND SU %= '绿色创新'".
        """
        # CNKI SU%= 对长句支持差，必须拆成 4-8 字核心关键词
        def extract_core(text: str, max_len: int = 8) -> str:
            if not text:
                return ""
            text = text.strip()
            # 若已是空格分隔的关键词，直接使用（外部已提取）
            if " " in text:
                return text
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
            # 空格分隔的关键词，每个单独作为 SU %= 条件
            if " " in core_topic:
                for kw in core_topic.split():
                    if kw.strip():
                        parts.append(f"SU %= '{kw.strip()}'")
            else:
                parts.append(f"SU %= '{core_topic}'")
        if core_content and core_content not in core_topic:
            if " " in core_content:
                for kw in core_content.split():
                    if kw.strip() and kw.strip() not in core_topic:
                        parts.append(f"SU %= '{kw.strip()}'")
            else:
                parts.append(f"SU %= '{core_content}'")
        return " AND ".join(parts) if parts else f"SU %= '{core_topic}'"

    @staticmethod
    def build_professional_query(
        subject: str = "",
        title: str = "",
        keyword: str = "",
        author: str = "",
        affiliation: str = "",
        journal: str = "",
        year_start: str = "",
        year_end: str = "",
        fund: str = "",
        min_citations: int = 0,
    ) -> str:
        """构建 CNKI 专业检索式（完整字段支持）.

        根据 CNKI 检索手册 1.2.5，支持多字段组合检索：
        - 主题（SU）: 相关匹配 %=
        - 篇名（TI）: 模糊匹配 %
        - 关键词（KY）: 精确匹配 =
        - 作者（AU）: 精确匹配 =
        - 机构（AF）: 精确匹配 =
        - 文献来源（JN）: 精确匹配 =
        - 年份（YE）: BETWEEN
        - 基金（FU）: 精确匹配 =
        - 被引频次（CF）: > >= < <=

        同字段内支持复合运算符：
        - * : 同时包含（AND）
        - + : 包含其一（OR）
        - - : 包含前者但不包含后者（NOT）

        Args:
            subject: 主题词（支持 * + - 组合）.
            title: 篇名词.
            keyword: 关键词.
            author: 作者名.
            affiliation: 机构名.
            journal: 文献来源（期刊名）.
            year_start: 起始年份.
            year_end: 结束年份.
            fund: 基金名称.
            min_citations: 最低被引频次（0=不筛选）.

        Returns:
            CNKI 专业检索式字符串.

        Examples:
            >>> build_professional_query(subject="数字经济 * 绿色创新", author="王磊", year_start="2022", year_end="2023")
            "SU %= '数字经济 * 绿色创新' AND AU = '王磊' AND YE BETWEEN ('2022', '2023')"
        """
        parts = []

        if subject:
            parts.append(f"SU %= '{subject}'")
        if title:
            parts.append(f"TI % '{title}'")
        if keyword:
            parts.append(f"KY = '{keyword}'")
        if author:
            parts.append(f"AU = '{author}'")
        if affiliation:
            parts.append(f"AF = '{affiliation}'")
        if journal:
            parts.append(f"JN = '{journal}'")
        if fund:
            parts.append(f"FU = '{fund}'")

        # 年份范围
        if year_start and year_end:
            if year_start == year_end:
                parts.append(f"YE = '{year_start}'")
            else:
                parts.append(f"YE BETWEEN ('{year_start}', '{year_end}')")
        elif year_start:
            parts.append(f"YE >= '{year_start}'")
        elif year_end:
            parts.append(f"YE <= '{year_end}'")

        # 被引频次筛选
        if min_citations > 0:
            parts.append(f"CF >= {min_citations}")

        return " AND ".join(parts) if parts else "SU %= ''"

    @staticmethod
    def build_query_json(
        search_query: str,
        year_start: str = "2020",
        year_end: str = "2026",
        author: str = "",
        journal: str = "",
        affiliation: str = "",
        min_citations: int = 0,
        source_categories: list[str] | None = None,
    ) -> str:
        """构建 QueryJson 参数（复刻 papertracker_social 格式）.

        根据 CNKI 检索手册，每个检索字段对应一个独立的 QGroup 条目：
        - Subject (EXPERT): 主题检索式
        - Author (AU): 作者精确匹配
        - Journal (JN): 文献来源精确匹配
        - Affiliation (AF): 机构精确匹配
        - CitedFreq (CF): 被引频次筛选
        - ControlGroup: 年份范围 + 来源类别筛选

        Args:
            search_query: CNKI 检索式（如 SU %= '地方政府债务'）。
            year_start: 起始年份。
            year_end: 结束年份。
            author: 作者名（AU= 精确匹配）。
            journal: 文献来源/期刊名（JN= 精确匹配）。
            affiliation: 机构名（AF= 精确匹配）。
            min_citations: 最低被引频次（0=不筛选）。
            source_categories: 来源类别列表（如 ["SCI","北大核心","CSSCI"]）。
                支持的类别见 SOURCE_CATEGORY_MAPPING。
                None 表示不筛选来源类别（返回全部期刊）。
                空列表等同 None。

        Returns:
            JSON 字符串。
        """
        q_group = [
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
        ]

        # 作者检索字段（AU= 精确匹配）
        if author:
            q_group.append({
                "Key": "Author",
                "Title": "作者",
                "Logic": 0,
                "Items": [
                    {
                        "Key": "Author",
                        "Title": "",
                        "Logic": 0,
                        "Field": "AU",
                        "Operator": 0,
                        "Value": author,
                        "Value2": "",
                    }
                ],
                "ChildItems": [],
            })

        # 文献来源检索字段（JN= 精确匹配）
        if journal:
            q_group.append({
                "Key": "Journal",
                "Title": "文献来源",
                "Logic": 0,
                "Items": [
                    {
                        "Key": "Journal",
                        "Title": "",
                        "Logic": 0,
                        "Field": "JN",
                        "Operator": 0,
                        "Value": journal,
                        "Value2": "",
                    }
                ],
                "ChildItems": [],
            })

        # 机构检索字段（AF= 精确匹配）
        if affiliation:
            q_group.append({
                "Key": "Affiliation",
                "Title": "机构",
                "Logic": 0,
                "Items": [
                    {
                        "Key": "Affiliation",
                        "Title": "",
                        "Logic": 0,
                        "Field": "AF",
                        "Operator": 0,
                        "Value": affiliation,
                        "Value2": "",
                    }
                ],
                "ChildItems": [],
            })

        # 被引频次筛选（CF >= N）
        if min_citations > 0:
            q_group.append({
                "Key": "CitedFreq",
                "Title": "被引频次",
                "Logic": 0,
                "Items": [
                    {
                        "Key": "CitedFreq",
                        "Title": "",
                        "Logic": 0,
                        "Field": "CF",
                        "Operator": 3,  # >=
                        "Value": str(min_citations),
                        "Value2": "",
                    }
                ],
                "ChildItems": [],
            })

        # ControlGroup 子项: 年份范围 + 来源类别筛选
        control_children = [
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
        ]

        # 来源类别筛选: 每个类别一个 Item, Logic=1 (OR 关系)
        # 来源: papertracker_rich/literature_fetcher/engines/cnki.py 已验证
        if source_categories:
            source_items = []
            for cat in source_categories:
                mapping = SOURCE_CATEGORY_MAPPING.get(cat)
                if mapping:
                    source_items.append({
                        "Key": 0,
                        "Title": mapping["Title"],
                        "Logic": 1,  # OR: 满足任一来源类别即可
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

        q_group.append({
            "Key": "ControlGroup",
            "Title": "",
            "Logic": 0,
            "Items": [],
            "ChildItems": control_children,
        })

        query_json = {
            "Platform": "",
            "Resource": "JOURNAL",
            "Classid": "YSTT4HG0",
            "Products": "",
            "QNode": {
                "QGroup": q_group,
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

    @staticmethod
    def _build_v2_query(
        keyword: str,
        year_start: str,
        year_end: str,
    ) -> str:
        """构建 SearchType=2 极简检索 QueryJson（经验证可返回数据的格式）.

        关键差异 vs build_query_json：
        - SearchType=2（不是 4）
        - 主题项用 TOPRANK 简洁格式直接放关键词（非 DEXPERT 检索式）
        - 年份通过第二个 QGroup 的 ControlGroup(.tit-startend-yearbox) 表达

        实测（2026-08-27）：极简返回 70,644 条；+Control年份返回 3,795 条。

        Args:
            keyword: 检索关键词（原始词）。
            year_start: 起始年份。
            year_end: 结束年份。
        """
        subject = {
            "Key": "Subject", "Title": "", "Logic": 0,
            "Items": [{
                "Field": "SU", "Value": keyword,
                "Operator": "TOPRANK", "Logic": 0, "Title": "主题",
            }],
            "ChildItems": [],
        }
        year_cc = {
            "Key": ".tit-startend-yearbox", "Title": "", "Logic": 0,
            "Items": [{
                "Key": ".tit-startend-yearbox", "Title": "出版年度",
                "Logic": 0, "Field": "YE", "Operator": 7,
                "Value": year_start, "Value2": year_end,
            }],
            "ChildItems": [],
        }
        q_group = [subject, {
            "Key": "ControlGroup", "Title": "", "Logic": 0,
            "Items": [], "ChildItems": [year_cc],
        }]
        query_json = {
            "Platform": "", "Resource": "JOURNAL", "Classid": "YSTT4HG0",
            "Products": "", "QNode": {"QGroup": q_group},
            "ExScope": 1, "SimpTrad": "0", "SearchType": 2,
            "Rlang": "CHINESE", "KuaKuCode": "", "Expands": {},
            "View": "changeDBCh", "SearchFrom": 1,
        }
        return json.dumps(query_json, ensure_ascii=False)

    @staticmethod
    def _build_search_from(
        year_start: str,
        year_end: str,
        source_categories: list[str] | None = None,
    ) -> str:
        """构建 searchFrom 字符串.

        searchFrom 是 CNKI 表单提交时的描述性参数,记录当前筛选状态.
        来源类别部分需要列出已选类别,未选时显示"全部期刊".

        Args:
            year_start: 起始年份.
            year_end: 结束年份.
            source_categories: 来源类别列表.

        Returns:
            searchFrom 字符串.
        """
        if source_categories:
            # 列出已选来源类别名称
            cat_names = []
            for cat in source_categories:
                mapping = SOURCE_CATEGORY_MAPPING.get(cat)
                if mapping:
                    cat_names.append(mapping["Title"])
            source_str = ",".join(cat_names) if cat_names else "全部期刊"
        else:
            source_str = "全部期刊"

        return (
            f"资源范围：学术期刊;  中英文扩展;  "
            f"时间范围：出版年度：{year_start} 到 {year_end},"
            f"更新时间：不限;  "
            f"来源类别：{source_str}; "
        )

    # ===== 检索执行 =====

    async def _warmup_session(self, session: aiohttp.ClientSession) -> None:
        """VPN 模式预热: 访问 AdvSearch 页面获取机构 Session Cookie.

        CNKI 通过机构 IP 自动认证时,访问 AdvSearch 页面会发放
        Session Cookie(SID_kns_new, KNS2COOKIE)。预热后
        session.cookie_jar 会自动保存这些 Cookie,后续检索请求
        会自动携带(与 self._cookies 中的 FALLBACK_COOKIE 合并)。

        Args:
            session: aiohttp ClientSession 对象.
        """
        warmup_url = self._adv_search_url
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        try:
            async with session.get(
                warmup_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=True,
            ) as response:
                # session.cookie_jar 自动保存响应中的 Cookie
                logger.debug(
                    f"CNKI warmup: HTTP {response.status}, "
                    f"cookies acquired: {len(session.cookie_jar)}"
                )
        except Exception as e:
            logger.warning(f"CNKI warmup failed (non-fatal): {e}")

    def _detect_institutional_auth(self, html: str) -> bool:
        """检测响应中是否含机构认证标识.

        VPN 模式下,CNKI 通过机构 IP 自动认证。响应中通常包含
        机构名称或"机构用户"等标识。

        Args:
            html: CNKI 响应 HTML.

        Returns:
            True 如果检测到机构认证标识.
        """
        html_lower = html.lower()
        institutional_indicators = [
            "institutional",
            "机构用户",
            "ip登录",
            "ip 登录",
            "单位用户",
        ]
        for indicator in institutional_indicators:
            if indicator.lower() in html_lower:
                logger.debug(
                    f"CNKI institutional auth detected (indicator: {indicator})"
                )
                return True
        return False

    async def search(
        self,
        query: str,
        limit: int = 20,
        page: int = 1,
        year_start: str = "2020",
        year_end: str = "2026",
        sort_field: str = "FFD",
        author: str = "",
        journal: str = "",
        affiliation: str = "",
        min_citations: int = 0,
        source_categories: list[str] | None = None,
    ) -> CNKISearchResult:
        """执行 CNKI 检索.

        支持 CNKI 检索手册中的多种筛选条件：
        - 主题检索（SU %=）
        - 作者检索（AU =）
        - 机构检索（AF =）
        - 文献来源检索（JN =）
        - 年份范围（YE BETWEEN）
        - 被引频次筛选（CF >=）
        - 来源类别筛选（SCI/北大核心/CSSCI/EI/CSCD/AMI/WJCI）
        - 排序：FFD=发表时间, RU=被引, 空=相关度

        Args:
            query: 检索词或检索式。如果是纯文本（不含 SU %=），自动构建检索式。
            limit: 返回数量（最大 50）。
            page: 页码。
            year_start: 起始年份。
            year_end: 结束年份。
            sort_field: 排序字段（FFD=发表时间, RU=被引, 空=相关度）。
            author: 作者名（精确匹配 AU=，用于引用验证）。
            journal: 文献来源/期刊名（精确匹配 JN=）。
            affiliation: 机构名（精确匹配 AF=）。
            min_citations: 最低被引频次（0=不筛选）。
            source_categories: 来源类别列表（如 ["SCI","北大核心","CSSCI"]）。
                None 表示不筛选来源类别（返回全部期刊）。

        Returns:
            CNKISearchResult: 检索结果。
        """
        # 构建检索式
        # 检测是否已是专业检索式（含 SU %= / AU = / KY = 等语法）
        is_pro = any(
            f"{code} %=" in query or f"{code} =" in query or f"{code} %" in query
            for code in ["SU", "TI", "KY", "AB", "AU", "AF", "JN", "FT", "FU"]
        )
        if is_pro:
            search_query = query
        elif "SU%=" in query or "TI%=" in query:
            # 兼容旧格式 SU%= → 转为新格式 SU %=
            search_query = query.replace("SU%=", "SU %=").replace("TI%=", "TI %")
        else:
            # 纯文本 → 自动构建检索式
            search_query = self.build_query(query)

        # 额外筛选条件通过 QGroup 传入（不拼进检索式字符串）
        # 这样每个字段是独立的 QGroup 条目，CNKI API 能正确解析

        logger.info(
            "[CNKI search] 检索参数: query='%s', page=%d, limit=%d, "
            "year=%s-%s, sort=%s, author='%s', journal='%s', "
            "affiliation='%s', min_citations=%d, source_categories=%s",
            query, page, limit, year_start, year_end, sort_field,
            author, journal, affiliation, min_citations, source_categories,
        )
        logger.debug("[CNKI search] 构建的检索式: %s", search_query)

        query_json = self._build_v2_query(query, year_start, year_end)

        # 打印 QueryJson 关键结构（DEBUG 级别）
        try:
            qj_parsed = json.loads(query_json)
            q_group = qj_parsed.get("QNode", {}).get("QGroup", [])
            logger.debug(
                "[CNKI search] QueryJson QGroup 数量: %d, "
                "各组 Key: %s",
                len(q_group),
                [g.get("Key") for g in q_group],
            )
            # 详细打印 ControlGroup 的来源类别子项
            for g in q_group:
                if g.get("Key") == "ControlGroup":
                    children = g.get("ChildItems", [])
                    logger.debug(
                        "[CNKI search] ControlGroup ChildItems 数量: %d",
                        len(children),
                    )
                    for i, child in enumerate(children):
                        items = child.get("Items", [])
                        if child.get("Key") == ".extend-tit-checklist":
                            cat_titles = [
                                it.get("Title", "") for it in items
                            ]
                            cat_fields = [
                                f"{it.get('Field','')}={it.get('Value','')}"
                                for it in items
                            ]
                            logger.info(
                                "[CNKI search] 来源类别筛选: %d 个类别, "
                                "titles=%s, fields=%s",
                                len(items), cat_titles, cat_fields,
                            )
                        else:
                            logger.debug(
                                "[CNKI search] ControlGroup child[%d] "
                                "Key='%s', items=%d",
                                i, child.get("Key"), len(items),
                            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("[CNKI search] QueryJson 解析失败: %s", e)

        search_from = self._build_search_from(
            year_start, year_end, source_categories,
        )
        logger.info("[CNKI search] searchFrom: %s", search_from)

        post_data = {
            "boolSearch": "true",
            "QueryJson": query_json,
            "pageNum": str(page),
            "pageSize": str(min(limit, 50)),
            "dstyle": "listmode",
            "productStr": CNKI_JOURNAL_PRODUCT_STR,
            "aside": f"(主题：{query})",
            "searchFrom": "资源范围：学术期刊",
            "subject": "",
            "language": "",
            "uniplatform": "",
            "CurPage": str(page),
        }

        # 结果页 Referer（与浏览器真实请求对齐，需 URL 编码中文）
        try:
            from urllib.parse import quote
            referer = (
                f"{self.host}/kns8s/defaultresult/index"
                f"?kw={quote(query)}&korder=SU&dbcode=CJFQ"
            )
        except Exception:
            referer = self._adv_search_url

        headers = {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
        }
        grid_url = self._brief_grid_url + "?sf_request_type=ajax"

        logger.info(
            "[CNKI search] 发送请求: URL=%s, pageNum=%s, pageSize=%s, "
            "vpn_mode=%s, cookie_keys=%s",
            grid_url,
            post_data["pageNum"], post_data["pageSize"],
            self.vpn_mode,
            list(self._cookies.keys())[:5] if self._cookies else "none",
        )

        try:
            configure_no_proxy()
            # 统一入口探活：操作前先经图书馆门户建立会话上下文（一次进程内缓存）
            if self.vpn_mode and not self._lib_checked:
                try:
                    from scholarpilot.skills.vpn_database_access import (
                        verify_library_entry,
                    )
                    probe = verify_library_entry()
                    self._lib_checked = True
                    if probe["ok"]:
                        logger.info("[CNKI VPN] 统一入口就绪 (TWFID=%s...)",
                                    probe.get("twfid", "")[:6])
                    else:
                        logger.warning("[CNKI VPN] 统一入口探活失败: %s",
                                       probe.get("error"))
                except Exception as e:
                    logger.warning(f"[CNKI VPN] 统一入口探活异常: {e}")
            async with aiohttp.ClientSession(trust_env=False) as session:
                # VPN 模式预热: 访问 AdvSearch 页面获取机构 Session Cookie
                if self.vpn_mode:
                    logger.debug("[CNKI search] VPN 模式: 预热 Session")
                    await self._warmup_session(session)

                async with session.post(
                    grid_url,
                    data=_urlencode_body(post_data),
                    headers=headers,
                    cookies=self._cookies,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    html = await response.text()
                    status_code = response.status

                    logger.info(
                        "[CNKI search] 响应: HTTP %d, HTML 长度=%d",
                        status_code, len(html),
                    )

                    # 检测验证码
                    if "captcha" in html.lower() or "verify" in html.lower():
                        if self.vpn_mode:
                            # VPN 模式下验证码较少见,记录但不回退到 Cookie
                            logger.warning(
                                "CNKI returned captcha in VPN mode. "
                                "Institutional IP may not be recognized."
                            )
                        else:
                            logger.warning(
                                "CNKI returned captcha/verify page. "
                                "Cookie may be invalid."
                            )
                        return CNKISearchResult(query=query, total_count=0)

                    # VPN 模式下检测机构认证是否生效
                    if self.vpn_mode:
                        self._detect_institutional_auth(html)

                    result = self._parse_grid_html(html, query)
                    result.raw_response = html[:5000]

                    logger.info(
                        "[CNKI search] 检索完成: query='%s', "
                        "total_count=%d, returned=%d",
                        query, result.total_count, len(result.papers),
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