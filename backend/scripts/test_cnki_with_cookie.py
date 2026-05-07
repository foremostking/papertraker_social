"""
使用用户提供的Cookie测试CNKI API调用
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup

# 用户提供的Cookie
COOKIE = "Ecp_ClientId=d83c495f79519b333571ce13a1caecb30VAT2g2H06; cnkiUserKey=db56d603-79ef-3f2a-90f1-7263e8b74a7d; Ecp_IpLoginFail=26032539.144.210.17; SID_restapi=018108; SID_kns_new=kns15018109; KNS2COOKIE=1774513277.535.171404.517558|b25e41a932fd162af3b8c5cff4059fc3; knsadv-searchtype=%7B%22BLZOG7CK%22%3A%22gradeSearch%2CmajorSearch%22%2C%22MPMFIG1A%22%3A%22gradeSearch%2CmajorSearch%2CsentenceSearch%22%2C%22T2VC03OH%22%3A%22gradeSearch%2CmajorSearch%22%2C%22JQIRZIYA%22%3A%22gradeSearch%2CmajorSearch%2CsentenceSearch%22%2C%22S81HNSV3%22%3A%22gradeSearch%22%2C%22YSTT4HG0%22%3A%22gradeSearch%2CmajorSearch%2CauthorSearch%2CsentenceSearch%22%2C%22ML4DRIDX%22%3A%22gradeSearch%2CmajorSearch%22%2C%22WQ0UVIAA%22%3A%22gradeSearch%2CmajorSearch%22%2C%22VUDIXAIY%22%3A%22gradeSearch%2CmajorSearch%22%2C%22LIQN9Z3G%22%3A%22gradeSearch%22%2C%22NN3FJMUV%22%3A%22gradeSearch%2CmajorSearch%2CauthorSearch%2CsentenceSearch%22%2C%22LSTPFY1C%22%3A%22gradeSearch%2CmajorSearch%2CsentenceSearch%22%2C%22HHCPM1F8%22%3A%22gradeSearch%2CmajorSearch%22%2C%22OORPU5FE%22%3A%22gradeSearch%2CmajorSearch%22%2C%22WD0FTY92%22%3A%22gradeSearch%2CmajorSearch%2CauthorSearch%2CsentenceSearch%22%2C%22BPBAFJ5S%22%3A%22gradeSearch%2CmajorSearch%2CauthorSearch%2CsentenceSearch%22%2C%22EMRPGLPA%22%3A%22gradeSearch%2CmajorSearch%22%2C%22PWFIRAGL%22%3A%22gradeSearch%2CmajorSearch%2CsentenceSearch%22%2C%22U8J8LYLV%22%3A%22gradeSearch%2CmajorSearch%22%2C%22R79MZMCB%22%3A%22gradeSearch%22%2C%22J708GVCE%22%3A%22gradeSearch%2CmajorSearch%22%2C%228JBZLDJQ%22%3A%22gradeSearch%2CmajorSearch%2CsentenceSearch%22%2C%22HR1YT1Z9%22%3A%22gradeSearch%2CmajorSearch%22%2C%22JUP3MUPD%22%3A%22gradeSearch%2CmajorSearch%2CauthorSearch%2CsentenceSearch%22%2C%22NLBO1Z6R%22%3A%22gradeSearch%2CmajorSearch%22%2C%22RMJLXHZ3%22%3A%22gradeSearch%2CmajorSearch%2CsentenceSearch%22%2C%221UR4K4HZ%22%3A%22gradeSearch%2CmajorSearch%2CauthorSearch%2CsentenceSearch%22%2C%22NB3WEHK%22%3A%22gradeSearch%2CmajorSearch%22%2C%22XVLO76FD%22%3A%22gradeSearch%2CmajorSearch%22%7D; drlang=both; SID_sug=018106; dsortypes=DESC; dsorders=FFD; searchTimeFlags=1; knsLeftGroupSelectItem=; KNS2COOKIE=1774513277.535.171404.517558|b25e41a932fd162af3b8c5cff4059fc3; createtime-advInput=2026-03-26%2016%3A21%3A15"

# 测试关键词
KEYWORDS = ['零基预算', '甘肃省']


def parse_cookie_string(cookie_str):
    """解析Cookie字符串为字典"""
    cookies = {}
    for pair in cookie_str.split(';'):
        pair = pair.strip()
        if '=' in pair:
            key, value = pair.split('=', 1)
            cookies[key.strip()] = value.strip()
    return cookies


def build_query_json(keywords):
    """构建QueryJson"""
    # 使用 SU%= 语法
    search_query = " AND ".join([f"SU%='{kw}'" for kw in keywords])

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
    import json
    return json.dumps(query_json, ensure_ascii=False)


async def test_cnki_api():
    """测试CNKI API调用"""

    print("=" * 70)
    print("使用有效Cookie测试CNKI brief/grid API")
    print("=" * 70)
    print(f"\n测试关键词: {KEYWORDS}")
    print("-" * 70)

    # 构建请求
    query_json_str = build_query_json(KEYWORDS)
    search_query = " AND ".join([f"SU%='{kw}'" for kw in KEYWORDS])

    post_data = {
        'boolSearch': 'true',
        'QueryJson': query_json_str,
        'pageNum': '1',
        'pageSize': '20',
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

    cookies = parse_cookie_string(COOKIE)

    print(f"\nCookie信息:")
    print(f"  Ecp_ClientId: {cookies.get('Ecp_ClientId', 'N/A')[:30]}...")
    print(f"  SID_kns_new: {cookies.get('SID_kns_new', 'N/A')}")
    print(f"  KNS2COOKIE: {cookies.get('KNS2COOKIE', 'N/A')[:30]}...")

    print(f"\n检索式: {search_query}")
    print(f"\n发送POST请求到: https://kns.cnki.net/kns8s/brief/grid")
    print("-" * 70)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            'https://kns.cnki.net/kns8s/brief/grid',
            data=post_data,
            headers=headers,
            cookies=cookies
        ) as response:
            print(f"\n响应状态码: {response.status}")

            html_content = await response.text()

            # 保存完整响应
            with open('data/test_api_response.html', 'w', encoding='utf-8') as f:
                f.write(html_content)

            print(f"响应长度: {len(html_content)} 字符")
            print(f"响应前500字符:\n{html_content[:500]}")

            # 解析结果
            soup = BeautifulSoup(html_content, 'html.parser')

            # 解析文献总数
            count_div = soup.find('div', id='countPageDiv')
            if count_div:
                count_em = count_div.find('em')
                if count_em:
                    try:
                        total_count = int(count_em.get_text().strip())
                        print(f"\n[OK] 文献总数: {total_count} 篇")
                    except:
                        print(f"\n[ERROR] 无法解析文献总数")

            # 解析文献列表
            table = soup.find('table', class_='result-table-list')
            if table:
                tbody = soup.find('tbody')
                if tbody:
                    rows = tbody.find_all('tr')
                    print(f"\n[OK] 找到 {len(rows)} 篇文献")

                    print(f"\n前5篇文献:")
                    for i, row in enumerate(rows[:5], 1):
                        cells = row.find_all('td')
                        if len(cells) > 4:
                            # 篇名
                            name_cell = cells[1] if len(cells) > 1 else None
                            title = "未知"
                            if name_cell:
                                title_link = name_cell.find('a', class_='fz14')
                                if title_link:
                                    for font in title_link.find_all('font'):
                                        font.unwrap()
                                    title = title_link.get_text().strip()

                            # 期刊
                            source_cell = cells[3] if len(cells) > 3 else None
                            journal = "未知"
                            if source_cell:
                                source_link = source_cell.find('a')
                                if source_link:
                                    journal = source_link.get_text().strip()

                            print(f"  {i}. [{journal}] {title}")

            print("\n" + "=" * 70)
            print("测试完成")
            print("=" * 70)


if __name__ == '__main__':
    asyncio.run(test_cnki_api())
