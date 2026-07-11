"""中介效应与调节效应分析（MediationAnalysis）功能验证测试.

测试范围:
1. Baron & Kenny 三步法（系数正确性、中介类型判定）
2. Sobel 检验（z统计量、p值、显著性）
3. Bootstrap 中介效应检验（置信区间、显著性）
4. 调节效应分析（交互项识别、中心化）
5. 机制分析报告生成（Markdown 格式）
6. 带控制变量的中介分析
7. 边界情况与错误处理

模拟数据真实模型:
    X ~ N(0, 1)
    M = 0.5 * X + noise       (a = 0.5)
    Y = 0.3 * X + 0.4 * M + noise  (c' = 0.3, b = 0.4)
    总效应 c = c' + a*b = 0.3 + 0.5*0.4 = 0.5
    间接效应 a*b = 0.2

运行方式:
    cd scholarpilot
    $env:PYTHONPATH='src'; python -m pytest tests/test_mediation.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scholarpilot.tools.mediation_analysis import MediationAnalysis, _significance_stars
from scholarpilot.tools.stats_engine import StatsEngine


# ===== Fixtures =====

@pytest.fixture
def engine():
    """创建 StatsEngine 实例."""
    return StatsEngine()


@pytest.fixture
def ma(engine):
    """创建 MediationAnalysis 实例（复用 StatsEngine）."""
    return MediationAnalysis(engine)


@pytest.fixture
def mediation_df():
    """生成有中介效应的模拟数据（固定随机种子）.

    真实模型:
        X ~ N(0, 1)
        M = 0.5 * X + noise          (a = 0.5)
        Y = 0.3 * X + 0.4 * M + noise (c' = 0.3, b = 0.4)

    理论值:
        总效应 c = 0.3 + 0.5*0.4 = 0.5
        间接效应 a*b = 0.5 * 0.4 = 0.2
        直接效应 c' = 0.3
    """
    np.random.seed(42)
    n = 500
    x = np.random.randn(n)
    m = 0.5 * x + np.random.randn(n) * 0.3
    y = 0.3 * x + 0.4 * m + np.random.randn(n) * 0.3
    return pd.DataFrame({"X": x, "M": m, "Y": y})


@pytest.fixture
def mediation_df_with_controls():
    """生成带控制变量的中介效应模拟数据.

    真实模型:
        X ~ N(0, 1)
        C1 ~ N(0, 1), C2 ~ N(0, 1)
        M = 0.5 * X + 0.2 * C1 + noise
        Y = 0.3 * X + 0.4 * M + 0.1 * C2 + noise
    """
    np.random.seed(123)
    n = 500
    x = np.random.randn(n)
    c1 = np.random.randn(n)
    c2 = np.random.randn(n)
    m = 0.5 * x + 0.2 * c1 + np.random.randn(n) * 0.3
    y = 0.3 * x + 0.4 * m + 0.1 * c2 + np.random.randn(n) * 0.3
    return pd.DataFrame({"X": x, "M": m, "Y": y, "C1": c1, "C2": c2})


@pytest.fixture
def full_mediation_df():
    """生成完全中介效应的模拟数据（c'不显著）.

    真实模型:
        X ~ N(0, 1)
        M = 0.6 * X + noise          (a = 0.6)
        Y = 0.0 * X + 0.5 * M + noise (c' = 0, b = 0.5)
    完全中介: c显著，c'不显著，a*b显著
    """
    np.random.seed(456)
    n = 500
    x = np.random.randn(n)
    m = 0.6 * x + np.random.randn(n) * 0.2
    y = 0.5 * m + np.random.randn(n) * 0.3
    return pd.DataFrame({"X": x, "M": m, "Y": y})


@pytest.fixture
def no_mediation_df():
    """生成无中介效应的模拟数据（b不显著）.

    真实模型:
        X ~ N(0, 1)
        M = 0.5 * X + noise          (a = 0.5, 显著)
        Y = 0.5 * X + 0.0 * M + noise (b = 0, c' = 0.5)
    无中介: b不显著 → a*b不显著
    """
    np.random.seed(789)
    n = 500
    x = np.random.randn(n)
    m = 0.5 * x + np.random.randn(n) * 0.3
    y = 0.5 * x + np.random.randn(n) * 0.5
    return pd.DataFrame({"X": x, "M": m, "Y": y})


@pytest.fixture
def moderation_df():
    """生成有调节效应的模拟数据.

    真实模型:
        X ~ N(0, 1)
        W ~ N(0, 1)
        Y = 0.5 * X + 0.3 * W + 0.4 * (X*W) + noise
    交互项系数 β3 = 0.4，应显著
    """
    np.random.seed(321)
    n = 500
    x = np.random.randn(n)
    w = np.random.randn(n)
    # 中心化后相乘
    x_c = x - x.mean()
    w_c = w - w.mean()
    y = 0.5 * x + 0.3 * w + 0.4 * (x_c * w_c) + np.random.randn(n) * 0.2
    return pd.DataFrame({"X": x, "W": w, "Y": y})


@pytest.fixture
def no_moderation_df():
    """生成无调节效应的模拟数据（交互项不显著）.

    真实模型:
        X ~ N(0, 1)
        W ~ N(0, 1)
        Y = 0.5 * X + 0.3 * W + 0.0 * (X*W) + noise
    交互项系数 β3 = 0，应不显著
    使用较大噪声确保交互项不出现伪显著
    """
    np.random.seed(2024)
    n = 500
    x = np.random.randn(n)
    w = np.random.randn(n)
    y = 0.5 * x + 0.3 * w + np.random.randn(n) * 0.8
    return pd.DataFrame({"X": x, "W": w, "Y": y})


# ===== 1. 显著性星号函数测试 =====

class TestSignificanceStars:
    """测试 _significance_stars 函数."""

    def test_stars_p_less_than_001(self):
        """p < 0.01 返回 ***."""
        assert _significance_stars(0.001) == "***"
        assert _significance_stars(0.009) == "***"

    def test_stars_p_less_than_005(self):
        """0.01 <= p < 0.05 返回 **."""
        assert _significance_stars(0.01) == "**"
        assert _significance_stars(0.049) == "**"

    def test_stars_p_greater_than_01(self):
        """p >= 0.1 返回空字符串."""
        assert _significance_stars(0.1) == ""
        assert _significance_stars(0.5) == ""


# ===== 2. Baron & Kenny 三步法测试 =====

class TestBaronKenny:
    """测试 Baron & Kenny 三步法."""

    def test_bk_total_effect(self, ma, mediation_df):
        """总效应 c 接近真实值 0.5."""
        result = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        c = result["total_effect"]
        # 真实 c = 0.3 + 0.5*0.4 = 0.5
        assert abs(c - 0.5) < 0.1

    def test_bk_direct_effect(self, ma, mediation_df):
        """直接效应 c' 接近真实值 0.3."""
        result = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        c_prime = result["direct_effect"]
        # 真实 c' = 0.3
        assert abs(c_prime - 0.3) < 0.1

    def test_bk_indirect_effect(self, ma, mediation_df):
        """间接效应 a*b 接近真实值 0.2."""
        result = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        indirect = result["indirect_effect"]
        # 真实 a*b = 0.5 * 0.4 = 0.2
        assert abs(indirect - 0.2) < 0.08

    def test_bk_path_coefficients(self, ma, mediation_df):
        """路径系数 a 和 b 接近真实值."""
        result = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        # a = 0.5, b = 0.4
        assert abs(result["a"] - 0.5) < 0.1
        assert abs(result["b"] - 0.4) < 0.1

    def test_bk_partial_mediation(self, ma, mediation_df):
        """部分中介: c显著, c'显著, a*b显著."""
        result = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        assert result["mediation_type"] == "partial"

    def test_bk_full_mediation(self, ma, full_mediation_df):
        """完全中介: c显著, c'不显著, a*b显著."""
        result = ma.baron_kenny(full_mediation_df, x="X", y="Y", mediator="M")
        assert result["mediation_type"] == "full"

    def test_bk_no_mediation(self, ma, no_mediation_df):
        """无中介: b不显著 → a*b不显著."""
        result = ma.baron_kenny(no_mediation_df, x="X", y="Y", mediator="M")
        assert result["mediation_type"] == "none"

    def test_bk_with_controls(self, ma, mediation_df_with_controls):
        """带控制变量的三步法系数接近真实值."""
        result = ma.baron_kenny(
            mediation_df_with_controls,
            x="X", y="Y", mediator="M",
            controls=["C1", "C2"],
        )
        # a ≈ 0.5, b ≈ 0.4, c' ≈ 0.3
        assert abs(result["a"] - 0.5) < 0.1
        assert abs(result["b"] - 0.4) < 0.1
        assert abs(result["direct_effect"] - 0.3) < 0.1

    def test_bk_step_results_structure(self, ma, mediation_df):
        """三步法返回结构包含所有必要字段."""
        result = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        assert "step1" in result
        assert "step2" in result
        assert "step3" in result
        assert "total_effect" in result
        assert "direct_effect" in result
        assert "indirect_effect" in result
        assert "a" in result
        assert "b" in result
        assert "se_a" in result
        assert "se_b" in result
        assert "mediation_type" in result
        assert "indirect_ratio" in result

    def test_bk_indirect_ratio(self, ma, mediation_df):
        """中介效应占比 = 间接效应 / 总效应."""
        result = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        ratio = result["indirect_ratio"]
        # 真实比例 = 0.2 / 0.5 = 0.4
        assert abs(ratio - 0.4) < 0.15


# ===== 3. Sobel 检验测试 =====

class TestSobelTest:
    """测试 Sobel 检验."""

    def test_sobel_significant(self, ma, mediation_df):
        """有中介效应时 Sobel 检验显著."""
        bk = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        sobel = ma.sobel_test(
            a=bk["a"], b=bk["b"],
            se_a=bk["se_a"], se_b=bk["se_b"],
        )
        assert sobel["significant"] is True
        assert sobel["p_value"] < 0.05
        assert abs(sobel["z"]) > 1.96  # 5% 双侧临界值

    def test_sobel_z_value(self, ma):
        """Sobel z 统计量计算正确."""
        # 手动验证: a=0.5, b=0.4, se_a=0.05, se_b=0.06
        # se_indirect = sqrt(0.4^2*0.05^2 + 0.5^2*0.06^2)
        #             = sqrt(0.0004 + 0.0009) = sqrt(0.0013) ≈ 0.03606
        # z = 0.5*0.4 / 0.03606 = 0.2 / 0.03606 ≈ 5.547
        result = ma.sobel_test(a=0.5, b=0.4, se_a=0.05, se_b=0.06)
        assert abs(result["z"] - 5.547) < 0.5
        assert result["indirect_effect"] == pytest.approx(0.2, abs=0.001)

    def test_sobel_p_value(self, ma):
        """Sobel p 值在合理范围."""
        result = ma.sobel_test(a=0.5, b=0.4, se_a=0.05, se_b=0.06)
        assert 0 <= result["p_value"] <= 1
        # z 很大时 p 应极小
        assert result["p_value"] < 0.001

    def test_sobel_not_significant(self, ma):
        """间接效应为0时不显著."""
        # a=0 → a*b=0
        result = ma.sobel_test(a=0.0, b=0.4, se_a=0.05, se_b=0.06)
        assert result["significant"] is False
        assert result["z"] == pytest.approx(0.0, abs=0.01)


# ===== 4. Bootstrap 中介效应检验测试 =====

class TestBootstrapMediation:
    """测试 Bootstrap 中介效应检验."""

    def test_bootstrap_ci_excludes_zero(self, ma, mediation_df):
        """有中介效应时 Bootstrap CI 不包含0."""
        result = ma.bootstrap_mediation(
            mediation_df, x="X", y="Y", mediator="M",
            n_bootstrap=500,
        )
        assert result["significant"] is True
        # CI 不包含0: 下界 > 0 或上界 < 0
        assert result["ci_lower"] > 0 or result["ci_upper"] < 0

    def test_bootstrap_indirect_effect(self, ma, mediation_df):
        """Bootstrap 点估计接近真实值 0.2."""
        result = ma.bootstrap_mediation(
            mediation_df, x="X", y="Y", mediator="M",
            n_bootstrap=500,
        )
        assert abs(result["indirect_effect"] - 0.2) < 0.08

    def test_bootstrap_ci_bounds(self, ma, mediation_df):
        """CI 下界 < CI 上界."""
        result = ma.bootstrap_mediation(
            mediation_df, x="X", y="Y", mediator="M",
            n_bootstrap=500,
        )
        assert result["ci_lower"] < result["ci_upper"]

    def test_bootstrap_n_bootstrap(self, ma, mediation_df):
        """返回的抽样次数正确."""
        result = ma.bootstrap_mediation(
            mediation_df, x="X", y="Y", mediator="M",
            n_bootstrap=300,
        )
        assert result["n_bootstrap"] > 0
        # 应接近 300（可能有少量失败被删除）
        assert result["n_bootstrap"] >= 250

    def test_bootstrap_with_controls(self, ma, mediation_df_with_controls):
        """带控制变量的 Bootstrap 检验."""
        result = ma.bootstrap_mediation(
            mediation_df_with_controls,
            x="X", y="Y", mediator="M",
            controls=["C1", "C2"],
            n_bootstrap=300,
        )
        assert result["significant"] is True
        assert result["ci_lower"] > 0 or result["ci_upper"] < 0


# ===== 5. 调节效应分析测试 =====

class TestModerationAnalysis:
    """测试调节效应分析."""

    def test_moderation_detected(self, ma, moderation_df):
        """有调节效应时正确识别交互项显著."""
        result = ma.moderation_analysis(
            moderation_df, x="X", y="Y", moderator="W",
        )
        assert result["has_moderation"] is True
        assert result["interaction_p_value"] < 0.05

    def test_moderation_coefficient(self, ma, moderation_df):
        """交互项系数接近真实值 0.4."""
        result = ma.moderation_analysis(
            moderation_df, x="X", y="Y", moderator="W",
        )
        # 真实 β3 = 0.4（中心化后）
        assert abs(result["interaction_coefficient"] - 0.4) < 0.1

    def test_moderation_not_detected(self, ma, no_moderation_df):
        """无调节效应时正确识别交互项不显著."""
        result = ma.moderation_analysis(
            no_moderation_df, x="X", y="Y", moderator="W",
        )
        assert result["has_moderation"] is False
        assert result["interaction_p_value"] > 0.05

    def test_moderation_interaction_var_name(self, ma, moderation_df):
        """交互项变量名正确."""
        result = ma.moderation_analysis(
            moderation_df, x="X", y="Y", moderator="W",
        )
        assert result["interaction_var"] == "X_x_W"

    def test_moderation_with_controls(self, ma, mediation_df_with_controls):
        """带控制变量的调节效应分析."""
        df = mediation_df_with_controls.copy()
        df["W"] = np.random.default_rng(999).standard_normal(len(df))
        # Y += 0.3 * X * W 交互
        df["Y"] = df["Y"] + 0.3 * (df["X"] - df["X"].mean()) * (df["W"] - df["W"].mean())
        result = ma.moderation_analysis(
            df, x="X", y="Y", moderator="W",
            controls=["C1", "C2"],
        )
        assert result["has_moderation"] is True

    def test_moderation_r_squared(self, ma, moderation_df):
        """R² 在合理范围."""
        result = ma.moderation_analysis(
            moderation_df, x="X", y="Y", moderator="W",
        )
        assert 0 <= result["r_squared"] <= 1
        assert result["r_squared"] > 0.5  # 模型拟合较好


# ===== 6. 机制分析报告测试 =====

class TestGenerateReport:
    """测试机制分析报告生成."""

    def test_report_contains_title(self, ma, mediation_df):
        """报告包含标题."""
        bk = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        report = ma.generate_mechanism_report(bk)
        assert "机制分析报告" in report

    def test_report_contains_three_steps(self, ma, mediation_df):
        """报告包含三步法回归表."""
        bk = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        report = ma.generate_mechanism_report(bk)
        assert "步骤1" in report
        assert "步骤2" in report
        assert "步骤3" in report
        assert "总效应" in report
        assert "直接效应" in report

    def test_report_contains_effects_table(self, ma, mediation_df):
        """报告包含中介效应分解表."""
        bk = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        report = ma.generate_mechanism_report(bk)
        assert "中介效应分解" in report
        assert "间接效应" in report
        assert "中介效应占比" in report

    def test_report_contains_conclusion(self, ma, mediation_df):
        """报告包含结论."""
        bk = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        report = ma.generate_mechanism_report(bk)
        assert "结论" in report
        assert "中介类型" in report

    def test_report_with_sobel(self, ma, mediation_df):
        """报告包含 Sobel 检验结果."""
        bk = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        sobel = ma.sobel_test(
            a=bk["a"], b=bk["b"],
            se_a=bk["se_a"], se_b=bk["se_b"],
        )
        bk["sobel"] = sobel
        report = ma.generate_mechanism_report(bk)
        assert "Sobel" in report
        assert "z 统计量" in report

    def test_report_with_bootstrap(self, ma, mediation_df):
        """报告包含 Bootstrap 检验结果."""
        bk = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        boot = ma.bootstrap_mediation(
            mediation_df, x="X", y="Y", mediator="M",
            n_bootstrap=200,
        )
        bk["bootstrap"] = boot
        report = ma.generate_mechanism_report(bk)
        assert "Bootstrap" in report
        assert "95% CI" in report

    def test_report_markdown_format(self, ma, mediation_df):
        """报告为 Markdown 格式（含表格语法）."""
        bk = ma.baron_kenny(mediation_df, x="X", y="Y", mediator="M")
        report = ma.generate_mechanism_report(bk)
        # Markdown 表头分隔符
        assert "|------|" in report or "|---" in report
        assert "|" in report
        assert "###" in report  # Markdown 标题

    def test_report_full_mediation_conclusion(self, ma, full_mediation_df):
        """完全中介报告包含正确结论文字."""
        bk = ma.baron_kenny(full_mediation_df, x="X", y="Y", mediator="M")
        report = ma.generate_mechanism_report(bk)
        assert "完全中介" in report

    def test_report_no_mediation_conclusion(self, ma, no_mediation_df):
        """无中介报告包含正确结论文字."""
        bk = ma.baron_kenny(no_mediation_df, x="X", y="Y", mediator="M")
        report = ma.generate_mechanism_report(bk)
        assert "未发现显著的中介效应" in report


# ===== 7. 边界情况与错误处理测试 =====

class TestEdgeCases:
    """测试边界情况."""

    def test_bk_small_sample(self, ma):
        """小样本数据三步法仍能运行."""
        np.random.seed(42)
        n = 30
        x = np.random.randn(n)
        m = 0.5 * x + np.random.randn(n) * 0.3
        y = 0.3 * x + 0.4 * m + np.random.randn(n) * 0.3
        df = pd.DataFrame({"X": x, "M": m, "Y": y})
        result = ma.baron_kenny(df, x="X", y="Y", mediator="M")
        assert "total_effect" in result

    def test_moderation_invalid_variable_raises(self, ma, mediation_df):
        """不存在的变量抛出 ValueError."""
        with pytest.raises(ValueError, match="不在数据列中"):
            ma.moderation_analysis(
                mediation_df, x="X", y="Y", moderator="nonexistent",
            )

    def test_bootstrap_insufficient_data_raises(self, ma):
        """样本量过小时 Bootstrap 抛出 ValueError."""
        np.random.seed(42)
        n = 5
        x = np.random.randn(n)
        m = 0.5 * x + np.random.randn(n) * 0.3
        y = 0.3 * x + 0.4 * m + np.random.randn(n) * 0.3
        df = pd.DataFrame({"X": x, "M": m, "Y": y})
        with pytest.raises(ValueError, match="有效样本量不足"):
            ma.bootstrap_mediation(
                df, x="X", y="Y", mediator="M", n_bootstrap=100,
            )
