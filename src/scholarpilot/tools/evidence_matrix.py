"""证据矩阵构建器 — 论点-证据映射核心模块.

在论文写作前，对每篇文献进行结构化证据提取，建立"论点→证据"映射关系，
确保每个论点都有相应强度的文献支撑，并识别证据缺口。

核心能力:
    1. 从文献摘要提取结构化证据（关键发现、证据类型、证据强度、可支撑论点）
    2. 批量构建证据矩阵（并发提取，支持 batch 合并调用）
    3. 大纲生成后补充章节-论点映射
    4. 格式化为写作 prompt 可注入文本
    5. 导出人类可读的 Markdown 版本
    6. JSON 序列化持久化

典型使用流程::

    from scholarpilot.tools.evidence_matrix import EvidenceMatrixBuilder
    from scholarpilot.llm.gateway import LLMGateway

    gateway = LLMGateway(config)
    builder = EvidenceMatrixBuilder(gateway, library)

    # 批量构建证据矩阵
    matrix = await builder.build_matrix(project_papers, topic="数字经济与创新")

    # 大纲生成后补充章节映射
    matrix = await builder.fill_section_maps(matrix, outline_sections)

    # 格式化为写作 prompt 注入文本
    writing_context = builder.format_for_writing("三、实证分析")

    # 导出 Markdown
    markdown = matrix.to_markdown()

    # 持久化
    matrix.save("evidence_matrix.json")
    loaded = EvidenceMatrix.load("evidence_matrix.json")
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from scholarpilot.context.prompts.evidence import (
    EVIDENCE_ARGUMENT_MAPPING_PROMPT,
    EVIDENCE_EXTRACTION_PROMPT,
)
from scholarpilot.llm.gateway import LLMGateway
from scholarpilot.utils.library import GlobalLibrary
# ADR-007 P4: 证据强度枚举收敛到 models/enums.py
from scholarpilot.models.enums import EvidenceStrength

logger = logging.getLogger(__name__)

__all__ = [
    "EvidenceType",
    "EvidenceStrength",
    "PaperEvidence",
    "EvidenceAssignment",
    "SectionEvidenceMap",
    "EvidenceMatrix",
    "EvidenceMatrixBuilder",
]


# =============================================================================
# 枚举定义
# =============================================================================


class EvidenceType(str, Enum):
    """证据类型枚举.

    Attributes:
        EMPIRICAL: 实证研究——基于数据分析（回归、实验、调查等）.
        THEORETICAL: 理论研究——构建理论模型或理论框架.
        CASE: 案例研究——基于一个或少数案例的深度分析.
        REVIEW: 综述研究——对已有文献的系统梳理和评述.
        DESCRIPTIVE: 描述性研究——现状描述、统计分析（无因果推断）.
    """

    EMPIRICAL = "empirical"
    THEORETICAL = "theoretical"
    CASE = "case"
    REVIEW = "review"
    DESCRIPTIVE = "descriptive"


# ADR-007 P4: EvidenceStrength 已收敛到 models/enums.py
# 以下直接使用导入的 EvidenceStrength，不再重复定义


# =============================================================================
# 数据模型
# =============================================================================


class PaperEvidence(BaseModel):
    """单篇文献的结构化证据.

    Attributes:
        paper_id: 文献 ID（来自全局文献库）.
        title: 文献标题.
        authors: 作者列表.
        year: 发表年份.
        source: 来源/期刊.
        abstract: 摘要.
        key_findings: 关键发现列表.
        evidence_type: 证据类型.
        evidence_strength: 证据强度.
        relevance_score: 与论文主题的相关性评分（0-1）.
        usable_arguments: 可支撑论点列表.
    """

    paper_id: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: str = ""
    source: str = ""
    abstract: str = ""
    key_findings: list[str] = Field(default_factory=list)
    evidence_type: EvidenceType = EvidenceType.DESCRIPTIVE
    evidence_strength: EvidenceStrength = EvidenceStrength.UNVERIFIED
    relevance_score: float = 0.0
    usable_arguments: list[str] = Field(default_factory=list)


class EvidenceAssignment(BaseModel):
    """单个论点的证据分配.

    Attributes:
        argument: 论点文本.
        paper_ids: 支撑该论点的文献 ID 列表.
        evidence_summary: 证据摘要.
        support_direction: 支撑方向 (support/partial/contrast/background).
        gap_flag: 证据缺口标记（True 表示缺乏充分证据）.
    """

    argument: str
    paper_ids: list[str] = Field(default_factory=list)
    evidence_summary: str = ""
    support_direction: str = "support"
    gap_flag: bool = True


class SectionEvidenceMap(BaseModel):
    """章节-论点-证据映射.

    Attributes:
        section_title: 章节标题.
        key_arguments: 章节核心论点列表.
        evidence_entries: 每个论点的证据分配列表.
    """

    section_title: str
    key_arguments: list[str] = Field(default_factory=list)
    evidence_entries: list[EvidenceAssignment] = Field(default_factory=list)


class EvidenceMatrix(BaseModel):
    """证据矩阵——文献证据与论点映射的完整结构.

    Attributes:
        topic: 论文主题.
        created_at: 创建时间（ISO 格式）.
        total_papers: 文献总数.
        papers: 文献证据列表.
        section_maps: 章节映射列表.
        gap_report: 证据缺口报告.
    """

    topic: str
    created_at: str = ""
    total_papers: int = 0
    papers: list[PaperEvidence] = Field(default_factory=list)
    section_maps: list[SectionEvidenceMap] = Field(default_factory=list)
    gap_report: dict[str, Any] = Field(default_factory=dict)

    # ===== 持久化 =====

    def save(self, path: str | Path) -> Path:
        """将证据矩阵序列化保存为 JSON 文件.

        Args:
            path: 输出文件路径.

        Returns:
            保存的文件路径.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info("证据矩阵已保存: %s", path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> EvidenceMatrix:
        """从 JSON 文件加载证据矩阵.

        Args:
            path: JSON 文件路径.

        Returns:
            加载的 EvidenceMatrix 实例.
        """
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        return cls.model_validate_json(content)

    # ===== 导出 =====

    def to_markdown(self) -> str:
        """导出人类可读的 Markdown 版本.

        Returns:
            Markdown 格式的证据矩阵报告字符串.
        """
        lines: list[str] = []
        lines.append("# 证据矩阵报告")
        lines.append("")
        lines.append(f"- **论文主题**: {self.topic}")
        lines.append(f"- **创建时间**: {self.created_at}")
        lines.append(f"- **文献总数**: {self.total_papers}")
        lines.append("")

        # 证据强度分布
        strength_dist: dict[str, int] = {}
        for p in self.papers:
            key = p.evidence_strength.value
            strength_dist[key] = strength_dist.get(key, 0) + 1
        lines.append("## 一、证据强度分布")
        lines.append("")
        lines.append("| 证据强度 | 文献数 | 占比 |")
        lines.append("| --- | --- | --- |")
        for level in EvidenceStrength:
            count = strength_dist.get(level.value, 0)
            pct = f"{count / max(self.total_papers, 1) * 100:.0f}%" if self.total_papers else "0%"
            lines.append(f"| {level.value} | {count} | {pct} |")
        lines.append("")

        # 文献证据明细
        lines.append("## 二、文献证据明细")
        lines.append("")
        for i, p in enumerate(self.papers, 1):
            authors_str = "、".join(p.authors[:3])
            if len(p.authors) > 3:
                authors_str += "等"
            lines.append(f"### [{i}] {p.title}")
            lines.append(f"- **作者**: {authors_str}")
            lines.append(f"- **年份**: {p.year}")
            lines.append(f"- **来源**: {p.source}")
            lines.append(f"- **证据类型**: {p.evidence_type.value}")
            lines.append(f"- **证据强度**: {p.evidence_strength.value}")
            lines.append(f"- **相关性评分**: {p.relevance_score:.2f}")
            if p.key_findings:
                lines.append("- **关键发现**:")
                for f in p.key_findings:
                    lines.append(f"  - {f}")
            if p.usable_arguments:
                lines.append("- **可支撑论点**:")
                for a in p.usable_arguments:
                    lines.append(f"  - {a}")
            lines.append("")

        # 章节论点-证据映射
        if self.section_maps:
            lines.append("## 三、章节论点-证据映射")
            lines.append("")
            for sm in self.section_maps:
                lines.append(f"### {sm.section_title}")
                lines.append("")
                if sm.key_arguments:
                    lines.append("**核心论点**:")
                    for arg in sm.key_arguments:
                        lines.append(f"- {arg}")
                    lines.append("")
                if sm.evidence_entries:
                    lines.append("**证据分配**:")
                    lines.append("")
                    lines.append("| 论点 | 支撑文献 | 支撑方向 | 证据缺口 |")
                    lines.append("| --- | --- | --- | --- |")
                    for entry in sm.evidence_entries:
                        paper_ids_str = ", ".join(entry.paper_ids) if entry.paper_ids else "（无）"
                        gap_str = "是" if entry.gap_flag else "否"
                        lines.append(
                            f"| {entry.argument[:40]} | {paper_ids_str} | "
                            f"{entry.support_direction} | {gap_str} |"
                        )
                    lines.append("")

        # 证据缺口报告
        if self.gap_report:
            lines.append("## 四、证据缺口报告")
            lines.append("")
            gap_count = self.gap_report.get("total_gaps", 0)
            lines.append(f"- **缺口总数**: {gap_count}")
            gap_sections = self.gap_report.get("gap_sections", [])
            if gap_sections:
                lines.append("- **缺口分布**:")
                for gs in gap_sections:
                    lines.append(f"  - {gs}")
            lines.append("")

        return "\n".join(lines)


# =============================================================================
# 证据矩阵构建器
# =============================================================================


class EvidenceMatrixBuilder:
    """证据矩阵构建器.

    通过 LLM 从文献摘要提取结构化证据，建立论点-证据映射，
    并支持批量构建、章节映射补充、写作注入等能力。

    使用示例::

        gateway = LLMGateway(config)
        library = GlobalLibrary()
        builder = EvidenceMatrixBuilder(gateway, library)

        # 批量构建
        matrix = await builder.build_matrix(papers, topic="数字经济与创新")

        # 补充章节映射
        matrix = await builder.fill_section_maps(matrix, outline_sections)

        # 格式化写作注入
        text = builder.format_for_writing("三、实证分析")
    """

    def __init__(self, llm: LLMGateway, library: GlobalLibrary) -> None:
        """初始化证据矩阵构建器.

        Args:
            llm: LLM 网关实例，用于调用大模型提取证据.
            library: 全局文献库实例，用于查询文献详情.
        """
        self.llm = llm
        self.library = library
        # 当前正在构建的矩阵（供 format_for_writing 使用）
        self._current_matrix: EvidenceMatrix | None = None

    # ===== JSON 解析辅助 =====

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """从 LLM 响应中解析 JSON.

        前置清洗思考标记（如 [💭 思考]、[🔧 执行] 等），
        处理 ```json 代码块包裹和纯文本 JSON。

        Args:
            text: LLM 原始返回内容.

        Returns:
            解析后的字典，解析失败返回 None.
        """
        if not text or not text.strip():
            return None

        # 清洗思考标记
        text = re.sub(r"\[💭[^\]]*\]", "", text)
        text = re.sub(r"\[🔧[^\]]*\]", "", text)
        text = re.sub(r"\[✅[^\]]*\]", "", text)
        text = re.sub(r"\[❌[^\]]*\]", "", text)
        text = re.sub(r"\[📝[^\]]*\]", "", text)

        # 尝试提取 ```json ... ``` 代码块
        json_match = re.search(r"```(?:json)?\s*\n?(.+?)\n?```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1)

        # 尝试直接找 { ... } JSON
        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            text = brace_match.group(0)

        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    # ===== 单篇文献证据提取 =====

    async def extract_paper_evidence(
        self,
        paper: dict[str, Any],
        topic: str,
    ) -> PaperEvidence:
        """通过 LLM 提取单篇文献的结构化证据.

        Args:
            paper: 文献数据字典，应包含 title/authors/year/source/abstract 等字段.
            topic: 论文主题，用于评估相关性.

        Returns:
            PaperEvidence 结构化证据对象.
        """
        paper_id = paper.get("id", paper.get("paper_id", ""))
        title = paper.get("title", "")
        authors = paper.get("authors", [])
        year = str(paper.get("year", ""))
        source = paper.get("source", "") or paper.get("journal", "") or paper.get("venue", "")
        abstract = paper.get("abstract", "")

        # 摘要为空时直接返回未验证证据
        if not abstract or not abstract.strip():
            logger.warning("文献 [%s] 摘要为空，标记为 unverified", title[:30])
            return PaperEvidence(
                paper_id=paper_id,
                title=title,
                authors=authors if isinstance(authors, list) else [str(authors)],
                year=year,
                source=source,
                abstract="",
                key_findings=[],
                evidence_type=EvidenceType.DESCRIPTIVE,
                evidence_strength=EvidenceStrength.UNVERIFIED,
                relevance_score=0.0,
                usable_arguments=[],
            )

        # 格式化作者字符串
        if isinstance(authors, list):
            authors_str = "、".join(authors[:5])
            if len(authors) > 5:
                authors_str += "等"
        else:
            authors_str = str(authors)

        prompt = EVIDENCE_EXTRACTION_PROMPT.format(
            topic=topic,
            title=title,
            authors=authors_str,
            year=year,
            source=source,
            abstract=abstract[:2000],  # 截断避免 token 超限
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2000,
            )
        except Exception as e:
            logger.error("LLM 提取证据失败 [%s]: %s", title[:30], e)
            return PaperEvidence(
                paper_id=paper_id,
                title=title,
                authors=authors if isinstance(authors, list) else [str(authors)],
                year=year,
                source=source,
                abstract=abstract,
                evidence_strength=EvidenceStrength.UNVERIFIED,
            )

        result = self._extract_json(response)
        if not result:
            logger.warning("LLM 返回格式异常，无法解析 [%s]", title[:30])
            return PaperEvidence(
                paper_id=paper_id,
                title=title,
                authors=authors if isinstance(authors, list) else [str(authors)],
                year=year,
                source=source,
                abstract=abstract,
                evidence_strength=EvidenceStrength.UNVERIFIED,
            )

        # 解析证据类型
        evidence_type = self._parse_evidence_type(result.get("evidence_type", ""))

        # 解析证据强度（保守策略：降级处理）
        evidence_strength = self._parse_evidence_strength(
            result.get("evidence_strength", "")
        )

        # 保守策略：如果文献无 DOI 且来源不明，强制降级
        doi = paper.get("doi", "")
        if not doi and not source:
            if evidence_strength == EvidenceStrength.STRONG:
                evidence_strength = EvidenceStrength.MODERATE
                logger.debug("文献 [%s] 无 DOI 且来源不明，strong→moderate", title[:30])

        return PaperEvidence(
            paper_id=paper_id,
            title=title,
            authors=authors if isinstance(authors, list) else [str(authors)],
            year=year,
            source=source,
            abstract=abstract,
            key_findings=result.get("key_findings", []),
            evidence_type=evidence_type,
            evidence_strength=evidence_strength,
            relevance_score=self._estimate_relevance(abstract, topic),
            usable_arguments=result.get("usable_arguments", []),
        )

    @staticmethod
    def _parse_evidence_type(value: str) -> EvidenceType:
        """解析证据类型字符串为枚举.

        Args:
            value: LLM 返回的证据类型字符串.

        Returns:
            EvidenceType 枚举值，无法匹配时默认 DESCRIPTIVE.
        """
        value_lower = (value or "").strip().lower()
        for et in EvidenceType:
            if et.value in value_lower or value_lower in et.value:
                return et
        return EvidenceType.DESCRIPTIVE

    @staticmethod
    def _parse_evidence_strength(value: str) -> EvidenceStrength:
        """解析证据强度字符串为枚举.

        遵循保守策略：无法确定时降级为 WEAK 或 UNVERIFIED.

        Args:
            value: LLM 返回的证据强度字符串.

        Returns:
            EvidenceStrength 枚举值，无法匹配时默认 UNVERIFIED.
        """
        value_lower = (value or "").strip().lower()
        for es in EvidenceStrength:
            if es.value in value_lower or value_lower in es.value:
                return es
        return EvidenceStrength.UNVERIFIED

    @staticmethod
    def _estimate_relevance(abstract: str, topic: str) -> float:
        """粗略估计文献与论文主题的相关性评分.

        基于主题关键词在摘要中的命中率计算（0-1）。

        Args:
            abstract: 文献摘要.
            topic: 论文主题.

        Returns:
            相关性评分（0.0-1.0）.
        """
        if not abstract or not topic:
            return 0.0
        # 提取主题关键词（2字以上的中文词或英文词）
        keywords = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", topic.lower())
        if not keywords:
            return 0.5
        abstract_lower = abstract.lower()
        hits = sum(1 for kw in keywords if kw.lower() in abstract_lower)
        return round(hits / len(keywords), 2)

    # ===== 批量构建证据矩阵 =====

    async def build_matrix(
        self,
        project_papers: list[dict[str, Any]],
        topic: str,
        outline_sections: list[dict[str, Any]] | None = None,
        batch_size: int = 10,
        max_papers: int = 30,
    ) -> EvidenceMatrix:
        """批量构建证据矩阵.

        将文献分批处理（batch_size 篇合并为单次 LLM 调用），
        使用 asyncio.gather + Semaphore 控制并发。

        Args:
            project_papers: 项目文献列表，每项为文献数据字典.
            topic: 论文主题.
            outline_sections: 大纲章节列表（可选，提供则同时构建章节映射）.
            batch_size: 每批处理的文献数量.
            max_papers: 最大处理文献数（避免过多 API 调用）.
            batch_size: 每批文献数量.
            max_papers: 最大文献数.

        Returns:
            EvidenceMatrix 证据矩阵.
        """
        # 限制文献数量
        papers_to_process = project_papers[:max_papers]
        logger.info(
            "开始构建证据矩阵: %d 篇文献（上限 %d），主题='%s'",
            len(papers_to_process), max_papers, topic,
        )

        # 分批处理
        batches = [
            papers_to_process[i:i + batch_size]
            for i in range(0, len(papers_to_process), batch_size)
        ]

        semaphore = asyncio.Semaphore(3)  # 并发控制：最多 3 个批次同时处理

        async def _process_batch(batch: list[dict[str, Any]]) -> list[PaperEvidence]:
            async with semaphore:
                # 批内串行（单篇提取），批间并发
                results = []
                for paper in batch:
                    try:
                        evidence = await self.extract_paper_evidence(paper, topic)
                        results.append(evidence)
                    except Exception as e:
                        logger.error("提取文献证据异常 [%s]: %s", paper.get("title", "")[:30], e)
                        # 异常时返回未验证证据
                        results.append(PaperEvidence(
                            paper_id=paper.get("id", ""),
                            title=paper.get("title", ""),
                            authors=paper.get("authors", []),
                            year=str(paper.get("year", "")),
                            source=paper.get("source", ""),
                            abstract=paper.get("abstract", ""),
                            evidence_strength=EvidenceStrength.UNVERIFIED,
                        ))
                return results

        # 并发处理所有批次
        batch_results = await asyncio.gather(*[_process_batch(b) for b in batches])
        all_papers: list[PaperEvidence] = []
        for batch_result in batch_results:
            all_papers.extend(batch_result)

        # 构建矩阵
        matrix = EvidenceMatrix(
            topic=topic,
            created_at=datetime.now().isoformat(),
            total_papers=len(all_papers),
            papers=all_papers,
        )

        # 如果提供了大纲章节，构建章节映射
        if outline_sections:
            matrix = await self.fill_section_maps(matrix, outline_sections)

        # 生成缺口报告
        matrix.gap_report = self._build_gap_report(matrix)

        self._current_matrix = matrix
        logger.info(
            "证据矩阵构建完成: %d 篇文献，%d 个章节映射",
            matrix.total_papers, len(matrix.section_maps),
        )
        return matrix

    # ===== 章节论点-证据映射 =====

    async def fill_section_maps(
        self,
        matrix: EvidenceMatrix,
        outline_sections: list[dict[str, Any]],
    ) -> EvidenceMatrix:
        """大纲生成后补充章节-论点映射.

        对每个大纲章节，利用证据池生成论点-证据映射。

        Args:
            matrix: 已构建的证据矩阵.
            outline_sections: 大纲章节列表，每项含:
                - title: 章节标题
                - key_points: 章节关键点（列表或字符串）

        Returns:
            更新后的 EvidenceMatrix（section_maps 已填充）.
        """
        if not matrix.papers:
            logger.warning("证据矩阵为空，无法构建章节映射")
            return matrix

        # 构建证据池文本
        evidence_pool = self._format_evidence_pool(matrix.papers)

        semaphore = asyncio.Semaphore(3)

        async def _map_section(section: dict[str, Any]) -> SectionEvidenceMap:
            async with semaphore:
                section_title = section.get("title", "未命名章节")
                key_points = section.get("key_points", [])
                if isinstance(key_points, list):
                    key_points_str = "\n".join(f"- {p}" for p in key_points)
                else:
                    key_points_str = str(key_points)

                prompt = EVIDENCE_ARGUMENT_MAPPING_PROMPT.format(
                    section_title=section_title,
                    key_points=key_points_str or "（未提供关键点）",
                    evidence_pool=evidence_pool,
                )

                try:
                    response = await self.llm.chat(
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3,
                        max_tokens=3000,
                    )
                except Exception as e:
                    logger.error("章节映射 LLM 调用失败 [%s]: %s", section_title, e)
                    return SectionEvidenceMap(section_title=section_title)

                result = self._extract_json(response)
                if not result:
                    logger.warning("章节映射 JSON 解析失败 [%s]", section_title)
                    return SectionEvidenceMap(section_title=section_title)

                # 构建证据分配列表
                entries: list[EvidenceAssignment] = []
                for entry_data in result.get("evidence_entries", []):
                    entries.append(EvidenceAssignment(
                        argument=entry_data.get("argument", ""),
                        paper_ids=entry_data.get("paper_ids", []),
                        evidence_summary=entry_data.get("evidence_summary", ""),
                        support_direction=entry_data.get("support_direction", "support"),
                        gap_flag=entry_data.get("gap_flag", True),
                    ))

                return SectionEvidenceMap(
                    section_title=section_title,
                    key_arguments=result.get("key_arguments", []),
                    evidence_entries=entries,
                )

        # 并发处理所有章节
        section_maps = await asyncio.gather(
            *[_map_section(s) for s in outline_sections]
        )
        matrix.section_maps = list(section_maps)

        # 更新缺口报告
        matrix.gap_report = self._build_gap_report(matrix)

        self._current_matrix = matrix
        logger.info("章节映射完成: %d 个章节", len(matrix.section_maps))
        return matrix

    @staticmethod
    def _format_evidence_pool(papers: list[PaperEvidence]) -> str:
        """将文献证据列表格式化为证据池文本（供 LLM prompt 注入）.

        Args:
            papers: 文献证据列表.

        Returns:
            格式化后的证据池文本.
        """
        if not papers:
            return "（证据池为空）"

        lines: list[str] = []
        for i, p in enumerate(papers, 1):
            authors_str = "、".join(p.authors[:3])
            if len(p.authors) > 3:
                authors_str += "等"
            lines.append(f"[paper_id={p.paper_id}] {authors_str}（{p.year}）{p.title}")
            lines.append(f"  证据类型: {p.evidence_type.value} | 证据强度: {p.evidence_strength.value}")
            if p.key_findings:
                for f in p.key_findings[:3]:
                    lines.append(f"  - 发现: {f}")
            if p.usable_arguments:
                for a in p.usable_arguments[:3]:
                    lines.append(f"  - 可支撑: {a}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _build_gap_report(matrix: EvidenceMatrix) -> dict[str, Any]:
        """构建证据缺口报告.

        统计所有章节中标记为 gap_flag=True 的论点。

        Args:
            matrix: 证据矩阵.

        Returns:
            缺口报告字典，含 total_gaps 和 gap_sections.
        """
        total_gaps = 0
        gap_sections: list[str] = []

        for sm in matrix.section_maps:
            section_gaps = sum(1 for e in sm.evidence_entries if e.gap_flag)
            if section_gaps > 0:
                total_gaps += section_gaps
                gap_sections.append(
                    f"{sm.section_title}: {section_gaps} 个缺口"
                )

        # 证据强度分布
        strength_dist: dict[str, int] = {}
        for p in matrix.papers:
            key = p.evidence_strength.value
            strength_dist[key] = strength_dist.get(key, 0) + 1

        return {
            "total_gaps": total_gaps,
            "gap_sections": gap_sections,
            "strength_distribution": strength_dist,
            "weak_ratio": round(
                (strength_dist.get("weak", 0) + strength_dist.get("unverified", 0))
                / max(matrix.total_papers, 1), 2
            ),
        }

    # ===== 写作注入格式化 =====

    def format_for_writing(self, section_title: str) -> str:
        """格式化指定章节的证据映射为写作 prompt 可注入文本.

        输出格式包含论点、支撑文献（含证据强度标注）、证据缺口标记，
        供章节撰写阶段注入到写作 prompt 中。

        Args:
            section_title: 章节标题.

        Returns:
            格式化的证据注入文本。如果当前矩阵为空或未找到章节，返回提示文本.
        """
        if not self._current_matrix:
            return "（证据矩阵尚未构建，无法提供证据注入）"

        matrix = self._current_matrix

        # 查找匹配的章节映射
        section_map: SectionEvidenceMap | None = None
        for sm in matrix.section_maps:
            if section_title in sm.section_title or sm.section_title in section_title:
                section_map = sm
                break

        if not section_map:
            # 未找到章节映射，返回该主题的全局证据概要
            return self._format_global_evidence(matrix, section_title)

        lines: list[str] = []
        lines.append(f"### 章节证据注入：{section_title}")
        lines.append("")

        # 核心论点
        if section_map.key_arguments:
            lines.append("**本章核心论点**:")
            for i, arg in enumerate(section_map.key_arguments, 1):
                lines.append(f"{i}. {arg}")
            lines.append("")

        # 论点-证据映射
        if section_map.evidence_entries:
            lines.append("**论点-证据映射**:")
            lines.append("")
            for entry in section_map.evidence_entries:
                # 证据缺口标记
                gap_marker = " [⚠️ 证据缺口]" if entry.gap_flag else ""
                lines.append(f"- **论点**: {entry.argument}{gap_marker}")

                if entry.paper_ids:
                    # 标注每篇文献的证据强度
                    support_papers: list[str] = []
                    for pid in entry.paper_ids:
                        strength = self._get_paper_strength(matrix, pid)
                        support_papers.append(f"{pid}({strength})")
                    lines.append(f"  - 支撑文献: {', '.join(support_papers)}")
                else:
                    lines.append("  - 支撑文献: （无直接支撑文献）")

                lines.append(f"  - 支撑方向: {entry.support_direction}")
                if entry.evidence_summary:
                    lines.append(f"  - 证据摘要: {entry.evidence_summary}")
                lines.append("")

        # 证据缺口提示
        gap_entries = [e for e in section_map.evidence_entries if e.gap_flag]
        if gap_entries:
            lines.append("**证据缺口提示**:")
            lines.append("以下论点缺乏充分证据支撑，写作时应注意:")
            for entry in gap_entries:
                lines.append(f"- {entry.argument}")
            lines.append("建议：补充相关文献，或采用更谨慎的表述方式。")
            lines.append("")

        return "\n".join(lines)

    def _format_global_evidence(
        self,
        matrix: EvidenceMatrix,
        section_title: str,
    ) -> str:
        """格式化全局证据概要（未找到特定章节映射时的兜底）.

        Args:
            matrix: 证据矩阵.
            section_title: 章节标题.

        Returns:
            全局证据概要文本.
        """
        lines: list[str] = []
        lines.append(f"### 全局证据概要（章节: {section_title}）")
        lines.append("")
        lines.append(f"论文主题: {matrix.topic}")
        lines.append(f"可用文献: {matrix.total_papers} 篇")
        lines.append("")

        # 按证据强度排序展示
        sorted_papers = sorted(
            matrix.papers,
            key=lambda p: {
                EvidenceStrength.STRONG: 0,
                EvidenceStrength.MODERATE: 1,
                EvidenceStrength.WEAK: 2,
                EvidenceStrength.UNVERIFIED: 3,
            }.get(p.evidence_strength, 4),
        )

        lines.append("**可用文献证据（按强度排序）**:")
        lines.append("")
        for p in sorted_papers[:15]:  # 最多展示 15 篇
            authors_str = "、".join(p.authors[:2])
            if len(p.authors) > 2:
                authors_str += "等"
            strength_tag = f"[{p.evidence_strength.value}]"
            lines.append(f"- {strength_tag} {authors_str}（{p.year}）{p.title[:50]}")
            if p.usable_arguments:
                lines.append(f"  可支撑: {p.usable_arguments[0]}")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _get_paper_strength(matrix: EvidenceMatrix, paper_id: str) -> str:
        """获取指定文献的证据强度标注.

        Args:
            matrix: 证据矩阵.
            paper_id: 文献 ID.

        Returns:
            证据强度字符串（如 "strong"/"moderate"/"weak"/"unverified"）.
        """
        for p in matrix.papers:
            if p.paper_id == paper_id:
                return p.evidence_strength.value
        return "unknown"
