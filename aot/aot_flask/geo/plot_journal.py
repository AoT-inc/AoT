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

#: **원형(circular) 값** — 0 과 360 이 같은 지점이라 선형 통계가 성립하지 않는다.
#: 실측(2026-09-02, 미러-기상대 2026-08-17~23, 1,211표본): 실제로는 240~269도가
#: 50% 로 압도적인데 선형 통계는 `min=2.0 / max=359.0` 을 내 "나침반을 한 바퀴
#: 돌았다" 처럼 보였고, 선형평균 237.73도와 올바른 원형평균 241.48도가 이미
#: 어긋나 있었다. **주풍향이 0/360 경계에 걸쳐 있었다면 평균이 정반대로 튄다.**
#: min/max 는 원형 값에 뜻이 없으므로 아예 내지 않는다(`None`).
CIRCULAR_UNITS = frozenset({'bearing'})

#: **장치 자신의 상태**를 재는 채널 — 기르는 환경이 아니다. 기본으로 뺀다.
#:
#: 실측(육묘장 일지)에서 표의 절반이 전위·신호강도·신호대잡음비였다. 배터리가
#: 몇 볼트였는지는 장비를 관리할 때 필요한 값이지, "무엇을 어떻게 길렀나" 를
#: 넘겨받는 사람이 볼 것이 아니다. 쿼리 비용도 그만큼 든다(온습도 센서 6채널
#: 중 3채널이 이것들이라 **조회의 절반**이다).
#:
#: ⚠ **여기 없는 새 measurement 는 기본 포함이다.** 반대로 하면 새 환경 값이
#:   조용히 사라지는데, 없는 것과 안 실은 것은 문서에서 구별되지 않는다 —
#:   보이는 쪽이 안전한 실패다.
#: ⚠ 이것은 **기본값일 뿐 금지가 아니다.** 사용자가 고르면 그대로 싣는다
#:   (장비 점검용 일지를 만들 수도 있다).
DIAGNOSTIC_MEASUREMENTS = frozenset({
    'electrical_potential',   # 배터리 전압
    'rssi', 'snr',            # 무선 링크 품질
    'version',                # 펌웨어 버전
    'pid_p_value', 'pid_i_value', 'pid_d_value',   # 제어기 내부값
})

#: 원형 채널이 **시간당 몇 점**을 낼 것으로 보고 예산을 잡는가. 그 채널만
#: 집계가 아니라 원자료를 읽으므로(`_circular_channel_stats`) 행 예산이 다르다.
#: 실측(미러-기상대)에서 시간당 약 53점이라 보수적으로 60 으로 둔다 — 예산은
#: **큰 쪽으로 틀려야** 안전하다(작게 잡으면 통과시켜 놓고 저사양 기기가 멎는다).
CIRCULAR_POINTS_PER_HOUR = 60

#: 빛을 재는 measurement. 이것들만 DLI(일적산광량)를 파생한다.
LIGHT_MEASUREMENTS = frozenset({'radiation', 'light'})

#: 단위 → `(PPFD 환산계수, 가정이 들어갔는가)`.
#:
#: DLI(mol/m²/일)는 PPFD(µmol/m²/s)를 하루 동안 적분한 값이다. 센서가 무엇을
#: 내느냐에 따라 환산이 **완전히 다르다**:
#:
#: - `umol_m2_s` — 이미 PPFD 다. **곱하면 안 된다.** 여기에 W/m² 계수를 곱하면
#:   값이 두 배가 되는데, 숫자가 그럴듯해서 틀린 줄 모른다.
#: - `W_m2` — 전천일사(단파 전체). PAR 은 그 45% 가량이고 PAR 1 W/m² ≈
#:   4.57 µmol/m²/s 이므로 ≈ ×2.06. **가정이 둘 들어간 값이다**(PAR 비율·광원이
#:   태양광이라는 것) — 그래서 화면이 "추정" 이라고 말해야 한다.
#: - `lux`/`klux` — 사람 눈 기준 밝기라 스펙트럼에 크게 좌우된다. 태양광 기준
#:   대략 ×0.0185 인데 LED 보광 아래서는 크게 틀린다. 쓰되 추정으로 표시한다.
#:
#: ⚠ 모르는 단위는 **환산하지 않는다.** 그럴듯한 계수를 지어내면 DLI 가 나오고,
#:   나오는 순간 사람은 그것을 믿는다.
LIGHT_UNITS_TO_PPFD = {
    'umol_m2_s': (1.0, False),
    'W_m2': (2.06, True),
    'lux': (0.0185, True),
    'klux': (18.5, True),
}


def ppfd_factor(unit):
    """빛 단위 → `(계수, 추정인가)`. 모르면 `(None, None)`."""
    found = LIGHT_UNITS_TO_PPFD.get(str(unit or ''))
    return found if found else (None, None)


#: 표에 세우는 **순서**. 이름순은 사람이 읽는 순서가 아니다 — 실측에서
#: `습도 · 길이 · 일사량 · 속도 · 온도 · VPD` 로 나와, 무슨 기준인지 알 수
#: 없고 광합성을 좌우하는 값(일사)이 한가운데 파묻혔다.
#:
#: 순서의 근거는 **무엇이 작물을 결정하는가**다:
#:   1) 광합성 — 빛이 먼저고, 그다음이 그 빛을 쓰게 하거나 막는 것들
#:   2) 물 — 받은 물과 가진 물
#:   3) 바람 — **풍향과 풍속은 반드시 붙인다.** 둘은 한 사건의 두 축이라
#:      떨어져 있으면 사람이 눈으로 다시 붙여야 한다.
#:   4) 그 밖
#:
#: ⚠ 여기 없는 measurement 는 **3그룹과 4그룹 사이**에 이름순으로 놓인다.
#:   맨 뒤로 보내면 새 측정값이 늘 구석에 처박히고, 맨 앞이면 모르는 값이
#:   중요한 값을 밀어낸다.
MEASUREMENT_ORDER = (
    # 1) 광합성 — DLI 는 일사에서 파생한 값이라 바로 뒤에 붙인다.
    'radiation', 'light', 'dli', 'uvi', 'co2',
    'temperature', 'humidity', 'vapor_pressure_deficit', 'dewpoint',
    # 2) 물
    'precipitation', 'rain', 'snowfall', 'length',
    'volumetric_water_content', 'moisture', 'volume',
    # 3) 바람 — 붙여 둔다
    'direction', 'speed',
)

#: 위 목록 뒤에 오는 것들(기압·시정 등 참고값). 모르는 값보다 뒤다.
MEASUREMENT_ORDER_TAIL = ('pressure', 'visibility', 'altitude', 'unitless',
                          'version')


def measurement_rank(key):
    """측정 키 → 정렬 순위. 모르는 값은 알려진 것들 **사이**에 놓는다."""
    name = str(key or '')
    if name in MEASUREMENT_ORDER:
        return (0, MEASUREMENT_ORDER.index(name))
    if name in MEASUREMENT_ORDER_TAIL:
        return (2, MEASUREMENT_ORDER_TAIL.index(name))
    return (1, 0)          # 모르는 값 — 이름순으로 이 자리에 모인다


#: 화면·문서에 싣는 소수 자릿수. 반올림하지 않으면 파이썬 float repr 이 그대로
#: 찍힌다("71.26782390873016 percent"). `delta`·`usage`·`hours` 가 이미 각자
#: 반올림하고 있어, 안 맞추면 같은 표 안에서 열마다 정밀도가 달라진다.
VALUE_DECIMALS = 2


# ── 시간 버킷 → 현지 일자 ───────────────────────────────────────────────────
#
# 접는 규칙 자체는 `aot/utils/timekit` 에 있다 — `aot/utils/runtime.py`(데몬도
# 쓰는 저수준 모듈)가 같은 규칙을 필요로 하는데, 그것을 여기 두면 저수준이
# Flask 계층을 임포트하게 되어 계층이 뒤집히고 실제로 순환 임포트가 된다.
# 여기서는 이름만 다시 내보낸다(이 파일을 읽는 사람이 규칙을 찾아갈 수 있게).

from aot.utils.timekit import (                                    # noqa: E402
    ensure_utc,
    to_tz,
    bucket_local_key as bucket_key,
    bucket_seconds_for,
    buckets_expected as expected_buckets,
    local_day_bounds_utc as period_bounds_utc,
)


def photosynthesis_targets(plot):
    """구획 → 광합성 목표 중 **일지가 견줄 수 있는 것** 목록.

    지금은 `dli_target` 하나다. 프로그램의 `photosynthesis` 는 단계가 아니라
    **프로그램 수준**이라 단계 목표 목록에 없다 — 그래서 여기서 따로 만들어
    붙인다.

    ⚠ `shape='daily'` 를 붙이지 않는다. 그 표식은 "하루치 적산 목표를 순간값의
      일평균과 빼지 말라" 는 뜻인데(`delta_for`), DLI 는 **이미 하루치 적산**
      이라 차원이 맞는다. 붙이면 멀쩡한 비교가 막힌다.

    ⚠ `A_max`·`K_L`·`T_opt` 같은 나머지는 **목표가 아니라 모델 계수**다 —
      제어기가 광합성률을 추정할 때 쓰는 값이라 "도달했는가" 를 물을 수
      없다. 목표로 착각해 내보내면 화면이 못 지킨 목표를 잔뜩 보여준다.
    """
    from aot.databases.models import GeoProgram

    if plot is None or not getattr(plot, 'program_uuid', None):
        return []
    program = GeoProgram.query.filter_by(unique_id=plot.program_uuid).first()
    photo = (getattr(program, 'photosynthesis', None) or {}) if program else {}
    if not isinstance(photo, dict):
        return []

    out = []
    dli = photo.get('dli_target')
    if dli not in (None, ''):
        try:
            out.append({'measurement': 'dli', 'value': float(dli),
                        'label': 'DLI', 'unit': 'mol_m2_d',
                        'observable': True, 'source': 'program'})
        except (TypeError, ValueError):
            pass
    return out


def gdd_for_journal(plot, end_date, start_date=None):
    """구획 → 일지에 실을 적산온도 → dict.

    ```
    {'usable', 'reason', 't_base', 'total', 'period', 'by_day': {date: 값},
     'coverage_pct', 'days_counted', 'days_expected'}
    ```

    ⚠ **`by_day` 는 조립용 작업값이지 문서 내용이 아니다.** 키가 `date` 객체라
      JSON 으로 저장할 수 없다(실측: `keys must be str, int, float, bool or
      None, not datetime.date` 로 저장이 통째로 실패했고, 빌드는 끝났는데 행이
      영영 `running` 으로 남았다). 날짜별 값은 각 버킷에 이미 실리므로
      **저장 직전에 뺀다**(`build_journal_for_target` 참조).

    `plot_context.gdd_accumulated()` 가 이미 계산한다 — 여기서는 그것을 일지의
    두 축(누적 · 이 기간)으로 나누기만 한다. **두 번째 계산자를 만들지 않는다.**

    - `total`  — 작기 시작부터 기간 끝까지의 **누적**. 단계 전환을 좌우하는
                 값이라 농사에서 "지금 몇 도" 라고 할 때 이쪽이다.
    - `period` — 이 문서가 담은 기간의 합. 문서 자체의 산출물이다.

    ⚠ **못 쓸 때 0 을 내지 않는다.** `usable=False` 면 `reason` 을 그대로 낸다
      (`no-program`·`no-t-base`·커버리지 부족) — 빈칸이나 0 은 "그날 하나도
      안 쌓였다" 로 읽히는데, 못 쓰는 것과 0 은 전혀 다르다.
    """
    from aot.aot_flask.geo import plot_context
    from aot.databases.models import GeoProgram

    out = {'usable': False, 'reason': None, 't_base': None,
           'total': None, 'period': None, 'by_day': {},
           'coverage_pct': None, 'days_counted': 0, 'days_expected': 0}
    if plot is None or not getattr(plot, 'program_uuid', None):
        return dict(out, reason='no-program')

    program = GeoProgram.query.filter_by(
        unique_id=plot.program_uuid).first()
    try:
        found = plot_context.gdd_accumulated(plot, program, on=end_date,
                                             with_series=True)
    except Exception:
        logger.exception('journal: 적산온도 산출 실패')
        return dict(out, reason='error')

    out.update({k: found.get(k) for k in
                ('usable', 'reason', 't_base', 'coverage_pct',
                 'days_counted', 'days_expected')})
    out['total'] = _round(found.get('value'), 1)
    series = found.get('series') or []
    out['by_day'] = {day: value for day, value in series}
    if start_date is not None:
        window = [v for d, v in series if start_date <= d <= end_date]
        out['period'] = _round(sum(window), 1) if window else None
    return out


def sun_lookup(target_id):
    """대상 → `(현지날짜) → (일출, 일몰, 일장시간)` 조회 함수. 못 구하면 `None`.

    `aot.utils.solar.sun_times` 는 **target_id 로 좌표를 해소**하고 결과를
    캐시하므로, 날짜마다 불러도 같은 날은 한 번만 계산한다.

    ## 왜 필요한가

    주간/야간 목표(`when='day'|'night'`)의 편차를 그동안 내지 못했다 — 하루
    전체 평균과 견주면 **야간 12도 목표를 한낮 35.6도와 비교해 23.6도 차이**
    라는 허위 경보가 난다(실측). 일장을 알면 그 시간대만 골라 평균을 낼 수
    있어 그 편차가 성립한다.

    극지방처럼 일출·일몰이 없는 날은 `None` 을 돌려준다 — 그런 날 밤낮을
    가르는 것은 뜻이 없고, 억지로 가르면 하루가 통째로 한쪽에 몰린다.
    """
    from aot.utils import solar

    cache = {}

    def _lookup(local_date):
        if local_date in cache:
            return cache[local_date]
        result = None
        try:
            times = solar.sun_times(target_id=target_id, date=local_date)
            if times is not None and times.sunrise and times.sunset:
                hours = (times.sunset - times.sunrise).total_seconds() / 3600.0
                result = (times.sunrise, times.sunset, round(hours, 2))
        except Exception:
            logger.debug('journal: 태양시를 구할 수 없습니다 (%s)', local_date)
        cache[local_date] = result
        return result

    return _lookup


def _round(value, decimals=None):
    """표시용 반올림 — `None` 은 그대로 `None`.

    "값이 없다"(`None`)와 "값이 0 이다"는 문서에서 전혀 다른 뜻이므로 `or 0`
    같은 폴백을 쓰지 않는다.
    """
    if value is None:
        return None
    try:
        return round(float(value),
                     VALUE_DECIMALS if decimals is None else decimals)
    except (TypeError, ValueError):
        return None


def choose_granularity(start_date, end_date, rows=None, requested=None):
    """**저장할** 단위 → `'day'` | `'week'` | `'month'`.

    `requested` 는 사람이 생성 화면에서 고른 것이다. **일 단위 요청은 예산에
    막힐 수 있지만(그때 주간으로 내려간다) 굵게 고른 것은 언제나 그대로 따른다**
    — 굵은 쪽이 항상 더 싸므로 거절할 이유가 없다.

    ## 되도록 일 단위로 저장한다

    예전에는 기간이 `DAILY_DETAIL_MAX_DAYS`(60일)를 넘으면 무조건 주간으로
    접어 **그 단위로만** 저장했다. 그러면 열람하는 사람이 단위를 고를 수 없다 —
    **접는 것은 되돌릴 수 있어도 편 것은 되돌릴 수 없기 때문**이다(일→주는
    파이썬 계산이지만, 주로 저장된 것을 일로 되돌리려면 InfluxDB 를 다시 읽어야
    하고 그것은 스냅샷 계약을 깬다). 그래서 저장은 항상 **가장 잘게** 하고,
    주·월·전체는 열람할 때 `fold_buckets` 가 만든다.

    주간으로 내려가는 경우는 하나뿐이다 — 일 단위로는 행 예산(`MAX_JOURNAL_ROWS`)
    을 넘길 때. 그때는 접어서라도 문서를 만드는 편이 거절하는 것보다 낫고,
    접었다는 사실은 `caveats` 가 말한다.
    """
    if requested in ('week', 'month'):
        # 사람이 굵게 고른 것은 그대로 따른다. 더 잘게 저장해 봐야 그 사람이
        # 원하지 않은 문서만 커진다 — 접는 것은 열람에서 언제든 되고, 이 선택은
        # "그 상세가 필요 없다" 는 뜻이다.
        return requested
    if rows is not None and rows > MAX_JOURNAL_ROWS:
        return 'week'
    return 'day'


