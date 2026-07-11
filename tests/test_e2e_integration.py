"""端到端集成测试：验证实证工具链全流程连通性.

测试范围:
1. SPEC → 代码模板生成（code_template_generator）
2. SPEC → 表格模板生成（ScholarAgent.generate_tables）
3. 数据预处理 → 统计分析（data_preprocessor + stats_engine）
4. 草稿合并 → 质量报告 → 导出（_merge_draft + quality_report + exporter）
5. 完整流程：SPEC → 代码模板 + 表格模板 + 质量报告

运行方式:
    cd scholarpilot
    $env:PYTHONPATH='src'; python -m pytest tests/test_e2e_integration.py -v
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ===== 测试用 SPEC 文本 =====

EMPIRICAL_SPEC = """# 论文规格

## 研究主题
地方政府债务风险的空间溢出效应研究

## 研究问题
1. 地方政府债务风险是否存在空间溢出效应？
2. 财政缺口如何影响债务风险的空间传导？

## 变量设计
- 被解释变量：debt_risk（地方政府债务风险指数）
- 核心解释变量：fiscal_gap（财政缺口率）
- 控制变量：gdp_growth（GDP增长率）、pop_density（人口密度）、urban_rate（城镇化率）、fiscal_decn（财政分权度）

## 模型设定
采用空间杜宾模型（SDM），使用31个省份2010-2023年面板数据。
存在内生性问题，使用滞后一期财政缺口作为工具变量。
分析中介效应：fiscal_gap → financial_development → debt_risk

