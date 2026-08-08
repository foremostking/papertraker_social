"""共享 Prompt 常量 —— 学术引用规则与核心约束.

所有阶段共用的数值与文本块，避免在多个 prompt 模板中重复硬编码。
修改引用篇数、半衰期等参数时只需改此文件。

ADR-007 P4：消除"学术引用半衰期/CSSCI 篇数"在 8+ 处的重复。
"""

from __future__ import annotations

# ===== 核心数值常量 =====

CITATION_HALF_LIFE = "4-5"       # 学术引用半衰期（年）
RECENT_YEARS_WINDOW = "5-7"      # 中文核心期刊要求近 N 年文献为主
RECENT_3YR_RATIO = "50-60%"      # 近 3 年最新文献占比
CLASSIC_RATIO = "20-30%"         # 经典文献占比
CSSCI_REF_RANGE = "25-45"        # CSSCI 论文参考文献篇数
SSCI_REF_RANGE = "30-60"         # SSCI 论文参考文献篇数
SEARCH_BATCH_SIZE = "50"         # 每次检索至少返回篇数
CANDIDATE_POOL_SIZE = "50-100"   # 候选池目标篇数


# ===== 标准文本块（f-string 在导入时求值为普通 str，可安全拼入 .format() 模板）=====

CITATION_RULES_BLOCK = f"""## 文献引用规则（重要）
- **时效性**：学术引用半衰期约{CITATION_HALF_LIFE}年，中文核心期刊要求以近 {RECENT_YEARS_WINDOW} 年文献为主
- **引用量**：CSSCI 论文需 {CSSCI_REF_RANGE} 篇参考文献，SSCI 论文需 {SSCI_REF_RANGE} 篇
- **结构**：近 3 年最新文献 {RECENT_3YR_RATIO}，经典文献 {CLASSIC_RATIO}，其余为补充文献
- **检索量**：每次检索至少返回 {SEARCH_BATCH_SIZE} 篇，建立足够候选池"""


SHARED_CONSTRAINTS_BLOCK = f"""
## 学术诚信红线（适用于所有阶段）
- 不容忍任何AI编造的文献、数据、DOI、PMID、作者、年份或机制关系
- 引用必须真实存在且可验证，禁止编造文献
- 实证章节必须添加醒目占位符标记以区分AI生成模板与真实数据
- 结论不得超出证据支撑范围（相关性不等于因果性）

## 文献引用规则（适用于所有阶段）
- 时效性：学术引用半衰期约{CITATION_HALF_LIFE}年，中文核心期刊要求以近{RECENT_YEARS_WINDOW}年文献为主
- 引用量：CSSCI论文需{CSSCI_REF_RANGE}篇参考文献，SSCI论文需{SSCI_REF_RANGE}篇
- 结构：近3年最新文献{RECENT_3YR_RATIO}，经典文献{CLASSIC_RATIO}，其余为补充文献
- 检索量：每次检索至少返回{SEARCH_BATCH_SIZE}篇，建立足够候选池

## 工作方式
- 直接操作项目目录中的文件，所有产出都是真实文件
- 在关键决策点暂停等待用户确认
- 所有操作都会记录在项目记忆中
"""


SPEC_REF_STRATEGY = f"""   - 目标引用量：CSSCI 论文 {CSSCI_REF_RANGE} 篇，SSCI 论文 {SSCI_REF_RANGE} 篇
   - 时效性要求：学术引用半衰期{CITATION_HALF_LIFE}年，70% 以上引用应为近 {RECENT_YEARS_WINDOW} 年文献
   - 需检索至少 {CANDIDATE_POOL_SIZE} 篇文献作为候选池"""


REVIEW_CITATION_RULES = f"""文献引用规则：
- 学术引用半衰期约{CITATION_HALF_LIFE}年，近5年文献应占{RECENT_3YR_RATIO}
- 引用列表中的每篇文献至少被提及一次
- 优先引用CSSCI/SSCI核心期刊和被引频次高的文献"""


# 检索量规划块（用于 SEARCH_STRATEGY_PROMPT）
SEARCH_VOLUME_RULES = f"""- 经济学引用半衰期约4.2年，近5年文献应占{RECENT_3YR_RATIO}
- CSSCI论文需{CSSCI_REF_RANGE}篇参考文献，SSCI论文需{SSCI_REF_RANGE}篇
- 每源检索至少{SEARCH_BATCH_SIZE}篇，建立足够候选池（检索量:引用量 ≈ 2:1）"""


# 筛选目标块（用于 LITERATURE_SCREENING_PROMPT）
SCREENING_REF_TARGETS = f"""- CSSCI论文：{CSSCI_REF_RANGE}篇
- SSCI论文：{SSCI_REF_RANGE}篇
- 近5年文献占比：{RECENT_3YR_RATIO}
- 经典文献占比：{CLASSIC_RATIO}"""
