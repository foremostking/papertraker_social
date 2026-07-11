"""定稿处理和质量报告功能验证测试.

测试范围:
1. 质量报告生成（字数、引用数、结构检查、期刊达标评估）
2. 质量报告展示
3. _merge_draft 标题修复
4. finalize 命令接口验证

运行方式:
    cd scholarpilot
    python -m pytest tests/test_finalize.py -v
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===== Fixtures =====

@pytest.fixture
def temp_project():
    """创建临时项目目录和草稿文件."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "test_project"
        project_dir.mkdir()

        # 创建 draft 目录
        draft_dir = project_dir / "draft"
        draft_dir.mkdir()

        # 创建 .scholar/memory.json 目录
        scholar_dir = project_dir / ".scholar"
        scholar_dir.mkdir()

        # 创建 outline.json
        outline = {
            "title": "地方政府债务风险的空间溢出效应研究",
            "keywords": ["地方政府债务", "空间溢出", "财政风险"],
            "sections": [
                {"title": "第一章 引言", "word_count": 3000},
                {"title": "第二章 文献综述", "word_count": 4000},
                {"title": "第三章 理论分析与研究设计", "word_count": 3000},
                {"title": "第四章 实证分析", "word_count": 4000},
                {"title": "第五章 结论", "word_count": 2000},
            ],
        }
        (project_dir / "outline.json").write_text(
            json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 创建一个模拟草稿文件（含摘要、5章正文、参考文献）
        draft_content = """# 地方政府债务风险的空间溢出效应研究

## 摘要

本文研究地方政府债务风险的空间溢出效应。采用空间计量模型，使用2010-2023年省级面板数据进行实证分析。研究发现地方政府债务存在显著的空间溢出效应。

**关键词**: 地方政府债务；空间溢出；财政风险

**JEL分类号**: H63, H74

---

## 第一章 引言

地方政府债务问题是当前中国经济的核心风险之一（毛捷和徐军伟，2019）。近年来随着经济下行压力加大，地方债务规模持续膨胀。本文旨在分析债务风险的空间溢出效应。

---

## 第二章 文献综述

关于地方政府债务的研究，周黎安（2007）从财政分权角度分析了地方债务的成因。郭玉清等（2016）发现地方债务存在显著的区域差异。Smith and Jones（2022）examined fiscal sustainability across regions.

---

## 第三章 理论分析与研究设计

本文构建空间面板模型，采用邻接矩阵和地理距离矩阵。数据来源为 Wind 数据库和财政部公开数据。

---

## 第四章 实证分析

实证结果表明，地方政府债务存在显著的空间溢出效应。空间自相关系数为0.45，在1%水平显著。稳健性检验结果一致。

---

## 第五章 结论

本文研究发现地方政府债务风险存在显著的空间溢出效应，建议加强区域协同治理。

---

## 参考文献

[1] 毛捷,徐军伟.地方政府债务风险的空间溢出效应[J].经济研究,2019(07):102-115.
[2] 周黎安.中国地方债务的成因分析[J].经济研究,2007(05):33-50.
[3] 郭玉清,等.财政分权与地方政府债务[J].管理世界,2016(08):55-67.
[4] Smith J, Jones B. Fiscal sustainability across regions[J]. Journal of Public Economics, 2022, 200: 104-120.
[5] Brown A. Government debt and growth[J]. American Economic Review, 2023, 113(5): 1-28.
"""
        (draft_dir / "full_draft.md").write_text(draft_content, encoding="utf-8")

        # 创建 references.md
        ref_content = """## 参考文献

[1] 毛捷,徐军伟.地方政府债务风险的空间溢出效应[J].经济研究,2019(07):102-115.
[2] 周黎安.中国地方债务的成因分析[J].经济研究,2007(05):33-50.
[3] 郭玉清,等.财政分权与地方政府债务[J].管理世界,2016(08):55-67.
[4] Smith J, Jones B. Fiscal sustainability across regions[J]. Journal of Public Economics, 2022, 200: 104-120.
[5] Brown A. Government debt and growth[J]. American Economic Review, 2023, 113(5): 1-28.
"""
        (draft_dir / "references.md").write_text(ref_content, encoding="utf-8")

        yield project_dir


@pytest.fixture
def mock_agent(temp_project):
    """创建模拟的 ScholarAgent 实例（不初始化引擎）."""
    from scholarpilot.agent.scholar import ScholarAgent
    agent = ScholarAgent.__new__(ScholarAgent)
    agent.project_dir = temp_project
    agent.console = MagicMock()

    # 模拟 file_manager
    agent.file_manager = MagicMock()
    agent.file_manager.list_sections.return_value = [
        "chapter1_introduction.md",
        "chapter2_literature.md",
        "chapter3_theory.md",
        "chapter4_empirical.md",
        "chapter5_conclusion.md",
    ]
    agent.file_manager.load_section.return_value = "章节内容"

    # 模拟 memory
    agent.memory = MagicMock()
    agent.memory.get.return_value = {
        "total": 5,
        "verified": 4,
        "unverified": 1,
    }

    # 模拟 config
    agent.config = MagicMock()

    return agent


# ===== 1. 质量报告生成测试 =====

class TestQualityReportGeneration:
    """测试质量报告生成."""

    def test_report_has_all_fields(self, mock_agent):
        """报告包含所有必要字段."""
        report = mock_agent.generate_quality_report()

        assert "word_count" in report
        assert "chinese_chars" in report
        assert "english_words" in report
        assert "chapter_count" in report
        assert "reference_count" in report
        assert "verified_count" in report
        assert "unverified_count" in report
        assert "has_abstract" in report
        assert "has_keywords" in report
        assert "has_jel" in report
        assert "structure" in report
        assert "structure_complete" in report
        assert "missing_parts" in report
        assert "assessment" in report

    def test_word_count_positive(self, mock_agent):
        """字数统计为正数."""
        report = mock_agent.generate_quality_report()
        assert report["word_count"] > 0
        assert report["chinese_chars"] > 0
        assert report["english_words"] > 0

    def test_reference_count(self, mock_agent):
        """参考文献数量正确."""
        report = mock_agent.generate_quality_report()
        # 应该有 5 条参考文献
        assert report["reference_count"] == 5

    def test_structure_complete(self, mock_agent):
        """结构完整性检查."""
        report = mock_agent.generate_quality_report()
        structure = report["structure"]
        assert "引言/绪论" in structure
        assert "文献综述" in structure
        assert "理论分析/研究设计" in structure
        assert "实证分析" in structure
        assert "结论" in structure
        # 草稿包含所有部分
        assert report["structure_complete"] is True
        assert len(report["missing_parts"]) == 0

    def test_has_abstract_keywords_jel(self, mock_agent):
        """摘要、关键词、JEL分类号检测."""
        report = mock_agent.generate_quality_report()
        assert report["has_abstract"] is True
        assert report["has_keywords"] is True
        assert report["has_jel"] is True

    def test_verified_count_from_memory(self, mock_agent):
        """验证数从记忆中获取."""
        report = mock_agent.generate_quality_report()
        assert report["verified_count"] == 4
        assert report["unverified_count"] == 1

    def test_assessment_has_all_categories(self, mock_agent):
        """评估包含所有类别."""
        report = mock_agent.generate_quality_report()
        assessment = report["assessment"]
        assert "word_count" in assessment
        assert "references" in assessment
        assert "verification" in assessment
        assert "structure" in assessment


# ===== 2. 结构缺失检测测试 =====

class TestStructureDetection:
    """测试结构缺失检测."""

    def test_missing_empirical(self, mock_agent, temp_project):
        """缺失实证分析章节."""
        draft_path = temp_project / "draft" / "full_draft.md"
        content = draft_path.read_text(encoding="utf-8")
        # 删除实证分析部分
        content = content.replace("第四章 实证分析", "第四章 分析")
        content = content.replace("实证结果表明", "结果表明")
        content = content.replace("实证分析", "分析")
        draft_path.write_text(content, encoding="utf-8")

        report = mock_agent.generate_quality_report()
        assert "实证分析" in report["missing_parts"]
        assert report["structure_complete"] is False

    def test_missing_conclusion(self, mock_agent, temp_project):
        """缺失结论章节."""
        draft_path = temp_project / "draft" / "full_draft.md"
        content = draft_path.read_text(encoding="utf-8")
        # 替换所有结论相关关键词为非关键词
        content = content.replace("第五章 结论", "第五章 展望与政策建议")
        content = content.replace("结论", "展望")
        content = content.replace("结语", "展望")
        content = content.replace("总结", "展望")
        content = content.replace("Conclusion", "Outlook")
        draft_path.write_text(content, encoding="utf-8")

        report = mock_agent.generate_quality_report()
        assert "结论" in report["missing_parts"]


# ===== 3. 期刊达标评估测试 =====

class TestJournalReadiness:
    """测试期刊达标评估."""

    def test_word_count_assessment_levels(self, mock_agent):
        """字数评估分级正确."""
        # 模拟不同字数
        for count, expected_keyword in [(20000, "充足"), (12000, "基本达标"), (7000, "偏少"), (3000, "不足")]:
            report = mock_agent.generate_quality_report()
            report["word_count"] = count
            assessment = mock_agent._assess_journal_readiness(report)
            assert expected_keyword in assessment["word_count"]

    def test_reference_count_assessment(self, mock_agent):
        """参考文献评估分级正确."""
        for count, expected_keyword in [(30, "充足"), (20, "偏少"), (5, "不足"), (0, "缺失")]:
            report = mock_agent.generate_quality_report()
            report["reference_count"] = count
            assessment = mock_agent._assess_journal_readiness(report)
            assert expected_keyword in assessment["references"]

    def test_verification_rate_assessment(self, mock_agent):
        """验证率评估分级正确."""
        for verified, total, expected_keyword in [
            (8, 10, "良好"),  # 80%
            (6, 10, "一般"),  # 60%
            (3, 10, "较差"),  # 30%
            (0, 0, "未验证"),
        ]:
            report = mock_agent.generate_quality_report()
            report["verified_count"] = verified
            report["unverified_count"] = total - verified
            assessment = mock_agent._assess_journal_readiness(report)
            assert expected_keyword in assessment["verification"]


# ===== 4. _merge_draft 标题修复测试 =====

class TestMergeDraftTitle:
    """测试 _merge_draft 使用实际论文标题."""

    def test_merge_draft_uses_paper_title(self, mock_agent):
        """合并草稿使用 outline.json 中的标题."""
        mock_agent._merge_draft()

        draft_path = mock_agent.project_dir / "draft" / "full_draft.md"
        content = draft_path.read_text(encoding="utf-8")

        # 应该以实际标题开头，而不是"论文草稿"
        assert content.startswith("# 地方政府债务风险的空间溢出效应研究")
        assert "论文草稿" not in content.split("\n")[0]

    def test_merge_draft_fallback_title(self, mock_agent, temp_project):
        """无 outline.json 时回退到默认标题."""
        # 删除 outline.json
        (temp_project / "outline.json").unlink()

        mock_agent._merge_draft()

        draft_path = temp_project / "draft" / "full_draft.md"
        content = draft_path.read_text(encoding="utf-8")

        # 应该使用默认标题
        assert content.startswith("# 论文草稿")


# ===== 5. finalize 接口测试 =====

class TestFinalizeInterface:
    """测试 finalize 方法接口."""

    @pytest.mark.asyncio
    async def test_finalize_no_draft(self, mock_agent, temp_project):
        """草稿不存在时返回空字典."""
        # 删除草稿
        (temp_project / "draft" / "full_draft.md").unlink()

        result = await mock_agent.finalize(abstract=True, citations=True)
        assert result == {}

    @pytest.mark.asyncio
    async def test_finalize_report_only(self, mock_agent):
        """不执行操作时只生成质量报告."""
        # Mock 7a/7b 方法
        mock_agent._phase7a_generate_abstract = AsyncMock()
        mock_agent._phase7b_citation_management = AsyncMock()

        result = await mock_agent.finalize(abstract=False, citations=False)

        # 不应该调用摘要和引用方法
        mock_agent._phase7a_generate_abstract.assert_not_called()
        mock_agent._phase7b_citation_management.assert_not_called()

        # 应该返回质量报告
        assert "word_count" in result
        assert "assessment" in result

    @pytest.mark.asyncio
    async def test_finalize_abstract_only(self, mock_agent):
        """仅生成摘要."""
        mock_agent._phase7a_generate_abstract = AsyncMock()
        mock_agent._phase7b_citation_management = AsyncMock()

        result = await mock_agent.finalize(abstract=True, citations=False)

        mock_agent._phase7a_generate_abstract.assert_called_once()
        mock_agent._phase7b_citation_management.assert_not_called()
        assert "word_count" in result

    @pytest.mark.asyncio
    async def test_finalize_citations_only(self, mock_agent):
        """仅管理引用."""
        mock_agent._phase7a_generate_abstract = AsyncMock()
        mock_agent._phase7b_citation_management = AsyncMock()

        result = await mock_agent.finalize(abstract=False, citations=True)

        mock_agent._phase7a_generate_abstract.assert_not_called()
        mock_agent._phase7b_citation_management.assert_called_once()
        assert "word_count" in result

    @pytest.mark.asyncio
    async def test_finalize_both(self, mock_agent):
        """同时生成摘要和管理引用."""
        mock_agent._phase7a_generate_abstract = AsyncMock()
        mock_agent._phase7b_citation_management = AsyncMock()

        result = await mock_agent.finalize(abstract=True, citations=True)

        mock_agent._phase7a_generate_abstract.assert_called_once()
        mock_agent._phase7b_citation_management.assert_called_once()
        assert "assessment" in result


# ===== 6. 展示方法测试 =====

class TestDisplayQualityReport:
    """测试质量报告展示方法."""

    def test_display_does_not_crash(self, mock_agent):
        """展示方法不崩溃."""
        report = mock_agent.generate_quality_report()
        # 应该不抛出异常
        mock_agent._display_quality_report(report)

    def test_display_with_empty_report(self, mock_agent):
        """空报告展示不崩溃."""
        empty_report: dict = {}
        # 应该不抛出异常
        mock_agent._display_quality_report(empty_report)

    def test_display_with_missing_parts(self, mock_agent, temp_project):
        """有缺失部分时展示不崩溃."""
        draft_path = temp_project / "draft" / "full_draft.md"
        content = draft_path.read_text(encoding="utf-8")
        # 彻底移除所有实证相关关键词
        content = content.replace("实证分析", "数据分析")
        content = content.replace("实证研究", "数据分析")
        content = content.replace("实证结果", "数据结果")
        content = content.replace("Empirical", "Data")
        content = content.replace("回归结果", "模型输出")
        draft_path.write_text(content, encoding="utf-8")

        report = mock_agent.generate_quality_report()
        assert len(report["missing_parts"]) > 0
        mock_agent._display_quality_report(report)
