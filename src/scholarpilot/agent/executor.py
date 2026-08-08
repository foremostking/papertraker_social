"""任务执行器节点.

按执行计划逐步执行论文写作任务。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from scholarpilot.config import get_settings
from scholarpilot.context.engine import ContextEngine
from scholarpilot.context.prompts import get_role_prompt
from scholarpilot.llm.gateway import LLMGateway
from scholarpilot.models.plan import ExecutionPlan, ExecutionStep, StepStatus, StepType

from .state import ScholarState

logger = logging.getLogger(__name__)


async def scholar_execute_node(state: ScholarState) -> dict:
    """执行论文写作计划中的当前步骤.

    每次调用执行一个步骤，通过 LangGraph 条件边循环。
    根据 step_type 分发到不同的执行逻辑。

    支持的步骤类型：
    - LITERATURE_SEARCH: 多源文献检索
    - OUTLINE_GENERATION: 大纲生成
    - SECTION_WRITING: 章节撰写
    - CITATION_MANAGEMENT: 引用管理
    - FORMATTING: 格式化导出
    - CUSTOM: 自定义步骤

    Args:
        state: 当前 Agent 状态。

    Returns:
        包含执行结果和推进状态的状态更新字典。
    """
    execution_plan_dict = state.get("execution_plan", {})
    current_step = state.get("current_step", 0)
    project_path = state.get("project_path", "")
    paper_spec = state.get("paper_spec", {})

    if not execution_plan_dict:
        logger.warning("No execution plan in state")
        return {"current_step": 0, "completed_steps": ["no_plan"]}

    plan = ExecutionPlan(**execution_plan_dict)
    plan.current_step_index = current_step

    step = plan.get_current_step()
    if step is None:
        logger.info("All steps completed")
        return {"current_step": len(plan.steps)}

    logger.info(f"Executing step {current_step + 1}/{len(plan.steps)}: {step.name} ({step.step_type})")

    # 标记为进行中
    step.status = StepStatus.IN_PROGRESS

    # 根据步骤类型分发
    try:
        step_result = await _dispatch_step(step, project_path, paper_spec, state)
        step.status = StepStatus.COMPLETED
        step.result = step_result
    except Exception as e:
        logger.error(f"Step execution failed: {e}")
        step.status = StepStatus.FAILED
        step.result = {"error": str(e)}

    # 更新计划
    plan.steps[current_step] = step
    plan.advance()

    # 更新状态
    completed_steps = state.get("completed_steps", []) + [step.step_id]
    step_results = state.get("step_results", []) + [{
        "step_id": step.step_id,
        "name": step.name,
        "step_type": step.step_type.value,
        "status": step.status.value,
        "result": step.result,
    }]

    return {
        "execution_plan": plan.model_dump(),
        "current_step": plan.current_step_index,
        "completed_steps": completed_steps,
        "step_results": step_results,
    }


async def _dispatch_step(
    step: ExecutionStep,
    project_path: str,
    paper_spec: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """根据步骤类型分发到对应的执行逻辑.

    Args:
        step: 当前执行步骤。
        project_path: 项目目录路径。
        paper_spec: 论文规格。
        state: 完整状态。

    Returns:
        步骤执行结果。
    """
    if step.step_type == StepType.LITERATURE_SEARCH:
        return await _execute_literature_search(step, paper_spec)
    elif step.step_type == StepType.OUTLINE_GENERATION:
        return await _execute_outline_generation(step, project_path, paper_spec, state)
    elif step.step_type == StepType.SECTION_WRITING:
        return await _execute_section_writing(step, project_path, paper_spec, state)
    elif step.step_type == StepType.CITATION_MANAGEMENT:
        return await _execute_citation_management(step, project_path, state)
    elif step.step_type == StepType.PDF_DOWNLOAD:
        return await _execute_pdf_download(step, project_path, state)
    elif step.step_type == StepType.FORMATTING:
        return await _execute_formatting(step, project_path, paper_spec)
    elif step.step_type == StepType.CUSTOM:
        return await _execute_custom_step(step, paper_spec)
    else:
        return {"status": "skipped", "reason": f"Unknown step type: {step.step_type}"}


async def _execute_literature_search(
    step: ExecutionStep,
    paper_spec: dict[str, Any],
) -> dict[str, Any]:
    """执行文献检索步骤."""
    from scholarpilot.tools.search import LiteratureSearchManager
    from scholarpilot.utils.vpn import get_vpn_detector

    topic = paper_spec.get("topic", "")
    region = paper_spec.get("region", "中国")
    content = paper_spec.get("content", "")
    year_start = paper_spec.get("year_start", "2020")
    year_end = paper_spec.get("year_end", "2026")

    # 检测 VPN 状态，启用 CNKI/万方 机构 IP 认证
    detector = get_vpn_detector()
    vpn_status = await detector.check_vpn()
    if vpn_status.connected:
        logger.info(f"VPN connected, enabling institutional IP auth for CNKI/Wanfang")
    else:
        logger.warning(f"VPN not connected: {vpn_status.error}")

    manager = LiteratureSearchManager(
        ss_api_key=get_settings().ss_api_key,
        wos_api_key=get_settings().wos_api_key,
        wos_sid=get_settings().wos_sid,
        vpn_status=vpn_status,
    )
    try:
        result = await manager.search_all(
            topic=topic,
            region=region,
            content=content,
            year_start=year_start,
            year_end=year_end,
            max_per_source=20,
        )
        await manager.close()
        return {
            "total_count": result.total_count,
            "paper_count": len(result.all_papers),
            "chinese_count": (
                result.chinese_result.returned_count if result.chinese_result else 0
            ),
            "vpn_connected": vpn_status.connected,
            "all_papers": [p.to_dict() if hasattr(p, "to_dict") else p for p in result.all_papers],
        }
    except Exception as e:
        await manager.close()
        raise


async def _execute_outline_generation(
    step: ExecutionStep,
    project_path: str,
    paper_spec: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """执行大纲生成步骤."""
    config = get_settings()
    llm = LLMGateway(config)

    project_dir = Path(project_path) if project_path else None
    spec_content = json.dumps(paper_spec, ensure_ascii=False, indent=2)

    # 获取文献检索结果
    step_results = state.get("step_results", [])
    lit_summary = ""
    for sr in step_results:
        if sr.get("step_type") == "literature_search":
            lit_summary = json.dumps(sr.get("result", {}), ensure_ascii=False)
            break

    # 通过 ContextEngine 构建标准化上下文（ADR-007 P4：消除内联 prompt）
    engine = ContextEngine()
    context = engine.build_outline_context(
        spec_content=spec_content,
        research_type=paper_spec.get("research_type", "empirical"),
        literature_summary=lit_summary,
        target_journal=paper_spec.get("target_journal", "CSSCI核心期刊"),
    )

    response = await llm.chat(
        messages=context.to_messages(),
        model=config.default_writing_model,
        temperature=0.4,
    )

    # 提取 JSON
    import re
    outline_data = {}
    try:
        outline_data = json.loads(response)
    except json.JSONDecodeError:
        m = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if m:
            try:
                outline_data = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

    # 保存到文件
    if project_dir and outline_data:
        outline_path = project_dir / "outline.json"
        outline_path.parent.mkdir(parents=True, exist_ok=True)
        outline_path.write_text(
            json.dumps(outline_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # 同时保存 Markdown 版本
        md_path = project_dir / "outline.md"
        md_content = _outline_to_markdown(outline_data)
        md_path.write_text(md_content, encoding="utf-8")

    return {
        "title": outline_data.get("title", ""),
        "section_count": len(outline_data.get("sections", [])),
        "outline_path": str(project_dir / "outline.json") if project_dir else "",
    }


async def _execute_section_writing(
    step: ExecutionStep,
    project_path: str,
    paper_spec: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """执行章节撰写步骤."""
    config = get_settings()
    llm = LLMGateway(config)
    engine = ContextEngine()

    project_dir = Path(project_path) if project_path else None

    # 加载大纲
    outline_data = {}
    if project_dir:
        outline_path = project_dir / "outline.json"
        if outline_path.exists():
            outline_data = json.loads(outline_path.read_text(encoding="utf-8"))

    sections = outline_data.get("sections", [])
    paper_title = outline_data.get("title", paper_spec.get("topic", "论文"))

    # 获取文献检索结果
    step_results = state.get("step_results", [])
    lit_summary = ""
    for sr in step_results:
        if sr.get("step_type") == "literature_search":
            lit_summary = json.dumps(sr.get("result", {}), ensure_ascii=False)
            break

    written_sections = []
    previous_summaries = []

    for i, section in enumerate(sections):
        section_title = section.get("title", f"第{i+1}章")
        word_count = section.get("word_count", 2000)
        subsections = section.get("subsections", [])
        key_points = section.get("key_points", [])

        logger.info(f"Writing section: {section_title}")

        context = engine.build_section_writing_context(
            paper_title=paper_title,
            target_journal=paper_spec.get("target_journal", "CSSCI核心期刊"),
            language=paper_spec.get("language", "中文"),
            outline=json.dumps(outline_data, ensure_ascii=False),
            section_title=section_title,
            word_count=word_count,
            subsections=subsections,
            key_points=key_points,
            research_type=paper_spec.get("research_type", "empirical"),
            relevant_papers=lit_summary[:500] if lit_summary else "",
            previous_sections="\n".join(previous_summaries[-3:]) if previous_summaries else "",
        )

        response = await llm.chat(
            messages=context.to_messages(),
            model=config.default_writing_model,
            temperature=0.6,
        )

        # 保存章节
        if project_dir:
            draft_dir = project_dir / "draft"
            draft_dir.mkdir(parents=True, exist_ok=True)
            section_file = draft_dir / f"chapter{i+1:02d}.md"
            section_file.write_text(
                f"# {section_title}\n\n{response}",
                encoding="utf-8",
            )

        written_sections.append(section_title)
        previous_summaries.append(f"## {section_title}\n{response[:500]}...")

    # 合并草稿
    if project_dir:
        _merge_draft(project_dir)

    return {
        "sections_written": len(written_sections),
        "section_names": written_sections,
    }


async def _execute_citation_management(
    step: ExecutionStep,
    project_path: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    """执行引用管理步骤：提取引用→验证→格式化参考文献→附加AI声明."""
    from scholarpilot.tools.citation_manager import (
        extract_citations_from_text,
        verify_all_citations,
        format_references_list,
        generate_ai_disclosure,
    )

    project_dir = Path(project_path) if project_path else None

    if not project_dir:
        return {"status": "skipped", "reason": "no project path"}

    # 读取合并的草稿
    draft_path = project_dir / "draft" / "full_draft.md"
    if not draft_path.exists():
        return {"status": "skipped", "reason": "no draft found"}

    full_text = draft_path.read_text(encoding="utf-8")

    # 提取引用
    citations = extract_citations_from_text(full_text)
    if not citations:
        return {"status": "completed", "citations_found": 0}

    # 从 state 的 step_results 构建 literature_pool（Phase 2 文献池）
    literature_pool: list[dict] = []
    for sr in state.get("step_results", []):
        if isinstance(sr, dict) and sr.get("step_type") == "literature_search":
            result_data = sr.get("result", {})
            if isinstance(result_data, dict):
                literature_pool = result_data.get("all_papers", [])
                break

    # 从 paper_spec 构建 topic_keywords
    paper_spec = state.get("paper_spec", {})
    topic_keywords = " ".join(filter(None, [
        paper_spec.get("topic", "") if isinstance(paper_spec, dict) else "",
        paper_spec.get("region", "") if isinstance(paper_spec, dict) else "",
    ]))

    # 尝试初始化验证引擎（各自独立容错）
    cnki_engine = None
    try:
        from scholarpilot.mcp.servers.cnki.aiohttp_engine import CNKIAiohttpEngine
        cnki_engine = CNKIAiohttpEngine()
    except Exception:
        pass

    openalex_engine = None
    try:
        from scholarpilot.mcp.servers.openalex import OpenAlexEngine
        openalex_engine = OpenAlexEngine()
    except Exception:
        pass

    ss_engine = None
    try:
        from scholarpilot.mcp.servers.semantic_scholar import SemanticScholarEngine
        from scholarpilot.config import get_settings
        config = get_settings()
        ss_engine = SemanticScholarEngine(api_key=config.ss_api_key or None)
    except Exception:
        pass

    # 验证引用（传入引擎、文献池与主题关键词以提升验证命中率）
    verified_citations = await verify_all_citations(
        citations,
        cnki_engine=cnki_engine,
        openalex_engine=openalex_engine,
        ss_engine=ss_engine,
        concurrency=3,
        topic_keywords=topic_keywords,
        literature_pool=literature_pool,
    )

    # 关闭引擎
    for engine in [cnki_engine, openalex_engine]:
        if engine:
            try:
                if hasattr(engine, "close"):
                    await engine.close()
            except Exception:
                pass

    # 格式化参考文献列表
    ref_list = format_references_list(
        verified_citations,
        style="cssci",
        language_separate=True,
    )

    # AI声明
    ai_disclosure = generate_ai_disclosure(language="zh")

    # 保存参考文献列表
    ref_path = project_dir / "draft" / "references.md"
    ref_path.write_text(ref_list, encoding="utf-8")

    # 追加到完整草稿
    updated_draft = full_text + "\n\n---\n\n" + ref_list + "\n\n---\n\n" + ai_disclosure
    draft_path.write_text(updated_draft, encoding="utf-8")

    verified_count = sum(1 for c in verified_citations if c.verified)
    return {
        "status": "completed",
        "citations_found": len(verified_citations),
        "citations_verified": verified_count,
        "citations_unverified": len(verified_citations) - verified_count,
        "references_path": str(ref_path),
    }


async def _execute_formatting(
    step: ExecutionStep,
    project_path: str,
    paper_spec: dict[str, Any],
) -> dict[str, Any]:
    """执行格式化导出步骤."""
    from scholarpilot.tools.exporter import export_project

    project_dir = Path(project_path) if project_path else None

    if not project_dir:
        return {"status": "skipped", "reason": "no project path"}

    outputs = []
    try:
        docx_path = export_project(project_dir, fmt="docx")
        outputs.append(str(docx_path))
    except Exception as e:
        outputs.append(f"docx failed: {e}")

    try:
        tex_path = export_project(project_dir, fmt="latex")
        outputs.append(str(tex_path))
    except Exception as e:
        outputs.append(f"latex failed: {e}")

    return {
        "outputs": outputs,
        "status": "completed",
    }


async def _execute_pdf_download(
    step: ExecutionStep,
    project_path: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    """执行全文 PDF 下载步骤.

    从文献检索结果中提取论文信息，自动下载 PDF 全文。
    下载策略：OA 源优先（arXiv/Unpaywall）→ VPN 机构源（出版商直接下载）。
    VPN 未连接时仅尝试 OA 源，付费源跳过。

    Args:
        step: 执行步骤.
        project_path: 项目目录路径.
        state: 完整状态.

    Returns:
        下载结果摘要.
    """
    from scholarpilot.tools.pdf_downloader import PDFDownloadManager
    from scholarpilot.utils.vpn import get_vpn_detector

    project_dir = Path(project_path) if project_path else None
    if not project_dir:
        return {"status": "skipped", "reason": "no project path"}

    # 从 state 中获取文献检索结果
    step_results = state.get("step_results", [])
    papers_to_download: list[dict[str, Any]] = []

    for sr in step_results:
        if sr.get("step_type") == "literature_search":
            result_data = sr.get("result", {})
            # 从检索结果中提取论文信息
            all_papers = result_data.get("all_papers", [])
            if not all_papers:
                # 尝试从 papers 字段获取
                all_papers = result_data.get("papers", [])

            for paper in all_papers:
                doi = paper.get("doi", "")
                title = paper.get("title", "")
                arxiv_id = paper.get("arxiv_id", "")
                # 至少需要 DOI 或 arXiv ID 才能下载
                if doi or arxiv_id:
                    papers_to_download.append({
                        "doi": doi,
                        "title": title,
                        "arxiv_id": arxiv_id,
                    })
            break

    if not papers_to_download:
        logger.info("No papers with DOI/arXiv ID found for PDF download")
        return {
            "status": "completed",
            "total": 0,
            "success": 0,
            "reason": "No papers with DOI/arXiv ID found",
        }

    # 检测 VPN 状态
    config = get_settings()
    detector = get_vpn_detector()
    vpn_status = await detector.check_vpn()

    if not vpn_status.connected:
        logger.warning(
            "VPN 未连接，仅尝试 OA 源下载。"
            "请通过 EasyConnect 登录 VPN 以访问付费数据库全文资源。"
        )

    # 设置下载目录
    download_dir = project_dir / "downloads"
    if config.pdf_download_dir:
        download_dir = Path(config.pdf_download_dir)
    else:
        download_dir = project_dir / "downloads"

    # 执行批量下载
    manager = PDFDownloadManager(
        output_dir=download_dir,
        max_concurrent=config.pdf_max_concurrent,
        unpaywall_email=config.unpaywall_email,
    )

    try:
        batch_result = await manager.download_batch(
            papers=papers_to_download,
            output_dir=download_dir,
            check_vpn=False,  # 已检测
        )
        await manager.close()

        return {
            "status": "completed",
            "total": batch_result.total,
            "success": batch_result.success_count,
            "failed": batch_result.failed_count,
            "skipped": batch_result.skipped_count,
            "total_size_mb": round(batch_result.total_size / 1024 / 1024, 2),
            "vpn_connected": vpn_status.connected,
            "download_dir": str(download_dir),
        }
    except Exception as e:
        await manager.close()
        raise


async def _execute_custom_step(
    step: ExecutionStep,
    paper_spec: dict[str, Any],
) -> dict[str, Any]:
    """执行自定义步骤."""
    if step.input_prompt:
        config = get_settings()
        llm = LLMGateway(config)
        response = await llm.chat(
            messages=[
                {"role": "system", "content": get_role_prompt(None)},
                {"role": "user", "content": step.input_prompt},
            ],
            model=step.model or config.default_writing_model,
            temperature=0.5,
        )
        return {"response": response[:500]}

    return {"status": "completed", "note": "custom step with no input_prompt"}


# ===== 辅助函数 =====


def _outline_to_markdown(outline: dict[str, Any]) -> str:
    """将大纲 JSON 转为 Markdown 格式."""
    lines = []
    title = outline.get("title", "论文大纲")
    lines.append(f"# {title}")
    lines.append("")

    abstract = outline.get("abstract", "")
    if abstract:
        lines.append(f"## 摘要\n{abstract}\n")

    keywords = outline.get("keywords", [])
    if keywords:
        lines.append(f"**关键词：** {', '.join(keywords)}\n")

    sections = outline.get("sections", [])
    for i, sec in enumerate(sections):
        sec_title = sec.get("title", f"第{i+1}章")
        lines.append(f"## {sec_title}")
        lines.append("")

        key_points = sec.get("key_points", [])
        if key_points:
            lines.append("**关键点：**")
            for kp in key_points:
                lines.append(f"- {kp}")
            lines.append("")

        subsections = sec.get("subsections", [])
        for sub in subsections:
            lines.append(f"### {sub}")

        word_count = sec.get("word_count", 0)
        if word_count:
            lines.append(f"*（约{word_count}字）*")

        lines.append("")

    return "\n".join(lines)


def _merge_draft(project_dir: Path) -> None:
    """合并所有章节为完整草稿."""
    draft_dir = project_dir / "draft"
    if not draft_dir.exists():
        return

    sections = sorted(
        f for f in draft_dir.iterdir()
        if f.is_file() and f.suffix == ".md" and f.name != "full_draft.md"
    )
    if not sections:
        return

    merged = "# 论文草稿\n\n"
    for section in sections:
        content = section.read_text(encoding="utf-8")
        merged += content + "\n\n---\n\n"

    draft_path = draft_dir / "full_draft.md"
    draft_path.write_text(merged, encoding="utf-8")