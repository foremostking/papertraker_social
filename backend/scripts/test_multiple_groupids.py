"""
测试CNKI group/result API同时请求多个groupIds
"""

import asyncio
import aiohttp
import json
from bs4 import BeautifulSoup


async def test_multiple_groupids():
    """测试同时请求多个groupIds"""
    print("=" * 70)
    print("CNKI Multiple GroupIds Test")
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

    # 用户提供的完整groupIds列表
    all_group_ids = 'YJCC,CCL,YE,ZYZT|||CYZT,QK,FUC,LYBSM,AFC'

    post_data = {
        'queryJson': json.dumps(query_json, ensure_ascii=False),
        'groupIds': all_group_ids,
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

    print(f"\n[Request]")
    print(f"groupIds: {all_group_ids}")
    print(f"Expected dimensions:")
    print(f"  - YJCC: 研究层次")
    print(f"  - CCL: 学科")
    print(f"  - YE: 年度")
    print(f"  - ZYZT|||CYZT: 主题")
    print(f"  - QK: 期刊")
    print(f"  - FUC: 基金")
    print(f"  - LYBSM: 来源类别")
    print(f"  - AFC: 机构")
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

            html_content = await response.text()
            print(f"Content length: {len(html_content)}")

            # 保存响应
            with open('data/debug_multiple_groupids.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            print("Saved to: data/debug_multiple_groupids.html")

            # 解析各个维度的数据
            soup = BeautifulSoup(html_content, 'html.parser')

            dimensions_to_check = {
                'YJCC': '研究层次',
                'CCL': '学科',
                'YE': '年度',
                'ZYZT': '主题',
                'CYZT': '次要主题',
                'QK': '期刊',
                'FUC': '基金',
                'LYBSM': '来源类别',
                'AFC': '机构'
            }

            print(f"\n[Dimension Data Analysis]")
            for group_id, name in dimensions_to_check.items():
                # 查找对应groupId的dl标签
                dl = soup.find('dl', attrs={'groupId': lambda x: x and group_id in x})
                if dl:
                    dd = dl.find('dd')
                    if dd:
                        # 检查是否有实际数据
                        content = dd.get_text().strip()
                        result_div = dd.find('div', class_='resultlist')
                        if result_div and result_div.get_text().strip():
                            # 统计条目数量
                            items = dd.find_all('li')
                            print(f"  [OK] {name} ({group_id}): {len(items)} items")

                            # 显示前3条
                            for i, li in enumerate(items[:3]):
                                checkbox = li.find('input')
                                span = li.find('span')
                                if checkbox and span:
                                    print(f"      - {checkbox.get('text', '')[:20]}: {span.get_text().strip()}")
                        else:
                            print(f"  [EMPTY] {name} ({group_id}): Empty (collapsed)")
                    else:
                        print(f"  [WARN] {name} ({group_id}): No dd found")
                else:
                    print(f"  [WARN] {name} ({group_id}): No dl found")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    asyncio.run(test_multiple_groupids())
