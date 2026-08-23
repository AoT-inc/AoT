# coding=utf-8
"""
Facility I/O Manager.
CRUD for GeoFacility records and their linked GeoShape outer/bay polygons.
"""
from copy import deepcopy
from datetime import datetime
from flask import current_app

from sqlalchemy.orm.attributes import flag_modified

from aot.databases.models import GeoShape, GeoFacility
from aot.databases.models.geo import _flatten_coords
from aot.aot_flask.extensions import db


def _shift_coords(coords, dlng, dlat):
    """Recursively translate a GeoJSON coordinates array by (dlng, dlat)."""
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        return [coords[0] + dlng, coords[1] + dlat] + list(coords[2:])
    return [_shift_coords(c, dlng, dlat) for c in coords]


def _shift_geometry(geometry, dlng, dlat):
    """Translate a GeoJSON geometry dict by (dlng, dlat) degrees. Non-destructive."""
    if not geometry or not geometry.get('coordinates'):
        return geometry
    shifted = deepcopy(geometry)
    shifted['coordinates'] = _shift_coords(shifted['coordinates'], dlng, dlat)
    return shifted


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
            # [Phase B] 바인딩 색인을 한 번만 만든다 — 시설마다 조회하면
            # 목록 길이만큼 쿼리가 나간다(실측: 시설 11개 → 11회).
            try:
                from .device_binding import build_facility_index
                bindex = build_facility_index([r.unique_id for r in rows])
            except Exception:
                bindex = None
            return [FacilityManager._to_dict(r, include_shape=include_shape,
                                             binding_index=bindex)
                    for r in rows], None
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
        # [I6] aot_type 은 저장하지 않는다 — type 컬럼이 정본, 읽기 시 주입.
        def _build_feature(geometry, name):
            return {
                'type': 'Feature',
                'geometry': geometry,
                'properties': {
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
            # 구역 총량(p6_50)은 **시설을 다시 저장해도 살아남아야 한다.**
            # `bays_meta` 는 저장할 때마다 통째로 재생성되므로(위 도형 삭제 참조),
            # 사람이 적어 둔 총량이 여기서 그냥 사라진다 — 도형을 한 번 고쳤을
            # 뿐인데 구획의 분모가 없어지고 "4/12 베드" 가 "4" 로 읽힌다.
            # 그래서 id 로 이어받는다. 페이로드가 명시하면 그쪽이 이긴다.
            _prev_caps = {}
            for _b in (facility.bays if isinstance(facility.bays, list) else []):
                if isinstance(_b, dict) and _b.get('id') and _b.get('capacity'):
                    _prev_caps[_b['id']] = _b['capacity']

            def _with_cap(meta, src=None):
                cap = (src or {}).get('capacity')
                if cap is None:
                    cap = _prev_caps.get(meta.get('id'))
                if cap is not None:
                    meta['capacity'] = cap
                return meta

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
                    bays_meta.append(_with_cap({
                        'id':        str(z.get('id') or default_id),
                        'name':      z.get('name'),
                        'crop':      z.get('crop'),
                        'bay_start': s,
                        'bay_end':   e,
                    }, z))
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
                                'crop': bay.get('crop'),
                                'name': bay.get('name'),
                            }
                        }
                    )
                    db.session.add(bay_shape)
                    db.session.flush()
                    bays_meta.append(_with_cap({
                        'id': bay.get('id'),
                        'polygon_shape_uuid': bay_shape.unique_id,
                        'crop': bay.get('crop'),
                        'sensor_zone': bay.get('sensor_zone', []),
                        'name': bay.get('name'),
                    }, bay))
            elif facility.structure == 'single':
                bays_meta = [_with_cap({
                    'id': 'main',
                    'polygon_shape_uuid': shape.unique_id,
                    'crop': data.get('crop'),
                    'sensor_zone': data.get('sensor_zone', []),
                    'name': data.get('name'),
                }, data)]

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

            # [Phase C] 저장된 JSON 과 바인딩을 맞춘다.
            #
            # 이게 없으면 시설 편집기에서 fitting 의 장치를 **비워도 화면에는
            # 계속 옛 장치가 보인다** — 읽기(_to_dict)가 바인딩을 정본으로
            # 쓰기 때문에, 저장은 됐는데 바인딩이 그대로면 읽기가 저장을
            # 이긴다. Phase B-1 이 읽기를 바인딩으로 옮긴 순간 생긴 구멍이다.
            #
            # 페이로드가 아니라 **저장된 facility** 를 기준으로 부른다: 부분
            # 저장에서 페이로드를 기준으로 삼으면 "빠진 것 = 지운 것"이 되어
            # 멀쩡한 배정이 끊긴다(save_overlays 가 그 프로토콜로 도형을 잃었다).
            try:
                from aot.aot_flask.geo import device_binding
                with db.session.begin_nested():
                    device_binding.sync_facility_bindings(facility)
            except Exception as exc:
                current_app.logger.warning(
                    '[FacilityIO] 바인딩 동기화 실패(facility=%s) — %s',
                    facility.unique_id, exc)

            db.session.commit()

            # 구역 구성이 바뀌면 그 구역을 가리키던 **활성 구획**이 갈 곳을
            # 잃는다. 시설 구획은 위치의 정본이 `bay_id` 문자열이라, 구역이
            # 사라져도 에러가 나지 않고 지도에서 시설 외피로 슬그머니 넓어질
            # 뿐이다 — 저장한 사람은 아무것도 못 본다.
            #
            # **막지는 않는다.** 온실 구조를 바꾸는 것은 정당한 작업이고, 막으면
            # 구획을 먼저 지우는 것 말고는 길이 없어진다. 대신 무엇이 갈 곳을
            # 잃었는지 응답에 실어 사람이 결정하게 한다(문서 §대가 1).
            orphaned = FacilityManager._orphaned_plots(facility)

            return {
                'ok': True,
                'facility_uuid': facility.unique_id,
                'shape_uuid': shape.unique_id,
                'bays': bays_meta,
                'orphaned_plots': orphaned,
            }, None

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"FacilityManager.save error: {e}")
            return None, str(e)

    @staticmethod
    def _orphaned_plots(facility):
        """저장된 시설에서 **없는 구역을 가리키는 활성 구획** 목록.

        판정은 저장된 시설을 기준으로 한다 — 페이로드가 아니다. 부분 저장에서
        "페이로드에 없는 것 = 없앤 것" 으로 읽으면 멀쩡한 구역이 사라진 것으로
        잡힌다(`sync_facility_bindings` 가 같은 이유로 저장된 facility 를 본다).

        구역이 지정되지 않은 구획(`bay_id` NULL = 시설 전체)은 대상이 아니다.
        """
        try:
            from aot.databases.models import GeoPlot
            from .facility_bays import compute_bay_slices, spec_from_row

            valid = {sl['id'] for sl in compute_bay_slices(spec_from_row(facility))}
            if not valid:
                # 구역 목록을 못 만드는 시설(치수 미입력)에서는 판정하지 않는다 —
                # 근거 없이 "갈 곳을 잃었다" 고 말하면 멀쩡한 구획이 매 저장마다
                # 경고로 뜬다.
                return []

            rows = GeoPlot.query.filter(
                GeoPlot.facility_uuid == facility.unique_id,
                GeoPlot.bay_id.isnot(None),
                GeoPlot.ended_on.is_(None),
            ).all()
            out = [{'unique_id': r.unique_id, 'subject': r.subject, 'bay_id': r.bay_id}
                   for r in rows if r.bay_id not in valid]
            if out:
                current_app.logger.warning(
                    '[FacilityIO] 시설 %s 의 구역 구성 변경으로 활성 구획 %d 건이 '
                    '없는 구역을 가리킵니다: %s', facility.unique_id, len(out),
                    ', '.join('%s(%s)' % (o['subject'], o['bay_id']) for o in out))
            return out
        except Exception as exc:
            current_app.logger.warning(
                '[FacilityIO] 고아 구획 판정 실패(facility=%s): %s',
                getattr(facility, 'unique_id', None), exc)
            return []

    @staticmethod
    def clone_facility(source_uuid, user_id=None):
        """Duplicate a facility: same geometry/spec, device bindings reset to empty.

        Reuses save_facility's create path (new GeoShape, bay rebuild, binding
        sync) so the clone goes through the one verified code path. Device
        reference fields (fittings[].actuator_id/input_id/measurement_id,
        actuators[].device_uuid, weather_bindings) are stripped before
        handoff — sync_facility_bindings skips any slot with no device_id
        (device_binding.py `_want()`), so a cleared reference simply means no
        binding gets created for that slot. `sensors`/`commissioning_state`
        are legacy/derived columns save_facility never writes, so the new
        row keeps their column defaults (empty) automatically.
        """
        source = GeoFacility.query.filter_by(unique_id=source_uuid).first()
        if not source:
            return None, "Source facility not found"

        shape = GeoShape.query.filter_by(unique_id=source.shape_uuid).first()
        outer_geometry = (shape.feature or {}).get('geometry') if shape else None
        if not outer_geometry:
            return None, "Source facility has no placed geometry to copy"

        # Offset the clone east of the source by ~1.15x its own footprint width
        # so it lands next to the original instead of exactly on top of it
        # (an identical-geometry overlap is invisible on the map and trips
        # check_geo_integrity's duplicate detector). Falls back to a small
        # fixed offset (~20m) for a degenerate/point-like footprint.
        pts = _flatten_coords(outer_geometry.get('coordinates'))
        if pts:
            lngs = [p[0] for p in pts]
            width = max(lngs) - min(lngs)
            dlng = width * 1.15 if width > 1e-9 else 0.0002
        else:
            dlng = 0.0002
        outer_geometry = _shift_geometry(outer_geometry, dlng, 0.0)

        parent_site_uuid = None
        if shape and shape.parent_id:
            parent_site = GeoShape.query.filter_by(id=shape.parent_id, type='site').first()
            if parent_site:
                parent_site_uuid = parent_site.unique_id

        fittings = deepcopy(source.fittings) or []
        for fit in fittings:
            if isinstance(fit, dict):
                fit.pop('actuator_id', None)
                fit.pop('input_id', None)
                fit.pop('measurement_id', None)

        actuators = deepcopy(source.actuators)
        actuator_items = actuators.values() if isinstance(actuators, dict) else (actuators or [])
        for a in actuator_items:
            if isinstance(a, dict):
                a.pop('device_uuid', None)

        # bays: strip crop/sensor_zone (device refs), keep zone ranges or
        # geometry so save_facility can recreate 'connected'-structure bay
        # shapes. Ignored entirely for 'single' structure (see save_facility).
        bays_input = []
        for b in (deepcopy(source.bays) or []):
            if not isinstance(b, dict):
                continue
            entry = {'id': b.get('id'), 'name': b.get('name'), 'crop': None, 'sensor_zone': []}
            if b.get('bay_start') and b.get('bay_end'):
                entry['bay_start'] = b['bay_start']
                entry['bay_end'] = b['bay_end']
            poly_uuid = b.get('polygon_shape_uuid')
            if poly_uuid:
                bay_shape = GeoShape.query.filter_by(unique_id=poly_uuid).first()
                if bay_shape and bay_shape.feature:
                    # Same translation as the outer polygon, so bays stay
                    # aligned with the shifted footprint.
                    entry['geometry'] = _shift_geometry(
                        (bay_shape.feature or {}).get('geometry'), dlng, 0.0)
            bays_input.append(entry)

        payload = {
            'geo_id': source.geo_id,
            'name': f"{source.name} 복제" if source.name else 'New Facility',
            'preset': source.preset,
            'structure': source.structure,
            'bay_count': source.bay_count,
            'outer_geometry': outer_geometry,
            'geometry_3d': deepcopy(source.geometry_3d),
            'envelope': deepcopy(source.envelope),
            'actuators': actuators,
            'fittings': fittings,
            'computed': deepcopy(source.computed),
            'notes': '',
            'bays': bays_input,
            'view_options': deepcopy(source.view_options),
            'weather_bindings': [],
            'groups': deepcopy(source.groups) or {},
        }
        if parent_site_uuid:
            payload['site_shape_uuid'] = parent_site_uuid

        result, err = FacilityManager.save_facility(payload, user_id=user_id)
        if err:
            return result, err

        # Carry over fields save_facility never writes (timezone override,
        # 3D asset override) — these aren't device references, so copying
        # them keeps the clone visually/behaviorally identical apart from
        # the reset bindings.
        try:
            new_facility = GeoFacility.query.filter_by(unique_id=result['facility_uuid']).first()
            if new_facility:
                new_facility.timezone = source.timezone
                new_facility.tz_source = source.tz_source
                new_facility.model_asset_uuid = source.model_asset_uuid
                new_facility.model_transform = deepcopy(source.model_transform)
                new_facility.render_mode = source.render_mode
                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.warning(
                '[FacilityIO] 복제 후 부가필드 복사 실패(facility=%s) — %s',
                result.get('facility_uuid'), exc)

        return result, None

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
    def _to_dict(f, include_shape=False, binding_index=None):
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
        # [Phase B] 장치 참조(fittings.actuator_id/input_id,
        # actuators.device_uuid)를 geo_binding 기준으로 맞춘다. 이 한 곳이
        # 시설 JSON 의 유일한 출구라, 여기 걸면 하위 소비처
        # (facility_integration · irrigation_nozzles · facility_wind ·
        # facility_calc · 3D 위젯)가 한 줄도 안 바뀌고 바인딩을 읽는다.
        # 바인딩이 없으면 저장된 값 그대로(폴백) — 전환기 동안 안전하다.
        try:
            from .device_binding import resolve_facility_payload
            resolve_facility_payload(f.unique_id, d, index=binding_index)
        except Exception as exc:
            # 해석 실패가 시설 조회 자체를 막으면 안 된다 — 폴백 값이 이미
            # payload 에 들어 있으므로 종전 동작으로 계속 간다.
            current_app.logger.warning(
                '[FacilityIO] 바인딩 해석 실패(%s) — 저장값으로 계속: %s',
                f.unique_id, exc)

        # bay 슬라이스(폭 방향 로컬 미터 구간) — 지도/3D 위젯의 구역 라벨 배치용.
        # 지연 import: facility_bays 는 모델만 다루는 순수 계산 모듈.
        try:
            from .facility_bays import compute_bay_slices
            d['bay_slices'] = compute_bay_slices(d)
        except Exception:
            d['bay_slices'] = []
        # 구역 총량(p6_50) — 구획의 몫이 이것을 분모로 삼는다. 시설 런타임
        # (`/api/aot/facility/<uuid>/runtime`)이 이미 같은 값을 내보내는데,
        # **시설 편집기는 그 API 를 쓰지 않는다.** 두 화면이 같은 폼을 쓰므로
        # 여기서도 내야 접미("/12 베드")가 화면마다 갈리지 않는다.
        try:
            from .plot_context import bay_capacities
            d['bay_capacities'] = bay_capacities(f)
        except Exception:
            d['bay_capacities'] = {}
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
