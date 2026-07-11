"""格式导出工具.

支持将论文从 Markdown 导出为 Word (.docx) 和 LaTeX 格式。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def markdown_to_docx(md_content: str, output_path: Path, title: str = "论文") -> Path:
    """将 Markdown 转换为 Word 文档.

    Args:
        md_content: Markdown 格式的内容。
        output_path: 输出文件路径。
        title: 文档标题。

    Returns:
        生成的 .docx 文件路径。
    """
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # 设置默认字体（中文）
    style = doc.styles["Normal"]
    font = style.font
    font.name = "宋体"
    font.size = Pt(12)
    # 设置中文字体
    from docx.oxml.ns import qn
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    # 标题
    title_para = doc.add_heading(title, level=0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 解析 Markdown 并添加内容
    lines = md_content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # 标题
        if line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        # 分割线
        elif line.startswith("---"):
            doc.add_page_break()
        # 列表项
        elif line.startswith("- ") or line.startswith("* "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif re.match(r"^\d+\.\s", line):
            doc.add_paragraph(re.sub(r"^\d+\.\s", "", line), style="List Number")
        # 表格（简单处理）
        elif line.startswith("|"):
            # 收集表格所有行
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            _add_table_to_docx(doc, table_lines)
            continue
        # 代码块
        elif line.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if code_lines:
                p = doc.add_paragraph()
                run = p.add_text("\n".join(code_lines))
                run.font.name = "Courier New"
                run.font.size = Pt(10)
        # 普通段落
        else:
            # 处理加粗和斜体
            para = doc.add_paragraph()
            _add_formatted_text(para, line)

        i += 1

    # 保存
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return output_path


def markdown_to_latex(md_content: str, output_path: Path, title: str = "论文") -> Path:
    """将 Markdown 转换为 LaTeX 格式.

    Args:
        md_content: Markdown 格式的内容。
        output_path: 输出文件路径。
        title: 文档标题。

    Returns:
        生成的 .tex 文件路径。
    """
    lines = md_content.split("\n")
    latex_lines = [
        r"\documentclass[12pt,a4paper]{ctexart}",
        r"\usepackage{amsmath,amssymb}",
        r"\usepackage{graphicx}",
        r"\usepackage{hyperref}",
        r"\usepackage{booktabs}",
        r"\usepackage{geometry}",
        r"\geometry{margin=2.5cm}",
        r"",
        rf"\title{{{title}}}",
        r"\author{}",
        r"\date{}",
        r"",
        r"\begin{document}",
        r"\maketitle",
        r"",
    ]

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line:
            latex_lines.append("")
            i += 1
            continue

        # 标题
        if line.startswith("### "):
            latex_lines.append(rf"\subsubsection{{{_escape_latex(line[4:])}}}")
        elif line.startswith("## "):
            latex_lines.append(rf"\section{{{_escape_latex(line[3:])}}}")
        elif line.startswith("# "):
            latex_lines.append(rf"\section*{{{_escape_latex(line[2:])}}}")
        # 分割线
        elif line.startswith("---"):
            latex_lines.append(r"\newpage")
        # 列表项
        elif line.startswith("- ") or line.startswith("* "):
            latex_lines.append(rf"\item {_escape_latex(line[2:])}")
        # 普通段落
        else:
            # 处理加粗和斜体
            text = _escape_latex(line)
            text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
            text = re.sub(r"\*(.+?)\*", r"\\textit{\1}", text)
            latex_lines.append(text)

        i += 1

    latex_lines.extend([
        r"",
        r"\end{document}",
    ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(latex_lines), encoding="utf-8")
    return output_path


def export_project(
    project_dir: Path,
    fmt: str = "docx",
    output_name: str | None = None,
) -> Path:
    """导出项目的论文草稿为指定格式.

    Args:
        project_dir: 项目目录路径。
        fmt: 导出格式 (docx/latex/md)。
        output_name: 输出文件名（不含扩展名）。

    Returns:
        导出的文件路径。
    """
    # 加载完整草稿
    draft_path = project_dir / "draft" / "full_draft.md"
    if not draft_path.exists():
        # 合并所有章节
        draft_path = _merge_sections(project_dir)

    if not draft_path or not draft_path.exists():
        raise FileNotFoundError("未找到论文草稿，请先生成论文内容")

    md_content = draft_path.read_text(encoding="utf-8")

    # 获取标题
    title_match = re.search(r"^#\s+(.+)$", md_content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "论文"

    if output_name is None:
        output_name = title.replace(" ", "_")

    final_dir = project_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    if fmt.lower() == "docx":
        output_path = final_dir / f"{output_name}.docx"
        return markdown_to_docx(md_content, output_path, title)
    elif fmt.lower() in ("latex", "tex"):
        output_path = final_dir / f"{output_name}.tex"
        return markdown_to_latex(md_content, output_path, title)
    elif fmt.lower() == "md":
        output_path = final_dir / f"{output_name}.md"
        output_path.write_text(md_content, encoding="utf-8")
        return output_path
    elif fmt.lower() == "pdf":
        # 先生成 docx，再转换为 PDF
        docx_path = final_dir / f"{output_name}.docx"
        markdown_to_docx(md_content, docx_path, title)
        output_path = final_dir / f"{output_name}.pdf"
        _docx_to_pdf(docx_path, output_path)
        return output_path
    else:
        raise ValueError(f"不支持的格式: {fmt}。支持: docx, pdf, latex, md")


# ===== 内部辅助函数 =====

def _add_formatted_text(para, text: str) -> None:
    """处理 Markdown 格式并添加到段落."""
    # 分割加粗文本
    parts = re.split(r"(\*\*.+?\*\*|\*.+?\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = para.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("*") and part.endswith("*"):
            run = para.add_run(part[1:-1])
            run.italic = True
        else:
            para.add_run(part)


def _add_table_to_docx(doc, table_lines: list[str]) -> None:
    """将 Markdown 表格添加到 Word 文档."""
    from docx.shared import Pt

    rows = []
    for line in table_lines:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if cells:
            rows.append(cells)

    if not rows:
        return

    # 第一行是表头，第二行是分割线
    header = rows[0]
    data_rows = rows[2:] if len(rows) > 2 else rows[1:]

    table = doc.add_table(rows=1 + len(data_rows), cols=len(header))
    table.style = "Table Grid"

    # 表头
    for i, cell_text in enumerate(header):
        cell = table.rows[0].cells[i]
        cell.text = cell_text
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True

    # 数据行
    for row_idx, row_data in enumerate(data_rows):
        for col_idx, cell_text in enumerate(row_data):
            if col_idx < len(header):
                table.rows[row_idx + 1].cells[col_idx].text = cell_text


def _escape_latex(text: str) -> str:
    """转义 LaTeX 特殊字符."""
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def _docx_to_pdf(docx_path: Path, pdf_path: Path) -> Path:
    """将 Word 文档转换为 PDF.

    优先使用 docx2pdf（Windows 上利用 Word COM 自动化），
    失败则尝试 LibreOffice 命令行转换。

    Args:
        docx_path: .docx 文件路径。
        pdf_path: 输出 .pdf 文件路径。

    Returns:
        生成的 .pdf 文件路径。

    Raises:
        RuntimeError: 如果两种转换方式都失败。
    """
    import subprocess
    import sys

    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    # 方式1: docx2pdf（Windows 上利用 Word COM）
    try:
        from docx2pdf import convert as docx2pdf_convert
        docx2pdf_convert(str(docx_path), str(pdf_path))
        if pdf_path.exists():
            return pdf_path
    except ImportError:
        pass
    except Exception:
        pass

    # 方式2: LibreOffice 命令行
    try:
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf",
             "--outdir", str(pdf_path.parent), str(docx_path)],
            capture_output=True, text=True, timeout=60,
        )
        if pdf_path.exists():
            return pdf_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception:
        pass

    # 方式3: Windows 上尝试 soffice（LibreOffice 的 Windows 名称）
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf",
                 "--outdir", str(pdf_path.parent), str(docx_path)],
                capture_output=True, text=True, timeout=60,
            )
            if pdf_path.exists():
                return pdf_path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        except Exception:
            pass

    raise RuntimeError(
        "PDF 导出失败。请安装以下任一工具：\n"
        "  1. pip install docx2pdf（需要 Microsoft Word）\n"
        "  2. 安装 LibreOffice 并确保 libreoffice/soffice 在 PATH 中"
    )


def _merge_sections(project_dir: Path) -> Path | None:
    """合并所有章节为完整草稿.

    排除 full_draft.md 自身（避免重复合并）以及辅助文件（abstract/references/tables_template）。
    标题从 outline.json 读取，如不存在则回退到"论文草稿"。
    """
    draft_dir = project_dir / "draft"
    if not draft_dir.exists():
        return None

    # 排除 full_draft.md 自身和辅助文件
    exclude_names = {"full_draft.md", "abstract.md", "references.md", "tables_template.md"}
    sections = sorted(
        f for f in draft_dir.iterdir()
        if f.is_file() and f.suffix == ".md" and f.name not in exclude_names
    )
    if not sections:
        return None

    # 从 outline.json 读取标题
    title = "论文草稿"
    outline_path = project_dir / ".scholar" / "outline.json"
    if outline_path.exists():
        try:
            import json
            outline = json.loads(outline_path.read_text(encoding="utf-8"))
            title = outline.get("title", "论文草稿")
        except (json.JSONDecodeError, OSError):
            pass

    merged = f"# {title}\n\n"
    for section in sections:
        content = section.read_text(encoding="utf-8")
        merged += content + "\n\n---\n\n"

    draft_path = draft_dir / "full_draft.md"
    draft_path.write_text(merged, encoding="utf-8")
    return draft_path
