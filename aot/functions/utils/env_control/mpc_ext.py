# coding=utf-8
"""
env_control/mpc_ext.py — MPC 가 예측에 쓰는 외기 시퀀스(MPC 보강 F 단계, 2026-09-22).

예전 MPC 는 지평 동안 외기가 **지금 값 그대로** 라고 봤다. 지평이 10사이클이면 사이클
10분 설치에서 100분이다 — 해 질 녘 일사가 0 으로 떨어지는 것도, 한낮으로 가며 기온이
오르는 것도 모른 채 최적화했다.

## 외기 온도·습도 — 예보의 **변화량**만 쓴다

    T_ext(t) = T_ext(지금, 실측) + [F_T(t) − F_T(지금)]

F 는 예보 곡선(시간별 점을 직선으로 잇는다). 예보 값 자체를 쓰지 않는 이유: 예보는
격자 평균이고 실측은 이 시설의 기상대다 — 둘의 차(편향)가 수 °C 여서 그대로 쓰면
지평 첫 칸에서 외기가 계단처럼 뛴다. 변화량은 편향을 지운다.

예보가 없거나, 발표된 지 `STALE_H` 시간을 넘었거나, 지평을 다 덮지 못하면 **지금 값
유지**(예전 동작)다 — 모르는 구간을 지어내지 않는다.

## 일사 — 맑은 날 곡선 × 지금의 맑음 정도

기상청 단기예보에는 일사가 없다. 대신 태양 위치로 맑은 날 일사 C(t) 를 계산하고,
지금 실측이 그 몇 할인지(맑음 정도 k = S / C)를 지평 동안 유지한다:

    S(t) = k · C(t)

해가 낮으면(C < `K_MIN_CLEAR`) k 를 잴 수 없다 — 그때는 마지막으로 잰 k 를 쓰고, 그것도
없으면 지금 일사 유지다. 구름이 갑자기 끼는 것은 모른다(그것은 일사 선행 예측의 몫이고,
그쪽은 아직 기록만 한다). 이 방식은 좌표만 있으면 되므로 한국 밖에서도 돈다.

풍속·CO₂ 는 지금 값 유지.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, List, Optional, Tuple

STALE_H = 6.0          # 발표 뒤 이 시간이 지난 예보는 쓰지 않는다(AI 도구와 같은 기준)
K_MIN_CLEAR = 50.0     # W/m² — 맑은 날 일사가 이보다 작으면 맑음 정도를 재지 않는다
K_MAX = 1.2            # 구름 가장자리 반사로 맑은 날보다 잠깐 밝을 수 있다

Curve = List[Tuple[float, Optional[float], Optional[float]]]   # (epoch, T, RH)


def kma_curve(data: dict, now_epoch: float) -> Optional[Curve]:
    """기상청 단기예보 파일(`forecast.json`) → 시간별 (epoch, T, RH). 못 쓰면 None.

    파일의 오프셋은 **파일을 쓴 시각(`now`, 장치 벽시계 `tz`) 기준**이다 — 지금 기준이
    아니다. 파일이 3시간 전에 쓰였으면 오프셋 0 은 3시간 전이다.
    """
    if not data:
        return None
    fc = data.get('forecasts') or {}
    anchor = _parse_local(data.get('now'), data.get('tz'))
    pub = _parse_local(data.get('pub_dt'), data.get('tz'))
    if not fc or anchor is None:
        return None
    if pub is not None and (now_epoch - pub) / 3600.0 > STALE_H:
        return None
    pts: Curve = []
    for k, v in fc.items():
        try:
            off = int(k)
        except (TypeError, ValueError):
            continue
        if not isinstance(v, dict):
            continue
        T = _num(v.get('TMP'))
        RH = _num(v.get('REH'))
        if T is None and RH is None:
            continue
        pts.append((anchor + off * 3600.0, T, RH))
    pts.sort(key=lambda p: p[0])
    return pts if len(pts) >= 2 else None


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _parse_local(stamp, tz) -> Optional[float]:
    """'YYYYmmddHHMM' 벽시계 + 시간대 이름 → epoch. 시간대가 없으면 기상청(KST)."""
    if not stamp:
        return None
    try:
        import pytz
        naive = datetime.strptime(str(stamp), '%Y%m%d%H%M')
        zone = pytz.timezone(str(tz) if tz else 'Asia/Seoul')
        return zone.localize(naive).timestamp()
    except Exception:
        return None


def _interp(curve: Curve, t: float, idx: int) -> Optional[float]:
    """곡선의 t 시점 값(직선 보간). 범위 밖이거나 이웃 점에 값이 없으면 None."""
    if t < curve[0][0] or t > curve[-1][0]:
        return None
    for (t0, *v0), (t1, *v1) in zip(curve, curve[1:]):
        if t0 <= t <= t1:
            a, b = v0[idx], v1[idx]
            if a is None or b is None:
                return None
            f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            return a + f * (b - a)
    return None


def build_ext_seq(base: dict, horizon: int, cycle_sec: float, now_epoch: float,
                  curve: Optional[Curve] = None,
                  clear_sky: Optional[Callable[[float], Optional[float]]] = None,
                  k_memory: Optional[float] = None) -> Tuple[List[dict], dict]:
    """외기 시퀀스와 무엇을 썼는지(info).

    `base`: 지금 외기 {T_ext, RH_ext, CO2_ext, solar, wind}.
    각 칸은 그 사이클의 **가운데 시각** 값이다.
    `clear_sky(epoch)` → 맑은 날 일사 W/m²(좌표를 모르면 None 을 돌려준다).
    info: {'temp': 'forecast'|'persistence', 'solar': 'clear_sky'|'persistence', 'k': ...}
    """
    H = max(1, int(horizon))
    times = [now_epoch + (i + 0.5) * float(cycle_sec) for i in range(H)]
    seq = [dict(base) for _ in range(H)]
    info = {'temp': 'persistence', 'solar': 'persistence', 'k': None}

    # ── 온·습도: 예보 변화량 ──────────────────────────────────────────────
    if curve:
        for idx, key, lo, hi in ((0, 'T_ext', -60.0, 60.0), (1, 'RH_ext', 0.0, 100.0)):
            now_v = _interp(curve, now_epoch, idx)
            fut = [_interp(curve, t, idx) for t in times]
            b = base.get(key)
            if b is None or now_v is None or any(v is None for v in fut):
                continue
            for s, v in zip(seq, fut):
                s[key] = max(lo, min(hi, float(b) + (v - now_v)))
            info['temp'] = 'forecast'

    # ── 일사: 맑은 날 곡선 × 맑음 정도 ──────────────────────────────────────
    S = base.get('solar')
    if clear_sky is not None and S is not None:
        c_now = clear_sky(now_epoch)
        k = None
        if c_now is not None and c_now >= K_MIN_CLEAR:
            k = max(0.0, min(K_MAX, float(S) / c_now))
        elif c_now is not None and k_memory is not None:
            k = k_memory
        if k is not None:
            cs = [clear_sky(t) for t in times]
            if all(c is not None for c in cs):
                for s, c in zip(seq, cs):
                    s['solar'] = k * c
                info['solar'] = 'clear_sky'
                info['k'] = round(k, 3)
    return seq, info


__all__ = ['STALE_H', 'K_MIN_CLEAR', 'kma_curve', 'build_ext_seq']
