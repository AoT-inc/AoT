# coding=utf-8
#
#  AoT_map.py - Leaflet map widget to place devices on a map
#
import logging
import json
from aot.aot_flask.extensions import db
from flask_babel import lazy_gettext

from aot.aot_flask.geo.widget.maps import generate_page_variables_logic


logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Widget Definition
# ------------------------------------------------------------------------------

def execute_at_modification(mod_widget, request_form, custom_options_presave, custom_options_postsave):
    """Handle widget modification by merging framework and legacy custom_options schemes.

    @phase active
    @stability stable
    @dependency json
    """
    options = {}
    try:
        if mod_widget.custom_options:
            options = json.loads(mod_widget.custom_options) if isinstance(mod_widget.custom_options, str) else dict(mod_widget.custom_options)
    except: pass

    final_options = options.copy()
    
    # 1. Framework Auto-parsed Merge (Highest Reliability)
    if custom_options_postsave:
        for k, v in custom_options_postsave.items():
            final_options[k] = v

    # 2. Manual/Legacy Exception Handling
    if request_form:
        # Resolve 'device_ids' from measurement selectors if needed (Legacy Support)
        manual_logic_keys = ['device_selection_input', 'device_selection_output', 'device_selection_function']
        selected_dev_unique_ids = []
        for key in manual_logic_keys:
            raw_val = final_options.get(key, '')
            if raw_val:
                if isinstance(raw_val, list):
                    ids = [str(x).strip() for x in raw_val if str(x).strip()]
                elif isinstance(raw_val, str):
                    ids = [x.strip() for x in raw_val.split(',') if x.strip()]
                else: ids = []
                selected_dev_unique_ids.extend(ids)
        
        if selected_dev_unique_ids:
            final_options['device_ids'] = selected_dev_unique_ids
            final_options['include_all_devices'] = False
        else:
            # [Fix] Empty device filter must mean "show every device placed on
            # this map", not "show none". This branch previously forced
            # include_all_devices=False whenever the filter was left blank,
            # which made collect_devices() return an empty list
            # (utils_geo.py collect_devices: `if not target_ids and not
            # include_all: return []`) — silently hiding every marker the
            # moment a widget was saved once with the (now-Advanced, optional)
            # Device Filter left untouched. That contradicts the widget's
            # basic-view promise: placing a device on the map IS showing it.
            final_options['device_ids'] = []
            final_options['include_all_devices'] = True

    # 3. Handle Map Change -> Reset View if Map Changed
    # [Fix] Handle None values safely to prevent false 'Map Changed' triggers
    old_map_uuid = str(options.get('map_uuid') or '').strip().lower()
    new_map_uuid = str(final_options.get('map_uuid') or '').strip().lower()

    if old_map_uuid and new_map_uuid and old_map_uuid != new_map_uuid:
        logger.info(f"[AoT Map Save] Map changed from {old_map_uuid} to {new_map_uuid}. Resetting view.")
        for vk in ['fallback_latitude', 'fallback_longitude', 'default_zoom']:
            if vk in final_options: 
                logger.info(f"[AoT Map Save] Deleting {vk} due to map change.")
                del final_options[vk]
    else:
        logger.debug(f"[AoT Map Save] Map unchanged ({new_map_uuid}). Preserving view.")

    return True, True, mod_widget, final_options


def generate_page_variables(widget_unique_id, widget_options):
    """Prepare template variables for the AoT map widget rendering.

    @phase active
    @stability stable
    @dependency generate_page_variables_logic
    """
    return generate_page_variables_logic(widget_unique_id, widget_options)


def widget_variables(widget_unique_id, widget_options):
    """
    Prepare template variables with GIS mode detection.
    Extends generate_page_variables with geo_mode for dynamic script loading.

    @phase active
    @stability stable
    @returns dict with geo_mode: 'vector', 'raster', or 'both'
    """
    vars = generate_page_variables_logic(widget_unique_id, widget_options)

    # Detect GIS mode from active layers
    # [Migration] Default is now 'vector' for Pure MapLibre support (3D, pitch, bearing)
    try:
        from aot.aot_flask.utils.utils_geo import get_geo_config
        geo_config = get_geo_config()
        layers = geo_config.get('layers', [])

        has_vector = any(l.get('type') == 'vector' for l in layers)
        has_raster = any(l.get('type') in ('xyz', 'wms', 'tile') for l in layers)

        if has_vector and has_raster:
            geo_mode = 'vector'  # Both: use vector mode (supports raster overlays)
        elif has_vector:
            geo_mode = 'vector'
        else:
            geo_mode = 'vector'  # [Migration] Default: Pure MapLibre (raster fallback available)

        vars['geo_mode'] = geo_mode
        geo_config['geo_mode'] = geo_mode
        vars['geo_config'] = geo_config
    except Exception as e:
        logger.warning(f"[AoT_map] Failed to detect geo mode: {e}")
        vars['geo_mode'] = 'vector'  # [Migration] Default: Pure MapLibre

    # Actuator control panel: only users with edit permission see the ON/OFF and slider controls
    try:
        from aot.aot_flask.utils.utils_general import user_has_permission
        vars['can_control'] = user_has_permission('edit_settings', silent=True)
    except Exception:
        vars['can_control'] = False

    return vars


