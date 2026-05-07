"""
安全迁移方案 - 第3步：创建索引

特点：
- 使用 CREATE INDEX CONCURRENTLY（不阻塞读写）
- 可以与现有任务完全并行运行
- 每个索引独立创建，失败不影响其他
"""

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


def migrate_step3():
    """
    第3步：创建索引（使用 CONCURRENTLY，不阻塞）

    操作：
    - 为新增字段创建索引
    - 使用 CONCURRENTLY 选项，不阻塞读写
    - 每个索引独立创建
    """
    logger.info("=" * 60)
    logger.info("安全迁移 - 第3步：创建索引")
    logger.info("=" * 60)

    # 需要创建索引的字段
    index_columns = [
        'is_ami', 'is_cscd', 'is_sci', 'is_ei', 'is_cas',
        'is_inspec', 'is_jst', 'is_paj', 'is_wjci'
    ]

    # 使用 autocommit 连接（CONCURRENTLY 需要在事务外执行）
    from sqlalchemy.engine import Connection
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")

    try:
        # 检查现有索引
        result = conn.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'journals'
        """))
        existing_indexes = {row[0] for row in result}

        logger.info(f"现有索引数: {len(existing_indexes)}")

        for column_name in index_columns:
            index_name = f"ix_journals_{column_name}"

            if index_name in existing_indexes:
                logger.info(f"  [SKIP] {index_name} 已存在")
                continue

            try:
                start_time = time.time()

                # 使用 CONCURRENTLY 创建索引（不阻塞读写）
                sql = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON journals ({column_name})"
                conn.execute(text(sql))

                elapsed = time.time() - start_time
                logger.info(f"  [OK] {index_name} ({elapsed:.1f}s)")

            except Exception as e:
                logger.warning(f"  [WARN] {index_name}: {e}")
                # CONCURRENTLY 可能在某些情况下失败，但不影响数据

    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("第3步完成！索引已创建")
    logger.info("=" * 60)
    logger.info("\n✅ 迁移全部完成！")
    logger.info("\n可以清理临时文件:")
    logger.info("  - scripts/migrate_safe_step*.py")


if __name__ == '__main__':
    migrate_step3()
