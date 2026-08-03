"""统一文献检索管理器.

整合 CNKI、Semantic Scholar 和 arXiv 三个检索引擎，
提供统一的检索接口，自动调度多源检索。

Usage:
    manager = LiteratureSearchManager(
        cnki_cookie="...",
        ss_api_key="...",
    )
    results = await manager.search_all(
        topic="地方政府债务",
        region="中国",
        content="空间溢出",
        year_start="2015",
        year_end="2024",
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import litellm
    # 避免 litellm 拉取模型成本表时触发 SSL 警告
    litellm.model_cost_default_url = ""
    _LITELLM_AVAILABLE = True
except ImportError:  # pragma: no cover - litellm 为可选依赖
    litellm = None  # type: ignore[assignment]
    _LITELLM_AVAILABLE = False

from scholarpilot.mcp.servers.cnki import CNKISearchResult, CNKIPaper
from scholarpilot.mcp.servers.semantic_scholar import (
    SemanticScholarEngine,
    SSSearchResult,
    SSPaper,
)
from scholarpilot.mcp.servers.arxiv import ArxivEngine, ArxivSearchResult, ArxivPaper
from scholarpilot.mcp.servers.wos import WoSEngine, WoSSearchResult, WoSPaper
from scholarpilot.mcp.servers.chinaxiv import ChinaXivEngine, ChinaXivSearchResult, ChinaXivPaper
from scholarpilot.mcp.servers.pubscholar import PubScholarEngine, PubScholarSearchResult, PubScholarPaper
from scholarpilot.tools.chinese_search import (
    ChineseLiteratureManager,
    ChineseSearchResult,
    UnifiedChinesePaper,
)
from scholarpilot.utils.vpn import VPNStatus

logger = logging.getLogger(__name__)


@dataclass
class UnifiedPaper:
    """统一的论文数据模型.

    整合来自不同源的论文数据，统一字段。
    """

    source: str = ""  # cnki / semantic_scholar / arxiv
    title: str = ""
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    venue: str = ""  # 期刊/来源
    citation_count: int = 0
    url: str = ""
    doi: str = ""
    arxiv_id: str = ""
    keywords: list[str] = field(default_factory=list)
    language: str = ""  # zh / en
    raw: dict[str, Any] = field(default_factory=dict)  # 原始数据

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "citation_count": self.citation_count,
            "url": self.url,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "keywords": self.keywords,
            "language": self.language,
        }


@dataclass
class UnifiedSearchResult:
    """多源统一检索结果."""

    topic: str = ""
    chinese_result: Optional[ChineseSearchResult] = None  # 中文文献（CNKI+万方+NCPSSD）
    ss_result: Optional[SSSearchResult] = None
    arxiv_result: Optional[ArxivSearchResult] = None
    wos_result: Optional[WoSSearchResult] = None  # Web of Science（VPN/Session）
    chinaxiv_result: Optional[ChinaXivSearchResult] = None  # ChinaXiv 预印本
    pubscholar_result: Optional[PubScholarSearchResult] = None  # PubScholar OA
    all_papers: list[UnifiedPaper] = field(default_factory=list)
    total_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "chinese": self.chinese_result.to_dict() if self.chinese_result else None,
            "semantic_scholar": self.ss_result.to_dict() if self.ss_result else None,
            "arxiv": self.arxiv_result.to_dict() if self.arxiv_result else None,
            "wos": self.wos_result.to_dict() if self.wos_result else None,
            "chinaxiv": self.chinaxiv_result.to_dict() if self.chinaxiv_result else None,
            "pubscholar": self.pubscholar_result.to_dict() if self.pubscholar_result else None,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.all_papers],
        }


class LiteratureSearchManager:
    """统一文献检索管理器.

    整合 CNKI、Semantic Scholar 和 arXiv 三个引擎，
    提供统一的检索接口。

    对于英文文献源（Semantic Scholar、arXiv），自动将中文主题翻译为英文。
    内置财政学/经济学常见术语中英映射表，也支持传入英文主题。

    Usage:
        manager = LiteratureSearchManager(
            cnki_cookie="your_cookie",
            ss_api_key="your_key",
        )
        results = await manager.search_all(
            topic="地方政府债务",
            region="中国",
            content="空间溢出",
            year_start="2015",
            year_end="2024",
        )
    """

    # 降级缓存：此表为 LLM 动态翻译失败（无 API Key / 调用异常）时的降级回退方案，
    # 主要翻译机制为 LLM 动态翻译（见 _translate_to_english_llm）。
    # 仅覆盖财政学/经济学常见术语，无法覆盖任意学科；LLM 可用时将被优先调用。
    TERM_MAP: dict[str, str] = {
        # 核心概念
        "地方政府债务": "local government debt",
        "政府债务": "government debt",
        "债务风险": "debt risk",
        "财政风险": "fiscal risk",
        "财政政策": "fiscal policy",
        "财政分权": "fiscal decentralization",
        "财政支出": "fiscal expenditure",
        "财政收入": "fiscal revenue",
        "税收": "taxation",
        "税制改革": "tax reform",
        "预算": "budget",
        "预算绩效": "budget performance",
        "零基预算": "zero-based budgeting",
        "转移支付": "transfer payment",
        "土地财政": "land finance",
        "城投债": "urban investment bond",
        "专项债": "special purpose bond",
        "隐性债务": "implicit debt",
        "债务置换": "debt swap",
        # 区域/对象
        "中国": "China",
        "省级": "provincial",
        "市级": "municipal",
        "县级": "county-level",
        "地方政府": "local government",
        "中央政府": "central government",
        # 研究内容/方法
        "空间溢出": "spatial spillover",
        "溢出效应": "spillover effect",
        "经济增长": "economic growth",
        "高质量发展": "high-quality development",
        "实证": "empirical",
        "面板数据": "panel data",
        "空间计量": "spatial econometrics",
        "双重差分": "difference-in-differences",
        "工具变量": "instrumental variable",
        "固定效应": "fixed effects",
        "随机效应": "random effects",
        # 宏观经济
        "通货膨胀": "inflation",
        "货币政策": "monetary policy",
        "汇率": "exchange rate",
        "贸易": "trade",
        "消费": "consumption",
        "投资": "investment",
        "就业": "employment",
        "收入分配": "income distribution",
        "共同富裕": "common prosperity",
        # 公共管理
        "公共服务": "public service",
        "环境治理": "environmental governance",
        "碳中和": "carbon neutrality",
        "数字化转型": "digital transformation",
    }

    # 不相关主题黑名单：命中任一词的论文将被硬过滤丢弃，不受兜底保护
    # 注意：此黑名单为语义过滤（SemanticRelevanceFilter）的补充兜底，仅包含
    # 跨学科通用不相关主题（医学/农业/政治等），不含任何特定研究主题的过滤项。
    # 主题相关性判断主要依赖嵌入语义相似度，此列表仅处理明显跨域噪声。
    _IRRELEVANT_TOPIC_BLOCKLIST: tuple[str, ...] = (
        # 医学/疫情类
        "covid-19", "covid19", "coronavirus",
        "新冠", "疫情", "肺炎", "临床特征", "临床分析", "心理反应",
        "结核", "tuberculosis", "耐药", "drug resistance",
        # 农业/机器人类
        "采摘机器人", "红花", "农业机器人",
        "harvest robot", "safflower",
        # 医疗旅游类
        "医疗旅游", "文化旅游标准化", "medical tourism",
        # 国际关系/政治类
        "axis of allies", "us-japan alliance",
        "antitrust interoperability",
        # 结核病/抗菌类
        "mycobacterium tuberculosis", "antituberculosis", "drug resistance in",
    )

    def __init__(
        self,
        cnki_cookie: str = "",
        ss_api_key: str = "",
        wos_api_key: str = "",
        wos_sid: str = "",
        use_playwright: bool = False,
        timeout: int = 30,
        vpn_status: Optional[VPNStatus] = None,
    ) -> None:
        """初始化统一文献检索管理器.

        Args:
            cnki_cookie: CNKI 登录 Cookie（可选）。
            ss_api_key: Semantic Scholar API Key。
            wos_api_key: Web of Science Clarivate API Key（可选，优先使用）。
            wos_sid: WoS Session ID（从浏览器登录获取，可选）。
            use_playwright: 是否启用 Playwright CNKI 增强（需安装 playwright）。
            timeout: 请求超时秒数。
            vpn_status: VPN 连接状态。传入已检测的 VPNStatus，
                        CNKI 和万方将使用机构 IP 认证模式。
                        如不传入，需在调用 search_all 前手动设置。
        """
        # 中文文献：ChineseLiteratureManager（NCPSSD + CNKI + 万方 多源降级）
        # 传入 vpn_status 启用 CNKI/万方 机构 IP 认证
        self.chinese_manager = ChineseLiteratureManager(
            cnki_cookie=cnki_cookie,
            use_playwright=use_playwright,
            timeout=timeout,
            vpn_status=vpn_status,
        )
        self.ss_engine = SemanticScholarEngine(api_key=ss_api_key, timeout=timeout)
        self.arxiv_engine = ArxivEngine(timeout=timeout)
        # WoS 引擎：双模式（API Key 优先，其次 SID）
        self.wos_engine = WoSEngine(
            api_key=wos_api_key,
            sid=wos_sid,
            timeout=timeout,
        )
        # ChinaXiv 预印本引擎（免费，无需认证）
        self.chinaxiv_engine = ChinaXivEngine(timeout=timeout)
        # PubScholar OA 引擎（免费，SHA1 签名认证）
        self.pubscholar_engine = PubScholarEngine(timeout=timeout)

        # 保存 VPN 状态
        self.vpn_status = vpn_status

        # LLM 翻译/同义词扩展缓存：text -> result
        # 用于避免对同一中文文本重复调用 LLM，降低延迟与费用
        self._translation_cache: dict[str, str] = {}
        self._synonym_cache: dict[str, list[str]] = {}

        # 智谱 GLM-4 配置：从环境变量读取 API Key
        self._zhipu_api_key: str = os.environ.get("SCHOLAR_ZHIPU_API_KEY", "")
        self._zhipu_model: str = "openai/glm-4"
        self._zhipu_api_base: str = "https://open.bigmodel.cn/api/paas/v4/"

    def _translate_to_english_static(self, text: str) -> str:
        """基于静态 TERM_MAP 的降级翻译（同步）.

        对于映射表中已有的术语，直接替换；对于未映射的中文，保留原文
        （Semantic Scholar 也能处理部分中文搜索）。
        """
        result = text
        for cn_term, en_term in self.TERM_MAP.items():
            if cn_term in result:
                result = result.replace(cn_term, en_term)

        # 清理多余空格
        result = " ".join(result.split())
        return result

    async def _translate_to_english_llm(self, text: str) -> Optional[str]:
        """通过 LLM（智谱 GLM-4）将中文文本翻译为英文学术搜索词.

        使用 litellm.acompletion 调用智谱 GLM-4 模型，使任意学科的中英文翻译
        都能工作，不再受限于静态 TERM_MAP 的覆盖范围。

        Args:
            text: 中文文本（研究主题/区域/内容）。

        Returns:
            翻译后的纯英文短语；失败或不可用时返回 None，由调用方回退到静态映射。
        """
        if not text or not text.strip():
            return None

        # 命中缓存直接返回，避免重复调用 LLM
        if text in self._translation_cache:
            return self._translation_cache[text]

        # 若 litellm 不可用或未配置 API Key，直接返回 None 走静态降级
        if not _LITELLM_AVAILABLE or not self._zhipu_api_key:
            return None

        prompt = (
            "你是一位学术文献检索专家。请将下面的中文研究主题翻译为英文学术搜索词，"
            "用于在 Semantic Scholar / arXiv / Web of Science 等英文文献库中检索。\n"
            "要求：\n"
            "1. 输出纯英文短语，使用学术界通用术语；\n"
            "2. 不要添加任何解释、标点符号前缀或引号；\n"
            "3. 保持简洁，保留关键概念之间的逻辑关系（如 AND 连接）；\n"
            "4. 若输入已是英文，原样输出。\n\n"
            f"中文输入：{text}\n"
            "英文输出："
        )

        try:
            response = await litellm.acompletion(  # type: ignore[union-attr]
                model=self._zhipu_model,
                api_base=self._zhipu_api_base,
                api_key=self._zhipu_api_key,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=128,
                timeout=15,
            )
            en_text = response["choices"][0]["message"]["content"].strip()
            # 清理：去掉可能的引号、换行与多余空格
            en_text = en_text.strip('"\'` \n\r\t')
            en_text = " ".join(en_text.split())
            if not en_text:
                return None
            # 缓存结果
            self._translation_cache[text] = en_text
            return en_text
        except Exception as e:
            logger.debug("LLM 翻译失败，将回退到静态 TERM_MAP: %s", e)
            return None

    async def _translate_to_english(self, text: str) -> str:
        """将中文术语翻译为英文（LLM 优先，静态 TERM_MAP 降级）.

        优先调用 LLM（智谱 GLM-4）进行动态翻译，使任意学科的中英文翻译都能工作；
        LLM 不可用或调用失败时，回退到静态 TERM_MAP 术语映射表。

        Args:
            text: 中文文本。

        Returns:
            英文搜索词。
        """
        # 优先：LLM 动态翻译
        en_text = await self._translate_to_english_llm(text)
        if en_text:
            return en_text

        # 降级：静态 TERM_MAP 替换
        return self._translate_to_english_static(text)

    async def close(self) -> None:
        """关闭所有引擎."""
        await self.chinese_manager.close()
        await self.ss_engine.close()
        await self.arxiv_engine.close()
        await self.wos_engine.close()
        await self.chinaxiv_engine.close()
        await self.pubscholar_engine.close()

    async def search_all(
        self,
        topic: str,
        region: str = "中国",
        content: str = "",
        year_start: str = "2015",
        year_end: str = "2024",
        max_per_source: int = 20,
        include_arxiv: bool = True,
        include_wos: bool = True,
        include_oa: bool = True,
    ) -> UnifiedSearchResult:
        """执行多源统一检索.

        同时检索中文文献（CNKI+万方+NCPSSD）、Semantic Scholar、
        Web of Science（如已配置）、ChinaXiv、PubScholar 和 arXiv，
        并将结果整合为统一的论文列表。

        Args:
            topic: 核心主题（中文，如"地方政府债务"）。
            region: 研究区域。
            content: 研究内容。
            year_start: 起始年份。
            year_end: 结束年份。
            max_per_source: 每个数据源的最大返回数。
            include_arxiv: 是否检索 arXiv。
            include_wos: 是否检索 Web of Science（需配置 API Key 或 SID）。
            include_oa: 是否检索 OA 源（ChinaXiv + PubScholar）。

        Returns:
            UnifiedSearchResult: 统一检索结果。
        """
        result = UnifiedSearchResult(topic=topic)

        # 构建并行检索任务（arXiv 串行，因为3秒间隔限制）
        task_names: list[str] = ["chinese", "ss"]
        task_coros: list = [
            self._search_chinese(topic, region, content, year_start, year_end, max_per_source),
            self._search_semantic_scholar(topic, region, content, year_start, year_end, max_per_source),
        ]

        # WoS 仅在引擎可用时加入
        if include_wos and self.wos_engine.is_available:
            task_names.append("wos")
            task_coros.append(self._search_wos(topic, region, content, year_start, year_end, max_per_source))

        # OA 源（ChinaXiv + PubScholar）
        if include_oa:
            task_names.append("chinaxiv")
            task_coros.append(self._search_chinaxiv(topic, year_start, year_end, max_per_source))
            task_names.append("pubscholar")
            task_coros.append(self._search_pubscholar(topic, max_per_source))

        # 并行执行所有任务
        task_results = await asyncio.gather(*task_coros, return_exceptions=True)

        # 按名称处理结果
        for name, res in zip(task_names, task_results):
            if name == "chinese":
                if isinstance(res, Exception):
                    logger.error(f"Chinese literature search error: {res}")
                    result.chinese_result = ChineseSearchResult(query=topic)
                else:
                    result.chinese_result = res
            elif name == "ss":
                if isinstance(res, Exception):
                    logger.error(f"Semantic Scholar search error: {res}")
                    result.ss_result = SSSearchResult(query=topic, total_count=0)
                else:
                    result.ss_result = res
            elif name == "wos":
                if isinstance(res, Exception):
                    logger.error(f"WoS search error: {res}")
                    result.wos_result = WoSSearchResult(query=topic, error=str(res))
                else:
                    result.wos_result = res
            elif name == "chinaxiv":
                if isinstance(res, Exception):
                    logger.error(f"ChinaXiv search error: {res}")
                    result.chinaxiv_result = ChinaXivSearchResult(query=topic, error=str(res))
                else:
                    result.chinaxiv_result = res
            elif name == "pubscholar":
                if isinstance(res, Exception):
                    logger.error(f"PubScholar search error: {res}")
                    result.pubscholar_result = PubScholarSearchResult(query=topic, error=str(res))
                else:
                    result.pubscholar_result = res

        # 串行检索 arXiv（3秒间隔限制）
        if include_arxiv:
            arxiv_result = await self._search_arxiv(topic, content, max_per_source)
            result.arxiv_result = arxiv_result

        # 整合所有论文
        result.all_papers = await self._merge_papers(result)

        # 语义嵌入过滤（第三代 Bi-Encoder 初筛 + 第四代 Cross-Encoder 精排）
        # 两阶段架构：Bi-Encoder 快速初筛 → Cross-Encoder 精确重排序
        if result.all_papers and topic and len(result.all_papers) > 10:
            try:
                from scholarpilot.tools.citation_manager import get_semantic_filter
                sf = get_semantic_filter()
                # 检索阶段使用宽松阈值，只过滤最不相关的
                kept, filtered, method = await sf.filter_papers(
                    result.all_papers, topic,
                    threshold=sf.SEARCH_THRESHOLD,
                )
                if method == "semantic" and filtered:
                    logger.info(
                        "语义过滤(检索阶段): %d篇 → %d篇 (过滤%d篇, 阈值=%.2f)",
                        len(result.all_papers), len(kept),
                        len(filtered), sf.SEARCH_THRESHOLD,
                    )
                elif method == "trss_fallback":
                    logger.info("语义过滤降级到TRSS: 保留%d篇", len(kept))

                # Cross-Encoder 精排：对 Bi-Encoder 保留的论文进行精确重排序
                if method in ("semantic", "trss_fallback") and len(kept) > 5:
                    try:
                        from scholarpilot.tools.citation_manager import get_cross_encoder_reranker
                        reranker = get_cross_encoder_reranker()
                        reranked, dropped, rmethod = await reranker.rerank(
                            kept, topic, drop_bottom=True,
                        )
                        if rmethod != "skipped" and dropped:
                            logger.info(
                                "Cross-Encoder精排(检索阶段%s): %d篇→%d篇 (移除%d篇)",
                                rmethod, len(kept), len(reranked), len(dropped),
                            )
                        kept = reranked
                    except Exception as re:
                        logger.warning(f"Cross-Encoder精排异常(非致命): {re}")

                result.all_papers = kept
            except Exception as e:
                logger.warning(f"语义过滤异常(非致命): {e}")

        result.total_count = len(result.all_papers)

        return result

    async def _search_chinese(
        self, topic: str, region: str, content: str,
        year_start: str, year_end: str, max_results: int,
    ) -> ChineseSearchResult:
        """执行中文文献检索（NCPSSD + CNKI 多源降级）.

        使用 ChineseLiteratureManager 并行检索 NCPSSD（免费、稳定）
        和 CNKI（可选 Playwright 增强），自动合并去重。
        """
        return await self.chinese_manager.search(
            topic=topic,
            region=region,
            content=content,
            year_start=year_start,
            year_end=year_end,
            max_per_source=max_results,
        )

    async def _search_semantic_scholar(
        self, topic: str, region: str, content: str,
        year_start: str, year_end: str, max_results: int,
    ) -> SSSearchResult:
        """执行 Semantic Scholar 检索.

        自动将中文主题翻译为英文，因为 Semantic Scholar 主要是英文文献库。
        """
        # 翻译为英文（LLM 优先，静态 TERM_MAP 降级）
        en_topic = await self._translate_to_english(topic)
        en_region = await self._translate_to_english(region)
        en_content = await self._translate_to_english(content)

        query = SemanticScholarEngine.build_query_from_topic(
            topic=en_topic, region=en_region, content=en_content,
        )
        year_filter = f"{year_start}-{year_end}" if year_start and year_end else ""

        return await self.ss_engine.search(
            query=query,
            limit=max_results,
            year=year_filter,
            fields_of_study="Economics",
        )

    async def _search_arxiv(
        self, topic: str, content: str, max_results: int,
    ) -> ArxivSearchResult:
        """执行 arXiv 检索.

        自动将中文主题翻译为英文，因为 arXiv 主要是英文预印本库。
        """
        # 翻译为英文（LLM 优先，静态 TERM_MAP 降级）
        en_topic = await self._translate_to_english(topic)

        # 构建 arXiv 查询串（使用经济学分类）
        query = ArxivEngine.build_query(
            all_fields=en_topic,
            category="econ.GN",  # General Economics
        )

        if not query:
            query = f"all:{en_topic}"

        return await self.arxiv_engine.search(
            search_query=query,
            max_results=max_results,
            sort_by="submittedDate",
        )

    async def _search_wos(
        self, topic: str, region: str, content: str,
        year_start: str, year_end: str, max_results: int,
    ) -> WoSSearchResult:
        """执行 Web of Science 检索.

        自动将中文主题翻译为英文，因为 WoS 主要是英文文献库。
        使用 WoS 查询语言 (WQL) 构建检索式。
        """
        # 翻译为英文（LLM 优先，静态 TERM_MAP 降级）
        en_topic = await self._translate_to_english(topic)
        en_region = await self._translate_to_english(region)
        en_content = await self._translate_to_english(content)

        # 构建 WoS 查询式
        query = WoSEngine.build_query_from_topic(
            topic=en_topic,
            region=en_region,
            content=en_content,
            year_start=year_start,
            year_end=year_end,
        )

        return await self.wos_engine.search(
            query=query,
            limit=max_results,
        )

    async def _search_chinaxiv(
        self, topic: str, year_start: str, year_end: str, max_results: int,
    ) -> ChinaXivSearchResult:
        """执行 ChinaXiv 预印本检索.

        ChinaXiv 是中科院预印本平台，主要收录中文预印本。
        使用原始中文关键词检索。
        """
        return await self.chinaxiv_engine.search(
            query=topic,
            limit=max_results,
            year_start=year_start,
            year_end=year_end,
        )

    async def _search_pubscholar(
        self, topic: str, max_results: int,
    ) -> PubScholarSearchResult:
        """执行 PubScholar OA 资源检索.

        PubScholar 是公共学术 OA 平台，支持中英文检索。
        使用原始中文关键词检索。
        """
        return await self.pubscholar_engine.search(
            query=topic,
            limit=max_results,
            lang="zh",
        )

    async def _merge_papers(self, result: UnifiedSearchResult) -> list[UnifiedPaper]:
        """整合来自不同源的论文为统一列表."""
        papers: list[UnifiedPaper] = []

        # 中文文献（NCPSSD + CNKI 合并后的结果）
        if result.chinese_result:
            for p in result.chinese_result.papers:
                papers.append(UnifiedPaper(
                    source=p.source,  # "cnki" 或 "ncpssd"
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=p.year,
                    venue=p.journal,
                    url=p.url,
                    doi=p.doi,
                    keywords=p.keywords,
                    citation_count=p.cited_count,
                    language="zh",
                    raw=p.to_dict(),
                ))

        # Semantic Scholar 论文
        if result.ss_result:
            for p in result.ss_result.papers:
                papers.append(UnifiedPaper(
                    source="semantic_scholar",
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=str(p.year) if p.year else "",
                    venue=p.venue or p.journal_name,
                    citation_count=p.citation_count,
                    url=p.url,
                    doi=p.doi,
                    arxiv_id=p.arxiv_id,
                    keywords=p.fields_of_study,
                    language="en",
                    raw=p.to_dict(),
                ))

        # arXiv 论文
        if result.arxiv_result:
            for p in result.arxiv_result.papers:
                papers.append(UnifiedPaper(
                    source="arxiv",
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=p.published[:4] if p.published else "",
                    venue=p.primary_category,
                    url=p.abs_url,
                    doi=p.doi,
                    arxiv_id=p.arxiv_id,
                    keywords=p.categories,
                    language="en",
                    raw=p.to_dict(),
                ))

        # Web of Science 论文
        if result.wos_result:
            for p in result.wos_result.papers:
                papers.append(UnifiedPaper(
                    source="wos",
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=str(p.year) if p.year else "",
                    venue=p.journal,
                    citation_count=p.cited_by_count,
                    url=p.url,
                    doi=p.doi,
                    keywords=p.keywords + p.keywords_plus,
                    language="en",
                    raw=p.to_dict(),
                ))

        # ChinaXiv 预印本
        if result.chinaxiv_result:
            for p in result.chinaxiv_result.papers:
                papers.append(UnifiedPaper(
                    source="chinaxiv",
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=p.year,
                    venue=p.subject,
                    url=p.page_url,
                    doi=p.doi,
                    keywords=p.keywords,
                    language="zh",
                    raw=p.to_dict(),
                ))

        # PubScholar OA 论文
        if result.pubscholar_result:
            for p in result.pubscholar_result.papers:
                papers.append(UnifiedPaper(
                    source="pubscholar",
                    title=p.title,
                    abstract=p.abstract,
                    authors=p.authors,
                    year=p.year,
                    venue=p.source,
                    citation_count=p.cite_count,
                    url=p.page_url,
                    doi=p.doi,
                    keywords=p.keywords,
                    language=p.language or "zh",
                    raw=p.to_dict(),
                ))

        # 跨源去重：按 DOI（大小写不敏感）和归一化标题去重
        seen_dois: set[str] = set()
        seen_titles: set[str] = set()
        deduplicated: list[UnifiedPaper] = []

        for paper in papers:
            # DOI 去重（大小写不敏感）：若 DOI 已存在则跳过
            doi_key = paper.doi.strip().lower() if paper.doi else ""
            if doi_key and doi_key in seen_dois:
                continue
            # 归一化标题去重：移除所有非字母数字字符并转为小写
            normalized_title = re.sub(
                r'[^a-zA-Z0-9\u4e00-\u9fff]', '', paper.title
            ).lower()
            if normalized_title and normalized_title in seen_titles:
                continue
            # 记录已见的 DOI 和标题
            if doi_key:
                seen_dois.add(doi_key)
            if normalized_title:
                seen_titles.add(normalized_title)
            deduplicated.append(paper)

        papers = deduplicated

        # 主题相关性过滤（如果有可用主题）
        topic = getattr(result, "topic", "")
        if topic:
            papers = await self._filter_by_relevance(papers, topic)

        return papers

    def _expand_topic_synonyms_static(self, topic_words: set[str]) -> set[str]:
        """基于静态 synonym_map 的降级同义词扩展（同步）.

        将主题关键词扩展为包含相关同义词的集合，提升主题相关性匹配的召回率。
        仅覆盖财政学/经济学/数字化转型等领域常见术语。
        """
        # 降级缓存：此表为 LLM 同义词扩展失败（无 API Key / 调用异常）时的降级回退方案，
        # 主要同义词扩展机制为 LLM 动态生成（见 _expand_topic_synonyms 中的 LLM 分支）。
        # 仅覆盖财政学/经济学/数字化转型等领域常见术语；LLM 可用时将被优先调用。
        synonym_map: dict[str, list[str]] = {
            "数字化转型": ["数字技术", "数字化", "信息化", "人工智能", "大数据"],
            "数字化": ["数字技术", "数字化转型", "信息化", "人工智能"],
            "地方政府债务": ["地方债", "城投债", "隐性债务", "政府债务", "债务风险"],
            "政府债务": ["地方政府债务", "地方债", "国债", "债务"],
            "债务风险": ["债务危机", "财政风险", "违约风险"],
            "财政政策": ["财政支出", "财政收入", "积极财政", "减税"],
            "财政分权": ["分税制", "财权事权", "转移支付"],
            "经济增长": ["经济发展", "gdp", "增长"],
            "高质量发展": ["发展质量", "经济质量", "可持续"],
            "碳中和": ["碳排放", "碳达峰", "低碳", "绿色"],
            "digital transformation": ["digital", "digitization", "digitalization", "ai", "big data"],
            "debt": ["borrowing", "liability", "deficit"],
            "fiscal": ["budget", "tax", "revenue", "expenditure"],
        }

        expanded = set(topic_words)
        for word in topic_words:
            if word in synonym_map:
                expanded.update(synonym_map[word])

        return expanded

    async def _expand_topic_synonyms_llm(
        self, topic_words: set[str],
    ) -> Optional[set[str]]:
        """通过 LLM（智谱 GLM-4）生成同义词扩展.

        给定研究主题关键词，调用 LLM 生成 5-10 个相关同义词/近义词（中英文均可），
        替代静态 synonym_map，使任意学科的主题都能进行同义词扩展。

        Args:
            topic_words: 原始主题关键词集合。

        Returns:
            扩展后的关键词集合（包含原始词与 LLM 生成的同义词）；
            失败或不可用时返回 None，由调用方回退到静态 synonym_map。
        """
        if not topic_words:
            return None

        # 缓存键：排序后的关键词拼接，保证同一组关键词不重复调用 LLM
        cache_key = "|".join(sorted(topic_words))
        if cache_key in self._synonym_cache:
            return set(topic_words) | set(self._synonym_cache[cache_key])

        # 若 litellm 不可用或未配置 API Key，直接返回 None 走静态降级
        if not _LITELLM_AVAILABLE or not self._zhipu_api_key:
            return None

        words_str = "、".join(sorted(topic_words))
        prompt = (
            "你是一位学术文献检索专家。给定以下研究主题关键词，"
            "请生成 5-10 个相关的同义词或近义词（中英文均可），"
            "用于扩展文献检索的召回率。\n"
            "要求：\n"
            "1. 每行输出一个词，不要编号、不要解释；\n"
            "2. 涵盖该主题在学术界常用的不同表达方式；\n"
            "3. 同时包含中文和英文术语（如适用）。\n\n"
            f"主题关键词：{words_str}\n"
            "同义词/近义词："
        )

        try:
            response = await litellm.acompletion(  # type: ignore[union-attr]
                model=self._zhipu_model,
                api_base=self._zhipu_api_base,
                api_key=self._zhipu_api_key,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=256,
                timeout=15,
            )
            content = response["choices"][0]["message"]["content"].strip()
            # 解析：按行分割，去掉编号前缀与多余空白
            synonyms: list[str] = []
            for line in content.splitlines():
                line = line.strip().strip('"\'` \n\r\t')
                # 去掉可能的编号前缀 "1. "、"1、"、"1) " 等
                line = re.sub(r'^\d+[\.\)、]\s*', '', line)
                if line and line not in synonyms:
                    synonyms.append(line)
            if not synonyms:
                return None
            self._synonym_cache[cache_key] = synonyms
            return set(topic_words) | set(synonyms)
        except Exception as e:
            logger.debug("LLM 同义词扩展失败，将回退到静态 synonym_map: %s", e)
            return None

    async def _expand_topic_synonyms(self, topic_words: set[str]) -> set[str]:
        """扩展主题关键词的同义词集（LLM 优先，静态 synonym_map 降级）.

        优先调用 LLM（智谱 GLM-4）动态生成同义词，使任意学科的主题都能扩展；
        LLM 不可用或调用失败时，回退到静态 synonym_map 术语映射表。

        Args:
            topic_words: 原始主题关键词集合。

        Returns:
            扩展后的关键词集合（包含原始词与同义词）。
        """
        # 优先：LLM 动态生成
        expanded = await self._expand_topic_synonyms_llm(topic_words)
        if expanded:
            return expanded

        # 降级：静态 synonym_map
        return self._expand_topic_synonyms_static(topic_words)

    async def _filter_by_relevance(
        self,
        papers: list[UnifiedPaper],
        topic: str,
        min_score: float = 0.25,
    ) -> list[UnifiedPaper]:
        """根据主题相关性过滤论文.

        提取主题关键词（并扩展同义词），与每篇论文的
        标题+摘要关键词比对，计算重叠率作为相关性分数，
        过滤低相关性论文并按相关性降序排序。

        在词重合度计算之前，先对论文的标题+摘要进行硬过滤：
        命中不相关主题黑名单（``_IRRELEVANT_TOPIC_BLOCKLIST``）的
        论文直接丢弃，不受"<5 篇放宽阈值"兜底保护。

        Args:
            papers: 待过滤的论文列表。
            topic: 检索主题。
            min_score: 最低相关性分数阈值，默认 0.20。

        Returns:
            过滤并按相关性降序排序后的论文列表。若过滤后结果少于 5 篇，
            放宽阈值至 0.10 重新过滤，但仍剔除黑名单命中项。
        """
        # 提取主题关键词（中文连续 2 字以上 / 英文连续 3 字以上）
        topic_words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', topic.lower()))
        if not topic_words:
            return papers

        # 扩展主题同义词以提升召回率（LLM 优先，静态 synonym_map 降级）
        topic_words = await self._expand_topic_synonyms(topic_words)

        # 动态核心主题词：从研究主题中提取，替代旧版硬编码
        # 使用跨语言关键词扩展（中文→英文翻译），适用于任何研究主题
        from scholarpilot.tools.citation_manager import _expand_topic_keywords
        _core_topic_words = _expand_topic_keywords(topic)
        if not _core_topic_words:
            # 回退：如果无法提取核心词，跳过标题硬过滤
            _core_topic_words = topic_words

        # 计算每篇论文的相关性分数（同时进行黑名单硬过滤）
        # 命中黑名单的论文直接丢弃，不受后续兜底保护
        blocklist = self._IRRELEVANT_TOPIC_BLOCKLIST
        scored: list[tuple[float, UnifiedPaper]] = []
        for paper in papers:
            text = f"{paper.title} {paper.abstract}".lower()
            # 硬过滤：命中不相关主题黑名单则直接跳过
            if any(block_word in text for block_word in blocklist):
                continue
            # 标题硬过滤：标题中必须至少包含一个核心主题词
            title_lower = paper.title.lower()
            if not any(core in title_lower for core in _core_topic_words):
                continue
            paper_words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', text))
            overlap = len(topic_words & paper_words)
            score = overlap / max(len(topic_words), 1)
            scored.append((score, paper))

        # 过滤低相关性论文
        filtered = [(s, p) for s, p in scored if s >= min_score]

        # 若过滤后结果过少，放宽阈值至 0.10 重新过滤
        # （仍剔除黑名单命中项，因为 scored 中已不含这些论文）
        if len(filtered) < 5:
            filtered = [(s, p) for s, p in scored if s >= 0.10]

        # 按相关性分数降序排序
        filtered.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in filtered]

    def format_papers_for_display(self, papers: list[UnifiedPaper], max_display: int = 30) -> str:
        """格式化论文列表用于显示."""
        lines = []

        # 按来源分组
        cnki_papers = [p for p in papers if p.source == "cnki"]
        ncpssd_papers = [p for p in papers if p.source == "ncpssd"]
        ss_papers = [p for p in papers if p.source == "semantic_scholar"]
        arxiv_papers = [p for p in papers if p.source == "arxiv"]
        wos_papers = [p for p in papers if p.source == "wos"]
        chinaxiv_papers = [p for p in papers if p.source == "chinaxiv"]
        pubscholar_papers = [p for p in papers if p.source == "pubscholar"]

        if cnki_papers:
            lines.append(f"\n### CNKI 中文文献 ({len(cnki_papers)} 篇)")
            for i, p in enumerate(cnki_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year})")

        if ncpssd_papers:
            lines.append(f"\n### NCPSSD 中文文献 ({len(ncpssd_papers)} 篇)")
            for i, p in enumerate(ncpssd_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year})")

        if ss_papers:
            lines.append(f"\n### Semantic Scholar 英文文献 ({len(ss_papers)} 篇)")
            for i, p in enumerate(ss_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                cited = f" [cited: {p.citation_count}]" if p.citation_count else ""
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year}){cited}")

        if arxiv_papers:
            lines.append(f"\n### arXiv 预印本 ({len(arxiv_papers)} 篇)")
            for i, p in enumerate(arxiv_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                arxiv_id = f" [{p.arxiv_id}]" if p.arxiv_id else ""
                lines.append(f"{i+1}. {p.title} - {authors} ({p.year}){arxiv_id}")

        if wos_papers:
            lines.append(f"\n### Web of Science ({len(wos_papers)} 篇)")
            for i, p in enumerate(wos_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                cited = f" [cited: {p.citation_count}]" if p.citation_count else ""
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year}){cited}")

        if chinaxiv_papers:
            lines.append(f"\n### ChinaXiv 预印本 ({len(chinaxiv_papers)} 篇)")
            for i, p in enumerate(chinaxiv_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year})")

        if pubscholar_papers:
            lines.append(f"\n### PubScholar OA ({len(pubscholar_papers)} 篇)")
            for i, p in enumerate(pubscholar_papers[:max_display]):
                authors = ", ".join(p.authors[:3])
                cited = f" [cited: {p.citation_count}]" if p.citation_count else ""
                lines.append(f"{i+1}. {p.title} - {authors} ({p.venue}, {p.year}){cited}")

        return "\n".join(lines) if lines else "暂无检索结果"
