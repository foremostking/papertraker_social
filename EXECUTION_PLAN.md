# ScholarPilot 执行计划 — 基于学术志资料合集学习笔记

> 制定日期：2026-07-11
> 依据：学术志资料合集学习笔记与借鉴分析.md
> 目标：将学习笔记中的 P0/P1 借鉴方向落地为代码模块

## 一、执行项总览

| 优先级 | 编号 | 任务 | 新增/修改文件 | 状态 |
|--------|------|------|-------------|------|
| P0 | 1 | Prompt模板库重构 | `context/prompts/` 包（12个文件，46个Prompt常量） | ✅ 完成 |
| P0 | 2 | 文献综述流程升级 | `tools/review_methods.py`（5套方法论融合） | ✅ 完成 |
| P0 | 3 | 反幻觉与引用验证 | `tools/anti_hallucination.py`（DOI验证+证据等级+编造检测） | ✅ 完成 |
| P0 | 4 | 润色引擎升级 | `tools/polish_engine.py`（5层润色+斯坦福8类） | ✅ 完成 |
| P1 | 5 | 去AI味模块 | `tools/de_ai.py`（12策略+104组同义词） | ✅ 完成 |
| P1 | 6 | 补充缺失Prompt | `context/prompts/{topic,search,review,polish,de_ai,submission,defense,extended}.py`（33个新Prompt） | ✅ 完成 |
| P1 | 7 | 技术路线图生成 | `tools/roadmap_generator.py`（15模板+5模式+4格式导出） | ✅ 完成 |
| P1 | 8 | 多模型协同策略 | `tools/model_strategy.py`（5模型+19任务+4协同模式） | ✅ 完成 |
| — | 9 | 集成测试 | 376个现有测试通过 + 8个新模块导入验证通过 | ✅ 完成 |

## 二、各任务详细设计

### P0-1: Prompt模板库重构

**现状**：全部13个Prompt集中在 `prompts.py`（558行），缺乏分类管理
**目标**：拆分为按10阶段分类的模块化结构，新增150+条Prompt模板
**文件结构**：
```
context/prompts/
├── __init__.py          # 统一导出
├── system.py            # 系统提示词
├── topic.py             # 选题阶段（选题分析+选题细化）
├── search.py            # 文献检索阶段（检索策略+关键词拆解）
├── review.py            # 文献综述阶段（DeepSeek五步法+NotebookLM+Gemini）
├── spec.py              # 规格生成阶段
├── outline.py           # 大纲生成阶段
├── writing.py           # 章节撰写阶段
├── polish.py            # 润色阶段（5层润色+斯坦福8类指令）
├── de_ai.py             # 去AI味阶段（Gemini6策略+GPT5.5策略+降AI率）
├── submission.py        # 投稿阶段（期刊推荐+Cover Letter+审稿回复）
├── defense.py           # 答辩阶段
└── extended.py          # 补充Prompt（研究假设+学术辩论+时间表等）
```

### P0-2: 文献综述流程升级

**现状**：综述作为普通章节由 SECTION_WRITING_PROMPT 驱动，无独立方法论
**目标**：融合5套文献综述方法论，提供结构化的综述生成流程
**方法论融合**：
- DeepSeek五步法：边界锚定→矩阵构建→批判推演→大纲生成→分段验证
- NotebookLM五步法：关键词拆解→文献综述矩阵→综述撰写→风格调整→编辑审阅
- Gemini五步法：角色设定→海外调研→深层对比→痛点归纳→寻找缺口
- 文献综述指南PDF：五种综述类型+三段式结构+两道筛选
- ChatGPT逐段模板：研究背景→理论意义→实践意义→国外现状→国内现状→问题分析

### P0-3: 反幻觉与引用验证

**现状**：仅有人工审核环节和AI声明，无自动验证
**目标**：实现三套互补的反幻觉机制
**功能**：
- DOI验证：检查引用文献的DOI是否存在且可解析
- 证据等级标注：区分"强证据结论"与"推断性建议"
- 引用数量限制：每个关键论点最多引用3篇最直接文献
- 检索证据字段：记录每篇引用的数据库来源/检索关键词
- 引用交叉校验：检查正文引用是否在参考文献列表中

### P0-4: 润色引擎升级

**现状**：ParagraphEditor有7种操作，但无多层次润色
**目标**：建立5层润色能力
**层次**：
- 语法层：语法检查（只纠错不改写）、语法错误双列表格
- 表达层：英文润色(修改可追溯表格)、中文润色(分解长句+减少重复)、SCI论文润色
- 逻辑层：逻辑连贯性分析、段落衔接优化、句子结构多样性
- 风格层：期刊/会议风格适配、学术风格润色、封装基本事实
- 定位层：润色定位(指明具体修改了哪些段落)、修改建议(不全文修改)

### P1-5: 去AI味模块

