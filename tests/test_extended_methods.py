r"""新增实证研究方法测试。

测试范围:
== 第一部分：代码模板测试 ==
1. 面板门槛模型（Threshold, xthreg）
2. 断点回归（RDD, rdrobust）
3. 合成控制法（SCM, synth）
4. Heckman 两阶段模型
5. 动态面板 GMM（xtabond2）
6. VAR 模型（var / vargranger / irf）
7. 事件研究法（CAR 计算）
8. 逆概率加权（IPW）
9. 关键词检测（has_quantile / has_discrete / 复合 / 简单SPEC）
10. 完整模板生成（门槛 / VAR+GMM / 分位数+Logit）

== 第二部分：统计引擎测试 ==
1. 分位数回归（QuantileRegression）
2. Logit 回归
3. Probit 回归
4. Tobit 回归

运行方式:
    cd d:\副业\2026\AI论文自动化工程\scholarpilot
    $env:PYTHONPATH='src'; python -m pytest tests/test_extended_methods.py -v --tb=short
"""

from __future__ import annotations

import sys
import os

# 确保 src 目录在 Python 路径中
_src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

import numpy as np
import pandas as pd
import pytest

from scholarpilot.tools.code_template_generator import CodeTemplateGenerator
from scholarpilot.tools.stats_engine import StatsEngine


# ======================================================================
# 测试用 SPEC 文本
# ======================================================================

SPEC_THRESHOLD = """
# 论文规格
## 变量设计
- 被解释变量：debt_risk（债务风险）
- 核心解释变量：fiscal_gap（财政缺口）
- 控制变量：gdp_growth, urban_rate
## 模型设定
采用面板门槛模型（Hansen 1999），检验财政分权对债务风险的非线性影响。
门槛变量为gdp_growth。
"""

SPEC_RDD = """
# 论文规格
## 变量设计
- 被解释变量：policy_outcome（政策结果）
- 核心解释变量：treatment（处理变量）
- 控制变量：gdp_growth, pop_density
## 模型设定
采用断点回归（RDD），以人均收入为运行变量，分析政策门槛效应。
断点值为10000元。
"""

SPEC_SCM = """
# 论文规格
## 变量设计
- 被解释变量：gdp_growth
## 模型设定
采用合成控制法（SCM），以某省2016年政策为处理事件，构建反事实对照组。
"""

SPEC_HECKMAN = """
# 论文规格
## 变量设计
- 被解释变量：loan_amount（贷款金额）
- 核心解释变量：policy（政策变量）
## 模型设定
存在样本选择偏差，采用Heckman两阶段模型修正。
选择变量为是否申请贷款（apply=0/1）。
"""

SPEC_GMM = """
# 论文规格
## 变量设计
- 被解释变量：debt_risk
- 核心解释变量：fiscal_gap
## 模型设定
采用动态面板GMM（系统GMM），处理内生性问题。
"""

SPEC_VAR = """
# 论文规格
## 变量设计
- 变量：gdp_growth, debt_risk, fiscal_gap
## 模型设定
采用VAR模型分析变量间的动态关系，进行脉冲响应和方差分解分析。
做格兰杰因果检验和协整检验。
"""

SPEC_EVENT = """
# 论文规格
## 变量设计
- 被解释变量：stock_return
## 模型设定
采用事件研究法，分析政策公告对股价的影响。
计算异常收益率（AR）和累计异常收益率（CAR）。
"""

SPEC_IPW = """
# 论文规格
## 变量设计
- 被解释变量：debt_risk
## 模型设定
采用逆概率加权（IPW）和双重稳健估计，处理选择偏差。
"""

SPEC_QUANTILE = """
# 论文规格
## 变量设计
- 被解释变量：debt_risk
- 核心解释变量：fiscal_gap
## 模型设定
采用分位数回归，分析不同债务水平下财政缺口的异质性效应。
"""

SPEC_DISCRETE = """
# 论文规格
## 变量设计
- 被解释变量：default（是否违约，0/1）
- 核心解释变量：debt_ratio
## 模型设定
采用Logit和Tobit模型分析违约概率。
"""

