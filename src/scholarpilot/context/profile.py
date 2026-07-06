"""Researcher Profile - 研究者长期画像.

管理跨论文项目的长期记忆，包括：
- 期刊偏好（目标期刊、格式要求）
- 写作风格偏好（语言习惯、学术规范）
- 常用研究方法论
- 学科领域
- 已完成论文的历史记录

这是三级记忆体系的最顶层：工作记忆(当前任务) → 项目记忆(当前论文) → 长期记忆(研究者画像)。
所有论文项目共享同一份画像，实现跨论文的经验积累。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class ResearcherProfile:
    """研究者长期画像管理器.

    持久化存储研究者的跨论文偏好和历史记录，
    让 Agent 在处理新论文时能复用已有经验。

    存储位置：~/.scholarpilot/profile.json（用户主目录下，全局共享）

    Usage:
        profile = ResearcherProfile()
        profile.set_preference("target_journal", "财贸经济")
        profile.set_preference("writing_style", "实证导向，强调政策含义")
        journal = profile.get_preference("target_journal")
        # → "财贸经济"

        # 记录一篇完成的论文
        profile.add_paper_record({
            "project_name": "debt_spillover",
            "title": "地方政府债务风险空间溢出效应研究",
            "topic": "地方政府债务",
            "target_journal": "财贸经济",
            "research_type": "empirical",
            "completed_at": "2026-07-01",
        })
    """

    # 画像数据结构定义
    DEFAULT_DATA: dict[str, Any] = {
        "preferences": {},  # 偏好键值对
        "paper_records": [],  # 已完成论文记录列表
        "created_at": None,
        "updated_at": None,
    }

    def __init__(self, profile_path: Path | str | None = None) -> None:
        """初始化研究者画像.

        Args:
            profile_path: 画像文件路径。默认为 ~/.scholarpilot/profile.json。
        """
        if profile_path is None:
            profile_path = Path.home() / ".scholarpilot" / "profile.json"
        self.profile_path = Path(profile_path)
        # 初始化默认结构（创建独立副本，避免类变量可变对象共享引用）
        self._data: dict[str, Any] = {
            "preferences": {},
            "paper_records": [],
            "created_at": None,
            "updated_at": None,
        }

        # 从磁盘加载
        self._load_from_disk()

    # ===== 偏好管理 =====

    def set_preference(self, key: str, value: Any) -> None:
        """设置一个偏好项.

        Args:
            key: 偏好键名，如 "target_journal", "writing_style", "methodology"。
            value: 偏好值。
        """
        self._data["preferences"][key] = value
        self._save_to_disk()

    def get_preference(self, key: str, default: Any = None) -> Any:
        """获取一个偏好项.

        Args:
            key: 偏好键名。
            default: 不存在时的默认值。

        Returns:
            偏好值。
        """
        return self._data["preferences"].get(key, default)

    def get_all_preferences(self) -> dict[str, Any]:
        """获取所有偏好."""
        return dict(self._data.get("preferences", {}))

    def remove_preference(self, key: str) -> bool:
        """删除一个偏好项.

        Returns:
            是否删除成功。
        """
        if key in self._data["preferences"]:
            del self._data["preferences"][key]
            self._save_to_disk()
            return True
        return False

    # ===== 论文历史记录 =====

    def add_paper_record(self, record: dict[str, Any]) -> None:
        """添加一条论文完成记录.

        Args:
            record: 论文记录，建议包含：
                - project_name: 项目名称
                - title: 论文标题
                - topic: 研究主题
                - target_journal: 目标期刊
                - research_type: 研究类型
                - completed_at: 完成时间
        """
        if "completed_at" not in record:
            record["completed_at"] = datetime.now().isoformat()
        self._data["paper_records"].append(record)
        self._save_to_disk()

    def get_paper_records(self) -> list[dict[str, Any]]:
        """获取所有论文记录."""
        return list(self._data.get("paper_records", []))

    def get_recent_papers(self, n: int = 5) -> list[dict[str, Any]]:
        """获取最近的 n 篇论文记录.

        Args:
            n: 返回条目数。

        Returns:
            最近的论文记录列表。
        """
        records = self._data.get("paper_records", [])
        return records[-n:] if records else []

    def find_papers_by_topic(self, topic: str) -> list[dict[str, Any]]:
        """按主题关键词查找历史论文记录.

        Args:
            topic: 主题关键词。

        Returns:
            匹配的论文记录列表。
        """
        results = []
        topic_lower = topic.lower()
        for record in self._data.get("paper_records", []):
            record_topic = str(record.get("topic", "")).lower()
            if topic_lower in record_topic:
                results.append(record)
        return results

    # ===== 画像摘要（用于注入 LLM 上下文）=====

    def to_context_string(self) -> str:
        """生成画像摘要文本，供注入 LLM 上下文使用.

        Returns:
            格式化的画像摘要字符串。如果画像为空，返回提示信息。
        """
        prefs = self._data.get("preferences", {})
        papers = self._data.get("paper_records", [])

        if not prefs and not papers:
            return "（暂无研究者画像，这是首次使用）"

        lines = ["## 研究者画像（跨论文长期记忆）"]

        # 偏好
        if prefs:
            lines.append("\n### 偏好设置")
            pref_labels = {
                "target_journal": "目标期刊",
                "writing_style": "写作风格",
                "methodology": "常用方法论",
                "discipline": "学科领域",
                "language": "论文语言",
                "data_sources": "常用数据来源",
            }
            for key, value in prefs.items():
                label = pref_labels.get(key, key)
                lines.append(f"- {label}: {value}")

        # 论文历史
        if papers:
            lines.append(f"\n### 历史论文记录（共 {len(papers)} 篇）")
            recent = papers[-3:]  # 最近3篇
            for i, record in enumerate(recent, 1):
                title = record.get("title", record.get("project_name", "未知"))
                journal = record.get("target_journal", "")
                journal_str = f" → {journal}" if journal else ""
                lines.append(f"{i}. {title}{journal_str}")

        return "\n".join(lines)

    # ===== 持久化 =====

    def _load_from_disk(self) -> None:
        """从磁盘加载画像数据."""
        if not self.profile_path.exists():
            return
        try:
            content = self.profile_path.read_text(encoding="utf-8")
            loaded = json.loads(content)
            # 合并到默认结构（保留新字段，兼容旧数据）
            if "preferences" in loaded:
                self._data["preferences"] = loaded["preferences"]
            if "paper_records" in loaded:
                self._data["paper_records"] = loaded["paper_records"]
            if "created_at" in loaded:
                self._data["created_at"] = loaded["created_at"]
            else:
                self._data["created_at"] = datetime.now().isoformat()
        except (json.JSONDecodeError, OSError):
            pass  # 加载失败时保持默认空结构

    def _save_to_disk(self) -> None:
        """保存画像数据到磁盘."""
        self._data["updated_at"] = datetime.now().isoformat()
        if not self._data.get("created_at"):
            self._data["created_at"] = self._data["updated_at"]

        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
