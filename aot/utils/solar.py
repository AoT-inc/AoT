"""
solar — AoT 태양시(일출·일몰·박명·남중·태양고도) 단일 커널.

설계 배경: 일출/일몰은 지금까지 트리거 한 종류(trigger_sunrise_sunset)의
전용 계산이었다. 이 모듈은 그것을 시스템 전반(Function·Output·조건·예약·AI)이
공유하는 하나의 기본값으로 끌어올린다.

규약 (docs/design/timezone-management.md 와 동일):
  - 반환되는 모든 시각은 UTC-aware datetime. 표시 변환은 호출부에서
    timekit.to_tz(dt, resolve_tz(...)) 로 한다.
  - "그 날"의 경계는 UTC 가 아니라 **위치의 현지 날짜**다. astral 에 현지 tz 를
    넘겨 계산한 뒤 UTC 로 되돌린다(UTC 날짜로 계산하면 일출/일몰이 서로 다른
    현지 날짜에 걸쳐 어긋난다).
  - 좌표는 새 컬럼을 만들지 않고 timekit.resolve_coords 체인을 그대로 쓴다:
    도형(사이트/구역) → 소속 도형 상속 → 엔티티 자신의 좌표 → 농장 지도 중심.
    즉 엔티티는 기본적으로 자기가 속한 도형의 태양시를 상속한다.
  - 극야/백야는 예외가 아니라 status 로 반환한다(always_day / always_night).
    "항상 낮"을 어떻게 다룰지는 호출부(작물·설비 로직)가 결정한다.

daemon(컨트롤러)과 Flask 양쪽에서 그대로 쓸 수 있다 — DB 접근은 전부
timekit 경유(db_retrieve_table_daemon)이고, 계산 자체는 순수 함수다.
"""
import logging
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pytz

from aot.utils.timekit import as_tz, ensure_utc, resolve_coords, system_tz, utc_now

logger = logging.getLogger(__name__)

# 태양 상태 — 극지에서 일출/일몰이 존재하지 않는 날의 표현.
STATUS_NORMAL = 'normal'
STATUS_ALWAYS_DAY = 'always_day'      # 백야: 하루 종일 지평선 위
STATUS_ALWAYS_NIGHT = 'always_night'  # 극야: 하루 종일 지평선 아래
STATUS_UNKNOWN = 'unknown'            # 좌표 미해석 등 계산 불가

# 이벤트 종류 — next_sun_event(kind=...) 인자.
EVENT_SUNRISE = 'sunrise'
EVENT_SUNSET = 'sunset'
EVENT_SOLAR_NOON = 'solar_noon'
EVENT_CIVIL_DAWN = 'civil_dawn'    # 시민박명 시작(일출 전, 태양고도 -6°)
EVENT_CIVIL_DUSK = 'civil_dusk'    # 시민박명 끝(일몰 후, 태양고도 -6°)

SUN_EVENTS = (EVENT_SUNRISE, EVENT_SUNSET, EVENT_SOLAR_NOON,
              EVENT_CIVIL_DAWN, EVENT_CIVIL_DUSK)

# 하루치 계산 캐시 — 키는 (위도4, 경도4, tz명, 현지날짜).
# 같은 위치·같은 날은 몇 번을 물어도 한 번만 계산한다.
_CACHE_MAX = 512
_cache: "OrderedDict[tuple, SunTimes]" = OrderedDict()
_cache_lock = threading.Lock()

# next_sun_event 가 앞으로 훑는 최대 일수(극지에서 이벤트가 없는 날 대비).
_SEARCH_DAYS = 4


@dataclass(frozen=True)
class SunTimes:
    """한 위치의 하루치 태양시. 모든 datetime 은 UTC-aware(없으면 None)."""
    local_date: date_cls
    tz_name: str
    latitude: float
    longitude: float
    status: str
    sunrise: Optional[datetime] = None
    sunset: Optional[datetime] = None
    solar_noon: Optional[datetime] = None
    civil_dawn: Optional[datetime] = None
    civil_dusk: Optional[datetime] = None

    @property
    def day_length_seconds(self) -> Optional[float]:
        """일출~일몰 길이(초). 백야=86400, 극야=0, 계산 불가=None."""
        if self.status == STATUS_ALWAYS_DAY:
            return 86400.0
        if self.status == STATUS_ALWAYS_NIGHT:
            return 0.0
        if self.sunrise and self.sunset:
            return (self.sunset - self.sunrise).total_seconds()
        return None

    def event(self, kind: str) -> Optional[datetime]:
        """이벤트 이름으로 시각 조회. 알 수 없는 이름은 None."""
        return getattr(self, kind, None) if kind in SUN_EVENTS else None


