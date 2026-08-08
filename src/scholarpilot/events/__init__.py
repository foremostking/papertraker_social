"""事件系统 — 桌面 UI 与 ScholarAgent 之间的通信协议."""

from scholarpilot.events.types import (
    ProgressEvent,
    StepOutput,
    WorkflowCallback,
    WorkflowCallbackAdapter,
)

__all__ = [
    "ProgressEvent",
    "StepOutput",
    "WorkflowCallback",
    "WorkflowCallbackAdapter",
]
