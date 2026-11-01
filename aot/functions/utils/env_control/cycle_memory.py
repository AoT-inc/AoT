# coding=utf-8
"""판단 규칙의 사이클 간 기억을 **재시작 너머로** 잇는다 — 정본은 이 모듈 한 곳이다 (2026-10-10).

## 왜 있는가

일사·고온·스크린 규칙은 이력(히스테리시스)과 래치로 경계의 들락거림을 막는다. 그 기억이 프로세스
메모리에만 있으면 데몬 재시작 직후의 첫 사이클은 **'꺼져 있었다'** 고 가정하고 판정한다 — 이력 띠
안의 값은 재시작 전과 정반대로 읽힌다.

실측(영양 육묘장, 개발서버 2026-10-10 14:13:44 재시작): 재시작 전 사이클들은 해가 있다(`sun_on`)
였고 14:14:00 첫 사이클이 읽은 실외 일사는 지나가는 구름의 159.6 W/m² 였다 — 일사 부하 환기의
이력 띠(켬 200 · 끔 150) 안이다. 재시작이 없었으면 '아직 해가 있다' 로 하한(근거 51)이 섰을 값을,
새 프로세스는 '해 없음' 으로 읽어 천창·측창을 0 %(근거 1)에 두었다. 다음 사이클(14:24)에 일사가
598 W/m² 로 돌아오자 하한이 섰다. 같은 입력의 리플레이에 재시작을 넣으면 그대로 재현된다.

같은 모양의 기억이 더 있다:

    `_solar_vent_state`        일사 부하 환기 — 해 있음·하한 켬 이력
    `_screen_state`            스크린 — 해 있음 이력·구름비 EMA·**오늘 받은 광(DLI)**·차광막 하루
                               이동 수·왕복 방지 대기·밤 보온·결로 틈·아침 램프 단계
    `_heat_state`              극한 고온 보호 — 래치·단계·진입/해제 타이머·일사·분무 여력 이력
    `_frost_state`             서리 — 단계(주의·보호)·최소 유지 기준 시각·실내 끊김 시각
                               (사전 게이트가 쥐는 상태를 코디네이터 속성으로 이어 준다)
    `_wind_state`              강풍 — 단계·선 시각·풀림 평균 창의 표본(사전 게이트가 쥔다, 같은 방식)
    `_constraint_breach_state` 온습도 하드 한계 래치(히스테리시스)
    `_light_breach_state`      광량 하드 한계 래치
    `_night_condensation_escape` 야간 결로 탈출 이력
    `_outage_state`            실외 값이 끊긴 시각 — 30 분 넘게 이어진 두절에서 제습으로 열린 창을 닫는 시계
                               (`outage_clock`, 근거 58)
    `_weather_memory`          강우·풍속의 마지막 실측 — 끊긴 센서를 '원래 없던 센서' 와 가르는 근거이자 위험 값
                               래치(사전 게이트가 쥔다, 서리·강풍과 같은 방식). 없으면 재시작 뒤 "더 열지 않음"
                               천장(EXT_EXP)이 사라진다
    `_coord_state`             PI 상태 중 `t_ceiling_active`(온도 상한 항의 히스테리시스 이력)·`humid_zone`(과습 구간
                               진입/이탈 이력)·`purge`(아침 습기 빼기 켜짐·직전 실내 온도·평활한 변화율)만 — ⚠ 참조
    `_rain_hold`               강우 단계 유지 — (단계, 만료 시각). 예보 0.9/1.0 경계에서 천창이 사이클마다 오가지
                               않게 붙드는 시한이라, 잃으면 유지 중이던 제한이 풀린 채 출발한다(사전 게이트가 쥔다)
    `_outdoor_rain_seen`       마지막 신선한 실측 강우(`read_outdoor_sensors` 의 규칙 A) — 비를 보던 강우계가 끊긴
                               채 재시작하면 예보 모델이 강우를 넘겨받아 게이트의 실측 래치를 지운다
    `_gate_latches`            사전 게이트의 래치 — 한파 비상(`cold_latched`, 들어갈 때 문턱·나올 때 +2 °C 여유)과
                               육묘 일소 분무 잠금(`nursery_locked`, 250 켬 · 150 끔)
    `_gate_held_positions`     전체 게이트가 닫아 둔 장치의 위치 {actuator_id: %} — 해제되는 첫 사이클에 적분을 그 위치로
                               되맞추는 근거(`_rebase_integral_after_gate`). 잃으면 게이트 전 평형 개도로 돌아가려 한다.
                               복원은 지금 등록된 장치만 남긴다(빠졌거나 바뀐 장치 방지)

재시작이 오늘의 DLI 를 0 으로, 차광막 하루 이동 수를 0 으로 되돌리고, 서 있던 고온 보호를 풀어
진입 지연만큼 다시 기다리게 하던 것이 모두 이 한 가지 결함이다.

## 규칙

- 사이클 끝의 런타임 저장(`_save_runtime_state`)이 위 기억을 시각과 함께 싣고, 초기화의
  `_load_runtime_state` 가 되살린다.
- **`MEMORY_MAX_AGE_S` 보다 오래된 기억은 버린다** — 오래 멈췄다면 그 사이의 이력은 지금과
  무관하다. 그때는 종전처럼 빈 기억으로 시작한다(규칙마다 '모르면 꺼짐' 쪽).
- 되살린 뒤 첫 사이클의 판정은 규칙 모듈이 평소대로 한다 — 기억은 **이전 사이클의 상태**일 뿐이라
  풀림·단계·하루 바뀜(`day_key`)은 그 모듈의 규칙이 그대로 가른다.
- 상태 클래스에 필드가 늘거나 줄어도 깨지지 않는다 — 아는 필드만 싣고, 없는 필드는 기본값이다.

⚠ 코디네이터 PI 의 사이클 간 상태(`CoordinatorState` 의 `drive_sign`·`gradient_active` 등)는 여기서
  다루지 않는다 — 그쪽은 항목마다 '재시작 직후 한 사이클은 종전 규칙' 이 보수적인 이유가 붙어 있다
  (`coordinator.py` 의 필드 주석). **예외 하나: `t_ceiling_active`.** 이것은 보수적이지 않았다 —
  켜진 항은 선 아래로 `T_CEILING_HYST` 만큼 더 내려가야 꺼지고 그동안 더 큰 초과분으로 '닫기' 쪽을 민다.
  잃으면 재시작 직후 한 사이클은 그 힘이 작아져 습도·VPD 항이 이긴다. 김제 육묘장3(2026-10-12 22:14)에서
  실내 16.6 °C · 습도 93 % 인 밤, 재시작 전 사이클들은 측창 0 % 였는데 첫 사이클만 14.8 %(근거 1)로 열렸다 —
  이력 하나만 이어 주면 0 % 로 같다(리플레이로 필드별 확인: 같은 입력에 `drive_sign`·`gradient_active`·
  `deadzone_wrong_side` 를 이어도 14.8 % 는 그대로).
  **`humid_zone`·`purge` 도 같다(2026-10-13).** 과습 구간은 들어가는 문턱(VPD 0.30 · 여유 2 °C)이 나오는 문턱
  (0.40 · 3 °C)보다 낮은 이력 띠다. 재시작 직후는 '구간 밖' 을 가정하고 들어가는 문턱으로 읽으므로, 띠 안에 있던
  집은 구간 밖으로 읽혀 '실외가 더 습하면 닫는 쪽(파킹)'·열림 상한 30 % 가 풀린 채 PI 가 연다. 아침 습기 빼기는
  구간 안이어도 켬 문턱(더 엄격)과 '오르는 중인지 모름' 으로 읽혀 5~15 % 하한이 한 사이클 사라진다.
⚠ 저장 위치는 `function_runtime_state.calibration_state_json` 의 `cycle_memory` 키다 — 그레이박스
  학습 창(`greybox_shadow_state`)과 같은 방식(병합 저장)이라 스키마를 바꾸지 않는다.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any, Dict, Optional

# 이보다 오래된 기억은 되살리지 않는다. 구동 주기(600 s)의 세 배 — 재시작 한 번과 사이클 한두 번의
# 지연은 넘기고, 반나절 멈춘 뒤의 이력은 버린다.
MEMORY_MAX_AGE_S = 1800.0

STORE_KEY = 'cycle_memory'

# (코디네이터 속성, 상태 클래스를 돌려주는 함수) — 클래스는 순환 import 를 피해 늦게 부른다.


def _solar_vent_cls():
    from .solar_vent import SolarVentState
    return SolarVentState


def _screen_cls():
    from .screen_policy import ScreenState
    return ScreenState


def _heat_cls():
    from .heat_protect import HeatProtectState
    return HeatProtectState


def _frost_cls():
    from .safety_gates import FrostState
    return FrostState


def _wind_cls():
    from .safety_gates import WindState
    return WindState


def _outage_cls():
    from .outage_clock import OutageState
    return OutageState


def _weather_cls():
    from .safety_gates import WeatherMemory
    return WeatherMemory


DATACLASS_MEMORIES = (
    ('_solar_vent_state', _solar_vent_cls),
    ('_screen_state', _screen_cls),
    ('_heat_state', _heat_cls),
    ('_frost_state', _frost_cls),
    ('_wind_state', _wind_cls),
    ('_outage_state', _outage_cls),
    ('_weather_memory', _weather_cls),
)
# 평범한 dict·bool 기억 — 되살릴 때 아는 키만 덮어쓴다(dict), 또는 bool 로 바꾼다.
DICT_MEMORIES = ('_constraint_breach_state', '_light_breach_state')
BOOL_MEMORIES = ('_night_condensation_escape',)
# 코디네이터 PI 상태(`CoordinatorState`, 코디네이터 속성 `_coord_state`)의 bool 이력 중 **재시작이 '열리는 쪽' 으로
# 읽는 것**만 싣는다 — 머리말 ⚠ 참조.
COORD_STATE_FLAGS = ('t_ceiling_active', 'humid_zone')
COORD_STATE_ATTR = '_coord_state'
# `CoordinatorState.purge`(`humid_regime.PurgeState`) — 평범한 dict 로 `_coord_state` 절 안에 싣는다.
COORD_STATE_PURGE = 'purge'
# 사전 게이트의 bool 래치 묶음 — 코디네이터 속성 `_gate_latches`(dict, 게이트로 이어 주는 속성)
PROPERTY_FLAG_MEMORIES = ('_gate_latches',)
# 게이트가 닫아 둔 위치 — 코디네이터 속성 `_gate_held_positions` = {actuator_id: 개도 %}.
HELD_POSITIONS_ATTR = '_gate_held_positions'
# 강우 단계 유지 — 코디네이터 속성 `_rain_hold` = (단계, 만료 시각[epoch 초, 벽시계]) 튜플.
RAIN_HOLD_ATTR = '_rain_hold'
# 마지막 신선한 실측 강우 — 코디네이터 속성 `_outdoor_rain_seen` = {'measured_mm': float, 'devices': [str]}
RAIN_SEEN_ATTR = '_outdoor_rain_seen'
# 온도 변화율(°C/h)로 받아들이는 범위 — 이보다 크면 망가진 값이다.
_PURGE_TREND_MAX = 60.0

# JSON 은 튜플을 배열로 낸다 — 튜플을 값으로 쓰는 dict 필드는 되돌린다.
_TUPLE_VALUE_FIELDS = {'pending'}


def _plain(v):
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_plain(x) for x in v]
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    raise TypeError('직렬화할 수 없는 값: %r' % type(v))


def _finite(v) -> Optional[float]:
    """유한한 실수면 그 값, 아니면 None(bool·문자열·NaN·inf 는 망가진 값이다)."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _export_purge(purge) -> Optional[dict]:
    if purge is None or not dataclasses.is_dataclass(purge):
        return None
    return {'on': bool(getattr(purge, 'on', False)),
            'T_prev': _finite(getattr(purge, 'T_prev', None)),
            'dT_h': _finite(getattr(purge, 'dT_h', None))}


