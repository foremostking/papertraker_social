"""Web of Science 检索引擎.

通过 Clarivate Web of Science 检索外文学术文献。
支持双模式访问：
1. 官方 REST API（WoSLite API，需 API Key）
2. Web Session API（/api/wosnx/core/，需浏览器登录后的 SID）

WoS 查询语言 (WQL) 字段前缀：
- TS=  主题检索（标题+摘要+关键词+Keywords Plus）
- TI=  标题检索
- AU=  作者检索
- AI=  作者识别号 (ORCID/ResearcherID)
- SO=  出版物名称
- PY=  出版年份
- DO=  DOI
- UT=  Unique Identifier (WoS ID)

Usage:
    # 官方 API 模式
    engine = WoSEngine(api_key="your_key")
    result = await engine.search("fiscal policy economic growth", limit=20)

    # Session 模式（需从浏览器获取 SID）
    engine = WoSEngine(sid="your_sid")
    result = await engine.search("fiscal policy", limit=20)
"""

from scholarpilot.mcp.servers.wos.engine import (
    WoSEngine,
    WoSPaper,
    WoSSearchResult,
    WoSAccessMode,
    WoSQueryBuilder,
)

__all__ = [
    "WoSEngine",
    "WoSPaper",
    "WoSSearchResult",
    "WoSAccessMode",
    "WoSQueryBuilder",
]
