"""
CNKI期刊列表页抓取（完整字段版）

从搜索结果页提取所有可用信息：
- 名称、ISSN、CN、影响因子、主办单位
- journal_tags（CSSCI/北大核心/网络首发等标签）
- detail_url（详情页链接，用于后续补充更多信息）
- 核心标识（is_cssci, is_beida_core, is_network_first等）
"""
import os
import sys
import re
import json
import time
import random
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.journal import Journal

COOKIE_STR = "Ecp_ClientId=_vqrnqik__caByTET4758758s8HvEM9n0VHXDg7Gd7; SID_navi=018110; cnkiUserKey=e152802a-81bb-45ea-1563-56419bc6c85d; Ecp_IpLoginFail=26050739.144.210.22"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]


def get_headers():
    return {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT',
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': random.choice(['zh-CN,zh;q=0.9', 'zh-CN,zh;q=0.9,en;q=0.8']),
    }


def parse_cookie():
    cookies = {}
    for pair in COOKIE_STR.split(';'):
        pair = pair.strip()
        if '=' in pair:
            k, v = pair.split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies


def random_delay():
    base = random.uniform(1.5, 3.5)
    if random.random() < 0.08:
        base += random.uniform(2.0, 5.0)
    return base


def fetch_page(session, page_num):
    url = 'https://navi.cnki.net/knavi/journals/searchbaseinfo'
    search_state = {
        "StateID": "", "Platfrom": "", "QueryTime": "",
        "Account": "knavi", "ClientToken": "", "Language": "",
        "CNode": {"PCode": "OYXNO5VW", "SMode": "", "OperateT": ""},
        "QNode": {"SelectT": "", "Select_Fields": "", "S_DBCodes": "",
                  "Subscribed": "", "QGroup": [], "OrderBy": "OTA|DESC",
                  "GroupBy": "", "Additon": ""}
    }
    data = {
        'searchStateJson': json.dumps(search_state, separators=(',', ':')),
        'displaymode': '1', 'pageindex': str(page_num), 'pagecount': '21',
        'index': 'JSTMWT6S', 'searchType': '刊名(曾用刊名)',
        'parentcode': 'SQN63324', 'switchdata': 'clickTabSearch',
    }

    for attempt in range(3):
        try:
            resp = session.post(url, data=data, headers=get_headers(), timeout=25)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 403:
                print(f"  [HTTP 403] Cookie可能已失效")
                return None
            else:
                print(f"  [HTTP {resp.status_code}] 第{page_num}页 (重试{attempt+1}/3)")
        except Exception as e:
            print(f"  [ERROR] 第{page_num}页: {e} (重试{attempt+1}/3)")
        if attempt < 2:
            time.sleep(random.uniform(5.0, 10.0))
    return None


def parse_journals(html: str) -> List[Dict]:
    """解析期刊列表，提取所有可用字段"""
    journals = []

    # 匹配每个 <li> 条目
    items = re.findall(r'<li>\s*(.*?)\s*</li>', html, re.DOTALL)

    for item in items:
        # 必须有 detail URL 才认为是有效条目
        url_match = re.search(r'href="(https://navi\.cnki\.net/knavi/detail\?p=[^"]+)"', item)
        if not url_match:
            continue

        j = {'detail_url': url_match.group(1)}

        # 标题（在 <h1> 中）
        name_match = re.search(r'<h1>\s*([^<]+)</h1>', item)
        if name_match:
            j['name'] = name_match.group(1).strip()
        else:
            continue  # 没有名称跳过

        # 标签（<span>标签内容）
        tags = re.findall(r'<span>([^<]+)</span>', item)
        j['journal_tags'] = [t.strip() for t in tags if t.strip()]

        # 从标签推断核心标识
        all_tags_text = ' '.join(j['journal_tags'])
        j['is_cssci'] = 'CSSCI来源' in all_tags_text or 'CSSCI' in all_tags_text
        j['is_cssci_expansion'] = 'CSSCI扩展' in all_tags_text
        j['is_beida_core'] = '中文核心' in all_tags_text or '北大核心' in all_tags_text
        j['is_network_first'] = '网络首发' in all_tags_text
        j['is_enhanced_publishing'] = '增强出版' in all_tags_text

        # 影响因子
        cf = re.search(r'复合影响因子[：:]([\d.]+)', item)
        if cf:
            j['composite_impact_factor'] = float(cf.group(1))

        ci = re.search(r'综合影响因子[：:]([\d.]+)', item)
        if ci:
            j['comprehensive_impact_factor'] = float(ci.group(1))

        # ISSN
        issn = re.search(r'ISSN[：:]([\dA-Z\-]+)', item)
        if issn:
            j['issn'] = issn.group(1).strip()

        # CN
        cn = re.search(r'CN[：:]([\dA-Z\-/]+)', item)
        if cn:
            j['cn'] = cn.group(1).strip()

        # 主办单位
        pub = re.search(r'主办单位[：:]([^<]+)', item)
        if pub:
            j['publisher'] = pub.group(1).strip()[:200]

        journals.append(j)

    return journals


