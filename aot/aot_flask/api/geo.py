# coding=utf-8
import json
import traceback
from datetime import datetime

from flask import request, current_app
from werkzeug.exceptions import HTTPException
from flask_restx import Resource, abort, fields
from flask_login import login_required
from sqlalchemy import or_

from flask_babel import gettext as _
from aot.databases.models import GeoMap, GeoShape, GeoSetting, Input, Output, GeoLayer, PID, Trigger, Conditional, CustomController, Function
from aot.aot_flask.api import api, default_responses
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_general, utils_geo
from aot.utils.inputs import parse_input_information
from aot.utils.timekit import naive_utc, utc_now

ns_geo = api.namespace('geo', description='Geo Information Services')

# --- Models ---
geo_overlay_model = ns_geo.model('GeoOverlay', {
    'type': fields.String(description='FeatureCollection'),
    'features': fields.List(fields.Raw, description='GeoJSON Features'),
    'level_id': fields.Integer(description='Hierarchy Level (1=Site, 2=Zone, 3=Device)'),
    'channel_id': fields.String(description='Logical Channel ID'),
    'map_uuid': fields.String(required=True, description='Target Map UUID'),
})

geo_design_model = ns_geo.model('GeoDesign', {
    'map_uuid': fields.String(description='Map UUID (Optional for create)'),
    'name': fields.String(required=True, description='Map Name'),
    'state_json': fields.String(description='Full Map State in JSON string')
})

# --- Resources ---

@ns_geo.route('/designs')
class GeoDesigns(Resource):
    # @manual geo/api-reference#design-maps
    @ns_geo.doc(responses=default_responses)
    @login_required
    def get(self):
        """Get List of all Design Maps"""
        try:
            # [P3] 모든 지도가 동등하다 — category 분기 폐기.
            all_maps = GeoMap.query.order_by(GeoMap.updated_at.desc()).all()
            result = []
            for m in all_maps:
                # 저장된 카메라는 state_json 'center' 에 {lat, lng}(지도 저장·새 지도
                # 시작 위치) 또는 [lat, lng](init_design 이 만든 첫 지도)로 있다.
                # 리스트로만 읽으면 {lat, lng} 인 지도가 전부 기본값(서울)으로
                # 나간다 — 두 형식을 푸는 곳은 GeoMap.viewport() 하나다
                # (routes_geo_map.api_geo_designs_list 와 같은 규칙).
                lat, lng, zoom = m.viewport()
                result.append({
                    'unique_id': m.unique_id,
                    'name': m.name,
                    # 시작 위치가 없으면 세계 전도(0,0 줌 2) — 도시 리터럴 없음.
                    'latitude': lat if lat is not None else 0,
                    'longitude': lng if lng is not None else 0,
                    'zoom': zoom if zoom is not None else (13 if lat is not None else 2)
                })
            return result
        except Exception as e:
            abort(500, message=str(e))

    # @manual geo/design-tool#manual-save, geo/api-reference#design-maps
    @ns_geo.doc(responses=default_responses)
    @ns_geo.expect(geo_design_model)
    @login_required
    def post(self):
        """Create or Update GeoMap Metadata & State"""
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        from aot.aot_flask.geo import GeoDesignManager
        data = request.get_json() or {}

        # 그룹 스코프 — 지도는 자기 자신이 부여 단위다.
        #
        # (예전에 `routes_geo.api_geo_design_save` 가 같은 URL 로 이중 등록돼
        # 있었다 — 등록 순서에 기대는 상태였고 한쪽만 막으면 조용히 뚫렸다.
        # 그 중복 등록은 제거했다: 정본은 이 경로 하나뿐이다.
        # 정본: docs/design/access-scope-groups.md)
        from aot.aot_flask.access import scope
        _map_uuid = data.get('map_uuid')
        if _map_uuid and not scope.can_operate('geo_map', _map_uuid):
            abort(403, message=scope.deny_message())

        from flask_login import current_user
        result, error = GeoDesignManager.save_design_map(data, current_user.id)
        if error:
            abort(500, message=error)
        return result