# 复合 SPEC（同时包含多种方法）
SPEC_COMPOUND = """
# 论文规格
## 变量设计
- 被解释变量：debt_risk
- 核心解释变量：fiscal_gap
## 模型设定
采用分位数回归和Logit模型分析债务风险。
同时使用断点回归（RDD）检验非线性效应。
"""

# 简单 SPEC（不含任何新方法关键词）
SPEC_SIMPLE = """
# 论文规格
## 变量设计
- 被解释变量：debt_risk
- 核心解释变量：fiscal_gap
## 模型设定
采用固定效应面板回归模型。
"""

# VAR + GMM 复合 SPEC
SPEC_VAR_GMM = """
# 论文规格
## 变量设计
- 变量：gdp_growth, debt_risk, fiscal_gap
## 模型设定
采用VAR模型分析变量间的动态关系。
采用动态面板GMM处理内生性问题。
"""

# 分位数 + Logit 复合 SPEC
SPEC_QUANTILE_LOGIT = """
# 论文规格
## 变量设计
- 被解释变量：debt_risk
- 核心解释变量：fiscal_gap
## 模型设定
采用分位数回归和Logit模型分析债务风险。
"""


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def generator():
    """创建 CodeTemplateGenerator 实例."""
    return CodeTemplateGenerator()


@pytest.fixture
def engine():
    """创建 StatsEngine 实例."""
    return StatsEngine()


@pytest.fixture
def quantile_df():
    """生成分位数回归测试数据.

    真实模型: y = 1.0 + 2.0*x1 + 0.5*x2 + noise
    """
    np.random.seed(42)
    n = 500
    x1 = np.random.normal(0, 1, n)
    x2 = np.random.normal(0, 1, n)
    y = 1.0 + 2.0 * x1 + 0.5 * x2 + np.random.normal(0, 1, n)
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2})


@pytest.fixture
def logit_df():
    """生成 Logit/Probit 回归测试数据.

    真实模型: y = 1 if 0.5 + 1.0*x1 - 0.5*x2 + noise > 0
    """
    np.random.seed(42)
    n = 500
    x1 = np.random.normal(0, 1, n)
    x2 = np.random.normal(0, 1, n)
    latent = 0.5 + 1.0 * x1 - 0.5 * x2 + np.random.normal(0, 1, n)
    y = (latent > 0).astype(int)
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2})


@pytest.fixture
def tobit_df():
    """生成 Tobit 回归测试数据（左截断在0）.

    真实模型: y* = 1.0 + 2.0*x1 + 0.5*x2 + noise, y = max(y*, 0)
    """
    np.random.seed(42)
    n = 500
    x1 = np.random.normal(0, 1, n)
    x2 = np.random.normal(0, 1, n)
    y_raw = 1.0 + 2.0 * x1 + 0.5 * x2 + np.random.normal(0, 1, n)
    y = np.maximum(y_raw, 0)
    return pd.DataFrame({"y": y, "x1": x1, "x2": x2})


# ======================================================================
# 第一部分：代码模板测试
# ======================================================================

# ===== 1. 面板门槛模型模板测试 =====

class TestThresholdTemplate:
    """测试面板门槛模型模板生成."""

    def test_threshold_contains_xthreg(self, generator):
        """门槛模板包含 xthreg 命令."""
        v = generator._extract_variables_from_spec(SPEC_THRESHOLD)
        code = generator._generate_threshold_template(v, SPEC_THRESHOLD)
        assert "xthreg" in code

    def test_threshold_contains_thnum(self, generator):
        """门槛模板包含 thnum 关键词."""
        v = generator._extract_variables_from_spec(SPEC_THRESHOLD)
        code = generator._generate_threshold_template(v, SPEC_THRESHOLD)
        assert "thnum" in code

    def test_threshold_contains_threshold_var(self, generator):
        """门槛模板包含门槛变量（gdp_growth）."""
        v = generator._extract_variables_from_spec(SPEC_THRESHOLD)
        code = generator._generate_threshold_template(v, SPEC_THRESHOLD)
        assert "gdp_growth" in code

    def test_keyword_has_threshold(self, generator):
        """关键词检测 has_threshold=True."""
        kw = generator._detect_method_keywords(SPEC_THRESHOLD)
        assert kw["has_threshold"] is True


# ===== 2. 断点回归模板测试 =====

