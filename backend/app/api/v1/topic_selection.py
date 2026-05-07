"""
选题功能API端点

提供想法解析、关键词验证、选题生成等功能的API
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.services.cnki_literature_validator import validate_keywords_async

router = APIRouter(prefix="/api/v1/topic-selection", tags=["topic-selection"])


class CNKIValidationRequest(BaseModel):
    """CNKI验证请求"""
    keywords: List[str]  # 关键词列表


class SourceDistributionItem(BaseModel):
    """来源类别分布项"""
    name: str
    count: int


class TopJournalItem(BaseModel):
    """热门期刊项"""
    name: str
    count: int
    core_types: List[str]


class CNKIValidationResponse(BaseModel):
    """CNKI验证响应"""
    keywords: List[str]
    search_query: str
    total_papers: int
    core_papers: int
    core_ratio: float
    source_distribution: dict
    top_journals: List[TopJournalItem]
    is_valid: bool
    validation_details: dict
    recommendation: str

    # 多维度分析数据
    year_distribution: dict = None
    main_topic_distribution: dict = None  # 主要主题 (ZYZT|||CYZT)
    topic_distribution: dict = None  # 兼容字段
    subject_distribution: dict = None
    research_level_distribution: dict = None
    funding_distribution: dict = None
    journal_distribution: dict = None  # 期刊分布 (QK)
    institution_distribution: dict = None  # 机构分布 (AFC)
    niche_subjects: List[str] = None  # 细分学科领域
    blue_ocean_topics: List[str] = None  # 蓝海主题

    # 智能分析结果
    trend_analysis: str = None  # 趋势分析
    competition_level: str = None  # 竞争程度
    research_type: str = None  # 研究类型
    interdisciplinary_score: float = 0.0  # 学科交叉评分


@router.post("/validate-cnki", response_model=CNKIValidationResponse)
async def validate_cnki(
    request: CNKIValidationRequest,
    db: Session = Depends(get_db)
):
    """
    通过CNKI验证关键词的学术性

    检查关键词组合在CNKI中的文献数量、核心期刊占比等指标，
    判断是否适合作为研究主题。

    ## 验证标准：
    - **文献数量**：≥300篇（优秀），50-299篇（可用），<50篇（不足）
    - **核心期刊占比**：≥30%（良好），<30%（一般）

    ## 返回数据：
    - total_papers: CNKI检索到的文献总数
    - core_papers: 核心期刊文献数（需要CSSCI数据库）
    - core_ratio: 核心期刊占比
    - source_distribution: 来源类别分布（CSSCI、北大核心等）
    - top_journals: 热门期刊列表
    - is_valid: 是否合格（文献数≥50）
    - recommendation: 优化建议
    """
    try:
        result = await validate_keywords_async(request.keywords, db=db)

        # 转换top_journals格式
        top_journals = []
        for journal in result.top_journals:
            top_journals.append(TopJournalItem(
                name=journal['name'],
                count=journal['count'],
                core_types=journal.get('core_types', [])
            ))

        # 生成建议
        if result.is_valid and result.total_papers >= 300:
            recommendation = "关键词组合学术性优秀，非常适合开展研究。"
        elif result.is_valid:
            recommendation = f"关键词组合学术性可用（{result.total_papers}篇文献）。建议添加限定维度缩小范围。"
        elif result.total_papers < 50:
            recommendation = f"文献总量不足（仅{result.total_papers}篇），建议：1. 考虑更换为更通用的关键词；2. 减少关键词数量，扩大检索范围。"
        else:
            recommendation = "需要进一步优化关键词组合。"

        return CNKIValidationResponse(
            keywords=result.keywords,
            search_query=result.search_query,
            total_papers=result.total_papers,
            core_papers=result.core_papers,
            core_ratio=result.core_ratio,
            source_distribution=result.source_distribution,
            top_journals=top_journals,
            is_valid=result.is_valid,
            validation_details=result.validation_details,
            recommendation=recommendation,
            # 多维度分析数据
            year_distribution=result.year_distribution,
            main_topic_distribution=result.main_topic_distribution,
            topic_distribution=result.topic_distribution,
            subject_distribution=result.subject_distribution,
            research_level_distribution=result.research_level_distribution,
            funding_distribution=result.funding_distribution,
            journal_distribution=result.journal_distribution,
            institution_distribution=result.institution_distribution,
            niche_subjects=result.niche_subjects or [],
            blue_ocean_topics=result.blue_ocean_topics or [],
            # 智能分析结果
            trend_analysis=result.trend_analysis,
            competition_level=result.competition_level,
            research_type=result.research_type,
            interdisciplinary_score=result.interdisciplinary_score
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
