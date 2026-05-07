"""
添加 journal_columns_detail 字段到 journals 表

使用方式:
    python scripts/add_journal_columns_detail_field.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import Database
from app.core.config import settings
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_journal_columns_detail_field():
    """添加 journal_columns_detail 字段"""
    db = Database(settings.DATABASE_URL)
    engine = db.engine

    # 检查字段是否已存在
    check_sql = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'journals'
        AND column_name = 'journal_columns_detail';
    """)

    with engine.connect() as conn:
        result = conn.execute(check_sql).fetchone()

        if result and result[0] == 'journal_columns_detail':
            logger.info("字段 journal_columns_detail 已存在，跳过创建")
            return

    # 添加字段
    add_sql = text("""
        ALTER TABLE journals
        ADD COLUMN IF NOT EXISTS journal_columns_detail JSONB;
    """)

    try:
        with engine.begin() as conn:
            conn.execute(add_sql)
        logger.info("成功添加 journal_columns_detail 字段")
    except Exception as e:
        logger.error(f"添加字段失败: {e}")
        raise


if __name__ == '__main__':
    add_journal_columns_detail_field()
