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
    """마커 feature JSON.

    구조 필드는 넣지 않는다: `aot_type`(I6 — 정본은 type 컬럼),
    `device_id`/`channel_id`(GB-5 — 정본은 geo_binding, 읽기 시
    `get_overlays` 가 주입). 저장된 사본이 남아 있으면 도형 복제나 옛
    페이로드 재전송이 죽은 참조를 되살린다.

    `unique_id` 는 남는다 — 사본이 아니라 프런트가 엔트리를 식별하는
    계약이다(채널 0 = 장치 uuid, 그 외 'uuid::N'). 서버가 조용히 비우면
    지도·위젯의 엔트리 식별이 통째로 깨진다(GB-5b, 별도 게이팅).
    """
    return {
        'type': 'Feature',
        'geometry': {'type': 'Point',
                     'coordinates': [float(lng), float(lat)]},
        'properties': {
            'unique_id': _entry_uid(device_id, channel_id),
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


def move_device_markers(device_id, lat, lng, commit=False):
    """장치 좌표가 바뀌었을 때 그 장치의 마커를 따라 옮긴다. 옮긴 개수 반환.

    장치 설정에서 위도·경도를 고치는 경로(설정 폼·AI 편집)가 쓴다. 예전에는
    그 경로가 `GeoShape.query.filter_by(device_id=...)` 로 도형을 직접 찾아
    `feature['geometry']` 를 제자리에서 고쳤다 — 지도 데이터의 내부 구조를
    장치 도메인이 알고 있었다는 뜻이고, 마커 하나만 고쳐서 다중 채널·다중
    지도에 걸친 나머지는 그대로 남았다.

    `place_device` 와 다르다: 저쪽은 "이 지도의 이 자리에 놓는다"이고 이쪽은
    "이미 놓인 것들을 새 좌표로 따라오게 한다"다. 어느 지도에 몇 개가 놓여
    있는지는 호출자가 알 필요가 없다.
    """
    from aot.aot_flask.geo import device_binding

    if lat is None or lng is None:
        return 0

    moved = 0
    for shape in device_binding.shapes_for_device(device_id, role='marker'):
        feat = shape.feature
        if not isinstance(feat, dict):
            continue
        geom = feat.get('geometry')
        if not isinstance(geom, dict) or geom.get('type') != 'Point':
            continue
        # ORM 이 들고 있는 dict 를 제자리에서 고치지 않는다 — JSON 컬럼은
        # Mutable 래퍼가 없어 제자리 변경을 SQLAlchemy 가 추적하지 못한다.
        new_feat = dict(feat)
        new_geom = dict(geom)
        new_geom['coordinates'] = [float(lng), float(lat)]
        new_feat['geometry'] = new_geom
        shape.feature = new_feat
        shape.updated_at = datetime.utcnow()
        moved += 1

    if moved:
        logger.info('move_device_markers: device=%s 마커 %d개 이동',
                    device_id, moved)
        if commit:
            db.session.commit()
    return moved


def sync_device_name(device_id, new_name, channel_id=None, commit=True):
    """장치 이름이 바뀌면 그 장치 도형의 표시 이름도 따라간다. 갱신 개수 반환.

    도형 JSON 을 고치는 일이라 geo 패키지가 소유한다 — 예전에는
    `utils_general` 이 GeoShape 를 직접 조회해 feature 를 고쳤다.

    ⚠ 마커에만 적용할지 구역까지 적용할지는 미결이다(설계 문서 「미결」 3번).
    현재는 예전 동작 그대로 **양쪽 다** 갱신한다. "공간이 정본"이라는 B1 의
    귀결은 사람이 지은 슬롯 이름을 보존하는 쪽이지만, 그 전환은 이름을 새로
    지을 UI 와 함께 가야 한다 — 여기서 조용히 바꾸면 기존 도형 이름이 전부
    장치 이름으로 덮인 채 되돌릴 방법이 없다.
    """
    from aot.aot_flask.geo import device_binding

    if not device_id or not new_name:
        return 0

    updated = 0
    for shape in device_binding.shapes_for_device(device_id,
                                                  channel_id=channel_id):
        feat = shape.feature
        if not isinstance(feat, dict) or 'properties' not in feat:
            continue
        new_feat = dict(feat)
        props = dict(new_feat.get('properties') or {})
        if props.get('name') == new_name:
            continue
        props['name'] = new_name
        new_feat['properties'] = props
        shape.feature = new_feat
        updated += 1

    if updated and commit:
        db.session.commit()
    return updated


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
