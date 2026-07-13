"""可复现研究包模块（Reproducibility Packager）.

将一个 ScholarPilot 项目目录打包成可复现的 zip 包，包含：
    1. data/ + code/ + paper/ 项目内容
    2. requirements.txt（使用 pip freeze 锁定版本）
    3. Makefile（支持 ``make data`` / ``make analysis`` / ``make paper``）
    4. README.md（项目说明、数据来源、运行步骤、依赖列表）
    5. manifest.json（溯源追踪：输入/输出文件 SHA256 + 运行参数 + 依赖版本）

设计原则：
    - 与 stats_engine / result_parser 风格保持一致
    - 延迟导入重型依赖（如 pip / importlib.metadata 仅在需要时调用）
    - 不修改用户原始项目，所有生成物写入打包目录或 zip
    - 失败降级：pip freeze 不可用时回退到 importlib.metadata

使用示例::

    from scholarpilot.tools.reproducibility import (
        ProvenanceTracker,
        ReproducibilityPackager,
    )

    tracker = ProvenanceTracker()
    tracker.track_input("data/raw.csv")
    tracker.record_params({"model": "fe", "year_start": 2010})
    tracker.track_output("analysis/result.md")
    manifest = tracker.generate_manifest()

    packager = ReproducibilityPackager()
    zip_path = packager.package("projects/debt_paper", "debt_paper_repro.zip")
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["ProvenanceTracker", "ReproducibilityPackager"]

# 打包时默认纳入的项目子目录
_DEFAULT_INCLUDE_DIRS: tuple[str, ...] = ("data", "code", "paper")

# 默认追踪的 Python 依赖包名（用于 manifest 的 dependencies 字段）
_DEFAULT_TRACKED_DEPS: tuple[str, ...] = (
    "numpy",
    "pandas",
    "scipy",
    "statsmodels",
    "linearmodels",
    "matplotlib",
    "seaborn",
    "scholarpilot",
)


def _compute_sha256(file_path: Path, chunk_size: int = 8192) -> str:
    """计算文件的 SHA256 哈希值.

    Args:
        file_path: 文件路径。
        chunk_size: 分块读取大小（字节），默认 8192。

    Returns:
        小写十六进制 SHA256 字符串。

    Raises:
        FileNotFoundError: 文件不存在。
        IsADirectoryError: 路径是目录而非文件。
    """
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")
    if file_path.is_dir():
        raise IsADirectoryError(f"路径是目录而非文件: {file_path}")

    h = hashlib.sha256()
    with file_path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _get_scholarpilot_version() -> str:
    """获取 ScholarPilot 版本号.

    优先从 ``scholarpilot.__version__`` 读取，
    失败时回退到 ``importlib.metadata``，再失败返回 ``"unknown"``。
    """
    try:
        from scholarpilot import __version__  # 延迟导入避免循环依赖

        return __version__
    except Exception:  # pragma: no cover - 极端情况
        pass
    try:
        from importlib.metadata import version

        return version("scholarpilot")
    except Exception:  # pragma: no cover - 未安装时
        return "unknown"


def _get_dependency_versions() -> dict[str, str]:
    """获取已安装的关键依赖版本.

    使用 ``importlib.metadata`` 查询，缺失的包会被跳过。

    Returns:
        依赖名 -> 版本号 字典，如 ``{"numpy": "1.26.0", "pandas": "2.1.0"}``。
    """
    from importlib.metadata import PackageNotFoundError, version

    deps: dict[str, str] = {}
    for pkg in _DEFAULT_TRACKED_DEPS:
        try:
            deps[pkg] = version(pkg)
        except PackageNotFoundError:
            logger.debug("依赖未安装，跳过: %s", pkg)
        except Exception:  # pragma: no cover - 防御性
            logger.debug("查询依赖版本失败: %s", pkg)
    return deps


class ProvenanceTracker:
    """溯源追踪器——记录输入/输出文件指纹与运行参数.

    负责收集一次研究运行过程中的输入文件、输出文件、运行参数，
    最终生成 ``manifest.json`` 字典，用于可复现性验证。

    使用示例::

        tracker = ProvenanceTracker()
        tracker.track_input("data/raw.csv")
        tracker.record_params({"model": "fe", "cluster": "province"})
        tracker.track_output("analysis/result.md")
        manifest = tracker.generate_manifest()
    """

    def __init__(self) -> None:
        """初始化溯源追踪器."""
        self._inputs: list[dict[str, Any]] = []
        self._outputs: list[dict[str, Any]] = []
        self._params: dict[str, Any] = {}
        self._created_at: str = datetime.now(timezone.utc).isoformat()
        logger.debug("ProvenanceTracker 已初始化")

    def _track_file(
        self, file_path: str | Path, *, kind: str
    ) -> dict[str, Any]:
        """追踪单个文件的元信息（内部方法）.

        Args:
            file_path: 文件路径。
            kind: ``"input"`` 或 ``"output"``。

        Returns:
            文件元信息字典，包含 path / sha256 / size / modified。

        Raises:
            FileNotFoundError: 文件不存在。
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        sha = _compute_sha256(path)
        stat = path.stat()
        record: dict[str, Any] = {
            "path": str(path),
            "sha256": sha,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        }
        logger.debug("追踪 %s 文件: %s (sha256=%s...)", kind, path, sha[:8])
        return record

    def track_input(self, file_path: str | Path) -> dict[str, Any]:
        """记录一个输入文件.

        计算文件 SHA256，记录文件名、大小、修改时间。

        Args:
            file_path: 输入文件路径。

        Returns:
            输入文件元信息字典。

        Raises:
            FileNotFoundError: 文件不存在。
        """
        record = self._track_file(file_path, kind="input")
        self._inputs.append(record)
        return record

    def track_output(self, file_path: str | Path) -> dict[str, Any]:
        """记录一个输出文件.

        计算文件 SHA256，记录文件名、大小、修改时间。

        Args:
            file_path: 输出文件路径。

        Returns:
            输出文件元信息字典。

        Raises:
            FileNotFoundError: 文件不存在。
        """
        record = self._track_file(file_path, kind="output")
        self._outputs.append(record)
        return record

    def record_params(self, params: dict[str, Any]) -> None:
        """记录运行参数.

        多次调用会合并参数（后者覆盖前者同名键）。

        Args:
            params: 运行参数字典，如 ``{"model": "fe", "year_start": 2010}``。
        """
        if not isinstance(params, dict):
            raise TypeError(f"params 必须是 dict，收到 {type(params).__name__}")
        self._params.update(params)
        logger.debug("记录参数: %s", params)

    def generate_manifest(self) -> dict[str, Any]:
        """生成 manifest.json 字典.

        Returns:
            manifest 字典，结构为::

                {
                    "created_at": "2026-07-13T...",
                    "scholarpilot_version": "0.1.0",
                    "inputs": [{"path": "...", "sha256": "...", "size": N}, ...],
                    "outputs": [{"path": "...", "sha256": "...", "size": N}, ...],
                    "parameters": {...},
                    "python_version": "3.13.x",
                    "dependencies": {"numpy": "1.x.x", ...}
                }
        """
        manifest: dict[str, Any] = {
            "created_at": self._created_at,
            "scholarpilot_version": _get_scholarpilot_version(),
            "inputs": list(self._inputs),
            "outputs": list(self._outputs),
            "parameters": dict(self._params),
            "python_version": platform.python_version(),
            "dependencies": _get_dependency_versions(),
        }
        logger.info(
            "manifest 已生成: %d 个输入, %d 个输出",
            len(manifest["inputs"]),
            len(manifest["outputs"]),
        )
        return manifest

    def to_json(self, indent: int = 2) -> str:
        """将 manifest 序列化为 JSON 字符串.

        Args:
            indent: JSON 缩进空格数，默认 2。

        Returns:
            JSON 字符串。
        """
        return json.dumps(self.generate_manifest(), indent=indent, ensure_ascii=False)

    def save_manifest(self, output_path: str | Path, indent: int = 2) -> Path:
        """将 manifest 保存为 JSON 文件.

        Args:
            output_path: 输出文件路径。
            indent: JSON 缩进空格数，默认 2。

        Returns:
            保存的文件路径。
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(indent=indent), encoding="utf-8")
        logger.info("manifest 已保存: %s", path)
        return path


class ReproducibilityPackager:
    """可复现研究包打包器.

    将项目目录打包成 zip，包含 data/ + code/ + paper/ 以及
    requirements.txt、Makefile、README.md、manifest.json。

    使用示例::

        packager = ReproducibilityPackager()
        zip_path = packager.package(
            project_dir="projects/debt_paper",
            output_path="debt_paper_repro.zip",
            include_data=True,
        )
    """

    def __init__(
        self,
        include_dirs: tuple[str, ...] | None = None,
    ) -> None:
        """初始化打包器.

        Args:
            include_dirs: 要纳入的项目子目录名，默认 ``("data", "code", "paper")``。
        """
        self.include_dirs: tuple[str, ...] = (
            include_dirs if include_dirs is not None else _DEFAULT_INCLUDE_DIRS
        )
        logger.debug("ReproducibilityPackager 初始化, include_dirs=%s", self.include_dirs)

    # ---------- 生成物构建 ----------

    def generate_requirements(self, output_path: str | Path) -> Path:
        """生成 requirements.txt（使用 pip freeze 锁定版本）.

        优先使用 ``pip freeze``；失败时回退到 ``importlib.metadata``
        遍历已安装包。

        Args:
            output_path: 输出文件路径。

        Returns:
            生成的 requirements.txt 路径。
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = self._collect_pip_freeze()
        if not lines:
            logger.warning("pip freeze 无输出，回退到 importlib.metadata")
            lines = self._collect_installed_distributions()

        # 在文件头部加注释
        header = [
            "# Auto-generated by ScholarPilot ReproducibilityPackager",
            f"# Generated at: {datetime.now(timezone.utc).isoformat()}",
            f"# Python: {platform.python_version()}",
            "",
        ]
        content = "\n".join(header + lines) + "\n"
        path.write_text(content, encoding="utf-8")
        logger.info("requirements.txt 已生成: %s (%d 行)", path, len(lines))
        return path

    def _collect_pip_freeze(self) -> list[str]:
        """调用 pip freeze 收集依赖（内部方法）.

        Returns:
            依赖行列表。失败时返回空列表。
        """
        try:
            # 延迟导入，避免在纯模块加载时触发
            import subprocess

            result = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if result.returncode == 0:
                lines = [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip() and not line.startswith("#")
                ]
                return lines
            logger.warning("pip freeze 返回码 %d: %s", result.returncode, result.stderr)
        except FileNotFoundError:
            logger.warning("pip 不可用，跳过 pip freeze")
        except Exception as e:  # pragma: no cover - 防御性
            logger.warning("pip freeze 失败: %s", e)
        return []

    def _collect_installed_distributions(self) -> list[str]:
        """使用 importlib.metadata 收集已安装包（回退方案）.

        Returns:
            ``name==version`` 格式的依赖行列表。
        """
        from importlib.metadata import distributions

        lines: list[str] = []
        try:
            for dist in distributions():
                name = dist.metadata.get("Name", "")
                version = dist.version
                if name and version:
                    lines.append(f"{name}=={version}")
        except Exception as e:  # pragma: no cover - 防御性
            logger.warning("importlib.metadata 遍历失败: %s", e)
        return sorted(lines)

    def generate_makefile(self, output_path: str | Path) -> Path:
        """生成 Makefile（支持 make data / make analysis / make paper）.

        Args:
            output_path: 输出文件路径。

        Returns:
            生成的 Makefile 路径。
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        content = self._render_makefile()
        path.write_text(content, encoding="utf-8")
        logger.info("Makefile 已生成: %s", path)
        return path

    def _render_makefile(self) -> str:
        """渲染 Makefile 内容（内部方法）.

        Returns:
            Makefile 文本内容。
        """
        return (
            "# Auto-generated by ScholarPilot ReproducibilityPackager\n"
            "# 可复现研究包 Makefile\n"
            ".PHONY: all data analysis paper clean install\n"
            "\n"
            "PYTHON ?= python\n"
            "PIP ?= pip\n"
            "\n"
            "all: data analysis paper\n"
            "\n"
            "# ── 环境安装 ──────────────────────────────────────\n"
            "install:\n"
            "\t$(PIP) install -r requirements.txt\n"
            "\n"
            "# ── 数据准备 ──────────────────────────────────────\n"
            "data:\n"
            "\t@echo \"[data] 准备数据...\"\n"
            "\t$(PYTHON) code/01_data.py\n"
            "\n"
            "# ── 统计分析 ──────────────────────────────────────\n"
            "analysis:\n"
            "\t@echo \"[analysis] 运行分析...\"\n"
            "\t$(PYTHON) code/02_analysis.py\n"
            "\n"
            "# ── 论文编译 ──────────────────────────────────────\n"
            "paper:\n"
            "\t@echo \"[paper] 生成论文...\"\n"
            "\t$(PYTHON) code/03_paper.py\n"
            "\n"
            "# ── 清理 ──────────────────────────────────────────\n"
            "clean:\n"
            "\tfind . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true\n"
            "\trm -rf analysis/output/*.log analysis/output/*.tmp 2>/dev/null || true\n"
        )

    def generate_readme(
        self,
        output_path: str | Path,
        project_name: str = "research_project",
        description: str = "",
        data_source: str = "",
    ) -> Path:
        """生成 README.md（项目说明、数据来源、运行步骤、依赖列表）.

        Args:
            output_path: 输出文件路径。
            project_name: 项目名称。
            description: 项目描述（可为空）。
            data_source: 数据来源说明（可为空）。

        Returns:
            生成的 README.md 路径。
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        deps = _get_dependency_versions()
        deps_lines = "\n".join(
            f"- {name}: {ver}" for name, ver in deps.items()
        ) or "- （未检测到关键依赖）"

        description_text = description.strip() or "（请在打包后补充项目描述）"
        data_source_text = data_source.strip() or "（请在打包后补充数据来源说明）"

        content = f"""# {project_name}

> 本可复现研究包由 ScholarPilot 自动生成。

## 项目说明

{description_text}

## 数据来源

{data_source_text}

## 运行步骤

### 1. 创建虚拟环境（推荐）

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows
.venv\\Scripts\\activate
```

### 2. 安装依赖

```bash
make install
# 或
pip install -r requirements.txt
```

### 3. 一键复现

```bash
make all
```

也可分步运行：

```bash
make data       # 数据准备
make analysis   # 统计分析
make paper      # 论文生成
```

## 依赖列表

{deps_lines}

完整依赖版本见 `requirements.txt`。

## 溯源信息

- Python 版本: {platform.python_version()}
- ScholarPilot 版本: {_get_scholarpilot_version()}
- 打包时间: {datetime.now(timezone.utc).isoformat()}

详细的输入/输出文件指纹与运行参数见 `manifest.json`。

## 目录结构

```
{project_name}/
├── data/            # 原始与处理后数据
├── code/            # 分析脚本
├── paper/           # 论文手稿
├── requirements.txt # 依赖锁定
├── Makefile         # 复现入口
├── manifest.json    # 溯源清单
└── README.md        # 本文件
```
"""
        path.write_text(content, encoding="utf-8")
        logger.info("README.md 已生成: %s", path)
        return path

    # ---------- 打包主流程 ----------

    def package(
        self,
        project_dir: str | Path,
        output_path: str | Path,
        include_data: bool = True,
        project_name: str | None = None,
        description: str = "",
        data_source: str = "",
        params: dict[str, Any] | None = None,
    ) -> Path:
        """打包项目为可复现 zip 包.

        流程：
            1. 在临时目录中组装打包内容
            2. 复制 data/ + code/ + paper/ 子目录
            3. 生成 requirements.txt / Makefile / README.md
            4. 收集输入/输出文件指纹，生成 manifest.json
            5. 压缩为 zip

        Args:
            project_dir: 项目根目录路径。
            output_path: 输出 zip 文件路径。
            include_data: 是否包含 data/ 目录，默认 True。
            project_name: 项目名称（用于 README），默认取目录名。
            description: 项目描述。
            data_source: 数据来源说明。
            params: 额外运行参数，写入 manifest。

        Returns:
            生成的 zip 文件路径。

        Raises:
            FileNotFoundError: 项目目录不存在。
        """
        src = Path(project_dir)
        if not src.exists():
            raise FileNotFoundError(f"项目目录不存在: {src}")
        if not src.is_dir():
            raise NotADirectoryError(f"路径不是目录: {src}")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        name = project_name or src.name
        logger.info("开始打包项目: %s -> %s (include_data=%s)", src, out, include_data)

        # 决定实际纳入的目录
        include_dirs = list(self.include_dirs)
        if not include_data and "data" in include_dirs:
            include_dirs = [d for d in include_dirs if d != "data"]

        tracker = ProvenanceTracker()
        if params:
            tracker.record_params(params)

        # 直接写入 zip，避免临时目录
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. 复制项目子目录
            for sub in include_dirs:
                sub_path = src / sub
                if not sub_path.exists():
                    logger.debug("子目录不存在，跳过: %s", sub_path)
                    continue
                self._add_directory_to_zip(zf, sub_path, src, tracker, sub)

            # 2. 在内存中生成 requirements.txt / Makefile / README.md / manifest.json
            import io

            # requirements.txt
            req_buf = io.StringIO()
            req_buf.write("# Auto-generated by ScholarPilot ReproducibilityPackager\n")
            req_buf.write(
                f"# Generated at: {datetime.now(timezone.utc).isoformat()}\n"
            )
            req_buf.write(f"# Python: {platform.python_version()}\n\n")
            req_lines = self._collect_pip_freeze()
            if not req_lines:
                req_lines = self._collect_installed_distributions()
            req_buf.write("\n".join(req_lines))
            req_buf.write("\n")
            zf.writestr("requirements.txt", req_buf.getvalue())

            # Makefile
            zf.writestr("Makefile", self._render_makefile())

            # README.md
            readme_content = self._render_readme(
                project_name=name,
                description=description,
                data_source=data_source,
            )
            zf.writestr("README.md", readme_content)

            # manifest.json —— 汇总输入/输出指纹与运行参数
            manifest = tracker.generate_manifest()
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, ensure_ascii=False),
            )

        logger.info("打包完成: %s (大小: %d bytes)", out, out.stat().st_size)
        return out

    def _add_directory_to_zip(
        self,
        zf: zipfile.ZipFile,
        dir_path: Path,
        project_root: Path,
        tracker: ProvenanceTracker,
        kind: str,
    ) -> None:
        """将目录递归加入 zip，并追踪文件指纹（内部方法）.

        Args:
            zf: ZipFile 实例。
            dir_path: 要加入的目录路径。
            project_root: 项目根目录（用于计算相对路径作为 zip 内路径）。
            tracker: 溯源追踪器。
            kind: 目录类别（data / code / paper），决定记为 input 还是 output。
        """
        for file_path in sorted(dir_path.rglob("*")):
            if file_path.is_dir():
                continue
            if self._is_ignored(file_path):
                continue
            arcname = file_path.relative_to(project_root).as_posix()
            zf.write(file_path, arcname)

            # 追踪文件指纹：data/code 视为输入，paper 视为输出
            try:
                stat = file_path.stat()
                record: dict[str, Any] = {
                    "path": arcname,
                    "sha256": _compute_sha256(file_path),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
                if kind == "paper":
                    tracker._outputs.append(record)  # noqa: SLF001
                else:
                    tracker._inputs.append(record)  # noqa: SLF001
            except Exception as e:  # pragma: no cover - 防御性
                logger.warning("追踪文件失败 %s: %s", file_path, e)

    @staticmethod
    def _is_ignored(path: Path) -> bool:
        """判断文件是否应被忽略（内部方法）.

        忽略 __pycache__、.pyc、.DS_Store、临时文件等。

        Args:
            path: 文件路径。

        Returns:
            True 表示忽略。
        """
        parts = path.parts
        if "__pycache__" in parts:
            return True
        name = path.name
        if name.endswith(".pyc") or name.endswith(".pyo"):
            return True
        if name in {".DS_Store", "Thumbs.db"}:
            return True
        if name.endswith(".tmp") or name.endswith(".swp"):
            return True
        return False

    def _render_readme(
        self,
        project_name: str,
        description: str,
        data_source: str,
    ) -> str:
        """渲染 README.md 内容（内部方法）.

        Args:
            project_name: 项目名称。
            description: 项目描述。
            data_source: 数据来源。

        Returns:
            README.md 文本内容。
        """
        deps = _get_dependency_versions()
        deps_lines = "\n".join(
            f"- {name}: {ver}" for name, ver in deps.items()
        ) or "- （未检测到关键依赖）"

        description_text = description.strip() or "（请在打包后补充项目描述）"
        data_source_text = data_source.strip() or "（请在打包后补充数据来源说明）"

        return f"""# {project_name}

> 本可复现研究包由 ScholarPilot 自动生成。

## 项目说明

{description_text}

## 数据来源

{data_source_text}

## 运行步骤

### 1. 创建虚拟环境（推荐）

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows
.venv\\Scripts\\activate
```

### 2. 安装依赖

```bash
make install
# 或
pip install -r requirements.txt
```

### 3. 一键复现

```bash
make all
```

也可分步运行：

```bash
make data       # 数据准备
make analysis   # 统计分析
make paper      # 论文生成
```

## 依赖列表

{deps_lines}

完整依赖版本见 `requirements.txt`。

## 溯源信息

- Python 版本: {platform.python_version()}
- ScholarPilot 版本: {_get_scholarpilot_version()}
- 打包时间: {datetime.now(timezone.utc).isoformat()}

详细的输入/输出文件指纹与运行参数见 `manifest.json`。

## 目录结构

```
{project_name}/
├── data/            # 原始与处理后数据
├── code/            # 分析脚本
├── paper/           # 论文手稿
├── requirements.txt # 依赖锁定
├── Makefile         # 复现入口
├── manifest.json    # 溯源清单
└── README.md        # 本文件
```
"""
