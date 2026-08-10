"""ScholarPilot 桌面应用主入口 — pywebview.

使用 pywebview 创建桌面窗口，前端用 HTML/CSS/JS，
后端 Python 直接调用 ScholarAgent。

启动方式：
    python -m scholarpilot.desktop.app
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from scholarpilot.config import get_settings
from scholarpilot.utils.file_manager import FileManager
from scholarpilot.workflow.controller import WorkflowController
from scholarpilot.workflow.feedback import FeedbackHandler

logger = logging.getLogger(__name__)


class DesktopApp:
    """pywebview 桌面应用 — 暴露 Python API 给前端 JS.

    所有 public 方法自动暴露给 JS，前端通过
    window.pywebview.api.method_name() 调用。
    """

    def __init__(self) -> None:
        self._window: Any = None  # 下划线前缀，避免 pywebview 递归遍历
        self._controller: WorkflowController | None = None
        self._config = get_settings()
        self._file_manager = FileManager(self._config.projects_dir)

    # ── 项目管理 API ──────────────────────────────────

    def get_project_list(self) -> str:
        """获取项目列表，返回 JSON 字符串.

        Returns:
            JSON 格式的项目列表
        """
        try:
            project_names = self._file_manager.list_projects()
            projects = []
            for name in project_names:
                project_dir = self._file_manager.get_project_dir(name)
                if not project_dir:
                    continue
                meta = self._file_manager.get_project_meta(project_dir) or {}
                progress = self._file_manager.load_progress(project_dir) or {}
                completed_phases = progress.get("completed_phases", [])
                completed_sections = progress.get("completed_sections", [])
                total_sections = progress.get("total_sections", 0)

                # 所有可能的阶段（与 ScholarAgent 实际 emit 的阶段名一致）
                all_phases = [
                    "policy_search", "topic_analysis", "literature_search",
                    "evidence_matrix", "spec_generation", "outline",
                    "data_collection", "section_writing", "post_processing",
                    "claim_calibration",
                ]

                # 文件一致性校验：只有阶段标记为完成且对应文件存在才算真正完成
                verified_phases = [
                    p for p in completed_phases
                    if self._verify_phase_file(project_dir, p)
                ]

                # 判断项目状态
                status = "not_started"
                if verified_phases:
                    status = "in_progress"
                if len(verified_phases) >= len(all_phases):
                    status = "completed"

                # 计算进度百分比（基于文件验证后的阶段数）
                phase_pct = len(verified_phases) / len(all_phases)

                projects.append({
                    "name": name,
                    "title": meta.get("title", "") or meta.get("topic", ""),
                    "topic": meta.get("topic", ""),
                    "created_at": meta.get("created_at", ""),
                    "updated_at": meta.get("updated_at", ""),
                    "status": status,
                    "progress_pct": round(phase_pct * 100),
                    "completed_phases": completed_phases,
                    "completed_sections": completed_sections,
                    "total_sections": total_sections,
                    "char_count": self._count_chars(project_dir),
                })

            # 按更新时间降序排序
            projects.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
            return json.dumps(projects, ensure_ascii=False)
        except Exception as e:
            logger.error(f"获取项目列表失败: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def create_project(self, name: str, topic: str = "") -> str:
        """创建新项目.

        Args:
            name: 项目名称
            topic: 研究主题（可选）

        Returns:
            JSON 格式的创建结果
        """
        try:
            project_dir = self._file_manager.create_project(name)
            if topic:
                meta = self._file_manager.get_project_meta(project_dir) or {}
                meta["topic"] = topic
                meta["title"] = ""
                self._file_manager._write_json(project_dir / ".scholar" / "meta.json", meta)
            return json.dumps({"success": True, "project_dir": str(project_dir)}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"创建项目失败: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def delete_project(self, name: str) -> str:
        """删除项目.

        Args:
            name: 项目名称

        Returns:
            JSON 格式的删除结果
        """
        try:
            import shutil
            project_dir = self._file_manager.get_project_dir(name)
            if project_dir and project_dir.exists():
                shutil.rmtree(project_dir)
                return json.dumps({"success": True}, ensure_ascii=False)
            return json.dumps({"error": "项目不存在"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def rename_project(self, old_name: str, new_name: str) -> str:
        """重命名项目.

        Args:
            old_name: 原项目名称
            new_name: 新项目名称

        Returns:
            JSON 格式的结果
        """
        try:
            project_dir = self._file_manager.get_project_dir(old_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            new_dir = project_dir.parent / new_name
            if new_dir.exists():
                return json.dumps({"error": "目标名称已存在"}, ensure_ascii=False)

            project_dir.rename(new_dir)

            # 更新 meta.json 中的名称
            meta_path = new_dir / ".scholar" / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["name"] = new_name
                meta["updated_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

            return json.dumps({"success": True, "new_name": new_name}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"重命名失败: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 工作流控制 API ──────────────────────────────────

    def start_generation(self, project_name: str, topic: str) -> str:
        """开始生成论文.

        Args:
            project_name: 项目名称
            topic: 研究主题/想法

        Returns:
            JSON 格式的启动结果
        """
        try:
            project_dir = self._file_manager.get_project_dir(project_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            if self._controller and self._controller.is_running:
                return json.dumps({"error": "已有生成任务在运行中"}, ensure_ascii=False)

            self._controller = WorkflowController(
                project_dir=Path(project_dir),
                ui_callback=self._update_ui,
                config=self._config,
            )
            self._controller.start(topic)

            return json.dumps({"success": True, "message": "工作流已启动"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"启动生成失败: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def cancel_generation(self) -> str:
        """取消当前生成任务.

        Returns:
            JSON 格式的取消结果
        """
        try:
            if self._controller and self._controller.is_running:
                self._controller.cancel()
                return json.dumps({"success": True, "message": "已发送取消请求"}, ensure_ascii=False)
            return json.dumps({"error": "没有正在运行的生成任务"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def submit_review(self, review_id: str, decision: str, feedback: str = "") -> str:
        """提交用户审核决策，唤醒等待中的工作流.

        当前端审核模态框收到用户决策后调用此方法，
        将决策传递给后台线程中暂停等待的 ScholarAgent。

        Args:
            review_id: 审核唯一标识（由 review_request 事件携带）。
            decision: 用户决策 "confirm" | "modify" | "reject"。
            feedback: 修改意见（decision=modify 时填写）。

        Returns:
            JSON 格式的提交结果
        """
        try:
            if not self._controller:
                return json.dumps({"error": "没有活跃的工作流"}, ensure_ascii=False)

            success = self._controller.submit_review(review_id, decision, feedback)
            if success:
                return json.dumps({"success": True, "message": f"审核决策已提交: {decision}"}, ensure_ascii=False)
            return json.dumps({"error": "审核 ID 不存在或已过期"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"提交审核失败: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def get_generation_status(self) -> str:
        """获取当前生成状态.

        Returns:
            JSON 格式的状态信息
        """
        is_running = self._controller.is_running if self._controller else False
        return json.dumps({"is_running": is_running}, ensure_ascii=False)

    # ── 步骤预览 API ──────────────────────────────────

    def get_step_list(self, project_name: str) -> str:
        """获取项目的所有步骤列表及完成状态.

        Args:
            project_name: 项目名称

        Returns:
            JSON 格式的步骤列表
        """
        try:
            project_dir = self._file_manager.get_project_dir(project_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            progress = self._file_manager.load_progress(Path(project_dir)) or {}
            completed_phases = progress.get("completed_phases", [])

            all_steps = [
                {"id": "policy_search", "name": "政策调研", "icon": "🏛️"},
                {"id": "topic_analysis", "name": "选题分析", "icon": "🎯"},
                {"id": "literature_search", "name": "文献检索", "icon": "📚"},
                {"id": "evidence_matrix", "name": "证据矩阵", "icon": "🔍"},
                {"id": "spec_generation", "name": "规格生成", "icon": "📋"},
                {"id": "outline", "name": "大纲生成", "icon": "📝"},
                {"id": "data_collection", "name": "数据采集", "icon": "📊"},
                {"id": "section_writing", "name": "逐章撰写", "icon": "✍️"},
                {"id": "post_processing", "name": "后处理", "icon": "🔧"},
                {"id": "completed", "name": "完成", "icon": "✅"},
            ]

            for step in all_steps:
                step["completed"] = (
                    step["id"] in completed_phases
                    and self._verify_phase_file(Path(project_dir), step["id"])
                )

            return json.dumps(all_steps, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def get_step_output(self, project_name: str, phase: str) -> str:
        """获取步骤的输出内容（供前端预览）.

        Args:
            project_name: 项目名称
            phase: 阶段标识

        Returns:
            JSON 格式的步骤输出
        """
        try:
            project_dir = self._file_manager.get_project_dir(project_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            # 优先从 steps 目录读取缓存的输出（桌面版运行时创建）
            step_file = Path(project_dir) / ".scholar" / "steps" / f"{phase}.json"
            if step_file.exists():
                return step_file.read_text(encoding="utf-8")

            # 降级：从实际项目文件读取（兼容 CLI 版本生成的项目）
            content = self._read_phase_output(Path(project_dir), phase)
            if content:
                return json.dumps({
                    "phase": phase,
                    "content": content,
                    "content_type": "markdown",
                    "metadata": {"char_count": len(content)},
                    "saved_at": "",
                }, ensure_ascii=False)

            return json.dumps({
                "phase": phase,
                "content": "（步骤尚未完成，暂无输出）",
                "content_type": "text",
                "metadata": {},
                "saved_at": "",
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def get_chapter_list(self, project_name: str) -> str:
        """获取项目的章节列表（逐章撰写阶段）.

        Args:
            project_name: 项目名称

        Returns:
            JSON 格式的章节列表
        """
        try:
            project_dir = self._file_manager.get_project_dir(project_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            # 从 outline.json 读取章节
            outline_path = Path(project_dir) / "outline.json"
            if outline_path.exists():
                outline = json.loads(outline_path.read_text(encoding="utf-8"))
                sections = outline.get("sections", [])
                chapters = []
                for i, section in enumerate(sections):
                    section_name = f"chapter{i+1}"
                    # 检查章节是否已完成
                    chapter_path = Path(project_dir) / "draft" / f"{section_name}.md"
                    chapters.append({
                        "id": section_name,
                        "title": section.get("title", f"第{i+1}章"),
                        "word_count": section.get("word_count", 2000),
                        "completed": chapter_path.exists(),
                        "char_count": len(chapter_path.read_text(encoding="utf-8")) if chapter_path.exists() else 0,
                    })
                return json.dumps(chapters, ensure_ascii=False)

            return json.dumps([], ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 反馈与评论 API ──────────────────────────────────

    def rewrite_section(
        self,
        project_name: str,
        section_title: str,
        original_content: str,
        feedback: str,
        selected_text: str = "",
    ) -> str:
        """根据用户反馈重写章节.

        Args:
            project_name: 项目名称
            section_title: 章节标题
            original_content: 原始内容
            feedback: 修改意见
            selected_text: 选中的文字（可选）

        Returns:
            JSON 格式的重写结果
        """
        try:
            project_dir = self._file_manager.get_project_dir(project_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            handler = FeedbackHandler(Path(project_dir), self._config)

            # 在新的事件循环中运行 async 方法
            loop = asyncio.new_event_loop()
            try:
                new_content = loop.run_until_complete(
                    handler.rewrite_section(
                        section_title=section_title,
                        original_content=original_content,
                        feedback=feedback,
                        selected_text=selected_text,
                    )
                )
            finally:
                loop.close()

            return json.dumps({
                "success": True,
                "new_content": new_content,
                "original_content": original_content,
            }, ensure_ascii=False)
        except Exception as e:
            logger.error(f"章节重写失败: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def apply_rewrite(
        self,
        project_name: str,
        section_name: str,
        new_content: str,
        feedback: str,
    ) -> str:
        """应用重写结果到章节文件.

        Args:
            project_name: 项目名称
            section_name: 章节标识 (如 "chapter4")
            new_content: 重写后的内容
            feedback: 修改意见

        Returns:
            JSON 格式的应用结果
        """
        try:
            project_dir = self._file_manager.get_project_dir(project_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            handler = FeedbackHandler(Path(project_dir), self._config)
            section_path = handler.save_rewritten_section(
                section_name=section_name,
                new_content=new_content,
                feedback=feedback,
            )

            return json.dumps({
                "success": True,
                "section_path": str(section_path),
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def get_comments(self, project_name: str) -> str:
        """获取项目的所有评论.

        Args:
            project_name: 项目名称

        Returns:
            JSON 格式的评论列表
        """
        try:
            project_dir = self._file_manager.get_project_dir(project_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            handler = FeedbackHandler(Path(project_dir), self._config)
            comments = handler.load_comments()
            return json.dumps(comments, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def add_comment(
        self,
        project_name: str,
        quote: str,
        text: str,
        section: str = "",
        position: int = 0,
    ) -> str:
        """添加评论.

        Args:
            project_name: 项目名称
            quote: 被选中的原文
            text: 评论内容
            section: 所在章节
            position: 字符偏移量

        Returns:
            JSON 格式的评论对象
        """
        try:
            project_dir = self._file_manager.get_project_dir(project_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            handler = FeedbackHandler(Path(project_dir), self._config)
            comment = handler.add_comment(quote, text, section, position)
            return json.dumps(comment, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def resolve_comment(self, project_name: str, comment_id: str) -> str:
        """标记评论为已解决.

        Args:
            project_name: 项目名称
            comment_id: 评论 ID

        Returns:
            JSON 格式的结果
        """
        try:
            project_dir = self._file_manager.get_project_dir(project_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            handler = FeedbackHandler(Path(project_dir), self._config)
            success = handler.resolve_comment(comment_id)
            return json.dumps({"success": success}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 导出 API ──────────────────────────────────

    def export_project(self, project_name: str, fmt: str = "docx") -> str:
        """导出论文为指定格式.

        Args:
            project_name: 项目名称
            fmt: 导出格式 (docx/pdf/latex/md)

        Returns:
            JSON 格式的导出结果
        """
        try:
            project_dir = self._file_manager.get_project_dir(project_name)
            if not project_dir:
                return json.dumps({"error": "项目不存在"}, ensure_ascii=False)

            from scholarpilot.tools.exporter import export_project as do_export

            output_path = do_export(Path(project_dir), fmt=fmt)
            return json.dumps({
                "success": True,
                "output_path": str(output_path),
                "format": fmt,
            }, ensure_ascii=False)
        except FileNotFoundError as e:
            return json.dumps({"error": f"论文草稿未找到: {e}"}, ensure_ascii=False)
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"导出失败: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 配置 API ──────────────────────────────────

    def get_config(self) -> str:
        """获取当前配置信息（不包含敏感 API Key 原文）.

        Returns:
            JSON 格式的配置信息
        """
        try:
            key_providers = {
                "zhipu": "zhipu_api_key",
                "ark": "ark_api_key",
                "claude": "claude_api_key",
                "openai": "openai_api_key",
                "deepseek": "deepseek_api_key",
            }
            config_info = {
                "has_api_key": False,
                "writing_model": getattr(self._config, "default_writing_model", ""),
                "projects_dir": str(self._config.projects_dir),
            }
            for provider, attr in key_providers.items():
                config_info[f"{provider}_configured"] = bool(getattr(self._config, attr, ""))
                if bool(getattr(self._config, attr, "")):
                    config_info["has_api_key"] = True
            return json.dumps(config_info, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def set_api_key(self, provider: str, api_key: str) -> str:
        """设置 API Key 并持久化到 .env 文件.

        Args:
            provider: 提供商 (zhipu/ark/claude/openai/deepseek)
            api_key: API Key

        Returns:
            JSON 格式的设置结果
        """
        try:
            import os
            import re
            from scholarpilot.config import _find_env_file

            key_map = {
                "zhipu": "ZHIPU_API_KEY",
                "ark": "ARK_API_KEY",
                "claude": "CLAUDE_API_KEY",
                "openai": "OPENAI_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
            }
            env_key = key_map.get(provider, f"{provider.upper()}_API_KEY")

            # 1. 更新当前进程环境变量
            os.environ[env_key] = api_key

            # 2. 持久化到 .env 文件
            env_path = _find_env_file()
            if env_path.exists():
                content = env_path.read_text(encoding="utf-8")
                if re.search(fr"^{env_key}=.*$", content, re.MULTILINE):
                    content = re.sub(
                        fr"^{env_key}=.*$",
                        f"{env_key}={api_key}",
                        content,
                        flags=re.MULTILINE,
                    )
                else:
                    content = content.rstrip("\n") + f"\n{env_key}={api_key}\n"
                env_path.write_text(content, encoding="utf-8")
            else:
                env_path.write_text(f"{env_key}={api_key}\n", encoding="utf-8")

            # 3. 重置配置单例，下次 get_settings() 会重新读取 .env
            from scholarpilot.config import reset_settings
            reset_settings()
            # 立即刷新当前实例的配置引用
            self._config = get_settings()

            return json.dumps({"success": True, "provider": provider}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"设置 API Key 失败: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def set_model_config(self, writing_model: str) -> str:
        """设置默认写作模型并持久化.

        Args:
            writing_model: 模型标识符（如 claude-sonnet-4-20250514）

        Returns:
            JSON 格式的设置结果
        """
        try:
            import os
            import re
            from scholarpilot.config import _find_env_file

            env_key = "SCHOLAR_DEFAULT_WRITING_MODEL"
            os.environ[env_key] = writing_model

            env_path = _find_env_file()
            if env_path.exists():
                content = env_path.read_text(encoding="utf-8")
                if re.search(fr"^{env_key}=.*$", content, re.MULTILINE):
                    content = re.sub(
                        fr"^{env_key}=.*$",
                        f"{env_key}={writing_model}",
                        content,
                        flags=re.MULTILINE,
                    )
                else:
                    content = content.rstrip("\n") + f"\n{env_key}={writing_model}\n"
                env_path.write_text(content, encoding="utf-8")
            else:
                env_path.write_text(f"{env_key}={writing_model}\n", encoding="utf-8")

            from scholarpilot.config import reset_settings, get_settings
            reset_settings()
            self._config = get_settings()

            return json.dumps({"success": True}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── UI 更新回调（由 WorkflowController 调用）──────────────────

    def _update_ui(self, event_type: str, data: dict) -> None:
        """将进度事件推送到前端 JS.

        由 WorkflowController 在后台线程中调用，
        pywebview 的 evaluate_js 是线程安全的。

        Args:
            event_type: 事件类型 "progress" | "step_complete" | "error" | "review_request"
            data: 事件数据字典
        """
        if not self._window:
            logger.warning("_update_ui: window 未初始化，事件丢弃")
            return

        try:
            js_data = json.dumps(data, ensure_ascii=False)
            js_code = f"window.app && window.app.onEvent('{event_type}', {js_data});"
            self._window.evaluate_js(js_code)
            # 每 10 次事件输出一次 INFO 日志，避免刷屏
            if not hasattr(self, "_event_count"):
                self._event_count = 0
            self._event_count += 1
            if self._event_count % 10 == 0:
                logger.info(f"已推送 {self._event_count} 个 UI 事件到前端")
        except Exception as e:
            logger.error(f"evaluate_js 失败 [{event_type}]: {e}")

    # ── 辅助方法 ──────────────────────────────────

    def _verify_phase_file(self, project_dir: Path, phase: str) -> bool:
        """验证阶段的输出文件是否真正完成.

        用于进度一致性校验：即使 state.json 中标记为完成，
        如果对应文件不存在或只是占位符，仍然认为该阶段未完成。

        判定规则（必须同时满足）：
        1. 文件存在
        2. 文件大小 >= min_size 字节（排除 FileManager 创建的占位符）
        3. 文件不含 "（待填写）" 占位标记
        """
        file_map = {
            "policy_search": ("policy_research.md", 200),
            "topic_analysis": ("SPEC.md", 200),
            "literature_search": ("literature/review.md", 500),
            "evidence_matrix": ("literature/evidence_matrix.md", 300),
            "spec_generation": ("SPEC.md", 500),
            "outline": ("outline.md", 200),
            "data_collection": ("data_collection_guide.md", 200),
            "section_writing": ("draft/full_draft.md", 1000),
            "post_processing": ("draft/deai_report.md", 200),
            "claim_calibration": ("draft/claim_calibration_report.md", 200),
            "completed": ("draft/full_draft_polished.md", 1000),
        }
        fallback_map = {
            "literature_search": "literature/evidence_matrix.md",
        }
        if phase in file_map:
            rel_path, min_size = file_map[phase]
            file_path = project_dir / rel_path
            if not file_path.exists() and phase in fallback_map:
                file_path = project_dir / fallback_map[phase]
            if not file_path.exists():
                return False
            try:
                stat = file_path.stat()
                if stat.st_size < min_size:
                    return False
                # 检查是否还是占位符（适用于覆盖了占位符文件的情况）
                if "（待填写）" in file_path.read_text(encoding="utf-8")[:500]:
                    return False
            except OSError:
                return False
            return True
        return False

    def _count_chars(self, project_dir: Path) -> int:
        """统计项目的总字符数."""
        draft_dir = project_dir / "draft"
        if not draft_dir.exists():
            return 0
        total = 0
        for md_file in draft_dir.glob("*.md"):
            try:
                total += len(md_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return total

    def _read_phase_output(self, project_dir: Path, phase: str) -> str:
        """从项目实际文件读取阶段输出（CLI 兼容降级方案）.

        当 .scholar/steps/ 缓存不存在时，直接读取对应文件。
        """
        file_map = {
            "policy_search": "policy_research.md",
            "topic_analysis": "SPEC.md",
            "literature_search": "literature/review.md",
            "evidence_matrix": "literature/evidence_matrix.md",
            "spec_generation": "SPEC.md",
            "outline": "outline.md",
            "data_collection": "data_collection_guide.md",
            "section_writing": "draft/full_draft.md",
            "post_processing": "draft/deai_report.md",
            "claim_calibration": "draft/claim_calibration_report.md",
            "completed": "draft/full_draft_polished.md",
        }
        # 降级映射：主文件不存在时尝试的替代文件
        fallback_map = {
            "literature_search": "literature/evidence_matrix.md",
        }
        if phase in file_map:
            file_path = project_dir / file_map[phase]
            if not file_path.exists() and phase in fallback_map:
                file_path = project_dir / fallback_map[phase]
            if file_path.exists():
                try:
                    return file_path.read_text(encoding="utf-8")
                except Exception:
                    return ""
        return ""


def main() -> None:
    """启动 ScholarPilot 桌面应用."""
    import webview

    # 配置 logging，确保 ERROR 级别日志可见
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    app = DesktopApp()

    html_path = Path(__file__).parent / "web" / "index.html"

    # 使用 file:// 协议加载本地页面（EdgeChromium 需要，否则会加载失败卡住）
    url = html_path.as_uri()

    window = webview.create_window(
        title="ScholarPilot — AI 学术研究助手",
        url=url,
        width=1280,
        height=800,
        min_size=(720, 480),
        js_api=app,
        background_color="#0D1117",
    )
    app._window = window

    # 启动 pywebview
    webview.start(debug=False)


if __name__ == "__main__":
    main()
