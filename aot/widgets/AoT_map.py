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

    # [Migration v2.0] Leaflet is gone, so the widget renders with Pure MapLibre
    # regardless of which layer types the GIS config has — raster layers are drawn
    # as MapLibre raster sources, not by a separate raster (Leaflet) code path.
    # geo_mode is therefore a constant; it is still emitted because the client
    # bundle and geo_config consumers read it.
    try:
        from aot.aot_flask.utils.utils_geo import get_geo_config
        geo_config = get_geo_config()
        vars['geo_mode'] = 'vector'
        geo_config['geo_mode'] = 'vector'
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

# Default: Pure MapLibre (Leaflet-free) - 3D, pitch, bearing supported
# [Migration v2.0] Leaflet completely removed
WIDGET_HEAD_HTML = """
<!-- MapLibre GL is provided by the AoT dashboard page template.
     Do NOT load it here — a second copy overwrites window.maplibregl,
     breaks the existing Map instance (canvas hidden, API mismatch).
     If maplibregl is missing the widget init will log a clear error. -->

<!-- Map tool styles (.map-tools-left/right, .tool-group, .btn-circle) — same as /geo/design -->
{#- map.css 는 layout.html 이 모든 페이지에서 이미 싣는다 — 여기서 또 걸면
    한 화면에 같은 파일이 두 번 내려간다(실측으로 확인). -#}

<!-- widget-shared — **구획 위젯(AoT_plot)과 나눠 쓰는 소스.** 반드시 아래
     aot-map-widget 보다 먼저.
     plot-labels · plot-form · dataviz · sensor-label · geo-data · map-sensor-labels · popup

     예전에는 이 442KB 가 지도 위젯 번들과 구획 위젯 번들 **양쪽에 사본으로** 들어
     있었다(구획 위젯 번들의 69% 가 지도 위젯 번들과 같은 소스였다). 각 모듈에 가드가
     있어 재정의는 건너뛰었지만 **받고 파싱하는 값은 두 번 치렀다** — 한 대시보드에
     두 위젯이 서면 442KB 를 두 벌 받았다. 이제 URL 이 같으므로 한 벌만 받는다.
     위젯 하나만 있는 대시보드가 받는 총량은 예전과 **같다**(쪼갰을 뿐 더하지 않았다). -->
<script src="{{ asset('widget-shared') }}"></script>

<!-- 위젯 핵심 스크립트 → 단일 번들 (static/js/tools/bundle.mjs: aot-map-widget).
     순서 보존: vector-layer-manager → map-loader → stopwatch → controls → custom-controls
     → actuator-order → bay → facility-runtime → label-layers → plot → widget-vector.
     아래 three/facility-3d/map-3d document.write 가드 블록은 유지(AoT_facility 위젯 공존 시
     중복로드 방지). 소스 수정 시 npm run build:bundles 후 위젯 재생성. -->
<script src="{{ asset('aot-map-widget') }}"></script>

<!-- 3D Facility rendering (three.js + AoTFacility3D + AoTFacilityMap3D)
     예전에는 이 셋(831KB)을 document.write 로 무조건 끌어왔다. 지도 위젯만 올려도
     3D 시설을 한 번도 안 여는 대시보드가 831KB 를 받고 파싱했고, document.write 는
     파서까지 멈춰 세웠다. 이제 로더만 미리 두고, 지도에 3D 지오메트리를 가진 시설이
     실제로 있을 때 aot-map-widget-vector.js 가 ensure() 로 그때 받는다. -->
<script src="{{ asset('widget-map-extra') }}"></script>

<!-- GeoJSON overlay support -->

<!-- Sensor labels (facility fittings measurement labels + 24h popup) -->
<!-- aot-chart-core: 공용 Highcharts 기본값(local TZ 등) — bay 모달 인라인 차트가 사용 -->
<!-- 출력 상태 공용 분류기(on/off/pending/fault). 위젯 코드가 이미 이것을
     전제로 쓰고 있었는데 정작 로드는 안 하고 있어서, 늘 인라인 폴백으로
     떨어져 있었다 — 'fault'(무응답) 판정이 화면마다 달라질 수 있는 상태였다. -->
<!-- 고정 리터럴 `?v=52` 였다 — 내용이 바뀌어도 URL 이 그대로라 1년 캐시가
     곧 "1년간 옛 JS" 가 된다(CLAUDE.md 정적 캐시 무효화). url_for 가 내용
     해시를 붙인다. -->
{% if "css_sensor_label" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/widget/aot-sensor-label.css') }}">
{% set _dummy = dashboard_dict.update({"css_sensor_label": 1}) %}
{% endif %}
<!-- 공용 데이터 시각화 프리미티브(밴드 바 · 불릿 · 기간 바).
     구획 모달의 기간 축이 쓴다. 규약: docs/design/dataviz-primitives.md -->
{#- aot-dataviz.css 도 layout.html 이 이미 싣는다. -#}
{#- aot-plot-form.css 는 AoT_plot 위젯도 건다 — 먼저 그린 쪽만 걸리게 한다. -#}
{% if "css_plot_form" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/components/aot-plot-form.css') }}">
{% set _dummy = dashboard_dict.update({"css_plot_form": 1}) %}
{% endif %}

<!-- Shared time-wheel module (also used by AoT_timer, sequence widgets) — zone popup "settings" (turn on until end time) -->
{% if "css_time_wheel" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/components/aot-time-wheel.css') }}">
{% set _dummy = dashboard_dict.update({"css_time_wheel": 1}) %}
{% endif %}
<script src="{{ asset('widget-map-tail') }}"></script>

<!-- Actuator group panel -->
{% if "css_facility_widget" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/widget/aot-facility-widget.css') }}">
{% set _dummy = dashboard_dict.update({"css_facility_widget": 1}) %}
{% endif %}

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
    /* 사다리 예외: 지도 위에 겹쳐 두는 저작권 표시다. 지도를 가리지 않으면서
       읽을 수는 있어야 하는 자리라 MapLibre·OSM 관례 크기를 따른다 —
       사다리 최소단(2xs = 11.2px)으로 키우면 좁은 위젯에서 지도를 덮는다. */
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

  /* Device-type label toggle: overrides collision handler's inline display:block
     ⚠ `:not(.aot-focus-show)` 는 임시 표시를 위한 것이다 — 아래 주석 참조. */
  .aot-type-hidden:not(.aot-focus-show) {
    display: none !important;
  }

  /* Zoom gate (LABEL_MIN_ZOOM): 축척이 낮을 때 장치 단위 라벨·키를 감춘다.
     사용자 토글(.aot-type-hidden)과 같은 이유로 !important — 충돌 회피가
     인라인 display:block 을 직접 찍기 때문에 클래스가 이겨야 한다. */
  .aot-zoom-hidden:not(.aot-focus-show) {
    display: none !important;
  }

  /* L2 게이트의 "켜짐-단독" 제한 (FOCUS_LIMIT_L2, 지금은 출력만).
     위 `.aot-zoom-hidden` 은 그대로 두고(안 켜진 출력은 여전히 줌 17에서
     접힌다) 이 클래스를 그 위에 추가로 얹는다 — 켜져 있어서(active) 임시
     표시 중이던 것이 아주 멀리 줌아웃하면(L2 기준, 기본 15.5) 다시 접히게
     하기 위해서다. `:not(.aot-focus-show-modal)` 이라 **모달이 열려 있으면**
     (그 순간엔 "어디 이야기인지" 를 보여줘야 하므로) 이 게이트도 비켜간다 —
     `.aot-focus-show`(이유 불문) 대신 이 클래스를 쓰는 것이 핵심: active
     단독으로는 못 이기고 modal 이 있어야 이긴다. */
  .aot-zoom-hidden-l2:not(.aot-focus-show-modal) {
    display: none !important;
  }

  /* 임시 표시 — 사용자가 꺼 둔 라벨이라도 **지금 봐야 할 이유**가 있으면 보인다
     (그 대상의 모달이 열려 있다 · 그 출력이 켜져 있다).

     ⚠ **`display` 값을 지정하지 않는다.** 예전에는 `display: block !important`
     로 되살렸는데, 그러면 그 라벨이 원래 무엇이었는지를 여기서 정해 버린다 —
     값 키의 원형 모드(`.aot-sensor-map-marker--circle`)는 `display: flex` 로
     숫자를 원 한가운데 놓으므로, block 으로 바뀌는 순간 숫자가 좌상단으로
     밀린다(실측). 라벨 종류마다 display 가 다르니 여기서 하나를 고르면 언제나
     어느 하나는 깨진다.

     대신 **숨김 규칙이 이 클래스를 비켜 가게** 한다. 그러면 각자의 display 가
     그대로 살아 있고, 이유가 사라지면 숨김이 다시 걸린다(꺼 둔 상태 자체는
     건드리지 않는다). 새 숨김 클래스를 만들면 여기에도 `:not(.aot-focus-show)`
     를 붙일 것 — 빠뜨리면 그 종류만 임시 표시가 안 듣는다. */
</style>
"""

