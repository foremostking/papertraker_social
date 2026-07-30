"""PubScholar OA 资源检索引擎.

公共学术 OA 资源平台，提供中英文学术论文的开放获取检索。
通过 REST API 检索，支持 SHA1 签名认证。

特点:
    - REST API，返回结构化 JSON
    - SHA1 签名认证（无需账号）
    - 支持中英文检索
    - 覆盖 OA 期刊论文和学位论文

Usage:
    engine = PubScholarEngine()
    result = await engine.search("财政政策", limit=20)
"""

from scholarpilot.mcp.servers.pubscholar.engine import (
    PubScholarEngine,
    PubScholarPaper,
    PubScholarSearchResult,
)

__all__ = [
    "PubScholarEngine",
    "PubScholarPaper",
    "PubScholarSearchResult",
]
