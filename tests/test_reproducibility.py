"""可复现研究包模块（reproducibility）功能验证测试.

测试范围:
1. ProvenanceTracker 的 SHA256 哈希计算
2. ProvenanceTracker 的 track_input / track_output / record_params
3. ProvenanceTracker 的 manifest 生成与字段完整性
4. ReproducibilityPackager 的 requirements.txt 生成
5. ReproducibilityPackager 的 Makefile 生成
6. ReproducibilityPackager 的 README.md 生成
7. ReproducibilityPackager 的 zip 打包功能（含 manifest.json 校验）
8. include_data 开关与异常处理

运行方式:
    cd scholarpilot
    .venv\\Scripts\\python.exe -m pytest tests/test_reproducibility.py -v --tb=short
"""

from __future__ import annotations

import hashlib
import json
import platform
import zipfile
from pathlib import Path

import pytest

from scholarpilot.tools.reproducibility import (
    ProvenanceTracker,
    ReproducibilityPackager,
    _compute_sha256,
    _get_dependency_versions,
    _get_scholarpilot_version,
)


# ===== 辅助 fixtures =====


@pytest.fixture
def sample_text_file(tmp_path: Path) -> Path:
    """创建一个包含固定内容的文本文件."""
    path = tmp_path / "sample.txt"
    path.write_text("hello scholarpilot reproducibility\n", encoding="utf-8")
    return path


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """创建一个模拟的 ScholarPilot 项目目录（含 data/code/paper 子目录）."""
    project_dir = tmp_path / "demo_project"
    project_dir.mkdir()

    # data/ 目录
    data_dir = project_dir / "data"
    data_dir.mkdir()
    (data_dir / "raw.csv").write_text("year,region,gdp\n2020,北京,100\n", encoding="utf-8")
    (data_dir / "clean.csv").write_text("year,region,gdp\n2020,北京,100\n", encoding="utf-8")

    # code/ 目录
    code_dir = project_dir / "code"
    code_dir.mkdir()
    (code_dir / "01_data.py").write_text("print('data step')\n", encoding="utf-8")
    (code_dir / "02_analysis.py").write_text("print('analysis step')\n", encoding="utf-8")
    (code_dir / "03_paper.py").write_text("print('paper step')\n", encoding="utf-8")

    # paper/ 目录
    paper_dir = project_dir / "paper"
    paper_dir.mkdir()
    (paper_dir / "main.md").write_text("# 论文标题\n\n正文内容。\n", encoding="utf-8")
    (paper_dir / "references.bib").write_text("@article{ref1, title={Test}}\n", encoding="utf-8")

    return project_dir


@pytest.fixture
def tracker() -> ProvenanceTracker:
    """创建 ProvenanceTracker 实例."""
    return ProvenanceTracker()


@pytest.fixture
def packager() -> ReproducibilityPackager:
    """创建 ReproducibilityPackager 实例."""
    return ReproducibilityPackager()


# ===== 1. _compute_sha256 函数测试 =====


