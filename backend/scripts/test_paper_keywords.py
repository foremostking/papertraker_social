"""
测试从CNKI论文列表中提取关键词
用于构建主题分布
"""

import asyncio
import aiohttp
import json
import re
from bs4 import BeautifulSoup


async def test_paper_keywords_extraction():
    """测试从论文列表中提取关键词"""
    print("=" * 70)
    print("CNKI Paper Keywords Extraction Test")
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
        "SearchFrom": 1
    }

    post_data = {
        'boolSearch': 'true',
        'QueryJson': json.dumps(query_json, ensure_ascii=False),
        'pageNum': '1',
        'pageSize': '50',  # 获取更多论文以提取关键词
        'sortField': 'FFD',
        'sortType': 'DESC',
        'dstyle': 'listmode',
        'boolSortSearch': 'false',
        'aside': f'({search_query})',
        'searchFrom': '资源范围：学术期刊;  中英文扩展;  时间范围：出版年度：2020 到 2026,更新时间：不限;  来源类别：全部期刊; ',
        'subject': '',
        'turnpage': '',
        'language': 'uniplatform',
        'CurPage': '1'
    }

    headers = {
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'https://kns.cnki.net',
        'Referer': 'https://kns.cnki.net/kns8s/AdvSearch?crossids=YSTT4HG0%2CLSTPFY1C%2CJUP3MUPD%2CMPMFIG1A%2CWQ0UVIAA%2CBLZOG7CK%2CPWFIRAGL%2CEMRPGLPA%2CNLBO1Z6R%2CNN3FJMUV',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest'
    }

    cookies = {
        "Ecp_ClientId": "d83c495f79519b333571ce13a1caecb30VAT2g2H06",
        "cnkiUserKey": "db56d603-79ef-3f2a-90f1-7263e8b74a7d",
        "SID_kns_new": "kns15018109",
        "KNS2COOKIE": "1774513277.535.171404.517558|b25e41a932fd162af3b8c5cff4059fc3"
    }

    print(f"\n[Request]")
    print(f"Keywords: {keywords}")
    print(f"Query: {search_query}")
    print("-" * 70)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            'https://kns.cnki.net/kns8s/Brief/Grid',
            data=post_data,
            headers=headers,
            cookies=cookies
        ) as response:
            html_content = await response.text()
            print(f"\n[Response]")
            print(f"Status: {response.status}")

            # 保存响应
            with open('data/debug_paper_keywords.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            print("Saved to: data/debug_paper_keywords.html")

            # 解析论文和关键词
            soup = BeautifulSoup(html_content, 'html.parser')

            # 查找论文表格
            table = soup.find('table', class_='result-table-list')
            if not table:
                print("\n[ERROR] No result table found")
                return

            tbody = table.find('tbody')
            if not tbody:
                print("\n[ERROR] No tbody found")
                return

            # 收集所有关键词
            all_keywords = []
            paper_count = 0

            print(f"\n[Paper Keywords Extraction]")
            for row in tbody.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) < 3:
                    continue

                # 提取标题
                title = ""
                title_cell = cells[1]
                title_link = title_cell.find('a', class_='fz14')
                if title_link:
                    title = title_link.get_text().strip()

                # 提取关键词（如果有）
                paper_keywords = []

                # 尝试多种方式提取关键词
                # 方式1: 查找包含关键词的div或span
                for div in title_cell.find_all('div', class_='keyword'):
                    keyword_text = div.get_text().strip()
                    if keyword_text:
                        paper_keywords.extend([k.strip() for k in keyword_text.replace(';', ' ').replace('；', ' ').split()])

                # 方式2: 查找data-keyword属性
                if not paper_keywords:
                    for elem in title_cell.find_all(attrs={'data-keyword': True}):
                        kw = elem.get('data-keyword', '').strip()
                        if kw:
                            paper_keywords.extend([k.strip() for k in kw.split(';')])

                # 方式3: 从title属性提取
                if not paper_keywords:
                    title_elem = title_cell.find('a', class_='fz14')
                    if title_elem:
                        title_attr = title_elem.get('title', '')
                        # 检查是否包含关键词信息
                        if '关键词' in title_attr or 'Keyword' in title_attr:
                            # 尝试解析
                            match = re.search(r'关键词[：:]\s*([^.\n]+)', title_attr)
                            if match:
                                kw_text = match.group(1)
                                paper_keywords.extend([k.strip() for k in kw_text.replace(';', ' ').split()])

                if paper_keywords:
                    all_keywords.extend(paper_keywords)
                    paper_count += 1
                    if paper_count <= 5:  # 只显示前5篇
                        print(f"  [{paper_count}] {title[:30]}...")
                        print(f"      关键词: {', '.join(paper_keywords[:5])}")

            # 统计关键词频率
            from collections import Counter
            keyword_counter = Counter(all_keywords)

            print(f"\n[Keyword Frequency Analysis]")
            print(f"Total papers analyzed: {paper_count}")
            print(f"Total keywords extracted: {len(all_keywords)}")
            print(f"Unique keywords: {len(keyword_counter)}")

            print(f"\n[Top 20 Keywords]")
            for keyword, count in keyword_counter.most_common(20):
                print(f"  {count:3d} - {keyword}")

            # 保存关键词分布
            with open('data/keyword_distribution.json', 'w', encoding='utf-8') as f:
                json.dump(dict(keyword_counter), f, ensure_ascii=False, indent=2)
            print("\nSaved to: data/keyword_distribution.json")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    asyncio.run(test_paper_keywords_extraction())
