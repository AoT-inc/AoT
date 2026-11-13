# coding=utf-8
"""트윈 구획 그래프 자료 — 지도 모달 '트윈' 탭의 [그래프] 가 한 번에 읽는 묶음 (`GET /api/twin/chart/plot/<id>`).

한 화면이 필요한 것을 서버에서 한 번 모은다: 예측(분위수 곡선·머리말), 센서 실측 점, 비·기온(과거 관측 +
대지 지정 예보), 사건 확률. 읽는 쪽 규칙(계약 §7-4)은 `twin_read.usable` 이 그대로 적용한다 — 만료·숨김 발행은
곡선 없이 이유만 싣는다(마지막 값으로 채우지 않는다).

**날짜는 문자열 키(`YYYY-MM-DD`)로 싣는다 — 모두 대지 시간대의 현지 날짜다.** 예측 곡선의 일 격자 점은 **그 지역 00:00**(`t0 = 오늘 * 86400 - tz`,
한국 11-02 은 `11-01 15:00Z`)이라 UTC 날짜로 접으면 하루 앞으로 밀린다 — `twin_read.grid_date(t, tz_name)` 가 점마다 현지 날짜를 정한다(서머타임을 넘는 격자도 하루가 겹치거나 빠지지 않는다).
화면이 시간대 계산을 하지 않게 서버가 날짜로 접어 준다. 점 관측(`theta.obs`)만 epoch 초로 싣고 `tz_offset_s` 를 함께 준다(그날 안의 위치를 그리려고).

**분석 이력·시나리오(D7)**: `post=True` 면 동기화로 맞춘 과거(`env_twin_field_post`, 발행 시각 앞의 사후 추정)를 `post` 로,
`scenario=<id>` 면 그 시나리오의 곡선(`env_twin_scn_field`)을 `scenario` 로 얹는다 — 둘 다 기본 예측 `theta`·`temp.tmin` 과 같은 모양이다.
모든 응답은 `lineage`(보정됨/원본·보정 판·예보 발표·관측 출처)와 `baseline_src` 를 싣는다.

출처: 읽은 계열마다 장치 이름·채널을 `sources` 에 싣는다(실측·미러·가상 구분은 하지 않는다 — PR #302). 값의 층
(원본·보정됨)은 데이터 관리 설계가 정해지면 `layer` 에 채운다 — 지금은 'raw' 고정.
"""
from __future__ import annotations

import datetime
import logging
import math
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from aot.twin import output as O
from aot.utils import twin_config, twin_read

logger = logging.getLogger(__name__)

DAY_S = 86400.0
MAX_BACK_D = 60
MAX_AHEAD_D = 14
#: 일광절약시간 전환일에 발행 때 오프셋과 읽는 때 오프셋이 달라 생기는 창 경계 어긋남(최대 1 시간)의 여유.
DST_PAD_S = 7200.0

#: 그래프가 읽는 머리말 채널 = 지도 제공자가 읽는 것 + 기준선(포장용수량·위조점·물 부족 문턱)과 센서 관측식 계수.
#: 기준선은 모델이 계산해 발행 머리말에 싣는다(토성 + 작물 고갈 허용률, 계약 §10.4 33~35) — 사용자가 정하는 값이 아니다.
_M = O.FIELD_META
REF_CHANNELS = (_M['theta_fc'], _M['theta_wp'], _M['theta_thr'], _M['obs_a'], _M['obs_b'])
LINEAGE_CHANNELS = (_M['fc_issue_epoch'], _M['fc_cal_rev'], _M['obs_origin'])
EFFECT_CHANNELS = (_M['plan_src'], _M['effects_modeled'], _M['effects_unmodeled'])
CHART_META_CHANNELS = tuple(twin_read.META_CHANNELS) + REF_CHANNELS + LINEAGE_CHANNELS + EFFECT_CHANNELS

