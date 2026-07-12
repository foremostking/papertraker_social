"""文献综述方法论模块.

融合5套文献综述方法论，为 ScholarPilot 提供系统化的文献综述生成能力。

5套方法论:
    1. DeepSeek五步法: 边界锚定→矩阵构建→批判推演→大纲生成→分段验证
    2. NotebookLM五步法: 关键词拆解→文献矩阵→综述撰写→风格调整→编辑审阅
    3. Gemini五步法: 角色设定→海外调研→深层对比→痛点归纳→寻找缺口
    4. 文献综述指南法: 识别类型→主题转化→两道筛选→三部分结构
    5. ChatGPT逐段模板法: 6段结构化模板

使用示例::

    from scholarpilot.tools.review_methods import (
        ReviewMethodEngine, ReviewMethod, select_method, check_review_quality,
    )
    from scholarpilot.models.spec import PaperType

    # 自动选择方法论
    method = select_method(PaperType.JOURNAL, "economics", 35)

    # 执行综述生成
    engine = ReviewMethodEngine()
    result = engine.generate(
        method=method,
        topic="地方政府债务与经济增长",
        literature=literature_items,
        research_focus="债务规模对区域经济增长的非线性影响",
    )

    # 质量检查
    quality = check_review_quality(review_text)
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from scholarpilot.models.spec import PaperType

logger = logging.getLogger(__name__)


# ===========================================================================
# 枚举定义
# ===========================================================================


class ReviewMethod(str, Enum):
    """文献综述方法论枚举.

    Attributes:
        DEEPSEEK_FIVE_STEP: DeepSeek五步法，矩阵驱动，适合大文献量.
        NOTEBOOKLM_FIVE_STEP: NotebookLM五步法，矩阵+撰写，适合中等文献量.
        GEMINI_FIVE_STEP: Gemini五步法，国际化视角，适合英文文献为主的综述.
        TEXTBOOK_GUIDE: 文献综述指南法，结构化指南，适合学位论文.
        CHATGPT_PARAGRAPH: ChatGPT逐段模板法，6段模板，适合快速生成.
        HYBRID: 混合方法，自动组合多套方法论.
    """

    DEEPSEEK_FIVE_STEP = "deepseek_five_step"
    NOTEBOOKLM_FIVE_STEP = "notebooklm_five_step"
    GEMINI_FIVE_STEP = "gemini_five_step"
    TEXTBOOK_GUIDE = "textbook_guide"
    CHATGPT_PARAGRAPH = "chatgpt_paragraph"
    HYBRID = "hybrid"


class ReviewType(str, Enum):
    """综述类型枚举.

    Attributes:
        BACKGROUND: 背景式综述，介绍研究领域的背景和现状.
        HISTORICAL: 历史性综述，按时间脉络梳理研究发展.
        THEORETICAL: 理论式综述，聚焦理论框架和概念演进.
        METHODICAL: 方法性综述，比较不同研究方法.
        INTEGRATIVE: 整合式综述，综合多种视角形成新框架.
    """

    BACKGROUND = "background"
    HISTORICAL = "historical"
    THEORETICAL = "theoretical"
    METHODICAL = "methodical"
    INTEGRATIVE = "integrative"


# ===========================================================================
# 数据模型
# ===========================================================================


class LiteratureItem(BaseModel):
    """文献条目模型.

    Attributes:
        title: 文献标题.
        authors: 作者列表.
        year: 发表年份.
        source: 来源（期刊名/会议名）.
        key_findings: 主要发现.
        methodology: 研究方法.
        limitations: 局限性.
        relevance_score: 与本研究的相关性评分（0-1）.
    """

    title: str
    authors: list[str] = Field(default_factory=list)
    year: int
    source: str = ""
    key_findings: str = ""
    methodology: str = ""
    limitations: str = ""
    relevance_score: float = 0.5

    @field_validator("relevance_score")
    @classmethod
    def validate_relevance_score(cls, v: float) -> float:
        """验证相关性评分在0-1范围内."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("relevance_score 必须在 0 到 1 之间")
        return v

    @property
    def author_year_str(self) -> str:
        """返回"作者（年份）"格式的引用字符串."""
        if not self.authors:
            return f"（{self.year}）"
        first_author = self.authors[0]
        if len(self.authors) > 3:
            return f"{first_author}等（{self.year}）"
        return f"{'、'.join(self.authors)}（{self.year}）"


class ReviewMatrix(BaseModel):
    """文献比较矩阵 - DeepSeek五步法中的7列结构.

    Attributes:
        literature: 文献列表.
        dimensions: 比较维度（列名）.
        matrix: 矩阵内容，每行对应一篇文献，每列对应一个维度.
    """

    literature: list[LiteratureItem] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    matrix: list[list[str]] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """将矩阵转为 Markdown 表格格式.

        Returns:
            Markdown 格式的表格字符串，无数据时返回空字符串.
        """
        if not self.dimensions or not self.matrix:
            return ""
        lines = ["| " + " | ".join(self.dimensions) + " |"]
        lines.append("| " + " | ".join("---" for _ in self.dimensions) + " |")
        for row in self.matrix:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)


class ReviewOutline(BaseModel):
    """综述大纲.

    Attributes:
        title: 综述标题.
        sections: 章节列表，每项为含 title/content_hint/key_refs 的字典.
        logic_thread: 逻辑主线标记，"A"为时间线，"B"为主题线.
    """

    title: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    logic_thread: str = "B"

    def to_markdown(self) -> str:
        """将大纲转为 Markdown 格式.

        Returns:
            Markdown 格式的大纲字符串.
        """
        lines = [f"# {self.title}\n"]
        for i, sec in enumerate(self.sections, 1):
            lines.append(f"## {i}. {sec.get('title', '')}")
            if sec.get("content_hint"):
                lines.append(f"  - {sec['content_hint']}")
            if sec.get("key_refs"):
                refs = sec["key_refs"]
                if isinstance(refs, list):
                    lines.append(f"  - 关键引用: {', '.join(refs)}")
                else:
                    lines.append(f"  - 关键引用: {refs}")
            lines.append("")
        return "\n".join(lines)


class ReviewStep(BaseModel):
    """综述生成的单个步骤.

    Attributes:
        step_index: 步骤序号（从1开始）.
        step_name: 步骤名称.
        description: 步骤描述.
        prompt: 可直接传给 LLM 的提示词.
        expected_output: 预期输出说明.
    """

    step_index: int
    step_name: str
    description: str
    prompt: str
    expected_output: str = ""


class ReviewResult(BaseModel):
    """综述方法论执行结果.

    Attributes:
        method: 使用的方法论.
        topic: 研究主题.
        steps: 生成步骤列表（含提示词）.
        outline: 综述大纲（如有）.
        matrix: 文献矩阵（如有）.
        review_type: 综述类型（如有）.
        metadata: 额外元数据.
    """

    method: ReviewMethod
    topic: str
    steps: list[ReviewStep] = Field(default_factory=list)
    outline: Optional[ReviewOutline] = None
    matrix: Optional[ReviewMatrix] = None
    review_type: Optional[ReviewType] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ===========================================================================
# 质量检查常量
# ===========================================================================

