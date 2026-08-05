# 架构决策记录（Architecture Decision Records）

本目录记录 ScholarPilot 项目的架构决策（ADR，Architecture Decision Record）。

采用 [Michael Nygard 风格](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)：
每篇 ADR 独立成文，记录 **状态 / 背景 / 决策 / 后果**，以便日后回溯"为什么这么做"。

## 阅读方式

- 每条 ADR 状态为 `已接受`（Accepted）/ `已提议`（Proposed）/ `已废弃`（Deprecated）。
- 按决策点独立编号，互相引用时用 `ADR-NNN`。
- 决策变更时**新增一条 ADR** 声明取代旧条目，不直接改写历史，保持可追溯。

## 索引

| 编号 | 决策点 | 状态 |
|---|---|---|
| [ADR-001](./0001-单一主线与归档.md) | 确立 ScholarPilot 为唯一主线，其余旁支子系统归档 | 已接受 |
| [ADR-002](./0002-CNKI引擎收敛.md) | CNKI 接入收敛为 aiohttp 单一活动引擎 | 已接受 |
| [ADR-003](./0003-Agent运行时统一.md) | Agent 编排统一为 LangGraph，先抽后删过程式 ScholarAgent | 已接受 |
| [ADR-004](./0004-检索层合并.md) | 检索层合并为单一 LiteratureSearchManager | 已接受 |
| [ADR-005](./0005-MCP定位.md) | MCP 定位为直接导入的引擎包，不构建协议路由层 | 已接受 |
| [ADR-006](./0006-Web形态.md) | Web 层采用 Streamlit 最小监控面板 | 已接受 |
| [ADR-007](./0007-收敛路线图.md) | 收敛执行路线图（P0–P6 顺序与依赖） | 已接受 |

## 关联文档

- 全局架构评估与旁支盘点见工作区根目录（`AI论文自动化工程/`）的评估结论。
- 开发状态与多轮优化计划见 `.trae/documents/`。

_更新：2026-08-05_