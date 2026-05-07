"""
CNKI 期刊代码提取服务（使用 Playwright）

通过模拟浏览器点击流程提取期刊代码
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class CNKIJournalCodeExtractor:
    """CNKI 期刊代码提取器（使用 Playwright）"""

    def __init__(self, headless: bool = True, timeout: int = 30000):
        """
        初始化提取器

        Args:
            headless: 是否使用无头模式
            timeout: 超时时间（毫秒）
        """
        self.headless = headless
        self.timeout = timeout

    async def extract_journal_code(self, detail_url: str) -> Dict[str, Any]:
        """
        从 CNKI 详情页提取期刊代码

        Args:
            detail_url: CNKI 期刊详情页 URL

        Returns:
            包含 journal_code 和 columns 的字典
        """
        result = {
            'journal_code': None,
            'columns': None,
            'columns_detail': None,
            'error': None
        }

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=['--disable-blink-features=AutomationControlled']
                )

                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36'
                )

                page = await context.new_page()

                # 监听网络请求
                def log_request(request):
                    url = request.url
                    if '/openapi/index-dataset-api/report/journals/' in url and '/columns' in url:
                        import re
                        match = re.search(r'/journals/([A-Z]+)/columns', url)
                        if match and not result['journal_code']:
                            result['journal_code'] = match.group(1)
                            logger.info(f"捕获到期刊代码: {result['journal_code']}")

                page.on('request', log_request)

                # 访问详情页
                await page.goto(detail_url, timeout=self.timeout, wait_until='networkidle')
                await page.wait_for_timeout(2000)

                # 点击 #selectprograma
                try:
                    await page.click('#selectprograma', timeout=5000)
                    await page.wait_for_timeout(1000)
                except:
                    pass

                # 查找并点击 #recentThree
                try:
                    recent_three = await page.query_selector('#recentThree')
                    if recent_three:
                        await recent_three.click()
                        await page.wait_for_timeout(2000)
                except:
                    pass

                # 等待可能的 API 请求
                await page.wait_for_timeout(3000)

                # 如果获取到期刊代码，获取栏目
                if result['journal_code']:
                    columns_result = await self._fetch_columns(page, result['journal_code'])
                    result['columns'] = columns_result.get('titles')
                    result['columns_detail'] = columns_result.get('detail')

                await browser.close()

        except Exception as e:
            result['error'] = str(e)
            logger.error(f"提取期刊代码失败: {e}")

        return result

    async def _fetch_columns(self, page, journal_code: str) -> Dict[str, Any]:
        """
        获取期刊栏目列表

        Returns:
            {
                'titles': ['栏目1', '栏目2', ...],
                'detail': [{'param': '...', 'title': '...', 'value': '...'}, ...]
            }
        """
        try:
            columns_url = f"https://kns.cnki.net/openapi/index-dataset-api/report/journals/{journal_code}/columns?year=3&lang=CHS"

            response = await page.request.get(columns_url)
            if response.ok:
                data = await response.json()
                if data.get('code') == 0:
                    columns_data = data.get('data', [])
                    titles = [item.get('title', '') for item in columns_data if item.get('title')]
                    detail = [
                        {
                            'param': item.get('param', ''),
                            'title': item.get('title', ''),
                            'value': item.get('value', '')
                        }
                        for item in columns_data
                    ]
                    logger.info(f"获取到 {len(titles)} 个栏目")
                    return {'titles': titles, 'detail': detail}
        except Exception as e:
            logger.error(f"获取栏目失败: {e}")

        return {'titles': None, 'detail': None}


# 全局实例
_extractor_instance = None


def get_extractor() -> CNKIJournalCodeExtractor:
    """获取提取器实例（单例）"""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = CNKIJournalCodeExtractor(headless=True)
    return _extractor_instance


def extract_journal_code_sync(detail_url: str) -> Dict[str, Any]:
    """
    同步版本的期刊代码提取函数

    Args:
        detail_url: CNKI 期刊详情页 URL

    Returns:
        包含 journal_code 和 columns 的字典
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    extractor = get_extractor()
    return loop.run_until_complete(extractor.extract_journal_code(detail_url))
