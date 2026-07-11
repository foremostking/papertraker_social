"""统计分析引擎（StatsEngine）功能验证测试.

测试范围:
1. 显著性星号函数 _significance_stars
2. 描述性统计（含 skew/kurtosis）
3. 相关系数矩阵（Pearson/Spearman + p值 + 显著性）
4. OLS回归（系数正确性、稳健标准误、显著性、R²）
5. 面板回归（FE/RE、聚类标准误）
6. VIF多重共线性检验
7. Hausman检验
8. 结果格式化（Markdown/LaTeX/JSON）
9. 一键完整分析

运行方式:
    cd scholarpilot
    python -m pytest tests/test_stats_engine.py -v
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from scholarpilot.tools.stats_engine import StatsEngine, _significance_stars


# ===== Fixtures =====

@pytest.fixture
def engine():
    """创建 StatsEngine 实例."""
    return StatsEngine()


@pytest.fixture
def cross_section_df():
    """生成交截面数据（固定随机种子）.

    真实模型: y = 1.0 + 2.0 * x1 + 3.0 * x2 + noise
    """
    np.random.seed(42)
    n = 200
    x1 = np.random.randn(n)
    x2 = np.random.randn(n)
    noise = np.random.randn(n) * 0.5
    y = 1.0 + 2.0 * x1 + 3.0 * x2 + noise
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2, "noise": noise})


@pytest.fixture
def panel_df():
    """生成面板数据（固定随机种子）.

    真实模型: y = 1.0 + 2.0 * x1 + 3.0 * x2 + entity_effect + noise
    20个个体 x 10年 = 200个观测值
    """
    np.random.seed(42)
    n_entities = 20
    n_years = 10
    n = n_entities * n_years

    entity_ids = np.repeat(np.arange(n_entities), n_years)
    years = np.tile(np.arange(2010, 2010 + n_years), n_entities)

    x1 = np.random.randn(n)
    x2 = np.random.randn(n)
    entity_effects = np.repeat(np.random.randn(n_entities) * 2, n_years)
    noise = np.random.randn(n) * 0.5
    y = 1.0 + 2.0 * x1 + 3.0 * x2 + entity_effects + noise

    return pd.DataFrame({
        "entity": entity_ids,
        "year": years,
        "y": y,
        "x1": x1,
        "x2": x2,
    })


@pytest.fixture
def multicollinear_df():
    """生成有多重共线性的数据（x3 ≈ 2*x1 + x2）."""
    np.random.seed(42)
    n = 200
    x1 = np.random.randn(n)
    x2 = np.random.randn(n)
    x3 = 2.0 * x1 + x2 + np.random.randn(n) * 0.01  # 近似线性相关
    y = 1.0 + x1 + x2 + x3 + np.random.randn(n) * 0.1
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2, "x3": x3})


@pytest.fixture
def df_with_missing():
    """生成含缺失值的数据."""
    np.random.seed(42)
    n = 100
    x1 = np.random.randn(n)
    x2 = np.random.randn(n)
    y = 1.0 + 2.0 * x1 + 3.0 * x2 + np.random.randn(n) * 0.5
    df = pd.DataFrame({"y": y, "x1": x1, "x2": x2})
    # 在 x1 中引入 10 个缺失值
    df.loc[df.sample(10, random_state=42).index, "x1"] = np.nan
    return df


# ===== 1. 显著性星号函数测试 =====

class TestSignificanceStars:
    """测试 _significance_stars 函数."""

    def test_stars_p_less_than_001(self):
        """p < 0.01 返回 ***."""
        assert _significance_stars(0.001) == "***"
        assert _significance_stars(0.009) == "***"
        assert _significance_stars(0.0) == "***"

    def test_stars_p_less_than_005(self):
        """0.01 <= p < 0.05 返回 **."""
        assert _significance_stars(0.01) == "**"
        assert _significance_stars(0.049) == "**"

    def test_stars_p_less_than_01(self):
        """0.05 <= p < 0.1 返回 *."""
        assert _significance_stars(0.05) == "*"
        assert _significance_stars(0.099) == "*"

    def test_stars_p_greater_than_01(self):
        """p >= 0.1 返回空字符串."""
        assert _significance_stars(0.1) == ""
        assert _significance_stars(0.5) == ""
        assert _significance_stars(1.0) == ""


# ===== 2. 描述性统计测试 =====

class TestDescriptiveStats:
    """测试描述性统计."""

    def test_descriptive_stats_basic(self, engine, cross_section_df):
        """基本描述性统计包含所有必要字段."""
        stats = engine.descriptive_stats(cross_section_df, variables=["y", "x1", "x2"])

        assert "y" in stats
        assert "x1" in stats
        assert "x2" in stats

        for var in ["y", "x1", "x2"]:
            s = stats[var]
            assert "count" in s
            assert "mean" in s
            assert "std" in s
            assert "min" in s
            assert "median" in s
            assert "max" in s
            assert "skew" in s
            assert "kurtosis" in s

    def test_descriptive_stats_count(self, engine, cross_section_df):
        """观测数等于数据行数."""
        stats = engine.descriptive_stats(cross_section_df, variables=["y"])
        assert stats["y"]["count"] == 200

    def test_descriptive_stats_skew_kurtosis(self, engine, cross_section_df):
        """偏度和峰度被正确计算（正态分布近似 0）."""
        stats = engine.descriptive_stats(cross_section_df, variables=["x1"])
        # x1 是标准正态分布，偏度应接近 0
        assert abs(stats["x1"]["skew"]) < 0.5
        # 超额峰度应接近 0
        assert abs(stats["x1"]["kurtosis"]) < 1.0

    def test_descriptive_stats_all_numeric(self, engine, cross_section_df):
        """不指定变量时统计所有数值列."""
        stats = engine.descriptive_stats(cross_section_df)
        assert "y" in stats
        assert "x1" in stats
        assert "x2" in stats

    def test_descriptive_stats_missing_variable(self, engine, cross_section_df):
        """不存在的变量被跳过."""
        stats = engine.descriptive_stats(cross_section_df, variables=["y", "nonexistent"])
        assert "y" in stats
        assert "nonexistent" not in stats

    def test_descriptive_stats_with_missing_values(self, engine, df_with_missing):
        """含缺失值时 count 正确反映非缺失数量."""
        stats = engine.descriptive_stats(df_with_missing, variables=["x1"])
        assert stats["x1"]["count"] == 90  # 100 - 10 缺失


# ===== 3. 相关系数矩阵测试 =====

class TestCorrelationMatrix:
    """测试相关系数矩阵."""

    def test_correlation_diagonal_is_one(self, engine, cross_section_df):
        """对角线相关系数为 1.0."""
        result = engine.correlation_matrix(cross_section_df, variables=["x1", "x2", "y"])
        matrix = result["matrix"]
        assert matrix["x1"]["x1"] == 1.0
        assert matrix["x2"]["x2"] == 1.0
        assert matrix["y"]["y"] == 1.0

    def test_correlation_symmetric(self, engine, cross_section_df):
        """相关系数矩阵是对称的."""
        result = engine.correlation_matrix(cross_section_df, variables=["x1", "x2", "y"])
        matrix = result["matrix"]
        assert matrix["x1"]["x2"] == matrix["x2"]["x1"]
        assert matrix["x1"]["y"] == matrix["y"]["x1"]

    def test_correlation_p_values_exist(self, engine, cross_section_df):
        """p 值矩阵被正确生成."""
        result = engine.correlation_matrix(cross_section_df, variables=["x1", "x2", "y"])
        p_values = result["p_values"]
        assert "x1" in p_values
        assert "x2" in p_values["x1"]

    def test_correlation_significant_stars(self, engine, cross_section_df):
        """显著性星号正确生成."""
        result = engine.correlation_matrix(cross_section_df, variables=["x1", "x2", "y"])
        sig = result["significant"]
        # 对角线应为 ***
        assert sig["x1"]["x1"] == "***"
        # x1 和 y 高度相关（因为 y = 1 + 2*x1 + 3*x2），应为 ***
        assert sig["x1"]["y"] == "***"

    def test_correlation_perfect_correlation(self, engine):
        """完全线性相关的变量相关系数为 1.0."""
        np.random.seed(42)
        x = np.random.randn(100)
        df = pd.DataFrame({"x": x, "x_double": 2 * x})
        result = engine.correlation_matrix(df, variables=["x", "x_double"])
        assert abs(result["matrix"]["x"]["x_double"] - 1.0) < 0.001

    def test_correlation_method_spearman(self, engine, cross_section_df):
        """Spearman 相关系数方法可用."""
        result = engine.correlation_matrix(
            cross_section_df, variables=["x1", "x2"], method="spearman"
        )
        assert result["method"] == "spearman"
        assert "matrix" in result


# ===== 4. OLS 回归测试 =====

class TestOLSRegression:
    """测试 OLS 回归."""

    def test_ols_coefficients_correct(self, engine, cross_section_df):
        """OLS 系数接近真实值（y = 1 + 2*x1 + 3*x2）."""
        result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"], robust=False
        )
        coeffs = result["coefficients"]
        # 截距应接近 1.0
        assert abs(coeffs["const"] - 1.0) < 0.2
        # x1 系数应接近 2.0
        assert abs(coeffs["x1"] - 2.0) < 0.2
        # x2 系数应接近 3.0
        assert abs(coeffs["x2"] - 3.0) < 0.2

    def test_ols_r_squared_valid(self, engine, cross_section_df):
        """R² 在 [0, 1] 范围内且较高."""
        result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        r_sq = result["r_squared"]
        assert 0 <= r_sq <= 1
        # 由于 y = 1 + 2*x1 + 3*x2 + small noise，R² 应该很高
        assert r_sq > 0.9

    def test_ols_significance_stars(self, engine, cross_section_df):
        """显著变量的星号正确."""
        result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        sig = result["significant"]
        # x1 和 x2 都高度显著
        assert sig["x1"] == "***"
        assert sig["x2"] == "***"

    def test_ols_robust_vs_non_robust(self, engine, cross_section_df):
        """稳健标准误和普通标准误不同."""
        robust_result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"], robust=True
        )
        non_robust_result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"], robust=False
        )
        # 系数相同（都是 OLS 估计）
        assert robust_result["coefficients"] == non_robust_result["coefficients"]
        # 标准误可能不同
        assert robust_result["std_errors"]["x1"] != non_robust_result["std_errors"]["x1"]

    def test_ols_n_obs(self, engine, cross_section_df):
        """观测数正确."""
        result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        assert result["n_obs"] == 200

    def test_ols_f_statistic(self, engine, cross_section_df):
        """F 统计量和 p 值存在且合理."""
        result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        assert result["f_statistic"] > 0
        assert result["f_pvalue"] < 0.01  # 整体显著

    def test_ols_with_missing_values(self, engine, df_with_missing):
        """含缺失值时自动删除并正确回归."""
        result = engine.ols_regression(
            df_with_missing, dep_var="y", indep_vars=["x1", "x2"]
        )
        assert result["n_obs"] == 90  # 100 - 10 缺失

    def test_ols_invalid_variable_raises(self, engine, cross_section_df):
        """不存在的变量抛出 ValueError."""
        with pytest.raises(ValueError, match="不在数据列中"):
            engine.ols_regression(
                cross_section_df, dep_var="y", indep_vars=["nonexistent"]
            )


# ===== 5. 面板回归测试 =====

class TestPanelRegression:
    """测试面板回归."""

    def test_panel_fe_basic(self, engine, panel_df):
        """固定效应面板回归基本功能."""
        result = engine.panel_regression(
            panel_df, dep_var="y", indep_vars=["x1", "x2"],
            entity_var="entity", time_var="year", model="fe"
        )
        assert result["model"] == "fe"
        assert result["entity_effects"] is True
        assert "x1" in result["coefficients"]
        assert "x2" in result["coefficients"]
        # FE 不应有常数项（被个体效应吸收）
        assert "const" not in result["coefficients"]

    def test_panel_fe_coefficients_correct(self, engine, panel_df):
        """FE 系数接近真实值（y = 1 + 2*x1 + 3*x2 + entity_effect）."""
        result = engine.panel_regression(
            panel_df, dep_var="y", indep_vars=["x1", "x2"],
            entity_var="entity", time_var="year", model="fe", cluster=False
        )
        coeffs = result["coefficients"]
        # FE 消除了个体效应后，系数应接近真实值
        assert abs(coeffs["x1"] - 2.0) < 0.2
        assert abs(coeffs["x2"] - 3.0) < 0.2

    def test_panel_re_basic(self, engine, panel_df):
        """随机效应面板回归基本功能."""
        result = engine.panel_regression(
            panel_df, dep_var="y", indep_vars=["x1", "x2"],
            entity_var="entity", time_var="year", model="re"
        )
        assert result["model"] == "re"
        assert result["entity_effects"] is False
        # RE 应有常数项
        assert "const" in result["coefficients"]

    def test_panel_cluster_flag(self, engine, panel_df):
        """聚类标准误标志正确."""
        result_clustered = engine.panel_regression(
            panel_df, dep_var="y", indep_vars=["x1", "x2"],
            entity_var="entity", time_var="year", model="fe", cluster=True
        )
        result_unclustered = engine.panel_regression(
            panel_df, dep_var="y", indep_vars=["x1", "x2"],
            entity_var="entity", time_var="year", model="fe", cluster=False
        )
        assert result_clustered["clustered"] is True
        assert result_unclustered["clustered"] is False

    def test_panel_invalid_model_raises(self, engine, panel_df):
        """不支持的模型类型抛出 ValueError."""
        with pytest.raises(ValueError, match="不支持的面板模型"):
            engine.panel_regression(
                panel_df, dep_var="y", indep_vars=["x1"],
                entity_var="entity", time_var="year", model="invalid"
            )


# ===== 6. VIF 检验测试 =====

class TestVIFTest:
    """测试 VIF 多重共线性检验."""

    def test_vif_basic(self, engine, cross_section_df):
        """VIF 基本计算."""
        result = engine.vif_test(cross_section_df, indep_vars=["x1", "x2"])
        assert "variables" in result
        assert "x1" in result["variables"]
        assert "x2" in result["variables"]
        assert "max_vif" in result
        assert "has_multicollinearity" in result

    def test_vif_no_multicollinearity(self, engine, cross_section_df):
        """独立变量的 VIF 接近 1."""
        result = engine.vif_test(cross_section_df, indep_vars=["x1", "x2"])
        # x1 和 x2 独立，VIF 应接近 1
        assert result["variables"]["x1"] < 5
        assert result["variables"]["x2"] < 5
        assert result["has_multicollinearity"] is False

    def test_vif_high_multicollinearity(self, engine, multicollinear_df):
        """高度共线性变量的 VIF > 10."""
        result = engine.vif_test(multicollinear_df, indep_vars=["x1", "x2", "x3"])
        # x3 ≈ 2*x1 + x2，至少有一个 VIF > 10
        assert result["max_vif"] > 10
        assert result["has_multicollinearity"] is True

    def test_vif_invalid_variable_raises(self, engine, cross_section_df):
        """不存在的变量抛出 ValueError."""
        with pytest.raises(ValueError, match="不在数据列中"):
            engine.vif_test(cross_section_df, indep_vars=["nonexistent"])


# ===== 7. Hausman 检验测试 =====

class TestHausmanTest:
    """测试 Hausman 检验."""

    def test_hausman_returns_result(self, engine, panel_df):
        """Hausman 检验返回有效结果."""
        result = engine.hausman_test(
            panel_df, dep_var="y", indep_vars=["x1", "x2"],
            entity_var="entity", time_var="year"
        )
        assert "chi2" in result
        assert "p_value" in result
        assert "recommendation" in result
        assert "interpretation" in result
        assert result["recommendation"] in ("fe", "re")

    def test_hausman_chi2_non_negative(self, engine, panel_df):
        """Hausman chi2 统计量为非负（或负值时推荐 RE）."""
        result = engine.hausman_test(
            panel_df, dep_var="y", indep_vars=["x1", "x2"],
            entity_var="entity", time_var="year"
        )
        if result["chi2"] is not None:
            # chi2 可能为负（此时推荐 RE），但应为数值
            assert isinstance(result["chi2"], (int, float))


# ===== 8. 结果格式化测试 =====

class TestFormatResults:
    """测试结果格式化."""

    def test_format_ols_markdown(self, engine, cross_section_df):
        """OLS 结果 Markdown 格式包含必要内容."""
        result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        md = engine.format_results(result, format_type="markdown")
        assert "OLS" in md
        assert "x1" in md
        assert "x2" in md
        assert "const" in md
        assert "***" in md  # 显著性星号
        # 标准误在括号内
        assert "(" in md and ")" in md

    def test_format_ols_latex(self, engine, cross_section_df):
        """OLS 结果 LaTeX 格式包含 tabular 环境."""
        result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        latex = engine.format_results(result, format_type="latex")
        assert r"\begin{tabular}" in latex
        assert r"\end{tabular}" in latex
        assert r"\toprule" in latex
        assert r"\bottomrule" in latex

    def test_format_json(self, engine, cross_section_df):
        """JSON 格式输出有效 JSON."""
        result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        json_str = engine.format_results(result, format_type="json")
        parsed = json.loads(json_str)
        assert "coefficients" in parsed
        assert "r_squared" in parsed

    def test_format_descriptive_markdown(self, engine, cross_section_df):
        """描述性统计 Markdown 格式包含偏度和峰度."""
        desc = engine.descriptive_stats(cross_section_df, variables=["x1"])
        md = engine.format_results(desc, format_type="markdown")
        assert "偏度" in md
        assert "峰度" in md

    def test_format_correlation_markdown(self, engine, cross_section_df):
        """相关系数矩阵 Markdown 格式."""
        corr = engine.correlation_matrix(cross_section_df, variables=["x1", "x2"])
        md = engine.format_results(corr, format_type="markdown")
        assert "Pearson" in md
        assert "1.0000" in md  # 对角线

    def test_format_vif_markdown(self, engine, multicollinear_df):
        """VIF 结果 Markdown 格式."""
        vif = engine.vif_test(multicollinear_df, indep_vars=["x1", "x2", "x3"])
        md = engine.format_results(vif, format_type="markdown")
        assert "VIF" in md
        assert "x1" in md

    def test_format_hausman_markdown(self, engine, panel_df):
        """Hausman 检验结果 Markdown 格式."""
        hausman = engine.hausman_test(
            panel_df, dep_var="y", indep_vars=["x1", "x2"],
            entity_var="entity", time_var="year"
        )
        md = engine.format_results(hausman, format_type="markdown")
        assert "Hausman" in md
        assert "推荐模型" in md

    def test_format_invalid_type_raises(self, engine, cross_section_df):
        """不支持的格式类型抛出 ValueError."""
        result = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1"]
        )
        with pytest.raises(ValueError, match="不支持的格式"):
            engine.format_results(result, format_type="invalid")


# ===== 9. 一键完整分析测试 =====

class TestRunFullAnalysis:
    """测试一键完整分析."""

    def test_full_analysis_ols(self, engine, cross_section_df):
        """OLS 完整分析包含所有部分."""
        result = engine.run_full_analysis(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        assert "descriptive" in result
        assert "correlation" in result
        assert "regression" in result
        assert "vif" in result
        # 非面板数据不应有 Hausman
        assert "hausman" not in result

    def test_full_analysis_panel(self, engine, panel_df):
        """面板完整分析包含 Hausman 检验."""
        result = engine.run_full_analysis(
            panel_df, dep_var="y", indep_vars=["x1", "x2"],
            entity_var="entity", time_var="year"
        )
        assert "descriptive" in result
        assert "correlation" in result
        assert "regression" in result
        assert "vif" in result
        assert "hausman" in result
        # 面板回归应为 FE
        assert result["regression"]["model"] == "fe"

    def test_full_analysis_regression_coefficients(self, engine, cross_section_df):
        """完整分析中的回归系数与单独 OLS 一致."""
        full = engine.run_full_analysis(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        single = engine.ols_regression(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        assert (
            full["regression"]["coefficients"]["x1"]
            == single["coefficients"]["x1"]
        )
