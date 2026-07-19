"""Migration script to add sort_order column to map_config table."""
import sqlite3
import os


def add_column():
    """Add sort_order integer column to map_config table if absent.

    @phase migration
    @stability stable
    @dependency sqlite3
    """
    # Path relative to script location in AoT/aot/scripts/
    # Target: AoT/databases/aot.db
    # Script is at AoT/aot/scripts/ -> ../../ is AoT/
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
    db_path = os.path.join(base_dir, 'databases', 'aot.db')
    
    print(f"Connecting to database at: {db_path}")
    
    if not os.path.exists(db_path):
        print("Database not found!")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check columns
        cursor.execute("PRAGMA table_info(map_config)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'sort_order' in columns:
            print("Column 'sort_order' already exists in 'map_config'.")
        else:
            print("Adding 'sort_order' column to 'map_config'...")
            cursor.execute("ALTER TABLE map_config ADD COLUMN sort_order INTEGER DEFAULT 0")
            conn.commit()
            print("Successfully added 'sort_order' column.")
            
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    add_column()
