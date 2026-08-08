# coding=utf-8
"""지도 데이터 불변식의 DB 계층 강제 DDL (SQLite 트리거 + 부분 유니크 인덱스).

왜 트리거인가: 앱 계층 가드는 다음 코드 경로가 우회하면 끝난다 — 2026-08-03
사고의 오염원 24건 중 12건이 ORM 이벤트도 거치지 않는 bulk delete / 원시 SQL
이었고, AI 대량생성은 GeoShape 를 직접 INSERT 했다. 트리거는 ORM·원시 SQL·
alembic·복제·대량생성 어떤 경로든 통과하지 못한다. 또한 SQLite 에서 기존
테이블에 FK/CHECK 를 새로 다는 것과 달리 테이블 재구축이 필요 없고,
`PRAGMA foreign_keys=ON` 전역 스위치와 달리(geo 와 무관한 widget→tab 유령
위반 48~51건/서버가 함께 터진다) geo 불변식만 선별 강제한다.

불변식 정의와 단계 구분은 docs/design/geo-data-integrity.md 가 정본.
각 불변식은 aot/tests/geo/test_geo_invariants_attack.py 가 원시 SQL 로
우회 공격해 차단을 검증한다.

Tier-1 (I1~I5): 현재 데이터·현재 앱 코드와 즉시 호환. 사전 정리는 마커
  중복(I2 인덱스 생성 전) 하나뿐.
Tier-2 (I6~I8): 앱 수정(저장 시 aot_type 제거, 라벨 되먹임 절단, 필지
  가져오기의 유령 지도)이 선행돼야 켤 수 있다 — 먼저 켜면 정상 기능이 막힌다.

재귀 주의: 트리거 본문은 `recursive_triggers` OFF(기본값)에서 동작하도록
평탄화돼 있다. 도형 삭제 트리거(I3)가 bay 를 지울 때 자기 자신은 재발화하지
않지만, bay 는 시설·하위 도형·map_overlay_id 참조 대상이 아니므로 안전하다.
지도 삭제 트리거(I5)는 도형 삭제에 의존하지 않고 자체적으로 전부 정리한다.

모든 오류 메시지는 'GEO-I<n>' 태그를 포함한다 — 로그에서 어느 불변식이
막았는지 즉시 식별하기 위함이다.
"""

# geo_shape.type 에 허용되는 전체 어휘. 프런트 typesToSync 의
# infra_blob/reference 까지 포함한다 — 화이트리스트가 실사용 어휘보다 좁으면
# 정상 저장이 막히므로, 이 목록의 변경은 설계 문서와 함께 갱신할 것.
VALID_SHAPE_TYPES = (
    'site', 'zone', 'facility', 'facility_bay', 'aot_device', 'device',
    'label_aux', 'equipment', 'equipment_collection', 'feature',
    'infra_blob', 'reference',
)

# map_overlay_id / map_config_id 를 가진 테이블 전부. 하나라도 빠지면 그
# 테이블의 참조가 조용히 썩는다(2026-08-03: 이 목록을 안 보고 도형을 지워
# 참조 11건이 끊겼다). "trigger"/"function" 은 SQL 예약어라 전부 인용한다.
DEVICE_LINK_TABLES = (
    'input', 'output', 'pid', 'trigger', 'conditional',
    'custom_controller', 'function',
)

_TYPES_SQL = ', '.join("'%s'" % t for t in VALID_SHAPE_TYPES)


def _drop(name, kind='TRIGGER'):
    return 'DROP %s IF EXISTS %s' % (kind, name)


# ---------------------------------------------------------------------------
# Tier-1
# ---------------------------------------------------------------------------

TIER1_STATEMENTS = []

# I1 — type 화이트리스트. default='feature' 조용한 폴백 자체는 스키마
# 기본값이라 여기서 못 없애지만, 어휘 밖 쓰레기 값은 이 자리에서 죽는다.
for _when, _suffix in (('INSERT', 'ins'), ('UPDATE OF type', 'upd')):
    TIER1_STATEMENTS += [
        _drop('geo_itg_i1_%s' % _suffix),
        """
        CREATE TRIGGER geo_itg_i1_{suffix}
        BEFORE {when} ON geo_shape
        WHEN NEW.type NOT IN ({types})
        BEGIN
            SELECT RAISE(ABORT, 'GEO-I1: geo_shape.type 허용값 아님');
        END
        """.format(when=_when, suffix=_suffix, types=_TYPES_SQL),
    ]

