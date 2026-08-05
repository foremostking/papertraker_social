"""CNKI MCP Server 包.

将 CNKI 检索能力封装为 MCP (Model Context Protocol) Server，
供 Scholar Agent 通过 MCP 协议调用。

核心功能:
    - 4 层检索策略生成
    - CNKI 文献检索（需要 Cookie 或机构 IP）
    - 8 维统计分析
    - 选题可行性判定

引擎选择:
    - CNKIAiohttpEngine: 推荐，基于 papertracker_social 已验证方案，
      aiohttp + 正确 QueryJson，2026-06-27 实测返回 1736 篇
    - CNKIPlaywrightEngine: 浏览器内 fetch（可选，默认不启用）
"""

from scholarpilot.mcp.servers.cnki.server import (
    CNKIPaper,
    CNKISearchResult,
    QueryLayer,
    calculate_eight_dimensions,
    assess_feasibility,
)
from scholarpilot.mcp.servers.cnki.aiohttp_engine import (
    CNKIAiohttpEngine,
    SOURCE_CATEGORY_MAPPING,
    DEFAULT_SOURCE_CATEGORIES,
)

__all__ = [
    "CNKIAiohttpEngine",
    "CNKIPaper",
    "CNKISearchResult",
    "QueryLayer",
    "calculate_eight_dimensions",
    "assess_feasibility",
    "SOURCE_CATEGORY_MAPPING",
    "DEFAULT_SOURCE_CATEGORIES",
]
