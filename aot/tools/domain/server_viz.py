# -*- coding: utf-8 -*-
"""값 조회(measure.latest·measure.history)를 viz 카드로 서버가 직접 올린다 — 날씨·장소 카드(`server_card`)와 같은 결정.

글로 시킨 카드는 절반 남짓만 올라갔고(설계 §8 실측 40~45%), 값 조회에서는 도메인 틀이 `card_hint` 를 아예 떼므로
AI 에게는 안내조차 가지 않는다(값 조회 = 지금은 순수 텍스트, 카드 없음). 그래서 반드시 일어나야 할 일은 서버가 한다:
장치 대상 현재값(`measure.latest`→get_sensor_reading)은 **게이지**, 짧은 이력(`measure.history`→get_sensor_detail)은
**미니그래프(spark)** 로 만들어, AI 가 쓰는 길과 같은 길(`screen_action` action=post, 감사·한도·화면 허용·수신함이 같다)로
올린다. 텍스트 응답은 그대로 둔다 — 카드는 화면의 산출물이고 글은 대화에 남는다(병행, 사용자 결정 2026-11-06).

올리지 않는 때는 `server_card.skip_reason` 과 같다(인앱·사용자 없음·화면 꺼짐·화면 도구 없음·자동 카드 꺼짐). 실패한
조회·구역 요약(한 값이 아님)·눈금을 모르는 측정 항목에는 타일을 만들지 않는다 — 그때는 글만 남는다.

응답: 타일을 올린 성공 조회의 dict 본문에는 `card`({state: posted|already_shown|skipped, …}) 한 칸을 싣고 옛 안내를
뗀다. 본문이 list(이력 단수)면 올리기만 하고 본문은 그대로 둔다(list 에는 card 칸을 못 싣는다).
"""
import json
import logging

from flask_babel import lazy_gettext as lg

from aot.tools.domain import server_card
from aot.utils import ai_card_files as files

logger = logging.getLogger(__name__)

#: (tool, op) → 타일 종류.
VIZ_OPS = {('measure', 'latest'): 'gauge', ('measure', 'history'): 'spark'}
#: 한 카드에 담는 타일 상한(수신함 첨부 상한 8) 과 장치당 채널 상한.
MAX_TILES = 8
MAX_CHANNELS = 4
_FAILED_CALL = ("screen(op='card', title='%s', attach=[{name:'x.viz', "
                "text:'{\"viz\":\"gauge\",\"label\":…,\"value\":…,\"min\":…,\"max\":…}'}])")

#: 게이지 눈금(측정 이름 앞부분 → min·max). 모르는 항목은 게이지를 만들지 않는다(글만). 섭씨 기준 —
#: 단위가 화씨면 온도·이슬점만 환산한다. 값이 눈금 밖이면 바늘이 끝에 박히지 않게 살짝 넓힌다.
_SCALE = (
    ('temperature', (-10.0, 45.0)),
    ('dew_point', (-10.0, 40.0)),
    ('relative_humidity', (0.0, 100.0)),
    ('humidity', (0.0, 100.0)),
    ('soil_moisture', (0.0, 100.0)),
    ('volumetric_water_content', (0.0, 100.0)),
    ('moisture', (0.0, 100.0)),
    ('cloud_cover', (0.0, 100.0)),
    ('battery', (0.0, 100.0)),
    ('vapour_pressure_deficit', (0.0, 5.0)),
    ('vapor_pressure_deficit', (0.0, 5.0)),
    ('vpd', (0.0, 5.0)),
    ('carbon_dioxide', (0.0, 2000.0)),
    ('co2', (0.0, 2000.0)),
    ('conductivity', (0.0, 5.0)),
    ('ec', (0.0, 5.0)),
    ('ph', (0.0, 14.0)),
    ('illuminance', (0.0, 100000.0)),
    ('lux', (0.0, 100000.0)),
    ('light', (0.0, 100000.0)),
    ('shortwave_radiation', (0.0, 1200.0)),
    ('solar', (0.0, 1200.0)),
    ('radiation', (0.0, 1200.0)),
    ('wind_speed', (0.0, 30.0)),
    ('speed', (0.0, 30.0)),
    ('precipitation_probability', (0.0, 100.0)),
    ('precipitation', (0.0, 50.0)),
    ('rain', (0.0, 50.0)),
    ('pressure', (950.0, 1050.0)),
)


