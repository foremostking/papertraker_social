"""
抓取CNKI全部期刊数据

特性：
- 继承反爬虫策略（延迟、UA轮换、重试）
- 检查点恢复（可随时中断继续）
- 支持数据库/JSON双模式
- 预计数据量：数万本期刊
- 预计时间：根据页数确定

使用方法:
    # JSON模式（保存到文件）
    python scripts/fetch_all_journals.py

    # 数据库模式（直接写入数据库）
    python scripts/fetch_all_journals.py --db

    # 同时保存JSON和数据库
    python scripts/fetch_all_journals.py --db --json

    # 测试模式（只抓取前几页）
    python scripts/fetch_all_journals.py --max-pages 2

    # 显示浏览器（观察模式）
    python scripts/fetch_all_journals.py --headful
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
    parser = argparse.ArgumentParser(description='抓取CNKI全部期刊数据')
    parser.add_argument('--db', action='store_true', help='写入数据库')
    parser.add_argument('--json', action='store_true', help='保存JSON文件')
    parser.add_argument('--headful', action='store_true', help='显示浏览器（观察模式）')
    parser.add_argument('--max-pages', type=int, default=None, help='最大抓取页数（用于测试）')
    args = parser.parse_args()

    use_db = args.db
    save_json = args.json or not args.db  # 默认保存JSON，除非指定--db且不指定--json

    print("=" * 70)
    print("CNKI 全部期刊抓取")
    print("=" * 70)
    print("\n模式:")
    if use_db:
        print("  - 数据库模式: 是")
    if save_json:
        print("  - JSON保存: 是")
    if args.max_pages:
        print(f"  - 测试模式: 仅抓取前 {args.max_pages} 页")
    print("\n反爬虫策略:")
    print("  - 随机延迟: 1.5-4秒/页")
    print("  - User-Agent轮换: 8个")
    print("  - 自动重试: 最多3次")
    print("  - 检查点: 每5页保存")
    print("\n注意: 全部期刊数据量可能很大，抓取时间较长")
    print("按Ctrl+C可随时中断（已抓取的数据会自动保存，可恢复）\n")

    try:
        await asyncio.sleep(2)

        # 创建抓取器，不指定click_name则获取全部期刊
        fetcher = CNKICSSCIFetcherAntiDetection(
            headless=not args.headful,
            use_db=use_db,
            click_name=''  # 空字符串表示不筛选，获取全部期刊
        )

        print("开始抓取...")
        print("-" * 70)

        # 抓取期刊
        journals = await fetcher.fetch_cssci_journals(max_pages=args.max_pages)

        print("\n" + "=" * 70)
        print("抓取完成!")
        print("=" * 70)

        if journals:
            print(f"\n成功抓取 {len(journals)} 本期刊")

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

            # CSSCI期刊统计
            cssci_count = len([j for j in journals if j.get('is_cssci')])
            print(f"\nCSSCI期刊: {cssci_count} 本")

            # 保存JSON（如果需要）
            if save_json:
                output_file = "data/journals/all_journals.json"
                fetcher.save_to_json(output_file, force=True)

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
