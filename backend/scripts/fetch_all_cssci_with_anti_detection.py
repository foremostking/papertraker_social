"""
完整抓取所有51页CSSCI期刊（反爬虫增强版）

特性：
- 随机延迟和User-Agent轮换
- 检查点恢复（可随时中断继续）
- 重试机制
- 支持直接写入数据库
- 预计时间：2-3分钟（无头模式）/ 3-5分钟（观察模式）

使用方法:
    # JSON模式（保存到文件）
    python scripts/fetch_all_cssci_with_anti_detection.py

    # 数据库模式（直接写入数据库）
    python scripts/fetch_all_cssci_with_anti_detection.py --db

    # 同时保存JSON和数据库
    python scripts/fetch_all_cssci_with_anti_detection.py --db --json
"""

import asyncio
import sys
import os
import argparse

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.cnki_cssci_fetcher_anti_detection import CNKICSSCIFetcherAntiDetection


async def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='抓取CSSCI期刊数据')
    parser.add_argument('--db', action='store_true', help='写入数据库')
    parser.add_argument('--json', action='store_true', help='保存JSON文件')
    parser.add_argument('--headful', action='store_true', help='显示浏览器（观察模式）')
    args = parser.parse_args()

    use_db = args.db
    save_json = args.json or not args.db  # 默认保存JSON，除非指定--db且不指定--json

    print("=" * 70)
    print("CNKI CSSCI期刊完整抓取（反爬虫增强版）")
    print("=" * 70)
    print("\n目标:")
    print("  - 总页数: 51页")
    print("  - 预计期刊数: 1062本")
    print("  - 预计时间: 3-5分钟")
    print("\n模式:")
    if use_db:
        print("  - 数据库模式: 是")
    if save_json:
        print("  - JSON保存: 是")
    print("\n反爬虫策略:")
    print("  - 随机延迟: 1.5-4秒/页")
    print("  - User-Agent轮换: 8个")
    print("  - 自动重试: 最多3次")
    print("  - 检查点: 每5页保存")
    print("\n按Ctrl+C可随时中断（已抓取的数据会自动保存，可恢复）\n")

    try:
        await asyncio.sleep(2)

        # 创建抓取器
        fetcher = CNKICSSCIFetcherAntiDetection(
            headless=not args.headful,
            use_db=use_db
        )

        print("开始抓取...")
        print("-" * 70)

        # 抓取全部51页（max_pages=None表示全部）
        journals = await fetcher.fetch_cssci_journals(max_pages=None)

        print("\n" + "=" * 70)
        print("抓取完成!")
        print("=" * 70)

        if journals:
            print(f"\n成功抓取 {len(journals)} 本CSSCI期刊")

            # 显示完整统计
            print(f"\n数据统计:")
            print(f"  总页数: {fetcher.stats['total_pages']}")
            print(f"  总期刊数: {len(journals)}")
            print(f"  重试次数: {fetcher.stats['retry_count']}")
            print(f"  失败页面: {fetcher.stats['failed_pages']}")
            if use_db:
                print(f"  数据库新增: {fetcher.stats.get('added_to_db', 0)}")
                print(f"  数据库更新: {fetcher.stats.get('updated_in_db', 0)}")

            # 字段完整度
            with_issn = len([j for j in journals if j.get('issn')])
            with_cn = len([j for j in journals if j.get('cn')])
            with_publisher = len([j for j in journals if j.get('publisher')])

            print(f"\n字段完整度:")
            print(f"  ISSN: {with_issn}/{len(journals)} ({with_issn/len(journals)*100:.1f}%)")
            print(f"  CN: {with_cn}/{len(journals)} ({with_cn/len(journals)*100:.1f}%)")
            print(f"  主办单位: {with_publisher}/{len(journals)} ({with_publisher/len(journals)*100:.1f}%)")

            # 保存JSON（如果需要）
            if save_json:
                output_file = "data/journals/cssci_journals_all.json"
                fetcher.save_to_json(output_file, force=True)

            # 按主办单位分类统计
            print(f"\n主办单位分布:")
            journals_by_publisher = {}
            for journal in journals:
                publisher = journal.get('publisher', 'Unknown')
                if publisher:
                    # 提取主办单位的关键词
                    if '中国科学院' in publisher or '中国社科院' in publisher:
                        key = '科学院系统'
                    elif '大学' in publisher or '学院' in publisher:
                        key = '高校系统'
                    elif '学会' in publisher:
                        key = '学会系统'
                    elif '研究' in publisher:
                        key = '研究机构'
                    else:
                        key = '其他'

                    journals_by_publisher[key] = journals_by_publisher.get(key, 0) + 1

            for key, count in sorted(journals_by_publisher.items(), key=lambda x: -x[1]):
                print(f"  {key}: {count}本")

            # 如果有失败页面，提示
            if fetcher.stats['failed_pages']:
                print(f"\n[提示] 以下页面获取失败，可重新运行:")
                for page in fetcher.stats['failed_pages']:
                    print(f"  - 第{page}页")

        else:
            print("\n[FAIL] 未抓取到期刊数据")

    except KeyboardInterrupt:
        print("\n\n[INFO] 用户中断")
        print("已抓取的数据已保存在检查点文件中")
        print("重新运行脚本从上次位置继续")

    except Exception as e:
        print(f"\n[ERROR] 抓取失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(main())
