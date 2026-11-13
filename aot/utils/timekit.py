"""
timekit — AoT 통합 시간 관리 단일 진입점.

설계: docs/design/timezone-management.md

시간대 해석·변환·직렬화의 단일 진입점이다. 공개 입구는 `PUBLIC_ENTRIES` 열 둘뿐이고
(옛 이름은 S10 에서 모두 삭제), 가드 `aot/scripts/check_time_rules.py` 가 우회를 막는다.

핵심 규약 (변하지 않음):
  - "지금"과 저장은 항상 UTC-aware.            → utc_now(), _ensure_utc()
  - 벽시계 의도(예약)는 앵커 tz로 UTC 변환.     → wall_to_utc() / to_tz()
  - API 직렬화는 항상 UTC+offset ISO.          → iso_utc()
  - tz 해석은 단일 우선순위 체인.              → resolve_tz()

Phase 1 범위: 현행 동작과 100% 동일한 부분만 통합한다(순수 리팩터).
  - resolve_tz 의 상속(부모 도형) 단계와 User.timezone 은 아직 없다
    (각각 Phase 3 / Phase 4). 지금은 explicit → coords → system → UTC 만.

프로젝트 표준: pytz (requirements.txt). Docker 컨테이너 tz 는 항상 UTC 취급,
os.timezone 에 의존하지 않는다.
"""
import contextlib
import contextvars
import logging
from datetime import datetime, timezone
from datetime import tzinfo as datetime_tzinfo
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
SOURCE_DEVICE = "device"        # 도형·시설·구획·지도에서 해석 (장소 id)


# ---------------------------------------------------------------------------
# "지금" · UTC 규약
# ---------------------------------------------------------------------------
def utc_now() -> datetime:
    """tz-aware 현재 UTC 시각. 모든 신규 코드의 '지금'."""
    return datetime.now(timezone.utc)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
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
def _as_tz(tz: Union[str, pytz.BaseTzInfo, None]) -> pytz.BaseTzInfo:
    """IANA 문자열 또는 tzinfo 를 pytz tzinfo 로. 실패 시 UTC."""
    if tz is None:
        return pytz.utc
    if isinstance(tz, str):
        try:
            return pytz.timezone(tz)
        except Exception:
            return pytz.utc
    return tz


def to_tz(value, where) -> Optional[datetime]:
    """순간(datetime·epoch·ISO 문자열; naive=UTC) → `where` 시계의 aware datetime."""
    if value is None:
        return None
    dt = _ensure_utc(value if isinstance(value, datetime) else parse_utc(value))
    return dt.astimezone(tz_of(where))


def naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """DB naive 컬럼과 비교·저장할 UTC naive. aware 는 UTC 로 바꿔 tzinfo 를 뗀다."""
    if dt is None:
        return None
    return _ensure_utc(dt).replace(tzinfo=None)


def parse_utc(value) -> datetime:
    """datetime·epoch·ISO 문자열(`Z`·오프셋)을 순간(UTC aware)으로. 오프셋이 없으면 UTC.

    못 읽으면 `ValueError`.
    """
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"시각으로 읽을 수 없는 값: {value!r}")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    s = str(value).strip().replace(' ', 'T')
    if s.endswith(('Z', 'z')):
        s = s[:-1] + '+00:00'
    try:
        return _ensure_utc(datetime.fromisoformat(s))
    except ValueError:
        raise ValueError(f"시각으로 읽을 수 없는 값: {value!r}") from None


def iso_at(value, where, cache=None):
    """사람·AI 가 읽는 ISO — `where` 시계의 오프셋 문자열. 못 읽으면 입력 그대로."""
    if value is None:
        return None
    try:
        dt = _ensure_utc(value if isinstance(value, datetime) else parse_utc(value))
        return dt.astimezone(tz_of(where, cache)).isoformat()
    except Exception:
        return value


def today_at(where):
    """`where` 시계의 오늘 날짜."""
    return utc_now().astimezone(tz_of(where)).date()


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """API 직렬화 표준: 항상 UTC+offset ISO 8601 문자열.

    예: '2026-05-06T12:34:56+00:00'. 프론트(AoTTz)가 device/viewer tz 로
    변환하는 단일 진실 공급원. naive 는 UTC 로 가정.
    """
    dt = _ensure_utc(dt)
    return dt.isoformat() if dt is not None else None