def _import_purge(data):
    """저장된 dict → `PurgeState`. 값 하나라도 망가졌으면 None(통째로 버린다 — 일부만 이으면 추세가 엇나간다)."""
    if not isinstance(data, dict) or not isinstance(data.get('on'), bool):
        return None
    out = {}
    for k in ('T_prev', 'dT_h'):
        v = data.get(k)
        if v is None:
            out[k] = None
            continue
        f = _finite(v)
        if f is None or (k == 'dT_h' and abs(f) > _PURGE_TREND_MAX):
            return None
        out[k] = f
    from .humid_regime import PurgeState
    return PurgeState(on=data['on'], T_prev=out['T_prev'], dT_h=out['dT_h'])


def export_memory(owner, now: float) -> Dict[str, Any]:
    """`owner`(코디네이터)의 기억 → JSON 으로 쓸 수 있는 dict. 없는 기억은 싣지 않는다."""
    out: Dict[str, Any] = {'ts': float(now)}
    for attr, _cls in DATACLASS_MEMORIES:
        st = getattr(owner, attr, None)
        if st is None or not dataclasses.is_dataclass(st):
            continue
        try:
            out[attr] = _plain(dataclasses.asdict(st))
        except (TypeError, ValueError):
            continue
    for attr in DICT_MEMORIES:
        d = getattr(owner, attr, None)
        if isinstance(d, dict):
            try:
                out[attr] = _plain(d)
            except (TypeError, ValueError):
                continue
    for attr in BOOL_MEMORIES:
        if hasattr(owner, attr):
            out[attr] = bool(getattr(owner, attr))
    for attr in PROPERTY_FLAG_MEMORIES:
        d = getattr(owner, attr, None)
        if isinstance(d, dict) and d:
            out[attr] = {str(k): bool(v) for k, v in d.items()}
    cs = getattr(owner, COORD_STATE_ATTR, None)
    if cs is not None:
        flags = {f: bool(getattr(cs, f)) for f in COORD_STATE_FLAGS if hasattr(cs, f)}
        purge = _export_purge(getattr(cs, COORD_STATE_PURGE, None))
        if purge is not None:
            flags[COORD_STATE_PURGE] = purge
        if flags:
            out[COORD_STATE_ATTR] = flags
    held = _clean_held(getattr(owner, HELD_POSITIONS_ATTR, None))
    if held:
        out[HELD_POSITIONS_ATTR] = held
    hold = getattr(owner, RAIN_HOLD_ATTR, None)
    if isinstance(hold, (tuple, list)) and len(hold) == 2:
        level, until = _finite(hold[0]), _finite(hold[1])
        # 선 단계 제한이 아직 유효한 것만 — 만료됐거나 단계가 없으면 싣지 않는다(빈 기억과 같다).
        if level is not None and until is not None and until > float(now):
            out[RAIN_HOLD_ATTR] = {'level': int(level), 'until': until}
    seen = getattr(owner, RAIN_SEEN_ATTR, None)
    if isinstance(seen, dict):
        mm = _finite(seen.get('measured_mm'))
        devs = seen.get('devices')
        # 0 이하는 싣지 않는다 — 규칙 A 는 '마지막 실측이 비였을 때' 만 읽는다(비어 있는 기억과 같다).
        if mm is not None and mm > 0.0 and isinstance(devs, (list, tuple)):
            out[RAIN_SEEN_ATTR] = {'measured_mm': mm,
                                   'devices': [d for d in devs if isinstance(d, str)]}
    return out


