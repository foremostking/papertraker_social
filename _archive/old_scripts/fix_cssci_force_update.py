"""
强制重新解析CSSCI期刊

针对所有含CSSCI标签的期刊，重新应用修复后的解析逻辑
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from app.core.database import Database
from app.models.journal import Journal
from app.services.journal_core_parser import JournalCoreParser
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 初始化数据库
db_instance = Database(settings.DATABASE_URL)
SessionLocal = db_instance.SessionLocal


def fix_cssci_journals(batch_size: int = 500):
    """
    强制更新所有含CSSCI标签的期刊
    """
    logger.info("=" * 60)
    logger.info("CSSCI期刊强制重新解析")
    logger.info("=" * 60)

    db = SessionLocal()

    try:
        # 查询所有含CSSCI标签的期刊
        all_journals = db.query(Journal).filter(
            Journal.journal_tags.isnot(None)
        ).all()

        # 筛选含CSSCI的期刊
        cssci_journals = []
        for j in all_journals:
            if j.journal_tags and any("cssci" in str(tag).lower() for tag in j.journal_tags):
                cssci_journals.append(j)

        logger.info(f"找到含CSSCI标签的期刊: {len(cssci_journals)} 本")

        # 修复前统计
        before_cssci = sum(1 for j in cssci_journals if j.is_cssci)
        before_cssci_exp = sum(1 for j in cssci_journals if j.is_cssci_expansion)
        before_none = sum(1 for j in cssci_journals if not j.is_cssci and not j.is_cssci_expansion)

        logger.info(f"\n修复前统计:")
        logger.info(f"  is_cssci=True: {before_cssci}")
        logger.info(f"  is_cssci_expansion=True: {before_cssci_exp}")
        logger.info(f"  未标记: {before_none}")

        # 分批处理
        updated_count = 0
        batches = (len(cssci_journals) + batch_size - 1) // batch_size

        for batch_num in range(batches):
            batch = cssci_journals[batch_num * batch_size:(batch_num + 1) * batch_size]

            for journal in batch:
                # 记录旧值
                old_cssci = journal.is_cssci
                old_cssci_exp = journal.is_cssci_expansion

                # 重新解析所有核心字段
                core_flags = JournalCoreParser.parse_tags(journal.journal_tags)

                # 更新CSSCI相关字段
                journal.is_cssci = core_flags.get('is_cssci', False)
                journal.is_cssci_expansion = core_flags.get('is_cssci_expansion', False)

                # 记录是否有变化
                if (old_cssci != journal.is_cssci or
                    old_cssci_exp != journal.is_cssci_expansion):
                    updated_count += 1
                    if updated_count <= 5:  # 显示前5个变化
                        logger.info(f"  [{journal.name}] is_cssci: {old_cssci}→{journal.is_cssci}, is_cssci_expansion: {old_cssci_exp}→{journal.is_cssci_expansion}")

            # 提交这一批
            try:
                db.commit()
            except Exception as e:
                logger.error(f"批次提交失败: {e}")
                db.rollback()

            logger.info(f"批次 {batch_num + 1}/{batches} 完成")

        # 重新查询统计（从数据库获取最新值）
        final_cssci = db.query(Journal).filter(Journal.is_cssci == True).count()
        final_cssci_exp = db.query(Journal).filter(Journal.is_cssci_expansion == True).count()

        logger.info("\n" + "=" * 60)
        logger.info("修复完成！")
        logger.info("=" * 60)
        logger.info(f"更新记录数: {updated_count}")
        logger.info(f"\n最终统计:")
        logger.info(f"  is_cssci=True: {final_cssci} 本")
        logger.info(f"  is_cssci_expansion=True: {final_cssci_exp} 本")
        logger.info(f"  总计: {final_cssci + final_cssci_exp} 本")

        # 列出样例
        logger.info(f"\nCSSCI扩展版样例 (前3本):")
        exp_journals = db.query(Journal).filter(
            Journal.is_cssci_expansion == True
        ).limit(3).all()
        for j in exp_journals:
            logger.info(f"  - {j.name}: {j.journal_tags}")

    except Exception as e:
        logger.error(f"修复失败: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()

    finally:
        db.close()


if __name__ == '__main__':
    fix_cssci_journals()
