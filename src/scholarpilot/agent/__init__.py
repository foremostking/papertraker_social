"""ScholarPilot Agent 模块.

基于 LangGraph 构建的学术写作 Agent 状态图。
核心编排路径：agent.graph.create_scholar_graph()
（过程式 ScholarAgent 保留但弃用中，见 ADR-003）。
"""

from .state import ScholarState
from .scholar import ScholarAgent
from .graph import create_scholar_graph

__all__ = ["ScholarState", "ScholarAgent", "create_scholar_graph"]
