"""优秀论文知识库模块.

通过批量采集CSSCI核心期刊已发表论文，分析其写作规范、引用模式、
语言特征和实证格式，构建质量基准知识库，用于校准AI论文生成质量。

模块组成:
    - journal_list: CSSCI核心期刊列表（财政/经济金融类）
    - paper_harvester: 批量论文采集器（CNKI + NCPSSD搜索）
    - fulltext_downloader: 全文PDF下载器（NCPSSD免费下载）
    - paper_analyzer: 论文分析器（结构/引用/语言/实证特征提取）
    - knowledge_base: 知识库构建器（质量基准/范例库）
"""

from scholarpilot.benchmark.journal_list import CSSCI_JOURNALS, get_journals_by_category
from scholarpilot.benchmark.paper_harvester import PaperHarvester
from scholarpilot.benchmark.fulltext_downloader import FullTextDownloader
from scholarpilot.benchmark.paper_analyzer import PaperAnalyzer, PaperAnalysis
from scholarpilot.benchmark.knowledge_base import KnowledgeBase

__all__ = [
    "CSSCI_JOURNALS",
    "get_journals_by_category",
    "PaperHarvester",
    "FullTextDownloader",
    "PaperAnalyzer",
    "PaperAnalysis",
    "KnowledgeBase",
]
