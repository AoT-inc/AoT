# coding=utf-8
import json
import logging
from aot.aot_flask.extensions import db
from aot.aot_flask.geo.facility_sensors import channel_label_meta
from aot.aot_flask.utils import utils_geo
from aot.config import (
    MAP_API_KEY,
    MAP_DEFAULT_CENTER,
    MAP_DEFAULT_ZOOM,
    MAP_PROVIDER,
    MAP_STYLE_URL,
)
from aot.config.mcp_config import UI_MAP_ADVICE_PANEL
from aot.databases.models import (
    Conversion,
    Input,
    Output,
    Misc,
    DeviceMeasurements,
    CustomController,
    GeoMap,
    GeoSetting,
    GeoShape,
    Measurement,
    Unit,
    OutputChannel,
    Trigger,
    Conditional,
    PID,
    AIGlobalSettings,
)
from flask_babel import gettext

from sqlalchemy.orm import load_only
from sqlalchemy import or_

# from .options import extract_device_ids, extract_measurements # [Refactor] Moved to internal
from aot.utils.runtime import get_started_at, get_last_duration # [Runtime Service]
from aot.utils.influx import read_influxdb_single
from aot.utils.system_pi import return_measurement_info

# @ANCHOR: ai_advice_import
try:
    from aot.ai.services.ai_summary_service import AISummaryService as _AISummaryService
except Exception:
    _AISummaryService = None

logger = logging.getLogger(__name__)


def _measurement_display_name(measurement_key):
    """측정 키 → 사람이 읽는 이름. 모르는 키면 `None`(호출부가 폴백한다).

    정본은 `MEASUREMENTS`(`config_devices_units.py`) 하나다 — 화면마다 자기
    이름표를 들면 같은 값이 자리마다 다른 이름으로 보인다.

    ⚠ `MEASUREMENTS` 의 이름은 `lazy_gettext` 객체다. **참/거짓으로 평가하지
      말 것** — 그 순간 `__len__` → `str()` 이 불려 번역이 강제되고, 요청
      컨텍스트가 없으면 거기서 예외가 난다. `is None` 으로만 본다.
    """
    if not measurement_key:
        return None
    try:
        from aot.config_devices_units import MEASUREMENTS
        entry = MEASUREMENTS.get(str(measurement_key))
        if entry is None:
            return None
        name = entry.get('name')
        if name is None:
            return None
        return str(name) or None
    except Exception:
        # 이름을 못 얻는 것이 지도를 못 그릴 이유는 아니다 — 호출부가
        # 원문 키로 폴백한다.
        return None


# NOTE: Cross-request ORM caching of GeoMap caused DetachedInstanceError on
# tab duplication / dashboard re-render (instances became detached after the
# original request's session was torn down). The cache is intentionally
# disabled; GeoMap.query is cheap. Helpers are kept for API stability.
def _get_geomap_cached(uuid):
    if not uuid:
        return None
    return GeoMap.query.filter_by(unique_id=uuid).first()


def _get_latest_geomap_cached():
    return GeoMap.query.order_by(GeoMap.updated_at.desc()).first()


def invalidate_geomap_cache(uuid=None):
    return


def normalize_layer_name(name):
    """Normalize layer name for comparison (trim, lowercase, strip parentheticals, collapse spaces)"""
    if not name:
        return ""
    import re
    cleaned = re.sub(r'\s*\([^)]*\)', '', str(name))  # remove (...)
    cleaned = re.sub(r'\s+', ' ', cleaned)             # collapse multiple spaces
    return cleaned.strip().lower()


def _int_option(widget_options, key, fallback):
    """Read an integer custom_option defensively.

    Saved custom_options are NOT type-checked on every write path. The partial-save
    endpoint (`routes_dashboard.save_widget_custom_options`) hands its JSON straight
    to the widget's `execute_at_modification`, which blind-merges it — so a number
    field the user simply cleared arrives here as `''`. A bare `int('')` then raises
    ValueError while building widget_vars, and because that happens during page
    render **the whole dashboard returns 500** — worse, the error page carries no
    CSRF token, so the value cannot be corrected from that dashboard at all.

    Reproduced locally 2026-08-12: clearing 'Input Value Refresh Period' and pausing
    past the settings modal's 400ms autosave debounce persisted `''` and bricked the
    dashboard. `period` above already had this try/except for the same reason; every
    integer option reachable from the form needs it, not just that one.
    """
    if not widget_options:
        return fallback
    try:
        return int(widget_options.get(key, fallback))
    except (TypeError, ValueError):
        logger.warning(
            "[AoT Map] custom_option '%s' 값이 정수가 아니어서 기본값 %s 로 대체: %r",
            key, fallback, widget_options.get(key))
        return fallback


