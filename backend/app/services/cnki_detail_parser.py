"""
CNKI 期刊详情页解析服务

负责从 CNKI 期刊详情页提取额外的期刊信息
包含反爬虫策略：随机延迟、User-Agent 轮换、重试机制
使用 Playwright 动态提取期刊代码和栏目
"""
import requests
from bs4 import BeautifulSoup
import re
import logging
import time
import random
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.journal import Journal
from app.services.cnki_journal_code_extractor import extract_journal_code_sync
from urllib3.exceptions import SSLError as URLLIB3_SSLError
from requests.exceptions import SSLError, ConnectionError, RequestException, Timeout

logger = logging.getLogger(__name__)


# 随机 User-Agent 池
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0',
]


class CNKIDetailParser:
    """CNKI 期刊详情页解析器（含反爬虫策略）"""

    # 字段映射：CNKI 字段名 -> 数据库字段名
    FIELD_MAPPING = {
        '主办单位': 'publisher',
        '出版周期': 'publishing_cycle',
        '出版地': 'publishing_location',
        '语种': 'language',
        '开本': 'format',
        '邮发代号': 'postal_code',
        '创刊时间': 'founded_year',
        '专辑名称': 'field',           # 专辑名称直接映射到一级学科 field
        '专题名称': 'subfield',         # 专题名称映射到二级学科 subfield
        '出版文献量': 'total_documents',
        '总下载次数': 'total_downloads',
        '总被引次数': 'total_citations',
    }

    # 正则模式
    PATTERNS = {
        '主办单位': r'主办单位[::：\s]*([\u4e00-\u9fa5a-zA-Z\d()（）]{3,80})',
        '出版周期': r'出版周期[::：\s]*([\u4e00-\u9fa5a-zA-Z\d()（）]{2,10})',
        '出版地': r'出版地[::：\s]*([\u4e00-\u9fa5\d()（）]{2,50})',
        '语种': r'语种[::：\s]*([\u4e00-\u9fa5a-zA-Z\d()（）]{2,10})',
        '开本': r'开本[::：\s]*([\u4e00-\u9fa5\d()（）]{2,10})',
        '邮发代号': r'邮发代号[::：\s]*([\d-]{1,10})',
        '创刊时间': r'创刊时间[::：\s]*(\d{4})',
        # 专辑名称和专题名称使用简单模式
        '专辑名称': r'专辑名称[::：\s]*([^；;\n\t]*(?:[；;]|\s*(?=$|ISSN|CN|主办|出版|语种|开本|邮发|创刊|出版文献|总下载|总被引|专题名称)))',
        '专题名称': r'专题名称[::：\s]*([^；;\n\t]*(?:[；;]|\s*(?=$|ISSN|CN|主办|出版|语种|开本|邮发|创刊|出版文献|总下载|总被引|专辑名称)))',
        '出版文献量': r'出版文献量[::：\s]*([\d,]+)',
        '总下载次数': r'总下载次数[::：\s]*([\d,]+)',
        '总被引次数': r'总被引次数[::：\s]*([\d,]+)',
    }

    def __init__(
        self,
        db: Session,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        max_retries: int = 3
    ):
        """
        初始化解析器

        Args:
            db: 数据库会话
            min_delay: 请求最小延迟（秒）
            max_delay: 请求最大延迟（秒）
            max_retries: 最大重试次数
        """
        self.db = db
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0
        }

        # 创建 Session 用于连接复用
        self.session = requests.Session()
        # 预先连接到 CNKI 建立初始会话
        try:
            self.session.get('https://navi.cnki.net', timeout=10, headers={'User-Agent': random.choice(USER_AGENTS)})
        except:
            pass

        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'max-age=0',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

    def _get_random_headers(self) -> Dict[str, str]:
        """获取随机请求头"""
        headers = self.session.headers.copy()
        headers['User-Agent'] = random.choice(USER_AGENTS)
        return headers

    def _random_delay(self):
        """随机延迟"""
        delay = random.uniform(self.min_delay, self.max_delay)
        logger.debug(f"延迟 {delay:.2f} 秒...")
        time.sleep(delay)

    def _fetch_with_retry(self, url: str) -> Optional[requests.Response]:
        """
        带重试机制的请求

        Args:
            url: 请求 URL

        Returns:
            Response 对象，失败返回 None
        """
        for attempt in range(self.max_retries):
            try:
                headers = self._get_random_headers()
                response = self.session.get(
                    url,
                    headers=headers,
                    timeout=30,
                    allow_redirects=True,
                    verify=True  # SSL 验证
                )

                if response.status_code == 200:
                    return response
                elif response.status_code == 429:
                    # 请求过于频繁，增加等待时间
                    wait_time = (attempt + 1) * 5
                    logger.warning(f"请求频繁，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                elif response.status_code >= 500:
                    # 服务器错误，指数退避
                    wait_time = 2 ** attempt
                    logger.warning(f"服务器错误，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"HTTP {response.status_code}: {url}")
                    return None

            except Timeout:
                wait_time = 2 ** attempt + 3
                logger.warning(f"请求超时，{wait_time} 秒后重试...")
                time.sleep(wait_time)
            except SSLError as e:
                # SSL 错误，增加等待时间后重试
                wait_time = (attempt + 1) * 10
                logger.warning(f"SSL错误，等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
            except ConnectionError as e:
                # 连接错误（包括 WinError 10053），增加等待时间
                wait_time = (attempt + 1) * 15
                logger.warning(f"连接错误，等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
            except RequestException as e:
                logger.error(f"请求异常: {e}")
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(5)

        return None

    def _extract_journal_code(self, detail_url: str) -> Optional[str]:
        """
        从 detail_url 中提取期刊代码

        使用 Playwright 模拟浏览器点击流程：
        1. 打开期刊详情页
        2. 点击 #selectprograma 元素
        3. 点击 #recentThree 元素
        4. 拦截网络请求获取期刊代码

        Args:
            detail_url: CNKI 期刊详情页 URL

        Returns:
            期刊代码，如 'ZGFX'（中国法学）
        """
        # 首先尝试从 URL 中直接提取
        match = re.search(r'/journals/([A-Z]+)/', detail_url)
        if match:
            return match.group(1)

        # 使用 Playwright 动态提取
        try:
            logger.info(f"使用 Playwright 提取期刊代码: {detail_url[:60]}...")
            result = extract_journal_code_sync(detail_url)

            if result.get('journal_code'):
                logger.info(f"成功提取期刊代码: {result['journal_code']}")
                return result['journal_code']
            elif result.get('error'):
                logger.warning(f"Playwright 提取失败: {result['error']}")
        except Exception as e:
            logger.warning(f"Playwright 提取期刊代码异常: {e}")

        return None

    def fetch_journal_columns(self, journal_code: str) -> Optional[list]:
        """
        获取期刊栏目列表

        Args:
            journal_code: 期刊代码，如 'ZGFX'

        Returns:
            栏目名称列表，失败返回 None
        """
        columns_url = f"https://kns.cnki.net/openapi/index-dataset-api/report/journals/{journal_code}/columns?year=3&lang=CHS"

        try:
            headers = self._get_random_headers()
            headers.update({
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Connection': 'keep-alive',
                'Origin': 'https://navi.cnki.net',
                'Referer': 'https://navi.cnki.net/',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site',
            })

            response = self.session.get(columns_url, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0:
                    columns_data = data.get('data', [])
                    # 提取栏目名称
                    columns = [item.get('title', '') for item in columns_data if item.get('title')]
                    logger.info(f"成功获取期刊 {journal_code} 的 {len(columns)} 个栏目")
                    return columns
                else:
                    logger.warning(f"API返回错误: {data.get('message')}")
                    return None
            else:
                logger.warning(f"获取栏目失败: HTTP {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"获取栏目异常: {e}")
            return None

    def parse_detail_page(self, detail_url: str) -> Dict[str, Any]:
        """
        解析单个期刊详情页

        Args:
            detail_url: CNKI 期刊详情页 URL

        Returns:
            包含提取字段的字典，失败时包含 'error' 键
        """
        if not detail_url:
            return {'error': 'detail_url 为空'}

        response = self._fetch_with_retry(detail_url)
        if not response:
            return {'error': '请求失败'}

        try:
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')

            # 查找期刊信息容器（多种可能的结构）
            dd = soup.find('dl', class_='journalInfo')
            if not dd:
                # 尝试其他可能的结构
                dd = soup.find('dd', class_='journal-info')
            if not dd:
                # 尝试任何包含期刊信息的 dd
                all_dd = soup.find_all('dd')
                for d in all_dd:
                    text = d.get_text(strip=True)
                    if len(text) > 50 and ('主办单位' in text or '出版周期' in text):
                        dd = d
                        break

            if not dd:
                logger.info(f"无法找到期刊信息容器，页面可能已失效")
                return {'error': '无法找到期刊信息'}

            text = dd.get_text(separator=' ', strip=True)
            info = {}

            # 逐个匹配字段
            for field, pattern in self.PATTERNS.items():
                match = re.search(pattern, text)
                if match:
                    value = match.group(1).strip()
                    # 清理前导符号
                    value = re.sub(r'^[:：\s]+', '', value)

                    # 数字字段处理
                    if field in ['创刊时间', '出版文献量', '总下载次数', '总被引次数']:
                        value = value.replace(',', '')
                        if value.isdigit():
                            info[self.FIELD_MAPPING[field]] = int(value)
                    else:
                        info[self.FIELD_MAPPING[field]] = value

            # 专门处理专辑名称和专题名称（使用更精确的解析）
            # 格式可能是: "专辑名称：社会科学Ⅰ辑；专题名称：中国政治和国际政治"
            if '专辑名称：' in text or '专辑名称:' in text:
                # 先尝试找"专辑名称："
                album_match = re.search(r'专辑名称[::：]\s*([^；;]+?)(?:[；;]|\s*(?:专题名称|$))', text)
                if album_match:
                    info['field'] = album_match.group(1).strip()

            if '专题名称：' in text or '专题名称:' in text:
                # 找"专题名称："
                subject_match = re.search(r'专题名称[::：]\s*([^；;]+?)(?:[；;]|\s*$)', text)
                if subject_match:
                    info['subfield'] = subject_match.group(1).strip()

            # 提取专辑名称和专题名称（使用专门的 HTML 元素）
            # 专辑名称 <span id="jiName"> = 一级学科 (field)
            # 专题名称 <span id="tiName"> = 二级学科 (subfield)
            ji_name_span = soup.find('span', id='jiName')
            if ji_name_span:
                info['field'] = ji_name_span.get_text(strip=True)

            ti_name_span = soup.find('span', id='tiName')
            if ti_name_span:
                info['subfield'] = ti_name_span.get_text(strip=True)

            # 提取期刊标签
            journal_type2 = soup.find('p', class_='journalType2')
            if journal_type2:
                tags_text = journal_type2.get_text(strip=True)
                info['journal_tags'] = tags_text.split()

            # 添加更新时间
            info['cnki_detail_last_updated'] = datetime.now()

            # 检查是否至少提取到一些有效信息
            if len(info) <= 1:  # 只有更新时间，没有其他信息
                logger.info(f"页面内容过短，未提取到有效信息")
                return {'error': '页面内容无效或结构异常'}

            # 输出解析结果（使用 INFO 级别，无论是否 verbose）
            field_info = f"field={info.get('field')}, subfield={info.get('subfield')}"
            logger.info(f"解析结果: {field_info}")

            return info

        except Exception as e:
            logger.error(f"解析失败 {detail_url}: {e}")
            return {'error': str(e)}

    def update_journal(self, journal_id: int, delay: bool = True) -> bool:
        """
        更新单个期刊的 CNKI 详情

        Args:
            journal_id: 期刊 ID
            delay: 是否添加随机延迟（批量更新时为 True）

        Returns:
            是否更新成功
        """
        journal = self.db.query(Journal).filter(Journal.id == journal_id).first()
        if not journal:
            logger.warning(f"期刊 ID {journal_id} 不存在")
            self.stats['failed'] += 1
            return False

        if not journal.detail_url:
            logger.warning(f"期刊 {journal.name} 没有 detail_url")
            self.stats['skipped'] += 1
            return False

        # 添加随机延迟
        if delay:
            self._random_delay()

        info = self.parse_detail_page(journal.detail_url)
        if 'error' in info:
            logger.warning(f"期刊 {journal.name} 解析失败: {info['error']}")
            # 即使解析失败，也更新时间戳，避免重复尝试
            try:
                journal.cnki_detail_last_updated = datetime.now()
                self.db.commit()
            except:
                self.db.rollback()
            self.stats['failed'] += 1
            return False

        # 更新详情页基本信息（field、subfield等，不含栏目）
        for key, value in info.items():
            if key != 'error' and hasattr(journal, key):
                setattr(journal, key, value)

        try:
            self.db.commit()
            self.stats['success'] += 1
            logger.info(f"成功更新期刊: {journal.name}")
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"数据库更新失败 {journal.name}: {e}")
            self.stats['failed'] += 1
            return False

    def batch_update(
        self,
        limit: Optional[int] = None,
        force: bool = False,
        skip_days: int = 7
    ) -> Dict[str, int]:
        """
        批量更新期刊详情

        Args:
            limit: 限制更新数量
            force: 是否强制更新（忽略更新时间）
            skip_days: 增量更新模式下，跳过 N 天内已更新的期刊

        Returns:
            统计信息字典
        """
        # 构建查询
        query = self.db.query(Journal).filter(Journal.detail_url.isnot(None))

        # 非强制模式下，跳过已有 field（一级学科）数据的期刊
        # 同时跳过最近 10 分钟内更新的期刊（断点续传安全窗口）
        if not force:
            safe_window = datetime.now() - timedelta(minutes=10)
            query = query.filter(
                (Journal.field.is_(None)) &
                ((Journal.cnki_detail_last_updated.is_(None)) | (Journal.cnki_detail_last_updated < safe_window))
            )

        if limit:
            query = query.limit(limit)

        journals = query.all()
        self.stats['total'] = len(journals)

        logger.info(f"开始批量更新，共 {len(journals)} 个期刊")
        logger.info(f"延迟设置: {self.min_delay}-{self.max_delay} 秒")

        for i, journal in enumerate(journals, 1):
            logger.info(f"[{i}/{len(journals)}] 更新: {journal.name}")
            self.update_journal(journal.id, delay=True)

        return self.stats

    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self.stats.copy()

    def reset_stats(self):
        """重置统计信息"""
        self.stats = {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0}

    def __del__(self):
        """清理资源"""
        if hasattr(self, 'session'):
            self.session.close()