@ns_geo.route('/designs/<string:map_uuid>')
class GeoDesignDetail(Resource):
    # @manual geo/api-reference#design-maps
    @ns_geo.doc(responses=default_responses)
    @login_required
    def get(self, map_uuid):
        """Get GeoMap Metadata & State by UUID"""
        from aot.aot_flask.geo import GeoDesignManager
        result, error = GeoDesignManager.get_design_map(map_uuid)
        if error:
            abort(404 if "not found" in error else 500, message=error)
        return result

    # @manual geo/design-tool#deleting-a-map, geo/api-reference#design-maps
    @ns_geo.doc(responses=default_responses)
    @login_required
    def delete(self, map_uuid):
        """Delete GeoMap"""
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        # 그룹 스코프 — 지도는 자기 자신이 부여 단위다.
        from aot.aot_flask.access import scope
        if not scope.can_operate('geo_map', map_uuid):
            abort(403, message=scope.deny_message())
        from aot.aot_flask.geo import GeoDesignManager
        result, error = GeoDesignManager.delete_design_map(map_uuid)
        if error:
            # 아직 쓰는 곳이 있어 거절한 것은 서버 오류가 아니다.
            blocked = isinstance(result, dict) and result.get('blocked')
            abort(409 if blocked else 500, message=error)
        return result


@ns_geo.route('/maps/<string:map_uuid>/restore-original')
class GeoMapRestoreOriginal(Resource):
    # @manual geo/api-reference#design-maps
    @ns_geo.doc(responses=default_responses)
    @login_required
    def post(self, map_uuid):
        """Restore all migrated overlays for a map to their original pre-migration data."""
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        # 그룹 스코프 — 그 지도의 도형을 통째로 되돌리는 경로다.
        from aot.aot_flask.access import scope
        if not scope.can_operate('geo_map', map_uuid):
            abort(403, message=scope.deny_message())
        try:
            from aot.aot_flask.extensions import db
            import json

            # Check migration columns exist before using them
            try:
                rows = db.session.execute(
                    db.text(
                        "SELECT id, feature, original_data, migrated_from_version "
                        "FROM geo_shape WHERE geo_id=:uuid AND original_data IS NOT NULL"
                    ),
                    {'uuid': map_uuid}
                ).fetchall()
            except Exception:
                abort(400, message='Migration tracking columns not available. Run alembic upgrade head first.')

            restored = 0
            skipped = 0
            for row in rows:
                try:
                    original = json.loads(row.original_data)
                    # [I6] 복원 시에도 aot_type 은 되살리지 않는다 — 종류의
                    # 정본은 type 컬럼이고, 구 blob 의 aot_type 을 다시 심으면
                    # 정확히 p6_21 이 고친 드리프트를 재생산한다.
                    _p = original.get('properties') if isinstance(original, dict) else None
                    if isinstance(_p, dict) and 'aot_type' in _p:
                        original = dict(original)
                        original['properties'] = {
                            k: v for k, v in _p.items() if k != 'aot_type'}
                    db.session.execute(
                        db.text(
                            "UPDATE geo_shape SET feature=:feat, schema_version=:sv, "
                            "original_data=NULL, migrated_at=NULL, migrated_from_version=NULL "
                            "WHERE id=:id"
                        ),
                        {
                            'feat': json.dumps(original),
                            'sv': row.migrated_from_version,
                            'id': row.id
                        }
                    )
                    restored += 1
                except Exception:
                    skipped += 1

            db.session.commit()
            return {
                'ok': True,
                'map_uuid': map_uuid,
                'restored': restored,
                'skipped': skipped
            }
        except HTTPException:
            # 위의 abort(400)(추적 컬럼 없음)은 요청 쪽 문제다 — 아래
            # except Exception 이 잡으면 500 으로 바뀌어 원인이 가려진다.
            raise
        except Exception as e:
            current_app.logger.error(f'Restore original error: {e}')
            abort(500, message=str(e))


