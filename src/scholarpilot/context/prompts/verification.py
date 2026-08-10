"""角色自动校验 Prompt 模板 — Actor-Critic 双层架构.

每个阶段的 Actor 角色生成产出后，由不同职责的 Critic 角色自动校验。
校验结果以结构化 JSON 返回，包含评分、问题列表和决策建议。

Actor-Critic 映射表：
  policy_search      → Actor: 政策分析  → Critic: 研究设计师
  topic_analysis     → Actor: 检索专家  → Critic: 审稿人
  literature_search  → Actor: 检索专家  → Critic: 证据分析师
  evidence_matrix    → Actor: 证据分析师 → Critic: 审稿人
  spec_generation    → Actor: 研究设计师 → Critic: 审稿人
  outline            → Actor: 研究设计师 → Critic: 审稿人
  section_writing    → Actor: 学术作者   → Critic: 审稿人

决策分级：
  score >= 80  → "pass"  自动通过
  score 50-79  → "fix"   自动修复后继续
  score < 50   → "human" 升级人工审核
"""

from __future__ import annotations

# ===== 通用校验输出格式 =====

_VERIFICATION_OUTPUT_FORMAT = """
请以 JSON 格式输出校验结果，不要输出其他内容：
```json
{{
  "score": 0-100的整数,
  "decision": "pass" | "fix" | "human",
  "issues": [
    {{
      "severity": "critical" | "warning" | "info",
      "location": "问题位置描述",
      "description": "问题描述",
      "suggestion": "修改建议"
    }}
  ],
  "summary": "一句话总结校验结论"
}}
```

决策标准：
- score >= 80 且无 critical issues → "pass"
- score 50-79 或有 critical issues 但可自动修复 → "fix"
- score < 50 或存在无法自动修复的 critical issues → "human"
"""

# ===== Phase 0.5: 政策调研校验（Critic: 研究设计师）=====

POLICY_SEARCH_VERIFICATION_PROMPT = """## 任务：校验政策背景调研质量

你是一名研究设计师，需要校验政策调研阶段产出的质量。

### 用户研究想法
{user_input}

### 政策调研产出
{content}

### 校验维度（逐项检查并评分）

1. **政策相关性**（30分）：列出的政策法规是否与用户研究选题直接相关？是否有明显不相关的政策混入？
2. **政策演进脉络**（25分）：政策变迁时间线是否清晰？关键转折点是否标注？演进逻辑是否合理？
3. **社会问题提炼**（25分）：提炼的社会问题是否基于政策现状？问题是否具有现实意义？是否过度泛泛而谈？
4. **政策缺口分析**（20分）：是否明确指出现有政策的不足？缺口是否能转化为学术研究问题？
5. **格式规范**：是否有AI生成痕迹（如"请确认""需要告知"等交互式语句）？是否为陈述句结尾？

### 扣分规则
- 政策与选题不相关：每条扣5分
- 政策演进脉络缺失或混乱：扣10-15分
- 社会问题过于空泛：扣5-10分
- 政策缺口分析缺失：扣10分
- 含AI交互痕迹：扣20分并标记为 critical

""" + _VERIFICATION_OUTPUT_FORMAT


# ===== Phase 1: 选题分析校验（Critic: 审稿人）=====

TOPIC_ANALYSIS_VERIFICATION_PROMPT = """## 任务：校验选题分析质量

你是一名匿名审稿人，需要校验选题分析阶段产出的质量。

### 选题分析产出
{content}

### 校验维度（逐项检查并评分）

1. **选题清晰度**（25分）：核心主题、研究区域、研究内容是否明确？是否存在概念模糊？
2. **研究类型判断**（25分）：empirical/theoretical/case_study/review 的判断是否准确？判定理由是否充分？
   - 关键校验：如果输入含"实证""检验""效应""数据"等词，应判为 empirical
   - 如果仅涉及"理论""机制""框架"而无数据检验，应判为 theoretical
3. **时间范围合理性**（20分）：文献检索时间范围是否为近5-7年？起始年是否合理？
4. **学科领域准确性**（15分）：学科领域判断是否与选题内容匹配？
5. **可行性分析**（15分）：8维统计分析是否完整？竞争程度判断是否合理？

### 扣分规则
- 研究类型判断错误：扣25分并标记为 critical
- 选题概念模糊不清：扣10-15分
- 时间范围不合理（如超过10年或不足3年）：扣10分
- 8维统计缺失：扣10分

""" + _VERIFICATION_OUTPUT_FORMAT


# ===== Phase 2: 文献检索校验（Critic: 证据分析师）=====

