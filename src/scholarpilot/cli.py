"""ScholarPilot CLI 入口.

基于 Typer + Rich 构建的命令行工具。
用户通过自然语言与 Scholar Agent 交互，Agent 直接操作项目目录。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scholarpilot.config import get_settings
from scholarpilot.utils.file_manager import FileManager

app = typer.Typer(
    name="scholarpilot",
    help="ScholarPilot - 学术论文写作AI Agent",
    no_args_is_help=True,
)
console = Console()


def _get_file_manager() -> FileManager:
    """获取文件管理器实例."""
    settings = get_settings()
    return FileManager(projects_dir=settings.projects_dir)


@app.command()
def chat(
    project: str = typer.Option(None, "--project", "-p", help="项目名称"),
):
    """启动 Scholar Agent 交互对话."""
    console.print(
        Panel(
            "[bold blue]ScholarPilot[/bold blue] - 学术论文写作AI Agent",
            subtitle="v0.1.0",
        )
    )

    fm = _get_file_manager()

    if project:
        project_dir = fm.get_project_dir(project)
        if project_dir:
            console.print(f"[green]已加载项目:[/green] {project}")
            console.print(f"[dim]项目目录: {project_dir}[/dim]")
            # 显示项目状态
            meta = fm.get_project_meta(project_dir)
            if meta:
                console.print(f"[dim]状态: {meta.get('status', 'unknown')}[/dim]")
        else:
            console.print(f"[red]项目不存在: {project}[/red]")
            raise typer.Exit(1)
    else:
        # 列出可用项目
        projects = fm.list_projects()
        if projects:
            console.print("[dim]可用项目:[/dim]")
            for p in projects:
                console.print(f"  - {p}")
            console.print("\n[dim]使用 --project <name> 加载项目[/dim]")
        else:
            console.print("[yellow]暂无项目，使用 'scholarpilot new <name>' 创建[/yellow]")

    # 交互循环
    # 检查是否有模板预填的研究主题
    prefill_topic = ""
    if project_dir:
        spec_path = project_dir / "SPEC.md"
        if spec_path.exists():
            spec_content = spec_path.read_text(encoding="utf-8")
            import re as _re
            # 提取 HTML 注释中的研究主题
            topic_match = _re.search(r'<!--\s*研究主题:\s*(.+?)\s*-->', spec_content)
            if topic_match:
                prefill_topic = topic_match.group(1).strip()

    if prefill_topic:
        console.print(f"[dim]检测到模板预填的研究主题:[/dim]")
        console.print(f"  [cyan]{prefill_topic}[/cyan]\n")
        use_prefill = typer.confirm("使用此研究主题开始？", default=True)
        if use_prefill:
            user_input = prefill_topic
        else:
            console.print("[dim]输入您的研究想法，或输入 'exit' 退出。[/dim]\n")
            user_input = typer.prompt("ScholarPilot", default="", show_default=False)
    else:
        console.print("[dim]输入您的研究想法，或输入 'exit' 退出。[/dim]")
        console.print("[dim]示例：我想写一篇关于中国地方政府债务风险空间溢出效应的论文[/dim]\n")
        user_input = ""

    if not user_input.strip():
        while True:
            try:
                user_input = typer.prompt("ScholarPilot", default="", show_default=False)
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]再见！[/yellow]")
                return
            if user_input.strip():
                break
            if not user_input.strip():
                continue

    if user_input.strip().lower() in ("exit", "quit", "q"):
        console.print("[yellow]再见！[/yellow]")
        return

    # 启动 Scholar Agent
    import asyncio
    from scholarpilot.agent.scholar import ScholarAgent

    agent = ScholarAgent(project_dir=project_dir)
    asyncio.run(agent.run(user_input))


@app.command()
def new(
    name: str = typer.Argument(..., help="论文项目名称"),
    title: str = typer.Option("", "--title", "-t", help="论文标题（可选，选题后自动回填）"),
    journal: str = typer.Option("", "--journal", "-j", help="目标期刊（可选）"),
    template: str = typer.Option("", "--template", help="从示例模板创建（使用 scholarpilot examples 查看可用模板）"),
):
    """创建新的论文项目.

    可通过 --title 和 --journal 预设论文标题和目标期刊，
    也可在选题分析后由 Agent 自动回填。

    使用 --template 从示例模板创建，模板包含预设的研究主题描述，
    可用 `scholarpilot examples` 查看所有可用模板。
    """
    fm = _get_file_manager()

    # 检查是否已存在
    if fm.get_project_dir(name):
        console.print(f"[yellow]项目已存在: {name}[/yellow]")
        raise typer.Exit(1)

    # 创建项目
    project_dir = fm.create_project(name)

    # 如果提供了标题或期刊，更新元数据
    if title or journal:
        updates = {}
        if title:
            updates["title"] = title
        if journal:
            updates["target_journal"] = journal
        fm.update_project_meta(project_dir, updates)

    # 如果指定了模板，将模板描述写入 SPEC.md
    template_desc = ""
    if template:
        templates = _get_example_templates()
        matched = next((t for t in templates if t["id"] == template), None)
        if not matched:
            console.print(f"[red]模板不存在: {template}[/red]")
            console.print("[dim]使用 `scholarpilot examples` 查看可用模板[/dim]")
            raise typer.Exit(1)

        template_desc = matched["description"]
        # 用模板信息更新元数据
        fm.update_project_meta(project_dir, {
            "title": matched["title"],
            "research_type": matched.get("research_type", ""),
            "target_journal": journal or "",
        })
        # 将模板描述写入 SPEC.md 的备注区
        spec_path = project_dir / "SPEC.md"
        if spec_path.exists():
            spec_content = spec_path.read_text(encoding="utf-8")
            spec_content += f"\n\n<!-- 模板: {matched['id']} -->\n"
            spec_content += f"<!-- 研究主题: {template_desc} -->\n"
            spec_path.write_text(spec_content, encoding="utf-8")

        console.print(f"[green]项目创建成功:[/green] {name}")
        console.print(f"[dim]模板: {matched['title']}[/dim]")
        console.print(f"[dim]目录: {project_dir}[/dim]")
        console.print(f"\n[cyan]研究主题已预填，可直接开始:[/cyan]")
        console.print(f"  scholarpilot chat -p {name}")
        return

    console.print(f"[green]项目创建成功:[/green] {name}")
    console.print(f"[dim]目录: {project_dir}[/dim]")
    if title:
        console.print(f"[dim]标题: {title}[/dim]")
    if journal:
        console.print(f"[dim]目标期刊: {journal}[/dim]")

    # 显示项目结构
    tree = Table(title="项目结构", show_header=False, box=None)
    tree.add_column("path", style="cyan")
    tree.add_column("description", style="dim")

    tree.add_row("SPEC.md", "论文规格文档（Spec-Driven的核心）")
    tree.add_row("outline.md", "论文大纲")
    tree.add_row("literature/", "文献管理（综述+引用+PDF）")
    tree.add_row("data/", "研究数据（原始+处理）")
    tree.add_row("analysis/", "实证分析代码和结果")
    tree.add_row("draft/", "各章节草稿")
    tree.add_row("final/", "最终论文输出")
    tree.add_row(".scholar/", "Agent内部状态")

    console.print(tree)
    console.print(
        f"\n[dim]下一步: 编辑 {project_dir / 'SPEC.md'} 定义你的研究，"
        f"或运行 'scholarpilot chat -p {name}' 开始对话[/dim]"
    )


@app.command(name="list")
def list_projects():
    """列出所有论文项目."""
    fm = _get_file_manager()
    projects = fm.list_projects()

    if not projects:
        console.print("[yellow]暂无项目，使用 'scholarpilot new <name>' 创建[/yellow]")
        return

    table = Table(title="论文项目列表")
    table.add_column("名称", style="cyan")
    table.add_column("标题/主题", style="white")
    table.add_column("目标期刊", style="yellow")
    table.add_column("状态", style="green")
    table.add_column("章节", style="dim")
    table.add_column("更新时间", style="dim")

    for name in projects:
        project_dir = fm.get_project_dir(name)
        if project_dir:
            meta = fm.get_project_meta(project_dir) or {}
            sections = fm.list_sections(project_dir)
            # 标题优先显示，无标题则显示主题
            display_title = meta.get("title", "") or meta.get("topic", "") or "—"
            if len(display_title) > 30:
                display_title = display_title[:28] + "..."
            table.add_row(
                name,
                display_title,
                meta.get("target_journal", "—") or "—",
                meta.get("status", "unknown"),
                f"{len(sections)} 章",
                (meta.get("updated_at", "") or meta.get("created_at", ""))[:10],
            )

    console.print(table)


@app.command()
def status(
    project: str = typer.Argument(..., help="项目名称"),
):
    """查看项目状态."""
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)

    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    meta = fm.get_project_meta(project_dir) or {}
    sections = fm.list_sections(project_dir)
    plan = fm.load_plan(project_dir) or {}
    memory = fm.load_memory(project_dir) or {}

    console.print(Panel(f"[bold]{project}[/bold]", title="项目状态"))

    # 基本信息
    info = Table(show_header=False, box=None)
    info.add_column("key", style="dim")
    info.add_column("value", style="white")
    info.add_row("目录", str(project_dir))
    info.add_row("标题", meta.get("title", "") or "（待选题后回填）")
    info.add_row("研究主题", meta.get("topic", "") or "—")
    info.add_row("目标期刊", meta.get("target_journal", "") or "—")
    info.add_row("研究类型", meta.get("research_type", "") or "—")
    info.add_row("状态", meta.get("status", "unknown"))
    info.add_row("创建时间", meta.get("created_at", "")[:19])
    info.add_row("更新时间", (meta.get("updated_at", "") or "N/A")[:19])
    console.print(info)

    # 章节列表
    if sections:
        console.print("\n[bold]章节:[/bold]")
        for s in sections:
            console.print(f"  - {s}")

    # 执行计划
    plan_steps = plan.get("steps", [])
    if plan_steps:
        console.print("\n[bold]执行计划:[/bold]")
        current = plan.get("current_index", 0)
        for i, step in enumerate(plan_steps):
            marker = "[green]>[/green]" if i == current else " "
            status_str = step.get("status", "pending")
            console.print(f"  {marker} {i+1}. {step.get('task', 'N/A')} [{status_str}]")

    # 记忆
    memory_entries = memory.get("entries", [])
    if memory_entries:
        console.print(f"\n[bold]项目记忆:[/bold] {len(memory_entries)} 条")


@app.command()
def export(
    project: str = typer.Argument(..., help="项目名称"),
    fmt: str = typer.Option("docx", "--format", "-f", help="导出格式 (docx/pdf/md/tex)"),
    output: str = typer.Option(None, "--output", "-o", help="输出路径"),
):
    """导出论文为指定格式."""
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)

    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]导出项目 {project} 为 {fmt} 格式...[/dim]")
    try:
        from scholarpilot.tools.exporter import export_project
        output_path = export_project(project_dir, fmt=fmt, output_name=output)
        console.print(f"[green]导出成功: {output_path}[/green]")
    except FileNotFoundError as e:
        console.print(f"[red]导出失败: {e}[/red]")
    except Exception as e:
        console.print(f"[red]导出错误: {e}[/red]")


@app.command()
def profile(
    action: str = typer.Argument("show", help="操作: show/set/list-papers"),
    key: str = typer.Option("", "--key", "-k", help="偏好键名（set 操作时必填）"),
    value: str = typer.Option("", "--value", "-v", help="偏好值（set 操作时必填）"),
):
    """查看或管理研究者画像（跨论文长期记忆）.

    \b
    用法示例:
      scholarpilot profile show                    # 查看画像
      scholarpilot profile set -k target_journal -v 财贸经济  # 设置期刊偏好
      scholarpilot profile set -k writing_style -v "实证导向" # 设置写作风格
      scholarpilot profile list-papers             # 查看历史论文记录
    """
    from scholarpilot.context.profile import ResearcherProfile

    settings = get_settings()
    rp = ResearcherProfile(settings.user_home_dir / "profile.json")

    if action == "show":
        console.print(Panel(
            f"[dim]画像文件: {rp.profile_path}[/dim]",
            title="研究者画像",
        ))
        prefs = rp.get_all_preferences()
        if prefs:
            console.print("\n[bold]偏好设置:[/bold]")
            for k, v in prefs.items():
                console.print(f"  [cyan]{k}[/cyan]: {v}")
        else:
            console.print("\n[yellow]暂无偏好设置[/yellow]")

        papers = rp.get_paper_records()
        console.print(f"\n[bold]历史论文记录:[/bold] {len(papers)} 篇")
        for i, record in enumerate(papers[-5:], 1):
            title = record.get("title", record.get("project_name", "未知"))
            journal = record.get("target_journal", "")
            journal_str = f" → {journal}" if journal else ""
            console.print(f"  {i}. {title}{journal_str}")

    elif action == "set":
        if not key or not value:
            console.print("[red]set 操作需要 --key 和 --value 参数[/red]")
            raise typer.Exit(1)
        rp.set_preference(key, value)
        console.print(f"[green]已设置偏好: {key} = {value}[/green]")
        console.print(f"[dim]画像文件: {rp.profile_path}[/dim]")

    elif action == "list-papers":
        papers = rp.get_paper_records()
        if not papers:
            console.print("[yellow]暂无历史论文记录[/yellow]")
            return
        table = Table(title="历史论文记录")
        table.add_column("#", style="dim")
        table.add_column("项目", style="cyan")
        table.add_column("标题/主题", style="white")
        table.add_column("目标期刊", style="yellow")
        table.add_column("类型", style="dim")
        table.add_column("完成时间", style="dim")
        for i, record in enumerate(papers, 1):
            table.add_row(
                str(i),
                record.get("project_name", "—"),
                (record.get("title", "") or record.get("topic", ""))[:40],
                record.get("target_journal", "—") or "—",
                record.get("research_type", "—"),
                str(record.get("completed_at", ""))[:10],
            )
        console.print(table)

    else:
        console.print(f"[red]未知操作: {action}[/red]")
        console.print("[dim]可用操作: show, set, list-papers[/dim]")
        raise typer.Exit(1)


@app.command()
def versions(
    project: str = typer.Argument(..., help="项目名称"),
    action: str = typer.Argument("list", help="操作: list/restore/diff"),
    section: str = typer.Option("", "--section", "-s", help="章节名称，如 chapter1"),
    timestamp: str = typer.Option("", "--timestamp", "-t", help="版本时间戳（restore用）"),
    timestamp2: str = typer.Option("", "--timestamp2", help="对比的第二版本（diff用）"),
):
    """章节版本管理（查看历史/回退/对比）.

    \b
    科研场景：审稿人要求"改回上一版"或导师说"还是上一版好"。
    用法示例:
      scholarpilot versions debt_paper list -s chapter3           # 查看第3章历史版本
      scholarpilot versions debt_paper restore -s chapter3 -t 20260701_153000  # 回退
      scholarpilot versions debt_paper diff -s chapter3 -t 20260701_153000 --timestamp2 20260701_160000
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    if action == "list":
        if not section:
            # 列出所有有版本的章节
            versions_dir = project_dir / ".scholar" / "versions"
            if not versions_dir.exists():
                console.print("[yellow]暂无版本历史（首次保存后自动创建）[/yellow]")
                return
            sections = [d.name for d in versions_dir.iterdir() if d.is_dir()]
            if not sections:
                console.print("[yellow]暂无版本历史[/yellow]")
                return
            console.print("[bold]有版本记录的章节:[/bold]")
            for s in sorted(sections):
                count = len(list((versions_dir / s).glob("*.meta.json")))
                console.print(f"  {s} ({count} 个版本) - scholarpilot versions {project} list -s {s}")
        else:
            versions_list = fm.list_section_versions(project_dir, section)
            if not versions_list:
                console.print(f"[yellow]章节 {section} 暂无版本历史[/yellow]")
                return
            table = Table(title=f"{section} 版本历史")
            table.add_column("时间戳", style="cyan")
            table.add_column("标签", style="yellow")
            table.add_column("备注", style="white")
            table.add_column("字数", style="dim")
            for v in versions_list:
                table.add_row(
                    v.get("timestamp", ""),
                    v.get("label", "") or "—",
                    (v.get("note", "") or "—")[:40],
                    str(v.get("word_count", "—")),
                )
            console.print(table)
            console.print("\n[dim]回退: scholarpilot versions {} restore -s {} -t <时间戳>[/dim]".format(project, section))

    elif action == "restore":
        if not section or not timestamp:
            console.print("[red]restore 需要 --section 和 --timestamp 参数[/red]")
            raise typer.Exit(1)
        from rich.prompt import Confirm
        console.print(f"[yellow]即将将 {section} 回退到版本 {timestamp}[/yellow]")
        console.print("[dim]当前内容会自动保存为快照，不会丢失[/dim]")
        if not Confirm.ask("确认回退？", default=False):
            console.print("[dim]已取消[/dim]")
            return
        result = fm.restore_section_version(project_dir, section, timestamp)
        if result:
            console.print(f"[green]已回退: {result}[/green]")
        else:
            console.print(f"[red]版本 {timestamp} 不存在[/red]")

    elif action == "diff":
        if not section or not timestamp or not timestamp2:
            console.print("[red]diff 需要 --section、--timestamp、--timestamp2 参数[/red]")
            raise typer.Exit(1)
        diff_lines = fm.diff_section_versions(project_dir, section, timestamp, timestamp2)
        if diff_lines:
            for line in diff_lines:
                if line.startswith("+"):
                    console.print(f"[green]{line}[/green]", end="")
                elif line.startswith("-"):
                    console.print(f"[red]{line}[/red]", end="")
                elif line.startswith("@@"):
                    console.print(f"[cyan]{line}[/cyan]", end="")
                else:
                    console.print(line, end="")
        else:
            console.print("[yellow]两个版本内容相同[/yellow]")

    else:
        console.print(f"[red]未知操作: {action}[/red]")
        console.print("[dim]可用操作: list, restore, diff[/dim]")


