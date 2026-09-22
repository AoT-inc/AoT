# coding=utf-8
"""
greybox/channels.py — actuator kind ↔ greybox 명령 채널 매핑 (단일 출처).

greybox 모델(model.py)은 5개 집약 채널만 입력으로 받는다:
    heat, cool, vent, fog, co2_inj
실제 시설의 다양한 actuator kind 를 이 채널로 사상한다. 매핑이 없는 kind
(shade/curtain/lighting/circulation_fan/dehumidifier 등)는 greybox 가 물리적으로
모델링하지 않으므로 None 으로 분류되어, 제어 경로에서 레거시 effect 로 폴백된다.

shadow 집계와 effect 어댑터·MPC 가 모두 이 모듈을 공유해 일관성을 보장한다.
"""

from __future__ import annotations

from typing import Dict, Optional

# greybox 모델 명령 채널
CHANNELS = ('heat', 'cool', 'vent', 'fog', 'co2_inj')

# actuator kind → greybox 채널. 누락 kind 는 None (미모델).
KIND_TO_CHANNEL: Dict[str, str] = {
    # 난방
    'heater':         'heat',
    # 냉방
    'cooler':         'cool',
    'ac':             'cool',
    # 환기(외기 교환) — 개구부·환기팬
    'opening':        'vent',
    'vent':           'vent',
    'side_vent':      'vent',
    'roof_vent':      'vent',
    'window':         'vent',
    'exhaust_fan':    'vent',
    'intake_fan':     'vent',
    # 가습/포그
    'fogger':         'fog',
    'humidifier':     'fog',
    # CO2 주입
    'co2_injector':   'co2_inj',
}

# greybox 가 모델링하지 않는 kind (명시적 — 가독성/문서화용)
UNMODELED_KINDS = frozenset({
    'shade', 'curtain', 'lighting', 'supplemental_light',
    'circulation_fan', 'dehumidifier', 'co2_scrubber',
})


def channel_for_kind(kind: Optional[str]) -> Optional[str]:
    """actuator kind 에 대응하는 greybox 채널. 미모델이면 None."""
    if not kind:
        return None
    return KIND_TO_CHANNEL.get(str(kind).lower())


def _channel_from_id(aid: str) -> Optional[str]:
    """kind 정보가 없을 때의 폴백 — actuator_id 키워드 추정(하위 호환)."""
    s = (aid or '').lower()
    if 'heat' in s:
        return 'heat'
    if 'cool' in s or 'ac' in s:
        return 'cool'
    if 'vent' in s or 'opening' in s or 'window' in s or 'fan' in s:
        return 'vent'
    if 'fog' in s or 'humid' in s:
        return 'fog'
    if 'co2' in s:
        return 'co2_inj'
    return None


def aggregate_cmds_by_kind(
    cmds_pct: Dict[str, float],
    kind_by_aid: Optional[Dict[str, str]] = None,
    vent_caps: Optional[Dict[str, 'VentCap']] = None,
) -> Dict[str, float]:
    """actuator_id→pct 를 greybox 채널별 최대값으로 집계.

    kind_by_aid 가 주어지면 kind 매핑을 우선 사용하고, 없거나 미모델 kind 면
    actuator_id 키워드로 폴백 추정한다. 'fan' 키워드 폴백은 외기교환 환기팬을
    겨냥하나, circulation_fan 처럼 kind 가 명시되면(미모델) 채널에 잡히지 않는다.

    `vent_caps`(`vent_capacities`)가 있으면 vent 채널은 최댓값이 아니라 **풍량 비율**
    (`vent_channel_value`)이다 — 천창만 100 % 여는 것과 전부 100 % 여는 것이 다르다.
    없으면 예전처럼 최댓값(하위 호환).
    """
    result = {ch: 0.0 for ch in CHANNELS}
    kind_by_aid = kind_by_aid or {}
    # 차광막은 최적화 채널이 아니라 모델 **입력**이다(v2 — 일사 유입을 깎는다).
    # 개도(100 = 걷힘)의 평균. 차광막이 없으면 키를 두지 않는다(모델은 걷힘으로 본다).
    shades = [float(pct or 0.0) for aid, pct in cmds_pct.items()
              if kind_by_aid.get(aid) == 'shade']
    if shades:
        result['shade'] = sum(shades) / len(shades)
    # 보온커튼도 모델 입력이다(v3 — 외피 열손실·일사를 줄인다). 개도 100 = 걷힘.
    curtains = [float(pct or 0.0) for aid, pct in cmds_pct.items()
                if kind_by_aid.get(aid) == 'curtain']
    if curtains:
        result['curtain'] = sum(curtains) / len(curtains)
    for aid, pct in cmds_pct.items():
        kind = kind_by_aid.get(aid)
        ch = channel_for_kind(kind)
        # kind 가 없을 때만(미상) id 키워드로 폴백. 명시적 미모델 kind 는 폴백 안 함.
        if ch is None and kind is None:
            ch = _channel_from_id(aid)
        if ch is not None:
            result[ch] = max(result[ch], float(pct or 0.0))
    if vent_caps:
        result['vent'] = vent_channel_value(cmds_pct, vent_caps)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 환기 채널 세분 (MPC 보강 E 단계, 2026-09-22)
