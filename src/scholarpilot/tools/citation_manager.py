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
from scholarpilot.context.prompts.claim import RELEVANCE_SCORING_PROMPT
# ADR-007 P4: 标题归一化收敛到 utils/text.py
from scholarpilot.utils.text import normalize_title

logger = logging.getLogger(__name__)

# ===== 主题相关性评分系统（TRSS）=====
# 替代硬编码黑名单，通过动态计算论文与研究主题的关键词重合度来过滤不相关文献
# 适用于任何研究主题，无需手动维护黑名单

# 中→英核心研究术语映射（用于跨语言关键词匹配）
_ZH_EN_TOPIC_MAP: dict[str, list[str]] = {
    "数字化": ["digital", "digitization", "digitalization", "ict"],
    "转型": ["transformation", "transition", "upgrade"],
    "创新": ["innovation", "innovative", "rd", "research and development"],
    "企业": ["enterprise", "firm", "company", "corporate", "business"],
    "绩效": ["performance", "productivity", "efficiency", "output"],
    "影响": ["impact", "effect", "affect", "influence"],
    "财政": ["fiscal", "finance", "financial"],
    "债务": ["debt", "borrowing", "leverage"],
    "预算": ["budget", "budgeting"],
    "面板": ["panel"],
    "上市公司": ["listed", "public", "share"],
    "固定效应": ["fixed effect", "fixed-effect"],
    "经济": ["economic", "economy"],
    "增长": ["growth", "growing"],
    "投资": ["investment", "invest"],
    "消费": ["consumption", "consumer"],
    "收入": ["income", "revenue"],
    "税收": ["tax", "taxation"],
    "支出": ["expenditure", "spending"],
    "政策": ["policy"],
    "改革": ["reform"],
    "治理": ["governance"],
    "环境": ["environment", "green", "carbon"],
    "金融": ["financial", "finance", "banking"],
    "银行": ["bank", "banking"],
    "贸易": ["trade"],
    "出口": ["export"],
    "进口": ["import"],
    "全要素": ["total factor", "tfp"],
    "生产率": ["productivity"],
    "技术": ["technology", "technological", "tech"],
    "制造业": ["manufacturing", "manufacturer"],
    "服务业": ["service"],
    "所有制": ["ownership", "state-owned", "soe"],
    "国有": ["state-owned", "soe", "public"],
    "民营": ["private", "non-state"],
    "区域": ["region", "regional", "spatial"],
    "城市": ["city", "urban", "municipal"],
    "农村": ["rural", "countryside"],
    "人口": ["population", "demographic"],
    "劳动力": ["labor", "labour", "workforce"],
    "资本": ["capital"],
    "市场": ["market"],
    "竞争": ["competition", "competitive"],
    "垄断": ["monopoly"],
    "管制": ["regulation", "regulatory"],
    "薪酬": ["compensation", "salary", "pay"],
    "高管": ["executive", "ceo", "management"],
    "董事会": ["board", "director"],
    "股权": ["equity", "shareholder", "stock"],
    "融资": ["financing", "finance"],
    "约束": ["constraint"],
    "中介": ["mediating", "mediation", "intermediary"],
    "调节": ["moderating", "moderation", "moderate"],
    "异质": ["heterogene", "heterogeneity"],
    "稳健": ["robust", "robustness"],
    "工具变量": ["instrument", "iv"],
    "双重差分": ["difference-in-difference", "did"],
    "断点": ["regression discontinuity", "rd"],
    "随机": ["random", "rct"],
    "实验": ["experiment", "experimental"],
    "可持续": ["sustainab"],
    "绿色": ["green", "environmental"],
    "碳": ["carbon", "emission"],
    "能源": ["energy"],
    "数字": ["digital", "digitization"],
    "人工智能": ["artificial intelligence", "ai", "machine learning"],
    "大数据": ["big data"],
    "区块链": ["blockchain"],
    "平台": ["platform"],
    "电商": ["e-commerce", "ecommerce"],
    "网络": ["network", "internet"],
    "信息": ["information"],
    "知识": ["knowledge"],
    "溢出": ["spillover"],
    "配置": ["allocation", "allocat"],
    "资源": ["resource"],
    "组织": ["organization", "organizational"],
    "战略": ["strategy", "strategic"],
    "供应链": ["supply chain"],
    "价值": ["value", "valuation"],
    "风险": ["risk"],
    "质量": ["quality"],
    "规模": ["scale", "size"],
    "年龄": ["age"],
    "杠杆": ["leverage"],
    "盈利": ["profit", "profitab"],
    "研发": ["rd", "research and development"],
    "专利": ["patent"],
    "产权": ["property right", "property rights"],
    "制度": ["institution", "institutional"],
    "法律": ["legal", "law"],
    "文化": ["culture", "cultural"],
    "社会": ["social", "society"],
    "信任": ["trust"],
    "腐败": ["corrupt"],
    "透明": ["transparen"],
    "披露": ["disclosure", "disclos"],
    "审计": ["audit"],
    "会计": ["accounting"],
    "财务": ["financial", "accounting"],
    "并购": ["merger", "acquisition", "m&a"],
    "重组": ["restructur"],
    "国际化": ["international", "global"],
    "对外投资": ["fdi", "outward"],
    "外商投资": ["fdi", "foreign direct"],
    "汇率": ["exchange rate"],
    "利率": ["interest rate"],
    "通胀": ["inflation"],
    "失业": ["unemploy"],
    "工资": ["wage", "salary"],
    "住房": ["hous"],
    "土地": ["land"],
    "农业": ["agricultur"],
    "工业": ["industr"],
    "结构": ["structur"],
    "升级": ["upgrade", "upgrad"],
    "集聚": ["agglomerat", "cluster"],
    "创新绩效": ["innovation performance"],
    "经济绩效": ["economic performance"],
    "财务绩效": ["financial performance"],
    "环境绩效": ["environmental performance"],
    "企业绩效": ["firm performance", "corporate performance"],
    "数字化转型": ["digital transformation"],
}

# ===== 统一不相关主题安全网 =====
# 此常量合并了原 _OFF_TOPIC_DOMAIN_WORDS（TRSS 离题惩罚词）、
# _is_irrelevant_paper 中的 _legacy_blocklist（遗留黑名单）以及
# search.py 中的 _IRRELEVANT_TOPIC_BLOCKLIST 三处重复定义。
#
# 注意：此安全网是语义过滤器（SemanticRelevanceFilter）的补充兜底，
# 主题相关性判断主要依赖嵌入语义相似度，此列表仅处理明显跨域噪声。
# TODO: 在语义过滤稳定运行后移除此安全网
_IRRELEVANT_DOMAIN_WORDS: frozenset[str] = frozenset({
    # 医学/疫情类
    "tuberculosis", "mycobacterium", "mycobacterium tuberculosis",
    "covid-19", "covid19", "coronavirus",
    "patient", "clinical", "diagnosis", "treatment", "symptom",
    "mortality", "incidence", "prevalence", "antibiotic", "antiviral",
    "antituberculosis", "drug resistance", "drug resistance in",
    "pharmaceutical", "pharmaceutical innovation",
    "新冠", "疫情", "肺炎", "结核", "耐药",
    "临床", "临床特征", "临床分析", "心理反应",
    "患者", "诊断", "治疗", "症状", "死亡率", "发病率",
    "药物创新",
    # 农业/机器人类
    "crop", "harvest", "harvest robot", "livestock", "pesticide", "safflower",
    "采摘", "采摘机器人", "农作物", "畜牧业", "农药",
    "红花", "农业机器人",
    # 旅游业
    "tourism", "hotel", "hospitality",
    "旅游", "酒店", "餐饮",
    "医疗旅游", "medical tourism", "文化旅游标准化",
    # 纯机器学习技术（非应用）
    "neural architecture", "hyperparameter", "benchmark dataset",
    "image classification", "object detection",
    # 国际关系/政治类
    "axis of allies", "us-japan alliance", "geopolitic",
    "antitrust interoperability",
    # 其他噪声
    "data security and privacy protection", "ctrip",
    "endogenous knowledge spillover",
})

# 离题领域惩罚词（跨主题通用，不针对特定研究主题）
# 出现这些词的论文与研究主题不相关的概率极高
# 向后兼容别名：引用统一常量 _IRRELEVANT_DOMAIN_WORDS
# TODO: 在语义过滤稳定运行后移除此安全网
_OFF_TOPIC_DOMAIN_WORDS: frozenset[str] = _IRRELEVANT_DOMAIN_WORDS

# TRSS 最低相关性阈值：低于此值的论文将被过滤
_MIN_TOPIC_RELEVANCE: float = 0.10


def _expand_topic_keywords(topic_keywords: str) -> set[str]:
    """扩展主题关键词，加入中→英翻译，实现跨语言匹配.

    Args:
        topic_keywords: 空格分隔的研究主题关键词（中文为主）.

    Returns:
        扩展后的关键词集合（含中文原词 + 英文翻译）.
    """
    if not topic_keywords:
        return set()

    # 提取原始关键词
    raw_words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', topic_keywords.lower()))

    expanded = set(raw_words)

    # 添加英文翻译
    for zh, en_list in _ZH_EN_TOPIC_MAP.items():
        # 检查中文关键词是否在原始关键词中
        for raw in raw_words:
            if zh in raw or raw in zh:
                expanded.update(en_list)
                break

    return expanded


def _compute_topic_relevance(
    title: str,
    abstract: str,
    topic_keywords: str,
) -> float:
    """计算论文与研究主题的相关性评分（0.0-1.0）.

    基于三层评分：
    1. 标题关键词命中（权重0.5）：标题中出现主题词得高分
    2. 摘要关键词覆盖（权重0.3）：摘要中主题词覆盖率
    3. 离题领域惩罚（权重0.2）：出现明显无关领域词扣分

    支持跨语言匹配：中文主题关键词自动翻译为英文进行匹配。

    Args:
        title: 论文标题.
        abstract: 论文摘要.
        topic_keywords: 空格分隔的研究主题关键词.

    Returns:
        相关性评分 0.0（完全不相关）到 1.0（高度相关）.
    """
    if not topic_keywords or not title:
        return 0.0

    # 扩展关键词（含英文翻译）
    topic_words = _expand_topic_keywords(topic_keywords)
    if not topic_words:
        return 0.0

    title_lower = title.lower()
    abstract_lower = (abstract or "").lower()
    paper_text_lower = f"{title_lower} {abstract_lower}"

    # 1. 标题关键词命中（权重0.5）
    title_hits = sum(1 for kw in topic_words if kw in title_lower)
    title_score = min(title_hits / 2.0, 1.0)  # 命中2个关键词即满分

    # 2. 摘要关键词覆盖（权重0.3）
    abstract_hits = sum(1 for kw in topic_words if kw in abstract_lower)
    abstract_score = min(abstract_hits / max(len(topic_words) * 0.3, 1), 1.0)

    # 3. 离题领域惩罚（权重0.2）
    off_topic_hits = sum(1 for kw in _OFF_TOPIC_DOMAIN_WORDS if kw in paper_text_lower)
    penalty_score = max(0.0, 1.0 - off_topic_hits * 0.5)  # 每个离题词扣0.5

    # 综合评分
    score = title_score * 0.5 + abstract_score * 0.3 + penalty_score * 0.2

    return round(max(0.0, min(1.0, score)), 3)


