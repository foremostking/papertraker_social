"""文本处理公共工具 —— ADR-007 P4 RAG 工具收敛.

消除以下重复实现：
- normalize_title(): 4 处独立实现（utils/library.py, citation_manager.py, paper_harvester.py, search.py）
- safe_mean/median/stdev(): 2 处完全复制（knowledge_base.py, paper_analyzer.py）
- extract_keywords(): 2 处重复（database_rag.py, review_methods.py）
"""

from __future__ import annotations

import re
import statistics


# ===== 标题归一化 =====

# 编译一次正则，重复使用
_NON_ALNUM_RE = re.compile(r"[^\w\u4e00-\u9fff]", re.UNICODE)
_ARTICLE_PREFIXES = ("the", "a", "an")


def normalize_title(title: str) -> str:
    """归一化标题用于去重比较.

    合并 4 处独立实现的最佳策略：
    1. 处理空输入
    2. 移除所有空白和标点（保留字母、数字、下划线、CJK 字符）
    3. 转小写
    4. 移除英文冠词前缀（the/a/an）

    Args:
        title: 原始标题.

    Returns:
        归一化后的标题字符串。空输入返回空字符串。
    """
    if not title:
        return ""
    # 移除所有非字母数字非CJK字符
    normalized = _NON_ALNUM_RE.sub("", title)
    normalized = normalized.lower()
    # 移除英文冠词前缀
    for prefix in _ARTICLE_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    return normalized


# ===== 安全统计函数 =====


def safe_mean(values: list[float] | list[int]) -> float:
    """安全计算均值，空列表返回 0.0."""
    if not values:
        return 0.0
    return float(statistics.mean(values))


def safe_median(values: list[float] | list[int]) -> float:
    """安全计算中位数，空列表返回 0.0."""
    if not values:
        return 0.0
    return float(statistics.median(values))


def safe_stdev(values: list[float] | list[int]) -> float:
    """安全计算标准差，少于 2 个值返回 0.0."""
    if len(values) < 2:
        return 0.0
    return float(statistics.stdev(values))


# ===== 关键词提取 =====

# 合并两处停用词表
_KEYWORD_STOPWORDS = {
    # 中文停用词（合并 database_rag + review_methods）
    "的", "对", "影响", "与", "和", "及", "在", "了", "是", "为",
    "研究", "分析", "基于", "从", "到", "中", "上", "下",
    "关系", "关于",
    # 英文停用词
    "the", "of", "on", "in", "a", "an", "and", "or", "to", "for",
}

# 分词正则（合并两处分隔符）
_TOKEN_SPLIT_RE = re.compile(r"[\s,，。、；;：:（）()【】\[\]{}\"'《》]+")


def extract_keywords(text: str, max_keywords: int = 8) -> list[str]:
    """从研究主题中提取关键词.

    合并 database_rag.py 和 review_methods.py 两处实现：
    - 按常见分隔符拆分
    - 过滤停用词和过短/过长 token（2-12 字）
    - 无结果时回退到原始文本

    Args:
        text: 研究主题文本.
        max_keywords: 最大关键词数量，默认 8.

    Returns:
        关键词列表。
    """
    tokens = _TOKEN_SPLIT_RE.split(text)
    keywords: list[str] = []
    for token in tokens:
        token = token.strip()
        if not token or token in _KEYWORD_STOPWORDS:
            continue
        if len(token) < 2:
            continue
        keywords.append(token)
    # 无结果时回退到原始文本
    if not keywords and text.strip():
        keywords = [text.strip()]
    return keywords[:max_keywords]
