"""计量经济学诊断检验（EconometricDiagnostics）功能验证测试.

测试范围:
1. VIF 多重共线性检验（独立变量 VIF 低，共线性变量 VIF>10）
2. Hausman 检验（返回 recommendation 字段）
3. Breusch-Pagan 异方差检验（返回 p_value）
4. Wooldridge 面板自相关检验
5. 单位根检验（单序列 + 面板；平稳序列拒绝原假设）
6. 诊断报告生成（Markdown 格式正确）
7. 边界与异常情况

运行方式:
    cd scholarpilot
    $env:PYTHONPATH='src'; python -m pytest tests/test_diagnostics.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scholarpilot.tools.econometric_diagnostics import (
    EconometricDiagnostics,
    _significance_stars,
)


# ===== Fixtures =====


@pytest.fixture
def diag():
    """创建 EconometricDiagnostics 实例."""
    return EconometricDiagnostics()


@pytest.fixture
def cross_section_df():
    """生成交截面数据（固定随机种子）.

    真实模型: y = 1.0 + 2.0 * x1 + 3.0 * x2 + noise
    x1 和 x2 相互独立。
    """
    np.random.seed(42)
    n = 200
    x1 = np.random.randn(n)
    x2 = np.random.randn(n)
    noise = np.random.randn(n) * 0.5
    y = 1.0 + 2.0 * x1 + 3.0 * x2 + noise
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2})


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
def heteroskedastic_df():
    """生成有异方差的数据（误差方差随 x1 增大）."""
    np.random.seed(42)
    n = 300
    x1 = np.random.uniform(0, 10, n)
    x2 = np.random.randn(n)
    # 异方差：误差标准差随 x1 增大
    noise = np.random.randn(n) * x1
    y = 1.0 + 2.0 * x1 + 3.0 * x2 + noise
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2})


@pytest.fixture
def panel_df():
    """生成面板数据（固定随机种子）.

    真实模型: y = 1.0 + 2.0 * x1 + 3.0 * x2 + entity_effect + noise
    30个个体 x 15年 = 450个观测值
    """
    np.random.seed(42)
    n_entities = 30
    n_years = 15
    n = n_entities * n_years

    entity_ids = np.repeat(np.arange(n_entities), n_years)
    years = np.tile(np.arange(2000, 2000 + n_years), n_entities)

    x1 = np.random.randn(n)
    x2 = np.random.randn(n)
    entity_effects = np.repeat(np.random.randn(n_entities) * 2, n_years)
    noise = np.random.randn(n) * 0.5
    y = 1.0 + 2.0 * x1 + 3.0 * x2 + entity_effects + noise

    return pd.DataFrame(
        {
            "entity": entity_ids,
            "year": years,
            "y": y,
            "x1": x1,
            "x2": x2,
        }
    )


@pytest.fixture
def stationary_series_df():
    """生成平稳时间序列数据（白噪声）."""
    np.random.seed(42)
    n = 200
    # 平稳序列：白噪声 + 常数
    series = 5.0 + np.random.randn(n)
    return pd.DataFrame({"series": series})


@pytest.fixture
def nonstationary_series_df():
    """生成非平稳时间序列数据（随机游走）."""
    np.random.seed(42)
    n = 200
    # 随机游走：y_t = y_{t-1} + e_t，含单位根
    shocks = np.random.randn(n)
    series = np.cumsum(shocks)
    return pd.DataFrame({"series": series})


@pytest.fixture
def panel_stationary_df():
    """生成平稳面板数据（每个截面为白噪声）.

    每个截面 50 个时间观测，保证 ADF 检验有足够功效。
    """
    np.random.seed(42)
    n_entities = 20
    n_years = 50
    n = n_entities * n_years

    entity_ids = np.repeat(np.arange(n_entities), n_years)
    years = np.tile(np.arange(2000, 2000 + n_years), n_entities)
    # 每个截面平稳
    series = 5.0 + np.random.randn(n)

    return pd.DataFrame(
        {"entity": entity_ids, "year": years, "series": series}
    )


# ===== 1. VIF 多重共线性检验测试 =====


class TestVIFTest:
    """测试 VIF 多重共线性检验."""

    def test_vif_independent_vars_low(self, diag, cross_section_df):
        """独立变量的 VIF 较低（接近 1）."""
        result = diag.vif_test(cross_section_df, indep_vars=["x1", "x2"])
        # x1 和 x2 独立，VIF 应接近 1
        assert result["variables"]["x1"] < 5
        assert result["variables"]["x2"] < 5
        assert result["has_multicollinearity"] is False
        assert result["severity"] == "none"

    def test_vif_collinear_vars_high(self, diag, multicollinear_df):
        """共线性变量的 VIF > 10（严重多重共线性）."""
        result = diag.vif_test(
            multicollinear_df, indep_vars=["x1", "x2", "x3"]
        )
        # x3 ≈ 2*x1 + x2，至少有一个 VIF > 10
        assert result["max_vif"] > 10
        assert result["has_multicollinearity"] is True
        assert result["severity"] == "severe"
        assert result["significant"] is True

    def test_vif_result_fields(self, diag, cross_section_df):
        """VIF 结果包含所有必要字段."""
        result = diag.vif_test(cross_section_df, indep_vars=["x1", "x2"])
        assert "test_name" in result
        assert "variables" in result
        assert "max_vif" in result
        assert "has_multicollinearity" in result
        assert "severity" in result
        assert "p_value" in result
        assert "significant" in result
        assert "conclusion" in result
        assert "recommendation" in result
        # VIF 无 p 值
        assert result["p_value"] is None

    def test_vif_invalid_variable_raises(self, diag, cross_section_df):
        """不存在的变量抛出 ValueError."""
        with pytest.raises(ValueError, match="不在数据列中"):
            diag.vif_test(cross_section_df, indep_vars=["nonexistent"])

    def test_vif_single_var_raises(self, diag, cross_section_df):
        """单个变量无法计算 VIF，抛出 ValueError."""
        with pytest.raises(ValueError, match="至少需要 2 个"):
            diag.vif_test(cross_section_df, indep_vars=["x1"])


# ===== 2. Hausman 检验测试 =====


class TestHausmanTest:
    """测试 Hausman 检验."""

    def test_hausman_returns_recommendation(self, diag, panel_df):
        """Hausman 检验返回 recommendation 字段（fe 或 re）."""
        result = diag.hausman_test(
            panel_df,
            dep_var="y",
            indep_vars=["x1", "x2"],
            entity_var="entity",
            time_var="year",
        )
        assert "recommendation" in result
        assert result["recommendation"] in ("fe", "re")

    def test_hausman_result_fields(self, diag, panel_df):
        """Hausman 检验结果包含 p 值和显著性判断."""
        result = diag.hausman_test(
            panel_df,
            dep_var="y",
            indep_vars=["x1", "x2"],
            entity_var="entity",
            time_var="year",
        )
        assert "chi2" in result
        assert "df" in result
        assert "p_value" in result
        assert "significant" in result
        assert "conclusion" in result
        # recommendation 应为 fe 或 re
        assert result["recommendation"] in ("fe", "re")

    def test_hausman_invalid_variable_raises(self, diag, panel_df):
        """不存在的变量抛出 ValueError."""
        with pytest.raises(ValueError, match="不在数据列中"):
            diag.hausman_test(
                panel_df,
                dep_var="y",
                indep_vars=["nonexistent"],
                entity_var="entity",
                time_var="year",
            )


# ===== 3. Breusch-Pagan 异方差检验测试 =====


class TestBreuschPaganTest:
    """测试 Breusch-Pagan 异方差检验."""

    def test_bp_returns_p_value(self, diag, cross_section_df):
        """Breusch-Pagan 检验返回 p_value 字段."""
        result = diag.breusch_pagan_test(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        assert "p_value" in result
        assert isinstance(result["p_value"], float)
        assert 0 <= result["p_value"] <= 1

    def test_bp_homoskedastic_not_significant(self, diag, cross_section_df):
        """同方差数据未拒绝原假设（无异方差）."""
        result = diag.breusch_pagan_test(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        # cross_section_df 误差为常数方差，应不拒绝同方差
        assert result["has_heteroskedasticity"] is False
        assert result["significant"] is False

    def test_bp_heteroskedastic_detected(self, diag, heteroskedastic_df):
        """异方差数据被检测出异方差."""
        result = diag.breusch_pagan_test(
            heteroskedastic_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        # 误差方差随 x1 增大，应拒绝同方差
        assert result["has_heteroskedasticity"] is True
        assert result["significant"] is True
        assert result["p_value"] < 0.05

    def test_bp_result_fields(self, diag, cross_section_df):
        """Breusch-Pagan 结果包含所有必要字段."""
        result = diag.breusch_pagan_test(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        assert "lm_statistic" in result
        assert "lm_pvalue" in result
        assert "f_statistic" in result
        assert "f_pvalue" in result
        assert "conclusion" in result
        assert "recommendation" in result

    def test_bp_invalid_variable_raises(self, diag, cross_section_df):
        """不存在的变量抛出 ValueError."""
        with pytest.raises(ValueError, match="不在数据列中"):
            diag.breusch_pagan_test(
                cross_section_df, dep_var="y", indep_vars=["nonexistent"]
            )


# ===== 4. Wooldridge 面板自相关检验测试 =====


class TestWooldridgeTest:
    """测试 Wooldridge 面板自相关检验."""

    def test_wooldridge_returns_fields(self, diag, panel_df):
        """Wooldridge 检验返回所有必要字段."""
        result = diag.wooldridge_autocorrelation(
            panel_df,
            dep_var="y",
            indep_vars=["x1", "x2"],
            entity_var="entity",
            time_var="year",
        )
        assert "coefficient" in result
        assert "t_statistic" in result
        assert "p_value" in result
        assert "significant" in result
        assert "has_autocorrelation" in result
        assert "conclusion" in result
        assert "recommendation" in result

    def test_wooldridge_p_value_valid(self, diag, panel_df):
        """Wooldridge 检验 p 值在 [0, 1] 范围内."""
        result = diag.wooldridge_autocorrelation(
            panel_df,
            dep_var="y",
            indep_vars=["x1", "x2"],
            entity_var="entity",
            time_var="year",
        )
        if result["p_value"] is not None:
            assert 0 <= result["p_value"] <= 1


# ===== 5. 单位根检验测试 =====


class TestUnitRootTest:
    """测试单位根检验."""

    def test_unit_root_stationary_rejects(self, diag, stationary_series_df):
        """平稳序列拒绝原假设（is_stationary=True）."""
        result = diag.unit_root_test(
            stationary_series_df, variable="series"
        )
        assert result["is_panel"] is False
        assert result["is_stationary"] is True
        assert result["significant"] is True
        assert result["p_value"] < 0.05

    def test_unit_root_nonstationary_not_rejected(
        self, diag, nonstationary_series_df
    ):
        """非平稳序列（随机游走）不拒绝原假设（is_stationary=False）."""
        result = diag.unit_root_test(
            nonstationary_series_df, variable="series"
        )
        assert result["is_panel"] is False
        assert result["is_stationary"] is False
        assert result["p_value"] >= 0.05

    def test_unit_root_single_fields(self, diag, stationary_series_df):
        """单序列 ADF 结果包含统计量和临界值."""
        result = diag.unit_root_test(
            stationary_series_df, variable="series"
        )
        assert "statistic" in result
        assert "n_lags" in result
        assert "critical_values" in result
        assert "1%" in result["critical_values"]
        assert "5%" in result["critical_values"]
        assert "10%" in result["critical_values"]

    def test_unit_root_panel(self, diag, panel_stationary_df):
        """面板单位根检验逐截面 ADF，报告平稳比例."""
        result = diag.unit_root_test(
            panel_stationary_df,
            variable="series",
            entity_var="entity",
            time_var="year",
        )
        assert result["is_panel"] is True
        assert "cross_section_results" in result
        assert result["n_cross_sections"] == 20
        # 平稳面板，多数截面应平稳
        assert result["stationary_ratio"] > 0.5
        assert result["is_stationary"] is True

    def test_unit_root_invalid_test_type(self, diag, stationary_series_df):
        """不支持的检验方法抛出 ValueError."""
        with pytest.raises(ValueError, match="不支持的检验方法"):
            diag.unit_root_test(
                stationary_series_df, variable="series", test="kpss"
            )

    def test_unit_root_invalid_variable(self, diag, stationary_series_df):
        """不存在的变量抛出 ValueError."""
        with pytest.raises(ValueError, match="不在数据列中"):
            diag.unit_root_test(stationary_series_df, variable="nonexistent")


# ===== 6. 诊断报告生成测试 =====


class TestDiagnosticsReport:
    """测试诊断报告生成."""

    def test_report_markdown_format(self, diag, cross_section_df):
        """诊断报告为 Markdown 格式，包含标题和各检验段落."""
        vif = diag.vif_test(cross_section_df, indep_vars=["x1", "x2"])
        bp = diag.breusch_pagan_test(
            cross_section_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        report = diag.generate_diagnostics_report(
            {"vif": vif, "breusch_pagan": bp}
        )
        # Markdown 标题
        assert report.startswith("# 计量经济学诊断检验报告")
        # 各检验作为二级标题
        assert "## VIF多重共线性检验" in report
        assert "## Breusch-Pagan异方差检验" in report
        # 包含结论和建议
        assert "**结论**" in report
        assert "**建议**" in report

    def test_report_contains_summary_table(self, diag, cross_section_df):
        """报告包含汇总表."""
        vif = diag.vif_test(cross_section_df, indep_vars=["x1", "x2"])
        report = diag.generate_diagnostics_report({"vif": vif})
        assert "## 汇总" in report
        assert "| 检验 | p 值 | 显著性 | 结论 |" in report

    def test_report_full_diagnostics(self, diag, panel_df):
        """完整诊断报告包含所有检验类型."""
        vif = diag.vif_test(panel_df, indep_vars=["x1", "x2"])
        hausman = diag.hausman_test(
            panel_df,
            dep_var="y",
            indep_vars=["x1", "x2"],
            entity_var="entity",
            time_var="year",
        )
        bp = diag.breusch_pagan_test(
            panel_df, dep_var="y", indep_vars=["x1", "x2"]
        )
        wooldridge = diag.wooldridge_autocorrelation(
            panel_df,
            dep_var="y",
            indep_vars=["x1", "x2"],
            entity_var="entity",
            time_var="year",
        )
        report = diag.generate_diagnostics_report(
            {
                "vif": vif,
                "hausman": hausman,
                "breusch_pagan": bp,
                "wooldridge": wooldridge,
            }
        )
        # 包含所有检验名称
        assert "VIF" in report
        assert "Hausman" in report
        assert "Breusch-Pagan" in report
        assert "Wooldridge" in report
        # 包含推荐模型（Hausman）
        assert "推荐模型" in report

    def test_report_empty_results(self, diag):
        """空结果生成空报告提示."""
        report = diag.generate_diagnostics_report({})
        assert "暂无检验结果" in report


# ===== 7. 辅助函数测试 =====


class TestSignificanceStars:
    """测试 _significance_stars 辅助函数."""

    def test_stars_levels(self):
        """显著性星号正确分级."""
        assert _significance_stars(0.001) == "***"
        assert _significance_stars(0.04) == "**"
        assert _significance_stars(0.07) == "*"
        assert _significance_stars(0.2) == ""
        assert _significance_stars(None) == ""
