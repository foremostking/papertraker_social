"""数据预处理工具链测试.

测试范围:
1. 数据加载 (load_data): CSV / Excel / 错误处理
2. 缺失值检测 (check_missing): 各种缺失比例的建议
3. 缺失值处理 (handle_missing): drop / fill_mean / fill_median / fill_interpolate
4. 缩尾处理 (winsorize): 极端值截断 / NaN 保持 / 自定义分位数
5. 变量转换 (transform_variables): log / lag / diff / interaction / standardize
6. 面板平衡性检验 (check_panel_balance): 平衡 / 非平衡面板
7. 清洗报告 (generate_cleaning_report): Markdown 格式

所有测试使用内存中的 pandas DataFrame，不依赖外部文件。
Excel 加载测试使用临时文件。

运行方式:
    cd scholarpilot
    python -m pytest tests/test_data_preprocessor.py -v
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scholarpilot.tools.data_preprocessor import DataPreprocessor


# ===== Fixtures =====


@pytest.fixture
def preprocessor() -> DataPreprocessor:
    """创建 DataPreprocessor 实例."""
    return DataPreprocessor()


@pytest.fixture
def sample_panel_df() -> pd.DataFrame:
    """创建示例面板数据（3 省 x 5 年 = 15 行，平衡面板）.

    包含变量: province, year, gdp, debt, pop
    """
    data = []
    provinces = ["北京", "上海", "广东"]
    years = [2010, 2011, 2012, 2013, 2014]
    gdp_values = [14000, 16000, 18000, 20000, 22000]
    debt_values = [5000, 5500, 6200, 7000, 7800]
    pop_values = [2000, 2100, 2200, 2300, 2400]

    for i, prov in enumerate(provinces):
        for j, year in enumerate(years):
            data.append(
                {
                    "province": prov,
                    "year": year,
                    "gdp": gdp_values[j] + i * 1000,
                    "debt": debt_values[j] + i * 200,
                    "pop": pop_values[j] + i * 100,
                }
            )

    return pd.DataFrame(data)


@pytest.fixture
def missing_data_df() -> pd.DataFrame:
    """创建含缺失值的数据（21 行）.

    - high_missing: ~47.6% 缺失（建议 drop）
    - medium_missing: ~14.3% 缺失（建议 fill_interpolate）
    - low_missing: ~4.8% 缺失（建议 fill_mean）
    - no_missing: 0% 缺失
    """
    n_rows = 21  # 用 21 行使 1 个缺失 = ~4.76% < 5%
    df = pd.DataFrame(
        {
            "no_missing": np.arange(n_rows, dtype=float),
            "low_missing": np.arange(n_rows, dtype=float),
            "medium_missing": np.arange(n_rows, dtype=float),
            "high_missing": np.arange(n_rows, dtype=float),
        }
    )
    # 制造缺失值
    df.loc[0, "low_missing"] = np.nan  # 1/21 ≈ 4.76% < 5%
    df.loc[0:2, "medium_missing"] = np.nan  # 3/21 ≈ 14.29%
    df.loc[0:9, "high_missing"] = np.nan  # 10/21 ≈ 47.62%
    return df


@pytest.fixture
def extreme_value_df() -> pd.DataFrame:
    """创建含极端值的数据（用于缩尾测试）.

    包含 100 个正常值和 2 个极端值（一个极大、一个极小）。
    """
    rng = np.random.RandomState(42)
    normal_values = rng.normal(100, 10, size=100)
    values = np.concatenate([[1e6, -1e6], normal_values])
    return pd.DataFrame({"value": values})


# ===== 1. 数据加载测试 =====


class TestLoadData:
    """测试数据加载功能."""

    def test_load_csv(self, preprocessor: DataPreprocessor, tmp_path: Path):
        """测试加载 CSV 文件（utf-8-sig 编码）."""
        csv_path = tmp_path / "test_data.csv"
        df_expected = pd.DataFrame(
            {"province": ["北京", "上海"], "gdp": [1000, 2000]}
        )
        df_expected.to_csv(csv_path, index=False, encoding="utf-8-sig")

        df = preprocessor.load_data(csv_path)

        assert len(df) == 2
        assert list(df.columns) == ["province", "gdp"]
        assert df["gdp"].tolist() == [1000, 2000]

    def test_load_excel(self, preprocessor: DataPreprocessor, tmp_path: Path):
        """测试加载 Excel 文件."""
        excel_path = tmp_path / "test_data.xlsx"
        df_expected = pd.DataFrame(
            {"province": ["北京", "上海", "广东"], "year": [2010, 2010, 2010]}
        )
        df_expected.to_excel(excel_path, index=False)

        df = preprocessor.load_data(excel_path)

        assert len(df) == 3
        assert list(df.columns) == ["province", "year"]
        assert df["province"].tolist() == ["北京", "上海", "广东"]

    def test_load_file_not_found(self, preprocessor: DataPreprocessor):
        """测试加载不存在的文件抛出 FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="数据文件不存在"):
            preprocessor.load_data(Path("/nonexistent/path/data.csv"))

    def test_load_unsupported_format(self, preprocessor: DataPreprocessor, tmp_path: Path):
        """测试加载不支持的文件格式抛出 ValueError."""
        bad_path = tmp_path / "data.txt"
        bad_path.write_text("some content", encoding="utf-8")

        with pytest.raises(ValueError, match="不支持的文件格式"):
            preprocessor.load_data(bad_path)