# ------------------------------------------------------------------------------
# Widget HTML Templates (Embedded)
# ------------------------------------------------------------------------------

WIDGET_HEAD_HTML_VECTOR = """
<!-- Pure MapLibre Vector Map (Leaflet-free) -->
<link rel="stylesheet" href="/static/vendor/maplibre-gl-4.1.2/maplibre-gl.css" crossorigin="" />
<script src="/static/vendor/maplibre-gl-4.1.2/maplibre-gl.js" crossorigin=""></script>

<!-- Vector Layer Manager -->
<script src="/static/js/geo/aot-vector-layer-manager.js"></script>

<!-- Shared facility /runtime provider (dedup + short-TTL cache across pollers) -->
<script src="/static/js/widgets/AoT_map/aot-facility-runtime.js?v=1"></script>

<!-- Label layer registry & priority skeleton (rank x pin presets) -->
<script src="/static/js/widgets/AoT_map/aot-map-label-layers.js?v=1"></script>

<!-- Shared output-state classifier (pending/fault/on/off consistency) -->
<script src="/static/js/common/aot-output-state.js?v=1"></script>

<!-- Pure MapLibre Widget (no Leaflet dependency) -->
<script src="/static/js/widgets/AoT_map/aot-map-widget-vector.js?v=20260722a"></script>

<!-- Vector Map Styles -->
<style>
  .aot-map-container {
    width: 100%;
    height: 100%;
    min-height: 120px;
    position: relative;
    overflow: hidden;
  }
  .aot-vector-marker {
    cursor: pointer;
  }
  .aot-vector-marker:hover {
    z-index: 1000 !important;
  }
  .maplibregl-ctrl-group {
    border-radius: 4px !important;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2) !important;
  }
  .maplibregl-ctrl-compass .maplibregl-ctrl-icon {
    background-image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='29' height='29' viewBox='0 0 29 29'%3E%3Cpath fill='%23333' d='M14.5 0l-5 9h10z'/%3E%3Cpath fill='%23ccc' d='M14.5 29l5-9h-10z'/%3E%3C/svg%3E");
  }
</style>
"""

WIDGET_HEAD_HTML_RASTER = """
<!-- Leaflet Map Library (for raster mode) -->
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>

<!-- MarkerCluster Vendor Assets (Leaflet-dependent) -->
<link rel="stylesheet" href="/static/css/map/MarkerCluster.css">
<link rel="stylesheet" href="/static/css/map/MarkerCluster.Default.css">
<script src="/static/js/map/leaflet.markercluster.js?v=1.0.0"></script>

<!-- AoT Map Loader -->
<script src="/static/js/geo/aot-map-loader.js"></script>
<script src="/static/js/geo/aot-map-controls.js"></script>
<script src="/static/js/widgets/AoT_map/aot-stopwatch-manager.js"></script>
<!-- Actuator/device control-list ordering (natural sort + drag reorder, shared) -->
<script src="/static/js/widgets/AoT_facility/aot-actuator-order.js?v=3"></script>
<!-- Shared output-state classifier (pending/fault/on/off consistency) -->
<script src="/static/js/common/aot-output-state.js?v=1"></script>
<!-- Shared popup utilities (input/output/note HTML builders + dot positioning) -->
<script src="/static/js/widgets/AoT_map/aot-map-popup.js?v=21"></script>
<script src="/static/js/widgets/AoT_map/aot-map-widget-v3.js?v=9.3.26"></script>
<script src="/static/js/geo/aot-map-config.js?v=9.2.7"></script>

<style>
  .aot-map-container {
    width: 100%;
    height: 100%;
    min-height: 120px;
    z-index: 1;
    overflow: hidden;
  }
  .leaflet-zoom-animated { }
  .device-on {
     border-color: #ffffff !important; 
     z-index: 1000 !important;
     transition: background-color 0.4s ease, border 0.4s ease, box-shadow 0.4s ease;
  }
  .marker-pill.device-on {
      border-color: #ffffff !important;
      z-index: 1000 !important;
  }
  .geo-label-marker {
      background: none;
      border: none;
      margin: 0 !important;
      z-index: 500;
      will-change: transform;
  }
  .marker-cluster-small, .marker-cluster-medium, .marker-cluster-large {
    background-color: rgba(153, 90, 255, 0.2) !important;
  }
  .marker-cluster-small div, .marker-cluster-medium div, .marker-cluster-large div {
    background-color: rgba(153, 90, 255, 0.8) !important;
    border: 2px solid #fff;
    color: #fff !important;
    font-weight: bold;
    font-family: 'Inter', sans-serif;
    border-radius: 50%;
  }
  .marker-cluster span {
      line-height: 28px;
  }
  .marker-pill {
      display: inline-block;
      padding: 2px 8px; 
      border-radius: 4px;
      box-shadow: 0 2px 5px rgba(0,0,0,0.4);
      text-align: center;
      white-space: nowrap;
      font-weight: bold;
      transition: background-color 0.2s ease, border 0.2s ease, box-shadow 0.2s ease;
      box-sizing: border-box; 
      border-width: 2px !important;
      border-style: solid !important;
  }
  .marker-pill.device-on {
      background-color: #28a745 !important;
      border-color: #28a745 !important;
  }
  .leaflet-control-attribution img {
      display: inline !important;
      vertical-align: middle;
  }
</style>
"""