# ─────────────────────────────────────────────────────────────────────────────
#
# 모델의 vent 채널은 **시설 환기 능력 대비 실제 풍량 비율**(0~100)이다:
#
#     풍량   F = Σ_창 c_i·a_i + p(창 개도) · Σ_팬 c_j·a_j          [m³/s]
#     만수   C = max(Σ_창 c_i, Σ_팬 c_j)                           [m³/s]
#     vent  = 100 · F / C
#
#   c_i   창: 면적 × 0.5 m³/s/m²(베르누이 근사, `GreyboxParams.from_capacity_meta` 와 같다)
#         팬: 정격 풍량 m³/h ÷ 3600
#   p     팬 압력 유효도 — 창이 넓게 열리면 벽면 팬은 공기를 못 뺀다
#         (`effect_functions._exhaust_pressure_factor` 와 같은 식·같은 문턱)
#
# 예전에는 채널 값이 가장 많이 연 장치의 개도(최댓값)였고, MPC 는 같은 값을 모든 장치에
# 줬다. 그래서 천창·측창의 쓰임새 차이(부력)와 "창이 열리면 팬은 무력" 이 MPC 에 없었다.
# 채널 하나를 유지하는 것은 계획서 6절의 결정이다 — 채널을 나누면 학습할 계수가 늘고
# 현장 데이터로는 구분이 안 된다(천창·측창이 늘 같이 움직였다).

VENT_M3S_PER_M2 = 0.5        # 창 1 m² 를 다 열었을 때의 풍량 [m³/s]
DEFAULT_OPENING_M2 = 1.0     # 면적을 모르는 창
DEFAULT_FAN_M3H = 3000.0     # 정격을 모르는 팬(`_KIND_DEFAULT_RATED_M3H` 와 같다)
VENT_PRESSURE_F0 = 0.25      # `effect_functions.VENT_PRESSURE_F0` 와 같은 값
FAN_KINDS = frozenset({'exhaust_fan', 'intake_fan'})


class VentCap:
    """환기 장치 하나의 풍량 능력."""
    __slots__ = ('m3s', 'is_fan', 'form')

    def __init__(self, m3s: float, is_fan: bool, form: Optional[str] = None):
        self.m3s = float(m3s)
        self.is_fan = bool(is_fan)
        self.form = form

    def __repr__(self):
        return 'VentCap(%.2f, fan=%s, form=%s)' % (self.m3s, self.is_fan, self.form)


def vent_capacities(profiles) -> Dict[str, VentCap]:
    """vent 채널 장치별 풍량 능력 {actuator_id: VentCap}."""
    out: Dict[str, VentCap] = {}
    for p in profiles or []:
        kind = str(getattr(p, 'kind', '') or '').lower()
        if channel_for_kind(kind) != 'vent':
            continue
        if kind in FAN_KINDS:
            meta = getattr(p, 'capacity_meta', None) or {}
            m3h = float(meta.get('rated_m3h') or 0.0) or DEFAULT_FAN_M3H
            out[p.actuator_id] = VentCap(m3h / 3600.0, True)
        else:
            area = float(getattr(p, 'area_m2', None) or 0.0) or DEFAULT_OPENING_M2
            out[p.actuator_id] = VentCap(area * VENT_M3S_PER_M2, False,
                                         getattr(p, 'vent_form', None))
    return out


def _full_scale(caps: Dict[str, VentCap]) -> float:
    o = sum(c.m3s for c in caps.values() if not c.is_fan)
    f = sum(c.m3s for c in caps.values() if c.is_fan)
    return max(o, f)


