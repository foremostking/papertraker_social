"""
添加 CNKI 详情字段到 journals 表

执行方式:
    python scripts/add_cnki_detail_fields.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.config import settings
from app.core.database import Database


def add_cnki_detail_fields():
    """添加 CNKI 详情字段到 journals 表"""
    db_instance = Database(settings.DATABASE_URL)
    session = db_instance.SessionLocal()

    # 定义要添加的字段
    fields = [
        ("publishing_cycle", "VARCHAR(50)"),
        ("publishing_location", "VARCHAR(200)"),
        ("language", "VARCHAR(50)"),
        ("format", "VARCHAR(50)"),
        ("postal_code", "VARCHAR(50)"),
        ("founded_year", "INTEGER"),
        ("album_name", "VARCHAR(200)"),
        ("total_documents", "INTEGER"),
        ("total_downloads", "INTEGER"),
        ("total_citations", "INTEGER"),
        ("journal_tags", "TEXT[]"),  # PostgreSQL array type
        ("journal_columns", "TEXT[]"),  # 期刊固定栏目
        ("journal_code", "VARCHAR(50)"),  # CNKI期刊代码
        ("cnki_detail_last_updated", "TIMESTAMP"),
    ]

    try:
        # 检查字段是否已存在
        check_sql = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'journals'
            AND column_name = :field_name
        """)

        for field_name, field_type in fields:
            result = session.execute(check_sql, {"field_name": field_name}).fetchone()

            if not result:
                # 字段不存在，添加它
                alter_sql = text(f"""
                    ALTER TABLE journals
                    ADD COLUMN {field_name} {field_type}
                """)
                session.execute(alter_sql)
                print(f"[OK] Add field: {field_name}")
            else:
                print(f"[SKIP] Field exists: {field_name}")

        session.commit()
        print("\nDatabase fields updated successfully!")

    except Exception as e:
        session.rollback()
        print(f"错误: {e}")
        raise
    finally:
        session.close()


if __name__ == '__main__':
    add_cnki_detail_fields()
