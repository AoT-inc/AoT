# coding=utf-8
"""
greybox/effect_adapter.py — greybox-PI: 레거시 effect_model 을 물리모델 민감도로 교체.

coordinator.py 의 제어 알고리즘(PI·slew·hysteresis·conflict·gradient·anti-windup)을
그대로 재사용하면서, 단 하나의 입력 — actuator 별 effect 자성/방향 — 만 레거시 K-모델
대신 greybox 물리모델(model.step)의 유한차분 민감도로 산출한다.

coordinator 가 기대하는 effect_model 계약과 동일한 형태({var: EffectFn}) 를 반환하므로
coordinator.py 는 무수정으로 동작한다. 각 EffectFn 은 magnitude_native = "해당 채널을
0→100% 로 열었을 때 1 사이클 동안의 변수 변화량(native)" 을 반환한다(레거시와 동일 규약).

greybox 가 모델링하지 않는 kind(shade/curtain/lighting/circulation_fan 등)는 None 을
반환하여, 호출부가 그 actuator 만 레거시 effect 로 폴백하게 한다.

linearization 기준점(다른 채널의 현재 명령)은 env_context 의 '_gb_base_cmds' 로 전달한다.
모델이 채널 명령에 대해 선형이므로 0→100 유한차분은 기준점과 무관하게 일관된다.
"""

from __future__ import annotations

from typing import Dict, Optional

from .model import step
from .params import GreyboxParams
from .channels import channel_for_kind
from ..types import EffectResult

# coordinator 변수명 → greybox 상태벡터 인덱스
_VAR_INDEX = {'temperature': 0, 'humidity': 1, 'co2': 2}

_TINY = 1e-9


def _gb_effect(channel: str, idx: int, env: dict,
               params: GreyboxParams, dt_default: float) -> EffectResult:
    dt = float(env.get('cycle_sec', dt_default) or dt_default)
    T  = env.get('T_int',  env.get('T_ext', 20.0))
    RH = env.get('RH_int', env.get('RH_ext', 60.0))
    CO2 = env.get('CO2_int', env.get('CO2_ext', 400.0))
    ext = {
        'T_ext':   env.get('T_ext',   20.0),
        'RH_ext':  env.get('RH_ext',  60.0),
        'CO2_ext': env.get('CO2_ext', 400.0),
        'solar':   env.get('solar',   0.0) or 0.0,
        'wind':    env.get('wind',    0.0) or 0.0,
    }
    base = dict(env.get('_gb_base_cmds') or {})
    c0 = dict(base); c0[channel] = 0.0
    c1 = dict(base); c1[channel] = 100.0
    p0 = step(T, RH, CO2, ext, c0, params, dt)
    p1 = step(T, RH, CO2, ext, c1, params, dt)
    delta = p1[idx] - p0[idx]
    if abs(delta) < _TINY:
        return EffectResult('0', 0.0)
    return EffectResult('↑' if delta > 0 else '↓', abs(delta))


def greybox_effect_model(
    kind: str,
    params: GreyboxParams,
    dt_default: float = 60.0,
) -> Optional[Dict[str, object]]:
    """kind 에 대한 greybox effect_model({var: EffectFn}) 생성.

    greybox 미모델 kind 면 None (호출부가 레거시 effect_model 유지).
    """
    channel = channel_for_kind(kind)
    if channel is None:
        return None

    def _make(var_idx: int):
        def _fn(env, pct=100.0, profile=None, _ch=channel, _i=var_idx):
            # pct 는 coordinator 가 항상 100 으로 호출(자성=100% 기준). 모델이 선형이라
            # 0→100 유한차분이 곧 100% 자성이며, coordinator 가 cmd/100 로 스케일한다.
            return _gb_effect(_ch, _i, env, params, dt_default)
        return _fn

    return {var: _make(idx) for var, idx in _VAR_INDEX.items()}
