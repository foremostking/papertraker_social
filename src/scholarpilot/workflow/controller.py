"""WorkflowController — 管理 ScholarAgent 的线程生命周期.

不重复实现 phase 逻辑，只负责：
1. 在后台线程中创建 asyncio 事件循环并运行 ScholarAgent.run()
2. 将 ScholarAgent 的回调事件转发给 UI 更新函数
3. 提供取消功能
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from scholarpilot.agent.scholar import ScholarAgent
from scholarpilot.events.types import (
    ProgressEvent,
    StepOutput,
    WorkflowCallbackAdapter,
)

logger = logging.getLogger(__name__)


class _UICallback(WorkflowCallbackAdapter):
    """将 ScholarAgent 回调转发给 UI 更新函数."""

    def __init__(self, ui_update_fn: Any) -> None:
        super().__init__()
        self._ui_update_fn = ui_update_fn

    def on_progress(self, event: ProgressEvent) -> None:
        if self._ui_update_fn:
            try:
                self._ui_update_fn("progress", event.to_dict())
            except Exception as e:
                logger.debug(f"UI on_progress 转发失败: {e}")

    def on_step_complete(self, phase: str, output: StepOutput) -> None:
        if self._ui_update_fn:
            try:
                self._ui_update_fn("step_complete", output.to_dict())
            except Exception as e:
                logger.debug(f"UI on_step_complete 转发失败: {e}")

    def on_error(self, phase: str, error: str) -> None:
        if self._ui_update_fn:
            try:
                self._ui_update_fn("error", {"phase": phase, "error": error})
            except Exception as e:
                logger.debug(f"UI on_error 转发失败: {e}")


class WorkflowController:
    """管理 ScholarAgent 的生命周期，不重复实现 phase 逻辑.

    线程模型：
        - 主线程：pywebview UI 事件循环
        - 后台线程：asyncio 事件循环运行 ScholarAgent.run()
        - 通信：通过 ui_callback 函数调用 window.evaluate_js()（线程安全）

    Usage:
        controller = WorkflowController(project_dir, ui_callback)
        controller.start("我想写一篇关于地方政府债务的论文")
        # ... 用户点击取消 ...
        controller.cancel()
    """

    def __init__(
        self,
        project_dir: Path,
        ui_callback: Any,
        config: Any = None,
        cnki_cookie: str = "",
    ) -> None:
        """初始化控制器.

        Args:
            project_dir: 项目目录路径
            ui_callback: UI 更新回调函数，签名 (event_type: str, data: dict) -> None
            config: ScholarAgent 配置对象（可选）
            cnki_cookie: CNKI 登录 Cookie（可选）
        """
        self.project_dir = Path(project_dir)
        self.ui_callback = ui_callback
        self.config = config
        self.cnki_cookie = cnki_cookie

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cancel_event = threading.Event()
        self._is_running = False

    def start(self, topic: str) -> None:
        """在后台线程中启动工作流.

        Args:
            topic: 用户的研究想法/主题
        """
        if self._is_running:
            logger.warning("工作流已在运行中，忽略重复启动请求")
            return

        self._cancel_event.clear()
        self._is_running = True

        self._thread = threading.Thread(
            target=self._run_in_thread,
            args=(topic,),
            daemon=True,
            name="ScholarAgent-Worker",
        )
        self._thread.start()

    def _run_in_thread(self, topic: str) -> None:
        """后台线程：创建 asyncio 循环并运行 ScholarAgent."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        callback = _UICallback(self.ui_callback)

        agent = ScholarAgent(
            project_dir=self.project_dir,
            config=self.config,
            cnki_cookie=self.cnki_cookie,
            callback=callback,
        )
        # 桌面 UI 模式下自动跳过交互提示
        agent.non_interactive = True

        try:
            self._loop.run_until_complete(agent.run(topic))
        except asyncio.CancelledError:
            logger.info("工作流被用户取消")
        except Exception as e:
            logger.error(f"工作流异常: {e}", exc_info=True)
            try:
                callback.on_error("fatal", str(e))
            except Exception:
                pass
        finally:
            self._is_running = False
            self._loop.close()
            self._loop = None

    def cancel(self) -> None:
        """请求取消工作流.

        通过取消 asyncio 事件循环中的任务来实现。
        注意：LLM 请求可能需要几秒才能响应取消。
        """
        self._cancel_event.set()

        if self._loop and self._loop.is_running():
            # 在事件循环中安排取消
            asyncio.run_coroutine_threadsafe(
                self._cancel_tasks(), self._loop
            )

    async def _cancel_tasks(self) -> None:
        """取消事件循环中的所有任务."""
        tasks = asyncio.all_tasks(self._loop)
        for task in tasks:
            task.cancel()

    @property
    def is_running(self) -> bool:
        """工作流是否正在运行."""
        return self._is_running

    def wait(self, timeout: float | None = None) -> None:
        """等待工作流完成（阻塞）.

        Args:
            timeout: 超时时间（秒），None 表示无限等待
        """
        if self._thread:
            self._thread.join(timeout=timeout)
