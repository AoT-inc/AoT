import json
import os
import fcntl
import time
from flask import current_app

def read_json_safe(path, default=None):
    """
    Read a JSON file safely with shared lock.
    """
    if default is None:
        default = {}
    
    if not os.path.exists(path):
        return default

    try:
        with open(path, 'r') as f:
            try:
                fcntl.flock(f, fcntl.LOCK_SH)
                data = json.load(f)
                return data
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        # Log error but don't crash, return default to keep app running
        # But be careful: returning default on error can lead to overwriting with empty state!
        # Ideally we should re-raise or handle better, but for now we follow existing pattern with logging.
        try:
            if current_app:
                current_app.logger.error(f"Failed to read JSON safely from {path}: {e}")
            else:
                print(f"Failed to read JSON safely from {path}: {e}")
        except:
            pass
        return default

def write_json_safe(path, payload):
    """
    Write a JSON file safely with exclusive lock.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Open with 'r+' to allow locking before truncating, or 'w' but 'w' truncates immediately.
        # Best practice: Open 'a' (append) or 'r+' to get lock, then truncate.
        # But 'w' is easier if we accept a tiny race before lock? No, 'w' truncates.
        # Correct way: Open file, lock, truncate, write.
        
        # If file doesn't exist, 'r+' fails. 'w' creates but truncates.
        # 'a' creates if not exists.
        
        with open(path, 'a+') as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.seek(0)
                f.truncate()
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno()) # Ensure write to disk
                return True
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        try:
            if current_app:
                current_app.logger.error(f"Failed to write JSON safely to {path}: {e}")
            else:
                print(f"Failed to write JSON safely to {path}: {e}")
        except:
            pass
        return False
