# coding=utf-8
"""
Database connection utilities for AoT — engine caching and session scoping.

This module is NOT indexed. Keep it for human readers only.
"""
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# Global cache for database engines
ENGINES = {}
# Shared sessionmaker per engine URI (avoids recreating on every session_scope call)
SESSION_FACTORIES = {}


def get_engine(db_uri):
    """Return a cached SQLAlchemy Engine for the given URI, creating one if needed.

    Uses NullPool for SQLite — pooling provides no benefit for a local file DB and
    causes QueuePool exhaustion under high daemon thread concurrency.

    SQLite busy_timeout=10 000 ms: lets SQLite retry internally for up to 10 s
    before raising OperationalError, eliminating most transient lock collisions
    without application-level retry loops.

    @phase active
    @dependency sqlalchemy
    """
    if db_uri not in ENGINES:
        ENGINES[db_uri] = create_engine(
            f"{db_uri}?check_same_thread=False",
            poolclass=NullPool,
            connect_args={"timeout": 10},
        )
    return ENGINES[db_uri]


def _get_session_factory(db_uri):
    if db_uri not in SESSION_FACTORIES:
        SESSION_FACTORIES[db_uri] = sessionmaker(bind=get_engine(db_uri))
    return SESSION_FACTORIES[db_uri]


def reset_engine_cache():
    """Dispose all cached engines and clear caches (call after config changes)."""
    for engine in ENGINES.values():
        try:
            engine.dispose()
        except Exception:
            pass
    ENGINES.clear()
    SESSION_FACTORIES.clear()


@contextmanager
def session_scope(db_uri):
    """Provide a transactional scope around a series of database operations.

    Creates a Session bound to a cached engine, yields it for use in a with block,
    and automatically commits on success or rolls back on exception.
    The session is always closed in the finally block.

    @phase active
    @dependency get_engine
    """
    session = _get_session_factory(db_uri)()
    try:
        yield session
        session.commit()
    except Exception as e:
        import sqlalchemy.exc as _sa_exc
        import sqlite3 as _sqlite3
        _is_operational = isinstance(e, (_sa_exc.OperationalError, _sqlite3.OperationalError))
        if _is_operational:
            logger.error("Error raised in session_scope.  Session will be rolled back: "
                         "db_uri='{uri}', error='{err}'".format(uri=db_uri, err=e))
        else:
            logger.exception("Error raised in session_scope.  Session will be rolled back: "
                             "db_uri='{uri}', error='{err}'".format(uri=db_uri, err=e))
        session.rollback()
        raise
    finally:
        session.close()
