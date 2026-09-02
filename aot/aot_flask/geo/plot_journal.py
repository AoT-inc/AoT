# coding=utf-8
"""구획·구역 일지(Journal)의 **집계 엔진**.

일지는 site/zone/plot 과 기간을 받아 그 시점의 사실을 스냅샷으로 뜬다. 이
파일은 그 스냅샷의 **숫자를 만드는 부분**만 맡는다 — 대상에서 장치를 찾는 일
(`plot_context`), 노트를 모으는 일, 계약 dict 로 조립하는 일, 화면·라우트는
전부 바깥에 있다. 여기 있는 것은 전부 "입력을 받아 계산해서 돌려주는" 함수라
앱 컨텍스트만 있으면 단독으로 시험할 수 있다.

## 왜 시간 버킷을 받아서 파이썬에서 접는가 (이 파일의 핵심 결정)

Flux 의 `aggregateWindow` 는 **UTC 에폭 정렬**이고 기본 라벨이 `_stop`(구간의
오른쪽 경계)이다. `group_sec=86400` 을 그대로 쓰면 KST 에서 "하루" 가
09:00~익일 09:00 이 되고, 그 구간에 붙는 날짜는 **끝날**이다. 일지는 노트를
현지 날짜로 묶어 같은 줄에 놓으므로, 그대로 두면 **환경·제어 행과 노트 행이
하루 어긋난 채 나란히 놓인다.** 기존 `_daily_extremes`(GDD)가 이 문제를 안
겪는 이유는 합계만 쓰고 날짜 라벨을 사용자에게 보이지 않기 때문이다 — 일지는
라벨이 곧 산출물이라 그대로 물려받으면 안 된다.

`aggregateWindow` 에 `offset`/`timeSrc`/`timezone.location()` 을 얹는 안을
검토했지만 두 가지 이유로 버렸다. (1) 이 저장소는 `measurement_db_version`
1 과 2 를 **모두** 지원하는데(`influx.query_flux`) 그 구문을 쓴 선례가 저장소에
하나도 없다 — 확인되지 않은 Flux 기능 위에 날짜의 정확성을 얹지 않는다.
(2) 그러려면 **공유 쿼리 빌더(`influx.py`)를 고쳐야 하고**, 그 순간 그래프·
GDD·`runtime` 전부가 회귀 표면이 된다.

그래서 **시간 버킷으로 받아 여기서 현지 일자에 접는다.** `influx.py` 는 한 줄도
고치지 않는다(`group_sec` 에 3600 을 넘기는 것뿐이다). 덤으로 서머타임도
정확해진다 — 각 시간 버킷을 실제 tz 로 변환해 접으므로 전환일의 23시간/25시간
짜리 하루가 그대로 맞는다(고정 오프셋 방식이 못 하는 것이다).

### 치르는 대가 — 문서에 그대로 싣는다

- **일평균은 "시간평균의 평균"(시간 가중)이다.** 원자료를 그냥 더해 나눈 값
  (표본 가중)과 다르다. 로컬 실측(2026-09-02, KST 하루, 온도 채널 3개)에서
  차이는 **표본이 고를수록 0 에 수렴**했다 — 시간당 11~13개로 고른 채널은
  0.005도, 3~9개는 0.065도였다. 둘 중 어느 쪽이 "참" 인지는 정해져 있지
  않다. 표본 가중은 **자주 기록된 시간대로 값이 쏠리고**, 시간 가중은 각
  시간을 똑같이 센다 — 하루 평균으로 말할 때는 후자가 낫다.
- **정말 위험한 것은 근사가 아니라 결측이다.** 같은 실측에서 오차가 가장 컸던
  채널(0.193도)은 **24시간 중 7시간이 통째로 비어 있었다.** 그 경우 어떤
  평균을 쓰든 "그날의 평균" 이라고 말할 수 없는데, 숫자만 보면 알 방법이
  없다. 그래서 이 파일은 버킷마다 `samples`/`expected`/`coverage` 를 함께
  낸다 — GDD 가 `coverage_pct` 와 `_GDD_MIN_COVERAGE` 로 이미 하고 있는 것과
  같은 규율이다. **가리지 않고 함께 말하는 것이 이 설계의 답이다.**
- **min·max·누적계 차분·가동시간 합은 정확하다** — 접는 연산이 결합적이다.
- **반환 행이 24배**다(60일이면 채널·통계당 1,440행). 저사양 기기가 배포
  대상이므로 이것은 숨기지 않고 라우트의 승인 게이트가 행 예산으로 막는다.

## 이 파일이 하지 않는 것

- **판정을 새로 만들지 않는다.** 어떤 장치가 이 대상의 것인가는 `plot_context`·
  `device_membership` 이 정본이고, 여기서는 이미 정해진 장치 id 를 받는다.
- **실패를 삼키지 않는다.** 채널 조회가 실패하면 그 채널을 조용히 빼지 않고
  `errors` 에 담아 올린다 — 빠진 센서와 값이 없는 센서는 문서에서 전혀 다른
  뜻이고, 삼키면 "그날 데이터가 없었다" 로 읽힌다.
"""
import logging
import threading
import time
from datetime import date, datetime, timedelta

from aot.aot_flask.geo import plot_context

logger = logging.getLogger(__name__)

# ── 상수 ────────────────────────────────────────────────────────────────────

#: 이 일수를 넘으면 일별 상세 대신 주간 롤업으로 접는다. 문서를 읽을 수 있게
#: 하려는 것이지 부하를 줄이려는 것이 아니다 — 부하는 라우트의 승인 게이트가
#: 채널 수·기간·행 예산으로 막는다.
DAILY_DETAIL_MAX_DAYS = 60

#: 누적 계량기로 다루는 measurement. 값 자체가 "지금까지 총량" 이라 그날 사용량은
#: (그날 최대 − 그날 최소)로 파생한다. 확장은 여기 키 하나를 더하면 된다.
CUMULATIVE_METER_MEASUREMENTS = frozenset({'volume'})

#: 채널을 순회하며 쿼리를 쏘는 사이의 간격(초). 저사양 기기에서 짧은 버스트가
#: 공유 자원(InfluxDB·CPU)을 먹통으로 만드는 것은 이 저장소가 LoRaWAN 다운링크
#: 에서 이미 겪고 페이싱으로 해결한 실패다. 같은 원칙을 여기에도 적용한다.
QUERY_PACING_SEC = 0.05

#: 계약의 `caveats` 에 실어 문서 머리말에 찍는 문구 키. 번역은 화면에서 한다.
#: 값이 아니라 **키**인 이유: 문구를 여기서 한국어로 박으면 22개 로케일 중
#: 하나만 맞는 문서가 나온다.
AVG_IS_TIME_WEIGHTED = 'daily-average-is-mean-of-hourly-means'
CHANNEL_ZERO_ONLY = 'output-runtime-first-channel-only'

#: 이 비율 미만으로 시간이 채워진 버킷은 평균을 **믿을 수 없다**고 표시한다.
#: GDD 의 `_GDD_MIN_COVERAGE`(0.8)와 같은 값을 쓴다 — 같은 종류의 판단을 두 곳이
#: 다른 기준으로 하면 사용자가 둘을 대조할 수 없다.
MIN_COVERAGE = 0.8


# ── 시간 버킷 → 현지 일자 ───────────────────────────────────────────────────
#
# 접는 규칙 자체는 `aot/utils/timekit` 에 있다 — `aot/utils/runtime.py`(데몬도
# 쓰는 저수준 모듈)가 같은 규칙을 필요로 하는데, 그것을 여기 두면 저수준이
# Flask 계층을 임포트하게 되어 계층이 뒤집히고 실제로 순환 임포트가 된다.
# 여기서는 이름만 다시 내보낸다(이 파일을 읽는 사람이 규칙을 찾아갈 수 있게).

from aot.utils.timekit import (                                    # noqa: E402
    bucket_local_key as bucket_key,
    bucket_seconds_for,
    buckets_expected as expected_buckets,
    local_day_bounds_utc as period_bounds_utc,
)


def choose_granularity(start_date, end_date):
    """기간 → `'day'` | `'week'`. 경계는 `DAILY_DETAIL_MAX_DAYS`."""
    span = (end_date - start_date).days + 1
    return 'week' if span > DAILY_DETAIL_MAX_DAYS else 'day'


def bucket_labels(start_date, end_date, granularity):
    """구간 전체의 버킷 키 목록 → [date]. **값이 없는 버킷도 빠뜨리지 않는다.**

    조회 결과에 있는 날만 모으면 "그날 값이 없었다" 가 문서에서 통째로 사라져
    사람은 그 날이 원래 없었던 것으로 읽는다. 빈 버킷을 명시적으로 내보내는
    것이 이 함수의 존재 이유다.
    """
    out = []
    if granularity == 'week':
        cur = start_date - timedelta(days=start_date.weekday())
        while cur <= end_date:
            out.append(cur)
            cur += timedelta(days=7)
        return out
    cur = start_date
    while cur <= end_date:
        out.append(cur)
        cur += timedelta(days=1)
    return out


# ── 환경(Input) 채널 집계 ───────────────────────────────────────────────────

