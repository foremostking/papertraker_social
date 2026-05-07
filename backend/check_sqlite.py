import sqlite3
conn = sqlite3.connect('data/papertracker.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('SQLite tables:', [t[0] for t in tables])
for table in tables:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
        count = cursor.fetchone()[0]
        print(f"  {table[0]}: {count} rows")
    except Exception as e:
        print(f"  {table[0]}: error - {e}")
conn.close()
