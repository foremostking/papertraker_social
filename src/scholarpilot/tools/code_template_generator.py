"""实证分析代码模板生成器。

根据论文 SPEC 自动生成 Stata / R / Python 代码模板，
覆盖完整实证分析流程：数据预处理 -> 描述性统计 -> 基准回归 -> 诊断检验 ->
稳健性检验 -> 输出回归表。同时根据 SPEC 中提到的方法关键词智能追加
IV / DID / PSM / 中介效应 / 空间计量 等额外模板段落。

典型用法::

    from scholarpilot.tools.code_template_generator import CodeTemplateGenerator

    gen = CodeTemplateGenerator()
    code = gen.generate_stata_template(spec_text)
    code = gen.generate_full_template(spec_text, lang="stata")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class CodeTemplateGenerator:
    """实证分析代码模板生成器。"""

    def __init__(self, project_dir: Path | None = None):
        """初始化，可传入项目目录。

        Args:
            project_dir: 项目目录路径，用于后续读取 SPEC.json 等文件。
        """
        self.project_dir = project_dir

    # ==================================================================
    # 公开接口
    # ==================================================================

    def generate_stata_template(self, spec_text: str, title: str = "") -> str:
        """生成 Stata .do 文件模板。

        包含完整流程：环境设置 -> 数据导入 -> 预处理(缩尾) -> 描述性统计 ->
        相关系数 -> 基准回归(OLS+FE+RE) -> 诊断检验(VIF+Hausman) ->
        稳健性检验(替换变量/增控制/子样本/滞后) -> 输出回归表。

        Args:
            spec_text: 论文 SPEC 文本（Markdown 或 JSON 字符串）。
            title: 论文标题，用于文件头部注释。

        Returns:
            Stata .do 文件内容字符串。
        """
        v = self._extract_variables_from_spec(spec_text)
        dep = v["dep_var"]
        indep = v["indep_var"]
        controls = v["controls"]
        controls_str = " ".join(controls)
        entity_var = v["entity_var"]
        time_var = v["time_var"]

        header = title or v.get("title", "") or "实证分析"

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append(f"* {header}")
        lines.append("* 自动生成 by ScholarPilot CodeTemplateGenerator")
        lines.append("* 说明：请将 [DATA_PATH] 替换为实际数据文件路径后即可运行")
        lines.append("*===============================================================================")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 1. 环境设置")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("clear all")
        lines.append("set more off")
        lines.append("set matsize 10000")
        lines.append("capture log close")
        lines.append('log using "empirical_analysis.log", replace text')
        lines.append("")
        lines.append("* 安装外部命令（首次运行需取消注释）")
        lines.append("* ssc install estout, replace")
        lines.append("* ssc install winsor2, replace")
        lines.append("* ssc install reghdfe, replace")
        lines.append("* ssc install vif2, replace")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 2. 数据导入")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append('* 请将下方路径替换为实际数据文件路径')
        lines.append('import excel "[DATA_PATH]", firstrow clear')
        lines.append("* 或使用：use \"[DATA_PATH].dta\", clear")
        lines.append("")
        lines.append("* 设置面板数据结构")
        if entity_var and time_var:
            lines.append(f"encode {entity_var}, gen({entity_var}_id)")
            lines.append(f"xtset {entity_var}_id {time_var}")
        else:
            lines.append("* encode province, gen(province_id)")
            lines.append("* xtset province_id year")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 3. 数据预处理")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 3.1 缩尾处理（消除极端值影响，上下1%）")
        if controls:
            all_vars_for_winsor = " ".join([dep, indep] + controls)
        else:
            all_vars_for_winsor = f"{dep} {indep}"
        lines.append(f"winsor2 {all_vars_for_winsor}, replace cuts(1 99)")
        lines.append("")
        lines.append("* 3.2 生成对数变量（如需要）")
        lines.append(f"* gen ln_{dep} = ln({dep})")
        lines.append(f"* gen ln_{indep} = ln({indep})")
        lines.append("")
        lines.append("* 3.3 描述性统计")
        lines.append(f"summarize {dep} {indep} {controls_str}")
        lines.append(f"estpost summarize {dep} {indep} {controls_str}")
        lines.append('esttab using "descriptive_stats.rtf", replace cells("count mean sd min p50 max")')
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 4. 相关系数矩阵")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"pwcorr {dep} {indep} {controls_str}, sig star(0.05)")
        lines.append(f"estpost correlate {dep} {indep} {controls_str}")
        lines.append('esttab using "correlation.rtf", replace unstack not noobs compress')
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 5. 基准回归")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 5.1 OLS 混合回归")
        lines.append(f"reg {dep} {indep} {controls_str}, robust")
        lines.append("est store ols")
        lines.append("")
        lines.append("* 5.2 固定效应模型（FE）")
        if entity_var:
            lines.append(f"xtreg {dep} {indep} {controls_str} i.{time_var}, fe vce(cluster {entity_var}_id)")
        else:
            lines.append(f"xtreg {dep} {indep} {controls_str}, fe vce(cluster province_id)")
        lines.append("est store fe")
        lines.append("")
        lines.append("* 5.3 随机效应模型（RE）")
        if entity_var:
            lines.append(f"xtreg {dep} {indep} {controls_str}, re vce(cluster {entity_var}_id)")
        else:
            lines.append(f"xtreg {dep} {indep} {controls_str}, re vce(cluster province_id)")
        lines.append("est store re")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 6. 诊断检验")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 6.1 多重共线性检验（VIF）")
        lines.append(f"reg {dep} {indep} {controls_str}")
        lines.append("vif")
        lines.append("")
        lines.append("* 6.2 Hausman 检验（FE vs RE）")
        lines.append("hausman fe re")
        lines.append("")
        lines.append("* 6.3 修正沃尔德检验（组间异方差）")
        lines.append(f"xttest3")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 7. 稳健性检验")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 7.1 替换被解释变量")
        lines.append(f"* reg {dep}_alt {indep} {controls_str}, robust")
        lines.append("est store rob1")
        lines.append("")
        lines.append("* 7.2 替换核心解释变量")
        lines.append(f"* reg {dep} {indep}_alt {controls_str}, robust")
        lines.append("est store rob2")
        lines.append("")
        lines.append("* 7.3 增加控制变量")
        lines.append(f"* reg {dep} {indep} {controls_str} extra_control, robust")
        lines.append("est store rob3")
        lines.append("")
        lines.append("* 7.4 子样本回归")
        lines.append(f"* reg {dep} {indep} {controls_str} if {time_var}>=2015, robust")
        lines.append("est store rob4")
        lines.append("")
        lines.append("* 7.5 滞后解释变量")
        if entity_var:
            lines.append(f"xtreg {dep} L.{indep} {controls_str}, fe vce(cluster {entity_var}_id)")
        else:
            lines.append(f"xtreg {dep} L.{indep} {controls_str}, fe vce(cluster province_id)")
        lines.append("est store rob5")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 8. 输出回归表")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 基准回归表（显著性星号：* p<0.10, ** p<0.05, *** p<0.01）")
        lines.append(
            'esttab ols fe re using "baseline_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            "stats(N r2 r2_a F, labels(\"观测数\" \"R方\" \"调整R方\" \"F统计量\")) "
            "mtitles(\"OLS\" \"固定效应\" \"随机效应\") "
            'title("基准回归结果") compress nogaps'
        )
        lines.append("")
        lines.append("* 稳健性检验表")
        lines.append(
            'esttab rob1 rob2 rob3 rob4 rob5 using "robustness_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            "stats(N r2, labels(\"观测数\" \"R方\")) "
            "mtitles(\"替换被解释变量\" \"替换解释变量\" \"增加控制\" \"子样本\" \"滞后\") "
            'title("稳健性检验结果") compress nogaps'
        )
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("log close")
        lines.append("*============================== End of Do-File ================================")

        return "\n".join(lines)

    def generate_r_template(self, spec_text: str, title: str = "") -> str:
        """生成 R 脚本模板。

        使用 fixest / modelsummary / ggplot2 包实现完整实证分析流程。

        Args:
            spec_text: 论文 SPEC 文本。
            title: 论文标题。

        Returns:
            R 脚本内容字符串。
        """
        v = self._extract_variables_from_spec(spec_text)
        dep = v["dep_var"]
        indep = v["indep_var"]
        controls = v["controls"]
        controls_r = " + ".join(controls)
        entity_var = v["entity_var"] or "entity"
        time_var = v["time_var"] or "year"

        header = title or v.get("title", "") or "Empirical Analysis"

        lines: list[str] = []
        lines.append("# ===============================================================================")
        lines.append(f"# {header}")
        lines.append("# Auto-generated by ScholarPilot CodeTemplateGenerator")
        lines.append("# ===============================================================================")
        lines.append("")
        lines.append("# 1. 加载包 -------------------------------------------------------------------")
        lines.append("library(tidyverse)")
        lines.append("library(fixest)        # 高效固定效应回归")
        lines.append("library(modelsummary)  # 回归结果输出")
        lines.append("library(ggplot2)       # 可视化")
        lines.append("library(sandwich)      # 稳健标准误")
        lines.append("library(lmtest)        # 检验")
        lines.append("library(plm)           # 面板数据")
        lines.append("")
        lines.append("# 2. 数据导入 -----------------------------------------------------------------")
        lines.append('# 请将路径替换为实际数据文件路径')
        lines.append('df <- read_csv("[DATA_PATH]")')
        lines.append("")
        lines.append("# 设置面板数据")
        lines.append(f"df <- pdata.frame(df, index = c(\"{entity_var}\", \"{time_var}\"))")
        lines.append("")
        lines.append("# 3. 数据预处理 ---------------------------------------------------------------")
        lines.append("# 3.1 缩尾处理")
        all_vars_r_list = [dep, indep] + controls
        all_vars_r_str = ", ".join(f'"{v}"' for v in all_vars_r_list)
        lines.append(f"vars <- c({all_vars_r_str})")
        lines.append("df <- df %>%")
        lines.append("  mutate(across(all_of(vars), ~ Winsorize(.x, probs = c(0.01, 0.99))))")
        lines.append("")
        lines.append("# 3.2 描述性统计")
        lines.append("datasummary_skim(df, output = \"descriptive_stats.html\")")
        lines.append("")
        lines.append("# 3.3 相关系数矩阵")
        lines.append(f"cor_matrix <- cor(df[, vars], use = \"complete.obs\")")
        lines.append("print(cor_matrix)")
        lines.append("")
        lines.append("# 4. 基准回归 -----------------------------------------------------------------")
        fml_parts = [indep] + controls
        fml_rhs = " + ".join(fml_parts)
        lines.append("# 4.1 混合 OLS")
        lines.append(f"m_ols <- lm({dep} ~ {fml_rhs}, data = df)")
        lines.append("summary(m_ols)")
        lines.append("")
        lines.append("# 4.2 固定效应（使用 fixest::feols）")
        lines.append(f'm_fe <- feols({dep} ~ {fml_rhs} | {entity_var} + {time_var}, data = df, cluster = "{entity_var}")')
        lines.append("summary(m_fe)")
        lines.append("")
        lines.append("# 4.3 随机效应")
        lines.append(f"m_re <- plm({dep} ~ {fml_rhs}, data = df, model = \"random\")")
        lines.append("summary(m_re)")
        lines.append("")
        lines.append("# 5. 诊断检验 -----------------------------------------------------------------")
        lines.append("# 5.1 VIF")
        lines.append(f"car::vif(lm({dep} ~ {fml_rhs}, data = df))")
        lines.append("")
        lines.append("# 5.2 Hausman 检验")
        lines.append("phtest(m_fe, m_re)")
        lines.append("")
        lines.append("# 6. 稳健性检验 ---------------------------------------------------------------")
        lines.append("# 6.1 子样本")
        lines.append(f'm_rob1 <- feols({dep} ~ {fml_rhs} | {entity_var} + {time_var}, ')
        lines.append(f'           data = subset(df, {time_var} >= 2015), cluster = "{entity_var}")')
        lines.append("")
        lines.append("# 6.2 滞后解释变量")
        lines.append(f'm_rob2 <- feols({dep} ~ lag({indep}, 1) + {controls_r} | {entity_var} + {time_var}, ')
        lines.append(f'           data = df, cluster = "{entity_var}")')
        lines.append("")
        lines.append("# 7. 输出回归表 ---------------------------------------------------------------")
        lines.append("models <- list(")
        lines.append('  "OLS" = m_ols,')
        lines.append('  "FE" = m_fe,')
        lines.append('  "RE" = m_re')
        lines.append(")")
        lines.append("")
        lines.append('modelsummary(models,')
        lines.append('  output = "baseline_regression.docx",')
        lines.append('  stars = TRUE,')
        lines.append('  statistic = "std.error",')
        lines.append('  gof_omit = "IC|Log|Adj|RMSE|F|Within",')
        lines.append('  title = "基准回归结果"')
        lines.append(")")
        lines.append("")
        lines.append("models_rob <- list(")
        lines.append('  "子样本" = m_rob1,')
        lines.append('  "滞后" = m_rob2')
        lines.append(")")
        lines.append('modelsummary(models_rob,')
        lines.append('  output = "robustness_regression.docx",')
        lines.append('  stars = TRUE,')
        lines.append('  title = "稳健性检验结果"')
        lines.append(")")
        lines.append("")
        lines.append("# 8. 可视化 -------------------------------------------------------------------")
        lines.append(f'ggplot(df, aes(x = {indep}, y = {dep})) +')
        lines.append('  geom_point(alpha = 0.5) +')
        lines.append('  geom_smooth(method = "lm", color = "red") +')
        lines.append('  theme_minimal() +')
        lines.append(f'  labs(title = "{dep} vs {indep}", x = "{indep}", y = "{dep}")')
        lines.append('ggsave("scatter_plot.png", width = 8, height = 6)')
        lines.append("")
        lines.append("# ============================== End of R Script ===============================")

        return "\n".join(lines)

    def generate_python_template(self, spec_text: str, title: str = "") -> str:
        """生成 Python Notebook 模板。

        使用 statsmodels / linearmodels / pandas / matplotlib 实现完整实证分析流程。

        Args:
            spec_text: 论文 SPEC 文本。
            title: 论文标题。

        Returns:
            Python 脚本内容字符串。
        """
        v = self._extract_variables_from_spec(spec_text)
        dep = v["dep_var"]
        indep = v["indep_var"]
        controls = v["controls"]
        controls_py = " + ".join(controls)
        entity_var = v["entity_var"] or "entity"
        time_var = v["time_var"] or "year"

        header = title or v.get("title", "") or "Empirical Analysis"

        lines: list[str] = []
        lines.append('# ===============================================================================')
        lines.append(f'# {header}')
        lines.append('# Auto-generated by ScholarPilot CodeTemplateGenerator')
        lines.append('# ===============================================================================')
        lines.append("")
        lines.append("# %% [markdown]")
        lines.append("# # 1. 环境设置与数据导入")
        lines.append("")
        lines.append("# %%")
        lines.append("import numpy as np")
        lines.append("import pandas as pd")
        lines.append("import statsmodels.api as sm")
        lines.append("from statsmodels.stats.outliers_influence import variance_inflation_factor")
        lines.append("from linearmodels.panel import PanelOLS, RandomEffects, compare")
        lines.append("import matplotlib.pyplot as plt")
        lines.append("import warnings")
        lines.append("warnings.filterwarnings('ignore')")
        lines.append("")
        lines.append("# 请将路径替换为实际数据文件路径")
        lines.append('df = pd.read_excel("[DATA_PATH]")')
        lines.append("")
        lines.append("# 设置面板索引")
        lines.append(f'df = df.set_index(["{entity_var}", "{time_var}"])')
        lines.append("")
        lines.append("# %% [markdown]")
        lines.append("# # 2. 数据预处理")
        lines.append("")
        lines.append("# %%")
        lines.append("# 2.1 缩尾处理（上下1%）")
        all_vars_py = [dep, indep] + controls
        lines.append("vars_to_winsorize = " + repr(all_vars_py))
        lines.append("for col in vars_to_winsorize:")
        lines.append("    lower = df[col].quantile(0.01)")
        lines.append("    upper = df[col].quantile(0.99)")
        lines.append("    df[col] = df[col].clip(lower, upper)")
        lines.append("")
        lines.append("# 2.2 描述性统计")
        lines.append(f"desc = df[vars_to_winsorize].describe()")
        lines.append("print(desc)")
        lines.append("desc.to_csv('descriptive_stats.csv')")
        lines.append("")
        lines.append("# %% [markdown]")
        lines.append("# # 3. 相关系数矩阵")
        lines.append("")
        lines.append("# %%")
        lines.append(f"corr = df[vars_to_winsorize].corr()")
        lines.append("print(corr)")
        lines.append("")
        lines.append("# %% [markdown]")
        lines.append("# # 4. 基准回归")
        lines.append("")
        lines.append("# %%")
        exog_vars = [indep] + controls
        exog_str = " + ".join(exog_vars)
        lines.append(f'exog_vars = {exog_vars!r}')
        lines.append("X = sm.add_constant(df[exog_vars])")
        lines.append("")
        lines.append("# 4.1 混合 OLS")
        lines.append(f"m_ols = sm.OLS(df['{dep}'], X).fit(cov_type='HC1')")
        lines.append("print(m_ols.summary())")
        lines.append("")
        lines.append("# 4.2 固定效应模型")
        lines.append(f"m_fe = PanelOLS(df['{dep}'], df[exog_vars], ")
        lines.append(f"    entity_effects=True, time_effects=True).fit(cov_type='clustered')")
        lines.append("print(m_fe.summary)")
        lines.append("")
        lines.append("# 4.3 随机效应模型")
        lines.append(f"m_re = RandomEffects(df['{dep}'], df[exog_vars]).fit()")
        lines.append("print(m_re.summary)")
        lines.append("")
        lines.append("# %% [markdown]")
        lines.append("# # 5. 诊断检验")
        lines.append("")
        lines.append("# %%")
        lines.append("# 5.1 VIF 多重共线性检验")
        lines.append("for i, col in enumerate(X.columns):")
        lines.append("    if col != 'const':")
        lines.append("        vif = variance_inflation_factor(X.values, i)")
        lines.append("        print(f'{col}: VIF = {vif:.2f}')")
        lines.append("")
        lines.append("# 5.2 Hausman 检验")
        lines.append("from scipy import stats")
        lines.append("b_fe = m_fe.params")
        lines.append("b_re = m_re.params")
        lines.append("common = b_fe.index.intersection(b_re.index)")
        lines.append("diff = b_fe[common] - b_re[common]")
        lines.append("var_diff = np.diag(m_fe.cov.loc[common, common]) - np.diag(m_re.cov.loc[common, common])")
        lines.append("hausman_stat = diff.T @ np.linalg.inv(var_diff) @ diff")
        lines.append("p_value = 1 - stats.chi2.cdf(hausman_stat, len(common))")
        lines.append("print(f'Hausman 检验: chi2={hausman_stat:.4f}, p={p_value:.4f}')")
        lines.append("")
        lines.append("# %% [markdown]")
        lines.append("# # 6. 稳健性检验")
        lines.append("")
        lines.append("# %%")
        lines.append("# 6.1 子样本回归")
        lines.append(f'df_sub = df[df.index.get_level_values("{time_var}") >= 2015]')
        lines.append(f"m_rob1 = PanelOLS(df_sub['{dep}'], df_sub[exog_vars], ")
        lines.append(f"    entity_effects=True).fit(cov_type='clustered')")
        lines.append("")
        lines.append("# 6.2 滞后解释变量")
        lines.append(f"df['{indep}_lag'] = df['{indep}'].groupby(level=0).shift(1)")
        lines.append(f"exog_lag = ['{indep}_lag'] + {controls!r}")
        lines.append(f"m_rob2 = PanelOLS(df['{dep}'], df[exog_lag].dropna(), ")
        lines.append(f"    entity_effects=True).fit(cov_type='clustered')")
        lines.append("")
        lines.append("# %% [markdown]")
        lines.append("# # 7. 输出回归表")
        lines.append("")
        lines.append("# %%")
        lines.append("from statsmodels.iolib.summary2 import summary_col")
        lines.append("results = {'OLS': m_ols, 'FE': m_fe, 'RE': m_re}")
        lines.append("table = summary_col([m_ols], stars=True, ")
        lines.append("    float_format='%.3f',")
        lines.append("    info_dict={'N': lambda r: f'{int(r.nobs)}',")
        lines.append("               'R2': lambda r: f'{r.rsquared:.3f}'})")
        lines.append("print(table)")
        lines.append("with open('regression_results.txt', 'w') as f:")
        lines.append("    f.write(str(table))")
        lines.append("")
        lines.append("# %% [markdown]")
        lines.append("# # 8. 可视化")
        lines.append("")
        lines.append("# %%")
        lines.append(f"fig, ax = plt.subplots(figsize=(8, 6))")
        lines.append(f"ax.scatter(df['{indep}'], df['{dep}'], alpha=0.5)")
        lines.append("ax.set_xlabel(f'{indep}')")
        lines.append("ax.set_ylabel(f'{dep}')")
        lines.append(f"ax.set_title(f'{dep} vs {indep}')")
        lines.append("plt.tight_layout()")
        lines.append("plt.savefig('scatter_plot.png', dpi=150)")
        lines.append("plt.show()")
        lines.append("")
        lines.append("# ============================= End of Python Script ============================")

        return "\n".join(lines)

    def generate_full_template(self, spec_text: str, lang: str = "stata", title: str = "") -> str:
        """生成完整模板（基础流程 + 根据SPEC关键词智能追加额外模板）。

        Args:
            spec_text: 论文 SPEC 文本。
            lang: 目标语言，"stata" / "r" / "python"。
            title: 论文标题。

        Returns:
            完整代码模板字符串。
        """
        # 生成基础模板
        if lang == "stata":
            base = self.generate_stata_template(spec_text, title)
        elif lang == "r":
            base = self.generate_r_template(spec_text, title)
        elif lang == "python":
            base = self.generate_python_template(spec_text, title)
        else:
            raise ValueError(f"不支持的语言: {lang}，请使用 stata / r / python")

        # 检测方法关键词
        kw = self._detect_method_keywords(spec_text)
        v = self._extract_variables_from_spec(spec_text)

        # 追加额外模板段落（仅 Stata 支持完整额外模板，
        # R 和 Python 也提供对应段落）
        extra_parts: list[str] = []

        if kw["has_iv"] or kw["has_endogeneity"]:
            extra_parts.append(self._generate_iv_template(v))

        if kw["has_did"]:
            extra_parts.append(self._generate_did_template(v))

        if kw["has_psm"]:
            extra_parts.append(self._generate_psm_template(v))

        if kw["has_mediation"]:
            extra_parts.append(self._generate_mediation_template(v))

        if kw["has_spatial"]:
            extra_parts.append(self._generate_spatial_template(v))

        if kw["has_threshold"]:
            extra_parts.append(self._generate_threshold_template(v, spec_text))

        if kw["has_rdd"]:
            extra_parts.append(self._generate_rdd_template(v, spec_text))

        if kw["has_scm"]:
            extra_parts.append(self._generate_scm_template(v, spec_text))

        if kw["has_heckman"]:
            extra_parts.append(self._generate_heckman_template(v, spec_text))

        if kw["has_gmm"]:
            extra_parts.append(self._generate_gmm_template(v))

        if kw["has_var"]:
            extra_parts.append(self._generate_var_template(v))

        if kw["has_event_study"]:
            extra_parts.append(self._generate_event_study_template(v))

        if kw["has_ipw"]:
            extra_parts.append(self._generate_ipw_template(v))

        if kw["has_quantile"]:
            extra_parts.append(self._generate_quantile_template(v))

        if kw["has_discrete"]:
            extra_parts.append(self._generate_discrete_template(v))

        if extra_parts:
            separator = "\n\n" + "=" * 80 + "\n"
            extra_section = (
                separator
                + "* 以下为根据 SPEC 方法关键词智能追加的分析模板\n"
                + separator
                + "\n".join(extra_parts)
            )
            return base + "\n" + extra_section

        return base

    # ==================================================================
    # SPEC 解析
    # ==================================================================

    def _extract_variables_from_spec(self, spec_text: str) -> dict:
        """从SPEC提取变量定义。

        解析策略与 scholar.py 中的 _extract_variables_from_spec 类似，
        但返回更适合代码生成的字典结构。

        Args:
            spec_text: SPEC 文本（Markdown 或 JSON 字符串）。

        Returns:
            包含变量信息的字典::

                {
                    "dep_var": str,           # 被解释变量名
                    "indep_var": str,         # 核心解释变量名
                    "controls": list[str],    # 控制变量名列表
                    "all_variables": list[str],  # 所有变量名列表
                    "model_text": str,        # 模型设定段落原文
                    "entity_var": str,        # 个体/截面变量名
                    "time_var": str,          # 时间变量名
                    "title": str,             # 研究主题
                }
        """
        dep_var = ""
        indep_var = ""
        controls: list[str] = []

        # 提取研究主题
        title = ""
        title_match = re.search(
            r"研究主题[：:\s\n]+(.*?)(?=研究类型|变量设计|变量定义|模型设定|$)",
            spec_text, re.DOTALL | re.IGNORECASE,
        )
        if title_match:
            title = title_match.group(1).strip().split("\n")[0].strip()

        # 提取变量定义段落
        var_section_patterns = [
            r"变量设计[：:\s\n]+(.*?)(?=模型设定|稳健性|预期结果|研究方法|数据需求|$)",
            r"变量定义[：:\s\n]+(.*?)(?=模型设定|稳健性|预期结果|研究方法|数据需求|$)",
            r"核心变量[：:\s\n]+(.*?)(?=模型设定|稳健性|预期结果|研究方法|数据需求|$)",
        ]

        var_section = ""
        for pattern in var_section_patterns:
            match = re.search(pattern, spec_text, re.DOTALL | re.IGNORECASE)
            if match:
                var_section = match.group(1)
                break

        # 提取被解释变量
        dep_patterns = [
            r"(?:被解释变量|因变量|dependent variable)[：:]\s*(\w+)",
            r"[-•]\s*(?:被解释变量|因变量)[：:]\s*(\w+)",
            r"[-•]\s*(?:被解释变量|因变量)[：:]\s*\w+[（(](\w+)",
        ]
        for pattern in dep_patterns:
            match = re.search(pattern, spec_text, re.IGNORECASE)
            if match:
                dep_var = match.group(1).strip()
                break

        # 提取核心解释变量
        # 注意：必须先用"核心解释变量"精确匹配，避免"解释变量"匹配到"被解释变量"
        indep_patterns = [
            r"核心解释变量[：:]\s*(\w+)",
            r"[-•]\s*核心解释变量[：:]\s*(\w+)",
            r"(?<!被)解释变量[：:]\s*(\w+)",
            r"自变量[：:]\s*(\w+)",
            r"independent variable[：:]\s*(\w+)",
            r"[-•]\s*(?<!被)解释变量[：:]\s*(\w+)",
        ]
        for pattern in indep_patterns:
            match = re.search(pattern, spec_text, re.IGNORECASE)
            if match:
                indep_var = match.group(1).strip()
                break

        # 提取控制变量
        control_patterns = [
            r"[-•]\s*控制变量[：:]\s*(\w+)",
            r"控制变量[：:]\s*(\w+)",
        ]
        for match in re.finditer(r"[-•]\s*控制变量[：:]\s*(\w+)", spec_text, re.IGNORECASE):
            ctrl = match.group(1).strip()
            if ctrl and ctrl not in controls:
                controls.append(ctrl)

        # 如果没有按行提取到控制变量，尝试从一行中提取多个
        if not controls:
            ctrl_line_match = re.search(
                r"控制变量[：:]\s*(.+?)(?:\n|$)", spec_text, re.IGNORECASE,
            )
            if ctrl_line_match:
                ctrl_text = ctrl_line_match.group(1)
                # 尝试提取变量名（支持逗号、顿号分隔）
                for part in re.split(r"[、,，;；]", ctrl_text):
                    name_match = re.match(r"\s*(\w+)", part)
                    if name_match:
                        ctrl = name_match.group(1).strip()
                        if ctrl and ctrl not in controls:
                            controls.append(ctrl)

        # 提取模型设定文本
        model_text = ""
        model_section_patterns = [
            r"模型设定[：:\s\n]+(.*?)(?=预期结果|数据需求|$)",
            r"计量模型[：:\s\n]+(.*?)(?=预期结果|数据需求|$)",
        ]
        for pattern in model_section_patterns:
            match = re.search(pattern, spec_text, re.DOTALL | re.IGNORECASE)
            if match:
                model_text = match.group(1).strip()
                break

        # 从模型设定/数据需求中提取个体变量和时间变量
        entity_var = ""
        time_var = ""

        # 提取个体变量（省份、城市、企业等）
        entity_patterns = [
            r"(\d+)个?省份",
            r"省份",
            r"(\d+)个?城市",
            r"城市",
            r"(\d+)家?企业",
            r"企业",
            r"截面单元[：:]\s*(\S+)",
        ]
        for pattern in entity_patterns:
            match = re.search(pattern, spec_text, re.IGNORECASE)
            if match:
                entity_text = match.group(0)
                if "省" in entity_text:
                    entity_var = "province"
                elif "城" in entity_text:
                    entity_var = "city"
                elif "企" in entity_text:
                    entity_var = "firm"
                else:
                    entity_var = match.group(1).strip() if match.lastindex else "entity"
                break

        # 提取时间变量
        time_match = re.search(r"(\d{4})[-–—](\d{4})", spec_text)
        if time_match:
            time_var = "year"
        else:
            time_match2 = re.search(r"面板数据", spec_text, re.IGNORECASE)
            if time_match2:
                time_var = "year"

        # 汇总所有变量
        all_variables: list[str] = []
        if dep_var:
            all_variables.append(dep_var)
        if indep_var and indep_var not in all_variables:
            all_variables.append(indep_var)
        for c in controls:
            if c not in all_variables:
                all_variables.append(c)

        return {
            "dep_var": dep_var,
            "indep_var": indep_var,
            "controls": controls,
            "all_variables": all_variables,
            "model_text": model_text,
            "entity_var": entity_var,
            "time_var": time_var,
            "title": title,
        }

    def _detect_method_keywords(self, spec_text: str) -> dict:
        """检测SPEC中提到的方法关键词。

        Args:
            spec_text: SPEC 文本。

        Returns:
            方法关键词检测结果字典::

                {
                    "has_endogeneity": bool,  # 内生性
                    "has_did": bool,          # 双重差分
                    "has_psm": bool,          # 倾向得分匹配
                    "has_mediation": bool,    # 中介/调节效应
                    "has_spatial": bool,      # 空间计量
                    "has_iv": bool,           # 工具变量
                }
        """
        text_lower = spec_text.lower()

        has_iv = any(
            kw in spec_text for kw in ["工具变量", "IV", "2SLS", "两阶段最小二乘"]
        ) or any(kw in text_lower for kw in ["instrumental variable"])

        has_endogeneity = any(
            kw in spec_text for kw in ["内生性", "内生", "endogeneity"]
        ) or has_iv

        has_did = any(
            kw in spec_text for kw in ["准自然实验", "政策冲击", "DID", "双重差分", "倍差法"]
        ) or any(kw in text_lower for kw in ["difference-in-difference", "did "])

        has_psm = any(
            kw in spec_text for kw in ["匹配", "PSM", "倾向得分", "propensity score"]
        ) or any(kw in text_lower for kw in ["psm", "propensity score matching"])

        has_mediation = any(
            kw in spec_text for kw in ["机制", "中介", "调节", "mediation", "moderation", "mechanism"]
        )

        has_spatial = any(
            kw in spec_text for kw in ["空间", "溢出", "spatial", "spillover", "空间权重", "空间杜宾", "空间自回归"]
        ) or any(kw in text_lower for kw in ["spatial", "morans i", "sar model", "sem model", "sdm"])

        has_threshold = any(
            kw in spec_text for kw in ["门槛", "threshold", "xthreg", "Hansen"]
        ) or any(kw in text_lower for kw in ["threshold model", "panel threshold"])

        has_rdd = any(
            kw in spec_text for kw in ["断点回归", "RDD", "rdrobust", "运行变量", "断点值"]
        ) or any(kw in text_lower for kw in ["regression discontinuity", "rdrobust"])

        has_scm = any(
            kw in spec_text for kw in ["合成控制", "SCM", "synth", "反事实对照"]
        ) or any(kw in text_lower for kw in ["synthetic control", "synth"])

        has_heckman = any(
            kw in spec_text for kw in ["Heckman", "heckman", "样本选择", "选择偏差", "选择偏误"]
        ) or any(kw in text_lower for kw in ["heckman", "sample selection"])

        has_gmm = any(
            kw in spec_text for kw in ["GMM", "广义矩", "动态面板GMM", "系统GMM", "xtabond", "差分GMM"]
        ) or any(kw in text_lower for kw in ["gmm", "generalized method of moments", "xtabond2"])

        has_var = any(
            kw in spec_text for kw in ["VAR模型", "VAR分析", "向量自回归", "脉冲响应", "格兰杰因果", "方差分解"]
        ) or any(kw in text_lower for kw in ["vector autoregression", "var model", "impulse response", "granger causality"])

        has_event_study = any(
            kw in spec_text for kw in ["事件研究", "异常收益率", "累计异常收益", "累计超额收益"]
        ) or any(kw in text_lower for kw in ["event study", "car ", "abnormal return"])

        has_ipw = any(
            kw in spec_text for kw in ["逆概率加权", "IPW", "双重稳健", "倾向得分加权"]
        ) or any(kw in text_lower for kw in ["inverse probability weighting", "ipw", "doubly robust"])

        has_quantile = any(
            kw in spec_text for kw in ["分位数回归", "分位点回归", "quantile"]
        ) or any(kw in text_lower for kw in ["quantile regression", "qreg"])

        has_discrete = any(
            kw in spec_text for kw in ["Logit", "Probit", "Tobit", "离散选择", "二元选择"]
        ) or any(kw in text_lower for kw in ["logit model", "probit model", "tobit model", "discrete choice"])

        return {
            "has_endogeneity": has_endogeneity,
            "has_did": has_did,
            "has_psm": has_psm,
            "has_mediation": has_mediation,
            "has_spatial": has_spatial,
            "has_iv": has_iv,
            "has_threshold": has_threshold,
            "has_rdd": has_rdd,
            "has_scm": has_scm,
            "has_heckman": has_heckman,
            "has_gmm": has_gmm,
            "has_var": has_var,
            "has_event_study": has_event_study,
            "has_ipw": has_ipw,
            "has_quantile": has_quantile,
            "has_discrete": has_discrete,
        }

    # ==================================================================
    # 额外模板段落生成
    # ==================================================================

    def _generate_iv_template(self, vars: dict) -> str:
        """生成IV/2SLS代码段落。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata IV/2SLS 代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{indep_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"
        entity_var = vars.get("entity_var", "province")

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* IV / 2SLS 工具变量回归")
        lines.append("*===============================================================================")
        lines.append("* 第一步：工具变量回归（检验工具变量相关性）")
        lines.append(f"* 请将 [IV_VAR] 替换为实际工具变量名")
        lines.append(f"reg {indep} [IV_VAR] {controls_str}, robust")
        lines.append("est store first_stage")
        lines.append("* F 统计量应大于 10（弱工具变量检验）")
        lines.append("test [IV_VAR]")
        lines.append("")
        lines.append("* 第二步：2SLS 回归")
        lines.append(f"ivregress 2sls {dep} {controls_str} ({indep} = [IV_VAR]), robust first")
        lines.append("est store iv_2sls")
        lines.append("")
        lines.append("* 弱工具变量检验")
        lines.append("estat firststage")
        lines.append("")
        lines.append("* 过度识别检验（需多个工具变量）")
        lines.append("* estat overid")
        lines.append("")
        lines.append("* 输出 IV 结果表")
        lines.append(
            'esttab first_stage iv_2sls using "iv_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            "stats(N r2, labels(\"观测数\" \"R方\")) "
            'mtitles("第一阶段" "2SLS") title("工具变量回归结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_did_template(self, vars: dict) -> str:
        """生成DID代码段落（含事件研究法平行趋势检验）。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata DID 代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{treat_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"
        entity_var = vars.get("entity_var", "province")
        time_var = vars.get("time_var", "year")

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* DID 双重差分分析")
        lines.append("*===============================================================================")
        lines.append("* 生成处理变量和政策时点变量")
        lines.append(f"* 请根据实际政策冲击设定 treat 和 post 变量")
        lines.append(f"gen treat = ...    /* 处理组标识：1=处理组, 0=控制组 */")
        lines.append(f"gen post = ...     /* 政策时点：1=政策实施后, 0=政策实施前 */")
        lines.append("gen did = treat * post")
        lines.append("")
        lines.append("* 基准 DID 回归")
        lines.append(f"reghdfe {dep} did {controls_str}, absorb({entity_var} {time_var}) vce(cluster {entity_var})")
        lines.append("est store did_baseline")
        lines.append("")
        lines.append("* 平行趋势检验（事件研究法）")
        lines.append(f"* 生成政策实施前后的相对时间虚拟变量")
        lines.append(f"gen event_time = {time_var} - policy_year  /* policy_year为政策实施年份 */")
        lines.append("")
        lines.append("* 生成事件研究虚拟变量（以 t=-1 为基准组）")
        lines.append("forvalues t = -5/5 {")
        lines.append("    if `t' != -1 {")
        lines.append("        gen pre`t' = (event_time == `t')")
        lines.append("    }")
        lines.append("}")
        lines.append("")
        lines.append(f"reghdfe {dep} pre* {controls_str}, absorb({entity_var} {time_var}) vce(cluster {entity_var})")
        lines.append("est store event_study")
        lines.append("")
        lines.append("* 绘制事件研究图（需 coefplot 命令）")
        lines.append("* ssc install coefplot, replace")
        lines.append("coefplot event_study, vertical drop(_cons) yline(0) xline(5.5, lpattern(dash))")
        lines.append("")
        lines.append("* 安慰剂检验（随机抽取处理组）")
        lines.append("* bootstrap, reps(500): reghdfe ...")
        lines.append("")
        lines.append("* 输出 DID 结果表")
        lines.append(
            'esttab did_baseline using "did_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            "stats(N r2, labels(\"观测数\" \"R方\")) "
            'mtitles("DID基准回归") title("双重差分回归结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_psm_template(self, vars: dict) -> str:
        """生成PSM代码段落。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata PSM 代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{treat_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"
        entity_var = vars.get("entity_var", "province")

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* PSM 倾向得分匹配分析")
        lines.append("*===============================================================================")
        lines.append("* 安装 PSM 相关命令")
        lines.append("* ssc install psmatch2, replace")
        lines.append("")
        lines.append("* 第一步：Logit 估计倾向得分")
        lines.append(f"psmatch2 {indep} {controls_str}, outcome({dep}) logit neighbor(1) ties common ate")
        lines.append("est store psm_result")
        lines.append("")
        lines.append("* 平衡性检验")
        lines.append("pstest {controls}, both graph")
        lines.append("")
        lines.append("* 核匹配（稳健性检验）")
        lines.append(f"psmatch2 {indep} {controls_str}, outcome({dep}) kernel ate")
        lines.append("est store psm_kernel")
        lines.append("")
        lines.append("* 半径匹配（稳健性检验）")
        lines.append(f"psmatch2 {indep} {controls_str}, outcome({dep}) radius caliper(0.05) ate")
        lines.append("est store psm_radius")
        lines.append("")
        lines.append("* 输出 PSM 结果表")
        lines.append(
            'esttab psm_result psm_kernel psm_radius using "psm_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'mtitles("最近邻匹配" "核匹配" "半径匹配") '
            'title("倾向得分匹配结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_mediation_template(self, vars: dict) -> str:
        """生成中介效应代码段落（Baron & Kenny三步法 + Sobel检验）。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata 中介效应代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{indep_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* 中介效应分析（Baron & Kenny 三步法 + Sobel 检验）")
        lines.append("*===============================================================================")
        lines.append("* 请将 [MEDIATOR] 替换为实际中介变量名")
        lines.append("* 路径：{0} -> [MEDIATOR] -> {1}".format(indep, dep))
        lines.append("")
        lines.append("* 第一步：核心解释变量对被解释变量的总效应")
        lines.append(f"reg {dep} {indep} {controls_str}, robust")
        lines.append("est store med_step1")
        lines.append("* 记录系数 c（总效应）")
        lines.append("")
        lines.append("* 第二步：核心解释变量对中介变量的效应")
        lines.append(f"reg [MEDIATOR] {indep} {controls_str}, robust")
        lines.append("est store med_step2")
        lines.append("* 记录系数 a（自变量对中介变量的效应）")
        lines.append("")
        lines.append("* 第三步：核心解释变量和中介变量同时对被解释变量的效应")
        lines.append(f"reg {dep} {indep} [MEDIATOR] {controls_str}, robust")
        lines.append("est store med_step3")
        lines.append("* 记录系数 c'（直接效应）和 b（中介变量对因变量的效应）")
        lines.append("")
        lines.append("* Sobel 检验（需安装 sgmediation2 命令）")
        lines.append("* ssc install sgmediation2, replace")
        lines.append(f"sgmediation2 {dep}, mv([MEDIATOR]) iv({indep}) cv({controls_str})")
        lines.append("")
        lines.append("* Bootstrap 中介效应（更稳健的检验方法）")
        lines.append("* ssc install medeff, replace")
        lines.append(f"* medeff (reg {dep} {indep} {controls_str}) (reg {dep} {indep} [MEDIATOR] {controls_str}), "
                      "treat({0}) sims(1000) seed(12345)".format(indep))
        lines.append("")
        lines.append("* 输出中介效应结果表")
        lines.append(
            'esttab med_step1 med_step2 med_step3 using "mediation_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'stats(N r2, labels("观测数" "R方")) '
            'mtitles("总效应(c)" "自变量->中介(a)" "直接效应(c)") '
            'title("中介效应分析结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_spatial_template(self, vars: dict) -> str:
        """生成空间计量代码段落（Moran's I + SAR/SEM/SDM）。

        包含空间权重矩阵构建、Moran's I检验、SAR/SEM/SDM模型估计、效应分解。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata 空间计量代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{indep_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"
        entity_var = vars.get("entity_var", "province")
        time_var = vars.get("time_var", "year")

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* 空间计量分析（Moran's I + SAR/SEM/SDM）")
        lines.append("*===============================================================================")
        lines.append("* 安装空间计量命令")
        lines.append("* ssc install spmat, replace")
        lines.append("* ssc install spreg, replace")
        lines.append("* ssc install xsmle, replace   /* 空间面板回归 */")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 1. 空间权重矩阵构建")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 1.1 导入地理坐标数据，构建反距离权重矩阵")
        lines.append("* spmat idistance dist_matrix using coords.dta, id({0}) normalize(row)".format(entity_var))
        lines.append("")
        lines.append("* 1.2 或构建 0-1 邻接权重矩阵（Queen 邻接）")
        lines.append("* spmat using queen_matrix.dta, id({0}) name(queen_W)".format(entity_var))
        lines.append("")
        lines.append("* 1.3 或构建 K-nearest 权重矩阵")
        lines.append("* spmat knn knn_matrix using coords.dta, id({0}) k(4) normalize(row)".format(entity_var))
        lines.append("")
        lines.append("* 以下假设已构建空间权重矩阵 W")
        lines.append("* spmat copy W using spatial_W, replace")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 2. Moran's I 检验（空间自相关检验）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 2.1 全局 Moran's I 检验")
        lines.append(f"spatwmat using spatial_W, name(W)")
        lines.append(f"spatgsa {dep}, weights(W) moran")
        lines.append("")
        lines.append("* 2.2 局部 Moran's I 检验（LISA 图）")
        lines.append(f"spatlsa {dep}, weights(W) localmoran id({entity_var})")
        lines.append("")
        lines.append("* 2.3 逐年 Moran's I 检验")
        lines.append(f"levelsof {time_var}, local(years)")
        lines.append("foreach y of local years {")
        lines.append(f"    di \"Year: `y'\"")
        lines.append(f"    spatgsa {dep} if {time_var}==`y', weights(W) moran")
        lines.append("}")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 3. LM 检验（选择 SAR 或 SEM 模型）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"spreg ml {dep} {indep} {controls_str}, id({entity_var}) dlmat(W) elmat(W)")
        lines.append("* 根据 LM-lag 和 LM-error 的显著性选择模型")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 4. 空间面板模型估计")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 4.1 空间自回归模型（SAR）")
        lines.append(f"xsmle {dep} {indep} {controls_str}, fe wmat(W) model(sar) effects(direct)")
        lines.append("est store spatial_sar")
        lines.append("")
        lines.append("* 4.2 空间误差模型（SEM）")
        lines.append(f"xsmle {dep} {indep} {controls_str}, fe wmat(W) model(sem)")
        lines.append("est store spatial_sem")
        lines.append("")
        lines.append("* 4.3 空间杜宾模型（SDM）—— 含空间滞后解释变量")
        lines.append(f"xsmle {dep} {indep} {controls_str}, fe wmat(W) model(sdm) durbin({indep} {controls_str})")
        lines.append("est store spatial_sdm")
        lines.append("")
        lines.append("* 4.4 LR 检验（SDM 是否可以简化为 SAR 或 SEM）")
        lines.append("* 如果 LR 检验不显著，则 SDM 可简化为 SAR 或 SEM")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 5. 效应分解（直接效应 / 间接效应 / 总效应）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* SDM 模型的效应分解")
        lines.append(f"xsmle {dep} {indep} {controls_str}, fe wmat(W) model(sdm) durbin({indep} {controls_str}) effects(direct)")
        lines.append("est store sdm_effects")
        lines.append("")
        lines.append("* 直接效应：本地区解释变量对本地区被解释变量的影响")
        lines.append("* 间接效应（溢出效应）：本地区解释变量对其他地区被解释变量的影响")
        lines.append("* 总效应：直接效应 + 间接效应")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 6. 稳健性检验：替换空间权重矩阵")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 使用反距离矩阵替代邻接矩阵")
        lines.append(f"* xsmle {dep} {indep} {controls_str}, fe wmat(W_dist) model(sdm) durbin({indep} {controls_str})")
        lines.append("est store sdm_robust")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 7. 输出空间计量结果表")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(
            'esttab spatial_sar spatial_sem spatial_sdm using "spatial_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            "stats(N r2, labels(\"观测数\" \"R方\")) "
            'mtitles("SAR" "SEM" "SDM") '
            'title("空间面板回归结果") compress nogaps'
        )
        lines.append("")
        lines.append("* 效应分解结果表")
        lines.append(
            'esttab sdm_effects using "spatial_effects.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'title("空间杜宾模型效应分解") compress nogaps'
        )
        stata_code = "\n".join(lines)

        # 追加 R 代码
        r_code = self._generate_spatial_r_template(vars)

        # 追加 Python 代码
        python_code = self._generate_spatial_python_template(vars)

        return stata_code + "\n\n" + r_code + "\n\n" + python_code

    def _generate_spatial_r_template(self, vars: dict) -> str:
        """生成 R 空间计量代码段落（spdep + spatialreg + spreg + splm）。

        包含空间权重矩阵构建（Queen 邻接 / K-nearest / 反距离）、
        Moran's I 检验（全局 + 局部 + 逐年）、LM 检验、
        SAR / SEM / SDM 横截面与面板模型估计、效应分解（impacts）、
        稳健性检验与结果输出。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            R 空间计量代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{indep_var}"
        controls = vars.get("controls", [])
        fml_rhs = " + ".join([indep] + controls) if controls else indep
        entity_var = vars.get("entity_var", "province")
        time_var = vars.get("time_var", "year")

        lines: list[str] = []
        lines.append("# ===============================================================================")
        lines.append("# 空间计量分析（R: spdep + spatialreg + spreg + splm）")
        lines.append("# ===============================================================================")
        lines.append("# 0. 加载包 ---------------------------------------------------------------------")
        lines.append('# install.packages(c("spdep", "spatialreg", "spreg", "splm", "sf", "stargazer"))')
        lines.append("library(spdep)        # 空间权重矩阵与 Moran's I")
        lines.append("library(spatialreg)   # 空间滞后/误差/杜宾模型（ML 估计）")
        lines.append("library(spreg)        # 空间横截面回归（GM 估计）")
        lines.append("library(splm)         # 面板空间线性模型（固定/随机效应）")
        lines.append("library(sf)           # 读取 shapefile / 空间几何")
        lines.append("library(stargazer)    # 回归结果输出")
        lines.append("library(dplyr)        # 数据处理")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 1. 空间权重矩阵构建")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 1.1 读取面板数据与地图数据")
        lines.append("# 请将路径替换为实际数据文件路径")
        lines.append('panel_df <- read.csv("[DATA_PATH]")')
        lines.append('map_sf <- st_read("[SHP_PATH]")   # 省份 shapefile')
        lines.append("")
        lines.append("# 1.2 构建 Queen 邻接权重矩阵")
        lines.append("nb_queen <- poly2nb(map_sf, queen = TRUE)")
        lines.append('W_queen <- nb2listw(nb_queen, style = "W")   # 行标准化')
        lines.append("")
        lines.append("# 1.3 构建 K-nearest 权重矩阵")
        lines.append("coords <- st_coordinates(st_centroid(map_sf))")
        lines.append("nb_knn <- knn2nb(knearneigh(coords, k = 4))")
        lines.append('W_knn <- nb2listw(nb_knn, style = "W")')
        lines.append("")
        lines.append("# 1.4 构建反距离权重矩阵")
        lines.append("dists <- nbdists(nb_queen, coords)")
        lines.append("ids <- lapply(dists, function(d) 1 / d)")
        lines.append('W_dist <- nb2listw(nb_queen, glist = ids, style = "W")')
        lines.append("")
        lines.append("# 以下默认使用 Queen 邻接权重矩阵 W_queen")
        lines.append("W <- W_queen")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 2. Moran's I 检验（空间自相关检验）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 2.1 全局 Moran's I 检验（以首年截面为例）")
        lines.append(f'y_cross <- panel_df[[\"{dep}\"]][panel_df[[\"{time_var}\"]] == min(panel_df[[\"{time_var}\"]])]')
        lines.append("moran_global <- moran.test(y_cross, W)")
        lines.append("print(moran_global)")
        lines.append("")
        lines.append("# 2.2 局部 Moran's I 检验（LISA）")
        lines.append("local_moran <- localmoran(y_cross, W)")
        lines.append("print(head(local_moran))")
        lines.append("")
        lines.append("# 2.3 逐年 Moran's I 检验")
        lines.append(f'years <- sort(unique(panel_df[[\"{time_var}\"]]))')
        lines.append("moran_yearly <- lapply(years, function(yr) {")
        lines.append(f'  y_t <- panel_df[[\"{dep}\"]][panel_df[[\"{time_var}\"]] == yr]')
        lines.append("  moran.test(y_t, W)")
        lines.append("})")
        lines.append("names(moran_yearly) <- years")
        lines.append('lapply(moran_yearly, function(x) x$estimate["Moran I statistic"])')
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 3. LM 检验（选择 SAR 或 SEM 模型）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append(f"fml <- {dep} ~ {fml_rhs}")
        lines.append('lm_lag <- lm.LMtests(lm(fml, data = panel_df), W, test = "LMlag")')
        lines.append('lm_err <- lm.LMtests(lm(fml, data = panel_df), W, test = "LMerr")')
        lines.append("print(lm_lag)")
        lines.append("print(lm_err)")
        lines.append("# 若 LM-lag 显著则选 SAR，若 LM-error 显著则选 SEM")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 4. 空间横截面模型估计（ML）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 4.1 空间自回归模型（SAR）")
        lines.append("sar_ml <- lagsarlm(fml, data = panel_df, listw = W)")
        lines.append("summary(sar_ml)")
        lines.append("")
        lines.append("# 4.2 空间误差模型（SEM）")
        lines.append("sem_ml <- errorsarlm(fml, data = panel_df, listw = W)")
        lines.append("summary(sem_ml)")
        lines.append("")
        lines.append("# 4.3 空间杜宾模型（SDM）—— Durbin = TRUE 含空间滞后解释变量")
        lines.append("sdm_ml <- lagsarlm(fml, data = panel_df, listw = W, Durbin = TRUE)")
        lines.append("summary(sdm_ml)")
        lines.append("")
        lines.append("# 4.4 LR 检验（SDM 是否可简化为 SAR 或 SEM）")
        lines.append("LR.SDM(sdm_ml, sar_ml)   # SDM vs SAR")
        lines.append("LR.SDM(sdm_ml, sem_ml)   # SDM vs SEM")
        lines.append("# 如果 LR 检验不显著，则 SDM 可简化为 SAR 或 SEM")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 5. 面板空间模型（固定效应，使用 splm::spml）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 5.1 面板 SAR（固定效应）")
        lines.append(f'sar_panel <- spml(fml, data = panel_df, index = c("{entity_var}", "{time_var}"),')
        lines.append('                  listw = W, model = "within", lag = TRUE, spatial.error = "none")')
        lines.append("summary(sar_panel)")
        lines.append("")
        lines.append("# 5.2 面板 SEM（固定效应）")
        lines.append(f'sem_panel <- spml(fml, data = panel_df, index = c("{entity_var}", "{time_var}"),')
        lines.append('                  listw = W, model = "within", lag = FALSE, spatial.error = "b")')
        lines.append("summary(sem_panel)")
        lines.append("")
        lines.append("# 5.3 面板 SDM（固定效应，含空间滞后解释变量）")
        lines.append(f'sdm_panel <- spml(fml, data = panel_df, index = c("{entity_var}", "{time_var}"),')
        lines.append('                  listw = W, model = "within", lag = TRUE, Durbin = TRUE)')
        lines.append("summary(sdm_panel)")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 6. 效应分解（直接效应 / 间接效应 / 总效应）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# SDM 模型的效应分解（使用 impacts 函数，蒙特卡洛模拟 R=500 次）")
        lines.append("impacts_sdm <- impacts(sdm_panel, listw = W, R = 500)")
        lines.append("summary(impacts_sdm, zstats = TRUE)")
        lines.append("")
        lines.append("# 直接效应：本地区解释变量对本地区被解释变量的影响")
        lines.append("# 间接效应（溢出效应）：本地区解释变量对其他地区被解释变量的影响")
        lines.append("# 总效应：直接效应 + 间接效应")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 7. 稳健性检验：替换空间权重矩阵")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 使用反距离矩阵替代邻接矩阵")
        lines.append(f'sdm_robust <- spml(fml, data = panel_df, index = c("{entity_var}", "{time_var}"),')
        lines.append('                   listw = W_dist, model = "within", lag = TRUE, Durbin = TRUE)')
        lines.append("summary(sdm_robust)")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 8. 结果输出（stargazer / modelsummary）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("stargazer(sar_ml, sem_ml, sdm_ml,")
        lines.append('          type = "text", out = "spatial_cross_section.txt",')
        lines.append('          title = "空间横截面回归结果",')
        lines.append('          column.labels = c("SAR", "SEM", "SDM"))')
        lines.append("")
        lines.append("stargazer(sar_panel, sem_panel, sdm_panel,")
        lines.append('          type = "text", out = "spatial_panel.txt",')
        lines.append('          title = "空间面板回归结果（固定效应）",')
        lines.append('          column.labels = c("SAR-FE", "SEM-FE", "SDM-FE"))')
        lines.append("")
        lines.append("# 效应分解结果输出")
        lines.append('capture.output(summary(impacts_sdm, zstats = TRUE), file = "spatial_impacts.txt")')
        lines.append("")
        lines.append("# ============================= End of R Spatial ================================")
        return "\n".join(lines)

    def _generate_spatial_python_template(self, vars: dict) -> str:
        """生成 Python 空间计量代码段落（libpysal + esda + spreg）。

        包含空间权重矩阵构建（Queen / KNN / Distance）、
        Moran's I 检验（全局 + 局部 + 逐年）、LM 检验、
        SAR (ML_Lag) / SEM (ML_Error) / SDM 模型估计、
        GM_Lag / GM_Error 替代估计、效应分解、
        面板空间模型说明、稳健性检验与结果输出（pandas + to_latex）。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Python 空间计量代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{indep_var}"
        controls = vars.get("controls", [])
        x_vars = [indep] + controls if controls else [indep]
        x_vars_repr = repr(x_vars)
        entity_var = vars.get("entity_var", "province")
        time_var = vars.get("time_var", "year")

        lines: list[str] = []
        lines.append("# ===============================================================================")
        lines.append("# 空间计量分析（Python: libpysal + esda + spreg）")
        lines.append("# ===============================================================================")
        lines.append("# 0. 导入包 ---------------------------------------------------------------------")
        lines.append("# pip install pysal libpysal esda spreg geopandas")
        lines.append("import numpy as np")
        lines.append("import pandas as pd")
        lines.append("import geopandas as gpd")
        lines.append("import libpysal")
        lines.append("from libpysal.weights import Queen, KNN, DistanceBand")
        lines.append("from esda.moran import Moran, Moran_Local")
        lines.append("import spreg")
        lines.append("from spreg import ML_Lag, ML_Error, GM_Lag, GM_Error, OLS")
        lines.append("import warnings")
        lines.append("warnings.filterwarnings('ignore')")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 1. 空间权重矩阵构建")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 1.1 读取面板数据与地图数据")
        lines.append("# 请将路径替换为实际数据文件路径")
        lines.append('panel_df = pd.read_csv("[DATA_PATH]")')
        lines.append('map_gdf = gpd.read_file("[SHP_PATH]")   # 省份 shapefile')
        lines.append("")
        lines.append("# 1.2 构建 Queen 邻接权重矩阵")
        lines.append("W_queen = Queen.from_dataframe(map_gdf)")
        lines.append('W_queen.transform = "r"   # 行标准化')
        lines.append("")
        lines.append("# 1.3 构建 K-nearest 权重矩阵")
        lines.append("W_knn = KNN.from_dataframe(map_gdf, k=4)")
        lines.append('W_knn.transform = "r"')
        lines.append("")
        lines.append("# 1.4 构建反距离权重矩阵")
        lines.append("coords = np.column_stack([map_gdf.geometry.x, map_gdf.geometry.y])")
        lines.append("# 使用 DistanceBand 构建反距离矩阵（threshold 需根据实际距离设定）")
        lines.append("max_dist = libpysal.weights.min_threshold_dist_from_array(coords)")
        lines.append("W_dist = DistanceBand.from_array(coords, threshold=max_dist, binary=False)")
        lines.append('W_dist.transform = "r"')
        lines.append("")
        lines.append("# 以下默认使用 Queen 邻接权重矩阵 W_queen")
        lines.append("W = W_queen")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 2. Moran's I 检验（空间自相关检验）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 2.1 全局 Moran's I 检验（以首年截面为例）")
        lines.append(f'first_year = panel_df["{time_var}"].min()')
        lines.append(f'y_cross = panel_df[panel_df["{time_var}"] == first_year]["{dep}"].values')
        lines.append("moran_global = Moran(y_cross, W)")
        lines.append('print(f"Moran\'s I = {moran_global.I:.4f}, p-value = {moran_global.p_sim:.4f}")')
        lines.append("")
        lines.append("# 2.2 局部 Moran's I 检验（LISA）")
        lines.append("local_moran = Moran_Local(y_cross, W)")
        lines.append("# LISA 可视化（可选，需安装 splot）")
        lines.append("# from splot.esda import lisa_cluster")
        lines.append("# import matplotlib.pyplot as plt")
        lines.append("# fig, ax = plt.subplots(figsize=(8, 6))")
        lines.append("# lisa_cluster(local_moran, map_gdf, ax=ax)")
        lines.append("# plt.savefig('lisa_cluster.png', dpi=150)")
        lines.append("# plt.show()")
        lines.append("")
        lines.append("# 2.3 逐年 Moran's I 检验")
        lines.append(f'for yr in sorted(panel_df["{time_var}"].unique()):')
        lines.append(f'    y_t = panel_df[panel_df["{time_var}"] == yr]["{dep}"].values')
        lines.append("    mi = Moran(y_t, W)")
        lines.append('    print(f"Year {yr}: Moran\'s I = {mi.I:.4f}, p = {mi.p_sim:.4f}")')
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 3. LM 检验（选择 SAR 或 SEM 模型）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append(f"X_cols = {x_vars_repr}")
        lines.append(f'X = panel_df[X_cols].values')
        lines.append(f'y = panel_df["{dep}"].values')
        lines.append("# OLS 回归并输出空间诊断（LM-lag / LM-error）")
        lines.append("ols = OLS(y, X, w=W, spat_diag=True, moran=True,")
        lines.append(f'       name_y="{dep}", name_x=X_cols)')
        lines.append("print(ols.summary)")
        lines.append("# 根据 LM-lag 和 LM-error 的显著性选择模型")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 4. 空间模型估计（ML + GM）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 4.1 空间自回归模型 SAR（ML_Lag）")
        lines.append(f'sar_ml = ML_Lag(y, X, w=W, name_y="{dep}", name_x=X_cols)')
        lines.append("print(sar_ml.summary)")
        lines.append("")
        lines.append("# 4.2 空间误差模型 SEM（ML_Error）")
        lines.append(f'sem_ml = ML_Error(y, X, w=W, name_y="{dep}", name_x=X_cols)')
        lines.append("print(sem_ml.summary)")
        lines.append("")
        lines.append("# 4.3 空间杜宾模型 SDM（ML_Lag + 空间滞后解释变量 W*X）")
        lines.append("# 构建空间滞后解释变量")
        lines.append("wx = W.sparse @ X   # 空间滞后解释变量矩阵 (W*X)")
        lines.append("X_sdm = np.column_stack([X, wx])")
        lines.append(f"x_sdm_names = X_cols + ['W_' + c for c in X_cols]")
        lines.append(f'sdm_ml = ML_Lag(y, X_sdm, w=W, name_y="{dep}", name_x=x_sdm_names)')
        lines.append("print(sdm_ml.summary)")
        lines.append("")
        lines.append("# 4.4 GM 替代估计（当 ML 不收敛时使用）")
        lines.append(f'sar_gm = GM_Lag(y, X, w=W, name_y="{dep}", name_x=X_cols)')
        lines.append("print(sar_gm.summary)")
        lines.append("")
        lines.append(f'sem_gm = GM_Error(y, X, w=W, name_y="{dep}", name_x=X_cols)')
        lines.append("print(sem_gm.summary)")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 5. 效应分解（直接效应 / 间接效应 / 总效应）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# spreg 中通过 impacts 方法计算 SDM 的直接/间接/总效应")
        lines.append("# 直接效应：本地区解释变量对本地区被解释变量的影响")
        lines.append("# 间接效应（溢出效应）：本地区解释变量对其他地区被解释变量的影响")
        lines.append("# 总效应：直接效应 + 间接效应")
        lines.append("# 示例（需根据 spreg 版本调整 API）:")
        lines.append("# from spreg import spmultilag")
        lines.append("# sdm_impacts = spmultilag(y, X_sdm, w=W)")
        lines.append("# print(sdm_impacts.direct, sdm_impacts.indirect, sdm_impacts.total)")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 6. 面板空间模型说明")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 注意：Python 生态中暂无与 R splm 包直接对应的面板空间模型库。")
        lines.append("# 面板空间模型（固定效应 SAR/SEM/SDM）建议使用 R 的 splm::spml()，")
        lines.append("# 或在 Python 中通过组内去均值（demean）近似固定效应后使用横截面 spreg 估计。")
        lines.append("# 以下为去均值近似面板固定效应的示例：")
        lines.append(f'for col in X_cols + ["{dep}"]:')
        lines.append(f'    panel_df[col] = panel_df.groupby("{entity_var}")[col].transform(')
        lines.append("        lambda x: x - x.mean()")
        lines.append("    )")
        lines.append("# 去均值后使用横截面 spreg 估计（近似固定效应）")
        lines.append(f'y_demean = panel_df["{dep}"].values')
        lines.append("X_demean = panel_df[X_cols].values")
        lines.append(f'sar_panel = ML_Lag(y_demean, X_demean, w=W, name_y="{dep}", name_x=X_cols)')
        lines.append("print(sar_panel.summary)")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 7. 稳健性检验：替换空间权重矩阵")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 使用反距离矩阵替代邻接矩阵")
        lines.append(f'sdm_robust = ML_Lag(y, X_sdm, w=W_dist, name_y="{dep}", name_x=x_sdm_names)')
        lines.append("print(sdm_robust.summary)")
        lines.append("")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 8. 结果输出（pandas DataFrame + to_latex）")
        lines.append("# -------------------------------------------------------------------------------")
        lines.append("# 汇总各模型结果")
        lines.append("results = {")
        lines.append('    "SAR(ML)": sar_ml,')
        lines.append('    "SEM(ML)": sem_ml,')
        lines.append('    "SDM(ML)": sdm_ml,')
        lines.append('    "SAR(GM)": sar_gm,')
        lines.append('    "SEM(GM)": sem_gm,')
        lines.append("}")
        lines.append("")
        lines.append("# 提取系数和统计量到 DataFrame")
        lines.append("rows = []")
        lines.append("for name, model in results.items():")
        lines.append("    for i, b in enumerate(model.betas):")
        lines.append("        rows.append({")
        lines.append('            "Model": name,')
        lines.append('            "Variable": model.name_x[i],')
        lines.append('            "Coef": b[0],')
        lines.append('            "Std.Err": b[1],')
        lines.append('            "z": b[2],')
        lines.append('            "p": b[3],')
        lines.append("        })")
        lines.append("results_df = pd.DataFrame(rows)")
        lines.append("print(results_df)")
        lines.append("")
        lines.append("# 输出 LaTeX 表格")
        lines.append("latex_table = results_df.to_latex(index=False, float_format='%.4f',")
        lines.append('                              caption="空间计量回归结果", label="tab:spatial")')
        lines.append("with open('spatial_results.tex', 'w') as f:")
        lines.append("    f.write(latex_table)")
        lines.append("")
        lines.append("# =========================== End of Python Spatial =============================")
        return "\n".join(lines)

    # ==================================================================
    # 扩展方法模板段落生成
    # ==================================================================

    def _generate_threshold_template(self, vars: dict, spec_text: str = "") -> str:
        """生成面板门槛模型代码段落（Hansen 1999, xthreg）。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。
            spec_text: 原始 SPEC 文本（用于提取门槛变量）。

        Returns:
            Stata 面板门槛模型代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{indep_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"

        # 从 SPEC 文本中提取门槛变量
        threshold_var = ""
        if spec_text:
            tv_match = re.search(r"门槛变量[为是：:\s]+(\w+)", spec_text)
            if tv_match:
                threshold_var = tv_match.group(1).strip()
        if not threshold_var:
            threshold_var = controls[0] if controls else "{threshold_var}"

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* 面板门槛模型（Hansen 1999）")
        lines.append("*===============================================================================")
        lines.append("* 安装门槛回归命令")
        lines.append("* ssc install xthreg, replace")
        lines.append("")
        lines.append(f"* 门槛变量：{threshold_var}")
        lines.append("")
        lines.append("* 单门槛模型")
        lines.append(
            f"xthreg {dep} {indep} {controls_str}, "
            f"rx({indep}) qx({threshold_var}) thnum(1) trim(50) bs(300)"
        )
        lines.append("est store threshold_1")
        lines.append("")
        lines.append("* 双门槛模型")
        lines.append(
            f"xthreg {dep} {indep} {controls_str}, "
            f"rx({indep}) qx({threshold_var}) thnum(2) trim(50) bs(300)"
        )
        lines.append("est store threshold_2")
        lines.append("")
        lines.append("* 三门槛模型")
        lines.append(
            f"xthreg {dep} {indep} {controls_str}, "
            f"rx({indep}) qx({threshold_var}) thnum(3) trim(50) bs(300)"
        )
        lines.append("est store threshold_3")
        lines.append("")
        lines.append("* 门槛效应检验（自助法检验门槛个数）")
        lines.append("* 通过 LR 检验确定最优门槛个数")
        lines.append("")
        lines.append("* 绘制门槛变量似然比图")
        lines.append(f"* _matplot e(LR), columns(1 2) yline(7.35, lpattern(dash)) connect(direct)")
        lines.append("")
        lines.append("* 输出门槛回归结果表")
        lines.append(
            'esttab threshold_1 threshold_2 threshold_3 using "threshold_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'stats(N r2, labels("观测数" "R方")) '
            'mtitles("单门槛" "双门槛" "三门槛") '
            'title("面板门槛回归结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_rdd_template(self, vars: dict, spec_text: str = "") -> str:
        """生成断点回归（RDD）代码段落（rdrobust）。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。
            spec_text: 原始 SPEC 文本（用于提取运行变量和断点值）。

        Returns:
            Stata RDD 代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{treatment_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"

        # 从 SPEC 文本中提取运行变量和断点值
        running_var = "{running_var}"
        cutoff = "{cutoff}"
        if spec_text:
            # 优先匹配 "以X为运行变量" 模式
            rv_match = re.search(r"以(.+?)为运行变量", spec_text)
            if rv_match:
                running_var = rv_match.group(1).strip()
            else:
                rv_match = re.search(r"运行变量[为是：:\s]+(\S+?)(?:[，,。]|$)", spec_text)
                if rv_match:
                    running_var = rv_match.group(1).strip()
            co_match = re.search(r"断点值[为是：:\s]+([\d.]+)", spec_text)
            if co_match:
                cutoff = co_match.group(1).strip()

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* 断点回归（RDD）")
        lines.append("*===============================================================================")
        lines.append("* 安装 RDD 相关命令")
        lines.append("* ssc install rdrobust, replace")
        lines.append("* ssc install rdbwselect, replace")
        lines.append("* ssc install rddensity, replace")
        lines.append("")
        lines.append(f"* 运行变量：{running_var}")
        lines.append(f"* 断点值（cutoff）：{cutoff}")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 1. 带宽选择")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"rdbwselect {dep} {running_var}, c({cutoff})")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 2. RDD 估计（局部线性回归）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"rdrobust {dep} {running_var}, c({cutoff}) p(1) kernel(triangular)")
        lines.append("est store rdd_result")
        lines.append("")
        lines.append("* 使用不同带宽进行稳健性检验")
        lines.append(f"* rdrobust {dep} {running_var}, c({cutoff}) h(0.5) p(1)")
        lines.append(f"* rdrobust {dep} {running_var}, c({cutoff}) h(1.0) p(2)")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 3. 密度检验（McCrary 检验，检验断点处是否有操纵）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"rddensity {running_var}, c({cutoff})")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 4. 协变量平稳性检验（检验协变量在断点处是否连续）")
        lines.append("*-------------------------------------------------------------------------------")
        if controls:
            for ctrl in controls:
                lines.append(f"rdrobust {ctrl} {running_var}, c({cutoff}) p(1)")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 5. 可视化（散点图 + 拟合线）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"* rdplot {dep} {running_var}, c({cutoff}) p(1) kernel(triangular)")
        lines.append("")
        lines.append("* 输出 RDD 结果表")
        lines.append(
            'esttab rdd_result using "rdd_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'stats(N, labels("观测数")) '
            'mtitles("RDD估计") '
            'title("断点回归结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_scm_template(self, vars: dict, spec_text: str = "") -> str:
        """生成合成控制法（SCM）代码段落（synth）。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。
            spec_text: 原始 SPEC 文本（用于提取处理单元和处理时点）。

        Returns:
            Stata SCM 代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        entity_var = vars.get("entity_var", "province")
        time_var = vars.get("time_var", "year")

        # 从 SPEC 文本中提取处理时点
        trperiod = "{trperiod}"
        if spec_text:
            tp_match = re.search(r"(\d{4})年", spec_text)
            if tp_match:
                trperiod = tp_match.group(1)

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* 合成控制法（SCM）")
        lines.append("*===============================================================================")
        lines.append("* 安装 synth 命令")
        lines.append("* ssc install synth, replace")
        lines.append("")
        lines.append("* 设置面板数据结构")
        lines.append(f"* tsset {entity_var} {time_var}")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 合成控制估计")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"* trunit: 处理单元编号")
        lines.append(f"* trperiod: 政策实施时点（{trperiod}）")
        lines.append("")
        lines.append(f"synth {dep} {dep}(2010) {dep}(2012) {dep}(2014), "
                      f"trunit(1) trperiod({trperiod}) figure")
        lines.append("est store scm_result")
        lines.append("")
        lines.append("* 保存合成控制结果")
        lines.append(f"matrix res = e(Y_table)")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 安慰剂检验（Placebo Test）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 通过随机抽取控制组作为处理单元进行安慰剂检验")
        lines.append("* forvalues i = 2/`N' {")
        lines.append(f"*     synth {dep} {dep}(2010) {dep}(2012) {dep}(2014), trunit(`i') trperiod({trperiod})")
        lines.append("* }")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 输出合成控制结果")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 绘制处理组与合成控制组的趋势图")
        lines.append(f"* synth {dep} {dep}(2010) {dep}(2012) {dep}(2014), "
                      f"trunit(1) trperiod({trperiod}) figure resultsperiod(2010(1)2020)")
        return "\n".join(lines)

    def _generate_heckman_template(self, vars: dict, spec_text: str = "") -> str:
        """生成 Heckman 两阶段模型代码段落。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。
            spec_text: 原始 SPEC 文本（用于提取选择变量）。

        Returns:
            Stata Heckman 代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{indep_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"

        # 从 SPEC 文本中提取选择变量
        selection_var = "{selection_var}"
        if spec_text:
            # 优先匹配 "是否XXX（var=0/1）" 模式
            sv_match2 = re.search(r"是否\w+[（(](\w+)", spec_text)
            if sv_match2:
                selection_var = sv_match2.group(1).strip()
            else:
                sv_match = re.search(r"选择变量[为是：:\s]+(\w+)", spec_text)
                if sv_match:
                    selection_var = sv_match.group(1).strip()

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* Heckman 两阶段模型（修正样本选择偏差）")
        lines.append("*===============================================================================")
        lines.append(f"* 选择变量：{selection_var}（0/1）")
        lines.append(f"* 被解释变量：{dep}（仅在 {selection_var}=1 时可观测）")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 第一步：选择方程（Probit 估计选择概率）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"* {selection_var} = 1 的概率模型")
        lines.append(f"probit {selection_var} {indep} {controls_str}")
        lines.append("est store heckman_step1")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 第二步：Heckman 两阶段估计")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"heckman {dep} {indep} {controls_str}, "
                      f"select({selection_var} = {indep} {controls_str}) twostep")
        lines.append("est store heckman_result")
        lines.append("")
        lines.append("* 查看 Lambda（逆米尔斯比率）系数")
        lines.append("* Lambda 显著表示存在样本选择偏差")
        lines.append("")
        lines.append("* 使用 MLE 方法（更稳健）")
        lines.append(f"* heckman {dep} {indep} {controls_str}, "
                      f"select({selection_var} = {indep} {controls_str}) mle")
        lines.append("")
        lines.append("* 输出 Heckman 结果表")
        lines.append(
            'esttab heckman_step1 heckman_result using "heckman_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'stats(N, labels("观测数")) '
            'mtitles("选择方程" "Heckman两阶段") '
            'title("Heckman两阶段模型结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_gmm_template(self, vars: dict) -> str:
        """生成动态面板 GMM 代码段落（xtabond2）。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata GMM 代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{indep_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"
        entity_var = vars.get("entity_var", "province")

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* 动态面板 GMM（系统 GMM）")
        lines.append("*===============================================================================")
        lines.append("* 安装 xtabond2 命令")
        lines.append("* ssc install xtabond2, replace")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 1. 差分 GMM（Arellano-Bond 估计）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(
            f"xtabond2 {dep} L.{dep} {indep} {controls_str}, "
            f"gmm(L.{dep}) iv({indep} {controls_str}) robust"
        )
        lines.append("est store diff_gmm")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 2. 系统 GMM（Blundell-Bond 估计）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(
            f"xtabond2 {dep} L.{dep} {indep} {controls_str}, "
            f"gmm(L.{dep}, lag(2 .)) iv({indep} {controls_str}) robust twostep"
        )
        lines.append("est store sys_gmm")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 3. 诊断检验")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* AR(1) 检验：一阶序列相关（预期显著）")
        lines.append("* AR(2) 检验：二阶序列相关（预期不显著，p>0.1）")
        lines.append("* Hansen 检验：过度识别约束检验（预期不显著，p>0.1）")
        lines.append("* 工具变量个数不应超过截面个体数")
        lines.append("")
        lines.append("* 查看 AR(1) 和 AR(2) 检验结果")
        lines.append("* estat abond")
        lines.append("")
        lines.append("* 查看 Hansen 过度识别检验结果")
        lines.append("* estat sargan")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 4. 水平方程检验（Difference-in-Hansen 检验）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 检验水平方程工具变量的外生性")
        lines.append("")
        lines.append("* 输出 GMM 结果表")
        lines.append(
            'esttab diff_gmm sys_gmm using "gmm_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'stats(N, labels("观测数")) '
            'mtitles("差分GMM" "系统GMM") '
            'title("动态面板GMM回归结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_var_template(self, vars: dict) -> str:
        """生成 VAR 模型代码段落。

        包含 VAR 估计、最优滞后阶数选择、格兰杰因果检验、
        脉冲响应分析、方差分解、协整检验。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata VAR 代码段落字符串。
        """
        all_vars = vars.get("all_variables", [])
        if not all_vars:
            dep = vars.get("dep_var") or "{dep_var}"
            indep = vars.get("indep_var") or "{indep_var}"
            all_vars = [dep, indep]
        vars_str = " ".join(all_vars)
        time_var = vars.get("time_var", "year")

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* VAR 模型（向量自回归）")
        lines.append("*===============================================================================")
        lines.append("* 设置时间序列结构")
        lines.append(f"* tsset {time_var}")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 1. 平稳性检验（ADF 检验）")
        lines.append("*-------------------------------------------------------------------------------")
        for v in all_vars:
            lines.append(f"* dfuller {v}")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 2. 最优滞后阶数选择")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"varsoc {vars_str}, maxlag(4)")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 3. VAR 模型估计")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"var {vars_str}, lags(1/2)")
        lines.append("est store var_result")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 4. 格兰杰因果检验")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("vargranger")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 5. 脉冲响应分析")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("irf create var_irf, set(myirf) replace")
        lines.append("irf graph irf, impulse(" + all_vars[0] + ") response(" + " ".join(all_vars) + ")")
        lines.append("")
        lines.append("* 累积脉冲响应")
        lines.append("* irf graph cirf")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 6. 方差分解")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("irf table fevd, n(10)")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 7. 稳定性检验")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("varstable, graph")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 8. 协整检验（Johansen 检验）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"vecrank {vars_str}, maxlag(4)")
        lines.append("")
        lines.append("* 如果存在协整关系，使用 VECM 模型")
        lines.append(f"* vec {vars_str}, rank(1)")
        lines.append("")
        lines.append("* 输出 VAR 结果表")
        lines.append(
            'esttab var_result using "var_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'title("VAR模型估计结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_event_study_template(self, vars: dict) -> str:
        """生成事件研究法代码段落。

        包含异常收益率（AR）和累计异常收益率（CAR）的计算与检验。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata 事件研究法代码段落字符串。
        """
        dep = vars.get("dep_var") or "stock_return"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{market_return}"

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* 事件研究法（Event Study）")
        lines.append("*===============================================================================")
        lines.append("* 计算异常收益率（AR）和累计异常收益率（CAR）")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 1. 定义事件窗口和估计窗口")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 事件窗口：[-10, 10]（事件日前后10天）")
        lines.append("* 估计窗口：[-120, -11]（事件日前120天到前11天）")
        lines.append("")
        lines.append("* 生成事件时间变量")
        lines.append("gen event_time = trade_date - event_date")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 2. 估计正常收益率（市场模型）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"* 在估计窗口内回归：{dep} = alpha + beta * market_return")
        lines.append(f"reg {dep} {controls_str} if event_time >= -120 & event_time <= -11")
        lines.append("est store market_model")
        lines.append("predict expected_return if event_time >= -10 & event_time <= 10")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 3. 计算异常收益率（AR）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"gen AR = {dep} - expected_return")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 4. 计算累计异常收益率（CAR）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* CAR[-10, 10] = 累计 AR")
        lines.append("bysort firm_id: egen CAR = total(AR) if event_time >= -10 & event_time <= 10")
        lines.append("")
        lines.append("* 不同窗口的 CAR")
        lines.append("* CAR[-1, 1]：事件日前后1天")
        lines.append("* CAR[-5, 5]：事件日前后5天")
        lines.append("* CAR[0, 10]：事件日后10天")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 5. 统计检验")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 检验 CAR 是否显著异于 0")
        lines.append("ttest CAR == 0")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 6. 绘制事件研究图")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 绘制 CAR 随事件时间的变化图")
        lines.append("* collapse (mean) AR, by(event_time)")
        lines.append("* gen cumAR = sum(AR)")
        lines.append("* twoway (line cumAR event_time), yline(0) xline(0)")
        lines.append("")
        lines.append("* 输出事件研究结果表")
        lines.append(
            'esttab market_model using "event_study.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'stats(N r2, labels("观测数" "R方")) '
            'title("事件研究法结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_ipw_template(self, vars: dict) -> str:
        """生成逆概率加权（IPW）代码段落。

        包含 Probit 倾向得分估计、IPW 加权回归和双重稳健估计。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata IPW 代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{treatment_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* 逆概率加权（IPW）和双重稳健估计")
        lines.append("*===============================================================================")
        lines.append("* 安装 teffects 命令（Stata 13+ 内置）")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 1. Probit 估计倾向得分（倾向得分模型）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"probit {indep} {controls_str}")
        lines.append("predict ps, pr")
        lines.append("")
        lines.append("* 查看倾向得分分布")
        lines.append("* summarize ps")
        lines.append("* histogram ps, by({0})".format(indep))
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 2. 计算逆概率权重（IPW）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"gen ipw = {indep}/ps + (1-{indep})/(1-ps)")
        lines.append("")
        lines.append("* 检查权重分布（极端权重需截断）")
        lines.append("* summarize ipw")
        lines.append("* replace ipw = min(ipw, 10)  /* 截断极端权重 */")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 3. IPW 加权回归")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"reg {dep} {indep} {controls_str} [pw=ipw], robust")
        lines.append("est store ipw_result")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 4. 使用 teffects 的 IPW 估计（自动处理）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"teffects ipw ({dep}) ({indep} {controls_str}), ate")
        lines.append("est store teffect_ipw")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 5. 双重稳健估计（Doubly Robust, AIPW）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"teffects aipw ({dep} {controls_str}) ({indep} {controls_str}), ate")
        lines.append("est store teffect_aipw")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 6. 平衡性检验（检验加权后协变量是否平衡）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"* tebalance summarize")
        lines.append("")
        lines.append("* 输出 IPW 结果表")
        lines.append(
            'esttab ipw_result teffect_ipw teffect_aipw using "ipw_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'stats(N, labels("观测数")) '
            'mtitles("IPW加权" "teffects-IPW" "双重稳健") '
            'title("逆概率加权估计结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_quantile_template(self, vars: dict) -> str:
        """生成分位数回归代码段落（qreg）。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata 分位数回归代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{indep_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* 分位数回归（Quantile Regression）")
        lines.append("*===============================================================================")
        lines.append("* 安装分位数回归相关命令")
        lines.append("* ssc install sqreg, replace   /* 同时估计多个分位数 */")
        lines.append("* ssc install grqreg, replace   /* 绘制分位数回归系数图 */")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 1. 分位数回归估计")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"qreg {dep} {indep} {controls_str}, q(0.10)")
        lines.append("est store qr_10")
        lines.append("")
        lines.append(f"qreg {dep} {indep} {controls_str}, q(0.25)")
        lines.append("est store qr_25")
        lines.append("")
        lines.append(f"qreg {dep} {indep} {controls_str}, q(0.50)")
        lines.append("est store qr_50")
        lines.append("")
        lines.append(f"qreg {dep} {indep} {controls_str}, q(0.75)")
        lines.append("est store qr_75")
        lines.append("")
        lines.append(f"qreg {dep} {indep} {controls_str}, q(0.90)")
        lines.append("est store qr_90")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 2. 同时估计多个分位数（sqreg）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"sqreg {dep} {indep} {controls_str}, q(0.10 0.25 0.50 0.75 0.90) reps(500)")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 3. Bootstrap 标准误")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"bootstrap, reps(500): qreg {dep} {indep} {controls_str}, q(0.50)")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 4. 绘制分位数回归系数图")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* grqreg, ci ols")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 5. 分位数处理效应检验")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 检验不同分位数下系数是否显著不同")
        lines.append("")
        lines.append("* 输出分位数回归结果表")
        lines.append(
            'esttab qr_10 qr_25 qr_50 qr_75 qr_90 using "quantile_regression.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'stats(N, labels("观测数")) '
            'mtitles("Q10" "Q25" "Q50" "Q75" "Q90") '
            'title("分位数回归结果") compress nogaps'
        )
        return "\n".join(lines)

    def _generate_discrete_template(self, vars: dict) -> str:
        """生成离散选择模型代码段落（Logit / Probit / Tobit）。

        Args:
            vars: _extract_variables_from_spec 返回的变量字典。

        Returns:
            Stata 离散选择模型代码段落字符串。
        """
        dep = vars.get("dep_var") or "{dep_var}"
        indep = vars.get("indep_var") or "{indep_var}"
        controls = vars.get("controls", [])
        controls_str = " ".join(controls) if controls else "{controls}"

        lines: list[str] = []
        lines.append("*===============================================================================")
        lines.append("* 离散选择模型（Logit / Probit / Tobit）")
        lines.append("*===============================================================================")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 1. Logit 模型（二元选择）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"logit {dep} {indep} {controls_str}, robust")
        lines.append("est store logit_model")
        lines.append("")
        lines.append("* 计算边际效应（在均值处）")
        lines.append("margins, dydx(*) atmeans post")
        lines.append("est store logit_mfx")
        lines.append("")
        lines.append("* 计算平均边际效应")
        lines.append("* margins, dydx(*)")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 2. Probit 模型")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append(f"probit {dep} {indep} {controls_str}, robust")
        lines.append("est store probit_model")
        lines.append("")
        lines.append("* 计算边际效应")
        lines.append("margins, dydx(*) atmeans post")
        lines.append("est store probit_mfx")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 3. Tobit 模型（截断/截尾数据）")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 左截断在 0（适用于非负变量）")
        lines.append(f"tobit {dep} {indep} {controls_str}, ll(0)")
        lines.append("est store tobit_model")
        lines.append("")
        lines.append("* 右截断（如有需要）")
        lines.append(f"* tobit {dep} {indep} {controls_str}, ul(100)")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 4. 模型比较与选择")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 比较 Logit 和 Probit 的 AIC/BIC")
        lines.append("* estat ic")
        lines.append("")
        lines.append("* 预测正确率")
        lines.append(f"estat classification  /* Logit/Probit 模型 */")
        lines.append("")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 5. 稳健性检验")
        lines.append("*-------------------------------------------------------------------------------")
        lines.append("* 使用条件 Logit 模型（如有分组数据）")
        lines.append(f"* clogit {dep} {indep} {controls_str}, group(group_var)")
        lines.append("")
        lines.append("* 输出离散选择模型结果表")
        lines.append(
            'esttab logit_model probit_model tobit_model using "discrete_choice.rtf", replace '
            "b(3) t(2) star(* 0.10 ** 0.05 *** 0.01) "
            'stats(N, labels("观测数")) '
            'mtitles("Logit" "Probit" "Tobit") '
            'title("离散选择模型结果") compress nogaps'
        )
        return "\n".join(lines)


__all__ = ["CodeTemplateGenerator"]
