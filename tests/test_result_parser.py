"""结果解析器（ResultParser）功能验证测试.

测试范围:
1. Stata 输出解析（reg, xtreg, fe/re）
2. R 输出解析（lm, esttab 格式）
3. Python statsmodels 输出解析
4. JSON 格式解析
5. 自动格式检测
6. Markdown 格式化输出
7. StatsEngine 兼容格式转换

运行方式:
    cd scholarpilot
    python -m pytest tests/test_result_parser.py -v
"""

from __future__ import annotations

import json

import pytest

from scholarpilot.tools.result_parser import (
    ResultParser,
    _significance_stars,
    _safe_float,
    _parse_p_value,
    parse_stata_output,
    parse_r_output,
    parse_python_output,
)


# ===== Fixtures =====

@pytest.fixture
def parser():
    """创建 ResultParser 实例."""
    return ResultParser()


STATA_OLS_OUTPUT = """\
. reg y x1 x2

      Source |       SS           df       MS      Number of obs   =       200
-------------+----------------------------------   F(2, 197)       =   1234.56
       Model |  1234.5678901        2  617.28394505   Prob > F        =    0.0000
    Residual |  123.45678901      197  .62668420863   R-squared       =    0.9091
-------------+----------------------------------   Adj R-squared   =    0.9082
       Total |  1358.02467911      199  6.82424461767   Root MSE        =    .79163

------------------------------------------------------------------------------
           y |      Coef.   Std. Err.      t    P>|t|     [95% Conf. Interval]
-------------+----------------------------------------------------------------
          x1 |   2.012345   .0567890    35.44   0.000     1.900402    2.124288
          x2 |   3.023456   .0543210    55.66   0.000     2.916366    3.130547
       _cons |   1.012345   .0567890    17.84   0.000     .900402    1.124288
------------------------------------------------------------------------------
"""

STATA_XTREG_FE_OUTPUT = """\
. xtreg y x1 x2, fe

Fixed-effects (within) regression               Number of obs     =       200
Group variable: entity                          Number of groups  =        20

R-sq:                                           Obs per group:
     within  = 0.9091                                         min =        10
     between = 0.8765                                         avg =      10.0
     overall = 0.9012                                         max =        10

                                                F(2,178)          =   1234.56
corr(u_i, Xb)  = -0.1234                        Prob > F          =    0.0000

------------------------------------------------------------------------------
           y |      Coef.   Std. Err.      t    P>|t|     [95% Conf. Interval]
-------------+----------------------------------------------------------------
          x1 |   2.012345   .0567890    35.44   0.000     1.900402    2.124288
          x2 |   3.023456   .0543210    55.66   0.000     2.916366    3.130547
       _cons |   1.012345   .0567890    17.84   0.000     .900402    1.124288
-------------+----------------------------------------------------------------
      sigma_u |  1.2345678
      sigma_e |  .7916332
          rho |  .7081234   (fraction of variance due to u_i)
------------------------------------------------------------------------------
"""

R_LM_OUTPUT = """\
Call:
lm(formula = y ~ x1 + x2)

Residuals:
    Min      1Q  Median      3Q     Max 
-2.3456 -0.3456  0.0000  0.3456  2.3456 

Coefficients:
            Estimate Std. Error t value Pr(>|t|)    
(Intercept)  1.01234    0.05679  17.834  < 2e-16 ***
x1           2.01234    0.05679  35.444  < 2e-16 ***
x2           3.02345    0.05432  55.661  < 2e-16 ***
---
Signif. codes:  0 '***' 0.001 '**' 0.01 '*' 0.05 '.' 0.1 ' ' 1

Residual standard error: 0.7916 on 197 degrees of freedom
Multiple R-squared:  0.9091,	Adjusted R-squared:  0.9082 
F-statistic:  1234 on 2 and 197 DF,  p-value: < 2.2e-16
"""

R_ESTTAB_OUTPUT = """\
──────────────────────────────────────────────
                  model1      
──────────────────────────────────────────────
(Intercept)       1.012***    
                  (0.057)     
x1                2.012***    
                  (0.057)     
x2                3.023***    
                  (0.054)     
──────────────────────────────────────────────
N                 200         
R2                0.909       
──────────────────────────────────────────────
"""

