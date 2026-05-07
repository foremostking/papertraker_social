"""
CNKI期刊详情页并发抓取（6线程 + 断点续传）

反爬策略：
- 6个线程并发
- 每线程内部 2-5 秒随机延迟
- User-Agent 轮换
- 断点续传：每 100 本自动保存进度
- Cookie 失效检测：自动退出并保存断点
"""
import os
import sys
import re
import time
import random
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.journal import Journal

# 用户Cookie
COOKIE_STR = "Ecp_ClientId=_vqrnqik__caByTET4758758s8HvEM9n0VHXDg7Gd7; SID_navi=018110; cnkiUserKey=e152802a-81bb-45ea-1563-56419bc6c85d; Ecp_IpLoginFail=26050739.144.210.22"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# 字段映射
FIELD_MAPPING = {
    '主办单位': 'publisher',
    '出版周期': 'publishing_cycle',
    '出版地': 'publishing_location',
    '语种': 'language',
    '开本': 'format',
    '邮发代号': 'postal_code',
    '创刊时间': 'founded_year',
    '专辑名称': 'field',
    '专题名称': 'subfield',
    '出版文献量': 'total_documents',
    '总下载次数': 'total_downloads',
    '总被引次数': 'total_citations',
}

PATTERNS = {
    '主办单位': r'主办单位[::：\s]*([\u4e00-\u9fa5a-zA-Z\d()（）]{3,80})',
    '出版周期': r'出版周期[::：\s]*([\u4e00-\u9fa5a-zA-Z\d()（）]{2,10})',
    '出版地': r'出版地[::：\s]*([\u4e00-\u9fa5\d()（）]{2,50})',
    '语种': r'语种[::：\s]*([\u4e00-\u9fa5a-zA-Z\d()（）]{2,10})',
    '开本': r'开本[::：\s]*([\u4e00-\u9fa5\d()（）]{2,10})',
    '邮发代号': r'邮发代号[::：\s]*([\d-]{1,10})',
    '创刊时间': r'创刊时间[::：\s]*(\d{4})',
    '出版文献量': r'出版文献量[::：\s]*([\d,]+)',
    '总下载次数': r'总下载次数[::：\s]*([\d,]+)',
    '总被引次数': r'总被引次数[::：\s]*([\d,]+)',
}

# 全局锁和统计
lock = threading.Lock()
stats = {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0, 'cookie_invalid': False}


def parse_cookie():
    cookies = {}
    for pair in COOKIE_STR.split(';'):
        pair = pair.strip()
        if '=' in pair:
            k, v = pair.split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies


def random_delay():
    return random.uniform(2.0, 5.0)


def fetch_detail(url: str) -> Optional[str]:
    """获取详情页HTML"""
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': random.choice(['zh-CN,zh;q=0.9', 'zh-CN,zh;q=0.9,en;q=0.8']),
        'Referer': 'https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT',
    }
    cookies = parse_cookie()

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, cookies=cookies, timeout=20)
            if resp.status_code == 200:
                text = resp.text
                # 检测Cookie失效
                if 'verify' in text.lower() or 'captcha' in text.lower() or '验证' in text:
                    with lock:
                        stats['cookie_invalid'] = True
                    return None
                return text
            elif resp.status_code == 403:
                with lock:
                    stats['cookie_invalid'] = True
                return None
        except Exception as e:
            pass
        if attempt < 2:
            time.sleep(random.uniform(5.0, 10.0))
    return None


def parse_detail_page(html: str) -> Dict:
    """解析详情页"""
    info = {}
    soup = BeautifulSoup(html, 'html.parser')

    # 查找期刊信息容器
    dd = soup.find('dl', class_='journalInfo')
    if not dd:
        dd = soup.find('dd', class_='journal-info')
    if not dd:
        all_dd = soup.find_all('dd')
        for d in all_dd:
            text = d.get_text(strip=True)
            if len(text) > 50 and ('主办单位' in text or '出版周期' in text):
                dd = d
                break

    if not dd:
        return {'error': '无法找到期刊信息'}

    text = dd.get_text(separator=' ', strip=True)

    # 逐个匹配字段
    for field, pattern in PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip()
            value = re.sub(r'^[:：\s]+', '', value)
            if field in ['创刊时间', '出版文献量', '总下载次数', '总被引次数']:
                value = value.replace(',', '')
                if value.isdigit():
                    info[FIELD_MAPPING[field]] = int(value)
            else:
                info[FIELD_MAPPING[field]] = value

    # 专门处理专辑/专题名称
    if '专辑名称：' in text or '专辑名称:' in text:
        album_match = re.search(r'专辑名称[::：]\s*([^；;]+?)(?:[；;]|\s*(?:专题名称|$))', text)
        if album_match:
            info['field'] = album_match.group(1).strip()

    if '专题名称：' in text or '专题名称:' in text:
        subject_match = re.search(r'专题名称[::：]\s*([^；;]+?)(?:[；;]|\s*$)', text)
        if subject_match:
            info['subfield'] = subject_match.group(1).strip()

    # 通过span id提取
    ji_name = soup.find('span', id='jiName')
    if ji_name:
        info['field'] = ji_name.get_text(strip=True)

    ti_name = soup.find('span', id='tiName')
    if ti_name:
        info['subfield'] = ti_name.get_text(strip=True)

    # 提取期刊标签
    journal_type2 = soup.find('p', class_='journalType2')
    if journal_type2:
        tags_text = journal_type2.get_text(strip=True)
        info['journal_tags'] = tags_text.split()

    info['cnki_detail_last_updated'] = datetime.now()
    return info


