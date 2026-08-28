"""验证调试Edge + TWFID注入能否免登录打开图书馆VPN入口.

用法::
    python scripts/verify_library_edge.py

流程:
1. 从 ECAgent mem.db 读实时 TWFID
2. 启动/复用带调试端口的真实 Edge (临时 profile)
3. CDP 导航到门户, 清除故障 TWFID, 注入有效 TWFID
4. 导航到图书馆统一入口 http://library-lzufe-edu-cn.vpn.lzufe.edu.cn:8118/index
5. 汇报 URL / 是否重定向 / 页面标题与内容概要
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("verify_library_edge")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scholarpilot.utils.browser_auth_refresher import BrowserAuthRefresher  # noqa: E402

LIB_ENTRY = "http://library-lzufe-edu-cn.vpn.lzufe.edu.cn:8118/index"
PORTAL = "https://vpn.lzufe.edu.cn:8444/"


async def prepare_edge(r: BrowserAuthRefresher, twfid: str):
    """启动/复用调试Edge, 注入TWFID, 返回 (ws, session_id)."""
    import websockets

    ws_url = r._browser_ws_url()
    ws = await websockets.connect(ws_url, max_size=512 * 1024 * 1024)

    # 1. 建 tab 到门户(域锚点)
    resp = await r._cdp(ws, "Target.createTarget", {"url": PORTAL})
    target_id = resp["result"]["targetId"]
    resp = await r._cdp(ws, "Target.attachToTarget",
                        {"targetId": target_id, "flatten": True})
    session_id = resp["result"]["sessionId"]
    await r._cdp(ws, "Page.enable", session_id=session_id)
    await asyncio.sleep(4)

    # 2. 清除故障 TWFID 变体, 注入有效 TWFID
    del_js = """
    (() => {
      const variants = [
        "TWFID=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; path=/",
        "TWFID=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; path=/; domain=vpn.lzufe.edu.cn",
        "TWFID=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; path=/; domain=.vpn.lzufe.edu.cn",
        "TWFID=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; path=/; domain=library-lzufe-edu-cn.vpn.lzufe.edu.cn",
      ];
      for (const v of variants) document.cookie = v;
      return document.cookie;
    })()
    """
    await r._eval(ws, del_js, session_id)
    set_js = (
        f"document.cookie = 'TWFID={twfid}; domain=vpn.lzufe.edu.cn; path=/';"
        f"document.cookie;"
    )
    await r._eval(ws, set_js, session_id)

    # 3. 导航到图书馆入口
    await r._cdp(ws, "Page.navigate", {"url": LIB_ENTRY}, session_id=session_id)
    await asyncio.sleep(6)
    return ws, session_id


async def main():
    r = BrowserAuthRefresher(
        project_root=r"d:\副业\2026\AI论文自动化工程", debug_port=9223
    )
    twfid = r.read_realtime_twfid()
    if not twfid:
        print(json.dumps({"ok": False, "error": "无法读取ECAgent实时TWFID"},
                         ensure_ascii=False))
        return
    print(f"TWFID 读取成功: {twfid[:8]}...")
    if not r.ensure_debug_edge():
        print(json.dumps({"ok": False, "error": "无法启动调试Edge"}, ensure_ascii=False))
        return

    ws, session_id = await prepare_edge(r, twfid)
    cur_url = await r._eval(ws, "document.readyState + ' | ' + location.href", session_id)
    title = await r._eval(ws, "document.title", session_id)
    body_head = await r._eval(
        ws, "(document.body ? document.body.innerText : '').slice(0, 400)", session_id
    )
    redirected = "8444/portal" in (cur_url or "")
    print(json.dumps({
        "ok": not redirected,
        "ready_url": cur_url,
        "title": title,
        "redirected_to_portal": redirected,
        "body_head": body_head,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())