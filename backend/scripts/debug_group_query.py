"""
调试CNKI group/query API - 获取特定分组的详细数据
"""

import asyncio
import aiohttp
import json
from bs4 import BeautifulSoup


# 有效Cookie
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


async def test_group_query():
    """测试group/query API - 获取来源类别分组数据"""
    print("=" * 70)
    print("CNKI Group/Query API Test - Source Category Distribution")
    print("=" * 70)

    keywords = ['零基预算']
    search_query = " AND ".join([f"SU%='{kw}'" for kw in keywords])

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

    # 测试多个可能的API端点
    apis_to_test = [
        {
            "name": "group/query (LYBSM - 来源类别)",
            "url": "https://kns.cnki.net/kns8s/group/query",
            "params": {
                'field': 'LYBSM',
                'QueryJson': json.dumps(query_json, ensure_ascii=False),
                'aside': f'({search_query})',
                'searchFrom': '资源范围：学术期刊; 中英文扩展; 来源类别：全部期刊; ',
                'subject': '',
                'isSearch': 'true',
                'pageSize': '20',
                'pageNum': '1'
            }
        },
        {
            "name": "group/getGroupResult (LYBSM - 来源类别)",
            "url": "https://kns.cnki.net/kns8s/group/getGroupResult",
            "params": {
                'groupId': 'LYBSM',
                'QueryJson': json.dumps(query_json, ensure_ascii=False),
                'aside': f'({search_query})',
                'searchFrom': '资源范围：学术期刊; 中英文扩展; 来源类别：全部期刊; ',
                'subject': '',
                'pageIndex': '1',
                'pageSize': '50'
            }
        }
    ]

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

    async with aiohttp.ClientSession() as session:
        for api in apis_to_test:
            print(f"\n[Testing] {api['name']}")
            print(f"URL: {api['url']}")
            print("-" * 70)

            try:
                async with session.post(
                    api['url'],
                    data=api['params'],
                    headers=headers,
                    cookies=cookies
                ) as response:
                    print(f"Status: {response.status}")
                    print(f"Content-Type: {response.headers.get('Content-Type')}")

                    content = await response.text()
                    print(f"Length: {len(content)} characters")

                    # 保存响应
                    filename = f"data/debug_{api['url'].split('/')[-1]}_response.html"
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"Saved: {filename}")

                    # 分析响应
                    if content.strip().startswith('{'):
                        print("\n-> JSON response detected!")
                        try:
                            data = json.loads(content)
                            print(f"Top-level keys: {list(data.keys())}")

                            # 尝试解析来源类别数据
                            if 'data' in data:
                                print(f"\n[data] keys: {list(data['data'].keys()) if isinstance(data['data'], dict) else type(data['data']).__name__}")

                            if 'LYBSM' in data or 'data' in data:
                                print("\n[Found Source Category Data]")
                                # 显示结构
                                def extract_items(obj, depth=0):
                                    if depth > 4:
                                        return
                                    if isinstance(obj, dict):
                                        for k, v in obj.items():
                                            if isinstance(v, (dict, list)):
                                                print(f"{'  ' * depth}{k}:")
                                                extract_items(v, depth+1)
                                            else:
                                                print(f"{'  ' * depth}{k}: {v}")
                                extract_items(data)
                        except json.JSONDecodeError as e:
                            print(f"JSON decode error: {e}")
                    else:
                        print("\n-> HTML response detected")
                        # 尝试解析HTML中的来源类别数据
                        soup = BeautifulSoup(content, 'html.parser')

                        # 查找所有可能包含数据的元素
                        for li in soup.find_all('li'):
                            a_tag = li.find('a')
                            if a_tag:
                                text = a_tag.get_text().strip()
                                span = li.find('span')
                                if span:
                                    count = span.get_text().strip().strip('()')
                                    print(f"  - {text}: {count}")

            except Exception as e:
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()

    print("\n" + "=" * 70)


if __name__ == '__main__':
    asyncio.run(test_group_query())
