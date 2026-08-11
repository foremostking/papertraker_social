"""Scholar Agent - 学术论文写作 AI Agent 主控.

采用 Spec-Driven 范式：
1. 理解用户的研究想法
2. 通过 CNKI（4层检索）+ Semantic Scholar + arXiv 多源检索文献
3. 基于 CNKI 结果计算 8维统计，评估选题可行性
4. 生成结构化的论文规格文档（SPEC.md）
5. 基于规格生成大纲
6. 基于大纲逐章生成论文初稿
7. 所有产出直接写入项目目录

在每个关键决策点暂停等待用户确认（Human-in-the-Loop）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

from scholarpilot.config import get_settings
from scholarpilot.context.engine import ContextEngine
from scholarpilot.context.memory import ProjectMemory
from scholarpilot.context.profile import ResearcherProfile
from scholarpilot.context.prompts.constants import CSSCI_REF_RANGE
from scholarpilot.events.types import ProgressEvent, ReviewRequestEvent, StepOutput, WorkflowCallback
from scholarpilot.llm.gateway import LLMGateway
from scholarpilot.mcp.servers.cnki import (
    CNKISearchResult,
    calculate_eight_dimensions,
    assess_feasibility,
)
from scholarpilot.mcp.servers.semantic_scholar import SemanticScholarEngine
from scholarpilot.mcp.servers.arxiv import ArxivEngine
from scholarpilot.mcp.servers.openalex import OpenAlexEngine
from scholarpilot.tools.search import LiteratureSearchManager
from scholarpilot.utils.file_manager import FileManager
from scholarpilot.utils.library import GlobalLibrary
from scholarpilot.utils.vpn import EasyConnectDetector, VPNStatus

logger = logging.getLogger(__name__)
console = Console()


class ScholarAgent:
    """Scholar Agent - 学术论文写作 AI Agent [弃用中].

    .. deprecated:: ADR-003
        本过程式 Agent 正在弃用中，推荐使用 LangGraph 状态图路径
        （``agent.graph.create_scholar_graph``）。

        当前状态（P3 阶段）：
        - **A 类方法**（文献检索/大纲/写作/引用/导出）已被
          ``executor.py`` 完全覆盖，不再经由此类调用。
        - **B 类方法**（证据矩阵、SPEC 生成、表格模板、质量报告、
          去 AI 味、claim 校准等 14 个）保留在此类中，待抽取为
          ``tools/`` 下独立模块后随类删除。
        - ``scholar_finalize_node`` 已迁移至 ``agent/finalize.py``。

        严禁在 B 类能力下沉前删除本类（ADR-003 约束）。

    核心工作流：
        用户输入 → 选题分析 → 多源文献检索（CNKI + Semantic Scholar + arXiv）
        → 8维统计 → 可行性判定 → SPEC.md生成 → [用户审核]
        → 大纲生成 → [用户审核] → 逐章撰写 → [用户审核] → 完成

    Usage:
        agent = ScholarAgent(project_dir)
        await agent.run("我想写一篇关于地方政府债务的论文")
    """

    def __init__(
        self,
        project_dir: Path | str,
        config=None,
        cnki_cookie: str = "",
        callback: WorkflowCallback | None = None,
    ) -> None:
        """初始化 Scholar Agent.

        Args:
            project_dir: 项目目录路径。
            config: 配置对象，如不提供则自动获取。
            cnki_cookie: CNKI 登录 Cookie（可选）。
            callback: 工作流回调接口，用于桌面 UI 实时进度推送（可选）。
        """
        self.project_dir = Path(project_dir)
        self.config = config or get_settings()
        self.console = console
        self._callback = callback

        # 核心组件
        self.llm = LLMGateway(self.config)
        self.file_manager = FileManager(self.config.projects_dir)
        self.memory = ProjectMemory(self.project_dir / ".scholar" / "memory.json")
        # 研究者画像（跨论文长期记忆，从全局目录加载）
        profile_path = self.config.user_home_dir / "profile.json"
        self.profile = ResearcherProfile(profile_path)
        self.context_engine = ContextEngine(self.memory, self.profile)

        # 全局文献库（跨论文文献复用）
        library_dir = self.config.user_home_dir / "library"
        self.library = GlobalLibrary(library_dir)
        self.project_name = self.project_dir.name

        # 文献检索引擎（多源）
        self._cnki_cookie = cnki_cookie
        self.chinese_manager = LiteratureSearchManager(
            cnki_cookie=cnki_cookie,
            use_playwright=False,  # 可选启用 Playwright CNKI
        )
        self.ss_engine = SemanticScholarEngine(
            api_key=getattr(self.config, "ss_api_key", ""),
        )
        self.arxiv_engine = ArxivEngine()
        self.openalex_engine = OpenAlexEngine()

        # 状态
        self.history: list[dict[str, str]] = []
        self.topic_info: dict[str, Any] = {}
        self.discipline: str = "经济学"  # 学科领域，由 Phase 1 选题分析填充
        self.chinese_results: list[Any] = []  # ChineseSearchResult 列表
        self.ss_results: list[Any] = []  # SSSearchResult 列表
        self.arxiv_results: list[Any] = []  # ArxivSearchResult 列表
        self.openalex_results: list[Any] = []  # OpenAlexSearchResult 列表
        self.eight_dim_stats: dict[str, Any] = {}
        self.feasibility: dict[str, Any] = {}

        # 证据矩阵构建器（Phase 2.5 初始化，Phase 7 使用）
        self.evidence_matrix_builder = None

        # VPN 检测器（EasyConnect 机构访问）
        self.vpn_detector = EasyConnectDetector(
            check_timeout=getattr(self.config, "vpn_check_timeout", 10),
        )
        self.vpn_status: VPNStatus | None = None

        # 非交互模式（用于自动化测试或脚本调用）
        self.non_interactive: bool = False
        self.default_choices: dict[str, int] = {}  # 各交互步骤的默认选择

        # 审核管理器（桌面 UI 模式下由 WorkflowController 注入）
        self.review_manager = None  # ReviewManager | None
        self._loop = None  # asyncio.AbstractEventLoop | None

        # 自动校验（Actor-Critic 模式）：默认启用
        # 启用后每个阶段产出先由 Critic 角色自动校验，不通过才升级人工审核
        self.auto_verify: bool = True
        self._auto_verifier: Any = None  # 延迟初始化（需要 self.llm）
        self._last_user_input: str = ""  # 缓存用户输入供校验使用

    # ===== 回调辅助方法（桌面 UI 实时进度推送）=====

    def _emit(
        self,
        phase: str,
        status: str,
        message: str = "",
        progress_pct: float | None = None,
        **kwargs: Any,
    ) -> None:
        """发出进度事件到回调接口（如有）.

        Args:
            phase: 阶段标识
            status: "start" | "progress" | "complete" | "error"
            message: 人类可读描述
            progress_pct: 子步骤进度 0.0-1.0
            **kwargs: 附加数据，合并到 event.data
        """
        _cb = getattr(self, "_callback", None)
        if not _cb:
            return
        event = ProgressEvent(
            phase=phase,
            status=status,
            message=message,
            progress_pct=progress_pct,
            data=kwargs if kwargs else None,
        )
        try:
            _cb.on_progress(event)
        except Exception as e:
            logger.error(f"回调 on_progress 失败: {e}")

    def _emit_step_complete(self, phase: str, content: str, content_type: str = "markdown", **metadata: Any) -> None:
        """发出步骤完成事件，携带可预览的输出内容.

        Args:
            phase: 阶段标识
            content: Markdown/JSON/Text 内容
            content_type: "markdown" | "json" | "text"
            **metadata: 元数据（char_count, ref_count 等）
        """
        _cb = getattr(self, "_callback", None)
        if not _cb:
            return
        output = StepOutput(
            phase=phase,
            content=content,
            content_type=content_type,
            metadata=metadata,
        )
        try:
            _cb.on_step_complete(phase, output)
        except Exception as e:
            logger.error(f"回调 on_step_complete 失败: {e}")

    def _emit_error(self, phase: str, error: str) -> None:
        """发出错误事件."""
        _cb = getattr(self, "_callback", None)
        if not _cb:
            return
        try:
            _cb.on_error(phase, error)
        except Exception as e:
            logger.error(f"回调 on_error 失败: {e}")

    def _save_step_output(self, phase: str) -> None:
        """保存步骤输出到 .scholar/steps/ 目录，供前端预览加载.

        Args:
            phase: 阶段标识
        """
        steps_dir = self.project_dir / ".scholar" / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)

        content = ""
        content_type = "markdown"
        metadata: dict[str, Any] = {}

        # 根据阶段读取对应的输出文件
        file_map = {
            "policy_search": ("policy_research.md", "markdown"),
            "topic_analysis": (".scholar/memory.json", "json"),
            "literature_search": ("literature/review.md", "markdown"),
            "evidence_matrix": ("evidence_matrix.md", "markdown"),
            "spec_generation": ("SPEC.md", "markdown"),
            "outline": ("outline.md", "markdown"),
        }

        if phase in file_map:
            rel_path, content_type = file_map[phase]
            file_path = self.project_dir / rel_path
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                metadata["char_count"] = len(content)

        # 章节撰写阶段：读取所有已完成的章节
        if phase == "section_writing":
            draft_dir = self.project_dir / "draft"
            if draft_dir.exists():
                parts = []
                for md_file in sorted(draft_dir.glob("chapter*.md")):
                    parts.append(md_file.read_text(encoding="utf-8"))
                content = "\n\n---\n\n".join(parts)
                content_type = "markdown"
                metadata["char_count"] = len(content)
                metadata["chapter_count"] = len(parts)

        # 完成阶段：读取完整草稿
        if phase == "completed":
            full_draft = self.project_dir / "draft" / "full_draft.md"
            if not full_draft.exists():
                full_draft = self.project_dir / "draft" / "full_draft_polished.md"
            if full_draft.exists():
                content = full_draft.read_text(encoding="utf-8")
                metadata["char_count"] = len(content)

        output = StepOutput(
            phase=phase,
            content=content,
            content_type=content_type,
            metadata=metadata,
        )

        output_file = steps_dir / f"{phase}.json"
        output_file.write_text(output.to_json(), encoding="utf-8")

    async def run(self, user_input: str) -> None:
        """启动 Scholar Agent 工作流（支持断点续写）.

        科研场景：写到第三章时被审稿意见打断，回来后系统能告知
        "上次进行到：逐章撰写（已完成2/6章）"并从断点继续。

        Args:
            user_input: 用户的自然语言输入（研究想法）。
        """
        # 缓存用户输入，供 AutoVerifier 校验使用
        self._last_user_input = user_input

        # Phase 0: VPN 检测（EasyConnect 机构访问）
        if getattr(self.config, "vpn_auto_detect", True):
            await self._detect_vpn_interactive()

        # 检查是否有未完成的数据补交（跳过后重新运行）
        state = self.file_manager.load_project_state(self.project_dir)
        if state and state.get("data_status") == "pending":
            handled = await self._check_pending_data()
            if handled:
                return  # 数据补交完成，不重新走全流程

        # ── 断点续写检测 ──────────────────────────────────
        progress = self.file_manager.load_progress(self.project_dir)
        resume = False
        completed_phases: list[str] = []
        completed_sections: list[str] = []

        if progress and progress.get("can_resume"):
            summary = self.file_manager.get_progress_summary(self.project_dir)
            last_run = (progress.get("last_run_at", "") or "")[:19]
            self.console.print(
                Panel(
                    f"[yellow]检测到未完成的工作进度[/yellow]\n"
                    f"上次运行时间: {last_run}\n"
                    f"当前进度: {summary}\n",
                    title="断点续写",
                )
            )
            should_resume = False
            if self.non_interactive:
                self.console.print("  [dim][非交互模式] 自动从断点继续[/dim]")
                should_resume = True
            else:
                from rich.prompt import Confirm
                should_resume = Confirm.ask("是否从上次断点继续？", default=True)
            if should_resume:
                resume = True
                completed_phases = progress.get("completed_phases", [])
                completed_sections = progress.get("completed_sections", [])
                # 从项目记忆恢复运行时状态
                self.topic_info = self.memory.get("topic_analysis", {}) or {}
                self.discipline = self.topic_info.get("discipline", "经济学")
                self.eight_dim_stats = self.memory.get("eight_dim_stats", {}) or {}
                self.feasibility = self.memory.get("feasibility", {}) or {}
                self.console.print(
                    f"[green]从断点恢复，跳过 {len(completed_phases)} 个已完成阶段[/green]"
                )
            else:
                self.console.print("[dim]将从头开始执行[/dim]")

        if not resume:
            self.console.print(
                Panel(
                    f"[bold blue]ScholarPilot[/bold blue] 启动\n"
                    f"项目目录: {self.project_dir}\n"
                    f"研究想法: {user_input}",
                    title="Scholar Agent",
                )
            )

        try:
            # Phase 0.5: 政策/制度背景调研（新增）
            if "policy_search" not in completed_phases:
                self._emit("policy_search", "start", "开始政策背景调研...")
                await self._phase0_5_policy_search(user_input)
                self._emit("policy_search", "complete", "政策背景调研完成")
                self._save_step_output("policy_search")
                approved = await self._request_review(
                    phase="policy_search",
                    title="政策背景调研审核",
                    filename="policy_research.md",
                )
                if not approved:
                    self.file_manager.save_progress(
                        self.project_dir, "policy_search",
                        phase_detail="等待用户确认政策调研结果",
                    )
                    return
            self.file_manager.save_progress(
                self.project_dir, "topic_analysis"
            )

            # Phase 1: 选题分析
            if "topic_analysis" not in completed_phases:
                self._emit("topic_analysis", "start", "开始选题分析...")
                await self._phase1_topic_analysis(user_input)
                self._emit("topic_analysis", "complete", "选题分析完成")
                self._save_step_output("topic_analysis")
                approved = await self._request_review(
                    phase="topic_analysis",
                    title="选题分析审核",
                    content_override=self._format_topic_review(),
                )
                if not approved:
                    self.file_manager.save_progress(
                        self.project_dir, "topic_analysis",
                        phase_detail="等待用户确认选题分析",
                    )
                    return
            self.file_manager.save_progress(
                self.project_dir, "literature_search"
            )

            # Phase 2: 多源文献检索 + 8维统计
            if "literature_search" not in completed_phases:
                self._emit("literature_search", "start", "开始多源文献检索...")
                await self._phase2_literature_search()
                self._emit("literature_search", "complete", "文献检索完成")
                self._save_step_output("literature_search")
                approved = await self._request_review(
                    phase="literature_search",
                    title="文献检索结果审核",
                    content_override=self._format_literature_review(),
                )
                if not approved:
                    self.file_manager.save_progress(
                        self.project_dir, "literature_search",
                        phase_detail="等待用户确认文献检索结果",
                    )
                    return
            self.file_manager.save_progress(
                self.project_dir, "evidence_matrix"
            )

            # Phase 2.5: 证据矩阵构建（新增）
            if "evidence_matrix" not in completed_phases:
                self._emit("evidence_matrix", "start", "构建证据矩阵...")
                await self._phase2_5_build_evidence_matrix()
                self._emit("evidence_matrix", "complete", "证据矩阵构建完成")
                self._save_step_output("evidence_matrix")
            self.file_manager.save_progress(
                self.project_dir, "spec_generation"
            )

            # Phase 3 + 4: 生成论文规格 + 用户审核
            if "spec_generation" not in completed_phases:
                self._emit("spec_generation", "start", "生成论文规格文档...")
                await self._phase3_generate_spec()
                self._emit("spec_generation", "complete", "论文规格生成完成")
                self._save_step_output("spec_generation")
                approved = await self._request_review(
                    phase="spec_generation",
                    title="选题验证（SPEC）",
                    filename="SPEC.md",
                )
                if not approved:
                    self.console.print("[yellow]用户未确认选题，Agent 暂停。[/yellow]")
                    self.file_manager.save_progress(
                        self.project_dir, "spec_generation",
                        phase_detail="等待用户确认选题",
                    )
                    return
            self.file_manager.save_progress(
                self.project_dir, "outline"
            )

            # Phase 5 + 6: 生成大纲 + 用户审核
            if "outline" not in completed_phases:
                self._emit("outline", "start", "生成论文大纲...")
                await self._phase5_generate_outline()
                self._emit("outline", "complete", "大纲生成完成")
                self._save_step_output("outline")
                approved = await self._request_review(
                    phase="outline",
                    title="论文大纲审核",
                    filename="outline.md",
                )
                if not approved:
                    self.console.print("[yellow]用户未确认大纲，Agent 暂停。[/yellow]")
                    self.file_manager.save_progress(
                        self.project_dir, "outline",
                        phase_detail="等待用户确认大纲",
                    )
                    return
            self.file_manager.save_progress(
                self.project_dir, "data_collection"
            )

            # Phase 6.5: 数据采集协作（仅实证论文）
            if "data_collection" not in completed_phases:
                research_type = self.topic_info.get("research_type", "empirical")
                if research_type == "empirical":
                    self._emit("data_collection", "start", "数据采集协作...")
                    data_ready = await self._phase6_5_data_collection()
                    self._emit("data_collection", "complete", "数据采集阶段结束")
                    if not data_ready:
                        self.console.print(
                            "[yellow]用户跳过数据采集，实证章节将使用占位符模式[/yellow]\n"
                            "[dim]后续可将数据放入 data/ 文件夹后重新运行，"
                            "系统会自动检测并重新生成实证章节[/dim]"
                        )
            self.file_manager.save_progress(
                self.project_dir, "section_writing"
            )

            # Phase 7: 逐章撰写（支持章节级断点恢复）
            if "section_writing" not in completed_phases:
                self._emit("section_writing", "start", "开始逐章撰写...")
                await self._phase7_write_sections(
                    skip_sections=completed_sections if resume else None
                )
                self._emit("section_writing", "complete", "逐章撰写完成")
                self._save_step_output("section_writing")
            self.file_manager.save_progress(
                self.project_dir, "post_processing"
            )

            # Phase 8: 完成
            self.console.print(
                Panel(
                    "[green]论文初稿生成完成！[/green]\n\n"
                    f"项目目录: {self.project_dir}\n"
                    f"草稿目录: {self.project_dir / 'draft'}\n"
                    f"你可以用任何编辑器打开和修改这些文件。",
                    title="完成",
                )
            )

            # 更新项目状态和进度
            self.file_manager.update_project_status(self.project_dir, "draft_completed")
            self.file_manager.save_progress(self.project_dir, "completed")
            self._emit("completed", "start", "后处理：去AI味 + 润色 + Claim校准...")

            # 将本篇论文记录写入研究者画像（跨论文长期记忆）
            meta = self.file_manager.get_project_meta(self.project_dir) or {}
            self.profile.add_paper_record({
                "project_name": meta.get("name", self.project_dir.name),
                "title": meta.get("title", "") or self.topic_info.get("topic", ""),
                "topic": self.topic_info.get("topic", ""),
                "target_journal": meta.get("target_journal", ""),
                "research_type": self.topic_info.get("research_type", ""),
            })
            self.console.print(
                "[dim]已将本篇论文记录写入研究者画像（跨论文长期记忆）[/dim]"
            )

            # Phase 8b: 去AI味 + 中文润色后处理
            self._phase8b_deai_polish()

            # Phase 8c: Claim校准（新增）
            await self._phase8c_claim_calibration()

            # Phase 8 增强：显示质量报告 + 导出建议 + 实证工具提示
            self._phase8_post_completion()
            self._emit("completed", "complete", "论文生成全部完成！")
            self._save_step_output("completed")

        except Exception as e:
            logger.error(f"Scholar Agent error: {e}", exc_info=True)
            self.console.print(f"[red]错误: {e}[/red]")
            self._emit_error("error", str(e))
            # 保存当前进度以便恢复
            self.file_manager.save_progress(
                self.project_dir, "section_writing",
                phase_detail=f"异常中断: {e}",
            )

    # ===== Phase 0: VPN 检测 =====

    async def _detect_vpn_interactive(self) -> None:
        """VPN 连通性检测（Phase 0）.

        检测 EasyConnect VPN 是否已连接,如已连接则启用机构 IP 认证模式。
        - VPN 连接时: 重新初始化中文管理器为 VPN 模式, 显示可访问数据库
        - VPN 未连接时(交互模式): 提示用户启动 EasyConnect, 支持轮询等待
        - VPN 未连接时(非交互模式): 静默降级, 使用开放数据源
        """
        vpn_databases_str = getattr(
            self.config, "vpn_databases", "cnki,wanfang,wos"
        )
        databases = [
            d.strip() for d in vpn_databases_str.split(",") if d.strip()
        ]

        self.vpn_status = await self.vpn_detector.check_vpn(
            databases=databases
        )

        if self.vpn_status.connected:
            self.console.print(
                f"[green]VPN 已连接, 可访问机构数据库: "
                f"{', '.join(self.vpn_status.accessible_databases)}[/green]"
            )
            # 重新初始化中文管理器为 VPN 模式
            self.chinese_manager = LiteratureSearchManager(
                cnki_cookie=self._cnki_cookie,
                use_playwright=False,
                vpn_status=self.vpn_status,
            )
            logger.info(
                f"VPN connected, databases: "
                f"{self.vpn_status.accessible_databases}"
            )
        else:
            self.console.print(
                f"[yellow]未检测到 VPN 连接[/yellow] "
                f"[dim]({self.vpn_status.error})[/dim]"
            )
            if not self.non_interactive:
                self.console.print(
                    "[dim]如需访问机构数据库(CNKI全文/万方/WoS), "
                    "请启动 EasyConnect 并登录。[/dim]"
                )
                from rich.prompt import Confirm
                if Confirm.ask(
                    "是否已启动 EasyConnect? 等待检测...",
                    default=False,
                ):
                    wait_timeout = getattr(
                        self.config, "vpn_wait_timeout", 120
                    )
                    self.vpn_status = await self.vpn_detector.wait_for_vpn(
                        timeout=wait_timeout,
                        databases=databases,
                    )
                    if self.vpn_status.connected:
                        self.console.print("[green]VPN 连接成功![/green]")
                        self.chinese_manager = LiteratureSearchManager(
                            cnki_cookie=self._cnki_cookie,
                            use_playwright=False,
                            vpn_status=self.vpn_status,
                        )
                    else:
                        self.console.print(
                            "[yellow]VPN 检测超时, 将使用开放数据源继续。[/yellow]"
                        )
            else:
                self.console.print(
                    "  [dim][非交互模式] 使用开放数据源继续[/dim]"
                )

    # ===== Phase 1: 选题分析 =====

    async def _phase1_topic_analysis(self, user_input: str) -> None:
        """选题分析：使用 LLM 提取研究要素."""
        self.console.print("\n[bold cyan]━━━ Phase 1: 选题分析 ━━━[/bold cyan]")

        # 构建上下文
        ctx = self.context_engine.build_topic_analysis_context(
            user_input=user_input,
            history=[],
        )

        # 调用 LLM
        self.console.print("[dim]💭 正在分析研究选题...[/dim]")
        self._emit("topic_analysis", "progress", "正在调用 LLM 分析研究选题...")
        response = await self.llm.chat(
            messages=ctx.to_messages(),
            model=self.config.default_analysis_model,
            temperature=0.3,
        )

        # 记录历史
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": response})

        # 解析 JSON 响应
        self.topic_info = self._extract_json(response)

        # 强制执行硬约束：文献时间窗口 = 当前年-7 到 当前年
        from datetime import datetime
        current_year = datetime.now().year
        _enforced_start = str(current_year - 7)
        _enforced_end = str(current_year)

        if not self.topic_info:
            # 如果无法解析，使用默认值（动态 7 年窗口）
            self.topic_info = {
                "topic": user_input[:50],
                "region": "中国",
                "content": "",
                "research_type": "empirical",
                "discipline": "经济学",
                "year_start": _enforced_start,
                "year_end": _enforced_end,
                "analysis": response,
            }
        else:
            # LLM 成功解析后，强制覆盖年份为动态窗口
            _old_start = self.topic_info.get("year_start", "")
            _old_end = self.topic_info.get("year_end", "")
            if _old_start != _enforced_start or _old_end != _enforced_end:
                logger.info(
                    "时间窗口强制修正: %s-%s → %s-%s",
                    _old_start, _old_end, _enforced_start, _enforced_end,
                )
            self.topic_info["year_start"] = _enforced_start
            self.topic_info["year_end"] = _enforced_end

        # 提取学科领域（Phase 1 新增）：优先使用 LLM 输出的 discipline，
        # 若未输出则回退到默认值"经济学"
        self.discipline = self.topic_info.get("discipline") or "经济学"
        self.topic_info["discipline"] = self.discipline

        # 显示分析结果
        table = Table(title="选题分析结果")
        table.add_column("要素", style="cyan")
        table.add_column("值", style="white")
        table.add_row("核心主题", self.topic_info.get("topic", ""))
        table.add_row("区域/对象", self.topic_info.get("region", ""))
        table.add_row("研究内容", self.topic_info.get("content", ""))
        table.add_row("研究类型", self.topic_info.get("research_type", ""))
        table.add_row("学科领域", self.discipline)
        table.add_row("时间范围", f"{self.topic_info.get('year_start', '')}-{self.topic_info.get('year_end', '')}")
        self.console.print(table)

        # RAG 知识库查询：评估数据可得性（Phase 1 增强）
        # 在选题阶段即查询机构数据库覆盖情况，为后续 SPEC 生成提供数据支撑
        try:
            from scholarpilot.tools.data_source_guide import DataSourceGuide
            ds_guide = DataSourceGuide(project_dir=self.project_dir)
            rag_topic = " ".join(filter(None, [
                self.topic_info.get("topic", ""),
                self.topic_info.get("region", ""),
                self.topic_info.get("content", ""),
            ])) or user_input[:100]
            rag_dbs = ds_guide._query_rag_databases(rag_topic)
            if rag_dbs:
                db_names = [db.get("name", db.get("db_key", "")) for db in rag_dbs[:5]]
                self.console.print(
                    f"  [dim]📚 RAG 知识库: 覆盖该主题的数据库 {len(rag_dbs)} 个"
                    f"（{', '.join(db_names[:3])}...）[/dim]"
                )
                # 存入 memory，供 Phase 3 SPEC 生成时使用
                self.memory.add("rag_database_coverage", {
                    "topic": rag_topic,
                    "databases": rag_dbs[:8],
                    "db_count": len(rag_dbs),
                })
        except Exception as e:
            logger.debug(f"Phase 1 RAG 查询失败(非致命): {e}")

        # 保存到记忆
        self.memory.add("topic_analysis", self.topic_info)

        # 回填项目元数据（增强版 meta.json）
        meta_updates = {
            "topic": self.topic_info.get("topic", ""),
            "research_type": self.topic_info.get("research_type", ""),
            "discipline": self.discipline,
        }
        # 若画像中有期刊偏好，回填到元数据
        preferred_journal = self.profile.get_preference("target_journal")
        if preferred_journal:
            meta_updates["target_journal"] = preferred_journal
        self.file_manager.update_project_meta(self.project_dir, meta_updates)
        self.file_manager.update_project_status(self.project_dir, "topic_analyzed")

        # 显示画像复用提示（如果存在）
        if preferred_journal or self.profile.get_preference("writing_style"):
            self.console.print(
                f"  [dim]已加载研究者画像偏好"
                f"（期刊: {preferred_journal or '未设置'}）[/dim]"
            )

    # ===== Phase 2: CNKI 检索 + 8维统计 =====

    @staticmethod
    def _extract_search_keywords(text: str) -> str:
        """从混合文本中提取 2-3 个核心学术关键词，用于检索.

        从用户输入或 LLM 返回的 topic 中智能提取关键词，
        解决 LLM 可能返回完整句子而非关键词的问题。

        策略：
        1. 先清除常见停用词/虚词/功能词
        2. 用正则匹配学术关键词模式
        3. 若匹配到 2+ 个关键词，用空格拼接返回
        4. 否则回退到 CNKI extract_core 逻辑

        Args:
            text: 原始文本（可能是完整句子或关键词）。

        Returns:
            空格分隔的核心关键词，如 "财政政策 经济增长"。
        """
        if not text:
            return ""
        import re
        # 常见学术关键词正则模式（按优先级排序）
        KEYWORD_PATTERNS = [
            r'[\u4e00-\u9fff]{2,4}政策',
            r'[\u4e00-\u9fff]{2,4}增长',
            r'[\u4e00-\u9fff]{2,4}效应',
            r'[\u4e00-\u9fff]{2,6}债务',
            r'[\u4e00-\u9fff]{2,4}风险',
            r'[\u4e00-\u9fff]{2,4}影响',
            r'[\u4e00-\u9fff]{2,4}发展',
            r'[\u4e00-\u9fff]{2,6}经济',
            r'[\u4e00-\u9fff]{2,4}财政',
            r'[\u4e00-\u9fff]{2,4}改革',
            r'[\u4e00-\u9fff]{2,4}创新',
            r'[\u4e00-\u9fff]{2,4}投资',
            r'[\u4e00-\u9fff]{2,4}治理',
        ]
        # 停用词和虚词 - 从文本中清除
        STOP_WORDS = re.compile(
            r'我想写一篇关于|我想研究|研究|分析|探讨|实证|论文|的|了|和|与|及|或|对|在|从|将|把|被|'
            r'基于|通过|利用|采用|使用|运用|进行|开展|构建|建立|提出|探讨|分析|考察|检验|验证|'
            r'一个|一种|一篇|这个|那个|及其|以及|及其|之间|之中|之上|之下|'
            r'影响|关系|作用|机制|效应|因素|问题|现状|对策|建议|策略'
        )
        # 先清除停用词
        cleaned = STOP_WORDS.sub(' ', text)
        # 清除多余空格
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        # 在清理后的文本中匹配关键词
        found = []
        remaining = cleaned
        for pattern in KEYWORD_PATTERNS:
            matches = re.findall(pattern, remaining)
            for m in matches:
                if m not in found and len(m) >= 4:
                    # 过滤以虚词开头的伪关键词
                    if m[0] in "的对了和与及或":
                        continue
                    found.append(m)
                    remaining = remaining.replace(m, " ", 1)

        if len(found) >= 2:
            return " ".join(found[:3])

        # 回退：从清理后的文本中提取
        if cleaned:
            segments = [s.strip() for s in cleaned.split() if len(s.strip()) >= 4]
            if len(segments) >= 2:
                return " ".join(segments[:3])
            if segments:
                return segments[0][:12]

        # 最终回退：CNKI extract_core 逻辑
        text_stripped = text.strip()
        for suffix in ("研究", "分析", "探讨", "实证", "效应", "影响"):
            if text_stripped.endswith(suffix):
                text_stripped = text_stripped[:-len(suffix)]
        if text_stripped.startswith("中国"):
            text_stripped = text_stripped[2:]
        segments = [s.strip() for s in text_stripped.split("的") if s.strip()]
        if segments:
            candidates = [s for s in segments if 4 <= len(s) <= 12]
            if candidates:
                return " ".join(candidates[:2])
            return segments[0][:12]
        return text_stripped[:12]

    async def _phase2_literature_search(self) -> None:
        """多源文献检索（CNKI 4层 + Semantic Scholar + arXiv）+ 8维统计分析."""
        self.console.print("\n[bold cyan]━━━ Phase 2: 文献检索与统计分析 ━━━[/bold cyan]")

        raw_topic = self.topic_info.get("topic", "")
        region = self.topic_info.get("region", "中国")
        raw_content = self.topic_info.get("content", "")
        from datetime import datetime as _dt
        year_start = self.topic_info.get("year_start", str(_dt.now().year - 7))
        year_end = self.topic_info.get("year_end", str(_dt.now().year))

        # 智能提取检索关键词（解决 LLM 返回完整句子的问题）
        topic = self._extract_search_keywords(raw_topic)
        content = self._extract_search_keywords(raw_content) if raw_content else ""
        # region 超过 10 字符时也做关键词提取（避免 LLM 返回完整句子作为 region）
        region = self._extract_search_keywords(region) if len(region) > 10 else region
        if not topic and raw_topic:
            topic = raw_topic[:50]
        self.console.print(f"  [dim]检索关键词: topic='{topic}', content='{content}'[/dim]")

        # ── 全局文献库查重：先看已有多少可复用 ──────────────────
        existing_papers = self.library.search(keyword=topic, limit=200)
        if existing_papers:
            shared = sum(
                1 for p in existing_papers
                if len(p.get("used_by_projects", [])) > 1
            )
            self.console.print(
                f"[dim]📚 全局文献库已有 {len(existing_papers)} 篇"
                f"「{topic}」相关文献可复用"
                f"（其中 {shared} 篇曾被其他论文引用）[/dim]"
            )

        # ── 中文文献检索：NCPSSD + CNKI 多源降级 ──────────────
        self.console.print("\n[dim]🔍 正在检索中文文献（NCPSSD + CNKI）...[/dim]")
        self._emit("literature_search", "progress", "正在检索中文文献（NCPSSD + CNKI + 万方）...")
        self.chinese_results = []

        try:
            chinese_result = await self.chinese_manager.search_chinese(
                topic=topic,
                region=region,
                content=content,
                year_start=year_start,
                year_end=year_end,
                max_per_source=50,
            )
            self.chinese_results.append(chinese_result)
            self.console.print(
                f"  [green]NCPSSD: 找到 {chinese_result.ncpssd_count} 篇[/green]"
            )
            if chinese_result.cnki_count > 0:
                self.console.print(
                    f"  [green]CNKI: 找到 {chinese_result.cnki_count} 篇[/green]"
                )
            if chinese_result.wanfang_count > 0:
                self.console.print(
                    f"  [green]万方: 找到 {chinese_result.wanfang_count} 篇[/green]"
                )
            self.console.print(
                f"  [green]合并去重后: {chinese_result.returned_count} 篇中文文献[/green]"
            )
            self._emit("literature_search", "progress", f"中文文献检索完成: {chinese_result.returned_count} 篇")
        except Exception as e:
            self.console.print(f"  [red]中文文献检索失败: {e}[/red]")
            from scholarpilot.tools.chinese_search import ChineseSearchResult
            self.chinese_results.append(ChineseSearchResult(query=topic))

        # 关闭中文检索引擎
        await self.chinese_manager.close()

        # ── 多源检索：Semantic Scholar + arXiv ──────────────
        self.console.print("\n[dim]🔍 正在并行检索英文文献源（Semantic Scholar + arXiv）...[/dim]")
        self._emit("literature_search", "progress", "正在并行检索英文文献（Semantic Scholar + arXiv）...")

        # 构建 Semantic Scholar 查询（使用英文翻译，与 OpenAlex 一致）
        ss_query = self._build_english_query(topic, region, content)
        year_filter = f"{year_start}-{year_end}" if year_start and year_end else ""

        # 构建 arXiv 查询（同样使用英文翻译）
        arxiv_query_en = self._build_english_query(topic, region, content)
        arxiv_query = ArxivEngine.build_query(
            all_fields=arxiv_query_en,
            category="econ.GN",  # General Economics
        )
        if not arxiv_query:
            arxiv_query = f"all:{arxiv_query_en}"

        # 并行检索
        ss_task = self.ss_engine.search(
            query=ss_query,
            limit=20,
            year=year_filter,
            fields_of_study="Economics",
        )
        arxiv_task = self.arxiv_engine.search(
            search_query=arxiv_query,
            max_results=10,
            sort_by="submittedDate",
        )

        ss_result, arxiv_result = await asyncio.gather(ss_task, arxiv_task, return_exceptions=True)

        # 处理 Semantic Scholar 结果
        if isinstance(ss_result, Exception):
            self.console.print(f"  [red]Semantic Scholar 检索失败: {ss_result}[/red]")
            self._emit("literature_search", "progress", "Semantic Scholar 检索失败，跳过")
            from scholarpilot.mcp.servers.semantic_scholar import SSSearchResult
            self.ss_results = [SSSearchResult(query=ss_query, total_count=0)]
        else:
            self.ss_results = [ss_result]
            self.console.print(
                f"  [green]Semantic Scholar: 找到 {ss_result.total_count} 篇英文文献"
                f"（返回 {len(ss_result.papers)} 篇）[/green]"
            )
            self._emit("literature_search", "progress", f"Semantic Scholar 检索完成: {ss_result.total_count} 篇")

        # 处理 arXiv 结果
        if isinstance(arxiv_result, Exception):
            self.console.print(f"  [red]arXiv 检索失败: {arxiv_result}[/red]")
            self._emit("literature_search", "progress", "arXiv 检索失败，跳过")
            from scholarpilot.mcp.servers.arxiv import ArxivSearchResult
            self.arxiv_results = [ArxivSearchResult(query=arxiv_query, total_count=0)]
        else:
            self.arxiv_results = [arxiv_result]
            self.console.print(
                f"  [green]arXiv: 找到 {arxiv_result.total_count} 篇预印本"
                f"（返回 {len(arxiv_result.papers)} 篇）[/green]"
            )
            self._emit("literature_search", "progress", f"arXiv 检索完成: {arxiv_result.total_count} 篇")

        # ── OpenAlex 检索（主力英文文献源，免费稳定）────────
        self.console.print("\n[dim]🔍 正在检索 OpenAlex（英文主力源）...[/dim]")
        self._emit("literature_search", "progress", "正在检索 OpenAlex（英文主力源）...")
        try:
            # 构建英文查询：将中文主题翻译为关键词
            openalex_query = self._build_english_query(topic, region, content)
            self.console.print(f"  [dim]英文检索词: {openalex_query}[/dim]")
            openalex_result = await self.openalex_engine.search(
                query=openalex_query,
                limit=50,
                year_start=year_start,
                year_end=year_end,
                has_abstract=True,
            )
            self.openalex_results = [openalex_result]
            self.console.print(
                f"  [green]OpenAlex: 找到 {openalex_result.total_count} 篇英文文献"
                f"（返回 {len(openalex_result.papers)} 篇）[/green]"
            )
            self._emit("literature_search", "progress", f"OpenAlex 检索完成: {openalex_result.total_count} 篇")
            if openalex_result.papers:
                top = openalex_result.papers[0]
                self.console.print(
                    f"  [dim]首篇: {top.title}... "
                    f"({top.primary_venue}, {top.year}, cited: {top.cited_by_count})[/dim]"
                )
        except Exception as e:
            self.console.print(f"  [red]OpenAlex 检索失败: {e}[/red]")
            self._emit("literature_search", "progress", "OpenAlex 检索失败，跳过")
            from scholarpilot.mcp.servers.openalex import OpenAlexSearchResult
            self.openalex_results = [OpenAlexSearchResult(query=ss_query, total_count=0)]

        # 关闭英文检索引擎
        self._emit("literature_search", "progress", "英文文献检索全部完成，正在计算统计...")
        await self.ss_engine.close()
        await self.arxiv_engine.close()
        await self.openalex_engine.close()

        # ── 计算 8 维统计（基于中文文献检索结果）────────────
        self.console.print("\n[dim]📊 正在计算 8 维统计数据...[/dim]")
        self._emit("literature_search", "progress", "正在计算 8 维文献统计数据...")
        # 将 ChineseSearchResult 转为 CNKISearchResult 兼容格式
        cnki_compatible = []
        for cr in self.chinese_results:
            total = cr.ncpssd_count + cr.cnki_count + cr.wanfang_count
            cnki_compatible.append(CNKISearchResult(
                query=cr.query,
                total_count=total,
            ))
        self.eight_dim_stats = calculate_eight_dimensions(cnki_compatible)

        # 显示统计结果
        vol = self.eight_dim_stats.get("literature_volume", {})
        comp = self.eight_dim_stats.get("competition_level", {})
        chinese_count = sum(
            r.ncpssd_count + r.cnki_count + r.wanfang_count
            for r in self.chinese_results
        )
        self.console.print(f"  中文文献总量: {chinese_count} 篇")
        ss_count = sum(r.total_count for r in self.ss_results)
        arxiv_count = sum(r.total_count for r in self.arxiv_results)
        openalex_count = sum(r.total_count for r in self.openalex_results)
        self.console.print(f"  Semantic Scholar 英文文献: {ss_count} 篇")
        self.console.print(f"  OpenAlex 英文文献: {openalex_count} 篇")
        self.console.print(f"  arXiv 预印本: {arxiv_count} 篇")
        self.console.print(f"  竞争程度: {comp.get('level', 'unknown')} - {comp.get('assessment', '')}")

        # 可行性判定
        self.feasibility = assess_feasibility(self.eight_dim_stats)
        self.console.print(
            f"  可行性: {self.feasibility.get('verdict', 'unknown')} "
            f"(置信度: {self.feasibility.get('confidence', 0):.0%})"
        )
        self.console.print(f"  [dim]{self.feasibility.get('reasoning', '')}[/dim]")

        # 保存到记忆
        self.memory.add("eight_dim_stats", self.eight_dim_stats)
        self.memory.add("feasibility", self.feasibility)
        self.memory.add("literature_sources", {
            "chinese_count": chinese_count,
            "ncpssd_count": sum(r.ncpssd_count for r in self.chinese_results),
            "cnki_count": sum(r.cnki_count for r in self.chinese_results),
            "wanfang_count": sum(r.wanfang_count for r in self.chinese_results),
            "ss_count": ss_count,
            "openalex_count": openalex_count,
            "arxiv_count": arxiv_count,
        })

        self._emit("literature_search", "progress",
            f"8维统计完成: 中{chinese_count}篇+英{ss_count+openalex_count}篇, "
            f"可行性{self.feasibility.get('verdict', '?')}")

        # 保存文献列表到文件
        papers_summary = self._format_papers_for_display()

        # ── 全局文献库入库：跨论文复用 ──────────────────────
        self._emit("literature_search", "progress", "正在入库全局文献库...")
        all_papers = self._collect_papers_for_library()
        if all_papers:
            new_count, reuse_count = self.library.add_papers_batch(
                all_papers, project_name=self.project_name
            )
            self.console.print(
                f"[dim]📚 全局文献库入库: 新增 {new_count} 篇，"
                f"复用 {reuse_count} 篇（共 {new_count + reuse_count} 篇）[/dim]"
            )
            self._emit("literature_search", "progress",
                f"文献库入库完成: 新增{new_count}篇, 复用{reuse_count}篇")

        bib_path = self.project_dir / "literature" / "references.bib"
        bib_path.write_text(f"% BibTeX references\n% 生成时间: {__import__('datetime').datetime.now()}\n\n", encoding="utf-8")

    def _collect_papers_for_library(self) -> list[dict[str, Any]]:
        """将各检索引擎的结果转为统一格式，供全局文献库入库.

        汇集中文（NCPSSD+CNKI）、Semantic Scholar、arXiv、OpenAlex 的文献，
        转为统一的字典格式。
        """
        papers: list[dict[str, Any]] = []

        # 中文文献（NCPSSD + CNKI）
        for result in getattr(self, "chinese_results", []):
            for paper in result.papers:
                papers.append({
                    "title": paper.title,
                    "authors": paper.authors if isinstance(paper.authors, list) else [paper.authors],
                    "year": str(paper.year) if paper.year else "",
                    "journal": paper.journal or "",
                    "abstract": getattr(paper, "abstract", "") or "",
                    "source": paper.source,
                    "url": getattr(paper, "url", "") or "",
                    "language": "zh",
                })

        # Semantic Scholar
        for result in getattr(self, "ss_results", []):
            for paper in result.papers:
                papers.append({
                    "title": paper.title,
                    "authors": paper.authors if isinstance(paper.authors, list) else [],
                    "year": str(paper.year) if paper.year else "",
                    "journal": getattr(paper, "venue", "") or "",
                    "abstract": getattr(paper, "abstract", "") or "",
                    "source": "semantic_scholar",
                    "url": getattr(paper, "url", "") or "",
                    "doi": getattr(paper, "doi", "") or "",
                    "language": "en",
                })

        # arXiv
        for result in getattr(self, "arxiv_results", []):
            for paper in result.papers:
                # ArxivPaper 没有 year 字段，从 published (ISO日期) 提取
                published = getattr(paper, "published", "") or ""
                year_str = published[:4] if len(published) >= 4 else ""
                papers.append({
                    "title": paper.title,
                    "authors": paper.authors if isinstance(paper.authors, list) else [],
                    "year": year_str,
                    "journal": "arXiv",
                    "abstract": getattr(paper, "abstract", "") or "",
                    "source": "arxiv",
                    "url": getattr(paper, "abs_url", "") or getattr(paper, "pdf_url", "") or "",
                    "language": "en",
                })

        # OpenAlex
        for result in getattr(self, "openalex_results", []):
            for paper in result.papers:
                papers.append({
                    "title": paper.title,
                    "authors": getattr(paper, "authors", []) or [],
                    "year": str(paper.year) if paper.year else "",
                    "journal": getattr(paper, "primary_venue", "") or "",
                    "abstract": getattr(paper, "abstract", "") or "",
                    "source": "openalex",
                    "url": getattr(paper, "url", "") or "",
                    "doi": getattr(paper, "doi", "") or "",
                    "language": "en",
                })

        return papers

    def _build_english_query(self, topic: str, region: str, content: str) -> str:
        """将中文研究主题翻译为英文检索词，用于 OpenAlex 检索.

        采用关键词映射 + LLM 兜底策略：常见学术关键词有预设映射，
        未匹配的关键词通过简单规则转换。

        Args:
            topic: 中文核心主题（如"地方政府债务"）。
            region: 中文区域（如"中国"）。
            content: 中文研究内容（如"空间溢出效应"）。

        Returns:
            英文检索词字符串（如"local government debt China spatial spillover"）。
        """
        # 常见财政学/经济学中文关键词到英文的映射
        CN_EN_MAP = {
            # 主题 - 财政政策
            "财政政策": "fiscal policy",
            "财政支出": "fiscal expenditure",
            "财政收入": "fiscal revenue",
            "财政分权": "fiscal decentralization",
            "财政可持续": "fiscal sustainability",
            "财政透明度": "fiscal transparency",
            "税收政策": "tax policy",
            "税收竞争": "tax competition",
            "税收负担": "tax burden",
            "减税降费": "tax reduction",
            # 主题 - 经济增长
            "经济增长": "economic growth",
            "经济发展": "economic development",
            "高质量发展": "high-quality development",
            "经济波动": "economic fluctuation",
            "经济周期": "business cycle",
            # 主题 - 债务
            "地方政府债务": "local government debt",
            "地方债": "municipal bond",
            "城投债": "urban investment bond",
            "隐形债务": "implicit debt",
            "隐性债务": "implicit debt",
            "债务风险": "debt risk",
            "债务置换": "debt swap",
            # 主题 - 预算
            "零基预算": "zero-based budgeting",
            "预算改革": "budget reform",
            "预算绩效": "budget performance",
            "转移支付": "transfer payment",
            "绩效评价": "performance evaluation",
            # 内容
            "空间溢出": "spatial spillover",
            "溢出效应": "spillover effect",
            "空间计量": "spatial econometrics",
            "影响因素": "determinants",
            "效率": "efficiency",
            "门槛效应": "threshold effect",
            "非线性": "nonlinear",
            "异质性": "heterogeneity",
            "收敛性": "convergence",
            "协同": "coordination",
            "路径依赖": "path dependence",
            "制度变迁": "institutional change",
            "机制分析": "mechanism analysis",
            # 数字经济/创新
            "数字经济": "digital economy",
            "数字化转型": "digital transformation",
            "绿色创新": "green innovation",
            "企业创新": "enterprise innovation",
            "技术创新": "technological innovation",
            "创新绩效": "innovation performance",
            "绿色转型": "green transformation",
            "ESG": "ESG",
            "可持续发展": "sustainable development",
            "碳排放": "carbon emission",
            "能源转型": "energy transition",
            "上市公司": "listed companies",
            "A股": "A-share",
            "面板数据": "panel data",
            "中介效应": "mediating effect",
            "调节效应": "moderating effect",
            "异质性分析": "heterogeneity analysis",
            "稳健性检验": "robustness check",
            "内生性": "endogeneity",
            # 区域
            "中国": "China",
            "中国西部": "western China",
            "西部地区": "western China",
            "东部地区": "eastern China",
            "中部地区": "central China",
            "地级市": "prefecture-level city",
            "省级": "provincial",
        }

        # 逐段翻译：只保留匹配到的英文关键词，丢弃未翻译的中文残文
        # 策略：
        # 1. 若已是空格分隔的关键词（由 _extract_search_keywords 提取），
        #    对每个关键词单独翻译，避免重叠匹配问题
        # 2. 否则使用子串匹配（兼容旧逻辑）
        parts = []
        for text in [topic, content, region]:
            if not text:
                continue
            # 尝试完整匹配
            if text.strip() in CN_EN_MAP:
                parts.append(CN_EN_MAP[text.strip()])
                continue
            # 空格分隔的关键词 → 逐个翻译
            if " " in text.strip():
                found_keywords = []
                for kw in text.strip().split():
                    kw = kw.strip()
                    if not kw:
                        continue
                    if kw in CN_EN_MAP:
                        found_keywords.append(CN_EN_MAP[kw])
                if found_keywords:
                    parts.append(" ".join(found_keywords))
                continue
            # 子串匹配：提取所有已知中文关键词的英文翻译
            found_keywords = []
            remaining = text
            for cn, en in sorted(CN_EN_MAP.items(), key=lambda x: -len(x[0])):
                if cn in remaining:
                    found_keywords.append(en)
                    remaining = remaining.replace(cn, " ", 1)  # 只替换首次匹配
            if found_keywords:
                parts.append(" ".join(found_keywords))

        # 去重去空
        seen = set()
        result_parts = []
        for p in " ".join(parts).split():
            p_lower = p.lower()
            if p_lower not in seen:
                seen.add(p_lower)
                result_parts.append(p)

        return " ".join(result_parts) if result_parts else topic

    def _format_papers_brief(self, max_papers: int = 8) -> str:
        """格式化精简文献列表（仅标题+作者+年份，不含摘要），用于章节撰写.

        限制文献数量以避免 prompt 过长导致 LLM 空响应。

        Args:
            max_papers: 每个来源最大返回数量。

        Returns:
            精简格式的文献列表字符串。
        """
        lines = []
        count = 0

        # 中文文献
        for result in self.chinese_results:
            if result.papers:
                for paper in result.papers:
                    if count >= max_papers:
                        break
                    authors = ", ".join(paper.authors[:2]) if paper.authors else "未知"
                    lines.append(f"- {authors}（{paper.year}）.{paper.title}。{paper.journal or ''}")
                    count += 1

        # OpenAlex 英文文献
        for r in self.openalex_results:
            for paper in r.papers:
                if count >= max_papers * 2:
                    break
                authors = ", ".join(paper.authors[:2]) if paper.authors else "Unknown"
                lines.append(f"- {authors} ({paper.year}). {paper.title}. {paper.primary_venue or ''}")
                count += 1

        return "\n".join(lines) if lines else "暂无相关文献"

    def _format_papers_for_display(self) -> str:
        """格式化论文列表用于显示（中文文献 + Semantic Scholar + arXiv）."""
        lines = []

        # 中文文献（CNKI + 万方 + NCPSSD 合并去重）
        for i, result in enumerate(self.chinese_results):
            ncpssd_papers = [p for p in result.papers if p.source == "ncpssd"]
            cnki_papers = [p for p in result.papers if p.source == "cnki"]
            wanfang_papers = [p for p in result.papers if p.source == "wanfang"]

            if cnki_papers:
                lines.append(f"\n### CNKI 中文文献 ({result.cnki_count} 篇，显示 {len(cnki_papers)} 篇)")
                for j, paper in enumerate(cnki_papers[:10]):
                    authors = ", ".join(paper.authors[:3]) if paper.authors else ""
                    lines.append(
                        f"{j+1}. {paper.title} - {authors} "
                        f"({paper.journal}, {paper.year})"
                    )

            if wanfang_papers:
                lines.append(f"\n### 万方中文文献 ({result.wanfang_count} 篇，显示 {len(wanfang_papers)} 篇)")
                for j, paper in enumerate(wanfang_papers[:10]):
                    authors = ", ".join(paper.authors[:3]) if paper.authors else ""
                    ptype = f" [{paper.paper_type}]" if paper.paper_type else ""
                    lines.append(
                        f"{j+1}. {paper.title} - {authors} "
                        f"({paper.journal}, {paper.year}){ptype}"
                    )

            if ncpssd_papers:
                lines.append(f"\n### NCPSSD 中文文献 ({result.ncpssd_count} 篇，显示 {len(ncpssd_papers)} 篇)")
                for j, paper in enumerate(ncpssd_papers[:10]):
                    authors = ", ".join(paper.authors[:3]) if paper.authors else ""
                    lines.append(
                        f"{j+1}. {paper.title} - {authors} "
                        f"({paper.journal}, {paper.year})"
                    )

        # Semantic Scholar 英文文献
        ss_papers = []
        for r in self.ss_results:
            ss_papers.extend(r.papers)
        ss_total = sum(r.total_count for r in self.ss_results)
        if ss_papers:
            lines.append(f"\n### Semantic Scholar 英文文献 (共 {ss_total} 篇，显示 {len(ss_papers)} 篇)")
            for j, paper in enumerate(ss_papers[:10]):
                authors = ", ".join(paper.authors[:3])
                cited = f" [cited: {paper.citation_count}]" if paper.citation_count else ""
                venue = paper.venue or paper.journal_name or "N/A"
                year = paper.year or "N/A"
                lines.append(f"{j+1}. {paper.title} - {authors} ({venue}, {year}){cited}")

        # arXiv 预印本
        arxiv_papers = []
        for r in self.arxiv_results:
            arxiv_papers.extend(r.papers)
        if arxiv_papers:
            lines.append(f"\n### arXiv 预印本 ({len(arxiv_papers)} 篇)")
            for j, paper in enumerate(arxiv_papers[:10]):
                authors = ", ".join(paper.authors[:3])
                arxiv_id = f" [{paper.arxiv_id}]" if paper.arxiv_id else ""
                year = paper.published[:4] if paper.published else "N/A"
                lines.append(f"{j+1}. {paper.title} - {authors} ({year}){arxiv_id}")

        return "\n".join(lines) if lines else "暂无检索结果"

    def _format_papers_for_review(self, max_per_source: int = 15) -> str:
        """格式化文献列表用于文献综述撰写（包含摘要，更多文献）.

        Args:
            max_per_source: 每个来源最多显示的文献数.

        Returns:
            格式化的文献列表字符串.
        """
        lines = []

        # 中文文献（CNKI + NCPSSD）
        for result in self.chinese_results:
            if result.papers:
                lines.append(f"### 中文文献（{len(result.papers)}篇）")
                for j, paper in enumerate(result.papers[:max_per_source]):
                    authors = ", ".join(paper.authors[:3]) if paper.authors else "未知"
                    abstract = f"\n   摘要：{paper.abstract[:150]}..." if paper.abstract and len(paper.abstract) > 30 else ""
                    lines.append(f"{j+1}. {authors}（{paper.year}）。{paper.title}。{paper.journal or '未知期刊'}。{abstract}")

        # OpenAlex 英文文献（主力源，含摘要）
        oa_papers = []
        for r in self.openalex_results:
            oa_papers.extend(r.papers)
        oa_total = sum(r.total_count for r in self.openalex_results)
        if oa_papers:
            lines.append(f"\n### 英文文献 - OpenAlex（共{oa_total}篇，显示{min(len(oa_papers), max_per_source)}篇）")
            for j, paper in enumerate(oa_papers[:max_per_source]):
                authors = ", ".join(paper.authors[:3]) if paper.authors else "Unknown"
                venue = paper.primary_venue or "N/A"
                abstract = f"\n   Abstract: {paper.abstract[:150]}..." if paper.abstract else ""
                cited = f" [cited: {paper.cited_by_count}]" if paper.cited_by_count else ""
                lines.append(f"{j+1}. {authors} ({paper.year}). {paper.title}. {venue}.{cited}{abstract}")

        return "\n".join(lines) if lines else "暂无检索结果"

    # ===== Phase 2.5: 证据矩阵构建 =====

    async def _phase2_5_build_evidence_matrix(self) -> None:
        """Phase 2.5: 构建证据矩阵.

        在文献检索完成后、规格生成前，对文献池进行结构化证据提取：
        1. 收集当前项目的所有文献
        2. 通过 LLM 批量提取每篇文献的关键发现、证据类型、证据强度
        3. 构建论点-证据映射（此处仅建文献层，章节映射在 Phase 5 大纲生成后补充）
        4. 持久化到 .scholar/evidence_matrix.json 和 literature/evidence_matrix.md

        异常处理：证据矩阵构建失败不中断主流程，仅记录日志。
        """
        from rich.panel import Panel

        self.console.print(
            Panel(
                "[bold cyan]证据矩阵构建[/bold cyan]\n"
                "结构化提取文献证据 → 建立论点-证据映射 → 识别证据缺口",
                title="Phase 2.5",
                border_style="cyan",
            )
        )

        topic = self.topic_info.get("topic", "")
        if not topic:
            self.console.print("[yellow]研究主题为空，跳过证据矩阵构建[/yellow]")
            return

        # 收集当前项目的文献
        try:
            project_papers = self.library.get_project_papers(self.project_name)
        except Exception as e:
            logger.warning("获取项目文献失败: %s", e)
            project_papers = []

        if not project_papers:
            # 回退到各检索引擎的原始结果
            project_papers = self._collect_papers_for_library()

        if not project_papers:
            self.console.print("[yellow]文献池为空，跳过证据矩阵构建[/yellow]")
            return

        # 过滤有摘要的文献（无摘要无法提取证据）
        papers_with_abstract = [
            p for p in project_papers
            if p.get("abstract") and p.get("abstract", "").strip()
        ]
        self.console.print(
            f"  [dim]文献池: {len(project_papers)} 篇，"
            f"其中 {len(papers_with_abstract)} 篇有摘要可提取证据[/dim]"
        )

        if not papers_with_abstract:
            self.console.print("[yellow]无含摘要的文献，跳过证据矩阵构建[/yellow]")
            return

        # 初始化证据矩阵构建器
        try:
            from scholarpilot.tools.evidence_matrix import EvidenceMatrixBuilder
        except ImportError as e:
            logger.error("导入证据矩阵模块失败: %s", e)
            self.console.print(f"[red]导入证据矩阵模块失败: {e}[/red]")
            return

        self.evidence_matrix_builder = EvidenceMatrixBuilder(
            llm=self.llm,
            library=self.library,
        )

        # 构建证据矩阵（不含章节映射，大纲尚未生成）
        self.console.print("[dim]📋 正在构建证据矩阵（批量提取文献证据）...[/dim]")
        try:
            matrix = await self.evidence_matrix_builder.build_matrix(
                project_papers=papers_with_abstract,
                topic=topic,
                outline_sections=None,  # 大纲尚未生成，章节映射在 Phase 5 补充
                batch_size=10,
                max_papers=30,
                progress_callback=lambda phase, status, msg: self._emit(phase, status, msg),
            )
        except Exception as e:
            logger.error("证据矩阵构建失败: %s", e, exc_info=True)
            self.console.print(f"[red]证据矩阵构建失败: {e}[/red]")
            return

        # 统计输出
        strong = sum(1 for p in matrix.papers if p.evidence_strength.value == "strong")
        moderate = sum(1 for p in matrix.papers if p.evidence_strength.value == "moderate")
        weak = sum(1 for p in matrix.papers if p.evidence_strength.value == "weak")
        unverified = sum(1 for p in matrix.papers if p.evidence_strength.value == "unverified")

        self.console.print(f"  [green]证据矩阵构建完成: {matrix.total_papers} 篇文献[/green]")
        self.console.print(
            f"  [dim]证据强度分布: 强{strong} / 中{moderate} / 弱{weak} / 未验证{unverified}[/dim]"
        )

        # 持久化
        try:
            matrix_path = self.project_dir / ".scholar" / "evidence_matrix.json"
            matrix.save(matrix_path)
            self.console.print(f"  [dim]已保存: {matrix_path}[/dim]")

            # 导出人类可读的 Markdown 版本
            md_path = self.project_dir / "literature" / "evidence_matrix.md"
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(matrix.to_markdown(), encoding="utf-8")
            self.console.print(f"  [dim]已导出: {md_path}[/dim]")
        except Exception as e:
            logger.warning("证据矩阵持久化失败: %s", e)
            self.console.print(f"  [yellow]证据矩阵持久化失败: {e}[/yellow]")

        # 保存到记忆
        self.memory.add("evidence_matrix", {
            "total_papers": matrix.total_papers,
            "strong": strong,
            "moderate": moderate,
            "weak": weak,
            "unverified": unverified,
            "matrix_path": str(matrix_path) if 'matrix_path' in dir() else "",
        })

    # ===== Phase 3: 生成论文规格 =====

    async def _phase3_generate_spec(self) -> None:
        """生成论文规格文档（SPEC.md）."""
        self.console.print("\n[bold cyan]━━━ Phase 3: 生成论文规格 ━━━[/bold cyan]")

        # 准备上下文数据
        vol = self.eight_dim_stats.get("literature_volume", {})
        comp = self.eight_dim_stats.get("competition_level", {})
        core = self.eight_dim_stats.get("core_journal_ratio", {})

        # 格式化关键论文
        key_papers = self._format_papers_for_display()

        # RAG 知识库注入（Phase 3 增强）：将数据库覆盖信息注入 SPEC 生成上下文
        # 使 SPEC 中的"数据来源"和"变量测量"部分基于实际可得的机构数据库
        try:
            rag_coverage = self.memory.get("rag_database_coverage")
            if rag_coverage and rag_coverage.get("databases"):
                rag_dbs = rag_coverage["databases"]
                rag_text_parts = ["\n## 机构数据库覆盖（RAG 知识库）"]
                rag_text_parts.append(f"已探查到 {rag_coverage.get('db_count', 0)} 个数据库覆盖该研究主题：")
                for db in rag_dbs[:6]:
                    name = db.get("name", db.get("db_key", ""))
                    platform = db.get("platform", db.get("type", ""))
                    desc = db.get("description", db.get("desc", ""))[:80]
                    rag_text_parts.append(f"- {name}（{platform}）: {desc}")
                rag_text_parts.append("\n请在 SPEC 的数据来源部分优先推荐以上数据库。")
                key_papers += "\n".join(rag_text_parts)
                self.console.print(
                    f"  [dim]📚 RAG 注入: {len(rag_dbs)} 个数据库覆盖信息已加入 SPEC 上下文[/dim]"
                )
        except Exception as e:
            logger.debug(f"Phase 3 RAG 注入失败(非致命): {e}")

        # 多源检索计数
        ss_count = sum(r.total_count for r in self.ss_results)
        arxiv_count = sum(r.total_count for r in self.arxiv_results)
        chinese_count = sum(
            r.ncpssd_count + r.cnki_count + r.wanfang_count
            for r in self.chinese_results
        )

        # 构建上下文
        research_type = self.topic_info.get("research_type", "empirical")
        self.console.print(f"[dim]  论文类型: {research_type}[/dim]")
        ctx = self.context_engine.build_spec_generation_context(
            topic_info=self.topic_info,
            research_type=research_type,
            cnki_count=chinese_count,  # 中文文献总量（NCPSSD+CNKI）
            ss_count=ss_count,
            arxiv_count=arxiv_count,
            core_ratio=core.get("ratio", 0),
            competition_level=f"{comp.get('level', 'unknown')} - {comp.get('assessment', '')}",
            feasibility_result=json.dumps(self.feasibility, ensure_ascii=False, indent=2),
            key_papers=key_papers,
            discipline=self.discipline,
            history=[],  # SPEC 生成不传历史，避免消息序列混乱导致空响应
        )

        # 调用 LLM 生成 SPEC
        self.console.print("[dim]📝 正在生成论文规格文档...[/dim]")
        self._emit("spec_generation", "progress", "正在调用 LLM 生成论文规格文档...")
        spec_content = await self.llm.chat(
            messages=ctx.to_messages(),
            model=self.config.default_writing_model,
            temperature=0.3,
        )

        # 保存 SPEC.md
        spec_path = self.file_manager.save_spec(self.project_dir, spec_content)
        self.console.print(f"[green]SPEC.md 已生成: {spec_path}[/green]")

        # 记录历史
        self.history.append({"role": "assistant", "content": f"已生成论文规格文档:\n{spec_content[:500]}..."})

        # 保存到记忆
        self.memory.add("spec", {"path": str(spec_path), "content": spec_content})

    # ===== Phase 5: 生成大纲 =====

    async def _phase5_generate_outline(self) -> None:
        """生成论文大纲."""
        self.console.print("\n[bold cyan]━━━ Phase 5: 生成论文大纲 ━━━[/bold cyan]")

        # 加载 SPEC
        spec_content = self.file_manager.load_spec(self.project_dir) or ""

        # 构建上下文
        research_type = self.topic_info.get("research_type", "empirical")
        ctx = self.context_engine.build_outline_context(
            spec_content=spec_content,
            research_type=research_type,
            literature_summary=self._format_papers_for_display(),
            user_thoughts="",
            target_journal="CSSCI核心期刊",
            discipline=self.discipline,
            history=[],  # 大纲生成不传历史，避免消息序列混乱导致空响应
        )

        # 调用 LLM 生成大纲
        self.console.print("[dim]📋 正在生成论文大纲...[/dim]")
        self._emit("outline", "progress", "正在调用 LLM 生成论文大纲...")
        outline_content = await self.llm.chat(
            messages=ctx.to_messages(),
            model=self.config.default_writing_model,
            temperature=0.4,
        )

        # 尝试提取 JSON 结构
        outline_json = self._extract_json(outline_content)

        # 保存大纲
        outline_path = self.file_manager.save_outline(
            self.project_dir,
            md_content=outline_content,
            json_data=outline_json,
        )
        self.console.print(f"[green]大纲已生成: {outline_path}[/green]")

        # 保存到记忆
        self.memory.add("outline", {"path": str(outline_path), "json": outline_json})

        # ── 补充证据矩阵的章节-论点映射（Phase 2.5 → Phase 5 联动）──
        if self.evidence_matrix_builder and self.evidence_matrix_builder._current_matrix:
            sections_for_mapping = outline_json.get("sections", []) if outline_json else []
            if sections_for_mapping:
                self.console.print("[dim]📋 补充证据矩阵章节-论点映射...[/dim]")
                try:
                    updated_matrix = await self.evidence_matrix_builder.fill_section_maps(
                        self.evidence_matrix_builder._current_matrix,
                        sections_for_mapping,
                    )
                    # 重新持久化
                    matrix_path = self.project_dir / ".scholar" / "evidence_matrix.json"
                    updated_matrix.save(matrix_path)
                    md_path = self.project_dir / "literature" / "evidence_matrix.md"
                    md_path.write_text(updated_matrix.to_markdown(), encoding="utf-8")
                    gap_count = updated_matrix.gap_report.get("total_gaps", 0)
                    self.console.print(
                        f"  [green]章节映射完成: {len(updated_matrix.section_maps)} 章，"
                        f"证据缺口 {gap_count} 处[/green]"
                    )
                except Exception as e:
                    logger.warning("证据矩阵章节映射补充失败: %s", e)
                    self.console.print(f"  [yellow]证据矩阵章节映射补充失败: {e}[/yellow]")

    # ===== Phase 7: 逐章撰写 =====

    async def _phase7_write_sections(self, skip_sections: list[str] | None = None) -> None:
        """基于大纲逐章撰写论文（支持章节级断点恢复）.

        科研场景：写到第三章时中断，重新启动后自动跳过已完成的前两章，
        从第三章继续，不需要重新生成。

        Args:
            skip_sections: 要跳过的已完成章节名列表，如 ["chapter1", "chapter2"]。
        """
        self.console.print("\n[bold cyan]━━━ Phase 7: 逐章撰写 ━━━[/bold cyan]")

        # 加载大纲（优先从 outline.md 解析，兼容 outline.json）
        outline_md_path = self.project_dir / "outline.md"
        outline_json_path = self.project_dir / "outline.json"

        if not outline_md_path.exists() and not outline_json_path.exists():
            self.console.print("[red]大纲文件不存在，跳过撰写[/red]")
            return

        outline_data = self.file_manager.load_state(self.project_dir) or {}
        sections: list[dict[str, Any]] = []
        outline_json: dict[str, Any] = {}

        # 优先尝试从 JSON 读取结构化数据
        if outline_json_path.exists():
            try:
                outline_json = json.loads(outline_json_path.read_text(encoding="utf-8"))
                sections = outline_json.get("sections", [])
            except Exception:
                pass

        # 如果 JSON 中没有章节信息，从 Markdown 解析
        if not sections and outline_md_path.exists():
            self.console.print("[dim]从 outline.md 解析章节结构...[/dim]")
            try:
                md_outline = outline_md_path.read_text(encoding="utf-8")
                sections = self._extract_sections_from_md(md_outline)
            except Exception as e:
                self.console.print(f"[red]解析 Markdown 大纲失败: {e}[/red]")
                return

        paper_title = outline_json.get("title", "论文")

        # 准备文献信息
        papers_info = self._format_papers_for_display()

        # 加载实证数据（如果用户在 Phase 6.5 提供了数据）
        from scholarpilot.tools.data_collector import format_stats_for_prompt, is_empirical_section

        empirical_data_text = ""
        stats_path = self.project_dir / ".scholar" / "descriptive_stats.json"
        if stats_path.exists():
            try:
                stats_json = json.loads(stats_path.read_text(encoding="utf-8"))
                # descriptive_stats.json 结构: {"stats": {...}, "data_file": "..."}
                stats = stats_json.get("stats", stats_json)
                if stats and isinstance(stats, dict):
                    empirical_data_text = format_stats_for_prompt(stats)
                    self.console.print(
                        f"[dim]📊 已加载描述性统计数据（{len(stats)} 个变量），"
                        f"将在实证章节中注入[/dim]"
                    )
            except Exception as e:
                logger.warning(f"加载描述性统计失败: {e}")

        # 逐章撰写
        previous_summaries: list[str] = []
        skip_set = set(skip_sections or [])
        completed_sections = list(skip_set)  # 从已跳过的章节开始累计

        # 如有跳过的章节，加载其内容作为上下文
        if skip_set:
            self.console.print(
                f"[dim]⏭️ 跳过 {len(skip_set)} 个已完成章节，从断点继续[/dim]"
            )
            for i, section in enumerate(sections):
                section_name = f"chapter{i+1}"
                if section_name in skip_set:
                    existing = self.file_manager.load_section(self.project_dir, section_name)
                    if existing:
                        section_title = section.get("title", f"第{i+1}章")
                        previous_summaries.append(f"## {section_title}\n{existing[:500]}...")

        for i, section in enumerate(sections):
            section_title = section.get("title", f"第{i+1}章")
            word_count = section.get("word_count", 2000)
            subsections = section.get("subsections", [])
            key_points = section.get("key_points", [])

            section_name = f"chapter{i+1}"

            # 章节级断点恢复：跳过已完成的章节
            if section_name in skip_set:
                continue

            self.console.print(f"\n[dim]✍️ 正在撰写: {section_title} (约{word_count}字)...[/dim]")
            self._emit(
                "section_writing", "progress",
                f"正在撰写: {section_title}（第{i+1}章/共{len(sections)}章）",
                progress_pct=(i / len(sections)) if sections else 0,
                current_chapter=i + 1,
                total_chapters=len(sections),
                section_title=section_title,
            )

            # 为文献综述章节注入更详细的文献列表（含摘要），其他章节使用精简列表
            # 优先使用证据矩阵的结构化证据（如有）
            evidence_context = ""
            relevant_papers = self._format_papers_brief(max_papers=8)
            if "文献综述" in section_title or "综述" in section_title:
                relevant_papers = self._format_papers_for_review(max_per_source=10)
                self.console.print("[dim]  📚 文献综述章节：注入详细文献列表（含摘要）[/dim]")

            # 证据矩阵注入（Phase 2.5 生成）
            if hasattr(self, "evidence_matrix_builder") and self.evidence_matrix_builder:
                try:
                    evidence_context = self.evidence_matrix_builder.format_for_writing(section_title)
                    if evidence_context and "证据矩阵尚未构建" not in evidence_context:
                        self.console.print("[dim]  📋 证据矩阵：注入结构化论点-证据映射[/dim]")
                except Exception as e:
                    logger.debug("证据矩阵注入失败: %s", e)

            # 判断当前章节是否为实证章节，决定是否注入真实数据
            section_empirical_data = ""
            if empirical_data_text and is_empirical_section(section_title):
                section_empirical_data = empirical_data_text
                self.console.print("[dim]  📊 实证章节：注入真实描述性统计数据[/dim]")

            # 修改9: 注入 RAG 推荐的数据库和指标上下文（供研究设计/数据来源章节引用）
            rag_context_text = ""
            try:
                rag_ctx = self.memory.get("rag_context")
                if rag_ctx and isinstance(rag_ctx, str):
                    rag_context_text = rag_ctx
            except Exception:
                pass

            # 构建上下文（不再传入完整大纲，避免 prompt 过长）
            research_type = self.topic_info.get("research_type", "empirical")

            # 前序章节摘要：仅保留最近1章，每章限300字，避免 prompt 膨胀
            prev_summary_text = ""
            if previous_summaries:
                last_summary = previous_summaries[-1]
                prev_summary_text = last_summary[:300] + "..." if len(last_summary) > 300 else last_summary

            # 将 RAG 推荐上下文追加到证据上下文
            if rag_context_text:
                evidence_context = (evidence_context + "\n\n" + rag_context_text) if evidence_context else rag_context_text

            ctx = self.context_engine.build_section_writing_context(
                paper_title=paper_title,
                target_journal="CSSCI核心期刊",
                language="中文",
                outline="",  # 不再注入完整大纲
                section_title=section_title,
                word_count=word_count,
                subsections=subsections,
                key_points=key_points,
                research_type=research_type,
                relevant_papers=relevant_papers,
                previous_sections=prev_summary_text,
                empirical_data=section_empirical_data,
                evidence_context=evidence_context,
                discipline=self.discipline,
                history=[],  # 章节撰写不传历史，避免 prompt 膨胀
            )

            # 调用 LLM
            try:
                section_content = await self.llm.chat(
                    messages=ctx.to_messages(),
                    model=self.config.default_writing_model,
                    temperature=0.6,
                )

                # 内容检查：拒绝保存空内容
                if not section_content or not section_content.strip():
                    raise RuntimeError(
                        f"章节 '{section_title}' 的 LLM 响应为空，"
                        f"重试已耗尽，跳过此章节"
                    )

                # 保存章节（自动创建版本快照，标注为初稿）
                section_path = self.file_manager.save_section_with_version(
                    self.project_dir, section_name, section_content,
                    label="初稿",
                    note=f"AI生成初稿 - {section_title}",
                )
                self.console.print(f"  [green]已保存: {section_path}[/green]")

                # 记录摘要供下一章参考（限300字，避免 prompt 膨胀）
                previous_summaries.append(f"## {section_title}\n{section_content[:300]}...")

                # 章节级进度保存（断点续写用）
                completed_sections.append(section_name)
                self.file_manager.save_progress(
                    self.project_dir, "section_writing",
                    completed_sections=completed_sections,
                    total_sections=len(sections),
                    phase_detail=f"正在撰写: {section_title}（{len(completed_sections)}/{len(sections)}）",
                )
                self._emit(
                    "section_writing", "progress",
                    f"已完成: {section_title}（{len(completed_sections)}/{len(sections)}）",
                    progress_pct=len(completed_sections) / len(sections) if sections else 0,
                    completed_chapters=len(completed_sections),
                    total_chapters=len(sections),
                    section_title=section_title,
                    char_count=len(section_content),
                )
                self._save_step_output("section_writing")

            except Exception as e:
                self.console.print(f"  [red]章节撰写失败: {e}[/red]")
                logger.error(f"Section writing failed: {e}", exc_info=True)

        # 合并所有章节为完整草稿
        self._emit("section_writing", "progress", "正在合并所有章节为完整草稿...")
        self._merge_draft()

        # Phase 7a: 摘要+关键词+分类号生成
        await self._phase7a_generate_abstract()

        # Phase 7b: 引用管理（提取→验证→格式化→附加参考文献+AI声明）
        await self._phase7b_citation_management()

        # Phase 7c: 实证表格模板生成（仅实证论文）
        await self._phase7c_generate_table_templates()

        # 质量报告：写完后立即反馈达标情况
        report = self.generate_quality_report()
        self._display_quality_report(report)

    async def _phase6_5_data_collection(self) -> bool:
        """Phase 6.5: 数据采集协作（仅实证论文）.

        生成数据采集指南和 CSV 模板，暂停等待用户提交数据。

        Returns:
            True 如果用户提供了数据，False 如果用户跳过。
        """
        self.console.print("\n[bold cyan]━━━ Phase 6.5: 数据采集协作 ━━━[/bold cyan]")

        # 读取 SPEC
        spec_path = self.project_dir / "SPEC.json"
        spec_content = "{}"
        if spec_path.exists():
            spec_content = spec_path.read_text(encoding="utf-8")
        else:
            spec_md = self.project_dir / "SPEC.md"
            if spec_md.exists():
                spec_content = spec_md.read_text(encoding="utf-8")

        research_type = self.topic_info.get("research_type", "empirical")

        # 1. 优先调用 DataSourceGuide（集成 RAG 知识库）生成数据采集指南
        self.console.print("[dim]📝 正在生成数据采集指南（RAG 增强）...[/dim]")
        guide_content = None
        rag_recommendations = None

        try:
            from scholarpilot.tools.data_source_guide import DataSourceGuide
            ds_guide = DataSourceGuide(project_dir=self.project_dir)
            guide_content = ds_guide.generate_guide(spec_content)

            # 检查是否包含 RAG 推荐章节
            if "RAG 智能推荐数据库" in guide_content:
                self.console.print("  [green]✓ RAG 知识库已激活，数据采集指南包含智能推荐数据库[/green]")
            else:
                self.console.print("  [yellow]⚠ RAG 知识库未激活，指南仅包含静态数据源映射[/yellow]")

            # 获取 RAG 推荐结果（结构化数据），供后续章节撰写使用
            rag_recommendations = ds_guide.get_rag_recommendations(spec_content)
            if rag_recommendations and rag_recommendations.get("rag_active"):
                db_count = len(rag_recommendations.get("databases", []))
                ind_count = len(rag_recommendations.get("indicators", []))
                self.console.print(
                    f"  [dim]RAG 推荐: {db_count} 个数据库, {ind_count} 个指标[/dim]"
                )

        except Exception as e:
            self.console.print(f"[yellow]DataSourceGuide 生成失败，降级为 LLM 生成: {e}[/yellow]")
            guide_content = None

        # 降级：使用 LLM 生成
        if guide_content is None:
            self.console.print("[dim]📝 使用 LLM 生成数据采集指南...[/dim]")
            from scholarpilot.context.prompts import DATA_COLLECTION_PROMPT, SCHOLAR_SYSTEM_PROMPT

            prompt = DATA_COLLECTION_PROMPT.format(
                spec_content=spec_content[:6000],  # 截取避免超长
                research_type=research_type,
            )

            try:
                guide_content = await self.llm.chat(
                    messages=[
                        {"role": "system", "content": SCHOLAR_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    model=self.config.default_writing_model,
                    temperature=0.3,
                )
            except Exception as e:
                self.console.print(f"[red]数据采集指南生成失败: {e}[/red]")
                guide_content = "# 数据采集指南\n\n（生成失败，请参考 SPEC.json 中的变量定义手动采集数据）"

        # 保存指南
        guide_path = self.project_dir / "data_collection_guide.md"
        guide_path.write_text(guide_content, encoding="utf-8")
        self.console.print(f"  [green]数据采集指南已保存: {guide_path}[/green]")

        # 修改9: 将 RAG 推荐结果注入 memory，供后续章节撰写时 LLM 引用
        if rag_recommendations and rag_recommendations.get("rag_active"):
            # 存储到 self.memory 供后续章节撰写使用
            rag_context_parts: list[str] = []
            rag_context_parts.append("## RAG 推荐数据库（来自机构知识库）")
            for db in rag_recommendations.get("databases", [])[:8]:
                name = db.get("name", "N/A")
                platform = db.get("platform", "N/A")
                access = db.get("access_method", db.get("access", "N/A"))
                desc = db.get("description", "")[:60] if db.get("description") else ""
                rag_context_parts.append(f"- {name}（{platform}）: {desc} | 访问: {access}")

            if rag_recommendations.get("indicators"):
                rag_context_parts.append("\n## RAG 搜索指标")
                for ind in rag_recommendations.get("indicators", [])[:10]:
                    ind_name = ind.get("indicator", "N/A")
                    ind_db = ind.get("database", "N/A")
                    ind_path = ind.get("full_path", "N/A")[:50]
                    rag_context_parts.append(f"- {ind_name} @ {ind_db}: {ind_path}")

            rag_context = "\n".join(rag_context_parts)

            # 存储到 ProjectMemory（使用 .add() 方法）
            self.memory.add("rag_recommendations", rag_recommendations)
            self.memory.add("rag_context", rag_context)

            logger.info("RAG 推荐结果已注入 memory，可供章节撰写使用")
            self.console.print("  [dim]RAG 推荐结果已注入论文上下文[/dim]")

        # 2. 生成 CSV 模板（基本列：year, region + 从 SPEC 提取变量名）
        from scholarpilot.tools.data_collector import generate_csv_template

        # 尝试从 SPEC.json 提取变量名
        variables = []
        try:
            spec_json = json.loads(spec_content) if spec_content.startswith("{") else {}
            method = spec_json.get("methodology", {})
            var_construction = method.get("variable_construction", {})
            for key in ["dependent_variable", "core_independent_variable", "control_variables", "mediator_variables"]:
                val = var_construction.get(key, "")
                if val:
                    variables.append({"name": key.replace("_variable", "").replace("core_independent", "x_core"), "description": val})
        except Exception:
            pass

        # 如果无法提取变量，使用默认模板
        if not variables:
            variables = [
                {"name": "y_debt_risk", "description": "被解释变量"},
                {"name": "x_core", "description": "核心解释变量"},
                {"name": "ctrl1", "description": "控制变量1"},
                {"name": "ctrl2", "description": "控制变量2"},
            ]

        csv_path = self.project_dir / "data_template.csv"
        generate_csv_template(variables, csv_path)
        self.console.print(f"  [green]CSV 数据模板已保存: {csv_path}[/green]")

        # 3. 暂停，等待用户选择
        self.console.print(
            "\n[bold]请选择：[/bold]\n"
            "  [cyan]1[/cyan]. 我已将数据填入 data_template.csv，继续生成\n"
            "  [cyan]2[/cyan]. 我暂无数据，跳过（后续可将数据放入 data/ 文件夹后重新运行）\n"
            "  [cyan]3[/cyan]. 查看数据采集指南内容"
        )

        # 非交互模式：使用默认选择
        if self.non_interactive:
            choice = self.default_choices.get("data_collection", 2)
            self.console.print(f"  [dim][非交互模式] 自动选择: {choice}[/dim]")
        else:
            from rich.prompt import IntPrompt

            while True:
                choice = IntPrompt.ask("请输入选项", default=2, choices=["1", "2", "3"])
                if choice == 3:
                    # 显示指南前50行
                    self.console.print("\n[dim]--- 数据采集指南（前50行）---[/dim]")
                    for line in guide_content.split("\n")[:50]:
                        self.console.print(line)
                    self.console.print("[dim]--- 完整指南请查看 data_collection_guide.md ---\n[/dim]")
                    continue
                break

        if choice == 1:
            # 用户提供了数据
            data_file = self.project_dir / "data_template.csv"
            if not data_file.exists():
                self.console.print("[red]data_template.csv 不存在，请确认文件位置[/red]")
                return False

            try:
                from scholarpilot.tools.data_collector import (
                    load_user_data,
                    calculate_descriptive_stats,
                    save_stats_to_json,
                )

                self.console.print("[dim]📊 正在计算描述性统计...[/dim]")
                df = load_user_data(data_file)
                stats = calculate_descriptive_stats(df)

                stats_path = self.project_dir / ".scholar" / "descriptive_stats.json"
                save_stats_to_json(stats, stats_path, str(data_file))
                self.console.print(f"  [green]描述性统计已保存（{len(stats)} 个变量）[/green]")

                # 更新项目状态
                self.file_manager.update_data_status(self.project_dir, "provided", str(data_file))
                self.console.print("  [green]数据状态已更新: provided[/green]")
                return True

            except Exception as e:
                self.console.print(f"[red]数据处理失败: {e}[/red]")
                self.console.print("[yellow]将使用占位符模式继续[/yellow]")
                self.file_manager.update_data_status(self.project_dir, "pending")
                return False
        else:
            # 用户跳过
            self.file_manager.update_data_status(self.project_dir, "pending")

            # 保存项目状态（记录已完成阶段）
            state = self.file_manager.load_project_state(self.project_dir) or {}
            state["research_type"] = research_type
            state["phases_completed"] = ["phase1", "phase2", "phase3", "phase4", "phase5", "phase6", "phase6.5"]
            self.file_manager.save_project_state(self.project_dir, state)

            return False

    async def _check_pending_data(self) -> bool:
        """检测是否有待补交的数据文件.

        扫描 data/ 目录，发现数据文件则提示用户是否重新生成实证章节。

        Returns:
            True 如果处理了数据补交，False 如果用户选择跳过。
        """
        data_dir = self.project_dir / "data"
        data_files = []
        if data_dir.exists():
            data_files = [
                f for f in data_dir.iterdir()
                if f.is_file() and f.suffix.lower() in (".csv", ".xlsx", ".xls")
                and f.name != "data_template.csv"
            ]

        # 也检查根目录的 data_template.csv（用户可能直接填入模板）
        template = self.project_dir / "data_template.csv"
        if template.exists():
            # 检查模板是否有实际数据（超过2行表头+示例）
            try:
                import csv as csv_mod
                with template.open(encoding="utf-8-sig") as f:
                    rows = list(csv_mod.reader(f))
                if len(rows) > 4:  # 表头+2示例行+至少1行实际数据
                    data_files.append(template)
            except Exception:
                pass

        self.console.print(
            Panel(
                "[bold yellow]检测到该项目实证数据尚未提供[/bold yellow]\n"
                f"项目状态: data_status=pending",
                title="数据补交检测",
            )
        )

        if data_files:
            self.console.print(f"\n[green]检测到数据文件: {data_files[0].name}[/green]")
            self.console.print(f"  路径: {data_files[0]}")

            if self.non_interactive:
                self.console.print("  [dim][非交互模式] 自动跳过数据补交[/dim]")
                return False
            from rich.prompt import Confirm
            if Confirm.ask("是否基于该数据重新生成实证章节？", default=True):
                await self._regenerate_empirical_sections(data_files[0])
                return True
            else:
                self.console.print("[dim]跳过数据补交，继续查看当前草稿[/dim]")
                return False
        else:
            self.console.print(
                "\n[dim]未检测到数据文件。后续操作：[/dim]\n"
                "  1. 按照 data_collection_guide.md 采集数据\n"
                "  2. 将数据保存为 CSV/Excel 放入 data/ 文件夹\n"
                "  3. 重新运行项目，系统会自动检测并提示\n"
            )
            if self.non_interactive:
                self.console.print("  [dim][非交互模式] 自动继续[/dim]")
                return False
            from rich.prompt import Confirm
            if Confirm.ask("是否继续查看当前草稿？", default=True):
                return False
            return False

    async def _regenerate_empirical_sections(self, data_file: Path) -> None:
        """基于用户提交的数据，重新生成实证章节.

        Args:
            data_file: 用户数据文件路径。
        """
        self.console.print("\n[bold cyan]━━━ 重新生成实证章节 ━━━[/bold cyan]")

        # 1. 计算描述性统计
        from scholarpilot.tools.data_collector import (
            load_user_data,
            calculate_descriptive_stats,
            save_stats_to_json,
            format_stats_for_prompt,
            is_empirical_section,
        )

        self.console.print("[dim]📊 正在计算描述性统计...[/dim]")
        try:
            df = load_user_data(data_file)
            stats = calculate_descriptive_stats(df)
        except Exception as e:
            self.console.print(f"[red]数据加载失败: {e}[/red]")
            return

        stats_path = self.project_dir / ".scholar" / "descriptive_stats.json"
        save_stats_to_json(stats, stats_path, str(data_file))
        self.console.print(f"  [green]描述性统计已保存（{len(stats)} 个变量）[/green]")

        # 更新状态
        self.file_manager.update_data_status(self.project_dir, "provided", str(data_file))

        # 2. 读取大纲，识别实证章节
        outline_path = self.project_dir / "outline.json"
        if not outline_path.exists():
            self.console.print("[red]outline.json 不存在，无法识别实证章节[/red]")
            return

        outline = json.loads(outline_path.read_text(encoding="utf-8"))
        sections = outline.get("sections", [])
        paper_title = outline.get("title", "论文")

        # 3. 逐个重新生成实证章节
        empirical_sections = [s for s in sections if is_empirical_section(s.get("title", ""))]

        if not empirical_sections:
            self.console.print("[yellow]未识别到实证章节，无需重新生成[/yellow]")
            return

        self.console.print(f"[dim]识别到 {len(empirical_sections)} 个实证章节需要重新生成[/dim]")

        # 读取现有草稿
        draft_path = self.project_dir / "draft" / "full_draft.md"
        full_text = draft_path.read_text(encoding="utf-8") if draft_path.exists() else ""

        # 准备实证数据文本
        empirical_data_text = format_stats_for_prompt(stats)

        outline_md_path = self.project_dir / "outline.md"
        outline_text = outline_md_path.read_text(encoding="utf-8") if outline_md_path.exists() else ""

        for i, section in enumerate(sections):
            sec_title = section.get("title", f"第{i+1}章")
            if not is_empirical_section(sec_title):
                continue

            word_count = section.get("word_count", 3000)
            key_points = section.get("key_points", [])
            subsections = section.get("subsections", [])

            self.console.print(f"  [dim]重新生成: {sec_title}...[/dim]")

            research_type = self.topic_info.get("research_type", "empirical")
            ctx = self.context_engine.build_section_writing_context(
                paper_title=paper_title,
                target_journal="CSSCI核心期刊",
                language="中文",
                outline="",  # 不注入完整大纲
                section_title=sec_title,
                word_count=word_count,
                subsections=subsections,
                key_points=key_points,
                research_type=research_type,
                relevant_papers="（基于用户提交的真实数据重新生成）",
                previous_sections="（前序章节不变）",
                empirical_data=empirical_data_text,
                discipline=self.discipline,
                history=[],  # 不传历史，避免 prompt 膨胀
            )

            try:
                response = await self.llm.chat(
                    messages=ctx.to_messages(),
                    model=self.config.default_writing_model,
                    temperature=0.5,
                )

                # 保存章节
                chapter_path = self.project_dir / "draft" / f"chapter{i+1:02d}.md"
                chapter_path.write_text(f"# {sec_title}\n\n{response}", encoding="utf-8")
                self.console.print(f"  [green]已更新: chapter{i+1:02d}.md[/green]")

                # 替换 full_draft.md 中的对应章节
                old_header = f"# {sec_title}"
                new_content = f"# {sec_title}\n\n{response}"
                if old_header in full_text:
                    # 找到下一个 "# " 开头的章节，替换之间的内容
                    idx = full_text.index(old_header)
                    next_idx = full_text.find("\n# ", idx + 1)
                    if next_idx == -1:
                        next_idx = full_text.find("\n---", idx + 1)
                    if next_idx == -1:
                        full_text = full_text[:idx] + new_content
                    else:
                        full_text = full_text[:idx] + new_content + full_text[next_idx:]

            except Exception as e:
                self.console.print(f"  [red]章节 {sec_title} 重新生成失败: {e}[/red]")

        # 保存更新后的草稿
        draft_path.write_text(full_text, encoding="utf-8")
        self.console.print(f"  [green]草稿已更新: {draft_path}[/green]")

        # 重新触发引用提取+格式化
        self.console.print("[dim]📖 正在重新提取引用...[/dim]")
        await self._phase7b_citation_management()

        self.console.print(
            Panel(
                "[green]实证章节已基于真实数据重新生成！[/green]\n\n"
                f"项目目录: {self.project_dir}\n"
                f"草稿目录: {self.project_dir / 'draft'}",
                title="数据补交完成",
            )
        )

    async def _phase7a_generate_abstract(self) -> None:
        """生成符合期刊格式的中英文摘要、关键词和分类号."""
        self.console.print("\n[bold cyan]━━━ Phase 7a: 摘要+关键词+分类号生成 ━━━[/bold cyan]")

        draft_path = self.project_dir / "draft" / "full_draft.md"
        if not draft_path.exists():
            self.console.print("[yellow]草稿文件不存在，跳过摘要生成[/yellow]")
            return

        full_text = draft_path.read_text(encoding="utf-8")

        # 截取正文前8000字用于摘要生成（避免超出context）
        content_for_abstract = full_text[:8000]

        # 获取论文标题和已有关键词
        outline_json = {}
        outline_path = self.project_dir / "outline.json"
        if outline_path.exists():
            try:
                outline_json = json.loads(outline_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        paper_title = outline_json.get("title", "论文")
        existing_keywords = ", ".join(outline_json.get("keywords", []))

        # 构建摘要生成prompt
        from scholarpilot.context.prompts import ABSTRACT_GENERATION_PROMPT, SCHOLAR_SYSTEM_PROMPT

        prompt = ABSTRACT_GENERATION_PROMPT.format(
            paper_title=paper_title,
            paper_content=content_for_abstract,
            existing_keywords=existing_keywords,
        )

        self.console.print("[dim]💭 正在生成中英文摘要...[/dim]")
        self._emit("section_writing", "progress", "正在生成中英文摘要...")
        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": SCHOLAR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=self.config.default_writing_model,
                temperature=0.3,  # 低温度确保格式准确
            )

            # 保存摘要
            abstract_path = self.project_dir / "draft" / "abstract.md"
            abstract_path.write_text(response, encoding="utf-8")
            self.console.print(f"  [green]摘要已保存: {abstract_path}[/green]")

            # 将摘要插入到完整草稿的最前面
            updated_draft = f"# {paper_title}\n\n{response}\n\n---\n\n{full_text}"
            draft_path.write_text(updated_draft, encoding="utf-8")
            self.console.print(f"  [green]摘要已插入到草稿顶部[/green]")

            self.memory.add("abstract", {"path": str(abstract_path), "length": len(response)})
            self._emit("section_writing", "progress", "中英文摘要生成完成")

        except Exception as e:
            self.console.print(f"  [red]摘要生成失败: {e}[/red]")
            logger.error(f"Abstract generation failed: {e}", exc_info=True)

    async def _phase7b_citation_management(self) -> None:
        """引用管理：提取正文引用→API验证→格式化参考文献→附加AI声明."""
        self.console.print("\n[bold cyan]━━━ Phase 7b: 引用管理 ━━━[/bold cyan]")
        self._emit("section_writing", "progress", "正在管理引用: 提取→验证→格式化...")

        draft_path = self.project_dir / "draft" / "full_draft.md"
        if not draft_path.exists():
            self.console.print("[yellow]草稿文件不存在，跳过引用管理[/yellow]")
            return

        full_text = draft_path.read_text(encoding="utf-8")

        # 0a. 移除 LLM 自行生成的"参考文献"章节（含虚假引用列表）
        # LLM 常在正文中编造一个"参考文献"章节，其中包含大量虚假引用
        # （如同一作者十几篇论文），必须移除后由系统重新生成
        from scholarpilot.tools.citation_manager import strip_llm_reference_section
        original_len = len(full_text)
        full_text = strip_llm_reference_section(full_text)
        stripped_len = original_len - len(full_text)
        if stripped_len > 0:
            self.console.print(
                f"  [yellow]🗑️ 移除 LLM 生成的参考文献章节（{stripped_len} 字符）[/yellow]"
            )
            # 保存移除参考文献后的文本
            draft_path.write_text(full_text, encoding="utf-8")

        # 0. 先构建文献池（用于哈希ID清洗和正向引用构建）
        topic_info = self.topic_info or {}
        topic_keywords = " ".join(filter(None, [
            topic_info.get("core_topic", ""),
            topic_info.get("region", ""),
            topic_info.get("content", ""),
        ]))
        # 从主题中提取核心关键词（取前几个词）
        import re as _re
        kw_parts = _re.findall(r'[\u4e00-\u9fff]{2,6}|[a-zA-Z]{3,}', topic_keywords)
        topic_keywords = " ".join(kw_parts[:6]) if kw_parts else ""

        # 构建 Phase 2 文献池（从全局文献库中获取）
        literature_pool: list[dict] = []
        try:
            # 优先获取当前项目的文献（Phase 2 检索结果）
            project_papers = self.library.get_project_papers(self.project_name)
            if project_papers:
                literature_pool = project_papers
                self.console.print(f"  [dim]文献池: {len(literature_pool)} 篇当前项目文献可供匹配[/dim]")
            else:
                # 回退到全局文献库（其他项目的文献也可能有用）
                all_papers_dict = self.library.search(keyword="", limit=500)
                literature_pool = all_papers_dict
                self.console.print(f"  [dim]文献池: {len(literature_pool)} 篇全局文献库文献可供匹配[/dim]")
        except Exception as e:
            logger.debug(f"无法获取文献池: {e}")

        # 修改5: 哈希ID清洗（在提取引用之前执行）
        if literature_pool:
            self.console.print("[dim]🔧 正在清洗正文中的哈希ID...[/dim]")
            self._emit("section_writing", "progress", "引用管理: 清洗正文哈希ID...")
            full_text = self._replace_hash_ids(full_text, literature_pool)
            # 修改6: 替换正文中的虚假作者名 + 清除异常引用标记
            from scholarpilot.tools.citation_manager import replace_fake_authors_in_text
            full_text = replace_fake_authors_in_text(
                full_text, literature_pool, topic_keywords
            )
            # 保存清洗后的文本
            draft_path.write_text(full_text, encoding="utf-8")

        # 1. 提取引用
        self.console.print("[dim]📖 正在提取正文中的引用...[/dim]")
        self._emit("section_writing", "progress", "引用管理: 提取正文引用...")
        from scholarpilot.tools.citation_manager import (
            extract_citations_from_text,
            build_citations_from_pool,
            verify_all_citations,
            format_references_list,
            generate_ai_disclosure,
            detect_classic_methodology_citations,
        )

        citations = extract_citations_from_text(full_text)

        # 检测并补充经典方法论文献（如 Rogers, Kaplan, Baron 等）
        # 这些文献常被 LLM 引用但不在 Phase 2 文献池中
        classic_citations = detect_classic_methodology_citations(
            full_text, existing_citations=citations
        )
        if classic_citations:
            self.console.print(
                f"  [green]📚 经典方法论文献补充: {len(classic_citations)} 篇"
                f"（Rogers/Kaplan/Baron 等）[/green]"
            )
            citations.extend(classic_citations)

        # 修改6: 从文献池正向构建引用（以真实文献为主，文本提取为补充）
        pool_citations: list = []
        if literature_pool:
            self.console.print("[dim]📖 正在从文献池正向构建引用...[/dim]")
            pool_citations = build_citations_from_pool(
                literature_pool, full_text,
                existing_citations=citations,
                topic_keywords=topic_keywords,
            )
            if pool_citations:
                self.console.print(
                    f"  [green]文献池正向匹配到 {len(pool_citations)} 条已验证引用[/green]"
                )

        # 合并：文献池正向构建的引用（已验证）+ 文本提取的引用（需验证）
        # 文献池引用优先，文本提取引用中与文献池重复的跳过
        if pool_citations:
            pool_keys = set()
            for pc in pool_citations:
                if pc.authors:
                    pool_keys.add(f"{pc.authors[0].lower()}_{pc.year}")
            # 过滤掉与文献池重复的文本提取引用
            unique_text_citations = [
                c for c in citations
                if not (c.authors and f"{c.authors[0].lower()}_{c.year}" in pool_keys)
            ]
            citations = pool_citations + unique_text_citations

        if not citations:
            self.console.print("[yellow]未在正文中提取到任何引用[/yellow]")
            return

        zh_count = sum(1 for c in citations if c.language == "zh")
        en_count = sum(1 for c in citations if c.language != "zh")
        self.console.print(
            f"  [green]提取到 {len(citations)} 条引用"
            f"（中文 {zh_count}，英文 {en_count}）[/green]"
        )

        # 3. 验证引用
        self.console.print("[dim]🔍 正在验证引用真实性（文献池 + CNKI + OpenAlex + Semantic Scholar）...[/dim]")
        self._emit("section_writing", "progress",
            f"引用管理: 正在验证 {len(citations)} 条引用（CNKI + OpenAlex + Semantic Scholar）...")
        try:
            from scholarpilot.mcp.servers.cnki.aiohttp_engine import CNKIAiohttpEngine
            cnki_engine = CNKIAiohttpEngine()
        except Exception:
            cnki_engine = None
            self.console.print("[dim]  CNKI 引擎初始化失败，跳过中文引用验证[/dim]")

        openalex_engine = None
        try:
            from scholarpilot.mcp.servers.openalex import OpenAlexEngine
            openalex_engine = OpenAlexEngine()
        except Exception:
            self.console.print("[dim]  OpenAlex 引擎初始化失败，跳过英文引用验证[/dim]")

        # Semantic Scholar 引擎（英文验证兜底，原生支持作者名搜索）
        ss_engine = getattr(self, 'ss_engine', None)
        if ss_engine is None:
            try:
                from scholarpilot.mcp.servers.semantic_scholar import SemanticScholarEngine
                ss_engine = SemanticScholarEngine(api_key=self.settings.ss_api_key or None)
                self.ss_engine = ss_engine
            except Exception:
                ss_engine = None
                self.console.print("[dim]  Semantic Scholar 引擎初始化失败，英文验证可能不完整[/dim]")

        verified_citations = await verify_all_citations(
            citations,
            cnki_engine=cnki_engine,
            openalex_engine=openalex_engine,
            ss_engine=ss_engine,
            concurrency=3,
            topic_keywords=topic_keywords,
            literature_pool=literature_pool,
        )

        # 动态补充验证：对未验证的英文引用进行最后兜底
        # 仅用作者名+年份搜索（不加主题词），适用于经典方法论文献
        unverified_en = [
            c for c in verified_citations
            if not c.verified and c.language == "en" and c.authors
        ]
        if unverified_en and (openalex_engine or ss_engine):
            self.console.print(
                f"  [dim]🔍 动态补充验证: {len(unverified_en)} 条未验证英文引用[/dim]"
            )
            from scholarpilot.tools.citation_manager import supplement_unverified_english_citations
            verified_citations = await supplement_unverified_english_citations(
                verified_citations,
                openalex_engine=openalex_engine,
                ss_engine=ss_engine,
            )
            new_verified = sum(1 for c in verified_citations if c.verified)
            supplemented = new_verified - verified_count if 'verified_count' in dir() else 0

        # 关闭引擎
        if cnki_engine:
            try:
                await cnki_engine.close()
            except Exception:
                pass
        if openalex_engine:
            try:
                await openalex_engine.close()
            except Exception:
                pass

        verified_count = sum(1 for c in verified_citations if c.verified)
        unverified_count = len(verified_citations) - verified_count
        self.console.print(
            f"  [green]验证完成: {verified_count} 条已验证, "
            f"{unverified_count} 条未验证[/green]"
        )
        self._emit("section_writing", "progress",
            f"引用验证完成: {verified_count} 条已验证, {unverified_count} 条未验证")

        # 最终语义过滤：使用嵌入语义相似度移除主题不相关引用
        # 第三代方案：智谱 embedding-3 语义向量余弦相似度
        # 降级策略：API不可用时自动回退到TRSS关键词匹配
        from scholarpilot.tools.citation_manager import get_semantic_filter
        sf = get_semantic_filter()
        # 语义过滤使用完整主题描述（而非截取的关键词），提高嵌入精度
        semantic_topic = " ".join(filter(None, [
            topic_info.get("core_topic", ""),
            topic_info.get("region", ""),
            topic_info.get("content", ""),
        ])) or topic_keywords
        pre_filter_count = len(verified_citations)
        kept_citations, filtered_citations, filter_method = await sf.filter_papers(
            verified_citations, semantic_topic,
            threshold=sf.FINAL_THRESHOLD,
        )
        blocked_count = pre_filter_count - len(kept_citations)
        if blocked_count > 0:
            method_label = "语义嵌入" if filter_method == "semantic" else "TRSS降级"
            self.console.print(
                f"  [yellow]🚫 {method_label}过滤: 移除 {blocked_count} 条主题不相关引用[/yellow]"
            )
            logger.info(
                "%s最终过滤: 移除 %d 条主题不相关引用 (阈值=%.2f)",
                method_label, blocked_count, sf.FINAL_THRESHOLD,
            )
        verified_citations = kept_citations

        # Cross-Encoder 精排：对 Bi-Encoder 保留的引用进行精确重排序
        # 两阶段架构第二阶段：Bi-Encoder 初筛 → Cross-Encoder 精排
        # 最终阶段只重排序（不影响引用数量），移除由 Bi-Encoder 负责
        if len(verified_citations) > 5:
            try:
                from scholarpilot.tools.citation_manager import get_cross_encoder_reranker
                reranker = get_cross_encoder_reranker()
                reranked_cits, dropped_cits, rmethod = await reranker.rerank(
                    verified_citations, semantic_topic, drop_bottom=False,
                )
                if rmethod != "skipped":
                    rmethod_label = "BGE本地" if rmethod == "local_bge" else "LLM"
                    self.console.print(
                        f"  [cyan]🎯 {rmethod_label}精排: 引用已按相关性重排序[/cyan]"
                    )
                    verified_citations = reranked_cits
            except Exception as re:
                logger.warning(f"Cross-Encoder精排异常(非致命): {re}")

        # 2.5 作者频率限制：同一第一作者最多保留3篇论文
        # 防止 LLM 编造同一作者的大量论文充斥参考文献列表
        from scholarpilot.tools.citation_manager import cap_author_frequency
        pre_cap_count = len(verified_citations)
        verified_citations = cap_author_frequency(verified_citations, max_per_author=3)
        capped_count = pre_cap_count - len(verified_citations)
        if capped_count > 0:
            self.console.print(
                f"  [yellow]⚖️ 作者频率限制: 移除 {capped_count} 条超限引用"
                f"（同一作者上限3篇）[/yellow]"
            )

        # 3. 格式化参考文献列表
        self.console.print("[dim]📋 正在生成参考文献列表（CSSCI 格式）...[/dim]")
        ref_list = format_references_list(
            verified_citations,
            style="cssci",
            language_separate=True,
        )

        # 4. 生成AI声明
        ai_disclosure = generate_ai_disclosure(language="zh")

        # 5. 保存参考文献列表
        ref_path = self.project_dir / "draft" / "references.md"
        ref_path.write_text(ref_list, encoding="utf-8")
        self.console.print(f"  [green]参考文献列表已保存: {ref_path}[/green]")

        # 修改5: 正文引用←→参考文献列表交叉校验
        try:
            import re as _re_xcheck
            # 从参考文献列表提取所有作者名
            ref_authors: set[str] = set()
            for c in verified_citations:
                if c.authors:
                    for a in c.authors:
                        # 中文作者取全名，英文作者取姓氏
                        if _re_xcheck.search(r'[\u4e00-\u9fff]', a):
                            ref_authors.add(a.strip())
                        else:
                            # 英文作者取姓氏（最后一个单词）
                            surname = a.split()[-1] if a.split() else a
                            ref_authors.add(surname.lower().strip())

            # 从正文提取所有内联引用作者名
            in_text_pattern = _re_xcheck.compile(
                r'([\u4e00-\u9fff]{2,4}(?:[和与][\u4e00-\u9fff]{2,4})*(?:等)?)\s*[（(]\s*((?:19|20)\d{2})\s*[）)]'
            )
            in_text_authors: set[str] = set()
            for m in in_text_pattern.finditer(full_text):
                author = m.group(1).replace('等', '').strip()
                for part in _re_xcheck.split(r'[和与]', author):
                    part = part.strip()
                    if part:
                        in_text_authors.add(part)

            # 英文作者引用
            en_pattern = _re_xcheck.compile(
                r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)*(?:\s+et\s+al\.?)?)\s*[（(]\s*((?:19|20)\d{2})\s*[）)]'
            )
            for m in en_pattern.finditer(full_text):
                author = m.group(1).strip()
                surname = author.split()[-1] if author.split() else author
                in_text_authors.add(surname.lower().strip())

            # 找出正文中有但参考文献列表中无的作者
            missing_authors = in_text_authors - ref_authors
            # 过滤掉假名
            from scholarpilot.tools.citation_manager import _is_valid_zh_author, _FAKE_NAME_PATTERNS
            real_missing = set()
            for a in missing_authors:
                if a in _FAKE_NAME_PATTERNS:
                    continue
                if _re_xcheck.search(r'[\u4e00-\u9fff]', a):
                    if _is_valid_zh_author(a, set()):
                        real_missing.add(a)
                else:
                    real_missing.add(a)

            if real_missing:
                logger.warning(
                    "交叉校验: %d 个正文引用作者不在参考文献列表中: %s",
                    len(real_missing), list(real_missing)[:5],
                )
                self.console.print(
                    f"  [yellow]⚠️ 交叉校验: {len(real_missing)} 个正文引用作者不在参考文献列表中[/yellow]"
                )
            else:
                self.console.print("  [green]✓ 交叉校验通过: 正文引用与参考文献列表一致[/green]")
        except Exception as e:
            logger.debug("交叉校验失败: %s", e)

        # 5b. 保存 BibTeX 文件
        bib_lines = ["% BibTeX references (auto-generated by ScholarPilot)"]
        bib_count = 0
        for i, c in enumerate(verified_citations, 1):
            if not c.verified and not c.title:
                continue
            bib_key = f"ref{i}"
            if c.authors:
                author_str = " and ".join(c.authors[:5])
            else:
                author_str = "Unknown"
            bib_lines.append("")
            bib_lines.append(f"@article{{{bib_key},")
            bib_lines.append(f"  author = {{{author_str}}},")
            if c.title:
                bib_lines.append(f"  title = {{{{{c.title}}}}},")
            if c.journal:
                bib_lines.append(f"  journal = {{{c.journal}}},")
            bib_lines.append(f"  year = {{{c.year}}},")
            if c.volume:
                bib_lines.append(f"  volume = {{{c.volume}}},")
            if c.issue:
                bib_lines.append(f"  number = {{{c.issue}}},")
            if c.pages:
                bib_lines.append(f"  pages = {{{c.pages}}},")
            if c.doi:
                bib_lines.append(f"  doi = {{{c.doi}}},")
            bib_lines.append("}")
            bib_count += 1
        bib_path = self.project_dir / "literature" / "references.bib"
        bib_path.write_text("\n".join(bib_lines), encoding="utf-8")
        self.console.print(f"  [green]BibTeX 已保存: {bib_path}（{bib_count} 条）[/green]")

        # 6. 追加到完整草稿
        updated_draft = full_text + "\n\n---\n\n" + ref_list + "\n\n---\n\n" + ai_disclosure
        draft_path.write_text(updated_draft, encoding="utf-8")
        self.console.print(f"  [green]参考文献列表和AI声明已合并到草稿[/green]")

        # 7. 显示未验证的引用
        if unverified_count > 0:
            self.console.print(f"\n[yellow]⚠️ {unverified_count} 条引用未验证，请手动核查：[/yellow]")
            for c in verified_citations:
                if not c.verified:
                    self.console.print(f"  - {c.raw}")

        self.memory.add("citation_management", {
            "total": len(verified_citations),
            "verified": verified_count,
            "unverified": unverified_count,
        })

    def _replace_hash_ids(self, text: str, literature_pool: list[dict]) -> str:
        """清洗正文中的哈希ID（12位十六进制字符串）.

        LLM 在撰写正文时会从文献摘要中看到 paper_id（如 da3f8aaa5218），
        并直接用作引用标识残留在正文中。此方法：
        1. 构建 paper_id → 作者+年份 的映射
        2. 将正文中的哈希ID替换为"作者（年份）"格式
        3. 未匹配到作者的残余哈希ID用正则清除引用语句片段

        Args:
            text: 论文正文文本.
            literature_pool: 文献池（dict 列表）.

        Returns:
            清洗后的文本.
        """
        import re as _re

        if not literature_pool or not text:
            return text

        # 构建 paper_id → 作者+年份 映射
        hash_map: dict[str, str] = {}
        for paper in literature_pool:
            if not isinstance(paper, dict):
                continue
            paper_id = paper.get("paper_id", "") or paper.get("id", "")
            if paper_id and len(str(paper_id)) >= 8:
                authors = paper.get("authors", [])
                year = str(paper.get("year", ""))
                if authors and year:
                    first_author = authors[0]
                    hash_map[str(paper_id)] = f"{first_author}（{year}）"

        if not hash_map:
            return text

        # 替换已映射的哈希ID
        replaced_count = 0
        for hash_id, replacement in hash_map.items():
            if hash_id in text:
                text = text.replace(hash_id, replacement)
                replaced_count += 1

        # 清除残余的12位十六进制哈希ID（未匹配到文献的）
        # 匹配独立的12位hex字符串（不包含在更长的hex字符串中）
        hash_pattern = _re.compile(r'(?<![0-9a-fA-F])[0-9a-f]{12}(?![0-9a-fA-F])')
        remaining = hash_pattern.findall(text)
        if remaining:
            # 将残余哈希ID替换为"（参考文献）"或直接删除
            text = hash_pattern.sub("（参考文献）", text)
            replaced_count += len(remaining)

        if replaced_count > 0:
            logger.info("_replace_hash_ids: 清洗了 %d 处哈希ID", replaced_count)
            self.console.print(f"  [dim]哈希ID清洗: 替换/清除 {replaced_count} 处[/dim]")

        return text

    def _merge_draft(self) -> None:
        """合并所有章节为完整草稿."""
        sections = self.file_manager.list_sections(self.project_dir)
        if not sections:
            return

        # 从 outline.json 获取实际论文标题
        paper_title = "论文草稿"
        outline_path = self.project_dir / "outline.json"
        if outline_path.exists():
            try:
                outline_json = json.loads(outline_path.read_text(encoding="utf-8"))
                title = outline_json.get("title", "")
                if title:
                    paper_title = title
            except Exception:
                pass

        merged = f"# {paper_title}\n\n"
        for section_name in sections:
            content = self.file_manager.load_section(self.project_dir, section_name)
            if content:
                merged += content + "\n\n---\n\n"

        # 保存合并的草稿
        draft_path = self.project_dir / "draft" / "full_draft.md"
        # 全局标点清洗（LLM 生成时可能引入异常标点组合）
        # 使用 while 循环反复清洗 ；。，因为 `；。。` 这类组合单次替换后会残留 `；。`
        # （单次 `；。\s*→；` 会把 `；。。` 变成 `；。`，而后续 `。。+→。` 又匹配不上单个 `。`）。
        import re as _re_merge
        _merge_sp_total = 0
        while True:
            merged, _n = _re_merge.subn(r"；。\s*", "；", merged)
            _merge_sp_total += _n
            if _n == 0:
                break
        merged = _re_merge.sub(r"。。+", "。", merged)      # 多个句号 → 单句号
        merged = _re_merge.sub(r"；；+", "；", merged)      # 多个分号 → 单分号
        merged = _re_merge.sub(r"，，+", "，", merged)      # 多个逗号 → 单逗号
        if _merge_sp_total > 0:
            logger.info("_merge_draft 标点清洗: 共清除 %d 处 ；。残留", _merge_sp_total)
        draft_path.write_text(merged, encoding="utf-8")
        self.console.print(f"\n[green]完整草稿已合并: {draft_path}[/green]")

    @staticmethod
    def _extract_sections_from_md(md: str) -> list[dict]:
        """从 Markdown 大纲提取章节信息.

        支持两种格式：
        - `## 第一章 标题`（二级标题）
        - `### 第一章 标题`（三级标题）

        过滤规则：排除非正文章节（如"大纲概览"、"详细大纲"等元信息标题）。
        只保留包含"第X章"或数字编号的正式章节标题。
        自动清洗思考过程标记，确保不受 LLM 输出前缀干扰。
        """
        # 先清洗思考过程标记
        from scholarpilot.llm.gateway import LLMGateway
        md = LLMGateway._clean_llm_output(md)

        # 非正文章节标题关键词（出现在标题中则跳过）
        NON_SECTION_KEYWORDS = [
            "大纲概览", "详细大纲", "概述", "目录", "章节结构",
            "合计", "总计", "参考文献", "致谢", "论文大纲",
        ]

        sections = []
        lines = md.split("\n")
        current_section: dict[str, Any] | None = None

        for line in lines:
            # 匹配 ## 或 ### 开头的标题（但不匹配 #### 或更深层级）
            is_h2 = line.startswith("## ") and not line.startswith("### ")
            is_h3 = line.startswith("### ") and not line.startswith("#### ")

            if is_h2 or is_h3:
                if current_section:
                    sections.append(current_section)
                title = line[3:].strip() if is_h2 else line[4:].strip()

                # 过滤非正文章节
                is_non_section = any(kw in title for kw in NON_SECTION_KEYWORDS)
                # 正文章节识别：支持"第X章"、"一、引言"、"1. 引言"等多种格式
                is_real_section = (
                    "第" in title
                    or "引言" in title
                    or "结论" in title
                    or "绪论" in title
                    or "导论" in title
                    or "文献综述" in title
                    or "研究设计" in title
                    or "实证" in title
                    or "模型" in title
                    or "分析" in title
                    or "检验" in title
                    or "稳健" in title
                    or "机制" in title
                    or "异质" in title
                    or "政策" in title
                    or "建议" in title
                    # 中文数字编号：一、二、三、四、五、六、七、八、九、十
                    or re.match(r"^[一二三四五六七八九十]+[、\.]", title) is not None
                    # 阿拉伯数字编号：1. 2. 3.
                    or re.match(r"^\d+[\.、]", title) is not None
                )

                if is_non_section or not is_real_section:
                    current_section = None
                    continue

                # 从标题中提取字数（如"一、引言（约1500字）" → 1500）
                wc_match = re.search(r"约?(\d{3,6})\s*字", title)
                word_count = int(wc_match.group(1)) if wc_match else 2000

                current_section = {
                    "title": title,
                    "word_count": word_count,
                    "subsections": [],
                    "key_points": [],
                }
            elif line.startswith("- ") and current_section:
                # 小节（- 1.1 研究背景...）或要点
                content = line[2:].strip()
                if content and not content.startswith("**"):
                    current_section["subsections"].append(content)

        if current_section:
            sections.append(current_section)

        return sections

    # ===== Human-in-the-Loop =====

    async def _human_review(self, phase: str, filename: str) -> bool:
        """人工审核节点.

        Args:
            phase: 当前阶段名称。
            filename: 要审核的文件名。

        Returns:
            用户是否确认。
        """
        file_path = self.project_dir / filename
        self.console.print(
            Panel(
                f"[bold]⏸️ 需要确认: {phase}[/bold]\n\n"
                f"文件已生成: {file_path}\n"
                f"请查看并审核以上内容。\n\n"
                f"[dim]你可以用任何编辑器打开此文件查看。[/dim]",
                border_style="yellow",
            )
        )

        # 显示文件内容摘要
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8")
            preview = content[:1000] + ("..." if len(content) > 1000 else "")
            self.console.print(Panel(preview, title=f"{filename} 预览", border_style="blue"))

        # 等待用户输入
        if self.non_interactive:
            self.console.print("  [dim][非交互模式] 自动确认[/dim]")
            return True

        choice = Prompt.ask(
            "\n请选择",
            choices=["confirm", "modify", "skip", "exit"],
            default="confirm",
        )

        if choice == "confirm":
            self.console.print("[green]✓ 已确认，继续下一步[/green]")
            return True
        elif choice == "modify":
            feedback = Prompt.ask("请输入修改意见")
            self.memory.add("user_feedback", {"phase": phase, "feedback": feedback})
            self.console.print(f"[yellow]已记录修改意见: {feedback}[/yellow]")
            # TODO: 基于反馈重新生成
            return True  # 暂时继续
        elif choice == "skip":
            self.console.print("[yellow]已跳过此步骤[/yellow]")
            return True
        else:
            return False

    async def _request_review(
        self,
        phase: str,
        title: str,
        filename: str = "",
        content_override: str = "",
    ) -> bool:
        """请求审核 — 三级审核架构.

        审核流程（优先级从高到低）：
        1. **自动校验**（Actor-Critic）：Critic 角色自动评估产出质量
           - score >= 80 且无 critical → 自动通过
           - score 50-79 → 记录问题后继续（fix 模式）
           - score < 50 → 升级到人工审核
        2. **人工审核**（桌面 UI）：通过 ReviewManager 暂停等待用户决策
        3. **CLI 审核**：回退到 _human_review 的 rich.prompt 交互

        Args:
            phase: 阶段标识，如 "policy_search"。
            title: 审核标题，如 "政策背景调研审核"。
            filename: 要审核的文件名（相对项目目录），为空则用 content_override。
            content_override: 直接传入审核内容（不读文件）。

        Returns:
            是否通过审核。
        """
        # 读取审核内容
        content = content_override
        if not content and filename:
            file_path = self.project_dir / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")

        # ── Tier 1: 自动校验（Actor-Critic）──
        if self.auto_verify:
            result = await self._run_auto_verification(phase, content)
            if result and result.passed:
                # 自动通过
                self.memory.add("verification_history", {
                    "phase": phase,
                    "score": result.score,
                    "decision": "pass",
                    "critic": result.critic_name,
                    "summary": result.summary,
                })
                return True
            elif result and result.decision == "fix":
                # 记录问题但继续
                self.memory.add("verification_history", {
                    "phase": phase,
                    "score": result.score,
                    "decision": "fix",
                    "critic": result.critic_name,
                    "summary": result.summary,
                    "issues": [i.description for i in result.issues],
                })
                self.console.print(
                    f"[yellow]⚠ 自动校验发现问题（{result.score}分），"
                    f"已记录但继续执行: {result.summary}[/yellow]"
                )
                return True
            # decision == "human" → 继续到人工审核
            self.console.print(
                f"[yellow]⚠ 自动校验未通过（{result.score if result else '?'}分），"
                f"升级人工审核[/yellow]"
            )

        # ── Tier 2: 人工审核（桌面 UI 模式）──
        # 桌面模式下 non_interactive=True（禁用 CLI 交互），
        # 但 review_manager 存在时仍走 UI 审核
        if (
            self.review_manager
            and self._loop
        ):
            review_id = self.review_manager.create_review_id(phase)
            # 关键：必须在 wait_for_review 之前调用 create_review 注册到 _pending，
            # 否则 wait_for_review 找不到该 ID 会立即返回默认 confirm，
            # 且前端 submit_review 也会因 ID 不存在而失败
            self.review_manager.create_review(review_id)
            logger.info(f"审核请求创建: phase={phase}, review_id={review_id}")

            # 发出审核请求事件到前端
            event = ReviewRequestEvent(
                review_id=review_id,
                phase=phase,
                title=title,
                content=content[:5000],  # 限制传输大小
                metadata={"filename": filename} if filename else {},
            )
            _cb = getattr(self, "_callback", None)
            if _cb:
                try:
                    _cb.on_review_request(event)
                    logger.info(f"审核请求已发送到前端: {review_id}")
                except Exception as e:
                    logger.error(f"on_review_request 回调失败: {e}")

            # 暂停等待用户响应
            logger.info(f"开始等待用户审核: {review_id}")
            response = await self.review_manager.wait_for_review(
                review_id, timeout=3600
            )
            logger.info(f"审核等待结束: {review_id}, decision={response.decision if response else 'None'}")
            self.review_manager.clear(review_id)

            if response is None:
                return True  # 异常情况，默认通过

            if response.decision == "confirm":
                self.memory.add("review_history", {
                    "phase": phase,
                    "decision": "confirm",
                    "timestamp": response.timestamp,
                })
                self._emit(phase, "progress", f"用户已确认: {title}")
                return True
            elif response.decision == "modify":
                self.memory.add("user_feedback", {
                    "phase": phase,
                    "feedback": response.feedback,
                })
                self.console.print(
                    f"[yellow]用户修改意见: {response.feedback}[/yellow]"
                )
                # TODO: 基于反馈重新生成（P1 实现）
                return True
            elif response.decision == "reject":
                self.console.print(f"[yellow]用户驳回: {title}[/yellow]")
                return False
            return True

        # ── Tier 3: CLI 模式或非交互模式 ──
        if self.non_interactive:
            self.console.print(f"  [dim][非交互模式] 自动确认: {title}[/dim]")
            return True
        if not filename:
            return True  # 无文件可审核，直接通过
        return await self._human_review(title, filename)

    async def _run_auto_verification(
        self, phase: str, content: str
    ) -> Any:
        """执行自动校验（Actor-Critic 模式）.

        Args:
            phase: 阶段标识。
            content: 待校验内容。

        Returns:
            VerificationResult 或 None（校验不可用时）。
        """
        if not content:
            return None

        # 延迟初始化 AutoVerifier
        if self._auto_verifier is None:
            try:
                from scholarpilot.workflow.auto_verifier import AutoVerifier

                self._auto_verifier = AutoVerifier(
                    llm=self.llm,
                    callback=self._callback,
                )
            except ImportError as e:
                logger.warning(f"AutoVerifier 不可用: {e}")
                return None

        discipline = getattr(self, "discipline", "学术研究")

        try:
            result = await self._auto_verifier.verify(
                phase=phase,
                content=content,
                user_input=self._last_user_input,
                discipline=discipline,
            )
            return result
        except Exception as e:
            logger.error(f"自动校验异常 [{phase}]: {e}")
            return None

    def _format_topic_review(self) -> str:
        """格式化选题分析结果供审核展示."""
        if not self.topic_info:
            return "选题分析结果为空"
        lines = [
            f"## 选题分析结果\n",
            f"- **核心主题**: {self.topic_info.get('topic', '未提取')}",
            f"- **区域/对象**: {self.topic_info.get('region', '未提取')}",
            f"- **研究内容**: {self.topic_info.get('content', '未提取')}",
            f"- **研究类型**: {self.topic_info.get('research_type', '未提取')}",
            f"- **学科领域**: {self.topic_info.get('discipline', '未提取')}",
            f"- **时间范围**: {self.topic_info.get('year_start', '?')}-{self.topic_info.get('year_end', '?')}",
        ]
        reason = self.topic_info.get("research_type_reason", "")
        if reason:
            lines.append(f"- **类型判定理由**: {reason}")
        analysis = self.topic_info.get("analysis", "")
        if analysis:
            lines.append(f"\n### 初步分析\n{analysis}")
        return "\n".join(lines)

    def _format_literature_review(self) -> str:
        """格式化文献检索结果供审核展示."""
        lines = ["## 文献检索结果\n"]
        cnki_count = len(self.chinese_results)
        ss_count = len(self.ss_results)
        arxiv_count = len(self.arxiv_results)
        openalex_count = len(self.openalex_results)
        total = cnki_count + ss_count + arxiv_count + openalex_count
        lines.append(f"- **中文文献**: {cnki_count} 篇")
        lines.append(f"- **Semantic Scholar**: {ss_count} 篇")
        lines.append(f"- **arXiv**: {arxiv_count} 篇")
        lines.append(f"- **OpenAlex**: {openalex_count} 篇")
        lines.append(f"- **总计**: {total} 篇\n")

        if self.eight_dim_stats:
            lines.append("### 8维统计分析")
            lines.append(f"- 竞争程度: {self.eight_dim_stats.get('competition_level', '未知')}")
            lines.append(f"- 核心刊占比: {self.eight_dim_stats.get('core_journal_ratio', '未知')}")
            yr = self.eight_dim_stats.get('year_trend', {})
            lines.append(f"- 年度趋势: {yr.get('trend', '未知')}")
            lines.append("")

        if self.feasibility:
            lines.append("### 可行性判定")
            lines.append(f"- 判定: {self.feasibility.get('verdict', '未知')}")
            lines.append(f"- 置信度: {self.feasibility.get('confidence', '未知')}")
            lines.append(f"- 建议: {self.feasibility.get('recommendation', '未知')}")

        # 列出前5篇高相关文献
        lines.append("\n### 高相关文献（前5篇）")
        all_papers = list(self.chinese_results[:3]) + list(self.ss_results[:2])
        for i, p in enumerate(all_papers[:5], 1):
            title = getattr(p, 'title', '') or ''
            authors = getattr(p, 'authors', '') or ''
            year = getattr(p, 'year', '') or ''
            lines.append(f"{i}. {title} ({authors}, {year})")

        return "\n".join(lines)

    async def _phase0_5_policy_search(self, user_input: str) -> None:
        """Phase 0.5: 政策/制度背景调研.

        从 VPN 政策数据库检索相关政策法规，提炼社会问题，
        为选题分析提供现实背景支撑。

        产出: policy_research.md
        """
        self.console.print("\n[bold cyan]━━━ Phase 0.5: 政策背景调研 ━━━[/bold cyan]")

        # 1. 从用户输入提取政策关键词
        self._emit("policy_search", "progress", "正在提取政策关键词...")
        keywords = await self._extract_policy_keywords(user_input)
        self.console.print(f"  政策搜索关键词: {keywords}")
        self._emit("policy_search", "progress", f"政策关键词: {', '.join(keywords[:5])}")

        # 2. 搜索政策数据库
        self._emit("policy_search", "progress", "正在搜索政策数据库（中国经济信息网/国研网/北大法宝）...")
        results: list[dict] = []
        try:
            from scholarpilot.skills.policy_search import PolicySearchEngine
            from scholarpilot.tools.database_rag import DatabaseRAG

            rag = DatabaseRAG()
            engine = PolicySearchEngine(rag)
            results = await engine.search(keywords, max_results=20)
            self.console.print(f"  政策数据库检索到 {len(results)} 条结果")
            self._emit("policy_search", "progress", f"检索到 {len(results)} 条政策文件")
        except Exception as e:
            logger.warning(f"政策数据库搜索失败，降级为 LLM 生成: {e}")
            self.console.print(f"  [yellow]政策数据库搜索失败: {e}[/yellow]")
            self._emit("policy_search", "progress", "政策数据库搜索失败，使用 LLM 降级分析")

        # 3. LLM 提炼政策背景与社会问题
        self._emit("policy_search", "progress", "正在分析政策背景与社会问题...")
        policy_context = await self._analyze_policy_background(user_input, results)

        # 4. 保存结果
        output_path = self.project_dir / "policy_research.md"
        output_path.write_text(policy_context, encoding="utf-8")
        self.console.print(f"  政策背景调研结果已保存: {output_path}")

        # 5. 存入项目记忆
        self.memory.add("policy_research", {
            "keywords": keywords,
            "result_count": len(results),
            "analysis_preview": policy_context[:500],
        })

    async def _extract_policy_keywords(self, user_input: str) -> list[str]:
        """从用户研究想法中提取政策搜索关键词."""
        from scholarpilot.context.prompts.core import POLICY_KEYWORD_EXTRACTION_PROMPT

        prompt = POLICY_KEYWORD_EXTRACTION_PROMPT.format(user_input=user_input)
        messages = [
            {"role": "system", "content": "你是政策分析专家，擅长从研究想法中提取政策检索关键词。"},
            {"role": "user", "content": prompt},
        ]
        try:
            response = await self.llm.chat(messages, temperature=0.3)
            import json as _json
            # 尝试提取 JSON
            match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if match:
                data = _json.loads(match.group())
                return data.get("keywords", [])
        except Exception as e:
            logger.warning(f"政策关键词提取失败: {e}")

        # 降级：简单分词
        fallback = re.findall(r'[\u4e00-\u9fff]{2,6}', user_input)
        return fallback[:5] if fallback else [user_input[:10]]

    async def _analyze_policy_background(
        self, user_input: str, search_results: list[dict]
    ) -> str:
        """基于政策搜索结果，LLM 提炼政策背景与社会问题."""
        from scholarpilot.context.prompts.core import POLICY_BACKGROUND_ANALYSIS_PROMPT

        # 格式化搜索结果（按维度分组）
        if search_results:
            dim_labels = {
                "policy_text": "政策文本（法规/通知/意见等原文）",
                "policy_practice": "政策实践（实施案例/试点报道/新闻动态）",
                "policy_analysis": "政策分析（解读/评估/学术研究）",
            }
            # 按维度分组
            dim_groups: dict[str, list] = {}
            for r in search_results[:20]:
                dim = r.get("dimension", "policy_practice")
                dim_groups.setdefault(dim, []).append(r)

            sections = []
            for dim, label in dim_labels.items():
                items = dim_groups.get(dim, [])
                if not items:
                    continue
                item_lines = "\n".join(
                    f"  - **{r.get('title', '未知标题')}**\n"
                    f"    来源: {r.get('source', '未知')} | "
                    f"日期: {r.get('date', '未知')}\n"
                    f"    摘要: {r.get('summary', '无摘要')}"
                    for r in items[:8]
                )
                sections.append(f"#### {label}（{len(items)}条）\n{item_lines}")

            results_text = "\n\n".join(sections) if sections else ""
        else:
            results_text = "（政策数据库未检索到直接相关结果，以下分析基于通用知识，请研究者补充真实政策文件）"

        prompt = POLICY_BACKGROUND_ANALYSIS_PROMPT.format(
            user_input=user_input,
            search_results=results_text,
        )
        messages = [
            {
                "role": "system",
                "content": "你是政策分析专家和学术研究顾问，擅长将政策背景转化为学术研究问题。",
            },
            {"role": "user", "content": prompt},
        ]
        try:
            response = await self.llm.chat(messages, temperature=0.4)
            return response
        except Exception as e:
            logger.error(f"政策背景分析失败: {e}")
            return f"# 政策背景调研\n\n（分析生成失败: {e}）\n\n请研究者手动补充政策背景。"

    # ===== 辅助方法 =====

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """从 LLM 响应中提取 JSON.

        自动清洗思考过程标记和 markdown 代码块包裹，
        确保即使 LLM 输出含 [💭 思考] 等前缀也能正确提取 JSON。
        """
        # 先清洗思考过程标记
        from scholarpilot.llm.gateway import LLMGateway
        text = LLMGateway._clean_llm_output(text)

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试从 ```json 代码块中提取
        json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试从 { 开始的 JSON 中提取
        brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    # ===== 实证表格模板生成 =====

    async def _phase7c_generate_table_templates(self) -> None:
        """Phase 7c: 为实证论文生成统计表格空模板.

        科研场景：实证论文需要描述性统计表、回归结果表、相关系数矩阵。
        这些表格的框架（变量名、行列结构）应该根据 SPEC 自动生成，
        研究者只需填入真实数字——而不是从零开始排版。
        """
        # 读取 SPEC 判断是否实证论文
        spec_path = self.project_dir / "SPEC.md"
        spec_text = ""
        if spec_path.exists():
            spec_text = spec_path.read_text(encoding="utf-8")
        else:
            spec_json_path = self.project_dir / "SPEC.json"
            if spec_json_path.exists():
                try:
                    spec_data = json.loads(spec_json_path.read_text(encoding="utf-8"))
                    spec_text = json.dumps(spec_data, ensure_ascii=False, indent=2)
                except Exception:
                    pass

        if not spec_text:
            return

        # 判断是否实证论文
        empirical_keywords = ["实证", "empirical", "回归", "面板数据", "计量模型", "假设检验"]
        is_empirical = any(kw in spec_text for kw in empirical_keywords)
        if not is_empirical:
            return

        self.console.print("\n[bold cyan]━━━ Phase 7c: 实证表格模板生成 ━━━[/bold cyan]")
        self.console.print("[dim]📊 正在从 SPEC 提取变量定义...[/dim]")
        self._emit("section_writing", "progress", "正在生成实证表格模板...")

        # 从 SPEC 提取变量和模型信息
        variables, model_specs = self._extract_variables_from_spec(spec_text)

        if not variables:
            self.console.print("[yellow]未能从 SPEC 提取变量，跳过表格生成[/yellow]")
            self.console.print("[dim]可手动运行: scholarpilot tables <项目>[/dim]")
            return

        # 生成表格
        from scholarpilot.tools.table_generator import (
            generate_descriptive_stats_table,
            generate_regression_table,
            generate_correlation_table,
        )

        self.console.print(f"  [green]提取到 {len(variables)} 个变量[/green]")

        tables_parts: list[str] = []
        tables_parts.append("# 实证表格模板\n")
        tables_parts.append("> 以下表格由 ScholarPilot 根据 SPEC 自动生成，数据单元格留空供研究者填写。\n")

        # 1. 描述性统计表
        self.console.print("[dim]  生成描述性统计表...[/dim]")
        desc_table = generate_descriptive_stats_table(variables)
        tables_parts.append("## 表1 描述性统计\n")
        tables_parts.append(desc_table)
        tables_parts.append("")

        # 2. 回归结果表
        if model_specs:
            self.console.print(f"[dim]  生成回归结果表（{len(model_specs)}个模型）...[/dim]")
            reg_table = generate_regression_table(model_specs)
            tables_parts.append("## 表2 回归结果\n")
            tables_parts.append(reg_table)
            tables_parts.append("")
        else:
            # 默认生成一个基准回归模型
            self.console.print("[dim]  生成回归结果表（默认模型）...[/dim]")
            all_var_names = [v["name"] for v in variables]
            default_model = {
                "name": "基准回归",
                "variables": all_var_names[:5],  # 取前5个变量
                "has_fixed_effects": True,
                "has_cluster_se": True,
            }
            reg_table = generate_regression_table([default_model])
            tables_parts.append("## 表2 回归结果\n")
            tables_parts.append(reg_table)
            tables_parts.append("")

        # 3. 相关系数矩阵
        var_names = [v["name"] for v in variables if v.get("type") != "虚拟变量"]
        if len(var_names) >= 2:
            self.console.print("[dim]  生成相关系数矩阵...[/dim]")
            corr_table = generate_correlation_table(var_names[:8])  # 最多8个变量
            tables_parts.append("## 表3 相关系数矩阵\n")
            tables_parts.append(corr_table)
            tables_parts.append("")

        # 保存
        tables_path = self.project_dir / "draft" / "tables_template.md"
        tables_path.write_text("\n".join(tables_parts), encoding="utf-8")
        self.console.print(f"  [green]表格模板已保存: {tables_path}[/green]")
        self.console.print("[dim]请研究者填入真实数据后替换草稿中的占位符[/dim]")

        self.memory.add("table_templates", {
            "variables": len(variables),
            "models": len(model_specs) if model_specs else 1,
        })

    def _extract_variables_from_spec(
        self, spec_text: str
    ) -> tuple[list[dict], list[dict]]:
        """从 SPEC 文本中提取变量定义和模型设定.

        解析策略：
        1. 查找"变量设计"/"变量定义"段落
        2. 用正则匹配变量名和描述
        3. 查找"模型设定"段落提取模型信息

        Args:
            spec_text: SPEC 文本（Markdown 或 JSON 字符串）。

        Returns:
            (variables, model_specs) 元组。
            variables: [{"name": "debt_ratio", "description": "地方政府债务率", "type": "continuous"}, ...]
            model_specs: [{"name": "基准回归", "variables": [...], "has_fixed_effects": True}, ...]
        """
        variables: list[dict] = []
        model_specs: list[dict] = []

        # 提取变量定义段落
        # 匹配 "## 变量设计\n..." 或 "变量设计：..." 后面的内容
        var_section_patterns = [
            r"变量设计[：:\s\n]+(.*?)(?=模型设定|稳健性|预期结果|研究方法|$)",
            r"变量定义[：:\s\n]+(.*?)(?=模型设定|稳健性|预期结果|研究方法|$)",
            r"核心变量[：:\s\n]+(.*?)(?=模型设定|稳健性|预期结果|研究方法|$)",
            r"变量设计(.*?)(?=模型设定|稳健性|预期结果|研究方法|$)",
            r"变量定义(.*?)(?=模型设定|稳健性|预期结果|研究方法|$)",
        ]

        var_section = ""
        for pattern in var_section_patterns:
            match = re.search(pattern, spec_text, re.DOTALL | re.IGNORECASE)
            if match:
                var_section = match.group(1)
                break

        if var_section:
            # 提取变量：匹配 "变量名：描述" 或 "- 变量名（描述）" 等格式
            # 中文格式：被解释变量：GDP增长率
            # 英文格式：debt_ratio: Debt to GDP ratio
            var_patterns = [
                # "- 被解释变量：debt_ratio（地方政府债务率）"
                r"[-•]\s*(?:被解释变量|核心解释变量|控制变量)[：:]\s*(\w+)\s*[（(]([^）)]+)",
                # "- debt_ratio：地方政府债务率"
                r"[-•]\s*(\w+)[：:]\s*([^\n]{2,30})",
                # "debt_ratio (地方政府债务率)"
                r"(\w+)\s*[（(]([^）)]{2,30})",
            ]

            seen_names: set[str] = set()
            for pattern in var_patterns:
                for match in re.finditer(pattern, var_section):
                    name = match.group(1).strip()
                    desc = match.group(2).strip()
                    if name and len(name) <= 30 and name not in seen_names:
                        # 判断变量类型
                        var_type = "continuous"
                        if any(kw in desc for kw in ["虚拟", "dummy", "是否", "0-1", "二分"]):
                            var_type = "虚拟变量"
                        variables.append({
                            "name": name,
                            "description": desc,
                            "type": var_type,
                        })
                        seen_names.add(name)

        # 如果正则没提取到变量，尝试从 SPEC JSON 中提取
        if not variables:
            try:
                spec_json_path = self.project_dir / "SPEC.json"
                if spec_json_path.exists():
                    spec_data = json.loads(spec_json_path.read_text(encoding="utf-8"))
                    # 尝试从 JSON 中提取变量
                    for key in ["variables", "key_variables", "variable_design"]:
                        if key in spec_data and isinstance(spec_data[key], list):
                            for v in spec_data[key]:
                                if isinstance(v, dict) and v.get("name"):
                                    variables.append({
                                        "name": v["name"],
                                        "description": v.get("description", ""),
                                        "type": v.get("type", "continuous"),
                                    })
                                elif isinstance(v, str):
                                    variables.append({
                                        "name": v,
                                        "description": "",
                                        "type": "continuous",
                                    })
            except Exception:
                pass

        # 提取模型设定
        model_section_patterns = [
            r"模型设定[：:\s\n]+(.*?)(?=预期结果|数据需求|$)",
            r"计量模型[：:\s\n]+(.*?)(?=预期结果|数据需求|$)",
            r"模型设定(.*?)(?=预期结果|数据需求|$)",
            r"计量模型(.*?)(?=预期结果|数据需求|$)",
        ]

        model_section = ""
        for pattern in model_section_patterns:
            match = re.search(pattern, spec_text, re.DOTALL | re.IGNORECASE)
            if match:
                model_section = match.group(1)
                break

        if model_section:
            # 检测是否有固定效应、聚类标准误
            has_fe = any(kw in model_section for kw in ["固定效应", "fixed effect", "个体效应", "时间效应"])
            has_cluster = any(kw in model_section for kw in ["聚类", "cluster", "稳健标准误"])

            # 生成模型规格
            var_names = [v["name"] for v in variables]
            model_specs = [
                {
                    "name": "基准回归",
                    "variables": var_names[:5] if var_names else [],
                    "has_fixed_effects": has_fe,
                    "has_cluster_se": has_cluster,
                }
            ]

            # 如果提到稳健性检验，添加一个模型
            if any(kw in model_section for kw in ["稳健性", "robustness"]):
                model_specs.append({
                    "name": "稳健性检验",
                    "variables": var_names[:5] if var_names else [],
                    "has_fixed_effects": has_fe,
                    "has_cluster_se": has_cluster,
                })

        return variables, model_specs

    async def generate_tables(self) -> dict[str, Any]:
        """独立生成实证表格模板（用户编辑 SPEC 后可重新生成）.

        Returns:
            包含生成结果的字典。
        """
        spec_path = self.project_dir / "SPEC.md"
        spec_text = ""
        if spec_path.exists():
            spec_text = spec_path.read_text(encoding="utf-8")
        else:
            spec_json_path = self.project_dir / "SPEC.json"
            if spec_json_path.exists():
                try:
                    spec_data = json.loads(spec_json_path.read_text(encoding="utf-8"))
                    spec_text = json.dumps(spec_data, ensure_ascii=False, indent=2)
                except Exception:
                    pass

        if not spec_text:
            self.console.print("[red]SPEC 文件不存在，请先运行写作流程[/red]")
            return {}

        result = await self._phase7c_generate_table_templates()
        # _phase7c 内部已处理输出，这里返回状态
        tables_path = self.project_dir / "draft" / "tables_template.md"
        return {"generated": tables_path.exists(), "path": str(tables_path)}

    # ===== 独立定稿（用户手动编辑后重新处理） =====

    async def finalize(
        self,
        abstract: bool = True,
        citations: bool = True,
    ) -> dict[str, Any]:
        """独立定稿流程：在用户手动编辑草稿后重新生成摘要和参考文献.

        科研场景：研究者用 ScholarPilot 生成初稿后，必然会手动改写以降低 AI 率。
        改写后正文内容变了，原来的摘要和参考文献不再准确。此时不需要重跑整个
        chat 工作流，只需用 finalize 重新生成摘要 + 重新提取验证引用。

        Args:
            abstract: 是否重新生成摘要。
            citations: 是否重新提取和管理引用。

        Returns:
            质量报告字典。
        """
        draft_path = self.project_dir / "draft" / "full_draft.md"
        if not draft_path.exists():
            self.console.print("[red]草稿文件不存在，请先运行写作流程[/red]")
            return {}

        self.console.print(
            Panel(
                f"项目: {self.project_dir.name}\n"
                f"摘要: {'生成' if abstract else '跳过'}\n"
                f"引用: {'管理' if citations else '跳过'}",
                title="📝 定稿处理",
            )
        )

        # 如果两者都跳过，只做质量检查
        if not abstract and not citations:
            self.console.print("[yellow]未选择任何操作，仅显示质量报告[/yellow]")
        else:
            if abstract:
                await self._phase7a_generate_abstract()
            if citations:
                await self._phase7b_citation_management()

        # 质量报告
        report = self.generate_quality_report()
        self._display_quality_report(report)
        return report

    def generate_quality_report(self) -> dict[str, Any]:
        """生成论文质量报告：字数、引用数、结构完整性等.

        帮助研究者快速判断初稿是否达到目标期刊的投稿门槛。
        不需要 API 调用，纯本地分析。

        Returns:
            质量报告字典，包含:
            - word_count: 正文中文字数
            - reference_count: 参考文献数量
            - verified_count: 已验证引用数
            - unverified_count: 未验证引用数
            - chapter_count: 章节数
            - has_abstract: 是否有摘要
            - has_keywords: 是否有关键词
            - has_jel: 是否有JEL分类号
            - structure_complete: 结构是否完整
            - missing_parts: 缺失部分列表
        """
        import re
        report: dict[str, Any] = {}

        draft_path = self.project_dir / "draft" / "full_draft.md"
        full_text = draft_path.read_text(encoding="utf-8") if draft_path.exists() else ""

        # 1. 字数统计（中文字符 + 英文单词）
        # 移除 markdown 标记和参考文献部分
        body_text = full_text
        # 去掉参考文献和AI声明部分
        for separator in ["\n---\n## 参考文献", "\n---\n\n## 参考文献", "\n## 参考文献"]:
            if separator in body_text:
                body_text = body_text.split(separator)[0]
        # 去掉 markdown 标记
        clean_text = re.sub(r"#+\s*", "", body_text)
        clean_text = re.sub(r"\*+|`+|>+|\|", "", clean_text)
        clean_text = re.sub(r"\n+", "\n", clean_text)
        # 中文字符数
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", clean_text))
        # 英文单词数
        english_words = len(re.findall(r"[a-zA-Z]+", clean_text))
        # 综合字数：中文字 + 英文词（英文每词约等于2个中文字）
        report["word_count"] = chinese_chars + english_words
        report["chinese_chars"] = chinese_chars
        report["english_words"] = english_words

        # 2. 章节统计
        sections = self.file_manager.list_sections(self.project_dir)
        report["chapter_count"] = len(sections)
        report["chapters"] = sections

        # 3. 参考文献统计
        ref_path = self.project_dir / "draft" / "references.md"
        if ref_path.exists():
            ref_text = ref_path.read_text(encoding="utf-8")
            # 按行计算参考文献条目（排除标题和空行）
            ref_lines = [
                line.strip() for line in ref_text.split("\n")
                if line.strip()
                and not line.strip().startswith("#")
                and not line.strip().startswith("---")
                and not line.strip().startswith("【")
                and not line.strip().startswith("AI")
                and not line.strip().startswith("本文")
                and len(line.strip()) > 10
            ]
            report["reference_count"] = len(ref_lines)
        else:
            report["reference_count"] = 0

        # 从记忆中获取验证信息
        citation_mem = self.memory.get("citation_management", {})
        report["verified_count"] = citation_mem.get("verified", 0)
        report["unverified_count"] = citation_mem.get("unverified", 0)

        # 4. 摘要和关键词检查
        report["has_abstract"] = "摘要" in full_text or "Abstract" in full_text
        report["has_keywords"] = "关键词" in full_text or "Keywords" in full_text
        report["has_jel"] = "JEL" in full_text or "中图分类号" in full_text

        # 4b. 实证表格模板检查
        tables_path = self.project_dir / "draft" / "tables_template.md"
        report["has_tables_template"] = tables_path.exists()
        if report["has_tables_template"]:
            tables_text = tables_path.read_text(encoding="utf-8")
            report["table_count"] = tables_text.count("## 表")
        else:
            report["table_count"] = 0

        # 4c. 是否实证论文
        report["is_empirical"] = any(
            kw in full_text for kw in ["实证", "回归", "面板数据"]
        )

        # 5. 结构完整性检查
        # 典型论文结构：引言/绪论 + 文献综述 + 理论分析/研究设计 + 实证分析 + 结论
        structure_keywords = {
            "引言/绪论": ["引言", "绪论", "导论", "Introduction"],
            "文献综述": ["文献综述", "文献回顾", "Literature Review", "文献述评"],
            "理论分析/研究设计": ["理论分析", "研究设计", "理论框架", "模型设定", "Research Design"],
            "实证分析": ["实证分析", "实证研究", "实证结果", "Empirical", "回归结果"],
            "结论": ["结论", "结语", "Conclusion", "总结"],
        }
        found_structure: dict[str, bool] = {}
        for part, keywords in structure_keywords.items():
            found_structure[part] = any(kw in full_text for kw in keywords)
        report["structure"] = found_structure
        report["structure_complete"] = all(found_structure.values())
        report["missing_parts"] = [
            part for part, found in found_structure.items() if not found
        ]

        # 6. 期刊达标评估
        report["assessment"] = self._assess_journal_readiness(report)

        # 7. Claim 校准指标（从 state.json 读取）
        state = self.file_manager.load_state(self.project_dir) or {}
        claim_summary = state.get("claim_calibration_summary", {})
        if claim_summary:
            report["claim_calibration"] = {
                "completed": True,
                "total_claims": claim_summary.get("total_claims", 0),
                "supported": claim_summary.get("supported", 0),
                "overreach": claim_summary.get("overreach", 0),
                "unsupported": claim_summary.get("unsupported", 0),
                "partial": claim_summary.get("partial", 0),
                "integrity_score": claim_summary.get("integrity_score", 0),
                "critical_issues_count": claim_summary.get("critical_issues_count", 0),
            }
        else:
            report["claim_calibration"] = {"completed": False}

        # 8. 证据矩阵指标（从 state.json 读取）
        evidence_mem = self.memory.get("evidence_matrix", {})
        if evidence_mem:
            report["evidence_matrix"] = {
                "total_papers": evidence_mem.get("total_papers", 0),
                "strong": evidence_mem.get("strong", 0),
                "moderate": evidence_mem.get("moderate", 0),
                "weak": evidence_mem.get("weak", 0),
                "unverified": evidence_mem.get("unverified", 0),
            }
        else:
            report["evidence_matrix"] = {"total_papers": 0}

        return report

    def _assess_journal_readiness(self, report: dict[str, Any]) -> dict[str, str]:
        """评估论文是否达到常见期刊投稿标准.

        Args:
            report: 质量报告。

        Returns:
            各项评估结果字典。
        """
        assessment: dict[str, str] = {}

        # 字数评估
        wc = report.get("word_count", 0)
        if wc >= 15000:
            assessment["word_count"] = f"充足（{wc}字，达到CSSCI核心期刊标准）"
        elif wc >= 10000:
            assessment["word_count"] = f"基本达标（{wc}字，建议补充至1.5万字）"
        elif wc >= 5000:
            assessment["word_count"] = f"偏少（{wc}字，核心期刊通常需要1.5-2万字）"
        else:
            assessment["word_count"] = f"不足（{wc}字，需要大幅扩充）"

        # 参考文献评估
        ref_count = report.get("reference_count", 0)
        if ref_count >= 25:
            assessment["references"] = f"充足（{ref_count}篇，CSSCI标准{CSSCI_REF_RANGE}篇）"
        elif ref_count >= 15:
            assessment["references"] = f"偏少（{ref_count}篇，建议补充至25篇以上）"
        elif ref_count > 0:
            assessment["references"] = f"不足（{ref_count}篇，核心期刊通常需要{CSSCI_REF_RANGE}篇）"
        else:
            assessment["references"] = "缺失（无参考文献，请运行引用管理）"

        # 验证率
        total_cites = report.get("verified_count", 0) + report.get("unverified_count", 0)
        if total_cites > 0:
            verify_rate = report.get("verified_count", 0) / total_cites * 100
            if verify_rate >= 80:
                assessment["verification"] = f"良好（{verify_rate:.0f}%已验证）"
            elif verify_rate >= 50:
                assessment["verification"] = f"一般（{verify_rate:.0f}%已验证，需核查未验证引用）"
            else:
                assessment["verification"] = f"较差（{verify_rate:.0f}%已验证，大量引用需核查）"
        else:
            assessment["verification"] = "未验证（请运行引用管理）"

        # 结构完整性
        if report.get("structure_complete"):
            assessment["structure"] = "完整（包含全部5个标准章节）"
        else:
            missing = report.get("missing_parts", [])
            assessment["structure"] = f"不完整（缺失: {'、'.join(missing)}）"

        return assessment

    def _display_quality_report(self, report: dict[str, Any]) -> None:
        """以表格形式展示质量报告."""
        from rich.table import Table

        self.console.print("\n[bold cyan]━━━ 质量报告 ━━━[/bold cyan]\n")

        # 基本指标表
        table = Table(title="📊 论文质量指标")
        table.add_column("指标", style="cyan", width=15)
        table.add_column("数值", style="white", width=15)
        table.add_column("评估", style="yellow")

        assessment = report.get("assessment", {})

        table.add_row(
            "总字数",
            f"{report.get('word_count', 0)}",
            assessment.get("word_count", ""),
        )
        table.add_row(
            "参考文献",
            f"{report.get('reference_count', 0)} 篇",
            assessment.get("references", ""),
        )
        table.add_row(
            "引用验证",
            f"{report.get('verified_count', 0)}/{report.get('verified_count', 0) + report.get('unverified_count', 0)}",
            assessment.get("verification", ""),
        )
        table.add_row(
            "章节数",
            f"{report.get('chapter_count', 0)}",
            assessment.get("structure", ""),
        )

        self.console.print(table)

        # 结构详情
        structure = report.get("structure", {})
        if structure:
            self.console.print("\n[bold]结构检查:[/bold]")
            for part, found in structure.items():
                icon = "[green]✓[/green]" if found else "[red]✗[/red]"
                self.console.print(f"  {icon} {part}")

        # 摘要/关键词/分类号
        self.console.print("\n[bold]格式要素:[/bold]")
        items = [
            ("摘要", report.get("has_abstract", False)),
            ("关键词", report.get("has_keywords", False)),
            ("JEL/中图分类号", report.get("has_jel", False)),
        ]
        for name, found in items:
            icon = "[green]✓[/green]" if found else "[red]✗[/red]"
            self.console.print(f"  {icon} {name}")

        # 实证表格模板
        if report.get("has_tables_template"):
            table_count = report.get("table_count", 0)
            self.console.print(f"  [green]✓[/green] 实证表格模板（{table_count}张）")
        elif report.get("is_empirical", False):
            self.console.print("  [yellow]⚠ 实证表格模板未生成（运行: scholarpilot tables <项目>）[/yellow]")

        # 证据矩阵指标
        evidence = report.get("evidence_matrix", {})
        if evidence.get("total_papers", 0) > 0:
            self.console.print(
                f"\n[bold]证据矩阵:[/bold] {evidence['total_papers']} 篇文献 "
                f"(强{evidence.get('strong', 0)}/中{evidence.get('moderate', 0)}/"
                f"弱{evidence.get('weak', 0)}/未验证{evidence.get('unverified', 0)})"
            )

        # Claim 校准指标
        claim = report.get("claim_calibration", {})
        if claim.get("completed"):
            score = claim.get("integrity_score", 0)
            score_color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
            self.console.print(
                f"\n[bold]Claim 校准:[/bold] {claim.get('total_claims', 0)} 条结论 | "
                f"诚信评分: [{score_color}]{score}/100[/{score_color}]"
            )
            overreach = claim.get("overreach", 0)
            unsupported = claim.get("unsupported", 0)
            if overreach > 0 or unsupported > 0:
                self.console.print(
                    f"  [yellow]⚠ 结论越界 {overreach} 条 | 无引用支撑 {unsupported} 条[/yellow]"
                )
                self.console.print("  [dim]  详见: draft/claim_calibration_report.md[/dim]")

        # 未验证引用警告
        unverified = report.get("unverified_count", 0)
        if unverified > 0:
            self.console.print(
                f"\n[yellow]⚠️ {unverified} 条引用未通过验证，请手动核查[/yellow]"
            )

        # 建议
        self.console.print("\n[bold]下一步建议:[/bold]")
        wc = report.get("word_count", 0)
        if wc < 15000:
            self.console.print("  • 字数不足，建议扩充各章节内容")
        if report.get("reference_count", 0) < 25:
            self.console.print("  • 参考文献偏少，建议补充更多高质量文献")
        if report.get("missing_parts"):
            self.console.print(f"  • 结构缺失：{', '.join(report['missing_parts'])}")
        if not report.get("has_abstract"):
            self.console.print("  • 缺少摘要，运行: scholarpilot finalize <项目> --abstract-only")
        if report.get("unverified_count", 0) > 0:
            self.console.print("  • 有未验证引用，建议手动核查或重新运行引用管理")

        if (
            wc >= 15000
            and report.get("reference_count", 0) >= 25
            and report.get("structure_complete")
            and report.get("has_abstract")
        ):
            self.console.print("  [green]• 论文质量达标，可考虑导出投稿[/green]")
            self.console.print("  [dim]  导出命令: scholarpilot export <项目> -f docx[/dim]")

    def _phase8b_deai_polish(self) -> None:
        """Phase 8b: 去AI味 + 中文润色后处理.

        在引用管理（Phase 7b）之后、post_completion 之前执行：
        1. 对 full_draft.md 进行 AI 痕迹检测
        2. 逐章运行去AI味处理（自动策略选择）
        3. 对去AI味后文本进行中文润色
        4. 保存 full_draft_polished.md 和 deai_report.md
        5. 更新 state.json 记录完成状态

        异常处理：去AI味或润色失败时记录日志但不中断流程。
        """
        from rich.panel import Panel

        log = logging.getLogger(__name__)

        self.console.print(
            Panel(
                "[bold cyan]去AI味 + 中文润色后处理[/bold cyan]\n"
                "检测AI写作痕迹 → 逐章去AI味 → 中文润色 → 生成报告",
                title="Phase 8b",
                border_style="cyan",
            )
        )

        # 非交互模式判断
        if not self.non_interactive:
            from rich.prompt import Confirm

            try:
                should_run = Confirm.ask(
                    "是否执行去AI味和中文润色处理？",
                    default=True,
                )
            except Exception:
                should_run = True
            if not should_run:
                self.console.print("[yellow]已跳过去AI味和润色处理[/yellow]")
                return
        else:
            self.console.print("  [dim][非交互模式] 自动执行去AI味和润色[/dim]")

        # 读取 full_draft.md
        draft_path = self.project_dir / "draft" / "full_draft.md"
        if not draft_path.exists():
            self.console.print("[yellow]草稿文件不存在，跳过去AI味处理[/yellow]")
            logger.warning("full_draft.md 不存在，跳过 Phase 8b")
            return

        full_text = draft_path.read_text(encoding="utf-8")
        if not full_text.strip():
            self.console.print("[yellow]草稿内容为空，跳过去AI味处理[/yellow]")
            return

        # 延迟导入去AI味和润色模块
        try:
            from scholarpilot.tools.de_ai import DeAIEngine
            from scholarpilot.tools.polish_engine import PolishEngine
        except ImportError as e:
            logger.error("导入去AI味/润色模块失败: %s", e)
            self.console.print(f"[red]导入去AI味/润色模块失败: {e}[/red]")
            return

        deai_engine = DeAIEngine()
        polish_engine = PolishEngine()

        # ---- 1. AI痕迹检测（整体）----
        self.console.print("\n[dim]检测AI写作痕迹...[/dim]")
        try:
            risk_before = deai_engine.detect_ai_patterns(full_text)
        except Exception as e:
            logger.error("AI痕迹检测失败: %s", e)
            self.console.print(f"[red]AI痕迹检测失败: {e}[/red]")
            return

        self.console.print(
            f"  [cyan]处理前[/cyan] 风险等级: {risk_before.risk_level.value}, "
            f"AI生成概率: {risk_before.ai_probability:.1%}, "
            f"总体评分: {risk_before.overall_score:.1f}"
        )
        if risk_before.detected_patterns:
            self.console.print(
                f"  [dim]检测到AI模式: {', '.join(risk_before.detected_patterns)}[/dim]"
            )

        # ---- 2. 按章节拆分 ----
        sections = self._split_draft_for_deai(full_text)
        self.console.print(f"  [dim]共拆分 {len(sections)} 个章节[/dim]")

        # ---- 3. 逐章去AI味 + 中文润色 ----
        polished_sections: list[str] = []
        deai_results: list = []
        total_polish_changes = 0

        for idx, section in enumerate(sections, 1):
            title = section.get("title", f"章节{idx}")
            content = section.get("content", "")

            if not content.strip():
                polished_sections.append(content)
                continue

            self.console.print(
                f"  [dim]({idx}/{len(sections)}) 去AI味: {title}[/dim]"
            )

            # 去AI味处理（自动策略选择）
            deai_result = None
            try:
                deai_result = deai_engine.process(content)
                deai_results.append(deai_result)
                processed_text = deai_result.processed_text
            except Exception as e:
                logger.error("章节 '%s' 去AI味失败: %s", title, e)
                self.console.print(
                    f"    [yellow]去AI味失败，保留原文: {e}[/yellow]"
                )
                processed_text = content

            # 中文润色
            try:
                polish_result = polish_engine.polish_chinese(processed_text)
                polished_text = polish_result.polished_text
                total_polish_changes += polish_result.change_count
            except Exception as e:
                logger.error("章节 '%s' 中文润色失败: %s", title, e)
                self.console.print(
                    f"    [yellow]中文润色失败，使用去AI味结果: {e}[/yellow]"
                )
                polished_text = processed_text

            polished_sections.append(polished_text)

        # ---- 4. 合并结果 ----
        polished_full = "\n\n---\n\n".join(polished_sections)

        # ---- 4b. 全局标点清洗（去AI味/润色引擎可能在 LLM 调用后引入异常标点组合）----
        # 关键：单次 `；。\s*→；` 无法清除 `；。。` 这类组合（替换后会残留 `；。`，
        # 而后续 `。。+→。` 又匹配不上单个 `。`）。因此使用 while 循环反复清洗，
        # 同时处理 `；。\s*`（含尾随空白）与直接 `；。` 两种模式，直至一轮内无任何变化才停止。
        import re as _re_clean
        _semicolon_period_total = 0   # 专门统计 ；。 清除次数
        while True:
            _sp_count = 0      # 本轮 ；。 清除数
            _other_count = 0   # 本轮其他重复标点合并数
            # `；。\s*` 已涵盖直接的 `；。`（\s* 匹配零或多个空白）
            polished_full, _n = _re_clean.subn(r"；。\s*", "；", polished_full)
            _sp_count += _n
            _semicolon_period_total += _n
            # 合并重复标点（可能在 ；。 清除后形成新的异常邻接，需在同一轮处理）
            polished_full, _n = _re_clean.subn(r"。。+", "。", polished_full)
            _other_count += _n
            polished_full, _n = _re_clean.subn(r"；；+", "；", polished_full)
            _other_count += _n
            polished_full, _n = _re_clean.subn(r"，，+", "，", polished_full)
            _other_count += _n
            polished_full, _n = _re_clean.subn(r"：：+", "：", polished_full)
            _other_count += _n
            if _sp_count == 0 and _other_count == 0:
                break
        if _semicolon_period_total > 0:
            logger.info(
                "Phase 8b 标点清洗: full_draft_polished 共清除 %d 处 ；。残留",
                _semicolon_period_total,
            )
            self.console.print(
                f"  [dim]标点清洗: 清除 {_semicolon_period_total} 处；。残留[/dim]"
            )

        # ---- 4c. 修改15: 增强标点清洗 ----
        _enhanced_count = 0

        # 1. 修复标点前空格：删除标点前的空白字符
        polished_full, _n = _re_clean.subn(r'\s+([。，；：、！？）」』])', r'\1', polished_full)
        _enhanced_count += _n

        # 2. 修复括号格式：英文括号在中文语境中替换为中文括号
        # 仅在括号内含中文时替换
        def _fix_paren(m):
            inner = m.group(1)
            if _re_clean.search(r'[\u4e00-\u9fff]', inner):
                return f'（{inner}）'
            return m.group(0)
        polished_full_new = _re_clean.sub(r'\(([^)]{1,30})\)', _fix_paren, polished_full)
        _paren_count = len(_re_clean.findall(r'\(([^)]{1,30})\)', polished_full)) - \
                       len(_re_clean.findall(r'\(([^)]{1,30})\)', polished_full_new))
        polished_full = polished_full_new
        _enhanced_count += max(0, _paren_count)

        # 3. 修复从句中间的句号碎片化：短片段（5-12字）后的句号改为逗号
        # 仅当句号前是短中文片段且后面紧跟中文内容时
        polished_full, _n = _re_clean.subn(
            r'([\u4e00-\u9fff]{5,12})。([\u4e00-\u9fff])',
            r'\1，\2',
            polished_full
        )
        _enhanced_count += _n

        if _enhanced_count > 0:
            logger.info("Phase 8b 增强标点清洗: 共修复 %d 处", _enhanced_count)
            self.console.print(
                f"  [dim]增强标点清洗: 修复 {_enhanced_count} 处（空格/括号/碎片化）[/dim]"
            )

        # ---- 4d. 修改7: 标点碎片化扩展修复 ----
        # 7a: 数字/系数后句号改逗号
        polished_full, _n7a = _re_clean.subn(
            r'([0-9][0-9.%]*[个百分比标准差]*?)。([\u4e00-\u9fff])',
            r'\1，\2',
            polished_full,
        )
        # 7b: 右括号后句号改逗号
        polished_full, _n7b = _re_clean.subn(
            r'([）)])。([\u4e00-\u9fff])',
            r'\1，\2',
            polished_full,
        )
        # 7c: 英文单词后句号改逗号
        polished_full, _n7c = _re_clean.subn(
            r'([a-zA-Z]{2,})。([\u4e00-\u9fff])',
            r'\1，\2',
            polished_full,
        )
        # 7d: 连接词后句号改逗号（其中/其次/同时/例如/不过/因此/由此/此外/另外/而且/然而）
        # 后置字符匹配扩展为中文或$（LaTeX公式起始符）
        polished_full, _n7d = _re_clean.subn(
            r'(其中|其次|同时|例如|不过|因此|由此|此外|另外|而且|然而|总体而言|最后)。([\u4e00-\u9fff$])',
            r'\1，\2',
            polished_full,
        )
        # 7e: 右引号后句号改逗号（如 "同群效应"。显示 → "同群效应"，显示）
        polished_full, _n7e = _re_clean.subn(
            r'(["""''])。([\u4e00-\u9fff])',
            r'\1，\2',
            polished_full,
        )
        # 7f: 学术动词后句号改逗号（指出/发现/提出/强调/认为/表明/建议/证实/揭示/论证/说明/阐释）
        # 扩展动词列表：增加分析/认为/强调/指出/发现/提出/检验/验证/考察/探讨/构建/建立/采用/使用
        # 动态化改造：合并去重后新增确认/排除/支持/否定/证明/概述/总结/归纳/推断/预测/
        #   评估/测量/测定/量化/比较/对比/区分/识别/观察/记录/描述/界定/分类/划分
        polished_full, _n7f = _re_clean.subn(
            r'(指出|发现|提出|强调|认为|表明|建议|证实|揭示|论证|说明|阐释|分析|检验|验证|考察|探讨|构建|建立|采用|使用|运用|存在|具有|呈现|体现|显示|反映|确认|排除|支持|否定|证明|概述|总结|归纳|推断|预测|评估|测量|测定|量化|比较|对比|区分|识别|观察|记录|描述|界定|分类|划分)。([\u4e00-\u9fff])',
            r'\1，\2',
            polished_full,
        )
        # 7f2: 动词后句号改逗号 — 补充动词不在句首的情况（如"上述分析。""实证发现。"）
        polished_full, _n7f2 = _re_clean.subn(
            r'([\u4e00-\u9fff]{2,8}(?:指出|发现|提出|强调|认为|表明|建议|证实|揭示|论证|说明|阐释|分析|检验|验证|考察|探讨|构建|建立|确认|排除|支持|否定|证明|概述|总结|归纳|推断|预测|评估|测量|测定|量化|比较|对比|区分|识别|观察|记录|描述|界定|分类|划分))。([\u4e00-\u9fff])',
            r'\1，\2',
            polished_full,
        )
        _punct_ext_count = _n7a + _n7b + _n7c + _n7d + _n7e + _n7f + _n7f2
        if _punct_ext_count > 0:
            logger.info(
                "Phase 8b 标点扩展修复: 7a=%d, 7b=%d, 7c=%d, 7d=%d, 7e=%d, 7f=%d, 7f2=%d",
                _n7a, _n7b, _n7c, _n7d, _n7e, _n7f, _n7f2,
            )
            self.console.print(
                f"  [dim]标点扩展修复: {_punct_ext_count} 处（数字/括号/英文/连接词/引号/动词后句号）[/dim]"
            )

        # ---- 4e. 修改12: 引用标点修复（句号→逗号）----
        # 4e-1: 英文姓名后句号改逗号（如 Smith。2024 → Smith，2024）
        polished_full, _n_cite_en = _re_clean.subn(
            r'([A-Za-z]{2,}(?:\s[A-Za-z]+)*(?:等)?)。(\d{4})',
            r'\1，\2',
            polished_full,
        )
        # 4e-2: 中文姓名后句号改逗号（如 张天和易明。2024 → 张天和易明，2024）
        polished_full, _n_cite_zh = _re_clean.subn(
            r'([\u4e00-\u9fff]{2,4}和[\u4e00-\u9fff]{2,4})。(\d{4})',
            r'\1，\2',
            polished_full,
        )
        _n_cite = _n_cite_en + _n_cite_zh
        if _n_cite > 0:
            logger.info("Phase 8b 引用标点修复: %d 处句号→逗号", _n_cite)
            self.console.print(
                f"  [dim]引用标点修复: {_n_cite} 处[/dim]"
            )

        # ---- 4e-3: 清理"未知"占位引用 ----
        # 清理 "（未知，2026）" 或 "（未知，2025）" 等占位作者引用
        polished_full, _n_unknown = _re_clean.subn(
            r'（未知[，,]\s*\d{4}）', '', polished_full,
        )
        polished_full, _n_unknown2 = _re_clean.subn(
            r'[；;]\s*未知[，,]\s*\d{4}', '', polished_full,
        )
        polished_full, _n_unknown3 = _re_clean.subn(
            r'未知[，,]\s*\d{4}[；;]', '', polished_full,
        )
        _n_unknown_total = _n_unknown + _n_unknown2 + _n_unknown3
        if _n_unknown_total > 0:
            logger.info("Phase 8b 清理'未知'占位引用: %d 处", _n_unknown_total)
            self.console.print(
                f"  [dim]清理'未知'占位引用: {_n_unknown_total} 处[/dim]"
            )

        # ---- 4f. 修改8: 清理AI生成标记 ----
        # 清理【研究者注意：...】等占位标记
        polished_full, _n8a = _re_clean.subn(
            r'【研究者注意[^】]*】', '', polished_full,
        )
        polished_full, _n8b = _re_clean.subn(
            r'【(?:数据占位|示例|模板|TODO|待替换)[^】]*】', '', polished_full,
        )
        # 清理HTML注释风格的占位
        polished_full, _n8c = _re_clean.subn(
            r'<!--\s*(?:研究者|数据占位|示例|模板|TODO)[^>]*-->', '', polished_full,
        )
        # 清理连续空行（3+换行合并为2个）
        polished_full = _re_clean.sub(r'\n{3,}', '\n\n', polished_full)
        _ai_marker_count = _n8a + _n8b + _n8c
        if _ai_marker_count > 0:
            logger.info("Phase 8b AI标记清理: 清除 %d 处占位标记", _ai_marker_count)
            self.console.print(
                f"  [dim]AI标记清理: 清除 {_ai_marker_count} 处占位标记[/dim]"
            )

        # ---- 4g0. 异质性分析因果语言→相关性表述重写 ----
        # 防止无交互项检验的分组回归结果被表述为因果性比较
        # "对X的促进作用强于Y" → "与X的正相关关系强于Y"
        _overreach_patterns = [
            # "对...的促进作用/推动作用/驱动作用/助推作用强于" → "与...的正相关关系强于"
            (
                r'对([\u4e00-\u9fff]{2,20})的(促进|推动|驱动|助推)作用强于',
                r'与\1的正相关关系强于',
            ),
            # "对...的促进作用/推动作用/驱动作用/助推作用弱于" → "与...的正相关关系弱于"
            (
                r'对([\u4e00-\u9fff]{2,20})的(促进|推动|驱动|助推)作用弱于',
                r'与\1的正相关关系弱于',
            ),
            # "对...的影响/作用大于/小于" → "与...的相关性高于/低于"
            (
                r'对([\u4e00-\u9fff]{2,20})的影响大于',
                r'与\1的相关性高于',
            ),
            (
                r'对([\u4e00-\u9fff]{2,20})的影响小于',
                r'与\1的相关性低于',
            ),
            # "对...的作用大于/小于" → "与...的相关性高于/低于"
            (
                r'对([\u4e00-\u9fff]{2,20})的作用大于',
                r'与\1的相关性高于',
            ),
            (
                r'对([\u4e00-\u9fff]{2,20})的作用小于',
                r'与\1的相关性低于',
            ),
            # "有助于缓解X" → "与X呈显著负相关"
            (
                r'有助于缓解([\u4e00-\u9fff]{2,10})',
                r'与\1呈显著负相关',
            ),
            # "证实X对Y的促进作用" → "表明X与Y的正相关关系"（X/Y为任意中文术语，适配任何研究主题）
            (
                r'证实([\u4e00-\u9fff]{2,10})对([\u4e00-\u9fff]{2,15})的(促进|推动|驱动|助推)作用',
                r'表明\1与\2的正相关关系',
            ),
            # "揭示X对Y的驱动作用" → "显示X与Y的正相关关系"（适配任何研究主题）
            (
                r'揭示([\u4e00-\u9fff]{2,10})对([\u4e00-\u9fff]{2,15})的(驱动|促进|推动|助推)作用',
                r'显示\1与\2的正相关关系',
            ),
            # "...促进作用弱于..." → "...正相关关系弱于..."（无"对...的"前缀的情况）
            (
                r'(促进|推动|驱动|助推)作用弱于',
                r'正相关关系弱于',
            ),
            # "...促进作用强于..." → "...正相关关系强于..."（无"对...的"前缀的情况）
            (
                r'(促进|推动|驱动|助推)作用强于',
                r'正相关关系强于',
            ),
            # "约为"比较句式 → "接近"（避免精确数值断言）
            (
                r'约为([\d.]+)',
                r'接近\1',
            ),
            # "X导致Y" → "X与Y存在相关关系"（通用因果断言改写，适配任何主题）
            (
                r'([\u4e00-\u9fff]{2,10})导致了([\u4e00-\u9fff]{2,10})的',
                r'\1与\2存在相关关系，体现在\2的',
            ),
            # "X引起Y" → "X与Y显著相关"
            (
                r'([\u4e00-\u9fff]{2,10})引起了([\u4e00-\u9fff]{2,10})',
                r'\1与\2显著相关',
            ),
            # "X决定Y" → "X与Y密切相关"
            (
                r'([\u4e00-\u9fff]{2,10})决定了([\u4e00-\u9fff]{2,10})',
                r'\1与\2密切相关',
            ),
            # "X使得Y" → "X与Y呈正相关"
            (
                r'([\u4e00-\u9fff]{2,10})使得([\u4e00-\u9fff]{2,10})',
                r'\1与\2呈正相关',
            ),
            # "X促使Y" → "X与Y呈正相关"
            (
                r'([\u4e00-\u9fff]{2,10})促使([\u4e00-\u9fff]{2,10})',
                r'\1与\2呈正相关',
            ),
            # 通用因果动词检测：推动/拉动/引发/诱发/造就/抑制/阻碍/削弱/加剧/恶化
            # 这些动词在实证论文中表达因果关系，应改为相关性表述
            # "X推动了Y" → "X与Y呈正相关"
            (
                r'([\u4e00-\u9fff]{2,10})推动了([\u4e00-\u9fff]{2,10})',
                r'\1与\2呈正相关',
            ),
            # "X拉动了Y" → "X与Y呈正相关"
            (
                r'([\u4e00-\u9fff]{2,10})拉动了([\u4e00-\u9fff]{2,10})',
                r'\1与\2呈正相关',
            ),
            # "X引发了Y" → "X与Y显著相关"
            (
                r'([\u4e00-\u9fff]{2,10})引发了([\u4e00-\u9fff]{2,10})',
                r'\1与\2显著相关',
            ),
            # "X诱发了Y" → "X与Y存在关联"
            (
                r'([\u4e00-\u9fff]{2,10})诱发了([\u4e00-\u9fff]{2,10})',
                r'\1与\2存在关联',
            ),
            # "X造就了Y" → "X与Y密切相关"
            (
                r'([\u4e00-\u9fff]{2,10})造就了([\u4e00-\u9fff]{2,10})',
                r'\1与\2密切相关',
            ),
            # "X抑制了Y" → "X与Y呈负相关"
            (
                r'([\u4e00-\u9fff]{2,10})抑制了([\u4e00-\u9fff]{2,10})',
                r'\1与\2呈负相关',
            ),
            # "X阻碍了Y" → "X与Y呈负相关"
            (
                r'([\u4e00-\u9fff]{2,10})阻碍了([\u4e00-\u9fff]{2,10})',
                r'\1与\2呈负相关',
            ),
            # "X削弱了Y" → "X与Y呈负相关"
            (
                r'([\u4e00-\u9fff]{2,10})削弱了([\u4e00-\u9fff]{2,10})',
                r'\1与\2呈负相关',
            ),
            # "X加剧了Y" → "X与Y呈正相关"
            (
                r'([\u4e00-\u9fff]{2,10})加剧了([\u4e00-\u9fff]{2,10})',
                r'\1与\2呈正相关',
            ),
            # "X恶化了Y" → "X与Y呈负相关"
            (
                r'([\u4e00-\u9fff]{2,10})恶化了([\u4e00-\u9fff]{2,10})',
                r'\1与\2呈负相关',
            ),
        ]
        _overreach_count = 0
        for pat, repl in _overreach_patterns:
            polished_full, _n = _re_clean.subn(pat, repl, polished_full)
            _overreach_count += _n
        if _overreach_count > 0:
            logger.info("Phase 8b 因果语言重写: %d 处异质性分析表述修正", _overreach_count)
            self.console.print(
                f"  [dim]因果语言重写: {_overreach_count} 处（促进作用→正相关）[/dim]"
            )

        # ---- 4g. 修改10c: 过渡词频率检测与去重 ----
        _TRANSITION_WORDS = [
            "从最基本的层面来看", "进一步来看", "还应注意",
            "更为关键的是", "需要关注的是", "需要指出的是",
            "值得注意的是", "不容忽视的是", "显而易见的是",
            "毋庸置疑的是", "不言而喻的是", "从现实层面来看",
            "从理论层面来看", "从实践层面来看", "从宏观层面来看",
            "从微观层面来看", "从整体来看", "从长远来看",
            "从短期来看", "在此基础上", "与此同时",
            "除此之外", "更重要的是", "更值得注意的是",
            "令人瞩目的是", "引人深思的是", "发人深省的是",
        ]
        # 通用过渡词模式：检测任何"从X来看/X层面来看/值得注意的是X的是"等模式
        # 动态化改造：减少对固定词表的依赖，通过模式匹配发现未知过渡词
        _transition_pattern = re.compile(
            r'(从[\u4e00-\u9fff]{2,8}来看|从[\u4e00-\u9fff]{2,8}层面来看|'
            r'[\u4e00-\u9fff]{2,6}的是[，,]|'
            r'需要[\u4e00-\u9fff]{1,6}的是|值得注意的是|'
            r'显而易见的是|毋庸置疑的是|不言而喻的是|'
            r'令人[\u4e00-\u9fff]{2,4}的是|'
            r'更为[\u4e00-\u9fff]{2,4}的是)'
        )

        # 收集所有检测到的过渡词（已知列表 + 通用模式动态发现）
        _all_transitions: set[str] = set(_TRANSITION_WORDS)
        for _m in _transition_pattern.finditer(polished_full):
            _all_transitions.add(_m.group(1))

        _transition_replaced = 0
        for tw in _all_transitions:
            count = polished_full.count(tw)
            if count > 2:
                # 从第3次出现开始替换为"此外"
                parts = polished_full.split(tw)
                # 保留前2次，后续替换
                result_parts = parts[:3]
                for p in parts[3:]:
                    result_parts.append("此外")
                    result_parts.append(p)
                polished_full = tw.join(result_parts[:3]) + "此外".join([""] + result_parts[3:])
                # 修正拼接
                polished_full = parts[0] + tw + parts[1] + tw + parts[2] + "此外".join(parts[3:])
                _transition_replaced += (count - 2)
        if _transition_replaced > 0:
            logger.info("Phase 8b 过渡词去重: 替换 %d 处超出频率的过渡词", _transition_replaced)
            self.console.print(
                f"  [dim]过渡词去重: 替换 {_transition_replaced} 处[/dim]"
            )

        # ---- 4h. 修改11: 跨章节一致性校验 ----
        # 11a: 结构章数统一——从outline获取实际章节数
        try:
            outline_data = self.file_manager.load_state(self.project_dir) or {}
            outline_json_path = self.project_dir / "outline.json"
            actual_chapters = 0
            if outline_json_path.exists():
                oj = json.loads(outline_json_path.read_text(encoding="utf-8"))
                actual_chapters = len(oj.get("sections", []))
            if actual_chapters > 0:
                # 将"六章""七章"等替换为实际章数
                cn_nums = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
                actual_cn = next(k for k, v in cn_nums.items() if v == actual_chapters)
                for wrong_num, wrong_cn in [("六", "六"), ("七", "七"), ("八", "八")]:
                    if wrong_cn != actual_cn:
                        polished_full = polished_full.replace(
                            f"全文共分为{wrong_cn}章", f"全文共分为{actual_cn}章"
                        )
                        polished_full = polished_full.replace(
                            f"第{wrong_cn}章为结论", f"第{actual_cn}章为结论"
                        )
        except Exception as e:
            logger.debug("章节数统一失败: %s", e)

        # 11b: 样本量统一——取首次出现的数值为标准值
        try:
            import re as _re_sample
            sample_matches = _re_sample.findall(r'(\d{1,3}(?:,\d{3})+)\s*(?:个|个观测值|个样本|个公司)', polished_full)
            if len(set(sample_matches)) > 1:
                standard_sample = sample_matches[0] if sample_matches else ""
                if standard_sample:
                    for other_sample in set(sample_matches):
                        if other_sample != standard_sample:
                            polished_full = polished_full.replace(other_sample, standard_sample)
        except Exception as e:
            logger.debug("样本量统一失败: %s", e)

        # 11c: 变量命名统一——Dig_trans→DT, Inn_perf→Innovation
        try:
            import re as _re_var
            polished_full = _re_var.sub(r'\bDig_trans\b', 'DT', polished_full)
            polished_full = _re_var.sub(r'\bInn_perf\b', 'Innovation', polished_full)
            polished_full = _re_var.sub(r'\bDig_trans\b', 'DT', polished_full)
        except Exception as e:
            logger.debug("变量名统一失败: %s", e)

        # 11d: 年份窗口统一——从SPEC获取时间窗口
        try:
            spec_path = self.project_dir / "SPEC.md"
            if spec_path.exists():
                spec_text = spec_path.read_text(encoding="utf-8")
                import re as _re_year
                year_matches = _re_year.findall(r'(\d{4})\s*[-—到]\s*(\d{4})', spec_text)
                if year_matches:
                    spec_start, spec_end = year_matches[0]
                    # 统一正文中的年份范围
                    polished_full = _re_year.sub(
                        r'\d{4}[-—到]\d{4}',
                        f'{spec_start}-{spec_end}',
                        polished_full,
                    )
        except Exception as e:
            logger.debug("年份窗口统一失败: %s", e)

        # ---- 5. 保存 full_draft_polished.md（不覆盖原草稿）----
        polished_path = self.project_dir / "draft" / "full_draft_polished.md"
        try:
            polished_path.write_text(polished_full, encoding="utf-8")
            self.console.print(
                f"\n  [green]去AI味润色后草稿已保存: {polished_path}[/green]"
            )
        except Exception as e:
            logger.error("保存 full_draft_polished.md 失败: %s", e)
            self.console.print(f"  [red]保存润色后草稿失败: {e}[/red]")

        # ---- 6. 生成 deai_report.md（含前后风险对比）----
        try:
            risk_after = deai_engine.detect_ai_patterns(polished_full)
        except Exception as e:
            logger.error("处理后AI风险检测失败: %s", e)
            risk_after = risk_before  # 降级使用处理前的评估

        report = self._generate_deai_report(
            risk_before, risk_after, deai_results, total_polish_changes
        )
        report_path = self.project_dir / "draft" / "deai_report.md"
        try:
            report_path.write_text(report, encoding="utf-8")
            self.console.print(
                f"  [green]去AI味报告已保存: {report_path}[/green]"
            )
        except Exception as e:
            logger.error("保存 deai_report.md 失败: %s", e)
            self.console.print(f"  [red]保存报告失败: {e}[/red]")

        # 显示处理效果摘要
        self.console.print(
            f"\n  [cyan]处理后[/cyan] 风险等级: {risk_after.risk_level.value}, "
            f"AI生成概率: {risk_after.ai_probability:.1%}, "
            f"总体评分: {risk_after.overall_score:.1f}"
        )
        if risk_before.ai_probability > 0:
            improvement = (
                (risk_before.ai_probability - risk_after.ai_probability)
                / risk_before.ai_probability * 100
            )
        else:
            improvement = 0.0
        self.console.print(
            f"  [green]AI风险降低: {improvement:+.1f}%[/green]"
        )

        # ---- 7. 更新 state.json 记录去AI味和润色已完成 ----
        try:
            from datetime import datetime, timezone

            state = self.file_manager.load_state(self.project_dir) or {}
            state["deai_polish_completed"] = True
            state["deai_polish_at"] = datetime.now(timezone.utc).isoformat()
            state["deai_risk_before"] = {
                "level": risk_before.risk_level.value,
                "probability": risk_before.ai_probability,
                "score": risk_before.overall_score,
            }
            state["deai_risk_after"] = {
                "level": risk_after.risk_level.value,
                "probability": risk_after.ai_probability,
                "score": risk_after.overall_score,
            }
            state["deai_improvement"] = round(improvement, 1)
            state["deai_sections_processed"] = len(deai_results)
            state["deai_polish_changes"] = total_polish_changes
            self.file_manager.save_state(self.project_dir, state)
            logger.info("state.json 已更新：去AI味和润色完成")
        except Exception as e:
            logger.error("更新 state.json 失败: %s", e)
            self.console.print(f"  [yellow]更新状态文件失败: {e}[/yellow]")

    def _split_draft_for_deai(self, full_text: str) -> list[dict]:
        """将完整草稿拆分为章节列表，用于去AI味处理.

        按 ## 二级标题拆分；若无二级标题，则将整个文本作为单个章节处理。
        保留每章的标题行在内容中。

        Args:
            full_text: 完整草稿文本.

        Returns:
            章节字典列表，每项含 title 和 content.
        """
        lines = full_text.split("\n")
        sections: list[dict] = []
        current_title = "标题/前言"
        current_lines: list[str] = []

        for line in lines:
            # 匹配二级标题（## 开头，但不是 ### 或更深）
            if line.startswith("## ") and not line.startswith("### "):
                if current_lines:
                    sections.append({
                        "title": current_title,
                        "content": "\n".join(current_lines),
                    })
                current_title = line.lstrip("# ").strip()
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines:
            sections.append({
                "title": current_title,
                "content": "\n".join(current_lines),
            })

        return sections

    def _generate_deai_report(
        self,
        risk_before,
        risk_after,
        deai_results: list,
        polish_changes: int,
    ) -> str:
        """生成去AI味与润色报告（Markdown格式）.

        包含整体风险评估对比、检测到的AI写作模式、各章节处理摘要、
        应用策略汇总、中文润色统计和总结建议。

        Args:
            risk_before: 处理前AI风险评估（AIRiskAssessment）.
            risk_after: 处理后AI风险评估（AIRiskAssessment）.
            deai_results: 各章节的去AI味处理结果列表（DeAIResult）.
            polish_changes: 中文润色修改总数.

        Returns:
            Markdown 格式的报告字符串.
        """
        import datetime as _dt

        lines: list[str] = []

        lines.append("# ScholarPilot 去AI味与润色报告")
        lines.append("")
        lines.append(
            f"> 生成时间: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        lines.append("")

        # 一、整体AI风险评估对比
        lines.append("## 一、整体AI风险评估对比")
        lines.append("")
        lines.append("| 指标 | 处理前 | 处理后 | 变化 |")
        lines.append("| --- | --- | --- | --- |")
        lines.append(
            f"| 风险等级 | {risk_before.risk_level.value} | "
            f"{risk_after.risk_level.value} | "
            f"{'降低' if risk_after.risk_level.value != risk_before.risk_level.value else '未变'} |"
        )
        lines.append(
            f"| AI生成概率 | {risk_before.ai_probability:.1%} | "
            f"{risk_after.ai_probability:.1%} | "
            f"{(risk_after.ai_probability - risk_before.ai_probability):+.1%} |"
        )
        lines.append(
            f"| 总体AI特征评分 | {risk_before.overall_score:.1f} | "
            f"{risk_after.overall_score:.1f} | "
            f"{(risk_after.overall_score - risk_before.overall_score):+.1f} |"
        )
        lines.append("")

        # 二、检测到的AI写作模式
        lines.append("## 二、检测到的AI写作模式")
        lines.append("")
        lines.append("### 处理前检测到的模式")
        lines.append("")
        if risk_before.detected_patterns:
            for pattern in risk_before.detected_patterns:
                still = "仍存在" if pattern in risk_after.detected_patterns else "已消除"
                lines.append(f"- {pattern} —— {still}")
        else:
            lines.append("- 未检测到明显的AI写作模式")
        lines.append("")
        lines.append("### 处理后检测到的模式")
        lines.append("")
        if risk_after.detected_patterns:
            for pattern in risk_after.detected_patterns:
                lines.append(f"- {pattern}")
        else:
            lines.append("- 未检测到明显的AI写作模式")
        lines.append("")

        # 三、各章节处理摘要
        lines.append("## 三、各章节处理摘要")
        lines.append("")
        if deai_results:
            lines.append("| 章节 | 应用策略数 | 修改数 | 改善幅度 |")
            lines.append("| --- | --- | --- | --- |")
            for idx, result in enumerate(deai_results, 1):
                lines.append(
                    f"| 章节{idx} | {len(result.strategies_applied)} | "
                    f"{len(result.changes)} | {result.improvement:+.1f}% |"
                )
            lines.append("")

            # 策略汇总
            strategy_counts: dict[str, int] = {}
            for result in deai_results:
                for s in result.strategies_applied:
                    name = s.value if hasattr(s, "value") else str(s)
                    strategy_counts[name] = strategy_counts.get(name, 0) + 1
            if strategy_counts:
                lines.append("### 应用策略汇总")
                lines.append("")
                lines.append("| 策略 | 使用次数 |")
                lines.append("| --- | --- |")
                for name, count in sorted(
                    strategy_counts.items(), key=lambda x: -x[1]
                ):
                    lines.append(f"| {name} | {count} |")
                lines.append("")
        else:
            lines.append("无章节处理结果。")
            lines.append("")

        # 四、中文润色统计
        lines.append("## 四、中文润色统计")
        lines.append("")
        lines.append(f"- 中文润色修改总数: {polish_changes}")
        lines.append("")

        # 五、总结与建议
        lines.append("## 五、总结与建议")
        lines.append("")
        if risk_before.ai_probability > 0:
            improvement = (
                (risk_before.ai_probability - risk_after.ai_probability)
                / risk_before.ai_probability * 100
            )
        else:
            improvement = 0.0

        if improvement > 30:
            lines.append("去AI味效果显著，AI风险已大幅降低。")
        elif improvement > 10:
            lines.append("去AI味效果较好，AI风险有所降低，建议进一步优化。")
        elif improvement > 0:
            lines.append("去AI味效果有限，建议尝试更多策略组合。")
        else:
            lines.append("去AI味效果不明显，建议人工复核或调整策略。")
        lines.append("")

        if risk_after.detected_patterns:
            lines.append("**残留问题及建议**:")
            lines.append("")
            if "句式单一性" in risk_after.detected_patterns:
                lines.append("- 进一步调整句式长度分布，制造长短交替")
            if "套路化过渡词" in risk_after.detected_patterns:
                lines.append("- 替换或删除残留的套路化过渡词")
            if "过度对仗排比" in risk_after.detected_patterns:
                lines.append("- 打破残留的对称排比结构")
            if "过度精确表述" in risk_after.detected_patterns:
                lines.append("- 将过度精确的数据改为约数表述")
            if "机械的三段式结构" in risk_after.detected_patterns:
                lines.append("- 打破残留的三段式结构")
            lines.append("")

        lines.append("---")
        lines.append("*本报告由 ScholarPilot 去AI味引擎与润色引擎自动生成*")

        return "\n".join(lines)

    # ===== Phase 8c: Claim 校准 =====

    async def _phase8c_claim_calibration(self) -> None:
        """Phase 8c: Claim 校准（Actor-Critic 双代理模式）.

        在去AI味处理后，对论文中的核心结论句进行逐条校准：
        1. 读取润色后的全文（full_draft_polished.md，回退到 full_draft.md）
        2. 提取每章核心结论句（识别"因此""综上""研究表明"等标记）
        3. 逐条校准结论与证据的匹配关系
        4. 对"结论越界"判断增加 Actor-Critic 二次确认
        5. 生成 claim_calibration_report.md
        6. 更新 state.json 记录校准结果

        报告作为"建议"而非"强制修改"，不自动改正文。
        异常处理：校准失败不中断主流程，仅记录日志。
        """
        from rich.panel import Panel

        self.console.print(
            Panel(
                "[bold cyan]Claim 校准[/bold cyan]\n"
                "提取核心结论 → 逐条校准证据匹配 → 识别结论越界 → 生成报告",
                title="Phase 8c",
                border_style="cyan",
            )
        )

        # 非交互模式判断
        if not self.non_interactive:
            from rich.prompt import Confirm

            try:
                should_run = Confirm.ask(
                    "是否执行 Claim 校准（结论-证据匹配校验）？",
                    default=True,
                )
            except Exception:
                should_run = True
            if not should_run:
                self.console.print("[yellow]已跳过 Claim 校准[/yellow]")
                return
        else:
            self.console.print("  [dim][非交互模式] 自动执行 Claim 校准[/dim]")

        # 读取润色后的全文（优先 polished，回退到原始草稿）
        polished_path = self.project_dir / "draft" / "full_draft_polished.md"
        draft_path = self.project_dir / "draft" / "full_draft.md"

        full_text = ""
        source_label = ""
        if polished_path.exists():
            full_text = polished_path.read_text(encoding="utf-8")
            source_label = "full_draft_polished.md"
        elif draft_path.exists():
            full_text = draft_path.read_text(encoding="utf-8")
            source_label = "full_draft.md"

        # 读取后立即清洗标点（防御性：避免 ；。 残留进入 Claim 校准）
        # 使用 while 循环反复清洗，与 Phase 8b 保持一致，确保彻底清除 `；。。` 这类残留。
        import re as _re_clean
        _c8c_sp_total = 0
        while True:
            full_text, _n = _re_clean.subn(r"；。\s*", "；", full_text)
            _c8c_sp_total += _n
            if _n == 0:
                break
        full_text = _re_clean.sub(r"。。+", "。", full_text)
        full_text = _re_clean.sub(r"；；+", "；", full_text)
        if _c8c_sp_total > 0:
            logger.info(
                "Phase 8c 标点清洗: %s 读取后清除 %d 处 ；。残留",
                source_label, _c8c_sp_total,
            )

        if not full_text.strip():
            self.console.print("[yellow]草稿文件不存在或为空，跳过 Claim 校准[/yellow]")
            logger.warning("草稿为空，跳过 Phase 8c")
            return

        self.console.print(f"  [dim]读取源文件: {source_label}[/dim]")
        self._emit("post_processing", "progress", f"Claim 校准: 正在从 {source_label} 提取核心结论...")

        # 收集参考文献信息（用于校准时交叉验证）
        references: list[dict[str, Any]] = []
        ref_path = self.project_dir / "draft" / "references.md"
        if ref_path.exists():
            ref_text = ref_path.read_text(encoding="utf-8")
            for line in ref_text.split("\n"):
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("---") or len(line) < 10:
                    continue
                # 解析参考文献行，提取结构化信息
                # 格式: [N] 作者：标题，《期刊》，年份。
                import re as _re
                ref_match = _re.match(r'\[(\d+)\]\s*(.+)', line)
                if ref_match:
                    ref_num = ref_match.group(1)
                    ref_content = ref_match.group(2)
                    # 提取年份
                    year_match = _re.search(r'(\d{4})年?', ref_content)
                    year = year_match.group(1) if year_match else ""
                    # 提取作者（冒号前的部分）
                    author_part = ref_content.split("：")[0] if "：" in ref_content else ref_content.split(",")[0] if "," in ref_content else ""
                    # 提取标题（冒号后到《或"前）
                    title_part = ""
                    if "：" in ref_content:
                        after_colon = ref_content.split("：", 1)[1]
                        # 标题到《或"或.前
                        for sep in ["《", '"', "'", "."]:
                            if sep in after_colon:
                                title_part = after_colon.split(sep)[0].strip()
                                break
                        if not title_part:
                            title_part = after_colon[:50].strip()
                    references.append({
                        "id": ref_num,
                        "text": ref_content,
                        "authors": author_part.strip(),
                        "year": year,
                        "title": title_part.strip(),
                    })

        # 收集证据矩阵数据（用于交叉验证）
        evidence_matrix_data: dict[str, Any] | None = None
        matrix_path = self.project_dir / ".scholar" / "evidence_matrix.json"
        if matrix_path.exists():
            try:
                evidence_matrix_data = json.loads(
                    matrix_path.read_text(encoding="utf-8")
                )
                self.console.print(
                    f"  [dim]已加载证据矩阵数据（{evidence_matrix_data.get('total_papers', 0)} 篇文献）[/dim]"
                )
            except Exception as e:
                logger.debug("加载证据矩阵数据失败: %s", e)

        # 初始化 Claim 校准器
        try:
            from scholarpilot.tools.claim_calibrator import ClaimCalibrator
        except ImportError as e:
            logger.error("导入 Claim 校准模块失败: %s", e)
            self.console.print(f"[red]导入 Claim 校准模块失败: {e}[/red]")
            return

        calibrator = ClaimCalibrator(
            llm=self.llm,
            evidence_matrix_data=evidence_matrix_data,
        )

        # 执行校准
        self.console.print("[dim]🔍 正在校准核心结论（逐章提取+逐条校验）...[/dim]")
        try:
            report = await calibrator.calibrate_document(
                full_text=full_text,
                references=references,
            )
        except Exception as e:
            logger.error("Claim 校准失败: %s", e, exc_info=True)
            self.console.print(f"[red]Claim 校准失败: {e}[/red]")
            return

        # 输出统计
        self.console.print(f"  [green]Claim 校准完成: {report.total_claims} 条结论[/green]")
        self.console.print(
            f"  [dim]充分支撑: {report.supported} | 部分支撑: {report.partial} | "
            f"结论越界: {report.overreach} | 无引用: {report.unsupported}[/dim]"
        )
        self.console.print(
            f"  [dim]诚信评分: {report.overall_integrity_score}/100[/dim]"
        )

        if report.critical_issues:
            self.console.print(f"  [yellow]严重问题: {len(report.critical_issues)} 项[/yellow]")
            for issue in report.critical_issues[:5]:  # 最多显示5条
                self.console.print(f"    [red]• {issue}[/red]")
            if len(report.critical_issues) > 5:
                self.console.print(f"    [dim]...还有 {len(report.critical_issues) - 5} 项，详见报告[/dim]")

        # 修改18: 无引用支撑结论补充
        if report.unsupported > 0:
            self.console.print(
                f"  [dim]🔧 检测到 {report.unsupported} 条无引用支撑结论，尝试补充引用...[/dim]"
            )
            try:
                # 从文献池搜索相关论文
                literature_pool_18: list[dict] = []
                try:
                    project_papers = self.library.get_project_papers(self.project_name)
                    if project_papers:
                        literature_pool_18 = project_papers
                except Exception:
                    pass

                if literature_pool_18:
                    # 对每条无引用支撑结论，搜索文献池中的相关论文
                    supplement_count = 0
                    for claim in report.claims:
                        if claim.evidence_level == "unsupported":
                            # 提取结论关键词
                            claim_text = claim.text if hasattr(claim, 'text') else str(claim)
                            claim_keywords = set()
                            import re as _re_18
                            for kw in _re_18.findall(r'[\u4e00-\u9fff]{2,6}', claim_text):
                                if len(kw) >= 2:
                                    claim_keywords.add(kw)

                            # 在文献池中搜索相关论文
                            best_match = None
                            best_score = 0
                            for paper in literature_pool_18:
                                if not isinstance(paper, dict):
                                    continue
                                paper_text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
                                score = sum(1 for kw in claim_keywords if kw in paper_text)
                                if score > best_score:
                                    best_score = score
                                    best_match = paper

                            if best_match and best_score > 0:
                                # 追加引用到结论句
                                best_author = best_match.get("authors", ["未知"])[0] if best_match.get("authors") else "未知"
                                best_year = str(best_match.get("year", ""))
                                if best_author and best_year:
                                    # 在原文中找到结论句并追加引用
                                    if claim_text in full_text:
                                        cited_claim = f"{claim_text}（{best_author}，{best_year}）"
                                        full_text = full_text.replace(claim_text, cited_claim, 1)
                                        supplement_count += 1
                                        logger.info(
                                            "结论补充: 为无引用结论添加了引用 %s（%s）",
                                            best_author, best_year,
                                        )

                    if supplement_count > 0:
                        self.console.print(
                            f"  [green]✓ 为 {supplement_count} 条无引用结论补充了文献引用[/green]"
                        )
                        # 更新全文
                        if polished_path.exists():
                            polished_path.write_text(full_text, encoding="utf-8")
                    else:
                        self.console.print(
                            "  [yellow]⚠️ 未找到匹配文献，建议手动补充引用或降级因果表述[/yellow]"
                        )
                else:
                    self.console.print(
                        "  [yellow]⚠️ 文献池为空，无法自动补充引用[/yellow]"
                    )
            except Exception as e:
                logger.warning("结论补充失败: %s", e)

        # 生成报告文件
        try:
            report_md = calibrator.to_markdown(report)
            report_path = self.project_dir / "draft" / "claim_calibration_report.md"
            report_path.write_text(report_md, encoding="utf-8")
            self.console.print(f"  [dim]已保存报告: {report_path}[/dim]")
        except Exception as e:
            logger.warning("Claim 校准报告保存失败: %s", e)
            self.console.print(f"  [yellow]报告保存失败: {e}[/yellow]")

        # 更新 state.json
        try:
            from datetime import datetime, timezone

            state = self.file_manager.load_state(self.project_dir) or {}
            state["claim_calibration_completed"] = True
            state["claim_calibration_at"] = datetime.now(timezone.utc).isoformat()
            state["claim_calibration_summary"] = {
                "total_claims": report.total_claims,
                "supported": report.supported,
                "overreach": report.overreach,
                "unsupported": report.unsupported,
                "partial": report.partial,
                "integrity_score": report.overall_integrity_score,
                "critical_issues_count": len(report.critical_issues),
                "source_file": source_label,
            }
            self.file_manager.save_state(self.project_dir, state)
            logger.info("state.json 已更新：Claim 校准完成")
        except Exception as e:
            logger.error("更新 state.json 失败: %s", e)
            self.console.print(f"  [yellow]更新状态文件失败: {e}[/yellow]")

    def _phase8_post_completion(self) -> None:
        """Phase 8 后处理：质量报告 + 导出建议 + 实证工具提示."""
        from rich.panel import Panel

        # 1. 生成并显示质量报告
        try:
            report = self.generate_quality_report()
            self._display_quality_report(report)
        except Exception as e:
            logger.warning(f"质量报告生成失败: {e}")

        # 2. 实证论文工具提示
        is_empirical = (
            self.topic_info.get("research_type") == "empirical"
            if hasattr(self, "topic_info") and self.topic_info
            else False
        )

        if is_empirical:
            self.console.print(
                Panel(
                    "[bold]实证研究工具提示[/bold]\n\n"
                    "[cyan]代码模板[/cyan] — 生成 Stata/R/Python 实证分析代码骨架:\n"
                    f"  scholarpilot code {self.project_dir.name} --lang stata\n\n"
                    "[cyan]数据预处理[/cyan] — 缺失值检测、缩尾处理、清洗报告:\n"
                    f"  scholarpilot preprocess {self.project_dir.name} --data data/your_data.csv\n\n"
                    "[cyan]统计分析[/cyan] — 描述性统计、回归、VIF检验:\n"
                    f"  scholarpilot stats {self.project_dir.name} --dep <Y> --indep <X1,X2>\n\n"
                    "[cyan]计量诊断[/cyan] — VIF/Hausman/异方差/单位根检验:\n"
                    f"  scholarpilot diagnose {self.project_dir.name} --dep <Y> --indep <X1,X2> --entity <id> --time <year>\n\n"
                    "[cyan]机制分析[/cyan] — 中介效应/调节效应分析:\n"
                    f"  scholarpilot mechanism {self.project_dir.name} --x <X> --y <Y> --mediator <M>\n\n"
                    "[cyan]数据源指南[/cyan] — 匹配变量到CSMAR/Wind等数据源:\n"
                    f"  scholarpilot datasource {self.project_dir.name}\n\n"
                    "[cyan]科研绘图[/cyan] — 分布图/系数图/热力图:\n"
                    f"  scholarpilot plot {self.project_dir.name} --type distribution",
                    title="实证工具",
                    border_style="blue",
                )
            )

        # 3. 检测 data/ 文件夹中的用户数据
        data_dir = self.project_dir / "data"
        if data_dir.exists():
            data_files = list(data_dir.glob("*.csv")) + list(data_dir.glob("*.xlsx"))
            if data_files:
                self.console.print(
                    f"\n[green]✓ 检测到数据文件: {data_files[0].name}[/green]\n"
                    f"[dim]  运行统计分析: scholarpilot stats {self.project_dir.name}[/dim]"
                )

        # 4. 导出建议
        self.console.print(
            Panel(
                "[bold]导出选项[/bold]\n\n"
                f"  scholarpilot export {self.project_dir.name} -f docx   # Word格式\n"
                f"  scholarpilot export {self.project_dir.name} -f pdf    # PDF格式\n"
                f"  scholarpilot export {self.project_dir.name} -f latex  # LaTeX格式\n"
                f"  scholarpilot export {self.project_dir.name} -f md     # Markdown格式\n\n"
                "[dim]定稿命令（重新生成摘要+引用管理）:[/dim]\n"
                f"  scholarpilot finalize {self.project_dir.name}",
                title="下一步",
                border_style="green",
            )
        )
