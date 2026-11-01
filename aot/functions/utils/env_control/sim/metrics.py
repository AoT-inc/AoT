# coding=utf-8
"""
env_control/sim/metrics.py — 폐루프 추적 결과 → KPI.

입력은 하네스가 남기는 추적(trace) dict 하나다:

    meta       {'t0', 't_end', 'warmup_s', 'period', 'actuators': [ActuatorSpec dict...], ...}
    cycles     코디네이터 사이클마다 {t, sensor, truth, ext, target, guide, finals,
               emergency, gate_mask, gate_desc, acc(시설 누적량 사본), exc}
    fine       시설 세밀 기록(60 s) {'t', 'T', 'RH', 'VPD', 'open', 'fan', 'fog', 'rain', ...}
    fine_pos   {actuator_id: [물리 위치 %, ...]} (fine 과 같은 격자)
    dispatched [{t, aid, type, amount}] — 데몬으로 나간 그대로
    acc        끝 시점 시설 누적량

**참값으로 잰다** — 온·습도 KPI 는 시설 상태(fine)로 계산한다. 센서 고장 시나리오에서
제어기가 본 값(sensor)과 실제(truth)가 갈리는 것이 바로 보려는 것이기 때문이다.
워밍업(기본 1 시간)은 빼고 잰다. 누적량도 워밍업 끝 사본과의 차이다.
"""

from __future__ import annotations

import bisect
import math
from collections import Counter
from typing import Dict, List, Optional



def _psychro():
    """psychro 를 늦게 읽는다 — `compare.py` 는 이 파일을 패키지 밖에서 단독으로 싣는다.

    저장소 안: env_control.psychro / 하네스 컨테이너: 옆에 복사한 `_psychro.py`.
    """
    try:
        from .. import psychro as ps
        return ps
    except ImportError:
        pass
    try:
        from . import _psychro as ps      # type: ignore
        return ps
    except ImportError:
        import importlib.util
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        for cand in (os.path.join(here, '_psychro.py'),
                     os.path.join(here, '..', 'psychro.py')):
            if os.path.exists(cand):
                spec = importlib.util.spec_from_file_location('_envsim_psychro', cand)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
        raise

HEAT_THRESHOLDS = (35.0, 40.0, 45.0, 50.0)
PULSE_TYPES = ('sec', 'vol')
# 전천일사 W/m² → PPFD µmol/m²/s (`cumulative_tracker` 가 쓰는 시스템 변환표와 같은 값).
PPFD_PER_W = 2.02
KST_OFFSET_S = 9 * 3600.0


def _move_stats(series: List[tuple], min_step: float = 1.0) -> dict:
    """[(t, value)] → 이동 수·방향 반전 수."""
    moves = []
    prev = None
    for t, v in series:
        if v is None:
            continue
        if prev is not None and abs(v - prev) >= min_step:
            moves.append((t, 1 if v > prev else -1))
        prev = v
    rev = sum(1 for a, b in zip(moves, moves[1:]) if a[1] != b[1])
    return {'moves': len(moves), 'reversals': rev}


def _dispatch_stats(dispatched: List[dict], aid: str) -> dict:
    """데몬으로 나간 명령에서 장치 동작 횟수.

    값형(value/pwm): 직전과 1 %p 이상 다른 목표 = 한 번 움직임, 방향 반전 수.
    펄스형(sec/vol): 켬 명령 수(= 가동 시작 수)와 총 켬 시간.
    """
    vals = []
    starts = 0
    on_s = 0.0
    for d in dispatched:
        if d.get('aid') != aid:
            continue
        typ = d.get('type')
        if typ in PULSE_TYPES:
            starts += 1
            on_s += float(d.get('amount') or 0.0) if typ == 'sec' else 0.0
            continue
        v = 0.0 if typ == 'off' else d.get('amount')
        if v is None:
            continue
        vals.append((d['t'], float(v)))
    st = _move_stats(vals)
    st.update({'pulse_starts': starts, 'pulse_on_s': round(on_s, 1), 'sends': len(vals) + starts})
    return st


def _acc_delta(cycles: List[dict], acc_end: dict, t_from: float) -> dict:
    base = None
    for c in cycles:
        if c['t'] >= t_from and c.get('acc') is not None:
            base = c['acc']
            break
    if base is None:
        return dict(acc_end)
    return {k: acc_end.get(k, 0.0) - base.get(k, 0.0) for k in acc_end}


def _target_at(cycles: List[dict], ts: List[float], t: float) -> Optional[dict]:
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    return cycles[i]