# I2 — 장치 위치 마커는 (지도, 장치, 채널)당 1개.
# COALESCE 식 인덱스: channel_id 가 INSERT 경로에선 NULL, UPDATE 경로에선
# '0' 으로 갈리는 비대칭(geo_overlays.py:379 vs :359)이 중복 마커를 만들어
# 왔다. NULL 과 '0' 을 같은 키로 접어서 그 구멍을 봉쇄한다.
# type='aot_device' 로 한정: 그려진 구역(type='device' 폴리곤)은 한 장치에
# 여러 개가 정당하다(밸브 하나가 두 구역에 관수). 위치 점만 유일해야 하고,
# S3 의 map_overlay_id 파생 전환이 정확히 이 유일성 위에 선다.
TIER1_STATEMENTS += [
    _drop('geo_itg_i2_marker_unique', 'INDEX'),
    """
    CREATE UNIQUE INDEX geo_itg_i2_marker_unique
    ON geo_shape (geo_id, device_id, COALESCE(channel_id, '0'))
    WHERE device_id IS NOT NULL AND type = 'aot_device'
    """,
]

# I3 — 도형 삭제 → 시설·설정점·bay 연쇄 정리.
# 기존에는 삭제 12경로 중 3곳만 _cascade_delete_facilities_for_shapes 를
# 호출했다. 트리거는 경로를 가리지 않는다.
TIER1_STATEMENTS += [
    _drop('geo_itg_i3_shape_cascade'),
    """
    CREATE TRIGGER geo_itg_i3_shape_cascade
    AFTER DELETE ON geo_shape
    BEGIN
        DELETE FROM geo_facility_setpoint
         WHERE facility_uuid IN (SELECT unique_id FROM geo_facility
                                  WHERE shape_uuid = OLD.unique_id);
        DELETE FROM geo_facility WHERE shape_uuid = OLD.unique_id;
        DELETE FROM geo_shape
         WHERE parent_id = OLD.id AND type = 'facility_bay';
    END
    """,
]

# I4 — 도형 삭제 → 그 도형을 가리키던 장치 소속(map_overlay_id) NULL.
# ON DELETE SET NULL 에뮬레이션. 기존에는 이걸 하는 경로가 0곳이었다.
_i4_updates = '\n'.join(
    '        UPDATE "{t}" SET map_overlay_id = NULL '
    'WHERE map_overlay_id = OLD.id;'.format(t=t)
    for t in DEVICE_LINK_TABLES)
TIER1_STATEMENTS += [
    _drop('geo_itg_i4_overlay_setnull'),
    """
    CREATE TRIGGER geo_itg_i4_overlay_setnull
    AFTER DELETE ON geo_shape
    BEGIN
{updates}
    END
    """.format(updates=_i4_updates),
]

# I5 — 지도 삭제 → 도형·시설·설정점 정리 + 장치의 map_config_id/
# map_overlay_id 해제. 도형 삭제 트리거 연쇄에 의존하지 않고 자체 완결로
# 처리한다(재귀 제한 회피 + geo_design.py:144 같은 무가드 경로도 커버).
_i5_config_null = '\n'.join(
    '        UPDATE "{t}" SET map_config_id = NULL '
    'WHERE map_config_id = OLD.unique_id;'.format(t=t)
    for t in DEVICE_LINK_TABLES)
_i5_overlay_null = '\n'.join(
    '        UPDATE "{t}" SET map_overlay_id = NULL WHERE map_overlay_id IN '
    '(SELECT id FROM geo_shape WHERE geo_id = OLD.unique_id);'.format(t=t)
    for t in DEVICE_LINK_TABLES)
TIER1_STATEMENTS += [
    _drop('geo_itg_i5_map_cascade'),
    """
    CREATE TRIGGER geo_itg_i5_map_cascade
    AFTER DELETE ON geo_map
    BEGIN
{overlay_null}
{config_null}
        DELETE FROM geo_facility_setpoint
         WHERE facility_uuid IN (SELECT unique_id FROM geo_facility
                                  WHERE geo_id = OLD.unique_id);
        DELETE FROM geo_facility WHERE geo_id = OLD.unique_id;
        DELETE FROM geo_shape WHERE geo_id = OLD.unique_id;
    END
    """.format(overlay_null=_i5_overlay_null, config_null=_i5_config_null),
]


# ---------------------------------------------------------------------------
# Tier-2 — 앱 수정 선행 필수 (게이팅 조건은 설계 문서 참조)
# ---------------------------------------------------------------------------

TIER2_STATEMENTS = []

# I6 — 저장된 JSON 에 aot_type 키 자체가 존재 불가.
# '드리프트를 검사'하는 게 아니라 '두 번째 사본을 표현 불가능하게' 만든다.
# 켜기 전 조건: 서버가 저장 직전 properties.aot_type 을 제거해야 한다(S4).
for _when, _suffix in (('INSERT', 'ins'), ('UPDATE OF feature', 'upd')):
    TIER2_STATEMENTS += [
        _drop('geo_itg_i6_%s' % _suffix),
        """
        CREATE TRIGGER geo_itg_i6_{suffix}
        BEFORE {when} ON geo_shape
        WHEN json_extract(NEW.feature, '$.properties.aot_type') IS NOT NULL
        BEGIN
            SELECT RAISE(ABORT,
                'GEO-I6: feature JSON 에 aot_type 저장 금지 (type 컬럼이 정본)');
        END
        """.format(when=_when, suffix=_suffix),
    ]