def get_total_pages(html: str) -> int:
    m = re.search(r'pageCount[\s\:\=]+(\d+)', html)
    if m:
        return int(m.group(1))
    m = re.search(r'lblPageCount[\s\>]*([\d]+)', html)
    if m:
        return int(m.group(1))
    return 0


def save_to_db(journals: List[Dict], db_session):
    """保存到数据库，upsert模式"""
    added = 0
    updated = 0
    for j in journals:
        try:
            existing = db_session.query(Journal).filter(Journal.name == j['name']).first()
            if existing:
                # 更新所有字段
                existing.is_cssci = j.get('is_cssci', existing.is_cssci)
                existing.is_cssci_expansion = j.get('is_cssci_expansion', existing.is_cssci_expansion)
                existing.is_beida_core = j.get('is_beida_core', existing.is_beida_core)
                existing.is_network_first = j.get('is_network_first', existing.is_network_first)
                existing.is_enhanced_publishing = j.get('is_enhanced_publishing', existing.is_enhanced_publishing)
                existing.issn = j.get('issn') or existing.issn
                existing.cn = j.get('cn') or existing.cn
                existing.publisher = j.get('publisher') or existing.publisher
                existing.detail_url = j.get('detail_url') or existing.detail_url
                if 'composite_impact_factor' in j:
                    existing.composite_impact_factor = j['composite_impact_factor']
                if 'comprehensive_impact_factor' in j:
                    existing.comprehensive_impact_factor = j['comprehensive_impact_factor']
                if j.get('journal_tags'):
                    existing.journal_tags = j['journal_tags']
                existing.source = 'CNKI'
                updated += 1
            else:
                journal = Journal(
                    name=j['name'],
                    is_cssci=j.get('is_cssci', False),
                    is_cssci_expansion=j.get('is_cssci_expansion', False),
                    is_beida_core=j.get('is_beida_core', False),
                    is_network_first=j.get('is_network_first', False),
                    is_enhanced_publishing=j.get('is_enhanced_publishing', False),
                    issn=j.get('issn'),
                    cn=j.get('cn'),
                    publisher=j.get('publisher'),
                    composite_impact_factor=j.get('composite_impact_factor'),
                    comprehensive_impact_factor=j.get('comprehensive_impact_factor'),
                    detail_url=j.get('detail_url'),
                    journal_tags=j.get('journal_tags'),
                    source='CNKI'
                )
                db_session.add(journal)
                added += 1
        except Exception as e:
            print(f"  [DB ERROR] {j.get('name')}: {e}")
            db_session.rollback()

    try:
        db_session.commit()
    except Exception as e:
        print(f"  [DB COMMIT ERROR] {e}")
        db_session.rollback()

    return added, updated


def main(start_page=1):
    print("=" * 70)
    print("CNKI 期刊抓取（完整字段版）")
    print("=" * 70)

    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        db_url = 'postgresql://papertracker:changeme@localhost:15432/papertracker_social'

    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    cookies = parse_cookie()
    session = requests.Session()
    session.cookies.update(cookies)

    total_pages = 553

    if start_page == 1:
        print("\n[1/3] 获取第一页...")
        html = fetch_page(session, 1)
        if not html:
            print("[FAIL] Cookie可能已失效")
            db.close()
            return
        total_pages = get_total_pages(html)
        print(f"  总页数: {total_pages}")

        journals = parse_journals(html)
        print(f"  第1页: {len(journals)} 本")
        a, u = save_to_db(journals, db)
        print(f"  数据库: +{a} 新增, ~{u} 更新")
        start_page = 2
    else:
        print(f"\n[1/3] 断点续传，从第 {start_page} 页开始")
        # 验证Cookie有效性
        html = fetch_page(session, 1)
        if html:
            total_pages = get_total_pages(html)
        print(f"  总页数: {total_pages}")

    print(f"\n[2/3] 抓取第 {start_page} 到 {total_pages} 页...")
    db_total = db.query(Journal).count()

    for page_num in range(start_page, total_pages + 1):
        time.sleep(random_delay())

        html = fetch_page(session, page_num)
        if html:
            page_journals = parse_journals(html)
            a, u = save_to_db(page_journals, db)
            db_total += a

            if page_num <= 5 or page_num % 20 == 0 or page_num == total_pages:
                print(f"  第{page_num}/{total_pages}页: {len(page_journals)} 本 (DB累计: {db_total})")
        else:
            print(f"  [FAIL] 第{page_num}页获取失败")

    print(f"\n[3/3] 完成!")
    final_total = db.query(Journal).count()
    has_detail = db.query(Journal).filter(Journal.detail_url.isnot(None)).count()
    has_tags = db.query(Journal).filter(Journal.journal_tags.isnot(None)).count()
    print(f"  数据库总计: {final_total} 本")
    print(f"  有 detail_url: {has_detail} 本")
    print(f"  有 journal_tags: {has_tags} 本")
    db.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-page', type=int, default=1, help='起始页码')
    args = parser.parse_args()
    main(start_page=args.start_page)
