"""
测试CNKI API - 使用默认Cookie
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup


async def test_cnki_api():
    """使用默认Cookie测试CNKI API"""
    print("=" * 70)
    print("CNKI API Test with Default Cookie")
    print("=" * 70)

    # 默认Cookie（用户提供的有效Cookie）
    DEFAULT_COOKIE = (
        "Ecp_ClientId=d83c495f79519b333571ce13a1caecb30VAT2g2H06; "
        "cnkiUserKey=db56d603-79ef-3f2a-90f1-7263e8b74a7d; "
        "SID_kns_new=kns15018109; "
        "KNS2COOKIE=1774513277.535.171404.517558|b25e41a932fd162af3b8c5cff4059fc3"
    )

    # 解析Cookie
    cookies = {}
    for pair in DEFAULT_COOKIE.split(';'):
        pair = pair.strip()
        if '=' in pair:
            key, value = pair.split('=', 1)
            cookies[key.strip()] = value.strip()

    print("\n[Cookie Info]")
    for key in ['Ecp_ClientId', 'SID_kns_new', 'KNS2COOKIE']:
        if key in cookies:
            print(f"  {key}: ...{cookies[key][-20:]}")

    # 构建检索请求
    keywords = ['零基预算']
    search_query = " AND ".join([f"SU%='{kw}'" for kw in keywords])

    import json
    query_json = {
        "Platform": "",
        "Resource": "JOURNAL",
        "Classid": "YSTT4HG0",
        "QNode": {
            "QGroup": [
                {
                    "Key": "Subject",
                    "Logic": 0,
                    "Items": [
                        {
                            "Key": "Expert",
                            "Field": "EXPERT",
                            "Operator": 0,
                            "Value": search_query,
                            "Value2": ""
                        }
                    ],
                    "ChildItems": []
                }
            ]
        },
        "SearchType": 4,
        "Rlang": "CHINESE"
    }

    post_data = {
        'boolSearch': 'true',
        'QueryJson': json.dumps(query_json, ensure_ascii=False),
        'pageNum': '1',
        'pageSize': '20',
        'sortField': 'FFD',
        'sortType': 'DESC',
        'dstyle': 'listmode',
        'aside': f'({search_query})',
        'searchFrom': '资源范围：学术期刊',
        'subject': '',
        'turnpage': '',
        'language': 'uniplatform',
        'CurPage': '1'
    }

    headers = {
        'Accept': '*/*',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'https://kns.cnki.net',
        'Referer': 'https://kns.cnki.net/kns8s/AdvSearch?crossids=YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'X-Requested-With': 'XMLHttpRequest'
    }

    print(f"\n[Request]")
    print(f"Query: {search_query}")
    print(f"POST: https://kns.cnki.net/kns8s/brief/grid")
    print("-" * 70)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            'https://kns.cnki.net/kns8s/brief/grid',
            data=post_data,
            headers=headers,
            cookies=cookies
        ) as response:
            print(f"\n[Response]")
            print(f"Status: {response.status}")

            html = await response.text()
            print(f"Length: {len(html)} characters")

            # 解析结果
            soup = BeautifulSoup(html, 'html.parser')

            count_div = soup.find('div', id='countPageDiv')
            if count_div:
                count_em = count_div.find('em')
                if count_em:
                    # 移除数字中的逗号
                    count_text = count_em.get_text().strip().replace(',', '')
                    try:
                        total = int(count_text)
                        print(f"Total Papers: {total}")
                    except ValueError:
                        print(f"Total Papers: {count_text} (parse error)")

                    # 解析文献
                    table = soup.find('table', class_='result-table-list')
                    if table:
                        tbody = soup.find('tbody')
                        if tbody:
                            rows = tbody.find_all('tr')
                            print(f"Papers Found: {len(rows)}")

                            print(f"\n[Top 3 Papers]")
                            for i, row in enumerate(rows[:3], 1):
                                cells = row.find_all('td')
                                if len(cells) > 3:
                                    # 篇名
                                    title = "N/A"
                                    if len(cells) > 1:
                                        title_link = cells[1].find('a', class_='fz14')
                                        if title_link:
                                            for font in title_link.find_all('font'):
                                                font.unwrap()
                                            title = title_link.get_text().strip()[:40]

                                    # 期刊
                                    journal = "N/A"
                                    if len(cells) > 3:
                                        link = cells[3].find('a')
                                        if link:
                                            journal = link.get_text().strip()

                                    print(f"  {i}. [{journal}] {title}")

    print("\n" + "=" * 70)
    print("Test completed successfully!")
    print("=" * 70)


if __name__ == '__main__':
    asyncio.run(test_cnki_api())