def _channel_info(dm_row):
    """DeviceMeasurements 행 → (channel, unit, measurement). 못 쓰면 (None,…).

    `return_measurement_info` 는 **환산(conversion)이 걸린 채널에서 measurement
    를 비운다**(unit 만 바꿔 준다). 그 상태로는 Influx 의 `measure` 태그를 맞출
    수 없어 조회가 성립하지 않으므로 건너뛴다 — 기존 정본
    (`aot_data_tool_service._latest_by_measurement`)이 `if not unit or not meas:
    continue` 로 하는 것과 같은 판단이고, 여기서 다르게 굴면 같은 센서가 화면과
    일지에서 다르게 보인다.
    """
    from aot.databases.models import Conversion
    from aot.utils.system_pi import return_measurement_info

    conv = None
    if getattr(dm_row, 'conversion_id', None):
        conv = Conversion.query.filter(
            Conversion.unique_id == dm_row.conversion_id).first()
    channel, unit, measurement = return_measurement_info(dm_row, conv)
    if not unit or not measurement:
        return None, None, None
    return channel, unit, measurement


def daily_channel_stats(dm_row, start_str, end_str, tz,
                        granularity='day', bucket_sec=3600):
    """한 채널의 구간 전체 → 버킷별 min/max/avg.

    ```
    {'device_id', 'channel', 'unit', 'measurement',
     'by_bucket': {date: {'min','max','avg'}}}
    ```
    조회 실패·조회 불가면 `None`(부르는 쪽이 `errors` 에 담는다).

    쿼리는 **채널당 정확히 3회**이고 기간과 무관하다(min·max·mean). 날짜마다
    한 번씩 묻는 구조로 만들면 두 달치가 180회가 된다 — `_daily_extremes` 가
    같은 이유로 창 집계를 쓴다.

    접는 규칙: min 은 시간별 최소의 최소, max 는 최대의 최대(둘 다 **정확**),
    avg 는 시간평균의 평균(**근사** — 모듈 머리말의 대가 1).
    """
    from aot.utils.influx import query_string

    channel, unit, measurement = _channel_info(dm_row)
    if unit is None:
        return None

    acc = {}                       # key -> {'min': [], 'max': [], 'mean': []}
    for fn in ('min', 'max', 'mean'):
        try:
            tables = query_string(
                unit, dm_row.device_id, channel=channel, measure=measurement,
                start_str=start_str, end_str=end_str,
                group_sec=bucket_sec, group_fn=fn)
        except Exception as exc:
            logger.warning('journal: 채널 조회 실패(%s ch=%s %s): %s',
                           dm_row.device_id, channel, fn, exc)
            return None
        for table in (tables or []):
            for rec in table.records:
                try:
                    val = float(rec.get_value())
                except (TypeError, ValueError, AttributeError):
                    continue
                key = bucket_key(rec.get_time(), bucket_sec, tz, granularity)
                if key is None:
                    continue
                acc.setdefault(key, {'min': [], 'max': [], 'mean': []})[fn].append(val)

    by_bucket = {}
    for key, box in acc.items():
        by_bucket[key] = {
            'min': min(box['min']) if box['min'] else None,
            'max': max(box['max']) if box['max'] else None,
            'avg': (sum(box['mean']) / len(box['mean'])) if box['mean'] else None,
            # 값이 있었던 시간 조각 수. 분모(`expected_buckets`)와 짝을 이뤄
            # "이 평균이 하루의 몇 할을 근거로 하는가" 를 말한다 — 실측에서
            # 7시간 결측인 채널이 멀쩡한 평균처럼 보였다(모듈 머리말).
            'samples': len(box['mean']),
        }
    return {'device_id': dm_row.device_id, 'channel': channel,
            'unit': unit, 'measurement': measurement, 'by_bucket': by_bucket}


def env_channel_series(device_ids, start_str, end_str, tz,
                       granularity='day', bucket_sec=3600):
    """센서 장치 id 목록 → 채널별 시계열 + 실패 목록.

    돌려주는 것은 `(series, errors)`.
    `series` 는 `[{device_id, channel, sensor, unit, measurement, by_bucket}]`
    로 **채널 하나가 한 항목**이다.

    ## 측정 이름으로 접지 않는 이유

    한 대상에 `temperature` 채널이 둘(공기·지온) 있는 것은 정상이고, 이름만으로
    갈리지 않는다. 실측에서 **공기 온도 목표가 토양 센서 값과 비교된 적이
    있다**(`aot_data_tool_service` 의 같은 주석). 그래서 하나를 골라 대표로
    삼지 않고 둘 다 내보내며, `sensor`(장치 이름)를 반드시 함께 싣는다 — 어느
    쪽을 볼지는 사람이 정한다.
    """
    from aot.databases.models import DeviceMeasurements, Input

    ids = [d for d in (device_ids or []) if d]
    if not ids:
        return [], []

    names = {i.unique_id: i.name for i in Input.query.filter(
        Input.unique_id.in_(ids)).all()}
    rows = DeviceMeasurements.query.filter(
        DeviceMeasurements.device_id.in_(ids)).all()

    series, errors = [], []
    for dm in rows:
        stats = daily_channel_stats(dm, start_str, end_str, tz,
                                    granularity=granularity,
                                    bucket_sec=bucket_sec)
        if stats is None:
            errors.append({'device_id': dm.device_id,
                           'channel': getattr(dm, 'channel', None),
                           'reason': 'query-failed-or-unusable'})
            time.sleep(QUERY_PACING_SEC)
            continue
        stats['sensor'] = names.get(dm.device_id) or dm.device_id
        series.append(stats)
        time.sleep(QUERY_PACING_SEC)
    return series, errors


# ── 누적 계량기(유량 등) ────────────────────────────────────────────────────

def cumulative_meter_series(series):
    """채널 시계열 중 **누적 계량기**인 것만 골라 낸다 → 같은 모양의 list."""
    return [s for s in (series or [])
            if str(s.get('measurement') or '').strip().lower()
            in CUMULATIVE_METER_MEASUREMENTS]


def usage_from_stats(stat):
    """누적 계량 채널 하나 → 버킷별 사용량 `{date: {'amount','unit'} | None}`.

    누적계는 값 자체가 "지금까지 총량" 이라 그날 쓴 양은 **그날 최대 − 최소**다.
    별도 쿼리가 필요 없다.

    ⚠ `max < min` 이면 **사용량을 지어내지 않고 `None`** 을 낸다. 계량기가
      리셋됐거나(교체·전원 차단) 값이 뒤집힌 것인데, 그대로 빼면 음수가 나오고
      절댓값을 취하면 "그날 엄청 썼다" 는 거짓이 된다.
    """
    out = {}
    for key, box in (stat.get('by_bucket') or {}).items():
        lo, hi = box.get('min'), box.get('max')
        if lo is None or hi is None or hi < lo:
            out[key] = None
            continue
        out[key] = {'amount': round(hi - lo, 3), 'unit': stat.get('unit')}
    return out


# ── 목표 대비 편차 ──────────────────────────────────────────────────────────

def delta_for(target, avg):
    """목표 항목 하나와 그날 평균 → `(delta, skipped_reason)`.

    **편차를 낼 수 없는 자리에서 숫자를 지어내지 않는 것이 이 함수의 전부다.**
    돌려주는 `skipped_reason` 이 화면 문구를 정한다.

    - `'method'` — 곡선을 따르는 항목. `_stage_targets` 가 애초에 값을 비운다
      (곡선의 '지금 값' 은 메서드마다 계산이 다르다). 조용히 빠뜨리면 목표가
      없는 것처럼 보이므로 "곡선을 따름" 으로 말한다.
    - `'when'` — 주간/야간 전용 목표. 하루 전체 평균과 견주면 **실측에서 야간
      12도 목표를 한낮 35.6도와 비교해 23.6도 차이라는 허위 경보가 났다**
      (`plot_context._stage_targets` 주석). 낮/밤 재분할은 별도 설계라 여기서는
      목표값만 적고 편차를 내지 않는다.
    - `'daily-shape'` — `shape='daily'` 항목(DLI 등). **하루치 적산 목표를
      순간값의 일평균과 빼면 차원이 다른 뺄셈**이고, 숫자가 나오기 때문에 틀린
      줄 모른다.
    - `'unobservable'` — 이 대상이 그 항목을 재는 센서를 안 가졌다.
    - `'no-reading'` — 잴 수는 있는데 그 버킷에 값이 없다.
    """
    if target.get('source') == 'method' or (
            target.get('value') is None and target.get('method_uuid')):
        return None, 'method'
    if target.get('value') is None:
        return None, 'no-target'
    if target.get('observable') is False:
        return None, 'unobservable'
    if target.get('when') in ('day', 'night'):
        return None, 'when'
    if target.get('shape') == 'daily':
        return None, 'daily-shape'
    if avg is None:
        return None, 'no-reading'
    try:
        return round(float(avg) - float(target['value']), 2), None
    except (TypeError, ValueError):
        return None, 'no-reading'


def attach_targets(env_rows, targets):
    """한 버킷의 환경 행들에 그 시기의 목표를 붙인다(제자리 수정) → env_rows.

    맞추는 기준은 `measurement` 다. **같은 목표가 두 행에 붙을 수 있다** —
    `temperature` 채널이 둘이면 둘 다 그 목표의 대상이고, 어느 쪽이 '진짜'
    인지는 시스템이 알 수 없다(`env_channel_series` 주석 참조). 하나를 골라
    붙이면 그 선택이 조용한 판정이 된다.
    """
    by_meas = {}
    for t in (targets or []):
        m = str(t.get('measurement') or '').strip().lower()
        if m:
            by_meas.setdefault(m, []).append(t)

    for row in env_rows:
        cands = by_meas.get(str(row.get('measurement') or '').strip().lower())
        if not cands:
            row['target'] = None
            row['delta'] = None
            row['delta_skipped'] = None
            row['when'] = None
            continue
        t = cands[0]
        delta, skipped = delta_for(t, row.get('avg'))
        row['target'] = t.get('value')
        row['target_label'] = t.get('label')
        row['delta'] = delta
        row['delta_skipped'] = skipped
        row['when'] = t.get('when')
        if skipped == 'method':
            row['follows_curve'] = t.get('method_name')
    return env_rows


