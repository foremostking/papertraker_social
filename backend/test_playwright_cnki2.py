import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
        )
        page = await context.new_page()
        
        print("[1] Visiting CNKI homepage...")
        await page.goto("https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT", wait_until='domcontentloaded')
        await asyncio.sleep(3)
        title = await page.title()
        print("[1] Page loaded, title:", title)
        
        # Save screenshot if blocked
        if '验证' in title or '安全' in title:
            print("[1] BLOCKED! Saving screenshot...")
            await page.screenshot(path='data/cnki_blocked.png')
            print("[1] Screenshot saved to data/cnki_blocked.png")
        
        print("[2] Trying page.request.post (fixed API)...")
        try:
            response = await page.request.post(
                'https://navi.cnki.net/knavi/journals/searchbaseinfo',
                data='searchStateJson=%7B%22StateID%22%3A%22%22%2C%22Platfrom%22%3A%22%22%2C%22QueryTime%22%3A%22%22%2C%22Account%22%3A%22knavi%22%2C%22ClientToken%22%3A%22%22%2C%22Language%22%3A%22%22%2C%22CNode%22%3A%7B%22PCode%22%3A%22OYXNO5VW%22%2C%22SMode%22%3A%22%22%2C%22OperateT%22%3A%22%22%7D%2C%22QNode%22%3A%7B%22SelectT%22%3A%22%22%2C%22Select_Fields%22%3A%22%22%2C%22S_DBCodes%22%3A%22%22%2C%22Subscribed%22%3A%22%22%2C%22QGroup%22%3A%5B%5D%2C%22OrderBy%22%3A%22OTA%7CDESC%22%2C%22GroupBy%22%3A%22%22%2C%22Additon%22%3A%22%22%7D%7D&displaymode=1&pageindex=1&pagecount=21&index=JSTMWT6S&searchType=%E5%88%8A%E5%90%8D(%E6%9B%BE%E7%94%A8%E5%88%8A%E5%90%8D)&parentcode=SQN63324&switchdata=clickTabSearch&clickName=CSSCI+%E4%B8%AD%E6%96%87%E7%A4%BE%E4%BC%9A%E7%A7%91%E5%AD%A6%E5%BC%95%E6%96%87%E7%B4%A2%E5%BC%95',
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Referer': 'https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT',
                }
            )
            print("[2] status:", response.status)
            text = await response.text()
            print("[2] len:", len(text))
            print("[2] preview:", text[:300])
        except Exception as e:
            print("[2] request error:", e)
        
        await browser.close()

asyncio.run(main())
