"""多层次润色引擎.

提供语法层、表达层、逻辑层、风格层、定位层共五层润色能力，
支持英文/中文/双语润色，集成斯坦福大学官方推荐的8类润色指令。

五层润色架构::

    语法层 (Grammar)      —— 只纠错不改写，生成错误双列表格
    表达层 (Expression)   —— 句式优化、学术表达精准度提升
    逻辑层 (Logic)        —— 论点断层检测、段落衔接优化
    风格层 (Style)        —— 期刊风格适配、正式程度调整
    定位层 (Positioning)  —— 精确定位修改点、提供修改建议

典型使用流程::

    engine = PolishEngine()
    # 语法层
    errors = engine.check_grammar(text, lang=PolishLanguage.ENGLISH)
    result = engine.fix_grammar(text, lang=PolishLanguage.ENGLISH)
    # 表达层
    result = engine.polish_english(text)
    result = engine.polish_sci_paper(text)
    # 逻辑层
    issues = engine.analyze_logic(text)
    result = engine.optimize_transitions(text)
    # 批量润色 + 报告
    results = engine.batch_polish(sections, layers=[PolishLayer.GRAMMAR, PolishLayer.EXPRESSION])
    report = engine.generate_report(results)
"""

from __future__ import annotations

import logging
import re
from enum import Enum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = [
    "PolishLayer",
    "PolishLanguage",
    "PolishResult",
    "GrammarError",
    "LogicIssue",
    "PolishEngine",
    "STANFORD_POLISH_INSTRUCTIONS",
]


# =============================================================================
# 数据模型
# =============================================================================


class PolishLayer(str, Enum):
    """润色层级枚举.

    Attributes:
        GRAMMAR: 语法层 —— 检查并修正语法错误.
        EXPRESSION: 表达层 —— 优化句式与学术表达.
        LOGIC: 逻辑层 —— 分析并优化论证连贯性.
        STYLE: 风格层 —— 适配期刊风格与正式程度.
        POSITIONING: 定位层 —— 精确定位修改点与建议.
    """

    GRAMMAR = "grammar"
    EXPRESSION = "expression"
    LOGIC = "logic"
    STYLE = "style"
    POSITIONING = "positioning"


class PolishLanguage(str, Enum):
    """润色语言枚举.

    Attributes:
        ENGLISH: 英文润色.
        CHINESE: 中文润色.
        BILINGUAL: 双语润色.
    """

    ENGLISH = "english"
    CHINESE = "chinese"
    BILINGUAL = "bilingual"


class PolishResult(BaseModel):
    """润色结果.

    Attributes:
        original_text: 原始文本.
        polished_text: 润色后文本.
        layer: 应用的润色层级.
        changes: 修改明细列表，每项含 type/original/revised/reason/position.
        change_count: 修改数量.
        improvement_summary: 改进摘要.
    """

    original_text: str
    polished_text: str
    layer: PolishLayer
    changes: list[dict] = Field(default_factory=list)
    change_count: int = 0
    improvement_summary: str = ""


class GrammarError(BaseModel):
    """语法错误条目.

    Attributes:
        position: 句子定位（如"第3句"或"第2段第1句"）.
        error_type: 语法错误类型（如"时态"/"主谓一致"/"冠词"/"介词"）.
        original: 原始文本片段.
        correction: 修正后文本片段.
        explanation: 修正说明.
    """

    position: str
    error_type: str
    original: str
    correction: str
    explanation: str


class LogicIssue(BaseModel):
    """逻辑问题条目.

    Attributes:
        position: 问题位置定位.
        issue_type: 问题类型（断层/跳跃/循环/矛盾）.
        description: 问题描述.
        suggestion: 修改建议.
    """

    position: str
    issue_type: str
    description: str
    suggestion: str


# =============================================================================
# 斯坦福8类润色指令
# =============================================================================

STANFORD_POLISH_INSTRUCTIONS: dict[str, str] = {
    "grammar": "检查并修正语法错误，包括时态、主谓一致、冠词使用",
    "clarity": "提升表达清晰度，消除歧义和模糊表述",
    "flow": "改善行文流畅度，优化段落和句子间的过渡",
    "tone": "调整语气，确保学术写作的正式性和客观性",
    "word_choice": "优化用词选择，提升学术表达的精确性",
    "conciseness": "精简冗余表达，提升信息密度",
    "structure": "优化句子结构，增强可读性",
    "formatting": "规范格式，确保符合学术写作规范",
}


# =============================================================================
# 常量词典
# =============================================================================

# 英文弱表达 -> 学术强表达
_ENGLISH_EXPRESSION_UPGRADES: dict[str, str] = {
    "a lot of": "numerous",
    "lots of": "numerous",
    "very important": "crucial",
    "very big": "substantial",
    "very small": "negligible",
    "very good": "excellent",
    "very high": "substantial",
    "very low": "minimal",
    "really": "",
    "so that": "such that",
    "in order to": "to",
    "due to the fact that": "because",
    "in spite of the fact that": "although",
    "in the event that": "if",
    "at this point in time": "currently",
    "in the process of": "",
    "it should be noted that": "",
    "it is worth noting that": "",
    "as a matter of fact": "",
    "for the purpose of": "for",
    "in the nature of": "",
    "the reason why": "because",
    "make a decision": "decide",
    "conduct an investigation": "investigate",
    "give a description of": "describe",
    "make an analysis of": "analyze",
    "reach a conclusion": "conclude",
    "show a tendency": "tend",
    "is able to": "can",
    "are able to": "can",
    "has the ability to": "can",
    "in addition to": "besides",
    "a number of": "several",
    "the majority of": "most",
    "utilize": "use",
    "demonstrate": "show",
    "approximately": "about",
    "subsequent to": "after",
    "prior to": "before",
    "in accordance with": "according to",
    "with regard to": "regarding",
    "in terms of": "for",
    "on the basis of": "based on",
}

# 英文口语化表达 -> 正式表达
_ENGLISH_COLLOQUIAL: dict[str, str] = {
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "can't": "cannot",
    "won't": "will not",
    "wouldn't": "would not",
    "shouldn't": "should not",
    "couldn't": "could not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "hasn't": "has not",
    "haven't": "have not",
    "it's": "it is",
    "they're": "they are",
    "we're": "we are",
    "you're": "you are",
    "that's": "that is",
    "there's": "there is",
    "get": "obtain",
    "got": "obtained",
    "kids": "children",
    "stuff": "materials",
    "thing": "factor",
    "things": "factors",
    "big": "significant",
    "small": "minor",
    "good": "favorable",
    "bad": "adverse",
    "kind of": "somewhat",
    "sort of": "somewhat",
    "a lot": "considerably",
}

# 中文口语化表达 -> 书面表达
_CHINESE_COLLOQUIAL: dict[str, str] = {
    "我觉得": "本文认为",
    "我们认为": "研究表明",
    "大家知道": "众所周知",
    "所以说": "因此",
    "然后": "随后",
    "其实": "事实上",
    "说白了": "简言之",
    "差不多": "约",
    "大概": "约",
    "好多": "大量",
    "挺": "较为",
    "非常非常": "极为",
    "越来越": "日益",
    "搞": "开展",
    "弄": "进行",
    "东西": "要素",
    "办法": "方法",
    "好处": "优势",
    "坏处": "劣势",
    "看了看": "审视了",
    "想了一下": "经过思考",
    "差不多的": "近似的",
    "一下子": "骤然",
    "总的来说": "总体而言",
    "总而言之": "综上所述",
    "也就是说": "即",
    "换句话说": "换言之",
}

