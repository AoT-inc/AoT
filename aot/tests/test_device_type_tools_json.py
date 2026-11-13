# coding=utf-8
"""장치 종류 조회(`find.device_types`·`detail.device_type_options`)는 JSON 으로 나가야 한다.

종류 정의의 이름·옵션 문구가 `lazy_gettext` 라 예전엔 응답 직렬화 단계에서
`Object of type LazyString is not JSON serializable` 로 호출 전체가 실패했다
(벤치 26-11-07: 개선 전·후 모두 해당 호출 100% 실패 → 모델이 재시도·우회하느라 턴 낭비).
"""
import json

import pytest
from flask_babel.speaklater import LazyString

from aot.tools.data_tools.definition import DefinitionToolsMixin as D


def _lazy(text):
    return LazyString(lambda: text)


@pytest.fixture
def lazy_catalog(monkeypatch):
    inputs = {'T_IN': {'input_name': _lazy('입력 이름'), 'interfaces': ['I2C'],
                       'custom_options': [{'id': 'a', 'type': 'select', 'name': _lazy('옵션'),
                                           'default_value': _lazy('기본'),
                                           'options_select': [('x', _lazy('엑스'))]}]}}
    outputs = {'T_OUT': {'output_name': _lazy('출력 이름'), 'interfaces': ('GPIO',)}}
    monkeypatch.setattr(D, '_input_types', classmethod(lambda cls: inputs))
    monkeypatch.setattr(D, '_output_types', classmethod(lambda cls: outputs))
    import aot.config as cfg
    monkeypatch.setattr(cfg, 'FUNCTION_INFO', {'T_FN': {'name': _lazy('함수 이름')}}, raising=False)


@pytest.mark.parametrize('kind,name', [('input', '입력 이름'), ('output', '출력 이름'),
                                       ('function', '함수 이름')])
def test_list_device_types_is_json(lazy_catalog, kind, name):
    out = D.list_device_types(kind=kind)
    assert 'error' not in out
    text = json.dumps(out, ensure_ascii=False)
    assert name in text


def test_device_type_options_is_json(lazy_catalog):
    out = D.get_device_type_options(kind='input', device_type='T_IN')
    assert out['options'] == [{'id': 'a', 'type': 'select', 'name': '옵션', 'default': '기본'}]
    json.dumps(out, ensure_ascii=False)


def test_errors_unchanged(lazy_catalog):
    assert D.list_device_types(kind='bogus') == {'error': 'kind must be one of: input, output, function'}
    assert D.get_device_type_options(kind='input', device_type='NOPE') == {
        'error': "Unknown input_type 'NOPE'"}


def test_real_catalog_is_json():
    """실제 종류 정의 전체로도 직렬화된다 (함수 종류는 import 만으로 읽힌다)."""
    out = D.list_device_types(kind='function')
    assert out.get('types'), out
    json.dumps(out, ensure_ascii=False)


def test_list_device_types_query_is_part_of_type_or_name(lazy_catalog):
    # 실사용: find.device_types(kind='output', query='virtual') 가 거절됐다 — 종류·이름 조각으로 거른다.
    assert [t['type'] for t in D.list_device_types(kind='output', query='t_o')['types']] == ['T_OUT']
    assert [t['type'] for t in D.list_device_types(kind='output', query='출력')['types']] == ['T_OUT']
    assert D.list_device_types(kind='output', query='virtual')['types'] == []
    assert len(D.list_device_types(kind='output')['types']) == 1