# 批判性表达（中文）
CRITICAL_EXPRESSIONS_ZH: list[str] = [
    "然而", "但是", "不过", "尽管如此", "与此同时", "遗憾的是",
    "不足", "局限", "缺陷", "忽视", "忽略", "缺乏",
    "争议", "分歧", "矛盾", "尚未", "尚无", "尚缺",
    "有待", "需要进一步", "仍需", "未能", "值得商榷",
    "值得注意的是", "需要指出的是", "问题在于",
]

# 批判性表达（英文）
CRITICAL_EXPRESSIONS_EN: list[str] = [
    "however", "nevertheless", "nonetheless", "despite", "although",
    "limitation", "shortcoming", "gap", "lack", "neglect",
    "controversy", "debate", "contradict", "fail to",
    "it should be noted", "worth noting", "problematic",
]

# 逻辑过渡词（中文）
TRANSITION_WORDS_ZH: list[str] = [
    "首先", "其次", "再次", "最后", "此外", "另外", "而且",
    "因此", "由此可见", "综上所述", "与此相对", "相反",
    "相比之下", "同样地", "类似地", "一方面", "另一方面",
    "换言之", "总体而言", "总的来说", "进而", "从而",
    "与此同时", "在此基础上", "进一步地",
]

# 逻辑过渡词（英文）
TRANSITION_WORDS_EN: list[str] = [
    "first", "second", "third", "finally", "furthermore", "moreover",
    "therefore", "thus", "consequently", "in contrast", "however",
    "similarly", "likewise", "on the one hand", "on the other hand",
    "in addition", "additionally", "nevertheless", "nonetheless",
    "in summary", "to conclude", "subsequently",
]

# 研究空白识别词（中文）
GAP_INDICATORS_ZH: list[str] = [
    "研究空白", "尚未涉及", "有待研究", "鲜有研究", "少有研究",
    "尚无研究", "缺乏研究", "少有人研究", "鲜有人关注",
    "未来研究", "进一步研究", "需要深入研究", "尚待探索",
    "目前尚无", "鲜有学者", "鲜有文献", "鲜见",
]

# 研究空白识别词（英文）
GAP_INDICATORS_EN: list[str] = [
    "research gap", "remains unexplored", "has not been",
    "few studies", "little research", "scarce research",
    "future research", "further research", "needs further",
    "still lacking", "underexplored", "remains unknown",
]


# ===========================================================================
# 核心引擎类
# ===========================================================================


