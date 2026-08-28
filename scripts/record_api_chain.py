"""API请求链捕获器 CLI 入口.

用法::
    python scripts/record_api_chain.py --out .scholar/api_chains/library.jsonl
    # 一直运行直到 Ctrl+C / 被终止; 期间请在调试Edge里手动操作数据库
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# 确保 package 可导入
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from scholarpilot.utils.api_chain_recorder import ApiChainRecorder  # noqa: E402


async def _main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=".scholar/api_chains/capture.jsonl")
    p.add_argument("--port", type=int, default=9223)
    p.add_argument("--project-root", default=str(project_root))
    p.add_argument("--duration", type=int, default=0,
                   help="自动结束秒数, 0=一直运行直到被终止")
    p.add_argument("--self-test", action="store_true",
                   help="启动后在活动页注入一条合成fetch, 快速验证捕获链路")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rec = ApiChainRecorder(args.project_root, args.port, args.out)
    await rec.start()

    if args.self_test:
        # 勾子只对"新文档"生效, 不追溯当前页. 故先强制注入到活动页, 再发一次 fetch,
        # 统计钩子捕获到的增量(不做任何引用重置, 避免闭包指向旧数组的测试陷阱).
        for _ in range(20):
            if rec._pages:
                break
            await asyncio.sleep(0.5)
        if rec._pages:
            from scholarpilot.utils.api_chain_recorder import HOOK_JS
            sid = next(iter(rec._pages))
            await rec._eval(sid, HOOK_JS)
            before = int((await rec._eval(sid, "(window.__apiChain||[]).length")) or 0)
            await rec._eval(
                sid, "fetch('/api_synctest?x=1',{method:'POST',headers:{'X-Test':'1'},"
                "body:'ping'}).then(()=>true)")
            await asyncio.sleep(3)
            after = int((await rec._eval(sid, "(window.__apiChain||[]).length")) or 0)
            print(f"self-test: 捕获增量={after - before} (应>=1)")
        await asyncio.sleep(1)

    try:
        if args.duration > 0:
            await asyncio.sleep(args.duration)
            await rec.stop()
        else:
            await asyncio.Future()
    except (asyncio.CancelledError, KeyboardInterrupt):
        await rec.stop()


if __name__ == "__main__":
    asyncio.run(_main())