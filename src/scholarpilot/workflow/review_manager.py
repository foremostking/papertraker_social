"""ReviewManager — 跨线程审核暂停/恢复协调器.

ScholarAgent 在后台 asyncio 线程中运行，当到达审核点时：
1. 创建 asyncio.Event 并 await，工作流暂停
2. 通过 callback 发出 ReviewRequestEvent 到前端
3. 前端展示审核 UI，用户做出决策
4. 主线程调用 submit_review()，通过 run_coroutine_threadsafe 唤醒 Event
5. ScholarAgent 读取决策结果，继续执行

线程安全：_pending 字典通过 threading.Lock 保护。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import Any

from scholarpilot.events.types import ReviewResponse

logger = logging.getLogger(__name__)


class ReviewManager:
    """审核管理器 — 线程间暂停/恢复协调.

    Usage（后台线程 / ScholarAgent 侧）::

        review_id = manager.create_review_id("policy_search")
        event = manager.create_review(review_id)
        # 发出 ReviewRequestEvent 到前端...
        response = await manager.wait_for_review(review_id, timeout=3600)
        if response and response.decision == "confirm":
            ...

    Usage（主线程 / WorkflowController 侧）::

        manager.submit_review(review_id, "confirm", feedback="")
        manager.set_event(review_id, loop)
    """

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def create_review_id(phase: str) -> str:
        """生成审核唯一 ID."""
        return f"{phase}_{uuid.uuid4().hex[:8]}"

    def create_review(self, review_id: str) -> asyncio.Event:
        """创建一个审核请求，返回 asyncio.Event 供 await.

        必须在后台 asyncio 线程中调用（Event 需绑定到正确的循环）。

        Args:
            review_id: 审核唯一标识。

        Returns:
            asyncio.Event 对象，调用方 await event.wait() 暂停。
        """
        event = asyncio.Event()
        with self._lock:
            self._pending[review_id] = {"event": event, "response": None}
        logger.info(f"审核请求已创建: {review_id}")
        return event

    async def wait_for_review(
        self, review_id: str, timeout: float = 3600
    ) -> ReviewResponse | None:
        """等待用户审核响应（在后台 asyncio 线程中调用）.

        Args:
            review_id: 审核唯一标识。
            timeout: 超时时间（秒），默认 3600 秒（1 小时）。

        Returns:
            ReviewResponse 对象，超时返回默认 confirm 响应。
        """
        review = self._pending.get(review_id)
        if not review:
            logger.warning(f"审核请求不存在: {review_id}")
            return ReviewResponse(review_id=review_id, decision="confirm")

        try:
            await asyncio.wait_for(review["event"].wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"审核超时（{timeout}s），自动确认: {review_id}")
            return ReviewResponse(
                review_id=review_id, decision="confirm", feedback="超时自动确认"
            )

        return review.get("response")

    def submit_review(
        self, review_id: str, decision: str, feedback: str = ""
    ) -> bool:
        """提交审核结果（从主线程调用）.

        Args:
            review_id: 审核唯一标识。
            decision: 决策 "confirm" | "modify" | "reject"。
            feedback: 修改意见（decision=modify 时填写）。

        Returns:
            是否成功提交（审核 ID 不存在时返回 False）。
        """
        with self._lock:
            review = self._pending.get(review_id)
            if not review:
                logger.warning(f"审核 ID 不存在，无法提交: {review_id}")
                return False

            review["response"] = ReviewResponse(
                review_id=review_id, decision=decision, feedback=feedback
            )
            logger.info(f"审核结果已提交: {review_id} -> {decision}")
            return True

    def set_event(self, review_id: str, loop: asyncio.AbstractEventLoop) -> None:
        """在指定事件循环中设置 Event（唤醒等待的协程）.

        必须从主线程调用，通过 run_coroutine_threadsafe 将 Event.set()
        调度到后台 asyncio 线程中执行。

        Args:
            review_id: 审核唯一标识。
            loop: 后台线程的 asyncio 事件循环。
        """
        review = self._pending.get(review_id)
        if not review:
            logger.warning(f"审核 ID 不存在，无法唤醒: {review_id}")
            return

        event: asyncio.Event = review["event"]
        asyncio.run_coroutine_threadsafe(self._set_event(event), loop)

    @staticmethod
    async def _set_event(event: asyncio.Event) -> None:
        """在 asyncio 线程中设置 Event."""
        event.set()

    def clear(self, review_id: str) -> None:
        """清理已完成的审核."""
        with self._lock:
            self._pending.pop(review_id, None)

    def get_pending_review_ids(self) -> list[str]:
        """获取所有待处理的审核 ID（用于诊断）."""
        with self._lock:
            return list(self._pending.keys())