class ReviewMethodEngine:
    """文献综述方法论引擎.

    融合5套文献综述方法论，根据输入的主题和文献，
    生成结构化的综述大纲、文献矩阵和分步提示词。

    支持的方法论:
        - DeepSeek五步法: 矩阵驱动，适合大文献量
        - NotebookLM五步法: 矩阵+撰写，适合中等文献量
        - Gemini五步法: 国际化视角，适合英文文献为主的综述
        - 文献综述指南法: 结构化指南，适合学位论文
        - ChatGPT逐段模板法: 6段模板，适合快速生成

    使用示例::

        engine = ReviewMethodEngine()
        result = engine.generate(
            method=ReviewMethod.DEEPSEEK_FIVE_STEP,
            topic="地方政府债务与经济增长",
            literature=items,
        )
        for step in result.steps:
            print(f"步骤{step.step_index}: {step.step_name}")
            print(step.prompt)
    """

    # DeepSeek五步法的7列矩阵维度
    DEEPSEEK_DIMENSIONS: list[str] = [
        "作者年份", "研究主题", "理论框架",
        "研究方法", "主要发现", "局限性", "与本研究的关联",
    ]

    # ChatGPT逐段模板法的6段结构
    CHATGPT_SECTIONS: list[str] = [
        "研究背景", "理论意义", "实践意义",
        "国外研究现状", "国内研究现状", "现有问题分析",
    ]

    # 中文字符正则（用于判断文献来源是否为中文）
    _CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")

    def generate(
        self,
        method: ReviewMethod,
        topic: str,
        literature: list[LiteratureItem] | None = None,
        research_focus: str = "",
        **kwargs: Any,
    ) -> ReviewResult:
        """执行指定的综述方法论.

        Args:
            method: 综述方法论.
            topic: 研究主题.
            literature: 文献列表.
            research_focus: 研究聚焦点（可选）.
            **kwargs: 额外参数.

        Returns:
            综述生成结果.

        Raises:
            ValueError: 不支持的方法论.
        """
        literature = literature or []
        dispatch = {
            ReviewMethod.DEEPSEEK_FIVE_STEP: self._deepseek_generate,
            ReviewMethod.NOTEBOOKLM_FIVE_STEP: self._notebooklm_generate,
            ReviewMethod.GEMINI_FIVE_STEP: self._gemini_generate,
            ReviewMethod.TEXTBOOK_GUIDE: self._textbook_generate,
            ReviewMethod.CHATGPT_PARAGRAPH: self._chatgpt_generate,
        }
        handler = dispatch.get(method)
        if handler is None:
            raise ValueError(f"不支持的方法论: {method}")
        return handler(topic, literature, research_focus, **kwargs)

    # ------------------------------------------------------------------
    # DeepSeek五步法
    # ------------------------------------------------------------------

    def _deepseek_generate(
        self,
        topic: str,
        literature: list[LiteratureItem],
        research_focus: str,
        **kwargs: Any,
    ) -> ReviewResult:
        """DeepSeek五步法生成综述.

        五步流程:
            1. 边界锚定: 提取核心关键词（4-8字），生成检索式
            2. 矩阵构建: 构建7列文献矩阵
            3. 批判推演: 寻找"悖论/断层/错配"三种模式
            4. 大纲生成: 按逻辑主线A（时间线）或B（主题线）生成
            5. 分段验证: 检查引用完整性、逻辑连贯性、批判深度

        Args:
            topic: 研究主题.
            literature: 文献列表.
            research_focus: 研究聚焦点.

        Returns:
            综述生成结果.
        """
        steps: list[ReviewStep] = []

        # Step 1: 边界锚定
        keywords = self._extract_keywords(topic)
        search_query = self._build_search_query(keywords)
        steps.append(ReviewStep(
            step_index=1,
            step_name="边界锚定",
            description="提取核心关键词（4-8字），生成检索式，确定检索边界",
            prompt=(
                f"请围绕研究主题「{topic}」进行边界锚定：\n"
                f"1. 提取4-8个字的核心关键词\n"
                f"2. 生成布尔检索式（使用 AND/OR/NOT）\n"
                f"3. 确定检索范围（时间跨度、学科领域、文献类型）\n\n"
                f"初步提取的关键词：{', '.join(keywords)}\n"
                f"建议检索式：{search_query}\n\n"
                f"请补充和优化以上内容。"
            ),
            expected_output="核心关键词列表 + 布尔检索式 + 检索范围说明",
        ))

        # Step 2: 矩阵构建
        review_matrix = ReviewMatrix(
            literature=literature,
            dimensions=list(self.DEEPSEEK_DIMENSIONS),
            matrix=self._build_matrix(literature, self.DEEPSEEK_DIMENSIONS),
        )
        matrix_md = review_matrix.to_markdown()
        steps.append(ReviewStep(
            step_index=2,
            step_name="矩阵构建",
            description="构建7列文献矩阵（作者年份/研究主题/理论框架/研究方法/主要发现/局限性/与本研究的关联）",
            prompt=(
                f"请基于以下文献矩阵，补充每篇文献的理论框架、研究方法、"
                f"主要发现、局限性和与本研究的关联：\n\n"
                f"{matrix_md}\n\n"
                f"研究聚焦点：{research_focus or topic}\n"
                f"请确保每个单元格内容精炼（不超过50字）。"
            ),
            expected_output="完整的7列文献矩阵（Markdown表格）",
        ))

        # Step 3: 批判推演
        steps.append(ReviewStep(
            step_index=3,
            step_name="批判推演",
            description='寻找"悖论/断层/错配"三种模式，形成批判性分析',
            prompt=(
                f"请基于以下文献矩阵进行批判推演，寻找三种模式：\n\n"
                f"{matrix_md}\n\n"
                f"1. 【悖论】不同研究得出矛盾结论的情况\n"
                f"2. 【断层】研究主题之间存在未衔接的空白\n"
                f"3. 【错配】理论框架与研究方法不匹配的情况\n\n"
                f"请针对每种模式给出2-3个具体发现，并标注涉及的文献。"
            ),
            expected_output="3种模式各2-3个批判性发现（含文献标注）",
        ))

        # Step 4: 大纲生成
        logic_thread = self._determine_logic_thread(literature)
        outline = self._build_outline(topic, literature, logic_thread, research_focus)
        thread_desc = "时间线（按发表年份排列）" if logic_thread == "A" else "主题线（按研究主题分组）"
        steps.append(ReviewStep(
            step_index=4,
            step_name="大纲生成",
            description=f"按逻辑主线{logic_thread}（{thread_desc}）生成综述大纲",
            prompt=(
                f"请基于以下大纲框架，细化每个章节的内容要点和引用文献：\n\n"
                f"{outline.to_markdown()}\n\n"
                f"逻辑主线：{logic_thread}（{thread_desc}）\n"
                f"请确保章节之间逻辑连贯，每个章节标注关键引用文献。"
            ),
            expected_output="细化的综述大纲（含每章内容要点和引用文献）",
        ))

        # Step 5: 分段验证
        steps.append(ReviewStep(
            step_index=5,
            step_name="分段验证",
            description="逐段检查引用完整性、逻辑连贯性、批判深度",
            prompt=(
                "请对综述初稿进行分段验证，逐段检查以下三个维度：\n\n"
                "1. 【引用完整性】每段是否有足够的文献支撑（每千字至少3个引用）\n"
                "2. 【逻辑连贯性】段落之间是否有明确的过渡和逻辑关系\n"
                "3. 【批判深度】每段是否有批判性分析（而非仅罗列文献）\n\n"
                "请给出每段的评分（1-5分）和改进建议。"
            ),
            expected_output="逐段评分表 + 改进建议",
        ))

        return ReviewResult(
            method=ReviewMethod.DEEPSEEK_FIVE_STEP,
            topic=topic,
            steps=steps,
            outline=outline,
            matrix=review_matrix,
            metadata={
                "keywords": keywords,
                "search_query": search_query,
                "logic_thread": logic_thread,
            },
        )

    # ------------------------------------------------------------------
    # NotebookLM五步法
    # ------------------------------------------------------------------

    def _notebooklm_generate(
        self,
        topic: str,
        literature: list[LiteratureItem],
        research_focus: str,
        **kwargs: Any,
    ) -> ReviewResult:
        """NotebookLM五步法生成综述.

        五步流程:
            1. 关键词拆解: 从主题提取3-5个核心概念
            2. 文献综述矩阵: 构建比较表格
            3. 综述撰写: 基于矩阵生成初稿
            4. 风格调整: 学术化表达
            5. 编辑审阅: 查漏补缺

        Args:
            topic: 研究主题.
            literature: 文献列表.
            research_focus: 研究聚焦点.

        Returns:
            综述生成结果.
        """
        steps: list[ReviewStep] = []

        # Step 1: 关键词拆解
        keywords = self._extract_keywords(topic)[:5]
        steps.append(ReviewStep(
            step_index=1,
            step_name="关键词拆解",
            description="从研究主题提取3-5个核心概念",
            prompt=(
                f"请从研究主题「{topic}」中拆解出3-5个核心概念，"
                f"并为每个概念提供简要定义：\n\n"
                f"初步提取的概念：{', '.join(keywords)}\n"
                f"请补充定义并检查概念的完整性和准确性。"
            ),
            expected_output="3-5个核心概念及其定义",
        ))

        # Step 2: 文献综述矩阵
        dimensions = ["作者年份", "核心概念", "研究方法", "主要结论", "研究不足"]
        review_matrix = ReviewMatrix(
            literature=literature,
            dimensions=dimensions,
            matrix=self._build_matrix(literature, dimensions),
        )
        steps.append(ReviewStep(
            step_index=2,
            step_name="文献综述矩阵",
            description="构建文献比较表格",
            prompt=(
                f"请基于以下文献矩阵，补充每篇文献涉及的核心概念和主要结论：\n\n"
                f"{review_matrix.to_markdown()}\n\n"
                f"请确保矩阵内容准确反映各文献的核心贡献。"
            ),
            expected_output="完整的文献比较矩阵",
        ))

        # Step 3: 综述撰写
        outline = self._build_outline(topic, literature, "B", research_focus)
        steps.append(ReviewStep(
            step_index=3,
            step_name="综述撰写",
            description="基于矩阵生成综述初稿",
            prompt=(
                f"请基于文献矩阵和以下大纲，撰写综述初稿：\n\n"
                f"{outline.to_markdown()}\n\n"
                f"要求：\n"
                f"1. 每段至少引用2篇文献\n"
                f"2. 按主题组织，非简单罗列\n"
                f"3. 每段结尾给出简要评述\n"
                f"4. 聚焦研究主题：{research_focus or topic}"
            ),
            expected_output="综述初稿（按大纲结构）",
        ))

        # Step 4: 风格调整
        steps.append(ReviewStep(
            step_index=4,
            step_name="风格调整",
            description="学术化表达，提升语言规范性",
            prompt=(
                "请对综述初稿进行学术化风格调整：\n\n"
                "1. 将口语化表达改为学术用语\n"
                "2. 统一引用格式（作者，年份）\n"
                "3. 增加过渡词，提升段落连贯性\n"
                "4. 确保客观中立的学术语气\n"
                "5. 检查专业术语使用的一致性"
            ),
            expected_output="学术化处理后的综述",
        ))

        # Step 5: 编辑审阅
        steps.append(ReviewStep(
            step_index=5,
            step_name="编辑审阅",
            description="查漏补缺，确保综述完整性",
            prompt=(
                "请对综述进行编辑审阅，检查以下方面：\n\n"
                "1. 是否遗漏重要文献\n"
                "2. 引用格式是否统一\n"
                "3. 逻辑结构是否完整\n"
                "4. 是否有事实性错误\n"
                "5. 字数是否符合要求\n\n"
                "请列出发现的问题和修改建议。"
            ),
            expected_output="审阅意见 + 修改后的综述",
        ))

        return ReviewResult(
            method=ReviewMethod.NOTEBOOKLM_FIVE_STEP,
            topic=topic,
            steps=steps,
            outline=outline,
            matrix=review_matrix,
            metadata={"keywords": keywords},
        )

    # ------------------------------------------------------------------
    # Gemini五步法
    # ------------------------------------------------------------------

    def _gemini_generate(
        self,
        topic: str,
        literature: list[LiteratureItem],
        research_focus: str,
        **kwargs: Any,
    ) -> ReviewResult:
        """Gemini五步法生成综述.

        五步流程:
            1. 角色设定: 设定学术专家角色
            2. 海外调研: 优先检索英文文献
            3. 深层对比: 方法对比+理论对比+结论对比
            4. 痛点归纳: 归纳现有研究的3-5个痛点
            5. 寻找缺口: 定位研究空白

        Args:
            topic: 研究主题.
            literature: 文献列表.
            research_focus: 研究聚焦点.

        Returns:
            综述生成结果.
        """
        steps: list[ReviewStep] = []
        focus = research_focus or topic

        # Step 1: 角色设定
        steps.append(ReviewStep(
            step_index=1,
            step_name="角色设定",
            description="设定学术专家角色，明确综述视角",
            prompt=(
                f"请你以以下角色撰写文献综述：\n\n"
                f"角色：{focus}领域的资深研究者，熟悉国际前沿研究\n"
                f"任务：围绕「{topic}」撰写系统性文献综述\n"
                f"视角：国际化视角，优先关注英文文献和顶级期刊\n"
                f"语言：中英文混合（关键术语保留英文）\n\n"
                f"请首先列出你将关注的核心议题（3-5个）。"
            ),
            expected_output="角色设定 + 3-5个核心议题",
        ))

        # Step 2: 海外调研
        en_literature = [
            item for item in literature
            if item.source and not self._CJK_PATTERN.search(item.source)
        ]
        steps.append(ReviewStep(
            step_index=2,
            step_name="海外调研",
            description="优先检索和分析英文文献",
            prompt=(
                f"请围绕「{topic}」进行海外文献调研：\n\n"
                f"1. 优先检索英文顶级期刊（如 Nature, Science, Top 5 Econ journals 等）\n"
                f"2. 关注 SSRN、NBER Working Papers 等预印本\n"
                f"3. 追踪领域内高被引文献和最新成果\n\n"
                f"已有英文文献：{len(en_literature)} 篇\n"
                f"请补充检索并整理关键英文文献的核心贡献。"
            ),
            expected_output="英文文献调研报告（含核心贡献梳理）",
        ))

        # Step 3: 深层对比
        steps.append(ReviewStep(
            step_index=3,
            step_name="深层对比",
            description="方法对比+理论对比+结论对比",
            prompt=(
                f"请围绕「{topic}」进行三维度深层对比：\n\n"
                f"1. 【方法对比】比较不同研究使用的方法（实验/准实验/观测/模拟等）\n"
                f"2. 【理论对比】比较不同研究的理论框架和假设\n"
                f"3. 【结论对比】比较不同研究的核心结论，找出一致性和分歧\n\n"
                f"请以表格形式呈现对比结果，并标注涉及的文献。"
            ),
            expected_output="三维度对比表格 + 对比分析",
        ))

        # Step 4: 痛点归纳
        steps.append(ReviewStep(
            step_index=4,
            step_name="痛点归纳",
            description="归纳现有研究的3-5个痛点",
            prompt=(
                f"请基于以上对比分析，归纳现有研究在「{topic}」领域的3-5个痛点：\n\n"
                f"1. 每个痛点需有具体文献支撑\n"
                f"2. 痛点应涵盖：方法缺陷、理论不足、数据局限、结论分歧等\n"
                f"3. 按重要性排序\n\n"
                f"请确保痛点具有学术价值，而非泛泛而谈。"
            ),
            expected_output="3-5个研究痛点（含文献支撑和重要性排序）",
        ))

        # Step 5: 寻找缺口
        steps.append(ReviewStep(
            step_index=5,
            step_name="寻找缺口",
            description="定位研究空白，为本研究提供切入点",
            prompt=(
                f"请基于以上痛点分析，定位「{topic}」领域的研究空白：\n\n"
                f"1. 明确当前研究最关键的空白点（1-2个）\n"
                f"2. 说明该空白为何重要\n"
                f"3. 提出可能的切入方向\n"
                f"4. 预估研究的可行性和预期贡献\n\n"
                f"研究聚焦点：{focus}"
            ),
            expected_output="研究空白定位 + 切入方向 + 可行性分析",
        ))

        outline = ReviewOutline(
            title=f"文献综述：{topic}",
            sections=[
                {"title": "引言", "content_hint": "研究背景与综述范围（国际化视角）", "key_refs": []},
                {"title": "海外研究现状", "content_hint": "英文文献核心贡献梳理", "key_refs": []},
                {"title": "三维度对比分析", "content_hint": "方法/理论/结论对比", "key_refs": []},
                {"title": "研究痛点归纳", "content_hint": "3-5个痛点及文献支撑", "key_refs": []},
                {"title": "研究空白与展望", "content_hint": "空白定位与切入方向", "key_refs": []},
            ],
            logic_thread="B",
        )

        return ReviewResult(
            method=ReviewMethod.GEMINI_FIVE_STEP,
            topic=topic,
            steps=steps,
            outline=outline,
            metadata={"focus": focus, "en_literature_count": len(en_literature)},
        )

    # ------------------------------------------------------------------
    # 文献综述指南法
    # ------------------------------------------------------------------

    def _textbook_generate(
        self,
        topic: str,
        literature: list[LiteratureItem],
        research_focus: str,
        **kwargs: Any,
    ) -> ReviewResult:
        """文献综述指南法生成综述.

        流程:
            1. 识别综述类型（5种：背景式/历史性/理论式/方法性/整合式）
            2. 三步主题转化：宽泛主题→聚焦问题→综述主题
            3. 两道筛选：初筛（标题+摘要）→精筛（全文阅读）
            4. 三部分结构：引言→正文→结论

        Args:
            topic: 研究主题.
            literature: 文献列表.
            research_focus: 研究聚焦点.

        Returns:
            综述生成结果.
        """
        steps: list[ReviewStep] = []
        focus = research_focus or topic

        # Step 1: 识别综述类型
        review_type = self._identify_review_type(topic, literature)
        type_desc = {
            ReviewType.BACKGROUND: "背景式综述（介绍研究领域背景和现状）",
            ReviewType.HISTORICAL: "历史性综述（按时间脉络梳理发展）",
            ReviewType.THEORETICAL: "理论式综述（聚焦理论框架演进）",
            ReviewType.METHODICAL: "方法性综述（比较不同研究方法）",
            ReviewType.INTEGRATIVE: "整合式综述（综合多视角形成新框架）",
        }
        steps.append(ReviewStep(
            step_index=1,
            step_name="识别综述类型",
            description="从5种综述类型中选择最合适的类型",
            prompt=(
                f"请判断研究主题「{topic}」适合哪种综述类型：\n\n"
                f"1. 背景式综述：介绍研究领域的背景和现状\n"
                f"2. 历史性综述：按时间脉络梳理研究发展\n"
                f"3. 理论式综述：聚焦理论框架和概念演进\n"
                f"4. 方法性综述：比较不同研究方法\n"
                f"5. 整合式综述：综合多种视角形成新框架\n\n"
                f"初步判断：{type_desc.get(review_type, '待确认')}\n"
                f"请说明判断理由。"
            ),
            expected_output="综述类型 + 判断理由",
        ))

        # Step 2: 三步主题转化
        steps.append(ReviewStep(
            step_index=2,
            step_name="三步主题转化",
            description="宽泛主题→聚焦问题→综述主题",
            prompt=(
                f"请对研究主题进行三步转化：\n\n"
                f"第1步 - 宽泛主题：{topic}\n"
                f"第2步 - 聚焦问题：{focus}\n"
                f"第3步 - 综述主题：？\n\n"
                f"请将聚焦问题转化为具体的综述主题，"
                f"确保综述主题既不过于宽泛也不过于狭窄。"
            ),
            expected_output="三步主题转化结果 + 综述主题表述",
        ))

        # Step 3: 两道筛选
        steps.append(ReviewStep(
            step_index=3,
            step_name="两道筛选",
            description="初筛（标题+摘要）→精筛（全文阅读）",
            prompt=(
                f"请对文献进行两道筛选：\n\n"
                f"【初筛】基于标题和摘要，从{len(literature)}篇文献中筛选相关文献：\n"
                f"  - 排除标准：主题不相关、重复研究、非学术文献\n"
                f"  - 保留率建议：50%-70%\n\n"
                f"【精筛】通读全文，确定核心引用文献：\n"
                f"  - 评估标准：理论贡献、方法创新、结论可靠性\n"
                f"  - 保留率建议：初筛文献的30%-50%\n\n"
                f"请给出筛选结果和理由。"
            ),
            expected_output="初筛和精筛结果 + 筛选理由",
        ))

        # Step 4: 三部分结构
        body_organization = self._determine_body_organization(review_type)
        outline = ReviewOutline(
            title=f"文献综述：{topic}",
            sections=[
                {
                    "title": "引言",
                    "content_hint": f"研究背景+综述范围+组织方式（{body_organization}）",
                    "key_refs": [item.author_year_str for item in literature[:3]] if literature else [],
                },
                {
                    "title": f"正文（{body_organization}）",
                    "content_hint": f"按{body_organization}组织文献综述",
                    "key_refs": [item.author_year_str for item in literature[3:8]] if len(literature) > 3 else [],
                },
                {
                    "title": "结论",
                    "content_hint": "总结+研究空白+未来展望",
                    "key_refs": [item.author_year_str for item in literature[-3:]] if literature else [],
                },
            ],
            logic_thread="A" if review_type == ReviewType.HISTORICAL else "B",
        )
        steps.append(ReviewStep(
            step_index=4,
            step_name="三部分结构",
            description="引言（背景+范围+组织方式）→正文→结论（总结+空白+展望）",
            prompt=(
                f"请按三部分结构撰写综述：\n\n"
                f"{outline.to_markdown()}\n\n"
                f"综述类型：{type_desc.get(review_type, '')}\n"
                f"正文组织方式：{body_organization}\n\n"
                f"要求：\n"
                f"1. 引言明确综述范围和组织方式\n"
                f"2. 正文按{body_organization}组织，每段有批判性评述\n"
                f"3. 结论总结主要发现，指出研究空白和未来方向"
            ),
            expected_output="完整的三部分结构综述",
        ))

        return ReviewResult(
            method=ReviewMethod.TEXTBOOK_GUIDE,
            topic=topic,
            steps=steps,
            outline=outline,
            review_type=review_type,
            metadata={
                "review_type": review_type.value,
                "body_organization": body_organization,
            },
        )

    # ------------------------------------------------------------------
    # ChatGPT逐段模板法
    # ------------------------------------------------------------------

    def _chatgpt_generate(
        self,
        topic: str,
        literature: list[LiteratureItem],
        research_focus: str,
        **kwargs: Any,
    ) -> ReviewResult:
        """ChatGPT逐段模板法生成综述.

        6段结构:
            1. 研究背景
            2. 理论意义
            3. 实践意义
            4. 国外研究现状
            5. 国内研究现状
            6. 现有问题分析

        Args:
            topic: 研究主题.
            literature: 文献列表.
            research_focus: 研究聚焦点.

        Returns:
            综述生成结果.
        """
        steps: list[ReviewStep] = []
        focus = research_focus or topic

        # 按国内外分类文献
        en_refs = [
            item for item in literature
            if item.source and not self._CJK_PATTERN.search(item.source)
        ]
        zh_refs = [
            item for item in literature
            if not (item.source and not self._CJK_PATTERN.search(item.source))
        ]
        en_count = len(en_refs)
        zh_count = len(zh_refs)

        section_hints = {
            "研究背景": f"介绍「{topic}」的研究背景，说明研究的必要性和紧迫性",
            "理论意义": f"阐述「{focus}」研究的理论价值和对学科发展的贡献",
            "实践意义": f"说明「{focus}」研究的现实意义和应用价值",
            "国外研究现状": f"梳理国际学术界关于「{topic}」的主要研究成果",
            "国内研究现状": f"梳理国内学术界关于「{topic}」的主要研究成果",
            "现有问题分析": f"分析现有研究的不足，指出研究空白和改进方向",
        }

        sections: list[dict[str, Any]] = []
        for i, section_name in enumerate(self.CHATGPT_SECTIONS, 1):
            if section_name == "国外研究现状":
                key_refs = [item.author_year_str for item in en_refs[:5]]
            elif section_name == "国内研究现状":
                key_refs = [item.author_year_str for item in zh_refs[:5]]
            else:
                key_refs = [item.author_year_str for item in literature[:3]] if literature else []

            sections.append({
                "title": f"{i}. {section_name}",
                "content_hint": section_hints[section_name],
                "key_refs": key_refs,
            })

            steps.append(ReviewStep(
                step_index=i,
                step_name=section_name,
                description=section_hints[section_name],
                prompt=self._build_section_prompt(
                    section_name, topic, focus, i, en_count, zh_count,
                ),
                expected_output=f"{section_name}段落（500-800字）",
            ))

        outline = ReviewOutline(
            title=f"文献综述：{topic}",
            sections=sections,
            logic_thread="B",
        )

        return ReviewResult(
            method=ReviewMethod.CHATGPT_PARAGRAPH,
            topic=topic,
            steps=steps,
            outline=outline,
            metadata={
                "section_count": len(self.CHATGPT_SECTIONS),
                "en_refs": en_count,
                "zh_refs": zh_count,
            },
        )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _extract_keywords(self, topic: str) -> list[str]:
        """从研究主题提取核心关键词.

        采用启发式规则：按常见分隔符拆分，过滤停用词，
        保留有意义的短语。

        Args:
            topic: 研究主题.

        Returns:
            核心关键词列表.
        """
        stop_words = {"研究", "分析", "影响", "关系", "基于", "关于", "的", "与", "和"}
        parts = re.split(r"[，,、；;：:（）()\s]+", topic)
        keywords = []
        for part in parts:
            part = part.strip()
            if not part or part in stop_words:
                continue
            if 2 <= len(part) <= 12:
                keywords.append(part)
        if not keywords:
            keywords = [topic.strip()]
        return keywords[:8]

    def _build_search_query(self, keywords: list[str]) -> str:
        """根据关键词构建布尔检索式.

        Args:
            keywords: 关键词列表.

        Returns:
            布尔检索式字符串.
        """
        if not keywords:
            return ""
        if len(keywords) == 1:
            return f'"{keywords[0]}"'
        return " AND ".join(f'"{kw}"' for kw in keywords[:3])

    def _build_matrix(
        self,
        literature: list[LiteratureItem],
        dimensions: list[str],
    ) -> list[list[str]]:
        """构建文献矩阵内容.

        Args:
            literature: 文献列表.
            dimensions: 比较维度.

        Returns:
            矩阵内容（二维列表，每行一篇文献）.
        """
        matrix: list[list[str]] = []
        for item in literature:
            row = [
                item.author_year_str,
                item.title[:40] + ("..." if len(item.title) > 40 else ""),
                "待补充",
                item.methodology or "待补充",
                item.key_findings[:50] + ("..." if len(item.key_findings) > 50 else ""),
                item.limitations or "待补充",
                "待补充",
            ]
            while len(row) < len(dimensions):
                row.append("待补充")
            matrix.append(row[:len(dimensions)])
        return matrix

    def _determine_logic_thread(self, literature: list[LiteratureItem]) -> str:
        """确定逻辑主线.

        根据文献的年份分布和数量，自动判断使用
        时间线（A）还是主题线（B）。

        - 文献量 >= 15 且时间跨度 > 10年：使用时间线（A）
        - 否则：使用主题线（B）

        Args:
            literature: 文献列表.

        Returns:
            "A"（时间线）或 "B"（主题线）.
        """
        if len(literature) < 15:
            return "B"
        years = [item.year for item in literature if item.year]
        if not years:
            return "B"
        span = max(years) - min(years)
        return "A" if span > 10 else "B"

    def _build_outline(
        self,
        topic: str,
        literature: list[LiteratureItem],
        logic_thread: str,
        research_focus: str,
    ) -> ReviewOutline:
        """构建综述大纲.

        Args:
            topic: 研究主题.
            literature: 文献列表.
            logic_thread: 逻辑主线（A/B）.
            research_focus: 研究聚焦点.

        Returns:
            综述大纲.
        """
        focus = research_focus or topic
        if logic_thread == "A":
            sections = self._build_timeline_outline(literature, focus)
        else:
            sections = self._build_topic_outline(literature, focus)
        return ReviewOutline(
            title=f"文献综述：{topic}",
            sections=sections,
            logic_thread=logic_thread,
        )

    def _build_timeline_outline(
        self,
        literature: list[LiteratureItem],
        focus: str,
    ) -> list[dict[str, Any]]:
        """构建时间线大纲.

        Args:
            literature: 文献列表.
            focus: 研究聚焦点.

        Returns:
            章节列表.
        """
        if not literature:
            return [
                {"title": "引言", "content_hint": "研究背景与综述范围", "key_refs": []},
                {"title": "早期研究", "content_hint": "领域奠基性工作", "key_refs": []},
                {"title": "发展阶段", "content_hint": "理论和方法演进", "key_refs": []},
                {"title": "近期进展", "content_hint": "最新研究成果", "key_refs": []},
                {"title": "总结与展望", "content_hint": "研究空白与未来方向", "key_refs": []},
            ]
        years = sorted(item.year for item in literature if item.year)
        if not years:
            return self._build_topic_outline(literature, focus)
        min_year, max_year = years[0], years[-1]
        mid_year = (min_year + max_year) // 2
        early = [item for item in literature if item.year <= mid_year]
        late = [item for item in literature if item.year > mid_year]

        def _refs(items: list[LiteratureItem]) -> list[str]:
            return [item.author_year_str for item in items[:5]]

        return [
            {
                "title": "引言",
                "content_hint": f"研究背景、综述范围与组织方式（时间脉络，{min_year}-{max_year}）",
                "key_refs": _refs(literature[:5]),
            },
            {
                "title": f"早期研究（{min_year}-{mid_year}）",
                "content_hint": "领域奠基性工作与核心概念确立",
                "key_refs": _refs(early),
            },
            {
                "title": f"近期进展（{mid_year + 1}-{max_year}）",
                "content_hint": f"理论深化与方法创新，聚焦{focus}",
                "key_refs": _refs(late),
            },
            {
                "title": "研究评述与展望",
                "content_hint": "总结研究脉络，指出研究空白与未来方向",
                "key_refs": _refs(literature[-5:]),
            },
        ]

    def _build_topic_outline(
        self,
        literature: list[LiteratureItem],
        focus: str,
    ) -> list[dict[str, Any]]:
        """构建主题线大纲.

        Args:
            literature: 文献列表.
            focus: 研究聚焦点.

        Returns:
            章节列表.
        """
        def _refs(items: list[LiteratureItem]) -> list[str]:
            return [item.author_year_str for item in items[:5]]

        return [
            {
                "title": "引言",
                "content_hint": "研究背景、综述范围与组织方式（按主题分组）",
                "key_refs": _refs(literature[:5]) if literature else [],
            },
            {
                "title": "概念界定与理论基础",
                "content_hint": "核心概念界定、理论框架梳理",
                "key_refs": _refs(literature[:5]) if literature else [],
            },
            {
                "title": "研究方法综述",
                "content_hint": "主要研究方法及其演进",
                "key_refs": _refs(literature[5:10]) if len(literature) > 5 else [],
            },
            {
                "title": f"主要研究议题（聚焦{focus}）" if focus else "主要研究发现",
                "content_hint": "按研究主题分组综述主要发现",
                "key_refs": _refs(literature[10:20]) if len(literature) > 10 else (
                    _refs(literature[:5]) if literature else []
                ),
            },
            {
                "title": "研究评述与展望",
                "content_hint": "批判性评述、研究空白与未来方向",
                "key_refs": _refs(literature[-5:]) if literature else [],
            },
        ]

    def _identify_review_type(
        self,
        topic: str,
        literature: list[LiteratureItem],
    ) -> ReviewType:
        """识别综述类型.

        根据主题特征和文献特征，自动判断综述类型。

        判断规则:
            - 主题含"历史"/"演进"/"发展"→历史性
            - 主题含"理论"/"框架"/"模型"→理论式
            - 主题含"方法"/"实证"/"测量"→方法性
            - 文献量 > 30 且主题较宽泛→整合式
            - 默认→背景式

        Args:
            topic: 研究主题.
            literature: 文献列表.

        Returns:
            综述类型.
        """
        if any(kw in topic for kw in ["历史", "演进", "发展史", "演变"]):
            return ReviewType.HISTORICAL
        if any(kw in topic for kw in ["理论", "框架", "模型", "范式"]):
            return ReviewType.THEORETICAL
        if any(kw in topic for kw in ["方法", "实证", "测量", "估计", "检验"]):
            return ReviewType.METHODICAL
        if len(literature) > 30:
            return ReviewType.INTEGRATIVE
        return ReviewType.BACKGROUND

    def _determine_body_organization(self, review_type: ReviewType) -> str:
        """根据综述类型确定正文组织方式.

        Args:
            review_type: 综述类型.

        Returns:
            正文组织方式描述.
        """
        mapping = {
            ReviewType.BACKGROUND: "主题分组",
            ReviewType.HISTORICAL: "时间顺序",
            ReviewType.THEORETICAL: "理论流派分组",
            ReviewType.METHODICAL: "方法论分组",
            ReviewType.INTEGRATIVE: "主题分组+交叉分析",
        }
        return mapping.get(review_type, "主题分组")

    def _build_section_prompt(
        self,
        section_name: str,
        topic: str,
        focus: str,
        index: int,
        en_count: int,
        zh_count: int,
    ) -> str:
        """构建单个段落的提示词.

        Args:
            section_name: 段落名称.
            topic: 研究主题.
            focus: 研究聚焦点.
            index: 段落序号.
            en_count: 英文文献数量.
            zh_count: 中文文献数量.

        Returns:
            段落提示词.
        """
        templates = {
            "研究背景": (
                f"请撰写「{section_name}」段落（第{index}段，500-800字）：\n\n"
                f"内容要求：\n"
                f"1. 从宏观背景切入，逐步聚焦到「{topic}」\n"
                f"2. 说明该研究领域的现实需求和学术需求\n"
                f"3. 引出后续综述的必要性\n\n"
                f"写作要点：由大到小、由远及近、逻辑递进。"
            ),
            "理论意义": (
                f"请撰写「{section_name}」段落（第{index}段，500-800字）：\n\n"
                f"内容要求：\n"
                f"1. 阐述「{focus}」研究的理论价值\n"
                f"2. 说明对现有理论的补充或拓展\n"
                f"3. 指出可能的理论创新点\n\n"
                f"写作要点：理论深度、学术规范、创新指向。"
            ),
            "实践意义": (
                f"请撰写「{section_name}」段落（第{index}段，500-800字）：\n\n"
                f"内容要求：\n"
                f"1. 说明「{focus}」研究的现实应用价值\n"
                f"2. 对政策制定或行业实践的指导意义\n"
                f"3. 预期的社会效益或经济效益\n\n"
                f"写作要点：联系实际、具体可行、避免空泛。"
            ),
            "国外研究现状": (
                f"请撰写「{section_name}」段落（第{index}段，800-1200字）：\n\n"
                f"内容要求：\n"
                f"1. 按主题或时间梳理国际研究进展\n"
                f"2. 重点介绍代表性学者的核心贡献\n"
                f"3. 指出国际研究的主要趋势和方向\n\n"
                f"已有英文文献：{en_count}篇\n"
                f"写作要点：引用准确、评价客观、主线清晰。"
            ),
            "国内研究现状": (
                f"请撰写「{section_name}」段落（第{index}段，800-1200字）：\n\n"
                f"内容要求：\n"
                f"1. 梳理国内学者的主要研究成果\n"
                f"2. 对比国内外研究的异同\n"
                f"3. 指出国内研究的特色和不足\n\n"
                f"已有中文文献：{zh_count}篇\n"
                f"写作要点：本土视角、中外对比、客观评价。"
            ),
            "现有问题分析": (
                f"请撰写「{section_name}」段落（第{index}段，500-800字）：\n\n"
                f"内容要求：\n"
                f"1. 总结现有研究的主要不足\n"
                f"2. 指出尚未解决的关键问题\n"
                f"3. 引出本研究的切入点和创新方向\n\n"
                f"写作要点：问题明确、分析深入、承上启下。"
            ),
        }
        return templates.get(section_name, f"请撰写「{section_name}」段落。")


