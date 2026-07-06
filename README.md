# ScholarPilot

学术论文写作 AI Agent — 基于 LangGraph + LiteLLM + MCP 的自动化论文生成系统。

从研究想法到初稿完成，全流程自动化。

## 核心能力

- **选题分析** — LLM 解析研究想法，提取核心主题、区域、研究内容
- **多源文献检索** — CNKI（知网）+ NCPSSD（国家哲社文献中心）+ Semantic Scholar + arXiv
- **8 维统计分析** — 文献总量、竞争程度、趋势分析、可行性判定
- **Spec-Driven 范式** — 先生成论文规格文档（SPEC.md），再基于规格生成大纲和正文
- **LangGraph 工作流** — 规划→执行→审核→定稿，支持条件路由和 Human-in-the-Loop
- **多格式导出** — Markdown → Word (.docx) / LaTeX (.tex)

## 快速开始

### 安装

```bash
cd scholarpilot
pip install -e ".[dev]"
```

### 配置

复制环境变量模板并填写 API Keys：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# LLM（至少配置一个）
CLAUDE_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
DEEPSEEK_API_KEY=sk-xxx

# 可选
SS_API_KEY=xxx           # Semantic Scholar API Key
CNKI_COOKIE=xxx          # CNKI 登录 Cookie（可选，有缓存）
```

### 使用

```bash
# 创建新项目
scholarpilot new my_paper

# 交互式对话
scholarpilot chat -p my_paper

# 列出项目
scholarpilot list

# 导出为 Word
scholarpilot export -p my_paper -f docx
```

## 架构

```
用户输入 → 选题分析 → 多源文献检索 → 8维统计 → SPEC.md
                                                        ↓
    Word/LaTeX ← 定稿 ← 人工审核 ← 逐章撰写 ← 大纲 ← [用户确认]
```

### 目录结构

```
scholarpilot/
├── src/scholarpilot/
│   ├── agent/           # LangGraph Agent（状态图、节点）
│   │   ├── scholar.py   # 主控 + finalize_node
│   │   ├── planner.py   # 执行计划生成
│   │   ├── executor.py  # 步骤执行器
│   │   ├── review.py    # Human-in-the-Loop 审核
│   │   ├── graph.py     # StateGraph 定义
│   │   └── state.py     # ScholarState 类型
│   ├── mcp/             # MCP 协议层
│   │   ├── client.py    # 客户端管理器
│   │   ├── registry.py  # 服务器注册表
│   │   └── servers/     # 检索引擎
│   │       ├── cnki/    # CNKI（知网）
│   │       ├── ncpssd/  # 国家哲社文献中心
│   │       ├── semantic_scholar/
│   │       └── arxiv/
│   ├── llm/             # LLM 网关（LiteLLM）
│   ├── context/         # 上下文窗口 + 项目记忆
│   ├── models/          # 数据模型（Pydantic）
│   ├── tools/           # 文献检索管理 + 格式导出
│   └── utils/           # 文件管理 + 日志
└── tests/               # 测试
```

## 文献检索

| 数据源 | 类型 | 状态 | 说明 |
|--------|------|------|------|
| CNKI（知网） | 中文期刊 | ✅ 已验证 | 1736 篇实测，需有效 Cookie |
| NCPSSD | 中文期刊 | ✅ 已验证 | 703 篇，免费无需登录 |
| Semantic Scholar | 英文学术 | ✅ 已验证 | 2.14 亿篇 |
| arXiv | 英文预印本 | ✅ 已验证 | 经济学分类 |

中文文献使用 `ChineseLiteratureManager` 双源合并去重，CNKI 不可用时 NCPSSD 兜底。

## 开发

```bash
# 运行测试
pytest tests/ -v

# 代码检查
pylint src/scholarpilot/
```

## 技术栈

- **Python 3.10+**
- **LangGraph** — 状态图工作流
- **LiteLLM** — 多模型 LLM 网关（Claude/GPT/DeepSeek/智谱）
- **aiohttp + BeautifulSoup** — CNKI 检索
- **Pydantic v2** — 数据验证
- **Rich** — 终端 UI
- **pytest** — 测试框架

## License

MIT