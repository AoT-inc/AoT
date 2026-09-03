# coding=utf-8
import json
from datetime import datetime
from sqlalchemy.orm.attributes import flag_modified
from flask import current_app
try:
    from shapely.geometry import shape, Point, Polygon, box
    from shapely import affinity
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False

from aot.databases.models import GeoShape, Input, Output, OutputChannel, PID, Trigger, Conditional, CustomController, Function, GeoFacility, GeoFacilitySetpoint
from aot.aot_flask.extensions import db

def _is_ephemeral_sprinkler_marker(feat):
    """스프링클러 점 마커(sub_type='sprinkler')인가.

    정본 이미터는 `sprinkler_coverage`(원형 커버리지) 하나뿐이고, 점 마커는
    편집 세션 동안만 보이는 화면용 장식이다(aot-geo-stats.js의 "sprinkler_coverage
    is the canonical emitter; sprinkler dot markers are ephemeral" 참조,
    plot_journal._EMITTER_SUB_TYPE 도 동일). 클라이언트의 `_loadAllFeatures` 는
    이 점을 애초에 다시 불러오지 않으므로, 여기서 저장을 허용하면 클라이언트가
    자기가 예전에 저장한 사본을 다시는 보지 못해 지울 수도 없다 — 재생성할
    때마다 새 사본만 쌓인다(2026-09-03, 이미터 1개당 최대 8겹 실측). 저장
    경계에서 한 번 막아 두면 향후 다른 저장 경로가 실수로 이걸 다시 보내도
    안전하다.
    """
    props = (feat or {}).get('properties') or {}
    return props.get('sub_type') == 'sprinkler'


def _drop_containment_cache():
    """도형 기하가 바뀐 직후 포함 관계 캐시를 버린다.

    캐시에는 TTL(10분) 안전망이 있지만, 그것만 믿으면 사용자가 구역을 그리고
    "왜 그 안 구획이 안 잡히지" 를 10분 동안 본다. 정상 경로는 즉시 버린다.
    """
    try:
        from aot.aot_flask.geo import containment_cache
        containment_cache.invalidate()
    except Exception:
        pass


