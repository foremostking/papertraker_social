"""中介效应与调节效应分析工具.

提供中国实证论文中"机制分析"章节常用的统计方法：
    - Baron & Kenny 三步法（总效应、中介效应、直接效应）
    - Sobel 检验（中介效应显著性）
    - Bootstrap 中介效应检验（非参数置信区间）
    - 调节效应分析（交互项显著性）
    - 机制分析报告生成（Markdown）

设计原则：
    - 延迟导入 statsmodels / scipy / numpy，缺失时降级
    - 复用 stats_engine.ols_regression() 做回归，保证结果格式统一
    - 不生成虚假数据，只处理用户传入的真实 DataFrame

使用示例::

    from scholarpilot.tools.mediation_analysis import MediationAnalysis
    from scholarpilot.tools.stats_engine import StatsEngine

    engine = StatsEngine()
    ma = MediationAnalysis(engine)

    # Baron & Kenny 三步法
    bk = ma.baron_kenny(df, x="x", y="y", mediator="m", controls=["c1"])

    # Sobel 检验
    sobel = ma.sobel_test(a=0.5, b=0.4, se_a=0.05, se_b=0.06)

    # Bootstrap 检验
    boot = ma.bootstrap_mediation(df, x="x", y="y", mediator="m", n_bootstrap=1000)

    # 调节效应
    mod = ma.moderation_analysis(df, x="x", y="y", moderator="w")

    # 生成报告
    report = ma.generate_mechanism_report(bk)
"""

from __future__ import annotations

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