@app.command()
def library(
    action: str = typer.Argument("stats", help="操作: stats/search/project/export"),
    keyword: str = typer.Option("", "--keyword", "-k", help="搜索关键词"),
    project: str = typer.Option("", "--project", "-p", help="项目名称"),
    limit: int = typer.Option(20, "--limit", "-n", help="最多显示数量"),
):
    """全局文献库管理（跨论文文献复用）.

    \b
    科研场景：写多篇相关论文时文献高度重叠，全局库避免重复检索和下载。
    用法示例:
      scholarpilot library stats                          # 查看文献库统计
      scholarpilot library search -k "地方政府债务"        # 搜索已有文献
      scholarpilot library project -p debt_paper          # 查看项目引用的文献
      scholarpilot library export -p debt_paper           # 导出项目BibTeX
    """
    from scholarpilot.utils.library import GlobalLibrary
    from scholarpilot.config import get_settings

    settings = get_settings()
    lib = GlobalLibrary(settings.user_home_dir / "library")

    if action == "stats":
        stats = lib.get_stats()
        console.print(Panel(
            f"[bold]全局文献库统计[/bold]\n\n"
            f"文献总量: {stats['total_papers']} 篇\n"
            f"含PDF: {stats['with_pdf']} 篇\n"
            f"被多论文引用: {stats['shared_papers']} 篇\n"
            f"关联项目: {len(stats['projects'])} 个",
            title="📚 文献库",
        ))
        if stats["by_source"]:
            console.print("\n[bold]按来源:[/bold]")
            for source, count in sorted(stats["by_source"].items(), key=lambda x: -x[1]):
                console.print(f"  {source}: {count} 篇")
        if stats["by_language"]:
            console.print("\n[bold]按语言:[/bold]")
            for lang, count in stats["by_language"].items():
                console.print(f"  {lang}: {count} 篇")
        if stats["projects"]:
            console.print(f"\n[bold]关联项目:[/bold] {', '.join(stats['projects'])}")

    elif action == "search":
        if not keyword:
            console.print("[red]search 需要 --keyword 参数[/red]")
            raise typer.Exit(1)
        results = lib.search(keyword=keyword, limit=limit)
        if not results:
            console.print(f"[yellow]未找到包含「{keyword}」的文献[/yellow]")
            return
        console.print(f"[green]找到 {len(results)} 篇相关文献:[/green]\n")
        for i, paper in enumerate(results, 1):
            authors = ", ".join(paper.get("authors", [])[:2])
            title = paper.get("title", "")
            year = paper.get("year", "")
            journal = paper.get("journal", "")
            source = paper.get("source", "")
            projects = paper.get("used_by_projects", [])
            shared_tag = f" [dim](已被{len(projects)}篇论文引用)[/dim]" if len(projects) > 1 else ""
            console.print(f"{i}. {title}")
            console.print(f"   [dim]{authors} | {journal} | {year} | {source}{shared_tag}[/dim]")

    elif action == "project":
        if not project:
            console.print("[red]project 需要 --project 参数[/red]")
            raise typer.Exit(1)
        papers = lib.get_project_papers(project)
        if not papers:
            console.print(f"[yellow]项目 {project} 暂无文献记录[/yellow]")
            return
        console.print(f"[green]项目 {project} 引用了 {len(papers)} 篇文献:[/green]\n")
        table = Table(title=f"{project} 的文献引用")
        table.add_column("#", style="dim")
        table.add_column("标题", style="white")
        table.add_column("作者", style="cyan")
        table.add_column("年份", style="dim")
        table.add_column("来源", style="yellow")
        for i, paper in enumerate(papers[:limit], 1):
            title = paper.get("title", "")[:50]
            authors = ", ".join(paper.get("authors", [])[:2])
            table.add_row(
                str(i), title, authors,
                str(paper.get("year", "")),
                paper.get("source", ""),
            )
        console.print(table)

    elif action == "export":
        if not project:
            console.print("[red]export 需要 --project 参数[/red]")
            raise typer.Exit(1)
        papers = lib.get_project_papers(project)
        if not papers:
            console.print(f"[yellow]项目 {project} 暂无文献记录[/yellow]")
            return
        bib_text = lib.to_bibtex([p["id"] for p in papers])
        output_path = Path(f"{project}_references.bib")
        output_path.write_text(bib_text, encoding="utf-8")
        console.print(f"[green]已导出 {len(papers)} 篇文献的 BibTeX 到 {output_path}[/green]")

    else:
        console.print(f"[red]未知操作: {action}[/red]")
        console.print("[dim]可用操作: stats, search, project, export[/dim]")


@app.command()
def progress(
    project: str = typer.Argument(..., help="项目名称"),
):
    """查看论文撰写进度（断点续写信息）.

    科研场景：写A论文到一半切去处理B论文审稿，回来查看A论文进度。
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    progress_info = fm.load_progress(project_dir)
    if not progress_info:
        console.print(f"[yellow]项目 {project} 暂无执行进度（尚未启动 Agent）[/yellow]")
        return

    summary = fm.get_progress_summary(project_dir)
    last_run = (progress_info.get("last_run_at", "") or "")[:19]
    completed_phases = progress_info.get("completed_phases", [])
    completed_sections = progress_info.get("completed_sections", [])
    total_sections = progress_info.get("total_sections", 0)

    phase_labels = {
        "topic_analysis": "选题分析",
        "literature_search": "文献检索",
        "spec_generation": "规格生成",
        "outline": "大纲生成",
        "data_collection": "数据采集",
        "section_writing": "逐章撰写",
        "post_processing": "摘要与引用",
        "completed": "已完成",
    }

    console.print(Panel(
        f"[bold]撰写进度[/bold]\n\n"
        f"当前阶段: {summary}\n"
        f"上次运行: {last_run}\n"
        f"已完成阶段: {len(completed_phases)}/{len(fm.PHASE_ORDER)}\n"
        f"已完成章节: {len(completed_sections)}/{total_sections if total_sections else '?'}"
        + ("\n[green]可断点续写[/green]" if progress_info.get("can_resume") else ""),
        title=f"📊 {project}",
    ))

    if completed_phases:
        console.print("\n[bold]已完成阶段:[/bold]")
        all_phases = fm.PHASE_ORDER
        for phase in all_phases:
            label = phase_labels.get(phase, phase)
            if phase in completed_phases:
                console.print(f"  [green]✓ {label}[/green]")
            elif phase == progress_info.get("current_phase"):
                console.print(f"  [yellow]▶ {label}（进行中）[/yellow]")
            else:
                console.print(f"  [dim]○ {label}[/dim]")

    if completed_sections:
        console.print(f"\n[bold]已完成章节:[/bold] {', '.join(completed_sections)}")

    detail = progress_info.get("phase_detail", "")
    if detail:
        console.print(f"\n[dim]详情: {detail}[/dim]")

    if progress_info.get("can_resume"):
        console.print(
            f"\n[green]继续撰写: scholarpilot chat -p {project} \"继续\"[/green]"
        )


@app.command()
def edit(
    project: str = typer.Argument(..., help="项目名称"),
):
    """段落级交互编辑（反复打磨文字）.

    \b
    科研场景：生成初稿后，研究者逐段审阅、修改。
    这是写作中最高频的操作——不是整章重来，而是"把第3段改一下"。

    \b
    用法:
      scholarpilot edit debt_paper    # 进入交互编辑器
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    sections = fm.list_sections(project_dir)
    if not sections:
        console.print("[yellow]暂无章节可编辑，请先生成论文初稿[/yellow]")
        raise typer.Exit(1)

    import asyncio
    from scholarpilot.agent.editor import ParagraphEditor

    editor = ParagraphEditor(project_dir)
    asyncio.run(editor.edit_session())


@app.command()
def review(
    project: str = typer.Argument(..., help="项目名称"),
    action: str = typer.Argument(
        "full",
        help="操作: full/import/analyze/modify/respond/status",
    ),
):
    """审稿意见处理（投稿后修改+回复函）.

    \b
    科研场景：投稿后收到审稿意见，逐条解析→修改论文→生成回复函。
    这是投稿后最痛苦的流程，本命令覆盖全流程。

    \b
    用法:
      scholarpilot review debt_paper                     # 完整流程
      scholarpilot review debt_paper import              # 仅导入审稿意见
      scholarpilot review debt_paper analyze             # 重新解析意见
      scholarpilot review debt_paper modify              # 逐条修改
      scholarpilot review debt_paper respond             # 生成回复函
      scholarpilot review debt_paper status              # 查看处理状态
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    sections = fm.list_sections(project_dir)
    if not sections:
        console.print("[yellow]暂无论文章节，请先生成论文初稿[/yellow]")
        raise typer.Exit(1)

    import asyncio
    from scholarpilot.agent.review import ReviewHandler

    handler = ReviewHandler(project_dir)
    asyncio.run(handler.handle_review_session(action=action))


@app.command()
def finalize(
    project: str = typer.Argument(..., help="项目名称"),
    abstract_only: bool = typer.Option(False, "--abstract-only", help="仅重新生成摘要"),
    citations_only: bool = typer.Option(False, "--citations-only", help="仅重新管理引用"),
    report_only: bool = typer.Option(False, "--report-only", help="仅显示质量报告，不执行任何操作"),
):
    """定稿处理——手动编辑草稿后重新生成摘要和参考文献.

    \b
    科研场景：用 ScholarPilot 生成初稿后，你会手动改写以降低 AI 率。
    改完后正文变了，摘要和参考文献也需要更新。不用重跑整个 chat 流程，
    用 finalize 即可独立处理。

    \b
    用法:
      scholarpilot finalize debt_paper                      # 重新生成摘要+参考文献
      scholarpilot finalize debt_paper --abstract-only      # 仅重新生成摘要
      scholarpilot finalize debt_paper --citations-only     # 仅重新提取验证引用
      scholarpilot finalize debt_paper --report-only        # 仅查看质量报告
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    draft_path = project_dir / "draft" / "full_draft.md"
    if not draft_path.exists():
        console.print("[red]草稿文件不存在，请先运行写作流程 (scholarpilot chat)[/red]")
        raise typer.Exit(1)

    import asyncio
    from scholarpilot.agent.scholar import ScholarAgent

    agent = ScholarAgent(project_dir)

    if report_only:
        report = agent.generate_quality_report()
        agent._display_quality_report(report)
        return

    # 确定操作
    do_abstract = True
    do_citations = True
    if abstract_only:
        do_citations = False
    if citations_only:
        do_abstract = False

    asyncio.run(agent.finalize(abstract=do_abstract, citations=do_citations))


