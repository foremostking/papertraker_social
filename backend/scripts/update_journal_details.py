"""
批量更新期刊 CNKI 详情数据

使用方法:
    # 更新所有过期期刊（默认跳过 7 天内已更新的）
    python scripts/update_journal_details.py

    # 更新 10 条记录
    python scripts/update_journal_details.py --limit 10

    # 强制更新所有期刊
    python scripts/update_journal_details.py --force

    # 更新指定期刊
    python scripts/update_journal_details.py --journal-id 1

    # 跳过 3 天内已更新的
    python scripts/update_journal_details.py --skip-days 3

    # 显示详细日志
    python scripts/update_journal_details.py --verbose
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
from app.services.cnki_detail_parser import CNKIDetailParser


def setup_logging(verbose: bool = False):
    """配置日志"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )


def main():
    parser = argparse.ArgumentParser(
        description="更新期刊 CNKI 详情数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--limit', '-l',
        type=int,
        help='更新数量限制'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='强制更新所有期刊（忽略更新时间）'
    )
    parser.add_argument(
        '--journal-id', '-j',
        type=int,
        help='更新指定期刊 ID'
    )
    parser.add_argument(
        '--skip-days', '-s',
        type=int,
        default=7,
        help='增量更新模式下跳过天数（默认 7 天）'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='显示详细日志'
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # 直接初始化数据库连接
    from app.core.config import settings
    from app.core.database import Database
    db_instance = Database(settings.DATABASE_URL)
    db = db_instance.SessionLocal()

    cnki_parser = CNKIDetailParser(db)

    try:
        if args.journal_id:
            # 更新单个期刊
            logger.info(f"开始更新期刊 ID: {args.journal_id}")
            success = cnki_parser.update_journal(args.journal_id)
            if success:
                logger.info("更新成功!")
            else:
                logger.error("更新失败!")
                sys.exit(1)
        else:
            # 批量更新
            limit_str = str(args.limit) if args.limit else "全部"
            force_str = "强制" if args.force else "增量"
            logger.info(
                f"开始批量更新 (数量={limit_str}, 模式={force_str}, "
                f"跳过天数={args.skip_days})..."
            )

            stats = cnki_parser.batch_update(
                limit=args.limit,
                force=args.force,
                skip_days=args.skip_days
            )

            logger.info("=" * 50)
            logger.info("批量更新完成!")
            logger.info(f"  总计: {stats['total']}")
            logger.info(f"  成功: {stats['success']}")
            logger.info(f"  失败: {stats['failed']}")
            logger.info(f"  跳过: {stats['skipped']}")
            logger.info("=" * 50)

            if stats['failed'] > 0:
                sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\n用户中断，正在退出...")
        sys.exit(1)
    except Exception as e:
        logger.error(f"发生错误: {e}")
        raise


if __name__ == '__main__':
    main()
