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

import pytest  # noqa: E402


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


@pytest.fixture(scope='session')
def test_db_path():
    """이 세션이 쓰는 임시 DB 경로 — 격리가 깨졌는지 확인할 때 쓴다."""
    from aot.config import SQL_DATABASE_AOT
    return SQL_DATABASE_AOT
