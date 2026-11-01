# coding=utf-8
"""테스트 전역 설정 — 테스트를 레포의 실제 sqlite 파일에서 떼어낸다.

문제: `AOT_DB_PATH` 는 `aot/config/__init__.py` 가 **import 되는 시점에**
확정되는 전역 상수이고, `AOT_LOCAL_DIR` 이 없으면 레포 안의
`aot/databases/aot.db` 를 가리킨다. 그런데 데몬 계열 코드
(`db_retrieve_table_daemon` → `session_scope(AOT_DB_PATH)`)는 Flask 의
TestConfig(인메모리)를 거치지 않고 그 경로를 직접 연다. 그래서 순수 단위
테스트조차 개발자의 실제 DB 파일을 열었다.

두 가지가 따라왔다.

1. **테스트가 그 파일을 수정한다.** 읽기만 하는 테스트를 돌려도 WAL 이
   본 DB 로 체크포인트되며 md5 가 바뀐다(2026-08-04 실측).
2. **스키마가 앞서가면 무관한 테스트가 무더기로 깨진다.** 레포 DB 는
   `p5_46`(2026-07-20 리베이스라인 이전)에 멈춰 있고 코드는 `p6_24` 라,
   `no such column: misc.google_oauth_client_id` / `roles.position_y` 류로
   safety_gates·mcp_task24 같은 무관한 테스트가 죽었다.

해결: 세션마다 임시 디렉터리를 만들어 `AOT_LOCAL_DIR` 로 지정하고, 거기에
**모델에서 직접** 스키마를 만든다. 마이그레이션 체인이 아니라 모델을 쓰므로
스키마는 정의상 항상 코드와 일치한다. 레포 DB 는 열리지도 않는다.

이 모듈은 conftest 라 pytest 가 어떤 테스트보다 먼저 로드한다 — 환경변수
설정이 `aot.config` import 보다 앞서야 의미가 있으므로 그 순서가 중요하다.
"""
import os
import tempfile

# ---------------------------------------------------------------------------
# aot.config 를 import 하기 전에 환경을 잡는다. (아래 import 들보다 위여야 한다)
# ---------------------------------------------------------------------------
_TEST_DIR = tempfile.mkdtemp(prefix='aot-test-')
os.environ['AOT_LOCAL_DIR'] = _TEST_DIR
# 테스트 수집 중 alembic 자동 마이그레이션이 도는 것을 막는다.
os.environ.setdefault('ALEMBIC_RUNNING', '1')

# 예보 계열의 L0(Influx) 읽기를 기본으로 끈다 — Influx 가 없는 시험이 연결을 기다리지 않게.
# (import 부작용을 피하려고 환경변수로 끈다. L0 를 시험하는 곳은 forecast_series.L0_READ 를 monkeypatch 로 켠다.)
os.environ.setdefault('AOT_FC_L0_READ', '0')

import pytest  # noqa: E402

# aot.tools 는 aot.ai 를 직접 import 하지 않는다(tools-no-ai 가드) — 필요한 것은
# aot/tools/providers.py 의 콜백으로 받고, 그 등록은 aot.ai 가 import 될 때
# aot/ai/services/tool_providers.py::bind_all() 이 한다. 실제 앱 진입점은 모두
# (직접이든 간접이든) aot.ai 를 import 하므로 항상 바인딩되어 있지만, aot.tools
# 만 단독으로 import 하는 테스트는 그 경로를 안 타므로 여기서 명시적으로
# 바인딩해 둔다.
import aot.ai  # noqa: E402,F401

# 테스트 DB 는 어차피 버리므로 SQLite 의 fsync 를 끈다. 많은 테스트가 setUp 마다 파일 DB 에 스키마를
# 만들고 지우는데 DDL 은 문장마다 커밋이라, fsync 가 느린 나스 러너(커밋당 15ms, 맥 1ms)에서는 이것이
# 단위 스위트 시간의 대부분이었다. 2026-11-01 실측: 31분 → 10분. SQLAlchemy 를 거치는 연결에만 적용된다.
import sqlite3  # noqa: E402

from sqlalchemy import event  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402


@event.listens_for(Engine, 'connect')
def _sqlite_skip_fsync(dbapi_conn, _record):
    if isinstance(dbapi_conn, sqlite3.Connection):
        dbapi_conn.execute('PRAGMA synchronous=OFF')


# 비밀번호 해시 비용을 테스트에서만 낮춘다. `User.set_password` 는 bcrypt 기본 비용(12)을 쓰는데
# 한 번에 0.24초(맥)~2초 안팎(나스)이고, 사용자를 만드는 테스트가 수백 건이라 단위 스위트 시간의
# 상당 부분이 해시 계산이었다. 비용 4 는 1ms 다. 검증(`hashpw(입력, 저장된 해시)`)은 저장된 해시의
# 비용을 따라가므로 코드 쪽은 그대로 두고 소금(salt)만 싸게 만든다 — 운영 코드는 건드리지 않는다.
import bcrypt as _bcrypt  # noqa: E402

