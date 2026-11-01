# coding=utf-8
"""VPD 목표의 기준(공기/잎) — 잎 VPD 목표를 공기 VPD 목표로 옮기는 정본은 **이 모듈 한 곳**이다
(2026-10-09).

## 왜 있는가

작물에게 의미가 있는 것은 **잎** VPD 다 — 증산을 미는 힘은 잎 안(잎 온도에서 포화)과 둘레 공기의
수증기압 차이다(`psychro.leaf_vpd`). 공기 VPD 는 그 참고값이다. 그런데 제어의 내부 수량은 공기 VPD
다: 효과 모델·`decompose_vpd_to_T_RH`·단계 가이드가 모두 공기 VPD 로 되어 있고, 잎 온도는 대부분의
온실에서 재지 않는다.

그래서 내부 수량은 그대로 두고 **목표만** 옮긴다. 잎 VPD 목표가 v 이고 지금 잎이 T_leaf, 공기가
T_air 이면, 같은 뜻의 공기 VPD 목표는

    v_air = v + svp(T_air) − svp(T_leaf)          (`psychro.air_target_from_leaf`)

이다. 잎이 공기보다 차면 공기 목표가 올라가고, 따뜻하면 내려간다. 허용 오차(kPa)는 그대로 둔다.

## 의미 — 잰 엽온일 때만 옮긴다

    vpd_target_basis = air (기본)          → 목표는 공기 VPD 그대로 (종전과 완전히 같다)
    vpd_target_basis = leaf, 엽온이 유효   → 목표를 이 사이클의 온도차로 옮긴다 (TARGET_LEAF)
    vpd_target_basis = leaf, 엽온이 없다   → **이 사이클만** 공기 기준 (TARGET_LEAF_FALLBACK)

⚠ **엽온을 고정 오프셋(기온 − 1.5 °C 등)으로 어림해 옮기지 않는다.** 해 드는 낮에 기공이 닫힌 잎은
  공기보다 따뜻하고 맑은 밤에는 차다 — 부호도 크기도 상황마다 다르다. 어림값으로 옮기면 잎 기준이라는
  이름만 붙은 다른 공기 목표가 된다. 에너지 수지로 엽온을 추정하는 날이 오면 `LeafReading` 을 만드는
  쪽(코디네이터 `_read_leaf_temperature`)에 추정값을 넣는 자리가 있다 — 이 모듈은 출처를 묻지 않고
  `status` 만 본다.

"유효" 는 넷이다: 신선하다(`measurement_freshness`) · 범위 안이다(`sensor_status.check_value('T')`) ·
멈추지 않았다(`FrozenTracker`) · 공기와의 차이가 `LEAF_AIR_DELTA_MAX_C` 이내다(IR 센서가 잎 대신 바닥·
골조·하늘을 보면 차이가 터무니없이 커진다 — 그 값을 그대로 옮기면 목표가 수 kPa 움직인다).

## 바닥

잎이 공기보다 충분히 따뜻하면 공기를 포화시켜도 잎 VPD 가 목표를 넘는다 — 옮긴 공기 목표가 0 이하가
된다. 그 목표는 닿을 수 없고, 쫓으면 분무가 포화를 향해 끝없이 돈다. `AIR_TARGET_MIN_KPA` 로 자르고
`clamped` 로 남긴다.
"""
# @manual ai/env-control#leaf-vpd
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import psychro
from . import sensor_status as _ss

BASIS_AIR = 'air'
BASIS_LEAF = 'leaf'
_BASES = (BASIS_AIR, BASIS_LEAF)

# CH94 에 그대로 기록된다 — 숫자를 바꾸면 옛 기록이 뜻을 잃는다.
TARGET_AIR = 0              # 공기 기준(설정이 air)
TARGET_LEAF = 1             # 잎 기준 — 잰 엽온으로 공기 목표로 옮겼다
TARGET_LEAF_FALLBACK = 2    # 잎 기준인데 이번 사이클은 엽온이 없어 공기 기준으로 돌았다

STATE_LABEL = {
    TARGET_AIR: 'air',
    TARGET_LEAF: 'leaf',
    TARGET_LEAF_FALLBACK: 'leaf_fallback',
}

