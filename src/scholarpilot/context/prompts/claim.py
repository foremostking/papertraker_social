"""Claim 校准相关 Prompt — 用于 Phase 8c Claim 校准.

包含两个核心 Prompt：
1. CLAIM_EXTRACTION_PROMPT — 从章节文本提取核心结论句
2. CLAIM_CALIBRATION_PROMPT — 校准结论与证据的匹配关系
"""

from __future__ import annotations

# ===== Claim 提取 Prompt =====

CLAIM_EXTRACTION_PROMPT = """## 任务：提取需要证据支撑的核心结论句

### 章节标题
{section_title}

### 章节正文
{section_text}

### 请提取需要证据支撑的核心结论句

**只提取以下类型的结论句（每章最多5条，宁缺毋滥）：**

1. 包含因果推断的实质性结论（"A导致B""A促进B""A抑制B"等）
2. 引用文献支撑的 empirical 发现（"研究表明…""现有文献发现…"）
3. 包含明确数据支撑的发现（"回归结果显示…""实证结果表明…"）
4. 理论假设或命题的提出（"假设1：…"）

**不要提取以下内容：**
- 方法论描述（"本文采用面板固定效应模型""数据来源于CSMAR"）
- 结构性过渡句（"本章接下来分析…""如表X所示"）
- 纯描述性统计（"样本量为5000家""均值为0.35"）
- 政策建议（政策建议不需要引用支撑）
- 研究展望和未来方向

请以JSON数组格式输出：

```json
[
  {{
    "text": "结论句原文",
    "claim_type": "causal|correlational|descriptive|normative|methodological",
    "citations": ["引用的作者（年份）"]
  }}
]
```

### 结论类型判断标准
- causal（因果性）：声称A导致B，含因果动词（导致、促进、抑制、引起）
- correlational（相关性）：声称A与B相关，含相关动词（相关、关联、协同）
- descriptive（描述性）：描述现象或数据特征，无推断
- normative（规范性）：价值判断或政策建议（应该、需要、建议）
- methodological（方法论）：关于研究方法的结论

### 注意事项
- 每章最多提取5条最重要的结论
- citations 需从结论句及上下文中提取引用的作者和年份
- 如果结论句无引用，citations 设为空数组
- 只提取有实质学术价值的结论，不提取常识性陈述
"""

# ===== Claim 校准 Prompt =====

CLAIM_CALIBRATION_PROMPT = """## 任务：校准结论与证据的匹配关系

### 结论句
{claim_text}

### 结论类型
{claim_type}

### 该结论所在章节全文（用于上下文）
{section_context}

### 引用的参考文献详情
{references_detail}

### 证据矩阵中的相关论点-证据映射（如有）
{evidence_mapping}

### 请判断结论是否有充分证据支撑

请以JSON格式输出：

```json
{{
  "support_status": "supported|overreach|unsupported|partial",
  "issue_type": "overreach|unsupported|partial_support|mismatch|exaggeration|null",
  "evidence_basis": "证据基础描述（说明判断依据）",
  "recommendation": "修改建议（如需修改）"
}}
```

### 判断标准
- **supported**：结论有充分引用支撑且证据强度与结论类型匹配
- **overreach**：数据/证据只支撑相关性，但结论表述为因果性（最常见的越界）
- **unsupported**：结论无任何引用支撑
- **partial**：引用存在但证据强度不足以完全支撑结论

### issue_type 对应关系
- overreach → 结论越界（相关性→因果性）
- unsupported → 无引用支撑
- partial_support → 部分支撑
- mismatch → 图文/数据不匹配
- exaggeration → 夸大表述
- null → 无问题（supported时）

### 关键判断规则
1. 因果性结论（causal）必须有因果识别策略支撑（如IV、DID、RD、自然实验）
2. 如果研究仅做了OLS回归，结论不得使用"导致""促进"等因果性表述
3. 描述性统计不得推出因果性结论
4. 规范性结论需要基于实证证据，不能凭空建议
"""
