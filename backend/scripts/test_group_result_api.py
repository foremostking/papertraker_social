"""
测试CNKI group/result API - 获取来源类别分组数据
"""

import asyncio
import aiohttp
import json


async def test_group_result_with_group_ids():
    """测试使用groupIds参数调用group/result API"""
    print("=" * 70)
    print("CNKI Group/Result API Test - With groupIds Parameter")
    print("=" * 70)

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
                },
                {
                    "Key": "ControlGroup",
                    "Title": "",
                    "Logic": 0,
                    "Items": [],
                    "ChildItems": [
                        {
                            "Key": ".tit-startend-yearbox",
                            "Title": "",
                            "Logic": 0,
                            "Items": [
                                {
                                    "Key": ".tit-startend-yearbox",
                                    "Title": "出版年度",
                                    "Logic": 0,
                                    "Field": "YE",
                                    "Operator": 7,
                                    "Value": "2020",
                                    "Value2": "2026"
                                }
                            ],
                            "ChildItems": []
                        }
                    ]
                }
            ]
        },
        "ExScope": "1",
        "SearchType": 4,
        "Rlang": "CHINESE",
        "KuaKuCode": "",
        "Expands": {},
        "View": "changeDBCh",
        "SearchFrom": 99
    }

    # 用户提供的参数格式
    post_data = {
        'queryJson': json.dumps(query_json, ensure_ascii=False),
        'groupIds': 'LYBSM',  # 来源类别的ID
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

    # Cookie
    cookies = {
        "Ecp_ClientId": "d83c495f79519b333571ce13a1caecb30VAT2g2H06",
        "cnkiUserKey": "db56d603-79ef-3f2a-90f1-7263e8b74a7d",
        "SID_kns_new": "kns15018109",
        "KNS2COOKIE": "1774513277.535.171404.517558|b25e41a932fd162af3b8c5cff4059fc3"
    }

    print(f"\n[Request Parameters]")
    print(f"URL: https://kns.cnki.net/kns8s/group/result")
    print(f"Query: {search_query}")
    print(f"groupIds: LYBSM (来源类别)")
    print("-" * 70)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            'https://kns.cnki.net/kns8s/group/result',
            data=post_data,
            headers=headers,
            cookies=cookies
        ) as response:
            print(f"\n[Response]")
            print(f"Status: {response.status}")
            print(f"Content-Type: {response.headers.get('Content-Type')}")

            content = await response.text()
            print(f"Length: {len(content)} characters")

            # 保存响应
            with open('data/debug_group_result_LYBSM.html', 'w', encoding='utf-8') as f:
                f.write(content)
            print("Saved to: data/debug_group_result_LYBSM.html")

            # 分析响应
            if content.strip().startswith('{') or content.strip().startswith('['):
                print("\n-> JSON response!")
                try:
                    data = json.loads(content)
                    print(f"Top-level keys: {list(data.keys()) if isinstance(data, dict) else 'Array'}")

                    # 查找来源类别数据
                    def find_lybsm_data(obj, path=""):
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                new_path = f"{path}.{k}" if path else k
                                if 'LYBSM' in k or 'source' in k.lower() or '来源' in str(v):
                                    print(f"Found: {new_path} = {type(v).__name__}")
                                find_lybsm_data(v, new_path)
                        elif isinstance(obj, list):
                            for i, item in enumerate(obj):
                                find_lybsm_data(item, f"{path}[{i}]")

                    find_lybsm_data(data)

                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {e}")
            else:
                print("\n-> HTML response")
                # 尝试解析HTML中的来源类别数据
                from bs4 import BeautifulSoup
                import re

                soup = BeautifulSoup(content, 'html.parser')

                # 查找所有 dl 标签
                for dl in soup.find_all('dl'):
                    dt = dl.find('dt')
                    if dt and 'LYBSM' in dl.get('groupId', ''):
                        print(f"\n[Found LYBSM Group]")
                        print(f"Group ID: {dl.get('groupId')}")

                        dd = dl.find('dd')
                        if dd:
                            print(f"\nSource Categories:")
                            for li in dd.find_all('li'):
                                a_tag = li.find('a')
                                if a_tag:
                                    name = a_tag.get_text().strip()
                                    span = li.find('span')
                                    if span:
                                        count = span.get_text().strip().strip('()')
                                        print(f"  - {name}: {count}")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    asyncio.run(test_group_result_with_group_ids())