_real_gensalt = _bcrypt.gensalt


def _cheap_gensalt(rounds=12, prefix=b'2b'):
    return _real_gensalt(rounds=4, prefix=prefix)


_bcrypt.gensalt = _cheap_gensalt


def pytest_configure(config):
    """임시 DB 에 현재 모델 기준 스키마를 만들어 둔다.

    빈 파일로 두면 `db_retrieve_table_daemon()` 이 조회 실패 → 5회 재시도(각 1초)
    → `[]` 반환 경로를 타서, 테스트가 통과하더라도 파일 하나당 수십 초가 낭비된다.
    """
    from flask import Flask

    from aot.config import AOT_DB_PATH
    from aot.aot_flask.extensions import db
    import aot.databases.models  # noqa: F401  — 모델 등록

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = AOT_DB_PATH
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
    config._aot_test_db = AOT_DB_PATH


# `'aot'` 로거 격리 픽스처(`_isolate_aot_logger`)는 한 단계 위 `aot/conftest.py`
# 로 옮겼다 — 여기 두면 `aot/functions/**/tests` 같은 다른 테스트 디렉터리에는
# 적용되지 않는다.


@pytest.fixture(scope='session')
def test_db_path():
    """이 세션이 쓰는 임시 DB 경로 — 격리가 깨졌는지 확인할 때 쓴다."""
    from aot.config import SQL_DATABASE_AOT
    return SQL_DATABASE_AOT


@pytest.fixture
def timer_sessions(tmp_path, monkeypatch):
    """타이머 위젯의 상태 파일 디렉터리를 테스트마다 따로 쓰고, 남은 워커를 멈춘다.

    ## 왜 필요한가

    `AoT_timer._SESS_DIR` 은 고정 경로(`/tmp/aot_timer_sessions`)다. 거기에는
    두 가지가 얽혀 있다.

    1. `recover_scheduled_workers()` 는 **그 디렉터리의 모든 상태 파일**을 훑어
       "주인을 잃은 실행" 을 되살린다. 그래서 다른 테스트가 같은 디렉터리에
       남겨 둔(또는 지금 쓰고 있는) 상태 파일이 복구 대상으로 줍혀 올라온다.
    2. 테스트가 띄운 워커 스레드는 테스트가 끝난 뒤에도 돈다. 정리 코드가 상태
       파일을 지운 *뒤에* 스레드가 다시 써서 파일이 되살아나기도 한다.

    pytest-xdist 에서는 같은 디렉터리를 **프로세스끼리도** 공유하므로 순서와
    무관하게 터진다. 2026-10-09 나스 Gitea 실행 332:
    `test_timer_start_at_persistence::test_recovery_passes_the_persisted_start_at_through`
    가 자기 장치(`dev-startat-recovery`)가 아니라
    `test_timer_off_confirm_and_origin` 의 `dev-off-cross-process` 상태를
    복구하다 `'00:00' == '22:10'` 로 실패했다(재실행하면 통과, 단독으로도 통과).

    ## 하는 일

    - `_SESS_DIR` 을 테스트 전용 임시 디렉터리로 돌린다 → 다른 테스트·프로세스의
      파일이 보이지 않는다.
    - 테스트가 끝나면 이 테스트가 새로 띄운 `_cyc_worker` 스레드를 멈추고
      기다린다. 디렉터리가 원래대로 돌아오기 *전에* 해야 늦게 깬 스레드가 진짜
      `/tmp` 에 쓰지 못한다.
    """
    import threading

    import aot.widgets.AoT_timer as timer

    sess_dir = tmp_path / 'aot_timer_sessions'
    sess_dir.mkdir()
    monkeypatch.setattr(timer, '_SESS_DIR', str(sess_dir))

    before = set(threading.enumerate())
    yield str(sess_dir)

    # `_cyc_start_worker` 가 만든 스레드는 target=_cyc_worker 이고 stop_event 가
    # 위치 인자의 마지막이다(resume 은 kwargs). 레지스트리는 테스트의 정리
    # 코드가 이미 비웠을 수 있어 거기서 찾지 않고 스레드를 직접 센다.
    workers = [
        th for th in threading.enumerate()
        if th not in before and getattr(th, '_target', None) is timer._cyc_worker]
    for th in workers:
        th._args[-1].set()
    for th in workers:
        th.join(timeout=10.0)
    with timer._CYCLE_LOCK:
        timer._CYCLE_WORKERS.clear()
    stuck = [th for th in workers if th.is_alive()]
    assert not stuck, f'타이머 워커 스레드가 멈추지 않았다: {stuck}'