# ---------------------------------------------------------------------------
# 시스템(농장 전역) tz — Misc.timezone
# ---------------------------------------------------------------------------
def _system_tz_name() -> Optional[str]:
    """Misc.timezone 의 이름. 앱 컨텍스트가 있든 없든 같은 길(`_db_row`)로 읽는다.

    못 읽거나 미설정이면 None(호출자가 UTC 처리). 예전에는 데몬 읽기가 실패하면
    Flask 쪽 옛 입구로 한 번 더 시도했는데, 그쪽은 `Misc.query`
    라 컨텍스트가 없으면 어차피 실패했다.
    """
    from aot.databases.models.misc import Misc
    misc = _db_row(Misc, entry='first')
    name = getattr(misc, 'timezone', None) if misc else None
    return name or None


# ---------------------------------------------------------------------------
# 단일 해석 체인 — resolve_tz
# ---------------------------------------------------------------------------
class _Marker:
    """시계 표식 — `where` 에 넣는 값. 문자열과 구별되는 단일 객체."""
    __slots__ = ('name',)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"timekit.{self.name}"


FARM = _Marker('FARM')      # 장소와 무관한 시각(로그·감사·내보내기) = 농장 시계
VIEWER = _Marker('VIEWER')  # 보는 사람의 개인 tz → 농장


def _valid_tz_name(name) -> Optional[pytz.BaseTzInfo]:
    """IANA 이름이면 tzinfo, 아니면 None."""
    if isinstance(name, str) and name in pytz.all_timezones_set:
        return pytz.timezone(name)
    return None


def _farm_tz() -> Tuple[pytz.BaseTzInfo, str]:
    """농장 시계 — Misc.timezone, 못 읽거나 미설정이면 UTC."""
    tz = _valid_tz_name(_system_tz_name())
    if tz is not None:
        return tz, SOURCE_SYSTEM
    return pytz.utc, SOURCE_UTC


def _centroid_tz(centroid) -> Optional[pytz.BaseTzInfo]:
    if not centroid:
        return None
    try:
        from aot.utils.device_tz import resolve_tz_from_coords
        return _valid_tz_name(resolve_tz_from_coords(centroid[0], centroid[1]))
    except Exception:
        return None


def _facility_tz(fac) -> Optional[pytz.BaseTzInfo]:
    """시설: 명시 tz → 연결 도형 중심 좌표."""
    tz = _valid_tz_name(getattr(fac, 'timezone', None))
    if tz is not None:
        return tz
    from aot.databases.models.geo import GeoShape
    shape = _db_row(GeoShape, unique_id=fac.shape_uuid)
    return _centroid_tz(shape.get_centroid()) if shape is not None else None


def _shape_tz(shape, _seen=None) -> Optional[pytz.BaseTzInfo]:
    """도형: 저장값 → 부모 체인 → 연결 시설 → 자기 중심 좌표.

    `GeoShape.resolve_timezone` 과 같은 순서이되 조회는 `_db_row` 한 길이다
    (그쪽은 `.query` 라 앱 컨텍스트가 없으면 조용히 실패한다).
    """
    from aot.databases.models.geo import GeoFacility, GeoShape
    seen = _seen if _seen is not None else set()
    if shape is None or shape.id in seen:
        return None
    seen.add(shape.id)
    tz = _valid_tz_name(getattr(shape, 'timezone', None))
    if tz is not None:
        return tz
    pid = getattr(shape, 'parent_id', None)
    if pid is not None and pid not in seen:
        tz = _shape_tz(_db_row(GeoShape, device_id=pid), seen)
        if tz is not None:
            return tz
    fac = _db_row(GeoFacility, custom_name='shape_uuid',
                  custom_value=shape.unique_id, entry='first')
    if fac is not None:
        tz = _facility_tz(fac)
        if tz is not None:
            return tz
    return _centroid_tz(shape.get_centroid())


def _map_tz(geo_id) -> Optional[pytz.BaseTzInfo]:
    """지도 자체 — 그 지도의 site → zone → 나머지 도형 순."""
    from aot.databases.models.geo import GeoShape
    shapes = _db_row(GeoShape, custom_name='geo_id', custom_value=geo_id,
                     entry='all') or []
    for shape in sorted(shapes[:50], key=lambda s: s.level_id):
        tz = _shape_tz(shape)
        if tz is not None:
            return tz
    return None


def _scoped_containers(geo_id):
    """`tz_scope` 안에서만 지도별 site/zone 컨테이너를 한 번 읽어 재사용한다. 밖이면 None(기존 동작).

    구획마다 `load_containers` 가 지도 도형 전량을 다시 읽던 것을 막는다(구획 목록 185회).
    scope 가 끝나면 메모도 사라지고, 읽기 전용 블록이라 도형이 바뀌어 어긋나지 않는다.
    """
    scoped = _SCOPE_TZ.get()
    if scoped is None or not geo_id:
        return None
    key = ('__containers__', geo_id)
    if key not in scoped:
        from aot.space import device_membership
        scoped[key] = device_membership.load_containers(geo_id)
    return scoped[key]