def extract_device_ids(widget_options: dict) -> list:
    """Robustly extract device IDs from saved option keys.

    [Behavior] These are the Device Filter's EXCLUDE list — devices the user
    picked here are hidden from the map; everything else placed on the map
    still shows (see utils_geo.collect_devices docstring). Empty = show all.

    Source of truth: the three user-facing selection multi-selects
    (`device_selection_input/output/function`). The merged `device_ids` /
    `custom_option_device_ids` keys are derived caches written by
    `execute_at_modification` and can drift stale when the user clears one of
    the three lists (the form omits empty multi-selects, triggering the
    presave fallback). Trusting the explicit per-type lists prevents stale
    entries from leaking into map rendering.
    """
    if not widget_options:
        return []
    ids = []
    selection_keys = [
        'device_selection_input',
        'device_selection_output',
        'device_selection_function',
    ]
    has_selection_key = any(k in widget_options for k in selection_keys)
    keys = selection_keys if has_selection_key else [
        'custom_option_device_ids',
        'device_ids',
    ]
    for key in keys:
        raw = widget_options.get(key)
        if not raw:
            continue
        if isinstance(raw, str):
            parts = [p.strip() for p in raw.split(',') if p.strip()]
            ids.extend(parts)
        elif isinstance(raw, list):
            for entry in raw:
                try:
                    val = str(entry).strip()
                    if val:
                        val = val.split(',')[0].strip()
                        if val:
                            ids.append(val)
                except Exception:
                    continue
    # deduplicate preserving order
    return list(dict.fromkeys(ids))


def extract_measurements(widget_options: dict) -> dict:
    """
    Extract selected measurements from options.
    Returns: { device_id: [{'measurement_id': ..., 'channel': ...}, ...] }
    """
    if not widget_options:
        return {}, False

    measurements_config = {}
    measurements_map_has_any_selection = False
    
    # Keys for multi-select measurement options
    keys = [
        ('measurements_input', 'input'),
        ('measurements_function', 'function'),
        ('measurements_output', 'output'),
    ]

    for key, dev_type in keys:
        raw_val = widget_options.get(f"custom_option_{key}") or widget_options.get(key)
        if raw_val:
            logger.info(f"[AoT Map Opt TRACE] key={key} raw_val={raw_val} (type={type(raw_val)})")
        if not raw_val:
            continue
            
        items = []
        if isinstance(raw_val, str):
            items = [s.strip() for s in raw_val.split(',') if s.strip()]
        elif isinstance(raw_val, list):
            items = raw_val
            
        if items:
            measurements_map_has_any_selection = True
            
        for entry in items:
            # Format: "device_id::measurement_id" or "device_id,measurement_id"
            if not isinstance(entry, str):
                continue
                
            d_id, m_id = None, None
            if '::' in entry:
                parts = entry.split('::', 1)
                if len(parts) == 2:
                    d_id, m_id = parts[0].strip(), parts[1].strip()
            elif ',' in entry:
                parts = entry.split(',', 1)
                if len(parts) == 2:
                    d_id, m_id = parts[0].strip(), parts[1].strip()
            
            if not d_id or not m_id:
                continue

            if d_id not in measurements_config:
                measurements_config[d_id] = []
                
            measurements_config[d_id].append({
                'measurement_id': m_id,
                'device_type': dev_type
            })

    return measurements_config, measurements_map_has_any_selection



