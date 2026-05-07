"""
批量更新期刊核心期刊标识

从 journal_tags 字段解析并更新核心期刊标识字段
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.database import SessionLocal
from app.models.journal import Journal
from app.services.journal_core_parser import batch_update_journals
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("批量更新期刊核心期刊标识")
    logger.info("=" * 60)

    db = SessionLocal()

    try:
        # 先统计现有数据
        total = db.query(Journal).count()
        with_tags = db.query(Journal).filter(
            Journal.journal_tags.isnot(None)
        ).count()

        logger.info(f"期刊总数: {total}")
        logger.info(f"有标签的期刊: {with_tags}")

        # 显示一些示例标签
        sample_journals = db.query(Journal).filter(
            Journal.journal_tags.isnot(None)
        ).limit(5).all()

        if sample_journals:
            logger.info("\n示例期刊标签:")
            for j in sample_journals:
                logger.info(f"  {j.name}: {j.journal_tags}")

        # 执行批量更新
        logger.info("\n开始批量更新...")

        stats = batch_update_journals(db, limit=None, force=False)

        logger.info("\n" + "=" * 60)
        logger.info("更新统计:")
        logger.info("=" * 60)
        logger.info(f"  处理总数: {stats['total']}")
        logger.info(f"  更新成功: {stats['updated']}")
        logger.info(f"  跳过: {stats['skipped']}")
        logger.info(f"  无标签: {stats.get('no_tags', 0)}")
        logger.info(f"  错误: {stats['errors']}")

        # 显示更新后的统计
        logger.info("\n更新后核心期刊分布:")

        core_fields = {
            'CSSCI': 'is_cssci',
            'CSSCI扩展': 'is_cssci_expansion',
            '北大核心': 'is_beida_core',
            'AMI': 'is_ami',
            'CSCD': 'is_cscd',
            'SCI': 'is_sci',
            'EI': 'is_ei',
            'CAS': 'is_cas',
            'INSPEC': 'is_inspec',
            'JST': 'is_jst',
            'Pж(AJ)': 'is_paj',
            'WJCI': 'is_wjci',
        }

        for name, field in core_fields.items():
            count = db.query(Journal).filter(
                getattr(Journal, field) == True
            ).count()
            if count > 0:
                logger.info(f"  {name}: {count} 本")

    except Exception as e:
        logger.error(f"批量更新失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        db.close()


if __name__ == '__main__':
    main()
