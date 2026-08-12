# coding=utf-8
"""
Geo Domain Models.
Unifies MapConfig, MapOverlay, MapGlobalSettings, and GIS Inputs under the 'Geo' domain.
"""
from datetime import datetime
import json
from sqlalchemy import JSON
from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db


def _flatten_coords(coords):
    """GeoJSON coordinates (any nesting depth) → list of [lng, lat] pairs."""
    if not coords:
        return []
    if isinstance(coords[0], (int, float)):
        return [coords]
    result = []
    for item in coords:
        result.extend(_flatten_coords(item))
    return result


# ------------------------------------------------------------------------------
# GeoMap (Previously MapConfig)
# Represents a saved map view/instance.
# ------------------------------------------------------------------------------
class GeoMap(CRUDMixin, db.Model):
    """
    Represents a saved map view or instance in the Geo domain.

    GeoMap stores map provider settings, center/zoom state, API keys, and styling
    options. Devices can optionally own a map for dedicated display. Supports OSM
    and satellite tile providers.

    @phase active
    """
    __tablename__ = "geo_map"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name = db.Column(db.String(128), nullable=False, default='New Map')
    category = db.Column(db.String(64), nullable=True, index=True, default='design')
    sort_order = db.Column(db.Integer, default=0)

    # Center/zoom
    latitude = db.Column(db.Float, default=None)
    longitude = db.Column(db.Float, default=None)
    zoom = db.Column(db.Integer, default=12)
    is_device_owned = db.Column(db.Boolean, default=False)

    # Provider details
    provider = db.Column(db.String(32), default='osm')
    style_url = db.Column(db.Text, default='')
    api_key = db.Column(db.Text, default='')
    use_satellite = db.Column(db.Boolean, default=False)
    providers = db.Column(db.Text, default='{}')
    state_json = db.Column(db.Text, default='{}')

    # Interaction
    map_locked = db.Column(db.Boolean, default=False)

    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.String(36), default='')

    def __repr__(self):
        return "<GeoMap(id={0}, name='{1}')>".format(self.id, self.name)

    def state_dict(self):
        if not self.state_json:
            return {}
        try:
            value = json.loads(self.state_json)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def viewport(self):
        """Where this map's camera sits: (lat, lng, zoom), None for unknown.

        The live camera is saved into ``state_json`` ('center' as {lat, lng},
        'zoom' as a float) — the latitude/longitude columns predate that and no
        current write path fills them, so they are NULL on every real map. A
        reader that consults only the columns therefore sends every map to the
        same default coordinates and makes switching maps look like a no-op.
        Returning None rather than a default lets the caller decide (leave the
        camera alone, fit to the map's shapes) instead of teleporting to Seoul.
        """
        state = self.state_dict()
        center = state.get('center')
        lat = lng = None
        if isinstance(center, dict):
            lat, lng = center.get('lat'), center.get('lng')
        elif isinstance(center, (list, tuple)) and len(center) >= 2:
            lat, lng = center[0], center[1]
        if lat is None or lng is None:
            lat, lng = self.latitude, self.longitude
        zoom = state.get('zoom')
        if zoom is None:
            zoom = self.zoom
        return lat, lng, zoom

    def update_state(self, updates):
        if not updates:
            return False
        state = self.state_dict()
        changed = False
        for key, value in updates.items():
            if value is None:
                continue
            if state.get(key) == value:
                continue
            state[key] = value
            changed = True
        if changed:
            try:
                self.state_json = json.dumps(state, ensure_ascii=False)
            except Exception:
                self.state_json = json.dumps(state)
        return changed


