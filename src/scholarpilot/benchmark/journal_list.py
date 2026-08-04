"""CSSCI核心期刊列表（财政/经济金融类）.

收录南大核心（CSSCI）经济学、财政金融、管理学方向的高质量期刊。
每个期刊包含: 名称、ISSN、学科类别、影响力等级。

数据来源: CSSCI (2023-2024) 南大核心期刊目录
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JournalInfo:
    """期刊信息."""

    name: str          # 期刊名称
    issn: str = ""     # ISSN号
    category: str = "" # 学科类别
    tier: str = "A"    # 影响力等级: A(顶级)/B(核心)/C(重要)
    cnki_code: str = "" # CNKI期刊代码（如有）


# CSSCI核心期刊列表 — 财政/经济金融/管理学方向
CSSCI_JOURNALS: list[JournalInfo] = [
    # ===== 顶级经济学期刊 (Tier A) =====
    JournalInfo(name="经济研究", issn="0577-9154", category="经济学", tier="A"),
    JournalInfo(name="管理世界", issn="1002-5502", category="管理学", tier="A"),
    JournalInfo(name="经济学(季刊)", issn="2095-1086", category="经济学", tier="A"),
    JournalInfo(name="中国工业经济", issn="1006-480X", category="经济学", tier="A"),
    JournalInfo(name="世界经济", issn="1002-9621", category="经济学", tier="A"),
    JournalInfo(name="数量经济技术经济研究", issn="1000-3894", category="经济学", tier="A"),

    # ===== 财政金融类核心期刊 (Tier A/B) =====
    JournalInfo(name="金融研究", issn="1006-1690", category="金融学", tier="A"),
    JournalInfo(name="财政研究", issn="1003-2878", category="财政学", tier="A"),
    JournalInfo(name="财贸经济", issn="1002-8102", category="财政贸易", tier="A"),
    JournalInfo(name="财经研究", issn="1001-9952", category="经济学", tier="B"),
    JournalInfo(name="国际金融研究", issn="1674-7630", category="金融学", tier="B"),
    JournalInfo(name="金融经济学研究", issn="1674-1625", category="金融学", tier="B"),
    JournalInfo(name="证券市场导报", issn="1005-5557", category="金融学", tier="B"),
    JournalInfo(name="当代财经", issn="1005-0892", category="经济学", tier="B"),
    JournalInfo(name="财经科学", issn="1000-8306", category="经济学", tier="B"),
    JournalInfo(name="上海金融", issn="1006-1428", category="金融学", tier="B"),
    JournalInfo(name="投资研究", issn="1003-7624", category="金融学", tier="B"),
    JournalInfo(name="保险研究", issn="1004-3306", category="金融学", tier="B"),

    # ===== 会计审计类 (Tier B) =====
    JournalInfo(name="会计研究", issn="1003-2860", category="会计学", tier="A"),
    JournalInfo(name="审计研究", issn="1002-4239", category="审计学", tier="B"),

    # ===== 经济管理类 (Tier B/C) =====
    JournalInfo(name="经济管理", issn="1002-5766", category="管理学", tier="B"),
    JournalInfo(name="宏观经济研究", issn="1008-2069", category="经济学", tier="B"),
    JournalInfo(name="中国经济问题", issn="1000-4181", category="经济学", tier="B"),
    JournalInfo(name="经济问题探索", issn="1006-2912", category="经济学", tier="B"),
    JournalInfo(name="当代经济科学", issn="1002-2848", category="经济学", tier="B"),
    JournalInfo(name="南开经济研究", issn="1001-4691", category="经济学", tier="B"),
    JournalInfo(name="经济评论", issn="1005-2674", category="经济学", tier="B"),
    JournalInfo(name="经济学动态", issn="1002-8390", category="经济学", tier="B"),

    # ===== 区域经济与公共财政 (Tier B/C) =====
    JournalInfo(name="地方财政研究", issn="1672-9544", category="财政学", tier="B"),
    JournalInfo(name="涉外税务", issn="1006-3055", category="财政税收", tier="B"),
    JournalInfo(name="税务研究", issn="1003-4471", category="财政税收", tier="B"),
    JournalInfo(name="亚太经济", issn="1000-6052", category="区域经济", tier="B"),
    JournalInfo(name="城市问题", issn="1002-2031", category="城市经济", tier="B"),

    # ===== 综合经济类 (Tier C) =====
    JournalInfo(name="经济纵横", issn="1007-7685", category="经济学", tier="B"),
    JournalInfo(name="经济学家", issn="1003-765X", category="经济学", tier="B"),
    JournalInfo(name="经济经纬", issn="1006-1096", category="经济学", tier="B"),
    JournalInfo(name="当代经济研究", issn="1005-2674", category="经济学", tier="B"),
    JournalInfo(name="河北经贸大学学报", issn="1007-2101", category="经济学", tier="C"),
    JournalInfo(name="首都经济贸易大学学报", issn="1008-2700", category="经济学", tier="C"),
]


def get_journals_by_category(category: str = "") -> list[JournalInfo]:
    """按学科类别筛选期刊.

    Args:
        category: 学科类别（如"经济学""金融学""财政学""管理学"）.
                   空字符串返回全部.

    Returns:
        符合条件的期刊列表.
    """
    if not category:
        return CSSCI_JOURNALS
    return [j for j in CSSCI_JOURNALS if category in j.category]


def get_journals_by_tier(tier: str = "") -> list[JournalInfo]:
    """按影响力等级筛选期刊.

    Args:
        tier: 等级（A/B/C）. 空字符串返回全部.

    Returns:
        符合条件的期刊列表.
    """
    if not tier:
        return CSSCI_JOURNALS
    return [j for j in CSSCI_JOURNALS if j.tier == tier]


def get_journal_names() -> list[str]:
    """获取所有期刊名称列表."""
    return [j.name for j in CSSCI_JOURNALS]
