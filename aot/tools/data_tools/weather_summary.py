# -*- coding: utf-8 -*-
"""날씨 응답의 요약형 — 기본은 항목마다 최저·최고·평균·피크 시각만, 시계열은 요청할 때만.

관측(`get_weather`)은 항목마다 최근 값 5건, 예보(`get_weather_forecast`)는 시간 행
전부를 실어 응답이 5.8~10.5KB 였다. 질문 대부분("오늘 최고기온·바람")은 극값과 그
시각이면 끝나므로 기본을 요약으로 하고, 시계열은 `detail`·`measurement` 로 부를 때만 싣는다.

요약은 새 값을 만들지 않는다 — 안쪽 도구가 읽은 행에서 최소·최대·합을 셀 뿐이다
(원천은 그대로, 여기는 산출 모양만).

## 시간별 예보 입력의 지나간 구간 (`lead_points`)

`OPEN_METEO_HOURLY_FORECAST` 의 +1h·+3h·+6h 채널은 **받은 시각에 찍힌, L 시간 뒤를 가리키는 값**이다. 그대로 요약하면
같은 낮 최고가 12:00·09:00·06:00 에 있는 것처럼 보이고(2026-10-31 실측, 실제 대상 시각은 13:00), 강수는 같은 칸이
수집마다 다시 쌓여 곱절이 된다(10-29~30: 그대로 더하면 1.2 mm, 칸으로 세면 0.6 mm — 발표본 L0 와 같다). 순간값은
저장 시각 + 리드로 옮기고, 칸 값은 칸(끝나는 정시)마다 마지막 발표 하나만 남긴다.
"""
import math
import re

#: 요약 모드에서 관측 창의 기본(시간). 장치 주기로 넓어진 창이 더 길면 그쪽을 쓴다.
DEFAULT_WINDOW_H = 24

#: 예보 행에서 시각이 아닌 칸.
_NON_VALUE_KEYS = ('hour_offset', 'time', 'date')

#: 상세 모드(detail) 관측에서 항목당 시계열 상한(limit 를 주지 않았을 때).
DETAIL_READINGS = 24


def _norm(word):
    return re.sub(r'[\s\-]+', '_', str(word or '').strip().lower())


def wants_summary(detail):
    """`detail` 이 명시적으로 False 일 때만 요약이다. None(옛 호출)은 예전 모양 그대로."""
    return detail is False or str(detail).strip().lower() in ('false', '0', 'no')


def wants_full(detail):
    return detail is True or str(detail).strip().lower() in ('true', '1', 'yes')


def lead_points(points, lead_h, kind, start, end):
    """시간별 예보 채널의 [(저장 epoch, 값)] → 대상 시각 [(epoch, 값)](시각순). 구간은 대상 시각 기준이다.

    instant: 저장 시각 + 리드. 구간 start ≤ t ≤ end.
    cell: 그 값이 든 칸의 끝 정시(`ceil(저장 + 리드)`). 끝나지 않은 칸은 값이 아직 없으므로 start < 칸끝 ≤ end.
    한 칸·한 시각에 값이 여럿이면 나중에 발표된 값(대상에 더 가까운 값)만 남긴다."""
    lead_s = float(lead_h) * 3600.0
    out = {}
    for ts, v in sorted(points):
        if kind == 'cell':
            at = int(math.ceil((ts + lead_s) / 3600.0)) * 3600
            inside = start < at <= end
        else:
            at = ts + lead_s
            inside = start <= at <= end
        if inside:
            out[at] = v
    return sorted(out.items())


def cell_total(points, seconds):
    """누적 강수 판독 [(epoch, 값)] → (기간 합, 칸 수). 한 값이 `seconds` 를 덮으므로 칸마다 마지막 값만 더한다.

    수집 주기가 누적 구간보다 짧으면(5분마다 읽는 15분 합, 10분마다 읽는 1시간 합) 같은 비가 판독마다 다시 들어 있다.
    그대로 더하면 몇 배가 된다(2026-10-29~30 Open-Meteo 지금 칸: 7.2 mm, 시간 칸으로 0.6 mm)."""
    cells = {}
    for ts, v in sorted(points):
        cells[int(math.ceil(ts / float(seconds)))] = v
    return round(sum(cells.values()), 2), len(cells)


def is_rain_amount(measurement, unit):
    """강수'량' 채널인가 — 강수 확률(percent)·감우기(none)는 더할 값이 아니다."""
    name = str(measurement or '').lower()
    return ('rain' in name or 'precipitation' in name) and str(unit or '').lower() in (
        'mm', 'in', 'mm_h', 'mm/h', 'mm_hr', 'in_h', 'in/h')