def save_progress(progress_file: str, last_id: int):
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump({'last_processed_id': last_id, 'timestamp': datetime.now().isoformat()}, f)


def load_progress(progress_file: str) -> int:
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('last_processed_id', 0)
        except:
            pass
    return 0


def process_journal(journal_data: Dict, db_url: str, progress_file: str):
    """处理单本期刊"""
    if stats['cookie_invalid']:
        return

    time.sleep(random_delay())

    journal_id = journal_data['id']
    detail_url = journal_data['detail_url']
    name = journal_data['name']

    html = fetch_detail(detail_url)
    if not html:
        with lock:
            stats['failed'] += 1
        return

    info = parse_detail_page(html)
    if 'error' in info:
        with lock:
            stats['failed'] += 1
        return

    # 更新数据库
    try:
        engine = create_engine(db_url)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        journal = db.query(Journal).filter(Journal.id == journal_id).first()
        if journal:
            for key, value in info.items():
                if key != 'error' and hasattr(journal, key):
                    setattr(journal, key, value)
            db.commit()

        db.close()

        with lock:
            stats['success'] += 1

        # 保存进度（每100本）
        if stats['success'] % 100 == 0:
            save_progress(progress_file, journal_id)

    except Exception as e:
        with lock:
            stats['failed'] += 1


def main():
    print("=" * 70)
    print("CNKI 期刊详情页并发抓取（6线程 + 断点续传）")
    print("=" * 70)

    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        db_url = 'postgresql://papertracker:changeme@localhost:15432/papertracker_social'

    progress_file = 'data/detail_fetch_progress.json'
    last_id = load_progress(progress_file)

    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    # 查询需要更新的期刊（有detail_url 且 没有field）
    query = db.query(Journal).filter(
        Journal.detail_url.isnot(None),
        Journal.field.is_(None)
    )

    if last_id > 0:
        query = query.filter(Journal.id > last_id)
        print(f"[断点续传] 从 ID {last_id} 之后继续")

    journals = query.all()
    stats['total'] = len(journals)
    print(f"[待处理] 共 {len(journals)} 本期刊需要补充详情")
    print(f"[并发] 6 线程，每线程延迟 2-5 秒")
    print("")

    # 准备数据
    journal_data_list = [
        {'id': j.id, 'detail_url': j.detail_url, 'name': j.name}
        for j in journals
    ]

    db.close()

    # 6线程并发
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(process_journal, jd, db_url, progress_file): jd
            for jd in journal_data_list
        }

        for future in as_completed(futures):
            if stats['cookie_invalid']:
                print("\n[警告] Cookie 已失效，停止抓取...")
                executor.shutdown(wait=False)
                break

            # 每50本输出一次进度
            completed = stats['success'] + stats['failed']
            if completed % 50 == 0:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                remaining = stats['total'] - completed
                eta = remaining / rate if rate > 0 else 0
                print(f"  进度: {completed}/{stats['total']} | 成功: {stats['success']} | 失败: {stats['failed']} | 速度: {rate:.1f}本/秒 | ETA: {eta/60:.0f}分钟")

    # 最终统计
    print(f"\n{'=' * 70}")
    print("抓取完成!")
    print(f"  总计: {stats['total']}")
    print(f"  成功: {stats['success']}")
    print(f"  失败: {stats['failed']}")
    print(f"  Cookie失效: {stats['cookie_invalid']}")

    if stats['cookie_invalid']:
        print(f"\n[断点] 进度已保存到 {progress_file}")
        print("[提示] 请重新获取 Cookie 后再次运行脚本继续")

    # 验证结果
    db = SessionLocal()
    has_field = db.query(Journal).filter(Journal.field.isnot(None)).count()
    print(f"\n[验证] 数据库中有 {has_field} 本期刊已补充学科分类")
    db.close()


if __name__ == '__main__':
    main()