# ===== 2. 缺失值检测测试 =====


class TestCheckMissing:
    """测试缺失值检测功能."""

    def test_no_missing(self, preprocessor: DataPreprocessor):
        """无缺失值时建议为 none."""
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        result = preprocessor.check_missing(df)

        assert result["a"]["count"] == 0
        assert result["a"]["ratio"] == 0.0
        assert result["a"]["suggestion"] == "none"
        assert result["b"]["suggestion"] == "none"

    def test_high_missing_suggests_drop(
        self, preprocessor: DataPreprocessor, missing_data_df: pd.DataFrame
    ):
        """缺失比例 > 30% 建议删除."""
        result = preprocessor.check_missing(missing_data_df)

        assert result["high_missing"]["count"] == 10
        assert result["high_missing"]["ratio"] == round(10 / 21, 4)
        assert result["high_missing"]["suggestion"] == "drop"

    def test_medium_missing_suggests_interpolate(
        self, preprocessor: DataPreprocessor, missing_data_df: pd.DataFrame
    ):
        """缺失比例 5%-30% 建议插值."""
        result = preprocessor.check_missing(missing_data_df)

        assert result["medium_missing"]["count"] == 3
        assert result["medium_missing"]["ratio"] == round(3 / 21, 4)
        assert result["medium_missing"]["suggestion"] == "fill_interpolate"

    def test_low_missing_suggests_fill_mean(
        self, preprocessor: DataPreprocessor, missing_data_df: pd.DataFrame
    ):
        """缺失比例 < 5% 建议填充均值."""
        result = preprocessor.check_missing(missing_data_df)

        assert result["low_missing"]["count"] == 1
        assert result["low_missing"]["ratio"] == round(1 / 21, 4)
        assert result["low_missing"]["suggestion"] == "fill_mean"


# ===== 3. 缺失值处理测试 =====


