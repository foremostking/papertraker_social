"""枚举 CSMAR iframe(/csmar.html) 内的导航路由与可见入口链接, 用于规划数据检索路径.

用法: python scripts/csmar_enum.py
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


def _ws():
    ver = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{PORT}/json/version", timeout=5).read())
    return ver["webSocketDebuggerUrl"]


async def _cmd(ws, method, params=None, sid=None, timeout=60):
    mid = int(_t.time() * 1000) % 100000
    await ws.send(json.dumps({"id": mid, "method": method,
                              "params": params or {}, **({"sessionId": sid} if sid else {})}))
    while True:
        raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if raw.get("id") == mid:
            return raw


async def run():
    async with websockets.connect(_ws(), max_size=256 * 1024 * 1024) as ws:
        targets = (await _cmd(ws, "Target.getTargets"))["result"]["targetInfos"]
        frames = [t for t in targets
                  if "csmar" in (t.get("url") or "") or "/csmar.html" in (t.get("url") or "")]
        print("CSMAR 相关 target 数:", len(frames))
        for t in frames:
            print("  type=%s id=%s url=%s" % (t.get("type"), t.get("targetId")[:12], t.get("url")[:90]))
        # 取最深的 iframe (csmar.html)
        deep = [t for t in frames if "/csmar.html" in t.get("url", "")]
        deep = deep or frames
        for t in deep[-1:]:
            r = await _cmd(ws, "Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})
            sid = r["result"]["sessionId"]
            await _cmd(ws, "Runtime.enable", sid=sid)
            await asyncio.sleep(1)
            expr = ("(()=>{const links=(wd)=>{const out=[];"
                    "wd.document.querySelectorAll('a').forEach(a=>{const t=(a.innerText||'').trim().slice(0,24);if(t)out.push({t:t,h:a.href});});return out;};"
                    "const go=(wd)=>({href:wd.location.href,body:(wd.document.body?wd.document.body.innerText:'').slice(0,300),nav:links(wd)});"
                    "let f=document.querySelector('iframe');let D=null;"
                    "try{if(f&&f.contentDocument)D=go(f.contentWindow);}catch(e){D={err:String(e)};}"
                    "return JSON.stringify({parent:go(window),iframe:D});})()")
            v = (await _cmd(ws, "Runtime.evaluate",
                            {"expression": expr, "returnByValue": True}, sid=sid))
            rr = v.get("result", {})
            print("eval result keys:", list(rr.keys()), "vals:", json.dumps(rr, ensure_ascii=False)[:400])
            inner = (rr.get("result") or {})
            if "value" not in inner or inner.get("value") is None:
                print("evaluate 无返回值 (可能是 iframe 跨上下文/异常):", json.dumps(rr, ensure_ascii=False)[:300])
                return
            d = json.loads(inner["value"])
            for tag, doc in (("PARENT", d["parent"]), ("IFRAME", d["iframe"])):
                print(f"=== {tag} href ===", (doc or {}).get("href", "")[:100])
                print(f"=== {tag} body(前300) ===", (doc or {}).get("body", "").replace("\n", " | ")[:300])
                seen = set()
                print(f"=== {tag} 导航链接 ===")
                for l in (doc or {}).get("nav", [])[:60]:
                    key = (l["t"], l["h"])
                    if key in seen:
                        continue
                    seen.add(key)
                    print("  ", l["t"], "->", l["h"][:115])


asyncio.run(run())