#: 열람 시점에 고를 수 있는 단위. 저장 단위보다 **잘게** 는 볼 수 없다.
VIEW_GRANULARITIES = ('day', 'week', 'month', 'all')


def fold_buckets(buckets, to='week', granularity='day'):
    """저장된 버킷 목록 → 더 굵은 단위로 접은 버킷 목록. **순수 계산**이다.

    InfluxDB 를 다시 읽지 않고 DB 에 쓰지도 않는다 — 열람할 때마다 저장된
    스냅샷에서 새로 만든다. 그래서 스냅샷 불변 계약(§1)을 깨지 않는다.

    `to` 는 `'day'|'week'|'month'|'all'`. **저장 단위보다 잘게는 못 간다** —
    주 단위로 저장된 문서에 일 단위를 요구하면 접지 않고 그대로 돌려준다
    (없는 정보를 지어내지 않는다. 화면은 그 선택지를 아예 감춘다).
    """
    order = {'day': 0, 'week': 1, 'month': 2, 'all': 3}
    if order.get(to, 0) <= order.get(granularity, 0):
        return buckets
    if not buckets:
        return buckets

    def _key_of(bucket):
        """버킷 → 시작일(date). 옛 문서는 `key` 가 없어 라벨에서 되짚는다."""
        raw = bucket.get('key')
        if not raw:
            # `date_label` 은 'YYYY-MM-DD' 또는 'YYYY-MM-DD ~ YYYY-MM-DD'.
            raw = str(bucket.get('date_label') or '')[:10]
        try:
            return datetime.strptime(str(raw)[:10], '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None

    # ── 주 경계는 **기록 시작일**에 앵커한다 ─────────────────────────────
    # ISO 주(월요일 시작)로 자르면 "1주차" 가 며칠짜리인지 심은 요일에
    # 좌우된다. 쿠마모토 딸기가 실제로 그랬다 — 시작일 2026-08-23 이
    # **일요일**이라 1주차가 하루뿐이었고, 라벨이 `첫날+6일` 로 만들어져
    # "08-23 ~ 08-29" 라 적혔다. 그 안에 2주차(08-24~08-30)가 통째로 들어가
    # 겹쳐 보였고, 읽는 사람은 **데이터가 빠진 것**으로 읽었다.
    #
    # 일지에서 "N주차" 는 달력이 아니라 **재배 N주차**다. 시작일에 앵커하면
    # 모든 주가 7일이고 겹칠 수 없다. 달(月)은 그대로 달력 기준이다 —
    # 사람이 기록을 찾을 때 쓰는 단위가 달력의 달이라 옮기면 오히려 낯설다.
    anchor = None
    for bucket in buckets:
        d = _key_of(bucket)
        if d is not None:
            anchor = d if anchor is None else min(anchor, d)

    def _fold_key(day):
        if to == 'all':
            return 'all'
        if to == 'month':
            return day.replace(day=1)
        if anchor is None:
            return day - timedelta(days=day.weekday())
        return anchor + timedelta(days=((day - anchor).days // 7) * 7)

    merged = {}
    order_keys = []
    for bucket in buckets:
        day = _key_of(bucket)
        if day is None:
            # 되짚을 수 없는 버킷은 접지 않고 그대로 흘려보낸다 — 버리면
            # 그 구간이 문서에서 통째로 사라진다.
            order_keys.append(('~raw', id(bucket)))
            merged[('~raw', id(bucket))] = {'raw': bucket}
            continue
        fkey = _fold_key(day)
        if fkey not in merged:
            merged[fkey] = {'days': [], 'first': day, 'last': day,
                            'start': fkey if hasattr(fkey, 'isoformat') else day}
            order_keys.append(fkey)
        box = merged[fkey]
        box['days'].append(bucket)
        box['first'] = min(box['first'], day)
        box['last'] = max(box['last'], day)

    out = []
    for fkey in order_keys:
        box = merged[fkey]
        if 'raw' in box:
            out.append(box['raw'])
            continue
        out.append(_merge_bucket_group(box, to))
    return out


def _merge_bucket_group(box, to):
    """같은 구간에 드는 버킷들 → 하나로 접은 버킷.

    접는 규칙은 `daily_channel_stats` 와 같다 — min 은 최소의 최소, max 는
    최대의 최대(**정확**), avg 는 표본 가중 평균(방향은 원형 평균), 가동시간과
    사용량은 **합**(누적량이라 더하는 것이 맞다), 노트는 전부 이어 붙인다.
    """
    import math

    days = box['days']
    first, last = box['first'], box['last']
    if to == 'all':
        label = '%s ~ %s' % (first.isoformat(), last.isoformat())
    elif to == 'month':
        label = first.strftime('%Y-%m')
    else:
        # ⚠ **`첫날+6일` 로 쓰지 말 것.** 그 구간에 실제로 들어 있는 날이
        #   하나여도 7일짜리라고 적게 되고, 그 라벨이 다음 구간을 삼켜
        #   겹쳐 보인다(쿠마모토 딸기에서 실제로 겪었다). 구간의 시작은
        #   `box['start']`(접기 키 = 그 주의 첫날)이고 끝은 시작+6일이되,
        #   기록이 거기까지 안 미치면 **마지막 기록일**에서 끊는다.
        start = box.get('start') or first
        label = '%s ~ %s' % (start.isoformat(),
                             min(start + timedelta(days=6), last).isoformat())

    # ── 환경: (센서, 측정값) 별로 모은다 ──────────────────────────────────
    env_acc = {}
    env_order = []
    for bucket in days:
        for row in (bucket.get('env') or []):
            key = (row.get('device_id'), row.get('channel'),
                   row.get('measurement'), row.get('scope'))
            if key not in env_acc:
                env_acc[key] = []
                env_order.append(key)
            env_acc[key].append(row)

    env_rows = []
    for key in env_order:
        members = env_acc[key]
        base = dict(members[0])
        mins = [r['min'] for r in members if r.get('min') is not None]
        maxs = [r['max'] for r in members if r.get('max') is not None]
        pairs = [(r['avg'], r.get('samples') or 0)
                 for r in members if r.get('avg') is not None]
        circular = any(r.get('circular') for r in members)
        if not pairs:
            avg = None
        elif circular:
            sx = sum(math.sin(math.radians(v)) * max(n, 1) for v, n in pairs)
            cx = sum(math.cos(math.radians(v)) * max(n, 1) for v, n in pairs)
            avg = (math.degrees(math.atan2(sx, cx)) % 360.0
                   if math.hypot(sx, cx) else None)
        else:
            weight = sum(max(n, 1) for _v, n in pairs)
            avg = sum(v * max(n, 1) for v, n in pairs) / weight

        samples = sum(r.get('samples') or 0 for r in members)
        expected = sum(r.get('expected') or 0 for r in members) or None
        coverage = round(samples / expected, 3) if expected else None
        usages = [r['usage']['amount'] for r in members
                  if (r.get('usage') or {}).get('amount') is not None]
        base.update({
            'min': _round(min(mins)) if mins else None,
            'max': _round(max(maxs)) if maxs else None,
            'avg': _round(avg),
            'circular': circular,
            'samples': samples,
            'expected': expected,
            'coverage': coverage,
            'coverage_low': (coverage is not None and coverage < MIN_COVERAGE),
            # 사용량은 누적량이라 **더한다**(평균이 아니다).
            'usage': ({'amount': round(sum(usages), 3),
                       'unit': (members[0].get('usage') or {}).get('unit')}
                      if usages else None),
        })
        # 목표·편차는 접힌 구간 안에서 단계가 바뀌었을 수 있다. 마지막 버킷의
        # 것을 쓰되(그 구간 끝의 목표), 값이 여럿이면 편차 범위를 함께 낸다.
        # 피복 근거는 **다시 계산한다.** `dict(members[0])` 이 첫날의 실외값을
        # 그대로 들고 오는데 평균은 구간 전체의 것이라, 접는 순간 둘이 어긋난다
        # (실측: 값 28.89 옆에 "실외 0.0 × 0.78" 이 붙었다). 각 날의 값이
        # `실외 × tau` 이므로 평균을 tau 로 나누면 그것이 곧 실외 평균이다.
        cov = base.get('cover')
        if cov and cov.get('tau'):
            base['cover'] = dict(cov, outdoor=(_round(avg / cov['tau'])
                                               if avg is not None else None))

        deltas = [r['delta'] for r in members if r.get('delta') is not None]
        base['delta'] = _round(sum(deltas) / len(deltas)) if deltas else None
        base['delta_min'] = _round(min(deltas)) if deltas else None
        base['delta_max'] = _round(max(deltas)) if deltas else None
        env_rows.append(base)

    # ── 제어: 장치별 가동시간 합 ─────────────────────────────────────────
    ctrl_acc = {}
    ctrl_order = []
    for bucket in days:
        for row in (bucket.get('control') or []):
            key = row.get('output_id') or row.get('name')
            if key not in ctrl_acc:
                # ⚠ 누산기는 **0 에서 시작해야 한다.** `dict(row)` 는 첫날의
                #   가동시간·물량을 그대로 안고 오므로, 그 위에 더하면 첫날이
                #   두 번 세어진다(실측: 10 + 5 가 25 로 나왔다). `water` 는
                #   중첩 dict 라 얕은 복사로는 원본까지 함께 불어난다.
                ctrl_acc[key] = dict(row)
                ctrl_acc[key]['hours'] = 0.0
                ctrl_acc[key]['seconds'] = 0
                ctrl_acc[key].pop('water', None)
                ctrl_order.append(key)
            ctrl_acc[key]['hours'] += float(row.get('hours') or 0.0)
            # 초는 별도로 쌓는다 — 표시 단위(시/분/초)를 `runtime_text` 가
            # 여기서 고르므로, 첫날 값이 남아 있으면 접은 구간의 단위가 틀린다.
            try:
                ctrl_acc[key]['seconds'] += int(row.get('seconds') or 0)
            except (TypeError, ValueError):
                pass
            # 물량은 **합**이다(가동시간과 같이 쌓이는 값).
            water = row.get('water')
            if water and water.get('litres') is not None:
                box = ctrl_acc[key].setdefault(
                    'water', {'litres': 0.0, 'share': water.get('share', 1.0),
                              'estimated': True,
                              'source': water.get('source')})
                box['litres'] += float(water['litres'])
    control_rows = []
    for key in ctrl_order:
        row = ctrl_acc[key]
        row['hours'] = round(row['hours'], 2)
        if row.get('water'):
            row['water']['litres'] = round(row['water']['litres'], 1)
        control_rows.append(row)

    notes = []
    for bucket in days:
        notes.extend(bucket.get('notes') or [])

    # 일장은 **평균**으로 접는다(합계는 뜻이 없다) — 그 구간이 평균 몇 시간
    # 낮이었는가가 사람이 쓰는 값이다.
    # ⚠ 적산온도는 **합**이다(일장처럼 평균 내면 뜻이 달라진다) — 이름 그대로
    #   쌓이는 값이라, 주간 버킷의 GDD 는 그 주에 쌓인 총량이어야 한다.
    gdd_days = [b['gdd'] for b in days if b.get('gdd') is not None]
    daylight = [b['daylight_h'] for b in days if b.get('daylight_h') is not None]
    return {
        'key': first.isoformat(),
        'date_label': label,
        'sunrise': days[0].get('sunrise'),
        'sunset': days[-1].get('sunset'),
        'daylight_h': (round(sum(daylight) / len(daylight), 2)
                       if daylight else None),
        'gdd': round(sum(gdd_days), 1) if gdd_days else None,
        'env': env_rows,
        'control': control_rows,
        'notes': notes,
        'empty': not (env_rows or control_rows or notes),
    }


def bucket_labels(start_date, end_date, granularity):
    """구간 전체의 버킷 키 목록 → [date]. **값이 없는 버킷도 빠뜨리지 않는다.**

    조회 결과에 있는 날만 모으면 "그날 값이 없었다" 가 문서에서 통째로 사라져
    사람은 그 날이 원래 없었던 것으로 읽는다. 빈 버킷을 명시적으로 내보내는
    것이 이 함수의 존재 이유다.
    """
    out = []
    if granularity == 'week':
        # ⚠ 저장 단위의 주는 **ISO 주**다(열람의 접기와 다르다). 저장 키는
        #   `bucket_local_key` 가 정하고 그것이 ISO 주를 쓰므로, 여기서
        #   시작일에 앵커하면 라벨과 키가 어긋나 버킷이 통째로 빈다.
        cur = start_date - timedelta(days=start_date.weekday())
        while cur <= end_date:
            out.append(cur)
            cur += timedelta(days=7)
        return out
    if granularity == 'month':
        cur = start_date.replace(day=1)
        while cur <= end_date:
            out.append(cur)
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        return out
    cur = start_date
    while cur <= end_date:
        out.append(cur)
        cur += timedelta(days=1)
    return out


# ── 환경(Input) 채널 집계 ───────────────────────────────────────────────────

def _channel_info(dm_row):
    """DeviceMeasurements 행 → `(channel, unit, 표시 이름, 조회 필터)`.

    못 쓰면 `(None, None, None, None)` — 판정 기준은 **unit 이 있는가** 하나다.

    ## 표시 이름과 조회 필터를 가르는 이유 (실측으로 고친 결함)

    `return_measurement_info` 는 **환산(conversion)이 걸린 채널에서 measurement
    를 비운다**(unit 만 바꿔 준다). 예전에는 그것을 "조회가 성립하지 않는다" 로
    읽고 채널을 통째로 건너뛰었는데 **그 전제가 틀렸다.**

    실측(2026-09-03, 미러-온습도01 ch0, F→C 환산): `measure` 필터를 빼고 device
    +channel+unit 으로만 물으면 하루치 **1,444 포인트**가 그대로 나온다
    (`measure='temperature'` 로 물으면 0건 — 환산 채널은 그 태그로 저장되지
    않기 때문이다). 시스템의 정본 읽기 경로 `get_last_measurement` 도 정확히
    그렇게 한다: `return_measurement_info` 가 준 `None` 을 그대로
    `measure=` 로 넘기고, `query_string` 은 `None` 이면 필터를 안 건다.

    건너뛴 대가가 컸다. 육묘장 일지에서 **온도 8채널이 통째로 빠진 채**
    "10개 채널을 읽지 못했다" 로만 표시됐다 — 육묘장에서 가장 중요한 값이
    사라졌는데 원인은 조회 실패가 아니라 **묻지도 않은 것**이었다.

    환산은 **단위를 바꿀 뿐 무엇을 재는지는 바꾸지 않으므로**(F→C 여도 온도다)
    표시 이름은 원래 `dm_row.measurement` 를 그대로 쓴다.
    """
    from aot.databases.models import Conversion
    from aot.utils.system_pi import return_measurement_info

    conv = None
    if getattr(dm_row, 'conversion_id', None):
        conv = Conversion.query.filter(
            Conversion.unique_id == dm_row.conversion_id).first()
    channel, unit, measurement = return_measurement_info(dm_row, conv)
    if not unit:
        return None, None, None, None
    # `measurement` 가 비었다 = 환산 채널. 조회에는 필터를 걸지 않고(그 태그로
    # 저장돼 있지 않다), 표시에는 원래 이름을 쓴다.
    display = measurement or getattr(dm_row, 'measurement', None)
    if not display:
        return None, None, None, None
    return channel, unit, display, measurement


def daily_channel_stats(dm_row, start_str, end_str, tz,
                        granularity='day', bucket_sec=3600, sun_fn=None):
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

    ⚠ **방향(`unit='bearing'`)은 이 경로를 타지 않는다** — 원형(circular) 값이라
      선형 통계가 틀린 답을 낸다(`_circular_channel_stats` 참조).
    """
    from aot.utils.influx import query_string

    channel, unit, measurement, measure_filter = _channel_info(dm_row)
    if unit is None:
        return None

    if unit in CIRCULAR_UNITS:
        return _circular_channel_stats(dm_row, channel, unit, measurement,
                                       start_str, end_str, tz, granularity,
                                       measure_filter=measure_filter)

    acc = {}       # key -> {'min': [], 'max': [], 'mean': [], 'day': [], 'night': []}

    # 빛 채널이면 PPFD 환산계수를 미리 구해 둔다(모르는 단위면 `None` 이라
    # 적분을 아예 하지 않는다 — 계수를 지어내지 않는다).
    light_factor, light_assumed = (None, None)
    if measurement in LIGHT_MEASUREMENTS:
        light_factor, light_assumed = ppfd_factor(unit)

    def _phase(rec_time):
        """이 시간 조각이 낮인가 밤인가 → 'day'|'night'|None.

        ⚠ `aggregateWindow` 라벨은 구간의 **오른쪽 경계**라 창 길이를 빼서
          시작 시각으로 되돌린 뒤 판정한다 — 빼지 않으면 일몰 직전 조각이
          밤으로 넘어간다.
        """
        if sun_fn is None or rec_time is None:
            return None
        try:
            start = ensure_utc(rec_time) - timedelta(seconds=int(bucket_sec))
            local = to_tz(start, tz)
        except Exception:
            return None
        found = sun_fn(local.date())
        if not found:
            return None            # 백야·극야 — 가르지 않는다
        sunrise, sunset, _hours = found
        return 'day' if sunrise <= local < sunset else 'night'

    for fn in ('min', 'max', 'mean'):
        try:
            tables = query_string(
                unit, dm_row.device_id, channel=channel,
                # ⚠ 표시 이름이 아니라 **조회 필터**를 넘긴다 — 환산 채널은
                #   `None`(필터 없음)이어야 값이 나온다(`_channel_info`).
                measure=measure_filter,
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
                box = acc.setdefault(key, {'min': [], 'max': [], 'mean': [],
                                           'day': [], 'night': []})
                box[fn].append(val)
                # 평균만 밤낮으로 가른다 — min/max 는 그날의 극값이라
                # 시간대를 나누면 '그날 최고' 라는 뜻이 사라진다.
                if fn == 'mean':
                    phase = _phase(rec.get_time())
                    if phase:
                        box[phase].append(val)
                    # DLI 적분 — 시간별 평균 PPFD × 3600초 / 1e6.
                    # **하루 평균 × 24 로 계산하지 않는다**: 기록이 없는 시간이
                    # 있으면 그 시간까지 빛이 있었던 것으로 세게 된다.
                    if light_factor is not None:
                        box['mol'] = box.get('mol', 0.0) + (
                            val * light_factor * 3600.0 / 1e6)

    by_bucket = {}
    for key, box in acc.items():
        by_bucket[key] = {
            'min': min(box['min']) if box['min'] else None,
            'max': max(box['max']) if box['max'] else None,
            'avg': (sum(box['mean']) / len(box['mean'])) if box['mean'] else None,
            # 주간/야간 평균 — 주야 목표의 편차가 이것으로 성립한다.
            'avg_day': (sum(box['day']) / len(box['day'])) if box['day'] else None,
            'avg_night': ((sum(box['night']) / len(box['night']))
                          if box['night'] else None),
            'dli': box.get('mol'),
            # 값이 있었던 시간 조각 수. 분모(`expected_buckets`)와 짝을 이뤄
            # "이 평균이 하루의 몇 할을 근거로 하는가" 를 말한다 — 실측에서
            # 7시간 결측인 채널이 멀쩡한 평균처럼 보였다(모듈 머리말).
            'samples': len(box['mean']),
        }
    return {'device_id': dm_row.device_id, 'channel': channel,
            'unit': unit, 'measurement': measurement, 'by_bucket': by_bucket,
            # DLI 가 가정 위에 선 값인지 — 화면이 "추정" 이라고 말해야 한다.
            'dli_assumed': light_assumed}


def _wanted_measurement(dm_row, wanted):
    """이 채널을 일지에 실을 것인가 → bool.

    `wanted` 가 `None` 이면 **기본 규칙**(진단 채널만 뺀다), 집합이면 그 안에
    있는 것만. 판정 기준은 `_channel_info` 의 **표시 이름**이다 — 환산 채널은
    `return_measurement_info` 가 measurement 를 비우므로 원본 컬럼을 봐야
    한다(그러지 않으면 환산된 온도가 목록에서 통째로 빠진다).
    """
    name = _channel_info(dm_row)[2]
    if not name:
        return False
    if wanted is None:
        return name not in DIAGNOSTIC_MEASUREMENTS
    return name in wanted


def measurements_are_weather_only(target_type, target_id):
    """이 대상이 참조하는 센서가 **기상대뿐인가**.

    화면 문구를 고르는 데 쓴다 — 실내 센서가 하나도 없는 구획에서 "포함할
    측정값" 이라고만 하면 어디서 재는 값인지 알 수 없다. 기상대뿐이라면
    그렇게 말하는 편이 정확하다.

    구획이 아니면 판정하지 않는다(False) — 대지·구역의 센서 집합은 실내외가
    섞인 것이 보통이라 이 구분이 뜻을 갖지 않는다.
    """
    if target_type != 'plot':
        return False
    try:
        target_row = resolve_target_row(target_type, target_id)
        indoor, outdoor = _plot_sensor_ids(target_row)
    except Exception:
        return False
    return bool(outdoor) and not indoor


def available_measurements(target_type, target_id):
    """이 대상이 실제로 재는 measurement 목록 → 화면의 선택지.

    ```
    [{'key', 'label', 'diagnostic': bool, 'channels': int, 'default': bool}]
    ```

    **없는 것을 고르게 하지 않는다** — 이 대상에 붙은 센서가 실제로 내는 것만
    낸다. 전체 어휘(`MEASUREMENTS`)를 그대로 보여주면 고를 수 있는 것과 값이
    나오는 것이 달라져, 사용자는 골랐는데 빈 문서를 받는다.
    """
    from aot.databases.models import DeviceMeasurements

    target_row = resolve_target_row(target_type, target_id)
    sensor_ids, _actuators, _unassigned, _area = resolve_devices(
        target_type, target_row)
    ids = [d for d in (sensor_ids or []) if d]
    if not ids:
        return []

    counts = {}
    for dm in DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id.in_(ids)).all():
        name = _channel_info(dm)[2]
        if name:
            counts[name] = counts.get(name, 0) + 1

    out = []
    for key in sorted(counts):
        diagnostic = key in DIAGNOSTIC_MEASUREMENTS
        out.append({'key': key,
                    'label': measurement_label(key),
                    'diagnostic': diagnostic,
                    'channels': counts[key],
                    # 진단 채널은 기본으로 꺼 둔다 — 켜는 것은 사람의 선택이다.
                    'default': not diagnostic})
    return out


def _circular_channel_stats(dm_row, channel, unit, measurement,
                            start_str, end_str, tz, granularity='day',
                            measure_filter=None):
    """방향처럼 **원형인 값**의 버킷별 통계 → `daily_channel_stats` 와 같은 모양.

    ## 왜 선형 경로를 쓸 수 없는가

    0도와 359도는 1도 떨어져 있는데 선형 산술은 358도 떨어진 것으로 센다. 그래서
    `min`/`max`/평균이 전부 틀린다(실측 근거는 `CIRCULAR_UNITS` 주석).

    정답은 **각도를 단위벡터로 바꿔 더한 뒤 각도로 되돌리는 것**(원형평균)이다.
    `min`/`max` 는 원형 값에 정의되지 않으므로 **`None` 으로 둔다** — 0 이나
    아무 값이나 채우면 그 자리에 뜻이 있는 것처럼 보인다.

    ## 접는 규칙을 선형 경로와 맞춘다

    원자료를 받아 **먼저 시간별 원형평균**을 내고, 그 시간별 결과의 단위벡터를
    다시 버킷(일/주)으로 합친다. 원자료를 곧장 버킷으로 합치는 편이 계산은
    간단하지만 그러면 `samples` 가 "원자료 점 수" 가 되어, 분모가 시간 수인
    `coverage` 와 짝이 맞지 않는다(다른 채널과 다른 뜻의 숫자가 같은 열에
    놓인다). 여기서 `samples` 는 **값이 있었던 시간 수**로, 선형 경로와 같다.

    ⚠ 이 경로만 **원자료**를 읽는다(집계 쿼리 3회가 아니라 조회 1회). 메모리는
      버킷 수에 비례할 뿐이라(레코드를 순회하며 누산한다) 점 수가 많아도 늘지
      않는다. 조회 범위 자체는 기간 상한(`MAX_JOURNAL_DAYS`)이 막는다.
    """
    import math

    from aot.utils.influx import query_string
    from aot.utils.timekit import ensure_utc, to_tz

    try:
        tables = query_string(
            unit, dm_row.device_id, channel=channel, measure=measure_filter,
            start_str=start_str, end_str=end_str)
    except Exception as exc:
        logger.warning('journal: 방향 채널 조회 실패(%s ch=%s): %s',
                       dm_row.device_id, channel, exc)
        return None

    # (버킷키, 현지날짜, 현지시) -> [sin 합, cos 합, 개수]
    hours = {}
    for table in (tables or []):
        for rec in table.records:
            try:
                val = float(rec.get_value())
            except (TypeError, ValueError, AttributeError):
                continue
            rec_time = rec.get_time()
            # ⚠ **원자료는 라벨 보정을 하지 않는다.** `bucket_local_key` 의
            #   `bucket_sec` 뺄셈은 `aggregateWindow` 가 구간의 오른쪽 경계로
            #   라벨을 붙이기 때문인데, 원자료의 시각은 관측 시각 그 자체다.
            #   여기에 3600 을 넘기면 모든 값이 한 시간 앞 버킷으로 밀린다.
            key = bucket_key(rec_time, 0, tz, granularity)
            if key is None:
                continue
            try:
                local = to_tz(ensure_utc(rec_time), tz)
            except Exception:
                continue
            box = hours.setdefault((key, local.date(), local.hour),
                                   [0.0, 0.0, 0])
            rad = math.radians(val)
            box[0] += math.sin(rad)
            box[1] += math.cos(rad)
            box[2] += 1

    # 16방위 도수 — **평균 각도보다 이쪽이 읽힌다.** 실측(미러-기상대 1,211
    # 표본)에서 240~269도가 50% 였는데, 그것을 "241.5도" 라고 하면 아무것도
    # 말해 주지 않는다. "서남서 50%" 라야 사람이 쓴다.
    sectors = {}
    for (key, _day, _hour), (sin_sum, cos_sum, count) in hours.items():
        if not count:
            continue
        ang = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0
        idx = int((ang + 11.25) % 360.0 // 22.5)
        box = sectors.setdefault(key, {})
        box[idx] = box.get(idx, 0) + count

    # 시간별 평균방향 → 단위벡터 → 버킷으로 합산.
    acc = {}
    for (key, _day, _hour), (sin_sum, cos_sum, count) in hours.items():
        if not count:
            continue
        norm = math.hypot(sin_sum, cos_sum)
        if norm == 0.0:
            # 그 시간의 방향이 완전히 상쇄됐다 — 평균 방향이 정의되지 않는다.
            # 0도(북)로 채우면 없는 사실을 만들어 내므로 그 시간을 버린다.
            continue
        box = acc.setdefault(key, [0.0, 0.0, 0])
        box[0] += sin_sum / norm
        box[1] += cos_sum / norm
        box[2] += 1

    by_bucket = {}
    for key, (sin_sum, cos_sum, count) in acc.items():
        if math.hypot(sin_sum, cos_sum) == 0.0:
            avg = None
        else:
            avg = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0
        counts = sectors.get(key) or {}
        total = sum(counts.values())
        top_idx = max(counts, key=counts.get) if counts else None
        by_bucket[key] = {
            # 원형 값에는 정의되지 않는다(위 독스트링).
            'min': None, 'max': None,
            # 평균 각도는 계산은 해 두되 화면의 주값이 아니다 — 최다 풍향이
            # 주값이고, 이 값은 그것을 뒷받침한다.
            'avg': avg,
            'sector': top_idx,
            'sector_pct': (round(100.0 * counts[top_idx] / total)
                           if top_idx is not None and total else None),
            'samples': count,
        }
    return {'device_id': dm_row.device_id, 'channel': channel,
            'unit': unit, 'measurement': measurement, 'by_bucket': by_bucket,
            # 화면이 "이 행은 min/max 가 비는 게 정상" 을 알 수 있게 표시한다 —
            # 없으면 고장으로 읽힌다.
            'circular': True}


def env_channel_series(device_ids, start_str, end_str, tz,
                       granularity='day', bucket_sec=3600,
                       measurements=None, outdoor_ids=None, sun_fn=None):
    """센서 장치 id 목록 → 채널별 시계열 + 실패 목록.

    `measurements` 가 주어지면 **그 목록의 measurement 만** 조회한다(없으면
    `DIAGNOSTIC_MEASUREMENTS` 를 뺀 전부). 화면에서 거르지 않고 여기서
    거르는 이유는 **조회 비용**이다 — 안 볼 채널을 InfluxDB 에 묻는 것은
    저사양 기기에서 그대로 부담이 된다.

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

    wanted = None if measurements is None else set(measurements)

    series, errors = [], []
    for dm in rows:
        if not _wanted_measurement(dm, wanted):
            continue
        stats = daily_channel_stats(dm, start_str, end_str, tz,
                                    granularity=granularity,
                                    bucket_sec=bucket_sec, sun_fn=sun_fn)
        if stats is None:
            errors.append({'device_id': dm.device_id,
                           'channel': getattr(dm, 'channel', None),
                           'reason': 'query-failed-or-unusable'})
            time.sleep(QUERY_PACING_SEC)
            continue
        stats['sensor'] = names.get(dm.device_id) or dm.device_id
        # **사용자가 붙인 채널 이름이 정본이다.** measurement 키는 일반명이라
        # 무엇을 재는지 말해 주지 못한다 — 실측: 미러-기상대 ch5 는
        # `length`(길이)인데 사람이 '강우' 라고 이름을 붙여 두었다. 그 이름을
        # 무시하고 '길이' 라고 쓰면 사용자가 자기가 적은 것을 못 알아본다.
        # 지도 위젯이 이미 같은 우선순위를 쓴다(`maps.py` 의 display_name).
        stats['channel_name'] = (getattr(dm, 'name', None) or '').strip() or None
        # 실외(기상)인가. **실내 값과 절대 합치지 않기 위한 표식**이다 —
        # 기상대도 온·습도를 내므로 표시가 없으면 같은 measurement 로 묶여
        # 구획의 온도와 외기가 한 줄이 된다.
        stats['scope'] = ('outdoor' if dm.device_id in (outdoor_ids or set())
                          else 'indoor')
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

def delta_for(target, avg, avg_day=None, avg_night=None):
    """목표 항목 하나와 그날 평균 → `(delta, skipped_reason)`.

    **편차를 낼 수 없는 자리에서 숫자를 지어내지 않는 것이 이 함수의 전부다.**
    돌려주는 `skipped_reason` 이 화면 문구를 정한다.

    - `'method'` — 곡선을 따르는 항목. `_stage_targets` 가 애초에 값을 비운다
      (곡선의 '지금 값' 은 메서드마다 계산이 다르다). 조용히 빠뜨리면 목표가
      없는 것처럼 보이므로 "곡선을 따름" 으로 말한다.
    - `'when'` — 주간/야간 전용 목표. 하루 전체 평균과 견주면 **실측에서 야간
      12도 목표를 한낮 35.6도와 비교해 23.6도 차이라는 허위 경보가 났다**
      (`plot_context._stage_targets` 주석). **이제 그 시간대의 평균을 받으면
      제대로 뺀다** — 일출·일몰로 시간 조각을 갈라 낸 값이다(`sun_lookup`).
      그 값이 없을 때만(태양시를 못 구했거나 그 시간대에 기록이 없다) 예전처럼
      목표만 적고 편차를 비운다.
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
    when = target.get('when')
    if when in ('day', 'night'):
        phase_avg = avg_day if when == 'day' else avg_night
        if phase_avg is None:
            # 그 시간대의 값이 없다 — 하루 평균으로 대신하면 그것이 바로
            # 허위 경보를 냈던 그 계산이다.
            return None, 'when'
        try:
            return round(float(phase_avg) - float(target['value']), 2), None
        except (TypeError, ValueError):
            return None, 'no-reading'
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
        delta, skipped = delta_for(t, row.get('avg'),
                                   avg_day=row.get('avg_day'),
                                   avg_night=row.get('avg_night'))
        row['target'] = t.get('value')
        row['target_label'] = t.get('label')
        row['delta'] = delta
        row['delta_skipped'] = skipped
        row['when'] = t.get('when')
        if skipped == 'method':
            row['follows_curve'] = t.get('method_name')
    return env_rows


# ── 버킷 조립 ───────────────────────────────────────────────────────────────

def cover_light_factor(plot):
    """구획이 든 시설의 **피복 광 투과율**. 시설 밖이거나 알 수 없으면 None.

    반환: `{'tau', 'material', 'inner', 'layers', 'shade'}`.

    ## 왜 필요한가

    실외 일사에서 낸 DLI 는 **하늘이 준 빛**이지 작물이 받은 빛이 아니다.
    쿠마모토 딸기가 실측으로 그랬다 — 실외 42.3 mol/m²/일 인데 비닐 2중
    (투과율 0.78)을 지나면 33.0 이다. 딸기 목표가 17~20 대인 것을 생각하면
    **판단이 갈리는 크기**이고, 그것을 "실외 기준입니다" 라는 주석 한 줄로
    떠넘기면 읽는 사람이 매번 암산해야 한다. 시설은 이미 자기 피복을
    알고 있다(`facility_calc.MATERIALS`).

    ⚠ **차광 커튼은 계수에 넣지 않는다.** 그것은 고정 물성이 아니라 **사람이
      치고 걷는 것**이라, 항상 곱하면 안 친 날의 빛을 과소평가한다. 언제
      쳤는지는 기록에 없다 — 대신 시설에 차광이 있으면 `shade=True` 로
      알리고 문서가 "그날 쳤다면 이보다 적다" 를 말한다.

    ⚠ **두께는 쓰지 않는다.** 물성표가 재질 단위라 같은 재질의 두께 차이를
      구분하지 못한다. 지어내는 것보다 안 쓰는 것이 낫다 — 문서가 무엇을
      근거로 삼았는지(재질) 그대로 적는다.
    """
    fac_uuid = getattr(plot, 'facility_uuid', None)
    if not fac_uuid:
        return None            # 노지 — 실외 일사가 곧 작물이 받는 빛이다
    try:
        from aot.databases.models import GeoFacility
        from aot.aot_flask.geo import facility_calc as FC
        fac = GeoFacility.query.filter_by(unique_id=fac_uuid).first()
        if fac is None:
            return None
        env = FC._normalize_envelope(fac.envelope or {})
        tau = FC.effective_transmittance(
            env.get('layer_count'), env.get('outer_cover'),
            env.get('inner_cover'))
    except Exception:
        logger.exception('journal: 피복 투과율 조회 실패(%s)', fac_uuid)
        return None
    if not tau or not (0.0 < float(tau) <= 1.0):
        # 0 은 불투명(온실이 아니다)이고, 1 은 피복이 없는 것과 같다 —
        # 둘 다 곱해 봐야 사실을 더하지 않으므로 보정하지 않는다.
        return None
    return {'tau': float(tau),
            'material': env.get('outer_cover'),
            'inner': env.get('inner_cover'),
            'layers': int(env.get('layer_count') or 1),
            'shade': bool(env.get('curtain_shade_enabled'))}


def env_rows_by_bucket(series, labels, tz=None, bucket_sec=3600,
                       granularity='day', period_start=None, period_end=None,
                       cover=None):
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
                'channel_name': st.get('channel_name'),
                'scope': st.get('scope') or 'indoor',
                # 반올림은 여기 한 곳에서 한다(`VALUE_DECIMALS`). 안 하면
                # float repr 이 그대로 나간다("71.26782390873016 percent").
                # ⚠ 원형 채널은 `min`/`max` 가 `None` 인 것이 정상이다.
                'min': _round(box.get('min')),
                'max': _round(box.get('max')),
                'avg': _round(box.get('avg')),
                'avg_day': _round(box.get('avg_day')),
                'avg_night': _round(box.get('avg_night')),
                # 원형 값이라 min/max 가 비어 있다는 표시(고장이 아니다).
                'circular': bool(st.get('circular')),
                # 방위 도수 — 원형 채널만 값이 있다.
                'sector': box.get('sector'),
                'sector_pct': box.get('sector_pct'),
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
    # ── DLI 파생 행 ──────────────────────────────────────────────────
    #
    # 일사 채널에서 나온 적산 광량을 **자기 행**으로 세운다. 일사 행에 얹지
    # 않는 이유는 단위가 다르기 때문이다 — 그 행의 평균은 W/m²(순간값)이고
    # DLI 는 mol/m²/일(적산값)이라, 한 줄에 두면 목표·Δ 가 어느 쪽 것인지
    # 알 수 없다. 별도 행이면 `dli_target` 과 그대로 견줄 수 있다.
    for st in (series or []):
        if str(st.get('measurement') or '') not in LIGHT_MEASUREMENTS:
            continue
        for key, box in (st.get('by_bucket') or {}).items():
            if key not in out or box.get('dli') is None:
                continue
            _dli_expected = exp_cache.get(key)
            _dli_coverage = (round((box.get('samples') or 0) / _dli_expected, 3)
                             if _dli_expected else None)
            # ── 피복을 통과시킨다 ────────────────────────────────────────
            # 실외 일사에서 낸 DLI 는 하늘이 준 빛이지 **작물이 받은 빛이
            # 아니다.** 시설 안 구획이면 피복 투과율을 곱한다 — 실측에서
            # 실외 42.3 이 비닐 2중을 지나 33.0 이 됐고, 딸기 목표가 17~20
            # 대라 그 차이로 판단이 갈린다.
            #
            # ⚠ **행을 둘로 늘리지 않는다.** 같은 `dli` 로 두 행을 내면
            #   목표(`dli_target`)가 양쪽에 붙어 Δ 가 어느 쪽 것인지 알 수
            #   없어진다. 값은 작물이 받은 쪽으로 두고, 근거(실외값·계수·
            #   재질)를 행에 실어 문서가 그대로 말하게 한다.
            _dli_scope = st.get('scope') or 'indoor'
            _dli_value = box.get('dli')
            _dli_cover = None
            if cover and _dli_scope == 'outdoor' and _dli_value is not None:
                _dli_cover = dict(cover, outdoor=_round(_dli_value))
                _dli_value = _dli_value * cover['tau']
                _dli_scope = 'indoor'
            out[key].append({
                'device_id': st.get('device_id'),
                'channel': st.get('channel'),
                'sensor': st.get('sensor'),
                'measurement': 'dli',
                'unit': 'mol_m2_d',
                'channel_name': None,
                'scope': _dli_scope,
                # 피복을 지났으면 그 근거를 행이 들고 다닌다 — 화면·CSV·ODT가
                # 각자 다시 계산하면 갈라진다.
                'cover': _dli_cover,
                'min': None, 'max': None,
                'avg': _round(_dli_value),
                'avg_day': None, 'avg_night': None,
                'circular': False, 'sector': None, 'sector_pct': None,
                # 커버리지는 **원천 일사 채널의 것을 그대로 이어받는다.**
                # 비워 두면 기록이 반나절뿐인 날의 DLI 도 온전한 값처럼
                # 보이는데, DLI 는 적산값이라 빠진 시간만큼 그대로 적게 나온다.
                'samples': box.get('samples') or 0,
                'expected': exp_cache.get(key),
                'coverage': _dli_coverage,
                'coverage_low': (_dli_coverage is not None
                                 and _dli_coverage < MIN_COVERAGE),
                'usage': None,
                # 가정 위에 선 값인지 — 화면이 그대로 말해야 한다.
                'estimated': bool(st.get('dli_assumed')),
            })

    for key in out:
        # 이름순이 아니라 **중요도순**(`MEASUREMENT_ORDER`). 같은 측정값
        # 안에서는 실내를 먼저 두어 실외와 나란히 놓이게 한다 — 두 값을
        # 견주는 것이 이 표를 보는 이유다.
        out[key].sort(key=lambda r: (
            measurement_rank(r.get('measurement')),
            str(r.get('measurement') or ''),
            0 if (r.get('scope') or 'indoor') == 'indoor' else 1,
            str(r.get('sensor') or '')))
    return out


def control_rows_by_bucket(actuators, start_str, end_str, tz,   # noqa: C901
                           granularity='day', bucket_sec=3600, labels=None,
                           flows=None):
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
            row = {
                'output_id': oid,
                'name': a.get('name'),
                'kind': a.get('kind'),
                'scope': a.get('scope'),
                'seconds': int(secs),
                'hours': round(secs / 3600.0, 2),
            }
            # 설계 유량이 있으면 물량을 **추정**한다. 유량계 실측이 있으면
            # 그쪽이 이기므로(env 행의 `usage`) 여기서는 늘 '추정' 이다.
            flow = (flows or {}).get(oid)
            if flow and flow.get('lph'):
                litres = secs / 3600.0 * flow['lph'] * flow.get('share', 1.0)
                row['water'] = {
                    'litres': round(litres, 1),
                    'share': flow.get('share', 1.0),
                    'estimated': True,
                    # 근거가 배관 도면인지 지도 장비인지 — 나누는 방식이
                    # 아예 달라(동의 몫 · 구획 안 노즐) 문서 문장이 갈린다.
                    # 여기서 안 실으면 조립부가 알 길이 없어 시설용 문장이
                    # 노지 문서에 붙는다(실측으로 그랬다).
                    'source': flow.get('source'),
                }
            out[key].append(row)
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
        if granularity == 'week':
            key = d - timedelta(days=d.weekday())
        elif granularity == 'month':
            key = d.replace(day=1)
        else:
            key = d
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

def _plot_sensor_ids(plot, with_weather=True):
    """구획이 참조할 센서 id → `(실내 set, 실외 set)`.

    실내 우선순위는 `sensors_for_plot()` 그대로(배타적 체인). **실외(기상)는
    그 체인과 겨루지 않고 따로 온다** — 일사·강우는 대지에 하나 있는 기상대가
    재고, 구획 안에 온습도계가 있다는 이유로 빠지면 안 되기 때문이다.

    `measurable_in_plot()`(측정 이름만 필요)·`_plot_temperature_channels()`
    (GDD 채널)와 같은 우선순위를 세 번째로 반복한다 — 새 기준이 아니라 같은
    기준을 "이 구획이 참조하는 센서 id 전부" 라는 다른 산출물로 다시 읽는
    것뿐이다. 별도 공개 함수로 빼지 않은 이유는 소비처가 이 파일 하나뿐이기
    때문이다.
    """
    try:
        found = plot_context.sensors_for_plot(plot) or {}
    except Exception:
        return set(), set()
    ids = (list(found.get('in_plot') or [])
           or list(found.get('in_bay') or [])
           or list(found.get('from_facility') or [])
           or list(found.get('from_zone') or []))
    outdoor = set(found.get('from_weather') or []) if with_weather else set()
    # 같은 장치가 양쪽에 잡히면(대지에 기상대만 있고 그것이 구역 센서로도
    # 걸리는 설치) **실내에서 뺀다** — 실외로 보는 편이 사실에 가깝고, 양쪽에
    # 두면 같은 값이 표에 두 번 나온다.
    return set(ids) - outdoor, outdoor


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

    ⚠ **`kind_label`(번역된 라벨)을 여기서 계산해 저장하지 않는다 — 실제
      브라우저 검증에서 잡은 결함이다.** 이 함수는 백그라운드 생성 스레드
      (`_run_journal_build`)에서 불린다. 그 스레드는 앱 컨텍스트는 있어도
      **요청 컨텍스트가 없어** `flask_babel.gettext`가 로케일을 못 정하고
      영어로 떨어지는데, 그 값이 스냅샷에 그대로 굳어 저장된다 — §7 에서
      `title`/`summary`에 대해 이미 고친 것과 **같은 함정**을 `kind_label`
      에서는 놓쳤다. 원문 코드(`kind`)만 저장하고, 사람이 읽는 라벨은 열람
      시점(라우트·Markdown 렌더)에 `_target_kind_label()`을 다시 불러
      얻는다 — `caveat_text()`와 같은 패턴이다.
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
        sensor_ids, outdoor_ids = _plot_sensor_ids(target_row)
        actuators, unassigned = plot_context.actuators_for_plot(target_row)
        return sensor_ids | outdoor_ids, actuators, unassigned, None

    from aot.aot_flask.geo import device_membership

    area_ids = device_membership.device_ids_in_area(target_row.unique_id)
    if area_ids is None:
        # ⚠ `None` 은 "거르지 않는다" 라는 그 함수의 계약이지 "장치가 없다" 가
        #   아니다. 빈 집합으로 접으면 **지워진 구역에 대해 "장치 없음" 일지가
        #   조용히 만들어진다**(§3).
        raise ValueError('대상 도형을 찾을 수 없습니다 (%s)' % target_row.unique_id)
    return (plot_context._only_sensor_ids(area_ids),
            _area_actuators(area_ids), 0, area_ids)


def _rows_for(env_channels, circular_channels, control_channels, days):
    """조회 규모(행 수) 추정 → int. **게이트와 저장 단위 판정이 함께 쓴다.**

    두 곳이 따로 세면 갈라지고, 갈라지면 게이트를 통과해 놓고 다른 규모로 도는
    일이 생긴다 — 이 저장소가 반복해서 겪은 모양이다.
    """
    bucket_sec = 3600     # 최악(가장 잘게 써는 tz)은 900 이지만 4배는 예산에
                          # 여유가 있어 대표값으로 3600 을 쓴다
    per_day = 86400 // bucket_sec
    plain_queries = (env_channels - circular_channels) * 3 + control_channels
    # 원자료 채널은 시간당 한 점이 아니라 **여러 점**이 온다(실측 약 53점).
    # 예산은 **큰 쪽으로 틀려야** 안전하다.
    return (plain_queries * days * per_day
            + circular_channels * days * per_day * CIRCULAR_POINTS_PER_HOUR)


def first_data_at(target_type, target_id, max_channels=12):
    """이 대상의 자료가 **실제로 언제부터** 있는가 → date | None.

    대지·구역에는 구획의 `started_on` 같은 날짜가 없어, 사람이 감으로 기간을
    넣으면 앞쪽이 통째로 빈 문서가 나온다(실측: 10개 버킷 중 7개). 그 시작
    시각은 시스템이 아는 사실이므로 추측시킬 이유가 없다.

    채널마다 `first()` 한 번씩만 묻는다. **채널이 많으면 앞의 몇 개만 본다** —
    이건 폼을 채워 주는 편의 기능이라 사람을 기다리게 할 값이 아니고, 가장 이른
    시각을 정확히 맞히지 못해도 사람이 고쳐 넣으면 된다.
    """
    from aot.databases.models import DeviceMeasurements
    from aot.utils.influx import query_string
    from aot.utils.timekit import to_tz

    target_row = resolve_target_row(target_type, target_id)
    sensor_ids, actuators, _unassigned, _area = resolve_devices(
        target_type, target_row)

    ids = [d for d in (sensor_ids or []) if d]
    ids += [a.get('output_id') for a in (actuators or []) if a.get('output_id')]
    if not ids:
        return None

    rows = DeviceMeasurements.query.filter(
        DeviceMeasurements.device_id.in_(ids)).all()

    from aot.utils.device_tz import resolve_location_tz
    tz = resolve_location_tz(target_id)

    earliest = None
    looked = 0
    for dm in rows:
        if looked >= max_channels:
            break
        channel, unit, _display, measure_filter = _channel_info(dm)
        if unit is None:
            continue
        looked += 1
        try:
            tables = query_string(unit, dm.device_id, channel=channel,
                                  measure=measure_filter, value='FIRST')
        except Exception:
            continue
        for table in (tables or []):
            for rec in table.records:
                stamp = rec.get_time()
                if stamp is None:
                    continue
                if earliest is None or stamp < earliest:
                    earliest = stamp
    if earliest is None:
        return None
    try:
        return to_tz(earliest, tz).date()
    except Exception:
        return None


def journal_row_estimate(sensor_ids, actuators, start_date, end_date,
                         measurements=None):
    """이미 찾아 둔 장치로 행 수를 센다 → int.

    `estimate_journal_cost` 는 대상 uuid 로 장치를 **다시 찾는다**(라우트가
    시작 전에 부르는 자리라 그게 맞다). 조립 중에는 이미 손에 있으므로 그것을
    그대로 쓴다 — 판정식은 `_rows_for` 하나로 같다.
    """
    days = (end_date - start_date).days + 1
    env_channels, circular_channels = count_channels_detail(sensor_ids,
                                                            measurements)
    control_channels = len([a for a in (actuators or []) if a.get('output_id')])
    return _rows_for(env_channels, circular_channels, control_channels, days)


def count_channels_detail(sensor_ids, measurements=None):
    """이 센서들이 실제로 조회될 채널 수 → `(전체, 원형)`.

    `env_channel_series` 가 도는 것과 같은 기준으로 센다 — 환산이 걸려
    measurement 가 빈 채널은 그쪽이 건너뛰므로(`_channel_info`) 여기서도
    빼야 게이트의 숫자가 실제 쿼리 수와 맞는다.

    **원형 채널을 따로 세는 이유**: 그 채널만 집계가 아니라 **원자료**를 읽어서
    (`_circular_channel_stats`) 같은 기간·같은 채널 수라도 오가는 자료량이 훨씬
    크다. 하나로 뭉뚱그려 세면 게이트를 통과해 놓고 실제로는 다른 규모로 도는,
    이 저장소가 반복해서 겪은 모양의 실패가 된다.
    """
    from aot.databases.models import DeviceMeasurements

    ids = [d for d in (sensor_ids or []) if d]
    if not ids:
        return 0, 0
    rows = DeviceMeasurements.query.filter(
        DeviceMeasurements.device_id.in_(ids)).all()
    wanted = None if measurements is None else set(measurements)
    total = circular = 0
    for dm in rows:
        unit = _channel_info(dm)[1]
        if unit is None:
            continue
        # 게이트는 **실제로 도는 것과 같은 것**을 세야 한다 — 안 실을 채널까지
        # 세면 통과할 요청이 거절된다(그 반대보다는 낫지만 여전히 틀린 답이다).
        if not _wanted_measurement(dm, wanted):
            continue
        total += 1
        if unit in CIRCULAR_UNITS:
            circular += 1
    return total, circular


def count_channels(sensor_ids, measurements=None):
    """이 센서들이 실제로 조회될 **채널 수** → int.

    판정은 `count_channels_detail` 하나가 한다 — 두 벌을 두면 갈라진다.
    """
    return count_channels_detail(sensor_ids, measurements)[0]


def build_journal_for_target(target_type, target_id, start_date, end_date,
                             measurements=None, granularity=None):
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
    s_str, e_str = period_bounds_utc(start_date, end_date, tz)
    s_dt, e_dt = period_bounds_utc(start_date, end_date, tz, as_str=False)

    caveats = [AVG_IS_TIME_WEIGHTED]
    errors = []

    # ── 장치 조회(§3) ────────────────────────────────────────────────────
    (sensor_ids, actuators, unassigned_areas,
     area_device_ids) = resolve_devices(target_type, target_row)

    # 어느 것이 실외(기상)인가. 구획은 대지의 기상원을 따로 받고, zone/site
    # 대상은 자기 안에 기상대가 있으면 그것이 곧 실외다.
    if target_type == 'plot':
        _indoor, outdoor_ids = _plot_sensor_ids(target_row)
    else:
        from aot.aot_flask.geo import device_membership as _dm
        outdoor_ids = set(_dm.weather_device_ids(target_row.unique_id)[0])
    outdoor_ids = {d for d in outdoor_ids if d in set(sensor_ids)}

    # ── 저장 단위 ────────────────────────────────────────────────────────
    # 저장은 되도록 **일 단위**로 한다 — 주·월·전체는 열람할 때 `fold_buckets`
    # 가 만든다(접는 것은 되돌릴 수 있어도 편 것은 되돌릴 수 없다). 일 단위로
    # 행 예산을 넘길 때만 주간으로 내려간다.
    #
    # 예산은 **이미 찾아 둔 장치로** 센다(`estimate_journal_cost` 를 다시 부르면
    # 대상·장치 조회가 통째로 한 번 더 돈다). 세는 식은 그쪽과 같아야 하므로
    # `journal_row_estimate` 하나를 둘이 함께 쓴다 — 두 벌이 되면 갈라지고,
    # 갈라지면 게이트를 통과해 놓고 다르게 도는 일이 생긴다.
    # 무엇을 빼는지 **먼저 알아 둔다** — 조회한 결과만 보면 "값이 없었다" 와
    # "안 실었다" 가 구별되지 않는다.
    excluded_measurements = []
    try:
        wanted = None if measurements is None else set(measurements)
        from aot.databases.models import DeviceMeasurements as _DM
        seen = set()
        _ids = [d for d in (sensor_ids or []) if d]
        if _ids:
            for dm in _DM.query.filter(_DM.device_id.in_(_ids)).all():
                name = _channel_info(dm)[2]
                if name and not _wanted_measurement(dm, wanted):
                    seen.add(name)
        excluded_measurements = sorted(seen)
    except Exception:
        logger.exception('journal: 제외 목록 산정 실패')

    est_rows = journal_row_estimate(sensor_ids, actuators, start_date, end_date,
                                    measurements=measurements)
    granularity = choose_granularity(start_date, end_date, rows=est_rows,
                                     requested=granularity)
    caveats_forced_week = (granularity != 'day')
    labels = bucket_labels(start_date, end_date, granularity)

    # ── 환경(§4-2~4-3) ───────────────────────────────────────────────────
    # 태양시 — 주야 목표의 편차와 버킷의 일장이 이것에 달렸다.
    sun_fn = sun_lookup(target_id)

    # 적산온도 — 구획에만 있다(프로그램의 T_base 가 필요하다).
    gdd = (gdd_for_journal(target_row, end_date, start_date)
           if target_type == 'plot' else None)
    photo_targets = (photosynthesis_targets(target_row)
                     if target_type == 'plot' else [])

    series, env_errors = env_channel_series(
        sensor_ids, s_str, e_str, tz, granularity=granularity,
        bucket_sec=bucket_sec, measurements=measurements,
        outdoor_ids=outdoor_ids, sun_fn=sun_fn)
    errors.extend({'kind': 'env', **e} for e in env_errors)
    # 피복 투과율은 **한 번만** 조회한다 — 버킷마다 시설을 다시 읽으면
    # 반년짜리 문서에서 같은 질의를 수백 번 한다.
    cover = cover_light_factor(target_row) if target_type == 'plot' else None
    env_by_bucket = env_rows_by_bucket(
        series, labels, tz=tz, bucket_sec=bucket_sec, granularity=granularity,
        period_start=start_date, period_end=end_date, cover=cover)

    # ── 목표 대비 편차(§4-5, plot 만) ────────────────────────────────────
    stages = None
    if target_type == 'plot':
        stages = _plot_stages(target_row)
        # ⚠ `if stages:` 로 감싸지 않는다. 광합성 목표(DLI)는 **프로그램
        #   수준**이라 단계가 없어도 견줄 수 있는데, 단계 유무로 막으면
        #   단계를 안 짠 프로그램에서 DLI 가 통째로 사라진다.
        if stages or photo_targets:
            for key, rows in env_by_bucket.items():
                # 주간 버킷은 그 주의 월요일(현지)로 대표해 비교한다 — 단계가
                # 주 중간에 바뀌면 그 주는 월요일 쪽 단계로 잡힌다. 정확한
                # 주중 전환 판정은 이번 범위 밖이다(일별 상세로 보면 정확하다).
                st = stage_at(stages, key) if stages else None
                stage_targets = (st.get('targets') or []) if st else []
                attach_targets(rows, list(stage_targets) + photo_targets)

    # ── 제어(§4-4) ───────────────────────────────────────────────────────
    # 설계 유량 — 시설 구획에만 있다(노지에는 배관 도면이라는 것이 없다).
    flows = (irrigation_flow_for_plot(target_row)
             if target_type == 'plot' else {})

    control_by_bucket, ctrl_errors = control_rows_by_bucket(
        actuators, s_str, e_str, tz, granularity=granularity,
        bucket_sec=bucket_sec, labels=labels, flows=flows)
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
        if granularity == 'month':
            return key.strftime('%Y-%m')
        return key.isoformat()

    buckets = []
    for key in labels:
        env_rows = env_by_bucket.get(key) or []
        control_rows = control_by_bucket.get(key) or []
        note_rows = notes_by_bkt.get(key) or []
        # 일장 — 주간 버킷이면 그 주 월요일 기준이라 대표값이다(하루 단위로
        # 보면 정확하다). 못 구하면 `None` 이고 화면이 그 자리를 비운다.
        sun = sun_fn(key) if sun_fn else None
        # ⚠ `sun_times` 는 **UTC** 로 준다(실측: 일출 20:59Z = 05:59 KST).
        #   그대로 찍으면 일출이 저녁, 일몰이 아침으로 보인다 — 값은 맞는데
        #   화면만 틀리는 종류라 숫자를 봐서는 못 알아챈다.
        #   ⚠ 밤낮 판정(`_phase`)은 aware 끼리 비교하므로 **이미 옳다** —
        #     그쪽을 따라 고치지 말 것.
        def _hhmm(moment):
            try:
                return to_tz(moment, tz).strftime('%H:%M')
            except Exception:
                return None
        buckets.append({
            # 접기(`fold_buckets`)가 되짚을 수 있게 원본 키를 함께 싣는다 —
            # 라벨은 사람이 읽는 문자열이라 파싱해서 쓸 것이 못 된다.
            'key': key.isoformat(),
            'sunrise': _hhmm(sun[0]) if sun else None,
            'sunset': _hhmm(sun[1]) if sun else None,
            'daylight_h': sun[2] if sun else None,
            # 그날 쌓인 적산온도. 주간·월간으로 접을 때는 **합**이다.
            'gdd': (_round((gdd.get('by_day') or {}).get(key), 1)
                    if gdd and gdd.get('usable') else None),
            'date_label': _label(key),
            'env': env_rows,
            'control': control_rows,
            'notes': note_rows,
            'empty': not (env_rows or control_rows or note_rows),
        })

    buckets = collapse_edge_gaps(buckets)

    if excluded_measurements:
        caveats.append('measurements-excluded:%s'
                       % ','.join(excluded_measurements))

    # DLI 가 어떤 값인지 문서가 스스로 말한다 — 환산 가정과 측정 위치를
    # 모르면 목표와의 차이를 잘못 읽는다(실외 42 대 목표 22 는 시설 안이
    # 그만큼 밝았다는 뜻이 아니다).
    _dli_rows = [e for b in buckets for e in (b.get('env') or [])
                 if e.get('measurement') == 'dli']
    # 물량이 설계 유량 추정임을 문서가 말한다 — 유량계 실측과 섞여 보이면
    # 사람은 둘을 같은 신뢰도로 읽는다.
    _ctrl_rows = [c for b in buckets for c in (b.get('control') or [])]
    _waters = [c['water'] for c in _ctrl_rows if c.get('water')]
    if _waters:
        # 근거가 배관 도면인지 지도 장비인지에 따라 문장이 다르다 — 나누는
        # 방식(동의 몫 · 구획 안 노즐)이 아예 달라서, 한 문장으로 뭉치면
        # 어느 쪽으로 나눈 값인지 알 수 없다.
        if any(w.get('source') == 'map-equipment' for w in _waters):
            caveats.append('water-estimated-map')
        if any(w.get('source') != 'map-equipment' for w in _waters):
            caveats.append('water-estimated')
    elif _ctrl_rows:
        # 물량 칸이 하나도 안 채워졌다. 화면은 그 열을 아예 내지 않고(§10),
        # 문서는 왜 없는지를 여기서 말한다 — 예전에는 열이 빈 채로 남아
        # "관수량이 계산되지 않는다" 로 읽혔다(실제로 그 보고를 받았다).
        #
        # ⚠ **어느 장치가 관수인지 판정하지 않는다.** Output 은 통신 방식만
        #   알 뿐 의미 분류가 없고(실측: 노지 밸브 `v331` 의 `kind` 가
        #   `None`), 이름으로 맞히려 하면 `v331` 같은 이름에서 조용히 틀린다.
        #   그래서 문장을 **관수 여부가 아니라 그 열에 대한 사실**로 쓴다.
        caveats.append('water-no-flow-basis')

    if _dli_rows:
        if any(e.get('estimated') for e in _dli_rows):
            caveats.append('dli-estimated')
        _covered = [e for e in _dli_rows if e.get('cover')]
        if _covered:
            # 재질과 계수를 접미사로 실어, 문서가 무엇을 근거로 삼았는지
            # 그대로 말하게 한다(계수만 적으면 어디서 온 숫자인지 모른다).
            c = _covered[0]['cover']
            caveats.append('dli-through-cover:%s:%s' % (
                c.get('material') or '?', c.get('tau')))
            if c.get('shade'):
                caveats.append('dli-shade-not-counted')
        elif any((e.get('scope') or 'indoor') == 'outdoor' for e in _dli_rows):
            caveats.append('dli-outdoor')

    if caveats_forced_week:
        # 일 단위로는 예산을 넘겨 접어서 저장했다 — 열람 화면이 "일간" 을
        # 못 고르는 이유가 여기 있으므로 문서가 그 사실을 말해야 한다.
        caveats.append('stored-weekly-too-large')
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
        # `by_day` 는 위 버킷을 채우는 데만 쓴 작업값이라 뺀다 — 키가 `date`
        # 객체라 그대로 두면 **저장 자체가 실패한다**(위 함수의 경고 참조).
        'gdd': ({k: v for k, v in gdd.items() if k != 'by_day'}
                if gdd else None),
        # 무엇을 실었는지 **문서가 스스로 말해야 한다** — 없는 것과 안 실은
        # 것은 읽는 사람에게 구별되지 않는다("왜 온도가 없지?").
        'measurements': {
            'selected': (sorted(measurements)
                         if measurements is not None else None),
            'excluded': excluded_measurements,
        },
        'buckets': buckets,
        'caveats': caveats,
        'errors': errors,
        'generated_at': utc_now(),
    }


def collapse_edge_gaps(buckets):
    """**앞뒤로 이어진 빈 버킷**을 한 항목으로 접는다 → 새 버킷 목록.

    ## 왜 앞뒤만인가

    육묘장 실측에서 10개 주간 버킷 중 **7개(70%)가 "데이터 없음" 만** 반복했다.
    사용자가 데이터가 언제부터 있는지 모른 채 기간을 넉넉히 잡았기 때문인데,
    그 결과 문서의 대부분이 같은 문장의 사본이 된다.

    **가운데 낀 빈 구간은 접지 않는다** — 값이 있다가 끊겼다가 다시 온 것은
    그 자체가 사실이고(센서 고장·정전), 접으면 그 사실이 사라진다. 접어도 되는
    것은 **아직 시작 안 한 앞쪽과 이미 끝난 뒤쪽**뿐이다.
    """
    rows = list(buckets or [])
    if not rows:
        return rows

    first_data = next((i for i, b in enumerate(rows) if not b.get('empty')),
                      None)
    if first_data is None:
        # 전 구간이 비었다 — 통째로 한 줄로 접는다.
        return [_gap_bucket(rows)]

    last_data = next(i for i in range(len(rows) - 1, -1, -1)
                     if not rows[i].get('empty'))

    out = []
    if first_data > 0:
        out.append(_gap_bucket(rows[:first_data]))
    out.extend(rows[first_data:last_data + 1])
    if last_data < len(rows) - 1:
        out.append(_gap_bucket(rows[last_data + 1:]))
    return out


def _gap_bucket(group):
    """연속된 빈 버킷들 → 한 줄로 접은 '빈 구간' 항목."""
    def _start(bucket):
        return str(bucket.get('key')
                   or str(bucket.get('date_label') or '')[:10])

    def _end(bucket):
        label = str(bucket.get('date_label') or '')
        return label.split('~')[-1].strip() if '~' in label else _start(bucket)

    return {
        'key': _start(group[0]),
        'date_label': ('%s ~ %s' % (_start(group[0]), _end(group[-1]))
                       if len(group) > 1 else group[0].get('date_label')),
        'env': [], 'control': [], 'notes': [],
        'empty': True,
        # 몇 개를 접었는지 화면이 말할 수 있게 남긴다 — "7주간 기록 없음" 과
        # "기록 없음" 은 사용자에게 다른 정보다.
        'gap_count': len(group),
    }


def stage_sections(journal_data):
    """저장된 스냅샷 → **단계별 실제 기록** 목록. 열람 시점 순수 계산이다.

    ```
    [{'stage': 원본 단계, 'in_period': bool, 'days': int,
      'starts_on', 'ends_on',            # 이 문서의 기간과 겹치는 구간
      'env_groups': [...], 'control': [...], 'notes': [...], 'photos': [...]}]
    ```

    ## 왜 필요한가 (실사용에서 나온 지적)

    예전에는 단계 절이 **프로그램의 계획표**를 그대로 옮겨 놓기만 했다. 딸기
    구획의 5일짜리 일지에 단계 6개가 통째로 실렸는데 그중 **다섯은 이 문서의
    기간과 아무 상관이 없었고**(2026-12월까지의 미래), 겹치는 하나조차 지침과
    목표만 있고 그 기간에 **실제로 무슨 일이 있었는지는 한 줄도 없었다.**
    사용자가 "단계에 아무 내용이 없다" 고 한 것이 이것이다.

    여기서는 이미 저장된 버킷을 단계 구간으로 갈라 붙인다 — **InfluxDB 를 다시
    읽지 않는다**(`fold_buckets` 와 같은 규칙). 그래서 이 수정 이전에 만들어진
    일지도 열기만 하면 내용이 채워진다.

    **기간 밖 단계를 지우지는 않는다.** 계획 전체를 보는 것도 문서의 값이라
    `in_period=False` 로 표시만 하고, 화면이 접어 둔다 — 지우면 "이 작기가
    앞으로 어떻게 가는가" 를 문서가 말할 수 없게 된다.
    """
    stages = (journal_data or {}).get('stages') or []
    buckets = (journal_data or {}).get('buckets') or []
    if not stages:
        return []

    def _as_date(value):
        if not value:
            return None
        try:
            return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None

    # 버킷을 날짜로 색인한다. 접힌 '빈 구간'(gap_count)은 여러 날을 대표하므로
    # 시작일만 갖고는 못 가른다 — 어차피 내용이 없으니 넘긴다.
    dated = []
    for bucket in buckets:
        if bucket.get('gap_count'):
            continue
        key = _as_date(bucket.get('key') or bucket.get('date_label'))
        if key is not None:
            dated.append((key, bucket))

    out = []
    for stage in stages:
        starts = _as_date(stage.get('starts_on'))
        ends = _as_date(stage.get('ends_on'))
        mine = [(k, b) for k, b in dated
                if (starts is None or k >= starts)
                and (ends is None or k <= ends)]

        # **'예정' 과 '지난' 을 가른다.** 기간 밖이라고 전부 앞으로 올 일은
        # 아니다 — 문서 기간보다 **먼저 끝난** 단계도 기간 밖이고, 그것을
        # '예정' 이라 부르면 이미 한 일이 앞으로 할 일로 읽힌다(실측에서
        # 정식기가 그렇게 표시됐다).
        period = (journal_data.get('target') or {}).get('period') or {}
        doc_start = _as_date(period.get('start'))
        when = 'planned'
        if ends is not None and doc_start is not None and ends < doc_start:
            when = 'past'

        section = {
            'stage': stage,
            'in_period': bool(mine),
            'when': 'current' if mine else when,
            'days': len(mine),
            'starts_on': min(k for k, _b in mine).isoformat() if mine else None,
            'ends_on': max(k for k, _b in mine).isoformat() if mine else None,
            'env_groups': [], 'control': [], 'notes': [], 'photos': [],
        }
        if mine:
            merged = _merge_bucket_group(
                {'days': [b for _k, b in mine],
                 'first': min(k for k, _b in mine),
                 'last': max(k for k, _b in mine)}, 'all')
            section['env_groups'] = group_env_rows(merged.get('env') or [])
            section['control'] = merged.get('control') or []
            section['notes'] = merged.get('notes') or []
            # 사진은 노트 안에 흩어져 있다 — 단계 절에서 한눈에 보이게 모은다.
            for note in section['notes']:
                for name in (note.get('image_files') or []):
                    section['photos'].append({'file': name,
                                              'time': note.get('time'),
                                              'title': note.get('title')})
        out.append(section)
    return out


#: 16방위. **번역 대상**이라 여기서 한국어로 박지 않는다 — 방위 이름은
#: 언어마다 다르고(N/S/E/W ↔ 북/남/동/서), 22개 로케일로 나간다.
COMPASS_16 = (
    'N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
    'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW',
)


def compass_label(index):
    """16방위 번호 → 뷰어 언어의 방위 이름. 범위를 벗어나면 `None`."""
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return None
    if not (0 <= idx < len(COMPASS_16)):
        return None
    return _gettext_safe(COMPASS_16[idx])


#: 실외(기상) 문맥에서만 바꿔 부르는 측정값.
#:
#: `speed`·`direction` 의 정의명은 "속도"·"방향" 이다. 정의를 바꾸면 팬
#: 회전수처럼 같은 measurement 를 쓰는 다른 용도까지 함께 바뀐다 — 그래서
#: **기상 문맥에서만** 바꿔 부른다. 근거는 이미 있다(`scope='outdoor'`).
_OUTDOOR_LABELS = {
    'speed': 'Wind speed',
    'direction': 'Wind direction',
}


def runtime_text(row):
    """제어 행 → 가동시간 문구. **단위를 상황에 맞춘다.**

    ⚠ 시간으로만 쓰면 관수가 사라진다. 밸브는 분 단위로 도는 것이 정상이라
      6초 가동이 `0.0 시간` 으로 반올림되는데, 물량은 21.8 L 로 찍힌다 —
      "0시간인데 물이 나왔다" 는 모순으로 읽힌다(실측).

    1시간 미만은 분, 1분 미만은 초로 쓴다.
    """
    try:
        seconds = float(row.get('seconds') or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds >= 3600:
        return '%s %s' % (round(seconds / 3600.0, 2), _gettext_safe('h'))
    if seconds >= 60:
        return '%s %s' % (round(seconds / 60.0, 1), _gettext_safe('min'))
    if seconds > 0:
        return '%s %s' % (int(round(seconds)), _gettext_safe('s'))
    return '0 %s' % _gettext_safe('h')


def measurement_label(key, scope=None):
    """측정 키 → 사람이 읽는 이름(뷰어 언어). 모르는 키는 그대로 돌려준다.

    정본은 `MEASUREMENTS`(`config_devices_units.py`) 하나다 — 일지가 자기
    이름표를 따로 들면 같은 값이 화면마다 다른 이름으로 보인다(지도 위젯이
    'VPD' 로 되돌리는 정규화를 따로 들고 있던 것이 바로 그 증상이다).

    ⚠ **저장하지 않는다.** 이름은 번역 대상이라 저장하면 생성 시점의 언어로
      굳는다 — `title`/`summary`·`kind_label`·`caveat_text` 와 같은 규칙이다.

    ⚠ `MEASUREMENTS` 의 이름은 `lazy_gettext` 객체다. **참/거짓으로 평가하지
      말 것** — 그 순간 `__len__` → `str()` 이 불려 번역이 강제되고, 요청
      컨텍스트가 없으면 거기서 예외가 난다. `is None` 으로만 본다.
    """
    from aot.config_devices_units import MEASUREMENTS

    if not key:
        return key
    if str(key) == 'dli':
        # 측정 정의(`MEASUREMENTS`)에 없는 **파생값**이라 여기서 이름을 준다.
        return _gettext_safe('DLI')
    if scope == 'outdoor' and str(key) in _OUTDOOR_LABELS:
        return _gettext_safe(_OUTDOOR_LABELS[str(key)])
    entry = MEASUREMENTS.get(str(key))
    if entry is None:
        return key
    name = entry.get('name')
    if name is None:
        return key
    try:
        return str(name) or key
    except Exception:
        # 요청 컨텍스트 밖이면 번역할 수 없다 — 원문 키로 되돌린다.
        return key


def group_env_rows(rows):
    """버킷 하나의 env 행 → **측정값별로 묶은 표시용 그룹** 목록.

    ```
    [{'measurement', 'unit', 'sensors': [원본 행, …], 'summary': {…}|None}, …]
    ```

    ## 왜 필요한가 (실사용에서 드러난 것)

    같은 것을 재는 센서가 여럿이면 버킷마다 그만큼 줄이 는다 — 육묘장 실측에서
    습도 센서 7개가 **버킷마다 7줄**을 차지했다. 시간축은 접으면서 센서축은 하나도
    안 접으니, 사람이 "요약" 이라 부를 만한 것이 나오지 않는다.

    ## 그런데 대표 하나를 골라서는 안 된다

    §4-3 이 정한 것 — 같은 measurement 를 재는 센서가 여럿일 때 하나를 대표로
    뽑으면 **실제 위치별 편차가 감춰진다.** 그래서 여기서 하는 일은 고르는 것이
    아니라 **접는 것**이다: 대표 줄에 그룹 전체의 범위를 내고, 개별 센서 행은
    그대로 딸려 보내 화면이 펼칠 수 있게 한다(HTML `<details>`). 값은 하나도
    사라지지 않는다.

    ⚠ **저장된 스냅샷을 고치지 않는다.** 이 함수는 열람할 때마다 도는 순수
      계산이라 `GeoJournal.data` 와 JSON·MCP 내보내기는 원본 그대로다 — 접는
      것은 보는 방식이지 사실이 아니다.

    `summary` 는 센서가 **둘 이상일 때만** 만든다(하나면 접을 것이 없다).
    """
    import math

    groups = {}
    order = []
    for raw in (rows or []):
        # ⚠ **사본을 만들어 반올림한다.** 이유가 둘이다: (1) 원본은 저장된
        #   스냅샷(`GeoJournal.data`)이라 제자리에서 고치면 JSON 컬럼이
        #   더럽혀진다. (2) 반올림을 여기서도 하면 **반올림 이전에 만들어진
        #   일지도 제대로 보인다** — 저장 시점에만 하면 옛 문서는 영원히
        #   float repr 을 보여준다(재생성 말고는 고칠 길이 없다).
        row = dict(raw)
        row['min'] = _round(row.get('min'))
        row['max'] = _round(row.get('max'))
        row['avg'] = _round(row.get('avg'))
        row['delta'] = _round(row.get('delta'))
        # 저장된 것은 원문 키다 — 사람이 읽는 이름은 여기서 만든다.
        # 채널 이름 → 측정 정의 → 원문 키 순. 위 주석 참조.
        row['measurement_label'] = (
            row.get('channel_name')
            or measurement_label(row.get('measurement'), row.get('scope')))
        # ⚠ **scope 를 키에 넣는다.** 빼면 기상대의 실외 온도가 구획의 실내
        #   온도와 같은 그룹으로 접혀 하나의 평균이 된다 — 이 저장소에 이미
        #   실측으로 남은 실패(공기 온도 목표가 토양 센서와 비교된 건)와 같은
        #   모양이다.
        key = (str(row.get('measurement') or ''), str(row.get('unit') or ''),
               str(row.get('scope') or 'indoor'))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    out = []
    # 그룹 순서도 행과 같아야 한다 — 다르면 표를 접었다 폈다 할 때 줄이 튄다.
    order.sort(key=lambda k: (measurement_rank(k[0]), k[0],
                              0 if k[2] == 'indoor' else 1))
    for key in order:
        members = groups[key]
        measurement, unit, scope = key
        # 센서가 **하나면** 그 채널의 이름이 곧 그룹 이름이다 — 사용자가
        # '강우' 라고 적어 둔 것을 '길이' 로 되돌리면 자기가 적은 것을 못
        # 알아본다. 여럿이면 이름이 제각각일 수 있어 일반명을 쓴다.
        label = measurement_label(measurement, scope)
        if len(members) == 1 and members[0].get('channel_name'):
            label = members[0]['channel_name']
        entry = {'measurement': measurement, 'unit': unit, 'scope': scope,
                 'measurement_label': label,
                 'sensors': members, 'summary': None}
        if len(members) < 2:
            out.append(entry)
            continue

        mins = [r['min'] for r in members if r.get('min') is not None]
        maxs = [r['max'] for r in members if r.get('max') is not None]
        avgs = [(r['avg'], r.get('samples') or 0)
                for r in members if r.get('avg') is not None]
        circular = any(r.get('circular') for r in members)

        if not avgs:
            avg = None
        elif circular:
            # 방향의 평균은 산술평균이 아니다(`_circular_channel_stats`).
            # 센서를 가로질러 접을 때도 같은 규칙을 써야 한다 — 여기서만
            # 산술로 접으면 개별 행과 대표 줄이 서로 어긋난 값을 말한다.
            sx = sum(math.sin(math.radians(v)) * max(n, 1) for v, n in avgs)
            cx = sum(math.cos(math.radians(v)) * max(n, 1) for v, n in avgs)
            avg = (math.degrees(math.atan2(sx, cx)) % 360.0
                   if math.hypot(sx, cx) else None)
        else:
            # 표본 수로 가중한다 — 반나절만 기록된 센서와 온종일 기록된 센서를
            # 같은 무게로 세면 결측이 심한 쪽이 대표값을 끌어당긴다.
            weight = sum(max(n, 1) for _v, n in avgs)
            avg = sum(v * max(n, 1) for v, n in avgs) / weight

        targets = {r.get('target') for r in members
                   if r.get('target') is not None}
        deltas = [r['delta'] for r in members if r.get('delta') is not None]
        usages = [r['usage']['amount'] for r in members
                  if (r.get('usage') or {}).get('amount') is not None]

        entry['summary'] = {
            'sensor_count': len(members),
            # 원형 값은 min/max 가 없다 — 빈 리스트가 그대로 None 이 된다.
            'min': _round(min(mins)) if mins else None,
            'max': _round(max(maxs)) if maxs else None,
            'avg': _round(avg),
            'circular': circular,
            # 하나라도 못 미더우면 대표 줄에서 말한다 — 접었다고 경고가
            # 사라지면 접기가 사실을 가리는 장치가 된다.
            'coverage_low': any(r.get('coverage_low') for r in members),
            'target': (sorted(targets)[0] if len(targets) == 1 else None),
            'target_varies': len(targets) > 1,
            'delta_min': _round(min(deltas)) if deltas else None,
            'delta_max': _round(max(deltas)) if deltas else None,
            # 같은 이유로 대표 줄에도 남긴다(첫 행 기준 — 같은 measurement 면
            # 같은 목표를 보므로 사유도 같다).
            'delta_skipped': members[0].get('delta_skipped'),
            'follows_curve': members[0].get('follows_curve'),
            'usage': (round(sum(usages), 3) if usages else None),
        }
        out.append(entry)
    return out


# 피복 코드값 → 사람이 읽는 이름. **원문으로 두고 부를 때 번역한다** —
# 모듈 전역에서 `lazy_gettext` 를 만들면 이 파일을 import 하는 배경 스레드가
# 그 객체를 참/거짓으로 평가하는 순간 번역이 강제되고 거기서 죽는다.
COVER_LABELS = {
    'vinyl_single':      'Single-layer vinyl',
    'vinyl_double':      'Double-layer vinyl',
    'po_film':           'PO film',
    'pe_film':           'PE film',
    'polycarbonate':     'Polycarbonate',
    'glass':             'Glass',
    'non_woven_fabric':  'Non-woven fabric',
    'air_cushion':       'Air-cushion film',
}


def cover_material_label(key):
    """피복 코드값 → 사람이 읽는 이름. 모르면 코드 그대로(빈칸보다 낫다)."""
    name = COVER_LABELS.get(str(key or ''))
    return _gettext_safe(name) if name else str(key or '?')


def glossary_terms(journal_data):
    """이 문서에 **실제로 나오는** 전문용어만 → `[{'term', 'text'}, …]`.

    GDD·DLI·VPD 는 시설원예 바깥에서는 통하지 않는 말이다. 문서를 받는 쪽이
    인증기관이나 다음 사람이면 더 그렇다 — 숫자는 있는데 그 숫자가 무엇을
    세는 것인지 문서 안에 없으면 물어볼 데가 없다.

    ⚠ **안 나오는 용어를 설명하지 않는다.** 용어집을 통째로 실으면 GDD 를
      쓰지 않는 노지 일지에도 적산온도 설명이 붙는다 — 안내가 길어질수록
      읽히지 않고, 읽히지 않는 안내는 없는 것과 같다.
    """
    present = set()
    for bucket in (journal_data.get('buckets') or []):
        for row in (bucket.get('env') or []):
            m = str(row.get('measurement') or '')
            if m in ('dli', 'vapor_pressure_deficit'):
                present.add(m)
    if (journal_data.get('gdd') or {}).get('total') is not None:
        present.add('gdd')

    out = []
    if 'gdd' in present:
        out.append({'term': _gettext_safe('GDD (growing degree days)'),
                    'text': _gettext_safe(
                        "A running total of warmth. Each day adds how much "
                        "the day's average temperature sat above the "
                        "temperature this crop needs to grow at all, so a "
                        "warm day adds more than a cool one. Crops move "
                        "through their stages on accumulated warmth rather "
                        "than on the calendar, which is why a stage can "
                        "arrive early in a hot season.")})
    if 'dli' in present:
        out.append({'term': _gettext_safe('DLI (daily light integral)'),
                    'text': _gettext_safe(
                        "How much light the crop received over a whole day, "
                        "added up rather than measured at one moment. "
                        "Brightness alone does not say much — a bright but "
                        "short day and a dim but long one can come to the "
                        "same total. Measured in mol/m2/day.")})
    if 'vapor_pressure_deficit' in present:
        out.append({'term': _gettext_safe('VPD (vapour pressure deficit)'),
                    'text': _gettext_safe(
                        "How dry the air feels to the plant, in kPa. It "
                        "combines temperature and humidity, because the same "
                        "humidity is drying on a warm day and not on a cool "
                        "one. High VPD pushes the plant to transpire; too "
                        "high and it closes up and stops growing.")})
    return out


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
    if base == 'water-no-flow-basis':
        return _gettext_safe(
            "Water volume is only filled in for devices whose flow rate is "
            "known, and none here is — so this journal shows run times only. "
            "Facilities get flow from their piping layout; equipment drawn "
            "straight onto the map carries a flow rate but is not linked to "
            "the valve that opens it, so it cannot be attributed.")
    if base == 'water-estimated-map':
        return _gettext_safe(
            "Water volumes are estimated from the sprinklers drawn on the "
            "map inside the area each valve covers, and how long that valve "
            "ran — not measured by a flow meter. Only the part that overlaps "
            "this plot is counted, so no share is guessed.")
    if base == 'water-estimated':
        return _gettext_safe(
            "Water volumes are estimated from the designed nozzle flow and "
            "run time, and split by the plot's share of the bay — not "
            "measured by a flow meter.")
    if base == 'dli-estimated':
        return _gettext_safe(
            "Daily light integral is estimated from solar radiation "
            "(W/m2), assuming sunlight. A PAR sensor would measure it "
            "directly.")
    if base == 'dli-outdoor':
        return _gettext_safe(
            "Light is measured outdoors, so the daily light integral is "
            "what reached the site — not what reached the crop under "
            "cover or supplemental lighting.")
    if base == 'dli-through-cover':
        material, _, tau = suffix.partition(':')
        return _gettext_safe(
            "Light is measured outdoors, so the daily light integral shown "
            "is what got through the cover: the outdoor figure multiplied "
            "by %(tau)s for %(material)s. The cover's material is used; its "
            "thickness, age and dust are not, so the real figure is usually "
            "a little lower.") % {
                'tau': tau or '?', 'material': cover_material_label(material)}
    if base == 'dli-shade-not-counted':
        return _gettext_safe(
            "This facility has a shade screen. Whether it was drawn on any "
            "given day is not recorded, so it is not counted — on days it "
            "was drawn, the crop got less light than shown.")
    if base == 'measurements-excluded':
        names = [measurement_label(k) for k in suffix.split(',') if k]
        return _gettext_safe(
            "Device diagnostics were left out of this journal: %(names)s."
        ) % {'names': ' · '.join(str(n) for n in names)}
    if base == 'stored-weekly-too-large':
        return _gettext_safe(
            "This period was too large to store day by day, so it was saved "
            "in weekly buckets — daily detail is not available for it.")
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


def render_plot_journal_markdown(journal_data, granularity=None):
    """§6 계약 dict → Markdown 문자열(CommonMark 파이프 테이블).

    HTML(§10)과 같은 구조를 따른다: 캐비어트 → 개요 → 단계별 요약(plot만)
    → 버킷 루프(환경/제어/노트). 사진은 `/note_attachment/<filename>` 절대
    URL 링크로 낸다 — 서버가 살아있는 동안만 유효하다는 사실을 문구로 밝힌다.

    `granularity` 를 주면 그 단위로 접어서 낸다(HTML 의 단위 전환과 같은
    `fold_buckets`) — 화면에서 월간으로 보다가 내려받았는데 파일만 일간이면
    같은 문서의 두 판본이 생긴다.
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

    # ── 용어 ─────────────────────────────────────────────────────────────
    # HTML 은 안내 페이지에서 설명하는데, 내보낸 문서를 받는 쪽에는 그 페이지가
    # 없다 — 여기 없으면 GDD·DLI 가 설명 없는 숫자로만 건너간다.
    _terms = glossary_terms(journal_data)
    if _terms:
        lines.append('## Terms used here')
        lines.append('')
        for g in _terms:
            lines.append('- **%s** — %s' % (g['term'], g['text']))
        lines.append('')

    # ── 개요 ─────────────────────────────────────────────────────────────
    lines.append('## Overview')
    lines.append('')
    lines.append('| | |')
    lines.append('|---|---|')
    lines.append('| Type | %s |' % _md_escape(
        _target_kind_label(t.get('type'), t.get('kind'))))
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
    # 단계 절 — HTML(§10)과 **같은 것**을 낸다. 예전에는 여기도 계획표만
    # 옮겨 놓아, 기간과 상관없는 미래 단계까지 전부 실리고 정작 그 기간에
    # 무슨 일이 있었는지는 없었다. 두 출력이 다른 내용을 내면 같은 문서가
    # 아니게 되므로 같은 `stage_sections()` 를 쓴다.
    sections = stage_sections(journal_data)
    if sections:
        lines.append('## Program stages')
        lines.append('')
        for sec in sections:
            st = sec['stage']
            if not sec['in_period']:
                # 기간 밖(계획) — 있다는 것만 한 줄로.
                lines.append('- %s (%s – %s) — planned' % (
                    _md_escape(st.get('name') or st.get('key')),
                    st.get('starts_on') or '—', st.get('ends_on') or 'ongoing'))
                continue
            lines.append('### %s (%s – %s)' % (
                _md_escape(st.get('name') or st.get('key')),
                sec['starts_on'], sec['ends_on']))
            lines.append('')
            if st.get('guidance'):
                lines.append(_md_escape(st['guidance']))
                lines.append('')

            if sec['env_groups']:
                lines.append('| Sensor | Measurement | Min | Max | Avg | Target |')
                lines.append('|---|---|---|---|---|---|')
                for grp in sec['env_groups']:
                    row = grp.get('summary') or grp['sensors'][0]
                    who = ('%d sensors' % grp['summary']['sensor_count']
                           if grp.get('summary') else grp['sensors'][0].get('sensor'))
                    target = (('curve: %s' % row['follows_curve'])
                              if row.get('follows_curve')
                              else (row.get('target') if row.get('target') is not None else ''))
                    lines.append('| %s | %s | %s | %s | %s | %s |' % (
                        _md_escape(who),
                        _md_escape(grp.get('measurement_label') or grp.get('measurement')),
                        _md_escape(row.get('min')), _md_escape(row.get('max')),
                        _md_escape(row.get('avg')), _md_escape(target)))
                lines.append('')

            missing = [t.get('label') for t in (st.get('targets') or [])
                       if t.get('observable') is False]
            if missing:
                lines.append('_No sensor for: %s_' % _md_escape(' · '.join(
                    str(m) for m in missing)))
                lines.append('')

            if sec['control']:
                lines.append('| Device | Runtime (h) |')
                lines.append('|---|---|')
                for c in sec['control']:
                    lines.append('| %s | %s |' % (_md_escape(c.get('name')),
                                                  _md_escape(c.get('hours'))))
                lines.append('')

            for n in sec['notes']:
                time_str = (n.get('time') or '')[:16].replace('T', ' ')
                head = ('**%s**' % time_str) if time_str else ''
                if n.get('title'):
                    head += (' ' if head else '') + n['title']
                body = n.get('body') or ''
                lines.append('- %s%s' % (head, (' — ' + body) if head and body else body))
            for photo in sec['photos']:
                lines.append('  ![](%s)' % _note_attachment_url(photo['file']))
            if sec['notes'] or sec['photos']:
                lines.append('')

    # ── 버킷 루프 ────────────────────────────────────────────────────────
    #
    # 목표·Δ 는 plot 에서만 값을 가진다(대지·구역은 프로그램이 없다) — HTML
    # 과 같은 판정으로 열을 뺀다. 두 출력이 다른 표를 내면 같은 문서가 아니다.
    show_target = (t.get('type') == 'plot')
    stored = journal_data.get('granularity') or 'day'
    buckets = fold_buckets(journal_data.get('buckets') or [],
                           to=(granularity or stored), granularity=stored)

    lines.append('## Log')
    lines.append('')
    for b in buckets:
        lines.append('### %s' % b.get('date_label'))
        lines.append('')
        if b.get('empty'):
            gaps = b.get('gap_count') or 1
            lines.append('_No data recorded%s._'
                         % ((' — %d periods skipped' % gaps) if gaps > 1 else
                            ' for this period'))
            lines.append('')
            continue

        env = b.get('env') or []
        if env:
            if show_target:
                lines.append('| Sensor | Measurement | Min | Max | Avg | Target | Δ |')
                lines.append('|---|---|---|---|---|---|---|')
            else:
                lines.append('| Sensor | Measurement | Min | Max | Avg |')
                lines.append('|---|---|---|---|---|')
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
                label = measurement_label(e.get('measurement'), e.get('scope'))
                if show_target:
                    lines.append('| %s | %s%s | %s | %s | %s | %s | %s |' % (
                        _md_escape(e.get('sensor')), _md_escape(label),
                        usage_suffix, _md_escape(e.get('min')), _md_escape(e.get('max')),
                        _md_escape(avg_cell), _md_escape(target_cell),
                        _md_escape(_md_delta_value(e))))
                else:
                    lines.append('| %s | %s%s | %s | %s | %s |' % (
                        _md_escape(e.get('sensor')), _md_escape(label),
                        usage_suffix, _md_escape(e.get('min')), _md_escape(e.get('max')),
                        _md_escape(avg_cell)))
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


def estimate_journal_cost(target_type, target_id, start_date, end_date,
                          measurements=None):
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

    env_channels, circular_channels = count_channels_detail(sensor_ids,
                                                            measurements)
    control_channels = len([a for a in actuators if a.get('output_id')])
    # 원형 채널은 집계 3회가 아니라 **원자료 조회 1회**다(`_circular_channel_stats`).
    queries = ((env_channels - circular_channels) * 3 + circular_channels
               + control_channels)
    rows = _rows_for(env_channels, circular_channels, control_channels, days)

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


def _run_journal_build(app, journal_uuid, measurements=None,
                       granularity=None):
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
                        row.period_start, row.period_end,
                        measurements=measurements, granularity=granularity)

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


def start_journal_build(journal_uuid, measurements=None, granularity=None):
    """요청 스레드에서 부른다 — 앱 객체를 잡아 백그라운드로 넘긴다.

    `current_app` 은 요청 컨텍스트에 매여 있어 스레드로 그대로 넘기면 안 된다
    (선례가 `_get_current_object()` 를 쓰는 이유).

    `measurements`(고른 측정값)는 **행에 저장하지 않고 클로저로 넘긴다.**
    스레드가 같은 프로세스 안에서 돌기 때문이고, 새 컬럼과 마이그레이션을
    만들 이유가 없다. 재시작으로 중단된 빌드는 재시도하지 않고 `error` 로
    회수되므로(§13d) 나중에 다시 읽을 일도 없다. **무엇을 실었는가는 완성된
    스냅샷(`data['measurements']`)에 남는다** — 그쪽이 문서의 기록이다.
    """
    from flask import current_app

    _run_journal_build(current_app._get_current_object(), journal_uuid,
                       measurements=measurements, granularity=granularity)


# ── 내보내기: 열린 형식 ──────────────────────────────────────────────────
#
# HTML(화면·인쇄)·Markdown·JSON 에 더해 **표 계산용 CSV** 와 **편집 가능한
# 개방 문서 ODT** 를 낸다.
#
# ⚠ **서버에서 PDF 를 만들지 않는다.** `reportlab` 이 이미 의존성에 있지만,
#   PDF 는 브라우저 인쇄 경로가 이미 담당한다(§10 의 `@media print`). 서버에
#   두 번째 레이아웃을 두면 같은 문서가 경로마다 달라지고, 그 차이는 인쇄해
#   보기 전까지 아무도 모른다 — 이 저장소가 반복해서 겪은 모양이다.

def render_plot_journal_csv(journal_data, granularity=None):
    """§6 계약 dict → CSV 문자열(표 계산·통계용).

    한 줄이 **한 버킷의 한 측정값**이다. 가동시간도 같은 표에 `kind='runtime'`
    으로 넣는다 — 파일을 둘로 나누면 사람이 둘을 맞춰 보아야 하고, 그 맞춤은
    대개 안 된다.

    ⚠ 헤더를 번역하지 않는다. CSV 는 사람이 읽는 문서가 아니라 **다른 도구가
      읽는 자료**라, 열 이름이 로케일마다 바뀌면 그 도구의 수식이 깨진다.
      값 쪽의 이름(센서·측정값)은 저장된 원문 키를 쓴다.
    """
    import csv
    import io as _io

    stored = (journal_data or {}).get('granularity') or 'day'
    buckets = fold_buckets((journal_data or {}).get('buckets') or [],
                           to=(granularity or stored), granularity=stored)
    target = (journal_data or {}).get('target') or {}

    out = _io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        'period', 'kind', 'scope', 'device', 'measurement', 'unit',
        'min', 'max', 'avg', 'target', 'delta', 'samples', 'expected',
        'coverage', 'usage',
    ])
    for bucket in buckets:
        label = bucket.get('date_label')
        for row in (bucket.get('env') or []):
            usage = (row.get('usage') or {}).get('amount')
            writer.writerow([
                label, 'env', row.get('scope') or 'indoor',
                row.get('sensor'), row.get('measurement'), row.get('unit'),
                row.get('min'), row.get('max'), row.get('avg'),
                row.get('target'), row.get('delta'),
                row.get('samples'), row.get('expected'), row.get('coverage'),
                usage,
            ])
        for row in (bucket.get('control') or []):
            writer.writerow([
                label, 'runtime', 'indoor', row.get('name'),
                'runtime', 'h', '', '', row.get('hours'),
                '', '', '', '', '', '',
            ][:15])
        for note in (bucket.get('notes') or []):
            writer.writerow([
                label, 'note', '', note.get('title') or '',
                (note.get('body') or '').replace('\n', ' '),
                '', '', '', '', '', '', '', '', '', '',
            ])
    # 대상 정보는 맨 뒤에 한 줄 — 파일만 받아도 무엇에 대한 자료인지 안다.
    writer.writerow([])
    writer.writerow(['# target', target.get('type'), target.get('name'),
                     (target.get('period') or {}).get('start'),
                     (target.get('period') or {}).get('end'),
                     target.get('tz_name')])
    return out.getvalue()