class TestRDDTemplate:
    """测试断点回归（RDD）模板生成."""

    def test_rdd_contains_rdrobust(self, generator):
        """RDD 模板包含 rdrobust 命令."""
        v = generator._extract_variables_from_spec(SPEC_RDD)
        code = generator._generate_rdd_template(v, SPEC_RDD)
        assert "rdrobust" in code

    def test_rdd_contains_rdbwselect(self, generator):
        """RDD 模板包含 rdbwselect 带宽选择."""
        v = generator._extract_variables_from_spec(SPEC_RDD)
        code = generator._generate_rdd_template(v, SPEC_RDD)
        assert "rdbwselect" in code

    def test_rdd_contains_rddensity(self, generator):
        """RDD 模板包含 rddensity 密度检验."""
        v = generator._extract_variables_from_spec(SPEC_RDD)
        code = generator._generate_rdd_template(v, SPEC_RDD)
        assert "rddensity" in code

    def test_keyword_has_rdd(self, generator):
        """关键词检测 has_rdd=True."""
        kw = generator._detect_method_keywords(SPEC_RDD)
        assert kw["has_rdd"] is True


# ===== 3. 合成控制法模板测试 =====

class TestSCMTemplate:
    """测试合成控制法（SCM）模板生成."""

    def test_scm_contains_synth(self, generator):
        """SCM 模板包含 synth 命令."""
        v = generator._extract_variables_from_spec(SPEC_SCM)
        code = generator._generate_scm_template(v, SPEC_SCM)
        assert "synth" in code

    def test_scm_contains_trunit_trperiod(self, generator):
        """SCM 模板包含 trunit/trperiod."""
        v = generator._extract_variables_from_spec(SPEC_SCM)
        code = generator._generate_scm_template(v, SPEC_SCM)
        assert "trunit" in code
        assert "trperiod" in code

    def test_keyword_has_scm(self, generator):
        """关键词检测 has_scm=True."""
        kw = generator._detect_method_keywords(SPEC_SCM)
        assert kw["has_scm"] is True


# ===== 4. Heckman 两阶段模型模板测试 =====

class TestHeckmanTemplate:
    """测试 Heckman 两阶段模型模板生成."""

    def test_heckman_contains_heckman_command(self, generator):
        """Heckman 模板包含 heckman 命令."""
        v = generator._extract_variables_from_spec(SPEC_HECKMAN)
        code = generator._generate_heckman_template(v, SPEC_HECKMAN)
        assert "heckman" in code

    def test_heckman_contains_select_option(self, generator):
        """Heckman 模板包含 select() 选项."""
        v = generator._extract_variables_from_spec(SPEC_HECKMAN)
        code = generator._generate_heckman_template(v, SPEC_HECKMAN)
        assert "select(" in code

    def test_keyword_has_heckman(self, generator):
        """关键词检测 has_heckman=True."""
        kw = generator._detect_method_keywords(SPEC_HECKMAN)
        assert kw["has_heckman"] is True


# ===== 5. 动态面板 GMM 模板测试 =====

class TestGMMTemplate:
    """测试动态面板 GMM 模板生成."""

    def test_gmm_contains_xtabond2(self, generator):
        """GMM 模板包含 xtabond2 命令."""
        v = generator._extract_variables_from_spec(SPEC_GMM)
        code = generator._generate_gmm_template(v)
        assert "xtabond2" in code

    def test_gmm_contains_ar_tests(self, generator):
        """GMM 模板包含 AR(1)/AR(2) 检验."""
        v = generator._extract_variables_from_spec(SPEC_GMM)
        code = generator._generate_gmm_template(v)
        assert "AR(1)" in code
        assert "AR(2)" in code

    def test_keyword_has_gmm(self, generator):
        """关键词检测 has_gmm=True."""
        kw = generator._detect_method_keywords(SPEC_GMM)
        assert kw["has_gmm"] is True


# ===== 6. VAR 模型模板测试 =====