class TestHandleMissing:
    """测试缺失值处理功能."""

    def test_drop_strategy(self, preprocessor: DataPreprocessor):
        """测试 drop 策略：删除缺失行."""
        df = pd.DataFrame(
            {"a": [1.0, 2.0, np.nan, 4.0], "b": [10, 20, 30, 40]}
        )
        result = preprocessor.handle_missing(df, {"a": "drop"})

        assert len(result) == 3
        assert result["a"].isna().sum() == 0

    def test_fill_mean_strategy(self, preprocessor: DataPreprocessor):
        """测试 fill_mean 策略：用均值填充."""
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, np.nan, 5.0]})
        result = preprocessor.handle_missing(df, {"a": "fill_mean"})

        expected_mean = (1.0 + 2.0 + 3.0 + 5.0) / 4  # 2.75
        assert result["a"].isna().sum() == 0
        assert result["a"].iloc[3] == pytest.approx(expected_mean)

    def test_fill_median_strategy(self, preprocessor: DataPreprocessor):
        """测试 fill_median 策略：用中位数填充."""
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, np.nan, 100.0]})
        result = preprocessor.handle_missing(df, {"a": "fill_median"})

        # 中位数为 3.0（排序后 1, 2, 3, 100 -> 中位数 (2+3)/2 = 2.5）
        expected_median = 2.5
        assert result["a"].isna().sum() == 0
        assert result["a"].iloc[3] == pytest.approx(expected_median)

    def test_fill_interpolate_strategy(self, preprocessor: DataPreprocessor):
        """测试 fill_interpolate 策略：线性插值."""
        df = pd.DataFrame({"a": [1.0, np.nan, 3.0, np.nan, 5.0]})
        result = preprocessor.handle_missing(df, {"a": "fill_interpolate"})

        assert result["a"].isna().sum() == 0
        # 位置 1 应为 1 和 3 的中点 = 2.0
        assert result["a"].iloc[1] == pytest.approx(2.0)
        # 位置 3 应为 3 和 5 的中点 = 4.0
        assert result["a"].iloc[3] == pytest.approx(4.0)

    def test_unknown_strategy_raises(
        self, preprocessor: DataPreprocessor
    ):
        """测试未知策略抛出 ValueError."""
        df = pd.DataFrame({"a": [1.0, np.nan]})
        with pytest.raises(ValueError, match="未知的处理策略"):
            preprocessor.handle_missing(df, {"a": "unknown_method"})

    def test_handle_missing_does_not_mutate_original(
        self, preprocessor: DataPreprocessor
    ):
        """测试处理不修改原始 DataFrame."""
        df = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
        original_na_count = df["a"].isna().sum()

        _ = preprocessor.handle_missing(df, {"a": "fill_mean"})

        assert df["a"].isna().sum() == original_na_count


# ===== 4. 缩尾处理测试 =====


class TestWinsorize:
    """测试缩尾处理功能."""

    def test_clips_extreme_values(
        self, preprocessor: DataPreprocessor, extreme_value_df: pd.DataFrame
    ):
        """测试极端值被截断到分位数."""
        result = preprocessor.winsorize(
            extreme_value_df, ["value"], lower=0.01, upper=0.99
        )

        # 极大值应被截断
        assert result["value"].max() < extreme_value_df["value"].max()
        # 极小值应被截断
        assert result["value"].min() > extreme_value_df["value"].min()
        # 截断后的最大值应等于 99 分位数
        expected_upper = extreme_value_df["value"].quantile(0.99)
        assert result["value"].max() == pytest.approx(expected_upper)
        # 截断后的最小值应等于 1 分位数
        expected_lower = extreme_value_df["value"].quantile(0.01)
        assert result["value"].min() == pytest.approx(expected_lower)

    def test_preserves_nan(self, preprocessor: DataPreprocessor):
        """测试 NaN 值在缩尾后保持不变."""
        df = pd.DataFrame({"a": [1.0, np.nan, 3.0, 100.0, 5.0]})
        result = preprocessor.winsorize(df, ["a"], lower=0.01, upper=0.99)

        # NaN 应该保持为 NaN
        assert result["a"].isna().sum() == 1
        assert np.isnan(result["a"].iloc[1])

    def test_custom_percentiles(self, preprocessor: DataPreprocessor):
        """测试自定义分位数（5%/95%）."""
        df = pd.DataFrame({"a": list(range(101))})  # 0-100
        result = preprocessor.winsorize(df, ["a"], lower=0.05, upper=0.95)

        lower_bound = df["a"].quantile(0.05)
        upper_bound = df["a"].quantile(0.95)
        assert result["a"].min() == pytest.approx(lower_bound)
        assert result["a"].max() == pytest.approx(upper_bound)

    def test_winsorize_does_not_mutate_original(
        self, preprocessor: DataPreprocessor, extreme_value_df: pd.DataFrame
    ):
        """测试缩尾不修改原始 DataFrame."""
        original_max = extreme_value_df["value"].max()

        _ = preprocessor.winsorize(extreme_value_df, ["value"])

        assert extreme_value_df["value"].max() == original_max


