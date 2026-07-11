"""数据预处理工具链，面向中国金融实证研究。

提供数据加载、缺失值检测与处理、缩尾处理、变量转换、
面板数据平衡性检验及清洗报告生成等功能。

典型使用流程::

    preprocessor = DataPreprocessor()
    df = preprocessor.load_data(Path("data.csv"))
    missing_info = preprocessor.check_missing(df)
    strategy = {col: info["suggestion"] for col, info in missing_info.items()}
    df = preprocessor.handle_missing(df, strategy)
    df = preprocessor.winsorize(df, ["gdp", "debt"])
    df = preprocessor.transform_variables(df, [
        {"name": "ln_gdp", "type": "log", "source": "gdp"},
        {"name": "lag_debt", "type": "lag", "source": "debt", "periods": 1, "group_by": "province"},
    ])
    report = preprocessor.generate_cleaning_report(df_original, df, ["缩尾处理", "对数转换"])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import pandas as pd

__all__ = ["DataPreprocessor"]


def _import_pandas() -> Any:
    """延迟导入 pandas，未安装时抛出友好错误。

    Returns:
        pandas 模块。

    Raises:
        ImportError: pandas 未安装。
    """
    try:
        import pandas as pd

        return pd
    except ImportError as e:
        raise ImportError(
            "pandas 是数据预处理所必需的依赖。请安装: pip install pandas"
        ) from e


def _import_numpy() -> Any:
    """延迟导入 numpy，未安装时抛出友好错误。

    Returns:
        numpy 模块。

    Raises:
        ImportError: numpy 未安装。
    """
    try:
        import numpy as np

        return np
    except ImportError as e:
        raise ImportError(
            "numpy 是数据处理所必需的依赖。请安装: pip install numpy"
        ) from e


class DataPreprocessor:
    """数据预处理工具链，面向中国金融实证研究。

    封装了从原始数据到可用于回归分析的清洗数据的完整流程，
    包括缺失值处理、缩尾、变量转换和面板平衡性检验。
    """

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def load_data(self, file_path: Path) -> pd.DataFrame:
        """加载 CSV/Excel 数据。支持 utf-8-sig 编码。

        Args:
            file_path: 数据文件路径，支持 .csv / .xlsx / .xls。

        Returns:
            加载后的 pandas DataFrame。

        Raises:
            ImportError: pandas 未安装。
            FileNotFoundError: 文件不存在。
            ValueError: 不支持的文件格式。
        """
        pd = _import_pandas()
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(file_path, encoding="utf-8-sig")
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(file_path)
        else:
            raise ValueError(
                f"不支持的文件格式: {suffix}，请使用 CSV (.csv) 或 Excel (.xlsx/.xls)。"
            )

        logger.info(
            "数据加载成功: %s (%d 行, %d 列)", file_path, len(df), len(df.columns)
        )
        return df

    # ------------------------------------------------------------------
    # 缺失值检测与处理
    # ------------------------------------------------------------------

    def check_missing(self, df: Any) -> dict[str, dict[str, Any]]:
        """缺失值检测：每列缺失数量、比例、建议处理方式。

        处理建议规则：
        - 缺失比例 > 30%: 建议删除该列 (drop)
        - 缺失比例 5% ~ 30%: 建议插值 (fill_interpolate)
        - 缺失比例 < 5%: 建议填充均值 (fill_mean)
        - 无缺失: 标记为 none

        Args:
            df: pandas DataFrame。

        Returns:
            缺失值检测结果字典，格式::

                {
                    "var1": {
                        "count": 5,
                        "ratio": 0.05,
                        "suggestion": "fill_mean"
                    },
                    ...
                }
        """
        result: dict[str, dict[str, Any]] = {}
        total_rows = len(df)

        for col in df.columns:
            missing_count = int(df[col].isna().sum())
            ratio = missing_count / total_rows if total_rows > 0 else 0.0

            if missing_count == 0:
                suggestion = "none"
            elif ratio > 0.30:
                suggestion = "drop"
            elif ratio >= 0.05:
                suggestion = "fill_interpolate"
            else:
                suggestion = "fill_mean"

            result[col] = {
                "count": missing_count,
                "ratio": round(ratio, 4),
                "suggestion": suggestion,
            }

        logger.info("缺失值检测完成，共检查 %d 列", len(result))
        return result

    def handle_missing(
        self, df: Any, strategy: dict[str, str]
    ) -> pd.DataFrame:
        """缺失值处理。

        Args:
            df: pandas DataFrame。
            strategy: 处理策略字典，格式::

                {
                    "var1": "drop",
                    "var2": "fill_mean",
                    "var3": "fill_median",
                    "var4": "fill_interpolate"
                }

            支持的策略：
            - ``drop``: 删除该变量缺失的行
            - ``fill_mean``: 用均值填充
            - ``fill_median``: 用中位数填充
            - ``fill_interpolate``: 线性插值

        Returns:
            处理后的 DataFrame（副本）。

        Raises:
            ValueError: 未知的处理策略。
        """
        result = df.copy()

        valid_strategies = {
            "drop",
            "fill_mean",
            "fill_median",
            "fill_interpolate",
            "none",
        }

        for var, method in strategy.items():
            if var not in result.columns:
                logger.warning("变量 '%s' 不在数据列中，跳过", var)
                continue

            if method not in valid_strategies:
                raise ValueError(
                    f"未知的处理策略 '{method}'（变量: {var}）。"
                    f"支持: {sorted(valid_strategies)}"
                )

            if method == "none":
                continue
            elif method == "drop":
                before = len(result)
                result = result.dropna(subset=[var])
                logger.info(
                    "变量 '%s': 删除缺失行 (%d -> %d)", var, before, len(result)
                )
            elif method == "fill_mean":
                fill_value = result[var].mean()
                result[var] = result[var].fillna(fill_value)
                logger.info("变量 '%s': 填充均值 %.4f", var, fill_value)
            elif method == "fill_median":
                fill_value = result[var].median()
                result[var] = result[var].fillna(fill_value)
                logger.info("变量 '%s': 填充中位数 %.4f", var, fill_value)
            elif method == "fill_interpolate":
                result[var] = result[var].interpolate()
                # 插值后仍可能存在缺失（首尾），用前向/后向填充补充
                remaining = result[var].isna().sum()
                if remaining > 0:
                    result[var] = result[var].ffill().bfill()
                    logger.info(
                        "变量 '%s': 线性插值 + 边缘填充, 剩余缺失 %d",
                        var,
                        remaining,
                    )
                else:
                    logger.info("变量 '%s': 线性插值完成", var)

        logger.info("缺失值处理完成，剩余 %d 行", len(result))
        return result

    # ------------------------------------------------------------------
    # 缩尾处理
    # ------------------------------------------------------------------

    def winsorize(
        self,
        df: Any,
        variables: list[str],
        lower: float = 0.01,
        upper: float = 0.99,
    ) -> pd.DataFrame:
        """缩尾处理：将极端值截断到指定分位数。

        中国金融实证研究的标准操作（1%/99% winsorize）。
        手动实现，使用 pandas quantile，不依赖 scipy。

        截断逻辑：低于下分位数的值被替换为下分位数，
        高于上分位数的值被替换为上分位数。NaN 值保持不变。

        Args:
            df: pandas DataFrame。
            variables: 需要缩尾的变量列表。
            lower: 下分位数，默认 0.01（即第 1 百分位）。
            upper: 上分位数，默认 0.99（即第 99 百分位）。

        Returns:
            缩尾后的 DataFrame（副本）。
        """
        result = df.copy()

        for var in variables:
            if var not in result.columns:
                logger.warning("变量 '%s' 不在数据列中，跳过缩尾", var)
                continue

            series = result[var]
            lower_bound = series.quantile(lower)
            upper_bound = series.quantile(upper)

            result[var] = series.clip(lower=lower_bound, upper=upper_bound)

            logger.info(
                "变量 '%s' 缩尾完成: 截断区间 [%.4f, %.4f]",
                var,
                lower_bound,
                upper_bound,
            )

        return result

    # ------------------------------------------------------------------
    # 变量转换
    # ------------------------------------------------------------------

    def transform_variables(
        self, df: Any, transforms: list[dict[str, Any]]
    ) -> pd.DataFrame:
        """变量转换。

        支持的转换类型：
        - ``log``: 自然对数转换
        - ``lag``: 滞后项（支持分组）
        - ``diff``: 差分（支持分组）
        - ``interaction``: 交互项
        - ``standardize``: 标准化（Z-score）

        Args:
            df: pandas DataFrame。
            transforms: 转换规则列表，格式::

                [
                    {"name": "ln_gdp", "type": "log", "source": "gdp"},
                    {"name": "lag_gdp", "type": "lag", "source": "gdp",
                     "periods": 1, "group_by": "province"},
                    {"name": "diff_gdp", "type": "diff", "source": "gdp",
                     "periods": 1, "group_by": "province"},
                    {"name": "x1_x2", "type": "interaction", "sources": ["x1", "x2"]},
                    {"name": "z_score", "type": "standardize", "source": "var1"}
                ]

        Returns:
            添加了转换变量的 DataFrame（副本）。

        Raises:
            ValueError: 未知转换类型或源变量不存在。
            KeyError: 转换规则缺少必要字段。
        """
        result = df.copy()

        for t in transforms:
            name = t["name"]
            t_type = t["type"]

            if t_type == "log":
                source = t["source"]
                self._validate_column(result, source, name)
                np = _import_numpy()

                non_positive_count = int((result[source] <= 0).sum())
                if non_positive_count > 0:
                    logger.warning(
                        "变量 '%s' 有 %d 个非正值，取对数后将为 NaN",
                        source,
                        non_positive_count,
                    )
                result[name] = np.log(result[source])

            elif t_type == "lag":
                source = t["source"]
                periods = t.get("periods", 1)
                group_by = t.get("group_by")
                self._validate_column(result, source, name)
                if group_by:
                    self._validate_column(result, group_by, name)
                    result[name] = result.groupby(group_by)[source].shift(periods)
                else:
                    result[name] = result[source].shift(periods)

            elif t_type == "diff":
                source = t["source"]
                periods = t.get("periods", 1)
                group_by = t.get("group_by")
                self._validate_column(result, source, name)
                if group_by:
                    self._validate_column(result, group_by, name)
                    result[name] = result.groupby(group_by)[source].diff(periods)
                else:
                    result[name] = result[source].diff(periods)

            elif t_type == "interaction":
                sources = t["sources"]
                for s in sources:
                    self._validate_column(result, s, name)
                result[name] = result[sources].prod(axis=1)

            elif t_type == "standardize":
                source = t["source"]
                self._validate_column(result, source, name)
                mean_val = result[source].mean()
                std_val = result[source].std()
                if std_val == 0 or (std_val is not None and str(std_val) == "nan"):
                    logger.warning("变量 '%s' 标准差为 0 或 NaN，标准化结果全为 0", source)
                    result[name] = 0.0
                else:
                    result[name] = (result[source] - mean_val) / std_val

            else:
                raise ValueError(
                    f"未知的转换类型: '{t_type}'。"
                    f"支持: log, lag, diff, interaction, standardize"
                )

            logger.info("变量转换完成: %s (类型: %s)", name, t_type)

        return result

    # ------------------------------------------------------------------
    # 面板数据平衡性检验
    # ------------------------------------------------------------------

    def check_panel_balance(
        self, df: Any, entity_var: str, time_var: str
    ) -> dict[str, Any]:
        """面板数据平衡性检验：是否为平衡面板、各截面观测数、缺失年份。

        平衡面板的定义：每个截面个体在所有时间期都有观测值，
        即实际观测数 = 个体数 × 期数。

        Args:
            df: pandas DataFrame。
            entity_var: 截面个体变量名（如 "province"）。
            time_var: 时间变量名（如 "year"）。

        Returns:
            检验结果字典，格式::

                {
                    "is_balanced": True/False,
                    "entity_count": 30,
                    "time_periods": 10,
                    "expected_observations": 300,
                    "actual_observations": 295,
                    "entity_obs_counts": {"北京": 10, "上海": 9, ...},
                    "missing_combinations": [("上海", 2015), ...]
                }

        Raises:
            ValueError: entity_var 或 time_var 不在数据列中。
        """
        self._validate_column(df, entity_var, "(面板检验)")
        self._validate_column(df, time_var, "(面板检验)")

        entities = list(df[entity_var].unique())
        time_periods = sorted(df[time_var].unique())

        entity_count = len(entities)
        time_count = len(time_periods)
        expected = entity_count * time_count
        actual = len(df)

        # 各截面的观测数
        entity_obs = df.groupby(entity_var).size().to_dict()

        # 检查缺失的个体-时间组合
        all_combinations: set[tuple[Any, Any]] = set()
        for e in entities:
            for t_val in time_periods:
                all_combinations.add((e, t_val))

        existing_combinations = set(zip(df[entity_var], df[time_var]))
        missing_combinations = sorted(
            list(all_combinations - existing_combinations),
            key=lambda x: (str(x[0]), str(x[1])),
        )

        is_balanced = (actual == expected) and len(missing_combinations) == 0

        result = {
            "is_balanced": is_balanced,
            "entity_count": entity_count,
            "time_periods": time_count,
            "expected_observations": expected,
            "actual_observations": actual,
            "entity_obs_counts": {str(k): int(v) for k, v in entity_obs.items()},
            "missing_combinations": missing_combinations,
        }

        logger.info(
            "面板平衡性检验: %s (%d 个体 x %d 期, 实际 %d/%d)",
            "平衡" if is_balanced else "非平衡",
            entity_count,
            time_count,
            actual,
            expected,
        )

        return result

    # ------------------------------------------------------------------
    # 清洗报告
    # ------------------------------------------------------------------

    def generate_cleaning_report(
        self,
        df_original: Any,
        df_cleaned: Any,
        operations: list[str],
    ) -> str:
        """生成数据清洗报告（Markdown 格式）。

        报告内容包括：原始观测数、清洗后观测数、处理的缺失值数、
        缩尾变量、转换变量等。

        Args:
            df_original: 原始数据 DataFrame。
            df_cleaned: 清洗后数据 DataFrame。
            operations: 执行的操作描述列表，如
                ``["缩尾处理: gdp, debt (1%/99%)", "对数转换: ln_gdp"]``。

        Returns:
            Markdown 格式的清洗报告字符串。
        """
        original_rows = len(df_original)
        cleaned_rows = len(df_cleaned)
        rows_removed = original_rows - cleaned_rows

        original_cols = len(df_original.columns)
        cleaned_cols = len(df_cleaned.columns)

        original_missing = int(df_original.isna().sum().sum())
        cleaned_missing = int(df_cleaned.isna().sum().sum())
        missing_handled = original_missing - cleaned_missing

        lines: list[str] = []
        lines.append("# 数据清洗报告")
        lines.append("")
        lines.append("## 基本信息")
        lines.append("")
        lines.append(f"- 原始观测数: **{original_rows}**")
        lines.append(f"- 清洗后观测数: **{cleaned_rows}**")
        lines.append(f"- 删除观测数: **{rows_removed}**")
        lines.append(f"- 原始变量数: **{original_cols}**")
        lines.append(f"- 清洗后变量数: **{cleaned_cols}**")
        lines.append(f"- 处理缺失值数: **{missing_handled}**")
        lines.append(f"- 剩余缺失值数: **{cleaned_missing}**")
        lines.append("")

        lines.append("## 执行操作")
        lines.append("")
        if operations:
            for i, op in enumerate(operations, 1):
                lines.append(f"{i}. {op}")
        else:
            lines.append("（无操作记录）")
        lines.append("")

        lines.append("## 变量列表（清洗后）")
        lines.append("")
        lines.append("| 变量名 | 类型 | 非空值数 | 缺失值数 |")
        lines.append("|--------|------|----------|----------|")
        for col in df_cleaned.columns:
            dtype = str(df_cleaned[col].dtype)
            non_null = int(df_cleaned[col].notna().sum())
            null_count = int(df_cleaned[col].isna().sum())
            lines.append(f"| `{col}` | {dtype} | {non_null} | {null_count} |")
        lines.append("")

        report = "\n".join(lines)
        logger.info("数据清洗报告生成完成")
        return report

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_column(df: Any, col: str, context: str) -> None:
        """验证列是否存在于 DataFrame 中。

        Args:
            df: pandas DataFrame。
            col: 列名。
            context: 上下文描述（用于错误信息）。

        Raises:
            ValueError: 列不存在。
        """
        if col not in df.columns:
            raise ValueError(
                f"变量 '{col}' 不在数据列中（上下文: {context}）。"
                f"可用列: {list(df.columns)}"
            )
