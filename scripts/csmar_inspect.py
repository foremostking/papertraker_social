"""检查调试浏览器的某个 CSMAR 标签的实际渲染内容 + 截图+全文.

用法: python scripts/csmar_inspect.py [--url-substr data-csmar-com]
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

import urllib.request  # noqa: E402
import websockets  # noqa: E402

PORT = 9223


def _browser_ws_url(port: int = PORT) -> str:
    ver = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/json/version", timeout=5).read())
    return ver["webSocketDebuggerUrl"]


async def _cmd(ws, method, params=None, sid=None, timeout=60):
    mid = id(None) and int(__import__("time").time() * 1000) % 100000
    await ws.send(json.dumps({"id": mid, "method": method,
                              "params": params or {}, **({"sessionId": sid} if sid else {})}))
    while True:
        raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if raw.get("id") == mid:
            return raw


async def inspect(substr: str, snap: str):
    import time as _t
    async with websockets.connect(_browser_ws_url(), max_size=256 * 1024 * 1024) as ws:
        targets = (await _cmd(ws, "Target.getTargets"))["result"]["targetInfos"]
        matches = [t for t in targets if t.get("type") == "page"
                   and substr in (t.get("url") or "")]
        print("匹配页面数:", len(matches))
        for t in matches:
            print("  -", t.get("targetId", "?")[:12], (t.get("title") or "")[:30], t.get("url")[:80])
        if not matches:
            print("未找到含", substr, "的页面")
            return
        t = matches[-1]
        r = await _cmd(ws, "Target.attachToTarget",
                       {"targetId": t["targetId"], "flatten": True})
        sid = r["result"]["sessionId"]
        await _cmd(ws, "Page.enable", sid=sid)
        await _cmd(ws, "Runtime.enable", sid=sid)
        await asyncio.sleep(2)
        ev = (await _cmd(ws, "Runtime.evaluate", {
            "expression": "JSON.stringify({href:location.href,"
                          "html:document.documentElement?document.documentElement.outerHTML.slice(0,6000):'',"
                          "iframes:[...document.querySelectorAll('iframe')].map(f=>f.src),"
                          "ls_full:localStorage.getItem('__path__full__')})",
            "returnByValue": True}, sid=sid))["result"]["result"]["value"]
        d = json.loads(ev)
        print("=== href ===", d["href"][:120])
        print("=== localStorage.__path__full__ ===", d["ls_full"])
        print("=== iframes ===", d["iframes"])
        print("=== outerHTML(前6000) ===")
        print(d["html"][:6000])
        if snap:
            png = (await _cmd(ws, "Page.captureScreenshot", {"format": "png"}, sid=sid))
            data = png["result"]["data"]
            out = Path(snap)
            out.write_bytes(base64.b64decode(data))
            print("screenshot ->", out)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--url-substr", default="data-csmar-com")
    p.add_argument("--snap", default=".scholar/api_chains/csmar_snap.png")
    args = p.parse_args()
    snap = str(Path(project_root).parent / args.snap) if not Path(args.snap).is_absolute() else args.snap
    asyncio.run(inspect(args.url_substr, snap))


if __name__ == "__main__":
    main()