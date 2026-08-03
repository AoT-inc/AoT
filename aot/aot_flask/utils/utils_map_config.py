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
        # `type` must be carried over: it is what get_overlays() filters on
        # (site/zone/facility/aot_device/...). Omitting it fell back to the
        # column default 'feature', so every shape in a cloned map became
        # invisible to the map widget and the design editor alike.
        db.session.add(GeoShape(geo_id=cloned.unique_id,
                                  device_id=overlay.device_id,
                                  type=overlay.type,
                                  # level_id removed as it is now a property
                                  channel_id=overlay.channel_id,
                                  layer_group=overlay.layer_group,
                                  sort_order=overlay.sort_order,
                                  meta_json=overlay.meta_json,
                                  feature=duplicated_feature))
    current_app.logger.debug("Cloned map %s -> %s", source_map_uuid, cloned.unique_id)
    return cloned


def _map_still_referenced(map_config_uuid):
    """Return the (model, name) of any device still pointing at this map.

    Every controller type carries its own `map_config_id`, so a map is only
    disposable once no device references it any more.
    """
    from aot.databases.models import (
        Input, Output, PID, Trigger, Conditional, CustomController)

    for model in (Input, Output, PID, Trigger, Conditional, CustomController):
        if not hasattr(model, 'map_config_id'):
            continue
        row = model.query.filter_by(map_config_id=map_config_uuid).first()
        if row:
            return model.__name__, getattr(row, 'name', None)
    return None


def delete_map_config(map_config_uuid):
    """Delete a device-owned map and its overlays.

    Refuses to touch shared maps. A device's `map_config_id` does NOT imply
    ownership: the device settings page offers every non-device-owned map
    (i.e. the user's design maps) as a target so a device can be placed on
    the shared site map, and picking one stores that map's uuid here. Deleting
    the device then used to wipe the whole design map -- every shape plus the
    GeoMap row itself -- because this function trusted the uuid blindly.
    That is exactly how the '임실군' design map (62 shapes) was destroyed on
    aot-004 (2026-08-03) by deleting a single duplicate output, and it is a
    different code path from the save_overlays empty-delete guard added in
    e064f28, which is why that fix did not cover this.

    Two independent conditions must hold before anything is deleted:
      1. the map is device-owned (never a design/shared map), and
      2. no other device still references it.
    """
    if not map_config_uuid:
        return

    map_cfg = GeoMap.query.filter_by(unique_id=map_config_uuid).first()
    if not map_cfg:
        return

    if not map_cfg.is_device_owned or map_cfg.category != 'device':
        current_app.logger.info(
            "Refusing to delete shared map %s (%s, category=%s, "
            "is_device_owned=%s) -- it is not device-owned.",
            map_config_uuid, map_cfg.name, map_cfg.category,
            map_cfg.is_device_owned)
        return

    referenced = _map_still_referenced(map_config_uuid)
    if referenced:
        current_app.logger.info(
            "Refusing to delete map %s (%s) -- still referenced by %s %r.",
            map_config_uuid, map_cfg.name, referenced[0], referenced[1])
        return

    GeoShape.query.filter_by(geo_id=map_config_uuid).delete()
    GeoMap.query.filter_by(unique_id=map_config_uuid).delete()
    current_app.logger.debug("Deleted map %s and associated overlays", map_config_uuid)