def lead_row(head, points, unit, stamp, keep):
    """대상 시각 점 → `get_sensor_detail` 한 줄과 같은 모양(요약·카드·제어 비교가 그대로 읽는다)."""
    values = [v for _t, v in points]
    readings = [{'t': stamp(t), 'v': round(v, 2), 'u': unit} for t, v in points]
    row = dict(head, readings=readings[-keep:], total_readings=len(readings), stats={
        'min': round(min(values), 2), 'max': round(max(values), 2),
        'avg': round(sum(values) / len(values), 2), 'count': len(values),
        'max_at': readings[values.index(max(values))]['t'],
        'min_at': readings[values.index(min(values))]['t']})
    return row


def field_tokens(fields):
    """`sensor_type` → 소문자 낱말 목록(문자열 하나나 쉼표 목록도 받는다)."""
    if not fields:
        return []
    if isinstance(fields, str):
        fields = re.split(r'[,\s]+', fields)
    return [t for t in (_norm(f) for f in fields) if t]


def _matches(name, token):
    """항목 이름이 낱말과 맞는가 — 'wind' 가 wind_speed 에, 'temp' 가 temperature_2m 에 맞는다."""
    n = _norm(re.sub(r'\s*\(.*?\)\s*$', '', str(name)))
    return token in n or n in token


#: 일상어 → 저장·예보에서 쓰는 이름의 한 토막.
_ALIASES = {'rain': 'precipitation', 'rainfall': 'precipitation', 'humidity': 'relative_humidity',
            'rh': 'relative_humidity', 'temp': 'temperature', 'solar': 'shortwave_radiation',
            'radiation': 'shortwave_radiation', 'light': 'shortwave_radiation',
            'wind': 'wind', 'gust': 'wind_gusts', 'pressure': 'pressure', 'cloud': 'sky_condition',
            'sky': 'sky_condition'}


def pick_fields(names, tokens):
    """(남길 이름 목록, 못 찾은 낱말 목록)."""
    keep, missing = [], []
    for tok in tokens:
        alias = _ALIASES.get(tok, tok)
        hit = [n for n in names if _matches(n, tok) or _matches(n, alias)]
        if hit:
            for n in hit:
                if n not in keep:
                    keep.append(n)
        else:
            missing.append(tok)
    return keep, missing


def parse_window(time_range):
    """'24h'·'3d'·'2w'·숫자 → 시간. 못 읽으면 None(날짜 구간 등은 안쪽 도구가 읽는다)."""
    m = re.fullmatch(r'\s*(\d+)\s*([hdw]?)\s*', str(time_range or '').lower())
    if not m:
        return None
    n = int(m.group(1))
    return n * {'h': 1, '': 1, 'd': 24, 'w': 168}[m.group(2)]


def window_label(base_label, time_range, summary):
    """관측 창 문자열(`3h` 꼴) — 요청·기본·장치 창 중 넓은 쪽. 날짜 구간은 요청 그대로."""
    base_h = parse_window(base_label) or 1
    if time_range:
        asked = parse_window(time_range)
        if asked is None:
            return str(time_range)              # FROM/TO 같은 구간 — 안쪽 도구가 푼다
        base_h = max(base_h, asked)
    elif summary:
        base_h = max(base_h, DEFAULT_WINDOW_H)
    return "%dh" % base_h


def _short_time(t):
    """ISO 시각 → 'MM-DD HH:MM'(같은 날 한 응답 안이라 연도는 뺀다)."""
    s = str(t or '')
    return s[5:16].replace('T', ' ') if len(s) >= 16 else s


def _row_label(row):
    """항목을 고르는 글 — 측정 이름에 채널 이름을 붙인다('구름'·'solar' 는 저장 이름 sky_condition·light 에 없다)."""
    channel = row.get('channel')
    return '%s %s' % (row.get('measurement'), channel) if channel else row.get('measurement')


def _sum_fields(st):
    keys = ('sum', 'missing_hours', 'sum_why')
    return {k: st[k] for k in keys if st.get(k) is not None}


