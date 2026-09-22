# coding=utf-8
"""폭염·한파 게이트는 들어가는 문턱과 나오는 문턱이 다르다.

문턱 바로 위아래에서 값이 흔들리면 300 초 유지(gate_ttl)만으로는 5 분마다 전
장비가 비상 운전과 정상 운전을 오간다. 들어갈 때는 실외·실내 둘 다 문턱을
넘어야 하고, 나올 때는 둘 중 하나라도 문턱에서 여유(2 °C)만큼 물러나야 한다.
"""
from aot.functions.utils.env_control.safety_gates import (
    GATE_BIT_COLD, GATE_BIT_HEAT, PreGateConfig, SafetyPreGate)

from .conftest import make_opening_profile

CFG = PreGateConfig(heat_ext_threshold=38.0, heat_int_threshold=35.0,
                    cold_ext_threshold=-2.0, cold_int_threshold=5.0,
                    gate_ttl=0.0)


def _env(T_ext, T_int):
    return {'internal': {'T': T_int, 'T_max': T_int, 'T_min': T_int, 'RH': 60.0},
            'external': {'T': T_ext, 'rain': 0.0, 'wind': 1.0}}


def _mask(gate, T_ext, T_int):
    return gate.evaluate(_env(T_ext, T_int), [make_opening_profile()]).gate_mask


def test_heat_holds_inside_the_release_band():
    g = SafetyPreGate(CFG)
    assert _mask(g, 38.5, 35.5) & GATE_BIT_HEAT
    # 문턱 아래로 조금 내려왔지만 여유(2 °C) 안 — 유지
    assert _mask(g, 37.5, 34.0) & GATE_BIT_HEAT
    # 실내가 여유 밖으로 물러남 — 해제
    assert not _mask(g, 37.5, 32.9) & GATE_BIT_HEAT


def test_heat_does_not_enter_below_the_threshold():
    """들어가는 문턱은 그대로다 — 여유는 나올 때만 쓴다."""
    g = SafetyPreGate(CFG)
    assert not _mask(g, 37.5, 34.0) & GATE_BIT_HEAT


def test_heat_flicker_at_the_threshold_does_not_toggle():
    g = SafetyPreGate(CFG)
    seq = [(38.1, 35.1), (37.9, 34.9), (38.1, 35.1), (37.8, 34.8)]
    assert all(_mask(g, e, i) & GATE_BIT_HEAT for e, i in seq)


def test_cold_mirrors_heat():
    g = SafetyPreGate(CFG)
    assert _mask(g, -3.0, 4.0) & GATE_BIT_COLD
    assert _mask(g, -1.0, 6.5) & GATE_BIT_COLD        # 여유 안 — 유지
    assert not _mask(g, 0.5, 6.5) & GATE_BIT_COLD     # 실외가 여유 밖 — 해제


def test_unknown_values_release_the_latch():
    """모르면 발동하지 않는다 — 래치도 같다."""
    g = SafetyPreGate(CFG)
    assert _mask(g, 38.5, 35.5) & GATE_BIT_HEAT
    env = _env(38.5, None)
    env['internal'] = {'T': None, 'T_max': None, 'T_min': None, 'RH': None}
    assert not g.evaluate(env, [make_opening_profile()]).gate_mask & GATE_BIT_HEAT
