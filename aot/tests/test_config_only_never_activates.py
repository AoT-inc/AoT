# coding=utf-8
"""config_only 도구는 무엇도 활성화하지 않는다 — 계약의 **행위** 검사.

`tool_registry.py` 의 config_only 계약은 세 조건 위에 서 있다:

    1. 이 도구만으로는 어떤 장비도 움직이지 않는다.
    2. 편집 결과가 실제로 도는 시점은 activate_function 을 지나야 하고,
       그 활성화는 계속 승인 대상이다.
    3. 되돌릴 수 있다.

`test_tool_registry_ssot.py` 는 이 계약을 **선언 수준**에서만 지킨다 —
config_only 가 붙은 도구가 여전히 `mutating=True` 인지 볼 뿐, 그 도구가
런타임에 무슨 짓을 하는지는 모른다. 그래서 2026-08-07 까지
`modify_function_options` 가 계약을 깬 채로 통과하고 있었다: 편집 후
"데몬 리로드"를 하겠다고 `controller_deactivate()` → `controller_activate()`
를 **무조건** 불렀는데, `controller_activate()` 는 리로드 프리미티브가 아니라
`is_activated = True` 를 DB 에 쓰고 컨트롤러 스레드를 시작하는 함수다
(`aot_daemon.py`). 즉 비활성 함수의 옵션을 고치면 그 함수가 켜졌고,
config_only 라 승인은 없었다. 승인 없이 생성 → 승인 없이 옵션 편집 →
실제 장치 제어 가동이 성립했다.

선언이 맞아도 동작이 계약을 깰 수 있다. 그래서 이 파일은 도구를 실제로
실행시켜 놓고 `is_activated` 와 데몬 호출을 본다.

**config_only 도구를 추가하면 이 파일에 케이스도 같이 추가할 것.**
`test_every_config_only_tool_has_a_case()` 가 빠뜨림을 잡는다.
"""
import pytest

from aot.config import ProdConfig


# 리로드용으로 허용되는 데몬 호출 — 이것들은 활성 상태를 바꾸지 않는다.
# controller_activate 는 여기 절대 들어올 수 없다.
ALLOWED_DAEMON_CALLS = {'refresh_daemon_trigger_settings',
                        'refresh_daemon_misc_settings'}


class _DaemonRecorder:
    """DaemonControl 대역 — 부른 이름을 기록하고 성공을 흉내낸다.

    실 데몬에 붙지 않는 것 자체가 목적이다. 테스트가 우연히 살아 있는 데몬을
    깨워 진짜 컨트롤러를 켜면 그 순간 이 테스트는 검사가 아니라 사고다.

    다만 `controller_activate` 는 실물처럼 **DB 의 is_activated 도 켠다**
    (`aot_daemon.py` 가 그렇게 한다). 그러지 않으면 "함수가 켜지지 않았다"는
    단언이 공허해진다 — 대역이 아무것도 안 하니 어떤 코드를 넣어도 통과한다.
    """

    def __init__(self):
        self.calls = []

    def controller_activate(self, controller_id):
        self.calls.append('controller_activate')
        self._set_activation(controller_id, True)
        return 0, 'ok'

    def controller_deactivate(self, controller_id):
        self.calls.append('controller_deactivate')
        self._set_activation(controller_id, False)
        return 0, 'ok'

    @staticmethod
    def _set_activation(controller_id, value):
        from aot.aot_flask.extensions import db
        from aot.databases.models.controller import CustomController
        from aot.databases.models.function import Conditional, Trigger
        from aot.databases.models.pid import PID

        for Model in (CustomController, Conditional, PID, Trigger):
            row = Model.query.filter(Model.unique_id == controller_id).first()
            if row is not None:
                row.is_activated = value
                db.session.commit()
                return

    def __getattr__(self, name):
        """리로드류 등 나머지 호출은 이름만 기록한다."""
        def _record(*args, **kwargs):
            self.calls.append(name)
            return 0, 'ok'
        return _record

    @property
    def names(self):
        return list(self.calls)


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    db_file = tmp_path / "config_only.db"

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


@pytest.fixture
def daemon(monkeypatch):
    """도구들이 함수 본문에서 `from aot.aot_client import DaemonControl` 하므로
    원본 모듈의 이름을 갈아끼워야 한다."""
    import aot.aot_client as aot_client

    rec = _DaemonRecorder()
    monkeypatch.setattr(aot_client, 'DaemonControl', lambda *a, **kw: rec)
    return rec


def _make_outputs(count=2):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Output

    ids = []
    for i in range(count):
        oid = set_uuid()
        out = Output(unique_id=oid)
        out.name = f"valve-{i}"
        db.session.add(out)
        ids.append(oid)
    db.session.commit()
    return ids


def _make_sequence(device_count=2):
    """create_sequence_function 으로 비활성 시퀀스 하나를 세운다.

    픽스처를 손으로 만들지 않고 도구를 쓰는 이유: 그 도구도 config_only 라
    여기서 함께 검사 대상이 된다.
    """
    from aot.ai.services.aot_data_tool_service import AoTDataToolService

    res = AoTDataToolService.create_sequence_function(
        name='seq-under-test', device_ids=_make_outputs(device_count),
        state='on', step_duration=60)
    assert not res.get('error'), res
    return res


def _trigger(function_id):
    from aot.databases.models.function import Trigger
    return Trigger.query.filter(Trigger.unique_id == function_id).first()


# ---------------------------------------------------------------------------
# 계약 검사 — 도구별
# ---------------------------------------------------------------------------