# ===== 5. 变量转换测试 =====


class TestTransformVariables:
    """测试变量转换功能."""

    def test_log_transform(self, preprocessor: DataPreprocessor):
        """测试对数转换."""
        df = pd.DataFrame({"gdp": [1.0, np.e, np.e**2, 100.0]})
        result = preprocessor.transform_variables(
            df, [{"name": "ln_gdp", "type": "log", "source": "gdp"}]
        )

        assert "ln_gdp" in result.columns
        assert result["ln_gdp"].iloc[0] == pytest.approx(0.0)
        assert result["ln_gdp"].iloc[1] == pytest.approx(1.0)
        assert result["ln_gdp"].iloc[2] == pytest.approx(2.0)

    def test_lag_with_group(
        self, preprocessor: DataPreprocessor, sample_panel_df: pd.DataFrame
    ):
        """测试分组滞后项."""
        result = preprocessor.transform_variables(
            sample_panel_df,
            [
                {
                    "name": "lag_gdp",
                    "type": "lag",
                    "source": "gdp",
                    "periods": 1,
                    "group_by": "province",
                }
            ],
        )

        assert "lag_gdp" in result.columns
        # 每组第一行应为 NaN
        beijing_rows = result[result["province"] == "北京"]
        assert pd.isna(beijing_rows.iloc[0]["lag_gdp"])
        # 第二行应为第一行的 gdp 值
        assert beijing_rows.iloc[1]["lag_gdp"] == beijing_rows.iloc[0]["gdp"]

    def test_diff_with_group(
        self, preprocessor: DataPreprocessor, sample_panel_df: pd.DataFrame
    ):
        """测试分组差分."""
        result = preprocessor.transform_variables(
            sample_panel_df,
            [
                {
                    "name": "diff_gdp",
                    "type": "diff",
                    "source": "gdp",
                    "periods": 1,
                    "group_by": "province",
                }
            ],
        )

        assert "diff_gdp" in result.columns
        # 每组第一行应为 NaN
        beijing_rows = result[result["province"] == "北京"]
        assert pd.isna(beijing_rows.iloc[0]["diff_gdp"])
        # 第二行差分 = 第二行 gdp - 第一行 gdp = 2000
        expected_diff = beijing_rows.iloc[1]["gdp"] - beijing_rows.iloc[0]["gdp"]
        assert beijing_rows.iloc[1]["diff_gdp"] == pytest.approx(expected_diff)

    def test_interaction(self, preprocessor: DataPreprocessor):
        """测试交互项."""
        df = pd.DataFrame({"x1": [1.0, 2.0, 3.0], "x2": [4.0, 5.0, 6.0]})
        result = preprocessor.transform_variables(
            df,
            [{"name": "x1_x2", "type": "interaction", "sources": ["x1", "x2"]}],
        )

        assert "x1_x2" in result.columns
        assert result["x1_x2"].tolist() == [4.0, 10.0, 18.0]

    def test_standardize(self, preprocessor: DataPreprocessor):
        """测试标准化（Z-score）."""
        df = pd.DataFrame({"var1": [1.0, 2.0, 3.0, 4.0, 5.0]})
        result = preprocessor.transform_variables(
            df,
            [{"name": "z_score", "type": "standardize", "source": "var1"}],
        )

        assert "z_score" in result.columns
        # 标准化后均值应接近 0
        assert result["z_score"].mean() == pytest.approx(0.0, abs=1e-10)
        # 标准化后标准差应接近 1
        assert result["z_score"].std() == pytest.approx(1.0, abs=1e-10)

    def test_unknown_transform_type_raises(
        self, preprocessor: DataPreprocessor
    ):
        """测试未知转换类型抛出 ValueError."""
        df = pd.DataFrame({"a": [1.0, 2.0]})
        with pytest.raises(ValueError, match="未知的转换类型"):
            preprocessor.transform_variables(
                df,
                [{"name": "bad", "type": "unknown", "source": "a"}],
            )

    def test_transform_does_not_mutate_original(
        self, preprocessor: DataPreprocessor
    ):
        """测试转换不修改原始 DataFrame."""
        df = pd.DataFrame({"gdp": [1.0, 2.0, 3.0]})
        original_cols = list(df.columns)

        _ = preprocessor.transform_variables(
            df, [{"name": "ln_gdp", "type": "log", "source": "gdp"}]
        )

        assert list(df.columns) == original_cols


