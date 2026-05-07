"""
安全迁移总控脚本

一键执行所有步骤，或单独执行指定步骤

使用方法:
    # 执行所有步骤（推荐）
    python scripts/migrate_safe_all.py

    # 只执行第1步
    python scripts/migrate_safe_all.py --step 1

    # 执行第1-2步
    python scripts/migrate_safe_all.py --step 1-2

    # 查看状态
    python scripts/migrate_safe_all.py --status
"""

import os
import sys
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from app.core.database import Database
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 初始化数据库
db_instance = Database(settings.DATABASE_URL)
engine = db_instance.engine


def check_status():
    """检查迁移状态"""
    logger.info("=" * 60)
    logger.info("迁移状态检查")
    logger.info("=" * 60)

    with engine.connect() as conn:
        # 检查字段
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'journals'
            AND column_name IN ('is_ami', 'is_cscd', 'is_sci', 'is_ei', 'is_cas',
                               'is_inspec', 'is_jst', 'is_paj', 'is_wjci')
        """))
        columns = [row[0] for row in result]

        # 检查索引
        result = conn.execute(text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'journals'
            AND indexname LIKE 'ix_journals_is_%'
        """))
        indexes = [row[0] for row in result]

        # 检查数据（只检查已存在的字段）
        if 'is_ami' in columns:
            result = conn.execute(text("""
                SELECT
                    COUNT(*) as total,
                    COUNT(is_ami) as has_ami
                FROM journals
                WHERE journal_tags IS NOT NULL
            """))
            row = result.fetchone()
            total_with_tags = row[0]
            has_data = row[1] if row else 0
        else:
            total_with_tags = 0
            has_data = 0

    logger.info(f"字段添加: {len(columns)}/9")
    logger.info(f"索引创建: {len(indexes)}/9")
    logger.info(f"数据更新: {has_data}/{total_with_tags}")

    # 状态总结
    if len(columns) == 9:
        logger.info("\n[✓] 第1步完成：字段已添加")
    else:
        logger.info(f"\n[ ] 第1步待完成：已添加 {len(columns)}/9 字段")

    if has_data > 0:
        logger.info("[✓] 第2步完成：数据已更新")
    elif len(columns) == 9:
        logger.info("[ ] 第2步待执行：字段已就绪，可以更新数据")
    else:
        logger.info("[ ] 第2步等待：需要先完成第1步")

    if len(indexes) == 9:
        logger.info("[✓] 第3步完成：索引已创建")
    elif len(columns) == 9:
        logger.info(f"[ ] 第3步待执行：已创建 {len(indexes)}/9 索引")
    else:
        logger.info("[ ] 第3步等待：需要先完成第1步")

    logger.info("\n" + "=" * 60)


def run_step(step_num: int):
    """运行指定步骤"""
    step_scripts = {
        1: 'scripts/migrate_safe_step1_add_columns.py',
        2: 'scripts/migrate_safe_step2_update_data.py',
        3: 'scripts/migrate_safe_step3_create_indexes.py',
    }

    if step_num not in step_scripts:
        logger.error(f"无效步骤: {step_num}")
        return False

    script = step_scripts[step_num]
    logger.info(f"执行第{step_num}步: {script}")

    # 使用 subprocess 执行
    import subprocess
    result = subprocess.run(
        [sys.executable, script],
        cwd=str(project_root),
        capture_output=False
    )

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="安全迁移总控脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--step', '-s',
        type=str,
        help='执行指定步骤 (1, 2, 3, 或 1-2)'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='检查迁移状态'
    )
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='执行所有步骤'
    )

    args = parser.parse_args()

    if args.status:
        check_status()
        return

    if args.step:
        # 解析步骤范围
        if '-' in args.step:
            start, end = map(int, args.step.split('-'))
            steps = list(range(start, end + 1))
        else:
            steps = [int(args.step)]

        logger.info(f"将执行步骤: {steps}")

        for step in steps:
            logger.info(f"\n{'='*60}")
            logger.info(f"开始第{step}步")
            logger.info('='*60)

            success = run_step(step)

            if not success:
                logger.error(f"第{step}步失败，停止迁移")
                sys.exit(1)

            logger.info(f"第{step}步完成\n")

        logger.info("=" * 60)
        logger.info("所有指定步骤完成！")
        check_status()

    elif args.all:
        # 执行所有步骤
        for step in [1, 2, 3]:
            logger.info(f"\n{'='*60}")
            logger.info(f"开始第{step}步")
            logger.info('='*60)

            success = run_step(step)

            if not success:
                logger.error(f"第{step}步失败，停止迁移")
                sys.exit(1)

            logger.info(f"第{step}步完成\n")

        logger.info("=" * 60)
        logger.info("✅ 迁移全部完成！")
        check_status()

    else:
        # 默认显示状态
        check_status()
        logger.info("\n使用 --all 执行所有步骤，或 --step N 执行指定步骤")


if __name__ == '__main__':
    main()