class MediationAnalysis:
    """中介效应与调节效应分析工具。

    功能：
        - Baron & Kenny 三步法：分解总效应为直接效应和间接效应
        - Sobel 检验：间接效应 a*b 的正态近似显著性检验
        - Bootstrap 中介效应检验：非参数置信区间
        - 调节效应分析：交互项 X*M 的显著性检验
        - 机制分析报告：生成 Markdown 格式的完整报告

    使用示例::

        from scholarpilot.tools.stats_engine import StatsEngine
        from scholarpilot.tools.mediation_analysis import MediationAnalysis

        engine = StatsEngine()
        ma = MediationAnalysis(engine)
        result = ma.baron_kenny(df, x="X", y="Y", mediator="M")
        report = ma.generate_mechanism_report(result)
    """

    def __init__(self, stats_engine: Any | None = None) -> None:
        """初始化中介效应分析工具。

        Args:
            stats_engine: StatsEngine 实例，用于复用 ols_regression。
                          如不提供，则按需创建。
        """
        if stats_engine is not None:
            self._engine = stats_engine
        else:
            # 延迟导入，避免循环依赖
            from scholarpilot.tools.stats_engine import StatsEngine

            self._engine = StatsEngine()

    # ========== Baron & Kenny 三步法 ==========

    def baron_kenny(
        self,
        df: Any,
        x: str,
        y: str,
        mediator: str,
        controls: list[str] | None = None,
    ) -> dict:
        """Baron & Kenny 三步法中介效应分析。

        步骤1: Y = cX + controls     （总效应 c）
        步骤2: M = aX + controls     （X 对 M 的效应 a）
        步骤3: Y = c'X + bM + controls（直接效应 c'）

        中介效应 = a * b
        中介类型判定：
            - 完全中介：c 显著，c' 不显著，a*b 显著
            - 部分中介：c 显著，c' 显著但 |c'| < |c|，a*b 显著
            - 无中介：a*b 不显著，或 c 不显著

        Args:
            df: pandas DataFrame。
            x: 自变量名。
            y: 因变量名。
            mediator: 中介变量名。
            controls: 控制变量名列表，默认无。

        Returns:
            结果字典，格式为::

                {
                    "step1": {ols结果},        # 总效应回归
                    "step2": {ols结果},        # X→M 回归
                    "step3": {ols结果},        # 直接效应回归
                    "total_effect": float,     # c (总效应)
                    "direct_effect": float,    # c' (直接效应)
                    "indirect_effect": float,  # a*b (间接效应)
                    "a": float,                # 步骤2中X的系数
                    "b": float,                # 步骤3中M的系数
                    "se_a": float,             # a的标准误
                    "se_b": float,             # b的标准误
                    "mediation_type": "full"|"partial"|"none",
                    "indirect_ratio": float,   # 中介效应占总效应比例
                }
        """
        controls = controls or []

        # 步骤1: Y = cX + controls（总效应 c）
        step1_vars = [x] + controls
        step1 = self._engine.ols_regression(df, dep_var=y, indep_vars=step1_vars)
        c = step1["coefficients"].get(x, 0.0)

        # 步骤2: M = aX + controls（X 对 M 的效应 a）
        step2 = self._engine.ols_regression(df, dep_var=mediator, indep_vars=step1_vars)
        a = step2["coefficients"].get(x, 0.0)
        se_a = step2["std_errors"].get(x, 0.0)

        # 步骤3: Y = c'X + bM + controls（直接效应 c'）
        step3_vars = [x, mediator] + controls
        step3 = self._engine.ols_regression(df, dep_var=y, indep_vars=step3_vars)
        c_prime = step3["coefficients"].get(x, 0.0)
        b = step3["coefficients"].get(mediator, 0.0)
        se_b = step3["std_errors"].get(mediator, 0.0)

        # 间接效应 = a * b
        indirect_effect = a * b

        # 中介类型判定
        c_sig = step1["significant"].get(x, "") != ""
        c_prime_sig = step3["significant"].get(x, "") != ""
        b_sig = step3["significant"].get(mediator, "") != ""
        a_sig = step2["significant"].get(x, "") != ""

        indirect_sig = a_sig and b_sig

        if indirect_sig and not c_prime_sig and c_sig:
            mediation_type = "full"
        elif indirect_sig and c_prime_sig and c_sig:
            mediation_type = "partial"
        else:
            mediation_type = "none"

        # 中介效应占总效应比例
        if abs(c) > 1e-10:
            indirect_ratio = indirect_effect / c
        else:
            indirect_ratio = 0.0

        logger.info(
            "Baron & Kenny 三步法完成: c=%.4f, c'=%.4f, a*b=%.4f, 类型=%s",
            c, c_prime, indirect_effect, mediation_type,
        )

        return {
            "step1": step1,
            "step2": step2,
            "step3": step3,
            "total_effect": round(c, 6),
            "direct_effect": round(c_prime, 6),
            "indirect_effect": round(indirect_effect, 6),
            "a": round(a, 6),
            "b": round(b, 6),
            "se_a": round(se_a, 6),
            "se_b": round(se_b, 6),
            "mediation_type": mediation_type,
            "indirect_ratio": round(indirect_ratio, 4),
        }

    # ========== Sobel 检验 ==========

    def sobel_test(self, a: float, b: float, se_a: float, se_b: float) -> dict:
        """Sobel 检验：中介效应 a*b 的显著性检验。

        检验统计量：
            z = (a * b) / sqrt(b^2 * se_a^2 + a^2 * se_b^2)

        H0: 间接效应 a*b = 0（无中介效应）
        使用标准正态分布计算双侧 p 值。

        Args:
            a: 步骤2中 X 对 M 的效应系数。
            b: 步骤3中 M 对 Y 的效应系数。
            se_a: a 的标准误。
            se_b: b 的标准误。

        Returns:
            结果字典，格式为::

                {
                    "z": float,           # Sobel z 统计量
                    "p_value": float,     # 双侧 p 值
                    "significant": bool,  # p < 0.05 为显著
                    "indirect_effect": float,  # a*b
                    "se_indirect": float,      # 间接效应标准误
                }
        """
        try:
            import numpy as np
            from scipy import stats as sp_stats
        except ImportError as e:
            raise ImportError(
                "numpy and scipy are required for Sobel test. "
                "Install: pip install numpy scipy"
            ) from e

        indirect = a * b
        # 间接效应的标准误（Delta方法）
        var_indirect = (b ** 2) * (se_a ** 2) + (a ** 2) * (se_b ** 2)
        se_indirect = np.sqrt(var_indirect) if var_indirect > 0 else 0.0

        # z 统计量
        if se_indirect > 0:
            z = indirect / se_indirect
            p_value = 2 * (1 - sp_stats.norm.cdf(abs(z)))
        else:
            z = 0.0
            p_value = 1.0

        significant = p_value < 0.05

        logger.info(
            "Sobel检验完成: z=%.4f, p=%.4f, significant=%s",
            z, p_value, significant,
        )

        return {
            "z": round(float(z), 6),
            "p_value": round(float(p_value), 6),
            "significant": bool(significant),
            "indirect_effect": round(float(indirect), 6),
            "se_indirect": round(float(se_indirect), 6),
        }

    # ========== Bootstrap 中介效应检验 ==========

    def bootstrap_mediation(
        self,
        df: Any,
        x: str,
        y: str,
        mediator: str,
        controls: list[str] | None = None,
        n_bootstrap: int = 1000,
    ) -> dict:
        """Bootstrap 中介效应检验。

        重复抽样 n_bootstrap 次（有放回），每次计算 a*b，
        取 2.5% 和 97.5% 分位数作为 95% 置信区间。
        若置信区间不包含 0，则中介效应显著。

        Args:
            df: pandas DataFrame。
            x: 自变量名。
            y: 因变量名。
            mediator: 中介变量名。
            controls: 控制变量名列表，默认无。
            n_bootstrap: Bootstrap 抽样次数，默认 1000。

        Returns:
            结果字典，格式为::

                {
                    "indirect_effect": float,   # 原始样本的 a*b
                    "ci_lower": float,          # 95%CI 下界
                    "ci_upper": float,          # 95%CI 上界
                    "significant": bool,        # CI不包含0为显著
                    "n_bootstrap": int,         # 抽样次数
                    "bootstrap_mean": float,    # Bootstrap 均值
                    "bootstrap_std": float,     # Bootstrap 标准差
                }
        """
        try:
            import numpy as np
        except ImportError as e:
            raise ImportError(
                "numpy is required for bootstrap. Install: pip install numpy"
            ) from e

        controls = controls or []

        # 原始样本的间接效应
        bk_result = self.baron_kenny(df, x, y, mediator, controls)
        point_estimate = bk_result["indirect_effect"]

        # 准备数据
        all_vars = [x, y, mediator] + controls
        data = df[all_vars].dropna()
        n = len(data)
        if n < 10:
            raise ValueError(f"有效样本量不足（{n}行），Bootstrap 至少需要 10 行")

        # Bootstrap 抽样
        rng = np.random.default_rng(42)
        indirect_effects = np.empty(n_bootstrap)

        for i in range(n_bootstrap):
            # 有放回抽样
            indices = rng.integers(0, n, size=n)
            sample = data.iloc[indices]

            try:
                sample_bk = self._compute_indirect(sample, x, y, mediator, controls)
                indirect_effects[i] = sample_bk
            except Exception:
                # 单次回归失败时用 NaN 占位
                indirect_effects[i] = np.nan

        # 删除 NaN
        valid_effects = indirect_effects[~np.isnan(indirect_effects)]
        if len(valid_effects) < n_bootstrap * 0.5:
            raise RuntimeError(
                f"Bootstrap 失败次数过多（{n_bootstrap - len(valid_effects)}/{n_bootstrap}），"
                "请检查数据质量"
            )

        ci_lower = float(np.percentile(valid_effects, 2.5))
        ci_upper = float(np.percentile(valid_effects, 97.5))
        significant = (ci_lower > 0) or (ci_upper < 0)

        logger.info(
            "Bootstrap中介检验完成: a*b=%.4f, 95%%CI=[%.4f, %.4f], significant=%s, N=%d",
            point_estimate, ci_lower, ci_upper, significant, len(valid_effects),
        )

        return {
            "indirect_effect": round(point_estimate, 6),
            "ci_lower": round(ci_lower, 6),
            "ci_upper": round(ci_upper, 6),
            "significant": bool(significant),
            "n_bootstrap": int(len(valid_effects)),
            "bootstrap_mean": round(float(np.mean(valid_effects)), 6),
            "bootstrap_std": round(float(np.std(valid_effects)), 6),
        }

    def _compute_indirect(
        self,
        df: Any,
        x: str,
        y: str,
        mediator: str,
        controls: list[str],
    ) -> float:
        """计算单个样本的间接效应 a*b（内部辅助方法）。

        Args:
            df: pandas DataFrame（子样本）。
            x: 自变量名。
            y: 因变量名。
            mediator: 中介变量名。
            controls: 控制变量名列表。

        Returns:
            间接效应 a*b 的值。
        """
        x_vars = [x] + controls

        # 步骤2: M = aX + controls
        step2 = self._engine.ols_regression(df, dep_var=mediator, indep_vars=x_vars)
        a = step2["coefficients"].get(x, 0.0)

        # 步骤3: Y = c'X + bM + controls
        step3_vars = [x, mediator] + controls
        step3 = self._engine.ols_regression(df, dep_var=y, indep_vars=step3_vars)
        b = step3["coefficients"].get(mediator, 0.0)

        return a * b

    # ========== 调节效应分析 ==========

    def moderation_analysis(
        self,
        df: Any,
        x: str,
        y: str,
        moderator: str,
        controls: list[str] | None = None,
    ) -> dict:
        """调节效应分析。

        模型：Y = β1*X + β2*M + β3*(X*M) + controls

        β3（交互项系数）显著则存在调节效应。
        交互项通过中心化后相乘构建，以减少多重共线性。

        Args:
            df: pandas DataFrame。
            x: 自变量名。
            y: 因变量名。
            moderator: 调节变量名。
            controls: 控制变量名列表，默认无。

        Returns:
            结果字典，格式为::

                {
                    "coefficients": {...},          # 所有系数
                    "std_errors": {...},
                    "p_values": {...},
                    "significant": {...},
                    "interaction_p_value": float,   # 交互项 p 值
                    "interaction_coefficient": float,  # 交互项系数
                    "has_moderation": bool,         # 交互项是否显著
                    "r_squared": float,
                    "n_obs": int,
                    "interaction_var": str,         # 交互项变量名
                }
        """
        try:
            import numpy as np
        except ImportError as e:
            raise ImportError(
                "numpy is required for moderation analysis. Install: pip install numpy"
            ) from e

        controls = controls or []

        # 校验变量存在
        all_vars = [x, y, moderator] + controls
        for var in all_vars:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        # 构建中心化交互项以减少多重共线性
        work_df = df[all_vars].dropna().copy()

        x_centered = work_df[x] - work_df[x].mean()
        m_centered = work_df[moderator] - work_df[moderator].mean()
        interaction_name = f"{x}_x_{moderator}"
        work_df[interaction_name] = (x_centered * m_centered).values

        # 回归: Y = β1*X + β2*M + β3*(X*M) + controls
        indep_vars = [x, moderator, interaction_name] + controls
        result = self._engine.ols_regression(work_df, dep_var=y, indep_vars=indep_vars)

        interaction_p = result["p_values"].get(interaction_name, 1.0)
        interaction_coef = result["coefficients"].get(interaction_name, 0.0)
        has_moderation = result["significant"].get(interaction_name, "") != ""

        logger.info(
            "调节效应分析完成: 交互项系数=%.4f, p=%.4f, has_moderation=%s",
            interaction_coef, interaction_p, has_moderation,
        )

        return {
            "coefficients": result["coefficients"],
            "std_errors": result["std_errors"],
            "p_values": result["p_values"],
            "significant": result["significant"],
            "interaction_p_value": round(float(interaction_p), 6),
            "interaction_coefficient": round(float(interaction_coef), 6),
            "has_moderation": bool(has_moderation),
            "r_squared": result["r_squared"],
            "n_obs": result["n_obs"],
            "interaction_var": interaction_name,
        }

    # ========== 机制分析报告 ==========

    def generate_mechanism_report(self, results: dict) -> str:
        """生成机制分析报告（Markdown 格式）。

        根据 Baron & Kenny 三步法结果生成完整报告，包含：
            - 三步法回归结果表（系数、标准误、显著性）
            - 中介效应分解（总效应、直接效应、间接效应）
            - Sobel 检验 / Bootstrap 检验结果（如提供）
            - 中介类型结论

        Args:
            results: baron_kenny() 返回的结果字典。
                     可附加 "sobel" 和 "bootstrap" 字段。

        Returns:
            Markdown 格式的机制分析报告字符串。
        """
        lines: list[str] = []
        lines.append("## 机制分析报告")
        lines.append("")

        # ---- 三步法回归表 ----
        lines.append("### 一、Baron & Kenny 三步法回归结果")
        lines.append("")

        # 步骤1表
        step1 = results.get("step1", {})
        step2 = results.get("step2", {})
        step3 = results.get("step3", {})

        lines.append("**步骤1：总效应回归 Y = cX + controls**")
        lines.append("")
        lines.append("| 变量 | 系数 | 标准误 | p值 | 显著性 |")
        lines.append("|------|------|--------|-----|--------|")
        self._append_regression_rows(lines, step1)
        lines.append(f"| N | {step1.get('n_obs', '')} | | | |")
        lines.append(f"| R² | {step1.get('r_squared', 0):.4f} | | | |")
        lines.append("")

        # 步骤2表
        lines.append("**步骤2：X 对中介变量的效应 M = aX + controls**")
        lines.append("")
        lines.append("| 变量 | 系数 | 标准误 | p值 | 显著性 |")
        lines.append("|------|------|--------|-----|--------|")
        self._append_regression_rows(lines, step2)
        lines.append(f"| N | {step2.get('n_obs', '')} | | | |")
        lines.append(f"| R² | {step2.get('r_squared', 0):.4f} | | | |")
        lines.append("")

        # 步骤3表
        lines.append("**步骤3：直接效应回归 Y = c'X + bM + controls**")
        lines.append("")
        lines.append("| 变量 | 系数 | 标准误 | p值 | 显著性 |")
        lines.append("|------|------|--------|-----|--------|")
        self._append_regression_rows(lines, step3)
        lines.append(f"| N | {step3.get('n_obs', '')} | | | |")
        lines.append(f"| R² | {step3.get('r_squared', 0):.4f} | | | |")
        lines.append("")

        # ---- 中介效应分解 ----
        lines.append("### 二、中介效应分解")
        lines.append("")
        total = results.get("total_effect", 0.0)
        direct = results.get("direct_effect", 0.0)
        indirect = results.get("indirect_effect", 0.0)
        a_val = results.get("a", 0.0)
        b_val = results.get("b", 0.0)
        ratio = results.get("indirect_ratio", 0.0)
        med_type = results.get("mediation_type", "none")

        lines.append("| 效应类型 | 符号 | 估计值 |")
        lines.append("|----------|------|--------|")
        lines.append(f"| 总效应 | c | {total:.4f} |")
        lines.append(f"| 直接效应 | c' | {direct:.4f} |")
        lines.append(f"| 间接效应（中介效应） | a×b | {indirect:.4f} |")
        lines.append(f"| X→M 路径系数 | a | {a_val:.4f} |")
        lines.append(f"| M→Y 路径系数 | b | {b_val:.4f} |")
        lines.append(f"| 中介效应占比 | a×b/c | {ratio:.2%} |")
        lines.append("")

        # ---- Sobel 检验结果 ----
        sobel = results.get("sobel")
        if sobel is not None:
            lines.append("### 三、Sobel 检验")
            lines.append("")
            lines.append("| 统计量 | 值 |")
            lines.append("|--------|-----|")
            lines.append(f"| z 统计量 | {sobel['z']:.4f} |")
            lines.append(f"| p 值 | {sobel['p_value']:.4f} |")
            lines.append(
                f"| 间接效应标准误 | {sobel['se_indirect']:.4f} |"
            )
            sig_text = "显著（p < 0.05）" if sobel["significant"] else "不显著"
            lines.append(f"| 结论 | {sig_text} |")
            lines.append("")

        # ---- Bootstrap 检验结果 ----
        bootstrap = results.get("bootstrap")
        if bootstrap is not None:
            section_num = "三" if sobel is None else "四"
            lines.append(f"### {section_num}、Bootstrap 中介效应检验")
            lines.append("")
            lines.append("| 统计量 | 值 |")
            lines.append("|--------|-----|")
            lines.append(f"| 间接效应（a×b） | {bootstrap['indirect_effect']:.4f} |")
            lines.append(f"| 95% CI 下界 | {bootstrap['ci_lower']:.4f} |")
            lines.append(f"| 95% CI 上界 | {bootstrap['ci_upper']:.4f} |")
            lines.append(f"| Bootstrap 均值 | {bootstrap['bootstrap_mean']:.4f} |")
            lines.append(f"| Bootstrap 标准差 | {bootstrap['bootstrap_std']:.4f} |")
            lines.append(f"| 抽样次数 | {bootstrap['n_bootstrap']} |")
            sig_text = "显著（CI 不含 0）" if bootstrap["significant"] else "不显著"
            lines.append(f"| 结论 | {sig_text} |")
            lines.append("")

        # ---- 结论 ----
        conclusion_num = self._get_conclusion_section_num(sobel, bootstrap)
        lines.append(f"### {conclusion_num}、结论")
        lines.append("")

        type_map = {
            "full": "完全中介（Full Mediation）",
            "partial": "部分中介（Partial Mediation）",
            "none": "无中介效应",
        }
        type_text = type_map.get(med_type, med_type)

        if med_type == "full":
            conclusion = (
                f"Baron & Kenny 三步法结果表明，存在**完全中介效应**。"
                f"自变量对因变量的总效应为 c={total:.4f}，"
                f"在加入中介变量后直接效应 c'={direct:.4f} 不再显著，"
                f"间接效应 a×b={indirect:.4f}（a={a_val:.4f}, b={b_val:.4f}），"
                f"中介效应占总效应的 {ratio:.2%}。"
                f"说明自变量对因变量的影响完全通过中介变量传递。"
            )
        elif med_type == "partial":
            conclusion = (
                f"Baron & Kenny 三步法结果表明，存在**部分中介效应**。"
                f"自变量对因变量的总效应为 c={total:.4f}，"
                f"在加入中介变量后直接效应 c'={direct:.4f} 仍然显著但有所减弱，"
                f"间接效应 a×b={indirect:.4f}（a={a_val:.4f}, b={b_val:.4f}），"
                f"中介效应占总效应的 {ratio:.2%}。"
                f"说明中介变量部分解释了自变量对因变量的影响机制。"
            )
        else:
            conclusion = (
                f"Baron & Kenny 三步法结果表明，**未发现显著的中介效应**。"
                f"间接效应 a×b={indirect:.4f} 不显著，"
                f"中介变量未能在自变量和因变量之间起到中介作用。"
            )

        lines.append(conclusion)
        lines.append("")
        lines.append(f"**中介类型**：{type_text}")
        lines.append("")
        lines.append("---")
        lines.append("注：*** p<0.01, ** p<0.05, * p<0.1")

        return "\n".join(lines)

    def _append_regression_rows(self, lines: list[str], step_result: dict) -> None:
        """向报告行列表追加回归系数行（内部辅助方法）。

        Args:
            lines: 报告行列表（就地修改）。
            step_result: ols_regression 返回的结果字典。
        """
        coeffs = step_result.get("coefficients", {})
        std_errs = step_result.get("std_errors", {})
        p_vals = step_result.get("p_values", {})
        sigs = step_result.get("significant", {})

        for var in coeffs:
            c = coeffs[var]
            se = std_errs.get(var, 0)
            p = p_vals.get(var, 1)
            s = sigs.get(var, "")
            lines.append(f"| {var} | {c:.4f}{s} | ({se:.4f}) | {p:.4f} | {s} |")

    def _get_conclusion_section_num(
        self, sobel: dict | None, bootstrap: dict | None
    ) -> str:
        """根据是否有 Sobel/Bootstrap 结果确定结论部分的编号。

        Args:
            sobel: Sobel 检验结果（可能为 None）。
            bootstrap: Bootstrap 检验结果（可能为 None）。

        Returns:
            中文编号字符串，如 "三"、"四"、"五"。
        """
        extra_count = 0
        if sobel is not None:
            extra_count += 1
        if bootstrap is not None:
            extra_count += 1
        # 效应分解是"二"，结论是 二 + extra_count + 1
        num_map = {0: "三", 1: "四", 2: "五"}
        return num_map.get(extra_count, "三")


__all__ = [
    "MediationAnalysis",
    "_significance_stars",
]