# Default: Pure MapLibre (Leaflet-free) - 3D, pitch, bearing supported
# [Migration v2.0] Leaflet completely removed
WIDGET_HEAD_HTML = """
<!-- MapLibre GL is provided by the AoT dashboard page template.
     Do NOT load it here — a second copy overwrites window.maplibregl,
     breaks the existing Map instance (canvas hidden, API mismatch).
     If maplibregl is missing the widget init will log a clear error. -->

<!-- Map tool styles (.map-tools-left/right, .tool-group, .btn-circle) — same as /geo/design -->
<link rel="stylesheet" href="/static/css/map/map.css?v=20260725j" />

<!-- 위젯 핵심 스크립트 11개 → 단일 번들 (static/js/tools/bundle.mjs: aot-map-widget).
     순서 보존: vector-layer-manager → map-loader → stopwatch → controls → custom-controls
     → actuator-order → popup → bay → facility-runtime → geo-data → widget-vector.
     아래 three/facility-3d/map-3d document.write 가드 블록은 유지(AoT_facility 위젯 공존 시
     중복로드 방지). 소스 수정 시 npm run build:bundles 후 위젯 재생성. -->
<script src="{{ asset('aot-map-widget') }}"></script>

<!-- 3D Facility rendering (three.js + AoTFacility3D + AoTFacilityMap3D)
     Guards prevent duplicate load when AoT_facility widget is on the same dashboard. -->
<script>
if (!window._aotThreeLoaded) {
  window._aotThreeLoaded = true;
  document.write('<script src="/static/js/widgets/AoT_facility/three.min.js?v=2"><\/script>');
}
if (!window._aotFacility3DLoaded) {
  window._aotFacility3DLoaded = true;
  document.write('<script src="/static/js/widgets/AoT_facility/aot-facility-3d.js?v=32"><\/script>');
}
document.write('<script src="/static/js/geo/aot-facility-map-3d.js?v=28"><\/script>');
</script>

<!-- GeoJSON overlay support -->
<script src="/static/js/geo/aot-geojson-manager.js"></script>

<!-- Sensor labels (facility fittings measurement labels + 24h popup) -->
<!-- aot-chart-core: 공용 Highcharts 기본값(local TZ 등) — bay 모달 인라인 차트가 사용 -->
<script src="/static/js/common/aot-chart-core.js"></script>
<script src="/static/js/common/sensor-label.js?v=24"></script>
<script src="/static/js/widgets/AoT_map/aot-map-sensor-labels.js?v=15"></script>
<link rel="stylesheet" href="/static/css/widget/aot-sensor-label.css?v=30">
<link rel="stylesheet" href="/static/css/components/aot-toggle.css">

<!-- Shared time-wheel module (also used by AoT_timer, sequence widgets) — zone popup "settings" (turn on until end time) -->
<link rel="stylesheet" href="/static/css/components/aot-time-wheel.css">
<script src="/static/js/components/aot-time-wheel.js?v=20260722a"></script>

<!-- Actuator group panel -->
<script src="/static/js/widgets/AoT_facility/aot-facility-actuator-panel.js?v=15"></script>
<link rel="stylesheet" href="/static/css/widget/aot-facility-widget.css?v=27">

<style>
  /* Pure MapLibre Styles */
  .aot-map-container {
    width: 100%;
    height: 100%;
    min-height: 120px;
    position: relative;
    overflow: hidden;
  }
  
  /* Vector markers (MapLibre) */
  .aot-vector-marker {
    cursor: pointer;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
  }
  .aot-vector-marker:hover {
    transform: scale(1.2);
    z-index: 1000;
  }
  .aot-vector-marker.device-on {
    box-shadow: 0 0 10px currentColor;
  }
  
  /* MapLibre controls styling */
  .maplibregl-ctrl-group {
    border-radius: 4px !important;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2) !important;
  }
  .maplibregl-ctrl-compass .maplibregl-ctrl-icon {
    background-image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='29' height='29' viewBox='0 0 29 29'%3E%3Cpath fill='%23333' d='M14.5 0l-5 9h10z'/%3E%3Cpath fill='%23ccc' d='M14.5 29l5-9h-10z'/%3E%3C/svg%3E");
  }
  
  /* Device popup */
  .aot-device-popup .maplibregl-popup-content {
    padding: 8px;
    border-radius: 4px;
  }
  
  /* 3D Controls */
  .aot-3d-controls {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  }
  .aot-3d-controls input[type="range"] {
    cursor: pointer;
  }
  
  /* Attribution */
  .maplibregl-ctrl-attrib {
    font-size: 10px;
  }

  /* Label cluster badge */
  .aot-label-cluster {
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  .aot-label-cluster:hover {
    transform: scale(1.15);
    box-shadow: 0 4px 10px rgba(0,0,0,0.5) !important;
  }

  /* Device-type label toggle: overrides collision handler's inline display:block */
  .aot-type-hidden {
    display: none !important;
  }
</style>
"""

