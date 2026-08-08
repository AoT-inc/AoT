# coding=utf-8
"""장치 배치의 단일 게이트웨이 — 지도에 마커를 놓는 유일한 문.

지도 데이터는 geo 패키지가 소유한다. 장치·AI·위젯 등 다른 도메인의
로직이 GeoShape 를 직접 만들면, 그 도메인이 지도의 불변식을 알아야 하고
결국 아무도 다 알지 못한다 — 2026-08-03 사고의 구조적 원인이 그것이었다
(AI 대량생성이 channel_id 없이 마커를 직접 INSERT 해 첫 위치 저장에서
중복을 만들고, 복제가 남의 지도 링크를 물려받았다).

여기서 강제하는 계약:
  - 마커 종류는 항상 'aot_device' (I1 어휘, I7 불변과 정합)
  - channel_id 는 항상 문자열이며 기본값 '0' — NULL/'0' 비대칭이
    중복 마커의 실제 발생 경로였다(I2 인덱스가 COALESCE 로 접지만,
    애초에 만들지 않는 것이 낫다)
  - feature JSON 에 aot_type 을 넣지 않는다 (I6 — 정본은 type 컬럼)
  - 소속(map_overlay_id)을 쓰지 않는다 — 좌표에서 파생된다
    (device_membership.py)
  - 같은 (지도, 장치, 채널) 마커는 갱신이지 추가가 아니다

CI(aot/scripts/check_geo_writes.py)가 geo 패키지 밖의 GeoShape 쓰기를
거부하므로, 새 코드는 이 문을 지나갈 수밖에 없다.
"""
import logging
from datetime import datetime

from aot.aot_flask.extensions import db
from aot.databases.models import GeoShape

logger = logging.getLogger(__name__)

MARKER_TYPE = 'aot_device'


def _entry_uid(device_id, channel_id):
    """채널 0 은 장치 uuid 그대로, 그 외는 'uuid::N' — 프런트 계약."""
    ch = str(channel_id)
    return device_id if ch == '0' else '%s::%s' % (device_id, ch)


def build_marker_feature(device_id, channel_id, lat, lng,
                         device_type=None, name=None):
    """마커 feature JSON. aot_type 은 넣지 않는다 (I6)."""
    return {
        'type': 'Feature',
        'geometry': {'type': 'Point',
                     'coordinates': [float(lng), float(lat)]},
        'properties': {
            'unique_id': _entry_uid(device_id, channel_id),
            'device_id': device_id,
            'channel_id': str(channel_id),
            'device_type': device_type,
            'name': name or str(device_id),
        },
    }


def place_device(device_id, map_uuid, lat, lng, channel_id=0,
                 device_type=None, name=None, commit=False):
    """장치를 지도에 배치(또는 이동)한다. 마커 GeoShape 를 반환.

    같은 (지도, 장치, 채널) 마커가 있으면 갱신한다 — 추가하지 않는다.
    좌표가 없으면 배치 해제로 간주해 unplace_device 로 위임한다.
    commit=False 가 기본: 호출자의 트랜잭션에 합류한다.
    """
    if not device_id or not map_uuid:
        return None
    if lat is None or lng is None:
        return unplace_device(device_id, map_uuid, channel_id, commit=commit)

    ch = str(channel_id if channel_id is not None else 0)
    marker = GeoShape.query.filter_by(
        geo_id=map_uuid, device_id=device_id, channel_id=ch).first()
    feature = build_marker_feature(device_id, ch, lat, lng,
                                   device_type=device_type, name=name)
    if marker is None:
        marker = GeoShape(geo_id=map_uuid, device_id=device_id,
                          channel_id=ch, type=MARKER_TYPE,
                          feature=feature)   # feature 는 NOT NULL
        db.session.add(marker)
        logger.info('place_device: 마커 생성 device=%s ch=%s map=%s',
                    device_id, ch, map_uuid)
    else:
        marker.feature = feature
        logger.info('place_device: 마커 이동 device=%s ch=%s map=%s',
                    device_id, ch, map_uuid)
    marker.updated_at = datetime.utcnow()
    _record_marker_binding(marker, device_id, ch)
    if commit:
        db.session.commit()
    return marker


