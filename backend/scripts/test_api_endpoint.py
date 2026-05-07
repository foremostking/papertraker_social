"""
测试CNKI验证API端点
"""

import asyncio
import requests
import json


def test_validate_cnki_api():
    """测试/api/v1/topic-selection/validate-cnki端点"""
    print("=" * 70)
    print("CNKI Validation API Endpoint Test")
    print("=" * 70)

    # API端点URL
    url = "http://localhost:8000/api/v1/topic-selection/validate-cnki"

    # 请求数据
    request_data = {
        "keywords": ["零基预算"]
    }

    print(f"\n[Request]")
    print(f"URL: {url}")
    print(f"Data: {json.dumps(request_data, ensure_ascii=False)}")
    print("-" * 70)

    try:
        # 发送POST请求
        response = requests.post(
            url,
            json=request_data,
            headers={"Content-Type": "application/json"}
        )

        print(f"\n[Response]")
        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print(f"\n[Validation Result]")
            print(f"Keywords: {result['keywords']}")
            print(f"Search Query: {result['search_query']}")
            print(f"Total Papers: {result['total_papers']}")
            print(f"Core Papers: {result['core_papers']}")
            print(f"Core Ratio: {result['core_ratio']:.2%}")
            print(f"Is Valid: {result['is_valid']}")
            print(f"\nRecommendation:")
            print(f"  {result['recommendation']}")

            print(f"\n[Top Journals]")
            for journal in result['top_journals'][:5]:
                core_types = ', '.join(journal['core_types']) if journal['core_types'] else 'Ordinary'
                print(f"  - {journal['name']} ({journal['count']} papers) - {core_types}")

            print(f"\n[Source Distribution]")
            if result['source_distribution']:
                for source, count in result['source_distribution'].items():
                    if count > 0:
                        print(f"  - {source}: {count} papers")
            else:
                print("  (需要CSSCI数据库才能显示来源类别分布)")
        else:
            print(f"Error: {response.text}")

    except requests.exceptions.ConnectionError:
        print("\n[ERROR] 无法连接到服务器")
        print("请确保后端服务器正在运行:")
        print("  cd d:/副业/papertracker_social/backend")
        print("  python -m uvicorn app.main:app --reload")
    except Exception as e:
        print(f"\n[ERROR] {e}")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    test_validate_cnki_api()
