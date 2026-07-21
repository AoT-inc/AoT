"""
timekit — AoT 통합 시간 관리 단일 진입점.

설계: docs/design/timezone-management.md

이 모듈은 지금까지 5개로 흩어져 있던 시간대 해석 게이트
(get_device_tz · resolve_location_tz · get_user_tz · get_timezone_name ·
GeoShape/GeoFacility.resolve_timezone)를 하나의 표면으로 흡수한다.

핵심 규약 (변하지 않음):
  - "지금"과 저장은 항상 UTC-aware.            → utc_now(), ensure_utc()
  - 벽시계 의도(예약)는 앵커 tz로 UTC 변환.     → wall_to_utc() / utc_to_wall()
  - API 직렬화는 항상 UTC+offset ISO.          → iso_utc()
  - tz 해석은 단일 우선순위 체인.              → resolve_tz()

Phase 1 범위: 현행 동작과 100% 동일한 부분만 통합한다(순수 리팩터).
  - resolve_tz 의 상속(부모 도형) 단계와 User.timezone 은 아직 없다
    (각각 Phase 3 / Phase 4). 지금은 explicit → coords → system → UTC 만.
  - 기존 device_tz / tz_utils / time_utils 함수는 이 모듈로 위임(wrapper)한다.

프로젝트 표준: pytz (requirements.txt). Docker 컨테이너 tz 는 항상 UTC 취급,
os.timezone 에 의존하지 않는다.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Union

import pytz

logger = logging.getLogger(__name__)

# tz 해석 출처 라벨 — anchor_source / 감사에 사용.
SOURCE_EXPLICIT = "explicit"    # 엔티티에 명시 저장된 IANA tz
SOURCE_INHERITED = "inherited"  # 부모 도형(사이트/구역)에서 상속  (Phase 3)
SOURCE_COORDS = "coords"        # 엔티티 좌표 → timezonefinder
SOURCE_USER = "user"            # User.timezone                    (Phase 4)
SOURCE_SYSTEM = "system"        # Misc.timezone 농장 전역 폴백
SOURCE_UTC = "utc"              # 최종 폴백


# ---------------------------------------------------------------------------
# "지금" · UTC 규약
# ---------------------------------------------------------------------------
def utc_now() -> datetime:
    """tz-aware 현재 UTC 시각. 모든 신규 코드의 '지금'."""
    return datetime.now(timezone.utc)


# 편의 별칭 (기존 코드가 now_utc 로 부르는 곳과 호환)
now_utc = utc_now


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """어떤 datetime 이든 UTC-aware 로 정규화.

    naive datetime 은 UTC 로 가정한다(백엔드 저장 규약). None 은 그대로 통과.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# tz 객체 헬퍼
# ---------------------------------------------------------------------------
def as_tz(tz: Union[str, pytz.BaseTzInfo, None]) -> pytz.BaseTzInfo:
    """IANA 문자열 또는 tzinfo 를 pytz tzinfo 로. 실패 시 UTC."""
    if tz is None:
        return pytz.utc
    if isinstance(tz, str):
        try:
            return pytz.timezone(tz)
        except Exception:
            return pytz.utc
    return tz


def to_tz(dt: Optional[datetime], tz: Union[str, pytz.BaseTzInfo, None]) -> Optional[datetime]:
    """UTC(또는 naive=UTC) datetime 을 대상 tz 로 변환."""
    dt = ensure_utc(dt)
    if dt is None:
        return None
    return dt.astimezone(as_tz(tz))


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """API 직렬화 표준: 항상 UTC+offset ISO 8601 문자열.

    예: '2026-05-06T12:34:56+00:00'. 프론트(AoTTz)가 device/viewer tz 로
    변환하는 단일 진실 공급원. naive 는 UTC 로 가정.
    """
    dt = ensure_utc(dt)
    return dt.isoformat() if dt is not None else None