#: ODT 안에 넣는 고정 파일들. `.odt` 는 **ZIP 안의 XML** 이라 새 의존성 없이
#: 표준 라이브러리만으로 만들 수 있다(ISO/IEC 26300 · OpenDocument).
_ODT_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
 <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>
 <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
 <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""

_ODT_STYLES = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
 office:version="1.2">
 <office:styles>
  <style:style style:name="Title" style:family="paragraph">
   <style:text-properties fo:font-size="24pt" fo:font-weight="bold"/>
   <style:paragraph-properties fo:margin-bottom="0.4cm"/>
  </style:style>
  <style:style style:name="Heading_20_1" style:display-name="Heading 1" style:family="paragraph">
   <style:text-properties fo:font-size="15pt" fo:font-weight="bold"/>
   <style:paragraph-properties fo:margin-top="0.6cm" fo:margin-bottom="0.2cm"/>
  </style:style>
  <style:style style:name="Heading_20_2" style:display-name="Heading 2" style:family="paragraph">
   <style:text-properties fo:font-size="12pt" fo:font-weight="bold"/>
   <style:paragraph-properties fo:margin-top="0.4cm" fo:margin-bottom="0.15cm"/>
  </style:style>
  <style:style style:name="Muted" style:family="paragraph">
   <style:text-properties fo:font-size="9pt" fo:color="#666666"/>
  </style:style>
 </office:styles>
