# coding=utf-8
"""라이브 DB 에서 테스트가 돌지 못하게 막는 가드.

테스트 픽스처 여럿이 "내가 만든 행만" 이 아니라 **테이블 전체**를 지운다
(`MCPAuditLog.query.delete()` 류). 그 픽스처가 `create_app()` 이 고른 DB 에서
돌면 그것이 곧 라이브 DB 다 — 2026-10-10 로컬 앱 컨테이너(`/app/aot_local/
databases/aot.db`)에서 `AOT_LOCAL_DIR` 없이 테스트를 돌려 `mcp_audit_log`·
`mcp_confirmation` 이 전부 사라졌다. SQLite `secure_delete` 가 켜져 있어 복구가
안 됐다.

pytest 는 `conftest.py` 가 `AOT_LOCAL_DIR` 을 임시 디렉터리로 돌려놓으므로
안전하다. 위험한 것은 conftest 를 거치지 않는 실행(`python -m unittest`,
`python aot/tests/x.py`, 컨테이너 안의 직접 실행)이다.

사용: 테이블을 지우거나 라이브 상태를 바꾸는 픽스처의 `setUpClass` 맨 앞에서

    from aot.tests._live_db_guard import refuse_live_db
    refuse_live_db()

테스트용 복사본으로 돌리는 법:

    python3 - <<'PY'
    import sqlite3, os
    os.makedirs('/tmp/aotlocal/databases', exist_ok=True)
    src = sqlite3.connect('file:/app/aot_local/databases/aot.db?mode=ro', uri=True)
    dst = sqlite3.connect('/tmp/aotlocal/databases/aot.db')
    src.backup(dst)
    PY
    AOT_LOCAL_DIR=/tmp/aotlocal python -m unittest aot.tests.test_mcp_tool_profiles

(`cp` 는 WAL 을 놓친다 — 반드시 backup API.)
"""
import os

ALLOW_ENV = 'AOT_TESTS_ALLOW_LIVE_DB'

# 컨테이너 기본 경로 — docker-compose 가 AOT_LOCAL_DIR=/app/aot_local 로 준다.
_CONTAINER_LIVE = '/app/aot_local/databases/aot.db'


def _sqlite_file(uri):
    """`sqlite:///경로` → 경로. sqlite 가 아니면 None(인메모리 포함)."""
    if not uri or not uri.startswith('sqlite:///'):
        return None
    path = uri[len('sqlite:///'):]
    return None if path in ('', ':memory:') else path


def live_db_paths():
    """이 설치에서 라이브로 간주하는 DB 파일들(realpath)."""
    from aot import config
    paths = {_CONTAINER_LIVE,
             os.path.join(config.PROJECT_DATABASE_PATH, config.DATABASE_NAME)}
    return {os.path.realpath(p) for p in paths}


def resolved_db_files():
    """지금 프로세스의 `aot.config` 가 가리키는 DB 파일들(realpath)."""
    from aot import config
    files = {config.SQL_DATABASE_AOT, _sqlite_file(config.AOT_DB_PATH)}
    return {os.path.realpath(p) for p in files if p}


def refuse_live_db():
    """설정된 DB 가 라이브 경로이면 RuntimeError. 명시 허용 변수가 있으면 통과."""
    if os.environ.get(ALLOW_ENV) == '1':
        return
    hit = resolved_db_files() & live_db_paths()
    if not hit:
        return
    raise RuntimeError(
        '이 테스트는 테이블을 비우거나 라이브 상태를 바꾼다. 지금 DB 가 라이브 '
        'DB(%s)를 가리키고 있어 실행을 거부한다.\n'
        'AOT_LOCAL_DIR 을 DB 복사본 디렉터리로 지정해 다시 실행할 것 '
        '(복사본은 sqlite3 backup API 로 만든다 — `cp` 는 WAL 을 놓친다. '
        '예: AOT_LOCAL_DIR=/tmp/aotlocal, 안에 databases/aot.db). '
        'pytest 는 conftest 가 임시 디렉터리를 지정하므로 해당 없다. '
        '라이브 DB 에서 정말 돌려야 하면 %s=1 (권장하지 않음).'
        % (', '.join(sorted(hit)), ALLOW_ENV))
