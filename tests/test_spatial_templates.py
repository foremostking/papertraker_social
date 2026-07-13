r"""空间计量代码模板测试（R + Python 版本）。

测试范围:
== R 模板 ==
1. R 模板生成不报错
2. R 模板包含关键包（spdep / spreg / splm）
3. R 模板包含 Moran's I（全局 / 局部 / 逐年）
4. R 模板包含 SAR / SEM / SDM 模型
5. R 模板包含效应分解（impacts）
6. R 模板包含空间权重矩阵（Queen / KNN / 反距离）

== Python 模板 ==
7. Python 模板生成不报错
8. Python 模板包含关键包（libpysal / esda / spreg）
9. Python 模板包含 ML_Lag / ML_Error / GM_Lag / GM_Error
10. Python 模板包含 Moran's I 与 to_latex 输出

== 综合测试 ==
11. _generate_spatial_template() 同时包含三种语言代码（Stata / R / Python）
12. generate_full_template() 空间计量部分包含三种语言

运行方式:
    cd d:\副业\2026\AI论文自动化工程\scholarpilot
    .venv\Scripts\python.exe -m pytest tests/test_spatial_templates.py -v --tb=short
"""

from __future__ import annotations

import sys
import os

# 确保 src 目录在 Python 路径中
_src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

import pytest

from scholarpilot.tools.code_template_generator import CodeTemplateGenerator


# ======================================================================
# 测试用 SPEC 文本
# ======================================================================

SPATIAL_SPEC = """
# 论文规格

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
分析中介效应：fiscal_gap -> financial_development -> debt_risk

## 数据需求
- 数据来源：Wind数据库
- 样本期间：2010-2023年
- 截面单元：31个省份
"""


# ======================================================================
# 测试夹具
# ======================================================================

@pytest.fixture
def generator():
    """创建 CodeTemplateGenerator 实例."""
    return CodeTemplateGenerator()


@pytest.fixture
def spatial_vars(generator):
    """从 SPATIAL_SPEC 提取变量字典."""
    return generator._extract_variables_from_spec(SPATIAL_SPEC)


# ======================================================================
# R 模板测试
# ======================================================================

class TestSpatialRTemplate:
    """测试 _generate_spatial_r_template() 方法."""

    def test_r_template_no_error(self, generator, spatial_vars):
        """测试 1: R 模板生成不报错."""
        code = generator._generate_spatial_r_template(spatial_vars)
        assert isinstance(code, str)
        assert len(code) > 0

    def test_r_template_contains_packages(self, generator, spatial_vars):
        """测试 2: R 模板包含关键包（spdep / spreg / splm）."""
        code = generator._generate_spatial_r_template(spatial_vars)
        assert "spdep" in code
        assert "spreg" in code
        assert "splm" in code
        assert "library" in code

    def test_r_template_contains_moran(self, generator, spatial_vars):
        """测试 3: R 模板包含 Moran's I（全局 / 局部 / 逐年）."""
        code = generator._generate_spatial_r_template(spatial_vars)
        assert "Moran" in code or "moran" in code
        assert "moran.test" in code          # 全局 Moran's I
        assert "localmoran" in code          # 局部 Moran's I (LISA)
        assert "逐年" in code                 # 逐年 Moran's I

    def test_r_template_contains_sar_sem_sdm(self, generator, spatial_vars):
        """测试 4: R 模板包含 SAR / SEM / SDM 模型."""
        code = generator._generate_spatial_r_template(spatial_vars)
        assert "SAR" in code or "sar" in code.lower()
        assert "SEM" in code or "sem" in code.lower()
        assert "SDM" in code or "sdm" in code.lower()
        assert "lagsarlm" in code   # SAR / SDM 估计函数
        assert "errorsarlm" in code  # SEM 估计函数

    def test_r_template_contains_impacts(self, generator, spatial_vars):
        """测试 5: R 模板包含效应分解（impacts）."""
        code = generator._generate_spatial_r_template(spatial_vars)
        assert "impacts" in code
        assert "直接效应" in code
        assert "间接效应" in code
        assert "总效应" in code
        assert "溢出" in code

    def test_r_template_contains_weight_matrices(self, generator, spatial_vars):
        """测试 6: R 模板包含多种空间权重矩阵（Queen / KNN / 反距离）."""
        code = generator._generate_spatial_r_template(spatial_vars)
        assert "poly2nb" in code or "Queen" in code    # Queen 邻接
        assert "knn" in code.lower() or "K-nearest" in code  # K-nearest
        assert "nbdists" in code or "反距离" in code     # 反距离


