# coding=utf-8
"""식생 구획(작기)의 적산온도(GDD)·일적산광량(DLI) — `plot_context` 에서 뗀 조각.

`plot_context.py` 의 함수 83개 중 이 묶음(GDD·DLI)은 밖으로 나가는 참조가
`plot_sources`·`aot.utils.*` 뿐이라 안전하게 뗄 수 있었다(`plot_context` 자신을
들여오지 않는다 — 들여오면 순환이 생긴다). `plot_context` 가 이 모듈을 들여와
이름을 재노출한다.

설계 정본: docs/design/geo-vegetation-plot.md
"""
import logging
from datetime import date
from datetime import datetime as _datetime
from datetime import timedelta as _timedelta
from datetime import timezone as _tzmod
from time import monotonic as _monotonic

logger = logging.getLogger(__name__)


# ── GDD (적산온도) ──────────────────────────────────────────────────────────
#
# 자료 커버리지 하한. 센서가 며칠 비면 그만큼 덜 쌓이고 단계가 조용히 뒤처진다 —
# 화면에는 "아직 육묘기" 로만 보이고 왜인지는 어디에도 없다. 그래서 부족하면
# GDD 를 **쓰지 않고** 날짜로 되돌아가되, 되돌아간 이유를 함께 싣는다.
#
# 이 값은 사실이 아니라 **정책**이다. 옳은 숫자가 따로 있는 것이 아니라, 어디까지
# 비면 판정을 포기할지 정한 것이다.
_GDD_MIN_COVERAGE = 0.8

# 온도로 볼 측정 이름. `DeviceMeasurements.measurement` 어휘를 그대로 쓴다.
_GDD_TEMP_MEASURE = 'temperature'

# 일별 최고·최저 캐시. 지나간 하루는 변하지 않으므로 다시 조회하지 않는다.
# TTL 은 뒤늦게 들어오는 과거 데이터(백필·재전송)를 위한 것이다.
_EXTREMES_CACHE = {}
_EXTREMES_TODAY = {}
_EXTREMES_TTL = 1800.0
# 오늘 하루는 계속 쌓이는 중이라 짧게만 붙잡는다. 목록 화면 한 장이 같은
# 채널을 구획 수만큼 다시 묻는 것을 막는 정도의 수명이다.
_EXTREMES_TODAY_TTL = 60.0
_EXTREMES_MAX_DAYS = 500
_EXTREMES_MAX_KEYS = 400


