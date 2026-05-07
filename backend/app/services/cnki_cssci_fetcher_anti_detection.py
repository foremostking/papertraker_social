"""
CNKI CSSCI期刊抓取器 - 增强版（含反爬虫策略）

关键特性：
- 随机延迟和User-Agent轮换
- 重试机制与指数退避
- 检查点恢复
- 人类行为模拟
- 请求限流
- 支持直接写入数据库
"""

import asyncio
import json
import re
import random
import os
import time
from typing import Dict, List, Optional
from playwright.async_api import async_playwright, Page, Browser
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class CNKICSSCIFetcherAntiDetection:
    """CNKI CSSCI期刊抓取器 - 反爬虫增强版"""

    # User-Agent池 - 轮换使用
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
    ]

    def __init__(self, headless: bool = True, use_db: bool = False, db_url: str = None,
                 click_name: Optional[str] = 'CSSCI 中文社会科学引文索引'):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.journals: List[Dict] = []
        self.click_name = click_name  # 期刊类别筛选参数，为空则获取全部期刊
        self.stats = {
            "total_pages": 0,
            "total_journals": 0,
            "retry_count": 0,
            "failed_pages": [],
            "added_to_db": 0,
            "updated_in_db": 0
        }

        # 延迟配置（秒）
        self.min_delay = 1.5
        self.max_delay = 4.0

        # 重试配置
        self.max_retries = 3
        self.retry_base_delay = 2  # 指数退避基础延迟

        # 检查点配置
        self.checkpoint_interval = 5  # 每5页保存一次
        self.checkpoint_file = "data/journals/cssci_checkpoint.json"

        # 恢复模式
        self.resume_from_checkpoint = False
        self.start_page = 1

        # 数据库配置
        self.use_db = use_db
        self.db_session = None
        if use_db:
            self._setup_database(db_url)

    def _setup_database(self, db_url: str = None):
        """设置数据库连接"""
        try:
            from app.models.journal import Journal as JournalModel
            import os
            from dotenv import load_dotenv

            load_dotenv()
            self.JournalModel = JournalModel

            if db_url:
                database_url = db_url
            else:
                database_url = os.getenv('DATABASE_URL')

            if not database_url:
                print("[警告] 未设置DATABASE_URL环境变量")
                print("[警告] 将使用JSON模式")
                self.use_db = False
                return

            engine = create_engine(database_url)
            SessionLocal = sessionmaker(bind=engine)
            self.db_session = SessionLocal()

            print("[数据库] 已连接")
        except ImportError as e:
            print(f"[警告] 无法导入数据库模块: {e}")
            print("[警告] 将使用JSON模式")
            self.use_db = False
        except Exception as e:
            print(f"[警告] 数据库连接失败: {e}")
            print("[警告] 将使用JSON模式")
            self.use_db = False

    def _save_journal_to_db(self, journal_data: Dict) -> bool:
        """将单条期刊数据保存到数据库"""
        if not self.use_db or not self.db_session:
            return False

        try:
            # 查找是否已存在
            existing = self.db_session.query(self.JournalModel).filter(
                self.JournalModel.name == journal_data['name']
            ).first()

            if existing:
                # 更新
                existing.issn = journal_data.get('issn')
                existing.cn = journal_data.get('cn')
                existing.publisher = journal_data.get('publisher')
                existing.composite_impact_factor = float(journal_data['composite_impact_factor']) if journal_data.get('composite_impact_factor') else None
                existing.comprehensive_impact_factor = float(journal_data['comprehensive_impact_factor']) if journal_data.get('comprehensive_impact_factor') else None
                existing.is_network_first = journal_data.get('is_network_first', False)
                existing.is_enhanced_publishing = journal_data.get('is_enhanced_publishing', False)
                existing.detail_url = journal_data.get('detail_url')
                existing.is_cssci = journal_data.get('is_cssci', True)
                existing.cssci_year = journal_data.get('cssci_year')
                existing.source = journal_data.get('source')
                self.stats["updated_in_db"] += 1
            else:
                # 新增
                journal = self.JournalModel(
                    name=journal_data['name'],
                    issn=journal_data.get('issn'),
                    cn=journal_data.get('cn'),
                    publisher=journal_data.get('publisher'),
                    composite_impact_factor=float(journal_data['composite_impact_factor']) if journal_data.get('composite_impact_factor') else None,
                    comprehensive_impact_factor=float(journal_data['comprehensive_impact_factor']) if journal_data.get('comprehensive_impact_factor') else None,
                    is_network_first=journal_data.get('is_network_first', False),
                    is_enhanced_publishing=journal_data.get('is_enhanced_publishing', False),
                    detail_url=journal_data.get('detail_url'),
                    is_cssci=journal_data.get('is_cssci', True),
                    cssci_year=journal_data.get('cssci_year'),
                    source=journal_data.get('source')
                )
                self.db_session.add(journal)
                self.stats["added_to_db"] += 1

            self.db_session.commit()
            return True

        except Exception as e:
            self.db_session.rollback()
            print(f"  [ERROR] 数据库保存失败: {e}")
            return False

    def close_db(self):
        """关闭数据库连接"""
        if self.db_session:
            self.db_session.close()
            self.db_session = None

    def _random_delay(self, multiplier: float = 1.0):
        """生成随机延迟时间"""
        base_delay = random.uniform(self.min_delay, self.max_delay)
        return base_delay * multiplier

    def _get_random_user_agent(self) -> str:
        """获取随机User-Agent"""
        return random.choice(self.USER_AGENTS)

    async def _simulate_human_behavior(self):
        """模拟人类浏览行为"""
        try:
            # 随机滚动
            scroll_times = random.randint(1, 3)
            for _ in range(scroll_times):
                scroll_y = random.randint(100, 500)
                await self.page.evaluate(f"window.scrollBy(0, {scroll_y})")
                await asyncio.sleep(random.uniform(0.1, 0.3))

            # 滚回顶部
            await self.page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(random.uniform(0.2, 0.5))

        except Exception as e:
            # 模拟行为失败不影响主流程
            pass

    async def _check_checkpoint(self):
        """检查是否有检查点可恢复"""
        if not os.path.exists(self.checkpoint_file):
            return False

        try:
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if data.get('journals'):
                self.journals = data['journals']
                last_page = data.get('stats', {}).get('last_completed_page', 0)
                total_pages = data.get('stats', {}).get('total_pages', 0)

                print(f"\n[恢复] 发现检查点文件")
                print(f"  已抓取: {len(self.journals)} 本期刊")
                print(f"  上次完成到: 第 {last_page} 页")
                print(f"  总页数: {total_pages}")

                if last_page < total_pages:
                    self.start_page = last_page + 1
                    self.resume_from_checkpoint = True
                    return True

        except Exception as e:
            print(f"[WARN] 检查点文件损坏: {e}")

        return False

    async def fetch_cssci_journals(self, max_pages: Optional[int] = None) -> List[Dict]:
        """使用clickName参数获取CSSCI期刊"""

        print("=" * 70)
        print("CNKI CSSCI期刊抓取 (反爬虫增强版)")
        print("=" * 70)
        print("\n反爬虫策略:")
        print(f"  - 随机延迟: {self.min_delay}-{self.max_delay}秒")
        print(f"  - User-Agent池: {len(self.USER_AGENTS)}个")
        print(f"  - 最大重试: {self.max_retries}次")
        print(f"  - 检查点间隔: 每{self.checkpoint_interval}页")
        print("")

        # 检查检查点
        await self._check_checkpoint()

        if self.resume_from_checkpoint:
            print(f"[恢复] 从第{self.start_page}页继续抓取...\n")
        else:
            self.start_page = 1

        async with async_playwright() as p:
            # 使用随机User-Agent启动
            user_agent = self._get_random_user_agent()
            self.browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox'
                ]
            )

            context = await self.browser.new_context(
                user_agent=user_agent,
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN',
                timezone_id='Asia/Shanghai'
            )

            # 添加初始化脚本，隐藏自动化特征
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en']
                });
            """)

            self.page = await context.new_page()

            # 设置超时
            self.page.set_default_timeout(60000)
            self.page.set_default_navigation_timeout(60000)

            try:
                if not self.resume_from_checkpoint:
                    # 访问主页面（恢复时跳过）
                    print("[步骤1] 访问主页面...")
                    await self.page.goto(
                        "https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT",
                        wait_until='domcontentloaded'
                    )

                    # 初始延迟
                    initial_delay = self._random_delay(1.5)
                    print(f"  等待 {initial_delay:.1f} 秒...")
                    await asyncio.sleep(initial_delay)

                    # 模拟人类行为
                    await self._simulate_human_behavior()

                # 抓取所有页面
                if self.click_name:
                    print(f"\n[步骤2] 开始抓取期刊...")
                    print(f"  参数: clickName='{self.click_name}'\n")
                else:
                    print("\n[步骤2] 开始抓取全部期刊（无筛选）...\n")
                if self.use_db:
                    print("  模式: 数据库模式（直接写入数据库）")
                else:
                    print("  模式: JSON模式（保存到文件）")
                print("")

                await self._fetch_all_pages(max_pages)

                self.stats["total_journals"] = len(self.journals)

                # 清理检查点（成功完成后）
                if not self.stats.get("failed_pages"):
                    if os.path.exists(self.checkpoint_file):
                        os.remove(self.checkpoint_file)
                        print("\n[清理] 检查点文件已删除")

            except Exception as e:
                print(f"\n[ERROR] 抓取过程出错: {e}")
                import traceback
                traceback.print_exc()

                # 保存紧急检查点
                self._save_checkpoint()

            finally:
                await self.browser.close()
                self.close_db()  # 关闭数据库连接

        return self.journals

    async def _fetch_all_pages(self, max_pages: Optional[int]):
        """获取所有页面（带重试机制）"""

        total_pages = 0  # 初始化

        # 如果是恢复模式，需要先获取总页数
        if self.resume_from_checkpoint:
            # 只获取第一页来解析总页数
            html = await self._fetch_page_with_retry(1)
            if html:
                total_pages = self._parse_total_pages(html)
                self.stats["total_pages"] = total_pages
        else:
            # 获取第一页
            html = await self._fetch_page_with_retry(1)
            if not html:
                print("\n[ERROR] 无法获取第一页数据")
                return

            # 解析总页数
            total_pages = self._parse_total_pages(html)
            self.stats["total_pages"] = total_pages

        if max_pages:
            total_pages = min(total_pages, max_pages)

        print(f"  总页数: {total_pages}")
        print(f"  起始页: {self.start_page}")
        print("")

        # 确定起始页
        if self.resume_from_checkpoint and self.start_page > 1:
            page_range = range(self.start_page, total_pages + 1)
        else:
            # 解析第一页期刊
            journals = self._parse_journals_from_html(html)
            self.journals.extend(journals)
            print(f"  第1页: {len(journals)} 本期刊")
            page_range = range(2, total_pages + 1)

        # 翻页获取更多
        for page_num in page_range:
            delay = self._random_delay()
            print(f"  等待 {delay:.1f} 秒...", end=" ")
            await asyncio.sleep(delay)
            print("完成")

            html = await self._fetch_page_with_retry(page_num)

            if html:
                page_journals = self._parse_journals_from_html(html)
                self.journals.extend(page_journals)
                print(f"  第{page_num}页: {len(page_journals)} 本期刊")

                # 如果使用数据库，立即写入
                if self.use_db:
                    for journal in page_journals:
                        self._save_journal_to_db(journal)

                # 更新统计
                self.stats["last_completed_page"] = page_num

                # 定期保存检查点
                if page_num % self.checkpoint_interval == 0:
                    self._save_checkpoint()
                    if self.use_db:
                        print(f"  [检查点] 已保存 (进度: {page_num}/{total_pages}, DB: +{self.stats['added_to_db']} upd:{self.stats['updated_in_db']})")
                    else:
                        print(f"  [检查点] 已保存 (进度: {page_num}/{total_pages})")

                # 偶尔模拟人类行为
                if page_num % 7 == 0:
                    await self._simulate_human_behavior()

            # 每20页更换一次User-Agent（重新创建context）
            if page_num % 20 == 0:
                print(f"\n  [策略] 更换User-Agent...")
                await self._rotate_user_agent()

    async def _fetch_page_with_retry(self, page_num: int) -> Optional[str]:
        """获取指定页（带重试）"""

        for attempt in range(self.max_retries):
            try:
                result = await self._fetch_page(page_num)

                if result and len(result) > 1000:
                    return result
                else:
                    print(f"\n  [WARN] 第{page_num}页响应内容异常")
                    if attempt < self.max_retries - 1:
                        retry_delay = self.retry_base_delay * (2 ** attempt)
                        print(f"  [重试] {attempt + 1}/{self.max_retries}, 等待 {retry_delay} 秒...")
                        await asyncio.sleep(retry_delay)
                        self.stats["retry_count"] += 1

            except Exception as e:
                print(f"\n  [ERROR] 第{page_num}页请求失败: {e}")
                if attempt < self.max_retries - 1:
                    retry_delay = self.retry_base_delay * (2 ** attempt) * 2
                    print(f"  [重试] {attempt + 1}/{self.max_retries}, 等待 {retry_delay} 秒...")
                    await asyncio.sleep(retry_delay)
                    self.stats["retry_count"] += 1

        # 所有重试都失败
        if page_num not in self.stats["failed_pages"]:
            self.stats["failed_pages"].append(page_num)

        print(f"  [FAIL] 第{page_num}页获取失败，已跳过")
        return None

    async def _fetch_page(self, page_num: int) -> Optional[str]:
        """获取指定页的HTML"""

        result = await self.page.evaluate("""
            async (args) => {
                const pageNum = args.pageNum;
                const clickName = args.clickName;
                const params = {
                    searchStateJson: JSON.stringify({
                        "StateID": "",
                        "Platfrom": "",
                        "QueryTime": "",
                        "Account": "knavi",
                        "ClientToken": "",
                        "Language": "",
                        "CNode": {
                            "PCode": "OYXNO5VW",
                            "SMode": "",
                            "OperateT": ""
                        },
                        "QNode": {
                            "SelectT": "",
                            "Select_Fields": "",
                            "S_DBCodes": "",
                            "Subscribed": "",
                            "QGroup": [],
                            "OrderBy": "OTA|DESC",
                            "GroupBy": "",
                            "Additon": ""
                        }
                    }),
                    displaymode: '1',
                    pageindex: String(pageNum),
                    pagecount: '21',
                    index: 'JSTMWT6S',
                    searchType: '刊名(曾用刊名)',
                    parentcode: 'SQN63324',
                    switchdata: 'clickTabSearch'
                };

                // 只有当 clickName 非空时才添加该参数
                if (clickName) {
                    params.clickName = clickName;
                }

                const body = Object.keys(params)
                    .map(key => encodeURIComponent(key) + '=' + encodeURIComponent(params[key]))
                    .join('&');

                const response = await fetch('https://navi.cnki.net/knavi/journals/searchbaseinfo', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: body
                });

                return {
                    status: response.status,
                    ok: response.ok,
                    text: await response.text()
                };
            }
        """, {"pageNum": page_num, "clickName": self.click_name or ''})

        if result.get('ok') and result.get('text'):
            return result['text']
        else:
            return None

    async def _rotate_user_agent(self):
        """更换User-Agent"""
        try:
            # 获取当前context
            context = self.page.context

            # 创建新context
            new_user_agent = self._get_random_user_agent()
            new_context = await self.browser.new_context(
                user_agent=new_user_agent,
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN',
                timezone_id='Asia/Shanghai'
            )

            await new_context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            # 创建新页面
            new_page = await new_context.new_page()
            new_page.set_default_timeout(60000)

            # 访问主页面
            await new_page.goto(
                "https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT",
                wait_until='domcontentloaded'
            )
            await asyncio.sleep(self._random_delay())

            # 关闭旧context和页面
            await context.close()

            # 更新引用
            self.page = new_page

            print(f"    已更换: {new_user_agent[:50]}...")

        except Exception as e:
            print(f"    [WARN] 更换User-Agent失败: {e}")

    def _parse_total_pages(self, html: str) -> int:
        """从HTML解析总页数"""
        soup = BeautifulSoup(html, 'html.parser')
        elem = soup.find(id='lblPageCount')
        if elem:
            text = elem.get_text(strip=True)
            if text.isdigit():
                return int(text)
        return 1

    def _parse_journals_from_html(self, html: str) -> List[Dict]:
        """从HTML解析期刊列表"""
        journals = []
        soup = BeautifulSoup(html, 'html.parser')

        journal_list = soup.find('ul', class_='list_tup')
        if not journal_list:
            return journals

        items = journal_list.find_all('li', recursive=False)

        for item in items:
            if 'clearfix' in item.get('class', []):
                continue

            journal = self._parse_journal_item(item)
            if journal:
                journals.append(journal)

        return journals

    def _parse_journal_item(self, element) -> Optional[Dict]:
        """解析单个期刊"""
        try:
            name_link = element.find('a')
            if not name_link:
                return None

            # 获取纯期刊名称（a标签内的第一个文本节点）
            name = name_link.get_text(strip=True)

            # 清理name字段 - 移除后续的标识词和影响因子等信息
            # 期刊名称通常在"网络首发"、"增强出版"、"复合影响因子"等关键词之前
            for keyword in ['网络首发', '增强出版', '完全OA期刊', 'OA期刊', '复合影响因子', '综合影响因子', 'ISSN', 'CN', '主办单位']:
                if keyword in name:
                    name = name.split(keyword)[0].strip()
                    break

            detail_url = name_link.get('href', '')

            if detail_url and not detail_url.startswith('http'):
                if detail_url.startswith('/'):
                    detail_url = 'https://navi.cnki.net' + detail_url

            text = element.get_text(strip=True)

            # 解析各个字段
            issn = ""
            cn_code = ""
            publisher = ""
            composite_impact_factor = ""  # 复合影响因子
            comprehensive_impact_factor = ""  # 综合影响因子

            # 出版模式标识
            is_network_first = '网络首发' in text
            is_enhanced_publishing = '增强出版' in text

            # ISSN
            issn_match = re.search(r'ISSN[：:]\s*([0-9X-]+)', text)
            if issn_match:
                issn = issn_match.group(1)

            # CN刊号
            cn_match = re.search(r'CN[：:]\s*([0-9-]+/[0-9A-Z]+)', text)
            if cn_match:
                cn_code = cn_match.group(1)

            # 复合影响因子
            composite_match = re.search(r'复合影响因子[：:]\s*([\d.]+)', text)
            if composite_match:
                composite_impact_factor = composite_match.group(1)

            # 综合影响因子
            comprehensive_match = re.search(r'综合影响因子[：:]\s*([\d.]+)', text)
            if comprehensive_match:
                comprehensive_impact_factor = comprehensive_match.group(1)

            # 主办单位（在最后一个字段之后）
            pub_match = re.search(r'主办单位[：:]\s*(.+?)$', text)
            if pub_match:
                publisher = pub_match.group(1).strip()

            is_cssci = self.click_name == 'CSSCI 中文社会科学引文索引'
            return {
                'name': name,  # 纯期刊名称
                'issn': issn,
                'cn': cn_code,
                'publisher': publisher,
                'composite_impact_factor': composite_impact_factor,  # 复合影响因子
                'comprehensive_impact_factor': comprehensive_impact_factor,  # 综合影响因子
                'is_network_first': is_network_first,  # 网络首发
                'is_enhanced_publishing': is_enhanced_publishing,  # 增强出版
                'detail_url': detail_url,
                'is_cssci': is_cssci,
                'source': 'CNKI',
                'cssci_year': 2023 if is_cssci else None  # 只有 CSSCI 期刊才设置年份
            }

        except Exception as e:
            return None

    def _save_checkpoint(self):
        """保存检查点"""
        os.makedirs(os.path.dirname(self.checkpoint_file), exist_ok=True)

        with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump({
                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'stats': self.stats,
                'journals': self.journals
            }, f, ensure_ascii=False, indent=2)

    def save_to_json(self, filepath: str, force: bool = False):
        """保存到JSON文件

        Args:
            filepath: 保存路径
            force: 即使在数据库模式下也保存JSON
        """
        if self.use_db and not force:
            print("\n[信息] 数据库模式，跳过JSON保存（使用force=True可强制保存）")
            return

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
                'total': len(self.journals),
                'fetch_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'stats': self.stats,
                'journals': self.journals
            }, f, ensure_ascii=False, indent=2)

        print(f"\n[OK] 数据已保存: {filepath}")


async def main():
    """主函数"""
    print("=" * 70)
    print("CSSCI期刊抓取测试 (反爬虫增强版)")
    print("=" * 70)

    fetcher = CNKICSSCIFetcherAntiDetection(headless=False)

    # 测试10页
    print("\n配置: 测试10页")
    journals = await fetcher.fetch_cssci_journals(max_pages=10)

    if journals:
        print(f"\n成功抓取 {len(journals)} 本CSSCI期刊")

        # 显示样本
        print("\n期刊样本 (前10本):")
        for i, journal in enumerate(journals[:10], 1):
            print(f"  {i}. {journal['name']}")

        # 保存数据
        output_file = "data/journals/cssci_journals_anti_detection_test.json"
        fetcher.save_to_json(output_file)

        # 统计
        print(f"\n数据统计:")
        print(f"  总页数: {fetcher.stats['total_pages']}")
        print(f"  总期刊数: {len(journals)}")
        print(f"  重试次数: {fetcher.stats['retry_count']}")
        print(f"  失败页面: {fetcher.stats['failed_pages']}")

        # 字段完整度
        with_issn = len([j for j in journals if j.get('issn')])
        with_cn = len([j for j in journals if j.get('cn')])
        with_publisher = len([j for j in journals if j.get('publisher')])

        print(f"\n字段完整度:")
        print(f"  ISSN: {with_issn}/{len(journals)} ({with_issn/len(journals)*100:.1f}%)")
        print(f"  CN: {with_cn}/{len(journals)} ({with_cn/len(journals)*100:.1f}%)")
        print(f"  主办单位: {with_publisher}/{len(journals)} ({with_publisher/len(journals)*100:.1f}%)")
    else:
        print("\n[FAIL] 未抓取到期刊")


if __name__ == '__main__':
    asyncio.run(main())