# ===========================================================================
# 方法选择器
# ===========================================================================


def select_method(
    paper_type: PaperType,
    discipline: str,
    literature_count: int,
) -> ReviewMethod:
    """根据论文类型和学科自动推荐方法论.

    推荐规则:
        - 综述论文 + 大文献量（>=50）→ DeepSeek五步法
        - 综述论文 + 中等文献量 → 文献综述指南法
        - 学位论文 → 文献综述指南法（结构最完整）
        - 会议论文 → Gemini五步法（国际化）
        - 期刊论文（理工科）→ Gemini五步法
        - 期刊论文（人文社科）→ 按文献量选择
        - 文献量 < 15 → ChatGPT逐段模板法

    Args:
        paper_type: 论文类型.
        discipline: 学科领域（如 "economics", "computer_science"）.
        literature_count: 文献数量.

    Returns:
        推荐的方法论.
    """
    # 综述论文
    if paper_type == PaperType.REVIEW:
        if literature_count >= 50:
            return ReviewMethod.DEEPSEEK_FIVE_STEP
        return ReviewMethod.TEXTBOOK_GUIDE

    # 学位论文：需要最完整的结构
    if paper_type == PaperType.THESIS:
        return ReviewMethod.TEXTBOOK_GUIDE

    # 会议论文：国际化视角
    if paper_type == PaperType.CONFERENCE:
        return ReviewMethod.GEMINI_FIVE_STEP

    # 期刊论文：根据学科和文献量
    if paper_type == PaperType.JOURNAL:
        stem_disciplines = {
            "computer_science", "physics", "chemistry", "biology",
            "medicine", "engineering", "mathematics", "materials",
        }
        if discipline.lower() in stem_disciplines:
            if literature_count >= 40:
                return ReviewMethod.DEEPSEEK_FIVE_STEP
            return ReviewMethod.GEMINI_FIVE_STEP

        humanities_disciplines = {
            "economics", "finance", "management", "law", "education",
            "philosophy", "literature", "history", "sociology",
            "political_science", "public_administration",
        }
        if discipline.lower() in humanities_disciplines:
            if literature_count >= 30:
                return ReviewMethod.DEEPSEEK_FIVE_STEP
            if literature_count >= 15:
                return ReviewMethod.NOTEBOOKLM_FIVE_STEP
            return ReviewMethod.CHATGPT_PARAGRAPH

        # 未知学科：默认按文献量
        if literature_count >= 40:
            return ReviewMethod.DEEPSEEK_FIVE_STEP
        if literature_count >= 20:
            return ReviewMethod.NOTEBOOKLM_FIVE_STEP
        return ReviewMethod.CHATGPT_PARAGRAPH

    # 报告/预印本：默认
    if literature_count >= 30:
        return ReviewMethod.DEEPSEEK_FIVE_STEP
    return ReviewMethod.CHATGPT_PARAGRAPH


