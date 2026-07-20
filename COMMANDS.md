# ScholarPilot 命令速查表

33 个 CLI 命令，按用户旅程组织。

## 0. 入门

### `init` — 首次使用引导

```bash
scholarpilot init
```

**P7-2 新增**。交互式 3 步配置，约 2 分钟完成：

1. **选择 LLM 提供商** — 智谱 GLM-4 / 火山方舟 / Claude / OpenAI / DeepSeek
2. **输入 API Key** — 自动写入 `.env`，检测已有配置避免覆盖
3. **确认默认模型** — 写作/分析/轻量三阶段模型（可选推荐配置或自定义）
4. **（可选）Semantic Scholar API Key** — 避免英文文献检索限流

完成后显示下一步指引（创建项目 → 查看模板 → 开始生成）。

### `examples` — 查看示例模板

```bash
scholarpilot examples              # 查看所有模板
scholarpilot examples --list       # 仅列出名称
```

**P7-3 新增**。8 个示例模板，按 6 个学科分类：

| 学科 | 模板 ID | 标题 |
|------|---------|------|
| 金融学 | `finance-governance` | 数字金融对公司治理的影响研究 |
| 金融学 | `finance-green` | 绿色金融政策对企业绿色创新的影响 |
| 宏观经济学 | `macro-fiscal` | 财政分权对地方政府债务规模的影响 |
| 宏观经济学 | `macro-monetary` | 货币政策传导渠道的有效性比较研究 |
| 微观经济学 | `micro-innovation` | 企业数字化转型对劳动收入份额的影响 |
| 产业经济学 | `industry-digital` | 数字经济发展对产业结构升级的影响 |
| 区域经济学 | `region-urban` | 新型城镇化对城乡收入差距的影响 |
| 国际贸易 | `trade-rcep` | RCEP生效对中国制造业出口结构的影响 |

每个模板包含：研究类型、期刊级别、数据来源、详细研究主题描述。

---

## 1. 核心流程

### `new` — 创建论文项目

```bash
scholarpilot new <项目名>
scholarpilot new <项目名> --template <模板ID>    # 从模板创建
scholarpilot new <项目名> --title "标题" --journal "期刊"
```

创建新的论文项目目录，初始化 `.scholar/` 状态文件。

**选项:**
- `--template` 从示例模板创建（使用 `scholarpilot examples` 查看可用模板），自动预填标题、研究类型、研究主题描述
- `--title` 预设论文标题
- `--journal` 预设目标期刊

### `chat` — 交互式对话

```bash
scholarpilot chat -p <项目名> "研究主题描述"
scholarpilot chat -p <项目名> "继续"          # 断点续写
```

全流程自动化入口。LLM 解析研究想法，自动执行 8 阶段流程（选题→检索→规格→大纲→写作→引用验证→去AI味→导出）。

**选项:**
- `-p, --project` 项目名称（必填）
- `--no-interactive` 非交互模式，自动跳过人工审核

### `status` — 查看项目状态

```bash
scholarpilot status <项目名>
```

显示项目元信息、当前阶段、已完成章节。

### `progress` — 撰写进度

```bash
scholarpilot progress <项目名>
```

显示逐章撰写进度，支持断点续写定位。

### `dashboard` — 项目仪表盘

```bash
scholarpilot dashboard <项目名>
```

**P5-1 新增**。一站式项目总览，包含：
- 基本信息（标题、研究类型、状态）
- 阶段进度（8 阶段完成情况）
- 质量指标（文献数、引用验证率、字数、去AI味风险）
- 文件清单（规格/草稿/章节/文献/数据/导出/投稿）
- 投稿状态
- 下一步建议

### `list` — 列出所有项目

```bash
scholarpilot list
```

### `edit` — 段落级编辑

```bash
scholarpilot edit <项目名> --section <章节> --paragraph <段号>
```

交互式编辑指定段落，LLM 辅助润色。

### `versions` — 版本管理

```bash
scholarpilot versions <项目名>
scholarpilot versions <项目名> --diff <版本1> <版本2>
```

章节版本对比与回滚。

---

## 2. 质量保障

### `check-ai` — AI 写作检测

```bash
scholarpilot check-ai <项目名>
```

**P3-3 新增**。检测 10 类 AI 写作模式：
1. 过度对仗排比
2. 套路化过渡词
3. 句式单一性
4. 过度精确表述
5. 缺乏人称视角
6. 机械三段式结构
7. 过度被动语态
8. 列举项数量偏好
9. 缺乏口语化学术表达
10. 逻辑连接词过度使用

输出风险等级（低/中/高）+ 问题句子 + 修改建议，保存至 `analysis/ai_detection_report.md`。

### `quality` — 论文质量检查

```bash
scholarpilot quality <项目名>
```

检查论文结构完整性、引用规范、格式一致性。

### `review` — 人工审核

```bash
scholarpilot review <项目名>
```

