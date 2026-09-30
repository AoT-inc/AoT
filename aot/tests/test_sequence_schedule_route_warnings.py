# coding=utf-8
"""`/function_sequence_update_schedule` 와 `/sequence_update_weekday` 가
plan_for_day() 의 전체 경고(잘림·재시작·하루 여러 번 반복)를 번역해 돌려주는지.

## 왜 이 테스트가 있나

2026-09-25 이전에는 이 두 라우트가 weekly_schedule.build_warnings() 만 불러
"period > window" 하나(그것도 번역 없이 영어 그대로)만 돌려줬다. 실제 로컬
서버에 월요일 300초 주기(하루 120회 반복)로 설정된 시퀀스가 있었는데도 웹
화면은 아무 경고도 보여주지 않았다 — 이 파일의 시나리오가 바로 그 실측
사례다.

`Trigger`/`Actions` 는 실제 Flask-SQLAlchemy 세션에 저장하고, 라우트 안에서
호출하는 `utils_trigger.sequence_schedule_day_warnings()` 는 그 안에서
`SequenceTriggerController.plan_for_day()` 를 실제로 돌린다 — plan_for_day
는 `AOT_DB_PATH`(daemon 쪽 세션)로 조회하므로, 이 값을 테스트 앱과 같은
sqlite 파일로 맞춰야 두 경로가 같은 데이터를 본다
(test_trigger_sequence_restart_resume.py 와 같은 패턴).
"""
import json

import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path, monkeypatch):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db
    import aot.controllers.controller_trigger_sequence as seq_mod

    db_file = tmp_path / "route_warnings.db"
    db_uri = f"sqlite:///{db_file}"

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = db_uri
        TESTING = True

    application = create_app(config=_Config)
    # plan_for_day() 는 Flask 세션이 아니라 daemon 쪽 AOT_DB_PATH 로 직접
    # 읽는다 — 같은 파일을 보게 맞춘다.
    monkeypatch.setattr(seq_mod, 'AOT_DB_PATH', db_uri)
    import aot.utils.database as db_utils
    monkeypatch.setattr(db_utils, 'AOT_DB_PATH', db_uri)

    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def _entry(start='00:00', end='24:00', period=3600, enabled=True):
    return {'start': start, 'end': end, 'period': period, 'enabled': enabled}


def _make_monday_overrun_sequence(db):
    """실측 그대로: 월요일 300초 주기, 한 스텝이 700초 걸려 하루 120회
    반복되고 매 회차 재시작된다. 다른 요일은 꺼 둔다."""
    from aot.databases import set_uuid
    from aot.databases.models.function import Actions, Trigger

    trig = Trigger(unique_id=set_uuid())
    trig.trigger_type = 'trigger_sequence'
    trig.name = '월요일 과부하 시퀀스'
    trig.timer_start_time = '00:00'
    trig.timer_end_time = '24:00'
    trig.period = 300
    trig.output_duration = 0
    db.session.add(trig)
    db.session.commit()

    act = Actions(
        function_id=trig.unique_id, function_type='trigger',
        action_type='output_on_off',
        custom_options=json.dumps({
            'output': 'fake-output,0', 'state': 'on',
            'duration': 0.0, 'action_duration': 700.0,
            'sequence_mode': 'single', 'position': 0,
        }),
    )
    db.session.add(act)
    db.session.commit()

    days = {str(i): _entry(enabled=(i == 0)) for i in range(7)}
    days['0'] = _entry(start='00:00', end='10:00', period=300, enabled=True)
    schedule = {'version': 1, 'mode': 'per_day', 'shared': _entry(), 'days': days}

    from aot.utils import sequence_schedule
    errors = sequence_schedule.save(trig, schedule)
    assert not errors, errors
    db.session.commit()
    return trig.unique_id, schedule


def _call(app, monkeypatch, view_name, payload_fn):
    from aot.aot_flask.extensions import db
    import aot.aot_flask.routes_function as rf

    with app.test_request_context():
        fid, schedule = _make_monday_overrun_sequence(db)
    monkeypatch.setattr(rf, 'DaemonControl', lambda *a, **kw: type(
        'D', (), {'refresh_daemon_trigger_settings': lambda self, *a, **kw: None})())
    monkeypatch.setattr(rf.utils_general, 'user_has_permission', lambda *a, **kw: True)
    with app.test_request_context(json=payload_fn(fid, schedule)):
        resp = getattr(rf, view_name).__wrapped__()
    body = resp[0] if isinstance(resp, tuple) else resp
    return body.get_json()


class TestUpdateScheduleRoute:

    def test_returns_translated_per_day_warnings(self, app, monkeypatch):
        data = _call(app, monkeypatch, 'function_sequence_update_schedule',
                     lambda fid, sch: {'function_id': fid, 'schedule': sch})

        assert data.get('status') == 'success', data
        assert set(data['day_warnings'].keys()) == {'0'}, data
        msgs = data['day_warnings']['0']
        assert len(msgs) == 2, msgs  # 재시작 + 하루 여러 번 반복
        assert any('120' in m for m in msgs)
        assert len(data['warnings']) == 2


class TestUpdateWeekdayRoute:

    def test_returns_day_warnings_when_toggling_days(self, app, monkeypatch):
        data = _call(app, monkeypatch, 'sequence_update_weekday',
                     lambda fid, sch: {'function_id': fid, 'weekdays': '0'})

        assert data.get('status') == 'success', data
        assert '0' in data.get('day_warnings', {}), data
