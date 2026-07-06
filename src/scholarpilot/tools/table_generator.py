"""学术论文统计表格模板生成器。

提供描述性统计表、回归结果表和相关系数矩阵的 Markdown 模板生成功能，
数据单元格留空供研究者填写。
"""

from __future__ import annotations


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


__all__ = [
    "generate_descriptive_stats_table",
    "generate_regression_table",
    "generate_correlation_table",
]
