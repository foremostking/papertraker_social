"""ScholarPilot MCP 模块.

提供 MCP (Model Context Protocol) 客户端管理和服务器注册。
"""

from .client import MCPClientManager
from .registry import MCPRegistry

__all__ = ["MCPClientManager", "MCPRegistry"]
