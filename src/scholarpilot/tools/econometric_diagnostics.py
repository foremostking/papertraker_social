"""计量经济学诊断检验工具集.

提供审稿人常要求的诊断检验：
    - VIF 多重共线性检验
    - Hausman 检验（FE vs RE 模型选择）
    - Breusch-Pagan 异方差检验
    - Wooldridge 面板自相关检验
    - 单位根检验（ADF，支持单序列与面板）
    - 诊断报告生成（Markdown）

设计原则：
    - 延迟导入 statsmodels / linearmodels / scipy，缺失时给出清晰提示
    - 所有检验结果含 p 值（VIF 除外，基于阈值判断）和显著性判断
    - 中文注释和 docstring
    - 与 stats_engine 互补：stats_engine 提供基础 VIF/Hausman，
      本模块提供更全面的诊断检验集合，并统一输出 p 值、结论与建议

使用示例::

    from scholarpilot.tools.econometric_diagnostics import EconometricDiagnostics

    diag = EconometricDiagnostics()
    vif = diag.vif_test(df, indep_vars=["x1", "x2", "x3"])
    bp = diag.breusch_pagan_test(df, dep_var="y", indep_vars=["x1", "x2"])
    report = diag.generate_diagnostics_report({"vif": vif, "breusch_pagan": bp})
    print(report)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["EconometricDiagnostics"]


def _significance_stars(p: float | None) -> str:
    """根据 p 值返回显著性星号.

    显著性水平：
        - p < 0.01 → "***"
        - p < 0.05 → "**"
        - p < 0.1  → "*"
        - 否则     → ""

    Args:
        p: p 值，None 时返回空字符串。

    Returns:
        显著性星号字符串。
    """
    if p is None:
        return ""
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.1:
        return "*"
    return ""


class EconometricDiagnostics:
    """计量经济学诊断检验工具集。

    提供审稿人常要求的一整套诊断检验，覆盖多重共线性、异方差、
    自相关、单位根等常见问题，并生成可直接放入论文的 Markdown 报告。

    与 ``StatsEngine`` 的关系：
        - ``StatsEngine`` 提供基础 VIF/Hausman 检验，侧重回归本身；
        - 本类提供更全面的诊断检验集合，并统一输出 p 值、显著性、
          结论与建议，便于审稿回应。

    使用示例::

        diag = EconometricDiagnostics()
        # VIF 检验
        vif = diag.vif_test(df, indep_vars=["x1", "x2", "x3"])
        # 异方差检验
        bp = diag.breusch_pagan_test(df, dep_var="y", indep_vars=["x1", "x2"])
        # 生成报告
        report = diag.generate_diagnostics_report({"vif": vif, "breusch_pagan": bp})
    """

    # ========== VIF 多重共线性检验 ==========

    def vif_test(self, df: Any, indep_vars: list[str]) -> dict:
        """VIF 多重共线性检验。

        使用 ``statsmodels.stats.outliers_influence.variance_inflation_factor``。
        阈值：VIF > 10 表示严重多重共线性，VIF > 5 需关注。

        Args:
            df: pandas DataFrame。
            indep_vars: 解释变量名列表。

        Returns:
            结果字典，格式为::

                {
                    "test_name": "VIF多重共线性检验",
                    "variables": {"x1": vif, "x2": vif},
                    "max_vif": float,
                    "has_multicollinearity": bool,   # max_vif > 10
                    "severity": "none"|"moderate"|"severe",
                    "p_value": None,                 # VIF 无 p 值，基于阈值判断
                    "significant": bool,             # 等价于 has_multicollinearity
                    "conclusion": str,
                    "recommendation": str,
                }

        Raises:
            ImportError: statsmodels 未安装。
            ValueError: 变量不存在或样本量不足。
        """
        try:
            import statsmodels.api as sm
            from statsmodels.stats.outliers_influence import (
                variance_inflation_factor,
            )
        except ImportError as e:
            raise ImportError(
                "statsmodels is required for VIF test. "
                "Install: pip install statsmodels"
            ) from e

        # 校验变量
        for var in indep_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        if len(indep_vars) < 2:
            raise ValueError("VIF 检验至少需要 2 个解释变量")

        data = df[indep_vars].dropna()
        if len(data) < len(indep_vars) + 1:
            raise ValueError(
                f"样本量不足（{len(data)}行），至少需要 {len(indep_vars) + 1} 行来计算VIF"
            )

        X = sm.add_constant(data)

        vif_values: dict[str, float] = {}
        for i, var in enumerate(indep_vars):
            # VIF 计算时跳过常数列（位置0），从位置1开始
            vif = variance_inflation_factor(X.values, i + 1)
            vif_values[var] = round(float(vif), 4)

        max_vif = max(vif_values.values()) if vif_values else 0.0
        has_multicollinearity = max_vif > 10

        # 严重程度分级
        if max_vif > 10:
            severity = "severe"
        elif max_vif > 5:
            severity = "moderate"
        else:
            severity = "none"

        # 结论与建议
        if severity == "severe":
            conclusion = (
                f"存在严重多重共线性（最大VIF={max_vif:.4f} > 10），"
                f"变量间线性依赖程度高。"
            )
            recommendation = (
                "建议：剔除高VIF变量、或采用岭回归/主成分分析/变量聚类等降维方法。"
            )
        elif severity == "moderate":
            conclusion = (
                f"存在中等程度多重共线性（最大VIF={max_vif:.4f}，5 < VIF ≤ 10），"
                f"需关注但不一定需要处理。"
            )
            recommendation = "建议：检查变量经济含义，必要时剔除冗余变量。"
        else:
            conclusion = f"未检测到严重多重共线性（最大VIF={max_vif:.4f} ≤ 5）。"
            recommendation = "无需特殊处理，模型多重共线性在可接受范围内。"

        logger.info(
            "VIF检验完成: max_vif=%.4f, severity=%s", max_vif, severity
        )

        return {
            "test_name": "VIF多重共线性检验",
            "variables": vif_values,
            "max_vif": round(max_vif, 4),
            "has_multicollinearity": has_multicollinearity,
            "severity": severity,
            "p_value": None,  # VIF 无 p 值，基于阈值判断
            "significant": has_multicollinearity,
            "conclusion": conclusion,
            "recommendation": recommendation,
        }

    # ========== Hausman 检验 ==========

    def hausman_test(
        self,
        df: Any,
        dep_var: str,
        indep_vars: list[str],
        entity_var: str,
        time_var: str,
    ) -> dict:
        """Hausman 检验（FE vs RE 模型选择）。

        H0: 随机效应一致（选 RE）；H1: 选 FE。
        实现方式：用 linearmodels 跑 FE 和 RE，比较系数差异做卡方检验。

        统计量：H = (b_FE - b_RE)' * (V_FE - V_RE)^(-1) * (b_FE - b_RE)
        服从自由度为 k（比较的系数个数）的卡方分布。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名。
            indep_vars: 解释变量名列表。
            entity_var: 个体标识变量名。
            time_var: 时间标识变量名。

        Returns:
            结果字典，格式为::

                {
                    "test_name": "Hausman检验",
                    "chi2": float,
                    "df": int,
                    "p_value": float,
                    "significant": bool,             # p < 0.05
                    "recommendation": "fe"|"re",
                    "conclusion": str,
                    "interpretation": str,
                }

            如果 linearmodels 未安装，返回提示信息。
        """
        try:
            import numpy as np
            from linearmodels.panel import PanelOLS, RandomEffects
        except ImportError:
            return {
                "test_name": "Hausman检验",
                "chi2": None,
                "df": None,
                "p_value": None,
                "significant": False,
                "recommendation": None,
                "conclusion": "linearmodels 未安装，无法执行Hausman检验。",
                "interpretation": (
                    "linearmodels 未安装，无法执行Hausman检验。"
                    "请安装: pip install linearmodels"
                ),
            }

        # 校验变量
        all_vars = [dep_var] + indep_vars + [entity_var, time_var]
        for var in all_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        # 准备面板数据
        data = df[all_vars].dropna().copy()
        if len(data) < len(indep_vars) + 2:
            raise ValueError(f"有效样本量不足（{len(data)}行）")

        data = data.set_index([entity_var, time_var])
        data = data.sort_index()

        Y = data[dep_var]

        # FE 模型（不加常数，固定效应吸收）
        X_fe = data[indep_vars]
        fe_res = PanelOLS(Y, X_fe, entity_effects=True).fit()

        # RE 模型（加常数）
        X_re = data[indep_vars].copy()
        X_re.insert(0, "const", 1.0)
        re_res = RandomEffects(Y, X_re).fit()

        # 取共同变量（FE 无 const，RE 有 const，共同变量是 indep_vars）
        common_vars = [
            v for v in fe_res.params.index if v in re_res.params.index
        ]
        if len(common_vars) == 0:
            return {
                "test_name": "Hausman检验",
                "chi2": None,
                "df": 0,
                "p_value": None,
                "significant": False,
                "recommendation": "fe",
                "conclusion": "FE和RE无共同可比较变量，默认推荐固定效应（FE）。",
                "interpretation": "FE和RE无共同可比较变量，默认推荐固定效应（FE）。",
            }

        b_fe = fe_res.params[common_vars].values
        b_re = re_res.params[common_vars].values

        # 获取方差-协方差矩阵
        v_fe = fe_res.cov.loc[common_vars, common_vars].values
        v_re = re_res.cov.loc[common_vars, common_vars].values

        # Hausman 统计量
        diff = b_fe - b_re
        diff_var = v_fe - v_re

        try:
            from numpy.linalg import pinv
            from scipy import stats as sp_stats

            # 使用伪逆以防矩阵不可逆
            chi2 = float(diff @ pinv(diff_var) @ diff)
        except Exception as e:
            logger.error("Hausman检验计算失败: %s", e)
            return {
                "test_name": "Hausman检验",
                "chi2": None,
                "df": len(common_vars),
                "p_value": None,
                "significant": False,
                "recommendation": "fe",
                "conclusion": f"Hausman检验计算失败: {e}。默认推荐固定效应（FE）。",
                "interpretation": f"Hausman检验计算失败: {e}。默认推荐固定效应（FE）。",
            }

        k = len(common_vars)

        # chi2 为负时，说明 V_FE - V_RE 非正定（RE 至少不劣于 FE），推荐 RE
        if chi2 < 0:
            conclusion = (
                f"Hausman统计量为负（chi2={chi2:.4f}），"
                f"表明随机效应不劣于固定效应，建议使用随机效应（RE）。"
            )
            logger.info("Hausman检验: chi2=%.4f(负), 推荐=re", chi2)
            return {
                "test_name": "Hausman检验",
                "chi2": round(chi2, 4),
                "df": k,
                "p_value": 1.0,
                "significant": False,
                "recommendation": "re",
                "conclusion": conclusion,
                "interpretation": conclusion,
            }

        try:
            from scipy import stats as sp_stats

            p_value = float(sp_stats.chi2.sf(chi2, k))
        except Exception:
            p_value = None

        significant = p_value is not None and p_value < 0.05

        if significant:
            recommendation = "fe"
            conclusion = (
                f"Hausman检验: chi2={chi2:.4f}, df={k}, p={p_value:.4f} < 0.05，"
                f"拒绝随机效应一致的原假设（H0），建议使用固定效应（FE）。"
            )
        else:
            recommendation = "re"
            p_str = f"{p_value:.4f}" if p_value is not None else "N/A"
            conclusion = (
                f"Hausman检验: chi2={chi2:.4f}, df={k}, p={p_str} >= 0.05，"
                f"不能拒绝随机效应一致的原假设（H0），建议使用随机效应（RE）。"
            )

        logger.info(
            "Hausman检验完成: chi2=%.4f, p=%s, 推荐=%s",
            chi2,
            p_str,
            recommendation,
        )

        return {
            "test_name": "Hausman检验",
            "chi2": round(chi2, 4),
            "df": k,
            "p_value": round(p_value, 4) if p_value is not None else None,
            "significant": significant,
            "recommendation": recommendation,
            "conclusion": conclusion,
            "interpretation": conclusion,
        }

    # ========== Breusch-Pagan 异方差检验 ==========

    def breusch_pagan_test(
        self, df: Any, dep_var: str, indep_vars: list[str]
    ) -> dict:
        """Breusch-Pagan 异方差检验。

        使用 ``statsmodels.stats.diagnostic.het_breuschpagan``。
        H0: 同方差；拒绝则存在异方差，建议用稳健标准误。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名。
            indep_vars: 解释变量名列表。

        Returns:
            结果字典，格式为::

                {
                    "test_name": "Breusch-Pagan异方差检验",
                    "lm_statistic": float,        # LM 统计量
                    "lm_pvalue": float,
                    "f_statistic": float,
                    "f_pvalue": float,
                    "p_value": float,             # 统一为 lm_pvalue
                    "significant": bool,          # p < 0.05 拒绝同方差
                    "has_heteroskedasticity": bool,
                    "conclusion": str,
                    "recommendation": str,
                }

        Raises:
            ImportError: statsmodels 未安装。
            ValueError: 变量不存在或样本量不足。
        """
        try:
            import statsmodels.api as sm
            from statsmodels.stats.diagnostic import het_breuschpagan
        except ImportError as e:
            raise ImportError(
                "statsmodels is required for Breusch-Pagan test. "
                "Install: pip install statsmodels"
            ) from e

        # 校验变量
        all_vars = [dep_var] + indep_vars
        for var in all_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        data = df[all_vars].dropna()
        if len(data) < len(indep_vars) + 2:
            raise ValueError(
                f"有效样本量不足（{len(data)}行），至少需要 {len(indep_vars) + 2} 行"
            )

        # OLS 回归获取残差
        Y = data[dep_var]
        X = sm.add_constant(data[indep_vars])
        ols_res = sm.OLS(Y, X).fit()
        residuals = ols_res.resid

        # BP 检验
        lm, lm_pvalue, f_value, f_pvalue = het_breuschpagan(residuals, X)

        # 转为 Python 原生类型，避免 numpy 布尔值（np.bool_）
        has_hetero = bool(float(lm_pvalue) < 0.05)
        significant = has_hetero

        if has_hetero:
            conclusion = (
                f"Breusch-Pagan检验: LM={lm:.4f}, p={lm_pvalue:.4f} < 0.05，"
                f"拒绝同方差原假设，存在异方差。"
            )
            recommendation = (
                "建议：使用稳健标准误（HC1/HC3）或进行变量变换（如对数变换）。"
            )
        else:
            conclusion = (
                f"Breusch-Pagan检验: LM={lm:.4f}, p={lm_pvalue:.4f} >= 0.05，"
                f"不能拒绝同方差原假设，未发现显著异方差。"
            )
            recommendation = "无需特殊处理，普通OLS标准误可用。"

        logger.info(
            "Breusch-Pagan检验完成: LM=%.4f, p=%.4f, hetero=%s",
            lm,
            lm_pvalue,
            has_hetero,
        )

        return {
            "test_name": "Breusch-Pagan异方差检验",
            "lm_statistic": round(float(lm), 4),
            "lm_pvalue": round(float(lm_pvalue), 4),
            "f_statistic": round(float(f_value), 4),
            "f_pvalue": round(float(f_pvalue), 4),
            "p_value": round(float(lm_pvalue), 4),
            "significant": significant,
            "has_heteroskedasticity": has_hetero,
            "conclusion": conclusion,
            "recommendation": recommendation,
        }

    # ========== Wooldridge 面板自相关检验 ==========

    def wooldridge_autocorrelation(
        self,
        df: Any,
        dep_var: str,
        indep_vars: list[str],
        entity_var: str,
        time_var: str,
    ) -> dict:
        """Wooldridge 面板自相关检验。

        简化实现：对残差做一阶差分后回归，检验差分残差的系数是否显著不为 -0.5。
        H0: 无一阶自相关（差分残差系数 = -0.5）。

        实现步骤：
            1. 跑面板固定效应回归，获取残差；
            2. 对残差按个体做一阶差分；
            3. 将差分残差对其自身滞后项回归；
            4. 检验系数是否显著偏离 -0.5（t 检验）。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名。
            indep_vars: 解释变量名列表。
            entity_var: 个体标识变量名。
            time_var: 时间标识变量名。

        Returns:
            结果字典，格式为::

                {
                    "test_name": "Wooldridge面板自相关检验",
                    "coefficient": float,        # 差分残差回归系数
                    "t_statistic": float,        # 检验 coef=-0.5 的 t 统计量
                    "p_value": float,
                    "significant": bool,         # p < 0.05 拒绝无自相关
                    "has_autocorrelation": bool,
                    "conclusion": str,
                    "recommendation": str,
                }

            如果 linearmodels 未安装，返回提示信息。
        """
        try:
            import statsmodels.api as sm
            from linearmodels.panel import PanelOLS
        except ImportError:
            return {
                "test_name": "Wooldridge面板自相关检验",
                "coefficient": None,
                "t_statistic": None,
                "p_value": None,
                "significant": False,
                "has_autocorrelation": False,
                "conclusion": "linearmodels 未安装，无法执行Wooldridge检验。",
                "recommendation": "请安装: pip install linearmodels",
            }

        # 校验变量
        all_vars = [dep_var] + indep_vars + [entity_var, time_var]
        for var in all_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        data = df[all_vars].dropna().copy()
        if len(data) < len(indep_vars) + 2:
            raise ValueError(f"有效样本量不足（{len(data)}行）")

        data = data.set_index([entity_var, time_var])
        data = data.sort_index()

        # FE 回归获取残差
        Y = data[dep_var]
        X = data[indep_vars]
        fe_res = PanelOLS(Y, X, entity_effects=True).fit()
        residuals = fe_res.resids

        # 残差按个体做一阶差分
        resid_df = residuals.to_frame("resid")
        resid_df["d_resid"] = resid_df.groupby(level=0)["resid"].diff()
        resid_df["lag_d_resid"] = resid_df.groupby(level=0)["d_resid"].shift(1)

        # 删除缺失值
        reg_data = resid_df[["d_resid", "lag_d_resid"]].dropna()
        if len(reg_data) < 3:
            return {
                "test_name": "Wooldridge面板自相关检验",
                "coefficient": None,
                "t_statistic": None,
                "p_value": None,
                "significant": False,
                "has_autocorrelation": False,
                "conclusion": "差分残差有效观测数不足，无法执行检验。",
                "recommendation": "请增加面板时间维度。",
            }

        # 回归：d_resid ~ lag_d_resid
        Y_diff = reg_data["d_resid"]
        X_diff = sm.add_constant(reg_data[["lag_d_resid"]])
        model = sm.OLS(Y_diff, X_diff).fit()

        rho = float(model.params["lag_d_resid"])
        se = float(model.bse["lag_d_resid"])

        # 检验 H0: rho = -0.5
        # t = (rho - (-0.5)) / se = (rho + 0.5) / se
        if se == 0:
            t_stat = 0.0
            p_value = 1.0
        else:
            t_stat = (rho + 0.5) / se
            try:
                from scipy import stats as sp_stats

                dfree = int(model.df_resid)
                p_value = float(2 * sp_stats.t.sf(abs(t_stat), dfree))
            except Exception:
                p_value = None

        has_autocorr = p_value is not None and p_value < 0.05
        significant = has_autocorr

        if has_autocorr:
            conclusion = (
                f"Wooldridge检验: 系数={rho:.4f}, t={t_stat:.4f}, "
                f"p={p_value:.4f} < 0.05，拒绝无一阶自相关原假设，"
                f"存在一阶自相关。"
            )
            recommendation = (
                "建议：使用聚类稳健标准误（按个体聚类）或采用AR(1)模型。"
            )
        else:
            p_str = f"{p_value:.4f}" if p_value is not None else "N/A"
            conclusion = (
                f"Wooldridge检验: 系数={rho:.4f}, t={t_stat:.4f}, "
                f"p={p_str} >= 0.05，不能拒绝无一阶自相关原假设，"
                f"未发现显著一阶自相关。"
            )
            recommendation = "无需特殊处理，标准误无需修正自相关。"

        logger.info(
            "Wooldridge检验完成: rho=%.4f, t=%.4f, p=%s, autocorr=%s",
            rho,
            t_stat,
            p_str,
            has_autocorr,
        )

        return {
            "test_name": "Wooldridge面板自相关检验",
            "coefficient": round(rho, 4),
            "t_statistic": round(t_stat, 4),
            "p_value": round(p_value, 4) if p_value is not None else None,
            "significant": significant,
            "has_autocorrelation": has_autocorr,
            "conclusion": conclusion,
            "recommendation": recommendation,
        }

    # ========== 单位根检验 ==========

    def unit_root_test(
        self,
        df: Any,
        variable: str,
        entity_var: str | None = None,
        time_var: str | None = None,
        test: str = "adf",
    ) -> dict:
        """单位根检验。

        - 单序列：使用 ``statsmodels.tsa.stattools.adfuller``。
        - 面板：对每个截面分别做 ADF 检验，报告通过的截面比例。

        H0: 有单位根（不平稳）；拒绝则平稳。

        Args:
            df: pandas DataFrame。
            variable: 待检验变量名。
            entity_var: 个体标识变量名。提供且提供 time_var 时做面板检验。
            time_var: 时间标识变量名。提供且提供 entity_var 时做面板检验。
            test: 检验方法，目前仅支持 "adf"（默认）。

        Returns:
            结果字典。

            单序列格式::

                {
                    "test_name": "单位根检验(ADF)",
                    "test_type": "adf",
                    "is_panel": False,
                    "statistic": float,
                    "p_value": float,
                    "significant": bool,          # 拒绝原假设=平稳
                    "is_stationary": bool,
                    "n_lags": int,
                    "critical_values": {...},
                    "conclusion": str,
                    "recommendation": str,
                }

            面板格式额外含::

                {
                    "is_panel": True,
                    "cross_section_results": [...],
                    "n_cross_sections": int,
                    "n_stationary": int,
                    "stationary_ratio": float,
                }

        Raises:
            ImportError: statsmodels 未安装。
            ValueError: 变量不存在、检验方法不支持或样本量不足。
        """
        try:
            from statsmodels.tsa.stattools import adfuller
        except ImportError as e:
            raise ImportError(
                "statsmodels is required for unit root test. "
                "Install: pip install statsmodels"
            ) from e

        if test != "adf":
            raise ValueError(
                f"不支持的检验方法: {test}，目前仅支持: adf"
            )

        if variable not in df.columns:
            raise ValueError(f"变量 '{variable}' 不在数据列中")

        # 判断单序列还是面板
        is_panel = entity_var is not None and time_var is not None

        if not is_panel:
            return self._adf_single(df, variable, adfuller)

        # 面板单位根检验：逐截面 ADF
        if entity_var not in df.columns:
            raise ValueError(f"变量 '{entity_var}' 不在数据列中")
        if time_var not in df.columns:
            raise ValueError(f"变量 '{time_var}' 不在数据列中")

        data = df[[variable, entity_var, time_var]].dropna()
        entities = data[entity_var].unique()

        cross_results: list[dict] = []
        n_stationary = 0
        n_valid = 0

        for ent in entities:
            sub = data[data[entity_var] == ent].sort_values(time_var)
            series = sub[variable]
            if len(series) < 10:
                logger.warning(
                    "截面 %s 样本量不足（%d），跳过ADF检验", ent, len(series)
                )
                cross_results.append(
                    {
                        "entity": ent,
                        "statistic": None,
                        "p_value": None,
                        "is_stationary": False,
                        "note": f"样本量不足（{len(series)}）",
                    }
                )
                continue

            try:
                result = adfuller(series, autolag="AIC")
                stat = float(result[0])
                p = float(result[1])
                statio = p < 0.05
                if statio:
                    n_stationary += 1
                n_valid += 1
                cross_results.append(
                    {
                        "entity": ent,
                        "statistic": round(stat, 4),
                        "p_value": round(p, 4),
                        "is_stationary": statio,
                    }
                )
            except Exception as e:
                logger.warning("截面 %s ADF检验失败: %s", ent, e)
                cross_results.append(
                    {
                        "entity": ent,
                        "statistic": None,
                        "p_value": None,
                        "is_stationary": False,
                        "note": f"检验失败: {e}",
                    }
                )

        total = len(cross_results)
        ratio = n_stationary / total if total > 0 else 0.0

        # 整体判断：多数截面平稳则视为平稳
        is_stationary = ratio >= 0.5

        if is_stationary:
            conclusion = (
                f"面板单位根检验: 共 {total} 个截面，{n_stationary} 个拒绝单位根"
                f"（平稳比例={ratio:.1%}），整体视为平稳。"
            )
            recommendation = "序列平稳，可直接用于回归，无需差分。"
        else:
            conclusion = (
                f"面板单位根检验: 共 {total} 个截面，{n_stationary} 个拒绝单位根"
                f"（平稳比例={ratio:.1%}），整体存在单位根。"
            )
            recommendation = (
                "建议：对变量做一阶差分后再回归，或使用协整方法。"
            )

        logger.info(
            "面板ADF检验完成: %d/%d 截面平稳, ratio=%.2f",
            n_stationary,
            total,
            ratio,
        )

        return {
            "test_name": "单位根检验(ADF-面板)",
            "test_type": "adf",
            "is_panel": True,
            "statistic": None,  # 面板无单一统计量
            "p_value": None,
            "significant": is_stationary,
            "is_stationary": is_stationary,
            "cross_section_results": cross_results,
            "n_cross_sections": total,
            "n_stationary": n_stationary,
            "stationary_ratio": round(ratio, 4),
            "conclusion": conclusion,
            "recommendation": recommendation,
        }

    def _adf_single(self, df: Any, variable: str, adfuller_fn: Any) -> dict:
        """单序列 ADF 单位根检验。

        Args:
            df: pandas DataFrame。
            variable: 变量名。
            adfuller_fn: adfuller 函数。

        Returns:
            单序列 ADF 检验结果字典。
        """
        series = df[variable].dropna()
        if len(series) < 10:
            raise ValueError(
                f"样本量不足（{len(series)}行），ADF检验至少需要 10 行"
            )

        result = adfuller_fn(series, autolag="AIC")
        adf_stat = float(result[0])
        p_value = float(result[1])
        n_lags = int(result[2])
        n_obs = int(result[3])
        critical_values = {
            k: round(float(v), 4) for k, v in result[4].items()
        }

        is_stationary = p_value < 0.05
        significant = is_stationary

        if is_stationary:
            conclusion = (
                f"ADF检验: 统计量={adf_stat:.4f}, p={p_value:.4f} < 0.05，"
                f"拒绝有单位根原假设，序列平稳。"
            )
            recommendation = "序列平稳，可直接用于回归，无需差分。"
        else:
            conclusion = (
                f"ADF检验: 统计量={adf_stat:.4f}, p={p_value:.4f} >= 0.05，"
                f"不能拒绝有单位根原假设，序列不平稳。"
            )
            recommendation = (
                "建议：对变量做一阶差分后再回归，或使用协整方法。"
            )

        logger.info(
            "ADF检验完成(%s): stat=%.4f, p=%.4f, stationary=%s",
            variable,
            adf_stat,
            p_value,
            is_stationary,
        )

        return {
            "test_name": "单位根检验(ADF)",
            "test_type": "adf",
            "is_panel": False,
            "variable": variable,
            "statistic": round(adf_stat, 4),
            "p_value": round(p_value, 4),
            "significant": significant,
            "is_stationary": is_stationary,
            "n_lags": n_lags,
            "n_obs": n_obs,
            "critical_values": critical_values,
            "conclusion": conclusion,
            "recommendation": recommendation,
        }

    # ========== 诊断报告生成 ==========

    def generate_diagnostics_report(self, results: dict) -> str:
        """生成诊断报告（Markdown）。

        每项检验输出：检验名称、统计量、p 值、结论、建议。

        Args:
            results: 检验结果字典，键为检验标识（如 "vif"），值为各检验方法
                返回的结果字典。例如::

                    {
                        "vif": diag.vif_test(...),
                        "hausman": diag.hausman_test(...),
                        "breusch_pagan": diag.breusch_pagan_test(...),
                    }

        Returns:
            Markdown 格式的诊断报告字符串。
        """
        lines = ["# 计量经济学诊断检验报告", ""]

        if not results:
            lines.append("（暂无检验结果）")
            return "\n".join(lines)

        for key, result in results.items():
            if not isinstance(result, dict):
                logger.warning("检验结果 '%s' 不是字典，跳过", key)
                continue

            lines.extend(self._format_test_section(key, result))
            lines.append("")

        # 汇总表
        lines.append("---")
        lines.append("")
        lines.append("## 汇总")
        lines.append("")
        lines.append("| 检验 | p 值 | 显著性 | 结论 |")
        lines.append("|------|------|--------|------|")
        for key, result in results.items():
            if not isinstance(result, dict):
                continue
            test_name = result.get("test_name", key)
            p_value = result.get("p_value")
            p_str = (
                f"{p_value:.4f}" if isinstance(p_value, (int, float)) else "N/A"
            )
            sig = _significance_stars(p_value) if p_value is not None else ""
            # 简短结论
            if result.get("has_multicollinearity"):
                brief = "存在多重共线性"
            elif result.get("has_heteroskedasticity"):
                brief = "存在异方差"
            elif result.get("has_autocorrelation"):
                brief = "存在自相关"
            elif result.get("recommendation") == "fe":
                brief = "建议FE"
            elif result.get("recommendation") == "re":
                brief = "建议RE"
            elif "is_stationary" in result:
                brief = "平稳" if result["is_stationary"] else "不平稳"
            else:
                brief = "见详情"
            lines.append(f"| {test_name} | {p_str} | {sig} | {brief} |")

        lines.append("")
        lines.append("注：*** p<0.01, ** p<0.05, * p<0.1。VIF 基于阈值判断，无 p 值。")

        return "\n".join(lines)

    def _format_test_section(self, key: str, result: dict) -> list[str]:
        """格式化单个检验的 Markdown 段落。

        Args:
            key: 检验标识。
            result: 检验结果字典。

        Returns:
            Markdown 行列表。
        """
        test_name = result.get("test_name", key)
        lines = [f"## {test_name}", ""]

        # 统计量与 p 值（根据检验类型提取）
        p_value = result.get("p_value")
        p_str = (
            f"{p_value:.4f}" if isinstance(p_value, (int, float)) else "N/A"
        )
        stars = _significance_stars(p_value)

        # VIF 特殊处理
        if "max_vif" in result:
            lines.append(f"- **最大 VIF**: {result['max_vif']:.4f}")
            lines.append("- **各变量 VIF**:")
            for var, vif in result.get("variables", {}).items():
                flag = " (严重)" if vif > 10 else (" (关注)" if vif > 5 else "")
                lines.append(f"  - {var}: {vif:.4f}{flag}")
            lines.append(f"- **严重程度**: {result.get('severity', 'unknown')}")
            lines.append(f"- **p 值**: N/A（VIF 基于阈值判断）")
        elif "chi2" in result:
            # Hausman
            chi2 = result.get("chi2")
            chi2_str = f"{chi2:.4f}" if isinstance(chi2, (int, float)) else "N/A"
            lines.append(f"- **Chi2 统计量**: {chi2_str}")
            lines.append(f"- **自由度**: {result.get('df', 'N/A')}")
            lines.append(f"- **p 值**: {p_str}{stars}")
            rec = result.get("recommendation")
            if rec == "fe":
                lines.append("- **推荐模型**: 固定效应（FE）")
            elif rec == "re":
                lines.append("- **推荐模型**: 随机效应（RE）")
        elif "lm_statistic" in result:
            # Breusch-Pagan
            lines.append(f"- **LM 统计量**: {result['lm_statistic']:.4f}")
            lines.append(f"- **LM p 值**: {result['lm_pvalue']:.4f}{stars}")
            lines.append(f"- **F 统计量**: {result['f_statistic']:.4f}")
            lines.append(f"- **F p 值**: {result['f_pvalue']:.4f}")
            lines.append(f"- **p 值**: {p_str}{stars}")
            hetero = result.get("has_heteroskedasticity")
            lines.append(
                f"- **是否存在异方差**: {'是' if hetero else '否'}"
            )
        elif "coefficient" in result and "t_statistic" in result:
            # Wooldridge
            coef = result.get("coefficient")
            coef_str = f"{coef:.4f}" if isinstance(coef, (int, float)) else "N/A"
            t_stat = result.get("t_statistic")
            t_str = f"{t_stat:.4f}" if isinstance(t_stat, (int, float)) else "N/A"
            lines.append(f"- **差分残差系数**: {coef_str}")
            lines.append(f"- **t 统计量**: {t_str}")
            lines.append(f"- **p 值**: {p_str}{stars}")
            autocorr = result.get("has_autocorrelation")
            lines.append(
                f"- **是否存在自相关**: {'是' if autocorr else '否'}"
            )
        elif "is_panel" in result:
            # 单位根检验
            if result["is_panel"]:
                lines.append(
                    f"- **检验类型**: 面板 ADF（{result.get('n_cross_sections', 0)} 个截面）"
                )
                lines.append(
                    f"- **平稳截面数**: {result.get('n_stationary', 0)}"
                )
                lines.append(
                    f"- **平稳比例**: {result.get('stationary_ratio', 0):.1%}"
                )
                lines.append(f"- **p 值**: N/A（面板逐截面检验）")
            else:
                stat = result.get("statistic")
                stat_str = (
                    f"{stat:.4f}" if isinstance(stat, (int, float)) else "N/A"
                )
                lines.append(f"- **检验类型**: 单序列 ADF")
                lines.append(f"- **ADF 统计量**: {stat_str}")
                lines.append(f"- **p 值**: {p_str}{stars}")
                lines.append(f"- **滞后阶数**: {result.get('n_lags', 'N/A')}")
                stationary = result.get("is_stationary")
                lines.append(
                    f"- **是否平稳**: {'是' if stationary else '否'}"
                )
        else:
            # 通用回退
            lines.append(f"- **p 值**: {p_str}{stars}")

        # 结论与建议（所有检验通用）
        conclusion = result.get("conclusion", "")
        if conclusion:
            lines.append("")
            lines.append(f"**结论**: {conclusion}")

        recommendation = result.get("recommendation", "")
        if recommendation:
            lines.append("")
            lines.append(f"**建议**: {recommendation}")

        return lines
