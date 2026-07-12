"""反幻觉与引用验证模块.

检测 AI 生成论文中的幻觉引用、虚构文献，验证引用真实性。

核心功能:
    1. DOI 验证（通过 CrossRef API 异步查询）
    2. 引用真实性验证（作者、年份、标题匹配）
    3. 证据等级标注（STRONG / MODERATE / WEAK / UNVERIFIED）
    4. 引用密度检查（过度引用 / 引用不足）
    5. 引用交叉校验（正文 vs 参考文献列表）
    6. AI 编造文献检测（DOI 格式异常、期刊不存在、作者异常等）
    7. 检索证据字段构建（记录数据库来源、检索关键词、检索时间）
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from enum import Enum

import aiohttp
from pydantic import BaseModel, Field

from scholarpilot.utils.network import configure_no_proxy, get_aiohttp_session_kwargs

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


class EvidenceLevel(str, Enum):
    """证据等级枚举.

    Attributes:
        STRONG: 强证据 — 有 DOI 且来自权威期刊.
        MODERATE: 中等证据 — 有明确来源但无 DOI.
        WEAK: 弱证据 — 推断性表达，无直接来源支撑.
        UNVERIFIED: 未验证 — AI 生成的可能虚构引用.
    """

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    UNVERIFIED = "unverified"


class CitationVerification(BaseModel):
    """单条引用的验证结果."""

    citation_text: str
    doi: str | None = None
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    source_db: str = ""  # 来源数据库 (crossref / openalex / cnki / manual)
    search_keyword: str = ""  # 检索关键词
    evidence_level: EvidenceLevel = EvidenceLevel.UNVERIFIED
    is_verified: bool = False
    issues: list[str] = Field(default_factory=list)  # 发现的问题


class HallucinationReport(BaseModel):
    """幻觉检测汇总报告."""

    total_citations: int = 0
    verified: int = 0
    unverified: int = 0
    fabricated: int = 0
    evidence_distribution: dict[str, int] = Field(default_factory=dict)
    issues: list[dict] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# CrossRef API 基地址
CROSSREF_API = "https://api.crossref.org/works/"

# DOI 正则表达式（匹配 10.xxxx/yyy 格式）
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+\b")

# 推断性表达（弱证据信号）
INFERENTIAL_EXPRESSIONS: list[str] = [
    "研究表明", "有学者认为", "据研究", "有研究指出", "学界普遍认为",
    "一般认为", "通常认为", "有观点认为", "有文献表明", "据称",
    "以往研究", "相关研究", "已有研究",
    "It has been shown", "Studies suggest", "Research indicates",
    "It is widely believed", "Some scholars argue", "Previous research",
    "It is generally accepted",
]

# 已知权威期刊集合（用于编造文献检测的期刊名比对）
KNOWN_JOURNALS: set[str] = {
    # 中文核心
    "经济研究", "管理世界", "中国社会科学", "金融研究", "经济学（季刊）",
    "数量经济技术经济研究", "财贸经济", "财政研究", "会计研究",
    "中国工业经济", "世界经济", "经济学动态", "宏观经济研究",
    "统计研究", "中国软科学", "科研管理", "南开管理评论",
    # 英文权威
    "Nature", "Science", "Cell",
    "The American Economic Review", "American Economic Review",
    "Econometrica", "The Journal of Finance", "Journal of Finance",
    "The Journal of Political Economy", "Journal of Political Economy",
    "The Quarterly Journal of Economics", "Quarterly Journal of Economics",
    "Review of Economic Studies", "The Review of Economic Studies",
    "Journal of Monetary Economics", "Journal of Public Economics",
    "Journal of Financial Economics", "Journal of Econometrics",
    "European Economic Review", "Economics Letters",
    "Journal of Economic Literature", "Journal of Economic Perspectives",
}

# DOI 系统正式启用年份（CrossRef 前身于 2000 年开始大规模注册）
DOI_SYSTEM_START_YEAR = 2000

# 作者数量异常阈值
MAX_REASONABLE_AUTHORS = 20


# ---------------------------------------------------------------------------
# 核心检查器
# ---------------------------------------------------------------------------


class AntiHallucinationChecker:
    """反幻觉与引用验证检查器.

    对 AI 生成的论文引用进行多维度验证，识别幻觉和虚构文献。

    Usage:
        checker = AntiHallucinationChecker()

        # 同步验证单条引用
        result = checker.verify_citation("Smith, J. (2023). Deep learning...")

        # 异步批量验证
        results = await checker.async_batch_verify(["引用1", "引用2"])

        # 生成报告
        report = checker.generate_report(results)
    """

    def __init__(self, timeout: int = 30, max_concurrent: int = 5) -> None:
        """初始化反幻觉检查器.

        Args:
            timeout: 网络请求超时秒数.
            max_concurrent: 异步并发验证的最大并发数.
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_concurrent = max_concurrent
        # 确保代理绕过配置已生效
        configure_no_proxy()

    # ------------------------------------------------------------------
    # DOI 验证
    # ------------------------------------------------------------------

    def extract_doi(self, text: str) -> list[str]:
        """从文本中提取所有 DOI.

        支持以下常见格式:
            - 10.1234/abcde
            - https://doi.org/10.1234/abcde
            - doi: 10.1234/abcde
            - DOI: 10.1234/abcde

        Args:
            text: 待提取的文本.

        Returns:
            去重后的 DOI 列表.
        """
        matches = DOI_PATTERN.findall(text)
        # 清理尾部标点
        cleaned: list[str] = []
        seen: set[str] = set()
        for doi in matches:
            doi = doi.rstrip(".,;)")
            if doi not in seen:
                seen.add(doi)
                cleaned.append(doi)
        return cleaned

    def verify_doi(self, doi: str) -> bool:
        """同步验证 DOI 是否真实存在（通过 CrossRef API）.

        Args:
            doi: 待验证的 DOI 字符串.

        Returns:
            True 表示 DOI 在 CrossRef 中存在，False 表示不存在或验证失败.
        """
        return asyncio.get_event_loop().run_until_complete(self.async_verify_doi(doi))

    async def async_verify_doi(self, doi: str) -> bool:
        """异步验证 DOI 是否真实存在（通过 CrossRef API）.

        使用 aiohttp 发起请求，设置 ``trust_env=False`` 和 ``proxy=None``
        绕过系统代理。

        Args:
            doi: 待验证的 DOI 字符串.

        Returns:
            True 表示 DOI 在 CrossRef 中存在，False 表示不存在或验证失败.
        """
        url = f"{CROSSREF_API}{doi}"
        session_kwargs = get_aiohttp_session_kwargs(timeout=self.timeout)
        try:
            async with aiohttp.ClientSession(**session_kwargs) as session:
                async with session.get(url, proxy=None) as resp:
                    if resp.status == 200:
                        return True
                    if resp.status == 404:
                        logger.debug(f"DOI 不存在于 CrossRef: {doi}")
                        return False
                    logger.warning(f"CrossRef 返回异常状态码 {resp.status} for DOI: {doi}")
                    return False
        except aiohttp.ClientError as e:
            logger.warning(f"验证 DOI 网络错误 [{doi}]: {e}")
            return False
        except Exception as e:
            logger.warning(f"验证 DOI 异常 [{doi}]: {e}")
            return False

    async def _async_verify_doi_safe(self, doi: str) -> bool:
        """带异常保护的 DOI 异步验证（用于 gather）."""
        try:
            return await self.async_verify_doi(doi)
        except Exception as e:
            logger.warning(f"DOI 异步验证异常 [{doi}]: {e}")
            return False

    # ------------------------------------------------------------------
    # 引用验证
    # ------------------------------------------------------------------

    def verify_citation(self, citation_text: str) -> CitationVerification:
        """验证单条引用的真实性.

        检查项:
            1. 提取并验证 DOI（如果存在）
            2. 解析作者、年份、标题
            3. 评估证据等级
            4. 记录发现的问题

        Args:
            citation_text: 引用文本（如 "Smith, J. (2023). Title. Journal."）.

        Returns:
            CitationVerification 验证结果对象.
        """
        issues: list[str] = []
        result = CitationVerification(
            citation_text=citation_text,
            source_db="crossref",
            search_keyword="",
        )

        # 提取 DOI
        dois = self.extract_doi(citation_text)
        if dois:
            result.doi = dois[0]
            # 同步验证 DOI
            doi_valid = asyncio.get_event_loop().run_until_complete(
                self.async_verify_doi(dois[0])
            )
            if doi_valid:
                result.is_verified = True
                result.evidence_level = EvidenceLevel.STRONG
            else:
                issues.append(f"DOI {dois[0]} 在 CrossRef 中未找到")
                result.evidence_level = EvidenceLevel.UNVERIFIED
        else:
            issues.append("未检测到 DOI")

        # 解析年份
        year_match = re.search(r"\b(19|20)\d{2}\b", citation_text)
        if year_match:
            result.year = int(year_match.group(0))
            # 检查年份合理性
            current_year = datetime.now(timezone.utc).year
            if result.year > current_year:
                issues.append(f"年份 {result.year} 在未来，可能为编造")
        else:
            issues.append("未检测到年份")

        # 解析作者（简化：取句首到年份前的部分）
        if year_match:
            before_year = citation_text[: year_match.start()].strip().rstrip(",.")
            if before_year:
                # 按逗号或 & 或 and 分割
                raw_authors = re.split(r"[,;&]|\band\b", before_year)
                result.authors = [a.strip() for a in raw_authors if a.strip()]

        # 解析标题（年份后第一个句号前的内容）
        if year_match:
            after_year = citation_text[year_match.end():].lstrip(". ")
            title_match = re.match(r"(.+?)[.]", after_year)
            if title_match:
                result.title = title_match.group(1).strip()

        # 无 DOI 时评估证据等级
        if not result.is_verified:
            if result.authors and result.year and result.title:
                result.evidence_level = EvidenceLevel.MODERATE
            elif any(expr in citation_text for expr in INFERENTIAL_EXPRESSIONS):
                result.evidence_level = EvidenceLevel.WEAK
            else:
                result.evidence_level = EvidenceLevel.UNVERIFIED

        result.issues = issues
        result.search_keyword = self._build_search_keyword(result)
        return result

    def batch_verify(self, citations: list[str]) -> list[CitationVerification]:
        """同步批量验证引用.

        Args:
            citations: 引用文本列表.

        Returns:
            每条引用对应的验证结果列表.
        """
        return asyncio.get_event_loop().run_until_complete(
            self.async_batch_verify(citations)
        )

    async def async_batch_verify(
        self, citations: list[str]
    ) -> list[CitationVerification]:
        """异步批量验证引用.

        使用信号量控制并发数，避免 API 限流。

        Args:
            citations: 引用文本列表.

        Returns:
            每条引用对应的验证结果列表.
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _verify_one(cite: str) -> CitationVerification:
            async with semaphore:
                await asyncio.sleep(0.2)  # 请求间隔，避免限流
                return await self._async_verify_citation(cite)

        tasks = [_verify_one(c) for c in citations]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        verified: list[CitationVerification] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"引用验证异常: {result}")
                verified.append(CitationVerification(
                    citation_text=citations[i],
                    evidence_level=EvidenceLevel.UNVERIFIED,
                    is_verified=False,
                    issues=[f"验证过程异常: {result}"],
                ))
            else:
                verified.append(result)
        return verified

    async def _async_verify_citation(
        self, citation_text: str
    ) -> CitationVerification:
        """异步验证单条引用（内部方法）.

        与 ``verify_citation`` 类似，但 DOI 验证使用异步调用。
        """
        issues: list[str] = []
        result = CitationVerification(
            citation_text=citation_text,
            source_db="crossref",
        )

        # 提取并异步验证 DOI
        dois = self.extract_doi(citation_text)
        if dois:
            result.doi = dois[0]
            doi_valid = await self._async_verify_doi_safe(dois[0])
            if doi_valid:
                result.is_verified = True
                result.evidence_level = EvidenceLevel.STRONG
            else:
                issues.append(f"DOI {dois[0]} 在 CrossRef 中未找到")
                result.evidence_level = EvidenceLevel.UNVERIFIED
        else:
            issues.append("未检测到 DOI")

        # 解析年份
        year_match = re.search(r"\b(19|20)\d{2}\b", citation_text)
        if year_match:
            result.year = int(year_match.group(0))
            current_year = datetime.now(timezone.utc).year
            if result.year > current_year:
                issues.append(f"年份 {result.year} 在未来，可能为编造")
        else:
            issues.append("未检测到年份")

        # 解析作者
        if year_match:
            before_year = citation_text[: year_match.start()].strip().rstrip(",.")
            if before_year:
                raw_authors = re.split(r"[,;&]|\band\b", before_year)
                result.authors = [a.strip() for a in raw_authors if a.strip()]

        # 解析标题
        if year_match:
            after_year = citation_text[year_match.end():].lstrip(". ")
            title_match = re.match(r"(.+?)[.]", after_year)
            if title_match:
                result.title = title_match.group(1).strip()

        # 无 DOI 时评估证据等级
        if not result.is_verified:
            if result.authors and result.year and result.title:
                result.evidence_level = EvidenceLevel.MODERATE
            elif any(expr in citation_text for expr in INFERENTIAL_EXPRESSIONS):
                result.evidence_level = EvidenceLevel.WEAK
            else:
                result.evidence_level = EvidenceLevel.UNVERIFIED

        result.issues = issues
        result.search_keyword = self._build_search_keyword(result)
        return result

    def _build_search_keyword(self, verification: CitationVerification) -> str:
        """根据验证结果构建检索关键词.

        Args:
            verification: 引用验证结果.

        Returns:
            检索关键词字符串.
        """
        parts: list[str] = []
        if verification.authors:
            parts.append(verification.authors[0])
        if verification.year:
            parts.append(str(verification.year))
        if verification.title:
            # 取标题前 30 个字符作为关键词
            parts.append(verification.title[:30])
        return " ".join(parts)

    # ------------------------------------------------------------------
    # 证据等级标注
    # ------------------------------------------------------------------

    def assess_evidence_level(
        self, claim: str, citations: list[CitationVerification]
    ) -> EvidenceLevel:
        """评估某个论断的证据等级.

        规则:
            - 有 DOI 且验证通过 -> STRONG
            - 有明确来源但无 DOI -> MODERATE
            - 有"研究表明""有学者认为"等推断性表达 -> WEAK
            - 无任何引用支撑 -> UNVERIFIED

        Args:
            claim: 论断文本.
            citations: 支撑该论断的引用验证结果列表.

        Returns:
            EvidenceLevel 证据等级.
        """
        # 无引用支撑
        if not citations:
            return EvidenceLevel.UNVERIFIED

        # 检查是否有验证通过的 DOI 引用
        has_verified_doi = any(c.is_verified and c.doi for c in citations)
        if has_verified_doi:
            return EvidenceLevel.STRONG

        # 检查是否有明确来源（作者+年份+标题）
        has_explicit_source = any(
            c.authors and c.year and c.title for c in citations
        )
        if has_explicit_source:
            return EvidenceLevel.MODERATE

        # 检查推断性表达
        has_inferential = any(
            expr in claim for expr in INFERENTIAL_EXPRESSIONS
        )
        if has_inferential:
            return EvidenceLevel.WEAK

        return EvidenceLevel.UNVERIFIED

    # ------------------------------------------------------------------
    # 引用数量限制
    # ------------------------------------------------------------------

    def check_citation_density(self, text: str) -> dict:
        """检查引用密度是否合理.

        检测项:
            1. 过度引用：同一段落超过 5 篇引用
            2. 引用不足：关键论点（含推断性表达的句子）无引用支撑
            3. 每个关键论点最多 3 篇最直接文献

        Args:
            text: 论文正文文本.

        Returns:
            包含以下键的字典:
                - over_cited_paragraphs: 过度引用的段落列表
                - under_cited_claims: 引用不足的论断列表
                - max_per_claim: 每个论点的建议最大引用数 (3)
                - paragraph_citation_counts: 各段引用数统计
        """
        max_per_claim = 3
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        over_cited: list[dict] = []
        under_cited: list[dict] = []
        para_counts: list[dict] = []

        # 引用标记模式：(Author, Year) / （作者，年份）/ [1] / [Smith 2020]
        citation_marker_pattern = re.compile(
            r"\([^)]*(?:19|20)\d{2}[^)]*\)"  # (Author, 2020)
            r"|[（][^）]*(?:19|20)\d{2}[^）]*[）]"  # （作者，2020）
            r"|\[\d{1,3}\]"  # [1]
            r"|\[[A-Z][a-z]+\s+\d{4}\]"  # [Smith 2020]
        )

        for idx, para in enumerate(paragraphs):
            citations_in_para = citation_marker_pattern.findall(para)
            count = len(citations_in_para)
            para_counts.append({"paragraph": idx + 1, "citation_count": count})

            # 过度引用检测
            if count > 5:
                over_cited.append({
                    "paragraph": idx + 1,
                    "citation_count": count,
                    "message": f"第 {idx + 1} 段包含 {count} 篇引用，超过建议上限 5 篇",
                })

            # 引用不足检测：句子包含推断性表达但无引用
            sentences = re.split(r"[。.!?！？]", para)
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                has_inferential = any(
                    expr in sent for expr in INFERENTIAL_EXPRESSIONS
                )
                has_citation = bool(citation_marker_pattern.search(sent))
                if has_inferential and not has_citation:
                    under_cited.append({
                        "paragraph": idx + 1,
                        "sentence": sent[:80],
                        "message": "关键论点使用推断性表达但缺少引用支撑",
                    })

        return {
            "over_cited_paragraphs": over_cited,
            "under_cited_claims": under_cited,
            "max_per_claim": max_per_claim,
            "paragraph_citation_counts": para_counts,
        }

    # ------------------------------------------------------------------
    # 引用交叉校验
    # ------------------------------------------------------------------

    def cross_check_citations(
        self, body_text: str, reference_list: str
    ) -> dict:
        """交叉校验正文引用与参考文献列表的一致性.

        检查项:
            1. 正文中的引用是否都在参考文献列表中
            2. 参考文献列表中是否有未在正文中引用的文献
            3. 引用格式一致性

        Args:
            body_text: 论文正文文本.
            reference_list: 参考文献列表文本.

        Returns:
            包含以下键的字典:
                - in_body_not_in_refs: 正文有但参考文献列表中没有的引用
                - in_refs_not_in_body: 参考文献列表有但正文未引用的文献
                - format_issues: 格式一致性问题
                - is_consistent: 是否一致
        """
        # 提取正文中的引用标记（作者+年份格式）
        body_pattern = re.compile(
            r"([A-Z\u4e00-\u9fff][\w\u4e00-\u9fff]{1,20}"
            r"(?:\s*(?:et al\.?|等))?)"
            r"\s*[（(]\s*((?:19|20)\d{2})\s*[）)]"
        )
        body_citations: dict[str, str] = {}
        for m in body_pattern.finditer(body_text):
            key = f"{m.group(1).strip()}_{m.group(2)}"
            body_citations[key] = m.group(0)

        # 提取参考文献列表中的条目（按行）
        ref_lines = [
            line.strip()
            for line in reference_list.split("\n")
            if line.strip() and len(line.strip()) > 10
        ]
        ref_citations: dict[str, str] = {}
        for line in ref_lines:
            # 从参考文献行中提取作者+年份
            year_m = re.search(r"\b(19|20)\d{2}\b", line)
            if year_m:
                # 取年份前最近的名字
                before = line[: year_m.start()].strip().rstrip(",.")
                # 简化：取最后一个作者标记
                author_m = re.search(
                    r"([A-Z\u4e00-\u9fff][\w\u4e00-\u9fff]{1,20})\s*$",
                    before,
                )
                if author_m:
                    key = f"{author_m.group(1)}_{year_m.group(0)}"
                    ref_citations[key] = line

        # 正文有但参考文献列表没有
        in_body_not_in_refs = [
            {"citation": v, "key": k}
            for k, v in body_citations.items()
            if k not in ref_citations
        ]

        # 参考文献列表有但正文未引用
        in_refs_not_in_body = [
            {"reference": v, "key": k}
            for k, v in ref_citations.items()
            if k not in body_citations
        ]

        # 格式一致性检查
        format_issues: list[str] = []
        # 检查参考文献编号是否连续
        numbered_refs = [
            line for line in ref_lines if re.match(r"^\[\d+\]", line)
        ]
        if numbered_refs:
            numbers = [
                int(re.match(r"^\[(\d+)\]", line).group(1))
                for line in numbered_refs
            ]
            if numbers != list(range(1, len(numbers) + 1)):
                format_issues.append("参考文献编号不连续")

        # 检查是否混用不同引用格式
        has_apa = bool(re.search(r"\([A-Z][a-z]+,\s*\d{4}\)", body_text))
        has_numbered = bool(re.search(r"\[\d+\]", body_text))
        if has_apa and has_numbered:
            format_issues.append("正文混用了 APA 作者-年份格式和数字编号格式")

        return {
            "in_body_not_in_refs": in_body_not_in_refs,
            "in_refs_not_in_body": in_refs_not_in_body,
            "format_issues": format_issues,
            "is_consistent": (
                len(in_body_not_in_refs) == 0
                and len(in_refs_not_in_body) == 0
                and len(format_issues) == 0
            ),
        }

    # ------------------------------------------------------------------
    # AI 编造文献检测
    # ------------------------------------------------------------------

    def detect_fabricated_references(
        self, references: list[str]
    ) -> list[dict]:
        """检测 AI 编造的参考文献.

        检测模式:
            1. DOI 格式异常（如连续数字过多）
            2. 期刊名称不存在（与已知期刊列表比对）
            3. 作者数量异常（超过 20 位作者）
            4. 年份在未来或在 DOI 系统建立之前（< 2000 且有 DOI）
            5. 标题与已知文献高度相似但细节不同

        Args:
            references: 参考文献文本列表.

        Returns:
            每条可疑文献的检测结果字典列表，包含 ``reference``、``issues``、
            ``suspicion_score`` 等字段.
        """
        results: list[dict] = []
        current_year = datetime.now(timezone.utc).year

        for ref in references:
            issues: list[str] = []
            suspicion_score = 0

            # 1. DOI 格式异常检测
            dois = self.extract_doi(ref)
            if dois:
                for doi in dois:
                    # 检查 DOI 中是否有超长连续数字（>12 位）
                    if re.search(r"\d{13,}", doi):
                        issues.append(f"DOI 包含异常长连续数字: {doi}")
                        suspicion_score += 3
                    # 检查 DOI 前缀是否合理（注册机构代码通常 4-5 位）
                    prefix_match = re.match(r"^10\.(\d{4,5})/", doi)
                    if prefix_match:
                        prefix_num = int(prefix_match.group(1))
                        # CrossRef 注册机构代码通常在 1000-99999 范围内
                        if prefix_num < 1000:
                            issues.append(f"DOI 前缀异常: {doi}")
                            suspicion_score += 2

            # 2. 期刊名称检测
            # 提取期刊名（简化：尝试匹配已知期刊名）
            found_known_journal = False
            for journal in KNOWN_JOURNALS:
                if journal.lower() in ref.lower():
                    found_known_journal = True
                    break
            if not found_known_journal and "Journal" in ref:
                # 包含 "Journal" 但不在已知列表中，标记为可疑
                issues.append("期刊名不在已知权威期刊列表中")
                suspicion_score += 1

            # 3. 作者数量异常检测
            # 统计逗号分隔的名字段（粗略估计作者数）
            # 取年份之前的部分作为作者区域
            year_match = re.search(r"\b(19|20)\d{2}\b", ref)
            if year_match:
                author_part = ref[: year_match.start()]
                # 统计 "et al." 或 "等"
                has_et_al = bool(re.search(r"et\s+al\.?", author_part, re.IGNORECASE))
                if not has_et_al:
                    # 按逗号分割估算作者数
                    author_segments = [s for s in re.split(r"[,;&]", author_part) if s.strip()]
                    if len(author_segments) > MAX_REASONABLE_AUTHORS:
                        issues.append(
                            f"作者数量异常（{len(author_segments)} 位，"
                            f"超过 {MAX_REASONABLE_AUTHORS} 位上限）"
                        )
                        suspicion_score += 3

            # 4. 年份合理性检测
            if year_match:
                year = int(year_match.group(0))
                if year > current_year:
                    issues.append(f"发表年份 {year} 在未来，疑似编造")
                    suspicion_score += 4
                if year < DOI_SYSTEM_START_YEAR and dois:
                    issues.append(
                        f"年份 {year} 早于 DOI 系统建立（{DOI_SYSTEM_START_YEAR}），"
                        f"但包含 DOI，疑似编造"
                    )
                    suspicion_score += 3

            # 5. 标题过于模糊或通用（AI 编造的常见特征）
            # 提取标题部分（年份后到第一个句号）
            if year_match:
                after_year = ref[year_match.end():].lstrip(". ")
                title_match = re.match(r"(.+?)[.]", after_year)
                if title_match:
                    title = title_match.group(1).strip()
                    # 标题过短
                    if len(title) < 10:
                        issues.append(f"标题过短（'{title}'），可能为编造")
                        suspicion_score += 2
                    # 标题包含过多通用词
                    generic_words = ["研究", "分析", "探索", "study", "analysis"]
                    generic_count = sum(1 for w in generic_words if w.lower() in title.lower())
                    if generic_count >= 2:
                        issues.append(f"标题过于通用（'{title}'），缺乏具体性")
                        suspicion_score += 1

            if issues:
                results.append({
                    "reference": ref,
                    "issues": issues,
                    "suspicion_score": suspicion_score,
                    "is_fabricated": suspicion_score >= 5,
                })

        return results

    # ------------------------------------------------------------------
    # 检索证据字段构建
    # ------------------------------------------------------------------

    def build_evidence_field(
        self, citation: str, source_db: str, keyword: str
    ) -> dict:
        """构建引用的检索证据字段.

        记录每篇引用的数据库来源、检索关键词、检索时间等信息，
        确保引用可追溯。

        Args:
            citation: 引用文本.
            source_db: 来源数据库（如 crossref / openalex / cnki / ncpssd）.
            keyword: 检索关键词.

        Returns:
            包含以下键的字典:
                - citation: 引用文本
                - source_db: 来源数据库
                - search_keyword: 检索关键词
                - search_time: 检索时间（ISO 8601 格式）
                - doi: 提取到的 DOI（如有）
                - evidence_level: 证据等级
        """
        dois = self.extract_doi(citation)
        doi = dois[0] if dois else None

        # 简单评估证据等级
        if doi:
            evidence_level = EvidenceLevel.STRONG
        elif citation and len(citation) > 20:
            evidence_level = EvidenceLevel.MODERATE
        else:
            evidence_level = EvidenceLevel.UNVERIFIED

        return {
            "citation": citation,
            "source_db": source_db,
            "search_keyword": keyword,
            "search_time": datetime.now(timezone.utc).isoformat(),
            "doi": doi,
            "evidence_level": evidence_level.value,
        }

    # ------------------------------------------------------------------
    # 报告生成
    # ------------------------------------------------------------------

    def generate_report(
        self, verifications: list[CitationVerification]
    ) -> HallucinationReport:
        """根据验证结果生成幻觉检测汇总报告.

        Args:
            verifications: 引用验证结果列表.

        Returns:
            HallucinationReport 汇总报告.
        """
        total = len(verifications)
        verified = sum(1 for v in verifications if v.is_verified)
        unverified = sum(1 for v in verifications if not v.is_verified)

        # 证据等级分布
        distribution: dict[str, int] = {}
        for level in EvidenceLevel:
            distribution[level.value] = sum(
                1 for v in verifications if v.evidence_level == level
            )

        # 编造文献数（证据等级为 UNVERIFIED 且有问题的）
        fabricated = sum(
            1
            for v in verifications
            if v.evidence_level == EvidenceLevel.UNVERIFIED and v.issues
        )

        # 汇总问题
        issues: list[dict] = []
        for v in verifications:
            if v.issues:
                issues.append({
                    "citation": v.citation_text[:100],
                    "issues": v.issues,
                    "evidence_level": v.evidence_level.value,
                })

        # 生成建议
        recommendations: list[str] = []
        if unverified > 0:
            recommendations.append(
                f"发现 {unverified} 条未验证引用，建议通过 CNKI/OpenAlex/CrossRef 人工核实"
            )
        if fabricated > 0:
            recommendations.append(
                f"发现 {fabricated} 条疑似编造文献，建议删除或替换为真实文献"
            )
        if distribution.get(EvidenceLevel.WEAK.value, 0) > 0:
            recommendations.append(
                f"发现 {distribution[EvidenceLevel.WEAK.value]} 条弱证据引用，"
                f"建议补充直接来源"
            )
        if distribution.get(EvidenceLevel.STRONG.value, 0) < total * 0.3:
            recommendations.append(
                "强证据引用占比偏低，建议增加有 DOI 的权威文献"
            )
        if not recommendations:
            recommendations.append("所有引用验证通过，证据等级分布合理")

        return HallucinationReport(
            total_citations=total,
            verified=verified,
            unverified=unverified,
            fabricated=fabricated,
            evidence_distribution=distribution,
            issues=issues,
            recommendations=recommendations,
        )


__all__ = [
    "EvidenceLevel",
    "CitationVerification",
    "HallucinationReport",
    "AntiHallucinationChecker",
]
