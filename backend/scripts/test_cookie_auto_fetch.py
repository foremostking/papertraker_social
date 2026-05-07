"""
测试CNKI Cookie自动获取功能
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.cnki_cookie_manager import CNKICookieManager
from app.services.cnki_literature_validator import CNKILiteratureValidator, validate_keywords


async def test_cookie_auto_fetch():
    """测试Cookie自动获取和验证"""
    print("=" * 70)
    print("CNKI Cookie Auto-Fetch & Validation Test")
    print("=" * 70)

    # 测试1: Cookie自动获取
    print("\n[Test 1] Auto-fetch Cookie")
    print("-" * 70)

    manager = CNKICookieManager()

    # 先尝试使用缓存
    cached = manager.get_cookie(force_refresh=False)
    if cached:
        print(f"[CACHED] Using cached cookie")
        print(f"Length: {len(cached)} characters")

        # 显示关键Cookie
        for key in ['Ecp_ClientId', 'SID_kns_new']:
            if key in cached:
                start = cached.find(key + '=')
                if start != -1:
                    end = cached.find(';', start)
                    if end == -1:
                        end = start + 50
                    value = cached[start:end]
                    print(f"  {key}: ...{value[-30:]}")
    else:
        print("[FETCH] No cached cookie, fetching new one...")
        cookie = await manager.fetch_cookie_async(
            headless=False,
            wait_for_verification=60
        )

        if cookie:
            print(f"[SUCCESS] Cookie fetched:")
            print(f"Length: {len(cookie)} characters")
        else:
            print("[FAILED] Could not fetch cookie")
            return

    # 测试2: 使用Cookie进行验证
    print("\n[Test 2] Validate Keywords with Auto-Fetched Cookie")
    print("-" * 70)

    # 创建验证器（启用自动获取Cookie）
    validator = CNKILiteratureValidator(auto_fetch=True)

    # 测试单个关键词
    keywords = ['零基预算']
    result = await validator.validate_keywords(keywords)

    print(f"\n[RESULT]")
    print(f"Keywords: {result.keywords}")
    print(f"Search Query: {result.search_query}")
    print(f"Total Papers: {result.total_papers}")
    print(f"Is Valid: {result.is_valid}")

    if result.top_journals:
        print(f"\n[Top Journals]")
        for i, journal in enumerate(result.top_journals[:5], 1):
            core_types = ', '.join(journal.get('core_types', []))
            if not core_types:
                core_types = 'Ordinary'
            print(f"  {i}. {journal['name']} ({journal['count']} papers) - {core_types}")

    # 测试3: 多关键词验证
    print("\n[Test 3] Multiple Keywords Validation")
    print("-" * 70)

    keywords2 = ['零基预算', '改革']
    result2 = await validator.validate_keywords(keywords2)

    print(f"[RESULT]")
    print(f"Keywords: {result2.keywords}")
    print(f"Total Papers: {result2.total_papers}")

    print("\n" + "=" * 70)
    print("All tests completed")
    print("=" * 70)


if __name__ == '__main__':
    asyncio.run(test_cookie_auto_fetch())
