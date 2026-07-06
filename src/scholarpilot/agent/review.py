"""Review Handler - 审稿意见处理器.

解决投稿后最痛苦的流程：处理审稿意见 + 写回复函。

科研工作者的真实审稿修改流程：
1. 收到审稿意见（通常5-15条，major+minor混合）
2. 逐条理解"审稿人到底要我改什么"
3. 在论文中找到对应位置
4. 决定怎么改（采纳/部分采纳/委婉拒绝）
5. 执行修改
6. 写一份"审稿意见回复函"，逐条说明改了什么
7. 重新提交

当前 ScholarPilot 完全没有覆盖这个流程。本模块填补这个空白。
"""

from __future__ import annotations

import json
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


class ReviewHandler:
    """审稿意见处理器.

    工作流程:
        导入审稿意见 → Agent 逐条解析 → 研究者审核解析 →
        逐条修改论文 → 生成回复函

    Usage:
        handler = ReviewHandler(project_dir)
        await handler.handle_review_session()

    状态持久化:
        .scholar/review_state.json 存储审稿处理全过程状态，
        支持中断后恢复。
    """

    def __init__(self, project_dir: Path) -> None:
        """初始化审稿处理器.

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

        self.topic_info = self.memory.get("topic_analysis", {}) or {}
        self.paper_title = self._get_paper_title()

    def _get_paper_title(self) -> str:
        """获取论文标题."""
        meta = self.file_manager.get_project_meta(self.project_dir) or {}
        return meta.get("title", "") or self.topic_info.get("topic", "未命名论文")

    async def handle_review_session(self, action: str = "full") -> None:
        """启动审稿意见处理会话.

        Args:
            action: 处理阶段
                - "import": 仅导入审稿意见
                - "analyze": 解析审稿意见
                - "modify": 逐条修改
                - "respond": 生成回复函
                - "status": 查看处理状态
                - "full": 完整流程
        """
        if action == "status":
            self._show_status()
            return

        if action == "full":
            # 完整流程
            review_state = self.file_manager.load_review_state(self.project_dir)

            if not review_state:
                # Step 1: 导入审稿意见
                comments = await self._import_comments()
                if not comments:
                    return

                # Step 2: 解析
                await self._analyze_comments(comments)
                review_state = self.file_manager.load_review_state(self.project_dir)

            # Step 3: 逐条修改
            if review_state and review_state.get("comments"):
                await self._modify_loop(review_state)

            # Step 4: 生成回复函
            if review_state and review_state.get("comments"):
                await self._generate_response_letter()

        elif action == "import":
            comments = await self._import_comments()
            if comments:
                await self._analyze_comments(comments)

        elif action == "analyze":
            review_state = self.file_manager.load_review_state(self.project_dir)
            if review_state and review_state.get("raw_comments"):
                await self._analyze_comments(review_state["raw_comments"])
            else:
                console.print("[yellow]请先导入审稿意见[/yellow]")

        elif action == "modify":
            review_state = self.file_manager.load_review_state(self.project_dir)
            if review_state and review_state.get("comments"):
                await self._modify_loop(review_state)
            else:
                console.print("[yellow]请先导入并解析审稿意见[/yellow]")

        elif action == "respond":
            review_state = self.file_manager.load_review_state(self.project_dir)
            if review_state and review_state.get("comments"):
                await self._generate_response_letter()
            else:
                console.print("[yellow]请先导入并解析审稿意见[/yellow]")

    async def _import_comments(self) -> str | None:
        """导入审稿意见.

        支持两种方式：
        1. 直接粘贴文本
        2. 指定文件路径
        """
        console.print(
            Panel(
                "[bold]导入审稿意见[/bold]\n\n"
                "请选择导入方式：\n"
                "1. 直接粘贴文本\n"
                "2. 指定文件路径",
                title="📥 审稿意见导入",
            )
        )

        choice = Prompt.ask("选择导入方式", default="1")

        comments = ""
        if choice == "1":
            console.print("[dim]请粘贴审稿意见全文（输入空行结束）：[/dim]")
            lines = []
            while True:
                line = input()
                if line == "":
                    if lines:
                        break
                    continue
                lines.append(line)
            comments = "\n".join(lines)

        elif choice == "2":
            file_path = Prompt.ask("输入文件路径")
            try:
                comments = Path(file_path).read_text(encoding="utf-8")
            except Exception as e:
                console.print(f"[red]读取文件失败: {e}[/red]")
                return None

        if not comments.strip():
            console.print("[yellow]未输入审稿意见[/yellow]")
            return None

        # 保存审稿意见原文
        self.file_manager.import_review_comments(self.project_dir, comments)
        console.print(f"[green]✓ 已导入审稿意见（{len(comments)} 字符）[/green]")

        return comments

    async def _analyze_comments(self, raw_comments: str) -> None:
        """解析审稿意见，逐条拆分并定位.

        将非结构化的审稿意见文本转为结构化的 JSON 列表，
        每条包含：类型、类别、关联章节、修改建议等。
        """
        console.print("\n[bold cyan]━━━ 解析审稿意见 ━━━[/bold cyan]")
        console.print("[dim]正在逐条解析并定位到论文章节...[/dim]")

        # 准备论文结构信息
        sections = self.file_manager.list_sections(self.project_dir)
        paper_structure = "\n".join(f"- {s}" for s in sections)

        # 准备各章节内容摘要（取前200字）
        summaries = []
        for s in sections:
            content = self.file_manager.load_section(self.project_dir, s) or ""
            summary = content[:200].replace("\n", " ") + "..."
            summaries.append(f"### {s}\n{summary}")
        paper_summary = "\n\n".join(summaries)

        # 构建上下文并调用 LLM
        ctx = self.context_engine.build_review_analysis_context(
            review_comments=raw_comments,
            paper_structure=paper_structure,
            paper_summary=paper_summary,
        )

        try:
            response = await self.llm.chat(
                messages=ctx.to_messages(),
                model=self.config.default_writing_model,
                temperature=0.3,  # 低温度确保解析准确
            )
        except Exception as e:
            console.print(f"[red]解析失败: {e}[/red]")
            return

        # 解析 JSON
        comments_list = self._extract_json_from_response(response)
        if not comments_list:
            console.print("[red]解析结果格式异常，请重试[/red]")
            return

        # 保存审稿状态
        review_state = {
            "raw_comments": raw_comments,
            "comments": comments_list,
            "status": "analyzed",
            "total_comments": len(comments_list),
        }
        self.file_manager.save_review_state(self.project_dir, review_state)

        # 展示解析结果
        self._display_analyzed_comments(comments_list)

        # 统计
        major_count = sum(1 for c in comments_list if c.get("type") == "major")
        minor_count = sum(1 for c in comments_list if c.get("type") == "minor")
        question_count = sum(1 for c in comments_list if c.get("type") == "question")
        positive_count = sum(1 for c in comments_list if c.get("type") == "positive")

        console.print(
            f"\n[green]✓ 解析完成：共 {len(comments_list)} 条意见[/green]\n"
            f"  重大修改: {major_count} | 小修: {minor_count} | "
            f"疑问: {question_count} | 肯定: {positive_count}"
        )

    def _display_analyzed_comments(self, comments: list[dict[str, Any]]) -> None:
        """展示解析后的审稿意见."""
        type_labels = {
            "major": ("重大", "red"),
            "minor": ("小修", "yellow"),
            "question": ("疑问", "blue"),
            "positive": ("肯定", "green"),
        }
        difficulty_labels = {"easy": "简单", "medium": "中等", "hard": "困难"}

        for c in comments:
            type_label, color = type_labels.get(c.get("type", "minor"), ("其他", "white"))
            difficulty = difficulty_labels.get(c.get("difficulty", "medium"), "中等")

            console.print(
                Panel(
                    f"[{color}]类型: {type_label}[/{color}] | "
                    f"分类: {c.get('category', 'other')} | "
                    f"难度: {difficulty} | "
                    f"优先级: {c.get('priority', 2)}\n\n"
                    f"[bold]原文:[/bold] {c.get('original_text', '')}\n\n"
                    f"[bold]理解:[/bold] {c.get('understood_request', '')}\n\n"
                    f"[bold]位置:[/bold] {c.get('related_section', '')} - {c.get('related_paragraph_hint', '')}\n\n"
                    f"[bold]建议:[/bold] {c.get('suggested_action', '')}",
                    title=f"意见 #{c.get('id', '?')}",
                )
            )

    async def _modify_loop(self, review_state: dict[str, Any]) -> None:
        """逐条修改论文.

        对每条审稿意见：
        1. 显示意见详情
        2. 研究者决定处理方式（采纳修改/手动修改/拒绝并解释）
        3. 如果采纳，Agent 生成修改内容并定位到对应段落
        4. 研究者确认后应用修改
        5. 记录修改状态
        """
        comments = review_state.get("comments", [])

        console.print(
            Panel(
                f"[bold]逐条处理审稿意见[/bold]\n"
                f"共 {len(comments)} 条意见\n"
                f"已处理: {sum(1 for c in comments if c.get('status') == 'done')} | "
                f"待处理: {sum(1 for c in comments if c.get('status') != 'done')}",
                title="📝 审稿修改",
            )
        )

        for i, comment in enumerate(comments):
            if comment.get("status") == "done":
                continue

            # 显示当前意见
            console.print(f"\n[bold cyan]━━━ 意见 #{comment.get('id', i+1)} / {len(comments)} ━━━[/bold cyan]")
            console.print(f"[bold]原文:[/bold] {comment.get('original_text', '')}")
            console.print(f"[bold]理解:[/bold] {comment.get('understood_request', '')}")
            console.print(f"[bold]建议:[/bold] {comment.get('suggested_action', '')}")

            related_section = comment.get("related_section", "")
            console.print(f"[dim]关联章节: {related_section}[/dim]")

            # 研究者决定处理方式
            action = Prompt.ask(
                "\n如何处理",
                choices=["auto", "manual", "reject", "skip"],
                default="auto",
            )

            if action == "skip":
                continue

            if action == "auto":
                # Agent 自动修改
                await self._auto_modify_comment(comment, review_state)

            elif action == "manual":
                # 研究者手动修改，记录说明
                note = Prompt.ask("记录你的修改说明（供回复函使用）")
                comment["status"] = "done"
                comment["handling"] = "manual"
                comment["modification_note"] = note
                comment["modification_location"] = related_section

            elif action == "reject":
                # 拒绝修改，记录理由
                reason = Prompt.ask("输入拒绝理由（供回复函使用）")
                comment["status"] = "rejected"
                comment["handling"] = "rejected"
                comment["rejection_reason"] = reason

            # 保存状态
            self.file_manager.save_review_state(self.project_dir, review_state)

        # 统计完成情况
        done = sum(1 for c in comments if c.get("status") == "done")
        rejected = sum(1 for c in comments if c.get("status") == "rejected")
        pending = sum(1 for c in comments if c.get("status") not in ("done", "rejected"))

        console.print(
            f"\n[green]修改完成：已修改 {done} | 拒绝 {rejected} | 待处理 {pending}[/green]"
        )

    async def _auto_modify_comment(
        self,
        comment: dict[str, Any],
        review_state: dict[str, Any],
    ) -> None:
        """Agent 自动修改单条审稿意见.

        定位到对应章节的段落，调用 LLM 生成修改后的段落。
        """
        related_section = comment.get("related_section", "")

        # 尝试匹配章节名
        sections = self.file_manager.list_sections(self.project_dir)
        target_section = None
        for s in sections:
            if related_section and related_section in s:
                target_section = s
                break
        if not target_section and sections:
            target_section = sections[0]  # 默认第一个

        if not target_section:
            console.print("[yellow]无法定位章节，请手动修改[/yellow]")
            comment["status"] = "pending_manual"
            return

        # 获取段落
        paragraphs = self.file_manager.get_paragraphs(self.project_dir, target_section)
        if not paragraphs:
            console.print("[yellow]章节无内容[/yellow]")
            comment["status"] = "pending_manual"
            return

        # 显示段落供研究者选择
        console.print(f"\n[bold]章节 {target_section} 的段落:[/bold]")
        for p in paragraphs:
            if p.get("editable", True):
                console.print(f"  [{p['index']}] ({p['char_count']}字) {p['preview']}")

        para_choice = Prompt.ask(
            "选择要修改的段落编号（0=整章重写）",
            default=str(paragraphs[0]["index"]) if paragraphs else "0",
        )

        try:
            para_idx = int(para_choice)
        except ValueError:
            para_idx = 0

        suggested_action = comment.get("suggested_action", "")
        understood = comment.get("understood_request", "")

        if para_idx == 0:
            # 整章重写
            console.print("[dim]正在根据审稿意见重新生成整章...[/dim]")
            full_section = self.file_manager.load_section(self.project_dir, target_section) or ""

            # 使用段落编辑的上下文，但操作类型为 custom
            ctx = self.context_engine.build_paragraph_edit_context(
                paper_title=self.paper_title,
                section_title=related_section or target_section,
                full_section=full_section,
                paragraph_index=0,
                target_paragraph=full_section,
                edit_type="custom",
                edit_instruction=f"根据审稿意见修改：{understood}。具体要求：{suggested_action}",
            )

            try:
                new_content = await self.llm.chat(
                    messages=ctx.to_messages(),
                    model=self.config.default_writing_model,
                    temperature=0.5,
                )
            except Exception as e:
                console.print(f"[red]生成失败: {e}[/red]")
                comment["status"] = "pending_manual"
                return

            # 预览
            console.print(Panel(new_content[:500] + "...", title="[green]修改后（预览）[/green]"))

            if Confirm.ask("接受修改？", default=True):
                self.file_manager.save_section_with_version(
                    self.project_dir, target_section, new_content,
                    label="审稿修改",
                    note=f"审稿意见 #{comment.get('id')}: {understood[:50]}",
                )
                comment["status"] = "done"
                comment["handling"] = "auto"
                comment["modification_location"] = target_section
                comment["modification_note"] = suggested_action
                console.print("[green]✓ 已修改[/green]")
            else:
                comment["status"] = "pending_manual"

        else:
            # 段落级修改
            target_para = None
            for p in paragraphs:
                if p["index"] == para_idx:
                    target_para = p
                    break

            if not target_para:
                console.print(f"[red]段落 {para_idx} 不存在[/red]")
                comment["status"] = "pending_manual"
                return

            full_section = self.file_manager.load_section(self.project_dir, target_section) or ""

            ctx = self.context_engine.build_paragraph_edit_context(
                paper_title=self.paper_title,
                section_title=related_section or target_section,
                full_section=full_section,
                paragraph_index=para_idx,
                target_paragraph=target_para["content"],
                edit_type="custom",
                edit_instruction=f"根据审稿意见修改此段落：{understood}。具体要求：{suggested_action}",
            )

            console.print(f"[dim]正在修改段落 {para_idx}...[/dim]")

            try:
                new_content = await self.llm.chat(
                    messages=ctx.to_messages(),
                    model=self.config.default_writing_model,
                    temperature=0.5,
                )
            except Exception as e:
                console.print(f"[red]生成失败: {e}[/red]")
                comment["status"] = "pending_manual"
                return

            # 清理
            new_content = new_content.strip()
            if new_content.startswith("```"):
                lines = new_content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                new_content = "\n".join(lines).strip()

            # 预览对比
            console.print(Panel(target_para["content"], title=f"[red]修改前（段落{para_idx}）[/red]", border_style="red"))
            console.print(Panel(new_content, title="[green]修改后[/green]", border_style="green"))

            if Confirm.ask("接受修改？", default=True):
                self.file_manager.replace_paragraph(
                    self.project_dir, target_section, para_idx, new_content,
                    label="审稿修改",
                    note=f"审稿意见 #{comment.get('id')}: {understood[:50]}",
                )
                comment["status"] = "done"
                comment["handling"] = "auto"
                comment["modification_location"] = f"{target_section} 段落{para_idx}"
                comment["modification_note"] = suggested_action
                console.print("[green]✓ 已修改[/green]")
            else:
                comment["status"] = "pending_manual"

    async def _generate_response_letter(self) -> None:
        """生成审稿意见回复函."""
        console.print("\n[bold cyan]━━━ 生成审稿意见回复函 ━━━[/bold cyan]")

        review_state = self.file_manager.load_review_state(self.project_dir)
        if not review_state:
            console.print("[yellow]无审稿处理记录[/yellow]")
            return

        comments = review_state.get("comments", [])

        # 准备记录文本
        records = []
        for c in comments:
            status = c.get("status", "pending")
            handling = c.get("handling", "")
            location = c.get("modification_location", "")
            note = c.get("modification_note", "")
            reason = c.get("rejection_reason", "")

            record = f"意见 #{c.get('id')}\n"
            record += f"原文: {c.get('original_text', '')}\n"
            record += f"类型: {c.get('type', '')}\n"
            record += f"处理状态: {status}\n"
            if handling == "auto":
                record += f"修改方式: Agent自动修改\n"
                record += f"修改位置: {location}\n"
                record += f"修改说明: {note}\n"
            elif handling == "manual":
                record += f"修改方式: 研究者手动修改\n"
                record += f"修改说明: {note}\n"
            elif handling == "rejected":
                record += f"处理方式: 未采纳\n"
                record += f"理由: {reason}\n"
            records.append(record)

        records_text = "\n---\n".join(records)

        # 生成回复函
        ctx = self.context_engine.build_review_response_context(
            review_records=records_text,
            diff_summary="",  # 差异摘要可选
        )

        console.print("[dim]正在生成回复函...[/dim]")

        try:
            letter = await self.llm.chat(
                messages=ctx.to_messages(),
                model=self.config.default_writing_model,
                temperature=0.4,
            )
        except Exception as e:
            console.print(f"[red]生成失败: {e}[/red]")
            return

        # 保存回复函
        letter_path = self.file_manager.save_review_letter(self.project_dir, letter)

        # 更新审稿状态
        review_state["status"] = "response_generated"
        self.file_manager.save_review_state(self.project_dir, review_state)

        console.print(f"\n[green]✓ 回复函已生成: {letter_path}[/green]")
        console.print(Panel(letter[:500] + "...", title="回复函预览"))

    def _show_status(self) -> None:
        """显示审稿处理状态."""
        review_state = self.file_manager.load_review_state(self.project_dir)
        if not review_state:
            console.print("[yellow]暂无审稿处理记录[/yellow]")
            return

        comments = review_state.get("comments", [])
        done = sum(1 for c in comments if c.get("status") == "done")
        rejected = sum(1 for c in comments if c.get("status") == "rejected")
        pending = len(comments) - done - rejected

        console.print(
            Panel(
                f"[bold]审稿处理状态[/bold]\n\n"
                f"总意见数: {len(comments)}\n"
                f"已修改: {done}\n"
                f"已拒绝: {rejected}\n"
                f"待处理: {pending}\n"
                f"整体状态: {review_state.get('status', 'unknown')}\n"
                f"更新时间: {review_state.get('updated_at', '')[:19]}",
                title=f"📋 {self.project_dir.name}",
            )
        )

        if comments:
            type_labels = {"major": "重大", "minor": "小修", "question": "疑问", "positive": "肯定"}
            status_labels = {"done": "[green]✓已修改[/green]", "rejected": "[red]✗已拒绝[/red]", "pending_manual": "[yellow]⚠待手动[/yellow]"}

            table = Table(title="审稿意见处理详情")
            table.add_column("#", style="dim")
            table.add_column("类型", style="cyan")
            table.add_column("内容", style="white")
            table.add_column("状态", style="yellow")

            for c in comments:
                status = c.get("status", "pending")
                status_str = status_labels.get(status, f"[dim]{status}[/dim]")
                text = c.get("original_text", "")[:40] + "..."
                table.add_row(
                    str(c.get("id", "")),
                    type_labels.get(c.get("type", ""), c.get("type", "")),
                    text,
                    status_str,
                )

            console.print(table)

    def _extract_json_from_response(self, response: str) -> list[dict[str, Any]] | None:
        """从 LLM 响应中提取 JSON 数组."""
        # 尝试直接解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # 尝试提取代码块中的 JSON
        import re
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试提取方括号内容
        bracket_match = re.search(r"\[.*\]", response, re.DOTALL)
        if bracket_match:
            try:
                return json.loads(bracket_match.group(0))
            except json.JSONDecodeError:
                pass

        return None
