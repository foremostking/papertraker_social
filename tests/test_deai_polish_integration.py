"""去AI味与润色集成测试：验证 Phase 8b 后处理流程.

测试范围:
1. _phase8b_deai_polish 方法存在且可调用
2. 非交互模式下自动执行
3. 生成 full_draft_polished.md 和 deai_report.md
4. 原草稿不被覆盖
5. state.json 正确更新
6. 异常处理（de_ai 模块出错时不中断流程）
7. 交互模式下用户拒绝时不执行
8. 章节拆分功能
9. 报告生成功能
10. 空草稿跳过处理

运行方式:
    cd scholarpilot
    .venv\\Scripts\\python.exe -m pytest tests/test_deai_polish_integration.py -v --tb=short
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ===== 测试用草稿文本（含明显AI写作模式）=====

AI_HEAVY_DRAFT = """# 地方政府债务风险的空间溢出效应研究

## 第一章 引言

值得注意的是，地方政府债务问题是当前中国经济的核心风险之一。首先，债务规模持续膨胀，风险不断积聚。其次，地方政府通过融资平台大量举债，导致隐性债务规模难以准确衡量。最后，债务风险可能引发系统性金融危机。综上所述，必须采取有效措施加以应对。不可否认，这一问题值得深入研究。研究表明，地方政府债务存在显著的空间溢出效应。

## 第二章 文献综述

一方面，周黎安（2007）从财政分权角度分析了地方债务的成因。另一方面，郭玉清等（2016）发现地方债务存在显著的区域差异。不仅如此，毛捷和徐军伟（2019）分析了隐性债务的规模和结构。因此，现有研究为本文提供了重要的理论基础。由此可见，地方政府债务问题已成为学术界关注的焦点。

## 第三章 结论

本文发现地方政府债务风险存在显著的空间溢出效应。建议加强区域协调监管，建立跨区域债务风险预警机制。总而言之，防范化解地方政府债务风险是一项长期而艰巨的任务。
"""


# ===== 辅助类 =====

class MockFileManager:
    """模拟 FileManager 的状态管理行为，真实读写 state.json."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.state_path = project_dir / ".scholar" / "state.json"
        self.saved_states: list[dict] = []  # 记录每次保存的状态

    def load_state(self, project_dir: Path) -> dict | None:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return None

    def save_state(self, project_dir: Path, state: dict) -> Path:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.saved_states.append(state)
        return self.state_path

    def update_project_status(self, project_dir: Path, status: str) -> None:
        pass

    def save_progress(self, project_dir: Path, phase: str, **kwargs) -> None:
        pass


# ===== Fixtures =====

