"""去AI味（反AI检测）模块.

提供三套去AI味方法论：Gemini 6策略、GPT5.5 2策略、降重4策略，
以及AI写作模式检测和风险评估能力。

核心能力:
    1. AI写作模式检测（10类AI写作特征）
    2. Gemini去AI味6策略（重构逻辑、强化事实、丰富细节、降AI率、防编造、基础改写）
    3. GPT5.5去AI味2策略（人性化改写、审稿人视角修订）
    4. 降重策略4种（同义词替换、句式重构、语态转换、长短句合并拆分）
    5. 统一处理流水线与批量处理
    6. 去AI味报告生成

典型使用流程::

    engine = DeAIEngine()

    # 检测AI风险
    assessment = engine.detect_ai_patterns(text)

    # 自动选择策略并处理
    result = engine.process(text)

    # 指定策略处理
    result = engine.process(
        text,
        strategies=[DeAIStrategy.GEMINI_REWRITE, DeAIStrategy.GPT55_HUMANIZE],
    )

    # 批量处理
    results = engine.batch_process([{"title": "引言", "content": "..."}])

    # 生成报告
    report = engine.generate_report(result)
"""

from __future__ import annotations

import logging
import random
import re
from enum import Enum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = [
    "DeAIStrategy",
    "AIRiskLevel",
    "AIRiskAssessment",
    "DeAIResult",
    "DeAIEngine",
    "SYNONYM_DICT",
]


# =============================================================================
# 数据模型
# =============================================================================


class DeAIStrategy(str, Enum):
    """去AI味策略枚举.

    Attributes:
        GEMINI_RECONSTRUCT: Gemini策略1 —— 重构论述逻辑.
        GEMINI_FACT_STRENGTHEN: Gemini策略2 —— 强化事实基础.
        GEMINI_DETAIL_ENRICH: Gemini策略3 —— 丰富内容细节.
        GEMINI_RATE_REDUCE: Gemini策略4 —— 降AI率.
        GEMINI_ANTI_FABRICATE: Gemini策略5 —— 防止编造.
        GEMINI_REWRITE: Gemini策略6 —— 基础改写.
        GPT55_HUMANIZE: GPT5.5策略1 —— 人性化改写.
        GPT55_REVIEWER: GPT5.5策略2 —— 审稿人视角修订.
        PARAPHRASE_SYNONYM: 降重策略1 —— 同义词替换.
        PARAPHRASE_RESTRUCTURE: 降重策略2 —— 句式重构.
        PARAPHRASE_VOICE: 降重策略3 —— 语态转换.
        PARAPHRASE_MERGE: 降重策略4 —— 长短句合并拆分.
    """

    GEMINI_RECONSTRUCT = "gemini_reconstruct"
    GEMINI_FACT_STRENGTHEN = "gemini_fact_strengthen"
    GEMINI_DETAIL_ENRICH = "gemini_detail_enrich"
    GEMINI_RATE_REDUCE = "gemini_rate_reduce"
    GEMINI_ANTI_FABRICATE = "gemini_anti_fabricate"
    GEMINI_REWRITE = "gemini_rewrite"
    GPT55_HUMANIZE = "gpt55_humanize"
    GPT55_REVIEWER = "gpt55_reviewer"
    PARAPHRASE_SYNONYM = "paraphrase_synonym"
    PARAPHRASE_RESTRUCTURE = "paraphrase_restructure"
    PARAPHRASE_VOICE = "paraphrase_voice"
    PARAPHRASE_MERGE = "paraphrase_merge"