def _astral_observer(latitude: float, longitude: float):
    from astral import Observer
    return Observer(latitude=latitude, longitude=longitude)


def _classify_polar(exc: Exception) -> str:
    """astral 의 '해가 뜨지/지지 않음' ValueError 를 status 로 분류."""
    msg = str(exc).lower()
    if 'always above' in msg:
        return STATUS_ALWAYS_DAY
    if 'always below' in msg:
        return STATUS_ALWAYS_NIGHT
    return STATUS_UNKNOWN


def _resolve_location(target_id=None, entity=None,
                      latitude=None, longitude=None) -> Tuple[Optional[float], Optional[float]]:
    """명시 좌표가 있으면 그대로, 없으면 timekit 상속 체인으로 해석."""
    if latitude is not None and longitude is not None:
        try:
            return float(latitude), float(longitude)
        except (TypeError, ValueError):
            pass
    lat, lon, _source = resolve_coords(entity, target_id=target_id)
    return lat, lon


def _tz_for(latitude: float, longitude: float) -> pytz.BaseTzInfo:
    """좌표의 IANA tz. 해석 실패 시 농장 전역 tz(Misc.timezone) 폴백."""
    try:
        from aot.utils.device_tz import resolve_tz_from_coords
        name = resolve_tz_from_coords(latitude, longitude)
        if name:
            return as_tz(name)
    except Exception:
        pass
    return system_tz()


def sun_times(target_id=None, entity=None, date=None,
              latitude=None, longitude=None) -> Optional[SunTimes]:
    """한 위치의 하루치 태양시를 반환. 좌표를 못 구하면 None.

    date 는 **그 위치의 현지 날짜**(datetime.date). 생략하면 현지 오늘.
    """
    lat, lon = _resolve_location(target_id, entity, latitude, longitude)
    if lat is None or lon is None:
        logger.debug("sun_times: 좌표를 해석할 수 없습니다 (target_id=%s)", target_id)
        return None

    tzinfo = _tz_for(lat, lon)
    if date is None:
        date = utc_now().astimezone(tzinfo).date()
    elif isinstance(date, datetime):
        date = date.date()

    key = (round(lat, 4), round(lon, 4), str(tzinfo), date)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit

    result = _compute(lat, lon, tzinfo, date)

    with _cache_lock:
        _cache[key] = result
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return result


def _compute(lat: float, lon: float, tzinfo, date: date_cls) -> SunTimes:
    """astral 계산 본체. 이벤트별로 개별 예외 처리해 부분 결과를 살린다."""
    from astral.sun import dawn, dusk, noon, sunrise, sunset

    observer = _astral_observer(lat, lon)
    status = STATUS_NORMAL
    values = {}

    for name, func in (('sunrise', sunrise), ('sunset', sunset),
                       ('solar_noon', noon), ('civil_dawn', dawn), ('civil_dusk', dusk)):
        try:
            # noon() 은 tzinfo 키워드를 받지만 극야/백야에도 항상 값이 있다.
            values[name] = ensure_utc(func(observer, date, tzinfo=tzinfo))
        except ValueError as exc:
            values[name] = None
            if name in ('sunrise', 'sunset') and status == STATUS_NORMAL:
                status = _classify_polar(exc)
        except Exception:
            logger.exception("태양시 계산 실패 (%s, lat=%s lon=%s, %s)", name, lat, lon, date)
            values[name] = None

    return SunTimes(
        local_date=date,
        tz_name=str(tzinfo),
        latitude=lat,
        longitude=lon,
        status=status,
        **values,
    )