@ns_geo.route('/overlays')
class GeoOverlays(Resource):
    # @manual geo/api-reference#overlays-shapes-geojson
    @ns_geo.doc(responses=default_responses)
    @login_required
    def get(self):
        """Get Overlays for a map"""
        from aot.aot_flask.geo import GeoOverlayManager
        map_uuid = request.args.get('map_uuid')
        target_type = request.args.get('type')
        parent_id = request.args.get('parent_id')
        device_id = request.args.get('device_id')
        result, error = GeoOverlayManager.get_overlays(map_uuid, target_type, parent_id, device_id=device_id)
        if error:
            abort(500, message=error)
        # 지도 하나의 도형은 한 화면에서 여러 위젯이 거듭 읽는다(실측: 대시보드
        # 한 번에 3회, 호출당 95KB). 본문 해시를 ETag 로 달아 브라우저가 재검증만
        # 하고 본문은 304 로 건너뛰게 한다 — 서버 계산은 그대로라 줄이는 것은 회선이다.
        from flask import jsonify
        from aot.aot_flask.utils import utils_http
        return utils_http.json_conditional(jsonify(result), request)

    # @manual geo/design-tool#manual-save, geo/api-reference#details-post-apigeooverlays
    @ns_geo.doc(responses=default_responses)
    @ns_geo.expect(geo_overlay_model)
    @login_required
    def post(self):
        """Bulk Save Overlays"""
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        from aot.aot_flask.geo import GeoOverlayManager
        data = request.get_json() or {}

        # 그룹 스코프 — 도형은 지도에 속한다. 여기를 막지 않으면 부여된 지도의
        # 도형을 남이 통째로 갈아치울 수 있다(이 경로는 전량 교체다).
        from aot.aot_flask.access import scope
        if not scope.can_operate('geo_map', data.get('map_uuid')):
            abort(403, message=scope.deny_message())

        result, error = GeoOverlayManager.save_overlays(data)
        if error:
            abort(500, message=error)
        return result

@ns_geo.route('/search')
class GeoSearch(Resource):
    # @manual geo/api-reference#search
    @ns_geo.doc(responses=default_responses)
    @login_required
    def post(self):
        """Execute Search via GIS Provider (Address, Coordinate, etc.)"""
        try:
            # Try getting data from multiple sources to be safe
            data = api.payload
            if not data:
                data = request.get_json(silent=True, force=True)
            
            if not data:
                return {'ok': False, 'message': 'Failed to decode JSON payload'}, 400

            layer_id = data.get('layer_id')
            query = data.get('query')
            search_type = data.get('type', 'address')
            
            if not query:
                return {'ok': False, 'message': 'Missing query'}, 400
                
            from aot.aot_flask.geo import geo_lookup
            try:
                result = geo_lookup.raw_search(query, provider=layer_id, search_type=search_type)
            except geo_lookup.GeoLookupError as e:
                return {'ok': False, 'message': e.message}, e.status

            if isinstance(result, dict) and 'error' in result:
                return {'ok': False, 'message': result['error']}, 200
                 
            return {'ok': True, 'results': result}

        except Exception as e:
            current_app.logger.error(f" [GeoAPI] Search Exception: {e}")
            return {'ok': False, 'message': str(e)}, 500

#: 좌표 → 주소 응답을 잠깐 담아 둔다 — 같은 자리를 다시 묻거나 시트를 다시 열 때 외부 지오코더를 또 부르지 않게
#: (Nominatim 은 초당 1건 정책). 좌표는 소수 5자리(약 1m)로 묶고, 성공한 것만 담는다.
_ADDRESS_CACHE = {}
_ADDRESS_CACHE_TTL_S = 3600
_ADDRESS_CACHE_MAX = 256


@ns_geo.route('/address')
class GeoAddress(Resource):
    # @manual geo/api-reference#search
    @ns_geo.doc(responses=default_responses)
    @login_required
    def get(self):
        """Reverse geocode (lat, lng -> address) through the GIS Input lookup gate."""
        import time
        from aot.aot_flask.geo import geo_lookup
        try:
            lat = float(request.args.get('lat'))
            lng = float(request.args.get('lng'))
        except (TypeError, ValueError):
            return {'ok': False, 'message': 'lat and lng are required numbers'}, 400
        key = (round(lat, 5), round(lng, 5))
        now = time.time()
        hit = _ADDRESS_CACHE.get(key)
        if hit and now - hit[0] < _ADDRESS_CACHE_TTL_S:
            return hit[1]
        found = geo_lookup.find_address(lat, lng)
        if found.get('status') != 'ok':
            return {'ok': False, 'code': found.get('code'), 'message': found.get('error')}, 200
        out = {'ok': True, 'address': found['address'], 'type': found.get('type'),
               'provider': found['provider']['type']}
        if len(_ADDRESS_CACHE) >= _ADDRESS_CACHE_MAX:
            _ADDRESS_CACHE.clear()
        _ADDRESS_CACHE[key] = (now, out)
        return out


