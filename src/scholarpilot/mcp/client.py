"""MCP Client 管理器.

管理与 MCP Server 的连接和通信。
支持两种模式：
1. 直接连接（DirectConnector）：引擎作为函数直接调用，适用于进程内场景
2. MCP 协议连接（stdio）：引擎作为独立子进程，通过 MCP 协议通信
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Any, Optional

from .registry import MCPServerConfig

logger = logging.getLogger(__name__)


class DirectConnector:
    """直接连接器：将引擎方法直接绑定为可调用工具.

    适用场景：检索引擎在进程内运行，不需要 stdio 子进程通信。
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    @property
    def tools(self) -> dict[str, callable]:
        """获取引擎的可调用工具."""
        tools = {}
        for attr_name in dir(self._engine):
            if attr_name.startswith("_"):
                continue
            attr = getattr(self._engine, attr_name)
            if callable(attr) and asyncio.iscoroutinefunction(attr):
                tools[attr_name] = attr
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        """调用工具."""
        if arguments is None:
            arguments = {}
        tool = getattr(self._engine, tool_name, None)
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' not found on engine")
        if asyncio.iscoroutinefunction(tool):
            return await tool(**arguments)
        return tool(**arguments)

    async def close(self) -> None:
        """关闭连接."""
        if hasattr(self._engine, "close"):
            close_method = self._engine.close
            if asyncio.iscoroutinefunction(close_method):
                await close_method()
            else:
                close_method()


class MCPClientManager:
    """MCP 客户端管理器.

    负责创建和管理与多个 MCP Server 的连接，
    提供统一的工具调用接口。

    支持两种连接模式：
    - direct: 直接绑定引擎对象（进程内调用）
    - stdio: 启动子进程通过 MCP 协议通信

    Usage:
        manager = MCPClientManager()

        # 直接连接模式
        engine = CNKIAiohttpEngine()
        await manager.connect_direct("cnki", engine)
        result = await manager.call_tool("cnki", "search", query="地方政府债务")

        # stdio 模式
        await manager.connect("arxiv", command="python", args=["-m", "arxiv_server"])
        result = await manager.call_tool("arxiv", "search_papers", query="LLM")
    """

    def __init__(self) -> None:
        """初始化 MCP 客户端管理器."""
        self._clients: dict[str, Any] = {}  # stdio 连接
        self._direct_connectors: dict[str, DirectConnector] = {}  # 直接连接

    async def connect_direct(self, server_name: str, engine: Any) -> None:
        """直接连接引擎（进程内调用）.

        Args:
            server_name: 服务器名称。
            engine: 引擎对象实例。
        """
        connector = DirectConnector(engine)
        self._direct_connectors[server_name] = connector
        logger.info(f"Direct connector registered for '{server_name}'")

    async def connect(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """连接到 MCP Server（stdio 子进程）.

        Args:
            server_name: 服务器名称。
            command: 启动命令。
            args: 命令参数。
            env: 环境变量。
        """
        if args is None:
            args = []

        merged_env = {**__import__("os").environ}
        if env:
            merged_env.update(env)

        try:
            process = subprocess.Popen(
                [command, *args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=merged_env,
                text=True,
            )
            self._clients[server_name] = process
            logger.info(f"Connected to MCP server '{server_name}' via stdio")
        except Exception as e:
            logger.error(f"Failed to connect to '{server_name}': {e}")
            raise

    async def disconnect(self, server_name: str) -> None:
        """断开与 MCP Server 的连接.

        Args:
            server_name: 服务器名称。
        """
        if server_name in self._direct_connectors:
            await self._direct_connectors[server_name].close()
            del self._direct_connectors[server_name]
            return

        if server_name in self._clients:
            process = self._clients[server_name]
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                process.kill()
            del self._clients[server_name]
            logger.info(f"Disconnected from '{server_name}'")

    async def disconnect_all(self) -> None:
        """断开所有连接."""
        for name in list(self._clients.keys()):
            await self.disconnect(name)
        for name in list(self._direct_connectors.keys()):
            await self.disconnect(name)

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        """列出 MCP Server 提供的工具.

        Args:
            server_name: 服务器名称。

        Returns:
            工具描述列表。
        """
        if server_name in self._direct_connectors:
            connector = self._direct_connectors[server_name]
            return [
                {
                    "name": name,
                    "description": getattr(func, "__doc__", "") or "",
                }
                for name, func in connector.tools.items()
            ]

        return []  # stdio 模式暂未实现工具发现

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """调用 MCP Server 的工具.

        Args:
            server_name: 服务器名称。
            tool_name: 工具名称。
            arguments: 工具参数。

        Returns:
            工具调用结果。
        """
        if server_name in self._direct_connectors:
            return await self._direct_connectors[server_name].call_tool(tool_name, arguments)

        if server_name in self._clients:
            # stdio 模式：发送 JSON-RPC 请求
            process = self._clients[server_name]
            request = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments or {},
                },
                "id": 1,
            }
            try:
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                response_line = process.stdout.readline()
                if response_line:
                    response = json.loads(response_line)
                    if "error" in response:
                        raise RuntimeError(f"MCP error: {response['error']}")
                    return response.get("result")
            except Exception as e:
                logger.error(f"MCP call failed for '{server_name}/{tool_name}': {e}")
                raise

        raise ValueError(f"Server '{server_name}' not connected")

    @property
    def connected_servers(self) -> list[str]:
        """获取已连接的服务器列表."""
        return list(self._clients.keys()) + list(self._direct_connectors.keys())