"""实证表格模板生成功能验证测试.

测试范围:
1. SPEC 变量提取（正则解析）
2. 表格模板生成（描述性统计/回归/相关系数）
3. 集成测试：从 SPEC 到表格文件
4. 质量报告中的表格检查

运行方式:
    cd scholarpilot
    python -m pytest tests/test_tables.py -v
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ===== Fixtures =====

@pytest.fixture
def empirical_project():
    """创建实证论文项目（含 SPEC）."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "empirical_paper"
        project_dir.mkdir()
        (project_dir / "draft").mkdir()
        (project_dir / ".scholar").mkdir()

        # SPEC.md 含变量设计和模型设定
        spec_content = """# 论文规格

## 研究主题
地方政府债务风险的空间溢出效应

## 研究类型
empirical（实证研究）

## 变量设计
- 被解释变量：debt_risk（地方政府债务风险指数）
- 核心解释变量：fiscal_gap（财政缺口率）
- 控制变量：gdp_growth（GDP增长率）
- 控制变量：pop_density（人口密度）
- 控制变量：urban_rate（城镇化率，虚拟变量）
- 控制变量：fdi_ratio（FDI占比）

## 模型设定
采用空间面板模型，包含个体固定效应和时间固定效应。
使用聚类稳健标准误。稳健性检验：替换空间权重矩阵。

## 预期结果
财政缺口对债务风险有正向影响。
"""
        (project_dir / "SPEC.md").write_text(spec_content, encoding="utf-8")

        # outline.json
        outline = {
            "title": "地方政府债务风险的空间溢出效应研究",
            "keywords": ["地方政府债务", "空间溢出"],
            "sections": [],
        }
        (project_dir / "outline.json").write_text(
            json.dumps(outline, ensure_ascii=False), encoding="utf-8"
        )

        # 草稿文件
        draft_content = "# 地方政府债务风险的空间溢出效应研究\n\n## 摘要\n\n本文研究实证分析。\n\n## 第一章 引言\n\n## 第二章 文献综述\n\n## 第三章 研究设计\n\n## 第四章 实证分析\n\n回归结果显著。\n\n## 第五章 结论\n"
        (project_dir / "draft" / "full_draft.md").write_text(draft_content, encoding="utf-8")

        yield project_dir


@pytest.fixture
def theoretical_project():
    """创建理论论文项目（非实证）."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "theoretical_paper"
        project_dir.mkdir()
        (project_dir / "draft").mkdir()
        (project_dir / ".scholar").mkdir()

        spec_content = """# 论文规格

## 研究主题
财政分权理论框架的拓展

## 研究类型
theoretical（理论分析）

