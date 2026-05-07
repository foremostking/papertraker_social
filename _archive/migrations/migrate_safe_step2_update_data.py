"""
安全迁移方案 - 第2步：更新数据

特点：
- 只读取 journal_tags 字段
- 批量更新，每次提交一批
- 可以与现有任务完全并行运行
- 支持断点续传
"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from app.core.config import settings
from app.core.database import Database
from app.models.journal import Journal
from app.services.journal_core_parser import JournalCoreParser
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化数据库
db_instance = Database(settings.DATABASE_URL)
SessionLocal = db_instance.SessionLocal


def migrate_step2(batch_size: int = 100):
    """
    第2步：从 journal_tags 解析并更新核心期刊标识

    操作：
    - 读取 journal_tags
    - 解析核心期刊标识
    - 更新新字段
    - 分批提交，避免长事务

    Args:
        batch_size: 每批处理的数量
    """
    logger.info("=" * 60)
    logger.info("安全迁移 - 第2步：更新数据")
    logger.info("=" * 60)

    db = SessionLocal()

    try:
        # 统计信息
        total_journals = db.query(Journal).count()
        with_tags = db.query(Journal).filter(
            Journal.journal_tags.isnot(None)
        ).count()
        needs_update = db.query(Journal).filter(
            Journal.journal_tags.isnot(None),
            Journal.is_ami.is_(None)  # 任一字段为空说明需要更新
        ).count()

        logger.info(f"期刊总数: {total_journals}")
        logger.info(f"有标签的期刊: {with_tags}")
        logger.info(f"待更新: {needs_update}")
        logger.info(f"批次大小: {batch_size}")

        if needs_update == 0:
            logger.info("\n没有需要更新的数据，跳过第2步")
            return

        # 分批处理
        updated = 0
        skipped = 0
        batches = (needs_update + batch_size - 1) // batch_size

        for batch_num in range(batches):
            logger.info(f"\n处理批次 {batch_num + 1}/{batches}...")

            # 查询一批待更新的期刊
            journals = db.query(Journal).filter(
                Journal.journal_tags.isnot(None),
                Journal.is_ami.is_(None)
            ).limit(batch_size).all()

            for journal in journals:
                try:
                    # 解析标签
                    core_flags = JournalCoreParser.parse_tags(journal.journal_tags)

                    # 更新字段
                    for field, value in core_flags.items():
                        if hasattr(journal, field):
                            setattr(journal, field, value)

                    updated += 1

                except Exception as e:
                    logger.warning(f"  更新 {journal.name} 失败: {e}")
                    skipped += 1

            # 提交这一批
            try:
                db.commit()
                logger.info(f"  批次完成: +{len(journals)} 条记录")
            except Exception as e:
                logger.error(f"  批次提交失败: {e}")
                db.rollback()

        logger.info("\n" + "=" * 60)
        logger.info("第2步完成！")
        logger.info("=" * 60)
        logger.info(f"更新成功: {updated}")
        logger.info(f"跳过: {skipped}")

        # 统计更新后的核心期刊分布
        logger.info("\n核心期刊分布:")

        core_fields = {
            'CSSCI': 'is_cssci',
            'CSSCI扩展': 'is_cssci_expansion',
            '北大核心': 'is_beida_core',
            'AMI': 'is_ami',
            'CSCD': 'is_cscd',
            'SCI': 'is_sci',
            'EI': 'is_ei',
        }

        for name, field in core_fields.items():
            count = db.query(Journal).filter(
                getattr(Journal, field) == True
            ).count()
            if count > 0:
                logger.info(f"  {name}: {count} 本")

    except Exception as e:
        logger.error(f"第2步失败: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()

    finally:
        db.close()

    logger.info("\n下一步：运行 python scripts/migrate_safe_step3_create_indexes.py")
    logger.info("（可以与现有任务并行运行）")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="安全迁移第2步：更新数据")
    parser.add_argument('--batch-size', '-b', type=int, default=100,
                       help='每批处理数量（默认100）')
    args = parser.parse_args()

    migrate_step2(batch_size=args.batch_size)
