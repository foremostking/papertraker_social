"""证据矩阵相关 Prompt — 用于 Phase 2.5 证据矩阵构建.

包含两个核心 Prompt：
1. EVIDENCE_EXTRACTION_PROMPT — 从文献摘要提取结构化证据
2. EVIDENCE_ARGUMENT_MAPPING_PROMPT — 为章节生成论点-证据映射
"""

from __future__ import annotations

# ===== 证据提取 Prompt =====

EVIDENCE_EXTRACTION_PROMPT = """## 任务：从文献中提取结构化证据

### 论文主题
{topic}

### 文献信息
- 标题：{title}
- 作者：{authors}
- 年份：{year}
- 来源：{source}
- 摘要：{abstract}

### 请为该文献提取以下信息

请以JSON格式输出：

```json
{{
  "key_findings": ["关键发现1（1-2句）", "关键发现2"],
  "evidence_type": "empirical|theoretical|case|review|descriptive",
  "evidence_strength": "strong|moderate|weak|unverified",
  "usable_arguments": ["可支撑的论点1", "可支撑的论点2"]
}}
```

### 证据类型判断标准
- empirical（实证）：包含回归分析、实验、问卷调查、面板数据等实证方法
- theoretical（理论）：以理论模型构建、数学推导、机制分析为主
- case（案例）：聚焦单个或少数案例的深度分析
- review（综述）：系统梳理、评述已有文献的综述/元分析
- descriptive（描述性）：仅提供描述性统计，无因果推断

### 证据强度判断标准（保守策略）
- strong：有DOI+权威期刊+大样本（N>500）实证研究
- moderate：同行评议但样本有限（N<500）或方法有局限
- weak：预印本/小样本/推断性/案例研究
- unverified：信息不足，无法判断
- 宁可标记为weak也不标strong

### 注意事项
- key_findings 必须基于文献摘要内容，不得编造
- usable_arguments 是该文献可以支撑的学术论点（与论文主题相关）
- 如果摘要信息不足以判断，evidence_strength 设为 unverified
"""

# ===== 论点-证据映射 Prompt =====

EVIDENCE_ARGUMENT_MAPPING_PROMPT = """## 任务：为章节生成论点-证据映射

### 章节标题
{section_title}

### 章节关键点
{key_points}

### 可用文献证据池
{evidence_pool}

### 请生成本章论点-证据映射

请以JSON格式输出：

```json
{{
  "key_arguments": ["本章需要论证的核心论点1", "核心论点2", "核心论点3"],
  "evidence_entries": [
    {{
      "argument": "论点1",
      "paper_ids": ["paper_1", "paper_3"],
      "evidence_summary": "综合这些文献的证据摘要",
      "support_direction": "support|contradict|partial",
      "gap_flag": false
    }},
    {{
      "argument": "论点2（无直接证据）",
      "paper_ids": [],
      "evidence_summary": "暂无直接支撑文献",
      "support_direction": "partial",
      "gap_flag": true
    }}
  ]
}}
```

### 映射规则
- 每个论点至少映射到1篇文献，若无可用的则 gap_flag=true
- support_direction：support=直接支撑，contradict=反驳，partial=部分支撑
- evidence_summary 需综合该论点下所有文献的关键发现
- key_arguments 数量建议 3-5 个，覆盖章节核心论证逻辑
- 论点需与章节关键点紧密相关，不得偏离主题
"""