def summarize_observed(out, tokens=None):
    """`get_weather` 응답(항목 목록 `data`)을 항목당 한 줄로 접는다.

    줄: measurement·unit·latest·latest_at·min·max·avg·max_at·min_at. 안쪽 도구가
    `peaks=True` 로 읽어 stats 에 max_at/min_at 이 들어 있다. 항목 목록이 아닌 응답
    (오류·후보 안내)은 그대로 둔다.

    이미 끝난 구간(`period_ended`)이면 latest·latest_at 대신 last·last_at 이다 — 구간 안의 마지막 값이지
    지금 값이 아니다. 도메인 표면이 읽은 줄(`channel`)은 같은 측정이 여럿이거나 예보 리드일 때 채널을 밝히고,
    강수량 줄은 기간 합(`sum`)을 싣는다.
    """
    data = out.get('data') if isinstance(out, dict) else None
    if not isinstance(data, list) or not data or not all(isinstance(r, dict) and 'stats' in r for r in data):
        return out
    rows = data
    missing = []
    if tokens:
        keep, missing = pick_fields([_row_label(r) for r in rows], tokens)
        rows = [r for r in rows if _row_label(r) in keep]
    latest = 'last' if out.get('period_ended') else 'latest'
    names = [r.get('measurement') for r in data]
    lines = []
    for r in rows:
        st = r.get('stats') or {}
        last = (r.get('readings') or [{}])[-1]
        line = {'measurement': r.get('measurement')}
        if r.get('channel') and (r.get('lead_h') or names.count(r.get('measurement')) > 1):
            line['channel'] = r['channel']
        line.update({
            'unit': last.get('u'),
            latest: last.get('v'),
            latest + '_at': _short_time(last.get('t')),
            'min': st.get('min'), 'min_at': _short_time(st.get('min_at')),
            'max': st.get('max'), 'max_at': _short_time(st.get('max_at')),
            'avg': st.get('avg'),
        })
        line.update(_sum_fields(st))
        lines.append(line)
    res = {k: v for k, v in out.items() if k != 'data'}
    res['summary'] = lines
    res['summary_note'] = ("Min/max/avg over the window with the time of each extreme; "
                           "pass detail=true or measurement=... for the readings series.")
    if missing:
        res['fields_not_found'] = missing
        res['available_fields'] = [r.get('measurement') for r in data]
    # 후보 장치 안내는 시계열 요청에서만 — 요약에는 개수만.
    others = res.pop('other_weather_devices', None)
    if others:
        res['other_weather_devices_count'] = len(others)
    res.pop('weather_pick', None)
    return res


def filter_observed(out, tokens):
    """상세 모드에서 `sensor_type` 로 항목을 고른다(시계열 그대로)."""
    data = out.get('data') if isinstance(out, dict) else None
    if not tokens or not isinstance(data, list) or not data:
        return out
    keep, missing = pick_fields([_row_label(r) for r in data if isinstance(r, dict)], tokens)
    res = dict(out)
    res['data'] = [r for r in data if isinstance(r, dict) and _row_label(r) in keep]
    if missing:
        res['fields_not_found'] = missing
        res['available_fields'] = [r.get('measurement') for r in data if isinstance(r, dict)]
    return res