def _pressure_factor(open_frac: float) -> float:
    return max(0.0, 1.0 - open_frac / VENT_PRESSURE_F0)


def vent_channel_value(cmds_pct: Dict[str, float],
                       caps: Dict[str, VentCap]) -> float:
    """장치별 개도 → vent 채널 값(풍량 비율 %)."""
    C = _full_scale(caps)
    if C <= 0.0:
        return 0.0
    o_cap = sum(c.m3s for c in caps.values() if not c.is_fan)
    o_flow = sum(c.m3s * float(cmds_pct.get(a, 0.0) or 0.0) / 100.0
                 for a, c in caps.items() if not c.is_fan)
    f_flow = sum(c.m3s * float(cmds_pct.get(a, 0.0) or 0.0) / 100.0
                 for a, c in caps.items() if c.is_fan)
    open_frac = (o_flow / o_cap) if o_cap > 0 else 0.0
    return max(0.0, min(100.0, 100.0 * (o_flow + _pressure_factor(open_frac) * f_flow) / C))


# 창 형태별 우선순위 — `effect_functions.VENT_FORM_GAIN` 을 그대로 쓴다(한 곳).
def _form_rank(form: Optional[str], indoor_hotter: bool) -> float:
    from ..effect_functions import VENT_FORM_GAIN
    if form not in ('ridge', 'side'):
        return 1.0
    return VENT_FORM_GAIN[(form, bool(indoor_hotter))]


def vent_reachable_pct(caps: Dict[str, VentCap], blocked=()) -> float:
    """막힌 장치를 빼고 낼 수 있는 최대 vent 채널 값 — MPC 의 채널 상한."""
    C = _full_scale(caps)
    if C <= 0.0:
        return 0.0
    free = {a: c for a, c in caps.items() if a not in set(blocked)}
    o = sum(c.m3s for c in free.values() if not c.is_fan)
    f = sum(c.m3s for c in free.values() if c.is_fan)
    return min(100.0, 100.0 * max(o, f) / C)


def distribute_vent(u: float, caps: Dict[str, VentCap], indoor_hotter: bool,
                    blocked=()) -> Dict[str, float]:
    """vent 채널 값 u(%) → 장치별 개도. `vent_channel_value` 의 역이다.

    - 창과 팬 중 **풍량이 큰 쪽 하나**로 낸다. 둘을 섞으면 창이 팬의 압력을 빼앗아
      같은 풍량에 장치만 더 돈다. 팬으로 낼 때는 창을 닫아 둔다(압력).
    - 창은 형태 우선순위 순서로 채운다 — 실내가 더우면 천창(부력이 돕는다)부터,
      실외가 더 더우면 측창부터. 같은 순위끼리는 같은 개도로 연다.
    - `blocked`(파킹 등)는 0 이다. 나머지가 그 몫을 대신 낸다.
    """
    out = {a: 0.0 for a in caps}
    C = _full_scale(caps)
    if C <= 0.0 or u <= 0.0:
        return out
    bl = set(blocked)
    free = {a: c for a, c in caps.items() if a not in bl}
    o = {a: c for a, c in free.items() if not c.is_fan}
    f = {a: c for a, c in free.items() if c.is_fan}
    o_cap = sum(c.m3s for c in o.values())
    f_cap = sum(c.m3s for c in f.values())
    need = max(0.0, min(100.0, u)) / 100.0 * C       # m³/s
    if f_cap > o_cap:
        a = min(100.0, 100.0 * need / f_cap)
        for k in f:
            out[k] = a
        return out
    if o_cap <= 0.0:
        return out
    ranks = sorted({_form_rank(c.form, indoor_hotter) for c in o.values()}, reverse=True)
    for r in ranks:
        grp = [k for k, c in o.items() if _form_rank(c.form, indoor_hotter) == r]
        cap = sum(o[k].m3s for k in grp)
        if need <= 0.0 or cap <= 0.0:
            break
        a = min(100.0, 100.0 * need / cap)
        for k in grp:
            out[k] = a
        need -= cap * a / 100.0
    return out


def vent_shares(caps: Dict[str, VentCap]) -> Dict[str, float]:
    """장치 하나를 다 열었을 때 채널에서 차지하는 몫(c_i / C) — greybox-PI 효과 배율."""
    C = _full_scale(caps)
    if C <= 0.0:
        return {}
    return {a: c.m3s / C for a, c in caps.items()}