def _plot_tz(plot) -> Optional[pytz.BaseTzInfo]:
    """구획: 소속 구역(설계 §8 — 운영 그룹은 한 시계) → 시설 구획은 그 시설 → 그 지도.

    소속 판정(`zone_for_plot`)은 앱 컨텍스트가 없으면 `_db_row` 로 읽는다.
    """
    from aot.databases.models.geo import GeoFacility
    try:
        from aot.space import plot_context
        container = plot_context.zone_for_plot(
            plot, containers=_scoped_containers(getattr(plot, 'geo_id', None)))
        if container is not None:
            tz = _shape_tz(container)
            if tz is not None:
                return tz
    except Exception as exc:
        logger.debug("timekit: 구획 소속 구역 판정 실패: %s", exc)
    fuid = getattr(plot, 'facility_uuid', None)
    if fuid:
        fac = _db_row(GeoFacility, unique_id=fuid)
        if fac is not None:
            tz = _facility_tz(fac)
            if tz is not None:
                return tz
    return _map_tz(plot.geo_id)


def _device_kind_of(row) -> Optional[str]:
    """장치 행 → device_kind (`device_binding.device_kind_models` 의 어휘). 장치가 아니면 None."""
    try:
        from aot.space.device_binding import device_kind_models
        for kind, model in device_kind_models():
            if isinstance(row, model):
                return kind
    except Exception as exc:
        logger.debug("timekit: device_kind 판별 실패: %s", exc)
    return None


def _locate_row(row):
    """장치 행 → 리졸버 `Placement`. 장치가 아니거나 실패하면 None (소비자가 농장 폴백)."""
    kind = _device_kind_of(row)
    uid = getattr(row, 'unique_id', None)
    if kind is None or not uid:
        return None
    try:
        from aot.space.device_location import locate
        return locate(kind, uid)
    except Exception as exc:
        logger.debug("timekit: 장치 위치 리졸버 실패: %s", exc)
        return None


def _device_tz(row) -> Optional[Tuple[pytz.BaseTzInfo, str]]:
    """장치 행: 리졸버(자리에서 상속한 tz) → 자리의 좌표.

    장치는 더 이상 자기 시간대를 저장하지 않는다(L4, 결정 ①: 공간 상속). 사람이
    "이 장치만 다른 시간대"로 핀한 explicit 값은 L4 백필이 자리 도형의 timezone 으로
    승격했으므로, 여기서는 배치에서만 해석한다.
    """
    pl = _locate_row(row)
    if pl is None:
        return None
    tz = _valid_tz_name(pl.tz)
    if tz is not None:
        return tz, SOURCE_INHERITED
    tz = _centroid_tz(pl.point)
    if tz is not None:
        return tz, SOURCE_COORDS
    return None


def _row_tz(row) -> Optional[Tuple[pytz.BaseTzInfo, str]]:
    """행(도형·시설·구획·장치) → (tz, source). 못 풀면 None."""
    if hasattr(row, 'parent_id') and hasattr(row, 'feature'):
        tz = _shape_tz(row)
        return (tz, SOURCE_DEVICE) if tz is not None else None
    if hasattr(row, 'shape_uuid'):
        tz = _facility_tz(row)
        return (tz, SOURCE_DEVICE) if tz is not None else None
    if hasattr(row, 'geo_id') and hasattr(row, 'facility_uuid'):
        tz = _plot_tz(row)
        return (tz, SOURCE_DEVICE) if tz is not None else None
    return _device_tz(row)


def _db_first(models, unique_id):
    """모델들을 차례로 보아 `unique_id` 가 처음 있는 행 하나. 세션 하나로 훑는다.

    `_db_row` 와 같은 DB 길(`session_scope(AOT_DB_PATH)`)이다. 못 찾는 id 는 모델 수만큼
    조회하므로(실측 11번) 한 세션에 묶는다. 읽기 실패 시 `_db_row` 로 하나씩 되돌아간다.
    """
    try:
        from aot.config import AOT_DB_PATH
        from aot.utils.database import session_scope
        with session_scope(AOT_DB_PATH) as session:
            for model in models:
                row = session.query(model).filter(model.unique_id == unique_id).first()
                if row is not None:
                    session.expunge_all()
                    return model, row
        return None, None
    except Exception:
        for model in models:
            row = _db_row(model, unique_id=unique_id)
            if row is not None:
                return model, row
        return None, None


