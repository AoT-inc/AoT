# coding=utf-8
"""
sunriseset — DEPRECATED. 태양시 계산은 aot.utils.solar 로 이전되었다.

이 모듈은 외부/사용자 코드(user_python_code, 사용자 스크립트)가 예전 이름을
계속 부를 수 있도록 남겨 둔 얇은 호환 shim 이다. 신규 코드는 전부
aot.utils.solar 를 직접 쓴다.

이전 구현과의 차이 (의도된 수정):
  - 계산 기준이 시스템 로컬 tz(datetime.tzlocal) → **위치의 현지 tz** 로 바뀌었다.
    컨테이너 tz 를 UTC 로 취급하는 프로젝트 규약(docs/design/timezone-management.md)
    아래서 예전 구현은 하루 경계를 잘못 잡을 수 있었다.
  - epoch 변환이 strftime('%s')(플랫폼 의존) → datetime.timestamp() 로 바뀌었다.
  - 선택 설치 의존성 suntime 이 필요 없다(astral 이 정식 의존성).
"""
import logging

from aot.utils.solar import next_sun_event, next_sun_event_epoch

logger = logging.getLogger("aot.sun_rise_set")

_DEPRECATION = ("aot.utils.sunriseset 은 더 이상 사용하지 않습니다. "
                "aot.utils.solar 를 사용하세요.")


def suntime_calculate_next_sunrise_sunset_epoch(
        latitude, longitude, date_offset_days, time_offset_minutes,
        rise_or_set, return_dt=False):
    """DEPRECATED — aot.utils.solar.next_sun_event(_epoch) 로 위임."""
    logger.debug(_DEPRECATION)
    kwargs = dict(latitude=latitude,
                  longitude=longitude,
                  date_offset_days=date_offset_days,
                  time_offset_minutes=time_offset_minutes)
    if return_dt:
        return next_sun_event(rise_or_set, **kwargs)
    return next_sun_event_epoch(rise_or_set, **kwargs)


def calculate_next_sunrise_sunset_epoch(
        latitude, longitude, zenith, date_offset_days, time_offset_minutes, rise_or_set):
    """DEPRECATED — zenith 인자는 무시된다(태양시 커널은 표준 굴절값 사용)."""
    logger.debug(_DEPRECATION)
    return next_sun_event_epoch(
        rise_or_set,
        latitude=latitude,
        longitude=longitude,
        date_offset_days=date_offset_days,
        time_offset_minutes=time_offset_minutes)