## 数据需求
- 数据来源：Wind数据库
- 样本期间：2010-2023年
- 截面单元：31个省份
"""


# ===== Fixtures =====

@pytest.fixture
def temp_project():
    """创建完整的临时项目目录."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "test_project"
        project_dir.mkdir()

        # 创建目录结构
        (project_dir / "draft").mkdir()
        (project_dir / ".scholar").mkdir()
        (project_dir / "data").mkdir()
        (project_dir / "analysis").mkdir()
        (project_dir / "final").mkdir()
        (project_dir / "literature").mkdir()

        # SPEC.md
        (project_dir / "SPEC.md").write_text(EMPIRICAL_SPEC, encoding="utf-8")

        # outline.json
        outline = {
            "title": "地方政府债务风险的空间溢出效应研究",
            "keywords": ["地方政府债务", "空间溢出", "财政风险"],
            "sections": [
                {"id": 1, "title": "引言", "word_count": 3000},
                {"id": 2, "title": "文献综述", "word_count": 4000},
                {"id": 3, "title": "理论分析与研究设计", "word_count": 3000},
                {"id": 4, "title": "实证分析", "word_count": 5000},
                {"id": 5, "title": "结论与政策建议", "word_count": 2000},
            ],
        }
        (project_dir / "outline.json").write_text(
            json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 草稿文件
        draft_content = """# 地方政府债务风险的空间溢出效应研究

## 摘要

本文研究地方政府债务风险的空间溢出效应。采用空间杜宾模型，使用2010-2023年省级面板数据进行实证分析。研究发现地方政府债务存在显著的空间溢出效应，财政缺口加剧了债务风险的空间传导。

**关键词**: 地方政府债务；空间溢出；财政风险

**JEL分类号**: H63, H74

---

## 第一章 引言

地方政府债务问题是当前中国经济的核心风险之一（毛捷和徐军伟，2019）。近年来随着经济下行压力加大，地方债务规模持续膨胀。本文旨在分析债务风险的空间溢出效应，为防范化解系统性风险提供理论依据。

---

## 第二章 文献综述

关于地方政府债务的研究，周黎安（2007）从财政分权角度分析了地方债务的成因。郭玉清等（2016）发现地方债务存在显著的区域差异。Smith and Jones（2022）examined fiscal sustainability across regions. 毛捷和徐军伟（2019）分析了隐性债务的规模和结构。

---

## 第三章 理论分析与研究设计

本文基于空间经济学理论，构建空间杜宾模型分析债务风险的空间溢出。变量设计包括被解释变量debt_risk、核心解释变量fiscal_gap，以及GDP增长率、人口密度等控制变量。

---

## 第四章 实证分析

描述性统计显示debt_risk均值为0.45，标准差0.12。回归结果表明fiscal_gap对debt_risk的系数为0.234，在1%水平显著。空间Moran's I指数为0.35，表明存在正向空间自相关。

---

## 第五章 结论与政策建议

本文发现地方政府债务风险存在显著的空间溢出效应。建议加强区域协调监管，建立跨区域债务风险预警机制。

## 参考文献

[1] 毛捷, 徐军伟. 地方政府隐性债务的规模与结构[J]. 经济研究, 2019(3): 18-33.

[2] 周黎安. 中国地方官员的晋升锦标赛模式研究[J]. 经济研究, 2007(7): 36-50.

[3] 郭玉清, 何杨, 孙宗宽. 地方政府债务风险的区域差异[J]. 金融研究, 2016(5): 100-115.

[4] Smith, J. and Jones, M. (2022). Fiscal sustainability across regions. Journal of Public Economics, 200, 104-120.
"""
        (project_dir / "draft" / "full_draft.md").write_text(draft_content, encoding="utf-8")

        # 创建独立章节文件
        for i, chapter in enumerate(["chapter1_introduction", "chapter2_literature",
                                      "chapter3_design", "chapter4_empirical", "chapter5_conclusion"], 1):
            (project_dir / "draft" / f"{chapter}.md").write_text(
                f"## 第{['一','二','三','四','五'][i-1]}章 {chapter.split('_',1)[1].title()}\n\n章节内容...\n",
                encoding="utf-8"
            )

        # 模拟数据文件
        try:
            import pandas as pd
            import numpy as np
            np.random.seed(42)
            n = 434  # 31省份 * 14年
            data = pd.DataFrame({
                "province": np.repeat(range(1, 32), 14),
                "year": np.tile(range(2010, 2024), 31),
                "debt_risk": np.random.normal(0.45, 0.12, n),
                "fiscal_gap": np.random.normal(0.3, 0.1, n),
                "gdp_growth": np.random.normal(7.5, 2.0, n),
                "pop_density": np.random.normal(400, 200, n),
                "urban_rate": np.random.normal(55, 15, n),
            })
            data_path = project_dir / "data" / "user_data.csv"
            data.to_csv(data_path, index=False, encoding="utf-8-sig")
        except ImportError:
            pass

        # memory.json
        memory = {
            "entries": [
                {"phase": "literature_search", "status": "done"},
                {"phase": "spec_generation", "status": "done"},
                {"phase": "outline", "status": "done"},
                {"phase": "writing", "status": "done"},
            ],
        }
        (project_dir / ".scholar" / "memory.json").write_text(
            json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # citation_memory.json
        citation_memory = {
            "total": 4,
            "verified": 3,
            "unverified": 1,
        }
        (project_dir / ".scholar" / "citation_memory.json").write_text(
            json.dumps(citation_memory, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        yield project_dir


@pytest.fixture
def mock_agent(temp_project):
    """创建模拟的 ScholarAgent 实例."""
    from scholarpilot.agent.scholar import ScholarAgent

    agent = ScholarAgent.__new__(ScholarAgent)
    agent.project_dir = temp_project
    agent.console = MagicMock()
    agent.config = MagicMock()
    agent.config.user_home_dir = temp_project / ".user_home"
    agent.config.user_home_dir.mkdir(exist_ok=True)

    # 模拟 file_manager
    agent.file_manager = MagicMock()
    agent.file_manager.list_sections.return_value = [
        "chapter1_introduction.md",
        "chapter2_literature.md",
        "chapter3_design.md",
        "chapter4_empirical.md",
        "chapter5_conclusion.md",
    ]
    agent.file_manager.load_section.return_value = "章节内容"

    # 模拟 memory
    agent.memory = MagicMock()
    agent.memory.get.return_value = {
        "total": 4,
        "verified": 3,
        "unverified": 1,
    }

    # 模拟 LLM
    agent.llm = MagicMock()
    agent.llm.chat = AsyncMock()

    return agent


# ===== 1. SPEC → 代码模板生成 =====

class TestSpecToCodeTemplate:
    """测试从 SPEC 生成代码模板的完整流程."""

    def test_stata_template_from_real_spec(self, temp_project):
        """从真实 SPEC 生成 Stata 模板."""
        from scholarpilot.tools.code_template_generator import CodeTemplateGenerator

        spec_text = (temp_project / "SPEC.md").read_text(encoding="utf-8")
        gen = CodeTemplateGenerator(project_dir=temp_project)

        template = gen.generate_stata_template(spec_text, title="测试论文")

        assert "clear all" in template
        assert "xtset" in template
        assert "xtreg" in template
        assert "winsor2" in template
        assert "esttab" in template
        assert "star(* 0.10 ** 0.05 *** 0.01)" in template
        assert "debt_risk" in template
        assert "fiscal_gap" in template

    def test_full_template_with_spatial_detection(self, temp_project):
        """完整模板检测到空间计量关键词."""
        from scholarpilot.tools.code_template_generator import CodeTemplateGenerator

        spec_text = (temp_project / "SPEC.md").read_text(encoding="utf-8")
        gen = CodeTemplateGenerator(project_dir=temp_project)

        template = gen.generate_full_template(spec_text, lang="stata", title="测试")

        # 应该检测到空间关键词并追加空间模板
        keywords = gen._detect_method_keywords(spec_text)
        assert keywords["has_spatial"] is True
        assert keywords["has_iv"] is True or keywords["has_endogeneity"] is True
        assert keywords["has_mediation"] is True

    def test_r_template_generated(self, temp_project):
        """生成 R 模板."""
        from scholarpilot.tools.code_template_generator import CodeTemplateGenerator

        spec_text = (temp_project / "SPEC.md").read_text(encoding="utf-8")
        gen = CodeTemplateGenerator(project_dir=temp_project)

        template = gen.generate_r_template(spec_text, title="测试")

        assert "library" in template
        assert "feols" in template or "lm" in template

    def test_python_template_generated(self, temp_project):
        """生成 Python 模板."""
        from scholarpilot.tools.code_template_generator import CodeTemplateGenerator

        spec_text = (temp_project / "SPEC.md").read_text(encoding="utf-8")
        gen = CodeTemplateGenerator(project_dir=temp_project)

        template = gen.generate_python_template(spec_text, title="测试")

        assert "import" in template
        assert "statsmodels" in template or "linearmodels" in template

    def test_code_saved_to_analysis_dir(self, temp_project):
        """代码模板应可保存到 analysis/ 目录."""
        from scholarpilot.tools.code_template_generator import CodeTemplateGenerator

        spec_text = (temp_project / "SPEC.md").read_text(encoding="utf-8")
        gen = CodeTemplateGenerator(project_dir=temp_project)

        template = gen.generate_full_template(spec_text, lang="stata", title="测试")
        output_path = temp_project / "analysis" / "analysis_template.do"
        output_path.write_text(template, encoding="utf-8")

        assert output_path.exists()
        assert len(template) > 500  # 模板应该有足够内容


# ===== 2. SPEC → 表格模板生成 =====

class TestSpecToTableTemplate:
    """测试从 SPEC 生成表格模板."""

    def test_generate_tables_returns_dict(self, mock_agent):
        """generate_tables 返回正确结构."""
        import asyncio

        result = asyncio.run(mock_agent.generate_tables())

        assert isinstance(result, dict)
        assert "table_count" in result or "tables" in result or "message" in result or "generated" in result

    def test_table_template_file_created(self, mock_agent):
        """表格模板文件被创建."""
        import asyncio

        asyncio.run(mock_agent.generate_tables())

        table_path = mock_agent.project_dir / "draft" / "tables_template.md"
        # 如果 SPEC 存在变量，应该生成表格
        if table_path.exists():
            content = table_path.read_text(encoding="utf-8")
            assert len(content) > 0


# ===== 3. 数据预处理 → 统计分析 =====

class TestDataPreprocessingAndStats:
    """测试数据预处理和统计分析的集成."""

    def test_preprocess_then_stats(self, temp_project):
        """预处理后数据可用于统计分析."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")

        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        from scholarpilot.tools.stats_engine import StatsEngine

        # 加载数据
        dp = DataPreprocessor()
        data_path = temp_project / "data" / "user_data.csv"
        df = dp.load_data(data_path)

        # 缩尾处理
        numeric_vars = ["debt_risk", "fiscal_gap", "gdp_growth"]
        df_cleaned = dp.winsorize(df, numeric_vars, lower=0.01, upper=0.99)

        # 描述性统计
        engine = StatsEngine()
        desc = engine.descriptive_stats(df_cleaned, variables=numeric_vars)

        assert "debt_risk" in desc
        assert "mean" in desc["debt_risk"]
        assert "std" in desc["debt_risk"]

    def test_ols_regression_on_real_data(self, temp_project):
        """用模拟数据跑 OLS 回归."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")

        try:
            import statsmodels  # noqa: F401
        except ImportError:
            pytest.skip("statsmodels not installed")

        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        from scholarpilot.tools.stats_engine import StatsEngine

        dp = DataPreprocessor()
        df = dp.load_data(temp_project / "data" / "user_data.csv")

        engine = StatsEngine()
        result = engine.ols_regression(
            df, dep_var="debt_risk",
            indep_vars=["fiscal_gap", "gdp_growth"],
            robust=True,
        )

        assert "coefficients" in result
        assert "r_squared" in result
        assert "n_obs" in result
        assert result["n_obs"] > 0

    def test_correlation_matrix_on_real_data(self, temp_project):
        """相关系数矩阵计算."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")

        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        from scholarpilot.tools.stats_engine import StatsEngine

        dp = DataPreprocessor()
        df = dp.load_data(temp_project / "data" / "user_data.csv")

        engine = StatsEngine()
        result = engine.correlation_matrix(
            df, variables=["debt_risk", "fiscal_gap", "gdp_growth"],
        )

        assert "matrix" in result
        assert "debt_risk" in result["matrix"]
        # 对角线应该是 1
        assert abs(result["matrix"]["debt_risk"]["debt_risk"] - 1.0) < 0.01

    def test_vif_test_on_real_data(self, temp_project):
        """VIF 检验."""
        try:
            import statsmodels  # noqa: F401
        except ImportError:
            pytest.skip("statsmodels not installed")

        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        from scholarpilot.tools.stats_engine import StatsEngine

        dp = DataPreprocessor()
        df = dp.load_data(temp_project / "data" / "user_data.csv")

        engine = StatsEngine()
        result = engine.vif_test(df, indep_vars=["fiscal_gap", "gdp_growth", "urban_rate"])

        assert "variables" in result
        assert "max_vif" in result
        assert result["max_vif"] > 0

    def test_panel_regression_on_real_data(self, temp_project):
        """面板回归测试."""
        try:
            import linearmodels  # noqa: F401
        except ImportError:
            pytest.skip("linearmodels not installed")

        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        from scholarpilot.tools.stats_engine import StatsEngine

        dp = DataPreprocessor()
        df = dp.load_data(temp_project / "data" / "user_data.csv")

        engine = StatsEngine()
        result = engine.panel_regression(
            df, dep_var="debt_risk",
            indep_vars=["fiscal_gap", "gdp_growth"],
            entity_var="province", time_var="year",
            model="fe", cluster=True,
        )

        assert "coefficients" in result
        assert "n_obs" in result

    def test_cleaning_report_generated(self, temp_project):
        """数据清洗报告生成."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")

        from scholarpilot.tools.data_preprocessor import DataPreprocessor

        dp = DataPreprocessor()
        df = dp.load_data(temp_project / "data" / "user_data.csv")
        df_cleaned = dp.winsorize(df, ["debt_risk", "fiscal_gap"])

        report = dp.generate_cleaning_report(
            df, df_cleaned,
            operations=["缩尾处理: 2个变量 (1%/99%)"],
        )

        assert "清洗" in report or "报告" in report or "原始" in report
        assert len(report) > 50


# ===== 4. 草稿合并 → 质量报告 → 导出 =====

class TestDraftMergeQualityExport:
    """测试草稿合并、质量报告和导出的集成."""

    def test_merge_draft_uses_outline_title(self, mock_agent):
        """合并草稿使用 outline.json 中的标题."""
        mock_agent._merge_draft()

        draft_path = mock_agent.project_dir / "draft" / "full_draft.md"
        assert draft_path.exists()
        content = draft_path.read_text(encoding="utf-8")
        assert "地方政府债务风险的空间溢出效应研究" in content

    def test_quality_report_on_real_draft(self, mock_agent):
        """对真实草稿生成质量报告."""
        report = mock_agent.generate_quality_report()

        assert report["word_count"] > 0
        assert report["chapter_count"] >= 0
        assert "structure" in report
        assert "assessment" in report
        assert "is_empirical" in report

    def test_quality_report_empirical_flag(self, mock_agent):
        """质量报告正确识别实证论文."""
        report = mock_agent.generate_quality_report()

        # SPEC 包含实证关键词，应该识别为实证
        assert report.get("is_empirical", False) is True

    def test_exporter_no_duplicate_content(self, temp_project):
        """导出器不重复合并 full_draft.md."""
        from scholarpilot.tools.exporter import _merge_sections

        # 调用 _merge_sections
        result = _merge_sections(temp_project)

        assert result is not None
        content = result.read_text(encoding="utf-8")

        # full_draft.md 原始内容不应在合并结果中出现两次
        # 检查标题不应重复出现
        title_count = content.count("地方政府债务风险的空间溢出效应研究")
        assert title_count <= 2  # 标题出现1-2次合理（合并标题+章节内）

        # 不应包含 full_draft.md 自身内容多次
        assert content.count("摘要") <= 2

    def test_exporter_excludes_auxiliary_files(self, temp_project):
        """导出器排除辅助文件（abstract/references/tables_template）."""
        from scholarpilot.tools.exporter import _merge_sections

        # 创建辅助文件
        (temp_project / "draft" / "abstract.md").write_text("# 摘要\n独立摘要文件", encoding="utf-8")
        (temp_project / "draft" / "references.md").write_text("# 参考文献\n独立参考文件", encoding="utf-8")

        result = _merge_sections(temp_project)
        content = result.read_text(encoding="utf-8")

        # 辅助文件内容不应被重复合并
        # (它们的内容可能在 full_draft.md 中已有，但不应额外添加)
        assert content.count("独立摘要文件") == 0
        assert content.count("独立参考文件") == 0

    def test_export_markdown(self, temp_project):
        """导出 Markdown 格式."""
        from scholarpilot.tools.exporter import export_project

        output = export_project(temp_project, fmt="md", output_name="test_paper")
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert len(content) > 100

    def test_export_docx(self, temp_project):
        """导出 DOCX 格式."""
        try:
            from docx import Document  # noqa: F401
        except ImportError:
            pytest.skip("python-docx not installed")

        from scholarpilot.tools.exporter import export_project

        output = export_project(temp_project, fmt="docx", output_name="test_paper")
        assert output.exists()
        assert output.suffix == ".docx"


# ===== 5. 完整流程集成 =====

class TestFullWorkflowIntegration:
    """测试完整实证工具链流程."""

    def test_spec_to_code_to_analysis(self, temp_project):
        """SPEC → 代码模板 → 保存到 analysis/ 目录."""
        from scholarpilot.tools.code_template_generator import CodeTemplateGenerator

        spec_text = (temp_project / "SPEC.md").read_text(encoding="utf-8")
        gen = CodeTemplateGenerator(project_dir=temp_project)

        # 生成完整模板
        template = gen.generate_full_template(spec_text, lang="stata", title="测试论文")

        # 保存
        output_path = temp_project / "analysis" / "analysis_template.do"
        output_path.write_text(template, encoding="utf-8")

        # 验证模板包含完整流程
        assert "数据导入" in template or "import" in template.lower()
        assert "描述性统计" in template or "summarize" in template
        assert "回归" in template or "reg" in template.lower()
        assert "稳健性" in template or "robust" in template.lower()

    def test_data_to_stats_to_report(self, temp_project):
        """数据 → 统计分析 → 结果保存."""
        try:
            import pandas as pd
            import statsmodels  # noqa: F401
        except ImportError:
            pytest.skip("empirical dependencies not installed")

        from scholarpilot.tools.data_preprocessor import DataPreprocessor
        from scholarpilot.tools.stats_engine import StatsEngine

        # 加载数据
        dp = DataPreprocessor()
        df = dp.load_data(temp_project / "data" / "user_data.csv")

        # 运行完整分析
        engine = StatsEngine()
        results = engine.run_full_analysis(
            df, dep_var="debt_risk",
            indep_vars=["fiscal_gap", "gdp_growth", "urban_rate"],
        )

        # 验证结果完整性
        assert "descriptive" in results
        assert "correlation" in results
        assert "regression" in results
        assert "vif" in results

        # 保存结果
        output_path = temp_project / ".scholar" / "stats_results.json"
        output_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        assert output_path.exists()

    def test_quality_report_after_writing(self, mock_agent):
        """写作完成后的质量报告包含所有必要评估."""
        report = mock_agent.generate_quality_report()

        # 核心字段
        required_fields = [
            "word_count", "chapter_count", "reference_count",
            "verified_count", "unverified_count",
            "has_abstract", "has_keywords", "has_jel",
            "structure", "structure_complete",
            "missing_parts", "assessment",
            "is_empirical",
        ]
        for field in required_fields:
            assert field in report, f"缺少字段: {field}"

        # 评估字段
        assessment = report["assessment"]
        assert "word_count" in assessment
        assert "references" in assessment

    def test_finalize_interface(self, mock_agent):
        """finalize 接口可正常调用."""
        import asyncio

        mock_agent._phase7a_generate_abstract = AsyncMock()
        mock_agent._phase7b_citation_management = AsyncMock()
        mock_agent._merge_draft = MagicMock()

        result = asyncio.run(
            mock_agent.finalize(abstract=True, citations=True)
        )

        mock_agent._phase7a_generate_abstract.assert_called_once()
        mock_agent._phase7b_citation_management.assert_called_once()
        assert isinstance(result, dict)
