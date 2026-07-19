"""Migration script to add custom UI color columns to the misc table."""
import sqlite3
import os

# Assuming SQLite default DB path is 'aot/databases/aot.db'
db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../databases/aot.db'))

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

commands = [
    "ALTER TABLE misc ADD COLUMN text_color_primary VARCHAR(7) DEFAULT '#13261B';",
    "ALTER TABLE misc ADD COLUMN text_color_secondary VARCHAR(7) DEFAULT '#5E6B64';",
    "ALTER TABLE misc ADD COLUMN text_color_tertiary VARCHAR(7) DEFAULT '#FFFFFF';",
    "ALTER TABLE misc ADD COLUMN bd_primary VARCHAR(7) DEFAULT '#FFFFFF';",
    "ALTER TABLE misc ADD COLUMN bd_secondary VARCHAR(7) DEFAULT '#F3F6F5';",
    "ALTER TABLE misc ADD COLUMN bd_tertiary VARCHAR(7) DEFAULT '#13261B';",
    "ALTER TABLE misc ADD COLUMN bg_upgrade VARCHAR(7) DEFAULT '#13261B';",
    "ALTER TABLE misc ADD COLUMN bg_active VARCHAR(7) DEFAULT '#B5BABA';",
    "ALTER TABLE misc ADD COLUMN bg_inactive VARCHAR(7) DEFAULT '#F3F6F5';",
    "ALTER TABLE misc ADD COLUMN bg_pause VARCHAR(7) DEFAULT '#B5BABA';",
    "ALTER TABLE misc ADD COLUMN bg_hold VARCHAR(7) DEFAULT '#B5BABA';"
]

for cmd in commands:
    try:
        cursor.execute(cmd)
        print(f"Successfully executed: {cmd}")
    except sqlite3.OperationalError as e:
        print(f"Skipping (likely already exists): {cmd}")
        print(f"Error: {e}")

conn.commit()
conn.close()
print("Direct database schema update complete.")