def _daily_extremes(device_id, channel, measure, start_ts, end_ts, tz,
                    bucket_sec):
    """장치 채널의 **일별 최고·최저** → {date: (tmax, tmin)}.

    Influx 에 창 집계를 시킨다 — 원자료를 다 받아 파이썬에서 접으면 몇 달치가
    수만 점이 된다. 쿼리는 장치당 2회(최고·최저)지, 날짜당 2회가 아니다.

    **하루는 현지 달력의 하루다.** 예전에는 `group_sec=86400` 으로 Influx 에
    직접 하루를 시켰는데, 창은 UTC 에폭에 정렬되므로 한국·일본에서는 그
    "하루" 가 현지 09:00~09:00 이었다. 최고기온(오후)은 제자리에 들어가지만
    **최저기온(새벽)이 전날 통에 들어가** 짝이 어긋난다.

    ⚠ 게다가 `aggregateWindow` 의 라벨은 구간의 **오른쪽 경계**라(`bucket_
      local_key` 주석) 빼지 않으면 모든 날짜가 하루씩 밀린다 — 예전 코드가
      `rec.get_time().date()` 를 그대로 썼다. 두 결함이 겹쳐 실측에서
      쿠마모토 딸기가 270.4(11일)로 나왔고, 현지일로 접으면 292.0(12일)이다.

    그래서 **시간별로 받아 파이썬에서 현지 일로 접는다**(`plot_journal.
    daily_channel_stats` 와 같은 방식). 쿼리 수는 그대로 채널당 2회다 —
    돌려받는 행이 24배가 될 뿐이고, 그 규모는 일지가 이미 감당하고 있다.

    **마지막 버킷은 버린다.** 오늘은 아직 안 끝났고, 그대로 두면 하루가 절반만
    쌓인 채 더해진다(그날의 Tmax 가 낮게 잡혀 GDD 가 과소평가된다).

    ⚠ **환산(Conversion)이 걸린 채널은 `measure` 인자를 그대로 쓰면 0건이
    나온다.** `return_measurement_info` 가 환산 채널에서는 measurement 를
    비우기 때문에(unit 만 바꿔 준다) — InfluxDB 에 그 이름 태그로 저장돼
    있지 않다는 뜻이다(`plot_journal._channel_info` 의 "온도 8채널 누락"
    사고와 같은 함정). 그래서 호출자가 준 이름을 무조건 믿지 않고 여기서
    다시 확인한다 — 실측: F→C 환산 채널을 `measure='temperature'` 로 물으면
    0건, 필터를 비우면(device+channel+unit 만) 하루치가 그대로 나온다.
    """
    from aot.databases.models import Conversion, DeviceMeasurements
    from aot.utils.influx import query_string
    from aot.utils.system_pi import return_measurement_info

    try:
        dm = DeviceMeasurements.query.filter_by(
            device_id=device_id, channel=channel).first()
        if dm is not None:
            conv = None
            if dm.conversion_id:
                conv = Conversion.query.filter(
                    Conversion.unique_id == dm.conversion_id).first()
            _, _, resolved = return_measurement_info(dm, conv)
            measure = resolved
    except Exception:
        pass   # 못 찾으면 호출자가 준 이름 그대로 시도(과거 동작 유지)

    from aot.utils.timekit import bucket_local_key, local_day_bounds_utc

    # ── 지나간 하루는 다시 재지 않는다 ────────────────────────────
    #
    # 이 조회는 **몇 달치를 시간별로** 받아 온다(창 3600초). 구획 하나가
    # 온도 채널 4개를 가지면 최고·최저로 8회, 목록 화면은 그것을 구획 수만큼
    # 반복한다 — 실측: 구획 26개에 27만 행. 그런데 **어제까지의 최고·최저는
    # 변하지 않는다.** 바뀌는 것은 오늘 하루뿐이다.
    #
    # 그래서 지난 날짜는 프로세스 캐시에서 꺼내고 오늘만 다시 잰다.
    # TTL 을 두는 이유는 **뒤늦게 들어오는 과거 데이터** 때문이다(백필·
    # 재전송·게이트웨이 지연). 캐시가 정본이 되면 그 데이터가 영영 안 보인다.
    _now = _monotonic()
    ck = (device_id, channel, measure, bucket_sec, str(getattr(tz, 'key', tz)))
    hit = _EXTREMES_CACHE.get(ck)
    if hit is not None and _now - hit['at'] > _EXTREMES_TTL:
        hit = None
    try:
        s_day = _local_day_of(start_ts, tz)
        e_day = _local_day_of(end_ts, tz, back=True)
        today_local = _datetime.now(_tzmod.utc).astimezone(tz).date()
    except Exception:                                       # noqa: BLE001
        s_day = e_day = today_local = None

    # **값이 아니라 '조회한 구간'을 기억한다.** 값만 기억하면 데이터가 없는
    # 날이 영영 "아직 안 본 날" 로 남아 캐시가 한 번도 안 걸린다(실측: 온도
    # 채널 하나가 비어 있어 매번 전량 재조회했다).
    settled_to = (today_local - _timedelta(days=1)) if today_local else None
    if hit and s_day and e_day and settled_to is not None:
        need_from, need_to = s_day, min(e_day, settled_to)
        if (need_to < need_from
                or (hit['from'] <= need_from and hit['to'] >= need_to)):
            have = hit['days']
            out = {d: v for d, v in have.items() if s_day <= d <= e_day}
            if e_day >= today_local:
                out.update(_today_extremes(device_id, channel, measure, tz,
                                           bucket_sec, today_local, ck, _now))
            return out

    res = _query_daily_extremes(device_id, channel, measure,
                                start_ts, end_ts, tz, bucket_sec)
    if today_local is not None and s_day and e_day:
        keep = dict((hit or {}).get('days') or {})
        keep.update({d: v for d, v in res.items() if d < today_local})
        # 무한히 자라지 않게 가장 오래된 것부터 버린다.
        if len(keep) > _EXTREMES_MAX_DAYS:
            for d in sorted(keep)[:len(keep) - _EXTREMES_MAX_DAYS]:
                keep.pop(d, None)
        if len(_EXTREMES_CACHE) > _EXTREMES_MAX_KEYS:
            _EXTREMES_CACHE.clear()
        lo = min(s_day, hit['from']) if hit else s_day
        hi = max(min(e_day, settled_to), hit['to']) if hit else min(e_day, settled_to)
        _EXTREMES_CACHE[ck] = {'at': _now, 'days': keep, 'from': lo, 'to': hi}
    return res


