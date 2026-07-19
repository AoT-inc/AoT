# coding=utf-8
"""Add role and specialty columns to the ai_agent table."""
import sqlite3
import os

db_path = os.getenv('AOT_DB_FILE',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../databases/aot.db'))

def migrate_ai_agent():
    """Add role and specialty columns to ai_agent if they do not exist.

    @phase migration
    @dependency sqlite3
    """
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("--- AI Agent Schema Migration ---")
    
    # Add role column
    try:
        cursor.execute("ALTER TABLE ai_agent ADD COLUMN role VARCHAR(20) DEFAULT 'worker'")
        print("Column 'role' added.")
    except sqlite3.OperationalError:
        print("Column 'role' already exists.")

    # Add specialty column
    try:
        cursor.execute("ALTER TABLE ai_agent ADD COLUMN specialty VARCHAR(100) DEFAULT 'general'")
        print("Column 'specialty' added.")
    except sqlite3.OperationalError:
        print("Column 'specialty' already exists.")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate_ai_agent()