交互式人工审核流程，支持逐章批注。

---

## 3. 数据分析

### `stats` — 描述性统计

```bash
scholarpilot stats <项目名> --data <数据文件>
```

生成描述性统计表（均值/标准差/最小值/最大值/观测数）。

### `diagnose` — 计量诊断

```bash
scholarpilot diagnose <项目名> --data <数据文件> --y <因变量> --x <自变量>
```

VIF 多重共线性检验、Hausman 检验、异方差检验、内生性检验。

### `mechanism` — 机制分析

```bash
scholarpilot mechanism <项目名> --mediator <中介变量>
scholarpilot mechanism <项目名> --moderator <调节变量>
```

中介效应（逐步回归 + Sobel + Bootstrap）和调节效应分析。

### `tables` — 表格模板

```bash
scholarpilot tables <项目名>
```

生成实证表格模板（描述性统计表/相关系数表/基准回归表/稳健性检验表）。

### `plot` — 科研绘图

```bash
scholarpilot plot <项目名> --type <图表类型>
```

支持散点图、折线图、柱状图、热力图、分布图等。

### `parse-result` — 回归结果解析

```bash
scholarpilot parse-result <项目名> --file <结果文件> --format <stata|r|python|json>
```

**P2-1 新增**。解析 Stata/R/Python/JSON 格式的回归输出，提取系数、标准误、p 值、R² 等结构化数据。

### `preprocess` — 数据预处理

```bash
scholarpilot preprocess <项目名> --data <数据文件>
```

缺失值处理、异常值检测、变量标准化、面板数据平衡。

### `code` — 代码生成

```bash
scholarpilot code <项目名> --lang <stata|r|python> --model <模型类型>
```

**P2-3 新增**。生成计量代码模板，支持 OLS/FE/RE/IV/GMM/空间计量等模型，多语言输出。

---

## 4. 导出打包

### `export` — 格式导出

```bash
scholarpilot export <项目名> -f docx
scholarpilot export <项目名> -f pdf
scholarpilot export <项目名> -f latex
scholarpilot export <项目名> -f md
```

支持 Word (.docx) / PDF / LaTeX / Markdown 四种格式。PDF 导出需安装 docx2pdf 或 LibreOffice。

### `finalize` — 定稿处理

```bash
scholarpilot finalize <项目名>
```

合并所有章节为完整草稿，生成最终版本。

### `package` — 可复现性打包

```bash
scholarpilot package <项目名>
```

**P2-2 新增**。打包项目为可复现研究包，包含：
- 数据溯源记录（ProvenanceTracker）
- 代码版本快照
- 环境依赖清单
- 复现说明文档

---

## 5. 投稿支持

### `recommend-journal` — 期刊推荐

```bash
scholarpilot recommend-journal <项目名>
scholarpilot recommend-journal <项目名> --level CSSCI --time "不急" --paid "可以接受"
```

**P4-1 新增**。基于论文信息推荐 5-8 本期刊，按冲刺/匹配/保底三级策略排列。

**选项:**
- `--level` 期望级别（CSSCI/SSCI/SCI/北大核心/普通）
- `--time` 时效要求（如"6个月内见刊""不急"）
- `--paid` 是否接受收费期刊
- `--other` 其他偏好

输出包含每本期刊的：影响因子、收录情况、审稿周期、录用率、版面费、匹配度评分、风险提示、投稿建议。报告保存至 `submission/journal_recommendation.md`。

### `cover-letter` — Cover Letter 生成

```bash
scholarpilot cover-letter <项目名> --journal "经济研究"
scholarpilot cover-letter <项目名> --journal "American Economic Review" --language 英文
```

**P4-2 新增**。生成 4 段式 Cover Letter：
1. 投稿声明与研究背景
2. 研究贡献（3-4 点）
3. 与期刊匹配度
4. 声明（原创性/利益冲突/伦理）

**选项:**
- `--journal` 目标期刊名称（必填）
- `--author` 通讯作者姓名
- `--email` 通讯作者邮箱
- `--affiliation` 作者单位
- `--language` 语言（中文/英文，默认中文）

文件保存至 `submission/cover_letter_<期刊名>.md`。

### `revision-plan` — 审稿回复计划

```bash
scholarpilot revision-plan <项目名> --reviews "审稿意见文本"
scholarpilot revision-plan <项目名> --reviews-file reviews.txt --deadline "30天"
```

**P4-2 新增**。逐条分析审稿意见，生成详细修改计划。每条意见包含 9 个要素：
- 意见编号（R1-1, R2-3 等）
- 意见摘要
- 分类（major/minor/question + content/method/data/...）
- 修改方案（操作层面）
- 修改位置（章节+段落）
- 预计工作量（时间+字数变化）
- 优先级（P0/P1/P2/P3）
- 依赖关系
- 风险评估
- 回复策略

输出还包含：执行顺序、工作量汇总、全局策略。报告保存至 `submission/revision_plan.md`。