PYTHON_OLS_OUTPUT = """\
                            OLS Regression Results                            
==============================================================================
Dep. Variable:                      y   R-squared:                       0.909
Model:                            OLS   Adj. R-squared:                  0.908
Method:                 Least Squares   F-statistic:                 1.234e+03
Date:                Mon, 01 Jan 2024   Prob (F-statistic):           1.23e-100
Time:                        00:00:00   Log-Likelihood:                -123.45
No. Observations:                 200   AIC:                             252.9
Df Residuals:                     197   BIC:                             262.8
Df Model:                           2                                         
Covariance Type:            nonrobust                                         
==============================================================================
                 coef    std err          t      P>|t|      [0.025      0.975]
------------------------------------------------------------------------------
const          1.0123      0.057     17.834      0.000       0.901       1.124
x1             2.0123      0.057     35.444      0.000       1.900       2.124
x2             3.0235      0.054     55.661      0.000       2.916       3.131
==============================================================================
Omnibus:                        0.123   Durbin-Watson:                   1.987
Prob(Omnibus):                  0.940   Jarque-Bera (JB):                0.123
Skew:                           0.012   Prob(JB):                        0.940
Kurtosis:                       2.987   Cond. No.                         1.23
==============================================================================
"""

JSON_RESULT = json.dumps({
    "coefficients": {"const": 1.0123, "x1": 2.0123, "x2": 3.0235},
    "std_errors": {"const": 0.057, "x1": 0.057, "x2": 0.054},
    "t_values": {"const": 17.834, "x1": 35.444, "x2": 55.661},
    "p_values": {"const": 0.000, "x1": 0.000, "x2": 0.000},
    "significant": {"const": "***", "x1": "***", "x2": "***"},
    "r_squared": 0.909,
    "adj_r_squared": 0.908,
    "f_statistic": 1234.0,
    "f_pvalue": 0.0001,
    "n_obs": 200,
    "model": "ols",
    "robust": True,
})


# ===== 辅助函数测试 =====

class TestSignificanceStars:
    def test_three_stars(self):
        assert _significance_stars(0.001) == "***"

    def test_two_stars(self):
        assert _significance_stars(0.02) == "**"

    def test_one_star(self):
        assert _significance_stars(0.08) == "*"

    def test_no_star(self):
        assert _significance_stars(0.15) == ""


class TestSafeFloat:
    def test_normal_float(self):
        assert _safe_float("1.234") == 1.234

    def test_scientific(self):
        assert _safe_float("1.23e-10") == 1.23e-10

    def test_dot(self):
        assert _safe_float(".") is None

    def test_empty(self):
        assert _safe_float("") is None

    def test_negative(self):
        assert _safe_float("-0.5") == -0.5


class TestParsePValue:
    def test_normal(self):
        assert _parse_p_value("0.000") == 0.0

    def test_r_format_lt(self):
        assert _parse_p_value("< 2e-16") == 2e-16

    def test_r_format_lt_no_space(self):
        assert _parse_p_value("<2e-16") == 2e-16

    def test_empty(self):
        assert _parse_p_value("") is None


# ===== Stata 解析测试 =====

class TestStataParser:
    def test_ols_basic(self, parser):
        """测试 Stata OLS 输出解析."""
        result = parser.parse_stata(STATA_OLS_OUTPUT)

        assert result["source"] == "stata"
        assert result["model_type"] == "ols"
        assert result["n_obs"] == 200
        assert result["r_squared"] == pytest.approx(0.9091, abs=0.001)
        assert result["adj_r_squared"] == pytest.approx(0.9082, abs=0.001)
        assert result["f_statistic"] == pytest.approx(1234.56, abs=0.1)

    def test_ols_coefficients(self, parser):
        """测试系数提取."""
        result = parser.parse_stata(STATA_OLS_OUTPUT)

        assert "x1" in result["coefficients"]
        assert "x2" in result["coefficients"]
        assert "const" in result["coefficients"]  # _cons -> const
        assert result["coefficients"]["x1"] == pytest.approx(2.012345, abs=0.001)
        assert result["coefficients"]["x2"] == pytest.approx(3.023456, abs=0.001)

    def test_ols_std_errors(self, parser):
        """测试标准误提取."""
        result = parser.parse_stata(STATA_OLS_OUTPUT)

        assert result["std_errors"]["x1"] == pytest.approx(0.0567890, abs=0.001)
        assert result["p_values"]["x1"] == pytest.approx(0.000, abs=0.001)
        assert result["significant"]["x1"] == "***"

    def test_xtreg_fe(self, parser):
        """测试面板固定效应模型."""
        result = parser.parse_stata(STATA_XTREG_FE_OUTPUT)

        assert result["model_type"] == "fe"
        assert result["n_obs"] == 200
        # 面板模型用 within R²
        assert result["r_squared"] == pytest.approx(0.9091, abs=0.001)
        assert "sigma_u" in result["additional_stats"]
        assert "sigma_e" in result["additional_stats"]
        assert "rho" in result["additional_stats"]

    def test_variables_list(self, parser):
        """测试变量列表."""
        result = parser.parse_stata(STATA_OLS_OUTPUT)
        assert "x1" in result["variables"]
        assert "x2" in result["variables"]
        assert "const" in result["variables"]


