"""
清理错误的 field 数据

修复之前同步时产生的错误数据，如：
- "信息科技专辑名称："
- "一级学科：社会科学Ⅰ辑；专题名称：中国政治"
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import Database
from app.core.config import settings
from sqlalchemy import text
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def clean_field_data():
    """清理错误的 field 数据"""

    db = Database(settings.DATABASE_URL)
    session = db.SessionLocal()

    try:
        # 1. 统计需要清理的记录
        logger.info("=== 统计需要清理的记录 ===")

        result = session.execute(text("""
            SELECT COUNT(*) as count
            FROM journals
            WHERE field IS NOT NULL
              AND (field LIKE '%专辑名称%' OR field LIKE '%专题名称%' OR field LIKE '%一级学科%')
        """)).fetchone()

        logger.info(f"发现 {result.count} 条错误记录需要清理")

        if result.count == 0:
            logger.info("没有发现需要清理的数据")
            return

        # 2. 显示一些示例
        logger.info("\n=== 错误数据示例 ===")
        samples = session.execute(text("""
            SELECT id, name, field
            FROM journals
            WHERE field IS NOT NULL
              AND (field LIKE '%专辑名称%' OR field LIKE '%专题名称%' OR field LIKE '%一级学科%')
            LIMIT 5
        """)).fetchall()

        for row in samples:
            logger.info(f"  ID={row.id}: {row.name[:30]} | {row.field[:60]}")

        # 3. 清理数据
        logger.info("\n=== 开始清理 ===")

        # 获取所有需要清理的记录
        records = session.execute(text("""
            SELECT id, field
            FROM journals
            WHERE field IS NOT NULL
              AND (field LIKE '%专辑名称%' OR field LIKE '%专题名称%' OR field LIKE '%一级学科%')
        """)).fetchall()

        fixed_count = 0
        for record in records:
            original_field = record.field
            new_field = None

            # 尝试提取正确的值
            # 格式1: "一级学科：社会科学Ⅰ辑；专题名称：中国政治"
            if '一级学科：' in original_field and '专题名称：' in original_field:
                match = re.search(r'一级学科[::：]\s*([^；;]+?)(?:[；;]|专题名称)', original_field)
                if match:
                    new_field = match.group(1).strip()

            # 格式2: "信息科技专辑名称：" (取专辑名称前面的部分)
            elif '专辑名称：' in original_field:
                match = re.search(r'(.+?)专辑名称[::：]', original_field)
                if match:
                    new_field = match.group(1).strip()
                else:
                    # 如果无法提取，设为 NULL 等待重新获取
                    new_field = None

            # 格式3: "社会科学Ⅰ辑；专题名称：中国政治"
            elif '；专题名称：' in original_field or ';专题名称:' in original_field:
                match = re.search(r'^([^；;]+)', original_field)
                if match:
                    new_field = match.group(1).strip()

            # 应用修正
            if new_field and new_field != original_field:
                session.execute(text("""
                    UPDATE journals
                    SET field = :new_field
                    WHERE id = :id
                """), {'new_field': new_field, 'id': record.id})
                fixed_count += 1
            elif not new_field:
                # 无法修复，设为 NULL
                session.execute(text("""
                    UPDATE journals
                    SET field = NULL
                    WHERE id = :id
                """), {'id': record.id})
                fixed_count += 1

        logger.info(f"已修正 {fixed_count} 条记录")
        session.commit()

        # 4. 最终统计
        logger.info("\n=== 清理后统计 ===")
        stats = session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(field) as has_field,
                COUNT(subfield) as has_subfield
            FROM journals
        """)).fetchone()

        logger.info(f"总期刊数: {stats.total}")
        logger.info(f"有 field (一级学科): {stats.has_field}")
        logger.info(f"有 subfield (二级学科): {stats.has_subfield}")

        logger.info("\n=== 需要重新获取期刊详情 ===")
        logger.info("请运行批量更新任务重新获取期刊详情:")
        logger.info("  python scripts/batch_update_concurrent.py")

    except Exception as e:
        session.rollback()
        logger.error(f"清理失败: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    clean_field_data()
