"""
调试解析失败的期刊
"""
import os
import sys
sys.path.insert(0, '/app')

import requests
from bs4 import BeautifulSoup

def debug_journal_page(detail_url: str):
    """调试单个期刊页面"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    response = requests.get(detail_url, headers=headers, timeout=30)
    response.encoding = 'utf-8'

    soup = BeautifulSoup(response.text, 'html.parser')

    print(f"URL: {detail_url[:80]}...")
    print(f"状态码: {response.status_code}")

    # 查找期刊信息容器
    dd = soup.find('dl', class_='journalInfo')
    print(f"journalInfo容器: {'找到' if dd else '未找到'}")

    # 查找其他可能的容器
    journal_info = soup.find('dd', class_='journal-info')
    print(f"journal-info容器: {'找到' if journal_info else '未找到'}")

    # 检查是否有错误页面
    if 'error' in response.text.lower() or '异常' in response.text:
        print("⚠️ 页面可能包含错误信息")

    # 检查是否需要登录
    if '登录' in response.text or 'login' in response.text.lower():
        print("⚠️ 页面可能需要登录")

    # 查找任何 dl 标签
    all_dl = soup.find_all('dl')
    print(f"页面中 dl 标签数量: {len(all_dl)}")

    # 查找任何 dd 标签
    all_dd = soup.find_all('dd')
    print(f"页面中 dd 标签数量: {len(all_dd)}")

    # 显示页面标题
    title = soup.find('title')
    if title:
        print(f"页面标题: {title.get_text(strip=True)}")

    # 检查是否有期刊名称
    journal_name = soup.find('h1')
    if journal_name:
        print(f"期刊名称: {journal_name.get_text(strip=True)}")

    print()

# 从数据库获取这些失败的期刊
from app.core.config import settings
from app.core.database import Database
from app.models.journal import Journal

db_instance = Database(settings.DATABASE_URL)
db = db_instance.SessionLocal()

# 获取前5个失败的期刊
journals = db.query(Journal).filter(
    Journal.detail_url.isnot(None),
    Journal.field.is_(None)
).limit(5).all()

print("=== 调试解析失败的期刊 ===\n")

for journal in journals:
    print(f"\n期刊: {journal.name} (ID: {journal.id})")
    debug_journal_page(journal.detail_url)
