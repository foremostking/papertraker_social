"""ChinaXiv 预印本检索引擎.

中国科学院科技论文预发布平台，提供中文学术预印本检索。
类似于 arXiv 的中文对标平台，覆盖自然科学和社会科学各学科。

特点:
    - 免费开放，无需认证即可检索
    - 下载全文需登录
    - 服务端渲染 HTML，需解析 DOM
    - 存在反爬机制，需控制请求频率

Usage:
    engine = ChinaXivEngine()
    result = await engine.search("财政政策", limit=20)
"""

from scholarpilot.mcp.servers.chinaxiv.engine import (
    ChinaXivEngine,
    ChinaXivPaper,
    ChinaXivSearchResult,
)

__all__ = [
    "ChinaXivEngine",
    "ChinaXivPaper",
    "ChinaXivSearchResult",
]