Q = O.FIELD_DAILY_Q
E = O.FIELD_DAILY_EVENTS
#: 응답 이름 → env_twin_field 채널. 측정·채널 이름은 여기 한 곳에서만 안다
#: (저장 계층이 바뀌면 이 표와 `read_curves` 만 고친다).
CHART_CHANNELS: Dict[str, int] = {
    'theta_root_p10': Q['theta_root'], 'theta_root_p50': Q['theta_root'] + 1, 'theta_root_p90': Q['theta_root'] + 2,
    'theta_sensor_p10': Q['theta_sensor'], 'theta_sensor_p50': Q['theta_sensor'] + 1,
    'theta_sensor_p90': Q['theta_sensor'] + 2,
    'tmin_p10': Q['Tmin'], 'tmin_p50': Q['Tmin'] + 1, 'tmin_p90': Q['Tmin'] + 2,
    'p_water_deficit': E['water_deficit'], 'p_frost': E['frost'], 'p_waterlogging': E['waterlogging'],
}


def _local_day_n(t: float, tz_name: str) -> int:
    """순간 → 구획 현지 날짜의 에포크 일 번호."""
    from aot.utils.timekit import to_tz
    return (to_tz(float(t), tz_name).date() - datetime.date(1970, 1, 1)).days


def _local_midnight(day_n: int, tz_name: str) -> float:
    """에포크 일 번호의 현지 자정 → epoch 초(그날의 오프셋으로 — 서머타임 날도 정확)."""
    from aot.utils.timekit import wall_to_utc
    d = datetime.date(1970, 1, 1) + datetime.timedelta(days=int(day_n))
    return wall_to_utc(datetime.datetime(d.year, d.month, d.day), tz_name).timestamp()


def day_text(day_number: int) -> str:
    return (datetime.date(1970, 1, 1) + datetime.timedelta(days=int(day_number))).isoformat()


