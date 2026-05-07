"""
调试CNKI group/result API - 查看实际返回格式
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


async def debug_group_api():
    """调试group/result API"""
    print("=" * 70)
    print("CNKI Group/Result API Debug")
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

    post_data = {
        'boolSearch': 'true',
        'QueryJson': json.dumps(query_json, ensure_ascii=False),
        'aside': f'({search_query})',
        'searchFrom': '资源范围：学术期刊; 中英文扩展; 来源类别：全部期刊; ',
        'subject': ''
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

    print(f"\n[Request]")
    print(f"URL: https://kns.cnki.net/kns8s/group/result")
    print(f"Query: {search_query}")
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

            # 保存原始响应
            with open('data/debug_group_response.html', 'w', encoding='utf-8') as f:
                f.write(content)
            print("\n[Saved to data/debug_group_response.html]")

            # 检查响应类型
            print("\n[Content Analysis]")
            if content.strip().startswith('{'):
                print("-> JSON response detected")
                try:
                    data = json.loads(content)
                    print(f"-> Keys: {list(data.keys())}")

                    # 显示结构
                    def show_structure(obj, indent=0, max_depth=4):
                        if indent > max_depth:
                            return "..."
                        if isinstance(obj, dict):
                            items = []
                            for k, v in list(obj.items())[:10]:  # 限制显示数量
                                if isinstance(v, (dict, list)):
                                    items.append(f"  {'  ' * indent}{k}: {show_structure(v, indent+1)}")
                                else:
                                    items.append(f"  {'  ' * indent}{k}: {type(v).__name__}")
                            return "\n".join(items)
                        elif isinstance(obj, list) and obj:
                            return f"[{show_structure(obj[0], indent)}] (len={len(obj)})"
                        else:
                            return str(type(obj).__name__)

                    print("\n[Structure Preview]")
                    print(show_structure(data))
                except json.JSONDecodeError as e:
                    print(f"-> JSON decode error: {e}")
            else:
                print("-> HTML response detected")
                soup = BeautifulSoup(content, 'html.parser')

                # 查找所有可能包含分组信息的元素
                print("\n[HTML Analysis]")

                # 查找左侧分组区域
                left_section = soup.find('div', class_='leftSec')
                if left_section:
                    print("-> Found leftSec div")

                    # 查找所有dt标签（分组标题）
                    dt_tags = left_section.find_all('dt')
                    print(f"-> Found {len(dt_tags)} dt tags:")
                    for dt in dt_tags:
                        print(f"   - {dt.get_text().strip()[:50]}")

                    # 查找来源类别分组
                    for dl in left_section.find_all('dl'):
                        dt = dl.find('dt')
                        if dt and '来源' in dt.get_text():
                            print(f"\n[Found Source Category Group]")
                            dd_items = dl.find_all('dd')
                            print(f"-> {len(dd_items)} items")
                            for i, dd in enumerate(dd_items[:10]):
                                a_tag = dd.find('a')
                                if a_tag:
                                    print(f"   {i+1}. {a_tag.get_text().strip()}")
                                    href = a_tag.get('href', '')
                                    if href:
                                        print(f"      href: {href[:80]}")
                else:
                    print("-> No leftSec div found")

                # 查找其他可能的分组容器
                for div in soup.find_all('div', class_=True):
                    if 'group' in div.get('class', []).__str__().lower():
                        print(f"-> Found potential group div: {div.get('class')}")

                # 查找所有可能包含数量链接的a标签
                count_links = []
                for a in soup.find_all('a'):
                    text = a.get_text()
                    if text and any(c.isdigit() for c in text):
                        href = a.get('href', '')
                        if 'source' in href.lower() or '来源' in text:
                            count_links.append((text.strip(), href))
                            if len(count_links) >= 10:
                                break

                if count_links:
                    print(f"\n[Found {len(count_links)} potential source links]")
                    for text, href in count_links:
                        print(f"   - {text}")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    asyncio.run(debug_group_api())
