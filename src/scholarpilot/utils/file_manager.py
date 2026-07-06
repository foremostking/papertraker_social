"""项目文件管理器.

负责创建和管理论文项目的目录结构。
Agent 通过此管理器直接操作文件系统，所有产出物都是真实文件。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class FileManager:
    """论文项目文件管理器.

    管理项目目录的创建、文件读写等操作。
    Agent 的所有产出都通过此管理器写入真实文件，
    用户可以用任何编辑器（VSCode、Typora、Word）查看和修改。

    Usage:
        fm = FileManager(projects_dir=Path("./projects"))
        project = fm.create_project("my_paper")
        fm.save_spec(project, spec_content)
        fm.save_outline(project, outline_content)
        fm.save_section(project, "chapter1", content)
    """

    # 项目目录结构定义
    PROJECT_DIRS = [
        "literature",
        "literature/papers",
        "data",
        "data/raw",
        "data/processed",
        "analysis",
        "analysis/results",
        "draft",
        "final",
        "final/figures",
        ".scholar",
    ]

    def __init__(self, projects_dir: Path | str) -> None:
        """初始化文件管理器.

        Args:
            projects_dir: 项目根目录。
        """
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def create_project(self, name: str) -> Path:
        """创建新的论文项目目录结构.

        目录结构:
            {projects_dir}/{name}/
            ├── SPEC.md              # 论文规格文档
            ├── outline.md           # 大纲
            ├── outline.json         # 大纲结构化数据
            ├── literature/          # 文献
            │   ├── review.md        # 文献综述
            │   ├── references.bib   # 参考文献
            │   └── papers/          # 下载的PDF
            ├── data/                # 数据
            │   ├── raw/             # 原始数据
            │   └── processed/       # 处理后的数据
            ├── analysis/            # 实证分析
            │   ├── main.py          # 分析代码
            │   └── results/         # 分析结果
            ├── draft/               # 各章节草稿
            ├── final/              # 最终论文
            │   ├── paper.tex        # LaTeX终稿
            │   └── figures/         # 图表
            └── .scholar/           # Agent内部状态
                ├── state.json      # 状态检查点
                ├── memory.json     # 项目记忆
                └── plan.json       # 执行计划

        Args:
            name: 项目名称。

        Returns:
            项目目录路径。
        """
        project_dir = self.projects_dir / name
        project_dir.mkdir(parents=True, exist_ok=True)

        # 创建所有子目录
        for sub in self.PROJECT_DIRS:
            (project_dir / sub).mkdir(parents=True, exist_ok=True)

        # 初始化元数据文件（增强版：含论文标题、主题、目标期刊）
        meta = {
            "name": name,
            "title": "",  # 论文标题（选题后回填）
            "topic": "",  # 研究主题关键词
            "target_journal": "",  # 目标期刊
            "research_type": "",  # 研究类型（empirical/theoretical）
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": "created",
        }
        self._write_json(project_dir / ".scholar" / "meta.json", meta)

        # 初始化空文件（占位）
        spec_path = project_dir / "SPEC.md"
        if not spec_path.exists():
            spec_path.write_text(
                f"# 论文规格文档\n\n> 项目: {name}\n> 创建时间: {meta['created_at']}\n\n"
                "## 研究主题\n\n（待填写）\n\n## 研究问题\n\n（待填写）\n",
                encoding="utf-8",
            )

        # 初始化空的 BibTeX 文件
        bib_path = project_dir / "literature" / "references.bib"
        if not bib_path.exists():
            bib_path.write_text("% BibTeX references\n", encoding="utf-8")

        # 初始化空的执行计划
        plan_path = project_dir / ".scholar" / "plan.json"
        if not plan_path.exists():
            self._write_json(plan_path, {"steps": [], "current_index": 0})

        # 初始化空的项目记忆
        memory_path = project_dir / ".scholar" / "memory.json"
        if not memory_path.exists():
            self._write_json(memory_path, {"entries": {}})

        return project_dir

    def get_project_dir(self, name: str) -> Path | None:
        """获取项目目录路径.

        Args:
            name: 项目名称。

        Returns:
            项目目录路径，如果不存在则返回 None。
        """
        project_dir = self.projects_dir / name
        if project_dir.exists() and (project_dir / ".scholar" / "meta.json").exists():
            return project_dir
        return None

    def list_projects(self) -> list[str]:
        """列出所有项目.

        Returns:
            项目名称列表。
        """
        projects = []
        if not self.projects_dir.exists():
            return projects
        for p in self.projects_dir.iterdir():
            if p.is_dir() and (p / ".scholar" / "meta.json").exists():
                projects.append(p.name)
        return sorted(projects)

    def delete_project(self, name: str) -> bool:
        """删除项目.

        Args:
            name: 项目名称。

        Returns:
            是否删除成功。
        """
        import shutil

        project_dir = self.projects_dir / name
        if project_dir.exists():
            shutil.rmtree(project_dir)
            return True
        return False

    # ===== 文件读写方法 =====

    def save_spec(self, project_dir: Path, content: str) -> Path:
        """保存论文规格文档."""
        path = project_dir / "SPEC.md"
        path.write_text(content, encoding="utf-8")
        return path

    def load_spec(self, project_dir: Path) -> str | None:
        """加载论文规格文档."""
        path = project_dir / "SPEC.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def save_outline(self, project_dir: Path, md_content: str, json_data: dict | None = None) -> Path:
        """保存大纲（Markdown + JSON 双格式）."""
        md_path = project_dir / "outline.md"
        md_path.write_text(md_content, encoding="utf-8")
        if json_data:
            self._write_json(project_dir / "outline.json", json_data)
        return md_path

    def save_review(self, project_dir: Path, content: str) -> Path:
        """保存文献综述."""
        path = project_dir / "literature" / "review.md"
        path.write_text(content, encoding="utf-8")
        return path

    def save_section(self, project_dir: Path, section_name: str, content: str) -> Path:
        """保存章节内容到 draft/ 目录（自动创建版本快照）.

        每次保存都会创建带时间戳的版本快照，确保每次修改都有历史记录可追溯。
        """
        draft_dir = project_dir / "draft"
        draft_dir.mkdir(parents=True, exist_ok=True)
        file_path = draft_dir / f"{section_name}.md"
        file_path.write_text(content, encoding="utf-8")

        # 为当前保存创建版本快照
        self._save_version_snapshot(project_dir, section_name, content)
        return file_path

    def save_section_with_version(
        self,
        project_dir: Path,
        section_name: str,
        content: str,
        label: str = "",
        note: str = "",
    ) -> Path:
        """保存章节内容并附加语义标签和修改备注.

        用于科研工作者标记重要节点：初稿、投稿版、一审修改、终稿等。
        每次保存都会创建版本快照，标签和备注描述的是本次保存的内容。

        Args:
            project_dir: 项目目录。
            section_name: 章节名称。
            content: 章节内容。
            label: 语义标签，如 "初稿" "投稿版" "一审修改"。
            note: 修改备注，如 "根据审稿意见补充了稳健性检验"。

        Returns:
            保存的章节文件路径。
        """
        draft_dir = project_dir / "draft"
        draft_dir.mkdir(parents=True, exist_ok=True)
        file_path = draft_dir / f"{section_name}.md"
        file_path.write_text(content, encoding="utf-8")

        # 为当前保存创建版本快照（标签和备注描述本次保存的内容）
        self._save_version_snapshot(project_dir, section_name, content, label, note)
        return file_path

    def _save_version_snapshot(
        self,
        project_dir: Path,
        section_name: str,
        content: str,
        label: str = "",
        note: str = "",
    ) -> Path:
        """将内容保存为版本快照.

        存储结构: .scholar/versions/{section_name}/{timestamp}.md
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        version_dir = project_dir / ".scholar" / "versions" / section_name
        version_dir.mkdir(parents=True, exist_ok=True)

        # 避免同一秒内重复快照（添加序号后缀）
        content_path = version_dir / f"{ts}.md"
        meta_path = version_dir / f"{ts}.meta.json"
        if content_path.exists():
            seq = 1
            while content_path.exists():
                content_path = version_dir / f"{ts}_{seq}.md"
                meta_path = version_dir / f"{ts}_{seq}.meta.json"
                seq += 1
            ts = f"{ts}_{seq - 1}"

        content_path.write_text(content, encoding="utf-8")

        meta = {
            "timestamp": ts,
            "label": label,
            "note": note,
            "char_count": len(content),
            "word_count": len(content.replace(" ", "").replace("\n", "")),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json(meta_path, meta)
        return content_path

    def list_section_versions(
        self, project_dir: Path, section_name: str
    ) -> list[dict[str, Any]]:
        """列出章节的所有历史版本.

        Returns:
            版本信息列表，按时间倒序排列。每个元素包含:
            - timestamp: 版本时间戳
            - label: 语义标签
            - note: 修改备注
            - char_count: 字符数
            - word_count: 字数
        """
        version_dir = project_dir / ".scholar" / "versions" / section_name
        if not version_dir.exists():
            return []

        versions = []
        for meta_file in version_dir.glob("*.meta.json"):
            try:
                meta = self._read_json(meta_file)
                versions.append(meta)
            except (json.JSONDecodeError, OSError):
                continue

        # 按时间戳倒序
        versions.sort(key=lambda v: v.get("timestamp", ""), reverse=True)
        return versions

    def get_section_version(
        self, project_dir: Path, section_name: str, timestamp: str
    ) -> str | None:
        """获取指定历史版本的内容.

        Args:
            timestamp: 版本时间戳，如 "20260701_153000"。
        """
        version_path = project_dir / ".scholar" / "versions" / section_name / f"{timestamp}.md"
        if version_path.exists():
            return version_path.read_text(encoding="utf-8")
        return None

    def restore_section_version(
        self, project_dir: Path, section_name: str, timestamp: str
    ) -> Path | None:
        """将章节回退到指定历史版本.

        科研场景：审稿人要求"改回上一版"或导师说"还是上一版好"。
        回退前会先将当前内容保存为快照，确保不会丢失当前内容。
        回退操作本身也会创建一个"回退"标签的快照。

        Args:
            timestamp: 要回退到的版本时间戳。

        Returns:
            恢复后的章节文件路径，版本不存在则返回 None。
        """
        old_content = self.get_section_version(project_dir, section_name, timestamp)
        if old_content is None:
            return None

        # 先保存当前版本（标记为回退前快照）
        draft_path = project_dir / "draft" / f"{section_name}.md"
        if draft_path.exists():
            current_content = draft_path.read_text(encoding="utf-8")
            if current_content != old_content:
                self._save_version_snapshot(
                    project_dir, section_name, current_content,
                    label="回退前自动快照",
                    note=f"回退到 {timestamp} 前的自动保存",
                )

        # 恢复旧版本并创建回退快照
        draft_path.write_text(old_content, encoding="utf-8")
        self._save_version_snapshot(
            project_dir, section_name, old_content,
            label="回退",
            note=f"回退到版本 {timestamp}",
        )
        return draft_path

    def diff_section_versions(
        self,
        project_dir: Path,
        section_name: str,
        timestamp_1: str,
        timestamp_2: str,
    ) -> list[str]:
        """对比两个历史版本的差异.

        科研场景：查看"投稿版和修改版之间到底改了哪些地方"。

        Returns:
            差异行列表，格式类似 unified diff。
        """
        import difflib

        content_1 = self.get_section_version(project_dir, section_name, timestamp_1)
        content_2 = self.get_section_version(project_dir, section_name, timestamp_2)

        if content_1 is None or content_2 is None:
            return ["错误：无法找到指定的版本文件"]

        lines_1 = content_1.splitlines(keepends=True)
        lines_2 = content_2.splitlines(keepends=True)

        diff = difflib.unified_diff(
            lines_1, lines_2,
            fromfile=f"{timestamp_1}",
            tofile=f"{timestamp_2}",
            lineterm="",
        )
        return list(diff)

    def load_section(self, project_dir: Path, section_name: str) -> str | None:
        """加载章节内容."""
        file_path = project_dir / "draft" / f"{section_name}.md"
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
        return None

    def get_paragraphs(self, project_dir: Path, section_name: str) -> list[dict[str, Any]]:
        """将章节内容拆分为段落列表（供段落级编辑）.

        科研场景：研究者需要看到"第3段"然后说"改第3段"，
        而不是数行号或截取文本。

        段落按空行分割。每个段落包含：
        - index: 段落序号（从1开始）
        - content: 段落内容
        - preview: 前60字预览
        - char_count: 字数
        - type: 段落类型（heading/body/table/code）

        Returns:
            段落列表，空章节返回空列表。
        """
        content = self.load_section(project_dir, section_name)
        if not content:
            return []

        # 按双换行分割段落
        raw_paragraphs = re.split(r"\n\s*\n", content.strip())
        paragraphs: list[dict[str, Any]] = []

        for i, para in enumerate(raw_paragraphs, 1):
            para = para.strip()
            if not para:
                continue

            # 判断段落类型
            para_type = "body"
            if para.startswith("#"):
                para_type = "heading"
            elif para.startswith("|") or para.startswith("+--") or para.startswith("| "):
                para_type = "table"
            elif para.startswith("```"):
                para_type = "code"
            elif para.startswith(">"):
                para_type = "quote"

            # 过滤纯标题和表格代码块（这些通常不需要编辑）
            if para_type in ("heading", "code"):
                paragraphs.append({
                    "index": i,
                    "content": para,
                    "preview": para[:60],
                    "char_count": len(para),
                    "type": para_type,
                    "editable": False,
                })
            else:
                paragraphs.append({
                    "index": i,
                    "content": para,
                    "preview": para[:60] + ("..." if len(para) > 60 else ""),
                    "char_count": len(para),
                    "type": para_type,
                    "editable": True,
                })

        return paragraphs

    def replace_paragraph(
        self,
        project_dir: Path,
        section_name: str,
        paragraph_index: int,
        new_content: str,
        label: str = "段落编辑",
        note: str = "",
    ) -> Path | None:
        """替换单个段落内容（自动创建版本快照）.

        科研场景：研究者说"把第3段改一下"，Agent 生成新段落，
        此方法只替换第3段，其余不动。

        Args:
            paragraph_index: 段落序号（从1开始，与 get_paragraphs 返回的 index 对应）。
            new_content: 新段落内容。
            label: 版本快照标签。
            note: 修改备注。

        Returns:
            保存后的文件路径，段落不存在返回 None。
        """
        content = self.load_section(project_dir, section_name)
        if not content:
            return None

        # 按双换行分割，保留分隔符
        parts = re.split(r"(\n\s*\n)", content.strip())
        # parts 交替为 [段落, 分隔符, 段落, 分隔符, ...]
        # 重建段落列表（只含内容部分）
        paragraph_contents = [parts[i] for i in range(0, len(parts), 2)]
        separators = [parts[i] for i in range(1, len(parts), 2)]

        # 找到目标段落（跳过空段）
        current_index = 0
        target_pos = -1
        for pos, para in enumerate(paragraph_contents):
            if para.strip():
                current_index += 1
                if current_index == paragraph_index:
                    target_pos = pos
                    break

        if target_pos == -1:
            return None

        # 保存旧版本快照
        self._save_version_snapshot(
            project_dir, section_name, content, label, note
        )

        # 替换段落
        paragraph_contents[target_pos] = new_content.strip()

        # 重新组装
        result_parts = []
        for i, para in enumerate(paragraph_contents):
            result_parts.append(para)
            if i < len(separators):
                result_parts.append(separators[i])

        new_full_content = "\n".join(result_parts)

        # 保存
        draft_path = project_dir / "draft" / f"{section_name}.md"
        draft_path.write_text(new_full_content, encoding="utf-8")
        return draft_path

    def list_sections(self, project_dir: Path) -> list[str]:
        """列出所有章节名称（排除合并的完整草稿）."""
        draft_dir = project_dir / "draft"
        if not draft_dir.exists():
            return []
        return sorted(
            f.stem for f in draft_dir.iterdir()
            if f.is_file() and f.suffix == ".md" and f.stem != "full_draft"
        )

    def save_references(self, project_dir: Path, bib_content: str) -> Path:
        """保存 BibTeX 参考文献."""
        path = project_dir / "literature" / "references.bib"
        path.write_text(bib_content, encoding="utf-8")
        return path

    def append_reference(self, project_dir: Path, bib_entry: str) -> Path:
        """追加 BibTeX 条目."""
        path = project_dir / "literature" / "references.bib"
        with path.open("a", encoding="utf-8") as f:
            f.write(bib_entry + "\n\n")
        return path

    def save_final(self, project_dir: Path, filename: str, content: bytes | str) -> Path:
        """保存最终论文文件."""
        final_dir = project_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        path = final_dir / filename
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_bytes(content)
        return path

    def save_analysis_code(self, project_dir: Path, filename: str, content: str) -> Path:
        """保存实证分析代码."""
        analysis_dir = project_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        path = analysis_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def save_data(self, project_dir: Path, filename: str, content: str | bytes, raw: bool = True) -> Path:
        """保存数据文件."""
        subdir = "raw" if raw else "processed"
        data_dir = project_dir / "data" / subdir
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / filename
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_bytes(content)
        return path

    def save_state(self, project_dir: Path, state: dict[str, Any]) -> Path:
        """保存 Agent 状态检查点."""
        path = project_dir / ".scholar" / "state.json"
        self._write_json(path, state)
        return path

    def load_state(self, project_dir: Path) -> dict | None:
        """加载 Agent 状态检查点."""
        path = project_dir / ".scholar" / "state.json"
        if path.exists():
            return self._read_json(path)
        return None

    def save_plan(self, project_dir: Path, plan: dict) -> Path:
        """保存执行计划."""
        path = project_dir / ".scholar" / "plan.json"
        self._write_json(path, plan)
        return path

    def load_plan(self, project_dir: Path) -> dict | None:
        """加载执行计划."""
        path = project_dir / ".scholar" / "plan.json"
        if path.exists():
            return self._read_json(path)
        return None

    def save_memory(self, project_dir: Path, memory: dict) -> Path:
        """保存项目记忆."""
        path = project_dir / ".scholar" / "memory.json"
        self._write_json(path, memory)
        return path

    def load_memory(self, project_dir: Path) -> dict | None:
        """加载项目记忆."""
        path = project_dir / ".scholar" / "memory.json"
        if path.exists():
            return self._read_json(path)
        return None

    def get_project_meta(self, project_dir: Path) -> dict | None:
        """获取项目元数据."""
        path = project_dir / ".scholar" / "meta.json"
        if path.exists():
            return self._read_json(path)
        return None

    def update_project_status(self, project_dir: Path, status: str) -> None:
        """更新项目状态."""
        meta = self.get_project_meta(project_dir) or {}
        meta["status"] = status
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(project_dir / ".scholar" / "meta.json", meta)

    def update_project_meta(self, project_dir: Path, updates: dict[str, Any]) -> None:
        """批量更新项目元数据字段.

        支持更新 title、topic、target_journal、research_type、status 等字段。
        自动维护 updated_at 时间戳。对于已存在的旧格式 meta.json（缺少新字段），
        会自动补全。

        Args:
            project_dir: 项目目录路径。
            updates: 要更新的字段键值对。

        Usage:
            fm.update_project_meta(project_dir, {
                "title": "地方政府债务风险空间溢出效应研究",
                "topic": "地方政府债务",
                "target_journal": "财贸经济",
            })
        """
        meta = self.get_project_meta(project_dir) or {}
        # 确保新字段存在（兼容旧项目）
        for field in ("title", "topic", "target_journal", "research_type"):
            if field not in meta:
                meta[field] = ""
        meta.update(updates)
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(project_dir / ".scholar" / "meta.json", meta)

    # ===== 数据采集状态管理 =====

    def load_project_state(self, project_dir: Path) -> dict | None:
        """加载项目状态（含数据采集状态）."""
        return self.load_state(project_dir)

    def save_project_state(self, project_dir: Path, state: dict[str, Any]) -> Path:
        """保存项目状态."""
        return self.save_state(project_dir, state)

    def update_data_status(
        self,
        project_dir: Path,
        status: str,
        data_file: str = "",
    ) -> None:
        """更新数据采集状态.

        Args:
            project_dir: 项目目录。
            status: 数据状态 ("pending" | "provided" | "skipped")。
            data_file: 数据文件路径（如已提供）。
        """
        state = self.load_state(project_dir) or {}
        state["data_status"] = status
        if data_file:
            state["data_file"] = data_file
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save_state(project_dir, state)

    # ===== 审稿意见管理 =====

    def save_review_state(self, project_dir: Path, review_state: dict[str, Any]) -> Path:
        """保存审稿意见处理状态.

        存储结构: .scholar/review_state.json
        包含审稿意见解析结果、修改状态、回复记录。
        """
        review_path = project_dir / ".scholar" / "review_state.json"
        review_state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(review_path, review_state)
        return review_path

    def load_review_state(self, project_dir: Path) -> dict[str, Any] | None:
        """加载审稿意见处理状态."""
        review_path = project_dir / ".scholar" / "review_state.json"
        if review_path.exists():
            return self._read_json(review_path)
        return None

    def save_review_letter(self, project_dir: Path, letter_content: str) -> Path:
        """保存审稿意见回复函."""
        letter_path = project_dir / "review_response.md"
        letter_path.write_text(letter_content, encoding="utf-8")
        return letter_path

    def import_review_comments(self, project_dir: Path, comments: str) -> Path:
        """导入审稿意见原文."""
        comments_path = project_dir / ".scholar" / "review_comments.txt"
        comments_path.parent.mkdir(parents=True, exist_ok=True)
        comments_path.write_text(comments, encoding="utf-8")
        return comments_path

    # ===== 断点续写：进度持久化 =====

    # Agent 执行阶段定义（按顺序）
    PHASE_ORDER = [
        "topic_analysis",      # 选题分析
        "literature_search",   # 文献检索
        "spec_generation",     # 规格生成
        "outline",             # 大纲生成
        "data_collection",     # 数据采集
        "section_writing",     # 逐章撰写
        "post_processing",     # 摘要+引用管理
        "completed",           # 完成
    ]

    def save_progress(
        self,
        project_dir: Path,
        phase: str,
        completed_sections: list[str] | None = None,
        total_sections: int = 0,
        phase_detail: str = "",
    ) -> None:
        """保存 Agent 执行进度（支持断点续写）.

        科研场景：写到第三章时被审稿意见打断，回来后系统能告知
        "上次进行到：逐章撰写（已完成2/6章）"并从断点继续。

        Args:
            project_dir: 项目目录。
            phase: 当前阶段，取值见 PHASE_ORDER。
            completed_sections: 已完成的章节名列表，如 ["chapter1", "chapter2"]。
            total_sections: 总章节数。
            phase_detail: 阶段细节描述，如 "正在撰写第3章：文献综述"。
        """
        state = self.load_state(project_dir) or {}

        # 更新进度信息
        state["current_phase"] = phase
        state["last_run_at"] = datetime.now(timezone.utc).isoformat()

        # 维护已完成阶段列表
        completed_phases = state.get("completed_phases", [])
        phase_index = self.PHASE_ORDER.index(phase) if phase in self.PHASE_ORDER else -1
        if phase_index > 0:
            # 之前的阶段标记为已完成
            for i in range(phase_index):
                prev_phase = self.PHASE_ORDER[i]
                if prev_phase not in completed_phases:
                    completed_phases.append(prev_phase)
        state["completed_phases"] = completed_phases

        # 章节进度
        if completed_sections is not None:
            state["completed_sections"] = completed_sections
        if total_sections:
            state["total_sections"] = total_sections
        if phase_detail:
            state["phase_detail"] = phase_detail

        self.save_state(project_dir, state)

    def load_progress(self, project_dir: Path) -> dict[str, Any] | None:
        """加载项目执行进度.

        Returns:
            进度信息字典，包含:
            - current_phase: 当前阶段
            - completed_phases: 已完成阶段列表
            - completed_sections: 已完成章节
            - total_sections: 总章节数
            - last_run_at: 上次运行时间
            - phase_detail: 阶段细节
            - can_resume: 是否可以断点续写
            如无进度记录则返回 None。
        """
        state = self.load_state(project_dir)
        if not state or "current_phase" not in state:
            return None

        state["can_resume"] = (
            state.get("current_phase") != "completed"
            and len(state.get("completed_phases", [])) > 0
        )
        return state

    def get_progress_summary(self, project_dir: Path) -> str:
        """获取进度摘要文本（用于 CLI 展示）.

        Returns:
            如 "逐章撰写：已完成2/6章（正在撰写第3章：文献综述）"
            无进度则返回空字符串。
        """
        progress = self.load_progress(project_dir)
        if not progress:
            return ""

        phase = progress.get("current_phase", "")
        phase_labels = {
            "topic_analysis": "选题分析",
            "literature_search": "文献检索",
            "spec_generation": "规格生成",
            "outline": "大纲生成",
            "data_collection": "数据采集",
            "section_writing": "逐章撰写",
            "post_processing": "摘要与引用",
            "completed": "已完成",
        }
        phase_label = phase_labels.get(phase, phase)

        if phase == "completed":
            return "已完成"

        parts = [phase_label]
        completed = progress.get("completed_sections", [])
        total = progress.get("total_sections", 0)
        if total > 0:
            parts.append(f"已完成{len(completed)}/{total}章")

        detail = progress.get("phase_detail", "")
        if detail:
            parts.append(f"（{detail}）")

        return "：".join(parts[:2]) + (parts[2] if len(parts) > 2 else "")

    def _write_json(self, path: Path, data: dict) -> None:
        """写入 JSON 文件."""
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _read_json(self, path: Path) -> dict:
        """读取 JSON 文件."""
        return json.loads(path.read_text(encoding="utf-8"))
