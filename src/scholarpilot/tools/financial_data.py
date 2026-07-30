"""金融数据处理模块.

自动检测和解析 CSMAR/RESSET 导出的金融数据文件，
生成描述性统计，并接入 ScholarPilot 实证研究工作流。

支持的数据源:
    - CSMAR (国泰安): CSV+TXT 元数据对、ZIP 压缩包
    - RESSET (锐思): CSV、Excel、TXT
    - 通用 CSV/Excel: 自动推断

CSMAR 指纹特征:
    - 列名含 Stkcd/Accper/Typrep/TradingDate
    - 财务字段匹配 ^[ABD]\\d{9}$ 编码模式
    - ZIP 内含 [DES] 标记的 TXT 元数据文件

RESSET 指纹特征:
    - 字段含中英文标签
    - 高频文件名匹配 ^\\w+hf\\d{4}_\\d{6}(sz|sh|si)$

工作流:
    1. 用户从 CSMAR/RESSET 下载数据 → 放入 data/ 文件夹
    2. FinancialDataProcessor 自动检测文件格式和数据源
    3. 规范化列名（股票代码补零、日期解析等）
    4. 生成描述性统计 → save_stats_to_json()
    5. 统计数据注入实证章节

Usage:
    processor = FinancialDataProcessor()
    result = processor.process_directory("./data")
    stats = processor.generate_stats(result)
    processor.save_stats_to_json(stats, "./.scholar/descriptive_stats.json")
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ===== CSMAR 列名规范化映射 =====

CSMAR_COLUMN_MAP: dict[str, str] = {
    # 股票代码
    "Stkcd": "stock_code",
    "Symbol": "stock_code",
    "Sym": "stock_code",
    "StockCode": "stock_code",
    # 日期
    "TradingDate": "trading_date",
    "Accper": "accounting_period",
    "SgnYear": "year",
    "sgnyear": "year",
    "YearBuilt": "year",
    # 报表类型
    "Typrep": "report_type",
    # 常见财务指标
    "A001000000": "total_assets",
    "A002000000": "total_liabilities",
    "B001300000": "net_profit",
    "B002000000": "operating_profit",
    "D000101000": "cash_inflow_operating",
}

# CSMAR 财务字段编码模式 (A/B/D + 9位数字)
CSMAR_FINANCIAL_FIELD_PATTERN = re.compile(r"^[ABD]\d{9}$")

# CSMAR 股票代码模式 (6位数字)
STOCK_CODE_PATTERN = re.compile(r"^\d{6}$")

# CSMAR ZIP 元数据文件标记
CSMAR_DES_MARKER = "[DES]"


@dataclass
class DataFileInfo:
    """数据文件信息."""

    file_path: Path
    file_format: str = ""  # csv / excel / txt / zip
    data_source: str = ""  # csmar / resset / unknown
    encoding: str = "utf-8"
    has_metadata: bool = False  # CSMAR TXT 元数据
    metadata_path: Optional[Path] = None
    row_count: int = 0
    column_count: int = 0
    columns: list[str] = field(default_factory=list)


@dataclass
class ProcessedDataset:
    """处理后的数据集."""

    file_path: str = ""
    data_source: str = ""  # csmar / resset / unknown
    dataframe: Optional[pd.DataFrame] = None
    column_labels: dict[str, str] = field(default_factory=dict)  # 列名→中文标签
    stats: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "data_source": self.data_source,
            "column_labels": self.column_labels,
            "stats": self.stats,
            "error": self.error,
            "row_count": len(self.dataframe) if self.dataframe is not None else 0,
            "column_count": len(self.dataframe.columns) if self.dataframe is not None else 0,
        }


@dataclass
class ProcessingResult:
    """数据处理结果."""

    files_processed: list[ProcessedDataset] = field(default_factory=list)
    total_rows: int = 0
    total_files: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_files": self.total_files,
            "total_rows": self.total_rows,
            "files": [d.to_dict() for d in self.files_processed],
            "errors": self.errors,
        }


class FinancialDataProcessor:
    """金融数据处理引擎.

    自动检测、解析和统计 CSMAR/RESSET 导出的数据文件。

    Usage:
        processor = FinancialDataProcessor()
        result = processor.process_directory("./data")
        stats = processor.generate_comprehensive_stats(result)
        processor.save_stats_to_json(stats, "./.scholar/descriptive_stats.json")
    """

    def __init__(self) -> None:
        """初始化金融数据处理引擎."""
        self._csmar_column_map = CSMAR_COLUMN_MAP.copy()

    # ===== 文件检测 =====

    def detect_file_format(self, file_path: Path) -> str:
        """检测文件格式.

        Args:
            file_path: 文件路径.

        Returns:
            格式字符串: csv / excel / txt / zip / unknown.
        """
        suffix = file_path.suffix.lower()

        if suffix == ".csv":
            return "csv"
        elif suffix in (".xls", ".xlsx"):
            return "excel"
        elif suffix == ".txt":
            return "txt"
        elif suffix == ".zip":
            return "zip"
        elif suffix == ".dta":
            return "stata"
        elif suffix == ".sav":
            return "spss"
        elif suffix == ".sas7bdat":
            return "sas"
        else:
            return "unknown"

    def detect_data_source(
        self,
        file_path: Path,
        columns: list[str] | None = None,
        zip_contents: list[str] | None = None,
    ) -> str:
        """检测数据来源（CSMAR / RESSET / 通用）.

        基于文件名模式、列名特征和 ZIP 内容判断。

        Args:
            file_path: 文件路径.
            columns: 已读取的列名列表（可选）.
            zip_contents: ZIP 内文件列表（可选）.

        Returns:
            数据源: csmar / resset / unknown.
        """
        filename = file_path.name.lower()

        # CSMAR ZIP 元数据检测
        if zip_contents:
            for name in zip_contents:
                if CSMAR_DES_MARKER in name or name.endswith("[csv].txt"):
                    return "csmar"

        # CSMAR 列名特征检测
        if columns:
            csmar_indicators = 0
            for col in columns:
                col_clean = col.strip()
                # 检查 CSMAR 标准列名
                if col_clean in self._csmar_column_map:
                    csmar_indicators += 1
                # 检查财务字段编码模式
                if CSMAR_FINANCIAL_FIELD_PATTERN.match(col_clean):
                    csmar_indicators += 1

            if csmar_indicators >= 2:
                return "csmar"

        # RESSET 高频文件名检测
        if re.match(r"^\w+hf\d{4}_\d{6}(sz|sh|si)", filename):
            return "resset"

        # RESSET 文件名特征（含中文或特定前缀）
        resset_prefixes = ["resset", "rs_"]
        for prefix in resset_prefixes:
            if prefix in filename:
                return "resset"

        return "unknown"

    def find_metadata_file(self, csv_path: Path) -> Optional[Path]:
        """查找 CSMAR 配套的元数据 TXT 文件.

        CSMAR 导出通常为 xxx.csv + xxx[DES][csv].txt

        Args:
            csv_path: CSV 文件路径.

        Returns:
            元数据文件路径，如不存在返回 None.
        """
        stem = csv_path.stem
        parent = csv_path.parent

        # CSMAR 元数据文件命名模式
        patterns = [
            f"{stem}[DES][csv].txt",
            f"{stem}[DES].txt",
            f"{stem}_DES.txt",
            f"{stem}.txt",  # 简单同名 TXT
        ]

        for pattern in patterns:
            meta_path = parent / pattern
            if meta_path.exists():
                return meta_path

        return None

    def parse_csmar_metadata(self, meta_path: Path) -> dict[str, str]:
        """解析 CSMAR 元数据 TXT 文件.

        格式: [字段名] 中文描述

        Args:
            meta_path: 元数据文件路径.

        Returns:
            {字段名: 中文标签} 字典.
        """
        labels: dict[str, str] = {}

        try:
            # CSMAR TXT 可能有多种编码
            for encoding in ["utf-8", "gbk", "gb2312", "latin-1"]:
                try:
                    with open(meta_path, "r", encoding=encoding) as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue

                            # 匹配 [字段名] 中文描述
                            match = re.match(r"\[(\w+)\]\s*(.+)", line)
                            if match:
                                field_name = match.group(1)
                                label = match.group(2).strip()
                                labels[field_name] = label

                    if labels:
                        break

                except UnicodeDecodeError:
                    continue

        except Exception as e:
            logger.warning(f"Failed to parse CSMAR metadata {meta_path}: {e}")

        return labels

    # ===== 数据加载 =====

    def load_csv(
        self,
        file_path: Path,
        encoding: str = "",
    ) -> tuple[pd.DataFrame, str]:
        """加载 CSV 文件，自动检测编码.

        Args:
            file_path: CSV 文件路径.
            encoding: 指定编码（空则自动检测）.

        Returns:
            (DataFrame, 实际使用的编码).
        """
        encodings = [encoding] if encoding else ["utf-8", "gbk", "gb2312", "latin-1"]

        for enc in encodings:
            try:
                df = pd.read_csv(file_path, encoding=enc, low_memory=False)
                logger.debug(f"Loaded CSV {file_path.name} with encoding={enc}")
                return df, enc
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.warning(f"Failed to load CSV with {enc}: {e}")
                continue

        # 最后尝试无编码指定
        try:
            df = pd.read_csv(file_path, low_memory=False)
            return df, "auto"
        except Exception as e:
            raise ValueError(f"Failed to load CSV {file_path}: {e}")

    def load_excel(self, file_path: Path) -> pd.DataFrame:
        """加载 Excel 文件."""
        try:
            return pd.read_excel(file_path)
        except Exception as e:
            raise ValueError(f"Failed to load Excel {file_path}: {e}")

    def load_zip(self, file_path: Path) -> list[tuple[str, pd.DataFrame, dict[str, str]]]:
        """加载 ZIP 压缩包（CSMAR 格式）.

        CSMAR ZIP 内含 CSV 数据文件 + TXT 元数据文件。

        Args:
            file_path: ZIP 文件路径.

        Returns:
            [(文件名, DataFrame, 列标签字典)] 列表.
        """
        results: list[tuple[str, pd.DataFrame, dict[str, str]]] = []

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                names = zf.namelist()

                # 查找 CSV 文件
                csv_names = [n for n in names if n.lower().endswith(".csv")]
                # 查找 TXT 元数据文件
                txt_names = [n for n in names if n.lower().endswith(".txt")]

                for csv_name in csv_names:
                    # 读取 CSV
                    try:
                        with zf.open(csv_name) as f:
                            df = pd.read_csv(f, low_memory=False)
                    except Exception as e:
                        logger.warning(f"Failed to read {csv_name} in ZIP: {e}")
                        continue

                    # 查找配套的元数据 TXT
                    labels: dict[str, str] = {}
                    csv_stem = Path(csv_name).stem

                    for txt_name in txt_names:
                        if csv_stem in txt_name or CSMAR_DES_MARKER in txt_name:
                            try:
                                with zf.open(txt_name) as f:
                                    content = f.read().decode("utf-8", errors="ignore")
                                    for line in content.split("\n"):
                                        match = re.match(r"\[(\w+)\]\s*(.+)", line.strip())
                                        if match:
                                            labels[match.group(1)] = match.group(2).strip()
                            except Exception:
                                pass
                            break

                    results.append((csv_name, df, labels))

        except Exception as e:
            raise ValueError(f"Failed to open ZIP {file_path}: {e}")

        return results

    # ===== 列名规范化 =====

    def normalize_columns(
        self,
        df: pd.DataFrame,
        data_source: str,
        labels: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        """规范化列名.

        - CSMAR: 英文缩写 → 标准化名称
        - 股票代码: 补零至 6 位
        - 日期: 统一为 datetime

        Args:
            df: 原始 DataFrame.
            data_source: 数据来源.
            labels: CSMAR 元数据标签.

        Returns:
            规范化后的 DataFrame.
        """
        df = df.copy()

        # CSMAR 列名映射
        if data_source == "csmar":
            rename_map = {}
            for col in df.columns:
                col_clean = col.strip()
                if col_clean in self._csmar_column_map:
                    rename_map[col] = self._csmar_column_map[col_clean]
            if rename_map:
                df = df.rename(columns=rename_map)

        # 股票代码规范化（补零至6位）
        code_cols = [c for c in df.columns if "code" in c.lower() or "stkcd" in c.lower()]
        for col in code_cols:
            # 先转为字符串，去除小数点（如 1.0 → "1"），再补零
            df[col] = df[col].astype(str).str.replace(r"\.0$", "", regex=True)
            df[col] = df[col].str.replace(r"\D", "", regex=True)
            df[col] = df[col].apply(lambda x: x.zfill(6) if x and len(x) < 6 else x)

        # 日期列规范化
        date_cols = [c for c in df.columns if any(
            kw in c.lower() for kw in ["date", "period", "trading", "accper"]
        )]
        for col in date_cols:
            try:
                df[col] = pd.to_datetime(df[col], errors="coerce")
            except Exception:
                pass

        # 年份列
        year_cols = [c for c in df.columns if c.lower() == "year"]
        for col in year_cols:
            try:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
            except Exception:
                pass

        return df

    # ===== 统计生成 =====

    def generate_stats(self, df: pd.DataFrame, data_source: str = "") -> dict[str, Any]:
        """生成描述性统计.

        Args:
            df: 数据 DataFrame.
            data_source: 数据来源.

        Returns:
            统计字典，兼容 save_stats_to_json() 格式.
        """
        stats: dict[str, Any] = {
            "data_source": data_source,
            "total_observations": len(df),
            "total_variables": len(df.columns),
            "variables": {},
        }

        for col in df.columns:
            col_stats: dict[str, Any] = {}

            # 数值型统计
            if df[col].dtype in ["int64", "float64", "Int64"]:
                col_stats = {
                    "type": "numeric",
                    "count": int(df[col].count()),
                    "mean": float(df[col].mean()) if df[col].count() > 0 else None,
                    "std": float(df[col].std()) if df[col].count() > 0 else None,
                    "min": float(df[col].min()) if df[col].count() > 0 else None,
                    "q25": float(df[col].quantile(0.25)) if df[col].count() > 0 else None,
                    "median": float(df[col].median()) if df[col].count() > 0 else None,
                    "q75": float(df[col].quantile(0.75)) if df[col].count() > 0 else None,
                    "max": float(df[col].max()) if df[col].count() > 0 else None,
                    "missing": int(df[col].isna().sum()),
                }
            else:
                # 分类/文本型统计
                value_counts = df[col].value_counts()
                # 将 key 转为字符串，避免 Timestamp 等不可序列化类型
                top_values = {}
                for key, val in value_counts.head(5).items():
                    top_values[str(key)] = int(val)
                col_stats = {
                    "type": "categorical",
                    "count": int(df[col].count()),
                    "unique": int(df[col].nunique()),
                    "missing": int(df[col].isna().sum()),
                    "top_values": top_values,
                }

            stats["variables"][col] = col_stats

        return stats

    def generate_comprehensive_stats(self, result: ProcessingResult) -> dict[str, Any]:
        """生成综合统计报告.

        汇总所有已处理文件的统计信息。

        Args:
            result: 数据处理结果.

        Returns:
            综合统计字典.
        """
        comprehensive: dict[str, Any] = {
            "summary": {
                "total_files": result.total_files,
                "total_observations": result.total_rows,
                "data_sources": list(set(
                    d.data_source for d in result.files_processed if d.data_source
                )),
                "processing_errors": len(result.errors),
            },
            "datasets": [],
        }

        for dataset in result.files_processed:
            if dataset.stats:
                comprehensive["datasets"].append({
                    "file": dataset.file_path,
                    "source": dataset.data_source,
                    "stats": dataset.stats,
                    "column_labels": dataset.column_labels,
                })

        return comprehensive

    # ===== 保存统计 =====

    def save_stats_to_json(
        self,
        stats: dict[str, Any],
        output_path: str | Path,
    ) -> None:
        """保存统计到 JSON 文件.

        兼容 ScholarPilot 实证章节注入工作流:
        .scholar/descriptive_stats.json → format_stats_for_prompt() → 实证章节

        Args:
            stats: 统计字典.
            output_path: 输出文件路径.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"Stats saved to {output_path}")

    # ===== 目录处理 =====

    def process_directory(self, dir_path: str | Path) -> ProcessingResult:
        """处理目录中的所有数据文件.

        自动检测 CSV/Excel/TXT/ZIP 文件，解析并生成统计。

        Args:
            dir_path: 数据目录路径.

        Returns:
            ProcessingResult: 处理结果.
        """
        dir_path = Path(dir_path)
        result = ProcessingResult()

        if not dir_path.exists():
            result.errors.append(f"Directory not found: {dir_path}")
            return result

        # 支持的文件扩展名
        supported_extensions = {".csv", ".xls", ".xlsx", ".txt", ".zip", ".dta"}

        for file_path in sorted(dir_path.iterdir()):
            if not file_path.is_file():
                continue

            fmt = self.detect_file_format(file_path)
            if fmt == "unknown" or file_path.suffix.lower() not in supported_extensions:
                continue

            try:
                dataset = self.process_file(file_path)
                result.files_processed.append(dataset)
                if dataset.dataframe is not None:
                    result.total_rows += len(dataset.dataframe)
            except Exception as e:
                error_msg = f"{file_path.name}: {e}"
                result.errors.append(error_msg)
                logger.error(f"Error processing {file_path}: {e}")

        result.total_files = len(result.files_processed)
        logger.info(
            f"Processed {result.total_files} files, "
            f"{result.total_rows} total rows, "
            f"{len(result.errors)} errors"
        )

        return result

    def process_file(self, file_path: Path) -> ProcessedDataset:
        """处理单个数据文件.

        Args:
            file_path: 文件路径.

        Returns:
            ProcessedDataset: 处理后的数据集.
        """
        dataset = ProcessedDataset(file_path=str(file_path))
        fmt = self.detect_file_format(file_path)

        try:
            if fmt == "csv":
                df, encoding = self.load_csv(file_path)
                data_source = self.detect_data_source(file_path, list(df.columns))

                # 查找 CSMAR 元数据
                meta_path = self.find_metadata_file(file_path)
                labels = {}
                if meta_path:
                    labels = self.parse_csmar_metadata(meta_path)
                    if labels:
                        data_source = "csmar"

                df = self.normalize_columns(df, data_source, labels)
                dataset.dataframe = df
                dataset.data_source = data_source
                dataset.column_labels = labels
                dataset.stats = self.generate_stats(df, data_source)

            elif fmt == "excel":
                df = self.load_excel(file_path)
                data_source = self.detect_data_source(file_path, list(df.columns))
                df = self.normalize_columns(df, data_source)
                dataset.dataframe = df
                dataset.data_source = data_source
                dataset.stats = self.generate_stats(df, data_source)

            elif fmt == "zip":
                # CSMAR ZIP: CSV + TXT 元数据
                zip_results = self.load_zip(file_path)
                if zip_results:
                    # 合并所有 CSV（通常只有一个）
                    all_dfs = []
                    all_labels = {}
                    for name, df, labels in zip_results:
                        data_source = self.detect_data_source(
                            file_path, list(df.columns), zip_contents=[name]
                        )
                        if labels:
                            data_source = "csmar"
                            all_labels.update(labels)
                        df = self.normalize_columns(df, data_source, labels)
                        all_dfs.append(df)

                    if all_dfs:
                        combined = pd.concat(all_dfs, ignore_index=True)
                        dataset.dataframe = combined
                        dataset.data_source = "csmar" if all_labels else "unknown"
                        dataset.column_labels = all_labels
                        dataset.stats = self.generate_stats(combined, dataset.data_source)

            elif fmt == "txt":
                # 尝试 CSV 格式读取 TXT
                try:
                    df, encoding = self.load_csv(file_path)
                    data_source = self.detect_data_source(file_path, list(df.columns))
                    df = self.normalize_columns(df, data_source)
                    dataset.dataframe = df
                    dataset.data_source = data_source
                    dataset.stats = self.generate_stats(df, data_source)
                except Exception:
                    # 尝试 Tab 分隔
                    try:
                        df = pd.read_csv(file_path, sep="\t", low_memory=False)
                        data_source = self.detect_data_source(file_path, list(df.columns))
                        df = self.normalize_columns(df, data_source)
                        dataset.dataframe = df
                        dataset.data_source = data_source
                        dataset.stats = self.generate_stats(df, data_source)
                    except Exception as e:
                        dataset.error = f"Failed to parse TXT: {e}"

            elif fmt == "stata":
                try:
                    df = pd.read_stata(file_path)
                    data_source = self.detect_data_source(file_path, list(df.columns))
                    df = self.normalize_columns(df, data_source)
                    dataset.dataframe = df
                    dataset.data_source = data_source
                    dataset.stats = self.generate_stats(df, data_source)
                except Exception as e:
                    dataset.error = f"Failed to load Stata file: {e}"

        except Exception as e:
            dataset.error = str(e)
            logger.error(f"Error processing {file_path}: {e}")

        return dataset

    # ===== 格式化统计用于 Prompt =====

    @staticmethod
    def format_stats_for_prompt(stats: dict[str, Any]) -> str:
        """将统计格式化为 LLM Prompt 文本.

        用于将描述性统计注入实证章节的 LLM 生成。

        Args:
            stats: 统计字典.

        Returns:
            格式化的统计文本.
        """
        lines = []

        summary = stats.get("summary", {})
        lines.append(f"数据概览: {summary.get('total_files', 0)} 个文件, "
                      f"{summary.get('total_observations', 0)} 条观测值, "
                      f"数据来源: {', '.join(summary.get('data_sources', ['未知']))}")

        for dataset in stats.get("datasets", []):
            lines.append(f"\n--- {dataset.get('file', '未知文件')} ---")
            lines.append(f"数据来源: {dataset.get('source', '未知')}")

            ds_stats = dataset.get("stats", {})
            lines.append(f"观测值: {ds_stats.get('total_observations', 0)}")
            lines.append(f"变量数: {ds_stats.get('total_variables', 0)}")

            # 输出数值型变量的关键统计
            lines.append("\n描述性统计:")
            lines.append(f"{'变量':<30} {'均值':>12} {'标准差':>12} {'最小值':>12} {'中位数':>12} {'最大值':>12}")
            lines.append("-" * 90)

            for var_name, var_stats in ds_stats.get("variables", {}).items():
                if var_stats.get("type") == "numeric":
                    label = dataset.get("column_labels", {}).get(var_name, var_name)
                    name_display = f"{var_name}({label})" if label != var_name else var_name
                    if len(name_display) > 28:
                        name_display = name_display[:28]

                    lines.append(
                        f"{name_display:<30} "
                        f"{var_stats.get('mean', 0) or 0:>12.4f} "
                        f"{var_stats.get('std', 0) or 0:>12.4f} "
                        f"{var_stats.get('min', 0) or 0:>12.4f} "
                        f"{var_stats.get('median', 0) or 0:>12.4f} "
                        f"{var_stats.get('max', 0) or 0:>12.4f}"
                    )

        return "\n".join(lines)
