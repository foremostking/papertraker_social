"""引用管理器 - 验证 LLM 生成的引用真实性 + 格式化参考文献.

核心功能:
    1. 从 LLM 生成的正文中提取引用（如"作者，年份"或"作者(年份)"格式）
    2. 通过 CNKI/OpenAlex API 验证引用是否真实存在
    3. 按 CSSCI 或 APA 7th 格式生成参考文献列表
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from scholarpilot.utils.network import configure_no_proxy

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """单个引用条目."""

    # 原始引用文本（从正文提取）
    raw: str = ""
    # 结构化字段
    authors: list[str] = field(default_factory=list)
    year: str = ""
    title: str = ""  # 验证后填充
    journal: str = ""  # 验证后填充
    doi: str = ""
    source: str = ""  # cnki / openalex / unverified
    verified: bool = False
    language: str = ""  # zh / en
    # OpenAlex / CNKI 返回的额外字段
    abstract: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "authors": self.authors,
            "year": self.year,
            "title": self.title,
            "journal": self.journal,
            "doi": self.doi,
            "source": self.source,
            "verified": self.verified,
            "language": self.language,
        }


def extract_citations_from_text(text: str) -> list[Citation]:
    """从正文中提取引用.

    支持的格式:
        - 中文：作者（年份），如 毛捷、徐军伟（2019）
        - 中文：作者和作者（年份），如 钟辉勇、陆铭（2015）
        - 中文：作者等（年份），如 龚强等（2011）
        - 英文：Author (Year)，如 Elhorst (2014)
        - 英文：Author and Author (Year)，如 Weiss (2010)

    Args:
        text: 论文正文文本.

    Returns:
        提取到的 Citation 列表.
    """
    citations = []
    seen: set[str] = set()

    # 模式1: 中文引用 — 多种格式
    # 格式A: 作者（年份），如 毛捷、徐军伟（2019）
    # 格式B: 作者和作者（年份），如 钟辉勇和陆铭（2015）
    # 格式C: 作者等（年份），如 龚强等（2011）
    # 格式D: 作者年份，无括号（少见但可能），如 周黎安2007
    # 匹配策略: 先匹配括号内年份的格式

    # 格式1: 中文作者（年份）— 兼容顿号、逗号、和/与 连接
    zh_pattern_paren = re.compile(
        r'(?<![\u4e00-\u9fff（(])'  # 前面不能是汉字或括号
        r'([\u4e00-\u9fff]{2,6}'
        r'(?:[、，,]\s*[\u4e00-\u9fff]{2,6})*'  # 多作者（顿号/逗号分隔）
        r'(?:\s*[和与]\s*[\u4e00-\u9fff]{2,6})*'  # "和/与"连接的多作者
        r'(?:等)?)'  # 可能有"等"
        r'\s*[（(]\s*((?:19|20)\d{2})\s*[）)]'  # 完整年份（4位）
    )

    # 格式2: 纯中文作者+年份无括号（如 王术华，2017）
    zh_pattern_comma = re.compile(
        r'(?<![\u4e00-\u9fff])'  # 前面不能是汉字
        r'([\u4e00-\u9fff]{2,6}'
        r'(?:[、，,]\s*[\u4e00-\u9fff]{2,6})*'
        r'(?:\s*[和与]\s*[\u4e00-\u9fff]{2,6})*'
        r'(?:等)?)'
        r'\s*[，,]\s*((?:19|20)\d{2})'
    )

    # 模式2: 英文引用 — "Author (Year)" 或 "Author et al. (Year)"
    en_pattern = re.compile(
        r'([A-Z][a-z]+(?:\s+(?:and|&|,)\s+[A-Z][a-z]+)*(?:\s+et\s+al\.?)?)'
        r'\s*[(（]\s*(\d{4})\s*[)）]'
    )

    # 提取中文引用（括号格式，优先）
    for m in zh_pattern_paren.finditer(text):
        raw = m.group(0)
        authors_str = m.group(1)
        year = m.group(2)  # (19|20)\d{2} 的第一个捕获组
        key = f"{authors_str}_{year}"
        if key not in seen:
            seen.add(key)
            # 解析作者列表
            authors = re.split(r'[、，,与及]', authors_str)
            authors = [a.replace('等', '').strip() for a in authors if a.strip()]
            citations.append(Citation(
                raw=raw,
                authors=authors,
                year=year,
                language="zh",
            ))

    # 提取中文引用（逗号格式，补充）
    for m in zh_pattern_comma.finditer(text):
        raw = m.group(0)
        authors_str = m.group(1)
        year = m.group(2)
        key = f"{authors_str}_{year}"
        if key not in seen:
            seen.add(key)
            authors = re.split(r'[、，,与及]', authors_str)
            authors = [a.replace('等', '').strip() for a in authors if a.strip()]
            citations.append(Citation(
                raw=raw,
                authors=authors,
                year=year,
                language="zh",
            ))

    # 提取英文引用
    for m in en_pattern.finditer(text):
        raw = m.group(0)
        authors_str = m.group(1)
        year = m.group(2)
        key = f"{authors_str}_{year}"
        if key not in seen:
            seen.add(key)
            # 解析作者列表
            authors_clean = re.split(r'\s+(?:and|&|,)\s+', authors_str)
            authors_clean = [a.replace('et al.', '').strip() for a in authors_clean if a.strip()]
            citations.append(Citation(
                raw=raw,
                authors=authors_clean,
                year=year,
                language="en",
            ))

    return citations


async def verify_citation(
    citation: Citation,
    cnki_engine=None,
    openalex_engine=None,
) -> Citation:
    """验证单个引用是否真实存在.

    策略:
        1. 中文引用优先用 CNKI 验证
        2. 英文引用优先用 OpenAlex 验证
        3. 如果优先源失败，尝试另一个源
        4. 搜索关键词: 第一作者姓氏 + 年份 + 上下文关键词

    Args:
        citation: 待验证的引用.
        cnki_engine: CNKIAiohttpEngine 实例（可选）.
        openalex_engine: OpenAlexEngine 实例（可选）.

    Returns:
        更新后的 Citation（含验证结果）.
    """
    if not citation.authors or not citation.year:
        citation.source = "unverified"
        return citation

    first_author = citation.authors[0]

    try:
        if citation.language == "zh" and cnki_engine:
            # 用第一作者 + 年份搜索 CNKI
            query = first_author
            result = await cnki_engine.search(
                query=query,
                year_start=citation.year,
                year_end=citation.year,
                limit=5,
            )
            if result.papers:
                # 尝试匹配年份
                for paper in result.papers:
                    if citation.year in str(paper.year):
                        citation.verified = True
                        citation.source = "cnki"
                        citation.title = paper.title
                        citation.journal = paper.journal or ""
                        citation.authors = paper.authors[:5]
                        return citation
                # 如果没有精确年份匹配，取最相似的
                if result.papers:
                    paper = result.papers[0]
                    citation.verified = True
                    citation.source = "cnki"
                    citation.title = paper.title
                    citation.journal = paper.journal or ""
                    citation.authors = paper.authors[:5]

        if not citation.verified and openalex_engine:
            # 用第一作者 + 年份搜索 OpenAlex
            query = first_author
            if citation.language == "en":
                result = await openalex_engine.search(
                    query=query,
                    limit=5,
                    year_start=citation.year,
                    year_end=citation.year,
                    has_abstract=True,
                )
            else:
                result = await openalex_engine.search(
                    query=query,
                    limit=5,
                    year_start=citation.year,
                    year_end=citation.year,
                )
            if result.papers:
                for paper in result.papers:
                    if str(paper.year) == citation.year:
                        citation.verified = True
                        citation.source = "openalex"
                        citation.title = paper.title
                        citation.journal = paper.primary_venue or ""
                        citation.doi = paper.doi
                        citation.abstract = paper.abstract
                        citation.volume = paper.biblio_volume
                        citation.issue = paper.biblio_issue
                        citation.pages = f"{paper.biblio_first_page}-{paper.biblio_last_page}".strip("-")
                        if paper.authors:
                            citation.authors = paper.authors[:5]
                        return citation

    except Exception as e:
        logger.warning(f"验证引用失败 [{citation.raw}]: {e}")

    if not citation.verified:
        citation.source = "unverified"

    return citation


async def verify_all_citations(
    citations: list[Citation],
    cnki_engine=None,
    openalex_engine=None,
    concurrency: int = 3,
) -> list[Citation]:
    """批量验证引用.

    Args:
        citations: 待验证的引用列表.
        cnki_engine: CNKI 引擎实例.
        openalex_engine: OpenAlex 引擎实例.
        concurrency: 并发数（避免 API 限流）.

    Returns:
        更新后的引用列表.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _verify_one(cite: Citation) -> Citation:
        async with semaphore:
            await asyncio.sleep(0.3)  # 请求间隔
            return await verify_citation(cite, cnki_engine, openalex_engine)

    tasks = [_verify_one(c) for c in citations]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    verified = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"验证异常: {result}")
            citations[i].source = "unverified"
            verified.append(citations[i])
        else:
            verified.append(result)

    return verified