WIDGET_BODY_HTML = """

<div id="aot-map-{{each_widget.unique_id}}" class="aot-map-container" style="position: relative;">
    <div id="aot-map-{{each_widget.unique_id}}-canvas" style="width: 100%; height: 100%;"></div>

    <!-- Address search overlay. The toolbar's search button toggles `.d-none` on
         this element (aot-map-widget-vector.js: `_wire(btnSearch, ...)`), and the
         fly-to listener matches `search-comp-<uid>` — so it is required in vector
         mode, i.e. always. It used to sit behind an if-block on `geo_mode`
         labelled "raster only"; that only rendered because bare `geo_mode` is
         undefined in this template context (widget vars arrive as
         `widget_variables.*`), and Undefined != 'vector' is true. Making that
         condition "correct" would have deleted the overlay and silently broken
         address search. -->
    <div id="search-overlay-{{ each_widget.unique_id }}" class="map-search-overlay d-none">
        <aot-map-search-fixed id="search-comp-{{ each_widget.unique_id }}" placeholder="{{ _('Enter an address.') }}"></aot-map-search-fixed>
    </div>

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
                        '<span class="aot-sensor-popup-title">' + esc(item.scope_label) + '</span>' +
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
                closeBtn.style.cssText = 'position:absolute;top:10px;right:14px;background:none;border:none;cursor:pointer;font-size:var(--aot-font-size-base);line-height:1;padding:4px 6px;z-index:1;';

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
            # 지도는 세계 어디로든 간다 — 그래서 이 독이 답하는 "지금 몇 시인가"는
            # 농장의 시간이 아니라 **화면 한가운데가 있는 곳의 현지 시각**이다.
            # 시간대 해석과 태양시는 전부 서버 몫이다(/api/geo/local_time).
            # 기본값이 꺼짐인 이유: 지도 상단 중앙은 주소 검색바와 AI 조언 칩이
            # 이미 쓰는 자리다. 켜면 시간 독이 그 자리의 상주자가 되고 나머지가
            # 아래로 밀린다(map.css --aot-top-dock-h) — 시간을 늘 띄워 두겠다고
            # 정한 사람만 그 대가를 치르면 된다.
            'id': 'show_local_time',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Show Local Time'),
            'phrase': lazy_gettext(
                'Show a dock at the top of the map with the current time, sunrise '
                'and sunset for wherever the map is centered.'
            )
        },
        # --- Data Transfer Period ---
        # [Restore] These three refresh knobs used to be scattered/removed
        # during earlier simplification passes (input_update_interval was
        # dropped from the form entirely; output status had no knob of its
        # own and silently rode the widget period). Grouped together here
        # because they answer one question users actually ask: "how fresh
        # is what I'm looking at" — for the map view itself, for input
        # readings, and for output on/off state, each on its own clock.
        # Collapsed like the other secondary groups below (Device Filter,
        # Measurement Panel, ...) — rarely-touched knobs, not part of the
        # first-look basic view (Map / Display / AI Advice above stay open).
        {
            'type': 'collapse_start',
            'id': 'data_transfer_period',
            'name': lazy_gettext('Data Transfer Period')
        },
        {
            'id': 'period',
            'type': 'integer',
            'default_value': '5',
            'name': lazy_gettext('Widget Refresh Period (Seconds)'),
            'phrase': lazy_gettext('Refresh the widget every N seconds. 0 to disable.'),
            'constraints': {'min': 0, 'max': 86400}
        },
        {
            'id': 'input_update_interval',
            'type': 'integer',
            'default_value': '300',
            'name': lazy_gettext('Input Value Refresh Period (Seconds)'),
            'phrase': lazy_gettext('How often input measurement values in the panel are refreshed.'),
            'constraints': {'min': 5, 'max': 86400}
        },
        {
            'id': 'output_update_interval',
            'type': 'integer',
            'default_value': '5',
            'name': lazy_gettext('Output Status Refresh Period (Seconds)'),
            'phrase': lazy_gettext('How often output on/off status is refreshed on the map.'),
            'constraints': {'min': 5, 'max': 86400}
        },
        {
            'type': 'collapse_end'
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
            # 그룹 전체의 마스터 스위치 — 아래 선택은 그대로 둔 채 패널만
            # 통째로 숨긴다(선택을 비우는 것과 다르다: 다시 켜면 고르던
            # 항목이 그대로 돌아온다).
            'id': 'show_measurement_panel',
            'type': 'bool',
            'default_value': True,

            'name': lazy_gettext('Show Measurement Panel'),
            'phrase': lazy_gettext(
                'Show the measurement panel dock. Turn off to hide it entirely, '
                'even if measurements are selected below.'
            )
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
            # L1 — 시설/장치/값 키. 가까이 가야 읽히는 것들이라 기준 줌이 높다
            # (기본 17). 구역·시설은 더 넓은 축척부터 계속 보여야 뜻이 있어
            # 같은 줌 하나로 못 묶는다 — 그래서 L2(아래)로 따로 뺐다.
            'id': 'label_min_zoom',
            'type': 'integer',
            'default_value': 17,

            'name': lazy_gettext('Hide Labels When Zoomed Out — L1'),
            'phrase': lazy_gettext(
                'Below this zoom level, output / input / function / equipment / '
                'sensor / plot / bay / note labels and value keys are hidden. '
                'Site labels always stay visible so the map keeps its bearings. '
                'Zone and facility labels have their own threshold below (L2). '
                'Set 0 to never hide.'
            ),
            'constraints': {'min': 0, 'max': 22}
        },
        {
            # L2 — 구역·시설 라벨 + 구역·구획·설비 도형(_SHAPE_LOD_L2, 2026-08-29
            # 도형 축 편입). 지금은 이 다섯뿐이지만 이름을 "L2"로 둔 이유는
            # 앞으로 다른 라벨·키·도형이 이 축척대에서 접혀야 한다고 밝혀지면
            # 여기 추가할 자리이기 때문이다(L1 은 건드리지 않는다).
            'id': 'label_min_zoom_l2',
            'type': 'float',
            'default_value': '15.5',

            'name': lazy_gettext('Hide Labels & Shapes When Zoomed Out — L2'),
            'phrase': lazy_gettext(
                'A second, independent zoom threshold — currently for zone/facility '
                'labels and zone/plot/equipment shapes. They need to stay visible at '
                'a wider zoom than L1 above, so they get their own value here. More '
                'label and shape kinds may be added to this tier later. Set 0 to '
                'never hide.'
            ),
            'constraints': {'min': 0, 'max': 22}
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
        # 설정 간소화(e939cf4)에서 화면만 빠지고 값 전달은 그대로 남아 있었다 —
        # 설정할 방법이 없는 옵션이 되어 있었다. 구역·시설·장치 모달이 같은 탭
        # 세 개를 쓰게 되면서 이 설정이 세 계층 모두에 걸리므로 되살린다.
        {
            'id': 'popup_default_tab',
            'type': 'select',
            'default_value': 'overview',
            'options_select': [
                ('overview', lazy_gettext('Overview')),
                ('envctl', lazy_gettext('Environment & Control')),
                ('about', lazy_gettext('About')),
            ],
            'name': lazy_gettext('Popup Default Tab'),
            'phrase': lazy_gettext('Which tab opens first in the zone and facility modals. The device modal has no tabs.')
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
            # 구획(plot) — **도형 그룹에 둔다.** 예전에는 맨 위 기본 영역에
            # 혼자 있었는데, 구획도 지도에 그려지는 도형이라 사람이 그것을
            # 여기서 찾는다(대지·구역·시설과 같은 줄에 있어야 "무엇을 그릴까"
            # 를 한 번에 정한다).
            #
            # 기본값이 이 그룹의 다른 것들과 다르다(True) — 구획은 그리라고
            # 만든 것이라 켜 두고, 라벨만 줌 게이트로 접는다.
            #
            # ⚠ 옛 id 는 `show_vegetation` 이었다(p6_44 전). 이미 저장된 위젯
            # 설정은 그 키로 남아 있으므로 **클라이언트가 둘 다 읽는다** — 새
            # 키만 보면 일부러 꺼 둔 사람의 레이어가 업그레이드에서 조용히
            # 다시 켜진다.
            'id': 'show_plots',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Plot Shape'),
            'phrase': lazy_gettext(
                'Show plots (what is where) on the map. '
                'Plot labels appear when zoomed in.'
            )
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
    {#- 이름은 셸이 렌더한다. 여기는 제목줄 오른쪽 도구만. -#}
    <div class="widget-map-controls" id="widget-map-controls-{{each_widget.unique_id}}">
        {#- ⚠ 이 두 버튼의 이름표(title)와 아이콘 상태는 눌릴 때마다
            `aot-map-widget-vector.js` 가 다시 쓴다(`_wire(btnLock…)`).
            그래서 여기서 `aria-label` 을 따로 주면 눌린 뒤 값이 어긋난다 —
            이름표 일원화는 그 JS(번들 재빌드 필요)와 함께 다뤄야 한다.
            같은 이유로 hide 상태의 흐림도 JS 가 인라인으로 넣는 값을 따른다. -#}
        <a class="aot-w-tool widget-map-ctrl-btn"
           id="tool-lock-{{each_widget.unique_id}}"
           role="button" tabindex="0"
           data-locked="{{ 'true' if widget_variables.get('map_locked', False) else 'false' }}"
           title="{{ _('Unlock Map') if widget_variables.get('map_locked', False) else _('Lock Map') }}">
            <i class="fas fa-{{ 'lock' if widget_variables.get('map_locked', False) else 'unlock' }}"></i>
        </a>
        <a class="aot-w-tool widget-map-ctrl-btn"
           id="tool-hide-{{each_widget.unique_id}}"
           role="button" tabindex="0"
           data-hidden="{{ 'true' if widget_variables.get('hide_controls', False) else 'false' }}"
           title="{{ _('Show Controls') if widget_variables.get('hide_controls', False) else _('Hide Controls') }}">
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