@app.command()
def quality(
    project: str = typer.Argument(..., help="项目名称"),
):
    """查看论文质量报告——字数、引用数、结构完整性、期刊达标评估.

    \b
    不执行任何修改操作，仅分析当前草稿状态。
    帮你快速判断是否达到目标期刊的投稿门槛。

    \b
    用法:
      scholarpilot quality debt_paper
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    draft_path = project_dir / "draft" / "full_draft.md"
    if not draft_path.exists():
        console.print("[red]草稿文件不存在，请先运行写作流程[/red]")
        raise typer.Exit(1)

    from scholarpilot.agent.scholar import ScholarAgent

    agent = ScholarAgent(project_dir)
    report = agent.generate_quality_report()
    agent._display_quality_report(report)


@app.command()
def tables(
    project: str = typer.Argument(..., help="项目名称"),
):
    """生成实证表格模板——描述性统计表、回归结果表、相关系数矩阵.

    \b
    科研场景：实证论文需要标准的统计表格，但手动排版很耗时。
    本命令从 SPEC 中提取变量定义和模型设定，自动生成空表格模板。
    研究者只需填入真实数据，无需从零开始排版。

    \b
    用法:
      scholarpilot tables debt_paper    # 生成或重新生成表格模板
    """
    import asyncio
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    spec_path = project_dir / "SPEC.md"
    if not spec_path.exists() and not (project_dir / "SPEC.json").exists():
        console.print("[red]SPEC 文件不存在，请先运行写作流程[/red]")
        raise typer.Exit(1)

    from scholarpilot.agent.scholar import ScholarAgent

    agent = ScholarAgent(project_dir)
    asyncio.run(agent.generate_tables())


@app.command()
def feed(
    action: str = typer.Argument("run", help="操作: run/seeds/history/save"),
    max_recs: int = typer.Option(0, "--max", "-n", help="最大推荐数（0=用配置默认值20）"),
    strategies: str = typer.Option("", "--strategies", "-s", help="策略，逗号分隔: citation,author,topic"),
    add_seed: str = typer.Option("", "--add", help="添加种子论文（文献ID）"),
    remove_seed: str = typer.Option("", "--remove", help="移除种子论文（文献ID）"),
    auto_seed: bool = typer.Option(False, "--auto", help="自动选取种子论文"),
    seed_count: int = typer.Option(0, "--count", help="自动选取种子数量（0=配置默认值）"),
    save_id: str = typer.Option("", "--paper-id", help="保存推荐文献到全局库（save操作用）"),
):
    """文献动态订阅——追踪谁引用了你的核心文献，发现同领域新文章.

    \b
    科研场景：论文写完投出去了，但研究不会停止——你需要知道：
    - 谁引用了你的核心参考文献？（反向引用追踪）
    - 你关注的作者最近又发了什么？（同作者追踪）
    - 同领域最近有什么新文章？（主题增量）

    \b
    用法示例:
      scholarpilot feed                                # 运行订阅，获取推荐
      scholarpilot feed run -n 30 -s citation,author   # 指定数量和策略
      scholarpilot feed seeds                          # 查看种子论文
      scholarpilot feed seeds --auto --count 10        # 自动选取10篇种子
      scholarpilot feed seeds --add <paper_id>         # 手动添加种子
      scholarpilot feed seeds --remove <paper_id>      # 移除种子
      scholarpilot feed history                        # 查看推送历史
      scholarpilot feed save --paper-id <rec_id>       # 保存推荐到文献库
    """
    from scholarpilot.utils.library import GlobalLibrary
    from scholarpilot.config import get_settings

    settings = get_settings()
    lib = GlobalLibrary(settings.user_home_dir / "library")

    if action == "seeds":
        _feed_seeds_action(lib, settings, add_seed, remove_seed, auto_seed, seed_count)

    elif action == "history":
        _feed_history_action(lib)

    elif action == "save":
        _feed_save_action(lib, save_id)

    else:  # action == "run" or default
        _feed_run_action(lib, settings, max_recs, strategies)


def _feed_run_action(lib, settings, max_recs, strategies):
    """执行 feed 订阅运行."""
    import asyncio
    from scholarpilot.agent.feed import FeedManager

    # 检查种子论文
    seeds = lib.get_seed_papers()
    if not seeds:
        console.print("[yellow]暂无种子论文，正在自动选取...[/yellow]")
        seeds = lib.auto_select_seeds(count=settings.feed_auto_seed_count)
        if not seeds:
            console.print(
                "[red]全局文献库中没有足够文献作为种子。[/red]\n"
                "[dim]请先运行文献检索（scholarpilot chat）积累文献，"
                "或手动添加种子：scholarpilot feed seeds --add <paper_id>[/dim]"
            )
            raise typer.Exit(1)
        console.print(f"[green]已自动选取 {len(seeds)} 篇种子论文[/green]")

    # 显示种子信息
    console.print(Panel(
        f"种子论文: {len(seeds)} 篇\n"
        f"策略: {strategies or settings.feed_strategies}\n"
        f"最大推荐: {max_recs or settings.feed_max_recommendations} 篇",
        title="📡 文献动态订阅",
    ))

    # 检查是否有 LLM API Key（用于生成推荐理由）
    llm_gateway = None
    has_api_key = any([
        settings.claude_api_key,
        settings.openai_api_key,
        settings.deepseek_api_key,
        settings.zhipu_api_key,
        settings.ark_api_key,
    ])
    if settings.feed_enable_llm_reasons and has_api_key:
        try:
            from scholarpilot.llm.gateway import LLMGateway
            llm_gateway = LLMGateway(settings)
            console.print("[dim]已启用 LLM 推荐理由生成[/dim]")
        except Exception as e:
            console.print(f"[yellow]LLM 初始化失败，跳过推荐理由: {e}[/yellow]")

    # 创建 FeedManager 并运行
    manager = FeedManager(lib, settings, llm_gateway)

    strategy_list = strategies.split(",") if strategies else None

    console.print("\n[dim]正在检索新文献...（可能需要 30-60 秒）[/dim]")

    try:
        recommendations = asyncio.run(
            manager.run_feed(
                max_recommendations=max_recs,
                strategies=strategy_list,
            )
        )
    except Exception as e:
        console.print(f"[red]订阅运行失败: {e}[/red]")
        raise typer.Exit(1)

    # 展示结果
    if not recommendations:
        console.print("[yellow]本次未发现新文献。[/yellow]")
        console.print("[dim]可能原因：所有相关文献已在库中，或种子论文较少。[/dim]")
        console.print("[dim]建议：添加更多种子论文，或过几天再试。[/dim]")
        return

    console.print(f"\n[green]发现 {len(recommendations)} 篇新文献！[/green]\n")

    # 按策略分组展示
    strategy_labels = {
        "citation": "反向引用",
        "author": "同作者",
        "topic": "主题增量",
    }

    table = Table(title="📚 推荐文献")
    table.add_column("#", style="dim", width=3)
    table.add_column("策略", style="cyan", width=6)
    table.add_column("标题", style="white")
    table.add_column("作者", style="yellow", width=20)
    table.add_column("年份", style="dim", width=4)
    table.add_column("来源", style="dim", width=8)

    for i, rec in enumerate(recommendations, 1):
        strategy_label = strategy_labels.get(rec.get("strategy", ""), rec.get("strategy", ""))
        title = rec.get("title", "")[:60]
        authors = ", ".join(rec.get("authors", [])[:2])
        if len(authors) > 20:
            authors = authors[:18] + ".."
        year = str(rec.get("year", ""))
        source = rec.get("source", "")
        table.add_row(str(i), strategy_label, title, authors, year, source)

    console.print(table)

    # 显示推荐理由（如果有）
    has_reasons = any(rec.get("reason") for rec in recommendations)
    if has_reasons:
        console.print("\n[bold]推荐理由:[/bold]")
        for i, rec in enumerate(recommendations, 1):
            reason = rec.get("reason", "")
            if reason:
                console.print(f"  {i}. [dim]{reason}[/dim]")

    # 显示种子追踪信息
    console.print("\n[bold]种子追踪:[/bold]")
    for seed in seeds[:5]:
        title = seed.get("title", "")[:40]
        last_checked = seed.get("last_checked_citations_at", "")
        citation_count = seed.get("last_citation_count", 0)
        checked_str = f"（上次检查: {last_checked[:10]}，引用数: {citation_count}）" if last_checked else ""
        console.print(f"  • {title} {checked_str}")

    # 提示保存操作
    console.print(
        f"\n[dim]保存感兴趣文献到库: scholarpilot feed save --paper-id <序号>[/dim]"
    )
    console.print(
        f"[dim]查看历史推送: scholarpilot feed history[/dim]"
    )


def _feed_seeds_action(lib, settings, add_seed, remove_seed, auto_seed, seed_count):
    """种子论文管理操作."""
    if auto_seed:
        count = seed_count or settings.feed_auto_seed_count
        console.print(f"[dim]正在自动选取 {count} 篇种子论文...[/dim]")
        selected = lib.auto_select_seeds(count=count)
        if selected:
            console.print(f"[green]已选取 {len(selected)} 篇种子论文:[/green]")
            for i, paper in enumerate(selected, 1):
                title = paper.get("title", "")[:50]
                authors = ", ".join(paper.get("authors", [])[:2])
                console.print(f"  {i}. {title}")
                console.print(f"     [dim]{authors} | {paper.get('year', '')}[/dim]")
        else:
            console.print("[yellow]未能自动选取种子论文（库中文献引用数不足）[/yellow]")
            console.print("[dim]建议手动添加: scholarpilot feed seeds --add <paper_id>[/dim]")
        return

    if add_seed:
        paper = lib.get_paper(add_seed)
        if not paper:
            console.print(f"[red]文献不存在: {add_seed}[/red]")
            console.print("[dim]使用 'scholarpilot library search -k <关键词>' 查找文献ID[/dim]")
            raise typer.Exit(1)
        lib.mark_as_seed(add_seed)
        console.print(f"[green]已添加种子论文: {paper.get('title', '')[:50]}[/green]")
        return

    if remove_seed:
        if lib.unmark_seed(remove_seed):
            console.print(f"[green]已移除种子论文: {remove_seed}[/green]")
        else:
            console.print(f"[red]文献不存在: {remove_seed}[/red]")
            raise typer.Exit(1)
        return

    # 默认：列出种子论文
    seeds = lib.get_seed_papers()
    if not seeds:
        console.print("[yellow]暂无种子论文[/yellow]")
        console.print(
            "[dim]添加种子: scholarpilot feed seeds --add <paper_id>\n"
            "自动选取: scholarpilot feed seeds --auto[/dim]"
        )
        return

    console.print(f"[bold]种子论文（{len(seeds)} 篇）[/bold]\n")
    table = Table(title="🌱 种子论文")
    table.add_column("#", style="dim", width=3)
    table.add_column("标题", style="white")
    table.add_column("作者", style="cyan", width=20)
    table.add_column("年份", style="dim", width=4)
    table.add_column("引用数", style="yellow", width=6)
    table.add_column("订阅时间", style="dim", width=10)

    for i, paper in enumerate(seeds, 1):
        title = paper.get("title", "")[:50]
        authors = ", ".join(paper.get("authors", [])[:2])
        if len(authors) > 20:
            authors = authors[:18] + ".."
        year = str(paper.get("year", ""))
        citations = paper.get("last_citation_count", 0) or paper.get("citation_count", 0)
        subscribed = (paper.get("subscribed_at", "") or "")[:10]
        table.add_row(str(i), title, authors, year, str(citations), subscribed)

    console.print(table)
    console.print(
        f"\n[dim]运行订阅: scholarpilot feed\n"
        f"移除种子: scholarpilot feed seeds --remove <paper_id>[/dim]"
    )


def _feed_history_action(lib):
    """查看 feed 推送历史."""
    history = lib.get_feed_history(limit=20)
    if not history:
        console.print("[yellow]暂无推送历史[/yellow]")
        console.print("[dim]运行订阅: scholarpilot feed[/dim]")
        return

    console.print(f"[bold]推送历史（最近 {len(history)} 次）[/bold]\n")

    for i, record in enumerate(history, 1):
        timestamp = record.get("timestamp", "")[:19]
        strategy = record.get("strategy", "")
        seed_count = record.get("seed_count", 0)
        rec_count = record.get("recommendation_count", 0)

        console.print(
            f"  {i}. [{timestamp}] 策略: {strategy} | "
            f"种子: {seed_count} | 推荐: {rec_count} 篇"
        )

        # 显示前 3 条推荐标题
        recs = record.get("recommendations", [])[:3]
        for rec in recs:
            title = rec.get("title", "")[:50]
            console.print(f"     • {title}")

        if rec_count > 3:
            console.print(f"     [dim]... 还有 {rec_count - 3} 篇[/dim]")


def _feed_save_action(lib, save_id):
    """保存推荐文献到全局库."""
    # save_id 可以是序号（从最近一次推送中选取）或文献ID
    # 这里简化处理：直接通过 ID 查找
    if not save_id:
        console.print("[red]save 操作需要 --paper-id 参数[/red]")
        console.print("[dim]可以指定推荐列表中的序号或文献ID[/dim]")
        raise typer.Exit(1)

    # 尝试作为序号处理（从最近一次推送中获取）
    try:
        idx = int(save_id) - 1
        history = lib.get_feed_history(limit=1)
        if history:
            recs = history[0].get("recommendations", [])
            if 0 <= idx < len(recs):
                rec = recs[idx]
                # 添加到全局库
                lib.add_paper({
                    "title": rec.get("title", ""),
                    "authors": rec.get("authors", []),
                    "year": rec.get("year", ""),
                    "abstract": rec.get("abstract", ""),
                    "source": rec.get("source", ""),
                    "url": rec.get("url", ""),
                    "doi": rec.get("doi", ""),
                    "language": rec.get("language", ""),
                    "ss_paper_id": rec.get("ss_paper_id", ""),
                    "openalex_id": rec.get("openalex_id", ""),
                })
                console.print(f"[green]已保存到全局库: {rec.get('title', '')[:50]}[/green]")
                return
            else:
                console.print(f"[red]序号超出范围（1-{len(recs)}）[/red]")
                raise typer.Exit(1)
    except ValueError:
        pass

    # 作为文献ID处理
    paper = lib.get_paper(save_id)
    if paper:
        console.print(f"[green]文献已在库中: {paper.get('title', '')[:50]}[/green]")
    else:
        console.print(f"[red]未找到文献: {save_id}[/red]")


@app.command()
def code(
    project: str = typer.Argument(..., help="项目名称"),
    lang: str = typer.Option("stata", "--lang", "-l", help="语言: stata|r|python"),
    full: bool = typer.Option(True, "--full/--basic", help="生成完整模板（含智能方法追加）"),
    output: str = typer.Option("", "--output", "-o", help="输出文件路径（默认 analysis/ 目录）"),
):
    """生成实证分析代码模板——Stata .do / R / Python.

    \b
    科研场景：拿到 SPEC 后需要写 Stata/R 代码进行实证分析。
    从零写极耗时——本命令根据 SPEC 自动生成完整代码骨架，
    覆盖数据导入→预处理→描述统计→回归→诊断检验→稳健性检验全流程。
    还会根据 SPEC 关键词智能追加 DID/PSM/IV/中介/空间计量模板。

    \b
    用法:
      scholarpilot code debt_paper                          # 生成 Stata 模板
      scholarpilot code debt_paper --lang r                 # 生成 R 模板
      scholarpilot code debt_paper --lang python            # 生成 Python 模板
      scholarpilot code debt_paper --basic                  # 仅基础流程，不追加高级方法
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    # 读取 SPEC
    spec_path = project_dir / "SPEC.md"
    if not spec_path.exists():
        console.print("[red]SPEC.md 不存在，请先运行写作流程[/red]")
        raise typer.Exit(1)

    spec_text = spec_path.read_text(encoding="utf-8")

    # 从 outline.json 读取标题
    title = ""
    outline_path = project_dir / ".scholar" / "outline.json"
    if outline_path.exists():
        try:
            import json
            outline = json.loads(outline_path.read_text(encoding="utf-8"))
            title = outline.get("title", "")
        except (json.JSONDecodeError, OSError):
            pass

    from scholarpilot.tools.code_template_generator import CodeTemplateGenerator

    gen = CodeTemplateGenerator(project_dir=project_dir)

    if full:
        template = gen.generate_full_template(spec_text, lang=lang, title=title)
    else:
        if lang == "stata":
            template = gen.generate_stata_template(spec_text, title=title)
        elif lang == "r":
            template = gen.generate_r_template(spec_text, title=title)
        elif lang == "python":
            template = gen.generate_python_template(spec_text, title=title)
        else:
            console.print(f"[red]不支持的语言: {lang}。支持: stata, r, python[/red]")
            raise typer.Exit(1)

    # 确定输出路径
    ext_map = {"stata": ".do", "r": ".R", "python": ".py"}
    ext = ext_map.get(lang, ".txt")

    if output:
        output_path = Path(output)
    else:
        analysis_dir = project_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        output_path = analysis_dir / f"analysis_template{ext}"

    output_path.write_text(template, encoding="utf-8")

    console.print(f"[green]代码模板已生成: {output_path}[/green]")
    console.print(f"[dim]语言: {lang} | 模板长度: {len(template)} 字符[/dim]")

    # 显示模板概要
    lines = template.split("\n")
    section_markers = [l for l in lines if l.strip().startswith("// ===")]
    if section_markers:
        console.print("\n[bold]模板结构:[/bold]")
        for marker in section_markers:
            console.print(f"  {marker.strip()}")


@app.command()
def stats(
    project: str = typer.Argument(..., help="项目名称"),
    data: str = typer.Option("", "--data", "-d", help="数据文件路径（CSV/Excel），默认搜索 data/ 目录"),
    dep_var: str = typer.Option("", "--dep", help="被解释变量名"),
    indep_vars: str = typer.Option("", "--indep", help="解释变量名，逗号分隔"),
    entity_var: str = typer.Option("", "--entity", help="面板个体变量（如 province）"),
    time_var: str = typer.Option("", "--time", help="时间变量（如 year）"),
    model: str = typer.Option("ols", "--model", help="回归模型: ols|fe|re|quantile|logit|probit|tobit"),
    quantiles: str = typer.Option("", "--quantiles", help="分位数列表（逗号分隔），如 0.1,0.25,0.5,0.75,0.9"),
    tobit_lower: float = typer.Option(None, "--tobit-lower", help="Tobit左截断点"),
    tobit_upper: float = typer.Option(None, "--tobit-upper", help="Tobit右截断点"),
    output: str = typer.Option("", "--output", "-o", help="输出路径（默认 .scholar/stats_results.json）"),
):
    """统计分析——描述性统计、回归、VIF检验、分位数回归、离散选择模型.

    \b
    科研场景：研究者上传 CSV 数据后，不想打开 Stata 也能跑基础分析。
    本命令直接用 pandas + statsmodels 计算，结果可注入论文。

    \b
    用法:
      scholarpilot stats debt_paper --data data/user_data.csv \\
          --dep debt_risk --indep fiscal_gap,gdp_growth \\
          --entity province --time year --model fe

      scholarpilot stats debt_paper --dep debt_risk --indep fiscal_gap,gdp_growth \\
          --model quantile --quantiles 0.1,0.25,0.5,0.75,0.9

      scholarpilot stats debt_paper --dep default --indep debt_ratio,gdp_growth --model logit
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    # 查找数据文件
    if data:
        data_path = Path(data)
        if not data_path.is_absolute():
            data_path = project_dir / data_path
    else:
        # 自动搜索 data/ 目录
        data_dir = project_dir / "data"
        if data_dir.exists():
            candidates = list(data_dir.glob("*.csv")) + list(data_dir.glob("*.xlsx"))
            if candidates:
                data_path = candidates[0]
                console.print(f"[dim]自动检测到数据文件: {data_path.name}[/dim]")
            else:
                console.print("[red]未找到数据文件。请用 --data 指定路径，或将文件放入 data/ 目录[/red]")
                raise typer.Exit(1)
        else:
            console.print("[red]未找到 data/ 目录。请用 --data 指定数据文件路径[/red]")
            raise typer.Exit(1)

    if not data_path.exists():
        console.print(f"[red]数据文件不存在: {data_path}[/red]")
        raise typer.Exit(1)

    try:
        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        from scholarpilot.tools.stats_engine import StatsEngine
    except ImportError as e:
        console.print(f"[red]实证分析依赖未安装: {e}[/red]")
        console.print("[dim]安装: pip install scholarpilot[empirical][/dim]")
        raise typer.Exit(1)

    # 加载数据
    dp = DataPreprocessor()
    df = dp.load_data(data_path)
    console.print(f"[green]数据加载成功: {len(df)} 行, {len(df.columns)} 列[/green]")

    engine = StatsEngine()

    # 描述性统计
    console.print("\n[bold]描述性统计:[/bold]")
    desc_stats = engine.descriptive_stats(df)
    console.print(engine.format_results(desc_stats, format_type="markdown"))

    # 相关系数
    console.print("\n[bold]相关系数矩阵:[/bold]")
    corr = engine.correlation_matrix(df)
    console.print(engine.format_results(corr, format_type="markdown"))

    # 回归分析
    if dep_var and indep_vars:
        indep_list = [v.strip() for v in indep_vars.split(",")]

        if model in ("fe", "re") and entity_var and time_var:
            console.print(f"\n[bold]面板回归 ({model.upper()}):[/bold]")
            reg_results = engine.panel_regression(
                df, dep_var, indep_list, entity_var, time_var,
                model=model, cluster=True,
            )
        elif model == "quantile":
            q_list = None
            if quantiles:
                q_list = [float(q.strip()) for q in quantiles.split(",")]
            console.print(f"\n[bold]分位数回归:[/bold]")
            reg_results = engine.quantile_regression(
                df, dep_var, indep_list, quantiles=q_list, robust=True,
            )
        elif model == "logit":
            console.print(f"\n[bold]Logit 回归:[/bold]")
            reg_results = engine.logit_regression(df, dep_var, indep_list, robust=True)
        elif model == "probit":
            console.print(f"\n[bold]Probit 回归:[/bold]")
            reg_results = engine.probit_regression(df, dep_var, indep_list, robust=True)
        elif model == "tobit":
            console.print(f"\n[bold]Tobit 回归:[/bold]")
            reg_results = engine.tobit_regression(
                df, dep_var, indep_list, lower=tobit_lower, upper=tobit_upper,
            )
        else:
            console.print(f"\n[bold]OLS 回归:[/bold]")
            reg_results = engine.ols_regression(df, dep_var, indep_list, robust=True)

        console.print(engine.format_results(reg_results, format_type="markdown"))

        # VIF 检验（仅对连续模型做，logit/probit/tobit 跳过）
        if model not in ("logit", "probit", "tobit"):
            console.print("\n[bold]VIF 多重共线性检验:[/bold]")
            vif_results = engine.vif_test(df, indep_list)
            console.print(engine.format_results(vif_results, format_type="markdown"))
            has_vif = True
        else:
            vif_results = {}
            has_vif = False

        # 保存结果
        import json
        results = {
            "descriptive": desc_stats,
            "correlation": corr,
            "regression": reg_results,
        }
        if has_vif:
            results["vif"] = vif_results
        output_path = Path(output) if output else project_dir / ".scholar" / "stats_results.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        console.print(f"\n[green]结果已保存: {output_path}[/green]")
    else:
        console.print("\n[dim]未指定 --dep 和 --indep，跳过回归分析[/dim]")
        console.print("[dim]模型选项: ols|fe|re|quantile|logit|probit|tobit[/dim]")
        console.print("[dim]完整分析: scholarpilot stats <project> --dep <Y> --indep <X1,X2> --entity <id> --time <t> --model fe[/dim]")


@app.command(name="preprocess")
def preprocess(
    project: str = typer.Argument(..., help="项目名称"),
    data: str = typer.Option("", "--data", "-d", help="数据文件路径（CSV/Excel）"),
    winsorize: bool = typer.Option(True, "--winsorize/--no-winsorize", help="1%/99%缩尾处理"),
    output: str = typer.Option("", "--output", "-o", help="输出路径（默认 data/cleaned_data.csv）"),
):
    """数据预处理——缺失值检测、缩尾处理、清洗报告.

    \b
    科研场景：拿到原始数据第一步就是清洗。本命令自动检测缺失值、
    执行 1%/99% 缩尾处理（中国金融实证标准操作），并生成清洗报告。

    \b
    用法:
      scholarpilot preprocess debt_paper --data data/raw_data.csv
      scholarpilot preprocess debt_paper --data data/raw_data.xlsx --no-winsorize
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    # 查找数据文件
    if data:
        data_path = Path(data)
        if not data_path.is_absolute():
            data_path = project_dir / data_path
    else:
        data_dir = project_dir / "data"
        if data_dir.exists():
            candidates = list(data_dir.glob("*.csv")) + list(data_dir.glob("*.xlsx"))
            if candidates:
                data_path = candidates[0]
                console.print(f"[dim]自动检测到数据文件: {data_path.name}[/dim]")
            else:
                console.print("[red]未找到数据文件。请用 --data 指定路径[/red]")
                raise typer.Exit(1)
        else:
            console.print("[red]未找到 data/ 目录。请用 --data 指定数据文件路径[/red]")
            raise typer.Exit(1)

    if not data_path.exists():
        console.print(f"[red]数据文件不存在: {data_path}[/red]")
        raise typer.Exit(1)

    try:
        from scholarpilot.tools.data_preprocessor import DataPreprocessor
    except ImportError as e:
        console.print(f"[red]依赖未安装: {e}[/red]")
        console.print("[dim]安装: pip install scholarpilot[empirical][/dim]")
        raise typer.Exit(1)

    dp = DataPreprocessor()
    df_original = dp.load_data(data_path)
    console.print(f"[green]数据加载成功: {len(df_original)} 行, {len(df_original.columns)} 列[/green]")

    operations = []

    # 缺失值检测
    console.print("\n[bold]缺失值检测:[/bold]")
    missing_report = dp.check_missing(df_original)
    has_missing = False
    for var, info in missing_report.items():
        if info["count"] > 0:
            has_missing = True
            console.print(f"  {var}: {info['count']} 缺失 ({info['percentage']:.1f}%) → 建议: {info['suggestion']}")

    if not has_missing:
        console.print("  [green]无缺失值[/green]")

    # 缺失值处理
    df_cleaned = df_original.copy()
    if has_missing:
        strategy = {}
        for var, info in missing_report.items():
            if info["count"] > 0:
                strategy[var] = info["suggestion"].split()[0]
        if strategy:
            df_cleaned = dp.handle_missing(df_cleaned, strategy)
            operations.append(f"缺失值处理: {strategy}")
            console.print(f"[dim]已处理缺失值: {len(strategy)} 个变量[/dim]")

    # 缩尾处理
    if winsorize:
        numeric_vars = df_cleaned.select_dtypes(include=["number"]).columns.tolist()
        # 排除标识列
        id_cols = {"year", "province", "city", "region", "id", "code"}
        winsor_vars = [v for v in numeric_vars if v.lower() not in id_cols]
        if winsor_vars:
            df_cleaned = dp.winsorize(df_cleaned, winsor_vars, lower=0.01, upper=0.99)
            operations.append(f"缩尾处理: {len(winsor_vars)} 个变量 (1%/99%)")
            console.print(f"[dim]已缩尾处理: {len(winsor_vars)} 个变量[/dim]")

    # 生成清洗报告
    report = dp.generate_cleaning_report(df_original, df_cleaned, operations)
    console.print(f"\n[bold]数据清洗报告:[/bold]")
    console.print(report)

    # 保存清洗后数据
    output_path = Path(output) if output else project_dir / "data" / "cleaned_data.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_cleaned.to_csv(output_path, index=False, encoding="utf-8-sig")
    console.print(f"\n[green]清洗后数据已保存: {output_path}[/green]")
    console.print(f"[dim]原始行数: {len(df_original)} → 清洗后: {len(df_cleaned)}[/dim]")


