# coding=utf-8
# @manual geo/journal#dli
"""빛 측정 단위 환산. 순수 단위 환산이라 geo·journal·제어 어디에도 속하지
않는다 — 여러 계층이 **같은 표**를 봐야 하므로 모두 내려다보는 여기에 둔다.

⚠ 표가 두 벌이다. 위쪽 `LIGHT_UNITS_TO_PPFD`(W/m²→×2.06, 추정 표시 포함)는
  지도 일지의 DLI 가, 아래쪽 시스템 변환표 경로(`light_to_ppfd`·`light_to_wm2`,
  `config_devices_units.UNIT_CONVERSIONS`, W/m²→×2.02)는 제어·누적 추적이 쓴다.
  옮기면서 값은 바꾸지 않았다 — 하나로 합치는 것은 별도 결정이다.
"""

from collections import deque
from typing import Optional

from aot.utils.safe_eval import safe_eval

#: 단위 → `(PPFD 환산계수, 가정이 들어갔는가)`.
#:
#: DLI(mol/m²/일)는 PPFD(µmol/m²/s)를 하루 동안 적분한 값이다. 센서가 무엇을
#: 내느냐에 따라 환산이 **완전히 다르다**:
#:
#: - `umol_m2_s` — 이미 PPFD 다. **곱하면 안 된다.** 여기에 W/m² 계수를 곱하면
#:   값이 두 배가 되는데, 숫자가 그럴듯해서 틀린 줄 모른다.
#: - `W_m2` — 전천일사(단파 전체). PAR 은 그 45% 가량이고 PAR 1 W/m² ≈
#:   4.57 µmol/m²/s 이므로 ≈ ×2.06. **가정이 둘 들어간 값이다**(PAR 비율·광원이
#:   태양광이라는 것) — 그래서 화면이 "추정" 이라고 말해야 한다.
#: - `lux`/`klux` — 사람 눈 기준 밝기라 스펙트럼에 크게 좌우된다. 태양광 기준
#:   대략 ×0.0185 인데 LED 보광 아래서는 크게 틀린다. 쓰되 추정으로 표시한다.
#:
#: ⚠ 모르는 단위는 **환산하지 않는다.** 그럴듯한 계수를 지어내면 DLI 가 나오고,
#:   나오는 순간 사람은 그것을 믿는다.
LIGHT_UNITS_TO_PPFD = {
    'umol_m2_s': (1.0, False),
    'W_m2': (2.06, True),
    'lux': (0.0185, True),
    'klux': (18.5, True),
}


def ppfd_factor(unit):
    """빛 단위 → `(계수, 추정인가)`. 모르면 `(None, None)`."""
    found = LIGHT_UNITS_TO_PPFD.get(str(unit or ''))
    return found if found else (None, None)


# ── 광 단위 → PPFD(µmol/m²/s) 환산 ────────────────────────────────────────────
# DLI 는 PPFD 통적이 필요하다. 시스템의 internal['light'] 는 관례상 W/m²(일사량)이며
# (facility_sensors: _UNIT_BY_KEY['light']='W/m²', 실내 광센서 부재 시 실외 solar_wm2 보충).
# 환산은 시스템 단위 정의(config_devices_units.UNIT_CONVERSIONS)를 그대로 사용한다 —
# 별도 계수를 두지 않고 시스템 변환표를 단일 출처로 삼는다(W_m2→umol_m2_s ×2.02 등).
# ⚠ `W_m2` 는 **전천일사**다. PAR 센서는 `umol_m2_s` 로 등록해야 한다 —
# 근거는 config_devices_units 의 그 항목 주석 참조.

# PPFD 의 시스템 단위 키
_PPFD_UNIT_KEY = 'umol_m2_s'

# 입력 단위 문자열 → config_devices_units 단위 키 정규화
_LIGHT_UNIT_ALIASES = {
    'umol_m2_s': 'umol_m2_s', 'umol': 'umol_m2_s', 'umol/m2/s': 'umol_m2_s',
    'µmol/m²/s': 'umol_m2_s', 'ppfd': 'umol_m2_s', 'par': 'umol_m2_s',
    'w_m2': 'W_m2', 'w/m^2': 'W_m2', 'w/m²': 'W_m2', 'w/m2': 'W_m2', 'wm2': 'W_m2',
    'solar': 'W_m2', 'solar_wm2': 'W_m2', 'irradiance': 'W_m2', 'radiation': 'W_m2', 'light': 'W_m2',
    'lux': 'lux', 'lx': 'lux', 'klux': 'klux', 'full': 'full',
    'j_cm2': 'J_cm2', 'j/cm²': 'J_cm2', 'j/cm2': 'J_cm2',
}
# 단위 미상 시 기본 가정: 시스템 관례(W/m²).
_LIGHT_DEFAULT_UNIT_KEY = 'W_m2'