# I7 — type 은 생성 후 불변. 라벨 이름 변경 되먹임 고리(GET 정규화 →
# /delta 재전송 → row.type 덮어쓰기 → 다음 저장에서 이중화)의 마지막 봉인.
# 켜기 전 조건: /delta 가 클라이언트 aot_type 으로 기존 행을 재분류하지
# 않도록 수정(S4). 종류를 바꾸려면 삭제 후 생성.
TIER2_STATEMENTS += [
    _drop('geo_itg_i7_type_immutable'),
    """
    CREATE TRIGGER geo_itg_i7_type_immutable
    BEFORE UPDATE OF type ON geo_shape
    WHEN NEW.type IS NOT OLD.type
    BEGIN
        SELECT RAISE(ABORT, 'GEO-I7: type 은 불변 — 종류 변경은 삭제 후 생성');
    END
    """,
]

# I8 — 유령 지도 금지. '__parcel_import__' 센티널처럼 실존하지 않는
# geo_id 아래 도형을 만들면 어떤 삭제 경로로도 회수되지 않는 영구 누수가 된다.
# 켜기 전 조건: 필지 가져오기가 실존 지도를 요구하도록 수정(S4).
for _when, _suffix in (('INSERT', 'ins'), ('UPDATE OF geo_id', 'upd')):
    TIER2_STATEMENTS += [
        _drop('geo_itg_i8_%s' % _suffix),
        """
        CREATE TRIGGER geo_itg_i8_{suffix}
        BEFORE {when} ON geo_shape
        WHEN NOT EXISTS (SELECT 1 FROM geo_map
                          WHERE unique_id = NEW.geo_id)
        BEGIN
            SELECT RAISE(ABORT, 'GEO-I8: 실존하지 않는 지도(geo_id)');
        END
        """.format(when=_when, suffix=_suffix),
    ]


# ---------------------------------------------------------------------------
# 공간-장치 바인딩 (GB-1, GB-2) — docs/design/geo-device-binding.md
#
# geo_binding 테이블 전용. Tier-1/2 와 분리한 이유: 그 둘은 geo_shape/geo_map
# 이 있는 모든 설치에 적용되지만, 이쪽은 p6_27 이후에만 테이블이 존재한다.
# 섞으면 테이블 없는 설치에서 Tier-1 전체가 죽는다.
# ---------------------------------------------------------------------------

# spatial_kind 어휘. 인벤토리 6곳 중 저장처가 다른 것마다 하나씩이며,
# fitting(fittings[].actuator_id/input_id)과 actuator(actuators[].device_uuid)
# 는 같은 시설의 다른 JSON 컬럼이라 합치지 않는다.
VALID_SPATIAL_KINDS = ('shape', 'fitting', 'actuator', 'sensor_role', 'weather')

# device_kind 어휘 = DEVICE_LINK_TABLES 와 같은 7종('device' = custom_controller).
# 마커는 Function·PID·Trigger 에도 붙으므로 좁히면 백필이 조용히 버린다.
VALID_DEVICE_KINDS = ('input', 'output', 'device', 'function', 'pid',
                      'trigger', 'conditional')

VALID_END_REASONS = ('replaced', 'device_deleted', 'unbound', 'spatial_deleted')

# 단일 점유 — 한 창을 두 모터가 열지 않는다.
SINGLE_OCCUPANCY_KINDS = ('shape', 'fitting', 'actuator')
# 다중 점유 — GeoFacility.sensors 는 같은 role 에 여러 장치를 등록해
# 가중평균하도록 설계돼 있다(모델 주석). 단일 규칙을 일괄 적용하면 정상
# 기능을 DB 가 거부한다. 다만 같은 (장치, 채널, 측정값)의 중복 등록은 막는다.
MULTI_OCCUPANCY_KINDS = ('sensor_role', 'weather')

_SPATIAL_SQL = ', '.join("'%s'" % k for k in VALID_SPATIAL_KINDS)
_DEVICE_SQL = ', '.join("'%s'" % k for k in VALID_DEVICE_KINDS)
_REASON_SQL = ', '.join("'%s'" % k for k in VALID_END_REASONS)
_SINGLE_SQL = ', '.join("'%s'" % k for k in SINGLE_OCCUPANCY_KINDS)
_MULTI_SQL = ', '.join("'%s'" % k for k in MULTI_OCCUPANCY_KINDS)