def _today_extremes(device_id, channel, measure, tz, bucket_sec, today, ck,
                    now_m):
    """오늘 하루의 최고·최저. 짧은 수명으로 붙잡는다."""
    from aot.utils.timekit import local_day_bounds_utc

    slot = _EXTREMES_TODAY.get(ck)
    if (slot and slot['day'] == today
            and now_m - slot['at'] <= _EXTREMES_TODAY_TTL):
        return dict(slot['days'])
    t0, t1 = local_day_bounds_utc(today, today, tz)
    got = _query_daily_extremes(device_id, channel, measure, t0, t1, tz,
                                bucket_sec)
    if len(_EXTREMES_TODAY) > _EXTREMES_MAX_KEYS:
        _EXTREMES_TODAY.clear()
    _EXTREMES_TODAY[ck] = {'day': today, 'at': now_m, 'days': dict(got)}
    return got


def _local_day_of(ts, tz, back=False):
    """`local_day_bounds_utc` 가 만든 경계 문자열 → 현지 날짜.

    끝 경계(`back=True`)는 **다음 날 자정**이라 1초를 빼야 그 구간의 마지막
    날이 나온다.
    """
    d = _datetime.strptime(str(ts), '%Y-%m-%dT%H:%M:%SZ').replace(
        tzinfo=_tzmod.utc)
    if back:
        d -= _timedelta(seconds=1)
    return d.astimezone(tz).date()


def _query_daily_extremes(device_id, channel, measure, start_ts, end_ts, tz,
                          bucket_sec):
    """`_daily_extremes` 의 실제 조회부. 캐시를 거치지 않는다."""
    from aot.utils.influx import query_string
    from aot.utils.timekit import bucket_local_key

    out = {}
    for fn in ('max', 'min'):
        try:
            tables = query_string(
                'C', device_id, channel=channel, measure=measure,
                start_str=start_ts, end_str=end_ts,
                group_sec=bucket_sec, group_fn=fn)
        except Exception as exc:
            logger.debug('GDD: %s 조회 실패(%s): %s', device_id, fn, exc)
            return {}
        for table in (tables or []):
            for rec in table.records:
                try:
                    day = bucket_local_key(rec.get_time(), bucket_sec, tz)
                    val = float(rec.get_value())
                except (TypeError, ValueError, AttributeError):
                    continue
                if day is None:
                    continue
                cur = out.get(day) or [None, None]
                idx = 0 if fn == 'max' else 1
                # 같은 날짜가 두 번 나올 수 있다(창 경계). 극값으로 접는다.
                if cur[idx] is None:
                    cur[idx] = val
                elif fn == 'max':
                    cur[idx] = max(cur[idx], val)
                else:
                    cur[idx] = min(cur[idx], val)
                out[day] = cur
    return {d: (v[0], v[1]) for d, v in out.items()
            if v[0] is not None and v[1] is not None}


