"""ScholarState - Scholar Agent 的全局状态定义.

所有节点共享的状态结构，遵循 LangGraph 的 TypedDict 模式。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional

from langgraph.graph import add_messages
from typing_extensions import TypedDict


class ScholarState(TypedDict, total=False):
    """Scholar Agent 的全局共享状态.

    Attributes:
        messages: 对话消息历史，使用 add_messages reducer 自动追加。
        project_name: 当前论文项目名称。
        project_path: 项目目录的绝对路径。
        paper_spec: 论文规格描述（主题、方向、约束等）。
        execution_plan: 当前执行计划。
        current_step: 当前执行步骤索引。
        completed_steps: 已完成的步骤列表。
        step_results: 各步骤的执行结果。
        human_feedback: 用户在 review 节点提供的反馈。
        needs_revision: 是否需要根据反馈进行修订。
        final_output: 最终生成的论文输出路径或内容。
        metadata: 其他元数据。
    """

    # ── 对话状态 ──────────────────────────────────────────
    messages: Annotated[list, add_messages]

    # ── 项目信息 ──────────────────────────────────────────
    project_name: Optional[str]
    project_path: Optional[str]

    # ── 论文规格 ──────────────────────────────────────────
    paper_spec: Optional[dict[str, Any]]

    # ── 执行计划 ──────────────────────────────────────────
    execution_plan: Optional[dict[str, Any]]
    current_step: Optional[int]
    completed_steps: list[str]
    step_results: Annotated[list[dict[str, Any]], operator.add]

    # ── Human Review ───────────────────────────────────────
    human_feedback: Optional[str]
    needs_revision: bool

    # ── 输出 ──────────────────────────────────────────────
    final_output: Optional[str]

    # ── 元数据 ────────────────────────────────────────────
    metadata: dict[str, Any]
