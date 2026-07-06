"""Project Memory - 项目记忆管理.

管理项目级别的持久化记忆，包括对话摘要、决策历史和关键信息。
采用同步的 key-value 存储模式，数据持久化到 JSON 文件。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class ProjectMemory:
    """项目记忆管理器.

    持久化存储项目的关键决策、对话摘要和重要信息，
    为 Agent 提供长期记忆支持。

    Usage:
        memory = ProjectMemory(Path("./projects/my_paper/.scholar/memory.json"))
        memory.add("topic_analysis", {"topic": "地方政府债务", "region": "甘肃省"})
        topic_info = memory.get("topic_analysis")
    """

    def __init__(self, memory_path: Path | str | None = None) -> None:
        """初始化项目记忆管理器.

        Args:
            memory_path: 记忆文件路径。如不提供则仅在内存中操作。
        """
        self.memory_path = Path(memory_path) if memory_path else None
        self._data: dict[str, Any] = {"entries": {}}

        # 尝试从磁盘加载
        if self.memory_path and self.memory_path.exists():
            self._load_from_disk()

    def add(self, key: str, value: Any) -> None:
        """添加或更新一条记忆.

        Args:
            key: 记忆键名（如 "topic_analysis", "feasibility"）。
            value: 记忆值（任意可 JSON 序列化的数据）。
        """
        self._data["entries"][key] = {
            "value": value,
            "timestamp": datetime.now().isoformat(),
        }
        self._save_to_disk()

    def get(self, key: str, default: Any = None) -> Any:
        """获取一条记忆.

        Args:
            key: 记忆键名。
            default: 如果不存在，返回的默认值。

        Returns:
            记忆值，如果不存在则返回 default。
        """
        entry = self._data["entries"].get(key)
        if entry:
            return entry["value"]
        return default

    def remove(self, key: str) -> bool:
        """删除一条记忆.

        Args:
            key: 记忆键名。

        Returns:
            是否删除成功。
        """
        if key in self._data["entries"]:
            del self._data["entries"][key]
            self._save_to_disk()
            return True
        return False

    def list_keys(self) -> list[str]:
        """列出所有记忆键名."""
        return list(self._data["entries"].keys())

    def load(self) -> dict[str, Any]:
        """加载所有记忆数据.

        Returns:
            完整的记忆数据字典。
        """
        if self.memory_path and self.memory_path.exists():
            self._load_from_disk()
        return self._data.get("entries", {})

    def clear(self) -> None:
        """清除所有记忆."""
        self._data["entries"] = {}
        self._save_to_disk()

    def get_recent(self, n: int = 10) -> dict[str, Any]:
        """获取最近添加的 n 条记忆.

        Args:
            n: 返回条目数。

        Returns:
            最近的记忆字典。
        """
        entries = self._data.get("entries", {})
        # 按时间戳排序
        sorted_entries = sorted(
            entries.items(),
            key=lambda x: x[1].get("timestamp", ""),
            reverse=True,
        )
        return dict(sorted_entries[:n])

    def _load_from_disk(self) -> None:
        """从磁盘加载记忆数据."""
        if not self.memory_path or not self.memory_path.exists():
            return
        try:
            content = self.memory_path.read_text(encoding="utf-8")
            self._data = json.loads(content)
            # 兼容旧格式：entries 为列表时转换为字典
            if "entries" not in self._data:
                self._data["entries"] = {}
            elif isinstance(self._data["entries"], list):
                # 旧格式（列表）→ 新格式（字典）
                self._data["entries"] = {}
        except (json.JSONDecodeError, OSError):
            self._data = {"entries": {}}

    def _save_to_disk(self) -> None:
        """保存记忆数据到磁盘."""
        if not self.memory_path:
            return
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