def generate_page_variables_logic(widget_unique_id, widget_options):
    """
    Prepare variables for template rendering using modular logic.
    """
    legacy_device_ids = extract_device_ids(widget_options or {})
    measurements_config, measurements_map_has_any_selection = extract_measurements(widget_options or {})
    
    # [Guaranteed Log] Trace widget options
    logger.debug(f"\n[AoT Map TRACE] widget_unique_id: {widget_unique_id}")
    logger.debug(f"[AoT Map TRACE] widget_options: {widget_options}")
    logger.debug(f"[AoT Map TRACE] measurements_config: {measurements_config}\n")
    
    measurements_map = {}
    measurement_device_ids = []

    if measurements_config:
        all_meas_ids = []
        for dev_id, meas_list in measurements_config.items():
            for m in meas_list:
                all_meas_ids.append(m['measurement_id'])
        
        if all_meas_ids:
            meas_query = DeviceMeasurements.query.filter(
                DeviceMeasurements.unique_id.in_(all_meas_ids)
            ).options(load_only(
                DeviceMeasurements.unique_id,
                DeviceMeasurements.name,
                DeviceMeasurements.measurement,
                DeviceMeasurements.measurement_type,
                DeviceMeasurements.channel,
                DeviceMeasurements.unit,
                DeviceMeasurements.rescaled_unit,
                DeviceMeasurements.rescaled_measurement,
                DeviceMeasurements.conversion_id
            )).all()
            
            meas_lookup = {m.unique_id: m for m in meas_query}

            # conversion_id → convert_unit_to 일괄 조회 (변환 단위 우선)
            conv_ids = {m.conversion_id for m in meas_lookup.values() if m.conversion_id}
            conv_unit_lookup = {}
            if conv_ids:
                from aot.utils.database import db_retrieve_table_daemon
                convs = db_retrieve_table_daemon(Conversion).filter(
                    Conversion.unique_id.in_(conv_ids)
                ).all()
                conv_unit_lookup = {c.unique_id: (c.convert_unit_to or '') for c in convs}

            # [New] Fetch Device Names for Measurements Panel
            dev_name_lookup = {}
            # Group By Type
            ids_by_type = {'input': [], 'output': [], 'function': []}
            for dev_id, meas_list in measurements_config.items():
                if not meas_list: continue
                # Assume first item type is representative or check all? Usually same device.
                dt = meas_list[0].get('device_type', 'input')
                if dt == 'output': ids_by_type['output'].append(dev_id)
                elif dt == 'input': ids_by_type['input'].append(dev_id)
                else: ids_by_type['function'].append(dev_id) # catch-all for func/pid/etc

            if ids_by_type['input']:
                for r in Input.query.filter(Input.unique_id.in_(ids_by_type['input'])).options(load_only(Input.unique_id, Input.name)).all():
                    dev_name_lookup[r.unique_id] = r.name
            if ids_by_type['output']:
                for r in Output.query.filter(Output.unique_id.in_(ids_by_type['output'])).options(load_only(Output.unique_id, Output.name)).all():
                    dev_name_lookup[r.unique_id] = r.name
            if ids_by_type['function']:
                 # Check each table? Or just CustomController? Functions include PID, etc.
                 # Simplified: Try CustomController, PID, Trigger
                 # If needed, we can expand. For now, try common ones.
                 for Model in [CustomController, PID, Trigger, Conditional]:
                     for r in Model.query.filter(Model.unique_id.in_(ids_by_type['function'])).options(load_only(Model.unique_id, Model.name)).all():
                         dev_name_lookup[r.unique_id] = r.name

            for dev_id, meas_list in measurements_config.items():
                measurements_map[dev_id] = []
                for m_conf in meas_list:
                    m_id = m_conf['measurement_id']
                    if m_id in meas_lookup:
                        meas = meas_lookup[m_id]
                        chan = meas.channel if meas.channel is not None else 0
                        raw_name = (meas.name or meas.measurement or '')
                        # 표시명은 **측정 정의(`MEASUREMENTS`)를 정본으로** 쓴다.
                        #
                        # 예전에는 사용자가 채널 이름을 안 지었을 때 원문 키를
                        # 그대로 내보냈다(`vapor_pressure_deficit`). 그래서
                        # 클라이언트(`aot-map-custom-controls.js`)가 철자
                        # 5가지를 'VPD' 로 되돌리는 정규화를 자기 안에 들고
                        # 있었는데, 그것은 같은 판정의 **두 번째 사본**이라
                        # 정의를 고쳐도 지도만 안 따라오는 상태가 된다.
                        #
                        # ⚠ `raw_name` 은 그대로 둔다 — 아래 `channel_label_meta`
                        #   가 밴드 key 를 뽑는 근거이고, 그 자리에는 번역되지
                        #   않는 원문이 필요하다(바로 아래 주석 참조).
                        display_name = meas.name or _measurement_display_name(
                            meas.measurement) or raw_name
                        eff_unit = (conv_unit_lookup.get(meas.conversion_id)
                                    if meas.conversion_id else None) \
                            or meas.rescaled_unit or meas.unit or ''
                        # 시설 fitting 센서와 동일한 밴드 key / 표시 단위 규칙
                        # (facility_sensors.channel_label_meta 가 정본).
                        # 표시명은 번역되므로 key 대용으로 쓸 수 없다.
                        band_key, disp_unit = channel_label_meta(
                            meas.measurement_type, raw_name, eff_unit,
                            meas.measurement or '')

                        measurements_map[dev_id].append({
                            'id': m_id,
                            'device_unique_id': dev_id,
                            'channel': chan,
                            'name': f"[CH{chan}] {gettext(display_name)}".strip(),
                            'meas_name': gettext(display_name),
                            'measurement_type': meas.measurement_type,
                            'key': band_key,
                            'device_type': m_conf['device_type'],
                            'device_name': gettext(dev_name_lookup.get(dev_id) or ''),
                            'unit': eff_unit,
                            'display_unit': disp_unit,
                            'last_value': getattr(meas, 'last_value', '')
                        })
                        measurement_device_ids.append(f"{dev_id}::{chan}")

    # NOTE: Initial InfluxDB last-value prefetch removed to avoid N+1 sync HTTP calls
    # during page render (caused slow widget load). The client-side widget JS polls
    # live values after mount, so last_value starts empty and is filled shortly after.

    # Device Filter is an EXCLUDE list (see utils_geo.collect_devices
    # docstring): every device placed on the map is always fetched, and
    # legacy_device_ids — the selected ones — are dropped from the result.
    # `include_all_devices` no longer gates the fetch; it is kept only so the
    # value round-trips through widget_vars for older client code that still
    # reads it (harmless — collect_devices ignores it now). The measurement
    # panel's own selection (measurement_device_ids) is unrelated to this and
    # is no longer used as an inclusion fallback here.
    include_all = widget_options.get('include_all_devices')
    include_all = (include_all is None) or (include_all == "true" or include_all == "True" or include_all is True)
    final_fetch_ids = legacy_device_ids if legacy_device_ids else None

    logger.debug(f"[AoT Map Logic] widget: {widget_unique_id} exclude_ids: {len(legacy_device_ids)} meas_ids: {len(measurement_device_ids)}")
    
    layer_mode = widget_options.get('layer_mode', 'default') if widget_options else 'default'
    fallback_lat = widget_options.get('fallback_latitude', None) if widget_options else None
    fallback_lng = widget_options.get('fallback_longitude', None) if widget_options else None
    w_zoom = widget_options.get('default_zoom') if widget_options else None
    if w_zoom == '': w_zoom = None # [Fix] Treat empty string as None for fallback
    w_pitch   = widget_options.get('default_pitch')   if widget_options else None
    w_bearing = widget_options.get('default_bearing') if widget_options else None
    raw_map_uuid = (widget_options.get('map_uuid') or widget_options.get('custom_option_map_uuid')) if widget_options else None
    selected_map_uuid = str(raw_map_uuid).strip() if raw_map_uuid else None

    logger.debug(f"[AoT Map Logic] widget: {widget_unique_id} map_uuid: {selected_map_uuid} include_all: {include_all}")
    
    period_seconds = widget_options.get('period', 5) if widget_options else 5
    map_locked = bool(widget_options.get('map_locked', False)) if widget_options else False
    hide_controls = bool(widget_options.get('hide_controls', False)) if widget_options else False
    show_drawn_shapes = bool(widget_options.get('show_drawn_shapes', False)) if widget_options else False
    selected_map = None
    if selected_map_uuid:
        selected_map = _get_geomap_cached(selected_map_uuid)

    if w_zoom is not None and str(w_zoom).strip() != '':
        try:
             default_zoom = float(w_zoom)
        except:
             default_zoom = MAP_DEFAULT_ZOOM
    elif selected_map and selected_map.zoom is not None:
         default_zoom = selected_map.zoom
    else:
         default_zoom = MAP_DEFAULT_ZOOM

    try:
        period_seconds = int(period_seconds)
    except Exception:
        period_seconds = 5
    
    misc = utils_geo.get_misc_cached()
    
    device_shape_opacity = widget_options.get('device_shape_opacity', 50) if widget_options else 50
    
    def to_bool(val, default):
        if val is None: return default
        if isinstance(val, bool): return val
        if isinstance(val, str):
            return val.lower() in ('true', '1', 't', 'y', 'yes')
        return bool(val)

    # device_shape_color = widget_options.get('device_shape_color', '#007bff') if widget_options else '#007bff'
    enable_label_collision = to_bool(widget_options.get('enable_label_collision'), True) if widget_options else True
    label_position = widget_options.get('label_position', 'bottom') if widget_options else 'bottom'
    label_spacing = _int_option(widget_options, 'label_spacing', 0)
    # Master label switch. Drives every category render gate (site / zone / device /
    # sensor); per-device-type granularity lives in the runtime map controller.
    # Legacy widgets predate 'show_labels' — derive the master from the old per-category
    # toggles so their existing visibility is preserved on first load.
    _master_raw = widget_options.get('show_labels') if widget_options else None
    if _master_raw is None and widget_options:
        show_labels = (
            to_bool(widget_options.get('show_site_label'), False)
            or to_bool(widget_options.get('show_zone_label'), False)
            or to_bool(widget_options.get('show_device_labels'), False)
            or to_bool(widget_options.get('show_sensor_labels'), False)
        )
    else:
        show_labels = to_bool(_master_raw, True)

    show_device_labels = show_labels
    show_device_shapes = to_bool(widget_options.get('show_device_shapes'), False) if widget_options else False
    show_site_label = show_labels
    show_zone_label = show_labels
    show_site_shape = to_bool(widget_options.get('show_site_shape'), False) if widget_options else False
    show_zone_shape = to_bool(widget_options.get('show_zone_shape'), False) if widget_options else False
    show_facility_shape = to_bool(widget_options.get('show_facility_shape'), False) if widget_options else False
    show_equipment_shape = to_bool(widget_options.get('show_equipment_shape'), False) if widget_options else False
    global_label_size = widget_options.get('global_label_size', '1.0') if widget_options else '1.0'
    label_priority_facility = to_bool(widget_options.get('label_priority_facility'), False) if widget_options else False
    # 라벨 숨김 기준 줌. 0 = 숨기지 않음. 빈 문자열/None/비수치는 기본 16 으로.
    try:
        label_min_zoom = int(float(widget_options.get('label_min_zoom', 16))) if widget_options else 16
    except (TypeError, ValueError):
        label_min_zoom = 16
    label_min_zoom = max(0, min(22, label_min_zoom))
    overlay_data_only = to_bool(widget_options.get('overlay_data_only'), False) if widget_options else False

    try:
        device_shape_opacity = int(device_shape_opacity)
        if device_shape_opacity < 0: device_shape_opacity = 0
        if device_shape_opacity > 100: device_shape_opacity = 100
    except Exception:
        device_shape_opacity = 50
    
    map_list = []
    config_map = selected_map
    if not config_map:
        config_map = _get_latest_geomap_cached()
    
    if not selected_map_uuid and config_map:
        selected_map_uuid = config_map.unique_id

    sites_in_map = []
    map_provider_val = MAP_PROVIDER
    map_style_url_val = MAP_STYLE_URL
    map_api_key_val = MAP_API_KEY
    map_use_satellite = False
    
    if config_map:
        if config_map.provider:
            map_provider_val = config_map.provider
        if config_map.style_url:
            map_style_url_val = config_map.style_url
        if config_map.api_key:
            map_api_key_val = config_map.api_key
        if config_map.use_satellite:
            map_use_satellite = True

    saved_layer = widget_options.get('selected_base_layer') or widget_options.get('layer')
    if saved_layer:
        map_provider_val = saved_layer

    # [Fix] Per-widget Vector Style URL custom_option overrides global/map-level style.
    # Without this, widget_vars['map_style_url'] = global value would shadow the user's
    # input (the JS reads wOpts.map_style_url as the authoritative base style).
    _opt_style_url = (widget_options.get('map_style_url') or '').strip() if widget_options else ''
    if _opt_style_url:
        map_style_url_val = _opt_style_url

    common_center = None
    if fallback_lat is not None and fallback_lng is not None:
        try:
            common_center = (float(fallback_lat), float(fallback_lng))
        except Exception:
            pass

    if common_center is None and selected_map:
        if selected_map.latitude is not None and selected_map.longitude is not None:
            common_center = (selected_map.latitude, selected_map.longitude)

    geo_setting = GeoSetting.query.first()
    if common_center is None and geo_setting and geo_setting.default_lat is not None and geo_setting.default_lng is not None:
        common_center = (geo_setting.default_lat, geo_setting.default_lng)

    if common_center is None and misc and misc.map_latitude is not None and misc.map_longitude is not None:
        common_center = (misc.map_latitude, misc.map_longitude)

    if layer_mode == 'default' and map_use_satellite and map_api_key_val:
        layer_mode = 'satellite'

    # [Optimization] Default to Async Loading (User Request to fix 1500ms lag)
    # If not explicitly set to False, default to True.
    async_opt = widget_options.get('async_devices') if widget_options else None
    if async_opt is not None:
        async_devices = bool(async_opt)
    else:
        async_devices = True # Default True

    # If user explicitly requests include_all, we treat it as async capable too,
    # but the primary switch is now async_devices.
    # However, if async_devices is False, we MUST load usage synchronously.
    
    devices = []
    
    if async_devices:
        # Skip synchronous loading
        pass
    else:
        # Load synchronously (Legacy behavior or small scale)
        # [Fix] Use final_fetch_ids (Priority: Manual > Measurement)
        # [Refactor] Device collection now relies on Theme/Individual Design (Decoupled)
        devices = utils_geo.collect_devices(final_fetch_ids, include_all, default_color=None, map_uuid=selected_map_uuid)
    
    data = {} # Empty for SSR
    # [Fix] Populate all configuration dropdown lists and measurements
    config_opts = utils_geo.get_available_config_options()
    available_inputs = config_opts.get('available_inputs', [])
    available_outputs = config_opts.get('available_outputs', [])
    available_functions = config_opts.get('available_functions', [])
    available_measurements_input = config_opts.get('available_measurements_input', [])
    available_measurements_output = config_opts.get('available_measurements_output', [])
    available_measurements_function = config_opts.get('available_measurements_function', [])
    available_maps = config_opts.get('available_maps', [])
    
    # [Fix] Populate Available Maps for SSR
    try:
        from sqlalchemy import or_
        # [P3] 모든 지도가 동등하다 — category 분기 폐기.
        maps = GeoMap.query.order_by(GeoMap.updated_at.desc()).all()
        available_maps = [{
            'id': m.unique_id,
            'name': m.name,
            'latitude': m.latitude,
            'longitude': m.longitude,
            'zoom': m.zoom
        } for m in maps]
    except Exception as e:
        logger.error(f"Error fetching variable maps for config: {e}")
        available_maps = []
    
    measurements_map_has_any_selection = bool(measurements_map)
    if not measurements_map_has_any_selection:
        measurements_map = {}

    if measurements_map:
        logger.debug(f"[AoT Map Debug] Final measurements_map size: {len(measurements_map)}")
        for dev_id in measurements_map:
            measurements_map[dev_id] = sorted(
                measurements_map[dev_id],
                key=lambda m: m.get('channel') if isinstance(m.get('channel'), (int, float)) else 999
            )
        measurements_map = {k: v for k, v in measurements_map.items() if v}

    selected_map_center = None
    selected_map_zoom = None
    if selected_map:
        if selected_map.latitude is not None and selected_map.longitude is not None:
            selected_map_center = [selected_map.latitude, selected_map.longitude]
        if selected_map.zoom is not None:
            selected_map_zoom = selected_map.zoom

    global_providers = {}
    global_keys = {}
    if geo_setting:
        try:
            global_providers = json.loads(geo_setting.providers) if geo_setting.providers else {}
            global_keys = json.loads(geo_setting.keys) if geo_setting.keys else {}
        except Exception:
            pass

    geo_config = utils_geo.get_geo_config()
    theme_config = geo_config.get('theme_config', {})
    if isinstance(theme_config, str):
        try:
            theme_config = json.loads(theme_config)
        except:
            theme_config = {}

    map_global_style = {}
    if config_map:
        if config_map.providers:
            try:
                map_specific_providers = json.loads(config_map.providers)
                if map_specific_providers:
                    global_providers = map_specific_providers
            except Exception:
                pass
        
        # 지도별 theme_config 병합은 제거했다(2026-08-05).
        #
        # geo/design 에서 색을 고르면 전역 GeoSetting.theme_config 로 저장되는
        # 동시에, 그 세션에서 만진 키만 담긴 부분 dict 가 GeoMap.state_json 에도
        # 함께 기록됐다. 여기서 그 부분 dict 를 전역 위에 덮어썼기 때문에, 그
        # 지도를 쓰는 위젯은 전역 색을 아무리 바꿔도 옛 색 그대로였다(예: 전역
        # output #04a19a 인데 '영양' 지도만 #0084ff). 화면마다 다른 색이 나오는
        # 주요 경로였고, 지도별 색을 의도적으로 쓰는 기능도 아니었다 — 부작용에
        # 가깝다. 색의 정본은 전역 theme_config 하나뿐이다.
        # 저장 쪽도 함께 끊었다(aot-geo-design-v3.js saveDesign),
        # 남아 있던 state_json 값은 aot/scripts/fix_geo_theme_drift.py 로 제거.
        state = config_map.state_dict()
        if state:
            if 'draw-fill-color' in state:
                map_global_style['fillColor'] = state['draw-fill-color']
            if 'draw-stroke-color' in state:
                map_global_style['color'] = state['draw-stroke-color']
            if 'draw-fill-off-color' in state:
                map_global_style['offColor'] = state['draw-fill-off-color']

            if 'draw-fill-off-color' in state:
                map_global_style['offColor'] = state['draw-fill-off-color']

    map_state_id_val = f"widget-{widget_unique_id}" 
    # Original func signature was (widget_unique_id, widget_options).
    # This func only takes widget_options?
    # Wait, in AoT_map.py, the wrapper calls generate_page_variables_logic(widget_options).
    # So I need to pass widget_unique_id to generate_page_variables_logic?
    # Or extract from options?
    # The original generate_page_variables had widget_unique_id as argument 1.
    # My simplified wrapper passed `generate_page_variables_logic(widget_options)`.
    # I should change wrapper to pass unique_id too or just assume it's lost.
    # It is used for map_state_id_val.
    
    geo_config['theme_config'] = theme_config

    saved_active_names = widget_options.get('active_layers')
    global_layers = geo_config.get('layers', [])
    
    # Create widget-specific copy of layers to prevent sharing
    import copy
    widget_layers = copy.deepcopy(global_layers)
    
    saved_names_list = []
    if saved_active_names is not None:
        if isinstance(saved_active_names, str):
            saved_names_list = [s.strip() for s in saved_active_names.split(',') if s.strip()]
        elif isinstance(saved_active_names, list):
            extracted = []
            for item in saved_active_names:
                if isinstance(item, str):
                    if item.strip():
                        extracted.append(item.strip())
                elif isinstance(item, dict):
                    name = item.get('name') or item.get('id') or ''
                    if name:
                        extracted.append(str(name).strip())
            saved_names_list = extracted
    
    saved_names_normalized = [normalize_layer_name(s) for s in saved_names_list]
    
    # Debug logging for layer matching
    logger.debug(f"[AoT Map Layer Debug] Widget {widget_unique_id}: saved_names={saved_names_list}")
    logger.debug(f"[AoT Map Layer Debug] Widget {widget_unique_id}: global_layer_names={[l.get('name') for l in widget_layers]}")

    active_layers = []
    selected_base = widget_options.get('selected_base_layer')
    
    for l in widget_layers:  # Changed from global_layers
        layer_copy = l.copy()
        layer_name = l.get('name')
        layer_name_normalized = normalize_layer_name(layer_name)
        
        is_base = (l.get('is_base') is True) or (l.get('role') == 'base')
        
        if is_base:
            if selected_base:
                layer_copy['visible'] = (normalize_layer_name(selected_base) == layer_name_normalized)
            else:
                layer_copy['visible'] = l.get('visible', l.get('is_active', l.get('is_default', False)))
        else:
            if saved_active_names is not None:
                layer_copy['visible'] = (layer_name_normalized in saved_names_normalized)
            else:
                # 새 위젯(active_layers 저장 이력 없음)은 오버레이를 항상 꺼진 채로
                # 시작한다. 예전에는 전역 GeoLayer 상태(관리자가 레이어 미리보기에서
                # 마지막으로 저장한 channel_visible_*/layer_visible 값)를 그대로
                # 상속해서, 관리자가 KMA 채널을 켠 채로 저장해두면 모든 신규 위젯에
                # KMA 오버레이가 자동으로 켜지는 버그가 있었다.
                layer_copy['visible'] = False
            
        active_layers.append(layer_copy)
    
    # Debug logging for matched layers
    logger.debug(f"[AoT Map Layer Debug] Widget {widget_unique_id}: matched_layers={[l.get('name') for l in active_layers if l.get('visible')]}")
    
    default_zoom = w_zoom
    
    if default_zoom is None and selected_map_zoom is not None:
        default_zoom = selected_map_zoom
    
    if default_zoom is None and geo_setting and geo_setting.zoom is not None:
        default_zoom = geo_setting.zoom

    if default_zoom is None and misc and misc.map_zoom is not None:
        default_zoom = misc.map_zoom
        
    if default_zoom is None:
        default_zoom = MAP_DEFAULT_ZOOM

    try:
        default_zoom = round(float(default_zoom), 2)
    except:
        default_zoom = MAP_DEFAULT_ZOOM

    label_position = widget_options.get('label_position', 'bottom') if widget_options else 'bottom'

    # [Fix] Fetch ALL measurements for devices on the map (for Popups)
    # Replaced inline logic with reusable function
    all_measurements_map = {}
    if not async_devices and devices:
        all_measurements_map = utils_geo.get_all_measurements_for_map(devices)

    # @ANCHOR: ai_advice_summary_fetch
    # Check global AI enablement and widget-level ai_advice_enabled setting
    # Rule: NO HARDCODING — all dimensions and offsets from mcp_config.UI_MAP_ADVICE_PANEL
    ai_advice_list = []

    # Check global AI setting — 1단계(ai_enabled) 뿐 아니라 2단계(ai_running)까지
    # 켜져 있어야 한다. 안 그러면 "AI 조언 숨김" 툴바 버튼이 2단계 꺼진 채로도
    # 나타나는데, 눌러 봐야 숨길 조언 자체가 없다(요약 생성 자체가 2단계에
    # 걸려 있다 — aot/ai/services/ai_scheduler_service.py).
    ai_globally_enabled = False
    try:
        from aot.ai.services import ai_runtime_state
        ai_settings = AIGlobalSettings.query.first()
        ai_globally_enabled = ai_runtime_state.ai_autonomy_enabled(ai_settings)
    except Exception:
        ai_globally_enabled = False

    # Check widget-level ai_advice_enabled (default: true if AI globally enabled)
    widget_ai_advice_enabled = widget_options.get('ai_advice_enabled', ai_globally_enabled) if widget_options else ai_globally_enabled
    # Normalize to boolean
    if isinstance(widget_ai_advice_enabled, str):
        widget_ai_advice_enabled = widget_ai_advice_enabled.lower() in ('true', '1', 't', 'yes')
    else:
        widget_ai_advice_enabled = bool(widget_ai_advice_enabled)
    # 위젯에 저장된 값은 "끄기"만 할 수 있어야 한다 — 전역 2단계가 꺼져 있는데
    # 위젯 옵션에 예전에 저장된 True 가 남아 있으면(과거엔 2단계 개념이 없었다)
    # 그 값이 전역 OFF 를 덮어써 버튼이 계속 나타났다(2026-08-30 재발 보고).
    # 전역 스위치가 위젯 옵션보다 항상 우선한다.
    widget_ai_advice_enabled = widget_ai_advice_enabled and ai_globally_enabled

    # Fetch AI summaries only if both global and widget settings allow it.
    # One advisory per relevant scope: facility (legacy option) > this map (farm) > system.
    if ai_globally_enabled and widget_ai_advice_enabled and _AISummaryService is not None:
        _adv_scopes = []
        _facility_id = (widget_options or {}).get('facility_id') or None
        if _facility_id:
            _adv_scopes.append(('facility', str(_facility_id), gettext('Facility')))
        if selected_map_uuid:
            _map_label = (config_map.name if config_map and config_map.name else gettext('Map'))
            _adv_scopes.append(('farm', selected_map_uuid, _map_label))
        _adv_scopes.append(('system', None, gettext('System')))

        for _stype, _sid, _slabel in _adv_scopes:
            try:
                _s = _AISummaryService.get_latest_summary(scope_type=_stype, scope_id=_sid)
            except Exception:
                _s = None
            if _s is None:
                continue

            # change_summary holds a JSON array of anomaly dicts ({type, level, message})
            _anomalies = []
            if _s.change_summary:
                try:
                    _parsed = json.loads(_s.change_summary)
                    if isinstance(_parsed, list):
                        for _a in _parsed:
                            if isinstance(_a, dict):
                                _msg = _a.get('message') or _a.get('description') or ''
                            else:
                                _msg = str(_a)
                            if _msg:
                                _anomalies.append(_msg)
                except Exception:
                    pass

            # Chip title: first anomaly message if any, else the summary's first sentence
            _title = _anomalies[0] if _anomalies else (_s.summary_text or '').split('.')[0].strip()

            ai_advice_list.append({
                'scope_type': _stype,
                'scope_label': _slabel,
                'title': _title,
                'timestamp': _s.timestamp.isoformat() if _s.timestamp else None,
                'summary_text': _s.summary_text,
                'quality_score': _s.quality_score,
                'anomalies': _anomalies,
                'alert_level': _s.alert_level or 'none',
                'anomaly_detected': bool(_s.anomaly_detected),
            })

    widget_vars = {
        'async_devices': async_devices,
        'devices': devices,
        'all_measurements_map': all_measurements_map, # [New]
        'selected_base_layer': widget_options.get('selected_base_layer'),
        'device_shape_opacity': device_shape_opacity,
        # 'device_shape_color': device_shape_color, # Legacy removed
        'enable_label_collision': enable_label_collision,
        'show_labels': show_labels,
        'show_device_labels': show_device_labels,
        'show_site_label': show_site_label,
        'show_zone_label': show_zone_label,
        'show_sensor_labels': show_labels,  # sensor labels follow the master switch
        'show_site_shape': show_site_shape,
        'show_zone_shape': show_zone_shape,
        'show_facility_shape': show_facility_shape,
        'show_equipment_shape': show_equipment_shape,
        'show_device_shapes': show_device_shapes,
        'global_label_size': global_label_size,
        'label_priority_facility': label_priority_facility,
        'label_min_zoom': label_min_zoom,
        'overlay_data_only': overlay_data_only,
        'include_all_devices': include_all,
        'device_ids': ",".join(legacy_device_ids) if isinstance(legacy_device_ids, list) else legacy_device_ids,
        'device_ids_str': ",".join(legacy_device_ids) if isinstance(legacy_device_ids, list) else legacy_device_ids, # [Fix] For checkboxes
        'map_device_ids': ",".join(final_fetch_ids) if final_fetch_ids else None, # [Fix] Strictly filtered for map
        'fallback_latitude': fallback_lat,
        'fallback_longitude': fallback_lng,
        'default_zoom': default_zoom,
        'default_pitch':   int(float(w_pitch))   if w_pitch   not in (None, '') else 0,
        'default_bearing': int(float(w_bearing)) if w_bearing not in (None, '') else 0,
        'map_provider': map_provider_val,
        'map_api_key': map_api_key_val,
        'map_style_url': map_style_url_val,
        'map_default_center': common_center or MAP_DEFAULT_CENTER,
        'map_default_zoom': default_zoom or MAP_DEFAULT_ZOOM,
        'fallback_center': common_center,
        'map_state_id': map_state_id_val,
        'map_state_key': selected_map_uuid,
        'selected_map_uuid': selected_map_uuid, 
        'map_uuid': selected_map_uuid, # [Alias] for config template
        # 0 = 자동 새로고침 끔(위젯 옵션 phrase/constraints min=0 과 동일한 계약).
        # 예전엔 무조건 max(5, ...) 라 0 을 저장해도 5초 폴링이 계속 돌았다.
        # JS 는 이미 `if (vars.refreshSeconds > 0)` 로 0 을 존중한다.
        'period': 0 if period_seconds <= 0 else max(5, period_seconds),
        'map_locked': map_locked,
        'hide_controls': hide_controls,
        'show_drawn_shapes': show_drawn_shapes,
        'available_maps': available_maps,
        'available_inputs': available_inputs,
        'available_outputs': available_outputs,
        'available_functions': available_functions,
        'available_measurements_input': available_measurements_input,
        'available_measurements_output': available_measurements_output,
        'available_measurements_function': available_measurements_function,
        'measurements_input': widget_options.get('measurements_input', ''),
        'measurements_output': widget_options.get('measurements_output', ''),
        'measurements_function': widget_options.get('measurements_function', ''),
        'measurements_map': measurements_map,
        'map_list': map_list,
        'sites_in_map': sites_in_map,
        # 'selected_map_uuid': selected_map_uuid, # Duplicate, removed
        'selected_map_center': selected_map_center,
        'selected_map_zoom': selected_map_zoom,
        'global_providers': global_providers,
        'global_keys': global_keys,
        'map_global_style': map_global_style,
        'widget_unique_id': widget_unique_id,
        'label_position': label_position,
        'label_spacing': label_spacing,
        'max_measure_age': _int_option(widget_options, 'max_measure_age', 300),
        'input_update_interval': _int_option(widget_options, 'input_update_interval', 300),
        'output_update_interval': _int_option(widget_options, 'output_update_interval', 5),
        # [Simplification] These sensor-label style knobs and the popup default tab
        # were removed from the widget settings form (rarely touched, mostly
        # clutter) and are now fixed sensible constants. `.get(key, constant)`
        # still honors any value a widget saved before the form field was
        # removed — only NEW widgets (no saved value) get the constant.
        'sensor_label_max_channels': _int_option(widget_options, 'sensor_label_max_channels', 1),
        'sensor_label_decimals': _int_option(widget_options, 'sensor_label_decimals', 1),
        'sensor_label_size': float(widget_options.get('sensor_label_size', 0.85)) if widget_options else 0.85,
        'sensor_label_bg': widget_options.get('sensor_label_bg', 'rgba(15,23,42,0.78)') if widget_options else 'rgba(15,23,42,0.78)',
        'sensor_label_fg': widget_options.get('sensor_label_fg', '#f8fafc') if widget_options else '#f8fafc',
        'sensor_label_offset_y': float(widget_options.get('sensor_label_offset_y', 0.0)) if widget_options else 0.0,
        'sensor_label_opacity': float(widget_options.get('sensor_label_opacity', 0.7)) if widget_options else 0.7,
        'popup_default_tab': widget_options.get('popup_default_tab', 'overview') if widget_options else 'overview',
        'hide_ui': widget_options.get('hide_ui', False) if widget_options else False,
        'label_hidden_input': widget_options.get('label_hidden_input', False) if widget_options else False,
        'label_hidden_output': widget_options.get('label_hidden_output', False) if widget_options else False,
        'label_hidden_function': widget_options.get('label_hidden_function', False) if widget_options else False,
        'label_hidden_meas': widget_options.get('label_hidden_meas', False) if widget_options else False,
        'theme_config': theme_config,
        'active_layers': active_layers,
        'geo_config': geo_config,
        # @ANCHOR: ai_advice_summary_var
        'ai_advice_list': ai_advice_list,
        'ai_globally_enabled': ai_globally_enabled,
        'widget_ai_advice_enabled': widget_ai_advice_enabled,
        'ui_map_advice_panel': UI_MAP_ADVICE_PANEL,
    }

    # [Fix] Pass-through merge so EVERY saved custom_option reaches the client.
    # The widget JS reads all options from `vars.vars` (== this dict), treating it as
    # the full custom_options set. Historically widget_vars was a hand-maintained
    # allow-list, so newer options (sensor_label_*, facility_render_mode, enable_3d_*,
    # popup_default_tab, …) were saved but never forwarded → always fell back to JS
    # defaults. Base on the raw options and let curated/computed keys above win.
    if widget_options:
        merged = dict(widget_options)
        merged.update(widget_vars)
        widget_vars = merged

    return widget_vars