@app.command()
def datasource(
    project: str = typer.Argument(..., help="项目名称"),
    output: str = typer.Option("", "--output", "-o", help="输出路径（默认 data_collection_guide.md）"),
):
    """生成数据采集指南——匹配变量到 CSMAR/Wind/RESSET/NBS 等数据源.

    \b
    科研场景：研究生拿到 SPEC 后不知道去哪里找数据。
    本命令根据 SPEC 中的变量设计，自动匹配推荐数据源。

    \b
    用法:
      scholarpilot datasource debt_paper
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    spec_path = project_dir / "SPEC.md"
    if not spec_path.exists():
        console.print("[red]SPEC.md 不存在[/red]")
        raise typer.Exit(1)

    spec_text = spec_path.read_text(encoding="utf-8")

    from scholarpilot.tools.data_source_guide import generate_data_source_guide

    output_path = Path(output) if output else project_dir / "data_collection_guide.md"
    guide = generate_data_source_guide(spec_text, output_path)

    console.print(f"[green]数据采集指南已生成: {output_path}[/green]")
    console.print(f"[dim]指南长度: {len(guide)} 字符[/dim]")


@app.command()
def diagnose(
    project: str = typer.Argument(..., help="项目名称"),
    data: str = typer.Option("", "--data", "-d", help="数据文件路径"),
    dep_var: str = typer.Option("", "--dep", help="被解释变量"),
    indep_vars: str = typer.Option("", "--indep", help="解释变量，逗号分隔"),
    entity_var: str = typer.Option("", "--entity", help="面板个体变量"),
    time_var: str = typer.Option("", "--time", help="时间变量"),
):
    """计量诊断检验——VIF/Hausman/异方差/自相关/单位根.

    \b
    科研场景：审稿人常问"是否做了多重共线性检验""FE还是RE""是否存在异方差"。

    \b
    用法:
      scholarpilot diagnose debt_paper --data data/user_data.csv \\
          --dep debt_risk --indep fiscal_gap,gdp_growth \\
          --entity province --time year
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    if data:
        data_path = Path(data)
        if not data_path.is_absolute():
            data_path = project_dir / data_path
    else:
        data_dir = project_dir / "data"
        if data_dir.exists():
            candidates = list(data_dir.glob("*.csv")) + list(data_dir.glob("*.xlsx"))
            if candidates:
                data_path = candidates[0]
            else:
                console.print("[red]未找到数据文件[/red]")
                raise typer.Exit(1)
        else:
            console.print("[red]未找到 data/ 目录[/red]")
            raise typer.Exit(1)

    try:
        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        from scholarpilot.tools.econometric_diagnostics import EconometricDiagnostics
    except ImportError as e:
        console.print(f"[red]依赖未安装: {e}[/red]")
        console.print("[dim]安装: pip install scholarpilot[empirical][/dim]")
        raise typer.Exit(1)

    dp = DataPreprocessor()
    df = dp.load_data(data_path)
    console.print(f"[green]数据加载: {len(df)} 行, {len(df.columns)} 列[/green]")

    diag = EconometricDiagnostics()
    results = {}

    indep_list = [v.strip() for v in indep_vars.split(",")] if indep_vars else []

    if indep_list:
        # VIF
        console.print("\n[bold]VIF 多重共线性检验:[/bold]")
        vif = diag.vif_test(df, indep_list)
        results["vif"] = vif
        for var, val in vif.get("variables", {}).items():
            console.print(f"  {var}: VIF = {val:.2f}")
        console.print(f"  最大VIF: {vif.get('max_vif', 'N/A'):.2f}")

    if dep_var and indep_list and entity_var and time_var:
        # Hausman
        console.print("\n[bold]Hausman 检验 (FE vs RE):[/bold]")
        hausman = diag.hausman_test(df, dep_var, indep_list, entity_var, time_var)
        results["hausman"] = hausman
        console.print(f"  chi2 = {hausman.get('chi2', 'N/A')}")
        console.print(f"  p值 = {hausman.get('p_value', 'N/A')}")
        console.print(f"  建议: {hausman.get('recommendation', 'N/A')}")

    if dep_var and indep_list:
        # Breusch-Pagan
        console.print("\n[bold]Breusch-Pagan 异方差检验:[/bold]")
        bp = diag.breusch_pagan_test(df, dep_var, indep_list)
        results["breusch_pagan"] = bp
        console.print(f"  LM = {bp.get('lm_statistic', 'N/A')}")
        console.print(f"  p值 = {bp.get('p_value', 'N/A')}")

    # 诊断报告
    if results:
        report = diag.generate_diagnostics_report(results)
        report_path = project_dir / ".scholar" / "diagnostics_report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        console.print(f"\n[green]诊断报告已保存: {report_path}[/green]")


@app.command()
def mechanism(
    project: str = typer.Argument(..., help="项目名称"),
    data: str = typer.Option("", "--data", "-d", help="数据文件路径"),
    x: str = typer.Option("", "--x", help="自变量（核心解释变量）"),
    y: str = typer.Option("", "--y", help="因变量（被解释变量）"),
    mediator: str = typer.Option("", "--mediator", "-m", help="中介变量"),
    moderator: str = typer.Option("", "--moderator", help="调节变量（调节效应分析用）"),
    controls: str = typer.Option("", "--controls", help="控制变量，逗号分隔"),
    analysis_type: str = typer.Option("mediation", "--type", help="分析类型: mediation|moderation"),
    bootstrap: bool = typer.Option(False, "--bootstrap", help="使用Bootstrap检验中介效应"),
):
    """机制分析——中介效应/调节效应分析.

    \b
    科研场景：中国实证论文几乎都有"机制分析"章节。

    \b
    用法:
      # 中介效应
      scholarpilot mechanism debt_paper --data data/user_data.csv \\
          --x fiscal_gap --y debt_risk --mediator financial_dev --controls gdp_growth,urban_rate

      # 调节效应
      scholarpilot mechanism debt_paper --data data/user_data.csv \\
          --x fiscal_gap --y debt_risk --moderator gdp_growth --type moderation
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    if data:
        data_path = Path(data)
        if not data_path.is_absolute():
            data_path = project_dir / data_path
    else:
        data_dir = project_dir / "data"
        if data_dir.exists():
            candidates = list(data_dir.glob("*.csv")) + list(data_dir.glob("*.xlsx"))
            if candidates:
                data_path = candidates[0]
            else:
                console.print("[red]未找到数据文件[/red]")
                raise typer.Exit(1)
        else:
            console.print("[red]未找到 data/ 目录[/red]")
            raise typer.Exit(1)

    try:
        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        from scholarpilot.tools.mediation_analysis import MediationAnalysis
    except ImportError as e:
        console.print(f"[red]依赖未安装: {e}[/red]")
        console.print("[dim]安装: pip install scholarpilot[empirical][/dim]")
        raise typer.Exit(1)

    dp = DataPreprocessor()
    df = dp.load_data(data_path)
    console.print(f"[green]数据加载: {len(df)} 行[/green]")

    ma = MediationAnalysis()
    control_list = [c.strip() for c in controls.split(",")] if controls else None
    results = {}

    if analysis_type == "mediation" and x and y and mediator:
        console.print(f"\n[bold]中介效应分析 (Baron & Kenny 三步法):[/bold]")
        console.print(f"  路径: {x} → {mediator} → {y}")

        bk = ma.baron_kenny(df, x=x, y=y, mediator=mediator, controls=control_list)
        results["baron_kenny"] = bk

        console.print(f"\n  步骤1 (总效应 c): {bk.get('total_effect', 'N/A')}")
        console.print(f"  步骤2 (X→M, a): {bk.get('step2', {}).get('coefficients', {}).get(x, 'N/A')}")
        console.print(f"  步骤3 (直接效应 c'): {bk.get('direct_effect', 'N/A')}")
        console.print(f"  间接效应 (a*b): {bk.get('indirect_effect', 'N/A')}")
        console.print(f"  中介类型: {bk.get('mediation_type', 'N/A')}")

        # Sobel检验
        if "step2" in bk and "step3" in bk:
            a_coef = bk["step2"].get("coefficients", {}).get(x, 0)
            a_se = bk["step2"].get("std_errors", {}).get(x, 0)
            b_coef = bk["step3"].get("coefficients", {}).get(mediator, 0)
            b_se = bk["step3"].get("std_errors", {}).get(mediator, 0)

            sobel = ma.sobel_test(a_coef, b_coef, a_se, b_se)
            results["sobel"] = sobel
            console.print(f"\n  Sobel检验: z = {sobel.get('z', 'N/A')}, p = {sobel.get('p_value', 'N/A')}")

        # Bootstrap
        if bootstrap:
            console.print(f"\n  Bootstrap 检验 (1000次)...")
            boot = ma.bootstrap_mediation(df, x=x, y=y, mediator=mediator,
                                          controls=control_list, n_bootstrap=1000)
            results["bootstrap"] = boot
            console.print(f"  间接效应: {boot.get('indirect_effect', 'N/A')}")
            console.print(f"  95% CI: [{boot.get('ci_lower', 'N/A')}, {boot.get('ci_upper', 'N/A')}]")
            console.print(f"  显著: {'是' if boot.get('significant') else '否'}")

    elif analysis_type == "moderation" and x and y and moderator:
        console.print(f"\n[bold]调节效应分析:[/bold]")
        console.print(f"  模型: {y} = β1*{x} + β2*{moderator} + β3*({x}*{moderator}) + controls")

        mod = ma.moderation_analysis(df, x=x, y=y, moderator=moderator, controls=control_list)
        results["moderation"] = mod

        console.print(f"\n  R² = {mod.get('r_squared', 'N/A')}")
        console.print(f"  交互项系数 = {mod.get('coefficients', {}).get(f'{x}_{moderator}', 'N/A')}")
        console.print(f"  交互项p值 = {mod.get('interaction_p_value', 'N/A')}")
        console.print(f"  存在调节效应: {'是' if mod.get('has_moderation') else '否'}")
    else:
        console.print("[red]参数不足。中介效应需要 --x --y --mediator；调节效应需要 --x --y --moderator --type moderation[/red]")
        raise typer.Exit(1)

    # 生成报告
    report = ma.generate_mechanism_report(results)
    report_path = project_dir / ".scholar" / "mechanism_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    console.print(f"\n[green]机制分析报告已保存: {report_path}[/green]")


@app.command(name="plot")
def plot_cmd(
    project: str = typer.Argument(..., help="项目名称"),
    plot_type: str = typer.Option("distribution", "--type", "-t", help="图表类型: distribution|boxplot|coef|corr|event|moran"),
    data: str = typer.Option("", "--data", "-d", help="数据文件路径"),
    variables: str = typer.Option("", "--vars", help="变量名，逗号分隔"),
    output: str = typer.Option("", "--output", "-o", help="输出路径（默认 analysis/ 目录）"),
):
    """科研绘图——分布图/箱线图/系数图/热力图/事件研究图/Moran散点图.

    \b
    用法:
      scholarpilot plot debt_paper --type distribution --vars debt_risk,fiscal_gap
      scholarpilot plot debt_paper --type coef --output analysis/coef_plot.pdf
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    try:
        import matplotlib  # noqa: F401
    except ImportError:
        console.print("[red]matplotlib 未安装。安装: pip install scholarpilot[empirical][/red]")
        raise typer.Exit(1)

    from scholarpilot.tools.plot_generator import PlotGenerator

    pg = PlotGenerator()
    var_list = [v.strip() for v in variables.split(",")] if variables else []

    # 确定输出路径
    if output:
        output_path = Path(output)
    else:
        analysis_dir = project_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        output_path = analysis_dir / f"{plot_type}_plot.pdf"

    if plot_type in ("distribution", "boxplot"):
        if not data:
            data_dir = project_dir / "data"
            if data_dir.exists():
                candidates = list(data_dir.glob("*.csv")) + list(data_dir.glob("*.xlsx"))
                if candidates:
                    data_path = candidates[0]
                else:
                    console.print("[red]未找到数据文件[/red]")
                    raise typer.Exit(1)
            else:
                console.print("[red]请用 --data 指定数据文件[/red]")
                raise typer.Exit(1)
        else:
            data_path = Path(data)
            if not data_path.is_absolute():
                data_path = project_dir / data_path

        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        dp = DataPreprocessor()
        df = dp.load_data(data_path)

        if not var_list:
            var_list = df.select_dtypes(include=["number"]).columns.tolist()[:4]

        if plot_type == "distribution":
            pdf_path, png_path = pg.plot_distribution(df, var_list, output_path)
        else:
            pdf_path, png_path = pg.plot_boxplot(df, var_list, output_path)

        console.print(f"[green]图表已生成: {pdf_path}[/green]")
        console.print(f"[dim]预览图: {png_path}[/dim]")

    elif plot_type == "corr":
        if not data:
            data_dir = project_dir / "data"
            candidates = list(data_dir.glob("*.csv")) if data_dir.exists() else []
            if not candidates:
                console.print("[red]请用 --data 指定数据文件[/red]")
                raise typer.Exit(1)
            data_path = candidates[0]
        else:
            data_path = Path(data)
            if not data_path.is_absolute():
                data_path = project_dir / data_path

        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        from scholarpilot.tools.stats_engine import StatsEngine
        dp = DataPreprocessor()
        df = dp.load_data(data_path)
        engine = StatsEngine()
        corr = engine.correlation_matrix(df, variables=var_list if var_list else None)

        pdf_path, png_path = pg.plot_correlation_heatmap(corr, output_path)
        console.print(f"[green]相关系数热力图已生成: {pdf_path}[/green]")

    else:
        console.print(f"[yellow]图表类型 '{plot_type}' 需要提供结果数据。请使用 Python API 调用。[/yellow]")
        console.print("[dim]支持的数据驱动类型: distribution, boxplot, corr[/dim]")


@app.command(name="parse-result")
def parse_result(
    project: str = typer.Argument(..., help="项目名称"),
    file: str = typer.Option("", "--file", "-f", help="回归输出文件路径"),
    source: str = typer.Option("auto", "--source", "-s", help="输出格式: auto/stata/r/python/json"),
    output: str = typer.Option("", "--output", "-o", help="输出路径（默认 analysis/parsed_result.md）"),
):
    """解析回归输出——从 Stata/R/Python 日志提取系数/标准误/p值.

    \b
    科研场景：研究生用 Stata/R 跑完回归后，需要把输出结果
    整理成论文表格。本命令自动解析日志文件，提取系数、标准误、
    p 值等关键信息，生成 Markdown 表格。

    \b
    用法:
      scholarpilot parse-result debt_paper --file data/stata_output.log
      scholarpilot parse-result debt_paper --file data/r_output.txt --source r
      scholarpilot parse-result debt_paper --file data/result.json --source json
    """
    from scholarpilot.tools.result_parser import ResultParser

    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    if not file:
        console.print("[red]请用 --file 指定回归输出文件路径[/red]")
        raise typer.Exit(1)

    file_path = Path(file)
    if not file_path.is_absolute():
        file_path = project_dir / file_path

    if not file_path.exists():
        console.print(f"[red]文件不存在: {file_path}[/red]")
        raise typer.Exit(1)

    parser = ResultParser()
    try:
        result = parser.parse_file(file_path, source=source)
    except Exception as e:
        console.print(f"[red]解析失败: {e}[/red]")
        raise typer.Exit(1)

    # 输出 Markdown 表格
    md_text = parser.to_markdown(result, title=f"回归结果（来源: {result['source']}）")

    output_path = Path(output) if output else project_dir / "analysis" / "parsed_result.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md_text, encoding="utf-8")

    console.print(f"[green]解析完成！结果已保存: {output_path}[/green]")
    console.print(f"[dim]模型类型: {result['model_type']}, 变量数: {len(result['variables'])}[/dim]")
    if result.get("n_obs"):
        console.print(f"[dim]观测数: {result['n_obs']}[/dim]")
    if result.get("r_squared") is not None:
        console.print(f"[dim]R²: {result['r_squared']:.4f}[/dim]")


