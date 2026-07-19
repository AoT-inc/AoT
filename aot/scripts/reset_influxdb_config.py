"""Reset InfluxDB connection settings in the Misc table to factory defaults."""
import sys
import os
import logging

# Ensure we can import aot modules
# Assuming this script is run from AoT/aot/scripts/ or similar
current_dir = os.path.dirname(os.path.abspath(__file__))
aot_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(aot_root)

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.databases.models import Misc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reset_influxdb_config")

def reset_influx_config():
    """Reset InfluxDB host, port, credentials, and version to defaults.

    @phase maintenance
    @dependency aot.aot_flask.app, aot.databases.models
    """
    app = create_app()
    with app.app_context():
        try:
            misc_settings = Misc.query.first()
            if not misc_settings:
                logger.error("Misc settings table not found!")
                return False

            logger.info("Resetting InfluxDB configuration to defaults...")
            
            # Default values matching upgrade_commands.sh and misc.py defaults
            # Corresponds to: --username aot --password mmdu77sj3nIoiajjs --token mmdu77sj3nIoiajjs
            misc_settings.measurement_db_user = 'aot'
            misc_settings.measurement_db_password = 'mmdu77sj3nIoiajjs' # Used as token for InfluxDB 2.x
            misc_settings.measurement_db_db_name = 'aot_db'
            misc_settings.measurement_db_host = 'localhost'
            misc_settings.measurement_db_port = '8086'
            
            # Ensure DB version is set to 2 if we are resetting for InfluxDB 2.x
            # NOTE: upgrade_commands.sh 'update-influxdb-2-db-user' implies v2
            # But let's be careful not to override if it was v1 unless explicitly desired.
            # Given this is called from 'update-influxdb-2-db-user', we should probably set it to '2'.
            misc_settings.measurement_db_version = '2' 
            misc_settings.measurement_db_name = 'influxdb'
            
            db.session.commit()
            logger.info("InfluxDB configuration reset successfully.")
            return True
        except Exception as e:
            logger.exception(f"Failed to reset InfluxDB config: {e}")
            return False

if __name__ == "__main__":
    success = reset_influx_config()
    sys.exit(0 if success else 1)
