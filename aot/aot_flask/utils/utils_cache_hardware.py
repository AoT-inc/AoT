# coding=utf-8
import logging
import subprocess
import re
import os
from functools import lru_cache
from flask import current_app
from aot.utils.system_pi import dpkg_package_exists

logger = logging.getLogger('aot.aot_flask.utils.cache_hardware')

@lru_cache(maxsize=1)
def get_cached_1wire_devices():
    """
    Cached version of 1-wire device detection using owdir.
    TTL is effectively infinite for the process lifetime, 
    assuming plugged devices don't change frequently during runtime.
    If they do, we might need a TTL mechanism, but process restart is common for hardware changes.
    """
    devices_1wire_ow_shell = []
    
    # We can't access current_app inside the cache function easily if it's called outside request context,
    # but here it's likely fine. However, safely check config.
    try:
        testing = current_app.config.get('TESTING', False)
    except:
        testing = False

    if testing:
        return []

    if not dpkg_package_exists('ow-shell'):
        return []

    try:
        test_cmd = subprocess.check_output(['owdir']).splitlines()
        for each_ow in test_cmd:
            str_ow = re.sub("\ |\/|\'", "", each_ow.decode("utf-8"))  # Strip / and '
            if '.' in str_ow and len(str_ow) == 15:
                devices_1wire_ow_shell.append(str_ow)
    except Exception as e:
        logger.error(f"Error finding 1-wire devices with 'owdir': {e}")
        
    return devices_1wire_ow_shell

@lru_cache(maxsize=1)
def get_cached_ftdi_devices():
    """
    Cached version of FTDI device list.
    """
    try:
        testing = current_app.config.get('TESTING', False)
    except:
        testing = False

    if testing:
        return []

    try:
        from aot.devices.atlas_scientific_ftdi import get_ftdi_device_list
        return get_ftdi_device_list()
    except Exception as e:
        logger.error(f"Error fetching FTDI devices: {e}")
        return []
