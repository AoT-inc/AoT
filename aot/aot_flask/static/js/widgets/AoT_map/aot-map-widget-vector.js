/**
 * aot-map-widget-vector.js
 * Pure MapLibre GL-based AoT Map Widget
 * Leaflet-free implementation with full 3D support
 * 
 * @version 3.0.1 (Pure MapLibre, AoTMapPopup)
 * @requires maplibre-gl.js
 */

(function() {
    'use strict';

    /**
     * Initialize Pure MapLibre Map Widget
     * @param {string} uniqueId - Widget unique identifier
     */
    // Inject .aot-type-hidden CSS rule once — independent of Python template caching
    if (!document.getElementById('aot-type-hidden-style')) {
        var _styleEl = document.createElement('style');
        _styleEl.id = 'aot-type-hidden-style';
        _styleEl.textContent = '.aot-type-hidden { display: none !important; }';
        document.head.appendChild(_styleEl);
    }

    window.initAoTMapVectorWidget = async function(uniqueId) {

        // Get widget data from embedded JSON
        const varsEl = document.getElementById('aot-map-vars-' + uniqueId);
        if (!varsEl) {
            return;
        }

        let vars;
        try {
            vars = JSON.parse(varsEl.textContent);
        } catch (e) {
            return;
        }

        const mapId = vars.mapId || 'aot-map-' + uniqueId;
        const mapContainer = document.getElementById(mapId);
        if (!mapContainer) {
            return;
        }

        const canvasId = mapId + '-canvas';
        let canvas = document.getElementById(canvasId);
        if (!canvas) {
            canvas = document.createElement('div');
            canvas.id = canvasId;
            canvas.style.width = '100%';
            canvas.style.height = '100%';
            mapContainer.appendChild(canvas);
        }

        // Get geo config from global or vars
        const geoConfig = vars.geoConfig || window.AOT_GEO_CONFIG || {};
        const settings = geoConfig.settings || geoConfig;

        // Widget custom_options — vars.vars == widget_variables from generate_page_variables_logic
        const wOpts = (vars && vars.vars) || {};

        // Extract configuration — widget custom_options take precedence over global defaults
        const defaultLat = parseFloat(wOpts.fallback_latitude) || parseFloat(settings.default_lat) || 37.5665;
        const defaultLng = parseFloat(wOpts.fallback_longitude) || parseFloat(settings.default_lng) || 126.978;
        const defaultZoom = parseFloat(wOpts.default_zoom) || parseFloat(settings.zoom) || 12;
        const maxZoom = parseInt(settings.max_zoom) || 22;
        const defaultPitch = parseFloat(wOpts.default_pitch) || parseFloat(vars.default_pitch) || 0;
        const defaultBearing = parseFloat(wOpts.default_bearing) || parseFloat(vars.default_bearing) || 0;

        // Get layers from config
        const layers = vars.layers || settings.layers || geoConfig.layers || [];
        const activeLayers = vars.active_layers || [];

        // Find vector base layer — map_style_url custom option overrides geoConfig
        const vectorLayers = layers.filter(l => l.type === 'vector');
        const _selectedBase = wOpts.selected_base_layer || '';
        const _selectedVectorLayer = _selectedBase
            ? vectorLayers.find(l => l.name === _selectedBase)
            : null;
        const baseStyleUrl = wOpts.map_style_url
            || (_selectedVectorLayer && _selectedVectorLayer.url ? _selectedVectorLayer.url
                : (vectorLayers.length > 0 ? vectorLayers[0].url : 'https://demotiles.maplibre.org/style.json'));

        // Create MapLibre map
        if (typeof maplibregl === 'undefined') {
            return;
        }

        const map = new maplibregl.Map({
            container: canvasId,
            style: baseStyleUrl,
            center: [defaultLng, defaultLat],
            zoom: defaultZoom,
            maxZoom: maxZoom,
            pitch: defaultPitch,
            bearing: defaultBearing,
            attributionControl: false
        });

        // 전역 가드: 빈/잘못된 타일 URL 의 raster 소스 추가를 거부한다.
        // tiles:[''] 같은 소스는 MapLibre 워커가 보이는 타일마다 빈 URL 을
        // 요청하고, 빈 URL 은 '현재 페이지'(대시보드 HTML ~1.3MB)로 해소되어
        // 타일 수만큼 페이지를 재요청한다 → gunicorn 워커 풀 포화 → 구역 칩
        // 클릭 등 사용자 요청이 수 초간 큐에 밀린다. 모든 addSource 호출이
        // 이 인스턴스 메서드를 거치므로 단일 지점에서 차단한다.
        (function (m) {
            if (!m || typeof m.addSource !== 'function' || m._aotSrcGuarded) return;
            m._aotSrcGuarded = true;
            const _add = m.addSource.bind(m);
            const _validTileUrl = function (u) {
                return typeof u === 'string' && u.trim() &&
                    ((u.indexOf('{z}') !== -1 && u.indexOf('{x}') !== -1 &&
                      (u.indexOf('{y}') !== -1 || u.indexOf('{-y}') !== -1)) ||
                     u.toLowerCase().indexOf('{bbox') !== -1);
            };
            m.addSource = function (id, src) {
                try {
                    if (src && (src.type === 'raster' || src.type === 'raster-dem') &&
                        Array.isArray(src.tiles) &&
                        (!src.tiles.length || !src.tiles.every(_validTileUrl))) {
                        console.warn('[AoTMap] addSource blocked — invalid/empty raster tiles:',
                            id, JSON.stringify(src.tiles));
                        return m;
                    }
                } catch (e) { /* fall through to native */ }
                return _add(id, src);
            };
        })(map);

        // Apply lock state immediately — before 'load' fires — so interactions are
        // disabled during tile/style loading, not just after the map is fully ready.
        if (vars.isLocked) {
            ['dragPan', 'scrollZoom', 'boxZoom', 'doubleClickZoom', 'touchZoomRotate', 'keyboard'].forEach(function(h) {
                if (map[h]) { try { map[h].disable(); } catch (_) {} }
            });
        }

        // Suppress missing-sprite-image warnings by providing a 1x1 transparent placeholder
        map.on('styleimagemissing', function(e) {
            map.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) });
        });

        // Add attribution control
        map.addControl(new maplibregl.AttributionControl({
            compact: true,
            position: 'bottom-left'
        }), 'bottom-left');

        // NOTE: native NavigationControl removed — its top-right placement
        // overlapped the new .map-tools-right toolbar (Layers/Note/Measure)
        // and intercepted clicks. Zoom +/- now lives in the left tool-group.
        // The compass button is injected into the left tool-group by
        // addControlButtons() so pitch-rotation is still available.

        // Add scale control
        map.addControl(new maplibregl.ScaleControl({
            maxWidth: 100,
            unit: 'metric'
        }), 'bottom-left');

        // Store widget instance
        window.AoTWidgetInstances = window.AoTWidgetInstances || {};
        window.AoTWidgetInstances[uniqueId] = {
            uniqueId: uniqueId,
            map: map,
            vars: vars,
            markers: new Map(),
            shapes: new Map(),
            sources: new Map(),
            layers: new Map()
        };

        const instance = window.AoTWidgetInstances[uniqueId];

        // Seed persisted label-hidden state NOW, before any label/marker renderer
        // runs (loadGeoJSONLayers below creates facility bay chips, geo-design
        // labels, and device markers — all well before addLayerPanel's toolbar
        // would otherwise seed this same state). See _seedHiddenLabelsEarly.
        _seedHiddenLabelsEarly(uniqueId, vars);

        // Label layer registry skeleton (rank x pin presets). P1: init only —
        // renderers register entries in a later phase. Reading the toggle here so
        // the preset choice is bound up front.
        instance._labelFacilityCentric = wOpts.label_priority_facility === true
            || wOpts.label_priority_facility === 'true';
        if (window.AoTMapLabelLayers) {
            try {
                window.AoTMapLabelLayers.init(uniqueId, { facilityCentric: instance._labelFacilityCentric });
            } catch (e) {}
        }

        // Kick off LOCAL /api/geo/* fetches NOW, in parallel with the EXTERNAL
        // basemap style/sprite/glyph download — instead of waiting for the map
        // 'load' event. The 'load' event only fires after the tile CDN's style +
        // sprite (~591KB) + glyph fonts finish (~2.2s), which previously held all
        // local geo data hostage to CDN latency. loadGeoJSONLayers() consumes
        // these prefetched responses transparently via geoFetch() once 'load'
        // fires, so render order/logic below is unchanged — only timing moves up.
        try {
            const _prefetchMapUuid = wOpts.selected_map_uuid || wOpts.map_uuid || (vars && vars.contentMapUuid) || '';
            prefetchGeoLayers(wOpts, _prefetchMapUuid, (vars && vars.contentMapUuid) || '');
        } catch (e) {}

        // Initialize when style is loaded
        map.on('load', async function() {
            // Ensure canvas is visible and sized correctly.
            // map.resize() must always run: the canvas may have been initialised
            // at a small placeholder size (e.g. 61×300 px) and needs to expand to
            // the real container dimensions before the render loop starts.
            try {
                const cv = map.getCanvas();
                if (cv && cv.style.display === 'none') {
                    cv.style.display = ''; // un-hide if a rogue script hid it
                }
                map.resize(); // always resize — container may have grown since map init
            } catch (_) {}

            // Snapshot the TECHNICAL base style's own layer ids (background, water,
            // roads, etc.) before anything else is added to the map. _hideAllVectorBase/
            // _showAllVectorBase (used when a raster base like VWorld is activated) rely
            // on this list to hide only the underlying vector engine — capturing it later
            // (e.g. inside addLayerPanel, after loadGeoJSONLayers has already run) would
            // pick up shape/label layer ids too and hide zones/sites/devices whenever a
            // raster base is switched in.
            map._aotBaseStyleIds = ((map.getStyle() || {}).layers || []).map(function(l) { return l.id; });

            // Initialize VectorLayerManager (bind only). Overlay raster layers are
            // added AFTER shapes/labels (below) so the overlay map (오버레이지도)
            // stacks ON TOP of the drawn shape fill/line layers.
            // Load order: 베이스지도 → 도형/라벨/키 → 오버레이지도.
            if (window.AoTVectorLayerManager && typeof window.AoTVectorLayerManager.init === 'function') {
                window.AoTVectorLayerManager.init(map);
            }

            // Add GeoJSON layers for sites/zones/devices
            await loadGeoJSONLayers(uniqueId, map, vars);

            // Add geo/design labels (label_aux markers)
            await loadGeoDesignLabels(uniqueId, map, vars);

            // Overlay raster layers (오버레이지도, e.g. soil-info WMS) are added
            // LAST and DEFERRED — see the map.once('idle') block after the legend.
            // They stream heavy raster tiles through the WMS proxy; adding them here
            // (before shapes/labels/keys finish rendering) made a cold/uncached load
            // feel slow because the soil overlay competed with shape/label rendering.

            // 3D terrain (enable_3d_terrain custom option)
            const _wOpts = (vars && vars.vars) || {};
            if (_wOpts.enable_3d_terrain === true || _wOpts.enable_3d_terrain === 'true') {
                try {
                    if (!map.getSource('mapbox-dem')) {
                        map.addSource('mapbox-dem', { type: 'raster-dem', url: 'https://demotiles.maplibre.org/terrain-tiles/tiles.json', tileSize: 256 });
                    }
                    map.setTerrain({ source: 'mapbox-dem', exaggeration: 1.5 });
                } catch (e) { }
            }

            // Load device markers: async if async_devices=true (default), sync fallback
            const _wOpts3 = (vars && vars.vars) || {};
            if (_wOpts3.async_devices === true || _wOpts3.async_devices === 'true' || _wOpts3.async_devices === undefined) {
                fetchAndRenderDevices(uniqueId, map, vars);
            } else if (vars.devices && vars.devices.length > 0) {
                addDeviceMarkers(uniqueId, map, vars.devices, vars.theme, vars);
            }

            // Restore widget UI: control buttons, measurement panel, overlay legend
            try { addControlButtons(uniqueId, map, vars); } catch (e) {
                console.warn('[AoT Map] addControlButtons failed:', e);
            }
            try { addMeasurementPanel(uniqueId, map, vars); } catch (e) {
                console.warn('[AoT Map] addMeasurementPanel failed:', e);
            }
            // Layer panel (top-right unified toolbar: Layers + Measure + Note).
            // Must come before addLegendOverlay so legend can reference the layer panel's update hook.
            try { addLayerPanel(uniqueId, map, vars); } catch (e) {
                console.warn('[AoT Map] addLayerPanel failed:', e);
            }
            // Legend — uses initial active_layers; also wired to layer panel changes.
            try { addLegendOverlay(uniqueId, map, vars); } catch (e) {
                console.warn('[AoT Map] addLegendOverlay failed:', e);
            }

            // ── Overlay raster layers (오버레이지도, e.g. soil-info WMS) — DEFERRED ──
            // Load order requested: 베이스지도 → 도형 → 라벨 → 키 → 오버레이지도.
            // Shapes/labels/keys are all set up above (synchronously). We now wait for
            // the map to go 'idle' (base map + shape layers finished rendering) before
            // adding the heavy WMS overlay tiles, so the user sees shapes/labels/keys
            // immediately and the soil overlay streams in afterward instead of competing
            // with them. Added last → still stacks on top (z-order preserved).
            // A fallback timer covers the case where 'idle' is delayed by continuous
            // base-tile loading on a slow network.
            if (window.AoTVectorLayerManager && typeof window.AoTVectorLayerManager.addLayer === 'function') {
                let _overlaysAdded = false;
                const _addOverlayLayers = function () {
                    if (_overlaysAdded) return;
                    _overlaysAdded = true;
                    for (const layerConfig of layers) {
                        if (layerConfig.enabled !== false) {
                            try {
                                window.AoTVectorLayerManager.addLayer(layerConfig);
                            } catch (e) {
                            }
                        }
                    }
                };
                try { map.once('idle', _addOverlayLayers); } catch (e) { _addOverlayLayers(); }
                setTimeout(_addOverlayLayers, 1500);
            }
            // Note markers (port of v3 raster widget renderMapNotes).
            try { startMapNotesPolling(uniqueId, map, vars.refreshSeconds); } catch (e) {
            }
            // Site list rehydration from /api/geo/overlays (port of v3:744-813).
            try { refreshSiteList(uniqueId, map, vars); } catch (e) {
            }
            // Apply global panel transparency after all panels are created.
            try { applyPanelOpacity(uniqueId, vars); } catch (e) {
            }
            // Compact mode: adapt toolbars/panels to small widget heights so
            // the widget never needs internal scrolling.
            try { setupCompactMode(uniqueId, map, vars); } catch (e) {
            }
        });

        // Handle errors — tile decode failures (e.g. WMS service exception returned as
        // XML/HTML) are downgraded to warnings so the console stays clean.
        map.on('error', function(e) {
            const msg = (e && e.error && e.error.message) || '';
            // Tile-level HTTP errors (404/410) and image decode failures are expected
            // for optional overlay layers — downgrade to warn to keep console clean.
            if (msg.indexOf('decode') !== -1 || msg.indexOf('source image') !== -1 ||
                msg.indexOf('410') !== -1 || msg.indexOf('404') !== -1 ||
                (e && e.tile)) {
            } else {
            }
        });

        // Persist view state (center, zoom, pitch, bearing) after user interaction
        let _viewSaveTimer;
        map.on('moveend', function() {
            clearTimeout(_viewSaveTimer);
            _viewSaveTimer = setTimeout(function() {
                const widgetId = (vars && vars.widgetId) || uniqueId;
                const center = map.getCenter();
                fetch('/save_widget_custom_options', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        widget_id: widgetId,
                        options: {
                            fallback_latitude:  center.lat.toFixed(6),
                            fallback_longitude: center.lng.toFixed(6),
                            default_zoom:       map.getZoom().toFixed(2),
                            default_pitch:      Math.round(map.getPitch()),
                            default_bearing:    Math.round(map.getBearing())
                        }
                    })
                }).catch(function(e) { })
            }, 1000);
        });

        // Refresh handler
        if (vars.refreshSeconds > 0) {
            setupRefresh(uniqueId, vars.refreshSeconds);
        }
        // Expose a live refresh-interval setter so the settings modal can apply the
        // `period` option immediately (auto-save + live) instead of on reload.
        try {
            var _refInst = window.AoTWidgetInstances[uniqueId];
            if (_refInst) { _refInst._setupRefresh = function (s) { setupRefresh(uniqueId, s); }; }
        } catch (e) {}

    };

    // ──────────────────────────────────────────────────────────────────────
    // Geo data fetch — delegates GET requests to the shared window.AoTGeoData
    // provider (in-flight dedup + short-TTL parsed-JSON cache) so that N map
    // widgets pointing at the same map issue ONE request per endpoint instead
    // of N. Returns a Response-like shim ({ ok, status, json() }); callers use
    // res.ok / await res.json() unchanged. Falls back to raw fetch() when the
    // provider is missing or the call is a non-GET.
    // ──────────────────────────────────────────────────────────────────────
    function geoFetch(url, opts) {
        const isGet = !opts || !opts.method || String(opts.method).toUpperCase() === 'GET';
        if (isGet && window.AoTGeoData) {
            return window.AoTGeoData.get(url);
        }
        return fetch(url, opts);
    }
    function prefetchGeoLayers(wOpts, mapUuid, labelMapUuid) {
        function on(key) { const v = wOpts[key]; return v === true || v === 'true' || v === 1; }
        const urls = [];
        if (on('show_site_shape')) urls.push('/api/geo/sites?format=geojson');
        if (on('show_zone_shape')) urls.push('/api/geo/zones?format=geojson');
        // Labels (label_aux markers) — loadGeoDesignLabels keys off vars.contentMapUuid,
        // which may differ from the shape mapUuid; prefetch so labels render early too.
        if (labelMapUuid && (on('show_site_label') || on('show_zone_label') || on('show_device_labels'))) {
            urls.push('/api/geo/overlays?map_uuid=' + encodeURIComponent(labelMapUuid) + '&type=label_aux');
        }
        if (mapUuid) {
            const mu = encodeURIComponent(mapUuid);
            if (on('show_facility_shape')) {
                urls.push('/api/geo/overlays?map_uuid=' + mu + '&type=facility');
                if (window.AoTFacilityMap3D && window.AoTFacility3D) {
                    urls.push('/api/geo/facility/list?geo_id=' + mu);
                }
            }
            if (on('show_equipment_shape')) urls.push('/api/geo/overlays?map_uuid=' + mu + '&type=equipment');
            if (on('show_device_shapes'))   urls.push('/api/geo/overlays?map_uuid=' + mu + '&type=aot_device');
            // Untyped overlays — consumed by drawn-shapes (loadGeoJSONLayers) and
            // refreshSiteList; prefetched unconditionally since refreshSiteList runs always.
            urls.push('/api/geo/overlays?map_uuid=' + mu);
        }
        // Warm the shared provider's cache; geoFetch() consumers reuse it.
        // Across instances this collapses to one request per unique URL.
        if (window.AoTGeoData) {
            window.AoTGeoData.prefetch(urls);
        } else {
            urls.forEach(function(u) { try { fetch(u); } catch (e) {} });
        }
    }

    /**
     * Load GeoJSON layers (sites, zones, devices)
     */
    async function loadGeoJSONLayers(uniqueId, map, vars) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        const wOpts = (vars && vars.vars) || {};
        function _boolOpt(key) {
            const v = wOpts[key];
            return v === true || v === 'true' || v === 1;
        }
        function _sensorLabelOpts(_vars) {
            const o = ((_vars && _vars.vars) || wOpts) || {};
            return {
                show:         o.show_sensor_labels !== false && o.show_sensor_labels !== 'false',
                style:        o.sensor_label_style || 'circle',
                max_channels: parseInt(o.sensor_label_max_channels || 1, 10),
                decimals:     parseInt(o.sensor_label_decimals != null ? o.sensor_label_decimals : 1, 10),
                size_em:      parseFloat(o.sensor_label_size || 0.85),
                bg:           o.sensor_label_bg || 'rgba(15,23,42,0.78)',
                fg:           o.sensor_label_fg || '#f8fafc',
                offset_y:     parseFloat(o.sensor_label_offset_y || 0),
                opacity:      o.sensor_label_opacity != null ? parseFloat(o.sensor_label_opacity) : 0.7,
                popup:        o.sensor_popup_enabled !== false && o.sensor_popup_enabled !== 'false',
                // Label collision avoidance (keep spacing instead of hiding) — uses the custom_option 'label_spacing' px.
                collision:    o.enable_label_collision !== false && o.enable_label_collision !== 'false',
                spacing:      (function () { var s = parseInt(o.label_spacing, 10); return isNaN(s) ? 0 : s; })(),
                refresh_seconds: parseInt(o.period || 60, 10),
                // Stacking priority vs geo-design labels (ZINDEX_MAP: site=3, zone=2,
                // facility=5, device=6). Without a z-index the sensor (facility key)
                // labels fall UNDER zone labels. Facility-centric → above device (7);
                // outdoor → below site (1). This makes the toggle visibly reorder them.
                priority_z:   ((o.label_priority_facility === true || o.label_priority_facility === 'true') ? 7 : 1)
            };
        }

        // ── Actuator category labels (map markers + popup controls) ────────────
        // Categories: envelope (curtain/shade), window (opening), water (irrigation), facility (everything else)
        var _actLabelState = {};  // uid -> { markers[], pollTimer, popup, facilities, states }

        // ── Zone modal ────────────────────────────────────────────────────────
        // uid -> { popup, zoneUuid, _sensors, overlayOutputId, overlayOutputName, _histCache }
        var _zonePopupState = {};
        var _ZONE_HIST_CACHE_MS = 60000;

        function _zoneCanCtrl(uid) {
            var st = uid && _actLabelState[uid];
            if (st) return !!st.canCtrl;
            return _boolOpt('can_control');
        }

        function _escZ(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        function _tr(s) { return (window._ ? window._(s) : s); }

        function _buildZoneSkel() {
            return '<div class="aot-ov-skel">' +
                '<div class="aot-ov-skel-bar w60"></div>' +
                '<div class="aot-ov-skel-bar w80"></div>' +
                '<div class="aot-ov-skel-bar w40"></div>' +
                '</div>';
        }

        function _buildZonePopupHTML(zoneName, defSec) {
            // defSec: initial active zone tab (zoverview / zdevices / zfunctions),
            // mapped from the widget's popup_default_tab in _openZonePopup.
            defSec = (defSec === 'zdevices' || defSec === 'zfunctions') ? defSec : 'zoverview';
            function _zNav(sec, label) {
                return '<button type="button" class="aot-act-tab-btn' +
                    (sec === defSec ? ' active' : '') + '" data-sec="' + sec + '">' + label + '</button>';
            }
            function _zPane(sec, inner) {
                return '<div class="aot-bay-popup-pane" data-pane="' + sec + '"' +
                    (sec === defSec ? '' : ' style="display:none"') + '>' + inner + '</div>';
            }
            return '<div class="aot-sensor-popup-header">' +
                       '<span class="aot-sensor-popup-title">' + _escZ(zoneName || _tr('Zone')) + '</span>' +
                   '</div>' +
                   '<div class="aot-act-tabs-nav aot-bay-popup-nav">' +
                       _zNav('zoverview', _tr('Status')) +
                       _zNav('zdevices', _tr('Environment & Control')) +
                       _zNav('zfunctions', _tr('Functions')) +
                   '</div>' +
                   _zPane('zoverview', _buildZoneSkel()) +
                   _zPane('zdevices', '') +
                   _zPane('zfunctions', '');
        }

        // [현황] 탭 — 사진 + 구역 정보 + 노트
        function _renderZoneOverview(uid, pane, data, zoneUuid) {
            var z = data.zone || {};
            if (!window.AoTMapPopup) { return; }
            pane.innerHTML = window.AoTMapPopup.buildZoneOverviewHtml(z);

            // 사진 업로드 wiring
            var phBtn = pane.querySelector('.aot-ov-photo-btn');
            var phInput = pane.querySelector('.aot-ov-photo-input');
            if (phBtn && phInput) {
                phBtn.addEventListener('click', function () { phInput.click(); });
                phInput.addEventListener('change', function () {
                    if (!phInput.files || !phInput.files[0]) return;
                    var fd = new FormData();
                    fd.append('photo', phInput.files[0]);
                    phBtn.disabled = true;
                    fetch('/api/geo/zone/' + encodeURIComponent(zoneUuid) + '/photo', {
                        method: 'POST',
                        headers: { 'X-CSRFToken': _csrfHeader() },
                        body: fd
                    })
                    .then(function (r) { return r.json(); })
                    .then(function (j) {
                        phBtn.disabled = false;
                        if (!j.ok) return;
                        var img = pane.querySelector('.aot-ov-photo img');
                        if (img) {
                            img.src = j.photo_url;
                        } else {
                            // 사진 블록이 없던 경우 — 전체 개요 재렌더
                            fetch('/api/geo/zone/' + encodeURIComponent(zoneUuid) + '/contents')
                                .then(function (r) { return r.ok ? r.json() : null; })
                                .then(function (d) {
                                    if (d && d.ok) _renderZoneOverview(uid, pane, d, zoneUuid);
                                })
                                .catch(function () {});
                        }
                    })
                    .catch(function () { phBtn.disabled = false; });
                });
            }

            // 노트 패널 열기 함수
            var zoneName = z.name || '';
            function _openZoneNotesPanel() {
                var z2 = _zonePopupState[uid];
                if (z2 && z2.popup) {
                    try { z2.popup.remove(); } catch (e) {}
                }
                window.dispatchEvent(new CustomEvent('open-notes', {
                    detail: { targetId: zoneUuid, targetType: 'GeoShape', name: zoneName }
                }));
            }

            var noteBtn = pane.querySelector('.aot-ov-notes-open');
            if (noteBtn) noteBtn.addEventListener('click', _openZoneNotesPanel);

            // 노트 목록 비동기 채움
            var notesList = pane.querySelector('.aot-ov-notes-list');
            if (notesList) {
                fetch('/notes/target/' + encodeURIComponent(zoneUuid))
                    .then(function (r) { return r.ok ? r.json() : []; })
                    .then(function (notes) {
                        if (!pane.isConnected) return;
                        window.AoTMapPopup.fillOverviewNotes(notesList, notes, _openZoneNotesPanel);
                    })
                    .catch(function () {});
            }
        }

        // 현재 보이는 센서 차트 div 반환 (zdevices pane 내)
        function _zoneActiveChartDiv(popupEl) {
            var devPane = popupEl.querySelector('.aot-bay-popup-pane[data-pane="zdevices"]');
            if (!devPane) return null;
            var charts = devPane.querySelectorAll('.aot-bay-sensor-chart');
            for (var i = 0; i < charts.length; i++) {
                if (charts[i].style.display !== 'none') return charts[i];
            }
            return null;
        }

        // 장치 이력 fetch (캐시 포함)
        function _fetchZoneOutputHistory(uid, outputId) {
            var z = _zonePopupState[uid];
            if (!z) return Promise.resolve(null);
            z._histCache = z._histCache || {};
            var cached = z._histCache[outputId];
            if (cached && (Date.now() - cached.ts) < _ZONE_HIST_CACHE_MS) {
                return Promise.resolve(cached.data);
            }
            var zoneUuid = z.zoneUuid;
            return fetch('/api/geo/zone/' + encodeURIComponent(zoneUuid) +
                         '/output_history?output_id=' + encodeURIComponent(outputId))
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (d && d.ok) {
                        var z2 = _zonePopupState[uid];
                        if (z2) z2._histCache[outputId] = { ts: Date.now(), data: d };
                    }
                    return d;
                })
                .catch(function () { return null; });
        }

        // 선택된 장치 행 하이라이트
        function _markZoneOverlayRow(devPane, outputId) {
            if (!devPane) return;
            devPane.querySelectorAll('.aot-act-row[data-slot]').forEach(function (r) {
                r.classList.toggle('aot-act-row--selected', !!outputId && r.dataset.slot === outputId);
            });
        }

        // 현재 보이는 차트에 선택된 오버레이 (재)적용 — 차트가 아직 렌더 중이면 재시도
        function _reapplyZoneOverlay(uid, popupEl, attempt) {
            var z = _zonePopupState[uid];
            if (!z || !z.overlayOutputId) return;
            var outputId = z.overlayOutputId;
            var div = _zoneActiveChartDiv(popupEl);
            if (!div || !div._aotChart) {
                attempt = attempt || 0;
                if (attempt < 20) {
                    setTimeout(function () {
                        var z2 = _zonePopupState[uid];
                        if (z2 && z2.overlayOutputId === outputId) {
                            _reapplyZoneOverlay(uid, popupEl, attempt + 1);
                        }
                    }, 250);
                }
                return;
            }
            _fetchZoneOutputHistory(uid, outputId).then(function (hist) {
                var z2 = _zonePopupState[uid];
                if (!z2 || z2.overlayOutputId !== outputId || !hist || !hist.ok) return;
                _applyOverlaySeries(div, hist, z2.overlayOutputName || outputId);
            });
        }

        // 독립 장치 이력 차트 렌더 (센서 없을 때 — 행 아래 토글)
        function _renderZoneDeviceChart(div, hist, name) {
            if (!window.Highcharts) { return; }
            var isOnOff = hist.series_type === 'onoff';
            var pts = (hist.points || []).map(function (p) {
                return [p[0] * 1000, p[1]];
            }).sort(function (a, b) { return a[0] - b[0]; });
            if (!pts.length) {
                div.innerHTML = '<span class="aot-ov-muted" style="padding:8px;display:block">' +
                                _tr('No data') + '</span>';
                return;
            }
            requestAnimationFrame(function () {
                var w = div.offsetWidth || 280;
                var h = Math.max(120, Math.min(200, Math.round(w * 0.46)));
                if (window.AoTChart && window.AoTChart.applyGlobalDefaults) {
                    window.AoTChart.applyGlobalDefaults();
                }
                try {
                    div._aotChart = window.Highcharts.stockChart(div, {
                        chart: { height: h, spacing: [4, 4, 4, 4] },
                        rangeSelector: { enabled: false },
                        navigator: { enabled: false },
                        scrollbar: { enabled: false },
                        credits: { enabled: false },
                        exporting: { enabled: false },
                        legend: { enabled: false },
                        xAxis: { type: 'datetime',
                                 labels: { style: { fontSize: '9px' } } },
                        yAxis: { min: 0, title: { text: null },
                                 labels: {
                                     enabled: true,
                                     style: { fontSize: '9px' },
                                     formatter: isOnOff
                                         ? function () { return this.value + 'm'; }
                                         : function () { return this.value + '%'; }
                                 }, gridLineWidth: 1 },
                        tooltip: { valueDecimals: 1,
                                   valueSuffix: isOnOff ? (' ' + _tr('min')) : ' %' },
                        series: [{
                            name: name,
                            type: isOnOff ? 'column' : 'line',
                            step: isOnOff ? undefined : 'left',
                            data: pts,
                            maxPointWidth: isOnOff ? 3 : undefined,
                            borderWidth: isOnOff ? 0 : undefined,
                            color: '#4a90d9'
                        }]
                    });
                } catch (e) {}
            });
        }

        // 장치 이름 클릭 → 이력 오버레이 on/off
        // - 센서 차트 있을 때: 센서 차트에 오버레이 (facility 동일)
        // - 센서 없을 때: 장치 행 아래 독립 차트 토글
        function _selectZoneOutputOverlay(uid, popupEl, outputId, outputName) {
            var z = _zonePopupState[uid];
            if (!z) return;
            var devPane = popupEl.querySelector('.aot-bay-popup-pane[data-pane="zdevices"]');
            var sensorChart = _zoneActiveChartDiv(popupEl);

            if (sensorChart) {
                // ── 센서 차트 오버레이 모드 ──
                if (z.overlayOutputId === outputId) {
                    z.overlayOutputId = null;
                    z.overlayOutputName = null;
                    var chart = sensorChart._aotChart;
                    if (chart) {
                        try { var s = chart.get('aot-act-overlay'); if (s) s.remove(); } catch (e) {}
                        try { var ax = chart.get('aot-act-axis'); if (ax) ax.remove(); } catch (e) {}
                    }
                    _markZoneOverlayRow(devPane, null);
                } else {
                    z.overlayOutputId = outputId;
                    z.overlayOutputName = outputName;
                    _reapplyZoneOverlay(uid, popupEl);
                    _markZoneOverlayRow(devPane, outputId);
                }
            } else {
                // ── 고정 차트 영역 모드 (센서 없음) ──
                var chartFixed = devPane && devPane.querySelector('.aot-zone-dev-chart-fixed');
                if (!chartFixed) return;

                if (z.overlayOutputId === outputId) {
                    // 재클릭 → 차트 제거 (토글 off), 그래프 영역 자체는 계속 확보
                    if (chartFixed._aotChart) { try { chartFixed._aotChart.destroy(); } catch (e) {} chartFixed._aotChart = null; }
                    chartFixed.style.display = 'flex';
                    chartFixed.innerHTML = '<span class="aot-ov-muted">' + _tr('Select a device below to view its history') + '</span>';
                    z.overlayOutputId = null;
                    z.overlayOutputName = null;
                    _markZoneOverlayRow(devPane, null);
                } else {
                    // 새 장치 선택 → 고정 차트 영역에 렌더
                    if (chartFixed._aotChart) { try { chartFixed._aotChart.destroy(); } catch (e) {} chartFixed._aotChart = null; }
                    chartFixed.innerHTML = '';
                    chartFixed.style.display = 'block';
                    z.overlayOutputId = outputId;
                    z.overlayOutputName = outputName;
                    _markZoneOverlayRow(devPane, outputId);
                    _fetchZoneOutputHistory(uid, outputId).then(function (hist) {
                        var z2 = _zonePopupState[uid];
                        if (!z2 || z2.overlayOutputId !== outputId) return;
                        if (!hist || !hist.ok) {
                            chartFixed.innerHTML = '<span class="aot-ov-muted" style="padding:8px;display:block">' +
                                                   _tr('No data') + '</span>';
                            return;
                        }
                        _renderZoneDeviceChart(chartFixed, hist, outputName);
                    });
                }
            }
        }

        // 센서 탭 활성화 + 지연 렌더 (facility _activateBaySensorTab 과 동일 패턴)
        function _activateZoneSensorTab(uid, devPane, sensorIdx) {
            var z = _zonePopupState[uid];
            if (!z || !devPane) return;
            var sensorSec = devPane.querySelector('.aot-zone-sensor-sec');
            if (!sensorSec) return;

            sensorSec.querySelectorAll('.aot-act-tab-btn[data-sensor-idx]').forEach(function (b) {
                b.classList.toggle('active', parseInt(b.dataset.sensorIdx, 10) === sensorIdx);
            });
            sensorSec.querySelectorAll('.aot-bay-sensor-chart').forEach(function (div) {
                var idx = parseInt(div.dataset.sensorIdx, 10);
                var on = idx === sensorIdx;
                div.style.display = on ? '' : 'none';
                if (on && div.dataset.rendered !== '1') {
                    div.dataset.rendered = '1';
                    var sensors = z._sensors || [];
                    var s = sensors[idx];
                    if (s && s.channels && s.channels.length && window.AoTSensorLabel) {
                        var sObj = {
                            device_id: s.unique_id,
                            name: s.name,
                            fitting_id: s.unique_id,
                            channels: s.channels.map(function (c) {
                                return { measurement_id: c.measurement_id, key: c.key,
                                         measurement_type: c.measurement_type, unit: c.unit,
                                         value: null, stale: false };
                            })
                        };
                        window.AoTSensorLabel.renderHistory(div, [sObj], {});
                    }
                }
            });

            // 차트가 바뀌면 오버레이 재적용
            var popupEl = devPane.closest('.maplibregl-popup-content');
            if (popupEl) _reapplyZoneOverlay(uid, popupEl);
        }

        // [센서·장치] 탭 렌더
        function _renderZoneDevices(uid, pane, data, zoneUuid) {
            var canCtrl = _zoneCanCtrl(uid);
            var z = _zonePopupState[uid] || {};
            var outputOrder = (data.zone && data.zone.output_order) || [];
            var sensors = z._sensors || [];
            var html = '';

            // 단일 차트 영역 — 센서 있으면 센서 차트, 없으면 장치 선택 시 여기에 렌더
            html += '<div class="aot-zone-chart-area">';
            if (sensors.length) {
                var sensorTabs = sensors.length > 1
                    ? '<div class="aot-act-tabs-nav">' + sensors.map(function (s, i) {
                        return '<button type="button" class="aot-act-tab-btn' + (i === 0 ? ' active' : '') + '"' +
                               ' data-sensor-idx="' + i + '">' + _escZ(s.name) + '</button>';
                      }).join('') + '</div>'
                    : '';
                var sensorCharts = sensors.map(function (s, i) {
                    return '<div class="aot-bay-sensor-chart" data-sensor-idx="' + i + '"' +
                           (i === 0 ? '' : ' style="display:none"') + '></div>';
                }).join('');
                html += '<div class="aot-zone-sensor-sec">' + sensorTabs + sensorCharts + '</div>';
            } else {
                // 입력(센서)이 없어도 그래프 영역은 항상 확보 — 장치 선택 전에는
                // 안내 문구를 보여주고, 선택 시 _selectZoneOutputOverlay 가 이 자리에 렌더한다.
                html += '<div class="aot-zone-dev-chart-fixed" style="min-height:120px;display:flex;align-items:center;justify-content:center">' +
                        '<span class="aot-ov-muted">' + _tr('Select a device below to view its history') + '</span>' +
                        '</div>';
            }
            html += '</div>';

            // 장치 섹션 — drag ordering + name→overlay
            var outputs = data.outputs || [];
            if (outputs.length) {
                // 저장된 순서 적용
                if (outputOrder.length) {
                    var oMap = {};
                    outputs.forEach(function (o) { oMap[o.unique_id] = o; });
                    var ordered = [];
                    outputOrder.forEach(function (id) { if (oMap[id]) ordered.push(oMap[id]); });
                    outputs.forEach(function (o) { if (ordered.indexOf(o) < 0) ordered.push(o); });
                    outputs = ordered;
                }
                html += '<div class="aot-act-group-header">' + _tr('Devices') + '</div>';
                html += '<div class="aot-zone-output-list">';
                outputs.forEach(function (out) {
                    out.channels.forEach(function (ch) {
                        var rawLabel = out.channels.length > 1
                            ? out.name + ' – ' + ch.name
                            : out.name;
                        var label = _escZ(rawLabel);
                        var ctrl = canCtrl
                            ? '<label class="btn-toggle aot-act-toggle-right">' +
                              '<input type="checkbox" class="btn-toggle-input aot-zone-output-toggle"' +
                              ' data-output-id="' + _escZ(out.unique_id) + '"' +
                              ' data-channel="' + ch.channel + '">' +
                              '<span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>' +
                              '</label>'
                            : '';
                        var drag = canCtrl
                            ? '<span class="aot-act-drag-handle" title="' + _tr('Reorder') + '"><i class="fa fa-grip-lines"></i></span>'
                            : '';
                        html += '<div class="aot-act-row" data-slot="' + _escZ(out.unique_id) + '">' +
                                '<div class="aot-act-line">' +
                                drag +
                                '<span class="aot-act-name" style="cursor:pointer"' +
                                ' data-output-id="' + _escZ(out.unique_id) + '"' +
                                ' data-output-name="' + _escZ(rawLabel) + '">' +
                                label + '</span>' +
                                ctrl +
                                '</div></div>';
                    });
                });
                html += '</div>';
            } else {
                html += '<div class="aot-act-empty">' + _tr('No devices') + '</div>';
            }

            pane.innerHTML = html;

            // 드래그 정렬
            if (canCtrl && window.AoTActuatorOrder) {
                var listEl = pane.querySelector('.aot-zone-output-list');
                if (listEl) {
                    window.AoTActuatorOrder.makeSortable(listEl, {
                        handleSelector: '.aot-act-drag-handle',
                        onReorder: function (newSeq) {
                            var zUuid = (_zonePopupState[uid] || {}).zoneUuid || zoneUuid;
                            fetch('/api/geo/zone/' + encodeURIComponent(zUuid) + '/output_order', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json',
                                           'X-CSRFToken': _csrfHeader() },
                                body: JSON.stringify({ order: newSeq })
                            }).catch(function () {});
                        }
                    });
                }
            }
        }

        // [함수] 탭 렌더
        function _renderZoneFunctions(pane, data, uid) {
            var canCtrl = _zoneCanCtrl(uid);
            var funcs = data.functions || [];
            if (!funcs.length) {
                pane.innerHTML = '<div class="aot-act-empty">' + _tr('No functions') + '</div>';
                return;
            }
            var kindLabel = { 'custom': _tr('Custom'), 'function': _tr('Function'),
                'conditional': _tr('Conditional'), 'trigger': _tr('Trigger'), 'pid': 'PID' };
            var html = '';
            funcs.forEach(function (fn) {
                var kl = kindLabel[fn.kind] || fn.kind;
                var ctrl = canCtrl
                    ? '<label class="btn-toggle aot-act-toggle-right">' +
                      '<input type="checkbox" class="btn-toggle-input aot-zone-func-toggle"' +
                      ' data-func-id="' + _escZ(fn.unique_id) + '"' +
                      ' data-func-kind="' + _escZ(fn.kind) + '"' +
                      ' data-active="' + (fn.is_activated ? '1' : '0') + '"' +
                      (fn.is_activated ? ' checked' : '') + '>' +
                      '<span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>' +
                      '</label>'
                    : '<span class="aot-act-val-ro ' + (fn.is_activated ? 'aot-act-on' : 'aot-act-off') + '">' +
                      (fn.is_activated ? 'ON' : 'OFF') + '</span>';
                html += '<div class="aot-act-row">' +
                        '<div class="aot-act-line">' +
                        '<span class="aot-act-name">' + _escZ(fn.name) +
                        ' <span class="aot-act-tag">' + _escZ(kl) + '</span></span>' +
                        ctrl +
                        '</div></div>';
            });
            pane.innerHTML = html;
        }

        // 이벤트 위임 — 탭 전환·센서 탭·장치 클릭·ON/OFF·함수 토글
        function _wireZoneTabs(popupEl, uid, zoneUuid) {
            if (!popupEl || popupEl._zoneTabsWired) return;
            popupEl._zoneTabsWired = true;
            popupEl.addEventListener('click', function (e) {

                // 센서 서브탭 클릭 (facility: data-fitting, zone: data-sensor-idx)
                var sensorTabBtn = e.target.closest('.aot-act-tab-btn[data-sensor-idx]');
                if (sensorTabBtn && popupEl.contains(sensorTabBtn)) {
                    var idx = parseInt(sensorTabBtn.dataset.sensorIdx, 10);
                    var devPane = popupEl.querySelector('.aot-bay-popup-pane[data-pane="zdevices"]');
                    if (devPane) _activateZoneSensorTab(uid, devPane, idx);
                    return;
                }

                // 장치 이름 클릭 → 이력 오버레이
                var nameEl = e.target.closest('.aot-act-name[data-output-id]');
                if (nameEl && popupEl.contains(nameEl)) {
                    var row = nameEl.closest('.aot-act-row[data-slot]');
                    if (row) {
                        _selectZoneOutputOverlay(uid, popupEl,
                            nameEl.dataset.outputId, nameEl.dataset.outputName || '');
                    }
                    return;
                }

                // 메인 탭 전환 (nav 버튼)
                var navBtn = e.target.closest('.aot-bay-popup-nav .aot-act-tab-btn[data-sec]');
                if (navBtn && popupEl.contains(navBtn)) {
                    popupEl.querySelectorAll('.aot-bay-popup-nav .aot-act-tab-btn').forEach(function (b) {
                        b.classList.toggle('active', b === navBtn);
                    });
                    var secKey = navBtn.dataset.sec;
                    popupEl.querySelectorAll('.aot-bay-popup-pane').forEach(function (p) {
                        p.style.display = (p.dataset.pane === secKey) ? '' : 'none';
                    });
                    if (secKey === 'zdevices') {
                        var devPane2 = popupEl.querySelector('.aot-bay-popup-pane[data-pane="zdevices"]');
                        if (devPane2) {
                            var firstChart = devPane2.querySelector('.aot-bay-sensor-chart');
                            if (firstChart && firstChart.dataset.rendered !== '1') {
                                _activateZoneSensorTab(uid, devPane2, 0);
                            }
                            _reapplyZoneOverlay(uid, popupEl);
                        }
                    }
                    return;
                }

                // 장치 ON/OFF 토글
                var outTgl = e.target.closest('.aot-zone-output-toggle');
                if (outTgl && popupEl.contains(outTgl)) {
                    var outputId = outTgl.dataset.outputId;
                    var channel = parseInt(outTgl.dataset.channel || '0', 10);
                    var state = outTgl.checked;
                    outTgl.disabled = true;
                    fetch('/api/geo/output/' + encodeURIComponent(outputId) + '/state', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json',
                                   'X-CSRFToken': _csrfHeader() },
                        body: JSON.stringify({ state: state, channel: channel })
                    })
                    .then(function (r) { return r.json(); })
                    .then(function (j) { outTgl.disabled = false; if (!j.ok) outTgl.checked = !state; })
                    .catch(function () { outTgl.disabled = false; outTgl.checked = !state; });
                    return;
                }

                // 함수 활성 토글
                var fnTgl = e.target.closest('.aot-zone-func-toggle');
                if (fnTgl && popupEl.contains(fnTgl)) {
                    var funcId = fnTgl.dataset.funcId;
                    var kind = fnTgl.dataset.funcKind;
                    var isActive = fnTgl.dataset.active === '1';
                    var newActive = fnTgl.checked;
                    if (isActive && !newActive &&
                        !window.confirm(_tr('Deactivate this function?'))) {
                        fnTgl.checked = true;
                        return;
                    }
                    fnTgl.disabled = true;
                    fetch('/api/geo/function/' + encodeURIComponent(kind) + '/' +
                          encodeURIComponent(funcId) + '/activate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json',
                                   'X-CSRFToken': _csrfHeader() },
                        body: JSON.stringify({ active: newActive })
                    })
                    .then(function (r) { return r.json(); })
                    .then(function (j) {
                        fnTgl.disabled = false;
                        if (!j.ok) { fnTgl.checked = !newActive; return; }
                        fnTgl.dataset.active = newActive ? '1' : '0';
                    })
                    .catch(function () { fnTgl.disabled = false; fnTgl.checked = !newActive; });
                    return;
                }
            });
        }

        function _openZonePopup(uid, zoneUuid, zoneName) {
            var st = _zonePopupState[uid] || {};
            if (st.popup) { try { st.popup.remove(); } catch (e) {} }

            // Apply the widget's popup_default_tab to the zone popup. Facility tab keys
            // (overview/envctl/about) map onto zone tab keys; 'about' has no zone
            // equivalent so it falls back to the Status tab.
            var _zdt = (_actLabelState[uid] || {}).popupDefaultTab;
            var zoneDefSec = (_zdt === 'envctl') ? 'zdevices' : 'zoverview';

            var popup = _showFacilityCenterOverlay(_buildZonePopupHTML(zoneName, zoneDefSec), uid);
            _zonePopupState[uid] = { popup: popup, zoneUuid: zoneUuid,
                                     _sensors: [], _histCache: {},
                                     overlayOutputId: null, overlayOutputName: null };

            var popupEl = popup.getElement();
            var body = popupEl && popupEl.querySelector('.maplibregl-popup-content');

            popup.on('close', function () {
                var z = _zonePopupState[uid];
                if (z && z.popup === popup) { _zonePopupState[uid] = {}; }
            });

            fetch('/api/geo/zone/' + encodeURIComponent(zoneUuid) + '/contents')
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    if (!data || !data.ok) return;
                    var z = _zonePopupState[uid];
                    if (!z || !z.popup) return;

                    // 센서 목록 저장 (탭 지연 렌더에 사용)
                    z._sensors = data.sensors || [];

                    // [현황] 탭
                    var ovPane = body && body.querySelector('.aot-bay-popup-pane[data-pane="zoverview"]');
                    if (ovPane) _renderZoneOverview(uid, ovPane, data, zoneUuid);

                    // [센서·장치] 탭
                    var devPane = body && body.querySelector('.aot-bay-popup-pane[data-pane="zdevices"]');
                    if (devPane) _renderZoneDevices(uid, devPane, data, zoneUuid);

                    // [함수] 탭
                    var fnPane = body && body.querySelector('.aot-bay-popup-pane[data-pane="zfunctions"]');
                    if (fnPane) _renderZoneFunctions(fnPane, data, uid);

                    _wireZoneTabs(body, uid, zoneUuid);

                    // When the popup opened directly on the devices tab (popup_default_tab
                    // = envctl), render its sensor charts now — normally deferred to the
                    // nav click handler.
                    if (zoneDefSec === 'zdevices' && devPane) {
                        var firstChart = devPane.querySelector('.aot-bay-sensor-chart');
                        if (firstChart && firstChart.dataset.rendered !== '1') {
                            _activateZoneSensorTab(uid, devPane, 0);
                        }
                        _reapplyZoneOverlay(uid, popupEl);
                    }

                    // 제목 갱신
                    var titleEl = body && body.querySelector('.aot-sensor-popup-title');
                    if (titleEl && data.zone && data.zone.name) {
                        titleEl.textContent = data.zone.name;
                    }
                })
                .catch(function () {});
        }
        // ── End Zone modal ─────────────────────────────────────────────────────

        var _ACT_CATS = [
            { key: 'envelope', label: (window._ ? window._('Thermal') : 'Thermal'),    kinds: ['curtain', 'shade'] },
            { key: 'window',   label: (window._ ? window._('Openings') : 'Openings'),  kinds: ['opening'] },
            { key: 'water',    label: (window._ ? window._('Irrigation') : 'Irrigation'), kinds: ['irrigation'] },
            { key: 'facility', label: (window._ ? window._('Facility') : 'Facility'),  kinds: null }  // catch-all
        ];

        function _actKindToCat(kind) {
            for (var i = 0; i < _ACT_CATS.length; i++) {
                var cat = _ACT_CATS[i];
                if (cat.kinds && cat.kinds.indexOf(kind) !== -1) return cat.key;
            }
            return 'facility';  // catch-all
        }

        function _facilityCenter_act(facility) {
            if (facility.lat != null && facility.lng != null) return [facility.lng, facility.lat];
            var g3d = facility.geometry_3d;
            if (g3d && g3d.center_lng != null && g3d.center_lat != null) {
                return [g3d.center_lng, g3d.center_lat];
            }
            var feat = facility.outer_feature;
            if (!feat) return null;
            var geom = feat.type === 'Feature' ? (feat.geometry || {}) : feat;
            if (geom.type === 'Polygon') {
                var ring = (geom.coordinates || [])[0];
                if (!ring || !ring.length) return null;
                var sx = 0, sy = 0;
                for (var k = 0; k < ring.length; k++) { sx += ring[k][0]; sy += ring[k][1]; }
                return [sx / ring.length, sy / ring.length];
            }
            return null;
        }

        // Returns the outer ring of the outer_feature Polygon. Null if it is not a Polygon.
        function _facilityRing(facility) {
            var feat = facility.outer_feature;
            if (!feat) return null;
            var geom = feat.type === 'Feature' ? (feat.geometry || {}) : feat;
            if (geom.type !== 'Polygon') return null;
            return (geom.coordinates || [])[0] || null;
        }

        // Returns the closest point on the polygon perimeter to (qLng, qLat) (no push).
        // ring: [[lng,lat],...] (closed ring where the first point equals the last point)
        function _nearestEdgePoint(ring, centroid, qLng, qLat) {
            if (!ring || ring.length < 2) return null;
            var cx = centroid[0], cy = centroid[1];
            var bestDist = Infinity, bestX = cx, bestY = cy;
            for (var i = 0; i < ring.length - 1; i++) {
                var ax = ring[i][0],     ay = ring[i][1];
                var bx = ring[i + 1][0], by = ring[i + 1][1];
                var dx = bx - ax, dy = by - ay;
                var lenSq = dx * dx + dy * dy;
                var t = lenSq > 0
                    ? Math.max(0, Math.min(1, ((qLng - ax) * dx + (qLat - ay) * dy) / lenSq))
                    : 0;
                var px = ax + t * dx, py = ay + t * dy;
                var d = (px - qLng) * (px - qLng) + (py - qLat) * (py - qLat);
                if (d < bestDist) { bestDist = d; bestX = px; bestY = py; }
            }
            return [bestX, bestY];
        }

        // Returns the geo coordinate pushed outward by _ACT_CHIP_PUSH_PX in screen coordinates.
        // Always keeps the same pixel distance regardless of zoom level.
        var _ACT_CHIP_PUSH_PX = 36;
        function _computeChipPos(ring, centroid, qLng, qLat, map) {
            var edge = _nearestEdgePoint(ring, centroid, qLng, qLat);
            if (!edge) return null;
            var cPx = map.project(centroid);
            var ePx = map.project(edge);
            var dx = ePx.x - cPx.x, dy = ePx.y - cPx.y;
            var len = Math.sqrt(dx * dx + dy * dy);
            if (len < 1) return edge;
            var chipPx = map.unproject({
                x: ePx.x + (dx / len) * _ACT_CHIP_PUSH_PX,
                y: ePx.y + (dy / len) * _ACT_CHIP_PUSH_PX
            });
            return [chipPx.lng, chipPx.lat];
        }

        function _escAct(s) {
            return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        }

        // Determine the control type — based on the return value of routes_geo.py _resolve_control_type.
        // 'value'  → Actuator Paired position slider
        // 'pwm'    → PWM slider
        // else     → ON/OFF toggle
        function _actCtrlType(act) {
            var ct = act && act.control_type;
            if (ct === 'value') return 'value';
            if (ct === 'pwm')   return 'pwm';
            return 'binary';
        }

        // Popup HTML generation / dot position calculation / event delegation — uses the shared aot-map-popup.js component.
        // _buildCatPopupHTML / _positionCurrentDotsMap / _wirePopupEvents were
        // replaced by window.AoTMapPopup.buildActuatorTabs / positionDots / wire.

        function _csrfHeader() {
            // Extract the token from layout.html's <meta name="csrf-token">.
            // The routes_geo blueprint has CSRF protection enabled, so it is required for POST requests.
            var meta = document.querySelector('meta[name="csrf-token"]');
            return (meta && meta.getAttribute('content')) || '';
        }

        // ── Facility control popup: fixed screen-centered overlay ───────────────
        // Uses a viewport-centered fixed overlay instead of maplibregl.Popup (map-coordinate anchor).
        // The return value is an interface compatible with popup.getElement() / popup.remove() / popup.on('close',fn).
        //
        // Hierarchy (maplibregl.Popup compatible):
        function _sendActControl(facilityUuid, slotKey, action, percent, uid) {
            fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) + '/control', {
                method:  'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken':  _csrfHeader()
                },
                body:    JSON.stringify({
                    slot_key: slotKey,
                    action:   action,
                    percent:  percent,
                    reason:   'manual'
                })
            })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                _fetchAndUpdateActLabels(uid, facilityUuid);
                // 수동 제어한 장치가 오버레이 선택 중이면 5초 뒤 이력 재조회
                // (Output 컨트롤러의 Influx 기록 반영 시간 고려)
                var st = _actLabelState[uid];
                if (st && st.overlaySlot === slotKey) {
                    setTimeout(function () {
                        var st2 = _actLabelState[uid];
                        if (!st2 || st2.overlaySlot !== slotKey || !st2.openBayPopup) return;
                        if (st2._histCache) delete st2._histCache[slotKey];
                        var pEl = st2.openBayPopup.getElement();
                        var body = pEl && pEl.querySelector('.maplibregl-popup-content');
                        if (body) _reapplyOverlay(uid, facilityUuid, body);
                    }, 5000);
                }
            })
            .catch(function (e) { });
        }

        // Footprint ring for chip positioning: the drawn outer_feature polygon
        // when available, otherwise a rectangle computed from geometry_3d
        // dimensions (span/bay count/length/orientation) around the center.
        // Facilities placed by center+dimensions have no outer_feature — without
        // this fallback their bay chips would never clear the model.
        function _facilityFootprintRing(fac) {
            var ring = _facilityRing(fac);
            if (ring && ring.length) return ring;
            var center = _facilityCenter_act(fac);
            if (!center || !window.maplibregl) return null;
            var g3d = fac.geometry_3d || {};
            try {
                var spanW = parseFloat(g3d.span_width_m || 0);
                var length = parseFloat(g3d.length_m || 0);
                var bayCount = parseInt(fac.bay_count || 1, 10);
                var spacing = parseFloat(g3d.spacing_m || 0);
                var isConnected = fac.structure === 'connected';
                var effSpacing = isConnected ? 0 : spacing;
                var totalWidth = bayCount * spanW + (bayCount - 1) * effSpacing;
                if (!(totalWidth > 0) || !(length > 0)) return null;
                var hw = totalWidth / 2, hl = length / 2;
                var theta = (parseFloat(g3d.orientation_deg) || 0) * Math.PI / 180;
                var merc = window.maplibregl.MercatorCoordinate.fromLngLat(
                    { lng: center[0], lat: center[1] }, 0);
                var unit = merc.meterInMercatorCoordinateUnits();
                var corners = [[-hw, -hl], [hw, -hl], [hw, hl], [-hw, hl]].map(function (c) {
                    var rx = c[0] * Math.cos(theta) + c[1] * Math.sin(theta);
                    var rz = -c[0] * Math.sin(theta) + c[1] * Math.cos(theta);
                    var ll = new window.maplibregl.MercatorCoordinate(
                        merc.x + rx * unit, merc.y + rz * unit, merc.z).toLngLat();
                    return [ll.lng, ll.lat];
                });
                corners.push(corners[0]);
                return corners;
            } catch (e) { return null; }
        }

        function _attachActuatorLabels(uid, facilities, opts, map, refreshSeconds) {
            _detachActuatorLabels(uid);
            if (!map || !window.maplibregl) return;
            if (!Array.isArray(facilities) || !facilities.length) return;
            var canCtrl = !!(opts && (opts.can_control === true || opts.can_control === 'true'));
            // Control label text size — applies the widget custom_option 'global_label_size'.
            var ctrlLabelEm = parseFloat(opts && opts.global_label_size) || 1.0;
            var markers = [];
            var bayMarkers = [];
            // Mirror onto the widget instance (same array reference — later .push()
            // calls below are reflected) so sibling top-level functions that only
            // have window.AoTWidgetInstances access (e.g. addLayerPanel's label
            // toggles) can reach the bay chips. _actLabelState is local to this
            // function and is NOT in scope from those siblings.
            var _uidInstTop = window.AoTWidgetInstances[uid];
            if (_uidInstTop) _uidInstTop.bayMarkers = bayMarkers;

            facilities.forEach(function (fac) {
                // NOTE: the facility-edge chips (sensor summary + Control) were
                // removed — per-bay chips below are the single access point for
                // facility monitoring/control on the map.

                // ── Bay(구역) chips — one per zone (bay 1개 시설은 슬라이스 없음) ──
                // Chip shows the bay name (+ representative value after polling).
                // Click → per-bay monitoring/control modal (_openBayPopup).
                var bSlices = (window.AoTMapBay && window.AoTMapBay.slices(fac)) || [];
                bSlices.forEach(function (sl) {
                    var bPos = window.AoTMapBay.centerLngLat(fac, sl);
                    if (!bPos) return;
                    var bEl = document.createElement('div');
                    bEl.className = 'aot-sensor-map-marker aot-sensor-label-clickable aot-bay-chip';
                    bEl.dataset.facilityId = fac.unique_id;
                    bEl.dataset.bayId = sl.id;
                    // 2행 라벨: 1행 = 구역명, 2행 = 대표 측정값 (폴링 후 갱신)
                    bEl.innerHTML =
                        '<div class="aot-bay-chip-name">' + _escAct(sl.name || sl.id) + '</div>' +
                        '<div class="aot-bay-chip-val">—</div>';
                    bEl.style.fontSize = ctrlLabelEm + 'em';
                    bEl.style.transform = 'none';
                    // Bay chips attach asynchronously, well after the label toolbar's
                    // saved-state seeding runs — apply the current facility-label
                    // hidden state at creation time so a pre-hidden chip doesn't flash
                    // visible before the next retry timer catches it.
                    if (_uidInstTop && _uidInstTop._hiddenLabels && _uidInstTop._hiddenLabels.facility) {
                        bEl.classList.add('aot-type-hidden');
                    }
                    bEl.addEventListener('click', function (ev) {
                        ev.stopPropagation();
                        _openBayPopup(uid, fac.unique_id, sl.id);
                    });
                    // Anchored at the bay center; the vertical offset is computed
                    // per frame so the chip sits above the facility outline
                    // (see _repositionBayChips).
                    var bMarker = new window.maplibregl.Marker({
                            element: bEl, anchor: 'bottom'
                        })
                        .setLngLat(bPos)
                        .addTo(map);
                    bayMarkers.push({ marker: bMarker, el: bEl, lngLat: bPos,
                                      ring: _facilityFootprintRing(fac),
                                      facilityUuid: fac.unique_id, bayId: sl.id, slice: sl });
                });
            });

            _actLabelState[uid] = {
                markers: markers,
                bayMarkers: bayMarkers,
                facilities: facilities,
                statesByFac: {},
                sensorsByFac: {},
                openPopup: null,
                openPopupFacility: null,
                openSensorPopup: null,
                openSensorPopupFacility: null,
                openBayPopup: null,
                openBayFacility: null,
                openBayId: null,
                pollTimer: null,
                canCtrl: canCtrl,
                map: map,
                // 팝업 2탭 + 오버레이 상태
                popupDefaultTab: (function (v) {
                    return (v === 'envctl' || v === 'about') ? v : 'overview';
                })(opts && opts.popup_default_tab),
                overlaySlot: null,
                ovTimer: null,
                _histCache: {},
                _iecPending: false
            };

            // Control summary row in the measurement panel follows the facility
            // nearest to the map center — recompute when panning stops.
            var summaryMoveHandler = function () { _updateCtrlSummary(uid); };
            map.on('moveend', summaryMoveHandler);
            _actLabelState[uid].summaryMoveHandler = summaryMoveHandler;

            // Bay chips float above the facility outline: per frame, push each
            // chip up so its bottom clears the topmost screen point of the
            // facility footprint (plus margin for the 3D model height).
            // 2차 패스: 칩끼리 겹치면 위로 밀어 올려 간격을 자동 조절한다
            // (시설이 가까울 때 라벨이 서로 가려지지 않도록 세로 스택 정렬).
            var _BAY_CHIP_MARGIN_PX = 14;
            var _BAY_CHIP_GAP_PX    = 4;    // 칩 사이 최소 간격
            function _repositionBayChips() {
                var st = _actLabelState[uid];
                if (!st) return;

                // 1차: 시설 외곽선 기준 기본 오프셋 계산
                var items = [];
                st.bayMarkers.forEach(function (bm) {
                    if (!bm.lngLat) return;
                    var basePx = map.project({ lng: bm.lngLat[0], lat: bm.lngLat[1] });
                    var dy = -24;   // footprint 없을 때 고정 상승 폴백
                    if (bm.ring) {
                        var minY = Infinity;
                        for (var i = 0; i < bm.ring.length; i++) {
                            var p = map.project({ lng: bm.ring[i][0], lat: bm.ring[i][1] });
                            if (p.y < minY) minY = p.y;
                        }
                        if (isFinite(minY)) {
                            dy = (minY - _BAY_CHIP_MARGIN_PX) - basePx.y;
                            if (dy > 0) dy = 0;   // never push the chip below its anchor
                        }
                    }
                    items.push({
                        bm: bm, x: basePx.x, y: basePx.y, dy: dy,
                        w: bm.el.offsetWidth || 64, h: bm.el.offsetHeight || 30
                    });
                });

                // 2차: 겹치는 칩들을 클러스터로 묶고, 각 클러스터를 앵커 평균
                // 중심 기준으로 좌우 대칭 배열한다. 칩의 상대 순서(x 오름차순)는
                // 유지되므로 지도상의 좌우 관계가 뒤집히지 않는다.
                items.sort(function (a, b) { return a.x - b.x; });
                var clusters = [];
                items.forEach(function (it) {
                    var l = it.x - it.w / 2 - _BAY_CHIP_GAP_PX;
                    var r = it.x + it.w / 2 + _BAY_CHIP_GAP_PX;
                    var t = it.y + it.dy - it.h - _BAY_CHIP_GAP_PX;
                    var b = it.y + it.dy + _BAY_CHIP_GAP_PX;
                    var joined = null;
                    for (var i = 0; i < clusters.length; i++) {
                        var c = clusters[i];
                        if (!(r <= c.left || l >= c.right ||
                              b <= c.top || t >= c.bottom)) { joined = c; break; }
                    }
                    if (!joined) {
                        clusters.push({ members: [it], left: l, right: r, top: t, bottom: b });
                    } else {
                        joined.members.push(it);
                        if (l < joined.left)   joined.left = l;
                        if (r > joined.right)  joined.right = r;
                        if (t < joined.top)    joined.top = t;
                        if (b > joined.bottom) joined.bottom = b;
                    }
                });
                clusters.forEach(function (c) {
                    if (c.members.length < 2) {
                        var solo = c.members[0];
                        try { solo.bm.marker.setOffset([0, solo.dy]); } catch (e) {}
                        return;
                    }
                    var sumX = 0, totalW = 0;
                    c.members.forEach(function (m) { sumX += m.x; totalW += m.w; });
                    totalW += _BAY_CHIP_GAP_PX * (c.members.length - 1);
                    // 클러스터 중심(앵커 평균)에서 좌우로 균등 분배
                    var cursor = (sumX / c.members.length) - totalW / 2;
                    c.members.forEach(function (m) {
                        var dx = (cursor + m.w / 2) - m.x;
                        cursor += m.w + _BAY_CHIP_GAP_PX;
                        try { m.bm.marker.setOffset([dx, m.dy]); } catch (e) {}
                    });
                });
            }
            var _bayRafId = null;
            var bayMoveHandler = function () {
                if (_bayRafId) return;
                _bayRafId = requestAnimationFrame(function () {
                    _bayRafId = null;
                    _repositionBayChips();
                });
            };
            map.on('move', bayMoveHandler);
            _actLabelState[uid].bayMoveHandler = bayMoveHandler;
            _repositionBayChips();

            // Initial fetch
            facilities.forEach(function (fac) { _fetchAndUpdateActLabels(uid, fac.unique_id); });

            // Polling
            var interval = Math.max(5, parseFloat(refreshSeconds || (opts && opts.period) || 60)) * 1000;
            _actLabelState[uid].refreshMs = interval;   // [현황] 갱신도 동일 주기 사용
            _actLabelState[uid].pollTimer = setInterval(function () {
                if (document.hidden) return;
                var st = _actLabelState[uid];
                if (!st) return;
                st.facilities.forEach(function (fac) { _fetchAndUpdateActLabels(uid, fac.unique_id); });
            }, interval);
        }

        function _fetchAndUpdateActLabels(uid, facilityUuid) {
            // 공용 런타임 프로바이더로 요청 통합 — 센서 라벨 폴러와 동일
            // /runtime 을 공유해 저사양(Pi) 스레드 풀 포화를 막는다.
            var _rt = window.AoTFacilityRuntime
                ? window.AoTFacilityRuntime.get(facilityUuid)
                : fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) + '/runtime')
                    .then(function (r) { return r.ok ? r.json() : null; });
            _rt
                .then(function (data) {
                    if (!data) return;
                    var st = _actLabelState[uid];
                    if (!st) return;
                    var states = data.actuator_states || {};
                    st.statesByFac[facilityUuid] = states;
                    st.sensorsByFac[facilityUuid] = data.fitting_sensors || [];
                    // User-defined order cache (natural sort if absent). The local cache right after a
                    // drag-save may be newer than polling, so the cache takes priority.
                    st.orderByFac = st.orderByFac || {};
                    var cached = window.AoTActuatorOrder && window.AoTActuatorOrder.getCache(facilityUuid);
                    st.orderByFac[facilityUuid] = cached || data.actuator_order || [];
                    _updateActLabels(uid, facilityUuid, states);
                    _updateSensorSumChip(uid, facilityUuid);
                    _updateBayChips(uid, facilityUuid);
                    _refreshBayPopup(uid, facilityUuid);
                    _updateCtrlSummary(uid);
                })
                .catch(function () {});
        }

        // Tab button click → swap in the body for that group. Bound by delegation on
        // scopeEl (.maplibregl-popup-content), so the listener survives innerHTML changes.
        function _wireActTabs(scopeEl, uid, facilityUuid, canCtrl) {
            if (!scopeEl || scopeEl._actTabsWired) return;
            scopeEl._actTabsWired = true;
            scopeEl.addEventListener('click', function (e) {
                var btn = e.target.closest('.aot-act-tab-btn');
                if (!btn || !scopeEl.contains(btn)) return;
                var st = _actLabelState[uid];
                if (!st) return;
                var catKey     = btn.dataset.cat;
                var states     = (st.statesByFac && st.statesByFac[facilityUuid]) || {};
                var savedOrder = (st.orderByFac  && st.orderByFac[facilityUuid])  || [];
                if (!window.AoTMapPopup) return;
                scopeEl.innerHTML = window.AoTMapPopup.buildActuatorTabs(
                    catKey, _ACT_CATS, states, canCtrl, st._lastCmd || {}, _actKindToCat, savedOrder);
                window.AoTMapPopup.positionDots(scopeEl);
                _wireActSortable(scopeEl, uid, facilityUuid);
            });
        }

        // Enables drag-sorting of actuator rows in the popup (edit-permitted users only).
        // On drop, merges the category's new order into the full order and saves it to the server.
        function _wireActSortable(scopeEl, uid, facilityUuid) {
            if (!scopeEl || !window.AoTActuatorOrder) return;
            var st = _actLabelState[uid];
            if (!st || !st.canCtrl) return;
            window.AoTActuatorOrder.makeSortable(scopeEl, {
                itemSelector:  '.aot-act-row[data-slot]',
                handleSelector: '.aot-act-drag-handle',
                onReorder: function (seq) {
                    var states   = (st.statesByFac && st.statesByFac[facilityUuid]) || {};
                    var saved    = (st.orderByFac  && st.orderByFac[facilityUuid])  || [];
                    var allSlots = Object.keys(states);
                    var newFull  = window.AoTActuatorOrder.reorder(allSlots, saved, function (sk) {
                        return (states[sk] && states[sk].name) || sk;
                    }, seq);
                    st.orderByFac = st.orderByFac || {};
                    st.orderByFac[facilityUuid] = newFull;
                    window.AoTActuatorOrder.save(facilityUuid, newFull);
                }
            });
        }

        function _updateActLabels(uid, facilityUuid, states) {
            var st = _actLabelState[uid];
            if (!st) return;
            var markerEntry = null;
            for (var i = 0; i < st.markers.length; i++) {
                if (st.markers[i].facilityUuid === facilityUuid) { markerEntry = st.markers[i]; break; }
            }
            if (!markerEntry) return;
            var container = markerEntry.el;

            // Single 'Control' label: shows the total actuator count (hidden when 0).
            var total = Object.keys(states).length;
            var chip = container.querySelector('.aot-act-ctrl-chip');
            if (chip) {
                if (total === 0) {
                    chip.style.display = 'none';
                } else {
                    chip.style.display = '';
                    chip.textContent = (window._ ? window._('Control') : 'Control') + ' ' + total;
                }
            }

            // If open popup is for THIS facility, refresh its content.
            // Skip if openPopupFacility is a different facility — replacing the current popup
            // content with another facility's states causes a category mismatch.
            if (st.openPopup && st.openPopupFacility === facilityUuid) {
                var popupEl = st.openPopup.getElement();
                var body = popupEl && popupEl.querySelector('.maplibregl-popup-content');
                if (body && window.AoTMapPopup) {
                    // Rebuild the full tabbed popup while preserving the currently active tab.
                    var tabsEl    = body.querySelector('.aot-act-tabs');
                    var activeCat = tabsEl ? tabsEl.dataset.activeCat : null;
                    var canCtrl2  = !!(st.canCtrl);
                    var savedOrder2 = (st.orderByFac && st.orderByFac[facilityUuid]) || [];
                    // innerHTML 교체로 제어 목록 스크롤이 초기화되지 않도록 위치 보존
                    var listEl0 = body.querySelector('.aot-act-tabs-body');
                    var listScroll0 = listEl0 ? listEl0.scrollTop : 0;
                    body.innerHTML = window.AoTMapPopup.buildActuatorTabs(
                        activeCat, _ACT_CATS, states, canCtrl2, st._lastCmd || {}, _actKindToCat, savedOrder2);
                    var listEl1 = body.querySelector('.aot-act-tabs-body');
                    if (listEl1 && listScroll0) listEl1.scrollTop = listScroll0;
                    window.AoTMapPopup.positionDots(body);
                    // Rows were replaced, so re-enable draggable (listeners are delegated, bound once).
                    _wireActSortable(body, uid, facilityUuid);
                    // Do NOT re-call wire() / _wireActTabs() — the delegated listeners registered on the
                    // initial chip click keep working via event bubbling. Re-registering would accumulate
                    // duplicate listeners on every refresh and send duplicate control commands.
                }
            }
        }

        // ── Sensor summary chip + tabbed sensor popup ────────────────────────────
        // Representative measurement priority for the chip text (VPD first).
        var _SENSOR_SUM_PRIORITY = ['VPD', 'T', 'RH', 'CO2', 'light', 'wind_ms'];

        // Aggregate fitting_sensors[] → { key, avg, unit, more } for the chip.
        function _sensorSummary(sensors) {
            var byKey = {};
            (sensors || []).forEach(function (s) {
                (s.channels || []).forEach(function (c) {
                    if (!c || c.value == null || isNaN(+c.value)) return;
                    var k = c.key || c.measurement_type || '?';
                    var e = byKey[k] = byKey[k] || { sum: 0, n: 0, unit: c.unit || '' };
                    e.sum += +c.value; e.n += 1;
                });
            });
            var keys = Object.keys(byKey);
            if (!keys.length) return null;
            var primary = null;
            for (var i = 0; i < _SENSOR_SUM_PRIORITY.length; i++) {
                if (byKey[_SENSOR_SUM_PRIORITY[i]]) { primary = _SENSOR_SUM_PRIORITY[i]; break; }
            }
            if (!primary) primary = keys[0];
            var e2 = byKey[primary];
            return { key: primary, avg: e2.sum / e2.n, unit: e2.unit, more: keys.length > 1 };
        }

        function _facilityRanges_act(uid, facilityUuid) {
            var st = _actLabelState[uid];
            var facs = (st && st.facilities) || [];
            for (var i = 0; i < facs.length; i++) {
                if (facs[i] && facs[i].unique_id === facilityUuid) {
                    return (facs[i].view_options || {}).sensor_ranges || null;
                }
            }
            return null;
        }

        function _updateSensorSumChip(uid, facilityUuid) {
            var st = _actLabelState[uid];
            if (!st) return;
            var markerEntry = null;
            for (var i = 0; i < st.markers.length; i++) {
                if (st.markers[i].facilityUuid === facilityUuid) { markerEntry = st.markers[i]; break; }
            }
            if (!markerEntry) return;
            var sChip = markerEntry.el.querySelector('.aot-sensor-sum-chip');
            if (!sChip) return;

            var sum = _sensorSummary(st.sensorsByFac[facilityUuid]);
            if (!sum) { sChip.style.display = 'none'; return; }

            var dec = window.AoTSensorLabel ? window.AoTSensorLabel.defaultDecimals(sum.key) : 1;
            sChip.textContent = (sum.key === 'VPD' ? 'VPD ' : '') +
                                sum.avg.toFixed(dec) + (sum.unit || '') +
                                (sum.more ? ' +' : '');
            sChip.style.display = '';

            // Band color of the representative (averaged) value
            if (window.AoTMapSensorLabels && window.AoTMapSensorLabels.bandColor) {
                var ranges = _facilityRanges_act(uid, facilityUuid);
                var color = window.AoTMapSensorLabels.bandColor(sum.key, sum.avg, ranges);
                if (color) {
                    sChip.style.background = color;
                    sChip.style.color = window.AoTMapSensorLabels.textOn(color);
                } else {
                    sChip.style.background = '';
                    sChip.style.color = '';
                }
            }

            // Refresh the open sensor popup (this facility only), keeping the active tab.
            if (st.openSensorPopup && st.openSensorPopupFacility === facilityUuid) {
                var popupEl = st.openSensorPopup.getElement();
                var body = popupEl && popupEl.querySelector('.maplibregl-popup-content');
                if (body && window.AoTMapPopup) {
                    var tabsEl = body.querySelector('.aot-act-tabs');
                    var activeKey = tabsEl ? tabsEl.dataset.activeCat : null;
                    body.innerHTML = window.AoTMapPopup.buildSensorTabs(
                        activeKey, st.sensorsByFac[facilityUuid] || []);
                }
            }
        }

        function _openSensorTabsPopup(uid, facilityUuid) {
            var st = _actLabelState[uid];
            if (!st || !window.AoTMapPopup) return;
            if (st.openSensorPopup) { try { st.openSensorPopup.remove(); } catch (e) {} st.openSensorPopup = null; }

            var sensors = st.sensorsByFac[facilityUuid] || [];
            var popup = _showFacilityCenterOverlay(
                window.AoTMapPopup.buildSensorTabs(null, sensors), uid);

            var popupEl = popup.getElement();
            var bodyEl = popupEl && popupEl.querySelector('.maplibregl-popup-content');
            if (bodyEl) _wireSensorTabs(bodyEl, uid, facilityUuid);

            popup.on('close', function () {
                var st2 = _actLabelState[uid];
                if (st2 && st2.openSensorPopup === popup) {
                    st2.openSensorPopup = null;
                    st2.openSensorPopupFacility = null;
                }
            });
            st.openSensorPopup = popup;
            st.openSensorPopupFacility = facilityUuid;
        }

        // Tab switch + row click (24h chart popup) for the sensor popup.
        // Delegated on the popup content element, so it survives innerHTML refreshes.
        function _wireSensorTabs(scopeEl, uid, facilityUuid) {
            if (!scopeEl || scopeEl._sensorTabsWired) return;
            scopeEl._sensorTabsWired = true;
            scopeEl.addEventListener('click', function (e) {
                var st = _actLabelState[uid];
                if (!st) return;
                var btn = e.target.closest('.aot-act-tab-btn');
                if (btn && scopeEl.contains(btn)) {
                    scopeEl.innerHTML = window.AoTMapPopup.buildSensorTabs(
                        btn.dataset.cat, st.sensorsByFac[facilityUuid] || []);
                    return;
                }
                var row = e.target.closest('.aot-sensor-tab-row');
                if (row && scopeEl.contains(row) && window.AoTSensorLabel) {
                    var fittingId = row.dataset.fitting;
                    var sensors = st.sensorsByFac[facilityUuid] || [];
                    for (var i = 0; i < sensors.length; i++) {
                        if (String(sensors[i].fitting_id) === String(fittingId)) {
                            window.AoTSensorLabel.openPopup(sensors[i], { modal: true });
                            break;
                        }
                    }
                }
            });
        }

        // ── Bay(구역) chips + per-bay monitoring/control modal ───────────────────
        // Composes AoTMapBay filters with the shared AoTMapPopup builders.
        // The modal stacks two tab blocks: sensors (buildSensorTabs) on top,
        // actuators (buildActuatorTabs) below — each refreshed independently.

        // Chip rows: line 1 = zone name, line 2 = representative measurement
        // (VPD first) with band color applied to the whole chip.
        function _updateBayChips(uid, facilityUuid) {
            var st = _actLabelState[uid];
            if (!st || !st.bayMarkers || !window.AoTMapBay) return;
            var sensors = st.sensorsByFac[facilityUuid] || [];
            var ranges  = _facilityRanges_act(uid, facilityUuid);
            st.bayMarkers.forEach(function (bm) {
                if (bm.facilityUuid !== facilityUuid) return;
                var valEl = bm.el.querySelector('.aot-bay-chip-val');
                if (!valEl) return;
                var sum = _sensorSummary(window.AoTMapBay.filterSensors(sensors, bm.bayId));
                if (!sum) {
                    valEl.textContent = '—';
                    bm.el.style.background = '';
                    bm.el.style.color = '';
                    return;
                }
                var dec = window.AoTSensorLabel ? window.AoTSensorLabel.defaultDecimals(sum.key) : 1;
                valEl.textContent =
                    (sum.key === 'VPD' ? 'VPD ' : '') +
                    sum.avg.toFixed(dec) + (sum.unit || '') +
                    (sum.more ? ' +' : '');
                if (window.AoTMapSensorLabels && window.AoTMapSensorLabels.bandColor) {
                    var color = window.AoTMapSensorLabels.bandColor(sum.key, sum.avg, ranges);
                    if (color) {
                        bm.el.style.background = color;
                        bm.el.style.color = window.AoTMapSensorLabels.textOn(color);
                    } else {
                        bm.el.style.background = '';
                        bm.el.style.color = '';
                    }
                }
            });
        }

        // Modal body HTML — title + inline 24h sensor chart + actuator tab block.
        // No section headers, no sensor tabs/click-through: the chart shows every
        // bay sensor at once (AoTSensorLabel.renderHistory, rendered after insert).
        function _buildBayPopupHTML(uid, facilityUuid, bayId, activeActCat) {
            var st = _actLabelState[uid];
            if (!st || !window.AoTMapPopup || !window.AoTMapBay) return '';
            var fac = null;
            (st.facilities || []).forEach(function (f) {
                if (f && f.unique_id === facilityUuid) fac = f;
            });
            var slice = null;
            (fac ? window.AoTMapBay.slices(fac) : []).forEach(function (sl) {
                if (sl.id === bayId) slice = sl;
            });
            var title = ((fac && fac.name) || '') + ' — ' + ((slice && slice.name) || bayId);

            var states  = _bayCtrlStates(st, facilityUuid, bayId);
            var savedOrder = (st.orderByFac && st.orderByFac[facilityUuid]) || [];
            var defSec = (st.popupDefaultTab === 'envctl' || st.popupDefaultTab === 'about')
                ? st.popupDefaultTab : 'overview';

            // 제목: 센서 팝업(sensor-label.js openPopup)과 동일한 헤더 스타일.
            // 3탭 구조: [현황](동적 — IEC 운전/편차/예보) /
            //           [환경·제어](bay 단위 센서 차트 + 액추에이터) /
            //           [개요](정적 — 사진/시설 정보/설명/노트).
            // /overview 응답 전까지 보이는 스켈레톤 — 빈/말줄임 박스 대신
            // 로딩 중임을 드러내 체감 지연을 줄인다.
            var _skel = '<div class="aot-ov-skel">' +
                        '<div class="aot-ov-skel-bar w60"></div>' +
                        '<div class="aot-ov-skel-bar w80"></div>' +
                        '<div class="aot-ov-skel-bar w40"></div>' +
                        '<div class="aot-ov-skel-bar w80"></div>' +
                        '</div>';
            return '<div class="aot-sensor-popup-header">' +
                       '<span class="aot-sensor-popup-title">' + _escAct(title) + '</span>' +
                   '</div>' +
                   window.AoTMapPopup.buildSectionNav(defSec) +
                   '<div class="aot-bay-popup-pane" data-pane="overview"' +
                       (defSec === 'overview' ? '' : ' style="display:none"') + '>' +
                       _skel +
                   '</div>' +
                   '<div class="aot-bay-popup-pane" data-pane="envctl"' +
                       (defSec === 'envctl' ? '' : ' style="display:none"') + '>' +
                       '<div class="aot-bay-popup-section" data-zone="sensors"></div>' +
                       '<div class="aot-bay-popup-section" data-zone="acts">' +
                           window.AoTMapPopup.buildActuatorTabs(activeActCat, _ACT_CATS, states,
                               st.canCtrl, st._lastCmd || {}, _actKindToCat, savedOrder) +
                       '</div>' +
                   '</div>' +
                   '<div class="aot-bay-popup-pane" data-pane="about"' +
                       (defSec === 'about' ? '' : ' style="display:none"') + '>' +
                       _skel +
                   '</div>';
        }

        // 구역 제어 상태 — 단동(슬라이스 1개) 시설은 구역 칩이 유일한
        // 진입점이므로 시설 공통(bay_ids=[]) 액추에이터도 포함한다.
        function _bayCtrlStates(st, facilityUuid, bayId) {
            var fac = null;
            (st.facilities || []).forEach(function (f) {
                if (f && f.unique_id === facilityUuid) fac = f;
            });
            var slices = fac ? window.AoTMapBay.slices(fac) : [];
            return window.AoTMapBay.filterStates(
                st.statesByFac[facilityUuid] || {}, bayId, slices.length === 1);
        }

        // 현재 보이는 pane 키 ('overview' | 'envctl' | null)
        function _activePane(bodyEl) {
            var panes = bodyEl ? bodyEl.querySelectorAll('.aot-bay-popup-pane') : [];
            for (var i = 0; i < panes.length; i++) {
                if (panes[i].style.display !== 'none') return panes[i].dataset.pane;
            }
            return null;
        }

        // Sensors shown in the bay modal: the bay's own sensors first, then
        // facility-common sensors with no bay attribution (예: 기상대/실외 센서).
        function _baySensors(st, facilityUuid, bayId) {
            var all = st.sensorsByFac[facilityUuid] || [];
            var inBay = window.AoTMapBay.filterSensors(all, bayId);
            var common = all.filter(function (s) { return s && s.bay_id == null; });
            return inBay.concat(common);
        }

        // Build the per-sensor tab structure once per popup (one tab per sensor,
        // single-sensor case skips the nav). Each tab holds its own chart div,
        // rendered lazily on first activation — charts fetch their own /past
        // history, so they must NOT be rebuilt on every poll. Retries on later
        // polls until runtime sensors arrive.
        function _renderBayChart(uid, facilityUuid, bayId, bodyEl) {
            var st = _actLabelState[uid];
            if (!st || !window.AoTSensorLabel || !window.AoTMapBay || !bodyEl) return;
            var sec = bodyEl.querySelector('.aot-bay-popup-section[data-zone="sensors"]');
            if (!sec || sec.dataset.chartDone === '1') return;
            var sensors = _baySensors(st, facilityUuid, bayId);
            if (!sensors.length) return;   // runtime not polled yet — retry on next poll
            sec.dataset.chartDone = '1';

            var nav = '<div class="aot-act-tabs-nav">' + sensors.map(function (s, i) {
                return '<button type="button" class="aot-act-tab-btn' + (i === 0 ? ' active' : '') + '"' +
                       ' data-fitting="' + _escAct(s.fitting_id) + '">' +
                       _escAct(s.name || s.fitting_id) + '</button>';
            }).join('') + '</div>';
            var charts = sensors.map(function (s, i) {
                return '<div class="aot-bay-sensor-chart" data-fitting="' + _escAct(s.fitting_id) + '"' +
                       (i === 0 ? '' : ' style="display:none"') + '></div>';
            }).join('');
            sec.innerHTML = (sensors.length > 1 ? nav : '') + charts;
            _activateBaySensorTab(uid, facilityUuid, bayId, sec, String(sensors[0].fitting_id));
        }

        function _activateBaySensorTab(uid, facilityUuid, bayId, sec, fittingId) {
            var st = _actLabelState[uid];
            if (!st || !sec) return;
            sec.querySelectorAll('.aot-act-tab-btn[data-fitting]').forEach(function (b) {
                b.classList.toggle('active', b.dataset.fitting === fittingId);
            });
            sec.querySelectorAll('.aot-bay-sensor-chart').forEach(function (div) {
                var on = div.dataset.fitting === fittingId;
                div.style.display = on ? '' : 'none';
                if (on && div.dataset.rendered !== '1') {
                    div.dataset.rendered = '1';
                    var sensors = _baySensors(st, facilityUuid, bayId);
                    for (var i = 0; i < sensors.length; i++) {
                        if (String(sensors[i].fitting_id) === String(fittingId)) {
                            window.AoTSensorLabel.renderHistory(div, [sensors[i]], {});
                            break;
                        }
                    }
                }
            });
        }

        // Tab switch (sensor tabs + actuator tabs). Delegated on the popup body,
        // so the listener survives section innerHTML refreshes. Only the acts
        // section rebuilds on poll — chart tabs keep their rendered state.
        function _wireBayTabs(scopeEl, uid, facilityUuid, bayId) {
            if (!scopeEl || scopeEl._bayTabsWired) return;
            scopeEl._bayTabsWired = true;
            scopeEl.addEventListener('click', function (e) {
                var st = _actLabelState[uid];
                if (!st || !window.AoTMapPopup || !window.AoTMapBay) return;

                // 자동제어 토글 (현황 pane) — 슬라이드 토글의 checkbox input 만 매칭
                // (label 클릭 시 브라우저가 input 에 합성 click 을 1회 발생시킨다)
                var tgl = e.target.closest('.aot-iec-toggle-input');
                if (tgl && scopeEl.contains(tgl)) {
                    _toggleIec(uid, facilityUuid, tgl);
                    return;
                }

                // 액추에이터 이름 클릭 → 차트 오버레이 선택/해제
                // (행 전체가 아닌 이름 영역으로 한정 — 슬라이더/토글과 분리)
                var nameEl = e.target.closest('.aot-act-name');
                if (nameEl && scopeEl.contains(nameEl)) {
                    var row = nameEl.closest('.aot-act-row[data-slot]');
                    var actsSec = nameEl.closest('.aot-bay-popup-section[data-zone="acts"]');
                    if (row && actsSec) {
                        _selectOverlayActuator(uid, facilityUuid, row.dataset.slot, scopeEl);
                        return;
                    }
                }

                var btn = e.target.closest('.aot-act-tab-btn');
                if (!btn || !scopeEl.contains(btn)) return;

                // 섹션 pane 전환 ([현황] / [환경·제어])
                if (btn.dataset.sec) {
                    var nav = btn.closest('.aot-bay-popup-nav');
                    if (nav) {
                        nav.querySelectorAll('.aot-act-tab-btn').forEach(function (b) {
                            b.classList.toggle('active', b === btn);
                        });
                    }
                    scopeEl.querySelectorAll('.aot-bay-popup-pane').forEach(function (p) {
                        p.style.display = (p.dataset.pane === btn.dataset.sec) ? '' : 'none';
                    });
                    if (btn.dataset.sec === 'envctl') {
                        // 차트는 pane 이 보일 때 렌더해야 폭 계산이 맞다 (지연 렌더)
                        _renderBayChart(uid, facilityUuid, bayId, scopeEl);
                        _reapplyOverlay(uid, facilityUuid, scopeEl);
                        // 숨김 상태에서 건너뛴 슬라이더 dot 위치 재계산
                        window.AoTMapPopup.positionDots(scopeEl);
                    }
                    return;
                }
                // 센서 탭: 해당 센서 차트 표시 (최초 활성화 시 지연 렌더)
                if (btn.dataset.fitting) {
                    var sSec = btn.closest('.aot-bay-popup-section[data-zone="sensors"]');
                    if (sSec) {
                        _activateBaySensorTab(uid, facilityUuid, bayId, sSec, btn.dataset.fitting);
                        // 차트가 바뀜 — 선택된 액추에이터 오버레이를 새 차트에 재적용
                        _reapplyOverlay(uid, facilityUuid, scopeEl);
                    }
                    return;
                }
                var section = btn.closest('.aot-bay-popup-section[data-zone="acts"]');
                if (!section) return;
                var states = _bayCtrlStates(st, facilityUuid, bayId);
                var savedOrder = (st.orderByFac && st.orderByFac[facilityUuid]) || [];
                section.innerHTML = window.AoTMapPopup.buildActuatorTabs(
                    btn.dataset.cat, _ACT_CATS, states, st.canCtrl,
                    st._lastCmd || {}, _actKindToCat, savedOrder);
                window.AoTMapPopup.positionDots(section);
                _markOverlayRow(section, st.overlaySlot);
            });
        }

        // 오버레이 선택된 행 하이라이트 재적용 (acts section innerHTML 재생성 후)
        function _markOverlayRow(sectionEl, slotKey) {
            if (!sectionEl) return;
            sectionEl.querySelectorAll('.aot-act-row[data-slot]').forEach(function (r) {
                r.classList.toggle('aot-act-row--selected',
                                   !!slotKey && r.dataset.slot === slotKey);
            });
        }

        // [현황]/오버레이 갱신 정책 상수
        var _OV_REFRESH_MS  = 30000;  // env_summary 갱신 주기 폴백 (위젯 period 옵션 우선)
        var _IEC_POLL_MS    = 2000;   // 토글 후 데몬 반영 확인 주기
        var _IEC_POLL_MAX   = 10;     // 토글 확인 최대 횟수
        var _HIST_CACHE_MS  = 60000;  // 액추에이터 이력 캐시 수명
        var _HIST_HOURS     = 24;     // 이력 조회 구간 (센서 차트와 동일)

        // ── [현황] pane: env_summary + status 로드 → 렌더 → 노트 비동기 채움 ──
        function _loadOverview(uid, facilityUuid) {
            var st = _actLabelState[uid];
            if (!st || !st.openBayPopup) return;
            var popupEl = st.openBayPopup.getElement();
            var body = popupEl && popupEl.querySelector('.maplibregl-popup-content');
            var pane = body && body.querySelector('.aot-bay-popup-pane[data-pane="overview"]');
            var abPane = body && body.querySelector('.aot-bay-popup-pane[data-pane="about"]');
            if (!pane) return;
            if (st._iecPending) return;   // 토글 적용 중 — 재렌더로 pending 상태를 지우지 않음
            if (st._ovEditing) return;    // 설명 편집 중 — 30초 갱신이 입력을 지우지 않음
            var _tr = function (s) { return (window._ ? window._(s) : s); };
            var _j = function (r) { return r.ok ? r.json() : null; };
            var _render = function (res) {
                var st2 = _actLabelState[uid];
                if (!st2 || !st2.openBayPopup || st2.openBayFacility !== facilityUuid) return;
                if (!res[0]) {
                    pane.innerHTML = '<div class="aot-ov-block aot-ov-inactive">' +
                                     _tr('Failed to load information') + '</div>';
                    return;
                }
                // [현황] = 동적 정보, [개요] = 정적 정보 — 분리 렌더.
                // [개요]는 내용이 실제로 바뀐 경우에만 DOM 교체 — 매 갱신마다
                // innerHTML 을 갈아끼우면 대표사진 <img> 가 다시 로드되며 깜빡인다.
                pane.innerHTML = window.AoTMapPopup.buildOverviewSection(
                    res[0], res[1], { canToggle: st2.canCtrl });
                var aboutChanged = false;
                if (abPane) {
                    var aboutHtml = window.AoTMapPopup.buildAboutSection(res[2]);
                    if (aboutHtml !== st2._aboutHtml) {
                        st2._aboutHtml = aboutHtml;
                        abPane.innerHTML = aboutHtml;
                        aboutChanged = true;
                    }
                }
                var wireEl = abPane || pane;   // 사진/설명은 [개요] pane (노트는 [현황])

                var facName = '';
                (st2.facilities || []).forEach(function (f) {
                    if (f && f.unique_id === facilityUuid) facName = f.name || '';
                });

                // 노트 패널 열기 (조회 + 작성) — 팝업 모달이 노트 패널을
                // 가리므로(z-index 최상위) 먼저 모달을 닫는다.
                function _openNotesPanel() {
                    var st3 = _actLabelState[uid];
                    if (st3 && st3.openBayPopup) {
                        try { st3.openBayPopup.remove(); } catch (e) {}
                    }
                    window.dispatchEvent(new CustomEvent('open-notes', {
                        detail: { targetId: facilityUuid,
                                  targetType: 'GeoFacility', name: facName }
                    }));
                }
                var noteBtn = pane.querySelector('.aot-ov-notes-open');
                if (noteBtn) noteBtn.addEventListener('click', _openNotesPanel);

                // 대표사진 업로드 (editor 이상에서만 버튼이 렌더됨).
                // [개요] DOM 이 교체된 경우에만 wiring — 유지된 DOM 에
                // 리스너를 다시 달면 중복 실행된다.
                var phBtn = aboutChanged ? wireEl.querySelector('.aot-ov-photo-btn') : null;
                var phInput = aboutChanged ? wireEl.querySelector('.aot-ov-photo-input') : null;
                if (phBtn && phInput) {
                    phBtn.addEventListener('click', function () { phInput.click(); });
                    phInput.addEventListener('change', function () {
                        if (!phInput.files || !phInput.files[0]) return;
                        var fd = new FormData();
                        fd.append('photo', phInput.files[0]);
                        phBtn.disabled = true;
                        fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) + '/photo', {
                            method: 'POST',
                            headers: { 'X-CSRFToken': _csrfHeader() },
                            body: fd
                        })
                        .then(function (r) { return r.json(); })
                        .then(function () { _loadOverview(uid, facilityUuid); })
                        .catch(function () { phBtn.disabled = false; });
                    });
                }

                // 설명 편집/저장 (editor 이상에서만 편집 UI 렌더됨, 위와 동일 정책)
                var descEdit   = aboutChanged ? wireEl.querySelector('.aot-ov-desc-edit') : null;
                var descView   = wireEl.querySelector('.aot-ov-desc-view');
                var descWrap   = wireEl.querySelector('.aot-ov-desc-editwrap');
                var descInput  = wireEl.querySelector('.aot-ov-desc-input');
                var descSave   = wireEl.querySelector('.aot-ov-desc-save');
                var descCancel = wireEl.querySelector('.aot-ov-desc-cancel');
                if (descEdit && descWrap) {
                    descEdit.addEventListener('click', function () {
                        st2._ovEditing = true;
                        descView.style.display = 'none';
                        descEdit.style.display = 'none';
                        descWrap.style.display = '';
                        if (descInput) descInput.focus();
                    });
                    if (descCancel) descCancel.addEventListener('click', function () {
                        st2._ovEditing = false;
                        descWrap.style.display = 'none';
                        descView.style.display = '';
                        descEdit.style.display = '';
                    });
                    if (descSave) descSave.addEventListener('click', function () {
                        descSave.disabled = true;
                        fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) + '/info', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json',
                                       'X-CSRFToken': _csrfHeader() },
                            body: JSON.stringify({
                                description: descInput ? descInput.value : '' })
                        })
                        .then(function (r) { return r.json(); })
                        .then(function () {
                            st2._ovEditing = false;
                            _loadOverview(uid, facilityUuid);
                        })
                        .catch(function () { descSave.disabled = false; });
                    });
                }

                // 노트 목록 — 30초 갱신 시 깜빡임 방지: 이전 렌더 내용을
                // 즉시 복원해 placeholder(…)가 보이지 않게 하고, fetch 결과가
                // 실제로 달라졌을 때만 DOM 을 교체한다.
                var listEl = pane.querySelector('.aot-ov-notes-list');
                function _bindNoteClicks(el) {
                    el.querySelectorAll('.aot-ov-note').forEach(function (n) {
                        n.addEventListener('click', _openNotesPanel);
                    });
                }
                if (listEl && st2._notesHtml) {
                    listEl.innerHTML = st2._notesHtml;
                    _bindNoteClicks(listEl);
                }
                fetch('/notes/target/' + encodeURIComponent(facilityUuid))
                    .then(_j)
                    .then(function (notes) {
                        var st4 = _actLabelState[uid];
                        if (!st4 || !listEl) return;
                        var tmp = document.createElement('div');
                        window.AoTMapPopup.fillOverviewNotes(tmp, notes, null);
                        if (tmp.innerHTML !== st4._notesHtml) {
                            st4._notesHtml = tmp.innerHTML;
                            listEl.innerHTML = tmp.innerHTML;
                            _bindNoteClicks(listEl);
                        }
                    })
                    .catch(function () {});
            };

            // env_summary + status + info 를 한 요청(/overview)으로 묶어
            // 받는다. 개별 fetch 3개는 gthread 워커 스레드 3개를 동시에
            // 점유해, 페이지 로드 직후 맵 폴링 버스트와 겹칠 때 스레드 풀이
            // 포화되어 모달 렌더가 1초+(콜드 시 4초+) 지연되는 주원인이었다.
            fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) + '/overview')
                .then(_j).catch(function () { return null; })
                .then(function (j) {
                    j = j || {};
                    _render([j.env_summary || null, j.status || null,
                             j.info || null]);
                });
        }

        // 자동제어 토글: 확인(비활성화 시) → POST → status 폴링으로 데몬 반영
        // input 은 공용 슬라이드 토글(btn-toggle)의 checkbox — 클릭 시점에
        // 브라우저가 이미 checked 를 뒤집었으므로 취소 시 되돌린다.
        // 적용 완료까지 disabled (기동/종료에 수 초 소요, 연타 방지).
        function _toggleIec(uid, facilityUuid, input) {
            var st = _actLabelState[uid];
            if (!st || input.disabled) return;
            var _tr = function (s) { return (window._ ? window._(s) : s); };
            var isActive = input.dataset.active === '1';
            if (isActive &&
                !window.confirm(_tr('Automatic environment control will stop. Continue?'))) {
                input.checked = true;   // 취소 → 토글 상태 복원
                return;
            }
            input.disabled = true;
            st._iecPending = true;
            var _done = function () {
                var st2 = _actLabelState[uid];
                if (st2) st2._iecPending = false;
                _loadOverview(uid, facilityUuid);
            };
            fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) + '/function_state', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrfHeader() },
                body: JSON.stringify({ action: isActive ? 'deactivate' : 'activate' })
            })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) {
                    _done();
                    return;
                }
                var want = !isActive;
                var tries = 0;
                (function poll() {
                    tries++;
                    fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) + '/status')
                        .then(function (r) { return r.ok ? r.json() : null; })
                        .then(function (s) {
                            if ((s && s.function_active === want) ||
                                tries >= _IEC_POLL_MAX) _done();
                            else setTimeout(poll, _IEC_POLL_MS);
                        })
                        .catch(function () {
                            if (tries >= _IEC_POLL_MAX) _done();
                            else setTimeout(poll, _IEC_POLL_MS);
                        });
                })();
            })
            .catch(_done);
        }

        // ── 액추에이터 차트 오버레이 ──────────────────────────────────────────
        // 행 이름 클릭 → 해당 장치의 작동 이력을 센서 차트에 시리즈로 추가.
        // percent형: 계단형 step 'left' 라인(0~100%),
        // on/off형: ON 이벤트별 작동 시간(분)을 막대(column)로.
        // 동시 1개 — 다른 장치 선택 시 교체 (id 기반).

        function _activeBayChartContainer(scopeEl) {
            var sec = scopeEl &&
                scopeEl.querySelector('.aot-bay-popup-section[data-zone="sensors"]');
            if (!sec) return null;
            var divs = sec.querySelectorAll('.aot-bay-sensor-chart');
            for (var i = 0; i < divs.length; i++) {
                if (divs[i].style.display !== 'none') return divs[i];
            }
            return null;
        }

        function _fetchActuatorHistory(uid, facilityUuid, slotKey) {
            var st = _actLabelState[uid];
            if (!st) return Promise.resolve(null);
            st._histCache = st._histCache || {};
            var c = st._histCache[slotKey];
            var now = Date.now();
            if (c && (now - c.ts) < _HIST_CACHE_MS) return Promise.resolve(c.data);
            return fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) +
                         '/actuator_history?slot_key=' + encodeURIComponent(slotKey) +
                         '&hours=' + _HIST_HOURS)
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (d && d.ok) st._histCache[slotKey] = { ts: now, data: d };
                    return d;
                })
                .catch(function () { return null; });
        }

        function _applyOverlaySeries(chartDiv, hist, name) {
            var chart = chartDiv && chartDiv._aotChart;
            if (!chart) return false;
            try {
                var old = chart.get('aot-act-overlay');
                if (old) old.remove(false);
                // 축은 series_type(% vs 작동분)에 따라 스케일이 달라지므로 매번 재생성.
                var oldAxis = chart.get('aot-act-axis');
                if (oldAxis) oldAxis.remove(false);

                var isOnOff = hist.series_type === 'onoff';
                var pts = (hist.points || []).map(function (p) {
                    return [p[0] * 1000, p[1]];
                }).sort(function (a, b) { return a[0] - b[0]; });

                if (isOnOff) {
                    // on/off 장치: ON 이벤트마다 작동 시간(분)을 막대로.
                    // 우측 보조축은 0~ 자동 최대(분), 라벨 표기.
                    chart.addAxis({
                        id: 'aot-act-axis', min: 0, opposite: true,
                        title: { text: null },
                        labels: {
                            enabled: true,
                            style: { fontSize: '9px' },
                            formatter: function () { return this.value + 'm'; }
                        },
                        gridLineWidth: 0
                    }, false, false);
                    if (!pts.length) { chart.redraw(); return true; }
                    chart.addSeries({
                        id: 'aot-act-overlay',
                        name: name,
                        yAxis: 'aot-act-axis',
                        type: 'column',
                        data: pts,
                        maxPointWidth: 3,
                        borderWidth: 0,
                        tooltip: { valueSuffix: ' ' + (window._ ? window._('min') : 'min'),
                                   valueDecimals: 1 }
                    }, true);
                } else {
                    // 위치형(percent) 장치: 0~100% 계단형 라인 (기존 동작 유지).
                    chart.addAxis({
                        id: 'aot-act-axis', min: 0, max: 105, opposite: true,
                        title: { text: null }, labels: { enabled: false },
                        gridLineWidth: 0
                    }, false, false);
                    if (!pts.length) { chart.redraw(); return true; }
                    chart.addSeries({
                        id: 'aot-act-overlay',
                        name: name,
                        yAxis: 'aot-act-axis',
                        type: 'line',
                        step: 'left',
                        data: pts,
                        lineWidth: 2,
                        tooltip: { valueSuffix: ' %' }
                    }, true);
                }
                return true;
            } catch (e) { return false; }
        }

        function _removeOverlaySeries(scopeEl) {
            var div = _activeBayChartContainer(scopeEl);
            var chart = div && div._aotChart;
            if (!chart) return;
            try {
                var s = chart.get('aot-act-overlay');
                if (s) s.remove();
            } catch (e) {}
        }

        // 선택 상태를 현재 보이는 차트에 (재)적용. 차트가 아직 비동기 렌더
        // 중이면 짧게 재시도 (renderHistory 는 완료 콜백이 없다).
        function _reapplyOverlay(uid, facilityUuid, scopeEl, attempt) {
            var st = _actLabelState[uid];
            if (!st || !st.overlaySlot) return;
            var slot = st.overlaySlot;
            var div = _activeBayChartContainer(scopeEl);
            if (!div || !div._aotChart) {
                attempt = attempt || 0;
                if (attempt < 20) {
                    setTimeout(function () {
                        var st2 = _actLabelState[uid];
                        if (st2 && st2.overlaySlot === slot) {
                            _reapplyOverlay(uid, facilityUuid, scopeEl, attempt + 1);
                        }
                    }, 250);
                }
                return;
            }
            var states = st.statesByFac[facilityUuid] || {};
            var name = (states[slot] && states[slot].name) || slot;
            _fetchActuatorHistory(uid, facilityUuid, slot).then(function (hist) {
                var st2 = _actLabelState[uid];
                if (!st2 || st2.overlaySlot !== slot || !hist || !hist.ok) return;
                _applyOverlaySeries(div, hist, name);
            });
        }

        function _selectOverlayActuator(uid, facilityUuid, slotKey, scopeEl) {
            var st = _actLabelState[uid];
            if (!st || !slotKey) return;
            if (st.overlaySlot === slotKey) {
                st.overlaySlot = null;          // 재클릭 → 해제
                _removeOverlaySeries(scopeEl);
            } else {
                st.overlaySlot = slotKey;       // 교체 (동시 1개)
                _reapplyOverlay(uid, facilityUuid, scopeEl);
            }
            var sec = scopeEl.querySelector('.aot-bay-popup-section[data-zone="acts"]');
            _markOverlayRow(sec, st.overlaySlot);
        }

        function _openBayPopup(uid, facilityUuid, bayId) {
            var st = _actLabelState[uid];
            if (!st || !window.AoTMapPopup || !window.AoTMapBay) return;
            if (st.openBayPopup) { try { st.openBayPopup.remove(); } catch (e) {} st.openBayPopup = null; }

            var popup = _showFacilityCenterOverlay(
                _buildBayPopupHTML(uid, facilityUuid, bayId, null), uid);
            var popupEl = popup.getElement();
            var bodyEl = popupEl && popupEl.querySelector('.maplibregl-popup-content');
            if (bodyEl) {
                window.AoTMapPopup.positionDots(bodyEl);
                if (_activePane(bodyEl) === 'envctl') {
                    _renderBayChart(uid, facilityUuid, bayId, bodyEl);
                }
                _wireBayTabs(bodyEl, uid, facilityUuid, bayId);
                // 드래그 정렬: 구역에 보이는 부분 목록의 새 순서를
                // AoTActuatorOrder.reorder 가 시설 전체 순서에 병합해 저장한다.
                // (위임 바인딩이라 행이 갱신돼도 1회 바인딩으로 충분)
                _wireActSortable(bodyEl, uid, facilityUuid);
                if (st.canCtrl) {
                    window.AoTMapPopup.wire(popupEl,
                        function (slotKey, action, percent) {
                            _sendActControl(facilityUuid, slotKey, action, percent, uid);
                        },
                        {
                            set: function (slot, val) {
                                var _st = _actLabelState[uid];
                                if (_st) { _st._lastCmd = _st._lastCmd || {}; _st._lastCmd[slot] = val; }
                            }
                        });
                }
            }

            popup.on('close', function () {
                var st2 = _actLabelState[uid];
                if (st2 && st2.openBayPopup === popup) {
                    if (st2.ovTimer) { clearInterval(st2.ovTimer); st2.ovTimer = null; }
                    st2.openBayPopup = null;
                    st2.openBayFacility = null;
                    st2.openBayId = null;
                    st2.overlaySlot = null;
                    st2._ovEditing = false;
                }
            });
            st.openBayPopup = popup;
            st.openBayFacility = facilityUuid;
            st.openBayId = bayId;
            st.overlaySlot = null;
            st._notesHtml = null;
            st._aboutHtml = null;

            // [현황] 데이터 로드 + 30초 주기 갱신 (팝업 열려있는 동안만 —
            // 사이클 주기와 유사하므로 더 짧을 필요 없음)
            _loadOverview(uid, facilityUuid);
            if (st.ovTimer) clearInterval(st.ovTimer);
            st.ovTimer = setInterval(function () {
                if (document.hidden) return;
                _loadOverview(uid, facilityUuid);
            }, st.refreshMs || _OV_REFRESH_MS);
        }

        // Poll refresh for the open bay modal — rebuild ONLY the acts section,
        // keeping the active tab. The chart section is left untouched (it owns
        // its own /past history fetch). Delegated listeners on the body keep
        // working; do NOT re-call wire()/_wireBayTabs() (would duplicate sends).
        function _refreshBayPopup(uid, facilityUuid) {
            var st = _actLabelState[uid];
            if (!st || !st.openBayPopup || st.openBayFacility !== facilityUuid) return;
            var popupEl = st.openBayPopup.getElement();
            var body = popupEl && popupEl.querySelector('.maplibregl-popup-content');
            if (!body || !window.AoTMapPopup || !window.AoTMapBay) return;
            // Late chart render: runtime sensors may have arrived after open.
            // 차트는 envctl pane 이 보일 때만 렌더 (숨김 상태 렌더 = 폭 0).
            if (_activePane(body) === 'envctl') {
                _renderBayChart(uid, facilityUuid, st.openBayId, body);
            }
            var section = body.querySelector('.aot-bay-popup-section[data-zone="acts"]');
            if (!section) return;
            var tabsEl = section.querySelector('.aot-act-tabs');
            var activeCat = tabsEl ? tabsEl.dataset.activeCat : null;
            var states = _bayCtrlStates(st, facilityUuid, st.openBayId);
            var savedOrder = (st.orderByFac && st.orderByFac[facilityUuid]) || [];
            // innerHTML 교체 시 제어 목록(.aot-act-tabs-body)과 상위 pane 의
            // 스크롤이 초기화/클램프되지 않도록 위치 보존
            var listEl = section.querySelector('.aot-act-tabs-body');
            var listScroll = listEl ? listEl.scrollTop : 0;
            var paneEl = section.closest ? section.closest('.aot-bay-popup-pane') : null;
            var paneScroll = paneEl ? paneEl.scrollTop : 0;
            section.innerHTML = window.AoTMapPopup.buildActuatorTabs(
                activeCat, _ACT_CATS, states, st.canCtrl,
                st._lastCmd || {}, _actKindToCat, savedOrder);
            var listEl2 = section.querySelector('.aot-act-tabs-body');
            if (listEl2 && listScroll) listEl2.scrollTop = listScroll;
            if (paneEl && paneScroll) paneEl.scrollTop = paneScroll;
            window.AoTMapPopup.positionDots(section);
            _markOverlayRow(section, st.overlaySlot);
        }

        // ── Control summary row (measurement panel, facility nearest to center) ──
        function _updateCtrlSummary(uid) {
            var st = _actLabelState[uid];
            var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uid];
            var handle = inst && inst.measurementPanel;
            if (!st || !handle || typeof handle.setSummary !== 'function') return;
            var map = st.map;
            if (!map) return;

            var mc = map.getCenter();
            var bounds = map.getBounds();
            var best = null, bestD = Infinity;
            (st.facilities || []).forEach(function (fac) {
                var c = _facilityCenter_act(fac);
                if (!c) return;
                // 뷰포트 밖 시설은 제외 — c = [lng, lat]
                if (bounds && !bounds.contains([c[0], c[1]])) return;
                var d = (c[0] - mc.lng) * (c[0] - mc.lng) + (c[1] - mc.lat) * (c[1] - mc.lat);
                if (d < bestD) { bestD = d; best = fac; }
            });
            if (!best) { handle.setSummary([]); return; }

            var states = (st.statesByFac && st.statesByFac[best.unique_id]) || {};
            var slots = Object.keys(states);
            if (!slots.length) { handle.setSummary([]); return; }
            var saved = (st.orderByFac && st.orderByFac[best.unique_id]) || [];
            if (window.AoTActuatorOrder) {
                slots = window.AoTActuatorOrder.order(slots, saved, function (sk) {
                    return (states[sk] && states[sk].name) || sk;
                });
            }
            // Position actuators report on=true whenever position != 0, so the raw
            // flag cannot distinguish "moving" from "resting at 45%". Like the
            // marker pills (value_3way), detect motion via percent changes between
            // polls and color the number red only inside a short motion window.
            if (!st._sumPrevPct) { st._sumPrevPct = {}; st._sumMotionTs = {}; }
            var MOTION_WINDOW_MS = 7000;
            var items = slots.map(function (sk) {
                var s = states[sk];
                // Numbers for anything with a position/level; dot only for true on/off.
                if (s.percent != null || _actCtrlType(s) !== 'binary') {
                    var pct = s.percent != null ? parseFloat(s.percent) : (s.on ? 100 : 0);
                    var mkey = best.unique_id + '|' + sk;
                    var prev = st._sumPrevPct[mkey];
                    if (prev != null && Math.abs(pct - prev) > 0.5) {
                        st._sumMotionTs[mkey] = Date.now();
                    }
                    st._sumPrevPct[mkey] = pct;
                    var moving = (Date.now() - (st._sumMotionTs[mkey] || 0)) < MOTION_WINDOW_MS;
                    return { label: s.name || sk, value: pct.toFixed(0), on: moving };
                }
                // True binary: no position, just on/off dot
                return { label: s.name || sk, on: !!s.on };
            });
            handle.setSummary(items, best.name || '');
        }

        function _detachActuatorLabels(uid) {
            var st = _actLabelState[uid];
            if (!st) return;
            if (st.pollTimer) { clearInterval(st.pollTimer); }
            if (st.openPopup) { try { st.openPopup.remove(); } catch (e) {} }
            if (st.openSensorPopup) { try { st.openSensorPopup.remove(); } catch (e) {} }
            if (st.openBayPopup) { try { st.openBayPopup.remove(); } catch (e) {} }
            if (st.moveHandler && st.map) { try { st.map.off('move', st.moveHandler); } catch (e) {} }
            if (st.bayMoveHandler && st.map) { try { st.map.off('move', st.bayMoveHandler); } catch (e) {} }
            if (st.summaryMoveHandler && st.map) { try { st.map.off('moveend', st.summaryMoveHandler); } catch (e) {} }
            st.markers.forEach(function (m) { try { m.marker.remove(); } catch (e) {} });
            (st.bayMarkers || []).forEach(function (m) { try { m.marker.remove(); } catch (e) {} });
            var _wiDetach = window.AoTWidgetInstances[uid];
            if (_wiDetach && _wiDetach.bayMarkers === st.bayMarkers) _wiDetach.bayMarkers = [];
            delete _actLabelState[uid];
        }

        // Theme colors from geo/design panel settings
        // Device colors are stored by sub-type: theme['input'], theme['output'], theme['function']
        const theme = wOpts.theme_config || (vars && vars.theme) || {};
        const C = {
            site:      theme.site      || '#DF5353',
            zone:      theme.zone      || '#28a745',
            facility:  theme.facility  || '#82898f',
            equipment: theme.equipment || '#007bff',
            drawn:     theme.drawn     || '#f59e42'
        };
        // Data-driven device shape color: match GeoJSON device_type property to theme key
        const _devInputColor    = theme['input']    || '#995aff';
        const _devOutputColor   = theme['output']   || '#dd4444';
        const _devFunctionColor = theme['function'] || '#28a745';
        const _deviceColorExpr = ['match', ['get', 'device_type'],
            'input',    _devInputColor,
            'output',   _devOutputColor,
            'function', _devFunctionColor,
            _devInputColor
        ];

        // mapUuid: multiple fallback sources (fixes aot-device missing when contentMapUuid empty)
        const mapUuid = wOpts.selected_map_uuid || wOpts.map_uuid || (vars && vars.contentMapUuid) || '';

        // ============================================================
        // Sites — rendered only when show_site_shape is ON
        // ============================================================
        if (_boolOpt('show_site_shape')) {
            try {
                const sitesResponse = await geoFetch('/api/geo/sites?format=geojson');
                if (sitesResponse.ok) {
                    const sitesGeoJSON = await sitesResponse.json();
                    if (sitesGeoJSON.features && sitesGeoJSON.features.length > 0) {
                        addGeoJSONLayer(uniqueId, map, 'sites', sitesGeoJSON, {
                            type: 'fill',
                            paint: { 'fill-color': C.site, 'fill-opacity': 0.08 }
                        }, 'sites-fill');
                        addGeoJSONLayer(uniqueId, map, 'sites', sitesGeoJSON, {
                            type: 'line',
                            paint: { 'line-color': C.site, 'line-width': 3, 'line-opacity': 0.8 }
                        }, 'sites-line');
                    }
                }
            } catch (e) {
            }
        }

        // ============================================================
        // Zones — zone GeoJSON 은 도형(show_zone_shape) 뿐 아니라 zone
        // 라벨→모달 클릭 콜백(_onZoneLabelClick) 등록에도 필요하다. 라벨은
        // show_zone_label 로 도형과 독립 제어되므로, 둘 중 하나라도 켜져 있으면
        // fetch + 콜백 등록을 수행하고, 실제 fill/line 도형은 show_zone_shape
        // 일 때만 그린다. (과거엔 콜백이 show_zone_shape 에만 묶여 있어, 도형은
        // 끄고 라벨만 켠 경우 클릭 시 모달 대신 옛 maplibre 팝업이 떴다.)
        // ============================================================
        if (_boolOpt('show_zone_shape') || _boolOpt('show_zone_label')) {
            try {
                const zonesResponse = await geoFetch('/api/geo/zones?format=geojson');
                if (zonesResponse.ok) {
                    const zonesGeoJSON = await zonesResponse.json();
                    if (zonesGeoJSON.features && zonesGeoJSON.features.length > 0) {
                        if (_boolOpt('show_zone_shape')) {
                            addGeoJSONLayer(uniqueId, map, 'zones', zonesGeoJSON, {
                                type: 'fill',
                                paint: { 'fill-color': C.zone, 'fill-opacity': 0.1 }
                            }, 'zones-fill');
                            addGeoJSONLayer(uniqueId, map, 'zones', zonesGeoJSON, {
                                type: 'line',
                                paint: { 'line-color': C.zone, 'line-width': 2, 'line-dasharray': [2, 2], 'line-opacity': 0.8 }
                            }, 'zones-line');
                        }

                        // zone 도형 클릭은 비활성 — 라벨 버튼 클릭만 모달 열기

                        // node_id → uuid 맵 등록 (zone label click 콜백용)
                        // f.id = shape.unique_id (DB PK), f.properties.id = draw ID
                        var _zonesByNodeId = {};
                        zonesGeoJSON.features.forEach(function(f) {
                            if (f.properties && f.properties.node_id) {
                                _zonesByNodeId[f.properties.node_id] = f.id || f.properties.id;
                            }
                        });
                        var _inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uniqueId];
                        if (_inst) {
                            _inst._onZoneLabelClick = function(nodeId, zoneName) {
                                var zoneUuid = _zonesByNodeId[nodeId];
                                if (zoneUuid) _openZonePopup(uniqueId, zoneUuid, zoneName);
                            };
                        }
                    }
                }
            } catch (e) {
            }
        }

        // facility/equipment/device/drawn require mapUuid
        if (!mapUuid) return;

        // ============================================================
        // Facility shapes
        // ============================================================
        if (_boolOpt('show_facility_shape')) {
            try {
                const facRes = await geoFetch('/api/geo/overlays?map_uuid=' + encodeURIComponent(mapUuid) + '&type=facility');
                if (facRes.ok) {
                    const facGeoJSON = await facRes.json();
                    if (facGeoJSON.features && facGeoJSON.features.length > 0) {
                        addGeoJSONLayer(uniqueId, map, 'facilities', facGeoJSON, {
                            type: 'fill',
                            paint: { 'fill-color': C.facility, 'fill-opacity': 0.15 }
                        }, 'facilities-fill');
                        addGeoJSONLayer(uniqueId, map, 'facilities', facGeoJSON, {
                            type: 'line',
                            paint: { 'line-color': C.facility, 'line-width': 1.5 }
                        }, 'facilities-line');
                        addGeoJSONLayer(uniqueId, map, 'facilities', facGeoJSON, {
                            type: 'fill-extrusion',
                            layout: { visibility: 'none' },
                            paint: {
                                'fill-extrusion-color': C.facility,
                                'fill-extrusion-height': ['coalesce', ['get', 'height_m'], 4],
                                'fill-extrusion-base':   ['coalesce', ['get', 'base_m'], 0],
                                'fill-extrusion-opacity': 0.55
                            }
                        }, 'facilities-3d');

                        // Attach Three.js greenhouse model overlay (replaces fill-extrusion box)
                        if (window.AoTFacilityMap3D && window.AoTFacility3D) {
                            try {
                                const facListRes = await geoFetch('/api/geo/facility/list?geo_id=' + encodeURIComponent(mapUuid));
                                if (facListRes.ok) {
                                    const facListData = await facListRes.json();
                                    const facilities3d = (facListData.facilities || facListData || []).filter(function(f) {
                                        return f.geometry_3d && f.outer_feature;
                                    });
                                    // Cache for style-reload rehydration (no re-fetch needed).
                                    const _fi = window.AoTWidgetInstances[uniqueId];
                                    if (_fi) _fi.cachedFacilities3d = facilities3d;
                                    if (facilities3d.length) {
                                        AoTFacilityMap3D.attach(map, facilities3d, { hideLayers: ['facilities-3d'], renderMode: wOpts.facility_render_mode || 'default' });
                                        // Sensor value labels (overlay markers + 24h popup)
                                        if (window.AoTMapSensorLabels) {
                                            try {
                                                AoTMapSensorLabels.attach(uniqueId, map, facilities3d, _sensorLabelOpts(vars));
                                            } catch (eSL) {
                                            }
                                        }
                                        // Actuator category labels (map markers + popup controls)
                                        try {
                                            _attachActuatorLabels(uniqueId, facilities3d, wOpts, map, vars.refreshSeconds);
                                        } catch (eAL) {
                                        }
                                    }
                                }
                            } catch (e3d) {
                            }
                        }
                    }
                }
            } catch (e) {
            }
        }

        // ============================================================
        // Equipment shapes
        // ============================================================
        if (_boolOpt('show_equipment_shape')) {
            try {
                const eqRes = await geoFetch('/api/geo/overlays?map_uuid=' + encodeURIComponent(mapUuid) + '&type=equipment');
                if (eqRes.ok) {
                    const eqGeoJSON = await eqRes.json();
                    if (eqGeoJSON.features && eqGeoJSON.features.length > 0) {
                        addGeoJSONLayer(uniqueId, map, 'equipment', eqGeoJSON, {
                            type: 'line',
                            paint: { 'line-color': C.equipment, 'line-width': 2, 'line-opacity': 0.9 }
                        }, 'equipment-line');
                        addGeoJSONLayer(uniqueId, map, 'equipment', eqGeoJSON, {
                            type: 'fill',
                            // 배관(pipe_main/pipe_branch)은 선으로만 그린다. fill은
                            // sprinkler_coverage 등 면(폴리곤) 설비에만 적용.
                            filter: ['!', ['in', ['get', 'sub_type'], ['literal', ['pipe_main', 'pipe_branch']]]],
                            paint: { 'fill-color': C.equipment, 'fill-opacity': 0.12 }
                        }, 'equipment-fill');
                    }
                }
            } catch (e) {
            }
        }

        // ============================================================
        // Device shapes (aot_device) — on:0.9 / off:0.2 via data-driven expr
        // Initial state: all OFF (0.2); updated after device fetch
        // ============================================================
        if (_boolOpt('show_device_shapes')) {
            try {
                const devRes = await geoFetch('/api/geo/overlays?map_uuid=' + encodeURIComponent(mapUuid) + '&type=aot_device');
                if (devRes.ok) {
                    const devGeoJSON = await devRes.json();
                    if (devGeoJSON.features && devGeoJSON.features.length > 0) {
                        addGeoJSONLayer(uniqueId, map, 'aot_devices', devGeoJSON, {
                            type: 'line',
                            paint: { 'line-color': _deviceColorExpr, 'line-width': 2, 'line-opacity': 0.5 }
                        }, 'aot-devices-line');
                        addGeoJSONLayer(uniqueId, map, 'aot_devices', devGeoJSON, {
                            type: 'fill',
                            paint: { 'fill-color': _deviceColorExpr, 'fill-opacity': 0.2 }
                        }, 'aot-devices-fill');
                    }
                }
            } catch (e) {
            }
        }

        // ============================================================
        // Drawn shapes (other drawn shapes — types not in known list)
        // ============================================================
        if (_boolOpt('show_drawn_shapes')) {
            try {
                const KNOWN_TYPES = new Set([
                    'site', 'zone', 'facility', 'facility_bay',
                    'equipment', 'equipment_collection',
                    'aot_device', 'connection', 'label_aux'
                ]);
                const allRes = await geoFetch('/api/geo/overlays?map_uuid=' + encodeURIComponent(mapUuid));
                if (allRes.ok) {
                    const allGeoJSON = await allRes.json();
                    if (allGeoJSON.features) {
                        const drawnFeatures = allGeoJSON.features.filter(function(f) {
                            const t = ((f.properties || {}).aot_type || '').toLowerCase();
                            return t && !KNOWN_TYPES.has(t);
                        });
                        if (drawnFeatures.length > 0) {
                            const drawnGeoJSON = { type: 'FeatureCollection', features: drawnFeatures };
                            addGeoJSONLayer(uniqueId, map, 'drawn_shapes', drawnGeoJSON, {
                                type: 'fill',
                                paint: { 'fill-color': C.drawn, 'fill-opacity': 0.2 }
                            }, 'drawn-shapes-fill');
                            addGeoJSONLayer(uniqueId, map, 'drawn_shapes', drawnGeoJSON, {
                                type: 'line',
                                paint: { 'line-color': C.drawn, 'line-width': 2, 'line-opacity': 0.8 }
                            }, 'drawn-shapes-line');
                        }
                    }
                }
            } catch (e) {
            }
        }
    }

    /**
     * Load geo/design label_aux markers and render them as HTML markers
     * matching the geo/design visual style.
     */

    /**
     * Shared label collision + clustering.
     * Overlapping markers are hidden and replaced with a cluster badge showing the count.
     * Clicking the badge flies/fits the map so the individual labels become visible.
     *
     * @param {maplibregl.Marker[]} markers  All label markers to process
     * @param {maplibregl.Map}      map
     * @param {number}              spacing  Extra padding (px) around each label rect
     * @param {object}              instance Widget instance
     * @param {string}              clusterKey  instance[clusterKey] = cluster marker array
     */
    // ── Inline hex→rgba (no external dep, hoisted here so all label helpers can use it) ──
    function _clusterHexRgba(hex, a) {
        if (!hex || hex[0] !== '#') return 'rgba(153,90,255,' + a + ')';
        var r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
        return 'rgba('+r+','+g+','+b+','+a+')';
    }

    /**
     * Show a floating popup listing co-located cluster members.
     * Used when labels share the same (or very close) coordinates and cannot
     * be separated by zooming, so flyTo/fitBounds would just re-cluster them.
     */
    function _showColocatedPopup(members, anchorEl) {
        var existing = document.getElementById('aot-cluster-popup');
        if (existing) { existing.remove(); return; }

        var popup = document.createElement('div');
        popup.id = 'aot-cluster-popup';
        popup.style.cssText = [
            'position:fixed',
            'z-index:var(--aot-z-fixed-panel)',
            'background:#1e293b',
            'border:1px solid rgba(255,255,255,0.15)',
            'border-radius:8px',
            'padding:6px 0',
            'box-shadow:0 4px 16px rgba(0,0,0,0.5)',
            'font-family:var(--aot-font-family,Inter,sans-serif)',
            'font-size:13px',
            'min-width:140px',
            'max-width:240px'
        ].join(';');

        members.forEach(function(m) {
            var item = document.createElement('div');
            item.style.cssText = 'padding:5px 12px;color:#f8fafc;display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden;';
            item.innerHTML =
                '<span style="width:8px;height:8px;border-radius:50%;background:' + (m.color || '#995aff') + ';flex-shrink:0;display:inline-block"></span>' +
                '<span style="overflow:hidden;text-overflow:ellipsis">' + (m.name || '?') + '</span>';
            popup.appendChild(item);
        });

        var rect = anchorEl.getBoundingClientRect();
        popup.style.left = rect.left + 'px';
        popup.style.top  = (rect.bottom + 4) + 'px';
        document.body.appendChild(popup);

        requestAnimationFrame(function() {
            var pr = popup.getBoundingClientRect();
            if (pr.right > window.innerWidth - 8)
                popup.style.left = Math.max(8, window.innerWidth - pr.width - 8) + 'px';
            if (pr.bottom > window.innerHeight - 8)
                popup.style.top = Math.max(8, rect.top - pr.height - 4) + 'px';
        });

        setTimeout(function() {
            function _close(ev) {
                if (!popup.contains(ev.target)) {
                    popup.remove();
                    document.removeEventListener('click', _close, true);
                }
            }
            document.addEventListener('click', _close, true);
        }, 0);
    }

    /**
     * Single-group collision pass.
     *
     * @param {maplibregl.Marker[]} markers      Markers for THIS group only.
     * @param {maplibregl.Map}      map
     * @param {number}              spacing      Extra px padding around each label.
     * @param {object}              instance     Widget instance.
     * @param {string}              clusterKey   instance[clusterKey] = array of cluster badge markers.
     * @param {Array}               preOccupied  Rects already taken by higher-priority groups
     *                                           (same coordinate system as getBoundingClientRect).
     * @returns {Array} Rects occupied by visible solo labels in this group (for next group's preOccupied).
     */
    function runLabelCollisionWithClustering(markers, map, spacing, instance, clusterKey, preOccupied) {
        preOccupied = preOccupied || [];
        var placedRects = [];   // rects of solo visible labels → fed to lower-priority groups

        // Remove previous cluster badges
        if (instance[clusterKey]) {
            instance[clusterKey].forEach(function(m) { try { m.remove(); } catch(e) {} });
        }
        instance[clusterKey] = [];

        if (!markers || markers.length === 0) return placedRects;

        // Reset all to invisible-but-in-layout
        markers.forEach(function(mk) {
            var e = mk.getElement();
            e.style.display = 'block';
            e.style.opacity = '0';
            e.style.pointerEvents = 'none';
        });

        // Sort: highest zIndex first
        var sorted = markers.slice().sort(function(a, b) {
            var za = parseInt(a.getElement().style.zIndex) || 0;
            var zb = parseInt(b.getElement().style.zIndex) || 0;
            return zb - za;
        });

        if (sorted.length > 0) void sorted[0].getElement().offsetWidth; // force reflow

        var n = sorted.length;
        var sp = spacing;

        function _overlaps(ra, rb) {
            return !(ra.right <= rb.left || ra.left >= rb.right ||
                     ra.bottom <= rb.top  || ra.top  >= rb.bottom);
        }

        // Build padded rects + flag markers conflicted by higher-priority groups
        var rects = sorted.map(function(mk) {
            var r = mk.getElement().getBoundingClientRect();
            var padded = {
                left:   r.left   - sp,
                right:  r.right  + sp,
                top:    r.top    - sp,
                bottom: r.bottom + sp,
                valid:  r.width > 1,
                conflicted: false
            };
            if (padded.valid) {
                for (var pi = 0; pi < preOccupied.length; pi++) {
                    if (_overlaps(padded, preOccupied[pi])) {
                        padded.conflicted = true;
                        // Remember which higher-priority (site/zone) label swallowed this
                        // one, so we can surface a "+N hidden" indicator on it. Without
                        // this, devices absorbed under a site/zone label vanish silently.
                        padded.absorbedBy = preOccupied[pi].el || null;
                        break;
                    }
                }
            }
            return padded;
        });

        // Hide conflicted markers immediately (higher-priority group wins).
        rects.forEach(function(rect, idx) {
            if (rect.conflicted) {
                sorted[idx].getElement().style.display = 'none';
                if (rect.absorbedBy) rect.absorbedBy.__absorbedCount = (rect.absorbedBy.__absorbedCount || 0) + 1;
            }
        });

        // Union-Find on non-conflicted, valid markers only
        var parent = [];
        for (var ii = 0; ii < n; ii++) parent[ii] = ii;
        function ufFind(x) { return parent[x] === x ? x : (parent[x] = ufFind(parent[x])); }

        for (var ii = 0; ii < n; ii++) {
            if (rects[ii].conflicted || !rects[ii].valid) continue;
            for (var jj = ii + 1; jj < n; jj++) {
                if (rects[jj].conflicted || !rects[jj].valid) continue;
                if (_overlaps(rects[ii], rects[jj])) {
                    var rootI = ufFind(ii), rootJ = ufFind(jj);
                    if (rootI !== rootJ) parent[rootI] = rootJ;
                }
            }
        }

        // Build groups (non-conflicted only)
        var groups = {};
        for (var ii = 0; ii < n; ii++) {
            if (rects[ii].conflicted) continue;
            var root = ufFind(ii);
            if (!groups[root]) groups[root] = [];
            groups[root].push(ii);
        }

        // Process each group
        Object.keys(groups).forEach(function(root) {
            var group = groups[root];

            if (group.length === 1) {
                var mk = sorted[group[0]];
                var e  = mk.getElement();
                if (!rects[group[0]].valid) {
                    e.style.display = 'none';
                } else {
                    e.style.opacity = '1';
                    e.style.pointerEvents = 'auto';
                    rects[group[0]].el = e; // owner, so lower tiers can attribute absorptions
                    placedRects.push(rects[group[0]]); // reserve for lower-priority groups
                }
            } else {
                // Hide all members, show cluster badge
                var lngLats = [];
                var members = [];
                group.forEach(function(idx) {
                    sorted[idx].getElement().style.display = 'none';
                    lngLats.push(sorted[idx].getLngLat());
                    var el = sorted[idx].getElement();
                    members.push({ name: el.dataset.labelName || '', color: el.dataset.labelColor || '#995aff' });
                });

                var sumLng = 0, sumLat = 0;
                lngLats.forEach(function(ll) { sumLng += ll.lng; sumLat += ll.lat; });
                var cLng = sumLng / lngLats.length;
                var cLat = sumLat / lngLats.length;

                // Representative: lowest sorted index = highest zIndex
                var repIdx   = group.reduce(function(a, b) { return a < b ? a : b; });
                var repEl    = sorted[repIdx].getElement();
                var repName  = repEl.dataset.labelName  || '';
                var repColor = repEl.dataset.labelColor || '#995aff';
                var repLabel = repName.length > 8 ? repName.substring(0, 7) + '…' : repName;
                var badgeBg     = _clusterHexRgba(repColor, 0.92);
                var badgeShadow = _clusterHexRgba(repColor, 0.40);

                var clusterEl = document.createElement('div');
                clusterEl.className = 'aot-label-cluster';
                clusterEl.style.cssText = [
                    'background-color:' + badgeBg,
                    'color:#fff',
                    'border-radius:14px',
                    'height:28px',
                    'padding:0 8px',
                    'display:inline-flex',
                    'align-items:center',
                    'gap:4px',
                    'font-weight:var(--aot-fw-bold)',
                    'font-size:var(--aot-fs-label)',
                    'cursor:pointer',
                    'box-shadow:0 2px 6px ' + badgeShadow,
                    'border:2px solid #fff',
                    'z-index:10',
                    'user-select:none',
                    'white-space:nowrap',
                    'max-width:160px',
                    // iOS: ensure taps register as taps (no 300ms delay / double-tap zoom)
                    'touch-action:manipulation',
                    // Created hidden; _deconflictClusterBadges reveals the survivors in
                    // the next frame. Prevents the 1-frame flash where a badge appears,
                    // then gets hidden by deconfliction (load/zoom flicker). Use
                    // visibility (not display) so it still has size for measurement.
                    'visibility:hidden'
                ].join(';');
                // "+N" as plain text — no wrapping box (background/rounded/padding removed).
                clusterEl.innerHTML =
                    '<span style="overflow:hidden;text-overflow:ellipsis;max-width:90px">' + repLabel + '</span>' +
                    '<span style="font-size:var(--aot-fs-caption);flex-shrink:0">+' + (group.length - 1) + '</span>';

                (function(lls, centerLng, centerLat, mbrs) {
                    function _activate(e) {
                        // Stop the map from treating the tap as a gesture. On touchend,
                        // preventDefault also cancels the emulated click → no double-fire.
                        if (e) { e.stopPropagation(); if (e.cancelable) e.preventDefault(); }
                        var minLng = Math.min.apply(null, lls.map(function(l) { return l.lng; }));
                        var maxLng = Math.max.apply(null, lls.map(function(l) { return l.lng; }));
                        var minLat = Math.min.apply(null, lls.map(function(l) { return l.lat; }));
                        var maxLat = Math.max.apply(null, lls.map(function(l) { return l.lat; }));
                        // Threshold ~5 m: labels this close cannot be separated by any zoom level,
                        // so zooming just re-clusters them — show a member list popup instead.
                        var colocated = (maxLng - minLng) < 0.00005 && (maxLat - minLat) < 0.00005;
                        if (colocated) {
                            _showColocatedPopup(mbrs, clusterEl);
                        } else {
                            // Padding must scale with the map container. A fixed 120px ate
                            // small widgets / phone screens whole → fitBounds had no room to
                            // zoom and did nothing. Keep it a small fraction of the shorter
                            // side, capped, so there is always room to zoom in.
                            var _c = map.getContainer ? map.getContainer() : null;
                            var _minDim = _c ? Math.min(_c.clientWidth || 400, _c.clientHeight || 400) : 400;
                            var _pad = Math.max(8, Math.min(60, Math.floor(_minDim * 0.1)));
                            map.fitBounds([[minLng, minLat], [maxLng, maxLat]], { padding: _pad, maxZoom: 22, duration: 600 });
                        }
                    }
                    // iOS Safari often swallows the synthetic click on map-overlay
                    // markers, so bind touchend directly. Guard so touchend and the
                    // following emulated click do NOT both run fitBounds (double-fire
                    // cancels the animation → stays put + flickers).
                    var _lastTouchTs = 0;
                    var _tStart = null;
                    clusterEl.addEventListener('click', function (e) {
                        if (Date.now() - _lastTouchTs < 700) return; // already handled by touchend
                        _activate(e);
                    });
                    clusterEl.addEventListener('touchstart', function (e) {
                        var t = e.touches && e.touches[0];
                        _tStart = t ? { x: t.clientX, y: t.clientY } : null;
                    }, { passive: true });
                    clusterEl.addEventListener('touchend', function (e) {
                        var t = e.changedTouches && e.changedTouches[0];
                        if (_tStart && t && (Math.abs(t.clientX - _tStart.x) > 10 || Math.abs(t.clientY - _tStart.y) > 10)) {
                            _tStart = null; return; // moved too far → a drag, not a tap
                        }
                        _tStart = null;
                        _lastTouchTs = Date.now();
                        _activate(e);
                    });
                })(lngLats, cLng, cLat, members);

                var clusterMarker = new maplibregl.Marker({ element: clusterEl, anchor: 'center' })
                    .setLngLat([cLng, cLat])
                    .addTo(map);
                instance[clusterKey].push(clusterMarker);
            }
        });

        return placedRects;
    }

    /**
     * Post-pass: after all group collision runs, deconflict the cluster BADGES themselves.
     * Priority: siteZone > geoDevice > device.
     * Lower-priority badges that overlap a higher-priority badge are hidden.
     */
    function _deconflictClusterBadges(instance, spacing) {
        var sp = spacing;
        var tiers = [
            instance.siteZoneClusterMarkers  || [],   // priority 1
            instance.geoDeviceClusterMarkers || [],   // priority 2
            instance.deviceClusterMarkers    || []    // priority 3
        ];
        var placedBadgeRects = [];

        tiers.forEach(function(clusterArr) {
            clusterArr.forEach(function(cm) {
                var e = cm.getElement();
                var r = e.getBoundingClientRect();
                if (r.width <= 1) { e.style.display = 'none'; return; }
                var rect = { left: r.left - sp, right: r.right + sp, top: r.top - sp, bottom: r.bottom + sp };
                var blocked = placedBadgeRects.some(function(pr) {
                    return !(rect.right <= pr.left || rect.left >= pr.right ||
                             rect.bottom <= pr.top  || rect.top  >= pr.bottom);
                });
                if (blocked) {
                    e.style.display = 'none';
                } else {
                    placedBadgeRects.push(rect);
                    // Badges are created visibility:hidden; reveal only the survivors
                    // here (after deconfliction) so none flash on first paint.
                    e.style.visibility = 'visible';
                }
            });
        });
    }

    /**
     * Run all three group passes in priority order, then deconflict badges.
     * siteZone (1) → geoDevice (2) → pillDevice (3)
     */
    function _runUnifiedLabelCollision(instance, map, spacing) {
        var sp = spacing;

        // Reset absorbed-device counters on site/zone labels (recomputed below).
        (instance.siteZoneLabelMarkers || []).forEach(function(m) {
            var e = m.getElement && m.getElement(); if (e) e.__absorbedCount = 0;
        });

        // Pass 1: site + zone (no pre-occupied)
        var occ1 = runLabelCollisionWithClustering(
            instance.siteZoneLabelMarkers  || [], map, sp, instance, 'siteZoneClusterMarkers', []
        );

        // Pass 2: geo aot_device labels (must avoid site+zone areas)
        var occ2 = runLabelCollisionWithClustering(
            instance.geoDeviceLabelMarkers || [], map, sp, instance, 'geoDeviceClusterMarkers', occ1
        );

        // Pass 3: pill device markers (lowest priority)
        runLabelCollisionWithClustering(
            instance.deviceLabelMarkers    || [], map, sp, instance, 'deviceClusterMarkers', occ1.concat(occ2)
        );

        // Represent device labels absorbed under a site/zone label using the SAME
        // cluster-badge mechanism as everything else ("name +N"), not an inline
        // label tweak — so absorbed devices aren't invisible until you zoom in.
        _renderAbsorbedDeviceBadges(instance, map);

        // Badge-level deconfliction in next frame (badges need to be rendered first)
        requestAnimationFrame(function() {
            _deconflictClusterBadges(instance, sp);
        });
    }

    // For each visible site/zone label that swallowed device labels, hide the plain
    // label and show a standard cluster badge ("name +N") at its position — exactly
    // like the within-tier cluster badges. Clicking zooms in to reveal the devices.
    function _renderAbsorbedDeviceBadges(instance, map) {
        if (instance.absorbBadges) instance.absorbBadges.forEach(function(m) { try { m.remove(); } catch (e) {} });
        instance.absorbBadges = [];
        (instance.siteZoneLabelMarkers || []).forEach(function(m) {
            var e = m.getElement && m.getElement(); if (!e) return;
            // Remove any stale inline span left by an older build.
            var stale = e.querySelector('.aot-absorb-dev'); if (stale) stale.remove();
            var n = e.__absorbedCount || 0;
            if (n <= 0 || e.style.display === 'none') return;
            var name = e.dataset.labelName || '';
            var color = e.dataset.labelColor || '#995aff';
            var rep = name.length > 8 ? name.substring(0, 7) + '…' : name;
            var bg = _clusterHexRgba(color, 0.92), sh = _clusterHexRgba(color, 0.40);
            e.style.display = 'none'; // hide the plain label; the badge stands in for it
            var b = document.createElement('div');
            b.className = 'aot-label-cluster';
            b.style.cssText = [
                'background-color:' + bg, 'color:#fff', 'border-radius:14px', 'height:28px',
                'padding:0 8px', 'display:inline-flex', 'align-items:center', 'gap:4px',
                'font-weight:var(--aot-fw-bold)', 'font-size:var(--aot-fs-label)', 'cursor:pointer',
                'box-shadow:0 2px 6px ' + sh, 'border:2px solid #fff', 'z-index:10',
                'user-select:none', 'white-space:nowrap', 'max-width:160px', 'touch-action:manipulation'
            ].join(';');
            b.innerHTML =
                '<span style="overflow:hidden;text-overflow:ellipsis;max-width:90px">' + rep + '</span>' +
                '<span style="font-size:var(--aot-fs-caption);flex-shrink:0">+' + n + '</span>';
            var _ll = m.getLngLat(); // badge sits on the label position
            b.addEventListener('click', function (ev) {
                ev.stopPropagation();
                // Zoom in CENTERED on this badge so the absorbed devices reveal here —
                // zoomTo() without a center would zoom toward the map center (wrong place).
                try { map.easeTo({ center: _ll, zoom: map.getZoom() + 2, duration: 300 }); } catch (e) {}
            });
            try {
                var mk = new maplibregl.Marker({ element: b, anchor: 'center' }).setLngLat(_ll).addTo(map);
                instance.absorbBadges.push(mk);
            } catch (e) {}
        });
    }

    /**
     * Run a label cluster pass once the map is settled. If already settled, do it
     * next frame (positions are final); otherwise wait for 'idle'.
     */
    function _revealLabelsOnce(instance, map, spacing) {
        function run() {
            if (!window.AoTWidgetInstances[instance.uniqueId]) return; // torn down
            _runUnifiedLabelCollision(instance, map, spacing);
        }
        var settled = (typeof map.loaded === 'function' ? map.loaded() : true)
            && !(typeof map.isMoving === 'function' && map.isMoving());
        if (settled) { requestAnimationFrame(run); } else { map.once('idle', run); }
    }

    /**
     * Register (or replace) the single unified collision handler on the map.
     * Call this whenever geo-labels or device-labels are refreshed.
     */
    function _updateUnifiedCollisionHandler(instance, map, spacing) {
        var sp = spacing;

        // Remove old handler
        if (instance._unifiedCollisionHandler) {
            map.off('moveend', instance._unifiedCollisionHandler);
            map.off('zoomend', instance._unifiedCollisionHandler);
            instance._unifiedCollisionHandler = null;
        }

        var _debounce;
        function debouncedUnified() {
            clearTimeout(_debounce);
            _debounce = setTimeout(function() {
                requestAnimationFrame(function() { _runUnifiedLabelCollision(instance, map, sp); });
            }, 150);
        }

        instance._unifiedCollisionHandler = debouncedUnified;
        // Only re-cluster on ZOOM change. A pan translates every marker by the same
        // pixel offset, so relative overlaps — and therefore the clustering result —
        // are unchanged; rebuilding on every 'moveend' (pan) only caused flicker
        // (badges removed/recreated, then deconflicted a frame later). Cluster badges
        // are real markers at the centroid lng/lat, so they pan correctly on their own.
        map.on('zoomend', debouncedUnified);
    }

    async function loadGeoDesignLabels(uniqueId, map, vars) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        // Remove old label markers and clean up collision listeners before re-loading
        ['labelMarkers', 'siteZoneLabelMarkers', 'geoDeviceLabelMarkers'].forEach(function(key) {
            if (instance[key] && instance[key].length > 0) {
                instance[key].forEach(function(m) { try { m.remove(); } catch(e) {} });
            }
            instance[key] = [];
        });
        ['labelClusterMarkers', 'siteZoneClusterMarkers', 'geoDeviceClusterMarkers', 'absorbBadges'].forEach(function(key) {
            if (instance[key] && instance[key].length > 0) {
                instance[key].forEach(function(m) { try { m.remove(); } catch(e) {} });
            }
            instance[key] = [];
        });
        // Remove old per-group handler (legacy) and unified handler
        if (instance._collisionHandler) {
            map.off('moveend', instance._collisionHandler);
            map.off('zoomend', instance._collisionHandler);
            instance._collisionHandler = null;
        }

        const mapUuid = (vars && vars.contentMapUuid) || '';
        if (!mapUuid) return;

        const wOpts = (vars && vars.vars) || {};
        const showSiteLabel    = wOpts.show_site_label   === true || wOpts.show_site_label   === 'true';
        const showZoneLabel    = wOpts.show_zone_label   === true || wOpts.show_zone_label   === 'true';
        const showDeviceLabels = wOpts.show_device_labels === true || wOpts.show_device_labels === 'true';
        const labelCollision   = wOpts.enable_label_collision !== false && wOpts.enable_label_collision !== 'false';
        const _rawSpacing      = parseInt(wOpts.label_spacing);
        const labelSpacing     = (!isNaN(_rawSpacing) && wOpts.label_spacing !== '' && wOpts.label_spacing !== null && wOpts.label_spacing !== undefined) ? _rawSpacing : 0;
        const globalLabelSize  = parseFloat(wOpts.global_label_size) || 1.0;
        const labelFontPx      = Math.round(globalLabelSize * 14);

        // Skip if no label type is enabled
        if (!showSiteLabel && !showZoneLabel && !showDeviceLabels) return;

        // Build allowed device ID set (mirrors addDeviceMarkers) so device labels
        // only render for devices the widget is configured to display.
        const allowedDeviceIds = new Set();
        const _fetchIdsLbl = wOpts.map_device_ids || wOpts.device_ids;
        if (_fetchIdsLbl && wOpts.include_all_devices !== true) {
            String(_fetchIdsLbl).split(',').forEach(function(id) {
                const t = id.trim();
                if (t) {
                    allowedDeviceIds.add(t);
                    if (t.includes('::')) allowedDeviceIds.add(t.split('::')[0]);
                }
            });
        }
        const isStrictDeviceLabelFilter = (allowedDeviceIds.size > 0 && wOpts.include_all_devices !== true);

        // Theme colors from geo/design panel settings (mirrors shape fill color logic above)
        const labelTheme = wOpts.theme_config || (vars && vars.theme) || {};
        const COLOR_MAP = {
            'site':       labelTheme.site      || '#DF5353',
            'zone':       labelTheme.zone      || '#28a745',
            'facility':   labelTheme.facility  || '#82898f',
            'equipment':  labelTheme.equipment || '#007bff',
            'device':     labelTheme['input']  || '#995aff',
            'aot_device': labelTheme['input']  || '#995aff'
        };
        // 넓은 영역일수록 아래, 구체 대상일수록 위: 대지(site) < 구역(zone)
        // < 시설(facility) < 장비/장치. 시설 라벨이 대지 라벨에 가리지 않게 한다.
        const ZINDEX_MAP = {
            'site':       3,
            'zone':       2,
            'facility':   5,
            'equipment':  6,
            'device':     6,
            'aot_device': 6
        };

        try {
            const url = '/api/geo/overlays?map_uuid=' + encodeURIComponent(mapUuid) + '&type=label_aux';
            const res = await geoFetch(url);
            if (!res.ok) return;

            const geojson = await res.json();
            if (!geojson.features || geojson.features.length === 0) return;

            if (!instance.labelMarkers) instance.labelMarkers = [];

            geojson.features.forEach(function(feature) {
                if (!feature.geometry || feature.geometry.type !== 'Point') return;
                const coords = feature.geometry.coordinates;
                const props = feature.properties || {};
                const pType = props.parent_type || '';

                // Respect show_site_label / show_zone_label / show_device_labels options
                if (pType === 'site' && !showSiteLabel) return;
                if (pType === 'zone' && !showZoneLabel) return;
                if (pType === 'aot_device' && !showDeviceLabels) return;

                // Strict device-label filtering: hide labels for devices not in selection
                if (pType === 'aot_device' && isStrictDeviceLabelFilter) {
                    const _devLabelId = String(props.device_id || props.parent_id || props.db_id || '');
                    const _devLabelBase = _devLabelId.split('::')[0];
                    if (!allowedDeviceIds.has(_devLabelId) && !allowedDeviceIds.has(_devLabelBase)) return;
                }

                const color  = COLOR_MAP[pType] || '#666';
                const zIndex = ZINDEX_MAP[pType] || 2;
                const name   = props.label_name || '';
                const area   = props.label_area  || '';

                const el = document.createElement('div');
                el.className = 'geo-label-marker';
                el.dataset.labelName  = name;
                el.dataset.labelColor = color;
                el.style.cssText = [
                    'background-color:' + color,
                    'color:white',
                    'border-radius:4px',
                    'padding:2px 8px',
                    'box-shadow:0 2px 4px rgba(0,0,0,0.3)',
                    'text-align:center',
                    'font-size:' + labelFontPx + 'px',
                    'cursor:pointer',
                    'white-space:nowrap'
                ].join(';');
                // Store parent type/id for device-state refresh in the periodic cycle
                el.dataset.parentType = pType;
                el.dataset.parentId   = String(props.parent_id || props.db_id || '');
                // Apply persisted per-category label-hidden state immediately —
                // this function runs before addLayerPanel's toolbar seeds
                // instance._hiddenLabels, so without this a hidden category would
                // render visible first and only hide once the toolbar catches up.
                if (pType !== 'aot_device' && instance._hiddenLabels && instance._hiddenLabels[pType]) {
                    el.classList.add('aot-type-hidden');
                }

                const nameDiv = document.createElement('div');
                nameDiv.style.fontWeight = 'bold';
                nameDiv.textContent = name;
                el.appendChild(nameDiv);

                // [3-way Actuator] Empty value slot for aot_device labels.
                // Filled in _updateGeoDesignDeviceLabels when device state arrives.
                if (pType === 'aot_device') {
                    const valSpan = document.createElement('span');
                    valSpan.className = 'aot-3way-pct';
                    valSpan.style.cssText = 'margin-left:4px;font-weight:bold;display:none;';
                    nameDiv.appendChild(valSpan);
                }

                const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
                    .setLngLat([coords[0], coords[1]])
                    .addTo(map);

                el.style.zIndex = String(zIndex);

                // Click → popup (v3 port: name + Open Notes button + last note preview)
                (function(lngLat, popupName, popupArea, tId, tType, nodeId) {
                    el.addEventListener('click', function(e) {
                        e.stopPropagation();
                        // zone label → zone modal (if callback registered)
                        if (tType === 'zone' && instance._onZoneLabelClick) {
                            instance._onZoneLabelClick(nodeId, popupName);
                            return;
                        }
                        if (instance._labelPopup) { instance._labelPopup.remove(); }
                        var noteElId = 'label-note-' + tId;
                        var safeName = (popupName || '').replace(/'/g, "\\'");
                        var openNoteAction = 'window.dispatchEvent(new CustomEvent(\'open-notes\',{detail:{targetId:\'' + tId + '\',targetType:\'' + tType + '\',name:\'' + safeName + '\'}}))';
                        var html = '<div class="aot-popup-body">'
                            + '<div class="aot-popup-title">' + popupName + '</div>'
                            + (popupArea ? '<div class="aot-popup-subtitle">' + popupArea + '</div>' : '')
                            + '<hr class="aot-popup-divider">'
                            + '<button class="aot-popup-btn aot-popup-btn--primary aot-popup-btn--full" onclick="' + openNoteAction + '">'
                            + (window._ ? window._('Open Notes') : 'Open Notes') + '</button>'
                            + '<div id="' + noteElId + '" class="aot-popup-note-preview">'
                            + (window._ ? window._('Loading...') : 'Loading...') + '</div>'
                            + '</div>';
                        instance._labelPopup = new maplibregl.Popup({ offset: 12, closeOnClick: true, className: 'aot-popup aot-popup--label' })
                            .setLngLat(lngLat)
                            .setHTML(html)
                            .addTo(map);
                        // Fetch last note
                        setTimeout(function() {
                            fetch('/notes/target/' + tId)
                                .then(function(r) { return r.json(); })
                                .then(function(notes) {
                                    var el = document.getElementById(noteElId);
                                    if (!el) return;
                                    if (notes && notes.length > 0) {
                                        var txt = notes[0].note || '';
                                        el.innerText = txt.substring(0, 30) + (txt.length > 30 ? '...' : '');
                                        el.style.color = '#555';
                                    } else {
                                        el.innerText = window._ ? window._('No notes written') : 'No notes written';
                                        el.style.color = '#ccc';
                                    }
                                }).catch(function() {});
                        }, 100);
                    });
                }([coords[0], coords[1]], name, area,
                  props.db_id || props.parent_id || name,
                  props.parent_type || 'site',
                  props.parent_node_id || ''));

                instance.labelMarkers.push(marker);
                // Split by group: site+zone vs aot_device
                if (pType === 'site' || pType === 'zone') {
                    instance.siteZoneLabelMarkers.push(marker);
                } else if (pType === 'aot_device') {
                    instance.geoDeviceLabelMarkers.push(marker);
                }
            });

            // Unified collision — all groups in priority order via single handler.
            if (labelCollision) {
                instance._labelSpacing = labelSpacing;
                _updateUnifiedCollisionHandler(instance, map, labelSpacing);
                // Reveal hidden labels with a SINGLE pass at a settled time. Running both
                // an early rAF AND a later idle pass made boundary labels (e.g. an input
                // label next to a site/zone) flicker: the two passes clustered differently
                // because positions were still moving. If the map is already settled, do it
                // next frame; otherwise wait for idle. Either way, exactly one reveal pass.
                _revealLabelsOnce(instance, map, labelSpacing);
            }

        } catch (e) {
        }
    }

    /**
     * Add GeoJSON layer to map.
     *
     * @param {object} layerConfig  { type: 'fill'|'line'|'fill-extrusion', paint: {...}, layout?: {...} }
     */
    function addGeoJSONLayer(uniqueId, map, sourceId, geojson, layerConfig, layerId) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        const actualLayerId = layerId || sourceId;
        const layerType = layerConfig && layerConfig.type;
        const paintProps = (layerConfig && layerConfig.paint) || {};

        // Add source if not exists
        if (!map.getSource(sourceId)) {
            map.addSource(sourceId, {
                type: 'geojson',
                data: geojson
            });
            instance.sources.set(sourceId, geojson);
        }

        // Add layer
        if (!map.getLayer(actualLayerId)) {
            const layerDef = {
                id: actualLayerId,
                type: layerType,
                source: sourceId,
                paint: paintProps
            };
            if (layerConfig && layerConfig.layout) {
                layerDef.layout = layerConfig.layout;
            }
            if (layerConfig && layerConfig.filter) {
                layerDef.filter = layerConfig.filter;
            }
            map.addLayer(layerDef);

            instance.layers.set(actualLayerId, layerType);
            // Cache full spec so style-reload can rehydrate without API calls.
            if (!instance.layerDefs) instance.layerDefs = new Map();
            instance.layerDefs.set(actualLayerId, { sourceId: sourceId, geojson: geojson, layerDef: layerDef });
        }
    }

    /**
     * Shared centered-modal overlay (fixed backdrop + popup-compatible interface).
     * Used by facility/zone controls and the site-list modal.
     * uid is used only to de-duplicate: a second call with the same uid replaces the first.
     */
    function _showFacilityCenterOverlay(html, uid) {
        var OVERLAY_ID = 'aot-facility-ctrl-overlay-' + uid;
        var existing = document.getElementById(OVERLAY_ID);
        if (existing) existing.remove();

        var overlay = document.createElement('div');
        overlay.id = OVERLAY_ID;
        overlay.style.cssText = [
            'position:fixed', 'inset:0', 'z-index:var(--aot-z-modal)',
            'display:flex', 'align-items:center', 'justify-content:center',
            'background:rgba(0,0,0,0.35)'
        ].join(';');

        var popupWrap = document.createElement('div');
        popupWrap.style.cssText = 'position:relative;';

        var box = document.createElement('div');
        box.className = 'maplibregl-popup-content aot-center-modal';
        box.innerHTML = html;

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
        var _scrollbarW = window.innerWidth - document.documentElement.clientWidth;
        document.body.style.overflow = 'hidden';
        if (_scrollbarW > 0) document.body.style.paddingRight = _scrollbarW + 'px';

        // Native Fullscreen API puts the fullscreen element in the browser's
        // top-layer; siblings appended to <body> render behind it regardless
        // of z-index. Mount inside the fullscreen element when one is active.
        var _fsHost = document.fullscreenElement || document.webkitFullscreenElement ||
            document.mozFullScreenElement || document.msFullscreenElement || document.body;
        _fsHost.appendChild(overlay);

        var _closeListeners = [];
        function _close() {
            if (!document.getElementById(OVERLAY_ID)) return;
            overlay.remove();
            document.body.style.overflow = _prevOverflow;
            if (_scrollbarW > 0) document.body.style.paddingRight = '';
            _closeListeners.forEach(function (fn) { try { fn(); } catch (e) {} });
        }

        overlay.addEventListener('wheel', function (e) {
            if (e.target === overlay) e.preventDefault();
        }, { passive: false });
        overlay.addEventListener('touchmove', function (e) {
            if (e.target === overlay) e.preventDefault();
        }, { passive: false });

        overlay.addEventListener('click', function (e) { if (e.target === overlay) _close(); });
        closeBtn.addEventListener('click', _close);

        return {
            getElement: function () { return popupWrap; },
            remove:     function () { _close(); },
            on: function (evt, fn) {
                if (evt === 'close') _closeListeners.push(fn);
            }
        };
    }

    // ── Unified label-visibility model (shared constants) ──────────────────────
    // Single key namespace `label_hidden_<key>` drives every label category.
    // Mirrors the copies inside addLayerPanel's toolbar IIFE (kept in sync by
    // name) — duplicated here at module scope so _seedHiddenLabelsEarly can run
    // BEFORE addLayerPanel exists (see call site, right after instance creation).
    var _LABEL_DEVICE = { input: 1, output: 1, 'function': 1 };
    var _LABEL_REGCAT = { site: 'land', zone: 'zone', facility: 'facility', equipment: 'equipment', sensor: 'sensor' };
    var LABEL_KEYS = ['input', 'output', 'function', 'facility', 'site', 'zone', 'equipment', 'sensor'];

    // Read one label key's persisted hidden state: server-saved custom_option
    // first, then localStorage, then a one-time migration from the legacy
    // combined category toggle (cat_hidden_<cat>, which hid shape + label together).
    function _readLabelHiddenState(uniqueId, vars, key) {
        var widgetId = (vars && vars.widgetId) || uniqueId;
        var innerVars = (vars && vars.vars) || {};
        var sv = innerVars['label_hidden_' + key];
        if (sv === true || sv === 'true') return true;
        if (sv === false || sv === 'false') return false;
        try {
            var lv = localStorage.getItem('aot_map_toggle_' + widgetId + '_label_hidden_' + key);
            if (lv === 'true') return true;
            if (lv === 'false') return false;
        } catch (e) {}
        var legacyCat = _LABEL_REGCAT[key];
        if (legacyCat) {
            var lg = innerVars['cat_hidden_' + legacyCat];
            if (lg === true || lg === 'true') return true;
        }
        return false;
    }

    // Seed inst._hiddenLabels / inst._hiddenTypes BEFORE any label/marker is
    // created (loadGeoJSONLayers → loadGeoDesignLabels/addDeviceMarkers/
    // _attachActuatorLabels all run before addLayerPanel builds the toolbar and
    // would otherwise seed this state itself, well after those renderers already
    // drew everything visible). Without this, a label whose creation-time hide
    // check reads inst._hiddenLabels before it exists renders visible first and
    // only hides once addLayerPanel's toolbar runs — a visible flash on load, most
    // noticeable for facility bay chips (single-pass creation, no async re-render
    // to correct it) but latent for every label type.
    function _seedHiddenLabelsEarly(uniqueId, vars) {
        var inst = window.AoTWidgetInstances[uniqueId];
        if (!inst) return;
        if (!inst._hiddenLabels) inst._hiddenLabels = {};
        if (!inst._hiddenTypes) inst._hiddenTypes = {};
        LABEL_KEYS.forEach(function(key) {
            var hidden = _readLabelHiddenState(uniqueId, vars, key);
            inst._hiddenLabels[key] = hidden;
            if (_LABEL_DEVICE[key]) inst._hiddenTypes[key] = hidden;
        });
    }

    /**
     * Build a tool button (matches /geo/design styling).
     */
    function _toolBtn(id, iconCls, title, classes) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.id = id;
        btn.className = 'btn btn-white' + (classes ? ' ' + classes : '');
        if (window.AoTSetTitle) window.AoTSetTitle(btn, title); else btn.title = title || '';
        const i = document.createElement('i');
        i.className = iconCls;
        btn.appendChild(i);
        return btn;
    }

    function _setMapInteraction(map, enabled) {
        const handlers = ['dragPan', 'scrollZoom', 'boxZoom', 'doubleClickZoom', 'touchZoomRotate', 'keyboard'];
        handlers.forEach(function(h) {
            if (map[h]) {
                try { enabled ? map[h].enable() : map[h].disable(); } catch (e) {}
            }
        });
    }

    /**
     * Add control buttons.
     * Left rail (custom HTML, simple direct map calls): zoom, fullscreen,
     * search, locate, reset, lock, hide.
     * Site-list / Layers / Note / Measure: delegated to the existing
     * AoTMapCustomControls factories (same code that powers /geo/design).
     */
    function addControlButtons(uniqueId, map, vars) {
        const LOG = '[AoT Map]';
        const mapContainer = map.getContainer();
        const widgetWrap = document.getElementById('aot-map-' + uniqueId) || mapContainer;
        widgetWrap.style.position = widgetWrap.style.position || 'relative';

        // Warn once if map.css didn't load (the toolbar would render but be invisible).
        const probe = document.createElement('div');
        probe.className = 'map-tools-right';
        probe.style.visibility = 'hidden';
        document.body.appendChild(probe);
        const probeZ = window.getComputedStyle(probe).zIndex;
        document.body.removeChild(probe);
        if (probeZ === 'auto' || probeZ === '') {
        }

        const isLocked = !!vars.isLocked;
        const isHidden = !!vars.hideControls;

        // ---------- LEFT TOOLBAR ----------
        const left = document.createElement('div');
        left.className = 'map-tools-left';
        left.style.cssText = 'position:absolute; top:10px; left:10px; z-index:20; pointer-events:auto;';

        // Group: Zoom in/out (+ native compass injected after creation)
        const zoomGroup = document.createElement('div');
        zoomGroup.className = 'tool-group';
        const btnZoomIn  = _toolBtn(`tool-zoom-in-${uniqueId}`,  'fas fa-plus',  'Zoom In');
        const btnZoomOut = _toolBtn(`tool-zoom-out-${uniqueId}`, 'fas fa-minus', 'Zoom Out');
        zoomGroup.appendChild(btnZoomIn);
        zoomGroup.appendChild(btnZoomOut);
        left.appendChild(zoomGroup);

        // Compass-only NavigationControl, attached then moved into zoomGroup so
        // it shares the left rail with zoom +/- (matches /geo/design layout).
        try {
            const navCtrl = new maplibregl.NavigationControl({
                showCompass: true,
                showZoom: false,
                visualizePitch: true
            });
            map.addControl(navCtrl, 'top-left');
            // The control's DOM is inserted next frame; relocate it.
            requestAnimationFrame(function() {
                const nativeGroup = mapContainer.querySelector('.maplibregl-ctrl-top-left .maplibregl-ctrl-group');
                if (nativeGroup) {
                    zoomGroup.appendChild(nativeGroup);
                }
            });
        } catch (e) {}

        // Group: Fullscreen / Search / Locate / Reset
        const navGroup = document.createElement('div');
        navGroup.className = 'tool-group mt-2';
        const btnFs     = _toolBtn(`tool-fullscreen-${uniqueId}`, 'fas fa-expand',     'Fullscreen');
        const btnSearch = _toolBtn(`tool-search-${uniqueId}`,     'fas fa-search',     'Search Address');
        const btnLocate = _toolBtn(`tool-locate-${uniqueId}`,     'fas fa-crosshairs', 'My Location');
        const btnReset  = _toolBtn(`tool-reset-${uniqueId}`,      'fas fa-undo',       'Reset View');
        navGroup.appendChild(btnFs);
        navGroup.appendChild(btnSearch);
        navGroup.appendChild(btnLocate);
        navGroup.appendChild(btnReset);
        left.appendChild(navGroup);

        // Group: Site list — lock/hide buttons are in the widget title bar
        const utilGroup = document.createElement('div');
        utilGroup.className = 'tool-group mt-2';

        const btnLock = document.getElementById(`tool-lock-${uniqueId}`);
        const btnHide = document.getElementById(`tool-hide-${uniqueId}`);

        const btnSiteList = _toolBtn(`tool-site-list-${uniqueId}`,
            'fas fa-list', 'Site List');
        utilGroup.appendChild(btnSiteList);

        left.appendChild(utilGroup);

        widgetWrap.appendChild(left);

        // Note / Measure / Layers buttons are built together in addLayerPanel()
        // into a single right-rail toolbar for correct vertical alignment.

        // ---------- WIRE HANDLERS ----------
        function _wire(btn, label, fn) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                try { fn(e); } catch (err) {
                }
            });
        }

        _wire(btnZoomIn,  'zoom-in',  function() { map.zoomIn(); });
        _wire(btnZoomOut, 'zoom-out', function() { map.zoomOut(); });

        _wire(btnFs, 'fullscreen', function() {
            const target = widgetWrap;
            const doc = document;
            const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
            const requestFullScreen = target.requestFullscreen || target.webkitRequestFullscreen ||
                                      target.mozRequestFullScreen || target.msRequestFullscreen;

            if (isIOS || !requestFullScreen) {
                // Pseudo-fullscreen (iOS / browsers without the Fullscreen API).
                // The widget lives inside a grid-stack-item whose CSS `transform`
                // creates a stacking context (and, on iOS, the containing block
                // for `position: fixed`), trapping the map below the navbar.
                // Reparent to <body> so z-index/fixed resolve against the viewport.
                const isEntering = !target.classList.contains('aot-map-pseudo-fullscreen');
                if (isEntering) {
                    if (!target._aotFsPlaceholder) {
                        const ph = doc.createComment('aot-fs-placeholder');
                        target._aotFsPlaceholder = ph;
                        if (target.parentNode) target.parentNode.insertBefore(ph, target);
                    }
                    doc.body.appendChild(target);
                    target.classList.add('aot-map-pseudo-fullscreen');
                    doc.body.classList.add('aot-map-fullscreen-active');
                } else {
                    target.classList.remove('aot-map-pseudo-fullscreen');
                    doc.body.classList.remove('aot-map-fullscreen-active');
                    const ph = target._aotFsPlaceholder;
                    if (ph && ph.parentNode) {
                        ph.parentNode.insertBefore(target, ph);
                        ph.parentNode.removeChild(ph);
                    }
                    target._aotFsPlaceholder = null;
                }
                setTimeout(function() { try { map.resize(); } catch (err) {} }, 50);
            } else if (!doc.fullscreenElement && !doc.webkitFullscreenElement) {
                requestFullScreen.call(target);
            } else {
                (doc.exitFullscreen || doc.webkitExitFullscreen).call(doc);
            }
        });

        _wire(btnSearch, 'search', function() {
            const overlay = document.getElementById('search-overlay-' + uniqueId);
            if (overlay) overlay.classList.toggle('d-none');
        });

        // Address search → fly to the selected result. <aot-map-search-fixed>
        // dispatches 'location-selected' {lat,lng,name} (bubbles+composed) on the
        // host element. The shared AoTMapSearchController assumes a Leaflet shim
        // (this.map._originalMap) and doesn't fit this native-maplibre widget, so
        // the selection previously had no listener — the map never moved. Delegate
        // on document (timing-proof; survives the search element mounting late) and
        // match this widget's component by id so multiple map widgets don't cross-fire.
        if (!map._aotSearchWired) {
            map._aotSearchWired = true;
            document.addEventListener('location-selected', function(e) {
                const t = e.target;
                if (!t || t.id !== 'search-comp-' + uniqueId) return;
                const d = e.detail || {};
                const lat = parseFloat(d.lat), lng = parseFloat(d.lng);
                if (isNaN(lat) || isNaN(lng)) return;
                map.flyTo({ center: [lng, lat], zoom: 16 });
                const ov = document.getElementById('search-overlay-' + uniqueId);
                if (ov) ov.classList.add('d-none');
            });
        }

        _wire(btnLocate, 'locate', function() {
            if (!navigator.geolocation) return;
            navigator.geolocation.getCurrentPosition(function(pos) {
                map.flyTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: 16 });
            }, function(err) {
            });
        });

        _wire(btnReset, 'reset', function() {
            const lat = parseFloat((vars.geoConfig && vars.geoConfig.settings && vars.geoConfig.settings.default_lat) || vars.default_lat) || 37.5665;
            const lng = parseFloat((vars.geoConfig && vars.geoConfig.settings && vars.geoConfig.settings.default_lng) || vars.default_lng) || 126.978;
            const z   = parseFloat((vars.geoConfig && vars.geoConfig.settings && vars.geoConfig.settings.zoom) || vars.default_zoom) || 12;
            map.flyTo({ center: [lng, lat], zoom: z, pitch: 0, bearing: 0 });
        });

        _wire(btnLock, 'lock', function() {
            const locked = btnLock.dataset.locked !== 'true';
            btnLock.dataset.locked = locked ? 'true' : 'false';
            const ic = btnLock.querySelector('i');
            if (ic) ic.className = locked ? 'fas fa-lock' : 'fas fa-unlock';
            const lockTitle = locked ? (window._ ? window._('Unlock Map') : 'Unlock Map') : (window._ ? window._('Lock Map') : 'Lock Map');
            if (window.AoTSetTitle) window.AoTSetTitle(btnLock, lockTitle); else btnLock.title = lockTitle;
            _setMapInteraction(map, !locked);
            fetch('/save_widget_custom_options', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ widget_id: (vars && vars.widgetId) || uniqueId, options: { map_locked: locked } })
            }).catch(function(e) { })
        });

        _wire(btnHide, 'hide-button', function() {
            const hidden = btnHide.dataset.hidden !== 'true';
            btnHide.dataset.hidden = hidden ? 'true' : 'false';
            const ic = btnHide.querySelector('i');
            if (ic) { ic.className = 'fas fa-grip-horizontal'; ic.style.opacity = hidden ? '0.35' : ''; }
            const hideTitle = hidden ? (window._ ? window._('Show Button') : 'Show Button') : (window._ ? window._('Hide Button') : 'Hide Button');
            if (window.AoTSetTitle) window.AoTSetTitle(btnHide, hideTitle); else btnHide.title = hideTitle;
            const disp = hidden ? 'none' : '';
            // Hide/show map canvas controls (title bar buttons stay visible)
            [zoomGroup, navGroup, btnSiteList].forEach(function(el) {
                if (el) el.style.display = disp;
            });
            const rightToolbar = widgetWrap.querySelector('#map-tools-right-' + uniqueId);
            if (rightToolbar) rightToolbar.style.display = disp;
            fetch('/save_widget_custom_options', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ widget_id: (vars && vars.widgetId) || uniqueId, options: { hide_controls: hidden } })
            }).catch(function(e) { })
        });

        // Site list modal — master/detail. Left column = site list (always visible);
        // selecting a site keeps the list in place and reveals its zones in a right
        // column, so another site can be picked immediately. A zone-less site (or a
        // zone / "Go to site") navigates and closes.
        _wire(btnSiteList, 'site-list', function() {
            const inst = window.AoTWidgetInstances[uniqueId] || {};
            const inner = (vars && vars.vars) || {};
            const sites = (inst.sites && inst.sites.length) ? inst.sites : (inner.sites_in_map || []);
            const _tr = function(s) { return window._ ? window._(s) : s; };
            const _esc = function(s) {
                return String(s == null ? '' : s).replace(/[&<>"]/g, function(c) {
                    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
                });
            };

            // Drag-reorder is an edit action — gate it on control permission,
            // like the zone device list. NOTE: this handler lives in
            // addControlButtons(), a different function scope than the main
            // init's _boolOpt/_csrfHeader helpers, so read the option locally
            // (vars.vars === the widget custom_options, same as wOpts).
            const _opts = (vars && vars.vars) || {};
            const canOrder = (_opts.can_control === true || _opts.can_control === 'true' || _opts.can_control === 1);
            const _csrf = function() {
                const m = document.querySelector('meta[name="csrf-token"]');
                return (m && m.getAttribute('content')) || '';
            };
            // Stable ordering keys (match refreshSiteList._key). Shared by
            // sites and zones — both use db_id with a name fallback.
            const _keyOf = function(o) {
                return String(o && o._key != null ? o._key
                    : (o && o.db_id != null ? o.db_id : ('n:' + ((o && o.name) || ''))));
            };
            // Drag grip — identical markup to the reference lists
            // (aot-map-popup.js / facility panel): fa-grip-lines inside the
            // shared .aot-act-drag-handle span, NOT a unicode hamburger.
            const _grip = function() {
                return '<span class="aot-act-drag-handle aot-sl-grip" title="' +
                    _esc(_tr('Reorder')) + '"><i class="fa fa-grip-lines"></i></span>';
            };

            function _navigateTo(item) {
                if (item.geometry && window.turf) {
                    try {
                        const bbox = window.turf.bbox(item.geometry);
                        map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 60, maxZoom: 18 });
                        return;
                    } catch (e) {}
                }
                if (item.lat != null && item.lng != null) {
                    map.flyTo({ center: [parseFloat(item.lng), parseFloat(item.lat)], zoom: item.zoom || 17 });
                }
            }

            // Reuse the shared modal shell (.aot-center-modal): same card surface,
            // 16px radius, shadow, and close button as the zone/bay modals. Header
            // uses .aot-sensor-popup-header (its border-bottom divider comes from
            // `.aot-center-modal > .aot-sensor-popup-header`). Rows use a scoped,
            // theme-token style (NOT .aot-act-row, whose --bg-off is a light
            // device-state surface that looks wrong as a list background).
            // Single-column accordion: clicking a site expands its zones inline
            // below it (dropdown). One site open at a time. Single column keeps
            // full row width on mobile (no cramped side-by-side columns).
            // Visual language adopted from the app's modern option modal
            // (aot-modal-modern.css): bold 700 labels, a strong 2px title underline,
            // and clean 1px row separators — replicated with theme tokens so it
            // matches in both light/dark without depending on Bootstrap-modal scope.
            const sid = 'sl-' + uniqueId;
            const scopedCss =
                '<style>' +
                  '#' + sid + '{display:flex;flex-direction:column;flex:1;min-height:0;}' +
                  '#' + sid + ' .aot-sl-title{flex:0 0 auto;font-size:1.2em;font-weight:700;' +
                    'color:var(--aot-text-title);padding:0 28px 8px 2px;margin:0 0 8px;' +
                    'border-bottom:1px solid var(--aot-border-light);overflow:hidden;' +
                    'text-overflow:ellipsis;white-space:nowrap;}' +
                  '#' + sid + ' .aot-sl-list{flex:1;min-height:0;overflow-y:auto;scrollbar-width:none;padding:1px;}' +
                  '#' + sid + ' .aot-sl-list::-webkit-scrollbar{width:0;height:0;}' +
                  // Rows = rounded cards, matching the zone device list (.aot-act-row):
                  // 1px border, --bg-off surface, .4rem radius, gap between cards.
                  // NO left guide bar (the previous brand-green inset read as a black line).
                  '#' + sid + ' .aot-sl-row{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
                    'padding:.55rem .6rem;margin-bottom:.35rem;border-radius:.4rem;' +
                    'border:1px solid var(--aot-border-light);background:var(--bg-off);' +
                    'cursor:pointer;color:var(--aot-text-main);font-size:1.05em;font-weight:600;' +
                    'line-height:1.3;transition:background .12s ease,border-color .12s ease;}' +
                  '#' + sid + ' .aot-sl-row:hover{background:var(--bg-active);}' +
                  // 선택(펼침) 카드: 실제 렌더되는 활성 dash-tab(.aot-nav-tab.active)과 동일하게
                  // --bd-btn-secondary(#5E6B64 뮤트 세이지) 배경 + 흰 글자 + 700.
                  '#' + sid + ' .aot-sl-row.sel{background:var(--bd-btn-secondary);color:var(--text-color-tertiary);font-weight:700;}' +
                  '#' + sid + ' .aot-sl-row.sel .aot-sl-chev,' +
                  '#' + sid + ' .aot-sl-row.sel .aot-sl-grip{color:var(--text-color-tertiary);opacity:.9;}' +
                  '#' + sid + ' .aot-sl-left{display:flex;align-items:center;gap:8px;flex:1;min-width:0;}' +
                  '#' + sid + ' .aot-sl-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}' +
                  '#' + sid + ' .aot-sl-chev{flex:0 0 auto;color:var(--aot-text-secondary);font-size:0.85em;font-weight:400;}' +
                  // Drag grip — same fa-grip-lines handle the zone device list and
                  // facility panels use (.aot-act-drag-handle). Muted, grab cursor,
                  // stronger on row hover. pointerdown is captured by makeSortable
                  // so dragging the grip never triggers row navigation.
                  '#' + sid + ' .aot-sl-grip{flex:0 0 auto;padding:0;margin:0;font-size:13px;' +
                    'opacity:.5;touch-action:none;}' +
                  '#' + sid + ' .aot-sl-grip i{font-size:13px;line-height:1;}' +
                  '#' + sid + ' .aot-sl-row:hover .aot-sl-grip{opacity:.85;}' +
                  '#' + sid + ' .aot-act-dragging{opacity:.5;}' +
                  '#' + sid + ' .aot-act-dragging .aot-sl-grip{cursor:grabbing;}' +
                  // Zone dropdown: indented child cards (smaller). No guide bar/border on the
                  // container — the indent alone conveys hierarchy, like nested control cards.
                  '#' + sid + ' .aot-sl-zones{display:none;margin:0 0 .35rem .9rem;}' +
                  '#' + sid + ' .aot-sl-zones.open{display:block;}' +
                  '#' + sid + ' .aot-sl-zrow{padding:.45rem .55rem;font-size:1em;font-weight:400;' +
                    'background:var(--aot-surface-card);}' +
                  '#' + sid + ' .aot-sl-zrow .aot-sl-grip{font-size:11px;}' +
                  '#' + sid + ' .aot-sl-zrow .aot-sl-grip i{font-size:11px;}' +
                  '#' + sid + ' .aot-sl-empty{padding:14px 6px;color:var(--aot-text-secondary);}' +
                '</style>';
            const modalHtml =
                scopedCss +
                '<div id="' + sid + '">' +
                  '<div class="aot-sl-title" id="aot-site-modal-title-' + uniqueId + '">' + _esc(_tr('Sites')) + '</div>' +
                  '<div id="aot-site-modal-list-' + uniqueId + '" class="aot-sl-list"></div>' +
                '</div>';

            const popup = _showFacilityCenterOverlay(modalHtml, uniqueId + '-sitelist');
            const wrap = popup.getElement();

            // Use the shared .aot-center-modal sizing AS-IS (identical to the zone
            // popup): clamp(340px,38vw,600px) × min(80vh,760px) on desktop, and
            // fullscreen 100vw×100dvh with border-radius:0 on mobile (≤768px).
            // No inline width/height overrides — those previously beat the mobile
            // media query, leaving a floating rounded box where the zone modal goes
            // fullscreen (the corner mismatch on mobile). The list scrolls inside.

            const titleEl  = wrap.querySelector('#aot-site-modal-title-' + uniqueId);
            const listWrap = wrap.querySelector('#aot-site-modal-list-' + uniqueId);

            // A clean themed list row: [drag] name + optional chevron, hover/selected.
            // withDrag adds the grip handle (only top-level site rows are reorderable).
            function _row(label, chevron, extraClass, onClick, withDrag) {
                const row = document.createElement('div');
                row.className = 'aot-sl-row' + (extraClass ? ' ' + extraClass : '');
                const left = document.createElement('span');
                left.className = 'aot-sl-left';
                if (withDrag) {
                    // Reuse the shared drag-handle markup (fa-grip-lines) so the
                    // handle selector AND the standard grip styling both apply.
                    left.insertAdjacentHTML('afterbegin', _grip());
                }
                const nameEl = document.createElement('span');
                nameEl.className = 'aot-sl-name';
                nameEl.textContent = label || '(unnamed)';
                left.appendChild(nameEl);
                row.appendChild(left);
                if (chevron) {
                    const chev = document.createElement('span');
                    chev.className = 'aot-sl-chev';
                    chev.textContent = chevron;
                    row.appendChild(chev);
                }
                row.addEventListener('click', onClick);
                return row;
            }

            let _openSite = null;     // currently expanded site data
            let _openRow = null;      // its header row element
            let _openZonesEl = null;  // its zones container element

            function _collapse() {
                if (_openRow) {
                    _openRow.classList.remove('sel');
                    const c = _openRow.querySelector('.aot-sl-chev');
                    if (c) c.textContent = '▾';  // ▾  (expand)
                }
                if (_openZonesEl) _openZonesEl.classList.remove('open');
                _openSite = null; _openRow = null; _openZonesEl = null;
            }

            function _expand(site, row, zonesEl) {
                _collapse();
                _openSite = site; _openRow = row; _openZonesEl = zonesEl;
                row.classList.add('sel');
                const c = row.querySelector('.aot-sl-chev');
                if (c) c.textContent = '↗';  // ↗  (now a direct go-to)
                zonesEl.classList.add('open');
            }

            // Generic ordering (shared by sites AND each site's zones): saved keys
            // first in their saved sequence, then any new/unsaved entries appended
            // in natural-sort name order — the same policy the zone device list
            // uses (AoTActuatorOrder.order). No saved order → keep source
            // (creation) order untouched, so default behaviour is unchanged.
            function _orderList(items, saved) {
                items = items || [];
                if (!saved || !saved.length) return items.slice();
                const byKey = {};
                items.forEach(function(o) { byKey[_keyOf(o)] = o; });
                const keys = items.map(_keyOf);
                let orderedKeys;
                if (window.AoTActuatorOrder) {
                    orderedKeys = window.AoTActuatorOrder.order(keys, saved, function(k) {
                        const o = byKey[k];
                        return o ? (o.name || '') : k;
                    });
                } else {
                    const seen = {};
                    orderedKeys = [];
                    saved.forEach(function(k) { if (byKey[k] && !seen[k]) { orderedKeys.push(k); seen[k] = true; } });
                    keys.forEach(function(k) { if (!seen[k]) { orderedKeys.push(k); seen[k] = true; } });
                }
                return orderedKeys.map(function(k) { return byKey[k]; }).filter(Boolean);
            }

            // Persist a list order to the map. Body shape:
            //   { order: [...] }                       → site order
            //   { site_key: '...', zone_order: [...] } → one site's zone order
            const _mapId = inst.contentMapUuid || (vars && vars.contentMapUuid) || '';
            function _saveOrder(body) {
                if (!_mapId) return;
                const _orderUrl = '/api/geo/map/' + encodeURIComponent(_mapId) + '/site_order';
                fetch(_orderUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json',
                               'X-CSRFToken': _csrf() },
                    body: JSON.stringify(body)
                }).then(function() {
                    // Drop the cached order so the next refreshSiteList re-fetches.
                    if (window.AoTGeoData) window.AoTGeoData.invalidate(_orderUrl);
                }).catch(function() {});
            }

            function _renderSites() {
                titleEl.textContent = _tr('Sites');
                listWrap.innerHTML = '';
                if (!sites.length) {
                    const empty = document.createElement('div');
                    empty.className = 'aot-sl-empty';
                    empty.textContent = _tr('No registered sites.');
                    listWrap.appendChild(empty);
                    return;
                }
                const ordered = _orderList(sites, inst.siteOrder || []);
                // Drag only makes sense with ≥2 entries and control permission.
                const siteDrag = canOrder && ordered.length > 1;
                const zoneOrderMap = inst.zoneOrder || {};

                ordered.forEach(function(s) {
                    const sKey = _keyOf(s);
                    const zones = _orderList(s.zones || [], zoneOrderMap[sKey] || []);
                    const zoneDrag = canOrder && zones.length > 1;

                    // Each site = one reorderable item wrapping its header row and
                    // zone dropdown, so the dropdown travels with its site on drag.
                    const item = document.createElement('div');
                    item.className = 'aot-sl-item';
                    item.dataset.slot = sKey;

                    // Zone dropdown container (rendered once, toggled via .open).
                    // Zones are independently reorderable within their site.
                    const zonesEl = document.createElement('div');
                    zonesEl.className = 'aot-sl-zones';
                    zones.forEach(function(z) {
                        const zrow = _row(z.name, null, 'aot-sl-zrow', function(e) {
                            e.stopPropagation();
                            _navigateTo(z);
                            popup.remove();
                        }, zoneDrag);
                        zrow.dataset.slot = _keyOf(z);
                        zonesEl.appendChild(zrow);
                    });

                    const row = _row(s.name, zones.length > 0 ? '▾' : null, null, function() {
                        if (_openSite === s) {
                            // Already expanded → this site is now a direct go-to.
                            _navigateTo(s);
                            popup.remove();
                        } else if (zones.length > 0) {
                            // Collapsed site with zones → expand its zone dropdown.
                            _expand(s, row, zonesEl);
                        } else {
                            // Zone-less site → navigate immediately.
                            _navigateTo(s);
                            popup.remove();
                        }
                    }, siteDrag);

                    item.appendChild(row);
                    item.appendChild(zonesEl);
                    listWrap.appendChild(item);

                    // Per-site zone reorder. The handle's pointerdown is captured
                    // (stopPropagation) by makeSortable, so grabbing a zone grip
                    // drags only the zone — never the parent site item.
                    if (zoneDrag && window.AoTActuatorOrder) {
                        window.AoTActuatorOrder.makeSortable(zonesEl, {
                            itemSelector: '.aot-sl-zrow',
                            handleSelector: '.aot-act-drag-handle',
                            onReorder: function(newSeq) {
                                const zo = inst.zoneOrder || (inst.zoneOrder = {});
                                zo[sKey] = newSeq.slice();
                                _saveOrder({ site_key: sKey, zone_order: newSeq });
                            }
                        });
                    }
                });

                // Site-level reorder.
                if (siteDrag && window.AoTActuatorOrder) {
                    window.AoTActuatorOrder.makeSortable(listWrap, {
                        itemSelector: '.aot-sl-item',
                        handleSelector: '.aot-act-drag-handle',
                        onReorder: function(newSeq) {
                            inst.siteOrder = newSeq.slice();
                            _saveOrder({ order: newSeq });
                        }
                    });
                }
            }

            _renderSites();
        });

        // Initial lock state
        if (isLocked) _setMapInteraction(map, false);

        // Initial hide state
        if (isHidden) {
            [zoomGroup, navGroup, btnSiteList].forEach(function(el) {
                if (el) el.style.display = 'none';
            });
            const rightToolbar = widgetWrap.querySelector('#map-tools-right-' + uniqueId);
            if (rightToolbar) rightToolbar.style.display = 'none';
        }

        // Track for cleanup
        const inst = window.AoTWidgetInstances[uniqueId];
        if (inst) inst.toolbarLeft = left;
    }

    /**
     * Compact mode — adapt the overlay UI to the widget's rendered height so a
     * small widget stays clean without internal scrolling.
     *   height < 380px : .aot-map-h-sm — legend/advice panels capped to the widget box
     *   height < 260px : .aot-map-h-xs — left tool rail goes horizontal, dock slims down
     * Classes are toggled on the .aot-map-container wrapper; styles live in map.css.
     * Also calls map.resize() so the canvas tracks gridstack item resizes
     * (MapLibre's trackResize only listens to window resize).
     */
    function setupCompactMode(uniqueId, map, vars) {
        const widgetWrap = document.getElementById('aot-map-' + uniqueId);
        if (!widgetWrap || typeof ResizeObserver === 'undefined') return;

        let raf = null;
        function _apply() {
            raf = null;
            const h = widgetWrap.clientHeight;
            if (!h) return;
            widgetWrap.classList.toggle('aot-map-h-sm', h < 380);
            widgetWrap.classList.toggle('aot-map-h-xs', h < 260);
            try { map.resize(); } catch (e) {}
        }
        const ro = new ResizeObserver(function() {
            if (raf) return;
            raf = requestAnimationFrame(_apply);
        });
        ro.observe(widgetWrap);
        _apply();

        const inst = window.AoTWidgetInstances[uniqueId];
        if (inst) inst._compactResizeObserver = ro;
    }

    /**
     * Compute a rough center for a GeoJSON geometry (average of all coords).
     * Good enough for fly-to. Used by refreshSiteList for site centers.
     */
    function _computeCenter(geometry) {
        if (!geometry || !geometry.coordinates) return null;
        const lngs = [], lats = [];
        (function walk(arr) {
            if (typeof arr[0] === 'number') { lngs.push(arr[0]); lats.push(arr[1]); }
            else if (Array.isArray(arr)) { arr.forEach(walk); }
        })(geometry.coordinates);
        if (!lngs.length) return null;
        return {
            lng: lngs.reduce(function(a, b) { return a + b; }, 0) / lngs.length,
            lat: lats.reduce(function(a, b) { return a + b; }, 0) / lats.length
        };
    }

    /**
     * Point-in-polygon (ray casting). Used to assign zones to their containing
     * site when parent_id is absent (legacy data has parent_id=NULL).
     *
     * Deliberately NOT turf.booleanPointInPolygon: turf rejects unclosed rings
     * ("First and last coordinates in a ring must be the same") and THROWS, which
     * silently dropped every match on maps whose polygons are stored open (e.g.
     * okjeong/aot-004). Ray casting wraps last→first implicitly, so it is correct
     * for both open and closed rings. pt is [lng, lat].
     */
    function _ringContainsPoint(pt, ring) {
        let inside = false;
        const x = pt[0], y = pt[1];
        for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
            const xi = ring[i][0], yi = ring[i][1];
            const xj = ring[j][0], yj = ring[j][1];
            if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) {
                inside = !inside;
            }
        }
        return inside;
    }
    function _pointInPolygonGeom(pt, geom) {
        if (!geom || !geom.coordinates) return false;
        if (geom.type === 'Polygon') {
            const rings = geom.coordinates;
            if (!rings.length || !_ringContainsPoint(pt, rings[0])) return false;
            for (let k = 1; k < rings.length; k++) {
                if (_ringContainsPoint(pt, rings[k])) return false; // inside a hole
            }
            return true;
        }
        if (geom.type === 'MultiPolygon') {
            for (let p = 0; p < geom.coordinates.length; p++) {
                const poly = geom.coordinates[p];
                if (!poly.length || !_ringContainsPoint(pt, poly[0])) continue;
                let inHole = false;
                for (let k = 1; k < poly.length; k++) {
                    if (_ringContainsPoint(pt, poly[k])) { inHole = true; break; }
                }
                if (!inHole) return true;
            }
            return false;
        }
        return false;
    }

    /**
     * Fetch /api/geo/overlays for the widget's selected map, filter site and zone
     * features, compute centers, store on instance.sites and instance.zonesBySiteDbId
     * for the site-list modal.
     */
    function refreshSiteList(uniqueId, map, vars) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;
        const mapUuid = vars && vars.contentMapUuid;
        if (!mapUuid) {
            instance.sites = (vars && vars.vars && vars.vars.sites_in_map) || [];
            instance.zonesBySiteDbId = {};
            return;
        }
        geoFetch('/api/geo/overlays?map_uuid=' + encodeURIComponent(mapUuid))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                const features = (data && data.features) || [];
                const sites = [];
                const zones = [];

                features.forEach(function(f) {
                    const p = f.properties || {};
                    const aotType = String(p.aot_type || '').toLowerCase();
                    if (aotType !== 'site' && aotType !== 'zone') return;

                    let lat = null, lng = null;
                    if (p.center_lat != null && p.center_lng != null) {
                        lat = parseFloat(p.center_lat);
                        lng = parseFloat(p.center_lng);
                    } else if (f.geometry) {
                        const c = _computeCenter(f.geometry);
                        if (c) { lat = c.lat; lng = c.lng; }
                    }
                    if (lat == null || lng == null || isNaN(lat) || isNaN(lng)) return;

                    if (aotType === 'site') {
                        sites.push({
                            name: p.label_name || p.name || ('Site ' + (p.db_id || p.id || '')),
                            lat: lat,
                            lng: lng,
                            zoom: 17,
                            geometry: f.geometry || null,
                            parent_id: p.parent_id != null ? p.parent_id : null,
                            db_id: p.db_id != null ? p.db_id : null,
                            zones: []
                        });
                    } else if (aotType === 'zone') {
                        zones.push({
                            name: p.label_name || p.name || ('Zone ' + (p.db_id || '')),
                            lat: lat,
                            lng: lng,
                            zoom: 18,
                            geometry: f.geometry || null,
                            parent_id: p.parent_id != null ? p.parent_id : null,
                            db_id: p.db_id != null ? p.db_id : null
                        });
                    }
                });

                // Assign each zone to its parent site. parent_id is the most reliable
                // link; when it is missing (legacy data has parent_id=NULL) fall back
                // to geometric containment — a zone belongs to the site whose polygon
                // contains the zone's center point.
                const sitesByDbId = {};
                sites.forEach(function(s) { if (s.db_id != null) sitesByDbId[s.db_id] = s; });

                zones.forEach(function(z) {
                    let target = null;
                    if (z.parent_id != null && sitesByDbId[z.parent_id]) {
                        target = sitesByDbId[z.parent_id];
                    } else if (z.lat != null && z.lng != null) {
                        const pt = [parseFloat(z.lng), parseFloat(z.lat)];
                        for (let i = 0; i < sites.length; i++) {
                            const sg = sites[i].geometry;
                            if (sg && _pointInPolygonGeom(pt, sg)) {
                                target = sites[i];
                                break;
                            }
                        }
                    }
                    if (target) target.zones.push(z);
                });

                // Stable keys for user-defined ordering (drag-reorder). db_id is
                // the reliable identifier; legacy rows without it fall back to a
                // name-based key so they still order/persist.
                sites.forEach(function(s) {
                    s._key = String(s.db_id != null ? s.db_id : ('n:' + (s.name || '')));
                    (s.zones || []).forEach(function(z) {
                        z._key = String(z.db_id != null ? z.db_id : ('n:' + (z.name || '')));
                    });
                });

                instance.sites = sites;
            })
            .catch(function(e) { });

        // Saved list order for this map (parallel, non-blocking). Mirrors the
        // zone device-list order: site_order is a flat list of site keys;
        // zone_order maps each site key → its zones' display order.
        // geoFetch() dedups across map widgets via the shared AoTGeoData cache;
        // _saveOrder() invalidates this URL so a reorder is reflected immediately.
        geoFetch('/api/geo/map/' + encodeURIComponent(mapUuid) + '/site_order')
            .then(function(r) { return r.json(); })
            .then(function(d) {
                instance.siteOrder = (d && d.ok && Array.isArray(d.order)) ? d.order : [];
                instance.zoneOrder = (d && d.ok && d.zone_order && typeof d.zone_order === 'object') ? d.zone_order : {};
            })
            .catch(function() {
                instance.siteOrder = instance.siteOrder || [];
                instance.zoneOrder = instance.zoneOrder || {};
            });
    }

    /**
     * Unified right toolbar: Layers button (+ panel) / Measure / Note.
     * All three buttons live in a single flex-column container at top-right
     * so they are always vertically aligned with consistent 5px gaps.
     *
     * Layer selection is persisted per-widget via /save_widget_custom_options.
     * On overlay change, the legend is also refreshed via instance.refreshLegend.
     */

    /**
     * Resolve active overlay names from innerVars.active_layers.
     * Python returns a list of layer objects with a `visible` flag; older paths
     * may pass a comma-separated string or a plain array of name strings.
     */
    function _resolveActiveOverlayNames(rawActiveLayers) {
        if (!rawActiveLayers) return [];
        if (Array.isArray(rawActiveLayers)) {
            if (rawActiveLayers.length && rawActiveLayers[0] !== null && typeof rawActiveLayers[0] === 'object') {
                // Layer objects from Python — extract names of visible overlays
                return rawActiveLayers
                    .filter(function(l) { return l && l.visible && !(l.is_base || l.role === 'base'); })
                    .map(function(l) { return l.name || l.id || ''; })
                    .filter(Boolean);
            }
            // Array of plain strings
            return rawActiveLayers.map(function(s) { return String(s).trim(); }).filter(Boolean);
        }
        // Comma-separated string fallback
        return String(rawActiveLayers).split(',').map(function(s) { return s.trim(); }).filter(Boolean);
    }

    function addLayerPanel(uniqueId, map, vars) {
        const mapContainer = map.getContainer();
        mapContainer.style.position = mapContainer.style.position || 'relative';

        const geoLayers = (vars && vars.geoConfig && vars.geoConfig.layers)
            || (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.layers)
            || [];

        const innerVars = (vars && vars.vars) || {};
        let activeBase = innerVars.selected_base_layer || null;
        let activeOverlays = _resolveActiveOverlayNames(innerVars.active_layers);

        // ── Feature-type (category) visibility — P2 ──────────────────────────────
        // Coarse per-category show/hide for the geo features the widget draws.
        // Shapes are MapLibre layers (setLayoutProperty visibility); labels/markers
        // are DOM elements toggled via .aot-type-hidden; sensor values go through the
        // AoTMapSensorLabels module. Each row's checked state == visible.
        const _CAT_DEFS = [
            { cat: 'land',      label: (window._ ? window._('Site') : 'Site'),          layers: ['sites-fill', 'sites-line'],                          labelType: 'site' },
            { cat: 'zone',      label: (window._ ? window._('Zone') : 'Zone'),          layers: ['zones-fill', 'zones-line'],                          labelType: 'zone' },
            // NOTE: 'facilities-3d' (the fill-extrusion box) is intentionally NOT listed
            // here. It is created hidden and replaced by the Three.js facility model
            // (AoTFacilityMap3D.attach → hideLayers). If it were managed by the shape-LOD
            // toggle, _applyShapeLOD would re-show it on load/zoom, drawing the extrusion
            // box on top of the 3D model (box + model duplicate). Only the flat footprint
            // (fill/line) follows the facility category toggle.
            { cat: 'facility',  label: (window._ ? window._('Facility') : 'Facility'),  layers: ['facilities-fill', 'facilities-line'], labelType: 'facility' },
            { cat: 'equipment', label: (window._ ? window._('Equipment') : 'Equipment'),layers: ['equipment-line', 'equipment-fill'],                  labelType: 'equipment' },
            { cat: 'device',    label: (window._ ? window._('Device') : 'Device'),      layers: ['aot-devices-line', 'aot-devices-fill'],              labelType: 'aot_device', markers: true },
            { cat: 'sensor',    label: (window._ ? window._('Sensor Values') : 'Sensor Values'), sensor: true },
            { cat: 'drawn',     label: (window._ ? window._('Other Shapes') : 'Other Shapes'),   layers: ['drawn-shapes-fill', 'drawn-shapes-line'] }
        ];
        const _CAT_BY_KEY = {};
        _CAT_DEFS.forEach(function (d) { _CAT_BY_KEY[d.cat] = d; });

        const _catWidgetId = (vars && vars.widgetId) || uniqueId;
        const _catLsPrefix = 'aot_map_cat_' + _catWidgetId + '_';
        const _catHidden = {}; // cat -> true if hidden

        function _catReadSaved(cat) {
            // Server-side value (innerVars) wins; fall back to localStorage.
            var key = 'cat_hidden_' + cat;
            var sv = innerVars[key];
            if (sv === true || sv === 'true') return true;
            if (sv === false || sv === 'false') return false;
            try {
                var lv = localStorage.getItem(_catLsPrefix + cat);
                return lv === 'true';
            } catch (e) { return false; }
        }
        function _catSave(cat, hidden) {
            var patch = {}; patch['cat_hidden_' + cat] = hidden;
            fetch('/save_widget_custom_options', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ widget_id: _catWidgetId, options: patch })
            }).catch(function (e) { });
            try { localStorage.setItem(_catLsPrefix + cat, hidden ? 'true' : 'false'); } catch (e) { }
        }

        // Shape LOD threshold — reuse the editor's equipment_cull_zoom (default 15)
        // so the widget and /geo/design cull at the same zoom (visibility + render
        // load). Below the threshold (zoomed out) only the site (land) shapes show;
        // every other shape category is culled.
        const _shapeLodThreshold = (function () {
            var cfg = (vars && vars.geoConfig) || (window.AOT_GEO_CONFIG) || {};
            var t = parseFloat(cfg.equipment_cull_zoom);
            return isNaN(t) ? 15 : t;
        })();

        // Single source of truth for shape-layer visibility: combines the per-category
        // toggle (registry) with the zoom LOD. Non-site categories are hidden when
        // zoomed out past the threshold; site shapes always follow only their toggle.
        function _applyShapeLOD() {
            var z = (map && typeof map.getZoom === 'function') ? map.getZoom() : 99;
            _CAT_DEFS.forEach(function (def) {
                if (!def.layers || !def.layers.length) return; // shape categories only
                var catVisible = window.AoTMapLabelLayers
                    ? window.AoTMapLabelLayers.isShapeVisible(uniqueId, def.cat)
                    : !_catHidden[def.cat];
                // site (land) and device shapes are guaranteed across zoom (devices
                // must stay visible up to max zoom); the rest cull when zoomed out.
                var zoomOk = (def.cat === 'land' || def.cat === 'device') || (z >= _shapeLodThreshold);
                var vis = catVisible && zoomOk;
                def.layers.forEach(function (lid) {
                    if (map.getLayer(lid)) {
                        try { map.setLayoutProperty(lid, 'visibility', vis ? 'visible' : 'none'); } catch (e) { }
                    }
                });
            });
        }

        // Shape axis ONLY: toggle a category's fill/line MapLibre layers. Labels are an
        // independent axis (see the label toolbar / Labels panel section), so hiding a
        // shape no longer hides its label and vice versa.
        function _applyShapeVisible(cat, visible) {
            var def = _CAT_BY_KEY[cat];
            if (!def) return;
            _catHidden[cat] = !visible;
            if (window.AoTMapLabelLayers) {
                try { AoTMapLabelLayers.setShapeVisible(uniqueId, cat, visible); } catch (e) { }
            }
            // MapLibre shape layers — routed through the zoom-aware LOD so toggling a
            // category never overrides the zoom culling (and vice versa).
            if (def.layers && def.layers.length) _applyShapeLOD();
        }
        // Expose the shape-category toggle so the settings modal can live-apply the
        // show_*_shape options (the in-map shape toggles already call this).
        try {
            var _shInst = window.AoTWidgetInstances[uniqueId];
            if (_shInst) { _shInst._applyShapeVisible = _applyShapeVisible; }
        } catch (e) {}

        // Seed persisted SHAPE-hidden state into the registry. _applyShapeLOD (called
        // right after) reads shapeVisible to cull hidden shapes — no per-label timers
        // here anymore; label state is seeded in the label toolbar section instead.
        _CAT_DEFS.forEach(function (d) {
            var hidden = _catReadSaved(d.cat);
            _catHidden[d.cat] = hidden;
            if (window.AoTMapLabelLayers) {
                try { AoTMapLabelLayers.setShapeVisible(uniqueId, d.cat, !hidden); } catch (e) { }
            }
        });

        // Shape LOD: shapes are already loaded by the time the panel is built
        // (loadGeoJSONLayers is awaited before addLayerPanel), so apply ONCE now and
        // only re-apply on zoom change. A single 'idle' catch handles layers whose
        // add was deferred to style load. No staggered timeouts — those caused the
        // load flicker (shapes shown, then repeatedly re-culled).
        _applyShapeLOD();
        if (map && typeof map.on === 'function') {
            map.on('zoomend', _applyShapeLOD);
            map.once('idle', _applyShapeLOD);
        }

        // ---- Unified right toolbar ----
        const toolbar = document.createElement('div');
        toolbar.id = 'map-tools-right-' + uniqueId;
        toolbar.style.cssText = 'position:absolute; top:10px; right:10px; z-index:20; display:flex; flex-direction:column; align-items:center; gap:5px;';
        mapContainer.appendChild(toolbar);
        const _rightHidden = !!(vars && vars.hideControls);
        if (_rightHidden) toolbar.style.display = 'none';

        // ---- Tool group: Layers / Measure / Memo share one box (smaller footprint) ----
        const rightGroup = document.createElement('div');
        rightGroup.className = 'tool-group';
        toolbar.appendChild(rightGroup);

        // ---- Layer button + panel (sub-container so panel anchors correctly) ----
        const layerWrap = document.createElement('div');
        layerWrap.style.cssText = 'position:relative;';
        rightGroup.appendChild(layerWrap);

        const btn = document.createElement('a');
        btn.href = '#';
        btn.className = 'btn btn-white';
        const layersTitle = (typeof window._ === 'function') ? window._('Layers') : 'Layers';
        if (window.AoTSetTitle) window.AoTSetTitle(btn, layersTitle); else btn.title = layersTitle;
        btn.id = 'tool-layers-' + uniqueId;
        btn.setAttribute('role', 'button');
        const icon = document.createElement('i');
        icon.className = 'fas fa-layer-group';
        btn.appendChild(icon);
        layerWrap.appendChild(btn);

        // Panel lives on the toolbar (not inside the tool-group): the group has
        // overflow:hidden and would clip the absolutely positioned dropdown.
        const panel = document.createElement('div');
        panel.style.cssText = 'display:none; position:absolute; top:34px; right:0; background:white; padding:10px; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.25); min-width:220px; overflow-y:auto; z-index:30; font-size:var(--aot-fs-label);';
        toolbar.appendChild(panel);

        function _adjustLayerPanelHeight() {
            const containerRect = mapContainer.getBoundingClientRect();
            const panelRect = panel.getBoundingClientRect();
            const available = containerRect.bottom - panelRect.top - 10;
            panel.style.maxHeight = Math.max(80, available) + 'px';
        }
        if (map && typeof map.on === 'function') {
            map.on('resize', function() {
                if (panel.style.display === 'block') _adjustLayerPanelHeight();
            });
        }
        if (typeof ResizeObserver !== 'undefined') {
            new ResizeObserver(function() {
                if (panel.style.display === 'block') _adjustLayerPanelHeight();
            }).observe(mapContainer);
        }

        // ---- Measure + Memo buttons via factories, moved into toolbar ----
        if (window.AoTMapCustomControls) {
            ['createMeasureControl', 'createMemoControl'].forEach(function(fn) {
                try {
                    const result = window.AoTMapCustomControls[fn](map, {});
                    if (result && result.container) {
                        // Factory appended to mapContainer — detach and re-parent
                        if (result.container.parentNode) {
                            result.container.parentNode.removeChild(result.container);
                        }
                        // Clear absolute positioning so flex column controls placement
                        result.container.style.cssText = '';
                        result.container.classList.remove('aot-mr-10');
                        result.container.classList.remove('mt-2');
                        // Inside the shared tool-group the per-button shadow goes away
                        result.container.querySelectorAll('.btn-circle').forEach(function(b) {
                            b.classList.remove('btn-circle');
                        });
                        rightGroup.appendChild(result.container);
                    }
                } catch (e) { }
            });
        }

        // ---- Custom Options group: device-type label toggles + measurement hide ----
        (function() {
            var widgetId = (vars && vars.widgetId) || uniqueId;
            var innerVars = (vars && vars.vars) || {};
            var _lsPrefix = 'aot_map_toggle_' + widgetId + '_';

            function _lsGet(key) {
                try { var v = localStorage.getItem(_lsPrefix + key); return v === 'true' ? true : v === 'false' ? false : null; } catch(e) { return null; }
            }
            function _lsSet(key, val) {
                try { localStorage.setItem(_lsPrefix + key, val ? 'true' : 'false'); } catch(e) {}
            }

            function _readSaved(saveKey) {
                // Server-side state takes priority; fall back to localStorage if server returns nothing
                var sv = innerVars[saveKey];
                if (sv === true || sv === 'true') return true;
                if (sv === false || sv === 'false') return false;
                // sv is undefined/null → server didn't provide it; check localStorage
                var lv = _lsGet(saveKey);
                return lv === true;
            }

            function _saveToggleState(patch) {
                fetch('/save_widget_custom_options', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ widget_id: widgetId, options: patch })
                }).catch(function(e) { })
                // Mirror to localStorage as backup
                Object.keys(patch).forEach(function(k) { _lsSet(k, patch[k]); });
            }

            function _applyTypeHide(type, hidden) {
                var inst = window.AoTWidgetInstances[uniqueId];
                if (!inst) return;

                // 1. Device markers (pill / dot) stored in instance.markers
                if (inst.markers) {
                    inst.markers.forEach(function(marker) {
                        if (!marker || typeof marker.getElement !== 'function') return;
                        var el = marker.getElement();
                        if (!el || el.dataset.deviceType !== type) return;
                        el.classList.toggle('aot-type-hidden', hidden);
                    });
                }

                // 2. Geo-design device labels stored in instance.geoDeviceLabelMarkers
                //    These have dataset.parentId (device base UUID) — look up via _deviceTypeMap
                var typeMap = inst._deviceTypeMap || {};
                (inst.geoDeviceLabelMarkers || []).forEach(function(marker) {
                    if (!marker || typeof marker.getElement !== 'function') return;
                    var el = marker.getElement();
                    if (!el) return;
                    var parentId = el.dataset.parentId || '';
                    if (typeMap[parentId] !== type) return;
                    el.classList.toggle('aot-type-hidden', hidden);
                });

                // NOTE: sensor value labels are NO LONGER coupled to the input toggle.
                // They are an independent label category ('sensor', key label_hidden_sensor)
                // driven by _applyLabel below — this removes the old double-control where
                // both the Input button and the Sensor row moved sensor visibility.

                // Persist on instance so addDeviceMarkers applies on re-render
                if (!inst._hiddenTypes) inst._hiddenTypes = {};
                inst._hiddenTypes[type] = hidden;
            }

            // ── Unified label-visibility model ──────────────────────────────────
            // A single key namespace `label_hidden_<key>` drives every label category.
            // Device types (input/output/function) route through _applyTypeHide; geo
            // name labels (site/zone/facility/equipment) toggle .aot-type-hidden on
            // instance.labelMarkers matched by dataset.parentType; sensor values go
            // through the AoTMapSensorLabels module. The toolbar quick-buttons and the
            // Layers→Labels checkboxes share this state (two-way synced via _syncLabelControls).
            var _LABEL_DEVICE = { input: 1, output: 1, 'function': 1 };
            var _LABEL_PTYPE  = { site: 'site', zone: 'zone', facility: 'facility', equipment: 'equipment' };
            var _LABEL_REGCAT = { site: 'land', zone: 'zone', facility: 'facility', equipment: 'equipment', sensor: 'sensor' };
            // Every label key the widget knows (quick-buttons + Labels-panel rows).
            var LABEL_KEYS = ['input', 'output', 'function', 'facility', 'site', 'zone', 'equipment', 'sensor'];

            function _applyLabel(key, hidden) {
                var inst = window.AoTWidgetInstances[uniqueId];
                if (!inst) return;
                if (_LABEL_DEVICE[key]) {
                    _applyTypeHide(key, hidden);
                } else if (key === 'sensor') {
                    if (window.AoTMapSensorLabels) {
                        try { AoTMapSensorLabels.setVisible(uniqueId, !hidden); } catch (e) {}
                    }
                } else if (_LABEL_PTYPE[key]) {
                    var pType = _LABEL_PTYPE[key];
                    (inst.labelMarkers || []).forEach(function(m) {
                        if (!m || typeof m.getElement !== 'function') return;
                        var el = m.getElement();
                        if (el && el.dataset.parentType === pType) el.classList.toggle('aot-type-hidden', hidden);
                    });
                    // The on-map "facility label" a user actually sees is the per-bay
                    // name chip (.aot-bay-chip) built by _attachActuatorLabels. That
                    // function is local to initAoTMapVectorWidget and stores its state
                    // in the (also-local) _actLabelState — out of reach from here, since
                    // addLayerPanel is a sibling top-level function. _attachActuatorLabels
                    // mirrors its bayMarkers array onto window.AoTWidgetInstances[uid]
                    // for exactly this reason; go through the instance, not _actLabelState.
                    if (key === 'facility' && inst.bayMarkers) {
                        inst.bayMarkers.forEach(function(bm) {
                            if (bm && bm.el) bm.el.classList.toggle('aot-type-hidden', hidden);
                        });
                    }
                }
                if (window.AoTMapLabelLayers && _LABEL_REGCAT[key]) {
                    try { AoTMapLabelLayers.setLabelVisible(uniqueId, _LABEL_REGCAT[key], !hidden); } catch (e) {}
                }
                if (!inst._hiddenLabels) inst._hiddenLabels = {};
                inst._hiddenLabels[key] = hidden;
            }

            function _readLabelHidden(key) {
                var sv = innerVars['label_hidden_' + key];
                if (sv === true || sv === 'true') return true;
                if (sv === false || sv === 'false') return false;
                var lv = _lsGet('label_hidden_' + key);
                if (lv === true) return true;
                if (lv === false) return false;
                // Unset → migrate from the legacy combined category toggle
                // (cat_hidden_<cat> used to hide a category's shape AND label together).
                // Preserves the prior on-screen appearance for existing widgets.
                var legacyCat = _LABEL_REGCAT[key];
                if (legacyCat) {
                    var lg = innerVars['cat_hidden_' + legacyCat];
                    if (lg === true || lg === 'true') return true;
                }
                return false;
            }

            // Two-way sync: reflect the current hidden state onto BOTH the toolbar
            // quick-button and the Layers→Labels checkbox for this key.
            function _syncLabelControls(key) {
                var inst = window.AoTWidgetInstances[uniqueId];
                var hidden = !!(inst && inst._hiddenLabels && inst._hiddenLabels[key]);
                var qb = document.getElementById('tool-label-' + key + '-' + uniqueId);
                if (qb) qb.style.opacity = hidden ? '0.4' : '1';
                var cb = document.getElementById('label-cat-' + key + '-' + uniqueId);
                if (cb) cb.checked = !hidden;
            }

            // Single entry point for a label toggle: apply + persist + sync both UIs.
            function _setLabel(key, hidden) {
                _applyLabel(key, hidden);
                var patch = {}; patch['label_hidden_' + key] = hidden;
                _saveToggleState(patch);
                _syncLabelControls(key);
            }

            // Expose so the Layers→Labels panel (built later, in the outer scope) can
            // drive and read the exact same state.
            (function() {
                var inst = window.AoTWidgetInstances[uniqueId];
                if (!inst) return;
                inst._setLabel = _setLabel;
                inst._readLabelHidden = _readLabelHidden;
                inst._labelKeys = LABEL_KEYS;
            })();

            // Seed persisted hidden state for EVERY label key (whether or not it has a
            // quick-button), re-applying on a few delays since labels/markers/sensor
            // render asynchronously after the toolbar is built.
            (function() {
                var inst = window.AoTWidgetInstances[uniqueId];
                if (!inst) return;
                if (!inst._hiddenLabels) inst._hiddenLabels = {};
                if (!inst._hiddenTypes) inst._hiddenTypes = {};
                LABEL_KEYS.forEach(function(key) {
                    var hidden = _readLabelHidden(key);
                    inst._hiddenLabels[key] = hidden;
                    if (_LABEL_DEVICE[key]) inst._hiddenTypes[key] = hidden;
                    if (hidden) {
                        [500, 1500, 3000].forEach(function(ms) {
                            setTimeout(function() { _applyLabel(key, true); }, ms);
                        });
                    }
                });
            })();

            var customGroup = document.createElement('div');
            customGroup.className = 'tool-group mt-2';

            // Toolbar quick-buttons: the label categories users flip most often.
            // Facility is now a first-class button (previously reachable only via the
            // shape-coupled category checkbox).
            var quickLabels = [
                { key: 'input',    icon: 'fas fa-thermometer-half', title: (window._ ? window._('Toggle Input labels') : 'Toggle Input labels') },
                { key: 'output',   icon: 'fas fa-sliders-h',        title: (window._ ? window._('Toggle Output labels') : 'Toggle Output labels') },
                { key: 'function', icon: 'fas fa-code-branch',      title: (window._ ? window._('Toggle Function labels') : 'Toggle Function labels') },
                { key: 'facility', icon: 'fas fa-industry',         title: (window._ ? window._('Toggle Facility labels') : 'Toggle Facility labels') }
            ];

            quickLabels.forEach(function(dt) {
                var savedHidden = _readLabelHidden(dt.key);
                var btn = _toolBtn('tool-label-' + dt.key + '-' + uniqueId, dt.icon, dt.title);
                customGroup.appendChild(btn);
                if (savedHidden) btn.style.opacity = '0.4';

                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    var inst2 = window.AoTWidgetInstances[uniqueId];
                    if (!inst2._hiddenLabels) inst2._hiddenLabels = {};
                    var hidden = !inst2._hiddenLabels[dt.key];
                    _setLabel(dt.key, hidden);
                });
            });

            // AI advice hide button (replaced the old measurements-hide toggle) —
            // toggles the top advice chip stack (#aot-map-advice-chips-<id>,
            // rendered by the widget body's inline script).
            var savedAdviceHidden = _readSaved('ai_advice_chips_hidden');
            var adviceBtn = _toolBtn('tool-ai-advice-hide-' + uniqueId, 'aot-ai-tool-icon', (window._ ? window._('Hide AI advice') : 'Hide AI advice'));
            var adviceIcon = adviceBtn.querySelector('i');
            if (adviceIcon) adviceIcon.textContent = 'AI';
            customGroup.appendChild(adviceBtn);
            if (savedAdviceHidden) adviceBtn.style.opacity = '0.4';

            function _adviceChipsEl() {
                return document.getElementById('aot-map-advice-chips-' + widgetId);
            }
            // Apply saved hidden state (the chips element exists in the template DOM;
            // the inline renderer also reads the same flag to avoid a show flash).
            if (savedAdviceHidden) {
                var advEl0 = _adviceChipsEl();
                if (advEl0) advEl0.style.display = 'none';
            }

            adviceBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                var inst = window.AoTWidgetInstances[uniqueId];
                if (!inst) return;
                inst._adviceHidden = !inst._adviceHidden;
                adviceBtn.style.opacity = inst._adviceHidden ? '0.4' : '1';
                var advEl = _adviceChipsEl();
                if (advEl) advEl.style.display = inst._adviceHidden ? 'none' : '';
                _saveToggleState({ ai_advice_chips_hidden: inst._adviceHidden });
            });

            // Initialise _adviceHidden on instance
            var inst0 = window.AoTWidgetInstances[uniqueId];
            if (inst0) inst0._adviceHidden = savedAdviceHidden;

            toolbar.appendChild(customGroup);
        })();

        // ---- Map-side application helpers ----
        const _baseStyleIds = map._aotBaseStyleIds || ((map.getStyle() || {}).layers || []).map(function(l) { return l.id; });
        let _activeRasterBaseId = null;

        // Cache with TTL (5 min) so stale timestamps don't cause 410 Gone.
        const _tsCache = {};
        const _TS_TTL = 5 * 60 * 1000;

        // Extract timestamp from RainViewer meta — mirrors input-preview.js logic.
        function _extractRainviewerTs(meta) {
            if (!meta || !meta.radar) return null;
            const past = (meta.radar.past || []);
            const nowcast = (meta.radar.nowcast || []);
            const last = past.length ? past[past.length - 1] : (nowcast.length ? nowcast[0] : null);
            if (!last) return null;
            if (last.path) {
                const parts = String(last.path).split('/').filter(Boolean);
                return parts.length ? parts[parts.length - 1] : null;
            }
            return last.time ? String(last.time) : null;
        }

        function _buildSource(l, resolvedUrl) {
            if (map.getSource(l.id)) return;
            // Copyright/attribution for this GIS layer. Attaching it to the source
            // lets MapLibre's AttributionControl show/drop the notice automatically
            // as the layer is activated/hidden — restoring the dynamic per-active-GIS
            // copyright behaviour (previously only the base vector style showed).
            var _attr = l.attribution || (l.options && l.options.attribution) || '';
            // Aerial / drone photo overlay: a georeferenced `image` source defined
            // by 4 corner coordinates, not a tile pyramid.
            if (l.type === 'image') {
                var iopts = l.options || {};
                // Large image → XYZ tile pyramid (zoom-responsive) rather than a
                // single `image` source that would exceed the GPU texture limit.
                if (iopts.render_mode === 'tiled' && iopts.tile_url) {
                    var tspec = { type: 'raster', tiles: [iopts.tile_url], tileSize: 256 };
                    if (_attr) tspec.attribution = _attr;
                    var mnz = parseInt(iopts.minzoom, 10); if (!isNaN(mnz)) tspec.minzoom = mnz;
                    var mxz = parseInt(iopts.maxzoom, 10); if (!isNaN(mxz)) tspec.maxzoom = mxz;
                    try { map.addSource(l.id, tspec); } catch (e) { }
                    return;
                }
                var coords = iopts.coordinates;
                if (typeof coords === 'string') {
                    try { coords = JSON.parse(coords); } catch (e) { coords = null; }
                }
                // Prefer the render URL from options (downscaled preview for large
                // images) over the original; fall back to l.url.
                var imgUrl = iopts.image_url || l.url;
                if (!imgUrl || !coords || coords.length !== 4) return;
                var imgSpec = { type: 'image', url: imgUrl, coordinates: coords };
                if (_attr) imgSpec.attribution = _attr;
                try { map.addSource(l.id, imgSpec); } catch (e) { }
                return;
            }
            // Never create a source with an unresolved {ts} — it will 404.
            if (resolvedUrl && resolvedUrl.indexOf('{ts}') !== -1) {
                return;
            }
            const opts = (l.options) || {};
            const tileSize = parseInt(opts.tileSize || opts.tile_size) || 256;
            const tiles = _toTilesFromUrl(l, resolvedUrl);
            const spec = { type: 'raster', tiles: tiles, tileSize: tileSize };
            if (_attr) spec.attribution = _attr;
            const maxNative = parseInt(opts.maxNativeZoom || opts.max_native_zoom || opts.maxZoom || 0);
            if (maxNative > 0) spec.maxzoom = maxNative;
            const minNative = parseInt(opts.minZoom || opts.minNativeZoom || opts.min_zoom || 0);
            if (minNative > 0) spec.minzoom = minNative;
            try { map.addSource(l.id, spec); } catch (e) { }
        }

        function _toTilesFromUrl(l, url) {
            url = (url || l.url || '').replace(/\{r\}/g, '');
            if (l.type === 'wms') {
                return ['/api/geo/proxy/wms/' + encodeURIComponent(l.id) + '?BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256'];
            }
            if (url.indexOf('{s}') !== -1) {
                return ['a', 'b', 'c'].map(function(s) { return url.replace(/\{s\}/g, s); });
            }
            return [url];
        }

        // Async: resolves {ts} via RainViewer API, then calls onReady().
        // Mirrors input-preview.js: direct API first, proxy fallback, path extraction.
        function _ensureSource(l, onReady) {
            if (map.getSource(l.id)) { onReady && onReady(); return; }
            const url = l.url || '';
            if (url.indexOf('{ts}') !== -1) {
                // Use cached timestamp if still fresh.
                const cached = _tsCache.rainviewer;
                if (cached && (Date.now() - cached.at < _TS_TTL)) {
                    _buildSource(l, url.replace(/\{ts\}/g, cached.ts));
                    onReady && onReady();
                    return;
                }
                // Direct API first (CORS-enabled); proxy as fallback.
                const _tryFetch = function(u) {
                    return fetch(u, { credentials: 'omit' })
                        .then(function(r) { return r.ok ? r.json() : null; })
                        .catch(function() { return null; });
                };
                _tryFetch('https://api.rainviewer.com/public/weather-maps.json')
                    .then(function(meta) {
                        return meta || _tryFetch('/api/geo/proxy/rainviewer/meta');
                    })
                    .then(function(meta) {
                        const ts = _extractRainviewerTs(meta);
                        if (ts) _tsCache.rainviewer = { ts: ts, at: Date.now() };
                        _buildSource(l, ts ? url.replace(/\{ts\}/g, ts) : url);
                        onReady && onReady();
                    })
                    .catch(function() { _buildSource(l, url); onReady && onReady(); });
                return;
            }
            _buildSource(l, url);
            onReady && onReady();
        }
        function _hideAllVectorBase() {
            // Read live (not the closed-over _baseStyleIds snapshot) — a vector-base
            // switch (map.setStyle) replaces map._aotBaseStyleIds with the new style's
            // own layer ids, and a later raster-base switch must hide THAT style.
            (map._aotBaseStyleIds || _baseStyleIds).forEach(function(id) {
                try { map.setLayoutProperty(id, 'visibility', 'none'); } catch (e) {}
            });
        }
        function _showAllVectorBase() {
            (map._aotBaseStyleIds || _baseStyleIds).forEach(function(id) {
                try { map.setLayoutProperty(id, 'visibility', 'visible'); } catch (e) {}
            });
        }
        // Returns the first GeoJSON layer ID so raster tiles are inserted BEFORE it,
        // preventing raster tiles from covering GeoJSON shapes.
        function _getFirstGeoJSONLayerId() {
            const inst = window.AoTWidgetInstances[uniqueId];
            if (inst && inst.layers && inst.layers.size > 0) {
                // Return the first tracked layer that ACTUALLY exists in the current
                // style. inst.layers can hold ids that aren't in the map (deferred /
                // failed / removed adds, or entries left after setStyle rehydration).
                // Passing such a stale id as beforeId makes map.addLayer throw, which
                // silently aborted raster-base restore on refresh — the saved VWorld
                // (or other raster) base then fell back to the vector style. Mirrors
                // the existing guard in _getFirstOverlayLayerId.
                for (const layerId of inst.layers.keys()) {
                    if (map.getLayer(layerId)) return layerId;
                }
            }
            return undefined;
        }

        // Returns the first active overlay tile layer ID. Used to insert the raster
        // base BELOW overlays — prevents the base from covering overlay layers that
        // were added earlier with the same beforeId (first GeoJSON).
        function _getFirstOverlayLayerId() {
            for (var _oi = 0; _oi < geoLayers.length; _oi++) {
                var _ol = geoLayers[_oi];
                if (_ol.role === 'base' || _ol.is_base) continue;
                var _olyId = _ol.id + '_layer';
                if (map.getLayer(_olyId)) return _olyId;
            }
            return undefined;
        }

        // Re-stack GeoJSON shape layers (sites/zones/facilities/equipment/devices/drawn)
        // above all raster base/overlay layers so 2D rasters never cover shapes/labels.
        // Called after any raster add/show — covers cases where the raster was added
        // with beforeId=undefined (no shapes loaded yet at activation time) or where a
        // previously-hidden raster is re-shown without a fresh insertion point.
        // The Three.js facility overlay (aot-facility-3d-layer) is moved to the absolute
        // top AFTER all GeoJSON layers so it always renders above both raster tiles and
        // 2D GeoJSON shapes regardless of which base/overlay map is active.
        function _promoteShapesToTop() {
            const inst = window.AoTWidgetInstances[uniqueId];
            if (!inst || !inst.layers) return;
            inst.layers.forEach(function(_type, layerId) {
                if (map.getLayer(layerId)) {
                    try { map.moveLayer(layerId); } catch (e) {}
                }
            });
            // Three.js custom layer must sit above all 2D GeoJSON shapes.
            if (map.getLayer('aot-facility-3d-layer')) {
                try { map.moveLayer('aot-facility-3d-layer'); } catch (e) {}
            }
        }

        function _activateRasterBase(l) {
            const lyId = l.id + '_layer';
            _ensureSource(l, function() {
                if (!map.getSource(l.id)) return;
                // Insert base BELOW any active overlay layers so overlays remain visible.
                // Fall back to first GeoJSON layer (shapes stay on top).
                const beforeId = _getFirstOverlayLayerId() || _getFirstGeoJSONLayerId();
                if (!map.getLayer(lyId)) {
                    try {
                        map.addLayer({ id: lyId, type: 'raster', source: l.id, layout: { visibility: 'visible' } }, beforeId);
                    } catch (e) {
                    }
                } else {
                    map.setLayoutProperty(lyId, 'visibility', 'visible');
                }
                // Guarantee shapes/labels remain on top regardless of insertion order
                // or whether shapes were loaded before activation.
                _promoteShapesToTop();
            });
            _activeRasterBaseId = l.id;
            // The technical base style (MapTiler/demotiles/etc., loaded as the map's
            // initial `style:`) stays underneath, still `visibility:'visible'`, just
            // visually covered by this raster layer. MapLibre's AttributionControl only
            // drops a source's credit once its layers are actually hidden (SourceCache
            // .used flips false) — leaving them visible-but-covered keeps stacking that
            // engine's attribution (e.g. "MapTiler © OpenStreetMap") on every map
            // regardless of which base is actually shown. Hide them so only the
            // active engine's own attribution remains.
            _hideAllVectorBase();
        }
        function _deactivateRasterBase() {
            _showAllVectorBase();
            if (!_activeRasterBaseId) return;
            const lyId = _activeRasterBaseId + '_layer';
            try { map.setLayoutProperty(lyId, 'visibility', 'none'); } catch (e) {}
            _activeRasterBaseId = null;
        }
        function _setOverlayVisible(l, visible) {
            if (visible) {
                const lyId = l.id + '_layer';
                _ensureSource(l, function() {
                    if (!map.getSource(l.id)) return;
                    const beforeId = _getFirstGeoJSONLayerId();
                    if (!map.getLayer(lyId)) {
                        try { map.addLayer({ id: lyId, type: 'raster', source: l.id, layout: { visibility: 'visible' } }, beforeId); } catch(e) {}
                    } else {
                        map.setLayoutProperty(lyId, 'visibility', 'visible');
                    }
                    // Apply configured opacity for image overlays (drone photos).
                    if (l.type === 'image') {
                        var iop = parseFloat((l.options || {}).opacity);
                        if (!isNaN(iop)) { try { map.setPaintProperty(lyId, 'raster-opacity', iop); } catch (e) {} }
                    }
                    // Same guarantee for overlay rasters — covers re-toggle cases where
                    // a previously-hidden overlay would otherwise stay below shapes only
                    // by accident of original insertion position.
                    _promoteShapesToTop();
                });
            } else {
                const lyId = l.id + '_layer';
                if (map.getLayer(lyId)) {
                    try { map.setLayoutProperty(lyId, 'visibility', 'none'); } catch (e) {}
                }
            }
        }

        // Re-add all cached GeoJSON sources/layers after setStyle({diff:false}) wipes them.
        // HTML markers (devices, labels) survive setStyle — do NOT re-add them here.
        // Falls back to a full API fetch only if cache is empty (first-load edge case).
        function _rehydrateFromCache() {
            var inst = window.AoTWidgetInstances[uniqueId];
            if (!inst) return;
            var defs = inst.layerDefs;
            if (!defs || defs.size === 0) {
                loadGeoJSONLayers(uniqueId, map, vars);
                return;
            }
            defs.forEach(function(entry, layerId) {
                if (!map.getSource(entry.sourceId)) {
                    try { map.addSource(entry.sourceId, { type: 'geojson', data: entry.geojson }); } catch(e) {}
                    inst.sources.set(entry.sourceId, entry.geojson);
                }
                if (!map.getLayer(layerId)) {
                    try { map.addLayer(entry.layerDef); } catch(e) {}
                    inst.layers.set(layerId, entry.layerDef.type);
                }
            });
            // Re-attach Three.js facility overlay (custom layer also wiped by setStyle).
            // attach() calls nativeMap.addLayer which puts the layer at absolute top —
            // this is intentional so it renders above all 2D GeoJSON layers.
            if (inst.cachedFacilities3d && inst.cachedFacilities3d.length && window.AoTFacilityMap3D) {
                var _rVars = ((window.AoTWidgetInstances[inst.uniqueId] || {}).vars || {});
                var _rOpts = (_rVars && _rVars.vars) || {};
                try { AoTFacilityMap3D.attach(map, inst.cachedFacilities3d, { hideLayers: ['facilities-3d'], renderMode: _rOpts.facility_render_mode || 'default' }); } catch(e) {}
                if (window.AoTMapSensorLabels) {
                    try {
                        var _vars = (window.AoTWidgetInstances[inst.uniqueId] || {}).vars || {};
                        var _o = (_vars && _vars.vars) || {};
                        AoTMapSensorLabels.attach(inst.uniqueId, map, inst.cachedFacilities3d, {
                            show: _o.show_sensor_labels !== false && _o.show_sensor_labels !== 'false',
                            style: _o.sensor_label_style || 'circle',
                            max_channels: parseInt(_o.sensor_label_max_channels || 1, 10),
                            decimals: parseInt(_o.sensor_label_decimals != null ? _o.sensor_label_decimals : 1, 10),
                            size_em: parseFloat(_o.sensor_label_size || 0.85),
                            bg: _o.sensor_label_bg || 'rgba(15,23,42,0.78)',
                            fg: _o.sensor_label_fg || '#f8fafc',
                            offset_y: parseFloat(_o.sensor_label_offset_y || 0),
                            opacity: _o.sensor_label_opacity != null ? parseFloat(_o.sensor_label_opacity) : 0.7,
                            popup: _o.sensor_popup_enabled !== false && _o.sensor_popup_enabled !== 'false',
                            collision: _o.enable_label_collision !== false && _o.enable_label_collision !== 'false',
                            spacing: (function () { var s = parseInt(_o.label_spacing, 10); return isNaN(s) ? 0 : s; })(),
                            refresh_seconds: parseInt(_o.period || 60, 10)
                        });
                    } catch (e) {}
                }
            }
        }

        // ---- Persistence ----
        function saveSelection() {
            const widgetId = (vars && vars.widgetId) || uniqueId;
            fetch('/save_widget_custom_options', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ widget_id: widgetId, options: { selected_base_layer: activeBase || '', active_layers: activeOverlays } })
            }).catch(function(e) { })
        }

        var _catHeadCss = 'font-weight:var(--aot-fw-bold);color:#444;font-size:var(--aot-fs-caption);text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #eee;margin-bottom:4px;padding-bottom:2px;';
        var _catRowCss = 'display:flex;align-items:center;gap:6px;padding:3px 0;cursor:pointer;font-size:var(--aot-fs-body);';

        // ---- Render: SHAPE-type (category) toggles — fill/line polygons only ----
        function _renderShapeTypes() {
            const head = document.createElement('div');
            head.style.cssText = _catHeadCss;
            head.style.marginTop = '8px';
            head.textContent = (window._ ? window._('Shapes') : 'Shapes');
            panel.appendChild(head);

            _CAT_DEFS.forEach(function (d) {
                if (!d.layers || !d.layers.length) return; // shape categories only
                const row = document.createElement('label');
                row.style.cssText = _catRowCss;
                const input = document.createElement('input');
                input.type = 'checkbox';
                input.checked = !_catHidden[d.cat];
                input.addEventListener('change', function () {
                    _applyShapeVisible(d.cat, input.checked);
                    _catSave(d.cat, !input.checked);
                });
                row.appendChild(input);
                const span = document.createElement('span');
                span.textContent = d.label;
                row.appendChild(span);
                panel.appendChild(row);
            });
        }

        // ---- Render: LABEL toggles — text/marker labels, independent of shapes ----
        // Mirrors the toolbar quick-buttons (input/output/function/facility) and adds
        // the remaining categories (site/zone/equipment/sensor). Both surfaces share
        // state through inst._setLabel / inst._readLabelHidden, so a checkbox here and a
        // quick-button up top stay in sync (see _syncLabelControls).
        function _renderLabelTypes() {
            const inst = window.AoTWidgetInstances[uniqueId];
            if (!inst || typeof inst._setLabel !== 'function') return;
            const _t = function (s) { return window._ ? window._(s) : s; };
            const head = document.createElement('div');
            head.style.cssText = _catHeadCss;
            head.style.marginTop = '8px';
            head.textContent = _t('Labels');
            panel.appendChild(head);

            const labelDefs = [
                { key: 'site',      label: _t('Site') },
                { key: 'zone',      label: _t('Zone') },
                { key: 'facility',  label: _t('Facility') },
                { key: 'equipment', label: _t('Equipment') },
                { key: 'input',     label: _t('Input') },
                { key: 'output',    label: _t('Output') },
                { key: 'function',  label: _t('Function') },
                { key: 'sensor',    label: _t('Sensor Values') }
            ];
            labelDefs.forEach(function (d) {
                const row = document.createElement('label');
                row.style.cssText = _catRowCss;
                const input = document.createElement('input');
                input.type = 'checkbox';
                input.id = 'label-cat-' + d.key + '-' + uniqueId;
                input.checked = !inst._readLabelHidden(d.key);
                input.addEventListener('change', function () {
                    inst._setLabel(d.key, !input.checked);
                });
                row.appendChild(input);
                const span = document.createElement('span');
                span.textContent = d.label;
                row.appendChild(span);
                panel.appendChild(row);
            });
        }

        // ---- Render panel ----
        function render() {
            panel.innerHTML = '';
            const groups = { base: [], overlay: [] };
            geoLayers.forEach(function(l) {
                groups[(l.role === 'base' || l.is_base) ? 'base' : 'overlay'].push(l);
            });

            ['base', 'overlay'].forEach(function(role) {
                if (!groups[role].length) return;
                const head = document.createElement('div');
                head.style.cssText = 'font-weight:var(--aot-fw-bold);color:#444;font-size:var(--aot-fs-caption);text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #eee;margin-bottom:4px;padding-bottom:2px;';
                head.textContent = role === 'base' ? (window._ ? window._('Base Map') : 'Base Map') : (window._ ? window._('Overlay') : 'Overlay');
                panel.appendChild(head);

                groups[role].forEach(function(l) {
                    const row = document.createElement('label');
                    row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:3px 0;cursor:pointer;font-size:var(--aot-fs-body);';
                    const input = document.createElement('input');
                    if (role === 'base') {
                        input.type = 'radio';
                        input.name = 'layer-base-' + uniqueId;
                        input.checked = activeBase ? (l.name === activeBase) : false;
                    } else {
                        input.type = 'checkbox';
                        input.checked = activeOverlays.indexOf(l.name) !== -1;
                    }
                    input.dataset.layerId = l.id;
                    input.dataset.layerName = l.name;
                    input.addEventListener('change', function() {
                        if (role === 'base') {
                            activeBase = l.name;
                            // Base map always switches regardless of _dataOnly (only overlay tiles are suppressed)
                            _deactivateRasterBase();
                            if ((l.type || 'xyz') === 'vector' && l.url) {
                                try { map.setStyle(l.url, { diff: false }); } catch (e) { }
                                // setStyle({ diff:false }) destroys all custom sources/layers — re-add after style loads.
                                // HTML markers (devices, labels) survive setStyle; do NOT re-add them (duplicates / stale data).
                                map.once('style.load', function() {
                                    var inst = window.AoTWidgetInstances[uniqueId];
                                    if (inst) { inst.sources.clear(); inst.layers.clear(); }
                                    // setStyle loaded an entirely new style — re-snapshot its layer ids so a
                                    // later raster-base switch (_hideAllVectorBase) hides THIS style's layers,
                                    // not the stale ids from whatever vector style was active before.
                                    map._aotBaseStyleIds = ((map.getStyle() || {}).layers || []).map(function(ly) { return ly.id; });
                                    // Re-add GeoJSON shapes from cache — no API calls needed.
                                    _rehydrateFromCache();
                                    // Re-apply active overlay raster layers (also wiped by setStyle).
                                    if (!_dataOnly) {
                                        geoLayers.forEach(function(l) {
                                            var isBase = l.role === 'base' || l.is_base;
                                            if (!isBase && activeOverlays.indexOf(l.name) !== -1) {
                                                _setOverlayVisible(l, true);
                                            }
                                        });
                                    }
                                });
                            } else {
                                _activateRasterBase(l);
                            }
                        } else {
                            if (input.checked) {
                                if (activeOverlays.indexOf(l.name) === -1) activeOverlays.push(l.name);
                                if (!_dataOnly) _setOverlayVisible(l, true);
                            } else {
                                activeOverlays = activeOverlays.filter(function(n) { return n !== l.name; });
                                if (!_dataOnly) _setOverlayVisible(l, false);
                            }
                            // Refresh legend when overlay selection changes
                            const inst = window.AoTWidgetInstances[uniqueId];
                            if (inst && typeof inst.refreshLegend === 'function') {
                                inst.refreshLegend(activeOverlays);
                            }
                        }
                        saveSelection();
                    });
                    row.appendChild(input);
                    const span = document.createElement('span');
                    span.textContent = l.name || l.id;
                    row.appendChild(span);
                    panel.appendChild(row);
                });
            });

            // Feature axes: shapes (fill/line) and labels (text), independently toggled.
            _renderShapeTypes();
            _renderLabelTypes();
        }

        btn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const opening = panel.style.display === 'none';
            panel.style.display = opening ? 'block' : 'none';
            if (opening) { render(); _adjustLayerPanelHeight(); }
        });
        document.addEventListener('click', function(e) {
            if (!layerWrap.contains(e.target) && !panel.contains(e.target)) {
                panel.style.display = 'none';
            }
        });

        // Apply initial overlay/base selection.
        // overlay_data_only suppresses OVERLAY tiles only (legend data comes from
        // geoConfig metadata). The BASE map must still render — the same contract the
        // interactive base switcher honors ("Base map always switches regardless of
        // _dataOnly"). Previously this whole block early-returned on _dataOnly, so a
        // saved raster base (e.g. VWorld) was never restored on refresh in data-only
        // widgets and the map fell back to the vector default style.
        const _dataOnly = innerVars.overlay_data_only === true || innerVars.overlay_data_only === 'true';
        geoLayers.forEach(function(l) {
            const isBase = (l.role === 'base' || l.is_base);
            if (isBase && activeBase && l.name === activeBase) {
                if ((l.type || 'xyz') !== 'vector') _activateRasterBase(l);
            } else if (!isBase && !_dataOnly && activeOverlays.indexOf(l.name) !== -1) {
                _setOverlayVisible(l, true);
            }
        });

        // Refresh a single overlay layer on demand.
        // {ts} layers (e.g. RainViewer): clears the cached API timestamp and rebuilds the
        // source with a fresh frame via _setOverlayVisible → _ensureSource.
        // Regular raster layers: cache-busts the tile URL so new tiles are fetched.
        // Skips silently when the layer is not currently visible.
        function _refreshOverlayLayer(l) {
            const lyId = l.id + '_layer';
            let visible = false;
            try { visible = !!(map.getLayer(lyId) && map.getLayoutProperty(lyId, 'visibility') !== 'none'); } catch(e) {}
            if (!visible) return;

            if ((l.url || '').indexOf('{ts}') !== -1) {
                delete _tsCache.rainviewer;
                try { if (map.getLayer(lyId)) map.removeLayer(lyId); } catch(e) {}
                try { map.removeSource(l.id); } catch(e) {}
                _setOverlayVisible(l, true);
            } else {
                const originalTiles = (function() {
                    if (l.type === 'wms') return ['/api/geo/proxy/wms/' + encodeURIComponent(l.id) + '?BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256'];
                    const url = (l.url || '').replace(/\{r\}/g, '');
                    if (url.indexOf('{s}') !== -1) return ['a', 'b', 'c'].map(function(s) { return url.replace(/\{s\}/g, s); });
                    return [url];
                })();
                const tileSize = parseInt((l.options || {}).tileSize || (l.options || {}).tile_size) || 256;
                _reloadTileSource(map, l.id, originalTiles, tileSize, [lyId]);
            }
        }

        const inst = window.AoTWidgetInstances[uniqueId];
        if (inst) {
            inst.layerPanelContainer = toolbar;
            inst.activeOverlays = activeOverlays;

            // Per-layer refresh timers driven by each layer's own refresh_interval.
            // Centralised here because addLayerPanel has closure access to _tsCache and
            // _setOverlayVisible, which are required to rebuild {ts}-based tile sources.
            if (!_dataOnly) {
                if (!inst.layerRefreshTimers) inst.layerRefreshTimers = {};
                // {ts} URL layers (e.g. RainViewer) require periodic API re-fetch even when
                // refresh_interval is not configured — fall back to 5 minutes (RainViewer
                // publishes new frames every ~5 min per their API docs).
                var _TS_DEFAULT_INTERVAL = 5 * 60;
                function _effectiveInterval(l) {
                    var n = parseInt(l.refresh_interval) || 0;
                    if (n > 0) return n;
                    return (l.url || '').indexOf('{ts}') !== -1 ? _TS_DEFAULT_INTERVAL : 0;
                }

                var _lastRefresh = {};
                geoLayers.forEach(function(l) {
                    var interval = _effectiveInterval(l);
                    if (interval <= 0) return;
                    _lastRefresh[l.id] = Date.now();
                    inst.layerRefreshTimers[l.id] = setInterval(function() {
                        if (document.hidden) return;
                        if (activeOverlays.indexOf(l.name) === -1) return;
                        _refreshOverlayLayer(l);
                        _lastRefresh[l.id] = Date.now();
                    }, interval * 1000);
                });

                // On tab resume, immediately refresh any layer that missed one or more
                // update cycles while the page was hidden.
                var _overlayVisHandler = function() {
                    if (document.hidden) return;
                    var now = Date.now();
                    geoLayers.forEach(function(l) {
                        var interval = _effectiveInterval(l);
                        if (interval <= 0) return;
                        if (activeOverlays.indexOf(l.name) === -1) return;
                        if ((now - (_lastRefresh[l.id] || 0)) >= interval * 1000) {
                            _refreshOverlayLayer(l);
                            _lastRefresh[l.id] = now;
                        }
                    });
                };
                inst._rvVisHandler = _overlayVisHandler;
                document.addEventListener('visibilitychange', _overlayVisHandler);
            }
        }
    }

    /**
     * Poll /notes/geo and render a marker for every note with GPS coords.
     * Direct port of v3 raster widget's renderMapNotes (Leaflet → MapLibre).
     * Each marker carries a popup with the note's tag, content preview, and
     * Edit / Open Notes / Remove buttons (same UX as v3).
     */
    function startMapNotesPolling(uniqueId, map, refreshSeconds) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;
        if (!instance.noteMarkers) instance.noteMarkers = new Map();

        function _t(key, fallback) {
            return (typeof window._ === 'function') ? window._(key) : (fallback || key);
        }

        function buildPopupHtml(note, noteId, tagName, content) {
            const safeTag = String(tagName || '').replace(/'/g, "\\'");
            const safeContent = String(content || '').replace(/'/g, "\\'");
            const tId = note.target_id || note.unique_id;
            const openAction = "window.dispatchEvent(new CustomEvent('open-notes', { detail: { targetId: '" + tId + "', targetType: 'map_location', name: '" + safeTag + "' } }))";
            const renameAction = "window.AoTMapApp['" + uniqueId + "'].updateMapNoteTags('" + noteId + "', document.getElementById('rename-input-" + noteId + "').value)";
            const deleteAction = "window.AoTMapApp['" + uniqueId + "'].deleteMapNote('" + noteId + "')";
            const toggleAction = "window.AoTMapApp['" + uniqueId + "'].toggleNoteEditMode('" + noteId + "')";
            return ''
                + '<div class="aot-popup-body">'
                + '  <div class="aot-popup-note-tag">' + safeTag + '</div>'
                + '  <div id="note-row2-view-' + noteId + '" style="display:flex;flex-direction:column;gap:10px;">'
                + '    <div class="aot-popup-note-actions">'
                + '      <button class="aot-popup-btn aot-popup-btn--secondary" onclick="' + toggleAction + '">' + _t('edit', 'Edit') + '</button>'
                + '      <button class="aot-popup-btn aot-popup-btn--primary" onclick="' + openAction + '">' + _t('Open Notes', 'Open Notes') + '</button>'
                + '    </div>'
                + '    <div class="aot-popup-note-content">'
                +        (safeContent || '<span style="color:#ccc;">' + _t('no_content', 'No content') + '</span>')
                + '    </div>'
                + '  </div>'
                + '  <div id="note-row2-edit-' + noteId + '" style="display:none;flex-direction:column;gap:8px;">'
                + '    <input type="text" id="rename-input-' + noteId + '" value="' + safeTag + '" class="aot-popup-rename-input">'
                + '    <div class="aot-popup-note-actions">'
                + '      <button class="aot-popup-btn aot-popup-btn--muted" onclick="' + deleteAction + '">' + _t('Remove from Map', 'Remove from Map') + '</button>'
                + '      <button class="aot-popup-btn aot-popup-btn--primary" onclick="' + renameAction + '">' + _t('Save', 'Save') + '</button>'
                + '    </div>'
                + '  </div>'
                + '</div>';
        }

        function renderMapNotes(force) {
            // Across N map widgets the polling ticks line up, so route /notes/geo
            // through the shared AoTGeoData cache (in-flight dedup + short TTL):
            // one network request feeds every widget per tick. Mutations and the
            // notes-closed event pass force=true to bypass the cache for freshness.
            const notesP = window.AoTGeoData
                ? window.AoTGeoData.get('/notes/geo', { force: !!force }).then(function(r) { return r.json(); })
                : fetch('/notes/geo').then(function(res) { return res.json(); });
            return notesP
                .then(function(notes) {
                    if (!Array.isArray(notes)) return;

                    // Track which note IDs are still on the server so we can
                    // remove markers for notes that were deleted/hidden.
                    const seen = new Set();

                    notes.forEach(function(note) {
                        if (note.gps_lat == null || note.gps_lng == null) return;
                        const lat = parseFloat(note.gps_lat);
                        const lng = parseFloat(note.gps_lng);
                        if (isNaN(lat) || isNaN(lng)) return;

                        const noteId = note.unique_id;
                        seen.add(noteId);

                        const uniqueTag = (note.tag_list || []).find(function(t) {
                            return t.name !== 'widget' && t.name !== 'map_hidden';
                        }) || { name: _t('New Note', 'New Note') };
                        const tagName = uniqueTag.name;
                        const content = note.note || '';
                        const html = buildPopupHtml(note, noteId, tagName, content);

                        if (instance.noteMarkers.has(noteId)) {
                            // Existing marker: refresh popup + position
                            const m = instance.noteMarkers.get(noteId);
                            m.setLngLat([lng, lat]);
                            const pop = m.getPopup();
                            if (pop) pop.setHTML(html);
                            return;
                        }

                        // Pin element (matches v3 divIcon styling)
                        const el = document.createElement('div');
                        el.className = 'aot-map-note-marker';
                        el.style.cssText = 'background:var(--gray-dark, #495057); border:2px solid #fff; border-radius:50%; width:24px; height:24px; display:flex; justify-content:center; align-items:center; box-shadow:0 2px 5px rgba(0,0,0,0.3); color:#fff; cursor:pointer;';
                        el.innerHTML = '<i class="fas fa-map-pin" style="font-size:12px;"></i>';

                        const popup = new maplibregl.Popup({ offset: 12, closeOnClick: false, className: 'aot-popup aot-popup--note' })
                            .setHTML(html);
                        const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
                            .setLngLat([lng, lat])
                            .setPopup(popup)
                            .addTo(map);
                        instance.noteMarkers.set(noteId, marker);
                    });

                    // Remove markers for notes that disappeared from /notes/geo.
                    instance.noteMarkers.forEach(function(marker, id) {
                        if (!seen.has(id)) {
                            try { marker.remove(); } catch (e) {}
                            instance.noteMarkers.delete(id);
                        }
                    });
                })
                .catch(function(e) { })
        }

        // Expose helpers used by v3-style popup buttons (Open / Edit / Save / Remove).
        window.AoTMapApp = window.AoTMapApp || {};
        window.AoTMapApp[uniqueId] = window.AoTMapApp[uniqueId] || {};
        window.AoTMapApp[uniqueId].renderMapNotes = renderMapNotes;

        function _csrf() {
            return (window.AoTMapData && window.AoTMapData.getCsrfToken)
                ? window.AoTMapData.getCsrfToken()
                : (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
        }

        function _parseJsonOrThrow(r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }

        window.AoTMapApp[uniqueId].updateMapNoteTags = function(noteId, newTagName) {
            fetch('/notes/update/' + noteId, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrf() },
                body: JSON.stringify({ new_tag_name: newTagName })
            }).then(_parseJsonOrThrow).then(function(d) {
                if (d && d.error) alert('Error: ' + d.error);
                else renderMapNotes(true);
            }).catch(function(e) { alert('Update failed: ' + e); });
        };

        window.AoTMapApp[uniqueId].deleteMapNote = function(noteId) {
            if (!confirm(_t('confirm_remove_pin', 'Remove pin from map?'))) return;
            fetch('/notes/toggle_map_visibility', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrf() },
                body: JSON.stringify({ unique_id: noteId, visible: false })
            }).then(_parseJsonOrThrow).then(function(d) {
                if (d && d.error) alert('Error: ' + d.error);
                else renderMapNotes(true);
            }).catch(function(e) { alert('Remove failed: ' + e); });
        };

        window.AoTMapApp[uniqueId].toggleNoteEditMode = function(noteId) {
            const v = document.getElementById('note-row2-view-' + noteId);
            const e = document.getElementById('note-row2-edit-' + noteId);
            if (v && e) {
                if (v.style.display === 'none') { v.style.display = 'flex'; e.style.display = 'none'; }
                else                            { v.style.display = 'none'; e.style.display = 'flex'; }
            }
        };

        // Refresh markers when the user creates/closes notes (force-fresh).
        window.addEventListener('notes-closed', function() { renderMapNotes(true); });

        // Initial fetch + poll at refreshSeconds interval (min 30s to avoid over-polling).
        const _noteIntervalMs = Math.max(30, refreshSeconds || 30) * 1000;
        renderMapNotes();
        instance.notePollTimer = setInterval(function() {
            if (document.hidden) return;
            renderMapNotes();
        }, _noteIntervalMs);
    }

    /**
     * Build measurement list for the bottom panel from vars.measurements_map.
     */
    function buildPanelMeasurements(measurementsMap, devices) {
        const out = [];
        if (!measurementsMap || typeof measurementsMap !== 'object') return out;

        const devList = Array.isArray(devices) ? devices : [];
        Object.keys(measurementsMap).forEach(function(devId) {
            const measList = measurementsMap[devId];
            if (!Array.isArray(measList)) return;
            const devObj = devList.find(function(d) {
                return d.device_unique_id === devId || d.unique_id === devId;
            });
            const fallbackName = devObj ? (devObj.device_name || devObj.name) : null;

            measList.forEach(function(m) {
                out.push({
                    id: m.id || (devId + '_0'),
                    device_unique_id: m.device_unique_id || devId,
                    device_type: m.device_type,
                    device_name: m.device_name || fallbackName,
                    // meas_name has no channel prefix; fall back to name only if meas_name absent
                    name: m.meas_name || m.device_name || fallbackName || m.label || 'Measurement',
                    unit: m.unit || '',
                    value: (m.last_value !== undefined && m.last_value !== null && m.last_value !== '') ? m.last_value : '-'
                });
            });
        });

        out.sort(function(a, b) {
            const an = a.device_name || a.name || '';
            const bn = b.device_name || b.name || '';
            return an.localeCompare(bn, undefined, { numeric: true, sensitivity: 'base' });
        });
        return out;
    }

    /**
     * Fetch the latest value for each panel measurement via /last/ and update the panel.
     */
    function refreshMeasurementPanelValues(uniqueId) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance || !instance.measurementPanel) return;
        const panel = instance.measurementPanel;
        const measurements = instance.panelMeasurements || [];

        measurements.forEach(function(m) {
            const devId = m.device_unique_id;
            const measId = m.id;
            const devType = m.device_type || 'input';
            if (!devId || !measId) return;

            // Resolve unit: aotMapUnits has proper display symbols (m/s, °C, bearing…)
            const resolvedUnit = (window.aotMapUnits && window.aotMapUnits[measId]) || m.unit || '';
            fetch('/last/' + encodeURIComponent(devId) + '/' + encodeURIComponent(devType) + '/' + encodeURIComponent(measId) + '/600')
                .then(function(res) {
                    if (!res.ok || res.status === 204) return null;
                    return res.json();
                })
                .then(function(data) {
                    if (data && Array.isArray(data) && data[1] !== null && data[1] !== undefined) {
                        panel.updateValue(measId, data[1], resolvedUnit);
                    }
                })
                .catch(function() {});
        });
    }

    /**
     * Add bottom-center measurement panel using AoTMapCustomControls.
     */
    /**
     * Sync --aot-dock-h on the map container with the dock's rendered height.
     * 0 when the panel is hidden (display:none → offsetParent null). Consumers:
     * legend chip/box, maplibregl-ctrl-bottom-left, advice panel (map.css).
     */
    function _updateDockHeightVar(uniqueId) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance || !instance.map) return;
        const container = instance.map.getContainer();
        if (!container) return;
        const handle = instance.measurementPanel;
        const panel = handle && handle.panel;
        const h = (panel && panel.offsetParent !== null) ? panel.offsetHeight : 0;
        container.style.setProperty('--aot-dock-h', h + 'px');

        // The measurement dock sits bottom-CENTER, but the copyright/scale controls
        // sit bottom-LEFT. Lifting the copyright by the full dock height whenever the
        // dock is visible leaves it floating in empty space on wide screens where the
        // two never overlap. Only lift it when the bottom-left control group would
        // actually collide with the centered dock horizontally.
        let leftLift = h;
        if (h > 0) {
            const bl = container.querySelector('.maplibregl-ctrl-bottom-left');
            if (bl && panel) {
                const GAP = 8; // px breathing room before they're considered touching
                const blRect = bl.getBoundingClientRect();
                const pRect = panel.getBoundingClientRect();
                if (blRect.right + GAP <= pRect.left) leftLift = 0;
            }
        }
        container.style.setProperty('--aot-dock-h-left', leftLift + 'px');

        // Dock visibility decides legend chip-vs-expanded mode — keep in sync
        if (typeof instance._syncLegendMode === 'function') instance._syncLegendMode();
    }

    function addMeasurementPanel(uniqueId, map, vars) {
        const LOG = '[AoT Map]';
        if (!window.AoTMapCustomControls || typeof window.AoTMapCustomControls.createMeasurementPanel !== 'function') {
            return;
        }
        const innerVars = (vars && vars.vars) || {};
        const panelMeasurements = buildPanelMeasurements(innerVars.measurements_map, vars.devices);
        // No early return on empty: the panel also hosts the facility control
        // summary row (setSummary), which must work without user measurements.
        // createMeasurementPanel keeps the panel hidden until content exists.

        // Dock collapse state: server option first, localStorage mirror as fallback
        // (same dual pattern as label_hidden_meas).
        const widgetId = (vars && vars.widgetId) || uniqueId;
        const _lsKey = 'aot_map_toggle_' + widgetId + '_meas_dock_collapsed';
        let initCollapsed;
        const sv = innerVars.meas_dock_collapsed;
        if (sv === true || sv === 'true') initCollapsed = true;
        else if (sv === false || sv === 'false') initCollapsed = false;
        else {
            try { initCollapsed = localStorage.getItem(_lsKey) === 'true'; } catch (e) { initCollapsed = false; }
        }

        // Panel font balance (control summary vs measurement text trade-off):
        // server option first, localStorage mirror as fallback
        // (same dual pattern as meas_dock_collapsed).
        const _lsBalKey = 'aot_map_toggle_' + widgetId + '_meas_panel_balance';
        let initBalance = parseFloat(innerVars.meas_panel_balance);
        if (!isFinite(initBalance)) {
            try { initBalance = parseFloat(localStorage.getItem(_lsBalKey)); } catch (e) { initBalance = NaN; }
        }
        if (!isFinite(initBalance)) initBalance = 0;

        // Wheel events fire in bursts — mirror to localStorage immediately,
        // debounce the server save until scrolling settles.
        let _balSaveTimer = null;
        function _persistBalance(balance) {
            try { localStorage.setItem(_lsBalKey, String(balance)); } catch (e) {}
            if (_balSaveTimer) clearTimeout(_balSaveTimer);
            _balSaveTimer = setTimeout(function() {
                fetch('/save_widget_custom_options', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ widget_id: widgetId, options: { meas_panel_balance: balance } })
                }).catch(function() {});
            }, 600);
        }

        const handle = window.AoTMapCustomControls.createMeasurementPanel(map, {
            measurements: panelMeasurements,
            updateInterval: innerVars.input_update_interval || 300,
            maxAge: innerVars.max_measure_age || 300,
            dock: true,
            collapsed: initCollapsed,
            balance: initBalance,
            onBalanceChange: _persistBalance,
            onCollapsedChange: function(collapsed) {
                fetch('/save_widget_custom_options', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ widget_id: widgetId, options: { meas_dock_collapsed: collapsed } })
                }).catch(function() {});
                try { localStorage.setItem(_lsKey, collapsed ? 'true' : 'false'); } catch (e) {}
                _updateDockHeightVar(uniqueId);
            }
        });
        const instance = window.AoTWidgetInstances[uniqueId];
        if (instance) {
            instance.measurementPanel = handle;
            instance.panelMeasurements = panelMeasurements;

            // Keep --aot-dock-h in sync with the rendered dock height so the
            // legend chip, attribution and advice panel ride above the dock.
            _updateDockHeightVar(uniqueId);
            if (typeof ResizeObserver !== 'undefined' && handle.panel) {
                const dockRo = new ResizeObserver(function() { _updateDockHeightVar(uniqueId); });
                dockRo.observe(handle.panel);
                instance._dockResizeObserver = dockRo;
            }
            // Copyright-vs-dock overlap depends on viewport width, so recompute the
            // left-side lift when the map is resized (window resize, panel toggles).
            try { map.on('resize', function() { _updateDockHeightVar(uniqueId); }); } catch (e) {}

            // Fetch live values immediately (backend initial value may be stale)
            setTimeout(function() { refreshMeasurementPanelValues(uniqueId); }, 200);

            // Periodic refresh for measurement values
            const refreshMs = Math.max(10, (innerVars.input_update_interval || 60)) * 1000;
            if (instance.panelRefreshTimer) clearInterval(instance.panelRefreshTimer);
            instance.panelRefreshTimer = setInterval(function() {
                if (document.hidden) return;
                refreshMeasurementPanelValues(uniqueId);
            }, refreshMs);
        }
    }

    /**
     * Build legend HTML for a single layer's legend data into a wrapper div.
     */
    function _buildLegendItem(layer) {
        const wrapper = document.createElement('div');
        wrapper.className = 'aot-legend-item-wrapper';
        wrapper.style.cssText = 'margin-bottom:6px;';
        // Layer name intentionally omitted — legend content is self-describing
        const legendData = layer.legend;
        // Resolve the layer's API key (mirrors aot-map-loader.js approach)
        const layerApiKey = layer.api_key
            || (layer.options && (layer.options.apiKey || layer.options.api_key))
            || '';

        if (legendData && legendData.type === 'html' && legendData.content) {
            const body = document.createElement('div');
            body.innerHTML = legendData.content;
            // Inject API key so _fetchLegendCenterValues can replace {apiKey} in URLs
            if (layerApiKey) {
                body.querySelectorAll('.aot-legend-value-box').forEach(function(box) {
                    box.dataset.apiKey = layerApiKey;
                });
            }
            wrapper.appendChild(body);
        } else if (legendData && legendData.type === 'img' && legendData.url) {
            const img = document.createElement('img');
            img.src = legendData.url;
            img.alt = (window._ ? window._('Legend') : 'Legend');
            img.style.cssText = 'max-width:100%;display:block;';
            wrapper.appendChild(img);
        } else if (legendData && Array.isArray(legendData.items)) {
            legendData.items.forEach(function(item) {
                const row = document.createElement('div');
                row.style.cssText = 'display:flex;align-items:center;gap:6px;line-height:1.4;';
                const swatch = document.createElement('span');
                swatch.style.cssText = 'display:inline-block;width:14px;height:14px;border:1px solid #ccc;background:' + (item.color || '#ccc') + ';';
                const lbl = document.createElement('span');
                lbl.textContent = item.label || '';
                row.appendChild(swatch);
                row.appendChild(lbl);
                wrapper.appendChild(row);
            });
        } else if (typeof legendData === 'string') {
            const body = document.createElement('div');
            body.innerHTML = legendData;
            wrapper.appendChild(body);
        }

        // Wrap trailing (unit) in .aot-legend-title for CSS-based hiding
        wrapper.querySelectorAll('.aot-legend-title').forEach(function(el) {
            const m = el.textContent.match(/^(.*?)\s*(\([^)]+\))\s*$/);
            if (m) {
                el.innerHTML = m[1] + '<span class="aot-legend-title-unit"> ' + m[2] + '</span>';
            }
        });

        return wrapper;
    }

    /**
     * Fetch center-point values for .aot-legend-value-box elements in legendEl.
     * Mirrors the dynamic updater from aot-map-loader.js.
     */
    function _fetchLegendCenterValues(legendEl, map) {
        if (!legendEl || legendEl.style.display === 'none') return;
        const boxes = legendEl.querySelectorAll('.aot-legend-value-box');
        if (!boxes.length) return;

        const center = map.getCenter();

        boxes.forEach(function(box) {
            const paramPath = box.getAttribute('data-api-param');
            const customUrl  = box.getAttribute('data-api-url');
            const dFactor    = box.getAttribute('data-d-factor');
            const valueText  = box.querySelector('.aot-legend-value-text');
            if (!valueText || !paramPath || !customUrl) return;

            const apiKey = box.dataset.apiKey || '';
            // Skip if URL still needs an apiKey that wasn't provided
            if (!apiKey && /\{apiKey\}|appid=&|appid=$/.test(customUrl)) {
                valueText.innerText = '-';
                return;
            }

            // Round to 3 decimals (~111m) to maximise cache hits on small map pans.
            // ISRIC SoilGrids native resolution is ~250m, so this loses no useful precision.
            const rLat = Math.round(center.lat * 1000) / 1000;
            const rLng = Math.round(center.lng * 1000) / 1000;
            const url = customUrl
                .replace(/\{lat\}/g,    rLat)
                .replace(/\{lon\}/g,    rLng)
                .replace(/\{lng\}/g,    rLng)
                .replace(/\{apiKey\}/g, apiKey);

            valueText.innerText = '…';

            const req = (window.AoTAPIManager && typeof window.AoTAPIManager.request === 'function')
                ? window.AoTAPIManager.request(url)
                : fetch(url).then(function(r) { return r.json(); });

            req.then(function(data) {
                    const keys = paramPath.split('.');
                    let val = data;
                    for (let k of keys) {
                        if (val != null && k in Object(val)) {
                            val = val[k];
                        } else if (Array.isArray(val) && !isNaN(parseInt(k))) {
                            val = val[parseInt(k)];
                        } else { val = undefined; break; }
                    }
                    if (val !== undefined && val !== null) {
                        let num = parseFloat(val);
                        if (dFactor) num = num / parseFloat(dFactor);
                        valueText.innerText = isNaN(num) ? val : (Math.round(num * 100) / 100);
                    } else {
                        valueText.innerText = '-';
                    }
                })
                .catch(function() { valueText.innerText = '-'; });
        });
    }

    /**
     * Measurement panel is always bottom-center regardless of legend visibility.
     * Legend is positioned above the panel via CSS (bottom: 120px desktop / 100px mobile).
     */
    function _syncLegendPanelLayout(instance) {
        const panel = instance.measurementPanel && instance.measurementPanel.panel;
        if (!panel) return;
        panel.classList.remove('left-aligned');
        panel.style.maxWidth = '';
    }

    /**
     * Overlay legend panel in the bottom-right corner.
     * Uses vars.geoConfig.layers as the full layer list (which carries legend
     * metadata). Exposes instance.refreshLegend(activeLayerNames) so the layer
     * panel can call it when overlay selection changes.
     */
    function addLegendOverlay(uniqueId, map, vars) {
        const allLayers = (vars && vars.geoConfig && vars.geoConfig.layers)
            || (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.layers)
            || (vars && vars.layers)
            || [];

        const mapCanvas    = map.getContainer();                                               // maplibregl canvas wrapper
        const mapId        = vars.mapId || ('aot-map-' + uniqueId);
        const mapContainer = document.getElementById(mapId) || mapCanvas.parentElement || mapCanvas;  // .aot-map-container
        mapContainer.style.position = mapContainer.style.position || 'relative';

        const _legendVars = (vars && vars.vars) || {};
        const _dataOnlyMode = _legendVars.overlay_data_only === true || _legendVars.overlay_data_only === 'true';

        const legendEl = document.createElement('div');
        legendEl.className = 'aot-legend-container aot-vector-legend';

        // The legend is always placed at the bottom-right inside mapContainer (its normal position)
        // _dataOnlyMode: only the overlay tiles are hidden (handled by addLayerPanel); the base map and legend show normally
        legendEl.style.cssText = 'position:absolute; right:10px; max-width:220px; overflow-y:auto; font-size:var(--aot-fs-caption); color:#333; display:none; box-sizing:border-box;';
        mapContainer.appendChild(legendEl);

        // Collapsed legend chip — the resting state. Clicking expands the legend
        // box; clicking outside collapses it again. Session-only (not persisted).
        const chipEl = document.createElement('div');
        chipEl.className = 'aot-legend-chip';
        chipEl.textContent = (window._ ? window._('Legend') : 'Legend');
        chipEl.style.display = 'none';
        mapContainer.appendChild(chipEl);

        const instance = window.AoTWidgetInstances[uniqueId];
        if (instance) instance._legendExpanded = false;

        // If there is no measurement panel, lower the legend by the panel's bottom y offset (bottom: 32px)
        if (!instance || !instance.measurementPanel) {
            legendEl.classList.add('aot-legend-no-panel');
        }

        let _hasLegend = false;

        // Chip mode only makes sense when the measurement dock occupies the
        // bottom edge. Without it the legend stays expanded — collapsing would
        // force an extra click just to read legend values.
        function _dockVisible() {
            const inst = window.AoTWidgetInstances[uniqueId];
            const p = inst && inst.measurementPanel && inst.measurementPanel.panel;
            return !!(p && p.offsetParent !== null);
        }

        // Apply the current display state (box vs chip). Fetches center values
        // when the box transitions from hidden to visible.
        function _applyLegendMode() {
            const wasVisible = legendEl.style.display !== 'none';
            if (!_hasLegend) {
                legendEl.style.display = 'none';
                chipEl.style.display = 'none';
                if (instance) instance._legendExpanded = false;
                return;
            }
            const chipMode = _dockVisible();
            if (!chipMode || (instance && instance._legendExpanded)) {
                if (instance) instance._legendExpanded = true;
                legendEl.style.display = 'block';
                chipEl.style.display = 'none';
                if (!wasVisible) {
                    setTimeout(function() { _fetchLegendCenterValues(legendEl, map); }, 50);
                }
            } else {
                legendEl.style.display = 'none';
                chipEl.style.display = 'flex';
            }
        }

        function _expandLegend() {
            if (!_hasLegend) return;
            if (instance) instance._legendExpanded = true;
            _applyLegendMode();
        }

        function _collapseLegend() {
            if (!_dockVisible()) return;  // no chip mode → stay expanded
            if (instance) instance._legendExpanded = false;
            _applyLegendMode();
        }

        chipEl.addEventListener('click', function(e) {
            e.stopPropagation();
            _expandLegend();
        });

        // Outside click/touch collapses the expanded legend (chip mode only)
        document.addEventListener('pointerdown', function(e) {
            if (!instance || !instance._legendExpanded) return;
            if (legendEl.contains(e.target) || chipEl.contains(e.target)) return;
            _collapseLegend();
        });

        function refreshLegend(activeLayerNames) {
            legendEl.innerHTML = '';
            const names = Array.isArray(activeLayerNames) ? activeLayerNames
                : (typeof activeLayerNames === 'string' ? activeLayerNames.split(',').map(function(s) { return s.trim(); }) : []);

            const candidates = allLayers.filter(function(l) {
                if (!l || !l.legend) return false;
                if (l.enabled === false) return false;
                if (!names.length) return false;  // no active overlays → show no legend
                return names.indexOf(l.name)               !== -1
                    || names.indexOf(l.id)                 !== -1
                    || names.indexOf(String(l.unique_id || '')) !== -1;
            });

            _hasLegend = candidates.length > 0;
            if (_hasLegend) {
                candidates.forEach(function(layer) { legendEl.appendChild(_buildLegendItem(layer)); });
            }
            // Content was rebuilt — force a fresh fetch when the box shows
            legendEl.style.display = 'none';
            _applyLegendMode();

            // Reposition measurement panel after legend visibility change
            if (instance) { _syncLegendPanelLayout(instance); }
        }

        // Re-fetch center values on map move (debounced) — only while expanded,
        // so the legend center-value API stays quiet in the collapsed state.
        let _moveDebounce;
        map.on('moveend', function() {
            clearTimeout(_moveDebounce);
            _moveDebounce = setTimeout(function() {
                if (!instance || !instance._legendExpanded) return;
                _fetchLegendCenterValues(legendEl, map);
            }, 500);
        });

        // Get initial active overlays from widget custom_options
        const innerVars = (vars && vars.vars) || {};
        const initActive = _resolveActiveOverlayNames(innerVars.active_layers);

        refreshLegend(initActive);

        if (instance) {
            instance.legendEl        = legendEl;
            instance.legendChipEl    = chipEl;
            instance.refreshLegend   = refreshLegend;
            instance._syncLegendMode = _applyLegendMode;
        }
    }

    /**
     * Apply global panel background from geo design theme settings.
     * Reads vars.theme.panel_bg (hex, default #ffffff) and
     * vars.theme.panel_opacity (0-100, default 90), then applies the
     * resulting rgba background to all panels created by this widget instance.
     */
    function applyPanelOpacity(uniqueId, vars) {
        const theme = (vars && vars.theme) || {};
        const globalTheme = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) || {};
        const rawOpacity = theme.panel_opacity !== undefined ? theme.panel_opacity
            : (globalTheme.panel_opacity || 90);
        const opacity = Math.min(1, Math.max(0, parseInt(rawOpacity) / 100));
        if (isNaN(opacity)) return;

        const hex = theme.panel_bg || globalTheme.panel_bg || '#ffffff';
        const m = /^#?([0-9a-f]{6})$/i.exec(hex);
        const rgb = m ? [parseInt(m[1].substr(0, 2), 16), parseInt(m[1].substr(2, 2), 16), parseInt(m[1].substr(4, 2), 16)].join(',') : '255,255,255';
        const bg = 'rgba(' + rgb + ',' + opacity + ')';
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        // Set CSS variable on map container — cascades to both .aot-measurement-panel
        // and .aot-legend-container (bypasses !important on background-color).
        const mapContainer = instance.map ? instance.map.getContainer() : null;
        if (mapContainer) {
            mapContainer.style.setProperty('--panel-bg-rgba', bg);
        }
    }

    /**
     * Add device markers to map
     */
    function addDeviceMarkers(uniqueId, map, devices, theme, vars) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        const wOpts = (vars && vars.vars) || {};
        const showDeviceLabels = wOpts.show_device_labels === true || wOpts.show_device_labels === 'true';
        const globalLabelSize = parseFloat(wOpts.global_label_size) || 1.0;
        const labelCollision   = wOpts.enable_label_collision !== false && wOpts.enable_label_collision !== 'false';
        const _rawSpacingD     = parseInt(wOpts.label_spacing);
        const labelSpacing     = (!isNaN(_rawSpacingD) && wOpts.label_spacing !== '' && wOpts.label_spacing !== null && wOpts.label_spacing !== undefined) ? _rawSpacingD : 0;

        // Build allowed ID set for strict filtering (mirrors v3 renderDevices)
        const allowedIds = new Set();
        const fetchIds = wOpts.map_device_ids || wOpts.device_ids;
        if (fetchIds && wOpts.include_all_devices !== true) {
            String(fetchIds).split(',').forEach(function(id) {
                const t = id.trim();
                if (t) {
                    allowedIds.add(t);
                    if (t.includes('::')) allowedIds.add(t.split('::')[0]);
                }
            });
        }
        const isStrictFiltering = (allowedIds.size > 0 && wOpts.include_all_devices !== true);

        // Clear existing device markers and cluster badges before re-rendering
        instance.markers.forEach(function(m) { m.remove(); });
        instance.markers.clear();

        if (instance.deviceClusterMarkers) {
            instance.deviceClusterMarkers.forEach(function(m) { try { m.remove(); } catch(e) {} });
        }
        instance.deviceClusterMarkers = [];
        instance.deviceLabelMarkers = [];

        if (instance._deviceCollisionHandler) {
            map.off('moveend', instance._deviceCollisionHandler);
            map.off('zoomend', instance._deviceCollisionHandler);
            instance._deviceCollisionHandler = null;
        }

        // Build deviceTypeMap: baseUUID → device_type ('input'|'output'|'function')
        // Used by _applyTypeHide to also cover geoDeviceLabelMarkers
        if (!instance._deviceTypeMap) instance._deviceTypeMap = {};
        devices.forEach(function(dev) {
            const baseId = String(dev.device_id || dev.device_unique_id ||
                (dev.unique_id ? dev.unique_id.split('::')[0] : (dev.id || '').split('::')[0]));
            if (baseId) instance._deviceTypeMap[baseId] = dev.device_type || dev.type || '';
        });

        // Apply persisted hide state to geo-device labels now that _deviceTypeMap is built
        // (loadGeoDesignLabels runs before this, so it can't do this itself)
        var _hiddenTypes = instance._hiddenTypes || {};
        (instance.geoDeviceLabelMarkers || []).forEach(function(marker) {
            if (!marker || typeof marker.getElement !== 'function') return;
            var el = marker.getElement();
            if (!el) return;
            var parentId = el.dataset.parentId || '';
            var devType = instance._deviceTypeMap[parentId];
            if (!devType) return;
            el.classList.toggle('aot-type-hidden', !!_hiddenTypes[devType]);
        });

        devices.forEach(function(dev) {
            const devLat = dev.lat || dev.latitude;
            const devLng = dev.lng || dev.longitude;
            if (!devLat || !devLng) return;

            // Strict device filtering
            if (isStrictFiltering) {
                const devId = String(dev.id || dev.unique_id || '');
                const baseId = devId.split('::')[0];
                if (!allowedIds.has(devId) && !allowedIds.has(baseId)) return;
            }

            // [3-way Actuator] Initial render: always off-style. Motion (detected from
            // position changes between polls or commandActuator calls) flips it to ON.
            const isON = (dev.control_kind === 'value_3way')
                ? false
                : (dev.status === 'active' || dev.status === 'on' ||
                   dev.is_activated === true || dev.is_activated === 'true');

            const devType2 = dev.device_type || dev.type || '';
            const userColor = getUnifiedDeviceColor(devType2, dev, theme);

            const popup = createDevicePopup(uniqueId, dev, wOpts);

            if (showDeviceLabels) {
                // Pill label style (show_device_labels = true)
                const displayName = (dev.device_name || dev.name ||
                    (dev.unique_id || dev.id || '').toString().split('::')[0] || '').toString().trim();
                if (!displayName) return;

                const targetMap = wOpts.all_measurements_map || wOpts.measurements_map || {};
                const devIdKey = dev.device_id || dev.device_unique_id ||
                                 (dev.unique_id ? dev.unique_id.split('::')[0] : (dev.id || '').split('::')[0]);
                const devMeas = targetMap[devIdKey] || [];
                let firstVal = '';
                let unit = '';
                if (devMeas.length > 0) {
                    const m = devMeas.find(function(x) { return parseInt(x.channel) === parseInt(dev.channel_id); }) || devMeas[0];
                    if (m && m.last_value !== undefined && m.last_value !== null && m.last_value !== '') {
                        firstVal = m.last_value;
                        unit = (window.aotMapUnits && window.aotMapUnits[m.id]) ? window.aotMapUnits[m.id] : (m.unit || '');
                        if (unit === 'bearing') unit = '';
                    }
                }
                // [3-way Actuator] Override label value with current position % (and direction arrow)
                if (dev.control_kind === 'value_3way') {
                    const p = (typeof dev.position_pct === 'number') ? dev.position_pct : 0;
                    const dir = dev.motion_dir;
                    const arrow = (dir === 'open') ? '▲ ' : (dir === 'close') ? '▼ ' : '';
                    firstVal = arrow + Math.round(p);
                    unit = '%';
                }

                let baseSize = globalLabelSize;
                if (dev.font_size) {
                    const scale = parseInt(dev.font_size);
                    if (!isNaN(scale)) baseSize = baseSize * (1 + ((scale - 1) * 0.2));
                }

                const showValue = firstVal !== '' && firstVal !== undefined && firstVal !== null;
                const shadowColorOff = hexToRgba(userColor, 0.3);
                const shadowColorOn  = hexToRgba(userColor, 0.6);
                const pillStyle = isON
                    ? 'background-color:' + userColor + ';color:#fff;border:2px solid #fff !important;box-shadow:0 4px 12px ' + shadowColorOn + ' !important;'
                    : 'background-color:#fff;color:' + userColor + ';border:2px solid ' + userColor + ' !important;box-shadow:0 2px 5px ' + shadowColorOff + ' !important;';

                const labelHtml =
                    '<div class="aot-label-content marker-pill' + (isON ? ' device-on' : '') + '" ' +
                    'style="' + pillStyle + 'font-size:' + baseSize + 'em;padding:4px 8px;border-radius:12px;' +
                    'width:max-content;white-space:nowrap;margin:0;' + (dev.label_style || '') + '">' +
                    '<div style="line-height:1.2">' +
                    '<span class="dev-name">' + displayName + '</span>' +
                    (showValue
                        ? '<span class="dev-val-group" style="display:inline;margin-left:4px">' +
                          '<span class="dev-value">' + firstVal + '</span>' +
                          '<span class="dev-unit aot-w-unit" style="font-size:var(--aot-fs-caption);margin-left:2px">' + unit + '</span>' +
                          '</span>'
                        : '') +
                    '</div></div>';

                const el = document.createElement('div');
                el.className = 'aot-device-label-wrapper';
                el.dataset.labelName  = displayName;
                el.dataset.labelColor = userColor;
                el.dataset.deviceType = devType2;
                el.innerHTML = labelHtml;
                // Apply persisted hide state immediately on creation
                if (instance._hiddenTypes && instance._hiddenTypes[devType2]) {
                    el.classList.add('aot-type-hidden');
                }

                const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
                    .setLngLat([parseFloat(devLng), parseFloat(devLat)])
                    .addTo(map);

                el.addEventListener('click', function(e) {
                    e.stopPropagation();
                    if (popup.isOpen()) { popup.remove(); }
                    else { popup.setLngLat([parseFloat(devLng), parseFloat(devLat)]).addTo(map); }
                });

                instance.markers.set(dev.unique_id || dev.id, marker);
                instance.markers.set('__popup__' + (dev.unique_id || dev.id), { remove: function() { popup.remove(); } });
                instance.deviceLabelMarkers.push(marker);

            } else {
                // Dot style (show_device_labels = false, default)
                const el = document.createElement('div');
                el.className = 'map-marker-dot' + (isON ? ' device-on' : '');
                el.dataset.deviceType = devType2;
                el.style.cssText =
                    'background-color:' + (isON ? userColor : '#fff') + ';' +
                    'border:2px solid ' + userColor + ';' +
                    'opacity:' + (dev.opacity !== undefined ? dev.opacity : 1) + ';' +
                    'cursor:pointer;';
                // Apply persisted hide state immediately on creation
                if (instance._hiddenTypes && instance._hiddenTypes[devType2]) {
                    el.classList.add('aot-type-hidden');
                }

                const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
                    .setLngLat([parseFloat(devLng), parseFloat(devLat)])
                    .addTo(map);

                el.addEventListener('click', function(e) {
                    e.stopPropagation();
                    if (popup.isOpen()) { popup.remove(); }
                    else { popup.setLngLat([parseFloat(devLng), parseFloat(devLat)]).addTo(map); }
                });

                instance.markers.set(dev.unique_id || dev.id, marker);
                instance.markers.set('__popup__' + (dev.unique_id || dev.id), { remove: function() { popup.remove(); } });
            }
        });

        // Device label collision — joins unified handler (all groups run together in priority order)
        if (showDeviceLabels && labelCollision && instance.deviceLabelMarkers.length > 0) {
            instance._labelSpacing = labelSpacing;
            _updateUnifiedCollisionHandler(instance, map, labelSpacing);
            // Single settled reveal pass (see note in loadGeoDesignLabels) — avoids the
            // rAF-vs-idle disagreement that flickered boundary input labels.
            _revealLabelsOnce(instance, map, labelSpacing);
        }

        // Sync device shape opacity with initial on/off state
        _updateDeviceShapeOpacity(instance, devices);
    }

    function hexToRgba(hex, alpha) {
        if (!hex) return 'rgba(0,0,0,' + alpha + ')';
        const r = parseInt(hex.slice(1, 3), 16) || 0;
        const g = parseInt(hex.slice(3, 5), 16) || 0;
        const b = parseInt(hex.slice(5, 7), 16) || 0;
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    // Color priority: Theme (type-specific → generic) → device label_color → device color → fallback
    function getUnifiedDeviceColor(type, dev, theme) {
        if (theme) {
            if (theme[type + '-color']) return theme[type + '-color'];
            if (theme[type]) return theme[type];
            if (theme['aot_device-color']) return theme['aot_device-color'];
            if (theme['aot_device']) return theme['aot_device'];
            if (theme.device) return theme.device;
        }
        if (dev && dev.label_color) return dev.label_color;
        var bc = dev && (dev.color || dev.marker_color);
        if (bc && bc.trim()) return bc.trim();
        return (theme && theme.primary) || '#995aff';
    }

    /**
     * Create device popup (MapLibre) — exact port of v3 bindDevicePopup.
     * Returns { popup, onOpen } where onOpen must be called after marker.setPopup(popup).addTo(map).
     */
    function createDevicePopup(uniqueId, dev, wOpts) {
        const devType = dev.device_type || dev.type || '';
        const isInput = devType === 'input';
        const isOutput = devType === 'output' || devType === 'function';
        const isON = dev.status === 'active' || dev.status === 'on' ||
                     dev.is_activated === true || dev.is_activated === 'true';

        const displayName = dev.device_name || dev.name || dev.unique_id || 'Device';
        const uniqueKey = dev.device_id || dev.device_unique_id ||
                          (dev.unique_id ? dev.unique_id.split('::')[0] : (dev.id || '').split('::')[0]);
        const channel = (dev.channel_id && dev.channel_id !== 'undefined') ? dev.channel_id : 0;
        const notePreviewId = 'note-prev-' + uniqueKey; // matches AoTMapPopup.buildNoteSection()

        const targetMap = (wOpts && (wOpts.all_measurements_map || wOpts.measurements_map)) || {};
        const devMeas = targetMap[uniqueKey] || [];

        // ----- Input device → shared facility sensor modal -----
        // Input devices open the SAME modal component as facility fitting sensors
        // (AoTSensorLabel.openPopup): identical chrome, 24h chart, and legend — one
        // popup component, not a map popup with facility content embedded. Returns a
        // lightweight proxy implementing the MapLibre Popup interface that the marker
        // click handlers use, but driving the shared modal instead.
        if (isInput) {
            const sensorObj = {
                name: displayName,
                fitting_id: uniqueKey,
                device_id: uniqueKey,
                channels: devMeas.map(function(m) {
                    var u = (window.aotMapUnits && window.aotMapUnits[m.id]) ? window.aotMapUnits[m.id] : (m.unit || '');
                    return {
                        key: m.meas_name || m.name || '',
                        measurement_id: m.id,
                        value: (m.last_value !== undefined && m.last_value !== null && m.last_value !== '') ? m.last_value : null,
                        unit: (u === 'bearing') ? '' : u
                    };
                })
            };
            return {
                // Click always (re)opens the modal — same UX as facility sensor labels.
                isOpen: function() { return false; },
                setLngLat: function() { return this; },
                addTo: function() {
                    if (window.AoTSensorLabel && window.AoTSensorLabel.openPopup) {
                        window.AoTSensorLabel.openPopup(sensorObj, {
                            modal: true,
                            note: { targetId: uniqueKey, targetType: 'device', name: displayName }
                        });
                    }
                    return this;
                },
                remove: function() {
                    if (window.AoTSensorLabel && window.AoTSensorLabel.closePopup) window.AoTSensorLabel.closePopup();
                    return this;
                },
                on: function() { return this; },
                getElement: function() { return null; }
            };
        }

        // ----- Notes section (shared utility) -----
        const noteSectionHtml = window.AoTMapPopup
            ? window.AoTMapPopup.buildNoteSection(uniqueKey, displayName)
            : '<hr class="aot-popup-divider">' +
              '<button class="aot-popup-btn aot-popup-btn--primary aot-popup-btn--full" onclick="window.dispatchEvent(new CustomEvent(\'open-notes\',{detail:{targetId:\'' + uniqueKey + '\',targetType:\'device\',name:\'' + displayName.replace(/'/g, "\\'") + '\'}}))"> ' +
              (window._ ? window._('Create Note') : 'Create Note') + '</button>' +
              '<div id="' + notePreviewId + '" class="aot-popup-note-preview"><span style="color:#ccc;font-style:italic">...</span></div>';

        // Hoist devId/toggleId to function scope so onOpen closure can access them
        const devId = dev.id || dev.unique_id || '';
        const toggleId = 'toggle-' + devId;

        let html = '';

        if (dev.control_kind === 'value_3way') {
            // ----- 3-way Actuator popup: Open/Stop/Close + slider -----
            const posInit = (typeof dev.position_pct === 'number') ? dev.position_pct : 0;
            const posRounded = Math.round(posInit);
            const posDispId = 'pos-disp-' + devId;
            const sliderId = 'pos-slider-' + devId;
            const cmd = function(action, valueExpr) {
                return "window.AoTMapLoader.commandActuator('" + devId + "','" + action + "'," + valueExpr + ",'" + channel + "','" + uniqueId + "')";
            };
            const headerHtml3 =
                '<div class="aot-3way-header">' +
                '<div class="aot-popup-title">' + displayName + '</div>' +
                '<div id="' + posDispId + '" class="aot-3way-position">' + posRounded + '%</div></div>';
            const buttonsHtml =
                '<div class="aot-3way-buttons">' +
                '<button class="aot-popup-btn aot-popup-btn--ctrl" onclick="' + cmd('close', '0') + '">' + (window._ ? window._('Close') : 'Close') + '</button>' +
                '<button class="aot-popup-btn aot-popup-btn--ctrl" onclick="' + cmd('stop', 'null') + '">' + (window._ ? window._('Stop') : 'Stop') + '</button>' +
                '<button class="aot-popup-btn aot-popup-btn--ctrl" onclick="' + cmd('open', '100') + '">' + (window._ ? window._('Open') : 'Open') + '</button></div>';
            const sliderHtml =
                '<div class="aot-3way-slider-wrap">' +
                '<input type="range" id="' + sliderId + '" class="aot-3way-slider" min="0" max="100" step="1" value="' + posRounded + '" ' +
                'data-current="' + posRounded + '" ' +
                'style="--aot-current-pct: ' + posRounded + '%;" ' +
                'oninput="document.getElementById(\'' + posDispId + '\').innerText = this.value + \'%\'" ' +
                'onchange="' + cmd('goto', 'parseFloat(this.value)') + '">' +
                '<div class="aot-3way-current-dot"></div></div>';
            // [3-way] Only Last Work Time; Current Work Time has no meaningful value at rest.
            const infoHtml3 =
                '<div class="aot-3way-info">' +
                '<div class="aot-3way-info-row">' +
                '<span class="aot-3way-info-label">' + (window._ ? window._('Last Work Time') : 'Last Work Time') + '</span>' +
                '<span id="last-dur-' + devId + '" class="aot-3way-info-value">00:00:00</span></div></div>';
            html = '<div class="aot-3way-popup aot-popup-body">' + headerHtml3 + buttonsHtml + sliderHtml + infoHtml3 + noteSectionHtml + '</div>';

        } else {
            // ----- Output / Function popup: name + toggle + timer -----
            const durId = 'dur-' + devId;
            const canControl = isOutput;

            const btnHtml = '<label class="btn-toggle" style="margin-bottom:0">' +
                '<input type="checkbox" id="' + toggleId + '" class="btn-toggle-input" ' + (isON ? 'checked' : '') +
                (canControl ? '' : ' disabled') +
                ' onchange="(function(cb,ev){' +
                    'if(ev)ev.stopPropagation();' +
                    'var inst=window.AoTWidgetInstances&&window.AoTWidgetInstances[\'' + uniqueId + '\'];' +
                    'if(inst&&inst.markers){var mk=inst.markers.get(\'' + devId + '\');' +
                    'if(mk){mk._pendingToggle=Date.now();mk._isActive=cb.checked;}}' +
                    'if(window.AoTMapLoader&&window.AoTMapLoader.toggleDevice){' +
                    'window.AoTMapLoader.toggleDevice(\'' + devId + '\',cb.checked,\'' + channel + '\',\'' + devType + '\');}' +
                    'else{' +
                    'var bid=\'' + devId + '\'.split(\'::\')[0];' +
                    'if(\'' + devType + '\'===\'function\'){' +
                    'var fd=new FormData();fd.append(\'function_id\',bid);fd.append(cb.checked?\'function_activate\':\'function_deactivate\',\'True\');' +
                    'fetch(\'/function_submit\',{method:\'POST\',body:fd}).catch(function(){});}' +
                    'else{fetch(\'/api/outputs/\'+bid,{method:\'POST\',' +
                    'headers:{\'Content-Type\':\'application/vnd.aot.v1+json\',\'Accept\':\'application/vnd.aot.v1+json\'},' +
                    'body:JSON.stringify({state:cb.checked,channel:\'' + channel + '\'})}).catch(function(){});}}' +
                '})(this,event)">' +
                '<span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span></label>';

            const headerHtml =
                '<div class="aot-popup-header">' +
                '<div class="aot-popup-title" style="margin:0">' + displayName + '</div>' +
                '<div style="flex:0 0 auto">' + btnHtml + '</div></div>';

            const infoHtml =
                '<div class="aot-popup-info">' +
                '<div class="aot-popup-info-row">' +
                '<span class="aot-popup-info-label">' + (window._ ? window._('Current Work Time') : 'Current Work Time') + '</span>' +
                '<span id="' + durId + '" class="aot-timer-display aot-popup-info-value">00:00:00</span></div>' +
                '<div class="aot-popup-info-row">' +
                '<span class="aot-popup-info-label">' + (window._ ? window._('Last Work Time') : 'Last Work Time') + '</span>' +
                '<span id="last-dur-' + devId + '" class="aot-popup-info-value">00:00:00</span></div></div>';

            html = '<div class="aot-popup-body">' + headerHtml + infoHtml + noteSectionHtml + '</div>';
        }

        const popup = new maplibregl.Popup({ offset: 12, className: 'aot-popup aot-popup--device' }).setHTML(html);

        // ----- onOpen: fetch fresh values + notes -----
        function onOpen() {
            // [3-way] Position current-dot after popup DOM is ready
            if (dev.control_kind === 'value_3way') {
                requestAnimationFrame(function () {
                    var sl = document.getElementById('pos-slider-' + devId);
                    if (sl && window.AoTMapPopup) window.AoTMapPopup.positionDots(sl.parentElement);
                });
            }

            // Fetch last note
            var noteEl = document.getElementById(notePreviewId);
            if (noteEl) {
                fetch('/notes/target/' + uniqueKey)
                    .then(function(r) { return r.json(); })
                    .then(function(notes) {
                        if (!noteEl) return;
                        if (notes && notes.length > 0) {
                            noteEl.innerText = notes[0].note;
                            noteEl.style.fontStyle = 'normal';
                        } else {
                            noteEl.innerHTML = '<span style="color:#ccc;font-style:italic">' + (window._ ? window._('No Notes') : 'No Notes') + '</span>';
                        }
                    }).catch(function() {});
            }

            // Input devices never reach onOpen — they return a modal proxy from
            // createDevicePopup and open AoTSensorLabel.openPopup directly.

            if (isOutput) {
                var baseDevId = (dev.device_unique_id || dev.id || '').split('::')[0];
                var durEl = document.getElementById('dur-' + (dev.id || dev.unique_id || ''));


                // Async fetch: live state + start epoch, then register stopwatch
                Promise.all([
                    fetch('/outputstate_unique_id/' + baseDevId + '/' + channel)
                        .then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
                    fetch('/output_started_at_public/' + baseDevId + '/' + channel)
                        .then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; })
                ]).then(function(results) {
                    var state = results[0];
                    var startData = results[1];
                    // Shared classifier: on/off/pending/fault consistent with v3.
                    var cls = window.AoTOutputState
                        ? window.AoTOutputState.classify(state)
                        : { isOn: (state === 'on' || (typeof state === 'number' && state > 0)),
                            isPending: (state === 'pending'), isFault: (state === 'fault'),
                            countsRuntime: (state === 'on' || (typeof state === 'number' && state > 0)) };
                    var liveON = (state !== null && state !== undefined) ? cls.isOn : isON;

                    // Prefer started_at_epoch; fall back to server-computed elapsed_sec
                    var startEpoch = null;
                    if (startData) {
                        if (startData.started_at_epoch) {
                            startEpoch = startData.started_at_epoch;
                        } else if (startData.elapsed_sec > 0 && startData.server_now_epoch) {
                            // Reconstruct start epoch using server clock to avoid client-clock skew
                            startEpoch = startData.server_now_epoch - startData.elapsed_sec;
                        }
                    }

                    var cb = document.getElementById(toggleId);
                    if (cb) {
                        cb.checked = liveON;
                        cb.classList.toggle('aot-toggle-pending', !!cls.isPending);
                        cb.classList.toggle('aot-toggle-fault', !!cls.isFault);
                    }
                    // Runtime counts only for a confirmed-on device (Model A): the
                    // stopwatch starts from the confirmed-on epoch. Pending/fault
                    // (offline) never start it — no fictional runtime.
                    if (durEl && window.AoTStopwatchManager) {
                        window.AoTStopwatchManager.register(
                            baseDevId, channel,
                            cls.countsRuntime, cls.countsRuntime ? startEpoch : null,
                            durEl, 7000, false
                        );
                    }
                });

                // Last Work Time (separate — no dependency on live state)
                setTimeout(function() {
                    var lastDurEl = document.getElementById('last-dur-' + (dev.id || dev.unique_id || ''));
                    if (lastDurEl) {
                        fetch('/output_last_duration_public/' + baseDevId + '/' + channel)
                            .then(function(r) { return r.json(); })
                            .then(function(d) {
                                if (d && d.last_duration_sec !== undefined && d.last_duration_sec !== null && lastDurEl) {
                                    var s = parseInt(d.last_duration_sec, 10);
                                    if (isNaN(s)) return;
                                    var h = Math.floor(s / 3600).toString().padStart(2, '0');
                                    var mm = Math.floor((s % 3600) / 60).toString().padStart(2, '0');
                                    var ss = (s % 60).toString().padStart(2, '0');
                                    lastDurEl.innerText = h + ':' + mm + ':' + ss;
                                }
                            }).catch(function() {});
                    }
                }, 50);
            }
        }

        popup.on('open', onOpen);
        return popup;
    }

    /**
     * Shared /api/geo/devices fetcher.
     * Multiple map widgets on one dashboard poll with identical params —
     * calls within the TTL window share a single network request instead of
     * each widget issuing its own.
     */
    const _geoDevicesCache = {};  // paramsString -> { ts, promise }
    const GEO_DEVICES_SHARE_TTL_MS = 5000;

    function fetchGeoDevicesShared(paramsString) {
        const now = Date.now();
        let entry = _geoDevicesCache[paramsString];
        if (!entry || (now - entry.ts) >= GEO_DEVICES_SHARE_TTL_MS) {
            const promise = fetch('/api/geo/devices?' + paramsString)
                .then(function(r) {
                    if (!r.ok) throw new Error('geo/devices HTTP ' + r.status);
                    return r.json();
                });
            entry = { ts: now, promise: promise };
            _geoDevicesCache[paramsString] = entry;
            // Don't cache failures — let the next caller retry
            promise.catch(function() {
                if (_geoDevicesCache[paramsString] === entry) delete _geoDevicesCache[paramsString];
            });
        }
        // Each caller gets its own copy — widgets mutate the response in place
        // (all_measurements_map merge etc.) and must not affect each other.
        return entry.promise.then(function(data) {
            try { return structuredClone(data); } catch (e) { return data; }
        });
    }

    /**
     * A widget can be on a hidden dashboard tab while its timers keep firing.
     * offsetParent is null when the container (or an ancestor) is display:none.
     */
    function _isWidgetVisible(instance) {
        try {
            const el = instance && instance.map && instance.map.getContainer();
            return !!(el && el.offsetParent !== null);
        } catch (e) { return true; }
    }

    /**
     * Fetch devices from /api/geo/devices and render markers.
     * Used when async_devices=true (default).
     */
    async function fetchAndRenderDevices(uniqueId, map, vars) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        const wOpts = (vars && vars.vars) || {};
        const mapUuid = wOpts.selected_map_uuid || wOpts.map_uuid || vars.contentMapUuid || '';
        const deviceIds = wOpts.map_device_ids || wOpts.device_ids || '';
        const includeAll = wOpts.include_all_devices === true || wOpts.include_all_devices === 'true';

        const params = new URLSearchParams();
        if (mapUuid) params.set('map_uuid', mapUuid);
        if (deviceIds) params.set('device_ids', deviceIds);
        params.set('include_all', String(includeAll));

        try {
            const data = await fetchGeoDevicesShared(params.toString());
            if (!data.ok) {
                return;
            }

            const devices = data.devices || [];
            // Merge measurements from API response into vars so popup can use them
            if (data.all_measurements_map) {
                wOpts.all_measurements_map = data.all_measurements_map;
            }

            if (devices.length > 0) {
                addDeviceMarkers(uniqueId, map, devices, vars.theme, vars);
                // [3-way Actuator] Immediately reflect initial state on geo-design
                // labels (parent_type=aot_device). Without this they wait one full
                // poll cycle before showing the position %.
                const instance = window.AoTWidgetInstances[uniqueId];
                if (instance) {
                    try { _updateGeoDesignDeviceLabels(instance, devices, vars.theme); } catch (e) {}
                }
            }
        } catch (e) {
        }
    }

    /**
     * Setup automatic refresh — re-fetches device data from API.
     */
    /**
     * Refresh device marker appearance (color, label text) without remove/re-add.
     * Called by setupRefresh. Positions never change → no flicker.
     */
    function refreshDeviceMarkersAppearance(uniqueId, devices, wOpts) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        const showDeviceLabels = wOpts.show_device_labels === true || wOpts.show_device_labels === 'true';
        const globalLabelSize = parseFloat(wOpts.global_label_size) || 1.0;
        const targetMap = wOpts.all_measurements_map || wOpts.measurements_map || {};
        const theme = (instance.vars && instance.vars.theme) || {};

        devices.forEach(function(dev) {
            const markerId = dev.unique_id || dev.id;
            const marker = instance.markers.get(markerId);
            if (!marker) return;

            let isON = dev.status === 'active' || dev.status === 'on' ||
                         dev.is_activated === true || dev.is_activated === 'true';
            const devType2 = dev.device_type || dev.type || '';
            const userColor = getUnifiedDeviceColor(devType2, dev, theme);
            const el = marker.getElement();

            // [3-way Actuator] Override "on" semantics: label ON only when MOTION is
            // happening (transient). Motion is detected via position changes between
            // polls (or a recent commandActuator call). At rest at any position, the
            // label renders in the off style — consistent with other outputs.
            if (dev.control_kind === 'value_3way') {
                const newPos = (typeof dev.position_pct === 'number') ? dev.position_pct : 0;
                const prevPos = (typeof marker._prevPosPct === 'number') ? marker._prevPosPct : newPos;
                if (Math.abs(newPos - prevPos) > 0.5) {
                    marker._motion_detected_ts = Date.now();
                }
                marker._prevPosPct = newPos;
                const motionTs = marker._motion_detected_ts || 0;
                const cmdTs = marker._pending_command || 0;
                const motionWindowMs = 7000; // ~one poll cycle + grace
                isON = (Date.now() - Math.max(motionTs, cmdTs)) < motionWindowMs;
            }

            if (showDeviceLabels) {
                // Update pill: measurement value + color
                const devIdKey = dev.device_id || dev.device_unique_id ||
                    (dev.unique_id ? dev.unique_id.split('::')[0] : (dev.id || '').split('::')[0]);
                const devMeas = targetMap[devIdKey] || [];
                let firstVal = '', unit = '';
                if (devMeas.length > 0) {
                    const m = devMeas.find(function(x) { return parseInt(x.channel) === parseInt(dev.channel_id); }) || devMeas[0];
                    if (m && m.last_value !== undefined && m.last_value !== null && m.last_value !== '') {
                        firstVal = String(m.last_value);
                        unit = (window.aotMapUnits && window.aotMapUnits[m.id]) ? window.aotMapUnits[m.id] : (m.unit || '');
                        if (unit === 'bearing') unit = '';
                    }
                }
                // [3-way Actuator] Live position % refresh for labels
                if (dev.control_kind === 'value_3way') {
                    const p = (typeof dev.position_pct === 'number') ? dev.position_pct : 0;
                    const dir = dev.motion_dir;
                    const arrow = (dir === 'open') ? '▲ ' : (dir === 'close') ? '▼ ' : '';
                    firstVal = arrow + Math.round(p);
                    unit = '%';
                    // Also sync open popup's position display + slider (if not focused)
                    const posDisp = document.getElementById('pos-disp-' + (dev.id || dev.unique_id || ''));
                    if (posDisp) posDisp.innerText = Math.round(p) + '%';
                    const slider = document.getElementById('pos-slider-' + (dev.id || dev.unique_id || ''));
                    if (slider && document.activeElement !== slider) {
                        const r2 = Math.round(p);
                        // Current value (dot + fill) — always synced to the server value
                        slider.dataset.current = r2;
                        slider.style.setProperty('--aot-current-pct', r2 + '%');
                        if (window.AoTMapPopup) window.AoTMapPopup.positionDots(slider.parentElement);
                        // Target value (thumb) — global cache > server current value (falls back to server value if no cache after settling)
                        const baseIdV = (dev.id || dev.unique_id || '').split('::')[0];
                        const globalTargetV = window._aotActuatorTargetPct && window._aotActuatorTargetPct[baseIdV] !== undefined
                            ? window._aotActuatorTargetPct[baseIdV] : null;
                        if (globalTargetV !== null) {
                            slider.value = globalTargetV;
                        } else {
                            const _cmdTs2 = marker._pending_command || 0;
                            const _motionTs2 = marker._motion_detected_ts || 0;
                            if ((Date.now() - Math.max(_cmdTs2, _motionTs2)) >= 7000) {
                                slider.value = r2;
                            }
                        }
                    }
                }
                const valEl = el.querySelector('.dev-value');
                const unitEl = el.querySelector('.dev-unit');
                const valGroup = el.querySelector('.dev-val-group');
                if (valEl && firstVal !== '') { valEl.textContent = firstVal; if (valGroup) valGroup.style.display = 'inline'; }
                else if (valGroup) valGroup.style.display = 'none';
                if (unitEl) unitEl.textContent = unit;

                const pillEl = el.querySelector('.marker-pill');
                if (pillEl) {
                    const shadowOn  = hexToRgba(userColor, 0.6);
                    const shadowOff = hexToRgba(userColor, 0.3);
                    if (isON) {
                        pillEl.style.backgroundColor = userColor;
                        pillEl.style.color = '#fff';
                        pillEl.style.border = '2px solid #fff';
                        pillEl.style.boxShadow = '0 4px 12px ' + shadowOn;
                    } else {
                        pillEl.style.backgroundColor = '#fff';
                        pillEl.style.color = userColor;
                        pillEl.style.border = '2px solid ' + userColor;
                        pillEl.style.boxShadow = '0 2px 5px ' + shadowOff;
                    }
                }
            } else {
                // Update dot color
                el.style.backgroundColor = isON ? userColor : '#fff';
                el.style.borderColor = userColor;
            }

            // --- Sync open popup: toggle button + stopwatch ---
            const devId2   = String(dev.id || dev.unique_id || '');
            const baseId2  = devId2.split('::')[0];
            const ch2      = (dev.channel_id && dev.channel_id !== 'undefined') ? dev.channel_id : 0;
            const isOutput2 = (devType2 === 'output' || devType2 === 'function');

            // 1. Update toggle checkbox (popup is open when element exists in DOM)
            var toggleEl = document.getElementById('toggle-' + devId2);
            if (toggleEl) {
                toggleEl.checked = isON;
            }

            // 2. Update stopwatch — only relevant for output/function devices
            if (isOutput2) {
                var durEl2 = document.getElementById('dur-' + devId2);
                if (durEl2 && window.AoTStopwatchManager) {
                    if (isON) {
                        // Device ON: register/update timer
                        var swKey2 = window.AoTStopwatchManager.register(
                            baseId2, ch2, true, null, durEl2, 7000, false
                        );
                        // Force immediate sync when:
                        //  - first observation (no cached state yet), or
                        //  - state just transitioned from OFF → ON
                        var prevState2 = instance._deviceStateCache && instance._deviceStateCache[devId2];
                        if (prevState2 !== true) {
                            window.AoTStopwatchManager.sync(swKey2);
                        }
                    } else {
                        // Device OFF: stop timer, reset display
                        window.AoTStopwatchManager.register(
                            baseId2, ch2, false, null, durEl2, 7000, false
                        );
                    }
                }
            }

            // Cache current ON/OFF state for next cycle comparison
            if (!instance._deviceStateCache) instance._deviceStateCache = {};
            instance._deviceStateCache[devId2] = isON;
        });

        // Update aot-devices shape opacity based on device on/off state
        // on: fill-opacity 0.9 / line-opacity 1.0
        // off: fill-opacity 0.2 / line-opacity 0.5
        _updateDeviceShapeOpacity(instance, devices);

        // Update geo-design aot_device label marker color/opacity based on device state
        _updateGeoDesignDeviceLabels(instance, devices, theme);
    }

    /**
     * Update geo-design label_aux markers that have aot_device parent type.
     * ON  → device theme color, full opacity.
     * OFF → dimmed grey, reduced opacity.
     * Called by refreshDeviceMarkersAppearance at every refresh cycle.
     */
    function _updateGeoDesignDeviceLabels(instance, devices, theme) {
        if (!instance.labelMarkers || !instance.labelMarkers.length) return;

        // Build lookup: base device_id → { isON, devType, controlKind, positionPct }
        // [3-way Actuator] For value_3way devices, treat "ON" as motion in progress
        // (position change since last poll). isActivated alone is position>0, which
        // is misleading for a resting actuator — at rest it should look like other
        // outputs in off state.
        const stateMap = {};
        devices.forEach(function(dev) {
            const devId = String(dev.device_id || (dev.unique_id ? dev.unique_id.split('::')[0] : '') || dev.id || '');
            if (!devId) return;
            const devType = dev.device_type || dev.type || '';
            const controlKind = dev.control_kind || 'on_off';
            const positionPct = (typeof dev.position_pct === 'number') ? dev.position_pct : null;

            let isON = dev.status === 'active' || dev.status === 'on' ||
                       dev.is_activated === true || dev.is_activated === 'true';

            if (controlKind === 'value_3way') {
                // Track motion per device on the instance state
                if (!instance._3wayState) instance._3wayState = {};
                const tracker = instance._3wayState[devId] || {};
                const prev = (typeof tracker.prevPos === 'number') ? tracker.prevPos : (positionPct || 0);
                const curr = (positionPct != null) ? positionPct : 0;
                if (Math.abs(curr - prev) > 0.5) {
                    tracker.motionTs = Date.now();
                }
                tracker.prevPos = curr;
                instance._3wayState[devId] = tracker;
                const motionTs = tracker.motionTs || 0;
                isON = (Date.now() - motionTs) < 7000;
            }

            stateMap[devId] = {
                isON: isON,
                devType: devType,
                controlKind: controlKind,
                positionPct: positionPct,
            };
        });

        instance.labelMarkers.forEach(function(marker) {
            const el = marker.getElement();
            if (!el || el.dataset.parentType !== 'aot_device') return;
            const parentId = el.dataset.parentId || '';
            if (!parentId) return;
            const state = stateMap[parentId];
            if (!state) return;

            if (state.isON) {
                const color = getUnifiedDeviceColor(state.devType, {}, theme || {});
                el.style.backgroundColor = color;
                el.style.opacity = '1';
            } else {
                el.style.backgroundColor = '#999';
                el.style.opacity = '0.55';
            }

            // [3-way Actuator] Update the position % suffix beside the device name.
            const pctEl = el.querySelector('.aot-3way-pct');
            if (pctEl) {
                if (state.controlKind === 'value_3way' && state.positionPct != null) {
                    pctEl.textContent = ' ' + Math.round(state.positionPct) + '%';
                    pctEl.style.display = 'inline';
                } else {
                    pctEl.style.display = 'none';
                }
            }
        });
    }

    function _updateDeviceShapeOpacity(instance, devices) {
        const map = instance && instance.map;
        if (!map || !map.getLayer('aot-devices-fill')) return;

        // Base opacity: use device_shape_opacity widget setting (0–100 → 0.0–1.0), default 0.5
        const wOpts = (instance.vars && instance.vars.vars) || {};
        const baseOp = (wOpts.device_shape_opacity !== undefined && wOpts.device_shape_opacity !== '')
            ? Math.max(0, Math.min(1, parseInt(wOpts.device_shape_opacity) / 100))
            : 0.5;

        // Only OUTPUT type devices have a meaningful ON/OFF runtime state.
        // Input sensors are "activated" (is_activated=true) whenever enabled in DB,
        // which is NOT the same as "currently operating" — their shapes must use base opacity.
        const onIds = [];
        devices.forEach(function(dev) {
            const devType = (dev.device_type || dev.type || '').toLowerCase();
            if (devType !== 'output') return;
            const isON = dev.status === 'active' || dev.status === 'on' ||
                         dev.is_activated === true || dev.is_activated === 'true';
            if (isON) {
                const devId = String(dev.device_id || (dev.unique_id ? dev.unique_id.split('::')[0] : '') || dev.id || '');
                if (devId) onIds.push(devId);
            }
        });

        try {
            if (onIds.length > 0) {
                // ON output device_ids → 0.9 opacity, all others → base opacity
                const fillExpr = ['match', ['get', 'device_id'], onIds, 0.9, baseOp];
                const lineExpr = ['match', ['get', 'device_id'], onIds, 1.0, Math.min(1, baseOp + 0.2)];
                map.setPaintProperty('aot-devices-fill', 'fill-opacity', fillExpr);
                if (map.getLayer('aot-devices-line')) {
                    map.setPaintProperty('aot-devices-line', 'line-opacity', lineExpr);
                }
            } else {
                map.setPaintProperty('aot-devices-fill', 'fill-opacity', baseOp);
                if (map.getLayer('aot-devices-line')) {
                    map.setPaintProperty('aot-devices-line', 'line-opacity', Math.min(1, baseOp + 0.2));
                }
            }
        } catch (e) {
        }
    }

    /**
     * Force-reload a raster tile source by cycling the tile URL with a cache-busting
     * timestamp. Removes and re-adds the MapLibre source so new tiles are fetched.
     */
    function _reloadTileSource(map, sourceId, originalTiles, tileSize, layerIds) {
        if (!map || !map.getSource(sourceId)) return;
        const ts = Math.floor(Date.now() / 1000);
        const sep = originalTiles[0].indexOf('?') !== -1 ? '&' : '?';
        const bustedTiles = originalTiles.map(function(u) { return u + sep + '_ts=' + ts; });

        // setTiles() keeps the source/layer objects alive and only reloads tiles.
        // The remove/add fallback below destroys and recreates the source every
        // cycle (full tile refetch, layer z-order pop, internal object churn).
        const src = map.getSource(sourceId);
        if (src && typeof src.setTiles === 'function') {
            try {
                src.setTiles(bustedTiles);
                return;
            } catch (e) {}
        }

        layerIds.forEach(function(id) {
            try { if (map.getLayer(id)) map.removeLayer(id); } catch (e) {}
        });
        try { map.removeSource(sourceId); } catch (e) {}
        try {
            map.addSource(sourceId, { type: 'raster', tiles: bustedTiles, tileSize: tileSize });
            layerIds.forEach(function(id) {
                try { map.addLayer({ id: id, type: 'raster', source: sourceId, layout: { visibility: 'visible' } }); } catch (e) {}
            });
        } catch (e) {}
    }

    function setupRefresh(uniqueId, intervalSeconds) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        if (instance.refreshTimer) {
            clearInterval(instance.refreshTimer);
        }

        instance.refreshTimer = setInterval(function() {
            if (document.hidden) return;
            if (!_isWidgetVisible(instance)) return;
            const vars = instance.vars;
            const map = instance.map;
            if (!vars || !map) return;

            const wOpts = (vars && vars.vars) || {};
            const mapUuid = wOpts.selected_map_uuid || wOpts.map_uuid || vars.contentMapUuid || '';
            const deviceIds = wOpts.map_device_ids || wOpts.device_ids || '';
            const includeAll = wOpts.include_all_devices === true || wOpts.include_all_devices === 'true';

            const params = new URLSearchParams();
            if (mapUuid) params.set('map_uuid', mapUuid);
            if (deviceIds) params.set('device_ids', deviceIds);
            params.set('include_all', String(includeAll));

            fetchGeoDevicesShared(params.toString())
                .then(function(data) {
                    if (!data.ok) return;
                    const devices = data.devices || [];
                    if (data.all_measurements_map) wOpts.all_measurements_map = data.all_measurements_map;
                    // Update appearance only — no remove/re-add to prevent position flicker
                    if (devices.length > 0) {
                        refreshDeviceMarkersAppearance(uniqueId, devices, wOpts);
                    }
                })
                .catch(function(e) { })
        }, intervalSeconds * 1000);
    }

    /**
     * Clean up widget instance
     */
    window.destroyAoTMapVectorWidget = function(uniqueId) {
        const instance = window.AoTWidgetInstances?.[uniqueId];
        if (!instance) return;

        // Clear refresh timers
        if (_actPollTimers[uniqueId]) {
            clearInterval(_actPollTimers[uniqueId]);
            delete _actPollTimers[uniqueId];
        }
        if (instance.layerRefreshTimers) {
            Object.values(instance.layerRefreshTimers).forEach(function(t) { clearInterval(t); });
            instance.layerRefreshTimers = {};
        }
        if (instance._rvVisHandler) {
            document.removeEventListener('visibilitychange', instance._rvVisHandler);
            instance._rvVisHandler = null;
        }
        if (instance.refreshTimer) {
            clearInterval(instance.refreshTimer);
        }
        if (instance.panelRefreshTimer) {
            clearInterval(instance.panelRefreshTimer);
        }
        // Detach sensor labels
        if (window.AoTMapSensorLabels) {
            try { AoTMapSensorLabels.detach(uniqueId); } catch (e) {}
        }

        // Remove all markers
        for (const marker of instance.markers.values()) {
            marker.remove();
        }

        // Remove unified collision handler
        if (instance._unifiedCollisionHandler && instance.map) {
            instance.map.off('moveend', instance._unifiedCollisionHandler);
            instance.map.off('zoomend', instance._unifiedCollisionHandler);
            instance._unifiedCollisionHandler = null;
        }

        // Remove geo/design label markers and cluster badges
        [
            'labelMarkers', 'siteZoneLabelMarkers', 'geoDeviceLabelMarkers',
            'labelClusterMarkers', 'siteZoneClusterMarkers', 'geoDeviceClusterMarkers',
            'deviceLabelMarkers', 'deviceClusterMarkers', 'absorbBadges'
        ].forEach(function(key) {
            if (instance[key]) {
                instance[key].forEach(function(m) { try { m.remove(); } catch (e) {} });
                instance[key] = [];
            }
        });

        // Tear down restored UI
        if (instance.measurementPanel && typeof instance.measurementPanel.destroy === 'function') {
            try { instance.measurementPanel.destroy(); } catch (e) {}
        }
        if (instance.legendEl && instance.legendEl.parentNode) {
            instance.legendEl.parentNode.removeChild(instance.legendEl);
        }
        if (instance.toolbarLeft && instance.toolbarLeft.parentNode) {
            instance.toolbarLeft.parentNode.removeChild(instance.toolbarLeft);
        }
        if (instance.notePollTimer) {
            clearInterval(instance.notePollTimer);
            instance.notePollTimer = null;
        }
        if (instance.noteMarkers) {
            instance.noteMarkers.forEach(function(m) { try { m.remove(); } catch (e) {} });
            instance.noteMarkers.clear();
        }
        if (instance.layerPanelContainer && instance.layerPanelContainer.parentNode) {
            instance.layerPanelContainer.parentNode.removeChild(instance.layerPanelContainer);
        }

        // Drop label layer registry
        if (window.AoTMapLabelLayers) {
            try { window.AoTMapLabelLayers.clear(uniqueId); } catch (e) {}
        }

        // Remove map
        if (instance.map) {
            instance.map.remove();
        }

        delete window.AoTWidgetInstances[uniqueId];
    };


})();