# ===========================================================================
# 综述质量检查
# ===========================================================================


def check_review_quality(text: str) -> dict[str, Any]:
    """检查综述文本的质量.

    检查维度:
        1. 引用密度（每千字引用数）
        2. 批判性表达比例
        3. 逻辑过渡词使用
        4. 文献覆盖时间跨度
        5. 研究空白识别

    Args:
        text: 综述文本.

    Returns:
        质量检查结果字典，包含各维度的评分和详情.
    """
    if not text or not text.strip():
        return {
            "overall_score": 0.0,
            "char_count": 0,
            "citation_density": 0.0,
            "citation_count": 0,
            "critical_ratio": 0.0,
            "critical_count": 0,
            "transition_count": 0,
            "time_span": {"min_year": None, "max_year": None, "span": 0},
            "gap_indicators": [],
            "dimension_scores": {},
            "suggestions": ["综述文本为空，请先撰写综述内容。"],
        }

    char_count = len(text)

    # 1. 引用密度
    citations = _extract_citations(text)
    citation_count = len(citations)
    citation_density = round(citation_count / max(char_count / 1000, 0.1), 2)

    # 2. 批判性表达比例
    critical_count = _count_expressions(text, CRITICAL_EXPRESSIONS_ZH + CRITICAL_EXPRESSIONS_EN)
    sentences = re.split(r"[。！？.!?]+", text)
    sentence_count = max(len([s for s in sentences if s.strip()]), 1)
    critical_ratio = round(critical_count / sentence_count, 4)

    # 3. 逻辑过渡词使用
    transition_count = _count_expressions(text, TRANSITION_WORDS_ZH + TRANSITION_WORDS_EN)

    # 4. 文献覆盖时间跨度
    years = _extract_years(text, citations)
    if years:
        min_year, max_year = min(years), max(years)
        time_span: dict[str, Any] = {
            "min_year": min_year,
            "max_year": max_year,
            "span": max_year - min_year,
        }
    else:
        time_span = {"min_year": None, "max_year": None, "span": 0}

    # 5. 研究空白识别
    gap_indicators = _find_gap_indicators(text)

    # 综合评分（每维度满分20，总分100）
    dimension_scores = {
        "citation": min(citation_density / 3.0, 1.0) * 20,
        "critical": min(critical_ratio / 0.15, 1.0) * 20,
        "transition": min(transition_count / 10, 1.0) * 20,
        "coverage": min(time_span["span"] / 10, 1.0) * 20 if time_span["span"] > 0 else 0,
        "gap": 20 if gap_indicators else 0,
    }
    overall_score = round(sum(dimension_scores.values()), 1)

    # 改进建议
    suggestions = _generate_suggestions(
        citation_density, critical_ratio, transition_count, time_span, gap_indicators,
    )

    return {
        "overall_score": overall_score,
        "char_count": char_count,
        "citation_density": citation_density,
        "citation_count": citation_count,
        "critical_ratio": critical_ratio,
        "critical_count": critical_count,
        "transition_count": transition_count,
        "time_span": time_span,
        "gap_indicators": gap_indicators,
        "dimension_scores": dimension_scores,
        "suggestions": suggestions,
    }


