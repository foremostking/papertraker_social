"""Prompt 模板库 — 按 10 阶段分类的模块化 Prompt 管理.

原有 13 个核心 Prompt 常量定义在 core.py，可通过 `from scholarpilot.context.prompts import XXX` 访问。
新增 150+ 条 Prompt 模板按阶段分类存放。

ADR-007 P4：原 prompts.py（兼容性 shim）已删除，legacy.py 已重命名为 core.py。

阶段划分：
  1. system    — 系统提示词
  2. topic     — 选题阶段
  3. search    — 文献检索阶段
  4. review    — 文献综述阶段
  5. spec      — 规格生成阶段
  6. outline   — 大纲生成阶段
  7. writing   — 章节撰写阶段
  8. polish    — 润色阶段
  9. de_ai     — 去AI味阶段
  10. submission — 投稿阶段
  11. defense  — 答辩阶段
  12. extended — 补充Prompt
"""

from __future__ import annotations

# ===== 向后兼容：重新导出原有 13 个 Prompt =====
from scholarpilot.context.prompts.core import (
    SCHOLAR_SYSTEM_PROMPT,
    TOPIC_ANALYSIS_PROMPT,
    SPEC_GENERATION_PROMPT,
    OUTLINE_GENERATION_PROMPT,
    SECTION_WRITING_PROMPT,
    REVIEW_WRITING_PROMPT,
    ABSTRACT_GENERATION_PROMPT,
    DATA_COLLECTION_PROMPT,
    HUMAN_REVIEW_PROMPT,
    PLAN_GENERATION_PROMPT,
    PARAGRAPH_EDIT_PROMPT,
    REVIEW_ANALYSIS_PROMPT,
    REVIEW_RESPONSE_PROMPT,
)

# ===== 新增 Prompt 模板 =====

# 选题阶段
from scholarpilot.context.prompts.topic import (
    TOPIC_REFINEMENT_PROMPT,
    TOPIC_FEASIBILITY_PROMPT,
    TOPIC_INNOVATION_PROMPT,
)

# 文献检索阶段
from scholarpilot.context.prompts.search import (
    SEARCH_STRATEGY_PROMPT,
    KEYWORD_DECOMPOSITION_PROMPT,
    LITERATURE_SCREENING_PROMPT,
    KEYWORD_TRANSLATION_PROMPT,
    SYNONYM_EXPANSION_PROMPT,
)

# 文献综述阶段
from scholarpilot.context.prompts.review import (
    DEEPSEEK_FIVE_STEP_PROMPT,
    NOTEBOOKLM_FIVE_STEP_PROMPT,
    GEMINI_FIVE_STEP_PROMPT,
    CHATGPT_REVIEW_PARAGRAPH_PROMPT,
    REVIEW_QUALITY_CHECK_PROMPT,
)

# 润色阶段
from scholarpilot.context.prompts.polish import (
    GRAMMAR_CHECK_PROMPT,
    ENGLISH_POLISH_PROMPT,
    CHINESE_POLISH_PROMPT,
    SCI_POLISH_PROMPT,
    STANFORD_POLISH_PROMPT,
    LOGIC_ANALYSIS_PROMPT,
    TRANSITION_OPTIMIZATION_PROMPT,
)

# 去AI味阶段
from scholarpilot.context.prompts.de_ai import (
    AI_PATTERN_DETECTION_PROMPT,
    GEMINI_DE_AI_PROMPT,
    GPT55_DE_AI_PROMPT,
    PARAPHRASE_PROMPT,
    ANTI_FABRICATE_PROMPT,
)

# 投稿阶段
from scholarpilot.context.prompts.submission import (
    JOURNAL_RECOMMENDATION_PROMPT,
    COVER_LETTER_PROMPT,
    REVISION_PLAN_PROMPT,
)

# 答辩阶段
from scholarpilot.context.prompts.defense import (
    DEFENSE_SLIDES_PROMPT,
    DEFENSE_QA_PROMPT,
)

# 补充Prompt
from scholarpilot.context.prompts.extended import (
    RESEARCH_HYPOTHESIS_PROMPT,
    ACADEMIC_DEBATE_PROMPT,
    RESEARCH_TIMELINE_PROMPT,
    METHODOLOGY_DESIGN_PROMPT,
    VARIABLE_DEFINITION_PROMPT,
    ROBUSTNESS_CHECK_PROMPT,
)

# 阶段化角色卡
from scholarpilot.context.prompts.roles import (
    PHASE_ROLES,
    get_role_prompt,
    RETRIEVAL_EXPERT_ROLE,
    EVIDENCE_ANALYST_ROLE,
    RESEARCH_DESIGNER_ROLE,
    ACADEMIC_WRITER_ROLE,
    CITATION_CURATOR_ROLE,
    DEAI_EDITOR_ROLE,
    REVIEWER_ROLE,
)

