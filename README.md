# ScholarPilot

**AI 辅助学术研究全流程工具** — 从选题到投稿，基于真实工具支撑（文献检索 + 计量分析 + 代码生成），非纯 LLM 生成。

面向高校教师、硕士/博士研究生，覆盖论文写作全生命周期。

## 核心能力

### 全流程自动化（8 阶段）
- **选题分析** — LLM 解析研究想法，提取主题/区域/研究类型，8 维可行性评估
- **多源文献检索** — CNKI + NCPSSD + Semantic Scholar + OpenAlex + arXiv，候选池 50-100 篇
- **Spec-Driven 生成** — 先生成 SPEC.md，再基于规格生成大纲和正文
- **逐章撰写** — 实证章节自动注入用户数据（描述性统计/回归结果）
- **引用验证** — 三层模糊匹配（精确/年份±1/经典文献），确保引用真实性
- **去 AI 味+润色** — 10 类 AI 写作模式检测，12 策略去 AI 处理，中文润色
- **多格式导出** — Word (.docx) / PDF / LaTeX / Markdown
- **投稿支持** — 期刊推荐 / Cover Letter / 审稿回复计划

### 学术诚信红线
- 所有引用经 CNKI/OpenAlex API 验证，未验证引用明确标注
- 实证章节用醒目占位符区分 AI 模板与真实数据
- 自动检测 data/ 文件夹中的用户数据并注入
- 去 AI 味处理降低 AI 检测概率

### 多模型支持
- **智谱 GLM-4** — 国产模型，性价比高，中文写作质量好（推荐国内用户）
- **火山方舟/豆包** — OpenAI 兼容，国内直连
- **Claude Sonnet 4** — 英文写作最佳，适合 SSCI/SCI 投稿
- **GPT-4o** — 通用分析能力强
- **DeepSeek** — 成本最低，适合轻量任务

支持分阶段配置不同模型（写作/分析/轻量），通过 `scholarpilot model-config` 管理。

## 快速开始

### 安装

```bash
cd scholarpilot
pip install -e ".[dev]"
```

### 配置

```bash
# 方式1：交互式引导（推荐首次用户）
cp .env.example .env
scholarpilot init

# 方式2：手动编辑
cp .env.example .env
# 编辑 .env，填入 API Key
```

`.env` 至少配置一个 LLM API Key：

```env
# 推荐：智谱 GLM-4（国内用户首选）
SCHOLAR_ZHIPU_API_KEY=your_key
SCHOLAR_DEFAULT_WRITING_MODEL=glm-4
SCHOLAR_DEFAULT_ANALYSIS_MODEL=glm-4
SCHOLAR_DEFAULT_CASUAL_MODEL=glm-4

# 或使用火山方舟
SCHOLAR_ARK_API_KEY=ark-xxx
SCHOLAR_ARK_DEFAULT_MODEL=ep-2024xxxx-xxxxx

# 可选：文献检索增强
SCHOLAR_SS_API_KEY=xxx           # Semantic Scholar（避免限流）
```

### 基本用法

```bash
# 0. 首次使用引导（交互式配置 API Key 和模型）
scholarpilot init

# 1. 查看示例模板（不知道写什么主题？从这里开始）
scholarpilot examples

# 2. 创建项目（从模板创建，研究主题自动预填）
scholarpilot new my_paper --template macro-fiscal

# 3. 交互式生成论文（全流程自动化）
scholarpilot chat -p my_paper

# 4. 查看仪表盘
scholarpilot dashboard my_paper

# 5. 检测 AI 写作痕迹
scholarpilot check-ai my_paper

# 6. 导出 Word
scholarpilot export my_paper -f docx

# 7. 推荐投稿期刊
scholarpilot recommend-journal my_paper --level CSSCI

# 8. 生成 Cover Letter
scholarpilot cover-letter my_paper --journal "经济研究"

# 9. 审稿回复计划
scholarpilot revision-plan my_paper --reviews "审稿意见..."
```

## 三类用户场景

### 高校教师
- **投稿决策**：`recommend-journal` 按冲刺/匹配/保底三级策略推荐期刊
- **投稿信撰写**：`cover-letter` 自动生成 4 段式 Cover Letter
- **审稿回复**：`revision-plan` 逐条分析审稿意见，生成修改计划+回复策略
- **学生指导**：`datasource` 帮学生定位数据源，`code` 生成计量代码

### 博士研究生
- **文献综述**：多源检索 50-100 篇，`literature-matrix` 生成结构化文献笔记
- **实证分析**：`stats`/`diagnose`/`mechanism` 完整计量工具链
- **论文打磨**：`check-ai` 检测 AI 痕迹，自动去 AI 味+润色
- **投稿准备**：期刊推荐 → Cover Letter → 导出 → 投稿

### 硕士研究生
- **数据指引**：`datasource` 匹配变量到 CSMAR/Wind/NBS 等数据源
- **代码生成**：`code` 生成 Stata/R/Python 计量代码模板
- **结果解析**：`parse-result` 解析回归输出为结构化表格
- **格式导出**：一键导出 Word/PDF，满足毕业论文格式要求

