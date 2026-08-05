# coding=utf-8
"""select_device 옵션 정규화 테스트.

옵션 프레임워크는 `select_device` 타입을 만나면 `<id>_id` 속성에 값을 넣는다
(`abstract_base_controller.setup_custom_options_csv`). 저장 형식이나 과거
데이터에 따라 `<id>` 자체에 들어 있기도 하다. 반면 조율기 내부 코드는
`<id>_device_id` 하나만 참조한다. 그 셋을 한 곳으로 모으는 것이 정규화다.

이게 빠지면 **아무 에러 없이** 해당 옵션이 영원히 빈값이 된다. 실제로 method
3종이 정규화 목록에서 빠져 있던 동안 setpoint 가 조용히 None 으로 떨어져
Method 곡선이 한 번도 평가되지 않았다.

예전에는 대상을 손으로 나열했다. 지금은 FUNCTION_INFORMATION 에서 뽑으므로
새 select_device 옵션이 자동으로 포함된다 — 이 테스트는 그 자동 도출이 실제로
전부를 덮는지, 그리고 세 입력 형태가 모두 같은 곳으로 모이는지 확인한다.
"""
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.custom_functions.env_coordinator_impl._function_info import (
    FUNCTION_INFORMATION,
)

_SELECT_DEVICE_IDS = [
    o['id'] for o in FUNCTION_INFORMATION.get('custom_options', [])
    if isinstance(o, dict) and o.get('type') == 'select_device' and o.get('id')
]


@pytest.fixture()
def coord():
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    return c


def test_there_are_select_device_options():
    """대상이 0개면 이 테스트 전체가 무의미해진다 — 조기에 알아채야 한다."""
    assert _SELECT_DEVICE_IDS, 'select_device 옵션을 하나도 찾지 못했다'


@pytest.mark.parametrize('oid', _SELECT_DEVICE_IDS)
def test_value_from_framework_id_suffix(coord, oid):
    """프레임워크가 쓰는 `<id>_id` 가 `<id>_device_id` 로 모여야 한다."""
    setattr(coord, f'{oid}_device_id', None)
    setattr(coord, f'{oid}_id', 'uuid-from-framework')
    setattr(coord, oid, None)

    coord._normalize_select_device_options()

    assert getattr(coord, f'{oid}_device_id') == 'uuid-from-framework'


@pytest.mark.parametrize('oid', _SELECT_DEVICE_IDS)
def test_value_from_bare_option_id(coord, oid):
    """`<id>` 자체에 들어 있는 형태도 흡수해야 한다."""
    setattr(coord, f'{oid}_device_id', None)
    setattr(coord, f'{oid}_id', None)
    setattr(coord, oid, 'uuid-bare')

    coord._normalize_select_device_options()

    assert getattr(coord, f'{oid}_device_id') == 'uuid-bare'


@pytest.mark.parametrize('oid', _SELECT_DEVICE_IDS)
def test_existing_value_is_not_overwritten(coord, oid):
    """이미 정규화된 값이 있으면 건드리지 않는다."""
    setattr(coord, f'{oid}_device_id', 'already-set')
    setattr(coord, f'{oid}_id', 'other')
    setattr(coord, oid, 'another')

    coord._normalize_select_device_options()

    assert getattr(coord, f'{oid}_device_id') == 'already-set'


@pytest.mark.parametrize('oid', _SELECT_DEVICE_IDS)
def test_empty_becomes_none_not_empty_string(coord, oid):
    """빈 문자열로 남기면 `if not x` 는 통과해도 DB 조회에 그대로 실린다."""
    setattr(coord, f'{oid}_device_id', '')
    setattr(coord, f'{oid}_id', '')
    setattr(coord, oid, '')

    coord._normalize_select_device_options()

    assert getattr(coord, f'{oid}_device_id') is None


def test_normalization_covers_every_select_device_option(coord):
    """자동 도출이 실제로 전부를 덮는지 — 하드코딩 목록으로 되돌아가면 여기서 걸린다."""
    for oid in _SELECT_DEVICE_IDS:
        setattr(coord, f'{oid}_device_id', None)
        setattr(coord, f'{oid}_id', f'v-{oid}')
        setattr(coord, oid, None)

    coord._normalize_select_device_options()

    missed = [oid for oid in _SELECT_DEVICE_IDS
              if getattr(coord, f'{oid}_device_id') != f'v-{oid}']
    assert not missed, f'정규화에서 빠진 select_device 옵션: {missed}'


def test_unknown_attributes_do_not_raise(coord):
    """옵션이 아직 주입되지 않은 상태(초기화 전)에서도 죽지 않아야 한다."""
    coord._normalize_select_device_options()   # 아무 속성도 없는 인스턴스
    for oid in _SELECT_DEVICE_IDS:
        assert getattr(coord, f'{oid}_device_id') is None
