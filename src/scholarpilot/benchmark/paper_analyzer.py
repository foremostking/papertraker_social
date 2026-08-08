"""论文分析器 - 从 CSSCI 论文中提取写作模式与质量基准.

本模块是基准学习系统的核心组件, 通过分析真实 CSSCI 论文提取四个维度的
写作特征:

1. **结构分析** (Structure): 章节划分、字数分布、比例、子章节结构
2. **引用模式** (Citations): 引用密度、作者多样性、年份分布、中英文比例
3. **语言模式** (Language): 学术句式模板、过渡词使用、句长分布、学术短语
4. **实证模式** (Empirical): 表格引用、统计报告模式、模型类型、稳健性检验

分析结果以 ``PaperAnalysis`` 数据类返回, 可通过 ``aggregate_stats()``
聚合多篇论文的统计基准, 用于校准 AI 论文生成的质量.

Usage:
    analyzer = PaperAnalyzer()
    analysis = analyzer.analyze(paper_text, {"title": "...", "journal": "..."})
    print(analysis.structure.section_count)
    print(analysis.citations.citation_density)

    # 批量分析 + 聚合
    analyses = analyzer.analyze_batch([(text1, meta1), (text2, meta2)])
    stats = analyzer.aggregate_stats(analyses)
    print(stats.citation_stats["mean_total_citations"])
"""

from __future__ import annotations

import logging
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ADR-007 P4: 统一统计辅助函数到 utils/text.py
from scholarpilot.utils.text import safe_mean, safe_median, safe_stdev

logger = logging.getLogger(__name__)


__all__ = [
    "SectionAnalysis",
    "StructureAnalysis",
    "CitationAnalysis",
    "LanguageAnalysis",
    "EmpiricalAnalysis",
    "PaperAnalysis",
    "AggregatedStats",
    "PaperAnalyzer",
]


# ======================================================================
# 数据类定义
# ======================================================================


@dataclass
class SectionAnalysis:
    """单章节分析结果.

    用于兼容 ``knowledge_base.py`` 的导入, 也可作为章节级别的
    结构化容器使用.
    """

    title: str = ""
    section_type: str = ""
    char_count: int = 0
    proportion: float = 0.0
    subsections: list[str] = field(default_factory=list)
    subsection_count: int = 0
    opening_sentences: list[str] = field(default_factory=list)
    closing_sentences: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class StructureAnalysis:
    """结构分析结果.

    Attributes:
        sections: 章节列表, 每个元素为包含 title / char_count /
            proportion / subsections / section_type 等键的字典.
        total_chars: 全文中文字符总数.
        section_count: 章节数量.
    """

    sections: list[dict]  # [{title, char_count, proportion, subsections, ...}]
    total_chars: int
    section_count: int


@dataclass
class CitationAnalysis:
    """引用模式分析结果.

    Attributes:
        total_citations: 引用总数.
        citation_density: 引用密度 (每 1000 中文字符的引用数).
        unique_first_authors: 唯一第一作者数量.
        max_papers_per_author: 单个第一作者的最大引用次数.
        year_distribution: 年份分布 {year_range: count}.
        recent_3yr_ratio: 近 3 年引用占比.
        recent_5yr_ratio: 近 5 年引用占比.
        classic_ratio: 经典文献 (>10 年) 占比.
        chinese_ratio: 中文引用占比.
        english_ratio: 英文引用占比.
    """

    total_citations: int
    citation_density: float  # per 1000 chars
    unique_first_authors: int
    max_papers_per_author: int
    year_distribution: dict  # {year_range: count}
    recent_3yr_ratio: float
    recent_5yr_ratio: float
    classic_ratio: float  # >10 years old
    chinese_ratio: float
    english_ratio: float


@dataclass
class LanguageAnalysis:
    """语言模式分析结果.

    Attributes:
        sentence_templates: 学术句式模板 {template: count}.
        transition_words: 过渡词使用 {word: count}.
        avg_sentence_length: 平均句长 (中文字符/句).
        total_sentences: 句子总数.
        academic_phrases: 学术短语 {phrase: count}.
    """

    sentence_templates: dict[str, int]  # {template: count}
    transition_words: dict[str, int]  # {word: count}
    avg_sentence_length: float
    total_sentences: int
    academic_phrases: dict[str, int]


@dataclass
class EmpiricalAnalysis:
    """实证分析模式结果.

    Attributes:
        table_count: 引用的表格数量 (去重).
        statistics_patterns: 统计报告模式 {pattern: count}.
        model_types: 检测到的模型类型列表.
        robustness_methods: 检测到的稳健性检验方法列表.
    """

    table_count: int
    statistics_patterns: dict[str, int]  # {pattern: count}
    model_types: list[str]
    robustness_methods: list[str]


@dataclass
class PaperAnalysis:
    """单篇论文的完整分析结果.

    Attributes:
        structure: 结构分析.
        citations: 引用模式分析.
        language: 语言模式分析.
        empirical: 实证分析模式.
        metadata: 论文元数据 (标题、期刊、年份等).
    """

    structure: StructureAnalysis
    citations: CitationAnalysis
    language: LanguageAnalysis
    empirical: EmpiricalAnalysis
    metadata: dict


