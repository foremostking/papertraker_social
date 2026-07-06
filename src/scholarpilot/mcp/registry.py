"""MCP Server 注册表骨架.

管理可用 MCP Server 的配置和注册信息。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


class MCPServerConfig:
    """单个 MCP Server 的配置."""

    def __init__(
        self,
        name: str,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        description: str = "",
        enabled: bool = True,
    ) -> None:
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.description = description
        self.enabled = enabled


class MCPRegistry:
    """MCP Server 注册表.

    维护所有已知 MCP Server 的配置，支持从文件加载和动态注册。

    Usage:
        registry = MCPRegistry()
        registry.register(MCPServerConfig(
            name="arxiv",
            command="python",
            args=["-m", "arxiv_server"],
        ))
        servers = registry.get_enabled_servers()
    """

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        """初始化 MCP 注册表.

        Args:
            config_dir: MCP 服务器配置文件目录。
        """
        self.config_dir = config_dir
        self._servers: dict[str, MCPServerConfig] = {}

    def register(self, config: MCPServerConfig) -> None:
        """注册一个 MCP Server.

        Args:
            config: 服务器配置。
        """
        self._servers[config.name] = config

    def unregister(self, name: str) -> None:
        """取消注册一个 MCP Server.

        Args:
            name: 服务器名称。
        """
        self._servers.pop(name, None)

    def get(self, name: str) -> Optional[MCPServerConfig]:
        """获取指定服务器的配置.

        Args:
            name: 服务器名称。

        Returns:
            服务器配置，如果不存在则返回 None。
        """
        return self._servers.get(name)

    def get_enabled_servers(self) -> list[MCPServerConfig]:
        """获取所有已启用的服务器配置.

        Returns:
            已启用的服务器配置列表。
        """
        return [s for s in self._servers.values() if s.enabled]

    def list_all(self) -> list[MCPServerConfig]:
        """列出所有已注册的服务器.

        Returns:
            所有服务器配置列表。
        """
        return list(self._servers.values())

    async def load_from_dir(self, directory: Path | None = None) -> None:
        """从目录加载 MCP 服务器配置.

        扫描指定目录中的 JSON 配置文件，解析并注册 MCP Server。

        Args:
            directory: 配置文件目录，默认使用初始化时的 config_dir。
        """
        import json
        import logging

        logger = logging.getLogger(__name__)

        dir_path = directory or self.config_dir
        if not dir_path or not dir_path.exists():
            logger.warning(f"MCP config directory not found: {dir_path}")
            return

        for config_file in sorted(dir_path.glob("*.json")):
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
                name = data.get("name", config_file.stem)
                self.register(MCPServerConfig(
                    name=name,
                    command=data.get("command", "python"),
                    args=data.get("args", []),
                    env=data.get("env", {}),
                    description=data.get("description", ""),
                    enabled=data.get("enabled", True),
                ))
                logger.info(f"Loaded MCP server config: {name}")
            except Exception as e:
                logger.warning(f"Failed to load MCP config {config_file}: {e}")

    def clear(self) -> None:
        """清除所有注册."""
        self._servers.clear()