# ── 버킷 조립 ───────────────────────────────────────────────────────────────

def env_rows_by_bucket(series, labels, tz=None, bucket_sec=3600,
                       granularity='day', period_start=None, period_end=None):
    """채널 시계열 → `{bucket_key: [env row, …]}`.

    값이 없는 버킷에도 **키를 만든다**(빈 리스트). 그래야 바깥에서 "그날은
    데이터가 없었다" 를 말할 수 있다 — 키가 없으면 그 날 자체가 사라진다.

    각 행에 `samples`/`expected`/`coverage`/`coverage_low` 를 싣는다. **평균만
    내보내면 결측을 숨긴다** — 실측에서 24시간 중 7시간이 빈 채널의 평균이
    멀쩡한 숫자로 보였다(모듈 머리말). 화면은 `coverage_low` 인 행의 평균을
    "참고값" 으로 표시해야 한다.
    """
    out = {key: [] for key in labels}
    exp_cache = {}
    for st in (series or []):
        is_meter = (str(st.get('measurement') or '').strip().lower()
                   in CUMULATIVE_METER_MEASUREMENTS)
        # 계량 채널이면 이 채널의 버킷별 사용량을 **한 번만** 계산해 두고
        # 아래에서 행마다 찾아 붙인다 — daily_channel_stats 가 이미 구한
        # min/max 를 재사용할 뿐 별도 쿼리를 내지 않는다(§4-4).
        usage_map = usage_from_stats(st) if is_meter else {}
        for key, box in (st.get('by_bucket') or {}).items():
            if key not in out:
                continue                # 구간 밖(경계 버킷) — 버린다
            if tz is not None and key not in exp_cache:
                exp_cache[key] = expected_buckets(
                    key, granularity, tz, bucket_sec,
                    period_start=period_start, period_end=period_end)
            expected = exp_cache.get(key)
            samples = box.get('samples') or 0
            coverage = (round(samples / expected, 3)
                        if expected else None)
            out[key].append({
                'device_id': st.get('device_id'),
                'channel': st.get('channel'),
                'sensor': st.get('sensor'),
                'measurement': st.get('measurement'),
                'unit': st.get('unit'),
                'min': box.get('min'),
                'max': box.get('max'),
                'avg': box.get('avg'),
                'samples': samples,
                'expected': expected,
                'coverage': coverage,
                # 평균을 지우지 않는다 — 지우면 "센서가 없었다" 와 구별이 안 된다.
                # 대신 믿을 만한지를 함께 말한다.
                'coverage_low': (coverage is not None
                                 and coverage < MIN_COVERAGE),
                # 누적 계량 채널(§4-4)만 값이 있다. ⚠ **`control` 이 아니라
                # 여기 싣는다** — 밸브(Output)와 유량계(Input)를 잇는 배선
                # 정보가 이 저장소 데이터 모델에 없어(§확정된 사실: Output 은
                # 통신방식만 알 뿐 의미 분류가 없다), "이 밸브가 이 유량계"
                # 라는 짝을 지어낼 근거가 없다. 유량계는 그 자체로 하나의
                # 측정 채널이므로 다른 env 행과 같은 자리에 둔다.
                'usage': usage_map.get(key),
            })
    for key in out:
        out[key].sort(key=lambda r: (str(r.get('measurement') or ''),
                                     str(r.get('sensor') or '')))
    return out


def control_rows_by_bucket(actuators, start_str, end_str, tz,
                           granularity='day', bucket_sec=3600, labels=None):
    """출력 장치 목록 → `({bucket_key: [control row, …]}, errors)`.

    `actuators` 는 `plot_context.actuators_for_plot()` 형태
    (`{'output_id','name','kind','scope'}`)를 기대한다. 가동시간은 **항상**
    싣는다 — Output 에는 "관수/난방" 같은 의미 분류 필드가 없어
    (`output_type` 은 통신방식일 뿐) 무엇을 한 장치인지 시스템이 모르기
    때문이고, 그래도 "얼마나 돌았나" 는 그 자체로 사실이다.

    ⚠ **`usage`(사용량)는 여기 없다.** 초안 계약은 그것을 control 행에
      두었지만, 어느 유량계가 어느 밸브에 딸린 것인지 이을 배선이 데이터
      모델에 없다(§확정된 사실). 지어내는 대신 유량계는 그 자체로 하나의
      env 행이 되어 `env_rows_by_bucket` 이 낸다.
    """
    from aot.utils.runtime import get_operational_seconds_by_day

    out = {key: [] for key in (labels or [])}
    errors = []
    for a in (actuators or []):
        oid = a.get('output_id')
        if not oid:
            continue
        try:
            by_bucket = get_operational_seconds_by_day(
                oid, start_str, end_str, tz=tz,
                granularity=granularity, bucket_sec=bucket_sec)
        except Exception as exc:
            logger.warning('journal: 가동시간 조회 실패(%s): %s', oid, exc)
            errors.append({'output_id': oid, 'reason': 'query-failed'})
            time.sleep(QUERY_PACING_SEC)
            continue
        for key, secs in by_bucket.items():
            if key not in out:
                continue
            out[key].append({
                'output_id': oid,
                'name': a.get('name'),
                'kind': a.get('kind'),
                'scope': a.get('scope'),
                'seconds': int(secs),
                'hours': round(secs / 3600.0, 2),
            })
        time.sleep(QUERY_PACING_SEC)
    for key in out:
        out[key].sort(key=lambda r: str(r.get('name') or ''))
    return out, errors


def stage_at(stages, on_day):
    """단계 목록(`stage_schedule_view` 결과)에서 그날이 속한 단계 → dict | None.

    ⚠ `stage_schedule_view` 의 `starts_on`/`ends_on` 은 **ISO 문자열**이다.
    ⚠ 그 결과의 `state`(`'done'|'current'|'future'`)는 **오늘 기준**이라
      일지에서는 쓰지 않는다 — 끝난 작기의 문서에 "current" 를 찍으면 거짓이다.
    """
    if not stages:
        return None
    found = None
    for st in stages:
        s = _as_date(st.get('starts_on'))
        if s is None or s > on_day:
            continue
        e = _as_date(st.get('ends_on'))
        if e is not None and on_day > e:
            continue
        found = st
    return found


def _as_date(iso):
    """ISO 문자열 → date. 못 읽으면 None."""
    if not iso:
        return None
    if isinstance(iso, date) and not isinstance(iso, datetime):
        return iso
    if isinstance(iso, datetime):
        return iso.date()
    try:
        return datetime.strptime(str(iso)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


# ── 노트 ────────────────────────────────────────────────────────────────────
#
# 노트가 대상에 걸리는 길은 **네 갈래**이고 넷 다 봐야 한다.
#
#   1. 대상 자신에 붙은 노트(`target_id` 가 그 도형/구획).
#   2. 자손에 붙은 노트 — 안쪽 도형·시설·구획·장치.
#   3. **좌표만 가진 노트** — 무엇에도 매이지 않고 지도의 그 자리에 찍어 적은
#      노트다(`target_type='map_location'` 등). 사용자가 특정 위치에서 본
#      현상을 기록하는 수단이라 일지의 목적에 정확히 해당한다.
#   4. 기간 — 위 셋을 통과한 것 중 일지 구간에 든 것.
#
# ## 정본이 둘인데 **어느 하나로도 부족하다**
#
# - `device_membership.note_ids_in_area()` 는 "공간에 붙은 노트 · 장치에 붙은
#   노트 · **좌표 노트**" 를 낸다. 그런데 자손 판정이 `_shapes_inside`(GeoShape)
#   + GeoFacility 까지라 **GeoPlot 을 보지 않는다.**
# - `geo_hierarchy.descendant_target_ids()` 는 구획까지 보지만 **좌표를 모른다.**
#
# 로컬 실측(2026-09-02, 노트 61건): `target_type='plot'` 이 **21건으로 최다**
# 이고 좌표를 가진 노트가 13건이다. 어느 하나만 쓰면 구역 일지에서 구획 노트가
# 통째로 빠지거나 그 자리에 적은 노트가 통째로 빠진다. 그래서 **합집합**이다.
#
# ## 출처를 버리지 않는다
#
# 각 노트에 `anchor` 를 붙인다 — `'target'`(대상 자신) · `'descendant'`(안쪽
# 구획·시설·장치) · `'position'`(그 자리에 찍은 좌표 노트). 출처를 지우면
# 사용자는 자기가 그 구역에 매어 쓴 적 없는 노트가 왜 여기 있는지 설명할 근거를
# 잃는다.

_MEDIA_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic',
              '.mp4', '.webm', '.mov')


def _parse_files(raw):
    """`Notes.files`(쉼표 구분 문자열) → `(media, others)`.

    ⚠ 리스트가 아니라 **문자열**이다. 노트 위젯도 `files.split(',')` 로 읽는다.
      비어 있는 조각(연속 쉼표·후행 쉼표)이 흔해서 털어내야 한다.
    """
    media, others = [], []
    for part in str(raw or '').split(','):
        name = part.strip()
        if not name:
            continue
        (media if name.lower().endswith(_MEDIA_EXT) else others).append(name)
    return media, others


