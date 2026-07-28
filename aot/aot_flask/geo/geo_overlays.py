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
                # [Fix] Inject Device/Channel IDs for Frontend Filtering (Strict Selection)
                if hasattr(s, 'device_id') and s.device_id:
                    feat['properties']['device_id'] = s.device_id
                if hasattr(s, 'channel_id') and s.channel_id:
                    feat['properties']['channel_id'] = s.channel_id

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

    @staticmethod
    def save_overlays(data):
        """
        Save Overlays with Validation.
        Strategy: Delta Sync (Diff-based Update/Delete/Insert) to prevent DB bloat.
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

            # 3. Analyze Incoming Payload
            incoming_ids = set()
            to_insert = []
            to_update = []

            for feat in new_features:
                props = feat.get('properties', {})
                db_id = props.get('db_id')
                
                # Check if this ID really exists in our scope (security check)
                if db_id and db_id in existing_ids:
                    incoming_ids.add(db_id)
                    to_update.append((db_id, feat))
                else:
                    to_insert.append(feat)
            
            # 4. Determine Deletions (Existing - Incoming)
            to_delete_ids = existing_ids - incoming_ids

            # [Safety] Block accidental full-wipe. An empty payload that would delete
            # existing rows is almost always a desync — a full-sync that fired before
            # overlays finished loading, or one pointed at a stale/wrong map — not an
            # intentional clear. (Individual deletes flow through /overlays/delta.)
            # Device-scoped clears (device_id set) and explicit allow_empty are exempt.
            if not new_features and to_delete_ids and not allow_empty and not device_id:
                current_app.logger.warning(
                    f"[GeoOverlay] Blocked empty-payload wipe "
                    f"(map={map_uuid}, type={target_type}, would_delete={len(to_delete_ids)}). "
                    "Pass allow_empty=true to confirm a full clear."
                )
                return {'ok': True, 'count': 0,
                        'stats': {'skipped': 'empty_wipe_blocked',
                                  'would_delete': len(to_delete_ids)}}, None

            # 5. Execute Operations

            # A. DELETE
            if to_delete_ids:
                 # Deleted shapes may be facility outlines — clean up their
                 # GeoFacility before the bulk shape delete (see docstring).
                 GeoOverlayManager._cascade_delete_facilities_for_shapes(to_delete_ids)
                 # Bulk Delete
                 query.filter(GeoShape.id.in_(to_delete_ids)).delete(synchronize_session=False)
                 
            # B. UPDATE
            for db_id, feat in to_update:
                row = existing_map[db_id]
                row.feature = feat # Update JSON
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
                    
                s.feature = feat
                db.session.add(s)
                
            db.session.commit()

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
                    'deleted': len(to_delete_ids),
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
            equip_upserts = [f for f in upserts
                             if f.get('properties', {}).get('aot_type') == 'equipment']
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
                    row.feature = feat
                    row.type = target_type
                    # Update columns if needed
                    if hasattr(row, 'device_id') and device_id: row.device_id = device_id
                    if hasattr(row, 'channel_id') and props.get('channel_id'): row.channel_id = str(props.get('channel_id'))
                    if hasattr(row, 'parent_id') and parent_id: row.parent_id = parent_id
                    row.updated_at = datetime.utcnow()
                    
                    # [New] Sync Properties (Name, etc.) back to Source Models
                    GeoOverlayManager._sync_device_properties(feat)
                else:
                    # Insert
                    row = GeoShape(geo_id=map_uuid, type=target_type, feature=feat)
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

            db.session.commit()
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