# ===========================================================================
# 质量检查辅助函数
# ===========================================================================


def _extract_citations(text: str) -> list[str]:
    """从文本中提取引用.

    支持格式:
        - 中文：作者（年份），如 张三（2020）
        - 英文：Author (Year)，如 Smith (2020)
        - 数字引用：[1], [2] 等

    Args:
        text: 文本.

    Returns:
        引用字符串列表.
    """
    citations: list[str] = []

    # 中文引用
    zh_pattern = re.compile(
        r"[\u4e00-\u9fff]{2,6}(?:[、，,]\s*[\u4e00-\u9fff]{2,6})*"
        r"(?:\s*[和与]\s*[\u4e00-\u9fff]{2,6})*(?:等)?"
        r"\s*[（(]\s*((?:19|20)\d{2})\s*[）)]"
    )
    citations.extend(m.group(0) for m in zh_pattern.finditer(text))

    # 英文引用
    en_pattern = re.compile(
        r"[A-Z][a-z]+(?:\s+(?:and|&|,)\s+[A-Z][a-z]+)*"
        r"(?:\s+et\s+al\.?)?\s*[(（]\s*(\d{4})\s*[)）]"
    )
    citations.extend(m.group(0) for m in en_pattern.finditer(text))

    # 数字引用 [1]
    num_pattern = re.compile(r"\[\d+\]")
    citations.extend(m.group(0) for m in num_pattern.finditer(text))

    return citations