**现状**：无任何去AI味功能
**目标**：整合三套去AI味方法论为统一流水线
**策略**：
- Gemini去AI味6策略：重构论述逻辑/强化事实基础/丰富内容细节/降AI率/防止编造/基础改写
- GPT5.5去AI味：人性化改写(≤20词/句)/以审稿人身份修订
- 50个顶级指令降重：11种降重策略

### P1-6: 补充缺失Prompt

**现状**：缺少选题细化、研究假设、学术辩论、期刊推荐、时间表、Cover Letter
**目标**：补充7个缺失的Prompt模板

### P1-7: 技术路线图生成

**现状**：无任何技术路线图功能
**目标**：基于923套模板的结构模式，实现自动推荐+Draw.io XML生成
**功能**：
- 5种结构模式识别（线性/分支/层级/环形/矩阵）
- 基于论文大纲自动推荐路线图结构
- 生成Draw.io XML代码
- 支持PPTX/DOCX格式输出

### P1-8: 多模型协同策略

**现状**：config.py中有3个默认模型，但无协同策略
**目标**：实现任务类型→模型自动匹配
**分工**：
- DeepSeek：深度推理（数学推导、逻辑论证、代码调试）
- 豆包/Claude：中文表达（正文撰写、润色、本土化）
- GPT：逻辑梳理、找漏洞、跨学科拓展
- Gemini：文献处理、结构化分析、技术路线图

## 三、执行顺序

1. P0-1 → P0-2 → P0-3 → P0-4（串行，P0核心）
2. P1-5 → P1-6（串行，依赖P0-1的Prompt结构）
3. P1-7 → P1-8（可并行）
4. 集成测试

---

## 四、P2-P6 执行记录（2026-07-18 ~ 2026-07-20）

### P2: 工具链增强（2026-07-18 完成）

| 编号 | 任务 | 文件 | 测试 | 状态 |
|------|------|------|------|------|
| P2-1 | 回归结果解析器 | `tools/result_parser.py` | 43 tests | ✅ |
| P2-2 | 可复现性打包 | `tools/reproducibility.py` | 45 tests | ✅ |
| P2-3 | 空间计量模板 | `tools/code_template_generator.py` | 16 tests | ✅ |

**关键成果：**
- `result_parser.py` 支持 Stata/R/Python/JSON 四种格式回归输出解析
- `reproducibility.py` 实现 ProvenanceTracker + ReproducibilityPackager
- `code_template_generator.py` 新增空间计量（SAR/SEM/SDM）R 和 Python 模板

### P3: 学术诚信基础（2026-07-19 完成）

| 编号 | 任务 | 文件 | 状态 |
|------|------|------|------|
| P3-1 | 三层引用模糊匹配 | `tools/citation_manager.py` | ✅ |
| P3-2 | 去AI味+润色集成 | `agent/scholar.py` (Phase 8b) | ✅ |
| P3-3 | AI检测CLI命令 | `cli.py` (`check-ai`) | ✅ |
| P3-4 | 导出验证 | `cli.py` (`export`) | ✅ |
| P3-5 | E2E v5 完美通过 | — | ✅ |

**关键成果：**
- 引用验证三层策略：1a 精确匹配 → 1b 年份±1模糊 → 1c 经典文献忽略年份
- Phase 8b 去 AI 味+润色自动执行，生成 `full_draft_polished.md` + `deai_report.md`
- E2E v5：0 CRITICAL，0 WARNING，5章25386字（原始）+26515字（润色），37引用0未验证，48.6%中文

### P4: 差异化价值（2026-07-20 完成）

| 编号 | 任务 | 文件 | 状态 |
|------|------|------|------|
| P4-1 | 期刊推荐 | `tools/submission_helper.py` + `cli.py` | ✅ |
| P4-2 | Cover Letter + 审稿回复 | `tools/submission_helper.py` + `cli.py` | ✅ |
| P4-3 | 数据源指引 | `tools/data_source_guide.py` + `cli.py` | ✅ |

**关键成果：**
- `recommend-journal`：冲刺/匹配/保底三级策略，6本期刊推荐
- `cover-letter`：4段式结构（投稿声明/贡献/匹配度/声明）
- `revision-plan`：9要素修改计划 + 执行顺序 + 工作量汇总
- `datasource`：17变量匹配 CSMAR/Wind/NBS 等数据源

### P5: 体验壁垒（2026-07-20 完成）

| 编号 | 任务 | 文件 | 状态 |
|------|------|------|------|
| P5-1 | 项目仪表盘 | `cli.py` (`dashboard`) | ✅ |
| P5-2 | 文献笔记矩阵 | `cli.py` (`literature-matrix`) | ✅ |
| P5-3 | 多模型配置 | `cli.py` (`model-config`) | ✅ |

**关键成果：**
- `dashboard`：6区块总览（基本信息/阶段进度/质量指标/文件清单/投稿状态/下一步建议）
- `literature-matrix`：基础版+LLM增强版，解析32条文献
- `model-config`：查看配置/API Key状态/阶段-模型映射/模型推荐

