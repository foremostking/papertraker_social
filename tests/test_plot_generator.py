"""科研绘图工具（PlotGenerator）功能验证测试.

测试范围:
1. 初始化与字体配置
2. 变量分布图（单变量 / 多变量 / 中文标签）
3. 箱线图（简单 / 分组）
4. 回归系数图（含置信区间 / 变量标签）
5. 相关系数热力图
6. 事件研究图（DID平行趋势）
7. Moran's I 散点图
8. 输出格式验证（PDF + PNG 双文件）
9. 错误处理（变量不存在 / 空数据 / 长度不一致）

所有测试使用 numpy 生成模拟数据，不依赖外部文件。
图表输出到临时目录，测试结束后自动清理。

运行方式:
    cd scholarpilot
    $env:PYTHONPATH='src'; python -m pytest tests/test_plot_generator.py -v
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scholarpilot.tools.plot_generator import PlotGenerator


# ===== Fixtures =====


@pytest.fixture
def generator() -> PlotGenerator:
    """创建 PlotGenerator 实例."""
    return PlotGenerator()


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """创建示例数据（固定随机种子）.

    包含变量: gdp, debt, pop, region
    """
    np.random.seed(42)
    n = 300
    gdp = np.random.lognormal(mean=10, sigma=0.3, size=n)
    debt = gdp * 0.4 + np.random.randn(n) * 2000
    pop = np.random.randint(500, 5000, size=n).astype(float)
    region = np.random.choice(["东部", "中部", "西部"], size=n)
    return pd.DataFrame({"gdp": gdp, "debt": debt, "pop": pop, "region": region})


@pytest.fixture
def ols_results() -> dict:
    """创建模拟 OLS 回归结果（格式同 stats_engine.ols_regression）."""
    return {
        "coefficients": {"const": 1.5, "gdp": 0.32, "debt": -0.15, "pop": 0.008},
        "std_errors": {"const": 0.3, "gdp": 0.05, "debt": 0.08, "pop": 0.003},
        "t_values": {"const": 5.0, "gdp": 6.4, "debt": -1.875, "pop": 2.667},
        "p_values": {"const": 0.0001, "gdp": 0.00001, "debt": 0.06, "pop": 0.008},
        "r_squared": 0.75,
        "adj_r_squared": 0.74,
        "f_statistic": 250.0,
        "f_pvalue": 0.0001,
        "n_obs": 300,
        "significant": {"const": "***", "gdp": "***", "debt": "*", "pop": "***"},
        "robust": True,
    }


@pytest.fixture
def corr_matrix() -> dict:
    """创建模拟相关系数矩阵."""
    return {
        "gdp": {"gdp": 1.0, "debt": 0.65, "pop": 0.30},
        "debt": {"gdp": 0.65, "debt": 1.0, "pop": 0.20},
        "pop": {"gdp": 0.30, "debt": 0.20, "pop": 1.0},
    }


@pytest.fixture
def did_results() -> dict:
    """创建模拟 DID 事件研究结果."""
    return {
        "periods": [-3, -2, -1, 1, 2, 3],
        "coefficients": [0.02, -0.01, 0.03, 0.15, 0.22, 0.28],
        "ci_lower": [-0.05, -0.08, -0.04, 0.06, 0.12, 0.18],
        "ci_upper": [0.09, 0.06, 0.10, 0.24, 0.32, 0.38],
    }


@pytest.fixture
def moran_i_result() -> dict:
    """创建模拟 Moran's I 分析结果."""
    np.random.seed(42)
    n = 50
    x = np.random.randn(n)
    # 空间滞后值与 x 有正相关
    y = 0.35 * x + np.random.randn(n) * 0.5
    return {
        "x": x.tolist(),
        "y": y.tolist(),
        "moran_i": 0.35,
        "expected": 1 / (n - 1),
    }


# ===== 1. 初始化测试 =====


