# coding=utf-8
"""SafetyService — 물리 동작 전 검증.

두 가지를 고정한다. 둘 다 2026-08-10 에 "돌고 있다고 믿었지만 안 돌던" 것이다.

1. `_check_spatial_conflicts` 는 `areas_to_check`/`geo_shape` 미정의(NameError)로
   **한 번도 작동한 적이 없었다.** 예외를 warning 한 줄로 삼켜 아무도 못 봤다.
2. `validate()` 가 받는 것은 `mcp_tool_call` + MCP **서버** uuid 다 —
   `action_type='output'` 은 폐기됐다. 껍데기를 벗기지 않으면 파라미터 상한도
   일일 한도도 공간 충돌도 전부 서버를 검사하며 헛돈다(SEC-001 이 이름만 남는다).
"""
from datetime import datetime, timedelta, timezone

import pytest

from aot.ai.services import safety_service
from aot.ai.services.safety_service import SafetyService


class _FakeShape(object):
    def __init__(self, unique_id, type_, name=None):
        self.unique_id = unique_id
        self.type = type_
        self.feature = {'properties': {'name': name}} if name else {}


class _FakePlan(object):
    def __init__(self, target_id, state='RUNNING', schedule_time=None,
                 end_time=None, reasoning='irrigation cycle'):
        self.target_id = target_id
        self.state = state
        self.schedule_time = schedule_time
        self.end_time = end_time
        self.reasoning = reasoning


@pytest.fixture
def wire(monkeypatch):
    """플랜 목록과 장치→공간 해석을 갈아끼운다 (DB 없이)."""
    def _wire(plans, areas):
        monkeypatch.setattr(SafetyService, '_active_plan_jobs',
                            staticmethod(lambda: plans))
        monkeypatch.setattr(SafetyService, '_areas_for_target',
                            staticmethod(lambda target_id: areas))
    return _wire


def test_running_plan_in_same_area_conflicts(wire):
    zone = _FakeShape('zone-1', 'zone', name='A동')
    wire([_FakePlan('zone-1')], {'zone-1': zone})

    violations = SafetyService._check_spatial_conflicts('output', 'dev-1')

    assert len(violations) == 1
    assert "zone 'A동'" in violations[0]


def test_plan_in_another_area_does_not_conflict(wire):
    wire([_FakePlan('zone-9')], {'zone-1': _FakeShape('zone-1', 'zone')})
    assert SafetyService._check_spatial_conflicts('output', 'dev-1') == []


def test_pending_plan_conflicts_only_inside_its_window(wire):
    """PENDING 은 시간창 안일 때만 충돌이다. DB 의 naive 값은 UTC 로 읽는다 —
    aware/naive 를 섞어 비교하면 TypeError 로 검사 전체가 죽는다."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    zone = _FakeShape('zone-1', 'zone', name='A동')

    inside = _FakePlan('zone-1', state='PENDING',
                       schedule_time=now - timedelta(minutes=5),
                       end_time=now + timedelta(minutes=5))
    wire([inside], {'zone-1': zone})
    assert len(SafetyService._check_spatial_conflicts('output', 'dev-1')) == 1

    later = _FakePlan('zone-1', state='PENDING',
                      schedule_time=now + timedelta(hours=2),
                      end_time=now + timedelta(hours=3))
    wire([later], {'zone-1': zone})
    assert SafetyService._check_spatial_conflicts('output', 'dev-1') == []


def test_abstract_plan_is_exempt(monkeypatch):
    def _boom():
        raise AssertionError('plan 끼리는 조회조차 하지 않아야 한다')
    monkeypatch.setattr(SafetyService, '_active_plan_jobs', staticmethod(_boom))
    assert SafetyService._check_spatial_conflicts('abstract_plan', 'zone-1') == []


def test_no_plans_skips_spatial_resolution(monkeypatch):
    """플랜이 하나도 없으면 비싼 공간 해석은 아예 하지 않는다."""
    monkeypatch.setattr(SafetyService, '_active_plan_jobs', staticmethod(lambda: []))

    def _boom(target_id):
        raise AssertionError('플랜이 없으면 공간 해석을 하면 안 된다')
    monkeypatch.setattr(SafetyService, '_areas_for_target', staticmethod(_boom))

    assert SafetyService._check_spatial_conflicts('output', 'dev-1') == []


def test_non_device_target_resolves_to_no_areas(wire):
    """mcp_tool_call 의 target_id 는 MCP 서버 uuid 다 — 도형이 없으니 무충돌."""
    wire([_FakePlan('zone-1')], {})
    assert SafetyService._check_spatial_conflicts('mcp_tool_call', 'srv-uuid') == []


def test_mcp_wrapper_unwraps_to_the_device():
    """physical_control_resolver 는 target_id=MCP 서버로 validate 를 부른다.
    껍데기를 벗기지 않으면 파라미터·일일한도·공간 검사가 전부 헛돈다."""
    action_type, target_id, params = SafetyService._unwrap_device_action(
        'mcp_tool_call', 'srv-uuid',
        {'tool_name': 'operate_device',
         'arguments': {'device_id': 'dev-1', 'state': 'on',
                       'channel': 0, 'duration_seconds': 180}})

    assert (action_type, target_id) == ('output', 'dev-1')
    assert params == {'state': 'on', 'channel': 0, 'amount': 180}


def test_mcp_wrapper_accepts_boolean_state():
    _, _, params = SafetyService._unwrap_device_action(
        'mcp_tool_call', 'srv-uuid',
        {'tool_name': 'operate_device',
         'arguments': {'device_id': 'dev-1', 'state': True}})
    assert params['state'] == 'on'


@pytest.mark.parametrize('params', [
    {'tool_name': 'get_sensor_reading', 'arguments': {'device_id': 'dev-1'}},
    {'tool_name': 'operate_device', 'arguments': {}},
    {},
])
def test_non_control_tool_calls_are_left_wrapped(params):
    """제어가 아니거나 장치를 못 찾으면 손대지 않는다 — 장치를 지어내지 않는다."""
    assert SafetyService._unwrap_device_action('mcp_tool_call', 'srv-uuid', params) \
        == ('mcp_tool_call', 'srv-uuid', params)


def test_unwrapped_duration_is_actually_capped():
    """껍데기를 벗긴 결과가 기존 파라미터 검사에 실제로 걸리는지."""
    action_type, target_id, params = SafetyService._unwrap_device_action(
        'mcp_tool_call', 'srv-uuid',
        {'tool_name': 'operate_device',
         'arguments': {'device_id': 'dev-1', 'state': 'on',
                       'duration_seconds': 99999}})

    violations = SafetyService._check_output_params(target_id, params)
    assert violations and 'exceeds max duration' in violations[0]


def test_failure_is_logged_not_raised(monkeypatch, caplog):
    """fail-open 은 유지하되, 조용히 죽지는 않는다(ERROR + 트레이스백)."""
    def _boom():
        raise RuntimeError('geo down')
    monkeypatch.setattr(SafetyService, '_active_plan_jobs', staticmethod(_boom))

    with caplog.at_level('ERROR', logger=safety_service.__name__):
        assert SafetyService._check_spatial_conflicts('output', 'dev-1') == []

    assert any(r.levelname == 'ERROR' and r.exc_info for r in caplog.records)
