"""统计分析引擎（L1内置层）.

提供描述性统计、相关系数矩阵、OLS回归、面板回归（FE/RE）、
VIF多重共线性检验、Hausman检验、分位数回归、Logit/Probit离散选择回归、
Tobit回归（近似实现）等功能。
使用 pandas + statsmodels + linearmodels 实现，让用户不上 Stata 也能跑基础分析。

stats_engine 是 data_collector 的升级版：
- data_collector 仅提供描述性统计（count/mean/std/min/median/max）
- stats_engine 额外提供 skew/kurtosis、回归分析、检验功能

设计原则：
    - 延迟导入 statsmodels / linearmodels / scipy，缺失时降级
    - 不生成虚假数据，只处理用户传入的真实DataFrame
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _significance_stars(p: float) -> str:
    """根据 p 值返回显著性星号.

    显著性水平：
        - p < 0.01 → "***"
        - p < 0.05 → "**"
        - p < 0.1  → "*"
        - 否则     → ""

    Args:
        p: p 值。

    Returns:
        显著性星号字符串。
    """
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.1:
        return "*"
    return ""


class StatsEngine:
    """统计分析引擎（L1内置层）。使用 pandas + statsmodels + linearmodels。

    功能：
        - 描述性统计（含偏度 skew、峰度 kurtosis）
        - 相关系数矩阵（Pearson / Spearman / Kendall）+ p 值
        - OLS回归（支持 HC1 稳健标准误）
        - 面板回归（固定效应 FE / 随机效应 RE，支持聚类标准误）
        - VIF多重共线性检验
        - Hausman检验（FE vs RE选择）
        - 分位数回归（Quantile Regression，多分位数系数对比）
        - Logit / Probit 离散选择回归（含边际效应）
        - Tobit回归（截断/删失回归，近似实现）
        - 结果格式化（Markdown / LaTeX / JSON）

    使用示例::

        engine = StatsEngine()
        desc = engine.descriptive_stats(df, variables=["gdp", "debt"])
        ols = engine.ols_regression(df, dep_var="y", indep_vars=["x1", "x2"])
        panel = engine.panel_regression(
            df, dep_var="y", indep_vars=["x1"],
            entity_var="province", time_var="year", model="fe"
        )
        qr = engine.quantile_regression(df, dep_var="y", indep_vars=["x1", "x2"])
        logit = engine.logit_regression(df, dep_var="binary_y", indep_vars=["x1"])
        print(engine.format_results(ols, format_type="markdown"))
    """

    # ========== 描述性统计 ==========

    def descriptive_stats(self, df: Any, variables: list[str] | None = None) -> dict:
        """描述性统计：count/mean/std/min/median/max/skew/kurtosis。

        比 data_collector.calculate_descriptive_stats() 多 skew 和 kurtosis。

        Args:
            df: pandas DataFrame。
            variables: 要统计的变量名列表。如不提供，统计所有数值列。

        Returns:
            统计结果字典，格式为::

                {
                    "variable_name": {
                        "count": 3601,
                        "mean": 0.523,
                        "std": 0.178,
                        "min": 0.012,
                        "median": 0.498,
                        "max": 0.987,
                        "skew": 0.123,
                        "kurtosis": 2.987,
                    }
                }
        """
        if variables is None:
            variables = df.select_dtypes(include=["number"]).columns.tolist()

        stats: dict[str, dict[str, float]] = {}
        for var in variables:
            if var not in df.columns:
                logger.warning("变量 '%s' 不在数据列中，跳过", var)
                continue

            series = df[var].dropna()
            if len(series) == 0:
                logger.warning("变量 '%s' 无有效数据，跳过", var)
                continue

            stats[var] = {
                "count": int(len(series)),
                "mean": round(float(series.mean()), 4),
                "std": round(float(series.std()), 4),
                "min": round(float(series.min()), 4),
                "median": round(float(series.median()), 4),
                "max": round(float(series.max()), 4),
                "skew": round(float(series.skew()), 4),
                "kurtosis": round(float(series.kurtosis()), 4),
            }

        logger.info("描述性统计完成，共 %d 个变量", len(stats))
        return stats

    # ========== 相关系数矩阵 ==========

    def correlation_matrix(
        self, df: Any, variables: list[str] | None = None, method: str = "pearson"
    ) -> dict:
        """相关系数矩阵 + p值。

        Args:
            df: pandas DataFrame。
            variables: 要计算的变量名列表。如不提供，使用所有数值列。
            method: 相关系数方法，可选 "pearson"（默认）、"spearman"、"kendall"。

        Returns:
            结果字典，格式为::

                {
                    "matrix": {var1: {var2: corr_value}},
                    "p_values": {var1: {var2: p_value}},
                    "significant": {var1: {var2: "***"|"**"|"*"|""}},
                    "method": "pearson"
                }

        Raises:
            ValueError: 当 method 不支持时。
        """
        try:
            from scipy import stats as sp_stats
        except ImportError as e:
            raise ImportError(
                "scipy is required for correlation p-values. Install: pip install scipy"
            ) from e

        if variables is None:
            variables = df.select_dtypes(include=["number"]).columns.tolist()

        # 过滤出实际存在的列
        variables = [v for v in variables if v in df.columns]
        n = len(variables)

        if n == 0:
            return {"matrix": {}, "p_values": {}, "significant": {}, "method": method}

        # 初始化矩阵
        matrix: dict[str, dict[str, float]] = {
            v1: {v2: 0.0 for v2 in variables} for v1 in variables
        }
        p_values: dict[str, dict[str, float]] = {
            v1: {v2: 0.0 for v2 in variables} for v1 in variables
        }
        significant: dict[str, dict[str, str]] = {
            v1: {v2: "" for v2 in variables} for v1 in variables
        }

        for i, v1 in enumerate(variables):
            for j, v2 in enumerate(variables):
                if i == j:
                    matrix[v1][v2] = 1.0
                    p_values[v1][v2] = 0.0
                    significant[v1][v2] = "***"
                    continue

                # 配对删除缺失值
                paired = df[[v1, v2]].dropna()
                if len(paired) < 3:
                    matrix[v1][v2] = float("nan")
                    p_values[v1][v2] = float("nan")
                    significant[v1][v2] = ""
                    continue

                if method == "pearson":
                    corr, p = sp_stats.pearsonr(paired[v1], paired[v2])
                elif method == "spearman":
                    corr, p = sp_stats.spearmanr(paired[v1], paired[v2])
                elif method == "kendall":
                    corr, p = sp_stats.kendalltau(paired[v1], paired[v2])
                else:
                    raise ValueError(
                        f"不支持的相关方法: {method}，可选: pearson/spearman/kendall"
                    )

                matrix[v1][v2] = round(float(corr), 4)
                p_values[v1][v2] = round(float(p), 4)
                significant[v1][v2] = _significance_stars(float(p))

        logger.info("相关系数矩阵计算完成（%s），共 %d 个变量", method, n)
        return {
            "matrix": matrix,
            "p_values": p_values,
            "significant": significant,
            "method": method,
        }

    # ========== OLS 回归 ==========

    def ols_regression(
        self, df: Any, dep_var: str, indep_vars: list[str], robust: bool = True
    ) -> dict:
        """OLS回归。

        使用 statsmodels.api.OLS，robust=True 时用 HC1 稳健标准误。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名。
            indep_vars: 解释变量名列表。
            robust: 是否使用 HC1 稳健标准误，默认 True。

        Returns:
            回归结果字典，格式为::

                {
                    "coefficients": {"const": ..., "x1": ...},
                    "std_errors": {"const": ..., "x1": ...},
                    "t_values": {"const": ..., "x1": ...},
                    "p_values": {"const": ..., "x1": ...},
                    "r_squared": float,
                    "adj_r_squared": float,
                    "f_statistic": float,
                    "f_pvalue": float,
                    "n_obs": int,
                    "significant": {"const": "***", "x1": "**"},
                    "robust": True
                }

        Raises:
            ImportError: statsmodels 未安装。
            ValueError: 数据无效或变量不存在。
        """
        try:
            import statsmodels.api as sm
        except ImportError as e:
            raise ImportError(
                "statsmodels is required for OLS regression. "
                "Install: pip install statsmodels"
            ) from e

        # 校验变量存在
        all_vars = [dep_var] + indep_vars
        for var in all_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        # 选取并清洗数据
        data = df[all_vars].dropna()
        if len(data) < len(indep_vars) + 2:
            raise ValueError(
                f"有效样本量不足（{len(data)}行），至少需要 {len(indep_vars) + 2} 行"
            )

        Y = data[dep_var]
        X = sm.add_constant(data[indep_vars])

        if robust:
            model = sm.OLS(Y, X).fit(cov_type="HC1")
        else:
            model = sm.OLS(Y, X).fit()

        # 提取结果
        coefficients: dict[str, float] = {}
        std_errors: dict[str, float] = {}
        t_values: dict[str, float] = {}
        p_values: dict[str, float] = {}
        significant: dict[str, str] = {}

        for var in X.columns:
            coefficients[var] = round(float(model.params[var]), 6)
            std_errors[var] = round(float(model.bse[var]), 6)
            t_values[var] = round(float(model.tvalues[var]), 4)
            p = float(model.pvalues[var])
            p_values[var] = round(p, 6)
            significant[var] = _significance_stars(p)

        logger.info(
            "OLS回归完成: N=%d, R²=%.4f, robust=%s",
            int(model.nobs),
            float(model.rsquared),
            robust,
        )

        return {
            "coefficients": coefficients,
            "std_errors": std_errors,
            "t_values": t_values,
            "p_values": p_values,
            "r_squared": round(float(model.rsquared), 6),
            "adj_r_squared": round(float(model.rsquared_adj), 6),
            "f_statistic": round(float(model.fvalue), 4),
            "f_pvalue": round(float(model.f_pvalue), 6),
            "n_obs": int(model.nobs),
            "significant": significant,
            "robust": robust,
        }

    # ========== 面板回归 ==========

    def panel_regression(
        self,
        df: Any,
        dep_var: str,
        indep_vars: list[str],
        entity_var: str,
        time_var: str,
        model: str = "fe",
        cluster: bool = True,
    ) -> dict:
        """面板回归。

        使用 linearmodels.PanelOLS（FE）或 RandomEffects（RE）。
        需要先 set_index([entity_var, time_var])。
        cluster=True 时按 entity 聚类标准误。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名。
            indep_vars: 解释变量名列表。
            entity_var: 个体标识变量名（如 "province"）。
            time_var: 时间标识变量名（如 "year"）。
            model: 模型类型，"fe"（固定效应，默认）或 "re"（随机效应）。
            cluster: 是否按 entity 聚类标准误，默认 True。

        Returns:
            回归结果字典，格式同 ols_regression，额外含::

                "entity_effects": bool,   # 是否使用固定效应
                "clustered": bool,        # 是否聚类标准误
                "model": "fe"|"re"        # 模型类型

            如果 linearmodels 未安装，降级为 OLS 并在结果中添加 warning 字段。

        Raises:
            ValueError: model 参数不合法或数据无效。
        """
        try:
            from linearmodels.panel import PanelOLS, RandomEffects
        except ImportError:
            logger.warning(
                "linearmodels 未安装，面板回归降级为普通OLS（无固定效应）。"
                "建议安装: pip install linearmodels"
            )
            return self._panel_fallback_ols(df, dep_var, indep_vars, model, cluster)

        # 校验变量
        all_vars = [dep_var] + indep_vars + [entity_var, time_var]
        for var in all_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        # 选取并清洗数据
        data = df[all_vars].dropna().copy()
        if len(data) < len(indep_vars) + 2:
            raise ValueError(
                f"有效样本量不足（{len(data)}行），至少需要 {len(indep_vars) + 2} 行"
            )

        # 检查 (entity, time) 唯一性
        dup_count = data.duplicated(subset=[entity_var, time_var]).sum()
        if dup_count > 0:
            raise ValueError(
                f"面板数据中存在 {dup_count} 个重复的 ({entity_var}, {time_var}) 组合，"
                "请确保每个个体-时间组合唯一"
            )

        # 设置面板 MultiIndex 并排序
        data = data.set_index([entity_var, time_var])
        data = data.sort_index()

        Y = data[dep_var]

        if model == "fe":
            # 固定效应：不加常数（被个体效应吸收）
            X = data[indep_vars]
            mod = PanelOLS(Y, X, entity_effects=True)
            entity_effects = True
        elif model == "re":
            # 随机效应：需要加常数
            X = data[indep_vars].copy()
            X.insert(0, "const", 1.0)
            mod = RandomEffects(Y, X)
            entity_effects = False
        else:
            raise ValueError(f"不支持的面板模型: {model}，可选: fe/re")

        # 拟合
        if cluster:
            res = mod.fit(cov_type="clustered", cluster_entity=True)
        else:
            res = mod.fit()

        # 提取结果
        coefficients: dict[str, float] = {}
        std_errors: dict[str, float] = {}
        t_values: dict[str, float] = {}
        p_values: dict[str, float] = {}
        significant: dict[str, str] = {}

        for var in res.params.index:
            coefficients[var] = round(float(res.params[var]), 6)
            std_errors[var] = round(float(res.std_errors[var]), 6)
            t_values[var] = round(float(res.tstats[var]), 4)
            p = float(res.pvalues[var])
            p_values[var] = round(p, 6)
            significant[var] = _significance_stars(p)

        # R²
        r_sq = round(float(res.rsquared), 6)
        # 调整 R²（linearmodels 部分版本可能不提供）
        try:
            adj_r_sq = round(float(res.rsquared_adj), 6)
        except (AttributeError, TypeError):
            adj_r_sq = None

        # F 统计量
        f_stat_obj = getattr(res, "f_statistic", None)
        if f_stat_obj is not None and hasattr(f_stat_obj, "stat"):
            f_statistic = round(float(f_stat_obj.stat), 4)
            f_pvalue = round(float(f_stat_obj.pval), 6)
        else:
            f_statistic = None
            f_pvalue = None

        logger.info(
            "面板回归完成: model=%s, N=%d, R²=%.4f, cluster=%s",
            model,
            int(res.nobs),
            r_sq,
            cluster,
        )

        return {
            "coefficients": coefficients,
            "std_errors": std_errors,
            "t_values": t_values,
            "p_values": p_values,
            "r_squared": r_sq,
            "adj_r_squared": adj_r_sq,
            "f_statistic": f_statistic,
            "f_pvalue": f_pvalue,
            "n_obs": int(res.nobs),
            "significant": significant,
            "entity_effects": entity_effects,
            "clustered": cluster,
            "model": model,
        }

    def _panel_fallback_ols(
        self, df: Any, dep_var: str, indep_vars: list[str], model: str, cluster: bool
    ) -> dict:
        """linearmodels 未安装时的面板回归降级方案。

        退化为普通 OLS（无固定效应），并在结果中添加 warning 字段。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名。
            indep_vars: 解释变量名列表。
            model: 原始请求的模型类型。
            cluster: 原始请求的聚类设置。

        Returns:
            OLS 回归结果字典，附加降级提示字段。
        """
        result = self.ols_regression(df, dep_var, indep_vars, robust=True)
        result["entity_effects"] = False
        result["clustered"] = False
        result["model"] = "ols_fallback"
        result["warning"] = (
            "linearmodels 未安装，面板回归已降级为普通OLS（无固定效应/聚类标准误）。"
            "请安装 linearmodels 以获得完整的面板回归功能: pip install linearmodels"
        )
        return result

    # ========== VIF 多重共线性检验 ==========

    def vif_test(self, df: Any, indep_vars: list[str]) -> dict:
        """VIF多重共线性检验。

        使用 statsmodels.stats.outliers_influence.variance_inflation_factor。
        阈值：VIF > 10 表示严重多重共线性。

        Args:
            df: pandas DataFrame。
            indep_vars: 解释变量名列表。

        Returns:
            结果字典，格式为::

                {
                    "variables": {"x1": vif_value, "x2": vif_value},
                    "max_vif": float,
                    "has_multicollinearity": bool   # max_vif > 10
                }

        Raises:
            ImportError: statsmodels 未安装。
            ValueError: 变量不存在或样本量不足。
        """
        try:
            import statsmodels.api as sm
            from statsmodels.stats.outliers_influence import variance_inflation_factor
        except ImportError as e:
            raise ImportError(
                "statsmodels is required for VIF test. "
                "Install: pip install statsmodels"
            ) from e

        # 校验变量
        for var in indep_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

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

        logger.info(
            "VIF检验完成: max_vif=%.4f, has_multicollinearity=%s",
            max_vif,
            has_multicollinearity,
        )

        return {
            "variables": vif_values,
            "max_vif": round(max_vif, 4),
            "has_multicollinearity": has_multicollinearity,
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
        """Hausman检验（FE vs RE选择）。

        H0: 随机效应一致（选RE）；H1: 选FE。
        实现方式：比较FE和RE的系数差异。

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
                    "chi2": float,
                    "p_value": float,
                    "recommendation": "fe"|"re",
                    "interpretation": str
                }

            如果 linearmodels 未安装，返回提示信息。
        """
        try:
            import numpy as np
            from linearmodels.panel import PanelOLS, RandomEffects
        except ImportError:
            return {
                "chi2": None,
                "p_value": None,
                "recommendation": None,
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

        # 取共同变量（FE 无 const，RE 有 const，所以共同变量是 indep_vars）
        common_vars = [v for v in fe_res.params.index if v in re_res.params.index]
        if len(common_vars) == 0:
            return {
                "chi2": None,
                "p_value": None,
                "recommendation": "fe",
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
                "chi2": None,
                "p_value": None,
                "recommendation": "fe",
                "interpretation": f"Hausman检验计算失败: {e}。默认推荐固定效应（FE）。",
            }

        k = len(common_vars)

        # chi2 为负时，说明 V_FE - V_RE 非正定（RE至少不劣于FE），推荐RE
        if chi2 < 0:
            recommendation = "re"
            interpretation = (
                f"Hausman统计量为负（chi2={chi2:.4f}），"
                f"表明随机效应不劣于固定效应，建议使用随机效应（RE）。"
            )
            return {
                "chi2": round(chi2, 4),
                "p_value": 1.0,
                "recommendation": recommendation,
                "interpretation": interpretation,
            }

        try:
            from scipy import stats as sp_stats

            p_value = float(sp_stats.chi2.sf(chi2, k))
        except Exception:
            p_value = None

        if p_value is not None and p_value < 0.05:
            recommendation = "fe"
            interpretation = (
                f"Hausman检验: chi2={chi2:.4f}, p={p_value:.4f} < 0.05，"
                f"拒绝随机效应一致的原假设（H0），建议使用固定效应（FE）。"
            )
        else:
            recommendation = "re"
            p_str = f"{p_value:.4f}" if p_value is not None else "N/A"
            interpretation = (
                f"Hausman检验: chi2={chi2:.4f}, p={p_str} >= 0.05，"
                f"不能拒绝随机效应一致的原假设（H0），建议使用随机效应（RE）。"
            )

        logger.info("Hausman检验完成: chi2=%.4f, p=%s, 推荐=%s", chi2, p_str, recommendation)

        return {
            "chi2": round(chi2, 4),
            "p_value": round(p_value, 4) if p_value is not None else None,
            "recommendation": recommendation,
            "interpretation": interpretation,
        }

    # ========== 分位数回归 ==========

    def quantile_regression(
        self,
        df: Any,
        dep_var: str,
        indep_vars: list[str],
        quantiles: list[float] | None = None,
        robust: bool = True,
    ) -> dict:
        """分位数回归（Quantile Regression）。

        使用 statsmodels.regression.quantile_regression.QuantReg，
        对每个分位数分别拟合，收集系数、标准误、p值与伪R²。
        robust=True 时通过 cov_type='HC1' 使用稳健标准误。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名。
            indep_vars: 解释变量名列表。
            quantiles: 要拟合的分位数列表，默认 [0.10, 0.25, 0.50, 0.75, 0.90]。
            robust: 是否使用 HC1 稳健标准误，默认 True。

        Returns:
            结果字典，格式为::

                {
                    "quantiles": [0.10, 0.25, 0.50, 0.75, 0.90],
                    # 规范格式：嵌套结果
                    "results": {
                        0.10: {"coefficients": {...}, "std_errors": {...},
                               "p_values": {...}, "pseudo_r2": float, "n_obs": int},
                        ...
                    },
                    # 向后兼容：扁平化结果（按分位数值索引）
                    "coefficients": {0.10: {...}, ...},
                    "std_errors": {0.10: {...}, ...},
                    "p_values": {0.10: {...}, ...},
                    # 跨分位数系数对比（以分位数值为键）
                    "coefficient_comparison": {
                        "var1": {0.10: coef, 0.25: coef, 0.50: coef,
                                 0.75: coef, 0.90: coef},
                        ...
                    },
                    "robust": bool,
                    "n_obs": int
                }

        Raises:
            ImportError: statsmodels 未安装。
            ValueError: 数据无效、变量不存在或分位数越界。
        """
        try:
            import statsmodels.api as sm
            from statsmodels.regression.quantile_regression import QuantReg
        except ImportError as e:
            raise ImportError(
                "statsmodels is required for quantile regression. "
                "Install: pip install statsmodels"
            ) from e

        if quantiles is None:
            quantiles = [0.10, 0.25, 0.50, 0.75, 0.90]

        # 校验分位数范围
        for q in quantiles:
            if not 0.0 < q < 1.0:
                raise ValueError(f"分位数必须在 (0, 1) 区间内，收到: {q}")

        # 校验变量存在
        all_vars = [dep_var] + indep_vars
        for var in all_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        # 选取并清洗数据
        data = df[all_vars].dropna()
        if len(data) < len(indep_vars) + 2:
            raise ValueError(
                f"有效样本量不足（{len(data)}行），至少需要 {len(indep_vars) + 2} 行"
            )

        Y = data[dep_var]
        X = sm.add_constant(data[indep_vars])

        results_by_q: dict[float, dict] = {}
        # 向后兼容：扁平化的系数/标准误/p值，按分位数值索引
        flat_coefficients: dict[float, dict] = {}
        flat_std_errors: dict[float, dict] = {}
        flat_p_values: dict[float, dict] = {}
        # 系数对比表（以分位数值为键，便于跨分位数比较）
        comparison: dict[str, dict[float, float]] = {var: {} for var in X.columns}

        for q in quantiles:
            mod = QuantReg(Y, X)
            if robust:
                res = mod.fit(q=q, cov_type="HC1")
            else:
                res = mod.fit(q=q)

            coefficients: dict[str, float] = {}
            std_errors: dict[str, float] = {}
            p_values: dict[str, float] = {}

            for var in X.columns:
                coefficients[var] = round(float(res.params[var]), 6)
                std_errors[var] = round(float(res.bse[var]), 6)
                p = float(res.pvalues[var])
                p_values[var] = round(p, 6)

            # 规范格式：嵌套结果
            results_by_q[q] = {
                "coefficients": coefficients,
                "std_errors": std_errors,
                "p_values": p_values,
                "pseudo_r2": round(float(res.prsquared), 6),
                "n_obs": int(res.nobs),
            }
            # 向后兼容：扁平化结果（按分位数值索引）
            flat_coefficients[q] = coefficients
            flat_std_errors[q] = std_errors
            flat_p_values[q] = p_values

            # 填充系数对比表（以分位数值为键）
            for var in X.columns:
                comparison[var][q] = coefficients[var]

        logger.info(
            "分位数回归完成: 分位数=%s, N=%d, robust=%s",
            quantiles,
            len(data),
            robust,
        )

        return {
            "quantiles": list(quantiles),
            # 规范格式：嵌套结果（每个分位数含 coefficients/std_errors/p_values/pseudo_r2/n_obs）
            "results": results_by_q,
            # 向后兼容：扁平化结果（按分位数值索引）
            "coefficients": flat_coefficients,
            "std_errors": flat_std_errors,
            "p_values": flat_p_values,
            # 跨分位数系数对比（以分位数值为键）
            "coefficient_comparison": comparison,
            "robust": robust,
            "n_obs": int(len(data)),
        }

    # ========== 离散选择回归（Logit / Probit）==========

    def logit_regression(
        self, df: Any, dep_var: str, indep_vars: list[str], robust: bool = True
    ) -> dict:
        """Logit回归（二元离散选择）。

        使用 statsmodels.api.Logit，被解释变量应为 0/1 变量。
        robust=True 时使用 HC1 稳健标准误。同时输出边际效应（marginal effects）。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名（0/1）。
            indep_vars: 解释变量名列表。
            robust: 是否使用 HC1 稳健标准误，默认 True。

        Returns:
            回归结果字典，格式同 ols_regression，额外含::

                "pseudo_r2": float,         # McFadden伪R²
                "log_likelihood": float,    # 对数似然值
                "aic": float,
                "bic": float,
                "marginal_effects": {var: float},
                "model": "logit"

        Raises:
            ImportError: statsmodels 未安装。
            ValueError: 数据无效、变量不存在或被解释变量非0/1。
        """
        return self._discrete_choice_regression(
            df, dep_var, indep_vars, model_type="logit", robust=robust
        )

    def probit_regression(
        self, df: Any, dep_var: str, indep_vars: list[str], robust: bool = True
    ) -> dict:
        """Probit回归（二元离散选择）。

        使用 statsmodels.api.Probit，被解释变量应为 0/1 变量。
        robust=True 时使用 HC1 稳健标准误。同时输出边际效应（marginal effects）。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名（0/1）。
            indep_vars: 解释变量名列表。
            robust: 是否使用 HC1 稳健标准误，默认 True。

        Returns:
            回归结果字典，格式同 logit_regression，"model" 为 "probit"。

        Raises:
            ImportError: statsmodels 未安装。
            ValueError: 数据无效、变量不存在或被解释变量非0/1。
        """
        return self._discrete_choice_regression(
            df, dep_var, indep_vars, model_type="probit", robust=robust
        )

    def _discrete_choice_regression(
        self,
        df: Any,
        dep_var: str,
        indep_vars: list[str],
        model_type: str,
        robust: bool,
    ) -> dict:
        """Logit/Probit 离散选择回归内部实现。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名（0/1）。
            indep_vars: 解释变量名列表。
            model_type: "logit" 或 "probit"。
            robust: 是否使用 HC1 稳健标准误。

        Returns:
            回归结果字典。

        Raises:
            ImportError: statsmodels 未安装。
            ValueError: 数据无效、变量不存在或被解释变量非0/1。
        """
        try:
            import statsmodels.api as sm
        except ImportError as e:
            raise ImportError(
                "statsmodels is required for discrete choice regression. "
                "Install: pip install statsmodels"
            ) from e

        # 校验变量存在
        all_vars = [dep_var] + indep_vars
        for var in all_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        # 选取并清洗数据
        data = df[all_vars].dropna()
        if len(data) < len(indep_vars) + 2:
            raise ValueError(
                f"有效样本量不足（{len(data)}行），至少需要 {len(indep_vars) + 2} 行"
            )

        # 校验被解释变量为 0/1
        unique_vals = set(data[dep_var].unique().tolist())
        if not unique_vals.issubset({0, 1}):
            raise ValueError(
                f"离散选择回归的被解释变量 '{dep_var}' 必须为 0/1 变量，"
                f"实际包含值: {sorted(unique_vals)}"
            )

        Y = data[dep_var]
        X = sm.add_constant(data[indep_vars])

        if model_type == "logit":
            mod = sm.Logit(Y, X)
        elif model_type == "probit":
            mod = sm.Probit(Y, X)
        else:
            raise ValueError(f"不支持的离散选择模型: {model_type}，可选: logit/probit")

        if robust:
            res = mod.fit(disp=0, cov_type="HC1")
        else:
            res = mod.fit(disp=0)

        # 提取系数（离散模型的 tvalues 实为 z 统计量，沿用 t_values 键以与 OLS 对齐）
        coefficients: dict[str, float] = {}
        std_errors: dict[str, float] = {}
        t_values: dict[str, float] = {}
        p_values: dict[str, float] = {}
        significant: dict[str, str] = {}

        for var in X.columns:
            coefficients[var] = round(float(res.params[var]), 6)
            std_errors[var] = round(float(res.bse[var]), 6)
            t_values[var] = round(float(res.tvalues[var]), 4)
            p = float(res.pvalues[var])
            p_values[var] = round(p, 6)
            significant[var] = _significance_stars(p)

        # 边际效应（overall）
        marginal_effects: dict[str, float] = {}
        try:
            margeff = res.get_margeff()
            me_frame = margeff.summary_frame()
            for var in X.columns:
                if var in me_frame.index:
                    marginal_effects[var] = round(float(me_frame.loc[var, "dy/dx"]), 6)
        except Exception as e:
            logger.warning("边际效应计算失败（%s）: %s", model_type, e)

        logger.info(
            "%s回归完成: N=%d, pseudo_R²=%.4f, robust=%s",
            model_type.capitalize(),
            int(res.nobs),
            float(res.prsquared),
            robust,
        )

        return {
            "coefficients": coefficients,
            "std_errors": std_errors,
            "t_values": t_values,
            "p_values": p_values,
            "significant": significant,
            "pseudo_r2": round(float(res.prsquared), 6),
            "log_likelihood": round(float(res.llf), 6),
            "aic": round(float(res.aic), 4),
            "bic": round(float(res.bic), 4),
            "n_obs": int(res.nobs),
            "marginal_effects": marginal_effects,
            "robust": robust,
            "model": model_type,
        }

    # ========== Tobit 回归（近似实现）==========

    def tobit_regression(
        self,
        df: Any,
        dep_var: str,
        indep_vars: list[str],
        lower: float | None = None,
        upper: float | None = None,
    ) -> dict:
        """Tobit回归（截断/删失回归，近似实现）。

        statsmodels 无原生 Tobit，此处采用截断回归（truncated regression）
        近似：对被解释变量超出截断区间的样本予以剔除后做 OLS（HC1稳健标准误）。
        注意：截断回归与原版 Tobit（删失回归，censored regression）的 MLE 估计
        存在偏差，尤其当删失比例较高时。建议删失比例较高时使用专门的 Tobit 实现
        （如 R 的 AER::tobit 或 Stata 的 tobit 命令）。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名。
            indep_vars: 解释变量名列表。
            lower: 左截断点，None 表示无左截断。
            upper: 右截断点，None 表示无右截断。

        Returns:
            结果字典，格式为::

                {
                    "coefficients": {...},
                    "std_errors": {...},
                    "t_values": {...},
                    "p_values": {...},
                    "significant": {...},
                    "n_obs": int,            # 截断后保留的观测数
                    "n_censored": int,       # 被删失的观测数
                    "censoring": "left"|"right"|"both"|"none",
                    "lower": float|None,
                    "upper": float|None,
                    "r_squared": float,
                    "note": str
                }

        Raises:
            ImportError: statsmodels 未安装。
            ValueError: 数据无效、变量不存在或截断设置不合法。
        """
        try:
            import statsmodels.api as sm
        except ImportError as e:
            raise ImportError(
                "statsmodels is required for tobit regression. "
                "Install: pip install statsmodels"
            ) from e

        # 校验截断点合法性
        if lower is not None and upper is not None and lower >= upper:
            raise ValueError(f"左截断点({lower})必须小于右截断点({upper})")

        # 校验变量存在
        all_vars = [dep_var] + indep_vars
        for var in all_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        # 选取并清洗数据
        data = df[all_vars].dropna()
        if len(data) < len(indep_vars) + 2:
            raise ValueError(
                f"有效样本量不足（{len(data)}行），至少需要 {len(indep_vars) + 2} 行"
            )

        # 确定删失类型
        if lower is not None and upper is not None:
            censoring = "both"
        elif lower is not None:
            censoring = "left"
        elif upper is not None:
            censoring = "right"
        else:
            censoring = "none"

        # 应用截断：左截断保留 dep_var > lower，右截断保留 dep_var < upper
        dep_series = data[dep_var]
        mask = dep_series.notna()  # dropna 后全为 True，作为布尔基础
        if lower is not None:
            mask = mask & (dep_series > lower)
        if upper is not None:
            mask = mask & (dep_series < upper)

        n_censored = int(len(data) - mask.sum())
        data = data[mask]

        if len(data) < len(indep_vars) + 2:
            raise ValueError(
                f"截断后有效样本量不足（{len(data)}行），至少需要 "
                f"{len(indep_vars) + 2} 行，请放宽截断区间或检查数据"
            )

        Y = data[dep_var]
        X = sm.add_constant(data[indep_vars])
        res = sm.OLS(Y, X).fit(cov_type="HC1")

        # 提取结果
        coefficients: dict[str, float] = {}
        std_errors: dict[str, float] = {}
        t_values: dict[str, float] = {}
        p_values: dict[str, float] = {}
        significant: dict[str, str] = {}

        for var in X.columns:
            coefficients[var] = round(float(res.params[var]), 6)
            std_errors[var] = round(float(res.bse[var]), 6)
            t_values[var] = round(float(res.tvalues[var]), 4)
            p = float(res.pvalues[var])
            p_values[var] = round(p, 6)
            significant[var] = _significance_stars(p)

        note = (
            "Tobit回归近似实现：statsmodels 无原生 Tobit，此处对被解释变量"
            "超出截断区间的样本予以剔除后做 OLS（即截断回归 truncated regression）。"
            "注意：截断回归与原版 Tobit（删失回归 censored regression）的 MLE "
            "估计存在偏差，尤其当删失比例较高时。建议删失比例较高时使用专门的 "
            "Tobit 实现（如 R 的 AER::tobit 或 Stata 的 tobit 命令）。"
        )

        logger.info(
            "Tobit回归（近似）完成: censoring=%s, N=%d, n_censored=%d, R²=%.4f",
            censoring,
            int(res.nobs),
            n_censored,
            float(res.rsquared),
        )

        return {
            "coefficients": coefficients,
            "std_errors": std_errors,
            "t_values": t_values,
            "p_values": p_values,
            "significant": significant,
            "n_obs": int(res.nobs),
            "n_censored": n_censored,
            "censoring": censoring,
            "lower": lower,
            "upper": upper,
            "r_squared": round(float(res.rsquared), 6),
            "note": note,
        }

    # ========== 结果格式化 ==========

    def format_results(self, results: dict, format_type: str = "markdown") -> str:
        """格式化结果为 Markdown/LaTeX/JSON。

        显著性星号：*** p<0.01, ** p<0.05, * p<0.1
        Markdown格式回归表：系数在上行，标准误在下方括号内，显著性星号跟在系数后。

        Args:
            results: 各分析方法返回的结果字典。
            format_type: 输出格式，"markdown"（默认）、"latex"、"json"。

        Returns:
            格式化后的字符串。

        Raises:
            ValueError: 当 format_type 不支持时。
        """
        if format_type == "json":
            return json.dumps(results, ensure_ascii=False, indent=2, default=str)

        if format_type not in ("markdown", "latex"):
            raise ValueError(
                f"不支持的格式: {format_type}，可选: markdown/latex/json"
            )

        # 检测结果类型
        result_type = self._detect_result_type(results)

        if result_type == "regression":
            return self._format_regression(results, format_type)
        elif result_type == "quantile":
            return self._format_quantile(results, format_type)
        elif result_type == "discrete":
            return self._format_discrete(results, format_type)
        elif result_type == "tobit":
            return self._format_tobit(results, format_type)
        elif result_type == "correlation":
            return self._format_correlation(results, format_type)
        elif result_type == "vif":
            return self._format_vif(results, format_type)
        elif result_type == "hausman":
            return self._format_hausman(results, format_type)
        else:
            return self._format_descriptive(results, format_type)

    def _detect_result_type(self, results: dict) -> str:
        """根据结果字典的键检测结果类型.

        Args:
            results: 结果字典。

        Returns:
            结果类型字符串: "regression"/"quantile"/"discrete"/"tobit"/
            "correlation"/"vif"/"hausman"/"descriptive"/"unknown"。
        """
        # 分位数回归：含 quantiles + coefficient_comparison
        if "quantiles" in results and "coefficient_comparison" in results:
            return "quantile"
        # Tobit：含 censoring（注意须在 regression 之前判定，因 tobit 也含 r_squared）
        if "censoring" in results:
            return "tobit"
        # 离散选择（Logit/Probit）：含 marginal_effects + pseudo_r2（无 r_squared）
        if "marginal_effects" in results and "pseudo_r2" in results:
            return "discrete"
        if "r_squared" in results:
            return "regression"
        if "matrix" in results and "p_values" in results:
            return "correlation"
        if "max_vif" in results:
            return "vif"
        if "chi2" in results and "recommendation" in results:
            return "hausman"
        if results and all(
            isinstance(v, dict) and "count" in v for v in results.values()
        ):
            return "descriptive"
        return "unknown"

    def _format_descriptive(self, results: dict, format_type: str) -> str:
        """格式化描述性统计结果.

        Args:
            results: 描述性统计结果字典。
            format_type: "markdown" 或 "latex"。

        Returns:
            格式化字符串。
        """
        if not results:
            return "（暂无描述性统计数据）"

        if format_type == "latex":
            lines = [
                r"\begin{tabular}{lcccccccc}",
                r"\toprule",
                r"变量 & 观测数 & 均值 & 标准差 & 最小值 & 中位数 & 最大值 & 偏度 & 峰度 \\",
                r"\midrule",
            ]
            for var, s in results.items():
                lines.append(
                    f"{var} & {s['count']} & {s['mean']:.4f} & {s['std']:.4f} "
                    f"& {s['min']:.4f} & {s['median']:.4f} & {s['max']:.4f} "
                    f"& {s['skew']:.4f} & {s['kurtosis']:.4f} \\\\"
                )
            lines.append(r"\bottomrule")
            lines.append(r"\end{tabular}")
            return "\n".join(lines)

        # Markdown
        lines = [
            "### 描述性统计",
            "",
            "| 变量 | 观测数 | 均值 | 标准差 | 最小值 | 中位数 | 最大值 | 偏度 | 峰度 |",
            "|------|--------|------|--------|--------|--------|--------|------|------|",
        ]
        for var, s in results.items():
            lines.append(
                f"| {var} | {s['count']} | {s['mean']:.4f} | {s['std']:.4f} "
                f"| {s['min']:.4f} | {s['median']:.4f} | {s['max']:.4f} "
                f"| {s['skew']:.4f} | {s['kurtosis']:.4f} |"
            )
        return "\n".join(lines)

    def _format_correlation(self, results: dict, format_type: str) -> str:
        """格式化相关系数矩阵结果.

        Args:
            results: 相关系数矩阵结果字典。
            format_type: "markdown" 或 "latex"。

        Returns:
            格式化字符串。
        """
        matrix = results.get("matrix", {})
        method = results.get("method", "pearson")
        method_name = {"pearson": "Pearson", "spearman": "Spearman", "kendall": "Kendall"}
        title = f"{method_name.get(method, method)}相关系数矩阵"

        if not matrix:
            return f"### {title}\n\n（暂无数据）"

        variables = list(matrix.keys())

        if format_type == "latex":
            header = " & ".join(["变量"] + variables)
            lines = [
                r"\begin{tabular}{l" + "c" * len(variables) + "}",
                r"\toprule",
                header + r" \\",
                r"\midrule",
            ]
            for v1 in variables:
                row = [v1]
                for v2 in variables:
                    val = matrix[v1][v2]
                    stars = results.get("significant", {}).get(v1, {}).get(v2, "")
                    row.append(f"{val:.4f}{stars}")
                lines.append(" & ".join(row) + r" \\")
            lines.append(r"\bottomrule")
            lines.append(r"\end{tabular}")
            return "\n".join(lines)

        # Markdown
        lines = [f"### {title}", ""]
        header = "| 变量 | " + " | ".join(variables) + " |"
        separator = "|------|" + "|".join(["------"] * len(variables)) + "|"
        lines.append(header)
        lines.append(separator)
        for v1 in variables:
            cells = [v1]
            for v2 in variables:
                val = matrix[v1][v2]
                stars = results.get("significant", {}).get(v1, {}).get(v2, "")
                cells.append(f"{val:.4f}{stars}")
            lines.append("| " + " | ".join(cells) + " |")

        lines.append("")
        lines.append("注：*** p<0.01, ** p<0.05, * p<0.1")
        return "\n".join(lines)

    def _format_regression(self, results: dict, format_type: str) -> str:
        """格式化回归结果。

        Markdown格式：系数在上行（带显著性星号），标准误在下方括号内。
        LaTeX格式：单行格式，系数和标准误分列。

        Args:
            results: 回归结果字典。
            format_type: "markdown" 或 "latex"。

        Returns:
            格式化字符串。
        """
        coeffs = results.get("coefficients", {})
        std_errs = results.get("std_errors", {})
        p_vals = results.get("p_values", {})
        sigs = results.get("significant", {})
        t_vals = results.get("t_values", {})

        model_type = results.get("model", "ols")
        is_panel = model_type in ("fe", "re")
        title_map = {"fe": "面板回归（固定效应 FE）", "re": "面板回归（随机效应 RE）",
                     "ols": "OLS回归", "ols_fallback": "OLS回归（面板降级）"}
        title = title_map.get(model_type, "回归结果")

        if results.get("robust"):
            title += " - HC1稳健标准误"
        if results.get("clustered"):
            title += " - 聚类标准误"

        if format_type == "latex":
            lines = [
                r"\begin{tabular}{lcccc}",
                r"\toprule",
                r"变量 & 系数 & 标准误 & t值 & p值 \\",
                r"\midrule",
            ]
            for var in coeffs:
                c = coeffs[var]
                se = std_errs.get(var, 0)
                t = t_vals.get(var, 0)
                p = p_vals.get(var, 0)
                s = sigs.get(var, "")
                lines.append(
                    f"{var} & {c:.4f}{s} & ({se:.4f}) & {t:.4f} & {p:.4f} \\\\"
                )
            lines.append(r"\midrule")
            lines.append(f"N & \\multicolumn{{4}}{{c}}{{{results.get('n_obs', '')}}} \\\\")
            r_sq = results.get("r_squared")
            if r_sq is not None:
                lines.append(f"R$^2$ & \\multicolumn{{4}}{{c}}{{{r_sq:.4f}}} \\\\")
            adj_r = results.get("adj_r_squared")
            if adj_r is not None:
                lines.append(f"调整R$^2$ & \\multicolumn{{4}}{{c}}{{{adj_r:.4f}}} \\\\")
            f_stat = results.get("f_statistic")
            if f_stat is not None:
                lines.append(f"F统计量 & \\multicolumn{{4}}{{c}}{{{f_stat:.4f}}} \\\\")
            lines.append(r"\bottomrule")
            lines.append(r"\end{tabular}")
            lines.append("")
            lines.append(r"注：*** p$<$0.01, ** p$<$0.05, * p$<$0.1")
            return "\n".join(lines)

        # Markdown：系数在上行，标准误在下方括号内
        lines = [f"### {title}", ""]
        lines.append("| 变量 | 系数 | t值 | p值 |")
        lines.append("|------|------|-----|-----|")

        for var in coeffs:
            c = coeffs[var]
            se = std_errs.get(var, 0)
            t = t_vals.get(var, 0)
            p = p_vals.get(var, 0)
            s = sigs.get(var, "")
            # 系数行（带显著性星号）
            lines.append(f"| {var} | {c:.4f}{s} | {t:.4f} | {p:.4f} |")
            # 标准误行（括号内）
            lines.append(f"| | ({se:.4f}) | | |")

        lines.append("|------|------|-----|-----|")

        # 底部统计量
        lines.append(f"| N | {results.get('n_obs', '')} | | |")
        r_sq = results.get("r_squared")
        if r_sq is not None:
            lines.append(f"| R² | {r_sq:.4f} | | |")
        adj_r = results.get("adj_r_squared")
        if adj_r is not None:
            lines.append(f"| 调整R² | {adj_r:.4f} | | |")
        f_stat = results.get("f_statistic")
        if f_stat is not None:
            f_pval = results.get("f_pvalue", 0)
            f_sig = _significance_stars(f_pval) if f_pval is not None else ""
            lines.append(f"| F统计量 | {f_stat:.4f}{f_sig} | | |")

        lines.append("")
        lines.append("注：括号内为标准误。*** p<0.01, ** p<0.05, * p<0.1")

        if "warning" in results:
            lines.append("")
            lines.append(f"> ⚠ {results['warning']}")

        return "\n".join(lines)

    def _format_vif(self, results: dict, format_type: str) -> str:
        """格式化VIF检验结果.

        Args:
            results: VIF检验结果字典。
            format_type: "markdown" 或 "latex"。

        Returns:
            格式化字符串。
        """
        variables = results.get("variables", {})
        max_vif = results.get("max_vif", 0)
        has_multi = results.get("has_multicollinearity", False)

        if format_type == "latex":
            lines = [
                r"\begin{tabular}{lc}",
                r"\toprule",
                r"变量 & VIF \\",
                r"\midrule",
            ]
            for var, vif in variables.items():
                lines.append(f"{var} & {vif:.4f} \\\\")
            lines.append(r"\midrule")
            lines.append(f"最大VIF & {max_vif:.4f} \\\\")
            lines.append(r"\bottomrule")
            lines.append(r"\end{tabular}")
            return "\n".join(lines)

        # Markdown
        lines = ["### VIF多重共线性检验", ""]
        lines.append("| 变量 | VIF值 |")
        lines.append("|------|-------|")
        for var, vif in variables.items():
            flag = " ⚠" if vif > 10 else ""
            lines.append(f"| {var} | {vif:.4f}{flag} |")
        lines.append("|------|-------|")
        lines.append(f"| 最大VIF | {max_vif:.4f} |")
        lines.append("")
        if has_multi:
            lines.append("> ⚠ 存在严重多重共线性（VIF > 10），建议检查变量或使用降维方法。")
        else:
            lines.append("未检测到严重多重共线性（VIF ≤ 10）。")
        return "\n".join(lines)

    def _format_hausman(self, results: dict, format_type: str) -> str:
        """格式化Hausman检验结果.

        Args:
            results: Hausman检验结果字典。
            format_type: "markdown" 或 "latex"。

        Returns:
            格式化字符串。
        """
        chi2 = results.get("chi2")
        p_value = results.get("p_value")
        recommendation = results.get("recommendation")
        interpretation = results.get("interpretation", "")

        if format_type == "latex":
            lines = [
                r"\begin{tabular}{lc}",
                r"\toprule",
                r"统计量 & 值 \\",
                r"\midrule",
            ]
            if chi2 is not None:
                lines.append(f"Chi2 & {chi2:.4f} \\\\")
            if p_value is not None:
                lines.append(f"p值 & {p_value:.4f} \\\\")
            if recommendation:
                rec_text = "固定效应 (FE)" if recommendation == "fe" else "随机效应 (RE)"
                lines.append(f"推荐模型 & {rec_text} \\\\")
            lines.append(r"\bottomrule")
            lines.append(r"\end{tabular}")
            lines.append("")
            lines.append(interpretation)
            return "\n".join(lines)

        # Markdown
        lines = ["### Hausman检验（FE vs RE）", ""]
        if chi2 is not None:
            lines.append(f"- **Chi2 统计量**: {chi2:.4f}")
        if p_value is not None:
            lines.append(f"- **p 值**: {p_value:.4f}")
        if recommendation:
            rec_text = "固定效应（FE）" if recommendation == "fe" else "随机效应（RE）"
            lines.append(f"- **推荐模型**: {rec_text}")
        lines.append("")
        lines.append(f"> {interpretation}")
        return "\n".join(lines)

    def _format_quantile(self, results: dict, format_type: str) -> str:
        """格式化分位数回归结果.

        Args:
            results: 分位数回归结果字典。
            format_type: "markdown" 或 "latex"。

        Returns:
            格式化字符串。
        """
        quantiles = results.get("quantiles", [])
        q_results = results.get("results", {})
        robust = results.get("robust", False)

        title = "分位数回归（Quantile Regression）"
        if robust:
            title += " - HC1稳健标准误"

        # 收集所有变量名（从第一个分位数结果取，保持顺序）
        all_vars: list[str] = []
        for q in quantiles:
            qres = q_results.get(q, {})
            for var in qres.get("coefficients", {}):
                if var not in all_vars:
                    all_vars.append(var)

        if format_type == "latex":
            lines = [
                r"\begin{tabular}{l" + "c" * len(quantiles) + "}",
                r"\toprule",
                "变量 & " + " & ".join([f"q={q:.2f}" for q in quantiles]) + r" \\",
                r"\midrule",
            ]
            for var in all_vars:
                row = [var]
                for q in quantiles:
                    qres = q_results.get(q, {})
                    coef = qres.get("coefficients", {}).get(var, 0.0)
                    p = qres.get("p_values", {}).get(var, 1.0)
                    stars = _significance_stars(p)
                    row.append(f"{coef:.4f}{stars}")
                lines.append(" & ".join(row) + r" \\")
            lines.append(r"\midrule")
            # 伪R²行
            row = [r"伪R$^2$"]
            for q in quantiles:
                pr2 = q_results.get(q, {}).get("pseudo_r2", 0.0)
                row.append(f"{pr2:.4f}")
            lines.append(" & ".join(row) + r" \\")
            lines.append(r"\bottomrule")
            lines.append(r"\end{tabular}")
            lines.append("")
            lines.append(r"注：*** p$<$0.01, ** p$<$0.05, * p$<$0.1")
            return "\n".join(lines)

        # Markdown
        lines = [f"### {title}", ""]
        lines.append("**分位数**: " + ", ".join([f"{q:.2f}" for q in quantiles]))
        lines.append("")
        lines.append("#### 系数对比表")
        lines.append("")
        header = "| 变量 | " + " | ".join([f"q={q:.2f}" for q in quantiles]) + " |"
        sep = "|------|" + "|".join(["------"] * len(quantiles)) + "|"
        lines.append(header)
        lines.append(sep)

        for var in all_vars:
            cells = [var]
            for q in quantiles:
                qres = q_results.get(q, {})
                coef = qres.get("coefficients", {}).get(var, 0.0)
                p = qres.get("p_values", {}).get(var, 1.0)
                stars = _significance_stars(p)
                cells.append(f"{coef:.4f}{stars}")
            lines.append("| " + " | ".join(cells) + " |")

        lines.append("")
        lines.append("#### 各分位数拟合统计")
        lines.append("")
        lines.append("| 分位数 | 伪R² | 观测数 |")
        lines.append("|--------|------|--------|")
        for q in quantiles:
            qres = q_results.get(q, {})
            lines.append(
                f"| {q:.2f} | {qres.get('pseudo_r2', 0.0):.4f} "
                f"| {qres.get('n_obs', 0)} |"
            )

        lines.append("")
        lines.append("注：*** p<0.01, ** p<0.05, * p<0.1")
        return "\n".join(lines)

    def _format_discrete(self, results: dict, format_type: str) -> str:
        """格式化Logit/Probit离散选择回归结果.

        Args:
            results: 离散选择回归结果字典。
            format_type: "markdown" 或 "latex"。

        Returns:
            格式化字符串。
        """
        model = results.get("model", "logit")
        title_map = {"logit": "Logit回归", "probit": "Probit回归"}
        title = title_map.get(model, "离散选择回归")
        if results.get("robust"):
            title += " - HC1稳健标准误"

        coeffs = results.get("coefficients", {})
        std_errs = results.get("std_errors", {})
        t_vals = results.get("t_values", {})
        p_vals = results.get("p_values", {})
        sigs = results.get("significant", {})
        me = results.get("marginal_effects", {})

        if format_type == "latex":
            lines = [
                r"\begin{tabular}{lcccc}",
                r"\toprule",
                r"变量 & 系数 & 标准误 & z值 & p值 \\",
                r"\midrule",
            ]
            for var in coeffs:
                c = coeffs[var]
                se = std_errs.get(var, 0)
                t = t_vals.get(var, 0)
                p = p_vals.get(var, 0)
                s = sigs.get(var, "")
                lines.append(
                    f"{var} & {c:.4f}{s} & ({se:.4f}) & {t:.4f} & {p:.4f} \\\\"
                )
            lines.append(r"\midrule")
            lines.append(
                f"N & \\multicolumn{{4}}{{c}}{{{results.get('n_obs', '')}}} \\\\"
            )
            pr2 = results.get("pseudo_r2")
            if pr2 is not None:
                lines.append(f"伪R$^2$ & \\multicolumn{{4}}{{c}}{{{pr2:.4f}}} \\\\")
            llf = results.get("log_likelihood")
            if llf is not None:
                lines.append(f"对数似然 & \\multicolumn{{4}}{{c}}{{{llf:.4f}}} \\\\")
            aic = results.get("aic")
            if aic is not None:
                lines.append(f"AIC & \\multicolumn{{4}}{{c}}{{{aic:.4f}}} \\\\")
            bic = results.get("bic")
            if bic is not None:
                lines.append(f"BIC & \\multicolumn{{4}}{{c}}{{{bic:.4f}}} \\\\")
            lines.append(r"\bottomrule")
            lines.append(r"\end{tabular}")
            lines.append("")
            # 边际效应表
            if me:
                lines.append(r"\begin{tabular}{lc}")
                lines.append(r"\toprule")
                lines.append(r"变量 & 边际效应 \\")
                lines.append(r"\midrule")
                for var, val in me.items():
                    lines.append(f"{var} & {val:.4f} \\\\")
                lines.append(r"\bottomrule")
                lines.append(r"\end{tabular}")
                lines.append("")
            lines.append(r"注：*** p$<$0.01, ** p$<$0.05, * p$<$0.1")
            return "\n".join(lines)

        # Markdown：系数在上行（带显著性星号），标准误在下方括号内
        lines = [f"### {title}", ""]
        lines.append("| 变量 | 系数 | z值 | p值 | 边际效应 |")
        lines.append("|------|------|-----|-----|----------|")
        for var in coeffs:
            c = coeffs[var]
            se = std_errs.get(var, 0)
            t = t_vals.get(var, 0)
            p = p_vals.get(var, 0)
            s = sigs.get(var, "")
            m = me.get(var)
            m_str = f"{m:.4f}" if isinstance(m, (int, float)) else ""
            lines.append(f"| {var} | {c:.4f}{s} | {t:.4f} | {p:.4f} | {m_str} |")
            lines.append(f"| | ({se:.4f}) | | | |")
        lines.append("|------|------|-----|-----|----------|")
        lines.append(f"| N | {results.get('n_obs', '')} | | | |")
        pr2 = results.get("pseudo_r2")
        if pr2 is not None:
            lines.append(f"| 伪R² | {pr2:.4f} | | | |")
        llf = results.get("log_likelihood")
        if llf is not None:
            lines.append(f"| 对数似然 | {llf:.4f} | | | |")
        aic = results.get("aic")
        if aic is not None:
            lines.append(f"| AIC | {aic:.4f} | | | |")
        bic = results.get("bic")
        if bic is not None:
            lines.append(f"| BIC | {bic:.4f} | | | |")
        lines.append("")
        lines.append("注：括号内为标准误。*** p<0.01, ** p<0.05, * p<0.1")
        return "\n".join(lines)

    def _format_tobit(self, results: dict, format_type: str) -> str:
        """格式化Tobit回归结果.

        Args:
            results: Tobit回归结果字典。
            format_type: "markdown" 或 "latex"。

        Returns:
            格式化字符串。
        """
        coeffs = results.get("coefficients", {})
        std_errs = results.get("std_errors", {})
        t_vals = results.get("t_values", {})
        p_vals = results.get("p_values", {})
        sigs = results.get("significant", {})
        censoring = results.get("censoring", "none")
        censor_map = {
            "none": "无删失",
            "left": "左删失",
            "right": "右删失",
            "both": "双侧删失",
        }
        title = f"Tobit回归（近似实现 - {censor_map.get(censoring, censoring)}）"

        if format_type == "latex":
            lines = [
                r"\begin{tabular}{lcccc}",
                r"\toprule",
                r"变量 & 系数 & 标准误 & t值 & p值 \\",
                r"\midrule",
            ]
            for var in coeffs:
                c = coeffs[var]
                se = std_errs.get(var, 0)
                t = t_vals.get(var, 0)
                p = p_vals.get(var, 0)
                s = sigs.get(var, "")
                lines.append(
                    f"{var} & {c:.4f}{s} & ({se:.4f}) & {t:.4f} & {p:.4f} \\\\"
                )
            lines.append(r"\midrule")
            lines.append(
                f"N & \\multicolumn{{4}}{{c}}{{{results.get('n_obs', '')}}} \\\\"
            )
            lines.append(
                f"删失数 & \\multicolumn{{4}}{{c}}{{{results.get('n_censored', 0)}}} \\\\"
            )
            r_sq = results.get("r_squared")
            if r_sq is not None:
                lines.append(f"R$^2$ & \\multicolumn{{4}}{{c}}{{{r_sq:.4f}}} \\\\")
            lines.append(r"\bottomrule")
            lines.append(r"\end{tabular}")
            lines.append("")
            note = results.get("note")
            if note:
                lines.append(note)
            return "\n".join(lines)

        # Markdown：系数在上行，标准误在下方括号内
        lines = [f"### {title}", ""]
        lines.append("| 变量 | 系数 | t值 | p值 |")
        lines.append("|------|------|-----|-----|")
        for var in coeffs:
            c = coeffs[var]
            se = std_errs.get(var, 0)
            t = t_vals.get(var, 0)
            p = p_vals.get(var, 0)
            s = sigs.get(var, "")
            lines.append(f"| {var} | {c:.4f}{s} | {t:.4f} | {p:.4f} |")
            lines.append(f"| | ({se:.4f}) | | |")
        lines.append("|------|------|-----|-----|")
        lines.append(f"| N | {results.get('n_obs', '')} | | |")
        lines.append(f"| 删失观测数 | {results.get('n_censored', 0)} | | |")
        lower = results.get("lower")
        upper = results.get("upper")
        lower_str = f"{lower:.4f}" if lower is not None else "无"
        upper_str = f"{upper:.4f}" if upper is not None else "无"
        lines.append(f"| 左截断点 | {lower_str} | | |")
        lines.append(f"| 右截断点 | {upper_str} | | |")
        r_sq = results.get("r_squared")
        if r_sq is not None:
            lines.append(f"| R² | {r_sq:.4f} | | |")
        lines.append("")
        lines.append("注：括号内为标准误。*** p<0.01, ** p<0.05, * p<0.1")
        note = results.get("note")
        if note:
            lines.append("")
            lines.append(f"> {note}")
        return "\n".join(lines)

    # ========== 一键完整分析 ==========

    def run_full_analysis(
        self,
        df: Any,
        dep_var: str,
        indep_vars: list[str],
        entity_var: str | None = None,
        time_var: str | None = None,
    ) -> dict:
        """一键完整分析：描述性统计 + 相关系数 + OLS/面板回归 + VIF + (可选)Hausman。

        Args:
            df: pandas DataFrame。
            dep_var: 被解释变量名。
            indep_vars: 解释变量名列表。
            entity_var: 个体标识变量名。提供时启用面板回归和Hausman检验。
            time_var: 时间标识变量名。提供时启用面板回归和Hausman检验。

        Returns:
            完整分析结果字典，格式为::

                {
                    "descriptive": {...},    # 描述性统计
                    "correlation": {...},    # 相关系数矩阵
                    "regression": {...},     # OLS或面板回归
                    "vif": {...},            # VIF检验
                    "hausman": {...}         # Hausman检验（仅面板数据）
                }

            当 entity_var 和 time_var 都提供时，使用面板回归；
            否则使用 OLS 回归，且不包含 Hausman 检验。
        """
        results: dict[str, Any] = {}

        # 确定要统计的变量列表
        desc_vars = list(indep_vars) + [dep_var]
        if entity_var:
            desc_vars.append(entity_var)
        if time_var:
            desc_vars.append(time_var)

        # 1. 描述性统计
        logger.info("=== 完整分析: 1/5 描述性统计 ===")
        results["descriptive"] = self.descriptive_stats(df, desc_vars)

        # 2. 相关系数矩阵
        logger.info("=== 完整分析: 2/5 相关系数矩阵 ===")
        corr_vars = list(indep_vars) + [dep_var]
        results["correlation"] = self.correlation_matrix(df, corr_vars)

        # 3. 回归
        if entity_var and time_var:
            logger.info("=== 完整分析: 3/5 面板回归（FE）===")
            results["regression"] = self.panel_regression(
                df, dep_var, indep_vars, entity_var, time_var,
                model="fe", cluster=True
            )
            # 5. Hausman 检验（仅面板数据）
            logger.info("=== 完整分析: 5/5 Hausman检验 ===")
            results["hausman"] = self.hausman_test(
                df, dep_var, indep_vars, entity_var, time_var
            )
        else:
            logger.info("=== 完整分析: 3/5 OLS回归 ===")
            results["regression"] = self.ols_regression(
                df, dep_var, indep_vars, robust=True
            )

        # 4. VIF 检验
        logger.info("=== 完整分析: 4/5 VIF检验 ===")
        results["vif"] = self.vif_test(df, indep_vars)

        logger.info("=== 完整分析完成 ===")
        return results


__all__ = [
    "StatsEngine",
    "_significance_stars",
]