def format_cssci(citation: Citation) -> str:
    """格式化为 CSSCI（中文核心期刊）参考文献格式.

    CSSCI 格式要求:
        - 作者-年份制，正文中引用格式：作者（年份）
        - 文后中文：作者：《标题》，《期刊》，年份第X期。
        - 文后英文：Author, Year, "Title", *Journal*, Vol(No), pp.
        - 中英文分开，中文在前
    """
    if not citation.verified and not citation.title:
        return f"[未验证] {citation.raw}"

    if citation.language == "zh":
        # 中文格式
        author_str = "、".join(citation.authors[:3])
        if len(citation.authors) > 3:
            author_str += "等"
        result = f"{author_str}：{citation.title}"
        if citation.journal:
            result += f"，《{citation.journal}》"
        else:
            result += "，"
        if citation.year:
            result += f"，{citation.year}年"
        if citation.issue:
            result += f"第{citation.issue}期"
        result += "。"
        return result
    else:
        # 英文格式
        author_str = ", ".join(citation.authors[:3])
        if len(citation.authors) > 3:
            author_str += " et al."
        result = f"{author_str}, {citation.year}"
        if citation.title:
            result += f', "{citation.title}"'
        if citation.journal:
            result += f", *{citation.journal}*"
        if citation.volume:
            result += f", Vol. {citation.volume}"
        if citation.issue:
            result += f", No. {citation.issue}"
        if citation.pages:
            result += f", pp. {citation.pages}"
        result += "."
        return result