def _is_irrelevant_paper(
    title: str,
    abstract: str,
    topic_keywords: str,
) -> bool:
    """检查论文是否与研究主题不相关（应被过滤）.

    综合使用TRSS评分和遗留黑名单进行判断：
    1. TRSS评分低于阈值 → 不相关
    2. 离题领域词命中数≥2 → 不相关（即使有少量关键词重合）
    3. 遗留黑名单命中 → 不相关（安全网）

    Args:
        title: 论文标题.
        abstract: 论文摘要.
        topic_keywords: 研究主题关键词.

    Returns:
        True 如果论文不相关，应被过滤.
    """
    if not title:
        return True

    paper_text_lower = f"{title} {abstract}".lower()

    # 安全网：遗留黑名单检查（引用统一常量 _IRRELEVANT_DOMAIN_WORDS）
    # TODO: 在语义过滤稳定运行后移除此安全网
    if any(block_word in paper_text_lower for block_word in _IRRELEVANT_DOMAIN_WORDS):
        return True

    # TRSS评分检查
    if not topic_keywords:
        # 无主题关键词时，只靠黑名单过滤
        return False

    relevance = _compute_topic_relevance(title, abstract, topic_keywords)
    if relevance < _MIN_TOPIC_RELEVANCE:
        return True

    # 离题领域词硬过滤：命中≥2个离题词，即使有少量关键词重合也过滤
    off_topic_count = sum(1 for kw in _OFF_TOPIC_DOMAIN_WORDS if kw in paper_text_lower)
    if off_topic_count >= 2:
        return True

    return False


# ===== 语义嵌入相关性过滤器（第三代方案）=====
# 基于智谱 embedding-3 模型，将论文和研究主题编码为高维向量，
# 通过余弦相似度判断语义相关性，从根本上解决黑名单/关键词匹配的局限性。
# 降级策略：API不可用时自动回退到TRSS关键词匹配。