def post_for(app, tool, op, out, ctx, show=None):
    """값 조회 응답 `out` 을 보고 viz 카드를 올린다. 성공·타일 있음·dict 본문이면 `card` 를 싣고 옛 안내를 뗀다."""
    kind = VIZ_OPS.get((tool, op))
    if kind is None:
        return out
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, (dict, list)):
        return out
    why = server_card.skip_reason(ctx, show)
    if why == 'not_external':
        return out                                          # 인앱 AI 의 길 — 손대지 않는다
    if not _ran_ok(body):
        return out
    if why:
        return _annotate(out, body, {'state': 'skipped', 'reason': why}) if isinstance(body, dict) else out
    try:
        built = server_card.in_user_locale(app, (ctx or {}).get('scope_user_uuid'),
                                            lambda: _build(kind, body))
    except Exception:                                       # noqa: BLE001
        logger.exception('[server_viz] build failed')
        built = None
    if not built:
        return _annotate(out, body, {'state': 'skipped', 'reason': 'nothing_to_show'}) \
            if isinstance(body, dict) else out
    title, message, tiles = built
    if not server_card.take_auto_slot((ctx or {}).get('scope_user_uuid')):
        # 자동 카드 몫을 다 썼다 — 수신함 한도의 나머지는 AI 가 올리는 카드 몫이다(`server_card.AUTO_PER_MIN`).
        return _annotate(out, body, {'state': 'skipped', 'reason': 'auto_card_budget'}) \
            if isinstance(body, dict) else out
    got = _post(app, title, message, tiles, ctx)
    state = got.get('status') if isinstance(got, dict) else None
    if state in ('posted', 'queued', 'sent', 'needs_confirmation', 'skipped'):
        ack = {'state': 'already_shown' if state == 'skipped' else 'posted', 'title': title}
        return _annotate(out, body, ack) if isinstance(body, dict) else out
    err = str((got or {}).get('error') or state or 'no answer') if isinstance(got, dict) else 'no answer'
    logger.info('[server_viz] not posted (%s)', err)
    if isinstance(body, dict):
        return _annotate(out, body, {'state': 'skipped', 'reason': 'post_failed: ' + err[:70], 'title': title},
                         call=_FAILED_CALL % title.replace("'", ''))
    return out


def eligible(ctx, show=None):
    return server_card.eligible(ctx, show)


def _ran_ok(body):
    if isinstance(body, list):
        return bool(body)
    return server_card._ran_ok(body)