def note_scope_for_target(target_type, target_row, device_ids=None):
    """대상 → 노트를 거는 근거 묶음. 판정 자체는 전부 기존 정본이 한다.

    ```
    {'self_id', 'descendant_ids': set, 'area_note_ids': set | None,
     'polygon': shapely geom | None, 'gps_skipped': str | None}
    ```

    `area_note_ids` 가 `None` 이면 **"거르지 않는다" 가 아니라 오류**다
    (`note_ids_in_area` 는 도형을 못 찾을 때 None 을 낸다). 빈 집합으로 접으면
    지워진 구역에 대해 "노트 없음" 일지가 조용히 만들어진다.
    """
    from shapely.geometry import shape as shapely_shape

    from aot.aot_flask.geo import device_membership, plot_context

    scope = {'self_id': getattr(target_row, 'unique_id', None),
             'descendant_ids': set(), 'area_note_ids': None,
             'polygon': None, 'gps_skipped': None}

    if target_type == 'plot':
        # 구획에 자손은 없다 — 노트는 그 GeoPlot 행에 직접 붙는다.
        #
        # ⚠ **시설 구획(has_own_geometry() == False)은 좌표 판정을 하지 않는다.**
        #   그 기하는 `geometry_of` 가 시설 외피에서 파생한 값이라, 그것으로 점
        #   포함을 세면 **시설 어딘가에 찍힌 노트가 전부 이 구획의 것**이 된다.
        #   `sensors_for_plot` 이 시설 구획에서 마커 판정을 아예 건너뛰는 것과
        #   정확히 같은 이유다 — 파생값을 사실처럼 쓰는 순간이다.
        if hasattr(target_row, 'has_own_geometry') and not target_row.has_own_geometry():
            scope['gps_skipped'] = 'facility-plot-derived-geometry'
            return scope
        geom = plot_context.geometry_of(target_row) or {}
        if geom.get('type') in ('Polygon', 'MultiPolygon'):
            try:
                scope['polygon'] = shapely_shape(geom)
            except Exception as exc:
                logger.warning('journal: 구획 기하 해석 실패(%s): %s',
                               scope['self_id'], exc)
                scope['gps_skipped'] = 'plot-geometry-unreadable'
        else:
            scope['gps_skipped'] = 'plot-has-no-polygon'
        return scope

    # zone/site — 두 정본의 합집합.
    from aot.utils.geo_hierarchy import descendant_target_ids

    more, _breakdown = descendant_target_ids(target_row, include_self=False)
    scope['descendant_ids'] = set(more) | set(device_ids or [])
    # 좌표 노트는 이쪽 정본이 이미 판정한다(폴리곤 점 포함). 여기서 다시
    # 세지 않는다 — 두 번째 판정 기준을 만들지 않는다.
    scope['area_note_ids'] = device_membership.note_ids_in_area(
        scope['self_id'], device_ids=device_ids)
    # 폴리곤은 **분류용**이다(수집은 위 정본이 이미 했다). `_anchor_of` 가
    # "좌표로 걸렸나" 를 소거법이 아니라 직접 확인하는 데 쓴다 — 아래 주석 참조.
    geom = plot_context.geometry_of(target_row) or {}
    if geom.get('type') in ('Polygon', 'MultiPolygon'):
        try:
            scope['polygon'] = shapely_shape(geom)
        except Exception:
            scope['polygon'] = None
    return scope


def _point_inside(note, scope):
    """이 노트의 좌표가 대상 폴리곤 안인가 → bool."""
    if scope['polygon'] is None:
        return False
    if note.gps_lat is None or note.gps_lng is None:
        return False
    try:
        from shapely.geometry import Point
        # ⚠ 순서는 (경도, 위도)다. 뒤집으면 지구 반대편이 되는데 **예외가 나지
        #   않아** 그냥 "그 안에 없다" 로 조용히 끝난다.
        return scope['polygon'].contains(Point(float(note.gps_lng),
                                               float(note.gps_lat)))
    except Exception:
        return False


def _anchor_of(note, scope):
    """이 노트가 **어떻게** 대상에 걸렸나 → 'target'|'descendant'|'position'|None.

    붙어 있는 쪽이 좌표보다 세다 — 구획에 매어 쓴 노트가 마침 그 안에 찍혀
    있다고 해서 "그 자리에 적은 노트" 로 부르면 사용자의 의도를 뒤집는다.

    ## 소거법으로 판정하지 않는다 (실측으로 드러난 결함)

    처음엔 "`note_ids_in_area` 가 잡았는데 내 자손 목록에 없으면 남는 근거는
    좌표뿐" 이라고 소거했다. **틀렸다.** 두 정본의 자손 판정 방식이 다르기
    때문이다 — `note_ids_in_area` 안쪽의 `_shapes_inside` 는 **기하**(대표점
    포함)로, `descendant_target_ids` 는 **계층**(부모 맵)으로 찾는다. 로컬
    실측에서 다른 site 폴리곤 안에 대표점이 든 site 에 붙은 노트가 잡혔고,
    좌표가 아예 없는데 `anchor='position'`(gps=None) 으로 분류됐다.

    그래서 **직접 증거로 판정한다**: 좌표가 실제로 폴리곤 안에 있을 때만
    `'position'` 이다. 아니면 부착으로 걸린 것이므로 `'descendant'` 다 —
    어느 자손인지까지는 두 해소기가 갈려 확정할 수 없지만, "이 대상 안의
    무언가에 붙어 있다" 는 사실은 정본이 이미 보증했다.
    """
    tid = note.target_id
    if tid and tid == scope['self_id']:
        return 'target'
    if tid and tid in scope['descendant_ids']:
        return 'descendant'
    if scope['area_note_ids'] is not None:
        if note.unique_id not in scope['area_note_ids']:
            return None
        return 'position' if _point_inside(note, scope) else 'descendant'
    # plot 대상 — 수집 정본이 없어 좌표 판정을 여기서 직접 한다.
    return 'position' if _point_inside(note, scope) else None


def _naive_utc(dt):
    """tz-aware 든 naive 든 → **naive UTC**. DB 비교 직전에 한 번 통과시킨다."""
    from aot.utils.timekit import ensure_utc

    if dt is None or getattr(dt, 'tzinfo', None) is None:
        return dt
    return ensure_utc(dt).replace(tzinfo=None)


def notes_for_target(target_type, target_row, start_utc, end_utc,
                     device_ids=None, tz=None):
    """대상+기간 → `(notes, meta)`. `notes` 는 계약(§6)의 노트 payload 목록.

    기간을 **SQL 에서 먼저 좁힌 뒤** 포함 판정을 돌린다 — 판정은 파이썬이라
    행이 적을수록 싸다.

    `meta['gps_skipped']` 가 차 있으면 그 대상에서는 좌표 노트를 세지 않았다는
    뜻이고, 그 사유를 문서의 `caveats` 에 실어야 한다(조용히 빼지 않는다).
    """
    from aot.databases.models import Notes
    from aot.utils.timekit import to_tz

    scope = note_scope_for_target(target_type, target_row, device_ids=device_ids)
    meta = {'gps_skipped': scope['gps_skipped'], 'anchors': {}}

    if target_type != 'plot' and scope['area_note_ids'] is None:
        raise ValueError('note_ids_in_area: 대상 도형을 찾을 수 없습니다 (%s)'
                         % scope['self_id'])

    # ⚠ **naive UTC 로 맞춘다.** `Notes.date_time` 은 naive UTC 로 저장되는데
    #   (실측: tzinfo=None, '2026-08-26 08:59:37.381816'), tz-aware 값을 그대로
    #   비교에 넣으면 SQLite 가 '+00:00' 이 붙은 문자열로 렌더해 **예외 없이
    #   어긋난 비교**를 한다 — 결과가 비면 "그 기간에 노트가 없었다" 로 읽힌다.
    start_utc = _naive_utc(start_utc)
    end_utc = _naive_utc(end_utc)

    # 구간은 반열림 [start, end) 이다. 닫으면 자정에 걸친 노트가 이틀에 다 실린다.
    rows = (Notes.query
            .filter(Notes.date_time >= start_utc, Notes.date_time < end_utc)
            .order_by(Notes.date_time.asc()).all())

    out = []
    for n in rows:
        anchor = _anchor_of(n, scope)
        if anchor is None:
            continue
        media, others = _parse_files(n.files)
        local = to_tz(n.date_time, tz) if tz is not None else n.date_time
        out.append({
            'unique_id': n.unique_id,
            'time': local.isoformat() if local is not None else None,
            'title': n.name,
            'body': n.note,
            'image_files': media,
            # 사진이 아닌 첨부(문서·로그)도 있었다는 사실을 지우지 않는다.
            'other_files': others,
            'anchor': anchor,
            'gps': ({'lat': n.gps_lat, 'lng': n.gps_lng}
                    if anchor == 'position' and n.gps_lat is not None else None),
        })
        meta['anchors'][anchor] = meta['anchors'].get(anchor, 0) + 1
    return out, meta


