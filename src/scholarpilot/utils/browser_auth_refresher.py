"""
浏览器认证刷新器 (BrowserAuthRefresher)
========================================
将验证过的"浏览器免登录 + 滑块通过 + 提取cookie"机制固化，供各 VPN 数据库凭据刷新复用。

核心链路（2026-08-12 验证通过）：
1. 从 ECAgent mem.db 读取实时 TWFID（会轮换，不能硬编码）
2. 通过 CDP 驱动调试 Edge：清故障 TWFID cookie → 注入 ECAgent 实时 TWFID
   → 浏览器即可免登录访问 `*.vpn.lzufe.edu.cn` 资源（不再被 302 到 8444 登录门户）
3. 导航到目标库，若遇滑块/登录则由用户手动完成一次
4. 提取页面 cookies → 保存到 `.scholar/empirical_auth.json`
5. 用 httpx 独立访问业务 API 验证银据可用（脱离浏览器）

根因说明：
- 浏览器打开 VPN 域名被要求登录，是因为 cookie jar 残留网关 302 时 Set-Cookie 的
  故障 TWFID（登录门户会话 ID，非资源访问 ID），与 ECAgent 有效 TWFID 冲突。
- 修复：在 VPN 门户页用 document.cookie 清除所有 TWFID 变体，再注入有效值。

Usage::
    from scholarpilot.utils.browser_auth_refresher import BrowserAuthRefresher
    r = BrowserAuthRefresher(debug_port=9223)
    twfid = r.read_realtime_twfid()
    ok = r.refresh_database("cnki", "http://kns-cnki-net-s.vpn.lzufe.edu.cn:8118/kns8s/")
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# EasyConnect ECAgent 配置
EC_MEM_DB = r"C:\Users\xuxiaobing\AppData\Roaming\Sangfor\SSL\ECAgent\s-1\default\p0\mem.db"
EC_EXE = r"C:\Program Files (x86)\Sangfor\SSL\EasyConnect\EasyConnect.exe"

# 默认调试端口
DEFAULT_PORT = 9223

# 各 VPN 库的入口 URL（用于导航+提取cookie）
VPN_DB_ENTRIES: dict[str, tuple[str, str]] = {
    # db_key: (入口URL, 业务API示例URL)
    "cnki": (
        "http://kns-cnki-net-s.vpn.lzufe.edu.cn:8118/kns8s/",
        "http://kns-cnki-net-s.vpn.lzufe.edu.cn:8118/kns8s/",
    ),
    "weiguan": (
        "http://microdata-sozdata-com-s.vpn.lzufe.edu.cn:8118/",
        "http://microdata-sozdata-com-s.vpn.lzufe.edu.cn:8118/",
    ),
    "quyu": (
        "http://cnrrd-sozdata-com-s.vpn.lzufe.edu.cn:8118/",
        "http://cnrrd-sozdata-com-s.vpn.lzufe.edu.cn:8118/",
    ),
}


class BrowserAuthRefresher:
    """浏览器认证刷新器：注入 TWFID → 免登录 → 提取 cookie → httpx 验证."""

    def __init__(self, project_root: str = ".", debug_port: int = DEFAULT_PORT):
        self._project_root = project_root
        self._port = debug_port
        self._browser_ws = None
        self._edge_proc = None

    # ─────────────────────────────────────────────────────────────
    #  1. ECAgent 实时 TWFID 读取
    # ─────────────────────────────────────────────────────────────

    def read_realtime_twfid(self) -> str | None:
        """从 ECAgent mem.db 读取实时 TWFID（会轮换）.

        Returns:
            TWFID 字符串，读取失败返回 None.
        """
        if not os.path.exists(EC_MEM_DB):
            logger.warning(f"ECAgent mem.db 不存在: {EC_MEM_DB}")
            return None
        try:
            conn = sqlite3.connect(EC_MEM_DB)
            cur = conn.cursor()
            for (tname,) in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall():
                for key, value in cur.execute(f'SELECT * FROM "{tname}"').fetchall():
                    if key == "twfID":
                        conn.close()
                        return json.loads(value).get("config", "").strip()
            conn.close()
        except Exception as e:
            logger.warning(f"读取 ECAgent TWFID 失败: {e}")
        return None

    # ─────────────────────────────────────────────────────────────
    #  2. 调试浏览器生命周期
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _find_browser_exe() -> str | None:
        """定位本机可用的 Chrome / Edge 可执行文件."""
        candidates = [
            os.environ.get("SCHOLARPILOT_BROWSER"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return None

    def ensure_debug_edge(self) -> bool:
        """确保带调试端口的浏览器已启动.

        若端口已有调试服务则复用；否则启动独立临时配置的浏览器。
        """
        if self._is_debug_port_ready():
            logger.info(f"调试端口 {self._port} 已就绪，复用")
            return True
        # 定位可用的浏览器可执行文件（Edge 优先，其次 Chrome）
        browser_exe = self._find_browser_exe()
        if not browser_exe:
            logger.warning("未找到 Chrome/Edge 可执行文件")
            return False
        # 启动独立浏览器（临时 user-data-dir，不污染用户配置）
        user_data = os.path.join(tempfile.gettempdir(), "edge_debug_auth")
        try:
            self._edge_proc = subprocess.Popen(
                [
                    browser_exe,
                    f"--remote-debugging-port={self._port}",
                    f"--user-data-dir={user_data}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-gpu",
                ],
                creationflags=0,
            )
            # 等待调试端口就绪
            for _ in range(20):
                if self._is_debug_port_ready():
                    logger.info(f"调试 Edge 已启动 (port={self._port})")
                    return True
                time.sleep(0.5)
            logger.warning("调试 Edge 启动超时")
            return False
        except Exception as e:
            logger.warning(f"启动调试 Edge 失败: {e}")
            return False

    def _is_debug_port_ready(self) -> bool:
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{self._port}/json/version", timeout=2
            )
            return True
        except Exception:
            return False

    def _browser_ws_url(self) -> str:
        ver = json.loads(
            urllib.request.urlopen(
                f"http://127.0.0.1:{self._port}/json/version", timeout=5
            ).read()
        )
        return ver["webSocketDebuggerUrl"]

    # ─────────────────────────────────────────────────────────────
    #  3. CDP 免登录导航 + 提取 cookie
    # ─────────────────────────────────────────────────────────────

    async def _cdp(self, ws, method: str, params: dict | None = None,
                   session_id: str | None = None, timeout: float = 60):
        """发送 CDP 命令并等待响应."""
        import websockets
        msg_id = int(time.time() * 1000) % 100000
        msg = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        await ws.send(json.dumps(msg))
        while True:
            raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            if raw.get("id") == msg_id:
                return raw

    async def _eval(self, ws, js: str, session_id: str | None = None):
        r = await self._cdp(
            ws, "Runtime.evaluate",
            {"expression": js, "returnByValue": True, "awaitPromise": True},
            session_id=session_id,
        )
        return r["result"]["result"].get("value")

    async def refresh_database(self, db_key: str, entry_url: str | None = None,
                               wait_seconds: int = 8) -> dict:
        """刷新指定 VPN 数据库的凭据.

        Args:
            db_key: 数据库键名 (cnki/weiguan/quyu).
            entry_url: 覆盖库入口 URL.
            wait_seconds: 导航后等待秒数.

        Returns:
            {"ok": bool, "cookies": {...}, "url": str, "error": str}
        """
        import websockets

        if db_key in VPN_DB_ENTRIES:
            entry_url = entry_url or VPN_DB_ENTRIES[db_key][0]

        twfid = self.read_realtime_twfid()
        if not twfid:
            return {"ok": False, "error": "无法读取 ECAgent 实时 TWFID，请确认 EasyConnect 已登录"}
        logger.info(f"使用 ECAgent 实时 TWFID: {twfid[:8]}...")

        if not self.ensure_debug_edge():
            return {"ok": False, "error": "无法启动/连接调试 Edge"}

        ws_url = self._browser_ws_url()
        async with websockets.connect(ws_url, max_size=128 * 1024 * 1024) as ws:
            # 1. 创建 tab 导航到 VPN 门户页(域锚点)
            r = await self._cdp(ws, "Target.createTarget", {"url": "https://vpn.lzufe.edu.cn:8444/"})
            target_id = r["result"]["targetId"]
            r = await self._cdp(ws, "Target.attachToTarget",
                                {"targetId": target_id, "flatten": True})
            session_id = r["result"]["sessionId"]
            await self._cdp(ws, "Page.enable", session_id=session_id)
            await asyncio.sleep(4)

            # 2. 在门户页清除所有故障 TWFID cookie
            del_js = """
            (() => {
              const variants = [
                "TWFID=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; path=/",
                "TWFID=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; path=/; domain=vpn.lzufe.edu.cn",
                "TWFID=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; path=/; domain=.vpn.lzufe.edu.cn",
                "TWFID=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; path=/; domain=library-lzufe-edu-cn.vpn.lzufe.edu.cn",
                "TWFID=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; path=/; domain=kns-cnki-net-s.vpn.lzufe.edu.cn",
              ];
              for (const v of variants) document.cookie = v;
              return document.cookie;
            })()
            """
            await self._eval(ws, del_js, session_id)

            # 3. 注入有效 TWFID
            set_js = (
                f"document.cookie = 'TWFID={twfid}; domain=vpn.lzufe.edu.cn; path=/';"
                f"document.cookie;"
            )
            await self._eval(ws, set_js, session_id)

            # 4. 导航到目标库入口
            await self._cdp(ws, "Page.navigate", {"url": entry_url}, session_id=session_id)
            await asyncio.sleep(wait_seconds)

            # 5. 检查当前 URL 并提取 cookies
            cur_url = await self._eval(ws, "location.href", session_id)
            cookies_str = await self._eval(ws, "document.cookie", session_id)
            cookies = {}
            for part in (cookies_str or "").split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    cookies[k] = v

            # 6. 若被重定向到登录门户，标记需用户协助
            redirected = "8444/portal" in (cur_url or "")
            result = {
                "ok": not redirected,
                "cookies": cookies,
                "url": cur_url,
                "twfid": twfid,
                "target_id": target_id,
                "session_id": session_id,
                "error": "被重定向到登录门户" if redirected else None,
            }
            if redirected:
                logger.warning(f"{db_key} 导航后被重定向到登录门户，需用户协助")
            else:
                logger.info(f"{db_key} 免登录成功，URL={cur_url[:80]}")
            return result

    def save_cookies(self, db_key: str, cookies: dict[str, str],
                     domain: str, method: str = "browser_auth") -> str:
        """保存 cookies 到 empirical_auth.json（合并 VPN 层 TWFID）.

        Returns:
            保存的文件路径.
        """
        auth_file = Path(self._project_root) / ".scholar" / "empirical_auth.json"
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(auth_file.read_text(encoding="utf-8")) if auth_file.exists() else {}
        data[db_key] = {
            "name": db_key,
            "auth_type": "cookie",
            "cookies": cookies,
            "domain": domain,
            "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "method": method,
        }
        auth_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"已保存 {db_key} cookies 到 {auth_file}")
        return str(auth_file)

    # ─────────────────────────────────────────────────────────────
    #  4. httpx 独立验证
    # ─────────────────────────────────────────────────────────────

    async def verify_httpx_access(self, db_key: str, api_url: str,
                                  post_body: str | None = None,
                                  referer: str | None = None) -> dict:
        """用保存的 cookies 通过 httpx 独立访问业务 API，验证程序化访问成立.

        Args:
            db_key: 数据库键名.
            api_url: 业务 API 完整 URL.
            post_body: 若为 POST，提供请求体.
            referer: Referer 头.

        Returns:
            {"ok": bool, "status": int, "len": int, "head": str}
        """
        auth_file = Path(self._project_root) / ".scholar" / "empirical_auth.json"
        data = json.loads(auth_file.read_text(encoding="utf-8"))
        cookies = data.get(db_key, {}).get("cookies", {})
        if not cookies:
            return {"ok": False, "error": "无保存的 cookies"}
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": cookie_str,
        }
        if referer:
            headers["Referer"] = referer
        try:
            async with httpx.AsyncClient(
                timeout=30, verify=False, trust_env=False, follow_redirects=False
            ) as c:
                if post_body is not None:
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                    r = await c.post(api_url, content=post_body, headers=headers)
                else:
                    r = await c.get(api_url, headers=headers)
                return {
                    "ok": r.status_code == 200,
                    "status": r.status_code,
                    "len": len(r.text),
                    "head": r.text[:200],
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}


async def main():
    """命令行示例：刷新 CNKI 凭据."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    r = BrowserAuthRefresher(project_root=r"d:\副业\2026\AI论文自动化工程")
    print(f"ECAgent 实时 TWFID: {r.read_realtime_twfid()}")
    result = await r.refresh_database("cnki")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())