# coding=utf-8
"""대지 하나의 보정 점검 — 읽기 → 짝짓기 → 맞춤 → 전진 검증 → 채택/되돌림 → 저장·성적·알림 (설계 §4).

`calibrate_site` 한 번이 (종류, 변수, 리드대) 전부를 새로 점검한다. 변수 하나(IO + 검증)마다 시간 제한(`Params.time_budget_s`)을 걸어,
넘으면 그 변수는 건너뛰고 **이전 상태를 그대로 둔다**(`deferred`, 다음 점검에서 다시). 한 대지씩만 돈다(호출하는 쪽 `job` 이 보장).

읽기는 `Sources`(기본 `InfluxSources`), 쓰기는 `store` 를 거친다. 시험은 둘을 바꿔 끼운다.
"""
import logging
import time
from typing import List, Optional

from . import pairing, store
from .common import (BANDS, DAY_S, HOUR_S, KIND_H, Ctx, Params, ST_DEFERRED, ST_FEW, ST_NO_FC, ST_NO_OBS, ST_OFF,
                     ST_REVERTED, USED_STATES, VARS, KIND_D)
from .methods import method_for
from .sources import OBS_KEY
from .validate import Timeout, decide, forward_validate, seed_of, summarize

logger = logging.getLogger('aot.fc_cal')


def _clean(x):
    """JSON 에 못 쓰는 값(NaN·inf)을 None 으로 — 지표 사전·요약을 안전하게."""
    if isinstance(x, float):
        return None if x != x or x in (float('inf'), float('-inf')) else round(x, 6)
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def _entry(kind, var, band, status, reason, **kw):
    e = {'kind': kind, 'var': var, 'band': band, 'status': status, 'reason': reason, 'method': None,
         'coef': None, 'meta': {}, 'window_start': None, 'window_end': None}
    e.update(kw)
    return e


def _all_bands(kind, var, status, reason, **meta):
    return [_entry(kind, var, b, status, reason, meta=dict(meta)) for b in BANDS[kind]]


def _obs_label(spec):
    return '%s CH%s' % (spec['device_id'], spec['channel'])


def _build_pairs(io, info, ctx, kind, var, now, p):
    """→ (쌍 목록, 중단 이유). 이유가 있으면 쌍은 비어 있다."""
    t0 = now - p.window_days * DAY_S
    spec = info['obs'][OBS_KEY[var]]
    inp = info['hourly_input'] if kind == KIND_H else info['daily_input']
    if kind == KIND_H:
        fc_rows = io.fc_hourly(inp, var, t0, now)
        if not fc_rows:
            return [], (ST_NO_FC, 'no_l0')
        obs = io.obs_hourly(spec, t0 - HOUR_S, now + HOUR_S, 'mean')
        if not obs:
            return [], (ST_NO_OBS, 'no_obs_data')
        aux_fc = obs_aux = None
        if var == 'RH':
            aux_fc = {(t, lead): v for t, lead, v in io.fc_hourly(inp, 'T', t0, now)}
            tspec = info['obs'].get('T')
            obs_aux = io.obs_hourly(tspec, t0 - HOUR_S, now + HOUR_S, 'mean') if tspec else {}
        elif var == 'RAIN':
            aux_fc = {(t, lead): v / 100.0 for t, lead, v in io.fc_hourly(inp, 'POP', t0, now)}
        pairs = pairing.hourly_pairs(var, fc_rows, obs, aux_fc, obs_aux)
    else:
        fc_rows = io.fc_daily(inp, var, t0, now)
        if not fc_rows:
            return [], (ST_NO_FC, 'no_l0')
        fn_obs, fn_day = ('max', max) if var == 'TMAX' else ('min', min) if var == 'TMIN' else ('mean', sum)
        hourly = io.obs_hourly(spec, t0 - DAY_S, now + HOUR_S, fn_obs)
        obs = pairing.daily_from_hourly(hourly, fn_day, ctx)
        if not obs:
            return [], (ST_NO_OBS, 'no_obs_data')
        aux_fc = None
        if var == 'RAIN':
            aux_fc = {(t, lead): v / 100.0 for t, lead, v in io.fc_daily(inp, 'POP', t0, now)}
        pairs = pairing.daily_pairs(var, fc_rows, obs, aux_fc)
    pairs = [pr for pr in pairs if pr.t <= now]
    if not pairs:
        return [], (ST_FEW, 'no_pairs')
    return pairs, None