@dataclass
class AggregatedStats:
    """多篇论文聚合统计结果.

    Attributes:
        structure_stats: 结构统计 {mean_total_chars, section_types: {...}}.
        citation_stats: 引用统计 {mean_total_citations, mean_density, ...}.
        language_stats: 语言统计 {common_templates, common_transitions, ...}.
        empirical_stats: 实证统计 {mean_table_count, common_models, ...}.
        sample_size: 样本量.
    """

    structure_stats: dict  # {section_type: {mean_proportion, median_proportion, std, ...}}
    citation_stats: dict  # {mean_total, median_total, mean_density, ...}
    language_stats: dict  # {common_templates, common_transitions, mean_sentence_length, ...}
    empirical_stats: dict  # {mean_tables, common_models, common_robustness, ...}
    sample_size: int


# ======================================================================
# 论文分析器
# ======================================================================


class PaperAnalyzer:
    """CSSCI 论文写作模式分析器.

    分析真实 CSSCI 论文, 提取结构、引用、语言和实证四个维度的写作
    特征, 构建质量基准用于校准 AI 论文生成.

    四大分析维度:

    1. **结构分析**: 通过检测 Markdown 标题或中文章节标题 (引言、
       文献综述、理论分析、研究设计、实证分析、稳健性检验、结论)
       划分章节, 统计各章节中文字符数和占比, 检测子章节结构.
    2. **引用模式**: 匹配中文引用 ``作者（年份）`` 和英文引用
       ``Author (Year)`` / ``Author et al. (Year)``, 计算引用密度、
       作者多样性、年份分布和中英文比例.
    3. **语言模式**: 提取学术句式模板 (如 "研究表明"、"如表X所示"),
       统计 27 个常见学术过渡词的使用频率, 计算平均句长.
    4. **实证模式**: 检测表格引用 (表1、表2)、统计报告模式
       (显著、正相关、1%水平等)、模型类型 (OLS、DID、GMM 等)
       和稳健性检验方法.

    Attributes:
        current_year: 用于计算引用时效性的基准年份.
    """

    # ------------------------------------------------------------------
    # 类常量: 章节标题模式
    # ------------------------------------------------------------------

    SECTION_PATTERNS: dict[str, list[str]] = {
        "introduction": [r"引言", r"绪论", r"导论", r"前言"],
        "literature_review": [r"文献综述", r"研究综述", r"文献回顾"],
        "theoretical_analysis": [
            r"理论分析",
            r"理论框架",
            r"理论基础",
            r"理论机制",
        ],
        "research_design": [
            r"研究设计",
            r"模型构建",
            r"模型设定",
            r"变量设定",
            r"变量定义",
            r"研究方法",
        ],
        "empirical_analysis": [
            r"实证分析",
            r"实证结果",
            r"实证检验",
            r"实证研究",
        ],
        "robustness_check": [r"稳健性检验", r"稳健性分析", r"稳健性"],
        "conclusion": [
            r"结论与建议",
            r"结论与展望",
            r"研究结论",
            r"结论",
            r"结语",
        ],
    }

    # 章节类型中文名 (用于 knowledge_base.py 兼容)
    SECTION_TYPE_CN: dict[str, str] = {
        "introduction": "引言",
        "literature_review": "文献综述",
        "theoretical_analysis": "理论分析",
        "research_design": "研究设计",
        "empirical_analysis": "实证分析",
        "robustness_check": "稳健性检验",
        "conclusion": "结论",
    }

    # ------------------------------------------------------------------
    # 类常量: 学术句式模板 (display_name, regex_pattern)
    # ------------------------------------------------------------------

    SENTENCE_TEMPLATES: list[tuple[str, str]] = [
        ("研究表明", r"研究表明"),
        ("本文发现", r"本文发现"),
        ("基于...分析", r"基于[^。]{0,30}分析"),
        ("实证结果显示", r"实证结果显示"),
        ("实证结果表明", r"实证结果表明"),
        ("如表X所示", r"如表\s*\d+所示"),
        ("与...一致", r"与[^。]{0,20}一致"),
        ("与...相符", r"与[^。]{0,20}相符"),
        ("在此基础上", r"在此基础上"),
        ("研究发现", r"研究发现"),
        ("结果表明", r"结果表明"),
        ("本文认为", r"本文认为"),
        ("本文旨在", r"本文旨在"),
        ("本文提出", r"本文提出"),
        ("本文构建", r"本文构建"),
        ("已有研究表明", r"已有研究表明"),
        ("上述分析表明", r"上述分析表明"),
        ("进一步分析表明", r"进一步分析表明"),
        ("本文以...为", r"本文以[^。]{0,30}为"),
        ("数据表明", r"数据表明"),
        ("本文基于...构建", r"本文基于[^。]{0,30}构建"),
        ("本文利用...数据", r"本文利用[^。]{0,30}数据"),
        ("本文采用...方法", r"本文采用[^。]{0,30}方法"),
    ]

    # ------------------------------------------------------------------
    # 类常量: 27 个常见学术过渡词
    # ------------------------------------------------------------------

    TRANSITION_WORDS: list[str] = [
        "因此",
        "然而",
        "此外",
        "综上所述",
        "具体而言",
        "值得注意的是",
        "进一步地",
        "基于此",
        "由此",
        "鉴于此",
        "与此同时",
        "另一方面",
        "总的来说",
        "总体而言",
        "相反",
        "尽管如此",
        "不仅如此",
        "更为重要的是",
        "由此可见",
        "事实上",
        "需要指出的是",
        "换言之",
        "也就是说",
        "例如",
        "具体来说",
        "在此基础上",
        "从而",
    ]

    # ------------------------------------------------------------------
    # 类常量: 常见学术短语
    # ------------------------------------------------------------------

    ACADEMIC_PHRASES: list[str] = [
        "本文从",
        "本文基于",
        "本文利用",
        "本文采用",
        "本文构建",
        "本文选取",
        "本文使用",
        "本文通过",
        "本文探讨",
        "本文研究",
        "研究问题",
        "研究目标",
        "研究贡献",
        "边际贡献",
        "政策建议",
        "研究局限",
        "未来研究",
        "主要贡献",
        "核心结论",
        "理论意义",
        "实践意义",
        "研究假设",
    ]

    # ------------------------------------------------------------------
    # 类常量: 统计报告模式 (name, regex)
    # ------------------------------------------------------------------

    STATISTICS_PATTERNS: dict[str, str] = {
        "显著": r"显著",
        "正相关": r"正相关",
        "负相关": r"负相关",
        "1%水平": r"1%\s*的?\s*水平",
        "5%水平": r"5%\s*的?\s*水平",
        "10%水平": r"10%\s*的?\s*水平",
        "系数": r"系数",
        "标准误": r"标准误",
        "P值": r"[Pp]\s*值",
        "t值": r"[tT]\s*值",
        "F统计量": r"[Ff]\s*统计量",
    }

    # ------------------------------------------------------------------
    # 类常量: 模型类型 (name, regex)
    # ------------------------------------------------------------------

    # 注意: Python 3 中 \b 将 CJK 字符视为 \w, 因此 \bDID\b 在
    # "DID估计" 这类中英混排文本中不会匹配 (CJK 与拉丁字母间无词边界).
    # 改用 lookbehind/lookahead 确保缩写不被嵌入更大的英文单词中,
    # 同时允许紧邻中文字符.
    MODEL_PATTERNS: dict[str, str] = {
        "固定效应": r"固定效应",
        "随机效应": r"随机效应",
        "OLS": r"(?<![a-zA-Z])OLS(?![a-zA-Z])",
        "GMM": r"(?<![a-zA-Z])GMM(?![a-zA-Z])",
        "IV": r"(?<![a-zA-Z])IV(?![a-zA-Z])",
        "2SLS": r"(?<![a-zA-Z])2SLS(?![a-zA-Z])",
        "DID": r"(?<![a-zA-Z])DID(?![a-zA-Z])",
        "PSM": r"(?<![a-zA-Z])PSM(?![a-zA-Z])",
    }

    # ------------------------------------------------------------------
    # 类常量: 稳健性检验模式 (name, regex)
    # ------------------------------------------------------------------

    ROBUSTNESS_PATTERNS: dict[str, str] = {
        "稳健性": r"稳健性",
        "替换": r"替换",
        "剔除": r"剔除",
        "滞后": r"滞后",
        "工具变量": r"工具变量",
    }

    # ------------------------------------------------------------------
    # 预编译正则表达式
    # ------------------------------------------------------------------

    CHINESE_CHAR_RE: re.Pattern[str] = re.compile(r"[\u4e00-\u9fff]")

    # 中文引用: 作者（年份） — 支持单作者、双作者 (和/与/及)、多作者 (等)
    CHINESE_CITATION_RE: re.Pattern[str] = re.compile(
        r"([\u4e00-\u9fff]{2,4}"
        r"(?:[和与及][\u4e00-\u9fff]{2,4})?"
        r"(?:等)?)"
        r"\s*[（(](\d{4})[）)]"
    )

    # 英文引用: Author (Year) / Author and Author (Year) / Author et al. (Year)
    ENGLISH_CITATION_RE: re.Pattern[str] = re.compile(
        r"([A-Z][a-zA-Z'\-]+"
        r"(?:\s+(?:and|&)\s+[A-Z][a-zA-Z'\-]+)?"
        r"(?:\s+et\s+al\.?)?)"
        r"\s*[（(](\d{4})[）)]"
    )

    # 表格引用: 表1、表 2 等
    TABLE_REF_RE: re.Pattern[str] = re.compile(r"表\s*(\d+)")

    # 中文句子结束标点
    SENTENCE_END_RE: re.Pattern[str] = re.compile(r"[。！？]")

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def __init__(self, current_year: int | None = None) -> None:
        """初始化论文分析器.

        Args:
            current_year: 用于计算引用时效性的基准年份.
                默认为当前系统年份 (datetime.now().year).
        """
        self.current_year: int = current_year or datetime.now().year

        # 预编译句式模板正则
        self._compiled_templates: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pattern)) for name, pattern in self.SENTENCE_TEMPLATES
        ]

        # 预编译过渡词正则 (使用 re.escape 防止特殊字符干扰)
        self._compiled_transitions: list[tuple[str, re.Pattern[str]]] = [
            (word, re.compile(re.escape(word))) for word in self.TRANSITION_WORDS
        ]

        # 预编译学术短语正则
        self._compiled_phrases: list[tuple[str, re.Pattern[str]]] = [
            (phrase, re.compile(re.escape(phrase))) for phrase in self.ACADEMIC_PHRASES
        ]

        # 预编译统计报告模式正则
        self._compiled_stats: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pattern))
            for name, pattern in self.STATISTICS_PATTERNS.items()
        ]

        # 预编译模型类型正则
        self._compiled_models: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pattern))
            for name, pattern in self.MODEL_PATTERNS.items()
        ]

        # 预编译稳健性检验正则
        self._compiled_robustness: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pattern))
            for name, pattern in self.ROBUSTNESS_PATTERNS.items()
        ]

        logger.debug(
            "PaperAnalyzer 初始化完成, current_year=%d, "
            "句式模板=%d, 过渡词=%d, 学术短语=%d",
            self.current_year,
            len(self._compiled_templates),
            len(self._compiled_transitions),
            len(self._compiled_phrases),
        )

    # ==================================================================
    # 公开 API
    # ==================================================================

    def analyze(
        self,
        paper_text: str,
        paper_metadata: dict | None = None,
    ) -> PaperAnalysis:
        """分析单篇论文, 返回四维度综合分析结果.

        Args:
            paper_text: 论文全文 (Markdown 或纯文本).
            paper_metadata: 可选元数据 (标题、作者、期刊、年份等).

        Returns:
            ``PaperAnalysis`` 对象, 包含结构、引用、语言、实证四个维度.

        Raises:
            本方法不会抛出异常 — 单维度分析失败时记录错误日志并
            返回该维度的空结果, 确保整体分析不被中断.
        """
        if not paper_text or not paper_text.strip():
            logger.warning("论文文本为空, 返回空分析结果")
            return self._empty_analysis(paper_metadata or {})

        metadata = paper_metadata or {}

        # --- 结构分析 ---
        try:
            structure = self._analyze_structure(paper_text)
        except Exception as exc:
            logger.error("结构分析失败: %s", exc, exc_info=True)
            structure = StructureAnalysis(sections=[], total_chars=0, section_count=0)

        # 用于引用密度计算的中文字符总数
        total_chars = structure.total_chars or len(
            self.CHINESE_CHAR_RE.findall(paper_text)
        )

        # --- 引用模式分析 ---
        try:
            citations = self._analyze_citations(paper_text, total_chars)
        except Exception as exc:
            logger.error("引用模式分析失败: %s", exc, exc_info=True)
            citations = self._empty_citation_analysis()

        # --- 语言模式分析 ---
        try:
            language = self._analyze_language(paper_text)
        except Exception as exc:
            logger.error("语言模式分析失败: %s", exc, exc_info=True)
            language = self._empty_language_analysis()

        # --- 实证模式分析 ---
        try:
            empirical = self._analyze_empirical(paper_text)
        except Exception as exc:
            logger.error("实证模式分析失败: %s", exc, exc_info=True)
            empirical = self._empty_empirical_analysis()

        logger.debug(
            "论文分析完成: %d 章节, %d 引用, %d 句, %d 表格",
            structure.section_count,
            citations.total_citations,
            language.total_sentences,
            empirical.table_count,
        )

        return PaperAnalysis(
            structure=structure,
            citations=citations,
            language=language,
            empirical=empirical,
            metadata=metadata,
        )

    def analyze_batch(
        self,
        papers: list[tuple[str, dict]],
    ) -> list[PaperAnalysis]:
        """批量分析多篇论文.

        Args:
            papers: ``(text, metadata)`` 元组列表.

        Returns:
            ``PaperAnalysis`` 对象列表, 与输入一一对应.
            单篇分析失败时返回空结果, 不影响其他论文.
        """
        results: list[PaperAnalysis] = []
        for idx, (text, metadata) in enumerate(papers):
            try:
                result = self.analyze(text, metadata)
                results.append(result)
            except Exception as exc:
                logger.error(
                    "第 %d 篇论文分析失败: %s", idx, exc, exc_info=True
                )
                results.append(self._empty_analysis(metadata))

        logger.info(
            "批量分析完成: %d/%d 篇论文成功处理", len(results), len(papers)
        )
        return results

    def aggregate_stats(
        self,
        analyses: list[PaperAnalysis],
    ) -> AggregatedStats:
        """聚合多篇论文分析结果, 生成统计基准.

        Args:
            analyses: ``PaperAnalysis`` 对象列表.

        Returns:
            ``AggregatedStats``, 包含四个维度的均值/中位数/标准差.
        """
        if not analyses:
            logger.warning("聚合统计输入为空, 返回空统计结果")
            return AggregatedStats(
                structure_stats={},
                citation_stats={},
                language_stats={},
                empirical_stats={},
                sample_size=0,
            )

        sample_size = len(analyses)
        logger.info("开始聚合 %d 篇论文的统计数据", sample_size)

        structure_stats = self._aggregate_structure(analyses)
        citation_stats = self._aggregate_citations(analyses)
        language_stats = self._aggregate_language(analyses)
        empirical_stats = self._aggregate_empirical(analyses)

        return AggregatedStats(
            structure_stats=structure_stats,
            citation_stats=citation_stats,
            language_stats=language_stats,
            empirical_stats=empirical_stats,
            sample_size=sample_size,
        )

    # ==================================================================
    # 维度一: 结构分析
    # ==================================================================

    def _analyze_structure(self, text: str) -> StructureAnalysis:
        """分析论文结构: 检测章节、统计字数、计算比例、检测子章节.

        检测策略:
            1. Markdown 标题 (``#``, ``##``, ``###``)
            2. 中文数字编号 (``一、``, ``二、``)
            3. 阿拉伯数字编号 (``1.``, ``2.``, ``3、``)
            4. 括号编号 (``(一)``, ``(1)``)
            5. 裸标题 (短行匹配已知章节标题模式)
        """
        lines = text.split("\n")
        sections: list[dict] = []
        current_title: str | None = None
        current_subsections: list[str] = []
        current_lines: list[str] = []
        preamble_lines: list[str] = []

        for line in lines:
            heading = self._detect_heading(line)
            if heading is not None:
                level, title = heading
                if level <= 1:
                    # 一级标题: 保存上一章节
                    if current_title is None:
                        # 检测前言/摘要
                        preamble_text = "\n".join(preamble_lines)
                        preamble_chars = self._count_chinese_chars(preamble_text)
                        if preamble_chars > 50:
                            sections.append(
                                self._make_section_dict(
                                    title="前言/摘要",
                                    text=preamble_text,
                                    subsections=[],
                                    section_type="preamble",
                                    proportion=0.0,
                                )
                            )
                    else:
                        section_text = "\n".join(current_lines)
                        sections.append(
                            self._make_section_dict(
                                title=current_title,
                                text=section_text,
                                subsections=current_subsections,
                                section_type=self._classify_section(current_title),
                                proportion=0.0,
                            )
                        )
                    current_title = title
                    current_subsections = []
                    current_lines = [line]
                else:
                    # 二级及以下标题: 子章节
                    current_subsections.append(title)
                    current_lines.append(line)
            else:
                if current_title is not None:
                    current_lines.append(line)
                else:
                    preamble_lines.append(line)

        # 保存最后一个章节
        if current_title is not None:
            section_text = "\n".join(current_lines)
            sections.append(
                self._make_section_dict(
                    title=current_title,
                    text=section_text,
                    subsections=current_subsections,
                    section_type=self._classify_section(current_title),
                    proportion=0.0,
                )
            )
        elif not sections:
            # 未检测到任何标题, 将全文视为一个章节
            char_count = self._count_chinese_chars(text)
            sections.append(
                self._make_section_dict(
                    title="全文",
                    text=text,
                    subsections=[],
                    section_type="full_text",
                    proportion=1.0,
                )
            )

        # 计算各章节占比
        total_chars = sum(s["char_count"] for s in sections)
        for s in sections:
            s["proportion"] = (
                s["char_count"] / total_chars if total_chars > 0 else 0.0
            )

        return StructureAnalysis(
            sections=sections,
            total_chars=total_chars,
            section_count=len(sections),
        )

    def _make_section_dict(
        self,
        title: str,
        text: str,
        subsections: list[str],
        section_type: str,
        proportion: float,
    ) -> dict:
        """构建章节字典, 包含字数统计和句子提取."""
        char_count = self._count_chinese_chars(text)

        # 提取句子用于 opening/closing 分析
        sentences_raw = self.SENTENCE_END_RE.split(text)
        sentences = [s.strip() for s in sentences_raw if s.strip()]

        # 提取段落 (双换行分隔)
        paragraphs = [
            p.strip() for p in text.split("\n\n") if p.strip() and len(p.strip()) > 10
        ]

        # opening: 前两句; closing: 后两句
        opening = sentences[:2] if len(sentences) >= 2 else sentences
        closing = sentences[-2:] if len(sentences) >= 2 else []

        return {
            "title": title,
            "char_count": char_count,
            "proportion": proportion,
            "subsections": subsections,
            "subsection_count": len(subsections),
            "section_type": section_type,
            "section_type_cn": self.SECTION_TYPE_CN.get(section_type, section_type),
            "opening_sentences": opening,
            "closing_sentences": closing,
            "paragraphs": paragraphs,
        }

    def _detect_heading(self, line: str) -> tuple[int, str] | None:
        """检测一行文本是否为章节标题.

        Returns:
            ``(level, title)`` 元组, level=1 为主章节, level>=2 为子章节.
            非标题行返回 ``None``.
        """
        stripped = line.strip()
        if not stripped:
            return None

        # Markdown 标题: # Title, ## Title 等
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip().rstrip("#").strip()
            return (level, title)

        # 中文数字编号: 一、 二、 三、 等
        m = re.match(r"^[一二三四五六七八九十]+[、.．:：]\s*(.+)$", stripped)
        if m:
            title = m.group(1).strip()
            return (1, title)

        # 括号中文数字: （一） （二） 等
        m = re.match(r"^[（(][一二三四五六七八九十]+[）)]\s*(.+)$", stripped)
        if m:
            title = m.group(1).strip()
            return (2, title)

        # 阿拉伯数字编号: 1. 2. 3. 等
        m = re.match(r"^(\d+)[.、．:：]\s*(.+)$", stripped)
        if m:
            title = m.group(2).strip()
            return (1, title)

        # 括号阿拉伯数字: (1) (2) 等
        m = re.match(r"^[（(]\d+[）)]\s*(.+)$", stripped)
        if m:
            title = m.group(1).strip()
            return (2, title)

        # 裸标题: 短行匹配已知章节标题模式
        if len(stripped) <= 25 and not stripped.endswith(("。", ".", "！", "？")):
            for patterns in self.SECTION_PATTERNS.values():
                for pattern in patterns:
                    if re.search(pattern, stripped):
                        return (1, stripped)

        return None

    def _classify_section(self, title: str) -> str:
        """将章节标题分类为标准章节类型.

        Args:
            title: 章节标题文本.

        Returns:
            章节类型字符串 (如 ``"introduction"``, ``"conclusion"``),
            未匹配返回 ``"other"``.
        """
        for section_type, patterns in self.SECTION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, title):
                    return section_type
        return "other"

    # ==================================================================
    # 维度二: 引用模式分析
    # ==================================================================

    def _analyze_citations(
        self,
        text: str,
        total_chars: int,
    ) -> CitationAnalysis:
        """分析引用模式: 密度、多样性、年份分布、语言比例.

        检测的引用格式:
            - 中文: ``张三（2020）``, ``张三和李四（2020）``, ``张三等（2020）``
            - 英文: ``Smith (2020)``, ``Smith and Jones (2020)``,
              ``Smith et al. (2020)``
        """
        chinese_citations = self.CHINESE_CITATION_RE.findall(text)
        english_citations = self.ENGLISH_CITATION_RE.findall(text)

        all_citations = chinese_citations + english_citations
        total_citations = len(all_citations)

        author_counter: Counter[str] = Counter()
        years: list[int] = []
        chinese_count = len(chinese_citations)
        english_count = len(english_citations)

        # 处理中文引用: 提取第一作者
        for author_str, year_str in chinese_citations:
            first_author = re.split(r"[和与及]", author_str)[0]
            first_author = re.sub(r"等$", "", first_author).strip()
            if first_author:
                author_counter[first_author] += 1
            try:
                years.append(int(year_str))
            except ValueError:
                logger.warning("无效引用年份: %s", year_str)

        # 处理英文引用: 提取第一作者
        for author_str, year_str in english_citations:
            first_author = re.split(r"\s+(?:and|&)\s+", author_str)[0]
            first_author = re.sub(
                r"\s+et\s+al\.?\s*$", "", first_author, flags=re.IGNORECASE
            ).strip()
            if first_author:
                author_counter[first_author] += 1
            try:
                years.append(int(year_str))
            except ValueError:
                logger.warning("无效引用年份: %s", year_str)

        unique_first_authors = len(author_counter)
        max_papers_per_author = (
            max(author_counter.values()) if author_counter else 0
        )

        # 年份分布与时效性比例
        year_distribution: dict[str, int] = {}
        recent_3yr = 0
        recent_5yr = 0
        classic = 0

        for year in years:
            age = self.current_year - year
            if age < 0:
                age = 0  # 未来年份视为当年

            if age <= 2:
                recent_3yr += 1
                bucket = "近3年"
            elif age <= 4:
                bucket = "4-5年"
            elif age <= 10:
                bucket = "6-10年"
            else:
                classic += 1
                bucket = "10年以上"

            if age <= 4:
                recent_5yr += 1

            year_distribution[bucket] = year_distribution.get(bucket, 0) + 1

        # 计算比例
        if total_citations > 0:
            citation_density = (
                total_citations / total_chars * 1000 if total_chars > 0 else 0.0
            )
            chinese_ratio = chinese_count / total_citations
            english_ratio = english_count / total_citations
            recent_3yr_ratio = recent_3yr / total_citations
            recent_5yr_ratio = recent_5yr / total_citations
            classic_ratio = classic / total_citations
        else:
            citation_density = 0.0
            chinese_ratio = 0.0
            english_ratio = 0.0
            recent_3yr_ratio = 0.0
            recent_5yr_ratio = 0.0
            classic_ratio = 0.0

        return CitationAnalysis(
            total_citations=total_citations,
            citation_density=round(citation_density, 4),
            unique_first_authors=unique_first_authors,
            max_papers_per_author=max_papers_per_author,
            year_distribution=year_distribution,
            recent_3yr_ratio=round(recent_3yr_ratio, 4),
            recent_5yr_ratio=round(recent_5yr_ratio, 4),
            classic_ratio=round(classic_ratio, 4),
            chinese_ratio=round(chinese_ratio, 4),
            english_ratio=round(english_ratio, 4),
        )

    # ==================================================================
    # 维度三: 语言模式分析
    # ==================================================================

    def _analyze_language(self, text: str) -> LanguageAnalysis:
        """分析语言模式: 句式模板、过渡词、句长、学术短语.

        检测内容:
            - 23 个学术句式模板 (如 "研究表明"、"如表X所示")
            - 27 个学术过渡词 (如 "因此"、"然而"、"综上所述")
            - 平均句长 (按中文句号 ``。`` 分句)
            - 22 个常见学术短语 (如 "本文基于"、"边际贡献")
        """
        # --- 句式模板 ---
        sentence_templates: dict[str, int] = {}
        for name, pattern in self._compiled_templates:
            matches = pattern.findall(text)
            if matches:
                sentence_templates[name] = len(matches)

        # --- 过渡词 ---
        transition_words: dict[str, int] = {}
        for word, pattern in self._compiled_transitions:
            matches = pattern.findall(text)
            if matches:
                transition_words[word] = len(matches)

        # --- 学术短语 ---
        academic_phrases: dict[str, int] = {}
        for phrase, pattern in self._compiled_phrases:
            matches = pattern.findall(text)
            if matches:
                academic_phrases[phrase] = len(matches)

        # --- 句长分析 ---
        # 按中文句末标点分句
        sentences = self.SENTENCE_END_RE.split(text)
        sentences = [s for s in sentences if s.strip()]
        total_sentences = len(sentences)
        total_chars = len(self.CHINESE_CHAR_RE.findall(text))
        avg_sentence_length = (
            total_chars / total_sentences if total_sentences > 0 else 0.0
        )

        return LanguageAnalysis(
            sentence_templates=sentence_templates,
            transition_words=transition_words,
            avg_sentence_length=round(avg_sentence_length, 2),
            total_sentences=total_sentences,
            academic_phrases=academic_phrases,
        )

    # ==================================================================
    # 维度四: 实证分析模式
    # ==================================================================

    def _analyze_empirical(self, text: str) -> EmpiricalAnalysis:
        """分析实证模式: 表格引用、统计报告、模型类型、稳健性检验.

        检测内容:
            - 表格引用 (``表1``, ``表2`` ...) — 去重计数
            - 11 个统计报告模式 (``显著``, ``正相关``, ``1%水平``, ``P值`` ...)
            - 8 种模型类型 (``OLS``, ``DID``, ``GMM``, ``固定效应`` ...)
            - 5 种稳健性检验方法 (``替换``, ``剔除``, ``滞后``, ``工具变量`` ...)
        """
        # --- 表格引用 (去重) ---
        table_matches = self.TABLE_REF_RE.findall(text)
        table_numbers = {int(n) for n in table_matches if n.isdigit()}
        table_count = len(table_numbers)

        # --- 统计报告模式 ---
        statistics_patterns: dict[str, int] = {}
        for name, pattern in self._compiled_stats:
            matches = pattern.findall(text)
            if matches:
                statistics_patterns[name] = len(matches)

        # --- 模型类型 ---
        model_types: list[str] = []
        for name, pattern in self._compiled_models:
            if pattern.search(text):
                model_types.append(name)

        # --- 稳健性检验方法 ---
        robustness_methods: list[str] = []
        for name, pattern in self._compiled_robustness:
            if pattern.search(text):
                robustness_methods.append(name)

        return EmpiricalAnalysis(
            table_count=table_count,
            statistics_patterns=statistics_patterns,
            model_types=model_types,
            robustness_methods=robustness_methods,
        )

    # ==================================================================
    # 聚合: 结构统计
    # ==================================================================

    def _aggregate_structure(
        self,
        analyses: list[PaperAnalysis],
    ) -> dict[str, Any]:
        """聚合结构统计: 各章节类型的占比/字数均值、中位数、标准差."""
        total_chars_list: list[float] = []
        section_counts: list[float] = []
        # section_type -> {"proportions": [...], "char_counts": [...]}
        section_type_data: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: {"proportions": [], "char_counts": []}
        )

        for analysis in analyses:
            total_chars_list.append(float(analysis.structure.total_chars))
            section_counts.append(float(analysis.structure.section_count))
            for section in analysis.structure.sections:
                stype = section.get("section_type", "other")
                section_type_data[stype]["proportions"].append(
                    float(section.get("proportion", 0.0))
                )
                section_type_data[stype]["char_counts"].append(
                    float(section.get("char_count", 0))
                )

        # 各章节类型统计
        section_type_stats: dict[str, dict[str, Any]] = {}
        for stype, data in section_type_data.items():
            props = data["proportions"]
            chars = data["char_counts"]
            section_type_stats[stype] = {
                "mean_proportion": round(self._safe_mean(props), 4),
                "median_proportion": round(self._safe_median(props), 4),
                "std_proportion": round(self._safe_stdev(props), 4),
                "mean_char_count": round(self._safe_mean(chars), 2),
                "median_char_count": round(self._safe_median(chars), 2),
                "count": len(props),
            }

        return {
            "mean_total_chars": round(self._safe_mean(total_chars_list), 2),
            "median_total_chars": round(self._safe_median(total_chars_list), 2),
            "std_total_chars": round(self._safe_stdev(total_chars_list), 2),
            "mean_section_count": round(self._safe_mean(section_counts), 2),
            "median_section_count": round(self._safe_median(section_counts), 2),
            "section_types": section_type_stats,
        }

    # ==================================================================
    # 聚合: 引用统计
    # ==================================================================

    def _aggregate_citations(
        self,
        analyses: list[PaperAnalysis],
    ) -> dict[str, Any]:
        """聚合引用统计: 引用数/密度/比例的均值和中位数."""
        totals: list[float] = []
        densities: list[float] = []
        unique_authors: list[float] = []
        max_per_author: list[float] = []
        recent_3yr: list[float] = []
        recent_5yr: list[float] = []
        classic: list[float] = []
        chinese: list[float] = []
        english: list[float] = []

        for analysis in analyses:
            c = analysis.citations
            totals.append(float(c.total_citations))
            densities.append(float(c.citation_density))
            unique_authors.append(float(c.unique_first_authors))
            max_per_author.append(float(c.max_papers_per_author))
            recent_3yr.append(float(c.recent_3yr_ratio))
            recent_5yr.append(float(c.recent_5yr_ratio))
            classic.append(float(c.classic_ratio))
            chinese.append(float(c.chinese_ratio))
            english.append(float(c.english_ratio))

        return {
            "mean_total_citations": round(self._safe_mean(totals), 2),
            "median_total_citations": round(self._safe_median(totals), 2),
            "std_total_citations": round(self._safe_stdev(totals), 2),
            "mean_citation_density": round(self._safe_mean(densities), 4),
            "median_citation_density": round(self._safe_median(densities), 4),
            "mean_unique_authors": round(self._safe_mean(unique_authors), 2),
            "mean_max_papers_per_author": round(
                self._safe_mean(max_per_author), 2
            ),
            "mean_recent_3yr_ratio": round(self._safe_mean(recent_3yr), 4),
            "mean_recent_5yr_ratio": round(self._safe_mean(recent_5yr), 4),
            "mean_classic_ratio": round(self._safe_mean(classic), 4),
            "mean_chinese_ratio": round(self._safe_mean(chinese), 4),
            "mean_english_ratio": round(self._safe_mean(english), 4),
        }

    # ==================================================================
    # 聚合: 语言统计
    # ==================================================================

    def _aggregate_language(
        self,
        analyses: list[PaperAnalysis],
    ) -> dict[str, Any]:
        """聚合语言统计: 句长均值、常见模板/过渡词/短语排名."""
        sentence_lengths: list[float] = []
        total_sentences: list[float] = []
        template_counts: dict[str, list[int]] = defaultdict(list)
        transition_counts: dict[str, list[int]] = defaultdict(list)
        phrase_counts: dict[str, list[int]] = defaultdict(list)

        for analysis in analyses:
            lang = analysis.language
            sentence_lengths.append(float(lang.avg_sentence_length))
            total_sentences.append(float(lang.total_sentences))
            for name, count in lang.sentence_templates.items():
                template_counts[name].append(count)
            for word, count in lang.transition_words.items():
                transition_counts[word].append(count)
            for phrase, count in lang.academic_phrases.items():
                phrase_counts[phrase].append(count)

        # 按平均出现次数降序排列
        common_templates = {
            name: round(self._safe_mean(counts), 2)
            for name, counts in sorted(
                template_counts.items(),
                key=lambda x: self._safe_mean(x[1]),
                reverse=True,
            )
        }
        common_transitions = {
            word: round(self._safe_mean(counts), 2)
            for word, counts in sorted(
                transition_counts.items(),
                key=lambda x: self._safe_mean(x[1]),
                reverse=True,
            )
        }
        common_phrases = {
            phrase: round(self._safe_mean(counts), 2)
            for phrase, counts in sorted(
                phrase_counts.items(),
                key=lambda x: self._safe_mean(x[1]),
                reverse=True,
            )
        }

        return {
            "mean_sentence_length": round(self._safe_mean(sentence_lengths), 2),
            "median_sentence_length": round(
                self._safe_median(sentence_lengths), 2
            ),
            "std_sentence_length": round(self._safe_stdev(sentence_lengths), 2),
            "mean_total_sentences": round(self._safe_mean(total_sentences), 2),
            "common_templates": common_templates,
            "common_transitions": common_transitions,
            "common_phrases": common_phrases,
        }

    # ==================================================================
    # 聚合: 实证统计
    # ==================================================================

    def _aggregate_empirical(
        self,
        analyses: list[PaperAnalysis],
    ) -> dict[str, Any]:
        """聚合实证统计: 表格数均值、常见模型/稳健性方法频次."""
        table_counts: list[float] = []
        model_counter: Counter[str] = Counter()
        robustness_counter: Counter[str] = Counter()
        stat_pattern_counts: dict[str, list[int]] = defaultdict(list)

        for analysis in analyses:
            emp = analysis.empirical
            table_counts.append(float(emp.table_count))
            for model in emp.model_types:
                model_counter[model] += 1
            for method in emp.robustness_methods:
                robustness_counter[method] += 1
            for name, count in emp.statistics_patterns.items():
                stat_pattern_counts[name].append(count)

        # 统计模式按平均出现次数降序
        common_statistics = {
            name: round(self._safe_mean(counts), 2)
            for name, counts in sorted(
                stat_pattern_counts.items(),
                key=lambda x: self._safe_mean(x[1]),
                reverse=True,
            )
        }

        return {
            "mean_table_count": round(self._safe_mean(table_counts), 2),
            "median_table_count": round(self._safe_median(table_counts), 2),
            "std_table_count": round(self._safe_stdev(table_counts), 2),
            "common_models": dict(model_counter.most_common()),
            "common_robustness": dict(robustness_counter.most_common()),
            "common_statistics": common_statistics,
        }

    # ==================================================================
    # 工具方法
    # ==================================================================

    @staticmethod
    def _count_chinese_chars(text: str) -> int:
        """统计文本中的中文字符数.

        使用 ``re.findall(r'[\\u4e00-\\u9fff]', text)`` 匹配
        CJK 统一表意文字区块.
        """
        return len(re.findall(r"[\u4e00-\u9fff]", text))

    # ADR-007 P4: _safe_mean/median/stdev 已收敛到 utils/text.py
    # 保留类级别名，避免 30+ 处 self._safe_xxx 调用逐个修改
    _safe_mean = staticmethod(safe_mean)
    _safe_median = staticmethod(safe_median)
    _safe_stdev = staticmethod(safe_stdev)

    # ==================================================================
    # 空结果工厂方法
    # ==================================================================

    def _empty_analysis(self, metadata: dict) -> PaperAnalysis:
        """返回空 PaperAnalysis (所有维度为默认值)."""
        return PaperAnalysis(
            structure=StructureAnalysis(
                sections=[], total_chars=0, section_count=0
            ),
            citations=self._empty_citation_analysis(),
            language=self._empty_language_analysis(),
            empirical=self._empty_empirical_analysis(),
            metadata=metadata,
        )

    @staticmethod
    def _empty_citation_analysis() -> CitationAnalysis:
        """返回空 CitationAnalysis."""
        return CitationAnalysis(
            total_citations=0,
            citation_density=0.0,
            unique_first_authors=0,
            max_papers_per_author=0,
            year_distribution={},
            recent_3yr_ratio=0.0,
            recent_5yr_ratio=0.0,
            classic_ratio=0.0,
            chinese_ratio=0.0,
            english_ratio=0.0,
        )

    @staticmethod
    def _empty_language_analysis() -> LanguageAnalysis:
        """返回空 LanguageAnalysis."""
        return LanguageAnalysis(
            sentence_templates={},
            transition_words={},
            avg_sentence_length=0.0,
            total_sentences=0,
            academic_phrases={},
        )

    @staticmethod
    def _empty_empirical_analysis() -> EmpiricalAnalysis:
        """返回空 EmpiricalAnalysis."""
        return EmpiricalAnalysis(
            table_count=0,
            statistics_patterns={},
            model_types=[],
            robustness_methods=[],
        )
