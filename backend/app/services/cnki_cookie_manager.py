"""
CNKI Cookie 自动获取管理器 V2

根据官方文档优化，通过CNKI安全验证
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Optional
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class CNKICookieManager:
    """CNKI Cookie 自动管理器 V2"""

    # 能成功获取Cookie的URL（包含crossids参数）
    COOKIE_FETCH_URL = "https://kns.cnki.net/kns8s/AdvSearch?crossids=YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV"

    # User-Agent池
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
    ]

    # 关键Cookie名称（只保留这些，其他的不过滤）
    KEY_COOKIES = [
        'Ecp_ClientId',
        'cnkiUserKey',
        'SID_kns_new',
        'KNS2COOKIE',
        'SID_restapi',
        'Ecp_IpLoginFail',
        'drlang',
        'SID_sug',
        'dsortypes',
        'dsorders',
        'searchTimeFlags',
        'knsLeftGroupSelectItem',
        'createtime-advInput'
    ]

    # CNKI相关的Cookie前缀
    CNKI_COOKIE_PREFIXES = [
        'Ecp_',
        'cnki',
        'SID_',
        'KNS',
        'dr',
        'ds',
        'searchTimeFlags',
        'kns',
        'createtime'
    ]

    def __init__(self, cache_file: str = "data/cnki_cookie_cache.json"):
        """初始化Cookie管理器"""
        self.cache_file = cache_file
        self.cookie_cache = self._load_cache()

    def _load_cache(self) -> dict:
        """从文件加载Cookie缓存"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    expiry_str = cache.get('expiry')
                    if expiry_str:
                        expiry = datetime.fromisoformat(expiry_str)
                        if datetime.now() < expiry:
                            logger.info(f"使用缓存的Cookie (过期时间: {expiry})")
                            return cache
                        else:
                            logger.info("缓存的Cookie已过期")
            except Exception as e:
                logger.warning(f"加载Cookie缓存失败: {e}")

        return {}

    def _save_cache(self, cookie_str: str, expiry_hours: int = 1):
        """保存Cookie到缓存文件"""
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)

        expiry = datetime.now() + timedelta(hours=expiry_hours)

        cache = {
            'cookie': cookie_str,
            'expiry': expiry.isoformat(),
            'fetched_at': datetime.now().isoformat()
        }

        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)

        logger.info(f"Cookie已缓存，过期时间: {expiry}")

    async def fetch_cookie_async(self, headless: bool = True,
                                   wait_for_verification: int = 0) -> Optional[str]:
        """
        异步获取CNKI Cookie

        Args:
            headless: 是否使用无头模式
            wait_for_verification: 如果触发安全验证，等待的秒数

        Returns:
            Cookie字符串，失败返回None
        """
        logger.info("开始获取CNKI Cookie...")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=headless,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-web-security',
                        '--disable-features=VizDisplayCompositor'
                    ]
                )

                # 使用精确的视口大小
                context = await browser.new_context(
                    user_agent=random.choice(self.USER_AGENTS),
                    viewport={'width': 1920, 'height': 1080},
                    locale='zh-CN',
                    timezone_id='Asia/Shanghai',
                    # 添加权限
                    permissions=['geolocation', 'notifications']
                )

                # 添加完整的反检测脚本
                await context.add_init_script("""
                    // 隐藏webdriver特征
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

                    // 添加插件
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });

                    // 添加语言
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['zh-CN', 'zh', 'en-US', 'en']
                    });

                    // 添加平台信息
                    Object.defineProperty(navigator, 'platform', {
                        get: () => 'Win32'
                    });

                    // 添加chrome对象
                    window.chrome = {
                        runtime: {}
                    };

                    // 添加权限API
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                """)

                page = await context.new_page()

                # 设置额外的请求头（每个请求都会带这些头）
                await page.set_extra_http_headers({
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"'
                })

                # 步骤1: 访问CNKI首页建立基础会话
                logger.info("访问CNKI首页...")
                try:
                    await page.goto(
                        "https://www.cnki.net/",
                        wait_until='domcontentloaded',
                        timeout=30000
                    )
                    await page.wait_for_timeout(random.uniform(1500, 2500))
                except Exception as e:
                    logger.warning(f"访问首页失败: {e}")

                # 步骤2: 访问包含crossids的特定URL获取完整Cookie
                logger.info(f"访问Cookie获取URL (包含crossids)...")

                # 添加随机延迟模拟人类行为
                await page.wait_for_timeout(random.uniform(500, 1500))

                await page.goto(
                    self.COOKIE_FETCH_URL,
                    wait_until='domcontentloaded',
                    timeout=30000
                )

                # 等待页面加载和JavaScript执行
                await page.wait_for_timeout(random.uniform(3000, 5000))

                # 检查是否触发安全验证
                page_title = await page.title()
                if '安全验证' in page_title or '验证' in page_title:
                    logger.warning(f"触发安全验证页面")

                    if wait_for_verification > 0:
                        logger.info(f"等待 {wait_for_verification} 秒以处理验证...")
                        await page.wait_for_timeout(wait_for_verification * 1000)

                        # 重新检查页面标题
                        page_title = await page.title()
                        if '安全验证' in page_title or '验证' in page_title:
                            logger.error("仍在安全验证页面，无法自动获取Cookie")
                            await browser.close()
                            return None
                    else:
                        logger.error("需要处理安全验证，请设置wait_for_verification参数")
                        await browser.close()
                        return None

                # 步骤3: 获取Cookie
                cookies = await page.context.cookies()

                # 过滤只保留CNKI相关的Cookie
                cnki_cookies = self._filter_cnki_cookies(cookies)

                # 格式化为字符串
                cookie_str = self._format_cookie_string(cnki_cookies)

                # 验证关键Cookie是否存在
                missing_keys = self._validate_cookie(cookie_str)
                if missing_keys:
                    logger.warning(f"缺少关键Cookie: {missing_keys}")
                else:
                    logger.info("成功获取所有关键Cookie")

                # 保存到缓存
                self._save_cache(cookie_str, expiry_hours=2)

                await browser.close()

                return cookie_str

        except Exception as e:
            logger.error(f"获取Cookie失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _filter_cnki_cookies(self, cookies: list) -> list:
        """
        过滤只保留CNKI相关的Cookie

        这样可以避免发送其他无关的Cookie，减少被识别的风险
        """
        cnki_cookies = []

        for cookie in cookies:
            name = cookie['name']

            # 检查是否是CNKI相关Cookie
            is_cnki_cookie = (
                any(name.startswith(prefix) for prefix in self.CNKI_COOKIE_PREFIXES) or
                name in self.KEY_COOKIES
            )

            if is_cnki_cookie:
                cnki_cookies.append(cookie)

        logger.debug(f"Cookie过滤: {len(cookies)} -> {len(cnki_cookies)}")
        return cnki_cookies

    def _format_cookie_string(self, cookies: list) -> str:
        """将Cookie列表格式化为字符串"""
        cookie_pairs = []
        for cookie in cookies:
            cookie_pairs.append(f"{cookie['name']}={cookie['value']}")
        return "; ".join(cookie_pairs)

    def _validate_cookie(self, cookie_str: str) -> list:
        """
        验证Cookie是否包含所有关键值

        Returns:
            缺失的Cookie名称列表
        """
        cookie_dict = {}
        for pair in cookie_str.split(';'):
            pair = pair.strip()
            if '=' in pair:
                key, value = pair.split('=', 1)
                cookie_dict[key.strip()] = value.strip()

        missing = []
        for key in self.KEY_COOKIES[:4]:  # 只检查前4个最重要的
            if key not in cookie_dict:
                missing.append(key)

        return missing

    def get_cookie(self, force_refresh: bool = False,
                   headless: bool = True) -> Optional[str]:
        """
        获取Cookie（同步方法）

        Args:
            force_refresh: 是否强制刷新，忽略缓存
            headless: 是否使用无头模式

        Returns:
            Cookie字符串，失败返回None
        """
        # 检查缓存
        if not force_refresh and self.cookie_cache:
            expiry_str = self.cookie_cache.get('expiry')
            if expiry_str:
                expiry = datetime.fromisoformat(expiry_str)
                if datetime.now() < expiry:
                    logger.info("使用缓存的Cookie")
                    return self.cookie_cache.get('cookie')

        # 获取新Cookie
        logger.info("获取新的Cookie...")
        return asyncio.run(self.fetch_cookie_async(headless=headless))

    async def get_cookie_async(self, force_refresh: bool = False,
                               headless: bool = True) -> Optional[str]:
        """
        获取Cookie（异步方法）

        Args:
            force_refresh: 是否强制刷新
            headless: 是否使用无头模式

        Returns:
            Cookie字符串，失败返回None
        """
        if not force_refresh and self.cookie_cache:
            expiry_str = self.cookie_cache.get('expiry')
            if expiry_str:
                expiry = datetime.fromisoformat(expiry_str)
                if datetime.now() < expiry:
                    logger.info("使用缓存的Cookie")
                    return self.cookie_cache.get('cookie')

        logger.info("获取新的Cookie...")
        return await self.fetch_cookie_async(headless=headless)

    def test_cookie(self, cookie_str: str) -> bool:
        """
        测试Cookie是否有效

        Args:
            cookie_str: Cookie字符串

        Returns:
            是否有效
        """
        import aiohttp

        async def _test():
            headers = {
                'User-Agent': random.choice(self.USER_AGENTS),
                'Referer': self.COOKIE_FETCH_URL,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            }

            cookies = {}
            for pair in cookie_str.split(';'):
                pair = pair.strip()
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    cookies[key.strip()] = value.strip()

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        'https://kns.cnki.net/kns8s/search',
                        headers=headers,
                        cookies=cookies,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as response:
                        return response.status == 200
            except Exception as e:
                logger.debug(f"Cookie测试失败: {e}")
                return False

        return asyncio.run(_test())


# 便捷函数
async def fetch_cnki_cookie_async(headless: bool = True) -> Optional[str]:
    """异步获取CNKI Cookie"""
    manager = CNKICookieManager()
    return await manager.fetch_cookie_async(headless=headless)


def fetch_cnki_cookie(headless: bool = True) -> Optional[str]:
    """同步获取CNKI Cookie"""
    manager = CNKICookieManager()
    return manager.get_cookie(headless=headless)


def get_cached_cookie() -> Optional[str]:
    """获取缓存的Cookie"""
    manager = CNKICookieManager()
    return manager.get_cookie(force_refresh=False)


# 测试代码
async def main():
    """测试Cookie获取"""
    print("=" * 70)
    print("CNKI Cookie Auto-Fetch V2 Test")
    print("=" * 70)

    manager = CNKICookieManager()

    # 先检查缓存
    cached = manager.get_cookie(force_refresh=False)
    if cached:
        print("\n[CACHED] Using cached cookie")
        print(f"Cookie length: {len(cached)} characters")
    else:
        print("\n[FETCH] Getting new cookie (browser window will be visible)...")

        cookie = await manager.fetch_cookie_async(
            headless=False,
            wait_for_verification=60
        )

        if cookie:
            print(f"\n[SUCCESS] Cookie fetched:")
            print(f"  Length: {len(cookie)} characters")

            # 显示关键Cookie
            for key in ['Ecp_ClientId', 'SID_kns_new', 'KNS2COOKIE']:
                if key in cookie:
                    start = cookie.find(key + '=')
                    if start != -1:
                        end = cookie.find(';', start)
                        if end == -1:
                            end = start + 60
                        value = cookie[start:end]
                        print(f"  {key}: {value[:50]}...")

            # 验证Cookie
            print(f"\n[VALIDATE] Testing cookie...")
            is_valid = manager.test_cookie(cookie)
            print(f"  Valid: {'YES' if is_valid else 'NO'}")
        else:
            print("\n[FAILED] Could not fetch cookie")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    asyncio.run(main())
