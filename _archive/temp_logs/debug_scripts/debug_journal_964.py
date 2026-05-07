"""
调试期刊ID 964的CNKI解析
"""
import os
import sys
sys.path.insert(0, '/app')

from app.core.database import Database
from app.models.journal import Journal
from app.services.cnki_detail_parser import CNKIDetailParser
from app.core.config import settings

def debug_journal_964():
    """调试解析期刊ID 964"""
    db_instance = Database(settings.DATABASE_URL)
    db = db_instance.SessionLocal()

    journal = db.query(Journal).filter(Journal.id == 964).first()
    if not journal:
        print("未找到期刊ID 964")
        return

    print(f"期刊名称: {journal.name}")
    print(f"详情URL: {journal.detail_url}")
    print()

    parser = CNKIDetailParser(db, min_delay=0, max_delay=0)
    info = parser.parse_detail_page(journal.detail_url)

    print("解析结果:")
    for key, value in info.items():
        if key != 'error':
            print(f"  {key}: {value}")

    if 'field' not in info:
        print("\n⚠️ 没有提取到 field (一级学科/专辑名称)")
    if 'subfield' not in info:
        print("⚠️ 没有提取到 subfield (二级学科/专题名称)")

if __name__ == "__main__":
    debug_journal_964()
