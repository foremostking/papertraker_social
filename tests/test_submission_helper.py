"""测试 SubmissionHelper 类的投稿辅助功能（P4/P5 新增功能）.

测试范围:
    1. _extract_paper_info: 从项目目录提取论文信息（SPEC.md/outline.json/full_draft.md）
    2. format_journal_recommendation: 格式化期刊推荐结果为 Markdown
    3. format_revision_plan: 格式化审稿修改计划为 Markdown
    4. _parse_json_response: 从 LLM 响应中解析 JSON
    5. recommend_journals/generate_cover_letter/plan_revision: LLM 调用方法（使用 mock）

运行方式:
    cd scholarpilot
    $env:PYTHONPATH = "src"
    python -m pytest tests/test_submission_helper.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scholarpilot.tools.submission_helper import SubmissionHelper


# ===== Fixtures =====

@pytest.fixture
def mock_gateway():
    """创建模拟 LLMGateway，chat 方法为 AsyncMock."""
    gateway = MagicMock()
    gateway.chat = AsyncMock()
    return gateway


@pytest.fixture
def complete_project(tmp_path):
    """创建完整的项目目录（含 SPEC.md/outline.json/draft/full_draft.md）."""
    # SPEC.md
    spec_content = """# 地方政府债务风险的空间溢出效应研究

## 研究主题
地方政府债务

## 研究类型
实证研究（empirical）

## 摘要
本文研究地方政府债务风险。
"""
    (tmp_path / "SPEC.md").write_text(spec_content, encoding="utf-8")

    # outline.json
    outline = {
        "title": "地方政府债务风险的空间溢出效应研究",
        "sections": [
            {"title": "第一章 引言", "word_count": 3000},
            {"title": "第二章 文献综述", "word_count": 4000},
            {"title": "第三章 实证分析", "word_count": 5000},
        ],
    }
    (tmp_path / "outline.json").write_text(
        json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # draft/full_draft.md
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    draft_content = """# 地方政府债务风险的空间溢出效应研究

摘要

本文研究地方政府债务风险的空间溢出效应，采用空间计量模型进行实证分析。研究发现存在显著空间溢出效应。

关键词

地方政府债务；空间溢出；财政风险

## 第一章 引言

正文内容。
"""
    (draft_dir / "full_draft.md").write_text(draft_content, encoding="utf-8")

    return tmp_path


# ===== _extract_paper_info 测试 =====

class TestExtractPaperInfo:
    """测试 _extract_paper_info 方法."""

    def test_extract_complete_project(self, mock_gateway, complete_project):
        """测试从完整项目目录提取论文信息."""
        helper = SubmissionHelper(mock_gateway)
        info = helper._extract_paper_info(complete_project)

        assert info["paper_title"] == "地方政府债务风险的空间溢出效应研究"
        assert "空间溢出效应" in info["abstract"]
        assert "地方政府债务" in info["keywords"]
        assert info["discipline"] == "经济学"  # 默认值
        assert info["research_type"] == "empirical"
        assert info["word_count"] > 0
        assert "第一章 引言" in info["paper_structure"]
        assert "第二章 文献综述" in info["paper_structure"]
        assert "约3000字" in info["paper_structure"]
        assert info["paper_content"]  # 非空
        assert info["data_status"] == "无数据（占位符模式）"

    def test_extract_with_data_files(self, mock_gateway, complete_project):
        """测试有数据文件时的 data_status."""
        data_dir = complete_project / "data"
        data_dir.mkdir()
        (data_dir / "sample.csv").write_text("col1,col2\n1,2", encoding="utf-8")
        (data_dir / "data.xlsx").write_bytes(b"fake xlsx content")

        helper = SubmissionHelper(mock_gateway)
        info = helper._extract_paper_info(complete_project)

        assert "有真实数据" in info["data_status"]
        assert "2个文件" in info["data_status"]

    def test_extract_with_state_json(self, mock_gateway, complete_project):
        """测试 state.json 中 deai_polish_completed 标记."""
        scholar_dir = complete_project / ".scholar"
        scholar_dir.mkdir()
        state = {"deai_polish_completed": True}
        (scholar_dir / "state.json").write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8"
        )

        helper = SubmissionHelper(mock_gateway)
        info = helper._extract_paper_info(complete_project)

        assert "已完成去AI味处理" in info["data_status"]

    def test_extract_theoretical_research_type(self, mock_gateway, tmp_path):
        """测试理论研究的 research_type 检测."""
        spec = """# 理论模型研究