def _fav_user():
    import flask_login
    return flask_login.current_user.name


def _fav_write_guard():
    if not utils_general.user_has_permission('edit_settings'):
        return {'ok': False, 'message': 'Insufficient permission'}, 403
    return None


def _fav_error(e):
    return {'ok': False, 'code': e.code, 'message': e.message}, e.status


@ns_geo.route('/favorites')
class GeoFavorites(Resource):
    # @manual geo/api-reference#search
    @ns_geo.doc(responses=default_responses)
    @login_required
    def get(self):
        """List the map favorites visible to this user (shared ones and the user's own)."""
        from aot.aot_flask.geo import geo_favorites
        return {'ok': True, 'favorites': geo_favorites.listing(_fav_user())}

    @ns_geo.doc(responses=default_responses)
    @login_required
    def post(self):
        """Save a place: {name, lat, lng, address, shared}. The same spot (about 1 m) is not added twice."""
        from aot.aot_flask.geo import geo_favorites
        denied = _fav_write_guard()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        try:
            row, created = geo_favorites.add(data.get('name'), data.get('lat'), data.get('lng'),
                                             data.get('address'), created_by=_fav_user(),
                                             shared=data.get('shared', True))
        except geo_favorites.FavoriteError as e:
            return _fav_error(e)
        return {'ok': True, 'created': created, 'favorite': geo_favorites.to_dict(row, _fav_user())}


@ns_geo.route('/favorites/<int:favorite_id>')
class GeoFavoriteItem(Resource):
    @ns_geo.doc(responses=default_responses)
    @login_required
    def patch(self, favorite_id):
        """Rename a favorite and/or change its sharing: {name?, shared?} (sharing: owner only)."""
        from aot.aot_flask.geo import geo_favorites
        denied = _fav_write_guard()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        try:
            row = geo_favorites.update(favorite_id, _fav_user(), name=data.get('name'), shared=data.get('shared'))
        except geo_favorites.FavoriteError as e:
            return _fav_error(e)
        return {'ok': True, 'favorite': geo_favorites.to_dict(row, _fav_user())}

    @ns_geo.doc(responses=default_responses)
    @login_required
    def delete(self, favorite_id):
        """Remove a favorite."""
        from aot.aot_flask.geo import geo_favorites
        denied = _fav_write_guard()
        if denied:
            return denied
        try:
            geo_favorites.remove(favorite_id, _fav_user())
        except geo_favorites.FavoriteError as e:
            return _fav_error(e)
        return {'ok': True}


@ns_geo.route('/favorites/<int:favorite_id>/move')
class GeoFavoriteMove(Resource):
    @ns_geo.doc(responses=default_responses)
    @login_required
    def post(self, favorite_id):
        """Move a favorite one step in the list: {direction: 'up'|'down'}."""
        from aot.aot_flask.geo import geo_favorites
        denied = _fav_write_guard()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        try:
            geo_favorites.move(favorite_id, _fav_user(), data.get('direction'))
        except geo_favorites.FavoriteError as e:
            return _fav_error(e)
        return {'ok': True, 'favorites': geo_favorites.listing(_fav_user())}


@ns_geo.route('/around')
class GeoAround(Resource):
    @ns_geo.doc(responses=default_responses)
    @login_required
    def get(self):
        """Which zone/plot a point is in and which devices are near it (names only) — the same reading the AI gets."""
        from aot.databases.models import Widget
        from aot.utils import geo_distance
        try:
            lat = float(request.args.get('lat'))
            lng = float(request.args.get('lng'))
        except (TypeError, ValueError):
            return {'ok': False, 'message': 'lat and lng are required numbers'}, 400
        map_uuid = None
        wid = request.args.get('widget_id')
        if wid:
            w = Widget.query.filter(Widget.unique_id == wid).first()
            if w is not None:
                try:
                    map_uuid = json.loads(w.custom_options or '{}').get('map_uuid')
                except ValueError:
                    map_uuid = None
        around = geo_distance.around_point(lat, lng, 1, map_uuid=map_uuid)
        return {'ok': True, 'inside': around.get('inside', []), 'edge': around.get('edge', []),
                'near': around.get('near', [])}