class GeoOverlayManager:
    """
    Manages Map Overlays (Features).
    Handles CRUD and Geometric Validation.
    """

    @staticmethod
    def _cascade_delete_facilities_for_shapes(shape_ids):
        """Delete any GeoFacility (+ GeoFacilitySetpoint, facility_bay children)
        linked to the given GeoShape ids, via GeoFacility.shape_uuid.

        The bulk `Query.delete()` calls this module uses for GeoShape rows
        bypass SQLAlchemy's ORM relationship handling entirely (no cascade,
        no error) — so deleting a 'facility'-type shape through the generic
        overlay save/delta paths used to silently orphan its GeoFacility row
        (dangling shape_uuid) instead of cleaning it up like the dedicated
        /api/geo/facility/<uuid> DELETE endpoint does. Call this BEFORE
        deleting `shape_ids` (facility_bay cleanup here matches on
        parent_id, which needs the parent shape id to still be well-defined).
        """
        if not shape_ids:
            return
        shape_ids = list(shape_ids)
        uuids = [row[0] for row in db.session.query(GeoShape.unique_id)
                 .filter(GeoShape.id.in_(shape_ids)).all()]
        if not uuids:
            return
        facility_uuids = [row[0] for row in db.session.query(GeoFacility.unique_id)
                           .filter(GeoFacility.shape_uuid.in_(uuids)).all()]
        if not facility_uuids:
            return
        GeoFacilitySetpoint.query.filter(
            GeoFacilitySetpoint.facility_uuid.in_(facility_uuids)
        ).delete(synchronize_session=False)
        GeoShape.query.filter(
            GeoShape.type == 'facility_bay', GeoShape.parent_id.in_(shape_ids)
        ).delete(synchronize_session=False)
        GeoFacility.query.filter(
            GeoFacility.unique_id.in_(facility_uuids)
        ).delete(synchronize_session=False)

    @staticmethod
    def get_overlays(map_uuid, target_type=None, parent_id=None, device_id=None):
        """Get All Overlays for a Map"""
        if not map_uuid:
            return {'type': 'FeatureCollection', 'features': []}, None
            
        try:
            query = GeoShape.query.filter_by(geo_id=map_uuid)
            
            if target_type:
                if target_type == 'equipment':
                    # Fetch both Individual (Legacy) and Collection (Bundle) types
                    query = query.filter(GeoShape.type.in_(['equipment', 'equipment_collection']))
                elif target_type == 'aot_device':
                    # Fetch both 'aot_device' (current) and legacy 'device' rows
                    query = query.filter(GeoShape.type.in_(['aot_device', 'device']))
                else:
                    query = query.filter_by(type=target_type)
            
            if parent_id:
                if hasattr(GeoShape, 'parent_id'):
                    query = query.filter_by(parent_id=parent_id)
            if device_id:
                if hasattr(GeoShape, 'device_id'):
                    query = query.filter_by(device_id=device_id)
                
            shapes = query.all()

            # Pre-fetch GeoFacility rows in one query when shapes include facilities,
            # so we can inject height_m/eave_h/name into facility feature.properties
            # for fill-extrusion rendering. Avoids N+1.
            # [Phase B] 도형↔장치 연결도 같은 이유로 한 번에 읽는다. 도형마다
            # 바인딩을 조회하면 지도 렌더가 도형 수만큼 쿼리를 낸다.
            try:
                from .device_binding import (devices_for_shapes,
                                             device_kinds_for_shapes)
                bound_devices = devices_for_shapes(shapes)
                bound_kinds = device_kinds_for_shapes(shapes)
            except Exception as exc:
                current_app.logger.warning(
                    '[GeoOverlays] 바인딩 일괄 해석 실패 — device_id 컬럼으로 '
                    '계속: %s', exc)
                bound_devices = {}
                bound_kinds = {}

            facility_meta = {}
            facility_shape_uuids = [s.unique_id for s in shapes if s.type == 'facility']
            if facility_shape_uuids:
                fac_rows = GeoFacility.query.filter(
                    GeoFacility.shape_uuid.in_(facility_shape_uuids)
                ).all()
                for fr in fac_rows:
                    g3d = fr.geometry_3d or {}
                    facility_meta[fr.shape_uuid] = {
                        'facility_uuid': fr.unique_id,
                        'name': fr.name,
                        'preset': fr.preset,
                        'structure': fr.structure,
                        'bay_count': fr.bay_count or 1,
                        'height_m': g3d.get('ridge_height_m', 4),
                        'eave_h': g3d.get('eave_height_m', 2),
                        'base_m': 0,
                    }

            features = []
            for s in shapes:
                # [Optimization] Handle Bundled Collection transparency
                if s.type == 'equipment_collection':
                    try:
                        collection = s.state_dict() if hasattr(s, 'state_dict') else (json.loads(s.feature) if isinstance(s.feature, str) else s.feature)
                        if collection and 'features' in collection:
                            for sub_feat in collection['features']:
                                # Inject minimal meta if missing (though usually stored intact)
                                if 'properties' not in sub_feat: sub_feat['properties'] = {}
                                # Ensure aot_type exists
                                if 'aot_type' not in sub_feat['properties']:
                                    sub_feat['properties']['aot_type'] = 'equipment'
                                features.append(sub_feat)
                    except Exception as e:
                        current_app.logger.error(f"Failed to unpack equipment_collection: {e}")
                    continue

                feat_raw = s.feature
                if not feat_raw: continue
                
                # Normalize Feature dict
                if isinstance(feat_raw, str):
                    try: feat = json.loads(feat_raw)
                    except: continue
                else:
                    try: feat = json.loads(json.dumps(feat_raw))
                    except: feat = dict(feat_raw) if isinstance(feat_raw, dict) else {}

                if not isinstance(feat, dict): continue
                    
                if 'properties' not in feat: feat['properties'] = {}
                
                # Inject DB Meta
                feat['properties']['db_id'] = s.id
                # [Fix] node_id backfill — 레거시 row(혹은 parcel-import 이전 데이터)는
                # feature.properties.node_id가 없어 cleanupOrphanLabels/migration에서
                # 부모 매칭 실패 → 라벨 orphan 삭제. shape.unique_id로 안정적으로 채운다.
                # 라벨의 parent_node_id도 과거에 parent_shape.unique_id로 저장돼 있어
                # 이 백필만으로 레거시 부모↔라벨 매칭이 자동 복구된다.
                if not feat['properties'].get('node_id'):
                    feat['properties']['node_id'] = s.unique_id
                # [Phase C] 도형의 진짜 식별자. node_id 와 **다르다** —
                # node_id 는 클라이언트가 만든 값이고 저장된 feature 안에
                # 그대로 남아 있어, 위 백필은 그 값이 없을 때만 동작한다.
                # 바인딩의 spatial_id 는 GeoShape.unique_id 여야 하므로
                # 둘을 섞으면 배정이 엉뚱한 자리에 저장되거나 거부된다
                # (실제로 그렇게 짰다가 지도에서 도형을 고르는 경로만
                # 조용히 동작하지 않았다).
                feat['properties']['shape_uuid'] = s.unique_id
                # [Fix] Inject Device/Channel IDs for Frontend Filtering (Strict Selection)
                # [Phase B] 어느 장치인지는 geo_binding 이 정본이고, 바인딩이
                # 없으면 device_id 컬럼으로 폴백한다(device_binding 리졸버가
                # 그 순서를 담당). 마커·구역 외 종류는 리졸버가 None 을
                # 돌려주므로 종전대로 컬럼 값을 쓴다.
                resolved_device = bound_devices.get(s.unique_id)
                if resolved_device:
                    feat['properties']['device_id'] = resolved_device
                elif hasattr(s, 'device_id') and s.device_id:
                    feat['properties']['device_id'] = s.device_id
                if hasattr(s, 'channel_id') and s.channel_id:
                    feat['properties']['channel_id'] = s.channel_id
                # 배정된 장치의 **종류**도 함께 내려준다 — 화면이 도형을 종류
                # 색으로 칠하는 데 쓴다. 이 값이 없으면 지도 위젯처럼 조회
                # 수단이 없는 소비처는 배정된 도형까지 공통색으로 칠한다.
                # 저장된 값이 있으면 건드리지 않는다(그쪽이 더 구체적일 수 있다).
                if not feat['properties'].get('device_type'):
                    bound_kind = bound_kinds.get(s.unique_id)
                    if bound_kind:
                        feat['properties']['device_type'] = bound_kind

                # Overwrite aot_type if missing OR null (old Leaflet data stored aot_type: null)
                if not feat['properties'].get('aot_type'):
                    feat['properties']['aot_type'] = s.type
                # Normalize legacy 'device' → 'aot_device'
                if feat['properties'].get('aot_type') == 'device':
                    feat['properties']['aot_type'] = 'aot_device'
                feat['properties']['parent_id'] = getattr(s, 'parent_id', None)

                # Facility extras for 3D extrusion (height_m, eave_h, name, preset, ...)
                if s.type == 'facility' and s.unique_id in facility_meta:
                    for k, v in facility_meta[s.unique_id].items():
                        # do not clobber explicit name if already set on the feature
                        if k == 'name' and feat['properties'].get('name'):
                            continue
                        feat['properties'][k] = v

                features.append(feat)
                
            return {
                'type': 'FeatureCollection',
                'features': features
            }, None
        except Exception as e:
            current_app.logger.error(f"Overlay GET Error: {e}")
            return None, str(e)

    # [I6] 저장 JSON 에서 제거하는 구조 필드. 도형의 종류는 type 컬럼이
    # 유일한 정본이며, aot_type 은 get_overlays() 가 읽기 시 주입하는
    # 파생값이다. 두 번째 사본을 저장하지 않으면 드리프트는 표현 자체가
    # 불가능하다 — Tier-2 트리거(GEO-I6, p6_23)가 DB 계층에서 이를 봉인한다.
    # 주의: equipment_collection 번들의 '자식' 피처는 DB 행이 없어 JSON 이
    # 유일한 정체성이므로 이 규칙의 대상이 아니다(트리거도 최상위만 검사).
    # [GB-5] device_id/channel_id 도 같은 이유로 제거한다 — 어느 장치인지의
    # 정본은 geo_binding 이고, 읽을 때 get_overlays 가 주입한다. 저장된 사본이
    # 남아 있으면 도형 복제·옛 페이로드 재전송이 죽은 참조를 되살린다
    # (clone_map_config 가 그 방식으로 도형 98개를 오염시켰다).
    # properties.unique_id 는 대상이 아니다 — 사본이 아니라 프런트의 식별
    # 계약이다(GB-5b, 별도 게이팅).
    _STORED_STRUCT_PROPS = ('aot_type', 'device_id', 'channel_id')

    @staticmethod
    def _strip_structural_props(feat):
        """저장 직전 구조 필드를 제거한 사본을 반환한다. 원본 불변."""
        if not isinstance(feat, dict):
            return feat
        props = feat.get('properties')
        if not isinstance(props, dict) or not any(
                k in props for k in GeoOverlayManager._STORED_STRUCT_PROPS):
            return feat
        out = dict(feat)
        out['properties'] = {k: v for k, v in props.items()
                             if k not in GeoOverlayManager._STORED_STRUCT_PROPS}
        return out

    @staticmethod
    def _record_bindings(target_type, pending):
        """도형↔장치 연결을 geo_binding 에 기록한다(도형 저장의 유일한 지점).

        예전에는 이 함수가 `GeoShape.device_id` 컬럼에만 각인했다. 그러면
        연결이 도형의 몸에 새겨져 장치보다 오래 살 수 없다 — 장치를 지우면
        고아가 되고, 갈아끼우면 도형을 다시 그려야 했다. 컬럼 쓰기는 폴백
        제거와 함께 사라지고, 그때까지 두 저장처를 같은 값으로 유지한다
        (그래야 `check_geo_integrity` 의 binding-drift 가 계속 의미를 갖는다).

        `rebind` 를 쓰는 이유: 같은 도형을 다시 저장하는 것이 정상 경로라
        (지도를 저장할 때마다 전체가 올라온다) `bind` 면 매번 점유 충돌이
        난다. rebind 는 값이 같으면 아무것도 하지 않는다.

        실패해도 도형 저장을 막지 않는다 — 도형은 이미 레거시 컬럼에
        저장됐고 백필이 나중에 같은 행을 만들 수 있는 반면, 여기서 예외를
        올리면 사용자는 지도를 저장하지 못한다. 대신 SAVEPOINT 안에서 쓴다:
        그냥 삼키면 실패한 flush 가 세션을 오염시킨 채 남아 뒤이은 커밋이
        무관한 자리에서 죽는다.
        """
        from aot.aot_flask.geo import device_binding

        role = device_binding.role_for_shape_type(target_type)
        if role is None or not pending:
            return          # 장치를 매다는 자리가 아닌 종류(site/zone/…)

        wanted = [(shape, str(dev).split('::')[0], ch)
                  for shape, dev, ch in pending if dev]
        if not wanted:
            return

        try:
            db.session.flush()          # INSERT 행의 unique_id 확보
            with db.session.begin_nested():
                for shape, dev, ch in wanted:
                    if not shape.unique_id:
                        continue
                    kind = device_binding.resolve_device_kind(dev)
                    if kind is None:
                        # 실존하지 않는 장치에 바인딩을 만들지 않는다 —
                        # 고아를 정본으로 승격시키지 않는 백필과 같은 정책.
                        continue
                    device_binding.rebind(
                        'shape', shape.unique_id, role, kind, dev,
                        channel_id=ch if ch is not None else '0')
        except Exception as exc:
            current_app.logger.warning(
                '[GeoOverlays] 바인딩 기록 실패(type=%s, %d건) — %s',
                target_type, len(wanted), exc)

    @staticmethod
    def save_overlays(data):
        """
        Save Overlays with Validation.

        Strategy [I9]: 기존 행 매칭은 db_id → node_id 순서의 안정 키로 하고,
        페이로드에서 빠진 행은 절대 지우지 않는다. 삭제는 반드시 '명시'다:
          - data['deletes'] — node_id 또는 db_id 목록 (부분 삭제)
          - features=[] + allow_empty=True (전체 비우기)
          - /overlays/delta 의 deletes[]
        '누락'과 '삭제'를 구분하는 것이 핵심이다. 지워야 할 것은 지워지고,
        빠뜨린 것은 살아남는다.

        과거의 "페이로드에 없음 = 삭제" 프로토콜은 클라이언트가 db_id 를
        빠뜨리는 순간 zone 전체를 삭제 후 새 id 로 재생성해 장치 소속을
        전원 끊었다(2026-08-03 사고 최다 발생원). docs/design/
        geo-data-integrity.md I9 참조.
        """
        map_uuid = data.get('map_uuid')
        target_type = data.get('type') # 'site', 'zone', 'infra_blob'
        new_features = data.get('features', [])
        parent_id = data.get('parent_id') # Required for infra_blob, optional for zone
        device_id = data.get('device_id')
        # [Safety] Explicit opt-in required before an empty payload may wipe existing
        # rows. Without this flag a full-sync that races ahead of overlay loading (or
        # targets a desynced/wrong map) would send features=[] and silently delete the
        # whole layer. See the empty-wipe guards in the equipment and delta-sync paths.
        allow_empty = bool(data.get('allow_empty'))

        if not map_uuid or not target_type:
            return None, "Missing map_uuid or type"

        # [Safety Guard] Never allow bulk-delete of aot_device GeoShapes via save_overlays.
        # Device marker locations are managed exclusively by /api/geo/device/location.
        # An empty features list would delete ALL device placements, so we block it here.
        if target_type == 'aot_device' and not new_features and not device_id:
            current_app.logger.warning(
                f"[GeoOverlay] Blocked bulk-delete attempt on aot_device "
                f"(map={map_uuid}, features=[], device_id=None). "
                "Use /api/geo/device/location to manage device placements."
            )
            return {'ok': True, 'count': 0, 'stats': {'skipped': 'aot_device_protected'}}, None

        # --- Optimization: Bulk Bundle for Equipment ---
        if target_type == 'equipment':
            try:
                # [Fix] Never persist ephemeral sprinkler dot markers — see
                # _is_ephemeral_sprinkler_marker. Filter before the empty-wipe
                # check below so a payload that is ONLY stray dot markers is
                # correctly treated as empty, not as "real equipment saved".
                new_features = [f for f in new_features
                                if not _is_ephemeral_sprinkler_marker(f)]

                # [Safety] This path deletes ALL equipment rows before re-inserting the
                # bundle. An empty payload would therefore wipe every equipment feature.
                # Block it unless the caller explicitly confirms an intentional clear.
                if not new_features and not allow_empty:
                    existing_eq = GeoShape.query.filter_by(geo_id=map_uuid).filter(
                        GeoShape.type.in_(['equipment', 'equipment_collection'])
                    ).count()
                    if existing_eq:
                        current_app.logger.warning(
                            f"[GeoOverlay] Blocked empty-payload equipment wipe "
                            f"(map={map_uuid}, existing={existing_eq}). "
                            "Pass allow_empty=true to confirm a full clear."
                        )
                        return {'ok': True, 'count': 0,
                                'stats': {'skipped': 'empty_wipe_blocked',
                                          'would_delete': existing_eq}}, None

                # 1. Prepare Feature Collection payload
                bundle = {
                    'type': 'FeatureCollection',
                    'features': new_features
                }
                
                # 2. Cleanup Old Data (Both Legacy Individual & Previous Bundle)
                GeoShape.query.filter_by(geo_id=map_uuid).filter(
                    GeoShape.type.in_(['equipment', 'equipment_collection'])
                ).delete(synchronize_session=False)
                
                # 3. Insert New Bundle Row
                s = GeoShape(
                    geo_id=map_uuid,
                    type='equipment_collection',
                    feature=bundle  # SQLAlchemy stores this as JSON
                )
                db.session.add(s)
                db.session.commit()
                # 기하가 바뀌면 포함 관계 캐시는 낡는다. 지우기만 하므로
                # 과하게 불러도 손해는 재계산 비용뿐이다.
                _drop_containment_cache()
                
                return {
                    'ok': True,
                    'count': len(new_features),
                    'stats': {'deleted': 'all_legacy', 'inserted': 1, 'mode': 'bulk_bundle'}
                }, None
                
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Bulk Save Error: {e}")
                return None, str(e)

        # --- Validation Phase ---
        if target_type in ['zone', 'facility', 'equipment', 'aot_device', 'infra_blob']:
             # 1. Fetch Parent Geometry Context if needed
             if parent_id:
                 pass # TODO: Implement strict DB fetch & validation if critical
        
        # 2. Geometry Rules Validation (Self-check)
        # [Fix] Skip Validation for Equipment to prevent GEOS crashes on degenerate segments (Trusted Source)
        if target_type != 'equipment':
            for feat in new_features:
                valid, msg = GeoOverlayManager._validate_geometry_rules(feat, target_type)
                if not valid:
                    return None, f"Geometry Error: {msg}"

        # --- Persistence Phase ---
        try:
            # 1. Define Scope Query
            query = GeoShape.query.filter_by(geo_id=map_uuid, type=target_type)
            
            if target_type == 'infra_blob':
                # Allow global save without parent_id (if generic)
                if parent_id and hasattr(GeoShape, 'parent_id'):
                    query = query.filter_by(parent_id=parent_id)
            elif target_type == 'zone' and parent_id:
                if hasattr(GeoShape, 'parent_id'):
                    query = query.filter_by(parent_id=parent_id)

            if device_id and hasattr(GeoShape, 'device_id'):
                query = query.filter_by(device_id=device_id)
                
            # 2. Fetch Existing IDs directly
            existing_rows = query.all()
            existing_map = {row.id: row for row in existing_rows}
            existing_ids = set(existing_map.keys())

            # [I9] 안정 키(node_id) 매칭 준비 — 클라이언트가 db_id 를 잃어버린
            # 피처(레이어 재구성, 라이브러리 왕복 등)를 신규 INSERT 로 취급하면
            # 같은 도형이 두 벌이 된다. 저장된 feature 의 node_id(레거시 행은
            # unique_id 백필 — get_overlays 와 동일 규칙)로 기존 행을 되찾는다.
            node_map = {}
            for row in existing_rows:
                rf = row.feature
                if isinstance(rf, str):
                    try:
                        rf = json.loads(rf)
                    except Exception:
                        rf = {}
                nid = ((rf or {}).get('properties') or {}).get('node_id') \
                    or row.unique_id
                node_map.setdefault(nid, row)

            # 3. Analyze Incoming Payload
            to_insert = []
            to_update = []
            matched_ids = set()

            for feat in new_features:
                props = feat.get('properties', {})
                db_id = props.get('db_id')

                # Check if this ID really exists in our scope (security check)
                if db_id and db_id in existing_ids:
                    matched_ids.add(db_id)
                    to_update.append((db_id, feat))
                    continue
                nid = props.get('node_id')
                row = node_map.get(nid) if nid else None
                if row is not None and row.id not in matched_ids:
                    matched_ids.add(row.id)
                    to_update.append((row.id, feat))
                    continue
                to_insert.append(feat)

            # 4a. [I9] 명시 삭제 — 클라이언트가 지운 도형을 목록으로 받는다.
            # 전체 저장에서도 삭제가 가능해야 하지만, 그 표현은 '누락'이
            # 아니라 '명시'여야 한다. node_id 또는 db_id 를 받아 현재 스코프
            # 안에서만 매칭한다(스코프 밖 id 를 넘겨도 남의 도형은 못 지운다).
            explicit_ids = set()
            for token in (data.get('deletes') or []):
                if isinstance(token, int) or (isinstance(token, str)
                                              and token.isdigit()):
                    tid = int(token)
                    if tid in existing_ids:
                        explicit_ids.add(tid)
                    continue
                row = node_map.get(token)
                if row is not None:
                    explicit_ids.add(row.id)
            # 방금 upsert 된 행은 지우지 않는다(삭제 후 재생성 순서 방어).
            explicit_ids -= matched_ids

            # 4b. [I9] 암묵 삭제 폐지 — "페이로드에 없음 = 삭제" 프로토콜은
            # 2026-08-03 사고의 최다 발생원이었다(클라이언트가 db_id 를 하나
            # 빠뜨리면 zone 전체가 삭제 후 새 id 로 재생성 → 장치 소속 전원
            # 단절). 전체 저장은 upsert 전용이며, 삭제는 명시 경로로만 간다:
            #   - 개별 삭제: /overlays/delta 의 deletes[] (명시 목록)
            #   - 전체 비우기: features=[] + allow_empty=True (명시 의사)
            deleted_count = 0
            if not new_features and existing_ids:
                if not allow_empty:
                    # 장치 스코프(device_id)든 아니든 동일하게 명시 요구 —
                    # I9 는 예외를 두지 않는다.
                    current_app.logger.warning(
                        f"[GeoOverlay] Blocked empty-payload wipe "
                        f"(map={map_uuid}, type={target_type}, "
                        f"device={device_id}, "
                        f"would_delete={len(existing_ids)}). "
                        "Pass allow_empty=true to confirm a clear.")
                    return {'ok': True, 'count': 0,
                            'stats': {'skipped': 'empty_wipe_blocked',
                                      'would_delete': len(existing_ids)}}, None
                # 명시적 전체 비우기 — I9 가 허용하는 유일한 일괄 삭제.
                GeoOverlayManager._cascade_delete_facilities_for_shapes(
                    existing_ids)
                deleted_count = query.filter(
                    GeoShape.id.in_(existing_ids)).delete(
                        synchronize_session=False)
            else:
                if explicit_ids:
                    GeoOverlayManager._cascade_delete_facilities_for_shapes(
                        explicit_ids)
                    deleted_count = query.filter(
                        GeoShape.id.in_(explicit_ids)).delete(
                            synchronize_session=False)
                    current_app.logger.info(
                        f"[GeoOverlay][I9] explicit delete {deleted_count} "
                        f"row(s) (map={map_uuid}, type={target_type}).")
                omitted = existing_ids - matched_ids - explicit_ids
                if omitted:
                    current_app.logger.info(
                        f"[GeoOverlay][I9] {len(omitted)} row(s) omitted from "
                        f"full-sync (map={map_uuid}, type={target_type}) — "
                        "kept. Deletions must be listed in deletes[].")

            # 5. Execute Operations
            #
            # [Phase C] 장치 연결은 geo_binding 이 정본이다. 아래 두 루프는
            # 레거시 컬럼을 계속 쓰되(폴백 제거와 함께 사라진다) 연결을
            # (도형, 장치, 채널) 로 모아 두었다가 커밋 직전에 게이트웨이로
            # 기록한다. INSERT 된 도형의 unique_id 는 flush 이후에야 생기므로
            # 루프 안에서 바로 bind 할 수 없다.
            pending_bindings = []

            # B. UPDATE
            for db_id, feat in to_update:
                row = existing_map[db_id]
                # [I6] 구조 필드 제거 후 저장. 이름 동기화는 원본 페이로드로.
                row.feature = GeoOverlayManager._strip_structural_props(feat)
                row.updated_at = datetime.utcnow()

                # [New] Sync Properties (Name, etc.) back to Source Models
                GeoOverlayManager._sync_device_properties(feat)

                # [Fix] Update device_id and channel_id columns for precise persistence
                feat_props = feat.get('properties', {})
                if hasattr(row, 'device_id'):
                    d_id = device_id or feat_props.get('device_id')
                    if d_id:
                        # [Fix] Strip channel suffix before storing in device_id column
                        row.device_id = str(d_id).split('::')[0]
                
                if hasattr(row, 'channel_id'):
                    ch_id = feat_props.get('channel_id')
                    if ch_id is not None:
                         row.channel_id = str(ch_id)

                pending_bindings.append(
                    (row, device_id or feat_props.get('device_id'),
                     feat_props.get('channel_id')))

            # C. INSERT
            for feat in to_insert:
                s = GeoShape()
                s.geo_id = map_uuid
                s.type = target_type

                # Prioritize payload device_id, fallback to feature property
                feat_props = feat.get('properties', {})
                if hasattr(s, 'device_id'):
                    d_id = device_id or feat_props.get('device_id')
                    if d_id:
                        # [Fix] Strip channel suffix before storing in device_id column
                        s.device_id = str(d_id).split('::')[0]

                # [New] Save channel_id for per-channel coordinates
                if hasattr(s, 'channel_id') and feat_props.get('channel_id'):
                    s.channel_id = str(feat_props.get('channel_id'))
                
                if hasattr(s, 'parent_id') and parent_id:
                    s.parent_id = parent_id

                s.feature = GeoOverlayManager._strip_structural_props(feat)  # [I6]
                db.session.add(s)
                pending_bindings.append(
                    (s, device_id or feat_props.get('device_id'),
                     feat_props.get('channel_id')))

            GeoOverlayManager._record_bindings(target_type, pending_bindings)
            db.session.commit()
            # 기하가 바뀌면 포함 관계 캐시는 낡는다. 지우기만 하므로
            # 과하게 불러도 손해는 재계산 비용뿐이다.
            _drop_containment_cache()

            # [Phase 3b] Materialize tz down the shape tree + linked devices.
            # Post-commit, own transaction — safe. (timezone-management.md §4)
            GeoOverlayManager.materialize_timezones(map_uuid)

            # 6. Prepare Response with ID Mapping
            id_map = {}
            # Refetch or use the objects we have
            # For newly inserted rows, we need their IDs
            # SQLAlchemy will populate id after commit
            
            # Combine to_update and to_insert to build id_map
            all_saved_rows = GeoShape.query.filter_by(geo_id=map_uuid, type=target_type).all()
            for row in all_saved_rows:
                feat = row.feature
                if isinstance(feat, str):
                    try: feat = json.loads(feat)
                    except: feat = {}
                node_id = feat.get('properties', {}).get('node_id')
                if node_id:
                    id_map[node_id] = row.id

            return {
                'ok': True, 
                'count': len(new_features),
                'id_map': id_map,
                'stats': {
                    'deleted': deleted_count,
                    'updated': len(to_update),
                    'inserted': len(to_insert)
                }
            }, None
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Save Overlays Error: {e}")
            return None, str(e)
            
    @staticmethod
    def materialize_timezones(map_uuid):
        """맵의 모든 도형 tz 를 상속 계층으로 물질화하고 연결 장치에 전파한다.

        저장(save_overlays 등) 커밋 직후 호출하는 별도 트랜잭션. 부모 도형(site)
        을 먼저 처리해 자식 zone·device 가 갱신된 부모 tz 를 상속하도록 한다.
        tz_source='explicit'(수동 override / 경계 그룹 선택)인 행은 절대 덮어쓰지
        않는다. (docs/design/timezone-management.md §4·§8 — Phase 3b 물질화/전파)
        """
        try:
            shapes = GeoShape.query.filter_by(geo_id=map_uuid).all()
            if not shapes:
                return
            # 부모 먼저: site(1) → zone(2) → device/feature(3)
            shapes.sort(key=lambda s: s.level_id)
            changed = False
            for s in shapes:
                if getattr(s, 'tz_source', None) != 'explicit':
                    tzn, src = s.compute_effective_tz()
                    if tzn and (s.timezone != tzn or s.tz_source != src):
                        s.timezone = tzn
                        s.tz_source = src
                        changed = True
                if s.type in ('site', 'zone'):
                    b = s.detect_tz_boundary()
                    if bool(s.tz_boundary) != bool(b):
                        s.tz_boundary = b
                        changed = True
            if changed:
                db.session.flush()  # 장치 전파가 갱신된 도형 tz 를 보도록

            # 연결 장치(device_id)에 전파 — explicit 핀 보존
            device_models = (Input, Output, Function, Conditional, Trigger, PID, CustomController)
            for s in shapes:
                did = getattr(s, 'device_id', None)
                if not did:
                    continue
                tz = s.resolve_timezone()
                if tz is None:
                    continue
                tz_str = str(tz)
                for Model in device_models:
                    row = Model.query.filter_by(unique_id=did).first()
                    if row is not None:
                        if getattr(row, 'tz_source', None) != 'explicit' and row.timezone != tz_str:
                            row.timezone = tz_str
                            row.tz_source = 'inherited'
                            changed = True
                        break
            if changed:
                db.session.commit()
                # 기하가 바뀌면 포함 관계 캐시는 낡는다. 지우기만 하므로
                # 과하게 불러도 손해는 재계산 비용뿐이다.
                _drop_containment_cache()
        except Exception as e:
            db.session.rollback()
            current_app.logger.warning(f"[GeoOverlay] materialize_timezones failed for {map_uuid}: {e}")

    @staticmethod
    def save_delta(data):
        """
        Efficient Delta Save for individual features.
        Payload: { map_uuid, upserts: [feat, ...], deletes: [db_id or node_id, ...] }
        """
        map_uuid = data.get('map_uuid')
        upserts = data.get('upserts', [])
        deletes = data.get('deletes', [])

        if not map_uuid:
            return None, "Missing map_uuid"

        try:
            # 1. Handle Deletes
            if deletes:
                db_ids = [d for d in deletes if isinstance(d, int)]
                node_ids = [d for d in deletes if isinstance(d, str)]
                
                if db_ids:
                    GeoOverlayManager._cascade_delete_facilities_for_shapes(db_ids)
                    GeoShape.query.filter(GeoShape.geo_id == map_uuid, GeoShape.id.in_(db_ids)).delete(synchronize_session=False)
                
                if node_ids:
                    # 2. Generic lookup for node_ids (Individual rows and Bundled collections)
                    all_shapes = GeoShape.query.filter_by(geo_id=map_uuid).all()
                    to_del = []
                    for s in all_shapes:
                        # Case A: Bundled Collection
                        if s.type == 'equipment_collection':
                            bundle = s.feature
                            if isinstance(bundle, str):
                                try: bundle = json.loads(bundle)
                                except: bundle = {}

                            if bundle and 'features' in bundle:
                                orig_count = len(bundle['features'])
                                bundle['features'] = [f for f in bundle['features']
                                                     if f.get('properties', {}).get('node_id') not in node_ids]
                                removed = orig_count - len(bundle['features'])

                                if removed > 0:
                                    if not bundle['features']:
                                        to_del.append(s.id)
                                    else:
                                        s.feature = bundle
                                        flag_modified(s, 'feature')
                                        s.updated_at = datetime.utcnow()

                        # Case B: Individual Row (Legacy or Delta-inserted)
                        else:
                            feat = s.feature
                            if isinstance(feat, str):
                                try: feat = json.loads(feat)
                                except: feat = {}
                            if feat.get('properties', {}).get('node_id') in node_ids:
                                to_del.append(s.id)

                    if to_del:
                        GeoOverlayManager._cascade_delete_facilities_for_shapes(to_del)
                        GeoShape.query.filter(GeoShape.id.in_(to_del)).delete(synchronize_session=False)

            # 2. Handle Upserts

            id_map = {}

            # [Fix] Equipment is stored as a single 'equipment_collection' bundle (see
            # save_overlays bulk-bundle path). The delete branch above already edits that
            # bundle, but upserts used to fall through to the generic loop below and were
            # inserted as stray individual 'equipment' rows. Those stray rows were wiped the
            # next time a full equipment save re-bundled, so freshly generated sprinklers
            # (which save via this delta path) vanished after a reload. Merge equipment
            # upserts INTO the bundle here, symmetric with the delete branch.
            # [Fix] Never persist ephemeral sprinkler dot markers (see
            # _is_ephemeral_sprinkler_marker) — this is the dominant save path for
            # newly-generated sprinklers (doSave path in generateSprinklers), and a
            # pure additive merge below, so anything that slips through here never
            # gets cleaned up: the client can't see its own past copies to delete
            # them (the load path never loads sub_type='sprinkler' Points back), so
            # every regenerate cycle piled a fresh batch on top of the old one.
            equip_upserts = [f for f in upserts
                             if f.get('properties', {}).get('aot_type') == 'equipment'
                             and not _is_ephemeral_sprinkler_marker(f)]
            other_upserts = [f for f in upserts
                             if f.get('properties', {}).get('aot_type') != 'equipment']

            if equip_upserts:
                bundle_row = GeoShape.query.filter_by(
                    geo_id=map_uuid, type='equipment_collection').first()
                bundle = None
                if bundle_row:
                    bundle = bundle_row.feature
                    if isinstance(bundle, str):
                        try: bundle = json.loads(bundle)
                        except: bundle = None
                if not bundle or 'features' not in bundle:
                    bundle = {'type': 'FeatureCollection', 'features': []}

                feats = bundle['features']
                idx_by_node = {}
                for i, bf in enumerate(feats):
                    nid = bf.get('properties', {}).get('node_id')
                    if nid is not None:
                        idx_by_node[nid] = i

                for feat in equip_upserts:
                    nid = feat.get('properties', {}).get('node_id')
                    if nid is not None and nid in idx_by_node:
                        feats[idx_by_node[nid]] = feat
                    else:
                        feats.append(feat)
                        if nid is not None:
                            idx_by_node[nid] = len(feats) - 1
                bundle['features'] = feats

                if bundle_row:
                    bundle_row.feature = bundle
                    flag_modified(bundle_row, 'feature')
                    bundle_row.updated_at = datetime.utcnow()
                else:
                    bundle_row = GeoShape(
                        geo_id=map_uuid, type='equipment_collection', feature=bundle)
                    db.session.add(bundle_row)

                # Purge any stray individual 'equipment' rows for these node_ids
                # (legacy data or rows inserted before this fix) to avoid duplicates.
                upserted_nids = set(
                    f.get('properties', {}).get('node_id') for f in equip_upserts
                    if f.get('properties', {}).get('node_id') is not None)
                if upserted_nids:
                    stray_del = []
                    for s in GeoShape.query.filter_by(geo_id=map_uuid, type='equipment').all():
                        sf = s.feature
                        if isinstance(sf, str):
                            try: sf = json.loads(sf)
                            except: sf = {}
                        if sf.get('properties', {}).get('node_id') in upserted_nids:
                            stray_del.append(s.id)
                    if stray_del:
                        GeoShape.query.filter(GeoShape.id.in_(stray_del)).delete(
                            synchronize_session=False)

            for feat in other_upserts:
                props = feat.get('properties', {})
                db_id = props.get('db_id')
                node_id = props.get('node_id')
                target_type = props.get('aot_type', 'feature')
                device_id = props.get('device_id')
                parent_id = props.get('parent_id')
                
                row = None
                if db_id:
                    row = GeoShape.query.filter_by(geo_id=map_uuid, id=db_id).first()
                
                if not row and node_id:
                    # Fallback to node_id search if db_id not provided by frontend yet
                    all_shapes = GeoShape.query.filter_by(geo_id=map_uuid, type=target_type).all()
                    for s in all_shapes:
                        s_feat = s.feature
                        if isinstance(s_feat, str):
                            try: s_feat = json.loads(s_feat)
                            except: s_feat = {}
                        if s_feat.get('properties', {}).get('node_id') == node_id:
                            row = s
                            break

                if row:
                    # [I7] 기존 행의 type 은 절대 재분류하지 않는다.
                    # 과거 `row.type = target_type` 은 되먹임 고리의 마지막
                    # 단계였다: GET 이 표시용으로 정규화한 aot_type 을
                    # 클라이언트가 그대로 되돌려보내면(위젯 라벨 이름 변경)
                    # 저장된 종류가 바뀌고, 다음 전체 저장의 type 스코프에서
                    # 벗어나 도형이 이중화됐다. 종류 변경은 삭제 후 생성뿐
                    # 이며, Tier-2 트리거(GEO-I7)가 DB 계층에서 봉인한다.
                    if target_type != row.type and props.get('aot_type'):
                        current_app.logger.info(
                            f"[GeoOverlay][I7] delta upsert ignored client "
                            f"aot_type={target_type!r} for shape id={row.id} "
                            f"(type={row.type!r} kept).")
                    row.feature = GeoOverlayManager._strip_structural_props(feat)  # [I6]
                    # Update columns if needed
                    if hasattr(row, 'device_id') and device_id: row.device_id = device_id
                    if hasattr(row, 'channel_id') and props.get('channel_id'): row.channel_id = str(props.get('channel_id'))
                    if hasattr(row, 'parent_id') and parent_id: row.parent_id = parent_id
                    row.updated_at = datetime.utcnow()

                    # [New] Sync Properties (Name, etc.) back to Source Models
                    GeoOverlayManager._sync_device_properties(feat)
                else:
                    # Insert — 신규 생성에 한해 클라이언트 aot_type 이 종류를
                    # 결정한다(생성 계약). 어휘는 I1 화이트리스트가 지킨다.
                    row = GeoShape(
                        geo_id=map_uuid, type=target_type,
                        feature=GeoOverlayManager._strip_structural_props(feat))  # [I6]
                    if hasattr(row, 'device_id') and device_id: row.device_id = device_id
                    if hasattr(row, 'channel_id') and props.get('channel_id'): row.channel_id = str(props.get('channel_id'))
                    if hasattr(row, 'parent_id') and parent_id: row.parent_id = parent_id
                    db.session.add(row)
                    
                    # [New] Sync Properties (Name, etc.) back to Source Models
                    GeoOverlayManager._sync_device_properties(feat)
                
                # We need to commit or flush to get the ID back
                db.session.flush()
                if node_id:
                    id_map[node_id] = row.id

                # [Phase C] 델타 경로도 바인딩을 남긴다. 여기가 빠지면 장치를
                # 활성화한 채 그린 도형이 델타로 저장될 때만 연결이 컬럼에만
                # 생겨, 같은 UI 안에서 저장 경로에 따라 결과가 갈린다.
                # row.type 을 쓴다 — 클라이언트가 보낸 aot_type 은 I7 때문에
                # 기존 행에 반영되지 않으므로 그 값으로 role 을 정하면
                # 저장된 종류와 어긋난다.
                if device_id:
                    GeoOverlayManager._record_bindings(
                        row.type, [(row, device_id, props.get('channel_id'))])

            db.session.commit()
            # 기하가 바뀌면 포함 관계 캐시는 낡는다. 지우기만 하므로
            # 과하게 불러도 손해는 재계산 비용뿐이다.
            _drop_containment_cache()
            # [Phase 3b] tz 물질화/전파 (timezone-management.md §4)
            GeoOverlayManager.materialize_timezones(map_uuid)
            return {'ok': True, 'id_map': id_map}, None

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Geo Delta Save Error: {e}")
            return None, str(e)

    @staticmethod
    def generate_pipes(data):
        """
        Generate Branch Pipes on the Backend using high-precision local projection.
        """
        from shapely.geometry import shape, mapping, LineString, MultiLineString, Polygon, Point
        from shapely.ops import split
        from shapely import affinity
        import math

        parent_feat = data.get('parent_feature')
        ref_feat = data.get('ref_line')
        config = data.get('config', {})
        map_uuid = data.get('map_uuid')

        if not parent_feat:
            return None, "Missing parent feature"

        try:
            boundary_geom = shape(parent_feat['geometry'])
            if not boundary_geom.is_valid:
                boundary_geom = boundary_geom.buffer(0)

            # 1. Determine Initial Reference Line
            ref_line = None
            if ref_feat:
                ref_line = shape(ref_feat['geometry'])
            else:
                if boundary_geom.geom_type == 'Polygon':
                    coords = list(boundary_geom.exterior.coords)
                    max_len = 0
                    for i in range(len(coords)-1):
                        p1, p2 = coords[i], coords[i+1]
                        l = math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)
                        if l > max_len:
                            max_len = l
                            ref_line = LineString([p1, p2])

            if not ref_line or ref_line.length == 0:
                return None, "Reference line could not be determined."

            # 2. High-Precision Local Projection (Meter-Space)
            c = boundary_geom.centroid
            origin_lng, origin_lat = c.x, c.y
            M_PER_DEG_LAT = 111320.0
            M_PER_DEG_LNG = M_PER_DEG_LAT * math.cos(math.radians(origin_lat))
            
            def project(geom):
                g = affinity.translate(geom, xoff=-origin_lng, yoff=-origin_lat)
                return affinity.scale(g, xfact=M_PER_DEG_LNG, yfact=M_PER_DEG_LAT, origin=(0,0))
            def unproject(geom):
                g = affinity.scale(geom, xfact=1.0/M_PER_DEG_LNG, yfact=1.0/M_PER_DEG_LAT, origin=(0,0))
                return affinity.translate(g, xoff=origin_lng, yoff=origin_lat)

            b_m = project(boundary_geom)
            r_m = project(ref_line)

            # 3. Handle Rotation & Extension (In Meter Space)
            is_90 = config.get('is90Deg', False)
            user_angle = float(config.get('angle', 0))
            


            total_rotation = user_angle + (90 if is_90 else 0)
            
            if abs(total_rotation) > 1e-9:
                r_m = affinity.rotate(r_m, total_rotation, origin='centroid')

            # Extend Baseline significantly for sweep
            diag = math.sqrt((b_m.bounds[2]-b_m.bounds[0])**2 + (b_m.bounds[3]-b_m.bounds[1])**2)
            coords = list(r_m.coords)
            if len(coords) >= 2:
                # Extend start and end along the same direction
                ext_len = diag * 2.0
                p1, p2 = coords[0], coords[1]
                dx_s, dy_s = p2[0]-p1[0], p2[1]-p1[1]
                mag_s = math.sqrt(dx_s**2 + dy_s**2)
                if mag_s > 0:
                    coords[0] = (p1[0] - dx_s/mag_s * ext_len, p1[1] - dy_s/mag_s * ext_len)
                
                pn_1, pn = coords[-2], coords[-1]
                dx_e, dy_e = pn[0]-pn_1[0], pn[1]-pn_1[1]
                mag_e = math.sqrt(dx_e**2 + dy_e**2)
                if mag_e > 0:
                    coords[-1] = (pn[0] + dx_e/mag_e * ext_len, pn[1] + dy_e/mag_e * ext_len)
                r_m = LineString(coords)

            # 4. Project Main Pipes
            main_pipes_m = []
            if map_uuid:
                shapes = GeoShape.query.filter_by(geo_id=map_uuid, type='equipment').all()
                for s in shapes:
                    f = s.feature
                    if f and f.get('properties', {}).get('sub_type') == 'pipe_main':
                        main_pipes_m.append(project(shape(f['geometry'])))

            # 5. Sweep & Generate Features
            generated_features = []
            spacing_m = float(config.get('spacing', 14.0))
            user_offset_m = float(config.get('offset', 0))
            # Sweep Loop
            # Increase margin to avoid missing edges on rotated zones
            max_iter = int(diag / spacing_m) + 10

            def process_segment(line_m):
                # 1. Clip to zone boundary
                inter = b_m.intersection(line_m)
                if inter.is_empty: return
                
                # 2. Normalize to a list of LineStrings
                segments = []
                if inter.geom_type == 'LineString':
                    segments = [inter]
                elif inter.geom_type == 'MultiLineString':
                    segments = list(inter.geoms)
                elif inter.geom_type == 'GeometryCollection':
                    segments = [g for g in inter.geoms if g.geom_type == 'LineString']
                else:
                    return

                # 3. Comprehensive Splitting by all Main Pipes
                for seg in segments:
                    all_parts = [seg]
                    for mp_m in main_pipes_m:
                        next_parts = []
                        for p in all_parts:
                            try:
                                res = split(p, mp_m)
                                next_parts.extend(list(res.geoms))
                            except:
                                next_parts.append(p)
                        all_parts = next_parts
                    
                    # 4. Refined Logic: Keep Significant Segments (V18 Fix)
                    if all_parts:
                        if len(all_parts) > 1:
                            max_p_len = max(p.length for p in all_parts)
                            for part in all_parts:
                                # [V18] If segment is < 10m AND significantly shorter than the main part, discard it as stub.
                                if part.length < 10.0 and part.length < max_p_len * 0.5:
                                    continue
                                push_feat(part)
                        else:
                            # Only one part exists, keep it if it's not tiny noise (> 1m)
                            if all_parts[0].length > 1.0:
                                push_feat(all_parts[0])

            def push_feat(geom_m):
                # Clean and simplify slightly to avoid precision artifacts
                # [Optimization] Reduced simplify tolerance for speed, preserve_topology=False for robustness
                clean_geom = geom_m.simplify(0.01, preserve_topology=False)
                feat = {
                    'type': 'Feature',
                    'geometry': mapping(unproject(clean_geom)),
                    'properties': {
                        'aot_type': 'equipment',
                        'sub_type': 'pipe_branch'
                    }
                }
                generated_features.append(feat)

            # Sweep iterations
            for i in range(-max_iter, max_iter + 1):
                total_offset = user_offset_m + (i * spacing_m)
                try:
                    if abs(total_offset) < 1e-6:
                        line = r_m
                    else:
                        side = 'left' if total_offset > 0 else 'right'
                        line = r_m.parallel_offset(abs(total_offset), side=side)
                        
                        # [Fix] parallel_offset reverses direction for side='right'
                        # Handle both LineString and MultiLineString for consistent piping flow
                        if side == 'right' and line:
                            if line.geom_type == 'LineString':
                                line = LineString(list(line.coords)[::-1])
                            elif line.geom_type == 'MultiLineString':
                                # Reverse segment sequence AND each segment's coords
                                reversed_geoms = [LineString(list(g.coords)[::-1]) for g in reversed(line.geoms)]
                                line = MultiLineString(reversed_geoms)
                    
                    if line:
                        process_segment(line)
                except: continue

            return {
                'type': 'FeatureCollection',
                'features': generated_features,
                'count': len(generated_features)
            }, None

        except Exception as e:
            current_app.logger.error(f"[GeoGen] High-Precision Engine Error: {e}")
            return None, str(e)

    @staticmethod
    def _validate_geometry_rules(feature, feature_type):
        """
        Validate geometry using Shapely.
        Rules:
         - Site/Zone: Must be Polygon (not LineString/Point).
         - All: Valid GeoJSON geometry.
        """
        try:
            geom = shape(feature['geometry'])
            if not geom.is_valid:
                return False, "Invalid Geometry (Self-intersection or other topological error)"
                
            if feature_type in ['site', 'zone']:
                if not isinstance(geom, Polygon):
                     # Allow MultiPolygon? Maybe. But definitely not Point/Line
                    if geom.geom_type not in ['Polygon', 'MultiPolygon']:
                        return False, f"{feature_type} must be a Polygon, got {geom.geom_type}"
            
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def find_containing_shape(lat, lng, map_uuid):
        """
        Finds the smallest (most specific) shape containing the given point.
        Priority: Zone > Site.
        """
        if not lat or not lng or not map_uuid:
            return None
            
        try:
            # point = Point(lng, lat) # Shapely uses (x, y) -> (lng, lat)
            # Actually, check if shape uses [lng, lat] or [lat, lng]. 
            # Standard GeoJSON is [lng, lat], Turf is [lng, lat].
            p = Point(float(lng), float(lat))
            
            # Fetch all Sites and Zones for this map
            shapes = GeoShape.query.filter(
                GeoShape.geo_id == map_uuid,
                GeoShape.type.in_(['site', 'zone'])
            ).all()
            
            best_match = None
            
            for s in shapes:
                feat = s.feature
                if not feat or 'geometry' not in feat:
                    continue
                    
                geom = shape(feat['geometry'])
                if geom.contains(p):
                    # Priority logic: Zone replaces Site
                    if not best_match:
                        best_match = s
                    elif s.type == 'zone' and best_match.type == 'site':
                        best_match = s
                    
            return best_match # Return object to allow robust property access (e.g. name via feature)
        except Exception as e:
            current_app.logger.error(f"Error finding containing shape: {e}")
            return None
 
    @staticmethod
    def _sync_device_properties(feature):
        """
        Syncs properties (like Name) from the GeoJSON feature back to the source device models.
        This ensures that renaming a marker on the map persists in the main device configuration.
        """
        if not feature or 'properties' not in feature:
            return

        props = feature['properties']
        aot_type = props.get('aot_type')
        device_id = props.get('device_id')
        channel_id = props.get('channel_id')
        new_name = props.get('name')

        if not device_id or not new_name:
            return

        # [Fix] ID Unification Support: If device_id contains '::', split it
        if '::' in str(device_id):
            parts = str(device_id).split('::')
            device_id = parts[0]
            if channel_id is None:
                channel_id = parts[1]

        try:
            # 1. Handle Output Channels (The most common per-channel entity)
            if aot_type == 'output' or props.get('device_type') == 'output':
                # Try to find specific channel 
                ch_num = 0
                try: ch_num = int(channel_id) if channel_id is not None else 0
                except: pass
                
                channel_row = OutputChannel.query.filter_by(output_id=device_id, channel=ch_num).first()
                if channel_row:
                    channel_row.name = new_name
                    # [New] Also update name inside custom_options JSON if it exists
                    if hasattr(channel_row, 'custom_options') and channel_row.custom_options:
                        try:
                            co = json.loads(channel_row.custom_options)
                            if isinstance(co, dict) and 'name' in co:
                                co['name'] = new_name
                                channel_row.custom_options = json.dumps(co)
                        except:
                            pass
                    # current_app.logger.info(f"[GeoSync] Updated OutputChannel {device_id}:{ch_num} name to {new_name}")
                
            # 2. Handle Primary Device Models (Input, CustomController, etc.)
            # For Channel 0 or non-channel devices, we also update the main record
            if channel_id is None or str(channel_id) == '0':
                model_map = {
                    'input': Input,
                    'output': Output,
                    'pid': PID,
                    'trigger': Trigger,
                    'conditional': Conditional,
                    'function': CustomController,
                    'custom': CustomController,
                    'generic_function': Function
                }
                
                # Check both aot_type and device_type
                dev_type = props.get('device_type') or aot_type
                ModelClass = model_map.get(dev_type.lower()) if dev_type else None
                
                if ModelClass:
                    record = ModelClass.query.filter_by(unique_id=device_id).first()
                    if record and hasattr(record, 'name'):
                        record.name = new_name
                        # [New] Also update name inside custom_options JSON if it exists
                        if hasattr(record, 'custom_options') and record.custom_options:
                            try:
                                co = json.loads(record.custom_options)
                                if isinstance(co, dict) and 'name' in co:
                                    co['name'] = new_name
                                    record.custom_options = json.dumps(co)
                            except:
                                pass
                        # current_app.logger.info(f"[GeoSync] Updated {dev_type} {device_id} name to {new_name}")
                elif dev_type == 'function':
                     # Ambiguous 'function' type fallback
                     for M in [CustomController, PID, Trigger, Conditional, Function]:
                         record = M.query.filter_by(unique_id=device_id).first()
                         if record and hasattr(record, 'name'):
                             record.name = new_name
                             break

        except Exception as e:
            current_app.logger.error(f"[GeoSync] Property Sync Error: {e}")
