"""
核心期刊标识解析服务

从期刊的 journal_tags 字段中解析各类核心期刊标识
"""

import logging
from typing import Dict, List, Optional, Set
from sqlalchemy.orm import Session
from app.models.journal import Journal

logger = logging.getLogger(__name__)


class JournalCoreParser:
    """核心期刊标识解析器"""

    # 核心期刊标签映射规则
    # 格式: (数据库字段名, [标签匹配模式列表])
    CORE_MAPPING = {
        # 中文核心
        'is_cssci': ['CSSCI', 'CSSCI来源', 'CSSCI 来源', '南大核心', '南大核心期刊'],
        'is_cssci_expansion': ['CSSCI扩展', 'CSSCI 扩展', 'CSSCI扩展版'],
        'is_beida_core': ['北大核心', '中文核心', '全国中文核心'],
        'is_ami': ['AMI', 'AMI核心', 'AMI 核心', 'AMI评价'],
        'is_cscd': ['CSCD', 'CSCD核心', 'CSCD 核心', '中国科学引文数据库', '中国科学引文'],

        # 国际核心
        'is_sci': ['SCI', 'SCI核心', 'SCI 核心', 'Science Citation Index'],
        'is_ei': ['EI', 'EI核心', 'EI 核心', 'Engineering Index'],
        'is_cas': ['CAS', 'Chemical Abstracts', '化学文摘'],
        'is_inspec': ['INSPEC', 'Inspec', '科学文摘'],
        'is_jst': ['JST', '日本科学技术振兴'],
        'is_paj': ['Pж', 'AJ', '文摘杂志', '俄罗斯文摘'],
        'is_wjci': ['WJCI', '科技期刊世界影响力', '世界期刊影响力指数'],
    }

    # 扩展版精确匹配模式（必须包含"CSSCI"才能判定为CSSCI扩展版）
    CSSCI_EXPANSION_PATTERNS = ['CSSCI扩展', 'CSSCI 扩展', 'CSSCI扩展版', 'CSSCI 扩展版']

    @classmethod
    def parse_tags(cls, tags: List[str]) -> Dict[str, bool]:
        """
        从期刊标签列表解析核心期刊标识

        Args:
            tags: 期刊标签列表，如 ['北大核心', 'CSSCI', 'CSCD']

        Returns:
            包含所有核心期刊标识的字典
        """
        if not tags:
            return {field: False for field in cls.CORE_MAPPING.keys()}

        # 将标签列表转换为字符串列表并去除空格
        tag_list = [str(tag).strip() for tag in tags if tag]

        # 初始化结果
        result = {field: False for field in cls.CORE_MAPPING.keys()}

        # 按优先级排序：先匹配更精确的模式
        # 将所有模式扁平化并带上字段信息，然后按长度降序排序
        all_patterns = []
        for field, patterns in cls.CORE_MAPPING.items():
            for pattern in patterns:
                all_patterns.append((field, pattern, len(pattern)))

        # 按模式长度降序排序，更长的模式优先匹配
        all_patterns.sort(key=lambda x: x[2], reverse=True)

        # 预先检查是否有CSSCI扩展版标签
        has_cssci_expansion = False
        for tag in tag_list:
            tag_upper = tag.upper()
            if any(pattern.upper() in tag_upper for pattern in cls.CSSCI_EXPANSION_PATTERNS):
                has_cssci_expansion = True
                result['is_cssci_expansion'] = True
                break

        # 对每个标签进行匹配
        for tag in tag_list:
            tag_upper = tag.upper()
            tag_matched = False

            for field, pattern, _ in all_patterns:
                pattern_upper = pattern.upper()

                # CSSCI扩展版特殊处理
                if field == 'is_cssci_expansion':
                    # 已在前面统一处理，跳过
                    continue
                elif field == 'is_cssci':
                    # 如果已标记为CSSCI扩展版，则不标记为来源版
                    if has_cssci_expansion:
                        continue

                # 精确匹配或标签包含模式
                if pattern_upper in tag_upper:
                    result[field] = True
                    tag_matched = True
                    break  # 该标签已匹配，跳过其他模式

        return result

    @classmethod
    def update_journal_from_tags(cls, journal: Journal) -> int:
        """
        根据期刊的 journal_tags 更新核心期刊标识字段

        Args:
            journal: Journal 模型实例

        Returns:
            更新的字段数量
        """
        if not journal.journal_tags:
            return 0

        core_flags = cls.parse_tags(journal.journal_tags)
        updated_count = 0

        for field, value in core_flags.items():
            if hasattr(journal, field):
                current_value = getattr(journal, field)
                if current_value != value:
                    setattr(journal, field, value)
                    updated_count += 1

        return updated_count

    @classmethod
    def batch_update_journals(
        cls,
        db: Session,
        limit: Optional[int] = None,
        force: bool = False
    ) -> Dict[str, int]:
        """
        批量更新期刊的核心期刊标识

        Args:
            db: 数据库会话
            limit: 限制更新数量（测试用）
            force: 是否强制更新（包括已有标识的期刊）

        Returns:
            统计信息字典
        """
        stats = {
            'total': 0,
            'updated': 0,
            'skipped': 0,
            'no_tags': 0,
            'errors': 0
        }

        # 构建查询：只处理有 journal_tags 的期刊
        query = db.query(Journal).filter(Journal.journal_tags.isnot(None))

        # 非强制模式下，跳过已有完整标识的期刊
        if not force:
            # 查找所有核心标识都为 False 的期刊
            condition = None
            for field in cls.CORE_MAPPING.keys():
                field_condition = getattr(Journal, field) == False
                if condition is None:
                    condition = field_condition
                else:
                    condition = condition & field_condition
            query = query.filter(condition)

        if limit:
            query = query.limit(limit)

        journals = query.all()
        stats['total'] = len(journals)

        logger.info(f"开始批量更新核心期刊标识，共 {len(journals)} 本期刊")

        for journal in journals:
            try:
                updated_count = cls.update_journal_from_tags(journal)

                if updated_count > 0:
                    stats['updated'] += 1
                    logger.debug(f"更新期刊 {journal.name}: {updated_count} 个字段")
                else:
                    stats['skipped'] += 1

            except Exception as e:
                logger.error(f"更新期刊 {journal.name} 失败: {e}")
                stats['errors'] += 1

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"批量提交失败: {e}")
            stats['errors'] += 1

        return stats

    @classmethod
    def get_journal_core_summary(cls, journal: Journal) -> Dict[str, List[str]]:
        """
        获取期刊的核心期刊标识摘要

        Args:
            journal: Journal 模型实例

        Returns:
            包含中文核心、国际核心分类的字典
        """
        chinese_cores = []
        international_cores = []

        # 中文核心
        if journal.is_cssci:
            chinese_cores.append('CSSCI')
        if journal.is_cssci_expansion:
            chinese_cores.append('CSSCI扩展版')
        if journal.is_beida_core:
            chinese_cores.append('北大核心')
        if journal.is_ami:
            chinese_cores.append('AMI')
        if journal.is_cscd:
            chinese_cores.append('CSCD')

        # 国际核心
        if journal.is_sci:
            international_cores.append('SCI')
        if journal.is_ei:
            international_cores.append('EI')
        if journal.is_cas:
            international_cores.append('CAS')
        if journal.is_inspec:
            international_cores.append('INSPEC')
        if journal.is_jst:
            international_cores.append('JST')
        if journal.is_paj:
            international_cores.append('Pж(AJ)')
        if journal.is_wjci:
            international_cores.append('WJCI')

        return {
            'chinese_cores': chinese_cores,
            'international_cores': international_cores,
            'is_core': len(chinese_cores) > 0 or len(international_cores) > 0
        }


def parse_journal_tags(tags: List[str]) -> Dict[str, bool]:
    """便捷函数：解析期刊标签"""
    return JournalCoreParser.parse_tags(tags)


def update_journal_from_tags(journal: Journal) -> int:
    """便捷函数：更新单个期刊"""
    return JournalCoreParser.update_journal_from_tags(journal)


def batch_update_journals(db: Session, limit: Optional[int] = None, force: bool = False) -> Dict[str, int]:
    """便捷函数：批量更新"""
    return JournalCoreParser.batch_update_journals(db, limit, force)


def get_journal_core_summary(journal: Journal) -> Dict[str, any]:
    """便捷函数：获取期刊核心标识摘要"""
    return JournalCoreParser.get_journal_core_summary(journal)
