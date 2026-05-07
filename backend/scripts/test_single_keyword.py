"""
测试单个关键词的检索结果
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.cnki_literature_validator import CNKILiteratureValidator


async def test_single_keyword():
    """测试单个关键词"""
    print("=" * 70)
    print("测试单个关键词: '零基预算'")
    print("=" * 70)

    validator = CNKILiteratureValidator()
    result = await validator.validate_keywords(['零基预算'])

    print(f"\n[验证结果]")
    print(f"检索式: {result.search_query}")
    print(f"文献总数: {result.total_papers} 篇")
    print(f"是否合格: {'[合格]' if result.is_valid else '[不合格]'}")

    if result.top_journals:
        print(f"\n[前5期刊分布]")
        for i, journal in enumerate(result.top_journals, 1):
            core_types = ', '.join(journal.get('core_types', []))
            if not core_types:
                core_types = '普通期刊'
            print(f"  {i}. {journal['name']} ({journal['count']}篇) - {core_types}")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    asyncio.run(test_single_keyword())
