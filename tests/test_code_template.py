"""实证分析代码模板生成器测试。

测试范围:
1. SPEC 变量提取（_extract_variables_from_spec）
2. 方法关键词检测（_detect_method_keywords）
3. Stata 模板生成（generate_stata_template）
4. R 模板生成（generate_r_template）
5. Python 模板生成（generate_python_template）
6. 完整模板生成（generate_full_template）—— 智能追加
7. 额外模板段落（IV / DID / PSM / 中介 / 空间）

运行方式:
    cd scholarpilot
    python -m pytest tests/test_code_template.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scholarpilot.tools.code_template_generator import CodeTemplateGenerator


# ===== Fixtures =====

@pytest.fixture
def generator():
    """创建 CodeTemplateGenerator 实例."""
    return CodeTemplateGenerator()


@pytest.fixture
def spatial_spec():
    """包含空间溢出 + 内生性 + 中介效应的完整 SPEC."""
    return """# 论文规格

## 研究主题
地方政府债务风险的空间溢出效应

## 变量设计
- 被解释变量：debt_risk（地方政府债务风险指数）
- 核心解释变量：fiscal_gap（财政缺口率）
- 控制变量：gdp_growth（GDP增长率）
- 控制变量：pop_density（人口密度）
- 控制变量：urban_rate（城镇化率）

## 模型设定
采用空间杜宾模型（SDM），使用31个省份2010-2023年面板数据。
存在内生性问题，使用滞后一期财政缺口作为工具变量。
分析中介效应：fiscal_gap → financial_development → debt_risk

## 数据需求
- 数据来源：Wind数据库
- 样本期间：2010-2023年
- 截面单元：31个省份
"""


@pytest.fixture
def did_spec():
    """包含 DID 双重差分的 SPEC."""
    return """# 论文规格

## 研究主题
环保税政策对企业绿色创新的影响

## 变量设计
- 被解释变量：green_innovation（绿色专利申请数）
- 核心解释变量：policy_treat（政策处理变量）
- 控制变量：firm_size（企业规模）
- 控制变量：firm_age（企业年龄）
- 控制变量：rd_intensity（研发强度）

## 模型设定
采用准自然实验（DID双重差分）方法，政策冲击为2018年环保税实施。
使用2010-2023年企业面板数据，包含个体固定效应和时间固定效应。

## 数据需求
- 样本期间：2010-2023年
- 截面单元：企业
"""


@pytest.fixture
def psm_spec():
    """包含 PSM 倾向得分匹配的 SPEC."""
    return """# 论文规格

## 研究主题
数字化转型对企业全要素生产率的影响

## 变量设计
- 被解释变量：tfp（全要素生产率）
- 核心解释变量：digital_transformation（数字化转型）
- 控制变量：firm_size（企业规模）
- 控制变量：leverage（资产负债率）

## 模型设定
采用倾向得分匹配（PSM）方法消除样本选择偏差。
使用2015-2023年上市企业面板数据。

## 数据需求
- 样本期间：2015-2023年
"""


@pytest.fixture
def simple_spec():
    """简单实证 SPEC（无特殊方法关键词）."""
    return """# 论文规格

## 研究主题
财政分权对经济增长的影响

## 变量设计
- 被解释变量：gdp_growth（GDP增长率）
- 核心解释变量：fiscal_decentralization（财政分权度）
- 控制变量：pop_growth（人口增长率）
- 控制变量：investment_ratio（投资占比）

## 模型设定
采用固定效应面板回归模型。

## 数据需求
- 样本期间：2005-2020年
"""


@pytest.fixture
def empty_spec():
    """空 SPEC（无变量定义）."""
    return """# 论文规格

## 研究主题
理论分析框架