def _place_tz(target_id) -> Optional[Tuple[pytz.BaseTzInfo, str]]:
    """id → (tz, source). 못 찾으면 None. 조회는 `_db_row`·`_db_first` 뿐."""
    from aot.databases.models import (
        PID, Conditional, CustomController, Function, GeoPlot, Input, Output, Trigger)
    from aot.databases.models.geo import GeoFacility, GeoShape
    model, row = _db_first(
        (GeoShape, GeoPlot, GeoFacility, Input, Output, Function, Conditional,
         Trigger, PID, CustomController), target_id)
    if row is not None:
        if model is GeoShape:
            tz = _shape_tz(row)
        elif model is GeoPlot:
            tz = _plot_tz(row)
        elif model is GeoFacility:
            tz = _facility_tz(row)
        else:
            return _device_tz(row)
        if tz is not None:
            return tz, SOURCE_DEVICE
    tz = _map_tz(target_id)
    return (tz, SOURCE_DEVICE) if tz is not None else None


# 도구 호출 하나 동안만 사는 시계 캐시(`tz_scope`). 프로세스 캐시가 아니다.
_SCOPE_TZ = contextvars.ContextVar('_timekit_scope_tz', default=None)


@contextlib.contextmanager
def tz_scope():
    """이 블록 안의 시계 해석을 한 번씩만 한다 (읽기 전용 일괄 계산용).

    요청 밖(MCP·데몬)에서는 `tz_of` 가 호출마다 DB 를 다시 읽는다. 장소 하나를 요약하는
    읽기 도구는 같은 구획·장소를 수백 번 묻는다(2026-11-07 실측: 개요 한 번에 266회,
    DB 에서 2초). 블록이 끝나면 캐시도 사라지므로 다른 호출·프로세스와 어긋날 수 없다.
    블록 안에서 시계를 바꾸는 쓰기를 하지 말 것. 중첩하면 바깥 캐시를 그대로 쓴다.
    """
    if _SCOPE_TZ.get() is not None:
        yield
        return
    token = _SCOPE_TZ.set({})
    try:
        yield
    finally:
        _SCOPE_TZ.reset(token)


def _request_cache():
    """요청 안에서만 사는 캐시(flask.g) 또는 `tz_scope` 캐시. 둘 다 아니면 None."""
    scoped = _SCOPE_TZ.get()
    if scoped is not None:
        return scoped
    try:
        from flask import g, has_request_context
        if has_request_context():
            return g.setdefault('_timekit_tz', {})
    except Exception:
        pass
    return None


def _resolve(where, cache=None) -> Tuple[pytz.BaseTzInfo, str]:
    """`where` → (tz, source). 폴백 사슬은 장소 → 농장 → UTC 하나."""
    if isinstance(where, datetime_tzinfo):
        return where, SOURCE_EXPLICIT
    if where is None or where is FARM:
        scoped = _SCOPE_TZ.get()
        if scoped is None:
            return _farm_tz()
        if '__farm__' not in scoped:
            scoped['__farm__'] = _farm_tz()
        return scoped['__farm__']
    if where is VIEWER:
        try:
            from flask_login import current_user
            if current_user is not None and getattr(current_user, 'is_authenticated', False):
                tz = _valid_tz_name(getattr(current_user, 'timezone', None))
                if tz is not None:
                    return tz, SOURCE_USER
        except Exception:
            pass
        return _farm_tz()
    if isinstance(where, str):
        key = where.strip()
        if not key or key.lower() == 'none':
            return _farm_tz()
        tz = _valid_tz_name(key)
        if tz is not None:
            return tz, SOURCE_EXPLICIT
        if cache is None:
            cache = _request_cache()
        if cache is not None and key in cache:
            return cache[key]
        try:
            found = _place_tz(key.split('::')[0])
        except Exception as exc:
            logger.debug("timekit: 장소 %s 조회 실패: %s", key, exc)
            found = None
        result = found if found is not None else _farm_tz()
        if cache is not None:
            cache[key] = result
        return result
    # 행(구획·시설·장치…)은 `tz_scope` 안에서만 캐시한다 — 요청 캐시는 문자열 키 전용이었다.
    scoped, row_key = _SCOPE_TZ.get(), None
    if scoped is not None:
        uid = getattr(where, 'unique_id', None)
        if uid:
            row_key = (type(where).__name__, uid)
            if row_key in scoped:
                return scoped[row_key]
    try:
        found = _row_tz(where)
    except Exception as exc:
        logger.debug("timekit: 행 시계 해석 실패: %s", exc)
        found = None
    result = found if found is not None else _farm_tz()
    if row_key is not None:
        scoped[row_key] = result
    return result


