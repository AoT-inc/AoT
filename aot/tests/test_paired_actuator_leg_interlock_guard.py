# coding=utf-8
"""짝 액추에이터(열기/닫기/selector) 밑단 on/off 채널의 인터락 가드.

배경(2026-09-25, 사용자 가이드 작성 중 발견): `actuator_paired.py`/
`actuator_paired_bus.py` 자체는 목표 위치를 바꿀 때 반대쪽 릴레이를 먼저
끄고 방향 전환 사이에 정지 시간을 둔다(`actuator_paired.py:473-490` 부근).
하지만 그 인터락은 **짝 액추에이터 드라이버 안에서만** 적용됐다 — 밑단의
열기/닫기/selector on/off 채널 자체는 평범한 on/off 출력이고, 그 출력을
직접 켜고 끄는 모든 경로가 지나는 단일 게이트인
`OutputController.output_on_off` (`aot/controllers/controller_output.py`)
는 "이 output_id 가 어떤 짝 액추에이터의 다리로 쓰이는가"를 전혀 몰랐다.
출력 페이지에서 두 채널을 각각 켜거나, Conditional 액션이
`self.control.output_on()` 으로 각각 켜거나, MCP `operate_device` 가
`DaemonControl.output_on_off()` 로 각각 켜면 — 셋 다 이 게이트 하나로
수렴하므로(`aot_daemon.py` 의 `output_off`/`output_on`, `aot/tools/
data_tools/device.py` 의 `daemon.output_on_off`) 세 경로 모두 같은 문제를
가졌다.

이제 `OutputController._interlock_paired_legs` 가 이 게이트 안에서 그 관계를
확인하고, 반대쪽(또는 같은 버스의 다른 selector)이 켜져 있으면 새 명령이
드라이버에 닿기 전에 먼저 끈다 — 이 파일은 그 가드가 실제로 걸리는지를,
`test_output_command_audit.py` 의 `_Gate` 패턴으로 게이트만 떼어내 확인한다.
게이트 한 곳의 동작만 증명하면 충분한 이유: 세 경로 모두 이 게이트를 통해서만
실제 드라이버를 건드리기 때문에, 경로마다 따로 daemon/RPC/MCP 스택을 통째로
띄워 재확인할 필요가 없다.
"""
import logging

from aot.controllers.controller_output import OutputController


class _OnOffLeg:
    """열기/닫기/selector 다리 역할을 하는 평범한 on/off 시뮬레이터 채널.

    `on_off_virtual_single.py` 의 `output_switch`/`is_on` 을 그대로 흉내낸다 —
    다른 채널의 존재를 전혀 모르는 것이 실제 드라이버와 같다.
    """

    def __init__(self, name):
        self.output_name = name
        self.output_states = {0: False}

    def output_on_off(self, state, output_channel=0, **kwargs):
        self.output_states[output_channel] = state in ('on', 1, True)
        return 0, 'ok'

    def is_on(self, output_channel=0):
        return self.output_states.get(output_channel, False)


class _Gate:
    """`OutputController` 에서 게이트+인터락 가드만 떼어낸 최소 구성.

    `_paired_leg_relations_cached` 를 오버라이드해 DB 조회 없이 테스트가
    준비한 관계 맵을 그대로 돌려준다 — 파싱 로직(`paired_actuator_common.
    paired_leg_relations`)은 그쪽 단위 테스트가 따로 지킨다.
    """

    output_on_off = OutputController.output_on_off
    _interlock_paired_legs = OutputController._interlock_paired_legs
    _audit_command = lambda self, *a, **k: None  # noqa: E731 — 감사는 이 테스트의 관심사가 아니다
    _audit_lifecycle = lambda self, *a, **k: None  # noqa: E731

    def __init__(self, legs, relations):
        self.output = dict(legs)
        self.logger = logging.getLogger('paired-leg-interlock-test')
        self._on_origin = {}
        self._relations = relations

    def _paired_leg_relations_cached(self):
        return self._relations


def _open_close_relations(open_key, close_key, owner_id='측창', owner_name='측창'):
    """열기/닫기 한 쌍만 있는 짝 액추에이터의 관계 맵."""
    return {
        open_key: [{'owner_id': owner_id, 'owner_name': owner_name,
                   'leg': 'open', 'partners': [close_key]}],
        close_key: [{'owner_id': owner_id, 'owner_name': owner_name,
                    'leg': 'close', 'partners': [open_key]}],
    }


