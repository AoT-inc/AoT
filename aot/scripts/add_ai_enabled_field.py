#!/usr/bin/env python
# coding=utf-8
"""
Migration script to add ai_enabled field to AIGlobalSettings table.
This field controls whether AI features are enabled system-wide.
"""
import sys
import os
import sqlite3

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(__file__, "../../../")))

def migrate():
    """Add ai_enabled column to ai_global_settings table if absent.

    @phase migration
    @stability stable
    @dependency sqlite3
    """
    print("Checking AIGlobalSettings table for ai_enabled field...")
    
    # Find database file
    db_paths = [
        'aot/databases/aot.db',
        'aot.db',
        '../aot.db'
    ]
    
    db_path = None
    for path in db_paths:
        if os.path.exists(path):
            db_path = path
            break
    
    if not db_path:
        print("✗ Database file not found. Tried paths:")
        for path in db_paths:
            print(f"  - {path}")
        return False
    
    print(f"Using database: {db_path}")
    
    try:
        # Connect directly to SQLite
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("PRAGMA table_info(ai_global_settings)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'ai_enabled' in columns:
            print("✓ ai_enabled field already exists. No migration needed.")
            conn.close()
            return True
            
        print("Adding ai_enabled field to AIGlobalSettings table...")
        
        # Add column with default value False (0 in SQLite)
        cursor.execute(
            "ALTER TABLE ai_global_settings ADD COLUMN ai_enabled BOOLEAN DEFAULT 0 NOT NULL"
        )
        conn.commit()
        
        print("✓ Successfully added ai_enabled field.")
        print("  Default value: False (AI features disabled by default)")
        print("  Users must explicitly enable AI features in the AI settings page.")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"✗ Migration failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)