## 命令速查（33 个命令）

| 类别 | 命令 | 说明 |
|------|------|------|
| **入门** | `init` | 首次使用引导（交互式配置 API Key 和模型） |
| | `examples` | 查看示例项目模板（8个模板，6个学科） |
| **核心流程** | `new` | 创建论文项目（支持 `--template` 从模板创建） |
| | `chat` | 交互式对话，全流程生成 |
| | `status` | 查看项目状态 |
| | `progress` | 查看撰写进度（断点续写） |
| | `dashboard` | 项目仪表盘（质量指标+文件清单） |
| | `list` | 列出所有项目 |
| | `edit` | 段落级交互编辑 |
| | `versions` | 章节版本管理 |
| **质量保障** | `check-ai` | 检测 AI 写作痕迹 |
| | `quality` | 论文质量检查 |
| | `review` | 人工审核 |
| **数据分析** | `stats` | 描述性统计 |
| | `diagnose` | 计量诊断（VIF/Hausman/异方差） |
| | `mechanism` | 中介/调节效应分析 |
| | `tables` | 生成表格模板 |
| | `plot` | 科研绘图 |
| | `parse-result` | 解析回归输出 |
| | `preprocess` | 数据预处理 |
| | `code` | 生成计量代码 |
| **导出打包** | `export` | 导出 Word/PDF/LaTeX/MD |
| | `finalize` | 定稿处理 |
| | `package` | 可复现性打包 |
| **投稿支持** | `recommend-journal` | 期刊推荐 |
| | `cover-letter` | Cover Letter 生成 |
| | `revision-plan` | 审稿回复计划 |
| | `datasource` | 数据源指引 |
| **体验增强** | `literature-matrix` | 文献笔记矩阵 |
| | `model-config` | 多模型配置 |
| **文献管理** | `library` | 全局文献库 |
| | `feed` | 文献订阅推送 |
| | `profile` | 研究者画像 |

详细用法见 [COMMANDS.md](COMMANDS.md)。

## 架构

```
用户输入 → 选题分析 → 多源文献检索 → 8维统计 → SPEC.md
                                                      ↓
         投稿支持 ← 导出 ← 去AI味+润色 ← 引用验证 ← 逐章撰写 ← 大纲 ← [用户确认]
```

### 目录结构

```
scholarpilot/
├── src/scholarpilot/
│   ├── agent/           # LangGraph Agent（状态图、节点）
│   │   ├── scholar.py   # 主控 + 8 阶段流程
│   │   ├── planner.py   # 执行计划生成
│   │   └── executor.py  # 步骤执行器
│   ├── mcp/             # MCP 协议层（检索引擎）
│   ├── llm/             # LLM 网关（多模型统一调用）
│   ├── context/         # 上下文 + 项目记忆 + Prompt 模板
│   ├── models/          # 数据模型（Pydantic）
│   ├── tools/           # 工具集
│   │   ├── citation_manager.py      # 引用管理+验证
│   │   ├── submission_helper.py     # 投稿支持
│   │   ├── de_ai.py                 # 去AI味引擎
│   │   ├── data_source_guide.py     # 数据源指引
│   │   ├── result_parser.py         # 回归结果解析
│   │   ├── reproducibility.py       # 可复现性打包
│   │   ├── code_template_generator.py  # 代码模板生成
│   │   └── exporter.py              # 格式导出
│   ├── cli.py           # CLI 命令入口（31 个命令）
│   └── config.py        # 配置管理
└── tests/               # 测试（20+ 测试文件，200+ 用例）
```

## 文献检索

| 数据源 | 类型 | 状态 | 说明 |
|--------|------|------|------|
| CNKI（知网） | 中文期刊 | ✅ 已验证 | 专业检索语法，需有效 Cookie |
| NCPSSD | 中文期刊 | ✅ 已验证 | 免费无需登录 |
| Semantic Scholar | 英文学术 | ✅ 已验证 | 2.14 亿篇，推荐配置 API Key |
| OpenAlex | 英文学术 | ✅ 已验证 | 免费，覆盖全面 |
| arXiv | 英文预印本 | ✅ 已验证 | 经济学分类 |

中文文献使用 `ChineseLiteratureManager` 双源合并去重，CNKI 不可用时 NCPSSD 兜底。

## 开发

```bash
# 运行全部测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_submission_helper.py -v

# 代码检查
ruff check src/scholarpilot/
```

## 技术栈

- **Python 3.10+**
- **LangGraph** — 状态图工作流
- **LiteLLM** — 多模型 LLM 网关（GLM-4/Claude/GPT/DeepSeek/火山方舟）
- **aiohttp + BeautifulSoup** — CNKI 检索
- **Pydantic v2** — 数据验证
- **Rich + Typer** — 终端 UI + CLI 框架
- **pytest** — 测试框架

## License

MIT
