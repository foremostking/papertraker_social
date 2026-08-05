"""定稿节点 - LangGraph scholar_finalize 节点.

从 scholar.py 抽取（ADR-003 Phase B），解除 scholar.py ↔ graph.py 的循环耦合。
负责合并章节草稿、导出最终文档（Word / LaTeX）。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def scholar_finalize_node(state: dict) -> dict:
    """定稿节点：合并章节、导出最终文档.

    从 ScholarState 中读取项目路径，合并所有草稿章节，
    调用导出工具生成 Word 和 LaTeX 格式的最终文档。

    Args:
        state: 当前 Agent 状态（ScholarState）。

    Returns:
        包含 final_output 的状态更新字典。
    """
    project_path = state.get("project_path", "")
    if not project_path:
        return {"final_output": ""}

    project_dir = Path(project_path)
    merged_path = project_dir / "draft" / "full_draft.md"

    # 合并章节（如果尚未合并）
    if not merged_path.exists():
        draft_dir = project_dir / "draft"
        if draft_dir.exists():
            sections = sorted(
                f for f in draft_dir.iterdir()
                if f.is_file() and f.suffix == ".md" and f.name != "full_draft.md"
            )
            if sections:
                merged = "# 论文草稿\n\n"
                for section_file in sections:
                    content = section_file.read_text(encoding="utf-8")
                    merged += content + "\n\n---\n\n"
                merged_path.parent.mkdir(parents=True, exist_ok=True)
                merged_path.write_text(merged, encoding="utf-8")

    if not merged_path.exists():
        return {"final_output": ""}

    # 导出为 Word 和 LaTeX
    from scholarpilot.tools.exporter import export_project

    final_outputs = []
    try:
        docx_path = export_project(project_dir, fmt="docx")
        final_outputs.append(str(docx_path))
    except Exception as e:
        final_outputs.append(f"docx export failed: {e}")

    try:
        tex_path = export_project(project_dir, fmt="latex")
        final_outputs.append(str(tex_path))
    except Exception as e:
        final_outputs.append(f"latex export failed: {e}")

    final_output = "\n".join(final_outputs)

    return {"final_output": final_output}
