"""
检查期刊ID 964的数据
"""
import os
from sqlalchemy import create_engine, text

def get_engine():
    """Get database engine from environment"""
    database_url = os.getenv('DATABASE_URL', 'postgresql://postgres:password@postgres:5432/papertracker_social')
    return create_engine(database_url)

def check_journal_964():
    """检查期刊ID 964的字段数据"""
    engine = get_engine()

    print("检查期刊 ID 964 的数据...\n")

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                id,
                name,
                field AS "一级学科",
                subfield AS "二级学科",
                cnki_detail_last_updated AS "CNKI更新时间",
                detail_url AS "详情URL"
            FROM journals
            WHERE id = 964
        """))

        row = result.fetchone()
        if row:
            print(f"期刊ID: {row[0]}")
            print(f"期刊名称: {row[1]}")
            print(f"一级学科(field): {row[2]}")
            print(f"二级学科(subfield): {row[3]}")
            print(f"CNKI更新时间: {row[4]}")
            print(f"详情URL: {row[5][:80] if row[5] else None}...")
        else:
            print("未找到ID为964的期刊")

        # 查找"中国农村研究"的ID
        print("\n查找'中国农村研究'期刊...")
        result2 = conn.execute(text("""
            SELECT
                id,
                name,
                field AS "一级学科",
                subfield AS "二级学科",
                cnki_detail_last_updated AS "CNKI更新时间"
            FROM journals
            WHERE name = '中国农村研究'
        """))

        row2 = result2.fetchone()
        if row2:
            print(f"\n找到期刊:")
            print(f"  期刊ID: {row2[0]}")
            print(f"  期刊名称: {row2[1]}")
            print(f"  一级学科: {row2[2]}")
            print(f"  二级学科: {row2[3]}")
            print(f"  CNKI更新时间: {row2[4]}")
        else:
            print("未找到名为'中国农村研究'的期刊")

        # 检查最近更新的期刊
        print("\n最近更新的10条期刊（有field数据的）:")
        result3 = conn.execute(text("""
            SELECT
                id,
                name,
                field AS "一级学科",
                subfield AS "二级学科",
                cnki_detail_last_updated AS "CNKI更新时间"
            FROM journals
            WHERE field IS NOT NULL
            ORDER BY cnki_detail_last_updated DESC
            LIMIT 10
        """))

        for row3 in result3:
            print(f"  ID={row3[0]}, 名称={row3[1]}, field={row3[2]}, subfield={row3[3]}, 更新时间={row3[4]}")

if __name__ == "__main__":
    check_journal_964()
