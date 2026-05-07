"""
论文获取相关的 Celery 任务

包含按栏目获取论文、去重处理等功能。
"""

import asyncio
import aiohttp
import re
import random
from bs4 import BeautifulSoup
from app.tasks.celery_app import celery_app
from app.tasks.base import DatabaseTask, update_task_status
from app.models.journal import Journal, Literature
from app.models.user import User
from typing import AsyncIterator, Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# 常量配置
DEFAULT_MAX_PAPERS = 500
MAX_MAX_PAPERS = 5000
BATCH_COMMIT_SIZE = 50  # 每50篇提交一次


def get_max_papers(user: User) -> int:
    """根据用户角色获取最大获取数量"""
    limits = {
        'free': 200,
        'pro': 1000,
        'vip': 5000
    }
    return limits.get(user.role, DEFAULT_MAX_PAPERS)


def extract_cnki_id(detail_url: str) -> str:
    """
    从 detail_url 提取 CNKI ID

    示例: /knavi/detail?p=XXX&... → XXX
    """
    match = re.search(r'[?&]p=([^&]+)', detail_url)
    return match.group(1) if match else detail_url[:100]


def parse_year_issue(year_issue: str) -> Tuple[Optional[int], Optional[str]]:
    """
    解析年/期字符串

    示例: "2024/05" → (2024, "05")
    """
    if not year_issue:
        return None, None

    if '/' in year_issue:
        parts = year_issue.split('/')
        year = int(parts[0]) if parts[0].isdigit() else None
        issue = parts[1] if len(parts) > 1 else None
        return year, issue

    match = re.match(r'(\d{4})年(\d+)期', year_issue)
    if match:
        return int(match.group(1)), match.group(2)

    return None, None


@celery_app.task(
    base=DatabaseTask,
    bind=True,
    max_retries=3
)
def fetch_papers_by_column_task(
    self,
    journal_id: int,
    column_name: str,
    user_id: int,
    fetch_details: bool = False,  # Phase 2: 是否获取详情
    max_papers: int = None
):
    """
    按栏目获取论文（带去重和批量提交）

    Args:
        journal_id: 期刊ID
        column_name: 栏目名称
        user_id: 用户ID
        fetch_details: 是否获取论文详情（Phase 2功能）
        max_papers: 最大获取数量（受用户角色限制）
    """
    task_id = self.request.id

    # 获取用户和限制
    user = self.db.query(User).filter(User.id == user_id).first()
    if not user:
        update_task_status(task_id, status='FAILURE', error=f"用户 {user_id} 不存在")
        return

    actual_max = min(
        max_papers or DEFAULT_MAX_PAPERS,
        get_max_papers(user),
        MAX_MAX_PAPERS
    )

    # 获取期刊信息
    journal = self.db.query(Journal).filter(Journal.id == journal_id).first()
    if not journal:
        update_task_status(task_id, status='FAILURE', error=f"期刊 {journal_id} 不存在")
        return

    if not journal.journal_code:
        update_task_status(task_id, status='FAILURE', error="该期刊没有 journal_code")
        return

    update_task_status(
        task_id,
        status='STARTED',
        progress={
            'current': 0,
            'total': 'unknown',
            'message': f'开始获取栏目 "{column_name}" 的论文...'
        }
    )

    try:
        fetcher = CNKIColumnPaperFetcher()
        papers_buffer = []
        papers_fetched = 0
        papers_skipped = 0

        async def fetch_and_save():
            nonlocal papers_buffer, papers_fetched, papers_skipped

            async for paper, current, estimated_total in fetcher.fetch_papers_async(
                journal_code=journal.journal_code,
                column_name=column_name,
                max_papers=actual_max
            ):
                # 提取 cnki_id（用于去重）
                cnki_id = extract_cnki_id(paper.get('detail_url', ''))

                # 检查是否已存在
                existing = self.db.query(Literature).filter(
                    Literature.cnki_id == cnki_id
                ).first()

                if existing:
                    papers_skipped += 1
                else:
                    # 解析年/期
                    year, issue = parse_year_issue(paper.get('year_issue', ''))

                    create_kwargs = {
                        'title': paper['title'],
                        'authors': paper.get('authors'),
                        'detail_url': paper.get('detail_url'),
                        'year_issue': paper.get('year_issue'),
                        'year': year,
                        'journal_id': journal.id,
                        'journal_name': journal.name,
                        'column_name': column_name,
                        'cnki_id': cnki_id,
                        'citation_count': paper.get('citation_count', 0),
                        'download_count': paper.get('download_count', 0),
                        'source': 'CNKI'
                    }

                    literature = Literature(**create_kwargs)
                    papers_buffer.append(literature)
                    papers_fetched += 1

                # 批量提交
                total_processed = papers_fetched + papers_skipped
                if len(papers_buffer) >= BATCH_COMMIT_SIZE or total_processed % 20 == 0:
                    if papers_buffer:
                        self.db.bulk_save_objects(papers_buffer)
                        papers_buffer.clear()

                    self.db.commit()

                    update_task_status(task_id, progress={
                        'current': total_processed,
                        'total': estimated_total or 'unknown',
                        'message': f'已处理 {total_processed} 篇（新增 {papers_fetched}，跳过 {papers_skipped}）',
                        'last_paper': paper.get('title', '')[:50]
                    })

                # 延迟避免封禁
                await asyncio.sleep(1.5)

            # 最终提交
            if papers_buffer:
                self.db.bulk_save_objects(papers_buffer)
                papers_buffer.clear()

            self.db.commit()

        asyncio.run(fetch_and_save())

        update_task_status(
            task_id,
            status='SUCCESS',
            progress={
                'current': papers_fetched + papers_skipped,
                'total': papers_fetched + papers_skipped,
                'message': '完成'
            },
            result={
                'journal_id': journal_id,
                'journal_name': journal.name,
                'column_name': column_name,
                'papers_fetched': papers_fetched,
                'papers_skipped': papers_skipped,
                'total_processed': papers_fetched + papers_skipped
            }
        )

        return {'fetched': papers_fetched, 'skipped': papers_skipped}

    except Exception as e:
        self.db.rollback()
        logger.error(f"获取论文失败: {e}", exc_info=True)
        update_task_status(
            task_id,
            status='FAILURE',
            error=str(e)
        )
        raise