def test_create_sequence_function_creates_deactivated(app, daemon):
    with app.test_request_context():
        res = _make_sequence()
        trig = _trigger(res['function_id'])

        assert res['activated'] is False, res
        assert not trig.is_activated, "생성 도구가 시퀀스를 켰다"
        assert res['step_count'] == 2, res          # 빈 껍데기가 아니어야 한다
        assert 'controller_activate' not in daemon.names, daemon.names


def test_modify_function_options_does_not_activate(app, daemon):
    """비활성 함수의 옵션을 고쳐도 켜지지 않는다 (2026-08-07 회귀)."""
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models.function import Conditional
    from aot.ai.services.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        uid = set_uuid()
        cond = Conditional(unique_id=uid)
        cond.name = 'cond-under-test'
        cond.is_activated = False
        db.session.add(cond)
        db.session.commit()

        res = AoTDataToolService.modify_function_options(uid, {'period': 42})
        row = Conditional.query.filter(Conditional.unique_id == uid).first()

        assert res.get('status') == 'modified', res      # 편집 자체는 되어야 한다
        assert '42' in (row.custom_options or ''), row.custom_options
        assert not row.is_activated, "옵션 편집이 함수를 켰다"
        assert res.get('activated') is False, res
        assert 'controller_activate' not in daemon.names, daemon.names


def test_modify_function_options_still_reloads_when_active(app, daemon):
    """이미 도는 함수는 종전대로 리로드된다 — 위 수정이 리로드를 죽이지 않았다."""
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models.function import Conditional
    from aot.ai.services.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        uid = set_uuid()
        cond = Conditional(unique_id=uid)
        cond.name = 'cond-active'
        cond.is_activated = True
        db.session.add(cond)
        db.session.commit()

        res = AoTDataToolService.modify_function_options(uid, {'period': 7})
        row = Conditional.query.filter(Conditional.unique_id == uid).first()

        assert res.get('reloaded') is True, res
        assert daemon.names == ['controller_deactivate', 'controller_activate'], daemon.names
        assert row.is_activated, "리로드가 활성 함수를 꺼뜨렸다"


def test_modify_sequence_schedule_does_not_activate(app, daemon):
    from aot.ai.services.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        seq = _make_sequence()
        daemon.calls.clear()

        res = AoTDataToolService.modify_sequence_schedule(
            seq['function_id'], start='21:00', end='22:00')
        assert not res.get('error'), res

        assert not _trigger(seq['function_id']).is_activated, "시간표 편집이 시퀀스를 켰다"
        assert 'controller_activate' not in daemon.names, daemon.names
        assert set(daemon.names) <= ALLOWED_DAEMON_CALLS, daemon.names


def test_modify_sequence_step_does_not_activate(app, daemon):
    from aot.databases.models.function import Actions
    from aot.ai.services.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        seq = _make_sequence()
        action = Actions.query.filter(
            Actions.function_id == seq['function_id']).first()
        assert action is not None
        daemon.calls.clear()

        res = AoTDataToolService.modify_sequence_step(
            action.unique_id, duration_seconds=120)
        assert not res.get('error'), res

        assert not _trigger(seq['function_id']).is_activated, "스텝 편집이 시퀀스를 켰다"
        assert 'controller_activate' not in daemon.names, daemon.names
        assert set(daemon.names) <= ALLOWED_DAEMON_CALLS, daemon.names


def test_configure_sequence_day_does_not_activate(app, daemon):
    from aot.databases.models.function import Actions
    from aot.ai.services.aot_data_tool_service import AoTDataToolService

    with app.test_request_context():
        seq = _make_sequence()
        actions = Actions.query.filter(
            Actions.function_id == seq['function_id']).all()
        daemon.calls.clear()

        res = AoTDataToolService.configure_sequence_day(
            seq['function_id'], day=0,
            slots=[{'devices': [actions[0].unique_id], 'minutes': 30}],
            start='21:00')
        assert not res.get('error'), res

        assert not _trigger(seq['function_id']).is_activated, "요일 계획 편집이 시퀀스를 켰다"
        assert 'controller_activate' not in daemon.names, daemon.names
        assert set(daemon.names) <= ALLOWED_DAEMON_CALLS, daemon.names


# ---------------------------------------------------------------------------
# 빠뜨림 방지 — 새 config_only 도구가 검사 없이 들어오는 것을 막는다
# ---------------------------------------------------------------------------

COVERED_CONFIG_ONLY_TOOLS = {
    'create_sequence_function',
    'modify_function_options',
    'modify_sequence_schedule',
    'modify_sequence_step',
    'configure_sequence_day',
}


def test_every_config_only_tool_has_a_case():
    """config_only 도구가 늘었는데 여기 케이스가 없으면 실패한다.

    승인을 면제받는 도구는 "장비를 움직이지 않는다"는 약속으로 그 면제를
    받는다. 약속을 지키는지 아무도 안 보는 도구가 그 집합에 조용히 끼는
    것을 막는 게 이 검사의 전부다.
    """
    from aot.ai.services.tool_registry import config_only_tools

    declared = set(config_only_tools())
    missing = declared - COVERED_CONFIG_ONLY_TOOLS
    stale = COVERED_CONFIG_ONLY_TOOLS - declared

    assert not missing, (
        f"config_only 인데 활성화 안 함을 검사하지 않는 도구: {sorted(missing)}. "
        f"이 파일에 케이스를 추가하고 COVERED_CONFIG_ONLY_TOOLS 에도 넣을 것.")
    assert not stale, (
        f"더 이상 config_only 가 아닌데 명부에 남은 도구: {sorted(stale)}. "
        f"COVERED_CONFIG_ONLY_TOOLS 에서 뺄 것.")