# ------------------------------------------------------------------------------
# GeoSetting (Previously MapGlobalSettings)
# Global configurations for the Geo system.
# ------------------------------------------------------------------------------
class GeoSetting(CRUDMixin, db.Model):
    """
    Singleton global configuration record for the Geo mapping system.

    GeoSetting stores default provider credentials, zoom limits, tile animation
    preferences, default map center coordinates, and theme configuration for
    site/zone/facility/equipment colors.

    @phase active
    """
    __tablename__ = "geo_setting"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    providers = db.Column(db.Text, default='{}')
    keys = db.Column(db.Text, default='{}')
    zoom = db.Column(db.Float, default=12.0)
    max_zoom = db.Column(db.Integer, default=25)
    digital_zoom = db.Column(db.Boolean, default=True)
    smooth_zoom = db.Column(db.Boolean, default=True)

    default_lat = db.Column(db.Float, default=37.5665)
    default_lng = db.Column(db.Float, default=126.9780)
    tile_fade_animation = db.Column(db.Boolean, default=True)
    prefer_canvas = db.Column(db.Boolean, default=False)

    max_polygons_device = db.Column(db.Integer, default=1000)
    max_polygons_site = db.Column(db.Integer, default=1000)
    max_polygons_zone = db.Column(db.Integer, default=1000)

    equipment_cull_zoom = db.Column(db.Integer, default=15)

    # Unit preferences
    length_unit = db.Column(db.String(8), nullable=False, default='m')  # mm|cm|m|in|ft

    # Theme Configuration (JSON)
    # Stores colors for Site, Zone, Facility, Equipment, etc.
    theme_config = db.Column(db.Text, default='{}')

    def _loads(self, value):
        if not value:
            return {}
        try:
            return json.loads(value)
        except Exception:
            return {}

    def state_dict(self):
        return {
            'providers': self._loads(self.providers),
            'keys': self._loads(self.keys),
            'zoom': self.zoom,
            'max_zoom': self.max_zoom,
            'digital_zoom': self.digital_zoom,
            'smooth_zoom': self.smooth_zoom,
            'default_lat': self.default_lat,
            'default_lng': self.default_lng,
            'tile_fade_animation': self.tile_fade_animation,
            'prefer_canvas': self.prefer_canvas,
            'max_polygons_device': self.max_polygons_device,
            'max_polygons_site': self.max_polygons_site,
            'max_polygons_zone': self.max_polygons_zone,
            'equipment_cull_zoom': self.equipment_cull_zoom if self.equipment_cull_zoom is not None else 15,
            'length_unit': self.length_unit or 'm',
            'theme_config': self._loads(self.theme_config)
        }