### `datasource` — 数据源指引

```bash
scholarpilot datasource <项目名>
```

**P4-3 新增**。从 SPEC.md 提取所有变量，匹配到合适的数据源：

| 数据源 | 类型 | 覆盖范围 |
|--------|------|----------|
| CSMAR | 金融经济 | A股/基金/债券/宏观 |
| Wind | 金融经济 | 全市场金融数据 |
| RESSET | 金融经济 | 学术研究专用 |
| CNRDS | 多学科 | 中国研究数据服务平台 |
| NBS | 宏观经济 | 国家统计局 |
| MOF | 财政 | 财政部 |
| CCER | 金融经济 | 色诺芬数据库 |

输出包含：变量清单、数据源推荐、CSV 数据模板、数据质量要求。保存至 `data_collection_guide.md`。

---

## 6. 体验增强

### `literature-matrix` — 文献笔记矩阵

```bash
scholarpilot literature-matrix <项目名>
scholarpilot literature-matrix <项目名> --enrich    # LLM 增强版
```

**P5-2 新增**。从参考文献生成结构化文献表。

**基础版：** 解析 `references.md` 或 `references.bib`，生成文献概览表（序号/作者/年份/标题/期刊/语言）。

**增强版 (`--enrich`)：** 使用 LLM 为每条文献补充：
- 研究主题（10 字内）
- 主要发现（20 字内）
- 与本文关系（15 字内，如"提供理论基础""方法借鉴""对比分析"）

生成详细文献笔记，适合答辩准备、组会汇报。保存至 `literature/literature_matrix.md`。

### `model-config` — 多模型配置

```bash
scholarpilot model-config --show
scholarpilot model-config --writing glm-4
scholarpilot model-config --writing glm-4 --analysis gpt-4o --casual deepseek-chat
```

**P5-3 新增**。查看和设置各阶段使用的模型。

**显示模式 (`--show`)：**
- 当前模型配置（写作/分析/轻量）
- API Key 状态（各提供商配置情况）
- 阶段-模型映射表（11 个阶段各用哪个模型）
- 模型选择建议

**修改模式：**
- `--writing` 写作模型
- `--analysis` 分析模型
- `--casual` 轻量模型

配置写入 `.env` 文件，重启后生效。

---

## 7. 文献管理

### `library` — 全局文献库

```bash
scholarpilot library list
scholarpilot library add <DOI>
scholarpilot library search <关键词>
```

跨论文共享的全局文献库管理。

### `feed` — 文献订阅推送

```bash
scholarpilot feed init <项目名>
scholarpilot feed update <项目名>
scholarpilot feed recommend <项目名>
```

基于已有文献池的智能订阅：
- **反向引用追踪** — 谁引用了你的参考文献
- **同作者追踪** — 参考文献作者的新作
- **主题增量** — 同主题新发表文献

### `profile` — 研究者画像

```bash
scholarpilot profile show
scholarpilot profile update
```

维护研究者画像（学科/方向/偏好），用于个性化推荐。

---

## 常见工作流

### 工作流 0：首次使用（3 分钟上手）

```bash
# 1. 交互式配置 API Key 和模型
scholarpilot init

# 2. 查看示例模板，选择感兴趣的研究主题
scholarpilot examples

# 3. 从模板创建项目（研究主题自动预填）
scholarpilot new my_paper --template macro-fiscal

# 4. 开始生成论文
scholarpilot chat -p my_paper
```

### 工作流 A：从零开始写论文

```bash
scholarpilot new debt_paper
scholarpilot chat -p debt_paper "数字经济对企业绿色创新的影响"
# ... 自动执行 8 阶段 ...
scholarpilot dashboard debt_paper
scholarpilot check-ai debt_paper
scholarpilot export debt_paper -f docx
```

### 工作流 B：投稿准备

```bash
scholarpilot recommend-journal debt_paper --level CSSCI
scholarpilot cover-letter debt_paper --journal "经济研究" --author "张三"
scholarpilot export debt_paper -f pdf
```

### 工作流 C：审稿回复

```bash
scholarpilot revision-plan debt_paper --reviews-file reviews.txt --deadline "30天"
# 按计划修改论文...
scholarpilot edit debt_paper --section 4 --paragraph 2
scholarpilot check-ai debt_paper
scholarpilot export debt_paper -f docx
```

### 工作流 D：文献综述准备

```bash
scholarpilot literature-matrix debt_paper --enrich
# 生成结构化文献笔记，用于组会汇报
```

### 工作流 E：多模型成本优化

```bash
scholarpilot model-config --show
# 写作用 GLM-4（中文好），分析用 GPT-4o（推理强），轻量用 DeepSeek（便宜）
scholarpilot model-config --writing glm-4 --analysis gpt-4o --casual deepseek/deepseek-chat
scholarpilot chat -p debt_paper "继续"
```
