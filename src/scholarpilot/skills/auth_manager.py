"""实证数据库持久化认证管理器.

将各库的 token/cookie 持久化存储到 .scholar/empirical_auth.json，
程序启动时自动加载，使用前验证有效性，过期时提示用户重新登录。
浏览器关闭后认证信息仍然有效（存储在文件中）。

支持的认证类型：
- bearer: harborn 平台（环球财经/黄河流域），真实域名 + Bearer token
- cookie: CNKI/微观/区域，VPN 代理地址 + 会话 Cookie
- api_key: EPS 等有独立 API Key 的库

Usage::
    mgr = AuthManager(project_root=".")
    creds = await mgr.get_credentials("huanqiu")
    if creds:
        # creds.access_token 可直接用于 API 调用
        headers = {"Authorization": f"Bearer {creds.access_token}"}
    else:
        # 凭据缺失或过期，需引导用户重新登录
        print(mgr.get_login_guide("huanqiu"))
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DBCredentials:
    """单个数据库的认证凭据."""

    db_key: str
    name: str
    auth_type: str  # bearer | cookie | api_key
    # bearer 类型
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_at: float = 0.0  # Unix 时间戳，0 表示未知
    # cookie 类型
    cookies: dict[str, str] = field(default_factory=dict)
    # 通用
    platform: str = ""  # harborn | sozdata | cnki | eps
    notes: str = ""

    @property
    def is_expired(self) -> bool:
        """检查凭据是否已过期（基于 expires_at）."""
        if self.expires_at == 0:
            return False  # 未知过期时间，保守认为未过期
        return time.time() > self.expires_at

    @property
    def bearer_header(self) -> str:
        """生成 Authorization 头值."""
        return f"{self.token_type} {self.access_token}"

    @property
    def cookie_header(self) -> str:
        """生成 Cookie 头值."""
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())


class AuthManager:
    """实证数据库持久化认证管理器.

    核心职责：
    1. 从 .scholar/empirical_auth.json 加载凭据（程序启动时）
    2. 使用前验证凭据有效性（轻量 API 探测）
    3. 凭据失效时返回 None + 登录引导信息
    4. 用户提供新凭据时自动保存

    持久化文件格式::

        {
          "version": 2,
          "saved_at": "2026-08-11T17:00:00",
          "databases": {
            "huanqiu": { "auth_type": "bearer", "access_token": "...", ... },
            "huanghe": { "auth_type": "bearer", "access_token": "...", ... },
            ...
          }
        }
    """

    AUTH_FILE = ".scholar/empirical_auth.json"

    # 各库的验证端点（轻量请求，用于检测 token/cookie 是否有效）
    VERIFY_ENDPOINTS: dict[str, dict[str, Any]] = {
        "huanqiu": {
            "url": "https://gf.harborn.cn/hqcj/home/hotSearch",
            "method": "GET",
            "auth_type": "bearer",
            "success_check": lambda r: r.status_code == 200 and r.text.startswith("{"),
        },
        "huanghe": {
            "url": "https://yrb.harborn.cn/hhly/home/homeIndicatorCategorys",
            "method": "GET",
            "auth_type": "bearer",
            "success_check": lambda r: r.status_code == 200 and r.text.startswith("{"),
        },
        "cnki_data": {
            "url": "http://data-cnki-net-s.vpn.lzufe.edu.cn:8118/",
            "method": "GET",
            "auth_type": "cookie",
            "success_check": lambda r: r.status_code == 200
            and "vpn.lzufe.edu.cn:8444" not in r.text,
        },
        "weiguan": {
            "url": "http://microdata-sozdata-com-s.vpn.lzufe.edu.cn:8118/",
            "method": "GET",
            "auth_type": "cookie",
            "success_check": lambda r: r.status_code == 200
            and "vpn.lzufe.edu.cn:8444" not in r.text,
        },
        "quyu": {
            "url": "http://cnrrd-sozdata-com-s.vpn.lzufe.edu.cn:8118/",
            "method": "GET",
            "auth_type": "cookie",
            "success_check": lambda r: r.status_code == 200
            and "vpn.lzufe.edu.cn:8444" not in r.text,
        },
    }

    # 各库的登录引导信息
    LOGIN_GUIDES: dict[str, str] = {
        "huanqiu": (
            "环球财经数据平台登录引导：\n"
            "1. 确保 EasyConnect VPN 已连接\n"
            "2. 在浏览器中访问 http://gf-harborn-cn-s.vpn.lzufe.edu.cn:8118/index\n"
            "3. 完成登录后，从浏览器 localStorage 提取 access_token 和 refresh_token\n"
            "4. 调用 auth_manager.save_credentials('huanqiu', ...) 保存"
        ),
        "huanghe": (
            "黄河流域数据库登录引导：\n"
            "1. 确保 EasyConnect VPN 已连接\n"
            "2. 在浏览器中访问 http://yrb-harborn-cn-s.vpn.lzufe.edu.cn:8118/index\n"
            "3. 完成登录后，从浏览器 localStorage 提取 access_token 和 refresh_token\n"
            "4. 调用 auth_manager.save_credentials('huanghe', ...) 保存"
        ),
        "cnki_data": (
            "CNKI 数据平台登录引导：\n"
            "1. 确保 EasyConnect VPN 已连接\n"
            "2. 在浏览器中访问 http://data-cnki-net-s.vpn.lzufe.edu.cn:8118/\n"
            "3. 完成登录后，从浏览器提取 SF_cookie_413 和 SID cookie\n"
            "4. 调用 auth_manager.save_credentials('cnki_data', ...) 保存"
        ),
        "weiguan": (
            "微观数据平台登录引导：\n"
            "1. 确保 EasyConnect VPN 已连接\n"
            "2. 在浏览器中访问 http://microdata-sozdata-com-s.vpn.lzufe.edu.cn:8118/\n"
            "3. 完成登录后，从浏览器提取 SESSION 等 cookie\n"
            "4. 调用 auth_manager.save_credentials('weiguan', ...) 保存"
        ),
        "quyu": (
            "区域研究平台登录引导：\n"
            "1. 确保 EasyConnect VPN 已连接\n"
            "2. 在浏览器中访问 http://cnrrd-sozdata-com-s.vpn.lzufe.edu.cn:8118/\n"
            "3. 完成登录后，从浏览器提取 JSESSIONID 和 re_sid cookie\n"
            "4. 调用 auth_manager.save_credentials('quyu', ...) 保存"
        ),
    }

    def __init__(self, project_root: str = ".") -> None:
        self._project_root = project_root
        self._credentials: dict[str, DBCredentials] = {}
        self._loaded = False

    def _auth_path(self) -> str:
        return os.path.join(self._project_root, self.AUTH_FILE)

    def load(self) -> None:
        """从文件加载所有凭据."""
        path = self._auth_path()
        if not os.path.exists(path):
            logger.debug(f"认证文件不存在: {path}")
            self._loaded = True
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, raw in data.get("databases", {}).items():
                self._credentials[key] = DBCredentials(
                    db_key=key,
                    name=raw.get("name", key),
                    auth_type=raw.get("auth_type", ""),
                    access_token=raw.get("access_token", ""),
                    refresh_token=raw.get("refresh_token", ""),
                    token_type=raw.get("token_type", "Bearer"),
                    expires_at=raw.get("expires_at", 0),
                    cookies=raw.get("cookies", {}),
                    platform=raw.get("platform", ""),
                    notes=raw.get("notes", ""),
                )
            logger.info(f"已加载 {len(self._credentials)} 个数据库凭据")
        except Exception as e:
            logger.warning(f"加载认证文件失败: {e}")
        self._loaded = True

    def save(self) -> None:
        """保存所有凭据到文件."""
        path = self._auth_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "version": 2,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": "持久化认证凭据。Token 有效期有限，过期后需重新登录提取。",
            "databases": {},
        }
        for key, cred in self._credentials.items():
            d = asdict(cred)
            d.pop("db_key")
            data["databases"][key] = d
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存 {len(self._credentials)} 个数据库凭据到 {path}")

    def save_credentials(
        self, db_key: str, name: str = "", auth_type: str = "bearer", **kwargs: Any
    ) -> None:
        """保存或更新单个数据库的凭据."""
        cred = DBCredentials(
            db_key=db_key,
            name=name or db_key,
            auth_type=auth_type,
            access_token=kwargs.get("access_token", ""),
            refresh_token=kwargs.get("refresh_token", ""),
            token_type=kwargs.get("token_type", "Bearer"),
            expires_at=kwargs.get("expires_at", 0),
            cookies=kwargs.get("cookies", {}),
            platform=kwargs.get("platform", ""),
            notes=kwargs.get("notes", ""),
        )
        self._credentials[db_key] = cred
        self.save()
        logger.info(f"凭据已保存: {db_key} ({auth_type})")

    def get_credentials(self, db_key: str) -> DBCredentials | None:
        """获取凭据（不验证有效性）."""
        if not self._loaded:
            self.load()
        cred = self._credentials.get(db_key)
        if cred is None:
            return None
        if cred.is_expired:
            logger.warning(f"凭据已过期: {db_key}")
            return None
        return cred

    async def get_valid_credentials(self, db_key: str) -> DBCredentials | None:
        """获取凭据并验证有效性（发轻量测试请求）."""
        cred = self.get_credentials(db_key)
        if cred is None:
            return None
        if await self.verify_credentials(db_key, cred):
            return cred
        logger.warning(f"凭据验证失败: {db_key}")
        return None

    async def verify_credentials(self, db_key: str, cred: DBCredentials) -> bool:
        """验证凭据是否有效（发轻量测试请求）."""
        endpoint = self.VERIFY_ENDPOINTS.get(db_key)
        if endpoint is None:
            return True  # 无验证端点的库，保守认为有效
        headers: dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        if cred.auth_type == "bearer" and cred.access_token:
            headers["Authorization"] = cred.bearer_header
        elif cred.auth_type == "cookie" and cred.cookies:
            headers["Cookie"] = cred.cookie_header

        try:
            async with httpx.AsyncClient(
                timeout=10, follow_redirects=False, verify=False, trust_env=False
            ) as client:
                if endpoint["method"] == "GET":
                    r = await client.get(endpoint["url"], headers=headers)
                else:
                    r = await client.post(endpoint["url"], headers=headers, json={})
                check = endpoint["success_check"]
                return bool(check(r))
        except Exception as e:
            logger.debug(f"验证 {db_key} 异常: {e}")
            return False

    def get_login_guide(self, db_key: str) -> str:
        """获取登录引导信息."""
        return self.LOGIN_GUIDES.get(
            db_key, f"数据库 {db_key} 需要重新登录，请参考相关平台说明。"
        )

    def list_status(self) -> list[dict[str, Any]]:
        """列出所有凭据的状态."""
        if not self._loaded:
            self.load()
        result = []
        for key, cred in self._credentials.items():
            result.append({
                "db_key": key,
                "name": cred.name,
                "auth_type": cred.auth_type,
                "has_token": bool(cred.access_token or cred.cookies),
                "expired": cred.is_expired,
            })
        return result

    def remove_credentials(self, db_key: str) -> None:
        """删除指定数据库的凭据."""
        if db_key in self._credentials:
            del self._credentials[db_key]
            self.save()
            logger.info(f"凭据已删除: {db_key}")

    # ═══════════════════════════════════════════════════════════════
    #  TWFID 统一管理（VPN 代理层 Cookie）
    # ═══════════════════════════════════════════════════════════════

    # TWFID 作为 VPN 代理层的会话凭证，存储在同一个 empirical_auth.json 中
    # 键名固定为 vpn_session，与各数据库凭据并列
    VPN_SESSION_KEY = "vpn_session"

    # TWFID 有效期约 2 小时，保守设为 100 分钟
    TWFID_TTL = 6000  # 秒

    def save_twfid(self, twfid: str, extra_cookies: dict[str, str] | None = None) -> None:
        """保存 TWFID 到持久化认证文件.

        将 VPN 代理层的 TWFID Cookie 统一存储到 empirical_auth.json，
        与各数据库凭据并列管理，消除双文件同步问题。

        Args:
            twfid: TWFID Cookie 值.
            extra_cookies: 附加 VPN 域 Cookie（如 language 等）.
        """
        cookies = {"TWFID": twfid}
        if extra_cookies:
            cookies.update(extra_cookies)

        cred = DBCredentials(
            db_key=self.VPN_SESSION_KEY,
            name="VPN 代理会话 (TWFID)",
            auth_type="cookie",
            cookies=cookies,
            platform="vpn_proxy",
            expires_at=time.time() + self.TWFID_TTL,
            notes="EasyConnect VPN Web 代理层会话，访问 *-s.vpn.lzufe.edu.cn 必需",
        )
        self._credentials[self.VPN_SESSION_KEY] = cred
        self.save()
        logger.info(f"TWFID 已保存到 AuthManager (有效期 {self.TWFID_TTL // 60} 分钟)")

    def get_twfid(self) -> str | None:
        """获取缓存的 TWFID 值（不验证有效性）.

        Returns:
            TWFID 字符串，不存在或已过期返回 None.
        """
        if not self._loaded:
            self.load()
        cred = self._credentials.get(self.VPN_SESSION_KEY)
        if cred is None or cred.is_expired:
            return None
        return cred.cookies.get("TWFID")

    def build_vpn_cookie_header(self, db_key: str) -> str:
        """构建 VPN 代理数据库的组合 Cookie 头.

        将 VPN 层 TWFID + 数据库层 Cookie 合并为单个 Cookie 头，
        解决此前数据库 cookie 从未注入 VPN 代理请求的问题。

        合并优先级: TWFID (VPN 层) → 数据库 cookies (应用层)
        重复 key 以数据库层为准（数据库层更具体）。

        Args:
            db_key: 数据库键名 (如 cnki_data / weiguan / quyu).

        Returns:
            组合 Cookie 字符串 (如 "TWFID=xxx; SF_cookie_413=91009105; SID=30100182").
            若无任何凭据返回空字符串.
        """
        if not self._loaded:
            self.load()

        parts: dict[str, str] = {}  # 用 dict 去重，后写入覆盖先写入

        # 1. VPN 层 TWFID
        vpn_cred = self._credentials.get(self.VPN_SESSION_KEY)
        if vpn_cred and not vpn_cred.is_expired:
            parts.update(vpn_cred.cookies)

        # 2. 数据库层 cookies（覆盖同名 key）
        db_cred = self._credentials.get(db_key)
        if db_cred and db_cred.cookies:
            parts.update(db_cred.cookies)

        return "; ".join(f"{k}={v}" for k, v in parts.items())

    async def verify_vpn_db_access(self, db_key: str) -> bool:
        """统一验证 VPN 代理数据库的两层认证是否都有效.

        检查链路: TWFID (VPN 层) → 数据库 cookies (应用层) → 实际可达性

        Args:
            db_key: 数据库键名.

        Returns:
            True 如果 TWFID 和数据库 cookies 都存在且实际可达.
        """
        if not self._loaded:
            self.load()

        # 检查 TWFID
        twfid = self.get_twfid()
        if not twfid:
            logger.warning(f"TWFID 缺失或过期，VPN 代理层认证不可用")
            return False

        # 检查数据库 cookies
        db_cred = self._credentials.get(db_key)
        if db_cred is None or not db_cred.cookies:
            logger.warning(f"数据库 {db_key} 凭据缺失")
            return False

        # 构建组合 Cookie 并发实际请求验证
        cookie_str = self.build_vpn_cookie_header(db_key)
        endpoint = self.VERIFY_ENDPOINTS.get(db_key)
        if endpoint is None:
            return True  # 无验证端点，保守认为有效

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Cookie": cookie_str,
        }
        try:
            async with httpx.AsyncClient(
                timeout=10, follow_redirects=False, verify=False, trust_env=False,
            ) as client:
                if endpoint["method"] == "GET":
                    r = await client.get(endpoint["url"], headers=headers)
                else:
                    r = await client.post(endpoint["url"], headers=headers, json={})
                check = endpoint["success_check"]
                return bool(check(r))
        except Exception as e:
            logger.debug(f"验证 {db_key} VPN 访问异常: {e}")
            return False

    def diagnose_vpn_db(self, db_key: str) -> dict[str, Any]:
        """诊断 VPN 代理数据库的认证状态（同步，不发请求）.

        返回各层认证状态，用于快速判断哪一层出了问题。

        Args:
            db_key: 数据库键名.

        Returns:
            诊断结果字典.
        """
        if not self._loaded:
            self.load()

        vpn_cred = self._credentials.get(self.VPN_SESSION_KEY)
        db_cred = self._credentials.get(db_key)

        return {
            "db_key": db_key,
            "vpn_layer": {
                "has_twfid": bool(vpn_cred and vpn_cred.cookies.get("TWFID")),
                "expired": vpn_cred.is_expired if vpn_cred else True,
                "expires_in": max(0, int(vpn_cred.expires_at - time.time()))
                    if vpn_cred and vpn_cred.expires_at > 0 else "unknown",
            },
            "db_layer": {
                "has_cookies": bool(db_cred and db_cred.cookies),
                "cookie_keys": list(db_cred.cookies.keys()) if db_cred else [],
            },
            "combined_cookie_ready": bool(
                vpn_cred and not vpn_cred.is_expired
                and db_cred and db_cred.cookies
            ),
        }


# 全局单例
_auth_manager: AuthManager | None = None


def get_auth_manager(project_root: str = ".") -> AuthManager:
    """获取全局 AuthManager 单例."""
    global _auth_manager
    if _auth_manager is None or _auth_manager._project_root != project_root:
        _auth_manager = AuthManager(project_root)
        _auth_manager.load()
    return _auth_manager