def resolve_tz(where=None, *, user=None) -> Tuple[pytz.BaseTzInfo, str]:
    """`where` 가 가리키는 시계와 출처 `(tz, source)`.

    where: 대상 id · 행(장치·도형·시설·구획) · tzinfo · IANA 이름 · FARM · VIEWER · None.
    폴백은 장소 → 농장(Misc.timezone) → UTC 하나이고 `source` 가 어디로 떨어졌는지
    말한다(`device`·`inherited`·`coords`·`explicit`·`user`·`system`·`utc`).
    `user=` 는 옛 호출 호환 — where 가 없을 때 그 사용자의 개인 tz → 농장.
    """
    if where is None and user is not None:
        tz = _valid_tz_name(getattr(user, 'timezone', None))
        if tz is not None:
            return tz, SOURCE_USER
    return _resolve(where)


def tz_of(where=None, cache=None) -> pytz.BaseTzInfo:
    """`where` 가 가리키는 시계. 요청 안에서는 장소마다 한 번만 푼다.

    `cache=` 는 요청 밖 일괄 처리용(dict 를 넘기면 거기에 쌓는다).
    """
    return _resolve(where, cache)[0]


# ---------------------------------------------------------------------------
# 좌표 해석 체인 — resolve_coords (resolve_tz 와 같은 상속 규칙, 값만 좌표)
# ---------------------------------------------------------------------------
def _db_row(table, **kwargs):
    """daemon·Flask 양쪽에서 동작하는 단일 row 조회(지연 임포트 — 순환 방지)."""
    try:
        from aot.utils.database import db_retrieve_table_daemon
        return db_retrieve_table_daemon(table, **kwargs)
    except Exception:
        return None


def _shape_centroid(shape) -> Optional[Tuple[float, float]]:
    """GeoShape 의 중심 좌표. 자기 도형에 없으면 부모 체인을 따라 올라간다."""
    seen = set()
    cur = shape
    while cur is not None and getattr(cur, 'id', None) not in seen:
        seen.add(getattr(cur, 'id', None))
        try:
            centroid = cur.get_centroid()
            if centroid and centroid[0] is not None and centroid[1] is not None:
                return (float(centroid[0]), float(centroid[1]))
        except Exception:
            pass
        parent_id = getattr(cur, 'parent_id', None)
        if not parent_id:
            return None
        from aot.databases.models.geo import GeoShape
        cur = _db_row(GeoShape, custom_name='id', custom_value=parent_id, entry='first')
    return None


class Coords(tuple):
    """(위도, 경도, source) 3-튜플 — 언패킹 호환. `.basis` 는 위치가 어디 기준인가
    ('device' 장치 자리 | 'site' 대지 | 'none' 리졸버 밖 폴백/없음)."""

    basis = 'none'

    def __new__(cls, lat, lon, source, basis='none'):
        self = super().__new__(cls, (lat, lon, source))
        self.basis = basis
        return self


def resolve_coords(entity=None, *, target_id=None) -> Coords:
    """엔티티/위치의 (위도, 경도, source) 를 resolve_tz 와 같은 우선순위로 해석.

    체인:
      1. 도형(GeoShape) 자신 또는 target_id 가 가리키는 도형의 중심 → shape
      2. 장치 row → `device_location.locate` (바인딩·레거시 과도기 포함) → inherited
         (결과의 `.basis` 가 'site' 면 장치 자리가 아니라 대지 기준)
      3. 농장 전역 폴백(Misc.map_* → 사이트 도형 중심 → 지도 기본값) → system
      4. 해석 불가                                                   → utc(=없음)

    daemon·Flask 양 컨텍스트에서 동작한다(db_retrieve_table_daemon 사용).
    좌표가 없으면 (None, None, SOURCE_UTC) — 호출자가 "위치 없음"으로 처리한다.
    """
    row = entity
    if row is None and target_id and target_id != 'none':
        from aot.databases.models.geo import GeoShape
        row = _db_row(GeoShape, unique_id=target_id, entry='first')
        if row is None:
            try:
                from aot.databases.models import (
                    Input, Output, Function, Conditional, Trigger, PID, CustomController)
                for model in (Input, Output, Function, Conditional,
                              Trigger, PID, CustomController):
                    found = _db_row(model, unique_id=target_id, entry='first')
                    if found is not None:
                        row = found
                        break
            except Exception:
                row = None

    if row is not None:
        # 1. 도형이면 자신(→부모) 중심
        if hasattr(row, 'get_centroid'):
            centroid = _shape_centroid(row)
            if centroid:
                return Coords(centroid[0], centroid[1], SOURCE_EXPLICIT)

        # 2. 장치 row → 리졸버 (유일한 장치 위치 판정). 좌표는 배치에서만 나온다
        #    — 장치 행에는 위치 컬럼이 없다(L4 S3c).
        pl = _locate_row(row)
        if pl is not None and pl.point is not None:
            try:
                return Coords(float(pl.point[0]), float(pl.point[1]),
                              SOURCE_INHERITED, pl.basis)
            except (TypeError, ValueError):
                pass

    # 4. 농장 전역 폴백
    lat, lon = _system_coords()
    if lat is not None and lon is not None:
        return Coords(lat, lon, SOURCE_SYSTEM)

    return Coords(None, None, SOURCE_UTC)


