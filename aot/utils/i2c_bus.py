# coding=utf-8
import logging
import threading

logger = logging.getLogger("aot.utils.i2c_bus")

class GlobalI2CBusLock:
    """
    A singleton class providing a global lock for I2C bus access.
    This prevents multiple threads from accessing the I2C bus simultaneously,
    reducing risk of bus lockups and data corruption.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(GlobalI2CBusLock, cls).__new__(cls)
                    cls._instance.bus_locks = {}
        return cls._instance

    def get_lock(self, bus_number):
        """Returns a threading.Lock for a specific I2C bus."""
        with self._lock:
            if bus_number not in self.bus_locks:
                self.bus_locks[bus_number] = threading.Lock()
            return self.bus_locks[bus_number]

# Global instance for easy import
i2c_lock_manager = GlobalI2CBusLock()