LITERATURE_SEARCH_VERIFICATION_PROMPT = """## 任务：校验文献检索质量

你是一名证据分析师，需要校验文献检索阶段产出的质量。

### 文献检索产出
{content}

### 校验维度（逐项检查并评分）

1. **文献覆盖度**（30分）：
   - 中英文文献是否都有覆盖？
   - 文献数量是否达到候选池目标（50-100篇）？
   - 是否覆盖了核心期刊文献？
2. **文献相关性**（25分）：
   - 检索到的文献是否与选题高度相关？
   - 是否有明显不相关的文献混入？
3. **来源多样性**（20分）：
   - 中文来源是否包含CNKI和NCPSSD？
   - 英文来源是否包含Semantic Scholar和arXiv？
   - 是否过度依赖单一来源？
4. **时间分布**（15分）：
   - 近3年文献占比是否达到50-60%？
   - 经典文献占比是否在20-30%？
5. **格式规范**（10分）：
   - 文献信息是否完整（标题、作者、年份、来源）？
   - 是否有AI生成痕迹？

### 扣分规则
- 文献数量不足30篇：扣15分
- 缺少中文或英文文献：扣15分并标记为 critical
- 近3年文献占比低于30%：扣10分
- 无核心期刊文献：扣10分

""" + _VERIFICATION_OUTPUT_FORMAT


# ===== Phase 2.5: 证据矩阵校验（Critic: 审稿人）=====

EVIDENCE_MATRIX_VERIFICATION_PROMPT = """## 任务：校验证据矩阵质量

你是一名匿名审稿人，需要校验证据矩阵构建阶段产出的质量。

### 证据矩阵产出
{content}

### 校验维度（逐项检查并评分）

1. **证据提取完整性**（30分）：
   - 是否从文献中提取了关键发现（key_findings）？
   - 证据类型判断（实证/理论/案例/综述/描述性）是否准确？
2. **证据强度评估**（25分）：
   - STRONG/MODERATE/WEAK/UNVERIFIED 判断是否符合标准？
   - 是否存在过度乐观的强度评估（如预印本标为STRONG）？
3. **论点-证据映射**（25分）：
   - 是否建立了论点与证据的映射关系？
   - 是否识别了证据缺口（gap_flag）？
4. **证据覆盖面**（20分）：
   - 是否覆盖了不同观点和方法的文献？
   - 是否存在明显的证据盲区？

### 扣分规则
- 证据强度评估明显不合理：每处扣5分
- 论点-证据映射缺失：扣15分并标记为 critical
- 证据提取遗漏关键文献：扣10分

""" + _VERIFICATION_OUTPUT_FORMAT


# ===== Phase 3: 规格生成校验（Critic: 审稿人）=====

SPEC_GENERATION_VERIFICATION_PROMPT = """## 任务：校验论文规格文档质量

你是一名匿名审稿人，需要校验论文规格文档（SPEC.md）的质量。

### 论文规格产出
{content}

### 校验维度（逐项检查并评分）

1. **研究问题清晰度**（25分）：
   - 核心研究问题是否1-3个且明确具体？
   - 研究问题是否可操作化（能转化为实证检验或理论分析）？
2. **研究设计严谨性**（25分）：
   - 实证论文：变量设计是否完整（被解释/核心解释/控制变量）？模型设定是否合理？
   - 理论论文：理论框架是否清晰？逻辑推演路径是否完整？
   - 案例论文：案例选择逻辑是否充分？
3. **创新点可行性**（20分）：
   - 创新点是否具体而非空泛？
   - 创新点是否基于已有文献的不足？
4. **目标期刊匹配度**（15分）：
   - 推荐期刊是否与选题学科匹配？
   - 期刊层次是否合理（不过高也不过低）？
5. **格式规范**（15分）：
   - 是否有AI交互痕迹？
   - 实证论文是否包含数据需求和变量设计？

### 扣分规则
- 研究问题模糊不可操作：扣15分并标记为 critical
- 实证论文缺少变量设计：扣15分
- 创新点空泛（如"填补空白"）：扣10分
- 含AI交互痕迹：扣15分

""" + _VERIFICATION_OUTPUT_FORMAT


# ===== Phase 5: 大纲校验（Critic: 审稿人）=====