geo_binding_model = ns_geo.model('GeoBinding', {
    'spatial_kind': fields.String(required=True,
                                  description="shape|fitting|actuator|sensor_role|weather"),
    'spatial_id': fields.String(required=True, description='Slot identifier'),
    'role': fields.String(required=True, description='marker|area|actuator|sensor|...'),
    'device_id': fields.String(required=True, description='Device unique_id'),
    'device_kind': fields.String(description='Resolved server-side when omitted'),
    'channel_id': fields.String(description="Defaults to '0'"),
    'measurement_id': fields.String(description='DeviceMeasurements.unique_id'),
})


def _binding_dict(row):
    return {
        'unique_id': row.unique_id,
        'spatial_kind': row.spatial_kind,
        'spatial_id': row.spatial_id,
        'role': row.role,
        'device_kind': row.device_kind,
        'device_id': row.device_id,
        'channel_id': row.channel_id,
        'measurement_id': row.measurement_id,
        'valid_from': row.valid_from.isoformat() if row.valid_from else None,
        'valid_to': row.valid_to.isoformat() if row.valid_to else None,
        'ended_reason': row.ended_reason,
    }


# @manual geo/api-reference#details-binding-fields
def _shape_by_node_id(node_id, map_uuid=None):
    """feature.properties.node_id 로 도형을 찾는다(저장 전 클라이언트 식별자).

    JSON 안을 봐야 해서 스캔이 필요하다. 지도 하나 범위이고 사람이 버튼을
    누른 순간에만 도는 경로라 비용이 문제되지 않는다 — `save_overlays` 도
    같은 이유로 같은 방식을 쓴다.
    """
    if not node_id:
        return None
    q = GeoShape.query
    if map_uuid:
        q = q.filter_by(geo_id=map_uuid)
    for row in q.all():
        feat = row.feature
        if isinstance(feat, str):
            try:
                feat = json.loads(feat)
            except Exception:
                continue
        if isinstance(feat, dict) and \
                (feat.get('properties') or {}).get('node_id') == node_id:
            return row
    return None


# @manual geo/api-reference#details-binding-fields
def _binding_args(data):
    """페이로드 → 게이트웨이 인자. device_kind 는 서버가 판별한다.

    클라이언트가 보낸 종류 문자열을 믿지 않는 이유: 지도 UI 의 타입 어휘는
    바인딩 어휘와 다르다('function' 이 UI 에서는 CustomController 다).
    그대로 저장하면 바인딩의 종류가 실제 테이블과 어긋난 채 조용히 남는다.
    """
    from aot.space import device_binding

    # device_id 는 `<uuid>::<channel>` 접미사를 받는다. 명시적 channel_id 가
    # 없으면 그 접미사가 채널이다 — 떼기만 하고 버리면 채널 3 배정이 채널 0
    # 으로 저장된다(/device/location 과 같은 규칙).
    raw_device_id = data.get('device_id') or ''
    parts = str(raw_device_id).split('::')
    device_id = parts[0]
    suffix_channel = parts[1] if len(parts) > 1 and parts[1] != '' else None
    kind = device_binding.resolve_device_kind(device_id)
    if kind is None:
        raise ValueError('존재하지 않는 장치: %s' % (data.get('device_id'),))
    declared = data.get('device_kind')
    if declared and declared != kind:
        current_app.logger.info(
            '[GeoAPI] device_kind 정정: 요청=%s 실제=%s (device=%s)',
            declared, kind, device_id)

    spatial_kind = data.get('spatial_kind')
    spatial_id = data.get('spatial_id')
    role = data.get('role')
    if spatial_kind == 'shape':
        # role 은 도형 자신의 type 컬럼에서만 나온다. 프런트의 aot_type 은
        # get_overlays 가 'device'→'aot_device' 로 정규화해 내보내므로,
        # 그 값을 role 로 쓰면 구역 배정이 마커 배정으로 저장된다.
        shape = GeoShape.query.filter_by(unique_id=spatial_id).first()
        if shape is None:
            # 클라이언트가 아직 저장 전이라 GeoShape.unique_id 를 모르면
            # 자기가 만든 node_id 를 보낸다. 그 값은 feature JSON 안에만
            # 있으므로 지도 범위에서 찾아 준다 — 프런트가 어느 식별자가
            # 정본인지 알아야 하는 상태로 두면, 저장 전후에 따라 배정이
            # 되기도 하고 안 되기도 하는 화면이 된다.
            shape = _shape_by_node_id(spatial_id, data.get('map_uuid'))
            if shape is None:
                raise ValueError('존재하지 않는 도형: %s' % (spatial_id,))
        spatial_id = shape.unique_id
        role = device_binding.role_for_shape_type(shape.type)
        if role is None:
            raise ValueError(
                "'%s' 종류의 도형에는 장치를 맬 수 없다 — 구역 폴리곤"
                "(type='device')이나 위치 마커만 가능하다." % shape.type)

    return {
        'spatial_kind': spatial_kind,
        'spatial_id': spatial_id,
        'role': role,
        'device_kind': kind,
        'device_id': device_id,
        'channel_id': data.get('channel_id') or suffix_channel or '0',
        'measurement_id': data.get('measurement_id') or None,
    }