# ======================================================================
# Python 模板测试
# ======================================================================

class TestSpatialPythonTemplate:
    """测试 _generate_spatial_python_template() 方法."""

    def test_python_template_no_error(self, generator, spatial_vars):
        """测试 7: Python 模板生成不报错."""
        code = generator._generate_spatial_python_template(spatial_vars)
        assert isinstance(code, str)
        assert len(code) > 0

    def test_python_template_contains_packages(self, generator, spatial_vars):
        """测试 8: Python 模板包含关键包（libpysal / esda / spreg）."""
        code = generator._generate_spatial_python_template(spatial_vars)
        assert "libpysal" in code
        assert "esda" in code
        assert "spreg" in code
        assert "import" in code

    def test_python_template_contains_ml_gm_models(self, generator, spatial_vars):
        """测试 9: Python 模板包含 ML_Lag / ML_Error / GM_Lag / GM_Error."""
        code = generator._generate_spatial_python_template(spatial_vars)
        assert "ML_Lag" in code      # SAR (ML)
        assert "ML_Error" in code    # SEM (ML)
        assert "GM_Lag" in code      # SAR (GM)
        assert "GM_Error" in code    # SEM (GM)

    def test_python_template_contains_moran_and_output(self, generator, spatial_vars):
        """测试 10: Python 模板包含 Moran's I 与 to_latex 输出."""
        code = generator._generate_spatial_python_template(spatial_vars)
        assert "Moran" in code or "moran" in code
        assert "Moran_Local" in code      # 局部 Moran's I
        assert "to_latex" in code         # LaTeX 表格输出
        assert "DataFrame" in code or "pd.DataFrame" in code  # pandas 输出


# ======================================================================
# 综合测试（_generate_spatial_template 三语言集成）
# ======================================================================

class TestSpatialTemplateIntegration:
    """测试修改后的 _generate_spatial_template() 同时包含三种语言."""

    def test_spatial_template_contains_stata(self, generator, spatial_vars):
        """测试 11a: _generate_spatial_template() 包含 Stata 代码."""
        code = generator._generate_spatial_template(spatial_vars)
        # Stata 代码特征
        assert "xsmle" in code           # Stata 空间面板命令
        assert "spatgsa" in code         # Stata Moran's I 命令
        assert "spmat" in code           # Stata 空间权重矩阵命令

    def test_spatial_template_contains_r(self, generator, spatial_vars):
        """测试 11b: _generate_spatial_template() 包含 R 代码."""
        code = generator._generate_spatial_template(spatial_vars)
        assert "spdep" in code
        assert "splm" in code
        assert "lagsarlm" in code
        assert "impacts" in code

    def test_spatial_template_contains_python(self, generator, spatial_vars):
        """测试 11c: _generate_spatial_template() 包含 Python 代码."""
        code = generator._generate_spatial_template(spatial_vars)
        assert "libpysal" in code
        assert "esda" in code
        assert "ML_Lag" in code
        assert "ML_Error" in code

    def test_spatial_template_contains_all_three_langs(self, generator, spatial_vars):
        """测试 11d: _generate_spatial_template() 同时包含三种语言标识."""
        code = generator._generate_spatial_template(spatial_vars)
        # Stata 标识
        assert "spmat" in code
        # R 标识
        assert "library(spdep)" in code
        # Python 标识
        assert "import libpysal" in code
        # 三种语言的标题均存在
        assert "空间计量分析" in code

    def test_full_template_contains_all_three_langs(self, generator):
        """测试 12: generate_full_template() 空间计量部分包含三种语言."""
        code = generator.generate_full_template(SPATIAL_SPEC, lang="stata")
        # Stata 空间代码
        assert "xsmle" in code
        assert "spmat" in code
        # R 空间代码
        assert "library(spdep)" in code
        assert "splm" in code
        assert "impacts" in code
        # Python 空间代码
        assert "import libpysal" in code
        assert "ML_Lag" in code
        assert "ML_Error" in code

    def test_full_template_r_lang_contains_spatial(self, generator):
        """测试 12b: generate_full_template(lang='r') 也包含空间计量三语言段落."""
        code = generator.generate_full_template(SPATIAL_SPEC, lang="r")
        # 基础 R 模板 + 空间计量段落（含 Stata/R/Python 三段）
        assert "library(spdep)" in code
        assert "import libpysal" in code
        assert "xsmle" in code