class TestComputeSha256:
    """测试 _compute_sha256 辅助函数."""

    def test_sha256_matches_hashlib(self, sample_text_file: Path):
        """_compute_sha256 结果应与 hashlib.sha256 一致."""
        expected = hashlib.sha256(sample_text_file.read_bytes()).hexdigest()
        assert _compute_sha256(sample_text_file) == expected

    def test_sha256_is_hex_string(self, sample_text_file: Path):
        """SHA256 应为 64 位小写十六进制字符串."""
        result = _compute_sha256(sample_text_file)
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_sha256_file_not_found(self, tmp_path: Path):
        """文件不存在时应抛出 FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            _compute_sha256(tmp_path / "nonexistent.txt")

    def test_sha256_on_directory_raises(self, tmp_path: Path):
        """对目录计算哈希应抛出 IsADirectoryError."""
        with pytest.raises(IsADirectoryError):
            _compute_sha256(tmp_path)

    def test_sha256_consistent(self, tmp_path: Path):
        """同一内容多次计算结果应一致."""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        content = b"consistent content"
        f1.write_bytes(content)
        f2.write_bytes(content)
        assert _compute_sha256(f1) == _compute_sha256(f2)


# ===== 2. ProvenanceTracker 测试 =====


class TestProvenanceTracker:
    """测试 ProvenanceTracker 的文件追踪与 manifest 生成."""

    def test_track_input_returns_record(self, tracker: ProvenanceTracker, sample_text_file: Path):
        """track_input 应返回包含 path/sha256/size/modified 的记录."""
        record = tracker.track_input(sample_text_file)
        assert record["path"] == str(sample_text_file)
        assert "sha256" in record
        assert record["size"] == sample_text_file.stat().st_size
        assert "modified" in record

    def test_track_input_sha256_correct(self, tracker: ProvenanceTracker, sample_text_file: Path):
        """track_input 记录的 sha256 应与手动计算一致."""
        record = tracker.track_input(sample_text_file)
        expected = hashlib.sha256(sample_text_file.read_bytes()).hexdigest()
        assert record["sha256"] == expected

    def test_track_output_separate_from_input(
        self, tracker: ProvenanceTracker, tmp_path: Path
    ):
        """track_output 记录应进入 outputs 而非 inputs."""
        in_file = tmp_path / "in.txt"
        out_file = tmp_path / "out.txt"
        in_file.write_text("input", encoding="utf-8")
        out_file.write_text("output", encoding="utf-8")

        tracker.track_input(in_file)
        tracker.track_output(out_file)

        manifest = tracker.generate_manifest()
        assert len(manifest["inputs"]) == 1
        assert len(manifest["outputs"]) == 1
        assert manifest["inputs"][0]["path"] == str(in_file)
        assert manifest["outputs"][0]["path"] == str(out_file)

    def test_track_input_file_not_found(self, tracker: ProvenanceTracker, tmp_path: Path):
        """追踪不存在的文件应抛出 FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            tracker.track_input(tmp_path / "missing.txt")

    def test_record_params_stored_in_manifest(
        self, tracker: ProvenanceTracker, sample_text_file: Path
    ):
        """record_params 的参数应出现在 manifest 的 parameters 字段."""
        tracker.track_input(sample_text_file)
        tracker.record_params({"model": "fe", "year_start": 2010, "cluster": "province"})
        manifest = tracker.generate_manifest()
        assert manifest["parameters"]["model"] == "fe"
        assert manifest["parameters"]["year_start"] == 2010
        assert manifest["parameters"]["cluster"] == "province"

    def test_record_params_merges(self, tracker: ProvenanceTracker):
        """多次 record_params 应合并（后者覆盖同名键）."""
        tracker.record_params({"a": 1, "b": 2})
        tracker.record_params({"b": 20, "c": 3})
        manifest = tracker.generate_manifest()
        assert manifest["parameters"] == {"a": 1, "b": 20, "c": 3}

    def test_record_params_type_error(self, tracker: ProvenanceTracker):
        """record_params 传入非 dict 应抛出 TypeError."""
        with pytest.raises(TypeError):
            tracker.record_params(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_manifest_has_required_fields(self, tracker: ProvenanceTracker):
        """manifest 应包含所有必需字段."""
        manifest = tracker.generate_manifest()
        required = {
            "created_at",
            "scholarpilot_version",
            "inputs",
            "outputs",
            "parameters",
            "python_version",
            "dependencies",
        }
        assert required.issubset(manifest.keys())

    def test_manifest_python_version(self, tracker: ProvenanceTracker):
        """manifest 的 python_version 应与 platform.python_version() 一致."""
        manifest = tracker.generate_manifest()
        assert manifest["python_version"] == platform.python_version()

    def test_manifest_scholarpilot_version(self, tracker: ProvenanceTracker):
        """manifest 的 scholarpilot_version 应非空."""
        manifest = tracker.generate_manifest()
        assert manifest["scholarpilot_version"]
        assert manifest["scholarpilot_version"] != ""

    def test_manifest_dependencies_is_dict(self, tracker: ProvenanceTracker):
        """manifest 的 dependencies 应为 dict."""
        manifest = tracker.generate_manifest()
        assert isinstance(manifest["dependencies"], dict)

    def test_to_json_valid(self, tracker: ProvenanceTracker, sample_text_file: Path):
        """to_json 应返回合法 JSON 字符串."""
        tracker.track_input(sample_text_file)
        tracker.record_params({"k": "v"})
        json_str = tracker.to_json()
        parsed = json.loads(json_str)
        assert parsed["parameters"]["k"] == "v"
        assert len(parsed["inputs"]) == 1

    def test_save_manifest_writes_file(
        self, tracker: ProvenanceTracker, sample_text_file: Path, tmp_path: Path
    ):
        """save_manifest 应写入 JSON 文件."""
        tracker.track_input(sample_text_file)
        out = tmp_path / "sub" / "manifest.json"
        result = tracker.save_manifest(out)
        assert result.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["inputs"]) == 1


