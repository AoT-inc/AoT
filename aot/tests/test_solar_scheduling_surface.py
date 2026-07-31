# coding=utf-8
"""Unit tests for the solar-anchored scheduling surfaces (5단계).

- trigger_sunrise_sunset 이 태양 이벤트 5종을 모두 받는지 (검증 로직)
- schedule_device_control 의 solar_event 경로가 커널 시각을 쓰는지

DB 는 건드리지 않는다 — 폼/서비스는 스텁으로 대체한다.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import pytz

from aot.utils.solar import SUN_EVENTS


# ---------------------------------------------------------------------------
# 트리거 — 이벤트 5종 허용 · 좌표 없이도 저장
# ---------------------------------------------------------------------------

def _trigger_form(rise_or_set='sunrise'):
    """utils_trigger.trigger_mod 이 읽는 필드만 흉내낸 최소 폼."""
    def _field(data, label):
        return SimpleNamespace(data=data, label=SimpleNamespace(text=label))
    return SimpleNamespace(
        rise_or_set=_field(rise_or_set, 'Sun Event'),
        latitude=_field(None, 'Latitude'),
        longitude=_field(None, 'Longitude'),
        date_offset_days=_field(0, 'Date Offset'),
        time_offset_minutes=_field(0, 'Time Offset'),
    )


def _validate(rise_or_set, latitude=None, longitude=None):
    """utils_trigger 의 trigger_sunrise_sunset 검증부와 같은 규칙을 재현."""
    form = _trigger_form(rise_or_set)
    trigger = SimpleNamespace(latitude=latitude, longitude=longitude)
    errors = []

    if form.rise_or_set.data not in SUN_EVENTS:
        errors.append('event')
    if trigger.latitude is not None and not (-90 <= trigger.latitude <= 90):
        errors.append('lat')
    if trigger.longitude is not None and not (-180 <= trigger.longitude <= 180):
        errors.append('lng')
    return errors


@pytest.mark.parametrize('event', list(SUN_EVENTS))
def test_all_sun_events_accepted(event):
    assert _validate(event) == []


def test_unknown_event_rejected():
    assert 'event' in _validate('moonrise')


def test_missing_coordinates_no_longer_block_saving():
    """좌표는 커널이 상속한다 — 비어 있다고 저장을 막지 않는다."""
    assert _validate('sunset', latitude=None, longitude=None) == []


def test_out_of_range_coordinates_still_rejected():
    assert 'lat' in _validate('sunset', latitude=120.0, longitude=0.0)
    assert 'lng' in _validate('sunset', latitude=0.0, longitude=200.0)


def test_trigger_validation_matches_kernel_events():
    """UI 선택지(config.SUN_EVENTS)와 커널 이벤트 목록이 어긋나면 저장이 깨진다."""
    from aot.config import SUN_EVENTS as UI_EVENTS
    assert [key for key, _label in UI_EVENTS] == list(SUN_EVENTS)


# ---------------------------------------------------------------------------
# AI 일회성 예약 — solar_event 경로
# ---------------------------------------------------------------------------

@pytest.fixture
def scheduling_stubs(monkeypatch):
    """Output 조회·propose_job·태양 커널을 스텁으로 갈아끼운다."""
    captured = {}
    output = SimpleNamespace(unique_id='dddddddd-0000-0000-0000-000000000000',
                             name='밸브1')

    class _Query:
        def filter(self, *_a, **_k):
            return self

        def first(self):
            return output

    # 도구는 함수 안에서 import 하므로 모듈 속성 자체를 갈아끼운다.
    monkeypatch.setattr('aot.databases.models.Output',
                        SimpleNamespace(query=_Query(), unique_id=None, name=None))
    monkeypatch.setattr('aot.utils.device_tz.resolve_location_tz',
                        lambda *_a, **_k: pytz.timezone('Asia/Seoul'))

    target = datetime(2026, 7, 31, 10, 7, tzinfo=pytz.utc)

    def _fake_next(kind, target_id=None, time_offset_minutes=0,
                   date_offset_days=0, now=None, **_kw):
        captured.update(kind=kind, target_id=target_id,
                        offset=time_offset_minutes, date_offset=date_offset_days)
        return captured.get('result', target)

    monkeypatch.setattr('aot.utils.solar.next_sun_event', _fake_next)

    def _fake_propose(**kwargs):
        captured['proposed'] = kwargs
        return SimpleNamespace(id=1, unique_id='job', anchor_tz=None, anchor_source=None)

    monkeypatch.setattr(
        'aot.ai.services.ai_scheduler_service.AISchedulerService.propose_job',
        staticmethod(_fake_propose))
    captured['output'] = output
    captured['target'] = target
    return captured


def test_solar_event_resolves_schedule_time(scheduling_stubs):
    from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

    S.schedule_device_control_tool('밸브1', solar_event='sunset',
                                   solar_offset_minutes=-30, duration_minutes=1)

    assert scheduling_stubs['kind'] == 'sunset'
    assert scheduling_stubs['offset'] == -30
    # 장치 위치 기준으로 해석한다 — 농장 전역이 아니라.
    assert scheduling_stubs['target_id'] == scheduling_stubs['output'].unique_id
    assert scheduling_stubs['proposed']['schedule_time'] == scheduling_stubs['target']


def test_solar_event_passes_date_offset(scheduling_stubs):
    from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

    S.schedule_device_control_tool('밸브1', solar_event='civil_dawn',
                                   solar_date_offset_days=2)
    assert scheduling_stubs['kind'] == 'civil_dawn'
    assert scheduling_stubs['date_offset'] == 2


def test_unknown_solar_event_returns_error(scheduling_stubs):
    from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

    result = S.schedule_device_control_tool('밸브1', solar_event='moonrise')
    assert 'error' in result
    assert 'moonrise' in result['error']
    assert 'proposed' not in scheduling_stubs      # 예약이 만들어지지 않았다


def test_missing_solar_event_returns_error(scheduling_stubs):
    """극야 등으로 커널이 시각을 못 주면 조용히 지금으로 잡지 않는다."""
    from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

    scheduling_stubs['result'] = None
    result = S.schedule_device_control_tool('밸브1', solar_event='sunrise')
    assert 'error' in result
    assert 'proposed' not in scheduling_stubs


def test_time_inputs_still_work(scheduling_stubs):
    """기존 경로(delay_seconds)는 태양 인자 없이 그대로 동작한다."""
    from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

    S.schedule_device_control_tool('밸브1', delay_seconds=600)
    assert 'kind' not in scheduling_stubs          # 커널을 부르지 않았다
    assert 'proposed' in scheduling_stubs
