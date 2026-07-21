# coding=utf-8
import logging
import json
import copy
import math
from datetime import datetime, timedelta, timezone
from aot.utils.time_utils import get_local_now, utc_now, to_local, serialize_ts
from sqlalchemy import or_, func

from aot.databases.models import GeoMap, GeoShape, Input, Camera, EnergyUsage, Notes, DeviceMeasurements, Conversion, IrrigationDesign, Actions, Misc, db
from aot.utils.tools import return_energy_usage
from aot.utils.system_pi import return_measurement_info
from aot.utils.influx import query_string
from aot.ai.services.ai_learning_service import AILearningService
from flask_login import current_user

logger = logging.getLogger(__name__)

# Phase 6 Optimization Caches
_SPATIAL_CACHE = None
_LAST_GEO_UPDATE = None

class AIContextService:
    """
    Service to aggregate multi-modal system data (Spatial, Energy, Visual, Semantic)
    into a unified context for AI observation.
    Now distinguishes between Input Power and Supplied Resources.
    """

    @staticmethod
    def simplify_geometry(geometry, tier='standard'):
        """
        v13.0: Semantic Geometry Abstraction.
        Reduces token bloat by rounding coordinates or abstracting to BBox.
        """
        if not geometry or 'type' not in geometry or 'coordinates' not in geometry:
            return geometry

        def round_coords(coords, precision):
            if isinstance(coords, (int, float)):
                return round(float(coords), precision)
            if not isinstance(coords, list): return coords
            return [round_coords(c, precision) for c in coords]

        # 1. Rounding based on tier
        precision = 6 if tier == 'heavy' else 5
        
        # 2. Hard Abstraction for Small Tier
        if tier == 'lightweight':
            # Calculate BBox and Centroid
            all_coords = []
            def extract_all(c):
                if not isinstance(c, list): return
                if len(c) >= 2 and isinstance(c[0], (int, float)):
                    all_coords.append(c)
                else:
                    for sub in c: extract_all(sub)
            
            try:
                extract_all(geometry['coordinates'])
                if not all_coords: return {"type": "Point", "coordinates": [0,0], "note": "empty"}
                
                lons = [c[0] for c in all_coords]
                lats = [c[1] for c in all_coords]
                bbox = [min(lons) if lons else 0, min(lats) if lats else 0, max(lons) if lons else 0, max(lats) if lats else 0]
                centroid = [sum(lons)/len(lons) if lons else 0, sum(lats)/len(lats) if lats else 0]
                
                return {
                    "type": "Abstract",
                    "bbox": [round(x, 5) for x in bbox],
                    "centroid": [round(x, 5) for x in centroid],
                    "original_type": geometry['type'],
                    "point_count": len(all_coords)
                }
            except Exception:
                return {"type": geometry['type'], "note": "abstraction_failed"}

        # Standard/Heavy: Just round the coordinates
        try:
            geometry['coordinates'] = round_coords(geometry['coordinates'], precision)
        except Exception:
            pass
        return geometry

    @staticmethod
    def summarize_readings(readings, tier='standard'):
        """
        v13.0: Sensor Data Aggregation.
        Instead of raw lists, provides statistical insights.
        """
        if not readings or not isinstance(readings, list):
            return readings

        if tier == 'lightweight' or len(readings) > 10:
            vals = []
            valid_readings = []
            for r in readings:
                v = None
                if isinstance(r, dict):
                    v = r.get('value') or r.get('_value')
                elif isinstance(r, (int, float)):
                    v = r
                
                if isinstance(v, (int, float)):
                    vals.append(v)
                    valid_readings.append(r)
            
            if not vals: 
                return readings[:3]
            
            avg_val = sum(vals) / len(vals)
            trend = "stable"
            if len(vals) > 1:
                trend = "rising" if vals[-1] > vals[0] else "falling"
                if abs(vals[-1] - vals[0]) < (max(vals) - min(vals)) * 0.05:
                    trend = "stable"
            
            status = "stable"
            if valid_readings and isinstance(valid_readings[-1], dict) and 'status' in valid_readings[-1]:
                status = valid_readings[-1]['status']

            return {
                "latest": valid_readings[-1],
                "stats": {
                    "avg": round(avg_val, 2),
                    "min": min(vals),
                    "max": max(vals),
                    "count": len(vals),
                    "trend": trend,
                    "status": status
                },
                "note": "summarized",
                "tier": tier
            }
        return readings

    @staticmethod
    def get_spatial_hierarchy(tier=None):
        """
        Builds a hierarchical tree of Site > Zone > Device/Feature from GeoShape records.
        Uses spatial inclusion (shapely) as a fallback if explicit parent_id is missing,
        and applies caching/BBox optimization for robust spatial awareness.
        v14.1: tier parameter for thread safety (replaces _current_tier class variable).
        """
        try:
            from shapely.geometry import shape, Point
            # import json (removed local import to prevent shadowing/unbound error)
            
            # --- Phase 6: Spatial Cache Check ---
            global _SPATIAL_CACHE, _LAST_GEO_UPDATE
            latest_geo = GeoShape.query.order_by(GeoShape.id.desc()).first()
            current_tag = latest_geo.id if latest_geo else 0
            
            if _SPATIAL_CACHE is not None and _LAST_GEO_UPDATE == current_tag:
                return copy.deepcopy(_SPATIAL_CACHE)  # E-1: Deep Copy
            # ------------------------------------

            # v14.0: Pre-fetch AI Semantic Notes for quick binding
            from aot.databases.models import Notes
            ai_notes = Notes.query.filter_by(category='ai_semantic', is_archived=False).all()
            semantic_map = {n.target_id: n.note for n in ai_notes if n.target_id}

            all_shapes = GeoShape.query.all()
            
            # 1. Pre-process Geometries (BBox & Caching)
            containers = [] # Used for fast spatial matching
            for s in all_shapes:
                if s.type in ['site', 'zone']:
                    feat = s.feature
                    if isinstance(feat, str):
                        try: feat = json.loads(feat)
                        except Exception: feat = {}

                    if feat and 'geometry' in feat:
                        try:
                            g = shape(feat['geometry'])
                            if g.is_valid and g.geom_type in ['Polygon', 'MultiPolygon']:
                                containers.append({
                                    'id': s.id,
                                    'geom': g,
                                    'bounds': g.bounds, # Fast BBox check (minx, miny, maxx, maxy)
                                    'is_zone': s.type == 'zone',
                                    'area': g.area
                                })
                        except Exception:
                            pass
            
            # 2. Determine Spatial Parent
            def find_parent_id(s):
                # Safe JSON parsing for feature
                feat = s.feature
                if isinstance(feat, str):
                    try: feat = json.loads(feat)
                    except Exception: feat = {}
                elif not isinstance(feat, dict):
                    feat = {}
                s._parsed_feat = feat # Cache it for build_tree
                
                # A. Explicit Fallback Priority
                if s.parent_id:
                    return s.parent_id
                    
                # B. Spatial Inclusion Check (Only for Point geometries like markers)
                if not feat or 'geometry' not in feat:
                    return None
                    
                try:
                    g = shape(feat['geometry'])
                    if g.geom_type != 'Point': # Usually we map Points to Polygons
                        return None
                        
                    # Find all containing polygons
                    p_x, p_y = g.x, g.y
                    matches = []
                    for c in containers:
                        b = c['bounds']
                        # Bounding Box 1차 사전 필터링 (최적화)
                        if p_x < b[0] or p_x > b[2] or p_y < b[1] or p_y > b[3]:
                            continue
                        
                        # 실제 다각형 포함 여부 확인
                        if c['geom'].contains(g):
                            matches.append(c)
                            
                    if matches:
                        # 중첩 우선순위 (Zone이 Site보다 우선, 면적이 작은 것이 우선)
                        matches.sort(key=lambda x: (not x['is_zone'], x['area']))
                        return matches[0]['id']
                except Exception:
                    pass
                
                return None

            # Pre-calculate spatial relationships
            parent_map = {s.id: find_parent_id(s) for s in all_shapes}
            
            # 3. Build Tree
            def build_tree(s, tier='standard'):
                meta = s.meta_json or {}
                if isinstance(meta, str):
                    try: meta = json.loads(meta)
                    except Exception: meta = {}
                
                feat = getattr(s, '_parsed_feat', {})
                props = feat.get('properties', {})
                
                # Semantic First: Priority Name Resolution
                display_name = (props.get('name') or props.get('label') or 
                                meta.get('name') or props.get('label_name') or 
                                (s.type.capitalize() + " " + str(s.id)))

                d_id = (s.device_id or 
                        meta.get('unique_id') or meta.get('node_id') or meta.get('device_id') or
                        props.get('unique_id') or props.get('node_id') or props.get('device_id'))
                
                clean_d_id = str(d_id).split('::')[0] if d_id else None

                # [TASK_29] AI Enablement Filter for Spatial Tree
                if clean_d_id:
                    # Check if device is AI enabled. If not, skip this node.
                    from aot.databases.models.input import Input
                    from aot.databases.models.output import Output
                    is_enabled = True
                    if clean_d_id.startswith('IN_'):
                        dev = Input.query.filter_by(unique_id=clean_d_id).first()
                        is_enabled = getattr(dev, 'is_ai_enabled', True)
                    elif clean_d_id.startswith('OUT_'):
                        dev = Output.query.filter_by(unique_id=clean_d_id).first()
                        is_enabled = getattr(dev, 'is_ai_enabled', True)
                    
                    if not is_enabled:
                        logger.debug(f"Skipping AI-disabled device {clean_d_id} in spatial tree")
                        return None
                
                # v14.0: Node Construction with Semantic Priority
                node = {
                    "name": display_name,
                    "type": s.type,
                    "semantic_note": semantic_map.get(s.geo_id, ""),
                    "id": s.id,
                    "unique_id": s.geo_id,
                    "device_id": clean_d_id,
                    "children": []
                }
                
                # Merge additional metadata if relevant
                if props:
                    # Filter out noisy props
                    relevant_props = {k: v for k, v in props.items() if k not in ['geometry', 'name', 'label']}
                    if relevant_props:
                        node["properties"] = relevant_props

                # v14.0: Equipment Aggregation Logic
                # Separate children into 'Spatial' (Site/Zone/Device) and 'Asset' (Equipment/Fixed Feature)
                raw_children = [child for child in all_shapes if parent_map.get(child.id) == s.id]
                
                equipment_counts = {}
                for child in raw_children:
                    # v14.1: Use pre-parsed feature to avoid AttributeError on string features
                    child_feat = getattr(child, '_parsed_feat', {})
                    child_props = child_feat.get('properties', {}) if isinstance(child_feat, dict) else {}

                    # Define what constitutes an 'Equipment' (No device_id usually means it's a passive asset)
                    is_equipment = (child.type == 'feature' and not child.device_id) or \
                                   child_props.get('is_equipment')

                    if is_equipment and tier in ['lightweight', 'standard']:
                        # Aggregate by layer_group or category
                        category = child.layer_group or child_props.get('category', 'general_asset')
                        equipment_counts[category] = equipment_counts.get(category, 0) + 1
                    else:
                        # Full recursive build for spatial nodes or heavy tier
                        child_node = build_tree(child, tier=tier)
                        if child_node:
                            node["children"].append(child_node)
                
                if equipment_counts:
                    node["equipment_summary"] = equipment_counts
                
                return node

            # Root items — v14.1: Prefer parameter, fallback to class var for backward compat
            tier = tier or getattr(AIContextService, '_current_tier', 'standard')
            roots = [s for s in all_shapes if parent_map.get(s.id) is None]
            hierarchy = [n for n in (build_tree(root, tier=tier) for root in roots) if n]
            
            # --- Phase 6: Update Cache ---
            _SPATIAL_CACHE = hierarchy
            _LAST_GEO_UPDATE = current_tag
            # -----------------------------
            
            return hierarchy
            
        except ImportError:
            logger.warning("shapely not installed! Spatial awareness degraded.")
            return []
        except Exception as e:
            logger.exception("Error building spatial hierarchy")
            return []

    # E-4: Spatial Cache Invalidation
    @staticmethod
    def invalidate_spatial_cache():
        """장치 등록/삭제 후 호출하여 공간 캐시를 즉시 무효화합니다."""
        global _SPATIAL_CACHE, _LAST_GEO_UPDATE
        _SPATIAL_CACHE = None
        _LAST_GEO_UPDATE = None
        logger.info("[SpatialCache] Cache invalidated")

    @staticmethod
    def get_note_digests(tier='standard', max_entities=40, recent_n=3, txt_len=140):
        """엔티티별 노트 다이제스트(초기 기록 + 최근 기록)를 컨텍스트 주입용으로 조립.

        모든 장치·토지/시설·구역/도형은 각자의 노트를 가진다(Notes.target_id ==
        엔티티.unique_id 로 바인딩). AI는 slim 툴 매니페스트로 이를 열거할 수 없어
        "어떤 엔티티에 어떤 노트가 있는지"를 아예 모른다. 그래서 여기서 엔티티별로
        - 초기 노트(first, 기준/기본 정보)와
        - 최근 노트 몇 건(recent, 진행 과정)을
        압축해 미리 주입한다. AI는 이걸로 "각 장치의 노트"를 컨텍스트만으로 답하고,
        전체/과거 본문이 필요하면 search_notes(target_name=...)로 드릴다운한다.

        ai_semantic 노트는 제외(이미 spatial_hierarchy 노드의 semantic_note로 노출됨).
        """
        try:
            from aot.databases.models import Notes, GeoShape, Input, Output, Function
            import json as _json

            rows = (Notes.query
                    .filter(Notes.is_archived == False)  # noqa: E712
                    .filter((Notes.category != 'ai_semantic') | (Notes.category.is_(None)))
                    .all())
            if not rows:
                return []

            by_target = {}
            for n in rows:
                if n.target_id:
                    by_target.setdefault(n.target_id, []).append(n)
            if not by_target:
                return []

            # 이름/타입 해석기 — 노트가 붙는 방식(엔티티.unique_id)과 동일한 키로 매핑.
            # 주의: GeoShape.geo_id 는 맵(GeoMap) FK(도형들이 공유)이고, 도형 자체
            # 식별자는 GeoShape.unique_id 다. 노트 target_id 는 unique_id 로 붙는다.
            name_map = {}  # unique_id -> (name, type)
            try:
                for s in GeoShape.query.all():
                    feat = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
                    props = (feat.get('properties') or {}) if isinstance(feat, dict) else {}
                    nm = str(props.get('name') or props.get('label') or props.get('title') or '').strip()
                    if s.unique_id:
                        name_map[s.unique_id] = (nm or (s.type or 'shape'), s.type or 'shape')
            except Exception:
                pass
            for model, _tt in ((Input, 'input'), (Output, 'output'), (Function, 'function')):
                try:
                    for d in model.query.all():
                        if d.unique_id:
                            name_map[d.unique_id] = (str(d.name or _tt), _tt)
                except Exception:
                    continue

            def _fmt(n):
                try:
                    t = n.date_time.strftime('%Y-%m-%d') if n.date_time else ''
                except Exception:
                    t = ''
                txt = (n.note or n.name or '').strip().replace('\n', ' ')
                if len(txt) > txt_len:
                    txt = txt[:txt_len].rstrip() + '…'
                entry = {"t": t, "txt": txt}
                if n.category and n.category != 'general':
                    entry["cat"] = n.category
                return entry

            def _key(n):
                return n.date_time or datetime.min

            digests = []
            for tid, notes in by_target.items():
                notes.sort(key=_key)  # 오래된 것 → 최신
                nm, tp = name_map.get(tid, (None, None))
                if not nm:
                    # 미해석(고아/레거시 id): 그래도 노출하되 노트 메타데이터로 라벨링.
                    nm = (notes[-1].name or notes[-1].target_type or 'unknown')
                    tp = notes[-1].target_type or 'unknown'
                first = notes[0]
                recent = [_fmt(r) for r in reversed(notes[-recent_n:]) if r is not first]
                entry = {
                    "entity": nm,
                    "type": tp,
                    "id": tid,
                    "total": len(notes),
                    "first": _fmt(first),
                }
                if recent:
                    entry["recent"] = recent
                digests.append((notes[-1].date_time or datetime.min, entry))

            digests.sort(key=lambda x: x[0], reverse=True)  # 최근 활동 엔티티 우선
            return [e for (_dt, e) in digests[:max_entities]]
        except Exception:
            logger.exception("Error building note digests")
            return []

    @staticmethod
    def get_energy_context():
        """
        Aggregates INPUT energy usage data (Power consumption).
        """
        try:
            # Reusing existing tool logic
            all_energy = EnergyUsage.query.all()
            dm_all = DeviceMeasurements.query
            conv_all = Conversion.query
            
            stats, graph = return_energy_usage(all_energy, dm_all, conv_all)
            
            # Formulate for AI consumption
            energy_ctx = []
            for e_usage in all_energy:
                stat = stats.get(e_usage.unique_id, {})
                energy_ctx.append({
                    "unique_id": e_usage.unique_id,
                    "name": e_usage.name,
                    "device_id": e_usage.device_id,
                    "usage_kwh": {
                        "hour": stat.get('hour', 0),
                        "day": stat.get('day', 0),
                        "month": stat.get('month', 0)
                    }
                })
            return energy_ctx
        except Exception as e:
            logger.exception("Error getting energy context")
            return []

    @staticmethod
    def get_supply_context():
        """
        Aggregates SUPPLY resources data (Moisture, Chemicals, Heat).
        """
        try:
            supply_ctx = []

            # 1. Irrigation (Moisture)
            designs = IrrigationDesign.query.all()
            for design in designs:
                supply_ctx.append({
                    "type": "moisture",
                    "source": design.name,
                    "device_id": design.function_id, # If function_id is linked to a device/output
                    "value": design.total_volume_applied,
                    "unit": "L",
                    "status": design.status,
                    "last_run": serialize_ts(design.last_run_at) if design.last_run_at else None
                })

            # 2. Sequential Actions (Chemicals/Dosing)
            # Fetch actions that involve 'output' and have 'amount'
            actions = Actions.query.filter(Actions.do_output_amount > 0).all()
            for action in actions:
                # Determining resource type from action or custom_options
                try:
                    opts = json.loads(action.custom_options) if action.custom_options else {}
                    res_type = opts.get('resource_type', 'chemical')
                except:
                    res_type = 'chemical'

                supply_ctx.append({
                    "type": res_type,
                    "source": f"Action_{action.unique_id}",
                    "device_id": action.do_unique_id,
                    "value": action.do_output_amount,
                    "unit": opts.get('unit', 'unit'),
                    "last_action": action.action_type
                })

            return supply_ctx
        except Exception as e:
            logger.exception("Error getting supply context")
            return []

    @staticmethod
    def get_camera_context():
        """
        Returns latest camera status, orientation, and capture metadata.
        """
        try:
            cameras = Camera.query.all()
            camera_ctx = []
            for cam in cameras:
                camera_ctx.append({
                    "unique_id": cam.unique_id,
                    "name": cam.name,
                    "url_still": cam.url_still,
                    "last_still_ts": cam.still_last_ts,
                    "resolution": {"w": cam.width, "h": cam.height},
                    "orientation": {"rotation": cam.rotation, "hflip": cam.hflip, "vflip": cam.vflip},
                    "is_active": cam.stream_started or cam.timelapse_started,
                    "capabilities": {
                        "can_capture": cam.library != 'stream_direct'
                    }
                })
            return camera_ctx
        except Exception as e:
            logger.exception("Error getting camera context")
            return []

    @staticmethod
    def capture_image(camera_id):
        """
        Triggers a new image capture for a specific camera.
        """
        try:
            camera = Camera.query.filter_by(unique_id=camera_id).first()
            if not camera:
                return {"error": "Camera not found"}
            
            # Using AoT's existing camera_record tool
            from aot.devices.camera import camera_record
            tmp_filename = f'{camera.unique_id}_ai_capture.jpg'
            path, filename = camera_record('photo', camera.unique_id, tmp_filename=tmp_filename)
            
            if path and filename:
                return {"status": "success", "file": filename, "path": path}
            else:
                return {"error": "Capture failed"}
        except Exception as e:
            logger.exception(f"Error triggering capture for {camera_id}")
            return {"error": str(e)}

    @staticmethod
    def get_sensor_context(target_device_ids=None):
        """
        Returns latest sensor readings for all active Input devices, or specifically targeted devices.
        No time limit - retrieves the absolute last recorded value.
        The AI can judge data freshness from the timestamp.
        """
        try:
            query = Input.query.filter_by(is_activated=True, is_ai_enabled=True)
            if target_device_ids is not None:
                query = query.filter(Input.unique_id.in_(target_device_ids))
            active_inputs = query.all()
            
            settings = Misc.query.first()
            sensor_ctx = []
            
            for input_dev in active_inputs:
                try:
                    dev_measurements = DeviceMeasurements.query.filter_by(
                        device_id=input_dev.unique_id,
                        is_enabled=True
                    ).all()

                    readings = []
                    # Optimization: Get ALL data for this device in one broad query per unit
                    # to handle tag mismatches (like channel or measure tag differences)
                    units_checked = set()
                    for dm in dev_measurements:
                        conversion = None
                        if dm.conversion_id:
                            conversion = Conversion.query.filter_by(
                                unique_id=dm.conversion_id).first()
                        
                        _, unit, measurement = return_measurement_info(dm, conversion)
                        if not unit or unit in units_checked:
                            continue
                        units_checked.add(unit)

                        try:
                            # Search for any data with this unit for this device
                            data = query_string(unit, input_dev.unique_id, value='LAST')
                            
                            if data:
                                for table in data:
                                    for row in table.records:
                                            val_time = row.values['_time']
                                            
                                            # Timestamp check (2-stage Max Age Validation)
                                            try:
                                                import datetime as dt
                                                now_aware = dt.datetime.now(val_time.tzinfo)
                                                age_seconds = (now_aware - val_time).total_seconds()
                                                
                                                period = float(input_dev.period or 900)
                                                tight_tolerance = period * 1.5
                                                # Stage 2: Max acceptable stale window (8x period, max 7 days)
                                                max_tolerance = min(max(period * 8, 3600), 86400 * 7)
                                                
                                                if age_seconds > max_tolerance:
                                                    continue
                                                
                                                status_tag = "fresh" if age_seconds <= tight_tolerance else "stale"
                                            except:
                                                status_tag = "unknown"
                                                age_seconds = 0
                                                
                                            # val_time is tz-aware (InfluxDB client) so it already carries
                                            # an unambiguous offset, but that offset is UTC — convert to
                                            # this device's own location tz so the displayed clock matches
                                            # what a person there would read, consistent with the rest of
                                            # the location-aware time work (age_seconds/status carry the
                                            # freshness signal the AI actually reasons on; this is display).
                                            try:
                                                from aot.utils.device_tz import resolve_location_tz
                                                _display_time = val_time.astimezone(resolve_location_tz(input_dev.unique_id))
                                            except Exception:
                                                _display_time = val_time
                                            readings.append({
                                                "measurement": row.values.get('measure') or measurement or "unknown",
                                                "value": round(row.values['_value'], 2),
                                                "unit": unit,
                                                "channel": row.values.get('channel'),
                                                "timestamp": _display_time.isoformat(),
                                                "age_seconds": round(age_seconds, 1),
                                                "status": status_tag,
                                                "source": "DB"  # [TASK_8 054_] Label as database source to distinguish from MCP
                                            })
                        except Exception as e:
                            logger.error(f"Error querying sensor {input_dev.unique_id} for unit {unit}: {e}")

                    if readings:
                        # v13.0: Semantic sensor aggregation
                        tier = getattr(AIContextService, '_current_tier', 'standard')
                        readings = AIContextService.summarize_readings(readings, tier=tier)
                        
                        sensor_ctx.append({
                            "input_id": input_dev.unique_id,
                            "name": input_dev.name or input_dev.device,
                            "device": input_dev.device,
                            "latitude": input_dev.latitude,
                            "longitude": input_dev.longitude,
                            "readings": readings
                        })
                except Exception as e:
                    logger.warning(f"Error processing sensor {input_dev.unique_id}: {e}")

            return sensor_ctx
        except Exception as e:
            logger.exception("Error getting sensor context")
            return []

    @staticmethod
    def get_semantic_context():
        """
        Fetches AI-specific notes (category='ai_semantic').
        """
        try:
            ai_notes = Notes.query.filter_by(category='ai_semantic', is_archived=False).all()
            notes_ctx = []
            for note in ai_notes:
                notes_ctx.append({
                    "target_id": note.target_id,
                    "target_type": note.target_type,
                    "content": note.note,
                    "tags": note.tags
                })
            return notes_ctx
        except Exception as e:
            logger.exception("Error getting semantic context")
            return []

    @staticmethod
    def get_device_details(target_id, target_type):
        """
        Fetches the complete database record for a specific device or resource.
        Useful for providing deep context during configuration.
        """
        try:
            from aot.databases.models import Input
            dev = None
            if target_type == 'input':
                dev = Input.query.filter_by(unique_id=target_id).first()
            elif target_type == 'output':
                from aot.databases.models import Output
                dev = Output.query.filter_by(unique_id=target_id).first()
            elif target_type in ['function', 'pid', 'trigger', 'conditional']:
                from aot.databases.models import Functions
                dev = Functions.query.filter_by(unique_id=target_id).first()
            
            if not dev:
                return None

            # Convert to dict, excluding unnecessary or internal/sensitive fields
            details = {}
            # Fields to skip to save tokens and avoid noise (Internal/System only)
            skip_fields = [
                'id', 'unique_id', 'created_at', 'updated_at', 
                'extra_data', 'sort_order', 'is_activated', 'user_id'
            ]
            
            for column in dev.__table__.columns:
                if column.name in skip_fields:
                    continue
                    
                val = getattr(dev, column.name)
                
                # Prune null or empty values
                if val is None or val == "" or val == "None":
                    continue
                
                # Special handling for JSON fields like custom_options
                if column.name == 'custom_options' and isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except:
                        pass
                    
                if isinstance(val, datetime):
                    # naive DB column (SQLite has no tz type) — localize, or a
                    # bare isoformat() shows the UTC hour as if it were local
                    # wall-clock time (e.g. Output.on_until/off_until, a live
                    # control window the AI may reason about directly).
                    val = serialize_ts(val)
                elif isinstance(val, timedelta):
                    # timedelta has no .isoformat() — would raise AttributeError
                    val = str(val)
                
                details[column.name] = val
            
            # Always keep name and type for identity
            details['name'] = getattr(dev, 'name', 'Unknown')
            details['target_type'] = target_type
            
            return details
        except Exception as e:
            logger.error(f"Error getting device details for {target_type}/{target_id}: {e}")
            return None

    # -----------------------------------------------------------------------
    # Phase 3: Schedule Awareness
    # -----------------------------------------------------------------------

    @staticmethod
    def get_upcoming_tasks(hours=24):
        """
        Fetches active tasks scheduled for the next N hours.
        This provides the AI with 'Schedule Awareness'.
        """
        try:
            from aot.databases.models import AITask
            now = utc_now()
            limit = now + timedelta(hours=hours)
            
            # Tasks that are pending/proposed/in_progress/cancelled and have a start time within range
            tasks = AITask.query.filter(
                AITask.status.in_(['pending', 'proposed', 'in_progress', 'scheduled', 'cancelled'])
            ).all()
            
            upcoming = []
            for t in tasks:
                t_start = t.start_date or t.proposed_start
                if t_start and t_start.tzinfo is None:
                    # DB DateTime columns come back naive (SQLite strips tzinfo);
                    # values are always written in UTC, so tag them explicitly.
                    t_start = t_start.replace(tzinfo=timezone.utc)
                if t_start and t_start <= limit and t_start >= (now - timedelta(hours=1)): # Include current/recent
                    upcoming.append({
                        "id": t.unique_id,
                        "title": t.title,
                        "status": t.status,
                        "action": t.action_type,
                        "target": t.target_id,
                        "time": t_start.isoformat(),
                        "desc": t.description[:50] if t.description else ""
                    })
            
            # Sort by time
            upcoming.sort(key=lambda x: x['time'])
            return upcoming
            
        except Exception as e:
            logger.exception("Error getting upcoming tasks")
            return []

    @staticmethod
    def get_human_schedule_context(days_ahead: int = 30) -> str:
        """
        Build a formatted, multi-layer text block of upcoming human-scheduled
        entries so the AI can both give concrete near-term advice ("3일 뒤
        수확 예정이니 그 전 방제 간격을 앞당기세요") and stay aware of the
        month ahead without the context ballooning.

        Calls AISchedulerService.get_schedule_horizon() and renders 3 tiers:
        - Imminent (next 48h) and This week (2-7 days): full detail per item
          (content + location + time) — near enough to act on concretely.
        - This month (7-`days_ahead` days): per-category COUNTS only (e.g.
          "[방제] 4건, [수확] 2건") — awareness without spelling out every
          row, so a busy month doesn't blow the token budget.

        Returns a non-empty string even when everything is empty
        ('[Farm Schedule Horizon]\n(none scheduled)').

        This block is appended to the master context under the key
        'human_schedules' and must NOT replace the AITask scheduled_tasks key.
        """
        # @ANCHOR: GET_HUMAN_SCHEDULE_CONTEXT [2026-07-20 — multi-layer horizon]
        try:
            from aot.ai.services.ai_scheduler_service import AISchedulerService
            horizon = AISchedulerService.get_schedule_horizon(days_ahead=days_ahead)
        except Exception:
            logger.exception("get_human_schedule_context: import/call failed")
            horizon = {'imminent': [], 'this_week': [], 'this_month': [], 'truncated': False}

        def _fmt_time(iso_str, target_id=None):
            # get_schedule_horizon returns an unambiguous UTC ISO string (with
            # offset) — convert to the SCHEDULE'S OWN LOCATION's local wall-clock
            # time for display (every zone/site/device resolves its own tz from
            # coordinates — see aot/utils/device_tz.py), falling back to the
            # farm-wide Misc.timezone when the schedule has no linked location.
            # That's what the user actually said ("오전 8시") and what the AI
            # should reason about, not a bare UTC instant or an assumed single tz.
            if not iso_str:
                return 'N/A'
            try:
                dt = datetime.fromisoformat(iso_str)
                from aot.utils.device_tz import resolve_location_tz
                tz = resolve_location_tz(target_id)
                return dt.astimezone(tz).strftime('%Y-%m-%d %H:%M')
            except Exception:
                try:
                    return to_local(datetime.fromisoformat(iso_str)).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    return iso_str

        def _fmt_item(e):
            loc = e.get('location')
            return (f"- [{e.get('category', '기타')}] {e.get('job_name', 'unknown')}"
                    + (f" @ {loc}" if loc else "")
                    + f"  |  {_fmt_time(e.get('schedule_time'), e.get('target_id'))}")

        def _category_counts(entries):
            counts = {}
            for e in entries:
                cat = e.get('category', '기타')
                counts[cat] = counts.get(cat, 0) + 1
            return ", ".join(f"[{cat}] {n}건" for cat, n in counts.items())

        imminent = horizon.get('imminent') or []
        this_week = horizon.get('this_week') or []
        this_month = horizon.get('this_month') or []

        if not (imminent or this_week or this_month):
            return "[Farm Schedule Horizon]\n(none scheduled)"

        lines = ["[Farm Schedule Horizon]"]

        lines.append(f"Imminent (next 48h) — {len(imminent)} item(s):")
        lines += [_fmt_item(e) for e in imminent] if imminent else ["  (none)"]

        lines.append(f"This week (2-7 days) — {len(this_week)} item(s):")
        lines += [_fmt_item(e) for e in this_week] if this_week else ["  (none)"]

        lines.append(f"This month ({days_ahead} days) — by category:")
        lines.append("  " + (_category_counts(this_month) if this_month else "(none)"))

        if horizon.get('truncated'):
            lines.append(f"(more schedules exist beyond this {days_ahead}-day window/cap — use search_schedule for the full list)")

        return "\n".join(lines)

    @staticmethod
    def get_global_decisions(months=6):
        """
        Retrieves summarized decisions and plans from across all threads.
        Filters by 'ai_semantic' category in Notes and recent AITasks.
        Helps AI maintain 'Cross-thread Memory'.
        """
        try:
            from aot.databases.models import Notes, AITask
            cutoff = utc_now() - timedelta(days=months * 30)
            
            # 1. Semantic Notes (Confirmed knowledge/decisions)
            notes = Notes.query.filter(
                Notes.category == 'ai_semantic',
                Notes.is_archived == False,
                Notes.date_time >= cutoff
            ).all()
            
            valid_notes = []
            for n in notes:
                tags = n.tags.split(',') if n.tags else []
                # Filter out 'incorrect', 'obsolete', or 'error' tagged info
                if any(t.strip().lower() in ['incorrect', 'obsolete', 'error'] for t in tags):
                    continue
                valid_notes.append({
                    "topic": n.target_type,
                    "content": n.note,
                    "tags": tags,
                    "created": n.date_time.isoformat()
                })
            
            # 2. Strategic AITasks (Major goals or milestones)
            tasks = AITask.query.filter(
                AITask.status.in_(['proposed', 'scheduled', 'in_progress', 'executed']),
                AITask.is_goal == True,
                AITask.created_at >= cutoff
            ).all()
            
            active_plans = []
            for t in tasks:
                active_plans.append({
                    "title": t.title,
                    "status": t.status,
                    "desc": t.description[:200] if t.description else ""
                })

            return {
                "confirmed_knowledge": valid_notes,
                "strategic_plans": active_plans
            }
        except Exception:
            logger.exception("Error getting global decisions")
            return {}

    @staticmethod
    def get_hierarchical_data(hierarchy, energy_map, supply_map):
        """
        Traverses spatial hierarchy and sums energy/resource usage for each node recursively.
        energy_map: { device_id: { hour: x, day: y, month: z } }
        supply_map: { device_id: [ {type: moisture, value: 10, unit: L}, ... ] }
        """
        level_total_energy = {"hour": 0, "day": 0, "month": 0}
        level_total_supply = {} # type: value sum

        for node in hierarchy:
            # 1. Node Input Energy
            node_energy = {"hour": 0, "day": 0, "month": 0}
            d_id = node.get('device_id')
            if d_id and d_id in energy_map:
                stat = energy_map[d_id]
                node_energy["hour"] += stat.get('hour', 0)
                node_energy["day"] += stat.get('day', 0)
                node_energy["month"] += stat.get('month', 0)
            
            # 2. Node Resource Supply
            node_supply = []
            if d_id and d_id in supply_map:
                node_supply.extend(supply_map[d_id])

            # 3. Recurse for children
            if node['children']:
                child_energy, child_supply = AIContextService.get_hierarchical_data(node['children'], energy_map, supply_map)
                
                # Sum Energy
                node_energy["hour"] += child_energy["hour"]
                node_energy["day"] += child_energy["day"]
                node_energy["month"] += child_energy["month"]

                # Sum Supply (Aggregate by type)
                merged_supply = {s['type']: {'value': s['value'], 'unit': s['unit']} for s in node_supply}
                for cs in child_supply:
                    t = cs['type']
                    if t in merged_supply:
                        merged_supply[t]['value'] += cs['value']
                    else:
                        merged_supply[t] = {'value': cs['value'], 'unit': cs['unit']}
                node_supply = [{"type": k, "value": v['value'], "unit": v['unit']} for k, v in merged_supply.items()]

            node["energy_input"] = node_energy
            node["resource_supply"] = node_supply
            
            # 4. Add to level totals
            level_total_energy["hour"] += node_energy["hour"]
            level_total_energy["day"] += node_energy["day"]
            level_total_energy["month"] += node_energy["month"]

            for s in node_supply:
                t = s['type']
                if t in level_total_supply:
                    level_total_supply[t] += s['value']
                else:
                    level_total_supply[t] = s['value']

        # Flatten level_total_supply for return
        supply_list = [{"type": k, "value": v} for k, v in level_total_supply.items()]
        return level_total_energy, supply_list

    # Device → zone location, derived SPATIALLY (see get_device_zone_map). Cached and
    # invalidated by GeoShape changes, mirroring _SPATIAL_CACHE.
    _DEVICE_ZONE_CACHE = None
    _DEVICE_ZONE_TAG = None

    @staticmethod
    def _geo_shape_revision_tag():
        """Cache-invalidation tag for GeoShape-derived caches below. MUST change on
        an in-place EDIT of an existing shape, not just an insert/delete — GIS
        editor saves (GeoOverlayManager.save_overlays) UPDATE a matched shape's row
        in place (`row.feature = feat; row.updated_at = utcnow()`), leaving its id
        and the table's max(id) unchanged. A tag keyed on max(id) alone never
        invalidates for a pure reshape/reassign edit — combine with max(updated_at)
        so any insert, delete, OR in-place edit changes the tag."""
        row = db.session.query(func.max(GeoShape.id), func.max(GeoShape.updated_at)).one()
        return (row[0] or 0, row[1])

    @staticmethod
    def get_device_zone_map():
        """Return {device_id: zone_name}, resolving each device's zone by SPATIAL
        containment of its geo shape's centroid inside a zone polygon.

        Devices are frequently drawn as polygons INSIDE a zone but not explicitly
        linked (parent_zone / map_overlay_id unset), so their location is only
        derivable spatially — without this the AI cannot answer location requests
        like "1포장 1-4구역 밸브 켜줘". Read-only; cached per GeoShape revision."""
        from shapely.geometry import shape as _shape
        try:
            tag = AIContextService._geo_shape_revision_tag()
            if AIContextService._DEVICE_ZONE_CACHE is not None and AIContextService._DEVICE_ZONE_TAG == tag:
                return AIContextService._DEVICE_ZONE_CACHE

            def _feat(s):
                f = s.feature
                if isinstance(f, str):
                    try: f = json.loads(f)
                    except Exception: f = {}
                return f or {}

            zones = []
            for s in GeoShape.query.filter(GeoShape.type.in_(['site', 'zone'])).all():
                f = _feat(s)
                if 'geometry' not in f:
                    continue
                try:
                    g = _shape(f['geometry'])
                    if g.is_valid and g.geom_type in ('Polygon', 'MultiPolygon'):
                        zones.append({
                            'name': (f.get('properties', {}) or {}).get('name'),
                            'geom': g, 'bounds': g.bounds,
                            'is_zone': s.type == 'zone', 'area': g.area,
                        })
                except Exception:
                    continue

            out = {}
            for s in GeoShape.query.filter_by(type='device').all():
                f = _feat(s)
                pr = f.get('properties', {}) or {}
                did = pr.get('device_id') or pr.get('aot_device_id') or pr.get('unique_id') or s.device_id
                geom = f.get('geometry')
                if not did or not geom or did in out:
                    continue
                try:
                    c = _shape(geom).centroid
                    px, py = c.x, c.y
                    matches = [z for z in zones
                               if not (px < z['bounds'][0] or px > z['bounds'][2]
                                       or py < z['bounds'][1] or py > z['bounds'][3])
                               and z['geom'].contains(c)]
                    if matches:
                        matches.sort(key=lambda x: (not x['is_zone'], x['area']))
                        if matches[0]['name']:
                            out[did] = matches[0]['name']
                except Exception:
                    continue

            AIContextService._DEVICE_ZONE_CACHE = out
            AIContextService._DEVICE_ZONE_TAG = tag
            return out
        except Exception as e:
            logger.debug(f"[DeviceZone] map failed: {e}")
            return {}

    _ZONE_SITE_CACHE = None
    _ZONE_SITE_TAG = None

    @staticmethod
    def get_zone_site_map():
        """Return {zone_name: site_name} by SPATIAL containment of each zone's
        centroid inside a site polygon. Lets a location-scoped proposal name the
        site for a zone ("1-3" → "1포장") without re-resolving per request. Cached
        per GeoShape revision."""
        from shapely.geometry import shape as _shape
        try:
            tag = AIContextService._geo_shape_revision_tag()
            if AIContextService._ZONE_SITE_CACHE is not None and AIContextService._ZONE_SITE_TAG == tag:
                return AIContextService._ZONE_SITE_CACHE

            def _feat(s):
                f = s.feature
                if isinstance(f, str):
                    try: f = json.loads(f)
                    except Exception: f = {}
                return f or {}

            sites = []
            zones = []
            for s in GeoShape.query.filter(GeoShape.type.in_(['site', 'zone'])).all():
                f = _feat(s)
                geom = f.get('geometry')
                name = (f.get('properties', {}) or {}).get('name')
                if not geom or not name:
                    continue
                try:
                    g = _shape(geom)
                    if not g.is_valid or g.geom_type not in ('Polygon', 'MultiPolygon'):
                        continue
                except Exception:
                    continue
                (sites if s.type == 'site' else zones).append({'name': name, 'geom': g, 'area': g.area})

            out = {}
            for z in zones:
                c = z['geom'].centroid
                containing = [s for s in sites if s['geom'].contains(c)]
                if containing:
                    containing.sort(key=lambda x: x['area'])  # smallest containing site
                    out[z['name']] = containing[0]['name']
            AIContextService._ZONE_SITE_CACHE = out
            AIContextService._ZONE_SITE_TAG = tag
            return out
        except Exception as e:
            logger.debug(f"[ZoneSite] map failed: {e}")
            return {}

    @staticmethod
    def resolve_point_to_location(lat, lng):
        """Given a map viewport center (lat, lng), return {'site': name|None,
        'zone': name|None} it falls within by SPATIAL containment.

        zone = the most-specific (smallest-area) containing 'zone' polygon; site =
        the smallest containing 'site' polygon. Lets a vague control command
        ("밸브 다 열어줘") be scoped to whatever site/zone the user is looking at on
        the dashboard map. Read-only."""
        from shapely.geometry import Point, shape as _shape
        try:
            pt = Point(float(lng), float(lat))  # GeoJSON order is (x=lng, y=lat)
        except (TypeError, ValueError):
            return {'site': None, 'zone': None}
        try:
            site_name, site_area = None, None
            zone_name, zone_area = None, None
            for s in GeoShape.query.filter(GeoShape.type.in_(['site', 'zone'])).all():
                f = s.feature
                if isinstance(f, str):
                    try: f = json.loads(f)
                    except Exception: f = {}
                f = f or {}
                geom = f.get('geometry')
                name = (f.get('properties', {}) or {}).get('name')
                if not geom or not name:
                    continue
                try:
                    g = _shape(geom)
                    if not g.is_valid or g.geom_type not in ('Polygon', 'MultiPolygon'):
                        continue
                    b = g.bounds
                    if pt.x < b[0] or pt.x > b[2] or pt.y < b[1] or pt.y > b[3]:
                        continue
                    if not g.contains(pt):
                        continue
                    if s.type == 'zone':
                        if zone_area is None or g.area < zone_area:
                            zone_area, zone_name = g.area, name
                    else:
                        if site_area is None or g.area < site_area:
                            site_area, site_name = g.area, name
                except Exception:
                    continue
            return {'site': site_name, 'zone': zone_name}
        except Exception as e:
            logger.debug(f"[PointLoc] resolve failed: {e}")
            return {'site': None, 'zone': None}

    @staticmethod
    def get_device_list_summary():
        """
        Returns list of {id, name, type, zone?} for all active inputs and outputs
        that are AI-enabled. 'zone' (when known) is the device's location, resolved
        spatially — lets the AI answer location requests ("1-4구역 밸브").
        """
        try:
            from aot.databases.models import Input, Output
            inputs = Input.query.filter_by(is_activated=True, is_ai_enabled=True).all()
            outputs = Output.query.filter_by(is_ai_enabled=True).all()
            zmap = AIContextService.get_device_zone_map()

            device_list = []
            for inp in inputs:
                _e = {"id": inp.unique_id, "name": inp.name or inp.unique_id, "type": inp.device}
                if zmap.get(inp.unique_id):
                    _e["zone"] = zmap[inp.unique_id]
                device_list.append(_e)
            for out in outputs:
                _e = {"id": out.unique_id, "name": out.name or out.unique_id, "type": out.output_type}
                if zmap.get(out.unique_id):
                    _e["zone"] = zmap[out.unique_id]
                device_list.append(_e)
            return device_list
        except Exception as e:
            logger.error(f"Error in get_device_list_summary: {e}")
            return []

    @staticmethod
    def get_mini_context(intent=None):
        """
        Fast Path context — spatial hierarchy names only + device list.
        NO InfluxDB calls (0 HTTP requests vs 60+ in full context).
        AI should use virtual_tool_call / get_sensor_detail for actual data.
        """
        try:
            now = get_local_now().isoformat()

            # Lightweight spatial hierarchy (names/types only, no sensor data)
            hierarchy = AIContextService.get_spatial_hierarchy()
            # Strip live data from hierarchy to keep it minimal
            def strip_live_data(nodes):
                for node in nodes:
                    node.pop('live_readings', None)
                    node.pop('energy_kwh', None)
                    node.pop('supply_resources', None)
                    if node.get('children'):
                        strip_live_data(node['children'])
            if hierarchy:
                strip_live_data(hierarchy)

            devices = AIContextService.get_device_list_summary()

            return {
                "timestamp": now,
                "mode": "fast_path",
                "spatial_hierarchy": hierarchy,
                "device_list": devices,
                "data_access_hint": (
                    "This is a lightweight context with NO live sensor data. "
                    "To get sensor readings, use 'virtual_tool_call' with action 'get_sensor_detail' "
                    "and provide the device unique_id and optional time_range. "
                    "Do NOT guess values — always query."
                ),
            }
        except Exception as e:
            logger.error(f"get_mini_context error: {e}")
            return {"timestamp": get_local_now().isoformat(), "mode": "fast_path", "error": str(e)}

    @staticmethod
    def get_master_context(include_keys=None, is_slim=False, tier='standard', focused_target=None):
        """
        Unified context aggregator.
        v6.1: Master data pruning - only returns requested domains to save tokens.
        v12.6: Ultra-slim mode for low-TPM workers.
        v13.0: Semantic data abstraction via tier.
        v6.4: Request-scoped cache — eliminates duplicate DB queries within the same request.
        """
        # @ANCHOR: MASTER_CONTEXT_REQUEST_CACHE [2026-03-25]
        try:
            from flask import g, has_request_context
            import hashlib, json as _json
            if has_request_context():
                if not hasattr(g, '_master_context_cache'):
                    g._master_context_cache = {}
                _keys_key = tuple(sorted(include_keys)) if include_keys else None
                _ft_key = _json.dumps(focused_target, sort_keys=True) if focused_target else None
                _cache_key = (_keys_key, is_slim, tier, _ft_key)
                if _cache_key in g._master_context_cache:
                    return g._master_context_cache[_cache_key]
        except Exception:
            pass

        try:
            # v13.0: Propagation of tier for static helpers
            AIContextService._current_tier = tier
            
            now = get_local_now().isoformat()
            
            # v12.6: Tier-based key masking (Pre-emptive diet)
            if tier == 'lightweight':
                # Force-exclude potentially large/non-essential keys for free tiers
                exclude_for_slim = ['geo_designs', 'semantics', 'dashboards', 'domain_glossary', 'available_api_keys']
                if include_keys:
                    include_keys = [k for k in include_keys if k not in exclude_for_slim]
                else:
                    # Default keys for lightweight if none specified
                    include_keys = ['spatial_hierarchy', 'sensor_readings', 'scheduled_tasks']
            
            # 0. Helper for token pruning
            def should_include(key):
                return not include_keys or key in include_keys

            # 1. Base Contexts (Lazy and selective)
            hierarchy = AIContextService.get_spatial_hierarchy(tier=tier) if should_include('spatial_hierarchy') or should_include('input_energy_summary') or should_include('supply_resource_summary') else []
            energy_raw = AIContextService.get_energy_context() if should_include('input_energy_summary') else []
            supply_raw = AIContextService.get_supply_context() if should_include('supply_resource_summary') else []
            cameras = AIContextService.get_camera_context() if should_include('cameras') else []
            sensors = AIContextService.get_sensor_context() if should_include('sensor_readings') else []
            semantics = AIContextService.get_semantic_context() if should_include('semantics') else []
            scheduled = AIContextService.get_upcoming_tasks() if should_include('scheduled_tasks') else []
            human_schedules = AIContextService.get_human_schedule_context() if should_include('scheduled_tasks') or should_include('human_schedules') else None
            geo_maps = AIContextService.get_geo_context() if should_include('geo_designs') else []
            global_plans = AIContextService.get_global_decisions() if should_include('global_plans') else {}
            domain_glossary = AILearningService.get_active_glossary() if should_include('domain_glossary') else []
            dash_id = focused_target.get('dashboard_id') if focused_target else None
            dashboards = AIContextService.get_dashboard_context(dashboard_id=dash_id) if should_include('dashboards') else []
            
            # v26.0: Semantic Snapshots for baseline awareness
            semantic_snapshots = []
            if should_include('spatial_hierarchy'):
                from aot.ai.services.cache_manager import CacheManager
                # Get system summary
                sys_summary = CacheManager.get_latest_summary('system', None)
                if sys_summary: semantic_snapshots.append(sys_summary)
                
                # If focused on a farm, get that farm's summary too
                if focused_target and focused_target.get('targetType') == 'farm':
                    farm_summary = CacheManager.get_latest_summary('farm', focused_target.get('targetId'))
                    if farm_summary: semantic_snapshots.append(farm_summary)

            focused_details = None
            if focused_target and focused_target.get('targetId') and focused_target.get('targetType'):
                focused_details = AIContextService.get_device_details(
                    focused_target['targetId'], 
                    focused_target['targetType']
                )
            
            # 2. Map Data for Hierarchical Aggregation
            energy_map = {e['device_id']: e['usage_kwh'] for e in energy_raw if e['device_id']}
            
            supply_map = {}
            for s in supply_raw:
                d_id = s.get('device_id')
                if d_id:
                    if d_id not in supply_map:
                        supply_map[d_id] = []
                    supply_map[d_id].append({
                        "type": s['type'],
                        "value": s['value'],
                        "unit": s['unit']
                    })

            # 3. Perform Hierarchical Aggregation (Only if hierarchy and either energy or supply is present)
            if hierarchy and (energy_map or supply_map):
                AIContextService.get_hierarchical_data(hierarchy, energy_map, supply_map)
            
            # 4. Data Enrichment: Map sensors directly into hierarchy nodes
            if hierarchy and sensors:
                sensor_map = {s['input_id']: s['readings'] for s in sensors}
                
                def inject_sensors(nodes):
                    for node in nodes:
                        d_id = node.get('device_id')
                        if d_id and d_id in sensor_map:
                            readings = sensor_map[d_id]
                            # v14.1: readings may be a dict (summarized) or list (raw)
                            if isinstance(readings, list):
                                limit = 3 if tier == 'lightweight' else 10
                                # v16.1: Safety check for empty or non-indexable list
                                try:
                                    node['live_readings'] = readings[:limit]
                                except (TypeError, KeyError):
                                    node['live_readings'] = []
                            else:
                                # Already summarized by summarize_readings() — use as-is
                                node['live_readings'] = readings
                        if node.get('children'):
                            inject_sensors(node['children'])
                
                inject_sensors(hierarchy)
                
                # v12.5: If hierarchy is present (and contains sensors), 
                # we don't need 'sensor_readings' as a huge top-level dictionary
                if should_include('spatial_hierarchy'):
                    sensors = [] # Clear top-level sensors to prevent 400 Refusal/TPM issues
            
            # 5. Global Context Awareness: If a zone has no sensors, identify "Global Devices" (Weather, etc.)
            # Add a dedicated section to help AI find weather for unnamed zones
            global_sensors = [s for s in sensors if 'weather' in (s.get('name') or '').lower() or 'weather' in (s.get('device') or '').lower()]
            
            master = {
                "timestamp": now,
                "historical_data_hint": "Live context only includes FRESH/STALE recent data. For deep history (e.g. '12h trend'), you MUST use 'mcp_influxdb' tool calls to query Flux data directly. Do not guess trends from this summary."
            }
            if global_sensors:
                master["global_environment_sensors"] = global_sensors
            
            if should_include('geo_designs'): master["geo_designs"] = geo_maps
            if should_include('spatial_hierarchy'): master["spatial_hierarchy"] = hierarchy
            if should_include('sensor_readings'): master["sensor_readings"] = sensors
            if should_include('input_energy_summary'): master["input_energy_summary"] = energy_raw
            if should_include('supply_resource_summary'): master["supply_resource_summary"] = supply_raw
            if should_include('cameras'): master["cameras"] = cameras
            if should_include('semantics'): master["semantics"] = semantics
            if should_include('scheduled_tasks'): master["scheduled_tasks"] = scheduled
            if human_schedules: master["human_schedules"] = human_schedules
            if should_include('global_plans'): master["global_plans"] = global_plans
            if should_include('domain_glossary'): master["domain_glossary"] = domain_glossary
            if should_include('dashboards'): master["dashboards"] = dashboards
            if semantic_snapshots: master["semantic_snapshots"] = semantic_snapshots
            if focused_details: master["focused_device_details"] = focused_details

            # 엔티티별 노트 다이제스트(초기+최근) — "각 장치의 노트"를 컨텍스트만으로
            # 인지/요약하게 하고, 상세는 search_notes 로 드릴다운. lightweight 제외.
            if tier != 'lightweight' and should_include('note_digests'):
                note_digests = AIContextService.get_note_digests(tier=tier)
                if note_digests:
                    master["note_digests"] = note_digests

            # Phase 2: Inject Context Metadata (Philosophy Alignment: P1_Honesty, P3_Transparency)
            # ONLY for standard/heavy tiers (excluded for lightweight to preserve token budget)
            if tier != 'lightweight':
                try:
                    from aot.ai.services.context_metadata_builder import ContextMetadataBuilder
                    from flask_login import current_user

                    if current_user and current_user.is_authenticated:
                        facility_id = current_user.current_facility_id if hasattr(current_user, 'current_facility_id') else None
                        if facility_id:
                            # Load domain module data for enrichment
                            from aot.ai.services.domain_context_loader import DomainContextLoader
                            domain_module = DomainContextLoader.load_active_module(
                                facility_id,
                                include_layer4=False,
                                resolve_growth_stage=True,
                            )

                            # Build context metadata
                            context_metadata = ContextMetadataBuilder.build(
                                facility_id=facility_id,
                                raw_context_dict=master,
                                domain_module_data=domain_module,
                            )

                            if context_metadata:
                                master["context_metadata"] = context_metadata
                except Exception as e:
                    logger.warning("Failed to inject context_metadata (Phase 2): %s", e)

            # Phase 6: Inject AI Documentation Index (ONLY for standard/heavy tiers)
            if tier != 'lightweight':
                try:
                    from aot.config import INSTALL_DIRECTORY
                    import os
                    index_path = os.path.join(INSTALL_DIRECTORY, "docs/ai_docs/ai_doc_index.json")
                    if os.path.exists(index_path):
                        with open(index_path, "r", encoding="utf-8") as f:
                            idx_data = json.load(f)
                            if tier == 'lightweight':
                                # v16.3: Slim Index (Filenames only) to save ~30KB
                                master["manual_index_files"] = list(idx_data.keys())
                                master["manual_index_hint"] = "Use 'read_manual' with these filenames for details."
                            else:
                                master["manual_index"] = idx_data
                except Exception as e:
                    logger.error(f"Failed to load AI doc index: {e}")

            # API Keys summary for AI (names and providers only, no secrets)
            try:
                from aot.databases.models import APIKey
                api_keys_raw = APIKey.query.all()
                if api_keys_raw:
                    master["available_api_keys"] = [
                        {"name": k.name, "provider": k.provider, "tag": k.tag}
                        for k in api_keys_raw
                    ]
            except Exception:
                pass

            # User Profile Injection (Phase 25)
            if current_user and current_user.is_authenticated:
                profile = AILearningService.get_user_profile(current_user.id)
                if profile:
                    master["user_profile"] = {
                        "level": profile.proficiency_level,
                        "score": profile.proficiency_score,
                        "notes": json.loads(profile.learning_notes_json) if profile.learning_notes_json else {}
                    }

            # Active Functions Injection (Conditional/Trigger/PID/Custom)
            # Skipped for lightweight tier to conserve tokens
            if tier != 'lightweight':
                try:
                    from aot.ai.services.aot_data_tool_service import AoTDataToolService
                    fn_result = AoTDataToolService.get_active_functions_summary()
                    fn_list = fn_result.get("active_functions", [])
                    if fn_list:
                        master["active_functions"] = fn_list
                except Exception:
                    logger.warning("Failed to inject active_functions into master context", exc_info=True)

            # Phase 6 & 12.6: Aggressive Prompt Compression (Token Diet)
            def compact(obj, depth=0):
                if depth > 10: return None # Strictly limit depth
                if isinstance(obj, list):
                    # v12.6: Aggressive list truncation for lightweight tier
                    # v16.2: Reduced cap from 8 to 5 for lightweight to ensure safety margin
                    cap = 5 if tier == 'lightweight' else 30
                    if len(obj) > cap: 
                        obj = obj[:cap] + [{"...": f"Truncated {len(obj)-cap} items"}]
                    return [compact(x, depth+1) for x in obj if x is not None]
                elif isinstance(obj, dict):
                    res = {}
                    for k, v in obj.items():
                        if v is not None and v != [] and v != {}:
                            # Strip large metadata blobs that AI usually doesn't need for reasoning
                            if tier == 'lightweight' and k in ['meta', 'extra_data', 'feature', 'config_options', 'custom_options']:
                                continue
                            compacted_v = compact(v, depth+1)
                            if compacted_v: res[k] = compacted_v
                    return res
                return obj
            
            result = compact(master)
            # @ANCHOR: MASTER_CONTEXT_REQUEST_CACHE [2026-03-25]
            try:
                from flask import g, has_request_context
                if has_request_context() and hasattr(g, '_master_context_cache'):
                    g._master_context_cache[_cache_key] = result
            except Exception:
                pass
            return result
        except Exception as e:
            logger.exception("Error creating master context")
            return {"error": str(e)}

    @staticmethod
    def get_geo_context():
        """
        Extracts available map designs and drawn zones/sites (e.g. 2포장).
        Helps the AI understand user-defined agricultural zones or sites.
        """
        try:
            maps = GeoMap.query.all()
            geo_ctx = []
            for m in maps:
                shapes = GeoShape.query.filter_by(geo_id=m.unique_id).all()
                shape_info = []
                for s in shapes:
                    feat = s.feature or {}
                    if isinstance(feat, str):
                        try: feat = json.loads(feat)
                        except: feat = {}
                    props = feat.get('properties', {})
                    meta = s.meta_json if s.meta_json else {}
                    
                    # Robust Name Search: meta -> properties (label/name) -> default
                    name = (meta.get('name') or 
                            props.get('label') or props.get('name') or props.get('label_name') or
                            'Unnamed shape')
                    
                    shape_info.append({
                        "id": s.id,
                        "geo_id": s.geo_id,
                        "type": s.type, # 'site', 'zone', 'feature'
                        "name": name,
                        "drawn_device_id": s.device_id,
                        "layer_group": s.layer_group,
                        "geometry": AIContextService.simplify_geometry(feat.get('geometry'), tier=getattr(AIContextService, '_current_tier', 'standard'))
                    })
                
                geo_ctx.append({
                    "map_id": m.unique_id,
                    "map_name": m.name,
                    "provider": m.provider,
                    "registered_shapes": shape_info
                })
            return geo_ctx
        except Exception as e:
            logger.exception("Error building geo context")
            return []

    @staticmethod
    def get_dashboard_context(dashboard_id=None):
        """
        Extracts user dashboard configurations and widget layouts.
        This provides AI awareness of 'what the user is currently looking at'.
        If dashboard_id is provided, only retrieves that specific dashboard to save tokens and time.
        """
        try:
            from aot.databases.models import Dashboard, Widget
            
            query = Dashboard.query
            if dashboard_id:
                query = query.filter_by(unique_id=dashboard_id)
            dashboards = query.order_by(Dashboard.sort_order.asc()).all()
            
            dash_ctx = []
            
            for dash in dashboards:
                # Widgets bind to a dashboard via tab_id (== Dashboard.unique_id);
                # there is no Widget.dashboard_id column. Using it raised
                # InvalidRequestError, which the outer try/except swallowed — so the
                # AI silently got NO dashboard/widget context on every call.
                widgets = Widget.query.filter_by(tab_id=dash.unique_id).all()
                widget_info = []
                
                # Phase 16: Collect relevant device_ids from widgets to fetch live readings
                target_device_ids = set()
                
                for w in widgets:
                    # Exclude raw positioning data (x, y, w, h) to save tokens
                    opts = {}
                    try:
                        if w.custom_options:
                            opts = json.loads(w.custom_options)
                    except:
                        pass
                    
                    # Extract device IDs from various possible keys
                    if 'device_ids' in opts and isinstance(opts['device_ids'], list):
                        target_device_ids.update(opts['device_ids'])
                    if 'device_selection_input' in opts and isinstance(opts['device_selection_input'], list):
                        target_device_ids.update(opts['device_selection_input'])
                        
                    # RC-1: Parse output_device_ids from w.output_ids
                    # w.output_ids format: "uuid,meas_id;uuid2,meas_id2"
                    _output_device_ids = []
                    if w.output_ids:
                        for _pair in w.output_ids.split(';'):
                            _parts = _pair.strip().split(',')
                            if _parts and _parts[0].strip():
                                _output_device_ids.append(_parts[0].strip())

                    widget_info.append({
                        "widget_id": w.unique_id,
                        "name": w.name,              # RC-1: Widget name (e.g. "밸브2") for AI device mapping
                        "type": w.graph_type,        # e.g. 'AoT_graph', 'AoT_gauge_angular'
                        "output_device_ids": _output_device_ids,  # RC-1: Output UUIDs for control mapping
                        "config_options": opts       # Contains target devices/channels
                    })
                    
                # Fetch live readings only for devices present on this dashboard
                live_sensor_data = []
                if target_device_ids:
                    live_sensor_data = AIContextService.get_sensor_context(target_device_ids=list(target_device_ids))
                    
                # Inject relevant live readings into widget info
                for w_info in widget_info:
                    opts = w_info.get("config_options", {})
                    w_targets = set()
                    if 'device_ids' in opts and isinstance(opts['device_ids'], list):
                        w_targets.update(opts['device_ids'])
                    if 'device_selection_input' in opts and isinstance(opts['device_selection_input'], list):
                        w_targets.update(opts['device_selection_input'])
                        
                    if w_targets:
                        w_readings = [r for r in live_sensor_data if r.get('input_id') in w_targets]
                        if w_readings:
                            w_info['live_readings'] = w_readings
                            
                    # v15.0: Visual Context Mirroring (Highcharts Interpretation)
                    w_info['visual_interpretation'] = AIContextService.get_widget_visual_summary(
                        w.unique_id, w.graph_type, opts
                    )
                            
                    # Phase 17: Dynamic GIS Layer Enrichment (replaces hardcoded ISRIC/NASA logic)
                    if w_info['type'] == 'AoT_map' and 'active_layers' in opts:
                        active_layers = opts.get('active_layers', [])
                        if isinstance(active_layers, str):
                            active_layers = [l.strip() for l in active_layers.split(',')]
                            
                        center = opts.get('fallback_center')
                        
                        # Smart coordinate fallback: widget center → global settings → device coordinates
                        if not center or not isinstance(center, list) or len(center) != 2:
                            from aot.databases.models import Misc, Input, Output
                            misc_settings = Misc.query.first()
                            if misc_settings and misc_settings.map_latitude and misc_settings.map_longitude:
                                lat, lng = misc_settings.map_latitude, misc_settings.map_longitude
                            else:
                                first_input = Input.query.filter(Input.latitude.isnot(None), Input.longitude.isnot(None)).first()
                                if first_input:
                                    lat, lng = first_input.latitude, first_input.longitude
                                else:
                                    first_output = Output.query.filter(Output.latitude.isnot(None), Output.longitude.isnot(None)).first()
                                    if first_output:
                                        lat, lng = first_output.latitude, first_output.longitude
                                    else:
                                        lat, lng = 37.5665, 126.9780
                        else:
                            lat, lng = center[0], center[1]
                        
                        # Dynamic plugin call — each GIS module reports its own data
                        try:
                            from aot.inputs.satellite_analysis import discover_and_query_for_ai
                            wms_data = discover_and_query_for_ai(active_layers, lat, lng)
                            if wms_data:
                                w_info['wms_readings'] = wms_data
                        except Exception as e:
                            logger.warning(f"Dynamic GIS enrichment failed: {e}")
                
                dash_ctx.append({
                    "dashboard_id": dash.unique_id,
                    "name": dash.name,
                    "widgets": widget_info
                })
                
            return dash_ctx
        except Exception as e:
            logger.exception("Error building dashboard context")
            return []

    @staticmethod
    def get_widget_visual_summary(widget_id, widget_type, options):
        """
        v15.0: Mirrored Visual Context.
        Translates Highcharts/Gauge configuration into a semantic summary for AI.
        """
        summary = {"timeframe": "live_only", "status": "unknown"}
        try:
            from aot.utils.influx import read_influxdb_list
            
            # --- Gauge Interpretation ---
            if 'gauge' in widget_type.lower():
                summary['type'] = 'gauge'
                summary['min'] = options.get('min', 0)
                summary['max'] = options.get('max', 100)
                
                # Extract danger/warning zones
                stops_raw = options.get('range_colors', [])
                if stops_raw:
                    zones = []
                    for s in stops_raw:
                        parts = s.split(',')
                        if len(parts) >= 3:
                            zones.append({"from": float(parts[0]), "to": float(parts[1]), "color": parts[2]})
                    summary['visual_zones'] = zones

            # --- Graph Interpretation (Time-series) ---
            elif 'graph' in widget_type.lower() or 'AoT_graph' in widget_type:
                duration_val = options.get('x_axis_duration', 1)
                duration_unit = options.get('x_axis_duration_unit', 'day')
                
                # Calculate duration in seconds
                duration_sec = duration_val * 60
                if duration_unit == 'day': duration_sec *= 1440
                elif duration_unit == 'hour': duration_sec *= 60
                
                summary['type'] = 'graph'
                summary['visible_time_window'] = f"{duration_val} {duration_unit}"
                
                # Fetch statistical summary for THIS EXACT timeframe
                targets = options.get('measurements_input', [])
                if isinstance(targets, list) and targets:
                    stats_summary = {}
                    for t in targets[:3]: # Limit to first 3 to save tokens
                        try:
                            parts = t.split(',')
                            if len(parts) < 2: continue
                            dev_id, m_id = parts[0], parts[1]
                            
                            # Fetch data for the full visual duration
                            from aot.databases.models import DeviceMeasurements, Conversion
                            from aot.utils.system_pi import return_measurement_info
                            dm = DeviceMeasurements.query.filter_by(unique_id=m_id).first()
                            if dm:
                                conv = Conversion.query.filter_by(unique_id=dm.conversion_id).first()
                                channel, unit, measurement = return_measurement_info(dm, conv)
                                
                                data = read_influxdb_list(dev_id, unit, channel=channel, measure=measurement, duration_sec=duration_sec)
                                if data:
                                    vals = [d[1] for d in data if isinstance(d[1], (int, float))]
                                    if vals:
                                        stats_summary[f"{dev_id}_{unit}"] = {
                                            "avg": round(sum(vals)/len(vals), 2),
                                            "min": min(vals),
                                            "max": max(vals),
                                            "trend": "rising" if vals[-1] > vals[0] else "falling",
                                            "data_points": len(vals)
                                        }
                        except: pass
                    if stats_summary:
                        summary['visual_stats_summary'] = stats_summary

            return summary
        except Exception as e:
            return {"error": "Visual summary extraction failed"}