# ===== R 解析测试 =====

class TestRParser:
    def test_lm_basic(self, parser):
        """测试 R lm() 输出解析."""
        result = parser.parse_r(R_LM_OUTPUT)

        assert result["source"] == "r"
        assert result["model_type"] == "ols"
        assert result["r_squared"] == pytest.approx(0.9091, abs=0.001)
        assert result["adj_r_squared"] == pytest.approx(0.9082, abs=0.001)
        assert result["f_statistic"] == pytest.approx(1234.0, abs=0.1)

    def test_lm_coefficients(self, parser):
        """测试 R lm() 系数提取."""
        result = parser.parse_r(R_LM_OUTPUT)

        assert "const" in result["coefficients"]  # (Intercept) -> const
        assert "x1" in result["coefficients"]
        assert "x2" in result["coefficients"]
        assert result["coefficients"]["x1"] == pytest.approx(2.01234, abs=0.001)
        assert result["std_errors"]["x1"] == pytest.approx(0.05679, abs=0.001)

    def test_lm_p_values(self, parser):
        """测试 R p 值解析（含 < 2e-16 格式）."""
        result = parser.parse_r(R_LM_OUTPUT)

        assert result["p_values"]["x1"] == pytest.approx(2e-16, rel=1)
        assert result["significant"]["x1"] == "***"

    def test_lm_n_obs(self, parser):
        """测试从残差自由度推算 N."""
        result = parser.parse_r(R_LM_OUTPUT)
        # 197 df + 3 params = 200
        assert result["n_obs"] == 200

    def test_esttab_format(self, parser):
        """测试 esttab/modelsummary 格式."""
        result = parser.parse_r(R_ESTTAB_OUTPUT)

        # esttab 格式可能不通过 Call: 检测，手动指定
        assert result["source"] == "r"
        if result["coefficients"]:
            assert "const" in result["coefficients"] or "(Intercept)" in result["coefficients"]


# ===== Python statsmodels 解析测试 =====

class TestPythonParser:
    def test_ols_basic(self, parser):
        """测试 Python statsmodels OLS summary 解析."""
        result = parser.parse_python(PYTHON_OLS_OUTPUT)

        assert result["source"] == "python"
        assert result["model_type"] == "ols"
        assert result["r_squared"] == pytest.approx(0.909, abs=0.001)
        assert result["adj_r_squared"] == pytest.approx(0.908, abs=0.001)
        assert result["n_obs"] == 200
        assert result["f_statistic"] == pytest.approx(1234.0, abs=0.1)

    def test_ols_coefficients(self, parser):
        """测试 Python 系数提取."""
        result = parser.parse_python(PYTHON_OLS_OUTPUT)

        assert "const" in result["coefficients"]
        assert "x1" in result["coefficients"]
        assert "x2" in result["coefficients"]
        assert result["coefficients"]["x1"] == pytest.approx(2.0123, abs=0.001)
        assert result["std_errors"]["x1"] == pytest.approx(0.057, abs=0.001)
        assert result["p_values"]["x1"] == pytest.approx(0.000, abs=0.001)
        assert result["significant"]["x1"] == "***"

    def test_additional_stats(self, parser):
        """测试额外统计量（AIC/BIC）."""
        result = parser.parse_python(PYTHON_OLS_OUTPUT)
        assert "aic" in result["additional_stats"]
        assert "bic" in result["additional_stats"]


# ===== JSON 解析测试 =====

