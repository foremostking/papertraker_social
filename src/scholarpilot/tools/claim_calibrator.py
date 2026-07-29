"""Claim 校准器 — 结论-证据匹配校验核心模块.

在论文去AI味处理后，对每段核心结论句（Claim）进行校准：
1. 提取每章核心结论句（识别"因此""综上""研究表明"等标记）
2. 判断结论类型（因果/相关/描述/规范/方法论）
3. 校准结论是否有对应引用支撑
4. 标记"结论越界"（如数据只支撑相关性，但结论写了因果性）
5. 生成 Claim 校准报告（claim_calibration_report.md）

核心设计：Actor-Critic 双代理模式
- 对 overreach 判断增加二次确认（独立 prompt 再审一次）
- 报告作为"建议"而非"强制修改"，不自动改正文

典型使用流程::

    from scholarpilot.tools.claim_calibrator import ClaimCalibrator
    from scholarpilot.llm.gateway import LLMGateway

    gateway = LLMGateway(config)
    calibrator = ClaimCalibrator(gateway)

    # 校准整篇文档
    report = await calibrator.calibrate_document(full_text, references)

    # 生成报告
    markdown = calibrator.to_markdown(report)
    report_path = project_dir / "draft" / "claim_calibration_report.md"
    report_path.write_text(markdown, encoding="utf-8")
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from scholarpilot.context.prompts.claim import (
    CLAIM_CALIBRATION_PROMPT,
    CLAIM_EXTRACTION_PROMPT,
)
from scholarpilot.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

__all__ = [
    "ClaimType",
    "ClaimIssue",
    "ClaimRecord",
    "ClaimCalibrationReport",
    "ClaimCalibrator",
]


# =============================================================================
# 枚举定义
# =============================================================================


class ClaimType(str, Enum):
    """结论类型枚举."""

    CAUSAL = "causal"              # 因果性结论
    CORRELATIONAL = "correlational"  # 相关性结论
    DESCRIPTIVE = "descriptive"    # 描述性结论
    NORMATIVE = "normative"        # 规范性结论（价值判断）
    METHODOLOGICAL = "methodological"  # 方法论结论


class ClaimIssue(str, Enum):
    """结论问题类型枚举."""

    OVERREACH = "overreach"              # 结论越界
    UNSUPPORTED = "unsupported"          # 无引用支撑
    PARTIAL_SUPPORT = "partial_support"  # 部分支撑
    MISMATCH = "mismatch"                # 图文/数据不匹配
    EXAGGERATION = "exaggeration"        # 夸大表述
    NULL = "null"                        # 无问题


# =============================================================================
# 数据模型
# =============================================================================


class ClaimRecord(BaseModel):
    """单条 Claim 校准记录."""

    section_title: str = ""
    paragraph_index: int = 0
    claim_text: str = ""
    claim_type: ClaimType = ClaimType.DESCRIPTIVE
    supporting_citations: list[str] = Field(default_factory=list)
    support_status: str = "supported"  # supported/overreach/unsupported/partial
    issue_type: ClaimIssue | None = None
    evidence_basis: str = ""
    recommendation: str = ""


class ClaimCalibrationReport(BaseModel):
    """Claim 校准汇总报告."""

    total_claims: int = 0
    supported: int = 0
    overreach: int = 0
    unsupported: int = 0
    partial: int = 0
    claims: list[ClaimRecord] = Field(default_factory=list)
    overall_integrity_score: float = 0.0
    critical_issues: list[str] = Field(default_factory=list)
    calibrated_at: str = ""


# =============================================================================
# Claim 校准器
# =============================================================================


class ClaimCalibrator:
    """Claim 校准器.

    通过 LLM 提取论文中的核心结论句，逐条校准结论与证据的匹配关系，
    识别"结论越界"（如相关性证据推出因果性结论）。

    Actor-Critic 双代理模式：对 overreach 判断增加二次确认。
    """

    # 支撑状态权重（用于计算 overall_integrity_score）
    _STATUS_WEIGHTS = {
        "supported": 1.0,
        "partial": 0.5,
        "overreach": 0.2,
        "unsupported": 0.0,
    }

    def __init__(
        self,
        llm: LLMGateway,
        evidence_matrix_data: dict[str, Any] | None = None,
    ) -> None:
        """初始化 Claim 校准器.

        Args:
            llm: LLM 网关实例.
            evidence_matrix_data: 证据矩阵数据（可选，用于交叉验证）.
        """
        self.llm = llm
        self.evidence_matrix_data = evidence_matrix_data

    # ===== JSON 解析辅助 =====

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | list[Any] | None:
        """从 LLM 响应中解析 JSON（支持对象和数组）."""
        if not text or not text.strip():
            return None

        # 清洗思考标记
        text = re.sub(r"\[💭[^\]]*\]", "", text)
        text = re.sub(r"\[🔧[^\]]*\]", "", text)
        text = re.sub(r"\[✅[^\]]*\]", "", text)
        text = re.sub(r"\[❌[^\]]*\]", "", text)

        # 尝试提取 ```json ... ``` 代码块
        json_match = re.search(r"```(?:json)?\s*\n?(.+?)\n?```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1)

        # 尝试直接解析
        try:
            return json.loads(text.strip())
        except (json.JSONDecodeError, TypeError):
            pass

        # 尝试提取 JSON 数组
        array_match = re.search(r"\[[\s\S]*\]", text)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except (json.JSONDecodeError, TypeError):
                pass

        # 尝试提取 JSON 对象
        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except (json.JSONDecodeError, TypeError):
                pass

        return None

    # ===== Claim 提取 =====

    async def extract_claims(
        self,
        section_text: str,
        section_title: str,
    ) -> list[dict[str, Any]]:
        """从章节文本提取核心结论句.

        Args:
            section_text: 章节正文.
            section_title: 章节标题.

        Returns:
            Claim 列表，每项含 text/claim_type/citations.
        """
        if not section_text or not section_text.strip():
            return []

        prompt = CLAIM_EXTRACTION_PROMPT.format(
            section_title=section_title,
            section_text=section_text[:8000],  # 截断避免超长
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=4000,
            )
        except Exception as e:
            logger.error("Claim 提取 LLM 调用失败 [%s]: %s", section_title, e)
            return []

        result = self._extract_json(response)
        if not result or not isinstance(result, list):
            logger.warning("Claim 提取 JSON 解析失败 [%s]", section_title)
            return []

        return result

    # ===== 单条 Claim 校准 =====

    async def calibrate_claim(
        self,
        claim: dict[str, Any],
        section_text: str,
        section_title: str,
        references: list[dict[str, Any]],
    ) -> ClaimRecord:
        """校准单条 Claim.

        Args:
            claim: Claim 数据（含 text/claim_type/citations）.
            section_text: 所在章节全文.
            section_title: 章节标题.
            references: 参考文献列表.

        Returns:
            ClaimRecord 校准记录.
        """
        claim_text = claim.get("text", "")
        claim_type_str = claim.get("claim_type", "descriptive")
        citations = claim.get("citations", [])

        if not claim_text:
            return ClaimRecord(
                section_title=section_title,
                claim_text="",
                support_status="unsupported",
                issue_type=ClaimIssue.UNSUPPORTED,
            )

        # 格式化参考文献详情
        references_detail = self._format_references(references, citations)

        # 格式化证据矩阵映射（如有）
        evidence_mapping = self._format_evidence_mapping(section_title)

        prompt = CLAIM_CALIBRATION_PROMPT.format(
            claim_text=claim_text,
            claim_type=claim_type_str,
            section_context=section_text[:4000],
            references_detail=references_detail,
            evidence_mapping=evidence_mapping,
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2000,
            )
        except Exception as e:
            logger.error("Claim 校准 LLM 调用失败: %s", e)
            return ClaimRecord(
                section_title=section_title,
                claim_text=claim_text,
                claim_type=self._parse_claim_type(claim_type_str),
                supporting_citations=citations,
                support_status="unsupported",
                issue_type=ClaimIssue.UNSUPPORTED,
                evidence_basis="LLM调用失败，无法校准",
            )

        result = self._extract_json(response)
        if not result or not isinstance(result, dict):
            logger.warning("Claim 校准 JSON 解析失败: %s", claim_text[:50])
            return ClaimRecord(
                section_title=section_title,
                claim_text=claim_text,
                claim_type=self._parse_claim_type(claim_type_str),
                supporting_citations=citations,
                support_status="unsupported",
                evidence_basis="JSON解析失败",
            )

        support_status = result.get("support_status", "unsupported")
        issue_type_str = result.get("issue_type", "null")

        # Actor-Critic 二次确认：对 overreach 增加独立审查
        if support_status == "overreach":
            confirmed = await self._double_check_overreach(
                claim_text, claim_type_str, section_text, references_detail
            )
            if not confirmed:
                support_status = "partial"
                issue_type_str = "partial_support"
                logger.info("overreach 二次确认未通过，降级为 partial: %s", claim_text[:50])

        return ClaimRecord(
            section_title=section_title,
            claim_text=claim_text,
            claim_type=self._parse_claim_type(claim_type_str),
            supporting_citations=citations,
            support_status=support_status,
            issue_type=self._parse_issue_type(issue_type_str),
            evidence_basis=result.get("evidence_basis", ""),
            recommendation=result.get("recommendation", ""),
        )

    async def _double_check_overreach(
        self,
        claim_text: str,
        claim_type: str,
        section_text: str,
        references_detail: str,
    ) -> bool:
        """Actor-Critic 二次确认 overreach 判断.

        Args:
            claim_text: 结论句.
            claim_type: 结论类型.
            section_text: 章节全文.
            references_detail: 参考文献详情.

        Returns:
            True 表示确认为 overreach，False 表示降级.
        """
        check_prompt = f"""## 任务：二次确认结论越界判断