# 证据矩阵 Prompt
from scholarpilot.context.prompts.evidence import (
    EVIDENCE_EXTRACTION_PROMPT,
    EVIDENCE_ARGUMENT_MAPPING_PROMPT,
)

# Claim校准 Prompt
from scholarpilot.context.prompts.claim import (
    CLAIM_EXTRACTION_PROMPT,
    CLAIM_CALIBRATION_PROMPT,
    RELEVANCE_SCORING_PROMPT,
    CLAIM_OVERREACH_CONFIRM_PROMPT,
)

__all__ = [
    # 原有 13 个
    "SCHOLAR_SYSTEM_PROMPT",
    "TOPIC_ANALYSIS_PROMPT",
    "SPEC_GENERATION_PROMPT",
    "OUTLINE_GENERATION_PROMPT",
    "SECTION_WRITING_PROMPT",
    "REVIEW_WRITING_PROMPT",
    "ABSTRACT_GENERATION_PROMPT",
    "DATA_COLLECTION_PROMPT",
    "HUMAN_REVIEW_PROMPT",
    "PLAN_GENERATION_PROMPT",
    "PARAGRAPH_EDIT_PROMPT",
    "REVIEW_ANALYSIS_PROMPT",
    "REVIEW_RESPONSE_PROMPT",
    # 选题阶段新增
    "TOPIC_REFINEMENT_PROMPT",
    "TOPIC_FEASIBILITY_PROMPT",
    "TOPIC_INNOVATION_PROMPT",
    # 文献检索阶段新增
    "SEARCH_STRATEGY_PROMPT",
    "KEYWORD_DECOMPOSITION_PROMPT",
    "LITERATURE_SCREENING_PROMPT",
    "KEYWORD_TRANSLATION_PROMPT",
    "SYNONYM_EXPANSION_PROMPT",
    # 文献综述阶段新增
    "DEEPSEEK_FIVE_STEP_PROMPT",
    "NOTEBOOKLM_FIVE_STEP_PROMPT",
    "GEMINI_FIVE_STEP_PROMPT",
    "CHATGPT_REVIEW_PARAGRAPH_PROMPT",
    "REVIEW_QUALITY_CHECK_PROMPT",
    # 润色阶段新增
    "GRAMMAR_CHECK_PROMPT",
    "ENGLISH_POLISH_PROMPT",
    "CHINESE_POLISH_PROMPT",
    "SCI_POLISH_PROMPT",
    "STANFORD_POLISH_PROMPT",
    "LOGIC_ANALYSIS_PROMPT",
    "TRANSITION_OPTIMIZATION_PROMPT",
    # 去AI味阶段新增
    "AI_PATTERN_DETECTION_PROMPT",
    "GEMINI_DE_AI_PROMPT",
    "GPT55_DE_AI_PROMPT",
    "PARAPHRASE_PROMPT",
    "ANTI_FABRICATE_PROMPT",
    # 投稿阶段新增
    "JOURNAL_RECOMMENDATION_PROMPT",
    "COVER_LETTER_PROMPT",
    "REVISION_PLAN_PROMPT",
    # 答辩阶段新增
    "DEFENSE_SLIDES_PROMPT",
    "DEFENSE_QA_PROMPT",
    # 补充Prompt
    "RESEARCH_HYPOTHESIS_PROMPT",
    "ACADEMIC_DEBATE_PROMPT",
    "RESEARCH_TIMELINE_PROMPT",
    "METHODOLOGY_DESIGN_PROMPT",
    "VARIABLE_DEFINITION_PROMPT",
    "ROBUSTNESS_CHECK_PROMPT",
    # 阶段化角色卡
    "PHASE_ROLES",
    "get_role_prompt",
    "RETRIEVAL_EXPERT_ROLE",
    "EVIDENCE_ANALYST_ROLE",
    "RESEARCH_DESIGNER_ROLE",
    "ACADEMIC_WRITER_ROLE",
    "CITATION_CURATOR_ROLE",
    "DEAI_EDITOR_ROLE",
    "REVIEWER_ROLE",
    # 证据矩阵 Prompt
    "EVIDENCE_EXTRACTION_PROMPT",
    "EVIDENCE_ARGUMENT_MAPPING_PROMPT",
    # Claim校准 Prompt
    "CLAIM_EXTRACTION_PROMPT",
    "CLAIM_CALIBRATION_PROMPT",
    "RELEVANCE_SCORING_PROMPT",
    "CLAIM_OVERREACH_CONFIRM_PROMPT",
]
