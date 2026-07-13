"""ScholarPilot CLI 入口.

基于 Typer + Rich 构建的命令行工具。
用户通过自然语言与 Scholar Agent 交互，Agent 直接操作项目目录。
"""

from __future__ import annotations

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
    console.print("\n[dim]输入您的研究想法，或输入 'exit' 退出。[/dim]")
    console.print("[dim]示例：我想写一篇关于中国地方政府债务风险空间溢出效应的论文[/dim]\n")

    while True:
        try:
            user_input = typer.prompt("ScholarPilot", default="", show_default=False)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]再见！[/yellow]")
            break

        if not user_input.strip():
            continue
        if user_input.strip().lower() in ("exit", "quit", "q"):
            console.print("[yellow]再见！[/yellow]")
            break

        # 启动 Scholar Agent
        import asyncio
        from scholarpilot.agent.scholar import ScholarAgent

        agent = ScholarAgent(project_dir=project_dir)
        asyncio.run(agent.run(user_input))
        break  # Agent 完成后退出


@app.command()
def new(
    name: str = typer.Argument(..., help="论文项目名称"),
    title: str = typer.Option("", "--title", "-t", help="论文标题（可选，选题后自动回填）"),
    journal: str = typer.Option("", "--journal", "-j", help="目标期刊（可选）"),
):
    """创建新的论文项目.

    可通过 --title 和 --journal 预设论文标题和目标期刊，
    也可在选题分析后由 Agent 自动回填。
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


if __name__ == "__main__":
    app()
