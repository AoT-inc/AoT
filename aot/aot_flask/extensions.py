# coding=utf-8
"""
The Flask extensions module contains extensions like Flask SQLAlchemy
which requires a flask context in order to operate.

These extensions are instantiated here and imported into the modules
that require them.  The extensions themselves are configured at run
time when the application factory in aot_flask initializes them
and adds it's configuration to them.
"""
from flask_wtf.csrf import CSRFProtect
from flask_caching import Cache

# db·ma 의 정본은 aot.databases.sqla (아키텍처 4a) — 같은 객체를 다시 내보낸다.
from aot.databases.sqla import db, ma  # noqa: E402,F401

csrf = CSRFProtect()
cache = Cache(config={
    'CACHE_TYPE': 'FileSystemCache',  # Shared across gunicorn workers
    'CACHE_DIR': '/tmp/aot_flask_cache',
    'CACHE_DEFAULT_TIMEOUT': 300
})
