"""EasyConnect VPN 连通性检测与会话管理模块.

EasyConnect 是深信服(Sangfor)SSL VPN 客户端,工作在 IP 网络层
(虚拟网卡 + 路由表修改),非 HTTP 代理。本模块检测 VPN 是否已连接
且机构资源可达。

与现有网络配置的关系:
- trust_env=False / proxy=None 工作在 HTTP 应用层,仅禁用 HTTP 代理环境变量
- EasyConnect VPN 工作在 IP 网络层,通过虚拟网卡劫持流量
- 两者处于不同层级,天然兼容,Python HTTP 客户端自动遵循 VPN 路由

SSE 心跳机制:
- EasyConnect 登录时建立到 VPN 服务器的 TCP 长连接 (通常端口 8444)
- SangforServiceClient 进程通过此连接持续发送心跳包,维持 VPN 隧道
- SSE 心跳由 VPN 客户端自动维护,Python 脚本无需手动发送
- 但数据库的 Web 会话会独立过期,需通过图书馆入口刷新

分通道模式说明:
- VPN 仅路由特定 IP 段 (如 202.201.80.x) 通过隧道
- CNKI/RESSET/CSMAR 等数据库走 VPN 隧道,IP 认证有效
- 图书馆网站 (library.lzufe.edu.cn) 不走 VPN 隧道,需单独登录
- ScienceDirect 等外文库可通过"不登录,直接访问"经 VPN 隧道访问

Usage:
    detector = EasyConnectDetector()
    status = await detector.check_vpn()
    if status.connected:
        print(f"VPN 已连接,SSE心跳: {status.sse_active}")
        print(f"可访问: {status.accessible_databases}")
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from scholarpilot.utils.network import configure_no_proxy

logger = logging.getLogger(__name__)


# ===== 数据模型 =====

@dataclass
class VPNStatus:
    """VPN 连接状态."""

    connected: bool = False
    """VPN 是否连通且机构资源可达."""

    accessible_databases: list[str] = field(default_factory=list)
    """可达的数据库列表(如 ["cnki", "wanfang", "wos"])."""

    detected_ip: str = ""
    """检测到的出口 IP(用于判断是否机构 IP)."""

    check_time: str = ""
    """检测时间(ISO 格式)."""

    latency_ms: dict[str, float] = field(default_factory=dict)
    """各数据库的响应延迟(毫秒)."""

    error: str = ""
    """错误信息(VPN 未连接时)."""

    process_running: bool = False
    """EasyConnect 进程是否在运行."""

    sse_active: bool = False
    """SSE 心跳连接是否活跃(到 VPN 服务器的 TCP 长连接)."""

    sse_connection_count: int = 0
    """SSE 心跳连接数量."""

    session_status: dict[str, str] = field(default_factory=dict)
    """各数据库的会话状态(如 {"cnki": "ok", "sciencedirect": "need_login"})."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "accessible_databases": self.accessible_databases,
            "detected_ip": self.detected_ip,
            "check_time": self.check_time,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "process_running": self.process_running,
            "sse_active": self.sse_active,
            "sse_connection_count": self.sse_connection_count,
            "session_status": self.session_status,
        }


# ===== 数据库探测配置 =====

# 各数据库的探测端点和可达性判断逻辑
DATABASE_PROBES: dict[str, dict[str, Any]] = {
    "cnki": {
        "url": "https://kns.cnki.net/kns8s/defaultresult/index",
        "method": "GET",
        "timeout": 5,
        # CNKI 返回 200/302/403 都算可达(403 是反爬但 IP 可达)
        "success_codes": [200, 302, 303, 403],
        # 机构 IP 通常不返回登录页
        "login_indicator": ["login", "密码", "用户名"],
    },
    "wanfang": {
        "url": "https://www.wanfangdata.com.cn/index.html",
        "method": "GET",
        "timeout": 5,
        "success_codes": [200],
        # 机构用户访问时页面含机构名
        "login_indicator": ["请登录", "login required"],
    },
    "wos": {
        "url": "https://webofscience.clarivate.cn/wos/woscc/basic-search",
        "method": "GET",
        "timeout": 8,
        "success_codes": [200, 302],
        # WoS 通过 VPN 可达,但需要额外的 Shibboleth/SSO 登录认证
        # VPN 仅提供网络层可达性,不等于已认证
        # 认证状态需通过 WoS 引擎的 SID/API Key 检查
        "login_indicator": ["session expired", "institutional access"],
    },
}

