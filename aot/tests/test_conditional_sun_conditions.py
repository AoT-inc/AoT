# coding=utf-8
"""Unit tests for the Conditional sun conditions (sun_state · sun_event_countdown).

DB 는 건드리지 않는다 — 조건 row 와 태양 커널을 스텁으로 갈아끼워 `get_condition_value`
의 분기만 검증한다(라이브 DB 대상 테스트 금지 규칙).
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytz

from aot.utils import actions as actions_module
from aot.utils.timekit import utc_now

CONDITIONAL_ID = 'aaaaaaaa-0000-0000-0000-000000000000'
CONDITION_ID = 'bbbbbbbb-0000-0000-0000-000000000000'


def _condition(**kwargs):
    """conditional_data row 를 흉내내는 최소 객체."""
    base = dict(
        unique_id=CONDITION_ID,
        conditional_id=CONDITIONAL_ID,
        condition_type='sun_state',
        sun_event='sunset',
        sun_offset_start_minutes=0,
        sun_offset_end_minutes=0,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.fixture
def stub_condition(monkeypatch):
    """db_retrieve_table_daemon(...).filter(...).first() 체인을 스텁으로 대체."""
    holder = {}

    class _Query:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return holder.get('row')

    monkeypatch.setattr(actions_module, 'db_retrieve_table_daemon',
                        lambda *a, **k: _Query())
    return holder


# ---------------------------------------------------------------------------
# sun_state — 주간/야간
# ---------------------------------------------------------------------------

def test_sun_state_returns_daytime_flag(stub_condition, monkeypatch):
    stub_condition['row'] = _condition()
    seen = {}

    def _fake_is_daytime(target_id=None, start_offset_minutes=0, end_offset_minutes=0, **_kw):
        seen.update(target_id=target_id,
                    start=start_offset_minutes,
                    end=end_offset_minutes)
        return True

    monkeypatch.setattr('aot.utils.solar.is_daytime', _fake_is_daytime)

    assert actions_module.get_condition_value(CONDITION_ID) is True
    # 위치는 부모 Conditional 을 상속한다 — 조건 자신의 좌표는 없다.
    assert seen['target_id'] == CONDITIONAL_ID


def test_sun_state_passes_offsets_through(stub_condition, monkeypatch):
    stub_condition['row'] = _condition(sun_offset_start_minutes=45,
                                       sun_offset_end_minutes=-30)
    seen = {}

    def _fake_is_daytime(target_id=None, start_offset_minutes=0, end_offset_minutes=0, **_kw):
        seen.update(start=start_offset_minutes, end=end_offset_minutes)
        return False

    monkeypatch.setattr('aot.utils.solar.is_daytime', _fake_is_daytime)

    assert actions_module.get_condition_value(CONDITION_ID) is False
    assert seen == {'start': 45, 'end': -30}


def test_sun_state_null_offsets_become_zero(stub_condition, monkeypatch):
    """마이그레이션 직후 NULL 인 기존 행도 터지지 않아야 한다."""
    stub_condition['row'] = _condition(sun_offset_start_minutes=None,
                                       sun_offset_end_minutes=None)
    seen = {}

    def _fake_is_daytime(target_id=None, start_offset_minutes=0, end_offset_minutes=0, **_kw):
        seen.update(start=start_offset_minutes, end=end_offset_minutes)
        return True

    monkeypatch.setattr('aot.utils.solar.is_daytime', _fake_is_daytime)

    assert actions_module.get_condition_value(CONDITION_ID) is True
    assert seen == {'start': 0, 'end': 0}


def test_sun_state_none_when_location_unresolved(stub_condition, monkeypatch):
    stub_condition['row'] = _condition()
    monkeypatch.setattr('aot.utils.solar.is_daytime', lambda **_kw: None)
    assert actions_module.get_condition_value(CONDITION_ID) is None


# ---------------------------------------------------------------------------
# sun_event_countdown — 다음 이벤트까지 남은 초
# ---------------------------------------------------------------------------

def test_countdown_returns_seconds_until_event(stub_condition, monkeypatch):
    stub_condition['row'] = _condition(condition_type='sun_event_countdown',
                                       sun_event='sunrise')
    target = utc_now() + timedelta(hours=2)
    seen = {}

    def _fake_next(kind, target_id=None, time_offset_minutes=0, **_kw):
        seen.update(kind=kind, target_id=target_id, offset=time_offset_minutes)
        return target

    monkeypatch.setattr('aot.utils.solar.next_sun_event', _fake_next)

    seconds = actions_module.get_condition_value(CONDITION_ID)
    assert seconds == pytest.approx(7200, abs=5)
    assert seen['kind'] == 'sunrise'
    assert seen['target_id'] == CONDITIONAL_ID


def test_countdown_uses_event_offset(stub_condition, monkeypatch):
    stub_condition['row'] = _condition(condition_type='sun_event_countdown',
                                       sun_event='sunset',
                                       sun_offset_start_minutes=-60)
    seen = {}
    monkeypatch.setattr(
        'aot.utils.solar.next_sun_event',
        lambda kind, target_id=None, time_offset_minutes=0, **_kw: (
            seen.update(offset=time_offset_minutes), utc_now() + timedelta(minutes=30))[1])

    actions_module.get_condition_value(CONDITION_ID)
    assert seen['offset'] == -60


def test_countdown_defaults_to_sunset(stub_condition, monkeypatch):
    stub_condition['row'] = _condition(condition_type='sun_event_countdown',
                                       sun_event=None)
    seen = {}
    monkeypatch.setattr(
        'aot.utils.solar.next_sun_event',
        lambda kind, **_kw: (seen.update(kind=kind), utc_now() + timedelta(minutes=1))[1])

    actions_module.get_condition_value(CONDITION_ID)
    assert seen['kind'] == 'sunset'


def test_countdown_none_when_event_unavailable(stub_condition, monkeypatch):
    """극지에서 해당 이벤트가 없는 날 — 조용히 0 이 아니라 None 을 돌려준다."""
    stub_condition['row'] = _condition(condition_type='sun_event_countdown')
    monkeypatch.setattr('aot.utils.solar.next_sun_event', lambda *a, **k: None)
    assert actions_module.get_condition_value(CONDITION_ID) is None


# ---------------------------------------------------------------------------
# 조건 목록 등록
# ---------------------------------------------------------------------------

def test_sun_conditions_are_selectable():
    from aot.config import CONDITIONAL_CONDITIONS, SUN_EVENTS

    keys = [key for key, _label in CONDITIONAL_CONDITIONS]
    assert 'sun_state' in keys
    assert 'sun_event_countdown' in keys

    from aot.utils.solar import SUN_EVENTS as KERNEL_EVENTS
    assert [key for key, _label in SUN_EVENTS] == list(KERNEL_EVENTS)