def next_sun_event(kind: str, target_id=None, entity=None,
                   time_offset_minutes: int = 0, date_offset_days: int = 0,
                   now: Optional[datetime] = None,
                   latitude=None, longitude=None) -> Optional[datetime]:
    """`now` 이후 처음 오는 태양 이벤트 시각(UTC-aware). 없으면 None.

    - kind: SUN_EVENTS 중 하나.
    - date_offset_days: 탐색 시작 현지 날짜를 N일 밀어준다(예: 1 = 내일부터).
    - time_offset_minutes: 이벤트 시각에 더할 분(음수 = 이전).
    극지에서 해당 이벤트가 없는 날은 다음 날로 넘어가며 최대 _SEARCH_DAYS 일까지
    훑고, 그래도 없으면 None(호출부가 '이 위치엔 지금 그 이벤트가 없다'로 처리).
    """
    if kind not in SUN_EVENTS:
        logger.error("next_sun_event: 알 수 없는 이벤트 '%s'", kind)
        return None

    now = ensure_utc(now) if now is not None else utc_now()
    lat, lon = _resolve_location(target_id, entity, latitude, longitude)
    if lat is None or lon is None:
        return None

    tzinfo = _tz_for(lat, lon)
    start_date = now.astimezone(tzinfo).date() + timedelta(days=int(date_offset_days or 0))

    for day in range(_SEARCH_DAYS):
        times = sun_times(latitude=lat, longitude=lon, date=start_date + timedelta(days=day))
        if times is None:
            return None
        event = times.event(kind)
        if event is None:
            continue
        event = event + timedelta(minutes=int(time_offset_minutes or 0))
        if event > now:
            return event

    logger.debug("next_sun_event: %s 이벤트를 %d일 내에서 찾지 못했습니다 (lat=%s lon=%s)",
                 kind, _SEARCH_DAYS, lat, lon)
    return None


def next_sun_event_epoch(kind: str, **kwargs) -> Optional[float]:
    """next_sun_event 의 epoch(초) 버전 — 타이머(timer_period) 호환용."""
    event = next_sun_event(kind, **kwargs)
    return event.timestamp() if event is not None else None


def is_daytime(target_id=None, entity=None, at: Optional[datetime] = None,
               start_offset_minutes: int = 0, end_offset_minutes: int = 0,
               latitude=None, longitude=None) -> Optional[bool]:
    """그 위치가 지금(또는 `at`) 주간인지. 판단 불가(좌표 없음)면 None.

    오프셋은 주간 구간의 양 끝을 민다 — start_offset_minutes=+30 이면
    "일출 30분 후부터 주간", end_offset_minutes=-30 이면 "일몰 30분 전에 야간".
    백야는 항상 True, 극야는 항상 False.
    """
    at = ensure_utc(at) if at is not None else utc_now()
    lat, lon = _resolve_location(target_id, entity, latitude, longitude)
    if lat is None or lon is None:
        return None

    tzinfo = _tz_for(lat, lon)
    times = sun_times(latitude=lat, longitude=lon, date=at.astimezone(tzinfo).date())
    if times is None:
        return None
    if times.status == STATUS_ALWAYS_DAY:
        return True
    if times.status == STATUS_ALWAYS_NIGHT:
        return False
    if not times.sunrise or not times.sunset:
        return None

    start = times.sunrise + timedelta(minutes=int(start_offset_minutes or 0))
    end = times.sunset + timedelta(minutes=int(end_offset_minutes or 0))
    return start <= at < end


def sun_position(target_id=None, entity=None, at: Optional[datetime] = None,
                 latitude=None, longitude=None) -> Tuple[Optional[float], Optional[float]]:
    """(태양고도°, 방위각°). 좌표 미해석 시 (None, None).

    고도는 지평선 기준 각도(음수 = 지평선 아래), 방위각은 북=0 시계방향.
    차광·일소 게이트처럼 "해가 얼마나 높은가"가 필요한 곳에서 쓴다.
    """
    at = ensure_utc(at) if at is not None else utc_now()
    lat, lon = _resolve_location(target_id, entity, latitude, longitude)
    if lat is None or lon is None:
        return None, None
    try:
        from astral.sun import azimuth, elevation
        observer = _astral_observer(lat, lon)
        return elevation(observer, at), azimuth(observer, at)
    except Exception:
        logger.exception("태양 위치 계산 실패 (lat=%s lon=%s)", lat, lon)
        return None, None


# 맑은 하늘·해수면 기준 최대 전천일사(W/m²). 태양고도만으로 일사를 어림할 때 쓴다.
CLEAR_SKY_PEAK_W_M2 = 1000.0


