# coding=utf-8
"""self_positioning value 출력(Matter 커튼 MATTER_COVERING)의 dispatch 어댑터 선택.

## 무엇을 지키는가

일반 value 어댑터는 0 % 를 `output_off()` 로 보낸다. 그런데 value 출력에서
off 는 **Stop** 이다(actuator_paired·Matter 커튼 모두). 스스로 위치를 잡는 커튼에
"닫아라(0 %)" 가 "멈춰라" 로 바뀌면, 코디네이터는 닫았다고 믿는데 커튼은 서 있다.

1. `self_positioning=True` 인 value 출력은 PairedAdapter — 0 % 도
   `output_on(output_type='value', amount=0)` 로 나간다. `output_off` 는 부르지 않는다.
2. 플래그가 없으면 같은 value 출력도 ValueAdapter(0 % → off) 그대로다 — 다른 출력은 안 바뀐다.
3. 디머(MATTER_LEVEL)는 pwm 이므로 PwmAdapter(0 % → off = OnOff Off).
4. 플래그는 모듈 파싱(`parse_output_information`)과 어댑터 맵 빌더까지 이어진다.
"""
from types import SimpleNamespace

import pytest

from aot.functions.utils.env_control import dispatch_adapters as da


class _Control:
    """output_off 가 불리면 바로 실패 — 0 % 가 Stop 으로 새는 것을 잡는다."""

    def __init__(self):
        self.calls = []

    def output_on(self, *a, **k):
        self.calls.append(('on', a, k))
        return (0, '')

    def output_off(self, *a, **k):
        self.calls.append(('off', a, k))
        return (0, '')


def test_self_positioning_value_output_gets_paired_adapter():
    adapter = da.select_adapter('MATTER_COVERING', ['value'], {}, True)
    assert isinstance(adapter, da.PairedAdapter)


def test_value_output_without_the_flag_keeps_the_plain_value_adapter():
    adapter = da.select_adapter('MATTER_COVERING', ['value'], {}, False)
    assert type(adapter) is da.ValueAdapter
    # 기본값(인자 생략)도 False
    assert type(da.select_adapter('SOME_DAC', ['value'])) is da.ValueAdapter


def test_self_positioning_flag_needs_a_value_type():
    # 플래그가 있어도 value 가 아니면 이 규칙을 타지 않는다.
    assert isinstance(da.select_adapter('X', ['pwm'], {}, True), da.PwmAdapter)


def test_dimmer_is_a_pwm_adapter():
    adapter = da.select_adapter('MATTER_LEVEL', ['pwm'], {}, False)
    assert isinstance(adapter, da.PwmAdapter)


def test_paired_adapter_sends_zero_percent_as_a_value_command():
    control = _Control()
    da.select_adapter('MATTER_COVERING', ['value'], {}, True).send(
        control, 'cov-1', 0.0, 0, 60.0)
    assert control.calls == [
        ('on', ('cov-1',), {'output_type': 'value', 'amount': 0.0, 'output_channel': 0})]
    assert not [c for c in control.calls if c[0] == 'off']


@pytest.mark.parametrize('pct', [0.0, 35.0, 100.0])
def test_paired_adapter_never_calls_output_off(pct):
    control = _Control()
    da.PairedAdapter().send(control, 'cov-1', pct, 0, 60.0)
    assert [c[0] for c in control.calls] == ['on']
    assert control.calls[0][2]['amount'] == pct


def test_plain_value_adapter_sends_zero_percent_as_off():
    """대비: 플래그 없는 value 출력의 0 % 는 off — 커튼에 그대로 쓰면 Stop 이 된다."""
    control = _Control()
    da.select_adapter('MATTER_COVERING', ['value'], {}, False).send(
        control, 'cov-1', 0.0, 0, 60.0)
    assert [c[0] for c in control.calls] == ['off']


def test_paired_adapter_still_raises_on_daemon_refusal():
    class Refusing(_Control):
        def output_on(self, *a, **k):
            return (1, 'node not reachable')

    with pytest.raises(RuntimeError, match='node not reachable'):
        da.select_adapter('MATTER_COVERING', ['value'], {}, True).send(
            Refusing(), 'cov-1', 0.0, 0, 60.0)


def test_parse_output_information_exposes_self_positioning():
    try:
        from aot.utils.outputs import parse_output_information
        info = parse_output_information()
    except Exception as err:  # pragma: no cover - environment specific
        pytest.skip(f'cannot load output modules without app/DB context: {err}')
    if 'MATTER_COVERING' not in info:  # pragma: no cover
        pytest.skip('output modules for Matter are not discoverable here')
    assert info['MATTER_COVERING'].get('self_positioning') is True
    assert info['MATTER_COVERING']['output_types'] == ['value']
    # 이 플래그는 커튼만 갖는다 — 다른 출력의 어댑터 선택이 바뀌면 안 된다.
    flagged = {name for name, meta in info.items() if meta.get('self_positioning')}
    assert flagged == {'MATTER_COVERING'}
    assert not info['MATTER_LEVEL'].get('self_positioning')


def test_build_adapter_map_passes_the_flag_through(monkeypatch):
    """모듈 정보의 self_positioning 이 어댑터 맵 빌더까지 도달한다."""
    monkeypatch.setattr(
        'aot.utils.outputs.parse_output_information',
        lambda *a, **k: {
            'MATTER_COVERING': {'output_types': ['value'], 'self_positioning': True},
            'MATTER_LEVEL': {'output_types': ['pwm']},
            'DAC': {'output_types': ['value']},
        })
    rows = {'cov': 'MATTER_COVERING', 'dim': 'MATTER_LEVEL', 'dac': 'DAC'}
    monkeypatch.setattr(
        'aot.utils.database.db_retrieve_table_daemon',
        lambda model, unique_id=None, **k: SimpleNamespace(output_type=rows[unique_id]))
    profile = SimpleNamespace(capacity_meta={}, cmd_constraints=None)
    adapters = da.build_adapter_map({'cov': profile, 'dim': profile, 'dac': profile})
    assert isinstance(adapters['cov'], da.PairedAdapter)
    assert isinstance(adapters['dim'], da.PwmAdapter)
    assert type(adapters['dac']) is da.ValueAdapter


def test_is_self_positioning_output_reads_the_module_flag():
    """지도의 열기/정지/닫기 버튼이 커튼에 붙는 근거 — 플래그가 있는 출력만 True."""
    from aot.outputs.paired_actuator_common import is_self_positioning_output
    try:
        from aot.utils.outputs import parse_output_information
        if 'MATTER_COVERING' not in parse_output_information():  # pragma: no cover
            pytest.skip('output modules for Matter are not discoverable here')
    except Exception as err:  # pragma: no cover - environment specific
        pytest.skip(f'cannot load output modules without app/DB context: {err}')
    assert is_self_positioning_output('MATTER_COVERING') is True
    assert is_self_positioning_output('MATTER_LEVEL') is False
    assert is_self_positioning_output('MATTER_ON_OFF') is False
    assert is_self_positioning_output(None) is False
    assert is_self_positioning_output('') is False
    assert is_self_positioning_output('NO_SUCH_OUTPUT') is False