OUTLINE_VERIFICATION_PROMPT = """## 任务：校验论文大纲质量

你是一名匿名审稿人，需要校验论文大纲的质量。

### 论文大纲产出
{content}

### 校验维度（逐项检查并评分）

1. **结构完整性**（25分）：
   - 是否包含5-7个主章节？
   - 每章是否有2-4个小节？
   - 章节是否覆盖了从引言到结论的完整逻辑链？
2. **逻辑递进性**（25分）：
   - 章节顺序是否符合学术论证逻辑？
   - 实证论文：引言→文献综述→研究设计→实证结果→结论？
   - 前后章节是否有逻辑衔接？
3. **内容覆盖度**（20分）：
   - 每章的核心内容要点是否明确？
   - 是否有遗漏的关键章节（如稳健性检验、政策建议）？
4. **字数分配**（15分）：
   - 各章预计字数是否合理？
   - 实证章节字数占比是否适当？
5. **类型匹配**（15分）：
   - 大纲结构是否与论文类型（empirical/theoretical/case_study/review）匹配？
   - 理论论文是否避免了"实证结果"等不适用章节？

### 扣分规则
- 章节数量不足5章或超过8章：扣10分
- 逻辑顺序混乱：扣15分并标记为 critical
- 论文类型与结构不匹配：扣15分
- 缺少关键章节：扣10分

""" + _VERIFICATION_OUTPUT_FORMAT


# ===== Phase 7: 章节撰写校验（Critic: 审稿人）=====

SECTION_WRITING_VERIFICATION_PROMPT = """## 任务：校验论文章节撰写质量

你是一名匿名审稿人，需要校验逐章撰写阶段产出的质量。

### 章节撰写产出
{content}

### 校验维度（逐项检查并评分）

1. **引用规范性**（25分）：
   - 每个论点是否有对应引用支撑？
   - 引用格式是否规范（作者（年份）或 Author (Year)）？
   - 是否存在编造引用的嫌疑？
   - 中文文献占比是否不低于40%？
2. **学术严谨性**（25分）：
   - 结论强度是否超出证据强度（overreach）？
   - 因果性结论是否有因果识别策略支撑？
   - 描述性统计是否推出因果性结论？
3. **内容连贯性**（20分）：
   - 章节间是否有逻辑衔接？
   - 段落间过渡是否自然？
   - 是否存在重复论述？
4. **实证数据规范**（15分）：
   - 实证章节是否有数据占位符标记？
   - 是否使用了真实统计数据（如有）？
   - 数据来源是否标注？
5. **语言规范**（15分）：
   - 是否使用规范学术语言？
   - 是否有AI写作痕迹（过度对仗、套路化过渡词）？
   - 是否有口语化表达？

### 扣分规则
- 存在overreach（结论越界）：每处扣5分并标记为 critical
- 引用编造嫌疑：扣20分并标记为 critical
- 实证章节无数据占位符：扣10分
- 中文文献占比低于40%：扣10分
- AI写作痕迹明显：扣10分

""" + _VERIFICATION_OUTPUT_FORMAT


# ===== 校验 Prompt 映射表 =====

VERIFICATION_PROMPTS = {
    "policy_search": POLICY_SEARCH_VERIFICATION_PROMPT,
    "topic_analysis": TOPIC_ANALYSIS_VERIFICATION_PROMPT,
    "literature_search": LITERATURE_SEARCH_VERIFICATION_PROMPT,
    "evidence_matrix": EVIDENCE_MATRIX_VERIFICATION_PROMPT,
    "spec_generation": SPEC_GENERATION_VERIFICATION_PROMPT,
    "outline": OUTLINE_VERIFICATION_PROMPT,
    "section_writing": SECTION_WRITING_VERIFICATION_PROMPT,
}

# ===== Actor-Critic 角色映射表 =====

ACTOR_CRITIC_MAP = {
    "policy_search": {
        "actor": "policy_analyst",
        "critic": "research_designer",
        "critic_role_key": "spec_generation",  # PHASE_ROLES 中的 key
        "critic_name": "研究设计师",
    },
    "topic_analysis": {
        "actor": "retrieval_expert",
        "critic": "reviewer",
        "critic_role_key": "claim_calibration",
        "critic_name": "审稿人",
    },
    "literature_search": {
        "actor": "retrieval_expert",
        "critic": "evidence_analyst",
        "critic_role_key": "evidence_matrix",
        "critic_name": "证据分析师",
    },
    "evidence_matrix": {
        "actor": "evidence_analyst",
        "critic": "reviewer",
        "critic_role_key": "claim_calibration",
        "critic_name": "审稿人",
    },
    "spec_generation": {
        "actor": "research_designer",
        "critic": "reviewer",
        "critic_role_key": "claim_calibration",
        "critic_name": "审稿人",
    },
    "outline": {
        "actor": "research_designer",
        "critic": "reviewer",
        "critic_role_key": "claim_calibration",
        "critic_name": "审稿人",
    },
    "section_writing": {
        "actor": "academic_writer",
        "critic": "reviewer",
        "critic_role_key": "claim_calibration",
        "critic_name": "审稿人",
    },
}
