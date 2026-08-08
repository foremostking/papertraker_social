"""ScholarPilot 数据模型.

定义论文、规格、执行计划等核心数据结构。
"""

from .enums import EvidenceStrength
from .paper import Paper
from .plan import ExecutionPlan, ExecutionStep
from .spec import PaperSpec

__all__ = [
    "Paper",
    "PaperSpec",
    "ExecutionPlan",
    "ExecutionStep",
    "EvidenceStrength",
]