## 研究方法
本文采用理论分析方法。
"""


# ===== 1. SPEC 变量提取测试 =====

class TestExtractVariables:
    """测试从 SPEC 提取变量定义."""

    def test_extract_dep_var(self, generator, spatial_spec):
        """提取被解释变量."""
        v = generator._extract_variables_from_spec(spatial_spec)
        assert v["dep_var"] == "debt_risk"

    def test_extract_indep_var(self, generator, spatial_spec):
        """提取核心解释变量."""
        v = generator._extract_variables_from_spec(spatial_spec)
        assert v["indep_var"] == "fiscal_gap"

    def test_extract_controls(self, generator, spatial_spec):
        """提取控制变量列表."""
        v = generator._extract_variables_from_spec(spatial_spec)
        assert len(v["controls"]) == 3
        assert "gdp_growth" in v["controls"]
        assert "pop_density" in v["controls"]
        assert "urban_rate" in v["controls"]

    def test_extract_all_variables(self, generator, spatial_spec):
        """提取所有变量汇总列表."""
        v = generator._extract_variables_from_spec(spatial_spec)
        assert v["dep_var"] in v["all_variables"]
        assert v["indep_var"] in v["all_variables"]
        for c in v["controls"]:
            assert c in v["all_variables"]

    def test_extract_entity_var(self, generator, spatial_spec):
        """提取截面单元变量（省份）."""
        v = generator._extract_variables_from_spec(spatial_spec)
        assert v["entity_var"] == "province"

    def test_extract_time_var(self, generator, spatial_spec):
        """提取时间变量（年份范围触发）."""
        v = generator._extract_variables_from_spec(spatial_spec)
        assert v["time_var"] == "year"

    def test_extract_title(self, generator, spatial_spec):
        """提取研究主题."""
        v = generator._extract_variables_from_spec(spatial_spec)
        assert "空间溢出" in v["title"]

    def test_extract_model_text(self, generator, spatial_spec):
        """提取模型设定文本."""
        v = generator._extract_variables_from_spec(spatial_spec)
        assert "空间杜宾" in v["model_text"] or "SDM" in v["model_text"]

    def test_empty_spec_returns_defaults(self, generator, empty_spec):
        """空 SPEC 返回默认占位符值."""
        v = generator._extract_variables_from_spec(empty_spec)
        assert v["dep_var"] == ""
        assert v["indep_var"] == ""
        assert v["controls"] == []


# ===== 2. 方法关键词检测测试 =====

class TestDetectKeywords:
    """测试方法关键词检测."""

    def test_detect_spatial(self, generator, spatial_spec):
        """检测空间计量关键词."""
        kw = generator._detect_method_keywords(spatial_spec)
        assert kw["has_spatial"] is True

    def test_detect_iv(self, generator, spatial_spec):
        """检测工具变量关键词."""
        kw = generator._detect_method_keywords(spatial_spec)
        assert kw["has_iv"] is True

    def test_detect_endogeneity(self, generator, spatial_spec):
        """检测内生性关键词."""
        kw = generator._detect_method_keywords(spatial_spec)
        assert kw["has_endogeneity"] is True

    def test_detect_mediation(self, generator, spatial_spec):
        """检测中介效应关键词."""
        kw = generator._detect_method_keywords(spatial_spec)
        assert kw["has_mediation"] is True

    def test_detect_did(self, generator, did_spec):
        """检测 DID 关键词."""
        kw = generator._detect_method_keywords(did_spec)
        assert kw["has_did"] is True

    def test_detect_psm(self, generator, psm_spec):
        """检测 PSM 关键词."""
        kw = generator._detect_method_keywords(psm_spec)
        assert kw["has_psm"] is True

    def test_no_keywords_in_simple_spec(self, generator, simple_spec):
        """简单 SPEC 无特殊方法关键词."""
        kw = generator._detect_method_keywords(simple_spec)
        assert kw["has_spatial"] is False
        assert kw["has_did"] is False
        assert kw["has_psm"] is False
        assert kw["has_iv"] is False
        assert kw["has_mediation"] is False

    def test_keyword_detection_returns_all_keys(self, generator, simple_spec):
        """关键词检测结果包含所有键."""
        kw = generator._detect_method_keywords(simple_spec)
        expected_keys = {
            "has_endogeneity", "has_did", "has_psm",
            "has_mediation", "has_spatial", "has_iv",
            "has_threshold", "has_rdd", "has_scm",
            "has_heckman", "has_gmm", "has_var",
            "has_event_study", "has_ipw", "has_quantile",
            "has_discrete",
        }
        assert set(kw.keys()) == expected_keys


# ===== 3. Stata 模板生成测试 =====

class TestStataTemplate:
    """测试 Stata 模板生成."""

    def test_stata_template_contains_comments(self, generator, spatial_spec):
        """Stata 模板包含中文注释."""
        code = generator.generate_stata_template(spatial_spec)
        assert "*" in code  # Stata 注释
        assert "环境设置" in code
        assert "数据导入" in code
        assert "基准回归" in code

    def test_stata_template_contains_dep_var(self, generator, spatial_spec):
        """Stata 模板包含被解释变量."""
        code = generator.generate_stata_template(spatial_spec)
        assert "debt_risk" in code

    def test_stata_template_contains_indep_var(self, generator, spatial_spec):
        """Stata 模板包含核心解释变量."""
        code = generator.generate_stata_template(spatial_spec)
        assert "fiscal_gap" in code

    def test_stata_template_contains_controls(self, generator, spatial_spec):
        """Stata 模板包含控制变量."""
        code = generator.generate_stata_template(spatial_spec)
        assert "gdp_growth" in code
        assert "pop_density" in code
        assert "urban_rate" in code

    def test_stata_template_contains_esttab_star(self, generator, spatial_spec):
        """Stata 模板的 esttab 包含显著性星号设定."""
        code = generator.generate_stata_template(spatial_spec)
        assert "star(* 0.10 ** 0.05 *** 0.01)" in code

    def test_stata_template_contains_ols_fe_re(self, generator, spatial_spec):
        """Stata 模板包含 OLS、FE、RE 三种回归."""
        code = generator.generate_stata_template(spatial_spec)
        assert "reg " in code  # OLS
        assert "xtreg" in code and "fe" in code  # FE
        assert "xtreg" in code and "re" in code  # RE

    def test_stata_template_contains_vif(self, generator, spatial_spec):
        """Stata 模板包含 VIF 检验."""
        code = generator.generate_stata_template(spatial_spec)
        assert "vif" in code

    def test_stata_template_contains_hausman(self, generator, spatial_spec):
        """Stata 模板包含 Hausman 检验."""
        code = generator.generate_stata_template(spatial_spec)
        assert "hausman" in code

    def test_stata_template_contains_winsor(self, generator, spatial_spec):
        """Stata 模板包含缩尾处理."""
        code = generator.generate_stata_template(spatial_spec)
        assert "winsor2" in code

    def test_stata_template_contains_robustness(self, generator, spatial_spec):
        """Stata 模板包含稳健性检验."""
        code = generator.generate_stata_template(spatial_spec)
        assert "稳健性检验" in code
        assert "替换" in code
        assert "子样本" in code
        assert "滞后" in code

    def test_stata_template_with_empty_spec_uses_placeholders(self, generator, empty_spec):
        """空 SPEC 使用占位符."""
        code = generator.generate_stata_template(empty_spec)
        assert code  # 应生成非空模板
        # 无变量时应仍包含基本结构
        assert "环境设置" in code

    def test_stata_template_title_in_header(self, generator, spatial_spec):
        """Stata 模板头部包含标题."""
        code = generator.generate_stata_template(spatial_spec, title="自定义标题")
        assert "自定义标题" in code


# ===== 4. R 模板生成测试 =====

class TestRTemplate:
    """测试 R 模板生成."""

    def test_r_template_contains_libraries(self, generator, spatial_spec):
        """R 模板包含所需包."""
        code = generator.generate_r_template(spatial_spec)
        assert "library(fixest)" in code
        assert "library(modelsummary)" in code
        assert "library(ggplot2)" in code

    def test_r_template_contains_feols(self, generator, spatial_spec):
        """R 模板使用 fixest::feols 固定效应回归."""
        code = generator.generate_r_template(spatial_spec)
        assert "feols" in code

    def test_r_template_contains_modelsummary(self, generator, spatial_spec):
        """R 模板使用 modelsummary 输出."""
        code = generator.generate_r_template(spatial_spec)
        assert "modelsummary" in code

    def test_r_template_contains_variables(self, generator, spatial_spec):
        """R 模板包含 SPEC 中的变量."""
        code = generator.generate_r_template(spatial_spec)
        assert "debt_risk" in code
        assert "fiscal_gap" in code


# ===== 5. Python 模板生成测试 =====

class TestPythonTemplate:
    """测试 Python 模板生成."""

    def test_python_template_contains_imports(self, generator, spatial_spec):
        """Python 模板包含所需库."""
        code = generator.generate_python_template(spatial_spec)
        assert "import statsmodels" in code
        assert "from linearmodels.panel" in code
        assert "import pandas" in code
        assert "import matplotlib" in code

    def test_python_template_contains_panelols(self, generator, spatial_spec):
        """Python 模板使用 PanelOLS 固定效应回归."""
        code = generator.generate_python_template(spatial_spec)
        assert "PanelOLS" in code
        assert "RandomEffects" in code

    def test_python_template_contains_vif(self, generator, spatial_spec):
        """Python 模板包含 VIF 检验."""
        code = generator.generate_python_template(spatial_spec)
        assert "variance_inflation_factor" in code or "vif" in code.lower()

    def test_python_template_contains_variables(self, generator, spatial_spec):
        """Python 模板包含 SPEC 中的变量."""
        code = generator.generate_python_template(spatial_spec)
        assert "debt_risk" in code
        assert "fiscal_gap" in code


# ===== 6. 完整模板生成测试（智能追加） =====

class TestFullTemplate:
    """测试 generate_full_template 智能追加."""

    def test_full_stata_adds_spatial(self, generator, spatial_spec):
        """检测到空间关键词后追加空间计量模板."""
        code = generator.generate_full_template(spatial_spec, lang="stata")
        assert "Moran" in code
        assert "SDM" in code or "sdm" in code
        assert "SAR" in code or "sar" in code

    def test_full_stata_adds_iv(self, generator, spatial_spec):
        """检测到工具变量关键词后追加 IV 模板."""
        code = generator.generate_full_template(spatial_spec, lang="stata")
        assert "2sls" in code.lower() or "ivregress" in code

    def test_full_stata_adds_mediation(self, generator, spatial_spec):
        """检测到中介关键词后追加中介效应模板."""
        code = generator.generate_full_template(spatial_spec, lang="stata")
        assert "中介" in code
        assert "Sobel" in code or "sobel" in code
        assert "Baron" in code or "三步法" in code

    def test_full_stata_adds_did(self, generator, did_spec):
        """检测到 DID 关键词后追加 DID 模板."""
        code = generator.generate_full_template(did_spec, lang="stata")
        assert "双重差分" in code or "DID" in code
        assert "事件研究" in code or "event" in code.lower()
        assert "平行趋势" in code

    def test_full_stata_adds_psm(self, generator, psm_spec):
        """检测到 PSM 关键词后追加 PSM 模板."""
        code = generator.generate_full_template(psm_spec, lang="stata")
        assert "psmatch2" in code
        assert "倾向得分匹配" in code

    def test_full_simple_spec_no_extra(self, generator, simple_spec):
        """简单 SPEC 不追加额外模板."""
        code = generator.generate_full_template(simple_spec, lang="stata")
        # 不应包含空间/IV/DID/PSM/中介段落
        assert "Moran" not in code
        assert "ivregress" not in code
        assert "psmatch2" not in code

    def test_full_unsupported_lang_raises(self, generator, simple_spec):
        """不支持的语言引发 ValueError."""
        with pytest.raises(ValueError, match="不支持的语言"):
            generator.generate_full_template(simple_spec, lang="matlab")

    def test_full_template_contains_base_flow(self, generator, spatial_spec):
        """完整模板包含基础流程."""
        code = generator.generate_full_template(spatial_spec, lang="stata")
        assert "基准回归" in code
        assert "稳健性检验" in code
        assert "esttab" in code


# ===== 7. 额外模板段落测试 =====

class TestExtraTemplates:
    """测试各额外模板段落生成."""

    def test_iv_template_contains_2sls(self, generator, spatial_spec):
        """IV 模板包含 2SLS 回归."""
        v = generator._extract_variables_from_spec(spatial_spec)
        code = generator._generate_iv_template(v)
        assert "ivregress 2sls" in code
        assert "第一阶段" in code
        assert "弱工具变量" in code

    def test_iv_template_contains_star(self, generator, spatial_spec):
        """IV 模板包含显著性星号."""
        v = generator._extract_variables_from_spec(spatial_spec)
        code = generator._generate_iv_template(v)
        assert "star(* 0.10 ** 0.05 *** 0.01)" in code

    def test_did_template_contains_event_study(self, generator, did_spec):
        """DID 模板包含事件研究法."""
        v = generator._extract_variables_from_spec(did_spec)
        code = generator._generate_did_template(v)
        assert "事件研究" in code
        assert "平行趋势" in code
        assert "event_time" in code

    def test_did_template_contains_placebo(self, generator, did_spec):
        """DID 模板包含安慰剂检验."""
        v = generator._extract_variables_from_spec(did_spec)
        code = generator._generate_did_template(v)
        assert "安慰剂" in code or "bootstrap" in code

    def test_psm_template_contains_psmatch2(self, generator, psm_spec):
        """PSM 模板包含 psmatch2 命令."""
        v = generator._extract_variables_from_spec(psm_spec)
        code = generator._generate_psm_template(v)
        assert "psmatch2" in code
        assert "平衡性检验" in code or "pstest" in code
        assert "核匹配" in code
        assert "半径匹配" in code

    def test_mediation_template_contains_three_steps(self, generator, spatial_spec):
        """中介模板包含 Baron & Kenny 三步法."""
        v = generator._extract_variables_from_spec(spatial_spec)
        code = generator._generate_mediation_template(v)
        assert "第一步" in code
        assert "第二步" in code
        assert "第三步" in code
        assert "Sobel" in code
        assert "总效应" in code
        assert "直接效应" in code

    def test_spatial_template_contains_moran(self, generator, spatial_spec):
        """空间模板包含 Moran's I 检验."""
        v = generator._extract_variables_from_spec(spatial_spec)
        code = generator._generate_spatial_template(v)
        assert "Moran" in code
        assert "spatgsa" in code or "moran" in code

    def test_spatial_template_contains_weight_matrix(self, generator, spatial_spec):
        """空间模板包含空间权重矩阵构建."""
        v = generator._extract_variables_from_spec(spatial_spec)
        code = generator._generate_spatial_template(v)
        assert "权重矩阵" in code
        assert "spmat" in code

    def test_spatial_template_contains_sar_sem_sdm(self, generator, spatial_spec):
        """空间模板包含 SAR/SEM/SDM 模型."""
        v = generator._extract_variables_from_spec(spatial_spec)
        code = generator._generate_spatial_template(v)
        assert "SAR" in code or "sar" in code.lower()
        assert "SEM" in code or "sem" in code.lower()
        assert "SDM" in code or "sdm" in code.lower()
        assert "xsmle" in code

    def test_spatial_template_contains_effect_decomposition(self, generator, spatial_spec):
        """空间模板包含效应分解（直接/间接/总效应）."""
        v = generator._extract_variables_from_spec(spatial_spec)
        code = generator._generate_spatial_template(v)
        assert "直接效应" in code
        assert "间接效应" in code
        assert "总效应" in code
        assert "溢出" in code

    def test_spatial_template_contains_lm_test(self, generator, spatial_spec):
        """空间模板包含 LM 检验."""
        v = generator._extract_variables_from_spec(spatial_spec)
        code = generator._generate_spatial_template(v)
        assert "LM" in code

    def test_spatial_template_contains_robustness_weight(self, generator, spatial_spec):
        """空间模板包含替换权重矩阵的稳健性检验."""
        v = generator._extract_variables_from_spec(spatial_spec)
        code = generator._generate_spatial_template(v)
        assert "替换空间权重" in code or "反距离" in code