class TestVARTemplate:
    """测试 VAR 模型模板生成."""

    def test_var_contains_var_command(self, generator):
        """VAR 模板包含 var 命令."""
        v = generator._extract_variables_from_spec(SPEC_VAR)
        code = generator._generate_var_template(v)
        assert "var " in code

    def test_var_contains_vargranger(self, generator):
        """VAR 模板包含 vargranger 格兰杰检验."""
        v = generator._extract_variables_from_spec(SPEC_VAR)
        code = generator._generate_var_template(v)
        assert "vargranger" in code

    def test_var_contains_irf(self, generator):
        """VAR 模板包含 irf 脉冲响应."""
        v = generator._extract_variables_from_spec(SPEC_VAR)
        code = generator._generate_var_template(v)
        assert "irf" in code

    def test_keyword_has_var(self, generator):
        """关键词检测 has_var=True."""
        kw = generator._detect_method_keywords(SPEC_VAR)
        assert kw["has_var"] is True


# ===== 7. 事件研究法模板测试 =====

class TestEventStudyTemplate:
    """测试事件研究法模板生成."""

    def test_event_study_contains_car(self, generator):
        """事件研究模板包含 CAR 计算."""
        v = generator._extract_variables_from_spec(SPEC_EVENT)
        code = generator._generate_event_study_template(v)
        assert "CAR" in code

    def test_event_study_contains_ar(self, generator):
        """事件研究模板包含异常收益率."""
        v = generator._extract_variables_from_spec(SPEC_EVENT)
        code = generator._generate_event_study_template(v)
        assert "异常收益率" in code
        assert "AR" in code

    def test_keyword_has_event_study(self, generator):
        """关键词检测 has_event_study=True."""
        kw = generator._detect_method_keywords(SPEC_EVENT)
        assert kw["has_event_study"] is True


# ===== 8. 逆概率加权模板测试 =====

class TestIPWTemplate:
    """测试逆概率加权（IPW）模板生成."""

    def test_ipw_contains_ipw(self, generator):
        """IPW 模板包含 ipw 计算."""
        v = generator._extract_variables_from_spec(SPEC_IPW)
        code = generator._generate_ipw_template(v)
        assert "ipw" in code

    def test_ipw_contains_probit(self, generator):
        """IPW 模板包含 probit 倾向得分估计."""
        v = generator._extract_variables_from_spec(SPEC_IPW)
        code = generator._generate_ipw_template(v)
        assert "probit" in code

    def test_keyword_has_ipw(self, generator):
        """关键词检测 has_ipw=True."""
        kw = generator._detect_method_keywords(SPEC_IPW)
        assert kw["has_ipw"] is True


# ===== 9. 关键词检测测试 =====

class TestKeywordDetection:
    """测试新增方法的关键词检测."""

    def test_has_quantile_detection(self, generator):
        """测试 has_quantile 检测."""
        kw = generator._detect_method_keywords(SPEC_QUANTILE)
        assert kw["has_quantile"] is True

    def test_has_discrete_detection(self, generator):
        """测试 has_discrete 检测."""
        kw = generator._detect_method_keywords(SPEC_DISCRETE)
        assert kw["has_discrete"] is True

    def test_compound_spec_detects_multiple(self, generator):
        """测试复合 SPEC 同时检测多种方法."""
        kw = generator._detect_method_keywords(SPEC_COMPOUND)
        assert kw["has_quantile"] is True
        assert kw["has_discrete"] is True
        assert kw["has_rdd"] is True

    def test_simple_spec_no_false_positive(self, generator):
        """测试简单 SPEC 不误报."""
        kw = generator._detect_method_keywords(SPEC_SIMPLE)
        assert kw["has_threshold"] is False
        assert kw["has_rdd"] is False
        assert kw["has_scm"] is False
        assert kw["has_heckman"] is False
        assert kw["has_gmm"] is False
        assert kw["has_var"] is False
        assert kw["has_event_study"] is False
        assert kw["has_ipw"] is False
        assert kw["has_quantile"] is False
        assert kw["has_discrete"] is False


# ===== 10. 完整模板生成测试（新增方法） =====

