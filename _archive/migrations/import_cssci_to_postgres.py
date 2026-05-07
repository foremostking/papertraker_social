"""
将CSSCI期刊JSON数据直接导入PostgreSQL

从 cssci_journals_all.json 导入到 PostgreSQL journals 表

使用方法:
    1. 启动PostgreSQL: docker-compose up -d
    2. 配置.env文件
    3. python scripts/import_cssci_to_postgres.py
"""

import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def import_cssci_to_postgres(
    json_file: str = "data/journals/cssci_journals_all.json",
    database_url: str = None
):
    """导入CSSCI期刊数据到PostgreSQL"""

    print("=" * 70)
    print("CSSCI期刊数据导入 (PostgreSQL)")
    print("=" * 70)

    # 获取数据库URL
    if database_url is None:
        # 尝试从环境变量加载
        from dotenv import load_dotenv
        load_dotenv("backend/.env")
        database_url = os.getenv('DATABASE_URL')

    if database_url is None:
        database_url = 'postgresql://postgres:password@localhost:5432/papertracker_social'

    print(f"\n数据库: {database_url}")

    # 测试连接
    from sqlalchemy import create_engine, text
    try:
        engine = create_engine(database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[OK] 数据库连接成功")
    except Exception as e:
        print(f"\n[错误] 数据库连接失败: {e}")
        print("\n请确保:")
        print("  1. PostgreSQL正在运行 (docker-compose up -d)")
        print("  2. .env文件配置正确")
        print("  3. 数据库已创建")
        return

    # 创建表结构
    print("\n创建表结构...")
    from app.models.journal import Base, Journal as JournalModel
    try:
        Base.metadata.create_all(bind=engine)
        print("[OK] 表结构创建成功")
    except Exception as e:
        print(f"[警告] 表结构创建: {e}")

    # 读取JSON数据
    print(f"\n读取数据文件: {json_file}")
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    journals_data = data.get('journals', [])
    print(f"[OK] 总记录数: {len(journals_data)}")

    # 导入数据
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        added = 0
        updated = 0
        skipped = 0

        print("\n开始导入...")
        print("-" * 70)

        for i, item in enumerate(journals_data, 1):
            try:
                # 检查是否已存在
                existing = db.query(JournalModel).filter(
                    JournalModel.name == item['name']
                ).first()

                if existing:
                    # 更新
                    existing.issn = item.get('issn')
                    existing.cn = item.get('cn')
                    existing.publisher = item.get('publisher')
                    existing.composite_impact_factor = float(item['composite_impact_factor']) if item.get('composite_impact_factor') else None
                    existing.comprehensive_impact_factor = float(item['comprehensive_impact_factor']) if item.get('comprehensive_impact_factor') else None
                    existing.is_network_first = item.get('is_network_first', False)
                    existing.is_enhanced_publishing = item.get('is_enhanced_publishing', False)
                    existing.detail_url = item.get('detail_url')
                    existing.is_cssci = item.get('is_cssci', True)
                    existing.cssci_year = item.get('cssci_year')
                    existing.source = item.get('source')
                    db.commit()
                    updated += 1
                    if updated % 100 == 0:
                        print(f"  更新进度: {updated}/{len(journals_data)}")
                else:
                    # 新增
                    journal = JournalModel(
                        name=item['name'],
                        issn=item.get('issn'),
                        cn=item.get('cn'),
                        publisher=item.get('publisher'),
                        composite_impact_factor=float(item['composite_impact_factor']) if item.get('composite_impact_factor') else None,
                        comprehensive_impact_factor=float(item['comprehensive_impact_factor']) if item.get('comprehensive_impact_factor') else None,
                        is_network_first=item.get('is_network_first', False),
                        is_enhanced_publishing=item.get('is_enhanced_publishing', False),
                        detail_url=item.get('detail_url'),
                        is_cssci=item.get('is_cssci', True),
                        cssci_year=item.get('cssci_year'),
                        source=item.get('source')
                    )
                    db.add(journal)
                    db.commit()
                    added += 1
                    if added % 100 == 0:
                        print(f"  新增进度: {added}/{len(journals_data)}")

            except Exception as e:
                print(f"  [ERROR] 第{i}条记录失败: {item.get('name', 'Unknown')} - {e}")
                skipped += 1
                db.rollback()
                continue

        print("\n" + "=" * 70)
        print("导入完成!")
        print("=" * 70)

        # 统计结果
        total_in_db = db.query(JournalModel).count()

        print(f"\n导入统计:")
        print(f"  新增记录: {added}")
        print(f"  更新记录: {updated}")
        print(f"  跳过记录: {skipped}")
        print(f"  数据库总数: {total_in_db}")

        # 字段完整度
        print(f"\n字段完整度:")
        with_issn = db.query(JournalModel).filter(JournalModel.issn != None, JournalModel.issn != '').count()
        with_cn = db.query(JournalModel).filter(JournalModel.cn != None, JournalModel.cn != '').count()
        with_publisher = db.query(JournalModel).filter(JournalModel.publisher != None, JournalModel.publisher != '').count()
        with_composite_if = db.query(JournalModel).filter(JournalModel.composite_impact_factor != None).count()
        network_first = db.query(JournalModel).filter(JournalModel.is_network_first == True).count()
        enhanced = db.query(JournalModel).filter(JournalModel.is_enhanced_publishing == True).count()

        print(f"  ISSN: {with_issn}/{total_in_db} ({with_issn/total_in_db*100:.1f}%)")
        print(f"  CN: {with_cn}/{total_in_db} ({with_cn/total_in_db*100:.1f}%)")
        print(f"  主办单位: {with_publisher}/{total_in_db} ({with_publisher/total_in_db*100:.1f}%)")
        print(f"  复合影响因子: {with_composite_if}/{total_in_db} ({with_composite_if/total_in_db*100:.1f}%)")
        print(f"  网络首发: {network_first}/{total_in_db} ({network_first/total_in_db*100:.1f}%)")
        print(f"  增强出版: {enhanced}/{total_in_db} ({enhanced/total_in_db*100:.1f}%)")

        # 显示样本
        print(f"\n期刊样本 (前5本):")
        samples = db.query(JournalModel).order_by(JournalModel.composite_impact_factor.desc()).limit(5).all()
        for j in samples:
            print(f"  - {j.name}")
            if j.composite_impact_factor:
                print(f"    复合IF: {j.composite_impact_factor}, 综合IF: {j.comprehensive_impact_factor}")

        print("\n✓ PostgreSQL数据库已就绪！")

    finally:
        db.close()


if __name__ == '__main__':
    asyncio.run(import_cssci_to_postgres())