@app.command(name="package")
def package(
    project: str = typer.Argument(..., help="项目名称或项目目录路径"),
    output: str = typer.Option("", "--output", "-o", help="输出 zip 路径（默认 <project>_repro.zip）"),
    include_data: bool = typer.Option(True, "--include-data/--no-include-data", help="是否包含 data/ 目录，默认 True"),
    description: str = typer.Option("", "--description", "-d", help="项目描述（写入 README）"),
    data_source: str = typer.Option("", "--data-source", help="数据来源说明（写入 README）"),
):
    """打包项目为可复现研究包（zip）.

    \b
    科研场景：论文投稿或数据共享时，需要将 data/ + code/ + paper/
    连同依赖锁文件、Makefile、README、溯源清单一起打包，供审稿人
    和读者复现研究。本命令自动完成打包。

    \b
    生成内容：
      - data/ + code/ + paper/ 项目内容
      - requirements.txt（pip freeze 锁定版本）
      - Makefile（make data / make analysis / make paper）
      - README.md（项目说明、运行步骤、依赖列表）
      - manifest.json（输入/输出文件 SHA256 + 参数 + 依赖版本）

    \b
    用法：
      scholarpilot package debt_paper
      scholarpilot package debt_paper --output repro.zip
      scholarpilot package debt_paper --no-include-data
    """
    from scholarpilot.tools.reproducibility import ReproducibilityPackager

    fm = _get_file_manager()

    # project 既可能是项目名称（在 projects_dir 下），也可能是直接的目录路径
    project_dir = fm.get_project_dir(project)
    if project_dir is None:
        # 尝试作为直接路径解析
        direct_path = Path(project)
        if direct_path.exists() and direct_path.is_dir():
            project_dir = direct_path
        else:
            console.print(f"[red]项目不存在: {project}[/red]")
            raise typer.Exit(1)

    # 默认输出路径
    if output:
        output_path = Path(output)
        if not output_path.is_absolute():
            output_path = project_dir.parent / output_path
    else:
        output_path = project_dir.parent / f"{project_dir.name}_repro.zip"

    packager = ReproducibilityPackager()
    try:
        zip_path = packager.package(
            project_dir=project_dir,
            output_path=output_path,
            include_data=include_data,
            project_name=project_dir.name,
            description=description,
            data_source=data_source,
        )
    except Exception as e:
        console.print(f"[red]打包失败: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]可复现研究包已生成: {zip_path}[/green]")
    console.print(f"[dim]文件大小: {zip_path.stat().st_size} bytes[/dim]")
    console.print(f"[dim]包含数据: {'是' if include_data else '否'}[/dim]")

    # 展示包内文件列表
    import zipfile as _zipfile

    with _zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
    console.print(f"[dim]包内文件数: {len(names)}[/dim]")
    table = Table(title="包内容", show_header=True, header_style="bold")
    table.add_column("文件", style="cyan")
    for name in names[:20]:
        table.add_row(name)
    if len(names) > 20:
        table.add_row(f"...（共 {len(names)} 个文件）")
    console.print(table)


@app.command(name="check-ai")
def check_ai(
    project: str = typer.Argument(..., help="项目名称"),
    file: str = typer.Option("", "--file", "-f", help="指定文件路径（默认检测 full_draft.md）"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="显示详细的问题句子列表"),
    output: str = typer.Option("", "--output", "-o", help="报告输出路径（默认 analysis/ai_detection_report.md）"),
):
    """AI生成痕迹检测——提交前的安全自查.

    \b
    科研场景：论文完成后、提交期刊或盲审之前，
    检测文本中是否存在AI写作特征（对仗排比、套路化过渡、
    句式单一等10类模式），给出风险等级和修改建议。

    \b
    用法:
      scholarpilot check-ai debt_paper
      scholarpilot check-ai debt_paper --detailed
      scholarpilot check-ai debt_paper -f draft/chapter2.md -d
    """
    from scholarpilot.tools.de_ai import DeAIEngine

    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    # 确定检测文件
    if file:
        file_path = Path(file)
        if not file_path.is_absolute():
            file_path = project_dir / file_path
    else:
        file_path = project_dir / "draft" / "full_draft_polished.md"
        if not file_path.exists():
            file_path = project_dir / "draft" / "full_draft.md"

    if not file_path.exists():
        console.print(f"[red]文件不存在: {file_path}[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]检测文件: {file_path}[/dim]")
    text = file_path.read_text(encoding="utf-8")
    if not text.strip():
        console.print("[red]文件内容为空[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]文本长度: {len(text):,} 字符，正在检测AI写作痕迹...[/dim]")

    engine = DeAIEngine()
    assessment = engine.detect_ai_patterns(text)

    # 风险等级颜色映射
    risk_colors = {"low": "green", "medium": "yellow", "high": "red"}
    risk_color = risk_colors.get(assessment.risk_level.value, "white")

    # 控制台输出摘要
    console.print()
    console.print(Panel(
        f"[{risk_color}]风险等级: {assessment.risk_level.value.upper()}[/{risk_color}]\n"
        f"AI生成概率: {assessment.ai_probability:.1%}\n"
        f"AI特征评分: {assessment.overall_score:.1f}/100\n"
        f"检测到模式: {len(assessment.detected_patterns)} 类\n"
        f"问题句子: {len(assessment.problematic_sentences)} 处",
        title="AI痕迹检测报告",
    ))

    # 检测到的模式
    if assessment.detected_patterns:
        console.print("\n[bold]检测到的AI写作模式:[/bold]")
        for i, pattern in enumerate(assessment.detected_patterns, 1):
            console.print(f"  {i}. {pattern}")

    # 详细问题句子
    if detailed and assessment.problematic_sentences:
        console.print("\n[bold]问题句子详情:[/bold]")
        for i, ps in enumerate(assessment.problematic_sentences[:20], 1):
            sentence = ps.get("sentence", "")[:80]
            pattern = ps.get("pattern", "")
            suggestion = ps.get("suggestion", "")
            console.print(f"\n  [cyan]{i}.[/cyan] {sentence}{'...' if len(ps.get('sentence',''))>80 else ''}")
            console.print(f"      [yellow]模式:[/yellow] {pattern}")
            if suggestion:
                console.print(f"      [green]建议:[/green] {suggestion}")

    # 生成报告文件
    report_lines = [
        "# AI痕迹检测报告",
        "",
        f"**检测文件**: `{file_path}`",
        f"**检测时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**文本长度**: {len(text):,} 字符",
        "",
        "## 检测结果摘要",
        "",
        f"| 指标 | 结果 |",
        f"|------|------|",
        f"| 风险等级 | {assessment.risk_level.value.upper()} |",
        f"| AI生成概率 | {assessment.ai_probability:.1%} |",
        f"| AI特征评分 | {assessment.overall_score:.1f}/100 |",
        f"| 检测模式数 | {len(assessment.detected_patterns)} |",
        f"| 问题句子数 | {len(assessment.problematic_sentences)} |",
        "",
    ]

    if assessment.detected_patterns:
        report_lines.append("## 检测到的AI写作模式")
        report_lines.append("")
        for pattern in assessment.detected_patterns:
            report_lines.append(f"- {pattern}")
        report_lines.append("")

    if assessment.problematic_sentences:
        report_lines.append("## 问题句子与修改建议")
        report_lines.append("")
        report_lines.append("| # | 句子 | 模式 | 修改建议 |")
        report_lines.append("|---|------|------|----------|")
        for i, ps in enumerate(assessment.problematic_sentences, 1):
            sentence = ps.get("sentence", "")[:100].replace("|", "\\|")
            pattern = ps.get("pattern", "").replace("|", "\\|")
            suggestion = ps.get("suggestion", "").replace("|", "\\|")
            report_lines.append(f"| {i} | {sentence} | {pattern} | {suggestion} |")
        report_lines.append("")

    report_lines.append("## 建议")
    report_lines.append("")
    if assessment.risk_level.value == "high":
        report_lines.append("⚠️ **风险较高**，建议使用 `scholarpilot run` 重新执行去AI味处理，或手动修改上述问题句子。")
    elif assessment.risk_level.value == "medium":
        report_lines.append("⚡ **风险适中**，建议针对性修改上述问题句子，特别是高频模式。")
    else:
        report_lines.append("✅ **风险较低**，文本AI痕迹不明显，可以放心提交。")

    report_text = "\n".join(report_lines)
    report_path = Path(output) if output else project_dir / "analysis" / "ai_detection_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    console.print(f"\n[green]报告已保存: {report_path}[/green]")

    # 高风险时返回非零退出码
    if assessment.risk_level.value == "high":
        raise typer.Exit(1)


@app.command(name="recommend-journal")
def recommend_journal(
    project: str = typer.Argument(..., help="项目名称"),
    level: str = typer.Option("", "--level", "-l", help="期望期刊级别: CSSCI/SSCI/北大核心/普通"),
    time: str = typer.Option("不急", "--time", "-t", help="时效要求，如'6个月内见刊'"),
    paid: str = typer.Option("可以接受", "--paid", "-p", help="是否接受收费期刊"),
    output: str = typer.Option("", "--output", "-o", help="报告输出路径"),
):
    """期刊推荐——基于论文信息匹配目标期刊.

    \b
    科研场景：论文完成后，选择合适的期刊投稿。
    系统根据论文主题、质量、时效要求推荐5-8本期刊，
    并给出"冲刺-匹配-保底"三层投稿梯队策略。

    \b
    用法:
      scholarpilot recommend-journal debt_paper
      scholarpilot recommend-journal debt_paper -l CSSCI -t "6个月内见刊"
    """
    import asyncio
    from scholarpilot.tools.submission_helper import SubmissionHelper

    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    settings = get_settings()
    from scholarpilot.llm.gateway import LLMGateway
    gateway = LLMGateway(settings)
    helper = SubmissionHelper(gateway)

    console.print(f"[dim]正在分析论文并推荐期刊...[/dim]")

    try:
        result = asyncio.run(helper.recommend_journals(
            project_dir,
            target_level=level,
            time_constraint=time,
            accept_paid=paid,
        ))
    except Exception as e:
        console.print(f"[red]推荐失败: {e}[/red]")
        raise typer.Exit(1)

    if result.get("error"):
        console.print(f"[yellow]警告: {result['error']}[/yellow]")

    recommendations = result.get("recommendations", [])
    if recommendations:
        table = Table(title="期刊推荐结果")
        table.add_column("排名", style="cyan")
        table.add_column("期刊名称")
        table.add_column("级别")
        table.add_column("匹配度")
        table.add_column("策略")

        for rec in recommendations:
            indexing = ", ".join(rec.get("indexing", []))
            table.add_row(
                str(rec.get("rank", "")),
                rec.get("journal_name", ""),
                indexing,
                str(rec.get("match_score", "")),
                rec.get("recommendation_tier", ""),
            )
        console.print(table)

    # 保存详细报告
    report_md = helper.format_journal_recommendation(result)
    report_path = Path(output) if output else project_dir / "submission" / "journal_recommendation.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    console.print(f"\n[green]详细报告已保存: {report_path}[/green]")


@app.command(name="cover-letter")
def cover_letter(
    project: str = typer.Argument(..., help="项目名称"),
    journal: str = typer.Option(..., "--journal", "-j", help="目标期刊名称"),
    author: str = typer.Option("（作者姓名）", "--author", "-a", help="通讯作者姓名"),
    affiliation: str = typer.Option("（单位）", "--affiliation", help="通讯作者单位"),
    email: str = typer.Option("（邮箱）", "--email", help="通讯作者邮箱"),
    language: str = typer.Option("中文", "--language", help="语言: 中文/英文"),
    output: str = typer.Option("", "--output", "-o", help="输出路径"),
):
    """生成投稿信（Cover Letter）.

    \b
    科研场景：向期刊投稿时需要附上 Cover Letter，
    说明论文贡献、与期刊的匹配度、原创性声明等。

    \b
    用法:
      scholarpilot cover-letter debt_paper -j "经济研究" -a "张三" --email "zhang@edu.cn"
    """
    import asyncio
    from scholarpilot.tools.submission_helper import SubmissionHelper

    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    settings = get_settings()
    from scholarpilot.llm.gateway import LLMGateway
    gateway = LLMGateway(settings)
    helper = SubmissionHelper(gateway)

    console.print(f"[dim]正在生成 Cover Letter（目标期刊: {journal}）...[/dim]")

    try:
        letter = asyncio.run(helper.generate_cover_letter(
            project_dir,
            target_journal=journal,
            corresponding_author=author,
            affiliation=affiliation,
            email=email,
            language=language,
        ))
    except Exception as e:
        console.print(f"[red]生成失败: {e}[/red]")
        raise typer.Exit(1)

    console.print(Panel(letter[:500] + ("..." if len(letter) > 500 else ""), title=f"Cover Letter → {journal}"))

    letter_path = Path(output) if output else project_dir / "submission" / f"cover_letter_{journal}.md"
    letter_path.parent.mkdir(parents=True, exist_ok=True)
    letter_path.write_text(letter, encoding="utf-8")
    console.print(f"\n[green]Cover Letter 已保存: {letter_path}[/green]")


@app.command(name="revision-plan")
def revision_plan(
    project: str = typer.Argument(..., help="项目名称"),
    reviews: str = typer.Option("", "--reviews", "-r", help="审稿意见文本（直接传入）"),
    reviews_file: str = typer.Option("", "--reviews-file", "-f", help="审稿意见文件路径"),
    deadline: str = typer.Option("30天", "--deadline", "-d", help="返修截止日期"),
    output: str = typer.Option("", "--output", "-o", help="报告输出路径"),
):
    """审稿意见修改计划——逐条分析审稿意见并制定修改方案.

    \b
    科研场景：收到期刊审稿意见后，需要逐条分析并制定
    可操作的修改计划。系统自动分类意见优先级、估算工作量、
    安排执行顺序，并给出回复函策略。

    \b
    用法:
      scholarpilot revision-plan debt_paper -r "审稿人1: 建议补充XX分析..."
      scholarpilot revision-plan debt_paper -f reviews.txt -d "15天"
    """
    import asyncio
    from scholarpilot.tools.submission_helper import SubmissionHelper

    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    # 获取审稿意见
    if reviews_file:
        reviews_path = Path(reviews_file)
        if not reviews_path.is_absolute():
            reviews_path = project_dir / reviews_path
        if not reviews_path.exists():
            console.print(f"[red]审稿意见文件不存在: {reviews_path}[/red]")
            raise typer.Exit(1)
        review_comments = reviews_path.read_text(encoding="utf-8")
    elif reviews:
        review_comments = reviews
    else:
        console.print("[red]请通过 --reviews 或 --reviews-file 提供审稿意见[/red]")
        raise typer.Exit(1)

    settings = get_settings()
    from scholarpilot.llm.gateway import LLMGateway
    gateway = LLMGateway(settings)
    helper = SubmissionHelper(gateway)

    console.print(f"[dim]正在分析 {len(review_comments)} 字符的审稿意见...[/dim]")

    try:
        result = asyncio.run(helper.plan_revision(
            project_dir,
            review_comments,
            revision_deadline=deadline,
        ))
    except Exception as e:
        console.print(f"[red]分析失败: {e}[/red]")
        raise typer.Exit(1)

    plans = result.get("revision_plans", [])
    if plans:
        # 统计优先级
        p0 = sum(1 for p in plans if p.get("priority") == "P0")
        p1 = sum(1 for p in plans if p.get("priority") == "P1")
        p2 = sum(1 for p in plans if p.get("priority") == "P2")

        console.print(Panel(
            f"审稿意见总数: {len(plans)}\n"
            f"P0（必须修改）: {p0}\n"
            f"P1（重要修改）: {p1}\n"
            f"P2（一般修改）: {p2}",
            title="修改计划概览",
        ))

    # 保存详细报告
    report_md = helper.format_revision_plan(result)
    report_path = Path(output) if output else project_dir / "submission" / "revision_plan.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    console.print(f"\n[green]修改计划已保存: {report_path}[/green]")