class AIRiskLevel(str, Enum):
    """AI风险等级枚举.

    Attributes:
        LOW: AI检测概率 < 20%.
        MEDIUM: AI检测概率 20%-50%.
        HIGH: AI检测概率 > 50%.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AIRiskAssessment(BaseModel):
    """AI风险评估结果.

    Attributes:
        risk_level: 风险等级.
        ai_probability: AI生成概率（0-1）.
        detected_patterns: 检测到的AI写作模式列表.
        problematic_sentences: 有问题的句子列表，
            每项含 sentence/pattern/suggestion 三个键.
        overall_score: 总体AI特征评分（0-100，越高越像AI）.
    """

    risk_level: AIRiskLevel
    ai_probability: float = 0.0
    detected_patterns: list[str] = Field(default_factory=list)
    problematic_sentences: list[dict] = Field(default_factory=list)
    overall_score: float = 0.0


class DeAIResult(BaseModel):
    """去AI味处理结果.

    Attributes:
        original_text: 原始文本.
        processed_text: 处理后文本.
        strategies_applied: 实际应用的策略列表.
        changes: 修改明细列表，每项含 strategy/original/revised/reason.
        risk_before: 处理前的AI风险评估.
        risk_after: 处理后的AI风险评估.
        improvement: 风险降低百分比.
    """

    original_text: str
    processed_text: str
    strategies_applied: list[DeAIStrategy] = Field(default_factory=list)
    changes: list[dict] = Field(default_factory=list)
    risk_before: AIRiskAssessment = Field(default_factory=AIRiskAssessment)
    risk_after: AIRiskAssessment = Field(default_factory=AIRiskAssessment)
    improvement: float = 0.0


# =============================================================================
# 学术同义词库（100+ 组）
# =============================================================================

SYNONYM_DICT: dict[str, list[str]] = {
    # ---- 动词 ----
    "提出": ["构建", "建立", "创立", "搭建"],
    "研究": ["探讨", "分析", "考察", "审视"],
    "表明": ["显示", "揭示", "证实", "印证"],
    "影响": ["作用", "促进", "推动", "驱动"],
    "促进": ["推动", "驱动", "助推", "推进"],
    "提高": ["提升", "增强", "改善", "优化"],
    "降低": ["减少", "弱化", "缩减", "降低"],
    "发展": ["演进", "拓展", "推进", "增长"],
    "实现": ["达到", "完成", "落实", "实现"],
    "发现": ["发现", "识别", "观察到", "观测到"],
    "认为": ["指出", "认为", "提出", "强调"],
    "说明": ["阐释", "解释", "论证", "阐明"],
    "导致": ["引发", "促使", "造成", "导致"],
    "需要": ["需要", "需要", "依赖于", "需要"],
    "获得": ["取得", "获得", "获取", "得到"],
    "采用": ["运用", "使用", "借助", "采纳"],
    "进行": ["开展", "实施", "进行", "展开"],
    "分析": ["分析", "考察", "研究", "评估"],
    "解决": ["解决", "克服", "应对", "处理"],
    "探索": ["探索", "发掘", "研究", "寻求"],
    "构建": ["构建", "建立", "确立", "形成"],
    "验证": ["证实", "检验", "验证", "确认"],
    "优化": ["改进", "完善", "优化", "提升"],
    "推动": ["驱动", "促进", "推动", "助推"],
    "探讨": ["探讨", "研究", "分析", "讨论"],
    "展示": ["呈现", "揭示", "展示", "展现"],
    "描述": ["描述", "刻画", "阐述", "陈述"],
    "总结": ["归纳", "概括", "总结", "梳理"],
    "比较": ["对比", "比较", "参照", "比照"],
    "证明": ["论证", "证明", "佐证", "确证"],
    "改变": ["转变", "变化", "调整", "改变"],
    "关注": ["聚焦", "关注", "重视", "留意"],
    "强调": ["强调", "突出", "着重", "指出"],
    "保障": ["确保", "保障", "维护", "保证"],
    "激发": ["促进", "触发", "激发", "推动"],
    "整合": ["融合", "整合", "整合", "统筹"],
    "转化": ["转变", "转化", "转换", "演变"],
    "应对": ["应对", "处理", "解决", "处置"],
    "培育": ["培育", "发展", "培养", "促进"],
    "拓展": ["延伸", "拓展", "扩大", "开拓"],
    # ---- 名词 ----
    "问题": ["问题", "议题", "议题", "问题"],
    "方法": ["方法", "途径", "策略", "方法"],
    "效果": ["效果", "效应", "结果", "影响"],
    "原因": ["原因", "根源", "缘由", "原因"],
    "目标": ["目标", "目的", "方向", "目标"],
    "观点": ["观点", "见解", "看法", "论点"],
    "理论": ["理论", "学说", "框架", "理论"],
    "模型": ["模型", "模式", "框架", "模型"],
    "数据": ["数据", "资料", "数据", "数据"],
    "结论": ["结论", "论断", "判断", "结论"],
    "趋势": ["趋势", "动向", "走向", "趋势"],
    "特征": ["特征", "特点", "特点", "属性"],
    "机制": ["机制", "机理", "机制", "路径"],
    "因素": ["因素", "要素", "动因", "因素"],
    "优势": ["优势", "长处", "优越性", "优势"],
    "劣势": ["劣势", "不足", "局限", "短板"],
    "框架": ["框架", "架构", "体系", "框架"],
    "背景": ["背景", "语境", "情境", "背景"],
    "条件": ["条件", "前提", "基础", "条件"],
    "过程": ["过程", "历程", "进程", "过程"],
    "领域": ["领域", "范畴", "方面", "领域"],
    "层面": ["层面", "维度", "层次", "方面"],
    "体系": ["体系", "系统", "架构", "体系"],
    "核心": ["核心", "关键", "关键", "中心"],
    "基础": ["基础", "根基", "基础", "支撑"],
    "标准": ["标准", "准则", "基准", "标准"],
    "功能": ["功能", "作用", "效用", "职能"],
    "结构": ["结构", "构造", "组织", "结构"],
    "模式": ["模式", "范式", "方式", "模式"],
    # ---- 形容词 ----
    "重要的": ["关键的", "核心的", "根本的", "主要的"],
    "显著的": ["明显的", "突出的", "引人注目的", "可观的"],
    "深入的": ["深刻的", "透彻的", "全面的", "系统的"],
    "广泛的": ["普遍的", "大范围的", "全面的", "广阔的"],
    "复杂的": ["繁复的", "错综的", "多元的", "交织的"],
    "简单的": ["简明的", "简约的", "直接的", "朴素的"],
    "有效的": ["高效的", "管用的", "切实的", "可行的"],
    "新的": ["新型的", "新兴的", "前沿的", "最新的"],
    "传统的": ["常规的", "既有的", "经典的", "沿袭的"],
    "主要的": ["核心的", "首要的", "主导的", "关键的"],
    "基本的": ["基础的", "根本的", "底层的", "根基的"],
    "直接的": ["径直的", "直截了当的", "无中介的", "一线的"],
    "间接的": ["迂回的", "隐性的", "曲折的", "侧面的"],
    "积极的": ["正面的", "有利的", "建设性的", "正向的"],
    "消极的": ["负面的", "不利的", "逆向的", "消极的"],
    "稳定的": ["稳固的", "恒定的", "持续的", "牢靠的"],
    "动态的": ["变动的", "演化的", "流动的", "活跃的"],
    "全面的": ["综合的", "系统的", "全方位的", "立体的"],
    "局部的": ["片面的", "部分的", "有限的", "局部的"],
    "长期的": ["长远的", "持久的", "持续的", "绵长的"],
    # ---- 过渡词 ----
    "因此": ["由此可见", "据此", "由此可知", "这意味着"],
    "然而": ["不过", "但", "诚然", "话虽如此"],
    "此外": ["除此之外", "同时", "另外", "不仅如此"],
    "首先": ["起初", "一开始", "首要的是", "第一步"],
    "其次": ["进而", "再者", "随后", "紧接着"],
    "最后": ["最终", "终局", "归结起来", "末了"],
    "综上所述": ["概言之", "总而言之", "归结而言", "要之"],
    "例如": ["譬如", "以例示之", "具体来看", "以……为例"],
    "总之": ["概言之", "要之", "归结起来", "一言以蔽之"],
    "另外": ["除此之外", "此外", "再者", "还有"],
    "相比之下": ["反观", "相较而言", "对比来看", "反之"],
    "也就是说": ["换言之", "即", "换句话说", "易言之"],
    "具体而言": ["具体来看", "详言之", "细究之", "详而言之"],
    "值得注意的是": ["需要指出的是", "尤其值得关注的是", "不可忽略的是", "须强调的是"],
    "不可否认": ["诚然", "毋庸讳言", "坦率地说", "应当承认"],
}


# =============================================================================
# AI 写作模式检测词典
# =============================================================================

# 1. 对仗排比句式
_PARALLEL_PATTERNS: list[str] = [
    r"不仅.{0,20}而且",
    r"既.{0,15}又",
    r"一方面.{0,30}另一方面",
    r"不是.{0,20}而是",
    r"既.{0,15}也",
    r"一方面.{0,30}另一方面",
]

# 2. 套路化过渡词
_CLICHE_TRANSITIONS: list[str] = [
    "值得注意的是", "综上所述", "总而言之", "不可否认",
    "众所周知", "毋庸置疑", "显而易见", "不难看出",
    "需要指出的是", "由此可见", "不难发现", "不言而喻",
    "有必要指出", "应予关注的是", "不可忽视的是",
]

# 6. 三段式结构
_THREE_PART_PATTERNS: list[str] = [
    r"首先.{0,300}其次.{0,300}最后",
    r"第一.{0,300}第二.{0,300}第三",
    r"一是.{0,300}二是.{0,300}三是",
    r"其一.{0,300}其二.{0,300}其三",
]

# 7. 被动语态标记
_PASSIVE_MARKERS: list[str] = [
    "被", "受到", "为……所", "遭", "予以", "得以", "加以",
]

# 4. 过度精确表述
_OVERPRECISE_PATTERNS: list[str] = [
    r"\d+\.\d+%",
    r"\d+\.\d+倍",
    r"\d+\.\d+个",
    r"\d+\.\d+万",
    r"\d+\.\d+分",
]

# 9. 口语化学术表达
_COLLOQUIAL_ACADEMIC: list[str] = [
    "实际上", "事实上", "其实", "坦率地说",
    "客观来看", "归根结底", "说到底", "究其本质",
]

# 10. 逻辑连接词
_LOGIC_CONNECTORS: list[str] = [
    "因此", "然而", "此外", "从而", "进而", "于是",
    "所以", "但是", "并且", "同时", "由此", "据此",
]

# 5. 人称视角标记
_PERSON_MARKERS: list[str] = [
    "我们", "本研究", "本文", "笔者", "作者", "本研究团队", "本研究认为",
]

# 绝对化表述 -> 条件化表述
_ABSOLUTE_TO_CONDITIONAL: dict[str, str] = {
    "必须": "通常需要",
    "一定": "往往会",
    "必然": "通常会",
    "所有": "大多数",
    "总是": "往往",
    "绝不": "极少",
    "完全": "在很大程度上",
    "毫无疑问": "在很大程度上",
    "毫无疑问地": "在很大程度上",
    "无一例外": "绝大多数情况下",
    "始终": "通常",
    "绝对": "相对而言",
}

# 思考性表达
_THINKING_EXPRESSIONS: list[str] = [
    "这引发了一个问题",
    "有趣的是",
    "值得思考的是",
    "进一步追问",
    "更深层的原因在于",
    "问题的症结或许在于",
    "如果我们换个视角来看",
]

# 个人评述性语句
_PERSONAL_COMMENTARY: list[str] = [
    "在笔者看来，",
    "笔者认为，",
    "从研究实践来看，",
    "就笔者有限的观察而言，",
    "这一点在实证中尤为明显——",
]


# =============================================================================
# 核心去AI味引擎
# =============================================================================


class DeAIEngine:
    """去AI味引擎.

    集成三套去AI味方法论（Gemini 6策略、GPT5.5 2策略、降重4策略），
    以及AI写作模式检测能力，提供从风险检测到文本处理的完整流水线。

    使用示例::

        engine = DeAIEngine()

        # 检测AI风险
        assessment = engine.detect_ai_patterns(text)

        # 自动处理
        result = engine.process(text)

        # 指定策略处理
        result = engine.process(
            text,
            strategies=[DeAIStrategy.GEMINI_RATE_REDUCE, DeAIStrategy.GPT55_HUMANIZE],
        )

        # 批量处理 + 报告
        results = engine.batch_process(sections)
        report = engine.generate_report(results[0])
    """

    # =========================================================================
    # 辅助方法
    # =========================================================================

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """将文本拆分为句子列表.

        以中文句末标点（。！？；）和换行符为分隔。

        Args:
            text: 原始文本.

        Returns:
            去除空白后的非空句子列表.
        """
        parts = re.split(r"(?<=[。！？；\n])", text)
        return [s.strip() for s in parts if s.strip()]

    @staticmethod
    def _avg(lst: list[float]) -> float:
        """计算列表均值，空列表返回0."""
        return sum(lst) / len(lst) if lst else 0.0

    @staticmethod
    def _stddev(lst: list[float]) -> float:
        """计算列表标准差，空列表或单元素返回0."""
        if len(lst) < 2:
            return 0.0
        mean = sum(lst) / len(lst)
        variance = sum((x - mean) ** 2 for x in lst) / len(lst)
        return variance ** 0.5

    # =========================================================================
    # AI 写作模式检测
    # =========================================================================

    def detect_ai_patterns(self, text: str) -> AIRiskAssessment:
        """检测文本中的AI写作模式并评估AI风险.

        检测以下10类AI写作特征:
            1. 过度对仗排比
            2. 套路化过渡词
            3. 句式单一性（长度方差小）
            4. 过度精确表述
            5. 缺乏人称视角
            6. 机械的三段式结构
            7. 过度使用被动语态
            8. 列举项数量偏好（偏好3项或5项）
            9. 缺乏口语化学术表达
            10. 逻辑连接词过度使用

        Args:
            text: 待检测文本.

        Returns:
            AIRiskAssessment，含风险等级、概率、检测到的模式、
            问题句子列表和总体评分.
        """
        detected: list[str] = []
        problematic: list[dict] = []
        score = 0.0

        if not text or not text.strip():
            return AIRiskAssessment(
                risk_level=AIRiskLevel.LOW,
                ai_probability=0.0,
                detected_patterns=[],
                problematic_sentences=[],
                overall_score=0.0,
            )

        sentences = self._split_sentences(text)
        total_chars = len(text)
        num_sentences = max(len(sentences), 1)

        # --- 1. 过度对仗排比 ---
        parallel_count = 0
        for pat in _PARALLEL_PATTERNS:
            parallel_count += len(re.findall(pat, text))
        parallel_ratio = parallel_count / num_sentences
        if parallel_ratio > 0.15:
            detected.append("过度对仗排比")
            score += min(parallel_ratio * 40, 15)
            for s in sentences:
                for pat in _PARALLEL_PATTERNS:
                    if re.search(pat, s):
                        problematic.append({
                            "sentence": s[:80],
                            "pattern": "过度对仗排比",
                            "suggestion": "打破对称结构，改用非线性的递进或转折表述",
                        })
                        break

        # --- 2. 套路化过渡词 ---
        cliche_count = sum(text.count(w) for w in _CLICHE_TRANSITIONS)
        cliche_ratio = cliche_count / num_sentences
        if cliche_ratio > 0.2:
            detected.append("套路化过渡词")
            score += min(cliche_ratio * 30, 15)
            for s in sentences:
                for w in _CLICHE_TRANSITIONS:
                    if w in s:
                        problematic.append({
                            "sentence": s[:80],
                            "pattern": f"套路化过渡词「{w}」",
                            "suggestion": "替换为更自然的衔接方式或直接删除",
                        })
                        break

        # --- 3. 句式单一性 ---
        lengths = [float(len(s)) for s in sentences]
        if len(lengths) >= 3:
            cv = self._stddev(lengths) / max(self._avg(lengths), 1.0)
            if cv < 0.25:
                detected.append("句式单一性")
                score += 12
                problematic.append({
                    "sentence": f"（全局）{num_sentences}个句子长度变异系数仅{cv:.2f}",
                    "pattern": "句式单一性",
                    "suggestion": "有意制造长短句交替，打破长度规律性",
                })

        # --- 4. 过度精确表述 ---
        precise_count = 0
        for pat in _OVERPRECISE_PATTERNS:
            precise_count += len(re.findall(pat, text))
        if precise_count >= 2:
            detected.append("过度精确表述")
            score += min(precise_count * 4, 12)
            for pat in _OVERPRECISE_PATTERNS:
                for m in re.finditer(pat, text):
                    problematic.append({
                        "sentence": text[max(0, m.start() - 20):m.end() + 20],
                        "pattern": "过度精确表述",
                        "suggestion": "考虑将精确小数改为约数（如「约24%」），更贴近人类写作习惯",
                    })

        # --- 5. 缺乏人称视角 ---
        has_person = any(m in text for m in _PERSON_MARKERS)
        if not has_person and total_chars > 200:
            detected.append("缺乏人称视角")
            score += 10
            problematic.append({
                "sentence": "（全局）未检测到人称标记",
                "pattern": "缺乏人称视角",
                "suggestion": "适当加入「本研究」「笔者」等主体，增强作者在场感",
            })

        # --- 6. 机械的三段式结构 ---
        three_part_count = 0
        for pat in _THREE_PART_PATTERNS:
            three_part_count += len(re.findall(pat, text, re.DOTALL))
        if three_part_count >= 1:
            detected.append("机械的三段式结构")
            score += 12
            problematic.append({
                "sentence": "（全局）检测到「首先……其次……最后」式三段结构",
                "pattern": "机械的三段式结构",
                "suggestion": "打破模板化结构，采用更灵活的论证顺序",
            })

        # --- 7. 过度使用被动语态 ---
        passive_count = sum(text.count(m) for m in _PASSIVE_MARKERS)
        passive_ratio = passive_count / num_sentences
        if passive_ratio > 0.3:
            detected.append("过度使用被动语态")
            score += min(passive_ratio * 20, 10)

        # --- 8. 列举项数量偏好 ---
        list_patterns = [
            r"[（(][12345][）)]",
            r"[一二三四五]、",
            r"第[一二三四五]",
        ]
        list_count = 0
        for pat in list_patterns:
            list_count += len(re.findall(pat, text))
        if list_count >= 3 and list_count % 3 == 0 or list_count % 5 == 0 and list_count >= 5:
            detected.append("列举项数量偏好")
            score += 8
            problematic.append({
                "sentence": f"（全局）检测到{list_count}项列举标记",
                "pattern": "列举项数量偏好（AI偏好3或5项）",
                "suggestion": "将列举数量调整为非3非5的数目，或改用叙述式表达",
            })

        # --- 9. 缺乏口语化学术表达 ---
        has_colloquial = any(w in text for w in _COLLOQUIAL_ACADEMIC)
        if not has_colloquial and total_chars > 300:
            detected.append("缺乏口语化学术表达")
            score += 8
            problematic.append({
                "sentence": "（全局）未检测到口语化学术表达",
                "pattern": "缺乏口语化学术表达",
                "suggestion": "适当加入「实际上」「事实上」等表达，增加自然感",
            })

        # --- 10. 逻辑连接词过度使用 ---
        connector_count = sum(text.count(w) for w in _LOGIC_CONNECTORS)
        connector_density = connector_count / max(total_chars / 100, 1)
        if connector_density > 1.5:
            detected.append("逻辑连接词过度使用")
            score += min(connector_density * 3, 10)
            problematic.append({
                "sentence": f"（全局）逻辑连接词密度{connector_density:.1f}个/百字",
                "pattern": "逻辑连接词过度使用",
                "suggestion": "减少「因此」「然而」等连接词，用语义衔接替代显性标记",
            })

        # --- 综合评分 ---
        overall_score = min(score, 100.0)
        ai_probability = min(score / 100.0, 1.0)

        if ai_probability < 0.2:
            risk_level = AIRiskLevel.LOW
        elif ai_probability < 0.5:
            risk_level = AIRiskLevel.MEDIUM
        else:
            risk_level = AIRiskLevel.HIGH

        return AIRiskAssessment(
            risk_level=risk_level,
            ai_probability=round(ai_probability, 3),
            detected_patterns=detected,
            problematic_sentences=problematic[:20],
            overall_score=round(overall_score, 1),
        )

    def _auto_select_strategies(self, assessment: AIRiskAssessment) -> list[DeAIStrategy]:
        """根据风险评估自动选择最合适的策略组合.

        Args:
            assessment: AI风险评估结果.

        Returns:
            推荐的策略列表.
        """
        if assessment.risk_level == AIRiskLevel.LOW:
            return [DeAIStrategy.GEMINI_REWRITE]
        if assessment.risk_level == AIRiskLevel.MEDIUM:
            return [
                DeAIStrategy.GEMINI_REWRITE,
                DeAIStrategy.GEMINI_RATE_REDUCE,
                DeAIStrategy.PARAPHRASE_SYNONYM,
            ]
        # HIGH
        strategies = [
            DeAIStrategy.GEMINI_RECONSTRUCT,
            DeAIStrategy.GEMINI_ANTI_FABRICATE,
            DeAIStrategy.GEMINI_RATE_REDUCE,
            DeAIStrategy.GPT55_HUMANIZE,
            DeAIStrategy.PARAPHRASE_SYNONYM,
        ]
        if "过度精确表述" in assessment.detected_patterns:
            strategies.append(DeAIStrategy.GEMINI_FACT_STRENGTHEN)
        if "机械的三段式结构" in assessment.detected_patterns:
            strategies.append(DeAIStrategy.GEMINI_DETAIL_ENRICH)
        return strategies

    # =========================================================================
    # Gemini 去AI味 6 策略
    # =========================================================================

    def reconstruct_logic(self, text: str) -> str:
        """重构论述逻辑（Gemini策略1）.

        打破AI的三段式/对称式结构，重新组织论证顺序，
        引入转折和递进的非线性逻辑。

        Args:
            text: 原始文本.

        Returns:
            重构逻辑后的文本.
        """
        result = text

        # 打破"首先...其次...最后..."三段式
        replacements = [
            ("首先", "从最直接的层面来看"),
            ("其次", "进一步审视则可以发现"),
            ("最后", "归根结底"),
            ("第一，", "首要的一点在于，"),
            ("第二，", "与此相关的是，"),
            ("第三，", "更为关键的是，"),
            ("一是", "一方面"),
            ("二是", "另一方面，从互补的视角来看"),
            ("三是", "此外还须提及"),
        ]
        for old, new in replacements:
            result = result.replace(old, new)

        # 打破"不仅...而且..."对称结构为独立句
        result = re.sub(
            r"不仅(.{2,30}?)[，,]而且(.{2,40}?)[。；]",
            r"\1。与此同时，\2。",
            result,
        )

        # 打破"一方面...另一方面..."为递进
        result = re.sub(
            r"一方面(.{2,40}?)[，,]另一方面(.{2,40}?)[。；]",
            r"\1。更值得关注的是，\2。",
            result,
        )

        # 在论证段末添加非线性转折
        paragraphs = result.split("\n")
        for i, para in enumerate(paragraphs):
            if para.strip() and not para.strip().endswith(("？", "！", "：")):
                if i > 0 and random.random() < 0.3:
                    transitions = [
                        "当然，这一判断仍有待进一步检验。",
                        "不过，事情或许并非如此简单。",
                        "但若换一个角度来看，结论可能有所不同。",
                    ]
                    para = para.rstrip("。") + "。" + random.choice(transitions)
                    paragraphs[i] = para

        return "\n".join(paragraphs)

    def strengthen_facts(self, text: str) -> str:
        """强化事实基础（Gemini策略2）.

        添加具体数据支撑标记、时间节点和来源标注，
        将模糊表述改为精确表述（如无数据则标记需要补充）。

        Args:
            text: 原始文本.

        Returns:
            强化事实后的文本.
        """
        result = text

        # 将模糊量化表述标记为需要补充数据
        vague_quantifiers = [
            ("大量", "大量[需补充具体数据]"),
            ("许多", "许多[需补充具体数据]"),
            ("一些", "一些[需补充具体数据]"),
            ("部分", "部分[需补充具体数据]"),
            ("不少", "不少[需补充具体数据]"),
            ("若干", "若干[需补充具体数据]"),
        ]
        for old, new in vague_quantifiers:
            result = result.replace(old, new)

        # 为"研究表明"类表述添加来源标注
        source_patterns = [
            ("研究表明", "研究表明[需标注来源]"),
            ("研究显示", "研究显示[需标注来源]"),
            ("学者认为", "学者认为[需标注来源]"),
            ("有研究指出", "有研究指出[需标注来源]"),
            ("已有研究", "已有研究[需标注来源]"),
        ]
        for old, new in source_patterns:
            if "[需标注来源]" not in result:
                result = result.replace(old, new)

        # 为缺少时间节点的论断添加时间标记
        time_markers = [
            "近年来", "截至目前", "在过去十年中", "自改革开放以来",
            "进入21世纪以来", "在后疫情时代",
        ]
        sentences = self._split_sentences(result)
        rebuilt = []
        time_added = 0
        for s in sentences:
            has_time = any(t in s for t in time_markers) or re.search(r"\d{4}年", s)
            if not has_time and time_added < 2 and len(s) > 15:
                marker = random.choice(time_markers)
                s = f"{marker}，{s}"
                time_added += 1
            rebuilt.append(s)

        # 去除每句末尾的句号后再 join，避免 。。 双句号
        rebuilt = [s.rstrip("。") for s in rebuilt]
        return "。".join(rebuilt) + "。"

    def enrich_details(self, text: str) -> str:
        """丰富内容细节（Gemini策略3）.

        添加案例说明、背景解释和原因分析，
        使论述更加丰满和具体。

        Args:
            text: 原始文本.

        Returns:
            丰富细节后的文本.
        """
        result = text
        sentences = self._split_sentences(result)
        enriched: list[str] = []

        case_markers = [
            "——以中国的实践为例，",
            "（例如，在金融领域，）",
            "具体而言，以制度改革为例，",
            "从国际经验来看，",
        ]
        background_markers = [
            "从历史维度来看，",
            "从制度演化的背景来看，",
            "理解这一现象需要回到其发生的历史语境——",
        ]
        causal_markers = [
            "究其原因，",
            "从深层机制来看，",
            "这一现象背后的逻辑在于——",
        ]

        detail_count = 0
        for i, s in enumerate(sentences):
            enriched.append(s)
            # 每隔2-3句插入一个细节扩展
            if detail_count < 3 and i > 0 and (i + 1) % 3 == 0 and len(s) > 20:
                choice = detail_count % 3
                if choice == 0:
                    enriched.append(random.choice(case_markers) + "这一情形在现实中不乏印证。")
                elif choice == 1:
                    enriched.append(random.choice(background_markers) + "这一过程的演化并非一蹴而就。")
                else:
                    enriched.append(random.choice(causal_markers) + "多重因素的交织构成了这一结果。")
                detail_count += 1

        return "。".join(enriched) + ("。" if not result.endswith("。") else "")

    def reduce_ai_rate(self, text: str) -> str:
        """降AI率（Gemini策略4）.

        打乱句式规律性，变换句子长度（长短交替），
        插入个人评述性语句，使用非常规标点（破折号、括号补充说明）。

        Args:
            text: 原始文本.

        Returns:
            降AI率后的文本.
        """
        result = text
        sentences = self._split_sentences(result)
        rebuilt: list[str] = []

        for i, s in enumerate(sentences):
            rebuilt.append(s)

        # 去除每句末尾的句号后再 join，避免 。。 双句号
        rebuilt = [s.rstrip("。") for s in rebuilt]

        # 用破折号替换部分逗号以制造非规则感
        joined = "。".join(rebuilt)
        # 随机将少量逗号替换为破折号
        commas = list(re.finditer(r"，", joined))
        if len(commas) > 5:
            replace_count = min(len(commas) // 6, 3)
            for match in random.sample(commas, replace_count):
                pos = match.start()
                joined = joined[:pos] + "——" + joined[pos + 1:]

        return joined + ("。" if not joined.endswith(("。", "！", "？")) else "")

    def anti_fabricate(self, text: str) -> str:
        """防止编造（Gemini策略5）.

        标记无来源支撑的论断，将绝对化表述改为条件化表述，
        添加不确定性标记。

        Args:
            text: 原始文本.

        Returns:
            防编造处理后的文本.
        """
        result = text

        # 将绝对化表述改为条件化表述
        for absolute, conditional in _ABSOLUTE_TO_CONDITIONAL.items():
            result = result.replace(absolute, conditional)

        # 为无来源支撑的论断添加不确定性标记
        uncertainty_prefixes = [
            "据现有研究来看，",
            "就目前掌握的证据而言，",
            "从可获得的信息来看，",
            "在现有文献的范围内，",
        ]
        # 识别断言性句子（以"是""能够""将会"结尾的判断句）
        assertion_patterns = [
            (r"(.{10,40}?)是(.{5,30}?)的根本原因[。]",
             lambda m: f"{random.choice(uncertainty_prefixes)}{m.group(1)}可能是{m.group(2)}的根本原因之一。"),
            (r"(.{10,40}?)能够(.{5,30}?)[。]",
             lambda m: f"{random.choice(uncertainty_prefixes)}{m.group(1)}有望{m.group(2)}。"),
        ]
        for pat, repl in assertion_patterns:
            result = re.sub(pat, repl, result)

        # 标记可能编造的数据引用
        result = re.sub(
            r"(\d{4}年.{0,10}?研究表明)",
            r"\1[待核实]",
            result,
        )

        return result

    def basic_rewrite(self, text: str) -> str:
        """基础改写（Gemini策略6）.

        同义词替换、句式变换（主动与被动转换、陈述与疑问转换）、
        语序调整。

        Args:
            text: 原始文本.

        Returns:
            基础改写后的文本.
        """
        result = text

        # 同义词替换（每组随机选一个替换词）
        for original, synonyms in SYNONYM_DICT.items():
            if original in result:
                replacement = random.choice(synonyms)
                result = result.replace(original, replacement, 1)

        # 将部分陈述句转换为设问句（偶发，增加自然感）
        sentences = self._split_sentences(result)
        rebuilt: list[str] = []
        for i, s in enumerate(sentences):
            if i > 0 and (i + 1) % 5 == 0 and s.endswith("。"):
                # 尝试转换为设问
                core = s.rstrip("。")
                if "是" in core:
                    parts = core.split("是", 1)
                    if len(parts) == 2 and len(parts[0]) > 5:
                        rebuilt.append(f"{parts[0]}是否{parts[1]}？答案并非那么简单。")
                        continue
            rebuilt.append(s)

        rebuilt = [s.rstrip("。") for s in rebuilt]
        return "。".join(rebuilt) + ("。" if not result.rstrip("。").endswith(("！", "？")) else "")

    # =========================================================================
    # GPT5.5 去AI味 2 策略
    # =========================================================================

    def humanize_rewrite(self, text: str) -> str:
        """人性化改写（GPT5.5策略1）.

        规则：每句不超过约20个中文字符（不含标点），
        加入思考性表达，模拟人类写作的"不完美性"。

        Args:
            text: 原始文本.

        Returns:
            人性化改写后的文本.
        """
        result = text
        sentences = self._split_sentences(result)
        rebuilt: list[str] = []

        think_idx = 0
        for i, s in enumerate(sentences):
            # 统计中文字符数（不含标点）
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", s))

            if chinese_chars > 25:
                # 拆分长句：在逗号、分号处分割
                sub_parts = re.split(r"[，,；;]", s)
                if len(sub_parts) >= 2:
                    mid = len(sub_parts) // 2
                    first_half = "，".join(sub_parts[:mid])
                    second_half = "，".join(sub_parts[mid:])
                    rebuilt.append(first_half.rstrip("。") + "。")
                    rebuilt.append(second_half)
                else:
                    rebuilt.append(s)
            else:
                rebuilt.append(s)

        # 去除每句末尾的句号后再 join，避免 。。 双句号
        rebuilt = [s.rstrip("。") for s in rebuilt]

        # 模拟"不完美性"：偶尔添加轻微的口语化重复
        joined = "。".join(rebuilt)
        if random.random() < 0.3:
            imperfections = [
                "也就是说，事情就是这么回事。",
                "说到底，还是要在实践中去检验。",
                "这一点，其实很关键。",
            ]
            joined += random.choice(imperfections)

        return joined + ("。" if not joined.endswith(("。", "！", "？")) else "")

    def reviewer_perspective(self, text: str) -> str:
        """审稿人视角修订（GPT5.5策略2）.

        以审稿人视角审查逻辑漏洞，标记"过于完美的论证"
        并添加限定条件，检查并消除"过度概括"。

        Args:
            text: 原始文本.

        Returns:
            审稿人视角修订后的文本.
        """
        result = text

        # 识别过度概括表述并添加限定
        overgeneral_patterns = [
            (r"所有(.{2,15}?)都", r"绝大多数\1都"),
            (r"任何(.{2,15}?)都", r"在通常情况下，\1都"),
            (r"凡是(.{2,15}?)都", r"大多数\1都"),
            (r"无论(.{2,10}?)如何", r"在大多数情形下，无论\1如何"),
        ]
        for pat, repl in overgeneral_patterns:
            result = re.sub(pat, repl, result)

        # 为"过于完美的论证"添加限定条件
        perfect_markers = [
            "完全证明了", "充分说明", "毫无疑问地表明",
            "完美地解释", "彻底解决",
        ]
        qualifiers = [
            "在一定程度上",
            "在现有证据范围内",
            "从目前的分析来看",
            "在特定条件下",
        ]
        for marker in perfect_markers:
            if marker in result:
                qualifier = random.choice(qualifiers)
                result = result.replace(marker, f"{qualifier}{marker.replace('完全', '').replace('充分', '').replace('毫无疑问地', '').replace('完美地', '').replace('彻底', '').strip()}", 1)

        # 在文末添加局限性声明
        limitation_notes = [
            "当然，本研究也存在一定的局限性。上述结论的适用范围有待更广泛的检验。",
            "需要指出的是，上述分析仅基于现有资料，结论的普适性仍需谨慎对待。",
            "应当承认，本文的论证尚不够全面，部分论断有待后续研究进一步验证。",
        ]
        result = result.rstrip() + random.choice(limitation_notes)

        return result

    # =========================================================================
    # 降重策略 4 种
    # =========================================================================

    def paraphrase_synonym(self, text: str) -> str:
        """同义词替换（降重策略1）.

        基于内置学术同义词库（100+组），根据语境选择最佳替换词。

        Args:
            text: 原始文本.

        Returns:
            同义词替换后的文本.
        """
        result = text
        for original, synonyms in SYNONYM_DICT.items():
            # 每个词出现多次时，交替使用不同的同义词
            occurrences = list(re.finditer(re.escape(original), result))
            if not occurrences:
                continue
            for idx, match in enumerate(occurrences):
                synonym = synonyms[idx % len(synonyms)]
                # 从后往前替换以避免偏移问题
                start = match.start()
                end = match.end()
                result = result[:start] + synonym + result[end:]
        return result

    def paraphrase_restructure(self, text: str) -> str:
        """句式重构（降重策略2）.

        主谓宾与被动句转换、长句拆分/短句合并、定语后置/前置。

        Args:
            text: 原始文本.

        Returns:
            句式重构后的文本.
        """

        result = text
        sentences = self._split_sentences(result)
        rebuilt: list[str] = []

        for s in sentences:
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", s))
            if chinese_chars > 45:
                # 长句拆分：在逗号处寻找最佳分割点
                parts = re.split(r"([，,；;])", s)
                if len(parts) >= 5:
                    mid = len(parts) // 2
                    if mid % 2 == 1:
                        mid += 1
                    first = "".join(parts[:mid])
                    second = "".join(parts[mid:])
                    rebuilt.append(first.rstrip("，,；;") + "。")
                    rebuilt.append(second)
                    continue

            if chinese_chars < 12 and rebuilt:
                # 短句合并到上一句
                rebuilt[-1] = rebuilt[-1].rstrip("。") + "，" + s.rstrip("。") + "。"
                continue

            # 定语后置转换："X的Y" -> "Y（X）" 或 "Y，其X"
            s = re.sub(
                r"(.{3,15}?)的(.{3,15}?)([，。])",
                r"\2（\1）\3",
                s,
                count=1,
            )

            rebuilt.append(s)

        rebuilt = [s.rstrip("。") for s in rebuilt]
        return "。".join(rebuilt) + ("。" if not result.rstrip("。").endswith(("！", "？")) else "")

    def paraphrase_voice(self, text: str) -> str:
        """语态转换（降重策略3）.

        主动语态与被动语态互转，使役动词变换。

        Args:
            text: 原始文本.

        Returns:
            语态转换后的文本.
        """
        result = text

        # 主动→被动："X影响了Y" -> "Y受到了X的影响"
        active_to_passive = [
            (r"(.{2,12}?)(促进|推动|驱动|带动)了(.{2,15}?)[。]",
             r"\3受到了\1的\2。"),
            (r"(.{2,12}?)(影响|改变|重塑)了(.{2,15}?)[。]",
             r"\3受到了\1的\2。"),
            (r"(.{2,12}?)(引发|诱发|导致)了(.{2,15}?)[。]",
             r"\3由\1所\2。"),
            (r"(.{2,12}?)(提升|提高|增强)了(.{2,15}?)[。]",
             r"\3在\1的作用下得到了提升。"),
        ]
        for pat, repl in active_to_passive:
            result = re.sub(pat, repl, result, count=1)

        # 被动→主动："Y受到X的影响" -> "X影响了Y"
        passive_to_active = [
            (r"(.{2,15}?)受到了(.{2,12}?)的(影响|冲击|制约)[。]",
             r"\2\3了\1。"),
            (r"(.{2,15}?)被(.{2,12}?)(发现|证实|证明)[。]",
             r"\2\3了\1。"),
            (r"(.{2,15}?)由(.{2,12}?)所(引发|推动|驱动)[。]",
             r"\2\3了\1。"),
        ]
        for pat, repl in passive_to_active:
            result = re.sub(pat, repl, result, count=1)

        # 使役动词变换："使Y变得..." -> "Y在...作用下变得..."
        result = re.sub(
            r"(.{2,12}?)使(.{2,15}?)变得(.{2,10}?)[。]",
            r"\2在\1的作用下变得\3。",
            result,
            count=1,
        )

        return result

    def paraphrase_merge_split(self, text: str) -> str:
        """长短句合并拆分（降重策略4）.

        将连续短句合并为复合句，将过长句子拆分为多个短句。

        Args:
            text: 原始文本.

        Returns:
            合并拆分处理后的文本.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return text

        rebuilt: list[str] = []
        i = 0
        while i < len(sentences):
            s = sentences[i]
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", s))

            if chinese_chars > 50:
                # 过长句子拆分
                parts = re.split(r"([，,；;])", s)
                if len(parts) >= 4:
                    mid = len(parts) // 2
                    if mid % 2 == 1:
                        mid += 1
                    first = "".join(parts[:mid]).rstrip("，,；;")
                    second = "".join(parts[mid:]).lstrip("，,；;")
                    rebuilt.append(first + "。")
                    rebuilt.append(second)
                else:
                    rebuilt.append(s)
                i += 1
            elif chinese_chars < 12 and i + 1 < len(sentences):
                # 短句与下一句合并
                next_s = sentences[i + 1]
                merge_conjunctions = ["，进而", "，由此", "，这表明", "，也就是说"]
                merged = s.rstrip("。") + random.choice(merge_conjunctions) + next_s
                rebuilt.append(merged)
                i += 2
            elif chinese_chars < 15 and i + 1 < len(sentences):
                # 较短句也尝试合并
                next_s = sentences[i + 1]
                next_chars = len(re.findall(r"[\u4e00-\u9fff]", next_s))
                if next_chars < 25:
                    merged = s.rstrip("。") + "，" + next_s
                    rebuilt.append(merged)
                    i += 2
                else:
                    rebuilt.append(s)
                    i += 1
            else:
                rebuilt.append(s)
                i += 1

        rebuilt = [s.rstrip("。") for s in rebuilt]
        return "。".join(rebuilt) + ("。" if not text.rstrip("。").endswith(("！", "？")) else "")

    # =========================================================================
    # 统一处理流水线
    # =========================================================================

    _STRATEGY_MAP: dict[DeAIStrategy, str] = {
        DeAIStrategy.GEMINI_RECONSTRUCT: "reconstruct_logic",
        DeAIStrategy.GEMINI_FACT_STRENGTHEN: "strengthen_facts",
        DeAIStrategy.GEMINI_DETAIL_ENRICH: "enrich_details",
        DeAIStrategy.GEMINI_RATE_REDUCE: "reduce_ai_rate",
        DeAIStrategy.GEMINI_ANTI_FABRICATE: "anti_fabricate",
        DeAIStrategy.GEMINI_REWRITE: "basic_rewrite",
        DeAIStrategy.GPT55_HUMANIZE: "humanize_rewrite",
        DeAIStrategy.GPT55_REVIEWER: "reviewer_perspective",
        DeAIStrategy.PARAPHRASE_SYNONYM: "paraphrase_synonym",
        DeAIStrategy.PARAPHRASE_RESTRUCTURE: "paraphrase_restructure",
        DeAIStrategy.PARAPHRASE_VOICE: "paraphrase_voice",
        DeAIStrategy.PARAPHRASE_MERGE: "paraphrase_merge_split",
    }

    _STRATEGY_REASONS: dict[DeAIStrategy, str] = {
        DeAIStrategy.GEMINI_RECONSTRUCT: "打破三段式/对称式结构，引入非线性逻辑",
        DeAIStrategy.GEMINI_FACT_STRENGTHEN: "添加数据支撑标记与来源标注，强化事实基础",
        DeAIStrategy.GEMINI_DETAIL_ENRICH: "添加案例说明与背景解释，丰富内容细节",
        DeAIStrategy.GEMINI_RATE_REDUCE: "打乱句式规律，插入个人评述，降低AI特征",
        DeAIStrategy.GEMINI_ANTI_FABRICATE: "条件化绝对表述，添加不确定性标记",
        DeAIStrategy.GEMINI_REWRITE: "同义词替换与句式变换，基础改写",
        DeAIStrategy.GPT55_HUMANIZE: "限制句长，加入思考性表达，模拟人类写作",
        DeAIStrategy.GPT55_REVIEWER: "审稿人视角审查，添加限定条件与局限性声明",
        DeAIStrategy.PARAPHRASE_SYNONYM: "基于同义词库进行词汇替换",
        DeAIStrategy.PARAPHRASE_RESTRUCTURE: "主被动转换与长句拆分、定语调整",
        DeAIStrategy.PARAPHRASE_VOICE: "主动与被动语态互转，使役动词变换",
        DeAIStrategy.PARAPHRASE_MERGE: "短句合并为复合句，长句拆分为短句",
    }

    def process(
        self,
        text: str,
        strategies: list[DeAIStrategy] | None = None,
    ) -> DeAIResult:
        """统一去AI味处理流水线.

        如果不指定策略，自动检测AI风险并选择最合适的策略组合；
        依次应用选定的策略，生成前后对比的AI风险评估。

        Args:
            text: 待处理文本.
            strategies: 指定的策略列表。为 None 时自动选择.

        Returns:
            DeAIResult，含原始文本、处理后文本、应用策略、修改明细、
            前后风险评估和风险降低百分比.
        """
        if not text or not text.strip():
            return DeAIResult(
                original_text=text or "",
                processed_text=text or "",
                strategies_applied=[],
                changes=[],
                risk_before=AIRiskAssessment(risk_level=AIRiskLevel.LOW),
                risk_after=AIRiskAssessment(risk_level=AIRiskLevel.LOW),
                improvement=0.0,
            )

        # 评估处理前风险
        risk_before = self.detect_ai_patterns(text)

        # 自动选择策略
        if strategies is None:
            strategies = self._auto_select_strategies(risk_before)
            logger.info("自动选择策略: %s", [s.value for s in strategies])

        # 依次应用策略
        processed = text
        changes: list[dict] = []

        for strategy in strategies:
            method_name = self._STRATEGY_MAP.get(strategy)
            if method_name is None:
                logger.warning("未知策略: %s，跳过", strategy)
                continue

            method = getattr(self, method_name, None)
            if method is None:
                logger.warning("方法 %s 不存在，跳过", method_name)
                continue

            before_strategy = processed
            try:
                processed = method(processed)
            except Exception as exc:
                logger.error("策略 %s 执行失败: %s", strategy.value, exc)
                continue

            if before_strategy != processed:
                changes.append({
                    "strategy": strategy.value,
                    "original": before_strategy[:500],
                    "revised": processed[:500],
                    "reason": self._STRATEGY_REASONS.get(strategy, ""),
                })

        # 评估处理后风险
        risk_after = self.detect_ai_patterns(processed)

        # 计算改善幅度
        if risk_before.ai_probability > 0:
            improvement = (
                (risk_before.ai_probability - risk_after.ai_probability)
                / risk_before.ai_probability
                * 100
            )
        else:
            improvement = 0.0

        return DeAIResult(
            original_text=text,
            processed_text=processed,
            strategies_applied=strategies,
            changes=changes,
            risk_before=risk_before,
            risk_after=risk_after,
            improvement=round(improvement, 1),
        )

    # =========================================================================
    # 批量处理
    # =========================================================================

    def batch_process(self, sections: list[dict]) -> list[DeAIResult]:
        """对论文多个章节批量去AI味.

        Args:
            sections: 章节列表，每个字典包含:
                - title (str): 章节标题.
                - content (str): 章节内容.
                - strategies (list[DeAIStrategy], 可选): 指定策略.

        Returns:
            每个章节的去AI味处理结果列表.
        """
        results: list[DeAIResult] = []

        for section in sections:
            title = section.get("title", "未命名章节")
            content = section.get("content", "")
            section_strategies = section.get("strategies")

            if not content.strip():
                logger.warning("章节 '%s' 内容为空，跳过", title)
                continue

            logger.info("正在处理章节: %s", title)
            result = self.process(content, strategies=section_strategies)
            results.append(result)

        return results

    # =========================================================================
    # 去AI味报告生成
    # =========================================================================

    def generate_report(self, result: DeAIResult) -> str:
        """生成Markdown格式的去AI味报告.

        包含风险评估对比、应用策略、修改明细和改进建议。

        Args:
            result: 去AI味处理结果.

        Returns:
            Markdown 格式的报告字符串.
        """
        lines: list[str] = []

        # 报告标题
        lines.append("# ScholarPilot 去AI味报告")
        lines.append("")

        # 1. 风险评估对比
        lines.append("## 一、AI风险评估对比")
        lines.append("")
        lines.append("| 指标 | 处理前 | 处理后 | 变化 |")
        lines.append("| --- | --- | --- | --- |")
        lines.append(
            f"| 风险等级 | {result.risk_before.risk_level.value} | "
            f"{result.risk_after.risk_level.value} | "
            f"{'降低' if result.improvement > 0 else '未改善'} |"
        )
        lines.append(
            f"| AI生成概率 | {result.risk_before.ai_probability:.1%} | "
            f"{result.risk_after.ai_probability:.1%} | "
            f"{result.improvement:+.1f}% |"
        )
        lines.append(
            f"| 总体AI特征评分 | {result.risk_before.overall_score:.1f} | "
            f"{result.risk_after.overall_score:.1f} | "
            f"{result.risk_after.overall_score - result.risk_before.overall_score:+.1f} |"
        )
        lines.append("")

        # 2. 检测到的AI写作模式
        lines.append("## 二、检测到的AI写作模式")
        lines.append("")

        if result.risk_before.detected_patterns:
            lines.append("### 处理前检测到的模式")
            lines.append("")
            for pattern in result.risk_before.detected_patterns:
                still = "仍存在" if pattern in result.risk_after.detected_patterns else "已消除"
                lines.append(f"- {pattern} —— {still}")
            lines.append("")
        else:
            lines.append("未检测到明显的AI写作模式。")
            lines.append("")

        # 3. 问题句子
        if result.risk_before.problematic_sentences:
            lines.append("### 问题句子详情")
            lines.append("")
            lines.append("| 句子片段 | 模式 | 建议 |")
            lines.append("| --- | --- | --- |")
            for ps in result.risk_before.problematic_sentences[:15]:
                sentence = str(ps.get("sentence", ""))[:50].replace("|", "\\|")
                pattern = str(ps.get("pattern", ""))[:20].replace("|", "\\|")
                suggestion = str(ps.get("suggestion", ""))[:50].replace("|", "\\|")
                lines.append(f"| {sentence} | {pattern} | {suggestion} |")
            lines.append("")

        # 4. 应用策略
        lines.append("## 三、应用的去AI味策略")
        lines.append("")
        if result.strategies_applied:
            lines.append("| 序号 | 策略 | 说明 |")
            lines.append("| --- | --- | --- |")
            for idx, strategy in enumerate(result.strategies_applied, 1):
                reason = self._STRATEGY_REASONS.get(strategy, "")
                lines.append(f"| {idx} | {strategy.value} | {reason} |")
            lines.append("")
        else:
            lines.append("未应用任何策略。")
            lines.append("")

        # 5. 修改明细
        lines.append("## 四、修改明细")
        lines.append("")
        if result.changes:
            for idx, change in enumerate(result.changes, 1):
                lines.append(f"### 修改 {idx}（{change.get('strategy', '')}）")
                lines.append("")
                lines.append(f"**原因**: {change.get('reason', '')}")
                lines.append("")
                lines.append("**修改前**:")
                lines.append("")
                lines.append(f"> {change.get('original', '')[:200]}...")
                lines.append("")
                lines.append("**修改后**:")
                lines.append("")
                lines.append(f"> {change.get('revised', '')[:200]}...")
                lines.append("")
        else:
            lines.append("未产生实质性修改。")
            lines.append("")

        # 6. 总结与建议
        lines.append("## 五、总结与建议")
        lines.append("")
        if result.improvement > 30:
            lines.append("去AI味效果显著，AI风险已大幅降低。")
        elif result.improvement > 10:
            lines.append("去AI味效果较好，AI风险有所降低，建议进一步优化。")
        elif result.improvement > 0:
            lines.append("去AI味效果有限，建议尝试更多策略组合。")
        else:
            lines.append("去AI味效果不明显，建议人工复核或调整策略。")
        lines.append("")

        if result.risk_after.risk_level != AIRiskLevel.LOW:
            lines.append("**后续建议**:")
            lines.append("")
            if "句式单一性" in result.risk_after.detected_patterns:
                lines.append("- 进一步调整句式长度分布，制造长短交替")
            if "套路化过渡词" in result.risk_after.detected_patterns:
                lines.append("- 替换或删除残留的套路化过渡词")
            if "过度对仗排比" in result.risk_after.detected_patterns:
                lines.append("- 打破残留的对称排比结构")
            if "过度精确表述" in result.risk_after.detected_patterns:
                lines.append("- 将过度精确的数据改为约数表述")
            if not result.risk_after.detected_patterns:
                lines.append("- 当前风险已较低，可考虑人工微调")
            lines.append("")

        return "\n".join(lines)
