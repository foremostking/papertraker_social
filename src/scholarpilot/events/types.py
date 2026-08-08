"""事件类型定义 — 桌面 UI 实时通信的数据结构."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@dataclass
class ProgressEvent:
    """工作流进度事件.

    由 ScholarAgent 在每个 phase 前后发出，通过 WorkflowController
    推送到前端 UI 更新进度面板。

    Attributes:
        phase: 阶段标识，如 "topic_analysis" | "literature_search" | ...
        status: 状态，"start" | "progress" | "complete" | "error"
        message: 人类可读的进度描述
        progress_pct: 子步骤进度 0.0-1.0（可选）
        data: 附加数据（文献数、字数等）
        timestamp: ISO 格式时间戳
    """

    phase: str
    status: str  # "start" | "progress" | "complete" | "error"
    message: str = ""
    progress_pct: float | None = None
    data: dict[str, Any] | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        """序列化为 JSON 字符串，供 evaluate_js 传递给前端."""
        return json.dumps(asdict(self), ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        """转为字典."""
        return asdict(self)


@dataclass
class StepOutput:
    """步骤完成后的输出内容，供前端预览.

    Attributes:
        phase: 阶段标识
        content: Markdown 或 JSON 字符串
        content_type: 内容类型 "markdown" | "json" | "text"
        metadata: 元数据（字数、文献数等）
        saved_at: 保存时间 ISO 格式
    """

    phase: str
    content: str
    content_type: str = "markdown"  # "markdown" | "json" | "text"
    metadata: dict[str, Any] = field(default_factory=dict)
    saved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        """序列化为 JSON 字符串."""
        return json.dumps(asdict(self), ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        """转为字典."""
        return asdict(self)


@runtime_checkable
class WorkflowCallback(Protocol):
    """工作流回调协议 — ScholarAgent 通过此接口通知 UI."""

    def on_progress(self, event: ProgressEvent) -> None:
        """进度更新事件."""
        ...

    def on_step_complete(self, phase: str, output: StepOutput) -> None:
        """步骤完成事件，携带可预览的输出内容."""
        ...

    def on_error(self, phase: str, error: str) -> None:
        """错误事件."""
        ...


class WorkflowCallbackAdapter:
    """回调适配器 — 将回调方法转发给一个简单的 callable.

    用于桌面 UI 场景：Python 后端线程通过此适配器
    调用 window.evaluate_js() 更新前端。
    """

    def __init__(
        self,
        on_progress_fn: Any | None = None,
        on_step_complete_fn: Any | None = None,
        on_error_fn: Any | None = None,
    ) -> None:
        self._on_progress = on_progress_fn
        self._on_step_complete = on_step_complete_fn
        self._on_error = on_error_fn

    def on_progress(self, event: ProgressEvent) -> None:
        if self._on_progress:
            self._on_progress(event)

    def on_step_complete(self, phase: str, output: StepOutput) -> None:
        if self._on_step_complete:
            self._on_step_complete(phase, output)

    def on_error(self, phase: str, error: str) -> None:
        if self._on_error:
            self._on_error(phase, error)
