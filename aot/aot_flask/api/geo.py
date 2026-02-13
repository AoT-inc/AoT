# coding=utf-8
import json
import traceback
from datetime import datetime

from flask import request, current_app
from flask_restx import Resource, abort, fields
from flask_login import login_required
from sqlalchemy import or_

from aot.databases.models import GeoMap, GeoShape, GeoSetting, Input, Output, GeoLayer, PID, Trigger, Conditional, CustomController, Function
from aot.aot_flask.api import api, default_responses
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_general, utils_geo
from aot.utils.inputs import parse_input_information

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
                
            if not layer_id:
                settings = GeoSetting.query.first()
                if settings and settings.providers:
                    try:
                        provs = json.loads(settings.providers)
                        layer_id = provs.get('search_provider')
                    except:
                        pass
                
                if not layer_id:
                    layer_id = 'gis_osm' # Default Fallback (Nominatim)
                
            layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
            file_path = None
            custom_opts = {}
            
            if layer:
                dict_inputs = parse_input_information()
                layer_def = dict_inputs.get(layer.type, {})
                file_path = layer_def.get('file_path')
                try:
                    custom_opts = json.loads(layer.options) if layer.options else {}
                except:
                    custom_opts = {}
            else:
                dict_inputs = parse_input_information()
                if layer_id in dict_inputs:
                    file_path = dict_inputs[layer_id].get('file_path')
                    
            if not file_path:
                return {'ok': False, 'message': 'Provider not found'}, 404
                 
            from aot.utils.modules import load_module_from_file
            from aot.aot_flask.utils.utils_geo import MockInputDev
            
            mod, status = load_module_from_file(file_path, 'inputs')
            if not mod or not hasattr(mod, 'InputModule'):
                return {'ok': False, 'message': 'Invalid Provider Module'}, 500
                 
            global_settings = GeoSetting.query.first()
            global_api_keys = {}
            if global_settings and global_settings.keys:
                try:
                    global_api_keys = json.loads(global_settings.keys)
                except:
                    global_api_keys = {}

            dict_inputs = parse_input_information()
            layer_def = dict_inputs.get(layer.type if layer else layer_id, {})
            
            if 'key_field' in layer_def:
                kf = layer_def['key_field']
                gkf = layer_def.get('global_key_field', kf)
                if not custom_opts.get(kf):
                    global_val = global_api_keys.get(gkf)
                    if global_val:
                        custom_opts[kf] = global_val

            mock_dev = MockInputDev(type('obj', (object,), {'unique_id': layer_id, 'name': 'SearchProxy'})())
            inst = mod.InputModule(mock_dev)
            inst.custom_options = custom_opts
            
            def mock_get_option(opt, default=None):
                return inst.custom_options.get(opt, default)
            inst.get_custom_option = mock_get_option

            if not hasattr(inst, 'search'):
                return {'ok': False, 'message': 'Search not supported by this provider'}, 400
                 
            result = inst.search(query, search_type=search_type)
            
            if isinstance(result, dict) and 'error' in result:
                return {'ok': False, 'message': result['error']}, 200
                 
            return {'ok': True, 'results': result}

        except Exception as e:
            current_app.logger.error(f" [GeoAPI] Search Exception: {e}")
            return {'ok': False, 'message': str(e)}, 500

@ns_geo.route('/device/location')
class GeoDeviceLocation(Resource):
    @ns_geo.doc(responses=default_responses)
    @login_required
    def post(self):
        """Saves device location directly to SQL columns (latitude, longitude)"""
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

            if str(channel_id) in ['0', 'None', '']:
                if hasattr(target_device, 'latitude'):
                    target_device.latitude = float(lat) if lat not in [None, ''] else None
                if hasattr(target_device, 'longitude'):
                    target_device.longitude = float(lng) if lng not in [None, ''] else None
                
            if hasattr(target_device, 'location_updated_utc'):
                target_device.location_updated_utc = datetime.utcnow()
                
            if map_uuid:
                if hasattr(target_device, 'map_config_id'):
                    target_device.map_config_id = map_uuid
                
                from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
                containing_shape = GeoOverlayManager.find_containing_shape(lat, lng, map_uuid)
                
                if hasattr(target_device, 'map_overlay_id'):
                    if containing_shape:
                        target_device.map_overlay_id = containing_shape.id
                    else:
                        target_device.map_overlay_id = None

                from aot.databases.models import GeoShape
                geo_shape = GeoShape.query.filter_by(
                    geo_id=map_uuid, 
                    device_id=unique_id, 
                    channel_id=str(channel_id)
                ).first()

                if lat is not None and lng is not None:
                    if not geo_shape:
                        geo_shape = GeoShape(
                            geo_id=map_uuid,
                            device_id=unique_id,
                            channel_id=str(channel_id),
                            type='aot_device'
                        )
                        db.session.add(geo_shape)
                    
                    geo_shape.feature = {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [float(lng), float(lat)]
                        },
                        "properties": {
                            "aot_type": "aot_device",
                            "unique_id": f"{unique_id}::{channel_id}" if str(channel_id) != '0' and channel_id is not None else unique_id,
                            "device_id": unique_id,
                            "channel_id": channel_id,
                            "device_type": dev_type,
                            "name": target_device.name
                        }
                    }
                    geo_shape.updated_at = datetime.utcnow()
                elif geo_shape:
                    db.session.delete(geo_shape)

            db.session.commit()
            return {
                'ok': True, 
                'message': 'Location saved',
                'overlay_id': getattr(target_device, 'map_overlay_id', None)
            }

        except Exception as e:
            current_app.logger.error(f" [GeoAPI] Location Exception: {e}")
            return {'ok': False, 'message': str(e)}, 500