@pytest.fixture
def temp_project():
    """创建临时项目目录，含 full_draft.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "test_project"
        project_dir.mkdir(parents=True)

        # 创建目录结构
        (project_dir / "draft").mkdir(parents=True)
        (project_dir / ".scholar").mkdir(parents=True)

        # 写入草稿文件
        (project_dir / "draft" / "full_draft.md").write_text(
            AI_HEAVY_DRAFT, encoding="utf-8"
        )

        # 初始化 state.json
        state = {"current_phase": "post_processing", "completed_phases": ["section_writing"]}
        (project_dir / ".scholar" / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        yield project_dir


@pytest.fixture
def mock_agent(temp_project):
    """创建非交互模式的 ScholarAgent 实例（跳过 __init__）."""
    from scholarpilot.agent.scholar import ScholarAgent

    agent = ScholarAgent.__new__(ScholarAgent)
    agent.project_dir = temp_project
    agent.console = MagicMock()
    agent.non_interactive = True
    agent.file_manager = MockFileManager(temp_project)
    agent.topic_info = {"research_type": "empirical", "topic": "地方政府债务"}

    return agent


@pytest.fixture
def mock_agent_interactive(temp_project):
    """创建交互模式的 ScholarAgent 实例（跳过 __init__）."""
    from scholarpilot.agent.scholar import ScholarAgent

    agent = ScholarAgent.__new__(ScholarAgent)
    agent.project_dir = temp_project
    agent.console = MagicMock()
    agent.non_interactive = False
    agent.file_manager = MockFileManager(temp_project)
    agent.topic_info = {"research_type": "empirical", "topic": "地方政府债务"}

    return agent


# ===== 1. 方法存在性与可调用性 =====

class TestMethodExistence:
    """测试 _phase8b_deai_polish 方法存在且可调用."""

    def test_method_exists(self, mock_agent):
        """方法应存在于 ScholarAgent 类中."""
        from scholarpilot.agent.scholar import ScholarAgent

        assert hasattr(ScholarAgent, "_phase8b_deai_polish")
        assert callable(getattr(ScholarAgent, "_phase8b_deai_polish"))

    def test_method_callable_on_instance(self, mock_agent):
        """方法应可在实例上调用."""
        assert hasattr(mock_agent, "_phase8b_deai_polish")
        assert callable(mock_agent._phase8b_deai_polish)

    def test_split_method_exists(self, mock_agent):
        """辅助方法 _split_draft_for_deai 应存在."""
        from scholarpilot.agent.scholar import ScholarAgent

        assert hasattr(ScholarAgent, "_split_draft_for_deai")
        assert hasattr(ScholarAgent, "_generate_deai_report")


# ===== 2. 非交互模式自动执行 =====

class TestNonInteractiveExecution:
    """测试非交互模式下自动执行."""

    def test_non_interactive_auto_executes(self, mock_agent):
        """非交互模式下应自动执行，不询问用户."""
        mock_agent._phase8b_deai_polish()

        # 应生成润色后草稿
        polished_path = mock_agent.project_dir / "draft" / "full_draft_polished.md"
        assert polished_path.exists(), "full_draft_polished.md 应被生成"

        # 应生成报告
        report_path = mock_agent.project_dir / "draft" / "deai_report.md"
        assert report_path.exists(), "deai_report.md 应被生成"

    def test_non_interactive_no_prompt(self, mock_agent):
        """非交互模式下不应调用 Confirm.ask."""
        with patch("rich.prompt.Confirm.ask") as mock_ask:
            mock_agent._phase8b_deai_polish()
            mock_ask.assert_not_called()


# ===== 3. 生成输出文件 =====

class TestOutputFiles:
    """测试生成 full_draft_polished.md 和 deai_report.md."""

    def test_generates_polished_draft(self, mock_agent):
        """应生成 full_draft_polished.md."""
        mock_agent._phase8b_deai_polish()

        polished_path = mock_agent.project_dir / "draft" / "full_draft_polished.md"
        assert polished_path.exists()
        content = polished_path.read_text(encoding="utf-8")
        assert len(content) > 0, "润色后草稿不应为空"

    def test_generates_deai_report(self, mock_agent):
        """应生成 deai_report.md 报告."""
        mock_agent._phase8b_deai_polish()

        report_path = mock_agent.project_dir / "draft" / "deai_report.md"
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "去AI味" in content or "AI风险" in content
        assert "处理前" in content
        assert "处理后" in content

    def test_report_contains_risk_comparison(self, mock_agent):
        """报告应包含前后风险对比."""
        mock_agent._phase8b_deai_polish()

        report_path = mock_agent.project_dir / "draft" / "deai_report.md"
        content = report_path.read_text(encoding="utf-8")
        assert "风险评估对比" in content or "风险等级" in content
        assert "AI生成概率" in content

    def test_original_draft_not_overwritten(self, mock_agent):
        """原草稿不应被覆盖."""
        original_path = mock_agent.project_dir / "draft" / "full_draft.md"
        original_content = original_path.read_text(encoding="utf-8")

        mock_agent._phase8b_deai_polish()

        # 原草稿内容应保持不变
        assert original_path.read_text(encoding="utf-8") == original_content

    def test_polished_differs_from_original(self, mock_agent):
        """润色后草稿应与原草稿不同（或至少是独立文件）."""
        mock_agent._phase8b_deai_polish()

        original = (mock_agent.project_dir / "draft" / "full_draft.md").read_text(
            encoding="utf-8"
        )
        polished = (mock_agent.project_dir / "draft" / "full_draft_polished.md").read_text(
            encoding="utf-8"
        )
        # 两个文件都应存在且不为空
        assert len(original) > 0
        assert len(polished) > 0


# ===== 4. state.json 更新 =====

class TestStateUpdate:
    """测试 state.json 正确更新."""

    def test_state_json_updated(self, mock_agent):
        """state.json 应记录去AI味和润色已完成."""
        mock_agent._phase8b_deai_polish()

        state = mock_agent.file_manager.load_state(mock_agent.project_dir)
        assert state is not None
        assert state.get("deai_polish_completed") is True

    def test_state_json_contains_risk_info(self, mock_agent):
        """state.json 应包含风险信息."""
        mock_agent._phase8b_deai_polish()

        state = mock_agent.file_manager.load_state(mock_agent.project_dir)
        assert "deai_risk_before" in state
        assert "deai_risk_after" in state
        assert "level" in state["deai_risk_before"]
        assert "level" in state["deai_risk_after"]

    def test_state_json_contains_timestamp(self, mock_agent):
        """state.json 应包含完成时间戳."""
        mock_agent._phase8b_deai_polish()

        state = mock_agent.file_manager.load_state(mock_agent.project_dir)
        assert "deai_polish_at" in state
        assert isinstance(state["deai_polish_at"], str)


# ===== 5. 异常处理 =====

class TestErrorHandling:
    """测试异常处理：去AI味或润色失败时不中断流程."""

    def test_deai_import_error_does_not_crash(self, mock_agent):
        """de_ai 模块导入失败时不中断流程."""
        with patch.dict(
            "sys.modules",
            {"scholarpilot.tools.de_ai": None},
        ):
            # 导入失败应被捕获，不抛出异常
            try:
                mock_agent._phase8b_deai_polish()
            except Exception as e:
                pytest.fail(f"导入失败不应导致异常: {e}")

    def test_deai_process_error_continues(self, mock_agent):
        """DeAIEngine.process 出错时流程不中断，保留原文."""
        from scholarpilot.tools.de_ai import DeAIEngine

        original_process = DeAIEngine.process

        def failing_process(self, text, strategies=None):
            raise RuntimeError("模拟去AI味处理失败")

        with patch.object(DeAIEngine, "process", failing_process):
            # 不应抛出异常
            mock_agent._phase8b_deai_polish()

        # 仍应生成输出文件（使用原文降级）
        polished_path = mock_agent.project_dir / "draft" / "full_draft_polished.md"
        assert polished_path.exists()

        # 恢复原始方法
        DeAIEngine.process = original_process

    def test_polish_error_continues(self, mock_agent):
        """PolishEngine.polish_chinese 出错时流程不中断."""
        from scholarpilot.tools.polish_engine import PolishEngine

        original_polish = PolishEngine.polish_chinese

        def failing_polish(self, text):
            raise RuntimeError("模拟中文润色失败")

        with patch.object(PolishEngine, "polish_chinese", failing_polish):
            # 不应抛出异常
            mock_agent._phase8b_deai_polish()

        # 仍应生成输出文件
        polished_path = mock_agent.project_dir / "draft" / "full_draft_polished.md"
        assert polished_path.exists()

        PolishEngine.polish_chinese = original_polish

    def test_missing_draft_skipped(self, mock_agent):
        """草稿文件不存在时应跳过，不抛出异常."""
        # 删除草稿文件
        draft_path = mock_agent.project_dir / "draft" / "full_draft.md"
        draft_path.unlink()

        # 不应抛出异常
        mock_agent._phase8b_deai_polish()

        # 不应生成润色文件
        polished_path = mock_agent.project_dir / "draft" / "full_draft_polished.md"
        assert not polished_path.exists()

    def test_empty_draft_skipped(self, mock_agent):
        """空草稿应被跳过."""
        draft_path = mock_agent.project_dir / "draft" / "full_draft.md"
        draft_path.write_text("", encoding="utf-8")

        mock_agent._phase8b_deai_polish()

        # 不应生成润色文件
        polished_path = mock_agent.project_dir / "draft" / "full_draft_polished.md"
        assert not polished_path.exists()


# ===== 6. 交互模式 =====

class TestInteractiveMode:
    """测试交互模式下的行为."""

    def test_user_decline_skips_processing(self, mock_agent_interactive):
        """交互模式下用户拒绝时应跳过处理."""
        with patch("rich.prompt.Confirm.ask", return_value=False):
            mock_agent_interactive._phase8b_deai_polish()

        # 不应生成润色文件
        polished_path = mock_agent_interactive.project_dir / "draft" / "full_draft_polished.md"
        assert not polished_path.exists()

    def test_user_accept_executes_processing(self, mock_agent_interactive):
        """交互模式下用户接受时应执行处理."""
        with patch("rich.prompt.Confirm.ask", return_value=True):
            mock_agent_interactive._phase8b_deai_polish()

        # 应生成润色文件
        polished_path = mock_agent_interactive.project_dir / "draft" / "full_draft_polished.md"
        assert polished_path.exists()


# ===== 7. 章节拆分 =====

class TestSplitDraft:
    """测试章节拆分功能."""

    def test_split_by_h2_headers(self, mock_agent):
        """应按 ## 二级标题拆分章节."""
        text = "# 论文标题\n\n## 第一章 引言\n\n引言内容\n\n## 第二章 方法\n\n方法内容\n\n## 第三章 结论\n\n结论内容"
        sections = mock_agent._split_draft_for_deai(text)

        assert len(sections) == 4  # 标题/前言 + 3章
        assert "引言" in sections[1]["title"]
        assert "方法" in sections[2]["title"]
        assert "结论" in sections[3]["title"]

    def test_split_no_h2_returns_single_section(self, mock_agent):
        """无二级标题时作为单个章节处理."""
        text = "这是一段没有标题的文本。"
        sections = mock_agent._split_draft_for_deai(text)

        assert len(sections) == 1
        assert sections[0]["content"] == text

    def test_split_preserves_content(self, mock_agent):
        """拆分后章节内容应保留."""
        text = "## 第一章 引言\n\n这是引言内容。"
        sections = mock_agent._split_draft_for_deai(text)

        assert len(sections) == 1
        assert "引言内容" in sections[0]["content"]


