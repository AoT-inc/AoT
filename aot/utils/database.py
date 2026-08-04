# coding=utf-8
import logging
import time
from sqlite3 import OperationalError

import sqlalchemy

from aot.config import AOT_DB_PATH
from aot.databases.utils import session_scope

logger = logging.getLogger("aot.database")

_LOCK_PHRASES = ("database is locked", "unable to open database")
_IO_PHRASES = ("disk i/o error",)


def _is_lock_error(exc) -> bool:
    msg = str(exc).lower()
    return any(p in msg for p in _LOCK_PHRASES)


def _is_io_error(exc) -> bool:
    msg = str(exc).lower()
    return any(p in msg for p in _IO_PHRASES)


def db_retrieve_table(table, entry=None, unique_id=None):
    """
    Return SQL database query object with optional filtering
    Used in Flask (For daemon, see db_retrieve_table_daemon() below)

    If entry='first', only the first table entry is returned.
    If entry='all', all table entries are returned.
    If device_id is set, the first entry with that device ID is returned.
    Otherwise, the table object is returned.
    """
    if unique_id:
        return_table = table.query.filter(table.unique_id == unique_id)
    else:
        return_table = table.query

    if entry == 'first' or unique_id:
        return_table = return_table.first()
    elif entry == 'all':
        return_table = return_table.all()

    return return_table


def db_retrieve_table_daemon(
        table,
        entry=None,
        device_id=None,
        unique_id=None,
        custom_name=None,
        custom_value=None):
    """
    Return SQL database query object with optional filtering
    Used in daemon (For Flask, see db_retrieve_table() above)

    If entry='first', only the first table entry is returned.
    If entry='all', all table entries are returned.
    If device_id is set, the first entry with that device ID is returned.
    Otherwise, the table object is returned.

    **조회 실패 시(락 5회 재시도 초과, 디스크 I/O 에러) 예외 대신 "빈 결과"를
    돌려준다.** 그 빈 결과는 성공 시의 반환 타입과 맞춘다 — 단일 행을 기대한
    호출에는 None, 목록을 기대한 호출에는 []. 예전에는 어느 경우든 [] 였는데,
    단일 행을 기대한 호출부가 그 리스트에 속성 접근을 해서
    `'list' object has no attribute 'measurement_db_host'` 같은 엉뚱한
    AttributeError 로 터졌다(2026-08-04 안전 게이트 사건). 호출부는 여전히
    None 검사를 해야 하지만, 최소한 실패가 실패처럼 보인다.
    """
    tries = 5
    # 성공 시 .first() 를 타는 형태 = 단일 행 기대.
    _wants_single = bool(entry == 'first' or device_id or unique_id)
    _empty = None if _wants_single else []
    while tries > 0:
        try:
            with session_scope(AOT_DB_PATH) as new_session:
                if device_id:
                    return_table = new_session.query(table).filter(
                        table.id == int(device_id))
                elif unique_id:
                    return_table = new_session.query(table).filter(
                        table.unique_id == unique_id)
                elif custom_name and custom_value:
                    return_table = new_session.query(table).filter(
                        getattr(table, custom_name) == custom_value)
                else:
                    return_table = new_session.query(table)

                if entry == 'first' or device_id or unique_id:
                    return_table = return_table.first()
                elif entry == 'all':
                    return_table = return_table.all()

                new_session.expunge_all()
                new_session.close()
            return return_table
        except (OperationalError, sqlalchemy.exc.OperationalError) as exc:
            if _is_io_error(exc):
                logger.error(
                    "The AoT database returned a disk I/O error — "
                    "skipping retry: %s", exc)
                return _empty
            # lock/busy: retry with backoff
        except Exception:
            break

        if tries == 1:
            logger.error(
                "Could not read the AoT database after retries. "
                "Please submit a New Issue at "
                "https://github.com/AoT-inc/AoT/issues/new")
        else:
            logger.error(
                "The AoT database is locked. "
                "Trying to access again in 1 second...")

        time.sleep(1)
        tries -= 1

    return _empty