@app.command()
def dashboard(
    project: str = typer.Argument(..., help="项目名称"),
):
    """项目仪表盘——质量指标、文件清单、阶段进度一览.

    \b
    科研场景：研究者需要快速了解论文项目的整体状态和质量。
    本命令汇总所有关键指标，一眼看清"论文写到哪了、质量如何、还缺什么"。

    \b
    用法:
      scholarpilot dashboard debt_paper
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    import json

    # ===== 1. 基本信息 =====
    meta = fm.get_project_meta(project_dir) or {}
    memory = fm.load_memory(project_dir) or {}
    entries = memory.get("entries", {})
    state_path = project_dir / ".scholar" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    title = meta.get("title", "") or entries.get("topic_analysis", {}).get("value", {}).get("topic", "") or "—"
    topic = meta.get("topic", "") or "—"
    research_type = entries.get("topic_analysis", {}).get("value", {}).get("research_type", "") or "—"

    console.print(Panel(
        f"[bold cyan]{title}[/bold cyan]\n\n"
        f"研究主题: {topic}\n"
        f"研究类型: {research_type}\n"
        f"项目状态: {state.get('current_phase', 'unknown')}\n"
        f"最后运行: {(state.get('last_run_at', '') or 'N/A')[:19]}",
        title=f"📊 项目仪表盘 — {project}",
    ))

    # ===== 2. 阶段进度 =====
    phase_labels = {
        "topic_analysis": "选题分析",
        "literature_search": "文献检索",
        "spec_generation": "规格生成",
        "outline": "大纲生成",
        "data_collection": "数据采集",
        "section_writing": "逐章撰写",
        "citation_verification": "引用验证",
        "deai_polish": "去AI味+润色",
        "post_processing": "后处理",
        "completed": "已完成",
    }
    completed_phases = state.get("completed_phases", [])
    current_phase = state.get("current_phase", "")
    completed_sections = state.get("completed_sections", [])
    total_sections = state.get("total_sections", 0)

    console.print("\n[bold]阶段进度[/bold]")
    all_phases = list(phase_labels.keys())
    for phase in all_phases:
        label = phase_labels.get(phase, phase)
        if phase in completed_phases:
            console.print(f"  [green]✓ {label}[/green]")
        elif phase == current_phase:
            console.print(f"  [yellow]▶ {label}（进行中）[/yellow]")
        else:
            console.print(f"  [dim]○ {label}[/dim]")

    if total_sections:
        console.print(f"\n  章节进度: {len(completed_sections)}/{total_sections}")

    # ===== 3. 质量指标 =====
    console.print("\n[bold]质量指标[/bold]")

    # 文献统计
    lit_sources = entries.get("literature_sources", {}).get("value", {})
    if lit_sources:
        cnki = lit_sources.get("cnki_count", 0)
        ncpssd = lit_sources.get("ncpssd_count", 0)
        openalex = lit_sources.get("openalex_count", 0)
        ss = lit_sources.get("ss_count", 0)
        total_lit = cnki + ncpssd + openalex + ss
        console.print(f"  📚 文献检索: CNKI {cnki} | NCPSSD {ncpssd} | OpenAlex {openalex} | SS {ss}（共 {total_lit}）")

    # 引用验证
    cit_mgmt = entries.get("citation_management", {}).get("value", {})
    if cit_mgmt:
        total_cit = cit_mgmt.get("total", 0)
        verified = cit_mgmt.get("verified", 0)
        rate = (verified / total_cit * 100) if total_cit else 0
        rate_color = "green" if rate >= 80 else "yellow" if rate >= 50 else "red"
        console.print(f"  📋 引用验证: {verified}/{total_cit}（[{rate_color}]{rate:.0f}%[/{rate_color}]）")

    # 字数统计
    draft_dir = project_dir / "draft"
    full_draft = draft_dir / "full_draft.md"
    polished = draft_dir / "full_draft_polished.md"
    if full_draft.exists():
        orig_chars = len(full_draft.read_text(encoding="utf-8"))
        console.print(f"  📝 论文字数: 原始 {orig_chars:,} 字", end="")
        if polished.exists():
            pol_chars = len(polished.read_text(encoding="utf-8"))
            console.print(f" | 润色后 {pol_chars:,} 字")
        else:
            console.print()
    elif completed_sections:
        total_chars = 0
        for sec in completed_sections:
            sec_path = draft_dir / f"{sec}.md"
            if sec_path.exists():
                total_chars += len(sec_path.read_text(encoding="utf-8"))
        if total_chars:
            console.print(f"  📝 论文字数: {total_chars:,} 字（{len(completed_sections)} 章）")

    # 去AI味统计
    if state.get("deai_polish_completed"):
        risk_before_raw = state.get("deai_risk_before", 0)
        risk_after_raw = state.get("deai_risk_after", 0)
        # 兼容 dict 和 number 两种格式
        if isinstance(risk_before_raw, dict):
            risk_before = risk_before_raw.get("score", 0)
            risk_level_before = risk_before_raw.get("level", "")
        else:
            risk_before = float(risk_before_raw or 0)
            risk_level_before = ""
        if isinstance(risk_after_raw, dict):
            risk_after = risk_after_raw.get("score", 0)
            risk_level_after = risk_after_raw.get("level", "")
        else:
            risk_after = float(risk_after_raw or 0)
            risk_level_after = ""
        improvement = state.get("deai_improvement", 0)
        sections_processed = state.get("deai_sections_processed", 0)
        changes = state.get("deai_polish_changes", 0)
        risk_color = "green" if risk_after < 20 else "yellow" if risk_after < 50 else "red"
        level_str = f"（{risk_level_after}）" if risk_level_after else ""
        console.print(
            f"  🤖 去AI味: 风险 {risk_before:.0f}→[{risk_color}]{risk_after:.0f}[/{risk_color}]{level_str}"
            f"（改善 {improvement:.0f}%，{sections_processed} 章 {changes} 处修改）"
        )

    # 表格模板
    table_info = entries.get("table_templates", {}).get("value", {})
    if table_info:
        console.print(f"  📊 表格模板: {table_info.get('variables', 0)} 变量 × {table_info.get('models', 0)} 模型")

    # ===== 4. 文件清单 =====
    console.print("\n[bold]文件清单[/bold]")
    file_groups = {
        "规格与大纲": ["SPEC.md", "outline.md", "outline.json"],
        "草稿": ["draft/full_draft.md", "draft/full_draft_polished.md", "draft/abstract.md",
                 "draft/references.md", "draft/tables_template.md", "draft/deai_report.md"],
        "章节": None,  # 动态生成
        "文献": ["literature/references.bib"],
        "数据": ["data_collection_guide.md", "data_template.csv"],
        "导出": None,  # 动态扫描 final/
        "投稿": None,  # 动态扫描 submission/
    }

    for group_name, file_list in file_groups.items():
        if group_name == "章节":
            if draft_dir.exists():
                chapters = sorted(f for f in draft_dir.iterdir()
                                  if f.is_file() and f.name.startswith("chapter") and f.suffix == ".md")
                if chapters:
                    console.print(f"  [dim]{group_name}:[/dim]")
                    for ch in chapters:
                        size = ch.stat().st_size
                        console.print(f"    {ch.name} ({size:,} bytes)")
            continue

        if group_name == "导出":
            final_dir = project_dir / "final"
            if final_dir.exists():
                files = sorted(f for f in final_dir.iterdir() if f.is_file())
                if files:
                    console.print(f"  [dim]{group_name}:[/dim]")
                    for f in files:
                        size = f.stat().st_size
                        console.print(f"    {f.name} ({size:,} bytes)")
            continue

        if group_name == "投稿":
            sub_dir = project_dir / "submission"
            if sub_dir.exists():
                files = sorted(f for f in sub_dir.iterdir() if f.is_file())
                if files:
                    console.print(f"  [dim]{group_name}:[/dim]")
                    for f in files:
                        size = f.stat().st_size
                        console.print(f"    {f.name} ({size:,} bytes)")
            continue

        if file_list:
            existing = []
            for fname in file_list:
                fpath = project_dir / fname
                if fpath.exists():
                    size = fpath.stat().st_size
                    existing.append(f"{fname} ({size:,} bytes)")
            if existing:
                console.print(f"  [dim]{group_name}:[/dim]")
                for item in existing:
                    console.print(f"    {item}")

    # ===== 5. 投稿状态 =====
    sub_dir = project_dir / "submission"
    if sub_dir.exists() and any(sub_dir.iterdir()):
        console.print("\n[bold]投稿状态[/bold]")
        sub_files = {f.name: f for f in sub_dir.iterdir() if f.is_file()}
        if any("journal_recommendation" in n for n in sub_files):
            console.print("  [green]✓ 期刊推荐[/green]")
        if any("cover_letter" in n for n in sub_files):
            console.print("  [green]✓ Cover Letter[/green]")
        if any("revision_plan" in n for n in sub_files):
            console.print("  [green]✓ 审稿回复计划[/green]")

    # ===== 6. 下一步建议 =====
    console.print("\n[bold]下一步建议[/bold]")
    suggestions = []
    if not completed_phases or "section_writing" not in completed_phases:
        suggestions.append("运行 `scholarpilot chat -p {p} \"继续\"` 推进论文生成")
    if full_draft.exists() and not polished.exists() and "deai_polish" not in completed_phases:
        suggestions.append("运行 `scholarpilot check-ai {p}` 检测AI写作痕迹")
    if polished.exists() and not (project_dir / "final").exists():
        suggestions.append("运行 `scholarpilot export {p} -f docx` 导出Word")
    if (project_dir / "final").exists() and not sub_dir.exists():
        suggestions.append("运行 `scholarpilot recommend-journal {p}` 推荐投稿期刊")
    if sub_dir.exists() and not any("revision_plan" in f.name for f in sub_dir.iterdir()):
        suggestions.append("收到审稿意见后运行 `scholarpilot revision-plan {p}`")

    if not suggestions:
        suggestions.append("项目已完成所有阶段，可考虑导出或投稿")

    for s in suggestions:
        console.print(f"  💡 {s.replace('{p}', project)}")


@app.command("literature-matrix")
def literature_matrix(
    project: str = typer.Argument(..., help="项目名称"),
    enrich: bool = typer.Option(False, "--enrich", "-e", help="使用LLM补充研究主题/主要发现/与本文关系"),
    output: str = typer.Option("", "--output", "-o", help="输出路径（默认 literature/literature_matrix.md）"),
):
    """文献笔记矩阵——从参考文献生成结构化文献表.

    \b
    科研场景：写完论文后需要整理文献笔记，用于答辩准备、组会汇报、
    或后续研究综述。手工逐条整理耗时，本命令自动从参考文献提取结构化信息。

    \b
    用法:
      # 基础版（仅解析参考文献）
      scholarpilot literature-matrix debt_paper

      # 增强版（LLM补充研究主题和发现）
      scholarpilot literature-matrix debt_paper --enrich
    """
    import re

    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    # 优先从 references.md 解析，回退到 references.bib
    ref_md_path = project_dir / "draft" / "references.md"
    ref_bib_path = project_dir / "literature" / "references.bib"

    entries: list[dict] = []

    if ref_md_path.exists():
        entries = _parse_references_md(ref_md_path.read_text(encoding="utf-8"))
    elif ref_bib_path.exists():
        entries = _parse_references_bib(ref_bib_path.read_text(encoding="utf-8"))
    else:
        console.print("[red]未找到参考文献文件（references.md 或 references.bib）[/red]")
        raise typer.Exit(1)

    if not entries:
        console.print("[yellow]未能从参考文献中解析出条目[/yellow]")
        raise typer.Exit(1)

    console.print(f"[dim]解析到 {len(entries)} 条参考文献[/dim]")

    # 统计
    zh_count = sum(1 for e in entries if e.get("language") == "zh")
    en_count = sum(1 for e in entries if e.get("language") == "en")
    has_title = sum(1 for e in entries if e.get("title"))
    has_journal = sum(1 for e in entries if e.get("journal"))

    console.print(Panel(
        f"总条目: {len(entries)}\n"
        f"中文: {zh_count} | 英文: {en_count}\n"
        f"有标题: {has_title} | 有期刊: {has_journal}",
        title="文献统计",
    ))

    # LLM 增强
    if enrich:
        console.print("[dim]正在使用LLM补充文献信息（研究主题/主要发现/与本文关系）...[/dim]")
        try:
            entries = _enrich_literature_with_llm(project_dir, entries)
        except Exception as e:
            console.print(f"[yellow]LLM增强失败（{e}），将输出基础版[/yellow]")

    # 生成 Markdown 矩阵
    md_lines: list[str] = []
    md_lines.append("# 文献笔记矩阵")
    md_lines.append("")
    md_lines.append(f"> 自动生成自 ScholarPilot，共 {len(entries)} 条文献（中文 {zh_count}，英文 {en_count}）。")
    md_lines.append("")

    # 概览表
    md_lines.append("## 文献概览")
    md_lines.append("")
    if enrich and any(e.get("topic") for e in entries):
        md_lines.append("| 序号 | 作者 | 年份 | 标题 | 期刊 | 语言 | 研究主题 |")
        md_lines.append("|------|------|------|------|------|------|----------|")
        for e in entries:
            authors = e.get("authors", "—")
            if len(authors) > 30:
                authors = authors[:28] + "..."
            title = e.get("title", "—")
            if len(title) > 40:
                title = title[:38] + "..."
            journal = e.get("journal", "—")
            if len(journal) > 20:
                journal = journal[:18] + "..."
            md_lines.append(
                f"| {e.get('index', '')} | {authors} | {e.get('year', '—')} | "
                f"{title} | {journal} | {e.get('language', '—')} | {e.get('topic', '—')} |"
            )
    else:
        md_lines.append("| 序号 | 作者 | 年份 | 标题 | 期刊 | 语言 |")
        md_lines.append("|------|------|------|------|------|------|")
        for e in entries:
            authors = e.get("authors", "—")
            if len(authors) > 30:
                authors = authors[:28] + "..."
            title = e.get("title", "—")
            if len(title) > 40:
                title = title[:38] + "..."
            journal = e.get("journal", "—")
            if len(journal) > 20:
                journal = journal[:18] + "..."
            md_lines.append(
                f"| {e.get('index', '')} | {authors} | {e.get('year', '—')} | "
                f"{title} | {journal} | {e.get('language', '—')} |"
            )
    md_lines.append("")

    # 详细笔记（增强模式）
    if enrich and any(e.get("finding") or e.get("relation") for e in entries):
        md_lines.append("## 详细文献笔记")
        md_lines.append("")
        for e in entries:
            if not (e.get("finding") or e.get("relation") or e.get("topic")):
                continue
            md_lines.append(f"### [{e.get('index', '')}] {e.get('authors', '—')}（{e.get('year', '—')}）")
            md_lines.append("")
            md_lines.append(f"- **标题**: {e.get('title', '—')}")
            md_lines.append(f"- **期刊**: {e.get('journal', '—')}")
            md_lines.append(f"- **语言**: {e.get('language', '—')}")
            if e.get("topic"):
                md_lines.append(f"- **研究主题**: {e.get('topic')}")
            if e.get("finding"):
                md_lines.append(f"- **主要发现**: {e.get('finding')}")
            if e.get("relation"):
                md_lines.append(f"- **与本文关系**: {e.get('relation')}")
            md_lines.append("")

    md_lines.append("---")
    md_lines.append("*生成自 ScholarPilot 文献笔记矩阵模块*")

    md_content = "\n".join(md_lines)

    # 保存
    output_path = Path(output) if output else project_dir / "literature" / "literature_matrix.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md_content, encoding="utf-8")

    console.print(f"\n[green]文献笔记矩阵已生成: {output_path}[/green]")
    console.print(f"[dim]矩阵长度: {len(md_content)} 字符[/dim]")


def _parse_references_md(content: str) -> list[dict]:
    """从 references.md 解析参考文献条目.

    支持格式:
    - 中文: [n] 作者：标题，《期刊》，年份年。
    - 英文: [n] Authors, Year, "Title", *Journal*, Vol. X, No. Y, pp. Z.
    - 英文简略: [n] Author, Year.
    """
    import re

    entries: list[dict] = []
    lines = content.split("\n")
    current_section = "zh"  # 默认中文

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 检测章节切换
        if "英文" in line or "English" in line.lower() or "References" in line:
            current_section = "en"
            continue
        if "中文" in line or "Chinese" in line.lower():
            current_section = "zh"
            continue

        # 匹配 [n] 开头的条目
        match = re.match(r'^\[(\d+)\]\s*(.+)', line)
        if not match:
            continue

        index = int(match.group(1))
        rest = match.group(2).strip()
        entry: dict = {"index": index, "language": current_section}

        if current_section == "zh":
            # 中文格式: 作者：标题，《期刊》，年份年。
            # 提取作者（冒号前）
            author_match = re.match(r'^(.+?)[:：]\s*(.+)', rest)
            if author_match:
                entry["authors"] = author_match.group(1).strip()
                rest2 = author_match.group(2).strip()

                # 提取期刊（《》内）
                journal_match = re.search(r'《(.+?)》', rest2)
                if journal_match:
                    entry["journal"] = journal_match.group(1).strip()

                # 提取年份
                year_match = re.search(r'((?:19|20)\d{2})', rest2)
                if year_match:
                    entry["year"] = year_match.group(1)

                # 标题：期刊前的部分
                if journal_match:
                    title_part = rest2[:journal_match.start()].rstrip('，,。 ')
                    if title_part:
                        entry["title"] = title_part
                else:
                    # 无期刊，取年份前的部分作为标题
                    if year_match:
                        entry["title"] = rest2[:year_match.start()].rstrip('，,。 ')
            else:
                entry["authors"] = rest[:30]
        else:
            # 英文格式: Authors, Year, "Title", *Journal*, Vol. X, No. Y, pp. Z.
            # 或简略: Author, Year.

            # 提取年份
            year_match = re.search(r'((?:19|20)\d{2})', rest)
            if year_match:
                entry["year"] = year_match.group(1)
                # 作者：年份前的部分
                authors_part = rest[:year_match.start()].rstrip(', ').strip()
                if authors_part:
                    entry["authors"] = authors_part
            else:
                entry["authors"] = rest[:30]

            # 提取标题（引号内）
            title_match = re.search(r'"(.+?)"', rest)
            if title_match:
                entry["title"] = title_match.group(1).strip()

            # 提取期刊（*斜体*内）
            journal_match = re.search(r'\*(.+?)\*', rest)
            if journal_match:
                entry["journal"] = journal_match.group(1).strip()

        entries.append(entry)

    return entries


def _parse_references_bib(content: str) -> list[dict]:
    """从 references.bib 解析参考文献条目."""
    import re

    entries: list[dict] = []
    # 匹配 @article{refN, ... }
    pattern = re.compile(r'@article\{(\w+),\s*\n(.*?)\}\s*\n', re.DOTALL)

    for i, match in enumerate(pattern.finditer(content), 1):
        ref_key = match.group(1)
        body = match.group(2)

        entry: dict = {"index": i, "language": "zh"}

        # 提取各字段
        author_match = re.search(r'author\s*=\s*\{(.+?)\}', body, re.DOTALL)
        if author_match:
            authors = author_match.group(1).strip()
            entry["authors"] = authors
            # 判断语言
            if re.search(r'[\u4e00-\u9fff]', authors):
                entry["language"] = "zh"
            else:
                entry["language"] = "en"

        title_match = re.search(r'title\s*=\s*\{\{(.+?)\}\}', body, re.DOTALL)
        if title_match:
            entry["title"] = title_match.group(1).strip()
        else:
            title_match = re.search(r'title\s*=\s*\{(.+?)\}', body, re.DOTALL)
            if title_match:
                entry["title"] = title_match.group(1).strip()

        journal_match = re.search(r'journal\s*=\s*\{(.+?)\}', body, re.DOTALL)
        if journal_match:
            entry["journal"] = journal_match.group(1).strip()

        year_match = re.search(r'year\s*=\s*\{(\d+)\}', body)
        if year_match:
            entry["year"] = year_match.group(1)

        entries.append(entry)

    return entries


def _enrich_literature_with_llm(project_dir: Path, entries: list[dict]) -> list[dict]:
    """使用LLM补充文献的研究主题、主要发现、与本文关系."""
    import asyncio
    import json

    from scholarpilot.config import get_settings
    from scholarpilot.llm.gateway import LLMGateway

    settings = get_settings()
    gateway = LLMGateway(settings)

    # 加载论文标题和摘要用于"与本文关系"判断
    spec_path = project_dir / "SPEC.md"
    paper_info = ""
    if spec_path.exists():
        spec_text = spec_path.read_text(encoding="utf-8")
        # 提取研究主题
        import re
        topic_match = re.search(r'研究主题[：:]\s*(.+)', spec_text)
        if topic_match:
            paper_info = f"本文研究主题：{topic_match.group(1).strip()}"

    # 构建文献列表文本
    lit_text = ""
    for e in entries:
        lit_text += f"[{e.get('index')}] {e.get('authors', '—')}（{e.get('year', '—')}）: {e.get('title', '—')}, {e.get('journal', '—')}\n"

    prompt = f"""请分析以下参考文献列表，为每条文献补充：研究主题（10字内）、主要发现（20字内）、与本文关系（15字内）。

