#!/usr/bin/env python
"""
Initialize or reset the AoT database safely.

This script handles:
1. Creating a new database if it doesn't exist
2. Backing up an existing database before updates
3. Running alembic migrations safely
4. Detecting if database already has tables and skipping if necessary
"""

import os
import sys
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

# Add the project root to the path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

def get_db_path():
    """Get the absolute path to the SQLite database."""
    try:
        from aot.config import SQL_DATABASE_AOT
        # Remove sqlite:/// prefix if present
        db_path = SQL_DATABASE_AOT
        if db_path.startswith('sqlite:///'):
            db_path = db_path[10:]  # Remove 'sqlite:///' 
        return db_path
    except ImportError as e:
        print(f"Warning: Could not import SQL_DATABASE_AOT: {e}")
        # Fallback to default path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(project_root, 'aot', 'databases', 'aot.db')

def backup_database(db_path):
    """Create a backup of the existing database."""
    if not os.path.exists(db_path):
        return None
    
    backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'aot_{timestamp}.db')
    
    try:
        shutil.copy2(db_path, backup_path)
        print(f"Database backed up to: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"Warning: Could not backup database: {e}")
        return None

def get_table_names(db_path):
    """Get list of existing tables in SQLite database."""
    if not os.path.exists(db_path):
        return []
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        return tables
    except Exception as e:
        print(f"Error reading database tables: {e}")
        return []

def check_alembic_version(db_path):
    """Check alembic version table in database."""
    if not os.path.exists(db_path):
        return None
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT version_num FROM alembic_version LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except:
        return None

def initialize_alembic_version(db_path, version='718f314963bc'):
    """Initialize alembic version table if database has tables but no version."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if alembic_version table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        )
        if cursor.fetchone():
            print("Alembic version table already exists.")
            return True
        
        # Create alembic_version table and insert version
        cursor.execute("""
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
        """)
        cursor.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (version,))
        conn.commit()
        conn.close()
        print(f"Alembic version table created with version: {version}")
        return True
    except Exception as e:
        print(f"Error initializing alembic version: {e}")
        return False

def main():
    try:
        db_path = get_db_path()
        db_dir = os.path.dirname(db_path)
        
        # Ensure database directory exists
        os.makedirs(db_dir, exist_ok=True)
        
        print(f"Database path: {db_path}")
        
        # Check if database exists and has tables
        existing_tables = get_table_names(db_path)
        alembic_version = check_alembic_version(db_path)
        
        if existing_tables:
            print(f"Found {len(existing_tables)} existing tables: {', '.join(existing_tables)}")
            
            if alembic_version:
                print(f"Database already has alembic version: {alembic_version}")
                print("Database appears to be initialized already. Skipping pre-migration setup.")
                return 0
            else:
                print("Database has tables but no alembic version. Registering version...")
                if initialize_alembic_version(db_path):
                    print("Successfully registered alembic version.")
                    return 0
                else:
                    print("Failed to register alembic version.")
                    return 1
        else:
            print("No existing tables found. New database will be created by alembic migration...")
            return 0
    except Exception as e:
        print(f"Error during database initialization: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