# ===== 3. _get_scholarpilot_version / _get_dependency_versions 测试 =====


class TestVersionHelpers:
    """测试版本获取辅助函数."""

    def test_get_scholarpilot_version_nonempty(self):
        """_get_scholarpilot_version 应返回非空字符串."""
        ver = _get_scholarpilot_version()
        assert isinstance(ver, str)
        assert ver  # 非空

    def test_get_dependency_versions_returns_dict(self):
        """_get_dependency_versions 应返回字典（可能为空但须是 dict）."""
        deps = _get_dependency_versions()
        assert isinstance(deps, dict)
        # scholarpilot 自身应能被检测到（已安装）
        assert "scholarpilot" in deps


# ===== 4. ReproducibilityPackager - requirements.txt 测试 =====


class TestRequirementsGeneration:
    """测试 requirements.txt 生成."""

    def test_generate_requirements_creates_file(self, packager: ReproducibilityPackager, tmp_path: Path):
        """generate_requirements 应创建 requirements.txt."""
        out = tmp_path / "requirements.txt"
        result = packager.generate_requirements(out)
        assert result == out
        assert out.exists()

    def test_requirements_has_header(self, packager: ReproducibilityPackager, tmp_path: Path):
        """requirements.txt 应包含自动生成头部注释."""
        out = tmp_path / "requirements.txt"
        packager.generate_requirements(out)
        content = out.read_text(encoding="utf-8")
        assert "Auto-generated by ScholarPilot" in content
        assert "Python:" in content

    def test_requirements_contains_packages(self, packager: ReproducibilityPackager, tmp_path: Path):
        """requirements.txt 应包含至少一个包（pip freeze 或回退）."""
        out = tmp_path / "requirements.txt"
        packager.generate_requirements(out)
        content = out.read_text(encoding="utf-8")
        lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
        assert len(lines) > 0, "requirements.txt 应至少包含一个依赖"


# ===== 5. ReproducibilityPackager - Makefile 测试 =====


class TestMakefileGeneration:
    """测试 Makefile 生成."""

    def test_generate_makefile_creates_file(self, packager: ReproducibilityPackager, tmp_path: Path):
        """generate_makefile 应创建 Makefile."""
        out = tmp_path / "Makefile"
        result = packager.generate_makefile(out)
        assert result == out
        assert out.exists()

    def test_makefile_has_targets(self, packager: ReproducibilityPackager, tmp_path: Path):
        """Makefile 应包含 data / analysis / paper 三个目标."""
        out = tmp_path / "Makefile"
        packager.generate_makefile(out)
        content = out.read_text(encoding="utf-8")
        assert "data:" in content
        assert "analysis:" in content
        assert "paper:" in content
        assert "all:" in content
        assert "install:" in content

    def test_makefile_has_phony(self, packager: ReproducibilityPackager, tmp_path: Path):
        """Makefile 应包含 .PHONY 声明."""
        out = tmp_path / "Makefile"
        packager.generate_makefile(out)
        content = out.read_text(encoding="utf-8")
        assert ".PHONY:" in content


