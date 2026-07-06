"""Paragraph Editor - 段落级交互编辑器.

解决科研写作中最高频的操作：反复打磨某一段文字。

科研工作者的真实写作流程不是"一键生成整章"，而是：
1. 生成初稿后，通读全文
2. 发现某段论证不够有力 → 选中该段 → "加强论证"
3. 发现某段太啰嗦 → 选中该段 → "精简"
4. 发现过渡生硬 → 选中该段 → "改善衔接"
5. 想换个说法 → 选中该段 → 输入自定义要求

每次编辑只改目标段落，不动其他部分。修改前自动创建版本快照。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from scholarpilot.config import get_settings
from scholarpilot.context.engine import ContextEngine
from scholarpilot.context.memory import ProjectMemory
from scholarpilot.context.profile import ResearcherProfile
from scholarpilot.llm.gateway import LLMGateway
from scholarpilot.utils.file_manager import FileManager

logger = logging.getLogger(__name__)
console = Console()


# 编辑操作类型及其描述
EDIT_OPERATIONS = {
    "1": ("expand", "扩写", "在保持原意的基础上扩展论述，增加论证深度和细节"),
    "2": ("condense", "精简", "删除冗余表述，保留核心论点"),
    "3": ("rephrase", "改写", "换一种表述方式，保持原意不变，改善表达"),
    "4": ("strengthen", "加强论证", "补充逻辑链条，增加因果论证，使论述更有说服力"),
    "5": ("tone", "调整语气", "调整为更学术/更客观/更严谨的语气"),
    "6": ("transition", "改善衔接", "优化与前后段的过渡，使逻辑更流畅"),
    "7": ("custom", "自定义", "输入你的具体修改要求"),
}


class ParagraphEditor:
    """段落级交互编辑器.

    Usage:
        editor = ParagraphEditor(project_dir)
        await editor.edit_session()

    交互流程:
        1. 选择章节
        2. 查看段落列表（带编号和预览）
        3. 选择要编辑的段落编号
        4. 选择编辑操作（扩写/精简/改写/...）
        5. Agent 生成修改后的段落
        6. 研究者预览对比，决定接受/重试/放弃
        7. 可以继续编辑同一段或其他段，或退出
    """

    def __init__(self, project_dir: Path) -> None:
        """初始化段落编辑器.

        Args:
            project_dir: 论文项目目录。
        """
        self.project_dir = project_dir
        self.config = get_settings()
        self.file_manager = FileManager(self.config.projects_dir)
        self.memory = ProjectMemory(project_dir / ".scholar" / "memory.json")
        profile_path = self.config.user_home_dir / "profile.json"
        self.profile = ResearcherProfile(profile_path)
        self.context_engine = ContextEngine(self.memory, self.profile)
        self.llm = LLMGateway(self.config)

        # 从项目记忆加载论文信息
        self.topic_info = self.memory.get("topic_analysis", {}) or {}
        self.paper_title = self._get_paper_title()

    def _get_paper_title(self) -> str:
        """获取论文标题."""
        meta = self.file_manager.get_project_meta(self.project_dir) or {}
        title = meta.get("title", "")
        if not title:
            title = self.topic_info.get("topic", "未命名论文")
        return title

    async def edit_session(self) -> None:
        """启动交互式编辑会话.

        这是主入口，研究者进入后会看到章节列表，选择章节后进入段落编辑。
        """
        console.print(
            Panel(
                f"[bold cyan]段落级编辑器[/bold cyan]\n"
                f"论文: {self.paper_title}\n"
                f"项目: {self.project_dir.name}",
                title="✍️ ScholarPilot Editor",
            )
        )

        while True:
            # Step 1: 选择章节
            section_name = self._select_section()
            if section_name is None:
                break

            # Step 2: 进入该章节的段落编辑循环
            await self._edit_section_loop(section_name)

        console.print("[dim]编辑会话结束[/dim]")

    def _select_section(self) -> str | None:
        """选择要编辑的章节.

        Returns:
            章节名称，取消则返回 None。
        """
        sections = self.file_manager.list_sections(self.project_dir)
        if not sections:
            console.print("[yellow]暂无章节可编辑，请先生成论文初稿[/yellow]")
            return None

        console.print("\n[bold]选择要编辑的章节:[/bold]")
        table = Table(show_header=True)
        table.add_column("#", style="dim")
        table.add_column("章节", style="cyan")
        table.add_column("段落数", style="green")
        table.add_column("字数", style="dim")

        for i, name in enumerate(sections, 1):
            paragraphs = self.file_manager.get_paragraphs(self.project_dir, name)
            char_count = sum(p.get("char_count", 0) for p in paragraphs)
            table.add_row(str(i), name, str(len(paragraphs)), str(char_count))

        console.print(table)

        choice = Prompt.ask(
            "\n输入章节编号（q 退出）",
            default="q",
        )

        if choice.lower() == "q":
            return None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(sections):
                return sections[idx]
        except ValueError:
            pass

        console.print("[red]无效选择[/red]")
        return None

    async def _edit_section_loop(self, section_name: str) -> None:
        """单个章节的段落编辑循环."""
        while True:
            # 获取段落列表
            paragraphs = self.file_manager.get_paragraphs(self.project_dir, section_name)
            if not paragraphs:
                console.print("[yellow]该章节无内容[/yellow]")
                return

            # 显示段落列表
            self._display_paragraphs(section_name, paragraphs)

            # 选择段落
            choice = Prompt.ask(
                "\n输入要编辑的段落编号（r 刷新，b 返回选章，q 退出）",
                default="b",
            )

            if choice.lower() == "q":
                console.print("[dim]编辑会话结束[/dim]")
                exit(0)
            elif choice.lower() == "b":
                return
            elif choice.lower() == "r":
                continue

            try:
                para_idx = int(choice)
                # 找到对应段落
                target = None
                for p in paragraphs:
                    if p["index"] == para_idx:
                        target = p
                        break

                if not target:
                    console.print(f"[red]段落 {para_idx} 不存在[/red]")
                    continue

                if not target.get("editable", True):
                    console.print(f"[yellow]段落 {para_idx} 是{target['type']}类型，跳过[/yellow]")
                    continue

                # 进入段落编辑
                await self._edit_paragraph(section_name, target, paragraphs)

            except ValueError:
                console.print("[red]请输入数字[/red]")

    def _display_paragraphs(self, section_name: str, paragraphs: list[dict[str, Any]]) -> None:
        """显示段落列表."""
        console.print(f"\n[bold cyan]━━━ {section_name} 的段落 ━━━[/bold cyan]")

        table = Table(show_header=True, title=f"共 {len(paragraphs)} 个段落")
        table.add_column("#", style="dim", width=4)
        table.add_column("类型", style="yellow", width=6)
        table.add_column("字数", style="green", width=6)
        table.add_column("内容预览", style="white")

        for p in paragraphs:
            type_icon = {"heading": "标题", "body": "正文", "table": "表格", "code": "代码", "quote": "引用"}
            icon = type_icon.get(p["type"], p["type"])
            editable = "" if p.get("editable", True) else " [dim](不可编辑)[/dim]"
            preview = p["preview"]
            table.add_row(
                str(p["index"]),
                icon,
                str(p["char_count"]),
                preview + editable,
            )

        console.print(table)

    async def _edit_paragraph(
        self,
        section_name: str,
        paragraph: dict[str, Any],
        all_paragraphs: list[dict[str, Any]],
    ) -> None:
        """编辑单个段落.

        流程：选择操作 → 生成修改 → 预览对比 → 接受/重试/放弃
        """
        para_idx = paragraph["index"]
        original_content = paragraph["content"]

        # 显示当前段落全文
        console.print(
            Panel(
                original_content,
                title=f"[bold]段落 {para_idx}（{paragraph['char_count']}字）[/bold]",
                border_style="blue",
            )
        )

        # 选择编辑操作
        console.print("\n[bold]选择编辑操作:[/bold]")
        for key, (op_code, op_name, op_desc) in EDIT_OPERATIONS.items():
            console.print(f"  [cyan]{key}[/cyan]. {op_name} - [dim]{op_desc}[/dim]")

        choice = Prompt.ask("\n选择操作编号", default="7")

        if choice not in EDIT_OPERATIONS:
            console.print("[red]无效选择[/red]")
            return

        op_code, op_name, _ = EDIT_OPERATIONS[choice]

        # 获取自定义指令
        edit_instruction = ""
        if op_code == "custom":
            edit_instruction = Prompt.ask("输入你的修改要求")
        else:
            # 对于预设操作，允许补充具体要求
            extra = Prompt.ask("补充要求（可选，直接回车跳过）", default="")
            if extra:
                edit_instruction = extra

        # 获取章节完整内容（供 Agent 理解上下文）
        full_section = self.file_manager.load_section(self.project_dir, section_name) or ""

        # 获取章节标题
        section_title = self._get_section_title_from_content(full_section)

        # 构建上下文并调用 LLM
        console.print(f"\n[dim]正在{op_name}...[/dim]")

        ctx = self.context_engine.build_paragraph_edit_context(
            paper_title=self.paper_title,
            section_title=section_title,
            full_section=full_section,
            paragraph_index=para_idx,
            target_paragraph=original_content,
            edit_type=op_code,
            edit_instruction=edit_instruction,
        )

        try:
            new_content = await self.llm.chat(
                messages=ctx.to_messages(),
                model=self.config.default_writing_model,
                temperature=0.6,
            )
        except Exception as e:
            console.print(f"[red]生成失败: {e}[/red]")
            return

        # 清理 LLM 可能添加的多余内容
        new_content = new_content.strip()
        # 去除可能的 markdown 代码块包裹
        if new_content.startswith("```"):
            lines = new_content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            new_content = "\n".join(lines).strip()

        # 预览对比
        self._show_comparison(original_content, new_content, para_idx)

        # 研究者决策
        action = Prompt.ask(
            "\n选择操作",
            choices=["accept", "retry", "discard"],
            default="accept",
        )

        if action == "accept":
            # 保存修改（自动创建版本快照）
            note = f"{op_name}" + (f": {edit_instruction}" if edit_instruction else "")
            result = self.file_manager.replace_paragraph(
                self.project_dir, section_name, para_idx, new_content,
                label=op_name,
                note=note,
            )
            if result:
                console.print(f"  [green]✓ 已保存修改（自动创建版本快照）[/green]")
                console.print(f"  [dim]字数: {paragraph['char_count']} → {len(new_content)}[/dim]")
            else:
                console.print(f"  [red]保存失败[/red]")

        elif action == "retry":
            # 重新生成（带上"上次不满意"的上下文）
            retry_feedback = Prompt.ask("告诉 Agent 上次哪里不满意", default="")
            edit_instruction = (edit_instruction + " " + retry_feedback).strip()
            # 递归调用自身重试
            paragraph["content"] = original_content  # 保持原文重试
            await self._edit_paragraph_with_retry(
                section_name, paragraph, full_section,
                op_code, op_name, edit_instruction,
            )

        elif action == "discard":
            console.print("[dim]已放弃修改[/dim]")

    async def _edit_paragraph_with_retry(
        self,
        section_name: str,
        paragraph: dict[str, Any],
        full_section: str,
        op_code: str,
        op_name: str,
        edit_instruction: str,
    ) -> None:
        """带反馈的重试编辑."""
        para_idx = paragraph["index"]
        original_content = paragraph["content"]
        section_title = self._get_section_title_from_content(full_section)

        console.print(f"\n[dim]正在重新{op_name}...[/dim]")

        ctx = self.context_engine.build_paragraph_edit_context(
            paper_title=self.paper_title,
            section_title=section_title,
            full_section=full_section,
            paragraph_index=para_idx,
            target_paragraph=original_content,
            edit_type=op_code,
            edit_instruction=edit_instruction,
        )

        try:
            new_content = await self.llm.chat(
                messages=ctx.to_messages(),
                model=self.config.default_writing_model,
                temperature=0.7,  # 略高温度增加多样性
            )
        except Exception as e:
            console.print(f"[red]生成失败: {e}[/red]")
            return

        new_content = new_content.strip()
        if new_content.startswith("```"):
            lines = new_content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            new_content = "\n".join(lines).strip()

        self._show_comparison(original_content, new_content, para_idx)

        action = Prompt.ask(
            "\n选择操作",
            choices=["accept", "discard"],
            default="accept",
        )

        if action == "accept":
            note = f"{op_name}（重试）" + (f": {edit_instruction}" if edit_instruction else "")
            result = self.file_manager.replace_paragraph(
                self.project_dir, section_name, para_idx, new_content,
                label=f"{op_name}（重试）",
                note=note,
            )
            if result:
                console.print(f"  [green]✓ 已保存修改[/green]")

        elif action == "discard":
            console.print("[dim]已放弃修改[/dim]")

    def _get_section_title_from_content(self, content: str) -> str:
        """从章节内容中提取标题（第一个 # 开头的行）."""
        for line in content.split("\n"):
            if line.startswith("#"):
                return line.lstrip("#").strip()
        return "未命名章节"

    def _show_comparison(self, original: str, modified: str, para_idx: int) -> None:
        """并排显示修改前后的段落内容."""
        console.print(f"\n[bold]━━━ 段落 {para_idx} 修改对比 ━━━[/bold]")

        # 原文
        console.print(
            Panel(
                original,
                title=f"[red]修改前（{len(original)}字）[/red]",
                border_style="red",
            )
        )

        # 修改后
        console.print(
            Panel(
                modified,
                title=f"[green]修改后（{len(modified)}字）[/green]",
                border_style="green",
            )
        )