def notes_by_bucket(notes, labels, tz, granularity='day'):
    """노트 payload 목록 → `{bucket_key: [note, …]}`.

    묶는 기준은 **현지 날짜**다 — 환경·제어 버킷과 같은 시간대·같은 경계를
    써야 두 줄이 같은 하루를 말한다(모듈 머리말의 일 경계 규칙).
    """
    from datetime import datetime as _dt

    out = {key: [] for key in labels}
    for n in notes:
        if not n.get('time'):
            continue
        try:
            d = _dt.fromisoformat(n['time']).date()
        except (ValueError, TypeError):
            continue
        key = (d - timedelta(days=d.weekday())) if granularity == 'week' else d
        if key in out:
            out[key].append(n)
    return out


# ── 계약 조립 ───────────────────────────────────────────────────────────────
#
# `build_journal_for_target()`의 반환값이 정본이다(§6). §3~§5 의 조회·집계
# 함수를 부르고 §6 모양으로 담기만 한다 — 여기서 새 판정을 하지 않는다.
#
# ⚠ **`usage`(사용량)의 위치를 계획 초안에서 바꿨다.** 초안 계약은 control
#   (Output) 행에 `usage` 를 두었는데, 조립하며 실제로 짜 보니 **어느 유량계가
#   어느 밸브에 딸린 것인지 이을 배선이 데이터 모델에 없다**(Output 은
#   통신방식만 알 뿐 의미 분류가 없다 — §확정된 사실). 지어낼 근거가 없어
#   유량계를 그 자체로 하나의 env 행으로 두고 `usage` 를 거기 싣는다
#   (`env_rows_by_bucket` 참조). control 행에서는 `usage` 키를 아예 뺐다.

def _plot_sensor_ids(plot):
    """구획이 참조할 센서 id → set. 우선순위는 `sensors_for_plot()` 그대로.

    `measurable_in_plot()`(측정 이름만 필요)·`_plot_temperature_channels()`
    (GDD 채널)와 같은 우선순위를 세 번째로 반복한다 — 새 기준이 아니라 같은
    기준을 "이 구획이 참조하는 센서 id 전부" 라는 다른 산출물로 다시 읽는
    것뿐이다. 별도 공개 함수로 빼지 않은 이유는 소비처가 이 파일 하나뿐이기
    때문이다.
    """
    try:
        found = plot_context.sensors_for_plot(plot) or {}
    except Exception:
        return set()
    ids = (list(found.get('in_plot') or [])
           or list(found.get('in_bay') or [])
           or list(found.get('from_facility') or [])
           or list(found.get('from_zone') or []))
    return set(ids)


def _area_actuators(device_ids):
    """zone/site 참조 집합 → `actuators_for_plot()` 과 같은 모양의 목록.

    Output 에는 종류 분류가 없으므로(§확정된 사실) `kind` 는 늘 `None` —
    `valves_for_plot()` 경로(plot 노지)와 같은 한계다. `scope` 도 같은 이유로
    의미가 없어 `None` 이다(zone/site 대상엔 bay/facility 개념이 없다).
    """
    from aot.databases.models import Output

    ids = plot_context._only_output_ids(device_ids)
    if not ids:
        return []
    rows = Output.query.with_entities(Output.unique_id, Output.name).filter(
        Output.unique_id.in_(list(ids))).all()
    return [{'output_id': oid, 'name': name, 'kind': None, 'scope': None}
            for oid, name in rows]


#: `GeoPlot.kind` 어휘(plot 대상 전용). `'zone'`/`'site'` 와 **섞지 않는다** —
#: 실측(4단계)에서 zone/site 를 이 표로 찾으면 둘 다 'other' 로 떨어져 실제
#: `kind='other'` 인 구획과 라벨이 같아졌다. 대상 종류(target.type)와 구획
#: 종류(GeoPlot.kind)는 서로 다른 어휘다.
_PLOT_KIND_LABELS = {'vegetation': 'Vegetation', 'livestock': 'Livestock',
                     'facility': 'Facility', 'other': 'Other'}
_AREA_KIND_LABELS = {'zone': 'Zone', 'site': 'Site'}


def _gettext_safe(label):
    """실패해도 원문으로 떨어진다 — 배경 스레드에는 `flask_babel` 요청
    컨텍스트가 없을 수 있다(`program_io._public_target_def` 와 같은 방어).
    """
    try:
        from flask_babel import gettext
        return gettext(label)
    except Exception:
        return label


def _target_kind_label(target_type, kind):
    """대상 → 사람이 읽는 종류 라벨.

    `target_type='plot'` 이면 `GeoPlot.kind` 어휘(vegetation 등)를, zone/site
    면 그 자체를 라벨로 삼는다 — 두 어휘를 하나로 접지 않는다(위 상수 참조).
    """
    if target_type == 'plot':
        return _gettext_safe(_PLOT_KIND_LABELS.get(kind, _PLOT_KIND_LABELS['other']))
    return _gettext_safe(_AREA_KIND_LABELS.get(target_type, target_type))


def _target_summary(target_type, target_row, unassigned_areas=0):
    """대상 하나 → §6 계약의 `target` 절.

    `location`·`program`·`area_m2` 는 plot 에서만 값을 갖는다(zone/site 는
    구조상 그 개념이 없다 — 단계도 마찬가지라 `stages` 는 호출부가 따로
    `None` 을 채운다).
    """
    out = {
        'type': target_type,
        'unique_id': target_row.unique_id,
        'unassigned_areas': unassigned_areas,
    }
    if target_type == 'plot':
        out.update({
            'name': target_row.name or target_row.subject,
            'kind': target_row.kind or 'vegetation',
            'kind_label': _target_kind_label('plot', target_row.kind or 'vegetation'),
            'subject': target_row.subject,
            'variety': target_row.variety,
            'location': None,
            'program': None,
            'area_m2': None,
        })
        own_geom = target_row.has_own_geometry()
        out['area_m2'] = round(plot_context.area_m2(target_row), 1) if own_geom else None

        zone = plot_context.zone_for_plot(target_row)
        loc = {'zone_name': plot_context._shape_name(zone) if zone else None,
              'facility_name': None, 'bay_name': None}
        if target_row.facility_uuid:
            brief = plot_context.facility_brief(target_row.facility_uuid)
            loc['facility_name'] = brief.get('name')
            loc['bay_name'] = (brief.get('bay_names') or {}).get(target_row.bay_id)
        out['location'] = loc

        prog = plot_context.program_brief(target_row)
        if prog and not prog.get('missing'):
            out['program'] = {'name': prog.get('name'), 'version': prog.get('version')}
    else:
        # zone/site — GeoShape. 종류 자체가 대상 타입이라 kind == target_type.
        out.update({
            'name': plot_context._shape_name(target_row) or target_row.unique_id,
            'kind': target_type,
            'kind_label': _target_kind_label(target_type, None),
            'subject': None, 'variety': None,
            'location': None, 'program': None, 'area_m2': None,
        })
    return out


def _plot_stages(plot):
    """구획의 단계 목록(§6 `stages`) → list | None.

    경계·이름·지침은 `stage_schedule_view()`(공개 경로) 하나로 얻는다 — 전
    단계를 한 번에 낸다. 목표만 그 함수의 `_view_targets`(편집 UI 전용, 값을
    깎는다) 대신 `stage_targets_full()`(§4-5, `measurement`/`when`/`shape`/
    `observable` 을 보존)로 **바꿔치기**한다 — 같은 단계 정의(`effective_stages`
    가 낸 것)를 두 번 조회하지 않도록 한 번만 얻어 재사용한다.

    ⚠ `state`(`'done'|'current'|'future'`)는 **쓰지 않는다** — 오늘 기준이라
      끝난 작기의 일지에 "current" 를 찍으면 거짓이다(§4-5 경고).
    """
    sched = plot_context.stage_schedule(plot)
    if sched is None:
        return None
    view = plot_context.stage_schedule_view(plot, sched=sched)
    if not view:
        return None
    program_row = sched.get('program_row')
    full_by_key = {st.get('key'): st
                  for st in plot_context.effective_stages(plot, program_row)}

    out = []
    for b in view:
        raw = full_by_key.get(b.get('key'))
        out.append({
            'key': b.get('key'),
            'name': b.get('name'),
            'starts_on': b.get('starts_on'),
            'ends_on': b.get('ends_on'),
            'guidance': b.get('guidance'),
            'targets': plot_context.stage_targets_full(
                raw, program_row=program_row, plot=plot) if raw else [],
        })
    return out


def resolve_target_row(target_type, target_id):
    """대상 종류+id → ORM 행. 못 찾으면 `ValueError`.

    승인 게이트(§13a)와 조립(§6)이 **같은 함수로** 대상을 찾는다 — 둘이 다른
    경로로 찾으면 "게이트는 통과했는데 조립은 대상을 못 찾는" 상태가 생긴다.
    """
    if target_type == 'plot':
        from aot.databases.models import GeoPlot
        row = GeoPlot.query.filter_by(unique_id=target_id).first()
    elif target_type in ('zone', 'site'):
        from aot.databases.models import GeoShape
        row = GeoShape.query.filter_by(unique_id=target_id).first()
    else:
        raise ValueError('알 수 없는 대상 종류: %s' % target_type)
    if row is None:
        raise ValueError('대상을 찾을 수 없습니다 (%s/%s)' % (target_type, target_id))
    return row