def _daily_light(cycles: List[dict], t_from: float, acc_end: dict) -> List[tuple]:
    """시설 현지(KST) 날짜별 (받은 J/m², 스크린 없이 받았을 J/m²) — 워밍업 뒤만."""
    rows = [(c['t'], c.get('acc') or {}) for c in cycles if c['t'] >= t_from]
    rows.append((rows[-1][0] + 1.0 if rows else t_from, acc_end))
    days: Dict[int, list] = {}
    for (t0, a0), (_t1, a1) in zip(rows, rows[1:]):
        d = int((t0 + KST_OFFSET_S) // 86400)
        acc = days.setdefault(d, [0.0, 0.0])
        acc[0] += a1.get('light_crop_J', 0.0) - a0.get('light_crop_J', 0.0)
        acc[1] += a1.get('light_open_J', 0.0) - a0.get('light_open_J', 0.0)
    return [tuple(v) for _, v in sorted(days.items())]


def dli_fraction(daily: List[tuple], target_mol: Optional[float]) -> Optional[float]:
    """가장 나쁜 날의 DLI 몫 — 받은 광 ÷ min(스크린 없이 받았을 광, 목표). 낮이 짧은 날(1 MJ 미만) 제외.

    목표를 모르면 스크린 없이 받았을 광이 기준이다(= 스크린이 깎은 몫만 본다).
    """
    fr = []
    for crop, open_ in daily:
        if open_ < 1e6:
            continue
        ref = open_
        if target_mol:
            ref = min(open_, float(target_mol) / (PPFD_PER_W * 1e-6))
        fr.append(min(1.0, crop / ref) if ref > 0 else 1.0)
    return round(min(fr), 3) if fr else None


def dawn_drop(fine: dict, weather: dict, t_from: float) -> Optional[float]:
    """일출 ±1 시간 동안 실내 최저 온도가 일출 1 시간 전보다 얼마나 내려갔나 [°C] — 날 중 최대."""
    wt, ws = weather.get('t') or [], weather.get('solar') or []
    ft, fT = fine.get('t') or [], fine.get('T') or []
    if not wt or not ft:
        return None
    rises = [wt[i] for i in range(1, len(wt))
             if (ws[i - 1] or 0.0) <= 0.0 < (ws[i] or 0.0) and wt[i] - 3600.0 >= t_from]
    out = None
    for r in rises:
        i0 = bisect.bisect_left(ft, r - 3600.0)
        i1 = bisect.bisect_right(ft, r + 3600.0)
        if i0 >= len(ft) or i1 <= i0:
            continue
        drop = max(0.0, fT[i0] - min(fT[i0:i1]))
        out = drop if out is None else max(out, drop)
    return None if out is None else round(out, 2)



# ─────────────────────────────────────────────────────────────────────────────
# 극한 기상 지표 (storm 묶음) — 외기 시계열(trace['weather'])과 시설 세밀 기록을 맞대어 센다
# ─────────────────────────────────────────────────────────────────────────────

OPEN_EPS = 0.005            # 개구 면적 비율이 이 이상이면 '열려 있다' (0.5 %)
WIND_GATE_MS = 12.0         # 코디네이터 강풍 게이트 기본 문턱(`PreGateConfig.wind_threshold`)
GUST_HAZARD_MS = 15.0       # 돌풍 위험 문턱
RAIN_HAZARD_MMH = 2.0       # 위험한 비(KMA 15 분 0.5 mm = 2 mm/h — 코디네이터 강우 문턱과 같은 양)
HEAVY_RAIN_MMH = 10.0
STORM_PAD_S = 1800.0        # 폭풍 구간 앞뒤로 넓히는 시간


def _interp_series(ts: List[float], vs: List[float], t: float) -> float:
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return vs[0]
    if i >= len(ts) - 1:
        return vs[-1]
    f = (t - ts[i]) / (ts[i + 1] - ts[i]) if ts[i + 1] > ts[i] else 0.0
    return vs[i] + (vs[i + 1] - vs[i]) * f


def _trailing_mean(ts: List[float], vs: List[float], t: float, win_s: float, step_s: float = 60.0) -> float:
    n = max(1, int(win_s // step_s))
    return sum(_interp_series(ts, vs, t - step_s * k) for k in range(n)) / n


def _command_moves(dispatched: List[dict], aid: str, min_step: float = 1.0) -> List[tuple]:
    """한 값형 장치의 명령 이동 [(t, 방향 ±1, 새 값)] — 'off' 는 0."""
    out = []
    prev = None
    for d in dispatched:
        if d.get('aid') != aid or d.get('type') in PULSE_TYPES:
            continue
        v = 0.0 if d.get('type') == 'off' else d.get('amount')
        if v is None:
            continue
        v = float(v)
        if prev is not None and abs(v - prev) >= min_step:
            out.append((d['t'], 1 if v > prev else -1, v))
        prev = v
    return out


def _merge_windows(wins: List[List[float]]) -> List[List[float]]:
    wins = sorted(wins)
    out: List[List[float]] = []
    for a, b in wins:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _drop_events(ts: List[float], vs: List[float], win_s: float, k: float) -> tuple:
    """win_s 안에 k 이상 떨어진 사건 수(1 시간 안의 중복은 한 건)와 가장 큰 하강폭."""
    if len(ts) < 2:
        return 0, 0.0
    step = ts[1] - ts[0]
    n = max(1, int(round(win_s / step)))
    worst = 0.0
    events = 0
    last_ev = -1e18
    for i in range(len(vs) - n):
        d = vs[i] - vs[i + n]
        worst = max(worst, d)
        if d >= k and ts[i] - last_ev > 3600.0:
            events += 1
            last_ev = ts[i]
    return events, worst


def storm_kpis(trace: dict, t_from: float, idx: List[int]) -> dict:
    """극한 기상 지표. 외기 시계열이 없으면 빈 dict."""
    wx = trace.get('weather') or {}
    fine = trace.get('fine') or {}
    meta = trace.get('meta') or {}
    wt = wx.get('t') or []
    if not wt or not idx or 'wind' not in wx:
        return {}
    ft = [fine['t'][i] for i in idx]
    step_min = float(meta.get('fine_step_s', 60.0)) / 60.0
    step_h = step_min / 60.0
    T = [fine['T'][i] for i in idx]
    Tm = [fine['Tm'][i] for i in idx] if fine.get('Tm') else None
    pool = [fine['pool'][i] for i in idx] if fine.get('pool') else None
    open_ = [fine['open'][i] or 0.0 for i in idx]
    rain = [fine['rain'][i] or 0.0 for i in idx]
    fogv = [fine['fog'][i] or 0.0 for i in idx] if fine.get('fog') else [0.0] * len(idx)
    wind10 = [_trailing_mean(wt, wx['wind'], t, 600.0) for t in ft]
    gust = [_interp_series(wt, wx.get('gust') or wx['wind'], t) for t in ft]
    solar = [_interp_series(wt, wx.get('solar') or [0.0] * len(wt), t) for t in ft]
    rh_ext = [_interp_series(wt, wx['RH'], t) for t in ft] if wx.get('RH') else None

    out: Dict[str, object] = {}
    out['wind10_max'] = round(max(wind10), 1)
    out['gust_max'] = round(max(gust), 1)
    is_open = [o > OPEN_EPS for o in open_]
    out['max_wind_open'] = round(max((w for w, o in zip(wind10, is_open) if o), default=0.0), 1)
    out['max_gust_open'] = round(max((g for g, o in zip(gust, is_open) if o), default=0.0), 1)
    out['open_gust15_min'] = round(sum(1 for g, o in zip(gust, is_open) if o and g > GUST_HAZARD_MS)
                                   * step_min, 1)
    out['open_wind12_min'] = round(sum(1 for w, o in zip(wind10, is_open) if o and w >= WIND_GATE_MS)
                                   * step_min, 1)
    hazard = [(w >= WIND_GATE_MS or r >= RAIN_HAZARD_MMH) for w, r in zip(wind10, rain)]
    out['hazard_min'] = round(sum(hazard) * step_min, 1)
    out['open_in_hazard_min'] = round(sum(1 for h, o in zip(hazard, is_open) if h and o) * step_min, 1)
    out['heavy_rain_open_min'] = round(sum(1 for r, o in zip(rain, is_open)
                                           if r >= HEAVY_RAIN_MMH and o) * step_min, 1)
    out['rain_intrusion_mm'] = round(sum(r * o for r, o in zip(rain, open_)) * step_h, 2)

    # 기온 하강 속도 — 실내(참값)와 실외
    ev, worst = _drop_events(ft, T, 20 * 60.0, 3.0)
    out['T_drop_events'] = ev
    out['T_drop_max_20min'] = round(worst, 1)
    ext_T = [_interp_series(wt, wx['T'], t) for t in ft]
    ev, worst = _drop_events(ft, ext_T, 30 * 60.0, 8.0)
    out['ext_T_drop_events'] = ev
    out['ext_T_drop_max_30min'] = round(worst, 1)
    ev, worst = _drop_events(ft, ext_T, 20 * 60.0, 8.0)
    out['ext_T_drop_max_20min'] = round(worst, 1)

    # 서리 / 밤 젖음 / 건조
    out['frost_min'] = round(sum(1 for x in T if x < 0.0) * step_min, 1)
    out['frost_degmin'] = round(sum(max(0.0, -x) for x in T) * step_min, 1)
    out['crop_frost_min'] = round(sum(1 for x in Tm if x < 0.0) * step_min, 1) if Tm else None
    night = [s <= 0.0 for s in solar]
    pp = meta.get('plant_params') or {}
    thr = 0.02 * float(pp.get('floor_m2', 340.0)) * float(pp.get('crop_cover', 0.8))
    out['crop_wet_night_min'] = (round(sum(1 for p, n in zip(pool, night) if n and p > thr)
                                       * step_min, 1) if pool else None)
    nT = [x for x, n in zip(T, night) if n]
    nRH = [fine['RH'][i] for i, n in zip(idx, night) if n]
    out['T_night_mean'] = round(sum(nT) / len(nT), 2) if nT else None
    out['T_night_min'] = round(min(nT), 2) if nT else None
    out['RH_night_mean'] = round(sum(nRH) / len(nRH), 1) if nRH else None
    vpd = [fine['VPD'][i] for i in idx]
    out['VPD_max'] = round(max(vpd), 2)
    out['vpd_gt2_min'] = round(sum(1 for v in vpd if v > 2.0) * step_min, 1)
    out['RH_min'] = round(min(fine['RH'][i] for i in idx), 1)
    out['fog_in_ext_fog_min'] = (round(sum(1 for f, r in zip(fogv, rh_ext) if f > 0 and r >= 98.0)
                                       * step_min, 1) if rh_ext else None)

    # 폭풍 구간(돌풍 > 15 m/s 또는 호우 ≥ 10 mm/h, 앞뒤 30 분)의 환기창 방향 반전 속도
    storm = _merge_windows([[t - STORM_PAD_S, t + STORM_PAD_S + 60.0]
                            for t, g, r in zip(ft, gust, rain)
                            if g > GUST_HAZARD_MS or r >= HEAVY_RAIN_MMH])
    out['storm_hours'] = round(sum(b - a for a, b in storm) / 3600.0, 2)
    disp = [d for d in (trace.get('dispatched') or []) if d['t'] >= t_from]
    vents = [a['actuator_id'] for a in (meta.get('actuators') or []) if a.get('kind') == 'opening']
    moves = {aid: _command_moves(disp, aid) for aid in vents}
    rev_t = []
    for mv in moves.values():
        rev_t += [b[0] for a, b in zip(mv, mv[1:]) if a[1] != b[1]]
    rev_t.sort()
    all_moves = sorted(m[0] for mv in moves.values() for m in mv)
    best = 0.0
    for a, b in storm:
        L = min(3600.0, b - a)
        s0 = a
        while s0 + L <= b + 1e-6:
            n = bisect.bisect_right(rev_t, s0 + L) - bisect.bisect_left(rev_t, s0)
            best = max(best, n / (L / 3600.0))
            s0 += 300.0
    out['vent_rev_storm_max_per_h'] = round(best, 1) if storm else None
    out['vent_moves_storm'] = sum(bisect.bisect_right(all_moves, b) - bisect.bisect_left(all_moves, a)
                                  for a, b in storm) if storm else None

    # 위험(강풍·비) 중에 환기창을 더 열라는 명령 — 참값 기준
    up = 0
    for mv in moves.values():
        for t, d, v in mv:
            if d > 0:
                w = _trailing_mean(wt, wx['wind'], t, 600.0)
                r = _interp_series(wt, wx['rain'], t)
                if w >= WIND_GATE_MS or r >= RAIN_HAZARD_MMH:
                    up += 1
    out['open_up_hazard_cnt'] = up

    # 실외 관측소 두절(고장 주입) 구간에서 위험한데 열려 있던 시간 — 규칙 A 시험
    faults = ((meta.get('scenario_meta') or {}).get('faults')) or []
    t0 = float(meta.get('t0') or ft[0])
    outage = [(t0 + float(f.get('start_h') or 0.0) * 3600.0,
               t0 + float(f['end_h']) * 3600.0 if f.get('end_h') is not None else float('inf'))
              for f in faults if str(f.get('kind', '')).startswith('outdoor_')]
    if outage:
        out['outage_min'] = round(sum(1 for t in ft if any(a <= t < b for a, b in outage)) * step_min, 1)
        out['open_in_outage_hazard_min'] = round(sum(
            1 for t, h, o in zip(ft, hazard, is_open)
            if h and o and any(a <= t < b for a, b in outage)) * step_min, 1)
        # 두절 동안 열라는 명령(참값이 위험했는지와 무관 — 낡은 값으로 열면 안 된다)
        out['open_up_in_outage_cnt'] = sum(
            1 for mv in moves.values() for t, d, v in mv
            if d > 0 and any(a <= t < b for a, b in outage))
    else:
        out['outage_min'] = out['open_in_outage_hazard_min'] = out['open_up_in_outage_cnt'] = None
    return out


def summarize(trace: dict) -> dict:
    meta = trace.get('meta') or {}
    cycles = trace.get('cycles') or []
    fine = trace.get('fine') or {}
    fine_pos = trace.get('fine_pos') or {}
    dispatched = trace.get('dispatched') or []
    t0 = float(meta.get('t0') or (fine.get('t') or [0])[0])
    t_from = t0 + float(meta.get('warmup_s', 3600.0))
    step_min = float(meta.get('fine_step_s', 60.0)) / 60.0

    idx = [i for i, t in enumerate(fine.get('t') or []) if t >= t_from]
    out: Dict[str, object] = {'scenario': meta.get('scenario'), 'variant': meta.get('variant'),
                              'code': meta.get('code_rev')}
    if not idx:
        out['error'] = 'no samples after warmup'
        return out
    hours = len(idx) * step_min / 60.0
    out['hours'] = round(hours, 2)

    T = [fine['T'][i] for i in idx]
    RH = [fine['RH'][i] for i in idx]
    VPD = [fine['VPD'][i] for i in idx]
    out['T_max'] = round(max(T), 2)
    out['T_min'] = round(min(T), 2)
    out['T_mean'] = round(sum(T) / len(T), 2)
    out['RH_mean'] = round(sum(RH) / len(RH), 1)
    out['RH_max'] = round(max(RH), 1)
    out['VPD_mean'] = round(sum(VPD) / len(VPD), 3)
    for th in HEAT_THRESHOLDS:
        out[f'degmin_gt{int(th)}'] = round(sum(max(0.0, x - th) for x in T) * step_min, 1)
    out['min_gt40'] = round(sum(1 for x in T if x > 40.0) * step_min, 1)
    out['min_gt50'] = round(sum(1 for x in T if x > 50.0) * step_min, 1)

    # ── 목표·유도 범위 체류율 ────────────────────────────────────────────
    cts = [c['t'] for c in cycles]
    n_g = n_T = n_RH = n_vpd = n_vpd2 = n_Tt = n_tgt = 0
    for i in idx:
        c = _target_at(cycles, cts, fine['t'][i])
        if c is None:
            continue
        g = c.get('guide') or {}
        tg = c.get('target') or {}
        Ti, RHi, Vi = fine['T'][i], fine['RH'][i], fine['VPD'][i]
        if g.get('T_min') is not None:
            n_g += 1
            n_T += 1 if g['T_min'] <= Ti <= g['T_max'] else 0
            n_RH += 1 if g['RH_min'] <= RHi <= g['RH_max'] else 0
        if tg.get('VPD') is not None:
            n_tgt += 1
            tol = float(tg.get('VPD_tol') or 0.1)
            d = abs(Vi - float(tg['VPD']))
            n_vpd += 1 if d <= tol else 0
            n_vpd2 += 1 if d <= 2 * tol else 0
            if tg.get('T') is not None:
                n_Tt += 1 if abs(Ti - float(tg['T'])) <= float(tg.get('T_tol') or 1.0) else 0
    out['T_in_guide_pct'] = round(100.0 * n_T / n_g, 1) if n_g else None
    out['RH_in_guide_pct'] = round(100.0 * n_RH / n_g, 1) if n_g else None
    out['VPD_in_tol_pct'] = round(100.0 * n_vpd / n_tgt, 1) if n_tgt else None
    out['VPD_in_2tol_pct'] = round(100.0 * n_vpd2 / n_tgt, 1) if n_tgt else None
    out['T_in_target_tol_pct'] = round(100.0 * n_Tt / n_tgt, 1) if n_tgt else None
    vt = [c['target']['VPD'] for c in cycles
          if c['t'] >= t_from and (c.get('target') or {}).get('VPD') is not None]
    out['VPD_target_mean'] = round(sum(vt) / len(vt), 3) if vt else None

    # ── 잎 VPD(`leaf_vpd`) — 시설 열질량 온도 Tm 을 엽온으로 본다 ─────────────
    # 목표는 사람이 **정한** 숫자(`vpd_set`, 잎 기준이면 옮기기 전)다. 공기 기준 판과 잎 기준 판을
    # 같은 잣대(그 숫자를 잎 VPD 목표로 읽었을 때)로 견준다. Tm 은 바닥·작물 덩어리라 실제 잎보다
    # 느리다 — 절댓값보다 A/B 차이를 볼 것.
    n_l = n_l1 = n_l2 = 0
    lv = []
    if fine.get('Tm'):
        _ps = _psychro()
        for i in idx:
            c = _target_at(cycles, cts, fine['t'][i])
            leaf = _ps.leaf_vpd(fine['Tm'][i], fine['T'][i], fine['RH'][i])
            lv.append(leaf)
            vs = (c or {}).get('vpd_set')
            if vs is None:
                vs = ((c or {}).get('target') or {}).get('VPD')
            if vs is None:
                continue
            tol = float(((c or {}).get('target') or {}).get('VPD_tol') or 0.1)
            n_l += 1
            n_l1 += 1 if abs(leaf - float(vs)) <= tol else 0
            n_l2 += 1 if abs(leaf - float(vs)) <= 2 * tol else 0
    out['leafVPD_mean'] = round(sum(lv) / len(lv), 3) if lv else None
    out['leafVPD_in_tol_pct'] = round(100.0 * n_l1 / n_l, 1) if n_l else None
    out['leafVPD_in_2tol_pct'] = round(100.0 * n_l2 / n_l, 1) if n_l else None
    out['leaf_minus_air_C'] = (round(sum(fine['Tm'][i] - fine['T'][i] for i in idx) / len(idx), 2)
                               if fine.get('Tm') else None)
    fb = [c.get('vpd_basis') for c in cycles if c['t'] >= t_from and c.get('vpd_basis')]
    out['vpd_basis_fallback_cycles'] = sum(1 for b in fb if b == 'leaf_fallback') if fb else None

    # ── 비 + 열림, 분무 ──────────────────────────────────────────────────
    out['rain_open_min'] = round(sum(
        1 for i in idx if (fine['rain'][i] or 0) > 0.1 and (fine['open'][i] or 0) > 0.05)
        * step_min, 1)
    rain_min = sum(1 for i in idx if (fine['rain'][i] or 0) > 0.1) * step_min
    out['rain_min'] = round(rain_min, 1)
    out['open_mean_pct'] = round(100.0 * sum(fine['open'][i] for i in idx) / len(idx), 1)
    out['fan_on_pct'] = round(100.0 * sum(1 for i in idx if (fine['fan'][i] or 0) > 0)
                              / len(idx), 1)

    acc = _acc_delta(cycles, trace.get('acc') or {}, t_from)
    out['fog_water_kg'] = round(acc.get('fog_water_kg', 0.0), 1)
    out['fog_evap_kg'] = round(acc.get('fog_evap_kg', 0.0), 1)
    out['fog_wetting_kg'] = round(acc.get('fog_unevap_kg', 0.0), 1)
    out['fog_on_min'] = round(acc.get('fog_on_s', 0.0) / 60.0, 1)
    out['fog_while_RH90_min'] = round(acc.get('fog_while_humid_s', 0.0) / 60.0, 1)
    out['leaf_wet_min'] = round(acc.get('leaf_wet_s', 0.0) / 60.0, 1)
    out['cond_min'] = round(acc.get('cond_s', 0.0) / 60.0, 1)
    out['cond_kg'] = round(acc.get('cond_kg', 0.0), 1)
    out['crop_dew_min'] = round(acc.get('crop_dew_s', 0.0) / 60.0, 1)
    out['heat_cool_simul_min'] = round(acc.get('heat_cool_s', 0.0) / 60.0, 1)
    out['energy_kwh'] = round(sum(acc.get(k, 0.0) for k in (
        'heater_kwh', 'cooler_kwh', 'fan_kwh', 'fog_pump_kwh')), 2)

    # ── 장치 ────────────────────────────────────────────────────────────
    acts = {}
    for a in meta.get('actuators') or []:
        aid = a['actuator_id']
        st = _dispatch_stats([d for d in dispatched if d['t'] >= t_from], aid)
        fin = [(c['t'], (c.get('finals') or {}).get(aid, [None])[0])
               for c in cycles if c['t'] >= t_from]
        cs = _move_stats(fin)
        pos = fine_pos.get(aid) or []
        pos = [pos[i] for i in idx if i < len(pos)]
        acts[aid] = {
            'name': a.get('name'), 'kind': a.get('kind'),
            'moves_per_h': round(st['moves'] / hours, 2),
            'reversals_per_h': round(st['reversals'] / hours, 2),
            'pulse_starts_per_h': round(st['pulse_starts'] / hours, 2),
            'cmd_moves_per_h': round(cs['moves'] / hours, 2),
            'cmd_reversals_per_h': round(cs['reversals'] / hours, 2),
            'mean_pos': round(sum(pos) / len(pos), 1) if pos else None,
        }
    out['actuators'] = acts
    out['vent_reversals_per_h'] = round(sum(
        v['reversals_per_h'] for v in acts.values() if v['kind'] == 'opening'), 2)
    out['vent_moves_per_h'] = round(sum(
        v['moves_per_h'] for v in acts.values() if v['kind'] == 'opening'), 2)
    for kind in ('shade', 'curtain'):
        ks = [v for v in acts.values() if v['kind'] == kind]
        out[f'{kind}_moves_per_h'] = (round(sum(v['moves_per_h'] for v in ks), 2)
                                      if ks else None)
        out[f'{kind}_reversals_per_h'] = (round(sum(v['reversals_per_h'] for v in ks), 2)
                                          if ks else None)
    # 차광막 하루 최대 이동 수(물리 위치 기준, 1 %p 이상 바뀐 횟수를 KST 날짜별로)
    shade_day = None
    for a in meta.get('actuators') or []:
        if a.get('kind') != 'shade':
            continue
        pos = fine_pos.get(a['actuator_id']) or []
        per = Counter()
        prev = None
        moving = False
        for i in idx:
            if i >= len(pos):
                break
            v = pos[i]
            m = prev is not None and abs(v - prev) > 0.05
            if m and not moving:
                per[int((fine['t'][i] + KST_OFFSET_S) // 86400)] += 1
            moving = m
            prev = v
        n = max(per.values()) if per else 0
        shade_day = n if shade_day is None else max(shade_day, n)
    out['shade_moves_day_max'] = shade_day

    # ── 빛(DLI) ─────────────────────────────────────────────────────────
    daily = _daily_light(cycles, t_from, trace.get('acc') or {})
    days_n = max(1e-9, hours / 24.0)
    crop = sum(d[0] for d in daily)
    opn = sum(d[1] for d in daily)
    out['DLI_mol'] = round(crop * PPFD_PER_W * 1e-6 / days_n, 2) if daily else None
    out['DLI_frac_open'] = round(crop / opn, 3) if opn > 0 else None
    out['DLI_frac'] = dli_fraction(daily, meta.get('dli_target'))
    out['dli_target'] = meta.get('dli_target')
    out['dawn_drop_C'] = dawn_drop(fine, trace.get('weather') or {}, t_from)

    # ── 코디네이터 쪽 ───────────────────────────────────────────────────
    cyc = [c for c in cycles if c['t'] >= t_from]
    em = Counter()
    gates = Counter()
    for c in cyc:
        e = c.get('emergency') or [None, None]
        if e and e[0]:
            em[(e[1] or '').split(':')[0] or '?'] += 1
        for r in (c.get('gate_desc') or '').replace(';', ',').split(','):
            r = r.strip()
            if r:
                gates[r] += 1
    out['cycles'] = len(cyc)
    out['emergency_cycles'] = sum(em.values())
    out['emergency_reasons'] = dict(em)
    out['gate_reasons'] = dict(gates)
    out['cycle_exceptions'] = sum(1 for c in cyc if c.get('exc'))
    errs = [abs(c['sensor']['T'] - c['truth']['T']) for c in cyc
            if (c.get('sensor') or {}).get('T') is not None]
    out['sensor_T_abs_err_mean'] = round(sum(errs) / len(errs), 2) if errs else None
    out['sensor_missing_cycles'] = sum(1 for c in cyc
                                       if (c.get('sensor') or {}).get('T') is None)
    out.update(storm_kpis(trace, t_from, idx))
    return out


# 비교표에 싣는 KPI(열 이름, 키, 형식)
KPI_COLUMNS = [
    ('Tmax', 'T_max', '{:.1f}'),
    ('Tmean', 'T_mean', '{:.1f}'),
    ('T∈guide%', 'T_in_guide_pct', '{:.0f}'),
    ('RH∈guide%', 'RH_in_guide_pct', '{:.0f}'),
    ('VPD±tol%', 'VPD_in_tol_pct', '{:.0f}'),
    ('VPD±2tol%', 'VPD_in_2tol_pct', '{:.0f}'),
    ('leafVPD', 'leafVPD_mean', '{:.2f}'),
    ('leaf±tol%', 'leafVPD_in_tol_pct', '{:.0f}'),
    ('leaf±2tol%', 'leafVPD_in_2tol_pct', '{:.0f}'),
    ('°Cmin>35', 'degmin_gt35', '{:.0f}'),
    ('°Cmin>40', 'degmin_gt40', '{:.0f}'),
    ('min>50', 'min_gt50', '{:.0f}'),
    ('vent mv/h', 'vent_moves_per_h', '{:.2f}'),
    ('vent rev/h', 'vent_reversals_per_h', '{:.2f}'),
    ('rain&open min', 'rain_open_min', '{:.0f}'),
    ('fog kg', 'fog_water_kg', '{:.0f}'),
    ('wet kg', 'fog_wetting_kg', '{:.0f}'),
    ('fog@RH90 min', 'fog_while_RH90_min', '{:.0f}'),
    ('cond min', 'cond_min', '{:.0f}'),
    ('dew min', 'crop_dew_min', '{:.0f}'),
    ('fan on%', 'fan_on_pct', '{:.0f}'),
    ('kWh', 'energy_kwh', '{:.1f}'),
    ('emerg', 'emergency_cycles', '{:d}'),
    ('DLI_frac', 'DLI_frac', '{:.2f}'),
    ('shade mv/h', 'shade_moves_per_h', '{:.2f}'),
    ('shade mv/d', 'shade_moves_day_max', '{:d}'),
    ('curt rev/h', 'curtain_reversals_per_h', '{:.2f}'),
    ('dawn drop', 'dawn_drop_C', '{:.1f}'),
]


# 극한 기상 묶음 비교표 열(compare.py --storm)
STORM_COLUMNS = [
    ('Tmin', 'T_min', '{:.1f}'),
    ('Tmax', 'T_max', '{:.1f}'),
    ('wind10 max', 'wind10_max', '{:.0f}'),
    ('gust max', 'gust_max', '{:.0f}'),
    ('wind@open', 'max_wind_open', '{:.0f}'),
    ('gust@open', 'max_gust_open', '{:.0f}'),
    ('open&gust15 min', 'open_gust15_min', '{:.0f}'),
    ('open&w12 min', 'open_wind12_min', '{:.0f}'),
    ('hazard min', 'hazard_min', '{:.0f}'),
    ('open&hazard min', 'open_in_hazard_min', '{:.0f}'),
    ('rain&open min', 'rain_open_min', '{:.0f}'),
    ('intrusion mm', 'rain_intrusion_mm', '{:.1f}'),
    ('open↑hazard', 'open_up_hazard_cnt', '{:d}'),
    ('outage open&hz min', 'open_in_outage_hazard_min', '{:.0f}'),
    ('outage open↑', 'open_up_in_outage_cnt', '{:d}'),
    ('vent rev/h storm', 'vent_rev_storm_max_per_h', '{:.1f}'),
    ('Tdrop20 in', 'T_drop_max_20min', '{:.1f}'),
    ('Tdrop20 ext', 'ext_T_drop_max_20min', '{:.1f}'),
    ('frost min', 'frost_min', '{:.0f}'),
    ('crop frost min', 'crop_frost_min', '{:.0f}'),
    ('wet night min', 'crop_wet_night_min', '{:.0f}'),
    ('T night', 'T_night_mean', '{:.1f}'),
    ('RH night', 'RH_night_mean', '{:.0f}'),
    ('°Cmin>35', 'degmin_gt35', '{:.0f}'),
    ('VPDmax', 'VPD_max', '{:.1f}'),
    ('VPD>2 min', 'vpd_gt2_min', '{:.0f}'),
    ('fog@extfog min', 'fog_in_ext_fog_min', '{:.0f}'),
    ('cond min', 'cond_min', '{:.0f}'),
    ('open%', 'open_mean_pct', '{:.0f}'),
]


def fmt(v, f):
    if v is None:
        return '-'
    try:
        return f.format(v)
    except (ValueError, TypeError):
        return str(v)


__all__ = ['summarize', 'storm_kpis', 'KPI_COLUMNS', 'STORM_COLUMNS', 'fmt', 'HEAT_THRESHOLDS']
