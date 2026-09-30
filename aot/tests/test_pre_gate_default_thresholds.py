# coding=utf-8
"""프리게이트 폭염·한파 외부 문턱의 정본은 `PreGateConfig` 기본값 하나다.

예전에는 기본값이 38 / −2 °C 인데 `EnvCoordinator.initialize` 가 45 / −5 °C 를
따로 넘겼다. 운영(과 매뉴얼 docs/ai/env-control.md#pre-gate-checked-before-l1l3)은
45 / −5 로 돌고, 인자 없이 만드는 곳(시설 IEC 미리보기 `routes_geo_iec`, 테스트)은
다른 문턱으로 돌았다 — 같은 날씨에 한쪽은 비상 운전, 한쪽은 정상이었다.
"""
import ast
import os

from aot.functions.utils.env_control.safety_gates import (
    GATE_BIT_COLD, GATE_BIT_HEAT, PreGateConfig, SafetyPreGate)
from aot.functions.utils.env_control.types import ActuatorProfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mask(gate, T_ext, T_int):
    env = {'internal': {'T': T_int, 'T_max': T_int, 'T_min': T_int, 'RH': 60.0},
           'external': {'T': T_ext, 'rain': 0.0, 'wind': 1.0}}
    vent = ActuatorProfile(actuator_id='vent-1', kind='opening',
                           capabilities=['open', 'close'],
                           cost_fn=lambda env, pct: 0.0)
    return gate.evaluate(env, [vent]).gate_mask


def test_defaults_match_the_manual():
    cfg = PreGateConfig()
    assert cfg.heat_ext_threshold == 45.0
    assert cfg.cold_ext_threshold == -5.0


def test_default_gate_does_not_fire_between_old_and_canonical_thresholds():
    """40 °C / −3 °C 는 옛 기본값(38 / −2)으로는 비상이었고 운영에서는 아니었다."""
    assert not _mask(SafetyPreGate(), 40.0, 36.0) & GATE_BIT_HEAT
    assert not _mask(SafetyPreGate(), -3.0, 4.0) & GATE_BIT_COLD


def test_default_gate_fires_at_canonical_thresholds():
    assert _mask(SafetyPreGate(), 45.5, 36.0) & GATE_BIT_HEAT
    assert _mask(SafetyPreGate(), -5.5, 4.0) & GATE_BIT_COLD


def _pre_gate_config_kwargs(path):
    """파일 안의 모든 `PreGateConfig(...)` 호출의 키워드 이름들."""
    with open(os.path.join(_ROOT, path), encoding='utf-8') as f:
        tree = ast.parse(f.read())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, 'id', None) or getattr(fn, 'attr', None)
            if name == 'PreGateConfig':
                out.append({k.arg for k in node.keywords})
    return out


def test_coordinator_does_not_restate_the_thresholds():
    """값을 두 곳에 두면 다시 갈라진다 — 코디네이터는 기본값을 그대로 쓴다."""
    calls = _pre_gate_config_kwargs(
        'functions/custom_functions/env_coordinator.py')
    assert calls, "EnvCoordinator.initialize 가 PreGateConfig 를 만들지 않는다?"
    for kw in calls:
        assert 'heat_ext_threshold' not in kw
        assert 'cold_ext_threshold' not in kw
