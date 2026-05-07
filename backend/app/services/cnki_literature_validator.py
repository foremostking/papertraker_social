"""
CNKI文献验证服务 V5 - 集成Cookie管理器

根据官方文档优化，支持Cookie自动获取和缓存
"""

import asyncio
import json
import logging
import os
import random
from typing import Dict, List, Optional
from dataclasses import dataclass
import aiohttp
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class CNKIValidationResult:
    """CNKI验证结果 - 完整版"""
    keywords: List[str]
    search_query: str
    total_papers: int = 0

    # 来源类别分布
    source_distribution: Dict[str, int] = None

    # 年度分布（用于趋势分析）
    year_distribution: Dict[str, int] = None
    recent_papers_ratio: float = 0.0  # 近3年文献占比

    # 主题分布（用于竞争度分析）
    main_topic_distribution: Dict[str, int] = None  # 主要主题 (ZYZT|||CYZT)
    # 注意: CNKI的ZYZT API需要使用ZYZT|||CYZT组合格式才能获取数据
    topic_distribution: Dict[str, int] = None  # 兼容字段
    blue_ocean_topics: List[str] = None  # 蓝海主题（文献数<50）
    niche_subjects: List[str] = None  # 细分学科领域（基于subject_distribution）

    # 学科分布（用于交叉机会分析）
    subject_distribution: Dict[str, int] = None
    interdisciplinary_score: float = 0.0  # 交叉学科评分

    # 研究层次分布
    research_level_distribution: Dict[str, int] = None

    # 基金支持分布
    funding_distribution: Dict[str, int] = None

    # 期刊分布
    journal_distribution: Dict[str, int] = None  # 期刊分组统计 (QK)
    top_journals: List[Dict] = None  # 热门期刊（带核心期刊标识）
    top_papers: List[Dict] = None

    # 机构分布
    institution_distribution: Dict[str, int] = None  # 机构分组统计 (AFC)

    # 综合指标
    core_papers: int = 0
    core_ratio: float = 0.0
    is_valid: bool = False
    validation_details: Dict = None

    # 智能分析结果
    trend_analysis: str = None  # 热点/稳定/冷门
    competition_level: str = None  # 激烈/中等/蓝海
    research_type: str = None  # 理论/应用/政策

    def __post_init__(self):
        if self.source_distribution is None:
            self.source_distribution = {}
        if self.year_distribution is None:
            self.year_distribution = {}
        if self.main_topic_distribution is None:
            self.main_topic_distribution = {}
        if self.topic_distribution is None:
            self.topic_distribution = {}
        if self.blue_ocean_topics is None:
            self.blue_ocean_topics = []
        if self.niche_subjects is None:
            self.niche_subjects = []
        if self.subject_distribution is None:
            self.subject_distribution = {}
        if self.research_level_distribution is None:
            self.research_level_distribution = {}
        if self.funding_distribution is None:
            self.funding_distribution = {}
        if self.journal_distribution is None:
            self.journal_distribution = {}
        if self.institution_distribution is None:
            self.institution_distribution = {}
        if self.top_journals is None:
            self.top_journals = []
        if self.top_papers is None:
            self.top_papers = []
        if self.validation_details is None:
            self.validation_details = {}