def _system_coords() -> Tuple[Optional[float], Optional[float]]:
    """농장 전역 기준 좌표.

    Misc.map_* (명시 설정) → 사이트 도형 중심(실제 농장 위치) → GeoSetting
    기본 지도 중심 순. 실서버에서 Misc.map_* 가 비어 있는 경우가 흔해서
    도형 단계가 사실상의 기준이 된다.
    """
    try:
        from aot.databases.models.misc import Misc
        misc = _db_row(Misc, entry='first')
        if misc is not None:
            lat = getattr(misc, 'map_latitude', None)
            lon = getattr(misc, 'map_longitude', None)
            if lat is not None and lon is not None:
                return float(lat), float(lon)
    except Exception:
        pass

    try:
        from aot.databases.models.geo import GeoShape
        site = _db_row(GeoShape, custom_name='type', custom_value='site', entry='first')
        if site is not None:
            centroid = _shape_centroid(site)
            if centroid:
                return centroid
    except Exception:
        pass

    try:
        from aot.databases.models.geo import GeoSetting
        setting = _db_row(GeoSetting, entry='first')
        if setting is not None:
            lat = getattr(setting, 'default_lat', None)
            lon = getattr(setting, 'default_lng', None)
            if lat is not None and lon is not None:
                return float(lat), float(lon)
    except Exception:
        pass

    return None, None


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


def wall_to_utc(wall: Union[str, datetime], where) -> datetime:
    """벽시계 → 순간(UTC aware). **오프셋이 붙어 있으면 그 순간**이고, 없으면 `where`
    시계의 벽시계로 읽는다(pytz.localize — DST 정확; 간극은 표준시, 중복은 두 번째).

    naive.replace(tzinfo=) 로 붙이는 방식은 과거 offset 이 고정되는 pytz 함정이 있다.
    """
    if isinstance(wall, datetime):
        dt = wall
    else:
        s = str(wall).strip().replace(' ', 'T')
        if s.endswith(('Z', 'z')):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    tzinfo = tz_of(where)
    try:
        local_aware = tzinfo.localize(dt)   # pytz: DST 정확
    except AttributeError:
        # zoneinfo 등 localize 가 없는 tzinfo 대비
        local_aware = dt.replace(tzinfo=tzinfo)
    return local_aware.astimezone(timezone.utc)


def utc_offset_label(dt: Optional[datetime], tz: Union[str, pytz.BaseTzInfo, None]) -> str:
    """그 순간의 tz 오프셋을 'UTC+09:00' 꼴로. 목록의 각 시각 뒤에 붙인다
    (이름보다 짧고, 서머타임이 있는 곳에서도 그 순간의 값이 정확하다)."""
    local = to_tz(dt, tz)
    off = local.strftime('%z') if local is not None else ''
    return 'UTC' + (off[:3] + ':' + off[3:] if off else '+00:00')


def tz_label(tz: Union[str, pytz.BaseTzInfo, None], at: Optional[datetime] = None) -> str:
    """입력 칸 옆에 붙일 '어느 시계인지' — 'Asia/Seoul (UTC+09:00)'."""
    tzinfo = _as_tz(tz)
    name = getattr(tzinfo, 'zone', None) or str(tzinfo)
    return '{} ({})'.format(name, utc_offset_label(at or utc_now(), tzinfo))


