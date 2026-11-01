# coding=utf-8
"""트윈의 토양 수분 예측을 AI·MCP 응답으로 — 노지 구획 하나, 뿌리층 체적수분(%) 일 단위 (시범).

읽기 규칙은 지도 예측 제공자(`GET /api/twin/plots`)와 **같은 것**이다 — `twin_read.usable`/
`plots_bundle` 이 만료·계산 불가 발행을 걸러 마지막 값으로 채우지 않는다. 게이트는 설정 > 일반
'디지털트윈' 플래그(`twin_config.ui_enabled`), 못 칠하는 이유가 설정이면 `twin_config.plot_diagnoses`
의 한 단어를 더한다. 이 모듈은 새 값을 만들지 않는다 — Influx 의 `env_twin_field` 에서 읽은 θ_root
분위수와 사건 확률을 사람이 읽는 모양으로 옮길 뿐이다(원천/정제/산출 중 산출 모양만).

범위: 노지 구획 · 토양 수분 하나. 시설 트윈·다른 변수(Dr·Ks·지온·GDD)는 아직 안 낸다.
"""
import logging
import time

logger = logging.getLogger(__name__)

#: 앞으로 며칠까지 싣는가(오늘 포함). 트윈의 신뢰 구간이 7일까지다(계약 §10.3).
AHEAD_DAYS = 7

UNIT = "% volumetric, root layer"

_STATUS = {0: 'ok', 1: 'degraded'}

_MESSAGES = {
    'twin_disabled': "The digital twin is switched off (Settings > General).",
    'facility_plot': "This plot is inside a facility; only open-field plots are covered so far.",
    'no_publication': "The twin has not published a result for this plot yet.",
    'bad_publication': "The twin's latest publication is incomplete.",
    'expired': "The twin's latest result has expired; it is not filled in with old values.",
    'status_2': "The twin cannot compute this plot (set-up missing).",
    'status_3': "The twin is not synchronised to this plot's sensors.",
    'no_curve_in_window': "The twin published nothing for the coming days.",
}


def _unavailable(plot, reason, **extra):
    out = {'status': 'unavailable', 'reason': reason,
           'message': _MESSAGES.get(reason, reason), 'plot': plot.name or plot.subject}
    out.update(extra)
    return out


def _round(v, n=1):
    return None if v is None else round(float(v), n)


def soil_moisture(plot, now=None, ahead=AHEAD_DAYS):
    """구획 행 하나 → 토양 수분 예측 응답 dict. 쓸 수 없으면 status='unavailable' + 이유."""
    from aot.twin import output as O
    from aot.utils import twin_config, twin_read
    from aot.utils.device_tz import location_iso
    from aot.utils.influx import read_twin_many

    now = time.time() if now is None else now
    if not twin_config.ui_enabled():
        return _unavailable(plot, 'twin_disabled')
    if getattr(plot, 'facility_uuid', None):
        return _unavailable(plot, 'facility_plot')
    pid = plot.unique_id
    start, end = now, now + (ahead + 1) * 86400.0   # start=now: 오늘 00시 점부터(어제는 뺀다)
    meta_rows = read_twin_many(O.M_FLD_META, [pid], twin_read.META_CHANNELS, now - 3 * 86400.0, now + 600.0)
    meta = twin_read.latest_meta(meta_rows, pid)
    ok, why = twin_read.usable(meta, now)
    curve_rows = {}
    if ok:
        chans = sorted(set(twin_read.CURVE_CHANNELS.values()))
        curve_rows = read_twin_many(O.M_FLD, [pid], chans, now - 2 * 86400.0, end)
    rec = twin_read.plots_bundle([pid], meta_rows, curve_rows, now, start, end)[0]
    if not rec['usable']:
        extra = {}
        if rec['reason'] in ('status_2', 'status_3'):
            try:
                setup = twin_config.plot_diagnoses([pid]).get(pid)
                if setup:
                    extra['setup'] = setup
            except Exception:                               # noqa: BLE001
                logger.debug("트윈 구획 설정 진단 실패", exc_info=True)
        return _unavailable(plot, rec['reason'], **extra)

    cache = {}
    days = []
    for i, t in enumerate(rec['days'][:ahead + 1]):
        row = {'date': (location_iso(t, pid, cache) or '')[:10],
               'p10': _round(rec['theta_root_p10'][i]), 'p50': _round(rec['theta_root_p50'][i]),
               'p90': _round(rec['theta_root_p90'][i])}
        for key, name in (('p_water_deficit', 'p_dry'), ('p_waterlogging', 'p_wet')):
            v = (rec.get(key) or [None] * (i + 1))[i]
            if v is not None:
                row[name] = _round(v, 2)
        days.append(row)
    m = rec['meta']
    quality = {k: m[k] for k in ('ensemble_size', 'obs_n', 'coverage_80', 'horizon_d') if k in m}
    quality = {k: (_round(v, 2) if isinstance(v, float) else v) for k, v in quality.items()}
    out = {
        'status': 'success', 'plot': plot.name or plot.subject, 'unit': UNIT,
        'source': "twin model forecast, not a measurement",
        'twin_status': _STATUS.get(int(m.get('status', 0)), int(m.get('status', 0))),
        'published_at': location_iso(m['t0'], pid, cache),
        'valid_until': location_iso(m['valid_until'], pid, cache),
        'days': days,
        'note': "p10-p90 = model range; p_dry = chance of water stress that day, p_wet = of waterlogging.",
        'quality': quality,
    }
    return out
