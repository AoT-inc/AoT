# -*- coding: utf-8 -*-
from datetime import datetime

from flask import current_app
from sqlalchemy import inspect, text

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape


def _generate_map_name(base_name):
    base = base_name or "Device"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return f"{base} Map ({timestamp})"




def ensure_map_config(map_config_uuid, device_name=None, latitude=None, longitude=None):
    """
    Return existing GeoMap if map_config_uuid is valid, otherwise create a new map.
    """
    if map_config_uuid:
        existing = GeoMap.query.filter_by(unique_id=map_config_uuid).first()
        if existing:
            return existing
    return create_map_config(device_name, latitude, longitude)


def create_map_config(device_name=None, latitude=None, longitude=None):
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
    # Duplicate overlays
    source_overlays = GeoShape.query.filter_by(geo_id=source_map_uuid).all()
    for overlay in source_overlays:
        duplicated_feature = overlay.feature.copy() if overlay.feature else {}
        props = duplicated_feature.get('properties') or {}
        props['map_id'] = cloned.unique_id
        
        # Sync hierarchy info
        # level_id is now a property based on type, not stored.
        
        duplicated_feature['properties'] = props
        db.session.add(GeoShape(geo_id=cloned.unique_id,
                                  device_id=overlay.device_id,
                                  # level_id removed as it is now a property
                                  channel_id=overlay.channel_id,
                                  feature=duplicated_feature))
    current_app.logger.debug("Cloned map %s -> %s", source_map_uuid, cloned.unique_id)
    return cloned


def delete_map_config(map_config_uuid):
    if not map_config_uuid:
        return
    GeoShape.query.filter_by(geo_id=map_config_uuid).delete()
    GeoMap.query.filter_by(unique_id=map_config_uuid).delete()
    current_app.logger.debug("Deleted map %s and associated overlays", map_config_uuid)