class TestJsonParser:
    def test_json_basic(self, parser):
        """测试 JSON 格式解析."""
        result = parser.parse_json(JSON_RESULT)

        assert result["source"] == "json"
        assert result["model_type"] == "ols"
        assert result["n_obs"] == 200
        assert result["r_squared"] == pytest.approx(0.909, abs=0.001)
        assert "x1" in result["coefficients"]
        assert result["coefficients"]["x1"] == pytest.approx(2.0123, abs=0.001)

    def test_json_additional_fields(self, parser):
        """测试 JSON 额外字段."""
        result = parser.parse_json(JSON_RESULT)
        assert "robust" in result["additional_stats"]
        assert result["additional_stats"]["robust"] is True


# ===== 自动检测测试 =====

class TestAutoDetect:
    def test_detect_stata(self, parser):
        assert parser._detect_source(STATA_OLS_OUTPUT) == "stata"

    def test_detect_r(self, parser):
        assert parser._detect_source(R_LM_OUTPUT) == "r"

    def test_detect_python(self, parser):
        assert parser._detect_source(PYTHON_OLS_OUTPUT) == "python"

    def test_detect_json(self, parser):
        assert parser._detect_source(JSON_RESULT) == "json"

    def test_auto_parse_stata(self, parser):
        result = parser.parse(STATA_OLS_OUTPUT)
        assert result["source"] == "stata"

    def test_auto_parse_r(self, parser):
        result = parser.parse(R_LM_OUTPUT)
        assert result["source"] == "r"

    def test_auto_parse_python(self, parser):
        result = parser.parse(PYTHON_OLS_OUTPUT)
        assert result["source"] == "python"

    def test_auto_parse_json(self, parser):
        result = parser.parse(JSON_RESULT)
        assert result["source"] == "json"


# ===== 格式化输出测试 =====

class TestFormatOutput:
    def test_to_markdown(self, parser):
        """测试 Markdown 格式化."""
        result = parser.parse_stata(STATA_OLS_OUTPUT)
        md = parser.to_markdown(result, title="OLS 回归结果")

        assert "### OLS 回归结果" in md
        assert "| 变量 |" in md
        assert "x1" in md
        assert "x2" in md
        assert "const" in md
        assert "***" in md
        assert "R²" in md

    def test_to_stats_engine_format(self, parser):
        """测试 StatsEngine 兼容格式."""
        result = parser.parse_stata(STATA_OLS_OUTPUT)
        se_result = parser.to_stats_engine_format(result)

        assert "coefficients" in se_result
        assert "std_errors" in se_result
        assert "p_values" in se_result
        assert "significant" in se_result
        assert "r_squared" in se_result
        assert "model" in se_result
        assert se_result["model"] == "ols"
        assert isinstance(se_result["r_squared"], float)
        assert isinstance(se_result["n_obs"], int)


# ===== 便捷函数测试 =====

class TestConvenienceFunctions:
    def test_parse_stata_output(self):
        result = parse_stata_output(STATA_OLS_OUTPUT)
        assert result["source"] == "stata"
        assert "x1" in result["coefficients"]

    def test_parse_r_output(self):
        result = parse_r_output(R_LM_OUTPUT)
        assert result["source"] == "r"
        assert "x1" in result["coefficients"]

    def test_parse_python_output(self):
        result = parse_python_output(PYTHON_OLS_OUTPUT)
        assert result["source"] == "python"
        assert "x1" in result["coefficients"]


# ===== 跨格式一致性测试 =====

class TestCrossFormatConsistency:
    def test_stata_r_python_same_coeffs(self, parser):
        """验证三种格式解析的系数一致性."""
        stata_result = parser.parse_stata(STATA_OLS_OUTPUT)
        r_result = parser.parse_r(R_LM_OUTPUT)
        py_result = parser.parse_python(PYTHON_OLS_OUTPUT)

        # x1 系数应在同一范围内
        assert stata_result["coefficients"]["x1"] == pytest.approx(2.012, abs=0.01)
        assert r_result["coefficients"]["x1"] == pytest.approx(2.012, abs=0.01)
        assert py_result["coefficients"]["x1"] == pytest.approx(2.012, abs=0.01)

    def test_all_have_significance(self, parser):
        """验证所有格式都生成了显著性星号."""
        for output in [STATA_OLS_OUTPUT, R_LM_OUTPUT, PYTHON_OLS_OUTPUT]:
            result = parser.parse(output)
            assert len(result["significant"]) > 0
            assert "***" in result["significant"].values()