### P6: 文档与测试（2026-07-20 完成）

| 编号 | 任务 | 文件 | 状态 |
|------|------|------|------|
| P6-1a | README 重写 | `README.md` | ✅ |
| P6-1b | .env.example 更新 | `.env.example` | ✅ |
| P6-1c | 命令速查表 | `COMMANDS.md` | ✅ |
| P6-2a | submission_helper 测试 | `tests/test_submission_helper.py` (29 tests) | ✅ |
| P6-2b | dashboard + literature 测试 | `tests/test_dashboard.py` (12) + `tests/test_literature_matrix.py` (23) | ✅ |

**关键成果：**
- README 反映 31 命令、GLM-4 支持、三类用户场景
- .env.example 补全智谱/火山方舟/Claude/OpenAI/DeepSeek 配置
- COMMANDS.md 详细命令速查 + 5 个常见工作流
- P4/P5 新增功能 64 个测试全部通过

---

## 五、GLM-4 集成记录（2026-07-18）

**背景：** LiteLLM 1.89.4 不原生支持 `zhipu/` 前缀，需通过 OpenAI 兼容模式调用。

**实现：**
- `config.py`：新增 `zhipu_api_base` / `zhipu_default_model` / `zhipu_api_key`
- `gateway.py`：新增 `_is_zhipu_model()` 方法 + Zhipu 分支（chat + chat_stream）
- `.env`：新增智谱配置，默认模型切换为 glm-4
- NO_PROXY：添加 `open.bigmodel.cn`

**关键修复：**
- `api_base` 未传入 `litellm.acompletion` → 修复为 `is_ark or is_zhipu` 共用 api_base 传入

---

## 六、当前 CLI 命令清单（33 个）

| 类别 | 命令 | 实现阶段 |
|------|------|----------|
| 入门 | `init`, `examples` | P7 |
| 核心流程 | `new`, `chat`, `status`, `progress`, `dashboard`, `list`, `edit`, `versions` | P0/P5/P7 |
| 质量保障 | `check-ai`, `quality`, `review` | P3/P0 |
| 数据分析 | `stats`, `diagnose`, `mechanism`, `tables`, `plot`, `parse-result`, `preprocess`, `code` | P0/P2 |
| 导出打包 | `export`, `finalize`, `package` | P0/P2 |
| 投稿支持 | `recommend-journal`, `cover-letter`, `revision-plan`, `datasource` | P4 |
| 体验增强 | `literature-matrix`, `model-config` | P5 |
| 文献管理 | `library`, `feed`, `profile` | P1 |

---

## 七、测试统计

| 测试文件 | 测试数 | 覆盖模块 |
|----------|--------|----------|
| test_submission_helper.py | 29 | P4 投稿支持 |
| test_dashboard.py | 12 | P5 仪表盘（参考文献解析） |
| test_literature_matrix.py | 23 | P5 文献矩阵（参考文献解析） |
| test_result_parser.py | 43 | P2-1 回归结果解析 |
| test_reproducibility.py | 45 | P2-2 可复现性打包 |
| test_code_template.py | 16 | P2-3 空间计量模板 |
| test_de_ai.py | 27 | P3-2 去AI味引擎 |
| 其他测试文件 | ~200+ | P0/P1 核心模块 |
| **总计** | **~400+** | — |

---

### P7: 用户体验关键路径优化（2026-07-20 完成）

| 编号 | 任务 | 文件 | 状态 |
|------|------|------|------|
| P7-1 | 修复 reproducibility 测试失败 | `tools/reproducibility.py` | ✅ |
| P7-2 | 首次使用引导命令 | `cli.py` (`init`) | ✅ |
| P7-3 | 示例项目模板（8个，6学科） | `cli.py` (`_get_example_templates`) | ✅ |
| P7-4 | examples 命令 + new --template | `cli.py` (`examples`, `new`) | ✅ |

**关键成果：**
- `_get_dependency_versions()` 增加 scholarpilot 开发模式回退，修复测试失败
- `init` 命令：3步交互式引导（选提供商→输入API Key→确认模型），2分钟完成首次配置
- `examples` 命令：8个模板覆盖金融学/宏观/微观/产业/区域/国际贸易
- `new --template` 选项：从模板创建项目，自动预填标题/研究类型/研究主题描述
- CLI 命令总数从 31 增至 33

---

## 八、后续规划

### P8: 多场景 E2E 验证（待实施）
- 场景 A：金融学实证（公司治理，A股样本）— 使用 `finance-governance` 模板
- 场景 B：宏观经济学（省级面板，财政政策）— 使用 `macro-fiscal` 模板
- 验证不同学科、不同数据结构的鲁棒性

### P9: 产品化打包（待实施）
- PyPI 发布准备
- Docker 化部署
- Web UI 原型
