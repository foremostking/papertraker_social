"""测试 cli.py 中文献矩阵解析功能（literature-matrix 命令相关）.

测试范围:
    1. _parse_references_md: 中文/英文/简略条目解析、中英文混合章节切换
    2. _parse_references_bib: @article 条目解析（双花括号/单花括号标题、语言检测）

运行方式:
    cd scholarpilot
    $env:PYTHONPATH = "src"
    python -m pytest tests/test_literature_matrix.py -v
"""

from __future__ import annotations

import pytest

from scholarpilot.cli import _parse_references_md, _parse_references_bib


# ===== _parse_references_md 中文条目详细测试 =====

class TestParseReferencesMdChinese:
    """测试 _parse_references_md 对中文条目的解析."""

    def test_chinese_full_entry(self):
        """测试完整中文条目（作者、标题、期刊、年份）."""
        content = "[1] 毛捷和徐军伟：地方政府债务的空间溢出效应，《经济研究》，2020年。"
        entries = _parse_references_md(content)

        assert len(entries) == 1
        e = entries[0]
        assert e["index"] == 1
        assert e["language"] == "zh"
        assert e["authors"] == "毛捷和徐军伟"
        assert e["title"] == "地方政府债务的空间溢出效应"
        assert e["journal"] == "经济研究"
        assert e["year"] == "2020"

    def test_chinese_entry_with_colon_separator(self):
        """测试中文条目使用全角冒号分隔作者."""
        content = "[2] 王五：研究标题，《某期刊》，2019年。"
        entries = _parse_references_md(content)

        assert len(entries) == 1
        e = entries[0]
        assert e["authors"] == "王五"
        assert e["title"] == "研究标题"
        assert e["journal"] == "某期刊"
        assert e["year"] == "2019"

    def test_chinese_entry_without_journal(self):
        """测试无期刊《》的中文条目（标题取年份前部分）."""
        content = "[3] 赵六：某项研究论文，2018年。"
        entries = _parse_references_md(content)

        assert len(entries) == 1
        e = entries[0]
        assert e["authors"] == "赵六"
        assert e["year"] == "2018"
        assert e["title"] == "某项研究论文"
        assert "journal" not in e

    def test_chinese_entry_without_year(self):
        """测试无年份的中文条目."""
        content = "[4] 孙七：研究标题，《期刊名》。"
        entries = _parse_references_md(content)

        assert len(entries) == 1
        e = entries[0]
        assert e["authors"] == "孙七"
        assert e["journal"] == "期刊名"
        assert e["title"] == "研究标题"
        assert "year" not in e

    def test_chinese_entry_without_colon(self):
        """测试无冒号的中文条目（作者取前30字符，无标题/期刊/年份）."""
        content = "[5] 这是一条没有冒号分隔的参考文献条目内容描述文字。"
        entries = _parse_references_md(content)

        assert len(entries) == 1
        e = entries[0]
        assert "authors" in e
        assert len(e["authors"]) <= 30
        assert "title" not in e
        assert "journal" not in e


# ===== _parse_references_md 英文条目详细测试 =====

