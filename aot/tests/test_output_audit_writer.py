# coding=utf-8
"""감사 writer 스레드가 실제로 audit_log 행을 남기는지 검증.

게이트는 큐에 넣고 즉시 반환하므로(제어 경로의 8초 RPC 예산을 쓰지 않기 위해),
"기록됐다"를 보장하는 건 전적으로 이 백그라운드 writer 다. 여기가 조용히 죽으면
게이트는 멀쩡히 동작하는데 감사로그만 비어 있게 된다 — 정확히 이번 사건의 모습이다.

데몬에는 Flask 요청 문맥이 없으므로 `audit_log()` 의 자동 행위자 추출이 통하지
않는다. 출처에서 뽑아 명시적으로 넘긴 user_id/username 이 제대로 저장되는지도
여기서 함께 본다.

인메모리 sqlite 를 쓰지 않는 이유: writer 는 별도 스레드에서 커밋하는데
`sqlite:///:memory:` 는 연결마다 별개의 DB 라 스레드를 건너면 테이블이 안 보인다.
"""
import os
import queue
import time

import pytest

os.environ["ALEMBIC_RUNNING"] = "1"

from aot.config import ProdConfig
from aot.utils import output_audit


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    db_file = tmp_path / "audit_test.db"

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


@pytest.fixture(autouse=True)
def _fresh_queue():
    output_audit._q = queue.Queue(maxsize=output_audit._MAXSIZE)
    output_audit._dropped = 0
    yield
    output_audit.stop_writer(timeout=3)


def _wait_for_rows(app, expected, timeout=10.0):
    from aot.databases.models import AuditLog

    deadline = time.time() + timeout
    while time.time() < deadline:
        with app.app_context():
            rows = AuditLog.query.all()
            if len(rows) >= expected:
                return rows
        time.sleep(0.05)
    with app.app_context():
        return AuditLog.query.all()


def test_writer_persists_user_command(app):
    output_audit.start_writer(app)
    output_audit.record({
        'output_id': '84cda10a-b39b-4640-a50c-f1310457aa09',
        'output_name': '관수: 미니스프링클러',
        'channel': 0,
        'state': 'on',
        'output_type': 'sec',
        'amount': 0,
        'origin': {'type': 'user', 'id': 42, 'name': 'aot', 'ip': '10.0.0.9'},
        'ip_address': '10.0.0.9',
        'result': 'success',
    })

    rows = _wait_for_rows(app, 1)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == 'output.control'
    assert row.target_type == 'Output'
    assert row.target_id == '84cda10a-b39b-4640-a50c-f1310457aa09'
    assert row.target_name == '관수: 미니스프링클러'
    assert row.result == 'success'
    # 데몬에는 요청 문맥이 없다 — 출처에서 넘긴 값이 그대로 들어가야 한다
    assert row.user_id == 42
    assert row.username == 'aot'
    assert row.ip_address == '10.0.0.9'
    assert 'origin=user' in row.detail
    assert 'state=on' in row.detail


def test_writer_records_unknown_origin_without_user(app):
    """출처 불명 명령도 반드시 남는다. user_id 는 비고 origin=unknown 으로 표시된다."""
    output_audit.start_writer(app)
    output_audit.record({
        'output_id': 'out-1',
        'output_name': '밸브',
        'channel': 0,
        'state': 'on',
        'output_type': 'sec',
        'amount': 0,
        'origin': {'type': 'unknown', 'id': None, 'name': None},
        'ip_address': None,
        'result': 'success',
    })

    rows = _wait_for_rows(app, 1)
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert 'origin=unknown' in rows[0].detail


def test_writer_batches_many_entries(app):
    """배치 커밋 경로 — 한 번에 몰려도 유실 없이 전부 남아야 한다."""
    output_audit.start_writer(app)
    total = 120  # _BATCH(50)를 넘겨 여러 배치를 태운다
    for i in range(total):
        output_audit.record({
            'output_id': f'out-{i}',
            'output_name': f'장치{i}',
            'channel': 0,
            'state': 'on',
            'output_type': 'sec',
            'amount': 0,
            'origin': {'type': 'user', 'id': 1, 'name': 'aot'},
            'ip_address': None,
            'result': 'success',
        })

    rows = _wait_for_rows(app, total, timeout=20.0)
    assert len(rows) == total


def test_bad_origin_is_recorded_not_dropped(app):
    """dict 가 아닌 origin 이 와도 그 명령의 기록은 남아야 한다.

    실제로 이런 항목이 들어오는 경로가 있고(2026-08, 로컬 36건), 예전에는
    `_flush_one` 이 AttributeError 로 터져 항목이 통째로 버려졌다. 그러면
    "명령은 있었는데 기록이 없다" 가 되고, 읽는 쪽은 "명령이 없었다" 로
    잘못 읽는다 — 감사로그에서 가장 나쁜 실패다.
    """
    output_audit.start_writer(app)
    output_audit.record({
        'output_id': 'out-bad',
        'output_name': '이상한 출처',
        'channel': 0, 'state': 'on', 'output_type': 'sec', 'amount': 0,
        'origin': 'not-a-dict',
        'ip_address': None, 'result': 'success',
    })
    output_audit.record({
        'output_id': 'out-ok',
        'output_name': '정상',
        'channel': 0, 'state': 'on', 'output_type': 'sec', 'amount': 0,
        'origin': {'type': 'user', 'id': 1, 'name': 'aot'},
        'ip_address': None, 'result': 'success',
    })

    rows = _wait_for_rows(app, 2, timeout=10.0)
    assert sorted(r.target_id for r in rows) == ['out-bad', 'out-ok']
    bad = next(r for r in rows if r.target_id == 'out-bad')
    # 형태만 바꿔 남기되, 어떤 출처였는지는 detail 에 보인다.
    assert 'not-a-dict' in bad.detail