# ------------------------------------------------------------------------------
# GeoShape (Previously MapOverlay)
# Represents a drawn shape or overlay on a GeoMap.
# ------------------------------------------------------------------------------
class GeoShape(CRUDMixin, db.Model):
    """
    Represents a GeoJSON shape drawn on a GeoMap.

    GeoShape stores a GeoJSON feature with optional metadata, linked to a GeoMap
    via geo_id. Shapes are hierarchical (site, zone, device, feature) and can
    be associated with physical devices or grouped into layers.

    @phase active
    """
    __tablename__ = "geo_shape"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    
    # Links to GeoMap (unified to 'geo_id' as per migration plan)
    geo_id = db.Column(db.String(64), nullable=False, index=True)
    
    device_id = db.Column(db.String(64), nullable=True, index=True)
    
    # Hierarchy
    type = db.Column(db.String(32), nullable=False, default='feature', index=True) # site, zone, feature
    channel_id = db.Column(db.String(64), nullable=True, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('geo_shape.id'), nullable=True, index=True)
    
    @property
    def level_id(self):
        mapping = {'site': 1, 'zone': 2, 'device': 3, 'feature': 3}
        return mapping.get(self.type, 3)
    
    layer_group = db.Column(db.String(64), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    
    # GeoJSON
    feature = db.Column(JSON, nullable=False)
    meta_json = db.Column(JSON, nullable=True)

    # Timezone (materialized) — this shape's effective IANA tz.
    # tz_source: 'explicit' (manual override / boundary choice — pinned, never
    # auto-overwritten) | 'inherited' (from parent site/zone) | 'coords' (own
    # centroid). tz_boundary: bbox corners resolve to >1 tz → needs an explicit
    # group tz choice. See docs/design/timezone-management.md §4·§8.
    timezone = db.Column(db.String(64), nullable=True, default=None)
    tz_source = db.Column(db.String(16), nullable=True, default=None)
    tz_boundary = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    map = db.relationship("GeoMap",
                          primaryjoin="foreign(GeoShape.geo_id) == GeoMap.unique_id",
                          backref=db.backref("shapes", cascade="all, delete-orphan"))

    def get_centroid(self):
        """Return (lat, lng) centroid of this shape's own GeoJSON geometry, or
        None if it has no geometry/coordinates. Own outline only — does NOT
        follow a linked GeoFacility (unlike resolve_timezone's priority chain).
        Shared by resolve_timezone() below and by
        aot.utils.device_tz.resolve_location_coords() (map previews etc.) —
        the centroid math used to be duplicated inline in both
        GeoShape.resolve_timezone and GeoFacility.resolve_timezone."""
        feat = self.feature or {}
        geom = feat.get('geometry') or {}
        coords = geom.get('coordinates')
        if not coords:
            return None
        try:
            flat = _flatten_coords(coords)
            if not flat:
                return None
            avg_lng = sum(c[0] for c in flat) / len(flat)
            avg_lat = sum(c[1] for c in flat) / len(flat)
            return (avg_lat, avg_lng)
        except Exception:
            return None

    def resolve_timezone(self, _seen=None):
        """Return pytz timezone for this shape's effective location tz.

        Inheritance chain (docs/design/timezone-management.md §4):
          1. self.timezone (materialized — explicit override or cached
             inherited/coords value). This is the O(1) fast path.
          2. Parent shape (parent_id chain) → its resolve_timezone().
             A device/zone with no tz of its own inherits its site's tz, so
             the whole operational group shares one clock (§8).
          3. Linked GeoFacility's resolve_timezone() (explicit override / centroid).
          4. This shape's own centroid → timezonefinder lookup.
          5. None (caller handles fallback, e.g. Misc.timezone/UTC).

        `_seen` guards against parent_id cycles.
        """
        import pytz

        # 1. materialized value on this shape
        if self.timezone:
            try:
                return pytz.timezone(self.timezone)
            except Exception:
                pass

        # 2. inherit from parent (cycle-guarded)
        seen = _seen or set()
        if self.id is not None:
            seen.add(self.id)
        parent = getattr(self, 'parent_id', None)
        if parent is not None and parent not in seen:
            try:
                parent_shape = GeoShape.query.get(parent)
                if parent_shape is not None:
                    tz = parent_shape.resolve_timezone(_seen=seen)
                    if tz is not None:
                        return tz
            except Exception:
                pass

        # 3. linked facility
        facility = getattr(self, 'facility', None)
        if facility is not None:
            tz = facility.resolve_timezone()
            if tz is not None:
                return tz

        # 4. own centroid
        from aot.utils.device_tz import resolve_tz_from_coords
        centroid = self.get_centroid()
        if centroid:
            try:
                avg_lat, avg_lng = centroid
                tz_name = resolve_tz_from_coords(avg_lat, avg_lng)
                if tz_name:
                    return pytz.timezone(tz_name)
            except Exception:
                pass
        return None

    def compute_effective_tz(self):
        """Recompute this shape's tz from inheritance, IGNORING self.timezone
        cache — used by materialization (docs/design/timezone-management.md §4).

        Priority: parent (parent_id chain) → linked facility → own centroid.
        Parent-inherit wins over own centroid so an operational group shares one
        clock (§8). Returns (tz_name or None, source) — source ∈
        {'inherited','coords'}.
        """
        # 1. inherit from parent
        parent = getattr(self, 'parent_id', None)
        if parent is not None:
            try:
                p = GeoShape.query.get(parent)
                if p is not None and p.id != self.id:
                    ptz = p.resolve_timezone()
                    if ptz is not None:
                        return str(ptz), 'inherited'
            except Exception:
                pass
        # 2. linked facility
        facility = getattr(self, 'facility', None)
        if facility is not None:
            try:
                ftz = facility.resolve_timezone()
                if ftz is not None:
                    return str(ftz), 'inherited'
            except Exception:
                pass
        # 3. own centroid
        from aot.utils.device_tz import resolve_tz_from_coords
        centroid = self.get_centroid()
        if centroid:
            tz_name = resolve_tz_from_coords(centroid[0], centroid[1])
            if tz_name:
                return tz_name, 'coords'
        return None, None

    def detect_tz_boundary(self):
        """Return True if this shape's geometry spans >1 IANA timezone — its
        bbox corners resolve to different tz (docs/design/timezone-management.md
        §8). Used to flag groups straddling a legal-tz/date-line boundary so the
        UI can force a single explicit group tz instead of silently splitting.
        """
        feat = self.feature or {}
        coords = (feat.get('geometry') or {}).get('coordinates')
        if not coords:
            return False
        flat = _flatten_coords(coords)
        if not flat or len(flat) < 2:
            return False
        lats = [c[1] for c in flat]
        lngs = [c[0] for c in flat]
        corners = [
            (min(lats), min(lngs)), (min(lats), max(lngs)),
            (max(lats), min(lngs)), (max(lats), max(lngs)),
        ]
        from aot.utils.device_tz import resolve_tz_from_coords
        names = set()
        for la, ln in corners:
            t = resolve_tz_from_coords(la, ln)
            if t:
                names.add(t)
        return len(names) > 1

    def __repr__(self):
        return "<GeoShape(id={0}, type='{1}', geo_id='{2}')>".format(self.id, self.type, self.geo_id)


# ------------------------------------------------------------------------------
# GeoLayer (Previously GIS Input)
# External GIS data sources (Tiles, WMS, etc.)
# ------------------------------------------------------------------------------
class GeoLayer(CRUDMixin, db.Model):
    """
    Represents an external GIS layer (tile, WMS, OSM) overlaid on a GeoMap.

    GeoLayer stores provider type (e.g., gis_osm, gis_esri) and JSON options
    containing URLs, API keys, or styling configuration for external mapping services.

    @phase active
    """
    __tablename__ = "geo_layer"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    
    name = db.Column(db.String(128), nullable=False, default='New Layer')
    is_activated = db.Column(db.Boolean, default=True)
    
    # 'device' in Input -> 'type' or 'source_type' here.
    # To keep consistent with other models using 'type', let's use 'type'.
    # e.g. 'gis_osm', 'gis_esri'
    type = db.Column(db.String(64), nullable=False, default='gis_osm')
    
    # Custom options (JSON string for URLs, keys, etc.)
    options = db.Column(db.Text, default='{}')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def position_y(self):
        try:
             opts = json.loads(self.options) if self.options else {}
             return opts.get('position_y', 0)
        except:
             return 0

    def __repr__(self):
        return "<GeoLayer(id={0}, name='{1}')>".format(self.id, self.name)


# ------------------------------------------------------------------------------
# GeoFacility
# Building-level facility metadata linked to GeoShape (type='facility').
# ------------------------------------------------------------------------------
class GeoFacility(CRUDMixin, db.Model):
    """
    Building-level facility metadata linked to a GeoShape outer polygon.

    Stores parametric building specs (geometry, envelope, actuators), bay
    breakdown for connected greenhouses, and a cached capacity computation
    (heating/cooling/ventilation reference values, ±5~10%).

    @phase active
    """
    __tablename__ = "geo_facility"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    # Linkage
    shape_uuid = db.Column(db.String(36), nullable=False, index=True)  # → GeoShape.unique_id
    geo_id = db.Column(db.String(64), nullable=False, index=True)      # → GeoMap.unique_id

    # Identity
    name = db.Column(db.String(128), nullable=False, default='New Facility')
    preset = db.Column(db.String(64), default='standard_arch')
    structure = db.Column(db.String(32), default='single')   # single | connected
    bay_count = db.Column(db.Integer, default=1)

    # JSON specs
    geometry_3d = db.Column(JSON, nullable=True)
    envelope = db.Column(JSON, nullable=True)
    actuators = db.Column(JSON, nullable=True)
    bays = db.Column(JSON, nullable=True)
    computed = db.Column(JSON, nullable=True)

    # Fittings registry — per-fitting placements in 3D (windows, doors, fans,
    # heaters, sensors, fixtures). Each entry carries position, size,
    # surface_normal, link_group, and one of {actuator_id (Output uuid) for
    # actuating kinds, input_id (Input uuid) for sensors}.
    # G1 policy: when fittings exist, they are the authoritative source of
    # vent opening area and orientation (not envelope.side_vent.stages).
    fittings = db.Column(JSON, nullable=True)

    # View options — UI 표시 옵션 (현재는 3D 미리보기 카테고리 가시성).
    # AoT_map 위젯에서도 같은 값을 읽어 시설 렌더 시 동일한 카테고리 토글을 적용.
    # Schema: { category_visibility: { envelope, opening, climate, sensor, fixture, irrig } }
    view_options = db.Column(JSON, nullable=True)

    # Sensor registry — list of sensor bindings for this facility.
    # Schema: [{role, device_id, measurement_id, name, weight}]
    # role: 'indoor_temp' | 'indoor_humidity' | 'indoor_co2'
    #       'outdoor_temp' | 'outdoor_humidity' | 'outdoor_wind' | 'outdoor_wind_dir' | 'outdoor_solar'
    # Multiple entries per role → weighted-average aggregation in runtime endpoint.
    sensors = db.Column(JSON, nullable=True)

    # Weather / forecast bindings — user-configured connections to forecast Input devices.
    # Any service (OpenWeatherMap, Open-Meteo, KMA, ...) that has an Input plugin
    # and writes to InfluxDB can be connected here.
    # Schema: [{measurement_type, input_uuid, measurement_id, name, max_age_sec?}]
    # measurement_type: 'forecast_temperature' | 'forecast_humidity' |
    #   'forecast_wind_speed' | 'forecast_precipitation_prob' |
    #   'forecast_precipitation' | 'forecast_solar'
    # max_age_sec (optional): 소스별 유효 수명. 생략 시 시스템 기본값(7200s) 적용.
    #   실측 기상 장치(AWS): 300~900, 예보 서비스(KMA/OpenMeteo): 3600~10800
    weather_bindings = db.Column(JSON, nullable=True)

    sort_order = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, default='')

    # 대표사진 — uploads/facility_photos 하위 상대경로 (맵 팝업 [현황] 탭 표시)
    photo_path = db.Column(db.String(255), nullable=True, default=None)

    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.String(36), default='')

    # Timezone (IANA string, e.g. 'Asia/Seoul'). Auto-derived from GeoShape centroid
    # via timezonefinder when None. Set explicitly to override auto-detection.
    timezone = db.Column(db.String(64), nullable=True, default=None)
    tz_source = db.Column(db.String(16), nullable=True, default=None)  # explicit | inherited | coords

    # 3D asset override (render_mode='asset' → parametric builder skipped)
    model_asset_uuid = db.Column(db.String(36), nullable=True, index=True)
    model_transform = db.Column(JSON, nullable=True)   # {position:[x,y,z], rotation:[rx,ry,rz], scale:[sx,sy,sz]}
    render_mode = db.Column(db.String(16), nullable=False, default='parametric')  # 'parametric' | 'asset'

    # Commissioning diagnostic state — stores per-actuator flags and calibration
    # anchors written by the device check wizard (routes_geo api_commissioning_*).
    # Schema: {
    #   commissioning_flags: {actuator_id: 'sensor_suspect' | 'device_fault'},
    #   k_upper_bounds:      {actuator_id: {var, ratio}},
    #   device_alarms:       [{actuator_id, message, ts}, ...],
    #   calibration_anchors: [{actuator_id, var, k_measured, ts}, ...],
    # }
    commissioning_state = db.Column(JSON, nullable=True)

    # Actuator group definitions — multi-stage / stacked curtains, windward pairs, etc.
    # Schema: {
    #   group_id: {
    #     mode:          'symmetric' | 'stacked' | 'multi_stage' | 'windward_diff',
    #     leader:        slot_key (리더 슬롯),
    #     members:       [slot_key, ...] (리더 포함 전체 멤버),
    #     threshold_pct: float (stacked 모드 전환 임계 %, 기본 50),
    #   }, ...
    # }
    groups = db.Column(JSON, nullable=True)

    # Relationship
    shape = db.relationship(
        "GeoShape",
        primaryjoin="foreign(GeoFacility.shape_uuid) == GeoShape.unique_id",
        backref=db.backref("facility", uselist=False)
    )

    def resolve_timezone(self):
        """Return pytz/zoneinfo timezone object for this facility.

        Priority:
          1. self.timezone (explicit IANA string)
          2. centroid of linked GeoShape → timezonefinder lookup
          3. None (caller must handle UTC fallback)
        """
        import pytz
        from aot.utils.device_tz import resolve_tz_from_coords

        tz_name = self.timezone
        if not tz_name and self.shape is not None:
            centroid = self.shape.get_centroid()
            if centroid:
                try:
                    avg_lat, avg_lng = centroid
                    tz_name = resolve_tz_from_coords(avg_lat, avg_lng)
                except Exception:
                    pass

        if tz_name:
            try:
                return pytz.timezone(tz_name)
            except Exception:
                pass
        return None

    def compute_geo_helpers(self):
        """GeoShape 폴리곤으로부터 azimuth_deg·area_m2를 계산해 geometry_3d에 캐시한다.

        Returns dict {'azimuth_deg': float, 'area_m2': float} or {}.
        좌표가 없거나 계산 불가 시 빈 dict 반환.

        azimuth_deg: 최소 외접 사각형(MBR)의 장축 방위각 (북쪽 기준, 시계 방향, 0~180°).
        area_m2: Shoelace + 위도 보정으로 근사한 포지션 면적(㎡).
        """
        import math

        if self.shape is None:
            return {}

        feat = self.shape.feature or {}
        geom = feat.get('geometry') or {}
        coords_raw = geom.get('coordinates')
        if not coords_raw:
            return {}

        pts = _flatten_coords(coords_raw)
        if len(pts) < 3:
            return {}

        # ── 위도 보정 계수 ──────────────────────────────────────────────
        lats = [p[1] for p in pts]
        lngs = [p[0] for p in pts]
        lat_c = sum(lats) / len(lats)
        lng_c = sum(lngs) / len(lngs)

        # 1° 위도 ≈ 111_320 m, 1° 경도 ≈ 111_320 × cos(lat) m
        _M_PER_DEG_LAT = 111_320.0
        cos_lat = math.cos(math.radians(lat_c))
        _M_PER_DEG_LNG = _M_PER_DEG_LAT * cos_lat

        # lng/lat → 로컬 평면 좌표 (m)
        def _to_xy(p):
            return ((p[0] - lng_c) * _M_PER_DEG_LNG,
                    (p[1] - lat_c) * _M_PER_DEG_LAT)

        xy = [_to_xy(p) for p in pts]

        # ── Shoelace 면적 ───────────────────────────────────────────────
        n = len(xy)
        area_2 = 0.0
        for i in range(n):
            j = (i + 1) % n
            area_2 += xy[i][0] * xy[j][1]
            area_2 -= xy[j][0] * xy[i][1]
        area_m2 = abs(area_2) / 2.0

        # ── 최소 외접 사각형(rotating calipers, convex hull 생략판) ─────
        # 단순화: 엣지 방향별 회전 후 bbox 면적 최소화
        def _convex_hull_2d(points):
            pts_s = sorted(set(points))
            if len(pts_s) < 3:
                return pts_s
            lower, upper = [], []
            for p in pts_s:
                while len(lower) >= 2 and (
                    (lower[-1][0] - lower[-2][0]) * (p[1] - lower[-2][1]) -
                    (lower[-1][1] - lower[-2][1]) * (p[0] - lower[-2][0]) <= 0
                ):
                    lower.pop()
                lower.append(p)
            for p in reversed(pts_s):
                while len(upper) >= 2 and (
                    (upper[-1][0] - upper[-2][0]) * (p[1] - upper[-2][1]) -
                    (upper[-1][1] - upper[-2][1]) * (p[0] - upper[-2][0]) <= 0
                ):
                    upper.pop()
                upper.append(p)
            return lower[:-1] + upper[:-1]

        hull = _convex_hull_2d(xy)
        if len(hull) < 2:
            azimuth_deg = 0.0
        else:
            best_angle = 0.0
            best_w, best_h = 1.0, 1.0
            min_box_area = float('inf')
            hn = len(hull)
            for i in range(hn):
                j = (i + 1) % hn
                dx, dy = hull[j][0] - hull[i][0], hull[j][1] - hull[i][1]
                edge_angle = math.atan2(dy, dx)
                ca, sa = math.cos(-edge_angle), math.sin(-edge_angle)
                rxs = [ca * p[0] - sa * p[1] for p in hull]
                rys = [sa * p[0] + ca * p[1] for p in hull]
                w = max(rxs) - min(rxs)
                h = max(rys) - min(rys)
                if w * h < min_box_area:
                    min_box_area = w * h
                    best_angle = edge_angle
                    best_w, best_h = w, h

            # best_w: 엣지 방향 길이, best_h: 수직 방향 길이
            # 장축 방향 = w >= h → 엣지 방향, w < h → 수직 방향
            if best_h > best_w:
                long_axis_angle = best_angle + math.pi / 2
            else:
                long_axis_angle = best_angle
            # math각(동=0,반시계) → compass 방위각(북=0,시계, 0~180°)
            azimuth_deg = (90.0 - math.degrees(long_axis_angle)) % 180.0

        result = {
            'azimuth_deg': round(azimuth_deg, 1),
            'area_m2':     round(area_m2, 1),
        }

        # geometry_3d에 캐시
        try:
            g3d = dict(self.geometry_3d or {})
            g3d.update(result)
            self.geometry_3d = g3d
        except Exception:
            pass

        return result

    def __repr__(self):
        return "<GeoFacility(id={0}, name='{1}', shape_uuid='{2}')>".format(
            self.id, self.name, self.shape_uuid)