def resolve_devices(target_type, target_row):
    """대상 → `(sensor_ids, actuators, unassigned_areas, area_device_ids)`.

    §3 의 정본 조합을 한 자리에 둔다. 승인 게이트가 **집계를 시작하기 전에**
    채널 수를 세려면 이 해소가 먼저 필요한데, 그것을 따로 짜면 게이트가 세는
    것과 실제로 도는 것이 갈린다.

    `area_device_ids` 는 zone/site 에서만 값을 갖는다 — `device_ids_in_area()`
    가 낸 **원본 참조 집합**(PID·함수 uuid 까지 포함)을 그대로 보존해 뒀다가
    노트 조회(§5)에 넘긴다. sensor/actuator id 만 추려 넘기면 그 사이(PID·
    함수에 직접 붙은 노트)가 빠진다 — `note_scope_for_target` 이 이 집합을
    `descendant_ids` 에 합치는 것이 정확히 그 갭을 메우는 자리다.
    """
    if target_type == 'plot':
        sensor_ids = _plot_sensor_ids(target_row)
        actuators, unassigned = plot_context.actuators_for_plot(target_row)
        return sensor_ids, actuators, unassigned, None

    from aot.aot_flask.geo import device_membership

    area_ids = device_membership.device_ids_in_area(target_row.unique_id)
    if area_ids is None:
        # ⚠ `None` 은 "거르지 않는다" 라는 그 함수의 계약이지 "장치가 없다" 가
        #   아니다. 빈 집합으로 접으면 **지워진 구역에 대해 "장치 없음" 일지가
        #   조용히 만들어진다**(§3).
        raise ValueError('대상 도형을 찾을 수 없습니다 (%s)' % target_row.unique_id)
    return (plot_context._only_sensor_ids(area_ids),
            _area_actuators(area_ids), 0, area_ids)


def count_channels(sensor_ids):
    """이 센서들이 실제로 조회될 **채널 수** → int.

    `env_channel_series` 가 도는 것과 같은 기준으로 센다 — 환산이 걸려
    measurement 가 빈 채널은 그쪽이 건너뛰므로(`_channel_info`) 여기서도
    빼야 게이트의 숫자가 실제 쿼리 수와 맞는다.
    """
    from aot.databases.models import DeviceMeasurements

    ids = [d for d in (sensor_ids or []) if d]
    if not ids:
        return 0
    rows = DeviceMeasurements.query.filter(
        DeviceMeasurements.device_id.in_(ids)).all()
    return sum(1 for dm in rows if _channel_info(dm)[1] is not None)


def build_journal_for_target(target_type, target_id, start_date, end_date):
    """site/zone/plot + 기간 → §6 계약 dict. 이 함수 하나가 정본이다.

    실패는 예외로 올린다(`ValueError`) — 라우트(§8)가 그것을 `status='error'`
    로 옮긴다. 여기서 빈 문서를 만들어 조용히 "성공"으로 접지 않는다.
    """
    if start_date > end_date:
        raise ValueError('시작일이 종료일보다 늦습니다')

    target_row = resolve_target_row(target_type, target_id)

    from aot.utils.timekit import as_tz
    from aot.utils.device_tz import resolve_location_tz

    tz = as_tz(resolve_location_tz(target_id))
    tz_name = str(getattr(tz, 'zone', None) or tz)
    bucket_sec = bucket_seconds_for(tz, start_date, end_date)
    granularity = choose_granularity(start_date, end_date)
    labels = bucket_labels(start_date, end_date, granularity)
    s_str, e_str = period_bounds_utc(start_date, end_date, tz)
    s_dt, e_dt = period_bounds_utc(start_date, end_date, tz, as_str=False)

    caveats = [AVG_IS_TIME_WEIGHTED]
    errors = []

    # ── 장치 조회(§3) ────────────────────────────────────────────────────
    (sensor_ids, actuators, unassigned_areas,
     area_device_ids) = resolve_devices(target_type, target_row)

    # ── 환경(§4-2~4-3) ───────────────────────────────────────────────────
    series, env_errors = env_channel_series(
        sensor_ids, s_str, e_str, tz, granularity=granularity,
        bucket_sec=bucket_sec)
    errors.extend({'kind': 'env', **e} for e in env_errors)
    env_by_bucket = env_rows_by_bucket(
        series, labels, tz=tz, bucket_sec=bucket_sec, granularity=granularity,
        period_start=start_date, period_end=end_date)

    # ── 목표 대비 편차(§4-5, plot 만) ────────────────────────────────────
    stages = None
    if target_type == 'plot':
        stages = _plot_stages(target_row)
        if stages:
            for key, rows in env_by_bucket.items():
                # 주간 버킷은 그 주의 월요일(현지)로 대표해 비교한다 — 단계가
                # 주 중간에 바뀌면 그 주는 월요일 쪽 단계로 잡힌다. 정확한
                # 주중 전환 판정은 이번 범위 밖이다(일별 상세로 보면 정확하다).
                st = stage_at(stages, key)
                if st is not None:
                    attach_targets(rows, st.get('targets') or [])

    # ── 제어(§4-4) ───────────────────────────────────────────────────────
    control_by_bucket, ctrl_errors = control_rows_by_bucket(
        actuators, s_str, e_str, tz, granularity=granularity,
        bucket_sec=bucket_sec, labels=labels)
    errors.extend({'kind': 'control', **e} for e in ctrl_errors)

    # ── 노트(§5) ─────────────────────────────────────────────────────────
    # plot 은 `note_scope_for_target` 이 device_ids 를 쓰지 않으므로 None 그대로
    # 넘긴다(구획엔 자손 개념이 없다 — §5).
    notes, note_meta = notes_for_target(
        target_type, target_row, s_dt, e_dt,
        device_ids=area_device_ids, tz=tz)
    notes_by_bkt = notes_by_bucket(notes, labels, tz, granularity=granularity)
    if note_meta.get('gps_skipped'):
        caveats.append('gps-notes-skipped:%s' % note_meta['gps_skipped'])

    # ── 버킷 조립 ────────────────────────────────────────────────────────
    def _label(key):
        if granularity == 'week':
            return '%s ~ %s' % (key.isoformat(), (key + timedelta(days=6)).isoformat())
        return key.isoformat()

    buckets = []
    for key in labels:
        env_rows = env_by_bucket.get(key) or []
        control_rows = control_by_bucket.get(key) or []
        note_rows = notes_by_bkt.get(key) or []
        buckets.append({
            'date_label': _label(key),
            'env': env_rows,
            'control': control_rows,
            'notes': note_rows,
            'empty': not (env_rows or control_rows or note_rows),
        })

    if actuators:
        # `control_rows_by_bucket` 은 항상 채널 0 으로 간다(§4-4) — 다채널
        # 출력에서는 첫 채널만 본다는 사실을 조용히 넘기지 않는다.
        caveats.append(CHANNEL_ZERO_ONLY)
    if errors:
        caveats.append('partial-query-failures:%d' % len(errors))
    if unassigned_areas:
        caveats.append('unassigned-areas:%d' % unassigned_areas)

    from aot.utils.timekit import utc_now

    return {
        'target': _target_summary(target_type, target_row, unassigned_areas)
                  | {'tz_name': tz_name,
                     'period': {'start': start_date, 'end': end_date,
                               'ongoing': (target_type == 'plot'
                                          and target_row.ended_on is None)}},
        'stages': stages,
        'granularity': granularity,
        'buckets': buckets,
        'caveats': caveats,
        'errors': errors,
        'generated_at': utc_now(),
    }


def caveat_text(key):
    """`caveats` 의 키 하나 → 뷰어 언어의 문장. HTML(§10)·MD(§11) 이 함께 쓴다.

    키로 저장해 둔 이유(모듈 상단 상수 주석)와 같다 — 문장을 저장하면 생성
    시점의 언어로 굳는다. `gps-notes-skipped:<사유>` 처럼 접미사가 붙는 키는
    ':' 로 갈라 사유별 문장을 고른다.
    """
    base, _, suffix = key.partition(':')

    if base == AVG_IS_TIME_WEIGHTED:
        return _gettext_safe(
            "Daily averages are the mean of hourly means, not a true "
            "time-weighted average of every reading.")
    if base == CHANNEL_ZERO_ONLY:
        return _gettext_safe(
            "Runtime is read from the first channel only, even for "
            "multi-channel outputs.")
    if base == 'partial-query-failures':
        return _gettext_safe(
            "%(n)s channel(s) could not be read and are missing from "
            "this journal.") % {'n': suffix}
    if base == 'unassigned-areas':
        return _gettext_safe(
            "%(n)s device area(s) overlap this plot with no device "
            "assigned yet.") % {'n': suffix}
    if base == 'gps-notes-skipped':
        if suffix == 'facility-plot-derived-geometry':
            return _gettext_safe(
                "Notes pinned to a map location are not included for "
                "facility plots — their outline is derived from the "
                "facility, not their own.")
        return _gettext_safe("Notes pinned to a map location were not checked.")
    return key


def journal_to_jsonable(journal_data):
    """계약 dict → JSON-safe dict. date/datetime 만 isoformat 으로, 그 외 그대로.

    HTML(§10)·MD(§11)·MCP(§12) 가 전부 이 함수의 결과(또는 계약 dict 원본)를
    같은 스키마로 받아야 하므로, 여기서 하는 일은 **직렬화뿐**이다 — 값을
    고르거나 감추지 않는다.
    """
    from datetime import date as _date, datetime as _datetime

    def _walk(v):
        if isinstance(v, _datetime):
            return v.isoformat()
        if isinstance(v, _date):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_walk(x) for x in v]
        if isinstance(v, set):
            return sorted(_walk(x) for x in v)
        return v

    return _walk(journal_data)


