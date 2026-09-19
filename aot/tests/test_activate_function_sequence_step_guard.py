# coding=utf-8
"""activate_function 은 스텝이 없는 trigger_sequence 를 켜면 안 된다.

`create_sequence_function` 은 스텝이 하나도 안 붙으면 생성 자체를 거부하지만,
범용 `create_function_tool(function_type='trigger_sequence')` 로는 스텝 없는
빈 시퀀스가 그대로 만들어진다(장치 배선은 별도 단계라는 설계). 이 빈 껍데기를
`activate_function` 이 그대로 켜버리면 "아무 동작도 안 하는 함수가 활성 상태"
가 아니라 다음에 스텝이 추가되는 순간 승인 없이 장치가 움직이기 시작하는
빌미가 된다. 이 파일은 그 게이트가 실제로 막는지, 그리고 스텝이 있는 정상
시퀀스는 여전히 켜지는지를 검사한다.
"""
import pytest

from aot.config import ProdConfig


class _DaemonRecorder:
    def __init__(self):
        self.calls = []

    def controller_activate(self, controller_id):
        self.calls.append('controller_activate')
        return 0, 'ok'

    def controller_deactivate(self, controller_id):
        self.calls.append('controller_deactivate')
        return 0, 'ok'

    def __getattr__(self, name):
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

    db_file = tmp_path / "activate_guard.db"

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
    import aot.aot_client as aot_client

    rec = _DaemonRecorder()
    monkeypatch.setattr(aot_client, 'DaemonControl', lambda *a, **kw: rec)
    return rec


def _make_output():
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Output

    oid = set_uuid()
    out = Output(unique_id=oid)
    out.name = "valve-0"
    db.session.add(out)
    db.session.commit()
    return oid


def test_empty_sequence_refuses_to_activate(app, daemon):
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    from aot.databases.models.function import Trigger

    with app.test_request_context():
        created = AoTDataToolService.create_function_tool(function_type='trigger_sequence')
        assert not created.get('error'), created

        res = AoTDataToolService.activate_function_tool(created['function_id'])

        assert res.get('error'), res
        assert 'no steps' in res['error']
        assert 'controller_activate' not in daemon.names, daemon.names

        trig = Trigger.query.filter_by(unique_id=created['function_id']).first()
        assert not trig.is_activated, "빈 시퀀스가 켜졌다"


def test_sequence_with_steps_still_activates(app, daemon):
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    from aot.databases.models.function import Trigger

    with app.test_request_context():
        created = AoTDataToolService.create_sequence_function(
            name='seq-with-steps', device_ids=[_make_output()],
            state='on', step_duration=30)
        assert not created.get('error'), created

        res = AoTDataToolService.activate_function_tool(created['function_id'])

        assert res.get('status') == 'success', res
        assert 'controller_activate' in daemon.names, daemon.names

        trig = Trigger.query.filter_by(unique_id=created['function_id']).first()
        assert trig.is_activated, "스텝 있는 시퀀스가 안 켜졌다"


def test_non_sequence_trigger_activation_unaffected(app, daemon):
    """게이트는 trigger_sequence 전용이어야 한다 — 다른 트리거 타입까지
    스텝 없다고 막으면 과잉 제한이다."""
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    from aot.databases.models.function import Trigger

    with app.test_request_context():
        created = AoTDataToolService.create_function_tool(
            function_type='trigger_timer_duration')
        assert not created.get('error'), created

        res = AoTDataToolService.activate_function_tool(created['function_id'])

        assert res.get('status') == 'success', res
        trig = Trigger.query.filter_by(unique_id=created['function_id']).first()
        assert trig.is_activated