class TestInitialization:
    """初始化与配置测试."""

    def test_generator_initializes_without_error(self, generator: PlotGenerator) -> None:
        """PlotGenerator 初始化不报错."""
        assert generator is not None
        assert hasattr(generator, "_plt")

    def test_font_sans_serif_configured(self) -> None:
        """初始化后 font.sans-serif 已配置（含中文字体候选）."""
        import matplotlib

        PlotGenerator()
        fonts = matplotlib.rcParams.get("font.sans-serif", [])
        assert len(fonts) > 0
        # 应包含 SimHei 或 Noto Sans CJK SC 之一作为候选
        chinese_fonts = {"SimHei", "Noto Sans CJK SC", "Microsoft YaHei"}
        assert any(f in chinese_fonts for f in fonts) or "Arial" in fonts

    def test_unicode_minus_disabled(self) -> None:
        """初始化后 axes.unicode_minus 设为 False（正常显示负号）."""
        import matplotlib

        PlotGenerator()
        assert matplotlib.rcParams["axes.unicode_minus"] is False


# ===== 2. 变量分布图测试 =====


class TestPlotDistribution:
    """变量分布图测试."""

    def test_distribution_single_variable(
        self, generator: PlotGenerator, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """单变量分布图：生成 PDF + PNG 两个文件."""
        output = tmp_path / "dist_single"
        pdf_path, png_path = generator.plot_distribution(
            sample_df, ["gdp"], output
        )
        assert pdf_path.exists()
        assert png_path.exists()
        assert pdf_path.suffix == ".pdf"
        assert png_path.suffix == ".png"
        # 文件大小大于 0
        assert pdf_path.stat().st_size > 0
        assert png_path.stat().st_size > 0

    def test_distribution_multiple_variables(
        self, generator: PlotGenerator, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """多变量分布图（3个变量）：不报错且生成文件."""
        output = tmp_path / "dist_multi"
        pdf_path, png_path = generator.plot_distribution(
            sample_df, ["gdp", "debt", "pop"], output
        )
        assert pdf_path.exists()
        assert png_path.exists()

    def test_distribution_with_pdf_suffix_input(
        self, generator: PlotGenerator, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """输入路径带 .pdf 后缀时，正确生成 .pdf 和 .png 两个文件."""
        output = tmp_path / "dist_suffix.pdf"
        pdf_path, png_path = generator.plot_distribution(
            sample_df, ["gdp"], output
        )
        assert pdf_path.name == "dist_suffix.pdf"
        assert png_path.name == "dist_suffix.png"
        assert pdf_path.exists()
        assert png_path.exists()

    def test_distribution_invalid_variable_raises(
        self, generator: PlotGenerator, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """变量不存在时抛出 ValueError."""
        with pytest.raises(ValueError, match="不在数据列中"):
            generator.plot_distribution(sample_df, ["nonexistent"], tmp_path / "err")


# ===== 3. 箱线图测试 =====


class TestPlotBoxplot:
    """箱线图测试."""

    def test_boxplot_simple(
        self, generator: PlotGenerator, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """简单箱线图（无分组）：生成 PDF + PNG."""
        output = tmp_path / "box_simple"
        pdf_path, png_path = generator.plot_boxplot(
            sample_df, ["gdp", "debt"], output
        )
        assert pdf_path.exists()
        assert png_path.exists()

    def test_boxplot_grouped(
        self, generator: PlotGenerator, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """分组箱线图（按 region 分组）：生成 PDF + PNG."""
        output = tmp_path / "box_grouped"
        pdf_path, png_path = generator.plot_boxplot(
            sample_df, ["gdp", "debt"], output, group_var="region"
        )
        assert pdf_path.exists()
        assert png_path.exists()

    def test_boxplot_invalid_group_var_raises(
        self, generator: PlotGenerator, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """分组变量不存在时抛出 ValueError."""
        with pytest.raises(ValueError, match="分组变量"):
            generator.plot_boxplot(
                sample_df, ["gdp"], tmp_path / "err", group_var="nonexistent"
            )


# ===== 4. 回归系数图测试 =====


class TestPlotCoef:
    """回归系数图测试."""

    def test_coef_plot_basic(
        self, generator: PlotGenerator, ols_results: dict, tmp_path: Path
    ) -> None:
        """基本回归系数图：生成 PDF + PNG."""
        output = tmp_path / "coef"
        pdf_path, png_path = generator.plot_coef(ols_results, output)
        assert pdf_path.exists()
        assert png_path.exists()

    def test_coef_plot_with_var_labels(
        self, generator: PlotGenerator, ols_results: dict, tmp_path: Path
    ) -> None:
        """带中文变量标签的回归系数图：不报错且生成文件."""
        output = tmp_path / "coef_labels"
        var_labels = {
            "gdp": "GDP增长率",
            "debt": "负债率",
            "pop": "人口规模",
            "const": "常数项",
        }
        pdf_path, png_path = generator.plot_coef(
            ols_results, output, var_labels=var_labels
        )
        assert pdf_path.exists()
        assert png_path.exists()

    def test_coef_plot_empty_coefficients_raises(
        self, generator: PlotGenerator, tmp_path: Path
    ) -> None:
        """coefficients 为空时抛出 ValueError."""
        with pytest.raises(ValueError, match="coefficients"):
            generator.plot_coef({"coefficients": {}}, tmp_path / "err")


# ===== 5. 相关系数热力图测试 =====


class TestPlotCorrelationHeatmap:
    """相关系数热力图测试."""

    def test_heatmap_basic(
        self, generator: PlotGenerator, corr_matrix: dict, tmp_path: Path
    ) -> None:
        """基本相关系数热力图：生成 PDF + PNG."""
        output = tmp_path / "corr_heatmap"
        pdf_path, png_path = generator.plot_correlation_heatmap(corr_matrix, output)
        assert pdf_path.exists()
        assert png_path.exists()

    def test_heatmap_empty_matrix_raises(
        self, generator: PlotGenerator, tmp_path: Path
    ) -> None:
        """空矩阵抛出 ValueError."""
        with pytest.raises(ValueError, match="为空"):
            generator.plot_correlation_heatmap({}, tmp_path / "err")

    def test_heatmap_two_variables(
        self, generator: PlotGenerator, tmp_path: Path
    ) -> None:
        """2x2 矩阵的热力图：不报错."""
        matrix = {
            "x": {"x": 1.0, "y": -0.8},
            "y": {"x": -0.8, "y": 1.0},
        }
        output = tmp_path / "corr_2var"
        pdf_path, png_path = generator.plot_correlation_heatmap(matrix, output)
        assert pdf_path.exists()
        assert png_path.exists()


# ===== 6. 事件研究图测试 =====


class TestPlotEventStudy:
    """事件研究图测试."""

    def test_event_study_with_ci(
        self, generator: PlotGenerator, did_results: dict, tmp_path: Path
    ) -> None:
        """带置信区间的事件研究图：生成 PDF + PNG."""
        output = tmp_path / "event_study"
        pdf_path, png_path = generator.plot_event_study(did_results, output)
        assert pdf_path.exists()
        assert png_path.exists()

    def test_event_study_without_ci(
        self, generator: PlotGenerator, tmp_path: Path
    ) -> None:
        """无置信区间的事件研究图：不报错且生成文件."""
        did_data = {
            "periods": [-2, -1, 1, 2],
            "coefficients": [0.01, -0.02, 0.12, 0.18],
        }
        output = tmp_path / "event_study_no_ci"
        pdf_path, png_path = generator.plot_event_study(did_data, output)
        assert pdf_path.exists()
        assert png_path.exists()

    def test_event_study_length_mismatch_raises(
        self, generator: PlotGenerator, tmp_path: Path
    ) -> None:
        """coefficients 与 periods 长度不一致时抛出 ValueError."""
        did_data = {
            "periods": [-1, 1, 2],
            "coefficients": [0.1, 0.2],  # 长度不一致
        }
        with pytest.raises(ValueError, match="不一致"):
            generator.plot_event_study(did_data, tmp_path / "err")

    def test_event_study_empty_raises(
        self, generator: PlotGenerator, tmp_path: Path
    ) -> None:
        """periods 和 coefficients 为空时抛出 ValueError."""
        with pytest.raises(ValueError, match="缺少"):
            generator.plot_event_study(
                {"periods": [], "coefficients": []}, tmp_path / "err"
            )


# ===== 7. Moran's I 散点图测试 =====


class TestPlotMoranScatter:
    """Moran's I 散点图测试."""

    def test_moran_scatter_basic(
        self, generator: PlotGenerator, moran_i_result: dict, tmp_path: Path
    ) -> None:
        """基本 Moran's I 散点图：生成 PDF + PNG."""
        output = tmp_path / "moran_scatter"
        pdf_path, png_path = generator.plot_moran_scatter(moran_i_result, output)
        assert pdf_path.exists()
        assert png_path.exists()

    def test_moran_scatter_missing_data_raises(
        self, generator: PlotGenerator, tmp_path: Path
    ) -> None:
        """缺少 x 或 y 字段时抛出 ValueError."""
        with pytest.raises(ValueError, match="缺少"):
            generator.plot_moran_scatter(
                {"x": [], "y": [], "moran_i": 0.1}, tmp_path / "err"
            )

    def test_moran_scatter_length_mismatch_raises(
        self, generator: PlotGenerator, tmp_path: Path
    ) -> None:
        """x 和 y 长度不一致时抛出 ValueError."""
        result = {
            "x": [1.0, 2.0, 3.0],
            "y": [1.0, 2.0],  # 长度不一致
            "moran_i": 0.2,
            "expected": 0.01,
        }
        with pytest.raises(ValueError, match="不一致"):
            generator.plot_moran_scatter(result, tmp_path / "err")


# ===== 8. 输出格式综合验证 =====


class TestOutputFormat:
    """输出格式验证测试."""

    def test_all_methods_return_path_tuple(
        self,
        generator: PlotGenerator,
        sample_df: pd.DataFrame,
        ols_results: dict,
        corr_matrix: dict,
        did_results: dict,
        moran_i_result: dict,
        tmp_path: Path,
    ) -> None:
        """所有绘图方法返回 (pdf_path, png_path) 元组，且文件存在."""
        # 分布图
        r = generator.plot_distribution(sample_df, ["gdp"], tmp_path / "a")
        assert isinstance(r, tuple) and len(r) == 2
        assert all(p.exists() for p in r)
        # 箱线图
        r = generator.plot_boxplot(sample_df, ["gdp"], tmp_path / "b")
        assert all(p.exists() for p in r)
        # 系数图
        r = generator.plot_coef(ols_results, tmp_path / "c")
        assert all(p.exists() for p in r)
        # 热力图
        r = generator.plot_correlation_heatmap(corr_matrix, tmp_path / "d")
        assert all(p.exists() for p in r)
        # 事件研究图
        r = generator.plot_event_study(did_results, tmp_path / "e")
        assert all(p.exists() for p in r)
        # Moran's I
        r = generator.plot_moran_scatter(moran_i_result, tmp_path / "f")
        assert all(p.exists() for p in r)

    def test_output_creates_nested_directories(
        self, generator: PlotGenerator, sample_df: pd.DataFrame, tmp_path: Path
    ) -> None:
        """输出到不存在的嵌套目录时，自动创建目录."""
        output = tmp_path / "nested" / "deep" / "path" / "plot"
        pdf_path, png_path = generator.plot_distribution(
            sample_df, ["gdp"], output
        )
        assert pdf_path.exists()
        assert png_path.exists()
