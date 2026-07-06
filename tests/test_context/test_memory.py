"""ProjectMemory 测试."""

import json
import pytest
from pathlib import Path
from scholarpilot.context.memory import ProjectMemory


class TestProjectMemory:
    """ProjectMemory CRUD 和持久化测试."""

    def test_create_memory(self, temp_project_dir):
        memory_path = temp_project_dir / ".scholar" / "memory.json"
        mem = ProjectMemory(memory_path)
        assert mem.memory_path == memory_path

    def test_add_and_get(self, temp_project_dir):
        memory_path = temp_project_dir / ".scholar" / "memory.json"
        mem = ProjectMemory(memory_path)

        mem.add("topic", "地方政府债务")
        assert mem.get("topic") == "地方政府债务"

    def test_add_dict(self, temp_project_dir):
        memory_path = temp_project_dir / ".scholar" / "memory.json"
        mem = ProjectMemory(memory_path)

        mem.add("paper_spec", {"topic": "test", "region": "中国"})
        result = mem.get("paper_spec")
        assert result["topic"] == "test"
        assert result["region"] == "中国"

    def test_get_missing_key(self, temp_project_dir):
        memory_path = temp_project_dir / ".scholar" / "memory.json"
        mem = ProjectMemory(memory_path)
        assert mem.get("nonexistent") is None
        assert mem.get("nonexistent", "default") == "default"

    def test_persistence(self, temp_project_dir):
        memory_path = temp_project_dir / ".scholar" / "memory.json"
        mem = ProjectMemory(memory_path)
        mem.add("topic", "地方政府债务")
        mem.add("year", "2025")

        # 重新加载
        mem2 = ProjectMemory(memory_path)
        assert mem2.get("topic") == "地方政府债务"
        assert mem2.get("year") == "2025"

    def test_overwrite(self, temp_project_dir):
        memory_path = temp_project_dir / ".scholar" / "memory.json"
        mem = ProjectMemory(memory_path)

        mem.add("key", "value1")
        assert mem.get("key") == "value1"

        mem.add("key", "value2")
        assert mem.get("key") == "value2"

    def test_empty_memory(self, temp_project_dir):
        memory_path = temp_project_dir / ".scholar" / "memory.json"
        mem = ProjectMemory(memory_path)
        assert mem.get("anything") is None

    def test_memory_file_format(self, temp_project_dir):
        memory_path = temp_project_dir / ".scholar" / "memory.json"
        mem = ProjectMemory(memory_path)
        mem.add("key1", "value1")
        mem.add("key2", 42)

        # 检查文件内容格式
        content = memory_path.read_text(encoding="utf-8")
        data = json.loads(content)
        assert "entries" in data
        assert data["entries"]["key1"]["value"] == "value1"
        assert data["entries"]["key2"]["value"] == 42