class CNKIColumnPaperFetcher:
    """CNKI 栏目论文获取器（带反爬虫策略）"""

    def __init__(self):
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0',
        ]

    def _get_random_headers(self) -> dict:
        """获取随机请求头"""
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://navi.cnki.net/',
        }

    async def fetch_papers_async(
        self,
        journal_code: str,
        column_name: str,
        max_papers: int = 500
    ) -> AsyncIterator[Tuple[Dict, int, int]]:
        """
        异步获取论文（带反爬虫策略）

        Yields:
            (论文信息, 当前序号, 估算总数)
        """
        pidx = 1
        total_fetched = 0
        consecutive_failures = 0
        max_failures = 3

        while total_fetched < max_papers and consecutive_failures < max_failures:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"https://navi.cnki.net/knavi/journals/{journal_code}/columns/papers",
                        headers=self._get_random_headers(),
                        data={
                            "pcode": "CJFD,CCJD",
                            "year": "3",
                            "colLayer": column_name,
                            "orderBy": "RET|DESC",
                            "pidx": str(pidx)
                        },
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status != 200:
                            logger.warning(f"HTTP {response.status} on page {pidx}")
                            consecutive_failures += 1
                            await asyncio.sleep(5)
                            continue

                        html = await response.text()

                papers, total_pages = self._parse_papers(html)

                if not papers:
                    consecutive_failures += 1
                    if consecutive_failures >= 2:
                        break
                    await asyncio.sleep(3)
                    continue

                consecutive_failures = 0

                for paper in papers:
                    if total_fetched >= max_papers:
                        break
                    yield paper, total_fetched + 1, total_pages * 20
                    total_fetched += 1

                if pidx >= total_pages:
                    break

                pidx += 1

                # 随机延迟
                delay = random.uniform(1.5, 2.5)
                await asyncio.sleep(delay)

            except asyncio.TimeoutError:
                logger.error(f"Timeout on page {pidx}")
                consecutive_failures += 1
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error on page {pidx}: {e}")
                consecutive_failures += 1
                await asyncio.sleep(5)

        if consecutive_failures >= max_failures:
            logger.warning(f"Stopped after {max_failures} consecutive failures")

    def _parse_papers(self, html: str) -> Tuple[List[Dict], int]:
        """解析论文列表 HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        papers = []

        # 获取总页数
        total_pages = 1
        count_elem = soup.select_one('#partiallistcount2')
        if count_elem:
            try:
                total_count = int(count_elem.text.strip())
                total_pages = max(1, (total_count + 19) // 20)
            except (ValueError, AttributeError):
                pass

        # 解析每一行论文
        for row in soup.select('tr[class="bgcGray"], tr:not([class])'):
            title_link = row.select_one('td.name a')
            if not title_link:
                continue

            # 提取 href（可能是相对路径）
            href = title_link.get('href', '')
            if href and not href.startswith('http'):
                href = f"https://navi.cnki.net{href}"

            paper = {
                'title': title_link.text.strip(),
                'detail_url': href,
                'authors': self._get_text(row.select_one('td.author')),
                'year_issue': self._get_text(row.select_one('td.yearTime')),
                'citation_count': self._parse_int(row.select_one('td.citedCount')),
                'download_count': self._parse_int(row.select_one('td.downCount')),
            }

            papers.append(paper)

        return papers, total_pages

    def _parse_int(self, element) -> int:
        """安全解析整数"""
        if element is None:
            return 0
        try:
            return int(element.text.strip())
        except (ValueError, AttributeError):
            return 0

    def _get_text(self, element) -> str:
        """安全获取元素文本"""
        if element is None:
            return ''
        try:
            return element.text.strip()
        except AttributeError:
            return ''