# ---------------------------------------------------------------------------
# 시스템(농장 전역) tz — Misc.timezone
# ---------------------------------------------------------------------------
def system_tz_name() -> Optional[str]:
    """Misc.timezone 을 daemon/Flask 양 컨텍스트에서 안전하게 읽어 반환.

    get_device_tz(None) 이 쓰던 폴백 순서를 그대로 보존한다:
      1) db_retrieve_table_daemon(Misc)  — daemon·Flask 모두 동작
      2) Flask-SQLAlchemy get_timezone_name() — 'UTC'가 아니면 채택
    둘 다 실패하면 None(호출자가 UTC 처리).
    """
    tz_name = None
    try:
        from aot.utils.database import db_retrieve_table_daemon
        from aot.databases.models.misc import Misc
        misc = db_retrieve_table_daemon(Misc, entry='first')
        if misc and getattr(misc, 'timezone', None):
            tz_name = misc.timezone
    except Exception:
        tz_name = None

    if not tz_name:
        try:
            from aot.utils.time_utils import get_timezone_name
            name = get_timezone_name()
            if name and name != 'UTC':
                tz_name = name
        except Exception:
            tz_name = None
    return tz_name


def system_tz() -> pytz.BaseTzInfo:
    """농장 전역 기본 tz (Misc.timezone). 최후 폴백. 실패 시 UTC."""
    return as_tz(system_tz_name() or 'UTC')


def current_user_tz() -> pytz.BaseTzInfo:
    """요청 컨텍스트의 로그인 사용자 개인 tz (User.timezone) → 없으면 시스템.

    개인 '표시'(뷰어 시각·개인 알림)에만 쓴다. 장치 예약 해석(장치 현지 앵커)이나
    벽시계 해석에는 쓰지 않는다(get_user_tz=시스템 유지). 요청 밖(daemon)이거나
    미로그인/미설정이면 시스템 tz 로 폴백해 어디서든 안전하다.
    """
    try:
        from flask_login import current_user
        if current_user is not None and getattr(current_user, 'is_authenticated', False):
            utz = getattr(current_user, 'timezone', None)
            if utz:
                return as_tz(utz)
    except Exception:
        pass
    return system_tz()


# ---------------------------------------------------------------------------
# 단일 해석 체인 — resolve_tz
# ---------------------------------------------------------------------------
def _inherited_tz_for_device(entity):
    """장치 row 의 소속 도형에서 tz 를 상속 (device_id 로 연결된 GeoShape →
    parent_id 체인). 도형이 없거나 해석 실패 시 None.

    device.timezone 캐시가 비었을 때만 호출되므로(아래 resolve_tz 참조) 읽기
    핫패스에는 추가 쿼리가 없다 — 기존 장치는 캐시가 이미 차 있다.
    """
    uid = getattr(entity, 'unique_id', None)
    if not uid:
        return None
    try:
        from aot.databases.models.geo import GeoShape
        shape = GeoShape.query.filter_by(device_id=uid).first()
        if shape is not None:
            return shape.resolve_timezone()
    except Exception:
        pass
    return None


