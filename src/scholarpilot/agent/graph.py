"""LangGraph StateGraph 定义 - Scholar Agent 的核心工作流.

定义了学术写作 Agent 的完整状态图：
规划 -> 执行（循环） -> 人工审核 -> 定稿，
支持条件路由、步骤回退和中断恢复。

Usage:
    # 基本用法
    from scholarpilot.agent.graph import create_scholar_graph
    graph = create_scholar_graph()
    compiled = graph.compile()

    # 带 Checkpoint 恢复
    compiled = graph.compile(checkpointer=create_checkpointer("./checkpoints.db"))
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .executor import scholar_execute_node
from .planner import scholar_plan_node
from .review import human_review_node
from .scholar import scholar_finalize_node
from .state import ScholarState


def create_scholar_graph() -> StateGraph:
    """创建 Scholar Agent 的 LangGraph 状态图.

    工作流：
        START
          │
          ▼
    scholar_plan ── 生成执行计划
          │
          ▼
    scholar_execute ── 执行当前步骤
          │
          ├── 还有步骤 → 循环回 scholar_execute
          │
          ▼
    human_review ── 等待用户审核
          │
          ├── needs_revision → scholar_execute（回退执行）
          │
          ▼
    scholar_finalize ── 合并草稿、导出终稿
          │
          ▼
         END

    Returns:
        构建完成的 StateGraph 对象（尚未编译）。
    """
    builder = StateGraph(ScholarState)

    # 添加节点
    builder.add_node("scholar_plan", scholar_plan_node)
    builder.add_node("scholar_execute", scholar_execute_node)
    builder.add_node("human_review", human_review_node)
    builder.add_node("scholar_finalize", scholar_finalize_node)

    # ── 边 ─────────────────────────────────────────────────

    # START → 规划
    builder.add_edge(START, "scholar_plan")

    # 规划 → 执行
    builder.add_edge("scholar_plan", "scholar_execute")

    # 执行 → 条件路由：还有步骤继续，否则进入审核
    builder.add_conditional_edges(
        "scholar_execute",
        _should_execute_more,
        {
            "scholar_execute": "scholar_execute",  # 循环执行下一步
            "human_review": "human_review",         # 全部完成，进入审核
            "scholar_finalize": "scholar_finalize",  # 跳过审核，直接定稿
        },
    )

    # 审核 → 条件路由：需要修改回退，否则定稿
    builder.add_conditional_edges(
        "human_review",
        _review_decision,
        {
            "scholar_execute": "scholar_execute",  # 回退执行
            "scholar_finalize": "scholar_finalize",  # 进入定稿
            END: END,                               # 用户退出
        },
    )

    # 定稿 → 结束
    builder.add_edge("scholar_finalize", END)

    return builder


def create_checkpointer(db_path: str | Path = "checkpoints.db") -> SqliteSaver:
    """创建 SQLite Checkpointer（用于中断恢复）.

    Args:
        db_path: 数据库文件路径。

    Returns:
        SqliteSaver 实例。
    """
    return SqliteSaver.from_conn_string(str(db_path))


def _should_execute_more(state: ScholarState) -> str:
    """判断是否还有更多步骤需要执行.

    Args:
        state: 当前 Agent 状态。

    Returns:
        下一个节点名称。
    """
    execution_plan = state.get("execution_plan", {})
    current_step = state.get("current_step", 0)
    paper_spec = state.get("paper_spec", {})

    # 无计划 → 直接定稿
    steps = execution_plan.get("steps", [])
    if not steps:
        return "scholar_finalize"

    # 还有步骤 → 继续执行
    if current_step < len(steps):
        return "scholar_execute"

    # 无 paper_spec 且无步骤结果 → 直接定稿（跳过审核）
    if not paper_spec and not state.get("step_results"):
        return "scholar_finalize"

    # 全部完成 → 进入审核
    return "human_review"


def _review_decision(state: ScholarState) -> str:
    """根据审核结果决定下一步路由.

    Args:
        state: 当前 Agent 状态。

    Returns:
        下一个节点名称。
    """
    needs_revision = state.get("needs_revision", False)
    feedback = state.get("human_feedback", "")

    # 用户退出
    if feedback == "exited":
        return END

    # 需要修改 → 回退到执行节点
    if needs_revision:
        return "scholar_execute"

    # 通过 → 进入定稿
    return "scholar_finalize"