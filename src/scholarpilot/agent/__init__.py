"""ScholarPilot Agent 模块.

基于 LangGraph 构建的学术写作 Agent 状态图。
核心组件是 ScholarAgent 类，负责协调选题分析、文献检索、大纲生成和论文撰写。
"""

from .state import ScholarState
from .scholar import ScholarAgent

__all__ = ["ScholarState", "ScholarAgent"]
