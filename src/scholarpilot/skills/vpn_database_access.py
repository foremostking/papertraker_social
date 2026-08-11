"""VPN数据库统一访问层 — 分类标注 + 自动选择 + 编程访问.

提供三层能力：
1. **数据库分类注册表**：74个数据库按研究用途分类标注
   - policy_research（政策调研）：CEI/DRCnet/Pkulaw/皮书/一带一路
   - literature_retrieval（文献检索）：CNKI/万方/WoS/ScienceDirect/Springer/...
   - empirical_data（实证数据）：CSMAR/RESSET/EPS/CNRDS/...
   - general_reference（综合参考）：超星/读秀/案例库/...
2. **DatabaseSelector 自动选择**：根据研究主题和方法论推荐数据库组合
3. **编程访问接口**：VPN URL重写、EPS API、英文文献搜索

注意：VPN URL重写格式为 {域名点改短横}-s.vpn.lzufe.edu.cn:8118/
例如: www.sciencedirect.com → www-sciencedirect-com-s.vpn.lzufe.edu.cn:8118

Usage:
    from scholarpilot.skills.vpn_database_access import (
        VpnDatabaseAccess, DatabaseSelector, build_vpn_url, DATABASES
    )

    # 1. 按研究主题推荐数据库
    selector = DatabaseSelector()
    plan = selector.recommend("地方政府债务风险", methodology="panel_data")
    # -> {"policy_research": [...], "literature_retrieval": [...], "empirical_data": [...]}

    # 2. 按研究阶段获取数据库
    policy_dbs = selector.get_by_stage("policy_research")

    # 3. 通过VPN搜索英文文献
    async with VpnDatabaseAccess() as vda:
        results = await vda.search_english_literature("machine learning")
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, quote

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "DatabaseConfig",
    "DatabaseSelector",
    "VpnDatabaseAccess",
    "build_vpn_url",
    "DATABASES",
    "VPN_HOST_TEMPLATE",
    "RESEARCH_CATEGORIES",
]

VPN_HOST_TEMPLATE = "{domain}-s.vpn.lzufe.edu.cn:8118"

# ===== 研究分类常量 =====

RESEARCH_CATEGORIES = {
    "policy_research": "政策调研",
    "literature_retrieval": "文献检索",
    "empirical_data": "实证数据",
    "general_reference": "综合参考",
}

# 研究子分类
RESEARCH_SUBCATEGORIES = {
    # 政策调研
    "policy_text": "政策文本（法规/通知/意见原文）",
    "policy_practice": "政策实践（实施案例/试点报道）",
    "policy_analysis": "政策分析（解读/评估/智库报告）",
    # 文献检索
    "chinese_journal": "中文期刊",
    "english_journal": "外文期刊",
    "thesis": "学位论文",
    "preprint": "预印本/OA文献",
    "newspaper": "报刊资料",
    # 实证数据
    "microenterprise": "微观企业数据",
    "macro_economy": "宏观经济数据",
    "financial_market": "金融市场数据",
    "regional_data": "区域/特色数据",
    "public_data": "公共免费数据",
    # 综合参考
    "ebook": "电子图书",
    "case_study": "教学案例",
    "video_lecture": "视频讲座",
    "general_search": "综合搜索",
}


def build_vpn_url(original_url: str) -> str:
    """将原始数据库URL转换为VPN代理URL.

    示例:
        https://www.sciencedirect.com/search?query=AI
        → http://www-sciencedirect-com-s.vpn.lzufe.edu.cn:8118/search?query=AI

    Args:
        original_url: 原始数据库URL（含http/https协议）.

    Returns:
        VPN代理URL。若无法解析原始URL，则原样返回.
    """
    match = re.match(r'https?://([^/]+)(/.*)?', original_url)
    if not match:
        return original_url
    domain = match.group(1)
    path = match.group(2) or ""
    # 域名中的点改为短横
    vpn_domain = domain.replace(".", "-")
    vpn_host = VPN_HOST_TEMPLATE.format(domain=vpn_domain)
    return f"http://{vpn_host}{path}"


@dataclass
class DatabaseConfig:
    """数据库访问配置与分类标注.

    Attributes:
        key: 数据库唯一标识.
        name: 数据库中文名称.
        platform: 平台标识（大写英文）.
        original_url: 原始URL.
        vpn_url: VPN代理URL.
        access_method: 访问方式 ("vpn_url_rewrite"|"eps_api"|"browser"|"direct"|"free_api"|"rag_index").
        api_base: API基础URL（如有）.
        search_url_template: URL搜索模板，{keyword}占位.
        research_category: 研究大类 ("policy_research"|"literature_retrieval"|"empirical_data"|"general_reference").
        research_subcategory: 研究子类（见 RESEARCH_SUBCATEGORIES）.
        content_description: 内容描述（一句话说明数据库包含什么）.
        strengths: 数据库优势领域列表.
        integration_status: 集成状态 ("integrated"|"configured"|"not_integrated").
        language: 主要语言 ("zh"|"en"|"mixed").
        is_free: 是否免费（True=免费/False=需VPN或付费）.
    """

    key: str
    name: str
    platform: str
    original_url: str
    vpn_url: str
    access_method: str  # "vpn_url_rewrite" | "eps_api" | "browser" | "direct" | "free_api" | "rag_index"
    api_base: str = ""
    search_url_template: str = ""
    # ===== 分类标注字段（新增，带默认值确保向后兼容）=====
    research_category: str = ""  # "policy_research" | "literature_retrieval" | "empirical_data" | "general_reference"
    research_subcategory: str = ""  # 见 RESEARCH_SUBCATEGORIES
    content_description: str = ""
    strengths: list[str] = field(default_factory=list)
    integration_status: str = "not_integrated"  # "integrated" | "configured" | "not_integrated"
    language: str = "zh"  # "zh" | "en" | "mixed"
    is_free: bool = False

    @property
    def vpn_domain(self) -> str:
        """从vpn_url中提取VPN域名（含端口）.

        例如: http://www-sciencedirect-com-s.vpn.lzufe.edu.cn:8118/
        → www-sciencedirect-com-s.vpn.lzufe.edu.cn:8118
        """
        parsed = urlparse(self.vpn_url)
        host = parsed.netloc or parsed.path.split("/")[0]
        return host

    @property
    def is_accessible(self) -> bool:
        """数据库是否已集成可自动访问."""
        return self.integration_status == "integrated"


# ===== 预配置的数据库注册表 =====
# 涵盖兰州财经大学图书馆74个数据库中与研究直接相关的约50个
# 按研究大类组织：政策调研 → 文献检索 → 实证数据 → 综合参考

DATABASES: dict[str, DatabaseConfig] = {

    # ═══════════════════════════════════════════════════════════════
    # 一、政策调研类（policy_research）
    # ═══════════════════════════════════════════════════════════════

    # --- 政策文本（法规原文）---

    "pkulaw": DatabaseConfig(
        key="pkulaw",
        name="北大法宝",
        platform="PKULAW",
        original_url="https://www.pkulaw.com/",
        vpn_url=build_vpn_url("https://www.pkulaw.com/"),
        access_method="vpn_url_rewrite",
        search_url_template="/law/chl?Keywords={keyword}&SearchKeywordType=Title&MatchType=Fuzzy",
        research_category="policy_research",
        research_subcategory="policy_text",
        content_description="法律法规专门库，含法律条文、规范性文件、司法案例",
        strengths=["法律法规原文", "规范性文件", "司法案例", "法律条文检索"],
        integration_status="integrated",
        language="zh",
    ),

    # --- 政策实践（实施案例/新闻动态）---

    "cei": DatabaseConfig(
        key="cei",
        name="中国经济信息网",
        platform="CEI",
        original_url="https://www.cei.cn/",
        vpn_url="https://www.cei.cn/",  # 直连，无需VPN
        access_method="direct",
        research_category="policy_research",
        research_subcategory="policy_practice",
        content_description="宏观/金融/行业/区域频道政策动态，支持关键词+栏目+排序+时间范围筛选",
        strengths=["政策落地报道", "试点新闻", "经济动态", "多维度筛选", "宏观/金融/行业/区域频道"],
        integration_status="integrated",
        language="zh",
        is_free=True,
    ),

    # --- 政策分析（解读/评估/智库报告）---

    "drcnet": DatabaseConfig(
        key="drcnet",
        name="国务院发展研究中心数据库",
        platform="DRCNET",
        original_url="https://edu.drcnet.com.cn/",
        vpn_url=build_vpn_url("https://edu.drcnet.com.cn/"),
        access_method="vpn_url_rewrite",
        search_url_template="/search/searchAC.aspx?fields={keyword}",
        research_category="policy_research",
        research_subcategory="policy_analysis",
        content_description="国务院智库研究报告、政策评估、形势分析",
        strengths=["智库报告", "政策评估", "宏观经济形势分析", "国务院权威解读"],
        integration_status="integrated",
        language="zh",
    ),

    "ydyl_drc": DatabaseConfig(
        key="ydyl_drc",
        name="一带一路研究与决策支撑平台",
        platform="YDYL",
        original_url="https://ydyl.drcnet.com.cn/",
        vpn_url=build_vpn_url("https://ydyl.drcnet.com.cn/"),
        access_method="vpn_url_rewrite",
        search_url_template="/search?keyword={keyword}",
        research_category="policy_research",
        research_subcategory="policy_analysis",
        content_description="一带一路政策研究、区域合作、沿线国家分析",
        strengths=["一带一路专题", "区域合作研究", "沿线国家数据"],
        integration_status="integrated",
        language="zh",
    ),

    "pishu": DatabaseConfig(
        key="pishu",
        name="皮书数据库",
        platform="PISHU",
        original_url="https://www.pishu.com.cn/",
        vpn_url=build_vpn_url("https://www.pishu.com.cn/"),
        access_method="vpn_url_rewrite",
        search_url_template="/search?keyword={keyword}",
        research_category="policy_research",
        research_subcategory="policy_analysis",
        content_description="社科院皮书系列，含经济蓝皮书、社会蓝皮书等年度行业/区域发展报告",
        strengths=["社科院权威报告", "年度行业发展分析", "区域发展报告", "经济蓝皮书"],
        integration_status="integrated",
        language="zh",
    ),

    # ═══════════════════════════════════════════════════════════════
    # 二、文献检索类（literature_retrieval）
    # ═══════════════════════════════════════════════════════════════

    # --- 中文期刊 ---

    "cnki": DatabaseConfig(
        key="cnki",
        name="中国知网CNKI系列数据库",
        platform="CNKI",
        original_url="https://www.cnki.net/",
        vpn_url=build_vpn_url("https://kns.cnki.net/"),
        access_method="vpn_url_rewrite",
        search_url_template="/kns8s/AdvSearch",
        research_category="literature_retrieval",
        research_subcategory="chinese_journal",
        content_description="最全面的中文期刊/学位论文/会议论文/报纸数据库",
        strengths=["中文期刊全文", "学位论文", "会议论文", "专业检索", "来源类别筛选(SCI/核心/CSSCI/EI/CSCD)"],
        integration_status="integrated",
        language="zh",
    ),

    "wanfang": DatabaseConfig(
        key="wanfang",
        name="万方数据",
        platform="WANFANG",
        original_url="https://www.wanfangdata.com.cn/",
        vpn_url=build_vpn_url("https://www.wanfangdata.com.cn/"),
        access_method="vpn_url_rewrite",
        research_category="literature_retrieval",
        research_subcategory="chinese_journal",
        content_description="中文期刊论文、学位论文、会议论文",
        strengths=["期刊论文", "学位论文", "会议论文", "核心期刊标签"],
        integration_status="integrated",
        language="zh",
    ),

    "ncpssd": DatabaseConfig(
        key="ncpssd",
        name="国家哲学社会科学文献中心",
        platform="NCPSSD",
        original_url="https://www.ncpssd.cn/",
        vpn_url="https://www.ncpssd.cn/",  # 免费，无需VPN
        access_method="free_api",
        research_category="literature_retrieval",
        research_subcategory="chinese_journal",
        content_description="免费社科期刊全文数据库",
        strengths=["免费全文", "社科期刊", "无需VPN"],
        integration_status="integrated",
        language="zh",
        is_free=True,
    ),

    "chaoxing_journal": DatabaseConfig(
        key="chaoxing_journal",
        name="超星期刊",
        platform="CHAOXING",
        original_url="https://qikan.chaoxing.com/",
        vpn_url=build_vpn_url("https://qikan.chaoxing.com/"),
        access_method="vpn_url_rewrite",
        research_category="literature_retrieval",
        research_subcategory="chinese_journal",
        content_description="约7000种中文期刊全文",
        strengths=["期刊全文", "覆盖面广"],
        search_url_template="/search?sw={keyword}",
        integration_status="integrated",
        language="zh",
    ),

    "rdfybk": DatabaseConfig(
        key="rdfybk",
        name="人大复印报刊资料全文数据库",
        platform="RDFYBK",
        original_url="https://www.rdfybk.com/",
        vpn_url=build_vpn_url("https://www.rdfybk.com/"),
        access_method="vpn_url_rewrite",
        research_category="literature_retrieval",
        research_subcategory="newspaper",
        content_description="精选优质社科论文全文转载，学术引用价值高",
        strengths=["精选优质论文", "全文转载", "社科领域权威精选"],
        search_url_template="/qkw/search?keyword={keyword}",
        integration_status="integrated",
        language="zh",
    ),

    "tws": DatabaseConfig(
        key="tws",
        name="TWS台湾学术期刊在线数据库",
        platform="TWS",
        original_url="https://www.tws.edu.cn/",
        vpn_url=build_vpn_url("https://www.tws.edu.cn/"),
        access_method="browser",
        research_category="literature_retrieval",
        research_subcategory="chinese_journal",
        content_description="台湾地区学术期刊全文",
        strengths=["台湾学术期刊", "地区补充"],
        integration_status="not_integrated",
        language="zh",
    ),

    "weipu": DatabaseConfig(
        key="weipu",
        name="维普经纶知识服务平台",
        platform="WEIPU",
        original_url="https://k.vipslib.com/",
        vpn_url="http://k-vipslib-com-s.vpn.lzufe.edu.cn:8118/",
        access_method="browser",
        search_url_template="/",
        research_category="literature_retrieval",
        research_subcategory="chinese_journal",
        content_description="中文期刊整合检索",
        strengths=["期刊整合检索", "文献传递"],
        integration_status="integrated",
        language="zh",
    ),

    # --- 外文期刊 ---

    "sciencedirect": DatabaseConfig(
        key="sciencedirect",
        name="ScienceDirect (Elsevier)",
        platform="SCIENCEDIRECT",
        original_url="https://www.sciencedirect.com/",
        vpn_url=build_vpn_url("https://www.sciencedirect.com/"),
        access_method="vpn_url_rewrite",
        search_url_template="/search?query={keyword}&show=25",
        research_category="literature_retrieval",
        research_subcategory="english_journal",
        content_description="Elsevier全文期刊，覆盖经济/金融/管理/社科",
        strengths=["全文期刊", "PDF下载", "经济金融类期刊丰富"],
        integration_status="integrated",
        language="en",
    ),

    "springer": DatabaseConfig(
        key="springer",
        name="Springer电子期刊",
        platform="SPRINGER",
        original_url="https://link.springer.com/",
        vpn_url=build_vpn_url("https://link.springer.com/"),
        access_method="vpn_url_rewrite",
        search_url_template="/search?query={keyword}&showAll=false",
        research_category="literature_retrieval",
        research_subcategory="english_journal",
        content_description="Springer全文期刊，覆盖经济学/管理学",
        strengths=["全文期刊", "PDF下载", "经济学期刊"],
        integration_status="integrated",
        language="en",
    ),

    "ebsco": DatabaseConfig(
        key="ebsco",
        name="EBSCO商管财经类数据库",
        platform="EBSCO",
        original_url="https://research.ebsco.com/",
        vpn_url="http://research-ebsco-com-s.vpn.lzufe.edu.cn:8118",
        access_method="browser",
        search_url_template="/c/nb4nnq/search/advanced",
        research_category="literature_retrieval",
        research_subcategory="english_journal",
        content_description="商管财经类期刊全文数据库",
        strengths=["商管期刊", "财经类全文", "Business Source Premier"],
        integration_status="integrated",
        language="en",
    ),

    "emerald": DatabaseConfig(
        key="emerald",
        name="Emerald管理学期刊",
        platform="EMERALD",
        original_url="https://www.emerald.com/",
        vpn_url=build_vpn_url("https://www.emerald.com/"),
        access_method="vpn_url_rewrite",
        search_url_template="/search?q={keyword}",
        research_category="literature_retrieval",
        research_subcategory="english_journal",
        content_description="Emerald管理学全文期刊",
        strengths=["管理学期刊", "全文PDF", "案例研究"],
        integration_status="integrated",
        language="en",
    ),

    "wos": DatabaseConfig(
        key="wos",
        name="Web of Science (SSCI)",
        platform="WOS",
        original_url="https://webofscience.clarivate.cn/",
        vpn_url=build_vpn_url("https://webofscience.clarivate.cn/"),
        access_method="browser",
        research_category="literature_retrieval",
        research_subcategory="english_journal",
        content_description="SSCI引文索引，支持引文检索和影响因子查询",
        strengths=["SSCI引文索引", "影响因子", "引文分析", "高被引论文"],
        integration_status="integrated",
        language="en",
    ),

    "zhiyun": DatabaseConfig(
        key="zhiyun",
        name="智云服务平台-外文文献系统",
        platform="ZHIYUN",
        original_url="http://zcloudlib.com/",
        vpn_url="http://zcloudlib-com.vpn.lzufe.edu.cn:8118/",
        access_method="browser",
        search_url_template="/",
        research_category="literature_retrieval",
        research_subcategory="english_journal",
        content_description="外文文献整合检索平台",
        strengths=["多源整合检索", "外文文献传递"],
        integration_status="integrated",
        language="en",
    ),

    # --- 预印本/OA文献 ---

    "arxiv": DatabaseConfig(
        key="arxiv",
        name="arXiv.org预印本",
        platform="ARXIV",
        original_url="https://arxiv.org/",
        vpn_url="https://arxiv.org/",
        access_method="free_api",
        research_category="literature_retrieval",
        research_subcategory="preprint",
        content_description="物理/数学/CS/经济学预印本论文",
        strengths=["预印本", "免费API", "快速获取最新研究"],
        integration_status="integrated",
        language="en",
        is_free=True,
    ),

    "chinaxiv": DatabaseConfig(
        key="chinaxiv",
        name="ChinaXiv中科院预印本平台",
        platform="CHINAXIV",
        original_url="https://chinaxiv.org/",
        vpn_url="https://chinaxiv.org/",
        access_method="free_api",
        research_category="literature_retrieval",
        research_subcategory="preprint",
        content_description="中文预印本论文",
        strengths=["中文预印本", "免费API", "中科院平台"],
        integration_status="integrated",
        language="zh",
        is_free=True,
    ),

    "openalex": DatabaseConfig(
        key="openalex",
        name="OpenAlex全球学术成果索引",
        platform="OPENALEX",
        original_url="https://openalex.org/",
        vpn_url="https://openalex.org/",
        access_method="free_api",
        research_category="literature_retrieval",
        research_subcategory="preprint",
        content_description="2.4亿+学术成果元数据，免费API",
        strengths=["全球学术成果", "免费API", "元数据丰富", "覆盖面最广"],
        integration_status="integrated",
        language="mixed",
        is_free=True,
    ),

    "semantic_scholar": DatabaseConfig(
        key="semantic_scholar",
        name="Semantic Scholar",
        platform="SS",
        original_url="https://www.semanticscholar.org/",
        vpn_url="https://www.semanticscholar.org/",
        access_method="free_api",
        research_category="literature_retrieval",
        research_subcategory="preprint",
        content_description="AI驱动学术检索，2亿+论文语义检索",
        strengths=["AI语义检索", "免费API", "引文网络分析"],
        integration_status="integrated",
        language="en",
        is_free=True,
    ),

    "pubscholar": DatabaseConfig(
        key="pubscholar",
        name="PubScholar公益学术平台",
        platform="PUBSCHOLAR",
        original_url="https://www.pubscholar.cn/",
        vpn_url="https://www.pubscholar.cn/",
        access_method="free_api",
        research_category="literature_retrieval",
        research_subcategory="preprint",
        content_description="公益OA文献整合检索",
        strengths=["OA文献整合", "免费访问"],
        integration_status="integrated",
        language="mixed",
        is_free=True,
    ),

    # --- 学位论文 ---

    "lzufethesis": DatabaseConfig(
        key="lzufethesis",
        name="兰州财经大学博硕士论文数据库",
        platform="LZUFE",
        original_url="https://library.lzufe.edu.cn/",
        vpn_url=build_vpn_url("https://library.lzufe.edu.cn/"),
        access_method="browser",
        research_category="literature_retrieval",
        research_subcategory="thesis",
        content_description="本校硕博学位论文全文",
        strengths=["本校论文", "学位论文全文"],
        search_url_template="/search?keyword={keyword}",
        integration_status="integrated",
        language="zh",
    ),

    "xinxueshu_thesis": DatabaseConfig(
        key="xinxueshu_thesis",
        name="新学术全球学位论文精选整合平台",
        platform="XINXUESHU",
        original_url="https://www.xinxueshu.com/",
        vpn_url=build_vpn_url("https://www.xinxueshu.com/"),
        access_method="browser",
        research_category="literature_retrieval",
        research_subcategory="thesis",
        content_description="国外名校学位论文精选",
        strengths=["国外学位论文", "精选整合"],
        integration_status="not_integrated",
        language="en",
    ),

    # ═══════════════════════════════════════════════════════════════
    # 三、实证研究数据类（empirical_data）
    # ═══════════════════════════════════════════════════════════════

    # --- 微观企业数据 ---

    "csmar": DatabaseConfig(
        key="csmar",
        name="国泰安CSMAR数据库",
        platform="CSMAR",
        original_url="https://data.csmar.com/",
        vpn_url=build_vpn_url("https://data.csmar.com/"),
        access_method="rag_index",
        api_base="https://data.csmar.com",
        research_category="empirical_data",
        research_subcategory="microenterprise",
        content_description="上市公司财务、股票交易、公司治理、创新专利（1990年至今）",
        strengths=["上市公司财务数据", "股票交易数据", "公司治理", "创新专利", "RAG知识库已覆盖"],
        integration_status="integrated",
        language="zh",
    ),

    "cnrds": DatabaseConfig(
        key="cnrds",
        name="中国研究数据服务平台CNRDS",
        platform="CNRDS",
        original_url="https://www.cnrds.com/",
        vpn_url=build_vpn_url("https://www.cnrds.com/"),
        access_method="browser",
        research_category="empirical_data",
        research_subcategory="microenterprise",
        content_description="文本分析、ESG评级、企业创新、数字化转型指数",
        strengths=["文本分析数据", "ESG评级", "数字化转型指数", "企业创新"],
        search_url_template="/search?keyword={keyword}",
        integration_status="integrated",
        language="zh",
    ),

    "weiguan": DatabaseConfig(
        key="weiguan",
        name="中国微观经济数据查询系统",
        platform="WEIGUAN",
        original_url="https://www.microdata.cn/",
        vpn_url=build_vpn_url("https://www.microdata.cn/"),
        access_method="browser",
        research_category="empirical_data",
        research_subcategory="microenterprise",
        content_description="工业企业调查数据、微观经济数据",
        strengths=["工业企业调查", "微观数据"],
        search_url_template="/search?keyword={keyword}",
        integration_status="integrated",
        language="zh",
    ),

    # --- 宏观经济数据 ---

    "eps": DatabaseConfig(
        key="eps",
        name="EPS全球统计数据/分析平台",
        platform="EPS",
        original_url="https://www.epsnet.com.cn/",
        vpn_url=build_vpn_url("https://www.epsnet.com.cn/"),
        access_method="eps_api",
        api_base="https://www.epsnet.com.cn",
        research_category="empirical_data",
        research_subcategory="macro_economy",
        content_description="宏观/行业/贸易/财政/金融/人口/教育/科技，100+子库，15亿条时间序列",
        strengths=["宏观数据", "行业数据", "财政数据", "API调用(sid认证)", "时间序列丰富"],
        integration_status="integrated",
        language="zh",
    ),

    "cnki_data": DatabaseConfig(
        key="cnki_data",
        name="中国经济社会大数据研究平台",
        platform="CNKI_DATA",
        original_url="https://data.cnki.net/",
        vpn_url=build_vpn_url("https://data.cnki.net/"),
        access_method="rag_index",
        api_base="https://data.cnki.net",
        research_category="empirical_data",
        research_subcategory="macro_economy",
        content_description="CNKI统计数据库，14个专题库（财政/金融/城市/县域/人口普查/科技/能源等）",
        strengths=["14个专题统计库", "财政/金融专题", "县域数据", "RAG知识库已覆盖"],
        integration_status="integrated",
        language="zh",
    ),

    "huanqiu_caijing": DatabaseConfig(
        key="huanqiu_caijing",
        name="环球财经数据平台",
        platform="HUANQIU",
        original_url="http://gf.harborn.cn/",
        vpn_url="http://gf-harborn-cn-s.vpn.lzufe.edu.cn:8118/index",
        access_method="browser",
        research_category="empirical_data",
        research_subcategory="macro_economy",
        content_description="全球宏观经济/金融数据",
        strengths=["全球宏观数据", "国际比较数据"],
        search_url_template="/",
        integration_status="integrated",
        language="mixed",
    ),

    # --- 金融市场数据 ---

    "resset": DatabaseConfig(
        key="resset",
        name="锐思RESSET金融研究数据库",
        platform="RESSET",
        original_url="https://db.resset.com/",
        vpn_url=build_vpn_url("https://db.resset.com/"),
        access_method="rag_index",
        api_base="https://db.resset.com",
        research_category="empirical_data",
        research_subcategory="financial_market",
        content_description="金融研究数据库（宏观/股票/债券/基金/期货/外汇/行业）",
        strengths=["金融研究", "债券数据", "基金数据", "期货/外汇", "RAG知识库已覆盖"],
        integration_status="integrated",
        language="zh",
    ),

    # --- 区域/特色数据 ---

    "quyu_yanjiu": DatabaseConfig(
        key="quyu_yanjiu",
        name="中国区域研究数据支撑平台",
        platform="QUYU",
        original_url="https://cnrrd.sozdata.com/",
        vpn_url="http://cnrrd-sozdata-com-s.vpn.lzufe.edu.cn:8118",
        access_method="browser",
        search_url_template="/#/home",
        research_category="empirical_data",
        research_subcategory="regional_data",
        content_description="省/市/县区域发展指标",
        strengths=["区域经济数据", "省/市/县数据", "区域发展指标"],
        integration_status="integrated",
        language="zh",
    ),

    "huanghe": DatabaseConfig(
        key="huanghe",
        name="黄河流域发展数据库",
        platform="HUANGHE",
        original_url="https://yrb.harborn.cn/",
        vpn_url="http://yrb-harborn-cn-s.vpn.lzufe.edu.cn:8118/index",
        access_method="browser",
        search_url_template="/",
        research_category="empirical_data",
        research_subcategory="regional_data",
        content_description="黄河流域经济社会数据",
        strengths=["黄河流域专题", "区域生态数据"],
        integration_status="integrated",
        language="zh",
    ),

    "ydyl_database": DatabaseConfig(
        key="ydyl_database",
        name="一带一路数据库",
        platform="YDYL_DB",
        original_url="https://www.ydylcn.com/",
        vpn_url="http://www-ydylcn-com-s.vpn.lzufe.edu.cn:8118/skwx_ydyl/sublibrary?SiteID=1&ID=8721",
        access_method="direct",
        research_category="empirical_data",
        research_subcategory="regional_data",
        content_description="一带一路沿线国家经济/贸易/投资数据",
        strengths=["沿线国家数据", "国际贸易", "投资数据"],
        search_url_template="/?keyword={keyword}",
        integration_status="integrated",
        language="zh",
    ),

    # --- 公共免费数据 ---

    "nbs": DatabaseConfig(
        key="nbs",
        name="国家统计局",
        platform="NBS",
        original_url="https://www.stats.gov.cn/",
        vpn_url="https://www.stats.gov.cn/",
        access_method="direct",
        research_category="empirical_data",
        research_subcategory="public_data",
        content_description="省级宏观经济、人口、就业免费数据",
        strengths=["省级宏观数据", "人口数据", "就业数据", "免费访问"],
        integration_status="integrated",
        language="zh",
        is_free=True,
    ),

    "mof": DatabaseConfig(
        key="mof",
        name="财政部",
        platform="MOF",
        original_url="http://www.mof.gov.cn/",
        vpn_url="http://www.mof.gov.cn/",
        access_method="direct",
        research_category="empirical_data",
        research_subcategory="public_data",
        content_description="财政收支、地方政府债务免费数据",
        strengths=["财政收支", "地方债务", "预算决算", "免费访问"],
        integration_status="integrated",
        language="zh",
        is_free=True,
    ),

    # ═══════════════════════════════════════════════════════════════
    # 四、综合参考类（general_reference）
    # ═══════════════════════════════════════════════════════════════

    "chaoxing_book": DatabaseConfig(
        key="chaoxing_book",
        name="超星电子图书",
        platform="CHAOXING_BOOK",
        original_url="https://www.sslibrary.com/",
        vpn_url=build_vpn_url("https://www.sslibrary.com/"),
        access_method="browser",
        research_category="general_reference",
        research_subcategory="ebook",
        content_description="电子图书",
        strengths=["电子书", "图书全文"],
        search_url_template="/book/search?keyword={keyword}",
        integration_status="integrated",
        language="zh",
    ),

    "duxiu": DatabaseConfig(
        key="duxiu",
        name="读秀学术搜索",
        platform="DUXIU",
        original_url="https://www.duxiu.com/",
        vpn_url=build_vpn_url("https://www.duxiu.com/"),
        access_method="browser",
        research_category="general_reference",
        research_subcategory="general_search",
        content_description="综合学术搜索平台",
        strengths=["综合搜索", "图书/期刊/报纸整合"],
        integration_status="not_integrated",
        language="zh",
    ),

    "anli": DatabaseConfig(
        key="anli",
        name="全球案例发现系统",
        platform="ANLI",
        original_url="https://www.htcases.com/",
        vpn_url="http://www-htcases-com-s.vpn.lzufe.edu.cn:8118/index.html",
        access_method="browser",
        search_url_template="/",
        research_category="general_reference",
        research_subcategory="case_study",
        content_description="教学案例库",
        strengths=["商业案例", "教学案例"],
        integration_status="integrated",
        language="zh",
    ),

    "baogaoting": DatabaseConfig(
        key="baogaoting",
        name="爱迪科森网上报告厅",
        platform="BAOGAOTING",
        original_url="https://zyk.bjadks.com/",
        vpn_url="http://zyk-bjadks-com-s.vpn.lzufe.edu.cn:8118/",
        access_method="browser",
        search_url_template="/",
        research_category="general_reference",
        research_subcategory="video_lecture",
        content_description="学术视频讲座",
        strengths=["学术讲座视频", "专家报告"],
        integration_status="integrated",
        language="zh",
    ),
}


class DatabaseSelector:
    """数据库智能选择器 — 根据研究主题和方法论推荐数据库组合.

    根据论文的研究主题、方法论和研究阶段，从DATABASES注册表中
    智能推荐最相关的数据库，帮助系统在每个研究阶段选择最佳数据源。

    Usage::
        selector = DatabaseSelector()

        # 按研究主题推荐全流程数据库组合
        plan = selector.recommend("地方政府债务风险", methodology="panel_data")
        # -> {
        #     "policy_research": [DatabaseConfig, ...],
        #     "literature_retrieval": [DatabaseConfig, ...],
        #     "empirical_data": [DatabaseConfig, ...],
        # }

        # 按研究阶段获取数据库
        policy_dbs = selector.get_by_stage("policy_research")

        # 按子分类获取数据库
        macro_dbs = selector.get_by_subcategory("macro_economy")
    """

    # 研究主题关键词到数据库子分类的映射
    TOPIC_TO_SUBCATEGORY: dict[str, list[str]] = {
        # 财政/税收类
        "财政": ["macro_economy", "public_data", "policy_text", "policy_analysis"],
        "税收": ["macro_economy", "public_data", "policy_text"],
        "预算": ["macro_economy", "public_data", "policy_text"],
        "债务": ["macro_economy", "financial_market", "public_data", "policy_analysis"],
        "专项债": ["macro_economy", "financial_market", "policy_practice"],
        "地方政府债务": ["macro_economy", "financial_market", "public_data", "policy_text", "policy_analysis"],
        # 金融/货币类
        "货币": ["macro_economy", "financial_market", "policy_analysis"],
        "利率": ["financial_market", "macro_economy"],
        "汇率": ["financial_market", "macro_economy"],
        "银行": ["financial_market", "microenterprise", "policy_analysis"],
        "股票": ["financial_market", "microenterprise"],
        "债券": ["financial_market", "macro_economy"],
        "基金": ["financial_market"],
        "金融风险": ["financial_market", "macro_economy", "policy_analysis"],
        # 企业/公司类
        "企业": ["microenterprise", "chinese_journal", "english_journal"],
        "上市公司": ["microenterprise", "financial_market"],
        "公司治理": ["microenterprise", "chinese_journal", "english_journal"],
        "创新": ["microenterprise", "chinese_journal", "english_journal"],
        "研发": ["microenterprise", "chinese_journal"],
        "ESG": ["microenterprise"],
        "数字化转型": ["microenterprise", "chinese_journal"],
        # 宏观经济类
        "GDP": ["macro_economy", "public_data"],
        "经济增长": ["macro_economy", "public_data", "policy_analysis"],
        "通货膨胀": ["macro_economy", "public_data"],
        "就业": ["macro_economy", "public_data"],
        "消费": ["macro_economy", "public_data"],
        "投资": ["macro_economy", "financial_market", "microenterprise"],
        # 区域经济类
        "区域": ["regional_data", "macro_economy", "policy_practice"],
        "省份": ["regional_data", "macro_economy", "public_data"],
        "城市": ["regional_data", "macro_economy"],
        "县域": ["regional_data", "macro_economy"],
        "黄河": ["regional_data"],
        "一带一路": ["regional_data", "policy_analysis"],
        # 国际贸易类
        "贸易": ["macro_economy", "regional_data"],
        "出口": ["macro_economy"],
        "进口": ["macro_economy"],
        "外商投资": ["macro_economy", "microenterprise"],
    }

    # 方法论到数据库子分类的映射
    METHODOLOGY_TO_SUBCATEGORY: dict[str, list[str]] = {
        "panel_data": ["macro_economy", "regional_data", "microenterprise"],
        "time_series": ["macro_economy", "financial_market"],
        "cross_section": ["microenterprise", "macro_economy"],
        "did": ["microenterprise", "regional_data", "policy_practice"],
        "rd": ["microenterprise", "regional_data"],
        "iv": ["macro_economy", "microenterprise"],
        "event_study": ["financial_market", "microenterprise"],
        "text_analysis": ["microenterprise", "chinese_journal", "english_journal"],
        "case_study": ["case_study", "policy_practice"],
    }

    # 研究阶段到数据库大类的映射
    STAGE_TO_CATEGORY: dict[str, list[str]] = {
        "policy_research": ["policy_research"],
        "literature_retrieval": ["literature_retrieval"],
        "empirical_data": ["empirical_data"],
        "spec_design": ["empirical_data", "policy_research"],
        "full_workflow": ["policy_research", "literature_retrieval", "empirical_data"],
    }

    def __init__(self) -> None:
        self._databases = DATABASES

    def get_by_category(self, category: str) -> list[DatabaseConfig]:
        """按研究大类获取数据库列表.

        Args:
            category: 研究大类 ("policy_research"|"literature_retrieval"|"empirical_data"|"general_reference").

        Returns:
            该分类下所有数据库列表，按集成状态排序（已集成优先）.
        """
        dbs = [db for db in self._databases.values() if db.research_category == category]
        # 已集成的排前面
        return sorted(dbs, key=lambda d: (d.integration_status != "integrated", d.name))

    def get_by_subcategory(self, subcategory: str) -> list[DatabaseConfig]:
        """按研究子分类获取数据库列表.

        Args:
            subcategory: 研究子分类（见 RESEARCH_SUBCATEGORIES）.

        Returns:
            该子分类下所有数据库列表.
        """
        return [
            db for db in self._databases.values()
            if db.research_subcategory == subcategory
        ]

    def get_by_stage(self, stage: str) -> list[DatabaseConfig]:
        """按研究阶段获取推荐数据库.

        Args:
            stage: 研究阶段 ("policy_research"|"literature_retrieval"|"empirical_data"|"spec_design"|"full_workflow").

        Returns:
            该阶段推荐的数据库列表.
        """
        categories = self.STAGE_TO_CATEGORY.get(stage, [])
        result: list[DatabaseConfig] = []
        seen_keys: set[str] = set()
        for cat in categories:
            for db in self.get_by_category(cat):
                if db.key not in seen_keys:
                    seen_keys.add(db.key)
                    result.append(db)
        return result

    def get_integrated(self, category: str | None = None) -> list[DatabaseConfig]:
        """获取已集成的数据库列表.

        Args:
            category: 可选，按研究大类过滤.

        Returns:
            已集成（integration_status=="integrated"）的数据库列表.
        """
        result = [
            db for db in self._databases.values()
            if db.integration_status == "integrated"
        ]
        if category:
            result = [db for db in result if db.research_category == category]
        return result

    def _match_subcategories(self, topic: str) -> list[str]:
        """根据研究主题匹配数据库子分类.

        Args:
            topic: 研究主题（中文关键词）.

        Returns:
            匹配的子分类列表，按匹配优先级排序.
        """
        matched: list[str] = []
        for keyword, subcats in self.TOPIC_TO_SUBCATEGORY.items():
            if keyword in topic:
                for sc in subcats:
                    if sc not in matched:
                        matched.append(sc)
        return matched

    def recommend(
        self,
        topic: str,
        methodology: str = "",
        stage: str = "full_workflow",
    ) -> dict[str, list[DatabaseConfig]]:
        """根据研究主题和方法论推荐数据库组合.

        核心推荐逻辑：
        1. 从主题中提取关键词，匹配到数据库子分类
        2. 从方法论中匹配到数据库子分类
        3. 合并子分类，按研究大类分组
        4. 每个大类内按集成状态排序（已集成优先）
        5. 如果主题无匹配，返回该大类下所有已集成数据库

        Args:
            topic: 研究主题（如"地方政府债务风险"）.
            methodology: 研究方法论（如"panel_data"|"did"|"time_series"）.
            stage: 研究阶段 ("policy_research"|"literature_retrieval"|"empirical_data"|"spec_design"|"full_workflow").

        Returns:
            按研究大类分组的数据库推荐字典:
            {
                "policy_research": [DatabaseConfig, ...],
                "literature_retrieval": [DatabaseConfig, ...],
                "empirical_data": [DatabaseConfig, ...],
            }
        """
        # 1. 匹配子分类
        topic_subcats = self._match_subcategories(topic)
        method_subcats = self.METHODOLOGY_TO_SUBCATEGORY.get(methodology, [])
        all_subcats = list(dict.fromkeys(topic_subcats + method_subcats))  # 去重保序

        # 2. 确定要返回哪些研究大类
        categories = self.STAGE_TO_CATEGORY.get(stage, ["policy_research", "literature_retrieval", "empirical_data"])

        # 3. 按大类分组推荐
        result: dict[str, list[DatabaseConfig]] = {}
        for cat in categories:
            if cat == "general_reference":
                continue

            # 获取该大类下所有数据库
            cat_dbs = self.get_by_category(cat)

            if all_subcats:
                # 有匹配的子分类：优先返回匹配的数据库
                matched_dbs = [
                    db for db in cat_dbs
                    if db.research_subcategory in all_subcats
                ]
                # 补充该大类下已集成但未匹配的数据库
                matched_keys = {db.key for db in matched_dbs}
                for db in cat_dbs:
                    if db.key not in matched_keys and db.integration_status == "integrated":
                        matched_dbs.append(db)
                        matched_keys.add(db.key)
                result[cat] = matched_dbs
            else:
                # 无匹配：返回该大类下所有数据库（已集成优先）
                result[cat] = cat_dbs

        logger.info(
            "DatabaseSelector.recommend: topic='%s', methodology='%s', "
            "matched_subcategories=%s, recommended=%s",
            topic, methodology, all_subcats,
            {cat: len(dbs) for cat, dbs in result.items()},
        )

        return result

    def recommend_for_policy_search(self, topic: str) -> list[DatabaseConfig]:
        """推荐政策调研阶段的数据库.

        Args:
            topic: 研究主题.

        Returns:
            政策调研类数据库列表，按相关度排序.
        """
        plan = self.recommend(topic, stage="policy_research")
        return plan.get("policy_research", [])

    def recommend_for_literature_search(self, topic: str) -> list[DatabaseConfig]:
        """推荐文献检索阶段的数据库.

        Args:
            topic: 研究主题.

        Returns:
            文献检索类数据库列表，中英文混合.
        """
        plan = self.recommend(topic, stage="literature_retrieval")
        return plan.get("literature_retrieval", [])

    def recommend_for_empirical_data(self, topic: str, methodology: str = "") -> list[DatabaseConfig]:
        """推荐实证数据阶段的数据库.

        Args:
            topic: 研究主题.
            methodology: 研究方法论.

        Returns:
            实证数据类数据库列表.
        """
        plan = self.recommend(topic, methodology=methodology, stage="empirical_data")
        return plan.get("empirical_data", [])

    def format_recommendation(self, plan: dict[str, list[DatabaseConfig]]) -> str:
        """格式化推荐结果为可读文本.

        Args:
            plan: recommend()方法返回的推荐字典.

        Returns:
            格式化的Markdown文本.
        """
        category_labels = {
            "policy_research": "政策调研",
            "literature_retrieval": "文献检索",
            "empirical_data": "实证数据",
        }
        status_labels = {
            "integrated": "已集成",
            "configured": "已配置",
            "not_integrated": "未集成",
        }

        lines: list[str] = []
        for cat, dbs in plan.items():
            label = category_labels.get(cat, cat)
            if not dbs:
                continue
            lines.append(f"### {label}（{len(dbs)}个数据库）")
            for db in dbs:
                status = status_labels.get(db.integration_status, db.integration_status)
                lang = "中文" if db.language == "zh" else ("外文" if db.language == "en" else "中英")
                free_tag = " | 免费" if db.is_free else ""
                lines.append(
                    f"- **{db.name}** [{status} | {lang}{free_tag}]"
                )
                if db.content_description:
                    lines.append(f"  内容: {db.content_description}")
                if db.strengths:
                    lines.append(f"  优势: {', '.join(db.strengths[:3])}")
            lines.append("")

        return "\n".join(lines) if lines else "（无推荐数据库）"


class VpnDatabaseAccess:
    """VPN数据库统一访问层.

    提供对VPN可达数据库的编程访问。
    英文文献数据库通过VPN代理URL重写访问；
    EPS统计数据通过API访问。
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._eps_sid: str | None = None  # EPS会话ID

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建httpx异步客户端."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                verify=False,  # VPN代理可能使用自签名证书
            )
        return self._client

    async def close(self):
        """关闭HTTP客户端."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    def get_database(self, key: str) -> DatabaseConfig | None:
        """获取数据库配置.

        Args:
            key: 数据库标识（如"sciencedirect"）.

        Returns:
            DatabaseConfig实例，若不存在返回None.
        """
        return DATABASES.get(key)

    def list_databases(self) -> list[DatabaseConfig]:
        """列出所有可用数据库.

        Returns:
            DatabaseConfig列表.
        """
        return list(DATABASES.values())

    def get_search_url(self, db_key: str, keyword: str) -> str | None:
        """获取VPN数据库的搜索URL.

        对于vpn_url_rewrite类型的数据库，构建完整的VPN搜索URL。
        对于browser类型的数据库，返回VPN基础URL（需浏览器自动化）。

        Args:
            db_key: 数据库标识.
            keyword: 搜索关键词.

        Returns:
            搜索URL字符串，或None.
        """
        db = DATABASES.get(db_key)
        if not db:
            return None
        if db.access_method == "vpn_url_rewrite" and db.search_url_template:
            search_path = db.search_url_template.format(keyword=keyword)
            return f"http://{db.vpn_domain}{search_path}"
        elif db.access_method == "browser":
            return db.vpn_url
        return None

    async def search_english_literature(
        self,
        keyword: str,
        sources: list[str] | None = None,
    ) -> list[dict]:
        """通过VPN代理搜索英文文献.

        对ScienceDirect/Springer/Emerald等数据库发起HTTP搜索请求。
        注意：这些数据库返回的是HTML页面，解析结果有限。
        建议优先使用OpenAlex/Semantic Scholar API获取元数据，
        此方法主要用于获取全文PDF链接。

        Args:
            keyword: 搜索关键词（英文）.
            sources: 数据库列表，默认["sciencedirect", "springer", "emerald"].

        Returns:
            搜索结果列表，每项含title/url/database字段.
        """
        if sources is None:
            sources = ["sciencedirect", "springer", "emerald"]

        results = []
        client = await self._get_client()

        for source in sources:
            db = DATABASES.get(source)
            if not db or db.access_method != "vpn_url_rewrite":
                continue
            try:
                search_path = db.search_url_template.format(keyword=keyword)
                url = f"http://{db.vpn_domain}{search_path}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    # 简单提取搜索结果链接
                    # 注意：完整解析需要BeautifulSoup，这里仅提取基本链接
                    links = re.findall(
                        r'href="(/[^"]*(?:article|chapter|book)[^"]*)"',
                        resp.text,
                    )
                    for link in links[:10]:  # 每个源最多10条
                        full_url = f"http://{db.vpn_domain}{link}"
                        results.append({
                            "url": full_url,
                            "database": db.name,
                            "access": "vpn_full_text",
                        })
                    logger.info(
                        f"VPN搜索 {db.name}: 找到 {len(links[:10])} 条结果"
                    )
            except Exception as e:
                logger.warning(f"VPN搜索 {db.name} 失败: {e}")
                continue

        return results

    async def get_fulltext_pdf_url(self, article_url: str) -> str | None:
        """获取文章的VPN全文PDF链接.

        给定文章页面URL，尝试提取PDF下载链接。
        需要通过VPN代理访问。

        Args:
            article_url: 文章页面URL（原始URL或VPN URL）.

        Returns:
            PDF的VPN下载URL，或None.
        """
        # 如果是原始URL，转换为VPN URL
        if "vpn.lzufe.edu.cn" not in article_url:
            article_url = build_vpn_url(article_url)

        client = await self._get_client()
        try:
            resp = await client.get(article_url)
            if resp.status_code == 200:
                # 查找PDF链接
                pdf_links = re.findall(
                    r'href="(/[^"]*\.pdf[^"]*)"',
                    resp.text,
                    re.IGNORECASE,
                )
                if pdf_links:
                    # 转换为VPN URL
                    domain_part = article_url.split("/")[2]  # 获取VPN域名
                    return f"http://{domain_part}{pdf_links[0]}"
        except Exception as e:
            logger.warning(f"获取PDF链接失败: {e}")
        return None

    # ===== EPS 统计数据 API =====

    async def eps_login(self) -> str | None:
        """EPS平台登录，获取sid（会话ID）.

        EPS通过sid参数即可调用API，无需显式CARSI登录。
        通过VPN访问EPS首页，从响应中提取sid。

        Returns:
            sid字符串，或None（失败时）.
        """
        client = await self._get_client()
        try:
            # 通过VPN访问EPS首页
            eps_vpn_url = build_vpn_url("https://www.epsnet.com.cn/")
            resp = await client.get(eps_vpn_url)
            if resp.status_code == 200:
                # 从HTML中提取sid
                sid_match = re.search(r'sid["\s:=]+([a-f0-9]{32})', resp.text)
                if sid_match:
                    self._eps_sid = sid_match.group(1)
                    logger.info(f"EPS登录成功，sid: {self._eps_sid[:8]}...")
                    return self._eps_sid
                # 从Cookie提取
                if "sid" in resp.cookies:
                    self._eps_sid = resp.cookies["sid"]
                    logger.info(
                        f"EPS登录成功(Cookie)，sid: {self._eps_sid[:8]}..."
                    )
                    return self._eps_sid
        except Exception as e:
            logger.warning(f"EPS登录失败: {e}")
        return None

    async def eps_get_cube_tree(self) -> list[dict]:
        """获取EPS数据立方体树结构.

        Returns:
            数据立方体列表，每项含cubeId/name/children等字段.
        """
        if not self._eps_sid:
            sid = await self.eps_login()
            if not sid:
                return []

        client = await self._get_client()
        eps_api = build_vpn_url("https://www.epsnet.com.cn/api/cube/getCubeTree")
        try:
            resp = await client.get(eps_api, params={"sid": self._eps_sid})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {}).get("children", [])
        except Exception as e:
            logger.warning(f"EPS获取立方体树失败: {e}")
        return []

    async def eps_search_indicators(self, keyword: str) -> list[dict]:
        """搜索EPS统计指标.

        Args:
            keyword: 指标关键词（如"GDP""财政收入"）.

        Returns:
            匹配的指标列表，每项含cubeId/dimensionId/memberId/name等字段.
        """
        cube_tree = await self.eps_get_cube_tree()
        results = []

        def search_in_tree(nodes, depth=0):
            for node in nodes:
                name = node.get("name", "")
                if keyword.lower() in name.lower():
                    results.append({
                        "cube_id": node.get("id", ""),
                        "name": name,
                        "path": node.get("path", ""),
                        "type": node.get("type", ""),
                    })
                children = node.get("children", [])
                if children and depth < 3:
                    search_in_tree(children, depth + 1)

        search_in_tree(cube_tree)
        return results[:20]  # 最多返回20条

    async def eps_get_data(
        self,
        cube_id: str,
        dimensions: dict | None = None,
    ) -> dict | None:
        """获取EPS数据立方体数据.

        Args:
            cube_id: 数据立方体ID.
            dimensions: 维度筛选，如{"region": ["北京", "上海"], "year": ["2020", "2021"]}.

        Returns:
            数据字典，含行列标签和数值.
        """
        if not self._eps_sid:
            sid = await self.eps_login()
            if not sid:
                return None

        client = await self._get_client()
        eps_api = build_vpn_url("https://www.epsnet.com.cn/api/cube/getData")

        payload = {
            "sid": self._eps_sid,
            "cubeId": cube_id,
        }
        if dimensions:
            payload.update(dimensions)

        try:
            resp = await client.post(eps_api, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {})
        except Exception as e:
            logger.warning(f"EPS获取数据失败: {e}")
        return None

    # ===== 通用数据库搜索接口 =====

    # HTTP可解析的数据库及其解析器
    _HTTP_SEARCHABLE = {"ydyl_database", "springer"}

    async def search_database(
        self,
        db_key: str,
        keyword: str,
        max_results: int = 20,
    ) -> list[dict]:
        """通用数据库搜索调度器.

        根据数据库类型自动路由到合适的搜索方法：
        - HTTP可解析数据库（ydyl_database, springer）：直接HTTP搜索+HTML解析
        - EPS API数据库：调用EPS API搜索指标
        - 英文文献数据库（sciencedirect, springer, emerald）：VPN代理搜索
        - 浏览器数据库：返回搜索URL供浏览器自动化使用

        Args:
            db_key: 数据库标识（如"ydyl_database", "springer", "pkulaw"）.
            keyword: 搜索关键词.
            max_results: 最大返回结果数.

        Returns:
            搜索结果列表，每项含 title/url/database/source/date 字段.
            对于浏览器类型数据库，返回 [{"url": search_url, "database": name, "note": "browser_required"}].
        """
        db = DATABASES.get(db_key)
        if not db:
            logger.warning(f"search_database: 未知数据库 '{db_key}'")
            return []

        # 1. HTTP可解析数据库
        if db_key == "ydyl_database":
            return await self._search_ydyl_database(keyword, max_results)
        elif db_key == "springer":
            return await self._search_springer(keyword, max_results)

        # 2. EPS API数据库
        elif db_key == "eps":
            indicators = await self.eps_search_indicators(keyword)
            return [
                {
                    "title": ind.get("name", ""),
                    "url": f"https://www.epsnet.com.cn/",
                    "database": "EPS数据平台",
                    "source": "EPS API",
                    "cube_id": ind.get("cube_id", ""),
                }
                for ind in indicators[:max_results]
            ]

        # 3. 英文文献VPN搜索
        elif db_key in ("sciencedirect", "emerald"):
            return await self.search_english_literature(
                keyword, sources=[db_key]
            )

        # 4. 浏览器类型数据库 — 返回搜索URL
        elif db.search_url_template:
            search_path = db.search_url_template.format(keyword=quote(keyword))
            if db.access_method == "vpn_url_rewrite":
                search_url = f"http://{db.vpn_domain}{search_path}"
            elif db.access_method == "browser" and db.vpn_url and "vpn.lzufe.edu.cn" in db.vpn_url:
                base = db.vpn_url.rstrip("/")
                search_url = f"{base}{search_path}"
            else:
                # direct 或 browser（无VPN）类型
                base = db.original_url.rstrip("/")
                search_url = f"{base}{search_path}"
            return [{
                "url": search_url,
                "database": db.name,
                "note": "browser_required",
                "keyword": keyword,
            }]

        # 5. RAG索引数据库
        elif db.access_method == "rag_index":
            return [{
                "url": db.original_url,
                "database": db.name,
                "note": "rag_indexed",
                "keyword": keyword,
            }]

        logger.warning(f"search_database: 数据库 '{db_key}' 无可用搜索方法")
        return []

    async def _search_ydyl_database(
        self, keyword: str, max_results: int = 20
    ) -> list[dict]:
        """搜索一带一路数据库（HTTP直连，HTML解析）.

        一带一路数据库 (ydylcn.com) 支持GET搜索，结果为HTML页面，
        文章链接格式: <a href="https://www.ydylcn.com/zx/.../xxx.shtml">标题</a>

        Args:
            keyword: 搜索关键词.
            max_results: 最大返回结果数.

        Returns:
            搜索结果列表.
        """
        client = await self._get_client()
        results: list[dict] = []
        seen_urls: set[str] = set()

        search_url = f"https://www.ydylcn.com/?keyword={quote(keyword)}"
        try:
            resp = await client.get(search_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            if resp.status_code != 200:
                logger.warning(f"一带一路数据库搜索返回 {resp.status_code}")
                return []

            html = resp.text

            # 提取文章链接: <a href="https://www.ydylcn.com/zx/.../xxx.shtml">标题</a>
            pattern = (
                r'<a[^>]*href="(https?://www\.ydylcn\.com/[^"]+\.shtml)"[^>]*>([^<]{4,})</a>'
            )
            matches = re.findall(pattern, html)

            for url, title in matches:
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                if len(clean_title) < 4 or url in seen_urls:
                    continue
                # 过滤导航/备案链接
                if any(x in clean_title for x in ["备案", "ICP", "首页", "登录"]):
                    continue
                seen_urls.add(url)
                results.append({
                    "title": clean_title,
                    "url": url,
                    "database": "一带一路数据库",
                    "source": "ydylcn.com",
                })
                if len(results) >= max_results:
                    break

            logger.info(f"一带一路数据库搜索 '{keyword}': 找到 {len(results)} 条结果")
        except Exception as e:
            logger.warning(f"一带一路数据库搜索失败: {e}")

        return results

    async def _search_springer(
        self, keyword: str, max_results: int = 20
    ) -> list[dict]:
        """搜索Springer期刊（HTTP直连，HTML解析）.

        Springer (link.springer.com) 搜索结果包含 /article/ 和 /chapter/ 链接。

        Args:
            keyword: 搜索关键词（英文）.
            max_results: 最大返回结果数.

        Returns:
            搜索结果列表.
        """
        client = await self._get_client()
        results: list[dict] = []
        seen_urls: set[str] = set()

        search_url = (
            f"https://link.springer.com/search?query={quote(keyword)}&showAll=false"
        )
        try:
            resp = await client.get(search_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            })
            if resp.status_code != 200:
                logger.warning(f"Springer搜索返回 {resp.status_code}")
                return []

            html = resp.text

            # Springer搜索结果中，文章链接附近通常有标题
            # 策略：先找所有/article/和/chapter/链接，再从附近HTML提取标题
            article_pattern = r'href="(/article/[^"]+)"'
            chapter_pattern = r'href="(/chapter/[^"]+)"'

            for pattern in [article_pattern, chapter_pattern]:
                matches = re.findall(pattern, html)
                for path in matches:
                    full_url = f"https://link.springer.com{path}"
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

                    # 多策略标题提取
                    title = ""
                    # 策略1: <a>标签的title属性
                    attr_pattern = rf'href="{re.escape(path)}"[^>]*title="([^"]+)"'
                    attr_match = re.search(attr_pattern, html)
                    if attr_match:
                        title = attr_match.group(1).strip()
                    # 策略2: <a>标签内的文本
                    if not title:
                        text_pattern = rf'href="{re.escape(path)}"[^>]*>([^<]{{4,}})</a>'
                        text_match = re.search(text_pattern, html)
                        if text_match:
                            title = re.sub(r'<[^>]+>', '', text_match.group(1)).strip()
                    # 策略3: 附近<h3>标题
                    if not title:
                        h3_pattern = rf'<h3[^>]*>.*?href="{re.escape(path)}"[^>]*>(.*?)</a>.*?</h3>'
                        h3_match = re.search(h3_pattern, html, re.DOTALL)
                        if h3_match:
                            title = re.sub(r'<[^>]+>', '', h3_match.group(1)).strip()
                    # 策略4: 搜索结果项中提取
                    if not title:
                        # 找到链接位置，向后搜索500字符内的文本
                        pos = html.find(f'href="{path}"')
                        if pos >= 0:
                            nearby = html[pos:pos+500]
                            # 查找附近最长的文本节点
                            text_matches = re.findall(r'>([^<]{10,200})<', nearby)
                            if text_matches:
                                # 选择最长的非链接文本
                                title = max(text_matches, key=len).strip()
                    # 最终回退: 使用DOI后缀
                    if not title:
                        title = path.split("/")[-1]

                    results.append({
                        "title": title,
                        "url": full_url,
                        "database": "Springer",
                        "source": "link.springer.com",
                        "type": "article" if "/article/" in path else "chapter",
                    })
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break

            logger.info(f"Springer搜索 '{keyword}': 找到 {len(results)} 条结果")
        except Exception as e:
            logger.warning(f"Springer搜索失败: {e}")

        return results

    def get_browser_search_url(self, db_key: str, keyword: str) -> str | None:
        """获取浏览器自动化搜索URL.

        对于需要JavaScript渲染的数据库，构建搜索URL供浏览器自动化使用。

        Args:
            db_key: 数据库标识.
            keyword: 搜索关键词.

        Returns:
            搜索URL字符串，或None（数据库不支持搜索）.
        """
        db = DATABASES.get(db_key)
        if not db or not db.search_url_template:
            return None

        search_path = db.search_url_template.format(keyword=quote(keyword))

        if db.access_method == "vpn_url_rewrite":
            return f"http://{db.vpn_domain}{search_path}"
        elif db.access_method in ("direct", "free_api"):
            base = db.original_url.rstrip("/")
            return f"{base}{search_path}"
        elif db.access_method == "browser":
            # browser类型：如果有VPN URL且与原始URL不同，使用VPN URL
            if db.vpn_url and "vpn.lzufe.edu.cn" in db.vpn_url:
                base = db.vpn_url.rstrip("/")
                return f"{base}{search_path}"
            else:
                base = db.original_url.rstrip("/")
                return f"{base}{search_path}"
        else:
            return db.vpn_url

    async def search_multiple(
        self,
        db_keys: list[str],
        keyword: str,
        max_per_db: int = 10,
    ) -> dict[str, list[dict]]:
        """并行搜索多个数据库.

        Args:
            db_keys: 数据库标识列表.
            keyword: 搜索关键词.
            max_per_db: 每个数据库最大返回结果数.

        Returns:
            {db_key: [results]} 字典.
        """
        results: dict[str, list[dict]] = {}

        for db_key in db_keys:
            try:
                db_results = await self.search_database(db_key, keyword, max_per_db)
                results[db_key] = db_results
            except Exception as e:
                logger.warning(f"搜索 {db_key} 失败: {e}")
                results[db_key] = []

        return results