def _calibrate_var(io, info, ctx, kind, var, now, p, mode, prev, site_id):
    if mode == 'off':
        return _all_bands(kind, var, ST_OFF, 'mode_off')
    inp = info['hourly_input'] if kind == KIND_H else info['daily_input']
    if not inp:
        return _all_bands(kind, var, ST_NO_FC, 'no_input')
    spec = info['obs'].get(OBS_KEY[var])
    if spec is None:
        return _all_bands(kind, var, ST_NO_OBS, 'no_channel')
    deadline = time.monotonic() + p.time_budget_s
    pairs, stop = _build_pairs(io, info, ctx, kind, var, now, p)
    if stop:
        return _all_bands(kind, var, stop[0], stop[1], obs=_obs_label(spec))
    by_band = pairing.split_bands(kind, pairs)
    method = method_for(kind, var)
    out = []
    for band in BANDS[kind]:
        bp = by_band.get(band) or []
        if not bp:
            out.append(_entry(kind, var, band, ST_FEW, 'no_pairs', meta={'obs': _obs_label(spec)}))
            continue
        prev_e = prev.get((kind, var, band)) or {}
        prev_status = prev_e.get('status')
        prev_used = prev_status in USED_STATES and bool(prev_e.get('coef'))
        model = method.fit(bp, now, p, ctx)
        vres = forward_validate(method, bp, now, p, ctx, deadline)
        summ = summarize(vres, kind, var, p, seed_of(site_id, kind, var, band))
        status, reason = decide(summ, prev_status, prev_e.get('meta'), now, p, kind, mode,
                                has_model=model is not None or prev_used)
        if model is None and prev_used:
            model = prev_e['coef']                      # 관측이 잠시 끊겨도 쓰던 계수는 그대로 쓴다
        meta = _clean({'metrics': summ['metrics'], 'ci_lo': summ['ci_lo'], 'ci_hi': summ['ci_hi'],
                       'days': summ['days'], 'n': summ['n'], 'recent': summ['recent'],
                       'obs': _obs_label(spec), 'obs_source': info.get('obs_source'),
                       'reduced': p.reduced_mode})
        if status == ST_REVERTED:
            meta['reverted_at'] = (prev_e.get('meta') or {}).get('reverted_at') \
                if prev_status == ST_REVERTED else now
        out.append(_entry(kind, var, band, status, reason, method=method.name, coef=model, meta=meta,
                          window_start=min(pr.t for pr in bp), window_end=max(pr.t for pr in bp)))
    return out


def _deferred(kind, var, prev):
    """시간 제한을 넘긴 변수 — 이전 상태를 그대로 옮기고, 이전이 없으면 `deferred`."""
    out = []
    for band in BANDS[kind]:
        e = prev.get((kind, var, band))
        if e:
            out.append(_entry(kind, var, band, e['status'], e['reason'], method=e.get('method'), coef=e.get('coef'),
                              meta=dict(e.get('meta') or {}, deferred=True),
                              window_start=e.get('window_start'), window_end=e.get('window_end')))
        else:
            out.append(_entry(kind, var, band, ST_DEFERRED, 'time_budget', meta={'deferred': True}))
    return out


def _events(prev, entries, info):
    evs = []
    for e in entries:
        key = (e['kind'], e['var'], e['band'])
        was = prev.get(key)
        was_used = bool(was) and was['status'] in USED_STATES and bool(was.get('coef'))
        now_used = e['status'] in USED_STATES and bool(e.get('coef'))
        if was_used == now_used:
            continue
        meta = e.get('meta') or {}
        detail = {'reason': e.get('reason'), 'metrics': meta.get('metrics'), 'ci_lo': meta.get('ci_lo'),
                  'days': meta.get('days'), 'recent': meta.get('recent'), 'obs': meta.get('obs'),
                  'before_status': was['status'] if was else None, 'after_status': e['status']}
        evs.append({'event': 'adopted' if now_used else 'reverted', 'kind': e['kind'], 'var': e['var'],
                    'band': e['band'], 'detail': detail})
    return evs


# @manual geo/map-widget#site-forecast-calibration
def calibrate_site(site_id, io, now=None, params: Optional[Params] = None, mode=None, writer=None, email=True,
                   dry=False):
    """한 대지의 보정을 점검하고 저장한다 → 요약 사전. 호출자가 DB 세션을 감싼다(앱 컨텍스트).

    `dry` 면 계산·판정만 하고 **아무것도 쓰지 않는다**(판·성적·알림·점검 기록 없음) — 개발서버에서 이력이 얼마나 쌓였나
    볼 때 쓴다(`aot/scripts/fc_cal_run.py --dry`)."""
    from aot.aot_flask.extensions import db
    now = time.time() if now is None else float(now)
    p = params or Params()
    info = io.site_info(site_id)
    mode = mode or store.site_mode(site_id)
    prev = store.active_entries(site_id)
    ctx = Ctx(info['tz'], info['lat'], info['lon'])
    entries: List[dict] = []
    timed_out = []
    for kind in (KIND_H, KIND_D):
        for var in VARS[kind]:
            try:
                entries += _calibrate_var(io, info, ctx, kind, var, now, p, mode, prev, site_id)
            except Timeout:
                timed_out.append('%s/%s' % (kind, var))
                entries += _deferred(kind, var, prev)
            except Exception:                           # noqa: BLE001 — 한 변수의 오류가 나머지를 막지 않는다
                logger.exception('[fc_cal] 점검 실패 %s %s/%s', site_id, kind, var)
                entries += _deferred(kind, var, prev)
    row = store.site_row(site_id, create=not dry)
    rev = row.active_rev if row is not None else 0
    events = []
    if store.changed_effect(prev, entries):
        events = _events(prev, entries, info)
        if not dry:
            rev = store.write_rev(site_id, entries, now)
            if events:
                store.add_events(site_id, info.get('name'), rev, events, now, email=email)
    if not dry:
        store.write_scores(site_id, entries, rev, now, writer=writer)
    summary = {'site': site_id, 'at': now, 'rev': rev, 'mode': mode, 'obs_source': info.get('obs_source'), 'timed_out': timed_out,
               'reduced': p.reduced_mode,
               'items': [{'kind': e['kind'], 'var': e['var'], 'band': e['band'], 'status': e['status'],
                          'reason': e.get('reason'),
                          'skill': ((e.get('meta') or {}).get('metrics') or {}).get('skill'),
                          'n': ((e.get('meta') or {}).get('metrics') or {}).get('n')} for e in entries]}
    if not dry:
        store.save_run(site_id, now, _clean(summary))
        db.session.commit()
    summary['dry'] = dry
    summary['events'] = [(ev['event'], ev['kind'], ev['var'], ev['band']) for ev in events]
    return summary