@ns_geo.route('/binding')
class GeoBindingResource(Resource):
    """공간 슬롯 ↔ 장치 배정. 마커 좌표는 여기가 아니라 /device/location 이다.

    구역 배정을 /device/location 에 얹지 않는 이유: 마커는 좌표(어디에
    있는가)이고 구역은 소속(무엇을 담당하는가)이라 뜻이 다르다. 한
    엔드포인트에 섞으면 좌표 없는 배정과 배정 없는 좌표를 구분할 수 없다.
    """

    # @manual geo/api-reference#device-binding
    @ns_geo.doc(responses=default_responses)
    @login_required
    def get(self):
        """Current bindings (and history) for one spatial slot"""
        from aot.space import device_binding
        spatial_kind = request.args.get('spatial_kind')
        spatial_id = request.args.get('spatial_id')
        role = request.args.get('role') or None
        if not spatial_kind or not spatial_id:
            return {'ok': False,
                    'message': 'spatial_kind, spatial_id required'}, 400
        try:
            rows = device_binding.current(spatial_kind, spatial_id, role=role)
            past = [b for b in device_binding.history(
                spatial_kind, spatial_id, role=role) if b.valid_to is not None]
            return {'ok': True,
                    'bindings': [_binding_dict(b) for b in rows],
                    'history': [_binding_dict(b) for b in past]}
        except Exception as e:
            current_app.logger.error('[GeoAPI] binding get: %s', e)
            return {'ok': False, 'message': str(e)}, 500

    # @manual geo/api-reference#device-binding
    @ns_geo.doc(responses=default_responses)
    @ns_geo.expect(geo_binding_model)
    @login_required
    def post(self):
        """Bind a device to an unoccupied slot"""
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        from aot.space import device_binding
        data = request.get_json() or {}
        try:
            row = device_binding.bind(commit=True, **_binding_args(data))
            return {'ok': True, 'binding': _binding_dict(row)}
        except device_binding.BindingConflict as e:
            db.session.rollback()
            # 409 — UI 는 이 코드를 보고 교체(rebind) 플로우로 안내한다.
            return {'ok': False, 'conflict': True, 'message': str(e)}, 409
        except (device_binding.BindingError, ValueError) as e:
            db.session.rollback()
            return {'ok': False, 'message': str(e)}, 400
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('[GeoAPI] binding post: %s', e)
            return {'ok': False, 'message': str(e)}, 500

    # @manual geo/api-reference#device-binding
    @ns_geo.doc(responses=default_responses)
    @ns_geo.expect(geo_binding_model)
    @login_required
    def put(self):
        """Replace the device on a slot (ends the old binding, keeps history)"""
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        from aot.space import device_binding
        data = request.get_json() or {}
        try:
            row = device_binding.rebind(commit=True, **_binding_args(data))
            return {'ok': True, 'binding': _binding_dict(row)}
        except (device_binding.BindingError, ValueError) as e:
            db.session.rollback()
            return {'ok': False, 'message': str(e)}, 400
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('[GeoAPI] binding put: %s', e)
            return {'ok': False, 'message': str(e)}, 500


