# -*- coding: utf-8 -*-
from datetime import datetime

from flask import current_app
from sqlalchemy import inspect, text

from aot.aot_flask.extensions import db
from aot.databases import set_uuid
from aot.databases.models import GeoMap, GeoShape


def _generate_map_name(base_name):
    base = base_name or "Device"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return f"{base} Map ({timestamp})"




def ensure_map_config(map_config_uuid, device_name=None, latitude=None, longitude=None):
    """[P1 이후 사망] 호출자 없음 — 새로 부르지 말 것.

    "장치가 지도를 소유한다"는 초기 모델의 함수다. site/facility 도입으로
    위치의 정본이 지리요소로 옮겨간 뒤에도 남아, 장치 생성·수정은 물론
    **GET 페이지 렌더에서도** 지도를 만들어 커밋했다. 그렇게 생긴 지도의
    91%가 도형 0 이었다(2026-08-04 운영 3서버 실측).

    지도는 사용자가 명시적으로 만들고, 장치는 배치될 때 지도에 속한다.
    소속 조회는 aot/aot_flask/geo/device_membership.py 가 정본이다.
    docs/design/geo-data-integrity.md "지도 소유권 모델" 참조.
    P5 에서 map_config_id 컬럼과 함께 제거한다.
    """
    if map_config_uuid:
        existing = GeoMap.query.filter_by(unique_id=map_config_uuid).first()
        if existing:
            return existing
    return create_map_config(device_name, latitude, longitude)


def create_map_config(device_name=None, latitude=None, longitude=None):
    """[P1 이후 사망] 장치 전용 지도 팩토리 — 호출자 없음.

    ensure_map_config / clone_map_config 의 종착지였다. 지도는 이제
    사용자가 명시적으로 만든다(원칙 4). P5 에서 제거.
    """
    map_name = _generate_map_name(device_name)
    map_cfg = GeoMap(
        name=map_name,
        category='device',  # [Fix] Explicitly set category to avoid polluting Design list
        latitude=latitude,
        longitude=longitude,
        is_device_owned=True
    )
    db.session.add(map_cfg)
    db.session.flush()
    current_app.logger.debug("Created dedicated map %s for %s", map_cfg.unique_id, device_name)
    return map_cfg


def clone_map_config(source_map_uuid, new_device_name=None):
    """[P1 이후 사망] 장치 복제 시 지도까지 복제하던 함수 — 호출자 없음.

    복제본은 미배치로 시작한다(원칙 2). 원본이 공유 디자인 지도에
    배치돼 있으면 그 도형 전체를 숨은 사설 지도로 복사하던 경로이기도
    했다. P5 에서 제거.
    """
    source = GeoMap.query.filter_by(unique_id=source_map_uuid).first()
    if not source:
        return create_map_config(new_device_name)
    cloned = GeoMap(
        name=_generate_map_name(new_device_name or source.name),
        category='device',  # [Fix] Explicitly set category
        latitude=source.latitude,
        longitude=source.longitude,
        zoom=source.zoom,
        provider=source.provider,
        style_url=source.style_url,
        api_key=source.api_key,
        use_satellite=source.use_satellite,
        providers=source.providers,
        map_locked=source.map_locked,
        is_device_owned=True
    )
    db.session.add(cloned)
    db.session.flush()

    # ── 지도 구조만 복제한다 (장치 배치는 복제하지 않는다) ──────────────────
    # device_id 를 가진 도형(장치 위치 마커, 그려진 장치 구역)은 제외한다.
    # 복제된 지도는 '다른' 장치를 위한 것인데 원본 장치의 마커를 그대로
    # 가져오면 그 장치가 두 지도에 존재하게 된다(2026-08-04 확인). 복제본은
    # 미배치로 시작하고 사용자가 새로 배치한다 — S5 게이트웨이 원칙과 동일.
    source_overlays = [
        s for s in GeoShape.query.filter_by(geo_id=source_map_uuid).all()
        if not s.device_id]

    # node_id 는 지도마다 새로 발급한다. 그대로 복사하면 지도 간 중복이 생겨
    # save_delta 의 node_id 폴백 조회(첫 일치 채택)가 엉뚱한 지도의 도형을
    # 편집할 수 있다. 라벨의 parent_node_id 도 새 값으로 함께 재매핑한다.
    node_remap = {}
    for overlay in source_overlays:
        old_nid = ((overlay.feature or {}).get('properties') or {}).get('node_id')
        if old_nid:
            node_remap[old_nid] = set_uuid()

    # 1패스: 도형을 만들고 원본 id → 새 행 매핑을 남긴다.
    id_remap = {}
    for overlay in source_overlays:
        duplicated_feature = overlay.feature.copy() if overlay.feature else {}
        props = dict(duplicated_feature.get('properties') or {})
        props['map_id'] = cloned.unique_id
        if props.get('node_id') in node_remap:
            props['node_id'] = node_remap[props['node_id']]
        if props.get('parent_node_id') in node_remap:
            props['parent_node_id'] = node_remap[props['parent_node_id']]
        duplicated_feature['properties'] = props

        # `type` must be carried over: it is what get_overlays() filters on
        # (site/zone/facility/aot_device/...). Omitting it fell back to the
        # column default 'feature', so every shape in a cloned map became
        # invisible to the map widget and the design editor alike.
        new_shape = GeoShape(geo_id=cloned.unique_id,
                             type=overlay.type,
                             channel_id=overlay.channel_id,
                             layer_group=overlay.layer_group,
                             sort_order=overlay.sort_order,
                             meta_json=overlay.meta_json,
                             feature=duplicated_feature)
        db.session.add(new_shape)
        id_remap[overlay.id] = new_shape

    # 2패스: parent_id 를 새 지도의 id 로 다시 건다. 그대로 복사하면 원본
    # 지도의 행을 가리키고, 빠뜨리면 계층이 평탄화돼 facility_bay 가 부모를
    # 잃고 영구히 도달 불가능해진다(facility_io 는 parent_id 로 bay 를 찾는다).
    if id_remap:
        db.session.flush()          # 새 행의 id 확보
        for overlay in source_overlays:
            if not overlay.parent_id:
                continue
            new_parent = id_remap.get(overlay.parent_id)
            if new_parent is not None:
                id_remap[overlay.id].parent_id = new_parent.id

    current_app.logger.debug(
        "Cloned map %s -> %s (도형 %d, 장치 배치 제외)",
        source_map_uuid, cloned.unique_id, len(source_overlays))
    return cloned