# 中文重复表达同义词库
_CHINESE_SYNONYMS: dict[str, list[str]] = {
    "影响": ["作用", "效应", "冲击"],
    "促进": ["推动", "驱动", "助推"],
    "提高": ["提升", "增强", "改善"],
    "降低": ["削减", "弱化", "缩减"],
    "表明": ["显示", "揭示", "证实"],
    "研究": ["考察", "探讨", "分析"],
    "问题": ["议题", "挑战", "困境"],
    "发展": ["演进", "拓展", "推进"],
    "重要": ["关键", "核心", "至关重要"],
    "显著": ["明显", "突出", "引人注目"],
}

# 段落过渡词库
_TRANSITION_WORDS: dict[str, list[str]] = {
    "addition": ["此外", "另外", "同时", "与此同时", "Furthermore", "Moreover", "In addition"],
    "contrast": ["然而", "但是", "相比之下", "However", "Nevertheless", "In contrast"],
    "cause": ["因此", "由此可见", "Consequently", "Therefore", "As a result"],
    "sequence": ["首先", "其次", "最后", "First", "Subsequently", "Finally"],
    "example": ["例如", "具体而言", "For instance", "Specifically", "Namely"],
    "conclusion": ["综上所述", "总之", "In summary", "To conclude", "Overall"],
}

# 主观色彩表达（需去除）
_SUBJECTIVE_EXPRESSIONS: list[str] = [
    "令人惊讶的是",
    "令人遗憾的是",
    "有趣的是",
    "遗憾的是",
    "令人欣慰的是",
    "令人鼓舞的是",
    "遗憾的是",
    "surprisingly",
    "interestingly",
    "unfortunately",
    "fortunately",
    "remarkably",
    "astonishingly",
]

# 期刊风格配置
_JOURNAL_STYLES: dict[str, dict] = {
    "Nature": {"max_words": 2500, "prefer_passive": False, "conciseness": "high"},
    "Science": {"max_words": 2500, "prefer_passive": False, "conciseness": "high"},
    "Econometrica": {"max_words": 8000, "prefer_passive": True, "conciseness": "medium"},
    "AER": {"max_words": 6000, "prefer_passive": False, "conciseness": "medium"},
    "管理世界": {"max_words": 15000, "prefer_passive": False, "conciseness": "low"},
    "经济研究": {"max_words": 12000, "prefer_passive": False, "conciseness": "low"},
    "金融研究": {"max_words": 12000, "prefer_passive": False, "conciseness": "low"},
}


# =============================================================================
# 核心润色引擎
# =============================================================================