@ns_geo.route('/binding/unbound')
class GeoBindingUnbound(Resource):
    # @manual geo/api-reference#device-binding
    @ns_geo.doc(responses=default_responses)
    @login_required
    def get(self):
        """Slots with no device bound — what a deletion or a swap left behind.

        `kinds` 로 반드시 좁혀서 부를 것(예: `kinds=shape`). 구역 폴리곤은
        지도가, 시설 설비는 시설 편집기가 관할이라 한 화면에 섞으면 안 된다.
        """
        from aot.space import device_binding
        raw = (request.args.get('kinds') or '').strip()
        kinds = tuple(k for k in raw.split(',') if k) or None
        try:
            slots = device_binding.unbound_slots(
                facility_uuid=request.args.get('facility_uuid') or None,
                map_uuid=request.args.get('map_uuid') or None,
                kinds=kinds)
            return {'ok': True, 'slots': slots}
        except Exception as e:
            current_app.logger.error('[GeoAPI] unbound slots: %s', e)
            return {'ok': False, 'message': str(e)}, 500


@ns_geo.route('/binding/<string:binding_uid>')
class GeoBindingDetail(Resource):
    # @manual geo/api-reference#device-binding
    @ns_geo.doc(responses=default_responses)
    @login_required
    def delete(self, binding_uid):
        """End a binding. The row is kept — history is the point (B3)."""
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        from aot.space import device_binding
        data = request.get_json(silent=True) or {}
        reason = data.get('reason') or request.args.get('reason') or 'unbound'
        try:
            row = device_binding.unbind(binding_uid, reason, commit=True)
            return {'ok': True, 'binding': _binding_dict(row)}
        except device_binding.BindingNotFound as e:
            db.session.rollback()
            return {'ok': False, 'message': str(e)}, 404
        except device_binding.BindingError as e:
            db.session.rollback()
            return {'ok': False, 'message': str(e)}, 400
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('[GeoAPI] binding delete: %s', e)
            return {'ok': False, 'message': str(e)}, 500


