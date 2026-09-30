"""미는 방향이 사이클마다 뒤집히면 창이 따라 뒤집히지 않는다 (2026-09-26).

실측(영양 육묘장 천창 09-24 12:19~18:00, 현장 리플레이): 창의 VPD 효과는
식힘(↓)과 건조한 외기(↑)가 겨룬 합이라, 실외 습도가 44↔53 % 로 흔들리자 부호가
사이클마다 바뀌었고 천창이 10분마다 열림·닫힘을 번갈아 6시간 24회 반전했다.
효과 크기는 0.12~0.27 kPa 로 작지 않았다 — 크기 하한으로는 못 거른다.
"""
from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
from aot.functions.utils.env_control.log_channels import (
    REASON_DIRECTION_UNSETTLED, REASON_PRIMARY,
)
from aot.functions.utils.env_control.tests.test_actuator_domains import (
    _TARGET, _Situation, _profile,
)

# VPD 가 목표보다 높다(건조) → 창의 효과가 ↓ 면 열고, ↑ 면 닫는다.
_DRY = {'vpd': +0.6}


def _run(directions, prev=20.0, integral=20.0):
    st = CoordinatorState(prev_commands={'vent': prev}, integral={'vent': integral})
    out = []
    for d in directions:
        vent = _profile('vent', 'opening', d, 0.2)
        cmds, st = coordinate(_Situation(_TARGET, _DRY), [vent], st, unique_id='t')
        c = cmds['vent']
        st.prev_commands['vent'] = c.control_value()      # 장치가 명령대로 섰다
        out.append((round(c.control_value(), 1), c.reason))
    return out


def _reversals(values):
    moves = [b - a for a, b in zip(values, values[1:]) if abs(b - a) >= 1.0]
    return sum(1 for a, b in zip(moves, moves[1:]) if (a > 0) != (b > 0))


def test_사이클마다_뒤집히는_방향에는_제자리를_지킨다():
    # 먼저 한 방향으로 자리 잡은 뒤(↓ 3회) 번갈아 뒤집힌다(600초 주기).
    out = _run(['↓'] * 3 + ['↑', '↓'] * 8)
    values = [v for v, _ in out]
    assert _reversals(values[3:]) == 0, out
    assert any(r == REASON_DIRECTION_UNSETTLED for _, r in out[3:]), out


def test_이어진_반전은_따른다():
    """진짜로 국면이 바뀌면(2사이클·10분 이상 같은 방향) 그쪽으로 간다."""
    out = _run(['↓'] * 3 + ['↑'] * 4)
    assert out[3][1] == REASON_DIRECTION_UNSETTLED
    assert out[-1][1] == REASON_PRIMARY
    assert out[-1][0] < out[2][0], out     # ↑ 면 닫는 쪽
