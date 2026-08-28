"""API 请求链捕获器 (ApiChainRecorder).

在调试 Edge (CDP) 中注入 fetch/XHR 钩子, 持续记录用户在真实会话里
触发的所有 API 请求(方法/URL/请求头/请求体/响应样例), 写入 JSONL 文件,
供后续逆向固化为程序化取数。

设计要点:
- 复用 BrowserAuthRefresher: 读取 ECAgent 实时 TWFID + 启动/复用调试 Edge
- Target.setAutoAttach + waitForDebuggerOnStart=True: 对新打开的每个标签页
  在文档加载前注入钩子, 保证跨标签彻底覆盖
- 轮询收集: 定时读取各页面 window.__apiChain 增量, 追加写 JSONL
- 任何单页面异常都不中断整体收集

用法(作为后台进程运行)::
    python scripts/record_api_chain.py --out .scholar/api_chains/library.jsonl
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import websockets

from scholarpilot.utils.browser_auth_refresher import BrowserAuthRefresher

logger = logging.getLogger("api_chain_recorder")

_WS = 9223
_DEF_OUT = ".scholar/api_chains/capture.jsonl"

# 注入到每个页面的 fetch/XHR 钩子. 在 app JS 运行前安装, 拦截所有请求.
CAP_BODY = 4000
_HOOK_TPL = r"""
(() => {
  if (!window.__apiChain) window.__apiChain = [];
  const $c = window.__apiChain;
  const CAP = @@CAP@@, MAX = 2000, TRIM = 300;
  function safeStr(o){try{return typeof o==='string'?o:JSON.stringify(o);}catch(_){return String(o);}}
  function hdrs(h){const o={};try{if(!h)return o;if(typeof Headers!=='undefined'&&h instanceof Headers){h.forEach((v,k)=>o[k]=v);}else if(Array.isArray(h)){h.forEach(x=>{const k=Object.keys(x)[0];o[k]=x[k];});}else if(typeof h==='object'){for(const k in h)o[k]=h[k];}}catch(_){}return o;}
  function cut(s){return (s&&s.length>CAP)?s.slice(0,CAP):s;}
  function rec(e){try{$c.push(e);if($c.length>MAX)$c.splice(0,TRIM);}catch(_){}}
  // fetch: 用函数标记保证幂等, 只包原生 fetch 一次, 避免重复注入重复记录
  if (window.fetch && !window.fetch.__apiHook) {
    const origFetch = window.fetch;
    const wf = function(){
      let url='',method='GET',body='',headers={},t0=Date.now();
      try{const a=arguments[0];url=(a&&a.url)?a.url:String(a||'');const o=arguments[1]||{};method=(o.method||'GET').toUpperCase();body=(typeof o.body==='string')?o.body:((o.body)?safeStr(o.body):'');headers=hdrs(o.headers);}catch(_){}
      return origFetch.apply(this,arguments).then(function(res){
        return res.clone().text().catch(function(){return '';}).then(function(t){
          rec({t:Date.now(),kind:'fetch',method,url,reqHeaders:headers,reqBody:cut(body),status:res.status,respLen:t.length,respHead:cut(t),ms:Date.now()-t0});
          return res;
        });
      }).catch(function(err){rec({t:Date.now(),kind:'fetch',method,url,reqHeaders:headers,reqBody:cut(body),error:String((err&&err.message)||err)});throw err;});
    };
    wf.__apiHook = true;
    window.fetch = wf;
  }
  // XHR
  const XP = window.XMLHttpRequest && window.XMLHttpRequest.prototype;
  if (XP && !XP.__apiHook) {
    const O=XP.open, S=XP.send;
    XP.open=function(m,u){this.__r={method:String(m).toUpperCase(),url:u};return O.apply(this,arguments);};
    XP.send=function(b){const self=this,r=(this.__r||{}),t0=Date.now();
      const reqBody=(typeof b==='string')?b:((b&&typeof b==='object'&&'body' in b)?String(b.body):'');
      this.addEventListener('loadend',function(){let t='';try{t=self.responseText||'';}catch(_){}
        rec({t:Date.now(),kind:'xhr',method:r.method,url:r.url,reqBody:cut(reqBody),status:self.status,respLen:t.length,respHead:cut(t),ms:Date.now()-t0});});
      return S.apply(this,arguments);};
    XP.__apiHook = true;
  }
  window.__apiChainInstalled = true;
})();
"""
HOOK_JS = _HOOK_TPL.replace("@@CAP@@", str(CAP_BODY))


class ApiChainRecorder:
    """CDP 驱动的请求链捕获器."""

    def __init__(self, project_root: str = ".", port: int = _WS,
                 out_path: str = _DEF_OUT):
        self.project_root = project_root
        self.port = port
        self.out_path = out_path
        self.r = BrowserAuthRefresher(project_root, port)
        self.ws: websockets.WebSocketClientProtocol | None = None
        self._pages: dict[str, dict] = {}  # sessionId -> {targetId, count, installed}
        self._stop = False
        self._recv_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._seq = 0

    # ───────────────────────── 基础 CDP ─────────────────────────
    # 单一消息泵: 只有一个 _receiver 循环在 recv(), 命令响应与事件统一分发,
    # 避免 websockets 禁止并发 recv 的冲突.
    async def _cmd(self, method: str, params: dict | None = None,
                   session_id: str | None = None, timeout: float = 30):
        self._seq = (self._seq + 1) % 100000
        mid = self._seq
        fut = asyncio.get_event_loop().create_future()
        self._pending[mid] = fut
        msg = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        await self.ws.send(json.dumps(msg))
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(mid, None)
            raise

    async def _eval(self, session_id, js: str):
        r = await self._cmd(
            "Runtime.evaluate",
            {"expression": js, "returnByValue": True, "awaitPromise": True},
            session_id=session_id,
        )
        return r.get("result", {}).get("value")

    # ─────────────────────── 钩子安装 ───────────────────────────
    async def _install_hook(self, session_id: str, wait_for_debugger: bool):
        """在指定页面会话安装钩子 (在文档加载前调用)."""
        try:
            await self._cmd("Page.enable", session_id=session_id)
            await self._cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": HOOK_JS}, session_id=session_id,
            )
            if wait_for_debugger:
                await self._cmd("Runtime.runIfWaitingForDebugger",
                                session_id=session_id)
            self._pages[session_id] = {
                "targetId": self._pages.get(session_id, {}).get("targetId", ""),
                "count": 0,
                "installed": True,
            }
        except Exception as e:
            logger.warning(f"install_hook 失败 session={session_id}: {e}")

    async def _attach_existing(self):
        """附加到已存在的 page target 并安装钩子."""
        targets = (await self._cmd("Target.getTargets")).get("targetInfos", [])
        for t in targets:
            if t.get("type") != "page":
                continue
            try:
                resp = await self._cmd(
                    "Target.attachToTarget",
                    {"targetId": t["targetId"], "flatten": True},
                )
                sid = resp.get("sessionId")
                self._pages[sid] = {"targetId": t["targetId"], "count": 0,
                                    "installed": False}
                await self._install_hook(sid, wait_for_debugger=False)
            except Exception as e:
                logger.warning(f"附加已有页面失败 {t.get('url')}: {e}")

    async def _auto_attach(self):
        """开启自动附加, 新开标签页在加载前注入钩子."""
        await self._cmd("Target.setAutoAttach", {
            "autoAttach": True,
            "waitForDebuggerOnStart": True,
            "flatten": True,
        })

    async def _receiver(self):
        """单一消息泵: 读取所有 CDP 消息, 命令响应回填 pending Future, 事件分发."""
        try:
            while not self._stop:
                try:
                    raw = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=60))
                except asyncio.TimeoutError:
                    continue
                # 命令响应 → 回填 pending Future
                if "id" in raw:
                    fut = self._pending.pop(raw["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(raw.get("result", {}))
                    continue
                # 事件分发. 注意: 处理任务须放入独立 Task, 不能在 receiver
                # 循环内 await——否则等待命令响应时没人 recv(), 必然自锁超时.
                method = raw.get("method")
                if method == "Target.attachedToTarget":
                    params = raw.get("params", {})
                    info = params.get("targetInfo", {})
                    sid = params.get("sessionId")
                    if sid and info.get("type") == "page":
                        self._pages.setdefault(sid, {
                            "targetId": info.get("targetId", ""),
                            "count": 0, "installed": False,
                        })
                        asyncio.create_task(self._install_hook(
                            sid,
                            wait_for_debugger=params.get("waitingForDebugger", False)))
        except websockets.ConnectionClosed:
            logger.info("CDP 连接关闭, receiver 退出")
        except Exception as e:
            logger.warning(f"receiver 异常: {e}")

    # ─────────────────────── 轮询收集 ───────────────────────────
    async def _poll(self):
        """周期性读取各页面的请求链增量, 追加写 JSONL."""
        Path(self.out_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.out_path, "a", encoding="utf-8") as f:
            while not self._stop:
                await asyncio.sleep(2.0)
                for sid, meta in list(self._pages.items()):
                    if not meta.get("installed"):
                        continue
                    try:
                        total_v = await self._eval(
                            sid, "(window.__apiChain||[]).length")
                        total = int(total_v or 0) if total_v else 0
                        if total > meta.get("count", 0):
                            entries_v = await self._eval(
                                sid,
                                "JSON.stringify(window.__apiChain.slice(%d))"
                                % meta.get("count", 0))
                            try:
                                arr = json.loads(entries_v or "[]")
                            except Exception:
                                arr = []
                            for e in arr:
                                e["_session"] = sid
                                e["_target"] = meta.get("targetId", "")
                                f.write(json.dumps(e, ensure_ascii=False) + "\n")
                            f.flush()
                            # 按实际写入条数递增, 避免两次 eval 间新增条目被重复切片
                            meta["count"] = meta.get("count", 0) + len(arr)
                            logger.info(
                                f"[{sid[:8]}] 新增 {len(arr)} 条请求 (累计 {total})")
                    except Exception as e:
                        logger.debug(f"轮询 {sid} 失败: {e}")

    # ───────────────────────── 生命周期 ─────────────────────────
    async def start(self):
        if not self.r.ensure_debug_edge():
            raise RuntimeError("无法启动/复用调试 Edge")
        self.ws = await websockets.connect(
            self.r._browser_ws_url(), max_size=512 * 1024 * 1024)
        # 必须先启动消息泵(receiver), _cmd 依赖它回填响应
        self._recv_task = asyncio.create_task(self._receiver())
        await asyncio.sleep(0.3)
        await self._auto_attach()
        await self._attach_existing()
        self._poll_task = asyncio.create_task(self._poll())
        logger.info(f"请求链捕获器已启动 → {self.out_path}")

    async def stop(self):
        self._stop = True
        for t in (self._recv_task, self._poll_task):
            if t:
                t.cancel()
        if self.ws:
            await self.ws.close()


async def _amain(out_path, port, project_root, duration):
    rec = ApiChainRecorder(project_root, port, out_path)
    await rec.start()
    try:
        if duration > 0:
            await asyncio.sleep(duration)
            await rec.stop()
        else:
            await asyncio.Future()
    except (asyncio.CancelledError, KeyboardInterrupt):
        await rec.stop()


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=_DEF_OUT)
    p.add_argument("--port", type=int, default=_WS)
    p.add_argument("--project-root", default=".")
    p.add_argument("--duration", type=int, default=0,
                   help="自动结束秒数, 0=一直运行直到被终止")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(_amain(args.out, args.port, args.project_root, args.duration))


if __name__ == "__main__":
    main()