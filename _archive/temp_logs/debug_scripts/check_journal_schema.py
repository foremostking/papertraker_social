"""
检查期刊表字段
"""
import os
from sqlalchemy import inspect, create_engine

def get_engine():
    """Get database engine from environment"""
    database_url = os.getenv('DATABASE_URL', 'postgresql://postgres:password@postgres:5432/papertracker_social')
    return create_engine(database_url)

def check_journal_columns():
    """检查期刊表的字段"""
    engine = get_engine()

    print("检查期刊表字段...\n")

    inspector = inspect(engine)
    journal_columns = inspector.get_columns('journals')

    print(f"期刊表共有 {len(journal_columns)} 个字段：\n")

    # 按模型中的顺序显示
    field_order = [
        'id', 'name', 'name_en', 'issn', 'cn',
        'is_cssci', 'is_cssci_expansion', 'is_beida_core', 'cssci_year',
        'field', 'subfield',
        'cnki_source_id', 'cnki_url', 'journal_code',
        'official_url', 'email',
        'framework_analyzed', 'total_papers', 'last_paper_date',
        'impact_factor', 'composite_impact_factor', 'comprehensive_impact_factor', 'publisher',
        'is_network_first', 'is_enhanced_publishing',
        'source', 'detail_url',
        'publishing_cycle', 'publishing_location', 'language', 'format',
        'postal_code', 'founded_year', 'total_documents', 'total_downloads',
        'total_citations', 'journal_tags', 'journal_columns',
        'journal_columns_detail', 'cnki_detail_last_updated',
        'created_at', 'updated_at'
    ]

    # 创建字段字典
    col_dict = {col['name']: col for col in journal_columns}

    for field_name in field_order:
        if field_name in col_dict:
            col = col_dict[field_name]
            nullable = "NULL" if col['nullable'] else "NOT NULL"
            default = f" DEFAULT {col['default']}" if col['default'] else ""
            print(f"  ✓ {col['name']:25} {str(col['type']):20} {nullable:8}{default}")
        else:
            print(f"  ✗ {field_name:25} 缺失")

    print(f"\n数据库中实际存在的所有字段：")
    for col in journal_columns:
        print(f"  - {col['name']} ({col['type']})")

if __name__ == "__main__":
    check_journal_columns()
