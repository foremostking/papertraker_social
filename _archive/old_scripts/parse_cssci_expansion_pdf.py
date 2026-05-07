"""
解析CSSCI扩展版PDF并匹配数据库
"""

import sys
import re
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pdfplumber
from app.core.config import settings
from app.core.database import Database
from app.models.journal import Journal
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def extract_journal_names_from_pdf(pdf_path: str) -> list:
    """
    从PDF中提取期刊名称
    """
    logger.info(f"解析PDF: {pdf_path}")

    journal_names = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            lines = text.split('\n')

            for line in lines:
                line = line.strip()
                # 跳过标题行和空行
                if not line or '中文社会科学' in line or 'CSSCI' in line or '共' in line:
                    continue

                # 匹配期刊名称
                # 格式: 序号 学校 期刊名称 刊号
                # 期刊名称通常是中文，4-20字
                # 尝试提取模式

                # 方法1: 查找以序号开头的行
                match = re.match(r'^\d+\s+.*?\s+([^\d]+?)(?:\s+\d+-\d+/\w)?$', line)
                if match:
                    name = match.group(1).strip()
                    # 清理可能的学校名称前缀
                    # 期刊名称通常不包含"大学"、"学院"等学校名称
                    if name and len(name) >= 3 and len(name) <= 20:
                        # 进一步过滤
                        if not re.search(r'^[^\w]*大学|^[^\w]*学院', name):
                            journal_names.append(name)
                            continue

                # 方法2: 直接提取中文名称
                chinese_match = re.findall(r'[\u4e00-\u9fa5]{3,20}', line)
                for name in chinese_match:
                    # 排除明显不是期刊名称的词
                    if name in ['大学', '学院', '学报', '研究', '出版社', '编辑部']:
                        continue
                    if name not in journal_names:
                        journal_names.append(name)

    # 去重并过滤
    unique_names = []
    seen = set()
    for name in journal_names:
        name = name.strip()
        if name and name not in seen and len(name) >= 3:
            # 排除常见的非期刊名称
            if name not in ['大学', '学院', '学报', '研究', '出版社', '编辑部',
                           '中国', '科学', '社会', '期刊', '来源', '扩展', '目录']:
                seen.add(name)
                unique_names.append(name)

    logger.info(f"提取到 {len(unique_names)} 个可能的期刊名称")
    return unique_names


def match_and_update_database(journal_names: list):
    """
    与数据库匹配并更新
    """
    logger.info("\n" + "=" * 60)
    logger.info("数据库匹配")
    logger.info("=" * 60)

    db_instance = Database(settings.DATABASE_URL)
    db = db_instance.SessionLocal()

    try:
        # 获取所有期刊
        all_journals = db.query(Journal).all()
        logger.info(f"数据库中共有 {len(all_journals)} 本期刊")

        exact_matched = []
        fuzzy_matched = []
        unmatched = []

        for target_name in journal_names:
            # 精确匹配
            exact = db.query(Journal).filter(Journal.name == target_name).first()
            if exact:
                exact_matched.append(exact)
                continue

            # 包含匹配（目标名称包含数据库名称，或反之）
            fuzzy1 = db.query(Journal).filter(Journal.name.contains(target_name)).first()
            if fuzzy1:
                fuzzy_matched.append((target_name, fuzzy1, 'db_contains'))
                continue

            # 反向包含匹配
            fuzzy2 = db.query(Journal).filter(
                Journal.name.op('~')(f'.*{target_name}.*')
            ).first()
            if fuzzy2:
                fuzzy_matched.append((target_name, fuzzy2, 'regex'))
                continue

            unmatched.append(target_name)

        logger.info(f"\n匹配结果:")
        logger.info(f"  精确匹配: {len(exact_matched)} 本")
        logger.info(f"  模糊匹配: {len(fuzzy_matched)} 本")
        logger.info(f"  未匹配: {len(unmatched)} 本")
        logger.info(f"  总计: {len(exact_matched) + len(fuzzy_matched)} / {len(journal_names)}")

        # 显示部分匹配结果
        if exact_matched:
            logger.info(f"\n精确匹配样例 (前10本):")
            for j in exact_matched[:10]:
                logger.info(f"  - {j.name}")

        if fuzzy_matched:
            logger.info(f"\n模糊匹配样例 (前10本):")
            for target, journal, method in fuzzy_matched[:10]:
                logger.info(f"  - {target} → {journal.name} ({method})")

        if unmatched:
            logger.info(f"\n未匹配样例 (前20个):")
            for name in unmatched[:20]:
                logger.info(f"  - {name}")

        # 更新数据库
        logger.info(f"\n开始更新数据库...")

        updated_count = 0

        # 更新精确匹配的期刊
        for journal in exact_matched:
            if not journal.is_cssci_expansion:
                journal.is_cssci_expansion = True
                # 如果之前标记为CSSCI来源版，需要调整
                if journal.is_cssci:
                    logger.info(f"  [{journal.name}] 从来源版改为扩展版")
                    journal.is_cssci = False
                updated_count += 1

        # 更新模糊匹配的期刊
        for target, journal, method in fuzzy_matched:
            if not journal.is_cssci_expansion:
                logger.info(f"  [{journal.name}] 模糊匹配自 '{target}'，标记为扩展版")
                journal.is_cssci_expansion = True
                if journal.is_cssci:
                    journal.is_cssci = False
                updated_count += 1

        db.commit()

        logger.info(f"\n更新完成: {updated_count} 本期刊")

        # 统计最终结果
        final_cssci = db.query(Journal).filter(Journal.is_cssci == True).count()
        final_cssci_exp = db.query(Journal).filter(Journal.is_cssci_expansion == True).count()

        logger.info(f"\n最终统计:")
        logger.info(f"  CSSCI来源版: {final_cssci} 本")
        logger.info(f"  CSSCI扩展版: {final_cssci_exp} 本")
        logger.info(f"  总计: {final_cssci + final_cssci_exp} 本")

        # 列出扩展版期刊
        if final_cssci_exp > 0:
            logger.info(f"\nCSSCI扩展版期刊列表:")
            exp_journals = db.query(Journal).filter(
                Journal.is_cssci_expansion == True
            ).all()
            for j in exp_journals:
                logger.info(f"  - {j.name}")

        # 保存未匹配列表
        if unmatched:
            unmatched_file = project_root / 'scripts' / 'cssci_expansion_unmatched.txt'
            with open(unmatched_file, 'w', encoding='utf-8') as f:
                for name in unmatched:
                    f.write(f"{name}\n")
            logger.info(f"\n未匹配期刊列表已保存到: {unmatched_file}")

    except Exception as e:
        logger.error(f"数据库操作失败: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()

    finally:
        db.close()


if __name__ == '__main__':
    pdf_path = project_root / 'scripts' / 'cssci_expansion_2021-2022.pdf'

    # 提取期刊名称
    journal_names = extract_journal_names_from_pdf(str(pdf_path))

    # 保存提取的名称
    names_file = project_root / 'scripts' / 'cssci_expansion_extracted_names.txt'
    with open(names_file, 'w', encoding='utf-8') as f:
        for name in journal_names:
            f.write(f"{name}\n")
    logger.info(f"\n提取的期刊名称已保存到: {names_file}")

    # 与数据库匹配并更新
    if journal_names:
        match_and_update_database(journal_names)
