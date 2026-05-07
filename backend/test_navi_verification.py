import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
        )
        page = await context.new_page()
        
        print("Opening navi.cnki.net... Please complete the verification if prompted.")
        await page.goto("https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT")
        
        # Wait for user to complete verification or page to load
        await asyncio.sleep(30)
        
        title = await page.title()
        print(f"Page title after 30s: {title}")
        
        # Try to fetch API
        if '验证' not in title and '安全' not in title:
            print("Trying API fetch...")
            result = await page.evaluate("""
                async () => {
                    try {
                        const response = await fetch('https://navi.cnki.net/knavi/journals/searchbaseinfo', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'X-Requested-With': 'XMLHttpRequest'
                            },
                            body: 'searchStateJson=%7B%22StateID%22%3A%22%22%2C%22Platfrom%22%3A%22%22%2C%22QueryTime%22%3A%22%22%2C%22Account%22%3A%22knavi%22%2C%22ClientToken%22%3A%22%22%2C%22Language%22%3A%22%22%2C%22CNode%22%3A%7B%22PCode%22%3A%22OYXNO5VW%22%2C%22SMode%22%3A%22%22%2C%22OperateT%22%3A%22%22%7D%2C%22QNode%22%3A%7B%22SelectT%22%3A%22%22%2C%22Select_Fields%22%3A%22%22%2C%22S_DBCodes%22%3A%22%22%2C%22Subscribed%22%3A%22%22%2C%22QGroup%22%3A%5B%5D%2C%22OrderBy%22%3A%22OTA%7CDESC%22%2C%22GroupBy%22%3A%22%22%2C%22Additon%22%3A%22%22%7D%7D&displaymode=1&pageindex=1&pagecount=21&index=JSTMWT6S&searchType=%E5%88%8A%E5%90%8D(%E6%9B%BE%E7%94%A8%E5%88%8A%E5%90%8D)&parentcode=SQN63324&switchdata=clickTabSearch&clickName=CSSCI+%E4%B8%AD%E6%96%87%E7%A4%BE%E4%BC%9A%E7%A7%91%E5%AD%A6%E5%BC%95%E6%96%87%E7%B4%A2%E5%BC%95'
                        });
                        return {status: response.status, ok: response.ok, text: await response.text()};
                    } catch(e) {
                        return {error: e.message};
                    }
                }
            """)
            print("API result:", result)
        else:
            print("Still blocked by verification.")
        
        await asyncio.sleep(5)
        await browser.close()

asyncio.run(main())
