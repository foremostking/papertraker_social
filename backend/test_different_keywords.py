"""
测试不同关键词的CNKI验证结果
"""

import asyncio
import requests
import json


def test_keywords(keywords_list):
    """测试多个关键词组合"""
    print("=" * 70)
    print("CNKI Validation - Different Keywords Test")
    print("=" * 70)

    url = "http://localhost:8000/api/v1/topic-selection/validate-cnki"

    for keywords in keywords_list:
        print(f"\n{'=' * 70}")
        print(f"Testing: {keywords}")
        print("-" * 70)

        request_data = {"keywords": keywords}

        try:
            response = requests.post(url, json=request_data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                print(f"Total Papers: {result['total_papers']}")
                print(f"Core Papers: {result['core_papers']}")
                print(f"Core Ratio: {result['core_ratio']:.2%}")
                print(f"Is Valid: {result['is_valid']}")
                
                print(f"\nSource Distribution:")
                if result['source_distribution']:
                    # 只显示非零的类别
                    non_zero = {k: v for k, v in result['source_distribution'].items() if v > 0}
                    # 按数量排序
                    sorted_items = sorted(non_zero.items(), key=lambda x: x[1], reverse=True)
                    for source, count in sorted_items:
                        print(f"  - {source:15s}: {count:4d} papers")
                
                # 检查是否有重复计数
                total_dist = sum(result['source_distribution'].values())
                print(f"\n验证: 分布总和={total_dist}, 文献总数={result['total_papers']}, 差异={abs(total_dist - result['total_papers'])}")
            else:
                print(f"Error: {response.status_code}")

        except Exception as e:
            print(f"Error: {e}")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    # 测试不同类型的关键词
    test_cases = [
        ["预算管理"],           # 单个关键词
        ["预算绩效"],           # 另一个单个关键词
        ["人工智能", "教育"],    # 两个关键词组合
        ["区块链", "金融"]       # 另一个两个关键词组合
    ]
    
    test_keywords(test_cases)
