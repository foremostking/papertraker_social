# ADR-003：Agent 编排统一为 LangGraph，先抽后删过程式 ScholarAgent

- 状态：已接受
- 日期：2026-08-05
- 关联：ADR-007（P3）

## 背景

`agent/` 下存在两套并行的 Agent 运行时：

1. **过程式** `agent/scholar.py` 中的 `ScholarAgent`（约 213 KB、90+ 方法）。`run()` 驱动 ~15 个 `_phase*` 阶段方法（`_phase1_topic_analysis` → `_phase8c_claim_calibration` → `finalize`），直接实例化多个引擎/管理器。仅被 `cli.py` 引用。
2. **状态图** `agent/graph.py` 的 LangGraph StateGraph（`scholar_plan → scholar_execute → human_review → scholar_finalize`），经 `agent/planner.py`、`agent/executor.py`、`agent/review.py` 实现。为当前主要路径。

关键问题：`ScholarAgent` 中有价值的逻辑（证据矩阵、claim 校准、8 维统计、多源检索编排）被现代 `executor.py` 路径绕过并重新实现（如 `phase7_write_sections` 与 `executor._execute_section_writing` 同义重复）。同时 `scholar_finalize_node` 图节点函数定义在 `scholar.py` 内，导致 `agent ↔ graph` 循环耦合。

## 决策

**确定 LangGraph 为唯一编排运行时，但分两步执行，先抽后删。**

- **Phase A**：把 `ScholarAgent` 中被现代路径绕过、但仍有价值的能力——证据矩阵、claim 校准、8 维统计等——抽取为 `tools/` 下的独立函数/模块。
- **Phase B**：抽取完成后**删除 `ScholarAgent` 类**；将 `scholar_finalize_node` 从 `scholar.py` 迁至独立文件（如 `agent/finalize.py`），解除 `scholar.py ↔ graph.py` 的循环耦合。
- `human_review` 的 "modify" 分支当前未实现，作为已知缺口在后续补充，不阻塞本次收敛。

## 后果

- **正面**：单一编排事实源，消除阶段逻辑双份实现与行为漂移；测试覆盖收敛到一条路径；代码显著减负（删除巨型类）。
- **负面/成本**：Phase A 抽取工作量大，是路线图中风险最高的一步；若抽取不完整会丢失有效逻辑。
- **约束**：必须先抽后删，严禁在能力下沉前直接删除，以免丢失 90+ 方法中的有效实现。

## 不决策的内容

- 不在此阶段重写 LangGraph 节点本身；只做"统一运行时 + 能力下沉"。
- 不改变 LangGraph 的 State / checkpoint 机制。