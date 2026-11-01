# coding=utf-8
"""화면이 읽는 보정 요약 — 대지 창(기상원·예보 출처 지정 화면)의 '예보 보정' 줄이 쓴다 (D5, 설계 §4.3·§9.2).

새 설정 칸은 없다. 대지마다 한 가지 — 자동 / 항상 켬 / 끔(`fc_calibration_site.mode`) — 와, 채택·되돌림이 일어났다는
알림(`fc_cal_event`)을 읽고 확인 표시를 하는 것뿐이다. 이 모듈은 문장을 만들지 않는다(번역은 화면이 한다) — 상태 코드와
숫자만 낸다.
"""
from typing import Dict, List, Optional

from .common import (BANDS, KIND_D, KIND_H, ST_ADOPTED, ST_CANDIDATE, ST_DEFERRED, ST_FEW, ST_FORCED, ST_NO_FC,
                     ST_NO_OBS, ST_OFF, ST_REVERTED, USED_STATES, VARS)
from . import store

#: 변수 → 표시 단위 (시간별 강수는 시간 칸 합 mm)
UNITS = {(KIND_H, 'T'): '°C', (KIND_H, 'RH'): '%', (KIND_H, 'WS'): 'm/s', (KIND_H, 'SOL'): 'W/m²',
         (KIND_H, 'RAIN'): 'mm', (KIND_D, 'TMAX'): '°C', (KIND_D, 'TMIN'): '°C', (KIND_D, 'RAIN'): 'mm'}

#: 변수 상태 코드 — 화면이 말로 바꾼다
V_APPLIED = 'applied'            # 보정됨: 한 리드대라도 쓰는 중
V_COLLECTING = 'collecting'      # 원본: 아직 낫다는 근거가 모자라 모으는 중(후보·표본 부족·되돌림 포함)
V_NO_OBS = 'no_obs'              # 원본: 비교할 현장 관측이 없다
V_NO_FC = 'no_forecast'          # 원본: 대지에 맞는 예보 출처가 없다
V_OFF = 'off'                    # 원본: 이 대지는 보정을 끔
V_WAITING = 'waiting'            # 원본: 아직 점검한 적이 없다


def _variable_state(items: List[dict]) -> str:
    if not items:
        return V_WAITING
    sts = [e['status'] for e in items]
    if any(s in USED_STATES for s in sts):
        return V_APPLIED
    if all(s == ST_OFF for s in sts):
        return V_OFF
    if any(s in (ST_CANDIDATE, ST_REVERTED, ST_FEW, ST_DEFERRED) for s in sts):
        return V_COLLECTING
    if all(s == ST_NO_OBS for s in sts):
        return V_NO_OBS
    if all(s == ST_NO_FC for s in sts):
        return V_NO_FC
    return V_COLLECTING


def _best(items: List[dict]) -> Optional[dict]:
    """쓰는 항목 중 평균 오차가 가장 많이 줄어든 하나의 전후 오차(자세히 줄에 쓴다)."""
    best = None
    for e in items:
        if e['status'] not in USED_STATES:
            continue
        m = (e.get('meta') or {}).get('metrics') or {}
        if m.get('mae_raw') is None or m.get('mae_cal') is None:
            continue
        gain = m['mae_raw'] - m['mae_cal']
        if best is None or gain > best[0]:
            best = (gain, {'before': round(m['mae_raw'], 2), 'after': round(m['mae_cal'], 2)})
    return best[1] if best else None


def event_dict(ev) -> dict:
    d = ev.detail_dict()
    m = d.get('metrics') or {}
    return {'id': ev.unique_id, 'event': ev.event, 'kind': ev.kind, 'var': ev.var, 'band': ev.band, 'rev': ev.rev,
            'at': ev.created_at.isoformat() + 'Z' if ev.created_at else None, 'acked': bool(ev.acked),
            'before': None if m.get('mae_raw') is None else round(m['mae_raw'], 2),
            'after': None if m.get('mae_cal') is None else round(m['mae_cal'], 2),
            'unit': UNITS.get((ev.kind, ev.var))}


def site_view(site_id, events_limit=6) -> Dict[str, object]:
    """대지의 보정 요약.

    ``{'mode', 'rev', 'applied', 'state', 'variables': [{kind, var, unit, state, bands, gain}], 'events': [...],
    'unacked', 'last_run_at', 'days_needed'}`` — ``state`` 는 ``off | applied | collecting``(대지 전체 한 줄)."""
    row = store.site_row(site_id)
    mode = store.site_mode(site_id)
    rev = int(row.active_rev or 0) if row is not None else 0
    entries = store.entries_of_rev(site_id, rev) if rev and mode != 'off' else {}
    variables = []
    for kind in (KIND_H, KIND_D):
        for var in VARS[kind]:
            items = [entries[(kind, var, b)] for b in BANDS[kind] if (kind, var, b) in entries]
            if mode == 'off':
                state = V_OFF
            else:
                state = _variable_state(items)
            variables.append({'kind': kind, 'var': var, 'unit': UNITS.get((kind, var)), 'state': state,
                              'bands': [e['band'] for e in items if e['status'] in USED_STATES],
                              'gain': _best(items)})
    applied = any(v['state'] == V_APPLIED for v in variables)
    state = 'off' if mode == 'off' else 'applied' if applied else 'collecting'
    evs = store.recent_events(site_id, events_limit)
    return {'mode': mode, 'rev': rev if applied else 0, 'applied': applied, 'state': state,
            'variables': variables, 'events': [event_dict(e) for e in evs],
            'unacked': sum(1 for e in store.recent_events(site_id, 200, unacked_only=True)),
            'last_run_at': row.last_run_at if row is not None else None, 'days_needed': 14}


def ack_events(site_id) -> int:
    """대지의 확인 안 한 알림을 모두 확인 처리 → 처리 수."""
    from aot.aot_flask.extensions import db
    n = 0
    for ev in store.recent_events(site_id, 500, unacked_only=True):
        ev.acked = True
        n += 1
    if n:
        db.session.commit()
    return n
