# -*- coding: utf-8 -*-
#
# gunicorn_conf.py - Environment-adaptive gunicorn settings for aotflask.
#
# Thread count priority:
#   1. GUNICORN_THREADS environment variable
#   2. Manual setting in the settings DB (misc.gunicorn_threads, NULL = auto)
#   3. Automatic recommendation from the detected environment
#      (cores, memory, Raspberry Pi / Docker limits)
#
# Resolution never raises — any failure falls back to the automatic value,
# so service startup cannot be blocked here.
#
# workers stays 1: flask-caching and the OpenMeteo failure cooldown are
# process-memory based; multiple workers would split those caches.
#
import os
import sys

_INSTALL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _INSTALL_DIR not in sys.path:
    sys.path.insert(0, _INSTALL_DIR)

from aot.utils.system_environment import detect, resolve_gunicorn_threads

# Mirrors aot.config DB path resolution without importing the full config
# (which pulls flask_babel and the rest of the app at master startup).
# Must NOT require 'databases' to already exist under AOT_LOCAL_DIR -- see
# the matching comment in aot/config/__init__.py.
_local_dir = os.environ.get('AOT_LOCAL_DIR')
if _local_dir:
    _db_path = os.path.join(_local_dir, 'databases', 'aot.db')
else:
    _db_path = os.path.join(_INSTALL_DIR, 'aot', 'databases', 'aot.db')

_env = detect()
_threads, _source = resolve_gunicorn_threads(database_path=_db_path)

workers = 1
worker_class = 'gthread'
threads = _threads
timeout = 300

print(
    f"[gunicorn_conf] platform={_env['platform_type']} "
    f"cores={_env['cpu_cores']} mem={_env['mem_total_gb']}GB "
    f"-> threads={threads} (source={_source})",
    flush=True)