class TestParseReferencesMdEnglish:
    """测试 _parse_references_md 对英文条目的解析."""

    def test_english_full_entry_with_quotes_and_italic(self):
        """测试含引号标题和斜体期刊的英文条目.

        注意: _parse_references_md 默认章节为 zh，需通过 "## References" 等
        章节标题切换到 en 模式后才会按英文格式解析。
        """
        content = """## References

[1] Smith, J. & Jones, K., 2022, "Fiscal Sustainability", *Journal of Public Economics*, Vol. 200, pp. 1-25.
"""
        entries = _parse_references_md(content)

        assert len(entries) == 1
        e = entries[0]
        assert e["index"] == 1
        assert e["language"] == "en"
        assert "Smith" in e["authors"]
        assert "Jones" in e["authors"]
        assert e["title"] == "Fiscal Sustainability"
        assert e["journal"] == "Journal of Public Economics"
        assert e["year"] == "2022"

    def test_english_simple_entry(self):
        """测试简略英文条目（只有作者和年份）."""
        content = """## References

[2] Brown, 2019.
"""
        entries = _parse_references_md(content)

        assert len(entries) == 1
        e = entries[0]
        assert e["language"] == "en"
        assert e["authors"] == "Brown"
        assert e["year"] == "2019"
        assert "title" not in e
        assert "journal" not in e

    def test_english_entry_without_year(self):
        """测试无年份的英文条目（含引号标题和斜体期刊）."""
        content = """## References

[3] Wilson, R., "Some Title", *Some Journal*.
"""
        entries = _parse_references_md(content)

        assert len(entries) == 1
        e = entries[0]
        assert "Wilson" in e["authors"]
        assert e["title"] == "Some Title"
        assert e["journal"] == "Some Journal"
        assert "year" not in e

    def test_english_entry_multiple_authors(self):
        """测试多作者英文条目."""
        content = """## References

[4] Johnson, A., Smith, B. and Lee, C., 2021, "Multi Author Paper", *Econ Journal*.
"""
        entries = _parse_references_md(content)

        assert len(entries) == 1
        e = entries[0]
        assert "Johnson" in e["authors"]
        assert "Lee" in e["authors"]
        assert e["title"] == "Multi Author Paper"
        assert e["journal"] == "Econ Journal"
        assert e["year"] == "2021"


# ===== _parse_references_md 中英文混合与章节切换测试 =====

class TestParseReferencesMdMixed:
    """测试中英文混合解析与章节切换检测."""

    def test_mixed_chinese_english_with_section_headers(self):
        """测试中英文混合，通过章节标题切换语言.

        注意: 条目文本中不能出现 "中文"/"英文"/"References" 子串，否则会被
        误判为章节切换行而跳过。
        """
        content = """## 中文文献

[1] 张三：经济论文，《经济研究》，2020年。

## 英文文献

[2] Smith, 2021, "Fiscal Paper", *Journal*.
"""
        entries = _parse_references_md(content)

        assert len(entries) == 2
        assert entries[0]["language"] == "zh"
        assert entries[0]["authors"] == "张三"
        assert entries[1]["language"] == "en"
        assert entries[1]["authors"] == "Smith"
        assert entries[1]["title"] == "Fiscal Paper"

    def test_section_switch_english_keyword(self):
        """测试 'References' 关键词触发英文模式."""
        content = """[1] 张三：经济论文，2020年。

References

[2] Brown, 2018.
"""
        entries = _parse_references_md(content)

        assert len(entries) == 2
        assert entries[0]["language"] == "zh"
        assert entries[1]["language"] == "en"

    def test_section_switch_references_keyword(self):
        """测试 'References' 标题行触发英文模式."""
        content = """[1] 李四：债务研究，2019年。

References

[2] Wilson, 2020, "Title", *Journal*.
"""
        entries = _parse_references_md(content)

        assert len(entries) == 2
        assert entries[0]["language"] == "zh"
        assert entries[1]["language"] == "en"

    def test_section_switch_back_to_chinese(self):
        """测试从英文切换回中文模式."""
        content = """## 英文文献

[1] Smith, 2020, "Fiscal Title", *Journal*.

## 中文文献

[2] 张三：债务研究，《经济期刊》，2021年。
"""
        entries = _parse_references_md(content)

        assert len(entries) == 2
        assert entries[0]["language"] == "en"
        assert entries[1]["language"] == "zh"
        assert entries[1]["authors"] == "张三"

    def test_multiple_entries_same_section(self):
        """测试同一章节下多个条目（语言一致）."""
        content = """[1] 张三：论文一，《期刊一》，2020年。
[2] 李四：论文二，《期刊二》，2021年。
[3] 王五：论文三，《期刊三》，2022年。
"""
        entries = _parse_references_md(content)

        assert len(entries) == 3
        assert all(e["language"] == "zh" for e in entries)
        assert entries[0]["index"] == 1
        assert entries[1]["index"] == 2
        assert entries[2]["index"] == 3

    def test_default_section_is_chinese(self):
        """测试默认章节为中文（无章节标题时）.

        注意: 条目文本不能含 "中文" 子串，否则触发章节切换导致条目被跳过。
        """
        content = "[1] 张三：无章节标题的研究条目，2020年。"
        entries = _parse_references_md(content)

        assert len(entries) == 1
        assert entries[0]["language"] == "zh"