# ── Markdown 출력 (§11) ──────────────────────────────────────────────────────
#
# **PDF는 별도 생성기를 만들지 않는다** — HTML(§10)이 브라우저 인쇄로 그
# 자리를 대신한다. Markdown 은 옮겨 적기·다른 도구에 붙여넣기용으로 셋째
# 형식만 낸다.
#
# 이 함수는 **순수 문자열 조립**이다(새 의존성 없음) — HTML(Jinja)이 이미
# 낸 것과 같은 구조(개요 → 단계별 요약 → 버킷 루프)를 파이프 테이블로 옮긴다.
# 값을 고르거나 새로 계산하지 않는다 — §6 계약 dict 를 그대로 읽는다.
#
# `journal_data` 는 이미 **jsonable** 이어야 한다(`GeoJournal.data`, 즉
# `journal_to_jsonable()` 을 거친 뒤의 dict) — 날짜가 문자열이라고 가정한다.

def _md_escape(v):
    """파이프 테이블 셀 안에서 `|`·개행이 표를 깨는 것만 막는다."""
    if v is None:
        return ''
    return str(v).replace('|', '\\|').replace('\n', ' ').strip()


def _md_target_value(t):
    """목표 항목 하나 → 표 셀 문자열. 곡선은 값이 없다는 사실을 그대로 말한다."""
    if t.get('source') == 'method':
        return 'curve: %s' % (t.get('method_name') or '—')
    if t.get('value') is None:
        return ''
    unit = t.get('unit') or ''
    return ('%s %s' % (t['value'], unit)).strip()


def _md_delta_value(e):
    """편차 셀 — §4-5 의 스킵 사유를 사람이 읽을 문구로. 지어내지 않는다."""
    if e.get('delta') is not None:
        return str(e['delta'])
    reason = {
        'when': 'day/night target',
        'daily-shape': 'cumulative target',
        'method': 'follows curve',
        'unobservable': 'no sensor',
        'no-reading': 'no reading',
        'no-target': '',
    }.get(e.get('delta_skipped'), '')
    return reason


def _note_attachment_url(filename):
    """첨부 파일명 → **절대 URL**(`/note_attachment/<filename>`).

    Markdown 은 앱 밖(다른 도구·나중 시점)에서 열릴 수 있으므로 상대 경로가
    아니라 절대 URL이어야 한다 — `render_plot_journal_markdown` 은 단일
    인자(`journal_data`)만 받는 순수 함수라는 계약(§11)이 있어, base URL 을
    인자로 받는 대신 요청 컨텍스트에서 직접 구한다(이 함수는 `format=md`
    라우트 안에서만 불린다 — 배경 스레드에서 부르지 않는다).
    """
    from flask import url_for

    return url_for('routes_general.send_note_attachment', filename=filename,
                   _external=True)


def render_plot_journal_markdown(journal_data):
    """§6 계약 dict → Markdown 문자열(CommonMark 파이프 테이블).

    HTML(§10)과 같은 구조를 따른다: 캐비어트 → 개요 → 단계별 요약(plot만)
    → 버킷 루프(환경/제어/노트). 사진은 `/note_attachment/<filename>` 절대
    URL 링크로 낸다 — 서버가 살아있는 동안만 유효하다는 사실을 문구로 밝힌다.
    """
    t = journal_data.get('target') or {}
    lines = []

    title = t.get('name') or t.get('unique_id') or 'Journal'
    period = t.get('period') or {}
    lines.append('# %s' % title)
    lines.append('')
    lines.append('%s – %s%s' % (period.get('start'), period.get('end'),
                                ' (ongoing)' if period.get('ongoing') else ''))
    lines.append('')

    caveats = journal_data.get('caveats') or []
    if caveats:
        lines.append('> Photo links below point to `/note_attachment/...` '
                     'and stay valid only while the server is running.')
        for key in caveats:
            lines.append('> - %s' % caveat_text(key))
        lines.append('')

    # ── 개요 ─────────────────────────────────────────────────────────────
    lines.append('## Overview')
    lines.append('')
    lines.append('| | |')
    lines.append('|---|---|')
    lines.append('| Type | %s |' % _md_escape(t.get('kind_label')))
    if t.get('subject'):
        item = t['subject'] + (' — %s' % t['variety'] if t.get('variety') else '')
        lines.append('| Item | %s |' % _md_escape(item))
    loc = t.get('location') or {}
    loc_parts = [v for v in (loc.get('zone_name'), loc.get('facility_name'),
                             loc.get('bay_name')) if v]
    if loc_parts:
        lines.append('| Location | %s |' % _md_escape(' · '.join(loc_parts)))
    prog = t.get('program') or {}
    if prog.get('name'):
        lines.append('| Program | %s |' % _md_escape(
            prog['name'] + (' (v%s)' % prog['version'] if prog.get('version') else '')))
    if t.get('area_m2') is not None:
        lines.append('| Area | %.1f m² |' % t['area_m2'])
    lines.append('| Time zone | %s |' % _md_escape(t.get('tz_name')))
    lines.append('')

    # ── 단계별 요약 (plot만) ─────────────────────────────────────────────
    stages = journal_data.get('stages')
    if stages:
        lines.append('## Stages')
        lines.append('')
        for st in stages:
            lines.append('### %s (%s – %s)' % (
                _md_escape(st.get('name') or st.get('key')),
                st.get('starts_on') or '—', st.get('ends_on') or 'ongoing'))
            lines.append('')
            if st.get('guidance'):
                lines.append(_md_escape(st['guidance']))
                lines.append('')
            targets = st.get('targets') or []
            if targets:
                lines.append('| Target | Value | |')
                lines.append('|---|---|---|')
                for tg in targets:
                    note = 'no sensor' if tg.get('observable') is False else ''
                    lines.append('| %s | %s | %s |' % (
                        _md_escape(tg.get('label')), _md_escape(_md_target_value(tg)),
                        note))
                lines.append('')

    # ── 버킷 루프 ────────────────────────────────────────────────────────
    lines.append('## Log')
    lines.append('')
    for b in (journal_data.get('buckets') or []):
        lines.append('### %s' % b.get('date_label'))
        lines.append('')
        if b.get('empty'):
            lines.append('_No data recorded for this period._')
            lines.append('')
            continue

        env = b.get('env') or []
        if env:
            lines.append('| Sensor | Measurement | Min | Max | Avg | Target | Δ |')
            lines.append('|---|---|---|---|---|---|---|')
            for e in env:
                avg = e.get('avg')
                avg_cell = ('%s %s' % (avg, e.get('unit') or '')).strip() \
                    if avg is not None else ''
                if e.get('coverage_low'):
                    avg_cell += ' (partial coverage)'
                target_cell = ('curve: %s' % e['follows_curve']
                               if e.get('follows_curve')
                               else (str(e['target']) if e.get('target') is not None else ''))
                usage_suffix = ''
                if e.get('usage'):
                    usage_suffix = ' (usage: %s %s)' % (
                        e['usage'].get('amount'), e['usage'].get('unit'))
                lines.append('| %s | %s%s | %s | %s | %s | %s | %s |' % (
                    _md_escape(e.get('sensor')), _md_escape(e.get('measurement')),
                    usage_suffix, _md_escape(e.get('min')), _md_escape(e.get('max')),
                    _md_escape(avg_cell), _md_escape(target_cell),
                    _md_escape(_md_delta_value(e))))
            lines.append('')

        control = b.get('control') or []
        if control:
            lines.append('| Device | Runtime (h) |')
            lines.append('|---|---|')
            for c in control:
                lines.append('| %s | %s |' % (_md_escape(c.get('name')),
                                              _md_escape(c.get('hours'))))
            lines.append('')

        notes = b.get('notes') or []
        for n in notes:
            time_str = (n.get('time') or '')[11:16]
            head = ('**%s**' % time_str) if time_str else ''
            if n.get('title'):
                head += (' ' if head else '') + n['title']
            body = n.get('body') or ''
            lines.append('- %s%s' % (head, (' — ' + body) if head and body else body))
            for fn in (n.get('image_files') or []):
                lines.append('  ![](%s)' % _note_attachment_url(fn))
            for fn in (n.get('other_files') or []):
                lines.append('  [%s](%s)' % (fn, _note_attachment_url(fn)))
        if notes:
            lines.append('')

    lines.append('---')
    lines.append('_Generated: %s_' % journal_data.get('generated_at'))
    return '\n'.join(lines)


# ── 자원 보호 (§13) ─────────────────────────────────────────────────────────
#
# 이 앱은 라즈베리파이 같은 저사양 기기에서 **데몬(장치 제어)과 같은 기기 위에**
# 웹이 함께 돈다는 것이 실제 배포 환경이다. 일지 생성은 채널마다 InfluxDB
# 쿼리가 나가는 작업이라, 큰 zone/site 를 통째로 고르면 짧은 시간에 쿼리가
# 몰려 CPU·IO 를 잡아먹고 다른 요청이나 데몬 동작을 지연시킨다.
#
# 새 작업 큐 시스템을 들여오지 않는다. 이 저장소가 이미 쓰는 패턴만 재사용한다:
#
#   a) 예방이 우선 — 시작하기 전에 세어 보고 넘으면 **시작하지 않는다**.
#   b) 백그라운드 스레드 + 전역 단일 실행 잠금 (routes_geo._start_overlay_tiling).
#   c) 채널 간 페이싱 (QUERY_PACING_SEC — LoRaWAN 다운링크와 같은 원칙).
#   d) 중간에 죽은 작업 회수 — 저사양 기기는 재시작이 드물지 않다.

