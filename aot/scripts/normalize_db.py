# coding=utf-8
import os
import sys
import logging

# Add current directory to path so we can import aot modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.config import SQL_DATABASE_AOT
from aot.databases.utils import session_scope
from aot.databases.models.output import Output

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("normalize_db")

def normalize_52pi_relay_i2c():
    """
    Sets i2c_bus = 1 for the 52pi_4channel_Relay output device.
    This resolves a daemon crash issue due to missing I2C bus number.
    """
    if not os.path.exists(SQL_DATABASE_AOT):
        logger.warning(f"Database not found at {SQL_DATABASE_AOT}. Skipping normalization.")
        return

    try:
        with session_scope(f'sqlite:///{SQL_DATABASE_AOT}') as session:
            # Find the output with the unique name '52pi_4channel_Relay'
            target_relay = session.query(Output).filter(Output.output_type == '52pi_4channel_Relay').all()
            
            if not target_relay:
                logger.info("No 52pi_4channel_Relay found in database.")
                return

            updated_count = 0
            for relay in target_relay:
                if relay.i2c_bus != 1:
                    relay.i2c_bus = 1
                    updated_count += 1
            
            if updated_count > 0:
                session.commit()
                logger.info(f"Successfully updated i2c_bus to 1 for {updated_count} 52pi_4channel_Relay device(s).")
            else:
                logger.info("All 52pi_4channel_Relay devices already have i2c_bus = 1.")

    except Exception as e:
        logger.error(f"Error during database normalization: {e}")

if __name__ == "__main__":
    normalize_52pi_relay_i2c()
