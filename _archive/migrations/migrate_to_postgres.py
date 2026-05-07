"""
SQLite数据迁移到PostgreSQL

将SQLite中的期刊数据迁移到PostgreSQL数据库

使用方法:
    1. 确保PostgreSQL正在运行
    2. 配置.env文件中的DATABASE_URL
    3. python scripts/migrate_to_postgres.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import json


def migrate():
    """迁移SQLite数据到PostgreSQL"""

    print("=" * 70)
    print("SQLite -> PostgreSQL 数据迁移")
    print("=" * 70)

    # 1. 连接SQLite（源数据库）
    sqlite_db = "data/journals.db"
    if not os.path.exists(sqlite_db):
        print(f"\n[错误] SQLite数据库不存在: {sqlite_db}")
        return

    sqlite_engine = create_engine(f'sqlite:///{sqlite_db}')
    sqlite_session = sessionmaker(bind=sqlite_engine)()

    # 2. 连接PostgreSQL（目标数据库）
    print("\n请确认PostgreSQL配置:")
    print("  1. PostgreSQL正在运行")
    print("  2. .env文件中DATABASE_URL已正确配置")
    print("  3. 数据库已创建")

    # 从环境变量或默认值获取数据库URL
    database_url = os.getenv('DATABASE_URL', 'postgresql://postgres:password@localhost:5432/papertracker_social')
    print(f"\n目标数据库: {database_url}")

    try:
        pg_engine = create_engine(database_url)
        pg_session = sessionmaker(bind=pg_engine)()

        # 测试连接
        pg_session.execute(text("SELECT 1"))
        print("✓ PostgreSQL连接成功")

    except Exception as e:
        print(f"\n[错误] 无法连接到PostgreSQL: {e}")
        print("\n请确保:")
        print("  1. PostgreSQL已安装并运行")
        print("  2. 数据库已创建: CREATE DATABASE papertracker_social;")
        print("  3. .env文件配置正确")
        return

    # 3. 创建表结构（使用项目模型）
    print("\n创建PostgreSQL表结构...")
    try:
        from app.models.journal import Base
        Base.metadata.create_all(bind=pg_engine)
        print("✓ 表结构创建成功")
    except Exception as e:
        print(f"[错误] 表结构创建失败: {e}")
        return

    # 4. 读取SQLite数据
    print("\n读取SQLite数据...")
    result = sqlite_session.execute(text("SELECT * FROM journals"))
    journals_data = result.fetchall()
    columns = result.keys()

    print(f"✓ 读取到 {len(journals_data)} 条期刊记录")

    # 5. 插入PostgreSQL
    print("\n导入数据到PostgreSQL...")
    added = 0
    updated = 0

    for i, row in enumerate(journals_data, 1):
        try:
            # 转换为字典
            data = dict(zip(columns, row))

            # 检查是否已存在
            existing = pg_session.execute(
                text("SELECT id FROM journals WHERE name = :name"),
                {"name": data['name']}
            ).fetchone()

            if existing:
                # 更新
                pg_session.execute(text("""
                    UPDATE journals SET
                        issn = :issn,
                        cn = :cn,
                        publisher = :publisher,
                        composite_impact_factor = :composite_impact_factor,
                        comprehensive_impact_factor = :comprehensive_impact_factor,
                        is_network_first = :is_network_first,
                        is_enhanced_publishing = :is_enhanced_publishing,
                        detail_url = :detail_url,
                        is_cssci = :is_cssci,
                        cssci_year = :cssci_year,
                        source = :source,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE name = :name
                """), data)
                updated += 1
            else:
                # 新增
                pg_session.execute(text("""
                    INSERT INTO journals (
                        name, issn, cn, publisher,
                        composite_impact_factor, comprehensive_impact_factor,
                        is_network_first, is_enhanced_publishing,
                        detail_url, is_cssci, cssci_year, source
                    ) VALUES (
                        :name, :issn, :cn, :publisher,
                        :composite_impact_factor, :comprehensive_impact_factor,
                        :is_network_first, :is_enhanced_publishing,
                        :detail_url, :is_cssci, :cssci_year, :source
                    )
                """), data)
                added += 1

            if i % 100 == 0:
                pg_session.commit()
                print(f"  进度: {i}/{len(journals_data)}")

        except Exception as e:
            print(f"  [错误] 第{i}条记录失败: {e}")
            pg_session.rollback()
            continue

    pg_session.commit()

    print("\n" + "=" * 70)
    print("迁移完成!")
    print("=" * 70)
    print(f"\n新增记录: {added}")
    print(f"更新记录: {updated}")

    # 验证
    total = pg_session.execute(text("SELECT COUNT(*) FROM journals")).scalar()
    print(f"PostgreSQL总记录数: {total}")

    sqlite_session.close()
    pg_session.close()

    print("\n✓ 数据迁移成功！现在可以使用PostgreSQL数据库了")


def create_sqlite_backup():
    """创建SQLite备份（可选）"""
    import shutil
    from datetime import datetime

    sqlite_db = "data/journals.db"
    if os.path.exists(sqlite_db):
        backup_name = f"data/journals_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(sqlite_db, backup_name)
        print(f"✓ SQLite备份已创建: {backup_name}")


if __name__ == '__main__':
    # 创建备份
    create_sqlite_backup()

    # 执行迁移
    migrate()