def _count_expressions(text: str, expressions: list[str]) -> int:
    """统计文本中指定表达的出现次数.

    Args:
        text: 文本.
        expressions: 表达列表.

    Returns:
        出现总次数.
    """
    text_lower = text.lower()
    count = 0
    for expr in expressions:
        if re.search(r"[\u4e00-\u9fff]", expr):
            count += text.count(expr)
        else:
            count += len(re.findall(re.escape(expr), text_lower))
    return count


def _extract_years(text: str, citations: list[str]) -> list[int]:
    """从文本和引用中提取年份.

    Args:
        text: 文本.
        citations: 引用列表.

    Returns:
        去重后的年份列表.
    """
    years: list[int] = []
    for cite in citations:
        year_matches = re.findall(r"(?:19|20)\d{2}", cite)
        years.extend(int(y) for y in year_matches)
    all_years = re.findall(r"(?:19|20)\d{2}", text)
    years.extend(int(y) for y in all_years)
    return list(set(years))


def _find_gap_indicators(text: str) -> list[str]:
    """识别文本中的研究空白指示词.

    Args:
        text: 文本.

    Returns:
        匹配到的空白指示词列表（去重）.
    """
    found: list[str] = []
    text_lower = text.lower()
    for indicator in GAP_INDICATORS_ZH + GAP_INDICATORS_EN:
        if re.search(r"[\u4e00-\u9fff]", indicator):
            if indicator in text:
                found.append(indicator)
        else:
            if indicator in text_lower:
                found.append(indicator)
    return list(set(found))