def _finite(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def curves_by_date(rows: Mapping, plot_id: str, t0: float, lo: float, hi: float, tz_name: str,
                   keep_past: bool = False) -> Dict[str, Dict[str, float]]:
    """곡선 행 → {응답 이름: {날짜: 값}}. 최신 발행 `t0` 앞의 점은 옛 발행의 잔재라 버린다(계약 §6.1).

    `keep_past=True` 는 분석 이력(`env_twin_field_post`)용 — 그 곡선은 `t0` **앞**의 사후 추정이라 앞을 자르지 않는다."""
    out: Dict[str, Dict[str, float]] = {}
    if not keep_past:
        lo = max(lo, t0 - 1.0)
    for name, ch in CHART_CHANNELS.items():
        s: Dict[str, float] = {}
        for t, v in rows.get((plot_id, ch)) or []:
            f = _finite(v)
            if f is not None and lo <= t <= hi:
                s[twin_read.grid_date(t, tz_name)] = round(f, 4)
        if s:
            out[name] = s
    return out


def hourly_means(points: Sequence[Tuple[float, float]], lo: float, hi: float) -> List[List[float]]:
    """원시 점 → 시간 칸 평균 [[칸 가운데 epoch, 값]] (그림 점 수를 줄이고, 센서 주기와 무관하게 한다)."""
    bins: Dict[int, List[float]] = {}
    for t, v in points:
        f = _finite(v)
        if f is None or not (lo <= t <= hi):
            continue
        bins.setdefault(int(t // 3600), []).append(f)
    return [[h * 3600.0 + 1800.0, round(sum(a) / len(a), 3)] for h, a in sorted(bins.items())]


def _series_src(cfg: Optional[Mapping], names: Mapping) -> Optional[Dict[str, object]]:
    if not cfg:
        return None
    # 출처 표시(실측·미러·가상)는 걷었다 — 센서는 위치·도형으로 정해지고 미러는 실측 사본이다(PR #302·#312). 이름만 싣는다.
    return {'unique_id': cfg.get('unique_id'), 'channel': cfg.get('channel'),
            'name': twin_config._series_label(cfg, names)}


def read_curves(plot_id: str, now: float, hi: float):
    """(머리말 행, 곡선 행) — Influx 왕복 둘. 실패하면 예외(호출자가 503 으로 바꾼다)."""
    from aot.utils.influx import read_twin_many
    meta_rows = read_twin_many(O.M_FLD_META, [plot_id], CHART_META_CHANNELS, now - 3 * DAY_S, now + 600.0)
    meta = twin_read.latest_meta(meta_rows, plot_id, CHART_META_CHANNELS)
    ok, _why = twin_read.usable(meta, now)
    curve_rows = read_twin_many(O.M_FLD, [plot_id], sorted(set(CHART_CHANNELS.values())),
                                now - 2 * DAY_S, hi) if ok else {}
    return meta_rows, curve_rows


def read_variant(plot_id: str, measurement: str, lo: float, hi: float, tags: Optional[Mapping[str, str]] = None):
    """분석 이력(`env_twin_field_post`)·시나리오 곡선(`env_twin_scn_field`) 행 — 곡선 채널과 같은 배치. 못 읽으면 예외."""
    from aot.utils.influx import read_twin_many
    return read_twin_many(measurement, [plot_id], sorted(set(CHART_CHANNELS.values())), lo, hi, tag_filters=tags)


def read_observed(cfg: Mapping, now: float, back_s: float) -> Dict[str, List[Tuple[float, float]]]:
    """구획이 쓰는 관측 입력(theta·rain·t_air·et0) → 원시 점. 못 읽은 입력은 빈 목록."""
    from aot.utils.influx import read_influxdb_list
    out: Dict[str, List[Tuple[float, float]]] = {}
    for key in ('theta', 'rain', 't_air', 'et0'):
        s = cfg.get(key)
        if not s:
            continue
        try:
            rows = read_influxdb_list(s['unique_id'], s['unit'], int(s['channel']), duration_sec=int(back_s)) or []
        except Exception:                                        # noqa: BLE001
            logger.exception('트윈 그래프: 관측 읽기 실패 %s', key)
            rows = []
        out[key] = [(float(t), float(v)) for t, v in rows if v is not None]
    return out


def read_forecast_days(site_id: str, t0: float, t1: float):
    """대지 지정 예보의 일 행(지도·AI 와 같은 출처). 못 읽으면 None."""
    try:
        from aot.space import forecast_series
        data = forecast_series.read(site_id, t0, t1, ['temp_c'])
    except Exception:                                            # noqa: BLE001
        logger.exception('트윈 그래프: 예보 읽기 실패')
        return None
    return data


def _daily_obs(obs: Mapping, cfg: Mapping, opts: Mapping, tz_name: str) -> Dict[str, object]:
    """관측 계열 → 현지 날짜 값. 비는 모델이 쓰는 묶는 법(`options.rain`)을 그대로 쓴다."""
    from aot.twin.models import field_bucket as fb
    out: Dict[str, object] = {}
    rt = obs.get('rain') or []
    if rt:
        rc = dict((opts or {}).get('rain') or {})
        d = fb.daily_rain([t for t, _ in rt], [v for _, v in rt], tz_name, str(rc.get('agg', 'hourly_mean_sum')),
                          float(rc.get('scale', 1.0)))
        out['rain'] = {day_text(k): round(v, 2) for k, v in d.items()}
    ta = obs.get('t_air') or []
    if ta:
        d = fb.daily_temps([t for t, _ in ta], [v for _, v in ta], tz_name)
        out['temp'] = {day_text(k): [round(a, 1), round(b, 1), round(c, 1)] for k, (a, b, c) in d.items()}
    et = obs.get('et0') or []
    if et:
        d = fb.daily_rain([t for t, _ in et], [v for _, v in et], tz_name, 'daily_last', 1.0)
        out['et0'] = {day_text(k): round(v, 2) for k, v in d.items()}
    return out


def lineage_of(meta: Optional[Mapping]) -> Dict[str, object]:
    """최신 발행 머리말의 계보 — 그래프의 '보정됨/원본' 표시 재료. 머리말이 없거나 칸이 비면 None(모름)."""
    meta = meta or {}
    rev, org = _finite(meta.get('fc_cal_rev')), _finite(meta.get('obs_origin'))
    return {'calibrated': None if rev is None else int(rev) > 0, 'cal_rev': None if rev is None else int(rev),
            'fc_issue_epoch': _finite(meta.get('fc_issue_epoch')), 'origin': None if org is None else int(org),
            't0': _finite(meta.get('t0'))}


def _curve_block(cur: Mapping, kind: str, scenario_id: Optional[str]) -> Dict[str, object]:
    """날짜 키 곡선 묶음 → 기본 예측 `theta`·`temp.tmin`·`events` 와 같은 모양의 한 덩어리."""
    base = 'theta_sensor_' if kind == 'sensor' else 'theta_root_'
    out: Dict[str, object] = {
        'theta': {'kind': kind, **{p: cur.get(base + p, {}) for p in ('p10', 'p50', 'p90')}},
        'tmin': {p: cur.get('tmin_' + p, {}) for p in ('p10', 'p50', 'p90')},
        'events': {k[2:]: v for k, v in cur.items() if k.startswith('p_')},
    }
    if scenario_id is not None:
        out['id'] = scenario_id
    return out


def baseline_refs(meta: Optional[Mapping], kind: Optional[str]) -> Optional[Dict[str, float]]:
    """기준선 {fc, wp, thr} — 곡선과 같은 단위(`kind`)로. 못 만들면 None(화면은 선만 뺀다).

    머리말 33~35 는 뿌리층 평균 θ [%]. 곡선이 센서 단위면 발행 때의 관측식 y = a·θ + b(36·37)로 옮긴다 —
    계수가 없거나 옮긴 값이 말이 안 되면(음수·wp < thr < fc 가 깨짐) 기준선을 내지 않는다(틀린 선을 그리느니 안 그린다)."""
    if not meta or kind not in ('root', 'sensor'):
        return None
    vals = {k: _finite(meta.get(k)) for k in ('theta_fc', 'theta_wp', 'theta_thr')}
    if any(v is None for v in vals.values()):
        return None
    a, b = 1.0, 0.0
    if kind == 'sensor':
        a, b = _finite(meta.get('obs_a')), _finite(meta.get('obs_b'))
        if a is None or b is None or a <= 0:
            return None
    out = {k[6:]: round(a * v + b, 2) for k, v in vals.items()}
    if not (0 < out['wp'] < out['thr'] < out['fc']):     # 계수가 어긋나면 옮긴 값이 음수·뒤집힌 순서가 된다(실측 3포장) — 틀린 선은 안 그린다
        return None
    return out


def assemble(plot_id: str, now: float, back_d: int, ahead_d: int, *, view: Mapping, meta_rows: Mapping,
             curve_rows: Mapping, observed: Mapping, forecast: Optional[Mapping], tz_offset_s: float,
             tz_name: str, names: Mapping, post_rows: Optional[Mapping] = None,
             scenario_rows: Optional[Mapping] = None, scenario_id: Optional[str] = None) -> Dict[str, object]:
    """읽어 온 것을 화면 묶음으로 조립한다(Influx·DB 를 모른다 — 시험 대상)."""
    meta = twin_read.latest_meta(meta_rows, plot_id, CHART_META_CHANNELS)
    ok, why = twin_read.usable(meta, now)
    inputs = view.get('inputs') or {}
    opts = view.get('options') or {}
    # 날짜는 점마다 구획 시간대로 푼다 — `tz_offset_s`(지금의 오프셋 하나)로 날짜를 만들면 서머타임을 낀 날의 경계가 ±1 h 어긋난다.
    today_n = _local_day_n(now, tz_name)
    days = [day_text(today_n + k) for k in range(-int(back_d), int(ahead_d) + 1)]
    lo = _local_midnight(today_n - int(back_d), tz_name)
    hi = _local_midnight(today_n + int(ahead_d) + 1, tz_name)
    clo = lo - DST_PAD_S      # 곡선 선택용 — 발행(`t0`)과 읽는 때의 UTC 오프셋이 일광절약시간으로 달라도 오늘 점이 빠지지 않게

    res: Dict[str, object] = {
        'plot_id': plot_id, 'now': now, 'tz': tz_name, 'tz_offset_s': tz_offset_s, 'today': day_text(today_n),
        'days': days, 'layer': 'raw',
        'state': {'usable': ok, 'reason': why, 'sensorless': False},
        'meta': None, 'theta': {'kind': None, 'unit': '%', 'obs': [], 'p10': {}, 'p50': {}, 'p90': {}},
        'rain': {'obs': {}, 'fc': {}}, 'et0': {'obs': {}, 'fc': {}}, 'temp': {'obs': {}, 'fc': {}, 'tmin': {}},
        'events': {}, 'refs': None, 'sources': {}, 'lineage': lineage_of(meta), 'baseline_src': None,
        'trust': twin_read.trust(meta, ok),
    }
    for k in ('theta', 'rain', 't_air', 'et0'):
        s = _series_src(inputs.get(k), names)
        if s:
            res['sources'][k] = s
    if meta:
        keep = ('t0', 'valid_until', 'status', 'sync_rmse_theta_1d', 'coverage_80', 'rain_fc_days', 'obs_n',
                'obs_age_s', 'rain_src', 'irrigation_known', 'horizon_d', 'plan_src', 'effects_modeled',
                'effects_unmodeled')
        res['meta'] = {k: meta[k] for k in keep if k in meta}
        st = res['state']
        st['sensorless'] = twin_read.sensorless(meta)

    # 예측 곡선 — 유효한 발행만
    if ok:
        cur = curves_by_date(curve_rows, plot_id, meta['t0'], clo, hi, tz_name)
        kind = twin_read.theta_basis('theta_sensor_p50' in cur, res['state']['sensorless'])
        base = 'theta_sensor_' if kind == 'sensor' else 'theta_root_'
        th = res['theta']
        th['kind'] = kind
        for p in ('p10', 'p50', 'p90'):
            th[p] = cur.get(base + p, {})
        res['temp']['tmin'] = {p: cur.get('tmin_' + p, {}) for p in ('p10', 'p50', 'p90')}
        res['events'] = {k[2:]: v for k, v in cur.items() if k.startswith('p_')}
        res['refs'] = baseline_refs(meta, th['kind'])
        res['baseline_src'] = 'header' if res['refs'] else None
        if scenario_id is not None:
            sc = curves_by_date(scenario_rows or {}, plot_id, meta['t0'], clo, hi, tz_name)
            res['scenario'] = _curve_block(sc, th['kind'], scenario_id)

    # 분석 이력 — 발행 `t0` 앞의 사후 추정(동기화로 맞춘 과거)
    if post_rows is not None and meta:
        po = curves_by_date(post_rows, plot_id, meta['t0'], clo, meta['t0'], tz_name, keep_past=True)
        res['post'] = _curve_block(po, twin_read.theta_basis('theta_sensor_p50' in po, res['state']['sensorless']), None)

    # 관측
    obs = observed or {}
    res['theta']['obs'] = hourly_means(obs.get('theta') or [], lo, now + 60.0)
    daily = _daily_obs(obs, inputs, opts, tz_name)
    if 'rain' in daily:
        res['rain']['obs'] = {d: v for d, v in daily['rain'].items() if d in set(days) and d < res['today']}
    if 'temp' in daily:
        res['temp']['obs'] = {d: v for d, v in daily['temp'].items() if d in set(days) and d <= res['today']}
    if 'et0' in daily:
        res['et0']['obs'] = {d: v for d, v in daily['et0'].items() if d in set(days) and d < res['today']}

    # 대지 지정 예보(같은 출처) — 오늘부터
    if forecast and forecast.get('available'):
        src = forecast.get('source') or {}
        res['sources']['forecast'] = {'name': src.get('name'), 'input_id': src.get('input_id'),
                                      'basis': forecast.get('source_basis'),
                                      'calibrated': bool(forecast.get('calibrated'))}
        dset = set(days)
        for r in forecast.get('daily') or []:
            d = r.get('date')
            if d not in dset or d < res['today']:
                continue
            if _finite(r.get('precip_mm')) is not None:
                res['rain']['fc'][d] = round(float(r['precip_mm']), 2)
            if _finite(r.get('et0_mm')) is not None:
                res['et0']['fc'][d] = round(float(r['et0_mm']), 2)
            lo_t, hi_t = _finite(r.get('temp_min_c')), _finite(r.get('temp_max_c'))
            if lo_t is not None and hi_t is not None:
                res['temp']['fc'][d] = [round(lo_t, 1), round(hi_t, 1)]
    elif forecast is not None:
        res['sources']['forecast'] = {'reason': forecast.get('reason') or 'none'}
    return res


# ── 시나리오 목록 · 장치 레인 (그래프 2단계) ─────────────────────────────────────────

#: 장치 근거의 나쁜 정도 — 합친 값의 출처는 합친 장치 중 가장 나쁜 쪽이다(장치 효과 E2). `plan` 은 앞날이라 따로 센다.
BASIS_RANK = {'actual': 0, 'duty_log': 1, 'command': 2, 'assumed': 3}
EFFECT_STATUS_RANK = ('modeled', 'partial', 'unmodeled', 'unknown')
#: 레인 값의 단위와 하루로 접는 법 — 노지 관수는 시 격자 mm 라 합하고, 시설은 정시 평균 % 라 평균한다.
LANE_UNITS = {'irrigation_mm': ('mm', 'sum')}


def scenario_items(rows: Sequence, base_t0s: Mapping, current_t0: Optional[float]) -> List[Dict[str, object]]:
    """시나리오 머리 행 → 그래프가 고르는 목록(최근 것부터). 낡음 = 끝난 시나리오의 `base_t0` ≠ 현재 발행 t0."""
    from aot.utils import twin_store
    out = []
    for r in rows:
        d = twin_store.scenario_dict(r, base_t0s.get(r.base_run))
        n = {k: 0 for k in EFFECT_STATUS_RANK}
        for e in d['effects']:
            n[e.get('status') if e.get('status') in n else 'unknown'] += 1
        base_t0 = _finite(d['base_t0'])
        out.append({
            'id': d['id'], 'label': d['label'], 'status': d['status'], 'fail_reason': d['fail_reason'],
            'pinned': d['pinned'], 'created_at': d['created_at'], 'expires_at': d['expires_at'],
            'stale': d['status'] == 'done' and current_t0 is not None and base_t0 is not None
                     and abs(base_t0 - current_t0) > 1.0,
            'future_input_mode': d['future_input_mode'], 'weather': d['weather_assumption'], 'actuators': d['actuator_plan'],
            'effects': n,
        })
    return out


def _act_groups(rows: Sequence) -> Dict[Tuple[str, str, str], List[List[float]]]:
    """`env_twin_act` 행 [(t, v, 태그)] → {(효과, 근거, 장치): [[t, v]]}."""
    g: Dict[Tuple[str, str, str], List[List[float]]] = {}
    for t, v, tg in rows or []:
        f = _finite(v)
        if f is None or not tg.get('effect'):
            continue
        g.setdefault((tg['effect'], tg.get('basis') or '', tg.get('dev') or O.ACT_ALL_DEVICES), []).append([float(t), round(f, 3)])
    return g


def lane_status(statuses: Sequence[str]) -> Optional[str]:
    """한 효과 채널의 장치 상태들 → 레인 상태. 하나라도 반영되면 '일부', 하나도 안 되면 '미반영', 장치를 모르면 None."""
    s = set(statuses)
    if not s:
        return None
    if s == {'modeled'}:
        return 'modeled'
    if 'modeled' in s or 'partial' in s:
        return 'partial'
    return 'unmodeled' if 'unmodeled' in s else 'unknown'


def _row_status(r: Mapping) -> str:
    """기본 예측이 이 장치의 효과를 실제로 쓰는가 — 노지 출력은 물 근거가 없으면 `applied=False` 라 미반영이다."""
    if r.get('applied') is False and r.get('status') in ('modeled', 'partial'):
        return 'unmodeled'
    s = r.get('status')
    return s if s in EFFECT_STATUS_RANK else 'unknown'


def _past_plan(groups: Mapping, effect: str, dev: str):
    """한 효과·장치의 (과거 근거별 [{basis, points}], 앞날 plan 점)."""
    past, plan = [], []
    for (e, basis, d), pts in sorted(groups.items()):
        if e != effect or d != dev:
            continue
        if basis == 'plan':
            plan = pts
        else:
            past.append({'basis': basis, 'points': pts})
    past.sort(key=lambda x: BASIS_RANK.get(x['basis'], 9))
    return past, plan


def build_lanes(kind: str, base_rows: Sequence, scn_rows: Optional[Sequence], roster: Optional[Sequence[Mapping]],
                counts: Optional[Mapping] = None) -> List[Dict[str, object]]:
    """장치 레인 — 효과 채널 하나가 한 레인(합친 값 `dev=all`), 장치별은 `devices` 로 펼친다.

    `base_rows` = 기본 예측의 작동 시계열(과거 근거 4값 + 앞날 plan), `scn_rows` = 고른 시나리오의 앞날 plan(없으면 None).
    `roster` = 대상의 장치 줄(`twin_effects.links.build_rows`: id·name·kind·channel·status·applied), 못 읽으면 None.
    모델이 없는 장치는 조용히 빼지 않는다 — 계열이 없어도 레인(또는 장치 줄)은 남기고 `status` 가 '미반영'을 말한다.
    효과 이름이 없는 장치(종류 모름)는 `effect=None` 레인에 모은다."""
    bg, sg = _act_groups(base_rows), _act_groups(scn_rows or [])
    rows = [r for r in (roster or []) if not r.get('excluded') and r.get('status') != 'supply']   # 공급 부품은 효과가 아니다
    effects = []
    for e in sorted({k[0] for k in list(bg) + list(sg)}):
        effects.append(e)
    for r in rows:
        if r.get('channel') and r['channel'] not in effects:
            effects.append(r['channel'])
    if any(not r.get('channel') for r in rows):
        effects.append(None)
    lanes: List[Dict[str, object]] = []
    for e in effects:
        devs = [r for r in rows if (r.get('channel') or None) == e]
        unit, agg = LANE_UNITS.get(e, ('%', 'mean')) if e else ('', 'mean')
        lane: Dict[str, object] = {'effect': e, 'unit': unit, 'agg': agg,
                                   'status': lane_status([_row_status(r) for r in devs]), 'past': [], 'base_plan': [],
                                   'scn_plan': None, 'devices': []}
        if e:
            lane['past'], lane['base_plan'] = _past_plan(bg, e, O.ACT_ALL_DEVICES)
            if scn_rows is not None:
                lane['scn_plan'] = _past_plan(sg, e, O.ACT_ALL_DEVICES)[1]
        for r in devs:
            d: Dict[str, object] = {'id': r.get('id'), 'name': r.get('name'), 'kind': r.get('kind'),
                                    'status': _row_status(r), 'past': [], 'base_plan': [], 'scn_plan': None}
            if e:
                d['past'], d['base_plan'] = _past_plan(bg, e, str(r.get('id')))
                if scn_rows is not None:
                    d['scn_plan'] = _past_plan(sg, e, str(r.get('id')))[1]
            lane['devices'].append(d)
        lane['device_count'] = len(devs)
        lanes.append(lane)
    if not roster and counts and (counts.get('effects_unmodeled') or 0) > 0 and None not in effects:
        # 장치 줄은 못 읽었지만 머리말이 '반영 안 된 장치 N개' 라고 말한다 — 조용히 빼지 않는다
        lanes.append({'effect': None, 'unit': '', 'agg': 'mean', 'status': 'unmodeled', 'past': [], 'base_plan': [],
                      'scn_plan': None, 'devices': [], 'device_count': int(counts['effects_unmodeled'])})
    return lanes


def read_acts(target_id: str, scenario: str, lo: float, hi: float) -> List:
    """작동 시계열 행 — 장치 구분(`dev`)을 걸러 내지 않고 합친 값과 장치별을 한 번에 읽는다. 못 읽으면 예외."""
    from aot.utils.influx import read_layer_points
    return read_layer_points(O.M_ACT, target_id, {'scenario': scenario}, lo, hi)


def field_roster(site, s_cfg: Optional[Mapping]) -> Optional[List[Dict[str, object]]]:
    """노지 구획의 장치 줄(대지의 시설 밖 출력). 못 읽으면 None."""
    try:
        from aot.utils import twin_effects_link
        for g in twin_effects_link.site_effects(site, s_cfg).get('groups') or []:
            if g.get('kind') == 'field':
                return list(g.get('rows') or [])
        return []
    except Exception:                                            # noqa: BLE001
        logger.exception('트윈 그래프: 장치 줄 읽기 실패')
        return None


# @manual geo/map-widget#twin-chart
def plot_chart(plot_id: str, now: float, back_d: int = 14, ahead_d: int = 7, scenario: Optional[str] = None,
               post: bool = False) -> Optional[Dict[str, object]]:
    """구획 그래프 묶음. 트윈 대상이 아닌 구획이면 None. 모르는 시나리오는 `twin_store.StoreError`(404)."""
    if scenario in ('', O.BASELINE):
        scenario = None
    if scenario is not None:
        from aot.utils import twin_store
        row = twin_store.get_scenario(scenario)
        if row is None or row.target_id != plot_id:
            raise twin_store.StoreError('scenario not found for this plot', 404)
    back_d = max(0, min(int(back_d), MAX_BACK_D))
    ahead_d = max(1, min(int(ahead_d), MAX_AHEAD_D))
    site = twin_config.site_of_plot(plot_id)
    if site is None:
        return None
    s_en, s_cfg = twin_config.read('site', site.site_id)
    p_en, p_cfg = twin_config.read('plot', plot_id)
    eff = twin_config.effective(s_cfg, p_cfg)
    view = {'inputs': {k: (eff.get(k) or {}).get('value') for k in twin_config.INPUT_KEYS},
            'options': twin_config.merge(s_cfg.get('options') or {}, p_cfg.get('options') or {})}
    from aot.space import forecast_series
    tz_name = forecast_series._site_tz_name(site.site_id)
    tz_offset_s = forecast_series._tz_offset_s(tz_name, now)     # 화면이 하루 안의 위치를 그릴 때만 쓴다(날짜는 tz_name)
    hi = now + (ahead_d + 2) * DAY_S
    meta_rows, curve_rows = read_curves(plot_id, now, hi)
    post_rows = read_variant(plot_id, O.M_FLD_POST, now - (back_d + 1) * DAY_S, now + 600.0) if post else None
    scenario_rows = (read_variant(plot_id, O.M_FLD_SCN, now - 2 * DAY_S, hi, {'scenario': scenario})
                     if scenario is not None else None)
    observed = read_observed(view['inputs'], now, (back_d + 1) * DAY_S + 3600.0)
    fc = read_forecast_days(site.site_id, now - DAY_S, now + (ahead_d + 1) * DAY_S)
    ids = [view['inputs'][k]['unique_id'] for k in ('theta', 'rain', 't_air', 'et0') if view['inputs'].get(k)]
    names = twin_config._device_names(ids)
    out = assemble(plot_id, now, back_d, ahead_d, view=view, meta_rows=meta_rows, curve_rows=curve_rows,
                   observed=observed, forecast=fc, tz_offset_s=tz_offset_s, tz_name=tz_name, names=names,
                   post_rows=post_rows, scenario_rows=scenario_rows, scenario_id=scenario)
    out['site'] = {'id': site.site_id, 'name': site.name, 'enabled': bool(s_en)}
    out['included'] = p_en is not False
    _add_stage2(out, plot_id, site, s_cfg, scenario, now, back_d, hi)
    return out


def _add_stage2(out: Dict[str, object], plot_id: str, site, s_cfg, scenario: Optional[str], now: float,
                back_d: int, hi: float) -> None:
    """2단계 묶음 — 시나리오 목록과 장치 레인. 읽기에 실패해도 1단계 그림은 그대로 나가게 이유만 싣는다."""
    from aot.utils import twin_store
    t0 = (out.get('lineage') or {}).get('t0')
    try:
        rows = twin_store.list_scenarios('field', plot_id)
        out['scenarios'] = {'items': scenario_items(rows, twin_store.base_t0_map(rows), t0),
                            'limit': twin_store.SCENARIO_LIMIT}
    except Exception:                                            # noqa: BLE001
        logger.exception('트윈 그래프: 시나리오 목록 읽기 실패')
        out['scenarios'] = {'items': [], 'limit': None, 'error': True}
    lo = now - (back_d + 1) * DAY_S
    try:
        base = read_acts(plot_id, O.BASELINE, lo, hi)
        scn = read_acts(plot_id, scenario, now - 2 * DAY_S, hi) if scenario else None
        meta = out.get('meta') or {}
        roster = field_roster(site, s_cfg)
        if roster is not None:                                   # 다른 구획에 물을 대는 밸브는 이 구획의 줄이 아니다
            roster = [r for r in roster if not r.get('plots') or plot_id in r['plots']]
        out['lanes'] = build_lanes('field', base, scn, roster,
                                   {'effects_unmodeled': meta.get('effects_unmodeled')})
    except Exception:                                            # noqa: BLE001
        logger.exception('트윈 그래프: 작동 시계열 읽기 실패')
        out['lanes'] = []
        out['lanes_error'] = True