def test_output_page_style_direct_on_turns_off_the_already_on_opposite_leg():
    """출력 페이지/API 가 반대 다리를 직접 켜면, 이미 켜져 있던 다리를 게이트가 먼저 끈다."""
    open_leg = _OnOffLeg('열기 릴레이')
    close_leg = _OnOffLeg('닫기 릴레이')
    relations = _open_close_relations(('open-leg', 0), ('close-leg', 0))
    gate = _Gate({'open-leg': open_leg, 'close-leg': close_leg}, relations)

    gate.output_on_off('open-leg', 'on', origin={'type': 'user', 'id': 1})
    assert open_leg.is_on() and not close_leg.is_on()

    gate.output_on_off('close-leg', 'on', origin={'type': 'user', 'id': 1})

    assert close_leg.is_on(), "직접 명령한 다리는 켜져야 한다."
    assert not open_leg.is_on(), (
        "반대쪽 다리가 인터락으로 먼저 꺼지지 않았다 — 열기/닫기가 동시에 "
        "ON 인 상태를 게이트가 막지 못했다는 뜻이다.")


def test_function_trigger_action_style_calls_are_interlocked_too():
    """Conditional/Function 이 `self.control.output_on()` 으로 켜는 경우도 동일하다.

    `self.control` 은 `DaemonControl` 인스턴스이고, 그 `output_on`/`output_off`
    는 데몬 RPC 를 거쳐 결국 이 게이트(`controller['Output'].output_on_off`)를
    부른다 — 그래서 함수/Conditional 경로가 이 게이트에 도달했을 때의 동작은
    여기 구성한 것과 같다.
    """
    open_leg = _OnOffLeg('열기 릴레이')
    close_leg = _OnOffLeg('닫기 릴레이')
    relations = _open_close_relations(('open-leg', 0), ('close-leg', 0))
    gate = _Gate({'open-leg': open_leg, 'close-leg': close_leg}, relations)

    gate.output_on_off('close-leg', 'on', origin={'type': 'conditional', 'id': 'cond-1'})
    gate.output_on_off('open-leg', 'on', origin={'type': 'conditional', 'id': 'cond-1'})

    assert open_leg.is_on() and not close_leg.is_on()


def test_mcp_operate_device_style_calls_are_interlocked_too():
    """MCP `operate_device` 도 `DaemonControl.output_on_off()` 로 같은 게이트에 닿는다."""
    open_leg = _OnOffLeg('열기 릴레이')
    close_leg = _OnOffLeg('닫기 릴레이')
    relations = _open_close_relations(('open-leg', 0), ('close-leg', 0))
    gate = _Gate({'open-leg': open_leg, 'close-leg': close_leg}, relations)

    gate.output_on_off('open-leg', 'on', origin={'type': 'ai', 'id': 'mcp'})
    gate.output_on_off('close-leg', 'on', origin={'type': 'ai', 'id': 'mcp'})

    assert close_leg.is_on() and not open_leg.is_on()


def test_unrelated_channels_are_left_alone():
    """관계 맵에 없는 평범한 on/off 채널은 가드가 아무것도 건드리지 않는다."""
    plain = _OnOffLeg('평범한 릴레이')
    gate = _Gate({'plain': plain}, relations={})

    gate.output_on_off('plain', 'on', origin={'type': 'user', 'id': 1})

    assert plain.is_on()


def test_bus_selectors_can_be_on_together_for_parallel_drive():
    """actuator_paired_bus 의 병렬 구동 — selector 여러 개가 동시에 켜져 있어야 한다.

    버스 스케줄러(`_run_stage`)는 같은 방향으로 움직일 멤버들의 selector 를
    차례로 켠 뒤 한꺼번에 확인하고 버스 릴레이를 한 번 켠다. 실제 관계
    (`paired_leg_relations`)로 게이트를 구성해, selector-2 를 켜도 selector-1
    이 꺼지지 않는지 본다 — 꺼지면 마지막 멤버만 움직인다(이관 검토에서 재현).
    """
    from aot.outputs.paired_actuator_common import paired_leg_relations
    rows = [
        (f'v{i}', {'output_open_id': 'bus-open', 'output_close_id': 'bus-close',
                   'selector_output_id': f'sel-{i}'})
        for i in (1, 2, 3)
    ]
    relations = paired_leg_relations(rows, {})
    legs = {f'sel-{i}': _OnOffLeg(f'선택{i}') for i in (1, 2, 3)}
    legs['bus-open'] = _OnOffLeg('버스열림')
    legs['bus-close'] = _OnOffLeg('버스닫힘')
    gate = _Gate(legs, relations)

    for i in (1, 2, 3):
        gate.output_on_off(f'sel-{i}', 'on', origin={'type': 'user', 'id': 1})
    assert all(legs[f'sel-{i}'].is_on() for i in (1, 2, 3))

    # 버스의 실제 위험(열림·닫힘 동시 ON)은 여전히 막는다.
    gate.output_on_off('bus-open', 'on', origin={'type': 'user', 'id': 1})
    gate.output_on_off('bus-close', 'on', origin={'type': 'user', 'id': 1})
    assert legs['bus-close'].is_on()
    assert not legs['bus-open'].is_on()