# EasyConnect 进程名(Windows)
EASYCONNECT_PROCESS_NAMES = [
    "EasyConnect.exe",
    "SangforCSClient.exe",
    "SangforVpnClient.exe",
    "SangforServiceClient.exe",
    "ECAgent.exe",
]

# VPN 服务器地址 (兰州财经大学)
VPN_SERVER_IP = "202.201.87.130"
VPN_SERVER_PORT = 8444

# 图书馆数据库导航页
LIBRARY_PORTAL = "https://library.lzufe.edu.cn/databaseguide/web_dataBaseHome1"

# CNKI 财政专题数据库配置
CNKI_FINANCE_BASE = "https://szjk.cnki.net"
CNKI_FINANCE_DIMENSION_ID = "650f537ecab44e9aac409d7bba4c1384"


class EasyConnectDetector:
    """EasyConnect VPN 连通性检测器.

    采用三级渐进检测策略:
    1. 进程检测(瞬时): 检查 EasyConnect 进程是否运行
    2. 机构 IP 检测(快速): 向 CNKI 首页发起请求,检查响应
    3. 数据库可达性探测(完整): 并行探测各目标数据库

    所有检测请求复用现有 network.py 配置(trust_env=False),
    确保 HTTP 代理设置不干扰 VPN 路由。
    """

    def __init__(self, check_timeout: int = 10) -> None:
        """初始化检测器.

        Args:
            check_timeout: 单次检测请求的超时秒数.
        """
        self.check_timeout = check_timeout
        self._cache: VPNStatus | None = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 60.0  # 缓存 60 秒

    # ===== 第一级:进程检测 =====

    def _check_process_running(self) -> bool:
        """检查 EasyConnect 进程是否运行(仅 Windows).

        Returns:
            True 如果检测到 EasyConnect 相关进程.
        """
        if platform.system() != "Windows":
            # Linux/macOS: 检查 pgrep
            try:
                result = subprocess.run(
                    ["pgrep", "-f", "easyconnect"],
                    capture_output=True,
                    timeout=3,
                )
                return result.returncode == 0
            except Exception:
                return False

        try:
            # Windows: 使用 tasklist
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                encoding="gbk",
                errors="replace",
            )
            output = result.stdout.lower()
            for proc_name in EASYCONNECT_PROCESS_NAMES:
                if proc_name.lower() in output:
                    logger.debug(f"Found EasyConnect process: {proc_name}")
                    return True
            return False
        except Exception as e:
            logger.debug(f"Process check failed: {e}")
            return False

    def _check_route_table(self) -> bool:
        """检查路由表是否存在 EasyConnect 虚拟网卡路由(仅 Windows).

        Returns:
            True 如果检测到 Sangfor 虚拟网卡路由.
        """
        if platform.system() != "Windows":
            return False

        try:
            result = subprocess.run(
                ["route", "print"],
                capture_output=True,
                text=True,
                timeout=5,
                encoding="gbk",
                errors="replace",
            )
            output = result.stdout.lower()
            # Sangfor 虚拟网卡通常显示为 "Sangfor" 或 "SSL VPN"
            indicators = ["sangfor", "ssl vpn", "sangfor ssl vpn"]
            return any(ind in output for ind in indicators)
        except Exception as e:
            logger.debug(f"Route table check failed: {e}")
            return False

    def _check_sse_heartbeat(self) -> tuple[bool, int]:
        """检测 VPN SSE 心跳连接状态.

        EasyConnect VPN 客户端通过 SSE (Server-Sent Events) 机制持续向
        VPN 服务器发送心跳包,维持 VPN 隧道。这些连接是到 VPN 服务器的
        TCP 长连接 (通常在 8444 端口)。

        SSE 心跳由 SangforServiceClient 进程自动维护,无需手动发送。
        本方法仅检测连接是否存在,不发送任何数据。

        Returns:
            (SSE 是否活跃, 连接数量).
        """
        if platform.system() != "Windows":
            return False, 0

        try:
            # 使用 netstat 检测到 VPN 服务器的 ESTABLISHED 连接
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=10,
                encoding="gbk",
                errors="replace",
            )
            count = 0
            for line in result.stdout.split("\n"):
                line = line.strip()
                if "ESTABLISHED" in line and VPN_SERVER_IP in line:
                    count += 1

            if count > 0:
                logger.info(
                    f"SSE heartbeat active: {count} connections to "
                    f"{VPN_SERVER_IP}:{VPN_SERVER_PORT}"
                )
            else:
                logger.warning(
                    f"No SSE connections to VPN server {VPN_SERVER_IP}"
                )
            return count > 0, count
        except Exception as e:
            logger.debug(f"SSE heartbeat check failed: {e}")
            return False, 0

    # ===== 第二级:机构 IP 检测 =====

    async def _check_institutional_ip(self) -> tuple[bool, str]:
        """检测是否通过机构 IP 访问.

        向 CNKI 检索页发起请求,检查响应是否正常。
        CNKI 根路径直接 GET 会返回 403(反爬),使用检索页更可靠。

        Returns:
            (是否机构 IP 可达, 检测到的出口 IP 或错误信息).
        """
        configure_no_proxy()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        try:
            async with aiohttp.ClientSession(trust_env=False) as session:
                # 使用检索页而非根路径(根路径返回 403)
                async with session.get(
                    "https://kns.cnki.net/kns8s/defaultresult/index",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.check_timeout),
                    allow_redirects=False,
                ) as response:
                    # 200/302/303/403 都算可达
                    # 403 是 CNKI 反爬机制,但说明 IP 可达
                    if response.status in (200, 302, 303, 403):
                        # 检查是否被重定向到登录页
                        location = response.headers.get("Location", "")
                        if "login" in location.lower():
                            return False, "Redirected to login page"
                        return True, f"CNKI accessible (HTTP {response.status})"
                    return False, f"HTTP {response.status}"
        except asyncio.TimeoutError:
            return False, "Timeout"
        except aiohttp.ClientConnectorError as e:
            return False, f"Connection failed: {e}"
        except Exception as e:
            return False, str(e)

    # ===== 第三级:数据库可达性探测 =====

    async def _probe_database(self, db_name: str) -> tuple[bool, float]:
        """探测单个数据库是否可达.

        Args:
            db_name: 数据库名称(cnki/wanfang/wos).

        Returns:
            (是否可达, 响应延迟毫秒).
        """
        probe = DATABASE_PROBES.get(db_name)
        if not probe:
            return False, 0.0

        configure_no_proxy()
        start_time = time.monotonic()

        try:
            async with aiohttp.ClientSession(trust_env=False) as session:
                timeout = aiohttp.ClientTimeout(total=probe["timeout"])
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/144.0.0.0 Safari/537.36"
                    ),
                }

                if probe["method"] == "GET":
                    async with session.get(
                        probe["url"],
                        timeout=timeout,
                        headers=headers,
                        allow_redirects=True,
                    ) as response:
                        latency = (time.monotonic() - start_time) * 1000

                        if response.status in probe["success_codes"]:
                            # 检查是否是登录页
                            text = await response.text()
                            login_indicators = probe.get("login_indicator", [])
                            for indicator in login_indicators:
                                if indicator.lower() in text.lower():
                                    logger.debug(
                                        f"{db_name}: reachable but shows login "
                                        f"(indicator: {indicator})"
                                    )
                                    return False, latency
                            logger.debug(
                                f"{db_name}: accessible ({latency:.0f}ms)"
                            )
                            return True, latency
                        logger.debug(
                            f"{db_name}: HTTP {response.status} ({latency:.0f}ms)"
                        )
                        return False, latency
        except asyncio.TimeoutError:
            latency = (time.monotonic() - start_time) * 1000
            logger.debug(f"{db_name}: timeout ({latency:.0f}ms)")
            return False, latency
        except Exception as e:
            latency = (time.monotonic() - start_time) * 1000
            logger.debug(f"{db_name}: error - {e} ({latency:.0f}ms)")
            return False, latency

    async def _probe_all_databases(
        self, databases: list[str]
    ) -> dict[str, tuple[bool, float]]:
        """并行探测多个数据库.

        Args:
            databases: 数据库名称列表.

        Returns:
            {db_name: (is_accessible, latency_ms)} 字典.
        """
        tasks = {db: self._probe_database(db) for db in databases}
        results = {}

        # 并行探测
        completed = await asyncio.gather(
            *tasks.values(), return_exceptions=True
        )

        for db_name, result in zip(tasks.keys(), completed):
            if isinstance(result, Exception):
                results[db_name] = (False, 0.0)
            else:
                results[db_name] = result

        return results

    # ===== 公共接口 =====

    async def check_vpn(
        self,
        databases: list[str] | None = None,
        use_cache: bool = True,
    ) -> VPNStatus:
        """检测 VPN 连通性(三级渐进检测).

        检测流程:
        1. 进程检测: EasyConnect 是否运行 + 路由表是否有虚拟网卡
        2. 机构 IP 检测: CNKI 首页是否可达
        3. 数据库可达性探测: 并行探测各目标数据库

        Args:
            databases: 要探测的数据库列表,默认 ["cnki", "wanfang", "wos"].
            use_cache: 是否使用缓存(60 秒 TTL).

        Returns:
            VPNStatus: VPN 连接状态.
        """
        # 缓存检查
        if use_cache and self._cache and self._is_cache_valid():
            logger.debug("Using cached VPN status")
            return self._cache

        if databases is None:
            databases = ["cnki", "wanfang", "wos"]

        status = VPNStatus(check_time=time.strftime("%Y-%m-%dT%H:%M:%S"))

        # 第一级:进程检测
        status.process_running = self._check_process_running()
        route_ok = self._check_route_table()

        # SSE 心跳检测
        status.sse_active, status.sse_connection_count = self._check_sse_heartbeat()

        if not status.process_running and not route_ok:
            # 进程未运行,VPN 肯定未连接
            status.connected = False
            status.error = "EasyConnect process not running"
            self._update_cache(status)
            return status

        logger.info(
            f"EasyConnect process: {status.process_running}, "
            f"route: {route_ok}, "
            f"SSE: {status.sse_active} ({status.sse_connection_count} connections)"
        )

        # 第二级:机构 IP 检测
        ip_ok, ip_info = await self._check_institutional_ip()
        status.detected_ip = ip_info

        if not ip_ok:
            # 进程运行但机构 IP 不可达,可能 VPN 未登录成功
            status.connected = False
            status.error = f"Institutional IP not accessible: {ip_info}"
            self._update_cache(status)
            return status

        logger.info(f"Institutional IP accessible: {ip_info}")

        # 第三级:数据库可达性探测
        probe_results = await self._probe_all_databases(databases)

        accessible = []
        for db_name, (is_ok, latency) in probe_results.items():
            status.latency_ms[db_name] = round(latency, 1)
            if is_ok:
                accessible.append(db_name)

        status.accessible_databases = accessible
        # 至少一个数据库可达则认为 VPN 连接成功
        status.connected = len(accessible) > 0

        # 检测各数据库会话状态
        if status.connected:
            try:
                status.session_status = await self.check_session_status()
            except Exception as e:
                logger.debug(f"Session status check failed: {e}")

        if not status.connected:
            status.error = "No databases accessible despite VPN process running"

        logger.info(
            f"VPN check complete: connected={status.connected}, "
            f"accessible={status.accessible_databases}"
        )

        self._update_cache(status)
        return status

    async def check_database_access(self, db_name: str) -> bool:
        """检测单个数据库是否可通过 VPN 访问.

        Args:
            db_name: 数据库名称(cnki/wanfang/wos).

        Returns:
            True 如果数据库可达.
        """
        is_ok, _ = await self._probe_database(db_name)
        return is_ok

    async def check_cnki_finance_api(self) -> dict[str, Any]:
        """检测 CNKI 财政专题数据库 API 是否可访问.

        财政专题数据库通过 VPN IP 认证访问,无需图书馆入口登录。
        API 端点位于 szjk.cnki.net,使用 dimensionId 标识特定数据库。

        Returns:
            各 API 端点的检测结果.
        """
        import httpx

        configure_no_proxy()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": f"{CNKI_FINANCE_BASE}/dpi/search-center/",
        }

        results: dict[str, Any] = {}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=15.0),
            follow_redirects=True,
            proxy=None,
            trust_env=False,
            verify=False,
        ) as client:
            # Step 1: 访问首页获取 Cookie
            try:
                resp = await client.get(
                    f"{CNKI_FINANCE_BASE}/dpi/search-center/",
                    headers=headers,
                )
                cookies = dict(resp.cookies)
            except Exception as e:
                return {"error": f"Homepage access failed: {e}"}

            # Step 2: 测试 API 端点
            api_tests = [
                ("data_counts", "POST",
                 f"{CNKI_FINANCE_BASE}/numerical-db-building/select/getDataCounts",
                 {"dimensionId": CNKI_FINANCE_DIMENSION_ID}),
                ("frequency", "GET",
                 f"{CNKI_FINANCE_BASE}/numerical-db-building/select/getHaveDataOfFrequency",
                 {"dimensionId": CNKI_FINANCE_DIMENSION_ID}),
                ("indicator_tree", "POST",
                 f"{CNKI_FINANCE_BASE}/numerical-db-building/select/getProjectLibIndexTreeForArea",
                 {"dimensionId": CNKI_FINANCE_DIMENSION_ID,
                  "timeFrequency": "year", "regionCode": ""}),
            ]

            for name, method, url, params in api_tests:
                try:
                    if method == "GET":
                        r = await client.get(
                            url, params=params,
                            headers=headers, cookies=cookies,
                        )
                    else:
                        r = await client.post(
                            url, json=params,
                            headers={**headers, "Content-Type": "application/json"},
                            cookies=cookies,
                        )

                    if r.status_code == 200:
                        data = r.json()
                        success = data.get("success", data.get("code") == 200)
                        result = data.get("result") or data.get("data")
                        if success and result is not None:
                            count = len(result) if isinstance(result, list) else 1
                            results[name] = {"status": "ok", "count": count}
                        else:
                            msg = data.get("message", data.get("msg", ""))
                            results[name] = {"status": "api_error", "message": msg}
                    elif r.status_code == 403:
                        results[name] = {"status": "forbidden"}
                    else:
                        results[name] = {"status": "error", "code": r.status_code}
                except Exception as e:
                    results[name] = {"status": "failed", "error": str(e)[:80]}

        return results

    async def check_session_status(self) -> dict[str, str]:
        """检测各数据库的会话状态.

        区分两种状态:
        - "ok": 数据库可达且会话有效 (IP 认证生效)
        - "forbidden": 数据库可达但会话过期 (需刷新)
        - "failed": 数据库不可达 (VPN 可能断开)

        Returns:
            {数据库名: 状态} 字典.
        """
        import httpx

        configure_no_proxy()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        }

        checks = [
            ("cnki", "https://www.cnki.net/"),
            ("cnki_data", "https://data.cnki.net/"),
            ("cnki_finance", f"{CNKI_FINANCE_BASE}/dpi/search-center/"),
            ("wanfang", "https://www.wanfangdata.com.cn/"),
            ("resset", "https://db.resset.com/"),
            ("csmar", "https://data.csmar.com/"),
            ("eps", "https://www.epsnet.com.cn/"),
            ("sciencedirect", "https://www.sciencedirect.com/"),
            ("springer", "https://link.springer.com/"),
        ]

        status: dict[str, str] = {}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=True,
            proxy=None,
            trust_env=False,
            verify=False,
        ) as client:
            for name, url in checks:
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        # 检查是否需要登录
                        text_lower = resp.text.lower()
                        if "请登录" in resp.text or (
                            "login" in text_lower and "required" in text_lower
                        ):
                            status[name] = "need_login"
                        elif resp.status_code == 403 or "禁止访问" in resp.text:
                            status[name] = "forbidden"
                        else:
                            status[name] = "ok"
                    elif resp.status_code == 403:
                        status[name] = "forbidden"
                    else:
                        status[name] = f"http_{resp.status_code}"
                except Exception:
                    status[name] = "failed"

        return status

    async def wait_for_vpn(
        self,
        timeout: int = 120,
        poll_interval: int = 5,
        databases: list[str] | None = None,
    ) -> VPNStatus:
        """等待 VPN 连接(用于用户手动启动 EasyConnect 后的轮询).

        每隔 poll_interval 秒检测一次,直到 VPN 连接成功或超时.

        Args:
            timeout: 最大等待秒数.
            poll_interval: 轮询间隔秒数.
            databases: 要探测的数据库列表.

        Returns:
            VPNStatus: 最终的 VPN 连接状态.
        """
        if databases is None:
            databases = ["cnki", "wanfang", "wos"]

        deadline = time.monotonic() + timeout
        attempt = 0

        while time.monotonic() < deadline:
            attempt += 1
            # 等待时不使用缓存
            status = await self.check_vpn(
                databases=databases, use_cache=False
            )

            if status.connected:
                logger.info(
                    f"VPN connected after {attempt} attempts "
                    f"({time.monotonic() - (deadline - timeout):.0f}s)"
                )
                return status

            logger.debug(
                f"VPN not connected (attempt {attempt}), "
                f"retrying in {poll_interval}s..."
            )
            await asyncio.sleep(poll_interval)

        logger.warning(f"VPN wait timed out after {timeout}s")
        return status

    def invalidate_cache(self) -> None:
        """清除缓存,强制下次检测重新发起请求."""
        self._cache = None
        self._cache_time = 0.0

    def _is_cache_valid(self) -> bool:
        """检查缓存是否仍在 TTL 内."""
        if self._cache is None:
            return False
        return (time.time() - self._cache_time) < self._cache_ttl

    def _update_cache(self, status: VPNStatus) -> None:
        """更新缓存."""
        self._cache = status
        self._cache_time = time.time()