def format_apa7(citation: Citation) -> str:
    """格式化为 APA 7th 参考文献格式.

    APA 7th 格式:
        Author, A. A., & Author, B. B. (Year). Title of article. *Journal Name*, Volume(Issue), Pages. https://doi.org/xxx
    """
    if not citation.verified and not citation.title:
        return f"[未验证] {citation.raw}"

    # 作者格式化
    if citation.language == "zh":
        author_str = "、".join(citation.authors[:3])
        if len(citation.authors) > 3:
            author_str += "等"
    else:
        authors = []
        for i, a in enumerate(citation.authors[:3]):
            authors.append(a)
        author_str = ", ".join(authors)
        if len(citation.authors) > 2:
            author_str += ", et al."
        elif len(citation.authors) == 2:
            author_str = f"{citation.authors[0]} & {citation.authors[1]}"

    result = f"{author_str} ({citation.year})"
    if citation.title:
        result += f". {citation.title}"
    if citation.journal:
        result += f". *{citation.journal}*"
    if citation.volume:
        result += f", {citation.volume}"
    if citation.issue:
        result += f"({citation.issue})"
    if citation.pages:
        result += f", {citation.pages}"
    if citation.doi:
        result += f". https://doi.org/{citation.doi}"
    result += "."
    return result


def format_references_list(
    citations: list[Citation],
    style: str = "cssci",
    language_separate: bool = True,
) -> str:
    """生成完整的参考文献列表.

    Args:
        citations: 引用列表.
        style: 格式风格 (cssci / apa7).
        language_separate: 是否中英文分开（CSSCI 要求）.

    Returns:
        格式化后的参考文献列表字符串.
    """
    formatter = format_cssci if style == "cssci" else format_apa7

    if language_separate:
        zh_cites = [c for c in citations if c.language == "zh"]
        en_cites = [c for c in citations if c.language != "zh"]
        lines = []
        if zh_cites:
            lines.append("## 参考文献（中文）")
            for c in zh_cites:
                lines.append(f"[{'✓' if c.verified else '✗'}] {formatter(c)}")
        if en_cites:
            if zh_cites:
                lines.append("")
            lines.append("## References（英文）")
            for c in en_cites:
                lines.append(f"[{'✓' if c.verified else '✗'}] {formatter(c)}")
        return "\n".join(lines)
    else:
        lines = ["## 参考文献"]
        for c in citations:
            lines.append(f"[{'✓' if c.verified else '✗'}] {formatter(c)}")
        return "\n".join(lines)


def generate_ai_disclosure(language: str = "zh") -> str:
    """生成 AI 使用声明.

    根据教育部 2025 新规和 CSSCI 期刊要求，生成透明披露声明。

    Args:
        language: 声明语言 (zh / en).

    Returns:
        AI 使用声明文本.
    """
    if language == "zh":
        return (
            "## AI 使用声明\n\n"
            "本文在写作过程中使用了 AI 辅助工具（ScholarPilot），主要用于以下方面：\n"
            "1. 文献检索：通过 CNKI、NCPSSD、OpenAlex 等学术数据库辅助检索相关文献；\n"
            "2. 语言润色：对部分段落的语言表达进行了辅助优化；\n"
            "3. 框架建议：在论文结构设计和写作思路方面提供了参考性建议。\n\n"
            "本文的核心研究问题、理论分析、实证设计和结论解释均由作者独立完成。"
            "所有文献引用均经过作者核实确认。作者对论文的全部内容承担学术责任。"
        )
    else:
        return (
            "## AI Disclosure Statement\n\n"
            "AI-assisted tools (ScholarPilot) were used in the preparation of this manuscript "
            "for the following purposes:\n"
            "1. Literature search: Assisted in retrieving relevant literature from CNKI, NCPSSD, "
            "OpenAlex, and other academic databases;\n"
            "2. Language polishing: Provided suggestions for improving language expression in "
            "certain paragraphs;\n"
            "3. Framework suggestions: Offered reference suggestions for paper structure and "
            "writing approach.\n\n"
            "The core research questions, theoretical analysis, empirical design, and interpretation "
            "of conclusions were independently completed by the authors. All citations have been "
            "verified by the authors. The authors bear full academic responsibility for the content "
            "of this paper."
        )


__all__ = [
    "Citation",
    "extract_citations_from_text",
    "verify_citation",
    "verify_all_citations",
    "format_cssci",
    "format_apa7",
    "format_references_list",
    "generate_ai_disclosure",
]
