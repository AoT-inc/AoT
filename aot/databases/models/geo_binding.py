# coding=utf-8
from aot.utils.time_utils import utc_now
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class GeoBinding(CRUDMixin, db.Model):
    """공간 요소 ↔ 장치 연결의 유일한 정본 — 이력을 보존하는 관계 테이블.

    고정 자산(지형·시설·구역, 수명 수십 년)이 유동 자산(장치, 수명 몇 년)의
    uuid 를 자기 몸에 새기고 있는 것이 이 도메인의 구조적 약점이었다. 장치를
    지우면 도형이 고아가 되거나 함께 사라지고, 장치를 교체하면 도형을 다시
    그려야 하고, 장치를 갈면 시계열이 끊긴다. 같은 사실이 6곳에 흩어져 있어
    어느 삭제 경로도 전부를 정리하지 못했다(설계: docs/design/geo-device-binding.md).

    이 테이블은 그 연결을 한 곳으로 모은다. 공간 요소는 장치 없이 완결적으로
    존재하고(미배정 슬롯), 장치 삭제·교체는 **바인딩의 종료**이지 공간 요소의
    삭제가 아니다. 그래서 "장치를 지울 때 도형을 같이 지울까 남길까"라는
    질문 자체가 성립하지 않게 된다.

    `DeviceMember` 와 같은 성격이다 — 어느 쪽의 수명도 소유하지 않는 참조
    관계이며, 활성화 cascade 에 관여하지 않는다.

    ## 이력 (valid_from / valid_to)

    바인딩은 지워지지 않고 끝난다. `valid_to IS NULL` 이 현재 유효한 바인딩
    이고, 종료된 행은 "이 슬롯을 언제 어떤 장치가 맡았나"의 답으로 남는다.
    이 이력이 곧 장치 교체를 관통하는 시계열 접합의 근거다 — InfluxDB 태그는
    device_id 그대로 두고(과거 데이터 재작성 금지), 조회 시점에 구간별로
    이어 붙인다.

    ## 슬롯 점유 수

    `shape`/`fitting`/`actuator` 는 단일 점유다 — 한 창을 두 모터가 열지
    않는다. 반면 `sensor_role`/`weather` 는 **다중 점유가 정상**이다:
    GeoFacility.sensors 는 같은 role 에 여러 장치를 등록해 가중평균하도록
    설계돼 있다. 그래서 GB-1 유일성 인덱스가 두 벌로 갈린다
    (geo_integrity_ddl.BINDING_STATEMENTS). 일괄 적용하면 정상 기능이
    DB 에서 거부된다.

    @phase active
    @stability experimental
    @dependency GeoShape, GeoFacility, Input, Output, CustomController
    """
    __tablename__ = "geo_binding"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True,
                          default=set_uuid)

    # ── 공간 측 ────────────────────────────────────────────────────────
    # 'shape' | 'fitting' | 'actuator' | 'sensor_role' | 'weather'
    # fitting 과 actuator 는 같은 시설의 서로 다른 JSON 컬럼이고 키 이름도
    # 다르다(fittings[].actuator_id vs actuators[].device_uuid). 합치지 말 것.
    spatial_kind = db.Column(db.String(16), nullable=False, index=True)

    # shape       → GeoShape.unique_id
    # fitting     → GeoFacility.unique_id + ':' + fittings[].id
    # actuator    → GeoFacility.unique_id + ':' + actuators[].id
    # sensor_role → GeoFacility.unique_id
    # weather     → GeoFacility.unique_id
    # 양쪽 모두 unique_id(문자열)로만 가리킨다. 정수 PK 참조 금지 —
    # map_overlay_id 가 정확히 그 방식으로 썩었다(재생성이 id 를 바꾸면
    # 참조가 끊긴다). 사문 모델 MapDependency 도 같은 실수를 했다.
    spatial_id = db.Column(db.String(64), nullable=False, index=True)

    # shape: 'marker'|'area' / fitting: 'actuator'|'sensor' /
    # actuator: 'actuator' / sensor_role: sensors[].role 어휘 /
    # weather: weather_bindings[].measurement_type 어휘
    role = db.Column(db.String(32), nullable=False)

    # ── 장치 측 ────────────────────────────────────────────────────────
    # geo_integrity_ddl.DEVICE_LINK_TABLES 와 같은 7종. 마커는 Function·PID·
    # Trigger 에도 붙으므로(place_device) input/output/device 3종으로 좁히면
    # 백필이 나머지를 조용히 버린다.
    device_kind = db.Column(db.String(16), nullable=False)
    device_id = db.Column(db.String(36), nullable=False, index=True)
    # NULL 금지 — NULL/'0' 비대칭이 중복 마커의 실제 발생 경로였다(I2).
    channel_id = db.Column(db.String(8), nullable=False, default='0')
    # DeviceMeasurements.unique_id. "이 장치의 이 측정값"까지가 바인딩 대상
    # 이므로 params 가 아니라 1급 컬럼이다 — 다중 점유 유일성이 이 값을 본다.
    measurement_id = db.Column(db.String(36), nullable=True)

    # ── 수명 ───────────────────────────────────────────────────────────
    valid_from = db.Column(db.DateTime, nullable=False, default=utc_now)
    valid_to = db.Column(db.DateTime, nullable=True, default=None)
    # 'replaced' | 'device_deleted' | 'unbound' | 'spatial_deleted'
    ended_reason = db.Column(db.String(16), nullable=True, default=None)

    # 역할별 나머지 파라미터 (sensor_role: weight / weather: max_age_sec)
    params = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=utc_now)

    @property
    def is_current(self):
        return self.valid_to is None

    def __repr__(self):
        state = 'current' if self.valid_to is None else self.ended_reason
        return "<GeoBinding({0}:{1}/{2} -> {3}:{4} [{5}])>".format(
            self.spatial_kind, self.spatial_id, self.role,
            self.device_kind, self.device_id, state)
