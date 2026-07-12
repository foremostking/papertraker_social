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
        - 中文：作者和作者（年份），如 钟辉勇和陆铭（2015）
        - 中文：作者等（年份），如 龚强等（2011）
        - 英文：Author (Year)，如 Elhorst (2014)
        - 英文：Author and Author (Year)，如 Weiss (2010)
        - 英文：Author et al. (Year)，如 Long et al. (2022)
        - 英文：First Last et al. (Year)，如 Guangqin Li et al. (2023)

    Args:
        text: 论文正文文本.

    Returns:
        提取到的 Citation 列表.
    """
    citations = []
    seen: set[str] = set()

    # 中文常见非引用短语黑名单（避免误匹配"另一方面，1984"等）
    ZH_BLACKLIST = {
        "另一方面", "从排他性看", "一方面", "另一方面", "总而言之",
        "综上所述", "由此可见", "不难看出", "值得注意", "需要指出",
        "具体而言", "换言之", "与此同时", "不可否认", "毋庸置疑",
        "显而易见", "众所周知", "一般来说", "通常而言", "一般而言",
    }

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
        r'\s*[，,]\s*((?:19|20)\d{2})(?=[^。\n])'  # 后面不能是句号/换行（排除正文叙述）
    )

    # 模式3: 英文引用 — 支持多作者和 et al.
    # 匹配: "Author & Author (Year)", "Author and Author (Year)", "Author et al. (Year)"
    # 支持: 单名(如Elhorst)、双名(如Guangqin Li)、姓+名组合
    en_pattern = re.compile(
        r'('
        r'(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'  # 第一作者（1或2个词）
        r'(?:\s*(?:and|&)\s*(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?))*'  # &/and 连接的后续作者
        r'(?:\s+et\s+al\.?)?'  # 可能有 et al.
        r')'
        r'\s*[(（]\s*(\d{4})\s*[)）]'
    )

    # 提取中文引用（括号格式，优先）
    for m in zh_pattern_paren.finditer(text):
        raw = m.group(0)
        authors_str = m.group(1)
        year = m.group(2)
        # 黑名单过滤
        if authors_str.strip() in ZH_BLACKLIST:
            continue
        key = f"{authors_str}_{year}"
        if key not in seen:
            seen.add(key)
            authors = re.split(r'[、，,]|和|与|及', authors_str)
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
        if authors_str.strip() in ZH_BLACKLIST:
            continue
        key = f"{authors_str}_{year}"
        if key not in seen:
            seen.add(key)
            authors = re.split(r'[、，,]|和|与|及', authors_str)
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
        authors_str = m.group(1).strip()
        year = m.group(2)
        key = f"{authors_str}_{year}"
        if key not in seen:
            seen.add(key)
            # 解析作者列表：按 & / and 分割
            has_et_al = "et al" in authors_str
            authors_clean = re.split(r'\s+(?:and|&)\s+', authors_str)
            authors_clean = [a.replace('et al.', '').replace('et al', '').strip()
                            for a in authors_clean if a.strip() and a.strip() != "et al."]
            if has_et_al and authors_clean:
                authors_clean[-1] = authors_clean[-1] + " et al."
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
    topic_keywords: str = "",
    literature_pool: list[dict] | None = None,
) -> Citation:
    """验证单个引用是否真实存在.

    策略（按优先级）:
        1. 先在 literature_pool（Phase 2 文献池）中匹配作者+年份
        2. 中文引用用 CNKI 验证（作者 + 年份 + 主题词）
        3. 英文引用用 OpenAlex 验证（作者 + 年份 + 主题词）
        4. 如果优先源失败，尝试另一个源
        5. 搜索关键词: 第一作者姓氏 + 年份 + 主题关键词

    Args:
        citation: 待验证的引用.
        cnki_engine: CNKIAiohttpEngine 实例（可选）.
        openalex_engine: OpenAlexEngine 实例（可选）.
        topic_keywords: 研究主题关键词（用于辅助搜索，避免返回不相关论文）.
        literature_pool: Phase 2 已检索到的文献列表（dict 列表），优先在此匹配.

    Returns:
        更新后的 Citation（含验证结果）.
    """
    if not citation.authors or not citation.year:
        citation.source = "unverified"
        return citation

    first_author = citation.authors[0]
    # 去掉 et al. 后缀
    first_author_clean = first_author.replace(" et al.", "").replace(" et al", "").strip()

    # === 策略1: 在 Phase 2 文献池中交叉匹配 ===
    if literature_pool:
        for paper in literature_pool:
            paper_year = str(paper.get("year", ""))
            if paper_year != citation.year:
                continue
            paper_authors = paper.get("authors", [])
            if not paper_authors:
                continue
            # 提取第一作者姓氏进行匹配
            for pa in paper_authors[:3]:
                pa_lower = pa.lower().strip()
                # 检查姓氏是否匹配（英文: 姓在前或后；中文: 全名匹配）
                if (first_author_clean.lower() in pa_lower
                    or pa_lower in first_author_clean.lower()
                    or _match_surname(first_author_clean, pa)):
                    citation.verified = True
                    citation.source = paper.get("source", "literature_pool")
                    citation.title = paper.get("title", "")
                    citation.journal = paper.get("journal", "") or paper.get("venue", "")
                    citation.doi = paper.get("doi", "")
                    citation.abstract = paper.get("abstract", "")
                    citation.authors = paper_authors[:5]
                    citation.year = paper_year
                    return citation

    try:
        if citation.language == "zh" and cnki_engine:
            # CNKI 搜索：主题词用 SU%= 检索，作者用 AU%= 检索（分开字段）
            # 不再把作者名拼进主题检索词
            query = topic_keywords.strip() if topic_keywords else ""
            if not query:
                # 没有主题词时用作者名作为主题词兜底
                query = first_author_clean
            result = await cnki_engine.search(
                query=query,
                year_start=citation.year,
                year_end=citation.year,
                limit=10,
                author=first_author_clean,
                sort_field="",  # 按相关度排序（非发表时间）
            )
            if result.papers:
                # 遍历结果，优先匹配年份+作者，其次只匹配年份
                for paper in result.papers:
                    if citation.year in str(paper.year):
                        # 验证作者名匹配（CNKI 已用 AU%= 过滤，这里二次确认）
                        author_match = _match_any_author(first_author_clean, paper.authors)
                        if author_match or not paper.authors:
                            citation.verified = True
                            citation.source = "cnki"
                            citation.title = paper.title
                            citation.journal = paper.journal or ""
                            citation.authors = paper.authors[:5]
                            return citation
                # 如果没有精确作者匹配，取年份匹配的第一篇（CNKI AU 过滤已保证相关性）
                for paper in result.papers:
                    if citation.year in str(paper.year):
                        citation.verified = True
                        citation.source = "cnki"
                        citation.title = paper.title
                        citation.journal = paper.journal or ""
                        citation.authors = paper.authors[:5]
                        return citation

        if not citation.verified and openalex_engine:
            # OpenAlex 搜索：作者名放入搜索词（OpenAlex 全文搜索会匹配作者名）
            # 不使用 authorships.author.display_name.search 过滤器（会导致 400 错误）
            query = f"{first_author_clean} {topic_keywords}".strip() if topic_keywords else first_author_clean
            result = await openalex_engine.search(
                query=query,
                limit=5,
                year_start=citation.year,
                year_end=citation.year,
            )
            if result.papers:
                # 优先匹配年份+作者，其次只匹配年份
                for paper in result.papers:
                    if str(paper.year) == citation.year:
                        author_match = _match_any_author(first_author_clean, paper.authors)
                        if author_match or not paper.authors:
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
                # 降级：取年份匹配的第一篇
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


def _match_any_author(query_author: str, paper_authors: list[str]) -> bool:
    """检查查询作者名是否匹配论文作者列表中的任一位.

    Args:
        query_author: 待查询的作者名（如 "王磊" 或 "Long"）.
        paper_authors: 论文返回的作者名列表.

    Returns:
        True 如果任一论文作者匹配.
    """
    if not paper_authors:
        return False
    query_clean = query_author.replace(" et al.", "").replace(" et al", "").strip()
    for pa in paper_authors:
        if _match_surname(query_clean, pa):
            return True
    return False


def _match_surname(query_author: str, paper_author: str) -> bool:
    """检查查询作者名是否与论文作者姓氏匹配.

    支持以下匹配方式:
        - "Long" 匹配 "Sheng Long"（姓在后）
        - "Long" 匹配 "Long"（精确匹配）
        - "Long" 匹配 "Long Xue"（姓在前）
        - "张" 匹配 "张三"（中文姓氏前缀）
    """
    query_lower = query_author.lower().strip()
    paper_lower = paper_author.lower().strip()

    # 精确匹配
    if query_lower == paper_lower:
        return True

    # 查询词是论文作者名的子串
    if query_lower in paper_lower:
        return True

    # 拆分论文名为单词列表，检查是否有单词匹配
    paper_parts = paper_lower.split()
    query_parts = query_lower.split()

    # 检查查询名的最后一个词（通常是姓氏）是否在论文作者名的各部分中
    if query_parts:
        query_surname = query_parts[-1]  # "Guangqin Li" → "li"
        if len(query_surname) >= 2 and query_surname in paper_parts:
            return True
        # 也检查查询名的第一词（可能是姓氏）
        query_first = query_parts[0]
        if len(query_first) >= 2 and query_first in paper_parts:
            return True

    return False


async def verify_all_citations(
    citations: list[Citation],
    cnki_engine=None,
    openalex_engine=None,
    concurrency: int = 3,
    topic_keywords: str = "",
    literature_pool: list[dict] | None = None,
) -> list[Citation]:
    """批量验证引用.

    Args:
        citations: 待验证的引用列表.
        cnki_engine: CNKI 引擎实例.
        openalex_engine: OpenAlex 引擎实例.
        concurrency: 并发数（避免 API 限流）.
        topic_keywords: 研究主题关键词（传递给 verify_citation）.
        literature_pool: Phase 2 文献池（传递给 verify_citation）.

    Returns:
        更新后的引用列表.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _verify_one(cite: Citation) -> Citation:
        async with semaphore:
            await asyncio.sleep(0.3)  # 请求间隔
            return await verify_citation(
                cite, cnki_engine, openalex_engine,
                topic_keywords=topic_keywords,
                literature_pool=literature_pool,
            )

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
        # 中文格式 — 修正作者姓名拼接（CNKI 返回的作者列表已经是"姓名"格式）
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
        # 处理 "et al." 后缀
        authors = list(citation.authors[:3])
        has_et_al = any("et al" in a.lower() for a in authors)
        authors_clean = [a.replace(" et al.", "").replace(" et al", "").strip() for a in authors]
        author_str = ", ".join(authors_clean)
        if len(citation.authors) > 3 or has_et_al:
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
        格式化后的参考文献列表字符串（带编号、换行分隔）.
    """
    formatter = format_cssci if style == "cssci" else format_apa7

    if language_separate:
        zh_cites = [c for c in citations if c.language == "zh"]
        en_cites = [c for c in citations if c.language != "zh"]
        lines = []
        num = 1
        if zh_cites:
            lines.append("## 参考文献（中文）")
            lines.append("")
            for c in zh_cites:
                lines.append(f"[{num}] {formatter(c)}")
                lines.append("")  # 每条引用之间空行
                num += 1
        if en_cites:
            if zh_cites:
                lines.append("")
            lines.append("## References（英文）")
            lines.append("")
            for c in en_cites:
                lines.append(f"[{num}] {formatter(c)}")
                lines.append("")  # 每条引用之间空行
                num += 1
        return "\n".join(lines)
    else:
        lines = ["## 参考文献", ""]
        for i, c in enumerate(citations, 1):
            lines.append(f"[{i}] {formatter(c)}")
            lines.append("")  # 每条引用之间空行
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