def test_one_bad_entry_does_not_lose_the_batch(app):
    """한 건이 터져도 나머지는 기록돼야 한다 — 감사 유실은 조용해서 위험하다."""
    output_audit.start_writer(app)
    # entry 자체가 dict 가 아니라 _flush_one 안에서 AttributeError 가 난다.
    output_audit.record('not-an-entry')
    output_audit.record({
        'output_id': 'out-ok',
        'output_name': '정상',
        'channel': 0, 'state': 'on', 'output_type': 'sec', 'amount': 0,
        'origin': {'type': 'user', 'id': 1, 'name': 'aot'},
        'ip_address': None, 'result': 'success',
    })

    rows = _wait_for_rows(app, 1, timeout=10.0)
    assert [r.target_id for r in rows] == ['out-ok']


def test_stop_writer_flushes_remaining_queue(app):
    """데몬 종료 시 큐에 남은 항목이 유실되면 안 된다.

    종료 경로가 각 장치에 Shutdown State 를 내보낸 직후라, 그 기록이 사라지면
    "종료가 장치를 껐다"는 사실이 통째로 없어진다 — 정확히 남기려고 만든 기능이다.
    """
    output_audit.start_writer(app)
    output_audit.stop_writer(timeout=3)  # writer 를 먼저 멈춘 뒤 적재한다

    output_audit.record({
        'output_id': 'out-shutdown',
        'output_name': '밸브',
        'channel': 0, 'state': 'off', 'output_type': 'state_shutdown',
        'amount': None,
        'origin': {'type': 'lifecycle', 'id': 'daemon_shutdown',
                   'name': 'daemon_shutdown'},
        'ip_address': None, 'result': 'success',
    })
    assert output_audit._q.qsize() == 1  # writer 는 멈춰 있다

    output_audit.stop_writer(timeout=3)  # 동기 flush 가 남은 걸 마저 쓴다

    from aot.databases.models import AuditLog
    with app.app_context():
        rows = AuditLog.query.all()
    assert [r.target_id for r in rows] == ['out-shutdown']
    assert 'origin=lifecycle' in rows[0].detail
    assert 'origin_id=daemon_shutdown' in rows[0].detail


# ------------------------------------------------- Flask 요청에서의 출처 판정

def test_origin_picks_up_logged_in_user_from_request_context(app, monkeypatch):
    """라우트를 하나도 안 고쳐도 로그인 사용자가 자동으로 잡혀야 한다.

    이 설계의 핵심 이득이다 — 출처를 라우트마다 심으면 새 라우트가 생길 때마다
    또 빠진다. 요청 문맥에서 자동으로 뽑으면 Flask 를 통과하는 모든 경로가 덮인다.
    """
    from aot.utils.command_origin import resolve_origin

    class _User:
        is_authenticated = True
        id = 42
        name = 'aot'

    with app.test_request_context('/output_mod/x/0/on/sec/0',
                                  environ_base={'REMOTE_ADDR': '10.0.0.9'}):
        import flask_login
        # flask_login.current_user 는 요청 문맥에 묶인 LocalProxy 다.
        # monkeypatch 로 갈아끼워야 다른 테스트로 새지 않는다.
        monkeypatch.setattr(flask_login.utils, '_get_user', lambda: _User())
        origin = resolve_origin()

    assert origin['type'] == 'user'
    assert origin['id'] == 42
    assert origin['name'] == 'aot'
    assert origin['ip'] == '10.0.0.9'


def test_origin_is_unknown_when_request_has_no_authenticated_user(app, monkeypatch):
    """요청은 있는데 인증이 없다 — 정상 경로면 안 나오는 조합이라 unknown 으로 남긴다."""
    from aot.utils.command_origin import resolve_origin

    class _Anon:
        is_authenticated = False

    with app.test_request_context('/output_mod/x/0/on/sec/0',
                                  environ_base={'REMOTE_ADDR': '10.0.0.9'}):
        import flask_login
        monkeypatch.setattr(flask_login.utils, '_get_user', lambda: _Anon())
        origin = resolve_origin()

    assert origin['type'] == 'unknown'
    assert origin['ip'] == '10.0.0.9'


# --------------------------------------------------- Pyro5 직렬화 (RPC 경계)

def test_origin_dict_survives_pyro5_serialization():
    """origin 은 RPC 인자로 건너간다 — 직렬화가 안 되면 제어 자체가 깨진다.

    Pyro5 기본 직렬화기(serpent)는 임의 객체를 못 넘긴다. origin 을 원시값만 담은
    평평한 dict 로 유지해야 하는 이유이고, 그 계약을 여기서 못박는다.
    """
    import serpent

    origin = {'type': 'user', 'id': 42, 'name': 'aot', 'ip': '10.0.0.9'}
    restored = serpent.loads(serpent.dumps(origin))
    assert restored == origin

    for variant in ({'type': 'automation', 'id': None, 'name': None},
                    {'type': 'trigger', 'id': 'trg-1', 'name': None},
                    {}):
        assert serpent.loads(serpent.dumps(variant)) == variant