## 研究类型
理论研究
"""
        (tmp_path / "SPEC.md").write_text(spec, encoding="utf-8")

        helper = SubmissionHelper(mock_gateway)
        info = helper._extract_paper_info(tmp_path)

        assert info["research_type"] == "theoretical"

    def test_extract_empty_project(self, mock_gateway, tmp_path):
        """测试空项目目录返回默认值."""
        helper = SubmissionHelper(mock_gateway)
        info = helper._extract_paper_info(tmp_path)

        assert info["paper_title"] == ""
        assert info["abstract"] == ""
        assert info["keywords"] == ""
        assert info["discipline"] == "经济学"
        assert info["research_type"] == "empirical"
        assert info["word_count"] == 0
        assert info["data_status"] == "无数据（占位符模式）"

    def test_extract_polished_draft(self, mock_gateway, tmp_path):
        """测试使用 polished 版本草稿（无 full_draft.md 时回退）."""
        draft_dir = tmp_path / "draft"
        draft_dir.mkdir()
        polished = """# 测试标题

摘要

这是润色后的摘要。

关键词

关键词1
"""
        (draft_dir / "full_draft_polished.md").write_text(polished, encoding="utf-8")

        helper = SubmissionHelper(mock_gateway)
        info = helper._extract_paper_info(tmp_path)

        assert "润色后的摘要" in info["abstract"]
        assert "关键词1" in info["keywords"]
        assert info["word_count"] > 0

    def test_extract_with_invalid_outline_json(self, mock_gateway, tmp_path):
        """测试 outline.json 格式错误时不崩溃."""
        (tmp_path / "outline.json").write_text("not a valid json {{{", encoding="utf-8")

        helper = SubmissionHelper(mock_gateway)
        info = helper._extract_paper_info(tmp_path)

        assert info["paper_structure"] == ""  # 默认空

    def test_extract_outline_without_sections(self, mock_gateway, tmp_path):
        """测试 outline.json 无 sections 字段时 paper_structure 为空."""
        outline = {"title": "测试论文"}  # 无 sections
        (tmp_path / "outline.json").write_text(
            json.dumps(outline, ensure_ascii=False), encoding="utf-8"
        )

        helper = SubmissionHelper(mock_gateway)
        info = helper._extract_paper_info(tmp_path)

        assert info["paper_structure"] == ""


# ===== format_journal_recommendation 测试 =====

class TestFormatJournalRecommendation:
    """测试 format_journal_recommendation 方法."""

    def test_format_complete_result(self, mock_gateway):
        """测试格式化完整的推荐结果."""
        result = {
            "recommendations": [
                {
                    "rank": 1,
                    "journal_name": "经济研究",
                    "publisher": "中国社会科学院",
                    "impact_factor": "无IF",
                    "indexing": ["CSSCI", "北大核心"],
                    "scope": "经济学综合",
                    "review_cycle": "3-6个月",
                    "publication_cycle": "6-12个月",
                    "acceptance_rate": "约5%",
                    "apc": "免版面费",
                    "oa_option": "否",
                    "match_score": 90,
                    "match_reasons": ["学科匹配", "质量匹配"],
                    "risks": ["录用率低"],
                    "recommendation_tier": "冲刺",
                    "submission_advice": "建议完善理论模型",
                },
            ],
            "tier_strategy": {
                "sprint": "经济研究",
                "match": "管理世界",
                "safety": "财经研究",
            },
            "summary": "总体推荐说明。",
        }

        helper = SubmissionHelper(mock_gateway)
        md = helper.format_journal_recommendation(result)

        assert "# 期刊推荐报告" in md
        assert "经济研究" in md
        assert "CSSCI" in md
        assert "冲刺" in md
        assert "学科匹配" in md
        assert "录用率低" in md
        assert "投稿梯队策略" in md
        assert "总体建议" in md

    def test_format_empty_recommendations_with_raw(self, mock_gateway):
        """测试无推荐结果但有原始响应."""
        result = {
            "recommendations": [],
            "raw_response": "LLM 出错了",
        }

        helper = SubmissionHelper(mock_gateway)
        md = helper.format_journal_recommendation(result)

        assert "未获取到推荐结果" in md
        assert "LLM 原始回复" in md
        assert "LLM 出错了" in md

    def test_format_empty_result(self, mock_gateway):
        """测试完全空的结果."""
        helper = SubmissionHelper(mock_gateway)
        md = helper.format_journal_recommendation({})

        assert "未获取到推荐结果" in md

    def test_format_recommendation_without_optional_fields(self, mock_gateway):
        """测试缺少可选字段时的容错."""
        result = {
            "recommendations": [
                {
                    "rank": 1,
                    "journal_name": "测试期刊",
                },
            ],
        }

        helper = SubmissionHelper(mock_gateway)
        md = helper.format_journal_recommendation(result)

        assert "测试期刊" in md
        assert "未知" in md  # 缺失字段显示"未知"


# ===== format_revision_plan 测试 =====

class TestFormatRevisionPlan:
    """测试 format_revision_plan 方法."""

    def test_format_complete_plan(self, mock_gateway):
        """测试格式化完整的修改计划."""
        result = {
            "revision_plans": [
                {
                    "comment_id": "C1",
                    "reviewer": "审稿人1",
                    "original_text": "请补充文献综述，现有文献不够充分。",
                    "summary": "补充文献综述",
                    "type": "minor",
                    "category": "文献",
                    "priority": "P1",
                    "modification_plan": {
                        "action": "补充",
                        "details": "增加3篇近5年文献",
                        "new_content_outline": "增加空间计量相关文献",
                        "content_to_remove": "",
                    },
                    "location": {"section": "第二章", "paragraph": "第3段"},
                    "estimated_workload": {
                        "time_hours": 4,
                        "word_count_change": "+500字",
                        "external_resources_needed": "需要检索新文献",
                    },
                    "dependencies": ["C2"],
                    "risks": "可能影响后续章节",
                    "response_strategy": "在回复中说明已补充",
                },
            ],
            "execution_order": ["1. 先修改C1", "2. 再修改C2"],
            "workload_summary": {
                "total_hours": 10,
                "total_word_change": "+1000字",
                "p0_count": 0,
                "p1_count": 1,
                "p2_count": 0,
                "external_resources": ["新文献"],
                "deadline_feasibility": "可行",
            },
            "global_strategy": "总体策略：先易后难。",
        }

        helper = SubmissionHelper(mock_gateway)
        md = helper.format_revision_plan(result)

        assert "# 审稿意见修改计划" in md
        assert "审稿人1" in md
        assert "补充文献综述" in md
        assert "P1" in md
        assert "修改操作" in md
        assert "新增内容要点" in md
        assert "依赖关系" in md
        assert "执行顺序" in md
        assert "工作量汇总" in md
        assert "总体修改策略" in md

    def test_format_empty_plans(self, mock_gateway):
        """测试无修改计划."""
        helper = SubmissionHelper(mock_gateway)
        md = helper.format_revision_plan({})

        assert "未获取到修改计划" in md

    def test_format_plan_with_long_original_text(self, mock_gateway):
        """测试原文过长时截断（>200字符）."""
        long_text = "这是一段很长的审稿意见。" * 50
        result = {
            "revision_plans": [
                {
                    "comment_id": "C1",
                    "reviewer": "审稿人1",
                    "original_text": long_text,
                    "summary": "测试截断",
                    "priority": "P0",
                },
            ],
        }

        helper = SubmissionHelper(mock_gateway)
        md = helper.format_revision_plan(result)

        assert "..." in md  # 截断标记
        assert "测试截断" in md

    def test_format_plan_minimal_fields(self, mock_gateway):
        """测试仅含必填字段的修改计划."""
        result = {
            "revision_plans": [
                {
                    "comment_id": "C2",
                    "summary": "修改图表",
                    "priority": "P2",
                },
            ],
        }

        helper = SubmissionHelper(mock_gateway)
        md = helper.format_revision_plan(result)

        assert "C2" in md
        assert "修改图表" in md
        assert "P2" in md


# ===== _parse_json_response 测试 =====

class TestParseJsonResponse:
    """测试 _parse_json_response 静态方法."""

    def test_parse_plain_json(self):
        """测试解析纯 JSON."""
        text = '{"key": "value"}'
        result = SubmissionHelper._parse_json_response(text)
        assert result == {"key": "value"}

    def test_parse_json_in_code_block(self):
        """测试解析 ```json 代码块."""
        text = '```json\n{"key": "value"}\n```'
        result = SubmissionHelper._parse_json_response(text)
        assert result == {"key": "value"}

    def test_parse_json_in_plain_code_block(self):
        """测试解析无 json 标记的代码块."""
        text = '```\n{"key": "value"}\n```'
        result = SubmissionHelper._parse_json_response(text)
        assert result == {"key": "value"}

    def test_parse_json_with_thinking_markers(self):
        """测试清理思考标记（[💭...]、[🔧...]）."""
        text = '[💭 思考中] {"key": "value"} [🔧 执行]'
        result = SubmissionHelper._parse_json_response(text)
        assert result == {"key": "value"}

    def test_parse_invalid_json(self):
        """测试无效 JSON 返回 None."""
        text = "这不是JSON"
        result = SubmissionHelper._parse_json_response(text)
        assert result is None

    def test_parse_json_embedded_in_text(self):
        """测试从文本中提取 JSON（花括号匹配）."""
        text = '前面有说明文字 {"key": "value"} 后面有文字'
        result = SubmissionHelper._parse_json_response(text)
        assert result == {"key": "value"}


# ===== LLM 调用方法测试（使用 mock）=====

class TestLLMMethods:
    """测试 LLM 调用方法（recommend_journals/generate_cover_letter/plan_revision）."""

    @pytest.mark.asyncio
    async def test_recommend_journals_success(self, mock_gateway, complete_project):
        """测试期刊推荐成功."""
        mock_response = {
            "recommendations": [
                {
                    "rank": 1,
                    "journal_name": "经济研究",
                    "indexing": ["CSSCI"],
                },
            ],
            "tier_strategy": {"sprint": "经济研究"},
        }
        mock_gateway.chat.return_value = json.dumps(mock_response, ensure_ascii=False)

        helper = SubmissionHelper(mock_gateway)
        result = await helper.recommend_journals(complete_project)

        assert "recommendations" in result
        assert len(result["recommendations"]) == 1
        assert result["recommendations"][0]["journal_name"] == "经济研究"
        mock_gateway.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recommend_journals_invalid_json(self, mock_gateway, complete_project):
        """测试 LLM 返回非 JSON 时的容错."""
        mock_gateway.chat.return_value = "这不是JSON格式"

        helper = SubmissionHelper(mock_gateway)
        result = await helper.recommend_journals(complete_project)

        assert result["recommendations"] == []
        assert "raw_response" in result
        assert "error" in result

    @pytest.mark.asyncio
    async def test_recommend_journals_with_json_code_block(self, mock_gateway, complete_project):
        """测试 LLM 返回 ```json 代码块包裹的 JSON."""
        mock_response = {
            "recommendations": [
                {"rank": 1, "journal_name": "管理世界"},
            ],
        }
        mock_gateway.chat.return_value = (
            "```json\n" + json.dumps(mock_response, ensure_ascii=False) + "\n```"
        )

        helper = SubmissionHelper(mock_gateway)
        result = await helper.recommend_journals(complete_project)

        assert len(result["recommendations"]) == 1
        assert result["recommendations"][0]["journal_name"] == "管理世界"

    @pytest.mark.asyncio
    async def test_generate_cover_letter(self, mock_gateway, complete_project):
        """测试生成 Cover Letter."""
        mock_gateway.chat.return_value = "尊敬的编辑，您好！\n\n特此投稿。"

        helper = SubmissionHelper(mock_gateway)
        letter = await helper.generate_cover_letter(
            complete_project, target_journal="经济研究"
        )

        assert "尊敬的编辑" in letter
        mock_gateway.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_cover_letter_strips_whitespace(self, mock_gateway, complete_project):
        """测试 Cover Letter 去除首尾空白."""
        mock_gateway.chat.return_value = "  \n  正文内容  \n  "

        helper = SubmissionHelper(mock_gateway)
        letter = await helper.generate_cover_letter(
            complete_project, target_journal="经济研究"
        )

        assert letter == "正文内容"

    @pytest.mark.asyncio
    async def test_plan_revision_success(self, mock_gateway, complete_project):
        """测试制定修改计划成功."""
        mock_response = {
            "revision_plans": [
                {
                    "comment_id": "C1",
                    "summary": "补充文献",
                    "priority": "P1",
                },
            ],
            "execution_order": ["1. 修改C1"],
        }
        mock_gateway.chat.return_value = json.dumps(mock_response, ensure_ascii=False)

        helper = SubmissionHelper(mock_gateway)
        result = await helper.plan_revision(
            complete_project, review_comments="请补充文献综述"
        )

        assert "revision_plans" in result
        assert len(result["revision_plans"]) == 1
        assert result["revision_plans"][0]["comment_id"] == "C1"

    @pytest.mark.asyncio
    async def test_plan_revision_invalid_json(self, mock_gateway, complete_project):
        """测试修改计划 LLM 返回非 JSON 时的容错."""
        mock_gateway.chat.return_value = "无效响应"

        helper = SubmissionHelper(mock_gateway)
        result = await helper.plan_revision(
            complete_project, review_comments="审稿意见"
        )

        assert result["revision_plans"] == []
        assert "error" in result
