"""ExecutionPlan 模型测试."""

import json
import pytest
from scholarpilot.models.plan import (
    ExecutionPlan,
    ExecutionStep,
    StepType,
    StepStatus,
)


class TestExecutionStep:
    """ExecutionStep 数据模型测试."""

    def test_create_step(self):
        step = ExecutionStep(
            step_id="step_1",
            name="文献检索",
            step_type=StepType.LITERATURE_SEARCH,
            order=1,
        )
        assert step.step_id == "step_1"
        assert step.name == "文献检索"
        assert step.step_type == StepType.LITERATURE_SEARCH
        assert step.order == 1
        assert step.status == StepStatus.PENDING
        assert step.dependencies == []
        assert step.tools == []

    def test_step_serialization(self):
        step = ExecutionStep(
            step_id="step_1",
            name="文献检索",
            step_type=StepType.LITERATURE_SEARCH,
            description="检索CNKI等",
            order=1,
            dependencies=["step_0"],
            tools=["cnki_search"],
            output_key="literature_results",
        )
        data = step.model_dump()
        assert data["step_id"] == "step_1"
        assert data["step_type"] == "literature_search"
        assert data["status"] == "pending"

        # 反序列化
        step2 = ExecutionStep(**data)
        assert step2.step_id == step.step_id
        assert step2.step_type == step.step_type

    def test_step_status_transition(self):
        step = ExecutionStep(step_id="s1", name="test", step_type=StepType.CUSTOM, order=1)
        assert step.status == StepStatus.PENDING
        step.status = StepStatus.IN_PROGRESS
        assert step.status == StepStatus.IN_PROGRESS
        step.status = StepStatus.COMPLETED
        assert step.status == StepStatus.COMPLETED

    def test_invalid_step_type(self):
        """测试无效 step_type 会回退到 CUSTOM."""
        step = ExecutionStep(
            step_id="s1", name="test",
            step_type=StepType.CUSTOM, order=1,
        )
        assert step.step_type == StepType.CUSTOM


class TestExecutionPlan:
    """ExecutionPlan 数据模型测试."""

    def test_create_plan(self, sample_execution_plan):
        plan = ExecutionPlan(**sample_execution_plan)
        assert plan.plan_id == "test_plan"
        assert plan.name == "测试计划"
        assert len(plan.steps) == 3
        assert plan.current_step_index == 0

    def test_get_current_step(self, sample_execution_plan):
        plan = ExecutionPlan(**sample_execution_plan)
        step = plan.get_current_step()
        assert step is not None
        assert step.step_id == "step_1"

    def test_advance(self, sample_execution_plan):
        plan = ExecutionPlan(**sample_execution_plan)
        assert plan.current_step_index == 0

        plan.advance()
        assert plan.current_step_index == 1
        assert plan.get_current_step().step_id == "step_2"

        plan.advance()
        assert plan.current_step_index == 2
        assert plan.get_current_step().step_id == "step_3"

        plan.advance()
        assert plan.current_step_index == 3
        assert plan.get_current_step() is None

    def test_advance_beyond_end(self, sample_execution_plan):
        plan = ExecutionPlan(**sample_execution_plan)
        plan.current_step_index = 3
        plan.advance()
        assert plan.current_step_index == 3  # 不再推进

    def test_serialization(self, sample_execution_plan):
        plan = ExecutionPlan(**sample_execution_plan)
        data = plan.model_dump()
        assert data["plan_id"] == "test_plan"
        assert len(data["steps"]) == 3

        # 反序列化
        plan2 = ExecutionPlan(**data)
        assert plan2.plan_id == plan.plan_id
        assert len(plan2.steps) == len(plan.steps)

    def test_step_dependencies(self, sample_execution_plan):
        plan = ExecutionPlan(**sample_execution_plan)
        step2 = plan.steps[1]
        assert "step_1" in step2.dependencies
        step3 = plan.steps[2]
        assert "step_2" in step3.dependencies

    def test_step_result(self, sample_execution_plan):
        plan = ExecutionPlan(**sample_execution_plan)
        step = plan.get_current_step()
        step.result = {"total_count": 1736, "paper_count": 20}
        assert step.result["total_count"] == 1736
        assert step.result["paper_count"] == 20