"""运行一次真实(带缓存 Cookie)的 CNKI 采集请求, 使用 7 类来源筛选.

用于验证真实环境下 build_query_json 生成的 QueryJson 与 search 流程,
以及 7 类来源筛选(SCI/北大核心/CSSCI/EI/CSCD/AMI/WJCI)是否生效。

注意: 结果取决于缓存 Cookie 是否有效与网络是否可达 CNKI。
    若遇到验证码/超时/网络不可达, 会给出明确提示, 不影响逻辑验证。
运行:
    py -3.13 scripts/run_real_cnki_collect.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

from scholarpilot.mcp.servers.cnki.aiohttp_engine import (
    CNKIAiohttpEngine,
    DEFAULT_SOURCE_CATEGORIES,
)


async def main() -> int:
    engine = CNKIAiohttpEngine(timeout=25)
    engine.load_cookie_from_cache()

    print("=" * 80)
    print("真实采集: 地方政府债务, 年份 2020-2026, 7 类来源筛选")
    print("=" * 80)

    result = await engine.search(
        query="地方政府债务",
        limit=10,
        year_start="2020",
        year_end="2026",
        source_categories=DEFAULT_SOURCE_CATEGORIES,
    )

    print("-" * 80)
    print(f"query='地方政府债务'")
    print(f"total_count = {result.total_count}")
    print(f"返回论文数 = {len(result.papers)}")
    for i, p in enumerate(result.papers[:5], 1):
        authors = ", ".join(p.authors[:3])
        print(f"  {i}. {p.title} | {authors} | {p.journal} | {p.year} | 被引{p.cited_count}")
    if result.total_count == 0 and not result.papers:
        print("\n提示: total=0, 可能是 Cookie 失效/验证码/网络不可达。")
        print("(缓存 Cookie fetched_at = 2026-06-27, 可能已过期)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))