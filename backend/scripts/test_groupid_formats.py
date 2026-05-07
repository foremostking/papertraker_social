"""
测试不同groupId格式的响应
"""

import asyncio
import aiohttp
import json
from bs4 import BeautifulSoup


async def test_groupid_format(group_id_to_test, name):
    """测试单个groupId格式"""
    print(f"\n{'='*60}")
    print(f"Testing: {name} ({group_id_to_test})")
    print('='*60)

    keywords = ['预算绩效']
    search_query = "SU%='" + keywords[0] + "'"

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

    post_data = {
        'queryJson': json.dumps(query_json, ensure_ascii=False),
        'groupIds': group_id_to_test,
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

    cookies = {
        "Ecp_ClientId": "d83c495f79519b333571ce13a1caecb30VAT2g2H06",
        "cnkiUserKey": "db56d603-79ef-3f2a-90f1-7263e8b74a7d",
        "SID_kns_new": "kns15018109",
        "KNS2COOKIE": "1774513277.535.171404.517558|b25e41a932fd162af3b8c5cff4059fc3"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            'https://kns.cnki.net/kns8s/group/result',
            data=post_data,
            headers=headers,
            cookies=cookies
        ) as response:
            html_content = await response.text()

            soup = BeautifulSoup(html_content, 'html.parser')

            # 查找所有dl标签并检查groupId属性
            dls = soup.find_all('dl')
            print(f"Found {len(dls)} dl tags")

            for dl in dls:
                group_id_attr = dl.get('groupId', 'no-id')
                class_attr = dl.get('class', [])
                dd = dl.find('dd')

                if dd:
                    items = dd.find_all('li')
                    content_len = len(dd.get_text().strip())

                    if items or content_len > 0:
                        print(f"\n  dl groupId: {group_id_attr[:60]}")
                        print(f"  class: {class_attr}")
                        print(f"  items: {len(items)}")
                        print(f"  content length: {content_len}")

                        # 显示前3条
                        for i, li in enumerate(items[:3]):
                            checkbox = li.find('input')
                            span = li.find('span')
                            if checkbox:
                                item_name = checkbox.get('text', '')
                            elif li.find('a'):
                                item_name = li.find('a').get_text().strip()
                            else:
                                item_name = ''

                            count = ''
                            if span:
                                count = span.get_text().strip()

                            if item_name:
                                print(f"    {i+1}. {item_name[:30]}: {count}")


async def main():
    """测试所有groupId格式"""
    formats_to_test = [
        ('ZYZT', 'Single: ZYZT'),
        ('CYZT', 'Single: CYZT'),
        ('ZYZT|||CYZT', 'Combined: ZYZT|||CYZT'),
        ('QK', 'Single: QK (Journal)'),
        ('AFC', 'Single: AFC (Institution)'),
    ]

    for group_id, name in formats_to_test:
        await test_groupid_format(group_id, name)
        await asyncio.sleep(1)  # 避免请求过快


if __name__ == '__main__':
    asyncio.run(main())
