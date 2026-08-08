"""知识库构建器 - 聚合论文分析结果，生成质量基准.

本模块接收 ``PaperAnalyzer`` 的输出（``PaperAnalysis`` 对象列表），
聚合 1000+ 篇 CSSCI 论文的分析结果，构建结构化的质量基准知识库。

知识库包含四大维度:
    1. **结构基准**: 各章节类型（引言/文献综述/理论分析/研究设计/
       实证分析/稳健性检验/结论）的篇幅占比、字符数、子节数量统计.
    2. **引用基准**: 总引用量、引用密度、作者多样性、时效性分布、
       中英文比例等统计.
    3. **语言基准**: 高频学术句式模板、过渡词、平均句长等.
    4. **实证基准**: 表格数量、常用模型类型、常用稳健性方法等.

此外还提取各章节的典型开篇句、结尾句和段落结构，作为 few-shot 范例
注入到论文写作 Prompt 中，校准 AI 生成论文的质量.

数据流:
    PaperAnalysis[]  -->  build_from_analyses()  -->  self._kb (dict)
                                                        |
                                         get_benchmark_context() --> str (注入 Prompt)
                                         get_section_template()  --> dict (few-shot 范例)

存储:
    ~/.scholarpilot/benchmark/knowledge_base.json

Usage:
    from scholarpilot.benchmark.knowledge_base import KnowledgeBase

    kb = KnowledgeBase()
    kb.build_from_analyses(analyses)
    kb.save()

    # 注入到写作 Prompt
    context = kb.get_benchmark_context(section_type="引言")
    prompt = SECTION_WRITING_PROMPT + "\\n\\n" + context

    # 获取章节范例
    template = kb.get_section_template("文献综述")
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scholarpilot.benchmark.paper_analyzer import (
    CitationAnalysis,
    EmpiricalAnalysis,
    LanguageAnalysis,
    PaperAnalysis,
    SectionAnalysis,
)
# ADR-007 P4: 统一统计辅助函数到 utils/text.py
from scholarpilot.utils.text import safe_mean, safe_median, safe_stdev

logger = logging.getLogger(__name__)


# ======================================================================
# 常量
# ======================================================================

# 论文章节类型（按 CSSCI 经济/金融类论文常见结构排列）
SECTION_TYPES: list[str] = [
    "引言",
    "文献综述",
    "理论分析",
    "研究设计",
    "实证分析",
    "稳健性检验",
    "结论",
]

# 英文章节类型 → 中文章节类型映射（兼容 paper_analyzer 的英文类型名）
SECTION_TYPE_MAP: dict[str, str] = {
    "introduction": "引言",
    "literature_review": "文献综述",
    "theoretical_analysis": "理论分析",
    "research_design": "研究设计",
    "empirical_analysis": "实证分析",
    "robustness_check": "稳健性检验",
    "conclusion": "结论",
    # 中文别名
    "绪论": "引言",
    "导论": "引言",
    "前言": "引言",
    "研究综述": "文献综述",
    "文献回顾": "文献综述",
    "理论框架": "理论分析",
    "理论基础": "理论分析",
    "理论机制": "理论分析",
    "模型构建": "研究设计",
    "模型设定": "研究设计",
    "变量设定": "研究设计",
    "变量定义": "研究设计",
    "研究方法": "研究设计",
    "实证结果": "实证分析",
    "实证检验": "实证分析",
    "实证研究": "实证分析",
    "稳健性分析": "稳健性检验",
    "稳健性": "稳健性检验",
    "结论与建议": "结论",
    "结论与展望": "结论",
    "研究结论": "结论",
    "结语": "结论",
}

# 默认存储目录
DEFAULT_STORAGE_DIR: Path = Path.home() / ".scholarpilot" / "benchmark"

# 存储文件名
STORAGE_FILENAME: str = "knowledge_base.json"

# 句式模板提取数量上限
TOP_TEMPLATES_LIMIT: int = 20

# 过渡词提取数量上限
TOP_TRANSITIONS_LIMIT: int = 15

# 章节范例句子数量上限
MAX_TEMPLATE_SENTENCES: int = 5

# 模型类型 / 稳健性方法展示数量上限
TOP_MODELS_LIMIT: int = 5
TOP_ROBUSTNESS_LIMIT: int = 5


# ======================================================================
# 统计辅助函数
# ======================================================================


# ADR-007 P4: _safe_mean/median/stdev 已收敛到 utils/text.py
# 此处保留模块级别名，避免 30+ 处调用点逐个修改
_safe_mean = safe_mean
_safe_median = safe_median
_safe_stdev = safe_stdev


def _normalize_proportion(value: float) -> float:
    """将比例值统一为百分比 (0-100).

    PaperAnalysis 中 proportion 可能以 0-1 的小数或 0-100 的百分比存储.
    本函数统一转为百分比.

    Args:
        value: 比例值.

    Returns:
        百分比值 (0-100).
    """
    if value is None:
        return 0.0
    if value <= 1.0:
        return value * 100.0
    return float(value)


def _format_pct(value: float) -> str:
    """格式化百分比为一位小数字符串."""
    return f"{value:.1f}"


def _format_num(value: float) -> str:
    """格式化数值为整数（四舍五入）."""
    return f"{value:.0f}"


def _format_float(value: float) -> str:
    """格式化浮点数为一位小数."""
    return f"{value:.1f}"


def _counter_to_list(
    counter: Counter[str],
    limit: int,
) -> list[list[Any]]:
    """将 Counter 转为 [item, count] 列表（按频次降序）.

    Args:
        counter: Counter 对象.
        limit: 返回条目上限.

    Returns:
        ``[[item, count], ...]`` 列表.
    """
    return [[item, count] for item, count in counter.most_common(limit)]


def _counter_to_str(
    counter: Counter[str],
    limit: int,
) -> str:
    """将 Counter 格式化为可读字符串.

    格式: ``item1(n1)、item2(n2)、item3(n3)``
    """
    items = counter.most_common(limit)
    if not items:
        return "暂无数据"
    return "、".join(f"{item}({count})" for item, count in items)


# ======================================================================
# 知识库类
# ======================================================================


class KnowledgeBase:
    """知识库构建器 - 聚合论文分析结果，生成质量基准.

    接收 ``PaperAnalysis`` 对象列表，聚合结构、引用、语言、实证四维度
    统计数据，生成可直接注入 LLM Prompt 的质量基准文本和章节范例.

    Attributes:
        DEFAULT_STORAGE_DIR: 默认存储目录 (~/.scholarpilot/benchmark).
        STORAGE_FILENAME: 存储文件名 (knowledge_base.json).
        SECTION_TYPES: 支持的章节类型列表.
    """

    DEFAULT_STORAGE_DIR: Path = DEFAULT_STORAGE_DIR
    STORAGE_FILENAME: str = STORAGE_FILENAME
    SECTION_TYPES: list[str] = SECTION_TYPES

    def __init__(self, storage_dir: Path | None = None) -> None:
        """初始化知识库构建器.

        Args:
            storage_dir: 存储目录路径. 默认为 ~/.scholarpilot/benchmark.
                         如果目录不存在会在保存时自动创建.
        """
        self._storage_dir: Path = storage_dir or self.DEFAULT_STORAGE_DIR
        self._storage_path: Path = self._storage_dir / self.STORAGE_FILENAME

        # 知识库数据（所有聚合统计和章节模板）
        self._kb: dict[str, Any] = self._empty_kb()

        # 尝试加载已有数据
        self.load()

        logger.info(
            "KnowledgeBase initialized: storage=%s, papers=%d",
            self._storage_path,
            self._kb.get("paper_count", 0),
        )

    # ==================================================================
    # 空知识库模板
    # ==================================================================

    @staticmethod
    def _empty_kb() -> dict[str, Any]:
        """创建空的知识库数据结构.

        Returns:
            包含所有字段初始值的字典.
        """
        return {
            "paper_count": 0,
            "updated_at": "",
            "structure": {},
            "citations": {},
            "language": {},
            "empirical": {},
            "section_templates": {},
        }

    @staticmethod
    def _empty_structure_entry() -> dict[str, Any]:
        """创建空的结构基准条目."""
        return {
            "proportion_mean": 0.0,
            "proportion_median": 0.0,
            "proportion_stdev": 0.0,
            "char_count_mean": 0.0,
            "char_count_median": 0.0,
            "char_count_stdev": 0.0,
            "subsection_count_mean": 0.0,
            "subsection_count_median": 0.0,
            "sample_count": 0,
        }

    @staticmethod
    def _empty_citation_entry() -> dict[str, Any]:
        """创建空的引用基准条目."""
        return {
            "total_mean": 0.0,
            "total_median": 0.0,
            "total_stdev": 0.0,
            "density_mean": 0.0,
            "density_median": 0.0,
            "density_stdev": 0.0,
            "max_papers_per_author_mean": 0.0,
            "max_papers_per_author_median": 0.0,
            "recent_3yr_ratio_mean": 0.0,
            "recent_3yr_ratio_median": 0.0,
            "recent_5yr_ratio_mean": 0.0,
            "recent_5yr_ratio_median": 0.0,
            "classic_ratio_mean": 0.0,
            "classic_ratio_median": 0.0,
            "chinese_ratio_mean": 0.0,
            "chinese_ratio_median": 0.0,
            "english_ratio_mean": 0.0,
            "english_ratio_median": 0.0,
        }

    @staticmethod
    def _empty_language_entry() -> dict[str, Any]:
        """创建空的语言基准条目."""
        return {
            "top_templates": [],
            "top_transitions": [],
            "sentence_length_mean": 0.0,
            "sentence_length_median": 0.0,
            "sentence_length_stdev": 0.0,
        }

    @staticmethod
    def _empty_empirical_entry() -> dict[str, Any]:
        """创建空的实证基准条目."""
        return {
            "table_count_mean": 0.0,
            "table_count_median": 0.0,
            "table_count_stdev": 0.0,
            "model_types": [],
            "robustness_methods": [],
        }

    @staticmethod
    def _empty_section_template() -> dict[str, Any]:
        """创建空的章节模板条目."""
        return {
            "opening_sentences": [],
            "closing_sentences": [],
            "paragraph_structures": [],
            "typical_char_count": 0.0,
            "typical_proportion": 0.0,
            "typical_subsection_count": 0.0,
            "sample_count": 0,
        }

    # ==================================================================
    # 核心构建方法
    # ==================================================================

    def build_from_analyses(self, analyses: list[PaperAnalysis]) -> None:
        """从论文分析结果列表构建知识库.

        聚合所有 ``PaperAnalysis`` 对象的结构、引用、语言、实证数据，
        计算统计基准（均值/中位数/标准差），提取章节范例模板.

        单篇论文的分析失败不会中断整体构建过程，仅记录警告日志.

        Args:
            analyses: ``PaperAnalysis`` 对象列表，通常来自 ``PaperAnalyzer``.
        """
        if not analyses:
            logger.warning("build_from_analyses: 分析结果列表为空，知识库未更新")
            return

        paper_count = len(analyses)
        logger.info("开始构建知识库: %d 篇论文", paper_count)

        # ---- 初始化累加容器 ----

        # 结构数据: {section_type: {proportions, char_counts, subsection_counts}}
        structure_acc: dict[str, dict[str, list[float]]] = {
            st: {"proportions": [], "char_counts": [], "subsection_counts": []}
            for st in self.SECTION_TYPES
        }

        # 引用数据
        citation_acc: dict[str, list[float]] = {
            "totals": [],
            "densities": [],
            "max_per_author": [],
            "recent_3yr": [],
            "recent_5yr": [],
            "classic": [],
            "chinese": [],
            "english": [],
        }

        # 语言数据
        language_acc: dict[str, Any] = {
            "templates": Counter[str](),
            "transitions": Counter[str](),
            "sentence_lengths": [],
        }

        # 实证数据
        empirical_acc: dict[str, Any] = {
            "table_counts": [],
            "model_types": Counter[str](),
            "robustness_methods": Counter[str](),
        }

        # 章节模板数据: {section_type: {opening, closing, paragraphs, char_counts, proportions, subsection_counts}}
        template_acc: dict[str, dict[str, Any]] = {
            st: {
                "opening": [],
                "closing": [],
                "paragraphs": [],
                "char_counts": [],
                "proportions": [],
                "subsection_counts": [],
            }
            for st in self.SECTION_TYPES
        }

        # ---- 逐篇聚合 ----
        success_count = 0
        for idx, analysis in enumerate(analyses):
            try:
                self._collect_structure(analysis, structure_acc, template_acc)
                self._collect_citations(analysis, citation_acc)
                self._collect_language(analysis, language_acc)
                self._collect_empirical(analysis, empirical_acc)
                success_count += 1
            except Exception as e:
                title = getattr(analysis, "title", f"#{idx}")
                logger.warning(
                    "聚合论文分析结果失败 [%s]: %s", title[:50], e,
                )

        logger.info(
            "聚合完成: %d/%d 篇成功", success_count, paper_count,
        )

        # ---- 计算统计量 ----
        self._kb["paper_count"] = paper_count
        self._kb["updated_at"] = datetime.now().isoformat()
        self._kb["structure"] = self._compute_structure_stats(structure_acc)
        self._kb["citations"] = self._compute_citation_stats(citation_acc)
        self._kb["language"] = self._compute_language_stats(language_acc)
        self._kb["empirical"] = self._compute_empirical_stats(empirical_acc)
        self._kb["section_templates"] = self._compute_section_templates(
            template_acc,
        )

        logger.info(
            "知识库构建完成: %d 篇论文, %d 个章节类型有结构数据, "
            "Top句式 %d 个, Top过渡词 %d 个",
            paper_count,
            len(self._kb["structure"]),
            len(self._kb["language"].get("top_templates", [])),
            len(self._kb["language"].get("top_transitions", [])),
        )

    # ==================================================================
    # 数据收集: 结构
    # ==================================================================

    def _collect_structure(
        self,
        analysis: PaperAnalysis,
        structure_acc: dict[str, dict[str, list[float]]],
        template_acc: dict[str, dict[str, Any]],
    ) -> None:
        """从单篇论文分析结果中收集结构数据.

        Args:
            analysis: 论文分析结果.
            structure_acc: 结构数据累加器.
            template_acc: 章节模板数据累加器.
        """
        # PaperAnalysis.structure 是 StructureAnalysis 对象
        structure_obj = getattr(analysis, "structure", None)
        if structure_obj is None:
            return

        # StructureAnalysis.sections 是 list[dict]
        sections: list[dict] = getattr(structure_obj, "sections", []) or []

        for section in sections:
            # sections 是字典列表，使用 dict.get() 访问
            if isinstance(section, dict):
                raw_type = section.get("section_type", "") or section.get("title", "")
                proportion = float(section.get("proportion", 0.0) or 0.0)
                char_count = int(section.get("char_count", 0) or 0)
                subsection_count = int(section.get("subsection_count", 0) or 0)
                opening = section.get("opening_sentences", []) or []
                closing = section.get("closing_sentences", []) or []
                paragraphs = section.get("paragraphs", []) or []
            else:
                # 兼容 SectionAnalysis 对象
                raw_type = getattr(section, "section_type", "") or getattr(section, "title", "")
                proportion = float(getattr(section, "proportion", 0.0) or 0.0)
                char_count = int(getattr(section, "char_count", 0) or 0)
                subsection_count = int(getattr(section, "subsection_count", 0) or 0)
                opening = getattr(section, "opening_sentences", []) or []
                closing = getattr(section, "closing_sentences", []) or []
                paragraphs = getattr(section, "paragraphs", []) or []

            section_type = raw_type.strip() if isinstance(raw_type, str) else str(raw_type).strip()
            if not section_type or section_type not in self.SECTION_TYPES:
                section_type = self._match_section_type(section_type)
                if not section_type:
                    continue

            # 结构统计
            structure_acc[section_type]["proportions"].append(
                _normalize_proportion(proportion),
            )
            structure_acc[section_type]["char_counts"].append(float(char_count))
            structure_acc[section_type]["subsection_counts"].append(
                float(subsection_count),
            )

            # 章节模板
            for sent in opening:
                sent = sent.strip() if isinstance(sent, str) else str(sent).strip()
                if sent and len(sent) > 5:
                    template_acc[section_type]["opening"].append(sent)

            for sent in closing:
                sent = sent.strip() if isinstance(sent, str) else str(sent).strip()
                if sent and len(sent) > 5:
                    template_acc[section_type]["closing"].append(sent)

            for para in paragraphs:
                para = para.strip() if isinstance(para, str) else str(para).strip()
                if para and len(para) > 10:
                    template_acc[section_type]["paragraphs"].append(para)

            template_acc[section_type]["char_counts"].append(float(char_count))
            template_acc[section_type]["proportions"].append(
                _normalize_proportion(proportion),
            )
            template_acc[section_type]["subsection_counts"].append(
                float(subsection_count),
            )

    def _match_section_type(self, raw_type: str) -> str:
        """模糊匹配章节类型.

        将 "一、引言" "introduction" "1.文献综述" 等变体匹配到标准章节类型.

        Args:
            raw_type: 原始章节类型字符串.

        Returns:
            匹配到的标准章节类型，未匹配返回空字符串.
        """
        if not raw_type:
            return ""
        cleaned = raw_type.strip()

        # 1. 先检查精确映射（英文类型名 → 中文）
        if cleaned in SECTION_TYPE_MAP:
            return SECTION_TYPE_MAP[cleaned]

        # 2. 检查标准类型是否已在字符串中
        for st in self.SECTION_TYPES:
            if st in cleaned:
                return st

        # 3. 检查映射表的键是否在字符串中
        for key, value in SECTION_TYPE_MAP.items():
            if key in cleaned:
                return value

        return ""

    # ==================================================================
    # 数据收集: 引用
    # ==================================================================

    def _collect_citations(
        self,
        analysis: PaperAnalysis,
        citation_acc: dict[str, list[float]],
    ) -> None:
        """从单篇论文分析结果中收集引用数据.

        Args:
            analysis: 论文分析结果.
            citation_acc: 引用数据累加器.
        """
        citations: CitationAnalysis | None = getattr(analysis, "citations", None)
        if citations is None:
            return

        total = int(getattr(citations, "total_citations", 0) or 0)
        density = float(getattr(citations, "citation_density", 0.0) or 0.0)
        max_per_author = int(
            getattr(citations, "max_papers_per_author", 0) or 0,
        )
        recent_3yr = float(getattr(citations, "recent_3yr_ratio", 0.0) or 0.0)
        recent_5yr = float(getattr(citations, "recent_5yr_ratio", 0.0) or 0.0)
        classic = float(getattr(citations, "classic_ratio", 0.0) or 0.0)
        chinese = float(getattr(citations, "chinese_ratio", 0.0) or 0.0)
        english = float(getattr(citations, "english_ratio", 0.0) or 0.0)

        citation_acc["totals"].append(float(total))
        citation_acc["densities"].append(density)
        citation_acc["max_per_author"].append(float(max_per_author))
        citation_acc["recent_3yr"].append(_normalize_proportion(recent_3yr))
        citation_acc["recent_5yr"].append(_normalize_proportion(recent_5yr))
        citation_acc["classic"].append(_normalize_proportion(classic))
        citation_acc["chinese"].append(_normalize_proportion(chinese))
        citation_acc["english"].append(_normalize_proportion(english))

    # ==================================================================
    # 数据收集: 语言
    # ==================================================================

    def _collect_language(
        self,
        analysis: PaperAnalysis,
        language_acc: dict[str, Any],
    ) -> None:
        """从单篇论文分析结果中收集语言数据.

        Args:
            analysis: 论文分析结果.
            language_acc: 语言数据累加器.
        """
        language: LanguageAnalysis | None = getattr(analysis, "language", None)
        if language is None:
            return

        # 句式模板 (dict[str, int])
        templates = getattr(language, "sentence_templates", {}) or {}
        if isinstance(templates, dict):
            for tpl, count in templates.items():
                tpl = tpl.strip() if isinstance(tpl, str) else str(tpl).strip()
                if tpl:
                    language_acc["templates"][tpl] += int(count)
        elif isinstance(templates, list):
            for tpl in templates:
                tpl = tpl.strip() if isinstance(tpl, str) else str(tpl).strip()
                if tpl:
                    language_acc["templates"][tpl] += 1

        # 过渡词 (dict[str, int])
        transitions = getattr(language, "transition_words", {}) or {}
        if isinstance(transitions, dict):
            for tw, count in transitions.items():
                tw = tw.strip() if isinstance(tw, str) else str(tw).strip()
                if tw:
                    language_acc["transitions"][tw] += int(count)
        elif isinstance(transitions, list):
            for tw in transitions:
                tw = tw.strip() if isinstance(tw, str) else str(tw).strip()
                if tw:
                    language_acc["transitions"][tw] += 1

        # 句长 (LanguageAnalysis 有 avg_sentence_length: float)
        avg_len = float(getattr(language, "avg_sentence_length", 0.0) or 0.0)
        if avg_len > 0:
            language_acc["sentence_lengths"].append(avg_len)

    # ==================================================================
    # 数据收集: 实证
    # ==================================================================

    def _collect_empirical(
        self,
        analysis: PaperAnalysis,
        empirical_acc: dict[str, Any],
    ) -> None:
        """从单篇论文分析结果中收集实证数据.

        Args:
            analysis: 论文分析结果.
            empirical_acc: 实证数据累加器.
        """
        empirical: EmpiricalAnalysis | None = getattr(analysis, "empirical", None)
        if empirical is None:
            return

        table_count = int(getattr(empirical, "table_count", 0) or 0)
        empirical_acc["table_counts"].append(float(table_count))

        model_types: list[str] = getattr(empirical, "model_types", []) or []
        for model in model_types:
            model = model.strip()
            if model:
                empirical_acc["model_types"][model] += 1

        robustness: list[str] = getattr(empirical, "robustness_methods", []) or []
        for method in robustness:
            method = method.strip()
            if method:
                empirical_acc["robustness_methods"][method] += 1

    # ==================================================================
    # 统计计算: 结构
    # ==================================================================

    def _compute_structure_stats(
        self,
        structure_acc: dict[str, dict[str, list[float]]],
    ) -> dict[str, dict[str, Any]]:
        """计算结构基准统计量.

        Args:
            structure_acc: 结构数据累加器.

        Returns:
            ``{section_type: {proportion_mean, ...}}`` 字典.
        """
        result: dict[str, dict[str, Any]] = {}

        for st, data in structure_acc.items():
            props = data["proportions"]
            chars = data["char_counts"]
            subs = data["subsection_counts"]

            if not props and not chars:
                continue

            entry = self._empty_structure_entry()
            entry["proportion_mean"] = _safe_mean(props)
            entry["proportion_median"] = _safe_median(props)
            entry["proportion_stdev"] = _safe_stdev(props)
            entry["char_count_mean"] = _safe_mean(chars)
            entry["char_count_median"] = _safe_median(chars)
            entry["char_count_stdev"] = _safe_stdev(chars)
            entry["subsection_count_mean"] = _safe_mean(subs)
            entry["subsection_count_median"] = _safe_median(subs)
            entry["sample_count"] = len(props)
            result[st] = entry

        return result

    # ==================================================================
    # 统计计算: 引用
    # ==================================================================

    def _compute_citation_stats(
        self,
        citation_acc: dict[str, list[float]],
    ) -> dict[str, Any]:
        """计算引用基准统计量.

        Args:
            citation_acc: 引用数据累加器.

        Returns:
            引用基准统计字典.
        """
        entry = self._empty_citation_entry()

        entry["total_mean"] = _safe_mean(citation_acc["totals"])
        entry["total_median"] = _safe_median(citation_acc["totals"])
        entry["total_stdev"] = _safe_stdev(citation_acc["totals"])

        entry["density_mean"] = _safe_mean(citation_acc["densities"])
        entry["density_median"] = _safe_median(citation_acc["densities"])
        entry["density_stdev"] = _safe_stdev(citation_acc["densities"])

        entry["max_papers_per_author_mean"] = _safe_mean(
            citation_acc["max_per_author"],
        )
        entry["max_papers_per_author_median"] = _safe_median(
            citation_acc["max_per_author"],
        )

        entry["recent_3yr_ratio_mean"] = _safe_mean(citation_acc["recent_3yr"])
        entry["recent_3yr_ratio_median"] = _safe_median(citation_acc["recent_3yr"])

        entry["recent_5yr_ratio_mean"] = _safe_mean(citation_acc["recent_5yr"])
        entry["recent_5yr_ratio_median"] = _safe_median(citation_acc["recent_5yr"])

        entry["classic_ratio_mean"] = _safe_mean(citation_acc["classic"])
        entry["classic_ratio_median"] = _safe_median(citation_acc["classic"])

        entry["chinese_ratio_mean"] = _safe_mean(citation_acc["chinese"])
        entry["chinese_ratio_median"] = _safe_median(citation_acc["chinese"])

        entry["english_ratio_mean"] = _safe_mean(citation_acc["english"])
        entry["english_ratio_median"] = _safe_median(citation_acc["english"])

        return entry

    # ==================================================================
    # 统计计算: 语言
    # ==================================================================

    def _compute_language_stats(
        self,
        language_acc: dict[str, Any],
    ) -> dict[str, Any]:
        """计算语言基准统计量.

        Args:
            language_acc: 语言数据累加器.

        Returns:
            语言基准统计字典.
        """
        entry = self._empty_language_entry()

        templates: Counter[str] = language_acc["templates"]
        transitions: Counter[str] = language_acc["transitions"]
        sentence_lengths: list[float] = language_acc["sentence_lengths"]

        entry["top_templates"] = _counter_to_list(
            templates, TOP_TEMPLATES_LIMIT,
        )
        entry["top_transitions"] = _counter_to_list(
            transitions, TOP_TRANSITIONS_LIMIT,
        )
        entry["sentence_length_mean"] = _safe_mean(sentence_lengths)
        entry["sentence_length_median"] = _safe_median(sentence_lengths)
        entry["sentence_length_stdev"] = _safe_stdev(sentence_lengths)

        return entry

    # ==================================================================
    # 统计计算: 实证
    # ==================================================================

    def _compute_empirical_stats(
        self,
        empirical_acc: dict[str, Any],
    ) -> dict[str, Any]:
        """计算实证基准统计量.

        Args:
            empirical_acc: 实证数据累加器.

        Returns:
            实证基准统计字典.
        """
        entry = self._empty_empirical_entry()

        table_counts: list[float] = empirical_acc["table_counts"]
        model_types: Counter[str] = empirical_acc["model_types"]
        robustness: Counter[str] = empirical_acc["robustness_methods"]

        entry["table_count_mean"] = _safe_mean(table_counts)
        entry["table_count_median"] = _safe_median(table_counts)
        entry["table_count_stdev"] = _safe_stdev(table_counts)
        entry["model_types"] = _counter_to_list(
            model_types, TOP_MODELS_LIMIT,
        )
        entry["robustness_methods"] = _counter_to_list(
            robustness, TOP_ROBUSTNESS_LIMIT,
        )

        return entry

    # ==================================================================
    # 章节模板计算
    # ==================================================================

    def _compute_section_templates(
        self,
        template_acc: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """计算章节范例模板.

        对每个章节类型，从收集的开篇句、结尾句中选取代表性范例，
        并计算典型字符数、比例和子节数量.

        选取策略:
            - 开篇句/结尾句: 去重后取前 MAX_TEMPLATE_SENTENCES 个.
            - 段落结构: 去重后取前 3 个作为范例.

        Args:
            template_acc: 章节模板数据累加器.

        Returns:
            ``{section_type: {opening_sentences, ...}}`` 字典.
        """
        result: dict[str, dict[str, Any]] = {}

        for st, data in template_acc.items():
            opening = data["opening"]
            closing = data["closing"]
            paragraphs = data["paragraphs"]
            char_counts = data["char_counts"]
            proportions = data["proportions"]
            subsection_counts = data["subsection_counts"]

            if not opening and not closing and not char_counts:
                continue

            entry = self._empty_section_template()

            # 开篇句：去重后取前 N 个
            entry["opening_sentences"] = self._deduplicate_and_limit(
                opening, MAX_TEMPLATE_SENTENCES,
            )

            # 结尾句：去重后取前 N 个
            entry["closing_sentences"] = self._deduplicate_and_limit(
                closing, MAX_TEMPLATE_SENTENCES,
            )

            # 段落结构：去重后取前 3 个
            entry["paragraph_structures"] = self._deduplicate_and_limit(
                paragraphs, 3,
            )

            # 典型统计量
            entry["typical_char_count"] = _safe_median(char_counts)
            entry["typical_proportion"] = _safe_median(proportions)
            entry["typical_subsection_count"] = _safe_median(subsection_counts)
            entry["sample_count"] = len(char_counts)

            result[st] = entry

        return result

    @staticmethod
    def _deduplicate_and_limit(
        items: list[str],
        limit: int,
    ) -> list[str]:
        """去重并限制数量.

        保持原始顺序，仅保留首次出现的项.

        Args:
            items: 字符串列表.
            limit: 返回数量上限.

        Returns:
            去重后的列表（最多 limit 项）.
        """
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            key = item.strip()
            if key and key not in seen:
                seen.add(key)
                result.append(item)
                if len(result) >= limit:
                    break
        return result

    # ==================================================================
    # 持久化: 加载 / 保存
    # ==================================================================

    def load(self) -> bool:
        """从 JSON 文件加载知识库数据.

        Returns:
            True 如果加载成功, False 如果文件不存在或加载失败.
        """
        if not self._storage_path.exists():
            return False

        try:
            data = json.loads(
                self._storage_path.read_text(encoding="utf-8"),
            )
            if not isinstance(data, dict):
                logger.warning("知识库文件格式无效: %s", self._storage_path)
                return False

            self._kb = data
            logger.info(
                "知识库已加载: %d 篇论文, 来自 %s",
                self._kb.get("paper_count", 0),
                self._storage_path,
            )
            return True

        except json.JSONDecodeError as e:
            logger.error("知识库 JSON 解析失败: %s - %s", self._storage_path, e)
            return False
        except OSError as e:
            logger.error("知识库文件读取失败: %s - %s", self._storage_path, e)
            return False
        except Exception as e:
            logger.error("加载知识库时发生意外错误: %s", e)
            return False

    def save(self) -> None:
        """将知识库数据保存到 JSON 文件.

        如果存储目录不存在会自动创建. 保存失败仅记录错误日志，
        不抛出异常.
        """
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._kb["updated_at"] = datetime.now().isoformat()
            self._storage_path.write_text(
                json.dumps(self._kb, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                "知识库已保存: %d 篇论文 -> %s",
                self._kb.get("paper_count", 0),
                self._storage_path,
            )
        except OSError as e:
            logger.error("知识库保存失败 (IO错误): %s", e)
        except (TypeError, ValueError) as e:
            logger.error("知识库保存失败 (序列化错误): %s", e)
        except Exception as e:
            logger.error("知识库保存时发生意外错误: %s", e)

    # ==================================================================
    # 基准上下文生成（核心输出方法）
    # ==================================================================

    def get_benchmark_context(self, section_type: str = "") -> str:
        """生成可注入 LLM Prompt 的质量基准文本.

        输出格式包含四大基准维度（结构/引用/语言/实证），
        如果指定了 ``section_type``，还会附加该章节的范例模板
        （开篇句、结尾句、段落结构），用于 few-shot 注入.

        Args:
            section_type: 章节类型（如 "引言" "文献综述"）.
                           为空时仅输出整体基准，不附加章节模板.

        Returns:
            格式化的质量基准文本字符串.
        """
        n = self._kb.get("paper_count", 0)
        lines: list[str] = []

        lines.append(f"## 质量基准（基于{n}篇CSSCI论文统计分析）")
        lines.append("")

        # 结构基准
        lines.append("### 结构基准")
        structure = self._kb.get("structure", {})
        if structure:
            for st in self.SECTION_TYPES:
                entry = structure.get(st)
                if not entry:
                    continue
                prop_mean = entry.get("proportion_mean", 0.0)
                char_mean = entry.get("char_count_mean", 0.0)
                lines.append(
                    f"- {st}：占总篇幅{_format_pct(prop_mean)}%"
                    f"（约{_format_num(char_mean)}字）",
                )
        else:
            lines.append("- 暂无数据")
        lines.append("")

        # 引用基准
        lines.append("### 引用基准")
        citations = self._kb.get("citations", {})
        if citations:
            total_mean = citations.get("total_mean", 0.0)
            total_median = citations.get("total_median", 0.0)
            density_mean = citations.get("density_mean", 0.0)
            density_median = citations.get("density_median", 0.0)
            max_author_mean = citations.get("max_papers_per_author_mean", 0.0)
            max_author_median = citations.get("max_papers_per_author_median", 0.0)
            r3_mean = citations.get("recent_3yr_ratio_mean", 0.0)
            r3_median = citations.get("recent_3yr_ratio_median", 0.0)
            r5_mean = citations.get("recent_5yr_ratio_mean", 0.0)
            r5_median = citations.get("recent_5yr_ratio_median", 0.0)
            classic_mean = citations.get("classic_ratio_mean", 0.0)
            classic_median = citations.get("classic_ratio_median", 0.0)
            cn_mean = citations.get("chinese_ratio_mean", 0.0)
            en_mean = citations.get("english_ratio_mean", 0.0)

            lines.append(
                f"- 总引用量：均值{_format_num(total_mean)}篇"
                f"（中位数{_format_num(total_median)}篇）",
            )
            lines.append(
                f"- 引用密度：均值{_format_float(density_mean)}次/千字"
                f"（中位数{_format_float(density_median)}）",
            )
            lines.append(
                f"- 同一作者最多：均值{_format_float(max_author_mean)}篇"
                f"（中位数{_format_float(max_author_median)}篇）",
            )
            lines.append(
                f"- 近3年文献占比：均值{_format_pct(r3_mean)}%"
                f"（中位数{_format_pct(r3_median)}%）",
            )
            lines.append(
                f"- 近5年文献占比：均值{_format_pct(r5_mean)}%"
                f"（中位数{_format_pct(r5_median)}%）",
            )
            lines.append(
                f"- 经典文献占比：均值{_format_pct(classic_mean)}%"
                f"（中位数{_format_pct(classic_median)}%）",
            )
            lines.append(
                f"- 中文文献占比：{_format_pct(cn_mean)}%，"
                f"英文文献占比：{_format_pct(en_mean)}%",
            )
        else:
            lines.append("- 暂无数据")
        lines.append("")

        # 语言基准
        lines.append("### 语言基准")
        language = self._kb.get("language", {})
        if language:
            top_templates = language.get("top_templates", [])
            top_transitions = language.get("top_transitions", [])
            sl_mean = language.get("sentence_length_mean", 0.0)
            sl_median = language.get("sentence_length_median", 0.0)

            # 句式模板：取前 5 个
            if top_templates:
                tpl_str = "、".join(
                    f"{item}({count})"
                    for item, count in top_templates[:5]
                )
            else:
                tpl_str = "暂无数据"
            lines.append(f"- 常用学术句式：{tpl_str}")

            # 过渡词：取前 5 个
            if top_transitions:
                tw_str = "、".join(
                    f"{item}({count})"
                    for item, count in top_transitions[:5]
                )
            else:
                tw_str = "暂无数据"
            lines.append(f"- 常用过渡词：{tw_str}")

            lines.append(
                f"- 平均句长：均值{_format_num(sl_mean)}字"
                f"（中位数{_format_num(sl_median)}字）",
            )
        else:
            lines.append("- 暂无数据")
        lines.append("")

        # 实证基准
        lines.append("### 实证基准")
        empirical = self._kb.get("empirical", {})
        if empirical:
            tc_mean = empirical.get("table_count_mean", 0.0)
            tc_median = empirical.get("table_count_median", 0.0)
            model_types = empirical.get("model_types", [])
            robustness = empirical.get("robustness_methods", [])

            lines.append(
                f"- 表格数量：均值{_format_float(tc_mean)}个"
                f"（中位数{_format_float(tc_median)}个）",
            )

            if model_types:
                model_str = "、".join(
                    f"{item}({count})"
                    for item, count in model_types[:3]
                )
            else:
                model_str = "暂无数据"
            lines.append(f"- 常用模型：{model_str}")

            if robustness:
                rb_str = "、".join(
                    f"{item}({count})"
                    for item, count in robustness[:3]
                )
            else:
                rb_str = "暂无数据"
            lines.append(f"- 常用稳健性方法：{rb_str}")
        else:
            lines.append("- 暂无数据")
        lines.append("")

        # 章节范例模板（如果指定了 section_type）
        if section_type:
            template = self.get_section_template(section_type)
            if template:
                lines.append(f"### {section_type} 范例模板")
                lines.append("")

                opening = template.get("opening_sentences", [])
                if opening:
                    lines.append("**典型开篇句：**")
                    for i, sent in enumerate(opening, 1):
                        lines.append(f"{i}. {sent}")
                    lines.append("")

                closing = template.get("closing_sentences", [])
                if closing:
                    lines.append("**典型结尾句：**")
                    for i, sent in enumerate(closing, 1):
                        lines.append(f"{i}. {sent}")
                    lines.append("")

                paragraphs = template.get("paragraph_structures", [])
                if paragraphs:
                    lines.append("**段落结构范例：**")
                    for i, para in enumerate(paragraphs, 1):
                        # 截取前 100 字展示
                        preview = para[:100] + ("..." if len(para) > 100 else "")
                        lines.append(f"{i}. {preview}")
                    lines.append("")

                typical_chars = template.get("typical_char_count", 0.0)
                typical_prop = template.get("typical_proportion", 0.0)
                typical_subs = template.get("typical_subsection_count", 0.0)
                lines.append(
                    f"- 典型篇幅：约{_format_num(typical_chars)}字"
                    f"（占总篇幅{_format_pct(typical_prop)}%）",
                )
                lines.append(
                    f"- 典型子节数：{_format_float(typical_subs)}个",
                )

        return "\n".join(lines)

    # ==================================================================
    # 标准/基准获取方法
    # ==================================================================

    def get_section_template(self, section_type: str) -> dict | None:
        """获取指定章节类型的范例模板.

        Args:
            section_type: 章节类型（如 "引言" "文献综述"）.

        Returns:
            模板字典，包含:
                - opening_sentences: 典型开篇句列表.
                - closing_sentences: 典型结尾句列表.
                - paragraph_structures: 段落结构范例列表.
                - typical_char_count: 典型字符数（中位数）.
                - typical_proportion: 典型篇幅占比（中位数）.
                - typical_subsection_count: 典型子节数（中位数）.
                - sample_count: 样本数.

            如果章节类型不存在或无数据，返回 None.
        """
        if not section_type:
            return None

        templates = self._kb.get("section_templates", {})
        return templates.get(section_type.strip())

    def get_citation_standards(self) -> dict:
        """获取引用基准统计.

        Returns:
            引用基准字典，包含各指标的均值/中位数/标准差.
        """
        return dict(self._kb.get("citations", self._empty_citation_entry()))

    def get_structure_standards(self) -> dict:
        """获取结构基准统计.

        Returns:
            ``{section_type: {proportion_mean, ...}}`` 字典.
        """
        return dict(self._kb.get("structure", {}))

    def get_language_standards(self) -> dict:
        """获取语言基准统计.

        Returns:
            语言基准字典，包含 top_templates, top_transitions,
            sentence_length_mean/median/stdev.
        """
        return dict(self._kb.get("language", self._empty_language_entry()))

    def get_empirical_standards(self) -> dict:
        """获取实证基准统计.

        Returns:
            实证基准字典，包含 table_count_mean/median/stdev,
            model_types, robustness_methods.
        """
        return dict(self._kb.get("empirical", self._empty_empirical_entry()))

    def get_stats(self) -> dict:
        """获取知识库统计摘要.

        Returns:
            统计字典，包含:
                - paper_count: 论文总数.
                - section_types_covered: 有结构数据的章节数.
                - templates_count: 句式模板总数.
                - transitions_count: 过渡词总数.
                - section_templates_count: 有范例模板的章节数.
                - updated_at: 最后更新时间.
                - storage_path: 存储路径.
        """
        structure = self._kb.get("structure", {})
        language = self._kb.get("language", {})
        section_templates = self._kb.get("section_templates", {})

        return {
            "paper_count": self._kb.get("paper_count", 0),
            "sample_size": self._kb.get("paper_count", 0),
            "section_types_covered": len(structure),
            "templates_count": len(language.get("top_templates", [])),
            "transitions_count": len(language.get("top_transitions", [])),
            "section_templates_count": len(section_templates),
            "updated_at": self._kb.get("updated_at", ""),
            "storage_path": str(self._storage_path),
        }

    # ==================================================================
    # 便捷属性
    # ==================================================================

    @property
    def paper_count(self) -> int:
        """知识库中的论文总数."""
        return self._kb.get("paper_count", 0)

    @property
    def is_built(self) -> bool:
        """知识库是否已构建（论文数 > 0）."""
        return self._kb.get("paper_count", 0) > 0


# ======================================================================
# 独立运行入口
# ======================================================================


def _main() -> None:
    """独立运行入口: 构建或查看知识库.

    支持两种模式:
        1. 从分析结果文件构建知识库 (--build 模式).
        2. 查看已有知识库的基准上下文 (默认模式).
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="知识库构建器 - 聚合论文分析结果，生成质量基准",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="从分析结果 JSON 文件构建知识库",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="",
        help="分析结果 JSON 文件路径 (build 模式使用)",
    )
    parser.add_argument(
        "--section",
        type=str,
        default="",
        help="查看指定章节的基准上下文 (如 '引言')",
    )
    parser.add_argument(
        "--storage-dir",
        type=str,
        default="",
        help="存储目录 (默认 ~/.scholarpilot/benchmark)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="显示知识库统计摘要",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    storage_dir = Path(args.storage_dir) if args.storage_dir else None
    kb = KnowledgeBase(storage_dir=storage_dir)

    if args.build:
        if not args.input:
            print("错误: --build 模式需要 --input 参数指定分析结果文件")
            return

        input_path = Path(args.input)
        if not input_path.exists():
            print(f"错误: 文件不存在: {input_path}")
            return

        # 加载分析结果
        # 注意: 这里加载的是序列化后的 PaperAnalysis 列表
        # 实际使用时应由 PaperAnalyzer 直接传递 PaperAnalysis 对象
        try:
            data = json.loads(input_path.read_text(encoding="utf-8"))
            print(f"已加载分析结果: {input_path}")
            print(f"数据类型: {type(data)}")

            # 由于 PaperAnalysis 是 dataclass，从 JSON 重建需要 PaperAnalyzer 支持
            # 这里仅做演示，实际应使用 PaperAnalyzer.analyze() 的直接输出
            print("提示: 请通过 PaperAnalyzer 直接传递 PaperAnalysis 对象到 build_from_analyses()")

        except Exception as e:
            print(f"加载分析结果失败: {e}")
        return

    if args.stats:
        stats = kb.get_stats()
        print("\n===== 知识库统计 =====")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        return

    # 默认: 输出基准上下文
    context = kb.get_benchmark_context(section_type=args.section)
    print(context)


if __name__ == "__main__":
    _main()