class TestFullTemplateWithNewMethods:
    """测试 generate_full_template 对新增方法的智能追加."""

    def test_full_template_threshold(self, generator):
        """门槛模型 SPEC 生成完整模板含门槛段落."""
        code = generator.generate_full_template(SPEC_THRESHOLD, lang="stata")
        assert "门槛" in code
        assert "xthreg" in code
        assert "thnum" in code

    def test_full_template_var_gmm(self, generator):
        """VAR+GMM 复合 SPEC 生成完整模板."""
        code = generator.generate_full_template(SPEC_VAR_GMM, lang="stata")
        # VAR 段落
        assert "vargranger" in code
        assert "irf" in code
        # GMM 段落
        assert "xtabond2" in code
        assert "AR(1)" in code or "AR(2)" in code

    def test_full_template_quantile_logit(self, generator):
        """分位数+Logit 复合 SPEC 生成完整模板."""
        code = generator.generate_full_template(SPEC_QUANTILE_LOGIT, lang="stata")
        # 分位数回归段落
        assert "qreg" in code
        # 离散选择模型段落
        assert "logit" in code.lower()
        assert "tobit" in code.lower()


# ======================================================================
# 第二部分：统计引擎测试
# ======================================================================

# ===== 1. 分位数回归测试 =====

class TestQuantileRegression:
    """测试分位数回归."""

    def test_returns_five_quantiles(self, engine, quantile_df):
        """测试返回含5个分位数结果."""
        result = engine.quantile_regression(quantile_df, "y", ["x1", "x2"])
        assert len(result["quantiles"]) == 5
        assert result["quantiles"] == [0.1, 0.25, 0.5, 0.75, 0.9]

    def test_coefficients_non_empty(self, engine, quantile_df):
        """测试系数字典非空."""
        result = engine.quantile_regression(quantile_df, "y", ["x1", "x2"])
        for q in result["quantiles"]:
            coeffs = result["coefficients"][q]
            assert len(coeffs) > 0
            assert "const" in coeffs
            assert "x1" in coeffs
            assert "x2" in coeffs

    def test_median_close_to_ols(self, engine, quantile_df):
        """测试中位数(0.5)回归系数接近OLS."""
        qr_result = engine.quantile_regression(
            quantile_df, "y", ["x1", "x2"], quantiles=[0.5]
        )
        ols_result = engine.ols_regression(quantile_df, "y", ["x1", "x2"], robust=False)
        # 中位数回归系数应与 OLS 接近（容忍度 0.2）
        for var in ["const", "x1", "x2"]:
            qr_coeff = qr_result["coefficients"][0.5][var]
            ols_coeff = ols_result["coefficients"][var]
            assert abs(qr_coeff - ols_coeff) < 0.2, (
                f"变量 {var}: 分位数回归系数 {qr_coeff} 与 OLS 系数 {ols_coeff} 差异过大"
            )

    def test_coefficient_comparison(self, engine, quantile_df):
        """测试 coefficient_comparison 字段."""
        result = engine.quantile_regression(quantile_df, "y", ["x1", "x2"])
        assert "coefficient_comparison" in result
        comp = result["coefficient_comparison"]
        # 每个变量都应有5个分位数的系数
        for var in ["const", "x1", "x2"]:
            assert var in comp
            assert len(comp[var]) == 5
            for q in result["quantiles"]:
                assert q in comp[var]

    def test_custom_quantiles(self, engine, quantile_df):
        """测试自定义分位数."""
        custom_qs = [0.2, 0.4, 0.6, 0.8]
        result = engine.quantile_regression(
            quantile_df, "y", ["x1", "x2"], quantiles=custom_qs
        )
        assert result["quantiles"] == custom_qs
        assert len(result["coefficients"]) == 4


# ===== 2. Logit 回归测试 =====

class TestLogitRegression:
    """测试 Logit 回归."""

    def test_returns_coefficients(self, engine, logit_df):
        """测试返回含 coefficients."""
        result = engine.logit_regression(logit_df, "y", ["x1", "x2"])
        assert "coefficients" in result
        assert "const" in result["coefficients"]
        assert "x1" in result["coefficients"]
        assert "x2" in result["coefficients"]

    def test_returns_pseudo_r2(self, engine, logit_df):
        """测试返回含 pseudo_r2."""
        result = engine.logit_regression(logit_df, "y", ["x1", "x2"])
        assert "pseudo_r2" in result
        assert 0 <= result["pseudo_r2"] < 1

    def test_returns_marginal_effects(self, engine, logit_df):
        """测试返回含 marginal_effects."""
        result = engine.logit_regression(logit_df, "y", ["x1", "x2"])
        assert "marginal_effects" in result
        assert len(result["marginal_effects"]) > 0
        assert "x1" in result["marginal_effects"]

    def test_returns_aic_bic(self, engine, logit_df):
        """测试返回含 aic/bic."""
        result = engine.logit_regression(logit_df, "y", ["x1", "x2"])
        assert "aic" in result
        assert "bic" in result
        assert result["aic"] > 0
        assert result["bic"] > 0

    def test_x1_coefficient_positive(self, engine, logit_df):
        """测试系数方向正确（x1系数为正）."""
        result = engine.logit_regression(logit_df, "y", ["x1", "x2"])
        # 真实模型中 x1 系数为正（1.0）
        assert result["coefficients"]["x1"] > 0