# ===== 便捷函数 =====

_async_detector: EasyConnectDetector | None = None


def get_vpn_detector() -> EasyConnectDetector:
    """获取全局 VPN 检测器单例.

    Returns:
        EasyConnectDetector 实例.
    """
    global _async_detector
    if _async_detector is None:
        _async_detector = EasyConnectDetector()
    return _async_detector


async def check_vpn_status(
    databases: list[str] | None = None,
) -> VPNStatus:
    """便捷函数:检测 VPN 状态.

    Args:
        databases: 要探测的数据库列表.

    Returns:
        VPNStatus: VPN 连接状态.
    """
    detector = get_vpn_detector()
    return await detector.check_vpn(databases=databases)


# ===== VPN Web 会话管理 (TWFID Cookie) =====


class VPNSessionManager:
    """EasyConnect VPN Web 会话管理器.

    EasyConnect 的 L3VPN 隧道（虚拟网卡）建立后，访问 *.vpn.lzufe.edu.cn
    的 Web 代理资源仍需要 TWFID Cookie 认证。本类负责：

    1. 检测 EasyConnect 隧道是否已建立（虚拟网卡 Up）
    2. 检查本地缓存的 TWFID Cookie 是否有效
    3. 若无效，通过 Playwright 启动浏览器让用户完成 Web 登录
    4. 登录成功后自动提取 TWFID Cookie 并缓存
    5. 提供 get_cookie_header() 供 httpx 注入

    Cookie 缓存路径: .scholar/vpn_session.json
    Cookie 有效期: 约 2 小时（可配置），过期后自动重新获取

    Usage::
        mgr = VPNSessionManager()
        cookie = await mgr.get_cookie_header()
        # cookie = "TWFID=de0103851a2ec145; language=zh_CN"
        headers = {"Cookie": cookie, ...}
        async with httpx.AsyncClient(headers=headers, ...) as c:
            resp = await c.get("http://www-pkulaw-com-s.vpn.lzufe.edu.cn:8118/...")
    """

    VPN_PORTAL = "https://vpn.lzufe.edu.cn:8444/"
    VPN_COOKIE_CACHE = ".scholar/vpn_session.json"
    CHROME_PROFILE = r"C:\Users\xuxiaobing\.trae-cn\work\vpn_chrome_profile"
    CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    # TWFID 有效期约 2 小时，保守设为 100 分钟
    COOKIE_TTL = 6000  # 秒

    def __init__(self, project_root: str = ".") -> None:
        self._project_root = project_root
        self._cookie_cache: dict[str, Any] | None = None
        self._cache_time: float = 0.0
        self._twfid: str | None = None
        self._full_cookie_str: str | None = None

    def _cookie_path(self) -> str:
        import os
        return os.path.join(self._project_root, self.VPN_COOKIE_CACHE)

    def _check_tunnel_up(self) -> bool:
        """检查 EasyConnect 隧道是否可用.

        通过尝试 TCP 连接 VPN 网关判断隧道状态，
        不依赖系统命令（netsh/powershell 在某些环境不可用）。
        """
        import socket
        try:
            sock = socket.create_connection(
                (VPN_SERVER_IP, VPN_SERVER_PORT), timeout=3,
            )
            sock.close()
            return True
        except Exception:
            return False

    def _load_cached_cookie(self) -> dict[str, Any] | None:
        """从本地文件加载缓存的 Cookie."""
        import json
        import os
        path = self._cookie_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            return None

    def _save_cookie_cache(self, cookies: list[dict], twfid: str) -> None:
        """保存 Cookie 到本地缓存文件."""
        import json
        import os
        path = self._cookie_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "twfid": twfid,
            "cookies": cookies,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "timestamp": time.time(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"VPN Cookie 已缓存到 {path}")

    def _is_cache_valid(self) -> bool:
        """检查缓存的 Cookie 是否仍在有效期内."""
        if self._cookie_cache is None:
            return False
        ts = self._cookie_cache.get("timestamp", 0)
        return (time.time() - ts) < self.COOKIE_TTL

    def _build_cookie_str(self, cookies: list[dict]) -> str:
        """从 Cookie 列表构建 Cookie 字符串（仅 vpn.lzufe.edu.cn 域）."""
        parts = []
        for c in cookies:
            domain = c.get("domain", "")
            if "vpn.lzufe.edu.cn" in domain or "lzufe" in domain:
                parts.append(f"{c['name']}={c['value']}")
        return "; ".join(parts)

    async def _verify_twfid(self, twfid: str) -> bool:
        """验证 TWFID 是否有效（发起测试请求）."""
        import httpx
        test_url = "http://www-pkulaw-com-s.vpn.lzufe.edu.cn:8118/law/chl"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": f"TWFID={twfid}",
        }
        try:
            async with httpx.AsyncClient(
                timeout=10, follow_redirects=False, verify=False,
                trust_env=False, headers=headers,
            ) as c:
                r = await c.get(test_url)
                # 200 = 有效，302 到 8444 = 无效
                return r.status_code == 200
        except Exception:
            return False

    async def _login_via_browser(self) -> tuple[str, list[dict]] | None:
        """通过 Playwright 启动浏览器完成 Web 登录，提取 TWFID.

        流程:
        1. 启动 Chrome（有头模式，持久化 profile）
        2. 打开 VPN 门户
        3. 等待用户手动登录（检测 URL 从 #!/login 变为 #!/service）
        4. 提取 TWFID Cookie

        Returns:
            (twfid, cookies_list) 或 None（失败/超时）
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright 未安装，无法自动登录 VPN Web 门户")
            return None

        import os
        os.makedirs(self.CHROME_PROFILE, exist_ok=True)

        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=self.CHROME_PROFILE,
                executable_path=self.CHROME_EXE,
                headless=False,
                ignore_https_errors=True,
                args=["--disable-blink-features=AutomationControlled"],
                no_viewport=True,
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            await page.goto(self.VPN_PORTAL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)

            if "#!/login" in page.url:
                logger.info("VPN 门户需要登录，请在浏览器窗口中完成登录...")
                # 等待登录（最多 5 分钟）
                for i in range(300):
                    await page.wait_for_timeout(1000)
                    try:
                        if "#!/service" in page.url or "#!/user_setting" in page.url:
                            logger.info("VPN Web 登录成功")
                            break
                    except Exception:
                        pass
                else:
                    logger.warning("VPN Web 登录超时（5分钟）")
                    await ctx.close()
                    return None

            await page.wait_for_timeout(3000)

            # 提取 Cookie
            cookies = await ctx.cookies()
            twfid = None
            for c in cookies:
                if c["name"].upper() == "TWFID":
                    twfid = c["value"]
                    break

            # 测试访问目标数据库（可能触发更多 Cookie 设置）
            if twfid:
                try:
                    await page.goto(
                        "http://www-pkulaw-com-s.vpn.lzufe.edu.cn:8118/law/chl",
                        wait_until="domcontentloaded", timeout=20000,
                    )
                    await page.wait_for_timeout(2000)
                    cookies = await ctx.cookies()  # 获取更新后的完整 Cookie
                except Exception:
                    pass

            await ctx.close()

            if twfid:
                return twfid, cookies
            logger.error("登录后未找到 TWFID Cookie")
            return None

    async def get_cookie_header(self, force_refresh: bool = False) -> str:
        """获取 VPN Web 会话 Cookie 字符串.

        优先使用缓存，缓存无效时自动启动浏览器登录。

        Args:
            force_refresh: 强制刷新（忽略缓存）.

        Returns:
            Cookie 字符串（如 "TWFID=xxx; language=zh_CN"），无 VPN 时返回空字符串.
        """
        # 检查隧道
        if not self._check_tunnel_up():
            logger.warning("EasyConnect 虚拟网卡未 Up，VPN 隧道未建立")
            return ""

        # 检查缓存
        if not force_refresh and self._is_cache_valid() and self._full_cookie_str:
            # 快速验证 TWFID 是否仍然有效
            if self._twfid and await self._verify_twfid(self._twfid):
                return self._full_cookie_str
            logger.info("缓存的 TWFID 已失效，需要重新获取")

        # 从文件加载缓存
        if not force_refresh:
            cached = self._load_cached_cookie()
            if cached:
                ts = cached.get("timestamp", 0)
                if (time.time() - ts) < self.COOKIE_TTL:
                    twfid = cached.get("twfid", "")
                    cookies = cached.get("cookies", [])
                    if twfid and await self._verify_twfid(twfid):
                        self._cookie_cache = cached
                        self._cache_time = ts
                        self._twfid = twfid
                        self._full_cookie_str = self._build_cookie_str(cookies)
                        logger.info(f"VPN Cookie 从缓存恢复（TWFID={twfid}）")
                        return self._full_cookie_str
                    logger.info("缓存的 TWFID 验证失败，需要重新登录")

        # 启动浏览器登录
        logger.info("启动浏览器进行 VPN Web 登录...")
        result = await self._login_via_browser()
        if result is None:
            return ""

        twfid, cookies = result
        self._twfid = twfid
        self._full_cookie_str = self._build_cookie_str(cookies)
        self._cookie_cache = {
            "twfid": twfid,
            "cookies": cookies,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "timestamp": time.time(),
        }
        self._cache_time = time.time()
        self._save_cookie_cache(cookies, twfid)

        logger.info(f"VPN Cookie 获取成功（TWFID={twfid}）")
        return self._full_cookie_str

    async def get_twfid(self, force_refresh: bool = False) -> str:
        """获取 TWFID 值（便捷方法）.

        Args:
            force_refresh: 强制刷新.

        Returns:
            TWFID 字符串，无 VPN 时返回空字符串.
        """
        if not self._twfid or force_refresh:
            await self.get_cookie_header(force_refresh=force_refresh)
        return self._twfid or ""


# 全局单例
_session_manager: VPNSessionManager | None = None


def get_vpn_session_manager(project_root: str = ".") -> VPNSessionManager:
    """获取全局 VPNSessionManager 单例.

    Args:
        project_root: 项目根目录（用于定位 .scholar/ 缓存目录）.

    Returns:
        VPNSessionManager 实例.
    """
    global _session_manager
    if _session_manager is None:
        _session_manager = VPNSessionManager(project_root=project_root)
    return _session_manager