WIDGET_BODY_HTML = """

<div id="aot-map-{{each_widget.unique_id}}" class="aot-map-container" style="position: relative;">
    <div id="aot-map-{{each_widget.unique_id}}-canvas" style="width: 100%; height: 100%;"></div>

    <!-- Search Overlay (Raster mode only) -->
    {% if geo_mode != 'vector' %}
    <div id="search-overlay-{{ each_widget.unique_id }}" class="map-search-overlay d-none">
        <aot-map-search-fixed id="search-comp-{{ each_widget.unique_id }}" placeholder="{{ _('Enter an address.') }}"></aot-map-search-fixed>
    </div>
    {% endif %}

    <!-- AI Advice chip bar (top-center; populated from #aot-map-ai-advice-{{each_widget.unique_id}} by the inline script below) -->
    <div id="aot-map-advice-chips-{{each_widget.unique_id}}" class="aot-map-advice-chips" style="display:none;">
        <div class="aot-map-advice-chips-track"></div>
    </div>
</div>

<!-- AI Advice Data Embedded -->
<script type="application/json" id="aot-map-ai-advice-{{ each_widget.unique_id }}">
{{ {
    'ai_advice_list': widget_variables.ai_advice_list or [],
    'enable_ai_advice': widget_variables.widget_ai_advice_enabled or False,
    'chips_hidden': widget_variables.ai_advice_chips_hidden or False
} | tojson | safe }}
</script>
<script type="application/json" id="aot-map-vars-{{ each_widget.unique_id }}">
{{ {
    'widgetId': each_widget.unique_id,
    'mapId': 'aot-map-' ~ each_widget.unique_id,
    'contentMapUuid': widget_variables.selected_map_uuid or '',
    'refreshSeconds': widget_variables.period | default(5),
    'devices': widget_variables.devices,
    'vars': widget_variables,
    'theme': widget_variables.theme_config,
    'layers': widget_variables.active_layers,
    'geoConfig': widget_variables.geo_config,
    'isLocked': widget_variables.map_locked or False,
    'hideControls': widget_variables.hide_controls or False,
    'geo_mode': widget_variables.geo_mode or 'vector',
    'can_control': widget_variables.can_control if widget_variables.can_control is not none else false
} | tojson | safe }}
</script>
<script>
    ;(function() {
        // Initialize Pure MapLibre Widget (Leaflet-free)
        if (typeof window.initAoTMapVectorWidget === 'function') {
            window.initAoTMapVectorWidget('{{each_widget.unique_id}}');
        } else {
            console.error('[AoT Map] Pure MapLibre Widget JS not loaded');
        }

        // AI Advice chips — reads #aot-map-ai-advice-{{each_widget.unique_id}}, no bundle dependency.
        // Compact title chips at the top of the map; click opens a detail modal
        // (shared .aot-center-modal shell) with a follow-up-question hook into
        // the global AI chat ('open-ai-chat' event → AoT_AI.openChat).
        (function (widgetId) {
            var dataEl = document.getElementById('aot-map-ai-advice-' + widgetId);
            var chipsWrap = document.getElementById('aot-map-advice-chips-' + widgetId);
            if (!dataEl || !chipsWrap) return;
            var track = chipsWrap.querySelector('.aot-map-advice-chips-track');

            var data;
            try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }
            var list = (data.enable_ai_advice && Array.isArray(data.ai_advice_list)) ? data.ai_advice_list : [];
            if (!list.length) return;

            var LVL = function (level) {
                if (level === 'critical') return { cls: 'danger', card: 'now', label: {{ _('Critical')|tojson }} };
                if (level === 'warning')  return { cls: 'warning', card: 'h1', label: {{ _('Warning')|tojson }} };
                if (level === 'info')     return { cls: 'info', card: 'h6', label: {{ _('Info')|tojson }} };
                return { cls: 'ok', card: 'h6', label: {{ _('Normal')|tojson }} };
            };

            function esc(str) {
                if (str == null) return '';
                return String(str)
                    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
            }

            // ── Detail modal: replicate the shared centered-modal shell
            //    (same DOM/classes as _showFacilityCenterOverlay in the map bundle) ──
            function openModal(item) {
                var OVERLAY_ID = 'aot-map-advice-modal-' + widgetId;
                var existing = document.getElementById(OVERLAY_ID);
                if (existing) existing.remove();

                var lvl = LVL(item.alert_level);
                var ts = item.timestamp ? new Date(item.timestamp).toLocaleString() : '';

                var overlay = document.createElement('div');
                overlay.id = OVERLAY_ID;
                overlay.style.cssText = 'position:fixed;inset:0;z-index:var(--aot-z-modal);display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.35)';

                var popupWrap = document.createElement('div');
                popupWrap.style.cssText = 'position:relative;';

                var box = document.createElement('div');
                box.className = 'maplibregl-popup-content aot-center-modal';
                box.innerHTML =
                    '<div class="aot-sensor-popup-header aot-adv-modal-header">' +
                        '<span class="aot-adv-dot aot-adv-lvl-' + lvl.cls + '"></span>' +
                        '<b>' + esc(item.scope_label) + '</b>' +
                        '<span class="aot-adv-modal-level">' + esc(lvl.label) + (ts ? ' · ' + esc(ts) : '') + '</span>' +
                    '</div>' +
                    '<div class="aot-adv-modal-body">' +
                        '<div class="advice-card ' + lvl.card + '">' +
                            '<div class="advice-actions">' + esc(item.summary_text || '') + '</div>' +
                        '</div>' +
                        (item.anomalies && item.anomalies.length
                            ? '<div class="aot-adv-modal-anoms">' + item.anomalies.map(function (a) {
                                  return '<div class="advice-reason">· ' + esc(a) + '</div>';
                              }).join('') + '</div>'
                            : '') +
                    '</div>' +
                    '<div class="aot-adv-modal-qa">' +
                        '<textarea class="form-control aot-adv-modal-qa-input" rows="2" placeholder="' + esc({{ _('Ask a question about this advisory (e.g., what should I do?)')|tojson }}) + '"></textarea>' +
                        '<button type="button" class="aot-popup-btn aot-popup-btn--primary aot-popup-btn--full aot-adv-modal-ask">' + {{ _('Ask AI what to do')|tojson }} + '</button>' +
                    '</div>';

                var closeBtn = document.createElement('button');
                closeBtn.className = 'maplibregl-popup-close-button aot-center-modal-close';
                closeBtn.setAttribute('type', 'button');
                closeBtn.setAttribute('aria-label', 'Close');
                closeBtn.innerHTML = '&#x2715;';
                closeBtn.style.cssText = 'position:absolute;top:10px;right:14px;background:none;border:none;cursor:pointer;font-size:16px;line-height:1;padding:4px 6px;z-index:1;';

                popupWrap.appendChild(box);
                popupWrap.appendChild(closeBtn);
                overlay.appendChild(popupWrap);

                var _prevOverflow = document.body.style.overflow;
                document.body.style.overflow = 'hidden';
                var _fsHost = document.fullscreenElement || document.webkitFullscreenElement || document.body;
                _fsHost.appendChild(overlay);

                function close() {
                    if (!document.getElementById(OVERLAY_ID)) return;
                    overlay.remove();
                    document.body.style.overflow = _prevOverflow;
                }
                overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
                closeBtn.addEventListener('click', close);

                // Follow-up Q&A → hand off to the global AI chat with this advisory as context
                box.querySelector('.aot-adv-modal-ask').addEventListener('click', function () {
                    var q = box.querySelector('.aot-adv-modal-qa-input').value.trim();
                    if (!q) q = {{ _('What concrete actions should I take based on this advisory?')|tojson }};
                    close();
                    window.dispatchEvent(new CustomEvent('open-ai-chat', { detail: {
                        name: item.scope_label,
                        targetType: 'ai_advisory',
                        autoMessage: q,
                        ai_advisory: {
                            scope_label: item.scope_label,
                            alert_level: item.alert_level,
                            timestamp: item.timestamp,
                            summary_text: item.summary_text,
                            anomalies: item.anomalies || []
                        }
                    }}));
                });
            }

            // ── Chip bar ──
            list.forEach(function (item, i) {
                var lvl = LVL(item.alert_level);
                var chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'aot-map-advice-chip';
                chip.innerHTML =
                    '<span class="aot-adv-dot aot-adv-lvl-' + lvl.cls + '"></span>' +
                    '<span class="aot-adv-chip-scope">' + esc(item.scope_label) + '</span>' +
                    '<span class="aot-adv-chip-title">' + esc(item.title || lvl.label) + '</span>';
                chip.addEventListener('click', function () { openModal(item); });
                track.appendChild(chip);
            });
            // Respect the toolbar's AI-advice hide toggle (persisted per widget);
            // chips are still rendered so un-hiding shows them instantly.
            if (!data.chips_hidden) chipsWrap.style.display = '';
        })('{{each_widget.unique_id}}');
    })();
</script>
"""

WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_map',
    'widget_name': lazy_gettext('AoT Map'),
    # On mobile (<=768px), place only one widget per row (full width). If False/unset, allow two per row.
    'mobile_full_width': True,
    'widget_library': 'MapLibre GL JS (Leaflet-free)',  # [Migration v2.0] Pure MapLibre
    'no_class': True,
    'head_html': WIDGET_HEAD_HTML,
    'body_html': WIDGET_BODY_HTML,
    'configure_html': None,
    'widget_dashboard_configure_options': None,

    'message': lazy_gettext('Displays the location of the selected device on a map. Highlights the operating state with the selected color. Supports 3D terrain, pitch, and bearing.'),

    'widget_width': 26,
    'widget_height': 17,
    'generate_page_variables': widget_variables,
    'execute_at_modification': execute_at_modification,

    # Custom options appear in the widget settings form.
    # [Simplification] Basic view = a single 'Map' section (~6 options: map
    # select, labels/data-only/AI-advice display toggles, refresh period).
    # Devices placed on the map in the map editor (/geo/design) are shown
    # automatically — there is no separate "which devices to show" step here.
    # Everything else (device/measurement filters, 3D, label fine-tuning,
    # shapes, runtime view-state) lives behind the collapsed 'Advanced'
    # disclosure so it doesn't have to be learned to use the widget.
    'custom_options': [
        # --- Map ---
        {
            'type': 'header',
            'name': lazy_gettext('Map')
        },
        {
            # [Simplification] Replaces the old 'Device Selection' dropdowns as the
            # primary way users learn how devices get on the map: placement in the
            # map editor IS the selection. Subset filtering (when you deliberately
            # want to hide some placed devices) still exists under Advanced.
            # Positioned BEFORE 'Select Map' (not after) so it groups visually with
            # that field: .aot-modal-option-row carries its own border-bottom, and
            # this message div carries none, so a message placed right after a row
            # always reads as a caption of the row that FOLLOWS it, not the one
            # above — with 'Select Map' next, this message looked like it was
            # describing 'Show Labels' below the field. Message-then-field with the
            # field's own border closing the group reads correctly instead.
            'type': 'message',
            'default_value': lazy_gettext(
                'All devices placed on this map in the map editor are shown '
                'automatically. Add or move devices in '
                '<a href="/geo/design" target="_blank" rel="noopener">Map Editor (geo/design)</a>.'
            )
        },
        {
            'id': 'map_uuid',
            'type': 'select_device',
            'options_select': ['Map'],
            'default_value': '',

            'name': lazy_gettext('Select Map'),
            'phrase': lazy_gettext('Select a map. Leave empty to use the most recently modified map.')
        },
        {
            # [Simplification] Display + Refresh folded into Map — one basic
            # section instead of three, since none of these need their own
            # topic header to be found.
            # Master label switch: turns ALL map labels (site / zone / device / sensor)
            # on or off. Per-device-type granularity (input / output / function) is
            # handled at runtime by the map's right-side label controller, so there is
            # no per-category toggle here.
            'id': 'show_labels',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Labels'),
            'phrase': lazy_gettext(
                'Master switch for all map labels (site, zone, device, sensor). '
                'Use the map\'s label controller to fine-tune input/output/function labels.'
            )
        },
        {
            'id': 'overlay_data_only',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Display Data Only (Hide Map)'),
            'phrase': lazy_gettext('Hide the overlay map and show only the data panel.')
        },
        {
            # @ANCHOR: ai_advice_enabled_option [2026-07-07]
            # Backend fetch (generate_page_variables_logic in maps.py) already reads
            # widget_options.get('ai_advice_enabled', ...) and embeds the latest
            # AISystemSummary via #aot-map-ai-advice-{id}; this option was the missing
            # piece exposing that toggle in the widget settings form.
            'id': 'ai_advice_enabled',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Show AI Advice'),
            'phrase': lazy_gettext(
                'Display the latest periodic AI advice summary for this map\'s facility/site.'
            )
        },
        {
            'id': 'period',
            'type': 'integer',
            'default_value': '5',
            'name': lazy_gettext('Period (Seconds)'),
            'phrase': lazy_gettext('Refresh the widget every N seconds. 0 to disable.'),
            'constraints': {'min': 0, 'max': 86400}
        },

        # ============================================================
        # Advanced groups — [Reorganize] Each topic gets its OWN collapsed
        # disclosure instead of one giant "Advanced" bucket. A single mega
        # section reads as "dumped in and done" and forces users to scan
        # everything to find one setting; separate, clearly-named groups let
        # someone jump straight to "3D" or "Shapes" without wading through
        # the rest. `fallback_latitude/longitude/default_zoom/default_pitch/
        # default_bearing/active_layers/selected_base_layer` are gone
        # entirely (not just collapsed) — they are pure runtime view state
        # the map already persists on its own via moveend/layer-toggle
        # handlers (aot-map-widget-vector.js: `/save_widget_custom_options`
        # on pan/zoom/rotate and on layer switch), so a form field for them
        # was never anything a user would hand-type; it was clutter with no
        # corresponding user action.
        # ============================================================

        # --- Device Filter ---
        {
            'type': 'collapse_start',
            'id': 'device_filter',
            'name': lazy_gettext('Device Filter')
        },
        {
            'type': 'message',
            'default_value': lazy_gettext(
                'Nothing is selected by default, so every device placed on the '
                'map is shown. Devices you select below are hidden from the map.'
            )
        },
        {
            'id': 'device_selection_input',
            'type': 'select_multi_device',
            'options_select': ['Input'],
            'default_value': '',

            'name': lazy_gettext('Input'),
            'phrase': lazy_gettext('Select inputs to hide. Leave empty to show all placed inputs.')
        },
        {
            'id': 'device_selection_output',
            'type': 'select_multi_device',
            'options_select': ['Output'],
            'default_value': '',

            'name': lazy_gettext('Output'),
            'phrase': lazy_gettext('Select outputs to hide. Leave empty to show all placed outputs.')
        },
        {
            'id': 'device_selection_function',
            'type': 'select_multi_device',
            'options_select': ['Function'],
            'default_value': '',

            'name': lazy_gettext('Function'),
            'phrase': lazy_gettext('Select functions to hide. Leave empty to show all placed functions.')
        },
        {
            'type': 'collapse_end'
        },

        # --- Measurement Panel ---
        {
            'type': 'collapse_start',
            'id': 'measurement_panel',
            'name': lazy_gettext('Measurement Panel')
        },
        {
            'id': 'measurements_input',
            'type': 'select_multi_measurement',
            'options_select': ['Input'],
            'default_value': '',

            'name': lazy_gettext('Input'),
            'phrase': lazy_gettext('Select input measurements to display in the panel.')
        },
        {
            'id': 'measurements_output',
            'type': 'select_multi_measurement',
            'options_select': ['Output'],
            'default_value': '',

            'name': lazy_gettext('Output'),
            'phrase': lazy_gettext('Select output measurements to display in the panel.')
        },
        {
            'id': 'measurements_function',
            'type': 'select_multi_measurement',
            'options_select': ['Function'],
            'default_value': '',

            'name': lazy_gettext('Function'),
            'phrase': lazy_gettext('Select function measurements to display in the panel.')
        },
        {
            'type': 'collapse_end'
        },

        # --- Label Style ---
        {
            'type': 'collapse_start',
            'id': 'label_style',
            'name': lazy_gettext('Label Style')
        },
        {
            'id': 'enable_label_collision',
            'type': 'bool',
            'default_value': True,

            'name': lazy_gettext('Prevent Label Collision'),
            'phrase': lazy_gettext('Automatically hide overlapping labels when enabled.')
        },
        {
            'id': 'global_label_size',
            'type': 'float',
            'default_value': '1.0',

            'name': lazy_gettext('Label Text Size'),
            'phrase': lazy_gettext('Specify the size of all map labels (unit: em).'),
            'constraints': {'min': 1.0, 'max': 3.0}
        },
        {
            'id': 'label_priority_facility',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('Facility-centric Labels'),
            'phrase': lazy_gettext(
                'Off (default): outdoor-centric — site/zone labels stay visible at all '
                'zoom levels; facility and sensor labels appear only when zoomed in. '
                'On: facility-centric — facility and sensor labels take priority; '
                'site/zone labels yield and merge when zoomed out.'
            )
        },
        {
            # Style-only; visibility follows the master 'Show Labels'. Fine styling
            # knobs (color/opacity/offset/decimals/max-channels) were removed and
            # are now fixed sensible constants (see maps.py widget_vars) — they were
            # rarely touched and mostly added clutter.
            'id': 'sensor_label_style',
            'type': 'select',
            'default_value': 'circle',
            'options_select': [
                ('circle', lazy_gettext('Circle (integer value)')),
                ('text', lazy_gettext('Text label')),
            ],
            'name': lazy_gettext('Sensor Marker Style'),
            'phrase': lazy_gettext('Circle: compact round marker showing the first measurement as an integer, colored by measurement band. Text: full value label.')
        },
        {
            'id': 'sensor_popup_enabled',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Enable Sensor Popup'),
            'phrase': lazy_gettext('Click a sensor label to open a detail popup with the last 24h chart.')
        },
        {
            'type': 'collapse_end'
        },

        # --- Shapes ---
        {
            'type': 'collapse_start',
            'id': 'shapes',
            'name': lazy_gettext('Shapes')
        },
        {
            'id': 'show_site_shape',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('Site Shape'),
            'phrase': lazy_gettext('Show Site polygons on the map.')
        },
        {
            'id': 'show_zone_shape',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('Zone Shape'),
            'phrase': lazy_gettext('Show Zone polygons on the map.')
        },
        {
            'id': 'show_facility_shape',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('Facility Shape'),
            'phrase': lazy_gettext('Show Facility polygons on the map.')
        },
        {
            'id': 'show_equipment_shape',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('Equipment Shape'),
            'phrase': lazy_gettext('Show Equipment (e.g., pipes) shapes on the map.')
        },
        {
            'id': 'show_device_shapes',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('Device Shape'),
            'phrase': lazy_gettext('Show Device shape areas on the map.')
        },
        {
            'id': 'show_drawn_shapes',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('Other Drawn Shapes'),
            'phrase': lazy_gettext('Show freeform shapes created with drawing tools.')
        },
        {
            'id': 'device_shape_opacity',
            'type': 'integer',
            'default_value': '50',
            'name': lazy_gettext('Device Shape Opacity'),
            'phrase': lazy_gettext('0 (Transparent) ~ 100 (Opaque)'),
            'constraints': {'min': 0, 'max': 100}
        },
        {
            'type': 'collapse_end'
        },

        # --- 3D Map ---
        {
            'type': 'collapse_start',
            'id': '3d_map',
            'name': lazy_gettext('3D Map (Vector Mode)')
        },
        {
            'id': 'enable_3d_terrain',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('Enable 3D Terrain'),
            'phrase': lazy_gettext('Enable 3D terrain rendering (Hillshade, elevation). Requires vector mode.')
        },
        {
            'id': 'facility_render_mode',
            'type': 'select',
            'default_value': 'default',
            'options_select': [
                ('default',     lazy_gettext('Default (transparent)')),
                ('solid',       lazy_gettext('Solid (opaque)')),
                ('wireframe',   lazy_gettext('Wireframe')),
                ('performance', lazy_gettext('Performance (mobile)')),
            ],
            'name': lazy_gettext('Facility Render Mode'),
            'phrase': lazy_gettext(
                'Render style for the 3D facility overlay on the map. '
                'Solid/Wireframe/Performance reduce GPU load.'
            )
        },
        {
            'id': 'map_style_url',
            'type': 'text',
            'default_value': '',

            'name': lazy_gettext('Vector Style URL'),
            'phrase': lazy_gettext('Custom MapLibre style JSON URL. Leave empty to use GIS input setting.')
        },
        {
            'type': 'collapse_end'
        },
    ],

    'widget_dashboard_head': WIDGET_HEAD_HTML,
    
    'widget_dashboard_title_bar': """
    <span class="aot-w-title" style="padding-right:0.5em">{{each_widget.name}}</span>

    <div class="widget-map-controls" id="widget-map-controls-{{each_widget.unique_id}}">
        <a class="widget-map-ctrl-btn"
           id="tool-lock-{{each_widget.unique_id}}"
           data-locked="{{ 'true' if widget_variables.get('map_locked', False) else 'false' }}"
           {% if not settings.hide_tooltips %}title="{{ _('Unlock Map') if widget_variables.get('map_locked', False) else _('Lock Map') }}"{% endif %}>
            <i class="fas fa-{{ 'lock' if widget_variables.get('map_locked', False) else 'unlock' }}"></i>
        </a>
        <a class="widget-map-ctrl-btn"
           id="tool-hide-{{each_widget.unique_id}}"
           data-hidden="{{ 'true' if widget_variables.get('hide_controls', False) else 'false' }}"
           {% if not settings.hide_tooltips %}title="{{ _('Show Controls') if widget_variables.get('hide_controls', False) else _('Hide Controls') }}"{% endif %}>
            <i class="fas fa-grip-horizontal" style="{{ 'opacity:0.35;' if widget_variables.get('hide_controls', False) else '' }}"></i>
        </a>
    </div>
    """,

    'widget_dashboard_body': WIDGET_BODY_HTML,

    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",

    'widget_dashboard_js_ready_end': """
  ;(function() {
      // 1. Inject Unit Configuration from Dashboard Context
      // This maps Measurement Unique ID -> Unit String (Symbol)
      var aotMapUnits = {};
      
      {% if dict_measure_units is defined %}
          {% for m_id, u_id in dict_measure_units.items() %}
              {% if dict_units is defined and u_id in dict_units %}
                  aotMapUnits['{{ m_id }}'] = '{{ dict_units[u_id].unit }}';
              {% else %}
                  aotMapUnits['{{ m_id }}'] = '{{ u_id }}';
              {% endif %}
          {% endfor %}
      {% endif %}

      // Expose to Global Scope for Map JS to use
      window.aotMapUnits = aotMapUnits;

  })();
"""
}