def gdd_accumulated(plot, program_row=None, on=None, with_series=False):
    """구획의 누적 GDD → dict (판정 불가면 `usable=False` + 이유).

    `GDD_day = max(0, (Tmax + Tmin) / 2 - T_base)` 를 날마다 더한다. 사용자가 고른
    공식이고, 하루 두 값만 있으면 되므로 센서 해상도에 덜 민감하다.

    ⚠ `env_control/cumulative_tracker` 의 GDD 와 **다른 값이다.** 그쪽은 제어
    보상용으로 사이클마다 적분하고 env_coordinator 함수가 있어야 한다. 노지
    구획에는 코디네이터가 없으므로 여기에 얹을 수 없다. 두 값이 다른 것은
    정상이다 — 한쪽을 다른 쪽에 맞추려 하지 말 것(docs/design/program-layer.md).

    ## 어느 센서의 값인가 — 날짜마다 정한다

    출처는 `plot_sources.resolve` 가 **기간별로** 준다(위치 이력 × 바인딩
    이력). 떼어낸 센서도 그 기간에는 출처이고, 구획 안에 새 센서가 찍혀도 그
    전 날짜는 구역 센서가 채운다 — 날짜마다 값이 있는 것 중 가장 좁은 출처를
    쓴다(`plot_sources.choose`).
    """
    from datetime import timedelta

    info = {'usable': False, 'value': None, 'reason': None,
            't_base': None, 'days_counted': 0, 'days_expected': 0,
            'coverage_pct': None, 'sensor_count': 0, 'target': None}

    if program_row is None:
        return dict(info, reason='no-program')

    photo = getattr(program_row, 'photosynthesis', None) or {}
    t_base = photo.get('T_base') if isinstance(photo, dict) else None
    try:
        t_base = None if t_base is None else float(t_base)
    except (TypeError, ValueError):
        t_base = None
    if t_base is None:
        # 지어내지 않는다 — 기준온도가 없으면 GDD 라는 값이 성립하지 않는다.
        return dict(info, reason='no-t-base')
    info['t_base'] = t_base

    # 목표 — 프로그램의 "하루 권장 GDD"(`gdd_daily`, program-settings.js
    # 'Suggested GDD per day')를 지금까지 지난 날수만큼 곱한다. 프로그램이
    # 주는 것은 하루 치 비율뿐이고 실측(`value`)은 누적이라, 그대로 나란히
    # 놓으면 단위가 안 맞는다 — **여기서 하루치를 누적으로 환산**해야 DLI 의
    # "오늘 값 / 오늘 목표" 와 같은 화면 문법(현재/목표)을 쓸 수 있다.
    gdd_daily = photo.get('gdd_daily') if isinstance(photo, dict) else None
    try:
        gdd_daily = None if gdd_daily is None else float(gdd_daily)
    except (TypeError, ValueError):
        gdd_daily = None

    start = getattr(plot, 'started_on', None)
    if start is None:
        return dict(info, reason='no-start-date')
    today = on or date.today()
    end = min(getattr(plot, 'ended_on', None) or today, today)
    if end < start:
        return dict(info, reason='not-started')
    # ⚠ **기대일수와 집계 범위가 같은 날들을 가리켜야 한다.** 예전에는
    #   기대일수만 오늘을 빼고(`(end-start).days`) 집계는 오늘까지 담아,
    #   현지일로 접자마자 커버리지가 109% 로 나왔다 — 분모와 분자가 다른
    #   날 집합을 세고 있었다는 뜻이다.
    #
    #   오늘을 빼는 이유는 아직 안 끝났기 때문이므로, **끝난 작기(ended_on
    #   이 과거)에는 마지막 날도 온전한 하루**라 그대로 센다.
    last = end - timedelta(days=1) if end >= today else end
    if last < start:
        return dict(info, reason='too-early')
    info['days_expected'] = (last - start).days + 1
    if gdd_daily is not None:
        info['target'] = round(gdd_daily * info['days_expected'], 1)
    if info['days_expected'] <= 0:
        return dict(info, reason='too-early')

    # 구간도 **현지 자정** 기준이다 — UTC 자정으로 자르면 첫날의 새벽과
    # 마지막 날의 저녁이 통째로 빠진다(그 자체로 하루가 덜 세어진다).
    from aot.aot_flask.geo import plot_sources
    from aot.utils.device_tz import resolve_location_tz
    from aot.utils.timekit import as_tz, bucket_seconds_for, local_day_bounds_utc

    tz = as_tz(resolve_location_tz(getattr(plot, 'unique_id', None)))
    # 창 크기는 **기간 전체를 보고** 정한다 — 서머타임 전환이 끼면 오프셋이
    # 둘이라, 한쪽만 보면 나머지 절반에서 현지 자정이 창 경계를 벗어난다.
    bucket_sec = bucket_seconds_for(tz, start, end)
    start_dt, end_dt = local_day_bounds_utc(start, end, tz, as_str=False)

    channels = plot_sources.channels_for(
        plot_sources.resolve(plot, start_dt, end_dt)['indoor'],
        (_GDD_TEMP_MEASURE,))
    info['sensor_count'] = len(channels)
    if not channels:
        return dict(info, reason='no-temperature-sensor')

    # 날짜마다 후보를 모은다. 출처의 기간이 조회 창 전체면 일별 극값 캐시를
    # 쓰고, 잘린 기간(떼어낸 센서·새로 단 센서)은 캐시를 거치지 않는다 —
    # 잘린 날의 절반 값이 캐시에 남아 다음 전체 조회에 섞이면 안 된다.
    _fmt = '%Y-%m-%dT%H:%M:%SZ'
    per_day = {}
    for src, dm in channels:
        for p_from, p_to in src['periods']:
            whole = (p_from, p_to) == (start_dt, end_dt)
            fetch = _daily_extremes if whole else _query_daily_extremes
            extremes = fetch(src['device_id'], dm.channel, _GDD_TEMP_MEASURE,
                             p_from.strftime(_fmt), p_to.strftime(_fmt),
                             tz, bucket_sec)
            for day, (tmax, tmin) in (extremes or {}).items():
                if day < start or day > last:
                    continue
                per_day.setdefault(day, []).append(
                    {'tier': src['tier'], 'rank': src['rank'],
                     'tmax': tmax, 'tmin': tmin})

    # 그날 쓸 출처의 채널이 여럿이면 **날마다 평균**한다. 최고끼리·최저끼리
    # 평균하는 것이라 한 센서의 이상값이 그날을 통째로 끌고 가지 않는다.
    total = 0.0
    series = []
    for day in sorted(per_day):
        chosen = plot_sources.choose(per_day[day], lambda c: True)
        maxes = [c['tmax'] for c in chosen]
        mins = [c['tmin'] for c in chosen]
        t_avg = (sum(maxes) / len(maxes) + sum(mins) / len(mins)) / 2.0
        gain = max(0.0, t_avg - t_base)
        total += gain
        series.append((day, gain))

    # 계열은 **요청할 때만** 싣는다. 몇 달치면 수백 항목이라 응답에 그대로
    # 들어가면 모달 페이로드가 부풀고, 화면은 그 값을 쓰지도 않는다.
    # 쓰는 곳은 하나다 — 단계가 넘어간 **날짜**를 되짚는 자리(P7 자동 승인).
    if with_series:
        info['series'] = series

    info['days_counted'] = len(per_day)
    info['value'] = round(total, 1)
    info['coverage_pct'] = round(
        100.0 * len(per_day) / info['days_expected'], 1)

    if len(per_day) < info['days_expected'] * _GDD_MIN_COVERAGE:
        return dict(info, reason='low-coverage')
    return dict(info, usable=True)


