"""
CNKI期刊抓取（支持手动验证）

特性：
- headful模式，支持手动完成滑块验证
- 验证通过后自动翻页抓取
- 直接写入数据库

使用方法:
    python scripts/fetch_journals_with_verification.py --db
"""

import asyncio
import sys
import os
import argparse
import json
import re
from typing import Dict, List, Optional
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 导入模型
from app.models.journal import Journal


class CNKIJournalFetcher:
    """CNKI期刊抓取器（支持手动验证）"""

    def __init__(self, headless: bool = False, use_db: bool = False, db_url: str = None, click_name: str = ''):
        self.headless = headless
        self.use_db = use_db
        self.click_name = click_name
        self.db_session = None
        self.browser = None
        self.page = None
        self.journals = []
        self.stats = {"total_pages": 0, "success": 0, "failed": 0}

        if use_db:
            self._setup_database(db_url)

    def _setup_database(self, db_url: str = None):
        """设置数据库连接"""
        if not db_url:
            db_url = os.getenv('DATABASE_URL')
        if not db_url:
            print("[警告] 未设置 DATABASE_URL")
            self.use_db = False
            return
        try:
            engine = create_engine(db_url)
            SessionLocal = sessionmaker(bind=engine)
            self.db_session = SessionLocal()
            print("[数据库] 已连接")
        except Exception as e:
            print(f"[ERROR] 数据库连接失败: {e}")
            self.use_db = False

    def _save_journal_to_db(self, journal_data: Dict) -> bool:
        """保存单条期刊到数据库"""
        if not self.use_db or not self.db_session:
            return False
        try:
            existing = self.db_session.query(Journal).filter(
                Journal.name == journal_data['name']
            ).first()
            if existing:
                existing.is_cssci = journal_data.get('is_cssci', True)
                existing.source = 'CNKI'
            else:
                journal = Journal(
                    name=journal_data['name'],
                    is_cssci=journal_data.get('is_cssci', True),
                    issn=journal_data.get('issn'),
                    cn=journal_data.get('cn'),
                    publisher=journal_data.get('publisher'),
                    composite_impact_factor=journal_data.get('composite_impact_factor'),
                    comprehensive_impact_factor=journal_data.get('comprehensive_impact_factor'),
                    source='CNKI'
                )
                self.db_session.add(journal)
            self.db_session.commit()
            return True
        except Exception as e:
            self.db_session.rollback()
            print(f"  [DB ERROR] {e}")
            return False

    def close_db(self):
        if self.db_session:
            self.db_session.close()

    def _parse_journals_from_html(self, html: str) -> List[Dict]:
        """从HTML中解析期刊列表"""
        journals = []
        # 匹配期刊条目
        pattern = r'<a[^>]*href="https://navi\.cnki\.net/knavi/detail\?p=([^"]+)"[^>]*title="([^"]+)"[^>]*>.*?<div class="detials">\s*<h1>\s*([^<]+)</h1>(.*?)</div>\s*</a>'
        matches = re.findall(pattern, html, re.DOTALL)

        for match in matches:
            encoded_url, title_attr, name, details_html = match
            journal = {
                'name': name.strip(),
                'detail_url': f"https://navi.cnki.net/knavi/detail?p={encoded_url}",
            }

            # 提取标签
            tags = re.findall(r'<span>([^<]+)</span>', details_html)
            journal['tags'] = [t.strip() for t in tags]

            # 提取影响因子
            cf_match = re.search(r'复合影响因子[：:]([\d.]+)', details_html)
            if cf_match:
                journal['composite_impact_factor'] = float(cf_match.group(1))

            ci_match = re.search(r'综合影响因子[：:]([\d.]+)', details_html)
            if ci_match:
                journal['comprehensive_impact_factor'] = float(ci_match.group(1))

            # 提取ISSN
            issn_match = re.search(r'ISSN[：:]([\dA-Z\-]+)', details_html)
            if issn_match:
                journal['issn'] = issn_match.group(1).strip()

            # 提取CN
            cn_match = re.search(r'CN[：:]([\dA-Z\-/]+)', details_html)
            if cn_match:
                journal['cn'] = cn_match.group(1).strip()

            # 提取主办单位
            pub_match = re.search(r'主办单位[：:]([^<]+)', details_html)
            if pub_match:
                journal['publisher'] = pub_match.group(1).strip()

            journals.append(journal)

        return journals

    async def _wait_for_verification(self, timeout: int = 300):
        """等待用户完成验证"""
        print("\n[验证] 检测到安全验证页面，请手动完成滑块验证...")
        print("[验证] 完成后页面会自动加载期刊列表")
        print(f"[验证] 等待时间: 最多 {timeout} 秒\n")

        for i in range(timeout):
            await asyncio.sleep(1)
            try:
                title = await self.page.title()
                if '验证' not in title and '安全' not in title and title.strip():
                    print(f"[验证] 验证已通过! 当前页面: {title}")
                    # 额外等待页面加载
                    await asyncio.sleep(3)
                    return True
            except:
                pass
            if i % 10 == 0 and i > 0:
                print(f"[验证] 已等待 {i} 秒，请完成验证...")

        print("[验证] 等待超时")
        return False

    async def _fetch_page(self, page_num: int) -> Optional[str]:
        """获取指定页"""
        try:
            result = await self.page.evaluate("""
                async (args) => {
                    const pageNum = args.pageNum;
                    const clickName = args.clickName;
                    const params = {
                        searchStateJson: JSON.stringify({
                            "StateID": "", "Platfrom": "", "QueryTime": "",
                            "Account": "knavi", "ClientToken": "", "Language": "",
                            "CNode": {"PCode": "OYXNO5VW", "SMode": "", "OperateT": ""},
                            "QNode": {"SelectT": "", "Select_Fields": "", "S_DBCodes": "",
                                      "Subscribed": "", "QGroup": [], "OrderBy": "OTA|DESC",
                                      "GroupBy": "", "Additon": ""}
                        }),
                        displaymode: '1',
                        pageindex: String(pageNum),
                        pagecount: '21',
                        index: 'JSTMWT6S',
                        searchType: '刊名(曾用刊名)',
                        parentcode: 'SQN63324',
                        switchdata: 'clickTabSearch'
                    };
                    if (clickName) params.clickName = clickName;

                    const body = Object.keys(params)
                        .map(key => encodeURIComponent(key) + '=' + encodeURIComponent(params[key]))
                        .join('&');

                    try {
                        const response = await fetch('https://navi.cnki.net/knavi/journals/searchbaseinfo', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'X-Requested-With': 'XMLHttpRequest'
                            },
                            body: body
                        });
                        return {status: response.status, ok: response.ok, text: await response.text()};
                    } catch(e) {
                        return {error: e.message};
                    }
                }
            """, {"pageNum": page_num, "clickName": self.click_name or ''})

            if result.get('ok') and result.get('text'):
                return result['text']
            else:
                print(f"  [WARN] 第{page_num}页返回异常: {result}")
                return None
        except Exception as e:
            print(f"  [ERROR] 第{page_num}页请求失败: {e}")
            return None

    def _parse_total_pages(self, html: str) -> int:
        """从HTML中解析总页数"""
        match = re.search(r'pageCount[\s\:\=]+(\d+)', html)
        if match:
            return int(match.group(1))
        match = re.search(r'lblPageCount[\s\>]*([\d]+)', html)
        if match:
            return int(match.group(1))
        return 0

    async def fetch_journals(self, max_pages: Optional[int] = None):
        """主抓取流程"""
        print("=" * 70)
        print("CNKI 期刊抓取（支持手动验证）")
        print("=" * 70)

        async with async_playwright() as p:
            self.browser = await p.chromium.launch(
                headless=self.headless,
                args=['--disable-blink-features=AutomationControlled',
                      '--disable-dev-shm-usage', '--no-sandbox']
            )
            context = await self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN', timezone_id='Asia/Shanghai'
            )
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            """)
            self.page = await context.new_page()
            self.page.set_default_timeout(60000)

            print("\n[步骤1] 访问 CNKI 期刊导航页面...")
            await self.page.goto(
                "https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT",
                wait_until='domcontentloaded'
            )
            await asyncio.sleep(3)

            title = await self.page.title()
            print(f"[步骤1] 页面标题: {title}")

            # 检查是否需要验证
            if '验证' in title or '安全' in title or not title.strip():
                success = await self._wait_for_verification(timeout=300)
                if not success:
                    print("[FAIL] 验证未完成，退出")
                    await self.browser.close()
                    return

            # 如果指定了 click_name，模拟点击筛选
            if self.click_name:
                print(f"\n[步骤2] 点击筛选: {self.click_name}")
                try:
                    await self.page.evaluate(f"""
                        () => {{
                            const links = document.querySelectorAll('a');
                            for (const link of links) {{
                                if (link.textContent.includes('{self.click_name}')) {{
                                    link.click();
                                    return true;
                                }}
                            }}
                            return false;
                        }}
                    """)
                    await asyncio.sleep(3)
                except Exception as e:
                    print(f"[WARN] 点击筛选失败: {e}")

            # 开始抓取
            print("\n[步骤3] 开始抓取期刊数据...")
            html = await self._fetch_page(1)
            if not html:
                print("[FAIL] 无法获取第一页数据")
                await self.browser.close()
                return

            total_pages = self._parse_total_pages(html)
            self.stats["total_pages"] = total_pages
            if max_pages:
                total_pages = min(total_pages, max_pages)

            print(f"  总页数: {total_pages}")

            # 解析第一页
            journals = self._parse_journals_from_html(html)
            self.journals.extend(journals)
            print(f"  第1页: {len(journals)} 本期刊")
            if self.use_db:
                for j in journals:
                    self._save_journal_to_db(j)

            # 翻页
            for page_num in range(2, total_pages + 1):
                delay = 2 + (page_num % 3)
                print(f"  等待 {delay} 秒...")
                await asyncio.sleep(delay)

                html = await self._fetch_page(page_num)
                if html:
                    page_journals = self._parse_journals_from_html(html)
                    self.journals.extend(page_journals)
                    print(f"  第{page_num}页: {len(page_journals)} 本期刊")
                    if self.use_db:
                        for j in page_journals:
                            self._save_journal_to_db(j)
                    self.stats["success"] += 1
                else:
                    print(f"  [FAIL] 第{page_num}页获取失败")
                    self.stats["failed"] += 1

            print(f"\n[完成] 共抓取 {len(self.journals)} 本期刊")
            print(f"  成功页数: {self.stats['success']}")
            print(f"  失败页数: {self.stats['failed']}")

            await self.browser.close()


async def main():
    parser = argparse.ArgumentParser(description='CNKI期刊抓取（支持手动验证）')
    parser.add_argument('--db', action='store_true', help='写入数据库')
    parser.add_argument('--headless', action='store_true', help='无头模式（不推荐，可能触发验证）')
    parser.add_argument('--max-pages', type=int, default=None, help='最大抓取页数')
    parser.add_argument('--click-name', type=str, default='', help='筛选名称（如 CSSCI 中文社会科学引文索引）')
    args = parser.parse_args()

    fetcher = CNKIJournalFetcher(
        headless=args.headless,
        use_db=args.db,
        click_name=args.click_name
    )

    try:
        await fetcher.fetch_journals(max_pages=args.max_pages)
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")
    finally:
        fetcher.close_db()


if __name__ == '__main__':
    asyncio.run(main())
