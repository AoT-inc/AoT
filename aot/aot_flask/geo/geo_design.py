# coding=utf-8
import json
from datetime import datetime
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from aot.databases.models import GeoMap, GeoSetting
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_geo
from aot.aot_flask.geo.widget.maps import invalidate_geomap_cache

class GeoDesignManager:
    """
    Manages Geo Design Maps (Metadata & State).
    """

    @staticmethod
    def get_design_map(map_uuid):
        """Get Map State by UUID"""
        geo_map = GeoMap.query.filter_by(unique_id=map_uuid).first()
        if not geo_map:
            return None, "Map not found"
        
        return {
            'ok': True,
            'uuid': geo_map.unique_id,
            'name': geo_map.name,
            'state': geo_map.state_dict()
        }, None

    @staticmethod
    def init_design_map(current_user_id):
        """
        Auto-load or Create the latest Design Map.
        """
        # 1. Find existing design maps [Optimization] Filter by category='design' in SQL
        target_map = GeoMap.query.filter_by(category='design').order_by(GeoMap.updated_at.desc()).first()
                
        # 2. If not found, create new
        if not target_map:
            try:
                # Get Global Defaults
                global_conf = utils_geo.get_geo_config()
                defaults = global_conf.get('settings', {})
                
                def_lat = defaults.get('default_lat', 37.5665)
                def_lng = defaults.get('default_lng', 126.9780)
                def_zoom = defaults.get('zoom', 13)
                
                target_map = GeoMap()
                target_map.name = "Design Map 1"
                target_map.category = "design" # [New] Use column
                target_map.created_by = current_user_id
                target_map.state_json = json.dumps({
                    "category": "design", 
                    "zoom": def_zoom, 
                    "center": [def_lat, def_lng]
                })
                target_map.save()
            except Exception as e:
                current_app.logger.error(f"Failed to init design map: {e}")
                return None, str(e)
            
        return {
            'ok': True,
            'uuid': target_map.unique_id,
            'name': target_map.name,
            'state': target_map.state_dict()
        }, None

    @staticmethod
    def save_design_map(data, current_user_id):
        """Create or Update GeoMap Metadata & State"""
        map_uuid = data.get('map_uuid')
        name = data.get('name')
        state_update = data.get('state', {})
        
        try:
            if map_uuid:
                geo_map = GeoMap.query.filter_by(unique_id=map_uuid).first()
                if not geo_map:
                    # [Fix] If UUID provided but not found (e.g. DB reset), create it instead of erroring
                    # This allow Auto-Initialization from out-of-sync client state.
                    geo_map = GeoMap(unique_id=map_uuid)
                    geo_map.created_by = current_user_id
                    geo_map.category = 'design'
                    db.session.add(geo_map)
                    current_app.logger.info(f"Auto-creating Map Design for unknown UUID: {map_uuid}")
            else:
                geo_map = GeoMap()
                geo_map.created_by = current_user_id
                geo_map.category = 'design' # [New] Set column
                state_update['category'] = 'design' 
            
            if name:
                geo_map.name = name
                
            # Update State JSON
            current_state = geo_map.state_dict()
            current_state.update(state_update)
            
            # Ensure category persists in both column and JSON
            geo_map.category = 'design'
            current_state['category'] = 'design'
                
            geo_map.state_json = json.dumps(current_state)
            geo_map.updated_at = datetime.utcnow()
            geo_map.save()
            invalidate_geomap_cache(geo_map.unique_id)

            return {'ok': True, 'uuid': geo_map.unique_id, 'name': geo_map.name}, None

        except Exception as e:
            current_app.logger.error(f"Geo Design Save Error: {e}")
            return None, str(e)

    @staticmethod
    def delete_design_map(map_uuid):
        """Delete GeoMap"""
        try:
            geo_map = GeoMap.query.filter_by(unique_id=map_uuid).first()
            if not geo_map:
                return None, "Map not found"
            
            # Assuming cascade delete or manual overlay deletion needed?
            # For now, relying on DB cascade or simple map deletion.
            db.session.delete(geo_map)
            db.session.commit()
            invalidate_geomap_cache(map_uuid)

            return {'ok': True}, None
        except Exception as e:
            current_app.logger.error(f"Geo Design Delete Error: {e}")
            db.session.rollback()
            return None, str(e)
