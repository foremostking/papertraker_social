"""
安全迁移方案 - 第1步：添加新字段

特点：
- 只添加字段，不更新数据
- 使用 DEFAULT NULL（不重写表，操作极快）
- 获取锁时间极短（毫秒级），对现有任务影响最小
"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from app.core.config import settings
from app.core.database import Database
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 初始化数据库
db_instance = Database(settings.DATABASE_URL)
engine = db_instance.engine


def migrate_step1():
    """
    第1步：添加新字段（最快、最安全）

    操作：
    - 添加 10 个新字段，默认值 NULL
    - 不创建索引（留给第3步）
    """
    logger.info("=" * 60)
    logger.info("安全迁移 - 第1步：添加新字段")
    logger.info("=" * 60)

    # 新增字段（使用 NULL 默认值，不重写表）
    new_columns = [
        ("is_ami", "BOOLEAN"),
        ("is_cscd", "BOOLEAN"),
        ("is_sci", "BOOLEAN"),
        ("is_ei", "BOOLEAN"),
        ("is_cas", "BOOLEAN"),
        ("is_inspec", "BOOLEAN"),
        ("is_jst", "BOOLEAN"),
        ("is_paj", "BOOLEAN"),
        ("is_wjci", "BOOLEAN"),
    ]

    with engine.connect() as conn:
        # 检查现有列
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'journals'
        """))
        existing_columns = {row[0] for row in result}

        logger.info(f"现有列数: {len(existing_columns)}")

        # 逐个添加列（每个操作独立，失败不影响其他）
        for column_name, column_type in new_columns:
            if column_name in existing_columns:
                logger.info(f"  [SKIP] {column_name} 已存在")
                continue

            try:
                start_time = time.time()
                sql = f"ALTER TABLE journals ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
                conn.execute(text(sql))
                conn.commit()

                elapsed = (time.time() - start_time) * 1000
                logger.info(f"  [OK] {column_name} ({elapsed:.0f}ms)")

            except Exception as e:
                logger.error(f"  [FAIL] {column_name}: {e}")
                conn.rollback()

    logger.info("=" * 60)
    logger.info("第1步完成！字段已添加，数据待更新")
    logger.info("=" * 60)
    logger.info("\n下一步：运行 python scripts/migrate_safe_step2_update_data.py")
    logger.info("（可以与现有任务并行运行）")


if __name__ == '__main__':
    migrate_step1()