@ns_geo.route('/device/location')
class GeoDeviceLocation(Resource):
    # @manual geo/design-tool#device-a, geo/api-reference#device-location-lists-detail
    @ns_geo.doc(responses=default_responses)
    @login_required
    def post(self):
        """Places (or moves/unplaces) a device marker via the placement gateway"""
        # 지도 편집 쓰기 — 형제 쓰기(/overlays·/binding·/designs)와 MCP
        # set_device_location 과 같은 edit_settings.
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        try:
            data = request.get_json()
            unique_id_raw = data.get('unique_id')
            dev_type = data.get('type')
            lat = data.get('lat')
            lng = data.get('lng')
            map_uuid = data.get('map_uuid') 
            
            if not unique_id_raw or not dev_type:
                return {'ok': False, 'message': 'Missing unique_id or type'}, 400

            unique_id = unique_id_raw
            channel_id = data.get('channel_id') or '0'
            
            if isinstance(unique_id, str) and '::' in unique_id:
                parts = unique_id.split('::')
                unique_id = parts[0]
                if not data.get('channel_id') and len(parts) > 1:
                    channel_id = parts[1]

            # 복합장치(Device)와 Custom Function 은 같은 테이블이지만 지도
            # 에서는 따로 배치한다(collect_devices 가 is_device 로 가른다).
            # 여기 'device' 가 없으면 장치 마커 저장이 400 으로 튕긴다.
            # 지도 어휘: 'function'=CustomController, 'generic_function'=Function.
            from aot.space.device_kind import models_for
            model_map = models_for(
                ('input', 'output', 'pid', 'trigger', 'conditional',
                 'device', 'function', 'custom', 'generic_function'),
                vocabulary='geo')
            
            ModelClass = model_map.get(dev_type.lower())
            if not ModelClass:
                if dev_type.lower() == 'function':
                    ModelClass = CustomController
                else:
                    return {'ok': False, 'message': f'Unknown device type: {dev_type}'}, 400

            model_candidates = []
            if dev_type == 'function':
                model_candidates = [CustomController, PID, Trigger, Conditional, Function]
            elif ModelClass:
                model_candidates = [ModelClass]
                
            target_device = None
            for M in model_candidates:
                 target_device = M.query.filter_by(unique_id=unique_id).first()
                 if target_device: 
                     break
                 
            if not target_device:
                 return {'ok': False, 'message': 'Device not found'}, 404

            # 그룹 스코프 — 대상이 정해진 뒤, 좌표·마커를 건드리기 전에.
            # 장치는 그 탭으로, 마커를 만들 지도는 지도 자신으로 판정한다.
            # (abort 는 아래 except Exception 에 삼켜져 500 이 되므로 응답으로 돌려준다.)
            from aot.aot_flask.access import scope
            if not scope.can_operate_device(target_device.unique_id) or \
                    (map_uuid and not scope.can_operate('geo_map', map_uuid)):
                return {'ok': False, 'message': scope.deny_message()}, 403

            # [L2] 장치 행의 좌표 컬럼에는 쓰지 않는다 — 위치의 정본은 배치
            # (마커 + geo_binding)이고 읽는 쪽은 device_location.locate 다.
            if not map_uuid and lat not in [None, ''] and lng not in [None, '']:
                # 옵션 모달의 지도는 map_uuid 를 보내지 않는다 — 장치의 현재 지도, 없으면
                # 지도가 하나뿐일 때 그 지도. 여러 개인데 미배치면 배치하지 않는다.
                from aot.space.device_membership import map_for_device
                map_uuid = map_for_device(unique_id)
                if not map_uuid:
                    _maps = GeoMap.query.all()
                    if len(_maps) == 1:
                        map_uuid = _maps[0].unique_id
                    elif len(_maps) > 1:
                        return {'ok': False,
                                'message': _('Select a map to place this device on.')}, 400
            if map_uuid:
                # [P2] map_config_id 저장 폐지 — 아래에서 만드는 마커의
                # geo_id 가 곧 '이 장치가 속한 지도'다(device_membership).

                # [S3] map_overlay_id 는 더 이상 쓰지 않는다. 소속은 아래에서
                # 만드는 위치 마커의 좌표로부터 실시간 파생된다
                # (aot/space/device_membership.py — 유일한 정본).
                # 저장하지 않으면 복제·zone 재생성·도형 삭제가 오염시킬 수 없다.

                # [S5] 마커 쓰기는 단일 게이트웨이를 통해서만 — 채널 정규화·
                # aot_type 미저장·중복 방지 계약이 그 안에 있다.
                from aot.aot_flask.geo.device_placement import place_device
                place_device(
                    unique_id, map_uuid, lat, lng,
                    channel_id=channel_id, device_type=dev_type,
                    name=getattr(target_device, 'name', str(unique_id)))

            db.session.commit()

            # Notify daemon to reload settings when location changes
            # so _facility_tz / device_tz is updated in memory immediately.
            if lat is not None and lng is not None:
                try:
                    from aot.aot_client import DaemonControl
                    from aot.databases.models.pid import PID as _PID
                    from aot.databases.models.controller import CustomController as _CC
                    ctrl = DaemonControl()
                    if isinstance(target_device, Trigger):
                        ctrl.refresh_daemon_trigger_settings(target_device.unique_id)
                        current_app.logger.info(
                            f"[GeoAPI] Trigger {target_device.unique_id} daemon settings refreshed")
                    elif isinstance(target_device, _PID):
                        ctrl.pid_mod(target_device.unique_id)
                        current_app.logger.info(
                            f"[GeoAPI] PID {target_device.unique_id} daemon settings refreshed (new tz from coords)")
                    elif isinstance(target_device, _CC):
                        ctrl.module_function('Function_Custom', target_device.unique_id,
                                             'cmd_reload', {}, thread=False)
                        current_app.logger.info(
                            f"[GeoAPI] CustomController {target_device.unique_id} reloaded (new tz from coords)")
                    elif isinstance(target_device, Input):
                        ctrl.controller_restart(target_device.unique_id)
                        current_app.logger.info(
                            f"[GeoAPI] Input {target_device.unique_id} controller restarted (new location)")
                    elif isinstance(target_device, Output):
                        ctrl.output_setup('Modify', target_device.unique_id)
                        current_app.logger.info(
                            f"[GeoAPI] Output {target_device.unique_id} reloaded (new location)")
                except Exception as exc:
                    current_app.logger.debug(f"[GeoAPI] Daemon refresh skipped: {exc}")

            # [S3] overlay_id 는 파생값으로 응답한다 (저장 컬럼은 사망 상태).
            derived_overlay_id = None
            if map_uuid:
                try:
                    from aot.space.device_membership import zone_for_device
                    _z = zone_for_device(unique_id, map_uuid)
                    derived_overlay_id = _z.id if _z is not None else None
                except Exception:
                    pass
            return {
                'ok': True,
                'message': 'Location saved',
                'overlay_id': derived_overlay_id
            }

        except Exception as e:
            current_app.logger.error(f" [GeoAPI] Location Exception: {e}")
            return {'ok': False, 'message': str(e)}, 500