# 빛을 재는 measurement — `plot_journal.LIGHT_MEASUREMENTS` 와 같은 어휘.
_DLI_LIGHT_MEASURES = frozenset({'radiation', 'light'})


def _light_channel_sum(device_id, channel, unit, factor, start_str, end_str):
    """이 채널의 [start_str, end_str] 구간 PPFD 적분 → `(mol/m², 표본 수)`.
    조회 실패면 None.

    표본 수를 함께 내는 이유: 밤에는 적분이 0 인 것이 정상이라, 적분값만으로는
    "빛이 없었다" 와 "센서가 값을 안 냈다" 가 구별되지 않는다 — 날짜별 출처
    선택(`plot_sources.choose`)은 뒤쪽만 건너뛰어야 한다.
    """
    from aot.utils.influx import query_string

    try:
        tables = query_string(
            unit, device_id, channel=channel, measure=None,
            start_str=start_str, end_str=end_str,
            group_sec=3600, group_fn='mean')
    except Exception as exc:
        logger.debug('DLI: %s 조회 실패: %s', device_id, exc)
        return None
    total = 0.0
    samples = 0
    for table in (tables or []):
        for rec in table.records:
            try:
                val = float(rec.get_value())
            except (TypeError, ValueError, AttributeError):
                continue
            total += val * factor * 3600.0 / 1e6
            samples += 1
    return total, samples