def _map_still_referenced(map_config_uuid):
    """Return the (model, name) of any device still pointing at this map.

    Every controller type carries its own `map_config_id`, so a map is only
    disposable once no device references it any more.
    """
    # [P1] Function 이 빠져 있었다 — geo_integrity_ddl.DEVICE_LINK_TABLES 는
    # 7개인데 여기만 6개라, Function 이 참조 중인 지도를 다른 장치 삭제가
    # 지울 수 있었다. 목록 누락은 이 도메인의 반복 실패 유형이다.
    from aot.databases.models import (
        Input, Output, PID, Trigger, Conditional, CustomController, Function)

    for model in (Input, Output, PID, Trigger, Conditional, CustomController,
                  Function):
        if not hasattr(model, 'map_config_id'):
            continue
        row = model.query.filter_by(map_config_id=map_config_uuid).first()
        if row:
            return model.__name__, getattr(row, 'name', None)
    return None


def delete_map_config(map_config_uuid):
    """Delete a device-owned map and its overlays.

    Refuses to touch shared maps. A device's `map_config_id` does NOT imply
    ownership: the device settings page offers every non-device-owned map
    (i.e. the user's design maps) as a target so a device can be placed on
    the shared site map, and picking one stores that map's uuid here. Deleting
    the device then used to wipe the whole design map -- every shape plus the
    GeoMap row itself -- because this function trusted the uuid blindly.
    That is exactly how the '임실군' design map (62 shapes) was destroyed on
    aot-004 (2026-08-03) by deleting a single duplicate output, and it is a
    different code path from the save_overlays empty-delete guard added in
    e064f28, which is why that fix did not cover this.

    Two independent conditions must hold before anything is deleted:
      1. the map is device-owned (never a design/shared map), and
      2. no other device still references it.
    """
    if not map_config_uuid:
        return

    map_cfg = GeoMap.query.filter_by(unique_id=map_config_uuid).first()
    if not map_cfg:
        return

    if not map_cfg.is_device_owned or map_cfg.category != 'device':
        current_app.logger.info(
            "Refusing to delete shared map %s (%s, category=%s, "
            "is_device_owned=%s) -- it is not device-owned.",
            map_config_uuid, map_cfg.name, map_cfg.category,
            map_cfg.is_device_owned)
        return

    referenced = _map_still_referenced(map_config_uuid)
    if referenced:
        current_app.logger.info(
            "Refusing to delete map %s (%s) -- still referenced by %s %r.",
            map_config_uuid, map_cfg.name, referenced[0], referenced[1])
        return

    GeoShape.query.filter_by(geo_id=map_config_uuid).delete()
    GeoMap.query.filter_by(unique_id=map_config_uuid).delete()
    current_app.logger.debug("Deleted map %s and associated overlays", map_config_uuid)