def _generate_suggestions(
    citation_density: float,
    critical_ratio: float,
    transition_count: int,
    time_span: dict[str, Any],
    gap_indicators: list[str],
) -> list[str]:
    """根据质量检查结果生成改进建议.

    Args:
        citation_density: 引用密度（每千字引用数）.
        critical_ratio: 批判性表达比例.
        transition_count: 过渡词数量.
        time_span: 时间跨度字典.
        gap_indicators: 空白指示词列表.

    Returns:
        改进建议列表.
    """
    suggestions: list[str] = []

    if citation_density < 3.0:
        suggestions.append(
            f"引用密度偏低（{citation_density}/千字），"
            f"建议每千字至少引用3篇文献，增加文献支撑。"
        )
    if critical_ratio < 0.10:
        suggestions.append(
            f"批判性表达比例偏低（{critical_ratio:.1%}），"
            f'建议增加"然而""不足""局限"等批判性分析。'
        )
    if transition_count < 5:
        suggestions.append(
            f"逻辑过渡词偏少（{transition_count}个），"
            f'建议增加"首先""此外""因此"等过渡词提升连贯性。'
        )
    if time_span.get("span", 0) < 5 and time_span.get("min_year"):
        suggestions.append(
            f"文献时间跨度较短（{time_span['span']}年），"
            f"建议补充更早期或最新的文献。"
        )
    if not gap_indicators:
        suggestions.append(
            "未识别到研究空白表述，建议在综述结尾明确指出研究空白和未来方向。"
        )
    if not suggestions:
        suggestions.append("综述质量良好，各维度均达标。")

    return suggestions


__all__ = [
    "ReviewMethod",
    "ReviewType",
    "LiteratureItem",
    "ReviewMatrix",
    "ReviewOutline",
    "ReviewStep",
    "ReviewResult",
    "ReviewMethodEngine",
    "select_method",
    "check_review_quality",
]