def format_labeled(dt: Optional[datetime], tz: Union[str, pytz.BaseTzInfo, None],
                   fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """순간을 tz 시계로 적고 **어느 시계인지**를 붙인다.

    예: '2026-09-21 09:00:00 (Asia/Seoul, UTC+09:00)'. 서로 다른 시간대의
    사람이 같은 글을 읽을 때 라벨 없는 시각은 각자 자기 시각으로 읽힌다.
    naive 는 UTC 로 본다.
    """
    local = to_tz(dt, tz)
    if local is None:
        return ''
    off = local.strftime('%z')
    off = off[:3] + ':' + off[3:] if off else '+00:00'
    name = getattr(local.tzinfo, 'zone', None) or str(local.tzinfo)
    return '{} ({}, UTC{})'.format(local.strftime(fmt), name, off)


# ---------------------------------------------------------------------------
# 집계 창(bucket) ↔ 현지 일자
# ---------------------------------------------------------------------------
#
# InfluxDB(Flux) 의 `aggregateWindow` 는 **UTC 에폭 정렬**이고 기본 라벨이
# `_stop`(구간의 오른쪽 경계)이다. 그래서 `group_sec=86400` 으로 "하루" 를
# 물으면 KST 에서는 09:00~익일 09:00 이 한 칸이 되고, 그 칸에 붙는 날짜는
# **끝날**이다. 값을 합계로만 쓰는 자리(GDD)는 이것이 드러나지 않지만,
# 날짜 라벨을 사람에게 보여주는 자리(일지)는 그대로 쓰면 하루가 밀린다.
#
# 해법은 **시간 단위 창으로 받아 여기서 현지 일자에 접는 것**이다. Flux 에
# `offset`/`timeSrc`/`timezone.location()` 을 얹는 안은 두 이유로 버렸다:
# 이 저장소는 InfluxDB 1.x/2.x 를 모두 지원하는데 그 구문을 쓴 선례가 없고,
# 그러려면 공유 쿼리 빌더(`influx.py`)를 고쳐야 해서 그래프·GDD·runtime 이
# 전부 회귀 표면이 된다.
#
# 접는 쪽을 고른 덕에 **서머타임도 정확해진다** — 각 창을 실제 tz 로 변환해
# 접으므로 전환일의 23시간/25시간짜리 하루가 그대로 맞는다.
#
# 이 헬퍼가 `timekit` 에 있는 이유: `aot/utils/runtime.py`(데몬도 쓰는 저수준
# 모듈)와 `aot/aot_flask/geo/plot_journal.py`(Flask 계층)가 **둘 다** 필요로
# 한다. 한쪽에 두면 다른 쪽이 그것을 임포트하게 되어 계층이 뒤집히고, 실제로
# 순환 임포트가 된다.

def bucket_seconds_for(tz: Union[str, pytz.BaseTzInfo, None],
                       *dates) -> int:
    """현지 자정이 창 경계에 떨어지는 **가장 큰** 창 크기 → 초.

    창은 UTC 에폭 정렬이므로, 창 크기가 그 시간대의 UTC 오프셋을 나누어
    떨어뜨려야 현지 자정이 창 **경계** 위에 온다. 대부분(한국·일본 등)은
    정시 오프셋이라 3600 이면 되고, 인도(+5:30)·네팔(+5:45) 같은 곳만 더
    잘게 썬다. 큰 쪽을 고르는 이유는 반환 행 수가 그만큼 늘기 때문이다.

    기간 안에 서머타임 전환이 있으면 오프셋이 둘이 되므로 **주는 날짜를 전부**
    본다(보통 기간의 시작일과 종료일을 넘긴다).
    """
    tzinfo = _as_tz(tz)
    offsets = set()
    for d in dates:
        if d is None:
            continue
        try:
            off = tzinfo.utcoffset(datetime(d.year, d.month, d.day, 12, 0, 0))
        except Exception:
            continue
        if off is not None:
            offsets.add(int(off.total_seconds()))
    if not offsets:
        return 3600
    for size in (3600, 1800, 900):
        if all(o % size == 0 for o in offsets):
            return size
    return 900


def local_day_bounds_utc(start_date, end_date,
                         tz: Union[str, pytz.BaseTzInfo, None],
                         as_str: bool = True):
    """현지 [시작일 00:00, 종료일 다음날 00:00) → UTC 구간 (반열림).

    **종료일을 포함**하려면 다음날 자정까지 열어야 한다. 같은 구간을 측정값
    조회와 노트 조회가 함께 써야 두 줄이 같은 하루를 말한다.

    `as_str=True`  → InfluxDB 용 RFC3339 문자열 쌍.
    `as_str=False` → **naive UTC datetime** 쌍(=DB 비교용).

    ⚠ naive 로 내는 것이 실수가 아니다. 이 저장소의 시각 컬럼은 **naive UTC**
      로 저장된다(`Notes.date_time` 실측: tzinfo=None, `2026-08-26 08:59:37`).
      tz-aware 값을 그대로 비교에 넣으면 SQLite 가 `+00:00` 이 붙은 문자열로
      렌더해 **조용히 어긋난 비교**를 한다 — 예외가 안 나서 결과가 빈 것을
      "그 기간에 없었다" 로 읽게 된다.
    """
    from datetime import timedelta as _td

    a = wall_to_utc(datetime(start_date.year, start_date.month,
                             start_date.day, 0, 0, 0), tz)
    nxt = end_date + _td(days=1)
    b = wall_to_utc(datetime(nxt.year, nxt.month, nxt.day, 0, 0, 0), tz)
    if as_str:
        return (a.strftime('%Y-%m-%dT%H:%M:%SZ'),
                b.strftime('%Y-%m-%dT%H:%M:%SZ'))
    return a.replace(tzinfo=None), b.replace(tzinfo=None)


def bucket_local_key(rec_time: Optional[datetime], bucket_sec: int,
                     tz: Union[str, pytz.BaseTzInfo, None],
                     granularity: str = 'day'):
    """집계 레코드 하나 → 그것이 속한 현지 버킷 키(date). 못 정하면 None.

    ⚠ **`aggregateWindow` 의 라벨은 구간의 오른쪽 경계(`_stop`)다.** 로컬
      InfluxDB 2.7 에서 원자료와 대조해 확인했다. 그래서 시작 시각으로 되돌린
      다음 시간대를 입힌다 — **이 뺄셈을 빼면 모든 날짜가 하루씩 밀린다.**

    `granularity='week'` 면 그 주의 월요일(현지 기준)을, `'month'` 면 그 달의
    1일을 키로 쓴다.
    """
    from datetime import timedelta as _td

    if rec_time is None:
        return None
    try:
        start = _ensure_utc(rec_time) - _td(seconds=int(bucket_sec))
        local_day = to_tz(start, tz).date()
    except Exception:
        return None
    if granularity == 'week':
        return local_day - _td(days=local_day.weekday())
    if granularity == 'month':
        return local_day.replace(day=1)
    return local_day


def buckets_expected(key, granularity: str,
                     tz: Union[str, pytz.BaseTzInfo, None], bucket_sec: int,
                     period_start=None, period_end=None) -> int:
    """이 버킷이 **원래 몇 개의 창으로 이뤄지는가** → int (커버리지의 분모).

    24 를 상수로 박지 않는 이유가 둘이다.

    - **서머타임**: 전환일은 23시간 또는 25시간이다. 24 로 나누면 그날만
      조용히 틀린 비율이 나온다.
    - **구간 가장자리**: 주간 롤업의 첫 주·마지막 주는 기간에 일부만 걸친다.
      온전한 7일로 나누면 멀쩡한 주가 "절반만 잰" 것으로 보인다.
    """
    from datetime import timedelta as _td

    # 커버리지의 분모는 그 버킷이 **덮는 날 수**다. 달은 28~31 로 제각각이라
    # 상수로 둘 수 없고, 주와 같은 방식으로 실제 날짜를 세어야 한다 — 30 으로
    # 박으면 2월은 늘 100% 를 넘고 1월은 늘 모자란다.
    if granularity == 'week':
        days = [key + _td(days=n) for n in range(7)]
    elif granularity == 'month':
        days = []
        d = key.replace(day=1)
        while d.month == key.month and d.year == key.year:
            days.append(d)
            d += _td(days=1)
    else:
        days = [key]
    total = 0
    for d in days:
        if period_start is not None and d < period_start:
            continue
        if period_end is not None and d > period_end:
            continue
        try:
            a = wall_to_utc(datetime(d.year, d.month, d.day, 0, 0, 0), tz)
            nxt = d + _td(days=1)
            b = wall_to_utc(datetime(nxt.year, nxt.month, nxt.day, 0, 0, 0), tz)
            total += int((b - a).total_seconds() // int(bucket_sec))
        except Exception:
            total += int(86400 // int(bucket_sec))
    return total


# 공개 입구 — 호출부가 쓰는 것은 이 열 둘뿐이다(설계: time_unification_design §2).
PUBLIC_ENTRIES = (
    "utc_now", "naive_utc", "parse_utc", "resolve_tz", "tz_of",
    "to_tz", "iso_utc", "iso_at", "wall_to_utc", "today_at",
    "FARM", "VIEWER",
)

# 입구가 아닌 보조(옛 이름은 S10 에서 삭제했다).
HELPERS = (
    "resolve_coords", "tz_scope",
    "Coords",
    "bucket_seconds_for", "local_day_bounds_utc",
    "bucket_local_key", "buckets_expected",
    "SOURCE_EXPLICIT", "SOURCE_INHERITED", "SOURCE_COORDS",
    "SOURCE_USER", "SOURCE_SYSTEM", "SOURCE_UTC", "SOURCE_DEVICE",
)

__all__ = list(PUBLIC_ENTRIES) + list(HELPERS)