# 엽온 판독 상태 — `sensor_status` 의 여섯 상태에 둘을 더한다.
LEAF_UNBOUND = 'unbound'          # 엽온 신호를 묶지 않았다
LEAF_IMPLAUSIBLE = 'implausible'  # 값은 그럴듯한데 공기와 너무 다르다 — 잎을 보고 있지 않다

# 잎–공기 온도차가 이보다 크면 잎이 아닌 것을 재고 있다고 본다. 강한 일사에 기공이 닫힌 잎도
# 공기보다 5~8 °C 더 따뜻해지는 정도다(문헌의 상한 쪽). 10 °C 는 오탐을 피하는 쪽으로 넉넉하다.
LEAF_AIR_DELTA_MAX_C = 10.0

# 옮긴 공기 목표의 바닥 [kPa] — 25 °C 에서 RH ≈ 97 %. 이보다 낮은 공기 목표는 결로만 부른다.
AIR_TARGET_MIN_KPA = 0.1


@dataclass
class LeafReading:
    """이번 사이클의 엽온 판독. `status` 가 `valid` 일 때만 `temp`(°C)를 믿는다."""
    temp: Optional[float] = None
    status: str = LEAF_UNBOUND


@dataclass
class VpdTargetBasis:
    """목표 기준 판정 결과 — 요약·기록·화면이 같은 것을 본다."""
    basis: str = BASIS_AIR                  # 설정
    applied: str = BASIS_AIR                # 이번 사이클에 목표가 걸린 쪽
    state: int = TARGET_AIR                 # CH94
    target: Optional[float] = None          # 설정된 목표(설정 기준의 kPa)
    air_target: Optional[float] = None      # 제어가 따르는 공기 VPD 목표
    leaf_vpd: Optional[float] = None        # 잰 엽온의 잎 VPD(엽온이 유효할 때만)
    leaf_temp: Optional[float] = None
    leaf_status: str = LEAF_UNBOUND
    clamped: bool = False                   # 옮긴 공기 목표가 바닥에 잘렸다

    def as_summary(self) -> dict:
        def _r(v, n=3):
            return None if v is None else round(float(v), n)
        return {
            'basis': self.basis,
            'applied': self.applied,
            'state': STATE_LABEL.get(self.state, 'air'),
            'target': _r(self.target),
            'air_target': _r(self.air_target),
            'leaf_vpd': _r(self.leaf_vpd),
            'leaf_temp': _r(self.leaf_temp, 2),
            'leaf_status': self.leaf_status,
            'clamped': bool(self.clamped),
        }


def normalise_basis(value) -> str:
    """알 수 없는 값은 기본(air) — 저장 경로가 검증을 지나지 않아도 판정이 서야 한다."""
    v = str(value or '').strip().lower()
    return v if v in _BASES else BASIS_AIR


def classify_leaf(temp, T_air) -> LeafReading:
    """읽은 엽온 하나(°C, 신선도·멈춤은 호출자가 이미 거른 값)를 범위·온도차로 가른다."""
    status, val = _ss.check_value('T', temp)
    if status != _ss.VALID or val is None:
        return LeafReading(None, _ss.OUT_OF_RANGE)
    if T_air is not None:
        try:
            if abs(val - float(T_air)) > LEAF_AIR_DELTA_MAX_C:
                return LeafReading(None, LEAF_IMPLAUSIBLE)
        except (TypeError, ValueError):
            pass
    return LeafReading(val, _ss.VALID)


def resolve(target: Optional[float], basis, T_air: Optional[float],
            RH: Optional[float], leaf: Optional[LeafReading]) -> VpdTargetBasis:
    """설정 목표 → 제어가 따를 공기 VPD 목표.

    `target` 이 없거나 0 이하이면 옮길 것이 없다(`air_target` None) — 상태는 그래도 매긴다.
    잎 VPD(`leaf_vpd`)는 기준과 무관하게 엽온이 유효하면 계산해 둔다(화면·기록용).
    """
    basis = normalise_basis(basis)
    leaf = leaf or LeafReading()
    leaf_ok = (leaf.status == _ss.VALID and leaf.temp is not None
               and T_air is not None and RH is not None)
    leaf_vpd = None
    if leaf_ok:
        leaf_vpd = psychro.leaf_vpd(float(leaf.temp), float(T_air), float(RH))
    has_target = target is not None and float(target) > 0.0
    res = VpdTargetBasis(
        basis=basis, target=(float(target) if has_target else None),
        leaf_vpd=leaf_vpd, leaf_temp=(float(leaf.temp) if leaf_ok else None),
        leaf_status=leaf.status)
    if basis == BASIS_AIR:
        res.air_target = res.target
        return res
    if not leaf_ok:
        res.state = TARGET_LEAF_FALLBACK
        res.air_target = res.target
        return res
    res.state = TARGET_LEAF
    res.applied = BASIS_LEAF
    if has_target:
        v = psychro.air_target_from_leaf(float(target), float(T_air), float(leaf.temp))
        if v < AIR_TARGET_MIN_KPA:
            v = AIR_TARGET_MIN_KPA
            res.clamped = True
        res.air_target = v
    return res


