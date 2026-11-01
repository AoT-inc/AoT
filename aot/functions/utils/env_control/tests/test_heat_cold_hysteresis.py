# coding=utf-8
"""한파 게이트는 들어가는 문턱과 나오는 문턱이 다르다 — 그리고 폭염 게이트는 없다.

문턱 바로 위아래에서 값이 흔들리면 300 초 유지(gate_ttl)만으로는 5 분마다 전
장비가 비상 운전과 정상 운전을 오간다. 들어갈 때는 실외·실내 둘 다 문턱을
넘어야 하고, 나올 때는 둘 중 하나라도 문턱에서 여유(2 °C)만큼 물러나야 한다.

폭염 비상 게이트(실외 ≥45 · 실내 ≥35 → 창 100)는 2026-10-09 에 없앴다. 그 조건에서는
대개 바깥이 더 더워 창 100 이 반대 방향이었다 — 고온은 극한 고온 보호(`heat_protect`)
가 같은 종류의 히스테리시스(해제 여유·해제 지속·최소 유지)로 맡는다
(`test_heat_protect.py::TestEntryRelease`).
"""
from aot.functions.utils.env_control.log_channels import GATE_BIT_HEAT
from aot.functions.utils.env_control.safety_gates import (
    GATE_BIT_COLD, PreGateConfig, SafetyPreGate)

from .conftest import make_opening_profile

CFG = PreGateConfig(cold_ext_threshold=-2.0, cold_int_threshold=5.0,
                    gate_ttl=0.0)


def _env(T_ext, T_int):
    return {'internal': {'T': T_int, 'T_max': T_int, 'T_min': T_int, 'RH': 60.0},
            'external': {'T': T_ext, 'rain': 0.0, 'wind': 1.0}}


def _mask(gate, T_ext, T_int):
    return gate.evaluate(_env(T_ext, T_int), [make_opening_profile()]).gate_mask


def test_cold_holds_inside_the_release_band():
    g = SafetyPreGate(CFG)
    assert _mask(g, -3.0, 4.0) & GATE_BIT_COLD
    assert _mask(g, -1.0, 6.5) & GATE_BIT_COLD        # 여유 안 — 유지
    assert not _mask(g, 0.5, 6.5) & GATE_BIT_COLD     # 실외가 여유 밖 — 해제


def test_cold_does_not_enter_above_the_threshold():
    """들어가는 문턱은 그대로다 — 여유는 나올 때만 쓴다."""
    g = SafetyPreGate(CFG)
    assert not _mask(g, -1.0, 6.0) & GATE_BIT_COLD


def test_cold_flicker_at_the_threshold_does_not_toggle():
    g = SafetyPreGate(CFG)
    seq = [(-2.1, 4.9), (-1.9, 5.1), (-2.1, 4.9), (-1.8, 5.2)]
    assert all(_mask(g, e, i) & GATE_BIT_COLD for e, i in seq)


def test_unknown_values_release_the_latch():
    """모르면 발동하지 않는다 — 래치도 같다."""
    g = SafetyPreGate(CFG)
    assert _mask(g, -3.0, 4.0) & GATE_BIT_COLD
    env = _env(-3.0, None)
    env['internal'] = {'T': None, 'T_max': None, 'T_min': None, 'RH': None}
    assert not g.evaluate(env, [make_opening_profile()]).gate_mask & GATE_BIT_COLD


def test_there_is_no_heat_gate_any_more():
    """실외 50 °C · 실내 45 °C 여도 게이트는 서지 않는다 — 극한 고온 보호의 일이다."""
    g = SafetyPreGate(CFG)
    res = g.evaluate(_env(50.0, 45.0), [make_opening_profile()])
    assert not res.gate_mask & GATE_BIT_HEAT
    assert not res.triggered and not res.forced_commands
    assert not hasattr(PreGateConfig(), 'heat_ext_threshold')
    assert not hasattr(PreGateConfig(), 'heat_int_threshold')