class CNKILiteratureValidator:
    """CNKI文献验证器 V5 - 集成Cookie管理器"""

    BASE_URL = "https://kns.cnki.net/kns8s"
    BRIEF_GRID_API = f"{BASE_URL}/brief/grid"
    GROUP_RESULT_API = f"{BASE_URL}/group/result"

    # 用户提供的有效Cookie（作为备用）
    FALLBACK_COOKIE = (
        "Ecp_ClientId=d83c495f79519b333571ce13a1caecb30VAT2g2H06; "
        "cnkiUserKey=db56d603-79ef-3f2a-90f1-7263e8b74a7d; "
        "SID_kns_new=kns15018109; "
        "KNS2COOKIE=1774513277.535.171404.517558|b25e41a932fd162af3b8c5cff4059fc3"
    )

    CORE_SOURCES = [
        'CSSCI', '北大核心', 'CSCD', 'AMI',
        'SCI来源期刊', 'EI来源期刊', 'WJCI'
    ]

    def __init__(self, cookie: Optional[str] = None, auto_fetch: bool = True):
        """
        初始化验证器

        Args:
            cookie: 可选，CNKI Cookie字符串
            auto_fetch: 是否自动获取Cookie（当未提供或无效时）
        """
        self.auto_fetch = auto_fetch
        self.cookie = cookie
        self.cookies_dict = {}

        if cookie:
            self.cookies_dict = self._parse_cookie_string(cookie)

    def _parse_cookie_string(self, cookie_str: str) -> Dict[str, str]:
        """将Cookie字符串转换为字典"""
        cookies = {}
        for pair in cookie_str.split(';'):
            pair = pair.strip()
            if '=' in pair:
                key, value = pair.split('=', 1)
                cookies[key.strip()] = value.strip()
        return cookies

    async def _ensure_cookie(self) -> bool:
        """确保有有效的Cookie"""
        if self.cookie:
            # 测试Cookie是否有效
            if await self._test_cookie(self.cookie):
                self.cookies_dict = self._parse_cookie_string(self.cookie)
                return True
            else:
                logger.warning("提供的Cookie无效")

        if self.auto_fetch:
            logger.info("尝试自动获取Cookie...")
            from app.services.cnki_cookie_manager import CNKICookieManager

            manager = CNKICookieManager()
            self.cookie = await manager.get_cookie_async()

            if self.cookie:
                self.cookies_dict = self._parse_cookie_string(self.cookie)
                logger.info("成功获取Cookie")
                return True
            else:
                logger.warning("自动获取Cookie失败，使用备用Cookie")
                self.cookie = self.FALLBACK_COOKIE
                self.cookies_dict = self._parse_cookie_string(self.cookie)
                return True
        else:
            # 使用备用Cookie
            self.cookie = self.FALLBACK_COOKIE
            self.cookies_dict = self._parse_cookie_string(self.cookie)
            return True

    async def _test_cookie(self, cookie_str: str) -> bool:
        """测试Cookie是否有效"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://kns.cnki.net/kns8s/AdvSearch?crossids=YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }

        cookies = self._parse_cookie_string(cookie_str)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/search",
                    headers=headers,
                    cookies=cookies,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    return response.status == 200
        except:
            return False

    def _build_search_query(self, keywords: List[str]) -> str:
        """构建检索式 - 使用 SU%= 语法"""
        return " AND ".join([f"SU%='{kw}'" for kw in keywords])

    def _build_query_json(self, search_query: str) -> str:
        """构建QueryJson参数"""
        query_json = {
            "Platform": "",
            "Resource": "JOURNAL",
            "Classid": "YSTT4HG0",
            "Products": "",
            "QNode": {
                "QGroup": [
                    {
                        "Key": "Subject",
                        "Title": "",
                        "Logic": 0,
                        "Items": [
                            {
                                "Key": "Expert",
                                "Title": "",
                                "Logic": 0,
                                "Field": "EXPERT",
                                "Operator": 0,
                                "Value": search_query,
                                "Value2": ""
                            }
                        ],
                        "ChildItems": []
                    },
                    {
                        "Key": "ControlGroup",
                        "Title": "",
                        "Logic": 0,
                        "Items": [],
                        "ChildItems": [
                            {
                                "Key": ".tit-startend-yearbox",
                                "Title": "",
                                "Logic": 0,
                                "Items": [
                                    {
                                        "Key": ".tit-startend-yearbox",
                                        "Title": "出版年度",
                                        "Logic": 0,
                                        "Field": "YE",
                                        "Operator": 7,
                                        "Value": "2020",
                                        "Value2": "2026"
                                    }
                                ],
                                "ChildItems": []
                            }
                        ]
                    }
                ]
            },
            "ExScope": "1",
            "SearchType": 4,
            "Rlang": "CHINESE",
            "KuaKuCode": "",
            "Expands": {},
            "View": "changeDBCh",
            "SearchFrom": 1
        }
        return json.dumps(query_json, ensure_ascii=False)

    async def _fetch_brief_grid(self, query_json: str, search_query: str) -> Dict:
        """请求brief/grid API获取文献列表"""
        post_data = {
            'boolSearch': 'true',
            'QueryJson': query_json,
            'pageNum': '1',
            'pageSize': '20',
            'sortField': 'FFD',
            'sortType': 'DESC',
            'dstyle': 'listmode',
            'boolSortSearch': 'false',
            'aside': f'({search_query})',
            'searchFrom': '资源范围：学术期刊;  中英文扩展;  时间范围：出版年度：2020 到 2026,更新时间：不限;  来源类别：全部期刊; ',
            'subject': '',
            'turnpage': '',
            'language': 'uniplatform',
            'CurPage': '1'
        }

        headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://kns.cnki.net',
            'Referer': 'https://kns.cnki.net/kns8s/AdvSearch?crossids=YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest'
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.BRIEF_GRID_API,
                data=post_data,
                headers=headers,
                cookies=self.cookies_dict
            ) as response:
                html_content = await response.text()

                # 保存响应用于调试
                os.makedirs('data', exist_ok=True)
                with open('data/debug_api_response.html', 'w', encoding='utf-8') as f:
                    f.write(html_content)

                return self._parse_brief_grid_html(html_content)

    def _parse_brief_grid_html(self, html: str) -> Dict:
        """解析brief/grid返回的HTML"""
        soup = BeautifulSoup(html, 'html.parser')

        result = {'total_count': 0, 'papers': []}

        # 解析文献总数
        count_div = soup.find('div', id='countPageDiv')
        if count_div:
            count_em = count_div.find('em')
            if count_em:
                try:
                    # 移除逗号再转换为整数（如 "10,707" -> 10707）
                    count_text = count_em.get_text().strip().replace(',', '')
                    result['total_count'] = int(count_text)
                except ValueError:
                    pass

        # 解析文献列表
        table = soup.find('table', class_='result-table-list')
        if table:
            tbody = soup.find('tbody')
            if tbody:
                for row in tbody.find_all('tr'):
                    paper = self._parse_paper_row(row)
                    if paper:
                        result['papers'].append(paper)

        return result

    def _parse_paper_row(self, row) -> Optional[Dict]:
        """解析单篇文献信息"""
        try:
            cells = row.find_all('td')
            if len(cells) < 6:
                return None

            paper = {'title': '', 'authors': [], 'journal': '', 'date': '', 'cited': 0, 'download': 0}

            # 篇名
            if len(cells) > 1:
                title_link = cells[1].find('a', class_='fz14')
                if title_link:
                    for font in title_link.find_all('font'):
                        font.unwrap()
                    paper['title'] = title_link.get_text().strip()

            # 作者
            if len(cells) > 2:
                author_links = cells[2].find_all('a', class_='KnowledgeNetLink')
                paper['authors'] = [a.get_text().strip() for a in author_links]

            # 刊名
            if len(cells) > 3:
                source_link = cells[3].find('a')
                if source_link:
                    paper['journal'] = source_link.get_text().strip()

            # 发表时间
            if len(cells) > 4:
                paper['date'] = cells[4].get_text().strip()

            # 被引
            if len(cells) > 5:
                quote_text = cells[5].get_text().strip()
                if quote_text.isdigit():
                    paper['cited'] = int(quote_text)

            # 下载
            if len(cells) > 6:
                download_link = cells[6].find('a', class_='downloadCnt')
                if download_link:
                    download_text = download_link.get_text().strip()
                    if download_text.isdigit():
                        paper['download'] = int(download_text)

            return paper
        except Exception as e:
            logger.warning(f"解析文献行失败: {e}")
            return None

    async def validate_keywords(self, keywords: List[str],
                               db: Optional[Session] = None) -> CNKIValidationResult:
        """验证关键词的学术性"""
        logger.info(f"开始验证关键词: {keywords}")

        search_query = self._build_search_query(keywords)
        result = CNKIValidationResult(keywords=keywords, search_query=search_query)

        try:
            # 确保有有效的Cookie
            if not await self._ensure_cookie():
                result.validation_details['error'] = "无法获取有效Cookie"
                return result

            # 构建QueryJson
            query_json = self._build_query_json(search_query)

            # 获取文献列表
            logger.info(f"检索式: {search_query}")
            brief_result = await self._fetch_brief_grid(query_json, search_query)
            result.total_papers = brief_result['total_count']

            logger.info(f"文献总数: {result.total_papers}")

            # 获取来源类别分组统计
            group_result = await self._fetch_group_result(query_json, search_query, db)
            result.source_distribution = group_result.get('source_distribution', {})

            # 并发获取其他维度的分组统计
            logger.info("获取多维度分组统计...")
            dimensions = await self._fetch_all_dimensions(query_json, search_query)

            result.year_distribution = dimensions.get('year', {})
            result.main_topic_distribution = dimensions.get('main_topic', {})
            result.topic_distribution = dimensions.get('main_topic', {})  # 兼容：使用主要主题
            result.subject_distribution = dimensions.get('subject', {})
            result.research_level_distribution = dimensions.get('research_level', {})
            result.funding_distribution = dimensions.get('funding', {})
            result.journal_distribution = dimensions.get('journal', {})
            result.institution_distribution = dimensions.get('institution', {})

            # 从subject_distribution中提取细分领域
            # 将文献数<50的学科定义为"细分领域"（相当于蓝海主题）
            if result.subject_distribution:
                result.niche_subjects = [
                    subject for subject, count in result.subject_distribution.items()
                    if 0 < count < 50
                ]
            else:
                result.niche_subjects = []

            # 分析主要主题的蓝海机会（如果ZYZT|||CYZT返回了数据）
            blue_ocean_from_main = []
            if result.main_topic_distribution:
                blue_ocean_from_main = [
                    topic for topic, count in result.main_topic_distribution.items()
                    if 0 < count < 50
                ]

            # 合并所有蓝海主题
            result.blue_ocean_topics = list(set(
                result.niche_subjects + blue_ocean_from_main
            ))

            # 记录API状态说明
            api_status = []
            if result.main_topic_distribution:
                api_status.append(f"主题分布(ZYZT|||CYZT): 已获取{len(result.main_topic_distribution)}项数据")
            else:
                api_status.append("主题分布(ZYZT|||CYZT): API返回空数据")

            result.validation_details['topic_api_note'] = "; ".join(api_status)

            # 计算近3年文献占比（使用完整的3年数据：2023-2025）
            recent_years = ['2025年', '2024年', '2023年']
            recent_count = sum(result.year_distribution.get(y, 0) for y in recent_years)
            total_for_ratio = sum(result.year_distribution.values())
            if total_for_ratio > 0:
                result.recent_papers_ratio = recent_count / total_for_ratio

            # 分析趋势
            if result.recent_papers_ratio > 0.5:
                result.trend_analysis = "热点上升期"
            elif result.recent_papers_ratio > 0.3:
                result.trend_analysis = "稳定发展期"
            else:
                result.trend_analysis = "成熟期或衰退期"

            # 分析竞争程度（基于细分领域数量）
            # 注意: 由于CNKI的ZYZT(主题)API不可用，使用niche_subjects分析
            if len(result.niche_subjects) > 5:
                result.competition_level = "蓝海（竞争少）"
            elif len(result.niche_subjects) > 2:
                result.competition_level = "中等竞争"
            else:
                result.competition_level = "激烈竞争"

            # 分析学科交叉程度
            if len(result.subject_distribution) > 0:
                total_subjects = sum(result.subject_distribution.values())
                max_subject_ratio = max(result.subject_distribution.values()) / total_subjects if total_subjects > 0 else 0
                result.interdisciplinary_score = 1 - max_subject_ratio  # 越分散说明越交叉

            # 分析研究类型
            if result.research_level_distribution:
                basic_ratio = result.research_level_distribution.get('基础研究', 0) / sum(result.research_level_distribution.values()) if sum(result.research_level_distribution.values()) > 0 else 0
                if basic_ratio > 0.5:
                    result.research_type = "理论型"
                else:
                    result.research_type = "应用型"

            # 计算核心期刊数量和占比
            result.core_papers = sum(
                result.source_distribution.get(s, 0) for s in self.CORE_SOURCES
            )
            if result.total_papers > 0:
                result.core_ratio = result.core_papers / result.total_papers

            logger.info(f"核心期刊: {result.core_papers}篇 ({result.core_ratio:.1%})")

            # 解析期刊分布
            if brief_result['papers']:
                journals = [p['journal'] for p in brief_result['papers'] if p['journal']]
                result.top_journals = self._analyze_journal_distribution(journals, db)

        except Exception as e:
            logger.error(f"CNKI检索失败: {e}")
            import traceback
            traceback.print_exc()
            result.validation_details['error'] = str(e)

        # 判断是否合格
        result.is_valid = self._check_validation(result)

        logger.info(f"验证完成: 总数={result.total_papers}, "
                   f"核心占比={result.core_ratio:.2%}, 合格={result.is_valid}")

        return result

    def _build_search_query(self, keywords: List[str]) -> str:
        """构建检索式 - 使用 SU%= 语法"""
        return " AND ".join([f"SU%='{kw}'" for kw in keywords])

    def _build_query_json(self, search_query: str) -> str:
        """构建QueryJson参数"""
        query_json = {
            "Platform": "",
            "Resource": "JOURNAL",
            "Classid": "YSTT4HG0",
            "Products": "",
            "QNode": {
                "QGroup": [
                    {
                        "Key": "Subject",
                        "Title": "",
                        "Logic": 0,
                        "Items": [
                            {
                                "Key": "Expert",
                                "Title": "",
                                "Logic": 0,
                                "Field": "EXPERT",
                                "Operator": 0,
                                "Value": search_query,
                                "Value2": ""
                            }
                        ],
                        "ChildItems": []
                    },
                    {
                        "Key": "ControlGroup",
                        "Title": "",
                        "Logic": 0,
                        "Items": [],
                        "ChildItems": [
                            {
                                "Key": ".tit-startend-yearbox",
                                "Title": "",
                                "Logic": 0,
                                "Items": [
                                    {
                                        "Key": ".tit-startend-yearbox",
                                        "Title": "出版年度",
                                        "Logic": 0,
                                        "Field": "YE",
                                        "Operator": 7,
                                        "Value": "2020",
                                        "Value2": "2026"
                                    }
                                ],
                                "ChildItems": []
                            }
                        ]
                    }
                ]
            },
            "ExScope": "1",
            "SearchType": 4,
            "Rlang": "CHINESE",
            "KuaKuCode": "",
            "Expands": {},
            "View": "changeDBCh",
            "SearchFrom": 1
        }
        return json.dumps(query_json, ensure_ascii=False)

    async def _fetch_brief_grid(self, query_json: str, search_query: str) -> Dict:
        """请求brief/grid API获取文献列表"""
        post_data = {
            'boolSearch': 'true',
            'QueryJson': query_json,
            'pageNum': '1',
            'pageSize': '20',
            'sortField': 'FFD',
            'sortType': 'DESC',
            'dstyle': 'listmode',
            'boolSortSearch': 'false',
            'aside': f'({search_query})',
            'searchFrom': '资源范围：学术期刊;  中英文扩展;  时间范围：出版年度：2020 到 2026,更新时间：不限;  来源类别：全部期刊; ',
            'subject': '',
            'turnpage': '',
            'language': 'uniplatform',
            'CurPage': '1'
        }

        headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://kns.cnki.net',
            'Referer': 'https://kns.cnki.net/kns8s/AdvSearch?crossids=YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin'
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.BRIEF_GRID_API,
                data=post_data,
                headers=headers,
                cookies=self.cookies_dict
            ) as response:
                html_content = await response.text()

                # 保存响应用于调试
                os.makedirs('data', exist_ok=True)
                with open('data/debug_api_response.html', 'w', encoding='utf-8') as f:
                    f.write(html_content)

                return self._parse_brief_grid_html(html_content)

    async def _fetch_group_result(self, query_json: str, search_query: str, db: Optional[Session] = None) -> Dict:
        """获取来源类别分组统计

        使用CNKI的group/result API，传递groupIds=LYBSM参数直接获取来源类别分布
        """
        logger.info("获取来源类别分组统计（通过CNKI API）...")

        # 使用groupIds参数获取来源类别分组
        post_data = {
            'queryJson': query_json,
            'groupIds': 'LYBSM',  # 来源类别的ID
            'aside': f'({search_query})',
            'subject': '',
            'language': 'uniplatform'
        }

        headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://kns.cnki.net',
            'Referer': 'https://kns.cnki.net/kns8s/AdvSearch?crossids=YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin'
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.GROUP_RESULT_API,
                    data=post_data,
                    headers=headers,
                    cookies=self.cookies_dict
                ) as response:
                    html_content = await response.text()

                    # 保存响应用于调试
                    os.makedirs('data', exist_ok=True)
                    with open('data/debug_group_result_LYBSM.html', 'w', encoding='utf-8') as f:
                        f.write(html_content)

                    return self._parse_group_result_html_lybsm(html_content)

        except Exception as e:
            logger.warning(f"获取分组统计失败: {e}")
            # 降级到期刊匹配方法
            logger.info("降级使用期刊匹配方法...")
            return await self._fetch_group_result_fallback(query_json, search_query, db)

    def _parse_group_result_html_lybsm(self, html: str) -> Dict:
        """从group/result API返回的HTML中解析来源类别（LYBSM）分组数据"""
        import re

        source_dist = {}

        # 使用正则表达式查找groupId="LYBSM"的dl标签内容
        # 因为BeautifulSoup可能会丢失某些属性
        lybsm_pattern = r'<dl[^>]*groupId="LYBSM"[^>]*>.*?</dl>'
        match = re.search(lybsm_pattern, html, re.DOTALL)

        if match:
            dl_html = match.group(0)
            soup = BeautifulSoup(dl_html, 'html.parser')

            dd = soup.find('dd')
            if dd:
                # 解析每个来源类别
                for li in dd.find_all('li'):
                    # 获取来源类别名称
                    checkbox = li.find('input')
                    name = checkbox.get('text', '') if checkbox else ''

                    # 获取文献数量
                    span = li.find('span')
                    if span:
                        count_text = span.get_text().strip().strip('()')
                        try:
                            count = int(count_text)
                            source_dist[name] = count
                        except ValueError:
                            pass

        logger.info(f"CNKI来源类别分布: {source_dist}")
        return {'source_distribution': source_dist}

    async def _fetch_group_result_fallback(self, query_json: str, search_query: str, db: Optional[Session] = None) -> Dict:
        """降级方法：通过期刊匹配获取来源类别分布"""
        logger.info("使用期刊匹配方法获取来源类别...")

        # 获取更多页的文献数据以便更准确地统计
        post_data = {
            'boolSearch': 'true',
            'QueryJson': query_json,
            'pageNum': '1',
            'pageSize': '50',
            'sortField': 'FFD',
            'sortType': 'DESC',
            'dstyle': 'listmode',
            'boolSortSearch': 'false',
            'aside': f'({search_query})',
            'searchFrom': '资源范围：学术期刊;  中英文扩展;  时间范围：出版年度：2020 到 2026,更新时间：不限;  来源类别：全部期刊; ',
            'subject': '',
            'turnpage': '',
            'language': 'uniplatform',
            'CurPage': '1'
        }

        headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://kns.cnki.net',
            'Referer': 'https://kns.cnki.net/kns8s/AdvSearch?crossids=YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin'
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.BRIEF_GRID_API,
                    data=post_data,
                    headers=headers,
                    cookies=self.cookies_dict
                ) as response:
                    html_content = await response.text()
                    soup = BeautifulSoup(html_content, 'html.parser')

                    # 解析期刊列表
                    journals = []
                    table = soup.find('table', class_='result-table-list')
                    if table:
                        tbody = soup.find('tbody')
                        if tbody:
                            for row in tbody.find_all('tr'):
                                cells = row.find_all('td')
                                if len(cells) > 3:
                                    source_link = cells[3].find('a')
                                    if source_link:
                                        journal_name = source_link.get_text().strip()
                                        journals.append(journal_name)

                    # 统计来源类别分布
                    source_dist = self._analyze_source_distribution(journals, 0, db)

                    return {
                        'source_distribution': source_dist,
                        'sample_journals': journals[:20]
                    }
        except Exception as e:
            logger.warning(f"期刊匹配方法也失败: {e}")
            return {}

    def _analyze_source_distribution(self, journals: List[str], total_count: int, db: Optional[Session] = None) -> Dict[str, int]:
        """分析期刊列表，统计来源类别分布（降级方法）

        Args:
            journals: 期刊名称列表（从CNKI获取的样本）
            total_count: CNKI返回的文献总数
            db: 数据库会话（可选，用于查询CSSCI数据库）

        Returns:
            来源类别分布字典
        """
        from collections import Counter

        # 按来源类别分组统计
        category_counts = Counter({
            'CSSCI': 0,
            'CSSCI扩展版': 0,
            '北大核心': 0,
            'CSCD': 0,
            'AMI': 0,
            'SCI来源期刊': 0,
            'EI来源期刊': 0,
            'WJCI': 0,
            '普通期刊': 0
        })

        if not db or not journals:
            logger.debug("无法分析来源类别：缺少数据库连接或期刊列表")
            return dict(category_counts)

        try:
            from app.models.journal import Journal

            # 获取所有期刊记录（批量查询）
            journal_records = db.query(Journal).filter(
                Journal.name.in_(journals)
            ).all()

            # 构建期刊名称到记录的映射
            journal_map = {j.name: j for j in journal_records}

            # 统计每个期刊的来源类别
            matched_count = 0
            for journal_name in journals:
                if journal_name in journal_map:
                    matched_count += 1
                    record = journal_map[journal_name]

                    # 根据期刊的核心字段统计（按优先级，每篇论文只计数一次）
                    # 优先级：CSSCI > CSSCI扩展版 > 北大核心 > CSCD > AMI > SCI/EI/WJCI > 普通期刊
                    if record.is_cssci:
                        category_counts['CSSCI'] += 1
                    elif record.is_cssci_expansion:
                        category_counts['CSSCI扩展版'] += 1
                    elif record.is_beida_core:
                        category_counts['北大核心'] += 1
                    elif record.is_cscd:
                        category_counts['CSCD'] += 1
                    elif record.is_ami:
                        category_counts['AMI'] += 1
                    elif record.is_sci:
                        category_counts['SCI来源期刊'] += 1
                    elif record.is_ei:
                        category_counts['EI来源期刊'] += 1
                    elif record.is_wjci:
                        category_counts['WJCI'] += 1
                    else:
                        # 不属于任何核心期刊，归类为普通期刊
                        category_counts['普通期刊'] += 1
                else:
                    # 期刊不在数据库中，归类为普通期刊
                    category_counts['普通期刊'] += 1

            logger.info(f"来源类别分析（期刊匹配）：匹配到 {matched_count}/{len(journals)} 本期刊")
            logger.info(f"期刊匹配的来源类别分布：{dict(category_counts)}")

        except Exception as e:
            logger.debug(f"分析来源类别失败（数据库表可能不存在）: {e}")

        return dict(category_counts)

    async def _fetch_all_dimensions(self, query_json: str, search_query: str) -> Dict[str, Dict]:
        """分别请求每个维度的分组统计数据

        由于CNKI的group/result API在传递多个groupIds时只返回部分数据，
        需要分别请求每个分组来获取完整数据。

        Returns:
            包含year, main_topic, minor_topic, subject, research_level,
            funding, journal, institution等维度的字典
        """
        headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://kns.cnki.net',
            'Referer': 'https://kns.cnki.net/kns8s/AdvSearch?crossids=YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin'
        }

        # 定义要获取的维度
        dimensions = {
            'year': 'YE',
            'main_topic': 'ZYZT|||CYZT',  # 主要主题（使用组合获取）
            'subject': 'CCL',
            'research_level': 'YJCC',
            'funding': 'FUC',
            'journal': 'QK',  # 期刊
            'institution': 'AFC',  # 机构
        }

        async def fetch_dimension(name: str, group_id: str) -> tuple:
            """获取单个维度的数据"""
            post_data = {
                'queryJson': query_json,
                'groupIds': group_id,
                'aside': f'({search_query})',
                'subject': '',
                'language': 'uniplatform'
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.GROUP_RESULT_API,
                        data=post_data,
                        headers=headers,
                        cookies=self.cookies_dict
                    ) as response:
                        html_content = await response.text()
                        return (name, self._parse_group_html_by_id(html_content, group_id))
            except Exception as e:
                logger.warning(f"获取{name}维度失败: {e}")
                return (name, {})

        # 并发获取所有维度
        tasks = [fetch_dimension(name, group_id) for name, group_id in dimensions.items()]
        results = await asyncio.gather(*tasks)

        return {name: data for name, data in results}

    def _parse_group_html_by_id(self, html: str, group_id: str) -> Dict[str, int]:
        """根据groupId解析分组HTML，提取统计数据

        当单独请求一个维度时，HTML响应通常只包含该维度的数据。
        我们只需要找到第一个有数据的dl标签即可。
        """
        import re
        from bs4 import BeautifulSoup

        result = {}
        soup = BeautifulSoup(html, 'html.parser')

        # 查找所有dl标签，找到第一个有实际数据的dl
        for dl in soup.find_all('dl'):
            dd = dl.find('dd')
            if not dd:
                continue

            # 检查dd是否有实际内容（不是空的或只有空格）
            content = dd.get_text().strip()
            if not content or content == '':
                continue

            # 检查是否有li条目
            items = dd.find_all('li')
            if not items:
                continue

            # 解析每个条目
            for li in items:
                # 获取名称
                name = ''
                checkbox = li.find('input')
                if checkbox and checkbox.get('text'):
                    name = checkbox.get('text', '')
                else:
                    a_tag = li.find('a')
                    if a_tag:
                        name = a_tag.get_text().strip()

                # 获取数量
                count = 0
                span = li.find('span')
                if span:
                    count_text = span.get_text().strip().strip('()')
                    try:
                        count = int(count_text)
                    except ValueError:
                        pass

                if name and count > 0:
                    result[name] = count

            # 如果找到了数据，就返回（假设每个响应只有一个主要的数据分组）
            if result:
                break

        return result

    def _parse_group_html(self, html: str, group_id: str) -> Dict[str, int]:
        """解析分组HTML，提取统计数据"""
        import re
        from bs4 import BeautifulSoup

        result = {}

        # 特殊处理：ZYZT/CYZT是组合的
        if group_id == 'ZYZT':
            # 查找主要主题（ZYZT）
            group_pattern = r'<dl[^>]*groupId="ZYZT\|\|CYZT"[^>]*>.*?</dl>'
            match = re.search(group_pattern, html, re.DOTALL)
            if match:
                dl_html = match.group(0)
                soup = BeautifulSoup(dl_html, 'html.parser')
                # 查找主要主题的dd（field="ZYZT"）
                dd = soup.find('dd', {'field': 'ZYZT'})
                if dd:
                    for li in dd.find_all('li'):
                        checkbox = li.find('input')
                        if checkbox:
                            name = checkbox.get('text', '')
                            span = li.find('span')
                            if span:
                                count_text = span.get_text().strip().strip('()')
                                try:
                                    count = int(count_text)
                                    result[name] = count
                                except ValueError:
                                    pass
        else:
            # 使用正则表达式查找对应的分组
            group_pattern = f'<dl[^>]*groupId="{group_id}[^"]*"[^>]*>.*?</dl>'
            match = re.search(group_pattern, html, re.DOTALL)

            if match:
                dl_html = match.group(0)
                soup = BeautifulSoup(dl_html, 'html.parser')

                dd = soup.find('dd')
                if dd:
                    # 解析每个条目
                    for li in dd.find_all('li'):
                        # 获取名称
                        checkbox = li.find('input')
                        if checkbox:
                            name = checkbox.get('text', '')
                        else:
                            a_tag = li.find('a')
                            name = a_tag.get_text().strip() if a_tag else ''

                        # 获取数量
                        span = li.find('span')
                        if span:
                            count_text = span.get_text().strip().strip('()')
                            try:
                                count = int(count_text)
                                result[name] = count
                            except ValueError:
                                pass

        logger.info(f"{group_id}维度分布: {result}")
        return result

    def _parse_brief_grid_html(self, html: str) -> Dict:
        """解析brief/grid返回的HTML"""
        soup = BeautifulSoup(html, 'html.parser')

        result = {'total_count': 0, 'papers': []}

        # 解析文献总数
        count_div = soup.find('div', id='countPageDiv')
        if count_div:
            count_em = count_div.find('em')
            if count_em:
                try:
                    # 移除逗号再转换为整数（如 "10,707" -> 10707）
                    count_text = count_em.get_text().strip().replace(',', '')
                    result['total_count'] = int(count_text)
                except ValueError:
                    pass

        # 解析文献列表
        table = soup.find('table', class_='result-table-list')
        if table:
            tbody = soup.find('tbody')
            if tbody:
                for row in tbody.find_all('tr'):
                    paper = self._parse_paper_row(row)
                    if paper:
                        result['papers'].append(paper)

        return result

    def _parse_paper_row(self, row) -> Optional[Dict]:
        """解析单篇文献信息"""
        try:
            cells = row.find_all('td')
            if len(cells) < 6:
                return None

            paper = {'title': '', 'authors': [], 'journal': '', 'date': '', 'cited': 0, 'download': 0}

            # 篇名
            if len(cells) > 1:
                title_link = cells[1].find('a', class_='fz14')
                if title_link:
                    for font in title_link.find_all('font'):
                        font.unwrap()
                    paper['title'] = title_link.get_text().strip()

            # 作者
            if len(cells) > 2:
                author_links = cells[2].find_all('a', class_='KnowledgeNetLink')
                paper['authors'] = [a.get_text().strip() for a in author_links]

            # 刊名
            if len(cells) > 3:
                source_link = cells[3].find('a')
                if source_link:
                    paper['journal'] = source_link.get_text().strip()

            # 发表时间
            if len(cells) > 4:
                paper['date'] = cells[4].get_text().strip()

            # 被引
            if len(cells) > 5:
                quote_text = cells[5].get_text().strip()
                if quote_text.isdigit():
                    paper['cited'] = int(quote_text)

            # 下载
            if len(cells) > 6:
                download_link = cells[6].find('a', class_='downloadCnt')
                if download_link:
                    download_text = download_link.get_text().strip()
                    if download_text.isdigit():
                        paper['download'] = int(download_text)

            return paper
        except Exception as e:
            logger.warning(f"解析文献行失败: {e}")
            return None

    def _analyze_journal_distribution(self, journals: List[str],
                                      db: Optional[Session]) -> List[Dict]:
        """分析期刊分布"""
        from collections import Counter

        journal_counter = Counter(journals)
        top_journals = []

        for journal, count in journal_counter.most_common(5):
            journal_info = {'name': journal, 'count': count, 'core_types': []}

            if db:
                try:
                    from app.models.journal import Journal
                    from app.services.journal_core_parser import JournalCoreParser

                    journal_record = db.query(Journal).filter(
                        Journal.name == journal
                    ).first()

                    if journal_record:
                        core_summary = JournalCoreParser.get_journal_core_summary(journal_record)
                        journal_info['core_types'] = (
                            core_summary['chinese_cores'] +
                            core_summary['international_cores']
                        )
                except Exception as e:
                    logger.debug(f"数据库查询失败（表可能不存在）: {e}")

            top_journals.append(journal_info)

        return top_journals

    def _check_validation(self, result: CNKIValidationResult) -> bool:
        """检查验证结果是否合格"""
        if result.total_papers < 50:
            return False
        return result.total_papers >= 50

    def get_validation_recommendation(self, result: CNKIValidationResult) -> str:
        """获取验证建议"""
        if result.is_valid:
            return "关键词组合学术性良好，可以开展研究。"

        recommendations = []

        if result.total_papers < 50:
            recommendations.append(f"文献总量不足（仅{result.total_papers}篇），建议：")
            recommendations.append("1. 考虑更换为更通用的关键词")
            recommendations.append("2. 减少关键词数量，扩大检索范围")
        elif result.total_papers < 300:
            recommendations.append(f"文献总量偏少（{result.total_papers}篇），建议添加限定维度")

        return "\n".join(recommendations)


# 便捷函数
async def validate_keywords_async(keywords: List[str],
                                   cookie: Optional[str] = None,
                                   db: Optional[Session] = None) -> CNKIValidationResult:
    """异步验证关键词"""
    validator = CNKILiteratureValidator(cookie=cookie, auto_fetch=True)
    return await validator.validate_keywords(keywords, db)

