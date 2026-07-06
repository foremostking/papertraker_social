"""文献动态订阅功能验证测试.

测试范围:
1. 全局文献库订阅字段与种子管理
2. 引用追踪增量检测
3. Feed 历史记录
4. FeedManager 去重逻辑
5. FeedManager 论文转换
6. 引擎层方法存在性验证
7. 配置项验证

运行方式:
    cd scholarpilot
    python -m pytest tests/test_feed.py -v
"""

import json
import tempfile
from pathlib import Path
from datetime import datetime

import pytest


# ===== Fixtures =====

@pytest.fixture
def temp_library():
    """创建临时全局文献库."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from scholarpilot.utils.library import GlobalLibrary
        lib = GlobalLibrary(Path(tmpdir))
        yield lib


@pytest.fixture
def library_with_papers(temp_library):
    """创建包含测试文献的全局文献库."""
    lib = temp_library
    # 添加 5 篇测试文献
    papers = [
        {
            "title": "地方政府债务风险的空间溢出效应研究",
            "authors": ["张三", "李四"],
            "year": 2023,
            "journal": "经济研究",
            "doi": "10.1234/test1",
            "abstract": "本文研究地方政府债务风险的空间溢出效应",
            "source": "cnki",
            "language": "zh",
            "citation_count": 50,
        },
        {
            "title": "Fiscal Policy and Economic Growth in China",
            "authors": ["John Smith", "Wang Wei"],
            "year": 2022,
            "journal": "Journal of Finance",
            "doi": "10.5678/test2",
            "abstract": "This paper examines fiscal policy effects",
            "source": "semantic_scholar",
            "language": "en",
            "citation_count": 120,
            "ss_paper_id": "abc123def456",
        },
        {
            "title": "财政分权与地方政府行为",
            "authors": ["王五"],
            "year": 2021,
            "journal": "管理世界",
            "doi": "10.9012/test3",
            "abstract": "财政分权体制下地方政府行为分析",
            "source": "ncpssd",
            "language": "zh",
            "citation_count": 30,
        },
        {
            "title": "Government Debt and Fiscal Sustainability",
            "authors": ["Alice Brown", "Bob Jones"],
            "year": 2024,
            "journal": "American Economic Review",
            "doi": "10.3456/test4",
            "abstract": "We analyze government debt sustainability",
            "source": "openalex",
            "language": "en",
            "citation_count": 15,
            "openalex_id": "W2741809807",
        },
        {
            "title": "中国地方政府债务的成因与治理",
            "authors": ["赵六", "钱七"],
            "year": 2020,
            "journal": "金融研究",
            "doi": "10.7890/test5",
            "abstract": "分析地方政府债务成因",
            "source": "cnki",
            "language": "zh",
            "citation_count": 8,
        },
    ]
    for paper in papers:
        lib.add_paper(paper, project_name="test_project")
    return lib


# ===== 1. 文献库订阅字段测试 =====

class TestLibrarySubscriptionFields:
    """测试文献记录中的订阅相关字段."""

    def test_new_paper_has_subscription_fields(self, temp_library):
        """新添加的文献应包含所有订阅字段."""
        lib = temp_library
        paper = lib.add_paper({
            "title": "测试论文",
            "year": 2024,
        })

        assert paper["is_seed"] is False
        assert paper["subscribed_at"] == ""
        assert paper["known_citation_ids"] == []
        assert paper["last_citation_count"] == 0
        assert paper["last_checked_citations_at"] == ""
        assert paper["ss_paper_id"] == ""
        assert paper["openalex_id"] == ""

    def test_existing_paper_gets_subscription_fields(self, library_with_papers):
        """已有文献在更新时应获得订阅字段."""
        lib = library_with_papers
        # 查找已有文献并更新
        existing = lib.find_paper("地方政府债务风险的空间溢出效应研究", year=2023)
        assert existing is not None
        # 更新（添加新信息）
        lib.add_paper({"title": "地方政府债务风险的空间溢出效应研究", "year": 2023, "doi": "10.1234/test1"})
        updated = lib.find_paper("地方政府债务风险的空间溢出效应研究", year=2023)
        assert updated["is_seed"] is False
        assert "known_citation_ids" in updated
        assert "last_citation_count" in updated


# ===== 2. 种子论文管理测试 =====

class TestSeedManagement:
    """测试种子论文管理功能."""

    def test_mark_as_seed(self, library_with_papers):
        """标记种子论文."""
        lib = library_with_papers
        paper = lib.find_paper("Fiscal Policy and Economic Growth in China", year=2022)
        assert paper is not None

        result = lib.mark_as_seed(paper["id"], ss_paper_id="abc123def456")
        assert result is True

        seeds = lib.get_seed_papers()
        assert len(seeds) == 1
        assert seeds[0]["title"] == "Fiscal Policy and Economic Growth in China"
        assert seeds[0]["is_seed"] is True
        assert seeds[0]["subscribed_at"] != ""
        assert seeds[0]["ss_paper_id"] == "abc123def456"

    def test_unmark_seed(self, library_with_papers):
        """取消种子标记."""
        lib = library_with_papers
        paper = lib.find_paper("Fiscal Policy and Economic Growth in China", year=2022)
        lib.mark_as_seed(paper["id"])

        result = lib.unmark_seed(paper["id"])
        assert result is True

        seeds = lib.get_seed_papers()
        assert len(seeds) == 0

    def test_auto_select_seeds(self, library_with_papers):
        """自动选取种子论文."""
        lib = library_with_papers
        selected = lib.auto_select_seeds(count=3, min_citations=5)

        assert len(selected) <= 3
        assert len(selected) > 0
        for paper in selected:
            assert paper["is_seed"] is True
            assert paper["subscribed_at"] != ""

        # 验证按引用数排序（第一篇应该引用数最高）
        if len(selected) >= 2:
            first_citations = selected[0].get("last_citation_count", 0) or selected[0].get("citation_count", 0)
            second_citations = selected[1].get("last_citation_count", 0) or selected[1].get("citation_count", 0)
            assert first_citations >= second_citations

    def test_auto_select_respects_existing_seeds(self, library_with_papers):
        """自动选取不会重复选取已标记的种子."""
        lib = library_with_papers
        # 先手动标记一篇
        paper = lib.find_paper("Fiscal Policy and Economic Growth in China", year=2022)
        lib.mark_as_seed(paper["id"])

        # 自动选取
        selected = lib.auto_select_seeds(count=3, min_citations=5)
        # 已标记的不应出现在 selected 中
        for p in selected:
            assert p["id"] != paper["id"]

        # 但总种子数应包含手动+自动
        all_seeds = lib.get_seed_papers()
        assert len(all_seeds) == 1 + len(selected)

    def test_set_external_ids(self, library_with_papers):
        """设置外部 API ID."""
        lib = library_with_papers
        paper = lib.find_paper("地方政府债务风险的空间溢出效应研究", year=2023)

        result = lib.set_external_ids(
            paper["id"],
            ss_paper_id="ss_test_123",
            openalex_id="W1234567890",
        )
        assert result is True

        updated = lib.get_paper(paper["id"])
        assert updated["ss_paper_id"] == "ss_test_123"
        assert updated["openalex_id"] == "W1234567890"


# ===== 3. 引用追踪增量检测测试 =====

class TestCitationTracking:
    """测试引用追踪增量检测."""

    def test_first_check_all_new(self, library_with_papers):
        """首次检查：所有引用都是新的."""
        lib = library_with_papers
        paper = lib.find_paper("Fiscal Policy and Economic Growth in China", year=2022)
        lib.mark_as_seed(paper["id"])

        # 模拟获取引用列表
        citing_ids = ["c1", "c2", "c3", "c4", "c5"]
        diff = lib.update_citation_tracking(paper["id"], citing_ids, citation_count=5)

        assert diff["total_new"] == "5"
        assert len(diff["new_ids"].split(",")) == 5

        # 验证状态已更新
        updated = lib.get_paper(paper["id"])
        assert updated["known_citation_ids"] == ["c1", "c2", "c3", "c4", "c5"]
        assert updated["last_citation_count"] == 5
        assert updated["last_checked_citations_at"] != ""

    def test_incremental_detection(self, library_with_papers):
        """增量检测：只返回新增引用."""
        lib = library_with_papers
        paper = lib.find_paper("Fiscal Policy and Economic Growth in China", year=2022)
        lib.mark_as_seed(paper["id"])

        # 第一次检查
        lib.update_citation_tracking(paper["id"], ["c1", "c2", "c3"], citation_count=3)

        # 第二次检查：新增 c4, c5
        diff = lib.update_citation_tracking(
            paper["id"], ["c1", "c2", "c3", "c4", "c5"], citation_count=5
        )

        assert diff["total_new"] == "2"
        new_ids = set(diff["new_ids"].split(","))
        assert new_ids == {"c4", "c5"}

    def test_no_new_citations(self, library_with_papers):
        """无新增引用."""
        lib = library_with_papers
        paper = lib.find_paper("Fiscal Policy and Economic Growth in China", year=2022)
        lib.mark_as_seed(paper["id"])

        lib.update_citation_tracking(paper["id"], ["c1", "c2"], citation_count=2)

        # 再次检查相同列表
        diff = lib.update_citation_tracking(paper["id"], ["c1", "c2"], citation_count=2)
        assert diff["total_new"] == "0"
        assert diff["new_ids"] == ""

    def test_get_papers_by_external_id(self, library_with_papers):
        """按外部 ID 查找文献."""
        lib = library_with_papers
        paper = lib.find_paper("Government Debt and Fiscal Sustainability", year=2024)
        lib.set_external_ids(paper["id"], openalex_id="W2741809807")

        results = lib.get_papers_by_external_id(openalex_id="W2741809807")
        assert len(results) == 1
        assert results[0]["title"] == "Government Debt and Fiscal Sustainability"


# ===== 4. Feed 历史记录测试 =====

class TestFeedHistory:
    """测试 Feed 推送历史."""

    def test_record_and_retrieve(self, temp_library):
        """记录并获取 feed 历史."""
        lib = temp_library
        recommendations = [
            {"title": "Paper A", "year": 2024, "source": "openalex", "strategy": "citation"},
            {"title": "Paper B", "year": 2023, "source": "ncpssd", "strategy": "topic"},
        ]
        lib.record_feed_result(
            strategy="citation,topic",
            seed_count=5,
            recommendations=recommendations,
        )

        history = lib.get_feed_history()
        assert len(history) == 1
        assert history[0]["strategy"] == "citation,topic"
        assert history[0]["seed_count"] == 5
        assert history[0]["recommendation_count"] == 2
        assert len(history[0]["recommendations"]) == 2

    def test_history_ordering(self, temp_library):
        """历史按时间倒序排列."""
        lib = temp_library
        lib.record_feed_result(strategy="citation", seed_count=1, recommendations=[])
        lib.record_feed_result(strategy="topic", seed_count=2, recommendations=[])

        history = lib.get_feed_history()
        assert len(history) == 2
        # 最新的在前
        assert history[0]["strategy"] == "topic"

    def test_history_limit(self, temp_library):
        """历史记录限制."""
        lib = temp_library
        for i in range(5):
            lib.record_feed_result(
                strategy=f"strategy_{i}",
                seed_count=i,
                recommendations=[],
            )

        history = lib.get_feed_history(limit=3)
        assert len(history) == 3

    def test_get_last_feed_time(self, temp_library):
        """获取上次推送时间."""
        lib = temp_library
        assert lib.get_last_feed_time() == ""

        lib.record_feed_result(strategy="citation", seed_count=1, recommendations=[])
        last_time = lib.get_last_feed_time()
        assert last_time != ""
        assert "T" in last_time  # ISO format

    def test_history_persistence(self, temp_library):
        """历史记录持久化到磁盘."""
        lib = temp_library
        lib.record_feed_result(
            strategy="citation",
            seed_count=3,
            recommendations=[{"title": "Test", "year": 2024}],
        )

        # 重新加载
        from scholarpilot.utils.library import GlobalLibrary
        lib2 = GlobalLibrary(lib.library_dir)
        history = lib2.get_feed_history()
        assert len(history) == 1
        assert history[0]["strategy"] == "citation"


# ===== 5. FeedManager 去重测试 =====

class TestFeedDeduplication:
    """测试 FeedManager 去重逻辑."""

    def test_dedup_removes_duplicates(self, library_with_papers):
        """去重移除列表内重复."""
        from scholarpilot.agent.feed import FeedManager
        from scholarpilot.config import get_settings

        lib = library_with_papers
        settings = get_settings()
        manager = FeedManager(lib, settings)

        recommendations = [
            {"title": "New Paper A", "authors": ["X"], "year": 2024, "ss_paper_id": "ss1"},
            {"title": "New Paper A", "authors": ["X"], "year": 2024, "ss_paper_id": "ss1"},  # 重复
            {"title": "New Paper B", "authors": ["Y"], "year": 2023, "openalex_id": "W1"},
        ]

        result = manager._deduplicate(recommendations)
        assert len(result) == 2

    def test_dedup_removes_library_papers(self, library_with_papers):
        """去重移除已在全局库中的文献."""
        from scholarpilot.agent.feed import FeedManager
        from scholarpilot.config import get_settings

        lib = library_with_papers
        settings = get_settings()
        manager = FeedManager(lib, settings)

        recommendations = [
            {"title": "Fiscal Policy and Economic Growth in China", "year": 2022},  # 已在库中
            {"title": "Brand New Paper", "year": 2024, "ss_paper_id": "new_ss"},
        ]

        result = manager._deduplicate(recommendations)
        assert len(result) == 1
        assert result[0]["title"] == "Brand New Paper"

    def test_dedup_by_external_id(self, library_with_papers):
        """按外部 ID 去重."""
        from scholarpilot.agent.feed import FeedManager
        from scholarpilot.config import get_settings

        lib = library_with_papers
        settings = get_settings()
        manager = FeedManager(lib, settings)

        # 库中已有 openalex_id=W2741809807 的文献
        recommendations = [
            {"title": "Different Title Same ID", "openalex_id": "W2741809807"},
            {"title": "Truly New Paper", "openalex_id": "W9999999999"},
        ]

        result = manager._deduplicate(recommendations)
        assert len(result) == 1
        assert result[0]["title"] == "Truly New Paper"


# ===== 6. FeedManager 论文转换测试 =====

class TestPaperConversion:
    """测试论文对象到推荐字典的转换."""

    def test_ss_paper_conversion(self):
        """SS 论文转换."""
        from scholarpilot.agent.feed import FeedManager
        from scholarpilot.mcp.servers.semantic_scholar import SSPaper

        manager = FeedManager.__new__(FeedManager)  # 不调用 __init__
        paper = SSPaper(
            paper_id="ss_abc",
            title="Test Paper",
            abstract="Test abstract",
            year=2024,
            authors=["Author A"],
            citation_count=50,
            influential_citation_count=5,
            doi="10.1234/test",
            url="https://example.com",
        )

        rec = manager._ss_paper_to_recommendation(paper, "citation", "Seed Title")

        assert rec["title"] == "Test Paper"
        assert rec["strategy"] == "citation"
        assert rec["seed_title"] == "Seed Title"
        assert rec["ss_paper_id"] == "ss_abc"
        assert rec["source"] == "semantic_scholar"
        assert rec["language"] == "en"
        assert rec["score"] == 50 + 5 * 5  # citation_count + influential * 5
        assert rec["reason"] == ""

    def test_oa_paper_conversion(self):
        """OpenAlex 论文转换."""
        from scholarpilot.agent.feed import FeedManager
        from scholarpilot.mcp.servers.openalex import OpenAlexPaper

        manager = FeedManager.__new__(FeedManager)
        paper = OpenAlexPaper(
            work_id="W123456",
            title="OpenAlex Paper",
            abstract="Abstract here",
            year=2023,
            authors=["Author B"],
            cited_by_count=30,
            doi="10.5678/oa",
            url="https://openalex.org/W123456",
        )

        rec = manager._oa_paper_to_recommendation(paper, "topic", "Seed Paper")

        assert rec["title"] == "OpenAlex Paper"
        assert rec["strategy"] == "topic"
        assert rec["openalex_id"] == "W123456"
        assert rec["source"] == "openalex"
        assert rec["score"] == 30

    def test_ncpssd_paper_conversion(self):
        """NCPSSD 论文转换."""
        from scholarpilot.agent.feed import FeedManager
        from scholarpilot.mcp.servers.ncpssd import NCPSSDPaper

        manager = FeedManager.__new__(FeedManager)
        paper = NCPSSDPaper(
            title="中文论文测试",
            authors=["张三"],
            journal="经济研究",
            year="2024",
            abstract="中文摘要",
            download_count=100,
            read_count=50,
        )

        rec = manager._ncpssd_paper_to_recommendation(paper, "topic", "种子论文")

        assert rec["title"] == "中文论文测试"
        assert rec["strategy"] == "topic"
        assert rec["source"] == "ncpssd"
        assert rec["language"] == "zh"
        assert rec["score"] == 100 + 50 * 2  # download + read * 2
        assert rec["journal"] == "经济研究"


# ===== 7. 引擎方法存在性验证 =====

class TestEngineMethods:
    """验证引擎层新增方法的存在性和签名."""

    def test_ss_engine_has_get_citations(self):
        """SemanticScholarEngine 应有 get_citations 方法."""
        from scholarpilot.mcp.servers.semantic_scholar import SemanticScholarEngine
        assert hasattr(SemanticScholarEngine, "get_citations")
        assert callable(getattr(SemanticScholarEngine, "get_citations"))

    def test_ss_engine_has_get_references(self):
        """SemanticScholarEngine 应有 get_references 方法."""
        from scholarpilot.mcp.servers.semantic_scholar import SemanticScholarEngine
        assert hasattr(SemanticScholarEngine, "get_references")

    def test_openalex_engine_has_get_citing_works(self):
        """OpenAlexEngine 应有 get_citing_works 方法."""
        from scholarpilot.mcp.servers.openalex import OpenAlexEngine
        assert hasattr(OpenAlexEngine, "get_citing_works")
        assert callable(getattr(OpenAlexEngine, "get_citing_works"))

    def test_openalex_engine_has_get_referenced_works(self):
        """OpenAlexEngine 应有 get_referenced_works 方法."""
        from scholarpilot.mcp.servers.openalex import OpenAlexEngine
        assert hasattr(OpenAlexEngine, "get_referenced_works")


# ===== 8. 配置项验证 =====

class TestFeedConfig:
    """测试 feed 配置项."""

    def test_default_config_values(self):
        """默认配置值正确."""
        from scholarpilot.config import Settings
        settings = Settings()
        assert settings.feed_max_recommendations == 20
        assert settings.feed_enable_llm_reasons is True
        assert settings.feed_strategies == "citation,author,topic"
        assert settings.feed_auto_seed_count == 5
        assert settings.openalex_mailto == ""

    def test_config_env_override(self, monkeypatch):
        """配置可通过环境变量覆盖."""
        monkeypatch.setenv("SCHOLAR_FEED_MAX_RECOMMENDATIONS", "50")
        monkeypatch.setenv("SCHOLAR_FEED_AUTO_SEED_COUNT", "10")
        from scholarpilot.config import Settings
        settings = Settings()
        assert settings.feed_max_recommendations == 50
        assert settings.feed_auto_seed_count == 10


# ===== 9. 辅助函数测试 =====

class TestHelperFunctions:
    """测试辅助函数."""

    def test_is_chinese_text(self):
        """中文文本判断."""
        from scholarpilot.agent.feed import _is_chinese_text
        assert _is_chinese_text("地方政府债务风险研究") is True
        assert _is_chinese_text("Fiscal Policy and Growth") is False
        assert _is_chinese_text("") is False
        assert _is_chinese_text("中国经济财政政策与地方政府债务") is True  # 高密度中文
        assert _is_chinese_text("中国 fiscal policy") is False  # 中文占比不足30%，视为英文检索方向

    def test_is_chinese_name(self):
        """中文名判断."""
        from scholarpilot.agent.feed import _is_chinese_name
        assert _is_chinese_name("张三") is True
        assert _is_chinese_name("李四五") is True
        assert _is_chinese_name("John Smith") is False
        assert _is_chinese_name("") is False
        assert _is_chinese_name("王") is True  # 单字也算


# ===== 10. FeedManager 种子管理接口测试 =====

class TestFeedManagerSeeds:
    """测试 FeedManager 种子管理接口."""

    def test_setup_seeds_auto(self, library_with_papers):
        """自动选取种子."""
        from scholarpilot.agent.feed import FeedManager
        from scholarpilot.config import get_settings

        lib = library_with_papers
        settings = get_settings()
        manager = FeedManager(lib, settings)

        seeds = manager.setup_seeds(auto=True, count=3)
        assert len(seeds) <= 3
        assert len(seeds) > 0

    def test_setup_seeds_manual(self, library_with_papers):
        """手动添加种子."""
        from scholarpilot.agent.feed import FeedManager
        from scholarpilot.config import get_settings

        lib = library_with_papers
        settings = get_settings()
        manager = FeedManager(lib, settings)

        paper = lib.find_paper("Fiscal Policy and Economic Growth in China", year=2022)
        seeds = manager.setup_seeds(auto=False, manual_paper_ids=[paper["id"]])
        assert len(seeds) == 1
        assert seeds[0]["title"] == "Fiscal Policy and Economic Growth in China"

    def test_add_remove_seed(self, library_with_papers):
        """添加和移除种子."""
        from scholarpilot.agent.feed import FeedManager
        from scholarpilot.config import get_settings

        lib = library_with_papers
        settings = get_settings()
        manager = FeedManager(lib, settings)

        paper = lib.find_paper("财政分权与地方政府行为", year=2021)
        assert manager.add_seed(paper["id"]) is True

        seeds = manager.get_seeds()
        assert len(seeds) == 1

        assert manager.remove_seed(paper["id"]) is True
        seeds = manager.get_seeds()
        assert len(seeds) == 0


# ===== 11. 统计信息测试 =====

class TestLibraryStats:
    """测试文献库统计中的种子信息."""

    def test_stats_includes_seed_count(self, library_with_papers):
        """统计信息包含种子论文数."""
        lib = library_with_papers
        paper = lib.find_paper("Fiscal Policy and Economic Growth in China", year=2022)
        lib.mark_as_seed(paper["id"])

        stats = lib.get_stats()
        assert "seed_papers" in stats
        assert stats["seed_papers"] == 1
        assert "last_feed_time" in stats

    def test_stats_includes_feed_time(self, temp_library):
        """统计信息包含上次推送时间."""
        lib = temp_library
        lib.record_feed_result(strategy="citation", seed_count=1, recommendations=[])

        stats = lib.get_stats()
        assert stats["last_feed_time"] != ""
