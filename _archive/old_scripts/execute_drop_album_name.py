"""
执行删除 album_name 字段的迁移

安全检查步骤：
1. 确认所有 album_name 已同步到 field
2. 执行数据库迁移
3. 验证结果
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import Database
from app.core.config import settings
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def execute_migration():
    """执行删除 album_name 字段的迁移"""

    db = Database(settings.DATABASE_URL)
    session = db.SessionLocal()

    try:
        # === 步骤1: 安全检查 ===
        logger.info("=== 步骤1: 数据安全检查 ===")

        # 检查是否有 field 为空但 album_name 不为空的记录
        result = session.execute(text("""
            SELECT COUNT(*) as count
            FROM journals
            WHERE field IS NULL AND album_name IS NOT NULL
        """)).fetchone()

        if result.count > 0:
            logger.error(f"❌ 发现 {result.count} 条记录的 field 为空但 album_name 不为空！")
            logger.error("请先运行以下脚本同步数据：")
            logger.error("  python scripts/fix_journal_field_mapping.py")
            return False
        else:
            logger.info("✓ 数据完整性检查通过")

        # 显示统计
        stats = session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(field) as has_field,
                COUNT(album_name) as has_album
            FROM journals
        """)).fetchone()

        logger.info(f"总期刊数: {stats.total}")
        logger.info(f"有 field (一级学科): {stats.has_field}")
        logger.info(f"有 album_name (将删除): {stats.has_album}")

        # 确认
        logger.info("\n即将删除 album_name 字段...")
        choice = input("确认继续? (yes/no): ").strip().lower()
        if choice not in ['yes', 'y']:
            logger.info("已取消迁移")
            return False

        # === 步骤2: 执行迁移 ===
        logger.info("\n=== 步骤2: 删除 album_name 字段 ===")

        session.execute(text("ALTER TABLE journals DROP COLUMN IF EXISTS album_name"))
        session.commit()

        logger.info("✓ album_name 字段已成功删除")

        # === 步骤3: 验证结果 ===
        logger.info("\n=== 步骤3: 验证结果 ===")

        # 尝试查询 album_name（应该失败）
        try:
            result = session.execute(text("""
                SELECT COUNT(*) as count
                FROM journals
                WHERE album_name IS NOT NULL
            """)).fetchone()
            logger.error(f"❌ 字段仍然存在！count={result.count}")
            return False
        except Exception as e:
            if 'column' in str(e).lower() or 'does not exist' in str(e).lower():
                logger.info("✓ 确认字段已删除（查询验证失败）")
            else:
                raise

        # 最终统计
        final_stats = session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(field) as has_field,
                COUNT(subfield) as has_subfield
            FROM journals
        """)).fetchone()

        logger.info(f"\n最终统计:")
        logger.info(f"  总期刊数: {final_stats.total}")
        logger.info(f"  有 field (一级学科): {final_stats.has_field}")
        logger.info(f"  有 subfield (二级学科): {final_stats.has_subfield}")

        logger.info("\n✓✓✓ 迁移完成！album_name 字段已安全删除 ✓✓✓")
        return True

    except Exception as e:
        session.rollback()
        logger.error(f"❌ 迁移失败: {e}")
        return False
    finally:
        session.close()


if __name__ == "__main__":
    success = execute_migration()
    sys.exit(0 if success else 1)
