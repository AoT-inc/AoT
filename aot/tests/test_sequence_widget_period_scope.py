# coding=utf-8
"""위젯 저장이 **요일별 주기를 뭉개지 않는가** — 실제 저장을 돌려 결과를 본다.

## 왜 이 테스트가 있나

per_day 는 요일마다 주기가 다른 것이 존재 이유다. 그런데 위젯 저장의 스케줄 동기화가
주기 하나를 7개 요일 전부에 덮어써서, 위젯에서 **아무 칸이나** 고쳐 저장하면
(표시 옵션이든 교차 시간이든) 요일마다 다르게 짜 둔 관수 주기가 조용히 하나로
뭉개졌다. 실측(2026-09-01 로컬): 요일별 `10800×6 + 금 1200` 이 관계없는 옵션 하나를
바꿔 저장하자 **전부 60** 이 됐다. 원래 값은 어디에도 남지 않는다.

예전 이 파일은 위젯 코드의 **문자열**(`for i in range(7)` 이 없는가 등)을 검사했다.
스케줄 저장이 정본 모듈(`aot/utils/sequence_schedule.py`) 하나로 모인 뒤로는(2026-09-21)
그런 문자열이 코드에서 사라져 검사가 의미를 잃는다. 그래서 **저장을 실제로 돌리고
DB 에 남은 스케줄을 본다** — 구조가 또 바뀌어도 이 테스트는 그대로 유효하다.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aot.config import ProdConfig

PERIODS = {0: 10800, 1: 10800, 2: 10800, 3: 10800, 4: 1200, 5: 10800, 6: 10800}


@pytest.fixture
def app(tmp_path, monkeypatch):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db
    import aot.aot_client
    import aot.utils.device_tz

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'period_scope.db'}"
        TESTING = True

    monkeypatch.setattr(aot.aot_client, 'DaemonControl', MagicMock())
    monkeypatch.setattr(aot.utils.device_tz, 'get_device_tz', lambda *a, **kw: 'UTC')
    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def _per_day_trigger(mode='per_day'):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import Trigger

    t = Trigger(unique_id=set_uuid())
    t.trigger_type = 'trigger_sequence'
    t.name = '주기 범위'
    t.is_activated = True
    t.timer_start_offset = 0
    t.output_duration = 0.0
    t.time_offset_minutes = 0
    t.resume_on_activate = True
    days = {str(d): {'enabled': True, 'start': '05:30', 'end': '17:00', 'period': p}
            for d, p in PERIODS.items()}
    t.timer_schedule = json.dumps({
        'version': 1, 'mode': mode,
        'shared': {'enabled': True, 'start': '05:30', 'end': '17:00', 'period': 10800},
        'days': days})
    t.timer_start_time, t.timer_end_time, t.period = '05:30', '17:00', 10800.0
    db.session.add(t)
    db.session.commit()
    return t


def _save_widget(trigger, stored, submitted):
    from aot.widgets.widget_trigger_sequence import execute_at_modification
    widget = SimpleNamespace(unique_id='w-1', custom_options=json.dumps(stored))
    return execute_at_modification(widget, None, None, submitted)


def _stored_periods(trigger):
    from aot.aot_flask.extensions import db
    from aot.databases.models import Trigger
    db.session.expire_all()
    t = Trigger.query.filter_by(unique_id=trigger.unique_id).first()
    sched = json.loads(t.timer_schedule)
    return {int(k): v['period'] for k, v in sched['days'].items()}, sched


def _today():
    from aot.utils.weekly_schedule import get_today_idx
    return get_today_idx('UTC')


def _base_options(trigger, period):
    return {'function_id': trigger.unique_id, 'sequence_period': period,
            'timer_start_offset': 0, 'output_duration': 0.0,
            'time_offset_minutes': 0, 'resume_on_activate': 'resume'}


def test_per_day_changes_only_todays_period(app):
    """핵심 회귀. 주기 칸을 고치면 **오늘 요일만** 바뀌고 나머지는 그대로다."""
    with app.app_context():
        t = _per_day_trigger()
        today = _today()
        stored = _base_options(t, float(PERIODS[today]))
        _save_widget(t, stored, {**stored, 'sequence_period': 60.0})

        periods, _ = _stored_periods(t)
        expected = dict(PERIODS)
        expected[today] = 60
        assert periods == expected, '요일별 주기가 뭉개졌다'


def test_saving_an_unrelated_option_leaves_the_schedule_alone(app):
    """교차 시간만 고쳤는데 주기가 바뀌면 안 된다(원래 사고의 모양)."""
    with app.app_context():
        t = _per_day_trigger()
        _, before = _stored_periods(t)
        stored = _base_options(t, float(PERIODS[_today()]))
        _save_widget(t, stored, {**stored, 'output_duration': 30.0})

        periods, after = _stored_periods(t)
        assert periods == PERIODS
        assert after['days'] == before['days']


def test_shared_mode_still_propagates_to_all_days(app):
    """공유 모드는 모든 요일이 같은 것이 정의다 — 여기까지 막으면 안 된다."""
    with app.app_context():
        t = _per_day_trigger(mode='shared')
        stored = _base_options(t, float(PERIODS[_today()]))
        _save_widget(t, stored, {**stored, 'sequence_period': 900.0})

        periods, sched = _stored_periods(t)
        assert set(periods.values()) == {900}
        assert sched['shared']['period'] == 900


def test_the_legacy_mirror_follows_the_single_rule(app):
    """저장 뒤 레거시 컬럼은 정본에서 **한 가지 규칙**(to_legacy)으로 맞춰진다 —
    예전에는 저장 경로마다 per_day 레거시 주기가 '오늘' 이기도 '첫 활성 요일' 이기도
    했다."""
    from aot.utils.weekly_schedule import to_legacy
    with app.app_context():
        t = _per_day_trigger()
        stored = _base_options(t, float(PERIODS[_today()]))
        _save_widget(t, stored, {**stored, 'sequence_period': 60.0})

        from aot.databases.models import Trigger
        row = Trigger.query.filter_by(unique_id=t.unique_id).first()
        start, end, weekday, period = to_legacy(json.loads(row.timer_schedule))
        assert (row.timer_start_time, row.timer_end_time, row.period) == (start, end, period)


def test_the_widget_shows_todays_period_not_the_mirror(app):
    """표시값은 레거시 거울(첫 활성 요일)이 아니라 오늘 항목에서 읽을 때 계산한다.
    예전에는 저장 경로가 거울을 '오늘 값' 으로 덮어써 두었는데 다음 날 낡았다."""
    from aot.widgets.widget_trigger_sequence import refresh_display_values
    with app.app_context():
        t = _per_day_trigger()
        t.period = 99999.0          # 거울이 무엇이든
        from aot.aot_flask.extensions import db
        db.session.commit()
        shown = refresh_display_values('w-1', {'function_id': t.unique_id})
        assert shown['sequence_period'] == float(PERIODS[_today()])
