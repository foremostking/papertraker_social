"""
CNKI文献验证服务测试脚本 - 使用有效Cookie
"""

import asyncio
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.cnki_literature_validator import CNKILiteratureValidator, validate_keywords


async def test_validator():
    """测试CNKI文献验证器"""

    print("=" * 70)
    print("CNKI文献验证服务测试 V4 (使用有效Cookie)")
    print("=" * 70)

    # 测试关键词
    keywords = ['零基预算', '甘肃省']

    print(f"\n测试关键词: {keywords}")
    print("-" * 70)

    try:
        # 使用默认Cookie（用户提供的有效Cookie）
        validator = CNKILiteratureValidator()

        # 执行验证
        result = await validator.validate_keywords(keywords)

        # 打印调试信息
        if result.validation_details.get('error'):
            print(f"\n[错误信息] {result.validation_details['error']}")

        # 打印结果
        print(f"\n[验证结果]")
        print(f"检索式: {result.search_query}")
        print(f"文献总数: {result.total_papers} 篇")
        print(f"核心期刊文献: {result.core_papers} 篇")
        print(f"核心期刊占比: {result.core_ratio:.2%}")
        print(f"是否合格: {'[合格]' if result.is_valid else '[不合格]'}")

        if result.top_journals:
            print(f"\n[前5期刊分布]")
            for i, journal in enumerate(result.top_journals, 1):
                core_types = ', '.join(journal.get('core_types', []))
                if not core_types:
                    core_types = '普通期刊'
                print(f"  {i}. {journal['name']} ({journal['count']}篇) - {core_types}")

        # 打印建议
        print(f"\n[验证建议]")
        recommendation = validator.get_validation_recommendation(result)
        print(recommendation)

    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)


if __name__ == '__main__':
    asyncio.run(test_validator())