# ===== _parse_references_bib 详细测试 =====

class TestParseReferencesBib:
    """测试 _parse_references_bib 对 @article 条目的解析."""

    def test_article_with_double_brace_title(self):
        """测试双花括号标题（{{...}}）的解析（BibTeX 保护大小写）."""
        content = """@article{ref1,
  author = {毛捷和徐军伟},
  title = {{地方政府债务风险的空间溢出效应}},
  journal = {经济研究},
  year = {2020},
}
"""
        entries = _parse_references_bib(content)

        assert len(entries) == 1
        e = entries[0]
        assert e["authors"] == "毛捷和徐军伟"
        assert e["title"] == "地方政府债务风险的空间溢出效应"
        assert e["journal"] == "经济研究"
        assert e["year"] == "2020"
        assert e["language"] == "zh"

    def test_article_with_single_brace_title(self):
        """测试单花括号标题（{...}）的解析."""
        content = """@article{ref2,
  author = {Smith, J.},
  title = {Fiscal Policy Effects},
  journal = {American Economic Review},
  year = {2021},
}
"""
        entries = _parse_references_bib(content)

        assert len(entries) == 1
        e = entries[0]
        assert e["title"] == "Fiscal Policy Effects"
        assert e["journal"] == "American Economic Review"
        assert e["language"] == "en"

    def test_article_language_detection_chinese(self):
        """测试中文作者触发 language=zh."""
        content = """@article{ref3,
  author = {周黎安},
  title = {行政发包制研究},
  journal = {社会},
  year = {2014},
}
"""
        entries = _parse_references_bib(content)
        assert entries[0]["language"] == "zh"

    def test_article_language_detection_english(self):
        """测试英文作者触发 language=en."""
        content = """@article{ref4,
  author = {Johnson, A. and Smith, B.},
  title = {Public Debt},
  journal = {Journal of Finance},
  year = {2018},
}
"""
        entries = _parse_references_bib(content)
        assert entries[0]["language"] == "en"

    def test_multiple_articles_sequential_index(self):
        """测试多个条目的序号递增（enumerate 1-based）."""
        content = """@article{ref1,
  author = {作者一},
  title = {{标题一}},
  journal = {期刊一},
  year = {2020},
}

@article{ref2,
  author = {Author Two},
  title = {Title Two},
  journal = {Journal Two},
  year = {2021},
}

@article{ref3,
  author = {作者三},
  title = {{标题三}},
  journal = {期刊三},
  year = {2022},
}
"""
        entries = _parse_references_bib(content)

        assert len(entries) == 3
        assert entries[0]["index"] == 1
        assert entries[1]["index"] == 2
        assert entries[2]["index"] == 3
        assert entries[0]["language"] == "zh"
        assert entries[1]["language"] == "en"
        assert entries[2]["language"] == "zh"

    def test_article_missing_fields(self):
        """测试缺失部分字段的 @article 条目."""
        content = """@article{ref5,
  author = {只有作者},
  year = {2019},
}
"""
        entries = _parse_references_bib(content)

        assert len(entries) == 1
        e = entries[0]
        assert e["authors"] == "只有作者"
        assert e["year"] == "2019"
        assert "title" not in e
        assert "journal" not in e

    def test_article_missing_year(self):
        """测试缺失年份的 @article 条目."""
        content = """@article{ref6,
  author = {某作者},
  title = {{某标题}},
  journal = {某期刊},
}
"""
        entries = _parse_references_bib(content)

        assert len(entries) == 1
        e = entries[0]
        assert e["authors"] == "某作者"
        assert e["title"] == "某标题"
        assert "year" not in e

    def test_no_article_entries(self):
        """测试无 @article 条目的内容."""
        content = """@book{ref7,
  author = {某作者},
  title = {某书},
  year = {2020},
}
"""
        entries = _parse_references_bib(content)
        assert entries == []