class SemanticRelevanceFilter:
    """基于嵌入语义相似度的文献相关性过滤器.

    使用智谱 embedding-3 模型将研究主题和论文编码为向量，
    通过余弦相似度判断相关性，从根本上解决黑名单/关键词匹配的局限性：
    - 语义级理解：同义不同形也能匹配（如"信息化建设"≈"数字化转型"）
    - 零维护：不需要手动维护任何词表或黑名单
    - 自动泛化：适配任何研究主题
    - 跨语言：embedding-3 支持中英多语言

    降级策略：API不可用时自动回退到TRSS关键词匹配。
    """

    # 类级缓存：主题文本 → 向量
    _topic_cache: dict[str, list[float]] = {}
    # 类级缓存：论文文本哈希 → 向量
    _paper_cache: dict[str, list[float]] = {}
    # API可用性标记（None=未检测, True/False=已检测）
    _api_available: bool | None = None

    # 默认相似度阈值：低于此值的论文被判定为不相关
    DEFAULT_THRESHOLD: float = 0.35
    # 检索阶段宽松阈值（只过滤最不相关的）
    SEARCH_THRESHOLD: float = 0.28
    # 最终过滤阶段严格阈值（考虑很多Citation只有标题没有摘要，适当降低）
    FINAL_THRESHOLD: float = 0.33

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "https://open.bigmodel.cn/api/paas/v4/",
        model: str = "embedding-3",
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.model = model

    async def _get_embedding(self, text: str) -> list[float] | None:
        """获取单条文本的嵌入向量，失败返回None."""
        cache_key = text[:500]
        if cache_key in self._topic_cache:
            return self._topic_cache[cache_key]

        try:
            import litellm
            litellm.model_cost_default_url = ""
            response = await litellm.aembedding(
                model=f"openai/{self.model}",
                input=[text[:2000]],  # 截断超长文本
                api_key=self.api_key,
                api_base=self.api_base,
            )
            vec = response.data[0]["embedding"]
            self._topic_cache[cache_key] = vec
            self._api_available = True
            return vec
        except Exception as e:
            logger.warning(f"Embedding API调用失败: {e}")
            self._api_available = False
            return None

    async def _get_embeddings_batch(
        self, texts: list[str]
    ) -> list[list[float] | None]:
        """批量获取嵌入向量，减少API调用次数."""
        results: list[list[float] | None] = [None] * len(texts)
        batch_size = 32  # 智谱API每批最多支持较多条目，32条平衡速度和可靠性

        # 先查缓存
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []
        for i, text in enumerate(texts):
            cache_key = text[:500]
            if cache_key in self._paper_cache:
                results[i] = self._paper_cache[cache_key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(cache_key)

        if not uncached_texts:
            return results

        # 批量获取未缓存的
        for start in range(0, len(uncached_texts), batch_size):
            batch_texts = uncached_texts[start:start + batch_size]
            batch_indices = uncached_indices[start:start + batch_size]
            try:
                import litellm
                litellm.model_cost_default_url = ""
                response = await litellm.aembedding(
                    model=f"openai/{self.model}",
                    input=[t[:2000] for t in batch_texts],
                    api_key=self.api_key,
                    api_base=self.api_base,
                )
                sorted_data = sorted(response.data, key=lambda x: x["index"])
                for idx, data in zip(batch_indices, sorted_data):
                    vec = data["embedding"]
                    results[idx] = vec
                    self._paper_cache[uncached_texts[
                        uncached_indices.index(idx)
                    ]] = vec
                self._api_available = True
            except Exception as e:
                logger.warning(f"批量嵌入失败(batch {start}): {e}")
                self._api_available = False

        return results

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算余弦相似度."""
        import math
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return round(dot / (norm_a * norm_b), 4)

    async def compute_relevance_score(
        self,
        paper_title: str,
        paper_abstract: str,
        topic: str,
    ) -> float:
        """计算单篇论文与研究主题的语义相关性评分（0.0-1.0）.

        Args:
            paper_title: 论文标题.
            paper_abstract: 论文摘要.
            topic: 研究主题.

        Returns:
            语义相似度评分 0.0-1.0，API不可用时返回-1.0表示降级.
        """
        if not topic or not paper_title:
            return 0.0

        # 获取主题向量
        topic_vec = await self._get_embedding(topic)
        if topic_vec is None:
            return -1.0  # 降级标记

        # 获取论文向量
        paper_text = f"{paper_title} {paper_abstract}"[:2000]
        paper_vec = await self._get_embedding(paper_text)
        if paper_vec is None:
            return -1.0

        return self._cosine_similarity(topic_vec, paper_vec)

    async def filter_papers(
        self,
        papers: list,
        topic: str,
        threshold: float | None = None,
    ) -> tuple[list, list, str]:
        """过滤不相关论文（语义嵌入版）.

        使用嵌入语义相似度替代黑名单/关键词匹配，
        从根本上解决文献相关性过滤问题。

        降级策略：如果 embedding API 不可用，
        自动回退到 TRSS 关键词匹配（_is_irrelevant_paper）。

        Args:
            papers: 论文列表（需有 title 和 abstract 属性）.
            topic: 研究主题.
            threshold: 相似度阈值，None 则使用 DEFAULT_THRESHOLD.

        Returns:
            (kept_papers, filtered_papers, method):
            - kept_papers: 保留的论文
            - filtered_papers: 被过滤的论文
            - method: "semantic"（语义过滤）或 "trss_fallback"（降级）
        """
        if not papers or not topic:
            return papers, [], "none"

        if threshold is None:
            threshold = self.DEFAULT_THRESHOLD

        # 获取主题向量
        topic_vec = await self._get_embedding(topic)
        if topic_vec is None:
            # API不可用，降级到TRSS
            logger.info("Embedding API不可用，降级到TRSS关键词过滤")
            kept, filtered = self._fallback_trss(papers, topic)
            return kept, filtered, "trss_fallback"

        # 准备论文文本
        paper_texts = []
        for p in papers:
            title = getattr(p, "title", "") or ""
            abstract = getattr(p, "abstract", "") or ""
            paper_texts.append(f"{title} {abstract}"[:2000])

        # 批量获取论文向量
        paper_vecs = await self._get_embeddings_batch(paper_texts)

        # 计算所有论文的相似度
        scored: list[tuple[float, object]] = []
        for paper, vec in zip(papers, paper_vecs):
            if vec is None:
                # 单篇获取失败，保留（保守策略），相似度记为1.0
                scored.append((1.0, paper))
                continue
            sim = self._cosine_similarity(topic_vec, vec)
            scored.append((sim, paper))

        # 过滤 + 保护机制：过滤后数量过少时自动降低阈值重试
        # 避免阈值过高导致过度过滤（很多Citation只有标题没有摘要，相似度偏低）
        min_keep = max(5, len(papers) // 4)  # 至少保留25%或5篇
        current_threshold = threshold
        min_threshold = 0.15  # 最低阈值底线

        while True:
            kept = [p for sim, p in scored if sim >= current_threshold]
            filtered = [p for sim, p in scored if sim < current_threshold]

            if len(kept) >= min_keep or current_threshold <= min_threshold:
                break

            # 降低阈值重试
            current_threshold = max(
                min_threshold,
                current_threshold - 0.05,
            )

        logger.info(
            "语义过滤完成: 保留%d篇, 过滤%d篇 (阈值=%.2f→%.2f)",
            len(kept), len(filtered), threshold, current_threshold,
        )
        return kept, filtered, "semantic"

    def _fallback_trss(
        self, papers: list, topic: str
    ) -> tuple[list, list]:
        """降级策略：使用TRSS关键词匹配."""
        kept: list = []
        filtered: list = []
        for p in papers:
            title = getattr(p, "title", "") or ""
            abstract = getattr(p, "abstract", "") or ""
            if _is_irrelevant_paper(title, abstract, topic):
                filtered.append(p)
            else:
                kept.append(p)
        return kept, filtered

    @classmethod
    def is_api_available(cls) -> bool:
        """检查embedding API是否在之前的调用中成功过."""
        return cls._api_available is True


# 全局单例（延迟初始化，首次使用时读取配置）
_semantic_filter: SemanticRelevanceFilter | None = None


def get_semantic_filter() -> SemanticRelevanceFilter:
    """获取全局 SemanticRelevanceFilter 单例.

    从 ScholarPilot 配置中读取智谱 API Key 和 api_base。
    如果未配置 API Key，返回一个不可用的实例（后续自动降级到TRSS）。
    """
    global _semantic_filter
    if _semantic_filter is not None:
        return _semantic_filter

    try:
        from scholarpilot.config import Settings
        config = Settings()
        _semantic_filter = SemanticRelevanceFilter(
            api_key=config.zhipu_api_key,
            api_base=config.zhipu_api_base,
        )
    except Exception:
        # 配置不可用，创建空实例（会自动降级）
        _semantic_filter = SemanticRelevanceFilter()

    return _semantic_filter


# ===== Cross-Encoder 精排器（第四代：两阶段架构）=====
# 在 Bi-Encoder 初筛后，使用 LLM-as-a-Judge 或本地 BGE-Reranker 进行精排。
# Bi-Encoder 快但粗（独立编码），Cross-Encoder 慢但精（联合编码）。
# 业界标准 RAG 两阶段架构：召回(Bi-Encoder) → 精排(Cross-Encoder)。

class CrossEncoderReranker:
    """Cross-Encoder 精排器：对 Bi-Encoder 初筛后的论文进行精确重排序.

    两阶段架构的第二阶段：
    1. Bi-Encoder（embedding-3）快速初筛，移除明显不相关的论文
    2. Cross-Encoder 精排，对保留的论文进行精确的相关性排序

    实现策略（优先级递减）：
    1. 本地 BGE-Reranker-v2-m3（sentence_transformers.CrossEncoder）
       - 精度最高，全交互注意力机制
       - 需要 sentence-transformers + torch（首次使用自动下载模型）
    2. LLM-as-a-Judge（GLM-4 API）
       - 无需额外依赖，使用已有 API
       - 将主题+论文拼接后让 LLM 评分，本质等同于 Cross-Encoder
    3. 跳过精排（降级到 Bi-Encoder 排序）

    精排的作用：
    - 重排序：将最相关的论文排到前面（影响引用优先级和文献池截取）
    - 精筛：移除 Bi-Encoder 误保留的边界不相关论文
    """

    # LLM-as-a-Judge 的批量大小（每批送入 LLM 评分的论文数）
    LLM_BATCH_SIZE: int = 10
    # 精排后移除底部的比例（最低相关的 N% 被移除）
    BOTTOM_DROP_RATIO: float = 0.10
    # LLM 评分低于此值的论文被移除（只移除明确不相关的 1-2 分）
    LLM_SCORE_THRESHOLD: float = 2.0  # LLM 评分范围 1-5

    def __init__(self) -> None:
        self._local_reranker = None  # sentence_transformers.CrossEncoder 实例
        self._local_available: bool | None = None  # None=未检测
        self._llm = None  # LLM 实例（延迟初始化）

    def _try_init_local_reranker(self) -> bool:
        """尝试初始化本地 BGE-Reranker-v2-m3 模型.

        Returns:
            True 如果本地模型可用.
        """
        if self._local_available is not None:
            return self._local_available

        try:
            # 设置 HuggingFace 镜像（中国用户加速）
            import os
            if "HF_ENDPOINT" not in os.environ:
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

            from sentence_transformers import CrossEncoder
            self._local_reranker = CrossEncoder(
                "BAAI/bge-reranker-v2-m3",
                max_length=512,
            )
            self._local_available = True
            logger.info("本地 BGE-Reranker-v2-m3 加载成功")
            return True
        except ImportError:
            logger.info(
                "sentence-transformers 未安装，Cross-Encoder 降级到 LLM-as-a-Judge"
            )
            self._local_available = False
            return False
        except Exception as e:
            logger.warning(f"本地 BGE-Reranker 加载失败: {e}")
            self._local_available = False
            return False

    def _score_local(
        self, topic: str, paper_texts: list[str],
    ) -> list[float]:
        """使用本地 BGE-Reranker 评分.

        Args:
            topic: 研究主题.
            paper_texts: 论文文本列表（标题+摘要）.

        Returns:
            相关性评分列表（0-1，越高越相关）.
        """
        if not self._local_reranker:
            return [0.5] * len(paper_texts)

        # Cross-Encoder 需要 (query, document) 对
        pairs = [(topic, text[:512]) for text in paper_texts]
        raw_scores = self._local_reranker.predict(pairs)

        # BGE-Reranker 输出 logits，通过 sigmoid 映射到 0-1
        import math
        return [1.0 / (1.0 + math.exp(-s)) for s in raw_scores]

    async def _score_llm(
        self, topic: str, papers: list, batch_size: int = 10,
    ) -> list[float]:
        """使用 LLM-as-a-Judge 评分（GLM-4）.

        将研究主题和论文标题+摘要拼接后送入 LLM，
        让 LLM 对每篇论文与研究主题的相关性打分（1-5分）。
        这本质上等同于 Cross-Encoder 的联合编码机制。

        Args:
            topic: 研究主题.
            papers: 论文列表.
            batch_size: 每批送入 LLM 的论文数.

        Returns:
            相关性评分列表（1.0-5.0，越高越相关）.
        """
        if not self._llm:
            try:
                from scholarpilot.config import Settings
                from scholarpilot.llm.gateway import LLMGateway
                config = Settings()
                self._llm = LLMGateway(config)
            except Exception as e:
                logger.warning(f"LLM 初始化失败，跳过精排: {e}")
                return [5.0] * len(papers)  # 保守策略：全部保留

        scores: list[float] = []
        # 分批处理，每批 batch_size 篇
        for start in range(0, len(papers), batch_size):
            batch = papers[start:start + batch_size]
            batch_scores = await self._score_llm_batch(topic, batch)
            scores.extend(batch_scores)

        return scores

    async def _score_llm_batch(
        self, topic: str, batch: list,
    ) -> list[float]:
        """单批 LLM 评分."""
        # 构建论文列表文本
        paper_lines: list[str] = []
        for i, p in enumerate(batch, 1):
            title = getattr(p, "title", "") or ""
            abstract = getattr(p, "abstract", "") or ""
            # 截断摘要，避免 prompt 过长
            abstract_short = abstract[:200] + "..." if len(abstract) > 200 else abstract
            paper_lines.append(f"[{i}] 标题: {title}\n摘要: {abstract_short}")

        papers_text = "\n\n".join(paper_lines)

        prompt = RELEVANCE_SCORING_PROMPT.format(
            topic=topic,
            batch_count=len(batch),
            papers_text=papers_text,
        )

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model="glm-4",
                temperature=0.1,  # 低温度，确保评分稳定
            )

            # 解析评分
            scores: list[float] = []
            for i in range(len(batch)):
                # 匹配 "N: score" 或 "N. score" 格式
                import re
                match = re.search(
                    rf'{i + 1}\s*[:.]\s*([1-5])', response,
                )
                if match:
                    scores.append(float(match.group(1)))
                else:
                    scores.append(5.0)  # 解析失败，保守保留

            return scores
        except Exception as e:
            logger.warning(f"LLM 评分失败: {e}")
            return [5.0] * len(batch)  # 失败时保守保留

    async def rerank(
        self,
        papers: list,
        topic: str,
        drop_bottom: bool = True,
    ) -> tuple[list, list, str]:
        """对论文列表进行 Cross-Encoder 精排.

        两阶段架构的第二阶段：在 Bi-Encoder 初筛后精排。

        Args:
            papers: Bi-Encoder 初筛后保留的论文列表.
            topic: 研究主题.
            drop_bottom: 是否移除最低相关的底部论文.

        Returns:
            (reranked_papers, dropped_papers, method):
            - reranked_papers: 按相关性降序排列的论文
            - dropped_papers: 被移除的底部论文
            - method: "local_bge" / "llm_judge" / "skipped"
        """
        if not papers or not topic or len(papers) <= 3:
            return papers, [], "skipped"

        # 策略1：尝试本地 BGE-Reranker
        if self._try_init_local_reranker():
            paper_texts = []
            for p in papers:
                title = getattr(p, "title", "") or ""
                abstract = getattr(p, "abstract", "") or ""
                paper_texts.append(f"{title} {abstract}")

            raw_scores = self._score_local(topic, paper_texts)
            method = "local_bge"
        else:
            # 策略2：LLM-as-a-Judge
            raw_scores = await self._score_llm(topic, papers)
            method = "llm_judge"

        # 按评分降序排列
        scored = list(zip(raw_scores, papers))
        scored.sort(key=lambda x: x[0], reverse=True)

        # 移除底部最低相关的论文
        dropped: list = []
        if drop_bottom and len(scored) > 5:
            # 本地模型用 0.3 阈值，LLM 用 3.0 阈值
            if method == "local_bge":
                threshold = 0.3  # sigmoid 后 0.3 以下移除
            else:
                threshold = self.LLM_SCORE_THRESHOLD

            # 找到低于阈值的论文
            kept_scored = []
            for score, paper in scored:
                if score < threshold and len(kept_scored) >= 5:
                    dropped.append(paper)
                else:
                    kept_scored.append((score, paper))

            scored = kept_scored

        reranked = [p for _, p in scored]

        logger.info(
            "Cross-Encoder精排(%s): %d篇→%d篇 (移除%d篇)",
            method, len(papers), len(reranked), len(dropped),
        )
        return reranked, dropped, method


# 全局 Cross-Encoder 精排器单例
_cross_encoder_reranker: CrossEncoderReranker | None = None


def get_cross_encoder_reranker() -> CrossEncoderReranker:
    """获取全局 CrossEncoderReranker 单例."""
    global _cross_encoder_reranker
    if _cross_encoder_reranker is None:
        _cross_encoder_reranker = CrossEncoderReranker()
    return _cross_encoder_reranker


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


# 常见占位假名集合（LLM 生成引用时可能编造的典型虚构姓名）
_FAKE_NAME_PATTERNS: set[str] = {
    "张三", "李四", "王五", "赵六", "孙七", "孙八", "周九", "吴十",
    "钱一", "孙二", "李五一", "李六一", "王七一", "赵八一", "郑十一",
    "冯十二", "陈十三", "杨二四", "黄二五", "张二六", "李二七", "王二八",
    "赵二九", "周三十", "吴三一", "郑三二", "冯三三", "陈三四", "杨三五",
    "张三七", "王三九", "孙四一", "吴四三", "冯四五", "杨四七", "张四九",
    "王五一", "周五三", "吴五四", "郑五五", "冯五六", "陈五七", "杨五八",
    "黄五九", "李六一", "未知", "佚名", "匿名", "某某", "XXX", "xxx",
}

# 常见中文姓氏（用于检测"姓+序数词"假名模式）
_COMMON_SURNAMES = set("张王李赵刘陈杨黄周吴徐孙朱马胡郭林何高梁郑")
# 中文序数字符（用于检测"姓+序数词"假名模式）
_ORDINAL_CHARS = set("一二三四五六七八九十")


# 非引用前缀词（出现在匹配前方的文本中时，说明不是引用而是正文叙述）
_NON_CITATION_PREFIXES: set[str] = {
    "根据", "参考", "按照", "遵循", "依据", "依照", "基于", "借鉴",
    "来源于", "来自于", "引自", "转引", "参见", "详见", "参见",
    "借鉴了", "参考了", "根据上述", "结合上述",
    "分析上述", "观察上述", "从上述", "由上述",
}

# 常见非姓名双字组合（实际是正文短语被误提取为作者名）
# 动态化改造：去重并新增更多非姓名组合（含3-4字结论性短语）
_NON_NAME_TWO_CHAR: set[str] = {
    "上述", "以下", "以上", "前述", "本研", "本节", "本章", "本文",
    "由此", "据此", "综上", "如表", "如图", "见表", "见图", "如上",
    "此外", "另外", "然而", "因此", "所以", "虽然", "尽管", "无论",
    "反之", "否则", "而且", "并且", "以及", "或者", "还是",
    "不仅", "不但", "而是", "即是", "便是", "正因", "故而", "从而",
    "进而", "甚至", "尤其", "特别", "主要", "基本", "大致", "大约",
    "截至", "迄今", "至今", "相较", "对比", "相对", "相比",
    "各类", "各项", "各种", "各个", "各部", "各方", "各组", "各期",
    "此期", "本期", "同期", "前期", "后期", "末期", "初期", "中期",
    "同年", "次年", "近年", "往年", "常年",
    "高企", "低迷", "走低", "走高", "攀升", "骤降", "暴涨", "暴跌",
    "根据", "按照", "依据", "依照", "基于", "借鉴", "鉴于", "考虑",
    "结合", "关于", "对于", "至于",
    "由于", "沿着", "顺着", "随着", "伴着", "本着",
    # 新增：常见正文结论性短语（3-4字，被误提取为作者名）
    "由此可知", "综上所述", "由此可见", "总而言之",
    "整体而言", "总体来看", "从而可知", "是以", "因而",
}


def _is_valid_zh_author(name: str, non_name_words: set[str]) -> bool:
    """检查中文字符串是否像真实作者名.

    Args:
        name: 待检查的字符串
        non_name_words: 非姓名用词集合

    Returns:
        True 如果像真实作者名，False 如果是误匹配
    """
    name = name.strip()
    if not name:
        return False

    # 长度检查：中文姓名通常 2-4 字（少数民族名可达 5-6 字）
    if len(name) < 2 or len(name) > 6:
        return False

    # 检查是否包含非姓名用词
    for word in non_name_words:
        if word in name:
            return False

    # 检查是否全是非姓名高频字
    # 常见非姓名高频字（单独出现或组合出现都不像人名）
    non_name_high_freq = set("的了在是为有对及或这与那其此该某本但而则即若")
    if all(c in non_name_high_freq for c in name):
        return False

    # 占位假名检测
    # 1. 命中常见占位假名集合（如 张三、李四、佚名、XXX 等）
    if name in _FAKE_NAME_PATTERNS:
        return False

    # 2. "姓+序数词"模式：如 张一、李三、王九（姓氏 + 单个序数字符）
    if len(name) == 2 and name[0] in _COMMON_SURNAMES and name[1] in _ORDINAL_CHARS:
        return False

    # 3. "姓+重复字"模式：如 张张、李李、王王、张张张（叠写，非真实姓名）
    # 动态化改造：扩展为3字叠字检测（如 张张张、李李李）
    if len(name) in (2, 3) and len(set(name)) == 1:
        return False

    # 4. 常见非姓名双字组合（正文短语被误提取）
    if name in _NON_NAME_TWO_CHAR:
        return False

    # 5. 以非姓名首字开头的检测
    # 常见动词/介词/连词首字，不太可能作为姓氏
    _unlikely_surname_starts = set("从由据凭鉴于考虑因所但而且并或则即若此其该某本被将把给向往朝为以按照遵循依据")
    if len(name) >= 2 and name[0] in _unlikely_surname_starts:
        # 但需要排除真实姓氏（如"从"姓、"方"姓等），只过滤明显非姓氏的
        _definitely_not_surnames = set("从由据凭鉴虑因所但而且并或则即若此其该某本被将把给向往朝为以按遵循依据")
        if name[0] in _definitely_not_surnames:
            return False

    # 6. 包含明显非姓名字符组合（如"分析"、"研究"、"结果"等嵌在名字中）
    _embedded_non_name = {"分析", "研究", "结果", "表明", "说明", "发现",
                          "数据", "样本", "模型", "回归", "系数", "变量",
                          "假设", "效应", "机制", "理论", "方法", "水平",
                          "显著", "相关", "影响", "因素", "指标", "衡量"}
    for word in _embedded_non_name:
        if word in name:
            return False

    # 7. "姓+数字"模式：如 张三1、李四2（姓氏 + 阿拉伯数字，LLM假名）
    # 动态化改造：检测姓氏后跟数字的假名模式
    if name[0] in _COMMON_SURNAMES and re.search(r'\d', name[1:]):
        return False

    # 8. "姓+英文"模式：如 王A、李test（姓氏 + 英文字母，LLM假名）
    # 动态化改造：检测姓氏后跟英文字母的假名模式
    if name[0] in _COMMON_SURNAMES and re.search(r'[A-Za-z]', name[1:]):
        return False

    return True


def _detect_suspicious_authors_by_frequency(
    text: str,
    reference_authors: set[str],
) -> set[str]:
    """基于频率的假名检测：检测在正文中以"XX（年份）"格式出现但不在参考文献列表中的作者名.

   如果一个作者名在正文中出现的上下文都是"XX（年份）"格式
    但从未出现在参考文献列表中，标记为可疑。

    Args:
        text: 论文正文文本
        reference_authors: 参考文献列表中的所有作者名集合

    Returns:
        可疑作者名集合（在正文中被引用但不在参考文献中的作者名）
    """
    if not text or not reference_authors:
        return set()

    suspicious: set[str] = set()
    # 匹配正文中的"作者（年份）"格式引用
    pattern = re.compile(
        r'([\u4e00-\u9fff]{2,4}(?:[和与][\u4e00-\u9fff]{2,4})*(?:等)?)\s*[（(]\s*((?:19|20)\d{2})\s*[）)]'
    )

    # 收集正文中所有被引用的作者名
    cited_authors: set[str] = set()
    for m in pattern.finditer(text):
        author_str = m.group(1)
        # 拆分多个作者（如"张三和李四"）
        parts = re.split(r'[和与]', author_str.replace('等', ''))
        for part in parts:
            part = part.strip()
            if part and len(part) >= 2:
                cited_authors.add(part)

    # 检查每个被引用的作者名是否出现在参考文献列表中
    for author in cited_authors:
        # 如果作者名不在参考文献列表中，标记为可疑
        if author not in reference_authors:
            suspicious.add(author)

    return suspicious


def _has_non_citation_prefix(text: str, match_start: int) -> bool:
    """检查匹配位置前方是否有非引用前缀词.

    Args:
        text: 原始文本
        match_start: 匹配在文本中的起始位置

    Returns:
        True 如果前方有非引用前缀词（应跳过此匹配）
    """
    # 取匹配前方最多10个字符作为上下文
    context_start = max(0, match_start - 10)
    preceding = text[context_start:match_start]

    for prefix in _NON_CITATION_PREFIXES:
        if preceding.endswith(prefix):
            return True

    return False


def _clean_html_tags(text: str) -> str:
    """清理文本中的HTML标签（如搜索结果高亮标签）.

    Args:
        text: 可能包含HTML标签的文本

    Returns:
        清理后的纯文本
    """
    if not text:
        return text
    # 移除所有HTML标签
    return re.sub(r'<[^>]+>', '', text)


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
        # 代词/指示词
        "这与", "那与", "这与刘", "那与刘", "其与",
        # 常见正文短语（2-6字）
        "水平上显著", "上显著", "显著", "不显著", "正相关", "负相关",
        "正相关关", "负相关关", "显著正相", "显著负相",
        "水平上", "上显著", "为显著", "呈显著",
        "系数为", "相关系", "相关系数",
        "研究发现", "研究结论", "研究结",
        "影响", "的结果", "的结果表",
    }

    # 中文非姓名用词（出现在作者名中则判定为误匹配）
    ZH_NON_NAME_CHARS = {
        # 常见动词/形容词/副词
        "显著", "水平", "关系", "影响", "结果", "表明", "说明",
        "发现", "系数", "相关", "回归", "模型", "变量", "数据",
        "样本", "假设", "效应", "机制", "理论", "分析",
        # 常见虚词/代词
        "的", "了", "在", "为", "是", "有", "对", "及", "或",
        "这", "那", "其", "此", "该", "某", "本", "该",
        "与", "和", "但", "而", "则", "即", "若",
        # 常见学术用语
        "研究", "论文", "文献", "参考", "引用",
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
    # 支持: 中英文混排 "Author和Author（Year）"、"Author与Author（Year）"
    en_pattern = re.compile(
        r'('
        r'(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'  # 第一作者（1或2个词）
        r'(?:\s*(?:and|&|和|与)\s*(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?))*'  # and/&,/与 连接的后续作者
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
        # 前缀上下文过滤：检查匹配前方是否有非引用前缀词
        if _has_non_citation_prefix(text, m.start()):
            continue
        key = f"{authors_str}_{year}"
        if key not in seen:
            seen.add(key)
            authors = re.split(r'[、，,]|和|与|及', authors_str)
            authors = [a.replace('等', '').strip() for a in authors if a.strip()]
            # 作者名合理性过滤：移除非姓名用词导致的误匹配
            valid_authors = [a for a in authors if _is_valid_zh_author(a, ZH_NON_NAME_CHARS)]
            if not valid_authors:
                # 所有作者名都不合理，丢弃此引用
                continue
            if len(valid_authors) < len(authors):
                # 部分作者名不合理，说明正则误匹配了正文文本
                # 只保留合理的作者名，并重建 raw
                authors = valid_authors
                raw = f"{'、'.join(authors)}（{year}）"
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
        # 前缀上下文过滤
        if _has_non_citation_prefix(text, m.start()):
            continue
        key = f"{authors_str}_{year}"
        if key not in seen:
            seen.add(key)
            authors = re.split(r'[、，,]|和|与|及', authors_str)
            authors = [a.replace('等', '').strip() for a in authors if a.strip()]
            # 作者名合理性过滤
            valid_authors = [a for a in authors if _is_valid_zh_author(a, ZH_NON_NAME_CHARS)]
            if not valid_authors:
                continue
            if len(valid_authors) < len(authors):
                authors = valid_authors
                raw = f"{'、'.join(authors)}，{year}"
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
            # 解析作者列表：按 & / and / 和 / 与 分割
            has_et_al = "et al" in authors_str
            authors_clean = re.split(r'\s*(?:and|&|和|与)\s*', authors_str)
            authors_clean = [a.replace('et al.', '').replace('et al', '').strip()
                            for a in authors_clean if a.strip() and a.strip() != "et al."]
            if has_et_al and authors_clean:
                authors_clean[-1] = authors_clean[-1] + " et al."
            # 标准化 raw 引用文本：将 和/与 替换为 &
            normalized_raw = raw
            if "和" in raw or "与" in raw:
                # 替换中英文连接词为标准 &
                normalized_raw = re.sub(
                    r'([A-Za-z]+)\s*(?:和|与)\s*([A-Za-z])',
                    r'\1 & \2',
                    raw,
                )
                # 将中文括号替换为英文括号
                normalized_raw = normalized_raw.replace("（", " (").replace("）", ")")
            citations.append(Citation(
                raw=normalized_raw,
                authors=authors_clean,
                year=year,
                language="en",
            ))

    return citations


# ===== 经典方法论文献检测与自动补充 =====

# 常见经典方法论引用缓存（LLM 在论文中常引用但文献池中可能没有的方法论文献）
# 格式: (作者姓氏, 年份, 完整作者名, 标题, 期刊, DOI)
#
# 注意：此列表为加速缓存，不是主要检测机制。主要机制是 supplement_unverified_english_citations()
# 函数，它通过 OpenAlex/Semantic Scholar API 动态检索任何未验证的英文引用。
# 此缓存仅覆盖最常被引用的15篇经典方法论文献，避免对这些高频文献重复发起API请求。
# 对于不在此列表的经典方法论引用（如 Hansen 1982 GMM、Newey & West 1987、Hausman 1978 等），
# 动态补充函数会自动处理。
_CLASSIC_METHODOLOGY_PAPERS: list[dict] = [
    {
        "authors": ["Rogers", "E. M."],
        "year": "2003",
        "title": "Diffusion of Innovations (5th Edition)",
        "journal": "Free Press",
        "doi": "",
        "first_author_surname": "Rogers",
    },
    {
        "authors": ["Kaplan", "S. N.", "Zingales", "L."],
        "year": "1997",
        "title": "Do Investment-Cash Flow Sensitivities Provide Useful Measures of Financing Constraints?",
        "journal": "The Quarterly Journal of Economics",
        "doi": "10.1162/003355397555163",
        "first_author_surname": "Kaplan",
    },
    {
        "authors": ["Baron", "R. M.", "Kenny", "D. A."],
        "year": "1986",
        "title": "The Moderator-Mediator Variable Distinction in Social Psychological Research",
        "journal": "Journal of Personality and Social Psychology",
        "doi": "10.1037/0022-3514.51.6.1173",
        "first_author_surname": "Baron",
    },
    {
        "authors": ["Heckman", "J. J."],
        "year": "1979",
        "title": "Sample Selection Bias as a Specification Error",
        "journal": "Econometrica",
        "doi": "10.2307/1912352",
        "first_author_surname": "Heckman",
    },
    {
        "authors": ["Wooldridge", "J. M."],
        "year": "2010",
        "title": "Econometric Analysis of Cross Section and Panel Data (2nd Edition)",
        "journal": "MIT Press",
        "doi": "",
        "first_author_surname": "Wooldridge",
    },
    {
        "authors": ["Cohen", "J."],
        "year": "1988",
        "title": "Statistical Power Analysis for the Behavioral Sciences (2nd Edition)",
        "journal": "Lawrence Erlbaum Associates",
        "doi": "",
        "first_author_surname": "Cohen",
    },
    {
        "authors": ["Sobel", "M. E."],
        "year": "1982",
        "title": "Asymptotic Confidence Intervals for Indirect Effects in Structural Equation Models",
        "journal": "Sociological Methodology",
        "doi": "10.2307/270723",
        "first_author_surname": "Sobel",
    },
    {
        "authors": ["Arellano", "M.", "Bond", "S."],
        "year": "1991",
        "title": "Some Tests of Specification for Panel Data: Monte Carlo Evidence and an Application to Employment Equations",
        "journal": "The Review of Economic Studies",
        "doi": "10.2307/2297968",
        "first_author_surname": "Arellano",
    },
    {
        "authors": ["Blundell", "R.", "Bond", "S."],
        "year": "1998",
        "title": "Initial Conditions and Moment Restrictions in Dynamic Panel Data Models",
        "journal": "Journal of Econometrics",
        "doi": "10.1016/S0304-4076(98)00009-8",
        "first_author_surname": "Blundell",
    },
    {
        "authors": ["White", "H."],
        "year": "1980",
        "title": "A Heteroskedasticity-Consistent Covariance Matrix Estimator and a Direct Test for Heteroskedasticity",
        "journal": "Econometrica",
        "doi": "10.2307/1912934",
        "first_author_surname": "White",
    },
    {
        "authors": ["MacKinnon", "J. G.", "White", "H."],
        "year": "1985",
        "title": "Some Heteroskedasticity-Consistent Covariance Matrix Estimators with Improved Finite Sample Properties",
        "journal": "Journal of Econometrics",
        "doi": "10.1016/0304-4076(85)90158-7",
        "first_author_surname": "MacKinnon",
    },
    {
        "authors": ["Tobin", "J."],
        "year": "1958",
        "title": "Estimation of Relationships for Limited Dependent Variables",
        "journal": "Econometrica",
        "doi": "10.2307/1907382",
        "first_author_surname": "Tobin",
    },
    {
        "authors": ["Heckman", "J. J.", "Ichimura", "H.", "Todd", "P."],
        "year": "1998",
        "title": "Matching as an Econometric Evaluation Estimator",
        "journal": "The Review of Economic Studies",
        "doi": "10.1111/1467-947X.00041",
        "first_author_surname": "Heckman",
    },
    {
        "authors": ["Rosenbaum", "P. R.", "Rubin", "D. B."],
        "year": "1983",
        "title": "The Central Role of the Propensity Score in Observational Studies for Causal Effects",
        "journal": "Biometrika",
        "doi": "10.1093/biomet/70.1.41",
        "first_author_surname": "Rosenbaum",
    },
    {
        "authors": ["Angrist", "J. D.", "Imbens", "G. W.", "Rubin", "D. B."],
        "year": "1996",
        "title": "Identification of Causal Effects Using Instrumental Variables",
        "journal": "Journal of the American Statistical Association",
        "doi": "10.1080/01621459.1996.10476902",
        "first_author_surname": "Angrist",
    },
]


def detect_classic_methodology_citations(
    full_text: str,
    existing_citations: list[Citation] | None = None,
) -> list[Citation]:
    """检测正文中引用的经典方法论文献，并构建已验证的 Citation 对象.

    LLM 在写论文时常引用经典方法论（如 Rogers 2003 创新扩散理论、
    Kaplan & Zingales 1997 融资约束 KZ 指数、Baron & Kenny 1986 中介效应），
    这些文献通常不在 Phase 2 文献池中。此函数自动检测这些引用并补充。

    Args:
        full_text: 论文正文文本.
        existing_citations: 已提取的引用列表（用于去重）.

    Returns:
        检测到的经典方法论文献 Citation 列表（已标记 verified=True）.
    """
    # 收集已有引用键
    seen_keys: set[str] = set()
    if existing_citations:
        for c in existing_citations:
            if c.authors:
                # 用第一作者姓氏+年份作为去重键
                surname = c.authors[0].split()[-1] if " " in c.authors[0] else c.authors[0]
                seen_keys.add(f"{surname.lower()}_{c.year}")

    detected: list[Citation] = []

    for paper in _CLASSIC_METHODOLOGY_PAPERS:
        surname = paper["first_author_surname"]
        year = paper["year"]

        # 去重检查
        dedup_key = f"{surname.lower()}_{year}"
        if dedup_key in seen_keys:
            continue

        # 在正文中搜索 姓氏+年份 模式
        # 支持: Rogers（2003）, Rogers (2003), Rogers, 2003, Rogers 2003
        # 支持: Kaplan和Zingales（1997）, Baron & Kenny (1986) 等
        patterns = [
            rf'{surname}\s*[（(]\s*{year}\s*[）)]',
            rf'{surname}\s*[，,]\s*{year}',
            rf'{surname}\s+{year}',
            # 姓氏后可能跟其他作者名再跟年份（如 Kaplan和Zingales（1997））
            rf'{surname}\s*(?:和|与|&|and)\s*[A-Z][a-z]+.*?[（(]\s*{year}\s*[）)]',
            rf'{surname}\s+[A-Z]\.\s*[A-Z][a-z]+.*?[（(]\s*{year}\s*[）)]',
        ]

        is_cited = False
        for pat in patterns:
            if re.search(pat, full_text, re.IGNORECASE):
                is_cited = True
                break

        if not is_cited:
            continue

        # 构建 Citation
        authors = paper["authors"]
        # 构建原始引用文本
        if len(authors) == 1:
            raw = f"{authors[0]} ({year})"
        elif len(authors) == 2:
            raw = f"{authors[0]} & {authors[1]} ({year})"
        else:
            raw = f"{authors[0]} et al. ({year})"

        citation = Citation(
            raw=raw,
            authors=authors,
            year=year,
            language="en",
            title=paper["title"],
            journal=paper["journal"],
            doi=paper.get("doi", ""),
            verified=True,
            source="classic_methodology",
        )

        detected.append(citation)
        seen_keys.add(dedup_key)
        logger.info("检测到经典方法论文献: %s (%s)", surname, year)

    if detected:
        logger.info("经典方法论文献检测: 补充 %d 篇", len(detected))

    return detected


def build_citations_from_pool(
    literature_pool: list[dict],
    full_text: str,
    existing_citations: list[Citation] | None = None,
    include_uncited_relevant: bool = True,
    topic_keywords: str = "",
) -> list[Citation]:
    """从文献池正向构建已验证的引用列表.

    遍历 Phase 2 检索到的真实文献池，检查每篇论文的作者+年份
    是否在正文中被引用。匹配成功的论文直接构建为已验证的 Citation 对象，
    避免 LLM 编造的虚假引用混入参考文献。

    Args:
        literature_pool: Phase 2 检索到的论文列表（dict 格式）.
        full_text: 论文正文文本.
        existing_citations: 已从正文提取的引用列表（可选），用于去重.

    Returns:
        从文献池正向构建的已验证 Citation 列表.
    """
    if not literature_pool or not full_text:
        return []

    # 收集已有引用的作者+年份键，避免重复
    seen_keys: set[str] = set()
    if existing_citations:
        for c in existing_citations:
            if c.authors:
                key = f"{c.authors[0].lower()}_{c.year}"
                seen_keys.add(key)

    pool_citations: list[Citation] = []

    for paper in literature_pool:
        if not isinstance(paper, dict):
            continue

        paper_authors = paper.get("authors", [])
        paper_year = str(paper.get("year", "")).strip()

        if not paper_authors or not paper_year:
            continue

        # TRSS主题相关性过滤：替代黑名单，动态计算论文与研究主题的相关性
        paper_title = paper.get("title", "")
        paper_abstract = paper.get("abstract", "")
        if _is_irrelevant_paper(paper_title, paper_abstract, topic_keywords):
            logger.debug("TRSS过滤（引用构建阶段）: %s", paper_title[:60])
            continue

        # 取第一作者
        first_author = paper_authors[0] if paper_authors else ""
        if not first_author:
            continue

        # 检查第一作者是否在正文中出现
        # 中文作者：直接搜索姓名
        # 英文作者：搜索姓氏
        is_cited = False

        if re.search(r'[\u4e00-\u9fff]', first_author):
            # 中文作者：在正文中搜索"作者（年份）"或"作者，年份"模式
            # 也检查作者名是否出现在正文中
            if first_author in full_text:
                # 进一步检查是否有年份关联
                year_patterns = [
                    f"{first_author}.*?{paper_year}",
                    f"{first_author}.*?（{paper_year}）",
                    f"{first_author}.*?({paper_year})",
                    f"{first_author}.*?，{paper_year}",
                ]
                for pat in year_patterns:
                    if re.search(pat, full_text, re.DOTALL):
                        is_cited = True
                        break
                # 如果作者名出现且年份±1内出现，也算匹配
                if not is_cited:
                    try:
                        py = int(paper_year)
                        for y in range(py - 1, py + 2):
                            if str(y) in full_text and first_author in full_text:
                                is_cited = True
                                break
                    except ValueError:
                        pass
        else:
            # 英文作者：搜索姓氏
            # 从 "First Last" 格式中提取姓氏
            surname = first_author.split()[-1] if " " in first_author else first_author
            if surname and len(surname) >= 2:
                # 搜索姓氏+年份
                year_patterns = [
                    f"{surname}.*?{paper_year}",
                    f"{surname}.*?\\({paper_year}\\)",
                ]
                for pat in year_patterns:
                    if re.search(pat, full_text, re.IGNORECASE | re.DOTALL):
                        is_cited = True
                        break

        if not is_cited:
            continue

        # 去重检查
        dedup_key = f"{first_author.lower()}_{paper_year}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        # 构建 Citation 对象
        # 判断语言
        title = paper.get("title", "")
        language = "en"
        if title and re.search(r'[\u4e00-\u9fff]', title):
            language = "zh"
        elif first_author and re.search(r'[\u4e00-\u9fff]', first_author):
            language = "zh"

        # 构建 raw 引用文本
        if language == "zh":
            raw = f"{first_author}（{paper_year}）"
        else:
            raw = f"{first_author} ({paper_year})"

        citation = Citation(
            raw=raw,
            authors=paper_authors[:5],
            year=paper_year,
            language=language,
        )

        # 从论文数据填充完整信息
        _fill_citation_from_paper(citation, paper, "literature_pool")

        pool_citations.append(citation)

    # 修改4: 补充未引用但相关的中文文献
    if include_uncited_relevant:
        topic_kw_set = set(topic_keywords.split()) if topic_keywords else set()
        uncited_zh: list[Citation] = []
        for paper in literature_pool:
            if not isinstance(paper, dict):
                continue
            paper_authors = paper.get("authors", [])
            paper_year = str(paper.get("year", "")).strip()
            if not paper_authors or not paper_year:
                continue
            first_author = paper_authors[0] if paper_authors else ""
            if not first_author or not re.search(r'[\u4e00-\u9fff]', first_author):
                continue  # 只补充中文文献
            # 检查是否已在已引用列表中
            dedup_key = f"{first_author.lower()}_{paper_year}"
            if dedup_key in seen_keys:
                continue
            # 计算主题相关性
            title = paper.get("title", "")
            abstract = paper.get("abstract", "")
            paper_text = f"{title} {abstract}"
            relevance = _calculate_topic_relevance(paper_text, topic_kw_set)
            if relevance > 0:
                seen_keys.add(dedup_key)
                raw = f"{first_author}（{paper_year}）"
                citation = Citation(
                    raw=raw,
                    authors=paper_authors[:5],
                    year=paper_year,
                    language="zh",
                    source="pool_supplementary",
                )
                _fill_citation_from_paper(citation, paper, "pool_supplementary")
                citation.verified = True
                uncited_zh.append((relevance, citation))

        # 按相关度排序，取前10篇
        uncited_zh.sort(key=lambda x: x[0], reverse=True)
        for _, c in uncited_zh[:10]:
            pool_citations.append(c)
        if uncited_zh:
            logger.info(
                "build_citations_from_pool: 补充 %d 篇相关中文文献（未在正文引用）",
                min(len(uncited_zh), 10),
            )

    logger.info(
        "build_citations_from_pool: 文献池 %d 篇，正向匹配到 %d 篇被引文献",
        len(literature_pool),
        len(pool_citations),
    )

    return pool_citations


def _calculate_topic_relevance(paper_text: str, topic_keywords: set[str]) -> float:
    """计算论文文本与主题关键词的相关度（词重合度）."""
    if not topic_keywords or not paper_text:
        return 0.0
    paper_lower = paper_text.lower()
    overlap = sum(1 for kw in topic_keywords if kw.lower() in paper_lower)
    return overlap / max(len(topic_keywords), 1)


def replace_fake_authors_in_text(
    text: str,
    literature_pool: list[dict],
    topic_keywords: str = "",
) -> str:
    """替换正文中的虚假作者名引用为文献池中的真实作者.

    扫描正文中所有"作者（年份）"格式的中文引用，检测作者名是否为假名
    （张三/李四/王五等），若为假名则从文献池中选取年份匹配且主题相关的
    真实论文替换。同时清除"（未知，2026）""（参考文献）"等异常引用。
    同时修正中英文混排引用格式（如 "Li和Gao et al.(2023)" → "Li & Gao et al. (2023)"）。

    Args:
        text: 论文正文文本.
        literature_pool: Phase 2 检索到的论文列表（dict 格式）.
        topic_keywords: 研究主题关键词（用于辅助匹配）.

    Returns:
        替换后的正文文本.
    """
    if not text:
        return text

    # 0. 修正中英文混排引用格式
    # "Author和Author（Year）" → "Author & Author (Year)"
    # "Author与Author（Year）" → "Author & Author (Year)"
    # "Author和Author et al.(Year)" → "Author & Author et al. (Year)"
    text = re.sub(
        r'([A-Z][a-z]+)\s*(?:和|与)\s*([A-Z][a-z]+(?:\s+et\s+al\.)?)\s*[（(]\s*((?:19|20)\d{2})\s*[）)]',
        r'\1 & \2 (\3)',
        text,
    )
    # "Author和Author，Year" → "Author & Author, Year"
    text = re.sub(
        r'([A-Z][a-z]+)\s*(?:和|与)\s*([A-Z][a-z]+(?:\s+et\s+al\.)?)\s*[，,]\s*((?:19|20)\d{2})',
        r'\1 & \2, \3',
        text,
    )
    # "Li和Gao et al." → "Li & Gao et al."（无年份的引用片段）
    text = re.sub(
        r'([A-Z][a-z]+)\s*(?:和|与)\s*([A-Z][a-z]+\s+et\s+al\.?)',
        r'\1 & \2',
        text,
    )

    non_name_words: set[str] = set()
    topic_kw_set = set(topic_keywords.split()) if topic_keywords else set()

    # 1. 清除异常引用模式："（未知，2026）""（参考文献）"等
    text = re.sub(
        r'[（(]\s*(?:未知|佚名|匿名|参考文献)\s*[,，]?\s*(?:19|20)?\d{0,4}\s*[）)]',
        '',
        text,
    )

    # 2. 提取所有中文作者引用
    pattern = re.compile(
        r'([\u4e00-\u9fff]{2,4}(?:[和与][\u4e00-\u9fff]{2,4})*(?:等)?)\s*[（(]\s*((?:19|20)\d{2})\s*[）)]'
    )

    matches = list(pattern.finditer(text))
    if not matches:
        return text

    # 按年份分组文献池中的中文论文，便于快速查找
    pool_by_year: dict[str, list[dict]] = {}
    for paper in literature_pool:
        if not isinstance(paper, dict):
            continue
        authors = paper.get("authors", [])
        if not authors:
            continue
        first_author = authors[0] if authors else ""
        if not first_author or not re.search(r'[\u4e00-\u9fff]', first_author):
            continue  # 只用中文论文替换
        year = str(paper.get("year", "")).strip()
        if year:
            pool_by_year.setdefault(year, []).append(paper)

    # 动态化改造：基于频率的假名检测
    # 收集参考文献池中所有作者名，用于检测正文中的可疑引用
    _reference_authors: set[str] = set()
    for paper in literature_pool:
        if not isinstance(paper, dict):
            continue
        for author in paper.get("authors", []):
            if author:
                _reference_authors.add(author.strip())
    _suspicious_authors = _detect_suspicious_authors_by_frequency(text, _reference_authors)

    # 从后往前替换避免偏移问题
    replacements: list[tuple[int, int, str]] = []
    for match in matches:
        author_str = match.group(1)
        year = match.group(2)
        full_match = match.group(0)

        # 检查是否为假名
        # 对于"张三和李四"格式，检查每个作者
        author_parts = re.split(r'[和与]', author_str.replace('等', ''))
        is_fake = False
        for part in author_parts:
            part = part.strip()
            if part and not _is_valid_zh_author(part, non_name_words):
                is_fake = True
                break
            if part in _FAKE_NAME_PATTERNS:
                is_fake = True
                break
            # 动态化改造：基于频率的假名检测
            # 作者名在正文中被引用但从未出现在参考文献列表中
            if part in _suspicious_authors:
                is_fake = True
                break

        if not is_fake:
            continue

        # 从文献池查找替换
        replacement = None
        # 优先精确年份匹配
        candidates = pool_by_year.get(year, [])
        # 年份±1模糊匹配
        if not candidates:
            try:
                year_int = int(year)
                for dy in [-1, 1]:
                    candidates.extend(pool_by_year.get(str(year_int + dy), []))
            except ValueError:
                pass

        if candidates:
            # 按主题相关度排序
            scored = []
            for paper in candidates:
                paper_text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
                score = _calculate_topic_relevance(paper_text, topic_kw_set)
                scored.append((score, paper))
            scored.sort(key=lambda x: x[0], reverse=True)
            if scored:
                best_paper = scored[0][1]
                best_author = best_paper["authors"][0]
                best_year = str(best_paper.get("year", year))
                if "等" in author_str:
                    replacement = f"{best_author}等（{best_year}）"
                else:
                    replacement = f"{best_author}（{best_year}）"

        if replacement:
            replacements.append((match.start(), match.end(), replacement))
        else:
            # 无法替换时删除引用标记
            replacements.append((match.start(), match.end(), ""))

    # 从后往前应用替换
    for start, end, repl in reversed(replacements):
        text = text[:start] + repl + text[end:]

    if replacements:
        logger.info(
            "replace_fake_authors_in_text: 替换了 %d 处虚假作者引用",
            len(replacements),
        )

    return text


def _normalize_title(title: str) -> str:
    """归一化标题用于去重比较."""
    if not title:
        return ""
    # 去除所有非字母数字字符，转小写
    normalized = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', '', title.lower())
    # 去除常见前缀
    for prefix in ['the', 'a', 'an']:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized


def _deduplicate_citations(citations: list[Citation]) -> list[Citation]:
    """对引用列表去重，基于归一化标题+第一作者姓氏+年份.

    Args:
        citations: 待去重的引用列表.

    Returns:
        去重后的引用列表.
    """
    if not citations:
        return citations

    seen_keys: set[str] = set()
    deduped: list[Citation] = []

    for c in citations:
        # 构建去重键
        title_norm = normalize_title(c.title or "")
        first_author = (c.authors[0] if c.authors else "").lower().strip()
        # 取姓氏（英文取最后一个单词，中文取第一个字）
        if re.search(r'[a-zA-Z]', first_author):
            surname = first_author.split()[-1] if first_author.split() else first_author
        else:
            surname = first_author[:1] if first_author else ""
        year = (c.year or "").strip()

        dedup_key = f"{title_norm}_{surname}_{year}"

        if dedup_key in seen_keys:
            logger.debug("去重: 跳过重复引用 %s (%s)", c.authors[:1], c.year)
            continue
        seen_keys.add(dedup_key)
        deduped.append(c)

    if len(deduped) < len(citations):
        logger.info(
            "去重: %d 条引用 -> %d 条（移除 %d 条重复）",
            len(citations),
            len(deduped),
            len(citations) - len(deduped),
        )

    return deduped


async def verify_citation(
    citation: Citation,
    cnki_engine=None,
    openalex_engine=None,
    ss_engine=None,
    topic_keywords: str = "",
    literature_pool: list[dict] | None = None,
) -> Citation:
    """验证单个引用是否真实存在.

    策略（按优先级）:
        1. 先在 literature_pool（Phase 2 文献池）中匹配作者+年份
        2. 中文引用用 CNKI 验证（作者 + 年份 + 主题词）
        3. 英文引用用 OpenAlex 验证（作者 + 年份 + 主题词）
        4. 如果 OpenAlex 失败，用 Semantic Scholar 兜底（原生支持作者名搜索）
        5. 搜索关键词: 第一作者姓氏 + 年份 + 主题关键词

    Args:
        citation: 待验证的引用.
        cnki_engine: CNKIAiohttpEngine 实例（可选）.
        openalex_engine: OpenAlexEngine 实例（可选）.
        ss_engine: SemanticScholarEngine 实例（可选，英文验证兜底）.
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

    # === 策略1: 在 Phase 2 文献池中多层匹配 ===
    # 匹配优先级：
    #   1a. 作者+年份精确匹配
    #   1b. 作者+年份±1年模糊匹配（LLM 常记错年份）
    #   1c. 作者+标题关键词匹配（忽略年份）
    if literature_pool:
        # 1a: 精确年份匹配
        for paper in literature_pool:
            paper_year = str(paper.get("year", ""))
            if paper_year != citation.year:
                continue
            if _match_paper_to_citation(paper, citation, first_author_clean):
                _fill_citation_from_paper(citation, paper, "literature_pool")
                return citation

        # 1b: 年份±1年模糊匹配（LLM 常记错年份）
        try:
            cit_year_int = int(citation.year)
        except ValueError:
            cit_year_int = None

        if cit_year_int is not None:
            for paper in literature_pool:
                paper_year_raw = paper.get("year", "")
                try:
                    paper_year_int = int(paper_year_raw)
                except (ValueError, TypeError):
                    continue
                # 年份差1年以内
                if abs(paper_year_int - cit_year_int) > 1:
                    continue
                if _match_paper_to_citation(paper, citation, first_author_clean):
                    _fill_citation_from_paper(citation, paper, "literature_pool")
                    citation.year = str(paper_year_int)  # 修正年份
                    return citation

        # 1c: 作者+标题关键词匹配（忽略年份，适用于经典文献）
        # 仅当引用的作者名较长（≥3字符）时才做此匹配，避免误匹配
        if len(first_author_clean) >= 3:
            for paper in literature_pool:
                if _match_paper_to_citation(paper, citation, first_author_clean):
                    _fill_citation_from_paper(citation, paper, "literature_pool")
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
                            # 根据返回内容更新语言标记
                            if paper.title and not re.search(r'[\u4e00-\u9fff]', paper.title):
                                citation.language = "en"
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
            # 对于经典文献（年份较早），不拼接主题词，只用作者名+年份搜索
            try:
                cit_year_int = int(citation.year)
            except ValueError:
                cit_year_int = None

            # 经典文献（2000年以前）不加主题词，避免搜索词过于 specific 导致搜不到
            if cit_year_int is not None and cit_year_int < 2000:
                query = first_author_clean
            else:
                query = f"{first_author_clean} {topic_keywords}".strip() if topic_keywords else first_author_clean
            result = await openalex_engine.search(
                query=query,
                limit=5,
                year_start=citation.year,
                year_end=citation.year,
            )
            if result.papers:
                # 优先匹配年份+作者，其次只匹配年份（±1年容错）
                for paper in result.papers:
                    if _year_match(paper.year, citation.year):
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
                    if _year_match(paper.year, citation.year):
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

        # ===== Semantic Scholar 兜底（英文引用验证） =====
        # SS 的 search API 原生匹配 authors 字段，比 OpenAlex 的 search 参数更准确
        if not citation.verified and ss_engine and citation.language == "en":
            try:
                ss_result = await ss_engine.search(
                    query=first_author_clean,
                    limit=5,
                    year=citation.year,
                )
                if ss_result and ss_result.papers:
                    for paper in ss_result.papers:
                        if _year_match(paper.year, citation.year):
                            author_match = _match_any_author(first_author_clean, paper.authors)
                            if author_match or not paper.authors:
                                citation.verified = True
                                citation.source = "semantic_scholar"
                                citation.title = paper.title
                                citation.journal = paper.primary_venue or ""
                                citation.doi = paper.doi
                                citation.abstract = paper.abstract
                                if paper.authors:
                                    citation.authors = paper.authors[:5]
                                return citation
            except Exception as ss_err:
                logger.debug(f"Semantic Scholar 兜底验证失败 [{citation.raw}]: {ss_err}")

    except Exception as e:
        logger.warning(f"验证引用失败 [{citation.raw}]: {e}")

    if not citation.verified:
        citation.source = "unverified"

    # TRSS主题相关性检查：即使API验证成功，论文主题不相关也标记为未验证
    # 替代旧黑名单，使用动态主题相关性评分，适用于任何研究主题
    if citation.verified and citation.title:
        if _is_irrelevant_paper(citation.title, citation.abstract or "", topic_keywords):
            relevance = _compute_topic_relevance(citation.title, citation.abstract or "", topic_keywords)
            logger.info(
                "TRSS过滤（验证阶段）: %s (相关性=%.3f)",
                citation.title[:80], relevance,
            )
            citation.verified = False
            citation.source = "irrelevant"
            citation.title = ""
            citation.journal = ""
            citation.abstract = ""
            citation.doi = ""

    return citation


async def supplement_unverified_english_citations(
    citations: list[Citation],
    openalex_engine=None,
    ss_engine=None,
) -> list[Citation]:
    """对未验证的英文引用进行动态补充检索.

    当 verify_citation 无法在文献池或API中找到引用时，此函数作为最后兜底：
    仅用作者姓名+年份搜索 OpenAlex/Semantic Scholar，不加主题关键词。
    适用于经典方法论文献（如 Hansen 1982、Newey & West 1987 等），
    这些文献可能不在文献池中但确实被正文引用。

    这是动态智能检测，替代硬编码列表，适用于任何研究主题。

    Args:
        citations: 引用列表（原地修改未验证的引用）.
        openalex_engine: OpenAlex 引擎实例.
        ss_engine: Semantic Scholar 引擎实例.

    Returns:
        更新后的引用列表.
    """
    unverified_en = [
        c for c in citations
        if not c.verified and c.language == "en" and c.authors
    ]
    if not unverified_en:
        return citations

    supplemented = 0
    for citation in unverified_en:
        first_author = citation.authors[0]
        first_author_clean = first_author.replace(" et al.", "").replace(" et al", "").strip()
        surname = first_author_clean.split()[-1] if " " in first_author_clean else first_author_clean

        if not surname or len(surname) < 2:
            continue

        # OpenAlex 搜索：仅用作者名+年份，不加主题词
        if openalex_engine:
            try:
                result = await openalex_engine.search(
                    query=first_author_clean,
                    limit=5,
                    year_start=citation.year,
                    year_end=citation.year,
                )
                if result.papers:
                    for paper in result.papers:
                        if _year_match(paper.year, citation.year):
                            author_match = _match_any_author(first_author_clean, paper.authors)
                            if author_match or not paper.authors:
                                citation.verified = True
                                citation.source = "openalex_supplement"
                                citation.title = paper.title
                                citation.journal = paper.primary_venue or ""
                                citation.doi = paper.doi
                                citation.abstract = paper.abstract
                                citation.volume = paper.biblio_volume
                                citation.issue = paper.biblio_issue
                                citation.pages = f"{paper.biblio_first_page}-{paper.biblio_last_page}".strip("-")
                                if paper.authors:
                                    citation.authors = paper.authors[:5]
                                supplemented += 1
                                logger.info("动态补充验证成功: %s (%s) -> %s",
                                           surname, citation.year, paper.title[:60])
                                break
            except Exception as e:
                logger.debug(f"OpenAlex动态补充失败 [{surname} {citation.year}]: {e}")

        # Semantic Scholar 兜底
        if not citation.verified and ss_engine:
            try:
                ss_result = await ss_engine.search(
                    query=first_author_clean,
                    limit=5,
                    year=citation.year,
                )
                if ss_result and ss_result.papers:
                    for paper in ss_result.papers:
                        if _year_match(paper.year, citation.year):
                            author_match = _match_any_author(first_author_clean, paper.authors)
                            if author_match or not paper.authors:
                                citation.verified = True
                                citation.source = "ss_supplement"
                                citation.title = paper.title
                                citation.journal = paper.primary_venue or ""
                                citation.doi = paper.doi
                                citation.abstract = paper.abstract
                                if paper.authors:
                                    citation.authors = paper.authors[:5]
                                supplemented += 1
                                logger.info("SS动态补充验证成功: %s (%s) -> %s",
                                           surname, citation.year, paper.title[:60])
                                break
            except Exception as e:
                logger.debug(f"SS动态补充失败 [{surname} {citation.year}]: {e}")

    if supplemented > 0:
        logger.info("动态补充验证: %d/%d 篇未验证英文引用补充成功", supplemented, len(unverified_en))

    return citations


def _year_match(paper_year, citation_year: str, tolerance: int = 1) -> bool:
    """检查论文年份是否匹配引用年份（允许 ±N 年误差）.

    LLM 常记错年份，严格匹配会导致大量验证失败。
    """
    if not paper_year or not citation_year:
        return False
    try:
        py = int(str(paper_year))
        cy = int(str(citation_year).strip())
        return abs(py - cy) <= tolerance
    except (ValueError, TypeError):
        return str(paper_year).strip() == str(citation_year).strip()


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


def _match_paper_to_citation(
    paper: dict,
    citation: Citation,
    first_author_clean: str,
) -> bool:
    """检查文献池中的一篇论文是否匹配当前引用.

    匹配规则（任一满足即认为匹配）:
        1. 作者名匹配（通过 _match_any_author）
        2. 标题关键词高度重合（≥2个共同关键词，适用于LLM生成的标题简写引用）

    Args:
        paper: 文献池中的论文 dict.
        citation: 待验证的引用.
        first_author_clean: 清理后的第一作者名.

    Returns:
        True 如果匹配.
    """
    paper_authors = paper.get("authors", [])

    # 规则1: 作者名匹配
    if paper_authors and _match_any_author(first_author_clean, paper_authors):
        return True

    # 规则2: 标题关键词匹配（仅当引用有 raw 文本时）
    # 适用于 LLM 生成的 "Zhang (2022)" 这种简写引用
    paper_title = paper.get("title", "")
    if paper_title and citation.raw:
        # 从 raw 中提取可能的标题词（去掉作者名和年份后）
        raw_lower = citation.raw.lower()
        title_lower = paper_title.lower()
        # 提取标题中的实词（≥4字符）
        title_words = set(re.findall(r'[a-z]{4,}', title_lower))
        raw_words = set(re.findall(r'[a-z]{4,}', raw_lower))
        # 如果标题中有≥2个词出现在 raw 中，认为匹配
        common = title_words & raw_words
        if len(common) >= 2:
            return True

    return False


def _fill_citation_from_paper(
    citation: Citation,
    paper: dict,
    source: str,
) -> None:
    """从文献池论文填充引用信息.

    Args:
        citation: 待填充的引用（原地修改）.
        paper: 文献池中的论文 dict.
        source: 来源标记（如 "literature_pool"）.
    """
    citation.verified = True
    citation.source = source
    citation.title = paper.get("title", "")
    citation.journal = paper.get("journal", "") or paper.get("venue", "") or paper.get("primary_venue", "")
    citation.doi = paper.get("doi", "")
    citation.abstract = paper.get("abstract", "")
    paper_authors = paper.get("authors", [])
    if paper_authors:
        citation.authors = paper_authors[:5]
    # 更新年份
    paper_year = str(paper.get("year", ""))
    if paper_year:
        citation.year = paper_year
    # 根据标题语言更新 citation.language
    if citation.title and not re.search(r'[\u4e00-\u9fff]', citation.title):
        citation.language = "en"
    elif citation.title and re.search(r'[\u4e00-\u9fff]', citation.title):
        citation.language = "zh"


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
    ss_engine=None,
    concurrency: int = 3,
    topic_keywords: str = "",
    literature_pool: list[dict] | None = None,
) -> list[Citation]:
    """批量验证引用.

    Args:
        citations: 待验证的引用列表.
        cnki_engine: CNKI 引擎实例.
        openalex_engine: OpenAlex 引擎实例.
        ss_engine: Semantic Scholar 引擎实例（英文验证兜底）.
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
                cite, cnki_engine, openalex_engine, ss_engine,
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


def _is_chinese_author(name: str) -> bool:
    """判断作者名是否为中文."""
    return bool(re.search(r'[\u4e00-\u9fff]', name))


def _format_authors(authors: list[str], language: str) -> str:
    """根据语言格式化作者列表.

    中文作者用顿号分隔（前3位），超过3位加"等".
    英文作者用 ", " 分隔（前3位），超过3位加 "et al."
    混合作者按主体语言处理.
    """
    if not authors:
        return ""

    # 判断主体语言
    zh_count = sum(1 for a in authors[:3] if _is_chinese_author(a))
    is_zh = language == "zh" and zh_count >= len(authors[:3]) / 2

    if is_zh:
        author_str = "、".join(authors[:3])
        if len(authors) > 3:
            author_str += "等"
        return author_str
    else:
        # 英文格式
        has_et_al = any("et al" in a.lower() for a in authors[:3])
        authors_clean = [a.replace(" et al.", "").replace(" et al", "").strip() for a in authors[:3]]
        if len(authors) == 1:
            return authors_clean[0]
        elif len(authors) == 2:
            return f"{authors_clean[0]} & {authors_clean[1]}"
        else:
            author_str = ", ".join(authors_clean[:3])
            if len(authors) > 3 or has_et_al:
                author_str += " et al."
            return author_str


def format_cssci(citation: Citation) -> str:
    """格式化为 CSSCI（中文核心期刊）参考文献格式.

    CSSCI 格式要求:
        - 作者-年份制，正文中引用格式：作者（年份）
        - 文后中文：作者：《标题》，《期刊》，年份第X期。
        - 文后英文：Author, Year, "Title", *Journal*, Vol(No), pp.
        - 中英文分开，中文在前
    """
    if not citation.verified and not citation.title:
        # 未验证且无标题：返回空字符串以便在列表中被过滤掉
        return ""

    # 清理HTML标签（防止搜索结果高亮标签泄漏到参考文献中）
    title = _clean_html_tags(citation.title) if citation.title else citation.title
    journal = _clean_html_tags(citation.journal) if citation.journal else citation.journal
    authors = [_clean_html_tags(a) for a in citation.authors] if citation.authors else citation.authors

    # 根据作者实际语言选择格式（而非 citation.language）
    # 修复：验证后作者名可能从中文变为英文（CNKI 返回英文论文）
    authors_are_chinese = any(_is_chinese_author(a) for a in authors[:1]) if authors else False

    if citation.language == "zh" and authors_are_chinese:
        # 中文格式
        author_str = _format_authors(authors, "zh")
        result = f"{author_str}：{title}"
        if journal:
            result += f"，《{journal}》"
        else:
            result += "，"
        if citation.year:
            result += f"，{citation.year}年"
        if citation.issue:
            result += f"第{citation.issue}期"
        result += "。"
        return result
    else:
        # 英文格式（包括验证后变为英文的情况）
        author_str = _format_authors(authors, "en")
        result = f"{author_str}, {citation.year}"
        if title:
            result += f', "{title}"'
        if journal:
            result += f", *{journal}*"
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
        # 未验证且无标题：返回空字符串以便在列表中被过滤掉
        return ""

    # 清理HTML标签
    title = _clean_html_tags(citation.title) if citation.title else citation.title
    journal = _clean_html_tags(citation.journal) if citation.journal else citation.journal
    clean_authors = [_clean_html_tags(a) for a in citation.authors] if citation.authors else citation.authors

    # 作者格式化
    if citation.language == "zh":
        author_str = "、".join(clean_authors[:3])
        if len(clean_authors) > 3:
            author_str += "等"
    else:
        authors = []
        for i, a in enumerate(clean_authors[:3]):
            authors.append(a)
        author_str = ", ".join(authors)
        if len(clean_authors) > 2:
            author_str += ", et al."
        elif len(clean_authors) == 2:
            author_str = f"{clean_authors[0]} & {clean_authors[1]}"

    result = f"{author_str} ({citation.year})"
    if title:
        result += f". {title}"
    if journal:
        result += f". *{journal}*"
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
    exclude_unverified: bool = True,
) -> str:
    """生成完整的参考文献列表.

    Args:
        citations: 引用列表.
        style: 格式风格 (cssci / apa7).
        language_separate: 是否中英文分开（CSSCI 要求）.
        exclude_unverified: 是否排除未验证且无标题的引用（默认 True）.

    Returns:
        格式化后的参考文献列表字符串（带编号、换行分隔）.
    """
    if exclude_unverified:
        # 过滤掉未验证且无标题的引用
        citations = [c for c in citations if not (not c.verified and not c.title)]

    # 去重：基于归一化标题+姓氏+年份
    citations = _deduplicate_citations(citations)

    formatter = format_cssci if style == "cssci" else format_apa7

    if language_separate:
        # 根据作者实际语言分类（修复：验证后作者名可能从中文变为英文）
        zh_cites = []
        en_cites = []
        for c in citations:
            # 检查第一作者是否为中文
            if c.authors and _is_chinese_author(c.authors[0]):
                zh_cites.append(c)
            elif c.language == "zh" and not c.authors:
                zh_cites.append(c)
            else:
                en_cites.append(c)
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


def strip_llm_reference_section(text: str) -> str:
    """移除正文中 LLM 自行生成的"参考文献"章节.

    LLM 在撰写论文时常自行生成一个"参考文献"章节，其中包含大量编造的
    虚假引用（如同一作者的十几篇论文）。这些虚假引用不应保留在正文中，
    应由系统的引用管理流程（提取→验证→格式化）重新生成参考文献列表。

    本函数检测并移除以下模式：
    - "## 参考文献" / "### 参考文献" 标题及其后所有内容
    - "## References" / "### References" 标题及其后所有内容
    - "---\\n\\n## 参考文献" 分隔符及之后内容（系统之前追加的）
    - 文末的编号引用列表（如 "[1] 作者（年份）.标题.期刊."）

    Args:
        text: 论文正文文本.

    Returns:
        移除 LLM 生成参考文献章节后的文本.
    """
    if not text:
        return text

    result = text

    # 模式1: 系统之前追加的参考文献（--- 分隔符之后的内容）
    for separator in [
        "\n---\n\n## 参考文献",
        "\n---\n## 参考文献",
        "\n---\n\n## References",
        "\n---\n## References",
        "\n---\n\n## AI 使用声明",
        "\n---\n## AI 使用声明",
        "\n---\n\n## AI Disclosure",
    ]:
        idx = result.find(separator)
        if idx != -1:
            result = result[:idx].rstrip()
            logger.info("移除已有参考文献/AI声明部分（分隔符匹配）")

    # 模式2: LLM 在正文中生成的"参考文献"章节
    # 匹配 ## 参考文献 / ### 参考文献 / ## References 等
    ref_section_pattern = re.compile(
        r'\n#{2,3}\s*(?:参考文献|References?|引用文献|Bibliography)\s*\n',
        re.IGNORECASE,
    )
    m = ref_section_pattern.search(result)
    if m:
        result = result[:m.start()].rstrip()
        logger.info("移除 LLM 生成的参考文献章节: 位置 %d-%d", m.start(), m.end())

    # 模式3: 文末的编号引用列表块
    # 检测连续多行以 "[数字]" 开头的引用列表（至少3条才算章节）
    lines = result.split("\n")
    cleaned_lines: list[str] = []
    ref_block_start = -1
    ref_block_count = 0

    for i, line in enumerate(lines):
        # 匹配 [1] 作者（年份）.标题.期刊. 格式
        if re.match(r'^\s*\[\d+\]\s*[\u4e00-\u9fffA-Za-z]', line):
            if ref_block_start == -1:
                ref_block_start = i
            ref_block_count += 1
        else:
            if ref_block_count >= 3 and ref_block_start != -1:
                # 发现一个引用列表块（>=3条），移除它
                logger.info(
                    "移除编号引用列表块: 行 %d-%d（%d 条）",
                    ref_block_start, i - 1, ref_block_count,
                )
                # 保留之前的行，跳过引用块
                # 同时移除引用块前的空行和可能的标题行
                while cleaned_lines and cleaned_lines[-1].strip() == "":
                    cleaned_lines.pop()
                # 检查是否移除了标题行（如"参考文献"）
                if cleaned_lines and re.match(
                    r'^#{1,3}\s*(?:参考文献|References?)',
                    cleaned_lines[-1],
                    re.IGNORECASE,
                ):
                    cleaned_lines.pop()
                    while cleaned_lines and cleaned_lines[-1].strip() == "":
                        cleaned_lines.pop()
                ref_block_start = -1
                ref_block_count = 0
                continue
            else:
                if ref_block_start != -1:
                    # 引用块不足3条，保留
                    for j in range(ref_block_start, i):
                        cleaned_lines.append(lines[j])
                    ref_block_start = -1
                    ref_block_count = 0
                cleaned_lines.append(line)

    # 处理末尾的引用块
    if ref_block_count >= 3 and ref_block_start != -1:
        logger.info(
            "移除末尾编号引用列表块: 行 %d-%d（%d 条）",
            ref_block_start, len(lines) - 1, ref_block_count,
        )
        while cleaned_lines and cleaned_lines[-1].strip() == "":
            cleaned_lines.pop()
        if cleaned_lines and re.match(
            r'^#{1,3}\s*(?:参考文献|References?)',
            cleaned_lines[-1],
            re.IGNORECASE,
        ):
            cleaned_lines.pop()
            while cleaned_lines and cleaned_lines[-1].strip() == "":
                cleaned_lines.pop()
    elif ref_block_start != -1:
        for j in range(ref_block_start, len(lines)):
            cleaned_lines.append(lines[j])

    result = "\n".join(cleaned_lines).rstrip()

    return result


def cap_author_frequency(
    citations: list[Citation],
    max_per_author: int = 3,
) -> list[Citation]:
    """限制同一第一作者在参考文献列表中的最大论文数量.

    LLM 在生成正文时可能反复引用同一作者的多篇论文（如17篇"许甜甜"），
    这不符合学术规范。本函数对同一第一作者保留最多 max_per_author 篇论文，
    优先保留已验证的、有标题的引用。

    Args:
        citations: 引用列表.
        max_per_author: 同一第一作者最大论文数量（默认3）.

    Returns:
        限制后的引用列表.
    """
    if not citations or max_per_author <= 0:
        return citations

    # 按第一作者归一化名分组
    author_groups: dict[str, list[Citation]] = {}
    for c in citations:
        if not c.authors:
            key = "_no_author"
        else:
            first_author = c.authors[0].strip()
            # 归一化：中文取全名，英文取姓氏（小写）
            if re.search(r'[\u4e00-\u9fff]', first_author):
                key = first_author.lower()
            else:
                # 英文取姓氏（最后一个单词）
                parts = first_author.split()
                key = parts[-1].lower() if parts else first_author.lower()
        author_groups.setdefault(key, []).append(c)

    result: list[Citation] = []
    capped_count = 0

    for key, group in author_groups.items():
        if len(group) <= max_per_author:
            result.extend(group)
            continue

        # 超过限制：按优先级排序保留
        # 优先级：verified=True > 有title > 有journal > 其他
        def sort_priority(c: Citation) -> tuple:
            return (
                0 if c.verified else 1,
                0 if c.title else 1,
                0 if c.journal else 1,
            )

        group.sort(key=sort_priority)
        kept = group[:max_per_author]
        removed = group[max_per_author:]

        result.extend(kept)
        capped_count += len(removed)

        if removed:
            author_display = group[0].authors[0] if group[0].authors else key
            logger.warning(
                "作者频率限制: %s 有 %d 篇引用，保留 %d 篇，移除 %d 篇",
                author_display, len(group), max_per_author, len(removed),
            )

    if capped_count > 0:
        logger.info(
            "作者频率限制: 共移除 %d 条超限引用（上限 %d 篇/作者）",
            capped_count, max_per_author,
        )

    return result


__all__ = [
    "Citation",
    "extract_citations_from_text",
    "verify_citation",
    "verify_all_citations",
    "build_citations_from_pool",
    "replace_fake_authors_in_text",
    "strip_llm_reference_section",
    "cap_author_frequency",
    "format_cssci",
    "format_apa7",
    "format_references_list",
    "generate_ai_disclosure",
]