def _build(cls, data: dict):
    names = {f.name for f in dataclasses.fields(cls)}
    kw = {k: v for k, v in (data or {}).items() if k in names}
    for k in _TUPLE_VALUE_FIELDS & set(kw):
        if isinstance(kw[k], dict):
            kw[k] = {kk: tuple(vv) if isinstance(vv, list) else vv
                     for kk, vv in kw[k].items()}
    return cls(**kw)


def restore_memory(owner, blob: Optional[dict], now: float,
                   max_age_s: float = MEMORY_MAX_AGE_S) -> list:
    """저장된 기억을 `owner` 에 되살린다 → 되살린 속성 이름 목록(없거나 낡았으면 []).

    기억이 `max_age_s` 보다 오래됐거나 시각이 없으면 아무것도 하지 않는다. 항목 하나가 깨져
    있어도 나머지는 되살린다.
    """
    if not isinstance(blob, dict):
        return []
    ts = _finite(blob.get('ts'))
    if ts is None:
        return []
    age = float(now) - ts
    if age < -60.0 or age > float(max_age_s):
        return []
    done = []
    for attr, cls_fn in DATACLASS_MEMORIES:
        data = blob.get(attr)
        if not isinstance(data, dict):
            continue
        try:
            setattr(owner, attr, _build(cls_fn(), data))
            done.append(attr)
        except (TypeError, ValueError):
            continue
    for attr in DICT_MEMORIES:
        data = blob.get(attr)
        if not isinstance(data, dict):
            continue
        cur = getattr(owner, attr, None)
        if isinstance(cur, dict):
            # 아는 키만 — 래치 이름이 바뀌었으면 새 키는 기본값으로 남는다.
            for k in cur:
                if k in data:
                    cur[k] = bool(data[k])
        else:
            setattr(owner, attr, {k: bool(v) for k, v in data.items()})
        done.append(attr)
    for attr in BOOL_MEMORIES:
        if attr in blob:
            setattr(owner, attr, bool(blob[attr]))
            done.append(attr)
    for attr in PROPERTY_FLAG_MEMORIES:
        data = blob.get(attr)
        cur = getattr(owner, attr, None)
        if not isinstance(data, dict) or not isinstance(cur, dict):
            continue
        new = dict(cur)
        got = False
        for k in cur:                       # 아는 키만
            if isinstance(data.get(k), bool):
                new[k] = data[k]
                got = True
        if got:
            try:
                setattr(owner, attr, new)
                done.append(attr)
            except (TypeError, ValueError, AttributeError):
                continue
    flags = blob.get(COORD_STATE_ATTR)
    cs = getattr(owner, COORD_STATE_ATTR, None)
    if isinstance(flags, dict) and cs is not None:
        got = False
        for f in COORD_STATE_FLAGS:
            if f in flags and hasattr(cs, f):
                setattr(cs, f, bool(flags[f]))
                got = True
        if COORD_STATE_PURGE in flags and hasattr(cs, COORD_STATE_PURGE):
            purge = _import_purge(flags[COORD_STATE_PURGE])
            if purge is not None:
                setattr(cs, COORD_STATE_PURGE, purge)
                got = True
        if got:
            done.append(COORD_STATE_ATTR)
    held = _clean_held(blob.get(HELD_POSITIONS_ATTR))
    if held:
        # 지금 등록된 장치만. 프로필이 아직 없으면(초기화 순서: 상태 복원 → 프로필 적재) 그대로 두고, 쓰는 자리
        # (`_rebase_integral_after_gate`)가 한 번 더 거른다.
        known = {getattr(p, 'actuator_id', None) for p in (getattr(owner, '_profiles', None) or [])}
        if known:
            held = {a: v for a, v in held.items() if a in known}
        if held:
            setattr(owner, HELD_POSITIONS_ATTR, held)
            done.append(HELD_POSITIONS_ATTR)
    if _restore_rain_hold(owner, blob.get(RAIN_HOLD_ATTR), float(now), ts):
        done.append(RAIN_HOLD_ATTR)
    seen = _clean_rain_seen(blob.get(RAIN_SEEN_ATTR))
    if seen is not None:
        setattr(owner, RAIN_SEEN_ATTR, seen)
        done.append(RAIN_SEEN_ATTR)
    return done


