"""ExecutionPlan - 执行计划模型.

描述论文写作的结构化执行步骤和依赖关系。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    """步骤状态枚举."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepType(str, Enum):
    """步骤类型枚举."""

    LITERATURE_SEARCH = "literature_search"
    OUTLINE_GENERATION = "outline_generation"
    SECTION_WRITING = "section_writing"
    CITATION_MANAGEMENT = "citation_management"
    REVISION = "revision"
    FORMATTING = "formatting"
    REVIEW = "review"
    CUSTOM = "custom"


class ExecutionStep(BaseModel):
    """单个执行步骤.

    Attributes:
        step_id: 步骤唯一标识.
        name: 步骤名称.
        step_type: 步骤类型.
        description: 步骤详细描述.
        order: 执行顺序.
        dependencies: 依赖的步骤 ID 列表.
        status: 当前状态.
        tools: 需要使用的工具列表.
        model: 推荐使用的 LLM 模型.
        input_prompt: 输入提示模板.
        output_key: 输出结果存储键.
    """

    step_id: str
    name: str
    step_type: StepType = StepType.CUSTOM
    description: str = ""
    order: int = 0
    dependencies: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    tools: list[str] = Field(default_factory=list)
    model: Optional[str] = None
    input_prompt: str = ""
    output_key: str = ""
    result: Optional[dict[str, Any]] = None


class ExecutionPlan(BaseModel):
    """执行计划.

    包含一系列有序的执行步骤，构成完整的论文写作流程。

    Attributes:
        plan_id: 计划唯一标识.
        name: 计划名称.
        description: 计划描述.
        steps: 执行步骤列表.
        current_step_index: 当前执行步骤索引.
        total_steps: 总步骤数.
    """

    plan_id: str = ""
    name: str = ""
    description: str = ""
    steps: list[ExecutionStep] = Field(default_factory=list)
    current_step_index: int = 0

    @property
    def total_steps(self) -> int:
        """返回总步骤数."""
        return len(self.steps)

    @property
    def is_complete(self) -> bool:
        """检查计划是否已全部完成."""
        return all(s.status == StepStatus.COMPLETED for s in self.steps)

    def get_current_step(self) -> Optional[ExecutionStep]:
        """获取当前待执行的步骤."""
        if self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def advance(self) -> Optional[ExecutionStep]:
        """推进到下一步."""
        if self.current_step_index < len(self.steps):
            self.current_step_index += 1
        return self.get_current_step()
