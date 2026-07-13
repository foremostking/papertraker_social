"""回归结果解析器——从 Stata/R/Python 输出日志中提取结构化结果.

核心功能:
    1. 解析 Stata log/.smcl 输出（reg, xtreg, ivreg, logit, probit）
    2. 解析 R 控制台输出（lm, plm, glm, summary 输出）
    3. 解析 Python statsmodels/linearmodels summary() 输出
    4. 解析 JSON 结果文件（StatsEngine 格式）
    5. 自动检测输入格式，返回统一的 StatsEngine 兼容 dict

统一输出 schema（与 StatsEngine 兼容）:
    {
        "coefficients": {"var": float, ...},
        "std_errors": {"var": float, ...},
        "t_values": {"var": float, ...},
        "p_values": {"var": float, ...},
        "significant": {"var": "***"|"**"|"*"|"", ...},
        "r_squared": float,
        "adj_r_squared": float,
        "f_statistic": float | None,
        "f_pvalue": float | None,
        "n_obs": int,
        "model_type": "ols"|"fe"|"re"|"logit"|"probit"|"iv"|"spatial"|"unknown",
        "source": "stata"|"r"|"python"|"json",
        "variables": ["var1", "var2", ...],
        "additional_stats": {},  # 模型特定统计量
    }

使用示例::

    from scholarpilot.tools.result_parser import ResultParser

    parser = ResultParser()
    result = parser.parse(stata_log_text)
    print(result["coefficients"])
    # 或自动检测文件
    result = parser.parse_file("regression_output.log")
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["ResultParser", "parse_stata_output", "parse_r_output", "parse_python_output"]


def _significance_stars(p: float) -> str:
    """根据 p 值返回显著性星号.

    显著性水平：
        - p < 0.01 → "***"
        - p < 0.05 → "**"
        - p < 0.1  → "*"
        - 否则     → ""
    """
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.1:
        return "*"
    return ""


def _safe_float(text: str) -> float | None:
    """安全地将文本转为 float，失败返回 None.

    支持 Stata 科学计数法 (如 1.23e-100, ., -) 。
    """
    text = text.strip()
    if text in (".", "-", "", "NA", "N/A", "nan", "NaN"):
        return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def _parse_p_value(text: str) -> float | None:
    """解析 p 值文本，支持 R 的 '< 2e-16' 格式和 Stata 的 '0.000' 格式.

    Args:
        text: p 值文本，如 "0.000", "< 2e-16", "<2e-16", "0.00123".

    Returns:
        p 值 float，或 None。
    """
    text = text.strip()
    if not text:
        return None

    # R 格式: "< 2e-16" 或 "<2e-16"
    lt_match = re.match(r"<\s*([\d.eE+-]+)", text)
    if lt_match:
        val = _safe_float(lt_match.group(1))
        return val if val is not None else 0.0

    return _safe_float(text)


class ResultParser:
    """回归结果解析器.

    自动检测输入格式（Stata/R/Python/JSON），解析为统一的
    StatsEngine 兼容 dict。

    使用示例::

        parser = ResultParser()
        result = parser.parse(log_text)
        # 或指定格式
        result = parser.parse_stata(log_text)
        # 或从文件读取
        result = parser.parse_file("output.log")
    """

    # ===== 公共接口 =====

    def parse(self, text: str, source: str = "auto") -> dict[str, Any]:
        """自动检测格式并解析回归输出.

        Args:
            text: 回归输出文本.
            source: 指定来源 "stata"/"r"/"python"/"json"/"auto"（默认）.

        Returns:
            统一格式的结果字典。

        Raises:
            ValueError: 无法识别格式或解析失败。
        """
        if source == "auto":
            source = self._detect_source(text)

        if source == "stata":
            return self.parse_stata(text)
        elif source == "r":
            return self.parse_r(text)
        elif source == "python":
            return self.parse_python(text)
        elif source == "json":
            return self.parse_json(text)
        else:
            raise ValueError(
                f"无法自动识别输出格式，请手动指定 source='stata'/'r'/'python'/'json'"
            )

    def parse_file(self, file_path: str | Path, source: str = "auto") -> dict[str, Any]:
        """从文件读取并解析回归输出.

        Args:
            file_path: 文件路径.
            source: 指定来源，默认 "auto"（根据扩展名自动检测）.

        Returns:
            统一格式的结果字典。
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        text = path.read_text(encoding="utf-8", errors="replace")

        # 根据扩展名推断
        if source == "auto":
            ext = path.suffix.lower()
            if ext in (".log", ".smcl"):
                source = "stata"
            elif ext in (".r", ".rout", ".rdata"):
                source = "r"
            elif ext in (".json"):
                source = "json"
            elif ext in (".txt", ".out"):
                source = "auto"  # 仍需内容检测

        return self.parse(text, source=source)

    # ===== Stata 解析 =====

    def parse_stata(self, text: str) -> dict[str, Any]:
        """解析 Stata 回归输出.

        支持:
            - reg / regress (OLS)
            - xtreg, fe / xtreg, re (面板 FE/RE)
            - ivreg / ivregress (IV)
            - logit / probit
            - esttab / estout 格式表格

        Args:
            text: Stata 输出文本.

        Returns:
            统一格式的结果字典。
        """
        logger.debug("开始解析 Stata 输出（%d 字符）", len(text))

        result: dict[str, Any] = {
            "coefficients": {},
            "std_errors": {},
            "t_values": {},
            "p_values": {},
            "significant": {},
            "r_squared": None,
            "adj_r_squared": None,
            "f_statistic": None,
            "f_pvalue": None,
            "n_obs": None,
            "model_type": "unknown",
            "source": "stata",
            "variables": [],
            "additional_stats": {},
            "raw_text": text[:2000],  # 保留前2000字符用于调试
        }

        # 检测模型类型
        if re.search(r"Fixed-effects.*regression", text, re.I):
            result["model_type"] = "fe"
        elif re.search(r"Random-effects.*regression", text, re.I):
            result["model_type"] = "re"
        elif re.search(r"\bivreg|ivregress\b", text, re.I):
            result["model_type"] = "iv"
        elif re.search(r"\blogit\b", text, re.I):
            result["model_type"] = "logit"
        elif re.search(r"\bprobit\b", text, re.I):
            result["model_type"] = "probit"
        elif re.search(r"\breg\b|regress", text, re.I):
            result["model_type"] = "ols"

        # 解析系数表
        self._parse_stata_coefficients(text, result)

        # 解析统计量
        self._parse_stata_stats(text, result)

        # 生成显著性星号
        for var, p in result["p_values"].items():
            if p is not None:
                result["significant"][var] = _significance_stars(p)

        result["variables"] = list(result["coefficients"].keys())

        logger.info(
            "Stata 解析完成: model=%s, vars=%d, N=%s, R²=%s",
            result["model_type"],
            len(result["variables"]),
            result["n_obs"],
            result["r_squared"],
        )
        return result

    def _parse_stata_coefficients(self, text: str, result: dict) -> None:
        """解析 Stata 系数表.

        Stata 系数表格式:
            y |      Coef.   Std. Err.      t    P>|t|     [95% Conf. Interval]
        -----+----------------------------------------------------------------
           x1 |   2.012345   .0567890    35.44   0.000     1.900402    2.124288
        """
        # 匹配系数行: 变量名 | Coef Std.Err t P>|t| [CI_lower CI_upper]
        # 变量名可能含 _cons, _b[var] 等
        # 数值可能含科学计数法、前导点(.0567)
        coef_pattern = re.compile(
            r"^\s*"
            r"([a-zA-Z_][\w.\[\]]*|_cons)"  # 变量名
            r"\s*\|\s*"
            r"(-?[\d.]+(?:e[+-]?\d+)?)\s+"  # Coef
            r"(\.?[\d.]+(?:e[+-]?\d+)?)\s+"  # Std. Err.
            r"(-?[\d.]+)\s+"  # t
            r"([\d.]+)\s+"  # P>|t| or P>|z|
            r"(?:\[?[\d.]+\s+[\d.]+\]?)?"  # CI (optional)
            r"\s*$",
            re.MULTILINE,
        )

        for m in coef_pattern.finditer(text):
            var_name = m.group(1)
            if var_name == "_cons":
                var_name = "const"

            coef = _safe_float(m.group(2))
            se = _safe_float(m.group(3))
            t_val = _safe_float(m.group(4))
            p_val = _safe_float(m.group(5))

            if coef is not None:
                result["coefficients"][var_name] = coef
            if se is not None:
                result["std_errors"][var_name] = se
            if t_val is not None:
                result["t_values"][var_name] = t_val
            if p_val is not None:
                result["p_values"][var_name] = p_val

    def _parse_stata_stats(self, text: str, result: dict) -> None:
        """解析 Stata 模型统计量.

        Number of obs   =       200
        F(2, 197)       =   1234.56
        Prob > F        =    0.0000
        R-squared       =    0.9091
        Adj R-squared   =    0.9082
        """
        # N obs
        n_match = re.search(r"Number of obs\s*=\s*(\d+)", text)
        if n_match:
            result["n_obs"] = int(n_match.group(1))

        # R-squared (注意区分 within/between/overall)
        r2_match = re.search(r"R-squared\s*=\s*([\d.]+)", text)
        if r2_match:
            result["r_squared"] = _safe_float(r2_match.group(1))
        # 面板模型的 within R²
        within_match = re.search(r"within\s*=\s*([\d.]+)", text)
        if within_match and result["model_type"] == "fe":
            result["r_squared"] = _safe_float(within_match.group(1))
            result["additional_stats"]["r_squared_within"] = result["r_squared"]

        # Adj R-squared
        adj_match = re.search(r"Adj R-squared\s*=\s*([\d.]+)", text)
        if adj_match:
            result["adj_r_squared"] = _safe_float(adj_match.group(1))

        # F-statistic
        f_match = re.search(r"F\(\d+,\s*\d+\)\s*=\s*([\d.]+)", text)
        if f_match:
            result["f_statistic"] = _safe_float(f_match.group(1))

        # Prob > F
        pf_match = re.search(r"Prob > F\s*=\s*([\d.]+)", text)
        if pf_match:
            result["f_pvalue"] = _safe_float(pf_match.group(1))

        # 面板额外统计量
        sigma_u = re.search(r"sigma_u\s*\|\s*([\d.]+)", text)
        if sigma_u:
            result["additional_stats"]["sigma_u"] = _safe_float(sigma_u.group(1))
        sigma_e = re.search(r"sigma_e\s*\|\s*([\d.]+)", text)
        if sigma_e:
            result["additional_stats"]["sigma_e"] = _safe_float(sigma_e.group(1))
        rho = re.search(r"rho\s*\|\s*([\d.]+)", text)
        if rho:
            result["additional_stats"]["rho"] = _safe_float(rho.group(1))

    # ===== R 解析 =====

    def parse_r(self, text: str) -> dict[str, Any]:
        """解析 R 回归输出.

        支持:
            - lm() OLS 输出
            - plm() 面板回归输出
            - glm() logit/probit 输出
            - summary() 格式

        Args:
            text: R 控制台输出文本.

        Returns:
            统一格式的结果字典。
        """
        logger.debug("开始解析 R 输出（%d 字符）", len(text))

        result: dict[str, Any] = {
            "coefficients": {},
            "std_errors": {},
            "t_values": {},
            "p_values": {},
            "significant": {},
            "r_squared": None,
            "adj_r_squared": None,
            "f_statistic": None,
            "f_pvalue": None,
            "n_obs": None,
            "model_type": "unknown",
            "source": "r",
            "variables": [],
            "additional_stats": {},
            "raw_text": text[:2000],
        }

        # 检测模型类型
        if "plm" in text or "pooling" in text or "between" in text.lower():
            if "within" in text.lower() or "fixed" in text.lower():
                result["model_type"] = "fe"
            elif "random" in text.lower():
                result["model_type"] = "re"
            else:
                result["model_type"] = "panel"
        elif "glm" in text.lower() and ("binomial" in text.lower() or "logit" in text.lower()):
            result["model_type"] = "logit"
        elif "glm" in text.lower() and "probit" in text.lower():
            result["model_type"] = "probit"
        elif "lm(" in text.lower() or "Call:" in text:
            result["model_type"] = "ols"

        # 解析系数表
        self._parse_r_coefficients(text, result)

        # 解析统计量
        self._parse_r_stats(text, result)

        # 生成显著性星号
        for var, p in result["p_values"].items():
            if p is not None:
                result["significant"][var] = _significance_stars(p)

        result["variables"] = list(result["coefficients"].keys())

        logger.info(
            "R 解析完成: model=%s, vars=%d, N=%s, R²=%s",
            result["model_type"],
            len(result["variables"]),
            result["n_obs"],
            result["r_squared"],
        )
        return result

    def _parse_r_coefficients(self, text: str, result: dict) -> None:
        """解析 R 系数表.

        R 系数表格式:
                    Estimate Std. Error t value Pr(>|t|)
            (Intercept)  1.01234    0.05679  17.834  < 2e-16 ***
            x1           2.01234    0.05679  35.444  < 2e-16 ***
        """
        # 找到 Coefficients: 行之后的内容
        coef_section = re.search(
            r"Coefficients?:\s*\n(.*?)(?:\n---|\nSignif|\nResidual std|\Z)",
            text,
            re.DOTALL,
        )
        if not coef_section:
            # 尝试 esttab/modelsummary 格式
            self._parse_r_esttab(text, result)
            return

        coef_text = coef_section.group(1)

        # 匹配每个系数行
        # 格式: 变量名  Estimate  Std.Error  t_value  Pr(>|t|)  stars
        coef_line = re.compile(
            r"^\s*"
            r"([\w.()\[\]]+)"  # 变量名（含 (Intercept), factor(var) 等）
            r"\s+"
            r"(-?[\d.]+(?:e[+-]?\d+)?)"  # Estimate
            r"\s+"
            r"(-?[\d.]+(?:e[+-]?\d+)?)"  # Std. Error
            r"\s+"
            r"(-?[\d.]+(?:e[+-]?\d+)?)"  # t value
            r"\s+"
            r"(<\s*[\d.eE+-]+|[\d.eE+-]+)"  # Pr(>|t|) (可能含 < 号)
            r"\s*"
            r"([\*\.]*)"  # 显著性星号
            r"\s*$",
            re.MULTILINE,
        )

        for m in coef_line.finditer(coef_text):
            var_name = m.group(1)
            if var_name == "(Intercept)":
                var_name = "const"

            coef = _safe_float(m.group(2))
            se = _safe_float(m.group(3))
            t_val = _safe_float(m.group(4))
            p_val = _parse_p_value(m.group(5))

            if coef is not None:
                result["coefficients"][var_name] = coef
            if se is not None:
                result["std_errors"][var_name] = se
            if t_val is not None:
                result["t_values"][var_name] = t_val
            if p_val is not None:
                result["p_values"][var_name] = p_val

    def _parse_r_esttab(self, text: str, result: dict) -> None:
        """解析 R esttab/modelsummary 格式表格.

        格式:
            ───────────────────────────────────────
                          model1      model2
            ───────────────────────────────────────
            (Intercept)    1.012***    0.987***
                           (0.057)     (0.054)
            x1             2.012***    1.987***
                           (0.057)     (0.054)
            ───────────────────────────────────────
            N              200         200
            R2             0.909       0.912
            ───────────────────────────────────────
        """
        # 匹配 变量名 + 系数(带星号) + (标准误) 的两行模式
        lines = text.split("\n")
        i = 0
        while i < len(lines) - 1:
            line = lines[i].strip()
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""

            # 尝试匹配: 变量名 数值(星号) 模式
            coef_match = re.match(
                r"^([\w.()\[\]]+)\s+(-?[\d.]+(?:e[+-]?\d+)?)(\*{0,3})",
                line,
            )
            # 下一行是标准误: (数值)
            se_match = re.match(r"^\((-?[\d.]+(?:e[+-]?\d+)?)\)", next_line)

            if coef_match and se_match:
                var_name = coef_match.group(1)
                if var_name == "(Intercept)":
                    var_name = "const"

                coef = _safe_float(coef_match.group(2))
                se = _safe_float(se_match.group(1))

                if coef is not None:
                    result["coefficients"][var_name] = coef
                if se is not None:
                    result["std_errors"][var_name] = se
                    # 从系数和标准误计算 t 值和 p 值
                    if coef is not None and se != 0:
                        t_val = coef / se
                        result["t_values"][var_name] = round(t_val, 4)
                        # 近似 p 值（正态分布近似）
                        from scipy import stats as sp_stats
                        p_val = 2 * (1 - sp_stats.norm.cdf(abs(t_val)))
                        result["p_values"][var_name] = round(p_val, 6)

                i += 2
                continue
            i += 1

    def _parse_r_stats(self, text: str, result: dict) -> None:
        """解析 R 模型统计量.

        Multiple R-squared:  0.9091,	Adjusted R-squared:  0.9082
        F-statistic:  1234 on 2 and 197 DF,  p-value: < 2.2e-16
        Residual standard error: 0.7916 on 197 degrees of freedom
        """
        # R-squared
        r2_match = re.search(r"Multiple R-squared:\s*([\d.]+)", text)
        if r2_match:
            result["r_squared"] = _safe_float(r2_match.group(1))

        # 面板模型的 R-squared（plm 格式）
        if result["r_squared"] is None:
            r2_match2 = re.search(r"R-Squared:\s*([\d.]+)", text)
            if r2_match2:
                result["r_squared"] = _safe_float(r2_match2.group(1))

        # Adj R-squared
        adj_match = re.search(r"Adjusted R-squared:\s*([\d.]+)", text)
        if adj_match:
            result["adj_r_squared"] = _safe_float(adj_match.group(1))

        # F-statistic
        f_match = re.search(r"F-statistic:\s*([\d.]+)\s+on\s+\d+\s+and\s+(\d+)", text)
        if f_match:
            result["f_statistic"] = _safe_float(f_match.group(1))

        # p-value of F
        fp_match = re.search(r"p-value:\s*(<\s*[\d.eE+-]+|[\d.eE+-]+)", text)
        if fp_match:
            result["f_pvalue"] = _parse_p_value(fp_match.group(1))

        # Residual standard error + degrees of freedom -> N obs
        rse_match = re.search(
            r"Residual standard error:\s*[\d.]+\s+on\s+(\d+)\s+degrees of freedom",
            text,
        )
        if rse_match:
            df_residual = int(rse_match.group(1))
            # N = df_residual + num_params (const + indep_vars)
            num_params = len(result["coefficients"])
            if num_params > 0:
                result["n_obs"] = df_residual + num_params
            else:
                result["n_obs"] = df_residual + 1  # at least const

        # plm 的观察数
        n_match = re.search(r"Observations?\s*[:\s]*\s*(\d+)", text)
        if n_match and result["n_obs"] is None:
            result["n_obs"] = int(n_match.group(1))

    # ===== Python statsmodels 解析 =====

    def parse_python(self, text: str) -> dict[str, Any]:
        """解析 Python statsmodels/linearmodels summary() 输出.

        支持:
            - statsmodels OLS summary()
            - statsmodels Logit/Probit summary()
            - linearmodels PanelOLS/RandomEffects summary()

        Args:
            text: Python summary 输出文本.

        Returns:
            统一格式的结果字典。
        """
        logger.debug("开始解析 Python 输出（%d 字符）", len(text))

        result: dict[str, Any] = {
            "coefficients": {},
            "std_errors": {},
            "t_values": {},
            "p_values": {},
            "significant": {},
            "r_squared": None,
            "adj_r_squared": None,
            "f_statistic": None,
            "f_pvalue": None,
            "n_obs": None,
            "model_type": "unknown",
            "source": "python",
            "variables": [],
            "additional_stats": {},
            "raw_text": text[:2000],
        }

        # 检测模型类型
        if "PanelOLS" in text or "Panel Effects" in text:
            if "Fixed Effects" in text or "EntityEffects" in text:
                result["model_type"] = "fe"
            elif "Random Effects" in text or "RandomEffects" in text:
                result["model_type"] = "re"
            else:
                result["model_type"] = "panel"
        elif "Logit" in text:
            result["model_type"] = "logit"
        elif "Probit" in text:
            result["model_type"] = "probit"
        elif "OLS" in text:
            result["model_type"] = "ols"

        # 解析系数表
        self._parse_python_coefficients(text, result)

        # 解析统计量
        self._parse_python_stats(text, result)

        # 生成显著性星号
        for var, p in result["p_values"].items():
            if p is not None:
                result["significant"][var] = _significance_stars(p)

        result["variables"] = list(result["coefficients"].keys())

        logger.info(
            "Python 解析完成: model=%s, vars=%d, N=%s, R²=%s",
            result["model_type"],
            len(result["variables"]),
            result["n_obs"],
            result["r_squared"],
        )
        return result

    def _parse_python_coefficients(self, text: str, result: dict) -> None:
        """解析 Python statsmodels 系数表.

        格式:
                        coef    std err          t      P>|t|      [0.025      0.975]
            --------------------------------------------------------------------
            const          1.0123      0.057     17.834      0.000       0.901       1.124
            x1             2.0123      0.057     35.444      0.000       1.900       2.124
        """
        # statsmodels 系数行格式: 变量名  coef  std_err  t  P>|t|  [CI_low CI_high]
        # 变量名可能含中文、点、下划线
        coef_pattern = re.compile(
            r"^\s*"
            r"([\w.\u4e00-\u9fff]+)"  # 变量名（支持中文）
            r"\s+"
            r"(-?[\d.]+(?:e[+-]?\d+)?)"  # coef
            r"\s+"
            r"(-?[\d.]+(?:e[+-]?\d+)?)"  # std err
            r"\s+"
            r"(-?[\d.]+(?:e[+-]?\d+)?)"  # t
            r"\s+"
            r"([\d.]+|<\s*[\d.eE+-]+)"  # P>|t|
            r"(?:\s+[\d.]+\s+[\d.]+)?"  # CI (optional)
            r"\s*$",
            re.MULTILINE,
        )

        for m in coef_pattern.finditer(text):
            var_name = m.group(1)
            # 排除非变量行（如 "Model:", "Method:", 等统计标签）
            if var_name in (
                "Model:", "Method:", "Date:", "Time:", "Dep.", "Variable:",
                "No.", "Df", "Covariance", "Omnibus:", "Prob(", "Skew:",
                "Kurtosis:", "Cond.", "Log-Likelihood:", "AIC:", "BIC:",
                "R-squared:", "Adj.", "F-statistic:",
            ):
                continue

            coef = _safe_float(m.group(2))
            se = _safe_float(m.group(3))
            t_val = _safe_float(m.group(4))
            p_val = _parse_p_value(m.group(5))

            if coef is not None:
                result["coefficients"][var_name] = coef
            if se is not None:
                result["std_errors"][var_name] = se
            if t_val is not None:
                result["t_values"][var_name] = t_val
            if p_val is not None:
                result["p_values"][var_name] = p_val

    def _parse_python_stats(self, text: str, result: dict) -> None:
        """解析 Python statsmodels 模型统计量.

        R-squared:                       0.909
        Adj. R-squared:                  0.908
        F-statistic:                 1.234e+03
        Prob (F-statistic):           1.23e-100
        No. Observations:                 200
        """
        r2_match = re.search(r"R-squared:\s+([\d.eE+-]+)", text)
        if r2_match:
            result["r_squared"] = _safe_float(r2_match.group(1))

        adj_match = re.search(r"Adj\.\s*R-squared:\s+([\d.eE+-]+)", text)
        if adj_match:
            result["adj_r_squared"] = _safe_float(adj_match.group(1))

        f_match = re.search(r"F-statistic:\s+([\d.eE+-]+)", text)
        if f_match:
            result["f_statistic"] = _safe_float(f_match.group(1))

        fp_match = re.search(r"Prob \(F-statistic\):\s+([\d.eE+-]+)", text)
        if fp_match:
            result["f_pvalue"] = _safe_float(fp_match.group(1))

        n_match = re.search(r"No\.\s*Observations:\s+(\d+)", text)
        if n_match:
            result["n_obs"] = int(n_match.group(1))

        # Pseudo R² (Logit/Probit)
        pseudo_match = re.search(r"Pseudo R-squared:\s+([\d.]+)", text)
        if pseudo_match:
            result["r_squared"] = _safe_float(pseudo_match.group(1))
            result["additional_stats"]["pseudo_r2"] = result["r_squared"]

        # linearmodels 面板统计量
        within_match = re.search(r"R-squared \(Within\):\s+([\d.eE+-]+)", text)
        if within_match:
            result["r_squared"] = _safe_float(within_match.group(1))
            result["additional_stats"]["r_squared_within"] = result["r_squared"]

        # AIC / BIC
        aic_match = re.search(r"AIC:\s+([\d.eE+-]+)", text)
        if aic_match:
            result["additional_stats"]["aic"] = _safe_float(aic_match.group(1))
        bic_match = re.search(r"BIC:\s+([\d.eE+-]+)", text)
        if bic_match:
            result["additional_stats"]["bic"] = _safe_float(bic_match.group(1))

    # ===== JSON 解析 =====

    def parse_json(self, text: str) -> dict[str, Any]:
        """解析 JSON 格式结果（StatsEngine 输出）.

        Args:
            text: JSON 字符串.

        Returns:
            统一格式的结果字典（补充缺失字段）。
        """
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败: {e}")

        # 确保所有必需字段存在
        result: dict[str, Any] = {
            "coefficients": data.get("coefficients", {}),
            "std_errors": data.get("std_errors", {}),
            "t_values": data.get("t_values", {}),
            "p_values": data.get("p_values", {}),
            "significant": data.get("significant", {}),
            "r_squared": data.get("r_squared"),
            "adj_r_squared": data.get("adj_r_squared"),
            "f_statistic": data.get("f_statistic"),
            "f_pvalue": data.get("f_pvalue"),
            "n_obs": data.get("n_obs"),
            "model_type": data.get("model", "unknown"),
            "source": "json",
            "variables": list(data.get("coefficients", {}).keys()),
            "additional_stats": {},
            "raw_text": text[:2000],
        }

        # 补充显著性星号
        if not result["significant"]:
            for var, p in result["p_values"].items():
                if p is not None:
                    result["significant"][var] = _significance_stars(p)

        # 拷贝额外字段
        known_keys = set(result.keys())
        for k, v in data.items():
            if k not in known_keys:
                result["additional_stats"][k] = v

        logger.info(
            "JSON 解析完成: model=%s, vars=%d, N=%s, R²=%s",
            result["model_type"],
            len(result["variables"]),
            result["n_obs"],
            result["r_squared"],
        )
        return result

    # ===== 格式检测 =====

    def _detect_source(self, text: str) -> str:
        """自动检测输出格式.

        检测逻辑:
            1. JSON: 以 { 开头
            2. Stata: 含 "Number of obs", "R-squared =", "_cons", "P>|t|" 等标记
            3. R: 含 "Call:", "Coefficients:", "Pr(>|t|)", "Residual standard error"
            4. Python: 含 "OLS Regression Results", "statsmodels", "P>|t|", "No. Observations"

        Args:
            text: 输出文本.

        Returns:
            检测到的格式 "stata"/"r"/"python"/"json"。

        Raises:
            ValueError: 无法识别。
        """
        text_stripped = text.strip()

        # JSON 检测
        if text_stripped.startswith("{"):
            return "json"

        # Stata 特征
        stata_markers = [
            r"Number of obs\s*=",
            r"R-squared\s*=",
            r"Adj R-squared\s*=",
            r"Prob > F\s*=",
            r"_cons\s*\|",
            r"\bxtreg\b",
            r"\bivreg\b",
        ]
        if any(re.search(p, text) for p in stata_markers):
            return "stata"

        # Python statsmodels 特征
        python_markers = [
            "OLS Regression Results",
            "statsmodels",
            "No. Observations:",
            "Covariance Type:",
            "Df Residuals:",
            "Df Model:",
            "P>|t|",
            "PanelOLS",
            "RandomEffects",
        ]
        if any(marker in text for marker in python_markers):
            return "python"

        # R 特征
        r_markers = [
            "Call:",
            "Coefficients:",
            "Pr(>|t|)",
            "Residual standard error",
            "Multiple R-squared",
            "Adjusted R-squared",
            "F-statistic:",
        ]
        if any(marker in text for marker in r_markers):
            return "r"

        raise ValueError("无法自动识别输出格式")

    # ===== 格式化输出 =====

    def to_markdown(self, result: dict, title: str = "回归结果") -> str:
        """将解析结果转为 Markdown 表格.

        Args:
            result: parse() 返回的结果字典.
            title: 表格标题.

        Returns:
            Markdown 格式的回归结果表。
        """
        variables = result.get("variables", [])
        if not variables:
            return f"### {title}\n\n（无有效系数）"

        coeffs = result.get("coefficients", {})
        std_errs = result.get("std_errors", {})
        p_vals = result.get("p_values", {})
        sigs = result.get("significant", {})

        lines = [f"### {title}", "", "| 变量 | 系数 | 标准误 | p值 | 显著性 |",
                 "|------|------|--------|-----|--------|"]

        for var in variables:
            coef = coeffs.get(var, "")
            se = std_errs.get(var, "")
            p = p_vals.get(var, "")
            sig = sigs.get(var, "")

            coef_str = f"{coef:.4f}" if isinstance(coef, (int, float)) else str(coef)
            se_str = f"{se:.4f}" if isinstance(se, (int, float)) else str(se)
            p_str = f"{p:.4f}" if isinstance(p, (int, float)) else str(p)

            lines.append(f"| {var} | {coef_str} | {se_str} | {p_str} | {sig} |")

        lines.append("")
        lines.append("注：*** p<0.01, ** p<0.05, * p<0.1")

        # 模型统计量
        stats_lines = []
        if result.get("n_obs"):
            stats_lines.append(f"观测数 N = {result['n_obs']}")
        if result.get("r_squared") is not None:
            stats_lines.append(f"R² = {result['r_squared']:.4f}")
        if result.get("adj_r_squared") is not None:
            stats_lines.append(f"调整后 R² = {result['adj_r_squared']:.4f}")
        if result.get("f_statistic") is not None:
            stats_lines.append(f"F 统计量 = {result['f_statistic']:.4f}")
        if result.get("model_type") and result["model_type"] != "unknown":
            stats_lines.append(f"模型类型 = {result['model_type']}")

        if stats_lines:
            lines.append("")
            lines.append("模型统计量：" + "，".join(stats_lines))

        return "\n".join(lines)

    def to_stats_engine_format(self, result: dict) -> dict:
        """将解析结果转为 StatsEngine 兼容格式（可直接用于 format_results）.

        Args:
            result: parse() 返回的结果字典.

        Returns:
            StatsEngine 兼容的结果字典。
        """
        se_result = {
            "coefficients": result.get("coefficients", {}),
            "std_errors": result.get("std_errors", {}),
            "t_values": result.get("t_values", {}),
            "p_values": result.get("p_values", {}),
            "significant": result.get("significant", {}),
            "r_squared": result.get("r_squared"),
            "adj_r_squared": result.get("adj_r_squared"),
            "f_statistic": result.get("f_statistic"),
            "f_pvalue": result.get("f_pvalue"),
            "n_obs": result.get("n_obs"),
            "model": result.get("model_type", "ols"),
        }

        # 补充 None 值为默认
        if se_result["r_squared"] is None:
            se_result["r_squared"] = 0.0
        if se_result["n_obs"] is None:
            se_result["n_obs"] = 0

        # 合并额外统计量
        se_result.update(result.get("additional_stats", {}))

        return se_result


# ===== 模块级便捷函数 =====

def parse_stata_output(text: str) -> dict[str, Any]:
    """便捷函数：解析 Stata 输出."""
    return ResultParser().parse_stata(text)


def parse_r_output(text: str) -> dict[str, Any]:
    """便捷函数：解析 R 输出."""
    return ResultParser().parse_r(text)


def parse_python_output(text: str) -> dict[str, Any]:
    """便捷函数：解析 Python 输出."""
    return ResultParser().parse_python(text)
