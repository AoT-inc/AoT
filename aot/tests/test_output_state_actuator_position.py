# coding=utf-8
"""모터로 여닫는 장치(측창·천창·커튼)의 get_output_state 는 **얼마나 열려
있는지**를 말해야 한다.

벤치(26-09-23, "SIM 측창 지금 얼마나 열려 있어?"): 응답이 채널 상태
`off`·`seconds_on 0` 뿐이라, 모델 여섯 번 중 다섯 번이 "닫혀 있음(0%)" 으로
답했다. 저장된 위치는 50% 였다 — 모터가 **돌지 않는다**는 것과 **닫혀
있다**는 것은 다르다. 위치는 장치 모듈이 매 이동마다 `last_position_pct`
로 저장해 두는데(재시작해도 남도록), 이 도구가 그것을 읽지 않았다.
"""
import json
import os
import tempfile

import pytest


@pytest.fixture(scope='module')
def ctx():
    from flask import Flask
    from flask_babel import Babel
    from aot.aot_flask.extensions import db
    import aot.databases.models  # noqa: F401
    from aot.databases.models import Output, OutputChannel

    tmp = tempfile.TemporaryDirectory()
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(tmp.name, 'o.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    Babel(app)
    c = app.app_context()
    c.push()
    db.create_all()
    db.session.add(Output(unique_id='vent-1', name='SIM 측창', output_type='actuator_paired'))
    db.session.add(OutputChannel(output_id='vent-1', channel=0, name='', custom_options=json.dumps(
        {'actuator_kind': 'side_vent', 'last_position_pct': 50.0, 'last_target_pct': 50.0})))
    db.session.add(Output(unique_id='valve-1', name='v111', output_type='virtual_on_off_single'))
    db.session.add(OutputChannel(output_id='valve-1', channel=0, name='', custom_options='{}'))
    db.session.commit()
    yield
    db.session.remove()
    c.pop()
    tmp.cleanup()


class _Daemon:
    states = {}

    def output_states_all(self):
        return self.states

    def output_sec_currently_on(self, *_a, **_k):
        return 0


def _call(monkeypatch, states, device_id):
    import aot.aot_client as client
    import aot.widgets.AoT_timer as timer
    import aot.utils.influx as influx
    from aot.tools.aot_data_tool_service import AoTDataToolService as S

    daemon = _Daemon()
    daemon.states = states
    monkeypatch.setattr(client, 'DaemonControl', lambda *a, **k: daemon)
    monkeypatch.setattr(timer, '_read_latest_started_at', lambda *a, **k: None)
    monkeypatch.setattr(influx, 'read_influxdb_single', lambda *a, **k: [None, None])
    return S.get_output_state(device_id)


def test_off_on_a_motor_actuator_reports_its_opening(ctx, monkeypatch):
    out = _call(monkeypatch, {'vent-1': {0: 'off'}}, 'vent-1')
    pos = out['position']
    assert pos['percent'] == 50.0
    assert pos['source'] == 'saved'


def test_the_reading_says_off_is_not_closed(ctx, monkeypatch):
    out = _call(monkeypatch, {'vent-1': {0: 'off'}}, 'vent-1')
    text = ' '.join(out['_reading'])
    assert "'position'" in text and 'closed' in text
    assert 'get_control_state' in text


def test_the_disagreement_is_said_not_hidden(ctx, monkeypatch):
    """채널이 off(=0%)라는데 저장된 위치는 50% 면 둘 다 보여야 한다."""
    out = _call(monkeypatch, {'vent-1': {0: 'off'}}, 'vent-1')
    assert out['position'].get('live_state_disagrees') is True


def test_a_live_numeric_state_is_the_position(ctx, monkeypatch):
    out = _call(monkeypatch, {'vent-1': {0: 35.0}}, 'vent-1')
    assert out['position']['percent'] == 35.0
    assert out['position']['source'] == 'live'
    assert 'live_state_disagrees' not in out['position']


def test_daemon_down_still_gives_the_saved_opening(ctx, monkeypatch):
    out = _call(monkeypatch, {}, 'vent-1')
    assert out['position']['percent'] == 50.0
    assert out['channels'] == {}


def test_a_plain_valve_is_unchanged(ctx, monkeypatch):
    out = _call(monkeypatch, {'valve-1': {0: 'off'}}, 'valve-1')
    assert 'position' not in out and '_reading' not in out
    assert out['channels']['0']['state'] == 'off'


def test_unknown_position_is_said_explicitly(ctx, monkeypatch):
    from aot.aot_flask.extensions import db
    from aot.databases.models import OutputChannel

    ch = OutputChannel.query.filter_by(output_id='vent-1').first()
    saved = ch.custom_options
    ch.custom_options = json.dumps({'actuator_kind': 'side_vent', 'last_position_pct': None})
    db.session.commit()
    try:
        out = _call(monkeypatch, {'vent-1': {0: 'off'}}, 'vent-1')
        assert out['position']['percent'] is None
        assert 'unknown' in ' '.join(out['_reading']).lower()
    finally:
        ch.custom_options = saved
        db.session.commit()


def test_the_logged_value_is_explained_as_target_or_position():
    """`value_logged_then` 은 이동 시작 때의 목표이거나 멈춘 때의 위치다."""
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    notes = ' '.join(S._actuator_position_reading(
        {'percent': 50.0, 'source': 'saved', 'value_logged_then': 80.0}))
    assert 'TARGET' in notes and 'POSITION' in notes
    assert 'value_logged_then' not in ' '.join(S._actuator_position_reading(
        {'percent': 50.0, 'source': 'saved'}))