BINDING_STATEMENTS = [
    # GB-1a — 단일 점유 슬롯의 현재 바인딩은 1개.
    _drop('geo_itg_gb1_single_current', 'INDEX'),
    """
    CREATE UNIQUE INDEX geo_itg_gb1_single_current
    ON geo_binding (spatial_kind, spatial_id, role, channel_id)
    WHERE valid_to IS NULL AND spatial_kind IN ({single})
    """.format(single=_SINGLE_SQL),

    # GB-1b — 다중 점유 슬롯은 같은 (장치, 채널, 측정값)의 중복만 막는다.
    # COALESCE: measurement_id 가 NULL 인 행끼리도 중복 판정 대상이 되도록
    # (SQLite 는 NULL 을 서로 다른 값으로 보므로 그냥 두면 무제한 중복).
    _drop('geo_itg_gb1_multi_current', 'INDEX'),
    """
    CREATE UNIQUE INDEX geo_itg_gb1_multi_current
    ON geo_binding (spatial_kind, spatial_id, role, device_id, channel_id,
                    COALESCE(measurement_id, ''))
    WHERE valid_to IS NULL AND spatial_kind IN ({multi})
    """.format(multi=_MULTI_SQL),
]

# GB-2 — 수명 정합 + 어휘. INSERT 와 UPDATE 양쪽에 건다.
for _when, _suffix in (('INSERT', 'ins'), ('UPDATE', 'upd')):
    BINDING_STATEMENTS += [
        _drop('geo_itg_gb2_%s' % _suffix),
        """
        CREATE TRIGGER geo_itg_gb2_{suffix}
        BEFORE {when} ON geo_binding
        BEGIN
            SELECT CASE
              WHEN NEW.spatial_kind NOT IN ({spatial})
                THEN RAISE(ABORT, 'GEO-GB2: spatial_kind 허용값 아님')
              WHEN NEW.device_kind NOT IN ({device})
                THEN RAISE(ABORT, 'GEO-GB2: device_kind 허용값 아님')
              WHEN NEW.channel_id IS NULL
                THEN RAISE(ABORT, 'GEO-GB2: channel_id 는 NULL 금지')
              WHEN NEW.valid_to IS NOT NULL AND NEW.ended_reason IS NULL
                THEN RAISE(ABORT, 'GEO-GB2: 종료된 바인딩은 ended_reason 필수')
              WHEN NEW.ended_reason IS NOT NULL
                   AND NEW.ended_reason NOT IN ({reason})
                THEN RAISE(ABORT, 'GEO-GB2: ended_reason 허용값 아님')
              WHEN NEW.valid_to IS NOT NULL AND NEW.valid_to < NEW.valid_from
                THEN RAISE(ABORT, 'GEO-GB2: valid_to 가 valid_from 보다 이르다')
            END;
        END
        """.format(when=_when, suffix=_suffix, spatial=_SPATIAL_SQL,
                   device=_DEVICE_SQL, reason=_REASON_SQL),
    ]


def apply_binding(connection):
    """GB-1·GB-2 를 적용한다(멱등). geo_binding 테이블이 있어야 한다 —
    없으면 조용히 건너뛴다(테이블 생성은 p6_27 마이그레이션의 몫)."""
    if not _table_exists(connection, 'geo_binding'):
        return False
    _run_all(connection, BINDING_STATEMENTS)
    return True


def _table_exists(connection, name):
    sql = ("SELECT name FROM sqlite_master "
           "WHERE type='table' AND name='%s'" % name)
    exec_fn = getattr(connection, 'exec_driver_sql', None)
    if exec_fn is None:                      # sqlite3.Connection
        exec_fn = connection.execute
    return exec_fn(sql).fetchone() is not None


def apply_tier1(connection):
    """Tier-1 강제를 적용한다(멱등). connection 은 raw DB-API 커서를 만들 수
    있는 sqlite3.Connection 또는 SQLAlchemy Connection."""
    _run_all(connection, TIER1_STATEMENTS)


def apply_tier2(connection):
    """Tier-2 강제를 적용한다(멱등). 게이팅 조건(S4) 충족 후에만 호출할 것."""
    _run_all(connection, TIER2_STATEMENTS)


def remove_all(connection):
    """모든 geo 무결성 트리거·인덱스를 제거한다(롤백용)."""
    names = []
    for stmts in (TIER1_STATEMENTS, TIER2_STATEMENTS, BINDING_STATEMENTS):
        for s in stmts:
            if s.startswith('DROP '):
                names.append(s)
    _run_all(connection, names)


def _run_all(connection, statements):
    exec_fn = getattr(connection, 'exec_driver_sql', None)
    if exec_fn is None:                      # sqlite3.Connection
        exec_fn = connection.execute
    for stmt in statements:
        exec_fn(stmt)
