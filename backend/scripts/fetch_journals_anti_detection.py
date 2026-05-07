"""
CNKI期刊批量抓取（反爬虫增强版）

反爬策略：
- User-Agent 轮换池（8个）
- 随机延迟（2-5秒，偶尔7-12秒）
- 随机请求头组合
- 使用 Session 保持连接
- 自动重试（最多3次）
- 支持断点续传
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

# 用户提供的Cookie
COOKIE_STR = "Ecp_ClientId=_vqrnqik__caByTET4758758s8HvEM9n0VHXDg7Gd7; SID_navi=018110; cnkiUserKey=e152802a-81bb-45ea-1563-56419bc6c85d; Ecp_IpLoginFail=26050739.144.210.22"

# User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 OPR/105.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

ACCEPT_HEADERS = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
]


def get_random_headers() -> dict:
    """生成随机请求头"""
    return {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT',
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': random.choice(ACCEPT_HEADERS),
        'Accept-Language': random.choice(['zh-CN,zh;q=0.9', 'zh-CN,zh;q=0.9,en;q=0.8', 'zh-CN,zh-HK;q=0.9,zh;q=0.8']),
        'Accept-Encoding': 'gzip, deflate, br',
        'Origin': 'https://navi.cnki.net',
        'Connection': 'keep-alive',
    }


def parse_cookie() -> dict:
    cookies = {}
    for pair in COOKIE_STR.split(';'):
        pair = pair.strip()
        if '=' in pair:
            k, v = pair.split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies


def random_delay() -> float:
    """随机延迟，模拟人类行为"""
    base = random.uniform(2.0, 5.0)
    # 偶尔停顿更久（模拟阅读/思考）
    if random.random() < 0.1:
        base += random.uniform(3.0, 8.0)
    return base


def fetch_page(session: requests.Session, page_num: int, click_name: str = '') -> Optional[str]:
    """获取单页，带重试"""
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
        'displaymode': '1',
        'pageindex': str(page_num),
        'pagecount': '21',
        'index': 'JSTMWT6S',
        'searchType': '刊名(曾用刊名)',
        'parentcode': 'SQN63324',
        'switchdata': 'clickTabSearch',
    }
    if click_name:
        data['clickName'] = click_name

    for attempt in range(3):
        try:
            headers = get_random_headers()
            resp = session.post(url, data=data, headers=headers, timeout=25)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 403:
                print(f"  [HTTP 403] 第{page_num}页 - Cookie可能已失效")
                return None
            else:
                print(f"  [HTTP {resp.status_code}] 第{page_num}页 (重试{attempt+1}/3)")
        except Exception as e:
            print(f"  [ERROR] 第{page_num}页: {e} (重试{attempt+1}/3)")

        if attempt < 2:
            time.sleep(random.uniform(5.0, 10.0))

    return None


def parse_journals(html: str) -> List[Dict]:
    journals = []
    items = re.findall(
        r'<a[^>]*href="https://navi\.cnki\.net/knavi/detail\?p=([^"]+)"[^>]*title="([^"]+)"[^>]*>.*?<div class="detials">\s*<h1>\s*([^<]+)</h1>(.*?)</div>\s*</a>',
        html, re.DOTALL
    )

    for encoded_url, title_attr, name, details in items:
        j = {'name': name.strip()}
        tags = re.findall(r'<span>([^<]+)</span>', details)
        j['tags'] = [t.strip() for t in tags]

        cf = re.search(r'复合影响因子[：:]([\d.]+)', details)
        if cf:
            j['composite_impact_factor'] = float(cf.group(1))

        ci = re.search(r'综合影响因子[：:]([\d.]+)', details)
        if ci:
            j['comprehensive_impact_factor'] = float(ci.group(1))

        issn = re.search(r'ISSN[：:]([\dA-Z\-]+)', details)
        if issn:
            j['issn'] = issn.group(1).strip()

        cn = re.search(r'CN[：:]([\dA-Z\-/]+)', details)
        if cn:
            j['cn'] = cn.group(1).strip()

        pub = re.search(r'主办单位[：:]([^<]+)', details)
        if pub:
            j['publisher'] = pub.group(1).strip()[:200]

        j['is_cssci'] = any('CSSCI' in t for t in j.get('tags', []))
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


def save_journals_to_db(journals: List[Dict], db_session):
    added = 0
    updated = 0
    for j in journals:
        try:
            existing = db_session.query(Journal).filter(Journal.name == j['name']).first()
            if existing:
                existing.is_cssci = j.get('is_cssci', True)
                existing.issn = j.get('issn') or existing.issn
                existing.cn = j.get('cn') or existing.cn
                existing.publisher = j.get('publisher') or existing.publisher
                if 'composite_impact_factor' in j:
                    existing.composite_impact_factor = j['composite_impact_factor']
                if 'comprehensive_impact_factor' in j:
                    existing.comprehensive_impact_factor = j['comprehensive_impact_factor']
                existing.source = 'CNKI'
                updated += 1
            else:
                journal = Journal(
                    name=j['name'],
                    is_cssci=j.get('is_cssci', True),
                    issn=j.get('issn'),
                    cn=j.get('cn'),
                    publisher=j.get('publisher'),
                    composite_impact_factor=j.get('composite_impact_factor'),
                    comprehensive_impact_factor=j.get('comprehensive_impact_factor'),
                    source='CNKI'
                )
                db_session.add(journal)
                added += 1
        except Exception as e:
            db_session.rollback()

    try:
        db_session.commit()
    except Exception as e:
        print(f"  [DB COMMIT ERROR] {e}")
        db_session.rollback()

    return added, updated


def main(start_page: int = 1, max_pages: Optional[int] = None):
    print("=" * 70)
    print("CNKI 期刊批量抓取（反爬虫增强版）")
    print("=" * 70)
    print(f"\n反爬策略:")
    print(f"  - User-Agent池: {len(USER_AGENTS)}个")
    print(f"  - 随机延迟: 2-5秒（偶尔+3-8秒）")
    print(f"  - 自动重试: 最多3次")
    print(f"  - 断点续传: 从第{start_page}页开始")

    # 数据库
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        try:
            from dotenv import load_dotenv
            load_dotenv('.env')
            db_url = os.getenv('DATABASE_URL')
        except:
            pass
    if not db_url:
        db_url = 'postgresql://papertracker:changeme@localhost:15432/papertracker_social'

    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    cookies = parse_cookie()
    session = requests.Session()
    session.cookies.update(cookies)

    # 获取第一页（如果从头开始）
    total_pages = 0
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
        a, u = save_journals_to_db(journals, db)
        print(f"  数据库: +{a} 新增, ~{u} 更新")
        start_page = 2
    else:
        # 如果从中断开始，先获取第一页来知道总页数
        html = fetch_page(session, 1)
        if html:
            total_pages = get_total_pages(html)
        print(f"\n[1/3] 断点续传，从第{start_page}页开始 (总页数: {total_pages})")

    if max_pages and total_pages:
        total_pages = min(total_pages, max_pages)

    # 抓取剩余页面
    print(f"\n[2/3] 抓取第 {start_page} 到 {total_pages} 页...")
    all_count = db.query(Journal).count()

    for page_num in range(start_page, total_pages + 1):
        delay = random_delay()
        time.sleep(delay)

        html = fetch_page(session, page_num)
        if html:
            page_journals = parse_journals(html)
            a, u = save_journals_to_db(page_journals, db)
            all_count += a

            if page_num <= 5 or page_num % 10 == 0 or page_num == total_pages:
                print(f"  第{page_num}/{total_pages}页: {len(page_journals)} 本 (累计DB: {all_count})")
        else:
            print(f"  [FAIL] 第{page_num}页获取失败，跳过")

    # 统计
    print(f"\n[3/3] 抓取完成!")
    db_total = db.query(Journal).count()
    db_cssci = db.query(Journal).filter(Journal.is_cssci == True).count()
    print(f"  数据库总计: {db_total} 本")
    print(f"  其中 CSSCI: {db_cssci} 本")
    db.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-page', type=int, default=1, help='起始页码（断点续传）')
    parser.add_argument('--max-pages', type=int, default=None, help='最大抓取页数')
    args = parser.parse_args()
    main(start_page=args.start_page, max_pages=args.max_pages)