# ===== 6. ReproducibilityPackager - README.md 测试 =====


class TestReadmeGeneration:
    """测试 README.md 生成."""

    def test_generate_readme_creates_file(self, packager: ReproducibilityPackager, tmp_path: Path):
        """generate_readme 应创建 README.md."""
        out = tmp_path / "README.md"
        result = packager.generate_readme(out, project_name="test_proj")
        assert result == out
        assert out.exists()

    def test_readme_contains_project_name(self, packager: ReproducibilityPackager, tmp_path: Path):
        """README 应包含项目名称标题."""
        out = tmp_path / "README.md"
        packager.generate_readme(out, project_name="my_paper")
        content = out.read_text(encoding="utf-8")
        assert "# my_paper" in content

    def test_readme_contains_run_steps(self, packager: ReproducibilityPackager, tmp_path: Path):
        """README 应包含运行步骤说明（make data/analysis/paper）."""
        out = tmp_path / "README.md"
        packager.generate_readme(out, project_name="proj")
        content = out.read_text(encoding="utf-8")
        assert "make data" in content
        assert "make analysis" in content
        assert "make paper" in content
        assert "make install" in content

    def test_readme_contains_description(self, packager: ReproducibilityPackager, tmp_path: Path):
        """README 应包含自定义描述."""
        out = tmp_path / "README.md"
        desc = "本研究探讨地方政府债务风险。"
        packager.generate_readme(out, project_name="proj", description=desc)
        content = out.read_text(encoding="utf-8")
        assert desc in content

    def test_readme_contains_data_source(self, packager: ReproducibilityPackager, tmp_path: Path):
        """README 应包含数据来源说明."""
        out = tmp_path / "README.md"
        src = "数据来自 CNKI 与国家统计局。"
        packager.generate_readme(out, project_name="proj", data_source=src)
        content = out.read_text(encoding="utf-8")
        assert src in content


# ===== 7. ReproducibilityPackager - package 打包测试 =====


