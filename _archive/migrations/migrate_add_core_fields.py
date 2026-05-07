"""
数据库迁移脚本：添加核心期刊标识字段

添加以下字段到 journals 表：
- 中文核心：is_ami, is_cscd
- 国际核心：is_sci, is_ei, is_cas, is_inspec, is_jst, is_paj, is_wjci
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from app.core.database import engine, SessionLocal
from app.models.journal import Journal
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate():
    """执行迁移"""
    logger.info("=" * 60)
    logger.info("开始迁移：添加核心期刊标识字段")
    logger.info("=" * 60)

    # 新增字段列表
    new_columns = [
        # 中文核心
        ("is_ami", "BOOLEAN DEFAULT FALSE"),
        ("is_cscd", "BOOLEAN DEFAULT FALSE"),

        # 国际核心
        ("is_sci", "BOOLEAN DEFAULT FALSE"),
        ("is_ei", "BOOLEAN DEFAULT FALSE"),
        ("is_cas", "BOOLEAN DEFAULT FALSE"),
        ("is_inspec", "BOOLEAN DEFAULT FALSE"),
        ("is_jst", "BOOLEAN DEFAULT FALSE"),
        ("is_paj", "BOOLEAN DEFAULT FALSE"),
        ("is_wjci", "BOOLEAN DEFAULT FALSE"),
    ]

    with engine.connect() as conn:
        # 检查现有列
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'journals'
        """))
        existing_columns = {row[0] for row in result}

        # 添加新列（如果不存在）
        for column_name, column_type in new_columns:
            if column_name not in existing_columns:
                sql = f"ALTER TABLE journals ADD COLUMN {column_name} {column_type}"
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"  [OK] 添加列: {column_name}")
                except Exception as e:
                    logger.error(f"  [FAIL] 添加列 {column_name} 失败: {e}")
                    conn.rollback()
            else:
                logger.info(f"  [SKIP] 列已存在: {column_name}")

        # 创建索引
        index_columns = ['is_ami', 'is_cscd', 'is_sci', 'is_ei', 'is_cas',
                        'is_inspec', 'is_jst', 'is_paj', 'is_wjci']

        for column_name in index_columns:
            index_name = f"ix_journals_{column_name}"
            try:
                # 检查索引是否已存在
                result = conn.execute(text("""
                    SELECT indexname
                    FROM pg_indexes
                    WHERE indexname = :index_name
                """), {"index_name": index_name})

                if result.fetchone() is None:
                    sql = f"CREATE INDEX {index_name} ON journals ({column_name})"
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"  [OK] 创建索引: {index_name}")
                else:
                    logger.info(f"  [SKIP] 索引已存在: {index_name}")
            except Exception as e:
                logger.warning(f"  [WARN] 创建索引 {index_name} 失败: {e}")

    logger.info("=" * 60)
    logger.info("迁移完成！")
    logger.info("=" * 60)

    # 统计现有数据
    db = SessionLocal()
    try:
        total = db.query(Journal).count()
        with_tags = db.query(Journal).filter(
            Journal.journal_tags.isnot(None)
        ).count()

        logger.info(f"期刊总数: {total}")
        logger.info(f"有标签的期刊: {with_tags}")
        logger.info("\n下一步：运行 python scripts/update_journal_cores.py 更新核心期刊标识")

    finally:
        db.close()


if __name__ == '__main__':
    migrate()
