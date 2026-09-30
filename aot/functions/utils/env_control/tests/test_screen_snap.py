"""스크린(커튼·차광막) 0/100 결정은 기록 앞에서, 히스테리시스를 두고 (2026-09-26).

실측(영양 보온커튼 09-25~26): 기록·화면은 40 %·27.6 %·13.9 % 였는데 `_dispatch`
가 50 % 에서 잘라 장치에는 28시간 동안 0 만 나갔다.
"""
import types

from aot.functions.utils.env_control.dispatch_adapters import (
    snap_screen_commands, snap_screen_value,
)


def test_기록되는_값이_곧_전송값이다():
    profiles = [types.SimpleNamespace(actuator_id='cur', kind='curtain'),
                types.SimpleNamespace(actuator_id='win', kind='opening')]
    cmds = {'cur': {'value': 40.0, 'reason': 1}, 'win': {'value': 40.0, 'reason': 1}}
    snap_screen_commands(cmds, profiles, {'cur': 0.0, 'win': 0.0})
    assert cmds['cur']['value'] == 0.0          # 닫힌 커튼, 40 → 닫힌 채
    assert cmds['win']['value'] == 40.0         # 창은 건드리지 않는다


def test_경계_근처에서_끝과_끝을_오가지_않는다():
    """명령이 45~55 를 오가도 서 있는 쪽을 지킨다."""
    pos = 0.0
    for v in (45, 55, 48, 52, 58, 44):
        pos = snap_screen_value(v, pos)
    assert pos == 0.0
    pos = 100.0
    for v in (55, 45, 52, 48, 42, 56):
        pos = snap_screen_value(v, pos)
    assert pos == 100.0


def test_경계를_확실히_넘으면_움직인다():
    assert snap_screen_value(60.0, 0.0) == 100.0
    assert snap_screen_value(40.0, 100.0) == 0.0
    assert snap_screen_value(50.0, None) == 100.0   # 위치를 모르면 50 에서 자른다