class TestPackageZip:
    """测试 zip 打包主流程."""

    def test_package_creates_zip(self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path):
        """package 应生成 zip 文件."""
        out = tmp_path / "result.zip"
        result = packager.package(sample_project, out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_package_zip_contains_expected_files(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """zip 内应包含项目文件和生成物."""
        out = tmp_path / "result.zip"
        packager.package(sample_project, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        # 项目文件
        assert "data/raw.csv" in names
        assert "data/clean.csv" in names
        assert "code/01_data.py" in names
        assert "code/02_analysis.py" in names
        assert "code/03_paper.py" in names
        assert "paper/main.md" in names
        assert "paper/references.bib" in names
        # 生成物
        assert "requirements.txt" in names
        assert "Makefile" in names
        assert "README.md" in names
        assert "manifest.json" in names

    def test_package_manifest_valid_json(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """zip 内的 manifest.json 应为合法 JSON 且字段完整."""
        out = tmp_path / "result.zip"
        packager.package(sample_project, out)
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        required = {
            "created_at",
            "scholarpilot_version",
            "inputs",
            "outputs",
            "parameters",
            "python_version",
            "dependencies",
        }
        assert required.issubset(manifest.keys())

    def test_package_manifest_inputs_include_data_files(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """manifest 的 inputs 应包含 data/ 和 code/ 下的文件."""
        out = tmp_path / "result.zip"
        packager.package(sample_project, out)
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        input_paths = [r["path"] for r in manifest["inputs"]]
        assert any(p.startswith("data/") for p in input_paths)
        assert any(p.startswith("code/") for p in input_paths)

    def test_package_manifest_outputs_include_paper_files(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """manifest 的 outputs 应包含 paper/ 下的文件."""
        out = tmp_path / "result.zip"
        packager.package(sample_project, out)
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        output_paths = [r["path"] for r in manifest["outputs"]]
        assert any(p.startswith("paper/") for p in output_paths)

    def test_package_manifest_records_sha256(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """manifest 中每个文件记录应包含非空 sha256."""
        out = tmp_path / "result.zip"
        packager.package(sample_project, out)
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        for record in manifest["inputs"] + manifest["outputs"]:
            assert record["sha256"]
            assert len(record["sha256"]) == 64

    def test_package_with_params(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """package 的 params 参数应写入 manifest."""
        out = tmp_path / "result.zip"
        packager.package(sample_project, out, params={"model": "fe", "n_boot": 500})
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["parameters"]["model"] == "fe"
        assert manifest["parameters"]["n_boot"] == 500

    def test_package_exclude_data(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """include_data=False 时 zip 内不应包含 data/ 目录."""
        out = tmp_path / "result.zip"
        packager.package(sample_project, out, include_data=False)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert not any(n.startswith("data/") for n in names)
        # code/ 和 paper/ 仍应存在
        assert any(n.startswith("code/") for n in names)
        assert any(n.startswith("paper/") for n in names)

    def test_package_project_not_found(self, packager: ReproducibilityPackager, tmp_path: Path):
        """项目目录不存在时应抛出 FileNotFoundError."""
        out = tmp_path / "result.zip"
        with pytest.raises(FileNotFoundError):
            packager.package(tmp_path / "nonexistent_project", out)

    def test_package_readme_in_zip_has_project_name(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """zip 内 README.md 应包含项目名称."""
        out = tmp_path / "result.zip"
        packager.package(sample_project, out, project_name="demo_project")
        with zipfile.ZipFile(out, "r") as zf:
            readme = zf.read("README.md").decode("utf-8")
        assert "# demo_project" in readme

    def test_package_requirements_in_zip_has_header(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """zip 内 requirements.txt 应包含生成头."""
        out = tmp_path / "result.zip"
        packager.package(sample_project, out)
        with zipfile.ZipFile(out, "r") as zf:
            req = zf.read("requirements.txt").decode("utf-8")
        assert "Auto-generated by ScholarPilot" in req

    def test_package_makefile_in_zip_has_targets(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """zip 内 Makefile 应包含 data/analysis/paper 目标."""
        out = tmp_path / "result.zip"
        packager.package(sample_project, out)
        with zipfile.ZipFile(out, "r") as zf:
            makefile = zf.read("Makefile").decode("utf-8")
        assert "data:" in makefile
        assert "analysis:" in makefile
        assert "paper:" in makefile

    def test_package_ignores_pycache(
        self, packager: ReproducibilityPackager, sample_project: Path, tmp_path: Path
    ):
        """打包时应忽略 __pycache__ 与 .pyc 文件."""
        # 在 code/ 下制造 __pycache__
        pycache = sample_project / "code" / "__pycache__"
        pycache.mkdir()
        (pycache / "module.cpython-313.pyc").write_bytes(b"\x00\x01\x02")
        (sample_project / "code" / "temp.tmp").write_text("tmp", encoding="utf-8")

        out = tmp_path / "result.zip"
        packager.package(sample_project, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert not any("__pycache__" in n for n in names)
        assert not any(n.endswith(".pyc") for n in names)
        assert not any(n.endswith(".tmp") for n in names)


# ===== 8. 自定义 include_dirs 测试 =====


class TestCustomIncludeDirs:
    """测试自定义 include_dirs 参数."""

    def test_custom_include_dirs(self, sample_project: Path, tmp_path: Path):
        """自定义 include_dirs 应只纳入指定目录."""
        # 在项目中加一个 analysis/ 目录
        (sample_project / "analysis").mkdir()
        (sample_project / "analysis" / "out.md").write_text("output", encoding="utf-8")

        packager = ReproducibilityPackager(include_dirs=("data", "analysis"))
        out = tmp_path / "result.zip"
        packager.package(sample_project, out)
        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()
        assert any(n.startswith("data/") for n in names)
        assert any(n.startswith("analysis/") for n in names)
        # code/ 和 paper/ 不应被纳入
        assert not any(n.startswith("code/") for n in names)
        assert not any(n.startswith("paper/") for n in names)
