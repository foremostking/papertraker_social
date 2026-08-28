"""API请求链捕获器 CLI 入口.

用法(后台运行)::
    python scripts/record_api_chain.py --out .scholar/api_chains/cnki_platform.jsonl
    # 一直运行直到 Ctrl+C / 被终止; 期间请在调试Edge里手动操作数据库
"""
from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from scholarpilot.utils.api_chain_recorder import ApiChainRecorder  # noqa: E402


def main():
    import asyncio
    import logging
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--out", default=".scholar/api_chains/capture.jsonl")
    p.add_argument("--port", type=int, default=9223)
    p.add_argument("--project-root", default=str(project_root))
    p.add_argument("--duration", type=int, default=0,
                   help="自动结束秒数, 0=一直运行直到被终止")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async def _run():
        rec = ApiChainRecorder(args.project_root, args.port, args.out)
        await rec.start()
        try:
            if args.duration > 0:
                await asyncio.sleep(args.duration)
                await rec.stop()
            else:
                await asyncio.Future()
        except (asyncio.CancelledError, KeyboardInterrupt):
            await rec.stop()

    asyncio.run(_run())


if __name__ == "__main__":
    main()