"""API 请求链捕获器 (ApiChainRecorder).

基于 CDP **Network 域**捕获调试 Edge (带实时 TWFID 的真实浏览器) 里的所有
API 请求(方法/URL/请求头含Cookie/请求体/响应状态/响应体样例), 写入 JSONL.

为什么用 Network 域而非 JS 钩子:
- JS 钩子依赖注入时机与页面执行上下文, 易漏捕; Network 域在浏览器网络层拦截,
  XHR/Fetch 全量、跨标签/iframe/新开标签彻底覆盖, 更可靠.
- 用 requestWillBeSent.type 过滤掉静态资源(Script/Stylesheet/Image/Document),
  只保留 XHR / Fetch 这类 API 请求.

认证前提: EasyConnect 网络层 + web代理 TWFID, 由 BrowserAuthRefresher 注入到
调试 Edge, 页面访问才免登录. 本记录器在真实会话里捕获, 得到的请求链可直接复刻.

用法(后台运行)::
    python scripts/record_api_chain.py --out .scholar/api_chains/cnki_platform.jsonl
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import websockets

from scholarpilot.utils.browser_auth_refresher import BrowserAuthRefresher

logger = logging.getLogger("api_chain_recorder")

_WS = 9223
_DEF_OUT = ".scholar/api_chains/capture.jsonl"
CAP_BODY = 8000          # 响应体样例字符上限
WANT_TYPES = {"XHR", "Fetch"}   # 只捕获这类请求

_IGNORE_URL_SUFFIX = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif",
                      ".svg", ".ico", ".woff", ".woff2", ".ttf", ".map")


class ApiChainRecorder:
    """CDP Network 域驱动的请求链捕获器."""

    def __init__(self, project_root: str = ".", port: int = _WS,
                 out_path: str = _DEF_OUT):
        self.project_root = project_root
        self.port = port
        self.out_path = out_path
        self.r = BrowserAuthRefresher(project_root, port)
        self.ws: websockets.WebSocketClientProtocol | None = None
        self._sessions: dict[str, dict] = {}   # sessionId -> {targetId}
        self._entries: dict[str, dict] = {}    # requestId -> entry
        self._stop = False
        self._recv_task: asyncio.Task | None = None
        self._seq = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()
        self._fh = None

    # ───────────────────────── 基础 CDP (单一消息泵) ────────────
    async def _cmd(self, method: str, params: dict | None = None,
                   session_id: str | None = None, timeout: float = 40):
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

    # ─────────────────────── 目标管理与 Network 开启 ────────────
    async def _enable_network(self, session_id: str, target_id: str = ""):
        """对指定页面会话开启 Network 捕获."""
        try:
            await self._cmd("Network.enable", session_id=session_id)
        except Exception as e:
            logger.warning(f"Network.enable 失败 {session_id}: {e}")
            return
        self._sessions[session_id] = {"targetId": target_id}

    async def _auto_attach(self):
        """自动附加到新标签页(无需暂停/等调试器), 各自开启 Network."""
        await self._cmd("Target.setAutoAttach", {
            "autoAttach": True,
            "waitForDebuggerOnStart": False,
            "flatten": True,
        })

    async def _attach_existing(self):
        """附加到已存在的 page target 并开启 Network."""
        targets = (await self._cmd("Target.getTargets")).get("targetInfos", [])
        for t in targets:
            if t.get("type") != "page":
                continue
            try:
                resp = await self._cmd(
                    "Target.attachToTarget",
                    {"targetId": t["targetId"], "flatten": True},
                )
                await self._enable_network(resp.get("sessionId"), t["targetId"])
            except Exception as e:
                logger.warning(f"附加已有页面失败 {t.get('url')}: {e}")

    # ─────────────────────── 事件接收器 ─────────────────────────
    def _make_entry(self, params: dict, sid: str):
        req = params.get("request", {})
        url = req.get("url", "")
        if url.startswith("ws://") or url.startswith("wss://"):
            return None
        if url.lower().endswith(_IGNORE_URL_SUFFIX):
            return None
        type_ = params.get("type", "")
        if type_ not in WANT_TYPES:
            return None
        return {
            "t": params.get("timestamp"),
            "session": sid,
            "kind": type_.lower(),
            "method": params.get("requestMethod") or req.get("method", ""),
            "url": url,
            "reqHeaders": dict(req.get("headers", {}) or {}),
            "reqBody": params.get("requestPostData")
                or params.get("postData") or "",
            "status": None,
            "respLen": None,
            "respHead": "",
        }

    async def _finalize(self, request_id: str, sid: str):
        """请求结束后补抓响应体并写 JSONL."""
        entry = self._entries.pop(request_id, None)
        if not entry:
            return
        try:
            if entry.get("status") and str(entry["status"]).startswith("2"):
                res = await self._cmd(
                    "Network.getResponseBody", {"requestId": request_id},
                    session_id=sid, timeout=15)
                body = res.get("body", "")
                entry["isBase64"] = bool(res.get("base64Encoded"))
            else:
                body = ""
        except Exception:
            body = ""
        entry["respLen"] = len(body) if isinstance(body, str) else -1
        if isinstance(body, str):
            entry["respHead"] = body[:CAP_BODY]
        try:
            await self._write_lock.acquire()
            self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._fh.flush()
        finally:
            if self._write_lock.locked():
                self._write_lock.release()

    async def _receiver(self):
        """单一消息泵: 命令响应回填 future, 事件分发到 Network 捕获."""
        try:
            while not self._stop:
                try:
                    raw = json.loads(
                        await asyncio.wait_for(self.ws.recv(), timeout=60))
                except asyncio.TimeoutError:
                    continue
                if "id" in raw:  # 命令响应
                    fut = self._pending.pop(raw["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(raw.get("result", {}))
                    continue
                method = raw.get("method")
                par = raw.get("params", {}) or {}
                sid = raw.get("sessionId")
                if method == "Target.attachedToTarget":
                    info = par.get("targetInfo", {})
                    if sid and info.get("type") == "page":
                        asyncio.create_task(
                            self._enable_network(sid, info.get("targetId", "")))
                elif method == "Network.requestWillBeSent":
                    if sid is None:
                        continue
                    entry = self._make_entry(par, sid)
                    if entry and par.get("requestId"):
                        self._entries[par["requestId"]] = entry
                elif method == "Network.requestWillBeSentExtraInfo":
                    e = self._entries.get(par.get("requestId"))
                    if e and par.get("headers"):
                        try:
                            e["reqHeaders"].update(par["headers"])
                        except Exception:
                            pass
                elif method == "Network.responseReceived":
                    e = self._entries.get(par.get("requestId"))
                    if e and par.get("response"):
                        e["status"] = par["response"].get("status")
                        e["mimeType"] = par["response"].get("mimeType", "")
                elif method == "Network.loadingFinished":
                    rid = par.get("requestId")
                    if rid and rid in self._entries:
                        asyncio.create_task(self._finalize(rid, sid))
        except websockets.ConnectionClosed:
            logger.info("CDP 连接关闭, receiver 退出")
        except Exception as e:
            logger.warning(f"receiver 异常: {e}")

    # ───────────────────────── 生命周期 ─────────────────────────
    async def start(self):
        if not self.r.ensure_debug_edge():
            raise RuntimeError("无法启动/复用调试 Edge")
        self.ws = await websockets.connect(
            self.r._browser_ws_url(), max_size=512 * 1024 * 1024)
        Path(self.out_path).parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.out_path, "w", encoding="utf-8")
        self._sessions.clear()
        # 消息泵先行, _cmd 依赖它回填
        self._recv_task = asyncio.create_task(self._receiver())
        await asyncio.sleep(0.3)
        await self._auto_attach()
        await self._attach_existing()
        logger.info(f"请求链捕获器(NaaS/Network)已启动 → {self.out_path}")

    async def stop(self):
        self._stop = True
        if self._recv_task:
            self._recv_task.cancel()
        if self._fh:
            self._fh.flush()
            self._fh.close()
        if self.ws:
            await self.ws.close()
        logger.info("请求链捕获器已停止")


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