"""执行计划生成节点.

根据论文规格生成结构化的执行计划。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from scholarpilot.config import get_settings
from scholarpilot.context.engine import ContextEngine
from scholarpilot.context.memory import ProjectMemory
from scholarpilot.llm.gateway import LLMGateway
from scholarpilot.models.plan import ExecutionPlan, ExecutionStep, StepType

from .state import ScholarState

logger = logging.getLogger(__name__)


async def scholar_plan_node(state: ScholarState) -> dict:
    """生成论文写作执行计划.

    根据论文规格（paper_spec），生成具体的执行步骤列表，
    包括文献检索、大纲编写、各章节撰写、引用管理等。

    流程：
    1. 提取 paper_spec 和 project_path
    2. 构建 LLM 上下文窗口
    3. LLM 生成 JSON 格式的执行步骤
    4. 使用 ExecutionPlan Pydantic 模型验证
    5. 保存到 .scholar/plan.json

    Args:
        state: 当前 Agent 状态。

    Returns:
        包含 execution_plan 和 current_step 的状态更新字典。
    """
    config = get_settings()
    llm = LLMGateway(config)
    project_path = state.get("project_path", "")
    paper_spec = state.get("paper_spec", {})

    if not paper_spec:
        logger.warning("No paper_spec in state, using default plan")
        return _generate_default_plan()

    project_dir = Path(project_path) if project_path else None

    # 构建上下文
    memory = ProjectMemory(project_dir / ".scholar" / "memory.json") if project_dir else None
    context_engine = ContextEngine(memory) if memory else None

    if context_engine:
        ctx = context_engine.build_plan_context(
            user_input=paper_spec.get("topic", ""),
            project_state=paper_spec,
        )
        messages = ctx.to_messages()
    else:
        # 回退：直接用 paper_spec 构建 prompt
        from scholarpilot.context.prompts import SCHOLAR_SYSTEM_PROMPT
        spec_json = json.dumps(paper_spec, ensure_ascii=False, indent=2)
        messages = [
            {"role": "system", "content": SCHOLAR_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"请根据以下论文规格，生成一个结构化的执行计划（JSON 格式）。\n\n"
                f"论文规格：\n{spec_json}\n\n"
                f"请生成包含以下步骤类型的执行计划：\n"
                f"- literature_search: 文献检索\n"
                f"- outline_generation: 大纲生成\n"
                f"- section_writing: 章节撰写\n"
                f"- citation_management: 引用管理\n"
                f"- formatting: 格式化导出\n"
            )},
        ]

    # 调用 LLM 生成计划
    try:
        response = await llm.chat(
            messages=messages,
            model=config.default_analysis_model,
            temperature=0.3,
        )
    except Exception as e:
        logger.error(f"LLM plan generation failed: {e}")
        return _generate_default_plan()

    # 提取 JSON
    plan_data = _extract_json(response)
    if not plan_data:
        logger.warning("Failed to parse LLM plan response, using default")
        return _generate_default_plan()

    # 用 Pydantic 模型验证
    try:
        steps_data = plan_data.get("steps", [])
        validated_steps = []
        for i, step in enumerate(steps_data):
            # 映射 step_type 字符串到枚举
            step_type_str = step.get("step_type", "custom")
            try:
                step_type = StepType(step_type_str)
            except ValueError:
                step_type = StepType.CUSTOM

            validated_steps.append(ExecutionStep(
                step_id=step.get("step_id", f"step_{i+1}"),
                name=step.get("name", f"步骤 {i+1}"),
                step_type=step_type,
                description=step.get("description", ""),
                order=step.get("order", i + 1),
                dependencies=step.get("dependencies", []),
                tools=step.get("tools", []),
                model=step.get("model"),
                input_prompt=step.get("input_prompt", ""),
                output_key=step.get("output_key", ""),
            ))

        plan = ExecutionPlan(
            plan_id=plan_data.get("plan_id", "plan_001"),
            name=plan_data.get("name", "论文写作计划"),
            description=plan_data.get("description", ""),
            steps=validated_steps,
        )

        # 保存到文件
        if project_dir:
            plan_path = project_dir / ".scholar" / "plan.json"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(
                plan.model_dump_json(indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"Execution plan saved to {plan_path}")

        return {
            "execution_plan": plan.model_dump(),
            "current_step": 0,
        }

    except Exception as e:
        logger.error(f"Failed to validate execution plan: {e}")
        return _generate_default_plan()


def _generate_default_plan() -> dict:
    """生成默认的执行计划（回退方案）."""
    default_steps = [
        ExecutionStep(
            step_id="step_1",
            name="文献检索",
            step_type=StepType.LITERATURE_SEARCH,
            description="检索CNKI、NCPSSD、Semantic Scholar、arXiv等文献源",
            order=1,
            tools=["cnki_search", "ncpssd_search", "ss_search", "arxiv_search"],
            output_key="literature_results",
        ),
        ExecutionStep(
            step_id="step_2",
            name="大纲生成",
            step_type=StepType.OUTLINE_GENERATION,
            description="基于文献检索结果生成论文大纲",
            order=2,
            dependencies=["step_1"],
            output_key="outline",
        ),
        ExecutionStep(
            step_id="step_3",
            name="章节撰写",
            step_type=StepType.SECTION_WRITING,
            description="基于大纲逐章撰写论文内容",
            order=3,
            dependencies=["step_2"],
            output_key="draft_sections",
        ),
        ExecutionStep(
            step_id="step_4",
            name="引用管理",
            step_type=StepType.CITATION_MANAGEMENT,
            description="生成BibTeX引用并格式化脚注",
            order=4,
            dependencies=["step_3"],
            output_key="references",
        ),
        ExecutionStep(
            step_id="step_5",
            name="格式化导出",
            step_type=StepType.FORMATTING,
            description="导出为Word和LaTeX格式",
            order=5,
            dependencies=["step_4"],
            output_key="final_output",
        ),
    ]

    plan = ExecutionPlan(
        plan_id="plan_default",
        name="论文写作默认计划",
        description="自动生成的默认执行计划",
        steps=default_steps,
    )

    return {
        "execution_plan": plan.model_dump(),
        "current_step": 0,
    }


def _extract_json(text: str) -> dict[str, Any] | None:
    """从 LLM 响应中提取 JSON."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None