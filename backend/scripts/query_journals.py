"""
期刊数据库查询工具

支持 SQLite 和 PostgreSQL

使用方法:
    # 统计信息
    python scripts/query_journals.py stats

    # 搜索期刊
    python scripts/query_journals.py search 经济

    # 影响因子TOP
    python scripts/query_journals.py top -l 10

    # 按主办单位查询
    python scripts/query_journals.py publisher 北京大学

    # 使用PostgreSQL
    python scripts/query_journals.py stats --db postgres
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def get_db_session(db_type='sqlite'):
    """获取数据库会话"""

    if db_type == 'postgres':
        # 尝试从环境变量加载
        try:
            from dotenv import load_dotenv
            load_dotenv("backend/.env")
            database_url = os.getenv('DATABASE_URL')
        except:
            database_url = None

        if not database_url:
            database_url = 'postgresql://postgres:password@localhost:5432/papertracker_social'

        print(f"使用PostgreSQL: {database_url}")
        engine = create_engine(database_url, pool_pre_ping=True)
    else:
        # SQLite
        db_path = "data/journals.db"
        print(f"使用SQLite: {db_path}")
        engine = create_engine(f'sqlite:///{db_path}')

    return sessionmaker(bind=engine)()


def search_by_name(keyword: str, limit: int = 20, db_type='sqlite'):
    """按期刊名称搜索"""
    db = get_db_session(db_type)
    try:
        results = db.execute(text("""
            SELECT name, issn, cn, publisher,
                   composite_impact_factor, comprehensive_impact_factor
            FROM journals
            WHERE name LIKE :keyword
            ORDER BY composite_impact_factor DESC
            LIMIT :limit
        """), {"keyword": f"%{keyword}%", "limit": limit}).fetchall()

        print(f"\n找到 {len(results)} 本期刊:")
        print("-" * 80)
        for r in results:
            print(f"\n期刊: {r[0]}")
            if r[1]: print(f"  ISSN: {r[1]}")
            if r[2]: print(f"  CN: {r[2]}")
            if r[3]: print(f"  主办单位: {r[3]}")
            if r[4]: print(f"  复合IF: {r[4]}, 综合IF: {r[5]}")
    finally:
        db.close()


def get_top_impact_factor(limit: int = 20, db_type='sqlite'):
    """获取影响因子最高的期刊"""
    db = get_db_session(db_type)
    try:
        results = db.execute(text("""
            SELECT name, composite_impact_factor, comprehensive_impact_factor, publisher
            FROM journals
            WHERE composite_impact_factor IS NOT NULL
            ORDER BY composite_impact_factor DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()

        print(f"\n复合影响因子 TOP {len(results)}:")
        print("-" * 80)
        for i, r in enumerate(results, 1):
            print(f"{i}. {r[0]}")
            print(f"   复合IF: {r[1]}, 综合IF: {r[2]}")
            if r[3]: print(f"   主办单位: {r[3]}")
    finally:
        db.close()


def get_stats(db_type='sqlite'):
    """获取数据库统计信息"""
    db = get_db_session(db_type)
    try:
        total = db.execute(text("SELECT COUNT(*) FROM journals")).scalar()
        cssci = db.execute(text("SELECT COUNT(*) FROM journals WHERE is_cssci = TRUE")).scalar()

        with_issn = db.execute(text("SELECT COUNT(*) FROM journals WHERE issn IS NOT NULL AND issn != ''")).scalar()
        with_cn = db.execute(text("SELECT COUNT(*) FROM journals WHERE cn IS NOT NULL AND cn != ''")).scalar()
        with_publisher = db.execute(text("SELECT COUNT(*) FROM journals WHERE publisher IS NOT NULL AND publisher != ''")).scalar()
        with_composite_if = db.execute(text("SELECT COUNT(*) FROM journals WHERE composite_impact_factor IS NOT NULL")).scalar()

        network_first = db.execute(text("SELECT COUNT(*) FROM journals WHERE is_network_first = TRUE")).scalar()
        enhanced = db.execute(text("SELECT COUNT(*) FROM journals WHERE is_enhanced_publishing = TRUE")).scalar()

        print("\n" + "=" * 50)
        print("期刊数据库统计")
        print("=" * 50)
        print(f"\n总期刊数: {total}")
        print(f"CSSCI期刊: {cssci}")

        print(f"\n字段完整度:")
        print(f"  ISSN: {with_issn}/{total} ({with_issn/total*100:.1f}%)")
        print(f"  CN: {with_cn}/{total} ({with_cn/total*100:.1f}%)")
        print(f"  主办单位: {with_publisher}/{total} ({with_publisher/total*100:.1f}%)")
        print(f"  复合影响因子: {with_composite_if}/{total} ({with_composite_if/total*100:.1f}%)")

        print(f"\n出版模式:")
        print(f"  网络首发: {network_first}/{total} ({network_first/total*100:.1f}%)")
        print(f"  增强出版: {enhanced}/{total} ({enhanced/total*100:.1f}%)")

    finally:
        db.close()


def list_by_publisher(keyword: str, limit: int = 20, db_type='sqlite'):
    """按主办单位查询"""
    db = get_db_session(db_type)
    try:
        results = db.execute(text("""
            SELECT name, publisher, composite_impact_factor
            FROM journals
            WHERE publisher LIKE :keyword
            ORDER BY composite_impact_factor DESC
            LIMIT :limit
        """), {"keyword": f"%{keyword}%", "limit": limit}).fetchall()

        print(f"\n主办单位包含 '{keyword}' 的期刊 (共{len(results)}本):")
        print("-" * 80)
        for r in results:
            print(f"\n{r[0]}")
            print(f"  主办单位: {r[1]}")
            if r[2]: print(f"  复合IF: {r[2]}")
    finally:
        db.close()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='期刊数据库查询工具')
    parser.add_argument('--db', choices=['sqlite', 'postgres'], default='sqlite',
                        help='数据库类型 (默认: sqlite)')

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # 搜索命令
    search_parser = subparsers.add_parser('search', help='按名称搜索期刊')
    search_parser.add_argument('keyword', help='搜索关键词')
    search_parser.add_argument('-l', '--limit', type=int, default=20, help='结果数量')

    # 影响因子TOP命令
    top_parser = subparsers.add_parser('top', help='影响因子TOP期刊')
    top_parser.add_argument('-l', '--limit', type=int, default=20, help='结果数量')

    # 主办单位命令
    pub_parser = subparsers.add_parser('publisher', help='按主办单位查询')
    pub_parser.add_argument('keyword', help='主办单位关键词')
    pub_parser.add_argument('-l', '--limit', type=int, default=20, help='结果数量')

    # 统计命令
    subparsers.add_parser('stats', help='数据库统计')

    args = parser.parse_args()

    if not args.command:
        get_stats(args.db)
        return

    if args.command == 'search':
        search_by_name(args.keyword, args.limit, args.db)
    elif args.command == 'top':
        get_top_impact_factor(args.limit, args.db)
    elif args.command == 'publisher':
        list_by_publisher(args.keyword, args.limit, args.db)
    elif args.command == 'stats':
        get_stats(args.db)


if __name__ == '__main__':
    main()