### 结论句
{claim_text}

### 结论类型
{claim_type}

### 章节上下文（截断）
{section_text[:2000]}

### 参考文献详情
{references_detail[:1500]}

### 请确认该结论是否确实越界

判断标准：
- overreach：证据仅支撑相关性（如OLS回归），但结论使用因果性表述（"导致""促进""抑制"）
- 如果结论使用了因果性词汇，但研究中使用了因果识别策略（IV/DID/RD），则不算越界
- 如果结论表述谨慎（如"与...相关""存在关联"），则不算越界

请只回答 "true"（确认为overreach）或 "false"（不确认，需降级）。
"""

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": check_prompt}],
                temperature=0.1,
                max_tokens=100,
            )
            return "true" in response.strip().lower()
        except Exception as e:
            logger.warning("overreach 二次确认失败: %s", e)
            return True  # 失败时保守处理，维持原判断

    # ===== 整篇文档校准 =====

    async def calibrate_document(
        self,
        full_text: str,
        references: list[dict[str, Any]] | None = None,
    ) -> ClaimCalibrationReport:
        """校准整篇文档.

        按章节拆分 → 逐章提取 claims → 逐条校准 → 汇总报告.

        Args:
            full_text: 论文全文（Markdown 格式）.
            references: 参考文献列表（可选）.

        Returns:
            ClaimCalibrationReport 校准报告.
        """
        references = references or []
        sections = self._split_sections(full_text)

        all_claims: list[ClaimRecord] = []

        for section_title, section_text in sections:
            if not section_text.strip():
                continue

            logger.info("正在校准章节: %s", section_title)

            # 提取 claims
            claims = await self.extract_claims(section_text, section_title)
            if not claims:
                continue

            # 逐条校准（并发控制）
            semaphore = asyncio.Semaphore(3)

            async def _calibrate(claim_data: dict[str, Any], idx: int) -> ClaimRecord:
                async with semaphore:
                    record = await self.calibrate_claim(
                        claim_data, section_text, section_title, references
                    )
                    record.paragraph_index = idx
                    return record

            tasks = [_calibrate(c, i) for i, c in enumerate(claims)]
            section_records = await asyncio.gather(*tasks)
            all_claims.extend(section_records)

        # 统计汇总
        report = self._build_report(all_claims)
        logger.info(
            "Claim 校准完成: 共 %d 条，supported=%d，overreach=%d，unsupported=%d",
            report.total_claims, report.supported, report.overreach, report.unsupported,
        )
        return report

    def _build_report(self, claims: list[ClaimRecord]) -> ClaimCalibrationReport:
        """构建校准汇总报告."""
        total = len(claims)
        supported = sum(1 for c in claims if c.support_status == "supported")
        overreach = sum(1 for c in claims if c.support_status == "overreach")
        unsupported = sum(1 for c in claims if c.support_status == "unsupported")
        partial = sum(1 for c in claims if c.support_status == "partial")

        # 加权计算诚信分
        if total > 0:
            score = sum(
                self._STATUS_WEIGHTS.get(c.support_status, 0.0) for c in claims
            ) / total * 100
        else:
            score = 100.0

        # 严重问题汇总
        critical_issues: list[str] = []
        for c in claims:
            if c.support_status == "overreach":
                critical_issues.append(
                    f"[{c.section_title}] 结论越界: {c.claim_text[:60]}... → {c.recommendation}"
                )
            elif c.support_status == "unsupported":
                critical_issues.append(
                    f"[{c.section_title}] 无引用支撑: {c.claim_text[:60]}..."
                )

        return ClaimCalibrationReport(
            total_claims=total,
            supported=supported,
            overreach=overreach,
            unsupported=unsupported,
            partial=partial,
            claims=claims,
            overall_integrity_score=round(score, 1),
            critical_issues=critical_issues,
            calibrated_at=datetime.now().isoformat(),
        )

    # ===== 报告导出 =====

    def to_markdown(self, report: ClaimCalibrationReport) -> str:
        """生成 claim_calibration_report.md.

        Args:
            report: 校准报告.

        Returns:
            Markdown 格式的报告字符串.
        """
        lines: list[str] = []
        lines.append("# Claim 校准报告")
        lines.append("")
        lines.append(f"- **校准时间**: {report.calibrated_at}")
        lines.append(f"- **结论总数**: {report.total_claims}")
        lines.append(f"- **诚信评分**: {report.overall_integrity_score}/100")
        lines.append("")

        # 统计摘要
        lines.append("## 一、统计摘要")
        lines.append("")
        lines.append("| 状态 | 数量 | 占比 |")
        lines.append("| --- | --- | --- |")
        for status, label in [
            ("supported", "充分支撑"),
            ("partial", "部分支撑"),
            ("overreach", "结论越界"),
            ("unsupported", "无引用支撑"),
        ]:
            count = getattr(report, status, 0)
            pct = f"{count / max(report.total_claims, 1) * 100:.0f}%"
            lines.append(f"| {label} | {count} | {pct} |")
        lines.append("")

        # 严重问题
        if report.critical_issues:
            lines.append("## 二、严重问题")
            lines.append("")
            for issue in report.critical_issues:
                lines.append(f"- {issue}")
            lines.append("")

        # 逐条详情
        if report.claims:
            lines.append("## 三、逐条校准详情")
            lines.append("")
            for i, claim in enumerate(report.claims, 1):
                status_emoji = {
                    "supported": "✅",
                    "partial": "⚠️",
                    "overreach": "🔴",
                    "unsupported": "❌",
                }.get(claim.support_status, "❓")

                lines.append(f"### [{i}] {status_emoji} {claim.support_status}")
                lines.append(f"- **章节**: {claim.section_title}")
                lines.append(f"- **结论句**: {claim.claim_text}")
                lines.append(f"- **结论类型**: {claim.claim_type.value}")
                citations_str = "、".join(claim.supporting_citations) if claim.supporting_citations else "（无）"
                lines.append(f"- **引用文献**: {citations_str}")
                if claim.issue_type:
                    lines.append(f"- **问题类型**: {claim.issue_type.value}")
                if claim.evidence_basis:
                    lines.append(f"- **证据基础**: {claim.evidence_basis}")
                if claim.recommendation:
                    lines.append(f"- **修改建议**: {claim.recommendation}")
                lines.append("")

        return "\n".join(lines)

    # ===== 辅助方法 =====

    @staticmethod
    def _split_sections(text: str) -> list[tuple[str, str]]:
        """将全文按章节拆分.

        支持一级标题（#）和二级标题（##），
        以及中文编号（一、二、三）。

        Returns:
            (章节标题, 章节正文) 列表.
        """
        sections: list[tuple[str, str]] = []

        # 匹配 Markdown 标题或中文编号标题
        pattern = re.compile(r"^(#{1,2}\s+.+|[一二三四五六七八九十]+[、．.].+)", re.MULTILINE)
        matches = list(pattern.finditer(text))

        if not matches:
            # 无标题，整篇作为一个章节
            return [("全文", text)]

        for i, match in enumerate(matches):
            title = match.group(1).strip().lstrip("#").strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()
            sections.append((title, section_text))

        return sections

    @staticmethod
    def _parse_claim_type(value: str) -> ClaimType:
        """解析结论类型字符串为枚举."""
        value_lower = (value or "").strip().lower()
        for ct in ClaimType:
            if ct.value in value_lower or value_lower in ct.value:
                return ct
        return ClaimType.DESCRIPTIVE

    @staticmethod
    def _parse_issue_type(value: str) -> ClaimIssue | None:
        """解析问题类型字符串为枚举."""
        if not value or value.strip().lower() == "null":
            return None
        value_lower = value.strip().lower()
        for ci in ClaimIssue:
            if ci.value in value_lower or value_lower in ci.value:
                return ci
        return None

    def _format_references(
        self,
        references: list[dict[str, Any]],
        citations: list[str],
    ) -> str:
        """格式化参考文献详情（供 prompt 注入）.

        如果有引用列表，优先展示被引用的文献（通过作者/年份模糊匹配）；
        否则展示全部参考文献（最多15篇）。
        """
        if not references:
            return "（无参考文献数据）"

        lines: list[str] = []

        # 如果有引用列表，优先展示被引用的文献
        if citations:
            matched: list[dict[str, Any]] = []
            unmatched: list[dict[str, Any]] = []
            for ref in references:
                ref_authors = ref.get("authors", "")
                ref_year = ref.get("year", "")
                ref_title = ref.get("title", "")
                ref_text = ref.get("text", "")

                # 模糊匹配：引用字符串中的作者姓或年份出现在参考文献中
                is_matched = False
                for cite in citations:
                    cite_lower = cite.lower()
                    # 匹配年份
                    if ref_year and ref_year in cite:
                        is_matched = True
                        break
                    # 匹配作者姓（取前2-3个字）
                    if ref_authors:
                        author_parts = ref_authors.replace("、", " ").replace(",", " ").split()
                        for ap in author_parts:
                            if len(ap) >= 2 and ap[:2] in cite:
                                is_matched = True
                                break
                        if is_matched:
                            break
                    # 匹配标题关键词
                    if ref_title and len(ref_title) >= 4:
                        if ref_title[:4] in cite or cite in ref_text:
                            is_matched = True
                            break

                if is_matched:
                    matched.append(ref)
                else:
                    unmatched.append(ref)

            # 展示匹配的文献 + 部分未匹配的（作为上下文）
            for ref in matched[:10]:
                ref_str = f"{ref.get('authors', '')}（{ref.get('year', '')}）{ref.get('title', '')}"
                lines.append(f"- ✅ {ref_str}")
            if unmatched and len(lines) < 10:
                lines.append(f"- （其他参考文献 {len(unmatched)} 篇省略）")
        else:
            # 无引用列表，展示全部参考文献（最多15篇）
            for ref in references[:15]:
                ref_str = f"{ref.get('authors', '')}（{ref.get('year', '')}）{ref.get('title', '')}"
                lines.append(f"- {ref_str}")

        return "\n".join(lines) if lines else "（无匹配参考文献）"

    def _format_evidence_mapping(self, section_title: str) -> str:
        """格式化证据矩阵中的论点-证据映射（如有）."""
        if not self.evidence_matrix_data:
            return "（无证据矩阵数据）"

        section_maps = self.evidence_matrix_data.get("section_maps", [])
        for sm in section_maps:
            if section_title in sm.get("section_title", "") or sm.get("section_title", "") in section_title:
                lines: list[str] = []
                for entry in sm.get("evidence_entries", []):
                    arg = entry.get("argument", "")
                    papers = ", ".join(entry.get("paper_ids", []))
                    direction = entry.get("support_direction", "")
                    gap = " [缺口]" if entry.get("gap_flag") else ""
                    lines.append(f"- 论点: {arg} | 文献: {papers} | 方向: {direction}{gap}")
                return "\n".join(lines) if lines else "（该章节无证据映射）"

        return "（该章节无证据矩阵映射）"