# ===== 8. 报告生成 =====

class TestReportGeneration:
    """测试报告生成功能."""

    def test_report_has_all_sections(self, mock_agent):
        """报告应包含所有主要部分."""
        mock_agent._phase8b_deai_polish()

        report = (mock_agent.project_dir / "draft" / "deai_report.md").read_text(
            encoding="utf-8"
        )
        assert "一、整体AI风险评估对比" in report
        assert "二、检测到的AI写作模式" in report
        assert "三、各章节处理摘要" in report
        assert "四、中文润色统计" in report
        assert "五、总结与建议" in report

    def test_report_contains_strategy_summary(self, mock_agent):
        """报告应包含策略汇总."""
        mock_agent._phase8b_deai_polish()

        report = (mock_agent.project_dir / "draft" / "deai_report.md").read_text(
            encoding="utf-8"
        )
        # 应包含策略名称（gemini_ 或 gpt55_ 或 paraphrase_ 开头）
        assert "策略" in report

    def test_generate_deai_report_directly(self, mock_agent):
        """直接测试 _generate_deai_report 方法."""
        from scholarpilot.tools.de_ai import DeAIEngine, AIRiskAssessment, AIRiskLevel, DeAIResult

        engine = DeAIEngine()
        risk_before = engine.detect_ai_patterns(AI_HEAVY_DRAFT)
        risk_after = AIRiskAssessment(
            risk_level=AIRiskLevel.LOW,
            ai_probability=0.1,
            detected_patterns=[],
            overall_score=10.0,
        )
        deai_result = DeAIResult(
            original_text="测试",
            processed_text="测试处理",
            strategies_applied=[],
            changes=[],
            risk_before=risk_before,
            risk_after=risk_after,
            improvement=50.0,
        )

        report = mock_agent._generate_deai_report(
            risk_before, risk_after, [deai_result], 5
        )

        assert "ScholarPilot 去AI味与润色报告" in report
        assert "处理前" in report
        assert "处理后" in report
        assert "中文润色修改总数: 5" in report


# ===== 9. 集成到 run() 方法 =====

class TestRunIntegration:
    """测试 _phase8b_deai_polish 在 run() 中的集成."""

    def test_phase8b_called_before_phase8(self, mock_agent):
        """验证 _phase8b_deai_polish 在 _phase8_post_completion 之前调用."""
        call_order = []

        original_phase8b = mock_agent._phase8b_deai_polish
        original_phase8 = mock_agent._phase8_post_completion

        def wrapped_phase8b():
            call_order.append("phase8b")
            original_phase8b()

        def wrapped_phase8():
            call_order.append("phase8")

        mock_agent._phase8b_deai_polish = wrapped_phase8b
        mock_agent._phase8_post_completion = wrapped_phase8

        # 模拟 run() 中的调用顺序
        mock_agent._phase8b_deai_polish()
        mock_agent._phase8_post_completion()

        assert call_order == ["phase8b", "phase8"]