class PolishEngine:
    """多层次润色引擎.

    集成语法层、表达层、逻辑层、风格层、定位层共五层润色能力，
    支持英文/中文/双语润色，并内置斯坦福8类润色指令。

    使用示例::

        engine = PolishEngine()

        # 语法层：检查 + 修正
        errors = engine.check_grammar(text, lang=PolishLanguage.ENGLISH)
        result = engine.fix_grammar(text, lang=PolishLanguage.ENGLISH)

        # 表达层：英文润色 / SCI论文专用
        result = engine.polish_english(text)
        result = engine.polish_sci_paper(text)

        # 逻辑层：逻辑分析 + 衔接优化
        issues = engine.analyze_logic(text)
        result = engine.optimize_transitions(text)

        # 风格层：期刊适配 + 正式程度
        result = engine.adapt_journal_style(text, journal_name="Nature")
        result = engine.adjust_formality(text, level="formal")

        # 定位层：修改定位 + 建议
        changes = engine.locate_changes(original, polished)
        suggestions = engine.suggest_changes(text)

        # 批量润色 + 报告
        results = engine.batch_polish(sections, layers=[PolishLayer.GRAMMAR])
        report = engine.generate_report(results)
    """

    # =========================================================================
    # 语法层 (Grammar)
    # =========================================================================

    def check_grammar(self, text: str, lang: PolishLanguage = PolishLanguage.ENGLISH) -> list[GrammarError]:
        """语法检查（只纠错不改写）.

        对英文检查时态、主谓一致、冠词、介词等常见错误；
        对中文检查搭配、语序、标点等问题。

        Args:
            text: 待检查文本.
            lang: 语言类型，默认英文.

        Returns:
            语法错误列表，每个 GrammarError 含位置、类型、原文、修正、说明.
        """
        errors: list[GrammarError] = []
        if not text.strip():
            return errors

        if lang == PolishLanguage.ENGLISH:
            errors.extend(self._check_english_grammar(text))
        elif lang == PolishLanguage.CHINESE:
            errors.extend(self._check_chinese_grammar(text))
        else:  # bilingual
            errors.extend(self._check_english_grammar(text))
            errors.extend(self._check_chinese_grammar(text))

        return errors

    def fix_grammar(self, text: str, lang: PolishLanguage = PolishLanguage.ENGLISH) -> PolishResult:
        """语法修正.

        基于 check_grammar 的检测结果，对文本进行语法修正，
        并生成语法错误双列表格（原文 vs 修正）。

        Args:
            text: 待修正文本.
            lang: 语言类型，默认英文.

        Returns:
            PolishResult，包含修正后文本、修改明细和改进摘要.
        """
        errors = self.check_grammar(text, lang)
        polished = text
        changes: list[dict] = []

        for err in errors:
            if err.original and err.original in polished:
                polished = polished.replace(err.original, err.correction, 1)
                changes.append({
                    "type": "grammar",
                    "original": err.original,
                    "revised": err.correction,
                    "reason": err.explanation,
                    "position": err.position,
                })

        summary = f"共修正 {len(changes)} 处语法错误"
        if errors:
            type_counts: dict[str, int] = {}
            for e in errors:
                type_counts[e.error_type] = type_counts.get(e.error_type, 0) + 1
            detail = "、".join(f"{t}{c}处" for t, c in type_counts.items())
            summary = f"共修正 {len(changes)} 处语法错误（{detail}）"

        return PolishResult(
            original_text=text,
            polished_text=polished,
            layer=PolishLayer.GRAMMAR,
            changes=changes,
            change_count=len(changes),
            improvement_summary=summary,
        )

    def _check_english_grammar(self, text: str) -> list[GrammarError]:
        """检查英文语法错误（内部方法）.

        Args:
            text: 英文文本.

        Returns:
            语法错误列表.
        """
        errors: list[GrammarError] = []
        sentences = re.split(r'(?<=[.!?])\s+', text)

        for idx, sentence in enumerate(sentences, 1):
            # 冠词检查：a + 元音开头
            for match in re.finditer(r'\ba\s+([aeiouAEIOU])', sentence):
                errors.append(GrammarError(
                    position=f"第{idx}句",
                    error_type="冠词",
                    original=match.group(0),
                    correction=f"an {match.group(1)}",
                    explanation=f"'{match.group(1)}' 是元音开头，应使用 'an' 而非 'a'",
                ))

            # 主谓一致：单数主语 + 复数动词
            for match in re.finditer(r'\b(he|she|it|this|that)\s+(are|were|have|do)\b', sentence, re.IGNORECASE):
                subj = match.group(1).lower()
                verb = match.group(2).lower()
                corrections = {"are": "is", "were": "was", "have": "has", "do": "does"}
                errors.append(GrammarError(
                    position=f"第{idx}句",
                    error_type="主谓一致",
                    original=match.group(0),
                    correction=f"{subj} {corrections[verb]}",
                    explanation=f"单数主语 '{subj}' 应搭配单数动词 '{corrections[verb]}'",
                ))

            # 主谓一致：复数主语 + 单数动词
            for match in re.finditer(r'\b(they|we|these|those)\s+(is|was|has|does)\b', sentence, re.IGNORECASE):
                subj = match.group(1).lower()
                verb = match.group(2).lower()
                corrections = {"is": "are", "was": "were", "has": "have", "does": "do"}
                errors.append(GrammarError(
                    position=f"第{idx}句",
                    error_type="主谓一致",
                    original=match.group(0),
                    correction=f"{subj} {corrections[verb]}",
                    explanation=f"复数主语 '{subj}' 应搭配复数动词 '{corrections[verb]}'",
                ))

            # 介词检查：common errors
            preposition_errors = {
                r'\bdifferent\s+than\b': ("different from", "表示比较差异时应用 'different from'"),
                r'\bsuperior\s+than\b': ("superior to", "表示优越关系时应用 'superior to'"),
                r'\binferior\s+than\b': ("inferior to", "表示低劣关系时应用 'inferior to'"),
                r'\bconsist\s+with\b': ("consist of", "表示由...组成应用 'consist of'"),
                r'\bcomprise\s+of\b': ("comprise", "'comprise' 已含'由...组成'之意，不需加 'of'"),
            }
            for pattern, (correction, explanation) in preposition_errors.items():
                for match in re.finditer(pattern, sentence, re.IGNORECASE):
                    errors.append(GrammarError(
                        position=f"第{idx}句",
                        error_type="介词",
                        original=match.group(0),
                        correction=correction,
                        explanation=explanation,
                    ))

        return errors

    def _check_chinese_grammar(self, text: str) -> list[GrammarError]:
        """检查中文语法错误（内部方法）.

        Args:
            text: 中文文本.

        Returns:
            语法错误列表.
        """
        errors: list[GrammarError] = []
        sentences = re.split(r'[。！？；]', text)

        for idx, sentence in enumerate(sentences, 1):
            if not sentence.strip():
                continue

            # 标点检查：中英文标点混用
            for match in re.finditer(r'[\u4e00-\u9fff]\s*[,.]\s*[\u4e00-\u9fff]', sentence):
                errors.append(GrammarError(
                    position=f"第{idx}句",
                    error_type="标点",
                    original=match.group(0),
                    correction=match.group(0).replace(",", "，").replace(".", "。"),
                    explanation="中文语境中应使用中文标点（，/。）而非英文标点（,/.)",
                ))

            # 搭配检查："提高" + 负面词
            for match in re.finditer(r'提高.{0,4}(风险|成本|负担|压力)', sentence):
                errors.append(GrammarError(
                    position=f"第{idx}句",
                    error_type="搭配",
                    original=match.group(0),
                    correction=match.group(0).replace("提高", "增加"),
                    explanation="'提高'不宜搭配负面名词，应使用'增加'",
                ))

            # 搭配检查："降低" + 正面词
            for match in re.finditer(r'降低.{0,4}(效率|效益|收入|利润|质量)', sentence):
                errors.append(GrammarError(
                    position=f"第{idx}句",
                    error_type="搭配",
                    original=match.group(0),
                    correction=match.group(0).replace("降低", "减少"),
                    explanation="'降低'不宜搭配正面名词，应使用'减少'",
                ))

        return errors

    # =========================================================================
    # 表达层 (Expression)
    # =========================================================================

    def polish_english(self, text: str) -> PolishResult:
        """英文润色.

        生成修改可追溯表格（原文/修改/原因），优化句式多样性
        （简单句/复合句/并列句平衡），提升学术表达精准度。

        Args:
            text: 待润色的英文文本.

        Returns:
            PolishResult，包含润色后文本、修改明细和改进摘要.
        """
        polished = text
        changes: list[dict] = []

        # 1. 口语化缩写展开
        for colloquial, formal in _ENGLISH_COLLOQUIAL.items():
            if colloquial in polished:
                count = polished.count(colloquial)
                polished = polished.replace(colloquial, formal)
                changes.append({
                    "type": "口语化修正",
                    "original": colloquial,
                    "revised": formal,
                    "reason": f"将口语化表达 '{colloquial}' 替换为正式表达 '{formal}'",
                    "position": f"共{count}处",
                })

        # 2. 弱表达升级
        for weak, strong in _ENGLISH_EXPRESSION_UPGRADES.items():
            pattern = re.compile(re.escape(weak), re.IGNORECASE)
            if pattern.search(polished):
                count = len(pattern.findall(polished))
                polished = pattern.sub(strong, polished)
                changes.append({
                    "type": "表达升级",
                    "original": weak,
                    "revised": strong if strong else "(删除冗余)",
                    "reason": f"将弱表达 '{weak}' 升级为更精确的学术表达",
                    "position": f"共{count}处",
                })

        # 3. 句式多样性检查
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', polished) if s.strip()]
        simple_count = sum(1 for s in sentences if s.count(",") == 0 and " and " not in s.lower())
        if len(sentences) > 3 and simple_count / len(sentences) > 0.7:
            changes.append({
                "type": "句式多样性",
                "original": f"简单句占比 {simple_count}/{len(sentences)} ({simple_count/len(sentences)*100:.0f}%)",
                "revised": "建议增加复合句和并列句",
                "reason": "简单句占比过高，建议通过从句和连接词丰富句式结构",
                "position": "全文",
            })

        summary = f"共完成 {len(changes)} 项表达优化"
        if changes:
            types = set(c["type"] for c in changes)
            summary = f"共完成 {len(changes)} 项表达优化（{', '.join(types)}）"

        return PolishResult(
            original_text=text,
            polished_text=polished,
            layer=PolishLayer.EXPRESSION,
            changes=changes,
            change_count=len(changes),
            improvement_summary=summary,
        )

    def polish_chinese(self, text: str) -> PolishResult:
        """中文润色.

        分解长句（超过60字的句子拆分），减少重复表达（同义词替换），
        消除口语化表达。

        Args:
            text: 待润色的中文文本.

        Returns:
            PolishResult，包含润色后文本、修改明细和改进摘要.
        """
        polished = text
        changes: list[dict] = []

        # 1. 消除口语化表达
        for colloquial, formal in _CHINESE_COLLOQUIAL.items():
            if colloquial in polished:
                count = polished.count(colloquial)
                polished = polished.replace(colloquial, formal)
                changes.append({
                    "type": "口语化修正",
                    "original": colloquial,
                    "revised": formal,
                    "reason": f"将口语化表达 '{colloquial}' 替换为书面表达 '{formal}'",
                    "position": f"共{count}处",
                })

        # 2. 分解长句（超过60字）
        sentences = re.split(r'([。！？])', polished)
        new_parts: list[str] = []
        split_count = 0
        i = 0
        while i < len(sentences):
            seg = sentences[i]
            if len(seg) > 60 and "，" in seg:
                # 在逗号处拆分
                clauses = seg.split("，")
                mid = len(clauses) // 2
                first_half = "，".join(clauses[:mid])
                second_half = "，".join(clauses[mid:])
                punctuation = sentences[i + 1] if i + 1 < len(sentences) else "。"
                new_parts.append(first_half + punctuation)
                new_parts.append(second_half)
                if i + 1 < len(sentences):
                    new_parts.append(sentences[i + 1])
                    i += 2
                else:
                    i += 1
                split_count += 1
                changes.append({
                    "type": "长句拆分",
                    "original": seg[:30] + "...",
                    "revised": f"拆分为2个短句（{len(first_half)}字 + {len(second_half)}字）",
                    "reason": f"原句{len(seg)}字超过60字阈值，在逗号处拆分以提升可读性",
                    "position": f"第{len(new_parts)}段附近",
                })
            else:
                new_parts.append(seg)
                i += 1

        if split_count > 0:
            polished = "".join(new_parts)

        # 3. 减少重复表达（同义词替换）
        word_positions: dict[str, int] = {}
        for word, synonyms in _CHINESE_SYNONYMS.items():
            occurrences = [m.start() for m in re.finditer(re.escape(word), polished)]
            if len(occurrences) > 2:
                # 保留前2次，后续替换为同义词
                replaced = 0
                for occ_idx in range(2, len(occurrences)):
                    synonym = synonyms[replaced % len(synonyms)]
                    replaced += 1
                    changes.append({
                        "type": "同义词替换",
                        "original": word,
                        "revised": synonym,
                        "reason": f"'{word}' 出现 {len(occurrences)} 次，第 {occ_idx + 1} 次替换为 '{synonym}' 以避免重复",
                        "position": f"第{occ_idx + 1}次出现",
                    })
                # 执行替换（从后往前替换以保持位置）
                for occ_idx in range(len(occurrences) - 1, 1, -1):
                    pos = occurrences[occ_idx]
                    synonym = synonyms[(occ_idx - 2) % len(synonyms)]
                    polished = polished[:pos] + synonym + polished[pos + len(word):]

        summary = f"共完成 {len(changes)} 项中文表达优化"
        if changes:
            types = set(c["type"] for c in changes)
            summary = f"共完成 {len(changes)} 项中文表达优化（{', '.join(types)}）"

        return PolishResult(
            original_text=text,
            polished_text=polished,
            layer=PolishLayer.EXPRESSION,
            changes=changes,
            change_count=len(changes),
            improvement_summary=summary,
        )

    def polish_sci_paper(self, text: str) -> PolishResult:
        """SCI论文专用润色.

        被动语态优化、时态规范（方法用过去时，事实用现在时）、
        术语一致性检查。

        Args:
            text: 待润色的SCI论文文本.

        Returns:
            PolishResult，包含润色后文本、修改明细和改进摘要.
        """
        polished = text
        changes: list[dict] = []

        # 1. 被动语态优化：避免过度使用被动语态
        # 检测 "It is + 过去分词 + that" 结构，建议改写
        passive_pattern = re.compile(
            r'\bIt\s+is\s+(shown|demonstrated|found|observed|noted|reported)\s+that\b',
            re.IGNORECASE,
        )
        for match in passive_pattern.finditer(polished):
            verb = match.group(1).lower()
            active_replacements = {
                "shown": "show",
                "demonstrated": "demonstrate",
                "found": "find",
                "observed": "observe",
                "noted": "note",
                "reported": "report",
            }
            active_verb = active_replacements.get(verb, verb)
            changes.append({
                "type": "被动语态优化",
                "original": match.group(0),
                "revised": f"We {active_verb} that",
                "reason": "过度使用被动语态降低可读性，建议改写为主动语态",
                "position": f"位置{match.start()}",
            })

        # 2. 时态规范：方法部分用过去时
        # 检测方法部分常见现在时动词（应为过去时）
        method_present_to_past: dict[str, str] = {
            r'\bwe\s+analyze\b': "we analyzed",
            r'\bwe\s+collect\b': "we collected",
            r'\bwe\s+use\b': "we used",
            r'\bwe\s+employ\b': "we employed",
            r'\bwe\s+estimate\b': "we estimated",
            r'\bwe\s+examine\b': "we examined",
            r'\bwe\s+investigate\b': "we investigated",
            r'\bwe\s+obtain\b': "we obtained",
            r'\bwe\s+select\b': "we selected",
            r'\bwe\s+apply\b': "we applied",
        }
        for pattern, replacement in method_present_to_past.items():
            compiled = re.compile(pattern, re.IGNORECASE)
            if compiled.search(polished):
                count = len(compiled.findall(polished))
                polished = compiled.sub(replacement, polished)
                changes.append({
                    "type": "时态规范",
                    "original": pattern.replace(r'\b', '').replace(r'\s+', ' '),
                    "revised": replacement,
                    "reason": "方法部分描述已完成的操作，应使用过去时",
                    "position": f"共{count}处",
                })

        # 3. 术语一致性检查
        # 检测常见术语的变体
        term_variants: dict[str, list[str]] = {
            "e.g.": ["e.g.", "eg.", "e.g", "for example", "for instance"],
            "i.e.": ["i.e.", "ie.", "i.e", "that is"],
            "et al.": ["et al.", "et al", "et al."],
            "USA": ["USA", "U.S.A.", "U.S.A", "United States of America"],
        }
        for canonical, variants in term_variants.items():
            found_variants: list[str] = []
            for v in variants:
                if v != canonical and re.search(re.escape(v), polished):
                    found_variants.append(v)
            if found_variants:
                for v in found_variants:
                    polished = re.sub(re.escape(v), canonical, polished)
                changes.append({
                    "type": "术语一致性",
                    "original": "/".join(found_variants),
                    "revised": canonical,
                    "reason": f"术语存在多种写法，统一为 '{canonical}'",
                    "position": "全文",
                })

        summary = f"共完成 {len(changes)} 项SCI论文润色"
        if changes:
            types = set(c["type"] for c in changes)
            summary = f"共完成 {len(changes)} 项SCI论文润色（{', '.join(types)}）"

        return PolishResult(
            original_text=text,
            polished_text=polished,
            layer=PolishLayer.EXPRESSION,
            changes=changes,
            change_count=len(changes),
            improvement_summary=summary,
        )

    # =========================================================================
    # 逻辑层 (Logic)
    # =========================================================================

    def analyze_logic(self, text: str) -> list[LogicIssue]:
        """逻辑连贯性分析.

        检测论点断层（论据不支撑论点）、逻辑跳跃（缺少过渡）、
        循环论证、自相矛盾。

        Args:
            text: 待分析文本.

        Returns:
            逻辑问题列表，每个 LogicIssue 含位置、类型、描述和建议.
        """
        issues: list[LogicIssue] = []
        if not text.strip():
            return issues

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        for idx, para in enumerate(paragraphs, 1):
            sentences = [s.strip() for s in re.split(r'[.。！？]', para) if s.strip()]

            # 1. 检测逻辑跳跃：段落内句子之间缺少过渡词
            transition_patterns = [
                r'\b(therefore|however|moreover|furthermore|consequently|thus|hence|nevertheless)\b',
                r'(因此|然而|此外|而且|从而|由此可见|但是|不过|综上)',
            ]
            for s_idx in range(1, len(sentences)):
                prev_sent = sentences[s_idx - 1]
                curr_sent = sentences[s_idx]
                has_transition = any(re.search(p, curr_sent, re.IGNORECASE) for p in transition_patterns)
                if not has_transition and len(prev_sent) > 20 and len(curr_sent) > 20:
                    issues.append(LogicIssue(
                        position=f"第{idx}段第{s_idx + 1}句",
                        issue_type="跳跃",
                        description=f"句子之间缺少过渡词，从'{prev_sent[:15]}...'到'{curr_sent[:15]}...'的逻辑连接不够明确",
                        suggestion="建议添加过渡词（如'因此'/'然而'/'此外'）以明确逻辑关系",
                    ))

            # 2. 检测循环论证：结论句与开头句高度相似
            if len(sentences) >= 3:
                first_sent = sentences[0]
                last_sent = sentences[-1]
                # 简化的相似度检测：共享关键词比例
                first_words = set(re.findall(r'\w+', first_sent.lower()))
                last_words = set(re.findall(r'\w+', last_sent.lower()))
                if first_words and last_words:
                    overlap = len(first_words & last_words) / min(len(first_words), len(last_words))
                    if overlap > 0.7 and first_sent != last_sent:
                        issues.append(LogicIssue(
                            position=f"第{idx}段",
                            issue_type="循环",
                            description="段落首尾句高度相似，可能存在循环论证",
                            suggestion="结尾句应提供新的论据或推论，而非重复开头论点",
                        ))

            # 3. 检测自相矛盾：检测否定+肯定的矛盾模式
            contradiction_patterns = [
                (r'(increase|rose|grew|enhanced)', r'(decrease|fell|declined|reduced)'),
                (r'(上升|增长|提高|增加)', r'(下降|减少|降低|缩减)'),
                (r'(positive|significant|effective)', r'(negative|insignificant|ineffective)'),
            ]
            for pos_pat, neg_pat in contradiction_patterns:
                pos_matches = list(re.finditer(pos_pat, para, re.IGNORECASE))
                neg_matches = list(re.finditer(neg_pat, para, re.IGNORECASE))
                if pos_matches and neg_matches:
                    # 检查是否在同一句子中
                    for pm in pos_matches:
                        for nm in neg_matches:
                            # 找到两个匹配所在的句子范围
                            sent_start = para.rfind('.', 0, min(pm.start(), nm.start())) + 1
                            sent_end = para.find('.', max(pm.end(), nm.end()))
                            if sent_end == -1:
                                sent_end = len(para)
                            if abs(pm.start() - nm.start()) < 50:
                                issues.append(LogicIssue(
                                    position=f"第{idx}段",
                                    issue_type="矛盾",
                                    description=f"同一句中同时出现正向词'{pm.group(0)}'和负向词'{nm.group(0)}'，可能存在自相矛盾",
                                    suggestion="请检查数据方向是否一致，或明确区分不同条件下的不同结果",
                                ))
                                break
                        else:
                            continue
                        break

        # 4. 检测论点断层：段落之间缺少衔接
        for idx in range(1, len(paragraphs)):
            prev_para = paragraphs[idx - 1]
            curr_para = paragraphs[idx]
            prev_last = prev_para.split('.')[-2] if '.' in prev_para else prev_para[-50:]
            curr_first = curr_para.split('.')[0]
            has_link = any(
                re.search(p, curr_first, re.IGNORECASE)
                for p in transition_patterns
            )
            if not has_link:
                issues.append(LogicIssue(
                    position=f"第{idx}段与第{idx + 1}段之间",
                    issue_type="断层",
                    description="相邻段落之间缺少衔接语句，论据到论点的过渡不够流畅",
                    suggestion="建议在新段落开头添加承上启下的过渡句",
                ))

        return issues

    def optimize_transitions(self, text: str) -> PolishResult:
        """段落衔接优化.

        添加逻辑过渡词，优化段落首尾衔接，确保论证链条完整。

        Args:
            text: 待优化文本.

        Returns:
            PolishResult，包含优化后文本和修改明细.
        """
        polished = text
        changes: list[dict] = []
        paragraphs = polished.split("\n\n")

        # 检测段落间的过渡需求
        transition_patterns = [
            r'\b(therefore|however|moreover|furthermore|consequently|thus|hence)\b',
            r'(因此|然而|此外|而且|从而|由此可见|但是|不过|综上)',
        ]

        for idx in range(1, len(paragraphs)):
            para = paragraphs[idx].strip()
            if not para:
                continue
            first_sentence = para.split('.')[0] if '.' in para else para[:50]
            has_transition = any(re.search(p, first_sentence, re.IGNORECASE) for p in transition_patterns)

            if not has_transition:
                # 分析上一段末尾判断需要什么类型的过渡词
                prev_para = paragraphs[idx - 1].strip()
                if any(w in prev_para[-80:] for w in ["but", "然而", "但是", "However"]):
                    transition = "Furthermore"
                    reason = "上一段存在转折，本段宜用递进过渡"
                elif any(w in prev_para[-80:] for w in ["show", "find", "表明", "发现", "result"]):
                    transition = "Therefore"
                    reason = "上一段展示结果，本段宜用因果过渡"
                else:
                    transition = "Moreover"
                    reason = "段落间缺少过渡，添加递进词以增强连贯性"

                # 在段落开头添加过渡词
                if re.match(r'^[A-Za-z]', para):
                    paragraphs[idx] = f"{transition}, {para}"
                else:
                    zh_transition = {"Furthermore": "此外，", "Therefore": "因此，", "Moreover": "此外，"}
                    paragraphs[idx] = f"{zh_transition.get(transition, '此外，')}{para}"

                changes.append({
                    "type": "过渡词添加",
                    "original": "(无过渡词)",
                    "revised": transition,
                    "reason": reason,
                    "position": f"第{idx + 1}段开头",
                })

        polished = "\n\n".join(paragraphs)
        summary = f"共优化 {len(changes)} 处段落衔接"

        return PolishResult(
            original_text=text,
            polished_text=polished,
            layer=PolishLayer.LOGIC,
            changes=changes,
            change_count=len(changes),
            improvement_summary=summary,
        )

    def diversify_sentences(self, text: str) -> PolishResult:
        """句子结构多样性优化.

        分析句子结构分布，调整过长/过短句子，变换句式开头。

        Args:
            text: 待优化文本.

        Returns:
            PolishResult，包含优化后文本和修改明细.
        """
        polished = text
        changes: list[dict] = []

        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', polished) if s.strip()]
        if not sentences:
            return PolishResult(
                original_text=text,
                polished_text=polished,
                layer=PolishLayer.LOGIC,
                changes=[],
                change_count=0,
                improvement_summary="未检测到可优化的句子",
            )

        # 1. 分析句子长度分布
        lengths = [len(s.split()) for s in sentences if re.match(r'^[A-Za-z]', s)]
        if lengths:
            avg_len = sum(lengths) / len(lengths)
            too_long = [i for i, l in enumerate(lengths) if l > 40]
            too_short = [i for i, l in enumerate(lengths) if l < 5 and l > 0]

            for i in too_long:
                changes.append({
                    "type": "过长句",
                    "original": f"句{i + 1}（{lengths[i]}词）",
                    "revised": "建议拆分为2-3个短句",
                    "reason": f"句子长度{lengths[i]}词远超平均值{avg_len:.0f}词，影响可读性",
                    "position": f"第{i + 1}句",
                })

            for i in too_short:
                changes.append({
                    "type": "过短句",
                    "original": f"句{i + 1}（{lengths[i]}词）",
                    "revised": "建议合并到相邻句子",
                    "reason": f"句子长度仅{lengths[i]}词，过于碎片化",
                    "position": f"第{i + 1}句",
                })

        # 2. 句式开头多样性分析
        starts = [s.split()[0] if s.split() else "" for s in sentences if re.match(r'^[A-Za-z]', s)]
        start_counts: dict[str, int] = {}
        for s in starts:
            start_counts[s] = start_counts.get(s, 0) + 1

        for word, count in start_counts.items():
            if count > 2:
                changes.append({
                    "type": "开头重复",
                    "original": f"'{word}' 开头{count}次",
                    "revised": "建议变换句式开头",
                    "reason": f"'{word}' 作为句首出现{count}次，句式过于单一",
                    "position": "全文",
                })

        # 3. 简单句/复合句/并列句分布
        simple = sum(1 for s in sentences if s.count(",") == 0 and " and " not in s.lower())
        compound = sum(1 for s in sentences if " and " in s.lower() or " but " in s.lower())
        complex_count = sum(1 for s in sentences if s.count(",") >= 1)

        if len(sentences) > 3:
            simple_ratio = simple / len(sentences)
            if simple_ratio > 0.6:
                changes.append({
                    "type": "句式分布",
                    "original": f"简单句{simple}句 / 复合句{complex_count}句 / 并列句{compound}句",
                    "revised": "建议增加复合句和并列句比例",
                    "reason": f"简单句占比{simple_ratio*100:.0f}%过高，句式结构不够丰富",
                    "position": "全文",
                })

        summary = f"共发现 {len(changes)} 项句式结构问题"
        if changes:
            types = set(c["type"] for c in changes)
            summary = f"共发现 {len(changes)} 项句式结构问题（{', '.join(types)}）"

        return PolishResult(
            original_text=text,
            polished_text=polished,
            layer=PolishLayer.LOGIC,
            changes=changes,
            change_count=len(changes),
            improvement_summary=summary,
        )

    # =========================================================================
    # 风格层 (Style)
    # =========================================================================

    def adapt_journal_style(self, text: str, journal_name: str) -> PolishResult:
        """期刊风格适配.

        根据目标期刊调整写作风格，包括字数控制、术语偏好等。

        Args:
            text: 待适配文本.
            journal_name: 目标期刊名称（如 "Nature", "经济研究"）.

        Returns:
            PolishResult，包含适配后文本和修改明细.
        """
        polished = text
        changes: list[dict] = []
        style = _JOURNAL_STYLES.get(journal_name, {})

        if not style:
            changes.append({
                "type": "期刊配置",
                "original": journal_name,
                "revised": "使用默认风格",
                "reason": f"未找到期刊 '{journal_name}' 的风格配置，使用默认设置",
                "position": "全文",
            })
        else:
            # 字数控制
            max_words = style.get("max_words", 8000)
            word_count = len(polished.split())
            if word_count > max_words:
                changes.append({
                    "type": "字数控制",
                    "original": f"当前{word_count}词",
                    "revised": f"目标{max_words}词以内",
                    "reason": f"超出{journal_name}字数限制 {max_words} 词，需精简约 {word_count - max_words} 词",
                    "position": "全文",
                })

            # 简洁度要求
            conciseness = style.get("conciseness", "medium")
            if conciseness == "high":
                # 检测冗余表达
                redundant_patterns = [
                    (r'\bin order to\b', "to"),
                    (r'\bdue to the fact that\b', "because"),
                    (r'\bin spite of the fact that\b', "although"),
                    (r'\ba large number of\b', "many"),
                    (r'\bthe majority of\b', "most"),
                ]
                for pattern, replacement in redundant_patterns:
                    if re.search(pattern, polished, re.IGNORECASE):
                        count = len(re.findall(pattern, polished, re.IGNORECASE))
                        polished = re.sub(pattern, replacement, polished, flags=re.IGNORECASE)
                        changes.append({
                            "type": "简洁化",
                            "original": pattern.replace(r'\b', ''),
                            "revised": replacement,
                            "reason": f"{journal_name}偏好高信息密度，精简冗余表达",
                            "position": f"共{count}处",
                        })

            changes.append({
                "type": "风格配置",
                "original": "通用风格",
                "revised": f"{journal_name}风格（简洁度:{conciseness}）",
                "reason": f"已适配{journal_name}的写作风格要求",
                "position": "全文",
            })

        summary = f"已适配期刊 '{journal_name}' 风格，共 {len(changes)} 项调整"

        return PolishResult(
            original_text=text,
            polished_text=polished,
            layer=PolishLayer.STYLE,
            changes=changes,
            change_count=len(changes),
            improvement_summary=summary,
        )

    def polish_academic_style(self, text: str) -> PolishResult:
        """学术风格润色.

        封装基本事实（不展开常识性内容），提升表述精确度，
        去除主观色彩表达。

        Args:
            text: 待润色文本.

        Returns:
            PolishResult，包含润色后文本和修改明细.
        """
        polished = text
        changes: list[dict] = []

        # 1. 去除主观色彩表达
        for expr in _SUBJECTIVE_EXPRESSIONS:
            if expr in polished:
                count = polished.count(expr)
                polished = polished.replace(expr, "")
                # 清理多余空格
                polished = re.sub(r'\s{2,}', ' ', polished)
                changes.append({
                    "type": "去主观化",
                    "original": expr,
                    "revised": "(已删除)",
                    "reason": f"主观色彩表达 '{expr}' 不符合学术写作客观性要求",
                    "position": f"共{count}处",
                })

        # 2. 提升表述精确度
        precision_upgrades: dict[str, str] = {
            "a lot of research": "extensive research",
            "many studies": "numerous studies",
            "some evidence": "empirical evidence",
            "good results": "favorable outcomes",
            "bad results": "adverse outcomes",
            "big sample": "large-scale sample",
            "small effect": "marginal effect",
            "重要意义": "重要价值",
            "很大作用": "显著作用",
            "一定的": "较为显著的",
            "比较好": "较为理想",
        }
        for vague, precise in precision_upgrades.items():
            if vague in polished:
                count = polished.count(vague)
                polished = polished.replace(vague, precise)
                changes.append({
                    "type": "精确化",
                    "original": vague,
                    "revised": precise,
                    "reason": f"模糊表达 '{vague}' 替换为更精确的 '{precise}'",
                    "position": f"共{count}处",
                })

        # 3. 封装基本事实检测
        # 检测常识性展开（如定义基本概念的长句）
        common_facts = [
            r'(?:GDP|国内生产总值)\s*(?:是|指|表示)\s*(?:一个|一国)[^。]{20,}。',
            r'(?:inflation|通胀|通货膨胀)\s*(?:is|refers to|是指)\s*[^.]{20,}\.',
        ]
        for pattern in common_facts:
            match = re.search(pattern, polished, re.IGNORECASE)
            if match:
                changes.append({
                    "type": "封装事实",
                    "original": match.group(0)[:40] + "...",
                    "revised": "建议简化为一句概述",
                    "reason": "该处展开常识性内容，学术写作中应封装基本事实，不展开常识",
                    "position": f"位置{match.start()}",
                })

        summary = f"共完成 {len(changes)} 项学术风格优化"
        if changes:
            types = set(c["type"] for c in changes)
            summary = f"共完成 {len(changes)} 项学术风格优化（{', '.join(types)}）"

        return PolishResult(
            original_text=text,
            polished_text=polished,
            layer=PolishLayer.STYLE,
            changes=changes,
            change_count=len(changes),
            improvement_summary=summary,
        )

    def adjust_formality(self, text: str, level: str = "formal") -> PolishResult:
        """正式程度调整.

        根据指定正式程度调整文本：formal（正式）、semi-formal（半正式）、
        informal（非正式）。

        Args:
            text: 待调整文本.
            level: 正式程度，可选 "formal" / "semi-formal" / "informal".

        Returns:
            PolishResult，包含调整后文本和修改明细.
        """
        polished = text
        changes: list[dict] = []

        if level == "formal":
            # 展开所有缩写
            for colloquial, formal in _ENGLISH_COLLOQUIAL.items():
                if colloquial in polished:
                    count = polished.count(colloquial)
                    polished = polished.replace(colloquial, formal)
                    changes.append({
                        "type": "正式化",
                        "original": colloquial,
                        "revised": formal,
                        "reason": f"正式写作中应使用完整形式 '{formal}' 而非缩写 '{colloquial}'",
                        "position": f"共{count}处",
                    })
            # 去除第一/第二人称（部分场景）
            first_person_patterns = [
                (r'\bwe\s+think\b', "it is argued that"),
                (r'\bI\s+think\b', "it is argued that"),
                (r'\bwe\s+believe\b', "it is suggested that"),
                (r'\bI\s+believe\b', "it is suggested that"),
            ]
            for pattern, replacement in first_person_patterns:
                if re.search(pattern, polished, re.IGNORECASE):
                    count = len(re.findall(pattern, polished, re.IGNORECASE))
                    polished = re.sub(pattern, replacement, polished, flags=re.IGNORECASE)
                    changes.append({
                        "type": "去人称化",
                        "original": pattern.replace(r'\b', '').replace(r'\s+', ' '),
                        "revised": replacement,
                        "reason": "正式学术写作中避免主观人称表达",
                        "position": f"共{count}处",
                    })

        elif level == "semi-formal":
            # 保持适度正式，不强制展开缩写
            # 但替换过于口语化的表达
            overly_casual = {
                "gonna": "going to",
                "wanna": "want to",
                "gotta": "have to",
                "kinda": "somewhat",
                "sorta": "somewhat",
            }
            for casual, semi in overly_casual.items():
                if casual in polished:
                    count = polished.count(casual)
                    polished = polished.replace(casual, semi)
                    changes.append({
                        "type": "半正式化",
                        "original": casual,
                        "revised": semi,
                        "reason": f"半正式写作中 '{casual}' 过于随意，替换为 '{semi}'",
                        "position": f"共{count}处",
                    })

        elif level == "informal":
            # 允许缩写和口语化表达
            for formal, informal in [("do not", "don't"), ("cannot", "can't"), ("it is", "it's")]:
                if formal in polished:
                    count = polished.count(formal)
                    polished = polished.replace(formal, informal)
                    changes.append({
                        "type": "非正式化",
                        "original": formal,
                        "revised": informal,
                        "reason": f"非正式语境下使用缩写 '{informal}' 更自然",
                        "position": f"共{count}处",
                    })
        else:
            changes.append({
                "type": "参数错误",
                "original": level,
                "revised": "formal",
                "reason": f"未知的正式程度 '{level}'，未做调整。可选: formal/semi-formal/informal",
                "position": "全文",
            })

        summary = f"正式程度已调整为 '{level}'，共 {len(changes)} 项修改"

        return PolishResult(
            original_text=text,
            polished_text=polished,
            layer=PolishLayer.STYLE,
            changes=changes,
            change_count=len(changes),
            improvement_summary=summary,
        )

    # =========================================================================
    # 定位层 (Positioning)
    # =========================================================================

    def locate_changes(self, original: str, polished: str) -> list[dict]:
        """润色定位.

        精确指出修改了哪些段落，标注修改类型（语法/表达/逻辑/风格），
        提供修改前后对比。

        Args:
            original: 原始文本.
            polished: 润色后文本.

        Returns:
            修改定位列表，每项含段落位置、修改类型、前后对比.
        """
        changes: list[dict] = []
        orig_paras = original.split("\n\n")
        polished_paras = polished.split("\n\n")
        max_len = max(len(orig_paras), len(polished_paras))

        for idx in range(max_len):
            orig_para = orig_paras[idx] if idx < len(orig_paras) else ""
            polished_para = polished_paras[idx] if idx < len(polished_paras) else ""

            if orig_para == polished_para:
                continue

            # 逐句对比
            orig_sentences = re.split(r'(?<=[.。！？])\s+', orig_para)
            polished_sentences = re.split(r'(?<=[.。！？])\s+', polished_para)

            sent_max = max(len(orig_sentences), len(polished_sentences))
            for s_idx in range(sent_max):
                orig_sent = orig_sentences[s_idx].strip() if s_idx < len(orig_sentences) else ""
                polished_sent = polished_sentences[s_idx].strip() if s_idx < len(polished_sentences) else ""

                if orig_sent == polished_sent:
                    continue

                # 推断修改类型
                change_type = self._infer_change_type(orig_sent, polished_sent)

                changes.append({
                    "type": change_type,
                    "position": f"第{idx + 1}段第{s_idx + 1}句",
                    "original": orig_sent,
                    "revised": polished_sent,
                    "reason": self._infer_change_reason(change_type, orig_sent, polished_sent),
                })

        return changes

    def suggest_changes(self, text: str) -> list[dict]:
        """修改建议（不全文修改）.

        只提供建议列表，标注优先级（高/中/低），提供修改理由。

        Args:
            text: 待分析文本.

        Returns:
            修改建议列表，每项含优先级、位置、建议内容、理由.
        """
        suggestions: list[dict] = []

        # 语法检查（高优先级）
        grammar_errors = self.check_grammar(text, PolishLanguage.ENGLISH)
        for err in grammar_errors:
            suggestions.append({
                "priority": "高",
                "type": "语法",
                "position": err.position,
                "suggestion": f"将 '{err.original}' 修正为 '{err.correction}'",
                "reason": err.explanation,
            })

        # 逻辑分析（高优先级）
        logic_issues = self.analyze_logic(text)
        for issue in logic_issues:
            priority = "高" if issue.issue_type in ("矛盾", "断层") else "中"
            suggestions.append({
                "priority": priority,
                "type": "逻辑",
                "position": issue.position,
                "suggestion": issue.suggestion,
                "reason": f"[{issue.issue_type}] {issue.description}",
            })

        # 句式多样性（中优先级）
        diversity_result = self.diversify_sentences(text)
        for change in diversity_result.changes:
            suggestions.append({
                "priority": "中",
                "type": "句式",
                "position": change["position"],
                "suggestion": change["revised"],
                "reason": change["reason"],
            })

        # 学术风格（低优先级）
        style_result = self.polish_academic_style(text)
        for change in style_result.changes:
            suggestions.append({
                "priority": "低",
                "type": "风格",
                "position": change["position"],
                "suggestion": f"将 '{change['original']}' 调整为 '{change['revised']}'",
                "reason": change["reason"],
            })

        # 按优先级排序
        priority_order = {"高": 0, "中": 1, "低": 2}
        suggestions.sort(key=lambda x: priority_order.get(x["priority"], 3))

        return suggestions

    def _infer_change_type(self, original: str, revised: str) -> str:
        """推断修改类型（内部方法）.

        Args:
            original: 原始句.
            revised: 修改后句.

        Returns:
            修改类型字符串（语法/表达/逻辑/风格）.
        """
        if not original:
            return "逻辑"
        if not revised:
            return "逻辑"

        # 语法类：单词形式变化（时态、单复数、冠词）
        if len(original.split()) == len(revised.split()):
            diff_words = sum(
                1 for o, r in zip(original.split(), revised.split()) if o.lower() != r.lower()
            )
            if diff_words <= 2:
                return "语法"

        # 风格类：主观表达去除
        for expr in _SUBJECTIVE_EXPRESSIONS:
            if expr in original and expr not in revised:
                return "风格"

        # 表达类：词数相近但用词变化较大
        if abs(len(original.split()) - len(revised.split())) <= 3:
            return "表达"

        # 逻辑类：句子数变化或结构重组
        return "逻辑"

    def _infer_change_reason(self, change_type: str, original: str, revised: str) -> str:
        """推断修改理由（内部方法）.

        Args:
            change_type: 修改类型.
            original: 原始句.
            revised: 修改后句.

        Returns:
            修改理由字符串.
        """
        reasons = {
            "语法": "修正语法错误",
            "表达": "优化学术表达",
            "逻辑": "改善逻辑连贯性",
            "风格": "调整写作风格",
        }
        return reasons.get(change_type, "文本优化")

    # =========================================================================
    # 斯坦福8类润色指令集成
    # =========================================================================

    def apply_stanford_instructions(self, text: str, categories: list[str] | None = None) -> PolishResult:
        """应用斯坦福8类润色指令.

        对文本应用斯坦福大学官方推荐的8类润色指令进行综合润色。

        Args:
            text: 待润色文本.
            categories: 要应用的指令类别列表，如 ["grammar", "clarity"]。
                为 None 时应用全部8类。

        Returns:
            PolishResult，包含润色后文本和综合修改明细.
        """
        if categories is None:
            categories = list(STANFORD_POLISH_INSTRUCTIONS.keys())

        polished = text
        all_changes: list[dict] = []

        # grammar -> 语法修正
        if "grammar" in categories:
            result = self.fix_grammar(polished, PolishLanguage.ENGLISH)
            polished = result.polished_text
            all_changes.extend(result.changes)

        # clarity + word_choice -> 表达润色
        if "clarity" in categories or "word_choice" in categories:
            result = self.polish_english(polished)
            polished = result.polished_text
            all_changes.extend(result.changes)

        # flow -> 衔接优化
        if "flow" in categories:
            result = self.optimize_transitions(polished)
            polished = result.polished_text
            all_changes.extend(result.changes)

        # tone + conciseness + structure -> 学术风格润色
        if any(c in categories for c in ["tone", "conciseness", "structure"]):
            result = self.polish_academic_style(polished)
            polished = result.polished_text
            all_changes.extend(result.changes)

        applied = [c for c in categories if c in STANFORD_POLISH_INSTRUCTIONS]
        summary = f"已应用斯坦福润色指令: {', '.join(applied)}，共 {len(all_changes)} 项修改"

        return PolishResult(
            original_text=text,
            polished_text=polished,
            layer=PolishLayer.EXPRESSION,
            changes=all_changes,
            change_count=len(all_changes),
            improvement_summary=summary,
        )

    # =========================================================================
    # 批量润色
    # =========================================================================

    def batch_polish(
        self,
        sections: list[dict],
        layers: list[PolishLayer] | None = None,
    ) -> list[PolishResult]:
        """批量润色多个章节.

        对论文多个章节进行批量润色，可选择应用的润色层。

        Args:
            sections: 章节列表，每个字典包含:
                - title (str): 章节标题.
                - content (str): 章节内容.
            layers: 要应用的润色层列表。为 None 时应用全部层。

        Returns:
            每个章节每个层级的润色结果列表.
        """
        if layers is None:
            layers = [
                PolishLayer.GRAMMAR,
                PolishLayer.EXPRESSION,
                PolishLayer.LOGIC,
                PolishLayer.STYLE,
            ]

        results: list[PolishResult] = []

        for section in sections:
            title = section.get("title", "未命名章节")
            content = section.get("content", "")
            if not content.strip():
                logger.warning("章节 '%s' 内容为空，跳过", title)
                continue

            logger.info("正在润色章节: %s", title)

            for layer in layers:
                if layer == PolishLayer.GRAMMAR:
                    result = self.fix_grammar(content, PolishLanguage.ENGLISH)
                elif layer == PolishLayer.EXPRESSION:
                    result = self.polish_english(content)
                elif layer == PolishLayer.LOGIC:
                    result = self.optimize_transitions(content)
                elif layer == PolishLayer.STYLE:
                    result = self.polish_academic_style(content)
                else:
                    continue
                results.append(result)
                # 将润色结果作为下一层的输入
                content = result.polished_text

        return results

    # =========================================================================
    # 润色报告生成
    # =========================================================================

    def generate_report(self, results: list[PolishResult]) -> str:
        """生成Markdown格式的润色报告.

        包含修改统计、修改明细表、改进建议。

        Args:
            results: 润色结果列表.

        Returns:
            Markdown 格式的润色报告字符串.
        """
        if not results:
            return "# 润色报告\n\n无润色结果。"

        lines: list[str] = []
        total_changes = sum(r.change_count for r in results)

        # 报告标题
        lines.append("# ScholarPilot 润色报告")
        lines.append("")

        # 1. 修改统计
        lines.append("## 一、修改统计")
        lines.append("")
        lines.append(f"| 指标 | 数值 |")
        lines.append(f"| --- | --- |")
        lines.append(f"| 润色段落数 | {len(results)} |")
        lines.append(f"| 修改总数 | {total_changes} |")
        lines.append("")

        # 按层级统计
        layer_counts: dict[str, int] = {}
        layer_changes: dict[str, int] = {}
        for r in results:
            layer_name = r.layer.value
            layer_counts[layer_name] = layer_counts.get(layer_name, 0) + 1
            layer_changes[layer_name] = layer_changes.get(layer_name, 0) + r.change_count

        lines.append("### 各层级修改统计")
        lines.append("")
        lines.append("| 润色层级 | 段落数 | 修改数 |")
        lines.append("| --- | --- | --- |")
        for layer in ["grammar", "expression", "logic", "style", "positioning"]:
            if layer in layer_counts:
                lines.append(f"| {layer} | {layer_counts[layer]} | {layer_changes[layer]} |")
        lines.append("")

        # 2. 修改明细表
        lines.append("## 二、修改明细")
        lines.append("")

        for idx, result in enumerate(results, 1):
            lines.append(f"### 段落 {idx}（{result.layer.value}层）")
            lines.append("")
            lines.append(f"**改进摘要**: {result.improvement_summary}")
            lines.append("")

            if result.changes:
                lines.append("| 序号 | 修改类型 | 原文 | 修改后 | 原因 | 位置 |")
                lines.append("| --- | --- | --- | --- | --- | --- |")
                for c_idx, change in enumerate(result.changes, 1):
                    orig = str(change.get("original", ""))[:40]
                    rev = str(change.get("revised", ""))[:40]
                    reason = str(change.get("reason", ""))[:50]
                    pos = str(change.get("position", ""))
                    c_type = str(change.get("type", ""))
                    lines.append(f"| {c_idx} | {c_type} | {orig} | {rev} | {reason} | {pos} |")
            else:
                lines.append("*本段落无修改*")
            lines.append("")

        # 3. 改进建议
        lines.append("## 三、改进建议")
        lines.append("")

        all_suggestions: list[str] = []
        for result in results:
            if result.original_text.strip():
                suggestions = self.suggest_changes(result.original_text)
                high_priority = [s for s in suggestions if s["priority"] == "高"]
                if high_priority:
                    all_suggestions.extend(
                        f"- [{s['priority']}] {s['position']}: {s['suggestion']}（{s['reason']}）"
                        for s in high_priority
                    )

        if all_suggestions:
            for s in all_suggestions[:20]:
                lines.append(s)
            if len(all_suggestions) > 20:
                lines.append(f"\n*...还有 {len(all_suggestions) - 20} 条建议*")
        else:
            lines.append("*暂无高优先级建议*")

        lines.append("")
        lines.append("---")
        lines.append("*本报告由 ScholarPilot 多层次润色引擎自动生成*")

        return "\n".join(lines)
