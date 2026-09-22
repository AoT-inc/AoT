# coding=utf-8
"""
env_control/capability.py — 축별 기능 상태 (1단계: 계산·기록·표시만).

"이 시설에서 축마다 무엇을 할 수 있는가" 를 **한 곳에서** 답한다. 지금까지 그
답은 네 곳에 흩어져 있었다.

  - 장치 종류로 정하는 등급      `authority.derive_authority`
  - 잴 수 있는가                 `situation.assess` 의 `unmeasured`
  - 점검 마법사 판정             `GeoFacility.commissioning_state`
  - 사람이 제어에서 뺀 장치      `disabled_actuators` 옵션(적재 때 걸러짐)

⚠ **1단계에서 제어는 이 값을 읽지 않는다.** 코디네이터는 여전히 `authority`
  와 `unmeasured` 로 돈다. 여기 결과는 요약·로그·화면에만 간다. 제어가 이것을
  읽는 것은 2단계다 — 그 전에 기존 판정과 갈리는 사례(`compare_with_legacy`)를
  모아 근거로 삼는다.

⚠ **숫자 신뢰도는 두지 않는다.** 계산할 정직한 근거가 없는 수치는 가짜
  정밀도다. 대신 무엇을 근거로 한 상태인지(장치 이름·점검 판정)를 싣는다.

⚠ **순간 상황은 여기 넣지 않는다.** 외기 구배, 실외 값 끊김, 파킹, 인터록은
  사이클마다 바뀌는 사정이라 L3·안전 게이트가 맡는다. 여기는 시설의 구성과
  측정 가능 여부만 본다.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .authority import (
    LEVEL_ACTIVE, LEVEL_NATURAL, LEVEL_PASSIVE, _RANK, kind_authority,
)

AXES = ('temperature', 'humidity', 'vpd', 'co2', 'light')

STATE_CONTROL      = 'CONTROL'
STATE_ONE_WAY_UP   = 'ONE_WAY_UP'
STATE_ONE_WAY_DOWN = 'ONE_WAY_DOWN'
STATE_OBSERVE_ONLY = 'OBSERVE_ONLY'
STATE_BLIND        = 'BLIND'
STATE_NONE         = 'NONE'

# 축 방향 → 그 방향을 만드는 authority 키들.
#
# VPD 는 온도·습도의 합성이라 두 축에서 온다: 온도를 올리거나 습도를 내리면
# VPD 가 오르고, 그 반대면 내린다. `authority._VAR_TO_KEY['vpd'] = 'T'` 는 온도
# 등급으로만 근사해 방향 등급이 달라진다 — 분무기의 VPD 내림이 ACTIVE(가습)가
# 아니라 PASSIVE(증발 냉각)로 보인다. 그 차이를 드러내는 것이 1단계의 목적 중
# 하나다(계획서 D1).
_AXIS_KEYS = {
    'temperature': {'up': ('T_up',),             'down': ('T_down',)},
    'humidity':    {'up': ('RH_up',),            'down': ('RH_down',)},
    'vpd':         {'up': ('T_up', 'RH_down'),   'down': ('T_down', 'RH_up')},
    'co2':         {'up': ('CO2_up',),           'down': ('CO2_down',)},
    'light':       {'up': ('Light_up',),         'down': ('Light_down',)},
}

# 점검 판정 중 장치에 대한 것. 1단계에서는 **근거로 싣기만** 하고 등급을 깎지
# 않는다 — "장치 불량" 을 제어에서 어떻게 다룰지는 2단계 결정이다.
_FLAG_DEVICE_FAULT   = 'device_fault'
_FLAG_SENSOR_SUSPECT = 'sensor_suspect'


def _stronger(a: str, b: str) -> str:
    return a if _RANK.get(a, 0) >= _RANK.get(b, 0) else b


def _state_of(measured: Optional[bool], up: str, down: str) -> str:
    has_up   = up != LEVEL_NATURAL
    has_down = down != LEVEL_NATURAL
    if not (has_up or has_down):
        return STATE_OBSERVE_ONLY if measured else STATE_NONE
    if measured is False:
        # "센서 없음" 은 그 축을 **직접** 움직이는 장치가 있을 때만 말한다.
        # 부수 효과뿐인 축(창의 CO₂ 내림, 차광막의 온도 내림)까지 BLIND 로 두면
        # CO₂ 주입기가 없는 시설마다 "CO₂ 센서 없음" 이 늘 떠 소음이 된다 —
        # 그 시설은 CO₂ 를 다룰 생각이 없다. 그런 축은 NONE 이다.
        if LEVEL_ACTIVE not in (up, down):
            return STATE_NONE
        return STATE_BLIND
    if has_up and has_down:
        return STATE_CONTROL
    return STATE_ONE_WAY_UP if has_up else STATE_ONE_WAY_DOWN


def measured_axes(internal: Optional[dict]) -> Optional[Dict[str, bool]]:
    """실내 측정값 dict → 축별 "이번 사이클에 잴 수 있었나".

    `situation` 의 `unmeasured` 는 **목표가 있는 축만** 본다 — VPD 모드에서 온도는
    목표가 아니라 제약이라 온도 센서가 끊겨도 거기 안 나온다. 기능 상태는 목표와
    무관하게 시설이 무엇을 재는지를 말해야 하므로 실내 값에서 직접 가른다.

    광량은 실내 광센서가 없으면 실외 일사로 추정한 값(`light_est`)을 쓴다 —
    코디네이터가 광 판정에 실제로 쓰는 값이 그것이라 "잴 수 있음" 으로 본다.

    internal 이 None 이면(판정 없음) None — 모른다는 뜻이다.
    """
    if internal is None:
        return None
    has = lambda k: internal.get(k) is not None
    return {
        'temperature': has('T'),
        'humidity':    has('RH'),
        'vpd':         has('VPD') or (has('T') and has('RH')),
        'co2':         has('CO2'),
        'light':       has('light') or has('light_est'),
    }


def assess_capability(profiles: Iterable,
                      measured: Optional[Dict[str, bool]] = None,
                      commissioning_state: Optional[dict] = None,
                      excluded: Optional[List[dict]] = None,
                      names: Optional[Dict[str, str]] = None) -> Dict[str, dict]:
    """축별 기능 상태를 만든다. 순수 함수 — DB 도 로그도 건드리지 않는다.

    Args:
        profiles:            이번 사이클의 ActuatorProfile 목록(제외된 장치는 이미 빠짐)
        measured:            `measured_axes()` 결과. None 이면 이번 사이클에 측정
                             판정이 없었다(운전 시간대 밖 등). 그때 축의 `measured`
                             는 None — 모른다는 뜻이고, False 로 지어내지 않는다.
        commissioning_state: 시설의 점검 상태(`commissioning_flags` 등)
        excluded:            사람이 뺀 장치 [{name, kind, reason}]
        names:               actuator_id → 사람이 읽는 이름

    Returns:
        {axis: {state, measured, up, down, devices_up, devices_down,
                flags, excluded}}
    """
    names = names or {}
    cstate = commissioning_state or {}
    flags_by_id = dict(cstate.get('commissioning_flags') or {})
    for aid in (cstate.get('k_upper_bounds') or {}):
        flags_by_id.setdefault(aid, _FLAG_DEVICE_FAULT)
    profiles = list(profiles or ())
    excluded = list(excluded or ())

    out: Dict[str, dict] = {}
    for axis in AXES:
        keys = _AXIS_KEYS[axis]
        levels = {'up': LEVEL_NATURAL, 'down': LEVEL_NATURAL}
        devices = {'up': [], 'down': []}
        flags: List[dict] = []
        for p in profiles:
            kmap = kind_authority(p.kind)
            touched = False
            for d in ('up', 'down'):
                lv = LEVEL_NATURAL
                for k in keys[d]:
                    lv = _stronger(lv, kmap.get(k, LEVEL_NATURAL))
                if lv != LEVEL_NATURAL:
                    levels[d] = _stronger(levels[d], lv)
                    devices[d].append(names.get(p.actuator_id) or p.kind)
                    touched = True
            flag = flags_by_id.get(p.actuator_id)
            if touched and flag:
                flags.append({'name': names.get(p.actuator_id) or p.kind,
                              'flag': flag})
        ex = [e for e in excluded
              if any(kind_authority(e.get('kind')).get(k, LEVEL_NATURAL)
                     != LEVEL_NATURAL
                     for d in ('up', 'down') for k in keys[d])]
        m: Optional[bool] = None if measured is None else bool(measured.get(axis))
        out[axis] = {
            'state':        _state_of(m, levels['up'], levels['down']),
            'measured':     m,
            'up':           levels['up'],
            'down':         levels['down'],
            'devices_up':   sorted(set(devices['up'])),
            'devices_down': sorted(set(devices['down'])),
            'flags':        flags,
            'excluded':     [{'name': e.get('name'), 'reason': e.get('reason')}
                             for e in ex],
        }
    return out


def capability_signature(cap: Dict[str, dict]) -> str:
    """상태가 **바뀔 때만** 로그를 남기기 위한 비교 키."""
    return ','.join(f"{a}={(cap.get(a) or {}).get('state')}" for a in AXES)


# 기존 판정이 방향별로 보는 authority 키(`authority._VAR_TO_KEY` + `_up/_down`).
# VPD 는 온도 키로 근사한다 — 여기가 새 판정과 갈리는 자리다.
_LEGACY_KEYS = {
    'temperature': ('T_up', 'T_down'),
    'humidity':    ('RH_up', 'RH_down'),
    'vpd':         ('T_up', 'T_down'),
    'co2':         ('CO2_up', 'CO2_down'),
    'light':       ('Light_up', 'Light_down'),
}


def compare_with_legacy(cap: Dict[str, dict], authority: Dict[str, str],
                        unmeasured: Optional[Iterable[str]],
                        target_axes: Iterable[str]) -> List[str]:
    """새 상태와 기존 판정이 **갈리는** 축을 사람이 읽는 문장으로 돌려준다.

    2단계에서 제어가 이 값을 읽기 전에, 둘이 어디서 다르게 답하는지 모으는
    그림자 비교다. 목표가 있는 축(`target_axes`)만 본다 — 목표 없는 축은 기존
    판정이 애초에 답하지 않는다.

    방향별 등급을 비교한다. 기존 판정은 제어 대상 제외(`is_natural_var`, 양방향
    NATURAL)와 도달 불가 경보(`needed_direction_authority`, 방향별)에 쓰인다.
    지금 있는 장치 종류로는 VPD 의 "양방향 NATURAL" 여부는 갈리지 않고(분무기도
    증발 냉각으로 온도 내림 PASSIVE 를 가진다), **방향 등급**이 갈린다 — 예컨대
    분무기의 VPD 내림은 기존 PASSIVE, 새 ACTIVE.
    """
    unmeasured = set(unmeasured or ())
    diffs: List[str] = []
    auth = authority or {}
    for axis in target_axes:
        c = cap.get(axis)
        if not c or axis not in _LEGACY_KEYS:
            continue
        up_k, down_k = _LEGACY_KEYS[axis]
        for d, k in (('up', up_k), ('down', down_k)):
            old = auth.get(k, LEVEL_NATURAL)
            if old != c[d]:
                diffs.append(f'{axis} {d}: 기존={old} / 새={c[d]}')
        if c['measured'] is not None and (axis in unmeasured) == c['measured']:
            diffs.append(f'{axis}: 기존=측정 {axis not in unmeasured} / 새=측정 {c["measured"]}')
    return diffs


__all__ = [
    'AXES', 'assess_capability', 'measured_axes', 'capability_signature', 'compare_with_legacy',
    'STATE_CONTROL', 'STATE_ONE_WAY_UP', 'STATE_ONE_WAY_DOWN',
    'STATE_OBSERVE_ONLY', 'STATE_BLIND', 'STATE_NONE',
    'LEVEL_ACTIVE', 'LEVEL_PASSIVE', 'LEVEL_NATURAL',
]
