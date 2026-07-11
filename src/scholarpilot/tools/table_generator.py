"""学术论文统计表格模板生成器。

提供描述性统计表、回归结果表和相关系数矩阵的 Markdown 和 LaTeX 模板生成功能。
支持显著性星号（*** p<0.01, ** p<0.05, * p<0.1）和 booktabs 三线表格式。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = [
    "generate_descriptive_stats_table",
    "generate_regression_table",
    "generate_correlation_table",
    "generate_regression_table_latex",
    "format_regression_with_significance",
    "format_correlation_with_significance",
    "generate_table_title",
    "get_significance_stars",
]


def get_significance_stars(p_value: float) -> str:
    """根据 p 值返回显著性星号。

    Args:
        p_value: p 值。

    Returns:
        显著性星号字符串：*** p<0.01, ** p<0.05, * p<0.1, 空字符串不显著。
    """
    if p_value is None:
        return ""
    if p_value < 0.01:
        return "***"
    elif p_value < 0.05:
        return "**"
    elif p_value < 0.1:
        return "*"
    return ""


def generate_table_title(table_type: str, number: int = 1, title: str = "") -> str:
    """生成表格标题。

    Args:
        table_type: 表格类型 ("descriptive"|"regression"|"correlation")。
        number: 表格编号。
        title: 自定义标题（可选）。

    Returns:
        表格标题字符串。
    """
    type_names = {
        "descriptive": "描述性统计",
        "regression": "回归结果",
        "correlation": "相关系数矩阵",
    }
    type_name = type_names.get(table_type, table_type)
    if title:
        return f"表{number} {title}"
    return f"表{number} {type_name}"


def generate_descriptive_stats_table(variables: list[dict]) -> str:
    """生成描述性统计表 Markdown 模板。

    Args:
        variables: 变量列表，每个字典包含：
            - name (str): 变量名
            - description (str): 变量描述
            - type (str): 变量类型，"continuous" 或 "虚拟变量"

    Returns:
        Markdown 格式的描述性统计表字符串。
    """
    header = ["变量", "定义", "观测数", "均值", "标准差", "最小值", "中位数", "最大值"]
    separator = ["---"] * len(header)

    lines: list[str] = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(separator) + "|")

    for var in variables:
        row = [var["name"], var["description"]]
        # 数据列留空
        row.extend(["", "", "", "", "", ""])
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("注：表中数据由研究者根据实际数据填写。")
    return "\n".join(lines)


def generate_regression_table(model_specs: list[dict]) -> str:
    """生成回归结果表 Markdown 模板。

    Args:
        model_specs: 模型规格列表，每个字典包含：
            - name (str): 列标题，如 "基准回归"
            - variables (list[str]): 变量名列表
            - has_fixed_effects (bool): 是否控制固定效应
            - has_cluster_se (bool): 是否使用聚类标准误

    Returns:
        Markdown 格式的回归结果表字符串。
    """
    if not model_specs:
        return ""

    # 收集所有变量（保持出现顺序且不重复）
    all_variables: list[str] = []
    seen: set[str] = set()
    for spec in model_specs:
        for var in spec["variables"]:
            if var not in seen:
                all_variables.append(var)
                seen.add(var)

    model_names = [spec["name"] for spec in model_specs]
    col_count = 1 + len(model_names)  # 变量名列 + 各模型列
    separator = ["---"] * col_count

    lines: list[str] = []
    header = [""] + model_names
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(separator) + "|")

    # 变量行
    for var in all_variables:
        row = [var] + [""] * len(model_names)
        lines.append("| " + " | ".join(row) + " |")

    lines.append("|" + "|".join(separator) + "|")

    # 底部统计量行
    stat_rows = ["观测数", "R²", "固定效应", "聚类标准误"]
    for stat in stat_rows:
        row: list[str] = [stat]
        for spec in model_specs:
            if stat == "固定效应":
                row.append("Yes" if spec.get("has_fixed_effects") else "No")
            elif stat == "聚类标准误":
                row.append("Yes" if spec.get("has_cluster_se") else "No")
            else:
                row.append("")
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def generate_correlation_table(variables: list[str]) -> str:
    """生成相关系数矩阵 Markdown 模板。

    Args:
        variables: 变量名列表。

    Returns:
        Markdown 格式的相关系数矩阵字符串，对角线为 1.000，
        上三角和下三角留空供研究者填写。
    """
    n = len(variables)
    if n == 0:
        return ""

    header = [""] + variables
    separator = ["---"] * (n + 1)

    lines: list[str] = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(separator) + "|")

    for i, row_var in enumerate(variables):
        cells: list[str] = [row_var]
        for j in range(n):
            if i == j:
                cells.append("1.000")
            else:
                cells.append("")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("注：相关系数由研究者填写。")
    return "\n".join(lines)


def format_regression_with_significance(
    model_specs: list[dict],
    results: dict | None = None,
) -> str:
    """生成带显著性星号的回归结果 Markdown 表。

    当 results 为 None 时生成空模板（留空待填）；
    当 results 提供时填入系数+标准误+显著性星号。

    Args:
        model_specs: 模型规格列表，每个含 name, variables。
        results: 回归结果，格式为 {model_name: {var: {"coef": float, "se": float, "p": float}}}。
            为 None 时生成空模板。

    Returns:
        Markdown 格式回归表，系数行后跟标准误行（括号内），含显著性星号。
    """
    if not model_specs:
        return ""

    all_variables: list[str] = []
    seen: set[str] = set()
    for spec in model_specs:
        for var in spec["variables"]:
            if var not in seen:
                all_variables.append(var)
                seen.add(var)

    model_names = [spec["name"] for spec in model_specs]
    col_count = 1 + len(model_names)

    lines: list[str] = []
    # 表头
    header = [""] + model_names
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * col_count) + "|")

    # 变量行（系数+标准误配对）
    for var in all_variables:
        # 系数行
        coef_row = [var]
        se_row = [""]  # 标准误行，变量名列留空
        for spec in model_specs:
            model_name = spec["name"]
            if results and model_name in results and var in results[model_name]:
                r = results[model_name][var]
                stars = get_significance_stars(r.get("p", 1.0))
                coef = r.get("coef", "")
                se = r.get("se", "")
                coef_str = f"{coef:.3f}{stars}" if isinstance(coef, (int, float)) else ""
                se_str = f"({se:.3f})" if isinstance(se, (int, float)) else ""
                coef_row.append(coef_str)
                se_row.append(se_str)
            else:
                coef_row.append("")
                se_row.append("")
        lines.append("| " + " | ".join(coef_row) + " |")
        lines.append("| " + " | ".join(se_row) + " |")

    lines.append("|" + "|".join(["---"] * col_count) + "|")

    # 底部统计量
    stat_rows = ["观测数", "R²", "固定效应", "聚类标准误"]
    for stat in stat_rows:
        row: list[str] = [stat]
        for spec in model_specs:
            if stat == "固定效应":
                row.append("Yes" if spec.get("has_fixed_effects") else "No")
            elif stat == "聚类标准误":
                row.append("Yes" if spec.get("has_cluster_se") else "No")
            elif results and spec["name"] in results:
                model_res = results[spec["name"]]
                if stat == "观测数":
                    row.append(str(model_res.get("n_obs", "")))
                elif stat == "R²":
                    r2 = model_res.get("r_squared", "")
                    row.append(f"{r2:.3f}" if isinstance(r2, (int, float)) else "")
                else:
                    row.append("")
            else:
                row.append("")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("注：*** p<0.01, ** p<0.05, * p<0.1；括号内为标准误。")
    return "\n".join(lines)


def format_correlation_with_significance(
    variables: list[str],
    corr_data: dict | None = None,
) -> str:
    """生成带显著性星号的相关系数矩阵 Markdown 表。

    Args:
        variables: 变量名列表。
        corr_data: 相关系数和 p 值，格式为
            {"matrix": {v1: {v2: corr}}, "p_values": {v1: {v2: p}}}。
            为 None 时生成空模板。

    Returns:
        Markdown 格式相关系数矩阵，含显著性星号。
    """
    n = len(variables)
    if n == 0:
        return ""

    header = [""] + variables
    separator = ["---"] * (n + 1)

    lines: list[str] = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(separator) + "|")

    for i, row_var in enumerate(variables):
        cells: list[str] = [row_var]
        for j, col_var in enumerate(variables):
            if i == j:
                cells.append("1.000")
            elif corr_data and "matrix" in corr_data:
                matrix = corr_data["matrix"]
                p_values = corr_data.get("p_values", {})
                if row_var in matrix and col_var in matrix[row_var]:
                    corr_val = matrix[row_var][col_var]
                    p_val = p_values.get(row_var, {}).get(col_var, 1.0)
                    stars = get_significance_stars(p_val)
                    cells.append(f"{corr_val:.3f}{stars}")
                else:
                    cells.append("")
            else:
                cells.append("")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("注：*** p<0.01, ** p<0.05, * p<0.1。")
    return "\n".join(lines)


def generate_regression_table_latex(model_specs: list[dict], caption: str = "") -> str:
    """生成 LaTeX booktabs 三线表格式的回归表模板。

    Args:
        model_specs: 模型规格列表。
        caption: 表格标题（LaTeX caption）。

    Returns:
        LaTeX booktabs 格式的回归表字符串。
    """
    if not model_specs:
        return ""

    all_variables: list[str] = []
    seen: set[str] = set()
    for spec in model_specs:
        for var in spec["variables"]:
            if var not in seen:
                all_variables.append(var)
                seen.add(var)

    model_names = [spec["name"] for spec in model_specs]
    n_cols = 1 + len(model_names)
    col_spec = "l" + "c" * len(model_names)

    lines: list[str] = []
    lines.append(r"\begin{table}[htbp]")
    lines.append(r"  \centering")
    if caption:
        lines.append(f"  \\caption{{{caption}}}")
    lines.append(f"  \\begin{{tabular}}{{{col_spec}}}")
    lines.append(r"    \toprule")

    # 表头
    header = " & ".join([""] + model_names) + r" \\"
    lines.append(f"    {header}")
    lines.append(r"    \midrule")

    # 变量行（系数+标准误配对）
    for var in all_variables:
        lines.append(f"    {var} & " + " & ".join([""] * len(model_names)) + r" \\")
        lines.append(f"     & " + " & ".join([""] * len(model_names)) + r" \\")

    lines.append(r"    \midrule")

    # 底部统计量
    stat_rows = ["观测数", "R$^2$", "固定效应", "聚类标准误"]
    for stat in stat_rows:
        cells = []
        for spec in model_specs:
            if stat == "固定效应":
                cells.append("Yes" if spec.get("has_fixed_effects") else "No")
            elif stat == "聚类标准误":
                cells.append("Yes" if spec.get("has_cluster_se") else "No")
            else:
                cells.append("")
        lines.append(f"    {stat} & " + " & ".join(cells) + r" \\")

    lines.append(r"    \bottomrule")
    lines.append(r"  \end{tabular}")
    lines.append(r"  \begin{tablenotes}")
    lines.append(r"    \small")
    lines.append(r"    \item 注：*** p$<$0.01, ** p$<$0.05, * p$<$0.1。括号内为标准误。")
    lines.append(r"  \end{tablenotes}")
    lines.append(r"\end{table}")

    return "\n".join(lines)