def _clean_held(data) -> dict:
    """{장치 id: 개도 %} 를 정리한다 — 키는 비지 않은 문자열, 값은 유한한 수(0~100 으로 자른다). 나머지는 버린다."""
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        f = _finite(v)
        if isinstance(k, str) and k and f is not None:
            out[k] = max(0.0, min(100.0, f))
    return out


def _restore_rain_hold(owner, data, now: float, saved_at: float) -> bool:
    """강우 단계 유지를 되살린다. 만료 시각은 `time.time()`(벽시계) 기준이라 재시작 너머로 그대로 뜻이 맞다.

    버리는 것: 이미 만료됐다 · 단계가 제한 단계(`HOLD_ROOF`·`RESTRICT`)가 아니다(전면 폐쇄는 게이트 TTL 이 맡고
    `_latch_rain_level` 도 잡지 않는다) · 저장한 시각에서 `RAIN_LEVEL_HOLD_S` 보다 멀리 떨어진 만료(시계가 어긋났거나
    망가진 값 — 유지가 무한정 서면 안 된다).
    """
    if not isinstance(data, dict) or not hasattr(owner, RAIN_HOLD_ATTR):
        return False
    from .safety_gates import (RAIN_LEVEL_HOLD_ROOF, RAIN_LEVEL_HOLD_S, RAIN_LEVEL_RESTRICT)
    level, until = data.get('level'), _finite(data.get('until'))
    if isinstance(level, bool) or not isinstance(level, int) or until is None:
        return False
    if level not in (RAIN_LEVEL_HOLD_ROOF, RAIN_LEVEL_RESTRICT):
        return False
    if until <= now or until > saved_at + float(RAIN_LEVEL_HOLD_S) + 60.0:
        return False
    try:
        setattr(owner, RAIN_HOLD_ATTR, (level, until))
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def _clean_rain_seen(data) -> Optional[dict]:
    """저장된 마지막 실측 강우 → 정리한 dict, 쓸 수 없으면 None. 비(> 0)를 본 기억만 뜻이 있다."""
    if not isinstance(data, dict):
        return None
    mm = _finite(data.get('measured_mm'))
    devs = data.get('devices')
    if mm is None or mm <= 0.0 or not isinstance(devs, list):
        return None
    devs = [d for d in devs if isinstance(d, str) and d]
    if not devs:
        return None
    return {'measured_mm': mm, 'devices': devs}