def dli_accumulated(plot, program_row=None, on=None):
    """구획의 **오늘치** DLI(일적산광량) → dict (판정 불가면 `usable=False` + 이유).

    PPFD(µmol/m²/s) 시간평균을 그날 자정부터 지금까지 더한다(`plot_journal.
    daily_channel_stats` 의 mol 적분과 같은 식). `gdd_accumulated` 와 달리 재배
    시작일부터의 누적이 아니라 **그날 하루만** 본다 — 빛은 그날 값이 그날의
    광합성을 결정하고, 여러 날을 더해 봤자 뜻이 없다.

    ⚠ `env_control/cumulative_tracker` 의 DLI 와 **다른 값이다**(그쪽은 제어
    사이클마다 적분하고 env_coordinator 함수가 있어야 한다 — `gdd_accumulated`
    독스트링의 같은 경고와 같은 이유). 두 값을 섞지 말 것.

    단위 환산은 `aot.utils.light_units.LIGHT_UNITS_TO_PPFD` 를 그대로 쓴다
    (모르는 단위는 환산하지 않는다 — 두 번째 환산표를 만들지 않는다).

    출처는 GDD 와 같다(`plot_sources.resolve`). **실외(기상)까지 포함한다** —
    일사는 대지에 하나 있는 기상대가 재고, 구획 안에 온습도계가 있다는 이유로
    빠지면 안 된다. 실내는 값을 낸 것 중 가장 좁은 출처만, 실외는 전부 더한다.
    """
    from aot.aot_flask.geo import plot_sources
    from aot.databases.models import Conversion
    from aot.utils.device_tz import resolve_location_tz
    from aot.utils.light_units import ppfd_factor
    from aot.utils.system_pi import return_measurement_info
    from aot.utils.timekit import as_tz, local_day_bounds_utc

    info = {'usable': False, 'value': None, 'reason': None,
            'target': None, 'sensor_count': 0, 'assumed': None}

    target = None
    if program_row is not None:
        photo = getattr(program_row, 'photosynthesis', None) or {}
        target = photo.get('dli_target') if isinstance(photo, dict) else None
        try:
            target = None if target is None else float(target)
        except (TypeError, ValueError):
            target = None
    info['target'] = target

    today = on or date.today()
    tz = as_tz(resolve_location_tz(plot.unique_id))
    start_dt, end_dt = local_day_bounds_utc(today, today, tz, as_str=False)

    found = plot_sources.resolve(plot, start_dt, end_dt)
    channels = plot_sources.channels_for(found['indoor'] + found['outdoor'],
                                         _DLI_LIGHT_MEASURES)
    info['sensor_count'] = len(channels)
    if not channels:
        return dict(info, reason='no-light-sensor')

    _fmt = '%Y-%m-%dT%H:%M:%SZ'
    indoor, outdoor = [], []
    for src, dm in channels:
        conv = None
        if getattr(dm, 'conversion_id', None):
            conv = Conversion.query.filter(
                Conversion.unique_id == dm.conversion_id).first()
        _ch, unit, _meas = return_measurement_info(dm, conv)
        factor, is_assumed = ppfd_factor(unit)
        if factor is None:
            continue          # 모르는 단위 — 지어내지 않는다
        value, samples, answered = 0.0, 0, False
        for p_from, p_to in src['periods']:
            got = _light_channel_sum(src['device_id'], dm.channel, unit, factor,
                                     p_from.strftime(_fmt), p_to.strftime(_fmt))
            if got is None:
                continue
            answered = True
            value += got[0]
            samples += got[1]
        if not answered:
            continue
        cand = {'tier': src['tier'], 'rank': src['rank'], 'value': value,
                'samples': samples, 'assumed': is_assumed}
        (outdoor if src['scope'] == 'outdoor' else indoor).append(cand)

    chosen = (plot_sources.choose(indoor, lambda c: c['samples'] > 0)
              + outdoor)
    if not chosen:
        return dict(info, reason='unknown-light-unit')

    info['value'] = round(sum(c['value'] for c in chosen), 2)
    info['assumed'] = any(c['assumed'] for c in chosen)
    return dict(info, usable=True)
