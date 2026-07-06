"""Planner 节点测试."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from scholarpilot.agent.planner import (
    scholar_plan_node,
    _generate_default_plan,
    _extract_json,
)


class TestPlanNode:
    """scholar_plan_node 测试."""

    def test_generate_default_plan(self):
        """测试默认计划生成."""
        result = _generate_default_plan()
        assert "execution_plan" in result
        assert "current_step" in result
        assert result["current_step"] == 0

        plan = result["execution_plan"]
        assert len(plan["steps"]) >= 3
        assert plan["steps"][0]["step_type"] == "literature_search"

    @pytest.mark.asyncio
    async def test_plan_node_without_spec(self):
        """测试无 paper_spec 时的回退."""
        state = {"project_path": "/tmp/test", "paper_spec": {}}
        result = await scholar_plan_node(state)
        assert "execution_plan" in result
        assert result["execution_plan"]["plan_id"] == "plan_default"

    @pytest.mark.asyncio
    async def test_plan_node_with_llm_failure(self, sample_state, mock_llm):
        """测试 LLM 调用失败时的回退."""
        mock_llm.side_effect = Exception("LLM error")
        result = await scholar_plan_node(sample_state)
        assert "execution_plan" in result
        # 应该回退到默认计划
        assert result["execution_plan"]["plan_id"] == "plan_default"

    @pytest.mark.asyncio
    async def test_plan_node_with_llm_success(self, sample_state, mock_llm, mock_llm_response):
        """测试 LLM 正常返回时的计划生成."""
        mock_llm.return_value = json.dumps(mock_llm_response, ensure_ascii=False)
        result = await scholar_plan_node(sample_state)
        assert "execution_plan" in result
        assert result["execution_plan"]["plan_id"] == "mock_plan_001"
        assert len(result["execution_plan"]["steps"]) == 2

    def test_extract_json_from_text(self):
        """测试从文本中提取 JSON."""
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert result["key"] == "value"

    def test_extract_json_direct(self):
        """测试直接 JSON 字符串."""
        text = '{"key": "value"}'
        result = _extract_json(text)
        assert result["key"] == "value"

    def test_extract_json_no_json(self):
        """测试无 JSON 的情况."""
        text = "This is plain text"
        result = _extract_json(text)
        assert result is None