def resolve_tz(entity=None, *, user=None) -> Tuple[pytz.BaseTzInfo, str]:
    """엔티티/사용자/시스템의 tz 를 단일 우선순위로 해석해 (tzinfo, source) 반환.

    체인 (docs/design/timezone-management.md §4·§5):
      entity 가 도형(GeoShape/GeoFacility, resolve_timezone 보유):
        그 자체 상속-aware 해석기(저장값→부모→facility→centroid)를 사용.
      entity 가 장치 row:
        1. entity.timezone (물질화 캐시 — 명시/상속/좌표)  → 캐시의 tz_source
        2. 소속 도형 상속(device_id→GeoShape→부모체인)       → inherited
        3. entity 좌표 → timezonefinder                      → coords
        4. 시스템(Misc.timezone)                             → system
      user: 현재는 시스템과 동일(User.timezone 은 Phase 4).
      entity=None: 시스템 폴백 체인.
    """
    # user 분기 — User.timezone(개인 표시 선호) → 시스템 폴백
    if entity is None and user is not None:
        utz = getattr(user, 'timezone', None)
        if utz:
            return as_tz(utz), SOURCE_USER
        name = system_tz_name()
        if name:
            return as_tz(name), SOURCE_SYSTEM
        return pytz.utc, SOURCE_UTC

    if entity is not None:
        # 도형/시설: 자체 상속-aware 해석기 사용
        resolver = getattr(entity, 'resolve_timezone', None)
        if callable(resolver):
            try:
                tz = resolver()
                if tz is not None:
                    return tz, (getattr(entity, 'tz_source', None) or SOURCE_INHERITED)
            except Exception:
                pass
        else:
            # 장치 row
            # 1. 물질화 캐시 (O(1) 핫패스)
            tz_name = getattr(entity, 'timezone', None)
            if tz_name:
                return as_tz(tz_name), (getattr(entity, 'tz_source', None) or SOURCE_EXPLICIT)
            # 2. 소속 도형 상속 (캐시 비었을 때만)
            inh = _inherited_tz_for_device(entity)
            if inh is not None:
                return inh, SOURCE_INHERITED
            # 3. 좌표 → finder
            try:
                from aot.utils.device_tz import resolve_tz_from_coords
                coord_tz = resolve_tz_from_coords(
                    getattr(entity, 'latitude', None),
                    getattr(entity, 'longitude', None),
                )
            except Exception:
                coord_tz = None
            if coord_tz:
                return as_tz(coord_tz), SOURCE_COORDS

    # 시스템 폴백
    name = system_tz_name()
    if name:
        return as_tz(name), SOURCE_SYSTEM
    return pytz.utc, SOURCE_UTC


# ---------------------------------------------------------------------------
# 벽시계 의도 ↔ UTC (예약 저장/표시)
# ---------------------------------------------------------------------------
def _parse_wall(wall: Union[str, datetime]) -> datetime:
    """벽시계 입력을 naive datetime 으로 파싱.

    허용: naive datetime, ISO 문자열('YYYY-MM-DDTHH:MM[:SS]'),
          공백 구분 'YYYY-MM-DD HH:MM[:SS]'.
    aware datetime 이 들어오면 tzinfo 를 떼어 벽시계로만 취급한다
    (앵커 tz 인자가 진실 공급원이므로).
    """
    if isinstance(wall, datetime):
        return wall.replace(tzinfo=None)
    s = str(wall).strip().replace(' ', 'T')
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=None)


def wall_to_utc(wall: Union[str, datetime],
                tz: Union[str, pytz.BaseTzInfo, None]) -> datetime:
    """벽시계(문자열/naive) + 앵커 tz → UTC-aware datetime (예약 저장용).

    pytz.localize 를 사용해 DST 를 올바르게 적용한다(naive.replace(tzinfo=)로
    붙이는 방식은 과거 offset 이 고정되는 pytz 함정이 있어 금지).
    """
    naive = _parse_wall(wall)
    tzinfo = as_tz(tz)
    try:
        local_aware = tzinfo.localize(naive)   # pytz: DST 정확
    except AttributeError:
        # zoneinfo 등 localize 가 없는 tzinfo 대비
        local_aware = naive.replace(tzinfo=tzinfo)
    return local_aware.astimezone(timezone.utc)


def utc_to_wall(dt: Optional[datetime],
                tz: Union[str, pytz.BaseTzInfo, None]) -> Optional[datetime]:
    """UTC(또는 naive=UTC) → 앵커 tz 의 벽시계(aware datetime, 예약 표시용)."""
    return to_tz(dt, tz)


__all__ = [
    "utc_now", "now_utc", "ensure_utc",
    "as_tz", "to_tz", "iso_utc",
    "system_tz", "system_tz_name", "current_user_tz",
    "resolve_tz",
    "wall_to_utc", "utc_to_wall",
    "SOURCE_EXPLICIT", "SOURCE_INHERITED", "SOURCE_COORDS",
    "SOURCE_USER", "SOURCE_SYSTEM", "SOURCE_UTC",
]