## 核心理论框架
基于博弈论构建中央-地方博弈模型。
"""
        (project_dir / "SPEC.md").write_text(spec_content, encoding="utf-8")
        yield project_dir


@pytest.fixture
def mock_agent_factory():
    """创建 ScholarAgent mock 工厂."""
    from scholarpilot.agent.scholar import ScholarAgent

    def _create(project_dir):
        agent = ScholarAgent.__new__(ScholarAgent)
        agent.project_dir = project_dir
        agent.console = MagicMock()
        agent.file_manager = MagicMock()
        agent.memory = MagicMock()
        agent.config = MagicMock()
        return agent

    return _create


# ===== 1. SPEC 变量提取测试 =====

class TestVariableExtraction:
    """测试从 SPEC 提取变量定义."""

    def test_extract_variables(self, mock_agent_factory, empirical_project):
        """从 SPEC 文本提取变量."""
        agent = mock_agent_factory(empirical_project)
        spec_text = (empirical_project / "SPEC.md").read_text(encoding="utf-8")

        variables, model_specs = agent._extract_variables_from_spec(spec_text)

        assert len(variables) > 0
        # 应该包含 debt_risk
        var_names = [v["name"] for v in variables]
        assert "debt_risk" in var_names
        assert "fiscal_gap" in var_names

    def test_extract_variable_descriptions(self, mock_agent_factory, empirical_project):
        """变量描述正确提取."""
        agent = mock_agent_factory(empirical_project)
        spec_text = (empirical_project / "SPEC.md").read_text(encoding="utf-8")

        variables, _ = agent._extract_variables_from_spec(spec_text)

        debt_risk = next(v for v in variables if v["name"] == "debt_risk")
        assert "债务风险" in debt_risk["description"]

    def test_detect_dummy_variable(self, mock_agent_factory, empirical_project):
        """虚拟变量类型检测."""
        agent = mock_agent_factory(empirical_project)
        spec_text = (empirical_project / "SPEC.md").read_text(encoding="utf-8")

        variables, _ = agent._extract_variables_from_spec(spec_text)

        urban = next(v for v in variables if v["name"] == "urban_rate")
        assert urban["type"] == "虚拟变量"

    def test_extract_model_specs(self, mock_agent_factory, empirical_project):
        """模型设定提取."""
        agent = mock_agent_factory(empirical_project)
        spec_text = (empirical_project / "SPEC.md").read_text(encoding="utf-8")

        _, model_specs = agent._extract_variables_from_spec(spec_text)

        assert len(model_specs) > 0
        # 应该检测到固定效应
        assert model_specs[0]["has_fixed_effects"] is True
        # 应该检测到聚类标准误
        assert model_specs[0]["has_cluster_se"] is True

    def test_robustness_model(self, mock_agent_factory, empirical_project):
        """稳健性检验模型."""
        agent = mock_agent_factory(empirical_project)
        spec_text = (empirical_project / "SPEC.md").read_text(encoding="utf-8")

        _, model_specs = agent._extract_variables_from_spec(spec_text)

        # 应该有2个模型（基准+稳健性）
        model_names = [m["name"] for m in model_specs]
        assert "基准回归" in model_names
        assert "稳健性检验" in model_names

    def test_no_variables_in_theoretical(self, mock_agent_factory, theoretical_project):
        """理论论文无变量提取."""
        agent = mock_agent_factory(theoretical_project)
        spec_text = (theoretical_project / "SPEC.md").read_text(encoding="utf-8")

        variables, _ = agent._extract_variables_from_spec(spec_text)
        # 理论论文不包含变量设计
        assert len(variables) == 0


# ===== 2. 表格模板生成测试 =====

class TestTableGeneration:
    """测试表格模板生成."""

    @pytest.mark.asyncio
    async def test_generate_tables_creates_file(self, mock_agent_factory, empirical_project):
        """生成表格模板文件."""
        agent = mock_agent_factory(empirical_project)
        await agent._phase7c_generate_table_templates()

        tables_path = empirical_project / "draft" / "tables_template.md"
        assert tables_path.exists()

        content = tables_path.read_text(encoding="utf-8")
        assert "描述性统计" in content
        assert "回归结果" in content
        assert "相关系数" in content

    @pytest.mark.asyncio
    async def test_tables_contain_variables(self, mock_agent_factory, empirical_project):
        """表格包含 SPEC 中的变量."""
        agent = mock_agent_factory(empirical_project)
        await agent._phase7c_generate_table_templates()

        content = (empirical_project / "draft" / "tables_template.md").read_text(encoding="utf-8")
        assert "debt_risk" in content
        assert "fiscal_gap" in content

    @pytest.mark.asyncio
    async def test_tables_have_empty_cells(self, mock_agent_factory, empirical_project):
        """表格数据单元格为空."""
        agent = mock_agent_factory(empirical_project)
        await agent._phase7c_generate_table_templates()

        content = (empirical_project / "draft" / "tables_template.md").read_text(encoding="utf-8")
        # 描述性统计表应该有空的数据单元格（|  | 格式，含空格）
        lines = content.split("\n")
        # 找到 debt_risk 行
        debt_line = next(l for l in lines if "debt_risk" in l)
        # 去掉变量名和描述后，应该有空单元格
        cleaned = debt_line.replace("debt_risk", "").replace("地方政府债务风险指数", "")
        # 空单元格表现为连续的 | 之间只有空格
        assert "|  |" in cleaned or "||" in cleaned

    @pytest.mark.asyncio
    async def test_skip_theoretical_paper(self, mock_agent_factory, theoretical_project):
        """理论论文跳过表格生成."""
        agent = mock_agent_factory(theoretical_project)
        await agent._phase7c_generate_table_templates()

        tables_path = theoretical_project / "draft" / "tables_template.md"
        assert not tables_path.exists()

    @pytest.mark.asyncio
    async def test_generate_tables_independent(self, mock_agent_factory, empirical_project):
        """独立 generate_tables 方法."""
        agent = mock_agent_factory(empirical_project)
        result = await agent.generate_tables()

        assert result["generated"] is True
        assert "tables_template.md" in result["path"]


# ===== 3. table_generator 单元测试 =====

class TestTableGenerator:
    """直接测试 table_generator 模块."""

    def test_descriptive_stats_table(self):
        """描述性统计表生成."""
        from scholarpilot.tools.table_generator import generate_descriptive_stats_table

        variables = [
            {"name": "gdp", "description": "GDP增长率", "type": "continuous"},
            {"name": "debt", "description": "债务率", "type": "continuous"},
        ]
        table = generate_descriptive_stats_table(variables)

        assert "变量" in table
        assert "均值" in table
        assert "标准差" in table
        assert "gdp" in table
        assert "debt" in table
        assert "GDP增长率" in table

    def test_regression_table(self):
        """回归结果表生成."""
        from scholarpilot.tools.table_generator import generate_regression_table

        model_specs = [
            {
                "name": "基准回归",
                "variables": ["gdp", "debt", "pop"],
                "has_fixed_effects": True,
                "has_cluster_se": True,
            },
            {
                "name": "稳健性检验",
                "variables": ["gdp", "debt"],
                "has_fixed_effects": True,
                "has_cluster_se": False,
            },
        ]
        table = generate_regression_table(model_specs)

        assert "基准回归" in table
        assert "稳健性检验" in table
        assert "gdp" in table
        assert "R²" in table
        assert "固定效应" in table
        assert "Yes" in table

    def test_correlation_table(self):
        """相关系数矩阵生成."""
        from scholarpilot.tools.table_generator import generate_correlation_table

        variables = ["gdp", "debt", "pop"]
        table = generate_correlation_table(variables)

        assert "gdp" in table
        assert "debt" in table
        assert "1.000" in table  # 对角线

    def test_empty_regression_table(self):
        """空模型规格不崩溃."""
        from scholarpilot.tools.table_generator import generate_regression_table

        table = generate_regression_table([])
        assert table == ""


# ===== 4. 质量报告中的表格检查 =====

class TestQualityReportTables:
    """测试质量报告中的表格模板检查."""

    def test_report_includes_tables_field(self, mock_agent_factory, empirical_project):
        """质量报告包含表格字段."""
        agent = mock_agent_factory(empirical_project)
        agent.file_manager.list_sections.return_value = ["ch1", "ch2", "ch3", "ch4", "ch5"]
        agent.file_manager.load_section.return_value = "内容"
        agent.memory.get.return_value = {}

        report = agent.generate_quality_report()
        assert "has_tables_template" in report
        assert "table_count" in report

    def test_report_shows_tables_after_generation(self, mock_agent_factory, empirical_project):
        """生成表格后质量报告显示."""
        agent = mock_agent_factory(empirical_project)
        agent.file_manager.list_sections.return_value = ["ch1", "ch2", "ch3", "ch4", "ch5"]
        agent.file_manager.load_section.return_value = "内容"
        agent.memory.get.return_value = {}

        # 先生成表格
        import asyncio
        asyncio.run(agent._phase7c_generate_table_templates())

        report = agent.generate_quality_report()
        assert report["has_tables_template"] is True
        assert report["table_count"] >= 3  # 至少3张表

    def test_report_shows_missing_tables(self, mock_agent_factory, empirical_project):
        """未生成表格时质量报告提示."""
        agent = mock_agent_factory(empirical_project)
        agent.file_manager.list_sections.return_value = ["ch1", "ch2", "ch3", "ch4", "ch5"]
        agent.file_manager.load_section.return_value = "内容"
        agent.memory.get.return_value = {}

        report = agent.generate_quality_report()
        assert report["has_tables_template"] is False
        assert report["table_count"] == 0
