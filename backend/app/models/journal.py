"""
期刊数据模型

定义期刊相关的数据库表结构
"""

from datetime import date
from sqlalchemy import (
    Column, Integer, String, Boolean, Integer as SQLInteger,
    DECIMAL, DateTime, Date, ForeignKey, Text, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from app.core.database import Base


class Journal(Base):
    """
    期刊表

    存储所有期刊的基本信息，包括CSSCI、北大核心等
    """
    __tablename__ = 'journals'

    # 主键
    id = Column(Integer, primary_key=True, index=True)

    # 基本信息
    name = Column(String(200), unique=True, nullable=False, index=True)
    name_en = Column(String(200))
    issn = Column(String(50))
    cn = Column(String(50))

    # 期刊级别 - 中文核心
    is_cssci = Column(Boolean, default=False, index=True)
    is_cssci_expansion = Column(Boolean, default=False, index=True)  # CSSCI扩展版
    is_beida_core = Column(Boolean, default=False, index=True)  # 北大核心
    is_ami = Column(Boolean, default=False, index=True)  # AMI（人文社科期刊AMI评价）
    is_cscd = Column(Boolean, default=False, index=True)  # CSCD（中国科学引文数据库）
    cssci_year = Column(Integer)

    # 期刊级别 - 国际核心
    is_sci = Column(Boolean, default=False, index=True)  # SCI（科学引文索引）
    is_ei = Column(Boolean, default=False, index=True)  # EI（工程索引）
    is_cas = Column(Boolean, default=False, index=True)  # CAS（化学文摘）
    is_inspec = Column(Boolean, default=False, index=True)  # INSPEC（科学文摘）
    is_jst = Column(Boolean, default=False, index=True)  # JST（日本科学技术振兴机构数据库）
    is_paj = Column(Boolean, default=False, index=True)  # Pж(AJ)（文摘杂志）
    is_wjci = Column(Boolean, default=False, index=True)  # WJCI（科技期刊世界影响力指数）

    # 学科分类
    field = Column(String(50), index=True)  # 一级学科：经济学/管理学/法学等
    subfield = Column(String(100))  # 二级学科

    # CNKI映射
    cnki_source_id = Column(String(100))
    cnki_url = Column(String(500))
    journal_code = Column(String(50))  # CNKI期刊代码（用于获取栏目等API）

    # 联系方式
    official_url = Column(String(500))
    email = Column(String(200))

    # 框架分析状态
    framework_analyzed = Column(Boolean, default=False)
    total_papers = Column(Integer, default=0)
    last_paper_date = Column(Date)

    # 元数据
    impact_factor = Column(DECIMAL(5, 2))  # 兼容旧数据
    composite_impact_factor = Column(DECIMAL(10, 3))  # 复合影响因子
    comprehensive_impact_factor = Column(DECIMAL(10, 3))  # 综合影响因子
    publisher = Column(String(200))

    # 出版模式标识
    is_network_first = Column(Boolean, default=False)  # 网络首发
    is_enhanced_publishing = Column(Boolean, default=False)  # 增强出版

    # 来源信息
    source = Column(String(50))  # 数据来源：CNKI等
    detail_url = Column(String(500))  # 详情页URL

    # 时间戳
    created_at = Column(DateTime, server_default='NOW()')
    updated_at = Column(DateTime, server_default='NOW()', onupdate='NOW()')

    # CNKI 详情页扩展字段
    publishing_cycle = Column(String(50))  # 出版周期
    publishing_location = Column(String(200))  # 出版地
    language = Column(String(50))  # 语种
    format = Column(String(50))  # 开本
    postal_code = Column(String(50))  # 邮发代号
    founded_year = Column(Integer)  # 创刊时间
    total_documents = Column(Integer)  # 出版文献量
    total_downloads = Column(Integer)  # 总下载次数
    total_citations = Column(Integer)  # 总被引次数
    journal_tags = Column(ARRAY(String))  # 期刊标签
    journal_columns = Column(ARRAY(String))  # 期刊固定栏目名称：如["理论研究", "实证研究"]
    journal_columns_detail = Column(JSONB)  # 期刊栏目完整数据：[{param, title, value}, ...]
    cnki_detail_last_updated = Column(DateTime)  # CNKI详情最后更新时间

    # 关系
    frameworks = relationship("JournalFramework", back_populates="journal")
    paper_structures = relationship("PaperStructure", back_populates="journal")

    # 索引
    __table_args__ = (
        Index('ix_journals_field_cssci', 'field', 'is_cssci'),
    )

    def __repr__(self):
        return f"<Journal(id={self.id}, name='{self.name}', field='{self.field}')>"


class JournalFramework(Base):
    """
    期刊框架模式表

    存储期刊的常见论文框架模式
    """
    __tablename__ = 'journal_frameworks'

    # 主键
    id = Column(Integer, primary_key=True, index=True)

    # 关联期刊
    journal_id = Column(Integer, ForeignKey('journals.id'), nullable=False)

    # 模式信息
    pattern_name = Column(String(200))  # AI生成的模式名称
    framework_structure = Column(JSONB)  # 框架结构（章节列表）
    frequency = Column(Integer)  # 该模式出现的次数
    percentage = Column(DECIMAL(5, 2))  # 占比
    avg_chapters = Column(Integer)  # 平均章节数

    # 示例论文
    sample_paper_ids = Column(ARRAY(Integer))  # 使用该模式的论文ID示例

    # 时间戳
    last_updated = Column(DateTime, server_default='NOW()', onupdate='NOW()')
    created_at = Column(DateTime, server_default='NOW()')

    # 关系
    journal = relationship("Journal", back_populates="frameworks")
    paper_structures = relationship("PaperStructure", back_populates="framework")

    def __repr__(self):
        return f"<JournalFramework(id={self.id}, pattern_name='{self.pattern_name}')>"


class PaperStructure(Base):
    """
    论文实际结构表

    存储每篇论文的实际章节结构
    """
    __tablename__ = 'paper_structures'

    # 主键
    id = Column(Integer, primary_key=True, index=True)

    # 关联
    literature_id = Column(Integer, ForeignKey('literature.id'))
    journal_id = Column(Integer, ForeignKey('journals.id'))
    framework_id = Column(Integer, ForeignKey('journal_frameworks.id'))

    # 结构信息
    structure = Column(JSONB)  # 该论文的实际章节结构
    chapter_count = Column(Integer)
    word_counts = Column(JSONB)  # 各章节字数统计

    # 时间戳
    extracted_at = Column(DateTime, server_default='NOW()')

    # 关系
    literature = relationship("Literature", back_populates="paper_structures")
    journal = relationship("Journal", back_populates="paper_structures")
    framework = relationship("JournalFramework", back_populates="paper_structures")

    def __repr__(self):
        return f"<PaperStructure(id={self.id}, journal_id={self.journal_id})>"


class Literature(Base):
    """
    文献表

    存储论文的基本信息
    """
    __tablename__ = 'literature'

    # 主键
    id = Column(Integer, primary_key=True, index=True)

    # 基本信息
    title = Column(String(500), nullable=False)
    authors = Column(String(500))
    journal_id = Column(Integer, ForeignKey('journals.id'))
    journal_name = Column(String(200))
    year = Column(Integer)
    source = Column(String(50))

    # CNKI 扩展字段（用于论文获取和去重）
    detail_url = Column(String(500), index=True)  # CNKI详情页URL
    year_issue = Column(String(20))  # 年/期格式，如 "2024/05"
    download_count = Column(Integer, default=0)  # 下载次数
    column_name = Column(String(200))  # 来源栏目追溯
    cnki_id = Column(String(100), unique=True)  # CNKI唯一标识（用于去重）

    # 摘要和关键词
    abstract = Column(Text)
    keywords = Column(String(500))

    # 引用信息
    citation_count = Column(Integer)
    is_cssci = Column(Boolean)

    # PDF存储
    pdf_path = Column(String(500))

    # 笔记
    notes = Column(Text)

    # 时间戳
    created_at = Column(DateTime, server_default='NOW()')
    updated_at = Column(DateTime, server_default='NOW()', onupdate='NOW()')

    # 关系
    paper_structures = relationship("PaperStructure", back_populates="literature")

    def __repr__(self):
        return f"<Literature(id={self.id}, title='{self.title[:50]}...')>"
