"""pytest 配置和 fixtures."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def temp_project_dir() -> Path:
    """创建临时项目目录结构."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "test_project"
        project_dir.mkdir(parents=True)

        # 创建基本目录结构
        (project_dir / "draft").mkdir(exist_ok=True)
        (project_dir / "literature").mkdir(exist_ok=True)
        (project_dir / ".scholar").mkdir(exist_ok=True)

        yield project_dir


@pytest.fixture
def sample_paper_spec() -> dict[str, Any]:
    """示例论文规格."""
    return {
        "topic": "地方政府债务",
        "region": "中国",
        "content": "空间溢出效应",
        "research_type": "empirical",
        "year_start": "2020",
        "year_end": "2026",
        "analysis": "研究地方政府债务的空间溢出效应",
    }


@pytest.fixture
def sample_execution_plan() -> dict[str, Any]:
    """示例执行计划."""
    return {
        "plan_id": "test_plan",
        "name": "测试计划",
        "description": "用于测试的执行计划",
        "steps": [
            {
                "step_id": "step_1",
                "name": "文献检索",
                "step_type": "literature_search",
                "description": "检索CNKI、NCPSSD等",
                "order": 1,
                "dependencies": [],
                "tools": ["cnki_search"],
                "input_prompt": "",
                "output_key": "literature_results",
            },
            {
                "step_id": "step_2",
                "name": "大纲生成",
                "step_type": "outline_generation",
                "description": "生成论文大纲",
                "order": 2,
                "dependencies": ["step_1"],
                "tools": [],
                "input_prompt": "",
                "output_key": "outline",
            },
            {
                "step_id": "step_3",
                "name": "章节撰写",
                "step_type": "section_writing",
                "description": "撰写论文章节",
                "order": 3,
                "dependencies": ["step_2"],
                "tools": [],
                "input_prompt": "",
                "output_key": "draft_sections",
            },
        ],
    }


@pytest.fixture
def sample_state(sample_paper_spec, sample_execution_plan) -> dict[str, Any]:
    """示例 ScholarState."""
    return {
        "project_path": str(Path(tempfile.gettempdir()) / "test_project"),
        "paper_spec": sample_paper_spec,
        "execution_plan": sample_execution_plan,
        "current_step": 0,
        "completed_steps": [],
        "step_results": [],
        "human_feedback": "",
        "needs_revision": False,
        "final_output": "",
    }


@pytest.fixture
def mock_llm_response() -> dict[str, Any]:
    """模拟 LLM 返回的 JSON 响应."""
    return {
        "plan_id": "mock_plan_001",
        "name": "模拟论文写作计划",
        "description": "由 mock LLM 生成的执行计划",
        "steps": [
            {
                "step_id": "step_1",
                "name": "文献检索与综述",
                "step_type": "literature_search",
                "description": "检索相关文献",
                "order": 1,
                "dependencies": [],
                "tools": ["cnki_search", "ncpssd_search"],
                "input_prompt": "",
                "output_key": "literature_results",
            },
            {
                "step_id": "step_2",
                "name": "论文大纲编写",
                "step_type": "outline_generation",
                "description": "根据文献综述生成大纲",
                "order": 2,
                "dependencies": ["step_1"],
                "tools": [],
                "input_prompt": "",
                "output_key": "outline",
            },
        ],
    }


@pytest.fixture
def mock_llm(mock_llm_response):
    """Mock LLMGateway.chat 方法."""
    with patch("scholarpilot.llm.gateway.LLMGateway.chat") as mock_chat:
        mock_chat.return_value = json.dumps(mock_llm_response, ensure_ascii=False)
        yield mock_chat


@pytest.fixture
def mock_search_manager():
    """Mock LiteratureSearchManager."""
    mock_result = MagicMock()
    mock_result.total_count = 1736
    mock_result.all_papers = []
    mock_result.chinese_result = None

    with patch("scholarpilot.tools.search.LiteratureSearchManager") as MockManager:
        instance = MockManager.return_value
        instance.search_all = AsyncMock(return_value=mock_result)
        instance.close = AsyncMock()
        yield instance


@pytest.fixture
def mock_ncpssd():
    """Mock NCPSSDEngine."""
    mock_result = MagicMock()
    mock_result.total_count = 703
    mock_result.papers = []

    with patch("scholarpilot.mcp.servers.ncpssd.NCPSSDEngine") as MockEngine:
        instance = MockEngine.return_value
        instance.search = AsyncMock(return_value=mock_result)
        instance.close = AsyncMock()
        yield instance


@pytest.fixture
def mock_cnki():
    """Mock CNKIAiohttpEngine."""
    mock_result = MagicMock()
    mock_result.total_count = 1736
    mock_result.papers = []

    with patch("scholarpilot.mcp.servers.cnki.aiohttp_engine.CNKIAiohttpEngine") as MockEngine:
        instance = MockEngine.return_value
        instance.search = AsyncMock(return_value=mock_result)
        instance.close = AsyncMock()
        yield instance