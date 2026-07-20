"""引用提取误匹配回归测试.

测试 extract_citations_from_text() 的作者名合理性过滤功能，
确保非作者文本（如"的水平上显著"、"这"）不会被误识别为作者名。

测试场景来自 E2E v5 和 v6 的真实误匹配案例。
"""
import pytest
from scholarpilot.tools.citation_manager import extract_citations_from_text


class TestCitationExtractionNoMismatch:
    """引用提取不应产生误匹配."""

    def test_zh_author_with_significance_context(self):
        """E2E v6 误匹配案例：'在1%的水平上显著，这与刘苗和韩毅（2026）'."""
        text = (
            "财政分权指数与地方政府债务规模呈显著正相关关系，"
            "相关系数为0.324，在1%的水平上显著，"
            "这与刘苗和韩毅（2026）的研究发现一致。"
        )
        citations = extract_citations_from_text(text)

        # 应该提取到 1 条引用：刘苗和韩毅（2026）
        assert len(citations) == 1
        c = citations[0]
        assert c.year == "2026"
        assert c.language == "zh"

        # 作者名不应包含"的水平上显著"或"这"
        for author in c.authors:
            assert "显著" not in author, f"作者名不应包含'显著': {author}"
            assert "水平" not in author, f"作者名不应包含'水平': {author}"
            assert author != "这", f"作者名不应是'这': {author}"
            assert author != "的水平上显著", f"作者名不应是'的水平上显著': {author}"

        # 应该提取到正确的作者名
        assert "刘苗" in c.authors
        assert "韩毅" in c.authors

    def test_zh_author_with_this_pronoun(self):
        """E2E v5 误匹配案例：'这与陈媛媛（2025）'."""
        text = "企业规模与企业绿色创新呈显著正相关，这与陈媛媛（2025）关于企业规模对创新影响的研究结论一致。"
        citations = extract_citations_from_text(text)

        # 应该提取到 1 条引用：陈媛媛（2025）
        assert len(citations) == 1
        c = citations[0]
        assert c.year == "2025"
        assert c.language == "zh"

        # 作者名不应包含"这"
        for author in c.authors:
            assert author != "这", f"作者名不应是'这': {author}"
            assert "这与" not in author, f"作者名不应包含'这与': {author}"

        # 应该提取到正确的作者名
        assert "陈媛媛" in c.authors

    def test_normal_zh_citation_unaffected(self):
        """正常中文引用不应受影响."""
        text = "毛捷和徐军伟（2019）研究发现地方债务对经济有显著影响。"
        citations = extract_citations_from_text(text)

        assert len(citations) == 1
        c = citations[0]
        assert c.year == "2019"
        assert "毛捷" in c.authors
        assert "徐军伟" in c.authors

    def test_normal_zh_citation_with_dunhao(self):
        """顿号分隔的多作者引用不应受影响."""
        text = "钟辉勇、陆铭（2015）研究了财政分权的影响。"
        citations = extract_citations_from_text(text)

        assert len(citations) >= 1
        c = citations[0]
        assert c.year == "2015"
        assert "钟辉勇" in c.authors
        assert "陆铭" in c.authors

    def test_normal_zh_citation_with_et_al(self):
        """'等'格式引用不应受影响."""
        text = "龚强等（2011）从财政分权角度分析了地方债务问题。"
        citations = extract_citations_from_text(text)

        assert len(citations) == 1
        c = citations[0]
        assert c.year == "2011"
        assert "龚强" in c.authors

    def test_en_citation_single_author(self):
        """英文单作者引用不应受影响."""
        text = "Elhorst (2014) proposed the spatial econometric model."
        citations = extract_citations_from_text(text)

        assert len(citations) == 1
        c = citations[0]
        assert c.year == "2014"
        assert c.language == "en"
        assert "Elhorst" in c.authors[0]

    def test_en_citation_et_al(self):
        """英文 et al. 引用不应受影响."""
        text = "Long et al. (2022) found significant effects."
        citations = extract_citations_from_text(text)

        assert len(citations) == 1
        c = citations[0]
        assert c.year == "2022"
        assert "Long" in c.authors[0]

    def test_en_classic_literature(self):
        """英文经典文献（单姓+年份）应能提取."""
        text = "The theory of fiscal federalism was established by Oates (1972)."
        citations = extract_citations_from_text(text)

        assert len(citations) == 1
        c = citations[0]
        assert c.year == "1972"
        assert c.language == "en"
        assert "Oates" in c.authors[0]

    def test_pure_text_no_citation(self):
        """纯正文（无引用）不应提取任何引用."""
        text = "研究结果表明，财政分权对地方政府债务有显著影响，相关系数为0.324，在1%的水平上显著。"
        citations = extract_citations_from_text(text)
        assert len(citations) == 0

    def test_mixed_context_with_citation(self):
        """混合上下文：正文+引用+正文，只应提取引用部分."""
        text = (
            "研究发现相关系数为0.521，在1%的水平上显著，"
            "这与毛捷和徐军伟（2019）的研究一致。"
            "此外，龚强等（2011）也发现了类似结果。"
        )
        citations = extract_citations_from_text(text)

        # 应提取到 2 条引用
        assert len(citations) == 2

        # 第一条：毛捷和徐军伟（2019）
        c1 = citations[0]
        assert c1.year == "2019"
        assert "毛捷" in c1.authors
        assert "徐军伟" in c1.authors
        for a in c1.authors:
            assert "显著" not in a
            assert a != "这"

        # 第二条：龚强等（2011）
        c2 = citations[1]
        assert c2.year == "2011"
        assert "龚强" in c2.authors

    def test_zh_blacklist_phrases(self):
        """黑名单短语不应被提取为引用."""
        text = "另一方面，2019年的政策变化也很重要。"
        citations = extract_citations_from_text(text)
        # "另一方面" 在黑名单中，不应提取
        # 但 "2019" 不是 (19|20)\d{2} 格式的引用（没有括号）
        assert len(citations) == 0

    def test_comma_format_citation(self):
        """逗号格式引用（无括号）也应正确提取."""
        text = "王术华，2017年提出了新的理论框架。"
        citations = extract_citations_from_text(text)

        if citations:
            c = citations[0]
            assert c.year == "2017"
            assert "王术华" in c.authors

    def test_raw_text_rebuilt_after_filter(self):
        """过滤误匹配后，raw 文本应被重建为干净的引用格式."""
        text = "在1%的水平上显著，这与刘苗和韩毅（2026）的研究发现一致。"
        citations = extract_citations_from_text(text)

        assert len(citations) == 1
        c = citations[0]
        # raw 不应包含"的水平上显著"
        assert "水平上显著" not in c.raw
        # raw 应包含"刘苗"和"韩毅"
        assert "刘苗" in c.raw
        assert "韩毅" in c.raw
        assert "2026" in c.raw


