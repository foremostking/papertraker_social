"""在 CSMAR 顶层壳页的 iframe 内执行 JS, 支持逐步驱动 SPA 检索.

用法: python scripts/csmar_drive.py "<js>" [--wait 2] [--out 0/1]
JS 在顶层壳页上下文执行, 用 frame.contentWindow 访问 CSMAR SPA.
返回值(returnByValue)若不是字符串则 JSON 序列化打印.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time as _t
import urllib.request
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

import websockets  # noqa: E402

PORT = 9223
CSMAR_SUBSTR = "data-csmar-com"


def _ws():
    ver = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{PORT}/json/version", timeout=5).read())
    return ver["webSocketDebuggerUrl"]


async def _cmd(ws, method, params=None, sid=None, timeout=90):
    mid = int(_t.time() * 1000) % 100000
    await ws.send(json.dumps({"id": mid, "method": method,
                              "params": params or {}, **({"sessionId": sid} if sid else {})}))
    while True:
        raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if raw.get("id") == mid:
            return raw


def _wrap(js):
    # 把用户 JS 包进 iframe 上下文; 返回 JSON 字符串便于阅读
    return ("(()=>{"
            "function __links(wd){const out=[];"
            "wd.document.querySelectorAll('a').forEach(a=>{const t=(a.innerText||'').trim().replace(/\\s+/g,' ').slice(0,26);if(t)out.push({t:t,h:a.href});});return out.slice(0,80);}"
            "function __snap(wd){return {href:wd.location.href,"
            "body:(wd.document.body?wd.document.body.innerText:'')"
            ".replace(/\\n+/g,' | ').slice(0,1200),"
            "links:__links(wd),inputs:[...wd.document.querySelectorAll('input,select,[contenteditable=true]')].map(e=>({tag:e.tagName,ph:e.placeholder||e.name||e.id||''})).slice(0,40)};}"
            "const f=document.querySelector('iframe');let wd=window;"
            "if(f&&f.contentWindow)wd=f.contentWindow;"
            "const wrap=(ctx)=>{return {snap:__snap(wd),err:String((ctx.error)||'')}};"
            "let out;try{out=eval(("+json.dumps("(" + js + ")") +
            "))(wd,__snap,__links);}catch(e){out={__drive_error:String(e)};}"
            "const snap=__snap(wd);"
            "return JSON.stringify({result:out,snap:snap});})()")


async def drive(js: str, wait: float):
    async with websockets.connect(_ws(), max_size=256 * 1024 * 1024) as ws:
        targets = (await _cmd(ws, "Target.getTargets"))["result"]["targetInfos"]
        pages = [t for t in targets if t.get("type") == "page"
                 and CSMAR_SUBSTR in (t.get("url") or "")]
        if not pages:
            print("未找到 CSMAR 页面")
            return
        t = pages[-1]
        r = await _cmd(ws, "Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})
        sid = r["result"]["sessionId"]
        await _cmd(ws, "Runtime.enable", sid=sid)
        if wait > 0:
            await asyncio.sleep(wait)
        v = await _cmd(ws, "Runtime.evaluate",
                       {"expression": _wrap(js), "returnByValue": True, "awaitPromise": True},
                       sid=sid, timeout=120)
        rr = v.get("result", {})
        inner = rr.get("result") or {}
        if "value" not in inner or inner.get("value") is None:
            print("evaluate 无返回值:", json.dumps(rr, ensure_ascii=False)[:500])
            return
        d = json.loads(inner["value"])
        print("### RESULT ###")
        print(json.dumps(d.get("result"), ensure_ascii=False, indent=2)[:3000])
        print("### after-snap ###")
        s = d.get("snap", {})
        print("href:", s.get("href", "")[:110])
        print("body:", s.get("body", ""))
        print("inputs:", [x["ph"] for x in s.get("inputs", [])][:40])


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("js")
    p.add_argument("--wait", type=float, default=1.5)
    args = p.parse_args()
    asyncio.run(drive(args.js, args.wait))


if __name__ == "__main__":
    main()