"""
CNKI文献验证完整测试 - 包含来源类别统计
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.cnki_literature_validator import validate_keywords_async
from app.core.database import get_db, init_db
import os


async def test_full_validation():
    """完整测试：包含文献总数、来源类别、期刊分布"""
    print("=" * 70)
    print("CNKI Literature Validation Full Test")
    print("=" * 70)

    # 初始化数据库
    print("\n[Init] Initializing database...")
    database_url = os.getenv('DATABASE_URL', 'sqlite:///./data/papertracker.db')
    init_db(database_url)

    # 测试单个关键词（获得更多结果）
    keywords = ['零基预算']

    print(f"\n[Test] Keywords: {keywords}")
    print("-" * 70)

    # 获取数据库连接
    db_generator = get_db()
    db = next(db_generator)

    try:
        result = await validate_keywords_async(keywords, db=db)

        print(f"\n[Search Query]")
        print(f"  {result.search_query}")

        print(f"\n[Paper Statistics]")
        print(f"  Total Papers: {result.total_papers}")
        print(f"  Core Journal Papers: {result.core_papers}")
        print(f"  Core Ratio: {result.core_ratio:.2%}")

        print(f"\n[Source Distribution - Core Journals]")
        if result.source_distribution:
            # 按数量排序显示
            sorted_sources = sorted(
                result.source_distribution.items(),
                key=lambda x: x[1],
                reverse=True
            )
            for source, count in sorted_sources[:10]:
                if count > 0:
                    is_core = source in ['CSSCI', '北大核心', 'CSCD', 'AMI', 'SCI来源期刊', 'EI来源期刊', 'WJCI']
                    core_mark = "[CORE]" if is_core else ""
                    print(f"  {source:20s}: {count:4d} papers {core_mark}")
        else:
            print("  No source distribution data available")

        print(f"\n[Top 10 Journals]")
        if result.top_journals:
            for i, journal in enumerate(result.top_journals[:10], 1):
                core_types = ', '.join(journal.get('core_types', []))
                if not core_types:
                    core_types = 'Ordinary'
                print(f"  {i:2d}. {journal['name']:30s} ({journal['count']:3d} papers) - {core_types}")
        else:
            print("  No journal data available")

        print(f"\n[Validation Result]")
        print(f"  Is Valid: {result.is_valid}")
        print(f"  Reason: ", end="")

        if result.is_valid:
            print("Keywords have good academic potential.")
        else:
            if result.total_papers < 50:
                print(f"Insufficient papers (only {result.total_papers})")
                print(f"  Suggestion: Try more common keywords")
            elif result.core_ratio < 0.3:
                print(f"Low core journal ratio ({result.core_ratio:.1%})")
                print(f"  Suggestion: Try more academic keywords")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

    print("\n" + "=" * 70)
    print("Test completed successfully!")
    print("=" * 70)


if __name__ == '__main__':
    asyncio.run(test_full_validation())
