"""
修复期刊表中学科字段的映射关系

- 将 album_name（专辑名称）同步到 field（一级学科）
- 清理不一致的数据
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


def fix_field_mapping():
    """修复学科字段映射"""

    db = Database(settings.DATABASE_URL)
    session = db.SessionLocal()

    try:
        # 统计当前状态
        logger.info("=== 数据修复前统计 ===")

        stats = session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(field) as has_field,
                COUNT(album_name) as has_album,
                COUNT(subfield) as has_subfield
            FROM journals
        """)).fetchone()

        logger.info(f"总期刊数: {stats.total}")
        logger.info(f"有field (一级学科): {stats.has_field}")
        logger.info(f"有album_name (专辑名称): {stats.has_album}")
        logger.info(f"有subfield (二级学科): {stats.has_subfield}")

        # 1. 将 album_name 同步到 field（当 field 为空时）
        logger.info("\n=== 步骤1: 同步专辑名称到一级学科 ===")
        result = session.execute(text("""
            UPDATE journals
            SET field = album_name
            WHERE field IS NULL AND album_name IS NOT NULL
        """))
        session.commit()
        logger.info(f"已更新 {result.rowcount} 条记录")

        # 2. 显示更新后的统计
        logger.info("\n=== 数据修复后统计 ===")
        stats_after = session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(field) as has_field,
                COUNT(album_name) as has_album,
                COUNT(subfield) as has_subfield
            FROM journals
        """)).fetchone()

        logger.info(f"总期刊数: {stats_after.total}")
        logger.info(f"有field (一级学科): {stats_after.has_field}")
        logger.info(f"有album_name (专辑名称): {stats_after.has_album}")
        logger.info(f"有subfield (二级学科): {stats_after.has_subfield}")

        # 3. 检查不一致的记录（field != album_name 的情况）
        logger.info("\n=== 检查不一致记录 ===")
        inconsistent = session.execute(text("""
            SELECT id, name, field, album_name
            FROM journals
            WHERE field IS NOT NULL AND album_name IS NOT NULL
              AND field != album_name
            LIMIT 10
        """)).fetchall()

        if inconsistent:
            logger.warning(f"发现 {len(inconsistent)} 条不一致记录（仅显示前10条）:")
            for row in inconsistent:
                logger.warning(f"  ID={row.id}, {row.name}: field='{row.field}', album_name='{row.album_name}'")

            # 询问是否统一为 album_name
            logger.info("\n是否将所有 field 统一为 album_name？")
            logger.info("(这会覆盖现有的 field 值，如果想保留 field 值，请选择否)")

            choice = input("统一为 album_name? (y/n): ").strip().lower()
            if choice == 'y':
                result = session.execute(text("""
                    UPDATE journals
                    SET field = album_name
                    WHERE album_name IS NOT NULL
                """))
                session.commit()
                logger.info(f"已统一 {result.rowcount} 条记录")
        else:
            logger.info("✓ 没有发现不一致的记录")

        # 4. 显示学科分布
        logger.info("\n=== 一级学科分布 ===")
        field_dist = session.execute(text("""
            SELECT field, COUNT(*) as count
            FROM journals
            WHERE field IS NOT NULL
            GROUP BY field
            ORDER BY count DESC
            LIMIT 20
        """)).fetchall()

        for row in field_dist:
            logger.info(f"  {row.field}: {row.count}")

        # 5. 显示专辑名称分布
        logger.info("\n=== 专辑名称分布 ===")
        album_dist = session.execute(text("""
            SELECT album_name, COUNT(*) as count
            FROM journals
            WHERE album_name IS NOT NULL
            GROUP BY album_name
            ORDER BY count DESC
            LIMIT 20
        """)).fetchall()

        for row in album_dist:
            logger.info(f"  {row.album_name}: {row.count}")

        logger.info("\n=== 修复完成 ===")

    except Exception as e:
        session.rollback()
        logger.error(f"修复失败: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    fix_field_mapping()