# ===== 6. 面板平衡性检验测试 =====


class TestPanelBalance:
    """测试面板数据平衡性检验."""

    def test_balanced_panel(
        self, preprocessor: DataPreprocessor, sample_panel_df: pd.DataFrame
    ):
        """测试平衡面板检测."""
        result = preprocessor.check_panel_balance(
            sample_panel_df, "province", "year"
        )

        assert result["is_balanced"] is True
        assert result["entity_count"] == 3
        assert result["time_periods"] == 5
        assert result["expected_observations"] == 15
        assert result["actual_observations"] == 15
        assert len(result["missing_combinations"]) == 0
        # 每个个体应有 5 个观测
        for count in result["entity_obs_counts"].values():
            assert count == 5

    def test_unbalanced_panel(self, preprocessor: DataPreprocessor):
        """测试非平衡面板检测."""
        # 删除一行使面板不平衡
        df = pd.DataFrame(
            {
                "province": ["北京"] * 3 + ["上海"] * 2,
                "year": [2010, 2011, 2012, 2010, 2011],
                "gdp": [100, 200, 300, 400, 500],
            }
        )
        result = preprocessor.check_panel_balance(df, "province", "year")

        assert result["is_balanced"] is False
        assert result["entity_count"] == 2
        assert result["time_periods"] == 3
        assert result["expected_observations"] == 6
        assert result["actual_observations"] == 5
        # 应检测到上海缺少 2012 年的数据
        assert len(result["missing_combinations"]) == 1
        missing = result["missing_combinations"][0]
        assert missing[0] == "上海"
        assert missing[1] == 2012

    def test_panel_invalid_column_raises(
        self, preprocessor: DataPreprocessor
    ):
        """测试不存在的列名抛出 ValueError."""
        df = pd.DataFrame({"a": [1], "b": [2]})
        with pytest.raises(ValueError, match="变量 'province' 不在数据列中"):
            preprocessor.check_panel_balance(df, "province", "year")


# ===== 7. 清洗报告测试 =====