def _record_marker_binding(marker, device_id, channel_id):
    """마커 배치를 바인딩에도 남긴다 — 레거시 컬럼 쓰기는 유지한다(Phase C).

    이 호출이 없으면 UI 로 배치할 때마다 `check_geo_integrity` 의
    binding-drift 가 늘어난다. 레거시 저장처에만 있고 바인딩에 없는 연결이
    새로 생기는 것이고, 그건 정확히 Phase C 의 게이팅 신호를 망가뜨리는
    방향이다 — 전환이 진행될수록 드리프트가 줄어야 한다.

    쓰기 실패로 배치 자체를 막지는 않는다. 마커는 이미 레거시 컬럼에
    저장됐고 백필이 나중에 같은 행을 만들 수 있는 반면, 여기서 예외를
    올리면 사용자는 장치를 지도에 놓지 못한다. 대신 **SAVEPOINT 안에서**
    쓴다 — 그냥 삼키면 실패한 flush 가 세션을 오염시킨 채로 남아 뒤이은
    커밋이 무관한 자리에서 죽는다.
    """
    from aot.aot_flask.geo import device_binding

    # 마커 자체의 flush 는 try 밖이다 — 여기서 실패하면 그건 바인딩 문제가
    # 아니라 배치 실패(I2·I8 트리거 등)이고, 삼키면 호출자의 commit 이
    # 무관한 자리에서 죽으면서 로그에는 "바인딩 기록 실패"만 남는다.
    db.session.flush()              # 새 도형의 unique_id 는 flush 때 생긴다
    if not marker.unique_id:
        return

    try:
        kind = device_binding.resolve_device_kind(device_id)
        if kind is None:
            # 실존하지 않는 장치에 바인딩을 만들지 않는다 — 고아를 정본으로
            # 승격시키지 않는 백필과 같은 정책.
            logger.warning('place_device: 장치 %s 를 어느 테이블에서도 찾지 '
                           '못해 바인딩을 남기지 않는다', device_id)
            return
        with db.session.begin_nested():
            device_binding.rebind('shape', marker.unique_id, 'marker',
                                  kind, device_id, channel_id=channel_id)
    except Exception as exc:
        logger.warning('place_device: 바인딩 기록 실패 device=%s ch=%s — %s',
                       device_id, channel_id, exc)


def unplace_device(device_id, map_uuid, channel_id=0, commit=False):
    """지도에서 장치 마커를 제거한다. 없으면 무동작."""
    ch = str(channel_id if channel_id is not None else 0)
    # 삭제 전에 바인딩을 끝낸다 — 행이 사라지면 어느 슬롯이었는지 알 수 없다.
    # 종료 사유는 'spatial_deleted'(도형이 사라진 결과)가 아니라 'unbound'
    # 다: 사람이 "이 지도에서 이 장치를 내린다"고 한 것이고, 마커 삭제는 그
    # 결정의 귀결이다(미배정 마커는 의미가 없다 — 설계의 마커 예외).
    _end_marker_binding(device_id, map_uuid, ch)
    # delete_shape 와 같은 이유로 bulk delete (관계 우회 + 트리거 연쇄).
    n = GeoShape.query.filter_by(
        geo_id=map_uuid, device_id=device_id, channel_id=ch).delete(
            synchronize_session=False)
    if n:
        db.session.expire_all()
        logger.info('unplace_device: 마커 제거 device=%s ch=%s map=%s',
                    device_id, ch, map_uuid)
    if commit:
        db.session.commit()
    return None


def _end_marker_binding(device_id, map_uuid, channel_id):
    """제거될 마커의 현재 바인딩을 종료한다. 실패해도 제거를 막지 않는다."""
    from aot.aot_flask.geo import device_binding

    try:
        markers = GeoShape.query.filter_by(
            geo_id=map_uuid, device_id=device_id, channel_id=channel_id).all()
        uids = [m.unique_id for m in markers if m.unique_id]
        if not uids:
            return
        with db.session.begin_nested():
            for uid in uids:
                row = device_binding.current_one('shape', uid, role='marker')
                if row is not None:
                    device_binding.unbind(row.unique_id, 'unbound')
    except Exception as exc:
        logger.warning('unplace_device: 바인딩 종료 실패 device=%s ch=%s — %s',
                       device_id, channel_id, exc)


def delete_shape(shape_unique_id, commit=False):
    """도형 하나를 unique_id 로 삭제한다. 삭제된 종류를 반환(없으면 None).

    geo 밖 도메인(AI 도구 등)이 도형을 지워야 할 때 쓰는 유일한 문이다.
    단건 삭제만 지원한다 — 레이어/일괄 삭제는 여기로 오지 않는다.
    시설·bay·설정점 연쇄와 장치 소속 해제는 DB 트리거(I3/I4)가 처리하므로
    호출자가 정리 순서를 알 필요가 없다. 그것이 이 문이 존재하는 이유다.

    ORM 삭제(session.delete)를 쓰지 않는 이유: GeoFacility.shape 관계가
    back_populates 로 걸려 있어, 시설이 매달린 도형을 ORM 으로 지우면
    SQLAlchemy 가 먼저 geo_facility.shape_uuid 를 NULL 로 만들려 하고
    NOT NULL 제약에 걸려 죽는다 — 트리거가 동작할 기회조차 없다.
    bulk delete 는 관계 처리를 건너뛰므로 DB 트리거가 연쇄를 완결한다.
    """
    shape = GeoShape.query.filter_by(unique_id=shape_unique_id).first()
    if shape is None:
        return None
    stype = shape.type
    GeoShape.query.filter_by(unique_id=shape_unique_id).delete(
        synchronize_session=False)
    db.session.expire_all()          # bulk delete 후 세션 캐시 무효화
    if commit:
        db.session.commit()
    logger.info('delete_shape: 도형 삭제 uuid=%s type=%s',
                shape_unique_id, stype)
    return stype