# ===== 3. Probit 回归测试 =====

class TestProbitRegression:
    """测试 Probit 回归."""

    def test_returns_coefficients(self, engine, logit_df):
        """测试返回含 coefficients."""
        result = engine.probit_regression(logit_df, "y", ["x1", "x2"])
        assert "coefficients" in result
        assert "const" in result["coefficients"]
        assert "x1" in result["coefficients"]
        assert "x2" in result["coefficients"]

    def test_returns_pseudo_r2(self, engine, logit_df):
        """测试返回含 pseudo_r2."""
        result = engine.probit_regression(logit_df, "y", ["x1", "x2"])
        assert "pseudo_r2" in result
        assert 0 <= result["pseudo_r2"] < 1

    def test_returns_marginal_effects(self, engine, logit_df):
        """测试返回含 marginal_effects."""
        result = engine.probit_regression(logit_df, "y", ["x1", "x2"])
        assert "marginal_effects" in result
        assert len(result["marginal_effects"]) > 0
        assert "x1" in result["marginal_effects"]

    def test_coefficients_same_direction_as_logit(self, engine, logit_df):
        """测试系数与 Logit 方向一致."""
        logit_result = engine.logit_regression(logit_df, "y", ["x1", "x2"])
        probit_result = engine.probit_regression(logit_df, "y", ["x1", "x2"])
        # x1 系数同为正
        assert logit_result["coefficients"]["x1"] > 0
        assert probit_result["coefficients"]["x1"] > 0
        # x2 系数同为负
        assert logit_result["coefficients"]["x2"] < 0
        assert probit_result["coefficients"]["x2"] < 0


# ===== 4. Tobit 回归测试 =====

class TestTobitRegression:
    """测试 Tobit 回归."""

    def test_returns_n_censored(self, engine, tobit_df):
        """测试返回含 n_censored."""
        result = engine.tobit_regression(tobit_df, "y", ["x1", "x2"], lower=0)
        assert "n_censored" in result
        assert result["n_censored"] > 0
        assert result["n_censored"] < 500  # 不应全部截断

    def test_censoring_left(self, engine, tobit_df):
        """测试返回含 censoring="left"."""
        result = engine.tobit_regression(tobit_df, "y", ["x1", "x2"], lower=0)
        assert result["censoring"] == "left"

    def test_coefficients_close_to_true(self, engine, tobit_df):
        """测试系数接近真实值（const=1.0, x1=2.0, x2=0.5）."""
        result = engine.tobit_regression(tobit_df, "y", ["x1", "x2"], lower=0)
        coeffs = result["coefficients"]
        # 容忍度 0.5（Tobit MLE 在有限样本下有一定偏差）
        assert abs(coeffs["const"] - 1.0) < 0.5, (
            f"截距系数 {coeffs['const']} 偏离真实值 1.0 过大"
        )
        assert abs(coeffs["x1"] - 2.0) < 0.5, (
            f"x1 系数 {coeffs['x1']} 偏离真实值 2.0 过大"
        )
        assert abs(coeffs["x2"] - 0.5) < 0.5, (
            f"x2 系数 {coeffs['x2']} 偏离真实值 0.5 过大"
        )

    def test_no_censoring_returns_none(self, engine, quantile_df):
        """测试无截断时 censoring="none"."""
        result = engine.tobit_regression(quantile_df, "y", ["x1", "x2"])
        assert result["censoring"] == "none"
        assert result["n_censored"] == 0
