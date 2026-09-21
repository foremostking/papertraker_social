"""自主驱动探针：注入 TWFID 后导航到国泰安(CSMAR)，判定免登录与可达访问.

用法: python scripts/csmar_probe.py
需要: EasyConnect 已登录 + 调试 Edge (port 9223) 已由 record_api_chain 拉起.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from scholarpilot.utils.browser_auth_refresher import BrowserAuthRefresher  # noqa: E402

CSMAR_ENTRY = "http://data-csmar-com-s.vpn.lzufe.edu.cn:8118/"


async def probe(port: int, entry: str):
    r = BrowserAuthRefresher(str(project_root), port)
    res = await r.refresh_database("csmar", entry_url=entry, wait_seconds=12)
    print("=== refresh_database result ===")
    print(json.dumps({k: res.get(k) for k in
                      ("ok", "url", "twfid", "target_id", "session_id", "error")},
                     ensure_ascii=False, indent=2))
    print("cookies keys:", sorted(res.get("cookies", {}).keys())[:25])
    print("cookies TWFID:", (res.get("cookies") or {}).get("TWFID", "(none)")[:12])
    return res


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9223)
    p.add_argument("--entry", default=CSMAR_ENTRY)
    args = p.parse_args()
    asyncio.run(probe(args.port, args.entry))


if __name__ == "__main__":
    main()