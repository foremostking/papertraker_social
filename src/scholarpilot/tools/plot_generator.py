"""科研绘图工具，生成期刊标准图表.

面向中国金融学实证研究，使用 matplotlib 生成符合学术期刊规范的图表。
支持变量分布图、箱线图、回归系数图、相关系数热力图、事件研究图（DID平行趋势）
和 Moran's I 散点图（空间自相关）。

图表规范：
    - 字体：中文用 Noto Sans CJK SC 或 SimHei，英文用 Arial
    - 输出：PDF（矢量）+ PNG（预览），两个文件
    - 尺寸：单栏 8cm，双栏 17cm
    - 风格：白底、细线、灰度色阶（学术风格）
    - DPI：300

设计原则：
    - 延迟导入 matplotlib / numpy / pandas，缺失时抛出友好错误
    - 所有图表同时输出 PDF 和 PNG 两种格式
    - 中文字体自动探测与回退，确保中文标签正确显示

典型使用流程::

    generator = PlotGenerator()
    generator.plot_distribution(df, ["gdp", "debt"], "output/distribution")
    generator.plot_coef(ols_result, "output/coef", var_labels={"x1": "解释变量1"})
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import pandas as pd

__all__ = ["PlotGenerator"]


# ========== 尺寸常量（厘米转英寸）==========

#: 单栏图宽度（8cm → inch）
SINGLE_COL_WIDTH = 8 / 2.54
#: 双栏图宽度（17cm → inch）
DOUBLE_COL_WIDTH = 17 / 2.54
#: 输出 DPI
DPI = 300


# ========== 延迟导入 ==========


def _import_matplotlib() -> Any:
    """延迟导入 matplotlib 并配置非交互式后端。

    Returns:
        matplotlib.pyplot 模块。

    Raises:
        ImportError: matplotlib 未安装。
    """
    try:
        import matplotlib

        # 使用 Agg 后端，避免无显示环境报错
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError as e:
        raise ImportError(
            "matplotlib 是科研绘图所必需的依赖。请安装: pip install matplotlib"
        ) from e


def _import_numpy() -> Any:
    """延迟导入 numpy。

    Returns:
        numpy 模块。

    Raises:
        ImportError: numpy 未安装。
    """
    try:
        import numpy as np

        return np
    except ImportError as e:
        raise ImportError(
            "numpy 是科研绘图所必需的依赖。请安装: pip install numpy"
        ) from e


def _import_pandas() -> Any:
    """延迟导入 pandas。

    Returns:
        pandas 模块。

    Raises:
        ImportError: pandas 未安装。
    """
    try:
        import pandas as pd

        return pd
    except ImportError as e:
        raise ImportError(
            "pandas 是科研绘图所必需的依赖。请安装: pip install pandas"
        ) from e


# ========== 字体与样式配置 ==========


def _setup_chinese_font() -> list[str]:
    """配置中文字体，返回可用的字体候选列表。

    按优先级探测以下中文字体：
        Noto Sans CJK SC → SimHei → Microsoft YaHei → WenQuanYi Zen Hei → Arial

    Returns:
        字体名称候选列表（已设置到 matplotlib rcParams）。
    """
    import matplotlib

    # 中文字体候选（按优先级排列）
    font_candidates = [
        "Noto Sans CJK SC",
        "SimHei",
        "Microsoft YaHei",
        "WenQuanYi Zen Hei",
        "Arial Unicode MS",
        "Arial",
    ]

    # 获取系统可用字体
    try:
        from matplotlib.font_manager import findSystemFonts, FontProperties

        available_fonts: set[str] = set()
        for font_path in findSystemFonts():
            try:
                fp = FontProperties(fname=font_path)
                name = fp.get_name()
                if name:
                    available_fonts.add(name)
            except Exception:
                continue
        # 过滤出实际可用的中文字体
        usable = [f for f in font_candidates if f in available_fonts]
        if not usable:
            logger.warning(
                "未检测到中文字体，中文可能显示为方框。"
                "建议安装 Noto Sans CJK SC 或 SimHei。"
            )
            usable = font_candidates
    except Exception as e:
        logger.warning("字体探测失败，使用默认候选列表: %s", e)
        usable = font_candidates

    # 设置 matplotlib 字体
    matplotlib.rcParams["font.sans-serif"] = usable
    matplotlib.rcParams["axes.unicode_minus"] = False  # 正常显示负号

    logger.debug("中文字体候选: %s", usable)
    return usable


def _apply_academic_style(plt: Any) -> None:
    """应用学术图表风格：白底、细线、灰度色阶。

    Args:
        plt: matplotlib.pyplot 模块。
    """
    import matplotlib

    matplotlib.rcParams.update(
        {
            # 白底
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            # 细线
            "axes.linewidth": 0.6,
            "lines.linewidth": 1.0,
            "xtick.major.width": 0.5,
            "ytick.major.width": 0.5,
            # 字体大小（学术期刊常用）
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            # 边框：仅左下
            "axes.spines.top": False,
            "axes.spines.right": False,
            # 网格
            "axes.grid": False,
        }
    )


#: 灰度色阶（学术风格），从深到浅
_GRAYSCALE_COLORS = [
    "#1a1a1a",
    "#404040",
    "#666666",
    "#8c8c8c",
    "#b3b3b3",
    "#d9d9d9",
    "#f0f0f0",
]


def _get_grayscale_palette(n: int) -> list[str]:
    """获取 n 个灰度色阶。

    Args:
        n: 所需颜色数量。

    Returns:
        灰度颜色列表（十六进制字符串）。
    """
    np = _import_numpy()
    if n <= len(_GRAYSCALE_COLORS):
        return _GRAYSCALE_COLORS[:n]
    # 颜色不足时在灰度范围内线性插值
    return [
        "#" + format(int(v), "02x") * 3
        for v in np.linspace(30, 220, n, dtype=int)
    ]


# ========== 路径处理 ==========


def _resolve_output_paths(output_path: str | Path) -> tuple[Path, Path]:
    """根据输出路径推导 PDF 和 PNG 文件路径。

    将 output_path 视为基名，自动生成 .pdf 和 .png 后缀。
    若 output_path 已带 .pdf / .png 后缀则先去除再重新拼接。

    Args:
        output_path: 输出路径（可带或不带后缀）。

    Returns:
        (pdf_path, png_path) 元组。
    """
    p = Path(output_path)
    # 去除已有后缀
    if p.suffix.lower() in (".pdf", ".png"):
        base = p.with_suffix("")
    else:
        base = p
    pdf_path = base.with_suffix(".pdf")
    png_path = base.with_suffix(".png")
    return pdf_path, png_path


def _save_figure(fig: Any, output_path: str | Path) -> tuple[Path, Path]:
    """保存图表为 PDF + PNG 两种格式。

    Args:
        fig: matplotlib Figure 对象。
        output_path: 输出路径基名。

    Returns:
        (pdf_path, png_path) 实际保存的文件路径元组。
    """
    pdf_path, png_path = _resolve_output_paths(output_path)

    # 确保父目录存在
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    # 保存 PDF（矢量）
    fig.savefig(str(pdf_path), format="pdf", dpi=DPI, bbox_inches="tight")
    logger.debug("已保存 PDF: %s", pdf_path)

    # 保存 PNG（预览）
    fig.savefig(str(png_path), format="png", dpi=DPI, bbox_inches="tight")
    logger.debug("已保存 PNG: %s", png_path)

    return pdf_path, png_path


class PlotGenerator:
    """科研绘图工具，生成期刊标准图表。

    面向中国金融学实证研究，生成符合学术期刊规范的 matplotlib 图表。
    所有图表同时输出 PDF（矢量）和 PNG（预览）两种格式。

    功能：
        - 变量分布图（直方图 + 核密度图）
        - 箱线图（可分组）
        - 回归系数图（含 95% 置信区间）
        - 相关系数热力图
        - 事件研究图（DID 平行趋势检验）
        - Moran's I 散点图（空间自相关）

    使用示例::

        generator = PlotGenerator()
        # 变量分布图
        generator.plot_distribution(df, ["gdp", "debt"], "figs/dist")
        # 回归系数图
        generator.plot_coef(ols_result, "figs/coef",
                            var_labels={"x1": "GDP增长率", "x2": "负债率"})
        # 事件研究图
        generator.plot_event_study(did_result, "figs/event_study")
    """

    def __init__(self) -> None:
        """初始化绘图工具，配置中文字体和学术风格。"""
        try:
            self._plt = _import_matplotlib()
            _setup_chinese_font()
            _apply_academic_style(self._plt)
            logger.info("PlotGenerator 初始化完成，已配置中文字体和学术风格")
        except ImportError as e:
            logger.error("matplotlib 初始化失败: %s", e)
            raise

    # ========== 变量分布图 ==========

    def plot_distribution(
        self,
        df: Any,
        variables: list[str],
        output_path: str | Path,
        style: str = "academic",
    ) -> tuple[Path, Path]:
        """变量分布图：直方图 + 核密度图。

        为每个变量生成一个子图，包含直方图（带频次）和核密度估计曲线。
        多变量时按网格排列子图。

        Args:
            df: pandas DataFrame。
            variables: 要绘制的变量名列表。
            output_path: 输出路径基名（自动生成 .pdf 和 .png）。
            style: 绘图风格，"academic"（默认，灰度学术风）或 "default"。

        Returns:
            (pdf_path, png_path) 保存的文件路径元组。

        Raises:
            ImportError: matplotlib / pandas 未安装。
            ValueError: 变量不存在于数据中。
        """
        plt = self._plt
        np = _import_numpy()

        # 校验变量
        for var in variables:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")

        n_vars = len(variables)
        if n_vars == 0:
            raise ValueError("变量列表为空")

        # 子图布局：最多 2 列
        n_cols = min(n_vars, 2)
        n_rows = (n_vars + n_cols - 1) // n_cols
        fig_width = SINGLE_COL_WIDTH if n_vars == 1 else DOUBLE_COL_WIDTH
        fig, axes = plt.subplots(
            n_rows, n_cols, figsize=(fig_width, fig_width * 0.4 * n_rows)
        )
        # 统一为二维数组方便索引
        axes_arr = np.atleast_2d(axes).flatten()

        palette = _get_grayscale_palette(n_vars)

        for idx, var in enumerate(variables):
            ax = axes_arr[idx]
            data = df[var].dropna().values

            if len(data) == 0:
                ax.text(0.5, 0.5, f"{var}\n（无有效数据）", ha="center", va="center",
                        transform=ax.transAxes)
                continue

            # 直方图
            ax.hist(
                data,
                bins=30,
                density=True,
                color=palette[idx % len(palette)],
                alpha=0.6,
                edgecolor="white",
                linewidth=0.3,
                label="直方图",
            )

            # 核密度估计（简易 KDE：高斯核）
            if len(data) > 1:
                kde_x, kde_y = self._gaussian_kde(data, np)
                ax.plot(
                    kde_x,
                    kde_y,
                    color="#1a1a1a",
                    linewidth=1.0,
                    label="核密度",
                )

            ax.set_title(var, fontsize=9)
            ax.set_xlabel(var, fontsize=8)
            ax.set_ylabel("密度", fontsize=8)
            ax.legend(frameon=False, fontsize=6)

        # 隐藏多余子图
        for idx in range(n_vars, len(axes_arr)):
            axes_arr[idx].set_visible(False)

        fig.tight_layout()
        result = _save_figure(fig, output_path)
        plt.close(fig)

        logger.info("变量分布图已生成: %s, %d 个变量", output_path, n_vars)
        return result

    @staticmethod
    def _gaussian_kde(data: Any, np: Any, n_points: int = 200) -> tuple[Any, Any]:
        """简易高斯核密度估计。

        使用 Silverman 经验法则选择带宽，避免依赖 scipy。

        Args:
            data: 一维数据数组。
            np: numpy 模块。
            n_points: 采样点数。

        Returns:
            (x_grid, density) 估计的密度曲线。
        """
        n = len(data)
        std = np.std(data, ddof=1) if n > 1 else 0.0
        if std == 0:
            std = 1.0
        # Silverman 经验法则带宽
        h = 1.06 * std * (n ** (-1 / 5))
        if h == 0:
            h = 1.0

        x_min, x_max = float(np.min(data)), float(np.max(data))
        padding = (x_max - x_min) * 0.1 if x_max > x_min else 1.0
        x_grid = np.linspace(x_min - padding, x_max + padding, n_points)

        # 高斯核密度估计
        density = np.zeros(n_points)
        for d in data:
            density += np.exp(-0.5 * ((x_grid - d) / h) ** 2)
        density /= (n * h * np.sqrt(2 * np.pi))

        return x_grid, density

    # ========== 箱线图 ==========

    def plot_boxplot(
        self,
        df: Any,
        variables: list[str],
        output_path: str | Path,
        group_var: str | None = None,
    ) -> tuple[Path, Path]:
        """箱线图。

        绘制一个或多个变量的箱线图。若提供 group_var，则按分组变量分列展示。

        Args:
            df: pandas DataFrame。
            variables: 要绘制的变量名列表。
            output_path: 输出路径基名。
            group_var: 分组变量名。提供时按该变量分组绘制箱线图。

        Returns:
            (pdf_path, png_path) 保存的文件路径元组。

        Raises:
            ValueError: 变量不存在于数据中。
        """
        plt = self._plt

        # 校验变量
        for var in variables:
            if var not in df.columns:
                raise ValueError(f"变量 '{var}' 不在数据列中")
        if group_var is not None and group_var not in df.columns:
            raise ValueError(f"分组变量 '{group_var}' 不在数据列中")

        n_vars = len(variables)
        if n_vars == 0:
            raise ValueError("变量列表为空")

        fig_width = SINGLE_COL_WIDTH if n_vars == 1 and group_var is None else DOUBLE_COL_WIDTH
        fig, ax = plt.subplots(figsize=(fig_width, fig_width * 0.6))

        if group_var is not None:
            # 分组箱线图：每个变量按分组分列
            groups = sorted(df[group_var].dropna().unique(), key=lambda x: str(x))
            positions: list[float] = []
            box_data: list[list] = []
            labels: list[str] = []
            pos = 1.0
            gap_between_vars = 1.5

            palette = _get_grayscale_palette(len(variables))
            for vi, var in enumerate(variables):
                for gi, g in enumerate(groups):
                    subset = df.loc[df[group_var] == g, var].dropna().tolist()
                    box_data.append(subset)
                    positions.append(pos)
                    labels.append(str(g))
                    pos += 1.0
                # 变量间间隔
                pos += gap_between_vars - 1.0

            bp = ax.boxplot(
                box_data,
                positions=positions,
                widths=0.7,
                patch_artist=True,
                showfliers=True,
                flierprops=dict(marker="o", markersize=2, markerfacecolor="#999999",
                                markeredgecolor="none", alpha=0.5),
            )
            # 灰度填色
            color_idx = 0
            for vi in range(len(variables)):
                for gi in range(len(groups)):
                    patch = bp["boxes"][color_idx]
                    patch.set_facecolor(palette[vi % len(palette)])
                    patch.set_alpha(0.7)
                    patch.set_edgecolor("#333333")
                    patch.set_linewidth(0.6)
                    color_idx += 1
            for element in ["whiskers", "caps", "medians"]:
                for line in bp[element]:
                    line.set_color("#333333")
                    line.set_linewidth(0.6)

            ax.set_xticks(positions)
            ax.set_xticklabels(labels, fontsize=7)
            ax.set_xlabel(group_var, fontsize=8)
        else:
            # 简单箱线图
            box_data = [df[var].dropna().tolist() for var in variables]
            palette = _get_grayscale_palette(n_vars)

            bp = ax.boxplot(
                box_data,
                positions=range(1, n_vars + 1),
                widths=0.5,
                patch_artist=True,
                showfliers=True,
                flierprops=dict(marker="o", markersize=2, markerfacecolor="#999999",
                                markeredgecolor="none", alpha=0.5),
            )
            for i, patch in enumerate(bp["boxes"]):
                patch.set_facecolor(palette[i % len(palette)])
                patch.set_alpha(0.7)
                patch.set_edgecolor("#333333")
                patch.set_linewidth(0.6)
            for element in ["whiskers", "caps", "medians"]:
                for line in bp[element]:
                    line.set_color("#333333")
                    line.set_linewidth(0.6)

            ax.set_xticks(range(1, n_vars + 1))
            ax.set_xticklabels(variables, fontsize=7)

        ax.set_ylabel("数值", fontsize=8)

        fig.tight_layout()
        result = _save_figure(fig, output_path)
        plt.close(fig)

        logger.info("箱线图已生成: %s", output_path)
        return result

    # ========== 回归系数图 ==========

    def plot_coef(
        self,
        results_json: dict,
        output_path: str | Path,
        var_labels: dict[str, str] | None = None,
    ) -> tuple[Path, Path]:
        """回归系数图：含 95% 置信区间。

        以水平点图展示各变量回归系数及 95% 置信区间（系数 ± 1.96 * 标准误）。
        显著的系数（p<0.05）用实心点标记，不显著的用空心点。

        Args:
            results_json: 回归结果字典，格式同 stats_engine.ols_regression() 返回值::

                    {
                        "coefficients": {"const": 0.5, "x1": 0.3},
                        "std_errors": {"const": 0.1, "x1": 0.05},
                        "p_values": {"const": 0.001, "x1": 0.08},
                        "significant": {"const": "***", "x1": "*"}
                    }

            output_path: 输出路径基名。
            var_labels: 变量标签映射，将变量名替换为中文标签。如 {"x1": "GDP增长率"}。

        Returns:
            (pdf_path, png_path) 保存的文件路径元组。

        Raises:
            ValueError: 结果字典缺少必要字段。
        """
        plt = self._plt
        np = _import_numpy()

        coefficients = results_json.get("coefficients", {})
        std_errors = results_json.get("std_errors", {})
        p_values = results_json.get("p_values", {})

        if not coefficients:
            raise ValueError("结果字典中无 coefficients 字段或为空")

        # 变量顺序（const 排在最后，符合学术惯例）
        var_names = list(coefficients.keys())
        if "const" in var_names:
            var_names.remove("const")
            var_names.append("const")

        # 应用变量标签
        labels = var_labels or {}
        display_names = [labels.get(v, v) for v in var_names]

        # 计算置信区间（95%: ±1.96 * se）
        coefs = np.array([float(coefficients[v]) for v in var_names])
        ses = np.array([float(std_errors.get(v, 0.0)) for v in var_names])
        ci_lower = coefs - 1.96 * ses
        ci_upper = coefs + 1.96 * ses

        # 显著性判断（p < 0.05）
        p_vals = [float(p_values.get(v, 1.0)) for v in var_names]
        significant_mask = [p < 0.05 for p in p_vals]

        n = len(var_names)
        y_pos = np.arange(n)[::-1]  # 从上到下排列

        fig, ax = plt.subplots(figsize=(SINGLE_COL_WIDTH, max(SINGLE_COL_WIDTH * 0.5, 0.5 * n + 1)))

        # 绘制置信区间横线
        for i in range(n):
            color = "#1a1a1a" if significant_mask[i] else "#999999"
            ax.plot(
                [ci_lower[i], ci_upper[i]],
                [y_pos[i], y_pos[i]],
                color=color,
                linewidth=1.0,
            )

        # 绘制系数点（显著=实心，不显著=空心）
        for i in range(n):
            if significant_mask[i]:
                ax.plot(
                    coefs[i], y_pos[i],
                    "o", color="#1a1a1a", markersize=4,
                )
            else:
                ax.plot(
                    coefs[i], y_pos[i],
                    "o", color="white", markeredgecolor="#999999",
                    markersize=4, markeredgewidth=0.8,
                )

        # 参考线（0 线）
        ax.axvline(x=0, color="#b3b3b3", linewidth=0.5, linestyle="--")

        ax.set_yticks(y_pos)
        ax.set_yticklabels(display_names, fontsize=7)
        ax.set_xlabel("系数（95% 置信区间）", fontsize=8)
        ax.invert_yaxis()

        # 添加显著性星号到 y 轴标签
        sig_stars = results_json.get("significant", {})
        y_labels_with_stars = []
        for v in var_names:
            name = labels.get(v, v)
            stars = sig_stars.get(v, "")
            if stars:
                y_labels_with_stars.append(f"{name} {stars}")
            else:
                y_labels_with_stars.append(name)
        ax.set_yticklabels(y_labels_with_stars, fontsize=7)

        fig.tight_layout()
        result = _save_figure(fig, output_path)
        plt.close(fig)

        logger.info("回归系数图已生成: %s, %d 个变量", output_path, n)
        return result

    # ========== 相关系数热力图 ==========

    def plot_correlation_heatmap(
        self,
        corr_matrix: dict,
        output_path: str | Path,
    ) -> tuple[Path, Path]:
        """相关系数热力图。

        绘制相关系数矩阵的热力图，使用灰度色阶，并在每个单元格中标注数值。

        Args:
            corr_matrix: 相关系数矩阵字典，格式::

                    {"var1": {"var1": 1.0, "var2": 0.5},
                     "var2": {"var1": 0.5, "var2": 1.0}}

            output_path: 输出路径基名。

        Returns:
            (pdf_path, png_path) 保存的文件路径元组。

        Raises:
            ValueError: 矩阵为空或格式不正确。
        """
        plt = self._plt
        np = _import_numpy()

        if not corr_matrix:
            raise ValueError("相关系数矩阵为空")

        variables = list(corr_matrix.keys())
        n = len(variables)

        # 构建矩阵数组
        matrix = np.zeros((n, n))
        for i, v1 in enumerate(variables):
            if v1 not in corr_matrix:
                continue
            for j, v2 in enumerate(variables):
                matrix[i, j] = float(corr_matrix[v1].get(v2, 0.0))

        # 灰度色阶：-1（白）→ 0（灰）→ 1（黑）
        from matplotlib.colors import LinearSegmentedColormap

        cmap = LinearSegmentedColormap.from_list(
            "grayscale_corr",
            ["#f0f0f0", "#ffffff", "#f0f0f0", "#404040", "#1a1a1a"],
            N=256,
        )

        size = max(SINGLE_COL_WIDTH * 1.2, 0.8 * n + 1)
        fig, ax = plt.subplots(figsize=(size, size * 0.9))

        im = ax.imshow(matrix, cmap=cmap, vmin=-1, vmax=1, aspect="auto")

        # 颜色条
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label("相关系数", fontsize=7)
        cbar.ax.tick_params(labelsize=6)

        # 设置刻度
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(variables, fontsize=6, rotation=45, ha="right")
        ax.set_yticklabels(variables, fontsize=6)

        # 在单元格中标注数值
        for i in range(n):
            for j in range(n):
                val = matrix[i, j]
                # 根据背景色深浅选择文字颜色
                text_color = "white" if abs(val) > 0.6 else "#1a1a1a"
                ax.text(
                    j, i, f"{val:.2f}",
                    ha="center", va="center",
                    fontsize=5.5, color=text_color,
                )

        # 恢复边框（热力图需要四边框）
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(0.6)

        fig.tight_layout()
        result = _save_figure(fig, output_path)
        plt.close(fig)

        logger.info("相关系数热力图已生成: %s, %d 个变量", output_path, n)
        return result

    # ========== 事件研究图（DID平行趋势检验）==========

    def plot_event_study(
        self,
        did_results: dict,
        output_path: str | Path,
    ) -> tuple[Path, Path]:
        """事件研究图（DID 平行趋势检验）。

        绘制各期处理效应系数及 95% 置信区间，用于检验平行趋势假设。
        通常在事件期 0（处理当期）处画参考线。

        Args:
            did_results: DID 事件研究结果字典，格式::

                    {
                        "periods": [-3, -2, -1, 1, 2, 3],
                        "coefficients": [0.01, -0.02, 0.03, 0.15, 0.20, 0.25],
                        "ci_lower": [...],
                        "ci_upper": [...]
                    }

            output_path: 输出路径基名。

        Returns:
            (pdf_path, png_path) 保存的文件路径元组。

        Raises:
            ValueError: 数据字段缺失或长度不一致。
        """
        plt = self._plt
        np = _import_numpy()

        periods = did_results.get("periods", [])
        coefficients = did_results.get("coefficients", [])
        ci_lower = did_results.get("ci_lower", [])
        ci_upper = did_results.get("ci_upper", [])

        if not periods or not coefficients:
            raise ValueError("did_results 缺少 periods 或 coefficients 字段")

        n = len(periods)
        if len(coefficients) != n:
            raise ValueError(
                f"coefficients 长度（{len(coefficients)}）与 periods 长度（{n}）不一致"
            )

        # 若未提供置信区间，用 None 填充
        has_ci = len(ci_lower) == n and len(ci_upper) == n

        periods_arr = np.array(periods, dtype=float)
        coefs_arr = np.array(coefficients, dtype=float)

        fig, ax = plt.subplots(figsize=(DOUBLE_COL_WIDTH, DOUBLE_COL_WIDTH * 0.5))

        # 置信区间（阴影带）
        if has_ci:
            ci_low_arr = np.array(ci_lower, dtype=float)
            ci_up_arr = np.array(ci_upper, dtype=float)
            ax.fill_between(
                periods_arr, ci_low_arr, ci_up_arr,
                color="#b3b3b3", alpha=0.3, label="95% 置信区间",
            )
            # 置信区间上下边界线
            ax.plot(periods_arr, ci_low_arr, color="#999999",
                    linewidth=0.5, linestyle="--")
            ax.plot(periods_arr, ci_up_arr, color="#999999",
                    linewidth=0.5, linestyle="--")

        # 系数点与连线
        ax.plot(periods_arr, coefs_arr, "o-", color="#1a1a1a",
                markersize=4, linewidth=1.0, label="处理效应")

        # 参考线：0 线
        ax.axhline(y=0, color="#666666", linewidth=0.5, linestyle="-")

        # 参考线：事件期 0（处理当期），若存在 -1 和 1 之间则画在 0
        ax.axvline(x=0, color="#d9d9d9", linewidth=0.8, linestyle=":")

        ax.set_xlabel("相对处理时间（期）", fontsize=8)
        ax.set_ylabel("系数估计值", fontsize=8)
        ax.set_title("事件研究图（平行趋势检验）", fontsize=9)
        ax.legend(frameon=False, fontsize=6, loc="best")

        # x 轴刻度为整数期
        ax.set_xticks(periods_arr)

        fig.tight_layout()
        result = _save_figure(fig, output_path)
        plt.close(fig)

        logger.info("事件研究图已生成: %s, %d 期", output_path, n)
        return result

    # ========== Moran's I 散点图 ==========

    def plot_moran_scatter(
        self,
        moran_i_result: dict,
        output_path: str | Path,
    ) -> tuple[Path, Path]:
        """Moran's I 散点图（空间自相关）。

        绘制变量值与其空间滞后值（加权平均邻居值）的散点图，
        叠加回归拟合线（斜率即 Moran's I）。

        Args:
            moran_i_result: Moran's I 分析结果字典，格式::

                    {
                        "x": [1.2, 0.8, ...],          # 变量值
                        "y": [1.1, 0.9, ...],          # 空间滞后值
                        "moran_i": 0.35,                # Moran's I 统计量
                        "expected": 0.03                # 期望值（1/(n-1)）
                    }

            output_path: 输出路径基名。

        Returns:
            (pdf_path, png_path) 保存的文件路径元组。

        Raises:
            ValueError: 数据字段缺失。
        """
        plt = self._plt
        np = _import_numpy()

        x_data = moran_i_result.get("x", [])
        y_data = moran_i_result.get("y", [])

        if not x_data or not y_data:
            raise ValueError("moran_i_result 缺少 x 或 y 字段")

        if len(x_data) != len(y_data):
            raise ValueError(
                f"x 长度（{len(x_data)}）与 y 长度（{len(y_data)}）不一致"
            )

        x_arr = np.array(x_data, dtype=float)
        y_arr = np.array(y_data, dtype=float)
        moran_i = moran_i_result.get("moran_i", 0.0)
        expected = moran_i_result.get("expected", 0.0)

        fig, ax = plt.subplots(figsize=(SINGLE_COL_WIDTH, SINGLE_COL_WIDTH))

        # 散点图
        ax.scatter(
            x_arr, y_arr,
            s=12, c="#666666", edgecolors="white", linewidths=0.2,
            alpha=0.7, zorder=2,
        )

        # 拟合线（斜率 = Moran's I）
        # 用最小二乘拟合
        if len(x_arr) > 1 and np.std(x_arr) > 0:
            slope, intercept = np.polyfit(x_arr, y_arr, 1)
            x_fit = np.linspace(float(x_arr.min()), float(x_arr.max()), 100)
            y_fit = slope * x_fit + intercept
            ax.plot(
                x_fit, y_fit,
                color="#1a1a1a", linewidth=1.0,
                label=f"拟合线 (Moran's I = {moran_i:.4f})",
                zorder=3,
            )

        # 参考线：均值线
        ax.axhline(y=float(y_arr.mean()), color="#b3b3b3",
                   linewidth=0.5, linestyle="--", zorder=1)
        ax.axvline(x=float(x_arr.mean()), color="#b3b3b3",
                   linewidth=0.5, linestyle="--", zorder=1)

        # 象限标注
        x_mean = float(x_arr.mean())
        y_mean = float(y_arr.mean())
        ax.text(
            0.97, 0.97, "高-高", transform=ax.transAxes,
            ha="right", va="top", fontsize=6, color="#999999",
        )
        ax.text(
            0.03, 0.97, "低-高", transform=ax.transAxes,
            ha="left", va="top", fontsize=6, color="#999999",
        )
        ax.text(
            0.03, 0.03, "低-低", transform=ax.transAxes,
            ha="left", va="bottom", fontsize=6, color="#999999",
        )
        ax.text(
            0.97, 0.03, "高-低", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=6, color="#999999",
        )

        ax.set_xlabel("变量值", fontsize=8)
        ax.set_ylabel("空间滞后值", fontsize=8)
        ax.set_title("Moran's I 散点图", fontsize=9)
        ax.legend(frameon=False, fontsize=6, loc="upper left")

        # 在图中标注期望值
        ax.annotate(
            f"期望值 = {expected:.4f}",
            xy=(0.02, 0.02), xycoords="axes fraction",
            fontsize=6, color="#666666",
        )

        fig.tight_layout()
        result = _save_figure(fig, output_path)
        plt.close(fig)

        logger.info("Moran's I 散点图已生成: %s, I=%.4f", output_path, moran_i)
        return result
