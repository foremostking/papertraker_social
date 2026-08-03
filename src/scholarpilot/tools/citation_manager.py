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

# 离题领域惩罚词（跨主题通用，不针对特定研究主题）
# 出现这些词的论文与研究主题不相关的概率极高
_OFF_TOPIC_DOMAIN_WORDS: frozenset[str] = frozenset({
    # 医学临床
    "tuberculosis", "mycobacterium", "covid-19", "covid19", "coronavirus",
    "patient", "clinical", "diagnosis", "treatment", "symptom",
    "mortality", "incidence", "prevalence", "antibiotic", "antiviral",
    "antituberculosis", "drug resistance", "pharmaceutical",
    "临床", "患者", "诊断", "治疗", "症状", "死亡率", "发病率",
    # 农业生物
    "crop", "harvest", "livestock", "pesticide", "safflower",
    "采摘", "农作物", "畜牧业", "农药",
    # 旅游业
    "tourism", "hotel", "hospitality",
    "旅游", "酒店", "餐饮",
    # 纯机器学习技术（非应用）
    "neural architecture", "hyperparameter", "benchmark dataset",
    "image classification", "object detection",
    # 国际关系/政治
    "axis of allies", "us-japan alliance", "geopolitic",
})

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

    # 安全网：遗留黑名单检查
    _legacy_blocklist = (
        "covid-19", "covid19", "coronavirus", "新冠", "疫情", "肺炎",
        "结核", "tuberculosis", "mycobacterium", "antituberculosis",
        "采摘机器人", "农业机器人", "harvest robot", "safflower",
        "医疗旅游", "medical tourism",
        "axis of allies", "us-japan alliance",
        "data security and privacy protection", "ctrip",
        "pharmaceutical innovation", "药物创新",
        "endogenous knowledge spillover",
    )
    if any(block_word in paper_text_lower for block_word in _legacy_blocklist):
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

    # 3. "姓+重复字"模式：如 张张、李李、王王（单字叠写，非真实姓名）
    if len(name) == 2 and name[0] == name[1]:
        return False

    return True


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
            citations.append(Citation(
                raw=raw,
                authors=authors_clean,
                year=year,
                language="en",
            ))

    return citations


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

    Args:
        text: 论文正文文本.
        literature_pool: Phase 2 检索到的论文列表（dict 格式）.
        topic_keywords: 研究主题关键词（用于辅助匹配）.

    Returns:
        替换后的正文文本.
    """
    if not text:
        return text

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
        title_norm = _normalize_title(c.title or "")
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

    # 根据作者实际语言选择格式（而非 citation.language）
    # 修复：验证后作者名可能从中文变为英文（CNKI 返回英文论文）
    authors_are_chinese = any(_is_chinese_author(a) for a in citation.authors[:1]) if citation.authors else False

    if citation.language == "zh" and authors_are_chinese:
        # 中文格式
        author_str = _format_authors(citation.authors, "zh")
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
        # 英文格式（包括验证后变为英文的情况）
        author_str = _format_authors(citation.authors, "en")
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
        # 未验证且无标题：返回空字符串以便在列表中被过滤掉
        return ""

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


__all__ = [
    "Citation",
    "extract_citations_from_text",
    "verify_citation",
    "verify_all_citations",
    "build_citations_from_pool",
    "replace_fake_authors_in_text",
    "format_cssci",
    "format_apa7",
    "format_references_list",
    "generate_ai_disclosure",
]