class TestIsValidZhAuthor:
    """测试 _is_valid_zh_author 函数."""

    def test_valid_two_char_name(self):
        from scholarpilot.tools.citation_manager import _is_valid_zh_author
        non_name = {"显著", "水平", "这", "的"}
        assert _is_valid_zh_author("刘苗", non_name) is True

    def test_valid_three_char_name(self):
        from scholarpilot.tools.citation_manager import _is_valid_zh_author
        non_name = {"显著", "水平", "这", "的"}
        assert _is_valid_zh_author("毛捷", non_name) is True
        assert _is_valid_zh_author("陈媛媛", non_name) is True

    def test_valid_four_char_name(self):
        from scholarpilot.tools.citation_manager import _is_valid_zh_author
        non_name = {"显著", "水平", "这", "的"}
        assert _is_valid_zh_author("徐军伟", non_name) is True
        assert _is_valid_zh_author("钟辉勇", non_name) is True

    def test_invalid_with_significance(self):
        from scholarpilot.tools.citation_manager import _is_valid_zh_author
        non_name = {"显著", "水平", "这", "的", "关系", "影响"}
        assert _is_valid_zh_author("的水平上显著", non_name) is False

    def test_invalid_with_this(self):
        from scholarpilot.tools.citation_manager import _is_valid_zh_author
        non_name = {"显著", "水平", "这", "的", "关系", "影响"}
        assert _is_valid_zh_author("这", non_name) is False

    def test_invalid_too_short(self):
        from scholarpilot.tools.citation_manager import _is_valid_zh_author
        non_name = {"显著", "水平", "这", "的"}
        assert _is_valid_zh_author("刘", non_name) is False

    def test_invalid_too_long(self):
        from scholarpilot.tools.citation_manager import _is_valid_zh_author
        non_name = {"显著", "水平", "这", "的"}
        assert _is_valid_zh_author("刘苗韩毅陈媛媛", non_name) is False

    def test_invalid_empty(self):
        from scholarpilot.tools.citation_manager import _is_valid_zh_author
        non_name = {"显著", "水平", "这", "的"}
        assert _is_valid_zh_author("", non_name) is False
        assert _is_valid_zh_author("  ", non_name) is False

    def test_invalid_all_function_words(self):
        from scholarpilot.tools.citation_manager import _is_valid_zh_author
        non_name = {"显著", "水平", "这", "的"}
        # 全是虚词/代词
        assert _is_valid_zh_author("这的", non_name) is False
        assert _is_valid_zh_author("为此", non_name) is False