def _normalize_light_unit(unit: Optional[str]) -> str:
    if not unit:
        return _LIGHT_DEFAULT_UNIT_KEY
    return _LIGHT_UNIT_ALIASES.get(unit.strip().lower(), _LIGHT_DEFAULT_UNIT_KEY)


def _apply_eq(eqn: str, x: float) -> float:
    """config 의 변환식('x * 4.57' 등)을 적용. 신뢰된 상수식만 평가."""
    return float(safe_eval(eqn, {'x': float(x)}))


def _convert_via_system(value: float, from_key: str, to_key: str) -> Optional[float]:
    """config_devices_units.UNIT_CONVERSIONS 그래프를 BFS 로 따라가 단위 변환.

    변환 경로가 없으면 None. 시스템 변환표를 단일 출처로 사용한다.
    """
    if from_key == to_key:
        return value
    try:
        from aot.config_devices_units import UNIT_CONVERSIONS
    except Exception:
        return None
    # 인접 리스트: from -> [(to, eqn)]
    adj = {}
    for f, t, eqn in UNIT_CONVERSIONS:
        adj.setdefault(f, []).append((t, eqn))
    # BFS (값을 들고 전파)
    q = deque([(from_key, value)])
    seen = {from_key}
    while q:
        node, val = q.popleft()
        for nxt, eqn in adj.get(node, []):
            if nxt in seen:
                continue
            try:
                nval = _apply_eq(eqn, val)
            except Exception:
                continue
            if nxt == to_key:
                return nval
            seen.add(nxt)
            q.append((nxt, nval))
    return None


def light_to_ppfd(value: Optional[float], unit: Optional[str] = None) -> Optional[float]:
    """광 측정값을 PPFD(µmol/m²/s)로 환산 — 시스템 단위 변환표(UNIT_CONVERSIONS) 사용.

    단위 미상/미매핑이면 시스템 관례(W/m²)로 가정. 변환 경로가 없으면 원값 반환.
    이미 PPFD(umol_m2_s/ppfd)면 그대로 통과.
    """
    if value is None:
        return None
    from_key = _normalize_light_unit(unit)
    converted = _convert_via_system(value, from_key, _PPFD_UNIT_KEY)
    return converted if converted is not None else value


_WM2_UNIT_KEY = 'W_m2'


def light_to_wm2(value: Optional[float], unit: Optional[str] = None) -> Optional[float]:
    """광 측정값을 전천일사(W/m²)로 환산 — `light_to_ppfd` 와 **같은 변환표**.

    제어가 쓰는 광량 임계(`light_min`/`light_max`)와 차광막 추정이 전부 W/m²
    를 전제한다. 그런데 `_MEAS_LIGHT_NAMES` 는 `lux`·`ppfd`·`par` 도 광량으로
    받아들이므로, 그런 채널의 값을 그대로 쓰면 **자릿수가 다른 숫자를 임계와
    비교하게 된다** — 조도계 50,000 lux 가 50,000 W/m² 로 읽혀 차광막이 영구히
    닫힌다. 에러는 나지 않는다.

    ⚠ **변환표를 여기서 새로 만들지 말 것.** `_convert_via_system` 이 시스템
      변환표(`config_devices_units.UNIT_CONVERSIONS`)를 단일 출처로 쓴다 —
      두 벌이 되면 갈라지고, 갈라지면 화면과 제어가 다른 값을 본다.

    ⚠ 단위 미상이면 **바꾸지 않는다**(W/m² 로 가정). 모르는 것을 추측해서
      곱하면 원래 맞던 값까지 틀어진다.
    """
    if value is None:
        return None
    from_key = _normalize_light_unit(unit)
    converted = _convert_via_system(value, from_key, _WM2_UNIT_KEY)
    return converted if converted is not None else value