# ------------------------------------------------------------------------------
# GeoModelAsset
# User-registered 3D model assets (primitives, extruded polygons, imported GLTF).
# ------------------------------------------------------------------------------
class GeoModelAsset(CRUDMixin, db.Model):
    """
    User-registered 3D model asset for facility preview override.

    Supports three kinds:
      - 'primitive'        : parametric box/cylinder/sphere/cone/plane
      - 'extruded_polygon' : 2-D polygon + extrude height
      - 'imported_gltf'    : uploaded .glb / .gltf file

    All length values inside spec_json are stored in metres (SI).
    authored_unit records the unit the user used when creating the asset
    (reference only — conversions are done in the UI layer).

    @phase active
    """
    __tablename__ = "geo_model_asset"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    owner_user_id = db.Column(db.Integer, nullable=True, index=True)

    name = db.Column(db.String(128), nullable=False, default='New Asset')
    kind = db.Column(db.String(32), nullable=False, default='primitive')  # primitive|extruded_polygon|imported_gltf
    spec_json = db.Column(JSON, nullable=True)
    authored_unit = db.Column(db.String(8), nullable=False, default='m')  # mm|cm|m|in|ft
    tags = db.Column(db.Text, nullable=True)          # comma-separated

    # Thumbnail (server-side render)
    preview_png = db.Column(db.Text, nullable=True)   # relative path under static/
    preview_status = db.Column(db.String(16), nullable=False, default='pending')  # pending|ok|failed

    # Uploaded file (imported_gltf only)
    source_file = db.Column(db.Text, nullable=True)   # relative path under static/uploads/model_assets/

    sort_order = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, default='')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return "<GeoModelAsset(id={0}, kind='{1}', name='{2}')>".format(
            self.id, self.kind, self.name)
