# coding=utf-8
import json
from datetime import datetime
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from aot.databases.models import GeoMap, GeoSetting, GeoShape, GeoFacility, GeoFacilitySetpoint
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
        # 1. 기존 지도 중 가장 최근 것
        # [P3] 모든 지도가 동등하다 — category 분기 폐기.
        target_map = GeoMap.query.order_by(GeoMap.updated_at.desc()).first()
                
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
        """Delete GeoMap and everything under it (facilities, setpoints, shapes).

        Deletes children explicitly, in dependency order, via bulk queries
        instead of relying on GeoMap.shapes' ORM cascade("all, delete-orphan").
        That cascade only reaches GeoShape — it does not know about GeoFacility
        (linked to GeoShape by shape_uuid, no cascade declared), so deleting a
        GeoShape that has a linked GeoFacility makes SQLAlchemy try to null out
        GeoFacility.shape_uuid before the delete, which fails (shape_uuid is
        NOT NULL). That failure used to surface *after* the map/shape deletes
        had already been sent to the DB, leaving a half-deleted map (facility
        rows orphaned, map+shapes gone) instead of rolling back cleanly.
        """
        # 이 지도를 아직 쓰는 위젯이 있으면 지우지 않는다.
        #
        # 도형·시설은 트리거(I3~I5)가 연쇄 정리하고, 장치의 map_config_id 도
        # 트리거가 NULL 로 되돌린다. 그런데 **위젯은 지도 uuid 를
        # custom_options JSON 안에 둔다** — 트리거도 FK 도 거기까지 닿지
        # 못한다. 그래서 지도를 지우면 그 지도를 보던 위젯이 오류 없이 빈
        # 지도를 보여주고, 사용자는 원인을 알 수 없었다.
        # (docs/design/geo-data-integrity.md 의 '잔여 위험' 항목)
        try:
            from aot.services.device_references import (
                deletion_blocked_message, find_referrers)
            referrers = find_referrers([map_uuid]).get(map_uuid)
            if referrers:
                geo_map = db.session.query(GeoMap).filter_by(
                    unique_id=map_uuid).first()
                # 서버 오류가 아니라 **거절**이다. 호출자가 상태 코드를
                # 가릴 수 있도록 result 에 표식을 남긴다(error 만 보는
                # 기존 호출자도 그대로 동작한다).
                return {'blocked': True}, deletion_blocked_message(
                    getattr(geo_map, 'name', None) or map_uuid, referrers)
        except Exception as e:
            # 검사가 깨져도 삭제 자체를 막지는 않는다 — 예전 동작으로 돌아갈 뿐이다.
            current_app.logger.error(f"Geo Design Delete 참조 검사 실패: {e}")

        try:
            facility_uuids = [
                row[0] for row in db.session.query(GeoFacility.unique_id)
                .filter_by(geo_id=map_uuid).all()
            ]
            if facility_uuids:
                db.session.query(GeoFacilitySetpoint).filter(
                    GeoFacilitySetpoint.facility_uuid.in_(facility_uuids)
                ).delete(synchronize_session=False)
                db.session.query(GeoFacility).filter_by(geo_id=map_uuid).delete(synchronize_session=False)

            db.session.query(GeoShape).filter_by(geo_id=map_uuid).delete(synchronize_session=False)

            deleted = db.session.query(GeoMap).filter_by(unique_id=map_uuid).delete(synchronize_session=False)
            if not deleted:
                db.session.rollback()
                return None, "Map not found"

            db.session.commit()
            # 기하가 바뀌면 포함 관계 캐시는 낡는다(지우기만 한다).
            try:
                from aot.aot_flask.geo import containment_cache
                containment_cache.invalidate()
            except Exception:
                pass
            invalidate_geomap_cache(map_uuid)

            return {'ok': True}, None
        except Exception as e:
            current_app.logger.error(f"Geo Design Delete Error: {e}")
            db.session.rollback()
            return None, str(e)