class TestCleaningReport:
    """测试数据清洗报告生成."""

    def test_report_basic_structure(
        self, preprocessor: DataPreprocessor, sample_panel_df: pd.DataFrame
    ):
        """测试报告基本结构."""
        df_cleaned = sample_panel_df.copy()
        report = preprocessor.generate_cleaning_report(
            sample_panel_df, df_cleaned, ["缩尾处理: gdp (1%/99%)"]
        )

        assert "# 数据清洗报告" in report
        assert "## 基本信息" in report
        assert "## 执行操作" in report
        assert "## 变量列表" in report
        assert "原始观测数" in report
        assert "清洗后观测数" in report

    def test_report_contains_operations(
        self, preprocessor: DataPreprocessor, sample_panel_df: pd.DataFrame
    ):
        """测试报告包含操作记录."""
        operations = [
            "缺失值处理: drop (province)",
            "缩尾处理: gdp, debt (1%/99%)",
            "对数转换: ln_gdp",
        ]
        report = preprocessor.generate_cleaning_report(
            sample_panel_df, sample_panel_df, operations
        )

        for op in operations:
            assert op in report

    def test_report_reflects_row_changes(
        self, preprocessor: DataPreprocessor
    ):
        """测试报告正确反映行数变化."""
        df_original = pd.DataFrame(
            {"a": [1, 2, 3, 4, 5], "b": [10, 20, 30, 40, 50]}
        )
        df_cleaned = df_original.iloc[:3].copy()  # 删除 2 行

        report = preprocessor.generate_cleaning_report(
            df_original, df_cleaned, ["删除缺失行"]
        )

        assert "原始观测数: **5**" in report
        assert "清洗后观测数: **3**" in report
        assert "删除观测数: **2**" in report

    def test_report_empty_operations(
        self, preprocessor: DataPreprocessor, sample_panel_df: pd.DataFrame
    ):
        """测试空操作列表."""
        report = preprocessor.generate_cleaning_report(
            sample_panel_df, sample_panel_df, []
        )

        assert "（无操作记录）" in report

    def test_report_contains_variable_table(
        self, preprocessor: DataPreprocessor, sample_panel_df: pd.DataFrame
    ):
        """测试报告包含变量列表表格."""
        report = preprocessor.generate_cleaning_report(
            sample_panel_df, sample_panel_df, ["测试"]
        )

        assert "| 变量名 | 类型 | 非空值数 | 缺失值数 |" in report
        for col in sample_panel_df.columns:
            assert f"`{col}`" in report


# ===== 8. 集成测试 =====


class TestIntegration:
    """端到端集成测试."""

    def test_full_pipeline(
        self, preprocessor: DataPreprocessor, sample_panel_df: pd.DataFrame
    ):
        """测试完整预处理流程: 检测缺失 -> 处理缺失 -> 缩尾 -> 转换 -> 报告."""
        # 1. 制造一些缺失值
        df_with_missing = sample_panel_df.copy()
        df_with_missing.loc[0, "gdp"] = np.nan
        df_with_missing.loc[1, "debt"] = np.nan

        # 2. 检测缺失值
        missing_info = preprocessor.check_missing(df_with_missing)
        assert missing_info["gdp"]["count"] == 1
        assert missing_info["debt"]["count"] == 1

        # 3. 处理缺失值
        strategy = {
            "gdp": "fill_mean",
            "debt": "fill_median",
            "province": "none",
            "year": "none",
            "pop": "none",
        }
        df_filled = preprocessor.handle_missing(df_with_missing, strategy)
        assert df_filled["gdp"].isna().sum() == 0
        assert df_filled["debt"].isna().sum() == 0

        # 4. 缩尾处理
        df_winsorized = preprocessor.winsorize(
            df_filled, ["gdp", "debt"], lower=0.05, upper=0.95
        )

        # 5. 变量转换
        df_transformed = preprocessor.transform_variables(
            df_winsorized,
            [
                {"name": "ln_gdp", "type": "log", "source": "gdp"},
                {
                    "name": "lag_debt",
                    "type": "lag",
                    "source": "debt",
                    "periods": 1,
                    "group_by": "province",
                },
            ],
        )
        assert "ln_gdp" in df_transformed.columns
        assert "lag_debt" in df_transformed.columns

        # 6. 面板平衡性检验
        balance = preprocessor.check_panel_balance(
            df_transformed, "province", "year"
        )
        assert balance["is_balanced"] is True

        # 7. 生成报告
        report = preprocessor.generate_cleaning_report(
            sample_panel_df,
            df_transformed,
            [
                "缺失值处理: gdp(fill_mean), debt(fill_median)",
                "缩尾处理: gdp, debt (5%/95%)",
                "变量转换: ln_gdp, lag_debt",
            ],
        )
        assert "# 数据清洗报告" in report
        assert "缩尾处理" in report
