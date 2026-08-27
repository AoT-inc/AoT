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
    // `.aot-type-hidden` 을 한 번 심는다 — 위젯 템플릿(파이썬)이 캐시돼 옛 CSS 를
    // 내보내도 토글이 듣게 하려는 보험이다.
    //
    // ⚠ **위젯 템플릿의 같은 규칙과 글자 그대로 같아야 한다**(`AoT_map.py`).
    // 규칙을 두 벌 두면 갈라지고, 갈라지면 **나중에 심긴 쪽이 이긴다** — 여기서
    // 실제로 겪었다: 템플릿 쪽에 `:not(.aot-focus-show)` 를 붙였는데 이 줄이
    // 옛 형태로 남아, 임시 표시가 라벨 종류 하나(값 키 원형)에서만 안 듣는 것도
    // 아니고 `.aot-type-hidden` 계열 **전부**에서 안 들었다. 화면에는 "모달을
    // 열어도 꺼 둔 라벨이 안 나온다" 로만 보인다.
    if (!document.getElementById('aot-type-hidden-style')) {
        var _styleEl = document.createElement('style');
        _styleEl.id = 'aot-type-hidden-style';
        _styleEl.textContent =
            '.aot-type-hidden:not(.aot-focus-show) { display: none !important; }';
        document.head.appendChild(_styleEl);
    }

    // ── 타일 메모리 캐시 정원 (데스크탑 전용) ─────────────────────────────────
    // MapLibre 4.1.2 는 화면 밖 타일 캐시의 크기를 뷰포트에서 계산한다
    // (`SourceCache.updateCacheSize`, 벤더 번들에서 확인):
    //
    //   cacheMax = floor( (ceil(W/tileSize)+1) × (ceil(H/tileSize)+1) × Z )
    //            = (한 화면분 타일 수) × Z          Z = maxTileCacheZoomLevels (기본 5)
    //
    // 즉 기본값은 "화면 5장분"이다. `maxTileCacheSize` 는 이 값을 **올리지 못한다**
    // — `Math.min` 으로 걸리는 상한일 뿐이라 정원을 키우는 손잡이는 Z 하나다.
    //
    // **실측(2026-08-13, 로컬 · 800×400 지도 · zoom 11 · 256px 타일):**
    //   Z=기본(5)  → cacheMax 75,  화면 안 12장
    //   Z=20       → cacheMax 300  (공식대로 15 × Z)
    //   가로 800×400 → 세로 400×800 회전: 신규 3장, 화면 밖 캐시로 3장 이동
    //   다시 가로로 회전:            **재요청 0건** (전부 메모리 캐시 적중)
    //
    // 그래서 **회전만 놓고 보면 이 손잡이는 아무것도 하지 않는다** — 기본값이 이미
    // 화면 5장분을 들고 있고 회전이 밀어내는 것은 한 화면분에도 한참 못 미친다.
    // 회전 비용은 프록시 캐시(`utils_http.tile_conditional`)가 없앤 것이지 여기가 아니다.
    // 이 값이 실제로 듣는 곳은 **줌 왕복과 넓은 팬** — 화면 5장분을 넘겨 훑고
    // 돌아오는 경우다. 그때조차 프록시 캐시가 생긴 뒤로는 재요청이 왕복이 아니라
    // 브라우저 디스크 캐시(실측 2ms / 0바이트) + 디코드 비용이므로, 아끼는 것은
    // 네트워크가 아니라 디코드다. 그래서 2배(10)로만 올린다.
    //
    // **모바일에서 켜지 않는 이유**: 보관되는 타일은 256×256 RGBA 텍스처 한 장당
    // 약 256KB 다. 정원을 2배로 하면 상한도 2배가 된다 — 지도 위젯 하나(800×500)
    // 기준 75장 19MB → 150장 38MB. 폰에서 그만큼을 얻자고 쓰기에는 비싸고,
    // 폰이야말로 이 프로젝트가 발열·메모리를 아끼려고 애쓰는 쪽이다.
    var _DESKTOP_TILE_CACHE_ZOOM_LEVELS = 10;

    /**
     * 데스크탑급 기기인가.
     *
     * **화면 회전으로 뒤집히지 않는 신호만 쓴다.** 뷰포트 폭(`innerWidth <= 768`)
     * 으로 가르면 폰을 가로로 눕히는 순간(예: 844×390) 데스크탑으로 분류된다 —
     * 정확히 이 값이 없어야 할 상황에서 켜지는 셈이다. 그래서
     *   - `pointer: coarse` / `hover: none` : 터치가 주 입력 → 폰·태블릿
     *   - `max(screen.width, screen.height)`: 방향과 무관한 화면 긴 변
     *   - `navigator.deviceMemory`          : 저사양 기기 제외
     * 셋을 본다. 판정 불가면 **모바일로 본다**(안전한 쪽 = 기본값 유지).
     */
    function _isDesktopClass() {
        try {
            var mm = window.matchMedia;
            if (mm && (mm('(pointer: coarse)').matches || mm('(hover: none)').matches)) {
                return false;
            }
            var longEdge = Math.max(window.screen && window.screen.width || 0,
                                    window.screen && window.screen.height || 0);
            if (!longEdge || longEdge <= 1024) return false;
            var mem = navigator.deviceMemory;
            if (typeof mem === 'number' && mem <= 2) return false;
            return true;
        } catch (e) {
            return false;
        }
    }

    /**
     * **스마트폰인가.** `_isDesktopClass()` 는 "데스크탑급인가" 라 태블릿도 false 인데,
     * 모달 시트는 폰에서만 쓴다 — 태블릿은 화면이 넓어 옆에 도킹하는 편이 낫다.
     *
     * 회전에 흔들리지 않는 신호만 본다: 포인터가 거친가(마우스가 없는가)와 **물리
     * 화면의 짧은 변**. 폰은 360~430, 태블릿은 768 이상이다. 뷰포트 폭으로 재면
     * 폰을 눕히는 순간 태블릿이 되고, 데스크탑 창을 좁히면 폰이 된다.
     */
    function _isPhoneClass() {
        try {
            var mm = window.matchMedia;
            var coarse = mm && (mm('(pointer: coarse)').matches || mm('(hover: none)').matches);
            if (!coarse) return false;
            var shortEdge = Math.min(window.screen && window.screen.width || 0,
                                     window.screen && window.screen.height || 0);
            if (!shortEdge) return false;
            return shortEdge <= 500;
        } catch (e) { return false; }
    }

    /**
     * **지금 눕혀져 있는가.** `_isPhoneClass()` 는 기기 종류라 회전에 흔들리지
     * 않아야 하지만, 이쪽은 반대로 **회전할 때마다 답이 달라져야 한다** — 그래서
     * 물리 화면이 아니라 뷰포트를 본다.
     */
    function _isLandscape() {
        try {
            var mm = window.matchMedia;
            if (mm && mm('(orientation: landscape)').media !== 'not all') {
                return mm('(orientation: landscape)').matches;
            }
            return window.innerWidth > window.innerHeight;
        } catch (e) {
            return window.innerWidth > window.innerHeight;
        }
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

        const mapOptions = {
            container: canvasId,
            style: baseStyleUrl,
            center: [defaultLng, defaultLat],
            zoom: defaultZoom,
            maxZoom: maxZoom,
            pitch: defaultPitch,
            bearing: defaultBearing,
            attributionControl: false
        };
        // 데스크탑에서만 화면 밖 타일 캐시를 넓힌다 (근거·실측은 파일 상단
        // _DESKTOP_TILE_CACHE_ZOOM_LEVELS 주석). 폰·태블릿은 기본값(5) 그대로 —
        // 정원을 넓히면 보관 텍스처 메모리 상한이 그대로 따라 오른다.
        // 이 옵션은 SourceCache 가 만들어질 때 map 에서 읽어가므로(onAdd) 생성
        // 시점에 넣어야 한다. 나중에 map._maxTileCacheZoomLevels 를 바꿔도 이미
        // 붙은 소스에는 반영되지 않는다.
        if (_isDesktopClass()) {
            mapOptions.maxTileCacheZoomLevels = _DESKTOP_TILE_CACHE_ZOOM_LEVELS;
        }

        const map = new maplibregl.Map(mapOptions);

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

        // The native corner credit is hidden unconditionally in CSS —
        // addLayerPanel always builds our own styled ⓘ button + panel instead,
        // whether or not the rest of the tool rail is showing (hideControls
        // only hides the FUNCTIONAL controls; the credit is a licence
        // requirement, not a control, and stays visible on its own either way).
        // Nothing to set here anymore; see .aot-attrib-native-fallback below
        // for the emergency escape hatch if that panel is never built.

        // Add attribution control
        map.addControl(new maplibregl.AttributionControl({
            compact: true,
            position: 'bottom-left'
        }), 'bottom-left');

        // compact:true only means "render the ⓘ toggle" — MapLibre v4 adds
        // maplibregl-compact AND maplibregl-compact-show together, so the credit
        // starts EXPANDED (measured 134–295px wide) and only collapses once the
        // user taps ⓘ. On a phone-width widget that band runs straight into the
        // bottom-right legend. Start collapsed instead: the ⓘ stays visible and
        // one tap still reveals the full credit.
        // This control is kept in the DOM but hidden (see map.css): it stays the
        // authority on which sources are actually being rendered, and the tool
        // rail's copyright panel (addLayerPanel) mirrors its text. The credit is
        // still shown without requiring interaction — that panel opens on its
        // own — which is what the OSMF guidelines require. Never make hiding it
        // the end state: something visible must always carry the credit.

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

        // 직전 세션에서 본 측정값을 먼저 심는다 — Input 키가 첫 렌더부터 값을
        // 갖고 그려지고, 실제 조회가 끝나면 조용히 교체된다. 마커 생성보다
        // 반드시 앞이어야 한다(_deviceChannels 가 이 캐시를 읽는다).
        try { _seedMeasValueCache(uniqueId, vars); } catch (e) {}

        // 줌 게이트: 축척이 낮으면 장치 단위 라벨/키를 감춘다(LABEL_MIN_ZOOM).
        // 라벨 렌더러보다 먼저 걸어 둬야 첫 렌더부터 기준이 적용된다.
        try { _installZoomGate(instance, map, uniqueId); } catch (e) {}

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

            // 식생 구획(작기). GeoShape 가 아니라 별도 테이블이라 아래 오버레이
            // 로더를 타지 않는다 — 자기 API(/api/geo/plots)로 따로 온다.
            //
            // **await 하지 않는다.** 아래 로더들이 느리거나 하나가 걸리면 식생까지
            // 함께 멈추기 때문이다(실제로 그 자리에 두었더니 레이어가 아예 안
            // 올라왔다). fetch 왕복이 있어 실제 추가는 대개 도형 뒤가 된다.
            try {
                if (window.AoTMapPlot) {
                    const _vegOpts = (vars && vars.vars) || {};
                    const _vegMapUuid = _vegOpts.selected_map_uuid ||
                                        _vegOpts.map_uuid ||
                                        (vars && vars.contentMapUuid) || '';
                    // 옛 키(show_vegetation)도 읽는다 — 새 키만 보면 일부러 꺼 둔
                    // 사람의 레이어가 업그레이드에서 조용히 다시 켜진다.
                    const _vegOpt = (_vegOpts.show_plots !== undefined)
                        ? _vegOpts.show_plots : _vegOpts.show_vegetation;
                    window.AoTMapPlot.load(uniqueId, map, {
                        mapUuid: _vegMapUuid,
                        shell: _showFacilityCenterOverlay,
                        facilityCentric: !!_vegOpts.label_priority_facility,
                        labelSizeEm: _vegOpts.global_label_size,
                        visible: !(_vegOpt === false || _vegOpt === 'false'),
                        // 구역·시설과 같은 옵션을 식생 모달도 따른다(탭 세 키가
                        // 같아 매핑이 없다).
                        defaultTab: _vegOpts.popup_default_tab,
                        // [환경·제어] 배선은 위젯이 빌려준다 — shell 과 같은
                        // 이음매다(_attachPlotControl 주석 참조). 등록소를
                        // 거치는 이유는 그 함수가 아직 정의되기 전이기 때문이다.
                        attachControl: function (uid, popup, body, plotUuid) {
                            const fn = _plotControlHooks[uid];
                            if (fn) fn(uid, popup, body, plotUuid);
                        },
                        // 뒤로가기 — 상세가 오는 즉시. `/contents` 를 기다리면
                        // 창이 다 그려진 뒤에도 화살표만 한참 늦게 나타난다.
                        wireUp: function (uid, body, plot) {
                            const fn = _plotUpHooks[uid];
                            if (fn) fn(body, plot);
                        },
                        // 연 구획으로 지도를 옮긴다. 구획 도형은 응답의 feature 에
                        // 실려 오므로(구획 소스는 AoTMapPlot 이 직접 붙인다) 그것을
                        // 먼저 쓰고, 없으면 uuid 로 지도 소스를 뒤진다.
                        focus: function (plot) {
                            const g = plot && plot.feature && plot.feature.geometry;
                            _focusMapOn(uniqueId, g ? { geometry: g }
                                                    : (plot && plot.unique_id));
                        }
                    });
                }
            } catch (e) {
                console.warn('[AoT Map] 식생 레이어 초기화 실패:', e);
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
            try { addTimeDock(uniqueId, map, vars); } catch (e) {
                console.warn('[AoT Map] addTimeDock failed:', e);
            }

            // Expose live-refresh hooks for the settings-drawer's auto-save
            // (dashboard-widget-live-preview.js) — Device Filter and Measurement
            // Panel selects used to only take effect after the full Save button
            // (page reload); this lets them auto-save + apply immediately like
            // every other option.
            try {
                var _instRefresh = window.AoTWidgetInstances[uniqueId];
                if (_instRefresh) {
                    _instRefresh._fetchAndRenderDevices = function () {
                        return fetchAndRenderDevices(uniqueId, map, vars);
                    };
                    // measurements_map has no "update items" API on the panel handle
                    // (items are fixed at construction — see createMeasurementPanel in
                    // aot-map-custom-controls.js), so a selection change tears the
                    // existing panel down (DOM node + its interval + ResizeObserver)
                    // and rebuilds it, rather than trying to patch it in place.
                    // 시간 독은 켜고 끄는 토글 하나뿐이라 통째로 다시 만든다
                    // (addTimeDock 이 먼저 이전 것을 걷어낸다).
                    _instRefresh._refreshTimeDock = function () {
                        try { addTimeDock(uniqueId, map, vars); } catch (eTime) {}
                    };
                    _instRefresh._refreshMeasurementPanel = function (newMeasurementsMap) {
                        var iv = (vars && vars.vars) || {};
                        iv.measurements_map = newMeasurementsMap || {};
                        var inst = window.AoTWidgetInstances[uniqueId];
                        if (!inst) return;
                        if (inst.panelRefreshTimer) { clearInterval(inst.panelRefreshTimer); inst.panelRefreshTimer = null; }
                        if (inst._dockResizeObserver) {
                            try { inst._dockResizeObserver.disconnect(); } catch (eDisc) {}
                            inst._dockResizeObserver = null;
                        }
                        if (inst.measurementPanel && inst.measurementPanel.panel && inst.measurementPanel.panel.parentNode) {
                            inst.measurementPanel.panel.parentNode.removeChild(inst.measurementPanel.panel);
                        }
                        inst.measurementPanel = null;
                        try { addMeasurementPanel(uniqueId, map, vars); } catch (eRebuild) {}
                    };
                }
            } catch (e) {}

            // Layer panel (top-right unified toolbar: Layers + Measure + Note).
            // Must come before addLegendOverlay so legend can reference the layer panel's update hook.
            try { addLayerPanel(uniqueId, map, vars); } catch (e) {
                console.warn('[AoT Map] addLayerPanel failed:', e);
            }
            // Attribution safety net: the corner control is hidden on the
            // promise that addLayerPanel built our own credit panel instead.
            // If that never happened (addLayerPanel threw before reaching it),
            // give the corner control back — a map must never render without
            // its attribution.
            try {
                const _mc = map.getContainer();
                if (!_mc.querySelector('.aot-map-attrib-panel')) {
                    _mc.classList.add('aot-attrib-native-fallback');
                }
            } catch (e) {}
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

        // Persist view state (center, zoom, pitch, bearing) after user interaction.
        //
        // ⚠ **사용자가 움직였을 때만 쓴다.** `moveend` 는 지도가 처음 자기
        // 위치로 잡을 때도 발화하므로, 그대로 두면 대시보드를 열기만 해도 지도
        // 위젯 수만큼 POST 가 나간다(김제 대시보드 실측 3회 — 사용자는 아무것도
        // 하지 않았고, 저장되는 값은 방금 읽어온 값 그대로다). 라즈베리파이처럼
        // 워커가 하나인 서버에서는 그 쓰기가 같은 순간의 읽기와 경합한다.
        //
        // 판정은 **저장될 값이 실제로 달라졌는가**로 한다. `originalEvent` 유무로
        // 사람/코드를 가르는 방법도 있지만, 확대·축소 버튼은 `map.zoomIn()` 을
        // 부르는 프로그램 이동이라 그 방식은 버튼으로 바꾼 뷰를 저장하지 않는다.
        // 첫 정착값을 기준선으로 잡아 두고 그와 다를 때만 보내면, 무엇이 지도를
        // 움직였든 "바뀐 것만 저장" 이 된다.
        let _viewSaveTimer;
        let _lastViewPayload = null;
        map.on('moveend', function() {
            clearTimeout(_viewSaveTimer);
            _viewSaveTimer = setTimeout(function() {
                const widgetId = (vars && vars.widgetId) || uniqueId;
                const center = map.getCenter();
                const options = {
                    fallback_latitude:  center.lat.toFixed(6),
                    fallback_longitude: center.lng.toFixed(6),
                    default_zoom:       map.getZoom().toFixed(2),
                    default_pitch:      Math.round(map.getPitch()),
                    default_bearing:    Math.round(map.getBearing())
                };
                const payload = JSON.stringify(options);
                // 첫 발화 = 지도가 자기 초기 위치로 잡은 것. 기준선으로만 삼고
                // 저장하지 않는다 — 여기서 보내면 대시보드를 열기만 해도 지도
                // 위젯 수만큼 쓰기가 나간다(실측 3회, 값은 방금 읽은 것 그대로).
                if (_lastViewPayload === null) { _lastViewPayload = payload; return; }
                if (payload === _lastViewPayload) return;   // 되돌아온 경우
                _lastViewPayload = payload;
                fetch('/save_widget_custom_options', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ widget_id: widgetId, options: options })
                }).catch(function(e) { })
            }, 1000);
        });

        // Refresh handler
        if (vars.refreshSeconds > 0) {
            setupRefresh(uniqueId, vars.refreshSeconds);
        }
        // 출력 상태는 위젯 갱신 주기가 아니라 '출력 상태 갱신 주기' 를 따른다.
        // 목록 재조회(무겁다)와 분리된 가벼운 폴러다.
        setupOutputStateRefresh(uniqueId, wOpts.output_update_interval);
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
    // ── 모달 응답도 공유 캐시를 탄다 ──────────────────────────────────────────
    //
    // 지도 레이어는 이미 AoTGeoData(파싱된 JSON 캐시 + 동시요청 합치기)를 쓰고
    // 시설 모달은 AoTFacilityRuntime 을 쓴다. 필지·구역·장치 모달만 매번 생
    // fetch 였다 — 콜드 실측 필지 요약 980ms, 구역 내용 280ms(구역은 서버
    // 캐시도 없어 **열 때마다** 그 값이었다).
    //
    // 같은 통로로 옮기면 세 가지가 함께 온다: TTL 안의 재요청은 왕복 없음,
    // 동시 요청 합치기(라벨 폴링과 클릭이 겹쳐도 한 번), 그리고 **호버 예열**.
    // 식생 모달에 [환경·제어]를 붙여 주는 함수의 위젯별 등록소.
    //
    // 그 함수는 `loadGeoJSONLayers` 안(구역 모달 기계가 사는 곳)에 정의되는데,
    // 식생 로더는 `initAoTMapVectorWidget` 에서 **그보다 먼저** 호출된다 —
    // 이름을 직접 참조하면 다른 스코프라 ReferenceError 가 나고, 그 자리의
    // try/catch 가 삼켜 **식생 레이어가 통째로 안 뜬다**(실제로 그렇게 됐다).
    // 그래서 늦게 찾아 쓴다.
    var _plotControlHooks = {};
    // 구획 모달의 **뒤로가기 배선**. 제어 배선과 따로 두는 이유는 시점이
    // 다르기 때문이다 — 상위가 누구인지는 구획 상세(`/api/geo/plot/<uuid>`)에
    // 이미 들어 있고, 제어는 그보다 훨씬 무거운 `/contents` 를 기다린다.
    var _plotUpHooks = {};

    function _modalUrl(kind, uuid, channel) {
        if (!uuid) return null;
        if (kind === 'site')  return '/api/geo/site/'  + encodeURIComponent(uuid) + '/summary';
        if (kind === 'zone')  return '/api/geo/zone/'  + encodeURIComponent(uuid) + '/contents';
        if (kind === 'facility') {
            return '/api/aot/facility/' + encodeURIComponent(uuid) + '/overview';
        }
        if (kind === 'device') {
            return '/api/geo/device/' + encodeURIComponent(uuid) + '/detail?channel=' +
                   encodeURIComponent(channel == null ? 0 : channel);
        }
        return null;
    }

    function modalFetch(kind, uuid, channel) {
        var u = _modalUrl(kind, uuid, channel);
        if (!u) return Promise.resolve({ ok: false, json: function () { return Promise.resolve(null); } });
        return geoFetch(u);
    }

    // 라벨에 마우스가 닿는 순간 미리 받아 둔다. 올려놓고 누르기까지 보통
    // 200~500ms 가 있고, 그 사이에 왕복이 끝나면 창은 값이 채워진 채로 열린다.
    function warmModal(kind, uuid, channel) {
        var u = _modalUrl(kind, uuid, channel);
        if (u && window.AoTGeoData) window.AoTGeoData.prefetch([u]);
    }

    // 쓰기 직후의 재조회는 캐시를 타면 안 된다(방금 올린 사진이 안 보인다).
    function invalidateModal(kind, uuid, channel) {
        var u = _modalUrl(kind, uuid, channel);
        if (u && window.AoTGeoData) window.AoTGeoData.invalidate(u);
    }

    // 예열은 지도가 다 그려진 뒤 한가할 때. 로드 순간에 끼워 넣으면 정작
    // 타일·라벨이 밀린다(저사양 호스트에서 스레드풀을 함께 쓴다).
    function _whenIdle(fn, delayMs) {
        var run = function () { try { fn(); } catch (e) {} };
        if (window.requestIdleCallback) {
            setTimeout(function () { requestIdleCallback(run, { timeout: 4000 }); },
                       delayMs || 0);
        } else {
            setTimeout(run, (delayMs || 0) + 500);
        }
    }

    function prefetchGeoLayers(wOpts, mapUuid, labelMapUuid) {
        function on(key) { const v = wOpts[key]; return v === true || v === 'true' || v === 1; }
        const urls = [];
        if (on('show_site_shape')) urls.push('/api/geo/sites?format=geojson' + (mapUuid ? '&map_uuid=' + encodeURIComponent(mapUuid) : ''));
        if (on('show_zone_shape')) urls.push('/api/geo/zones?format=geojson' + (mapUuid ? '&map_uuid=' + encodeURIComponent(mapUuid) : ''));
        // Labels (label_aux markers) — loadGeoDesignLabels keys off vars.contentMapUuid,
        // which may differ from the shape mapUuid; prefetch so labels render early too.
        if (labelMapUuid && (on('show_site_label') || on('show_zone_label') || on('show_device_labels'))) {
            urls.push('/api/geo/overlays?map_uuid=' + encodeURIComponent(labelMapUuid) + '&type=label_aux');
        }
        if (mapUuid) {
            const mu = encodeURIComponent(mapUuid);
            // Matches loadGeoJSONLayers' _ensureFacilityShapeLayer gate: facility
            // 3D data feeds Facility/Sensor Values labels too, not just the shape.
            if (on('show_facility_shape') || on('show_labels')) {
                urls.push('/api/geo/overlays?map_uuid=' + mu + '&type=facility');
                // 3D 스택 존재 여부로 걸지 않는다 — 이제 지연 로드라 이 시점에는
                // 아직 없는 것이 정상이고, 이 목록이야말로 3D 를 받을지 말지를
                // 정하는 근거다(_ensureFacilityShapeLayer 가 같은 URL 을 쓴다).
                urls.push('/api/geo/facility/list?geo_id=' + mu);
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

    // 장치 상세 모달 진입점 다리.
    // 모달을 여는 함수(_openDeviceModal)는 loadGeoJSONLayers 안에 있고, 마커
    // 팝업을 만드는 createDevicePopup 은 그 바깥 형제 함수다 — 서로 스코프가
    // 닿지 않는다. 팝업 HTML 을 만드는 쪽이 모달을 열 수 있도록 여기 참조를
    // 남긴다(_showFacilityCenterOverlay 처럼 바깥에 두는 것이 더 깔끔하지만,
    // 모달이 구역·시설 모달과 같은 상태 객체·헬퍼를 공유해서 함께 둔다).
    var _deviceModalOpener = null;

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
            return _sensorLabelOptsFrom(((_vars && _vars.vars) || wOpts) || {}, uniqueId);
        }

        // Expose a live re-attach for the sensor-label settings (style/size/colors/
        // decimals/offset/opacity/popup + the collision/spacing/priority options
        // _sensorLabelOpts also reads). AoTMapSensorLabels.attach() already calls
        // detach() first internally, so re-attaching with fresh opts is idempotent —
        // no separate teardown needed here. The caller (settings-modal live-apply)
        // updates `inst.vars.vars[key]` before invoking this; `vars` here is the same
        // object reference as `inst.vars`, so _sensorLabelOpts(vars) immediately picks
        // up the change. No-ops safely if this map has no 3D facilities cached.
        try {
            var _slInst = window.AoTWidgetInstances[uniqueId];
            if (_slInst) {
                _slInst._reattachSensorLabels = function () {
                    if (!window.AoTMapSensorLabels) { return; }
                    var _o = _sensorLabelOpts(vars);
                    // 시설 밖(구역/맨지도)에 배치된 Input 값 키는 별도 마커라
                    // attach() 재실행 대상이 아니다 — 같은 옵션으로 제자리
                    // 재스타일링해 준다. 이게 없으면 시설 센서 라벨만 크기가
                    // 바뀌고 Input 키는 옛 크기로 남는다.
                    try { _restyleInputSensorMarkers(uniqueId, _o); } catch (e) {}
                    var facilities3d = _slInst.cachedFacilities3d;
                    if (!facilities3d || !facilities3d.length) { return; }
                    try { AoTMapSensorLabels.attach(uniqueId, map, facilities3d, _o); } catch (e) {}
                };
            }
        } catch (e) {}

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

        // 모양은 공용(`AoTMapPopup.skeleton`)에 있다. 이 이름은 부르는 자리가
        // 여섯 곳이라 그대로 둔다.
        function _buildZoneSkel() {
            return window.AoTMapPopup.skeleton();
        }

        function _buildZonePopupHTML(zoneName, defSec) {
            // 탭 키·이름·순서는 시설 모달과 **같다**(overview/envctl/about).
            // 예전에는 zone 만 zoverview/zdevices/zfunctions 를 쓰고 첫 탭 이름도
            // [상태]여서, 시설에서 배운 화면 구조가 구역에서 통하지 않았다.
            // 위젯 옵션 popup_default_tab 도 이 세 키를 그대로 쓰므로 매핑이 없다.
            defSec = (defSec === 'envctl' || defSec === 'about') ? defSec : 'overview';
            var P = window.AoTMapPopup;
            return P.buildModalHeader({ name: zoneName || _tr('Zone'), up: true }) +
                   P.buildSectionNav(defSec, [
                       { key: 'overview', label: 'Overview' },
                       { key: 'envctl',   label: 'Environment & Control' },
                       { key: 'about',    label: 'About' }
                   ]) +
                   P.sectionPane('overview', defSec, _buildZoneSkel()) +
                   P.sectionPane('envctl',   defSec, '') +
                   P.sectionPane('about',    defSec, '');
        }

        // 노트 패널은 z-index 최상위라 모달 위로 뜨지 못한다 — 열기 전에 모달을
        // 먼저 닫는다(필지·시설·장치 모달도 같은 처리).
        function _closeZoneModal(uid) {
            var z2 = _zonePopupState[uid];
            if (z2 && z2.popup) {
                try { z2.popup.remove(); } catch (e) {}
            }
        }

        // 현재 블록의 값을 눌러 이 구역의 대표 측정을 정한다.
        //
        // 저장은 도형(GeoShape.meta_json)이다 — 구역마다 볼 것이 다르고(육묘장은
        // 온도, 노지는 토양수분), 도형에 붙어 있어야 지도 라벨·필지 요약·구역
        // 모달이 **한 값**을 본다. 위젯 옵션에 두면 같은 구역이 대시보드마다
        // 다른 것을 대표로 내세운다.
        function _wireZoneRepPick(uid, pane, zoneUuid, data) {
            if (!(data.zone || {}).can_edit) return;
            window.AoTMapPopup.wireEnvNowPick(pane, function (key) {
                fetch('/api/geo/zone/' + encodeURIComponent(zoneUuid) + '/rep_key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json',
                               'X-CSRFToken': _csrfHeader() },
                    body: JSON.stringify({ key: key })
                })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (j) {
                    if (!j || !j.ok) throw new Error('save failed');
                    data.rep_key = j.rep_key || null;
                    // 서버가 캐시를 비웠으니 클라이언트 캐시도 함께 버린다 —
                    // 안 버리면 창을 닫았다 다시 열 때 옛 지정이 돌아온다.
                    invalidateModal('zone', zoneUuid);
                    // 지도 구역 라벨도 이 값을 쓴다. 상태는 60초 주기라
                    // 다음 tick 까지 기다리면 방금 고른 것이 라벨에 안 뜬다.
                    var inst = window.AoTWidgetInstances[uid];
                    if (inst && inst._refreshZoneStatusNow) inst._refreshZoneStatusNow();
                })
                .catch(function () {
                    // 되돌린다 — 저장 안 된 지정을 켜 둔 채로 두면 다음에 열었을
                    // 때 사라져 있어 "왜 풀렸지"가 된다.
                    pane.querySelectorAll('.aot-env-now-item').forEach(function (el) {
                        el.classList.toggle('is-rep',
                            !!data.rep_key && el.dataset.repKey === data.rep_key);
                    });
                });
            });
        }

        /* 구역 [현재] 카드의 [설정]. 구역에는 [제어 상태] 카드가 없다 —
         * 자동제어는 시설의 것이다. */
        function _wireZoneCardConfig(uid, pane, zoneUuid, data) {
            var P = window.AoTMapPopup;
            if (!P || !(data.zone || {}).can_edit) return;
            _wireCardConfig(uid, pane, {
                canEdit: true,
                cards: ['now'],
                ownerUuid: zoneUuid,
                saveUrl: '/api/geo/zone/' + encodeURIComponent(zoneUuid) +
                         '/hidden_rows',
                titleOf: function () {
                    return (window._ ? window._('Environment') : 'Environment');
                },
                choicesOf: function () {
                    return P.envRowChoices(((data.zone || {}).env || {}).readings);
                },
                hiddenOf: function () { return data.hidden_rows || {}; },
                onSaved: function (rows) {
                    data.hidden_rows = rows;
                    invalidateModal('zone', zoneUuid);
                    _renderZoneOverview(uid, pane, data, zoneUuid);
                }
            });
        }

        // [현황] 탭 — 현재 환경 + 노트 (시설 [현황]과 같은 순서)
        function _renderZoneOverview(uid, pane, data, zoneUuid) {
            var z = data.zone || {};
            if (!window.AoTMapPopup) { return; }
            pane.innerHTML =
                (window.AoTMapPopup.buildHazardsHtml
                   ? window.AoTMapPopup.buildHazardsHtml(data.hazards) : '') +
                (window.AoTMapPopup.buildIrrigationHtml
                   ? window.AoTMapPopup.buildIrrigationHtml(data.irrigation) : '') +
                window.AoTMapPopup.buildZoneStatusHtml(z, {
                    repKey: data.rep_key || null,
                    selectable: !!z.can_edit,
                    canAdd: !!z.can_edit,
                    // 카드 제목 옆 [설정] — 시설과 같은 자리·같은 규칙.
                    configurable: !!z.can_edit,
                    hidden: (data.hidden_rows || {}).now
                });
            _wireZoneRepPick(uid, pane, zoneUuid, data);
            _wireZoneCardConfig(uid, pane, zoneUuid, data);
            // 축이 없는 줄(CO2·토양수분·이슬점…)은 추세로 답한다 — 값은 이미
            // 그려져 있고, 이력이 도착하면 그 자리만 스파크라인으로 바뀐다.
            if (window.AoTMapPopup.fillEnvSparklines) {
                window.AoTMapPopup.fillEnvSparklines(
                    pane, data.sensors, ((z.env) || {}).readings);
            }
            // 예정을 만드는 자리는 **노트 하나**다(노트 본문의 한 구간을 골라
            // 시각을 준다). 계층마다 별도 폼을 두면 사용자가 쓰기 전에 종류를
            // 고르는 옛 방식으로 되돌아간다.

            // 구획 줄 → 그 구획 모달로 내려간다. 구역 모달은 닫는다 —
            // 모달 위에 모달을 쌓으면 뒤로 가기가 어디로 가는지 알 수 없다
            // (필지 → 구역 줄 클릭과 같은 규약).
            pane.querySelectorAll('.aot-ov-plot-link').forEach(function (row) {
                row.addEventListener('click', function () {
                    var pUuid = row.dataset.plotUuid;
                    if (!pUuid || !window.AoTMapPlot) return;
                    var st = window.AoTMapPlot.state(uid);
                    if (!st || !st.opts) return;
                    _closeZoneModal(uid);
                    window.AoTMapPlot.openModal(
                        uid, (_actLabelState[uid] || {}).map, pUuid, st.opts);
                });
            });

            // 컨테이너다 — 그 안(구획·시설·장치)의 노트까지 함께 낸다.
            // 자기 것만 보이면 대부분 비어 있고, AI 는 이미 자손을 훑는다.
            window.AoTNotesBlock.wire(pane,
                { targetId: zoneUuid, targetType: 'GeoShape', name: z.name || '' },
                { descendants: true, beforeOpen: function () { _closeZoneModal(uid); } });
        }

        // [개요] 탭 — 사진 + 구역 정보 (시설 [개요]와 같은 순서)
        function _renderZoneAbout(uid, pane, data, zoneUuid) {
            var z = data.zone || {};
            if (!window.AoTMapPopup) { return; }
            pane.innerHTML = window.AoTMapPopup.buildZoneAboutHtml(z);

            var phBtn = pane.querySelector('.aot-ov-photo-btn');
            var phInput = pane.querySelector('.aot-ov-photo-input');
            if (!phBtn || !phInput) return;
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
                        // 사진 블록이 없던 경우 — [개요]만 재렌더.
                        // 방금 쓴 직후라 캐시를 먼저 버린다.
                        invalidateModal('zone', zoneUuid);
                        modalFetch('zone', zoneUuid)
                            .then(function (r) { return r.ok ? r.json() : null; })
                            .then(function (d) {
                                if (d && d.ok && pane.isConnected) {
                                    _renderZoneAbout(uid, pane, d, zoneUuid);
                                }
                            })
                            .catch(function () {});
                    }
                })
                .catch(function () { phBtn.disabled = false; });
            });
        }

        // 현재 보이는 센서 차트 div 반환 (envctl pane 내)
        function _zoneActiveChartDiv(popupEl) {
            var devPane = popupEl.querySelector('.aot-bay-popup-pane[data-pane="envctl"]');
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
            // 구역 스코프 없는 공용 이력 엔드포인트 — 시설 모달·장치 마커 팝업도
            // 같은 것을 쓴다(구역 별칭 라우트는 하위호환용으로만 남아있다).
            return fetch('/api/geo/output/' + encodeURIComponent(outputId) + '/history')
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

        // 독립 장치 이력 차트 렌더 (센서 없을 때 — 행 아래 토글).
        // 그래프 자체는 공용 모듈이 그린다(sensor-label.js) — 팝업마다 자체
        // Highstock 옵션을 두던 것을 통일한 결과.
        function _renderZoneDeviceChart(div, hist, name) {
            if (window.AoTSensorLabel && window.AoTSensorLabel.renderOutputHistory) {
                window.AoTSensorLabel.renderOutputHistory(div, hist, name, {});
            }
        }

        // 장치 이름 클릭 → 이력 오버레이 on/off
        // - 센서 차트 있을 때: 센서 차트에 오버레이 (facility 동일)
        // - 센서 없을 때: 장치 행 아래 독립 차트 토글
        function _selectZoneOutputOverlay(uid, popupEl, outputId, outputName) {
            var z = _zonePopupState[uid];
            if (!z) return;
            var devPane = popupEl.querySelector('.aot-bay-popup-pane[data-pane="envctl"]');
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
        //
        // **구역과 식생이 이 하나를 함께 쓴다.** 모달은 한 번에 하나만 열리므로
        // 상태 슬롯(`_zonePopupState[uid]`)도 공유한다 — 다른 점은 `z.scope`
        // 하나뿐이다(`{kind:'zone'|'plot', uuid}`).
        //
        // 식생에서 달라지는 것은 **드래그 정렬을 저장하지 않는다** 는 것뿐이다:
        // 장치 순서는 구역의 속성이라, 구획 창에서 바꾸면 그 구역을 보는 다른
        // 사람의 순서까지 조용히 바뀐다. 구획별 순서를 따로 저장하는 것은
        // "참조 결과를 저장하지 말 것"(C-2)에 걸린다.
        function _renderZoneDevices(uid, pane, data, zoneUuid) {
            var canCtrl = _zoneCanCtrl(uid);
            var z = _zonePopupState[uid] || {};
            var isPlot = !!(z.scope && z.scope.kind === 'plot');
            var outputOrder = (data.zone && data.zone.output_order) || [];
            var sensors = z._sensors || [];
            var html = '';

            // 단일 차트 영역 — 센서 있으면 센서 차트, 없으면 장치 선택 시 여기에 렌더
            // 카드 제목 — 베이(공용 빌더)와 **같은 어휘**를 쓴다.
            html += '<div class="aot-ov-card-title">' + _tr('Environment') + '</div>';
            html += '<div class="aot-zone-chart-area">';
            if (sensors.length) {
                var sensorTabs = sensors.length > 1
                    ? '<div class="aot-act-tabs-nav">' + sensors.map(function (s, i) {
                        // 구역에서 빌려온 센서는 그 사실을 탭에서도 말한다 —
                        // 안 그러면 구획마다 따로 잰 값으로 읽힌다.
                        return '<button type="button" class="aot-act-tab-btn' + (i === 0 ? ' active' : '') + '"' +
                               ' data-sensor-idx="' + i + '">' + _escZ(s.name) +
                               window.AoTMapPopup.scopeBadgeHtml(s.scope, s.distance_m,
                                                                 s.nearest_reason) +
                               window.AoTMapPopup.noDataBadgeHtml(s.no_data) + '</button>';
                      }).join('') + '</div>'
                    : '';
                var sensorCharts = sensors.map(function (s, i) {
                    return '<div class="aot-bay-sensor-chart" data-sensor-idx="' + i + '"' +
                           (i === 0 ? '' : ' style="display:none"') + '></div>';
                }).join('');
                // 센서가 하나면 탭이 없어 이름도 배지도 걸릴 자리가 없다.
                // 그런데 그 하나가 **구획 밖에서 온 값**이면(가장 가까운 것)
                // 그 사실이 사라지는 것이 가장 위험하다 — 사용자는 이 구획에서
                // 잰 값으로 읽는다. 탭 대신 설명 한 줄을 둔다(누를 것이 하나뿐인
                // 탭은 아무것도 제어하지 않는 컨트롤이라 두지 않는다).
                var sensorCaption = '';
                if (sensors.length === 1 && sensors[0] && sensors[0].scope &&
                        sensors[0].scope !== 'plot') {
                    sensorCaption = '<div class="aot-ov-muted aot-zone-sensor-src">' +
                        _escZ(sensors[0].name) +
                        window.AoTMapPopup.scopeBadgeHtml(sensors[0].scope,
                                                          sensors[0].distance_m,
                                                          sensors[0].nearest_reason) +
                        window.AoTMapPopup.noDataBadgeHtml(sensors[0].no_data) +
                        '</div>';
                }
                html += '<div class="aot-zone-sensor-sec">' + sensorTabs +
                        sensorCaption + sensorCharts + '</div>';
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
                html += '<div class="aot-ov-card-title">' + _tr('Control') + '</div>';
                html += '<div class="aot-zone-output-list">';
                outputs.forEach(function (out) {
                    out.channels.forEach(function (ch) {
                        var rawLabel = out.channels.length > 1
                            ? out.name + ' – ' + ch.name
                            : out.name;
                        // 시설 액추에이터와 **같은 2행 골격**을 쓴다. 예전에는
                        // 구역만 한 줄에 [설정][토글]을 몰아넣어, 같은 장치가
                        // 구역 목록과 시설 목록에서 다르게 생겼다.
                        var rtKey = out.unique_id + '::' + ch.channel;
                        // 영향 범위 — "켜면 무엇이 함께 젖는가". 토글 바로
                        // 아래(2행)에 둔다. 경고가 토글에서 멀어지면 켜는
                        // 순간에는 안 읽힌다.
                        var coverHtml = window.AoTMapPopup.coverageHtml(
                            out.also_covers, out.coverage_pct);
                        html += window.AoTMapPopup.buildOutputRow({
                            slot: out.unique_id,
                            // rawName 이라 **여기서 이스케이프한다** — 장치
                            // 이름은 사용자 입력이다.
                            name: _escZ(rawLabel) +
                                  window.AoTMapPopup.scopeBadgeHtml(out.scope,
                                                                    out.distance_m,
                                                                    out.nearest_reason),
                            rawName: true,
                            drag: canCtrl && !isPlot,
                            nameAttrs: ' style="cursor:pointer"' +
                                ' data-output-id="' + _escZ(out.unique_id) + '"' +
                                ' data-output-name="' + _escZ(rawLabel) + '"',
                            primary: canCtrl
                                ? '<label class="btn-toggle aot-act-toggle-right">' +
                                  '<input type="checkbox" class="btn-toggle-input aot-zone-output-toggle"' +
                                  ' data-output-id="' + _escZ(out.unique_id) + '"' +
                                  ' data-channel="' + ch.channel + '">' +
                                  '<span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>' +
                                  '</label>'
                                : '',
                            // 시간 칸은 공용(AoTMapPopup.timeSlotHtml)이다 —
                            // 시설·장치 모달과 같은 칸이라, 켜면 여기서도 곧바로
                            // 타이머가 흐른다. deferLast: 마지막 작동 시간은
                            // 아래 배치 한 방(_loadZoneOutputRuntimes)으로 온다.
                            meta: window.AoTMapPopup.timeSlotHtml({
                                      outputId: out.unique_id,
                                      channel: ch.channel,
                                      deferLast: true }) +
                                  '<span class="aot-act-rt" data-rt-key="' +
                                  _escZ(rtKey) + '"></span>',
                            // 자기 줄을 갖는 칸으로 넘긴다 — meta 에 이어붙이면
                            // 시간 숫자에 달라붙는다(buildOutputRow 주석 참조).
                            note: coverHtml,
                            settings: canCtrl
                                ? window.AoTMapPopup.scheduleButtonHtml({
                                      outputId: out.unique_id,
                                      channel: ch.channel,
                                      name: rawLabel })
                                : ''
                        });
                    });
                });
                html += '</div>';
            } else {
                html += window.AoTMapPopup.emptyLine(_tr('No devices'));
            }

            // 기능 목록 — 별도 탭이었던 것을 이 탭 하단으로 흡수
            html += _buildZoneFunctionsHtml(data, uid);

            // 상태 폴링(_fetchAndUpdateZoneOutputStates)이 재조회 없이 바로 쓸 수 있게
            // 이 팝업의 장치 id 목록과 렌더된 pane 을 상태 객체에 보관해 둔다.
            z.outputIds = outputs.map(function (o) { return o.unique_id; });
            z.devPane = pane;

            pane.innerHTML = html;

            // 2행의 작동·예약 시간 — 모달을 열 때 한 번만. 5초 폴링에 얹으면
            // influx 를 계속 두들긴다(서버 주석 참조).
            _loadZoneOutputRuntimes(pane, outputs);

            // 드래그 정렬 — 구역에서만. 순서는 구역의 속성이라 구획 창에서
            // 바꾸면 그 구역을 보는 다른 사람의 순서까지 함께 바뀐다.
            if (canCtrl && !isPlot && window.AoTActuatorOrder) {
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

        // 출력 행 2행의 마지막 작동 시간·예약을 배치 한 번으로 채운다.
        // 낱개로 물으면 장치 수만큼 influx 를 두들긴다. 자리는 렌더 때 이미
        // 잡혀 있으므로 도착한 것만 갈아 끼운다.
        function _loadZoneOutputRuntimes(pane, outputs) {
            if (!pane || !outputs || !outputs.length || !window.AoTMapPopup) return;
            var items = [];
            outputs.forEach(function (out) {
                (out.channels || []).forEach(function (ch) {
                    items.push({ id: out.unique_id, channel: ch.channel });
                });
            });
            if (!items.length) return;

            fetch('/api/geo/output_runtimes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json',
                           'X-CSRFToken': _csrfHeader() },
                body: JSON.stringify({ items: items })
            })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (j) {
                if (!j || !j.ok || !pane.isConnected) return;
                pane.querySelectorAll('.aot-act-rt').forEach(function (cell) {
                    var rt = j.runtimes[cell.dataset.rtKey];
                    var row = cell.closest('.aot-act-row');
                    window.AoTMapPopup.seedTimeSlot(
                        row && row.querySelector('.aot-act-time'), rt);
                    cell.innerHTML = window.AoTMapPopup.nextRunHtml(rt);
                });
            })
            .catch(function () {});
        }

        // 기능 목록 — [환경·제어] 탭 하단 섹션. 예전에는 별도 탭이었는데,
        // 시설은 탭이 3개(현황/환경·제어/개요)이고 구역만 4개라 같은 위치의
        // 탭이 다른 것을 열었다. 기능은 "이 구역을 무엇이 움직이는가"이므로
        // 장치 목록 바로 아래가 제자리다.
        function _buildZoneFunctionsHtml(data, uid) {
            var canCtrl = _zoneCanCtrl(uid);
            var funcs = data.functions || [];
            if (!funcs.length) return '';
            var kindLabel = { 'custom': _tr('Custom'), 'function': _tr('Function'),
                'conditional': _tr('Conditional'), 'trigger': _tr('Trigger'),
                'pid': 'PID', 'device': _tr('Device') };
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
                // 복합장치(그릇)는 이름을 눌러 그 장치의 모달로 내려갈 수 있게
                // 한다 — 안에 무엇이 들었는지는 거기서 본다.
                var nameAttrs = (fn.kind === 'device')
                    ? ' style="cursor:pointer" data-device-uuid="' + _escZ(fn.unique_id) +
                      '" data-device-name="' + _escZ(fn.name) + '"'
                    : '';
                html += '<div class="aot-act-row">' +
                        '<div class="aot-act-line">' +
                        '<span class="aot-act-name"' + nameAttrs + '>' + _escZ(fn.name) +
                        ' <span class="aot-act-tag">' + _escZ(kl) + '</span>' +
                        window.AoTMapPopup.scopeBadgeHtml(fn.scope, fn.distance_m) + '</span>' +
                        ctrl +
                        '</div></div>';
            });
            return '<div class="aot-act-group-header">' + _tr('Functions') + '</div>' + html;
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
                    var devPane = popupEl.querySelector('.aot-bay-popup-pane[data-pane="envctl"]');
                    if (devPane) _activateZoneSensorTab(uid, devPane, idx);
                    return;
                }

                // 복합장치 이름 클릭 → 그 장치의 모달 (구역 모달은 닫는다)
                var devNameEl = e.target.closest('.aot-act-name[data-device-uuid]');
                if (devNameEl && popupEl.contains(devNameEl)) {
                    var z0 = _zonePopupState[uid];
                    if (z0 && z0.popup) { try { z0.popup.remove(); } catch (err) {} }
                    _openDeviceModal(uid, devNameEl.dataset.deviceUuid, '0',
                                     devNameEl.dataset.deviceName || '');
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
                    var secKey = navBtn.dataset.sec;
                    window.AoTMapPopup.activateSection(
                        popupEl, secKey, navBtn.closest('.aot-bay-popup-nav'));
                    if (secKey === 'envctl') {
                        var devPane2 = popupEl.querySelector('.aot-bay-popup-pane[data-pane="envctl"]');
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

                // 장치 설정 — 시작/종료 시각 예약 (시설 모달·마커 팝업과 공용 창)
                var setBtn = e.target.closest('.aot-output-settings');
                if (setBtn && popupEl.contains(setBtn)) {
                    _openZoneOutputScheduleWheel(uid,
                        setBtn.dataset.outputId,
                        parseInt(setBtn.dataset.channel || '0', 10),
                        setBtn.dataset.outputName || '');
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

        // 구역 팝업 장치 목록 — 실제 상태 폴링 동기화.
        // 서버는 원본 상태값('on'/'off'/'pending'/'fault'/숫자/불리언)을 그대로 주고,
        // 판정은 공용 분류기 AoTOutputState(aot-output-state.js)로 한다 — 이게 없으면
        // 'fault'(응답 없음/오프라인)를 truthy 로 오판해 오프라인 장치가 켜진 것처럼
        // 표시되는 버그가 난다(facility 팝업/장치 마커와 동일 판정 기준으로 통일).
        function _fetchAndUpdateZoneOutputStates(uid) {
            var z = _zonePopupState[uid];
            if (!z || !z.popup || !z.outputIds || !z.outputIds.length || !z.devPane) return;
            fetch('/api/geo/output_states', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json',
                           'X-CSRFToken': _csrfHeader() },
                body: JSON.stringify({ ids: z.outputIds })
            })
            .then(function (r) { return r.json(); })
            .then(function (j) {
                var z2 = _zonePopupState[uid];
                if (!j || !j.ok || !z2 || !z2.popup || !z2.devPane) return;
                z2.devPane.querySelectorAll('.aot-act-row[data-slot]').forEach(function (row) {
                    var toggle = row.querySelector('.aot-zone-output-toggle');
                    if (!toggle) return;
                    var chStates = j.states[row.dataset.slot];
                    if (!chStates) return;
                    var raw = chStates[toggle.dataset.channel || '0'];
                    if (raw === undefined) return;
                    var cls = window.AoTOutputState
                        ? window.AoTOutputState.classify(raw)
                        : { isOn: (raw === 'on' || (typeof raw === 'number' && raw > 0)),
                            isPending: (raw === 'pending'), isFault: (raw === 'fault'),
                            cssClass: null };
                    if (!toggle.disabled && document.activeElement !== toggle) {
                        toggle.checked = !!cls.isOn;
                    }
                    toggle.classList.toggle('aot-toggle-pending', !!cls.isPending);
                    toggle.classList.toggle('aot-toggle-fault', !!cls.isFault);
                    row.classList.remove('active-background', 'inactive-background',
                                          'fault-background', 'hold-background',
                                          'unknown-background');
                    if (cls.cssClass) { row.classList.add(cls.cssClass); }
                    // 2행 시간 칸도 같은 판정으로 따라간다 — 이걸 빼먹어서
                    // 구역 목록만 켜고 꺼도 시간이 멈춰 있었다.
                    window.AoTMapPopup.applyTimeSlot(
                        row.querySelector('.aot-act-time'),
                        { countsRuntime: cls.countsRuntime });
                });
            })
            .catch(function () {});
        }

        function _startZoneOutputPolling(uid) {
            var z = _zonePopupState[uid];
            if (!z) return;
            if (z.pollTimer) { clearInterval(z.pollTimer); z.pollTimer = null; }
            if (z.visHandler) {
                document.removeEventListener('visibilitychange', z.visHandler);
                z.visHandler = null;
            }
            if (!z.outputIds || !z.outputIds.length) return;
            var refreshMs = ((_actLabelState[uid] || {}).refreshMs) || 5000;
            _fetchAndUpdateZoneOutputStates(uid);
            z.pollTimer = setInterval(function () { _fetchAndUpdateZoneOutputStates(uid); }, refreshMs);

            // 백그라운드 탭에서는 setInterval 이 분당 1회 수준으로 스로틀된다.
            // 모달을 탭 두 개에 띄워 놓고 한쪽에서 켜면 다른 쪽이 한참 옛 상태로
            // 남는다 — 돌아오는 순간 바로 맞춘다.
            z.visHandler = function () {
                if (document.visibilityState !== 'visible') return;
                var z2 = _zonePopupState[uid];
                if (!z2 || !z2.popup) {
                    document.removeEventListener('visibilitychange', z.visHandler);
                    return;
                }
                _fetchAndUpdateZoneOutputStates(uid);
            };
            document.addEventListener('visibilitychange', z.visHandler);
        }

        // 장치 시작/종료 예약 — 공용 모듈(AoTMapPopup.openOutputSchedule) 위임.
        // 예전에는 이 파일 안에 구역 전용 시간휠 + setTimeout 구현이 있었다.
        // 지금은 시설 모달·장치 마커 팝업과 같은 창을 쓰고, 미래 시작은 서버
        // 스케줄러에 등록되므로 탭을 닫아도 실행된다.
        function _openZoneOutputScheduleWheel(uid, outputId, channel, outputName) {
            if (!window.AoTMapPopup || !window.AoTMapPopup.openOutputSchedule) return;
            window.AoTMapPopup.openOutputSchedule({
                shell:     _showFacilityCenterOverlay,
                outputId:  outputId,
                channel:   channel,
                name:      outputName,
                onApplied: function () { _fetchAndUpdateZoneOutputStates(uid); }
            });
        }

        function _openZonePopup(uid, zoneUuid, zoneName) {
            var st = _zonePopupState[uid] || {};
            if (st.popup) { try { st.popup.remove(); } catch (e) {} }

            // 위젯 옵션 popup_default_tab 을 그대로 쓴다 — 구역 탭 키가 시설과
            // 같아지면서 매핑이 필요 없어졌다(예전에는 'about' 에 해당하는 구역
            // 탭이 없어 [상태]로 떨어졌다).
            var zoneDefSec = (_actLabelState[uid] || {}).popupDefaultTab || 'overview';

            var popup = _showFacilityCenterOverlay(
                _buildZonePopupHTML(zoneName, zoneDefSec), uid, zoneUuid);
            // 패널을 **연 뒤에** 옮긴다 — 카메라 여백이 패널 폭을 알아야 대상이
            // 패널 뒤로 가지 않는다.
            _focusMapOn(uid, zoneUuid);
            _zonePopupState[uid] = { popup: popup, zoneUuid: zoneUuid,
                                     _sensors: [], _histCache: {},
                                     overlayOutputId: null, overlayOutputName: null };

            var popupEl = popup.getElement();
            var body = popupEl && popupEl.querySelector('.maplibregl-popup-content');

            popup.on('close', function () {
                var z = _zonePopupState[uid];
                if (z && z.popup === popup) {
                    if (z.pollTimer) { clearInterval(z.pollTimer); }
                    if (z.visHandler) {
                        document.removeEventListener('visibilitychange', z.visHandler);
                    }
                    _zonePopupState[uid] = {};
                }
            });

            modalFetch('zone', zoneUuid)
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    if (!data || !data.ok) return;
                    var z = _zonePopupState[uid];
                    if (!z || !z.popup) return;

                    // 센서 목록 저장 (탭 지연 렌더에 사용)
                    z._sensors = data.sensors || [];

                    // [현황] 탭 — 현재 환경 + 노트
                    var ovPane = body && body.querySelector('.aot-bay-popup-pane[data-pane="overview"]');
                    if (ovPane) _renderZoneOverview(uid, ovPane, data, zoneUuid);

                    // [환경·제어] 탭 — 차트 + 장치 + 기능
                    var devPane = body && body.querySelector('.aot-bay-popup-pane[data-pane="envctl"]');
                    if (devPane) {
                        _renderZoneDevices(uid, devPane, data, zoneUuid);
                        _startZoneOutputPolling(uid);
                    }

                    // [개요] 탭 — 사진 + 구역 정보
                    var abPane = body && body.querySelector('.aot-bay-popup-pane[data-pane="about"]');
                    if (abPane) _renderZoneAbout(uid, abPane, data, zoneUuid);

                    _wireZoneTabs(body, uid, zoneUuid);

                    // When the popup opened directly on the devices tab (popup_default_tab
                    // = envctl), render its sensor charts now — normally deferred to the
                    // nav click handler.
                    if (zoneDefSec === 'envctl' && devPane) {
                        var firstChart = devPane.querySelector('.aot-bay-sensor-chart');
                        if (firstChart && firstChart.dataset.rendered !== '1') {
                            _activateZoneSensorTab(uid, devPane, 0);
                        }
                        _reapplyZoneOverlay(uid, popupEl);
                    }

                    // 제목 갱신 + 상태 점
                    var titleEl = body && body.querySelector('.aot-sensor-popup-title');
                    if (titleEl && data.zone && data.zone.name) {
                        titleEl.textContent = data.zone.name;
                    }
                    window.AoTMapPopup.applyStatusDot(body, data.zone && data.zone.status);

                    // 상위 필지로 올라가는 화살표
                    _wireUpBtn(body, uid, {
                        uuid: data.zone && data.zone.site_uuid,
                        name: data.zone && data.zone.site_name
                    }, function () {
                        var z2 = _zonePopupState[uid];
                        if (z2 && z2.popup) { try { z2.popup.remove(); } catch (e) {} }
                    });
                })
                .catch(function () {});
        }
        // ── End Zone modal ─────────────────────────────────────────────────────

        // ── 식생 모달에 [환경·제어]를 붙인다 ───────────────────────────────────
        //
        // 구획 모달 자체는 `aot-map-plot.js` 가 그린다(작물·기간·이력·노트는
        // 그쪽 일이다). 제어 배선만 여기서 빌려준다 — 폴링·토글·예약·이력
        // 오버레이가 전부 이 파일의 `_zonePopupState` 위에 서 있어서, 그쪽으로
        // 옮기면 같은 기계를 두 벌 갖게 된다.
        //
        // `shell` 을 opts 로 넘기는 것과 같은 이음매다. 모달은 한 번에 하나만
        // 열리므로 상태 슬롯도 구역과 **공유**한다 — 구역 모달이 열려 있었다면
        // 그쪽 폴링은 이미 자기 close 훅에서 정리됐다.
        /**
         * 필지 모달의 [환경·제어] — **구역 모달의 렌더를 그대로 빌려 쓴다.**
         *
         * 구획 모달이 같은 방식이다(`_attachPlotControl`). 센서 탭·제어 카드·
         * 이력 오버레이를 여기서 다시 만들면 같은 장치가 세 화면에서 다르게
         * 보이고, 폴링·토글·예약이 세 벌이 된다.
         *
         * `zoneUuid` 는 **비운다.** 구역 전용 쓰기(대표 측정 `rep_key`, 장치
         * 순서 `output_order`)가 필지 창에서 나가면 어느 구역의 설정인지
         * 모호하고, 실수로 그 구역을 보는 다른 사람의 화면을 바꾼다. 값이
         * 없으면 그 경로는 애초에 성립하지 않는다.
         */
        function _attachSiteControl(uid, popup, body, siteUuid) {
            if (!popup || !body) return;
            var pane = body.querySelector('.aot-bay-popup-pane[data-pane="envctl"]');
            if (!pane) return;

            var prev = _zonePopupState[uid];
            if (prev && prev.pollTimer) { clearInterval(prev.pollTimer); }
            if (prev && prev.visHandler) {
                document.removeEventListener('visibilitychange', prev.visHandler);
            }

            _zonePopupState[uid] = {
                popup: popup,
                zoneUuid: null,                       // 위 주석 참조
                scope: { kind: 'site', uuid: siteUuid },
                _sensors: [], _histCache: {},
                overlayOutputId: null, overlayOutputName: null
            };

            popup.on('close', function () {
                var z = _zonePopupState[uid];
                if (z && z.popup === popup) {
                    if (z.pollTimer) { clearInterval(z.pollTimer); }
                    if (z.visHandler) {
                        document.removeEventListener('visibilitychange', z.visHandler);
                    }
                    _zonePopupState[uid] = {};
                }
            });

            pane.innerHTML = _buildZoneSkel();

            fetch('/api/geo/site/' + encodeURIComponent(siteUuid) + '/contents',
                  { cache: 'no-store' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    if (!data || !data.ok) { pane.innerHTML = ''; return; }
                    var z = _zonePopupState[uid];
                    if (!z || z.popup !== popup || !pane.isConnected) return;

                    z._sensors = data.sensors || [];
                    // 구역처럼 `output_order` 를 읽지 않는다 — 필지에는 그
                    // 설정이 없다(빈 객체를 주어 구역의 순서를 빌려오지 않는다).
                    _renderZoneDevices(uid, pane, {
                        zone: {}, outputs: data.outputs, functions: data.functions
                    }, null);
                    _startZoneOutputPolling(uid);

                    if (pane.style.display !== 'none') {
                        var first = pane.querySelector('.aot-bay-sensor-chart');
                        if (first && first.dataset.rendered !== '1') {
                            _activateZoneSensorTab(uid, pane, 0);
                        }
                    }
                })
                .catch(function () { pane.innerHTML = ''; });

            // 탭·토글·이력 오버레이는 구역과 같은 위임 핸들러를 쓴다.
            _wireZoneTabs(body, uid, null);
        }

        function _attachPlotControl(uid, popup, body, plotUuid) {
            if (!popup || !body) return;
            var pane = body.querySelector('.aot-bay-popup-pane[data-pane="envctl"]');
            if (!pane) return;

            var prev = _zonePopupState[uid];
            if (prev && prev.pollTimer) { clearInterval(prev.pollTimer); }
            if (prev && prev.visHandler) {
                document.removeEventListener('visibilitychange', prev.visHandler);
            }

            _zonePopupState[uid] = {
                popup: popup,
                // zoneUuid 는 비운다 — 구역 전용 쓰기(rep_key·output_order)가
                // 실수로 구획 창에서 나가면 **그 구역을 보는 다른 사람의 설정**을
                // 바꾼다. 값이 없으면 그 경로는 애초에 성립하지 않는다.
                zoneUuid: null,
                scope: { kind: 'plot', uuid: plotUuid },
                _sensors: [], _histCache: {},
                overlayOutputId: null, overlayOutputName: null
            };

            popup.on('close', function () {
                var z = _zonePopupState[uid];
                if (z && z.popup === popup) {
                    if (z.pollTimer) { clearInterval(z.pollTimer); }
                    if (z.visHandler) {
                        document.removeEventListener('visibilitychange', z.visHandler);
                    }
                    _zonePopupState[uid] = {};
                }
            });

            pane.innerHTML = _buildZoneSkel();

            fetch('/api/geo/plot/' + encodeURIComponent(plotUuid) + '/contents',
                  { cache: 'no-store' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    if (!data || !data.ok) { pane.innerHTML = ''; return; }
                    var z = _zonePopupState[uid];
                    if (!z || z.popup !== popup || !pane.isConnected) return;

                    z._sensors = data.sensors || [];

                    // [현황]의 현재 환경 — 구역·시설과 같은 블록(밴드 바).
                    // 값이 이 응답에 함께 오므로 따로 조회하지 않는다.
                    // 대표 측정 지정은 넘기지 않는다: rep_key 는 시설의 설정이라
                    // 구획 창에서 쓰면 그 시설을 보는 다른 사람의 화면이 바뀐다.
                    var envSlot = body.querySelector(
                        '.aot-bay-popup-pane[data-pane="overview"] ' +
                        '[data-slot="envnow"]');
                    if (envSlot && window.AoTMapPopup.buildEnvNowHtml) {
                        envSlot.innerHTML = window.AoTMapPopup.buildEnvNowHtml(
                            (data.plot || {}).env,
                            // 프로그램이 정한 목표. 서버가 어떤 항목을 목표로
                            // 볼지 이미 정해 준다(_program_targets) — 여기서
                            // 다시 고르면 어휘가 두 곳에 생긴다.
                            { // 카드에서 뺄 항목 — **상위(시설/구역)의 설정을
                              // 물려받는다.** 서버가 어느 상위인지 이미 골라
                              // 준다(`_inherited_hidden_rows`) — 여기서 다시
                              // 고르면 규칙이 두 곳에 생긴다.
                              //
                              // [설정] 버튼은 두지 않는다(`configurable` 없음).
                              // 저장이 상위에 있으니 여기서 고치면 그 시설·구역을
                              // 보는 **다른 사람의 화면**이 함께 바뀐다 — 구획
                              // 창에 rep_key 를 넘기지 않는 것과 같은 이유다.
                              // 고치는 자리는 한 칸 위(←)의 그 창이다.
                              hidden: ((data.plot || {}).hidden_rows || {}).now,
                              targets: (data.plot || {}).targets,
                              // 한계(온도 주/야간 · 습도)는 목표와 다른 축이다 —
                              // 선으로 긋고 초록 면은 그리지 않는다.
                              limits: (data.plot || {}).limits,
                              // 목표가 곡선인 항목 — 숫자 대신 곡선 이름을 적고
                              // 앱 기본 구간은 그리지 않는다.
                              targetMethods: (data.plot || {}).target_methods });
                        // 축이 없는 줄(CO2·토양수분·이슬점…)은 추세로 답한다.
                        // 값은 이미 그려져 있고, 도착하면 그 자리만 바뀐다.
                        if (window.AoTMapPopup.fillEnvSparklines) {
                            window.AoTMapPopup.fillEnvSparklines(
                                envSlot, data.sensors,
                                ((data.plot || {}).env || {}).readings);
                        }
                    }

                    // `_renderZoneDevices` 는 `data.zone.output_order` 를 읽는다.
                    // 구획에는 순서가 없다 — 빈 객체를 주어 구역의 순서를
                    // 빌려오지 않게 한다(빌려오면 구역 창과 달라 보인다).
                    _renderZoneDevices(uid, pane, {
                        zone: {}, outputs: data.outputs, functions: data.functions
                    }, null);
                    _startZoneOutputPolling(uid);

                    // 상위로 올라가는 화살표.
                    //
                    // **시설 구획의 상위는 시설이다.** 예전에는 `kind:'zone'` 으로
                    // 고정했는데, 시설 구획에는 구역이 없어 서버가 `zone_uuid` 에
                    // **필지(site) 도형**을 넣어 준다(포함 판정의 폴백이 그렇게
                    // 잡는다 — 실측: `type='site'`). 그러면 구역 팝업이 필지
                    // uuid 로 열려 조회가 빈 손으로 끝나고, 화면은 **스켈레톤에
                    // 그대로 멈춘다**. 에러도 안 나서 "뒤로가기가 고장" 으로만 보인다.
                    //
                    // 이름까지 같은 경우가 있어(필지 "육묘장" 안의 시설 "육묘장")
                    // 화살표 라벨만으로는 어느 쪽인지 알 수 없었다.
                    // 노지 구획도 같은 함정을 갖는다 — zone 이 없는 지도에서는
                    // `zone_uuid` 에 site 가 온다. 그래서 **서버가 준 종류**
                    // (`zone_kind`)로 어느 창을 열지 정한다.
                    var _pl = data.plot || {};
                    var _up;
                    if (_pl.facility_uuid) {
                        _up = { kind: 'facility', uuid: _pl.facility_uuid,
                                name: _pl.facility_name };
                    } else {
                        _up = { kind: (_pl.zone_kind === 'site') ? 'site' : 'zone',
                                uuid: _pl.zone_uuid, name: _pl.zone_name };
                    }
                    _wireUpBtn(body, uid, _up, function () {
                        var z2 = _zonePopupState[uid];
                        if (z2 && z2.popup) { try { z2.popup.remove(); } catch (e) {} }
                    });

                    // 지금 이 탭이 열려 있으면 센서 차트를 바로 그린다(탭 클릭
                    // 핸들러가 하는 지연 렌더를 대신한다).
                    if (pane.style.display !== 'none') {
                        var first = pane.querySelector('.aot-bay-sensor-chart');
                        if (first && first.dataset.rendered !== '1') {
                            _activateZoneSensorTab(uid, pane, 0);
                        }
                    }
                })
                .catch(function () { pane.innerHTML = ''; });

            // 탭·토글·이력 오버레이는 구역과 같은 위임 핸들러를 쓴다.
            _wireZoneTabs(body, uid, null);
        }

        // 식생 로더가 늦게 찾아 쓸 수 있게 등록한다(등록소 주석 참조).
        _plotControlHooks[uniqueId] = _attachPlotControl;

        // 뒤로가기는 **구획 상세가 오는 즉시** 배선한다.
        //
        // 예전에는 `/contents` 응답 안에서만 드러냈다. 그 조회는 센서·환경·밸브를
        // 함께 끌어오는 무거운 것이라, 창이 다 그려진 뒤에도 제목줄의 화살표만
        // 한참 뒤에 튀어나왔다 — 사용자에게는 버튼이 늦게 "생기는" 것으로 보인다.
        //
        // 필요한 것(상위가 시설인가 구역인가, 그 이름)은 상세 응답에 이미 다
        // 들어 있다. `_wireUpBtn` 은 `dataset.wired` 로 두 번 붙지 않으므로
        // `/contents` 쪽 호출은 그대로 둬도 무해하다(그쪽이 먼저 오는 경로도 있다).
        //
        // **지도에 이미 있는 것으로 먼저 푼다.** 목록 응답에는 `zone_uuid` 만
        // 있고 그 도형이 구역인지 필지인지, 이름이 무엇인지는 없다 — 그런데
        // 지도는 그 도형을 이미 그리고 있다. 어느 소스에서 찾았는지가 곧 종류다
        // (도형 properties 에는 type 이 없다). 그래서 조회를 기다리지 않고
        // **창이 뜨는 순간** 화살표를 세울 수 있다.
        function _upFromMap(uuid) {
            var pairs = [['zones', 'zone'], ['sites', 'site'],
                         ['facilities', 'facility']];
            for (var i = 0; i < pairs.length; i++) {
                var src = map.getSource(pairs[i][0]);
                var hit = _findInFeatures(
                    (src && src._data && src._data.features) || [], uuid);
                if (!hit) continue;
                var pr = hit.properties || {};
                return { kind: pairs[i][1], uuid: uuid,
                         name: pr.name || pr.label_name || '' };
            }
            return null;
        }

        _plotUpHooks[uniqueId] = function (body, plot) {
            var _pl = plot || {};
            var _sn = _pl.sensors || {};
            var _up = null;
            if (_pl.facility_uuid) {
                _up = { kind: 'facility', uuid: _pl.facility_uuid,
                        name: _pl.facility_name };
            } else if (_sn.zone_uuid) {
                // 상세가 왔다 — 종류를 **서버가 준 값**으로 정한다. `zone_uuid`
                // 는 zone 이 아닐 수 있다: 구역이 없는 지도에서는 서버가
                // 필지(site)를 넣어 준다.
                _up = { kind: (_sn.zone_kind === 'site') ? 'site' : 'zone',
                        uuid: _sn.zone_uuid, name: _sn.zone_name };
            } else if (_pl.zone_uuid && _pl.zone_kind) {
                // 목록 응답도 종류와 이름을 함께 준다 — 상세를 기다릴 이유가 없다.
                _up = { kind: (_pl.zone_kind === 'site') ? 'site' : 'zone',
                        uuid: _pl.zone_uuid, name: _pl.zone_name };
            } else if (_pl.zone_uuid) {
                // 옛 응답(종류 없음) — 지도에 그 도형이 올라와 있으면 거기서
                // 푼다. 위젯이 구역 레이어를 안 그리는 설정이면 못 찾는다:
                // 그때는 그냥 두고 상세가 오면 붙는다(두 번 붙지는 않는다).
                _up = _upFromMap(_pl.zone_uuid);
            }
            if (!_up) return;
            _wireUpBtn(body, uniqueId, _up, function () {
                var z2 = _zonePopupState[uniqueId];
                if (z2 && z2.popup) { try { z2.popup.remove(); } catch (e) {} }
            });
        };

        // ── 상위(필지)로 올라가는 화살표 — 구역·시설 모달 제목줄 공용 ──────────
        //
        // site → 구역/시설로 내려가는 길은 필지 요약의 줄 클릭으로 열렸는데,
        // 되돌아오는 길이 없어 지도에서 라벨을 다시 찾아 눌러야 했다. 계층이
        // 한 방향으로만 흐르면 위젯 안에서 길을 잃는다.
        //
        // 버튼 자체는 공용 제목줄 빌더(AoTMapPopup.buildModalHeader)가 그린다.
        // 상위를 아직 모르는 동안에는 hidden 으로 자리만 잡아 두고, 상위가
        // 확인되면 아래에서 드러낸다 — 처음부터 보이면 상위가 없는 도형(필지에
        // 안 담긴 구역)에서 눌러도 아무 일도 일어나지 않는 버튼이 남는다.
        //
        // closeFn: 지금 열려 있는 모달을 닫는 방법(계층마다 다르다).
        // 모달 위에 모달을 쌓지 않는다 — 뒤로 가기가 어디로 가는지 모르게 된다.
        //
        // parent: { kind: 'site'|'zone'|'facility', uuid, name }
        // kind 를 안 주면 'site' 로 본다(구역·시설 모달의 상위는 늘 필지다).
        function _wireUpBtn(body, uid, parent, closeFn) {
            var btn = body && body.querySelector('.aot-modal-up');
            // kind 'sitelist' 는 uuid 가 없다 — 필지 위에는 개별 도형이 아니라
            // "이 지도의 필지 목록"이 있다.
            if (!btn || !parent) return;
            if (!parent.uuid && parent.kind !== 'sitelist') return;
            btn.hidden = false;
            btn.title = parent.name || '';
            btn.setAttribute('aria-label', _tr('Go up') + ': ' + (parent.name || ''));
            // _loadOverview 는 자동제어 토글 뒤에도 다시 돌아온다 — 그때마다
            // 리스너를 얹으면 한 번 눌러도 여러 번 열린다.
            if (btn.dataset.wired === '1') return;
            btn.dataset.wired = '1';
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                if (closeFn) { try { closeFn(); } catch (err) {} }
                var kind = parent.kind || 'site';
                if (kind === 'sitelist') {
                    // 목록 모달은 툴바 버튼 핸들러 안에 인라인으로 들어 있어
                    // 부를 함수가 없다 — 같은 사용자 동작(버튼 클릭)을 그대로 쓴다.
                    var listBtn = document.getElementById('tool-site-list-' + uid);
                    if (listBtn) listBtn.click();
                } else if (kind === 'zone') {
                    _openZonePopup(uid, parent.uuid, parent.name);
                } else if (kind === 'facility') {
                    var slices = _facilityBaySlices(uid, parent.uuid);
                    _openBayPopup(uid, parent.uuid,
                                  slices.length ? slices[0].id : null);
                } else {
                    _openSitePopup(uid, parent.uuid, parent.name);
                }
            });
        }

        // 시설의 bay 슬라이스 — 지도 칩이 쓰는 것과 같은 목록이어야 같은
        // 구역이 열린다(bay 1개 시설은 bays 가 비어 있고 slices 가 만들어 낸다).
        function _facilityBaySlices(uid, facilityUuid) {
            var facs = (_actLabelState[uid] || {}).facilities || [];
            for (var i = 0; i < facs.length; i++) {
                if (facs[i] && facs[i].unique_id === facilityUuid) {
                    return (window.AoTMapBay &&
                            window.AoTMapBay.slices(facs[i])) || [];
                }
            }
            return [];
        }

        // ── 구역 라벨의 대표값·상태 ────────────────────────────────────────────
        //
        // 시설 bay 칩이 이미 하는 일(2행: 이름 + 대표값, 밴드색 배경)을 구역
        // 라벨로 올린다. 예전에는 구역 라벨이 이름만 달고 있어, 지도를 열어도
        // "어디가 문제인가"를 알려면 구역을 하나씩 눌러 봐야 했다.
        //
        // 서버가 60초 캐시를 들고 있으므로 그보다 자주 물어도 새 값이 오지
        // 않는다. 값이 없는 구역은 2행을 그리지 않는다 — "—" 만 있는 줄은
        // 라벨만 키우고 아무것도 알려주지 않는다.
        function _startZoneLabelStatus(uid, mapUuid) {
            if (!mapUuid) return;
            var inst = window.AoTWidgetInstances[uid];
            if (!inst || inst._zoneStatusTimer) return;

            // 이 폴러는 **위젯 인스턴스마다** 돈다. 한 대시보드에 같은 지도를
            // 보는 지도 위젯이 여럿이면(김제: 지도·위성·위성2) 완전히 같은
            // 요청이 위젯 수만큼 같은 순간에 나갔다 — 생 fetch 라 공유 캐시를
            // 지나지 않았기 때문이다. 주기(60초)가 TTL(10초)보다 길어 신선도는
            // 그대로이고, 합쳐지는 것은 동시에 깨어난 위젯들의 중복뿐이다.
            //
            // `force` 는 다음 주기를 기다릴 수 없는 자리(대표 측정 변경 직후)용
            // 이다 — 캐시를 건너뛰지 않으면 방금 바꾼 것이 최대 10초 안 보인다.
            function _tick(force) {
                var i2 = window.AoTWidgetInstances[uid];
                if (!i2 || !i2.map) return;
                var _u = '/api/geo/zones/status?map_uuid=' + encodeURIComponent(mapUuid);
                var _p = window.AoTGeoData
                    ? window.AoTGeoData.get(_u, { force: !!force })
                          .then(function (r) { return r.ok ? r.json() : null; })
                    : fetch(_u).then(function (r) { return r.ok ? r.json() : null; });
                _p
                    .then(function (j) {
                        if (!j || !j.ok) return;
                        // 라벨이 아직 안 만들어졌을 수 있다 — 이 조회는 구역
                        // GeoJSON 이 도착하자마자 시작하는데, 라벨은 별도의
                        // label_aux 조회가 끝나야 생긴다. 응답을 들고 있다가
                        // 라벨이 생기면 그때 칠한다(예전에는 60초 뒤 다음
                        // 갱신까지 값이 안 나왔다).
                        var i3 = window.AoTWidgetInstances[uid];
                        if (i3) i3._zoneStatus = j.zones || {};
                        _applyZoneLabelStatusSoon(uid, 0);
                    })
                    .catch(function () {});
            }
            _tick();
            inst._zoneStatusTimer = setInterval(_tick, 60000);
            // 대표 측정을 바꾼 직후처럼 다음 주기를 기다릴 수 없는 자리를 위해.
            // 서버 캐시(60초)도 함께 비워졌을 때만 새 값이 온다.
            inst._refreshZoneStatusNow = function () { _tick(true); };
        }

        // 라벨이 나타날 때까지 짧게 재시도. 라벨 생성은 다른 비동기 경로라
        // 정확한 완료 시점을 알 수 없다.
        function _applyZoneLabelStatusSoon(uid, attempt) {
            var inst = window.AoTWidgetInstances[uid];
            if (!inst || !inst._zoneStatus) return;
            var painted = _applyZoneLabelStatus(uid, inst._zoneStatus);
            if (painted > 0 || attempt >= 6) return;
            setTimeout(function () {
                _applyZoneLabelStatusSoon(uid, attempt + 1);
            }, 1500);
        }

        // 구역 라벨이 값을 달지, 이름만 달지 — **입력 라벨이 켜져 있는가**가
        // 정한다.
        //
        // 입력 라벨(“1-1 28.7°C”)이 지도에 떠 있으면 구역 라벨의 대표값은 바로
        // 옆 숫자를 한 번 더 말하는 것이다. 같은 값이 두 번 뜨면 어느 쪽이
        // 기준인지 헷갈리고, 밴드색까지 두 겹으로 칠해져 지도가 시끄러워진다.
        // 그래서 그때는 예전처럼 이름만 남기고, 입력 라벨을 껐을 때만 구역
        // 라벨이 그 몫을 대신 진다.
        // 기준은 토글이 아니라 **지금 실제로 보이는가**다. 입력 라벨은 두 가지로
        // 사라진다: 사람이 토글로 끄거나, 줌 게이트(label_min_zoom)가 가리거나.
        // 처음에는 토글만 봤는데, "축소 시 라벨 숨기기"로 입력 라벨이 사라진
        // 화면에서는 구역 라벨이 이름만 단 채 남아 **아무도 값을 말하지 않았다**
        // — 정작 줌 아웃은 값이 가장 필요한 순간이다.
        function _zoneLabelDetailOn(inst) {
            if (!inst) return false;
            if (inst._hiddenLabels && inst._hiddenLabels.input) return true;
            return _inputLabelsZoomHidden(inst);
        }

        // 줌 게이트가 지금 입력 라벨을 가리고 있는가(_applyZoomGate 와 같은 판정).
        function _inputLabelsZoomHidden(inst) {
            var map = inst && inst.map;
            if (!map || typeof map.getZoom !== 'function') return false;
            var min = _labelMinZoom(inst);
            return min > 0 && map.getZoom() < min;
        }

        // 이름만 남기기 — 값 줄·문제 점·밴드색을 모두 걷는다. 토글은 언제든
        // 뒤집히므로 "안 그리기"로는 부족하고 이미 칠한 것을 되돌려야 한다.
        //
        // 배경은 **비우는 게 아니라 구역 기본색으로 되돌린다.** 라벨의 기본
        // 배경은 CSS 가 아니라 생성 시 인라인으로 박히므로(labelTheme 의 zone
        // 색), 그냥 지우면 투명한 글자만 남는다. 원래 색은 만들 때
        // dataset.labelColor 에 남겨 뒀다.
        function _stripZoneLabel(el) {
            var valEl = el.querySelector('.aot-zone-label-val');
            if (valEl) { valEl.style.display = 'none'; valEl.textContent = ''; }
            var dot = el.querySelector('.aot-zone-label-flag');
            if (dot) dot.remove();
            el.removeAttribute('title');
            _resetZoneLabelColor(el);
        }

        function _resetZoneLabelColor(el) {
            el.style.backgroundColor = el.dataset.labelColor || '';
            el.style.color = 'white';
        }

        function _applyZoneLabelStatus(uid, zones) {
            var inst = window.AoTWidgetInstances[uid];
            if (!inst) return 0;
            var byNode = inst._zonesByNodeId || {};
            var container = inst.map && inst.map.getContainer();
            if (!container) return 0;
            var detail = _zoneLabelDetailOn(inst);

            var painted = 0;
            container.querySelectorAll('.geo-label-marker[data-zone-node-id]')
                .forEach(function (el) {
                    painted++;
                    if (!detail) { _stripZoneLabel(el); return; }
                    var uuid = byNode[el.dataset.zoneNodeId];
                    var info = uuid && zones[uuid];
                    var valEl = el.querySelector('.aot-zone-label-val');
                    if (!valEl) return;
                    if (!info || !info.rep || info.rep.value == null) {
                        valEl.style.display = 'none';
                        // 값이 사라졌으면 밴드색도 함께 물러난다 — 안 그러면
                        // 센서가 끊긴 구역이 마지막 밴드색을 계속 달고 있다.
                        _resetZoneLabelColor(el);
                        _setZoneLabelFlag(el, info);
                        return;
                    }
                    var rep = info.rep;
                    valEl.style.display = '';
                    valEl.textContent = rep.value + (rep.unit || '');
                    // 밴드색은 지도 칩과 같은 함수가 낸다(경계·색표는 사용자가
                    // 바꿀 수 있고 그 정본은 JS 와 --aot-band-* 토큰이다).
                    if (window.AoTMapSensorLabels &&
                        window.AoTMapSensorLabels.bandColor) {
                        var c = window.AoTMapSensorLabels.bandColor(
                            rep.key, +rep.value, null, rep.unit);
                        if (c) {
                            el.style.backgroundColor = c;
                            el.style.color = window.AoTMapSensorLabels.textOn(c);
                        }
                    }
                    _setZoneLabelFlag(el, info);
                });
            return painted;
        }

        // 문제 표시 — 주의·이상일 때만. 라벨은 좁아서 글자를 더 넣을 수 없으니
        // 점 하나로 알리고, 자세한 것은 눌러서 본다(모달 제목줄과 같은 규칙).
        function _setZoneLabelFlag(el, info) {
            var head = el.querySelector('.aot-zone-label-head');
            if (!head) return;
            var status = info && info.status;
            var dot = head.querySelector('.aot-zone-label-flag');
            if (status !== 'warning' && status !== 'fault') {
                if (dot) dot.remove();
                el.removeAttribute('title');
                return;
            }
            if (!dot) {
                dot = document.createElement('span');
                dot.className = 'aot-zone-label-flag';
                head.appendChild(dot);
            }
            dot.className = 'aot-zone-label-flag is-' + status;
            var iss = (info && info.issues) || {};
            var sen = (info && info.sensors) || {};
            var why = iss.comm_fault ? _tr('Offline') + ' ' + iss.comm_fault
                    : iss.battery_low ? _tr('Battery') + ' ' + iss.battery_low
                    : (sen.total ? sen.valid + '/' + sen.total : _tr('Attention'));
            el.title = why;
        }

        // ── 장치 상세 모달 ─────────────────────────────────────────────────────
        //
        // 마커의 소형 팝업은 그대로 둔다 — "지도 위에서 바로 켜고 끈다"는 고유
        // 가치가 있고, 팝업이 커지면 anchor 계산이 깨져 늘 아래로 붙는다(그래서
        // 이력 차트를 안 넣었다). 대신 [자세히]로 이 모달을 연다: 요약은 팝업,
        // 파고들기는 모달로 **역할을 나눈다.**
        //
        // 탭은 구역·시설과 같은 셋이다(현황/환경·제어/개요).
        var _devicePopupState = {};
        _deviceModalOpener = _openDeviceModal;

        // 도형 호버 예열(_installShapeWarm)은 이 스코프 바깥에 있다 —
        // 모달 여는 함수들을 인스턴스에 걸어 두어야 닿는다(_onZoneLabelClick 과
        // 같은 방식).
        (function () {
            var _inst = window.AoTWidgetInstances[uniqueId];
            if (!_inst) return;
            _inst._openZoneModal = function (zoneUuid, zoneName) {
                _openZonePopup(uniqueId, zoneUuid, zoneName);
            };
            _inst._openSiteModal = function (siteUuid, siteName) {
                _openSitePopup(uniqueId, siteUuid, siteName);
            };
            _inst._openFacilityByShape = function (shapeUuid) {
                _openFacilityFromShape(uniqueId, shapeUuid);
            };
            // 입력(센서) 모달은 공용 컴포넌트가 띄우므로 **지도의 계층을 모른다**.
            // 상위가 무엇인지는 장치 상세 응답이 알려 주고(`data.parent`), 그것을
            // 여는 함수는 이 스코프에 있다 — 다리를 놓아 다른 모달과 같은 ← 버튼을
            // 쓰게 한다.
            // 센서 값 키(형제 모듈 aot-map-sensor-labels.js)가 여는 모달도 지도의
            // 다른 창들과 **같은 셸·같은 카메라**를 써야 한다. 그쪽은 모듈이 달라
            // 이 함수들에 닿지 못하므로 인스턴스에 걸어 둔다.
            _inst._modalShell = _showFacilityCenterOverlay;
            _inst._focusMap = function (target, opts) { _focusMapOn(uniqueId, target, opts); };
            _inst._wireSensorModalUp = function (body, deviceUuid, channel, closeFn) {
                if (!body || !deviceUuid) return;
                modalFetch('device', deviceUuid, channel)
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .then(function (data) {
                        if (data && data.ok) _wireUpBtn(body, uniqueId, data.parent, closeFn);
                    })
                    .catch(function () {});
            };
            // 도형 호버 예열이 시설 uuid 를 얻는 통로(_installShapeWarm 은
            // 형제 스코프다).
            _inst._facilityUuidOfShape = function (shapeUuid) {
                return _facilityUuidOfShape(uniqueId, shapeUuid);
            };
            // 입력 라벨 토글(addLayerPanel 은 형제 스코프다)이 구역 라벨을
            // 다시 칠하게 하는 통로. 캐시해 둔 상태를 쓰므로 재조회는 없다.
            _inst._repaintZoneLabels = function () {
                var i = window.AoTWidgetInstances[uniqueId];
                _applyZoneLabelStatus(uniqueId, (i && i._zoneStatus) || {});
            };
        }());

        // ── 장치 모달 — 탭 없는 단일 창 ────────────────────────────────────────
        //
        // 구역·시설은 "머무는 곳"이라 탭이 값을 한다(현황/환경·제어/개요).
        // 장치는 그렇지 않다 — **켜고 끄거나 열고 닫는 창**이다. 탭 셋으로
        // 나눠 놓으니 조작 하나 하려고 탭을 고르는 단계가 먼저 왔고, [개요]에
        // 담긴 것(유형·채널)은 그 조작에 아무 보탬이 안 됐다.
        //
        // 그래서 한 창에 세 덩이만 세운다: 이력 → 제어(시간·듀티 포함) → 노트.
        // 이력이 맨 위인 이유 — 켜기 전에 보는 것이 "지금까지 얼마나 돌았나"라서다.
        // 제어 행은 구역·시설 목록과 같은 2행 골격(buildOutputRow)이라,
        // 같은 장치가 어느 화면에서든 같은 모양으로 보인다.
        function _buildDevicePopupHTML(name) {
            return window.AoTMapPopup.buildModalHeader({ name: name, up: true }) +
                   '<div class="aot-bay-popup-pane" data-pane="dmain">' +
                   _buildZoneSkel() + '</div>';
        }

        function _openDeviceModal(uid, deviceUuid, channel, deviceName, onClose) {
            var st = _devicePopupState[uid] || {};
            if (st.popup) { try { st.popup.remove(); } catch (e) {} }

            var popup = _showFacilityCenterOverlay(
                _buildDevicePopupHTML(deviceName || _tr('Device')), uid, deviceUuid);
            _focusMapOn(uid, deviceUuid);
            _devicePopupState[uid] = { popup: popup, deviceUuid: deviceUuid,
                                       channel: channel };
            if (typeof onClose === 'function') { popup.on('close', onClose); }

            var popupEl = popup.getElement();
            var body = popupEl && popupEl.querySelector('.maplibregl-popup-content');

            popup.on('close', function () {
                var d = _devicePopupState[uid];
                if (d && d.popup === popup) { _devicePopupState[uid] = {}; }
            });

            modalFetch('device', deviceUuid, channel)
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    var d = _devicePopupState[uid];
                    if (!data || !data.ok || !d || d.popup !== popup || !body) return;
                    d.detail = data;

                    var titleEl = body.querySelector('.aot-sensor-popup-title');
                    if (titleEl && data.device && data.device.name) {
                        titleEl.textContent = data.device.name;
                    }
                    window.AoTMapPopup.applyStatusDot(body, data.status);

                    _renderDeviceBody(body, uid, data, deviceUuid, channel);

                    _wireUpBtn(body, uid, data.parent, function () {
                        var d2 = _devicePopupState[uid];
                        if (d2 && d2.popup) { try { d2.popup.remove(); } catch (e) {} }
                    });
                })
                .catch(function () {});
        }

        // 한 창의 본문: 이력 → 제어(또는 구성) → 노트.
        // 이력이 맨 위인 이유 — 지난 작동 기록이 곧 "이 장치가 어떻게 돌고
        // 있었나"의 답이라 제어 판단의 근거가 된다. 그래서 제어 행에서는 과거
        // 시간을 따로 나열하지 않는다(아래 시간 슬롯 설명 참조).
        // 복합장치는 자기 가동 이력이 없다 — 안에 든 것들이 각자 갖는다.
        function _renderDeviceBody(body, uid, data, deviceUuid, channel) {
            var pane = body.querySelector('.aot-bay-popup-pane[data-pane="dmain"]');
            if (!pane || !window.AoTMapPopup) return;
            var dev = data.device || {};
            var name = dev.name || '';

            var head = (dev.kind === 'device') ? _tr('Contents') : _tr('Control');
            pane.innerHTML =
                (dev.kind === 'device' ? '' :
                 '<div class="aot-ov-card-title">' + _tr('History') + '</div>' +
                 '<div class="aot-ov-block aot-device-hist">' +
                     '<div class="aot-bay-sensor-chart">' + _buildZoneSkel() + '</div>' +
                 '</div>') +
                '<div class="aot-ov-card-title">' + head + '</div>' +
                '<div class="aot-ov-block aot-device-ctrl">' +
                '</div>' +
                window.AoTNotesBlock.html();

            var host = pane.querySelector('.aot-device-ctrl');
            if (dev.kind === 'device') {
                host.insertAdjacentHTML('beforeend', _buildDeviceChildrenHtml(dev));
                _wireDeviceChildren(host, uid);
            } else {
                host.insertAdjacentHTML('beforeend',
                    _buildDeviceControlHtml(uid, data, deviceUuid, channel));
                _wireDeviceControl(host, uid, dev, deviceUuid, channel,
                                   dev.control_kind);
                // 현재 상태·작동 시간은 여기서 붙인다 — 이것을 빼먹어서
                // 켜 놓은 장치를 열어도 토글이 꺼진 채였고 시간이 멈춰 있었다.
                _wireDeviceStateAndTime(host, uid, deviceUuid, channel);
            }

            window.AoTNotesBlock.wire(pane,
                { targetId: deviceUuid, targetType: 'device', name: name },
                { beforeOpen: function () {
                    var d = _devicePopupState[uid];
                    if (d && d.popup) { try { d.popup.remove(); } catch (e) {} }
                } });

            _loadDeviceHistory(pane, deviceUuid, name);
        }

        // 가동 이력 — 구역·시설 모달과 같은 렌더러(renderOutputHistory)와 같은
        // 엔드포인트를 쓴다. 응답이 올 때까지는 스켈레톤이 자리를 지킨다.
        function _loadDeviceHistory(pane, deviceUuid, name) {
            var chartEl = pane.querySelector('.aot-device-hist .aot-bay-sensor-chart');
            if (!chartEl) return;
            fetch('/api/geo/output/' + encodeURIComponent(deviceUuid) + '/history')
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (j) {
                    if (!pane.isConnected) return;
                    if (!j || !j.ok || !window.AoTSensorLabel ||
                        !window.AoTSensorLabel.renderOutputHistory) {
                        chartEl.innerHTML = window.AoTMapPopup.emptyLine(_tr('No records'));
                        return;
                    }
                    window.AoTSensorLabel.renderOutputHistory(chartEl, j, name, {});
                })
                .catch(function () {
                    chartEl.innerHTML = window.AoTMapPopup.emptyLine(
                        _tr('Failed to load information'));
                });
        }

        // 상태·시간 채우기 — 마커 팝업이 쓰던 로직 그대로다.
        // 상태 판정은 공용 분류기(AoTOutputState.classify)를 쓴다: 'fault'(무응답)를
        // truthy 로 접으면 오프라인 장치가 켜진 것처럼 보이고, pending 은 아직
        // 확정이 아니라 스톱워치를 돌리면 안 된다.
        //
        // **모달이 열려 있는 동안 계속 따라간다.** 한 번만 읽으면, 다른 창이나
        // 스케줄러가 장치를 켜고 꺼도 이 모달은 열던 순간의 상태에 멈춰 있다.
        function _wireDeviceStateAndTime(host, uid, deviceUuid, channel) {
            _syncDeviceState(host, deviceUuid, channel);

            var refreshMs = ((_actLabelState[uid] || {}).refreshMs) || 5000;
            var timer = setInterval(function () {
                if (!host.isConnected) { clearInterval(timer); _detachVis(); return; }
                _syncDeviceState(host, deviceUuid, channel);
            }, refreshMs);

            // 백그라운드 탭에서는 setInterval 이 분당 1회 수준으로 스로틀된다 —
            // 탭을 두 개 띄워 놓고 한쪽에서 켜면 다른 쪽이 한참 옛 상태로 남는다.
            // 돌아오는 순간 바로 한 번 맞춘다.
            function _onVis() {
                if (document.visibilityState !== 'visible') return;
                if (!host.isConnected) { _detachVis(); return; }
                _syncDeviceState(host, deviceUuid, channel);
            }
            function _detachVis() {
                document.removeEventListener('visibilitychange', _onVis);
            }
            document.addEventListener('visibilitychange', _onVis);
        }

        function _syncDeviceState(host, deviceUuid, channel) {
            var tgl = host.querySelector('.aot-device-toggle');
            var durEl = host.querySelector('.aot-act-time');
            var duty = host.querySelector('.aot-device-duty');
            var valEl = host.querySelector('.aot-act-val');

            Promise.all([
                fetch('/outputstate_unique_id/' + deviceUuid + '/' + channel)
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .catch(function () { return null; }),
                fetch('/output_started_at_public/' + deviceUuid + '/' + channel)
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .catch(function () { return null; })
            ]).then(function (res) {
                if (!host.isConnected) return;
                var state = res[0], startData = res[1];
                var cls = window.AoTOutputState
                    ? window.AoTOutputState.classify(state)
                    : { isOn: (state === 'on' || (typeof state === 'number' && state > 0)),
                        isPending: (state === 'pending'), isFault: (state === 'fault'),
                        countsRuntime: (state === 'on' || (typeof state === 'number' && state > 0)) };

                // 서버 시계로 시작 시각을 되짚는다 — 클라이언트 시계가 틀어져
                // 있어도 경과가 어긋나지 않게.
                var startEpoch = null;
                if (startData) {
                    if (startData.started_at_epoch) {
                        startEpoch = startData.started_at_epoch;
                    } else if (startData.elapsed_sec > 0 && startData.server_now_epoch) {
                        startEpoch = startData.server_now_epoch - startData.elapsed_sec;
                    }
                }

                // 사용자가 막 만지고 있는 토글은 건드리지 않는다 — 누른 직후
                // 서버가 아직 옛 값을 주면 눈앞에서 도로 튕긴다(구역 목록 폴링과
                // 같은 규칙).
                if (tgl && !tgl.disabled && document.activeElement !== tgl) {
                    tgl.checked = !!cls.isOn;
                }
                if (tgl) {
                    tgl.classList.toggle('aot-toggle-pending', !!cls.isPending);
                    tgl.classList.toggle('aot-toggle-fault', !!cls.isFault);
                }
                if (duty && typeof state === 'number' &&
                    document.activeElement !== duty) {
                    duty.value = String(Math.round(state));
                    if (valEl) valEl.textContent = Math.round(state) + '%';
                }
                // 시간 칸은 구역·시설과 같은 공용 칸이다 — 갈아 끼우는 규칙도
                // 거기 한 벌뿐이다.
                window.AoTMapPopup.applyTimeSlot(durEl, {
                    countsRuntime: cls.countsRuntime, startEpoch: startEpoch });
            });
        }

        // 제어 행 — 1행 이름+주 제어, 2행 예약 + 설정(시간·듀티).
        // 주 제어는 장치 종류가 정한다: 개폐형은 닫기/정지/열기, PWM 은 듀티
        // 슬라이더, 나머지는 ON/OFF 토글. 셋 다 같은 골격에 얹혀서 목록과
        // 모양이 어긋나지 않는다.
        function _buildDeviceControlHtml(uid, data, deviceUuid, channel) {
            var dev = data.device || {};
            var ck = dev.control_kind || 'on_off';
            var canCtrl = _zoneCanCtrl(uid);
            // 상세 응답이 runtime(경과·마지막 작동)을 이미 들고 오므로 시간
            // 칸은 첫 렌더부터 제 값으로 선다 — 추가 요청이 필요 없다.
            var timeSlot = window.AoTMapPopup.timeSlotHtml({
                outputId: deviceUuid, channel: channel, runtime: data.runtime });
            if (!canCtrl) {
                return window.AoTMapPopup.buildOutputRow({
                    slot: deviceUuid, name: dev.name || '', meta: timeSlot
                });
            }

            var primary, settings = '';
            if (ck === 'value_3way') {
                primary = '<div class="aot-act-3btn">' +
                    '<button type="button" class="aot-act-pbtn" data-act="close">' +
                    _tr('Close') + '</button>' +
                    '<button type="button" class="aot-act-pbtn" data-act="stop">' +
                    _tr('Stop') + '</button>' +
                    '<button type="button" class="aot-act-pbtn" data-act="open">' +
                    _tr('Open') + '</button></div>';
            } else if (ck === 'pwm') {
                // 듀티는 값이 곧 상태다 — 1행에 현재값, 2행에 슬라이더.
                primary = '<span class="aot-act-val">0%</span>';
                settings = '<input type="range" class="aot-act-slider aot-device-duty"' +
                           ' min="0" max="100" step="1" value="0">';
            } else {
                primary = '<label class="btn-toggle aot-act-toggle-right">' +
                    '<input type="checkbox" class="btn-toggle-input aot-device-toggle">' +
                    '<span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>' +
                    '</label>';
                // 시작/종료 예약은 on/off 에만 의미가 있다 — 개폐율·듀티에는
                // "언제부터 언제까지 켬"이라는 구간이 성립하지 않는다.
                if (dev.kind === 'output') {
                    settings = window.AoTMapPopup.scheduleButtonHtml({
                        outputId: deviceUuid, channel: channel,
                        name: dev.name || '' });
                }
            }

            // 2행 왼쪽은 시간 칸 하나다(꺼짐=마지막 작동 / 켜짐=타이머).
            // 예약이 걸려 있으면 그 뒤에 덧붙인다 — 설정 버튼 바로 옆이라
            // "지금 무슨 예약이 걸려 있는가"가 그 버튼의 현재 값으로 읽힌다.
            return window.AoTMapPopup.buildOutputRow({
                slot: deviceUuid,
                name: dev.name || '',
                primary: primary,
                meta: timeSlot + window.AoTMapPopup.nextRunHtml(
                    data.runtime, deviceUuid + '::' + channel),
                settings: settings
            });
        }

        // 복합장치는 그릇이다 — 안에 든 Input/Output 을 세우고, 줄을 누르면 그
        // 장치의 모달로 내려간다(필지 요약의 구역 줄과 같은 문법).
        function _buildDeviceChildrenHtml(dev) {
            var kids = dev.children || [];
            if (!kids.length) {
                return window.AoTMapPopup.emptyLine(_tr('No devices'));
            }
            var label = { input: _tr('Sensors'), output: _tr('Devices') };
            return kids.map(function (c) {
                return '<div class="aot-site-row" data-child-uuid="' +
                       _escZ(c.uuid) + '" data-child-name="' + _escZ(c.name) + '">' +
                       '<span class="aot-site-row-name">' + _escZ(c.name) + '</span>' +
                       '<span class="aot-site-row-state">' +
                       _escZ(label[c.kind] || c.kind) + '</span></div>';
            }).join('');
        }

        function _wireDeviceChildren(host, uid) {
            host.querySelectorAll('.aot-site-row[data-child-uuid]').forEach(function (row) {
                row.addEventListener('click', function () {
                    var d = _devicePopupState[uid];
                    if (d && d.popup) { try { d.popup.remove(); } catch (e) {} }
                    _openDeviceModal(uid, row.dataset.childUuid, '0',
                                     row.dataset.childName || '');
                });
            });
        }

        function _wireDeviceControl(host, uid, dev, deviceUuid, channel, ck) {
            var tgl = host.querySelector('.aot-device-toggle');
            if (tgl) {
                tgl.addEventListener('change', function () {
                    var on = tgl.checked;
                    tgl.disabled = true;
                    if (window.AoTMapLoader && window.AoTMapLoader.toggleDevice) {
                        window.AoTMapLoader.toggleDevice(deviceUuid, on, channel,
                                                         dev.kind);
                    }
                    // 예전에는 아무 갱신도 걸지 않아(aot-map-loader 주석: "wait for
                    // polling") 다음 위젯 주기까지 마커가 옛 상태였다.
                    _refreshOutputStatesAfterCommand(uid);
                    setTimeout(function () { tgl.disabled = false; }, 600);
                });
            }

            if (ck === 'value_3way') {
                host.querySelectorAll('.aot-act-pbtn[data-act]').forEach(function (b) {
                    b.addEventListener('click', function () {
                        var act = b.dataset.act;
                        var val = act === 'open' ? 100 : (act === 'close' ? 0 : null);
                        if (window.AoTMapLoader && window.AoTMapLoader.commandActuator) {
                            window.AoTMapLoader.commandActuator(
                                deviceUuid, act, val, channel, uid);
                        }
                        _refreshOutputStatesAfterCommand(uid);
                    });
                });
            }

            var duty = host.querySelector('.aot-device-duty');
            if (duty) {
                var valEl = host.querySelector('.aot-act-val');
                // 끄는 동안 1행 숫자가 따라 움직여야 어디에 놓았는지 보인다.
                duty.addEventListener('input', function () {
                    if (valEl) valEl.textContent = duty.value + '%';
                });
                duty.addEventListener('change', function () {
                    if (window.AoTMapLoader && window.AoTMapLoader.commandActuator) {
                        window.AoTMapLoader.commandActuator(
                            deviceUuid, 'goto', parseFloat(duty.value), channel, uid);
                    }
                    _refreshOutputStatesAfterCommand(uid);
                });
            }

            var setBtn = host.querySelector('.aot-output-settings');
            if (setBtn && window.AoTMapPopup.openOutputSchedule) {
                setBtn.addEventListener('click', function (e) {
                    e.stopPropagation();
                    window.AoTMapPopup.openOutputSchedule({
                        shell:    _showFacilityCenterOverlay,
                        outputId: setBtn.dataset.outputId,
                        channel:  parseInt(setBtn.dataset.channel || '0', 10),
                        name:     setBtn.dataset.outputName || ''
                    });
                });
            }
        }

        // ── Site(필지) 요약 모달 ───────────────────────────────────────────────
        // 줌 아웃 화면에서 처음 만나는 계층이 site 인데, 예전 팝업은 이름·면적·
        // 메모 한 줄이라 "여기 들어가 볼 필요가 있나"를 답하지 못했다. 하위
        // 구역·시설을 한 눈에 세우고, 줄을 누르면 그 계층의 기존 모달로 넘긴다.
        //
        // 탭을 두지 않는다 — 이 모달은 머무는 곳이 아니라 갈 곳을 고르는 곳이다.
        var _sitePopupState = {};

        function _buildSitePopupHTML(siteName) {
            // 필지 위에는 개별 도형이 아니라 "이 지도의 필지 목록"이 있다 —
            // 계층을 끝까지 거슬러 올라갈 수 있어야 길을 잃지 않는다.
            //
            // 탭 키·순서는 구역·시설과 **같다**. 가운데만 다르다 —
            // 구역은 [환경·제어], 필지는 [구성]이다.
            //
            // **필지에 [환경·제어]를 두지 않는다.** 근거는 서버에 이미 적혀
            // 있다(`site_summary._child_entry` 의 `'control': None` —
            // "자동제어 연동은 시설별로 알 수가 없다"). 필지는 그보다 한 단계
            // 더 위라 근거가 더 없고, 제어는 구역·시설에서 한다.
            var P = window.AoTMapPopup;
            return P.buildModalHeader({ name: siteName || _tr('Site'), up: true }) +
                   P.buildSectionNav('overview', [
                       { key: 'overview', label: 'Overview' },
                       { key: 'envctl',   label: 'Environment & Control' },
                       { key: 'about',    label: 'About' }
                   ]) +
                   P.sectionPane('overview', 'overview', _buildZoneSkel()) +
                   P.sectionPane('envctl',   'overview', '') +
                   P.sectionPane('about',    'overview', '');
        }

        // 필지 요약의 마지막 응답을 들고 있는다. 서버가 30초 캐시를 갖고 있어도
        // **첫 그림까지 왕복 한 번**이 남아 모달이 스켈레톤으로 먼저 뜬다 —
        // 콜드 계산은 로컬 실측 600~700ms 다. 캐시가 있으면 즉시 그리고 응답이
        // 오면 조용히 갈아 끼운다(값이 30초쯤 낡아 보이는 것보다 낫다).
        var _siteSummaryCache = {};

        // 상태 → 사람이 읽을 한 마디. 숫자를 함께 적는 이유: "이상"만 있으면
        // 몇 대가 문제인지 알려고 결국 들어가 봐야 한다.
        function _siteStateText(child) {
            var iss = child.issues || {};
            var sen = child.sensors || {};
            if (child.status === 'empty')  return { text: _tr('No devices'), cls: '' };
            if (iss.comm_fault)            return { text: _tr('Offline') + ' ' + iss.comm_fault, cls: 'is-fault' };
            if (iss.battery_low)           return { text: _tr('Battery') + ' ' + iss.battery_low, cls: 'is-warning' };
            if (sen.total && sen.valid < sen.total) {
                return { text: sen.valid + '/' + sen.total, cls: 'is-warning' };
            }
            return { text: _tr('Normal'), cls: '' };
        }

        function _siteRowHTML(child) {
            var rep = child.rep;
            var valTxt = '—', valCls = ' is-blank', style = '';
            if (rep && rep.value != null) {
                valTxt = rep.value + (rep.unit || '');
                valCls = '';
                // 지도 칩과 같은 밴드 색. ranges 는 구역엔 없으므로 기본 경계를
                // 쓴다(시설별 sensor_ranges 는 시설 모달이 따로 적용한다).
                if (window.AoTMapSensorLabels && window.AoTMapSensorLabels.bandColor) {
                    var c = window.AoTMapSensorLabels.bandColor(rep.key, +rep.value, null, rep.unit);
                    if (c) {
                        style = ' style="background:' + c + ';color:' +
                                window.AoTMapSensorLabels.textOn(c) + '"';
                    }
                }
            }
            var st = _siteStateText(child);
            // 이름 없는 도형이 실제로 있다(geo/design 에서 그렸지만 시설 등록이
            // 안 된 경우). 서버는 그때 빈 이름을 주고, 무엇을 보일지는 여기서
            // 정한다 — uuid 를 보이면 사람이 읽을 수 없는 줄이 된다.
            var nm = child.name || _tr('Unnamed');
            return '<div class="aot-site-row" data-kind="' + _escZ(child.kind) +
                       '" data-uuid="' + _escZ(child.uuid) +
                       '" data-name="' + _escZ(nm) + '">' +
                       '<span class="aot-site-row-name">' + _escZ(nm) + '</span>' +
                       '<span class="aot-site-row-val' + valCls + '"' + style + '>' +
                       _escZ(valTxt) + '</span>' +
                       '<span class="aot-site-row-state ' + st.cls + '">' +
                       _escZ(st.text) + '</span>' +
                   '</div>';
        }

        function _buildSiteSummaryHTML(data) {
            var site = data.site || {};
            var counts = site.counts || {};
            var html = '';

            // 개요 카드(면적·구역·시설·장치·작물)는 **[개요] 탭**이 갖는다.
            // 필지에서 "지금 어떤가" 를 묻는 화면에 규모 숫자가 맨 위에 있으면,
            // 정작 봐야 할 것(무엇이 들어 있고 오늘 무슨 일이 있나)이 아래로
            // 밀린다 — 그 숫자는 한 번 보면 잘 안 바뀐다.

            // 구성(구역·시설)은 **[현황] 안에** 둔다 — 필지에서 "지금 어떤가" 를
            // 묻는 사람이 가장 먼저 보는 것이 "무엇이 들어 있나" 다.
            // 구역과 시설은 카드 둘로 나눈다(성격이 다르다: 땅과 구조물).
            html += _buildSiteChildrenHTML(data);

            var today = data.today || {};
            html += '<div class="aot-ov-card-title">' + _tr('Today') + '</div>' +
                '<div class="aot-ov-block">' +
                '<div class="aot-site-tiles">' +
                    // 일정은 타일(숫자)에서 뺐다 — 아래 목록이 같은 것을
                    // 더 정확히 말한다. 숫자는 '오늘' 창이라 목록('지금부터')과
                    // 어긋나, 대지가 0인데 구역엔 내일 일이 있는 상태가 났다.
                    _siteTileHTML('advice', today.advice_open || 0, _tr('Advice')) +
                    _siteTileHTML('offline', today.offline_devices || 0, _tr('Offline'),
                                  (today.offline_devices ? ' is-fault' : '')) +
                '</div>';
            if (today.advice_latest && today.advice_latest.title) {
                html += '<div class="aot-ov-trend">' +
                        _escZ(today.advice_latest.title) + '</div>';
            }
            html += '</div>';

            // 기록 — 예정과 노트가 **한 블록**이다(구역·식생과 같은 빌더).
            // 목록은 /site summary 의 것을 버리고 블록이 /notes/target 으로
            // 직접 채운다 — 그래야 날짜·첨부 썸네일까지 다른 창과 같은 모양이
            // 된다. 예전에는 여기만 목록을 직접 그려서 노트로 들어가는 문이
            // 아예 없었다(필지에 적어 둘 것이 가장 많은데도).
            html += window.AoTMapPopup.buildRecordBlock(data.schedule);
            return html;
        }

        /**
         * [구성] — 하위 **구역**과 **시설**을 카드 둘로 나눠 낸다.
         *
         * 종류를 가르는 이유: 구역은 땅이고 시설은 구조물이라 성격이 다르다.
         * 한 목록에 섞이면 이름만 보고 어느 쪽인지 알아야 하고, 제목("구역
         * 상태")은 절반만 맞는 말이 된다.
         *
         * **장치가 없는 항목도 행으로 낸다.** 예전에는 이름을 쉼표로 이어붙인
         * 한 줄이라 눌러도 아무 일이 없었다 — 그 항목으로 내려갈 방법이 아예
         * 없었다는 뜻이다. 상태 칸은 `_siteStateText` 가 이미 "장치 없음" 을
         * 낼 줄 안다.
         *
         * bay(시설 안 구역)는 여기 끌어올리지 않는다 — 필지에서 두 단계 아래이고,
         * 시설 8동 × bay 6개면 목록이 무너진다. 시설 행을 누르면 시설 모달이
         * 열리고 거기서 본다.
         */
        /** 개요 카드 — 규모 숫자. [개요] 탭이 쓴다. */
        function _siteOverviewCardHTML(site, counts) {
            return '<div class="aot-ov-block">' +
                '<div class="aot-ov-row"><span>' + _tr('Area') + '</span><span>' +
                (site.area_m2 != null ? (+site.area_m2).toLocaleString() + ' m²' : '—') +
                '</span></div>' +
                '<div class="aot-ov-row"><span>' + _tr('Zones') + '</span><span>' +
                (counts.zones || 0) + '</span></div>' +
                '<div class="aot-ov-row"><span>' + _tr('Facilities') + '</span><span>' +
                (counts.facilities || 0) + '</span></div>' +
                '<div class="aot-ov-row"><span>' + _tr('Devices') + '</span><span>' +
                (counts.devices || 0) + '</span></div>' +
                // 작물은 **숫자로만** 낸다. 아래 구역 행(이름|값|상태)에
                // 작물명을 이어붙이면 한 열이 두 가지를 말하게 되고 열 간격이
                // 틀어진다 — 필지에서 알고 싶은 것은 규모 감각이다.
                (counts.plots
                  ? '<div class="aot-ov-row"><span>' + _tr('Growing now') +
                    '</span><span>' +
                    _tr('%(kinds)s kinds · %(plots)s plots')
                      .replace('%(kinds)s', String(counts.subjects || 0))
                      .replace('%(plots)s', String(counts.plots)) +
                    '</span></div>'
                  : '') +
                '</div>';
        }

        function _buildSiteChildrenHTML(data) {
            var kids = data.children || [];
            var zones = kids.filter(function (c) { return c.kind !== 'facility'; });
            var facs  = kids.filter(function (c) { return c.kind === 'facility'; });

            // **빈 카드는 내지 않는다.** 구역만 있는 필지, 시설만 있는 필지가
            // 둘 다 정상이다 — 없는 쪽에 "아직 없습니다" 를 세워 두면 화면 절반이
            // 빈 칸을 설명하는 데 쓰이고, 사용자는 무언가 빠졌다고 읽는다.
            function _card(title, list) {
                if (!list.length) return '';
                var html = '<div class="aot-ov-card-title">' + _escZ(title) +
                           ' (' + list.length + ')</div>' +
                           '<div class="aot-ov-block">';
                // 상태가 있는 것을 먼저 — 빈 것이 위에 오면 "볼 것이 없는
                // 필지" 처럼 읽힌다.
                var live = list.filter(function (c) { return c.status !== 'empty'; });
                var idle = list.filter(function (c) { return c.status === 'empty'; });
                return html + live.concat(idle).map(_siteRowHTML).join('') + '</div>';
            }
            var cards = _card(_tr('Zones'), zones) + _card(_tr('Facilities'), facs);
            // 둘 다 없으면 그 사실을 한 번만 말한다. 필지를 막 그리고 아직
            // 아무것도 안 넣은 상태가 정상이므로, 오류처럼 보이면 안 된다.
            return cards || ('<div class="aot-ov-block"><div class="aot-site-empty">' +
                             _tr('Nothing to show yet') + '</div></div>');
        }

        /**
         * [설정] — 설명과 읽기 정보.
         *
         * 설명 블록은 **시설 모달과 같은 공용 컴포넌트**다
         * (`AoTMapPopup.buildDescriptionHtml`). 여기서 다시 적으면 [편집] 자리나
         * [취소]/[저장] 순서가 화면마다 갈린다.
         *
         * 도형 자체(경계·이름)는 여기서 고치지 않는다 — 그것은 geo/design 의
         * 일이고, 이 화면은 운영이다(구획 모달과 같은 분담).
         */
        /**
         * [개요] — 규모 숫자(면적·구역·시설·장치·작물).
         *
         * **설명 카드는 두지 않는다.** 한때 여기 있었는데, 필지에서 사람이
         * 적는 글은 노트가 받는다([현황] 탭) — 설명과 노트 둘을 두면 "어디에
         * 적어야 하나" 를 쓰기 전에 답해야 하고, 그 구분은 저장 위치이지
         * 사람이 아는 구분이 아니다(같은 이유로 예정/노트 입구도 하나로 모았다).
         *
         * 서버(`/api/geo/shape/<uuid>/description`)와 저장 자리(`meta_json`)는
         * 남겨 둔다 — 구역·시설이 같은 것을 쓰고, 되살릴 때 다시 만들 이유가 없다.
         */
        function _buildSiteAboutHTML(data) {
            var site = data.site || {};
            return _siteOverviewCardHTML(site, site.counts || {});
        }

        function _siteTileHTML(key, num, label, extraCls) {
            return '<div class="aot-site-tile" data-tile="' + key + '">' +
                       '<div class="aot-site-tile-num' + (extraCls || '') + '">' +
                       num + '</div>' +
                       '<div class="aot-site-tile-label">' + _escZ(label) + '</div>' +
                   '</div>';
        }

        // 줄을 누르면 그 계층의 기존 모달로 넘긴다. site 모달은 닫는다 —
        // 모달 위에 모달을 쌓으면 뒤로 가기가 어디로 가는지 알 수 없다.
        /** 필지 모달의 탭 전환 — 구역 모달과 같은 규약(`data-sec`/`data-pane`). */
        function _wireSiteRows(uid, body) {
            Array.prototype.forEach.call(
                body.querySelectorAll('.aot-site-row'), function (row) {
                row.addEventListener('click', function () {
                    var kind = row.dataset.kind;
                    var uuid = row.dataset.uuid;
                    var name = row.dataset.name;
                    var st = _sitePopupState[uid];
                    if (st && st.popup) { try { st.popup.remove(); } catch (e) {} }
                    if (kind === 'zone') {
                        _openZonePopup(uid, uuid, name);
                    } else {
                        _openFacilityFromShape(uid, uuid);
                    }
                });
            });
        }

        // 시설 줄 → 시설 모달. site 요약은 도형(shape) uuid 를 들고 있는데
        // 시설 모달은 GeoFacility uuid + bay id 로 열린다. 그 짝은 이미 받아 둔
        // 시설 목록(_actLabelState.facilities)에 있다.
        //
        // bay id 는 bays 컬럼이 아니라 AoTMapBay.slices() 로 얻는다 — 지도의 bay
        // 칩이 쓰는 것과 같은 목록이어야, 줄을 눌러 연 모달과 칩을 눌러 연 모달이
        // 같은 구역을 가리킨다(bay 1개 시설은 bays 가 비어 있고 slices 가 하나를
        // 만들어 낸다).
        // 도형 uuid → 시설 uuid. 시설 모달은 시설 uuid 로 조회하므로 호버
        // 예열도 이 변환을 거쳐야 한다.
        function _facilityUuidOfShape(uid, shapeUuid) {
            var facs = (_actLabelState[uid] || {}).facilities || [];
            for (var i = 0; i < facs.length; i++) {
                if (facs[i] && facs[i].shape_uuid === shapeUuid) {
                    return facs[i].unique_id;
                }
            }
            return null;
        }

        function _openFacilityFromShape(uid, shapeUuid) {
            var facs = (_actLabelState[uid] || {}).facilities || [];
            var hit = null;
            for (var i = 0; i < facs.length; i++) {
                if (facs[i] && facs[i].shape_uuid === shapeUuid) { hit = facs[i]; break; }
            }
            if (!hit) return;
            var slices = (window.AoTMapBay && window.AoTMapBay.slices(hit)) || [];
            _openBayPopup(uid, hit.unique_id, slices.length ? slices[0].id : null);
        }

        function _openSitePopup(uid, siteUuid, siteName) {
            var st = _sitePopupState[uid] || {};
            if (st.popup) { try { st.popup.remove(); } catch (e) {} }

            var popup = _showFacilityCenterOverlay(
                _buildSitePopupHTML(siteName), uid, siteUuid);
            _focusMapOn(uid, siteUuid);
            _sitePopupState[uid] = { popup: popup, siteUuid: siteUuid };

            var popupEl = popup.getElement();
            var body = popupEl && popupEl.querySelector('.maplibregl-popup-content');
            window.AoTMapPopup.wireSectionTabs(popupEl);
            // [환경·제어]는 요약과 **다른 조회**(장치 인벤토리)라 따로 붙인다.
            // 구획 모달과 같은 방식이다(`_attachPlotControl`).
            _attachSiteControl(uid, popup, body, siteUuid);

            popup.on('close', function () {
                var s = _sitePopupState[uid];
                if (s && s.popup === popup) {
                    if (s.pollTimer) { clearInterval(s.pollTimer); }
                    _sitePopupState[uid] = {};
                }
            });

            function _render(data) {
                var s = _sitePopupState[uid];
                if (!s || s.popup !== popup) return;
                var pane = body && body.querySelector(
                    '.aot-bay-popup-pane[data-pane="overview"]');
                if (!pane) return;
                pane.innerHTML = _buildSiteSummaryHTML(data);

                // [개요]도 **여기서 함께** 채운다. 탭을 누를 때 그리면 첫 클릭에
                // 빈 화면이 한 번 보이고, 폴링이 돌아오는 30초마다 그 상태로
                // 되돌아간다(pane 이 다시 비므로).
                var aboutPane = body.querySelector(
                    '.aot-bay-popup-pane[data-pane="about"]');
                if (aboutPane) aboutPane.innerHTML = _buildSiteAboutHTML(data);

                // 구성 목록은 [현황] 안에 있다 — 같은 pane 이므로 여기서 배선한다.
                _wireSiteRows(uid, pane);
                // 예정을 만드는 자리는 **노트 하나**다 — 계층마다 별도 폼을
                // 두면 사용자가 쓰기 전에 종류를 고르는 옛 방식으로 되돌아간다.
                // 필지 모달도 30초마다 다시 그린다 — 캐시로 깜빡임을 막는다.
                s._notesCache = s._notesCache || {};
                // 컨테이너다 — 그 안(구역·구획·시설·장치)의 노트까지.
                // 필지 자체 노트는 실측 0건이었다(그 아래는 16건).
                window.AoTNotesBlock.wire(pane,
                    { targetId: siteUuid, targetType: 'GeoShape',
                      name: (data.site && data.site.name) || siteName || '' },
                    { descendants: true, cache: s._notesCache,
                      beforeOpen: function () {
                          var s2 = _sitePopupState[uid];
                          if (s2 && s2.popup) { try { s2.popup.remove(); } catch (e) {} }
                      } });
                var titleEl = body.querySelector('.aot-sensor-popup-title');
                if (titleEl && data.site && data.site.name) {
                    titleEl.textContent = data.site.name;
                }
                window.AoTMapPopup.applyStatusDot(
                    body, data.site && data.site.status);
            }

            // 지난 응답이 있으면 먼저 그린다 — 스켈레톤을 보며 기다리는 대신
            // 값이 바로 뜨고, 새 응답이 오면 조용히 갈아 끼운다.
            if (_siteSummaryCache[siteUuid]) { _render(_siteSummaryCache[siteUuid]); }

            function _load() {
                modalFetch('site', siteUuid)
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .then(function (data) {
                        if (!data || !data.ok) return;
                        _siteSummaryCache[siteUuid] = data;
                        _render(data);
                    })
                    .catch(function () {});
            }
            _load();

            // 필지 목록으로 올라가기 — 필지 위에는 개별 도형이 없다.
            _wireUpBtn(body, uid, { kind: 'sitelist', name: _tr('Site list') },
                function () {
                    var s2 = _sitePopupState[uid];
                    if (s2 && s2.popup) { try { s2.popup.remove(); } catch (e) {} }
                });
            // 서버 캐시가 30초라 그보다 자주 물어봐야 값이 새로 오지 않는다.
            _sitePopupState[uid].pollTimer = setInterval(_load, 30000);
        }
        // ── End Site modal ─────────────────────────────────────────────────────

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
                _fetchAndUpdateActLabels(uid, facilityUuid, true);   // 제어 직후 = 캐시 우회
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

        // Distance from (lng,lat) to a facility's footprint: 0 if the point falls
        // inside the polygon, otherwise the distance to the nearest edge (works for
        // both open and closed rings — same ray-casting/wraparound approach as
        // _ringContainsPoint below). Falls back to center-point distance when no
        // footprint is available. Using the footprint instead of a single center
        // point matters for long/large facilities (e.g. a 3-span connected
        // greenhouse) whose centroid can sit far from a point that is still well
        // inside the building's outline.
        function _facilityDistToPoint(fac, lng, lat) {
            var ring = _facilityFootprintRing(fac);
            if (ring && ring.length >= 3) {
                if (_ringContainsPoint([lng, lat], ring)) return 0;
                var best = Infinity;
                for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
                    var ax = ring[j][0], ay = ring[j][1];
                    var bx = ring[i][0], by = ring[i][1];
                    var dx = bx - ax, dy = by - ay;
                    var lenSq = dx * dx + dy * dy;
                    var t = lenSq > 0
                        ? Math.max(0, Math.min(1, ((lng - ax) * dx + (lat - ay) * dy) / lenSq))
                        : 0;
                    var px = ax + t * dx, py = ay + t * dy;
                    var d = Math.sqrt((px - lng) * (px - lng) + (py - lat) * (py - lat));
                    if (d < best) best = d;
                }
                return best;
            }
            var c = _facilityCenter_act(fac);
            if (!c) return Infinity;
            var dLng = c[0] - lng, dLat = c[1] - lat;
            return Math.sqrt(dLng * dLng + dLat * dLat);
        }

        // Poll period comes from opts via _runtimePollSeconds — no separate
        // refreshSeconds argument, so the caller cannot pick a rate that disagrees
        // with the fitting sensor labels reading the same /runtime response.
        function _attachActuatorLabels(uid, facilities, opts, map) {
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
                // **시설 하나에 칩 하나.** 구역이 여럿이면 첫 구역 자리에 하나만
                // 두고 이름은 시설명이다.
                //
                // 구역마다 칩을 두면 서로를 덮는다 — 구역 중심이 8.4m 인 시설이
                // 있는데(폭 7m·6동을 둘로 나눈 것) 줌 17 에서 그 거리는 30px
                // 남짓이라 칩 하나 폭도 안 된다. 겹칠 때만 접는 방법도 있지만,
                // 그러면 줌을 만질 때마다 칩 개수가 바뀌어 지도가 요동친다.
                //
                // 구역으로 들어가는 길은 **시설 모달의 구역 전환 줄**이다
                // (`aot-bay-switch`). 어차피 그 경로로 들어가므로 지도에 구역을
                // 다 늘어놓을 이유가 없다.
                var _multiBay = bSlices.length > 1;
                (_multiBay ? bSlices.slice(0, 1) : bSlices).forEach(function (sl) {
                    var bPos = window.AoTMapBay.centerLngLat(fac, sl);
                    if (!bPos) return;
                    var bEl = document.createElement('div');
                    bEl.className = 'aot-sensor-map-marker aot-sensor-label-clickable aot-bay-chip';
                    bEl.dataset.facilityId = fac.unique_id;
                    bEl.dataset.bayId = sl.id;
                    // 구역이 여럿이라 하나로 합친 칩인가 — 라벨 컨트롤·진단이
                    // 이 표식으로 "이 시설은 구역이 더 있다" 를 안다.
                    if (_multiBay) {
                        bEl.dataset.bayRollup = String(bSlices.length);
                    }
                    // 2행 라벨: 1행 = 구역명, 2행 = 대표 측정값 (폴링 후 갱신).
                    // 2행은 빈 채로 만든다 — 값이 오기 전이나 아예 없는 시설에서
                    // 자리표시자를 그리면 이름만 있는 칩이 두 줄 높이를 차지한다
                    // (CSS `.aot-bay-chip-val:empty { display:none }` 가 접는다).
                    bEl.innerHTML =
                        '<div class="aot-bay-chip-name">' +
                        _escAct(_multiBay ? (fac.name || sl.name || sl.id)
                                          : (sl.name || sl.id)) + '</div>' +
                        '<div class="aot-bay-chip-val"></div>';
                    bEl.style.fontSize = ctrlLabelEm + 'em';
                    bEl.style.transform = 'none';
                    // Bay chips attach asynchronously, well after the label toolbar's
                    // saved-state seeding runs — apply the current facility-label
                    // hidden state at creation time so a pre-hidden chip doesn't flash
                    // visible before the next retry timer catches it.
                    if (_uidInstTop && _uidInstTop._hiddenLabels && _uidInstTop._hiddenLabels.facility) {
                        bEl.classList.add('aot-type-hidden');
                    }
                    // 시설(구역) 칩도 공용 z-order + "고른 라벨을 앞으로".
                    // CSS 에 z-index:6 이 박혀 있던 것을 LABEL_Z.facility 로 옮겼다.
                    // **자기 종류로 새긴다.** 예전에는 'facility' 로 새겨져
                    // 시설 라벨과 한 몸이었다 — 줌 게이트·쌓임·충돌이 전부 시설
                    // 것을 따랐고, `LABEL_ZOOM_GATED.bay` 를 등록해도 아무 일이
                    // 없었다(그 값을 읽는 요소가 없으니까).
                    // 줌 임계는 여전히 하나(label_min_zoom)라 **시설과 같은
                    // 축척에서 함께 접힌다** — 등록만 자기 이름으로 바뀐 것이다.
                    var _bRestore = _uidInstTop
                        ? _wireLabelStacking(_uidInstTop, bEl, 'bay') : null;
                    // 호버 예열 — 지도에서 시설 모달을 여는 실제 과녁이 이 칩이다.
                    // 도형(facilities-fill) 호버만으로는 칩 위에 마우스가 올라간
                    // 경우를 못 잡는다(칩은 DOM 이라 캔버스 이벤트가 안 온다).
                    bEl.addEventListener('mouseenter', function () {
                        warmModal('facility', fac.unique_id);
                    });
                    bEl.addEventListener('click', function (ev) {
                        ev.stopPropagation();
                        if (_uidInstTop && _bRestore) {
                            _uidInstTop._pinLabelToFront(bEl, _bRestore);
                        }
                        var _bp = _openBayPopup(uid, fac.unique_id, sl.id);
                        if (_bp && _bp.on && _uidInstTop) {
                            _bp.on('close', function () { _uidInstTop._unpinLabel(bEl); });
                        }
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

            // Polling (output status). Shared start/restart so the live settings-modal
            // setter below (output_update_interval) doesn't duplicate this logic.
            function _startActuatorPolling(ms) {
                var st = _actLabelState[uid];
                if (!st) return;
                if (st.pollTimer) clearInterval(st.pollTimer);
                st.refreshMs = ms;
                st.pollTimer = setInterval(function () {
                    if (document.hidden) return;
                    // 시설 수만큼 /runtime 을 부르는 가장 무거운 폴러다 —
                    // 화면 밖 지도에서는 통째로 쉰다.
                    if (!_isWidgetVisible(window.AoTWidgetInstances[uid])) return;
                    var st2 = _actLabelState[uid];
                    if (!st2) return;
                    st2.facilities.forEach(function (fac) { _fetchAndUpdateActLabels(uid, fac.unique_id); });
                }, ms);
            }
            // One /runtime fetch feeds BOTH the actuator on/off chip (output) and the
            // bay's representative sensor-value chip (input) — see
            // _fetchAndUpdateActLabels — so the period comes from the shared
            // _runtimePollSeconds, the same value the fitting sensor labels use.
            // The 5s floor is unchanged; AoTFacilityRuntime's 8s TTL is what actually
            // bounds the network rate (~1 req / 10s / facility, measured).
            function _actuatorPollMs() {
                return Math.max(5, _runtimePollSeconds(opts)) * 1000;
            }
            _startActuatorPolling(_actuatorPollMs());

            // Expose a live setter for output_update_interval/input_update_interval
            // (settings-modal live-apply): re-derive from current opts (same object
            // reference the modal writes into before calling this) and restart, no
            // re-attach.
            if (_uidInstTop) {
                _uidInstTop._setActuatorRefreshInterval = function () {
                    _startActuatorPolling(_actuatorPollMs());
                };
            }
        }

        // force=true: 8초 TTL 캐시를 건너뛴다. 제어 **직후** 갱신에는 반드시 필요하다 —
        // 캐시를 그대로 쓰면 방금 켠 장치가 최대 8초간 옛 상태로 보인다. 프로바이더가
        // 이 옵션을 처음부터 그 용도로 두고 있었는데(aot-facility-runtime.js 주석)
        // 정작 쓰는 곳이 없었다.
        function _fetchAndUpdateActLabels(uid, facilityUuid, force) {
            // 공용 런타임 프로바이더로 요청 통합 — 센서 라벨 폴러와 동일
            // /runtime 을 공유해 저사양(Pi) 스레드 풀 포화를 막는다.
            var _rt = window.AoTFacilityRuntime
                ? window.AoTFacilityRuntime.get(facilityUuid, { force: !!force })
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
                    // 값이 그대로면 손대지 않는다(`_setHtmlIfChanged` 주석).
                    if (!_setHtmlIfChanged(body, window.AoTMapPopup.buildActuatorTabs(
                            activeCat, _ACT_CATS, states, canCtrl2, st._lastCmd || {},
                            _actKindToCat, savedOrder2))) return;
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
        // repKey: 사용자가 시설 [현황]에서 지정한 대표 측정. 지금 값을 못 내면
        // 지정을 무시하고 우선순위로 물러선다(서버 _pick_rep 과 같은 규칙).
        //
        // **실외는 평균에 넣지 않는다.** 칩은 시설·구역 위에 앉아 "여기가 지금
        // 어떤가" 를 한 숫자로 답하는 자리인데, 기상대를 섞으면 그 숫자가
        // **안팎의 평균**이 된다 — 겨울에 안 25°C · 밖 -5°C 면 칩은 10°C 라고
        // 말하고, 그 값은 어느 곳도 가리키지 않는다. 에러도 없고 숫자도
        // 그럴듯해서 조용하다.
        //
        // 거르는 것은 여기 한 곳이다 — 부르는 쪽(시설 칩·구역 칩)이 각자
        // 기억하게 두면 새 호출부가 생길 때마다 다시 새는 자리가 된다.
        // 구역 칩은 이미 `filterSensors` 를 지나므로 두 번 걸러질 뿐 값은 같다.
        function _sensorSummary(sensors, repKey) {
            var byKey = {};
            (sensors || []).filter(function (s) {
                return !window.AoTMapBay || window.AoTMapBay.isIndoor(s);
            }).forEach(function (s) {
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
            if (repKey && byKey[repKey]) {
                primary = repKey;
            } else {
                for (var i = 0; i < _SENSOR_SUM_PRIORITY.length; i++) {
                    if (byKey[_SENSOR_SUM_PRIORITY[i]]) { primary = _SENSOR_SUM_PRIORITY[i]; break; }
                }
            }
            if (!primary) primary = keys[0];
            var e2 = byKey[primary];
            return { key: primary, avg: e2.sum / e2.n, unit: e2.unit };
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

            var sum = _sensorSummary(st.sensorsByFac[facilityUuid],
                                     _facilityRepKey(uid, facilityUuid));
            if (!sum) { sChip.style.display = 'none'; return; }

            var dec = window.AoTSensorLabel ? window.AoTSensorLabel.defaultDecimals(sum.key) : 1;
            sChip.textContent = (sum.key === 'VPD' ? 'VPD ' : '') +
                                sum.avg.toFixed(dec) + (sum.unit || '');
            sChip.style.display = '';

            // Band color of the representative (averaged) value
            if (window.AoTMapSensorLabels && window.AoTMapSensorLabels.bandColor) {
                var ranges = _facilityRanges_act(uid, facilityUuid);
                var color = window.AoTMapSensorLabels.bandColor(sum.key, sum.avg, ranges, sum.unit);
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
                    // 값이 그대로면 손대지 않는다(`_setHtmlIfChanged` 주석).
                    // 센서 값은 자주 바뀌지만 **표시 자릿수까지 같은 사이클**이
                    // 흔하다 — 그때 갈아끼우면 깜빡임만 남는다.
                    _setHtmlIfChanged(body, window.AoTMapPopup.buildSensorTabs(
                        activeKey, st.sensorsByFac[facilityUuid] || []));
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
            // 다른 모달과 같이 그 시설을 화면에 들인다(도형 uuid 로 찾는다).
            var _fRow = null, _fList = (st.facilities || []);
            for (var _fi = 0; _fi < _fList.length; _fi++) {
                if (_fList[_fi] && _fList[_fi].unique_id === facilityUuid) { _fRow = _fList[_fi]; break; }
            }
            var _facFocus = (_fRow && _fRow.shape_uuid) || facilityUuid;
            _focusMapOn(uid, _facFocus);
            (function () {
                var _inst = window.AoTWidgetInstances[uid];
                if (!_inst || !_facFocus) return;
                // 도형은 **도형 uuid**, 라벨(구역 칩)은 **시설 uuid** 로
                // 달려 있다 — 둘이 다르므로 둘 다 얹는다.
                [_facFocus, facilityUuid].forEach(function (u) {
                    if (u) _setFocus(_inst, uid, String(u), 'modal', true);
                });
                if (popup && popup.on) {
                    popup.on('close', function () {
                        [_facFocus, facilityUuid].forEach(function (u) {
                            if (u) _setFocus(_inst, uid, String(u), 'modal', false);
                        });
                    });
                }
            })();

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
                            // 도킹 셸로 연다 — 이 자리만 옛 중앙 모달로 남아 있었다.
                            window.AoTSensorLabel.openPopup(sensors[i], {
                                modal: true,
                                shell: _showFacilityCenterOverlay,
                                shellUid: uid
                            });
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
                var sum = _sensorSummary(
                    window.AoTMapBay.filterSensors(sensors, bm.bayId),
                    _facilityRepKey(uid, facilityUuid));
                if (!sum) {
                    // 값이 없으면 2행을 비운다 — '—' 를 남기면 이름만 있는 칩이
                    // 계속 두 줄 높이를 차지해 지도를 가린다(:empty 로 접힌다).
                    valEl.textContent = '';
                    bm.el.style.background = '';
                    bm.el.style.color = '';
                    return;
                }
                var dec = window.AoTSensorLabel ? window.AoTSensorLabel.defaultDecimals(sum.key) : 1;
                valEl.textContent =
                    (sum.key === 'VPD' ? 'VPD ' : '') +
                    sum.avg.toFixed(dec) + (sum.unit || '');
                if (window.AoTMapSensorLabels && window.AoTMapSensorLabels.bandColor) {
                    var color = window.AoTMapSensorLabels.bandColor(sum.key, sum.avg, ranges, sum.unit);
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
            // 베이는 바가 하나 더 많다 — 이 탭에 들어설 내용이 그만큼 길다.
            var _skel = window.AoTMapPopup.skeleton(['w60', 'w80', 'w40', 'w80']);

            // 구역 전환 줄 — **구역이 둘 이상인 시설에서만.**
            //
            // 이 모달은 구역 하나를 다루고, 다른 구역으로 가는 길이 지도의
            // 구역 칩뿐이었다. 그런데 그 칩들은 서로 겹쳐서(구역 중심이 8.4m 인
            // 시설이 있다) 이제 하나로 접힌다 — 접는 순간 나머지 구역에 닿을
            // 방법이 사라지므로, 그 길을 여기 먼저 만든다.
            var _allSlices = fac ? window.AoTMapBay.slices(fac) : [];
            var _bayNav = '';
            if (_allSlices.length > 1) {
                _bayNav = '<div class="aot-act-tabs-nav aot-bay-switch">';
                _allSlices.forEach(function (sl2) {
                    _bayNav += '<button type="button" class="aot-act-tab-btn' +
                               (sl2.id === bayId ? ' active' : '') +
                               '" data-bay-switch="' + _escAct(sl2.id) + '">' +
                               _escAct(sl2.name || sl2.id) + '</button>';
                });
                _bayNav += '</div>';
            }

            // 마지막 탭은 **'개요'** 다(2026-08-26 되돌림). 이 탭이 담는 것은
            // 시설의 기초 정보 — 사진·크기·면적·용적·설명이고, 편집은 그 옆에
            // 붙은 버튼 둘뿐이다. 자주 볼 것이 아니라서 마지막에 둔 자리이지
            // "설정하러 가는 곳" 이 아니다.
            //
            // 기본값('Settings')은 **구획** 모달을 위한 이름이다 — 거기 마지막
            // 탭은 이름·기간·프로그램·몫을 고치는 진짜 편집 폼이라 그 이름이
            // 맞다. 구역·대지는 이미 'About' 을 넘기고 있었으므로, 시설이
            // 기본값을 쓰는 동안 같은 자리의 탭 이름이 계층마다 갈려 있었다.
            // 규칙은 하나다 — **편집 폼이 본체인 곳만 '설정'**.
            // 키(`about`)는 그대로다. 바꾸면 기존 대시보드의
            // `popup_default_tab` 저장값이 없는 탭을 가리킨다.
            return window.AoTMapPopup.buildModalHeader({ name: title, up: true }) +
                   _bayNav +
                   window.AoTMapPopup.buildSectionNav(defSec, [
                       { key: 'overview', label: 'Overview' },
                       // [현황]과 [환경·제어] **사이**다. 왼쪽은 "지금 괜찮은가",
                       // 오른쪽은 "내가 직접 만지겠다" 이고, 그 사이에 놓이는
                       // 질문이 "왜 이렇게 하고 있나" 다. 순서가 곧 그 흐름이다.
                       { key: 'detail',   label: 'Facility detail' },
                       { key: 'envctl',   label: 'Environment & Control' },
                       { key: 'about',    label: 'About' }
                   ]) +
                   '<div class="aot-bay-popup-pane" data-pane="overview"' +
                       (defSec === 'overview' ? '' : ' style="display:none"') + '>' +
                       _skel +
                   '</div>' +
                   '<div class="aot-bay-popup-pane" data-pane="detail"' +
                       (defSec === 'detail' ? '' : ' style="display:none"') + '>' +
                       _skel +
                   '</div>' +
                   '<div class="aot-bay-popup-pane" data-pane="envctl"' +
                       (defSec === 'envctl' ? '' : ' style="display:none"') + '>' +
                       '<div class="aot-bay-popup-section" data-zone="sensors">' +
                           // 센서가 없어도 제목과 안내는 남긴다 — 값이 붙으면
                           // _renderBayChart 가 이 자리를 통째로 갈아끼운다.
                           window.AoTMapPopup.emptyBlock(
                               (window._ ? window._('Environment') : 'Environment'),
                               (window._ ? window._('No sensors are linked to this place yet.')
                                         : 'No sensors are linked to this place yet.')) +
                       '</div>' +
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

        /* 이 모달에 보일 센서 — 이 동의 것, 어느 동에도 배정되지 않은 시설 공통
         * 센서(단동 시설·시설 한가운데 센서), 그리고 **시설의 실외 센서 전부**.
         *
         * ⚠ **실외를 넣는다.** 시설은 안과 밖을 함께 다루는 단위다 — 창을 열지,
         * 커튼을 칠지는 바깥이 어떤가에서 나오는 판단이라, 환경 카드가 그것을
         * 말하지 못하면 사용자는 화면을 하나 더 열어야 한다. 예전에는 뺐는데
         * 그것이 뒤집힌 처리였다(2026-08-24).
         *
         * 실외는 **동으로 나누지 않는다.** 기상대도 시설 어딘가에 서 있어서
         * 좌표 → 슬라이스 매핑이 그것에 동을 붙이지만(실측: 영양 육묘장의
         * '기상대' 가 `bay_id: 'bay_1_6'`), 그 배정은 뜻이 없다 — 바깥은 어느
         * 동의 것도 아니다. 그래서 `bay_id` 를 보지 않고 시설 전체에서 모은다.
         *
         * 순서는 **안이 먼저, 밖이 나중**이다. 이 자리에서 먼저 읽어야 할 것은
         * 기르는 대상이 겪는 환경이고, 바깥은 그 판단의 근거다.
         *
         * ⚠ **평균에는 여전히 넣지 않는다**(`_sensorSummary` 가 거른다). 목록에
         * 보이는 것과 한 숫자로 접는 것은 다른 일이다 — 겨울에 안 25°C · 밖
         * -5°C 를 평균 내면 칩이 10°C 라고 말하고 그 값은 어느 곳도 가리키지
         * 않는다.
         *
         * 반대로 **구획(plot) 모달에는 실외가 들어가지 않는다** — 그쪽은 기르는
         * 대상이 겪는 환경만 묻는 자리다(`plot_context.facility_sensor_ids`). */
        function _baySensors(st, facilityUuid, bayId) {
            var all = st.sensorsByFac[facilityUuid] || [];
            var inBay = window.AoTMapBay.filterSensors(all, bayId);
            var common = all.filter(function (s) {
                return window.AoTMapBay.isIndoor(s) && s.bay_id == null;
            });
            var outdoor = all.filter(function (s) {
                return !window.AoTMapBay.isIndoor(s);
            });
            return inBay.concat(common).concat(outdoor);
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
                // 구역 전환 — 같은 시설의 다른 구역으로 창을 갈아 끼운다.
                // **탭 전환보다 먼저 본다**: 이 버튼도 `.aot-act-tab-btn` 이라
                // 아래 섹션 탭 분기가 먼저 잡으면 pane 만 바꾸고 끝난다.
                var swBtn = e.target.closest('[data-bay-switch]');
                if (swBtn && scopeEl.contains(swBtn)) {
                    var toBay = swBtn.getAttribute('data-bay-switch');
                    if (toBay && toBay !== bayId) _openBayPopup(uid, facilityUuid, toBay);
                    return;
                }
                var st = _actLabelState[uid];
                if (!st || !window.AoTMapPopup || !window.AoTMapBay) return;

                // 자동제어 토글 (현황 pane) — 슬라이드 토글의 checkbox input 만 매칭
                // (label 클릭 시 브라우저가 input 에 합성 click 을 1회 발생시킨다)
                var tgl = e.target.closest('.aot-iec-toggle-input');
                if (tgl && scopeEl.contains(tgl)) {
                    _toggleIec(uid, facilityUuid, tgl);
                    return;
                }

                // 장치 설정 — 시작/종료 시각 예약 (구역 모달·마커 팝업과 공용 창)
                var setBtn = e.target.closest('.aot-output-settings');
                if (setBtn && scopeEl.contains(setBtn) &&
                    window.AoTMapPopup && window.AoTMapPopup.openOutputSchedule) {
                    window.AoTMapPopup.openOutputSchedule({
                        shell:    _showFacilityCenterOverlay,
                        outputId: setBtn.dataset.outputId,
                        channel:  parseInt(setBtn.dataset.channel || '0', 10),
                        name:     setBtn.dataset.outputName || ''
                    });
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
                    window.AoTMapPopup.activateSection(
                        scopeEl, btn.dataset.sec, btn.closest('.aot-bay-popup-nav'));
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
        // 시설 [현황] 맨 위의 현재 환경 블록.
        //
        // 데이터는 이미 폴링 중인 /runtime 을 재사용한다 — AoTFacilityRuntime 이
        // 8초 TTL + in-flight dedup 으로 코얼레싱하므로 요청이 늘지 않는다.
        // 그 응답의 indoor(가중평균)와 sensors(valid/total)는 계산돼 있으면서도
        // 화면에 쓰이는 곳이 한 군데도 없었다.
        // 시설의 대표 측정 지정 — 구역과 같은 규칙, 같은 저장소(도형 meta_json).
        // 여는 순간 /overview 가 실어 오고, 여기 담아 두면 [현황] 블록과 지도
        // 라벨 칩이 같은 값을 본다.
        // 우선순위: 모달에서 방금 받은 값 → 시설 목록이 실어 온 값.
        // 목록에도 실어 두지 않으면 **모달을 한 번 열기 전까지** 지도 칩이
        // 지정을 무시한다.
        function _facilityRepKey(uid, facilityUuid) {
            var st = _actLabelState[uid];
            if (!st) return null;
            if (st.repKeyByFac && st.repKeyByFac[facilityUuid] !== undefined) {
                return st.repKeyByFac[facilityUuid];
            }
            var facs = st.facilities || [];
            for (var i = 0; i < facs.length; i++) {
                if (facs[i] && facs[i].unique_id === facilityUuid) {
                    return facs[i].rep_key || null;
                }
            }
            return null;
        }

        function _wireFacilityRepPick(uid, facilityUuid, pane, canEdit) {
            if (!canEdit || !window.AoTMapPopup.wireEnvNowPick) return;
            window.AoTMapPopup.wireEnvNowPick(pane, function (key) {
                fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) +
                      '/rep_key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json',
                               'X-CSRFToken': _csrfHeader() },
                    body: JSON.stringify({ key: key })
                })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (j) {
                    if (!j || !j.ok) throw new Error('save failed');
                    var st = _actLabelState[uid];
                    if (st) {
                        st.repKeyByFac = st.repKeyByFac || {};
                        st.repKeyByFac[facilityUuid] = j.rep_key || null;
                    }
                    // 지도 위 시설 칩도 이 값을 쓴다 — 다음 폴링을 기다리지
                    // 않고 바로 다시 칠한다.
                    _updateSensorSumChip(uid, facilityUuid);
                })
                .catch(function () {
                    var cur = _facilityRepKey(uid, facilityUuid);
                    pane.querySelectorAll('.aot-env-now-item').forEach(function (el) {
                        el.classList.toggle('is-rep',
                            !!cur && el.dataset.repKey === cur);
                    });
                });
            });
        }

        function _facilityHidden(uid, facilityUuid) {
            var st = _actLabelState[uid];
            return ((st && st.hiddenByFac) || {})[facilityUuid] || {};
        }

        /* 카드 제목 옆 [설정] — 어떤 항목을 낼지 고른다.
         *
         * 창은 예약 창과 **같은 방식**으로 띄운다: 같은 중앙 모달 셸에 다른
         * uid 를 주면 위에 하나 더 쌓인다(`_showFacilityCenterOverlay`).
         * 자체 오버레이를 만들면 폰 전체화면·안전영역 규칙이 따라오지 않는다.
         *
         * `choicesOf` 는 **열 때** 부른다 — 카드는 30초마다 다시 그려지므로
         * 창을 여는 순간의 목록이 맞다(그 사이에 센서가 하나 붙었을 수 있다).
         */
        function _wireCardConfig(uid, pane, cfg) {
            if (!window.AoTMapPopup.wireCardConfig || !cfg.canEdit) return;
            var P = window.AoTMapPopup;
            P.wireCardConfig(pane, cfg.cards, function (card) {
                var items = cfg.choicesOf(card) || [];
                var popup = _showFacilityCenterOverlay(
                    P.buildRowPickerHtml({
                        title: cfg.titleOf(card),
                        items: items,
                        hidden: (cfg.hiddenOf() || {})[card] || []
                    }), 'rowpick-' + card + '-' + cfg.ownerUuid);
                var el = popup.getElement();
                var close = function () { try { popup.remove(); } catch (e) {} };
                el.querySelector('.aot-rowpick-cancel').addEventListener('click', close);
                var saveBtn = el.querySelector('.aot-rowpick-save');
                saveBtn.addEventListener('click', function () {
                    saveBtn.disabled = true;
                    fetch(cfg.saveUrl, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json',
                                   'X-CSRFToken': _csrfHeader() },
                        body: JSON.stringify({ card: card,
                                               keys: P.readRowPicker(el) })
                    })
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .then(function (j) {
                        if (!j || !j.ok) throw new Error('save failed');
                        cfg.onSaved(j.hidden_rows || {});
                        close();
                    })
                    .catch(function () {
                        // 창을 닫지 않는다 — 닫아 버리면 저장된 줄 알고 지나간다.
                        saveBtn.disabled = false;
                    });
                });
            });
        }

        /* 시설의 두 카드([현재]·[제어 상태])에 [설정]을 건다.
         *
         * 카드마다 목록의 출처가 다르고 갱신 주기도 달라, 부르는 쪽이 자기가
         * 아는 것만 넘긴다(`readings` 또는 `summary`). 넘기지 않은 카드의
         * 버튼은 그 카드를 그린 쪽이 따로 건다. */
        function _wireFacilityCardConfig(uid, facilityUuid, pane, canEdit,
                                         card, source) {
            var P = window.AoTMapPopup;
            if (!P || !canEdit) return;
            _wireCardConfig(uid, pane, {
                canEdit: true,
                // **자기가 목록을 아는 카드만** 건다(wireCardConfig 주석).
                // 어느 카드인지는 부르는 쪽이 말한다 — `source` 가 비었는지로
                // 짐작하면 코디네이터가 없는 시설(summary 가 없다)에서 제어
                // 카드가 [현재]로 잘못 걸린다.
                cards: [card],
                ownerUuid: facilityUuid,
                saveUrl: '/api/aot/facility/' +
                         encodeURIComponent(facilityUuid) + '/hidden_rows',
                titleOf: function () {
                    var tr = function (x) { return (window._ ? window._(x) : x); };
                    return card === 'control' ? tr('Control Status') : tr('Environment');
                },
                choicesOf: function () {
                    return card === 'control' ? P.controlRowChoices(source)
                                              : P.envRowChoices(source);
                },
                hiddenOf: function () { return _facilityHidden(uid, facilityUuid); },
                onSaved: function (rows) {
                    var st = _actLabelState[uid];
                    if (st) {
                        st.hiddenByFac = st.hiddenByFac || {};
                        st.hiddenByFac[facilityUuid] = rows;
                    }
                    // 서버 캐시를 비웠으니 클라이언트 캐시도 버린다 — 안 버리면
                    // 창을 닫았다 다시 열 때 옛 설정이 돌아온다(rep_key 와 같다).
                    invalidateModal('facility', facilityUuid);
                    // 카드를 지금 다시 그린다. 30초를 기다리게 하면 저장이
                    // 안 된 줄 안다.
                    var st2 = _actLabelState[uid];
                    if (st2) { st2._ovHtml = null; }
                    _loadOverview(uid, facilityUuid, true);
                }
            });
        }

        // 시설 [현황]의 다가오는 일정.
        //
        // [현황] pane 은 30초마다 통째로 다시 그려지므로 `_prependFacilityEnvNow`
        // 와 같은 방식으로 매번 다시 끼운다. 응답을 위젯 상태에 캐시하는 것도
        // 같은 이유다 — 안 하면 30초마다 블록이 사라졌다 나타난다.
        //
        // 노트 **앞**에 넣는다. 네 계층 모두 노트가 마지막이고, 그 순서가
        // 화면을 옮겨 다녀도 같은 자리에서 같은 것을 찾게 해 준다.
        // 노트 배선 — 두 곳에서 부른다(첫 렌더 · 기록 블록 교체 뒤).
        //
        // [현황] pane 은 30초마다 통째로 다시 그려지므로 cache 를 넘겨
        // placeholder(…)가 매번 스쳐 보이지 않게 한다. 캐시는 pane 이 아니라
        // 위젯 상태에 산다(pane 은 교체된다).
        function _wireFacilityNotes(uid, facilityUuid, pane) {
            var st = _actLabelState[uid];
            if (!st || !pane || !window.AoTNotesBlock) return;
            var facName = '';
            (st.facilities || []).forEach(function (f) {
                if (f && f.unique_id === facilityUuid) facName = f.name || '';
            });
            st._notesCache = st._notesCache || {};
            // 시설도 컨테이너다(베이·장치를 담는다). 시설은 정체성이 둘이라
            // 서버가 도형으로 옮겨 자손을 푼다.
            window.AoTNotesBlock.wire(pane,
                { targetId: facilityUuid, targetType: 'GeoFacility', name: facName },
                { descendants: true, cache: st._notesCache,
                  beforeOpen: function () {
                      var st3 = _actLabelState[uid];
                      if (st3 && st3.openBayPopup) {
                          try { st3.openBayPopup.remove(); } catch (e) {}
                      }
                  } });
        }

        function _appendFacilitySchedule(uid, facilityUuid, pane) {
            if (!window.AoTMapPopup || !window.AoTMapPopup.buildRecordBlock) return;
            var st = _actLabelState[uid];
            if (!st) return;

            // 노트 블록을 **기록 블록으로 교체**한다 — 예정과 노트가 한
            // 블록이라는 점이 구역·식생과 같다. 교체이므로 노트를 다시
            // 배선해야 한다(새 DOM 이다).
            var insert = function (sched) {
                if (!pane || !pane.isConnected) return;
                var st2 = _actLabelState[uid];
                if (!st2 || st2.openBayFacility !== facilityUuid) return;
                var html = window.AoTMapPopup.buildRecordBlock(sched);
                if (!html) return;
                // ⚠ 견주는 것은 **지난번에 만든 문자열**이다. 아래 `outerHTML`
                // 비교는 현재 DOM 을 보는데, 이름 번역(`aot-user-i18n.js`)이
                // 우리가 쓴 직후 텍스트를 번역본으로 바꾸므로 원문으로 만든 새
                // 노드와는 **영원히 다르다** — 노트 자리표시자를 옮겨 심어
                // 한 번 막아 둔 그 깜빡임이, 번역을 켜면 그대로 되살아난다
                // (`_setHtmlIfChanged` 주석).
                if (pane._aotRecordHtml === html) return;
                pane._aotRecordHtml = html;
                var tmp = document.createElement('div');
                tmp.innerHTML = html;
                var node = tmp.firstElementChild;
                // `buildRecordBlock`/`notesBlockHtml` 모두 제목+박스를
                // `.aot-ov-card` 로 감싼 뿌리 노드 하나를 낸다(2026-08-20) —
                // 옛 박스(`.aot-ov-record`·`.aot-ov-notes`)로 찾은 뒤
                // `.closest()` 로 감싼 카드 전체를 집어야 제목까지 함께
                // 교체된다. 박스만 바꿔치기하면 옛 제목이 고아로 남는다.
                var slotBlock = pane.querySelector('.aot-ov-record') ||
                                pane.querySelector('.aot-ov-notes');
                var slot = slotBlock && (slotBlock.closest('.aot-ov-card') || slotBlock);
                // **노트 목록은 비동기로 채워진다.** `buildRecordBlock` 은 그
                // 자리를 자리표시자('…')로 두고 `_wireFacilityNotes` 가 나중에
                // 채운다. 교체할 때 그대로 두면 이미 받아 둔 노트가 '…' 로
                // 되돌아갔다가 다시 채워지므로, 지금 화면의 노트를 새 노드에
                // 옮겨 심고 나서 바꾼다 — 교체돼도 노트가 살아남는다.
                //
                // "바꿀 필요가 있는가" 는 위에서 이미 정했다(`_aotRecordHtml`).
                // 여기서 DOM 과 한 번 더 견주지 않는다 — 번역이 켜진 화면에서는
                // 그 비교가 늘 "다르다" 라 아무것도 막지 못하면서, 꺼진 화면
                // 에서는 진짜 갱신을 삼킬 수 있다.
                if (slot) {
                    var curList = slot.querySelector('.aot-ov-notes-list');
                    var newList = node.querySelector('.aot-ov-notes-list');
                    if (curList && newList) newList.innerHTML = curList.innerHTML;
                    slot.replaceWith(node);
                } else {
                    pane.appendChild(node);
                }
                _wireFacilityNotes(uid, facilityUuid, pane);
            };

            if (st._schedCache) insert(st._schedCache);
            fetch('/api/geo/schedule/' + encodeURIComponent(facilityUuid),
                  { cache: 'no-store' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (!d || !d.ok) return;
                    var st2 = _actLabelState[uid];
                    if (!st2) return;
                    st2._schedCache = { own: d.own || [], devices: d.devices || [] };
                    insert(st2._schedCache);
                })
                .catch(function () {});
        }

        /**
         * HTML 문자열 → 첫 요소 노드.
         *
         * 폴링 갱신에서 "내용이 같으면 손대지 않는다" 를 판정할 때 **문자열끼리
         * 비교하면 안 된다.** 브라우저는 파싱하며 속성 순서·따옴표·`style` 표기를
         * 정규화하므로(`display:none` → `display: none;`), 원본 문자열과 DOM 의
         * `outerHTML` 은 내용이 같아도 항상 달라 매번 교체된다 = 계속 깜빡인다.
         * 양쪽 다 파싱한 뒤 비교해야 한다.
         */
        function _parseNode(html) {
            var tmp = document.createElement('div');
            tmp.innerHTML = html;
            return tmp.firstElementChild;
        }

        /** 오늘(로컬). toISOString() 은 UTC 라 한국 오전에는 하루 전이 나온다. */
        function _todayLocal() {
            var d = new Date();
            var p = function (n) { return String(n).padStart(2, '0'); };
            return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
        }

        /**
         * "여기에 심기" 배선 — **위젯에서 새 구획을 만든다.**
         *
         * 시설 구획은 기하를 그리지 않으므로 여기서 만들 수 있다. 이것이 없으면
         * 지도만 쓰는 사람은 온실 식생을 아예 관리하지 못한다 — 시설 편집기까지
         * 갈 수 있는 계정만 심을 수 있게 되기 때문이다.
         *
         * 저장 뒤에는 런타임 캐시를 버리고 [현황]을 다시 그린다. 캐시만 두면
         * 방금 심은 것이 다음 폴링까지 화면에 없다(그리고 ETag 때문에 그 폴링이
         * 304 로 끝나면 더 오래 비어 있다 — `invalidate` 가 둘을 함께 버린다).
         */
        /** 총량 칸 라벨 — 단위가 무엇을 적는 칸인지 말한다(popup 쪽과 같은 어휘). */
        function _capTotalLabel(unit) {
            switch (unit) {
                case 'row':   return _tr('Total rows');
                case 'tray':  return _tr('Total trays');
                case 'area':  return _tr('Total area (m²)');
                case 'house': return _tr('Total houses');
                default:      return _tr('Total beds');
            }
        }

        /** 단위 표시 문구 — 서버 어휘(`_CAPACITY_UNITS`) 다섯 개와 짝이다. */
        function _capUnitLabel(unit) {
            switch (unit) {
                case 'row':   return _tr('rows');
                case 'tray':  return _tr('trays');
                case 'area':  return _tr('m²');
                case 'house': return _tr('houses');
                default:      return _tr('beds');
            }
        }

        /**
         * 구역 총량 편집 + "남은 몫" 표시 (p6_50).
         *
         * 총량은 **시설의 사실**이라 구획이 아니라 시설에 쓴다(전용 API). 구획
         * 저장이 이 값을 고칠 수 있으면 마지막에 저장한 구획이 분모를 정하게 된다.
         *
         * 남은 몫은 **막지 않는다** — 합이 총량을 넘는 것은 간작·혼작에서 정상이고
         * (VP-3), 넘었다는 것은 표시로만 알린다.
         */
        function _wireFacilityCapacity(uid, facilityUuid, bayId, block, pane, caps, plots) {
            block._aotCaps = caps || {};
            var left = block.querySelector('.aot-ov-alloc-left');
            var cap = (caps || {})[bayId] || null;

            if (left) {
                var used = 0, hasAny = false;
                (plots || []).forEach(function (p) {
                    var a = p.allocation;
                    if (!a) return;
                    if (cap && a.amount != null) { used += Number(a.amount) || 0; hasAny = true; }
                    else if (!cap && a.percent != null) { used += Number(a.percent) || 0; hasAny = true; }
                });
                if (cap) {
                    var rest = cap.total - used;
                    left.textContent = (rest >= 0)
                        ? _tr('%(n)s left').replace('%(n)s',
                              _fmtNum(rest) + ' / ' + cap.total + ' ' + _capUnitLabel(cap.unit))
                        : _tr('Overlapping by %(n)s').replace('%(n)s',
                              _fmtNum(-rest) + ' ' + _capUnitLabel(cap.unit));
                } else if (hasAny) {
                    left.textContent = (used <= 100)
                        ? _tr('%(n)s left').replace('%(n)s', _fmtNum(100 - used) + '%')
                        : _tr('Overlapping by %(n)s').replace('%(n)s', _fmtNum(used - 100) + '%');
                } else {
                    left.textContent = '';
                }
            }

            var edit = block.querySelector('.aot-ov-cap-edit');
            var capWrap = block.querySelector('.aot-ov-cap-wrap');
            if (!edit || !capWrap) return;
            var unitSel = capWrap.querySelector('[data-cf="unit"]');
            var totalIn = capWrap.querySelector('[data-cf="total"]');
            // 총량 칸이 **무엇을 적는 칸인지**는 단위가 정한다("전체 베드 수").
            // 라벨을 "전체" 로만 두면 전체 면적인지 배정 수량인지 알 수 없다.
            var totalLabel = capWrap.querySelector('.aot-ov-cap-total-label');
            var syncTotalLabel = function () {
                if (!totalLabel) return;
                totalLabel.textContent = _capTotalLabel(unitSel ? unitSel.value : 'bed');
            };
            if (unitSel) unitSel.addEventListener('change', syncTotalLabel);
            var showCap = function (on) {
                capWrap.style.display = on ? '' : 'none';
                edit.style.display = on ? 'none' : '';
                var st = _actLabelState[uid];
                if (st) st._plantEditing = on;   // 주기 갱신이 폼을 지우지 않게
            };
            edit.addEventListener('click', function () {
                if (unitSel) unitSel.value = (cap && cap.unit) || 'bed';
                if (totalIn) totalIn.value = cap ? cap.total : '';
                syncTotalLabel();
                showCap(true);
            });
            var cancel = capWrap.querySelector('.aot-ov-cap-cancel');
            if (cancel) cancel.addEventListener('click', function () { showCap(false); });

            var save = capWrap.querySelector('.aot-ov-cap-save');
            if (!save) return;
            save.addEventListener('click', function () {
                save.disabled = true;
                fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) +
                      '/bay_capacity', {
                    method: 'POST', credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': _csrfHeader()
                    },
                    body: JSON.stringify({
                        bay_id: bayId || 'main',
                        unit: unitSel ? unitSel.value : 'bed',
                        total: totalIn ? totalIn.value : ''
                    })
                }).then(function (r) { return r.json().catch(function () { return {}; }); })
                  .then(function (j) {
                    save.disabled = false;
                    if (!j || !j.ok) {
                        if (window.showToast) {
                            window.showToast((j && j.message) || _tr('Save failed'), 'error');
                        }
                        return;
                    }
                    var st = _actLabelState[uid];
                    if (st) st._plantEditing = false;
                    // 총량이 바뀌면 모든 구획의 파생 비율이 바뀐다 — 캐시를 버리고
                    // 카드를 다시 그린다(서버가 파생의 정본이다).
                    if (window.AoTFacilityRuntime) {
                        window.AoTFacilityRuntime.invalidate(facilityUuid);
                    }
                    var old = pane.querySelector('.aot-ov-facility-plots');
                    if (old) (old.closest('.aot-ov-card') || old).remove();
                    _appendFacilityPlots(uid, facilityUuid, pane);
                  }).catch(function () { save.disabled = false; });
            });
        }

        /** 소수점 없는 정수는 정수로 — "4.0 베드" 를 보이지 않게. */
        function _fmtNum(n) {
            var v = Number(n) || 0;
            return (Math.round(v * 10) / 10 === Math.round(v))
                ? String(Math.round(v)) : String(Math.round(v * 10) / 10);
        }

        function _wireFacilityPlotAdd(uid, facilityUuid, bayId, block, pane) {
            var btn = block.querySelector('.aot-ov-plot-add');
            var wrap = block.querySelector('.aot-ov-plot-new-wrap');
            if (!btn || !wrap) return;
            var show = function (on) {
                wrap.style.display = on ? '' : 'none';
                btn.style.display = on ? 'none' : '';
                // 주기 갱신이 이 폼을 지우지 않도록 잠근다(위 _loadOverview 참조).
                var st = _actLabelState[uid];
                if (st) st._plantEditing = on;
            };
            // 폼의 살아 있는 부분(종류↔프로그램, 몫 접미·안내)은 **공용
            // 컴포넌트**가 맡는다(`common/aot-plot-form.js`). 화면마다 이 배선을
            // 적으면 필드가 하나 늘 때 화면 수만큼 고쳐야 하고, 한 곳만
            // 빠뜨려도 그 화면에서만 조용히 동작이 다르다.
            var formCtx = {
                attr: 'data-nf',
                target: 'facility',
                bayId: bayId,
                capacities: block._aotCaps || {},
                // 프로그램 목록 캐시는 구획 모듈이 갖고 있다 — 조회는 계속
                // 그쪽이 맡는다(두 화면이 다른 목록을 보이면 안 된다).
                loadPrograms: function (kind) {
                    return (window.AoTMapPlot && window.AoTMapPlot.loadPrograms)
                        ? window.AoTMapPlot.loadPrograms(kind)
                        : Promise.resolve([]);
                }
            };
            var formApi = null;

            btn.addEventListener('click', function () {
                show(true);
                if (window.AoTPlotForm) {
                    // 총량은 폼을 열 때마다 다시 읽는다 — 그 사이 [구역 총량]
                    // 으로 바뀌었을 수 있다.
                    formCtx.capacities = block._aotCaps || {};
                    if (!formApi) formApi = window.AoTPlotForm.wire(wrap, formCtx);
                    else formApi.refresh();
                }
            });
            var cancel = wrap.querySelector('.aot-ov-plot-new-cancel');
            if (cancel) cancel.addEventListener('click', function () { show(false); });

            var save = wrap.querySelector('.aot-ov-plot-new-save');
            if (!save) return;
            save.addEventListener('click', function () {
                var payload = window.AoTPlotForm
                    ? window.AoTPlotForm.collect(wrap, formCtx)
                    : {};
                payload.facility_uuid = facilityUuid;
                if (!('bay_id' in payload)) payload.bay_id = bayId || '';
                if (!payload.subject) {
                    if (window.showToast) {
                        window.showToast(_tr('Enter what is planted.'), 'warning');
                    }
                    return;
                }
                if (!payload.started_on) payload.started_on = _todayLocal();
                save.disabled = true;
                fetch('/api/geo/plot', {
                    method: 'POST', credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': _csrfHeader()
                    },
                    body: JSON.stringify(payload)
                }).then(function (r) { return r.json().catch(function () { return {}; }); })
                  .then(function (j) {
                    save.disabled = false;
                    if (!j || !j.ok) {
                        if (window.showToast) {
                            window.showToast((j && j.message) || _tr('Save failed'), 'error');
                        }
                        return;      // 잠금은 유지 — 사람이 고칠 입력이 남아 있다
                    }
                    var stx = _actLabelState[uid];
                    if (stx) stx._plantEditing = false;
                    if (window.AoTFacilityRuntime) {
                        window.AoTFacilityRuntime.invalidate(facilityUuid);
                    }
                    // 지도 레이어도 갱신 — 새 구획이 그 구역 자리에 그려져야 한다.
                    if (window.AoTMapPlot) {
                        var vst = window.AoTMapPlot.state(uid);
                        var st2 = _actLabelState[uid];
                        if (vst && st2 && st2.map) {
                            window.AoTMapPlot.load(uid, st2.map, vst.opts || {});
                        }
                    }
                    var old = pane.querySelector('.aot-ov-facility-plots');
                    // 카드 전체(제목+박스)를 지운다 — 박스만 지우면 제목만
                    // 고아로 남는다(`.aot-ov-card` 로 감싼 이유는 위 참조).
                    if (old) (old.closest('.aot-ov-card') || old).remove();
                    _appendFacilityPlots(uid, facilityUuid, pane);
                  }).catch(function () { save.disabled = false; });
            });
        }

        /**
         * [현황]에 "지금 심겨 있는 것" 을 붙인다 — 제어 → 식생 방향.
         *
         * 데이터는 시설 런타임(`plots`)에서 온다. 이미 폴링하는 응답이라
         * 조회가 하나도 늘지 않는다.
         *
         * 줄을 누르면 그 구획 모달로 내려간다(구역 모달의 `aot-ov-plot-link`
         * 와 같은 규약) — 거기서 작물·기간·구역을 고칠 수 있다.
         */
        function _appendFacilityPlots(uid, facilityUuid, pane) {
            if (!window.AoTFacilityRuntime || !window.AoTMapPopup ||
                !window.AoTMapPopup.buildFacilityPlotsHtml) return;
            var st0 = _actLabelState[uid];
            var bayId = st0 ? st0.openBayId : null;
            window.AoTFacilityRuntime.get(facilityUuid).then(function (rt) {
                if (!rt || !pane || !pane.isConnected) return;
                var st = _actLabelState[uid];
                if (!st || st.openBayFacility !== facilityUuid) return;
                var html = window.AoTMapPopup.buildFacilityPlotsHtml(
                    rt.plots || [], bayId, {
                        // 설계 화면 링크를 보일지 — 편집 권한과 **다른 축**이다.
                        // 지금은 값이 같지만(둘 다 edit_settings) 운영 권한
                        // (edit_plots)이 생기면 갈린다.
                        canDesign: !!rt.can_design,
                        // 공용 폼이 몫 접미("/12 베드")를 그리려면 총량이 필요하다.
                        capacities: rt.bay_capacities || {},
                        // 구획 카드는 **작기 운영 권한**(edit_plots)으로 연다
                        // (p6_51). 시설 설정(대표 센서 선택 등)과 다른 축이다 —
                        // 예전에는 같은 플래그를 써서, 작기만 맡기려 해도 시설
                        // 설정을 통째로 열어야 했다. 서버가 같은 것을 요구하므로
                        // 버튼이 보이면 저장도 된다.
                        canEdit: !!rt.can_edit_plots,
                        bays: rt.bays || [],
                        today: _todayLocal()
                    });
                if (!html) return;
                // `buildFacilityPlotsHtml` 은 이제 제목+박스를 `.aot-ov-card`
                // 로 감싼 뿌리 노드 하나를 낸다 — 옛 박스(`.aot-ov-facility-plots`)
                // 로 찾은 뒤 `.closest()` 로 감싼 카드 전체를 집어야 제목까지
                // 함께 교체된다. 안 그러면 새 카드(제목+박스)가 옛 박스 자리에
                // 끼어들어 제목이 중복되거나 옛 제목이 고아로 남는다.
                var existingBlock = pane.querySelector('.aot-ov-facility-plots');
                var existing = existingBlock &&
                    (existingBlock.closest('.aot-ov-card') || existingBlock);
                // 같은 내용이면 손대지 않는다 — 5초마다 지웠다 다시 그리면
                // 화면이 깜빡이고, 열어 둔 심기 폼도 사라진다.
                //
                // ⚠ 견주는 것은 **지난번에 만든 문자열**이지 현재 DOM 이 아니다.
                // 이름 번역(`aot-user-i18n.js`)이 우리가 쓴 직후 텍스트를
                // 번역본으로 바꿔 놓으므로, `existing.outerHTML`(번역본)과 갓
                // 만든 노드(원문)를 견주면 **영원히 다르다** — 가드가 있는데도
                // 매 폴링마다 갈아끼우고 있었다(`_setHtmlIfChanged` 주석).
                if (pane._aotPlotsHtml === html) return;
                pane._aotPlotsHtml = html;
                var block = _parseNode(html);
                if (!block) return;
                if (existing) {
                    existing.replaceWith(block);
                    _wireFacilityCapacity(uid, facilityUuid, bayId, block, pane,
                                          rt.bay_capacities, rt.plots || []);
                    _wireFacilityPlotAdd(uid, facilityUuid, bayId, block, pane);
                    block.querySelectorAll('.aot-ov-plot-link').forEach(function (row) {
                        row.addEventListener('click', function () {
                            var pUuid = row.dataset.plotUuid;
                            if (!pUuid || !window.AoTMapPlot) return;
                            var vst2 = window.AoTMapPlot.state(uid);
                            var st3 = _actLabelState[uid];
                            if (!st3) return;
                            if (st3.openBayPopup) {
                                try { st3.openBayPopup.remove(); } catch (e) {}
                            }
                            window.AoTMapPlot.openModal(
                                uid, st3.map, pUuid, (vst2 && vst2.opts) || {});
                        });
                    });
                    return;
                }
                // 정해진 자리(위치·시간 층)에 넣는다. 예전에는 "환경 블록이 첫
                // 자식" 이라는 가정으로 그 뒤에 끼웠는데, 그 블록이 없는 시설
                // (센서 미등록)이나 응답이 늦는 날에는 자리가 달라졌다.
                // 같은 내용인지는 위에서 이미 걸렀다.
                var slot = pane.querySelector('[data-slot="plots"]');
                if (slot) {
                    slot.innerHTML = '';
                    slot.appendChild(block);
                } else {
                    pane.appendChild(block);
                }
                _wireFacilityCapacity(uid, facilityUuid, bayId, block, pane,
                                      rt.bay_capacities, rt.plots || []);
                _wireFacilityPlotAdd(uid, facilityUuid, bayId, block, pane);
                block.querySelectorAll('.aot-ov-plot-link').forEach(function (row) {
                    row.addEventListener('click', function () {
                        var pUuid = row.dataset.plotUuid;
                        if (!pUuid || !window.AoTMapPlot) return;
                        var vst = window.AoTMapPlot.state(uid);
                        var st2 = _actLabelState[uid];
                        if (!st2) return;
                        if (st2.openBayPopup) {
                            try { st2.openBayPopup.remove(); } catch (e) {}
                        }
                        window.AoTMapPlot.openModal(
                            uid, st2.map, pUuid, (vst && vst.opts) || {});
                    });
                });
            }).catch(function () { /* 부가 정보다 — 실패해도 [현황]은 그대로 */ });
        }

        function _prependFacilityEnvNow(uid, facilityUuid, pane) {
            if (!window.AoTFacilityRuntime || !window.AoTMapPopup ||
                !window.AoTMapPopup.buildEnvNowHtml) return;
            window.AoTFacilityRuntime.get(facilityUuid).then(function (rt) {
                if (!rt || !pane || !pane.isConnected) return;
                var st = _actLabelState[uid];
                if (!st || st.openBayFacility !== facilityUuid) return;

                var indoor = rt.indoor || {};
                var sensors = rt.sensors || {};
                var readings = [];
                if (indoor.temp_c != null) {
                    readings.push({ key: 'T', value: indoor.temp_c, unit: '°C' });
                }
                if (indoor.humidity_pct != null) {
                    readings.push({ key: 'RH', value: indoor.humidity_pct, unit: '%' });
                }
                // **VPD 는 이 시설의 1차 제어 목표다.** 센서가 재고 있는데도
                // 화면이 읽지 않아 [현재]에 안 나왔다(2026-08-20 육묘장:
                // indoor.vpd_kpa 는 계속 오고 있었다). 온·습도 다음에 둔다 —
                // 목표와 편차가 붙는 자리도 여기다.
                if (indoor.vpd_kpa != null) {
                    readings.push({ key: 'VPD', value: indoor.vpd_kpa, unit: 'kPa' });
                }
                if (indoor.co2_ppm != null) {
                    readings.push({ key: 'CO2', value: indoor.co2_ppm, unit: 'ppm' });
                }
                // 외기 — runtime.outdoor 는 계산돼 있으면서 화면에 쓰이는 곳이
                // 없었다. 실내값과 나란히 둬야 "안이 더운 것"과 "바깥이 더운 날"을
                // 가를 수 있다.
                var od = rt.outdoor || {};
                var outdoor = [];
                if (od.temp_c != null) outdoor.push({ key: 'T', value: od.temp_c, unit: '°C' });
                if (od.humidity_pct != null) outdoor.push({ key: 'RH', value: od.humidity_pct, unit: '%' });
                if (od.wind_ms != null) outdoor.push({ key: 'wind_ms', value: od.wind_ms, unit: 'm/s' });

                var canEdit = !!(st.repEditByFac && st.repEditByFac[facilityUuid]);
                var html = window.AoTMapPopup.buildEnvNowHtml({
                    readings: readings,
                    outdoor: outdoor,
                    sensors: { valid: sensors.valid_count || 0,
                               total: sensors.total_count || 0 }
                }, {
                    repKey: _facilityRepKey(uid, facilityUuid),
                    selectable: canEdit,
                    // 카드 제목 옆 [설정] — 낼 항목을 사용자가 고른다.
                    configurable: canEdit,
                    hidden: _facilityHidden(uid, facilityUuid).now,
                    // 목표·편차는 코디네이터 요약에서 온다(측정과 다른 요청).
                    // 값 옆에 붙어야 뜻이 생기므로 여기로 넘긴다 — 아직 안
                    // 왔으면 그 줄만 빠지고 다음 주기에 붙는다.
                    targets: (st._lastEnvSummary || {}).targets,
                    deviation: (st._lastEnvSummary || {}).deviation,
                    // 밴드 바의 축 — 라벨 색 판정과 **같은 표**를 넘긴다.
                    // 시설이 자기 범위를 설정했으면 그것이, 없으면 기본값이
                    // 쓰인다(bandScale 안에서 갈린다).
                    ranges: _facilityRanges_act(uid, facilityUuid),
                    // 프로그램이 정한 한계 — 온도·습도는 목표가 아니라 이쪽이다
                    // (build_env_target 의 R3 주석 참조).
                    limits:  st._lastProgramLimits,
                    trend:   st._lastTrend,
                    photo:   st._lastPhoto,
                    targets: st._lastTargets
                });
                if (html) {
                    // 같은 값이면 DOM 을 건드리지 않는다(위 _loadOverview 주석).
                    // `buildEnvNowHtml` 은 제목+박스를 `.aot-ov-card` 로 감싼
                    // 뿌리 노드 하나를 낸다(2026-08-20) — `_parseNode` 가 그
                    // 뿌리를 그대로 돌려주므로 `node` 는 이미 카드 전체다.
                    // 옛 박스(`.aot-ov-envnow`)로 찾은 뒤 `.closest()` 로 감싼
                    // 카드 전체를 집어야 제목까지 함께 교체된다 — 안 그러면
                    // (박스만 찾아 통째로 바꿔치기하면) 새 카드가 옛 박스
                    // 자리에 끼어들어 옛 제목이 고아로 남는다.
                    //
                    // ⚠ 견주는 것은 **지난번에 만든 문자열**이지 현재 DOM 이
                    // 아니다. 이름 번역(`aot-user-i18n.js`)이 우리가 쓴 직후
                    // 텍스트를 번역본으로 바꿔 놓으므로, `cur.outerHTML`
                    // (번역본)과 갓 만든 노드(원문)를 견주면 **영원히 다르다**
                    // — 가드가 있는데도 매 폴링마다 갈아끼우고 있었다
                    // (`_setHtmlIfChanged` 주석).
                    if (pane._aotEnvNowHtml === html) return;
                    pane._aotEnvNowHtml = html;
                    var node = _parseNode(html);
                    var curBlock = pane.querySelector('.aot-ov-envnow');
                    var cur = curBlock && (curBlock.closest('.aot-ov-card') || curBlock);
                    if (cur && node) {
                        cur.replaceWith(node);
                    } else {
                        // 정해진 자리에 넣는다(없으면 옛 동작으로 폴백).
                        var slot = pane.querySelector('[data-slot="now"]');
                        if (slot) slot.innerHTML = html;
                        else pane.insertAdjacentHTML('afterbegin', html);
                    }
                    _wireFacilityRepPick(uid, facilityUuid, pane, canEdit);
                    _wireFacilityCardConfig(uid, facilityUuid, pane, canEdit,
                                            'now', readings);
                    // 축이 없는 줄은 추세로 답한다. 센서 목록은 라벨용으로
                    // 이미 받아 둔 것을 쓴다(sensorsByFac) — 같은 것을 또
                    // 받으면 모달 열 때마다 왕복이 하나 는다.
                    if (window.AoTMapPopup.fillEnvSparklines) {
                        window.AoTMapPopup.fillEnvSparklines(
                            pane, (st.sensorsByFac || {})[facilityUuid],
                            readings);
                    }
                }
            }).catch(function () {});
        }

        // fresh=true 는 **쓰기 직후의 재조회**다(사진·설명·자동제어 토글).
        // 캐시를 타면 방금 끈 것이 켜진 채로 보여 토글이 고장 난 것처럼 읽힌다.
        function _loadOverview(uid, facilityUuid, fresh) {
            var st = _actLabelState[uid];
            if (!st || !st.openBayPopup) return;
            var popupEl = st.openBayPopup.getElement();
            var body = popupEl && popupEl.querySelector('.maplibregl-popup-content');
            var pane = body && body.querySelector('.aot-bay-popup-pane[data-pane="overview"]');
            var abPane = body && body.querySelector('.aot-bay-popup-pane[data-pane="about"]');
            if (!pane) return;
            if (st._iecPending) return;   // 토글 적용 중 — 재렌더로 pending 상태를 지우지 않음
            if (st._ovEditing) return;    // 설명 편집 중 — 30초 갱신이 입력을 지우지 않음
            // 심기 폼이 열려 있는 동안도 마찬가지다. [현황]은 30초마다 통째로
            // 다시 그려지는데, 그때 작성 중인 작물명·날짜가 사라진다 — 처음에는
            // "버튼이 안 먹는다" 로 보인다(폼을 열자마자 갱신이 지워버린다).
            // `_ovEditing` 과 따로 두는 이유: 설명 편집과 동시에 열릴 수 있고,
            // 한쪽을 닫을 때 다른 쪽 보호까지 풀리면 안 된다.
            if (st._plantEditing) return;
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
                // 위젯 폴링 주기(기본 5초)마다 불린다. 예전에는 그때마다
                // `innerHTML` 을 통째로 갈아끼워 **값이 하나도 안 바뀌어도 모달이
                // 계속 깜빡였다** — 그 위에 비동기로 붙는 블록들(환경·식생·기록)이
                // 매번 사라졌다 다시 나타나며 높이까지 튀었다.
                //
                // 내용이 같으면 손대지 않는다. 그러면 그 안의 배선(노트·토글)도
                // 살아남아 다시 붙일 일이 없다. [개요] 탭이 이미 같은 규칙이다.
                // 다음 [현재] 렌더가 목표·편차를 값 옆에 붙일 수 있게 보관한다.
                st2._lastEnvSummary = (res[0] || {}).summary || null;
                // 프로그램이 정한 한계(주/야간 온도 · 습도). 목표와 다른 축이라
                // 따로 보관한다 — [현재] 렌더가 선으로 긋는다.
                st2._lastProgramLimits = res[5] || null;
                // **순서는 개념 계층이다** — 위치·시간 → 데이터 → 제어 → 기록물.
                // 큰 것에서 작은 것으로, 상위에서 하위로.
                //
                // 자리를 **먼저 깔고** 비동기 블록이 그 안을 채운다. 예전에는
                // 도착한 순서대로 `afterbegin`/`insertBefore` 로 끼워 넣어,
                // 응답이 늦는 날에는 순서가 뒤바뀌었다(그래서 "환경 블록이 첫
                // 자식" 이라는 가정에 기대는 코드가 생겼다).
                var ovHtml =
                    // ① 위치·시간 — 지역(날씨)에서 이 시설(구획)로
                    (window.AoTMapPopup.buildHazardsHtml
                       ? window.AoTMapPopup.buildHazardsHtml(res[3]) : '') +
                    '<div class="aot-ov-slot" data-slot="plots"></div>' +
                    // ② 데이터
                    '<div class="aot-ov-slot" data-slot="now"></div>' +
                    // ③ 제어 — 직전에 한 일(관수) 다음에 지금 하는 일
                    //
                    // ⚠ **[시설 세부]로 옮기지 말 것** (2026-08-26 한 번 옮겼다
                    // 되돌림). "제어 정보니까 저쪽" 이 그럴듯해 보이지만 그
                    // 탭은 **코디네이터가 있는 시설에만** 뜬다 — 옮기는 순간
                    // 연동 안 된 시설은 관수 상태를 볼 자리가 아예 없어진다.
                    // 관수 판정(`irrigation_status`)은 코디네이터와 무관하다.
                    // 노지 [현황]도 같은 자리에서 같은 렌더러를 쓴다.
                    (window.AoTMapPopup.buildIrrigationHtml
                       ? window.AoTMapPopup.buildIrrigationHtml(res[4]) : '') +
                    // ④ 제어 상태 + ⑤ 기록물(노트)
                    window.AoTMapPopup.buildOverviewSection(
                        res[0], res[1], {
                            canToggle: st2.canCtrl,
                            // [제어 상태] 카드도 낼 항목을 고를 수 있다.
                            // 권한 축은 [현재]와 같다(edit_settings).
                            configurable: !!(st2.repEditByFac &&
                                             st2.repEditByFac[facilityUuid]),
                            hiddenControl:
                                _facilityHidden(uid, facilityUuid).control
                        });
                var ovSame = (st2._ovHtml === ovHtml) && pane.children.length > 0;
                if (!ovSame) {
                    st2._ovHtml = ovHtml;
                    pane.innerHTML = ovHtml;
                }

                // [시설 세부] — 같은 env_summary 를 근거 중심으로 편다.
                // **여기서 함께 그린다.** 탭을 누를 때 따로 받아오면 같은
                // 응답을 두 번 조회하게 되고(그 요청이 /overview 로 묶인
                // 이유가 정확히 그것이다), 열자마자 스켈레톤이 한 번 보인다.
                var dPane = body && body.querySelector(
                    '.aot-bay-popup-pane[data-pane="detail"]');

                // ── [시설 세부] 탭 — 연동 없으면 감춘다(근거는 헬퍼 주석) ────
                // 판정은 이 응답을 받은 **뒤에만** 가능하다(모달 골격은 그
                // 전에 그려진다). 그래서 답을 시설별로 기억해 뒀다가 다음에
                // 열 때 골격 단계에서 미리 적용한다 — 없으면 연동 안 된 시설을
                // 열 때마다 탭이 잠깐 보였다 사라진다.
                var _hasCoord = !!(res[0] && res[0].function);
                st2._facCoord = st2._facCoord || {};
                st2._facCoord[facilityUuid] = _hasCoord;
                _applyDetailTabVisibility(body, _hasCoord);

                if (_hasCoord && dPane && window.AoTMapPopup.buildFacilityDetailSection) {
                    var dHtml = window.AoTMapPopup.buildFacilityDetailSection(
                        res[0], {
                            // 이름·실제 개도는 여기서만 안다. 시설 공통까지
                            // 포함해야 한다 — 동을 고른 상태에서도 이 탭은
                            // 시설 전체의 제어를 설명하는 자리다.
                            states: (st2.statesByFac &&
                                     st2.statesByFac[facilityUuid]) || {}
                        });
                    // ⚠ 렌더 여부는 **요소에** 새긴다(위젯 상태가 아니라).
                    // 위젯 상태에 두면 팝업을 닫았다 다시 열 때 DOM 은 새
                    // 스켈레톤인데 상태는 "이미 그렸다" 로 남아, 탭이 영영
                    // 비어 있다(실제로 겪음). 요소에 붙이면 DOM 과 함께 죽는다.
                    if (dPane._detailHtml !== dHtml) {
                        dPane._detailHtml = dHtml;
                        dPane.innerHTML = dHtml;
                    }
                }
                // 현재 환경 + 센서 신뢰도를 맨 위에. 자동제어가 안 걸린 시설의
                // [현황]은 예전에 "연동된 자동제어 없음" 한 줄이 전부여서, 수동
                // 운영 시설에서는 탭이 통째로 빈 껍데기였다.
                // 단계 목표 대비 카드는 DOM 에 붙은 뒤에 채워진다(공용 로더).
                if (!ovSame && window.AoTCoordinatorPlot) {
                    window.AoTCoordinatorPlot.scan();
                }
                _prependFacilityEnvNow(uid, facilityUuid, pane);
                // [제어 상태]의 [설정]. [현재]는 자기 블록을 다시 그릴 때
                // 스스로 배선한다(`_prependFacilityEnvNow`) — 두 카드가 서로
                // 다른 주기로 갱신되므로 한 곳에서 함께 걸 수 없다.
                _wireFacilityCardConfig(
                    uid, facilityUuid, pane,
                    !!(st2.repEditByFac && st2.repEditByFac[facilityUuid]),
                    'control', (res[0] || {}).summary);
                _appendFacilityPlots(uid, facilityUuid, pane);
                _appendFacilitySchedule(uid, facilityUuid, pane);
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

                // [현황] DOM 이 그대로면 리스너도 그대로 살아 있다 — 다시 붙이면
                // 노트 목록을 되쓰면서 화면이 깜빡이고, 클릭 리스너도 겹친다.
                if (!ovSame) _wireFacilityNotes(uid, facilityUuid, pane);

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
                        .then(function () { _loadOverview(uid, facilityUuid, true); })
                        .catch(function () { phBtn.disabled = false; });
                    });
                }

                // 설명 편집/저장 (editor 이상에서만 편집 UI 렌더됨, 위와 동일 정책)
                var descEdit   = aboutChanged ? wireEl.querySelector('.aot-ov-desc-edit') : null;
                // 숨기는 것은 버튼이 아니라 **버튼이 든 행**이다. 버튼만 숨기면
                // 빈 행이 남아 편집 중에만 블록 아래가 한 줄만큼 벌어진다.
                var descEditRow = descEdit
                    ? (descEdit.closest('.aot-ov-actions') || descEdit) : null;
                var descView   = wireEl.querySelector('.aot-ov-desc-view');
                var descWrap   = wireEl.querySelector('.aot-ov-desc-editwrap');
                var descInput  = wireEl.querySelector('.aot-ov-desc-input');
                var descSave   = wireEl.querySelector('.aot-ov-desc-save');
                var descCancel = wireEl.querySelector('.aot-ov-desc-cancel');
                if (descEdit && descWrap) {
                    descEdit.addEventListener('click', function () {
                        st2._ovEditing = true;
                        descView.style.display = 'none';
                        descEditRow.style.display = 'none';
                        descWrap.style.display = '';
                        if (descInput) descInput.focus();
                    });
                    if (descCancel) descCancel.addEventListener('click', function () {
                        st2._ovEditing = false;
                        descWrap.style.display = 'none';
                        descView.style.display = '';
                        descEditRow.style.display = '';
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
                            _loadOverview(uid, facilityUuid, true);
                        })
                        .catch(function () { descSave.disabled = false; });
                    });
                }

            };

            // env_summary + status + info 를 한 요청(/overview)으로 묶어
            // 받는다. 개별 fetch 3개는 gthread 워커 스레드 3개를 동시에
            // 점유해, 페이지 로드 직후 맵 폴링 버스트와 겹칠 때 스레드 풀이
            // 포화되어 모달 렌더가 1초+(콜드 시 4초+) 지연되는 주원인이었다.
            var _ovReq;
            if (fresh) {
                invalidateModal('facility', facilityUuid);
                _ovReq = fetch('/api/aot/facility/' +
                               encodeURIComponent(facilityUuid) +
                               '/overview?fresh=1');
            } else {
                _ovReq = modalFetch('facility', facilityUuid);
            }
            _ovReq
                .then(_j).catch(function () { return null; })
                .then(function (j) {
                    j = j || {};
                    // 대표 측정 지정·권한을 먼저 담는다 — _render 안에서
                    // _prependFacilityEnvNow 가 바로 읽는다.
                    var st0 = _actLabelState[uid];
                    if (st0) {
                        st0.repKeyByFac = st0.repKeyByFac || {};
                        st0.repEditByFac = st0.repEditByFac || {};
                        st0.repKeyByFac[facilityUuid] = j.rep_key || null;
                        st0.repEditByFac[facilityUuid] = !!j.can_edit;
                        st0.hiddenByFac = st0.hiddenByFac || {};
                        st0.hiddenByFac[facilityUuid] = j.hidden_rows || {};
                    }
                    // 추세는 [환경] 카드가 그린다 — 그 카드는 별도 주기로
                    // 다시 그려지므로(_prependFacilityEnvNow) 여기서 상태에
                    // 실어 두고 그쪽이 읽는다.
                    if (st0) {
                        var _sm = (j.env_summary || {}).summary || {};
                        st0._lastTrend   = _sm.trend   || null;
                        st0._lastPhoto   = _sm.photo   || null;
                        st0._lastTargets = _sm.targets || null;
                        st0._lastIrr     = j.irrigation || null;
                    }
                    _render([j.env_summary || null, j.status || null,
                             j.info || null, j.hazards || null,
                             j.irrigation || null, j.limits || null]);

                    // 상위 필지로 올라가는 화살표 + 상태 점
                    var st2 = _actLabelState[uid];
                    var popupEl2 = st2 && st2.openBayPopup && st2.openBayPopup.getElement();
                    var body2 = popupEl2 && popupEl2.querySelector('.maplibregl-popup-content');
                    if (body2) {
                        window.AoTMapPopup.applyStatusDot(body2, j.area_status);
                        _wireUpBtn(body2, uid, j.site, function () {
                            var st3 = _actLabelState[uid];
                            if (st3 && st3.openBayPopup) {
                                try { st3.openBayPopup.remove(); } catch (e) {}
                                st3.openBayPopup = null;
                            }
                        });
                    }
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
                _loadOverview(uid, facilityUuid, true);
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

        // ── [시설 세부] 탭 표시 판정 ────────────────────────────────────────
        //
        // 이 탭이 답하는 질문은 "장치가 왜 지금 그 값인가" 이고 근거는 전부
        // env_coordinator 사이클에서 나온다. 연동이 없으면 낼 것이 하나도 없어
        // "아직 설명할 제어 사이클이 없습니다" 한 줄만 남는데, 그것은 **탭을
        // 눌러 봐야 알 수 있는 빈 방**이다.
        //
        // 기준은 **연동 여부**(`env_summary.function`)이지 신선도가 아니다.
        // stale 로 감추면 사이클이 한 번 늦을 때마다 탭이 사라졌다 나타나 탭
        // 목록이 흔들린다 — 붙어 있는 시설은 지금 값을 못 낼 뿐이고, 그 사실은
        // 그 탭 **안에서** 말하는 편이 맞다.
        function _applyDetailTabVisibility(body, hasCoord) {
            if (!body) return;
            var btn = body.querySelector(
                '.aot-bay-popup-nav .aot-act-tab-btn[data-sec="detail"]');
            var pane = body.querySelector(
                '.aot-bay-popup-pane[data-pane="detail"]');
            if (btn) btn.style.display = hasCoord ? '' : 'none';
            if (hasCoord) return;
            // 감춘 탭이 **열려 있던** 경우(저장된 popup_default_tab 이 'detail'
            // 이거나, 연동을 방금 끊었을 때) 빈 화면만 남는다. 항상 있는 탭으로
            // 되돌린다.
            if (btn && btn.classList.contains('active') &&
                window.AoTMapPopup && window.AoTMapPopup.activateSection) {
                window.AoTMapPopup.activateSection(
                    body, 'overview', btn.closest('.aot-bay-popup-nav'));
            }
            if (pane) pane.style.display = 'none';
        }

        function _openBayPopup(uid, facilityUuid, bayId) {
            var st = _actLabelState[uid];
            if (!st || !window.AoTMapPopup || !window.AoTMapBay) return;
            if (st.openBayPopup) { try { st.openBayPopup.remove(); } catch (e) {} st.openBayPopup = null; }

            var popup = _showFacilityCenterOverlay(
                _buildBayPopupHTML(uid, facilityUuid, bayId, null), uid);
            // 시설은 자기 uuid 가 아니라 **도형** uuid 로 지도에 있다.
            var _facRow = null, _facs = (st.facilities || []);
            for (var _fi = 0; _fi < _facs.length; _fi++) {
                if (_facs[_fi] && _facs[_fi].unique_id === facilityUuid) { _facRow = _facs[_fi]; break; }
            }
            var _bayFocus = (_facRow && _facRow.shape_uuid) || facilityUuid;
            _focusMapOn(uid, _bayFocus);
            // 셸을 부를 때는 도형 uuid 를 아직 몰랐다(시설 목록을 여기서 뒤진다).
            // 그래서 이유를 여기서 얹고, 창이 닫힐 때 거둔다.
            (function () {
                var _inst = window.AoTWidgetInstances[uid];
                if (!_inst || !_bayFocus) return;
                // 도형은 **도형 uuid**, 라벨(구역 칩)은 **시설 uuid** 로
                // 달려 있다 — 둘이 다르므로 둘 다 얹는다.
                [_bayFocus, facilityUuid].forEach(function (u) {
                    if (u) _setFocus(_inst, uid, String(u), 'modal', true);
                });
                if (popup && popup.on) {
                    popup.on('close', function () {
                        [_bayFocus, facilityUuid].forEach(function (u) {
                            if (u) _setFocus(_inst, uid, String(u), 'modal', false);
                        });
                    });
                }
            })();
            var popupEl = popup.getElement();
            var bodyEl = popupEl && popupEl.querySelector('.maplibregl-popup-content');
            if (bodyEl) {
                // 지난번에 "연동 없음" 으로 확인된 시설이면 미리 감춘다.
                // 모르면 건드리지 않는다 — 기본은 보이는 쪽이라, 연동된 시설의
                // 탭이 응답을 기다리는 동안 사라져 보이는 일이 없다.
                if (st._facCoord && st._facCoord[facilityUuid] === false) {
                    _applyDetailTabVisibility(bodyEl, false);
                }
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
                    st2._plantEditing = false;
                }
            });
            st.openBayPopup = popup;
            st.openBayFacility = facilityUuid;
            st.openBayId = bayId;
            st.overlaySlot = null;
            st._notesCache = null;   // 시설이 바뀌면 이전 시설의 노트를 물려주지 않는다
            st._aboutHtml = null;
            st._ovHtml = null;       // [현황] 재사용 캐시 — 시설이 바뀌면 버린다

            // [현황] 데이터 로드 + 30초 주기 갱신 (팝업 열려있는 동안만 —
            // 사이클 주기와 유사하므로 더 짧을 필요 없음)
            _loadOverview(uid, facilityUuid);
            if (st.ovTimer) clearInterval(st.ovTimer);
            st.ovTimer = setInterval(function () {
                if (document.hidden) return;
                _loadOverview(uid, facilityUuid);
            }, st.refreshMs || _OV_REFRESH_MS);

            // 호출자(구역 칩)가 close 를 구독해 "앞으로 고정"을 풀 수 있게 반환.
            return popup;
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
            // 값이 그대로면 손대지 않는다 — 5초마다 같은 HTML 로 갈아끼우는 것이
            // 곧 깜빡임이다(`_setHtmlIfChanged` 주석). 실측으로 이 섹션은 폴링
            // 사이에 글자 하나까지 같았는데도 매번 통째로 교체되고 있었다.
            var changed = _setHtmlIfChanged(section,
                window.AoTMapPopup.buildActuatorTabs(
                    activeCat, _ACT_CATS, states, st.canCtrl,
                    st._lastCmd || {}, _actKindToCat, savedOrder));
            if (!changed) return;
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
            // 지도가 이동/줌 애니메이션 중이면 건너뛴다. 이 함수는 moveend에서도
            // 호출되지만, 액추에이터 폴링 타이머는 사용자가 드래그하는 도중에도
            // 그대로 만료되어 그 순간의 중간 뷰포트를 기준으로 재계산한다 — 이때
            // 직전까지 표시되던 시설이 잠깐 후보에서 빠지면 패널이 비었다가
            // moveend 직후 다시 채워지며 떨려 보인다. 이동이 끝나면 moveend
            // 리스너가 정확한 최종 위치로 다시 호출해주므로 여기서 건너뛰어도
            // 안전하다.
            if (map.isMoving && map.isMoving()) return;

            var mc = map.getCenter();
            var bounds = map.getBounds();
            var candidates = [];
            (st.facilities || []).forEach(function (fac) {
                var ring = _facilityFootprintRing(fac);
                var center = _facilityCenter_act(fac);
                if (!ring && !center) return;
                // 시설이 뷰포트와 관련 있는지 판단 — 중심점이 뷰포트 안이거나,
                // 폴리곤 꼭짓점 중 하나라도 뷰포트 안이거나(부분적으로만 화면에
                // 걸친 큰 시설), 혹은 화면 중심 자체가 그 폴리곤 내부인 경우(꼭짓점이
                // 전부 화면 밖으로 나갈 만큼 큰 시설이 화면을 통째로 덮은 경우) 중
                // 하나라도 해당하면 후보로 포함한다.
                var inView = !!(center && bounds.contains([center[0], center[1]]));
                if (!inView && ring) {
                    for (var k = 0; k < ring.length && !inView; k++) {
                        if (bounds.contains([ring[k][0], ring[k][1]])) inView = true;
                    }
                }
                if (!inView && ring && _ringContainsPoint([mc.lng, mc.lat], ring)) inView = true;
                if (!inView) return;

                var dist = _facilityDistToPoint(fac, mc.lng, mc.lat);
                var ctrlCount = Object.keys((st.statesByFac && st.statesByFac[fac.unique_id]) || {}).length;
                var sensorCount = ((st.sensorsByFac && st.sensorsByFac[fac.unique_id]) || []).length;
                candidates.push({ fac: fac, dist: dist, ctrlCount: ctrlCount, sensorCount: sensorCount });
            });
            if (!candidates.length) { handle.setSummary([]); return; }

            // 거리는 시설 폴리곤 외곽선까지의 최단거리(내부면 0, _facilityDistToPoint)로
            // 계산해, 폭보다 길이가 훨씬 긴 시설(예: 3연동 온실)이 중심점 하나로만
            // 비교할 때 부당하게 밀리는 문제를 피한다.
            candidates.sort(function (a, b) { return a.dist - b.dist; });
            var nearest = candidates[0];
            var best;
            if (nearest.ctrlCount > 0 || nearest.sensorCount > 0) {
                // 화면 중심에 실제로 있는(가장 가까운) 시설에 제어값이든 측정값이든
                // 뭔가 있으면 그 시설을 그대로 보여준다 — 사용자가 실제로 이동해 간
                // 시설을 존중한다. 그 시설에 제어장치가 없어 이 칸(제어 요약)에 표시할
                // 게 없더라도, 엉뚱한 다른 시설의 제어값을 대신 보여주는 것보다는
                // 비어 있는 편이 정직하다.
                best = nearest.fac;
            } else {
                // 가장 가까운 시설에 제어값도 측정값도 전혀 없을 때만(예: 빈 창고),
                // 제어장치가 있는 다른 시설로 대체한다 — 그중 제어장치가 가장 많은
                // 시설을 우선하고, 동률이면 더 가까운 쪽을 택한다.
                var withCtrl = candidates.filter(function (c) { return c.ctrlCount > 0; });
                withCtrl.sort(function (a, b) { return b.ctrlCount - a.ctrlCount || a.dist - b.dist; });
                best = (withCtrl.length ? withCtrl[0] : nearest).fac;
            }

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

        // Theme colors from geo/design panel settings — resolved through the
        // shared AoTGeoTheme helper so the widget and the geo/design canvas
        // cannot drift apart on defaults (they used to: output fell back to
        // '#dd4444' here and '#995aff' there).
        const theme = wOpts.theme_config || (vars && vars.theme) || {};
        // 강조 레이어도 **같은 테마**로 색을 정해야 도형과 테두리가 갈리지 않는다.
        // 모듈 스코프의 _highlightShape 는 이 지역 변수에 닿지 못하므로 남겨 둔다.
        if (instance) instance._geoTheme = theme;
        const _T = window.AoTGeoTheme;
        const C = {
            site:      _T.color('site', theme),
            zone:      _T.color('zone', theme),
            facility:  _T.color('facility', theme),
            equipment: _T.color('equipment', theme),
            drawn:     theme.drawn || '#f59e42'
        };
        // Data-driven device shape color: match GeoJSON device_type to a theme key.
        // Function sub-types (trigger/pid/...) are listed explicitly — a shape saved
        // with the raw sub-type used to miss every branch and fall through to the
        // input color. The fallback is the shared device color, not input.
        const _deviceColorExpr = ['match', ['get', 'device_type']];
        ['input', 'output'].forEach(function (k) {
            _deviceColorExpr.push(k, _T.deviceColor(k, theme));
        });
        _T.FUNCTION_TYPES.forEach(function (k) {
            _deviceColorExpr.push(k, _T.deviceColor('function', theme));
        });
        _deviceColorExpr.push(_T.color('device', theme));

        // mapUuid: multiple fallback sources (fixes aot-device missing when contentMapUuid empty)
        const mapUuid = wOpts.selected_map_uuid || wOpts.map_uuid || (vars && vars.contentMapUuid) || '';

        // ============================================================
        // Each category's fetch+addLayer is its own named async function
        // (not just an inline `if`) so a LIVE toggle-on (settings drawer,
        // no page reload) can call the same one on-demand — see
        // `_applyShapeVisible` below. Previously these only ran here, at
        // widget init; turning e.g. Site/Zone Shape on later via the
        // settings drawer called `_applyShapeVisible` -> `setLayoutProperty`
        // on a MapLibre layer id ('sites-fill' etc.) that was never created
        // (the category was off at load, so this block's `if` never ran) —
        // silently a no-op until the next full page refresh re-ran init.
        // addGeoJSONLayer() is already idempotent (guards on getSource/
        // getLayer), so calling one of these twice (init + on-demand) is safe.
        // ============================================================

        // Site GeoJSON 은 도형뿐 아니라 site 라벨→요약 모달 콜백
        // (_onSiteLabelClick) 등록에도 쓴다 — zone 과 같은 구조다. 라벨은
        // show_site_label 로 도형과 독립 제어되므로, 도형을 끄고 라벨만 켠
        // 경우에도 콜백은 등록되어야 한다(그러지 않으면 옛 팝업이 뜬다).
        async function _ensureSiteShapeLayer() {
            try {
                const sitesResponse = await geoFetch('/api/geo/sites?format=geojson' + (mapUuid ? '&map_uuid=' + encodeURIComponent(mapUuid) : ''));
                if (sitesResponse.ok) {
                    const sitesGeoJSON = await sitesResponse.json();
                    _cacheShapes(uniqueId, sitesGeoJSON);
                    if (sitesGeoJSON.features && sitesGeoJSON.features.length > 0) {
                        if (_boolOpt('show_site_shape')) {
                            addGeoJSONLayer(uniqueId, map, 'sites', sitesGeoJSON, {
                                type: 'fill',
                                paint: { 'fill-color': C.site, 'fill-opacity': 0.08 }
                            }, 'sites-fill');
                            addGeoJSONLayer(uniqueId, map, 'sites', sitesGeoJSON, {
                                type: 'line',
                                paint: { 'line-color': C.site, 'line-width': 3, 'line-opacity': 0.8 }
                            }, 'sites-line');
                        }

                        // node_id → uuid 맵 등록 (site label click 콜백용)
                        var _sitesByNodeId = {};
                        sitesGeoJSON.features.forEach(function(f) {
                            if (f.properties && f.properties.node_id) {
                                _sitesByNodeId[f.properties.node_id] = f.id || f.properties.id;
                            }
                        });
                        var _sInst = window.AoTWidgetInstances && window.AoTWidgetInstances[uniqueId];
                        if (_sInst) {
                            // 라벨 호버 예열이 uuid 를 찾을 통로(_zonesByNodeId 와 같은 방식).
                            _sInst._sitesByNodeId = _sitesByNodeId;
                            _sInst._onSiteLabelClick = function(nodeId, siteName) {
                                var siteUuid = _sitesByNodeId[nodeId];
                                if (siteUuid) _openSitePopup(uniqueId, siteUuid, siteName);
                            };
                            // 필지 요약은 콜드가 1초에 가깝고 지도에 몇 개 없다.
                            // 지도가 자리를 잡은 뒤 한가할 때 미리 데워 두면
                            // 첫 클릭도 즉시 열린다(구역은 수가 많아 호버 예열만).
                            var _warmSites = Object.keys(_sitesByNodeId).map(function (n) {
                                return _sitesByNodeId[n];
                            });
                            _whenIdle(function () {
                                _warmSites.forEach(function (u) { warmModal('site', u); });
                            }, 3000);
                        }
                    }
                }
            } catch (e) {
            }
        }

        // Zone GeoJSON 은 도형(show_zone_shape) 뿐 아니라 zone 라벨→모달 클릭
        // 콜백(_onZoneLabelClick) 등록에도 필요하다. 라벨은 show_zone_label 로
        // 도형과 독립 제어되므로, 둘 중 하나라도 켜져 있으면 fetch + 콜백 등록을
        // 수행하고, 실제 fill/line 도형은 show_zone_shape 일 때만 그린다. (과거엔
        // 콜백이 show_zone_shape 에만 묶여 있어, 도형은 끄고 라벨만 켠 경우 클릭 시
        // 모달 대신 옛 maplibre 팝업이 떴다.)
        async function _ensureZoneShapeLayer() {
            try {
                const zonesResponse = await geoFetch('/api/geo/zones?format=geojson' + (mapUuid ? '&map_uuid=' + encodeURIComponent(mapUuid) : ''));
                if (zonesResponse.ok) {
                    const zonesGeoJSON = await zonesResponse.json();
                    // 레이어를 안 그리는 구성에서도 모달이 도형을 찾을 수 있게
                    // 캐시는 항상 채운다(show_zone_shape 와 무관하다).
                    _cacheShapes(uniqueId, zonesGeoJSON);
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
                            // 라벨의 상태·대표값 갱신도 같은 색인을 쓴다
                            // (라벨에는 node_id 만 있고 uuid 가 없다).
                            _inst._zonesByNodeId = _zonesByNodeId;
                            _inst._onZoneLabelClick = function(nodeId, zoneName) {
                                var zoneUuid = _zonesByNodeId[nodeId];
                                if (zoneUuid) _openZonePopup(uniqueId, zoneUuid, zoneName);
                            };
                            _startZoneLabelStatus(uniqueId, mapUuid);
                        }
                    }
                }
            } catch (e) {
            }
        }

        async function _ensureFacilityShapeLayer() {
            if (!mapUuid) return;
            try {
                const facRes = await geoFetch('/api/geo/overlays?map_uuid=' + encodeURIComponent(mapUuid) + '&type=facility');
                if (facRes.ok) {
                    const facGeoJSON = await facRes.json();
                    _cacheShapes(uniqueId, facGeoJSON);
                    if (facGeoJSON.features && facGeoJSON.features.length > 0) {
                        // Flat footprint + extrusion box: ONLY when the Facility shape
                        // category is actually on. The 3D model / sensor labels / actuator
                        // labels below are independent of this — they used to be nested
                        // inside the same unconditional block, which meant "Facility"/
                        // "Sensor Values" LABEL toggles had nothing to toggle whenever the
                        // Facility SHAPE was off (its default). Called whenever facility
                        // shape OR labels are wanted (see call site), so this branch alone
                        // decides whether the mesh itself renders.
                        if (_boolOpt('show_facility_shape')) {
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
                        }

                        // Attach Three.js greenhouse model overlay (replaces fill-extrusion box)
                        //
                        // 3D 스택(three + facility-3d + map-3d, 831KB)은 여기서 **처음
                        // 필요해질 때** 받는다. 예전에는 위젯 head 가 document.write 로
                        // 무조건 받아 놓고 이 자리에서 존재 여부만 확인했다 — 3D 시설이
                        // 하나도 없는 지도에서도 831KB 를 파싱했다는 뜻이다.
                        // 목록 조회가 먼저이고, 3D 지오메트리를 가진 시설이 하나라도
                        // 있을 때만 로드한다. 없으면 831KB 는 영영 안 받는다.
                        {
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
                                        if (window.AoTFacility3DLoader) await window.AoTFacility3DLoader.ensure();
                                        if (!window.AoTFacilityMap3D || !window.AoTFacility3D) throw new Error('3D stack unavailable');
                                        AoTFacilityMap3D.attach(map, facilities3d, { hideLayers: ['facilities-3d'], renderMode: wOpts.facility_render_mode || 'default' });
                                        // Sensor value labels (overlay markers + 24h popup)
                                        if (window.AoTMapSensorLabels) {
                                            try {
                                                AoTMapSensorLabels.attach(uniqueId, map, facilities3d, _sensorLabelOpts(vars));
                                            } catch (eSL) {
                                            }
                                        }
                                        // Actuator category labels (map markers + popup controls).
                                        // Refresh period is derived from wOpts inside
                                        // (_runtimePollSeconds) — output_update_interval /
                                        // input_update_interval, no longer the widget's
                                        // overall refresh period.
                                        try {
                                            _attachActuatorLabels(uniqueId, facilities3d, wOpts, map);
                                        } catch (eAL) {
                                        }
                                    }
                                }
                            } catch (e3d) {
                                // 예전에는 3D 스택이 늘 로드돼 있어 여기 남는 것은 데이터
                                // 문제뿐이었다. 이제 로드 실패도 여기로 떨어지는데, 그때
                                // 증상은 "3D 온실만 조용히 안 보임"이라 조용히 삼키면
                                // 원인 도달이 매우 늦어진다.
                                console.error('[AoT Map] 3D facility overlay failed:', e3d);
                            }
                        }
                    }
                }
            } catch (e) {
            }
        }

        async function _ensureEquipmentShapeLayer() {
            if (!mapUuid) return;
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

        // Device shapes (aot_device) — on:0.9 / off:0.2 via data-driven expr.
        // Initial state: all OFF (0.2); updated after device fetch.
        async function _ensureDeviceShapeLayer() {
            if (!mapUuid) return;
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

        // Drawn shapes (other drawn shapes — types not in known list).
        async function _ensureDrawnShapeLayer() {
            if (!mapUuid) return;
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

        // Expose so `_applyShapeVisible` (settings-drawer live toggle) can create a
        // category's layer on demand the first time it's switched on live.
        try {
            var _instShapes = window.AoTWidgetInstances && window.AoTWidgetInstances[uniqueId];
            if (_instShapes) {
                _instShapes._ensureShapeLayer = {
                    land: _ensureSiteShapeLayer, zone: _ensureZoneShapeLayer,
                    facility: _ensureFacilityShapeLayer, equipment: _ensureEquipmentShapeLayer,
                    device: _ensureDeviceShapeLayer, drawn: _ensureDrawnShapeLayer
                };
            }
        } catch (e) {
        }

        if (_boolOpt('show_site_shape') || _boolOpt('show_site_label')) { await _ensureSiteShapeLayer(); }
        if (_boolOpt('show_zone_shape') || _boolOpt('show_zone_label')) { await _ensureZoneShapeLayer(); }

        // facility/equipment/device/drawn require mapUuid
        if (!mapUuid) return;

        // Facility/sensor/actuator LABELS live inside this same fetch (see the
        // function body) — run it whenever labels are wanted too, not just the
        // Facility shape, so those label toggles have something to toggle by
        // default (show_labels defaults True, show_facility_shape defaults False).
        if (_boolOpt('show_facility_shape') || _boolOpt('show_labels')) { await _ensureFacilityShapeLayer(); }
        if (_boolOpt('show_equipment_shape')) { await _ensureEquipmentShapeLayer(); }
        if (_boolOpt('show_device_shapes')) { await _ensureDeviceShapeLayer(); }
        if (_boolOpt('show_drawn_shapes')) { await _ensureDrawnShapeLayer(); }

        _installShapeWarm(uniqueId, map);
    }

    // ── 도형 클릭 ──────────────────────────────────────────────────────────────
    //
    // 예전에는 라벨(작은 알약)만 눌러야 모달이 열렸다. 폴리곤 전체가 눌리면
    // 터치 타깃이 수십 배 커진다 — 특히 폰에서 라벨을 정확히 찍기 어렵다.
    //
    // 겹친 도형은 **좁은 것부터** 고른다(시설 > 구역 > 필지). 시설은 구역 안에,
    // 구역은 필지 안에 있으므로 넓은 것을 먼저 집으면 안쪽을 영영 못 연다.
    // (겹침에서 하나만 고르는 규칙은 삭제 클릭이 이미 쓰는 것과 같은 원칙이다.)
    /**
     * 도형 위 호버 **예열**만 설치한다.
     *
     * **도형을 눌러도 모달은 열리지 않는다.** 모달을 여는 것은 라벨과 값 키뿐이다
     * (전부 DOM 요소라 이 캔버스 핸들러를 지나지 않는다). 예전에는 필지·구역·
     * 시설의 fill 레이어 클릭도 모달을 열었는데, 그러면 지도를 짚거나 팬을
     * 시작하려고 도형을 누른 것까지 창이 뜬다. 겹친 도형 위에서는 무엇이 열릴지도
     * 예측할 수 없다(안쪽 도형을 노렸는데 위에 깔린 것이 열린다).
     *
     * 예열은 남긴다 — 라벨로 가는 길에 도형 위를 지나가는 것이 보통이라, 그때
     * 미리 받아 두면 라벨을 눌렀을 때 곧바로 뜬다.
     */
    function _installShapeWarm(uid, map) {
        var inst = window.AoTWidgetInstances[uid];
        if (!inst || inst._shapeWarmWired) return;
        inst._shapeWarmWired = true;

        // 레이어 한정 mousemove 라 히트테스트는 MapLibre 가 하고, 같은 도형
        // 위에서는 uuid 가 안 바뀌어 한 번만 나간다.
        // 시설은 도형 uuid 가 아니라 **시설 uuid** 로 조회한다(/overview) —
        // 그 대응은 inst.cachedFacilities3d 가 들고 있다.
        var _lastWarmed = null;
        [['zones-fill', 'zone'], ['sites-fill', 'site'],
         ['facilities-fill', 'facility']].forEach(function (pair) {
            map.on('mousemove', pair[0], function (e) {
                var f = e.features && e.features[0];
                var u = f && f.properties && f.properties.shape_uuid;
                if (!u || u === _lastWarmed) return;
                _lastWarmed = u;
                warmModal(pair[1],
                          pair[1] === 'facility'
                            ? (inst._facilityUuidOfShape &&
                               inst._facilityUuidOfShape(u))
                            : u);
            });
        });
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

        // Sort: 충돌 우선순위가 높은(=더 구체적인) 라벨부터 자리를 잡는다.
        // 쌓임 순서(z-index)와는 다른 축이다 — LABEL_COLLISION_RANK 주석 참고.
        var sorted = markers.slice().sort(function(a, b) {
            return _collisionRank(b.getElement()) - _collisionRank(a.getElement());
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

        // Reset absorbed counters on every group (recomputed below) — 어느 종류가
        // 흡수하는 쪽이 될지는 패스 순서에 달렸으므로 전 그룹을 초기화한다.
        _allLabelMarkers(instance).forEach(function(m) {
            var e = m.getElement && m.getElement(); if (e) e.__absorbedCount = 0;
        });

        // 패스 순서 = 충돌 우선순위. 구체적인 대상이 먼저 자리를 잡고, 넓은
        // 대상이 그 자리를 피한다(겹치면 넓은 쪽이 접힌다).
        // 쌓임 순서(LABEL_Z)는 이와 별개 축이다 — 그쪽은 site 가 위다.

        // Pass 1: 장치 pill · 값 키 (가장 구체적)
        var occ1 = runLabelCollisionWithClustering(
            instance.deviceLabelMarkers    || [], map, sp, instance, 'deviceClusterMarkers', []
        );

        // Pass 2: geo aot_device 이름 라벨
        var occ2 = runLabelCollisionWithClustering(
            instance.geoDeviceLabelMarkers || [], map, sp, instance, 'geoDeviceClusterMarkers', occ1
        );

        // Pass 3: 대지 + 구역 (가장 넓음 → 마지막)
        runLabelCollisionWithClustering(
            instance.siteZoneLabelMarkers  || [], map, sp, instance, 'siteZoneClusterMarkers', occ1.concat(occ2)
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
    /** 충돌 회피가 다루는 모든 라벨 마커(그룹 3종 합집합). */
    function _allLabelMarkers(instance) {
        return [].concat(
            instance.deviceLabelMarkers    || [],
            instance.geoDeviceLabelMarkers || [],
            instance.siteZoneLabelMarkers  || []
        );
    }

    function _renderAbsorbedDeviceBadges(instance, map) {
        if (instance.absorbBadges) instance.absorbBadges.forEach(function(m) { try { m.remove(); } catch (e) {} });
        instance.absorbBadges = [];
        // 그룹을 가리지 않는다: 흡수한 쪽이 site/zone 일 수도, 장치 라벨일 수도
        // 있다(패스 순서에 따라 달라진다). 어느 쪽이든 "+N" 으로 드러내지 않으면
        // 가려진 라벨이 조용히 사라진다.
        _allLabelMarkers(instance).forEach(function(m) {
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

        // wOpts.device_ids is the Device Filter's EXCLUDE list (see
        // utils_geo.collect_devices docstring: placing a device on the map IS
        // showing it, so the filter hides the few rather than whitelisting the
        // many). Geo-design labels come from a separate fetch than the device
        // markers, so the exclusion has to be re-applied here too.
        const excludedDeviceIds = new Set();
        const _fetchIdsLbl = wOpts.map_device_ids || wOpts.device_ids;
        if (_fetchIdsLbl) {
            String(_fetchIdsLbl).split(',').forEach(function(id) {
                const t = id.trim();
                if (t) {
                    excludedDeviceIds.add(t);
                    if (t.includes('::')) excludedDeviceIds.add(t.split('::')[0]);
                }
            });
        }
        const isStrictDeviceLabelFilter = excludedDeviceIds.size > 0;

        // Theme colors from geo/design panel settings (mirrors shape fill color logic above)
        const labelTheme = wOpts.theme_config || (vars && vars.theme) || {};
        const _LT = window.AoTGeoTheme;
        // 장치 라벨은 이 시점에 장치 종류를 모른다(label_aux 는 parent_type 만 들고
        // 온다). 예전에는 그 자리에 input 색을 박아 넣어, output·function 라벨까지
        // 전부 input 색으로 칠해졌다 — 상태가 도착해도 OFF 장치는 회색으로만 덮여
        // 끝내 정정되지 않았다. 종류를 모르는 동안에는 장치 공통색을 쓰고,
        // _updateGeoDesignDeviceLabels 가 장치 상태와 함께 종류별 색으로 정정한다.
        const COLOR_MAP = {
            'site':       _LT.color('site', labelTheme),
            'zone':       _LT.color('zone', labelTheme),
            'facility':   _LT.color('facility', labelTheme),
            'equipment':  _LT.color('equipment', labelTheme),
            'device':     _LT.color('device', labelTheme),
            'aot_device': _LT.color('device', labelTheme)
        };
        // parent_type → 공용 z-order 표(LABEL_Z)의 종류 키.
        // 장치 라벨(device/aot_device)은 여기서 실제 장치 종류를 아직 모른다
        // (_deviceTypeMap 은 addDeviceMarkers 에서 만들어진다) — 일단 output 단으로
        // 두고, 그쪽에서 input/function 으로 정정한다(_applyGeoDeviceLabelZ).
        const ZKIND_MAP = {
            'site':       'site',
            'zone':       'zone',
            'facility':   'facility',
            'equipment':  'equipment',
            'device':     'output',
            'aot_device': 'output'
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

                // Device Filter: hide the label for a device the user explicitly excluded.
                if (pType === 'aot_device' && isStrictDeviceLabelFilter) {
                    const _devLabelId = String(props.device_id || props.parent_id || props.db_id || '');
                    const _devLabelBase = _devLabelId.split('::')[0];
                    if (excludedDeviceIds.has(_devLabelId) || excludedDeviceIds.has(_devLabelBase)) return;
                }

                const color  = COLOR_MAP[pType] || '#666';
                const zKind  = ZKIND_MAP[pType] || 'zone';
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

                // 구역 라벨 2행 — 1행 이름, 2행 대표값. 시설 bay 칩과 같은
                // 문법이다(_updateZoneLabelStatus 가 값·색을 채운다). 구역
                // 라벨이 이름만 달고 있어서, 어디가 문제인지 알려면 하나씩
                // 열어 봐야 했다.
                if (pType === 'zone') {
                    // 구역 uuid 는 라벨에 직접 없다 — node_id 로만 이어진다
                    // (클릭 콜백도 같은 경로를 쓴다: _zonesByNodeId).
                    el.dataset.zoneNodeId = String(props.parent_node_id || '');
                    // 문제 점의 기준 상자는 이름 줄이다 — 라벨 요소 자체에
                    // position 을 주면 maplibre 의 절대배치를 덮어써서 라벨이
                    // 전체 폭 막대로 흘러내린다.
                    nameDiv.classList.add('aot-zone-label-head');
                    const zValDiv = document.createElement('div');
                    zValDiv.className = 'aot-zone-label-val';
                    zValDiv.style.display = 'none';
                    el.appendChild(zValDiv);
                }

                const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
                    .setLngLat([coords[0], coords[1]])
                    .addTo(map);

                // 공용 z-order + "고른 라벨을 앞으로" (LABEL_Z / _wireLabelStacking).
                // 충돌 회피가 꺼져 있거나 아직 클러스터 중이면 라벨이 그냥 겹쳐
                // 쌓이므로, 스택에 묻힌 라벨을 집어낼 수단이 반드시 필요하다.
                var _restoreZ = _wireLabelStacking(instance, el, zKind);

                // Click → popup (이름 + 공용 노트 블록)
                (function(lngLat, popupName, popupArea, tId, tType, nodeId) {
                    // 호버 예열 — 누르기 전에 응답을 받아 둔다. 예열은 공유
                    // 캐시에 담기므로 클릭이 안 와도 버려지지 않고, 여러 번
                    // 스쳐도 TTL 안에서는 한 번만 나간다.
                    if (tType === 'zone' || tType === 'site') {
                        el.addEventListener('mouseenter', function () {
                            var byNode = (tType === 'zone'
                                ? instance._zonesByNodeId : instance._sitesByNodeId) || {};
                            warmModal(tType, byNode[nodeId]);
                        });
                    }
                    el.addEventListener('click', function(e) {
                        e.stopPropagation();
                        instance._pinLabelToFront(el, _restoreZ);
                        // zone label → zone modal (if callback registered)
                        if (tType === 'zone' && instance._onZoneLabelClick) {
                            instance._onZoneLabelClick(nodeId, popupName);
                            return;
                        }
                        // site label → 필지 요약 모달. 콜백이 없으면(사이트
                        // GeoJSON 을 아직 못 받았거나 도형·라벨이 모두 꺼진 경우)
                        // 아래의 옛 팝업으로 흘러간다.
                        if (tType === 'site' && instance._onSiteLabelClick) {
                            instance._onSiteLabelClick(nodeId, popupName);
                            return;
                        }
                        if (instance._labelPopup) { instance._labelPopup.remove(); }
                        // 노트 블록은 모달과 **같은** 공용 컴포넌트다. 예전에는
                        // 여기만 전체폭 딥그린 슬래브 + 한 줄 미리보기여서, 같은
                        // 지도에서 라벨을 눌렀을 때와 도형을 눌렀을 때 노트 문이
                        // 아예 다른 물건처럼 보였다.
                        var html = '<div class="aot-popup-body">'
                            + '<div class="aot-popup-header">'
                            + '<div class="aot-popup-title" style="margin:0">' + popupName + '</div>'
                            + '<span class="aot-link-badges-slot"></span>'
                            + '</div>'
                            + (popupArea ? '<div class="aot-popup-subtitle">' + popupArea + '</div>' : '')
                            + '<hr class="aot-popup-divider">'
                            + window.AoTNotesBlock.html()
                            + '</div>';
                        instance._labelPopup = new maplibregl.Popup({ offset: 12, closeOnClick: true, className: 'aot-popup aot-popup--label' })
                            .setLngLat(lngLat)
                            .setHTML(html)
                            .addTo(map);
                        instance._labelPopup.on('close', function () { instance._unpinLabel(el); });
                        (function (popupRef) {
                            var root = popupRef.getElement &&
                                       popupRef.getElement();
                            if (!root) return;
                            window.AoTNotesBlock.wire(root,
                                { targetId: tId, targetType: tType, name: popupName || '' },
                                { beforeOpen: function () {
                                    try { popupRef.remove(); } catch (e) {}
                                } });
                        }(instance._labelPopup));
                        // 배터리·통신 배지 — 장치 라벨에서만. site/zone 라벨은 장치가
                        // 아니라 조회해 봐야 늘 빈 응답이다.
                        if (tType === 'aot_device' && window.AoTSensorLabel &&
                            window.AoTSensorLabel.fetchStatus) {
                            (function (popupRef) {
                                window.AoTSensorLabel.fetchStatus(tId).then(function (all) {
                                    var root = popupRef.getElement && popupRef.getElement();
                                    if (!root || instance._labelPopup !== popupRef) return;
                                    window.AoTSensorLabel.fillLinkBadges(root, all[tId]);
                                });
                            }(instance._labelPopup));
                        }
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
    /**
     * Sensor-label custom options (single source of truth).
     *
     * Module scope on purpose: the facility fitting labels, the style-reload
     * re-attach path AND addDeviceMarkers (zone / bare-map Input labels) must all
     * read the SAME options. While each site had its own inline copy, an Input
     * placed in a zone silently ignored the sensor-label settings that the very
     * same Input would have obeyed inside a facility.
     */
    /**
     * onLabelEl callback for AoTMapSensorLabels.attach(): gives every facility
     * fitting-sensor label the same base z-order + hover/click "bring to front"
     * as every other label, and returns pin/unpin hooks for its detail modal.
     * The sensor-label module has no widget instance, so the pin state lives here.
     */
    function _sensorLabelSelectHook(uniqueId) {
        return function (el) {
            const inst = window.AoTWidgetInstances[uniqueId];
            if (!inst) return null;
            const restore = _wireLabelStacking(inst, el, 'input');
            return {
                pin:   function () { inst._pinLabelToFront(el, restore); },
                unpin: function () { inst._unpinLabel(el); }
            };
        };
    }

    /**
     * Effective facility /runtime poll period, in seconds (single source of truth).
     *
     * ONE /runtime response feeds three consumers — actuator chips (output state),
     * bay chips (output state + representative input value) and the fitting sensor
     * labels (input values) — so they must agree on ONE rate. Letting the sensor
     * labels follow input_update_interval alone desynced them: with the 300s input
     * default the fitting labels went 10x staler (30s -> 300s) while the very same
     * number on the bay chip, riding the 5s output poll, stayed fresh.
     *
     * Both knobs are honored by taking the SHORTER period — asking for fresh input
     * values necessarily means fetching the response that carries them.
     *
     * This does NOT weaken the load protections, which live downstream and are the
     * actual governors (measured 2026-08-12, 4 facilities): AoTFacilityRuntime
     * coalesces concurrent callers and caches for 8s (aot-facility-runtime.js), so
     * the network settles at ~1 request / 10s / facility no matter how fast this
     * ticks, and aot-map-sensor-labels.js keeps its own Math.max(30, ...) floor.
     * With the defaults (input 300 / output 5) this returns 5 -> the label poller
     * floors to 30s, exactly the historical value.
     */
    function _runtimePollSeconds(o) {
        o = o || {};
        var cands = [o.input_update_interval, o.output_update_interval]
            .map(function (v) { return parseFloat(v); })
            .filter(function (n) { return !isNaN(n) && n > 0; });
        if (cands.length) { return Math.min.apply(null, cands); }
        var p = parseFloat(o.period);
        return (!isNaN(p) && p > 0) ? p : 60;
    }

    function _sensorLabelOptsFrom(o, uniqueId) {
        o = o || {};
        return {
            onLabelEl: uniqueId ? _sensorLabelSelectHook(uniqueId) : undefined,
            show:         o.show_sensor_labels !== false && o.show_sensor_labels !== 'false',
            style:        o.sensor_label_style || 'circle',
            max_channels: parseInt(o.sensor_label_max_channels || 1, 10),
            decimals:     parseInt(o.sensor_label_decimals != null ? o.sensor_label_decimals : 1, 10),
            // 위젯 옵션 'Label Text Size'(global_label_size)는 phrase 그대로
            // "지도의 **모든** 라벨" 크기다. 예전엔 site/zone/facility 이름 라벨과
            // 장치 pill 만 반영하고 측정값 키(시설 센서 라벨 + 구역/지도 Input 키)는
            // 고정 0.85em 이라, 이름은 커지는데 값은 그대로인 채로 남았다.
            size_em:      parseFloat(o.sensor_label_size || 0.85) *
                          (parseFloat(o.global_label_size) || 1.0),
            bg:           o.sensor_label_bg || 'rgba(15,23,42,0.78)',
            fg:           o.sensor_label_fg || '#f8fafc',
            offset_y:     parseFloat(o.sensor_label_offset_y || 0),
            opacity:      o.sensor_label_opacity != null ? parseFloat(o.sensor_label_opacity) : 0.7,
            popup:        o.sensor_popup_enabled !== false && o.sensor_popup_enabled !== 'false',
            // Label collision avoidance (keep spacing instead of hiding) — uses the custom_option 'label_spacing' px.
            collision:    o.enable_label_collision !== false && o.enable_label_collision !== 'false',
            spacing:      (function () { var s = parseInt(o.label_spacing, 10); return isNaN(s) ? 0 : s; })(),
            // 시설/구역 라벨은 INPUT 값을 보여주므로 input_update_interval 을 따른다.
            // 단 같은 /runtime 응답을 쓰는 액추에이터·구역 칩 폴러와 반드시 같은
            // 주기여야 하므로 판정은 _runtimePollSeconds 한 곳에서만 한다.
            refresh_seconds: _runtimePollSeconds(o),
            // 시설 fitting 센서 라벨도 결국 Input 의 측정값 키다 — 공용 z-order 의
            // input 단을 그대로 쓴다. 예전에는 label_priority_facility 토글이
            // 이 값을 7/1 로 뒤집어 같은 지도 안에서 키가 site/zone 위로 갔다
            // 아래로 갔다 했다. 그 토글은 이제 충돌 회피·줌 LOD 프리셋
            // (AoTMapLabelLayers) 에만 쓰이고, 쌓임 순서는 LABEL_Z 로 고정된다.
            priority_z:   LABEL_Z.input
        };
    }

    // ── 모달 셸 ───────────────────────────────────────────────────────────────
    // 하나의 셸이 세 가지로 뜨고, 어느 것으로 뜰지는 **기기**가 정한다.
    // 사용자 설정 항목은 만들지 않는다.
    //
    //   sheet  스마트폰. 아래에서 올라오는 시트, 위쪽은 지도(+ 지도 전체화면).
    //   side   그 밖(데스크탑·태블릿). 위젯 안 오른쪽 도킹. 크기로 다시 가르지
    //          않는다 — 창을 조금 좁혔다고 창 모양이 바뀌면 안 된다.
    //   center **지도 모달에는 더 이상 쓰지 않는다.** 이미 열린 패널 **위**에 뜨는
    //          작은 중첩 창(예약 휠 `output-sched-…`, 행 고르기 `rowpick-…`)과,
    //          지도가 없는 호출자(시설 위젯)만 이 모양으로 남는다.
    //
    // **왜 도킹인가**: 예전에는 어느 계층을 눌러도 화면 전체를 덮는 카드가 떠서,
    // 방금 누른 도형이 카드 **뒤**에 있었다(화면 중앙을 눌렀으니 당연하다).
    // 게다가 바깥을 누르면 닫혔으므로 "지도를 보려고 지도를 만지면 창이 닫힌다".
    // 모달 상태와 지도를 대조할 방법이 아예 없었다.
    //
    // 패널은 지도를 **밀지 않고 덮는다**. 캔버스를 줄이면 타일 재요청과 리페인트가
    // 따라오는데, 가려진 만큼을 카메라 padding 으로 비키는 편이 훨씬 싸고 같은
    // 효과를 낸다(그 연동은 2단계).
    // (크기 문턱은 없앴다 — 모드는 **기기**가 정한다: 스마트폰이면 시트,
    //  아니면 옆 도킹. 크기로 다시 가르면 창을 조금 좁혔을 뿐인데 창의 모양이
    //  바뀌어, 같은 화면에서 같은 동작의 결과가 달라 보인다.)

    // 열려 있는 셸의 close 함수 스택. Esc 는 **맨 위 하나만** 닫는다 — 예약 휠이
    // 구역 패널 위에 떠 있을 때 Esc 로 둘 다 닫히면 방금 한 조작의 맥락이 사라진다.
    var _modalStack = [];
    var _escBound = false;

    // ── 지도 최대화 — **브라우저 뷰포트 기준**(네이티브 전체화면 API 아님) ──
    //
    // 예전에는 데스크탑에서만 `requestFullscreen()` 을 썼다. 그러면 지도가
    // 브라우저의 top layer 로 올라가 **모니터 전체**를 덮는데, 이 화면에서는
    // 그것이 두 가지를 깬다 — geo/design 이 같은 이유로 이미 클래스 방식으로
    // 옮겨 갔다(`_toggleMaximize`, aot-geo-events.js):
    //
    //   1. **top layer 밖의 UI 가 전부 사라진다.** 모달 셸은 위젯 안에 도킹하니
    //      따라가지만, 토스트·드로어처럼 <body> 에 붙는 것들은 뒤로 숨는다.
    //   2. **임베드 환경에서 거부된다.** iframe 에 `allow="fullscreen"` 이
    //      없으면 "Permissions check failed" 로 실패한다. AoT 를 엣지 프록시
    //      뒤에서 임베드해 여는 것은 정상 사용 경로다.
    //
    // 그래서 iOS 폴백이던 의사 전체화면(`.aot-map-pseudo-fullscreen`, map.css)을
    // **모든 환경의 기본 동작**으로 올린다. 위젯을 <body> 로 옮기는 것은 그대로
    // 필요하다 — grid-stack 항목의 `transform` 이 stacking context 이자
    // (iOS 에서는) `position: fixed` 의 컨테이닝 블록이라, 그 안에 두면 지도가
    // 내비바 밑에 깔린다.
    function _isMaximized(target) {
        return !!(target && target.classList.contains('aot-map-pseudo-fullscreen'));
    }

    function _toggleMapMaximize(target) {
        if (!target) return;
        var doc = document;
        var entering = !_isMaximized(target);
        // Esc 로 빠져나올 수 있어야 한다. 이 핸들러는 원래 모달을 처음 열 때
        // 붙는데, 모달을 한 번도 안 열고 최대화만 한 경우에는 없다.
        _ensureEscHandler();

        if (entering) {
            if (!target._aotFsPlaceholder) {
                var ph = doc.createComment('aot-fs-placeholder');
                target._aotFsPlaceholder = ph;
                if (target.parentNode) target.parentNode.insertBefore(ph, target);
            }
            doc.body.appendChild(target);
            target.classList.add('aot-map-pseudo-fullscreen');
            doc.body.classList.add('aot-map-fullscreen-active');
        } else {
            target.classList.remove('aot-map-pseudo-fullscreen');
            doc.body.classList.remove('aot-map-fullscreen-active');
            var ph2 = target._aotFsPlaceholder;
            if (ph2 && ph2.parentNode) {
                ph2.parentNode.insertBefore(target, ph2);
                ph2.parentNode.removeChild(ph2);
            }
            target._aotFsPlaceholder = null;
        }

        // 버튼의 모양과 이름을 상태에 맞춘다(geo/design 과 같은 문법).
        var uid = (target.id || '').replace(/^aot-map-/, '');
        var btn = document.getElementById('tool-fullscreen-' + uid);
        if (btn) {
            var icon = btn.querySelector('i');
            if (icon) {
                icon.classList.toggle('fa-expand', !entering);
                icon.classList.toggle('fa-compress', entering);
            }
            var T = window._ || function (x) { return x; };
            var label = entering ? T('Exit fullscreen') : T('Fullscreen');
            btn.setAttribute('title', label);
            btn.setAttribute('aria-label', label);
        }

        // MapLibre 는 컨테이너 크기를 스스로 감시하지 않는다. 레이아웃이 자리를
        // 잡은 뒤 한 번, 트랜지션까지 끝난 뒤 한 번 더 잰다.
        var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uid];
        var resize = function () { try { if (inst && inst.map) inst.map.resize(); } catch (e) {} };
        if (window.requestAnimationFrame) requestAnimationFrame(resize); else setTimeout(resize, 16);
        setTimeout(resize, 450);
    }

    function _ensureEscHandler() {
        if (_escBound) return;
        _escBound = true;
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape' && e.keyCode !== 27) return;
            if (!_modalStack.length) {
                // 열린 모달이 없으면 최대화를 푼다. 네이티브 전체화면이 아니라
                // 뷰포트를 덮는 방식이라 브라우저가 Esc 를 대신 처리해 주지
                // 않는다 — 직접 받는다(geo/design 과 같다).
                var fsEl = document.querySelector('.aot-map-container.aot-map-pseudo-fullscreen');
                if (fsEl) { e.preventDefault(); _toggleMapMaximize(fsEl); }
                return;
            }
            // 입력 중 Esc 는 그 컴포넌트 몫이다(자동완성 닫기 등).
            var t = e.target;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' ||
                      t.tagName === 'SELECT' || t.isContentEditable)) return;
            e.preventDefault();
            _modalStack[_modalStack.length - 1]();
        });
    }

    // 위젯의 **주 패널**이면서 uid 에 접미사를 붙여 여는 자리. 도킹 대상이다.
    // 화이트리스트인 이유: 파생 uid 가 전부 도킹 대상은 아니다 — 예약 휠
    // ('output-sched-…')과 행 고르기('rowpick-…')는 이미 열린 패널 **위**에 뜨는
    // 중첩 창이라, 도킹하면 부모 패널 안에 갇히거나 부모를 통째로 가린다.
    // 사이트 목록은 반대다: 목록을 열어 둔 채 항목을 눌러 지도가 그리로 가는 것을
    // 봐야 고를 수 있다(`_navigateTo`). 덮는 모달로는 그 동작이 보이지 않는다.
    var PANEL_UID_SUFFIXES = ['-sitelist'];

    /** uid → 위젯 인스턴스 id (도킹 대상이 아니면 null). */
    function _widgetIdFromUid(uid) {
        if (!uid) return null;
        var W = window.AoTWidgetInstances || {};
        if (W[uid]) return uid;
        for (var i = 0; i < PANEL_UID_SUFFIXES.length; i++) {
            var suf = PANEL_UID_SUFFIXES[i];
            if (uid.length > suf.length && uid.slice(-suf.length) === suf) {
                var base = uid.slice(0, -suf.length);
                if (W[base]) return base;
            }
        }
        return null;
    }

    /**
     * 이 uid 를 도킹할 수 있으면 { host, mode } 를, 아니면 null(=중앙 모달).
     */
    function _panelHostFor(uid) {
        var wid = _widgetIdFromUid(uid);
        if (!wid) return null;
        var inst = window.AoTWidgetInstances[wid];
        if (!inst || !inst.map) return null;
        var host = document.getElementById('aot-map-' + wid);
        if (!host) return null;

        // ── 스마트폰: 시트 + 전체화면 ─────────────────────────────────────────
        // 폰에서는 위젯이 대개 화면의 일부라, 그 안에서 시트를 열면 지도 몫이
        // 손바닥만 해진다. 그래서 **모달을 여는 순간 지도를 전체화면으로 올린다**
        // (모니터 전체가 아니라 브라우저 뷰포트 — _toggleMapMaximize 주석 참조).
        // 우리가 올렸다는 표시를 남겨, 닫을 때 그 경우에만 되돌린다.
        if (_isPhoneClass()) {
            if (!_isMaximized(host)) {
                _toggleMapMaximize(host);
                host._aotFsByModal = true;
            }
            if (!host.clientWidth || !host.clientHeight) return null;
            // 눕히면 옆으로 — 가로에서는 높이가 곧 병목이다(폰을 눕히면 390px
            // 남짓). 아래에서 올라오는 시트는 그 높이를 다시 반으로 갈라 지도도
            // 모달도 못 쓰게 만든다. 폭은 남아도니 세로에서 부족했던 것과 정반대다.
            return { host: host, mode: _isLandscape() ? 'side' : 'sheet' };
        }

        // ── 그 밖(데스크탑·태블릿): **항상 옆에 도킹** ───────────────────────
        // 폰이 아니면 데스크탑 모드다. 크기로 다시 가르지 않는다 — 창을 조금
        // 좁혔다는 이유로 창이 화면 한가운데를 덮는 옛 모양으로 돌아가면, 같은
        // 화면에서 같은 동작을 해도 결과가 달라 보인다. 패널 폭은 clamp 라
        // 좁은 위젯에서는 알아서 줄어든다.
        // (시트는 쓰지 않는다. 아래에서 올라오는 시트는 폰 흉내처럼 보이고,
        //  옆으로 도킹할 수 있는데도 지도를 위아래로 반 토막 낸다.)
        if (!host.clientWidth || !host.clientHeight) return null;   // 숨은/접힌 위젯
        return { host: host, mode: 'side' };
    }

    // ── 모달을 열면 그 대상이 보이도록 지도를 옮긴다 ─────────────────────────
    // 패널이 지도를 가리지 않게 된 다음에도, 방금 연 도형이 화면 밖(또는 패널
    // 뒤)에 있으면 대조할 것이 없다. 그래서 모달을 여는 경로마다 이 함수를 부른다.
    //
    // **이미 잘 보이면 움직이지 않는다.** 매번 옮기면 사용자가 방금 맞춰 둔 축척과
    // 방향감각을 빼앗는다 — 특히 옆 도형을 연달아 눌러 비교하는 중에는 화면이
    // 계속 튄다. "잘 보인다"의 기준은 둘: 대상이 패널을 뺀 가시 영역 **안**에
    // 있고, 그 영역에서 너무 작지 않다(폭·높이 중 하나가 12% 이상).

    /** geometry 의 좌표를 전부 훑어 [[w,s],[e,n]]. 점 하나면 폭 0 인 상자다. */
    function _geomBounds(geometry) {
        if (!geometry || !geometry.coordinates) return null;
        var w = Infinity, s = Infinity, e = -Infinity, n = -Infinity, seen = false;
        (function walk(a) {
            if (!a) return;
            if (typeof a[0] === 'number') {
                var lng = a[0], lat = a[1];
                if (isNaN(lng) || isNaN(lat)) return;
                seen = true;
                if (lng < w) w = lng; if (lng > e) e = lng;
                if (lat < s) s = lat; if (lat > n) n = lat;
                return;
            }
            if (Array.isArray(a)) a.forEach(walk);
        })(geometry.coordinates);
        return seen ? [[w, s], [e, n]] : null;
    }

    /**
     * 받아 온 GeoJSON 을 uuid → 도형 캐시에 담는다.
     *
     * 지도에 **레이어로 올라가지 않는 도형**이 있기 때문에 필요하다 — 구역
     * 폴리곤은 `show_zone_shape` 가 꺼져 있으면 그리지 않지만(라벨만 뜬다)
     * 구역 모달은 여전히 열린다. 소스만 뒤지면 그런 도형은 옮길 곳도 강조할
     * 것도 못 찾고, 모달을 열어도 지도가 아무 반응을 하지 않는다.
     *
     * 도형의 정체가 자리마다 다른 키에 들어 있으므로(f.id · shape_uuid ·
     * properties.id) 있는 것을 모두 키로 등록한다.
     */
    function _cacheShapes(uniqueId, geojson) {
        var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uniqueId];
        if (!inst || !geojson) return;
        var feats = geojson.features || [];
        var cache = inst._shapeCache || (inst._shapeCache = {});
        feats.forEach(function (f) {
            if (!f || !f.geometry) return;
            var p = f.properties || {};
            var entry = {
                geometry: f.geometry,
                color: p.color || null,
                aot_type: String(p.aot_type || p.category || '').toLowerCase() || null
            };
            [f.id, p.shape_uuid, p.unique_id, p.id].forEach(function (k) {
                if (k) cache[String(k)] = entry;
            });
        });
    }

    /**
     * 이 위젯이 지도에 올린 GeoJSON 중 uuid 가 맞는 feature.
     * 도형의 정체는 자리마다 다른 키에 들어 있다(shape_uuid · unique_id ·
     * node_id) — 하나만 보면 종류에 따라 조용히 못 찾는다.
     */
    function _findFeature(uid, uuid) {
        if (!uuid) return null;
        var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uid];
        var srcs = inst && inst.sources;
        if (!srcs || typeof srcs.forEach !== 'function') return null;
        // 같은 장치가 **마커와 구역 폴리곤을 둘 다** 갖는 경우가 흔하다(장치
        // 목록 48건 중 점 32 · 면 16). 그때는 면을 고른다 — 테두리를 두를 수 있고
        // 카메라도 면 기준이라야 그 장치가 맡은 범위가 보인다. 먼저 찾은 것을
        // 그냥 쓰면 소스 순서에 따라 마커가 이기는 날과 아닌 날이 갈린다.
        var hit = null, hitSrc = null;
        var _isArea = function (f) {
            var t = (f && f.geometry && f.geometry.type) || '';
            return t.indexOf('Polygon') >= 0 || t.indexOf('LineString') >= 0;
        };
        var scan = function (gj, srcId) {
            if (!gj) return;
            if (hit && _isArea(hit)) return;          // 이미 면을 찾았으면 끝
            var feats = gj.features || (gj.type === 'Feature' ? [gj] : null);
            if (!feats) return;
            for (var i = 0; i < feats.length; i++) {
                var p = (feats[i] && feats[i].properties) || {};
                if (p.shape_uuid === uuid || p.unique_id === uuid ||
                    p.uuid === uuid || p.device_id === uuid || p.node_id === uuid) {
                    if (!hit || (_isArea(feats[i]) && !_isArea(hit))) {
                        hit = feats[i];
                        hitSrc = srcId || null;
                    }
                    if (_isArea(hit)) return;
                }
            }
        };
        srcs.forEach(function (gj, srcId) { scan(gj, srcId); });
        if (hit && _isArea(hit)) return { feature: hit, sourceId: hitSrc };
        // 자기 소스를 직접 붙이는 레이어(구획 등)는 instance.sources 에 없다 —
        // 지도에 올라간 geojson 소스를 그대로 훑는다. 새 레이어가 늘어도 따라온다.
        try {
            var style = inst.map && inst.map.getStyle && inst.map.getStyle();
            var ids = style && style.sources ? Object.keys(style.sources) : [];
            for (var k = 0; k < ids.length && !hit; k++) {
                var src = inst.map.getSource(ids[k]);
                if (src && src._data && typeof src._data !== 'string') scan(src._data, ids[k]);
                if (hit && _isArea(hit)) break;
            }
        } catch (e) {}
        if (hit) return { feature: hit, sourceId: hitSrc };
        // 지도에 레이어가 없는 도형(구역이 대표적이다)은 목록이 받아 둔 overlays
        // 캐시에서 찾는다. 여기까지 오지 않으면 구역 모달은 옮길 곳도 강조할 것도
        // 없이 조용히 아무 일도 하지 않는다.
        var cached = inst._shapeCache && inst._shapeCache[uuid];
        if (cached) {
            return {
                feature: { geometry: cached.geometry,
                           properties: { color: cached.color,
                                         aot_type: cached.aot_type } },
                sourceId: null
            };
        }
        return null;
    }

    // ── 연 도형을 지도에서 강조한다 ───────────────────────────────────────────
    // 카메라만 옮기면 "이 패널이 **어느** 도형 얘기인지" 는 여전히 안 보인다.
    // 겹친 구획이나 이름이 비슷한 구역이 나란히 있으면 특히 그렇다.
    //
    // 원 레이어의 paint 를 바꾸지 않는다 — 레이어는 도형 전체를 그리므로 거기서
    // 두께를 올리면 **모든** 도형이 두꺼워진다. 대신 그 도형 하나만 담은 강조
    // 레이어를 위에 얹고, 닫을 때 통째로 지운다(원복이 곧 삭제라 되돌릴 상태가
    // 남지 않는다).
    var HL_SRC = 'aot-focus-hl-src-';
    var HL_LYR = 'aot-focus-hl-line-';

    /** 이 소스를 그리는 첫 line 레이어의 색·두께(못 찾으면 기본값). */
    function _lineStyleOf(map, sourceId) {
        var style = { color: null, width: 2 };
        try {
            var layers = (map.getStyle() || {}).layers || [];
            for (var i = 0; i < layers.length; i++) {
                var L = layers[i];
                if (L.type !== 'line' || L.source !== sourceId) continue;
                var w = map.getPaintProperty(L.id, 'line-width');
                var c = map.getPaintProperty(L.id, 'line-color');
                if (typeof w === 'number') style.width = w;
                if (typeof c === 'string') style.color = c;
                break;
            }
        } catch (e) {}
        return style;
    }

    var HL_PT = 'aot-focus-hl-pt-';

    function _clearHighlight(uid) {
        var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uid];
        var map = inst && inst.map;
        if (!map) return;
        try {
            if (map.getLayer(HL_LYR + uid)) map.removeLayer(HL_LYR + uid);
            if (map.getLayer(HL_PT + uid)) map.removeLayer(HL_PT + uid);
            if (map.getSource(HL_SRC + uid)) map.removeSource(HL_SRC + uid);
        } catch (e) {}
    }

    function _highlightShape(uid, feature, sourceId) {
        var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uid];
        var map = inst && inst.map;
        if (!map || !feature || !feature.geometry) return;
        var t = feature.geometry.type || '';
        var isPoint = t.indexOf('Polygon') < 0 && t.indexOf('LineString') < 0;

        _clearHighlight(uid);
        var base = _lineStyleOf(map, sourceId);
        var props = feature.properties || {};

        // 색의 정본은 테마(theme_config) 하나다 — 강조도 도형을 칠한 것과 **같은
        // 함수**로 정한다. 하드코딩 폴백을 새로 만들지 않는다.
        //
        // 장치는 `color(...)` 가 아니라 `deviceColor(...)` 여야 한다. 장치 도형의
        // `aot_type` 은 종류와 무관하게 'aot_device' 라서, 그것으로 조회하면
        // input·output·function 이 전부 장치 공통색 하나로 수렴한다(실측: 입력
        // 마커가 #995aff = device 기본색으로 강조됐다). 지도가 도형을 칠할 때
        // 쓰는 expression 도 deviceColor 로 만들어져 있다.
        var color = null;
        var T = window.AoTGeoTheme;
        var theme = (inst && inst._geoTheme) || null;
        try {
            if (T && props.device_type)   color = T.deviceColor(props.device_type, theme);
            else if (T && props.aot_type) color = T.color(props.aot_type, theme);
        } catch (e) {}
        // 구획은 사용자가 고른 색이 테마 기본값을 이긴다(GeoPlot.color).
        if (props.plot_uuid && props.color) color = props.color;
        if (!color) color = base.color || props.color || '#ffffff';
        try {
            map.addSource(HL_SRC + uid, {
                type: 'geojson',
                data: { type: 'Feature', geometry: feature.geometry, properties: {} }
            });
            if (isPoint) {
                // 점으로만 있는 장치(마커)는 두를 테두리가 없다 — 자리에 고리를
                // 그린다. 채우지 않는 이유는 마커 라벨을 가리지 않기 위해서다.
                map.addLayer({
                    id: HL_PT + uid,
                    type: 'circle',
                    source: HL_SRC + uid,
                    paint: {
                        'circle-radius': 14,
                        'circle-color': 'rgba(0,0,0,0)',
                        'circle-stroke-color': color,
                        'circle-stroke-width': 4,   // 도형 테두리(2배)와 같은 무게
                        'circle-stroke-opacity': 1
                    }
                });
            } else {
                map.addLayer({
                    id: HL_LYR + uid,
                    type: 'line',
                    source: HL_SRC + uid,
                    paint: {
                        'line-color': color,
                        'line-width': base.width * 2,   // 원래 두께의 2배
                        'line-opacity': 1               // 가장 진하게
                    }
                });
            }
        } catch (e) {}
    }

    // ── 도형을 맞출 때 쓸 최대 줌 ────────────────────────────────────────────
    //
    // 예전에는 18 고정이었다. 그러면 **작은 대상만 제약을 받는다** — 실측한
    // "꽉 차는 줌"은 필지 16.3 · 구역 17.3 으로 여유가 있는데, 구획 18.4 ·
    // 장치 폴리곤 18.6 이라 이 둘만 상한에 걸려 화면을 덜 채웠다. 화면이 클수록
    // 도형의 지리적 크기는 그대로라 상대적으로 더 작게 느껴진다.
    //
    // 얼마까지 올릴 수 있는지는 **베이스맵이 정한다**: 벡터 타일은 오버줌해도
    // 선과 라벨이 선명하지만, 래스터(위성·항공)는 소스의 maxzoom 을 넘으면
    // 그때부터 픽셀이 뭉갠다. 그래서 고정값 대신 지금 깔린 베이스에서 읽는다.
    var FIT_ZOOM_VECTOR = 20;   // 벡터 전용 지도의 상한
    var FIT_ZOOM_FLOOR  = 18;   // 예전 고정값 — 이보다 내려가지는 않는다

    function _fitMaxZoom(map) {
        var z = null;
        try {
            var style = map.getStyle() || {};
            var sources = style.sources || {};
            // 실제로 그려지는 소스만 본다 — 스타일에 남아 있어도 레이어가 없거나
            // 꺼져 있으면 화면에 아무 영향이 없다.
            var used = {};
            (style.layers || []).forEach(function (l) {
                if (!l.source) return;
                if (l.layout && l.layout.visibility === 'none') return;
                used[l.source] = true;
            });
            Object.keys(sources).forEach(function (id) {
                if (!used[id] || sources[id].type !== 'raster') return;
                var mz = sources[id].maxzoom;
                if (typeof mz !== 'number') {
                    // 스타일에 없으면 TileJSON 로드 뒤 소스 객체에 채워진다.
                    var live = map.getSource(id);
                    if (live && typeof live.maxzoom === 'number') mz = live.maxzoom;
                }
                if (typeof mz !== 'number') return;
                // 한 단계 오버줌까지는 허용한다 — 픽셀이 2배로 늘 뿐 판이 깨지진
                // 않고, 그 한 단계가 작은 도형에는 결정적이다.
                var cand = mz + 1;
                z = (z == null) ? cand : Math.min(z, cand);
            });
        } catch (e) {}
        if (z == null) z = FIT_ZOOM_VECTOR;      // 래스터가 없다 = 벡터 지도
        var hard = (map.getMaxZoom && map.getMaxZoom()) || 22;
        return Math.max(FIT_ZOOM_FLOOR, Math.min(z, hard));
    }

    // ── 기울어진 지도에서도 정확히 맞추기 ────────────────────────────────────
    //
    // `cameraForBounds` 는 **pitch 를 계산에 넣지 않는다**(`pitch: 0` 을 명시로
    // 넘겨도 같은 값이 나온다). 화면이 기울어져 있으면 같은 줌에서도 도형이
    // 원근으로 멀어져 훨씬 작게 투영된다 — 실측(pitch 58°): 같은 카메라에서
    // 도형이 가시 높이의 48%, 눕히면 100%. 게다가 `offset` 도 어긋난다(화면
    // 위쪽은 멀고 아래쪽은 가까워 같은 픽셀이 다른 지리 거리에 대응한다).
    //
    // 공식으로 풀지 않고 **가상 카메라에 올려놓고 재서 맞춘다.** pitch·bearing·
    // 위도가 모두 섞인 값이라 근사식은 곧 틀어지지만, 실제 투영을 재면 그 전부가
    // 이미 반영돼 있다. `map.transform.clone()` 은 화면을 건드리지 않으므로
    // 사용자에게는 **이동이 한 번**으로 보인다(도착 뒤 다시 당기는 방식은 줌이
    // 두 번 일어나 눈에 거슬렸다).
    //
    // ⚠ `map.transform` 은 MapLibre 비공개 API 다. 없거나 모양이 바뀌면 아래
    // 폴백(cameraForBounds + offset)으로 내려간다 — 그 경우 기운 지도에서 도형이
    // 작게 잡히지만 동작은 한다.
    var FIT_SOLVE_ZOOM_STEPS   = 6;      // 줌 수렴
    var FIT_SOLVE_CENTER_STEPS = 4;      // 중심 수렴(줌 고정 뒤)
    var FIT_SOLVE_DAMPING      = 0.7;    // 줌·중심이 서로 얽혀 있어 감쇠가 필요하다

    /** 위도의 메르카토르 중간값 — 남북으로 긴 도형에서 산술평균은 어긋난다. */
    function _midLat(s, n) {
        var mY = function (lat) { return Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)); };
        var y = (mY(s) + mY(n)) / 2;
        return (Math.atan(Math.exp(y)) - Math.PI / 4) * 360 / Math.PI;
    }

    /**
     * 도형이 가시 사각형을 채우면서 그 한가운데 오는 카메라를 푼다.
     * @return { center, zoom } — 풀지 못하면 null(호출부가 폴백).
     */
    function _solveFitCamera(map, bounds, rect, startZoom, lockZoom) {
        var tr = null;
        try {
            tr = (map.transform && map.transform.clone) ? map.transform.clone() : null;
        } catch (e) { tr = null; }
        if (!tr || typeof tr.setLocationAtPoint !== 'function' ||
            typeof tr.locationPoint !== 'function') return null;

        var w = bounds[0][0], s = bounds[0][1], e = bounds[1][0], n = bounds[1][1];
        var corners = [[w, s], [e, s], [e, n], [w, n]];
        var anchor = { lng: (w + e) / 2, lat: _midLat(s, n) };
        // 목표 지점은 **중심 전용 좌표**다(rect.cx/cy — 위 _visibleMapRect 주석).
        // 다만 도형이 크면 그 자리에 두었을 때 아래위가 크롬에 물린다. 그래서
        // 도형 크기를 알게 된 뒤 **한계선 안으로 당긴다** — 겹치지 않는 선에서
        // 최대한 중앙이다. 공간 자체가 부족하면(도형이 가시 영역보다 큼) 위아래
        // 여백을 똑같이 나눈다.
        var base = { x: (rect.cx != null ? rect.cx : rect.x + rect.w / 2),
                     y: (rect.cy != null ? rect.cy : rect.y + rect.h / 2) };
        var lim = rect.limit;
        var clampAxis = function (v, size, lo, hi) {
            if (!lim) return v;
            var a = lo + size / 2, b = hi - size / 2;
            if (a > b) return (a + b) / 2;
            return Math.min(Math.max(v, a), b);
        };
        var tgt = { x: base.x, y: base.y };
        var maxZ = _fitMaxZoom(map);

        // 기울어진 지도에서 **투영은 폭발할 수 있다.** pitch 가 크면 화면 위쪽이
        // 지평선에 수렴하는데, 도형의 먼 변이 그 근처로 가면 y 가 화면의 수십 배로
        // 튄다(실측 pitch 60°·큰 필지: 도형 높이 6241px, 중심이 화면 밖 3232).
        // 그 값으로 줌을 풀면 카메라가 엉뚱한 데로 간다. 말이 안 되는 크기가 나오면
        // **푸는 것을 포기하고** 호출부의 폴백(cameraForBounds)으로 넘긴다 —
        // 그쪽은 pitch 를 무시해 도형이 작게 잡히지만, 적어도 화면 안에 든다.
        var SANE_SPAN = 4;   // 컨테이너의 4배
        var box = function () {
            var xs = [], ys = [];
            for (var i = 0; i < corners.length; i++) {
                var p = tr.locationPoint({ lng: corners[i][0], lat: corners[i][1] });
                if (!p || !isFinite(p.x) || !isFinite(p.y)) return null;
                xs.push(p.x); ys.push(p.y);
            }
            var l = Math.min.apply(null, xs), r = Math.max.apply(null, xs);
            var t = Math.min.apply(null, ys), b = Math.max.apply(null, ys);
            if ((r - l) > tr.width * SANE_SPAN || (b - t) > tr.height * SANE_SPAN) return null;
            return { l: l, r: r, t: t, b: b, w: r - l, h: b - t,
                     cx: (l + r) / 2, cy: (t + b) / 2 };
        };

        // lockZoom 이 오면 줌은 그대로 두고 중심만 맞춘다(사용자가 맞춰 둔 축척 유지).
        var z = (lockZoom != null) ? lockZoom : Math.min(maxZ, startZoom);
        var aim = { x: tgt.x, y: tgt.y };
        try {
            // 1단계 — 줌을 수렴시킨다. 중심은 매 회 따라 붙는다(둘이 얽혀 있다).
            for (var i = 0; lockZoom == null && i < FIT_SOLVE_ZOOM_STEPS; i++) {
                tr.zoom = z;
                tr.setLocationAtPoint(anchor, aim);
                var bb = box();
                if (!bb || bb.w <= 0 || bb.h <= 0) return null;
                if (lim) {
                    tgt.x = clampAxis(base.x, bb.w, lim.left, lim.right);
                    tgt.y = clampAxis(base.y, bb.h, lim.top, lim.bottom);
                }
                aim = { x: aim.x + (tgt.x - bb.cx), y: aim.y + (tgt.y - bb.cy) };
                var dz = Math.log2(Math.min(rect.w / bb.w, rect.h / bb.h));
                if (!isFinite(dz) || Math.abs(dz) < 0.02) break;
                z = Math.min(maxZ, z + dz * FIT_SOLVE_DAMPING);
            }
            // 2단계 — 줌을 고정하고 중심만 맞춘다(여기서는 곧바로 수렴한다).
            for (var k = 0; k < FIT_SOLVE_CENTER_STEPS; k++) {
                tr.zoom = z;
                tr.setLocationAtPoint(anchor, aim);
                var b2 = box();
                if (!b2) return null;
                if (lim) {
                    tgt.x = clampAxis(base.x, b2.w, lim.left, lim.right);
                    tgt.y = clampAxis(base.y, b2.h, lim.top, lim.bottom);
                }
                var ex = tgt.x - b2.cx, ey = tgt.y - b2.cy;
                if (Math.abs(ex) < 1 && Math.abs(ey) < 1) break;
                aim = { x: aim.x + ex, y: aim.y + ey };
            }
            tr.zoom = z;
            tr.setLocationAtPoint(anchor, aim);
            // **푼 결과를 그대로 믿지 않는다.** 마지막으로 한 번 더 재서, 도형이
            // 화면 안에 들어오고 중심이 목표에서 크게 벗어나지 않았을 때만 쓴다.
            // 위 반복이 수렴하지 못하는 경우가 있고(기운 지도 + 큰 도형), 그때
            // 그대로 넘기면 카메라가 화면 밖으로 날아간다.
            var fin = box();
            if (!fin) return null;
            if (Math.abs(fin.cx - tgt.x) > rect.W || Math.abs(fin.cy - tgt.y) > rect.H) return null;
            var c = tr.center;
            if (!c || !isFinite(c.lng) || !isFinite(c.lat)) return null;
            return { center: [c.lng, c.lat], zoom: z };
        } catch (e2) { return null; }
    }

    // ── 사용자가 확대해 둔 축척은 되돌리지 않는다 ────────────────────────────
    //
    // 일부러 크게 보려고 확대해 둔 상태에서 모달을 열면 계산값으로 **축소**되어
    // 도형이 도로 작아졌다. 대상을 화면에 들이는 것이 목적이지 축척을 정해 주는
    // 것이 목적은 아니다 — 이미 더 크게 보고 있다면 그대로 두고 **중심만** 옮긴다.
    //
    // 다만 무한정 봐줄 수는 없다. 멀리 확대해 다른 곳을 보다가 먼 대상을 열면
    // 도형이 화면을 크게 넘쳐 어디를 보는지 알 수 없다. 도형이 가시 영역의
    // **2배(줌 차 1단계)** 까지는 유지하고, 그보다 넘치면 계산값으로 맞춘다.
    var ZOOM_KEEP_MAX_OVER = 1.0;

    /** 유지할 줌(없으면 null). */
    function _keepUserZoom(map, fitZoom) {
        var cur = map.getZoom();
        if (!(cur > fitZoom)) return null;                  // 더 확대돼 있지 않다
        if (cur - fitZoom > ZOOM_KEEP_MAX_OVER) return null; // 너무 넘친다
        // 상한(_fitMaxZoom)으로 자르지 않는다 — 사용자가 그 위로 올려 둔 것도
        // 사용자의 선택이다. 상한은 **우리가 정할 때** 지키는 값이다.
        return cur;
    }

    /**
     * 모달 대상으로 지도를 옮긴다.
     * @param uid    위젯 인스턴스 id
     * @param target uuid 문자열, 또는 { geometry } / { lng, lat, zoom }
     */
    /**
     * 이 지도가 **잠겨 있는가**.
     *
     * 잠금의 목적은 "이 화면은 여기를 본다" 를 고정하는 것이다. 그래서 판정은
     * 저장된 옵션이 아니라 **지금 상호작용이 꺼져 있는가**로 한다 — 잠금은
     * 버튼으로 실행 중에 바뀌고(`_setMapInteraction`), 옵션은 저장 왕복이
     * 끝나야 최신이 된다. 둘을 각각 보면 방금 잠근 지도가 한 박자 동안 움직인다.
     */
    function _mapIsLocked(map) {
        try { return !!(map && map.dragPan && !map.dragPan.isEnabled()); }
        catch (e) { return false; }
    }

    function _focusMapOn(uid, target, opts) {
        opts = opts || {};
        var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uid];
        var map = inst && inst.map;
        if (!map || !target) return;

        var geometry = null, point = null;
        var doHighlight = opts.highlight !== false;
        if (typeof target === 'string') {
            var f = _findFeature(uid, target);
            geometry = f && f.feature && f.feature.geometry;
            if (f && doHighlight) _highlightShape(uid, f.feature, f.sourceId);
        } else if (target.geometry) {
            // geometry 를 직접 받은 자리(구획)는 소스를 모른다 — 색은 도형이
            // 실어 온 것을 쓰고 두께는 기본값이 된다.
            if (doHighlight) {
                _highlightShape(uid, { geometry: target.geometry,
                                       properties: target.properties || {} }, null);
            }
            geometry = target.geometry;
        } else if (target.lng != null && target.lat != null) {
            point = target;
        }

        // ⚠ **잠긴 지도는 옮기지 않는다.** 잠금은 "다른 곳으로 가지 않는다" 는
        // 뜻인데, 모달을 열 때마다 카메라가 대상으로 날아가면 그 뜻이 무너진다 —
        // 사용자가 맞춰 둔 화면이 창을 하나 열 때마다 사라진다.
        //
        // 강조(`_highlightShape`)는 **위에서 이미 걸었다.** 그것은 카메라를
        // 건드리지 않으므로 잠금과 무관하고, 오히려 지도가 움직이지 않을 때야말로
        // "이 패널이 어느 도형 얘기인가" 를 알려 줄 유일한 단서다.
        //
        // 여기서 되돌리므로 `_lastFocus` 도 남지 않는다 — 닫은 뒤의 재구성
        // (`_refocusAfterClose`)·화면 변화 재조정(`_refitCurrentFocus`)도 함께
        // 조용해진다. 셋 다 이 함수를 지나므로 관문은 여기 하나면 된다.
        //
        // 사용자가 직접 누르는 이동(주소 검색·현위치·초기화·클러스터 확대)은
        // 막지 않는다. 그것은 "가겠다" 는 의사표시이지 부수 효과가 아니다.
        if (_mapIsLocked(map)) return;

        var rect = _visibleMapRect(uid);
        if (!rect) return;

        var bounds = geometry ? _geomBounds(geometry) : null;
        if (bounds && bounds[0][0] === bounds[1][0] && bounds[0][1] === bounds[1][1]) {
            // 점 하나짜리 geometry — 넓이가 0 이라 줌을 정할 근거가 없다.
            point = { lng: bounds[0][0], lat: bounds[0][1] };
            bounds = null;
        }

        // 닫을 때 같은 대상으로 다시 맞추기 위해 기억해 둔다. 문자열 uuid 대신
        // **geometry 를 통째로** 담는다 — 도형 소스는 레이어 토글이나 새로고침에
        // 따라 사라질 수 있는데, 그때 uuid 만 들고 있으면 되찾을 방법이 없다.
        if (!opts.transient) {
            inst._lastFocus = bounds ? { geometry: geometry } : (point ? point : null);
        }

        // 도형을 **가시 사각형 한가운데**에 놓기 위한 카메라 오프셋.
        // `offset` 은 "화면 중심에서 이만큼 떨어진 자리에 center 를 놓아라" 라,
        // 가려진 면적이 아무리 커도 선형으로 정확하다. 가려진 영역을 padding 으로
        // 넘기는 방식은 시트가 화면의 62% 를 덮으면 어긋났다(실측 48px).
        var offset = [ (rect.cx != null ? rect.cx : rect.x + rect.w / 2) - rect.W / 2,
                       (rect.cy != null ? rect.cy : rect.y + rect.h / 2) - rect.H / 2 ];

        try {
            if (bounds) {
                // **"이미 잘 보이면 그냥 둔다" 는 규칙은 두지 않는다.** 모달을 여는
                // 것은 "이 대상을 보겠다" 는 분명한 의사표시다. 화면에 걸쳐 있기만
                // 해도 그대로 두면, 모달 안의 링크로 자식(구획·시설)을 열었을 때
                // 대상이 구석에 작게 놓인 채 지도가 꿈쩍도 하지 않는다(실측:
                // 중심 160px 아래, 가시 높이의 35%). 이미 맞아 있으면 easeTo 가
                // 아무것도 하지 않으므로 손해도 없다.
                //
                // **`fitBounds` 를 부르지 않는다.** 그것은 카메라를 움직일 뿐
                // 아니라 bearing 을 명시하지 않으면 **정북으로 되돌린다**(실측:
                // 45° → 0°). 사용자가 도형이 잘 보이는 방향으로 일부러 돌려 둔
                // 것을 코드가 되돌리면 안 된다. 여기서는 재기만 한다.
                //
                // **줌은 cameraForBounds 에게 맡기고, 중심은 우리가 잡는다.**
                // 어긋났던 것은 줌이 아니라 중심이었다(실측: 줌은 가시 영역을
                // 잘 채웠고 중심만 48px 아래로 밀렸다). 줌을 직접 환산하면
                // 도형이 세로로 길든 가로로 길든 한쪽 비율만 따라가 필요 이상으로
                // 작아진다 — 그 계산은 cameraForBounds 가 이미 정확히 한다.
                // padding 은 **대칭**으로 준다. 목적은 "가시 사각형과 같은 크기의
                // 창에 맞는 줌" 하나뿐이고, 어디에 놓을지는 아래 offset 이 정한다.
                // 실제 위치대로 비대칭 padding 을 주면 cameraForBounds 는 그
                // 비대칭 배치에 맞는 줌을 내는데, 우리가 중심을 옮기는 순간 그
                // 전제가 깨져 도형이 가시 사각형을 넘친다(실측 24px).
                var padOpt = {
                    top:    Math.max(0, (rect.H - rect.h) / 2),
                    bottom: Math.max(0, (rect.H - rect.h) / 2),
                    left:   Math.max(0, (rect.W - rect.w) / 2),
                    right:  Math.max(0, (rect.W - rect.w) / 2)
                };
                var cam = null;
                try {
                    cam = map.cameraForBounds(bounds, {
                        padding: padOpt, bearing: map.getBearing()
                    });
                } catch (e) {}
                if (!cam) {
                    // 여백이 컨테이너를 넘어 계산이 실패하는 경우의 폴백 —
                    // 전체 기준 줌에서 가시 사각형이 작아진 만큼 낮춘다.
                    cam = map.cameraForBounds(bounds, { padding: 0, bearing: map.getBearing() });
                    if (!cam) return;
                    cam = { center: cam.center,
                            zoom: cam.zoom + Math.log2(Math.min(rect.w / rect.W, rect.h / rect.H)) };
                }
                // 중심도 cameraForBounds 의 것을 쓴다. padding 이 **대칭**이라
                // 그 값은 "도형을 화면 한가운데 놓는 중심" 이고, 거기서 offset 만큼
                // 밀면 정확히 가시 사각형 한가운데다. 위경도 평균으로 대신 계산하면
                // 메르카토르에서 위도 방향이 비선형이라 남북으로 긴 도형에서 어긋난다
                // (실측 13px).
                // bearing·pitch 를 주지 않는다 = 사용자가 맞춰 둔 방향 그대로.
                // 가상 카메라에서 미리 풀어 **한 번에** 옮긴다.
                var solved = _solveFitCamera(map, bounds, rect, cam.zoom);
                if (solved) {
                    // 사용자가 더 확대해 둔 상태면 그 축척으로 다시 푼다(중심만).
                    var keep = _keepUserZoom(map, solved.zoom);
                    if (keep != null) {
                        var kept = _solveFitCamera(map, bounds, rect, cam.zoom, keep);
                        if (kept) solved = kept;
                    }
                    // 이미 도형 중심이 가시 사각형 한가운데 오도록 푼 값이라
                    // offset 은 주지 않는다(주면 두 번 밀린다).
                    map.easeTo({ center: solved.center, zoom: solved.zoom, duration: 400 });
                } else {
                    // transform 을 못 쓰는 경우의 폴백 — 눕힌 지도에서는 정확하다.
                    var fz = Math.min(_fitMaxZoom(map), cam.zoom);
                    var keep2 = _keepUserZoom(map, fz);
                    map.easeTo({ center: cam.center, zoom: (keep2 != null ? keep2 : fz),
                                 offset: offset, duration: 400 });
                }
            } else if (point) {
                var pz = point.zoom != null ? point.zoom : Math.max(map.getZoom(), 17);
                map.easeTo({ center: [point.lng, point.lat], zoom: pz,
                             offset: offset, duration: 400 });
            }
        } catch (e) {}
    }

    /**
     * 보이는 영역이 바뀌었을 때(시트 확대·축소, 측정 도크 접기·펼치기 …) 지금
     * 열려 있는 대상으로 **구도만** 다시 잡는다.
     *
     * 화면이 바뀌었는데 카메라가 그대로면, 방금 넓힌 자리가 빈 여백이 되거나
     * 도형이 새로 생긴 크롬 밑으로 들어간다. 패널이 열려 있을 때만 동작한다 —
     * 닫힌 뒤의 재구성은 `_refocusAfterClose` 가 따로 맡는다(그쪽은 강조도 없다).
     */
    var REFIT_COOLDOWN_MS = 1000;

    function _refitCurrentFocus(uid) {
        var wid = _widgetIdFromUid(uid);
        var inst = wid && window.AoTWidgetInstances && window.AoTWidgetInstances[wid];
        var host = wid && document.getElementById('aot-map-' + wid);
        if (!inst || !inst._lastFocus || !host) return;
        if (!host.getAttribute('data-aot-panel')) return;   // 패널이 없으면 할 일 없다
        // 연달아 부르지 않는다. 카메라를 옮기면 화면에 보이는 것이 달라지고, 그것이
        // 다시 재조정을 부르는 자리가 생기기 쉽다 — 마지막 방어선이다.
        var now = (window.performance && performance.now) ? performance.now() : Date.now();
        if (inst._lastRefitAt && (now - inst._lastRefitAt) < REFIT_COOLDOWN_MS) return;
        inst._lastRefitAt = now;
        _focusMapOn(wid, inst._lastFocus,
                    { force: true, highlight: false, transient: true });
    }

    /**
     * 패널이 닫힌 뒤, 마지막으로 본 도형을 넓어진 화면 가운데로 다시 맞춘다.
     *
     * 패널이 사라지면 그 폭만큼 지도가 갑자기 넓어지는데 카메라는 그대로라,
     * 방금까지 보던 도형이 한쪽에 치우치고 반대편에는 빈 여백이 남는다. 화면이
     * 바뀌었으니 구도도 다시 잡아 준다.
     *
     * **강조는 걸지 않는다**(highlight:false) — 닫으면서 막 지운 참이다.
     * 반드시 `data-aot-panel` 속성과 --aot-panel-* 을 지운 **뒤에** 부를 것:
     * 그 전에 부르면 없어진 패널 몫까지 여백으로 빼서 도형이 다시 치우친다.
     */
    function _refocusAfterClose(uid) {
        var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uid];
        var last = inst && inst._lastFocus;
        if (!last) return;
        _focusMapOn(uid, last, { force: true, highlight: false, transient: true });
    }

    // ── 지금 실제로 지도가 보이는 사각형 ─────────────────────────────────────
    //
    // 지도를 가리는 것은 도킹 패널만이 아니다. **가리는 것은 전부 여기 한 곳에서
    // 센다** — 예전에는 패널만 세서 도형 하단이 측정 도크에 33px 가린 채 "다 보인다"
    // 로 판정됐다(실측). 크롬이 늘어도 이 표에만 넣으면 카메라와 판정이 함께 따라온다.
    //
    // 각 항목은 "어느 변을 얼마나 먹는가" 로만 환산한다. 도크처럼 가운데에만 있는
    // 것도 그 변 전체를 먹는 것으로 본다 — 도형이 그 위에 걸치는지 매번 따지는 것보다
    // 예측 가능하고, 넉넉하게 잡아서 손해 보는 것은 약간의 축척뿐이다.
    var MAP_CHROME = [
        { sel: '.map-tools-left',          side: 'left'   },
        { sel: '[id^="map-tools-right-"]', side: 'right'  },
        { sel: '[id^="map-attrib-"]',      side: 'right'  },
        { sel: '.aot-meas-dock',           side: 'bottom' },
        { sel: '.aot-map-advice-chips',    side: 'top'    }
    ];
    // **범례는 일부러 넣지 않는다.** 우하단 구석의 상자일 뿐인데 높이가 꽤 되어,
    // 이것을 아래 경계로 삼으면 가시 영역이 크게 줄고 도형이 작아지면서 위로
    // 치우친다. 도형이 범례 위에 조금 걸치는 것보다 그 대가가 크다. 도크는
    // 다르다 — 하단 **중앙을 가로지르므로** 도형과 정면으로 겹친다.

    // 여백은 **가시 변에 비례**한다. 고정 40px 은 가시 높이가 124px 인 화면에서
    // 위아래 합쳐 65% 를 먹어, 도형에 돌아갈 자리를 43px 로 만들었다.
    var FIT_PAD_MIN = 8, FIT_PAD_MAX = 40, FIT_PAD_RATIO = 0.06;

    // 크롬이 패널을 피해 옮겨 간 뒤의 자리까지 남는 여백(map.css 의 `+ 10px`).
    var CHROME_GAP = 10;

    /**
     * @param panel { w, h } 도킹 패널이 가린 폭/높이(없으면 0).
     *
     * **패널이 열린 쪽은 재지 않고 계약대로 계산한다.** 오른쪽 크롬은 패널이 열리면
     * `right: calc(var(--aot-panel-w) + 10px)` 로 비켜가는데(map.css), 그 이동에는
     * 0.2s 트랜지션이 있다. 패널을 연 **직후**에 재면 아직 옮기기 전 자리가 나오고,
     * 그 값으로 카메라를 맞추면 도형이 딱 그만큼 밀린다(실측: 가로 20px, 줌도 과대).
     * 폭·높이는 트랜지션과 무관하게 정확하므로 그것만 쓴다.
     */
    function _mapChromeInset(host, contRect, panel) {
        var ins = { top: 0, right: 0, bottom: 0, left: 0 };
        MAP_CHROME.forEach(function (c) {
            var el = host.querySelector(c.sel);
            if (!el) return;
            var r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) return;   // 숨겨진 것은 안 센다
            var v = 0;
            if (c.side === 'top')         v = r.bottom - contRect.top;
            else if (c.side === 'left')   v = r.right - contRect.left;
            else if (c.side === 'right')  v = panel.w > 0 ? (panel.w + r.width + CHROME_GAP)
                                                          : (contRect.right - r.left);
            else                          v = panel.h > 0 ? (panel.h + r.height + CHROME_GAP)
                                                          : (contRect.bottom - r.top);
            v = Math.max(0, v);                          // 컨테이너 밖이면 0
            if (v > ins[c.side]) ins[c.side] = v;
        });
        return ins;
    }

    /**
     * 지도가 실제로 보이는 사각형(지도 컨테이너 좌표계) + 컨테이너 크기.
     * 카메라 계산과 가시성 판정이 **둘 다 이것만** 본다.
     */
    function _visibleMapRect(uid) {
        var wid = _widgetIdFromUid(uid);
        var inst = wid && window.AoTWidgetInstances && window.AoTWidgetInstances[wid];
        var map = inst && inst.map;
        if (!map) return null;
        var cont = map.getContainer();
        var W = cont.clientWidth, H = cont.clientHeight;
        if (!W || !H) return null;

        var host = document.getElementById('aot-map-' + wid) || cont;
        // 도킹 패널은 DOM 을 재지 않고 변수로 읽는다 — 셸이 이미 "가린 폭/높이" 로
        // 내보내고 있고(바깥 여백 포함), 그 값이 카메라가 알아야 할 바로 그 값이다.
        var read = function (n) { return parseFloat(host.style.getPropertyValue(n)) || 0; };
        var panel = { w: read('--aot-panel-w'), h: read('--aot-panel-h') };

        var ins = _mapChromeInset(host, cont.getBoundingClientRect(), panel);
        ins.right  = Math.max(ins.right,  panel.w);
        ins.bottom = Math.max(ins.bottom, panel.h);

        var vw = W - ins.left - ins.right;
        var vh = H - ins.top - ins.bottom;
        // 크롬이 다 먹어 버리면 크롬을 무시한다 — 어긋난 자리에 맞추는 것보다
        // 컨테이너 기준으로라도 맞추는 편이 낫다.
        if (vw < 60 || vh < 60) { ins = { top: 0, right: 0, bottom: 0, left: 0 }; vw = W; vh = H; }

        var mx = Math.min(FIT_PAD_MAX, Math.max(FIT_PAD_MIN, vw * FIT_PAD_RATIO));
        var my = Math.min(FIT_PAD_MAX, Math.max(FIT_PAD_MIN, vh * FIT_PAD_RATIO));
        // **크기를 정하는 사각형과 중심을 정하는 자리는 다르다.**
        //
        // 크기(줌)는 지금 계산한 사각형 그대로다 — 도크·범례·툴 레일에 도형이
        // 가리지 않으려면 그것들을 다 빼고 재야 한다.
        //
        // 중심은 다르다. 그 작은 크롬들까지 빼고 한가운데를 잡으면 도형이 지도의
        // **위쪽으로 치우쳐 보인다**(하단 도크 때문에 실측 40px). 사람은 도크를
        // "지도 위에 얹힌 것" 으로 보지 지도가 거기서 끝난다고 보지 않는다.
        // 그래서 중심은 **불투명하게 넓은 면을 덮는 것**(도킹 패널)만 피한다.
        var cw = W - panel.w, ch = H - panel.h;
        var rect = {
            x: ins.left + mx, y: ins.top + my,
            w: Math.max(20, vw - 2 * mx), h: Math.max(20, vh - 2 * my),
            cx: cw / 2, cy: ch / 2,
            // 크롬에 닿지 않는 한계선. 중심(cx/cy)을 그대로 쓰면 도형 아래가
            // 측정값 도크에 물리므로(실측 32px), 겹치지 않는 선까지만 내려간다.
            limit: { top: ins.top + my, bottom: H - ins.bottom - my,
                     left: ins.left + mx, right: W - ins.right - mx },
            W: W, H: H
        };
        // 진단용으로 남긴다 — 카메라가 어긋났을 때 "그때 무엇을 가려진 것으로
        // 봤는가" 를 되짚을 방법이 이것뿐이다(계산이 한 프레임 안에서 끝난다).
        inst._lastFitRect = rect;
        inst._lastFitInset = ins;
        return rect;
    }

    /**
     * 공용 모달 셸.
     *
     * `focusUuid` 를 주면 **열려 있는 동안** 그 대상의 도형·라벨이 보인다 —
     * 사용자가 그 종류를 꺼 두었더라도. 어디 이야기인지 지도에서 못 찾으면
     * 모달 안의 값이 어느 자리 것인지 알 수 없다. 닫으면 그대로 되돌아간다
     * (토글을 건드리지 않으므로 꺼 둔 상태가 남는다).
     */
    function _showFacilityCenterOverlay(html, uid, focusUuid) {
        var OVERLAY_ID = 'aot-facility-ctrl-overlay-' + uid;
        var existing = document.getElementById(OVERLAY_ID);
        // 앞 창의 임시 표시를 먼저 거둔다 — 아래 remove() 는 그 창의 닫힘
        // 리스너를 지나지 않는다(위 `_clearModalFocus` 주석).
        try {
            var _prevInst = window.AoTWidgetInstances[uid];
            if (_prevInst) _clearModalFocus(_prevInst, uid);
        } catch (e) {}
        if (existing) existing.remove();

        var dock = _panelHostFor(uid);
        var mode = dock ? dock.mode : 'center';

        var overlay = document.createElement('div');
        overlay.id = OVERLAY_ID;
        if (dock) {
            // 레이어 자체는 클릭을 통과시킨다(pointer-events 는 CSS). 백드롭도
            // 없다 — 지도가 계속 보이고 계속 조작돼야 하는 것이 이 모드의 전부다.
            overlay.className = 'aot-map-panel-layer';
            overlay.setAttribute('data-mode', mode);
        } else {
            overlay.style.cssText = [
                'position:fixed', 'inset:0', 'z-index:var(--aot-z-modal)',
                'display:flex', 'align-items:center', 'justify-content:center',
                'background:rgba(0,0,0,0.35)'
            ].join(';');
        }

        var popupWrap = document.createElement('div');
        popupWrap.style.cssText = 'position:relative;';
        if (dock) popupWrap.className = 'aot-map-panel-wrap';

        var box = document.createElement('div');
        box.className = 'maplibregl-popup-content aot-center-modal';
        box.innerHTML = html;

        var closeBtn = document.createElement('button');
        closeBtn.className = 'maplibregl-popup-close-button aot-center-modal-close';
        closeBtn.setAttribute('type', 'button');
        closeBtn.setAttribute('aria-label', 'Close');
        closeBtn.innerHTML = '&#x2715;';
        // 자리와 층만 인라인으로 둔다. **생김새는 CSS 가 갖는다**
        // (`button.aot-center-modal-close`) — 인라인은 어떤 규칙도 이기므로,
        // 여기에 배경·여백을 적어 두면 스타일시트에서 아무리 고쳐도 안 먹는다
        // (실측: 뒤로가기와 짝을 맞추려 배경을 줬는데 이 한 줄에 막혔다).
        closeBtn.style.cssText = 'position:absolute;top:10px;right:14px;border:none;cursor:pointer;line-height:1;z-index:1;';

        popupWrap.appendChild(box);
        popupWrap.appendChild(closeBtn);

        // 시트(폰·좁은 위젯)에는 위쪽에 그랩바를 둔다. 누르면 시트가 위젯 전체로
        // 커지고 다시 누르면 되돌아온다 — 지도를 보며 훑다가 내용이 길어지면
        // 그때 넓히면 된다. 바텀시트의 표준 어포던스라 설명이 필요 없고, 아이콘을
        // 새로 들이지 않는다.
        // 그랩바는 dock 이면 **모드와 무관하게** 만든다. 회전으로 시트↔옆이
        // 바뀔 때 만들었다 지웠다 하면 그 순간의 상태(펼침 여부·리스너)가 함께
        // 사라진다. 보이고 안 보이고는 CSS 가 `data-mode` 로 정한다.
        var grab = null;
        if (dock) {
            var _T = function (t) { return window._ ? window._(t) : t; };
            grab = document.createElement('button');
            grab.type = 'button';
            grab.className = 'aot-map-sheet-grab';
            grab.setAttribute('aria-expanded', 'false');
            grab.setAttribute('aria-label', _T('Expand'));
            grab.addEventListener('click', function () {
                var on = overlay.classList.toggle('is-expanded');
                grab.setAttribute('aria-expanded', on ? 'true' : 'false');
                grab.setAttribute('aria-label', on ? _T('Collapse') : _T('Expand'));
                // 높이가 바뀌면 크롬이 비켜갈 거리도, 지도가 보이는 자리도 바뀐다.
                setTimeout(function () {
                    if (typeof _syncPanelVarRef === 'function') _syncPanelVarRef();
                    _refitCurrentFocus(uid);             // 새 가시 영역에 다시 맞춘다
                }, 220);                                 // 높이 트랜지션 뒤에 잰다
            });
            popupWrap.insertBefore(grab, box);
        }
        overlay.appendChild(popupWrap);

        // 본문을 아래로 훑으면 탭 줄을 접고, 위로 올리면 즉시 되돌린다.
        //
        // 폰 시트는 높이가 곧 전부다 — 제목·탭·본문이 나눠 쓰는데 탭은 한 번
        // 고르고 나면 계속 자리만 차지한다. 셸에 한 번 달아 두면 구역·시설·구획
        // 모달이 전부 같은 동작을 한다(탭이 없는 모달은 아무 일도 일어나지 않는다).
        //
        // `scroll` 은 버블링하지 않으므로 **캡처 단계**에서 받는다. 스크롤하는
        // 것은 본문(.aot-bay-popup-pane)이고 그것은 나중에 만들어질 수도 있어,
        // 요소마다 걸지 않고 셸에서 위임으로 잡는다.
        //
        // ⚠ **접는 행위가 스크롤을 바꾼다 — 되먹임을 끊어야 한다.** 탭을 접으면
        // 본문이 그만큼 커지고, 스크롤 여유가 탭 높이만 한 화면에서는 바닥에
        // 붙어 있던 scrollTop 이 브라우저에 의해 위로 당겨진다. 그 감소는 "위로
        // 스크롤" 로 읽혀 탭이 다시 펼쳐지고, 그러면 다시 아래로 밀리고… 화면이
        // 떨린다(사용자 보고: "탭 가림과 바닥 반동이 핑퐁"). 그래서 **접어도
        // 여유가 남을 때만** 접는다.
        var NAV_SCROLL_EPS = 4;      // 이보다 작은 움직임은 떨림으로 본다
        var NAV_SLACK_RATIO = 2.5;   // 탭 높이의 이만큼은 남아야 접는다
        var NAV_LOCK_MS = 400;       // 한 번 바꾼 뒤 이만큼은 다시 안 바꾼다

        var _navNow = function () {
            return (window.performance && performance.now) ? performance.now() : Date.now();
        };
        /**
         * 상태를 바꾸고 **잠근다.**
         *
         * 여유 검사만으로는 부족했다 — 접힘/펼침에는 0.18s 전이가 붙어 있고 그
         * 동안에도 스크롤 이벤트는 계속 들어온다. 전이 중의 본문 높이는 중간값
         * 이라, 그것으로 방향을 재면 한 프레임마다 판정이 뒤집혀 다시 떨린다.
         * 바꾼 직후 잠깐 잠가 두면 어떤 경로로 들어오든 진동이 멈춘다.
         */
        var _setNavCollapsed = function (on) {
            if (box.classList.contains('aot-nav-collapsed') === on) return;
            box.classList.toggle('aot-nav-collapsed', on);
            box._aotNavLockUntil = _navNow() + NAV_LOCK_MS;
        };

        box.addEventListener('scroll', function (e) {
            var el = e.target;
            if (!el || !el.classList ||
                !el.classList.contains('aot-bay-popup-pane')) return;

            // 잠금 중에는 위치만 따라간다(다음 판정의 기준이 튀지 않게).
            if (box._aotNavLockUntil && _navNow() < box._aotNavLockUntil) {
                el._aotNavLastY = el.scrollTop;
                return;
            }

            var nav = box.querySelector('.aot-bay-popup-nav');
            // 접혀 있어도 scrollHeight 는 원래 높이를 유지한다(overflow:hidden).
            var navH = nav ? (nav.scrollHeight || 0) : 0;
            var collapsed = box.classList.contains('aot-nav-collapsed');
            // 접힌 상태에서는 본문이 이미 커져 있으므로, **펼친 기준**으로 환산해
            // 여유를 잰다. 그래야 접었다 폈다가 판정을 뒤집지 않는다.
            var slack = (el.scrollHeight - el.clientHeight) + (collapsed ? navH : 0);
            if (navH <= 0 || slack < navH * NAV_SLACK_RATIO) {
                _setNavCollapsed(false);
                el._aotNavLastY = el.scrollTop;
                return;
            }

            var y = el.scrollTop;
            var dy = y - (el._aotNavLastY || 0);
            el._aotNavLastY = y;
            // 맨 위에서는 언제나 보인다 — 접힌 채로 위에 도달하면 되돌릴 길이 없다.
            if (y <= NAV_SCROLL_EPS) { _setNavCollapsed(false); return; }

            // **바닥 근처에서는 펼치지 않는다.** 탭을 접으면 본문이 그만큼 커져
            // 최대 스크롤이 줄고, 바닥에 닿아 있던 화면은 브라우저가 그만큼 위로
            // 되민다. 그 되밀림은 "위로 스크롤" 과 구분되지 않아 곧바로 탭이
            // 펼쳐지고, 펼쳐지면 다시 아래로 밀린다 — 훑다 보면 어느 높이에서든
            // 결국 바닥에 닿으므로 **모든 화면에서** 떨렸다.
            var toBottom = el.scrollHeight - el.clientHeight - y;
            if (dy > NAV_SCROLL_EPS) { _setNavCollapsed(true); return; }
            if (dy < -NAV_SCROLL_EPS && toBottom > navH) _setNavCollapsed(false);
        }, true);

        /**
         * 닫기(✕)를 제목줄 **한가운데**, 뒤로가기(←)와 **좌우대칭**으로 맞춘다.
         *
         * 닫기 버튼은 셸 래퍼 기준 absolute 이고 제목줄은 셸 안쪽에 있어서,
         * 고정 `top`/`right` 으로는 뒤로가기와 맞지 않는다 — 셸의 위·좌우 여백이
         * 모드마다 다르고(도킹 12px · 시트 22px) 제목줄 높이도 다르다(36px ·
         * 폰 44px). 실측에서 닫기만 데스크탑 4.5px · 모바일 18.5px 위로 떠
         * 있었다(화살표·제목·상태점은 서로 맞아 있었다).
         *
         * 가로도 마찬가지: 닫기의 `right` 는 공용 규칙(`.maplibregl-popup-
         * close-button`, 작은 툴팁 팝업까지 공유)의 12px 고정값을 쓰는데, 이
         * 모달의 실제 좌측 여백(`.maplibregl-popup-content` 의 padding, 보통
         * 16px)과 달라 뒤로가기(좌측 여백 그대로 사용)와 좌우 비대칭으로
         * 보였다. 뒤로가기가 서 있는 제목줄의 **왼쪽 여백을 그대로 오른쪽에도
         * 적용**해 대칭을 맞춘다.
         *
         * `important` 로 넣는 이유: 폰 폭에서 닫기 위치를 잡는 규칙이
         * `!important` 라 그냥 인라인으로는 이기지 못한다.
         */
        function _alignCloseButton() {
            try {
                var hdr = box.querySelector('.aot-sensor-popup-header');
                if (!hdr) return;
                var hb = hdr.getBoundingClientRect();
                var wb = popupWrap.getBoundingClientRect();
                if (!hb.height) return;
                var cs = getComputedStyle(hdr);
                var padT = parseFloat(cs.paddingTop) || 0;
                var padB = parseFloat(cs.paddingBottom) || 0;
                // 제목줄의 **내용** 중심(구분선 여백은 뺀다)
                var mid = (hb.top - wb.top) + padT + (hb.height - padT - padB) / 2;
                var top = Math.round(mid - (closeBtn.offsetHeight || 24) / 2);
                closeBtn.style.setProperty('top', Math.max(2, top) + 'px', 'important');
                // 제목줄(뒤로가기가 서는 자리)의 왼쪽 여백 = 닫기의 오른쪽 여백.
                var leftInset = Math.round(hb.left - wb.left);
                closeBtn.style.setProperty('right', Math.max(2, leftInset) + 'px', 'important');
            } catch (e) {}
        }

        var _prevOverflow = null;
        var _scrollbarW = 0;
        var _panelRo = null;
        var _panelOrientOff = null;    // 회전 감시자 해제
        var _syncPanelVarRef = null;   // 그랩바(위에서 만든다)가 높이 변경 뒤 부른다

        if (dock) {
            // 위젯 wrapper(.aot-map-container, position:relative)에 붙인다. 전체화면
            // 버튼은 이 **같은 요소**를 전체화면으로 만들므로(의사/네이티브 모두),
            // 패널은 아무 배선 없이 전체화면을 따라간다.
            dock.host.appendChild(overlay);
            dock.host.setAttribute('data-aot-panel', mode);
            // 폰인지도 함께 남긴다. `side` 만으로는 데스크탑과 구분되지 않는데,
            // 하단 크롬을 숨길지 말지는 **폰이냐**가 가른다(폰 가로는 높이가
            // 375px 남짓이라 도크 하나가 지도의 상당 부분을 먹는다).
            // 판정을 CSS 미디어쿼리로 다시 쓰지 않는다 — `_isPhoneClass()` 가
            // 유일한 정본이어야 두 곳이 조용히 갈리지 않는다.
            if (_isPhoneClass()) dock.host.setAttribute('data-aot-panel-phone', '1');
            // 시트 모드에서는 측정 도크를 숨긴다(CSS). 숨기면 높이가 0 이 되므로
            // 도크 높이를 쓰는 크롬들이 따라오도록 다시 재게 한다.
            try { _updateDockHeightVar(_widgetIdFromUid(uid)); } catch (e) {}

            // 지도 크롬(저작권·범례·툴 레일·측정 도크)이 패널을 피하도록 실제
            // 렌더 크기를 변수로 내보낸다. 측정 도크의 --aot-dock-h 와 같은 방식.
            // **저작권이 가려지면 라이선스 준수 문제가 된다** — 이 배선은 선택이 아니다.
            //
            // 내보내는 값은 패널 **박스 폭이 아니라 패널이 가린 영역 폭**이다 —
            // 레이어의 바깥 여백(padding)까지 포함한다. 박스 폭만 내보내면 크롬이
            // 그 여백만큼 패널에 붙어 버려(실측 2px) 붙은 것처럼 보였다. 2단계에서
            // 카메라 padding 에 넘길 값도 "가려진 폭"이라 정의가 하나로 맞는다.
            var _syncPanelVar = function () {
                if (!dock.host.isConnected) return;
                var hostBox = dock.host.getBoundingClientRect();
                var panelBox = popupWrap.getBoundingClientRect();
                if (mode === 'side') {
                    dock.host.style.setProperty(
                        '--aot-panel-w', Math.max(0, Math.round(hostBox.right - panelBox.left)) + 'px');
                } else {
                    dock.host.style.setProperty(
                        '--aot-panel-h', Math.max(0, Math.round(hostBox.bottom - panelBox.top)) + 'px');
                }
            };
            _syncPanelVarRef = _syncPanelVar;
            _syncPanelVar();

            // ── 회전하면 배치를 다시 고른다 ─────────────────────────────────
            // 모드는 열 때 한 번 정해지는데, 폰은 열어 둔 채 눕히는 것이 흔하다.
            // 그대로 두면 눕힌 화면에서 시트가 남은 높이를 반으로 갈라 지도도
            // 모달도 못 쓴다. 모드만 갈아 끼우면 나머지(폭·크롬 회피·카메라)는
            // 이미 `data-mode` 를 보고 따라온다.
            var _applyMode = function () {
                if (!dock.host.isConnected) return;
                var next = _isPhoneClass() ? (_isLandscape() ? 'side' : 'sheet') : 'side';
                if (next === mode) return;
                // 이전 모드가 내보낸 변수를 지운다 — 남으면 크롬이 이제 없는
                // 패널을 계속 피해 한쪽이 텅 빈다.
                dock.host.style.removeProperty(
                    mode === 'side' ? '--aot-panel-w' : '--aot-panel-h');
                mode = next;
                overlay.setAttribute('data-mode', mode);
                dock.host.setAttribute('data-aot-panel', mode);
                if (_isPhoneClass()) dock.host.setAttribute('data-aot-panel-phone', '1');
                else dock.host.removeAttribute('data-aot-panel-phone');
                // 펼침은 시트에만 있는 상태다.
                if (mode !== 'sheet') overlay.classList.remove('is-expanded');
                try { _updateDockHeightVar(_widgetIdFromUid(uid)); } catch (e) {}
                _syncPanelVar();
                // 회전 직후에는 뷰포트도 위젯도 아직 정착하지 않았다 — 다시 재고
                // 카메라를 새 가시 영역에 맞춘다.
                setTimeout(function () {
                    if (!dock.host.isConnected) return;
                    _syncPanelVar();
                    _refitCurrentFocus(uid);
                }, 300);
            };
            var _orientT = null;
            var _onOrient = function () {
                if (_orientT) clearTimeout(_orientT);
                _orientT = setTimeout(_applyMode, 120);   // 회전 중 resize 폭풍을 모은다
            };
            window.addEventListener('resize', _onOrient);
            window.addEventListener('orientationchange', _onOrient);
            _panelOrientOff = function () {
                if (_orientT) { clearTimeout(_orientT); _orientT = null; }
                window.removeEventListener('resize', _onOrient);
                window.removeEventListener('orientationchange', _onOrient);
            };
            if (typeof ResizeObserver !== 'undefined') {
                // 패널 폭은 clamp 라 위젯이 리사이즈되면 함께 변한다.
                _panelRo = new ResizeObserver(_syncPanelVar);
                _panelRo.observe(popupWrap);
            }
        } else {
            _prevOverflow = document.body.style.overflow;
            _scrollbarW = window.innerWidth - document.documentElement.clientWidth;
            document.body.style.overflow = 'hidden';
            if (_scrollbarW > 0) document.body.style.paddingRight = _scrollbarW + 'px';

            // Native Fullscreen API puts the fullscreen element in the browser's
            // top-layer; siblings appended to <body> render behind it regardless
            // of z-index. Mount inside the fullscreen element when one is active.
            var _fsHost = document.fullscreenElement || document.webkitFullscreenElement ||
                document.mozFullScreenElement || document.msFullscreenElement || document.body;
            _fsHost.appendChild(overlay);
        }

        /* 눈금의 기준 라벨(적정 범위·목표·오늘)이 축 끝 라벨과 부딪히는지는
           **글자 폭**이 정하므로 붙은 뒤에 재야 한다(AoTViz.settle 주석 참조).
           본문 상당수가 슬롯에 나중에 채워지니 호출부마다 부르는 대신
           본문 변화를 보고 한 번씩 다시 잰다 — 슬롯이 늘어도 따라온다. */
        var _settleObs = null;
        if (window.AoTViz && window.AoTViz.settle && window.MutationObserver) {
            var _settlePending = false;
            var _settleNow = function () {
                _settlePending = false;
                try { window.AoTViz.settle(box); } catch (e) {}
                _alignCloseButton();
            };
            _settleNow();
            _settleObs = new MutationObserver(function () {
                if (_settlePending) return;
                _settlePending = true;
                // rAF 는 숨은 탭에서 아예 발화하지 않는다 — 다시 열었을 때
                // 라벨이 겹친 채로 남는다. 타이머는 느려질 뿐 멈추지 않는다.
                setTimeout(_settleNow, 0);
            });
            _settleObs.observe(box, { childList: true, subtree: true });
        }

        var _closeListeners = [];
        /**
         * @param byUser 사용자가 직접 닫았는가(✕ · Esc · 바깥 클릭).
         *
         * 모달 **안의 링크**로 다른 모달을 여는 경로는 "닫고 → (fetch) → 연다" 라,
         * 닫힘과 열림 사이에 왕복이 낀다. 그 틈에 닫힘 쪽이 카메라를 이전 도형으로
         * 되돌리면, 곧이어 시작되는 새 모달의 이동과 애니메이션이 겹쳐 **엉뚱한
         * 자리에 멈춘다**(라벨 클릭은 왕복이 없어서 멀쩡했다). 되돌리기는 사용자가
         * 실제로 닫았을 때만 한다 — 원래 의도도 그것이다.
         */
        function _close(byUser) {
            if (!document.getElementById(OVERLAY_ID)) return;
            overlay.remove();
            if (_settleObs) { _settleObs.disconnect(); _settleObs = null; }
            if (_panelRo) { try { _panelRo.disconnect(); } catch (e) {} _panelRo = null; }
            if (_panelOrientOff) { try { _panelOrientOff(); } catch (e) {} _panelOrientOff = null; }
            if (dock) {
                // 곧바로 다른 패널이 열리는 경우(도형을 연달아 클릭, 목록 →
                // 도형)에는 속성을 **지우지 않는다.** 지웠다 다시 붙이면 오른쪽
                // 크롬이 원위치로 갔다 되돌아오는 왕복 애니메이션을 매번 한다.
                // 다음 틱에 host 에 패널이 정말 없을 때만 정리한다.
                var _host = dock.host;
                // 사용자가 닫은 것이면 곧바로 정리한다. 교체(remove())라면 새 모달이
                // fetch 왕복 뒤에 열릴 수 있으므로 조금 기다린다 — 그 사이에 속성을
                // 지웠다 다시 붙이면 오른쪽 크롬이 왕복 애니메이션을 한 번 한다.
                setTimeout(function () {
                    if (_host.querySelector('.aot-map-panel-layer')) return;
                    _host.removeAttribute('data-aot-panel');
                    _host.removeAttribute('data-aot-panel-phone');
                    _host.style.removeProperty('--aot-panel-w');
                    _host.style.removeProperty('--aot-panel-h');
                    var _wid = _widgetIdFromUid(uid);
                    // 모달 때문에 올린 전체화면이면 되돌린다. 사용자가 직접 올려
                    // 둔 것이면 표시가 없으므로 그대로 둔다.
                    if (_host._aotFsByModal) {
                        _host._aotFsByModal = false;
                        try { if (_isMaximized(_host)) _toggleMapMaximize(_host); } catch (e) {}
                    }
                    try { _updateDockHeightVar(_wid); } catch (e) {}
                    // 넓어진 화면에 맞춰 구도를 다시 잡는다(속성을 지운 뒤라야
                    // 여백 계산이 맞다). 갈아타는 중이면 위에서 이미 반환했고,
                    // 링크로 다른 모달을 여는 중이면 byUser 가 false 다.
                    if (byUser) { try { _refocusAfterClose(_wid); } catch (e) {} }
                }, byUser ? 0 : 600);
            } else {
                document.body.style.overflow = _prevOverflow;
                if (_scrollbarW > 0) document.body.style.paddingRight = '';
            }
            // 강조는 되돌릴 상태가 없다 — 얹은 레이어를 지우면 원래 그림이다.
            try { _clearHighlight(_widgetIdFromUid(uid)); } catch (e) {}
            var i = _modalStack.indexOf(_closeByUser);
            if (i >= 0) _modalStack.splice(i, 1);
            _closeListeners.forEach(function (fn) { try { fn(); } catch (e) {} });
        }

        if (!dock) {
            // 백드롭 위 스크롤이 뒤 페이지로 새는 것을 막는다. 도킹 모드에는
            // 백드롭이 없고 레이어가 클릭을 통과시키므로 이 이벤트가 오지 않는다.
            overlay.addEventListener('wheel', function (e) {
                if (e.target === overlay) e.preventDefault();
            }, { passive: false });
            overlay.addEventListener('touchmove', function (e) {
                if (e.target === overlay) e.preventDefault();
            }, { passive: false });
            // 바깥 클릭 = 닫기는 **중앙 모달에서만**. 도킹 모드에서 이걸 두면
            // 지도를 만지는 순간 패널이 닫혀 대조가 통째로 무너진다.
            overlay.addEventListener('click', function (e) {
                if (e.target === overlay) _close(true);
            });
        }
        closeBtn.addEventListener('click', function () { _close(true); });

        // Esc 로 닫는 것도 사용자의 닫기다.
        var _closeByUser = function () { _close(true); };
        _modalStack.push(_closeByUser);
        _ensureEscHandler();

        // 열려 있는 동안 대상을 보이게 한다. 닫힐 때(사용자가 닫든, 다른 모달이
        // 갈아 끼우든) 이유를 거둔다 — `_close` 는 두 경로 모두 지난다.
        if (focusUuid) {
            var _fInst = window.AoTWidgetInstances[uid];
            if (_fInst) {
                _setFocus(_fInst, uid, focusUuid, 'modal', true);
                _closeListeners.push(function () {
                    _setFocus(_fInst, uid, focusUuid, 'modal', false);
                });
            }
        }

        return {
            getElement: function () { return popupWrap; },
            remove:     function () { _close(false); },
            on: function (evt, fn) {
                if (evt === 'close') _closeListeners.push(fn);
            }
        };
    }

    /**
     * 폴링이 다시 그리는 자리에 HTML 을 넣는다 — **내용이 실제로 달라졌을 때만.**
     * 넣었으면 true, 같아서 손대지 않았으면 false.
     *
     * ⚠ `innerHTML` 대입은 **내용이 같아도** 자식 노드를 전부 버리고 새로
     * 만든다. 모달 안 여러 자리가 5초마다(`output_update_interval`) 다시
     * 그려지는데 그 대부분은 값이 그대로다 — 실측: 열어 둔 시설 모달에서 5초
     * 간격 두 번의 빌드 결과가 **글자 하나까지 같았는데도** 제어 섹션은 노드가
     * 2개 지워지고 2개 생겼고, 개요 슬롯도 통째로 갈렸다.
     *
     * ⚠⚠ **비교 대상은 `el.innerHTML` 이 아니라 "지난번에 우리가 쓴 문자열"
     * 이다.** 사용자 지정 이름 번역(`aot-user-i18n.js`)이 우리가 쓴 직후 그
     * 텍스트 노드를 번역본으로 바꿔 놓기 때문이다. 그래서 현재 DOM 은 늘
     * **번역본**이고 새로 만든 HTML 은 늘 **원문**이라, 둘을 견주면 영원히
     * 다르다고 나온다 — 가드가 통째로 무력해지고 교체는 매번 일어난다.
     *
     * 그 조합이 정확히 사용자가 본 화면이다(사이트 언어 한국어 + 이름 번역
     * 켜짐): 5초마다 원문이 잠깐 보였다가 번역본으로 바뀌는 것이 **깜빡임**의
     * 정체다. 원문끼리 견주면 값이 안 바뀐 사이클에서는 아예 쓰지 않으므로
     * 번역기가 다시 할 일도 없다.
     *
     * 기록은 DOM 속성이 아니라 JS 프로퍼티에 둔다 — 속성으로 두면 그 쓰기
     * 자체가 또 하나의 변경이 되어 번역기의 관찰자를 깨운다.
     *
     * 부작용은 보기 나쁜 것만이 아니다 — 교체된 노드에서는 포커스·선택·열어 둔
     * 폼·스크롤 위치·CSS 전환이 함께 사라진다. 그래서 호출부가 스크롤을 재서
     * 되돌리는 코드를 덧붙여 왔는데, 애초에 안 바꾸면 그 보정도 필요 없다.
     *
     * 값이 **정말로** 바뀐 사이클에는 여전히 원문→번역본 전환이 한 번 보인다.
     * 그것을 없애려면 번역을 빌드 시점으로 당겨야 하는데 다른 층의 일이라
     * 여기서 건드리지 않는다 — 이 함수가 없애는 것은 **바뀌지 않았는데도**
     * 나던 주기적 깜빡임이다.
     */
    function _setHtmlIfChanged(el, html) {
        if (!el) return false;
        if (el._aotLastHtml === html) return false;
        el._aotLastHtml = html;
        el.innerHTML = html;
        return true;
    }

    // ── Unified label/key stacking order ──────────────────────────────────────
    // 하나의 표가 지도 위 **모든** 라벨·키의 z-index 를 정한다. 예전에는
    // geo-design 라벨(ZINDEX_MAP), 장치 pill(지정 없음 → auto), 센서 값 키
    // (priority_z), 구역 칩(CSS z-index:6)이 제각각이라 같은 지점에서 어느 것이
    // 위로 오는지 예측할 수 없었다.
    //
    // 순서: 넓은 대상이 **위**, 구체적인 대상이 아래.
    //   site > zone > facility > equipment > device > output > input > function
    // (equipment 는 사용자 지정 순서에 없지만 시설 부속 설비이므로 facility
    //  바로 아래에 둔다 — 나머지의 상대 순서는 지정 그대로다.)
    //
    // 복합장치(device)는 여기 **반드시 있어야 한다.** collect_devices 가
    // 복합장치를 `device_type='device'` 로 따로 내보내기 시작한 뒤(00764f1)
    // 이 표에 키가 없어서 _labelZ 폴백(LABEL_Z.zone)에 걸렸고, 복합장치
    // 라벨이 구역 라벨과 같은 단(6)에 올라가 시설·장치 라벨을 전부 덮었다.
    // 복합장치는 장치이므로 장치 라벨 단에 두되, 그 안에서는 가장 위다
    // (output/input/function 을 담는 그릇이라 이름이 가려지면 못 찾는다).
    // ⚠ 새 종류는 위 "네 표" 주석 참조 — 여기만 넣고 끝나지 않는다.
    var LABEL_Z = {
        site: 9, zone: 8, facility: 7,
        // 시설 구역(bay)은 시설 **안**이라 시설보다 위에 온다. 구획은 구역을
        // 나눈 것이라 그 아래.
        bay: 6, plot: 5,
        equipment: 4, device: 3, output: 2, input: 1, 'function': 1,
        // 노트 핀 — 사람이 그 자리에 일부러 찍은 표식이라 장치 라벨만큼 구체적이다.
        note: 2,
        // 센서(측정값) 라벨 — 가장 구체적이라 쌓임은 낮고 충돌에서는 이긴다.
        // **두 표 모두에 없었다**(2026-08-23 발견): 쌓임은 0 으로 깔리고 충돌
        // 순위는 `style.zIndex` 폴백이라 호버 여부에 따라 튀고 있었다.
        sensor: 1
    };

    // ── 충돌 우선순위 (쌓임 순서와 **별개 축**) ───────────────────────────────
    // 겹쳐서 하나만 남길 수 있을 때는 구체적인 대상이 남아야 한다: 대지 이름은
    // 어차피 넓은 영역 어디서나 읽히지만, 특정 장치의 값 키는 그 자리에서만
    // 읽을 수 있기 때문이다. 쌓임 순서(LABEL_Z)와 정반대이므로 같은 표를 쓸 수
    // 없다 — 예전에는 충돌 회피가 z-index 를 그대로 정렬 기준으로 삼아서, 쌓임
    // 순서를 뒤집자 site 라벨이 장치 키를 밀어내 버렸다.
    // 값은 LABEL_Z 의 정확한 역순이다 — 한쪽에 종류를 넣으면 다른 쪽에도 넣는다.
    // 빠뜨리면 아래 폴백이 `style.zIndex` 를 읽는데, 그 값은 호버/핀 중에는
    // LABEL_Z_FRONT(9000)라 우선순위가 포인터에 따라 튄다.
    var LABEL_COLLISION_RANK = {
        'function': 10, input: 9, sensor: 9, output: 8, device: 7, equipment: 6,
        // 노트는 **살아 있는 값에 진다.** 겹치면 지금 읽어야 하는 것은 측정값·
        // 장치 상태이고, 노트는 정적이라 줌인하거나 목록에서 다시 찾을 수 있다.
        // 대신 영역 라벨(구획·구역·대지)보다는 앞선다 — 그 자리를 콕 집은
        // 표식이라 넓은 이름에 가려지면 찍은 뜻이 없어진다.
        note: 5.5,
        plot: 5, bay: 4, facility: 3, zone: 2, site: 1
    };

    function _collisionRank(el) {
        var r = el && el.dataset ? LABEL_COLLISION_RANK[el.dataset.labelKind] : null;
        if (r != null) return r;
        // 아직 종류가 안 찍힌 요소는 z-index 로 폴백(과거 동작).
        return parseInt(el && el.style && el.style.zIndex, 10) || 0;
    }

    // ── 줌 게이트 ─────────────────────────────────────────────────────────────
    // ⚠⚠ **라벨 종류를 새로 만들면 아래 네 표에 전부 등록해야 한다.**
    //
    //   LABEL_Z              쌓임 순서(누가 위에 그려지나)
    //   LABEL_COLLISION_RANK 충돌에서 누가 남나  ← LABEL_Z 의 **역순**
    //   LABEL_ZOOM_GATED     줌아웃에서 접히나
    //   LABEL_KEYS           라벨 컨트롤에서 사람이 끄고 켜나
    //
    // 자주 있는 일이 아니라 자동 판정을 두지 않는다 — 종류마다 "이것이 멀리서도
    // 필요한 기준인가" 는 사람이 정할 판단이고, 기본값으로 때우면 그 판단이
    // 생략된 채 굳는다. 대신 **빠뜨리면 테스트가 잡는다**
    // (`test_geo_plot.py::test_every_map_label_kind_is_registered`).
    //
    // 등록을 빠뜨렸을 때의 증상은 표마다 다르고 전부 조용하다:
    //   Z 누락       → 다른 라벨 뒤에 깔린다(폴백이 0)
    //   RANK 누락    → 충돌 순위가 호버 여부에 따라 튄다(폴백이 style.zIndex)
    //   ZOOM 누락    → **줌아웃에서도 화면을 덮는다** ← bay·plot 이 그랬다
    //   KEYS 누락    → 라벨 컨트롤에 그 종류가 아예 안 나온다
    //
    // 이 표는 "줌 기준의 적용을 받는 종류" 다. 대지·구역은 멀리서 위치를 잡는
    // 기준이라 빠져 있고(항상 보인다), 나머지는 그 축척에서 읽히지도 않으면서
    // 화면만 덮으므로 접는다. 기준 줌 자체는 위젯 옵션(label_min_zoom, 기본 17).
    var LABEL_ZOOM_GATED = {
        facility: 1, bay: 1, plot: 1,
        device: 1, output: 1, input: 1, 'function': 1, equipment: 1, sensor: 1,
        // 노트 핀도 함께 접힌다. 멀리서 보는 화면에서 위치를 잡는 기준은
        // 대지·구역이고(그 둘만 게이트 밖이다), 노트는 그 자리에 가까이
        // 갔을 때 읽는 것이다 — 축척이 낮을수록 핀만 빽빽해져 지도를 덮는다.
        note: 1
    };
    var LABEL_MIN_ZOOM_DEFAULT = 17;

    /** 이 위젯의 라벨 숨김 기준 줌. 0(또는 미설정 0) = 숨기지 않음. */
    function _labelMinZoom(instance) {
        var o = (instance && instance.vars && instance.vars.vars) || {};
        var v = parseFloat(o.label_min_zoom);
        if (isNaN(v)) return LABEL_MIN_ZOOM_DEFAULT;
        return Math.max(0, Math.min(22, v));
    }
    // 사용자가 고른(호버/클릭) 라벨은 종류와 무관하게 최상단으로 올린다.
    var LABEL_Z_FRONT = 9000;

    function _labelZ(kind) {
        var z = LABEL_Z[kind];
        return z != null ? z : LABEL_Z.zone;
    }

    // "고른 라벨을 앞으로" 동작을 인스턴스에 1회 설치한다.
    // 클릭은 PIN(연 팝업/모달이 닫힐 때까지 유지) — hover-only 복귀는 팝업을
    // 만지러 포인터가 라벨을 벗어나는 순간 되돌아가 버린다. 인스턴스당 하나만
    // 핀 되도록 상태를 공유한다.
    function _ensurePinHelpers(instance) {
        if (instance._pinLabelToFront) return;
        instance._pinnedLabel = null; // { el, restore }
        instance._pinLabelToFront = function (pinEl, restoreFn) {
            if (instance._pinnedLabel && instance._pinnedLabel.el !== pinEl) {
                instance._pinnedLabel.restore();
            }
            pinEl.style.zIndex = String(LABEL_Z_FRONT);
            instance._pinnedLabel = { el: pinEl, restore: restoreFn };
        };
        instance._unpinLabel = function (pinEl) {
            if (instance._pinnedLabel && instance._pinnedLabel.el === pinEl) {
                instance._pinnedLabel.restore();
                instance._pinnedLabel = null;
            }
        };
    }

    /**
     * Give one label/key element its base stacking order plus the shared
     * hover/click "bring to front" behaviour. Returns the restore function so
     * the caller can hand it to _pinLabelToFront on click.
     *
     *   kind : LABEL_Z key ('site' | 'zone' | 'facility' | 'equipment' |
     *                       'output' | 'input' | 'function')
     */
    function _wireLabelStacking(instance, el, kind) {
        _ensurePinHelpers(instance);
        // 종류를 요소에 새긴다 — 쌓임(z), 충돌 우선순위, 줌 게이트가 모두 이걸 읽는다.
        el.dataset.labelKind = kind;
        // 기준 z 는 dataset 에 둔다 — 나중에 종류가 확정돼 바뀌어도
        // (_setLabelBaseZ) 이미 붙은 복귀 핸들러가 옛 값을 되살리지 않는다.
        el.dataset.baseZ = String(_labelZ(kind));
        el.style.zIndex = el.dataset.baseZ;
        _applyZoomGateTo(el, instance);
        var restore = function () { el.style.zIndex = el.dataset.baseZ || '0'; };
        el.addEventListener('mouseenter', function () {
            el.style.zIndex = String(LABEL_Z_FRONT);
        });
        el.addEventListener('mouseleave', function () {
            // 핀 된(클릭해서 팝업을 연) 라벨은 포인터가 떠나도 앞에 남긴다.
            if (!instance._pinnedLabel || instance._pinnedLabel.el !== el) restore();
        });
        return restore;
    }

    /** Re-assign an already-wired label's base order (kind became known later). */
    function _setLabelBaseZ(instance, el, kind) {
        el.dataset.labelKind = kind;
        el.dataset.baseZ = String(_labelZ(kind));
        var pinned = instance._pinnedLabel && instance._pinnedLabel.el === el;
        if (!pinned) el.style.zIndex = el.dataset.baseZ;
        _applyZoomGateTo(el, instance);
    }

    /** 한 요소에 줌 게이트를 적용한다. 감춤은 .aot-zoom-hidden 클래스로만 한다 —
     *  충돌 회피가 인라인 display 를 직접 건드리므로 그것과 섞이면 안 된다. */
    function _applyZoomGateTo(el, instance) {
        var map = instance && instance.map;
        if (!el || !map || typeof map.getZoom !== 'function') return;
        var min = _labelMinZoom(instance);
        el.classList.toggle('aot-zoom-hidden',
            min > 0 && !!LABEL_ZOOM_GATED[el.dataset.labelKind] && map.getZoom() < min);
    }

    /**
     * Re-apply the zoom gate to every label/key of this widget.
     * Installed once per instance; runs on zoom (rAF-throttled) and on zoomend.
     */
    function _applyZoomGate(instance) {
        var map = instance && instance.map;
        if (!map || typeof map.getContainer !== 'function') return;
        var z = map.getZoom();
        var min = _labelMinZoom(instance);
        var gated = min > 0 && z < min;
        map.getContainer().querySelectorAll('[data-label-kind]').forEach(function (el) {
            el.classList.toggle('aot-zoom-hidden',
                gated && !!LABEL_ZOOM_GATED[el.dataset.labelKind]);
        });

        // 입력 라벨이 줌으로 가려지는 순간 구역 라벨이 그 몫을 넘겨받고, 다시
        // 드러나면 돌려준다(구역 라벨은 줌 게이트 대상이 아니라 계속 떠 있다).
        // **바뀐 때만** 다시 칠한다 — 이 함수는 줌 제스처 내내 프레임마다 돈다.
        if (instance._inputZoomGated !== gated) {
            instance._inputZoomGated = gated;
            if (instance._repaintZoneLabels) {
                try { instance._repaintZoneLabels(); } catch (e) {}
            }
        }
    }

    // ── 임시 표시(focus) ──────────────────────────────────────────────────────
    // 사용자가 꺼 둔 도형·라벨이라도 **지금 봐야 할 이유**가 있으면 잠깐 보인다:
    //
    //   모달이 열려 있다 → 그 대상       (어디 이야기인지 지도에서 못 찾으면
    //                                     모달의 값이 어느 자리 것인지 알 수 없다)
    //   출력이 켜져 있다 → 그 장치       (지금 돌고 있는 것이 안 보이면 안 된다)
    //
    // **꺼 둔 상태를 바꾸지 않는다.** 토글을 켜 버리면 모달을 닫았을 때 사용자가
    // 꺼 둔 것이 켜진 채로 남는다. 그래서
    //   라벨 → `.aot-focus-show` 클래스(숨김 규칙이 이 클래스를 비켜 간다 —
    //          display 를 지정하지 않으므로 각 라벨의 생김새가 그대로 남는다)
    //   도형 → 카테고리 레이어를 켜는 대신 **전용 소스에 덧그린다**
    //
    // 이유가 둘이므로 **이유별로 센다.** 모달을 닫았다고 바로 끄면 그 장치가
    // 아직 켜져 있는데도 사라진다.
    var _focus = {};    // uid -> { targets: { key: {reason:1} }, feats: {key: feature} }

    function _focusState(uid) {
        if (!_focus[uid]) _focus[uid] = { targets: {}, feats: {} };
        return _focus[uid];
    }

    /** 이 위젯 지도 안에서 그 대상의 라벨 요소들. 라벨마다 uuid 를 담은 속성이
     *  달라서(도형 라벨=parentId · 구획 칩=plotUuid · 시설 칩=facilityId) 한꺼번에
     *  훑는다. 하나라도 맞으면 그 라벨이다. */
    function _focusLabelEls(instance, uuid) {
        var cont = instance && instance.map && instance.map.getContainer &&
                   instance.map.getContainer();
        if (!cont || !uuid) return [];
        var sel = ['parent-id', 'plot-uuid', 'facility-id', 'device-id', 'output-id',
                   'shape-uuid', 'bay-id']
            .map(function (a) { return '[data-' + a + '="' + uuid + '"]'; }).join(',');
        try { return Array.prototype.slice.call(cont.querySelectorAll(sel)); }
        catch (e) { return []; }
    }

    /** 대상 도형을 소스들에서 찾는다. 레이어마다 uuid 를 담은 속성 이름이 달라
     *  후보를 순서대로 본다. 못 찾으면 null(그때는 라벨만 보인다). */
    var _FOCUS_ID_KEYS = ['id', 'node_id', 'shape_uuid', 'unique_id', 'device_id',
                          'plot_uuid', 'parent_id'];

    /**
     * 같은 uuid 를 가진 피처 중 **면(Polygon)을 우선**해서 고른다.
     *
     * 장치는 한 uuid 에 피처가 둘이다 — 위치 **마커**(Point)와 그 장치가 맡은
     * **영역**(Polygon). 먼저 만나는 것을 잡으면 대개 Point 가 걸리는데, 이
     * 표시는 fill/line 레이어로 그리므로 점은 아무것도 그리지 못한다(실측:
     * `hasFeature: true, geom: 'Point'` 인데 그려진 피처는 0개였다).
     *
     * 점밖에 없으면 그것이라도 돌려준다 — 못 찾은 것과 구별돼야 재조회를
     * 반복하지 않는다.
     */
    function _findInFeatures(feats, uuid) {
        var fallback = null;
        for (var j = 0; j < (feats || []).length; j++) {
            var pr = feats[j].properties || {};
            var hit = false;
            for (var k = 0; k < _FOCUS_ID_KEYS.length && !hit; k++) {
                var v = pr[_FOCUS_ID_KEYS[k]];
                if (v && String(v) === String(uuid)) hit = true;
            }
            if (!hit) continue;
            var g = feats[j].geometry || {};
            if (/Polygon/.test(g.type || '')) return feats[j];
            if (!fallback) fallback = feats[j];
        }
        return fallback;
    }

    function _findShapeFeature(map, uid, uuid) {
        if (!map || !uuid) return null;
        // 이미 지도에 올라온 소스들 먼저 — 대부분 여기서 끝난다.
        var srcs = ['zones', 'sites', 'facilities', 'aot_devices', 'equipment',
                    'aot-plot-src-' + uid];
        var fallback = null;
        for (var i = 0; i < srcs.length; i++) {
            var src = map.getSource(srcs[i]);
            var hit = _findInFeatures((src && src._data && src._data.features) || [],
                                      uuid);
            if (!hit) continue;
            // 면이면 바로 끝, 점이면 더 나은 것이 있는지 계속 본다.
            if (/Polygon/.test((hit.geometry || {}).type || '')) return hit;
            if (!fallback) fallback = hit;
        }
        if (fallback) return fallback;
        // 꺼 둔 종류는 소스가 없다 — 따로 받아 둔 것에서 찾는다.
        return _findInFeatures((_focusState(uid).pool) || [], uuid);
    }

    function _ensureFocusLayers(map, uid) {
        var src = 'aot-focus-src-' + uid;
        if (map.getSource(src)) return src;
        try {
            map.addSource(src, { type: 'geojson',
                                 data: { type: 'FeatureCollection', features: [] } });
            // 원래 색을 그대로 쓴다 — 강조색을 새로 만들면 "이건 무슨 색이지" 가
            // 하나 늘고, 이 표시의 목적은 강조가 아니라 **보이게 하는 것**이다.
            //
            // ⚠ 색은 피처에 없다. 도형의 색은 `feature.properties.color` 가 아니라
            // **테마(theme_config)** 가 정한다(CLAUDE.md — 각인 금지). `['get','color']`
            // 로 읽으면 거의 항상 비어 폴백 한 색으로 통일돼 버린다(실측: 켜진 출력이
            // 브랜드 딥그린으로 나왔다). `_repaintFocus` 가 종류마다 테마를 해석해
            // `aot_focus_color` 로 찍어 주고, 여기서는 그것만 읽는다 — 찍는 것은 소스에
            // 넣는 사본뿐이라 DB 의 도형에는 색이 되쓰이지 않는다.
            map.addLayer({
                id: 'aot-focus-fill-' + uid, type: 'fill', source: src,
                filter: ['==', ['geometry-type'], 'Polygon'],
                paint: { 'fill-color': ['coalesce', ['get', 'aot_focus_color'], '#13261B'],
                         'fill-opacity': 0.18 }
            });
            map.addLayer({
                id: 'aot-focus-line-' + uid, type: 'line', source: src,
                filter: ['==', ['geometry-type'], 'Polygon'],
                paint: { 'line-color': ['coalesce', ['get', 'aot_focus_color'], '#13261B'],
                         'line-width': 2 }
            });
            // **면이 없는 장치가 있다.** 위치 마커만 있고 맡은 영역이 없는 것
            // (koat 실측: 출력 18개 중 펌프 2개가 점뿐이었다). 면만 그리면 그
            // 장치들은 라벨만 켜지고 도형은 영영 안 나온다 — 사용자에게는
            // "출력을 켜도 도형이 활성화되지 않는다" 로 보인다.
            //
            // 자리에 고리를 그린다. 채우지 않는 것은 마커 라벨을 가리지 않기
            // 위해서고, 이 규약은 `_highlightShape` 의 점 처리와 같다.
            map.addLayer({
                id: 'aot-focus-pt-' + uid, type: 'circle', source: src,
                filter: ['==', ['geometry-type'], 'Point'],
                paint: {
                    'circle-radius': 14,
                    'circle-color': 'rgba(0,0,0,0)',
                    'circle-stroke-color':
                        ['coalesce', ['get', 'aot_focus_color'], '#13261B'],
                    'circle-stroke-width': 3,
                    'circle-stroke-opacity': 0.9
                }
            });
        } catch (e) { return null; }
        return src;
    }

    // 임시 표시의 색 = **평소 그 도형이 갖는 색**. 종류마다 해석이 다르므로
    // (장치는 device_type 별, 나머지는 카테고리 키) 카테고리를 함께 들고 온다.
    var _FOCUS_THEME_KEY = { land: 'site', zone: 'zone', facility: 'facility',
                             equipment: 'equipment', plot: 'plot' };

    function _focusColor(instance, cat, feat) {
        var T = window.AoTGeoTheme;
        var theme = (instance && instance._geoTheme) || {};
        if (!T) return null;
        var pr = (feat && feat.properties) || {};
        if (cat === 'device' || (!cat && pr.device_type)) {
            return T.deviceColor(pr.device_type || pr.aot_device_type || '', theme);
        }
        // 구획만은 피처가 자기 색을 갖는다 — 구획 행(`GeoPlot.color`)에서 온
        // 값이라 각인된 색(테마 드리프트)이 아니고, 평소 레이어도 그것을 칠한다.
        // 나머지 종류는 절대 `properties.color` 를 보지 않는다: GeoShape 에
        // 남아 있을 수 있는 옛 각인 색을 되살리게 된다(CLAUDE.md 색 정본 절).
        if (cat === 'plot' && pr.color) return pr.color;
        var key = _FOCUS_THEME_KEY[cat];
        if (!key) {
            // 카테고리를 모르면 도형이 스스로 말하는 종류로 되짚는다.
            var t = String(pr.aot_type || pr.type || '').toLowerCase();
            key = _FOCUS_THEME_KEY[t === 'site' ? 'land' : t];
        }
        return key ? T.color(key, theme) : null;
    }

    function _repaintFocus(instance, uid) {
        var map = instance && instance.map;
        var st = _focusState(uid);
        if (!map) return;
        var feats = [];
        Object.keys(st.targets).forEach(function (uuid) {
            var f = st.feats[uuid];
            // 면이 없는 장치는 점이라도 그린다(위 `aot-focus-pt-` 고리).
            if (!f || !f.geometry || !/Polygon|Point/.test(f.geometry.type)) return;
            var color = _focusColor(instance, (st.cats || {})[uuid], f);
            // **사본**에만 찍는다 — 원본에 쓰면 그 값이 저장 경로를 타고 도형에
            // 각인될 수 있고, 그러면 테마를 바꿔도 그 도형만 옛 색으로 남는다.
            var props = {};
            Object.keys(f.properties || {}).forEach(function (k) {
                props[k] = f.properties[k]; });
            if (color) props.aot_focus_color = color;
            feats.push({ type: 'Feature', geometry: f.geometry, properties: props });
        });
        var src = _ensureFocusLayers(map, uid);
        if (!src) return;
        try {
            map.getSource(src).setData({ type: 'FeatureCollection', features: feats });
        } catch (e) {}
    }

    // 도형 원본을 **직접** 받아 둔다.
    //
    // ⚠ `_ensureShapeLayer[cat]` 을 부르면 안 된다 — 그것은 카테고리 **레이어를
    // 만들고**, 만들어진 레이어는 보인다. 실측으로 출력 하나가 켜지자 **모든**
    // 장치 도형이 떴고, 다른 모달이 열려 카테고리가 정상 상태로 돌아가는 순간
    // 그 전부가 함께 사라졌다. 우리가 필요한 것은 레이어가 아니라 **피처 하나**다.
    //
    // 받아 온 것은 focus 소스에만 들어가므로, 카테고리를 꺼 둔 상태는 처음부터
    // 끝까지 그대로다.
    var _FOCUS_OVERLAY_TYPE = { device: 'aot_device', zone: 'zone', land: 'site',
                                facility: 'facility', equipment: 'equipment' };

    function _fetchFocusShapes(instance, uid, cat) {
        var st = _focusState(uid);
        if (st['_fetch_' + cat]) return;          // 종류당 한 번

        // ⚠ **가드는 실제로 요청을 보낼 때만 세운다.**
        //
        // 예전에는 함수 첫 줄에서 세웠는데, 그러면 **실패한 시도가 기회를 태워
        // 버린다** — 아직 지도 uuid 를 못 읽는 이른 시점에 한 번 불리면 그대로
        // 영구히 죽고, 그 위젯에서는 꺼 둔 종류의 도형이 다시는 안 나온다.
        // 증상이 고약하다: 장치 도형 레이어를 **켰다 끄면** 그때부터 동작한다
        // (그 조작이 `aot_devices` 소스를 만들어 이 경로를 건너뛰게 하므로).
        // 사용자가 찾아낸 그 우회법이 곧 진단이었다.
        //
        // 같은 이유로 **응답이 실패하거나 비면 가드를 되돌린다.** 한 번의 네트워크
        // 오류가 그 위젯의 남은 세션 전체를 결정해서는 안 된다.
        var type = _FOCUS_OVERLAY_TYPE[cat];
        var mapUuid = (instance.vars && instance.vars.vars &&
                       (instance.vars.vars.selected_map_uuid ||
                        instance.vars.vars.map_uuid)) ||
                      (instance.vars && instance.vars.contentMapUuid) || '';
        if (!type || !mapUuid) return;            // 가드를 세우지 않는다 — 다시 온다
        st['_fetch_' + cat] = 1;
        geoFetch('/api/geo/overlays?map_uuid=' + encodeURIComponent(mapUuid) +
                 '&type=' + encodeURIComponent(type))
            .then(function (r) { return r.json(); })
            .then(function (gj) {
                var feats = (gj && gj.features) || [];
                if (!feats.length) { st['_fetch_' + cat] = 0; return; }
                st.pool = st.pool || [];
                st.pool = st.pool.concat(feats);
                // 기다리고 있던 대상들을 다시 찾는다.
                var changed = false;
                Object.keys(st.targets).forEach(function (u) {
                    var cur = st.feats[u];
                    // 점을 잡아 둔 것도 면이 오면 갈아 준다 — 그리는 것은 면이다.
                    if (cur && /Polygon/.test((cur.geometry || {}).type || '')) return;
                    var f = _findInFeatures(feats, u);
                    if (f && f !== cur) { st.feats[u] = f; changed = true; }
                });
                if (changed) _repaintFocus(instance, uid);
            })
            .catch(function () { st['_fetch_' + cat] = 0; });
    }

    /**
     * 대상 하나를 임시로 보이게 하거나(on) 그 이유를 거둔다(off).
     *   uuid   대상 식별자(구역·시설·구획·장치 어느 것이든)
     *   reason 'modal' | 'active'  — 이유별로 세므로 서로를 끄지 않는다
     */
    function _setFocus(instance, uid, uuid, reason, on, cat) {
        if (!instance || !uuid) return;
        var st = _focusState(uid);
        var box = st.targets[uuid] || (st.targets[uuid] = {});
        if (on) {
            box[reason] = 1;
            // 색을 해석하려면 종류가 필요하다(장치는 device_type, 나머지는 카테고리).
            if (cat) (st.cats || (st.cats = {}))[uuid] = cat;
            if (!st.feats[uuid]) {
                st.feats[uuid] = _findShapeFeature(instance.map, uid, uuid);
                // **못 찾는 것이 정상인 경우가 있다.** 그 종류의 도형을 꺼 두면
                // 데이터 자체를 안 받아온다 — 레이어는 옵션이 켜져 있을 때만
                // 만들어진다(`_ensureShapeLayer` 주석). 그래서 "켜진 장치의
                // 도형" 을 덧그리려 해도 그릴 것이 클라이언트에 없었다.
                //
                // 받아온 뒤 다시 찾는다. 받아오는 것과 **보이는 것은 별개**다 —
                // 카테고리 visibility 는 `_applyShapeLOD` 가 정하므로 꺼 둔
                // 상태는 그대로다.
                //
                // ⚠ **종류를 모르면 아는 종류를 전부 받는다.** 모달 쪽 호출부는
                // `cat` 을 넘기지 않는데(공용 셸 하나가 구역·구획·시설·장치를
                // 모두 연다), 그것을 그대로 두면 **꺼 둔 종류의 대상은 모달을
                // 열어도 아무 일도 일어나지 않는다** — 2026-08-23 실측: 장치
                // 도형 카테고리(`show_device_shapes`)가 꺼진 위젯에서 장치를
                // 골라도 도형이 뜨지 않았다(켜진 출력만 `'device'` 를 넘겨
                // 우연히 동작했다).
                //
                // 종류당 한 번만 받고(`_fetch_<cat>` 가드) 받은 것은 이 표시
                // 전용 소스에만 들어가므로, 꺼 둔 카테고리는 그대로 꺼져 있다.
                // 호출부마다 종류를 적게 하는 편이 정확하지만, 빠뜨렸을 때
                // 조용하다는 것이 이 결함의 전부였다.
                if (!st.feats[uuid]) {
                    var _cats = cat ? [cat] : Object.keys(_FOCUS_OVERLAY_TYPE);
                    _cats.forEach(function (c) { _fetchFocusShapes(instance, uid, c); });
                }
            }
        } else {
            delete box[reason];
            if (!Object.keys(box).length) {
                delete st.targets[uuid];
                delete st.feats[uuid];
                if (st.cats) delete st.cats[uuid];
            }
        }
        var show = !!st.targets[uuid];
        _focusLabelEls(instance, uuid).forEach(function (el) {
            el.classList.toggle('aot-focus-show', show);
        });
        _repaintFocus(instance, uid);
    }

    /** 이 위젯에 걸린 'modal' 이유를 전부 거둔다.
     *
     *  모달은 한 번에 하나이므로 이유도 하나뿐이고, **새 창을 열 때 먼저 거두는
     *  것**이 가장 확실하다. 창마다 닫힘 리스너에만 맡기면 갈아 끼우는 경로
     *  (`existing.remove()`)가 그 리스너를 지나지 않아 앞 대상이 계속 보인다
     *  (실측으로 그랬다). */
    function _clearModalFocus(instance, uid) {
        var st = _focusState(uid);
        Object.keys(st.targets).forEach(function (u) {
            if (st.targets[u] && st.targets[u].modal) {
                _setFocus(instance, uid, u, 'modal', false);
            }
        });
    }

    // 진단 훅 — 임시 표시가 왜 안 보이는지는 **어디서 끊겼는지**를 봐야 알 수
    // 있다(이유가 안 붙었나 · 도형을 못 찾았나 · 레이어가 없나). 화면만 보고는
    // 셋을 구별할 수 없어서 상태를 그대로 내보낸다.
    function _installFocusDebug(instance, uid) {
        if (instance._focusDebug) return;
        instance._focusDebug = function () {
            var st = _focusState(uid);
            var m = instance.map;
            var src = m && m.getSource('aot-focus-src-' + uid);
            return {
                targets: Object.keys(st.targets).map(function (u) {
                    return { uuid: u, reasons: Object.keys(st.targets[u]),
                             hasFeature: !!st.feats[u],
                             geom: st.feats[u] && st.feats[u].geometry
                                 ? st.feats[u].geometry.type : null };
                }),
                pool: (st.pool || []).length,
                fetched: Object.keys(st).filter(function (k) {
                    return k.indexOf('_fetch_') === 0; }),
                srcFeatures: src && src._data ? (src._data.features || []).length : null,
                layers: ['aot-focus-fill-' + uid, 'aot-focus-line-' + uid,
                         'aot-focus-pt-' + uid]
                    .map(function (l) { return l + '=' + (m && m.getLayer(l) ? 'ok' : 'none'); })
            };
        };
        instance._focusSet = function (uuid, reason, on, cat) {
            _setFocus(instance, uid, String(uuid), reason || 'active', on !== false, cat);
        };
    }

    function _installZoomGate(instance, map, uid) {
        _installFocusDebug(instance, uid);
        if (instance._zoomGateHandler) return;
        var raf = null;
        instance._zoomGateHandler = function () {
            if (raf) return;
            raf = requestAnimationFrame(function () { raf = null; _applyZoomGate(instance); });
        };
        // 'zoom' 은 제스처 중에도 계속 발화 — 축척이 기준을 넘는 순간 바로 반응한다.
        // 'zoomend' 는 마지막 상태를 확실히 맞추는 보정.
        map.on('zoom', instance._zoomGateHandler);
        map.on('zoomend', instance._zoomGateHandler);
        // 설정 모달의 라이브 적용이 부르는 훅 — 옵션(label_min_zoom)만 바뀌면
        // 라벨을 다시 만들 필요 없이 클래스만 재평가하면 된다.
        instance._applyZoomGate = function () { _applyZoomGate(instance); };
        _applyZoomGate(instance);
    }

    // ── Unified label-visibility model (shared constants) ──────────────────────
    // Single key namespace `label_hidden_<key>` drives every label category.
    // Mirrors the copies inside addLayerPanel's toolbar IIFE (kept in sync by
    // name) — duplicated here at module scope so _seedHiddenLabelsEarly can run
    // BEFORE addLayerPanel exists (see call site, right after instance creation).
    var _LABEL_DEVICE = { input: 1, output: 1, 'function': 1 };
    var _LABEL_REGCAT = { site: 'land', zone: 'zone', facility: 'facility', equipment: 'equipment', sensor: 'sensor' };
    // ⚠ 새 종류는 위 "네 표" 주석 참조. **아래 9424 줄의 같은 배열도 함께
    // 고쳐야 한다** — 한쪽만 고치면 시드와 컨트롤이 다른 목록을 본다.
    // 동(bay)은 여기 없다 — **시설 토글이 담당**한다(지도의 시설 이름이 곧 동
    // 칩이다). 줌 게이트·쌓임·충돌 표에는 그대로 있다(칩이 'bay' 로 새겨진다).
    var LABEL_KEYS = ['input', 'output', 'function', 'facility', 'plot',
                      'site', 'zone', 'equipment', 'sensor'];

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
            // 모니터 전체화면이 아니라 **브라우저 뷰포트**를 덮는다
            // (`_toggleMapMaximize` 주석에 근거).
            _toggleMapMaximize(widgetWrap);
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

            /**
             * 목록에서 고른 항목 → 그 도형의 모달.
             *
             * 예전에는 지도만 옮기고 목록이 그대로 사라졌다. 고른 것이 무엇인지
             * 확인할 화면이 없어서, 이름을 눌렀는데 지도가 움직이고 끝이었다.
             * 이제 목록을 닫고 **그 자리에** 도형 모달을 연다(같은 오른쪽 자리다).
             * 카메라는 모달 쪽이 옮긴다 — 여기서 또 옮기면 두 번 움직인다.
             */
            function _openFromList(item, kind) {
                popup.remove();
                var opener = kind === 'zone' ? inst._openZoneModal : inst._openSiteModal;
                if (item && item.shape_uuid && typeof opener === 'function') {
                    opener(item.shape_uuid, item.name);
                    return;
                }
                // 도형 uuid 가 없는 항목(레거시 데이터)은 최소한 지도라도 옮긴다.
                _navigateTo(item);
            }

            function _navigateTo(item) {
                // 모달을 여는 경로와 **같은 카메라 로직**을 쓴다 — 가려진 영역
                // 계산도, 방향 보존도 한 곳(`_focusMapOn`)에만 있어야 갈리지 않는다.
                // 강조는 걸지 않는다(목록은 도형을 고르는 중이지 연 것이 아니다).
                if (item.geometry) {
                    _focusMapOn(uniqueId, { geometry: item.geometry },
                                { force: true, highlight: false, transient: true });
                    return;
                }
                if (item.lat != null && item.lng != null) {
                    _focusMapOn(uniqueId,
                                { lng: parseFloat(item.lng), lat: parseFloat(item.lat),
                                  zoom: item.zoom || 17 },
                                { force: true, highlight: false, transient: true });
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
                  '#' + sid + ' .aot-sl-list{flex:1;min-height:0;overflow-y:auto;scrollbar-width:none;padding:1px;}' +
                  '#' + sid + ' .aot-sl-list::-webkit-scrollbar{width:0;height:0;}' +
                  // Rows = rounded cards, matching every other card in the app
                  // (--aot-surface-card = 배경 기본): 1px border, .4rem radius,
                  // gap between cards. NO left guide bar (the previous brand-green
                  // inset read as a black line).
                  '#' + sid + ' .aot-sl-row{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
                    'padding:.55rem .6rem;margin-bottom:.35rem;border-radius:.4rem;' +
                    'border:1px solid var(--aot-border-light);background:var(--aot-surface-card);' +
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
            // 헤더는 공용 빌더(AoTMapPopup.buildModalHeader)로 — 다른 모든
            // .aot-center-modal 헤더(구역/시설/필지 모달)와 같은 제목 크기·
            // 닫기 버튼 여백을 쓴다. .aot-center-modal 의 **직속 자식**이어야
            // 밑줄(border-bottom) 규칙이 먹는다 — #sid 래퍼 안에 넣으면 안 됨.
            const modalHtml =
                scopedCss +
                window.AoTMapPopup.buildModalHeader({ name: _tr('Sites') }) +
                '<div id="' + sid + '">' +
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

            const titleEl  = wrap.querySelector('.aot-sensor-popup-title');
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
                            _openFromList(z, 'zone');
                        }, zoneDrag);
                        zrow.dataset.slot = _keyOf(z);
                        zonesEl.appendChild(zrow);
                    });

                    const row = _row(s.name, zones.length > 0 ? '▾' : null, null, function() {
                        if (_openSite === s) {
                            // Already expanded → this site is now a direct go-to.
                            _openFromList(s, 'site');
                        } else if (zones.length > 0) {
                            // Collapsed site with zones → expand its zone dropdown.
                            _expand(s, row, zonesEl);
                        } else {
                            // Zone-less site → open immediately.
                            _openFromList(s, 'site');
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
            // Width classes gate the compact LEGEND. Viewport media queries were
            // wrong here: a widget is not the window — a narrow widget on a wide
            // desktop got the roomy legend, and a full-width widget on a phone
            // got the cramped one. Measure the widget itself.
            const w = widgetWrap.clientWidth;
            widgetWrap.classList.toggle('aot-map-w-sm', w > 0 && w < 420);
            // xs 에서 시간 독은 CSS 로 숨는다(.aot-map-h-xs .aot-time-dock).
            // 숨은 높이는 0 이어야 검색바·조언 칩이 원래 자리로 돌아간다.
            try { _updateTopDockHeightVar(uniqueId); } catch (e) {}
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

                // 모달이 대상 도형을 찾을 수 있게 uuid → 도형을 캐시한다.
                // 지도 소스만으로는 부족하다 — 구역 폴리곤은 지도에 레이어로
                // 올라가지 않는 구성이 있고(라벨만 그린다), 그러면 구역 모달을
                // 열어도 옮길 곳도 강조할 것도 못 찾는다. 목록은 어차피 같은
                // overlays 를 받으므로 여기서 한 번에 담아 둔다.
                const shapeCache = {};

                features.forEach(function(f) {
                    const p = f.properties || {};
                    const aotType = String(p.aot_type || '').toLowerCase();
                    if (p.shape_uuid && f.geometry) {
                        shapeCache[p.shape_uuid] = {
                            geometry: f.geometry,
                            color: p.color || null,
                            aot_type: aotType
                        };
                    }
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
                            // 목록에서 고른 항목의 **모달**을 열려면 도형 uuid 가
                            // 있어야 한다(db_id 는 순서 저장용 키일 뿐이다).
                            shape_uuid: p.shape_uuid || null,
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
                            shape_uuid: p.shape_uuid || null,
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
                instance._shapeCache = Object.assign(instance._shapeCache || {}, shapeCache);
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
            // 식생 구획 — 레이어 id 는 uid 가 붙어 고정 문자열이 아니다.
            // `layers` 는 아래 _applyShapeLOD/_applyShapeVisible 이 쓰는 실제 id 라
            // 여기서 만들어 넣는다(aot-map-plot.js 의 _ids 와 같은 규약).
            { cat: 'plot', label: (window._ ? window._('Plot') : 'Plot'),
              layers: ['aot-plot-fill-' + uniqueId, 'aot-plot-line-' + uniqueId,
                       'aot-plot-line-planned-' + uniqueId] },
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

        // Same key loadGeoJSONLayers' _boolOpt('show_X_shape') gates layer
        // CREATION on (init-time and on-demand via _ensureShapeLayer). This
        // panel used to read/write a separate 'cat_hidden_<cat>' key — visually
        // toggling on-demand-created layers just fine in the moment, but on the
        // next full page load _boolOpt('show_X_shape') was still whatever the
        // Settings modal last saved (default False for all 6 categories), so
        // the layer was never even created and the toggle looked reverted.
        // 'device' maps to 'show_device_shapes' (plural) — matches the actual
        // AoT_map.py option id, not a naming mistake.
        const _CAT_SHOW_KEY = {
            land: 'show_site_shape', zone: 'show_zone_shape', facility: 'show_facility_shape',
            equipment: 'show_equipment_shape', device: 'show_device_shapes', drawn: 'show_drawn_shapes',
            plot: 'show_plots'
        };

        function _catReadSaved(cat) {
            var showKey = _CAT_SHOW_KEY[cat];
            if (showKey) {
                var sv = innerVars[showKey];
                if (sv === true || sv === 'true') return false;  // shown -> not hidden
                if (sv === false || sv === 'false') return true; // not shown -> hidden
            }
            // Legacy fallback for widgets saved before this key unification.
            var legacy = innerVars['cat_hidden_' + cat];
            if (legacy === true || legacy === 'true') return true;
            if (legacy === false || legacy === 'false') return false;
            try {
                var lv = localStorage.getItem(_catLsPrefix + cat);
                return lv === 'true';
            } catch (e) { return false; }
        }
        function _catSave(cat, hidden) {
            var showKey = _CAT_SHOW_KEY[cat];
            if (showKey) {
                // Update the in-memory options FIRST so a same-tick on-demand
                // layer creation (_applyShapeVisible -> _ensureShapeLayer,
                // which re-checks _boolOpt(showKey)) sees the fresh value
                // instead of racing its own persisted change.
                innerVars[showKey] = !hidden;
                var patch = {}; patch[showKey] = !hidden;
                fetch('/save_widget_custom_options', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ widget_id: _catWidgetId, options: patch })
                }).catch(function (e) { });
            }
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
            // 구획 도형은 그 모듈이 관리한다(레이어 id 에 uid 가 붙어 여기서
            // 직접 못 만진다). **도형만** 끈다 — 라벨은 라벨 컨트롤의 일이다.
            // 예전에는 `setVisible`(도형+라벨)을 불러서, 다른 계층과 달리 구획만
            // 도형을 끄면 이름까지 사라졌다.
            if (cat === 'plot' && window.AoTMapPlot &&
                    window.AoTMapPlot.setShapeVisible) {
                try { window.AoTMapPlot.setShapeVisible(uniqueId, map, visible); }
                catch (e) { }
            }
            // Turning a category ON that was OFF at widget load never had its
            // MapLibre layer created (loadGeoJSONLayers only fetches/adds a
            // category's layer when its show_*_shape option was already true) —
            // setLayoutProperty below is then a silent no-op on a nonexistent
            // layer id, so the toggle visually does nothing until the next full
            // page refresh re-runs init. Create it on demand the first time.
            var firstLayerId = def.layers && def.layers[0];
            var needsCreate = visible && firstLayerId && !map.getLayer(firstLayerId);
            if (needsCreate) {
                var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uniqueId];
                var ensureFn = inst && inst._ensureShapeLayer && inst._ensureShapeLayer[cat];
                if (typeof ensureFn === 'function') {
                    ensureFn().then(_applyShapeLOD).catch(function () {});
                    return;
                }
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
        // ---- Copyright button + credit panel — ALWAYS its own standalone
        // group, entirely independent of the functional rail below. ----
        // The credit is a licence requirement, not a "control": hideControls
        // (_rightHidden, from the widget's saved option) AND the in-canvas
        // Hide-Button toggle (btnHide, live — see _wire(btnHide,...) above)
        // both only ever touch the FUNCTIONAL rail (#map-tools-right-*), never
        // this element. Earlier this button lived inside that rail when shown
        // and in a separate standalone element when hidden, decided once at
        // build time — but btnHide flips the rail's `display` live, on the
        // SAME already-built DOM, without knowing which case had been chosen.
        // Toggling controls back on then revealed a SECOND, empty rail sitting
        // exactly on top of the standalone button — a visible duplicate.
        // A single element that neither flag ever reaches cannot double up.
        const attribHost = document.createElement('div');
        attribHost.id = 'map-attrib-' + uniqueId;
        attribHost.style.cssText = 'position:absolute; top:10px; right:10px; z-index:20;';
        mapContainer.appendChild(attribHost);
        const attribGroup = document.createElement('div');
        attribGroup.className = 'tool-group aot-map-attrib-group';
        attribHost.appendChild(attribGroup);

        const attribWrap = document.createElement('div');
        attribWrap.style.cssText = 'position:relative;';
        attribGroup.appendChild(attribWrap);

        const attribBtn = document.createElement('a');
        attribBtn.href = '#';
        attribBtn.className = 'btn btn-white';
        attribBtn.setAttribute('role', 'button');
        const _attribTitle = (typeof window._ === 'function') ? window._('Copyright') : 'Copyright';
        if (window.AoTSetTitle) window.AoTSetTitle(attribBtn, _attribTitle); else attribBtn.title = _attribTitle;
        const attribIcon = document.createElement('i');
        attribIcon.className = 'fas fa-info-circle';
        attribBtn.appendChild(attribIcon);
        attribWrap.appendChild(attribBtn);

        // Panel hangs off the host, not the group: .tool-group clips overflow.
        // Its default CSS (top:0; right:40px) is written relative to a
        // position:absolute host at the top-right corner — true of both the
        // toolbar and the standalone host above, so no separate class needed.
        const attribPanel = document.createElement('div');
        attribPanel.className = 'aot-map-attrib-panel';
        attribPanel.style.display = 'none';
        attribHost.appendChild(attribPanel);

        function _attribHtml() {
            // MapLibre's own control stays in the DOM (hidden) and remains the
            // source of truth — it tracks which sources are actually rendered.
            const inner = mapContainer.querySelector('.maplibregl-ctrl-attrib-inner');
            return inner ? inner.innerHTML.trim() : '';
        }
        function _showAttrib() {
            const html = _attribHtml();
            if (!html) return;
            attribPanel.innerHTML = html;
            attribPanel.style.display = 'block';
            // While the credit itself is showing, the button loses the
            // dimmed/boxless idle treatment (.aot-map-attrib-group CSS) — that
            // treatment is specifically for reducing how much the button draws
            // the eye while collapsed, not for while the credit is already open.
            attribGroup.classList.add('is-open');
        }
        function _hideAttrib() {
            attribPanel.style.display = 'none';
            attribGroup.classList.remove('is-open');
        }

        attribBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            if (attribPanel.style.display === 'none') _showAttrib(); else _hideAttrib();
        });
        // Dismiss only when the user actually MOVES the map. Two things this is
        // deliberately not listening to:
        //   - `click`/`mousedown`: tapping a marker or a zone is not "done
        //     reading the credit", and dismissing there made the notice vanish
        //     the instant anyone touched the map.
        //   - `movestart`/`zoomstart`: they also fire for init-time
        //     flyTo/fitBounds and — measured — carry no `originalEvent` even for
        //     genuine gestures, so they can't tell a user apart from the code.
        // What is left only ever comes from a real manipulation.
        ['wheel', 'dragstart', 'touchmove', 'boxzoomstart'].forEach(function (ev) {
            try { map.on(ev, _hideAttrib); } catch (e) {}
        });
        try {
            map.once('idle', _showAttrib);
            const _inner = mapContainer.querySelector('.maplibregl-ctrl-attrib-inner');
            if (_inner && typeof MutationObserver !== 'undefined') {
                let _lastCredit = '';
                new MutationObserver(function () {
                    const t = _attribHtml();
                    if (t && t !== _lastCredit) { _lastCredit = t; _showAttrib(); }
                }).observe(_inner, { childList: true, subtree: true, characterData: true });
            }
        } catch (e) {}

        // ---- Unified right toolbar (Layers / Measure / Note / Hide-button /
        // ...). Independent of the copyright button above — see its comment. ----
        const toolbar = document.createElement('div');
        toolbar.id = 'map-tools-right-' + uniqueId;
        // Starts below the always-present copyright button (29px button +
        // 10px top gap + 8px breathing room ≈ 47px) so the two never overlap
        // regardless of which one hideControls/btnHide is currently hiding.
        toolbar.style.cssText = 'position:absolute; top:47px; right:10px; z-index:20; display:flex; flex-direction:column; align-items:center; gap:5px;';
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
            // ⚠ 위 8097 줄의 같은 배열과 **함께** 고칠 것(네 표 주석 참조).
            var LABEL_KEYS = ['input', 'output', 'function', 'facility',
                              'plot', 'site', 'zone', 'equipment', 'sensor'];

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
                    // **동 칩은 시설 토글이 끈다.** 지도에서 사람이 보는 시설
                    // 이름이 곧 이 칩이기 때문이다(시설 가장자리 칩은 예전에
                    // 없앴고 동 칩이 단일 진입점이다). 한때 동 토글로 갈랐다가
                    // "[시설] 을 눌러도 시설 이름이 안 꺼진다" 가 됐다 — 화면에
                    // 시설 라벨이 따로 없으니 그 버튼이 아무 일도 안 하는 것으로
                    // 보인다.
                    if (key === 'facility' && inst.bayMarkers) {
                        inst.bayMarkers.forEach(function(bm) {
                            if (bm && bm.el) bm.el.classList.toggle('aot-type-hidden', hidden);
                        });
                    }
                } else if (key === 'plot') {
                    // 구획 라벨은 다른 모듈(`AoTMapPlot`)이 만든다. 그 라벨의
                    // DOM 을 들고 있는 것도 그 모듈이므로 **클래스는 그쪽에서만
                    // 새긴다** — 여기서 한 번 더 새기면 두 곳이 같은 요소를
                    // 건드리는 자리가 되고, 나중에 한쪽만 고치면 조용히 갈린다
                    // (도형·라벨이 반대로 켜지던 사고가 그 모양이었다).
                    // `setLabelVisible` 은 폴링이 라벨을 다시 그릴 때도 이 값을
                    // 다시 입힌다(`_renderLabels` 의 `_applyLabelVisibility`).
                    if (window.AoTMapPlot && window.AoTMapPlot.setLabelVisible) {
                        try { window.AoTMapPlot.setLabelVisible(uniqueId, inst.map, !hidden); }
                        catch (e) {}
                    }
                }
                if (window.AoTMapLabelLayers && _LABEL_REGCAT[key]) {
                    try { AoTMapLabelLayers.setLabelVisible(uniqueId, _LABEL_REGCAT[key], !hidden); } catch (e) {}
                }
                if (!inst._hiddenLabels) inst._hiddenLabels = {};
                inst._hiddenLabels[key] = hidden;
                // 입력 라벨을 켜면 구역 라벨은 이름만, 끄면 대표값까지.
                // 같은 값을 두 겹으로 띄우지 않기 위한 맞물림이다.
                if (key === 'input' && inst._repaintZoneLabels) {
                    try { inst._repaintZoneLabels(); } catch (e) {}
                }
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
                // 함수 라벨 토글은 뺐다 — 누르는 일이 드물다. 그 자리를 구획
                // (plot)이 받는다: 한 구역에 두둑이 수십 개면 이 라벨이 지도에서
                // 가장 자주 걸린다.
                // (함수 라벨은 여전히 마스터 스위치 'Show Labels' 와 레이어
                //  컨트롤로 끌 수 있다 — 사라진 것은 빠른 버튼뿐이다.)
                { key: 'plot',     icon: 'fas fa-vector-square',     title: (window._ ? window._('Toggle Plot labels') : 'Toggle Plot labels') },
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
            if (inst && inst.layers) {
                inst.layers.forEach(function(_type, layerId) {
                    if (map.getLayer(layerId)) {
                        try { map.moveLayer(layerId); } catch (e) {}
                    }
                });
            }
            // Plot (vegetation/planting) layers live in a separate module
            // (aot-map-plot.js) and are never registered in inst.layers, so the
            // loop above never reaches them — its own load() is intentionally
            // un-awaited and can finish after a raster base has already been
            // inserted above it, leaving plots stuck under the raster with no
            // promotion ever catching them. Find them by the 'aot-plot-' naming
            // convention instead (the same one aot-map-custom-controls.js's
            // getLayerIdsByType('plot') relies on).
            const style = map.getStyle && map.getStyle();
            if (style && style.layers) {
                style.layers.forEach(function(layer) {
                    if (layer.id.indexOf('aot-plot-') === 0) {
                        try { map.moveLayer(layer.id); } catch (e) {}
                    }
                });
            }
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
            // 식생 구획도 setStyle 에 함께 지워진다 — layerDefs 캐시에는 없으므로
            // (자기 소스로 따로 올린다) 여기서 자기 캐시로 되살린다.
            if (window.AoTMapPlot && window.AoTMapPlot.rehydrate) {
                try { window.AoTMapPlot.rehydrate(uniqueId, map); } catch (e) {}
            }

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
                        AoTMapSensorLabels.attach(inst.uniqueId, map, inst.cachedFacilities3d,
                            _sensorLabelOptsFrom((_vars && _vars.vars) || {}, inst.uniqueId));
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
                    // _catSave first: it updates innerVars[show_X_shape] synchronously,
                    // so _applyShapeVisible's on-demand layer creation (when turning a
                    // never-created category on) reads the fresh value, not the stale one.
                    _catSave(d.cat, !input.checked);
                    _applyShapeVisible(d.cat, input.checked);
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

            // ⚠ **`LABEL_KEYS` 의 모든 종류가 여기 있어야 한다.** 빠진 종류는
            // 라벨 축을 켜고 끌 자리가 화면에 없는데, 저장은 계속 살아 있다 —
            // 구획이 실제로 그랬다: 도형 체크박스([도형] 그룹)만 있어서 사용자는
            // "토글이 켜져 있는데 라벨이 안 나온다" 를 보게 됐다(꺼 둔 것은 라벨
            // 축이고 그것을 되돌릴 체크박스가 없었다).
            const labelDefs = [
                { key: 'site',      label: _t('Site') },
                { key: 'zone',      label: _t('Zone') },
                { key: 'facility',  label: _t('Facility') },
                { key: 'plot',      label: _t('Plot') },
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

        // Expose overlay/base setters so the settings modal can live-apply the
        // active_layers / selected_base_layer options — same primitives the layer
        // panel checkboxes above already drive (_setOverlayVisible /
        // _activateRasterBase / _deactivateRasterBase / _rehydrateFromCache), just
        // parameterized instead of reading a clicked checkbox. No network call here
        // (the caller already persisted the option); this only updates the running map.
        try {
            var _ovInst = window.AoTWidgetInstances[uniqueId];
            if (_ovInst) {
                _ovInst._setActiveOverlayNames = function (names) {
                    var want = (names || []).map(function (s) { return String(s).trim(); }).filter(Boolean);
                    geoLayers.forEach(function (l) {
                        if (l.role === 'base' || l.is_base) { return; }
                        var shouldShow = want.indexOf(l.name) !== -1;
                        var wasShown = activeOverlays.indexOf(l.name) !== -1;
                        if (shouldShow === wasShown) { return; }
                        if (shouldShow) {
                            activeOverlays.push(l.name);
                            if (!_dataOnly) { _setOverlayVisible(l, true); }
                        } else {
                            activeOverlays = activeOverlays.filter(function (n) { return n !== l.name; });
                            if (!_dataOnly) { _setOverlayVisible(l, false); }
                        }
                    });
                    var _lpInst = window.AoTWidgetInstances[uniqueId];
                    if (_lpInst && typeof _lpInst.refreshLegend === 'function') { _lpInst.refreshLegend(activeOverlays); }
                };
                _ovInst._switchBaseLayer = function (name) {
                    var l = geoLayers.find(function (x) { return (x.role === 'base' || x.is_base) && x.name === name; });
                    if (!l || name === activeBase) { return; }
                    activeBase = name;
                    _deactivateRasterBase();
                    if ((l.type || 'xyz') === 'vector' && l.url) {
                        try { map.setStyle(l.url, { diff: false }); } catch (e) {}
                        // setStyle({diff:false}) destroys all custom sources/layers — re-add after style loads
                        // (mirrors the layer-panel base-radio handler above).
                        map.once('style.load', function () {
                            var inst = window.AoTWidgetInstances[uniqueId];
                            if (inst) { inst.sources.clear(); inst.layers.clear(); }
                            map._aotBaseStyleIds = ((map.getStyle() || {}).layers || []).map(function (ly) { return ly.id; });
                            _rehydrateFromCache();
                            if (!_dataOnly) {
                                geoLayers.forEach(function (gl) {
                                    var isBase = gl.role === 'base' || gl.is_base;
                                    if (!isBase && activeOverlays.indexOf(gl.name) !== -1) { _setOverlayVisible(gl, true); }
                                });
                            }
                        });
                    } else {
                        _activateRasterBase(l);
                    }
                };
            }
        } catch (e) {}

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
                        if (!_isWidgetVisible(inst)) return;
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
                        // **위젯의 라벨 관리에 등록한다.** 이것이 없으면 줌
                        // 게이트·쌓임·충돌이 이 핀을 아예 못 본다 — 명부에 이름만
                        // 올려서는 아무 일도 일어나지 않는다(그 값을 읽는 요소가
                        // 없기 때문이다). 노트 핀이 그동안 그 밖에 있어서, 다른
                        // 라벨이 전부 접힌 축척에서도 혼자 남아 지도를 덮었다.
                        try {
                            _wireLabelStacking(
                                window.AoTWidgetInstances[uniqueId], el, 'note');
                        } catch (e) {}

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
            if (!_isWidgetVisible(instance)) return;
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
     * (Re)start the docked measurement panel's periodic poll, with a
     * visibilitychange catch-up — same pattern as setupRefresh: while the tab
     * is hidden the setInterval below no-ops every tick (document.hidden), so
     * a tab left in the background for hours would otherwise sit on a stale
     * value until its next natural tick after becoming visible again.
     */
    function _startPanelRefresh(instance, uniqueId, ms) {
        if (instance.panelRefreshTimer) clearInterval(instance.panelRefreshTimer);
        if (instance._panelRefreshVisHandler) {
            document.removeEventListener('visibilitychange', instance._panelRefreshVisHandler);
            instance._panelRefreshVisHandler = null;
        }
        var _lastTick = 0;
        function _tick() {
            _lastTick = Date.now();
            refreshMeasurementPanelValues(uniqueId);
        }
        instance.panelRefreshTimer = setInterval(function() {
            if (document.hidden) return;
            if (!_isWidgetVisible(instance)) return;
            _tick();
        }, ms);
        instance._panelRefreshVisHandler = function() {
            if (document.hidden) return;
            if (!_isWidgetVisible(instance)) return;
            if ((Date.now() - _lastTick) >= ms) _tick();
        };
        document.addEventListener('visibilitychange', instance._panelRefreshVisHandler);
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

        // The dock lives inside map.getContainer() (.maplibregl-map) but the
        // legend is appended to its PARENT (.aot-map-container). CSS custom
        // properties only inherit downward, so setting --aot-dock-h on the inner
        // element never reached the legend — it resolved to the 0px fallback and
        // the legend sat ON TOP of the dock. Set it on the nearest common
        // ancestor so dock, legend and the bottom-left corner all agree.
        const varHost = container.closest('.aot-map-container') || container;
        varHost.style.setProperty('--aot-dock-h', h + 'px');

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
        varHost.style.setProperty('--aot-dock-h-left', leftLift + 'px');

        // Dock visibility decides legend chip-vs-expanded mode — keep in sync
        if (typeof instance._syncLegendMode === 'function') instance._syncLegendMode();
    }

    // ── 시간 독(상단 중앙) ──────────────────────────────────────────────────
    // 지도 중심이 있는 곳의 현지 시각·일출·일몰. 지도가 세계 어디로든 가므로
    // "지금 몇 시인가"의 답은 화면이 어디를 보고 있느냐에 따라 바뀐다.
    //
    // 서버(/api/geo/local_time)는 **위치가 바뀔 때만** 부른다. 초당 갱신은
    // 브라우저가 tz 이름으로 직접 한다(createTimeDock.tick) — 시계를 서버
    // 폴링으로 만들면 지도 위젯 하나가 초당 요청 하나를 만든다.

    // 재조회 문턱. 이보다 덜 움직였으면 일출/일몰은 표시 분해능(분) 안에서
    // 같은 값이다 — 지도를 조금씩 미는 동안 서버를 두들기지 않게 한다.
    const _TIME_DOCK_REFETCH_KM = 2;
    // 자료가 낡았는데 조회가 계속 실패할 때의 재시도 간격(초당 재시도 방지).
    const _TIME_DOCK_STALE_COOLDOWN_MS = 30000;

    /** 두 좌표 사이 거리(km). 재조회할 만큼 움직였는지만 보므로 구면 근사로 충분하다. */
    function _kmBetween(a, b) {
        const R = 6371;
        const rad = Math.PI / 180;
        const dLat = (b.lat - a.lat) * rad;
        const dLng = (b.lng - a.lng) * rad;
        const h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                  Math.cos(a.lat * rad) * Math.cos(b.lat * rad) *
                  Math.sin(dLng / 2) * Math.sin(dLng / 2);
        return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
    }

    /**
     * Sync --aot-top-dock-h on the map container with the time dock's height.
     *
     * 상단 중앙은 원래 주소 검색바(.map-search-overlay)와 AI 조언 칩
     * (.aot-map-advice-chips)이 쓰던 자리다. 시간 독이 켜지면 그 둘이 독 높이만큼
     * 아래로 내려가야 하는데, 독 높이는 크기 손잡이로 사람이 바꾼다 — 그래서
     * 고정 상수가 아니라 실제 렌더 높이를 변수로 내보낸다(하단 --aot-dock-h 와
     * 같은 방식). 독이 꺼졌거나 xs 컴팩트 모드로 숨겨졌으면 0 이라 두 요소는
     * 원래 자리로 돌아간다.
     */
    function _updateTopDockHeightVar(uniqueId) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance || !instance.map) return;
        const container = instance.map.getContainer();
        if (!container) return;
        const panel = instance.timeDock && instance.timeDock.panel;
        const h = (panel && panel.offsetParent !== null) ? panel.offsetHeight : 0;
        // --aot-dock-h 와 같은 이유로 공통 조상에 건다: 독은 지도 컨테이너
        // 안이지만 검색바·조언 칩은 그 부모(.aot-map-container)의 자식이다.
        const varHost = container.closest('.aot-map-container') || container;
        varHost.style.setProperty('--aot-top-dock-h', h + 'px');
    }

    /** 시간 독과 그것이 건 타이머·관찰자·지도 이벤트를 전부 걷어낸다. */
    function _destroyTimeDock(uniqueId) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;
        if (instance._timeDockTimer) {
            clearInterval(instance._timeDockTimer);
            instance._timeDockTimer = null;
        }
        if (instance._timeDockVisHandler) {
            document.removeEventListener('visibilitychange', instance._timeDockVisHandler);
            instance._timeDockVisHandler = null;
        }
        if (instance._timeDockResizeObserver) {
            try { instance._timeDockResizeObserver.disconnect(); } catch (e) {}
            instance._timeDockResizeObserver = null;
        }
        if (instance._timeDockMoveTimer) {
            clearTimeout(instance._timeDockMoveTimer);
            instance._timeDockMoveTimer = null;
        }
        if (instance._timeDockMoveHandler && instance.map) {
            try { instance.map.off('moveend', instance._timeDockMoveHandler); } catch (e) {}
            instance._timeDockMoveHandler = null;
        }
        if (instance.timeDock) {
            try { instance.timeDock.destroy(); } catch (e) {}
            instance.timeDock = null;
        }
    }

    /**
     * Add the top-center time dock (custom option `show_local_time`).
     * 꺼져 있으면 아무것도 만들지 않고 --aot-top-dock-h 만 0 으로 되돌린다.
     */
    function addTimeDock(uniqueId, map, vars) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        // 설정 즉시반영으로 다시 불릴 수 있다 — 항상 이전 것을 먼저 걷어낸다.
        _destroyTimeDock(uniqueId);

        const innerVars = (vars && vars.vars) || {};
        const on = (innerVars.show_local_time === true || innerVars.show_local_time === 'true');
        if (!on) {
            _updateTopDockHeightVar(uniqueId);
            return;
        }
        if (!window.AoTMapCustomControls ||
            typeof window.AoTMapCustomControls.createTimeDock !== 'function') {
            return;
        }

        const widgetId = (vars && vars.widgetId) || uniqueId;

        // 시계 크기: 서버 옵션 우선, localStorage 는 폴백
        // (meas_panel_balance 와 같은 이중 보관 방식).
        const _lsScaleKey = 'aot_map_toggle_' + widgetId + '_time_dock_scale';
        let initScale = parseFloat(innerVars.time_dock_scale);
        if (!isFinite(initScale)) {
            try { initScale = parseFloat(localStorage.getItem(_lsScaleKey)); } catch (e) { initScale = NaN; }
        }
        if (!isFinite(initScale)) initScale = 1;

        // 휠은 다발로 들어온다 — localStorage 에는 즉시, 서버에는 멎은 뒤에 한 번.
        let _scaleSaveTimer = null;
        function _persistScale(s) {
            try { localStorage.setItem(_lsScaleKey, String(s)); } catch (e) {}
            if (_scaleSaveTimer) clearTimeout(_scaleSaveTimer);
            _scaleSaveTimer = setTimeout(function() {
                fetch('/save_widget_custom_options', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ widget_id: widgetId, options: { time_dock_scale: s } })
                }).catch(function() {});
            }, 600);
        }

        // 접힘 상태: 서버 옵션 우선, localStorage 는 폴백
        // (meas_dock_collapsed 와 같은 이중 보관 방식).
        const _lsColKey = 'aot_map_toggle_' + widgetId + '_time_dock_collapsed';
        let initCollapsed;
        const _sv = innerVars.time_dock_collapsed;
        if (_sv === true || _sv === 'true') initCollapsed = true;
        else if (_sv === false || _sv === 'false') initCollapsed = false;
        else {
            try { initCollapsed = localStorage.getItem(_lsColKey) === 'true'; } catch (e) { initCollapsed = false; }
        }

        const handle = window.AoTMapCustomControls.createTimeDock(map, {
            scale: initScale,
            collapsed: initCollapsed,
            locale: document.documentElement.lang || undefined,
            onScaleChange: function(s) {
                _persistScale(s);
                // 글자가 커지면 독도 커진다 — 검색바·조언 칩이 따라 내려가야 한다.
                _updateTopDockHeightVar(uniqueId);
            },
            onCollapsedChange: function(c) {
                try { localStorage.setItem(_lsColKey, c ? 'true' : 'false'); } catch (e) {}
                fetch('/save_widget_custom_options', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ widget_id: widgetId, options: { time_dock_collapsed: c } })
                }).catch(function() {});
                // 접으면 상단이 그만큼 비어 검색바·조언 칩이 올라와야 한다.
                _updateTopDockHeightVar(uniqueId);
            }
        });
        instance.timeDock = handle;

        let lastFetchCenter = null;
        let fetchInFlight = false;
        let lastStaleFetch = 0;

        function _fetchNow(force) {
            if (fetchInFlight) return;
            let c;
            try {
                c = map.getCenter();
                // 지구를 몇 바퀴 돌면 경도가 ±180 을 넘어간다 — 서버는 범위 밖을
                // 400 으로 되돌려 보내므로 여기서 접어 준다.
                if (c && typeof c.wrap === 'function') c = c.wrap();
            } catch (e) { return; }
            if (!c) return;
            const center = { lat: c.lat, lng: c.lng };
            if (!force && lastFetchCenter &&
                _kmBetween(lastFetchCenter, center) < _TIME_DOCK_REFETCH_KM) {
                return;
            }
            fetchInFlight = true;
            fetch('/api/geo/local_time?lat=' + encodeURIComponent(center.lat.toFixed(4)) +
                  '&lng=' + encodeURIComponent(center.lng.toFixed(4)))
                .then(function(res) { return res.ok ? res.json() : null; })
                .then(function(d) {
                    fetchInFlight = false;
                    if (!d || d.error) return;
                    lastFetchCenter = center;
                    handle.update(d);
                    _updateTopDockHeightVar(uniqueId);
                })
                .catch(function() { fetchInFlight = false; });
        }

        // 지도가 멎은 뒤에만 묻는다. 드래그하는 내내 중심이 바뀌므로 moveend
        // 자체도 연달아 오고, 그래서 한 번 더 디바운스한다.
        const _onMoveEnd = function() {
            if (instance._timeDockMoveTimer) clearTimeout(instance._timeDockMoveTimer);
            instance._timeDockMoveTimer = setTimeout(function() { _fetchNow(false); }, 600);
        };
        instance._timeDockMoveHandler = _onMoveEnd;
        try { map.on('moveend', _onMoveEnd); } catch (e) {}

        function _tick() {
            // 안 보이는 위젯의 시계는 멈춰 있어도 된다 — 다시 보일 때 아래
            // visibilitychange/스크롤 진입에서 한 번에 따라잡는다.
            if (document.hidden) return;
            if (!_isWidgetVisible(instance)) return;
            if (handle.tick()) {
                const t = Date.now();
                if (t - lastStaleFetch > _TIME_DOCK_STALE_COOLDOWN_MS) {
                    lastStaleFetch = t;
                    _fetchNow(true);
                }
            }
        }
        instance._timeDockTimer = setInterval(_tick, 1000);

        // 탭이 다시 보이면 즉시 따라잡는다(1초를 기다리지 않는다).
        instance._timeDockVisHandler = function() {
            if (document.hidden) return;
            _tick();
        };
        document.addEventListener('visibilitychange', instance._timeDockVisHandler);

        if (typeof ResizeObserver !== 'undefined' && handle.panel) {
            const ro = new ResizeObserver(function() { _updateTopDockHeightVar(uniqueId); });
            ro.observe(handle.panel);
            instance._timeDockResizeObserver = ro;
        }

        _fetchNow(true);
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
                // 도크가 접히면 그만큼 지도가 더 보인다 — 열린 모달이 있으면
                // 그 대상 기준으로 구도를 다시 잡는다.
                setTimeout(function () { _refitCurrentFocus(uniqueId); }, 220);
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
                // **도크 크기 변화로 카메라를 다시 맞추지 않는다.**
                //
                // 도크는 화면에 보이는 시설의 요약을 싣는다 — 즉 **카메라의 결과**다.
                // 그것을 다시 카메라의 입력으로 쓰면 고리가 닫힌다: 도착 → 시설이
                // 가장자리에 걸침 → 요약 행이 생겨 도크가 커짐 → 다시 맞춤 → 시설이
                // 화면 밖으로 → 요약이 사라져 도크가 줄어듦 → 다시 맞춤 … 실제로
                // 줌이 출렁이며 멈추지 않았다(크롬에서 재현).
                //
                // 도크 높이는 **카메라를 계산하는 그 순간의 값**만 쓴다. 나중에
                // 커져서 도형 아래를 조금 가릴 수는 있지만, 화면이 진동하는 것보다
                // 낫다. 사람이 한 행동(시트 펼치기 등)으로 인한 재조정은 그대로다.
                const dockRo = new ResizeObserver(function() {
                    _updateDockHeightVar(uniqueId);
                });
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
            _startPanelRefresh(instance, uniqueId, refreshMs);

            // Expose a live setter for input_update_interval (settings-modal live-apply):
            // restart the same polling loop above with the new period, no panel rebuild.
            instance._setPanelRefreshInterval = function (seconds) {
                var ms = Math.max(10, parseFloat(seconds) || 60) * 1000;
                _startPanelRefresh(instance, uniqueId, ms);
            };
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
    /**
     * Channels for a map-placed device, in facility /runtime shape.
     * Server now ships the band `key` on every measurement row
     * (facility_sensors.channel_label_meta) — without it no band color is possible.
     */
    function _deviceBaseId(dev) {
        return dev.device_id || dev.device_unique_id ||
            (dev.unique_id ? dev.unique_id.split('::')[0] : (dev.id || '').split('::')[0]);
    }

    function _deviceChannels(dev, wOpts, instance) {
        const targetMap = wOpts.all_measurements_map || wOpts.measurements_map || {};
        if (!window.AoTMapSensorLabels) return [];
        const channels = window.AoTMapSensorLabels.channelsFromMeasurements(
            targetMap[_deviceBaseId(dev)] || []);
        // /api/geo/devices 는 측정 **메타**만 준다(값 조회는 render 경로에서 뺐다 —
        // 페이지 렌더 중 센서당 InfluxDB 조회가 위젯 로드를 느리게 만들었다).
        // 값은 _refreshInputValues 가 /data_batch 로 따로 받아 여기 캐시에 넣는다.
        const cache = instance && instance._measValues;
        if (cache) {
            channels.forEach(function (c) {
                if (c.value == null && cache[c.measurement_id] != null) {
                    c.value = cache[c.measurement_id];
                }
            });
        }
        _markChannelFreshness(channels, instance);
        return channels;
    }

    // 장치 주기를 넘겨 늦은 값이면 channel.valid=false 로 표시한다.
    // 값을 지우지는 않는다 — 하루 한 번 재는 센서의 20시간 된 값은 정상이고,
    // 숨기면 사용자는 "센서가 죽었나" 로 읽는다. 렌더러(renderValueLabel)가
    // 이미 `valid` 가 있는 채널만 보고 .aot-stale 을 붙이므로, 여기서 플래그만
    // 세우면 시설 fitting 센서 라벨과 같은 표시 정책으로 자동 수렴한다.
    //
    // 판정은 반드시 **그 장치의 주기 대비**로 한다. 전역 상수로는 불가능하다 —
    // 300초 장치의 290초 값은 정상이고 하루 1회 장치의 20시간 값도 정상이다.
    // 주기나 관측 시각을 모르면 `valid` 를 아예 붙이지 않는다: 모르면서
    // "오래됨" 으로 그리면 정상 장치가 상시 흐리게 보인다(장주기 노드가 늘
    // stale 로 보이던 문제 — device_link_status.LINK_MAX_AGE_S 주석과 같은 교훈).
    //
    // 배수 2 = 표본 1회 유실까지는 정상으로 본다. 1배로 하면 데몬·전송 지터
    // 몇 초에도 매 주기 끝마다 깜빡인다.
    //
    // 다만 배수는 어디까지나 **추정**이다. 장치가 `max_age_s`(서버가 붙인다,
    // p6_55)를 갖고 있으면 그것이 이긴다 — 40분마다 깨는 LoRaWAN 노드는
    // 주기×2 로 재면 정상 동작 중에도 절반은 늦은 것으로 보인다. 미설정이면
    // null 이라 종전 판정 그대로다.
    const STALE_PERIOD_FACTOR = 2;

    function _markChannelFreshness(channels, instance) {
        const tsMap = instance && instance._measTs;
        if (!tsMap) return;
        const nowSec = Date.now() / 1000;
        channels.forEach(function (c) {
            const ts = tsMap[c.measurement_id];
            if (ts == null) return;
            const declared = parseFloat(c.max_age_s);
            const period = parseFloat(c.sample_period);
            let maxAge;
            if (isFinite(declared) && declared > 0) {
                maxAge = declared;
            } else if (isFinite(period) && period > 0) {
                maxAge = period * STALE_PERIOD_FACTOR;
            } else {
                // 둘 다 모르면 판정하지 않는다 — 모르면서 "오래됨" 으로
                // 그리면 정상 장치가 상시 흐리게 보인다.
                return;
            }
            c.valid = (nowSec - ts) <= maxAge;
        });
    }

    /**
     * Live values for Input markers, via the existing /data_batch coalescer
     * (one POST for every channel of every input on this map, instead of N GETs).
     * Repaints only the input markers — the output/3-way refresh path has motion
     * bookkeeping that must not run twice per tick.
     */
    const INPUT_VALUE_MIN_INTERVAL_MS = 30000;

    // ── 측정값 세션 캐시 ───────────────────────────────────────────────────────
    // 새로고침 직후 값 조회가 끝날 때까지 키가 "—" 로 남는 구간을 없앤다.
    // 저장 수명은 /data_batch 요청의 창 하한(600초)에 맞춘 값이다. 그 안의 값이면
    // 라이브 경로가 돌려줄 값과 같은 신선도이므로 낙관적으로 그려도 사용자가 보는
    // 정보의 성격이 달라지지 않는다. 창을 넘긴 캐시는 버리고 "—" 로 시작한다.
    // 주기가 600초보다 긴 장치는 서버가 창을 넓히므로 라이브 값이 이 TTL 보다
    // 오래된 경우가 있는데, 그건 캐시를 늘려 해결할 문제가 아니다 — 관측 시각
    // (_measTs)이 없는 캐시 값에는 신선도 플래그를 붙이지 않아, 흐리게 그려야
    // 할 값을 정상으로 오인하지 않는다.
    var MEASVAL_CACHE_TTL_MS = 600000;

    function _measValueCacheKey(uniqueId, wOpts) {
        var inst = window.AoTWidgetInstances[uniqueId];
        var vars = inst && inst.vars;
        return 'aot_map_measvals_' + ((vars && vars.widgetId) || uniqueId);
    }

    function _saveMeasValueCache(uniqueId, wOpts) {
        var inst = window.AoTWidgetInstances[uniqueId];
        if (!inst || !inst._measValues) return;
        try {
            sessionStorage.setItem(_measValueCacheKey(uniqueId, wOpts),
                JSON.stringify({ ts: Date.now(), v: inst._measValues }));
        } catch (e) { /* 용량 초과/프라이빗 모드 — 캐시는 있으면 좋은 것뿐 */ }
    }

    /** 캐시된 값을 인스턴스에 심는다(첫 렌더 전에 호출). 성공 시 true. */
    function _seedMeasValueCache(uniqueId, vars) {
        var inst = window.AoTWidgetInstances[uniqueId];
        if (!inst) return false;
        try {
            var raw = sessionStorage.getItem(_measValueCacheKey(uniqueId, null));
            if (!raw) return false;
            var c = JSON.parse(raw);
            if (!c || !c.v || !c.ts) return false;
            if (Date.now() - c.ts > MEASVAL_CACHE_TTL_MS) {
                sessionStorage.removeItem(_measValueCacheKey(uniqueId, null));
                return false;
            }
            inst._measValues = Object.assign({}, c.v, inst._measValues || {});
            return true;
        } catch (e) { return false; }
    }

    // 라벨이 대표값으로 고를 만한 채널을 앞으로 보내는 우선순위.
    // 밴드 색이 정의된 환경값이 먼저고, 그중에서도 온도가 가장 자주 살아 있다.
    var _VALUE_KEY_PRIORITY = ['T', 'RH', 'VPD', 'CO2', 'light', 'P', 'wind_ms', 'wind_deg'];

    function _isMetaKey(key) {
        return !!(window.AoTSensorLabel && window.AoTSensorLabel.isMetaChannel &&
                  window.AoTSensorLabel.isMetaChannel({ key: key }));
    }

    /**
     * 한 장치에서 값 조회 대상 채널을, 라벨이 고를 법한 순서로 정렬해 돌려준다.
     * 메타 채널(rssi/snr/battery)은 제외 — renderValueLabel 이 라벨에서 이미
     * 빼는데도 예전에는 조회는 하고 있었다(전체 107채널 중 39개가 이것이었다).
     */
    function _valueChannelsFor(rows) {
        return (rows || [])
            .filter(function (m) { return m && m.id && !_isMetaKey(m.key); })
            .slice()
            .sort(function (x, y) {
                var ix = _VALUE_KEY_PRIORITY.indexOf(x.key);
                var iy = _VALUE_KEY_PRIORITY.indexOf(y.key);
                return (ix < 0 ? 99 : ix) - (iy < 0 ? 99 : iy);
            });
    }

    /** 라벨이 실제로 표시하는 채널 수 (circle 은 대표값 1개). */
    function _neededChannelCount(sOpts) {
        if (sOpts.style === 'circle') return 1;
        var n = parseInt(sOpts.max_channels, 10);
        return (isNaN(n) || n < 1) ? 1 : n;
    }

    // period 는 조회 창의 **하한**이다. 서버(_effective_lookback, routes_general.py)가
    // 이 장치의 샘플링 주기를 보고 필요하면 넓힌다 — 하루 한 번 재는 센서까지
    // 잡으려고 여기서 큰 값을 박으면, 15초 장치의 스캔 범위까지 같이 커진다.
    function _batchItem(baseId, mid) {
        return { kind: 'last', unique_id: baseId, measure_type: 'input',
                 measurement_id: mid, period: '600' };
    }

    function _postDataBatch(items) {
        var trimmed = items.slice(0, 300);
        // 공유 코얼레서를 지난다 — 같은 지도를 보는 지도 위젯이 여럿이면 항목이
        // 거의 겹치는데, 각자 POST 하면 그 수만큼 왕복이 늘어난다(실측 3회).
        // 모듈이 없으면(레이아웃이 안 실은 페이지) 예전처럼 직접 보낸다.
        if (window.AoTDataBatch && window.AoTDataBatch.postItems) {
            return window.AoTDataBatch.postItems(trimmed);
        }
        return fetch('/data_batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrfMeta() },
            body: JSON.stringify({ items: trimmed })
        })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (j) { return (j && Array.isArray(j.results)) ? j.results : null; });
    }

    /**
     * Live values for Input markers.
     *
     * 라벨이 **표시하는 채널만** 조회한다. 예전에는 장치의 전 채널을 받았는데,
     * 실측(입력 15대)에서 107채널 970ms 였고 그중 라벨이 쓰는 것은 15개(125ms)
     * 뿐이었다. 비용은 항목 수에 완전 선형이다(/data_batch 는 측정 1건당 InfluxDB
     * LAST 쿼리 1건, 8워커) — 즉 안 쓰는 채널을 빼는 것이 곧 그만큼의 단축이다.
     *
     * 대표 채널에 값이 없을 수 있으므로(전 채널을 받던 시절에는 다음 채널로
     * 자연히 넘어갔다) 빈손으로 돌아온 장치에 한해 나머지 채널로 2차 조회한다.
     * 흔한 경우엔 1차로 끝나고, 아닌 경우에도 예전처럼 값이 채워진다.
     */
    function _refreshInputValues(uniqueId, devices, wOpts) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance || !window.AoTMapSensorLabels) return;
        // 장치 폴링 주기(period, 최소 5초)와 무관하게 측정값은 30초 이상 간격으로만
        // 조회한다 — 시설 센서 라벨 폴러(refresh_seconds 최소 30초)와 같은 정책이고,
        // 매 틱마다 InfluxDB 배치 조회를 돌리면 저사양 호스트에서 낭비가 크다.
        const now = Date.now();
        if (instance._measValuesTs && (now - instance._measValuesTs) < INPUT_VALUE_MIN_INTERVAL_MS) return;
        instance._measValuesTs = now;

        const targetMap = wOpts.all_measurements_map || wOpts.measurements_map || {};
        const need = _neededChannelCount(_sensorLabelOptsFrom(wOpts));
        const items = [];       // 1차: 장치당 대표 채널
        const spare = {};       // baseId -> 남은 채널(2차 후보)
        const seen = {};
        devices.forEach(function (dev) {
            if ((dev.device_type || dev.type) !== 'input') return;
            const baseId = _deviceBaseId(dev);
            if (seen[baseId]) return;
            seen[baseId] = true;
            const ch = _valueChannelsFor(targetMap[baseId]);
            ch.slice(0, need).forEach(function (m) { items.push(_batchItem(baseId, m.id)); });
            const rest = ch.slice(need);
            if (rest.length) spare[baseId] = rest;
        });
        if (!items.length) return;

        function absorb(results, sent) {
            const inst = window.AoTWidgetInstances[uniqueId];
            if (!inst || !results) return null;
            inst._measValues = inst._measValues || {};
            // 관측 시각도 함께 남긴다(payload 는 [epoch초, 값]). 예전엔 res[0] 을
            // 버려서, 값이 방금 것인지 어제 것인지 화면이 구분할 수 없었다 —
            // 조회 창을 장치 주기만큼 넓힌 뒤에는 그 구분이 꼭 필요하다.
            inst._measTs = inst._measTs || {};
            const gotByDevice = {};
            results.forEach(function (res, i) {
                const it = sent[i];
                if (Array.isArray(res) && res[1] != null && !isNaN(+res[1])) {
                    inst._measValues[it.measurement_id] = +res[1];
                    if (res[0] != null && !isNaN(+res[0])) {
                        inst._measTs[it.measurement_id] = +res[0];
                    }
                    gotByDevice[it.unique_id] = true;
                }
            });
            return gotByDevice;
        }

        _postDataBatch(items)
            .then(function (results) {
                const got = absorb(results, items);
                if (!got) return;
                _repaintInputMarkers(uniqueId, devices, wOpts);
                _saveMeasValueCache(uniqueId, wOpts);

                // 2차: 대표 채널이 비어 있던 장치만 나머지 채널로 재시도.
                const retry = [];
                Object.keys(spare).forEach(function (baseId) {
                    if (got[baseId]) return;
                    spare[baseId].forEach(function (m) { retry.push(_batchItem(baseId, m.id)); });
                });
                if (!retry.length) return;
                return _postDataBatch(retry).then(function (r2) {
                    if (!absorb(r2, retry)) return;
                    _repaintInputMarkers(uniqueId, devices, wOpts);
                    _saveMeasValueCache(uniqueId, wOpts);
                });
            })
            .catch(function () {});
    }

    function _repaintInputMarkers(uniqueId, devices, wOpts) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance || !window.AoTMapSensorLabels ||
            !window.AoTMapSensorLabels.renderValueLabel) return;
        const sOpts = _sensorLabelOptsFrom(wOpts);
        devices.forEach(function (dev) {
            if ((dev.device_type || dev.type) !== 'input') return;
            const marker = instance.markers.get(dev.unique_id || dev.id);
            if (!marker || typeof marker.getElement !== 'function') return;
            const el = marker.getElement();
            if (!el || !el.classList.contains('aot-sensor-map-marker')) return;
            window.AoTMapSensorLabels.renderValueLabel(
                el, _deviceChannels(dev, wOpts, instance), null, sOpts,
                _deviceDisplayName(dev));
        });
    }

    /**
     * 툴팁의 전 채널 목록을 hover 시 채운다.
     *
     * 라벨은 대표 채널만 조회하므로(_refreshInputValues) circle 마커의 툴팁도
     * 그 한 개만 담기게 된다. 예전에는 전 채널이 나왔고 그게 이 마커의 쓸모
     * 중 하나였다 — 그래서 "필요할 때만" 되살린다: 한 장치를 처음 가리켰을 때
     * 그 장치의 나머지 채널만 한 번 받아오고, 이후로는 캐시로 답한다.
     * 첫 화면 로딩 비용은 그대로 두면서 정보는 잃지 않는다.
     */
    function _hydrateTooltip(uniqueId, dev, wOpts) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;
        const baseId = _deviceBaseId(dev);
        instance._tipHydrated = instance._tipHydrated || {};
        if (instance._tipHydrated[baseId]) return;
        instance._tipHydrated[baseId] = true;   // 재진입 방지 (성공/실패 무관, 1회만)

        const targetMap = wOpts.all_measurements_map || wOpts.measurements_map || {};
        const missing = _valueChannelsFor(targetMap[baseId]).filter(function (m) {
            return !(instance._measValues && instance._measValues[m.id] != null);
        });
        if (!missing.length) return;

        _postDataBatch(missing.map(function (m) { return _batchItem(baseId, m.id); }))
            .then(function (results) {
                const inst = window.AoTWidgetInstances[uniqueId];
                if (!inst || !results) return;
                inst._measValues = inst._measValues || {};
                results.forEach(function (res, i) {
                    if (Array.isArray(res) && res[1] != null && !isNaN(+res[1])) {
                        inst._measValues[missing[i].id] = +res[1];
                    }
                });
                _repaintInputMarkers(uniqueId, [dev], wOpts);
                _saveMeasValueCache(uniqueId, wOpts);
            })
            .catch(function () {});
    }

    /**
     * Re-style the zone/bare-map Input value markers in place (no data needed).
     * Used by the settings live-apply path when a sensor-label option that only
     * affects presentation changes — 'Label Text Size' above all. Text/colour
     * come from the next value poll; this only fixes the styling that was
     * stamped at creation time.
     */
    function _restyleInputSensorMarkers(uniqueId, sOpts) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance || !instance.markers) return;
        instance.markers.forEach(function (m) {
            if (!m || typeof m.getElement !== 'function') return;
            const el = m.getElement();
            if (!el || !el.classList.contains('aot-sensor-map-marker')) return;
            if (el.dataset.deviceType !== 'input') return;
            if (sOpts.size_em != null) el.style.fontSize = sOpts.size_em + 'em';
            if (sOpts.opacity != null) el.style.opacity  = sOpts.opacity;
            el.classList.toggle('aot-sensor-map-marker--circle', sOpts.style === 'circle');
        });
    }

    // layout.html 의 <meta name="csrf-token"> — routes_general 은 CSRF 보호가 켜져 있다.
    function _csrfMeta() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return (meta && meta.getAttribute('content')) || '';
    }

    function _deviceDisplayName(dev) {
        return (dev.device_name || dev.name ||
            (dev.unique_id || dev.id || '').toString().split('::')[0] || '').toString().trim();
    }

    /**
     * Marker for an Input placed outside a facility (zone / bare map).
     *
     * Deliberately mirrors aot-map-sensor-labels.attach(): same element class,
     * same styling knobs, same renderer, and the click opens the same shared
     * sensor modal (createDevicePopup already returns a proxy onto
     * AoTSensorLabel.openPopup for inputs). Visibility follows the sensor-label
     * option (show_sensor_labels → master "Show Labels"), like facility sensors —
     * `show_device_labels` governs output/function pills, not measurement values.
     */
    function _addInputSensorMarker(uniqueId, map, instance, dev, popup, sOpts, wOpts) {
        const devLat = dev.lat || dev.latitude;
        const devLng = dev.lng || dev.longitude;
        const displayName = _deviceDisplayName(dev);

        const el = document.createElement('div');
        el.className = 'aot-sensor-map-marker' +
            (sOpts.style === 'circle' ? ' aot-sensor-map-marker--circle' : '');
        el.dataset.deviceType = 'input';
        el.dataset.labelName = displayName;
        // 글자 크기·투명도는 renderValueLabel 이 매번 적용한다(옵션 변경 시
        // 이미 그려진 마커도 따라가도록) — 여기서 중복으로 찍지 않는다.
        // Persisted per-type hide state (Layers → Labels → Input)
        if (instance._hiddenTypes && instance._hiddenTypes.input) {
            el.classList.add('aot-type-hidden');
        }

        // 시설 밖 Input 은 소속 시설이 없으므로 밴드 구간은 기본값(DEFAULT_RANGES).
        window.AoTMapSensorLabels.renderValueLabel(
            el, _deviceChannels(dev, wOpts, instance), null, sOpts, displayName);

        const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
            .setLngLat([parseFloat(devLng), parseFloat(devLat)])
            .addTo(map);

        // 공용 z-order + "고른 키를 앞으로" — 다른 라벨과 같은 규칙(LABEL_Z.input).
        const _restoreKeyZ = _wireLabelStacking(instance, el, 'input');
        // 툴팁 전 채널은 처음 가리켰을 때만 받아온다(첫 로딩 비용에 포함하지 않는다).
        el.addEventListener('mouseenter', function () {
            _hydrateTooltip(uniqueId, dev, wOpts);
        });
        popup.on('close', function () { instance._unpinLabel(el); });
        if (sOpts.popup !== false) {
            el.style.cursor = 'pointer';
            el.addEventListener('click', function (e) {
                e.stopPropagation();
                instance._pinLabelToFront(el, _restoreKeyZ);
                popup.setLngLat([parseFloat(devLng), parseFloat(devLat)]).addTo(map);
            });
        }

        instance.markers.set(dev.unique_id || dev.id, marker);
        instance.markers.set('__popup__' + (dev.unique_id || dev.id),
                             { remove: function () { popup.remove(); } });
        instance.deviceLabelMarkers.push(marker);
    }

    function addDeviceMarkers(uniqueId, map, devices, theme, vars) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        const wOpts = (vars && vars.vars) || {};
        const showDeviceLabels = wOpts.show_device_labels === true || wOpts.show_device_labels === 'true';
        const globalLabelSize = parseFloat(wOpts.global_label_size) || 1.0;
        const labelCollision   = wOpts.enable_label_collision !== false && wOpts.enable_label_collision !== 'false';
        const _rawSpacingD     = parseInt(wOpts.label_spacing);
        const labelSpacing     = (!isNaN(_rawSpacingD) && wOpts.label_spacing !== '' && wOpts.label_spacing !== null && wOpts.label_spacing !== undefined) ? _rawSpacingD : 0;

        // No client-side re-filtering here: `devices` was already fetched from
        // /api/geo/devices, which applies the Device Filter's EXCLUDE list
        // server-side (utils_geo.collect_devices). Re-checking wOpts.device_ids
        // against it here would treat an exclude list as an include whitelist
        // and hide almost everything.

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
        // (loadGeoDesignLabels runs before this, so it can't do this itself).
        // 같은 이유로 z-order 도 여기서 정정한다 — loadGeoDesignLabels 는 장치 이름
        // 라벨을 만들 때 그 장치가 output/input/function 중 무엇인지 아직 모른다.
        var _hiddenTypes = instance._hiddenTypes || {};
        (instance.geoDeviceLabelMarkers || []).forEach(function(marker) {
            if (!marker || typeof marker.getElement !== 'function') return;
            var el = marker.getElement();
            if (!el) return;
            var parentId = el.dataset.parentId || '';
            var devType = instance._deviceTypeMap[parentId];
            if (!devType) return;
            el.classList.toggle('aot-type-hidden', !!_hiddenTypes[devType]);
            if (LABEL_Z[devType] != null) _setLabelBaseZ(instance, el, devType);
        });

        // Input(센서) 라벨 옵션 — 시설 fitting 센서와 **같은** 설정을 읽는다.
        const sensorOpts = _sensorLabelOptsFrom(wOpts);

        devices.forEach(function(dev) {
            const devLat = dev.lat || dev.latitude;
            const devLng = dev.lng || dev.longitude;
            if (!devLat || !devLng) return;

            // [3-way Actuator] Initial render: always off-style. Motion (detected from
            // position changes between polls or commandActuator calls) flips it to ON.
            const isON = (dev.control_kind === 'value_3way')
                ? false
                : (dev.status === 'active' || dev.status === 'on' ||
                   dev.is_activated === true || dev.is_activated === 'true');

            const devType2 = dev.device_type || dev.type || '';
            const userColor = getUnifiedDeviceColor(devType2, dev, theme);

            const popup = createDevicePopup(uniqueId, dev, wOpts);

            // ── Input: 시설 배치 센서와 동일한 라벨/키 ─────────────────────────
            // 예전에는 "이름 + 첫 측정값 원본 + 장치 색" pill 이라, 같은 Input 도
            // 시설 안에 있으면 밴드 색·다채널 포맷·circle/text 스타일을 따르고
            // 구역/맨지도에 있으면 안 따랐다. 이제 두 경로 모두
            // AoTMapSensorLabels.renderValueLabel 하나를 쓴다.
            // 라벨이 꺼진 상태(showDeviceLabels=false)는 종전대로 점 마커 —
            // 값 라벨을 없앨 뿐 장치의 존재 표시까지 지우면 안 된다.
            if (devType2 === 'input' && showDeviceLabels && sensorOpts.show &&
                window.AoTMapSensorLabels && window.AoTMapSensorLabels.renderValueLabel) {
                _addInputSensorMarker(uniqueId, map, instance, dev, popup, sensorOpts, wOpts);
                return;
            }

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
                // 임시 표시(focus)가 uuid 로 찾는다 — 켜져 있는 출력은 라벨을
                // 꺼 두었어도 보여야 한다. 도형과 라벨의 식별자가 다를 수 있어
                // (도형=shape_uuid) 둘 다 새긴다.
                el.dataset.deviceId = String(dev.device_id || dev.unique_id || '');
                if (dev.shape_uuid) el.dataset.shapeUuid = String(dev.shape_uuid);
                el.innerHTML = labelHtml;
                // Apply persisted hide state immediately on creation
                if (instance._hiddenTypes && instance._hiddenTypes[devType2]) {
                    el.classList.add('aot-type-hidden');
                }

                const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
                    .setLngLat([parseFloat(devLng), parseFloat(devLat)])
                    .addTo(map);

                // 공용 z-order + "고른 라벨을 앞으로" — geo-design 라벨과 같은 규칙.
                var _restorePillZ = _wireLabelStacking(instance, el, devType2);
                popup.on('close', function () { instance._unpinLabel(el); });

                el.addEventListener('click', function(e) {
                    e.stopPropagation();
                    if (popup.isOpen()) {
                        popup.remove(); // fires 'close' above -> unpins
                    } else {
                        instance._pinLabelToFront(el, _restorePillZ);
                        popup.setLngLat([parseFloat(devLng), parseFloat(devLat)]).addTo(map);
                    }
                });

                instance.markers.set(dev.unique_id || dev.id, marker);
                instance.markers.set('__popup__' + (dev.unique_id || dev.id), { remove: function() { popup.remove(); } });
                instance.deviceLabelMarkers.push(marker);

            } else {
                // Dot style (show_device_labels = false, default)
                const el = document.createElement('div');
                el.className = 'map-marker-dot' + (isON ? ' device-on' : '');
                el.dataset.deviceType = devType2;
                el.dataset.deviceId = String(dev.device_id || dev.unique_id || '');
                if (dev.shape_uuid) el.dataset.shapeUuid = String(dev.shape_uuid);
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

                // 점 마커도 같은 규칙을 따른다. 예전엔 z-index 자체가 없어(auto)
                // 겹치면 DOM 순서대로 쌓였고, 아래 깔린 점은 클릭조차 못 했다.
                var _restoreDotZ = _wireLabelStacking(instance, el, devType2);
                popup.on('close', function () { instance._unpinLabel(el); });

                el.addEventListener('click', function(e) {
                    e.stopPropagation();
                    if (popup.isOpen()) { popup.remove(); }
                    else {
                        instance._pinLabelToFront(el, _restoreDotZ);
                        popup.setLngLat([parseFloat(devLng), parseFloat(devLat)]).addTo(map);
                    }
                });

                instance.markers.set(dev.unique_id || dev.id, marker);
                instance.markers.set('__popup__' + (dev.unique_id || dev.id), { remove: function() { popup.remove(); } });
            }
        });

        // Device label collision — joins unified handler (all groups run together in priority order).
        // showDeviceLabels 를 조건에서 뺀 이유: Input 값 라벨은 이제 device-label
        // 옵션이 아니라 센서 라벨 옵션을 따르므로, 장치 pill 이 꺼져 있어도
        // deviceLabelMarkers 에 들어간다. 예전 조건이면 그 경우 충돌 회피가
        // 통째로 꺼져 라벨이 서로 겹친 채 남는다.
        if (labelCollision && instance.deviceLabelMarkers.length > 0) {
            instance._labelSpacing = labelSpacing;
            _updateUnifiedCollisionHandler(instance, map, labelSpacing);
            // Single settled reveal pass (see note in loadGeoDesignLabels) — avoids the
            // rAF-vs-idle disagreement that flickered boundary input labels.
            _revealLabelsOnce(instance, map, labelSpacing);
        }

        // Sync device shape opacity with initial on/off state
        _updateDeviceShapeOpacity(instance, devices);

        // Input 라벨의 실제 측정값 채우기 (메타만 오는 /api/geo/devices 보완)
        try { _refreshInputValues(uniqueId, devices, wOpts); } catch (e) {}
    }

    function hexToRgba(hex, alpha) {
        if (!hex) return 'rgba(0,0,0,' + alpha + ')';
        const r = parseInt(hex.slice(1, 3), 16) || 0;
        const g = parseInt(hex.slice(3, 5), 16) || 0;
        const b = parseInt(hex.slice(5, 7), 16) || 0;
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    // Color priority: theme (type-specific → device common) → per-device override.
    // 종류별 테마 해석은 AoTGeoTheme 하나로 모았다 — 도형은 device_type 별 색을
    // 쓰는데 마커만 다른 폴백 체인을 타서(function 이 theme.device 로, 도형은
    // '#28a745' 로) 같은 장치의 도형과 마커 색이 어긋나던 문제를 없앤다.
    function getUnifiedDeviceColor(type, dev, theme) {
        var t = theme || {};
        if (window.AoTGeoTheme.normalizeDeviceType(type) || t.device) {
            return window.AoTGeoTheme.deviceColor(type, t);
        }
        if (dev && dev.label_color) return dev.label_color;
        var bc = dev && (dev.color || dev.marker_color);
        if (bc && bc.trim()) return bc.trim();
        return window.AoTGeoTheme.deviceColor(type, t);
    }

    /**
     * Create device popup (MapLibre) — exact port of v3 bindDevicePopup.
     * Returns { popup, onOpen } where onOpen must be called after marker.setPopup(popup).addTo(map).
     */
    /**
     * 입력(센서) 모달 제목줄에 **상위로 가는 ← 버튼**을 붙인다.
     *
     * 다른 모달은 `AoTMapPopup.buildModalHeader` 가 이 버튼을 함께 그리는데,
     * 입력은 공용 센서 컴포넌트가 자기 제목줄을 만들어서 **혼자 버튼이 없었다.**
     * 마크업만 같은 자리에 끼워 넣으면 정렬(제목줄이 이미 flex 중앙)과 배선
     * (`_wireUpBtn`)이 그대로 따라온다.
     */
    function _addSensorModalUpButton(uniqueId, deviceUuid, channel) {
        try {
            var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uniqueId];
            if (!inst || typeof inst._wireSensorModalUp !== 'function') return;
            var hdr = document.querySelector(
                '.aot-sensor-popup--docked > .aot-sensor-popup-header, ' +
                '.aot-sensor-popup--modal > .aot-sensor-popup-header');
            if (!hdr) return;
            var btn = hdr.querySelector('.aot-modal-up');
            if (!btn) {
                btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'aot-modal-up';
                // 같은 아이콘을 쓴다 — 여기만 글리프로 두면 센서 모달의
                // 화살표만 다른 모양이 된다.
                btn.innerHTML = (window.AoTMapPopup && window.AoTMapPopup.upIconHtml)
                    ? window.AoTMapPopup.upIconHtml() : '\u2190';
                btn.hidden = true;          // 상위를 알아낸 뒤 _wireUpBtn 이 편다
                hdr.insertBefore(btn, hdr.firstChild);
            }
            inst._wireSensorModalUp(hdr, deviceUuid, channel, function () {
                if (window.AoTSensorLabel && window.AoTSensorLabel.closePopup) {
                    window.AoTSensorLabel.closePopup();
                }
            });
        } catch (e) {}
    }

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

        const targetMap = (wOpts && (wOpts.all_measurements_map || wOpts.measurements_map)) || {};
        const devMeas = targetMap[uniqueKey] || [];

        // ----- Input device → shared facility sensor modal -----
        // Input devices open the SAME modal component as facility fitting sensors
        // (AoTSensorLabel.openPopup): identical chrome, 24h chart, and legend — one
        // popup component, not a map popup with facility content embedded. Returns a
        // lightweight proxy implementing the MapLibre Popup interface that the marker
        // click handlers use, but driving the shared modal instead.
        if (isInput) {
            // 채널 정규화는 라벨과 **같은** 함수를 쓴다. 예전에는 여기서만
            // key 를 meas_name(번역된 표시명)으로 채웠는데, 그러면 차트가 key 로
            // y축을 묶을 때 풍속과 풍향이 둘 다 'Wind' 라는 이유로 한 축에 겹쳤고
            // 레전드 이름도 라벨 쪽과 달랐다.
            const sensorObj = {
                name: displayName,
                fitting_id: uniqueKey,
                device_id: uniqueKey,
                channels: (window.AoTMapSensorLabels &&
                           window.AoTMapSensorLabels.channelsFromMeasurements)
                    ? window.AoTMapSensorLabels.channelsFromMeasurements(devMeas)
                    : []
            };
            // 'close' 리스너 — 마커의 "앞으로 고정"을 모달이 닫힐 때 풀기 위해
            // maplibregl.Popup 과 같은 on('close', fn) 계약을 흉내낸다.
            const _closeFns = [];
            return {
                // Click always (re)opens the modal — same UX as facility sensor labels.
                isOpen: function() { return false; },
                setLngLat: function() { return this; },
                addTo: function() {
                    if (window.AoTSensorLabel && window.AoTSensorLabel.openPopup) {
                        // Communication status (io_link_health_infra_plan.md) — /inputstate
                        // returns every Input in one bulk call (same 3s-cached endpoint the
                        // Input list page polls), so a single marker click just reads its
                        // own key out rather than adding a per-device RPC. Mirrors the
                        // Output popup's fetch('/outputstate_unique_id/...') pattern above,
                        // just against the bulk Input endpoint since there is no per-device one.
                        fetch('/inputstate')
                            .then(function(r) { return r.ok ? r.json() : {}; })
                            .catch(function() { return {}; })
                            .then(function(states) {
                                var st = (states && states[uniqueKey]) || {};
                                sensorObj.comm_fault = !!st.comm_fault;
                                window.AoTSensorLabel.openPopup(sensorObj, {
                                    modal: true,
                                    // 지도의 다른 창들과 **같은 셸**을 쓴다 —
                                    // 폭이 넉넉하면 오른쪽 도킹, 좁으면 하단 시트.
                                    // 이걸 안 주면 컴포넌트가 자기 중앙 오버레이를
                                    // 띄워 입력만 옛 방식으로 남는다.
                                    shell: _showFacilityCenterOverlay,
                                    shellUid: uniqueId,
                                    // Input 모달만 그래프를 낮춘다(요청) — 시설 bay
                                    // 팝업은 이 옵션을 안 주므로 공용 기본값(1.5)을
                                    // 그대로 쓴다. 1.125 = 285px → 214px, 25% 감소.
                                    heightScale: 1.125,
                                    note: { targetId: uniqueKey, targetType: 'device', name: displayName },
                                    onClose: function () {
                                        _clearHighlight(uniqueId);
                                        _closeFns.forEach(function (fn) { try { fn(); } catch (e) {} });
                                    }
                                });
                                // **패널이 열린 뒤에** 옮긴다. 그 전에 부르면
                                // 가려질 폭을 아직 몰라 위젯 한가운데를 기준으로
                                // 잡고, 그러면 장치가 패널 뒤로 밀린다 —
                                // 다른 모달들이 전부 셸을 연 뒤에 부르는 이유다.
                                _focusMapOn(uniqueId, uniqueKey);
                                _addSensorModalUpButton(uniqueId, uniqueKey, channel);
                            });
                    }
                    return this;
                },
                remove: function() {
                    _clearHighlight(uniqueId);
                    if (window.AoTSensorLabel && window.AoTSensorLabel.closePopup) window.AoTSensorLabel.closePopup();
                    return this;
                },
                on: function(evt, fn) {
                    if (evt === 'close' && typeof fn === 'function') _closeFns.push(fn);
                    return this;
                },
                getElement: function() { return null; }
            };
        }

        // ----- Output / Function / 복합장치 / 3-way → 중앙 모달 -----
        //
        // 예전에는 이것들만 지도에 붙는 소형 팝업이었다. Input 은 모달, 구역·
        // 시설도 모달인데 출력만 팝업이라 같은 지도 위에서 두 가지 창이 섞였고,
        // 팝업은 높이 제약(anchor 계산) 때문에 이력·소속·채널을 담을 수도
        // 없었다. 이제 전 계층이 같은 중앙 모달을 쓴다.
        //
        // Input 분기와 같은 방식으로, 마커 클릭 핸들러가 기대하는
        // maplibregl.Popup 계약만 흉내 내는 얇은 프록시를 돌려준다.
        if (!isInput) {
            const _devCloseFns = [];
            return {
                isOpen: function () { return false; },
                setLngLat: function () { return this; },
                addTo: function () {
                    if (_deviceModalOpener) {
                        _deviceModalOpener(uniqueId, uniqueKey, channel, displayName,
                                           function () {
                                               _devCloseFns.forEach(function (fn) {
                                                   try { fn(); } catch (e) {}
                                               });
                                           });
                    }
                    return this;
                },
                remove: function () { return this; },
                on: function (evt, fn) {
                    if (evt === 'close' && typeof fn === 'function') _devCloseFns.push(fn);
                    return this;
                },
                getElement: function () { return null; }
            };
        }

        // 여기 있던 소형 팝업 구성(HTML·스톱워치·예약 버튼·노트 미리보기)은
        // 위 프록시가 중앙 모달로 보내면서 도달하지 않는 코드가 됐다. 남겨 두면
        // "출력은 팝업"이라는 옛 모델이 코드에 계속 살아 있는 것처럼 읽힌다.
        // 작동 시간·예약·노트는 모두 장치 모달이 대신 보여준다.
    }

    /**
     * Shared /api/geo/devices fetcher.
     * Multiple map widgets on one dashboard poll with identical params —
     * calls within the TTL window share a single network request instead of
     * each widget issuing its own.
     */
    const _geoDevicesCache = {};  // paramsString -> { ts, promise }
    const _geoDevicesEtag = {};   // paramsString -> { etag, data }
    const GEO_DEVICES_SHARE_TTL_MS = 5000;

    /**
     * @param {string} paramsString
     * @param {{skipIfUnchanged?: boolean}} [opts]
     *   skipIfUnchanged=true 면 서버가 304(변화 없음)를 준 경우 **null** 을 돌려준다.
     *   주기 갱신 경로 전용이다 — 최초 렌더 경로에서 쓰면 마커가 안 그려진다.
     */
    function fetchGeoDevicesShared(paramsString, opts) {
        const now = Date.now();
        let entry = _geoDevicesCache[paramsString];
        if (!entry || (now - entry.ts) >= GEO_DEVICES_SHARE_TTL_MS) {
            const prev = _geoDevicesEtag[paramsString];
            const headers = {};
            if (prev && prev.etag) headers['If-None-Match'] = prev.etag;
            // cache:'no-store' — 브라우저 HTTP 캐시가 우리 조건부 요청을 가로채면
            // 304 가 여기까지 올라오지 않고 200(캐시본)으로 둔갑한다. 그러면 본문을
            // 다시 파싱하게 되어 아끼려던 것을 그대로 쓴다.
            const promise = fetch('/api/geo/devices?' + paramsString, {
                    credentials: 'same-origin',
                    cache: 'no-store',
                    headers: headers
                })
                .then(function(r) {
                    if (r.status === 304 && prev) {
                        return { data: prev.data, unchanged: true };
                    }
                    if (!r.ok) throw new Error('geo/devices HTTP ' + r.status);
                    const tag = r.headers.get('ETag');
                    return r.json().then(function(data) {
                        _geoDevicesEtag[paramsString] = { etag: tag, data: data };
                        return { data: data, unchanged: false };
                    });
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
        return entry.promise.then(function(res) {
            // 변화가 없고 호출자가 건너뛰기를 원하면 복제조차 하지 않는다 —
            // 125KB 객체 그래프 복제도 5초마다면 공짜가 아니다.
            if (res.unchanged && opts && opts.skipIfUnchanged) return null;
            try { return structuredClone(res.data); } catch (e) { return res.data; }
        });
    }

    /**
     * A widget can be on a hidden dashboard tab while its timers keep firing.
     * offsetParent is null when the container (or an ancestor) is display:none.
     */
    // 예전에는 offsetParent 만 봤다 — 그건 display:none 검사이지 "화면에 보이는가"
    // 가 아니다. 폰에서 대시보드는 세로로 길어(실측 3,550px) 스크롤로 밀려난 지도도
    // 늘 '보임' 으로 판정돼 계속 폴링하고 마커를 다시 계산했다.
    //
    // 지도 위젯의 타이머는 지도 로드 이후에 걸리는 것이 많아 AoTPoll 의 ready_end
    // 귀속 구간을 벗어난다. 그래서 여기서 직접 뷰포트를 본다.
    // 여백은 AoTPoll 의 rootMargin 과 같은 뜻 — 한 화면쯤 미리 깨워 둔다.
    const _VIEWPORT_MARGIN_PX = 300;

    function _isWidgetVisible(instance) {
        try {
            const el = instance && instance.map && instance.map.getContainer();
            if (!el || el.offsetParent === null) return false;   // display:none 은 여전히 제외
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) return false;
            const vh = window.innerHeight || document.documentElement.clientHeight;
            const vw = window.innerWidth || document.documentElement.clientWidth;
            return r.bottom >= -_VIEWPORT_MARGIN_PX &&
                   r.top    <=  vh + _VIEWPORT_MARGIN_PX &&
                   r.right  >= -_VIEWPORT_MARGIN_PX &&
                   r.left   <=  vw + _VIEWPORT_MARGIN_PX;
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
                // 출력 상태 폴러가 쓸 목록을 여기서 남긴다. 서버 렌더의 vars.devices
                // 는 비어 있고(장치 조회는 클라이언트가 한다) setupRefresh 는 위젯
                // 주기(기본 30초)가 지나야 처음 채우므로, 그때까지 폴러가 갱신할
                // 대상이 없었다.
                if (instance) { instance._devices = devices; }
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
        const sensorOpts = _sensorLabelOptsFrom(wOpts);

        devices.forEach(function(dev) {
            const markerId = dev.unique_id || dev.id;
            const marker = instance.markers.get(markerId);
            if (!marker) return;

            let isON = dev.status === 'active' || dev.status === 'on' ||
                         dev.is_activated === true || dev.is_activated === 'true';
            const devType2 = dev.device_type || dev.type || '';
            const userColor = getUnifiedDeviceColor(devType2, dev, theme);
            const el = marker.getElement();

            // Input: 생성 때와 같은 공용 렌더러로 값/밴드 색만 갱신 (facility 동일)
            if (devType2 === 'input' && el &&
                el.classList.contains('aot-sensor-map-marker') &&
                window.AoTMapSensorLabels && window.AoTMapSensorLabels.renderValueLabel) {
                window.AoTMapSensorLabels.renderValueLabel(
                    el, _deviceChannels(dev, wOpts, instance), null, sensorOpts, _deviceDisplayName(dev));
                return;
            }

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


    // ── 출력 상태 전용 폴러 ─────────────────────────────────────────────────────
    // 장치 "목록" 과 "상태" 는 성격이 다르다: 목록은 배치를 바꿀 때만 변하고 조회가
    // 무겁다(/api/geo/devices), 상태는 수시로 변하고 조회가 가볍다(/outputstate —
    // 실측 출력 31개 15ms). 예전에는 둘이 위젯 갱신 주기 한 타이머에 묶여 있어서,
    // 출력을 켜도 그 주기가 돌아올 때까지(기본 30초) 마커가 옛 상태로 남았다.
    // 이제 상태만 '출력 상태 갱신 주기' 로 따로 돈다.
    function _outputDevicesOf(instance) {
        var list = (instance && instance._devices)
                || (instance && instance.vars && instance.vars.devices) || [];
        return list.filter(function (d) {
            return (d.device_type || d.type) === 'output';
        });
    }

    function _applyOutputStates(uniqueId, states) {
        var instance = window.AoTWidgetInstances[uniqueId];
        if (!instance || !states) return;
        var wOpts = (instance.vars && instance.vars.vars) || {};
        var touched = [];
        _outputDevicesOf(instance).forEach(function (dev) {
            // 식별은 마커 렌더러(refreshDeviceMarkersAppearance)와 같은 규칙으로.
            var base = dev.device_id || dev.device_unique_id
                || String(dev.unique_id || dev.id || '').split('::')[0];
            var byCh = states[base];
            if (!byCh) return;
            var ch = (dev.channel_id != null) ? String(dev.channel_id) : '0';
            var st = byCh[ch];
            if (st == null) return;
            dev.status = st;                       // 렌더러가 읽는 필드
            dev.is_activated = (st === 'on');
            touched.push(dev);
        });
        // **전체 목록**으로 부른다. 부분 목록으로 부르면 안 된다 —
        // refreshDeviceMarkersAppearance 끝의 _updateDeviceShapeOpacity 가 넘겨받은
        // 목록만으로 도형 레이어의 **전역** paint 표현식
        // (['match', device_id, onIds, 0.9, base])을 다시 쓰기 때문에, 목록에 빠진
        // ON 출력은 꺼진 것으로 칠해진다(/outputstate 가 모르는 출력이 그 경우다).
        // 상태는 위에서 같은 객체에 이미 써 넣었으므로 전체를 넘겨도 값은 최신이다.
        if (touched.length) {
            var all = (instance._devices)
                   || (instance.vars && instance.vars.devices) || [];
            refreshDeviceMarkersAppearance(uniqueId, all.length ? all : touched, wOpts);
        }

        // **켜져 있는 출력은 꺼 두었어도 보인다.** 지금 돌고 있는 것이 지도에
        // 없으면 "무엇이 작동 중인가" 를 화면이 답하지 못한다. 사용자가 꺼 둔
        // 상태는 그대로 두고(토글을 건드리지 않는다) 이유만 얹었다 뗀다 —
        // 꺼지면 원래대로 사라진다.
        //
        // 여기서 `touched` 만 보면 안 된다: /outputstate 가 모르는 출력은 목록에
        // 없고, 그 사이 꺼진 장치의 이유를 거둘 기회도 사라진다. 상태를 아는
        // 것 전부를 한 번에 훑는다.
        touched.forEach(function (dev) {
            var uuid = dev.shape_uuid || dev.unique_id || dev.device_id;
            if (!uuid) return;
            _setFocus(instance, uniqueId, String(uuid), 'active',
                      dev.is_activated === true, 'device');
        });
    }

    // /outputstate 는 전 출력을 한 번에 주는 **전역** 응답이고 데몬 RPC 를 탄다.
    // 대시보드에 지도 위젯이 여러 개면 같은 틱에 위젯 수만큼 같은 요청이 나가므로
    // (실측 3개 위젯 = 5초마다 3회) 짧은 TTL + in-flight 합치기로 1회로 접는다.
    // TTL 은 폴링 주기(최소 2초)보다 충분히 짧게 둔다 — 다음 틱은 반드시 새로 받는다.
    var _outStateCache = { ts: 0, data: null, inflight: null };
    var _OUT_STATE_TTL_MS = 900;

    function _fetchOutputStates(force) {
        var now = Date.now();
        if (!force) {
            if (_outStateCache.data && (now - _outStateCache.ts) < _OUT_STATE_TTL_MS) {
                return Promise.resolve(_outStateCache.data);
            }
            if (_outStateCache.inflight) { return _outStateCache.inflight; }
        }
        var pr = fetch('/outputstate')
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (d) { _outStateCache = { ts: Date.now(), data: d, inflight: null }; }
                else { _outStateCache.inflight = null; }
                return d;
            })
            .catch(function () { _outStateCache.inflight = null; return null; });
        if (!force) { _outStateCache.inflight = pr; }
        return pr;
    }

    // force=true 는 캐시를 건너뛴다 — 제어 직후에는 방금 보낸 명령보다 오래된
    // 응답을 쓰면 안 된다(시설 경로의 AoTFacilityRuntime force 와 같은 이유).
    function _refreshOutputStatesNow(uniqueId, force) {
        return _fetchOutputStates(force)
            .then(function (states) { _applyOutputStates(uniqueId, states); })
            .catch(function () { /* 데몬 불가 — 다음 주기에 다시 본다 */ });
    }

    // 제어 직후. 데몬이 상태를 반영하는 데 한 박자 걸리므로 짧게 여러 번 확인한다.
    // 화면을 낙관적으로 먼저 뒤집지는 않는다 — 명령이 실패하면 그 표시가 거짓이 된다.
    var _POST_CMD_REFRESH_MS = [120, 700, 1800];
    function _refreshOutputStatesAfterCommand(uniqueId) {
        _POST_CMD_REFRESH_MS.forEach(function (ms) {
            setTimeout(function () { _refreshOutputStatesNow(uniqueId, true); }, ms);
        });
    }

    function setupOutputStateRefresh(uniqueId, seconds) {
        var instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;
        if (instance.outputStateTimer) { clearInterval(instance.outputStateTimer); }
        var sec = parseFloat(seconds);
        // 0 = 끔. 위젯 갱신 주기(period)와는 독립이다 — 각 손잡이가 자기 것만 다스린다.
        if (!isFinite(sec) || sec <= 0) { instance.outputStateTimer = null; }
        else {
            var ms = Math.max(2, sec) * 1000;
            instance.outputStateTimer = setInterval(function () {
                if (document.hidden) return;
                if (!_isWidgetVisible(instance)) return;
                _refreshOutputStatesNow(uniqueId);
            }, ms);
        }
        // 설정 모달 라이브 반영용
        instance._setOutputStateInterval = function (s) {
            setupOutputStateRefresh(uniqueId, s);
        };
    }

    function setupRefresh(uniqueId, intervalSeconds) {
        const instance = window.AoTWidgetInstances[uniqueId];
        if (!instance) return;

        if (instance.refreshTimer) {
            clearInterval(instance.refreshTimer);
        }
        if (instance._deviceRefreshVisHandler) {
            document.removeEventListener('visibilitychange', instance._deviceRefreshVisHandler);
            instance._deviceRefreshVisHandler = null;
        }

        var _lastTick = 0;
        function _tick() {
            _lastTick = Date.now();
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

            fetchGeoDevicesShared(params.toString(), { skipIfUnchanged: true })
                .then(function(data) {
                    // null = 서버가 304. 파싱과 마커 외형 재계산은 건너뛴다 —
                    // 목록과 **상태**(status/position_pct)는 이 응답에 실려 있으니
                    // 304 면 그대로라는 뜻이 맞다.
                    //
                    // 하지만 측정 **값** 은 이 응답에 애초에 없다(실측: 측정행 195개
                    // 전부 last_value 없음 — 값은 /data_batch 가 따로 받는다). 그래서
                    // 값 갱신까지 함께 건너뛰면, 목록이 안 변하는 **정상 상태**에서
                    // 값이 영구히 멈춘다: 첫 로드가 한 번 비어 온 화면은 새로고침
                    // 말고는 복구할 방법이 없어진다. "장시간 미접속 후 열면 '—' 만
                    // 뜨고 갱신 주기에도 안 바뀐다" 는 증상이 이것이었다 —
                    // 콜드 캐시로 첫 조회가 비면 재시도가 사라진 것이 원인이고,
                    // 재현이 어려운 이유는 실패 자체가 일시적이기 때문이다.
                    if (!data || !data.ok) {
                        var known = instance._devices;
                        if (known && known.length) {
                            try { _refreshInputValues(uniqueId, known, wOpts); } catch (e) {}
                        }
                        return;
                    }
                    const devices = data.devices || [];
                    // 상태 폴러가 쓸 최신 목록을 남긴다(목록과 상태의 갱신 주기가 다르다).
                    if (devices.length > 0) instance._devices = devices;
                    if (data.all_measurements_map) wOpts.all_measurements_map = data.all_measurements_map;
                    // Update appearance only — no remove/re-add to prevent position flicker
                    if (devices.length > 0) {
                        refreshDeviceMarkersAppearance(uniqueId, devices, wOpts);
                        try { _refreshInputValues(uniqueId, devices, wOpts); } catch (e) {}
                    }
                })
                .catch(function(e) { })
        }

        instance.refreshTimer = setInterval(function() {
            if (document.hidden) return;
            if (!_isWidgetVisible(instance)) return;
            _tick();
        }, intervalSeconds * 1000);

        // 탭이 오래(수 시간) 숨어 있는 동안 위 setInterval 은 매 틱 document.hidden 에
        // 막혀 아무 것도 하지 않는다 — 다시 보이는 순간 다음 자연 틱까지 기다리지
        // 않고 즉시 한 번 갱신한다. 레이어 갱신(7806줄 _overlayVisHandler)과 같은
        // 패턴: "오랫동안 방문 없다가 열면 값이 안 뜨고 다음 갱신 주기까지 기다려야
        // 한다"는 증상이 이 손잡이의 부재였다 — 값 자체는 서버가 이미 장치 주기
        // 기준으로 조회 창을 넓혀 두므로(_effective_lookback) 항상 가져올 수 있는데,
        // 클라이언트가 그 요청을 던지는 시점만 숨은 탭의 다음 틱까지 밀렸다.
        instance._deviceRefreshVisHandler = function() {
            if (document.hidden) return;
            if (!_isWidgetVisible(instance)) return;
            if ((Date.now() - _lastTick) >= intervalSeconds * 1000) _tick();
        };
        document.addEventListener('visibilitychange', instance._deviceRefreshVisHandler);
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
        if (instance._deviceRefreshVisHandler) {
            document.removeEventListener('visibilitychange', instance._deviceRefreshVisHandler);
            instance._deviceRefreshVisHandler = null;
        }
        if (instance.refreshTimer) {
            clearInterval(instance.refreshTimer);
        }
        if (instance.panelRefreshTimer) {
            clearInterval(instance.panelRefreshTimer);
        }
        if (instance._panelRefreshVisHandler) {
            document.removeEventListener('visibilitychange', instance._panelRefreshVisHandler);
            instance._panelRefreshVisHandler = null;
        }
        if (instance.outputStateTimer) {
            clearInterval(instance.outputStateTimer);
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

        // Remove zoom gate handler
        if (instance._zoomGateHandler && instance.map) {
            instance.map.off('zoom', instance._zoomGateHandler);
            instance.map.off('zoomend', instance._zoomGateHandler);
            instance._zoomGateHandler = null;
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
