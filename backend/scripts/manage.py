#!/usr/bin/env python
"""
PaperTracker 数据管理工具

统一的命令行界面，用于管理期刊数据、CSSCI列表等。

使用方法:
    # 更新期刊详情
    python scripts/manage.py update-details [options]

    # 获取CSSCI期刊列表
    python scripts/manage.py fetch-cssci [options]

    # 获取CNKI期刊列表
    python scripts/manage.py fetch-journals [options]

    # 更新期刊核心信息
    python scripts/manage.py update-cores [options]

    # 查询期刊
    python scripts/manage.py query [options]

    # 显示帮助
    python scripts/manage.py --help
    python scripts/manage.py <command> --help
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
from typing import Optional


def setup_logging(verbose: bool = False):
    """配置日志"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )


def cmd_update_details(args):
    """更新期刊详情"""
    from app.services.cnki_detail_parser import CNKIDetailParser
    from app.core.config import settings
    from app.core.database import Database

    logger = logging.getLogger(__name__)

    db_instance = Database(settings.DATABASE_URL)
    db = db_instance.SessionLocal()

    cnki_parser = CNKIDetailParser(db)

    try:
        if args.journal_id:
            logger.info(f"开始更新期刊 ID: {args.journal_id}")
            success = cnki_parser.update_journal(args.journal_id)
            if success:
                logger.info("更新成功!")
            else:
                logger.error("更新失败!")
                return 1
        else:
            limit_str = str(args.limit) if args.limit else "全部"
            force_str = "强制" if args.force else "增量"
            logger.info(
                f"开始批量更新 (数量={limit_str}, 模式={force_str})..."
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
                return 1

    except KeyboardInterrupt:
        logger.info("\n用户中断，正在退出...")
        return 1
    except Exception as e:
        logger.error(f"发生错误: {e}")
        raise


def cmd_fetch_cssci(args):
    """获取CSSCI期刊列表"""
    logger = logging.getLogger(__name__)
    logger.info("正在获取CSSCI期刊列表...")

    # 动态导入以避免不必要的依赖
    import scripts.fetch_all_cssci_with_anti_detection as cssci_fetcher

    # 调用主函数
    sys.argv = ['fetch_cssci']  # 重置参数
    cssci_fetcher.main()


def cmd_fetch_journals(args):
    """获取CNKI期刊列表"""
    logger = logging.getLogger(__name__)
    logger.info("正在获取CNKI期刊列表...")

    import scripts.fetch_all_journals as journal_fetcher
    sys.argv = ['fetch_journals']
    journal_fetcher.main()


def cmd_update_cores(args):
    """更新期刊核心信息"""
    logger = logging.getLogger(__name__)
    logger.info("正在更新期刊核心信息...")

    import scripts.update_journal_cores as core_updater
    sys.argv = ['update_cores']
    core_updater.main()


def cmd_query(args):
    """查询期刊"""
    import scripts.query_journals as query_tool
    sys.argv = ['query']
    query_tool.main()


def main():
    parser = argparse.ArgumentParser(
        description="PaperTracker 数据管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='显示详细日志'
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # update-details 命令
    update_details_parser = subparsers.add_parser(
        'update-details',
        help='更新期刊详情（field、subfield等）'
    )
    update_details_parser.add_argument(
        '--limit', '-l',
        type=int,
        help='更新数量限制'
    )
    update_details_parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='强制更新所有期刊（忽略已有数据）'
    )
    update_details_parser.add_argument(
        '--journal-id', '-j',
        type=int,
        help='更新指定期刊 ID'
    )
    update_details_parser.add_argument(
        '--skip-days', '-s',
        type=int,
        default=7,
        help='跳过 N 天内已更新的期刊（默认 7）'
    )

    # fetch-cssci 命令
    subparsers.add_parser('fetch-cssci', help='获取CSSCI期刊列表')

    # fetch-journals 命令
    subparsers.add_parser('fetch-journals', help='获取CNKI期刊列表')

    # update-cores 命令
    subparsers.add_parser('update-cores', help='更新期刊核心信息')

    # query 命令
    subparsers.add_parser('query', help='查询期刊数据')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    setup_logging(args.verbose)

    # 命令映射
    commands = {
        'update-details': cmd_update_details,
        'fetch-cssci': cmd_fetch_cssci,
        'fetch-journals': cmd_fetch_journals,
        'update-cores': cmd_update_cores,
        'query': cmd_query,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        return cmd_func(args)
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main() or 0)