{paper_info}

参考文献列表：
{lit_text}

请以JSON数组格式输出，每个元素包含 index（序号）、topic（研究主题）、finding（主要发现）、relation（与本文关系）：

```json
[
  {{"index": 1, "topic": "...", "finding": "...", "relation": "..."}},
  ...
```

注意：
- 如果文献信息不完整（只有作者和年份），根据作者和年份推断可能的研究领域
- 与本文关系应具体（如"提供理论基础""对比分析""方法借鉴"等），不要泛泛而谈
- 输出必须是有效的JSON数组"""

    response = asyncio.run(gateway.chat(
        model=settings.default_writing_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    ))

    # 解析响应
    content = response.strip()
    # 提取 JSON
    json_match = re.search(r'```json\s*(.+?)\s*```', content, re.DOTALL)
    if json_match:
        content = json_match.group(1)
    else:
        # 尝试直接找数组
        arr_match = re.search(r'\[.+\]', content, re.DOTALL)
        if arr_match:
            content = arr_match.group(0)

    try:
        enrichments = json.loads(content)
        # 构建映射
        enrich_map = {e["index"]: e for e in enrichments if "index" in e}
        # 合并到 entries
        for entry in entries:
            idx = entry.get("index")
            if idx in enrich_map:
                entry["topic"] = enrich_map[idx].get("topic", "")
                entry["finding"] = enrich_map[idx].get("finding", "")
                entry["relation"] = enrich_map[idx].get("relation", "")
    except (json.JSONDecodeError, KeyError) as e:
        console.print(f"[yellow]LLM响应解析失败: {e}[/yellow]")

    return entries


@app.command("model-config")
def model_config(
    writing: str = typer.Option("", "--writing", "-w", help="设置写作模型（如 glm-4, claude-sonnet-4-20250514）"),
    analysis: str = typer.Option("", "--analysis", "-a", help="设置分析模型"),
    casual: str = typer.Option("", "--casual", "-c", help="设置轻量模型（文献检索等）"),
    show: bool = typer.Option(False, "--show", "-s", help="仅显示当前配置，不修改"),
):
    """多模型协作配置——查看和设置各阶段使用的模型.

    \b
    科研场景：不同研究阶段对模型能力要求不同。
    - 选题分析/大纲生成：需要强推理能力 → 用分析模型
    - 逐章撰写：需要长文写作能力 → 用写作模型
    - 文献检索/引用验证：轻量任务 → 用轻量模型（省钱）

    \b
    用法:
      # 查看当前配置
      scholarpilot model-config --show

      # 设置写作模型为GLM-4
      scholarpilot model-config --writing glm-4

      # 同时设置多个模型
      scholarpilot model-config --writing glm-4 --analysis glm-4 --casual glm-4
    """
    from scholarpilot.config import get_settings, reset_settings

    settings = get_settings()

    # ===== 阶段-模型映射表 =====
    phase_model_map = {
        "选题分析（Phase 1）": settings.default_analysis_model,
        "文献检索（Phase 2）": "（无需LLM，使用检索API）",
        "规格生成（Phase 3）": settings.default_writing_model,
        "大纲生成（Phase 5）": settings.default_writing_model,
        "数据采集（Phase 6.5）": settings.default_writing_model,
        "逐章撰写（Phase 7）": settings.default_writing_model,
        "摘要生成（Phase 7a）": settings.default_writing_model,
        "引用验证（Phase 7b）": "（无需LLM，使用CNKI/OpenAlex API）",
        "表格模板（Phase 7c）": settings.default_writing_model,
        "去AI味+润色（Phase 8b）": settings.default_writing_model,
        "后处理（Phase 8）": "（无需LLM，格式化处理）",
    }

    # ===== 显示当前配置 =====
    if show or (not writing and not analysis and not casual):
        console.print(Panel(
            f"[bold]当前模型配置[/bold]\n\n"
            f"写作模型: [cyan]{settings.default_writing_model}[/cyan]\n"
            f"分析模型: [cyan]{settings.default_analysis_model}[/cyan]\n"
            f"轻量模型: [cyan]{settings.default_casual_model}[/cyan]",
            title="🤖 模型配置",
        ))

        # API Key 状态
        console.print("\n[bold]API Key 状态[/bold]")
        key_status = [
            ("智谱 GLM", settings.zhipu_api_key, settings.zhipu_api_base),
            ("火山方舟", settings.ark_api_key, settings.ark_api_base),
            ("Claude", settings.claude_api_key, "https://api.anthropic.com"),
            ("OpenAI", settings.openai_api_key, "https://api.openai.com"),
            ("DeepSeek", settings.deepseek_api_key, "https://api.deepseek.com"),
        ]
        key_table = Table(title="API Key 状态")
        key_table.add_column("提供商", style="cyan")
        key_table.add_column("状态", style="white")
        key_table.add_column("API Base", style="dim")
        for name, key, base in key_status:
            status = "[green]✓ 已配置[/green]" if key else "[red]✗ 未配置[/red]"
            key_table.add_row(name, status, base)
        console.print(key_table)

        # 阶段-模型映射
        console.print("\n[bold]阶段-模型映射[/bold]")
        phase_table = Table(title="各阶段使用的模型")
        phase_table.add_column("阶段", style="white")
        phase_table.add_column("模型", style="cyan")
        for phase, model in phase_model_map.items():
            phase_table.add_row(phase, model)
        console.print(phase_table)

        # 模型选择建议
        console.print("\n[bold]模型选择建议[/bold]")
        suggestions = [
            ("智谱 GLM-4", "性价比高，中文写作质量好，适合国内学术写作"),
            ("智谱 GLM-4-Plus", "更强的推理能力，适合复杂分析阶段"),
            ("Claude Sonnet 4", "英文写作最佳，适合SSCI/SCI投稿"),
            ("GPT-4o", "通用能力强，适合分析阶段"),
            ("DeepSeek Chat", "成本最低，适合轻量任务"),
        ]
        sug_table = Table(title="可用模型推荐")
        sug_table.add_column("模型", style="cyan")
        sug_table.add_column("适用场景", style="white")
        for model, scenario in suggestions:
            sug_table.add_row(model, scenario)
        console.print(sug_table)

        if not writing and not analysis and not casual:
            console.print(
                "\n[dim]提示：使用 --writing / --analysis / --casual 修改模型配置[/dim]"
            )
            console.print(
                "[dim]配置将写入 .env 文件，重启后生效[/dim]"
            )
        return

    # ===== 修改配置 =====
    changes: list[str] = []

    if writing:
        # 写入 .env
        _update_env_var("SCHOLAR_DEFAULT_WRITING_MODEL", writing)
        changes.append(f"写作模型 → {writing}")

    if analysis:
        _update_env_var("SCHOLAR_DEFAULT_ANALYSIS_MODEL", analysis)
        changes.append(f"分析模型 → {analysis}")

    if casual:
        _update_env_var("SCHOLAR_DEFAULT_CASUAL_MODEL", casual)
        changes.append(f"轻量模型 → {casual}")

    if changes:
        console.print(Panel(
            "\n".join(f"[green]✓ {c}[/green]" for c in changes),
            title="配置已更新",
        ))
        console.print("[yellow]请重新运行命令以使新配置生效[/yellow]")
        reset_settings()


def _update_env_var(key: str, value: str) -> None:
    """更新 .env 文件中的环境变量（不存在则追加）."""
    from scholarpilot.config import _find_env_file

    env_path = _find_env_file()

    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")


@app.command()
def init():
    """首次使用引导——交互式配置 API Key 和默认模型.

    \b
    科研场景：研究者首次安装 ScholarPilot 后，面对众多配置项可能不知从何下手。
    本命令通过交互式问答，3步完成配置：
    1. 选择 LLM 提供商并输入 API Key
    2. 确认默认模型（写作/分析/轻量）
    3. （可选）配置 Semantic Scholar API Key

    \b
    用法:
      scholarpilot init
    """
    from scholarpilot.config import get_settings

    settings = get_settings()

    console.print(Panel(
        "[bold cyan]欢迎使用 ScholarPilot![/bold cyan]\n\n"
        "AI 辅助学术研究全流程工具\n"
        "面向高校教师、硕士/博士研究生\n\n"
        "[dim]本引导将帮你完成 3 步配置，约 2 分钟。[/dim]",
        title="🚀 ScholarPilot 初始化",
    ))

    # ===== Step 1: 选择 LLM 提供商 =====
    console.print("\n[bold]第 1 步：选择 LLM 提供商[/bold]")
    console.print("[dim]ScholarPilot 支持多个 LLM 提供商，至少配置一个。[/dim]\n")

    providers = [
        ("1", "智谱 GLM-4", "zhipu", "国产模型，性价比高，中文写作质量好（推荐国内用户）",
         "https://open.bigmodel.cn"),
        ("2", "火山方舟（豆包）", "ark", "国产模型，国内直连，OpenAI 兼容",
         "https://www.volcengine.com/product/ark"),
        ("3", "Claude (Anthropic)", "claude", "英文写作最佳，适合 SSCI/SCI 投稿",
         "https://console.anthropic.com"),
        ("4", "OpenAI GPT", "openai", "通用分析能力强",
         "https://platform.openai.com"),
        ("5", "DeepSeek", "deepseek", "成本最低，适合轻量任务",
         "https://platform.deepseek.com"),
    ]

    for num, name, _, desc, url in providers:
        console.print(f"  [{num}] [cyan]{name}[/cyan] — {desc}")
        console.print(f"      [dim]获取 API Key: {url}[/dim]")

    console.print()
    choice = typer.prompt(
        "选择提供商（输入数字）",
        default="1",
    )

    # 匹配选择
    selected = None
    for num, name, key, desc, url in providers:
        if choice == num:
            selected = (num, name, key, desc, url)
            break

    if not selected:
        console.print(f"[red]无效选择: {choice}[/red]")
        raise typer.Exit(1)

    _, name, provider_key, _, url = selected
    console.print(f"\n[green]已选择: {name}[/green]")

    # 检查是否已配置
    env_map = {
        "zhipu": ("SCHOLAR_ZHIPU_API_KEY", "zhipu_api_key"),
        "ark": ("SCHOLAR_ARK_API_KEY", "ark_api_key"),
        "claude": ("SCHOLAR_CLAUDE_API_KEY", "claude_api_key"),
        "openai": ("SCHOLAR_OPENAI_API_KEY", "openai_api_key"),
        "deepseek": ("SCHOLAR_DEEPSEEK_API_KEY", "deepseek_api_key"),
    }

    env_key, settings_key = env_map[provider_key]
    current_key = getattr(settings, settings_key, "")

    if current_key:
        console.print(f"[yellow]检测到已配置 API Key: {current_key[:8]}...[/yellow]")
        overwrite = typer.confirm("是否覆盖？", default=False)
        if not overwrite:
            console.print("[dim]保留现有 API Key[/dim]")
        else:
            current_key = ""
    else:
        console.print(f"[dim]尚未配置 API Key[/dim]")

    if not current_key:
        console.print(f"\n请前往 [link={url}]{url}[/link] 获取 API Key")
        api_key = typer.prompt("粘贴 API Key", hide_input=True)

        if not api_key.strip():
            console.print("[red]API Key 不能为空[/red]")
            raise typer.Exit(1)

        # 写入 .env
        _update_env_var(env_key, api_key.strip())
        console.print(f"[green]✓ API Key 已保存到 .env[/green]")

        # 如果是智谱，额外写入 api_base 和默认模型
        if provider_key == "zhipu":
            _update_env_var("SCHOLAR_ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4/")
            _update_env_var("SCHOLAR_ZHIPU_DEFAULT_MODEL", "glm-4")
        elif provider_key == "ark":
            _update_env_var("SCHOLAR_ARK_API_BASE", "https://ark.cn-beijing.volces.com/api/v3")
            ark_model = typer.prompt("输入火山方舟 Endpoint ID（如 ep-2024xxxx）", default="")
            if ark_model.strip():
                _update_env_var("SCHOLAR_ARK_DEFAULT_MODEL", ark_model.strip())

    # ===== Step 2: 确认默认模型 =====
    console.print("\n[bold]第 2 步：确认默认模型[/bold]")
    console.print("[dim]ScholarPilot 分阶段使用模型：写作/分析/轻量。可统一用一个，也可分开配置。[/dim]\n")

    # 根据提供商推荐模型
    model_recommendations = {
        "zhipu": ("glm-4", "glm-4", "glm-4"),
        "ark": ("doubao-pro-32k", "doubao-pro-32k", "doubao-lite-32k"),
        "claude": ("claude-sonnet-4-20250514", "claude-sonnet-4-20250514", "claude-sonnet-4-20250514"),
        "openai": ("gpt-4o", "gpt-4o", "gpt-4o-mini"),
        "deepseek": ("deepseek/deepseek-chat", "deepseek/deepseek-chat", "deepseek/deepseek-chat"),
    }

    writing_rec, analysis_rec, casual_rec = model_recommendations[provider_key]

    use_recommended = typer.confirm(
        f"使用推荐配置？（写作={writing_rec}, 分析={analysis_rec}, 轻量={casual_rec}）",
        default=True,
    )

    if use_recommended:
        writing_model = writing_rec
        analysis_model = analysis_rec
        casual_model = casual_rec
    else:
        writing_model = typer.prompt("写作模型", default=writing_rec)
        analysis_model = typer.prompt("分析模型", default=analysis_rec)
        casual_model = typer.prompt("轻量模型", default=casual_rec)

    _update_env_var("SCHOLAR_DEFAULT_WRITING_MODEL", writing_model)
    _update_env_var("SCHOLAR_DEFAULT_ANALYSIS_MODEL", analysis_model)
    _update_env_var("SCHOLAR_DEFAULT_CASUAL_MODEL", casual_model)
    console.print(f"[green]✓ 默认模型已保存[/green]")

    # ===== Step 3: Semantic Scholar API Key（可选）=====
    console.print("\n[bold]第 3 步：Semantic Scholar API Key（可选）[/bold]")
    console.print("[dim]Semantic Scholar 是英文文献检索源之一。配置 API Key 可避免限流。[/dim]")

    if settings.ss_api_key:
        console.print("[yellow]检测到已配置 Semantic Scholar API Key[/yellow]")
        skip_ss = typer.confirm("保留现有配置？", default=True)
        if not skip_ss:
            ss_key = typer.prompt("输入新的 Semantic Scholar API Key（留空跳过）", default="")
            if ss_key.strip():
                _update_env_var("SCHOLAR_SS_API_KEY", ss_key.strip())
                console.print("[green]✓ Semantic Scholar API Key 已更新[/green]")
    else:
        ss_key = typer.prompt("输入 Semantic Scholar API Key（留空跳过，后续可配置）", default="")
        if ss_key.strip():
            _update_env_var("SCHOLAR_SS_API_KEY", ss_key.strip())
            console.print("[green]✓ Semantic Scholar API Key 已保存[/green]")
        else:
            console.print("[dim]已跳过（不影响中文文献检索，仅影响英文文献检索速率）[/dim]")

    # ===== 完成总结 =====
    console.print(Panel(
        f"[bold green]✓ 配置完成！[/bold green]\n\n"
        f"LLM 提供商: [cyan]{name}[/cyan]\n"
        f"写作模型: [cyan]{writing_model}[/cyan]\n"
        f"分析模型: [cyan]{analysis_model}[/cyan]\n"
        f"轻量模型: [cyan]{casual_model}[/cyan]\n\n"
        f"[bold]下一步：[/bold]\n"
        f"  1. 创建论文项目: [cyan]scholarpilot new my_paper[/cyan]\n"
        f"  2. 查看示例模板: [cyan]scholarpilot examples[/cyan]\n"
        f"  3. 开始生成论文: [cyan]scholarpilot chat -p my_paper \"研究主题\"[/cyan]\n"
        f"  4. 查看命令文档: [cyan]scholarpilot --help[/cyan]",
        title="🎉 初始化完成",
    ))


@app.command()
def vpn(
    wait: bool = typer.Option(False, "--wait", "-w", help="等待 VPN 连接成功（轮询 120 秒）"),
    timeout: int = typer.Option(120, "--timeout", help="等待超时秒数（配合 --wait 使用）"),
    databases: str = typer.Option("", "--databases", "-d", help="指定探测的数据库（逗号分隔，如 cnki,wanfang,wos）"),
):
    """检测 EasyConnect VPN 连接状态和机构数据库可达性.

    \b
    科研场景：文献检索和全文下载前，确认 VPN 是否已连接。
    VPN 连接后系统出口 IP 变为机构 IP，可访问 CNKI、万方、WoS 等付费数据库。
    若 VPN 未连接，全文下载仅尝试 OA 源（arXiv/Unpaywall）。

    \b
    用法:
      scholarpilot vpn                    # 检测当前 VPN 状态
      scholarpilot vpn --wait             # 等待用户启动 EasyConnect 后连接成功
      scholarpilot vpn --databases cnki   # 仅探测 CNKI
    """
    import asyncio

    async def _run():
        from scholarpilot.utils.vpn import get_vpn_detector

        detector = get_vpn_detector()

        db_list = None
        if databases:
            db_list = [d.strip() for d in databases.split(",") if d.strip()]

        if wait:
            console.print(f"[yellow]等待 VPN 连接（超时 {timeout} 秒）...[/yellow]")
            console.print("[dim]请启动 EasyConnect 并完成登录[/dim]")
            status = await detector.wait_for_vpn(
                timeout=timeout, databases=db_list, poll_interval=5,
            )
        else:
            status = await detector.check_vpn(databases=db_list)

        return status

    status = asyncio.run(_run())

    # 状态面板
    if status.connected:
        console.print(Panel(
            f"[bold green]✓ VPN 已连接[/bold green]\n"
            f"可达数据库: {', '.join(status.accessible_databases) if status.accessible_databases else '无'}\n"
            f"检测IP: {status.detected_ip}\n"
            f"检测时间: {status.check_time}",
            title="VPN 状态",
        ))

        # 延迟表格
        if status.latency_ms:
            table = Table(title="数据库延迟", show_header=True)
            table.add_column("数据库", style="cyan")
            table.add_column("延迟(ms)", justify="right")
            table.add_column("状态", justify="center")
            for db, latency in status.latency_ms.items():
                ok = db in status.accessible_databases
                table.add_row(
                    db,
                    f"{latency:.0f}",
                    "[green]可达[/green]" if ok else "[red]不可达[/red]",
                )
            console.print(table)
    else:
        console.print(Panel(
            f"[bold red]✗ VPN 未连接[/bold red]\n"
            f"原因: {status.error or '未知'}\n"
            f"EasyConnect 进程: {'运行中' if status.process_running else '未运行'}\n\n"
            f"[yellow]请通过 EasyConnect 登录 VPN：[/yellow]\n"
            f"  程序路径: C:\\Program Files (x86)\\Sangfor\\SSL\\EasyConnect\\EasyConnect.exe\n"
            f"  登录后重新运行: scholarpilot vpn",
            title="VPN 状态",
        ))
        raise typer.Exit(1)


@app.command(name="pdf")
def pdf_download(
    doi: str = typer.Option("", "--doi", help="论文 DOI（如 10.1016/j.jfineco.2023.01.001）"),
    title: str = typer.Option("", "--title", help="论文标题（用于文件命名）"),
    arxiv_id: str = typer.Option("", "--arxiv", help="arXiv ID（如 2301.00001）"),
    output_dir: str = typer.Option("", "--output", "-o", help="下载目录（默认 ./downloads）"),
    no_vpn_check: bool = typer.Option(False, "--no-vpn-check", help="跳过 VPN 检测（仅尝试 OA 源）"),
):
    """下载论文全文 PDF.

    \b
    下载策略（按优先级自动尝试）：
    1. arXiv（免费，无需 VPN）
    2. Unpaywall OA 查找（免费，自动发现开放获取版本）
    3. 出版商直接下载（需 VPN 机构 IP 认证）
    4. DOI 直接解析（最后手段）

    \b
    用法:
      scholarpilot pdf --doi 10.1016/j.jfineco.2023.01.001 --title "Fiscal Policy"
      scholarpilot pdf --arxiv 2301.00001 --title "Deep Learning Paper"
      scholarpilot pdf --doi 10.3390/e25010001 --no-vpn-check
    """
    import asyncio

    if not doi and not arxiv_id:
        console.print("[red]请提供 --doi 或 --arxiv 参数[/red]")
        raise typer.Exit(1)

    out_dir = output_dir if output_dir else "./downloads"

    async def _run():
        from scholarpilot.tools.pdf_downloader import PDFDownloadManager

        manager = PDFDownloadManager(output_dir=out_dir)
        try:
            result = await manager.download(
                doi=doi,
                title=title,
                arxiv_id=arxiv_id,
                check_vpn=not no_vpn_check,
            )
            await manager.close()
            return result
        except Exception as e:
            await manager.close()
            raise

    result = asyncio.run(_run())

    if result.success:
        size_kb = result.file_size / 1024
        size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        console.print(Panel(
            f"[bold green]✓ 下载成功[/bold green]\n"
            f"来源: {result.source.value}\n"
            f"文件: {result.file_path}\n"
            f"大小: {size_str}\n"
            f"耗时: {result.download_time:.1f}s\n"
            f"VPN: {'已使用' if result.vpn_used else '未使用'}",
            title="PDF 下载结果",
        ))
    elif result.status.value == "skipped":
        console.print(Panel(
            f"[yellow]⚠ 跳过下载[/yellow]\n"
            f"原因: {result.error}\n\n"
            f"VPN 未连接，仅 OA 源可用。如需下载付费全文：\n"
            f"  1. 启动 EasyConnect 并登录 VPN\n"
            f"  2. 运行 [cyan]scholarpilot vpn[/cyan] 确认连接\n"
            f"  3. 重新执行下载命令",
            title="PDF 下载结果",
        ))
    else:
        console.print(Panel(
            f"[bold red]✗ 下载失败[/bold red]\n"
            f"DOI: {result.doi or 'N/A'}\n"
            f"arXiv: {result.arxiv_id if hasattr(result, 'arxiv_id') else 'N/A'}\n"
            f"错误: {result.error}\n\n"
            f"可能原因：\n"
            f"  - VPN 未连接（付费源需要机构 IP 认证）\n"
            f"  - 该论文无 OA 版本\n"
            f"  - 出版商需要额外的 Shibboleth/SSO 登录",
            title="PDF 下载结果",
        ))
        raise typer.Exit(1)


@app.command(name="financial-data")
def financial_data(
    project: str = typer.Argument(..., help="项目名称"),
    data_dir: str = typer.Option("", "--dir", "-d", help="数据目录路径（默认项目下 data/ 目录）"),
    output: str = typer.Option("", "--output", "-o", help="统计输出路径（默认 .scholar/descriptive_stats.json）"),
    show_table: bool = typer.Option(True, "--table/--no-table", help="是否在终端显示统计表格"),
):
    """解析 CSMAR/RESSET 金融数据并生成描述性统计.

    \b
    科研场景：研究者从 CSMAR/RESSET 下载数据后放入 data/ 目录，
    本命令自动检测文件格式（CSV/Excel/ZIP/Stata），解析并生成描述性统计，
    结果保存到 .scholar/descriptive_stats.json，可注入论文实证章节。

    \b
    支持的数据源:
      - CSMAR（国泰安）: CSV+TXT 元数据对、ZIP 压缩包
      - RESSET（锐思）: CSV、Excel、TXT
      - 通用 CSV/Excel: 自动推断

    \b
    用法:
      scholarpilot financial-data my_paper
      scholarpilot financial-data my_paper --dir /path/to/data --no-table
      scholarpilot financial-data my_paper --output custom_stats.json
    """
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project)
    if not project_dir:
        console.print(f"[red]项目不存在: {project}[/red]")
        raise typer.Exit(1)

    # 确定数据目录
    if data_dir:
        data_path = Path(data_dir)
        if not data_path.is_absolute():
            data_path = project_dir / data_path
    else:
        data_path = project_dir / "data"

    if not data_path.exists():
        console.print(f"[red]数据目录不存在: {data_path}[/red]")
        console.print("[dim]请将 CSMAR/RESSET 导出的数据文件放入该目录[/dim]")
        raise typer.Exit(1)

    # 检查目录是否有数据文件
    supported_exts = {".csv", ".xls", ".xlsx", ".txt", ".zip", ".dta"}
    data_files = [f for f in data_path.iterdir() if f.is_file() and f.suffix.lower() in supported_exts]
    if not data_files:
        console.print(f"[red]目录中未找到数据文件: {data_path}[/red]")
        console.print(f"[dim]支持的格式: {', '.join(supported_exts)}[/dim]")
        raise typer.Exit(1)

    console.print(f"[green]发现 {len(data_files)} 个数据文件[/green]")
    for f in data_files:
        console.print(f"  [dim]- {f.name}[/dim]")

    # 处理数据
    try:
        from scholarpilot.tools.financial_data import FinancialDataProcessor
    except ImportError as e:
        console.print(f"[red]金融数据模块导入失败: {e}[/red]")
        raise typer.Exit(1)

    processor = FinancialDataProcessor()

    console.print("\n[dim]正在解析数据...[/dim]")
    result = processor.process_directory(data_path)

    if result.errors:
        console.print(f"[yellow]处理完成，{len(result.errors)} 个错误:[/yellow]")
        for err in result.errors:
            console.print(f"  [red]- {err}[/red]")

    if not result.files_processed:
        console.print("[red]未能成功处理任何文件[/red]")
        raise typer.Exit(1)

    # 生成综合统计
    stats = processor.generate_comprehensive_stats(result)

    # 保存
    if output:
        output_path = Path(output)
        if not output_path.is_absolute():
            output_path = project_dir / output_path
    else:
        output_path = project_dir / ".scholar" / "descriptive_stats.json"

    processor.save_stats_to_json(stats, output_path)
    console.print(f"\n[green]✓ 统计已保存: {output_path}[/green]")

    # 显示摘要
    summary = stats.get("summary", {})
    console.print(Panel(
        f"处理文件: {summary.get('total_files', 0)}\n"
        f"总观测值: {summary.get('total_observations', 0)}\n"
        f"数据来源: {', '.join(summary.get('data_sources', ['未知']))}\n"
        f"处理错误: {summary.get('processing_errors', 0)}",
        title="数据概览",
    ))

    # 显示统计表格
    if show_table:
        for dataset in stats.get("datasets", []):
            ds_stats = dataset.get("stats", {})
            variables = ds_stats.get("variables", {})

            # 仅显示数值型变量
            numeric_vars = {
                k: v for k, v in variables.items()
                if v.get("type") == "numeric"
            }

            if not numeric_vars:
                continue

            table = Table(
                title=f"描述性统计 — {Path(dataset.get('file', '')).name}",
                show_header=True,
            )
            table.add_column("变量", style="cyan", max_width=30)
            table.add_column("N", justify="right")
            table.add_column("均值", justify="right")
            table.add_column("标准差", justify="right")
            table.add_column("最小值", justify="right")
            table.add_column("中位数", justify="right")
            table.add_column("最大值", justify="right")

            labels = dataset.get("column_labels", {})
            for var_name, var_stats in list(numeric_vars.items())[:20]:
                label = labels.get(var_name, "")
                display = f"{var_name}" + (f"\n[dim]{label}[/dim]" if label else "")
                table.add_row(
                    display,
                    str(var_stats.get("count", 0)),
                    f"{var_stats.get('mean', 0) or 0:.4f}",
                    f"{var_stats.get('std', 0) or 0:.4f}",
                    f"{var_stats.get('min', 0) or 0:.4f}",
                    f"{var_stats.get('median', 0) or 0:.4f}",
                    f"{var_stats.get('max', 0) or 0:.4f}",
                )

            console.print(table)

            if len(numeric_vars) > 20:
                console.print(f"[dim]  ... 还有 {len(numeric_vars) - 20} 个变量未显示[/dim]")

    console.print(
        f"\n[dim]统计数据将自动注入论文实证章节。"
        f"也可手动查看: {output_path}[/dim]"
    )


@app.command()
def examples(
    list_only: bool = typer.Option(False, "--list", "-l", help="仅列出模板名称，不显示详情"),
):
    """查看示例项目模板——按学科分类的论文主题参考.

    \b
    科研场景：研究者（尤其硕士生）可能不知道怎么描述研究主题才能获得好的结果。
    本命令提供按学科分类的示例模板，包含：
    - 研究主题描述（可直接复制用于 `scholarpilot chat`）
    - 推荐的研究类型和数据来源
    - 适合的期刊级别

    \b
    用法:
      scholarpilot examples              # 查看所有模板
      scholarpilot examples --list       # 仅列出名称
    """
    templates = _get_example_templates()

    if list_only:
        for t in templates:
            console.print(f"  [cyan]{t['id']}[/cyan] — {t['title']}")
        return

    # 按学科分组
    disciplines: dict[str, list[dict]] = {}
    for t in templates:
        disc = t.get("discipline", "其他")
        disciplines.setdefault(disc, []).append(t)

    for disc, items in disciplines.items():
        console.print(f"\n[bold magenta]【{disc}】[/bold magenta]")
        for t in items:
            console.print(f"\n  [bold cyan]{t['id']}[/bold cyan]: {t['title']}")
            console.print(f"  [dim]研究类型: {t.get('research_type', '—')} | "
                          f"期刊级别: {t.get('journal_level', '—')} | "
                          f"数据来源: {t.get('data_source', '—')}[/dim]")
            console.print(f"  [dim]主题描述: {t.get('description', '')[:80]}...[/dim]")

    console.print(f"\n[dim]共 {len(templates)} 个模板。使用 `scholarpilot new --template <id>` 创建项目。[/dim]")


def _get_example_templates() -> list[dict]:
    """返回示例项目模板列表."""
    return [
        # ===== 金融学 =====
        {
            "id": "finance-governance",
            "discipline": "金融学",
            "title": "数字金融对公司治理的影响研究",
            "research_type": "实证研究",
            "journal_level": "CSSCI",
            "data_source": "CSMAR/Wind",
            "description": (
                "数字经济背景下，数字金融发展对企业治理结构的影响。"
                "以2015-2023年A股上市公司为样本，研究数字金融指数对公司治理水平的影响，"
                "关注股权集中度、董事会独立性、高管薪酬等治理维度。"
                "采用面板固定效应模型，控制公司特征和行业固定效应。"
            ),
        },
        {
            "id": "finance-green",
            "discipline": "金融学",
            "title": "绿色金融政策对企业绿色创新的影响",
            "research_type": "实证研究",
            "journal_level": "CSSCI",
            "data_source": "CSMAR/绿色金融数据库",
            "description": (
                "以《绿色金融指引》发布为准自然实验，采用双重差分法（DID）"
                "评估绿色金融政策对企业绿色创新的影响。"
                "以2010-2022年A股重污染行业上市公司为样本，"
                "因变量为绿色专利申请数量（申请+授权），使用负二项回归。"
            ),
        },
        # ===== 宏观经济学 =====
        {
            "id": "macro-fiscal",
            "discipline": "宏观经济学",
            "title": "财政分权对地方政府债务规模的影响",
            "research_type": "实证研究",
            "journal_level": "CSSCI",
            "data_source": "Wind/国家统计局/财政部",
            "description": (
                "基于2010-2022年省级面板数据，研究财政分权对地方政府债务规模的影响。"
                "核心解释变量为财政分权度（收入分权+支出分权），"
                "因变量为地方政府债务余额占GDP比重。"
                "采用动态面板GMM估计，处理内生性问题。"
                "中介变量：土地财政依赖度。调节变量：官员任期。"
            ),
        },
        {
            "id": "macro-monetary",
            "discipline": "宏观经济学",
            "title": "货币政策传导渠道的有效性比较研究",
            "research_type": "实证研究",
            "journal_level": "CSSCI",
            "data_source": "Wind/中国人民银行",
            "description": (
                "比较利率渠道、信贷渠道和资产价格渠道的货币政策传导有效性。"
                "使用2008-2023年季度数据，构建SVAR模型，"
                "通过脉冲响应函数和方差分解分析不同渠道的传导时滞和贡献度。"
                "因变量为GDP增速和CPI，核心变量为M2增速、LPR利率、社融规模。"
            ),
        },
        # ===== 微观经济学 =====
        {
            "id": "micro-innovation",
            "discipline": "微观经济学",
            "title": "企业数字化转型对劳动收入份额的影响",
            "research_type": "实证研究",
            "journal_level": "CSSCI",
            "data_source": "CSMAR/国家统计局",
            "description": (
                "以2015-2023年A股制造业上市公司为样本，"
                "研究企业数字化转型对劳动收入份额的影响。"
                "核心解释变量为数字化转型指数（文本分析法构建），"
                "因变量为劳动收入份额（支付给职工的薪酬/增加值）。"
                "采用面板固定效应模型，工具变量法处理内生性。"
                "异质性分析：行业要素密集度、企业规模、所有制。"
            ),
        },
        # ==== 产业经济学 =====
        {
            "id": "industry-digital",
            "discipline": "产业经济学",
            "title": "数字经济发展对产业结构升级的影响",
            "research_type": "实证研究",
            "journal_level": "CSSCI",
            "data_source": "国家统计局/各省统计年鉴",
            "description": (
                "以2013-2022年省级面板数据为样本，研究数字经济发展对产业结构升级的影响。"
                "核心解释变量为数字经济指数（多指标熵值法构建），"
                "因变量为产业结构合理化与高级化指数。"
                "空间计量模型（SAR/SDM）分析空间溢出效应。"
                "中介变量：技术创新。门槛变量：人力资本。"
            ),
        },
        # ===== 区域经济学 =====
        {
            "id": "region-urban",
            "discipline": "区域经济学",
            "title": "新型城镇化对城乡收入差距的影响",
            "research_type": "实证研究",
            "journal_level": "CSSCI",
            "data_source": "国家统计局/各省统计年鉴",
            "description": (
                "以2014年新型城镇化综合试点为准自然实验，采用双重差分法（DID）"
                "评估新型城镇化对城乡收入差距的影响。"
                "以2010-2022年地级市面板数据为样本，"
                "因变量为城乡居民人均可支配收入比。"
                "异质性分析：东中西区域、城市规模等级。"
                "机制分析：农业转移人口市民化、公共服务均等化。"
            ),
        },
        # ===== 国际贸易 =====
        {
            "id": "trade-rcep",
            "discipline": "国际贸易",
            "title": "RCEP生效对中国制造业出口结构的影响",
            "research_type": "实证研究",
            "journal_level": "CSSCI",
            "data_source": "UN Comtrade/海关总署",
            "description": (
                "以RCEP生效为准自然实验，采用合成控制法（SCM）"
                "评估RCEP对中国制造业出口结构的影响。"
                "以2010-2023年HS6位码产品出口数据为样本，"
                "因变量为高技术产品出口占比、出口产品多样性指数。"
                "平行趋势检验、安慰剂检验确保结果稳健。"
            ),
        },
    ]


if __name__ == "__main__":
    app()
