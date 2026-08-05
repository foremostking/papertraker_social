"""CNKI MCP Server.

将 CNKI 检索能力封装为 MCP Server，供 Scholar Agent 通过 MCP 协议调用。
提炼了旧代码（papertraker_20260124）的核心检索算法，
包括 4 层检索策略、分组统计等。

Usage:
    # 作为独立 MCP Server 运行
    python -m scholarpilot.mcp.servers.cnki.server

    # 在 Scholar Agent 中通过 MCP Client 连接
    # 见 scholarpilot.mcp.client.MCPClientManager
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ===== 数据模型 =====

@dataclass
class CNKIPaper:
    """CNKI 检索结果中的单篇论文。"""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: str = ""
    source: str = ""  # 期刊/学位论文/会议等
    fund: str = ""  # 基金资助
    cited_count: int = 0
    download_count: int = 0
    url: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "journal": self.journal,
            "year": self.year,
            "source": self.source,
            "fund": self.fund,
            "cited_count": self.cited_count,
            "download_count": self.download_count,
            "url": self.url,
            "abstract": self.abstract,
            "keywords": self.keywords,
        }


@dataclass
class CNKISearchResult:
    """CNKI 检索结果。"""

    query: str = ""
    total_count: int = 0
    papers: list[CNKIPaper] = field(default_factory=list)
    group_stats: dict[str, Any] = field(default_factory=dict)  # 分组统计
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_count": self.total_count,
            "papers": [p.to_dict() for p in self.papers],
            "group_stats": self.group_stats,
        }


@dataclass
class QueryLayer:
    """单层检索式。"""

    layer: int
    description: str
    query: str  # CNKI 检索语法
    purpose: str



# ===== 8 维统计分析 =====

def calculate_eight_dimensions(
    layer_results: list[CNKISearchResult],
) -> dict[str, Any]:
    """计算 8 维统计数据.

    提炼自 papertraker_20260124 的 statistics_collector.py 核心算法。
    基于 4 层检索结果计算 8 个维度的统计数据。

    8 个维度：
    1. 文献总量（各层结果数）
    2. 核心刊占比（CSSCI/北大核心占比）
    3. 年度趋势（近3年占比，判断上升/稳定/下降）
    4. 学科对口度（相关学科占比）
    5. 研究层次（期刊/学位/会议占比）
    6. 关键词分布（高频关键词）
    7. 期刊来源（Top期刊）
    8. 竞争程度（基于总量和趋势的综合评估）

    Args:
        layer_results: 4 层检索结果列表。

    Returns:
        8 维统计数据字典。
    """
    stats: dict[str, Any] = {}

    # 1. 文献总量
    layer_counts = [r.total_count for r in layer_results]
    stats["literature_volume"] = {
        "layer1_precise": layer_counts[0] if len(layer_counts) > 0 else 0,
        "layer2_regional": layer_counts[1] if len(layer_counts) > 1 else 0,
        "layer3_benchmark": layer_counts[2] if len(layer_counts) > 2 else 0,
        "layer4_overall": layer_counts[3] if len(layer_counts) > 3 else 0,
        "total": sum(layer_counts),
    }

    # 2. 核心刊占比（从分组统计获取）
    all_papers: list[CNKIPaper] = []
    for r in layer_results:
        all_papers.extend(r.papers)

    core_journals = []
    for p in all_papers:
        # 简单判断：CSSCI/北大核心/SCI 标记
        if any(kw in p.source.upper() for kw in ["CSSCI", "北大核心", "SCI", "EI", "CSCD"]):
            core_journals.append(p)

    stats["core_journal_ratio"] = {
        "core_count": len(core_journals),
        "total_count": len(all_papers),
        "ratio": len(core_journals) / len(all_papers) if all_papers else 0,
    }

    # 3. 年度趋势
    year_dist: dict[str, int] = {}
    for p in all_papers:
        if p.year:
            year_dist[p.year] = year_dist.get(p.year, 0) + 1

    sorted_years = sorted(year_dist.keys(), reverse=True)
    recent_3_years = sum(year_dist[y] for y in sorted_years[:3] if y)
    total_with_year = sum(year_dist.values())
    recent_ratio = recent_3_years / total_with_year if total_with_year > 0 else 0
    trend = "rising" if recent_ratio > 0.5 else "stable"
    stats["year_trend"] = {
        "distribution": year_dist,
        "recent_3_years_ratio": recent_ratio,
        "trend": trend,
    }

    # 4. 学科对口度
    subject_stats: dict[str, int] = {}
    for r in layer_results:
        subjects = r.group_stats.get("subject", [])
        for s in subjects:
            subject_stats[s["name"]] = subject_stats.get(s["name"], 0) + s["count"]

    stats["subject_relevance"] = {
        "top_subjects": sorted(subject_stats.items(), key=lambda x: x[1], reverse=True)[:10],
    }

    # 5. 期刊来源分布
    journal_dist: dict[str, int] = {}
    for p in all_papers:
        if p.journal:
            journal_dist[p.journal] = journal_dist.get(p.journal, 0) + 1

    stats["journal_distribution"] = {
        "top_journals": sorted(journal_dist.items(), key=lambda x: x[1], reverse=True)[:10],
        "unique_journals": len(journal_dist),
    }

    # 6. 基金资助
    fund_stats: dict[str, int] = {}
    for r in layer_results:
        funds = r.group_stats.get("fund", [])
        for f in funds:
            fund_stats[f["name"]] = fund_stats.get(f["name"], 0) + f["count"]

    stats["fund_support"] = {
        "top_funds": sorted(fund_stats.items(), key=lambda x: x[1], reverse=True)[:10],
        "funded_ratio": len(fund_stats) / len(all_papers) if all_papers else 0,
    }

    # 7. 机构分布
    institution_stats: dict[str, int] = {}
    for r in layer_results:
        institutions = r.group_stats.get("institution", [])
        for inst in institutions:
            institution_stats[inst["name"]] = institution_stats.get(inst["name"], 0) + inst["count"]

    stats["institution_distribution"] = {
        "top_institutions": sorted(institution_stats.items(), key=lambda x: x[1], reverse=True)[:10],
    }

    # 8. 竞争程度评估（基于近 7 年文献总量，匹配经济学引用半衰期 4.2 年）
    total = stats["literature_volume"]["total"]
    trend = stats["year_trend"]["trend"]
    if total > 700:
        competition = "red_ocean"  # 红海：近 7 年 >700 篇
    elif total > 150:
        competition = "moderate"  # 中等
    elif total > 30:
        competition = "blue_ocean"  # 蓝海
    else:
        competition = "cold_spot"  # 冷门

    stats["competition_level"] = {
        "total_literature": total,
        "trend": trend,
        "level": competition,
        "assessment": {
            "red_ocean": "竞争激烈，需差异化切入",
            "moderate": "竞争适中，有发展空间",
            "blue_ocean": "蓝海领域，机会较大",
            "cold_spot": "冷门方向，需谨慎评估",
        }.get(competition, ""),
    }

    return stats


# ===== 可行性判定 =====

def assess_feasibility(
    eight_dim_stats: dict[str, Any],
    research_type: str = "empirical",
) -> dict[str, Any]:
    """基于 8 维统计进行选题可行性判定.

    提炼自 papertraker_20260124 的 feasibility_analyzer.py 核心规则。

    Args:
        eight_dim_stats: 8 维统计数据。
        research_type: 研究类型（empirical/ theoretical/ case_study/ review）。

    Returns:
        可行性判定结果。
    """
    total = eight_dim_stats.get("literature_volume", {}).get("total", 0)
    competition = eight_dim_stats.get("competition_level", {}).get("level", "moderate")
    trend = eight_dim_stats.get("year_trend", {}).get("trend", "stable")
    core_ratio = eight_dim_stats.get("core_journal_ratio", {}).get("ratio", 0)

    # 判定逻辑
    if competition == "blue_ocean" and trend == "rising":
        verdict = "high_quality_gap"
        confidence = 0.85
        reasoning = "蓝海领域且呈上升趋势，存在高质量研究空白，适合切入。"
    elif competition == "blue_ocean":
        verdict = "emerging_field"
        confidence = 0.7
        reasoning = "蓝海领域，研究尚少，但趋势不够明确，需进一步验证。"
    elif competition == "red_ocean" and trend == "rising":
        verdict = "competitive_hot"
        confidence = 0.5
        reasoning = "红海但仍在上升，需找到差异化切口才有机会。"
    elif competition == "red_ocean":
        verdict = "saturated"
        confidence = 0.3
        reasoning = "领域饱和且无增长趋势，发表难度大。"
    elif competition == "cold_spot":
        verdict = "cold_spot"
        confidence = 0.4
        reasoning = "文献极少，可能是冷门方向，需确认是否真有研究价值。"
    else:
        verdict = "moderate"
        confidence = 0.6
        reasoning = "竞争适中，有机会但需找准角度。"

    return {
        "verdict": verdict,
        "confidence": confidence,
        "reasoning": reasoning,
        "competition_level": competition,
        "trend": trend,
        "total_literature": total,
        "core_journal_ratio": core_ratio,
        "recommendation": {
            "high_quality_gap": "强烈推荐！领域空白且趋势向好，抓紧推进。",
            "emerging_field": "推荐，但需更多文献验证方向。",
            "competitive_hot": "需找到差异化切入点，建议聚焦细分领域。",
            "saturated": "不建议直接进入，考虑换角度或区域。",
            "cold_spot": "谨慎推进，需确认文献少的真实原因。",
            "moderate": "可以做，但需精心设计研究方案。",
        }.get(verdict, ""),
    }
