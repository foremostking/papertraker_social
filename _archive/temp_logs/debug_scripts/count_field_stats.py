"""
统计期刊field/subfield数据情况
"""
import os
from sqlalchemy import create_engine, text

def get_engine():
    """Get database engine from environment"""
    database_url = os.getenv('DATABASE_URL', 'postgresql://postgres:password@postgres:5432/papertracker_social')
    return create_engine(database_url)

def count_field_stats():
    """统计field/subfield数据情况"""
    engine = get_engine()

    print("期刊 field/subfield 数据统计\n")

    with engine.connect() as conn:
        # 总期刊数
        total = conn.execute(text("SELECT COUNT(*) FROM journals")).scalar()

        # 有field的
        has_field = conn.execute(text("SELECT COUNT(*) FROM journals WHERE field IS NOT NULL")).scalar()

        # 有subfield的
        has_subfield = conn.execute(text("SELECT COUNT(*) FROM journals WHERE subfield IS NOT NULL")).scalar()

        # 有detail_url的（可更新的）
        has_detail_url = conn.execute(text("SELECT COUNT(*) FROM journals WHERE detail_url IS NOT NULL")).scalar()

        print(f"总期刊数: {total}")
        print(f"有详情URL的: {has_detail_url}")
        print(f"有一级学科(field)的: {has_field} ({has_field/has_detail_url*100:.1f}% of 有URL的)")
        print(f"有二级学科(subfield)的: {has_subfield} ({has_subfield/has_detail_url*100:.1f}% of 有URL的)")
        print(f"待更新（有URL但无field）: {has_detail_url - has_field}")

        # 统计各专辑数量
        print("\n=== 各专辑（一级学科）期刊数量 ===")
        field_stats = conn.execute(text("""
            SELECT field, COUNT(*) as count
            FROM journals
            WHERE field IS NOT NULL
            GROUP BY field
            ORDER BY count DESC
            LIMIT 20
        """))

        for row in field_stats:
            print(f"  {row[0]}: {row[1]}")

if __name__ == "__main__":
    count_field_stats()
