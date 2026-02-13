# coding=utf-8
import json
import traceback
from datetime import datetime

from flask import request, current_app
from flask_restx import Resource, abort, fields
from flask_login import login_required
from sqlalchemy import or_

from aot.databases.models import GeoMap, GeoShape, GeoSetting, Input, Output
from aot.aot_flask.api import api, default_responses
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_general

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
    @ns_geo.doc(responses=default_responses)
    @login_required
    def get(self):
        """Get List of all Design Maps"""
        try:
            all_maps = GeoMap.query.filter_by(category='design').order_by(GeoMap.updated_at.desc()).all()
            result = []
            for m in all_maps:
                state = m.state_dict()
                center = state.get('center', [37.5665, 126.9780])
                result.append({
                    'unique_id': m.unique_id,
                    'name': m.name,
                    'latitude': center[0] if isinstance(center, list) and len(center) >= 2 else 37.5665,
                    'longitude': center[1] if isinstance(center, list) and len(center) >= 2 else 126.9780,
                    'zoom': state.get('zoom', 13)
                })
            return result
        except Exception as e:
            abort(500, message=str(e))

    @ns_geo.doc(responses=default_responses)
    @ns_geo.expect(geo_design_model)
    @login_required
    def post(self):
        """Create or Update GeoMap Metadata & State"""
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        from aot.aot_flask.geo import GeoDesignManager
        data = request.get_json()
        from flask_login import current_user
        result, error = GeoDesignManager.save_design_map(data, current_user.id)
        if error:
            abort(500, message=error)
        return result

@ns_geo.route('/designs/<string:map_uuid>')
class GeoDesignDetail(Resource):
    @ns_geo.doc(responses=default_responses)
    @login_required
    def get(self, map_uuid):
        """Get GeoMap Metadata & State by UUID"""
        from aot.aot_flask.geo import GeoDesignManager
        result, error = GeoDesignManager.get_design_map(map_uuid)
        if error:
            abort(404 if "not found" in error else 500, message=error)
        return result

    @ns_geo.doc(responses=default_responses)
    @login_required
    def delete(self, map_uuid):
        """Delete GeoMap"""
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        from aot.aot_flask.geo import GeoDesignManager
        result, error = GeoDesignManager.delete_design_map(map_uuid)
        if error:
            abort(500, message=error)
        return result

@ns_geo.route('/overlays')
class GeoOverlays(Resource):
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
        return result

    @ns_geo.doc(responses=default_responses)
    @ns_geo.expect(geo_overlay_model)
    @login_required
    def post(self):
        """Bulk Save Overlays"""
        if not utils_general.user_has_permission('edit_settings'):
            abort(403)
        from aot.aot_flask.geo import GeoOverlayManager
        data = request.get_json()
        result, error = GeoOverlayManager.save_overlays(data)
        if error:
            abort(500, message=error)
        return result

@ns_geo.route('/search')
class GeoSearch(Resource):
    @ns_geo.doc(responses=default_responses)
    @login_required
    def post(self):
        """Execute Search via GIS Provider (Address, Coordinate, etc.)"""
        # Endpoint documented. Implementation logic resides in routes_geo.py.
        return {"message": "Endpoint documented for reference"}, 200

@ns_geo.route('/device/location')
class GeoDeviceLocation(Resource):
    @ns_geo.doc(responses=default_responses)
    @login_required
    def post(self):
        """Saves device location directly to SQL columns (latitude, longitude)"""
        # Endpoint documented. Implementation logic resides in routes_geo.py.
        return {"message": "Endpoint documented for reference"}, 200
