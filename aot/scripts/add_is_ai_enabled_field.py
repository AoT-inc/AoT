# coding=utf-8
"""
Migration script — TASK_30 / Pillar 1
Adds is_ai_enabled (BOOLEAN, default 0) to the 'input' and 'output' tables.
Safe to run multiple times (idempotent).
"""
import os
import sqlite3


def migrate():
    """Add is_ai_enabled column to input and output tables idempotently.

    @phase migration
    @stability stable
    @dependency sqlite3
    """
    # Script is at aot/scripts/; DB is at aot/databases/aot.db
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "databases", "aot.db"
    )
    if not os.path.exists(db_path):
        # Fallback: three levels up + databases/aot.db
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "databases", "aot.db"
        )
    if not os.path.exists(db_path):
        print(f"ERROR: Could not locate aot.db. Tried: {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    changed = False

    for table in ("input", "output"):
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in cursor.fetchall()]
        if "is_ai_enabled" not in cols:
            cursor.execute(
                f"ALTER TABLE {table} ADD COLUMN is_ai_enabled BOOLEAN DEFAULT 0 NOT NULL"
            )
            print(f"✓ Added is_ai_enabled to '{table}' table.")
            changed = True
        else:
            print(f"  is_ai_enabled already exists in '{table}'. Skipping.")

    if changed:
        conn.commit()
    conn.close()
    return True


if __name__ == "__main__":
    migrate()
