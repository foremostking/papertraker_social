"""Executor 节点测试."""

import pytest
from unittest.mock import AsyncMock, patch

from scholarpilot.agent.executor import scholar_execute_node


class TestExecuteNode:
    """scholar_execute_node 测试."""

    @pytest.mark.asyncio
    async def test_execute_without_plan(self):
        """测试无执行计划时的处理."""
        state = {"execution_plan": {}, "current_step": 0}
        result = await scholar_execute_node(state)
        assert result["current_step"] == 0
        assert "no_plan" in result["completed_steps"]

    @pytest.mark.asyncio
    async def test_execute_first_step(self, sample_state, mock_cnki, mock_ncpssd):
        """测试执行第一个步骤."""
        result = await scholar_execute_node(sample_state)
        assert result["current_step"] == 1  # 推进到下一步
        assert len(result["step_results"]) == 1
        assert result["step_results"][0]["step_type"] == "literature_search"

    @pytest.mark.asyncio
    async def test_execute_all_steps_completed(self, sample_state):
        """测试所有步骤已完成."""
        sample_state["current_step"] = 3  # 已超出步骤数
        result = await scholar_execute_node(sample_state)
        assert result["current_step"] == 3  # 不再推进

    @pytest.mark.asyncio
    async def test_execute_step_failure(self, sample_state):
        """测试步骤执行失败时的处理."""
        with patch("scholarpilot.tools.search.LiteratureSearchManager") as MockMgr:
            instance = MockMgr.return_value
            instance.search_all = AsyncMock(side_effect=Exception("API error"))
            instance.close = AsyncMock()
            result = await scholar_execute_node(sample_state)
            assert len(result["step_results"]) == 1
            assert result["step_results"][0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_execute_outline_step(self, sample_state):
        """测试大纲生成步骤."""
        sample_state["current_step"] = 1  # 大纲生成是第二步
        sample_state["step_results"] = [{
            "step_id": "step_1",
            "name": "文献检索",
            "step_type": "literature_search",
            "status": "completed",
            "result": {"total_count": 100},
        }]

        with patch("scholarpilot.agent.executor.LLMGateway") as MockLLM:
            mock_llm_instance = MockLLM.return_value
            mock_llm_instance.chat = AsyncMock(return_value=json.dumps({
                "title": "测试论文",
                "sections": [{"title": "引言", "word_count": 1000}],
                "abstract": "摘要",
                "keywords": ["关键词1"],
            }))

            result = await scholar_execute_node(sample_state)
            assert result["current_step"] == 2
            assert len(result["step_results"]) == 2


import json