#: 한 일지가 쏠 수 있는 InfluxDB 쿼리 수 상한. 환경 채널당 3회(min/max/mean) +
#: 제어 채널당 1회(sum)로 세며, **기간과 무관**하다.
MAX_QUERIES_PER_JOURNAL = 240

#: 기간 상한(일). 횟수 상한만으로는 **스캔 부하가 안 잡힌다** — 채널 1개짜리
#: 5년 일지는 상한을 여유롭게 통과하면서 단일 쿼리로는 가장 무겁다. Influx 가
#: 훑는 점 수는 기간에 비례하기 때문이다.
MAX_JOURNAL_DAYS = 1100          # ≈ 3년

#: 반환 행 예산. §4-1 이 시간 버킷으로 받아 접으므로 행이 일별의 24배다.
#: 저사양 기기에서는 파이썬 쪽 접기 비용이 실제 부하라 이것도 함께 센다.
MAX_JOURNAL_ROWS = 500_000

#: 앱 전체에서 일지 생성은 **한 번에 하나**.
#:
#: ⚠ 이것이 "앱 전체" 로 성립하는 근거는 `install/gunicorn_conf.py` 의
#:   **`workers = 1`** 이다(스케줄러 때문에 1로 고정돼 있다). 워커를 늘리면 이
#:   잠금은 프로세스마다 따로 생겨 보장이 조용히 깨진다 — 그때는 DB 를 쓰는
#:   잠금으로 바꿔야 한다.
_BUILD_LOCK = threading.Lock()

#: 'running' 인 채 이만큼 지난 행은 죽은 것으로 보고 회수한다(§13d).
STALE_RUNNING_MINUTES = 30


def estimate_journal_cost(target_type, target_id, start_date, end_date):
    """집계를 **시작하기 전에** 비용을 센다 → dict.

    ```
    {'ok': bool, 'reason': str|None,
     'env_channels', 'control_channels', 'queries', 'days', 'rows'}
    ```

    `ok=False` 면 라우트가 400 으로 거절한다 — **몰래 일부만 잘라 보여주지
    않는다.** 무엇을 뺐는지 모르는 채로 "됐다" 고 말하는 것이 이 저장소가
    반복해서 겪은 실패다.

    세는 기준은 실제로 도는 것과 같아야 한다(`resolve_devices`·`count_channels`
    를 그대로 쓴다) — 게이트가 따로 세면 통과해 놓고 다르게 도는 일이 생긴다.
    """
    days = (end_date - start_date).days + 1
    target_row = resolve_target_row(target_type, target_id)
    sensor_ids, actuators, _unassigned, _area = resolve_devices(
        target_type, target_row)

    env_channels = count_channels(sensor_ids)
    control_channels = len([a for a in actuators if a.get('output_id')])
    queries = env_channels * 3 + control_channels
    bucket_sec = 3600           # 최악(가장 잘게 써는 tz)은 900 이지만 4배는
                                # 예산에 여유가 있어 대표값으로 3600 을 쓴다
    rows = queries * days * (86400 // bucket_sec)

    reason = None
    if days > MAX_JOURNAL_DAYS:
        reason = 'period-too-long'
    elif queries > MAX_QUERIES_PER_JOURNAL:
        reason = 'too-many-channels'
    elif rows > MAX_JOURNAL_ROWS:
        reason = 'too-much-data'

    return {'ok': reason is None, 'reason': reason,
            'env_channels': env_channels, 'control_channels': control_channels,
            'queries': queries, 'days': days, 'rows': rows}


def summarize_for_card(journal_data):
    """완성된 계약 dict → `(title, summary_json)`. 카드 목록이 쓴다.

    ## 왜 완성된 문장을 저장하지 않는가

    계획 초안은 `"{대상명} 일지 ({start}~{end})"` 같은 **완성된 문구**를
    저장하라고 했다. 그러면 그 문구가 **생성 시점의 언어로 굳는다** — 이 앱은
    22개 로케일로 나가고 한 농장을 여러 언어 사용자가 함께 보는 일이 정상이라,
    작년에 한국어로 만든 일지가 일본어 사용자 화면에서도 한국어로 남는다.

    그래서 여기서는 **번역이 필요 없는 것만** 저장한다.

    - `title` : **대상 이름 그대로**(사람이 지은 고유명사라 번역 대상이 아니다).
      "일지 (기간)" 같은 수식은 화면이 붙인다.
    - `summary`: 숫자만 담은 **JSON 문자열**. 화면이 읽어 자기 언어로 문장을
      만든다. 사람이 읽는 문자열을 저장해 두고 화면이 파싱하는 것보다 안전하다
      (구분자·어순이 언어마다 다르다).
    """
    import json as _json

    buckets = journal_data.get('buckets') or []
    target = journal_data.get('target') or {}
    payload = {
        'granularity': journal_data.get('granularity') or 'day',
        'buckets': len(buckets),
        'notes': sum(len(b.get('notes') or []) for b in buckets),
        'empty_buckets': sum(1 for b in buckets if b.get('empty')),
    }
    return (target.get('name') or ''), _json.dumps(payload)


def reclaim_stale_builds(minutes=None):
    """중간에 죽은 'running' 행을 'error' 로 회수한다 → 회수한 개수.

    빌드 중 프로세스가 재시작되면(저사양 기기에서 드물지 않다) 그 행은 영원히
    `'running'` 으로 남고, 화면은 사용자에게 "잠시 후 새로고침" 을 **영원히**
    말하게 된다. 잠금은 프로세스와 함께 사라지므로 다시 만드는 것을 막는 것도
    없다 — 회수해서 "다시 시도" 를 말할 수 있게 한다.

    허브 라우트 진입 시 부른다(§8).
    """
    from datetime import timedelta as _td

    from aot.aot_flask.extensions import db
    from aot.databases.models import GeoJournal
    from aot.utils.timekit import utc_now

    cutoff = (utc_now() - _td(minutes=minutes or STALE_RUNNING_MINUTES))
    cutoff = cutoff.replace(tzinfo=None)      # started_at 은 naive UTC 로 저장된다
    rows = GeoJournal.query.filter(
        GeoJournal.status == 'running',
        GeoJournal.started_at.isnot(None),
        GeoJournal.started_at < cutoff).all()
    for row in rows:
        row.status = 'error'
        row.error_message = 'build-interrupted'
    if rows:
        db.session.commit()
    return len(rows)


def _run_journal_build(app, journal_uuid):
    """백그라운드에서 일지 하나를 채운다. 선례: `routes_geo._start_overlay_tiling`.

    ## 잠금이 바깥이 아니라 **안**에 있는 이유

    `with _BUILD_LOCK:` 을 스레드를 띄우기 **전**에 걸면 요청 스레드가 거기서
    막혀 §13b 의 목적(웹 요청을 막지 않는다)이 무너진다. 스레드 안에서 걸어야
    두 번째 요청도 즉시 돌아가고, 실제 InfluxDB 부하만 순서를 선다.
    """
    from aot.aot_flask.extensions import db
    from aot.databases.models import GeoJournal
    from aot.utils.timekit import utc_now

    def _work():
        with app.app_context():
            try:
                with _BUILD_LOCK:
                    row = GeoJournal.query.filter_by(
                        unique_id=journal_uuid).first()
                    if row is None or row.status not in ('pending', 'running'):
                        return          # 지워졌거나 이미 끝났다
                    row.status = 'running'
                    row.started_at = utc_now().replace(tzinfo=None)
                    db.session.commit()

                    data = build_journal_for_target(
                        row.target_type, row.target_id,
                        row.period_start, row.period_end)

                    # 오래 걸리는 작업이라 **행을 다시 읽는다** — 그 사이
                    # 지워졌을 수 있다(선례의 "the row may have changed").
                    row = GeoJournal.query.filter_by(
                        unique_id=journal_uuid).first()
                    if row is None:
                        return
                    title, summary = summarize_for_card(data)
                    row.data = journal_to_jsonable(data)
                    row.tz_name = (data.get('target') or {}).get('tz_name')
                    row.title = title[:160]
                    row.summary = summary
                    row.error_message = None
                    row.status = 'done'
                    db.session.commit()
                    app.logger.info('[journal] built %s (%s, %d buckets)',
                                    journal_uuid, data.get('granularity'),
                                    len(data.get('buckets') or []))
            except Exception as exc:
                app.logger.exception('[journal] build failed for %s',
                                     journal_uuid)
                try:
                    row = GeoJournal.query.filter_by(
                        unique_id=journal_uuid).first()
                    if row is not None:
                        row.status = 'error'
                        row.error_message = str(exc)[:200]
                        db.session.commit()
                except Exception:
                    pass
            finally:
                db.session.remove()

    threading.Thread(target=_work, daemon=True,
                     name='journal_%s' % str(journal_uuid)[:8]).start()


def start_journal_build(journal_uuid):
    """요청 스레드에서 부른다 — 앱 객체를 잡아 백그라운드로 넘긴다.

    `current_app` 은 요청 컨텍스트에 매여 있어 스레드로 그대로 넘기면 안 된다
    (선례가 `_get_current_object()` 를 쓰는 이유).
    """
    from flask import current_app

    _run_journal_build(current_app._get_current_object(), journal_uuid)
