"""
调试CNKI展开分组API - 当用户点击展开某个分组时调用的API
"""

import asyncio
import aiohttp
import json
from bs4 import BeautifulSoup
import urllib.parse


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


async def test_expand_group():
    """测试展开分组API - 获取来源类别的详细数据"""
    print("=" * 70)
    print("CNKI Expand Group API Test - Source Category (LYBSM)")
    print("=" * 70)

    keywords = ['零基预算']
    search_query = " AND ".join([f"SU%='{kw}'" for kw in keywords])

    query_json_obj = {
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

    query_json = json.dumps(query_json_obj, ensure_ascii=False)

    # 尝试不同的API端点
    apis_to_test = [
        {
            "name": "group/getGroupData (LYBSM)",
            "url": "https://kns.cnki.net/kns8s/group/getGroupData",
            "params": {
                'groupId': 'LYBSM',
                'field': 'LYBSM',
                'QueryJson': query_json,
                'aside': f'({search_query})',
                'searchFrom': '资源范围：学术期刊; 中英文扩展; 来源类别：全部期刊; ',
                'subject': '',
                'pageIndex': '1',
                'pageSize': '50',
                'sortName': 'GROUP_BY_COUNT',
                'sortType': 'DESC'
            }
        },
        {
            "name": "group/data (LYBSM)",
            "url": "https://kns.cnki.net/kns8s/group/data",
            "params": {
                'groupId': 'LYBSM',
                'QueryJson': query_json,
                'aside': f'({search_query})',
                'searchFrom': '资源范围：学术期刊; 中英文扩展; 来源类别：全部期刊; ',
                'subject': ''
            }
        },
        {
            "name": "group/ajax (LYBSM)",
            "url": "https://kns.cnki.net/kns8s/group/ajax",
            "params": {
                'gcode': 'LYBSM',
                'field': 'LYBSM',
                'QueryJson': query_json,
                'aside': f'({search_query})',
                'searchFrom': '资源范围：学术期刊; 中英文扩展; 来源类别：全部期刊; ',
                'subject': ''
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
                    cookies=cookies,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    print(f"Status: {response.status}")
                    print(f"Content-Type: {response.headers.get('Content-Type')}")

                    content = await response.text()
                    print(f"Length: {len(content)} characters")

                    # 保存响应
                    filename = f"data/debug_{api['url'].split('/')[-1]}_LYBSM.html"
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(content)

                    # 分析响应
                    if content.strip().startswith('{') or content.strip().startswith('['):
                        print("\n-> JSON response detected!")
                        try:
                            data = json.loads(content)
                            print(f"Top-level keys: {list(data.keys()) if isinstance(data, dict) else 'Array'}")

                            # 尝试找到来源类别数据
                            def find_source_cat(obj, depth=0):
                                if depth > 6:
                                    return
                                if isinstance(obj, dict):
                                    for k, v in obj.items():
                                        if isinstance(v, (dict, list)):
                                            print(f"{'  ' * depth}{k}: {type(v).__name__}")
                                            find_source_cat(v, depth+1)
                                        else:
                                            if v and str(v)[:50]:
                                                print(f"{'  ' * depth}{k}: {str(v)[:100]}")
                                elif isinstance(obj, list) and obj:
                                    print(f"{'  ' * depth}[Array] len={len(obj)}")
                                    find_source_cat(obj[0], depth+1)

                            print("\n[Data Structure]")
                            find_source_cat(data)

                            # 尝试解析来源类别列表
                            source_cat_list = []
                            def extract_source_items(obj):
                                if isinstance(obj, dict):
                                    # 查找可能的来源类别条目
                                    if 'name' in obj and 'count' in obj:
                                        source_cat_list.append({
                                            'name': obj['name'],
                                            'count': obj.get('count', 0)
                                        })
                                    for v in obj.values():
                                        extract_source_items(v)
                                elif isinstance(obj, list):
                                    for item in obj:
                                        extract_source_items(item)

                            extract_source_items(data)

                            if source_cat_list:
                                print("\n[Source Category Items Found]")
                                for item in source_cat_list[:20]:
                                    print(f"  - {item['name']}: {item['count']}")

                        except json.JSONDecodeError as e:
                            print(f"JSON decode error: {e}")
                    else:
                        print("\n-> HTML response")
                        # 尝试解析HTML
                        soup = BeautifulSoup(content, 'html.parser')

                        # 查找所有可能包含来源类别的元素
                        for li in soup.find_all('li'):
                            a_tag = li.find('a')
                            if a_tag:
                                text = a_tag.get_text().strip()
                                span = li.find('span')
                                if span:
                                    count = span.get_text().strip().strip('()')
                                    if count.isdigit():
                                        print(f"  - {text}: {count}")

            except Exception as e:
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()

    print("\n" + "=" * 70)


if __name__ == '__main__':
    asyncio.run(test_expand_group())
