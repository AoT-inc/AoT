"""Create the IrrigationDesign table and verify it exists."""
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.databases.models.irrigation import IrrigationDesign

def create_table():
    """Create all database tables including irrigation_design.

    @phase setup
    @dependency aot.aot_flask.app, aot.databases.models.irrigation
    """
    app = create_app()
    with app.app_context():
        print("Creating all tables (including irrigation_design)...")
        db.create_all()
        print("Done.")
        
        # Verify
        try:
            count = IrrigationDesign.query.count()
            print(f"Verification: Successfully queried IrrigationDesign table. Count: {count}")
        except Exception as e:
            print(f"Error verification failed: {e}")

if __name__ == "__main__":
    create_table()
