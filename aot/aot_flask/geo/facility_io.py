# coding=utf-8
"""
Facility I/O Manager.
CRUD for GeoFacility records and their linked GeoShape outer/bay polygons.
"""
from datetime import datetime
from flask import current_app

from sqlalchemy.orm.attributes import flag_modified

from aot.databases.models import GeoShape, GeoFacility
from aot.databases.models.geo import _flatten_coords
from aot.aot_flask.extensions import db


def _geometry_centroid(geometry):
    """GeoJSON geometry dict → (lat, lng) centroid tuple, or None if no coordinates."""
    if not geometry:
        return None
    coords_raw = geometry.get('coordinates')
    if not coords_raw:
        return None
    pts = _flatten_coords(coords_raw)
    if not pts:
        return None
    avg_lng = sum(p[0] for p in pts) / len(pts)
    avg_lat = sum(p[1] for p in pts) / len(pts)
    return (avg_lat, avg_lng)


class FacilityManager:
    """Manages GeoFacility records and their linked GeoShape polygons.

    Atomically synchronizes:
      - Outer polygon  → GeoShape (type='facility')
      - Facility specs → GeoFacility
      - Bay polygons   → GeoShape (type='facility_bay', parent_id=outer.id)

    @phase active
    """

    @staticmethod
    def list_facilities(geo_id=None, include_shape=True):
        """List facilities, optionally filtered by GeoMap unique_id.

        include_shape=True (default): outer_feature is attached so the map
        can render facility footprints + 3D extrusion without a second roundtrip.
        """
        try:
            query = GeoFacility.query
            if geo_id:
                query = query.filter_by(geo_id=geo_id)
            rows = query.order_by(GeoFacility.updated_at.desc()).all()
            return [FacilityManager._to_dict(r, include_shape=include_shape) for r in rows], None
        except Exception as e:
            current_app.logger.error(f"FacilityManager.list error: {e}")
            return None, str(e)

    @staticmethod
    def get_facility(facility_uuid):
        """Get one facility by unique_id with its outer polygon feature."""
        try:
            row = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
            if not row:
                return None, "Facility not found"
            return FacilityManager._to_dict(row, include_shape=True), None
        except Exception as e:
            current_app.logger.error(f"FacilityManager.get error: {e}")
            return None, str(e)

    @staticmethod
    def save_facility(data, user_id=None):
        """Upsert facility (outer shape + spec + bay shapes) in one transaction.

        Payload keys:
          facility_uuid (optional) — present for update, absent for create
          geo_id (required)        — GeoMap.unique_id
          name, preset, structure, bay_count
          outer_geometry           — GeoJSON geometry of the outer polygon
          geometry_3d, envelope, actuators, fittings, computed, notes
          bays                     — list of {id, geometry, crop, sensor_zone, name}

        Fittings (G1 policy): list of placed 3D elements; authoritative for
        vent area and airflow when present.
        """
        facility_uuid = data.get('facility_uuid')
        geo_id = data.get('geo_id')
        outer_geometry = data.get('outer_geometry')
        bays_input = data.get('bays', []) or []
        site_shape_uuid = data.get('site_shape_uuid')

        if not geo_id:
            return None, "Missing geo_id"
        if not facility_uuid and not outer_geometry:
            return None, "Missing outer_geometry for new facility"

        # Resolve site → parent_id mapping (option Y: hierarchy via GeoShape.parent_id)
        parent_site_id = None
        if site_shape_uuid:
            site_shape = GeoShape.query.filter_by(
                unique_id=site_shape_uuid, type='site'
            ).first()
            if site_shape:
                parent_site_id = site_shape.id

        # Outer polygon feature builder (geo_shape.feature is NOT NULL)
        def _build_feature(geometry, name):
            return {
                'type': 'Feature',
                'geometry': geometry,
                'properties': {
                    'aot_type': 'facility',
                    'name': name or 'New Facility',
                }
            }

        try:
            # 1. Resolve or create facility + outer shape
            # Pattern: instantiate empty, set attrs, then add — matches geo_overlays.py
            # so SQLAlchemy reliably tracks JSON column writes before flush.
            if facility_uuid:
                facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
                if not facility:
                    return None, "Facility not found"
                shape = GeoShape.query.filter_by(unique_id=facility.shape_uuid).first()
                if not shape:
                    if not outer_geometry:
                        return None, "Missing outer_geometry to recover deleted shape"
                    shape = GeoShape()
                    shape.type = 'facility'
                    shape.geo_id = geo_id
                    shape.feature = _build_feature(outer_geometry, data.get('name'))
                    db.session.add(shape)
                    db.session.flush()
                    current_app.logger.info(
                        f"[FacilityManager] auto-recovered shape {shape.unique_id} "
                        f"for facility {facility_uuid}"
                    )
            else:
                facility = GeoFacility()
                shape = GeoShape()
                shape.type = 'facility'
                shape.geo_id = geo_id
                shape.feature = _build_feature(outer_geometry, data.get('name'))
                db.session.add(shape)
                db.session.flush()
                current_app.logger.info(
                    f"[FacilityManager] created new shape {shape.unique_id} "
                    f"(geo_id={geo_id}, has_geometry={outer_geometry is not None})"
                )

            # Defensive: feature must never be None at this point
            if shape.feature is None:
                shape.feature = _build_feature(outer_geometry or {}, data.get('name'))

            # 2. Update outer polygon feature on existing shape (if geometry provided)
            if outer_geometry:
                shape.feature = _build_feature(outer_geometry, data.get('name'))
            shape.geo_id = geo_id
            shape.updated_at = datetime.utcnow()

            # Apply site hierarchy: only overwrite parent_id when explicitly sent.
            # `site_shape_uuid` absent in payload → keep existing parent_id (do nothing).
            # `site_shape_uuid` empty string → clear parent_id (user de-selected site).
            if 'site_shape_uuid' in data:
                shape.parent_id = parent_site_id  # None when uuid is empty/invalid

            # 3. Facility spec
            facility.shape_uuid = shape.unique_id
            facility.geo_id = geo_id
            facility.name = data.get('name', facility.name or 'New Facility')
            facility.preset = data.get('preset', 'standard_arch')
            facility.structure = data.get('structure', 'single')
            facility.bay_count = data.get('bay_count', 1)
            facility.geometry_3d = data.get('geometry_3d')
            facility.envelope = data.get('envelope')
            facility.actuators = data.get('actuators')
            # Fittings: list of placed elements from the 3D editor (FittingsUI).
            # Authoritative source for vent area & airflow simulation (G1 policy).
            facility.fittings = data.get('fittings') or []
            flag_modified(facility, 'fittings')  # SQLAlchemy JSON 컬럼 변경 강제 감지
            # view_options: UI 표시 옵션 (카테고리 가시성 + 액추에이터 표시 순서).
            # AoT_map 위젯도 동일 값 읽음. actuator_order 는 위젯의 드래그 정렬에서
            # 별도 엔드포인트로 저장되므로, 디자인 에디터 저장 페이로드에 없을 때
            # 기존 값을 보존해 순서 유실을 막는다.
            new_view_options = data.get('view_options') or None
            try:
                prev_order = (facility.view_options or {}).get('actuator_order')
                if prev_order:
                    if isinstance(new_view_options, dict):
                        if 'actuator_order' not in new_view_options:
                            new_view_options['actuator_order'] = prev_order
                    elif new_view_options is None:
                        new_view_options = {'actuator_order': prev_order}
            except Exception:
                pass
            facility.view_options = new_view_options
            flag_modified(facility, 'view_options')  # JSON 컬럼 변경 강제 감지
            facility.computed = data.get('computed')
            # weather_bindings: 기상/예보 Input 장치 연결 목록.
            # 사용자가 어떤 예보 서비스(OpenMeteo, OWM, KMA, ...)를 연결하든
            # measurement_type 으로 식별하고 facility_sensors.read_forecast_sensors() 가 읽는다.
            if 'weather_bindings' in data:
                facility.weather_bindings = data.get('weather_bindings') or []
                flag_modified(facility, 'weather_bindings')
            # groups: 복합 액추에이터 그룹 정의 (multi_stage, stacked, windward_diff 등).
            # env_coordinator 의 group_expander 가 이 설정으로 팔로워 명령을 확장한다.
            if 'groups' in data:
                facility.groups = data.get('groups') or {}
                flag_modified(facility, 'groups')
            facility.notes = data.get('notes', '')
            facility.updated_at = datetime.utcnow()
            if user_id and not facility.created_by:
                facility.created_by = str(user_id)

            if facility.id is None:
                db.session.add(facility)
            db.session.flush()

            # 4. Rebuild bay shapes (connected only)
            outer_shape_id = shape.id
            old_bays = GeoShape.query.filter_by(
                geo_id=geo_id, type='facility_bay', parent_id=outer_shape_id
            ).all()
            for ob in old_bays:
                db.session.delete(ob)

            bays_meta = []
            # 구역(zone) 정의 — 편집기 구역 UI 가 보내는 bay 범위 항목.
            # {id, name, crop, bay_start, bay_end} (1-based, inclusive).
            # 폴리곤은 만들지 않는다: 슬라이스 좌표는 geometry_3d 에서 파생
            # (facility_bays.compute_bay_slices). 범위가 유효한 항목만 저장.
            zone_input = [
                b for b in bays_input
                if isinstance(b, dict) and b.get('bay_start') and b.get('bay_end')
            ]
            if zone_input:
                try:
                    _bc = int(facility.bay_count or 1)
                except (TypeError, ValueError):
                    _bc = 1
                for z in sorted(zone_input, key=lambda b: int(b.get('bay_start') or 0)):
                    try:
                        s, e = int(z['bay_start']), int(z['bay_end'])
                    except (TypeError, ValueError):
                        continue
                    if not (1 <= s <= e <= _bc):
                        continue
                    default_id = 'bay_%d' % s if s == e else 'bay_%d_%d' % (s, e)
                    bays_meta.append({
                        'id':        str(z.get('id') or default_id),
                        'name':      z.get('name'),
                        'crop':      z.get('crop'),
                        'bay_start': s,
                        'bay_end':   e,
                    })
            elif facility.structure == 'connected' and bays_input:
                for bay in bays_input:
                    bay_geom = bay.get('geometry')
                    if not bay_geom:
                        continue
                    bay_shape = GeoShape(
                        type='facility_bay',
                        geo_id=geo_id,
                        parent_id=outer_shape_id,
                        feature={
                            'type': 'Feature',
                            'geometry': bay_geom,
                            'properties': {
                                'aot_type': 'facility_bay',
                                'crop': bay.get('crop'),
                                'name': bay.get('name'),
                            }
                        }
                    )
                    db.session.add(bay_shape)
                    db.session.flush()
                    bays_meta.append({
                        'id': bay.get('id'),
                        'polygon_shape_uuid': bay_shape.unique_id,
                        'crop': bay.get('crop'),
                        'sensor_zone': bay.get('sensor_zone', []),
                        'name': bay.get('name'),
                    })
            elif facility.structure == 'single':
                bays_meta = [{
                    'id': 'main',
                    'polygon_shape_uuid': shape.unique_id,
                    'crop': data.get('crop'),
                    'sensor_zone': data.get('sensor_zone', []),
                    'name': data.get('name'),
                }]

            facility.bays = bays_meta

            # Backfill gps_lat/gps_lng on linked Notes when geometry is placed or updated.
            # Notes with target_type='facility' that have no position yet (or had stale position)
            # are updated to the polygon centroid so they appear on the map automatically.
            if outer_geometry:
                centroid = _geometry_centroid(outer_geometry)
                if centroid:
                    from aot.databases.models import Notes
                    linked_notes = Notes.query.filter_by(
                        target_type='facility',
                        target_id=facility.unique_id,
                    ).all()
                    for n in linked_notes:
                        n.gps_lat, n.gps_lng = centroid

            db.session.commit()
            return {
                'ok': True,
                'facility_uuid': facility.unique_id,
                'shape_uuid': shape.unique_id,
                'bays': bays_meta,
            }, None

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"FacilityManager.save error: {e}")
            return None, str(e)

    @staticmethod
    def delete_facility(facility_uuid, confirm_name=None):
        """Delete a facility — Constitution Art.5 confirmation enforced.

        Removes GeoFacility, outer GeoShape, and all bay shapes
        (parent_id=outer.id, type='facility_bay').
        """
        try:
            facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
            if not facility:
                return None, "Facility not found"

            if confirm_name is None or confirm_name != facility.name:
                return None, (
                    f"Confirmation required: reply with exact facility name "
                    f"'{facility.name}' to delete."
                )

            shape = GeoShape.query.filter_by(unique_id=facility.shape_uuid).first()
            if shape:
                bays = GeoShape.query.filter_by(parent_id=shape.id, type='facility_bay').all()
                for b in bays:
                    db.session.delete(b)
                db.session.delete(shape)

            db.session.delete(facility)
            db.session.commit()
            return {'ok': True, 'deleted': facility_uuid}, None
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"FacilityManager.delete error: {e}")
            return None, str(e)

    @staticmethod
    def _to_dict(f, include_shape=False):
        d = {
            'unique_id': f.unique_id,
            'shape_uuid': f.shape_uuid,
            'geo_id': f.geo_id,
            'name': f.name,
            'preset': f.preset,
            'structure': f.structure,
            'bay_count': f.bay_count,
            'geometry_3d': f.geometry_3d,
            'envelope': f.envelope,
            'actuators': f.actuators,
            'fittings': f.fittings or [],
            'groups': f.groups or {},
            'view_options': f.view_options or None,
            'bays': f.bays,
            'computed': f.computed,
            'notes': f.notes,
            'weather_bindings': f.weather_bindings or [],
            'created_at': f.created_at.isoformat() if f.created_at else None,
            'updated_at': f.updated_at.isoformat() if f.updated_at else None,
        }
        # bay 슬라이스(폭 방향 로컬 미터 구간) — 지도/3D 위젯의 구역 라벨 배치용.
        # 지연 import: facility_bays 는 모델만 다루는 순수 계산 모듈.
        try:
            from .facility_bays import compute_bay_slices
            d['bay_slices'] = compute_bay_slices(d)
        except Exception:
            d['bay_slices'] = []
        if include_shape and f.shape is not None:
            d['outer_feature'] = f.shape.feature
            d['parent_id'] = f.shape.parent_id
            # Resolve parent site (option Y) for client-side selector restore
            if f.shape.parent_id:
                site_shape = GeoShape.query.filter_by(id=f.shape.parent_id).first()
                if site_shape and site_shape.type == 'site':
                    d['parent_site_uuid'] = site_shape.unique_id
                    site_props = (site_shape.feature or {}).get('properties', {}) if isinstance(site_shape.feature, dict) else {}
                    d['parent_site_name'] = site_props.get('name', '')
        return d
