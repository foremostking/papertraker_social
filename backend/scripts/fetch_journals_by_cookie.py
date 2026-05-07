"""
使用Cookie批量抓取CNKI期刊数据
"""
import os
import sys
import re
import json
import time
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.journal import Journal

# 用户提供的Cookie
COOKIE_STR = "Ecp_ClientId=_vqrnqik__caByTET4758758s8HvEM9n0VHXDg7Gd7; SID_navi=018110; cnkiUserKey=e152802a-81bb-45ea-1563-56419bc6c85d; Ecp_IpLoginFail=26050739.144.210.22"

HEADERS = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}


def parse_cookie() -> dict:
    cookies = {}
    for pair in COOKIE_STR.split(';'):
        pair = pair.strip()
        if '=' in pair:
            k, v = pair.split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies


def fetch_page(page_num: int, click_name: str = '', cookies: dict = None) -> Optional[str]:
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

    try:
        resp = requests.post(url, data=data, headers=HEADERS, cookies=cookies, timeout=20)
        if resp.status_code == 200:
            return resp.text
        else:
            print(f"  [HTTP {resp.status_code}] 第{page_num}页")
            return None
    except Exception as e:
        print(f"  [ERROR] 第{page_num}页: {e}")
        return None


def parse_journals(html: str) -> List[Dict]:
    journals = []
    # 提取期刊条目
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
            print(f"  [DB ERROR] {j['name']}: {e}")
            db_session.rollback()

    try:
        db_session.commit()
    except Exception as e:
        print(f"  [DB COMMIT ERROR] {e}")
        db_session.rollback()

    return added, updated


def main():
    print("=" * 70)
    print("CNKI 期刊批量抓取（Cookie模式）")
    print("=" * 70)

    # 连接数据库
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        # 尝试从 .env 文件加载
        try:
            from dotenv import load_dotenv
            load_dotenv('.env')
            db_url = os.getenv('DATABASE_URL')
        except:
            pass
    if not db_url:
        # 使用默认配置
        db_url = 'postgresql://papertracker:changeme@localhost:15432/papertracker_social'
        print(f"[INFO] 使用默认数据库配置")

    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    cookies = parse_cookie()
    print(f"\nCookie 信息:")
    for k, v in cookies.items():
        print(f"  {k}: {v[:40]}...")

    # 抓取第一页获取总页数
    print("\n[1/3] 获取第一页...")
    html = fetch_page(1, cookies=cookies)
    if not html:
        print("[FAIL] 无法获取第一页，Cookie可能已失效")
        db.close()
        return

    total_pages = get_total_pages(html)
    print(f"  总页数: {total_pages}")

    journals = parse_journals(html)
    print(f"  第1页: {len(journals)} 本期刊")

    added, updated = save_journals_to_db(journals, db)
    print(f"  数据库: +{added} 新增, ~{updated} 更新")

    all_journals = journals.copy()

    # 批量抓取剩余页面
    print(f"\n[2/3] 开始批量抓取剩余 {total_pages - 1} 页...")
    for page_num in range(2, total_pages + 1):
        delay = 1.5 + (page_num % 2) * 0.5
        time.sleep(delay)

        html = fetch_page(page_num, cookies=cookies)
        if html:
            page_journals = parse_journals(html)
            all_journals.extend(page_journals)
            a, u = save_journals_to_db(page_journals, db)
            if page_num <= 5 or page_num % 10 == 0:
                print(f"  第{page_num}/{total_pages}页: {len(page_journals)} 本 (累计: {len(all_journals)})")
        else:
            print(f"  [FAIL] 第{page_num}页获取失败")

    # 统计
    print(f"\n[3/3] 抓取完成!")
    print(f"  总计抓取: {len(all_journals)} 本期刊")

    db_total = db.query(Journal).count()
    db_cssci = db.query(Journal).filter(Journal.is_cssci == True).count()
    print(f"  数据库总计: {db_total} 本")
    print(f"  其中 CSSCI: {db_cssci} 本")

    db.close()


if __name__ == '__main__':
    main()