def clear_sky_irradiance(target_id=None, entity=None, at: Optional[datetime] = None,
                         latitude=None, longitude=None) -> Optional[float]:
    """태양고도로 어림한 **맑은 날 기준** 수평면 일사(W/m²). 좌표 없으면 None.

    `I ≈ 1000 · sin(고도)` — 대기 감쇠·구름·에어로졸을 무시한 상한이다.
    측정값이 있으면 언제나 측정값을 쓴다. 이 값은 일사 센서가 아예 없는 시설에서
    "지금 해가 얼마나 강한가"를 아무것도 모르는 것보다 낫게 알기 위한 폴백이며,
    맑은 하늘을 가정하므로 **보수적으로 큰 쪽**이다 — 일소 보호처럼 과소평가가
    위험한 판정에 적합하다(구름 낀 날 잠깐 더 잠그는 대가로 맑은 날을 놓치지 않는다).
    해가 지평선 아래면 0.0.
    """
    elevation, _azimuth = sun_position(target_id=target_id, entity=entity, at=at,
                                       latitude=latitude, longitude=longitude)
    if elevation is None:
        return None
    if elevation <= 0.0:
        return 0.0
    return CLEAR_SKY_PEAK_W_M2 * math.sin(math.radians(elevation))


def night_bands(start: datetime, end: datetime, target_id=None, entity=None,
                latitude=None, longitude=None) -> list:
    """[start, end] 구간에 걸치는 밤(일몰~다음 일출)들을 UTC 튜플 목록으로.

    그래프 야간 음영이 쓴다. 구간 밖은 잘라내고, 극야는 그 날 전체를 밤으로,
    백야는 밤 없음으로 다룬다. 좌표를 못 구하면 빈 목록(음영 없이 그린다).
    """
    start = ensure_utc(start)
    end = ensure_utc(end)
    if start is None or end is None or end <= start:
        return []

    lat, lon = _resolve_location(target_id, entity, latitude, longitude)
    if lat is None or lon is None:
        return []
    tzinfo = _tz_for(lat, lon)

    # 경계에 걸친 밤을 놓치지 않도록 앞뒤로 하루씩 넓혀 훑는다.
    first_date = (start.astimezone(tzinfo) - timedelta(days=1)).date()
    last_date = (end.astimezone(tzinfo) + timedelta(days=1)).date()

    bands = []
    pending_sunset = None
    for offset in range((last_date - first_date).days + 1):
        day = first_date + timedelta(days=offset)
        times = sun_times(latitude=lat, longitude=lon, date=day)
        if times is None:
            return []

        if times.status == STATUS_ALWAYS_NIGHT:
            if pending_sunset is None:
                pending_sunset = ensure_utc(
                    tzinfo.localize(datetime.combine(day, datetime.min.time())))
            continue
        if times.status == STATUS_ALWAYS_DAY:
            if pending_sunset is not None:
                bands.append((pending_sunset, ensure_utc(
                    tzinfo.localize(datetime.combine(day, datetime.min.time())))))
                pending_sunset = None
            continue

        if pending_sunset is not None and times.sunrise is not None:
            bands.append((pending_sunset, times.sunrise))
        pending_sunset = times.sunset

    if pending_sunset is not None:
        bands.append((pending_sunset, end))

    clipped = []
    for band_from, band_to in bands:
        lo = max(band_from, start)
        hi = min(band_to, end)
        if hi > lo:
            clipped.append((lo, hi))
    return clipped


def clear_cache():
    """캐시 비우기 — 좌표/시간대 변경 후, 그리고 테스트에서 사용."""
    with _cache_lock:
        _cache.clear()


__all__ = [
    "SunTimes",
    "sun_times", "next_sun_event", "next_sun_event_epoch",
    "is_daytime", "sun_position", "night_bands", "clear_sky_irradiance", "clear_cache",
    "STATUS_NORMAL", "STATUS_ALWAYS_DAY", "STATUS_ALWAYS_NIGHT", "STATUS_UNKNOWN",
    "EVENT_SUNRISE", "EVENT_SUNSET", "EVENT_SOLAR_NOON",
    "EVENT_CIVIL_DAWN", "EVENT_CIVIL_DUSK", "SUN_EVENTS",
]
