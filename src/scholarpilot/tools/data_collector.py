"""实证数据采集与管理工具.

负责：
1. 根据论文规格生成数据采集指南
2. 生成 CSV 数据模板
3. 读取用户提交的数据文件
4. 计算描述性统计
5. 格式化统计结果供 Prompt 注入
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def generate_csv_template(
    variables: list[dict[str, str]],
    output_path: Path,
    id_columns: list[str] | None = None,
) -> Path:
    """生成 CSV 数据模板文件.

    Args:
        variables: 变量列表，每个变量含 name（列名）、description（描述）。
        output_path: 输出文件路径。
        id_columns: 标识列（如 year, region），默认为 ["year", "region"]。

    Returns:
        生成的 CSV 文件路径。
    """
    if id_columns is None:
        id_columns = ["year", "region"]

    # 构建表头
    headers = id_columns + [v["name"] for v in variables]

    # 构建示例行（2行）
    example_rows = [
        {h: "" for h in headers},
        {h: "" for h in headers},
    ]
    if "year" in headers:
        example_rows[0]["year"] = "2010"
        example_rows[1]["year"] = "2011"
    if "region" in headers:
        example_rows[0]["region"] = "北京"
        example_rows[1]["region"] = "北京"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in example_rows:
            writer.writerow(row)

    logger.info(f"CSV template generated: {output_path}")
    return output_path


def load_user_data(data_path: Path) -> "Any":
    """读取用户提交的数据文件（CSV 或 Excel）.

    Args:
        data_path: 数据文件路径。

    Returns:
        pandas DataFrame。

    Raises:
        ImportError: 如果 pandas 未安装。
        FileNotFoundError: 文件不存在。
    """
    try:
        import pandas as pd
    except ImportError as e:
        raise ImportError("pandas is required for data loading. Install: pip install pandas") from e

    data_path = Path(data_path)
    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    suffix = data_path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(data_path, encoding="utf-8-sig")
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(data_path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Please use CSV or Excel.")

    logger.info(f"Data loaded: {data_path} ({len(df)} rows, {len(df.columns)} columns)")
    return df


def calculate_descriptive_stats(
    df: "Any",
    variables: list[str] | None = None,
) -> dict[str, dict[str, float]]:
    """计算描述性统计.

    Args:
        df: pandas DataFrame。
        variables: 要统计的变量名列表。如不提供，统计所有数值列。

    Returns:
        统计结果字典，格式为:
        {
            "variable_name": {
                "count": 3601,
                "mean": 0.523,
                "std": 0.178,
                "min": 0.012,
                "median": 0.498,
                "max": 0.987,
            }
        }
    """
    if variables is None:
        # 自动选择数值列
        variables = df.select_dtypes(include=["number"]).columns.tolist()

    stats: dict[str, dict[str, float]] = {}
    for var in variables:
        if var not in df.columns:
            logger.warning(f"Variable '{var}' not found in data columns")
            continue

        series = df[var].dropna()
        if len(series) == 0:
            continue

        stats[var] = {
            "count": int(len(series)),
            "mean": round(float(series.mean()), 4),
            "std": round(float(series.std()), 4),
            "min": round(float(series.min()), 4),
            "median": round(float(series.median()), 4),
            "max": round(float(series.max()), 4),
        }

    logger.info(f"Descriptive stats calculated for {len(stats)} variables")
    return stats


def format_stats_for_prompt(stats: dict[str, dict[str, float]]) -> str:
    """将描述性统计格式化为可注入 Prompt 的文本.

    Args:
        stats: calculate_descriptive_stats() 的输出。

    Returns:
        Markdown 格式的描述性统计表文本。
    """
    if not stats:
        return "（暂无描述性统计数据）"

    lines = ["### 描述性统计（基于用户提交的真实数据）", ""]
    lines.append("| 变量 | 观测数 | 均值 | 标准差 | 最小值 | 中位数 | 最大值 |")
    lines.append("|------|--------|------|--------|--------|--------|--------|")

    for var, s in stats.items():
        lines.append(
            f"| {var} | {s['count']} | {s['mean']:.4f} | {s['std']:.4f} "
            f"| {s['min']:.4f} | {s['median']:.4f} | {s['max']:.4f} |"
        )

    lines.append("")
    lines.append(
        "请基于以上真实统计数据撰写实证章节。"
        "在描述样本特征时，直接引用这些统计值。"
        "回归结果部分仍需研究者自行补充（系统不计算回归）。"
    )

    return "\n".join(lines)


def save_stats_to_json(
    stats: dict[str, dict[str, float]],
    output_path: Path,
    data_file: str = "",
) -> Path:
    """保存描述性统计到 JSON 文件.

    Args:
        stats: 统计结果。
        output_path: 输出路径。
        data_file: 数据文件名（记录来源）。

    Returns:
        JSON 文件路径。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "data_file": data_file,
        "variable_count": len(stats),
        "stats": stats,
    }
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Stats saved: {output_path}")
    return output_path


def is_empirical_section(section_title: str) -> bool:
    """判断章节是否为实证数据章节.

    Args:
        section_title: 章节标题。

    Returns:
        True 如果是实证数据章节。
    """
    keywords = ["实证", "结果", "描述性统计", "回归", "稳健性", "相关性"]
    return any(kw in section_title for kw in keywords)


__all__ = [
    "generate_csv_template",
    "load_user_data",
    "calculate_descriptive_stats",
    "format_stats_for_prompt",
    "save_stats_to_json",
    "is_empirical_section",
]
