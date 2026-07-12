"""多模型协同策略模块.

基于学术志资料合集学习笔记中的多模型分工方案，为 ScholarPilot 提供智能的
模型协同策略。项目使用 LiteLLM 作为多模型网关，本模块负责在不同学术写作
阶段自动匹配最佳模型组合，并支持成本优化、质量优化和协同模式管理。

多模型分工原则::

    DeepSeek (deepseek-chat)   —— 深度推理 / 数学推导 / 代码调试 / 逻辑论证
    Claude  (claude-sonnet-4)  —— 中文表达 / 创意写作 / 长文写作
    GPT-4o  (gpt-4o)           —— 逻辑梳理 / 找漏洞 / 跨学科拓展
    Gemini  (gemini-2.0-flash) —— 文献处理 / 结构化分析 / 技术路线图
    豆包    (doubao-pro)        —— 中文表达 / 本土化 / 快速生成

四种协同模式::

    independent  —— 独立模式：单一模型完成任务
    sequential   —— 顺序模式：模型A生成 → 模型B审核/改进
    parallel     —— 并行模式：多模型同时生成 → 取最优/合并
    comparative  —— 对比模式：模型A生成 → 模型B评审 → 模型A修改

典型使用流程::

    from scholarpilot.tools.model_strategy import (
        ModelStrategyEngine, TaskType,
    )

    engine = ModelStrategyEngine()

    # 单任务匹配
    match = engine.match_model(TaskType.SECTION_WRITING, context={"language": "zh"})

    # 生成完整协同计划
    tasks = [TaskType.LITERATURE_REVIEW, TaskType.OUTLINE_GENERATION, TaskType.SECTION_WRITING]
    plan = engine.get_collaboration_plan(tasks)

    # 预算优化
    plan = engine.optimize_for_budget(tasks, max_cost=5.0)

    # 生成协同报告
    report = engine.generate_collaboration_report(plan)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

__all__ = [
    "TaskType",
    "ModelStrength",
    "ModelConfig",
    "TaskModelMatch",
    "ModelStrategyEngine",
    "MODEL_REGISTRY",
    "STRATEGY_PRESETS",
    "TASK_STRENGTH_MAP",
]


# =============================================================================
# 枚举定义
# =============================================================================


class TaskType(str, Enum):
    """学术写作任务类型枚举.

    按论文写作流程分为选题、文献、写作、润色、分析、投稿、答辩等阶段。

    Attributes:
        TOPIC_ANALYSIS: 选题分析 —— 分析研究方向的可行性与创新性.
        TOPIC_REFINEMENT: 选题优化 —— 细化与打磨研究问题.
        LITERATURE_SEARCH: 文献检索 —— 构建检索策略与关键词.
        LITERATURE_REVIEW: 文献综述 —— 综合梳理已有研究成果.
        LITERATURE_CRITIQUE: 文献批判 —— 评估文献质量与研究缺口.
        OUTLINE_GENERATION: 大纲生成 —— 构建论文结构框架.
        SECTION_WRITING: 分节写作 —— 撰写论文各章节正文.
        ABSTRACT_GENERATION: 摘要生成 —— 提炼论文摘要.
        POLISHING: 润色 —— 语言表达与学术风格优化.
        DE_AI: 去AI痕迹 —— 消除AI生成文本的典型特征.
        DATA_ANALYSIS: 数据分析 —— 处理与解读研究数据.
        STATISTICAL_MODELING: 统计建模 —— 构建与验证统计模型.
        JOURNAL_RECOMMENDATION: 期刊推荐 —— 匹配目标期刊.
        COVER_LETTER: 投稿信 —— 撰写投稿信.
        REVIEW_RESPONSE: 审稿回复 —— 撰写审稿意见回复.
        DEFENSE_PREP: 答辩准备 —— 准备答辩材料与预设问题.
        TRANSLATION: 翻译 —— 中英文互译.
        CODE_GENERATION: 代码生成 —— 生成研究用代码.
        LOGIC_CHECK: 逻辑检查 —— 审查论文论证逻辑.
    """

    # 选题阶段
    TOPIC_ANALYSIS = "topic_analysis"
    TOPIC_REFINEMENT = "topic_refinement"
    # 文献阶段
    LITERATURE_SEARCH = "literature_search"
    LITERATURE_REVIEW = "literature_review"
    LITERATURE_CRITIQUE = "literature_critique"
    # 写作阶段
    OUTLINE_GENERATION = "outline_generation"
    SECTION_WRITING = "section_writing"
    ABSTRACT_GENERATION = "abstract_generation"
    # 润色阶段
    POLISHING = "polishing"
    DE_AI = "de_ai"
    # 分析阶段
    DATA_ANALYSIS = "data_analysis"
    STATISTICAL_MODELING = "statistical_modeling"
    # 投稿阶段
    JOURNAL_RECOMMENDATION = "journal_recommendation"
    COVER_LETTER = "cover_letter"
    REVIEW_RESPONSE = "review_response"
    # 答辩阶段
    DEFENSE_PREP = "defense_prep"
    # 其他
    TRANSLATION = "translation"
    CODE_GENERATION = "code_generation"
    LOGIC_CHECK = "logic_check"


class ModelStrength(str, Enum):
    """模型能力维度枚举.

    Attributes:
        DEEP_REASONING: 深度推理 —— 复杂逻辑推演与因果分析.
        CHINESE_EXPRESSION: 中文表达 —— 中文学术语言的自然度与准确性.
        LOGIC_ANALYSIS: 逻辑分析 —— 发现论证漏洞与逻辑断层.
        LITERATURE_PROCESSING: 文献处理 —— 大规模文献的归纳与结构化.
        CREATIVE_WRITING: 创意写作 —— 创新性表达与叙事构建.
        CODE_DEBUGGING: 代码调试 —— 编程实现与错误排查.
        STRUCTURED_ANALYSIS: 结构化分析 —— 信息分类整理与框架构建.
        CROSS_DISCIPLINARY: 跨学科 —— 跨领域知识整合与迁移.
        MATH_DERIVATION: 数学推导 —— 数学公式推导与证明.
    """

    DEEP_REASONING = "deep_reasoning"
    CHINESE_EXPRESSION = "chinese_expression"
    LOGIC_ANALYSIS = "logic_analysis"
    LITERATURE_PROCESSING = "literature_processing"
    CREATIVE_WRITING = "creative_writing"
    CODE_DEBUGGING = "code_debugging"
    STRUCTURED_ANALYSIS = "structured_analysis"
    CROSS_DISCIPLINARY = "cross_disciplinary"
    MATH_DERIVATION = "math_derivation"


# =============================================================================
# 数据模型
# =============================================================================


class ModelConfig(BaseModel):
    """模型配置信息.

    Attributes:
        name: 模型名称（LiteLLM 调用标识）.
        alias: 中文别名.
        provider: 提供商.
        strengths: 能力维度列表.
        max_tokens: 单次最大输出 token 数.
        cost_per_1k: 每千 token 成本（美元）.
        speed_tier: 速度等级 —— fast / medium / slow.
        context_window: 上下文窗口大小（token）.
    """

    name: str
    alias: str
    provider: str
    strengths: list[ModelStrength]
    max_tokens: int
    cost_per_1k: float
    speed_tier: str  # fast / medium / slow
    context_window: int


class TaskModelMatch(BaseModel):
    """任务-模型匹配结果.

    Attributes:
        task_type: 任务类型.
        primary_model: 主模型名称.
        secondary_model: 辅助模型名称（可选，用于协同模式）.
        fallback_model: 备选模型名称（主模型不可用时回退）.
        reason: 选择理由.
        collaboration_mode: 协同模式 —— independent / sequential / parallel / comparative.
    """

    task_type: TaskType
    primary_model: str
    secondary_model: str | None = None
    fallback_model: str
    reason: str
    collaboration_mode: str = "independent"


# =============================================================================
# 模型注册表
# =============================================================================

MODEL_REGISTRY: dict[str, ModelConfig] = {
    "deepseek-chat": ModelConfig(
        name="deepseek-chat",
        alias="DeepSeek",
        provider="DeepSeek",
        strengths=[
            ModelStrength.DEEP_REASONING,
            ModelStrength.MATH_DERIVATION,
            ModelStrength.CODE_DEBUGGING,
            ModelStrength.LOGIC_ANALYSIS,
        ],
        max_tokens=8192,
        cost_per_1k=0.002,
        speed_tier="medium",
        context_window=65536,
    ),
    "claude-sonnet-4": ModelConfig(
        name="claude-sonnet-4",
        alias="Claude",
        provider="Anthropic",
        strengths=[
            ModelStrength.CHINESE_EXPRESSION,
            ModelStrength.CREATIVE_WRITING,
        ],
        max_tokens=8192,
        cost_per_1k=0.015,
        speed_tier="medium",
        context_window=200000,
    ),
    "gpt-4o": ModelConfig(
        name="gpt-4o",
        alias="GPT-4o",
        provider="OpenAI",
        strengths=[
            ModelStrength.LOGIC_ANALYSIS,
            ModelStrength.CROSS_DISCIPLINARY,
            ModelStrength.STRUCTURED_ANALYSIS,
        ],
        max_tokens=16384,
        cost_per_1k=0.005,
        speed_tier="fast",
        context_window=128000,
    ),
    "gemini-2.0-flash": ModelConfig(
        name="gemini-2.0-flash",
        alias="Gemini",
        provider="Google",
        strengths=[
            ModelStrength.LITERATURE_PROCESSING,
            ModelStrength.STRUCTURED_ANALYSIS,
        ],
        max_tokens=8192,
        cost_per_1k=0.001,
        speed_tier="fast",
        context_window=1000000,
    ),
    "doubao-pro": ModelConfig(
        name="doubao-pro",
        alias="豆包",
        provider="ByteDance",
        strengths=[
            ModelStrength.CHINESE_EXPRESSION,
        ],
        max_tokens=4096,
        cost_per_1k=0.0005,
        speed_tier="fast",
        context_window=32768,
    ),
}


# =============================================================================
# 任务-能力映射表
# =============================================================================

#: 每种任务类型优先需要的能力维度（按优先级排序）
TASK_STRENGTH_MAP: dict[TaskType, list[ModelStrength]] = {
    # 选题阶段
    TaskType.TOPIC_ANALYSIS: [
        ModelStrength.DEEP_REASONING,
        ModelStrength.CROSS_DISCIPLINARY,
    ],
    TaskType.TOPIC_REFINEMENT: [
        ModelStrength.DEEP_REASONING,
        ModelStrength.CREATIVE_WRITING,
    ],
    # 文献阶段
    TaskType.LITERATURE_SEARCH: [
        ModelStrength.LITERATURE_PROCESSING,
        ModelStrength.STRUCTURED_ANALYSIS,
    ],
    TaskType.LITERATURE_REVIEW: [
        ModelStrength.LITERATURE_PROCESSING,
        ModelStrength.STRUCTURED_ANALYSIS,
        ModelStrength.CHINESE_EXPRESSION,
    ],
    TaskType.LITERATURE_CRITIQUE: [
        ModelStrength.LOGIC_ANALYSIS,
        ModelStrength.DEEP_REASONING,
    ],
    # 写作阶段
    TaskType.OUTLINE_GENERATION: [
        ModelStrength.STRUCTURED_ANALYSIS,
        ModelStrength.DEEP_REASONING,
    ],
    TaskType.SECTION_WRITING: [
        ModelStrength.CREATIVE_WRITING,
        ModelStrength.CHINESE_EXPRESSION,
        ModelStrength.DEEP_REASONING,
    ],
    TaskType.ABSTRACT_GENERATION: [
        ModelStrength.CHINESE_EXPRESSION,
        ModelStrength.STRUCTURED_ANALYSIS,
    ],
    # 润色阶段
    TaskType.POLISHING: [
        ModelStrength.CHINESE_EXPRESSION,
        ModelStrength.CREATIVE_WRITING,
    ],
    TaskType.DE_AI: [
        ModelStrength.CHINESE_EXPRESSION,
        ModelStrength.CREATIVE_WRITING,
    ],
    # 分析阶段
    TaskType.DATA_ANALYSIS: [
        ModelStrength.STRUCTURED_ANALYSIS,
        ModelStrength.CODE_DEBUGGING,
    ],
    TaskType.STATISTICAL_MODELING: [
        ModelStrength.MATH_DERIVATION,
        ModelStrength.CODE_DEBUGGING,
    ],
    # 投稿阶段
    TaskType.JOURNAL_RECOMMENDATION: [
        ModelStrength.CROSS_DISCIPLINARY,
        ModelStrength.STRUCTURED_ANALYSIS,
    ],
    TaskType.COVER_LETTER: [
        ModelStrength.CREATIVE_WRITING,
        ModelStrength.CHINESE_EXPRESSION,
    ],
    TaskType.REVIEW_RESPONSE: [
        ModelStrength.LOGIC_ANALYSIS,
        ModelStrength.CHINESE_EXPRESSION,
    ],
    # 答辩阶段
    TaskType.DEFENSE_PREP: [
        ModelStrength.DEEP_REASONING,
        ModelStrength.LOGIC_ANALYSIS,
    ],
    # 其他
    TaskType.TRANSLATION: [
        ModelStrength.CHINESE_EXPRESSION,
    ],
    TaskType.CODE_GENERATION: [
        ModelStrength.CODE_DEBUGGING,
    ],
    TaskType.LOGIC_CHECK: [
        ModelStrength.LOGIC_ANALYSIS,
        ModelStrength.DEEP_REASONING,
    ],
}

#: 每种任务类型的默认协同模式
TASK_COLLABORATION_MAP: dict[TaskType, str] = {
    TaskType.TOPIC_ANALYSIS: "sequential",
    TaskType.TOPIC_REFINEMENT: "independent",
    TaskType.LITERATURE_SEARCH: "independent",
    TaskType.LITERATURE_REVIEW: "sequential",
    TaskType.LITERATURE_CRITIQUE: "comparative",
    TaskType.OUTLINE_GENERATION: "sequential",
    TaskType.SECTION_WRITING: "sequential",
    TaskType.ABSTRACT_GENERATION: "independent",
    TaskType.POLISHING: "parallel",
    TaskType.DE_AI: "independent",
    TaskType.DATA_ANALYSIS: "independent",
    TaskType.STATISTICAL_MODELING: "independent",
    TaskType.JOURNAL_RECOMMENDATION: "independent",
    TaskType.COVER_LETTER: "independent",
    TaskType.REVIEW_RESPONSE: "comparative",
    TaskType.DEFENSE_PREP: "sequential",
    TaskType.TRANSLATION: "independent",
    TaskType.CODE_GENERATION: "independent",
    TaskType.LOGIC_CHECK: "independent",
}


# =============================================================================
# 预设策略方案
# =============================================================================

STRATEGY_PRESETS: dict[str, dict[str, Any]] = {
    "economy": {
        "name": "经济方案",
        "description": "以 DeepSeek + 豆包 为主，最低成本",
        "model_priority": ["deepseek-chat", "doubao-pro", "gpt-4o"],
    },
    "standard": {
        "name": "标准方案",
        "description": "DeepSeek 推理 + Claude 写作 + GPT 审核",
        "model_priority": ["deepseek-chat", "claude-sonnet-4", "gpt-4o"],
    },
    "premium": {
        "name": "豪华方案",
        "description": "多模型协同，最佳质量",
        "model_priority": [
            "claude-sonnet-4",
            "gpt-4o",
            "deepseek-chat",
            "gemini-2.0-flash",
        ],
    },
}


# =============================================================================
# 核心引擎
# =============================================================================


class ModelStrategyEngine:
    """多模型协同策略引擎.

    根据任务类型、上下文（论文语言、学科、预算等）自动匹配最佳模型组合，
    支持四种协同模式（独立/顺序/并行/对比），并提供成本优化与质量优化能力。

    使用示例::

        engine = ModelStrategyEngine()
        match = engine.match_model(TaskType.SECTION_WRITING)
        plan = engine.get_collaboration_plan([TaskType.OUTLINE_GENERATION, TaskType.SECTION_WRITING])
    """

    def __init__(self, preset: str = "standard") -> None:
        """初始化策略引擎.

        Args:
            preset: 预设方案名称 —— economy / standard / premium.
        """
        self.preset = preset
        self.registry: dict[str, ModelConfig] = MODEL_REGISTRY
        self.presets: dict[str, dict[str, Any]] = STRATEGY_PRESETS

    # ------------------------------------------------------------------
    # 任务-模型匹配
    # ------------------------------------------------------------------

    def _score_model(
        self, model_name: str, preferred: list[ModelStrength]
    ) -> float:
        """计算模型对任务能力需求的匹配得分.

        Args:
            model_name: 模型名称.
            preferred: 任务优先需要的能力维度列表（按优先级排序）.

        Returns:
            匹配得分，越高表示越适合. 首位能力权重最高，依次递减.
        """
        model = self.registry.get(model_name)
        if model is None:
            return 0.0
        score = 0.0
        for idx, strength in enumerate(preferred):
            weight = 1.0 / (idx + 1)  # 首位权重 1.0，第二位 0.5，第三位 0.33 ...
            if strength in model.strengths:
                score += weight
        return score

    def _rank_models(
        self, preferred: list[ModelStrength]
    ) -> list[tuple[str, float]]:
        """按匹配得分对所有模型排序.

        Args:
            preferred: 任务优先需要的能力维度列表.

        Returns:
            (模型名称, 得分) 列表，按得分降序排列.
        """
        ranked = [
            (name, self._score_model(name, preferred))
            for name in self.registry
        ]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def match_model(
        self, task_type: TaskType, context: dict[str, Any] | None = None
    ) -> TaskModelMatch:
        """根据任务类型自动匹配最佳模型.

        综合考虑任务能力需求、上下文（论文语言、学科、预算等）和预设方案，
        选择主模型、辅助模型和备选模型，并确定协同模式。

        Args:
            task_type: 任务类型.
            context: 上下文字典，可包含以下键:
                - ``language``: 论文语言，``"zh"`` 或 ``"en"``.
                - ``discipline``: 学科领域，如 ``"economics"``.
                - ``budget``: 预算档位，``"economy"`` / ``"standard"`` / ``"premium"``.
                - ``token_estimate``: 预估 token 数.

        Returns:
            任务-模型匹配结果.
        """
        context = context or {}
        preferred = TASK_STRENGTH_MAP.get(task_type, [ModelStrength.DEEP_REASONING])
        collab_mode = TASK_COLLABORATION_MAP.get(task_type, "independent")

        # 根据上下文调整能力优先级
        language = context.get("language", "zh")
        if language == "zh" and ModelStrength.CHINESE_EXPRESSION not in preferred:
            preferred = preferred + [ModelStrength.CHINESE_EXPRESSION]

        # 根据预算档位选择预设方案
        budget_tier = context.get("budget", self.preset)
        model_priority = self.presets.get(
            budget_tier, self.presets[self.preset]
        )["model_priority"]

        # 在预设优先级范围内排序
        ranked_all = self._rank_models(preferred)
        priority_set = set(model_priority)

        # 优先使用预设方案内的模型，按得分排序
        ranked_in_preset = [
            (name, score) for name, score in ranked_all if name in priority_set
        ]
        ranked_fallback = [
            (name, score) for name, score in ranked_all if name not in priority_set
        ]
        ranked = ranked_in_preset + ranked_fallback

        if not ranked:
            # 兜底
            primary = model_priority[0]
            fallback = model_priority[-1] if len(model_priority) > 1 else primary
            return TaskModelMatch(
                task_type=task_type,
                primary_model=primary,
                secondary_model=None,
                fallback_model=fallback,
                reason="未找到匹配模型，使用默认方案.",
                collaboration_mode="independent",
            )

        primary = ranked[0][0]
        primary_score = ranked[0][1]

        # 辅助模型：选择能力互补的第二模型
        secondary = None
        if collab_mode in ("sequential", "parallel", "comparative"):
            for name, score in ranked[1:]:
                if name == primary:
                    continue
                # 选择能力互补的模型（strengths 不完全重叠）
                primary_strengths = set(self.registry[primary].strengths)
                other_strengths = set(self.registry[name].strengths)
                if other_strengths - primary_strengths:  # 有互补能力
                    secondary = name
                    break
            if secondary is None and len(ranked) > 1:
                secondary = ranked[1][0]

        # 备选模型：得分次高或成本更低的模型
        fallback = ranked[-1][0] if len(ranked) > 1 else primary
        # 如果备选和主模型相同，尝试找一个更便宜的
        if fallback == primary:
            cheapest = min(
                self.registry.keys(),
                key=lambda n: self.registry[n].cost_per_1k,
            )
            fallback = cheapest

        reason = self._build_reason(task_type, primary, secondary, preferred, primary_score)

        return TaskModelMatch(
            task_type=task_type,
            primary_model=primary,
            secondary_model=secondary,
            fallback_model=fallback,
            reason=reason,
            collaboration_mode=collab_mode,
        )

    def _build_reason(
        self,
        task_type: TaskType,
        primary: str,
        secondary: str | None,
        preferred: list[ModelStrength],
        score: float,
    ) -> str:
        """构建模型选择理由.

        Args:
            task_type: 任务类型.
            primary: 主模型名称.
            secondary: 辅助模型名称.
            preferred: 优先能力列表.
            score: 主模型匹配得分.

        Returns:
            选择理由文本.
        """
        model = self.registry[primary]
        matched = [s.value for s in preferred if s in model.strengths]
        parts = [
            f"任务「{task_type.value}」优先能力: {[s.value for s in preferred]}；",
            f"主模型 {model.alias}（{primary}）匹配能力: {matched}，得分 {score:.2f}。",
        ]
        if secondary:
            sec_model = self.registry[secondary]
            parts.append(f"辅助模型 {sec_model.alias}（{secondary}）用于协同。")
        return "".join(parts)

    def get_collaboration_plan(
        self, tasks: list[TaskType]
    ) -> list[TaskModelMatch]:
        """为一组任务生成完整的模型协同计划.

        依次匹配每个任务的最佳模型，整体保持协同模式的一致性。

        Args:
            tasks: 任务类型列表.

        Returns:
            任务-模型匹配列表，与输入任务一一对应.
        """
        plan: list[TaskModelMatch] = []
        for task in tasks:
            match = self.match_model(task)
            plan.append(match)
        return plan

    # ------------------------------------------------------------------
    # 成本优化
    # ------------------------------------------------------------------

    def estimate_cost(
        self, tasks: list[TaskType], tokens_per_task: int
    ) -> dict[str, Any]:
        """估算不同模型组合的成本.

        分别计算经济、标准、豪华三档方案的总成本。

        Args:
            tasks: 任务类型列表.
            tokens_per_task: 每个任务预估的 token 数.

        Returns:
            成本估算字典，结构::

                {
                    "economy": {"total_cost": float, "details": [...]},
                    "standard": {"total_cost": float, "details": [...]},
                    "premium": {"total_cost": float, "details": [...]},
                }
        """
        result: dict[str, Any] = {}
        original_preset = self.preset

        for tier in ("economy", "standard", "premium"):
            self.preset = tier
            plan = self.get_collaboration_plan(tasks)
            details: list[dict[str, Any]] = []
            total = 0.0
            for match in plan:
                cost = self._compute_task_cost(match, tokens_per_task)
                total += cost
                details.append({
                    "task": match.task_type.value,
                    "primary_model": match.primary_model,
                    "secondary_model": match.secondary_model,
                    "cost": round(cost, 4),
                    "collaboration_mode": match.collaboration_mode,
                })
            result[tier] = {
                "total_cost": round(total, 4),
                "details": details,
            }

        self.preset = original_preset
        return result

    def _compute_task_cost(
        self, match: TaskModelMatch, tokens: int
    ) -> float:
        """计算单个任务的预估成本.

        Args:
            match: 任务-模型匹配结果.
            tokens: 预估 token 数.

        Returns:
            预估成本（美元）.
        """
        cost = 0.0
        primary = self.registry.get(match.primary_model)
        if primary:
            cost += primary.cost_per_1k * (tokens / 1000)

        # 协同模式下辅助模型也需要消耗 token
        if match.secondary_model and match.collaboration_mode != "independent":
            secondary = self.registry.get(match.secondary_model)
            if secondary:
                # 顺序模式辅助模型处理约 50% token
                # 并行/对比模式辅助模型处理约 100% token
                ratio = 0.5 if match.collaboration_mode == "sequential" else 1.0
                cost += secondary.cost_per_1k * (tokens / 1000) * ratio

        return cost

    def optimize_for_budget(
        self, tasks: list[TaskType], max_cost: float
    ) -> list[TaskModelMatch]:
        """在预算约束下优化模型选择.

        从最佳匹配开始，逐步用更便宜的模型替换高成本模型，
        直到总成本满足预算约束。

        Args:
            tasks: 任务类型列表.
            max_cost: 最大预算（美元）.

        Returns:
            优化后的任务-模型匹配列表.
        """
        original_preset = self.preset

        # 按经济性从高到低尝试
        for tier in ("premium", "standard", "economy"):
            self.preset = tier
            plan = self.get_collaboration_plan(tasks)
            total = sum(
                self._compute_task_cost(m, 4000) for m in plan
            )
            if total <= max_cost:
                self.preset = original_preset
                logger.info(
                    "预算优化: 使用 %s 方案, 预估成本 $%.4f <= $%.4f",
                    tier, total, max_cost,
                )
                return plan

        # 所有方案都超预算，强制使用经济方案并替换最贵的模型
        self.preset = "economy"
        plan = self.get_collaboration_plan(tasks)
        self.preset = original_preset

        # 逐个替换为最便宜的可用模型
        cheapest_model = min(
            self.registry.keys(),
            key=lambda n: self.registry[n].cost_per_1k,
        )
        for match in plan:
            total = sum(self._compute_task_cost(m, 4000) for m in plan)
            if total <= max_cost:
                break
            if match.primary_model != cheapest_model:
                match.primary_model = cheapest_model
                match.secondary_model = None
                match.collaboration_mode = "independent"
                match.reason = f"预算约束（${max_cost}），降级至最经济模型."

        return plan

    # ------------------------------------------------------------------
    # 质量优化
    # ------------------------------------------------------------------

    def optimize_for_quality(
        self, tasks: list[TaskType]
    ) -> list[TaskModelMatch]:
        """不考虑成本，选择最佳模型组合.

        使用豪华方案，为每个任务匹配得分最高的模型，
        并在可能时启用协同模式以最大化质量。

        Args:
            tasks: 任务类型列表.

        Returns:
            质量最优的任务-模型匹配列表.
        """
        original_preset = self.preset
        self.preset = "premium"
        plan = self.get_collaboration_plan(tasks)
        self.preset = original_preset

        # 质量优先：对独立模式任务，尝试升级为协同模式
        for match in plan:
            if match.collaboration_mode == "independent":
                preferred = TASK_STRENGTH_MAP.get(
                    match.task_type, [ModelStrength.DEEP_REASONING]
                )
                ranked = self._rank_models(preferred)
                # 如果有得分接近的第二模型，升级为顺序协同
                if len(ranked) >= 2 and ranked[1][1] >= ranked[0][1] * 0.5:
                    match.secondary_model = ranked[1][0]
                    match.collaboration_mode = "sequential"
                    match.reason += " 质量优化: 升级为顺序协同模式."

        return plan

    # ------------------------------------------------------------------
    # 模型切换逻辑
    # ------------------------------------------------------------------

    def should_switch_model(
        self,
        current_task: TaskType,
        next_task: TaskType,
        current_model: str,
    ) -> bool:
        """判断是否需要切换模型.

        综合考虑任务连续性、模型切换成本和能力匹配度。
        当连续任务属于同一写作阶段且当前模型仍能胜任时，建议保持不变以减少切换成本。

        Args:
            current_task: 当前任务类型.
            next_task: 下一任务类型.
            current_model: 当前使用的模型名称.

        Returns:
            True 表示建议切换模型，False 表示建议保持当前模型.
        """
        # 同一任务类型，无需切换
        if current_task == next_task:
            return False

        # 计算当前模型对下一任务的得分
        next_preferred = TASK_STRENGTH_MAP.get(
            next_task, [ModelStrength.DEEP_REASONING]
        )
        current_score = self._score_model(current_model, next_preferred)

        # 找出下一任务的最佳模型
        ranked = self._rank_models(next_preferred)
        best_model = ranked[0][0] if ranked else current_model
        best_score = ranked[0][1] if ranked else 0.0

        # 如果当前模型就是最佳模型，无需切换
        if current_model == best_model:
            return False

        # 如果当前模型得分已经很高（达到最佳得分的 80% 以上），无需切换
        if best_score > 0 and current_score >= best_score * 0.8:
            logger.debug(
                "任务 %s → %s: 当前模型 %s 得分 %.2f >= 最佳 %.2f×0.8, 保持不变",
                current_task.value, next_task.value, current_model,
                current_score, best_score,
            )
            return False

        # 如果两任务属于同一阶段（能力需求相似），倾向不切换
        current_preferred = TASK_STRENGTH_MAP.get(
            current_task, [ModelStrength.DEEP_REASONING]
        )
        similarity = len(set(current_preferred) & set(next_preferred)) / max(
            len(set(current_preferred) | set(next_preferred)), 1
        )
        if similarity >= 0.5 and current_score > 0:
            return False

        return True

    # ------------------------------------------------------------------
    # Prompt 适配
    # ------------------------------------------------------------------

    #: 各模型的 Prompt 适配前缀
    PROMPT_ADAPTERS: dict[str, str] = {
        "deepseek-chat": (
            "【推理要求】请逐步展开推理过程，确保每一步逻辑严密、论证充分。"
            "对于涉及数学推导或形式逻辑的部分，请显式写出推导步骤。\n\n"
        ),
        "claude-sonnet-4": (
            "【表达要求】请用自然、流畅的中文学术语言撰写，"
            "注重段落之间的衔接与语气的连贯性，避免生硬的翻译腔。\n\n"
        ),
        "gpt-4o": (
            "【结构要求】请按结构化格式输出，使用清晰的层级标题、编号列表和表格。"
            "确保信息分类明确、逻辑层次分明。\n\n"
        ),
        "gemini-2.0-flash": (
            "【完整性要求】请确保信息覆盖全面，不遗漏关键要点。"
            "对文献或数据中的细节进行充分归纳，输出结构化的分析结果。\n\n"
        ),
        "doubao-pro": (
            "【生成要求】请快速生成简洁、自然的中文内容，"
            "注意使用符合中文学术习惯的表达方式。\n\n"
        ),
    }

    def adapt_prompt_for_model(self, prompt: str, model_name: str) -> str:
        """根据目标模型调整 Prompt 风格.

        为不同模型添加适配前缀，引导其发挥各自优势：
        - DeepSeek: 注重逻辑推理步骤.
        - Claude: 注重表达自然性.
        - GPT: 注重结构化输出.
        - Gemini: 注重信息完整性.
        - 豆包: 注重快速自然生成.

        Args:
            prompt: 原始 Prompt.
            model_name: 目标模型名称.

        Returns:
            适配后的 Prompt.
        """
        adapter = self.PROMPT_ADAPTERS.get(model_name, "")
        if adapter:
            return adapter + prompt
        return prompt

    # ------------------------------------------------------------------
    # 协同报告
    # ------------------------------------------------------------------

    def generate_collaboration_report(
        self, matches: list[TaskModelMatch]
    ) -> str:
        """生成 Markdown 格式的模型协同报告.

        报告包含任务-模型映射表、协同模式说明和成本估算。

        Args:
            matches: 任务-模型匹配列表.

        Returns:
            Markdown 格式的报告字符串.
        """
        lines: list[str] = []
        lines.append("# 多模型协同策略报告\n")
        lines.append(f"> 共 {len(matches)} 个任务\n")

        # 任务-模型映射表
        lines.append("\n## 一、任务-模型映射表\n")
        lines.append(
            "| # | 任务类型 | 主模型 | 辅助模型 | 备选模型 | 协同模式 |"
        )
        lines.append(
            "|---|----------|--------|----------|----------|----------|"
        )
        for idx, m in enumerate(matches, 1):
            primary_alias = self.registry.get(
                m.primary_model, type("", (), {"alias": m.primary_model})()
            ).alias
            sec_text = "-"
            if m.secondary_model:
                sec_alias = self.registry.get(
                    m.secondary_model, type("", (), {"alias": m.secondary_model})()
                ).alias
                sec_text = sec_alias
            fallback_alias = self.registry.get(
                m.fallback_model, type("", (), {"alias": m.fallback_model})()
            ).alias
            lines.append(
                f"| {idx} | {m.task_type.value} | {primary_alias} | "
                f"{sec_text} | {fallback_alias} | {m.collaboration_mode} |"
            )

        # 协同模式说明
        lines.append("\n## 二、协同模式说明\n")
        mode_descriptions = {
            "independent": "**独立模式** —— 单一模型独立完成任务，适用于简单或单一能力需求的任务.",
            "sequential": "**顺序模式** —— 主模型生成内容，辅助模型审核或改进。"
            "典型场景：DeepSeek 生成论证逻辑 → Claude 润色中文表达.",
            "parallel": "**并行模式** —— 多模型同时生成，取最优版本或合并。"
            "典型场景：Claude 和豆包同时写一段 → 取更好的版本.",
            "comparative": "**对比模式** —— 主模型生成，辅助模型评审，主模型修改。"
            "典型场景：DeepSeek 写实证分析 → GPT 找逻辑漏洞 → DeepSeek 修改.",
        }
        used_modes = {m.collaboration_mode for m in matches}
        for mode in ["independent", "sequential", "parallel", "comparative"]:
            if mode in used_modes:
                lines.append(f"- {mode_descriptions[mode]}")

        # 选择理由
        lines.append("\n## 三、模型选择理由\n")
        for m in matches:
            lines.append(f"### {m.task_type.value}")
            lines.append(f"- {m.reason}\n")

        # 成本估算
        lines.append("\n## 四、成本估算（按每任务 4000 token 估算）\n")
        lines.append("| 任务 | 主模型 | 成本（美元） |")
        lines.append("|------|--------|-------------|")
        total = 0.0
        for m in matches:
            cost = self._compute_task_cost(m, 4000)
            total += cost
            lines.append(
                f"| {m.task_type.value} | {m.primary_model} | ${cost:.4f} |"
            )
        lines.append(f"| **合计** | | **${total:.4f}** |")

        return "\n".join(lines)


# =============================================================================
# 模块级便捷函数
# =============================================================================


def quick_match(task_type: TaskType) -> TaskModelMatch:
    """快速匹配任务与模型（使用默认标准方案）.

    Args:
        task_type: 任务类型.

    Returns:
        任务-模型匹配结果.
    """
    engine = ModelStrategyEngine()
    return engine.match_model(task_type)


def quick_plan(tasks: list[TaskType]) -> list[TaskModelMatch]:
    """快速生成协同计划（使用默认标准方案）.

    Args:
        tasks: 任务类型列表.

    Returns:
        任务-模型匹配列表.
    """
    engine = ModelStrategyEngine()
    return engine.get_collaboration_plan(tasks)
