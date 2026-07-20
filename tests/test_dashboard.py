"""测试 cli.py 中参考文献解析函数（dashboard 命令相关）.

测试范围:
    1. _parse_references_md: 解析 Markdown 格式参考文献（中文/英文）
    2. _parse_references_bib: 解析 BibTeX 格式参考文献

运行方式:
    cd scholarpilot
    $env:PYTHONPATH = "src"
    python -m pytest tests/test_dashboard.py -v
"""

from __future__ import annotations

import pytest

from scholarpilot.cli import _parse_references_md, _parse_references_bib


# ===== _parse_references_md 测试 =====

class TestParseReferencesMd:
    """测试 _parse_references_md 函数（dashboard 相关基础解析）."""

    def test_parse_chinese_reference(self):
        """测试解析中文参考文献条目."""
        content = """## 中文文献

[1] 张三：论文标题研究，《经济研究》，2020年。
"""
        entries = _parse_references_md(content)

        assert len(entries) == 1
        entry = entries[0]
        assert entry["index"] == 1
        assert entry["language"] == "zh"
        assert entry["authors"] == "张三"
        assert entry["title"] == "论文标题研究"
        assert entry["journal"] == "经济研究"
        assert entry["year"] == "2020"

    def test_parse_english_reference(self):
        """测试解析英文参考文献条目."""
        content = """## References

[1] Smith, J., 2022, "Fiscal Policy", *Journal of Finance*, Vol. 10, pp. 1-20.
"""
        entries = _parse_references_md(content)

        assert len(entries) == 1
        entry = entries[0]
        assert entry["index"] == 1
        assert entry["language"] == "en"
        assert "Smith" in entry["authors"]
        assert entry["title"] == "Fiscal Policy"
        assert entry["journal"] == "Journal of Finance"
        assert entry["year"] == "2022"

    def test_parse_multiple_references(self):
        """测试解析多条参考文献."""
        content = """[1] 张三：论文一，《期刊一》，2020年。
[2] 李四：论文二，《期刊二》，2021年。
"""
        entries = _parse_references_md(content)

        assert len(entries) == 2
        assert entries[0]["index"] == 1
        assert entries[1]["index"] == 2
        assert entries[0]["authors"] == "张三"
        assert entries[1]["authors"] == "李四"

    def test_parse_from_file(self, tmp_path):
        """测试从临时文件读取并解析."""
        ref_file = tmp_path / "references.md"
        content = "[1] 李四：另一篇论文，《管理世界》，2019年。\n"
        ref_file.write_text(content, encoding="utf-8")

        entries = _parse_references_md(ref_file.read_text(encoding="utf-8"))

        assert len(entries) == 1
        assert entries[0]["authors"] == "李四"
        assert entries[0]["journal"] == "管理世界"

    def test_parse_empty_content(self):
        """测试空内容返回空列表."""
        entries = _parse_references_md("")
        assert entries == []

    def test_parse_no_entries(self):
        """测试无条目内容（仅含说明文字）."""
        content = """## 参考文献

这是一段说明文字，没有条目。
"""
        entries = _parse_references_md(content)
        assert entries == []

    def test_parse_skips_blank_lines(self):
        """测试跳过空行."""
        content = """

[1] 张三：论文，《期刊》，2020年。



[2] 李四：论文二，《期刊二》，2021年。
"""
        entries = _parse_references_md(content)

        assert len(entries) == 2


# ===== _parse_references_bib 测试 =====

class TestParseReferencesBib:
    """测试 _parse_references_bib 函数（dashboard 相关基础解析）."""

    def test_parse_bibtex_article(self):
        """测试解析 @article 条目."""
        content = """@article{ref1,
  author = {张三},
  title = {{论文标题}},
  journal = {经济研究},
  year = {2020},
}
"""
        entries = _parse_references_bib(content)

        assert len(entries) == 1
        entry = entries[0]
        assert entry["index"] == 1
        assert entry["authors"] == "张三"
        assert entry["title"] == "论文标题"
        assert entry["journal"] == "经济研究"
        assert entry["year"] == "2020"
        assert entry["language"] == "zh"

    def test_parse_bibtex_english(self):
        """测试解析英文 BibTeX 条目."""
        content = """@article{ref2,
  author = {Smith, J.},
  title = {Fiscal Policy},
  journal = {Journal of Finance},
  year = {2022},
}
"""
        entries = _parse_references_bib(content)

        assert len(entries) == 1
        entry = entries[0]
        assert entry["authors"] == "Smith, J."
        assert entry["title"] == "Fiscal Policy"
        assert entry["journal"] == "Journal of Finance"
        assert entry["year"] == "2022"
        assert entry["language"] == "en"

    def test_parse_bibtex_from_file(self, tmp_path):
        """测试从临时文件读取并解析 BibTeX."""
        bib_file = tmp_path / "references.bib"
        content = """@article{mao2020,
  author = {毛捷},
  title = {{地方政府债务}},
  journal = {经济研究},
  year = {2020},
}
"""
        bib_file.write_text(content, encoding="utf-8")

        entries = _parse_references_bib(bib_file.read_text(encoding="utf-8"))

        assert len(entries) == 1
        assert entries[0]["authors"] == "毛捷"
        assert entries[0]["title"] == "地方政府债务"

    def test_parse_empty_bibtex(self):
        """测试空 BibTeX 内容."""
        entries = _parse_references_bib("")
        assert entries == []

    def test_parse_multiple_bibtex_entries(self):
        """测试解析多个 BibTeX 条目."""
        content = """@article{ref1,
  author = {张三},
  title = {{标题一}},
  journal = {期刊一},
  year = {2020},
}

@article{ref2,
  author = {Smith},
  title = {Title Two},
  journal = {Journal Two},
  year = {2021},
}
"""
        entries = _parse_references_bib(content)

        assert len(entries) == 2
        assert entries[0]["index"] == 1
        assert entries[1]["index"] == 2
        assert entries[0]["language"] == "zh"
        assert entries[1]["language"] == "en"