</office:document-styles>
"""


def _odt_esc(value):
    """ODT 본문에 넣을 문자열 — XML 특수문자를 막는다.

    ⚠ 이스케이프를 빠뜨리면 작물 이름의 `&` 하나로 **파일이 통째로 안 열린다**
      (ZIP 은 멀쩡한데 XML 파서가 죽는다). 실패가 "문서가 손상됨" 으로만
      보여서 원인에 닿기 어렵다.
    """
    from xml.sax.saxutils import escape
    return escape('' if value is None else str(value))


def _odt_p(text, style=None):
    style_attr = (' text:style-name="%s"' % style) if style else ''
    return '<text:p%s>%s</text:p>' % (style_attr, _odt_esc(text))


def _odt_table(name, header, rows):
    """머리글 + 행 목록 → ODT 표 XML."""
    cols = len(header)
    out = ['<table:table table:name="%s">' % _odt_esc(name),
           '<table:table-column table:number-columns-repeated="%d"/>' % cols]

    def _row(cells, bold=False):
        parts = ['<table:table-row>']
        for cell in cells:
            parts.append('<table:table-cell office:value-type="string">')
            parts.append(_odt_p(cell, 'Heading_20_2' if bold else None))
            parts.append('</table:table-cell>')
        parts.append('</table:table-row>')
        return ''.join(parts)

    out.append(_row(header, bold=True))
    for row in rows:
        # 열 수를 머리글에 맞춘다 — 짧으면 뒤가 밀리고 길면 파서가 거부한다.
        cells = list(row)[:cols] + [''] * max(0, cols - len(row))
        out.append(_row(cells))
    out.append('</table:table>')
    return ''.join(out)


def render_plot_journal_odt(journal_data, granularity=None):
    """§6 계약 dict → ODT 바이트(OpenDocument Text).

    ## 왜 ODT 인가

    HTML 은 화면, PDF 는 고정본, Markdown 은 옮겨 적기, JSON 은 기계용이다.
    빠진 것은 **받는 사람이 이어서 쓰는 문서**다 — 인증기관이 소견을 덧붙이고
    다음 담당자가 메모를 남기는 자리. ODT 는 ISO/IEC 26300 표준이고
    LibreOffice·Word·Google Docs 가 모두 연다.

    ⚠ **새 의존성을 만들지 않는다.** `.odt` 는 ZIP 안의 XML 이라 표준
      라이브러리(`zipfile`)만으로 만든다. 문서 생성 라이브러리를 하나 더
      들이면 저사양 배포의 설치 목록이 그만큼 길어지고, 그 설치가 깨지면
      일지 전체가 안 나온다.

    ⚠ `mimetype` 은 **첫 항목**이고 **압축하지 않아야** 한다(ODF 규격). 이걸
      어기면 일부 프로그램이 파일 종류를 못 알아본다 — 열리는 데도 있어서
      테스트를 한 곳에서만 하면 통과한다.
    """
    import io as _io
    import zipfile

    stored = (journal_data or {}).get('granularity') or 'day'
    view = granularity or stored
    buckets = fold_buckets((journal_data or {}).get('buckets') or [],
                           to=view, granularity=stored)
    t = (journal_data or {}).get('target') or {}
    period = t.get('period') or {}

    body = []
    body.append(_odt_p(t.get('name') or t.get('unique_id') or 'Journal', 'Title'))
    body.append(_odt_p('%s – %s' % (period.get('start'), period.get('end'))))

    # ── 개요 ────────────────────────────────────────────────────────────
    body.append(_odt_p('Overview', 'Heading_20_1'))
    overview = [('Type', _target_kind_label(t.get('type'), t.get('kind')))]
    if t.get('subject'):
        item = t['subject'] + ((' — %s' % t['variety']) if t.get('variety') else '')
        overview.append(('Item', item))
    loc = t.get('location') or {}
    where = ' · '.join([v for v in (loc.get('zone_name'), loc.get('facility_name'),
                                    loc.get('bay_name')) if v])
    if where:
        overview.append(('Location', where))
    if t.get('program'):
        overview.append(('Program', t['program'].get('name')))
    if t.get('area_m2') is not None:
        overview.append(('Area', '%.1f m2' % t['area_m2']))
    overview.append(('Time zone', t.get('tz_name')))
    body.append(_odt_table('overview', ['', ''], overview))

    # ── 단계 ────────────────────────────────────────────────────────────
    for sec in stage_sections(journal_data):
        st = sec['stage']
        head = '%s (%s – %s)%s' % (
            st.get('name') or st.get('key'),
            sec['starts_on'] or st.get('starts_on') or '—',
            sec['ends_on'] or st.get('ends_on') or 'ongoing',
            '' if sec['in_period'] else ' · planned')
        body.append(_odt_p(head, 'Heading_20_1'))
        if st.get('guidance'):
            body.append(_odt_p(st['guidance']))
        if sec['in_period'] and sec['env_groups']:
            rows = []
            for grp in sec['env_groups']:
                row = grp.get('summary') or grp['sensors'][0]
                who = ('%d sensors' % grp['summary']['sensor_count']
                       if grp.get('summary') else grp['sensors'][0].get('sensor'))
                rows.append([who,
                             grp.get('measurement_label') or grp.get('measurement'),
                             row.get('min'), row.get('max'), row.get('avg')])
            body.append(_odt_table('stage-env',
                                   ['Sensor', 'Measurement', 'Min', 'Max', 'Avg'],
                                   rows))
        elif st.get('targets'):
            rows = [[tg.get('label'), _md_target_value(tg)]
                    for tg in st['targets']]
            body.append(_odt_table('stage-targets', ['Target', 'Value'], rows))
        for note in sec.get('notes') or []:
            body.append(_odt_p('%s  %s %s' % (
                (note.get('time') or '')[:16].replace('T', ' '),
                note.get('title') or '', note.get('body') or ''), 'Muted'))

    # ── 일자별 기록 ─────────────────────────────────────────────────────
    body.append(_odt_p('Log', 'Heading_20_1'))
    for bucket in buckets:
        body.append(_odt_p(bucket.get('date_label'), 'Heading_20_2'))
        if bucket.get('empty'):
            gaps = bucket.get('gap_count') or 1
            body.append(_odt_p(
                'No data recorded%s.'
                % ((' — %d periods skipped' % gaps) if gaps > 1 else ''), 'Muted'))
            continue
        env = bucket.get('env') or []
        if env:
            rows = [[e.get('sensor'),
                     measurement_label(e.get('measurement'), e.get('scope')),
                     e.get('min'), e.get('max'), e.get('avg'),
                     e.get('target'), e.get('delta')] for e in env]
            body.append(_odt_table(
                'env', ['Sensor', 'Measurement', 'Min', 'Max', 'Avg',
                        'Target', 'Delta'], rows))
        control = bucket.get('control') or []
        if control:
            body.append(_odt_table(
                'runtime', ['Device', 'Runtime (h)'],
                [[c.get('name'), c.get('hours')] for c in control]))
        for note in (bucket.get('notes') or []):
            body.append(_odt_p('%s  %s %s' % (
                (note.get('time') or '')[:16].replace('T', ' '),
                note.get('title') or '', note.get('body') or ''), 'Muted'))

    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content'
        ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
        ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
        ' office:version="1.2">'
        '<office:body><office:text>%s</office:text></office:body>'
        '</office:document-content>' % ''.join(body))

    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        # ⚠ 첫 항목 · 무압축(ODF 규격). 순서를 바꾸면 파일 종류 판별이 깨진다.
        z.writestr(zipfile.ZipInfo('mimetype'),
                   'application/vnd.oasis.opendocument.text',
                   compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/manifest.xml', _ODT_MANIFEST)
        z.writestr('styles.xml', _ODT_STYLES)
        z.writestr('content.xml', content)
    return buf.getvalue()


# ── 관수량 ───────────────────────────────────────────────────────────────

def _open_field_flow(plot):
    """노지 구획 → `{output_id: {'lph', 'share', 'source'}}`.

    ## 밸브는 자기가 맡은 구역을 **이미 알고 있다**

    지도에 놓인 출력은 `GeoShape(type='device')` — **담당 폴리곤**을 갖는다
    (`device_binding.SHAPE_TYPE_ROLES` 의 `'area'`). "이 밸브가 어디에 물을
    주는가" 는 그 도형이 답한다. 노즐 임자를 정하려고 별도의 지정을 만들
    이유가 없다 — 담당 폴리곤 안에 있는 노즐이 그 밸브 것이다.

    ⚠ **두 번째 판정자를 만들지 말 것.** 한때 구역 도형에 밸브를 매는 별도
      지정을 만들었다가 걷어냈다. 담당 폴리곤이 이미 있는데 구역 단위로
      묶었더니 **틀린 값**이 나왔다 — 나주 배밭은 v11·v12 가 각각 절반
      (510,000 / 512,900 L/h)을 맡는데, 구역으로 묶으면 2,205개가 통째로
      한 밸브에 얹혀 918,750 L/h 가 됐다.

    ## 몫으로 나누지 않는다 — 구획과 겹치는 만큼만 센다

    노지 구획은 폴리곤을 갖는다. **담당 폴리곤 ∩ 구획** 안의 노즐만 세면
    "그 밸브의 물 중 이 구획에 떨어진 몫" 이 곧 나온다 — 면적 비율로 어림할
    필요가 없다(구획 한쪽에 노즐이 몰린 배치가 흔하다).
    """
    from aot.aot_flask.geo import device_binding
    from aot.databases.models import GeoShape

    feature = getattr(plot, 'feature', None) or {}
    geom = feature.get('geometry') or {}
    if not geom:
        return {}
    try:
        from shapely.geometry import shape as _shape
        poly = _shape(geom)
        if poly.is_empty:
            return {}
    except Exception:
        logger.exception('journal: 구획 기하 해석 실패')
        return {}

    # 이 구획을 맡는 출력들 — 일지가 가동시간을 내는 것과 **같은 목록**이다.
    # 여기서 따로 찾으면 두 목록이 갈라져, 표에 있는 장치의 물량이 비거나
    # 없는 장치의 물량이 생긴다.
    try:
        actuators, _unassigned = plot_context.actuators_for_plot(plot)
    except Exception:
        logger.exception('journal: 구획 액추에이터 조회 실패')
        return {}
    output_ids = [a.get('output_id') for a in actuators if a.get('output_id')]
    if not output_ids:
        return {}

    sprinklers = _map_sprinklers(getattr(plot, 'geo_id', None)
                                 or _map_of_plot(plot))
    if not sprinklers:
        return {}

    out = {}
    for oid in output_ids:
        region = None
        for sh in _device_area_shapes(oid):
            try:
                area = _shape((sh.feature or {}).get('geometry') or {})
            except Exception:
                continue
            if area.is_empty:
                continue
            # 한 밸브가 담당 도형을 여럿 가질 수 있다(구역이 나뉜 배치).
            # 합집합으로 모아야 겹치는 노즐을 두 번 세지 않는다.
            region = area if region is None else region.union(area)
        if region is None:
            continue
        region = region.intersection(poly)
        if region.is_empty:
            continue
        lph = sum(flow for pt, flow in sprinklers if region.contains(pt))
        if lph > 0:
            out[oid] = {'lph': round(lph, 1), 'share': 1.0,
                        'source': 'map-equipment'}
    return out


def _device_area_shapes(output_id):
    """출력이 맡는 **담당 폴리곤** 도형들 → [GeoShape].

    마커(`aot_device`, 점)는 뺀다 — 위치일 뿐 담당 구역이 아니다.
    """
    from aot.aot_flask.geo import device_binding
    from aot.databases.models import GeoShape

    out = []
    try:
        found = device_binding.shapes_for_device(output_id) or []
    except Exception:
        logger.exception('journal: 담당 도형 조회 실패 (%s)', output_id)
        return out
    for item in found:
        row = item
        if not hasattr(row, 'feature'):
            row = GeoShape.query.filter_by(unique_id=str(item)).first()
        if row is None or row.type != 'device':
            continue
        out.append(row)
    return out


def _map_sprinklers(map_uuid):
    """지도의 스프링클러 → `[(Point, L/h)]`. 유량이 0 인 것은 빼고 낸다.

    노지 관수 장비는 지도에 직접 그린다 —
    `GeoShape(type='equipment_collection')` 안의 `sub_type='sprinkler'` 가
    각자 `flow`(L/h)를 들고 있다.
    """
    from aot.databases.models import GeoShape

    q = GeoShape.query.filter_by(type='equipment_collection')
    if map_uuid:
        q = q.filter(GeoShape.geo_id == map_uuid)
    out = []
    for coll in q.all():
        for f in ((coll.feature or {}).get('features') or []):
            pr = f.get('properties') or {}
            if pr.get('sub_type') != 'sprinkler':
                continue
            try:
                flow = float(pr.get('flow') or 0)
            except (TypeError, ValueError):
                continue
            if flow <= 0:
                continue
            pt = _sprinkler_point(f, pr)
            if pt is not None:
                out.append((pt, flow))
    return out


def _sprinkler_point(feature, props):
    """스프링클러 하나의 위치 → shapely Point. 못 얻으면 None.

    그리기 도구가 원(circle)으로 저장한 것은 기하가 아니라
    `center_lat`/`center_lng` 에 중심을 둔다 — 그것을 먼저 본다.
    """
    from shapely.geometry import Point, shape as _shape
    try:
        if props.get('center_lat') is not None:
            return Point(float(props['center_lng']), float(props['center_lat']))
        geom = feature.get('geometry') or {}
        if geom.get('type') == 'Point':
            return Point(*geom['coordinates'][:2])
        if geom:
            return _shape(geom).centroid
    except Exception:
        return None
    return None


def _map_of_plot(plot):
    """구획이 놓인 지도 uuid → str 또는 None.

    구획은 지도를 직접 들지 않는다 — 감싸는 도형이 든다.
    """
    from aot.databases.models import GeoShape
    uid = getattr(plot, 'zone_uuid', None)
    if not uid:
        return None
    row = GeoShape.query.filter_by(unique_id=uid).first()
    return row.geo_id if row is not None else None


def irrigation_flow_for_plot(plot):
    """구획 → `{output_id: {'lph', 'share', 'source'}}`.

    ## 왜 설계 유량으로 추정하는가

    유량계(`measurement='volume'`)가 있으면 그 실측이 이긴다 — 이미
    `usage_from_stats()` 가 낸다. 그런데 **대부분의 밸브에는 유량계가 없다.**
    그렇다고 가동시간만 내놓으면 "물을 얼마나 줬나" 라는 농사의 기본 질문에
    이 문서가 답하지 못한다.

    시설 설계도가 그 답을 이미 갖고 있다. `irrigation_nozzles.nozzles_by_actuator()`
    가 **배관 물길로** 밸브별 노즐을 갈라(노즐 하나는 정확히 한 액추에이터에만
    속한다) 시간당 토출량(`total_flow_lph`)을 낸다. 가동시간을 곱하면 물량이다.

    ## 몫으로 나눈다

    시설 구획이 동의 일부만 차지하면(`allocation`) 그 밸브의 물이 전부 이
    구획 것이 아니다. 구획의 몫만큼 나누고 **그 사실을 표시한다**(`share`).
    구획이 자기 기하를 갖지 않는 것이 시설 구획의 정상이라, "구획 안 노즐만
    센다" 는 애초에 성립하지 않는다.

    ⚠ 이것은 **추정치다.** 노즐이 설계대로 달려 있고 막히지 않았다는 전제 위에
      서 있다 — 화면이 실측과 구분해 말해야 한다.
    """
    from aot.aot_flask.geo import irrigation_nozzles
    from aot.databases.models import GeoFacility

    facility_uuid = getattr(plot, 'facility_uuid', None)
    if not facility_uuid:
        # 노지 — 배관 도면은 없지만 지도에 그린 스프링클러가 유량을 갖고 있다.
        return _open_field_flow(plot)
    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if facility is None:
        return {}

    try:
        by_actuator = irrigation_nozzles.nozzles_by_actuator(
            facility.fittings or [])
    except Exception:
        logger.exception('journal: 노즐 유량 조회 실패 (%s)', facility_uuid)
        return {}
    if not by_actuator:
        return {}

    share = _allocation_share(plot)
    out = {}
    for output_id, summary in by_actuator.items():
        lph = summary.get('total_flow_lph')
        if not output_id or not lph:
            continue
        out[output_id] = {'lph': float(lph), 'share': share, 'source': 'design'}
    return out


def _allocation_share(plot):
    """구획이 그 동에서 차지하는 몫(0~1). 모르면 1.0.

    ⚠ **비율을 직접 계산하지 않는다.** 저장된 것은 `{"amount": 4}` 같은 절대
      값이고 비율은 동의 총량에서 **파생**한다 — `plot_context.allocation_view()`
      가 그 정본이다. 여기서 다시 나누면 총량이 바뀔 때 두 값이 조용히 갈린다
      (그 함수가 비율을 저장하지 않는 이유가 정확히 그것이다).

    ⚠ **모를 때 1.0 이다.** 0 으로 두면 물량이 통째로 0 이 되어 "관수를 안
      했다" 로 읽히는데, 실제로는 몫을 안 적었을 뿐이다.
    """
    facility_uuid = getattr(plot, 'facility_uuid', None)
    if not facility_uuid:
        return 1.0
    try:
        brief = plot_context.facility_brief(facility_uuid)
        view = plot_context.allocation_view(
            getattr(plot, 'allocation', None),
            (brief.get('bay_capacities') or {}).get(
                getattr(plot, 'bay_id', None)))
    except Exception:
        logger.exception('journal: 몫 산출 실패')
        return 1.0
    if not view or view.get('percent') in (None, ''):
        return 1.0
    try:
        pct = float(view['percent'])
    except (TypeError, ValueError):
        return 1.0
    return pct / 100.0 if 0.0 < pct <= 100.0 else 1.0
