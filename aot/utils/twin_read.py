# coding=utf-8
"""트윈 결과 읽기 — 지도 예측 제공자용 구획 묶음 (계약 docs/design/digital-twin.md §7-4·§8·§10.4).

`GET /api/twin/plots` 의 조립기다. Influx 를 모른다 — 읽어 온 행을 받아 **읽는 쪽 규칙**을
서버에서 한 번 적용한다: 구획마다 가장 최근 머리말을 먼저 보고, 유효(만료 전·status < 2)할 때만
그 발행의 곡선(`t0` 이후)을 싣는다. 만료·숨김 발행은 이유만 싣는다 — 마지막 값으로 채우지 않는다.

`env_twin_field` 는 같은 대상 시각을 덮어쓰므로 `t0` 앞의 점은 옛 발행이 남긴 값이다. 평가에도
표시에도 쓰지 않는다(§6.1) — 그래서 곡선은 최신 발행의 `t0` 부터 자른다.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from aot.twin import output as O

Rows = Mapping[Tuple[str, int], Sequence[Tuple[float, float]]]

M = O.FIELD_META
META_CHANNELS = (M['status'], M['valid_until'], M['horizon_d'], M['ensemble_size'],
                 M['sync_rmse_theta_1d'], M['coverage_80'], M['obs_age_s'], M['rain_src'],
                 M['irrigation_known'], M['rain_fc_days'], M['obs_n'])
_Q = O.FIELD_DAILY_Q
_E = O.FIELD_DAILY_EVENTS
#: 응답 이름 → 채널. 지도 제공자가 쓰는 것만 싣는다(필요하면 추가만 한다).
CURVE_CHANNELS: Dict[str, int] = {
    'theta_root_p10': _Q['theta_root'], 'theta_root_p50': _Q['theta_root'] + 1,
    'theta_root_p90': _Q['theta_root'] + 2,
    'theta_sensor_p50': _Q['theta_sensor'] + 1,
    'p_water_deficit': _E['water_deficit'], 'p_water_deficit_severe': _E['water_deficit_severe'],
    'p_waterlogging': _E['waterlogging'],
}
META_NAMES = {v: k for k, v in M.items()}


def latest_meta(rows: Rows, device_id: str, channels: Sequence[int] = META_CHANNELS) -> Optional[Dict[str, float]]:
    """가장 최근 발행 머리말(`t0` = status 채널의 마지막 시각). 같은 `t0` 의 값만 모은다.

    `channels` 는 읽을 머리말 채널(기본 `META_CHANNELS`) — 그래프는 기준선 채널을 더해서 부른다."""
    st = rows.get((device_id, M['status'])) or []
    if not st:
        return None
    t0 = st[-1][0]
    meta = {'t0': float(t0)}
    for ch in channels:
        for t, v in rows.get((device_id, ch)) or []:
            if abs(t - t0) < 1.0:
                meta[META_NAMES[ch]] = float(v)
    return meta


def usable(meta: Optional[Mapping[str, float]], now: float) -> Tuple[bool, str]:
    if meta is None:
        return False, 'no_publication'
    if 'valid_until' not in meta or 'status' not in meta:
        return False, 'bad_publication'
    if int(meta['status']) >= 2:                  # 즉시 만료가 정상이라 이유는 상태로 적는다(§7-3)
        return False, 'status_%d' % int(meta['status'])
    if now > meta['valid_until']:
        return False, 'expired'
    return True, ''


def plots_bundle(plot_ids: Sequence[str], meta_rows: Rows, curve_rows: Rows, now: float,
                 start: float, end: float) -> List[Dict[str, object]]:
    """구획마다 {plot_uuid, usable, reason, meta, days, <곡선 이름>: [값]}.

    days 는 최신 발행 `t0` 이후, 하루 구간이 [start, end] 와 겹치는 일 격자 시각(모든 곡선에 값이 있는 날만).
    """
    out = []
    for pid in plot_ids:
        meta = latest_meta(meta_rows, pid)
        ok, why = usable(meta, now)
        rec: Dict[str, object] = {'plot_uuid': pid, 'usable': ok, 'reason': why, 'meta': meta}
        if ok:
            # 일 격자 점은 그날 00 시 — 하루 구간 [d, d+1 일) 이 창과 겹치면 싣는다(창이 낮에 시작해도 오늘이 빠지지 않게)
            lo = max(start - 86400.0 + 1.0, meta['t0'] - 1.0)
            series = {name: {t: v for t, v in (curve_rows.get((pid, ch)) or []) if lo <= t <= end}
                      for name, ch in CURVE_CHANNELS.items()}
            need = ('theta_root_p10', 'theta_root_p50', 'theta_root_p90')
            days = sorted(set.intersection(*(set(series[n]) for n in need))) if all(
                series[n] for n in need) else []
            rec['days'] = days
            for name, s in series.items():
                rec[name] = [s.get(t) for t in days]
            if not days:
                rec['usable'], rec['reason'] = False, 'no_curve_in_window'
        out.append(rec)
    return out