def _annotate(out, body, card, call=None):
    """dict 본문 앞쪽(상태 다음)에 `card` 를 싣고 옛 안내를 뗀다. `call` 은 서버가 못 올렸을 때 AI 가 올릴 길."""
    server_card.drop_hints(body)
    head = {'status': body['status']} if 'status' in body else {}
    body = {**head, 'card': card, **{k: v for k, v in body.items() if k not in ('card', 'status')}}
    if call:
        nxt = body.get('next') if isinstance(body.get('next'), dict) else {}
        body['next'] = dict(nxt, call=call)
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def _post(app, title, message, tiles, ctx):
    """AI 의 카드와 같은 길 — 이 대화가 지정해 둔 화면이 있으면 그 화면으로. viz 타일은 attach 로 올린다."""
    from aot.tools import screen_follow
    from aot.tools.tool_execution import _execute_tool
    attach = [{'name': 'reading-%d.viz' % i, 'text': json.dumps(spec, ensure_ascii=False)}
              for i, spec in enumerate(tiles)]
    args = {'action': 'post', 'title': title, 'message': message or '', 'attach': attach}
    key = screen_follow.designated_screen((ctx or {}).get('scope_user_uuid'), (ctx or {}).get('session_key'))
    if key:
        args['screen'] = key[:12]
    res = _execute_tool(app, 'screen_action', args, **(ctx or {}))
    try:
        return json.loads(res[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return None


# ── 눈금·형식 ────────────────────────────────────────────────────────────────

def _norm(name):
    return str(name or '').strip().lower().replace(' ', '_')


def _is_fahrenheit(unit):
    u = str(unit or '').strip().lower()
    return u in ('°f', 'f', '℉', 'degf', 'fahrenheit')


def _scale_for(measurement, unit, value):
    """(min, max) 또는 None. 모르는 측정 항목은 None — 게이지를 만들지 않는다."""
    k = _norm(measurement)
    for prefix, (lo, hi) in _SCALE:
        if k.startswith(prefix):
            if prefix in ('temperature', 'dew_point') and _is_fahrenheit(unit):
                lo, hi = lo * 9 / 5 + 32, hi * 9 / 5 + 32
            if 'pressure_deficit' in prefix or prefix == 'vpd':
                f = _VPD_FROM_KPA.get(str(unit or '').strip().lower(), 1.0)   # 눈금은 kPa — Pa 로 저장한 VPD 도 있다
                lo, hi = lo * f, hi * f
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                pad = (hi - lo) * 0.05 or 1.0
                lo = min(lo, value - pad) if value < lo else lo
                hi = max(hi, value + pad) if value > hi else hi
            return lo, hi
    return None


#: 원문 단위 → 표시 단위(이력 readings 의 'u' 는 "C"·"percent" 로 온다; 최신값 채널은 unit_label 을 따로 준다).
_UNIT_DISP = {'c': '°C', 'f': '°F', 'celsius': '°C', 'fahrenheit': '°F',
              'percent': '%', 'pct': '%'}


def _unit_disp(unit):
    if unit in (None, ''):
        return None
    return _UNIT_DISP.get(str(unit).strip().lower(), str(unit))


def _value_text(value, unit):
    """메시지 글줄용 — 숫자 + 단위 한 덩이."""
    txt = server_card._num(value)
    return ('%s %s' % (txt, unit)) if unit else txt


# ── 타일 만들기 ──────────────────────────────────────────────────────────────

def _build(kind, body):
    """(제목, 본문글, [스펙…]) 또는 None."""
    tiles, lines = (_gauges(body) if kind == 'gauge' else _sparks(body))
    tiles = tiles[:MAX_TILES]
    if not tiles:
        return None
    title = _title(body)
    message = '\n'.join(lines[:server_card.MAX_LINES])
    return title, message, tiles


def _title(body):
    name = None
    if isinstance(body, dict):
        name = body.get('name') or server_card._name_of(body)
        if not name:
            rows = body.get('results')
            if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict):
                name = rows[0].get('name') or (rows[0].get('result') or [{}])[0].get('device_name') \
                    if isinstance(rows[0].get('result'), list) else rows[0].get('name')
    elif isinstance(body, list) and body and isinstance(body[0], dict):
        name = body[0].get('device_name')
    return str(server_card._t('%(place)s reading', place=name)) if name else str(server_card._t('Reading'))


def _reading_dicts(body):
    """measure.latest 본문 → [(prefix_name, reading_dict), …]. 단수·다중 모두 평탄화."""
    if isinstance(body, dict):
        rows = body.get('results')
        if isinstance(rows, list):
            out = []
            for r in rows:
                if isinstance(r, dict) and 'value' in r:
                    out.append((r.get('name'), r))
            return out
        if 'value' in body or 'channels' in body:
            return [(None, body)]
    return []


def _comfort_ranges(device_id, cache):
    """장치 → 게이지 녹색 `{measurement: (lo, hi)}`. 출처는 셋이고 **앞의 것이 이긴다**(측정마다):

      1. 구획이 정한 범위 — 시설 코디네이터 `stage_guide`, 없으면(노지) 참조 구획의 단계 한계
         (정본·판정은 `coordinator_plot.comfort_ranges_for_device`).
      2. 지도·구획 카드가 쓰는 5단계 밴드의 적정 구간(밴드 3) — 시설 `view_options.sensor_ranges`,
         없으면 앱 기본값(`utils/sensor_bands.py`, 온도·습도·VPD 만). 지도 라벨 색·구획 카드
         초록과 **같은 표**라 세 화면이 같은 녹색을 말한다.
         단, 구획 프로그램이 그 항목을 정했으면(값 하나인 습도 한계·VPD 목표 포함) 2 를 쓰지 않는다
         — 프로그램 위에 앱 기본 범위를 덧그리면 화면이 두 기준을 동시에 말한다(구획 카드와 같은 규칙).

    카드 하나를 그리는 동안 장치마다 한 번만 해석한다(배치·구획 조회가 비싸다). 실패·없음은 빈
    dict 로 캐시해 되풀이 조회를 막는다 — 녹색이 없을 뿐 게이지는 그대로 나온다."""
    if not device_id:
        return {}
    if device_id in cache:
        return cache[device_id]
    try:
        from aot.aot_flask.geo import coordinator_plot
        precise = coordinator_plot.comfort_ranges_for_device(device_id) or {}
    except Exception:                                       # noqa: BLE001
        logger.exception('[server_viz] comfort ranges failed')
        precise = {}
    out = dict(_display_bands(device_id))
    out.update(precise)
    cache[device_id] = out
    return out


def _display_bands(device_id):
    """장치 → 시설 밴드(없으면 앱 기본)의 적정 구간, 프로그램이 정한 항목은 뺀다. 실패하면 빈 dict."""
    try:
        from aot.aot_flask.geo import coordinator_plot
        from aot.utils import sensor_bands
        spoken = coordinator_plot.program_spoken_measurements(device_id)
        bands = sensor_bands.ok_bands(_facility_sensor_ranges(coordinator_plot.facility_of_device(device_id)))
    except Exception:                                       # noqa: BLE001
        logger.exception('[server_viz] display bands failed')
        return {}
    return {k: v for k, v in bands.items() if k not in spoken}


def _facility_sensor_ranges(facility_uuid):
    """시설 → `view_options.sensor_ranges` | None (지도 라벨이 읽는 그 칸, `AoT_facility.py`)."""
    if not facility_uuid:
        return None
    from aot.databases.models import GeoFacility
    fac = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    vo = (getattr(fac, 'view_options', None) or {}) if fac else {}
    if not isinstance(vo, dict):
        return None
    return vo.get('sensor_ranges') or None


#: VPD 밴드는 kPa — 값 단위가 Pa·hPa 면 밴드를 그 단위로 옮긴다(JS `BAND_UNIT_SCALE` 의 역).
_VPD_FROM_KPA = {'pa': 1000.0, 'hpa': 10.0, 'kpa': 1.0}


def _band_for(ranges, measurement, unit):
    """측정 항목 → 적정 밴드 (lo, hi) | None. 온도는 눈금과 같은 규칙으로 화씨 환산한다."""
    if not ranges:
        return None
    k = _norm(measurement)
    if k.startswith('temperature') or k == 'temp':
        band = ranges.get('temperature')
        if band and _is_fahrenheit(unit):
            return (band[0] * 9 / 5 + 32, band[1] * 9 / 5 + 32)
        return band
    if k.startswith('relative_humidity') or k.startswith('humidity') or k == 'rh':
        return ranges.get('relative_humidity')
    if k.startswith('vapour_pressure_deficit') or k.startswith('vapor_pressure_deficit') or k == 'vpd':
        band = ranges.get('vapor_pressure_deficit')
        f = _VPD_FROM_KPA.get(str(unit or '').strip().lower(), 1.0)
        return (band[0] * f, band[1] * f) if band else None
    return None


def _gauge_from(label, value, unit, measurement, ok=None):
    scale = _scale_for(measurement, unit, value)
    if scale is None or not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    lo, hi = scale
    if lo == hi:
        return None
    # valueText 는 숫자만 — 단위는 unit 칸이 머리줄에 따로 붙는다(둘 다 넣으면 "22.2 C C").
    spec = {'viz': 'gauge', 'value': float(value), 'min': lo, 'max': hi,
            'valueText': server_card._num(value)}
    if label:
        spec['label'] = label
    if unit:
        spec['unit'] = str(unit)
    # 적정 밴드(녹색) — 구획(시설 코디네이터)이 정한 범위. 눈금 안으로 좁혀서 얹는다.
    # 값이 눈금 밖이라 눈금이 넓혀졌어도 밴드는 그 넓힌 눈금 안에 머문다.
    if ok:
        a, b = (ok[0], ok[1]) if ok[0] <= ok[1] else (ok[1], ok[0])
        a, b = max(lo, a), min(hi, b)
        if b > a:
            spec['okMin'] = a
            spec['okMax'] = b
    return spec


def _gauges(body):
    tiles, lines = [], []
    cache = {}
    for prefix, d in _reading_dicts(body):
        chans = d.get('channels') if isinstance(d.get('channels'), list) else None
        picked = chans[:MAX_CHANNELS] if chans else [d]       # d 는 top-level 에 value·unit·unit_label 을 가진다
        ranges = _comfort_ranges(d.get('device_id'), cache)
        for c in picked:
            meas = c.get('measurement')
            unit = c.get('unit_label') or _unit_disp(c.get('unit'))   # "°C"·"%" (원문 "C"·"percent" 아님)
            base = server_card._measure(meas) if meas else (prefix or '')
            label = ('%s %s' % (prefix, base)).strip() if prefix else base
            spec = _gauge_from(label or None, c.get('value'), unit, meas,
                               ok=_band_for(ranges, meas, unit))
            if spec is None:
                continue
            tiles.append(spec)
            lines.append('%s %s' % (label or base, _value_text(c.get('value'), unit)))
            if len(tiles) >= MAX_TILES:
                return tiles, lines
    return tiles, lines


def _series_lists(body):
    """measure.history 본문 → [(prefix_name, [row…]), …]. 단수(list)·다중({results}) 모두."""
    if isinstance(body, list):
        return [(None, body)]
    if isinstance(body, dict):
        rows = body.get('results')
        if isinstance(rows, list):
            # 단수 대상: results = 채널 행들(각자 readings). 다중 대상: results = {requested, result:[행들]}.
            if rows and isinstance(rows[0], dict) and 'readings' in rows[0]:
                return [(None, rows)]
            out = []
            for r in rows:
                inner = r.get('result') if isinstance(r, dict) else None
                if isinstance(inner, list) and inner:
                    out.append((r.get('requested') if isinstance(r, dict) else None, inner))
            return out
    return []


def _downsample(vals, limit=files.VIZ_MAX_POINTS):
    if len(vals) <= limit:
        return vals
    step = (len(vals) - 1) / (limit - 1)
    return [vals[min(len(vals) - 1, round(i * step))] for i in range(limit)]


def _sparks(body):
    tiles, lines = [], []
    for _prefix, rows in _series_lists(body):
        for row in rows[:MAX_CHANNELS]:
            if not isinstance(row, dict):
                continue
            readings = row.get('readings')
            if not isinstance(readings, list):
                continue
            pts = [r.get('v') for r in readings
                   if isinstance(r, dict) and isinstance(r.get('v'), (int, float)) and not isinstance(r.get('v'), bool)]
            if len(pts) < 2:
                continue
            pts = _downsample([float(p) for p in pts])
            meas = row.get('measurement')
            label = server_card._measure(meas) if meas else row.get('device_name')
            unit = _unit_disp(next((r.get('u') for r in readings if isinstance(r, dict) and r.get('u')), None))
            # valueText 는 숫자만 — 단위는 unit 칸이 머리줄에 따로 붙는다(게이지와 같은 규칙, 둘 다 넣으면 "26.4 °C °C").
            spec = {'viz': 'spark', 'points': pts, 'valueText': server_card._num(pts[-1])}
            if label:
                spec['label'] = str(label)
            if unit:
                spec['unit'] = str(unit)
            span = _span_label(row)
            if span:
                spec['span'] = span
            tiles.append(spec)
            lines.append('%s %s' % (label or '', _value_text(pts[-1], unit)))
            if len(tiles) >= MAX_TILES:
                return tiles, lines
    return tiles, lines


def _span_label(row):
    """이력 구간 라벨 — row.period.asked(사람이 물은 말) 가 있으면 그대로, 없으면 None."""
    p = row.get('period') if isinstance(row.get('period'), dict) else None
    asked = str((p or {}).get('asked') or '').strip() if p else ''
    return asked[:files.VIZ_SPAN_MAX] if asked else None
