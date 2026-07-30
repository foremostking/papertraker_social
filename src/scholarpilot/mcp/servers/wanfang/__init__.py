"""万方数据知识服务平台检索引擎.

万方数据是中文三大学术数据库之一,覆盖期刊论文、学位论文、
会议论文、专利、标准等多类型文献。与 CNKI 互补,尤其在
学位论文和会议论文方面覆盖更全。

Usage:
    from scholarpilot.mcp.servers.wanfang import WanfangEngine, WanfangPaper

    engine = WanfangEngine(vpn_mode=True)
    result = await engine.search("地方政府债务", limit=20)
"""

from scholarpilot.mcp.servers.wanfang.engine import (
    WanfangEngine,
    WanfangPaper,
    WanfangSearchResult,
)

__all__ = [
    "WanfangEngine",
    "WanfangPaper",
    "WanfangSearchResult",
]
