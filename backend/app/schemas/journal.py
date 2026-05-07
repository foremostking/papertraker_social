"""
期刊相关的Pydantic模式

用于API请求和响应的数据验证
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime


class JournalBase(BaseModel):
    """期刊基础模式"""
    name: str = Field(..., description="期刊名称")
    name_en: Optional[str] = Field(None, description="英文名称")
    issn: Optional[str] = Field(None, description="ISSN")
    cn: Optional[str] = Field(None, description="CN刊号")
    field: Optional[str] = Field(None, description="一级学科")
    subfield: Optional[str] = Field(None, description="二级学科")
    publisher: Optional[str] = Field(None, description="主办单位")


class JournalCreate(JournalBase):
    """创建期刊的模式"""
    is_cssci: bool = False
    is_cssci_expansion: bool = False
    is_beida_core: bool = False
    cssci_year: Optional[int] = None
    cnki_source_id: Optional[str] = None
    cnki_url: Optional[str] = None
    official_url: Optional[str] = None
    email: Optional[str] = None


class JournalUpdate(BaseModel):
    """更新期刊的模式"""
    name: Optional[str] = None
    name_en: Optional[str] = None
    issn: Optional[str] = None
    cn: Optional[str] = None
    field: Optional[str] = None
    subfield: Optional[str] = None
    publisher: Optional[str] = None
    official_url: Optional[str] = None
    email: Optional[str] = None
    impact_factor: Optional[float] = None
    framework_analyzed: Optional[bool] = None


class JournalResponse(JournalBase):
    """期刊响应模式"""
    id: int
    is_cssci: bool = True
    is_cssci_expansion: Optional[bool] = Field(default=None)
    is_beida_core: Optional[bool] = Field(default=None)
    cssci_year: Optional[int] = Field(default=None)
    cnki_source_id: Optional[str] = Field(default=None)
    cnki_url: Optional[str] = Field(default=None)
    journal_code: Optional[str] = Field(default=None, description="CNKI期刊代码")
    official_url: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    framework_analyzed: Optional[bool] = Field(default=None)
    total_papers: Optional[int] = Field(default=None)
    last_paper_date: Optional[datetime] = Field(default=None)
    impact_factor: Optional[float] = Field(default=None)
    composite_impact_factor: Optional[float] = Field(default=None)
    comprehensive_impact_factor: Optional[float] = Field(default=None)
    publisher: Optional[str] = Field(default=None)
    is_network_first: Optional[bool] = Field(default=None)
    is_enhanced_publishing: Optional[bool] = Field(default=None)
    source: Optional[str] = Field(default=None)
    detail_url: Optional[str] = Field(default=None)
    created_at: datetime
    updated_at: datetime

    # CNKI 详情扩展字段
    publishing_cycle: Optional[str] = Field(default=None, description="出版周期")
    publishing_location: Optional[str] = Field(default=None, description="出版地")
    language: Optional[str] = Field(default=None, description="语种")
    format: Optional[str] = Field(default=None, description="开本")
    postal_code: Optional[str] = Field(default=None, description="邮发代号")
    founded_year: Optional[int] = Field(default=None, description="创刊时间")
    total_documents: Optional[int] = Field(default=None, description="出版文献量")
    total_downloads: Optional[int] = Field(default=None, description="总下载次数")
    total_citations: Optional[int] = Field(default=None, description="总被引次数")
    journal_tags: Optional[List[str]] = Field(default=None, description="期刊标签")
    journal_columns: Optional[List[str]] = Field(default=None, description="期刊固定栏目名称")
    journal_columns_detail: Optional[List[Dict[str, str]]] = Field(default=None, description="期刊栏目完整数据")
    cnki_detail_last_updated: Optional[datetime] = Field(default=None, description="CNKI详情最后更新时间")

    class Config:
        from_attributes = True


class JournalListResponse(BaseModel):
    """期刊列表响应模式"""
    total: int
    journals: List[JournalResponse]


class JournalFrameworkBase(BaseModel):
    """期刊框架基础模式"""
    pattern_name: Optional[str] = None
    framework_structure: dict
    frequency: int
    percentage: float
    avg_chapters: Optional[int] = None


class JournalFrameworkResponse(JournalFrameworkBase):
    """期刊框架响应模式"""
    id: int
    journal_id: int
    sample_paper_ids: Optional[List[int]] = None
    last_updated: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class JournalStats(BaseModel):
    """期刊统计信息"""
    total_journals: int
    cssci_journals: int
    cssci_expansion_journals: int
    beida_core_journals: int
    journals_with_frameworks: int
    by_field: dict
