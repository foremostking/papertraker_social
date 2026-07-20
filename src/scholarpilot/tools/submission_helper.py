"""投稿辅助工具——期刊推荐、Cover Letter、审稿回复.

核心功能:
    1. recommend_journals: 基于论文信息推荐5-8本目标期刊
    2. generate_cover_letter: 撰写投稿信
    3. plan_revision: 审稿意见逐条修改计划+回复函

使用示例::

    from scholarpilot.tools.submission_helper import SubmissionHelper

    helper = SubmissionHelper(gateway=gateway)
    # 期刊推荐
    result = await helper.recommend_journals(project_dir)
    # Cover Letter
    letter = await helper.generate_cover_letter(project_dir, target_journal="经济研究")
    # 审稿回复
    plan = await helper.plan_revision(project_dir, review_comments="...")
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from scholarpilot.context.prompts.submission import (
    JOURNAL_RECOMMENDATION_PROMPT,
    COVER_LETTER_PROMPT,
    REVISION_PLAN_PROMPT,
)
from scholarpilot.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

__all__ = ["SubmissionHelper", "recommend_journals", "generate_cover_letter", "plan_revision"]


class SubmissionHelper:
    """投稿辅助工具.

    提供期刊推荐、Cover Letter 生成、审稿意见修改计划三大功能。
    所有功能通过 LLM 驱动，基于已有的 submission prompt 模板。

    Args:
        gateway: LLMGateway 实例，用于调用大模型.
    """

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    # ===== 论文信息提取 =====

    def _extract_paper_info(self, project_dir: Path) -> dict[str, Any]:
        """从项目目录提取论文信息.

        从 SPEC.md、outline.json、full_draft.md 中提取：
        - 标题、摘要、关键词
        - 学科领域、研究类型、字数
        - 章节结构
        """
        info: dict[str, Any] = {
            "paper_title": "",
            "abstract": "",
            "keywords": "",
            "discipline": "经济学",
            "research_type": "empirical",
            "word_count": 0,
            "paper_structure": "",
            "paper_content": "",
            "main_findings": "",
            "contributions": "",
            "methodology": "",
            "data_status": "无数据（占位符模式）",
        }

        # 从 SPEC.md 提取
        spec_path = project_dir / "SPEC.md"
        if spec_path.exists():
            spec = spec_path.read_text(encoding="utf-8")
            # 提取标题
            title_match = re.search(r"^#\s+(.+)$", spec, re.MULTILINE)
            if title_match:
                info["paper_title"] = title_match.group(1).strip()
            # 提取研究类型
            if "实证" in spec or "empirical" in spec.lower():
                info["research_type"] = "empirical"
            elif "理论" in spec:
                info["research_type"] = "theoretical"

        # 从 outline.json 提取章节结构
        outline_path = project_dir / "outline.json"
        if outline_path.exists():
            try:
                outline = json.loads(outline_path.read_text(encoding="utf-8"))
                if isinstance(outline, dict):
                    sections = outline.get("sections", [])
                    if sections:
                        info["paper_structure"] = "\n".join(
                            f"- {s.get('title', '')}（约{s.get('word_count', '?')}字）"
                            for s in sections
                        )
            except Exception:
                pass

        # 从 full_draft.md 提取摘要和关键词
        draft_path = project_dir / "draft" / "full_draft.md"
        if not draft_path.exists():
            # 尝试 polished 版本
            draft_path = project_dir / "draft" / "full_draft_polished.md"

        if draft_path.exists():
            content = draft_path.read_text(encoding="utf-8")
            info["paper_content"] = content
            info["word_count"] = len(content)

            # 提取摘要（中文"摘要"或"Abstract"后的段落）
            abstract_match = re.search(
                r"(?:摘\s*要|Abstract)[:\s]*\n*(.+?)(?=\n\s*(?:关键词|Key\s*word|1\.|##|#))",
                content,
                re.DOTALL | re.IGNORECASE,
            )
            if abstract_match:
                info["abstract"] = abstract_match.group(1).strip()[:500]

            # 提取关键词
            kw_match = re.search(
                r"(?:关键词|Key\s*words?)[:\s]*(.+?)(?=\n\s*(?:\d|##|#|JEL|$))",
                content,
                re.DOTALL | re.IGNORECASE,
            )
            if kw_match:
                info["keywords"] = kw_match.group(1).strip()[:200]

        # 检查数据状态
        data_dir = project_dir / "data"
        if data_dir.exists():
            data_files = list(data_dir.glob("*.csv")) + list(data_dir.glob("*.xlsx")) + list(data_dir.glob("*.dta"))
            if data_files:
                info["data_status"] = f"有真实数据（{len(data_files)}个文件）"

        # 从 state.json 提取统计信息
        state_path = project_dir / ".scholar" / "state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("deai_polish_completed"):
                    info["data_status"] += "，已完成去AI味处理"
            except Exception:
                pass

        return info

    # ===== 期刊推荐 =====

    async def recommend_journals(
        self,
        project_dir: Path | str,
        target_level: str = "",
        time_constraint: str = "不急",
        accept_paid: str = "可以接受",
        other_preferences: str = "",
    ) -> dict[str, Any]:
        """推荐目标期刊.

        Args:
            project_dir: 项目目录路径.
            target_level: 期望期刊级别（如 CSSCI/SSCI/北大核心）.
            time_constraint: 发表时效要求（如"6个月内见刊"）.
            accept_paid: 是否接受收费期刊.
            other_preferences: 其他偏好.

        Returns:
            期刊推荐结果 dict，含 recommendations 列表和 tier_strategy.
        """
        project_dir = Path(project_dir)
        info = self._extract_paper_info(project_dir)

        prompt = JOURNAL_RECOMMENDATION_PROMPT.format(
            paper_title=info["paper_title"] or "未命名论文",
            abstract=info["abstract"] or "（未提取到摘要）",
            keywords=info["keywords"] or "（未提取到关键词）",
            discipline=info["discipline"],
            research_type=info["research_type"],
            quality_level="中等（AI辅助生成，需人工打磨）",
            word_count=info["word_count"],
            target_level=target_level or "不限（推荐时说明）",
            time_constraint=time_constraint,
            accept_paid=accept_paid,
            other_preferences=other_preferences or "无",
        )

        response = await self.gateway.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4000,
        )

        # 解析 JSON
        result = self._parse_json_response(response)
        if not result:
            return {
                "recommendations": [],
                "raw_response": response,
                "error": "LLM返回格式异常，无法解析为JSON",
            }

        return result

    # ===== Cover Letter =====

    async def generate_cover_letter(
        self,
        project_dir: Path | str,
        target_journal: str,
        corresponding_author: str = "（作者姓名）",
        author_list: str = "（作者列表）",
        affiliation: str = "（单位）",
        email: str = "（邮箱）",
        title: str = "（职称）",
        language: str = "中文",
    ) -> str:
        """生成投稿信（Cover Letter）.

        Args:
            project_dir: 项目目录路径.
            target_journal: 目标期刊名称.
            corresponding_author: 通讯作者姓名.
            author_list: 作者列表.
            affiliation: 通讯作者单位.
            email: 通讯作者邮箱.
            title: 通讯作者职称.
            language: 语言（中文/英文）.

        Returns:
            Cover Letter 文本.
        """
        project_dir = Path(project_dir)
        info = self._extract_paper_info(project_dir)

        prompt = COVER_LETTER_PROMPT.format(
            paper_title=info["paper_title"] or "未命名论文",
            abstract=info["abstract"] or "（未提取到摘要）",
            keywords=info["keywords"] or "（未提取到关键词）",
            contributions=info.get("contributions", "（请参见论文正文的主要贡献部分）"),
            methodology=info.get("methodology", "（请参见论文研究设计章节）"),
            main_findings=info.get("main_findings", "（请参见论文实证结果章节）"),
            target_journal=target_journal,
            journal_scope="（请作者根据期刊官网补充）",
            editor_name="",
            submission_section="",
            corresponding_author=corresponding_author,
            author_list=author_list,
            affiliation=affiliation,
            email=email,
            title=title,
            language=language,
        )

        response = await self.gateway.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=2000,
        )

        return response.strip()

    # ===== 审稿意见修改计划 =====

    async def plan_revision(
        self,
        project_dir: Path | str,
        review_comments: str,
        revision_deadline: str = "30天",
    ) -> dict[str, Any]:
        """制定审稿意见修改计划.

        Args:
            project_dir: 项目目录路径.
            review_comments: 审稿意见全文（多个审稿人的意见）.
            revision_deadline: 返修截止日期.

        Returns:
            修改计划 dict，含 revision_plans 列表和 execution_order.
        """
        project_dir = Path(project_dir)
        info = self._extract_paper_info(project_dir)

        # 截断论文内容，避免超出 token 限制
        paper_content = info["paper_content"]
        if len(paper_content) > 20000:
            paper_content = paper_content[:20000] + "\n\n（论文内容已截断...）"

        prompt = REVISION_PLAN_PROMPT.format(
            review_comments=review_comments,
            paper_title=info["paper_title"] or "未命名论文",
            paper_structure=info["paper_structure"] or "（未提取到章节结构）",
            word_count=info["word_count"],
            data_status=info["data_status"],
            revision_deadline=revision_deadline,
            paper_content=paper_content,
        )

        response = await self.gateway.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=6000,
        )

        result = self._parse_json_response(response)
        if not result:
            return {
                "revision_plans": [],
                "raw_response": response,
                "error": "LLM返回格式异常，无法解析为JSON",
            }

        return result

    # ===== 辅助函数 =====

    @staticmethod
    def _parse_json_response(text: str) -> dict[str, Any] | None:
        """从 LLM 响应中解析 JSON.

        处理 ```json 代码块包裹和思考标记。
        """
        # 清理思考标记
        text = re.sub(r"\[💭[^\]]*\]", "", text)
        text = re.sub(r"\[🔧[^\]]*\]", "", text)

        # 尝试提取 ```json ... ``` 代码块
        json_match = re.search(r"```(?:json)?\s*\n?(.+?)\n?```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1)

        # 尝试直接找 { 开头的 JSON
        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            text = brace_match.group(0)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def format_journal_recommendation(self, result: dict[str, Any]) -> str:
        """将期刊推荐结果格式化为 Markdown.

        Args:
            result: recommend_journals 返回的结果.

        Returns:
            Markdown 格式的推荐报告.
        """
        lines = ["# 期刊推荐报告", ""]

        recommendations = result.get("recommendations", [])
        if not recommendations:
            lines.append("（未获取到推荐结果）")
            lines.append("")
            if result.get("raw_response"):
                lines.append("## LLM 原始回复")
                lines.append("```")
                lines.append(result["raw_response"][:2000])
                lines.append("```")
            return "\n".join(lines)

        lines.append("## 推荐期刊列表")
        lines.append("")
        lines.append("| 排名 | 期刊名称 | 级别 | 影响因子 | 审稿周期 | 录用率 | 匹配度 | 投稿策略 |")
        lines.append("|------|----------|------|----------|----------|--------|--------|----------|")

        for rec in recommendations:
            rank = rec.get("rank", "")
            name = rec.get("journal_name", "")
            indexing = ", ".join(rec.get("indexing", []))
            impact = rec.get("impact_factor", "未知")
            review_cycle = rec.get("review_cycle", "未知")
            acceptance = rec.get("acceptance_rate", "未知")
            match_score = rec.get("match_score", "")
            tier = rec.get("recommendation_tier", "")
            lines.append(f"| {rank} | {name} | {indexing} | {impact} | {review_cycle} | {acceptance} | {match_score} | {tier} |")

        lines.append("")

        # 详细推荐
        lines.append("## 详细推荐")
        lines.append("")
        for rec in recommendations:
            lines.append(f"### {rec.get('rank', '')}. {rec.get('journal_name', '')}")
            lines.append("")
            lines.append(f"- **主办机构**: {rec.get('publisher', '未知')}")
            lines.append(f"- **收稿范围**: {rec.get('scope', '未知')}")
            lines.append(f"- **审稿周期**: {rec.get('review_cycle', '未知')}")
            lines.append(f"- **见刊周期**: {rec.get('publication_cycle', '未知')}")
            lines.append(f"- **版面费**: {rec.get('apc', '未知')}")
            lines.append(f"- **开放获取**: {rec.get('oa_option', '未知')}")
            lines.append(f"- **投稿策略**: {rec.get('recommendation_tier', '')}")

            reasons = rec.get("match_reasons", [])
            if reasons:
                lines.append("")
                lines.append("**推荐理由**:")
                for r in reasons:
                    lines.append(f"- {r}")

            risks = rec.get("risks", [])
            if risks:
                lines.append("")
                lines.append("**风险提示**:")
                for risk in risks:
                    lines.append(f"- {risk}")

            advice = rec.get("submission_advice", "")
            if advice:
                lines.append("")
                lines.append(f"**投稿建议**: {advice}")

            lines.append("")

        # 梯队策略
        tier_strategy = result.get("tier_strategy", {})
        if tier_strategy:
            lines.append("## 投稿梯队策略")
            lines.append("")
            lines.append(f"- **冲刺**: {tier_strategy.get('sprint', '')}")
            lines.append(f"- **匹配**: {tier_strategy.get('match', '')}")
            lines.append(f"- **保底**: {tier_strategy.get('safety', '')}")
            lines.append("")

        summary = result.get("summary", "")
        if summary:
            lines.append("## 总体建议")
            lines.append("")
            lines.append(summary)

        return "\n".join(lines)

    def format_revision_plan(self, result: dict[str, Any]) -> str:
        """将审稿修改计划格式化为 Markdown.

        Args:
            result: plan_revision 返回的结果.

        Returns:
            Markdown 格式的修改计划.
        """
        lines = ["# 审稿意见修改计划", ""]

        plans = result.get("revision_plans", [])
        if not plans:
            lines.append("（未获取到修改计划）")
            return "\n".join(lines)

        lines.append("## 修改计划明细")
        lines.append("")

        for plan in plans:
            comment_id = plan.get("comment_id", "")
            reviewer = plan.get("reviewer", "")
            original = plan.get("original_text", "")
            summary = plan.get("summary", "")
            ptype = plan.get("type", "")
            category = plan.get("category", "")
            priority = plan.get("priority", "")

            lines.append(f"### {comment_id} [{priority}] {summary}")
            lines.append("")
            lines.append(f"- **审稿人**: {reviewer}")
            lines.append(f"- **意见类型**: {ptype} / {category}")
            lines.append(f"- **原文**: {original[:200]}{'...' if len(original)>200 else ''}")
            lines.append("")

            mod = plan.get("modification_plan", {})
            if mod:
                lines.append(f"- **修改操作**: {mod.get('action', '')}")
                lines.append(f"- **修改方案**: {mod.get('details', '')}")
                if mod.get("new_content_outline"):
                    lines.append(f"- **新增内容要点**: {mod['new_content_outline']}")
                if mod.get("content_to_remove"):
                    lines.append(f"- **需删除内容**: {mod['content_to_remove']}")

            location = plan.get("location", {})
            if location:
                lines.append(f"- **修改位置**: {location.get('section', '')} / {location.get('paragraph', '')}")

            workload = plan.get("estimated_workload", {})
            if workload:
                lines.append(f"- **预计工作量**: {workload.get('time_hours', '?')}小时, {workload.get('word_count_change', '?')}")
                if workload.get("external_resources_needed"):
                    lines.append(f"- **外部资源**: {workload['external_resources_needed']}")

            deps = plan.get("dependencies", [])
            if deps:
                lines.append(f"- **依赖关系**: {'; '.join(deps)}")

            risks = plan.get("risks", "")
            if risks:
                lines.append(f"- **风险**: {risks}")

            response_strategy = plan.get("response_strategy", "")
            if response_strategy:
                lines.append(f"- **回复策略**: {response_strategy}")

            lines.append("")

        # 执行顺序
        execution_order = result.get("execution_order", [])
        if execution_order:
            lines.append("## 执行顺序")
            lines.append("")
            for step in execution_order:
                lines.append(f"{step}")
            lines.append("")

        # 工作量汇总
        workload_summary = result.get("workload_summary", {})
        if workload_summary:
            lines.append("## 工作量汇总")
            lines.append("")
            lines.append(f"- **总工时**: {workload_summary.get('total_hours', '?')}小时")
            lines.append(f"- **字数变化**: {workload_summary.get('total_word_change', '?')}")
            lines.append(f"- **P0（必须修改）**: {workload_summary.get('p0_count', 0)}条")
            lines.append(f"- **P1（重要修改）**: {workload_summary.get('p1_count', 0)}条")
            lines.append(f"- **P2（一般修改）**: {workload_summary.get('p2_count', 0)}条")
            ext = workload_summary.get("external_resources", [])
            if ext:
                lines.append(f"- **外部资源需求**: {'; '.join(ext)}")
            lines.append(f"- **截止日期可行性**: {workload_summary.get('deadline_feasibility', '?')}")
            lines.append("")

        # 全局策略
        global_strategy = result.get("global_strategy", "")
        if global_strategy:
            lines.append("## 总体修改策略")
            lines.append("")
            lines.append(global_strategy)

        return "\n".join(lines)


# ===== 模块级便捷函数 =====

async def recommend_journals(
    project_dir: Path | str,
    gateway: LLMGateway,
    **kwargs,
) -> dict[str, Any]:
    """便捷函数：推荐期刊."""
    helper = SubmissionHelper(gateway)
    return await helper.recommend_journals(project_dir, **kwargs)


async def generate_cover_letter(
    project_dir: Path | str,
    gateway: LLMGateway,
    target_journal: str,
    **kwargs,
) -> str:
    """便捷函数：生成 Cover Letter."""
    helper = SubmissionHelper(gateway)
    return await helper.generate_cover_letter(project_dir, target_journal, **kwargs)


async def plan_revision(
    project_dir: Path | str,
    gateway: LLMGateway,
    review_comments: str,
    **kwargs,
) -> dict[str, Any]:
    """便捷函数：制定修改计划."""
    helper = SubmissionHelper(gateway)
    return await helper.plan_revision(project_dir, review_comments, **kwargs)