def readout_from_summary(summary) -> Optional[dict]:
    """사이클 요약(`summary_json`) → AI 가 읽는 VPD 현황. 요약에 VPD 가 없으면 None.

    AI 도구(`get_control_state`)와 AI 요약이 같은 모양을 쓰도록 여기 한 곳이다. 화면의
    [공기 VPD] / [잎 VPD] 와 같은 약속이다.

      air_kpa        공기 VPD — 걸러진 실내 온·습도에서 계산한 값(제어가 쓰는 쪽). 늘 공기다.
      leaf_kpa       잎 VPD — **잰 엽온이 유효할 때만** 싣는다. 없으면 키 자체가 없다
                     (고정 오프셋 어림값을 잎 VPD 로 내놓지 않는다).
      leaf_temp_c    그 엽온.
      target_basis   설정된 목표의 기준(air|leaf), target_applied 이번 사이클에 목표가 실제로
                     걸린 쪽(잎 기준인데 엽온이 없으면 air). 잎 기준 판정이 있었던 사이클에만.
      target_kpa / air_target_kpa   잎 기준일 때만 — 사람이 정한 잎 목표와, 제어가 실제로 따른
                     (옮긴) 공기 목표. 잎 기준이면 요약의 `targets.vpd` 는 후자다.
    """
    if not isinstance(summary, dict):
        return None

    def _r(v, n=2):
        try:
            return None if v is None else round(float(v), n)
        except (TypeError, ValueError):
            return None

    out: dict = {}
    air = _r((summary.get('photo') or {}).get('vpd'))
    if air is not None:
        out['air_kpa'] = air
    vt = summary.get('vpd_target')
    if isinstance(vt, dict):
        leaf = _r(vt.get('leaf_vpd'))
        if leaf is not None:
            out['leaf_kpa'] = leaf
            lt = _r(vt.get('leaf_temp'), 1)
            if lt is not None:
                out['leaf_temp_c'] = lt
        if vt.get('basis'):
            out['target_basis'] = vt.get('basis')
            out['target_applied'] = vt.get('applied') or BASIS_AIR
        if vt.get('basis') == BASIS_LEAF:
            for src, dst in (('target', 'target_kpa'), ('air_target', 'air_target_kpa')):
                v = _r(vt.get(src))
                if v is not None:
                    out[dst] = v
    return out or None


def describe(res: VpdTargetBasis) -> str:
    """사람이 읽는 한 줄(전환 로그용)."""
    if res.state == TARGET_LEAF:
        if res.target is None:
            return '잎 VPD 기준 — 엽온 %.1f °C (목표 없음)' % res.leaf_temp
        return ('잎 VPD 기준 — 엽온 %.1f °C, 잎 목표 %.2f kPa → 공기 목표 %.2f kPa%s'
                % (res.leaf_temp, res.target, res.air_target,
                   ' (바닥에 잘림)' if res.clamped else ''))
    if res.state == TARGET_LEAF_FALLBACK:
        return ('잎 VPD 기준인데 엽온을 쓸 수 없다(%s) — 이번 사이클은 같은 숫자를 공기 VPD '
                '목표로 쓴다' % _LEAF_STATUS_KO.get(res.leaf_status, res.leaf_status))
    return '공기 VPD 기준'


_LEAF_STATUS_KO = {
    LEAF_UNBOUND: '엽온 신호 미지정',
    LEAF_IMPLAUSIBLE: '공기와의 차이가 %.0f °C 를 넘음' % LEAF_AIR_DELTA_MAX_C,
    _ss.STALE: '값이 오래됨',
    _ss.MISSING: '값 없음',
    _ss.OUT_OF_RANGE: '범위 밖',
    _ss.FROZEN: '값이 멈춤',
}
