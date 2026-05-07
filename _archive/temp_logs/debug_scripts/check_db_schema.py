"""
Check and create missing database tables and columns
"""
import os
import sys
from sqlalchemy import inspect, text, create_engine
from app.core.database import Base
from app.models.journal import Literature, Journal
from app.models.user import User
from app.models.task import Task

def get_engine():
    """Get database engine from environment"""
    database_url = os.getenv('DATABASE_URL', 'postgresql://postgres:password@postgres:5432/papertracker_social')
    return create_engine(database_url)

def check_and_migrate():
    """Check existing schema and add missing columns"""

    engine = get_engine()

    print("Checking database schema...")

    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    print(f"Existing tables: {existing_tables}")

    # Create tables if they don't exist
    print("\nCreating tables if not exist...")
    Base.metadata.create_all(bind=engine, checkfirst=True)

    # Refresh inspector after creating tables
    inspector = inspect(engine)
    literature_columns = [col['name'] for col in inspector.get_columns('literature')]

    print(f"\nLiterature table columns: {literature_columns}")

    # Required columns for paper fetching
    required_columns = {
        'detail_url': 'VARCHAR(500)',
        'year_issue': 'VARCHAR(20)',
        'download_count': 'INTEGER',
        'column_name': 'VARCHAR(200)',
        'cnki_id': 'VARCHAR(100)'
    }

    missing_columns = [col for col in required_columns if col not in literature_columns]

    if missing_columns:
        print(f"\nMissing columns: {missing_columns}")
        print("Adding missing columns...")

        with engine.connect() as conn:
            for col in missing_columns:
                col_type = required_columns[col]
                if col == 'cnki_id':
                    # Add unique constraint
                    conn.execute(text(f"ALTER TABLE literature ADD COLUMN {col} {col_type} UNIQUE"))
                    conn.commit()
                else:
                    conn.execute(text(f"ALTER TABLE literature ADD COLUMN {col} {col_type}"))
                    conn.commit()
                print(f"  Added column: {col}")

        print("Columns added successfully!")
    else:
        print("\nAll required columns exist!")

    # Refresh inspector
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # Check tasks table
    if 'tasks' not in existing_tables:
        print("\nCreating tasks table...")
        Base.metadata.create_all(bind=engine, checkfirst=True)
        print("Tasks table created!")
    else:
        print("\nTasks table exists!")

    # Check users table
    if 'users' not in existing_tables:
        print("\nCreating users table...")
        Base.metadata.create_all(bind=engine, checkfirst=True)
        print("Users table created!")
    else:
        print("\nUsers table exists!")

    print("\n✅ Database schema check complete!")

if __name__ == "__main__":
    check_and_migrate()