def _stat_block(rows, key):
    pts = [(r.get('time') or r.get('date'), r.get(key)) for r in rows]
    pts = [(t, v) for t, v in pts if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not pts:
        return None
    lo = min(pts, key=lambda p: p[1])
    hi = max(pts, key=lambda p: p[1])
    block = {'min': round(lo[1], 2), 'min_at': _short_time(lo[0]),
             'max': round(hi[1], 2), 'max_at': _short_time(hi[0]),
             'avg': round(sum(v for _, v in pts) / len(pts), 2)}
    if key.startswith('precipitation ('):
        block['sum'] = round(sum(v for _, v in pts), 2)
        wet = next((t for t, v in pts if v > 0), None)
        if wet:
            block['first_at'] = _short_time(wet)        # 비가 시작되는 시각 — "언제부터 와?" 가 시계열 없이 답이 된다
    return block


#: 요약 모드에서 예보 응답에서 덜어내는 칸 — 격자·좌표 따위(출처·보정·주의는 남긴다).
_FORECAST_DROP = ('grid', 'latitude', 'longitude', 'elevation_m', 'source_segments', 'step_hours',
                  'requested_hours', 'count')


def summarize_forecast(result, tokens=None):
    """`get_weather_forecast` 의 시간 행을 항목별 극값·시각으로 접는다. 일 행은 이미 하루 요약이라 둔다."""
    if not isinstance(result, dict) or result.get('status') != 'success':
        return result
    rows = result.get('forecasts')
    period = result.get('period') or {}
    if not isinstance(rows, list) or not rows or period.get('daily'):
        return result                           # 일 단위(긴 기간)는 이미 요약이다
    # 조회는 끝 시각 행까지 싣는다(24h = 25행). 달력 하루 단위 요청(자정 시작, 24 의 배수)에서
    # 다음 날 00시 행이 요약에 섞이면 그날 강수·극값이 어긋난다(2026-11-03) — 요약에서만 뺀다.
    end = str(period.get('end') or '')
    if (str(period.get('start') or '').endswith('T00:00') and not (period.get('hours') or 0) % 24
            and len(rows) > 1 and str(rows[-1].get('time') or '') == end):
        rows = rows[:-1]
    keys = [k for k in rows[0] if k not in _NON_VALUE_KEYS]
    missing = []
    if tokens:
        keys, missing = pick_fields(keys, tokens)
    summary = {}
    for k in keys:
        blk = _stat_block(rows, k)
        if blk:
            summary[k] = blk
    res = {k: v for k, v in result.items() if k not in _FORECAST_DROP and k != 'forecasts'}
    res['summary'] = summary
    res['summary_rows'] = len(rows)
    if period.get('truncated') and rows[0].get('time') and rows[-1].get('time'):
        # 시간별 예보가 요청한 하루를 다 못 채웠다 — 요약이 덮는 시각을 알린다(일별 값은 하루 전체).
        res['covers'] = '%s to %s' % (_short_time(rows[0]['time']), _short_time(rows[-1]['time']))
    res['summary_note'] = ("Hourly rows folded to min/max/avg with the time of each extreme "
                           "(rain also sums); pass detail=true or measurement=... for the hourly rows.")
    if missing:
        res['fields_not_found'] = missing
        res['available_fields'] = [k for k in rows[0] if k not in _NON_VALUE_KEYS]
    return res


def filter_forecast(result, tokens):
    """상세 모드에서 `sensor_type` 로 예보 칸을 고른다(시간 행 그대로)."""
    if not tokens or not isinstance(result, dict):
        return result
    rows = result.get('forecasts')
    if not isinstance(rows, list) or not rows:
        return result
    avail = [k for k in rows[0] if k not in _NON_VALUE_KEYS]
    keep, missing = pick_fields(avail, tokens)
    keep_all = set(keep) | set(_NON_VALUE_KEYS)
    res = dict(result)
    res['forecasts'] = [{k: v for k, v in r.items() if k in keep_all} for r in rows]
    if missing:
        res['fields_not_found'] = missing
        res['available_fields'] = avail
    return res


def sun_day(st):
    """`solar.SunTimes` 하루치 → {date, sunrise, sunset}(그 위치 현지 HH:MM).

    새 출처가 아니다 — 주야 판정(`is_daytime`)·`get_local_time` 의 sun 블록과 같은 `aot.utils.solar`
    의 좌표 계산이다. 예보 출처를 쓰지 않으므로 어느 예보를 고르든 일출·일몰은 같다.
    극야·백야는 시각 대신 status 를 싣는다.
    """
    from aot.utils.timekit import tz_of
    tz = tz_of(st.tz_name)

    def hhmm(dt):
        return dt.astimezone(tz).strftime('%H:%M') if dt else None

    row = {'date': st.local_date.isoformat(), 'sunrise': hhmm(st.sunrise), 'sunset': hhmm(st.sunset)}
    if st.status != 'normal':
        row['status'] = st.status
    return row


def sun_for(lat=None, lon=None, target_id=None, dates=None):
    """장소의 일출·일몰. 좌표(또는 대상 id)를 못 풀면 None. `dates` 가 없으면 현지 오늘 한 줄(dict),
    있으면 날짜마다 한 줄(list)."""
    from aot.utils import solar
    try:
        if not dates:
            st = solar.sun_times(target_id=target_id, latitude=lat, longitude=lon)
            return sun_day(st) if st else None
        rows = []
        for d in dates:
            st = solar.sun_times(target_id=target_id, latitude=lat, longitude=lon, date=d)
            if st:
                rows.append(sun_day(st))
        return rows or None
    except Exception:                                       # noqa: BLE001
        return None


def period_dates(start, end):
    """예보 구간의 현지 날짜들('YYYY-MM-DDTHH:MM' 둘) — 끝 시각 직전까지."""
    from datetime import datetime, timedelta
    try:
        a = datetime.strptime(str(start)[:16], '%Y-%m-%dT%H:%M')
        b = datetime.strptime(str(end)[:16], '%Y-%m-%dT%H:%M') - timedelta(minutes=1)
    except (TypeError, ValueError):
        return []
    out, d = [], a.date()
    while d <= max(b.date(), a.date()) and len(out) < 15:
        out.append(d)
        d += timedelta(days=1)
    return out
