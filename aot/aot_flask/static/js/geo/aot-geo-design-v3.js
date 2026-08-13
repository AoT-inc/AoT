/**
 * aot-geo-design.js
 * Refactored Geo Design Client
 * Uses: AoTMapLoader, AoTMapEditor, AoTMapControls, AoTMapData
 */

class AoTGeoDesign {
    constructor(mapId) {
        this.mapId = mapId;
        this.map = null;
        this.currentMapUuid = null;
        this.currentMapName = "New Design Map";

        // State
        this.activeMode = 'site'; // site, zone, facility, equipment, aot_device
        this.activeLayer = null;  // Track currently selected layer for toggle
        this.isLocked = false;
        this.isHidden = false;

        // Layer Storage (Separated by Mode for Isolation) - Pure MapLibre via AoTGeoLayerGroup
        this.layerStorage = {
            'site': new AoTGeoLayerGroup('site'),
            'zone': new AoTGeoLayerGroup('zone'),
            'device': new AoTGeoLayerGroup('device'),
            'facility': new AoTGeoLayerGroup('facility'),
            'equipment': new AoTGeoLayerGroup('equipment'),
            'connection': new AoTGeoLayerGroup('connection'),
            'aot_device': new AoTGeoLayerGroup('aot_device'),
            'infra_blob': new AoTGeoLayerGroup('infra_blob'),
            'reference': new AoTGeoLayerGroup('reference'),
            'label_aux': new AoTGeoLayerGroup('label_aux'),
            // 식생 구획은 GeoShape 가 아니지만(별도 테이블) 그룹은 필요하다 —
            // 편집 도구가 여기서 레이어를 찾아 정점 편집 대상으로 삼는다
            // (_onDrawEdited 의 layerStorage 순회). 저장은 typesToSync 가
            // 아니라 vegetation 모듈이 자기 API 로 한다.
            'vegetation': new AoTGeoLayerGroup('vegetation')
        };
        
        // [Optimization] Dirty Tracking for Delta Save
        this.dirtyNodeIds = new Set();
        this.deletedNodeIds = new Set(); // Tracks node_ids (str) or db_ids (int)

        this.isLoading = false; // [Fix] Clear loading state on start
        this.loadingOverlay = null;

        // Initialized early to prevent Object.entries(undefined) before map.on('load') fires
        this.baseMaps = {};
        this.overlayMaps = {};

        // Design Statistics
        this.designStats = {
            sites: [],
            totals: {
                siteCount: 0, zoneCount: 0, deviceCount: 0,
                area: 0, pipeMainLen: 0, pipeBranchLen: 0,
                emitters: 0, input: 0, output: 0, function: 0, waterUsage: 0
            }
        };

        this.ui = new AoTGeoUI(this);
        this.geometry = new AoTGeoGeometry(this);
        this.events = new AoTGeoEvents(this);
        this.modules = new AoTGeoModules(this);
        this.labels = new AoTGeoLabel(this);
        this.devices = new AoTGeoDevices(this);
        // 공간 슬롯 ↔ 장치 배정(geo_binding). 배치(devices)와는 다른 축이다 —
        // 저쪽은 좌표, 이쪽은 "이 자리를 지금 어느 장치가 맡는가"다.
        this.binding = window.AoTGeoBinding ? new AoTGeoBinding(this) : null;
        // 식생 구획(작기). 저장처가 GeoShape 가 아니라 geo_planting 이라
        // saveDesign/typesToSync 경로를 타지 않는다 — 자기 API 로만 오간다.
        this.vegetation = window.AoTGeoVegetation
            ? new AoTGeoVegetation(this) : null;
        this.stats = new AoTGeoStats(this);
    }

    init() {
        // console.log("AoTGeoDesign initializing (Modular)...");
        this._initMap();
        this._initPanelToggle();

        // 1. Initialize Theme Config FIRST to ensure CSS Variables are ready
        this.ui.applyThemeConfig();

        // Initialize Map Search Controller
        if (window.AoTMapSearchController) {
            // console.log("[GeoDesign] Found AoTMapSearchController, initializing...");
            this.searchController = new AoTMapSearchController(this.map, {
                searchId: 'design-search',
                toggleBtnId: 'tool-search', // From geo_design.html HTML
                overlayId: 'search-overlay' // From geo_design.html HTML
            });
        }

        // Initialize Mode Panel FIRST to ensure checking for listeners works if they trigger immediate renders
        this.panel = new AoTGeoPanel('nav-mode-panel', this);

        // [Fix V19] Initialize UI with Default Mode
        // Call render first to ensure panel structure exists
        this.panel.render(this.activeMode);
        
        // Then Call setMode to initialize FULL UI (Draw Controls, Layers, Panel Sync)
        this.setMode(this.activeMode);

        this.events.bindEvents();
        this._autoLoadDesign();
    }



    // [Pure MapLibre] Map Initialization - No Leaflet Dependencies
    _initMap() {
        const self = this;
        
        // Wait for MapLibre GL to be available
        if (typeof maplibregl === 'undefined') {
            console.error('[GeoDesign] MapLibre GL is not loaded. Design page requires vector mode.');
            return;
        }

        // Get configuration from backend
        const config = window.AOT_GEO_CONFIG || {};
        const settings = config;
        
        // Get first vector layer as base style
        const vectorLayers = (config.layers || []).filter(l => l.type === 'vector');
        const FALLBACK_STYLE = 'https://demotiles.maplibre.org/style.json';
        const vectorStyle = (vectorLayers.length > 0 && vectorLayers[0].url)
            ? vectorLayers[0].url : FALLBACK_STYLE;

        // Calculate center and zoom from settings
        const centerLng = parseFloat(settings.default_lng) || 126.978;
        const centerLat = parseFloat(settings.default_lat) || 37.5665;
        const zoom = parseFloat(settings.zoom) || 12;
        const pitch = parseFloat(settings.default_pitch) || 0;
        const bearing = parseFloat(settings.default_bearing) || 0;

        // Create Pure MapLibre Map (No Leaflet)
        this.map = new maplibregl.Map({
            container: this.mapId,
            style: vectorStyle,
            center: [centerLng, centerLat],
            zoom: zoom,
            pitch: pitch,
            bearing: bearing,
            attributionControl: false,
            antialias: true
        });

        // Sprite icons referenced by the base vector style but absent from its sprite
        // sheet (e.g. POI icons like "office_11") otherwise spam "image could not be
        // loaded" warnings. Register a 1x1 transparent placeholder for any missing id.
        // NOTE: capture the NATIVE map instance here. `this.map` is reassigned to the
        // Leaflet compat shim below, and the shim does not delegate hasImage/addImage —
        // so referencing this.map inside this async handler would throw
        // "this.map.hasImage is not a function" once the event fires (e.g. at zoom >= 14
        // where the base style renders POI symbols that request missing sprite icons).
        const nativeMap = this.map;
        nativeMap.on('styleimagemissing', (e) => {
            if (!e || !e.id || nativeMap.hasImage(e.id)) return;
            nativeMap.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) });
        });

        // If the initial vectorStyle URL is unreachable (e.g. invalid API key → 401),
        // fall back to the open demotiles style so the map still renders.
        // Guard: once the initial style has loaded successfully, this handler must not
        // fire on subsequent tile/glyph 404s (which are normal during rendering and
        // must NOT trigger a style fallback — doing so loads demotiles world map).
        // Only fall back when the STYLE RESOURCE itself failed to load — i.e. an AJAX
        // error (auth/not-found) on the style.json URL. setLayoutProperty / "layer does
        // not exist in the map's style" errors are plain Errors with no .status and must
        // NOT trigger a fallback (was: msg.includes('style') → false positive that
        // wrongly dropped a valid MapTiler style to demotiles). The listener is detached
        // once the initial style loads so MapLibre's default error logging resumes.
        const _onInitError = (e) => {
            const err = e && e.error;
            const status = (err && err.status) || 0;
            const url = (err && err.url) || '';
            const isStyleResource = url === vectorStyle || url.indexOf('style.json') !== -1;
            if (isStyleResource && (status === 401 || status === 403 || status === 404 || status >= 500)) {
                console.warn('[GeoDesign] Base style failed to load (HTTP ' + status + '), falling back to demotiles:', vectorStyle);
                this.map.off('error', _onInitError);
                try { this.map.setStyle(FALLBACK_STYLE); } catch(err2) {}
            }
        };
        this.map.on('error', _onInitError);
        this.map.once('load', () => { this.map.off('error', _onInitError); });

        // Expose native map for debugging
        window._aotNativeMap = this.map;

        // Wrap with compat shim for Leaflet API compatibility (eachLayer, bindPopup, etc.)
        if (window.AoTMapLibreCompatShim && !this.map._isShimmed) {
            const mapInstance = this.map; // Keep reference to original MapLibre instance
            window._aotNativeMap = mapInstance; // Update to pre-shim instance
            const shim = new window.AoTMapLibreCompatShim(mapInstance);
            shim.init();
            
            // Delegate MapLibre native methods to original instance
            const nativeMethods = [
                'addControl', 'removeControl', 'on', 'off', 'once',
                'getStyle', 'getSource', 'addSource', 'getLayer',
                'addLayer', 'removeLayer', 'moveLayer', 'setLayoutProperty',
                'setPaintProperty', 'getCanvas', 'resize', 'remove',
                'jumpTo', 'easeTo', 'flyTo', 'panTo', 'setCenter',
                'setZoom', 'setBearing', 'setPitch', 'fitBounds',
                'project', 'unproject', 'queryRenderedFeatures', 'hasControl',
                // Critical: needed by AoTGeoLayerGroup.addLayer and _loadAllFeatures
                // to know whether to call doAdd immediately or wait for load event
                'isStyleLoaded', 'loaded',
                // Needed by _toggleLengthLabels
                'getContainer'
            ];

            nativeMethods.forEach(method => {
                if (typeof mapInstance[method] === 'function') {
                    shim[method] = mapInstance[method].bind(mapInstance);
                }
            });

            this.map._compatShim = shim;
            // [Fix] Set _originalMap on the SHIM (not on mapInstance) so that
            // (this.map._originalMap) correctly resolves the native map after this.map = shim
            shim._originalMap = mapInstance;
            mapInstance._compatShim = shim; // Allow native map to reference shim
            this.map = shim; // Use shim as this.map for components that need Leaflet APIs

            // [Fix] Override addLayer/removeLayer/hasLayer on shim to handle AoTGeoLayerGroup.
            // Native MapLibre's addLayer() expects a LayerSpecification ({id, type, source, ...}).
            // Passing an AoTGeoLayerGroup throws "Unknown layer type undefined", crashing
            // _processLoadedFeature → onEachFeature → fromGeoJSON → _loadAllFeatures.
            const _origAddLayer = mapInstance.addLayer.bind(mapInstance);
            const _origRemoveLayer = mapInstance.removeLayer.bind(mapInstance);
            const _origHasLayer = mapInstance.hasLayer ? mapInstance.hasLayer.bind(mapInstance) : null;

            shim.addLayer = function(layerOrGroup, beforeId) {
                if (layerOrGroup && layerOrGroup._isAoTLayerGroup) {
                    // Mark group as "on the map" and trigger doAdd() for all already-queued layers.
                    layerOrGroup._map = shim;
                    const existing = Array.from(layerOrGroup._layers.values());
                    existing.forEach(l => { l._map = shim; layerOrGroup.addLayer(l); });
                    return shim;
                }
                try { return _origAddLayer(layerOrGroup, beforeId); }
                catch (e) { console.warn('[GeoDesign] shim.addLayer error:', e.message); return shim; }
            };

            shim.removeLayer = function(layerOrGroup) {
                if (layerOrGroup && layerOrGroup._isAoTLayerGroup) {
                    // Just unmark — individual MapLibre layers stay in the style (avoid flicker).
                    layerOrGroup._map = null;
                    return shim;
                }
                if (typeof layerOrGroup === 'string') {
                    try { if (mapInstance.getLayer(layerOrGroup)) return _origRemoveLayer(layerOrGroup); }
                    catch (e) {}
                }
                return shim;
            };

            shim.hasLayer = function(layerOrGroup) {
                if (layerOrGroup && layerOrGroup._isAoTLayerGroup) {
                    return layerOrGroup._map === shim;
                }
                if (typeof layerOrGroup === 'string') {
                    try { return _origHasLayer ? _origHasLayer(layerOrGroup) : !!mapInstance.getLayer(layerOrGroup); }
                    catch (e) {}
                }
                return false;
            };
        }

        // [Fix] Pre-initialize AoTMapEditor.featureGroup synchronously so that
        // setMode() calls before the 'load' event fires don't crash on null featureGroup.
        // onMapReady will call the full AoTMapEditor.init() later (sets up drawManager etc.)
        if (window.AoTMapEditor && !window.AoTMapEditor.featureGroup) {
            window.AoTMapEditor.featureGroup = {
                layers: [],
                _isAoTLayerGroup: true,
                clearLayers: function() { this.layers = []; },
                getLayers: function() { return this.layers; },
                addLayer: function(l) { if (!this.layers.includes(l)) this.layers.push(l); },
                removeLayer: function(l) { this.layers = this.layers.filter(x => x !== l); },
                hasLayer: function(l) { return this.layers.includes(l); },
                eachLayer: function(fn) { this.layers.forEach(fn); },
                toGeoJSON: function() {
                    return {
                        type: 'FeatureCollection',
                        features: this.layers.map(l => l.toGeoJSON ? l.toGeoJSON()
                            : { type: 'Feature', geometry: l.feature?.geometry, properties: l.feature?.properties || {} })
                    };
                }
            };
        }

        // Native compass injected into .tool-group in onMapReady (after map loads).
        // Store for later use in onMapReady.
        this._navCtrl = new maplibregl.NavigationControl({
            showCompass: true,
            showZoom: false,
            visualizePitch: true
        });

        // Add Scale Control
        this.map.addControl(new maplibregl.ScaleControl({
            maxWidth: 100,
            unit: 'metric'
        }), 'bottom-left');

        // Add Attribution Control (bottom-right)
        // (OSM long-form "contributors" text is normalized globally by
        // aot-maplibre-patches.js, applied to every AttributionControl instance.)
        this.map.addControl(new maplibregl.AttributionControl({
            compact: true
        }), 'bottom-right');

        // Store as vectorMap for compatibility
        this.vectorMap = this.map;

        // Wait for map to load, then initialize managers
        // Run idempotently — if 'load' already fired before this listener attached
        // (possible due to shim wrapping order), invoke immediately.
        let _initRan = false;
        const onMapReady = () => {
            if (_initRan) return;
            _initRan = true;

            // [Priority 1] Initialize Editor with MapLibre map — must run first so
            // featureGroup & drawManager are ready before any other manager tries to use them.
            try {
                if (window.AoTMapEditor && window.AoTMapEditor.init) {
                    // Create MapLibre-compatible FeatureGroup (replaces pre-init stub)
                    const featureGroup = {
                        layers: [],
                        _isAoTLayerGroup: true, // Prevent AoTGeoLayer.addTo from calling maplibreMap.addLayer(this)
                        clearLayers: function() { this.layers = []; },
                        getLayers: function() { return this.layers; },
                        addLayer: function(l) {
                            // Always re-register with MapLibre — doAddToMap guards against duplicates.
                            // The old `!l._map` guard caused polygons from storage to skip addTo()
                            // because storageGroup.addLayer() had already set l._map = shim.
                            try {
                                if (l.addTo) l.addTo(self.map);
                            } catch(e) {
                                console.error('[featureGroup.addLayer] addTo threw:', e.message, e.stack);
                            }
                            if (!this.layers.includes(l)) this.layers.push(l);
                        },
                        removeLayer: function(l) {
                            this.layers = this.layers.filter(x => x !== l);
                        },
                        hasLayer: function(l) { return this.layers.includes(l); },
                        eachLayer: function(fn) { this.layers.forEach(fn); },
                        toGeoJSON: function() {
                            return {
                                type: 'FeatureCollection',
                                features: this.layers.map(l => l.toGeoJSON ? l.toGeoJSON()
                                    : { type: 'Feature', geometry: l.feature?.geometry, properties: l.feature?.properties || {} })
                            };
                        }
                    };
                    // Pass native MapLibre map — MapLibreDraw needs addControl, getCanvas, doubleClickZoom
                    const _nativeMapForEditor = self.map._originalMap || self.map;
                    window.AoTMapEditor.init(_nativeMapForEditor, featureGroup);
                    // Expose layerStorage so maplibre-draw.js fallback edit/delete can find loaded shapes
                    window.AoTMapEditor.layerStorage = self.layerStorage;
                }
            } catch (editorErr) {
                console.error('[GeoDesign] AoTMapEditor.init failed:', editorErr);
            }

            try {

            // Initialize Vector Layer Manager
            if (window.AoTVectorLayerManager && window.AoTVectorLayerManager.bind) {
                window.AoTVectorLayerManager.bind(self.map);
            }

            // Initialize Raster Bridge (for XYZ/WMS overlays)
            if (window.AoTRasterBridge && window.AoTRasterBridge.create) {
                window.AoTRasterBridge.create(self.map);
            }

            // Initialize GeoJSON Manager
            if (window.AoTGeoJSONManager && window.AoTGeoJSONManager.bind) {
                window.AoTGeoJSONManager.bind(self.map);
            }

            // Initialize MapLibre Draw
            if (window.AoTMapLibreDraw && window.AoTMapLibreDraw.bind) {
                window.AoTMapLibreDraw.bind(self.map);
            }

            // Initialize Custom Controls (Site List, Measure, Memo, Layer)
            if (window.AoTMapCustomControls && window.AoTMapCustomControls.addStandardCustomControls) {
;
                var customControls = window.AoTMapCustomControls.addStandardCustomControls(self.map._originalMap || self.map, {
                    // 사이트 목록은 HTML 툴바 버튼(#tool-site-list → toggleSiteList)이
                    // 실제 레이어를 스캔해 처리한다. 커스텀 컨트롤 버전은 sites 가 주입되지
                    // 않아 항상 비어 있는 비작동 중복이므로 비활성화(버튼 2개 중복 제거).
                    includeSiteList: false,
                    includeMeasure: false,
                    includeMemo: false,
                    includeLayer: false,
                    sites: []
                });
                self._customControls = customControls;
            } else {
                console.warn('[GeoDesign] AoTMapCustomControls not found, attempting dynamic load');
                // Try to load the script dynamically
                if (!document.querySelector('script[src*="aot-map-custom-controls"]')) {
                    var script = document.createElement('script');
                    script.src = '/static/js/geo/aot-map-custom-controls.js?v=' + (window.AOT_ASSET_V || '');
                    script.onload = function() {
                        if (window.AoTMapCustomControls && window.AoTMapCustomControls.addStandardCustomControls) {
                            var customControls = window.AoTMapCustomControls.addStandardCustomControls(self.map._originalMap || self.map, {
                                // 사이트 목록은 HTML 툴바 버튼(#tool-site-list → toggleSiteList)이
                    // 실제 레이어를 스캔해 처리한다. 커스텀 컨트롤 버전은 sites 가 주입되지
                    // 않아 항상 비어 있는 비작동 중복이므로 비활성화(버튼 2개 중복 제거).
                    includeSiteList: false,
                                includeMeasure: false,
                                includeMemo: false,
                                includeLayer: false,
                                sites: []
                            });
                            self._customControls = customControls;
                        }
                    };
                    document.head.appendChild(script);
                }
            }

            // Initialize Base/Overlay Maps (empty for pure MapLibre)
            self.baseMaps = {};
            self.overlayMaps = {};

            // [Fix V11] Ensure pendingOp is cleared when drawing stops
            if (window.AoTMapLibreDraw && typeof window.AoTMapLibreDraw.on === 'function') {
                window.AoTMapLibreDraw.on('modechange', () => {
                    const mode = window.AoTMapLibreDraw.getMode ? window.AoTMapLibreDraw.getMode() : null;
                    if (mode === 'simple_select' || mode === 'static' || !mode) {
                        self._resetPendingOp();
                    }
                });
                window.AoTMapLibreDraw.on('draw.create', () => {
                    self._resetPendingOp();
                });
            }

            // Initialize storage groups for GeoJSON layers
            self._initStorageGroups();

            // Inject native MapLibre compass into the zoom tool-group (below zoom-out).
            // onAdd() registers all bearing/pitch listeners and returns the ctrl container.
            if (self._navCtrl) {
                const _nativeForCompass = self.map._originalMap || self.map;
                try {
                    const ctrlEl = self._navCtrl.onAdd(_nativeForCompass);
                    const zoomGroup = document.querySelector('#geo-design-wrapper .map-tools-left .tool-group');
                    if (ctrlEl && zoomGroup) {
                        // Remove the placeholder button if still present
                        const placeholder = document.getElementById('tool-compass');
                        if (placeholder) placeholder.remove();
                        // Keep ctrlEl intact so MapLibre CSS rules (.maplibregl-ctrl button .icon)
                        // still apply (they require the .maplibregl-ctrl ancestor for specificity).
                        // Zero out the ctrl-group's own box — tool-group provides the visual container.
                        ctrlEl.style.cssText = 'background:transparent;box-shadow:none;border-radius:0;overflow:visible;';
                        zoomGroup.appendChild(ctrlEl);
                    }
                } catch(e) {
                    console.warn('[GeoDesign] Compass inject failed:', e.message);
                }
            }

            // Snapshot the layer IDs that belong to the initial vector style.
            // The layer panel uses this to hide/restore them when switching to a
            // raster base map, preventing vector + raster from rendering together.
            {
                const _native = self.map._originalMap || self.map;
                self._baseStyleLayerIds = (_native && _native.getStyle
                    ? (_native.getStyle().layers || []).map(l => l.id)
                    : []);
            }
            // Track the currently-loaded vector style URL so the layer panel can
            // detect when a real style switch is needed vs. just restoring visibility.
            self._activeVectorStyleUrl = vectorStyle;

            // Add layer control
            if (typeof globalThis.addLayerControlToMap === 'function') {
                globalThis.addLayerControlToMap(self.map);
            }

            // Initialize Legacy Layer Buttons (MapLibre-ready)
            if (self.ui && typeof self.ui.initLegacyLayerButtons === 'function') {
;
                self.ui.initLegacyLayerButtons();
            }

            } catch (e) {
                console.error('[GeoDesign] Error in onMapReady:', e);
            }
        };

        // Attach for future load events
        this.map.on('load', onMapReady);
        // Also try immediately — style may already be loaded if shim wrapping
        // happened after the underlying map fired 'load'.
        const _native = (this.map && this.map._originalMap) ||
                        (this.map && this.map.getNativeMap && this.map.getNativeMap()) ||
                        this.map;
        if (_native && _native.isStyleLoaded && _native.isStyleLoaded()) {
;
            onMapReady();
        } else if (_native && _native.once) {
            // Backup: also wait on the native map directly in case shim.on path is broken
            _native.once('load', onMapReady);
            _native.once('idle', onMapReady);
        }

        // Pre-inject label CSS so zoom handler can rely on it from the start
        this._ensureLabelStyles();

        // [C] Zoom-based equipment culling — threshold read from GIS settings (default 15)
        const MIN_COVERAGE_ZOOM = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.equipment_cull_zoom != null)
            ? window.AOT_GEO_CONFIG.equipment_cull_zoom : 15;
        const _nativeForZoom = (this.map && this.map._originalMap) || this.map;
        if (_nativeForZoom && _nativeForZoom.on) {
            _nativeForZoom.on('zoomend', () => {
                const zoom = _nativeForZoom.getZoom ? _nativeForZoom.getZoom() : 99;
                const visible = zoom >= MIN_COVERAGE_ZOOM;
                this._setEquipmentLayerVisibility(visible);
                this._setDetailLabelVisibility(visible);
            });

            // Apply initial zoom state once the map style is ready.
            // zoomend never fires on load, so _zoomDetailVisible would stay undefined
            // if the page opens at zoom < MIN_COVERAGE_ZOOM.
            const applyInitialZoom = () => {
                const zoom = _nativeForZoom.getZoom ? _nativeForZoom.getZoom() : 99;
                const visible = zoom >= MIN_COVERAGE_ZOOM;
                this._setEquipmentLayerVisibility(visible);
                this._setDetailLabelVisibility(visible);
            };
            if (_nativeForZoom.isStyleLoaded && _nativeForZoom.isStyleLoaded()) {
                applyInitialZoom();
            } else {
                _nativeForZoom.once('load', applyInitialZoom);
            }
        }

        // Handle map errors gracefully
        this.map.on('error', (e) => {
            if (e.error && e.error.status === 401) {
                console.warn('[GeoDesign] Map tile authentication failed. Check API key.');
            }
        });
    }

    _setEquipmentLayerVisibility(visible) {
        const mlMap = (this.map && this.map._originalMap) || this.map;
        if (!mlMap || !mlMap.setLayoutProperty) return;
        const visibility = visible ? 'visible' : 'none';
        const toggleLayer = (l) => {
            if (l && l._layerId) {
                try { mlMap.setLayoutProperty(l._layerId, 'visibility', visibility); } catch(e) {}
            }
        };
        const scanGroup = (group) => {
            if (!group || !group.eachLayer) return;
            group.eachLayer(toggleLayer);
        };
        scanGroup(this.layerStorage['equipment']);
        scanGroup(this.layerStorage['connection']);
        const fg = window.AoTMapEditor && window.AoTMapEditor.featureGroup;
        if (fg && fg.getLayers) {
            const isEquipmentMode = this.activeMode === 'equipment';
            if (isEquipmentMode) fg.getLayers().forEach(toggleLayer);
        }
    }

    _setDetailLabelVisibility(visible) {
        this._zoomDetailVisible = visible;

        // CSS class hides: zone name labels, all measure labels, pipe labels.
        // Site name labels (.aot-site-label) are NOT in this rule — always visible.
        // Zone name labels (.aot-zone-label) ARE hidden here per spec (hides zoom<15).
        // Connection dots are controlled separately via GL setLayoutProperty in
        // _applyConnectionVisibility, not via CSS.
        const container = this.map?.getContainer?.();
        if (container) {
            if (visible) {
                container.classList.remove('aot-zoom-hide-detail');
            } else {
                container.classList.add('aot-zoom-hide-detail');
            }
        }

        this._applyConnectionVisibility(visible);
    }

    _applyConnectionVisibility(visible) {
        const mlMap = (this.map && this.map._originalMap) || this.map;
        if (!mlMap || !mlMap.setLayoutProperty) return;
        const visibility = visible ? 'visible' : 'none';

        // Phase 3: Use the single 'connection-dot' bucket layer instead of iterating
        // each connection wrapper layer individually. This is much faster (1 call vs N calls).
        try {
            mlMap.setLayoutProperty('aot-bucket-connection-dot', 'visibility', visibility);
        } catch (e) {
            // Fallback: iterate all layers in the connection group (for mixed bucket/pre-bucket state)
            const connGroup = this.layerStorage['connection'];
            if (connGroup && connGroup.eachLayer) {
                connGroup.eachLayer(l => {
                    if (l && l._layerId) {
                        try { mlMap.setLayoutProperty(l._layerId, 'visibility', visibility); } catch(e2) {}
                    }
                });
            }
        }
    }

    // Re-read current zoom and re-apply equipment + detail-label visibility.
    // Must be called after any operation that adds GL layers (mode switch, initial load,
    // failsafe) because setStyle() always resets GL visibility to 'visible'.
    _reapplyZoomVisibility() {
        const _native = (this.map && this.map._originalMap) || this.map;
        if (!_native || !_native.getZoom) return;
        const minZ = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.equipment_cull_zoom != null)
            ? window.AOT_GEO_CONFIG.equipment_cull_zoom : 15;
        const visible = _native.getZoom() >= minZ;
        this._setEquipmentLayerVisibility(visible);
        this._setDetailLabelVisibility(visible);
    }

    // [Pure MapLibre] Initialize Storage Groups for GeoJSON Layers
    _initStorageGroups() {
        const self = this;
        const storageTypes = ['site', 'zone', 'facility', 'infra_blob', 'connection', 'equipment', 'aot_device', 'device', 'label_aux', 'reference'];
        
        storageTypes.forEach(type => {
            if (self.layerStorage[type]) {
                // MapLibre uses source/layer instead of Leaflet FeatureGroup
                // The actual layers will be added via GeoJSON Manager
            }
        });
    }

    // Elevate the active mode's pane above all other mode panes so its shapes
    // are rendered on top regardless of the fixed pane hierarchy.
    _applyActivePaneZ() {
        if (!this.map || typeof this.map.getPane !== 'function') return;
        const BASE_Z = { sitePane: 350, zonePane: 360, facilityPane: 400, equipmentPane: 450, devicePane: 460 };
        const MODE_TO_PANE = {
            site: 'sitePane', zone: 'zonePane', facility: 'facilityPane',
            equipment: 'equipmentPane', aot_device: 'devicePane', device: 'devicePane'
        };
        const activePane = MODE_TO_PANE[this.activeMode];
        Object.entries(BASE_Z).forEach(([name, z]) => {
            const pane = this.map.getPane(name);
            if (pane) pane.style.zIndex = (name === activePane) ? (z + 150) : z;
        });
    }

    // [Pure MapLibre] Explicit Layer Order Management
    // In MapLibre, z-ordering is handled via layer paint properties or style reordering.
    // This method ensures GeoJSON layers are correctly ordered in the style.
    _enforceLayerOrder() {
        if (!this.map || !this.map.isStyleLoaded()) return;
        
        // MapLibre handles z-ordering through style layer order
        // GeoJSON layers should be added in correct order to the style
        // For now, this is a no-op as layers are managed by AoTGeoJSONManager
    }

    _initPanelToggle() {
        const btn = document.getElementById('tool-toggle-panel');
        // Targeted ID for new panel
        const panel = document.getElementById('nav-mode-panel');

        if (!btn || !panel) return;

        btn.onclick = (e) => {
            e.preventDefault();
            const isHidden = btn.dataset.hidden === 'true';

            // console.log(`[GeoDesign] Panel Toggle Clicked. Current Hidden State: ${isHidden}`);

            if (isHidden) {
                // Show
                panel.style.setProperty('display', '', 'important'); 
                // Fallback if 'important' blocked reset, try forced block/flex? 
                // Usually '' removes the inline style, allowing CSS to take over. 
                // If CSS was 'display: none', this fails. But CSS should be visible by default.
                if (window.getComputedStyle(panel).display === 'none') {
                     panel.style.setProperty('display', 'flex', 'important');
                }
                
                btn.dataset.hidden = 'false';
                btn.innerHTML = '<i class="fas fa-chevron-down"></i>';
                btn.setAttribute('title', _('hide_panel'));
            } else {
                // Hide
                panel.style.setProperty('display', 'none', 'important');
                btn.dataset.hidden = 'true';
                btn.innerHTML = '<i class="fas fa-chevron-up"></i>';
                btn.setAttribute('title', _('show_panel'));
            }
        };
    }

    // [Legacy Sub-Tabs removed]

    _autoLoadDesign() {
        // ... (No change)
        // 1. Check URL or LocalStorage
        const urlParams = new URLSearchParams(window.location.search);
        let uuid = urlParams.get('uuid');

        if (!uuid) {
            uuid = localStorage.getItem('aot_last_map_uuid');
        }

        // 2. [Auto-Select] If no history, and only 1 map exists in the selector, pick it.
        if (!uuid || uuid === 'null') {
            const selector = document.getElementById('map-selector');
            if (selector) {
                // Options: [0]=Placeholder, [1]=New, [2]...=Maps
                // Check if we have exactly one map (index 2 exists, index 3 does not)
                if (selector.options.length === 3) {
                    const singleMapOption = selector.options[2];
                    if (singleMapOption && singleMapOption.value !== 'new') {
                        uuid = singleMapOption.value;
                        // console.log("[AutoLoad] Only one map found. Auto-selecting:", uuid);
                    }
                }
            }
        }

        if (uuid && uuid !== 'null') {
            // console.log("Auto-loading Map:", uuid);
            // Sync Selector UI if valid
            const selector = document.getElementById('map-selector');
            if (selector && $(selector).val() !== uuid) {
                $(selector).selectpicker('val', uuid);
            }
            this.loadMap(uuid);
        } else {
            // console.log("No Map to auto-load. Ready for new design.");
            this.isLoading = false; // Ensure false if no auto-load
        }
    }

    _toggleInteraction(enabled) {
        // ... (No change - just context for patch)
        // console.log(`[Interaction] ${enabled ? 'Enabling' : 'Disabling'} Map Interaction`);

        // 1. Overlay
        if (!enabled) {
            // Create Overlay if not exists
            if (!this.loadingOverlay) {
                this.loadingOverlay = document.createElement('div');
                this.loadingOverlay.className = 'map-loading-overlay';
                this.loadingOverlay.innerHTML = `
                    <div class="spinner-border text-primary" role="status"></div>
                    <div class="loading-text">${_('loading_map')}</div>
                `;

                // Add CSS inline if not in file (Fallback)
                const style = document.createElement('style');
                style.textContent = `
                    .map-loading-overlay {
                        position: absolute; top: 0; left: 0; width: 100%; height: 100%;
                        background: rgba(255, 255, 255, 0.6); z-index: var(--aot-z-fixed-panel);
                        display: flex; flex-direction: column; align-items: center; justify-content: center;
                        backdrop-filter: blur(2px); pointer-events: auto;
                    }
                    .map-loading-overlay .loading-text { margin-top: 10px; font-weight: 600; color: #333; }
                `;
                document.head.appendChild(style);

                const container = document.getElementById('geo-design-wrapper');
                if (container) container.appendChild(this.loadingOverlay);
            }
            this.loadingOverlay.style.display = 'flex';
        } else {
            if (this.loadingOverlay) {
                this.loadingOverlay.style.display = 'none';
            }
        }

        // 2. Disable Drawing Tools
        if (window.AoTMapControls && window.AoTMapControls.toggleTools) {
            window.AoTMapControls.toggleTools(enabled);
        }

        // 3. Disable Save Button
        const saveBtn = document.getElementById('btn-save-global');
        if (saveBtn) saveBtn.disabled = !enabled;
    }

    setMode(mode) {
        // [Fix] Stop any active drawing/editing before switching modes
        if (window.AoTMapEditor && window.AoTMapEditor.stopAll) {
            window.AoTMapEditor.stopAll();
        }

        const oldMode = this.activeMode;
        this.activeMode = mode;

        // [Fix] Dynamic Editor Pane Assignment
        // Ensure Editor's featureGroup belongs to the current mode's Pane
        if (this.map && this.featureGroup) {
            // 식생은 zone 안에 그려지므로 zonePane 을 함께 쓴다 — 전용 pane 을
            // 새로 만들면 Leaflet/MapLibre 두 경로의 z-index 표를 모두 손봐야
            // 하는데 얻는 것이 없다.
            const paneName = (mode === 'site' ? 'sitePane' :
                             (mode === 'zone' || mode === 'vegetation' ? 'zonePane' :
                             (mode === 'facility' ? 'facilityPane' :
                             (mode === 'equipment' ? 'equipmentPane' : 
                             (mode === 'aot_device' || mode === 'device' ? 'devicePane' : 'overlayPane')))));
            
            // Re-bind to Pane
            this.featureGroup.options.pane = paneName;
            
            // Sync Pane Interactivity (Pointer-events)
            if (this.ui && this.ui.updatePaneInteractivity) {
                this.ui.updatePaneInteractivity(mode);
            }
        }

        // Critical: Tell Editor the new type!
        if (window.AoTMapEditor && window.AoTMapEditor.setType) {
            // [Fix V19] Context-Aware Type Setting
            // Check panel stack for specific sub-context (e.g., equipment -> pipe)
            let editorType = mode;
            if (this.panel && this.panel.navStack && this.panel.navStack.length > 2) {
                 const sub = this.panel.navStack[2]; // main, equipment, [pipe]
                 if (mode === 'equipment' && sub === 'pipe') editorType = 'equipment'; // Default
                 if (mode === 'aot_device' && sub === 'input') editorType = 'aot_device';
            }
            window.AoTMapEditor.setType(editorType);
        }

        // [Removed Legacy UI Tab Updates - Logic delegated to Panel]
        // The Panel render call below handles all visual navigation changes.

        // Layer Context Switch
        try {
            this._switchLayerContext(oldMode, mode);
            // Notify Editor
            window.dispatchEvent(new CustomEvent('aot:editor:mode', { detail: mode }));
        } catch (e) {
            console.error(`[AoTGeoDesign] Error switching layer context from ${oldMode} to ${mode}:`, e);
            if (this.ui && this.ui.showToast) this.ui.showToast(_('mode_switch_error'), 'error');
        }

        // Update Styles (Visuals for active/inactive)
        this.ui.updateLayerStyles();
        this.ui.updateDrawControls();

        // Render Panel
        if (this.panel) {
            this.panel.render(mode, this.activeLayer && this.activeLayer.feature);
        }

        // Bring active mode pane to top so its shapes are always visually dominant
        this._applyActivePaneZ();

        // [Fix V20] Ensure Editor is always on top (Z-Index Fix)
        // Storage layers added during context switch might cover the Editor group (Leaflet Add Order).
        // This fixes the "Cannot select shapes on first entry" issue.
        this._enforceLayerOrder();

        // Re-apply zoom-based equipment visibility after mode switch.
        // _setLayerStyle() called during _swapStorageLayers() resets GL layer visibility to
        // 'visible' via setLayoutProperty. This corrects it back to the zoom-appropriate state.
        this._reapplyZoomVisibility();

        // Restore length-label visibility for the new mode.
        // Each mode tracks its own hidden flag; switching modes must re-apply the correct class.
        this._applyLengthLabelState();

        // Update device marker draggability — only allowed in aot_device mode
        if (this.devices && this.devices.updateMarkersInteractivity) {
            this.devices.updateMarkersInteractivity();
        }

        // 식생 구획은 별도 테이블이라 _switchLayerContext 의 대상이 아니다.
        // 처음 이 모드에 들어올 때 한 번 불러온다(이후는 캐시).
        if (this.vegetation) {
            // 식생 모드에서만 진하게 — 다른 모드에서는 배경으로 물러난다.
            this.vegetation.setEmphasis(mode === 'vegetation');
            // **모드와 무관하게 불러온다.** 예전에는 식생 모드일 때만 load()
            // 를 불러서, 페이지를 열면(초기 모드 'site') 구획이 아예 없다가
            // 식생 탭에 한 번 들어가야 나타났다 — 다른 모드에서 배치를 조정할
            // 때 참고할 것이 없다는 뜻이다. load() 는 자체 캐시 가드가 있어
            // 여러 번 불러도 서버 요청은 한 번이다.
            this.vegetation.bindEditHook();
            this.vegetation.bindDeleteHook();
            this.vegetation.load();
        }

        // Auto Save Mode Change
        this._autoSaveState();

    }






    _clearAllFeatures() {
        // console.log("[Delete All] Clearing Everything...");
        // 1. Clear Editor
        window.AoTMapEditor.clear();

        // 2. Clear Active Storage
        if (this.layerStorage[this.activeMode]) {
            this.layerStorage[this.activeMode].clearLayers();
        }

        // 3. Clear Labels (Strong Delete)
        if (this.layerStorage['label_aux']) {
            this.layerStorage['label_aux'].clearLayers();
            if (this.map.hasLayer(this.layerStorage['label_aux'])) {
                this.map.removeLayer(this.layerStorage['label_aux']);
                this.map.addLayer(this.layerStorage['label_aux']);
            }
        }

        // 4. Force Save to Backend?
        // User might expect "Save" button to persist.
        // But "Clear All" usually implies immediate action or just clearing canvas?
        // Let's just clear canvas and let user click Main Save.
        // console.log("[Delete All] Canvas Cleared. Click Global Save to persist.");
    }

    /* --- Interactive Operation Handlers --- */

    _onShapeCreated(layer, type, drawingType) {
        // [Fix] Ensure loading state is cleared when user interaction starts
        if (this.isLoading) {
             this.isLoading = false;
        }

        // Delegation to Modules
        if (this.modules) {
            this.modules.onShapeCreated(layer, type, drawingType);
            return;
        }
        // 0. Check Pending Operation
        if (this.pendingOp) {
            // REMOVED old 'split' drawing logic
            // Handle Main Pipe Creation
            if (this.pendingOp.type === 'create_main_pipe') {
                // console.log("[GeoDesign] Main Pipe Created");
                layer.feature = layer.feature || { properties: {} };
                layer.feature.properties.aot_type = 'equipment';
                layer.feature.properties.sub_type = 'pipe_main';
                layer.feature.properties.name = _('main_pipe');
                if (this.geometry) this.geometry.updatePipeLabels(layer);
                this._resetPendingOp();
                // Continue to normal UUID assignment
            } else if (this.pendingOp.type === 'create_branch_pipe') {
                // console.log("[GeoDesign] Branch Pipe Created");
                layer.feature = layer.feature || { properties: {} };
                layer.feature.properties.aot_type = 'equipment';
                layer.feature.properties.sub_type = 'pipe_branch';
                layer.feature.properties.name = _('branch_pipe');
                if (this.geometry) this.geometry.updatePipeLabels(layer);
                this._resetPendingOp();
            } else if (this.pendingOp.type === 'create_ref_line') {
                 // [Fix] Handle Reference Line Creation
                 layer.feature = layer.feature || { properties: {} };
                 layer.feature.properties.aot_type = 'reference';
                 layer.feature.properties.sub_type = 'reference_line';
                 layer.feature.properties.name = _('reference_line');
                 this._resetPendingOp();
             }
        }

        // Critical: Assign Persistent UUID immediately
        layer.feature = layer.feature || { type: 'Feature', properties: {} };
        layer.feature.properties = layer.feature.properties || {};

        if (!layer.feature.properties.node_id) {
            // [Fix] Use Standard UUID v4 (Crypto API or robust fallback)
            if (window.crypto && window.crypto.randomUUID) {
                layer.feature.properties.node_id = window.crypto.randomUUID();
            } else if (window.uuidv4) {
                layer.feature.properties.node_id = window.uuidv4();
            } else {
                // Robust Fallback (RFC4122)
                layer.feature.properties.node_id = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                    var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
                    return v.toString(16);
                });
            }
            // console.log(`[Shape] Assigned New UUID: ${layer.feature.properties.node_id}`);
        }

        // [New] Track as dirty for Delta Save
        if (layer.feature.properties.node_id) {
            this.dirtyNodeIds.add(layer.feature.properties.node_id);
        }

        // Critical: Assign Type if missing
        if (!layer.feature.properties.aot_type && type) {
            layer.feature.properties.aot_type = type;
            // console.log(`[Shape] Assigned Default Type: ${type}`);
        }

        // [New] AoT Device Shape Linking (Activation Mode)
        if (this.devices && this.devices.activeDevice) {
            // Override type to 'device' to link shape to device
            layer.feature.properties.aot_type = 'device';
            // [Fix] Deconstruct unique_id for explicit column persistence (Phase 2)
            const activeDev = this.devices.activeDevice;
            const fullId = activeDev.unique_id; // UUID::CH
            const baseId = fullId.split('::')[0];
            const chId = activeDev.channel_id;

            layer.feature.properties.device_id = baseId;
            layer.feature.properties.channel_id = chId;
            layer.feature.properties.unique_id = fullId; // Keep for design lookup
            layer.feature.properties.device_type = activeDev.type; // [Fix] Persist Device Type
            
            // Apply device theme color immediately
            const themeColor = window.AoTGeoTheme.deviceColor(this.devices.activeDevice.type);

            if (layer.setStyle) {
                layer.setStyle({ color: themeColor, fillColor: themeColor });
            }
        } else if (type && ['site', 'zone', 'facility', 'equipment'].includes(type)) {
            // Apply Theme Color for Standard Types
            const themeColor = window.AoTGeoTheme.color(type);

            if (layer.setStyle) {
                layer.setStyle({ color: themeColor, fillColor: themeColor });
            }
        }

        // --- Auto-Link to Active Zone (Equipment/Reference Mode) ---
        const fType = layer.feature.properties.aot_type;
        if (['reference', 'equipment'].includes(fType) && this.activeLayer) {
            const activeProps = this.activeLayer.feature?.properties;
            // [Fix] Allow Site parent as well for Equipment/Reference
            if (activeProps && (activeProps.aot_type === 'zone' || activeProps.aot_type === 'site')) {
                layer.feature.properties.parent_node_id = activeProps.node_id;
                // console.log(`[Shape] Auto-linked new ${fType} to parent ${activeProps.aot_type}: ${activeProps.node_id}`);
            }
        }

        // [Fix] Orphan Reference Line Check
        if (fType === 'reference') {
            // If no parent linked, check geometry intersection
            if (!layer.feature.properties.parent_node_id) {
                const refGeo = layer.toGeoJSON();
                let foundParent = false;

                // 1. Check Zones
                if (this.layerStorage['zone']) {
                    this.layerStorage['zone'].eachLayer(z => {
                        if (foundParent) return;
                        // Loose check: intersects or contains
                        const zGeo = z.toGeoJSON();
                        // Reference is LineString, Zone is Polygon
                        if (window.turf.booleanIntersects(refGeo, zGeo) || window.turf.booleanContains(zGeo, refGeo)) {
                            layer.feature.properties.parent_node_id = z.feature.properties.node_id;
                            foundParent = true;
                        }
                    });
                }

                // 2. Check Sites (if not found in zone)
                if (!foundParent && this.layerStorage['site']) {
                    this.layerStorage['site'].eachLayer(s => {
                        if (foundParent) return;
                        const sGeo = s.toGeoJSON();
                        if (window.turf.booleanIntersects(refGeo, sGeo) || window.turf.booleanContains(sGeo, refGeo)) {
                            layer.feature.properties.parent_node_id = s.feature.properties.node_id;
                            foundParent = true;
                            // We could restrict reference to Zone only as per user request ("those without a parent shape such as a land lot/parcel") -> Usually Zone.
                        }
                    });
                }

                if (!foundParent) {
                    this.ui.showToast(_('ref_line_out_of_bounds'), 'warning');
                    // Remove immediately
                    if (this.featureGroup.hasLayer(layer)) this.featureGroup.removeLayer(layer);
                    if (this.map.hasLayer(layer)) this.map.removeLayer(layer);
                    return; // Stop processing
                }
            }
        }

        // Interaction Binding (Centralized in _processLoadedFeature during reload)


        // 4. Interaction Binding (Toggle Logic - Duplicate Removal)
        // Note: Lines 953-964 in original code were duplicate binding of click event.
        // The block above (lines 846-877 in original context) handles the click logic comprehensively.
        // We should ensure we don't double-bind. 
        // Checking the original code structure:
        //  - 846-877: "if (layer.on) { ... layer.on('click') ... }"
        //  - 953-964: "layer.on('click') ..." (Appears efficiently redundant or separated for flow)
        // 
        // In this replacement, I am targeting the block starting at 846. 
        // Wait, looking at the previous view_file (lines 820-1000):
        //  - Line 846 starts the block.
        //  - Line 953 starts another click handler block? 
        // Let's look closely at the file content from Step 9014.
        // 
        // Line 846: if (layer.on) { layer.on('mousedown')... layer.on('click')... }
        // Line 953: layer.on('click', (e) => { ... })
        // 
        // It seems the original code had TWO click listeners attached to the same layer?
        // The first one (850) handles Merge/Sub and Selection.
        // The second one (953) handles Selection Toggle.
        // 
        // This explains why it was so "strong" - double handling.
        // I should probably consolidate them or just fix the propagation in the FIRST one and remove the second/ensure it respects rule.
        // 
        // However, `replace_file_content` works on a range.
        // The range 846-954 covers BOTH? No, 846 is far above. 
        // 
        // Let's re-read the Plan. The plan was to modify `_onShapeCreated`.
        // The code I viewed in Step 9014 shows the function `_onShapeCreated` spans many lines.
        // 
        // I need to be careful. 
        // The block at 846 is inside the function. 
        // The block at 953 is ALSO inside the function (further down).
        // 
        // I will replace the FIRST block (around 846) to handle the logic correctly.
        // AND I need to handle the SECOND block (around 953).
        // 
        // Actually, the second block (953) seems to be the "Main" selection toggle for some paths?
        // But the first block (850) also has selection logic:
        // "if (this.activeMode === fType) ... _setActiveLayer"
        // 
        // It looks like duplicated logic in the legacy code.
        // 
        // Strategy:
        // I will replace the FIRST block (846) with the correct conditional logic.
        // I will ALSO need to remove or fixing the SECOND block (953).
        // 
        // Let's do this in two steps if they are far apart, or one large step if I can cover it (846 to 964 is ~120 lines).
        // 120 lines is manageable. 
        // 
        // I will replace from line 846 to 964 with a consolidated, clean logic.
        // This is safer and cleans up the double-binding.

        // Wait, does the code between 878 and 952 rely on the first click handler?
        // 881: Marker Interaction
        // 890: Label Tool
        // 906: Area & Auto-Label
        // 942: Side Measurements
        // 947: Auto Save
        // 
        // None of these seem to rely on the *event listener* being attached. They are just setup code.
        // 
        // So I can wrap the event binding in one place.





        // Marker Popup Binding (Centralized in _processLoadedFeature)


        // 1. Label Tool
        if (drawingType === 'label') {
            const text = prompt("Enter Label Text:", "New Label");
            if (!text) {
                window.AoTMapEditor.featureGroup.removeLayer(layer);
                return;
            }
            // Manual label has no auto area
            layer.feature.properties.label_name = text;
            layer.feature.properties.label_area = '';
            layer.feature.properties.aot_type = 'label_aux';

            this._convertToLabel(layer);
            return;
        }

        // 2. Area & Auto-Label for Site/Zone
        if (type === 'site' || type === 'zone') {
            // Guard: Skip for LineString (Split Tools)
            if (layer._aotType === 'Polyline') {
                // Do nothing for lines
            } else {
                let areaDisplay = '';
                try {
                    if (!window.turf) throw new Error("Turf.js not loaded");

                    let geojson = layer.toGeoJSON();
                    // Handle Circle for Area Calc - Pure MapLibre via AoTGeoCircle
                    if (layer._aotType === 'Circle') {
                        const center = layer.getLatLng();
                        const radius = layer.getRadius();
                        geojson = window.turf.circle([center.lng, center.lat], radius, { steps: 16, units: 'meters' });
                    }

                    if (!geojson) throw new Error("Invalid GeoJSON generated");

                    const area = window.turf.area(geojson);
                    areaDisplay = Math.round(area) + ' m²';

                    // Store Area in Parent
                    layer.feature.properties.area = area;

                    // Auto Label
                    this.labels.createAutoLabel(layer, "New " + type, areaDisplay);
 
                } catch (e) {
                    // console.error("Area Calculation Failed:", e);
                    this.labels.createAutoLabel(layer, "New " + type, "0 m²");
                }
            }
        }

        // 3. Side Measurements
        if (type === 'site' || type === 'zone') {
            // Guard in function handles LineStrings, but explicit check here is fine.
            if (this.geometry) this.geometry.updateMeasurementLabels(layer);
        }
 
        // Auto Save
        // console.log("[AutoSave] Shape Created. Saving Design...");
        
        // [Fix] Ensure isLoading is false. If user is drawing, loading must be finished.
        if (this.isLoading) {
             // console.warn("[AutoSave] Forced isLoading=false to allow save.");
             this.isLoading = false;
        }

        const targetType = layer.feature.properties.aot_type || type;
        if (targetType !== this.activeMode) {
            const group = this.layerStorage[targetType];
            if (group && !this.map.hasLayer(group)) {
                this.map.addLayer(group);
            }
        }

        // [Fix] Move Save after processing to ensure feature is in storage
        this.saveDesign([type, 'label_aux'], true);

        // 5. Activate Immediately (New Shape = Active)
        // [Race Condition Fix] Delay activation slightly to ensure it happens AFTER the map click bubbles up.
        setTimeout(() => {
            if (this.map.hasLayer(layer) || this.featureGroup.hasLayer(layer)) {
                this._setActiveLayer(layer);
            }
        }, 100);


        // [New V4] Selective Pipe Logic (Splitting & Connections)
        // [Fix] Enforce Pane for New Shape
        const targetGroup = this.layerStorage[targetType];
        if (targetGroup && targetGroup.options.pane) {
            layer.options.pane = targetGroup.options.pane;
        }

        if (subType && subType.startsWith('pipe')) {
            layer.aot_type = 'equipment'; // Ensure backward compatibility for swap
            if (this.geometry) {
                // 1. Check for selective splitting (80-110 deg elbows)
                const newPipes = this.geometry.processSelectiveSplitting(layer);
                
                if (newPipes && newPipes.length > 0) {
                    // console.log(`[PipeSystem] Pipe split into ${newPipes.length} segments.`);
                    // Process each new segment
                    newPipes.forEach(p => {
                        this._processLoadedFeature(p, type);
                        this.geometry.updatePipeLabels(p);
                    });
                } else {
                    // Not split, process as single pipe (Trimming handled by rebuildConnections)
                    this.geometry.updatePipeLabels(layer);
                }

                // 2. Rebuild Contextual Connections (Scoped Update)
                // [Optimization] Verify only the areas affected by this operation.
                if (newPipes && newPipes.length > 0) {
                    // Rebuild for the first segment's vicinity (usually covers the whole split line)
                    this.geometry.rebuildConnectionsScoped(newPipes[0], newPipes);
                } else {
                    this.geometry.rebuildConnectionsScoped(layer);
                }
            }
        }

        // 6. Update Design Stats
        this.updateDesignInfo();
    }

    // _setActiveLayer logic merged to bottom (deduplicated)

    // _resetActiveLayer moved to bottom (deduplicated)

    handleGeometryOp(op, feature, data = null) {
        if (this.geometry) {
            this.geometry.handleGeometryOp(op, feature, data);
        }
    }






    // --- MERGE / SUBTRACT LOGIC ---



    _resetPendingOp() {
        this.pendingOp = null;
    }

    /* --- Procedural Generation Logic (Called from Panel) --- */
 
    startRefLineDraw() {
        // console.log("[GeoDesign] Starting Reference Line Draw Mode");
        // alert("Click inside the parcel where you want to draw the reference line to start. (double-click to finish)");
        this.pendingOp = { type: 'create_ref_line' }; 
        if (window.AoTMapEditor) {
            window.AoTMapEditor.setType('reference');
            window.AoTMapEditor.startDraw('polyline');
        }
    }
 
    startDrawMainPipe() {
        // console.log("[GeoDesign] Starting Main Pipe Draw Mode");
        this.pendingOp = { type: 'create_main_pipe' };
        if (window.AoTMapEditor) {
            window.AoTMapEditor.setType('equipment');
            window.AoTMapEditor.startDraw('polyline');
        }
    }

    /**
     * Generic wrapper to start drawing from UI Panel
     * @param {string} drawType - 'marker', 'polyline', 'polygon', 'circle'
     * @param {object} options - { type: 'main_pipe', sub_type: ... }
     */
    startDraw(drawType, options = {}) {
        // console.log(`[GeoDesign] startDraw: ${drawType}`, options);
        if (!window.AoTMapEditor) return;

        // Set Context Type if provided
        if (options.type) {
            // Mapping specific types to Editor Context if needed
            // For now, most things fall under 'equipment' or current active mode
            // If options.type is 'ref_line', we might want context 'reference'
            if (options.type === 'ref_line') window.AoTMapEditor.setType('reference');
            else if (options.type === 'main_pipe' || options.type === 'branch_pipe') window.AoTMapEditor.setType('equipment');
            else window.AoTMapEditor.setType(this.activeMode);
        } else {
            // [Fix V21] Ensure we pass a fallback if activeMode is generic
            const mode = this.activeMode || 'site';
            window.AoTMapEditor.setType(mode);
        }

        // [Fix V21-Redux] Reverted setTimeout. Synchronous call is safer for User Event Trusted Context.
        // Race condition was likely Z-Index related (fixed in V20) or Syntax Error (fixed).
        if (window.AoTMapEditor) window.AoTMapEditor.startDraw(drawType, options);
        
        // Store specific signaling for _onShapeCreated
        if (options.type === 'main_pipe') this.pendingOp = { type: 'create_main_pipe' };
        else if (options.type === 'branch_pipe') this.pendingOp = { type: 'create_branch_pipe' };
        else if (options.type === 'ref_line') {
            this.pendingOp = { type: 'create_ref_line' };
        }
        else this.pendingOp = null;

        // console.log(`[GeoDesign] startDraw: ${drawType}, PendingOp:`, this.pendingOp);
    }

    startDrawBranchPipe() {
        // console.log("[GeoDesign] Starting Branch Pipe Draw Mode");
        this.pendingOp = { type: 'create_branch_pipe' };
        if (window.AoTMapEditor) {
            window.AoTMapEditor.setType('equipment'); // Or pipe_branch if style differs? Equipment is fine.
            window.AoTMapEditor.startDraw('polyline');
        }
    }
 
    startDrawValve() {
        // console.log("[GeoDesign] Starting Valve Placement Mode");
        this.pendingOp = { type: 'create_valve' };
        if (window.AoTMapEditor) {
            window.AoTMapEditor.setType('equipment');
            window.AoTMapEditor.startDraw('marker'); // Valves are points
        }
    }
 
    startMainPipeDraw() {
        // console.log("[GeoDesign] Starting Main Pipe Draw Mode");
        if (window.AoTMapEditor) {
            // Set Type to Equipment (pipe_main)
            // Note: AoTMapEditor might need logic to handle sub_type or we rely on _onShapeCreated default.
            // For now, set generic 'equipment' but flagged as main pipe context?
            // Better: Just set 'equipment' and use _onShapeCreated to refine if possible, 
            // OR set a temporary state.
            // Let's rely on Editor type 'equipment' and modifying property post-creation or assuming 'equipment' lines drawn here are mains?
            // Actually, best way is to set Editor type to 'equipment' and maybe a sub-property?
            // AoTMapEditor.setType('equipment'); 

            // Allow drawing polyline.
            window.AoTMapEditor.setType('equipment');
            window.AoTMapEditor.startDraw('polyline');

            // Set Pending Op to tag it?
            this.pendingOp = { type: 'create_main_pipe' };
        }
    }

    async generatePipes(parentFeature, config, opts) {
        if (this.modules) return await this.modules.generatePipes(parentFeature, config, opts);
    }


    generateSprinklers(targetFeature, config, doSave, opts) {
        if (this.modules) this.modules.generateSprinklers(targetFeature, config, doSave, opts);
    }

    clearEquipments(parentFeature, clearMode = 'all') {
        if (this.modules) this.modules.clearEquipments(parentFeature, clearMode);
    }

    async _loadAllFeatures(mapUuid) {
        if (this.isLoading) {
            // console.warn("[Load] Already loading. Skipping request for:", mapUuid);
            return;
        }

        if (!mapUuid || mapUuid === 'null') {
            // console.log("No Map UUID to load.");
            this.isLoading = false;
            return;
        }

        this.isLoading = true;
        this._toggleInteraction(false); // [Fix] Lock Interaction

        // Cancel any stale deferred callbacks from a previous map load
        if (this._deferredRunId) {
            cancelIdleCallback(this._deferredRunId);
            this._deferredRunId = null;
        }
        this._pendingLabelUpdates = [];

        try {
            this._clearLayers();
            window.AoTMapEditor.clear(); // Clear editor's feature group

            // Load overlays. Devices are loaded separately in the finally block
            // to avoid duplicate _renderDevices calls (Promise.all + finally both firing).
            let allFeatures = await window.AoTMapData.loadOverlays(mapUuid);

            if (!allFeatures || allFeatures.length === 0) {
                // console.log("[Load] No features found.");
                return;
            }

            // Silently migrate legacy Leaflet/v1 features loaded from DB.
            // No confirmation dialog — data is already persisted; migration is transparent.
            if (window.AoTGeoMigration) {
                const fc = { type: 'FeatureCollection', features: allFeatures };
                if (AoTGeoMigration.needsMigration(fc)) {
                    allFeatures = AoTGeoMigration.migrate(fc).data.features;
                }
            }

            const loadedNodeIds = new Set();
            const loadedSpatialKeys = new Set();
            const loadedLabelTargets = new Set();

            const validFeatures = allFeatures.filter(f => {
                if (!f || typeof f !== 'object') return false;
                if (!f.type && f.geometry) f.type = 'Feature';
                if (f.type !== 'Feature' || !f.geometry) return false;

                const props = f.properties || {};
                const type = props.aot_type || 'feature';

                // 1. Node ID Deduplication
                if (props.node_id) {
                    if (loadedNodeIds.has(props.node_id)) return false;
                    loadedNodeIds.add(props.node_id);
                }

                // 2. Spatial Deduplication (Equipment/Sprinklers)
                if (f.geometry.coordinates) {
                    const coords = f.geometry.coordinates;
                    let key = `${type}_${props.sub_type || ''}`;

                    if (f.geometry.type === 'Point') {
                        key += `_${coords[0].toFixed(6)}_${coords[1].toFixed(6)}`;
                    } else if (f.geometry.type === 'LineString') {
                        key += `_${coords[0][0].toFixed(6)}_${coords[0][1].toFixed(6)}`;
                    } else if (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') {
                        const first = (f.geometry.type === 'Polygon') ? (coords[0] && coords[0][0]) : (coords[0] && coords[0][0] && coords[0][0][0]);
                        if (first) key += `_${first[0].toFixed(6)}_${first[1].toFixed(6)}`;
                    }

                    if (['equipment', 'sprinkler'].includes(type) || props.aot_type === 'equipment') {
                        if (loadedSpatialKeys.has(key)) return false;
                        loadedSpatialKeys.add(key);
                    }
                }

                // 3. Label Deduplication
                if (type === 'label_aux') {
                    const parentTarget = props.label_for;
                    if (parentTarget && loadedLabelTargets.has(parentTarget)) return false;
                    if (parentTarget) loadedLabelTargets.add(parentTarget);
                }

                // 4. Device Filter
                // [Fix] Block Point features that have a device_id (Ghost Markers).
                // BUT Allow if it's a Circle (saved as Point+Radius).
                if (props.device_id && f.geometry.type === 'Point') {
                    if (props.is_circle) return true; 
                    return false;
                }
                
                // Legacy Block for explicit types (ensure we don't load old markers either)
                if (type === 'aot_device' || type === 'device' || (props.type && ['input', 'output', 'function'].includes(props.type))) {
                    // Only block if it is likely a marker (Point) or if we want to block all "device" items
                    // given the "ghost" complaint, let's allow Polygons but block Points for these types too.
                     if (f.geometry.type === 'Point') {
                         if (props.is_circle) return true;
                         return false;
                     }
                }

                // [Fix] Block Point geometry for polygon-type aot_types.
                // Site/Zone/Facility are polygon types — a Point with these types is an old
                // Leaflet-era center marker that must not render as a dot in MapLibre.
                // Exception: is_circle (Point+radius compact circle storage).
                if (['site', 'zone', 'facility'].includes(type) && f.geometry.type === 'Point') {
                    if (props.is_circle) return true;
                    return false;
                }

                // [Fix] Block 'connection' features (Ephemereal).
                // They must be rebuilt by rebuildConnections() to ensure correct state.
                if (type === 'connection' || props.aot_type === 'connection') {
                    return false;
                }

                // [Fix] Block sprinkler center Point markers — only coverage circles render.
                // Non-circle Points with sub_type 'sprinkler' are center dots that must never appear.
                if (f.geometry.type === 'Point' && !props.is_circle &&
                    (props.sub_type === 'sprinkler' || props.aot_type === 'sprinkler')) {
                    return false;
                }

                return true;
            });

            if (validFeatures.length > 0) {
                // Pure MapLibre: Use AoTGeoLayer.fromGeoJSON instead of L.geoJSON
                const loadedLayers = AoTGeoLayer.fromGeoJSON({ type: 'FeatureCollection', features: validFeatures }, {
                    pointToLayer: (feature, latlng) => {
                        if (feature.geometry?.type !== 'Point') return null;

                        const props = feature.properties || {};

                        // AoTGeoCircle is stored as Point+radius — let fromGeoJSON keep the AoTGeoCircle it created
                        if (props.is_circle || props.drawType === 'circle') return null;

                        const isSprinkler = (props.aot_type === 'equipment' && props.sub_type === 'sprinkler') || (props.aot_type === 'sprinkler');
                        const isCoverage = (props.aot_type === 'equipment' && props.sub_type === 'sprinkler_coverage');

                        if (isSprinkler) {
                            return new AoTGeoCircleMarker([latlng.lat, latlng.lng], {
                                radius: 2, color: '#007bff', fillColor: '#007bff', fillOpacity: 1, interactive: false
                            });
                        }
                        if (isCoverage) {
                            return new AoTGeoCircle([latlng.lat, latlng.lng], {
                                radius: props.radius || 10, color: '#007bff', weight: 1, fillOpacity: 0.1, dashArray: '3, 3', interactive: false, renderSteps: 12
                            });
                        }
                        return new AoTGeoMarker([latlng.lat, latlng.lng]);
                    },
                    onEachFeature: (f, l) => {
                        l.feature = l.feature || { type: 'Feature', properties: {} };
                        l.feature.properties = l.feature.properties || {};
                        const type = l.feature.properties.aot_type || 'feature';
                        this._processLoadedFeature(l, type);
                    }
                });

                // [FIX] Add loaded layers to the map and storage - WAIT FOR STYLE
                if (loadedLayers && loadedLayers.length > 0) {
                    
                    // First, set _map on all layerStorage groups so addLayer() can add to MapLibre
                    Object.values(this.layerStorage).forEach(group => {
                        if (group && !group._map) {
                            group._map = this.map;
                        }
                    });
                    
                    // Helper function to add layers once style is ready
                    const addLayersWhenReady = () => {
                        loadedLayers.forEach(layer => {
                            // Skip old Polygon-format circles that _processLoadedFeature
                            // already recovered as AoTGeoCircle and added to storage.
                            // Without this guard, the original AoTGeoPolygon would be added
                            // as a fill GL layer and render as a jagged polygon shape.
                            if (!layer || layer._alreadyHandled) return;
                            // Skip sprinkler_coverage circles — handled by the re-flush block below.
                            // Non-sprinkler circles (site/zone/facility, is_circle=true) must NOT be
                            // skipped here: they fall through to storage.addLayer() which fires doAdd()
                            // and creates their per-instance fill GL layer.
                            const _lp = layer.feature?.properties || {};
                            if (_lp.sub_type === 'sprinkler_coverage') return;
                            // Skip Polylines (pipes/lines): they must go through storage→bucket only.
                            // Falling through to layer.addTo(this.map) on a Polyline would create
                            // a stale per-instance pl-{id} GL layer that shadows the bucket.
                            if (layer._aotType === 'Polyline' ||
                                layer.feature?.geometry?.type === 'LineString' ||
                                layer.feature?.geometry?.type === 'MultiLineString') {
                                const _type = layer.feature?.properties?.aot_type || 'feature';
                                const _storage = this.layerStorage[_type] || this.layerStorage['equipment'];
                                if (_storage && !_storage.hasLayer(layer)) _storage.addLayer(layer);
                                return;
                            }
                            const type = layer.feature?.properties?.aot_type || 'feature';
                            // Add to appropriate storage (this will also add to MapLibre)
                            const storage = this.layerStorage[type] || this.layerStorage['equipment'];
                            if (storage) {
                                storage.addLayer(layer);
                            } else {
                                // Fallback: add directly to map
                                layer.addTo(this.map);
                            }
                        });

                        // [Fix] Re-flush sprinkler coverage circles into the sprinkler-coverage
                        // RenderBucket. Only sub_type==='sprinkler_coverage' circles go through
                        // the bucket; site/zone/facility circles now use per-instance fill layers
                        // (created by doAdd above) and do NOT need re-flushing here.
                        // upsert is keyed by _layerId, so this is idempotent for circles that
                        // were already added to the bucket before style.load fired.
                        if (window.RenderBucket) {
                            Object.values(this.layerStorage).forEach(group => {
                                if (!group || typeof group.eachLayer !== 'function') return;
                                group.eachLayer(lyr => {
                                    if (lyr && lyr._aotType === 'Circle'
                                            && lyr.feature?.properties?.sub_type === 'sprinkler_coverage'
                                            && typeof lyr._toBucketGeoJSON === 'function') {
                                        lyr._map = this.map;
                                        const bucket = window.RenderBucket.get(group, 'sprinkler-coverage');
                                        if (bucket) bucket.upsert(lyr._layerId, lyr._toBucketGeoJSON());
                                    }
                                });
                            });
                        }
                    };
                    
                    // Resolve native MapLibre instance (bypass compat shim which lacks isStyleLoaded)
                    const _nativeForLoad = this.map._originalMap
                        || (this.map.getNativeMap && this.map.getNativeMap())
                        || this.map._mlMap
                        || this.map;
                    // Check if MapLibre style is loaded — use native instance to get isStyleLoaded
                    if (_nativeForLoad && _nativeForLoad.isStyleLoaded && _nativeForLoad.isStyleLoaded()) {
                        addLayersWhenReady();
                    } else if (_nativeForLoad && _nativeForLoad.once) {
                        // Wait for 'load' event on native map
                        _nativeForLoad.once('load', () => {
                            addLayersWhenReady();
                        });
                    } else {
                        // Fallback: add after short delay
                        setTimeout(addLayersWhenReady, 500);
                    }
                }
            }

            // Finalize: Setup Active Mode
            // This will handle moving layers to Editor and ensuring storage groups are visible.
            this._switchLayerContext(null, this.activeMode);

            // Orphan label cleanup is deferred to the finally block (after isLoading = false)
            // so that saveDesign() can run and purge orphan DB rows.

            // Flush deferred label updates in rAF batches (avoids blocking main thread during load)
            if (this._pendingLabelUpdates && this._pendingLabelUpdates.length > 0) {
                const pending = this._pendingLabelUpdates;
                this._pendingLabelUpdates = [];
                const BATCH = 25;
                let idx = 0;
                const flushBatch = () => {
                    const end = Math.min(idx + BATCH, pending.length);
                    for (; idx < end; idx++) {
                        const { l, type: t, targetKey: tk } = pending[idx];
                        if (['site', 'zone'].includes(t) || ['site', 'zone'].includes(tk)) {
                            this.geometry.updateMeasurementLabels(l);
                        }
                        this.geometry.updatePipeLabels(l);
                    }
                    if (idx < pending.length) requestAnimationFrame(flushBatch);
                };
                requestAnimationFrame(flushBatch);
            }

            // Update Design Info (idle callback — won't block first frame)
            const runDeferred = () => {
                if (this.geometry) this.geometry.recalculateSpatialRelationships();
                this.updateDesignInfo();
            };
            if (typeof requestIdleCallback !== 'undefined') {
                this._deferredRunId = requestIdleCallback(() => {
                    this._deferredRunId = null;
                    runDeferred();
                }, { timeout: 2000 });
            } else {
                setTimeout(runDeferred, 500);
            }

        } finally {
            // [Fix] Release isLoading BEFORE slow background tasks
            // This allows saves (ghost prevention now handled by Interaction Overlay)
            this.isLoading = false;
            this._toggleInteraction(true); // Unlock Interaction

            // Cleanup orphan labels after isLoading = false so saveDesign can purge DB rows.
            if (this.labels) this.labels.cleanupOrphanLabels();

            // [New] Ensure Layer Order (Editor Group on Top)
            this._enforceLayerOrder();

            // [New] Load Map Devices (Real Devices linked via location) as background task
            this._loadMapDevices(mapUuid);

            // Process a pending map switch that was queued while this load was running.
            // Use setTimeout(0) so the current call stack (finally + any .then handlers)
            // finishes before the new loadMap starts, ensuring isLoading is false.
            if (this._pendingMapLoad) {
                const pending = this._pendingMapLoad;
                this._pendingMapLoad = null;
                setTimeout(() => this.loadMap(pending.uuid, pending.name, pending.state), 0);
            }
        }
    }

    // _setActiveLayer moved to bottom (deduplicated)

    // [Extracted] _convertToLabel moved to aot-geo-label.js
    // [Extracted] _renameLabel moved to aot-geo-label.js
    // [Extracted] _applyLabelRename moved to aot-geo-label.js
    // [Extracted] _updateLabelIcon moved to aot-geo-label.js
    // [Extracted] _createAutoLabel moved to aot-geo-label.js

    // --- Auto Save State ---

    _autoSaveState() {
        if (!this.currentMapUuid || this.isLoading) return;

        const state = {
            center: this.map.getCenter(),
            zoom: this.map.getZoom(),
            activeMode: this.activeMode,
            visibleLayers: [],
            active_overlays: [],
            active_base_layer: null
        };

        // Track Visible Layers (Storage)
        Object.keys(this.layerStorage).forEach(key => {
            if (this.map.hasLayer(this.layerStorage[key])) {
                state.visibleLayers.push(key);
            }
        });

        // Track Standard Overlays
        if (this.overlayMaps) {
            Object.entries(this.overlayMaps).forEach(([n, l]) => {
                if (this.map.hasLayer(l)) state.active_overlays.push(n);
            });
        }

        // Track Base Layer
        if (this.baseMaps) {
            Object.entries(this.baseMaps).forEach(([n, l]) => {
                if (this.map.hasLayer(l)) state.active_base_layer = n;
            });
        }

        // Use Data Module to Save
        window.AoTMapData.saveMapDesign(this.currentMapUuid, this.currentMapName, state)
            .then(() => {
                // console.log("[AutoSave] View State Saved");
            })
            .catch(e => { /* console.warn("[AutoSave] View State Warning:", e); */ });
    }

    _debounce(func, wait) {
        let timeout;
        return function (...args) {
            const context = this;
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(context, args), wait);
        };
    }

    /* Actions */

    loadMap(uuid, name, state) {
        if (this.isLoading) {
            // Queue: only keep the most recent pending request so rapid clicks
            // converge on the map the user actually wants.
            this._pendingMapLoad = { uuid, name, state };
            return;
        }

        // Guard against stale loadMapDesign responses when the user switches
        // maps rapidly.  Each loadMap call stamps a unique token; the fetch
        // callback aborts if a newer loadMap has already started.
        const loadToken = (this._loadToken = (this._loadToken || 0) + 1);

        this.currentMapUuid = uuid;
        this.currentMapName = name || _('design_map_new');
        this.lastLoadedName = this.currentMapName.trim();

        // [Fix] Persist Last Opened Map Preference
        if (uuid) {
            localStorage.setItem('aot_last_map_uuid', uuid);
        }

        // Helper to apply full state
        const applyFullState = (s) => {
            // 1. Center/Zoom (Immediate feedback)
            if (s.center && s.zoom) {
                const c = Array.isArray(s.center)
                    ? { lng: s.center[1], lat: s.center[0] }
                    : s.center;
                this.map.jumpTo({ center: [c.lng, c.lat], zoom: s.zoom });
            }

            // 2. Load Data first, THEN Apply Mode/Layers
            this._loadAllFeatures(uuid).then(() => {
                // console.log("[Load] Features Loaded. Restoring State (Mode/Layers)...");
                this._applyState(s);
                // Force Update UI Counters (Repair Data first)
                this._repairLoadedData();
                // Equipment GL layers now exist — apply correct zoom-based visibility.
                // applyInitialZoom() ran at map 'load' before layers were created, so
                // equipment was never hidden. Re-apply now that layers are present.
                this._reapplyZoomVisibility();

                // [Fix] Force 'Site' mode entry on load to ensure UI tools are ready
                setTimeout(() => {
                    this.setMode('site');
                }, 500);

                // [FAILSAFE] 1000ms after load: scan all storage groups and featureGroup,
                // directly add any missing layer to the native MapLibre map.
                // This catches layers whose doAdd was skipped due to timing/ordering issues.
                setTimeout(() => {
                    const nativeMap = (this.map && this.map._originalMap) || this.map;
                    if (!nativeMap || !nativeMap.isStyleLoaded || !nativeMap.isStyleLoaded()) return;

                    const allLayers = [];
                    Object.values(this.layerStorage).forEach(g => g && g.getLayers && g.getLayers().forEach(l => allLayers.push(l)));
                    if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
                        window.AoTMapEditor.featureGroup.getLayers().forEach(l => allLayers.push(l));
                    }

                    let added = 0, existing = 0;
                    allLayers.forEach(layer => {
                        const layerId = layer._layerId;
                        const feature = layer.feature;
                        if (!layerId || !feature || !feature.geometry) return;

                        // DOM markers (AoTGeoMarker) are managed separately — skip GL layer creation
                        if (layer._aotType === 'Marker') return;

                        const sourceId = 'aot-source-' + layerId;
                        const geomType = feature.geometry.type;
                        if (geomType === 'Point') return; // skip stray point features

                        const mlLayerType = (geomType === 'LineString' || geomType === 'MultiLineString') ? 'line' : 'fill';
                        const paintProps = mlLayerType === 'line'
                            ? { 'line-color': '#3388ff', 'line-width': 2 }
                            : { 'fill-color': '#3388ff', 'fill-opacity': 0.3, 'fill-outline-color': '#3388ff' };

                        try {
                            if (!nativeMap.getSource(sourceId)) {
                                nativeMap.addSource(sourceId, { type: 'geojson', data: feature });
                            }
                            if (!nativeMap.getLayer(layerId)) {
                                nativeMap.addLayer({ id: layerId, type: mlLayerType, source: sourceId, paint: paintProps });
                                // Restore cached style instead of leaving hardcoded blue
                                if (layer._styleCache && Object.keys(layer._styleCache).length > 0) {
                                    layer.setStyle(layer._styleCache);
                                }
                                added++;
                            } else {
                                existing++;
                            }
                        } catch(e) {
                            console.warn('[FAILSAFE] Error adding layer', layerId, e.message);
                        }
                    });
                    // Any newly-added layers (and setStyle calls above) reset visibility to
                    // 'visible'. Re-apply the correct zoom-based state.
                    this._reapplyZoomVisibility();
                }, 1000);
            });
        };

        // 1. Load View State
        if (state) {
            applyFullState(state);
            this._updateUIHeader();
        } else {
            // Updated: loadMapDesign now returns {uuid, name, state}
            window.AoTMapData.loadMapDesign(uuid).then(resp => {
                // Stale response: a newer loadMap() already started — discard.
                if (this._loadToken !== loadToken) return;

                const s = resp.state || {}; // Extract state
                const n = resp.name || _('design_map_new'); // Extract name

                // Update Name State from DB
                this.currentMapName = n;
                this.lastLoadedName = n;

                applyFullState(s);
                this._updateUIHeader();
            }).catch(err => {
                // Stale response: discard silently.
                if (this._loadToken !== loadToken) return;

                // 404 = map was deleted — do not auto-recreate it
                const isNotFound = err && err.message && err.message.includes('NOT FOUND');
                if (isNotFound) {
                    localStorage.removeItem('aot_last_map_uuid');
                    this.ui.showToast(_('map_not_found') || 'Map not found', 'warning');
                    applyFullState({});
                    return;
                }

                // Any other failure (timeout, 5xx, a transient network blip — e.g.
                // during a backend restart) is NOT proof this design was never
                // saved. Treating every non-404 error as "first access" and
                // auto-saving a blank state here used to wipe a live farm's
                // design map: a few seconds of backend downtime made the fetch
                // fail, and this handler silently persisted an empty design over
                // real content. Never auto-save on a load failure — leave
                // whatever is already on screen untouched and let the user retry.
                console.error('[GeoDesign] Failed to load design for', uuid, err);
                this.ui.showToast(_('map_load_failed') || 'Failed to load the map. Please retry.', 'error');
            });
        }
    }

    _applyState(state) {
        if (!state) return;

        // 1. Center & Zoom
        if (state.center && state.zoom) {
            const c = Array.isArray(state.center)
                ? { lng: state.center[1], lat: state.center[0] }
                : state.center;
            this.map.jumpTo({ center: [c.lng, c.lat], zoom: state.zoom });
        }

        // 2. Active Mode
        // [Fix] Always default to 'site' mode on load per user request
        /*
        if (state.activeMode && state.activeMode !== this.activeMode) {
            this.setMode(state.activeMode);
        }
        */

        // 3. Locked/Hidden
        if (state.locked !== undefined && state.locked !== this.isLocked) this.toggleLock();
        if (state.hidden !== undefined && state.hidden !== this.isHidden) this.toggleHide();

        // 4. Base Layer
        let restoredBase = null;

        // [Fix] Try ID-based restoration first (Stable)
        if (state.active_base_id && this.baseMaps) {
             Object.values(this.baseMaps).forEach(l => {
                 if ((l.aot_base_id === state.active_base_id) || (l.aot_id === state.active_base_id)) {
                     restoredBase = l;
                 }
             });
        }

        // Fallback to Name-based restoration
        if (!restoredBase && state.active_base_layer && this.baseMaps[state.active_base_layer]) {
            restoredBase = this.baseMaps[state.active_base_layer];
        }

        if (restoredBase) {
            // Ensure we don't stack base layers if possible (remove others?)
            // For now, just add it. Leaflet control handles the radio button state update.
            if (!this.map.hasLayer(restoredBase)) this.map.addLayer(restoredBase);
        }

        // 5. Visible Layers (Storage Groups)
        if (state.visibleLayers) {
            Object.keys(this.layerStorage).forEach(key => {
                const group = this.layerStorage[key];

                // [Fix] Always ensure label_aux is visible (it contains dynamic measurement labels)
                // Visibility of individual labels is controlled by their parent's Add/Remove events.
                if (key === 'label_aux') {
                    if (!this.map.hasLayer(group)) this.map.addLayer(group);
                    return;
                }

                if (state.visibleLayers.includes(key)) {
                    if (!this.map.hasLayer(group)) this.map.addLayer(group);
                } else {
                    if (this.map.hasLayer(group)) this.map.removeLayer(group);
                }
            });
        }

        // 6. Active Overlays (Standard Maps like Cadastral) - Decoupled from visibleLayers
        if (state.active_overlays && this.overlayMaps) {
            Object.entries(this.overlayMaps).forEach(([name, layer]) => {
                // Check if it should be on
                if (state.active_overlays.includes(name)) {
                    if (!this.map.hasLayer(layer)) this.map.addLayer(layer);
                } else {
                    if (this.map.hasLayer(layer)) this.map.removeLayer(layer);
                }
            });
        }
    }

    // [Removed duplicate _loadAllFeatures]

    _clearLayers() {
        const mlMap = this.map && (this.map._originalMap || this.map);

        // 1. Remove GL layers for shapes currently in featureGroup (editor)
        if (window.AoTMapEditor?.featureGroup?.layers) {
            window.AoTMapEditor.featureGroup.layers.forEach(l => {
                if (l._mlDomMarker) { l._mlDomMarker.remove(); l._mlDomMarker = null; }
                if (mlMap && l._layerId) {
                    const lid = l._layerId, sid = 'aot-source-' + lid;
                    try { if (mlMap.getLayer && mlMap.getLayer(lid)) mlMap.removeLayer(lid); } catch(e) {}
                    try { if (mlMap.getSource && mlMap.getSource(sid)) mlMap.removeSource(sid); } catch(e) {}
                }
            });
        }

        // 2. Clear Storage (removes GL layers + DOM markers via updated clearLayers())
        Object.keys(this.layerStorage).forEach(k => {
            this.layerStorage[k].clearLayers();
            if (this.map.hasLayer(this.layerStorage[k])) {
                this.map.removeLayer(this.layerStorage[k]);
            }
        });

        // 3. Clear Editor references (array + drawManager, GL already removed above)
        if (window.AoTMapEditor) window.AoTMapEditor.clear();
    }

    // [New] Pan to Shape (for UI Links)
    panToShape(nodeId) {
        if (!nodeId) return;
        let targetLayer = null;

        // Search in Storage
        const keys = Object.keys(this.layerStorage);
        for (const key of keys) {
            this.layerStorage[key].eachLayer(l => {
                if (l.feature?.properties?.node_id === nodeId) targetLayer = l;
            });
            if (targetLayer) break;
        }

        // Search in Editor
        if (!targetLayer && window.AoTMapEditor.featureGroup) {
            window.AoTMapEditor.featureGroup.eachLayer(l => {
                if (l.feature?.properties?.node_id === nodeId) targetLayer = l;
            });
        }

        if (targetLayer) {
            // [New] Scroll Feature: Bring Map to Viewport
            if (this.map.getContainer()) {
                this.map.getContainer().scrollIntoView({ behavior: 'smooth', block: 'center' });
            }

            // activate it
            this._setActiveLayer(targetLayer);

            // Pan/Zoom (MapLibre API)
            if (targetLayer.getBounds) {
                const b = targetLayer.getBounds();
                if (b && b.isValid && b.isValid()) {
                    const sw = b.getSouthWest(), ne = b.getNorthEast();
                    this.map.fitBounds([[sw.lng, sw.lat], [ne.lng, ne.lat]], { padding: 50, maxZoom: 20 });
                }
            } else if (targetLayer.getLatLng) {
                const ll = targetLayer.getLatLng();
                this.map.flyTo({ center: [ll.lng, ll.lat], zoom: 20, duration: 0.5 });
            }
        } else {
             // console.warn("Feature not found:", nodeId);
        }
    }

    _updateUIHeader() {
        const titleEl = document.querySelector('.geo-design-header .design-title');
        // Update Selector if exists
        const selector = document.getElementById('map-selector');
        
        if (titleEl) titleEl.textContent = this.currentMapName;
        if (selector && this.currentMapUuid) {
             $(selector).selectpicker('val', this.currentMapUuid);
        }
    }

    // --- Mode Panel Interaction ---
    switchMode(mode) {
        if (this.isLocked) return;
        this.setMode(mode);
    }

    /* Auto Save System */


    /* Legacy Support for External Calls */
    _switchLayerContext(oldMode, newMode) {
        // Handled in setMode -> _swapStorageLayers
        this._swapStorageLayers(oldMode, newMode);
    }

    /* --- Final Initialization --- */
    _swapStorageLayers(oldMode, newMode) {
        if (this._isSwappingModes) return;
        this._isSwappingModes = true;

        try {
            // 1. Teardown Old Mode: Move from Editor to Storage
            if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
                const activeLayers = window.AoTMapEditor.featureGroup.getLayers();
                
                activeLayers.forEach(l => {
                // [Fix] Access properties.aot_type if direct aot_type is missing
                const type = l.aot_type || l.feature?.properties?.aot_type;
                const props = l.feature?.properties;

                // [Fix] Device Handling (Special Case)
                if (type === 'device' || type === 'aot_device') {
                    // 색은 테마에서 계산만 하고 도형에 각인하지 않는다(props.color 금지).
                    // 각인하면 그 값이 DB feature JSON 에 저장돼, 이후 테마를 바꿔도
                    // 이 도형만 옛 색으로 남는다.
                    const shapeColor = window.AoTGeoTheme.deviceColor(props.device_type);
                    if (l.setStyle) {
                        l.setStyle({ color: shapeColor, fillColor: shapeColor });
                    }
                    // [Fix] Link to Device Logic?
                    if (this.devices && this.devices.isDeviceOnMap(props.unique_id)) {
                        // Maybe update marker?
                    }
                    if (this.layerStorage['device']) {
                        this.layerStorage['device'].addLayer(l);
                    }
                }
                // Equipment Sub-types
                else if (type === 'equipment' || type === 'pipe_branch' || type === 'sprinkler') {
                    if (this.layerStorage['equipment']) {
                        this.layerStorage['equipment'].addLayer(l);
                    }
                }
                // Default: Move to Old Mode Storage (Site/Zone/etc)
                else {
                    const targetKey = type || oldMode;
                    const storage = this.layerStorage[targetKey] || this.layerStorage[oldMode] || this.layerStorage['site'];
                    if (storage) {
                        storage.addLayer(l);
                    }
                    this.ui._setLayerStyle(l, false);
                }
                });
                window.AoTMapEditor.clear(); // Clear Editor
            }

            // 2. Setup New Mode: Move from Storage to Editor
            if (newMode && this.layerStorage[newMode] && newMode !== 'aot_device') {
                const storageGroup = this.layerStorage[newMode];

                // Remove visual group from map if present
                if (this.map.hasLayer(storageGroup)) {
                    this.map.removeLayer(storageGroup);
                }

                // Move from Storage to Editor (Editable)
                // [Fix] Only clear if we are NOT in initial loading phase (where Editor might have been populated)
                // Actually, with the _processLoadedFeature fix, we can always clear safely.
                window.AoTMapEditor.clear();

                const layers = Array.from(storageGroup.getLayers());
                const mlMap = this.map._originalMap || this.map;

                layers.forEach(l => {
                    l._map = this.map;
                    // Use featureGroup.addLayer() which routes through AoTGeoLayer.addTo(),
                    // preserving cached styles and handling Markers as DOM elements.
                    if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
                        window.AoTMapEditor.featureGroup.addLayer(l);
                    }
                    // Re-apply the correct inactive style (preserves layer colors from load)
                    if (this.ui && this.ui._setLayerStyle) {
                        this.ui._setLayerStyle(l, false);
                    }
                });

                // Clear storage reference only — GL layers are now owned by featureGroup,
                // so we must NOT call clearLayers() which would remove GL layers from the map.
                storageGroup._layers.clear();
            }

            // [Fix] Device Shape Handling (Multi-Key)
            // If newMode is 'aot_device', we ALSO need to move 'device' shapes to Editor
            if (newMode === 'aot_device' && this.layerStorage['device']) {
                 const devGroup = this.layerStorage['device'];
                 if (this.map.hasLayer(devGroup)) this.map.removeLayer(devGroup);
                 
                 const layers = Array.from(devGroup.getLayers());
                 layers.forEach(l => {
                     window.AoTMapEditor.featureGroup.addLayer(l);
                     this.ui._setLayerStyle(l, true); // Active
                 });
                 devGroup._layers.clear(); // reference only — GL layers owned by featureGroup
            }

            // [New] Reference Line Editing in Equipment Mode
            // Allow Reference Lines to be edited/deleted when in 'equipment' mode (for Pipe drawing)
            if (newMode === 'equipment' && this.layerStorage['reference']) {
                 const refGroup = this.layerStorage['reference'];
                 if (this.map.hasLayer(refGroup)) this.map.removeLayer(refGroup);

                 const layers = Array.from(refGroup.getLayers());
                 layers.forEach(l => {
                     window.AoTMapEditor.featureGroup.addLayer(l);
                     this.ui._setLayerStyle(l, true);
                 });
                 refGroup._layers.clear(); // reference only — GL layers owned by featureGroup
            }

        } catch (e) {
            console.error("[AoTGeoDesign] Error during layer swap:", e);
        } finally {
            try {
                // 3. Finalize Map Layers (Ensure correct Storage Group visibility)
                Object.keys(this.layerStorage).forEach(key => {
                    const group = this.layerStorage[key];
                    if (!group) return;

                    // Active Mode Storage should be OFF the map (Editor handles it)
                    // Exception: 'aot_device' keeps markers in storage as reference
                    // Special Fix: 'aot_device' mode ALSO uses 'device' storage in Editor
                    const isActiveStorage = (key === newMode && key !== 'aot_device') 
                        || (newMode === 'aot_device' && key === 'device');

                    if (isActiveStorage) {
                        if (this.map.hasLayer(group)) {
                            this.map.removeLayer(group);
                        }
                    } else {
                        // Passive Storage Groups should be ON the map
                        if (!this.map.hasLayer(group)) {
                            this.map.addLayer(group);
                        }
                        // Refresh style for the new context (Active -> Passive)
                        // Wrap individually to prevent loop crash
                        group.eachLayer(l => { try { this.ui._setLayerStyle(l, false); } catch(errStyle){} });
                    }
                });

                // Always Ensure Labels are Visible (Read Only)
                if (!this.map.hasLayer(this.layerStorage['label_aux'])) {
                    this.map.addLayer(this.layerStorage['label_aux']);
                }

                // 4. Enforce Z-Order (Critical for Selection Priority)
                this._enforceLayerOrder();
            } catch (ex) {
                console.error("[AoTGeoDesign] Error prioritizing layers:", ex);
            }

            this._isSwappingModes = false; // Unlock
        }
    }

    saveDesign(targetTypes = null, isAutoSave = false) {
        if (this.isLoading) return Promise.resolve();

        // [Fix] Pending Save Mechanism (Throttle)
        if (this.isSaving) {
            // console.log("[GeoDesign] Save already in progress. Marking for pending save...");
            this.hasPendingSave = true;
            return Promise.resolve();
        }
        this.isSaving = true;
        this.hasPendingSave = false;

        const saveBtn = document.getElementById('btn-save-global');
        if (saveBtn) saveBtn.disabled = true;

        // 1. Gather Map State
        const activeOverlays = [];
        if (this.overlayMaps) {
            Object.entries(this.overlayMaps).forEach(([n, l]) => { if (this.map.hasLayer(l)) activeOverlays.push(n); });
        }

        let activeBase = null;
        if (this.baseMaps) {
            Object.entries(this.baseMaps).forEach(([n, l]) => { if (this.map.hasLayer(l)) activeBase = n; });
        }

        const state = {
            center: this.map.getCenter(),
            zoom: this.map.getZoom(),
            locked: this.isLocked,
            hidden: this.isHidden,
            active_overlays: activeOverlays,
            active_base_layer: activeBase
            // 지도별 theme_config 는 더 이상 쓰지 않는다. 예전에는 이 자리에
            // "그 세션에서 만진 색만 담긴 부분 dict"가 저장됐고, AoT_map 위젯이
            // 그 값을 전역 테마 위에 덮어써서(geo/widget/maps.py) 그 지도만
            // 옛 색으로 굳었다 — 전역을 아무리 바꿔도 바뀌지 않았다.
            // 정본은 GeoSetting.theme_config 하나뿐이다.
        };

        const currentName = this.currentMapName.trim();

        // 2. Save Map State (First)
        return window.AoTMapData.saveMapDesign(this.currentMapUuid, currentName, state)
            .then(res => {
                if (!res.ok) throw new Error(res.message || "Map Save Failed");
                
                const isNew = !this.currentMapUuid;
                if (isNew && res.uuid) {
                    this.currentMapUuid = res.uuid;
                    localStorage.setItem('aot_last_map_uuid', this.currentMapUuid);
                }

                // 3. Collect and Process Features
                const allFeatures = [];
                const savedIds = new Set();

                const collectLayer = (l, forcedType) => {
                    l.feature = l.feature || { type: 'Feature', properties: {} };
                    l.feature.properties = l.feature.properties || {};

                    // [Fix] Respect no_save flag (e.g. Dynamic Length Labels, Connection Dots)
                    if (l.feature.properties.no_save) return;

                    if (forcedType && (!l.feature.properties.aot_type || l.feature.properties.aot_type === 'feature')) {
                        l.feature.properties.aot_type = forcedType;
                    }

                    // Circle-to-Polygon conversion - Pure MapLibre via AoTGeoCircle
                    if (l._aotType === 'Circle') {
                        const currentType = l.feature.properties.aot_type || forcedType;
                        const isDevice = (currentType === 'device' || currentType === 'aot_device' || l.feature.properties.device_id);
                        if (window.turf) {
                            const center = l.getLatLng();
                            const radius = l.getRadius();
                            if (isDevice) {
                                l.feature.geometry = { type: 'Point', coordinates: [center.lng, center.lat] };
                            } else {
                                const polyGeo = window.turf.circle([center.lng, center.lat], radius, { steps: 16, units: 'meters' });
                                l.feature.geometry = polyGeo.geometry;
                            }
                            l.feature.properties.is_circle = true;
                            l.feature.properties.radius = radius;
                            // [Perf] Persist center so reload reconstructs as L.Circle without turf.centroid fallback.
                            l.feature.properties.center_lat = center.lat;
                            l.feature.properties.center_lng = center.lng;
                        }
                    } else if (l.toGeoJSON) {
                        l.feature.geometry = l.toGeoJSON().geometry;
                    }

                    const geom = l.feature.geometry;
                    if (!geom) return;

                    // Validation
                    if (window.turf) {
                        try {
                            const gType = geom.type;
                            if (gType === 'Polygon' || gType === 'MultiPolygon') {
                                if (window.turf.area(l.feature) < 0.01) return;
                                if (window.turf.kinks(l.feature).features.length > 0) return;
                            } else if (gType === 'LineString' && window.turf.length(l.feature, { units: 'meters' }) < 0.1) {
                                return;
                            }
                        } catch (e) { }
                    }

                    const nodeId = l.feature.properties.node_id;
                    if (nodeId) {
                        if (savedIds.has(nodeId)) return;
                        savedIds.add(nodeId);
                    }

                    allFeatures.push(l);
                };

                // Collect from Storage and Editor
                Object.keys(this.layerStorage).forEach(key => {
                    this.layerStorage[key].eachLayer(l => collectLayer(l, key));
                });
                if (window.AoTMapEditor) {
                    window.AoTMapEditor.featureGroup.eachLayer(l => {
                        let mode = this.activeMode;
                        if (mode === 'aot_device') {
                            if (l._aotType === 'Marker' && l.feature?.properties?.unique_id) return;
                            mode = 'device';
                        }
                        collectLayer(l, mode);
                    });
                }

                // 4. Delta or Full Sync Overlays
                if (isAutoSave && !isNew) {
                    const snapshotDirtyIds = new Set(this.dirtyNodeIds);
                    const snapshotDeletedIds = new Set(this.deletedNodeIds);

                    const upserts = allFeatures
                        .filter(l => snapshotDirtyIds.has(l.feature.properties.node_id))
                        .map(l => l.feature);

                    if (upserts.length === 0 && snapshotDeletedIds.size === 0) return { ok: true };

                    return window.AoTMapData.saveDelta(this.currentMapUuid, {
                        upserts: upserts,
                        deletes: Array.from(snapshotDeletedIds)
                    }).then(deltaRes => {
                        if (deltaRes.ok && deltaRes.id_map) {
                            const updateIds = (group) => {
                                group.eachLayer(l => {
                                    const nid = l.feature?.properties?.node_id;
                                    if (nid && deltaRes.id_map[nid]) l.feature.properties.db_id = deltaRes.id_map[nid];
                                });
                            };
                            Object.values(this.layerStorage).forEach(updateIds);
                            if (window.AoTMapEditor?.featureGroup) updateIds(window.AoTMapEditor.featureGroup);
                        }
                        
                        // [Fix] Robust Clearing: Remove only processed IDs
                        // Prevent clearing new changes that happened during the save request
                        upserts.forEach(f => this.dirtyNodeIds.delete(f.properties.node_id));
                        snapshotDeletedIds.forEach(id => this.deletedNodeIds.delete(id));
                        
                        return deltaRes;
                    });
                } else {
                    const categorized = {};
                    allFeatures.forEach(l => {
                        const type = l.feature.properties.aot_type || 'feature';
                        if (!categorized[type]) categorized[type] = [];
                        categorized[type].push(l.feature);
                    });

                    const savePromises = [];
                    // [Fix] Exclude 'aot_device' from typesToSync.
                    // Device marker locations are managed exclusively by /api/geo/device/location
                    // (GeoDeviceLocation.post). Including 'aot_device' here would call
                    // saveOverlays(mapUuid, 'aot_device', []) — an empty list causes ALL
                    // device GeoShape records to be deleted (delta-sync treats missing = deleted).
                    const typesToSync = targetTypes || ['site', 'zone', 'infra_blob', 'facility', 'equipment', 'label_aux', 'device', 'reference'];
                    // [I9] Deletions must be sent EXPLICITLY. The server no longer
                    // treats "absent from payload" as a deletion — a client that
                    // loses a db_id used to wipe and re-create whole zones, severing
                    // every device membership (2026-08-03). The same list goes to
                    // every type; the server only matches within each type's scope.
                    const explicitDeletes = Array.from(this.deletedNodeIds);
                    typesToSync.forEach(type => {
                        // This full-sync path is authoritative: saveDesign() bails early while
                        // this.isLoading is true, so by here overlays have finished loading and an
                        // empty category genuinely means "user deleted them all" — not a race.
                        // Pass allowEmpty so the server's empty-wipe guard permits the clear;
                        // without it, deleting the last shape of a type would be blocked and
                        // reappear on refresh.
                        savePromises.push(window.AoTMapData.saveOverlays(
                            this.currentMapUuid, type, categorized[type] || [],
                            { allowEmpty: true, deletes: explicitDeletes }));
                    });

                    // [Fix] Orphan aot_device shapes (drawn in device mode without a linked
                    // device — no device_id) are NOT covered by typesToSync's full-replace:
                    //   - 'aot_device' is excluded (would clobber device-marker GeoShapes).
                    //   - They can't ride the 'device' overlay either: their DB rows are
                    //     type='aot_device', but saveOverlays('device') only replaces type='device'
                    //     rows, so an edit would insert a duplicate type='device' row and leave
                    //     the original type='aot_device' row behind (the before/after orphan bug).
                    // Persist their edits (upsert by node_id) and deletes via the delta endpoint,
                    // which matches existing rows by node_id and updates in place — no duplicates.
                    const orphanUpserts = allFeatures
                        .filter(l => {
                            const p = l.feature?.properties || {};
                            return p.aot_type === 'aot_device' && !p.device_id && p.node_id
                                && this.dirtyNodeIds.has(p.node_id);
                        })
                        .map(l => l.feature);
                    const orphanDeletes = Array.from(this._deferredAotDeviceNids || []);

                    return Promise.all(savePromises).then(results => {
                        results.forEach(res => {
                            if (res.id_map) {
                                Object.values(this.layerStorage).forEach(group => {
                                    group.eachLayer(l => {
                                        const nid = l.feature?.properties?.node_id;
                                        if (nid && res.id_map[nid]) l.feature.properties.db_id = res.id_map[nid];
                                    });
                                });
                            }
                        });

                        // Full sync (manual save) clears everything as it sends full state
                        this.dirtyNodeIds.clear();
                        this.deletedNodeIds.clear();
                        this._deferredAotDeviceNids = null;

                        if ((orphanUpserts.length || orphanDeletes.length) && this.currentMapUuid) {
                            return window.AoTMapData.saveDelta(this.currentMapUuid, {
                                upserts: orphanUpserts, deletes: orphanDeletes
                            }).then(deltaRes => {
                                if (deltaRes && deltaRes.id_map) {
                                    Object.values(this.layerStorage).forEach(group => {
                                        group.eachLayer(l => {
                                            const nid = l.feature?.properties?.node_id;
                                            if (nid && deltaRes.id_map[nid]) l.feature.properties.db_id = deltaRes.id_map[nid];
                                        });
                                    });
                                }
                                return deltaRes;
                            });
                        }

                        return { ok: true };
                    });
                }
            })
            .then(res => {
                // [Fix] Removed global clear here, handled inside blocks above
                if (!isAutoSave) {
                    this.ui.showToast(_('saved_successfully'), 'success');
                    if (!this.currentMapUuid) location.reload();
                    else this._updateUIHeader();
                }
                return res;
            })
            .catch(error => {
                this.ui.showToast(_('save_failed') + ": " + error.message, 'error');
                throw error;
            }).finally(() => {
                if (saveBtn) saveBtn.disabled = false;
                
                // [Fix] Release Lock & Process Pending
                this.isSaving = false;
                if (this.hasPendingSave) {
                    // console.log("[GeoDesign] Processing pending save...");
                    // Recurse with same flags (or default? keeps auto-save context)
                    this.saveDesign(targetTypes, isAutoSave);
                }
            });
    }

    resetDesign() {
        // console.log("[Reset] Starting New Design Map...");
 
        // 1. Reset State
        this.currentMapUuid = null;
        this.currentMapName = "New Design Map";
        this.lastLoadedName = "";
        this.isLoading = false; // [Fix] Ensure immediate interaction
        this._toggleInteraction(true); // Force unlock if stuck

        // 2. Remove GL layers for shapes in featureGroup before clearing references
        const mlMap = this.map && (this.map._originalMap || this.map);
        if (window.AoTMapEditor?.featureGroup?.layers) {
            window.AoTMapEditor.featureGroup.layers.forEach(l => {
                if (l._mlDomMarker) { l._mlDomMarker.remove(); l._mlDomMarker = null; }
                if (mlMap && l._layerId) {
                    const lid = l._layerId, sid = 'aot-source-' + lid;
                    try { if (mlMap.getLayer && mlMap.getLayer(lid)) mlMap.removeLayer(lid); } catch(e) {}
                    try { if (mlMap.getSource && mlMap.getSource(sid)) mlMap.removeSource(sid); } catch(e) {}
                }
            });
        }
        window.AoTMapEditor.clear();

        // 3. Clear Passive Layers (Storage) & Measurement Labels
        Object.keys(this.layerStorage).forEach(key => {
            const group = this.layerStorage[key];

            // Clean up measurement labels attached to layers
            group.eachLayer(layer => {
                if (layer._measurementLabels) {
                    layer._measurementLabels.forEach(l => {
                        if (this.map.hasLayer(l)) this.map.removeLayer(l);
                    });
                    layer._measurementLabels = [];
                }
            });

            group.clearLayers();
        });

        // 4. Clear Stats
        this._updateStats();

        // 5. Section Table Reset
        const tbody = document.querySelector('#site-detail-table tbody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-3">' + _('no_data_table') + '</td></tr>';
        }

        // 6. Update UI
        this._updateUIHeader();

        // 7. Reset Mode to Default (Site)
        this.setMode('site');
 
        // console.log("[Reset] Map Cleared. Ready for new design.");
    }

    _updateStats() {
        // Reset Counters
        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.innerText = val;
        };
        setVal('stat-site-count', '0');
        setVal('stat-zone-count', '0');
        setVal('stat-device-count', '0');
        setVal('stat-total-area', '-');
    }

    _updateUIHeader() {
        // Update Selector Logic
        const sel = $('#map-selector');
        if (this.currentMapUuid) {
            sel.val(this.currentMapUuid);
            // Update option text if name changed
            const opt = sel.find(`option[value="${this.currentMapUuid}"]`);
            if (opt.length) {
                opt.text(this.currentMapName);
            }
        } else {
            sel.val('new');
        }
        sel.selectpicker('refresh');

        // Removed: design-title, design-uuid inputs
    }

    // --- Helper for Cleaning Orphan Labels (Black background error labels) ---
    deleteMap(uuid) {
        window.AoTMapData.deleteMapDesign(uuid)
            .then(() => {
                this.ui.showToast(_('deleted_successfully'), 'success');
                
                // [Fix] Smart Redirect Logic
                const sel = $('#map-selector');
                
                // 1. Remove from UI
                sel.find(`option[value="${uuid}"]`).remove();
                sel.selectpicker('refresh');
                
                // 2. Clear LocalStorage if matched
                if (localStorage.getItem('aot_last_map_uuid') === uuid) {
                    localStorage.removeItem('aot_last_map_uuid');
                }
                
                // 3. Determine Next Step
                // Options: [0]=Placeholder, [1]=New, [2]...=Maps
                // If length > 2, we have other maps.
                const options = Array.from(document.getElementById('map-selector').options);
                const mapOptions = options.filter(opt => opt.value !== 'default' && opt.value !== 'new');
                
                if (mapOptions.length > 0) {
                    // Go to the first available map (or previous if possible, but first is safe)
                    const nextUuid = mapOptions[0].value;
                    // console.log("[Delete] Redirecting to existing map:", nextUuid);
                    window.location.href = `/geo/design?uuid=${nextUuid}`;
                } else {
                    // No maps left -> Clean Slate
                    // console.log("[Delete] No maps left. Redirecting to New.");
                    window.location.href = '/geo/design';
                }
            })
            .catch(err => {
                // console.error("Delete Failed:", err);
                // console.error("[GeoDesign] Delete Failed:", err);
                this.ui.showToast(_('delete_failed') + ": " + err.message, 'error');
            });
    }

    /**
     * Bind Drawing Tools
     */
    _bindDrawEvents() {
        // Infrastructure Tools (Pipe/Sprinkler)
        const bindDraw = (id, type, options = {}) => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('click', (e) => {
                    e.preventDefault();
                    if (window.AoTMapEditor) {
                        // Map 'pipe' to 'LineString', 'sprinkler' to 'Point' (or specialized)
                        let drawMode = 'LineString';
                        let subType = type;

                        if (type === 'sprinkler') {
                            drawMode = 'Circle'; // Or Point? Sprinkler usually has radius.
                            // If logic requires Point, use 'Marker'.
                            // Let's assume Circle for coverage.
                        }

                        // Set Context
                        this.setMode('device'); // Ensure correct mode

                        // Start Draw
                        window.AoTMapEditor.startDraw(drawMode, {
                            aot_type: subType, // 'pipe', 'sprinkler'
                            ...options
                        });
                    }
                });
            }
        };

        bindDraw('tool-draw-pipe', 'pipe');
        bindDraw('tool-draw-sprinkler', 'sprinkler');

        // Zone Split
        const btnSplit = document.getElementById('btn-zone-split');
        if (btnSplit) {
            btnSplit.addEventListener('click', () => {
                this.ui.showToast(_('polygon_split_feature_coming_soon'), 'info');
            });
        }

        // aot:editor:created listener — handles side effects only (color, UI)
        // Save path is handled by draw:created → aot-geo-events.js → _onShapeCreated
        window.addEventListener('aot:editor:created', (e) => {
            const type = e.detail?.aotType;
            const layer = e.detail?.layer;

            if (!layer || !type) return;

            // [Fix] Immediate Color Application for New Device Shapes
            if (type === 'aot_device' && layer.feature && layer.feature.properties) {
                const props = layer.feature.properties;
                let devType = props.device_type;
                if (!devType && this.ui && this.ui.getDeviceSubMode) {
                    devType = this.ui.getDeviceSubMode();
                    props.device_type = devType;
                }
                // 테마에서 계산만 한다 — props.color 로 각인하지 않는다(위 2134 주석).
                const shapeColor = window.AoTGeoTheme.deviceColor(devType);
                if (layer.setStyle) {
                    layer.setStyle({ color: shapeColor, fillColor: shapeColor, fillOpacity: 0.5 });
                }
            }
        });

        // Listen for Leaflet.Draw edits too (Edit/Delete)
        // Listen for Leaflet.Draw edits too (Edit/Delete)
        this.map.on('draw:edited', (e) => {
            this.updateDesignInfo();
            // [Fix] Ensure changes are saved and geometry updated
            if (this.geometry && this.activeMode === 'equipment') this.geometry.rebuildConnections();
            this.saveDesign(null, true);
        });
        
        // [New] Individual Edit Events (Vertex/Move)
        const onRealtimeEdit = (e) => {
             // console.log(`[GeoDesign] Realtime Edit Detected (${e.type})`);
             this.updateDesignInfo();
             
             // Update Metrics for the specific layer if available
             if (e.layer) this._updateShapeMetrics(e.layer);
             else if (e.poly) this._updateShapeMetrics(e.poly);

             if (this.geometry && this.activeMode === 'equipment') this.geometry.rebuildConnections();
             this.saveDesign(null, true);
        };
        this.map.on('draw:editvertex', onRealtimeEdit);
        this.map.on('draw:editmove', onRealtimeEdit);
        this.map.on('draw:editresize', onRealtimeEdit);
        this.map.on('draw:deleted', (e) => {
            this.updateDesignInfo();
            // [Fix] Rebuild connections (remove orphan dots) and Auto Save deletion
            if (this.geometry) this.geometry.rebuildConnections();
            this.saveDesign(null, true);
        });

        // Fallback-mode delete: remove from layerStorage + save
        window.addEventListener('aot:editor:deleted', (e) => {
            const features = e.detail?.features || e.detail?.layers || [];
            const deletedTypes = new Set(this._pendingDeletedTypes || []);
            features.forEach(f => {
                if (!f) return;
                // Prefer node_id / db_id over GeoJSON Feature id (backend expects node_id)
                const nid = f.properties?.node_id || f.properties?.db_id || f.id;
                if (nid) this.deletedNodeIds.add(nid);
                if (f.properties?.aot_type) deletedTypes.add(f.properties.aot_type);
                // Remove from all layerStorage groups
                Object.values(this.layerStorage).forEach(group => {
                    if (!group || !group.eachLayer) return;
                    group.eachLayer(l => {
                        const lnid = l.feature?.properties?.node_id || l.feature?.properties?.db_id || l.feature?.id;
                        if (lnid && lnid === nid) group.removeLayer(l);
                    });
                });
                // Cascade: if a sprinkler head was deleted, also remove its coverage circle
                // Coverage circles share the same parent_node_id (pipe) and position as the head
                if (f.properties?.sub_type === 'sprinkler') {
                    const headCoords = f.geometry?.coordinates;
                    const headParent = f.properties?.parent_node_id;
                    const equipGroup = this.layerStorage['equipment'];
                    if (equipGroup && equipGroup.eachLayer) {
                        const toRemove = [];
                        equipGroup.eachLayer(l => {
                            const props = l.feature?.properties;
                            if (props?.sub_type !== 'sprinkler_coverage') return;
                            // Match by parent_node_id (same pipe) and same position
                            if (headParent && props.parent_node_id !== headParent) return;
                            const coords = l.feature?.geometry?.coordinates;
                            if (headCoords && coords &&
                                Math.abs(coords[0] - headCoords[0]) < 1e-9 &&
                                Math.abs(coords[1] - headCoords[1]) < 1e-9) {
                                toRemove.push(l);
                            }
                        });
                        toRemove.forEach(l => {
                            const cnid = l.feature?.properties?.node_id;
                            if (cnid) this.deletedNodeIds.add(cnid);
                            equipGroup.removeLayer(l);
                        });
                    }
                }
                // Reverse cascade: if a coverage circle was deleted, also remove its sprinkler head
                if (f.properties?.sub_type === 'sprinkler_coverage') {
                    const covCoords = f.geometry?.coordinates;
                    const covParent = f.properties?.parent_node_id;
                    const equipGroup = this.layerStorage['equipment'];
                    const fgGroup = window.AoTMapEditor?.featureGroup;
                    const scanGroup = (group) => {
                        if (!group || !group.eachLayer) return;
                        const toRemove = [];
                        group.eachLayer(l => {
                            const props = l.feature?.properties;
                            if (props?.sub_type !== 'sprinkler') return;
                            if (covParent && props.parent_node_id !== covParent) return;
                            const coords = l.feature?.geometry?.coordinates;
                            if (covCoords && coords &&
                                Math.abs(coords[0] - covCoords[0]) < 1e-9 &&
                                Math.abs(coords[1] - covCoords[1]) < 1e-9) {
                                toRemove.push(l);
                            }
                        });
                        toRemove.forEach(l => {
                            const hnid = l.feature?.properties?.node_id;
                            if (hnid) this.deletedNodeIds.add(hnid);
                            group.removeLayer(l);
                            if (this.map.hasLayer(l)) this.map.removeLayer(l);
                        });
                    };
                    scanGroup(equipGroup);
                    scanGroup(fgGroup);
                }

                // Cascade: remove auto-labels linked by parent_node_id.
                // Labels may be in layerStorage['label_aux'] OR in featureGroup (moved during delete mode).
                if (nid) {
                    const _self = this;
                    const removeLabel = (lbl, grp) => {
                        const lnid = lbl.feature?.properties?.node_id;
                        if (lnid) _self.deletedNodeIds.add(lnid);
                        if (lbl._mlDomMarker) { lbl._mlDomMarker.remove(); lbl._mlDomMarker = null; }
                        if (grp && grp.removeLayer) grp.removeLayer(lbl);
                        if (_self.map.hasLayer(lbl)) _self.map.removeLayer(lbl);
                    };
                    const scanGroup = (grp) => {
                        if (!grp || !grp.eachLayer) return;
                        const found = [];
                        grp.eachLayer(lbl => {
                            if (lbl.feature?.properties?.aot_type === 'label_aux' &&
                                lbl.feature?.properties?.parent_node_id === nid) found.push(lbl);
                        });
                        found.forEach(lbl => removeLabel(lbl, grp));
                    };
                    scanGroup(this.layerStorage['label_aux']);
                    scanGroup(window.AoTMapEditor?.featureGroup);
                }
            });
            this._pendingDeletedTypes = null;
            this.updateDesignInfo();
            if (this.geometry) this.geometry.rebuildConnections();
            // During an active delete session, defer save to saveActions() so cancelActions() can restore.
            if (!window.AoTMapEditor?.deleteEnabled) {
                this.saveDesign(deletedTypes.size ? Array.from(deletedTypes) : null, true);
            } else {
                // [Fix] aot_device deletions cannot be deferred via full save (typesToSync excludes it).
                // Track them separately so saveDesign's full-save path can delta-delete them.
                features.forEach(f => {
                    if (f.properties?.aot_type === 'aot_device') {
                        const nid = f.properties?.node_id || f.properties?.db_id || f.id;
                        if (nid) {
                            this._deferredAotDeviceNids = this._deferredAotDeviceNids || new Set();
                            this._deferredAotDeviceNids.add(nid);
                        }
                    }
                });
            }
        });

        // Fallback-mode edit: save after vertex drag committed
        window.addEventListener('aot:editor:edited', (e) => {
            const features = e.detail?.features || e.detail?.layers || [];
            features.forEach(f => {
                const nid = f?.properties?.node_id;
                if (nid) this.dirtyNodeIds.add(nid);
            });
            this.updateDesignInfo();
            if (this.geometry && this.activeMode === 'equipment') this.geometry.rebuildConnections();
            // During an active edit session, defer save to saveActions() so cancelActions() can revert.
            if (!window.AoTMapEditor?.editEnabled) {
                this.saveDesign(null, true);
            }
        });
    }

    _cleanupOrphanLabels() {
        // console.log("[Cleanup] Checking for orphan labels...");
        const labelGroup = this.layerStorage['label_aux'];
        if (!labelGroup) return;

        // 1. Collect Valid Parent IDs
        // 1. Collect Valid Parent IDs (Robust Scan)
        const validParentIds = new Set();
        
        // Check ALL Storage Groups
        Object.keys(this.layerStorage).forEach(key => {
            const group = this.layerStorage[key];
            if (group) {
                group.eachLayer(l => {
                    const id = l.feature?.properties?.node_id;
                    if (id) validParentIds.add(id);
                });
            }
        });

        // Check Editor (Always)
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            window.AoTMapEditor.featureGroup.eachLayer(l => {
                const id = l.feature?.properties?.node_id;
                if (id) validParentIds.add(id);
            });
        }

        // 2. Identify and Remove Orphans
        const layersToRemove = [];
        labelGroup.eachLayer(l => {
            const parentId = l.feature?.properties?.parent_node_id;

            // Criteria for Deletion:
            // - Has parent_id but parent not found (Broken Link)
            // - No parent_id (Unknown origin, likely error fallback)
            // - Name is "Label" (Default) AND parent missing (Strong indicator of error)

            if (l.feature?.properties?.aot_type === 'label_dynamic') return;

            if (!parentId || !validParentIds.has(parentId)) {
                 // console.warn(`[Cleanup] Removing Orphan Label: ${l.feature?.properties?.label_name || 'Unnamed'} (Parent: ${parentId})`);
                 // console.log(`[Cleanup Debug] Parent ID ${parentId} found in valid set? ${validParentIds.has(parentId)}`);
                layersToRemove.push(l);
            }
        });

        layersToRemove.forEach(l => {
            labelGroup.removeLayer(l);
            // Also remove from map if visible
            if (this.map.hasLayer(l)) this.map.removeLayer(l);
        });

        if (layersToRemove.length > 0) {
            // console.log(`[Cleanup] ${layersToRemove.length} orphan labels removed. Syncing with DB...`);
            this.saveDesign(['label_aux'], true);
        }
    }

    deleteMap(uuid) {
        if (!uuid) return;
        fetch(`/api/geo/designs/${uuid}`, {
            method: 'DELETE',
            headers: {
                'X-CSRFToken': window.AoTMapData.getCsrfToken()
            }
        })
            .then(res => res.json())
            .then(data => {
                if (data.ok) {
                    this.ui.showToast(_('deleted_successfully'), 'success');

                    // Clear localStorage if it points to the deleted map
                    if (localStorage.getItem('aot_last_map_uuid') === uuid) {
                        localStorage.removeItem('aot_last_map_uuid');
                    }

                    // Remove deleted option from selector, then navigate to next map
                    const sel = $('#map-selector');
                    sel.find(`option[value="${uuid}"]`).remove();
                    sel.selectpicker('refresh');

                    const remaining = Array.from(
                        document.getElementById('map-selector').options
                    ).filter(opt => opt.value !== 'default' && opt.value !== 'new');

                    if (remaining.length > 0) {
                        window.location.href = `/geo/design?uuid=${remaining[0].value}`;
                    } else {
                        window.location.href = '/geo/design';
                    }
                } else {
                    this.ui.showToast(_('delete_failed') + ": " + data.message, 'error');
                }
            })
            .catch(err => { /* console.error(err); */ });
    }

    /* UI Toggles (Legacy Support) */
    toggleLock() {
        this.isLocked = !this.isLocked;
        const btn = document.getElementById('tool-lock');

        // Handlers live on the native MapLibre map, not on the shim
        const nativeMap = (this.map && this.map._originalMap) || this.map;
        const mlHandlers = ['dragPan', 'scrollZoom', 'doubleClickZoom', 'keyboard', 'touchZoomRotate', 'dragRotate'];
        mlHandlers.forEach(h => {
            if (nativeMap[h] && typeof nativeMap[h].disable === 'function') {
                this.isLocked ? nativeMap[h].disable() : nativeMap[h].enable();
            }
        });

        if (this.isLocked) {
            btn.innerHTML = '<i class="fas fa-lock text-danger"></i>';
            btn.dataset.locked = "true";
        } else {
            btn.innerHTML = '<i class="fas fa-unlock"></i>';
            btn.dataset.locked = "false";
        }
    }

    toggleHide() {
        this.isHidden = !this.isHidden;
        const btn = document.getElementById('tool-hide');
        const targets = document.querySelectorAll('.map-tools-right, .mode-panel');
        const leftGroup = document.querySelector('.map-tools-left');

        if (this.isHidden) {
            targets.forEach(el => el.classList.add('d-none'));
            if (leftGroup) Array.from(leftGroup.children).forEach(c => c !== btn && c.classList.add('d-none'));
            btn.innerHTML = '<i class="fas fa-grip-horizontal" style="opacity:0.35"></i>';
        } else {
            targets.forEach(el => el.classList.remove('d-none'));
            if (leftGroup) Array.from(leftGroup.children).forEach(c => c.classList.remove('d-none'));
            btn.innerHTML = '<i class="fas fa-grip-horizontal"></i>';
        }
    }

    // --- Dynamic Updates & Measurements ---

    // --- Marker Interaction ---
    _openMarkerPopup(layer) {
        if (!layer || !layer.feature) return;
        const props = layer.feature.properties || {};
        const type = props.aot_type;

        // 1. Theme Color (Match _setLayerStyle)
        let headerColor = '#333'; // Default
        const textWhite = 'text-white';

        if (type === 'facility') headerColor = '#82898f'; // Grey
        else if (type === 'equipment') headerColor = '#007bff'; // Blue
        else if (type === 'aot_device') headerColor = '#995aff'; // Purple
        else if (type === 'site') headerColor = '#ffcc00';
        else if (type === 'zone') headerColor = '#28a745';

        // 2. Build Content
        const content = document.createElement('div');
        content.style.minWidth = '250px';
        content.innerHTML = `
            <div class="card border-0 shadow-sm">
                <div class="card-header py-2 ${textWhite} font-weight-bold d-flex justify-content-between align-items-center" style="background-color: ${headerColor}; border-radius: 8px 8px 0 0;">
                    <span>${type ? type.toUpperCase() : 'MARKER'} INFO</span>
                    <button class="btn btn-sm btn-link text-white p-0 close-popup"><i class="fas fa-times"></i></button>
                </div>
                <div class="card-body p-3">
                    <div class="form-group mb-2">
                        <label class="small text-muted mb-1">Name</label>
                        <input type="text" class="form-control form-control-sm" id="marker-name" value="${props.name || props.label_name || ''}" placeholder="Enter name...">
                    </div>
                    <div class="form-group mb-3">
                        <label class="small text-muted mb-1">Memo</label>
                        <textarea class="form-control form-control-sm" id="marker-memo" rows="3" placeholder="Enter memo...">${props.memo || ''}</textarea>
                    </div>
                    <button class="btn btn-block btn-sm btn-primary font-weight-bold" id="btn-save-marker">${_('save_btn_text')}</button>
                </div>
            </div>
        `;

        // 3. Bind Events
        const inputName = content.querySelector('#marker-name');
        const inputMemo = content.querySelector('#marker-memo');
        const btnSave = content.querySelector('#btn-save-marker');

        // Real-time Update (Visual & Properties)
        if (inputName) {
            inputName.oninput = (e) => {
                const val = e.target.value;
                layer.feature.properties.name = val;
                layer.feature.properties.label_name = val;
                
                // Update UI (Metrics/Label) immediately
                this._updateShapeMetrics(layer);
            };
            // Auto-Save on Blur (Enter handled by default behavior or below)
            inputName.onblur = () => {
                 this.saveDesign([type], true);
                 this.updateDesignInfo();
            };
            inputName.onkeydown = (e) => {
                if (e.key === 'Enter') {
                    btnSave.click();
                }
            };
        }

        // Close
        content.querySelector('.close-popup').onclick = () => {
            layer.closePopup();
        };

        // Save Button
        if (btnSave) {
            btnSave.onclick = () => {
                const name = inputName.value;
                const memo = inputMemo ? inputMemo.value : '';

                // Update Properties (redundant if oninput fired, but safe)
                layer.feature.properties.name = name;
                layer.feature.properties.label_name = name; 
                layer.feature.properties.memo = memo;

                // Close & Save
                layer.closePopup();
                this.saveDesign([type], true);
                this.updateDesignInfo(); 
            };
        }

        // 4. Bind & Open Popup
        layer.bindPopup(content, {
            maxWidth: 300,
            closeButton: false, 
            autoPan: true
        }).openPopup();
    }


    /**
     * Dynamic Update: Recalculate Area and Refresh Labels (Text/Icon + Sides)
     * Called on draw:editvertex or drag
     */
    _updateShapeMetrics(layer) {
        if (!layer || !layer.feature || !layer.feature.properties) return;

        const props = layer.feature.properties;
        const type = props.aot_type;

        // 1. Recalculate Area (if Site/Zone)
        if (['site', 'zone'].includes(type) && window.turf) {
            let areaDisplay = '';
            try {
                let geojson = layer.toGeoJSON();
                if (layer._aotType === 'Circle') {
                    const center = layer.getLatLng();
                    const radius = layer.getRadius();
                    geojson = window.turf.circle([center.lng, center.lat], radius, { steps: 16, units: 'meters' });
                }

                const area = window.turf.area(geojson);
                areaDisplay = Math.round(area) + ' m²';
                props.area = area; // Update data

                // 2. Update Linked Label (Find it first)
                const uuid = props.node_id;
                let linkedLabel = null;

                // Search Editor
                window.AoTMapEditor.featureGroup.eachLayer(l => {
                    if (l.feature?.properties?.parent_node_id === uuid) linkedLabel = l;
                });

                // Search Storage
                if (!linkedLabel && this.layerStorage['label_aux']) {
                    this.layerStorage['label_aux'].eachLayer(l => {
                        if (l.feature?.properties?.parent_node_id === uuid) linkedLabel = l;
                    });
                }

                if (linkedLabel) {
                    const labelName = linkedLabel.feature.properties.label_name || props.name || "Label";
                    let color = '#333';
                    if (type === 'site') color = '#ffcc00';
                    else if (type === 'zone') color = '#28a745';

                    if (this.labels) this.labels.updateLabelIcon(linkedLabel, labelName, areaDisplay, color);
                }

            } catch (e) {
                // console.warn("[Metrics] Update Failed:", e);
            }
        }

        // 3. Update Side Measurement Labels
        if (this.geometry) this.geometry.updateMeasurementLabels(layer);
    }


    /**
     * Process Branch Pipe Trimming against Main Pipe
     * Scans for 'pipe_branch' that intersect with 'pipe_main' and trims/splits them.
     * Also assigns 'connected_main_id' to establish hierarchy for stats.
     */

    /**
     * Update Pipe Labels (Length)
     * For pipes >= 5m, show length at center.
     */

    _ensureLabelStyles() {
        // Always replace the style element so rule changes take effect on hot reload.
        const existing = document.getElementById('aot-label-style');
        if (existing) existing.remove();
        const style = document.createElement('style');
        style.id = 'aot-label-style';
        style.innerHTML = `
            .aot-hide-site-labels .aot-site-label { display: none !important; }
            .aot-hide-zone-labels .aot-zone-label { display: none !important; }
            .aot-hide-pipe-labels .aot-pipe-label { display: none !important; }
            .aot-zoom-hide-detail .aot-zone-label,
            .aot-zoom-hide-detail .aot-measure-label,
            .aot-zoom-hide-detail .aot-pipe-label,
            .aot-zoom-hide-detail .aot-map-label-marker { display: none !important; }
            .aot-hide-labels .aot-measure-label,
            .aot-hide-labels .aot-pipe-label,
            .aot-hide-labels .leaflet-tooltip { display: none !important; }
            .aot-hide-site-measure .aot-measure-label.aot-site-label { display: none !important; }
            .aot-hide-zone-measure .aot-measure-label.aot-zone-label { display: none !important; }
        `;
        document.head.appendChild(style);
    }

    _applyLengthLabelState() {
        if (!this.map || !this.panel) return;
        this._ensureLabelStyles();
        const container = this.map.getContainer();
        const p = this.panel;
        // Apply all three independently — each CSS class is scoped to its own label type,
        // so setting all of them is correct regardless of the active mode.
        container.classList.toggle('aot-hide-site-measure', !!p.isSiteLabelHidden);
        container.classList.toggle('aot-hide-zone-measure', !!p.isZoneLabelHidden);
        container.classList.toggle('aot-hide-pipe-labels', !!p.isPipeLabelHidden);
    }

    _toggleLengthLabels() {
        if (!this.map) return;
        this._ensureLabelStyles();
        const container = this.map.getContainer();
        const mode = this.activeMode;
        // Toggle only the length labels relevant to the current mode
        if (mode === 'equipment') {
            container.classList.toggle('aot-hide-pipe-labels');
        } else if (mode === 'site') {
            container.classList.toggle('aot-hide-site-measure');
        } else if (mode === 'zone') {
            container.classList.toggle('aot-hide-zone-measure');
        } else {
            container.classList.toggle('aot-hide-labels');
        }
    }

    _toggleSiteLabels() {
        if (!this.map) return;
        this._ensureLabelStyles();
        const container = this.map.getContainer();
        container.classList.toggle('aot-hide-site-labels');
    }

    _toggleZoneLabels() {
        if (!this.map) return;
        this._ensureLabelStyles();
        const container = this.map.getContainer();
        container.classList.toggle('aot-hide-zone-labels');
    }

    _togglePipeLabels() {
        if (!this.map) return;
        this._ensureLabelStyles();
        const container = this.map.getContainer();
        container.classList.toggle('aot-hide-pipe-labels');
    }

    _toggleSprinklerPoints(visible) {
        const mlMap = (this.map && this.map._originalMap) || this.map;
        if (!mlMap || !mlMap.setLayoutProperty) return;
        const vis = visible ? 'visible' : 'none';

        // RenderBucket GL layers: sprinkler dot + coverage circle
        // These are shared bucket layers — toggle once, not per-instance
        try { mlMap.setLayoutProperty('aot-bucket-sprinkler-dot', 'visibility', vis); } catch(e) {}
        try { mlMap.setLayoutProperty('aot-bucket-sprinkler-coverage', 'visibility', vis); } catch(e) {}

        // Per-instance GL layers (legacy / non-bucket path)
        const scanGroup = (group) => {
            if (!group || !group.eachLayer) return;
            group.eachLayer(l => {
                const sub = l.feature?.properties?.sub_type;
                if (sub !== 'sprinkler' && sub !== 'sprinkler_coverage') return;
                try { mlMap.setLayoutProperty(l._layerId, 'visibility', vis); } catch(e) {}
            });
        };
        scanGroup(this.layerStorage['equipment']);
        const fg = window.AoTMapEditor?.featureGroup;
        if (fg && fg.getLayers) fg.getLayers().forEach(l => {
            const sub = l.feature?.properties?.sub_type;
            if (sub !== 'sprinkler' && sub !== 'sprinkler_coverage') return;
            try { mlMap.setLayoutProperty(l._layerId, 'visibility', vis); } catch(e) {}
        });
    }

    _toggleConnectionPoints(visible) {
        // [Perf] Toggle pipe-junction (elbow/tee) marker visibility at the GL layer level.
        // Uses MapLibre setLayoutProperty so hidden layers incur zero render cost.
        const mlMap = (this.map && this.map._originalMap) || this.map;
        if (!mlMap || !mlMap.setLayoutProperty) return;
        const apply = (l) => {
            if (l.feature?.properties?.aot_type !== 'connection') return;
            try { mlMap.setLayoutProperty(l._layerId, 'visibility', visible ? 'visible' : 'none'); } catch(e) {}
        };
        const connGroup = this.layerStorage['connection'];
        if (connGroup && connGroup.eachLayer) connGroup.eachLayer(apply);
        const fg = window.AoTMapEditor?.featureGroup;
        if (fg && fg.getLayers) fg.getLayers().forEach(apply);
    }

    getLayerColor(type) {
        switch (type) {
            case 'site': return '#ffcc00';
            case 'zone': return '#28a745';
            case 'facility': return '#17a2b8';
            case 'equipment': return '#333';
            default: return '#3388ff';
        }
    }

    /* --- Device Placement & Linking --- */

    async _loadMapDevices(mapUuid) {
        if (this.devices) this.devices.loadMapDevices();
    }

    placeDeviceOnMap(dev) {
        if (this.devices) this.devices.placeDeviceOnMap(dev);
    }

    setDeviceLabelColor(type, color) {
        if (this.devices) this.devices.updateDeviceColor(type, color);
    }

    setDeviceVisibility(type, isVisible) {
        if (this.devices) this.devices.setDeviceTypeVisibility(type, isVisible);
    }

    /**
     * Instantly update all existing layers and labels on map with the new theme color.
     * @param {string} type - site, zone, facility, equipment, input, output, function
     * @param {string} color - Hex color
     */
    updateLayerStylesByType(type, color) {
        // 장치 종류 키는 AoTGeoTheme 이 정본이다(DEVICE_KEYS). 여기 목록을
        // 따로 들고 있다가 복합장치('device_unit')를 빠뜨려, 색을 바꿔도
        // 새로고침 전까지 지도에 반영되지 않았다.
        const deviceKeys = window.AoTGeoTheme.DEVICE_KEYS;

        // 1. Handle Aot-Device subtypes UI (Icons/Labels in Devices Module)
        if (deviceKeys.includes(type) && this.devices) {
            this.devices.updateDeviceColor(type, color);
        }

        const isDeviceSubtype = deviceKeys.includes(type);

        // 2. Handle Map Layers (Storage + Active FeatureGroup)
        // [Fix] In Design Mode, the active type's layers are in featureGroup, not storageGroup.
        // [Fix] Handle Device Subtypes (input, output, function) which share 'aot_device' or 'device' storage.
        const helperHandleGroup = (group) => {
            if (!group) return;
            group.eachLayer(layer => {
                const props = layer.feature?.properties || {};
                const layerType = props.aot_type;
                const devType = props.device_type;

                // Match Logic: Check for direct type match OR device subtype match
                let match = (layerType === type);
                if (isDeviceSubtype && (layerType === 'aot_device' || layerType === 'device')) {
                    // 세부 타입 → 테마 키 변환은 AoTGeoTheme 한 곳에서.
                    // 'custom' 이 Function 계열이자 복합장치의 행 종류라
                    // 목록을 손으로 들고 있으면 반드시 갈린다.
                    match = (window.AoTGeoTheme.normalizeDeviceType(devType) === type);
                }

                if (!match) return;

                if (this.ui && this.ui._setLayerStyle) {
                    const isActive = (this.activeLayer === layer);
                    this.ui._setLayerStyle(layer, isActive);
                } else if (layer.setStyle) {
                    layer.setStyle({ color: color, fillColor: color });
                }

                if (this.geometry && this.geometry.updateMeasurementLabels) {
                    this.geometry.updateMeasurementLabels(layer);
                }
                if (this.geometry && this.geometry.updatePipeLabels) {
                    this.geometry.updatePipeLabels(layer);
                }
            });
        };

        // Update Relevant Starage Groups
        if (isDeviceSubtype) {
            helperHandleGroup(this.layerStorage['aot_device']);
            helperHandleGroup(this.layerStorage['device']);
        } else {
            helperHandleGroup(this.layerStorage[type]);
        }
        
        // Update Active Editor Group (Critical for real-time mode feedback)
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            helperHandleGroup(window.AoTMapEditor.featureGroup);
        }

        // 3. Handle Associated Persistent Labels (Name/Area labels in label_aux group)
        if (this.labels && this.layerStorage['label_aux']) {
            this.layerStorage['label_aux'].eachLayer(labelMarker => {
                const props = labelMarker.feature?.properties;
                if (!props) return;

                // [Fix] SKIP dynamic measurement labels (they are handled by updateMeasurementLabels above)
                // This prevents corrupting length labels with 'Label' text.
                if (props.aot_type === 'label_dynamic') return;

                // Check link to parent color type
                const parentType = props.parent_type;
                if (parentType === type || (type === 'device' && (parentType === 'input' || parentType === 'output' || parentType === 'function'))) {
                    const name = props.label_name || props.label_text || 'Label';
                    const area = props.label_area || '';
                    this.labels.updateLabelIcon(labelMarker, name, area, color);
                }
            });
        }
    }


    /**
     * Update Design Information Logic
     * Delegates to AoTGeoStats
     */
    updateDesignInfo() {
        if (this.stats) this.stats.updateDesignInfo();
    }
    /**
     * Re-assigns parent IDs for pipes and sprinklers based on their spatial location.
     * Triggered when a Site or Zone is edited.
     */

    /**
     * Automatic trimming of branch pipes that intersect with a main pipe.
     * Keeps the longer segment.
     */
    // [Refactor] Centralized Feature Processor (Used by Load and Create-Reload)
    _processLoadedFeature(l, type) {
        // [Fix] Ensure Feature Geometry Exists (Crucial for Turf/Stats)
        // L.Draw layers don't have .feature.geometry by default, identifying mismatch with L.geoJSON layers.
        if (!l.feature || !l.feature.geometry) {
            const geo = l.toGeoJSON();
            l.feature = l.feature || { type: 'Feature', properties: {} };
            l.feature.geometry = geo.geometry;
            // Merge properties if needed, but usually we set them manually in _onShapeCreated
        }

        // Apply Default Inactive Style
        this.ui._setLayerStyle(l, false);

        const f = l.feature;
        const props = f.properties;

        // RECOVER CIRCLE (only when saved as converted Polygon — old Leaflet format)
        // Point+radius circles are already correctly reconstructed as AoTGeoCircle by fromGeoJSON.
        // Recovering them here would create a second AoTGeoCircle with a different _layerId,
        // causing two upserts into the same RenderBucket and a duplicate/polygon-looking render.
        // Also recover Polygon+sub_type=sprinkler_coverage without is_circle (intermediate DB format).
        if ((props.is_circle || props.sub_type === 'sprinkler_coverage') && f.geometry.type !== 'Point') {
            let center = null;
            const radius = props.radius;

            if (props.center_lat && props.center_lng) {
                center = [props.center_lat, props.center_lng];
            } else if (window.turf && f.geometry.type === 'Polygon') {
                const centroid = window.turf.centroid(f);
                center = [centroid.geometry.coordinates[1], centroid.geometry.coordinates[0]];
            }

            if (center && radius) {
                const circleLayer = new AoTGeoCircle(center, {
                    radius: radius,
                    interactive: (props.sub_type !== 'sprinkler_coverage')
                });
                circleLayer.feature = Object.assign({}, l.feature, { properties: Object.assign({}, l.feature.properties) });

                // Mark the original Polygon layer so addLayersWhenReady skips it.
                // Without this, addLayersWhenReady adds the AoTGeoPolygon as a fill GL layer
                // on top of the correctly-recovered AoTGeoCircle, causing a polygon appearance.
                l._alreadyHandled = true;
                l = circleLayer;
            }
        }

        if (!l.feature.properties.aot_type) l.feature.properties.aot_type = type;

        const isLabel = l.feature.properties.aot_type === 'label_aux' || type === 'label_aux';

        // Determine Target Storage Group
        let targetKey = type;
        const subType = l.feature.properties.sub_type || l.feature.properties.aot_type;
        const aotType = l.feature.properties.aot_type;

        // [New] Route 'device' type to 'device' storage
        // [Fix] Race Condition: 'aot_device' storage is cleared by Device Module for markers.
        // We MUST put device SHAPES (Polygons/Lines) into 'device' storage to preserve them.
        if (aotType === 'device') {
            targetKey = 'device';
        } else if (aotType === 'aot_device') {
            // Route to 'device' storage to avoid race with Device Module marker clearing.
            targetKey = 'device';
            // [Fix] Conditional normalization, split by whether the shape is linked to a device:
            //  - Device-LINKED (has device_id): normalize aot_type → 'device' so full-save's
            //    'device' overlay (saveOverlays) preserves/updates it. Without this it would be
            //    categorized as 'aot_device' (excluded from typesToSync) → saveOverlays('device', [])
            //    runs empty → ALL type='device' rows wiped (device shapes lost).
            //  - ORPHAN (no device_id, drawn without selecting a device): KEEP aot_type='aot_device'
            //    so it rides the orphan delta path (upsert/delete by node_id) — no duplicate row,
            //    and it is NOT swept into the 'device' overlay full-replace.
            if (l.feature.properties.device_id) {
                l.feature.properties.aot_type = 'device';
            }
        } else if (subType && this.layerStorage[subType]) {
            targetKey = subType;
        }

        // [Fix] Prevent Style Reset for Connection Dots (mbT, E, T)
        // These have unique colors (Yellow, Orange) set at creation.
        // Applying default style here would overwrite them (e.g. to Blue).
        if (aotType === 'connection' || l.feature.properties.aot_type === 'connection') {
            // Ensure they are in connection or equipment storage, but DO NOT reset style.
            if (this.layerStorage['connection']) {
                if (!this.layerStorage['connection'].hasLayer(l)) this.layerStorage['connection'].addLayer(l);
            } else if (this.layerStorage['equipment']) {
                if (!this.layerStorage['equipment'].hasLayer(l)) this.layerStorage['equipment'].addLayer(l);
            }
            // Skip further generic styling
            return;
        }

        // [Fix] Ensure Style is applied BEFORE potential returns or group additions
        if (subType === 'sprinkler_coverage') {
            l.setStyle({
                color: '#007bff',
                weight: 1,
                fillOpacity: 0.2, // Match pipe level
                dashArray: '3, 3'
            });
        }
        
        // [New] Apply Device Theme Color for Device Shapes
        if ((aotType === 'device' || aotType === 'aot_device') && l.feature.properties.device_id) {
            // 색의 정본은 theme_config 뿐이다. 예전에는 여기서
            //   ① 도형에 각인된 properties.color 를 최우선으로 쓰고
            //   ② 계산한 색을 다시 properties.color 에 써 넣었다(sync back).
            // 그래서 한 번 각인된 도형은 이후 테마를 바꿔도 옛 색으로 되돌아왔고,
            // properties.color 를 읽지 않는 AoT_map 위젯과 색이 어긋났다.
            const color = window.AoTGeoTheme.deviceColor(l.feature.properties.device_type);

            // Apply Style
            if (l.setStyle) {
                l.setStyle({
                    color: color,
                    fillColor: color,
                    fillOpacity: 0.5,
                    weight: 3
                });
            }
        }

        if (isLabel) {
            if (this.labels) {
                this.labels.convertToLabel(l);
                // Ensure group has _map set BEFORE addLayer(l) so doAdd() fires
                // immediately for all labels (including the very first one loaded).
                if (!this.map.hasLayer(this.layerStorage['label_aux'])) {
                    this.map.addLayer(this.layerStorage['label_aux']);
                }
                if (!this.layerStorage['label_aux'].hasLayer(l)) {
                     this.layerStorage['label_aux'].addLayer(l);
                }
            }
        } else {
            // [Fix] Context-Aware Assignment
            // Logic: If current mode matches feature type, add to Editor directly.
            // This solves "disappearing shape" on initial load (where setMode(site) happens before load finishes)
            const currentMode = this.activeMode || 'site';
            
            // Special Check for 'device' layers when in 'aot_device' mode
            const isDeviceModeMatch = (currentMode === 'aot_device' && (targetKey === 'device' || targetKey === 'aot_device'));
            
            // [Fix] Allow adding to Editor even if isLoading is true, IF it is the active mode.
            // Previously `&& !this.isLoading` forced everything into storage, causing disappearance until manual switch.
            const shouldGoToEditor = (currentMode === type || currentMode === targetKey || isDeviceModeMatch);

                const storageGroup = this.layerStorage[targetKey] || this.layerStorage[type];
                
                // [Fix] During initial load, ALWAYS go to storage first.
                // The final _switchLayerContext call in _loadAllFeatures will move active items to Editor.
                // This prevents race conditions and ensures styles are applied correctly once loading finishes.
                const isPassive = !shouldGoToEditor || this.isLoading;

                if (!isPassive) {
                    if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
                        // [Fix] Enforce Pane - check l.options exists first (MapLibre-drawn features may lack .options)
                        if (l.options) {
                            if (storageGroup && storageGroup.options && storageGroup.options.pane) {
                                l.options.pane = storageGroup.options.pane;
                            } else if (targetKey && this.layerStorage[targetKey] && this.layerStorage[targetKey].options && this.layerStorage[targetKey].options.pane) {
                                l.options.pane = this.layerStorage[targetKey].options.pane;
                            }
                        }

                        if (!window.AoTMapEditor.featureGroup.hasLayer(l)) {
                             window.AoTMapEditor.featureGroup.addLayer(l);
                             this.ui._setLayerStyle(l, false); 
                        }
                    }
                } else {
                    if (storageGroup && !storageGroup.hasLayer(l)) {
                        // [Fix] Enforce Pane - check l.options exists first
                        if (l.options && storageGroup.options.pane) {
                             l.options.pane = storageGroup.options.pane;
                        }

                        // [Fix] Register storageGroup with map FIRST so _map is set,
                        // then addLayer → AoTGeoLayerGroup.doAdd fires with _map available.
                        // Previous order (addLayer → addLayer(group)) caused first feature's
                        // doAdd to be skipped because storageGroup._map was null.
                        if (!this.map.hasLayer(storageGroup)) {
                            this.map.addLayer(storageGroup);
                        }
                        storageGroup.addLayer(l);
                        this.ui._setLayerStyle(l, false);
                    }
                }

            // Initial Style: (Already handled in if/else above)
            // this.ui._setLayerStyle(l, false);

            // Labels: defer during bulk load to avoid per-feature turf+DOM cost
            if (this.geometry) {
                if (this.isLoading) {
                    if (!this._pendingLabelUpdates) this._pendingLabelUpdates = [];
                    this._pendingLabelUpdates.push({ l, type, targetKey });
                } else {
                    if (['site', 'zone'].includes(type) || ['site', 'zone'].includes(targetKey)) {
                        this.geometry.updateMeasurementLabels(l);
                    }
                    this.geometry.updatePipeLabels(l);
                }
            }

            // Guard: Sprinkler Coverage - Do not add interactive events for coverage circles
            if (l.feature.properties.sub_type === 'sprinkler_coverage') {
                return;
            }

            // Updated Event Handler (Compatible with Prop Changes)
            l.on('click', (e) => {
                const fType = l.feature.properties.aot_type;
                // Strict: only layers belonging to this mode (no site/zone cross-mode exception for edit/delete)
                const isAllowedStrict = (this.activeMode === fType)
                    || (this.activeMode === 'aot_device' && fType === 'device')
                    || (this.activeMode === 'equipment' && fType === 'reference');
                // Selection: also allow equipment mode to select site/zone as context
                const isAllowed = isAllowedStrict
                    || (this.activeMode === 'equipment' && ['site', 'zone'].includes(fType));

                if (window.AoTMapEditor && window.AoTMapEditor.editEnabled) {
                    if (!isAllowedStrict) return;
                    AoTDomEvent.stopPropagation(e);
                    if (e.originalEvent) e.originalEvent._aotLayerHandled = true;
                    const dm = window.AoTMapEditor.drawManager
                        || (window.AoTMapLibreDrawManager && window.AoTMapLibreDrawManager.getDefault && window.AoTMapLibreDrawManager.getDefault(this.map));
                    if (dm && dm.editSelectLayerDirect) dm.editSelectLayerDirect(l);
                    else if (dm && dm._editSelectLayer) dm._editSelectLayer(l._layerId);
                    return;
                }
                if (window.AoTMapEditor && window.AoTMapEditor.deleteEnabled) {
                    if (!isAllowedStrict) return;
                    AoTDomEvent.stopPropagation(e);
                    if (e.originalEvent) e.originalEvent._aotLayerHandled = true;
                    // Track deletion for backend save BEFORE the layer is removed
                    const props = l.feature && l.feature.properties;
                    const nid = props && (props.node_id || props.db_id);
                    const aotType = props && props.aot_type;
                    if (nid) this.deletedNodeIds.add(nid);
                    if (aotType) this._pendingDeletedTypes = this._pendingDeletedTypes || new Set();
                    if (aotType) this._pendingDeletedTypes.add(aotType);
                    const dm = window.AoTMapEditor.drawManager
                        || (window.AoTMapLibreDrawManager && window.AoTMapLibreDrawManager.getDefault && window.AoTMapLibreDrawManager.getDefault(this.map));
                    if (dm && dm.deleteLayerDirect) dm.deleteLayerDirect(l);
                    return;
                }

                if (!isAllowed) return; // Allow bubble for drawing tools

                // [Fix] Bubbling Protection: If we are DRAWING, do NOT stop propagation.
                // Stopping propagation here prevents the map from receiving the click and finishing the draw/rectangle/circle.
                if (window.AoTMapEditor && window.AoTMapEditor.activeShape) {
                    return;
                }

                AoTDomEvent.stopPropagation(e);
                if (e.originalEvent) e.originalEvent._aotLayerHandled = true;

                // INTERCEPT: Merge/Subtract Pending Op
                if (this.pendingOp && ['merge', 'sub'].includes(this.pendingOp.type)) {
                    const isPolygon = (l._aotType === 'Polygon') || (l.feature.geometry.type === 'Polygon');
                    if (isPolygon) {
                        if (this.pendingOp.type === 'merge') this.geometry.handleGeometryOp('merge', this.pendingOp.targetLayer, l);
                        else if (this.pendingOp.type === 'sub') this.geometry.handleGeometryOp('sub', this.pendingOp.targetLayer, l);

                        this.pendingOp = null;
                        AoTDomUtil.removeClass(this.map._container, 'crosshair-cursor');
                    } else {
                        this.ui.showToast(_('only_polygons_selectable'), 'warning');
                    }
                    return;
                }

                // Toggle Logic (Standard Activation)
                if (this.activeLayer === l) {
                    this._resetActiveLayer();
                } else {
                    this._setActiveLayer(l);
                }
            });

            // [New] Block mousedown ONLY if mode matches (Fix drag issues)
            l.on('mousedown', (e) => {
                // [Fix] Bubbling Protection for Mousedown (Crucial for Rectangles/Circles)
                if (window.AoTMapEditor && window.AoTMapEditor.activeShape) {
                    return;
                }

                const fType = l.feature.properties.aot_type;
                const isAllowed = (this.activeMode === fType)
                    || (this.activeMode === 'aot_device' && fType === 'device')
                    || (this.activeMode === 'equipment' && ['site', 'zone', 'reference'].includes(fType));
                if (isAllowed) {
                    AoTDomEvent.stopPropagation(e);
                }
            });

            // [New] Marker Interaction (Popup) - Unified
            if (l._aotType === 'Marker' && l.feature.properties.aot_type !== 'label_aux') {
                l.on('dblclick', (e) => {
                    AoTDomEvent.stopPropagation(e);
                    this._openMarkerPopup(l);
                });
            }

        }
    }

    /**
     * Repair Loaded Data Integrity
     * Called after loadMap to ensure all relationships (zone_id, connected_main_id) are valid.
     */
    _repairLoadedData() {
        // console.log("[GeoDesign] Repairing Loaded Data...");
        if (!window.turf || !window.AoTMapUtils) {
            this.updateDesignInfo();
            return;
        }

        // 1. Recalculate Spatial Relationships (Fix zone_id / parent_id)
        if (this.geometry) this.geometry.recalculateSpatialRelationships();

        // 2. Fix Pipe Connections (Trim & Link)
        // Find all main pipes
        const mainPipes = [];
        const findMain = (l) => {
            const p = l.feature?.properties;
            if (p && (p.sub_type === 'pipe_main' || p.aot_type === 'pipe_main')) {
                mainPipes.push(l);
            }
        };
        if (this.layerStorage['equipment']) this.layerStorage['equipment'].eachLayer(findMain);
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) window.AoTMapEditor.featureGroup.eachLayer(findMain);
 
        // console.log(`[GeoRepair] Found ${mainPipes.length} Main Pipes for connection check.`);
        // console.log(`[GeoRepair] Found ${mainPipes.length} Main Pipes for connection check.`);
        // [Optimization] Consolidate into single rebuildConnections pass.
        // processPipeTrimming here is redundant if rebuildConnections runs next.
        /*
        mainPipes.forEach(main => {
            if (this.geometry) this.geometry.processPipeTrimming(main);
        });
        */

        // [Fix] Force Label Refresh for ALL pipes (ensure labels exist after load/cleanup)
        const refreshLabels = (l) => {
             const p = l.feature?.properties;
             if (p && (p.sub_type === 'pipe_main' || p.sub_type === 'pipe_branch')) {
                 if (this.geometry) this.geometry.updatePipeLabels(l);
             }
        };
        if (this.layerStorage['equipment']) this.layerStorage['equipment'].eachLayer(refreshLabels);
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) window.AoTMapEditor.featureGroup.eachLayer(refreshLabels);

        // [Fix] Rebuild Connections (Tee/Elbow Dots) as they are ephemeral (no_save)
        // Ensure this runs after pipes are loaded and trimming checked.
        if (this.geometry) {
            // console.log("[GeoRepair] Rebuilding Connection Dots...");
            this.geometry.rebuildConnections();
        }

        // 3. Final UI Update
        this.updateDesignInfo();
        
        // [New] Final Z-Index Check
        this._enforceLayerOrder();
        // console.log("[GeoDesign] Data Repair Completed.");
    }

    /* --- Active Layer Management --- */

    _setActiveLayer(layer) {
        if (!layer) return;

        // Block cross-mode activation: only allow layers belonging to the current mode
        const fType = layer.feature?.properties?.aot_type;
        const modeAllowed = !fType
            || (this.activeMode === fType)
            || (this.activeMode === 'aot_device' && fType === 'device')
            || (this.activeMode === 'equipment' && ['reference', 'site', 'zone'].includes(fType));
        if (!modeAllowed) return;

        if (this.activeLayer && this.activeLayer !== layer) {
             this._resetActiveLayer();
        }

        this.activeLayer = layer;
        
        // Visual Highlight
        if (this.ui) this.ui._setLayerStyle(layer, true);

        // Update Panel
        if (this.panel) {
            this.panel.render(this.activeMode, layer.feature);
        }

        // [New] Auto Enable Edit (Removed per User Request)
        // Selection now only highlights and opens panel.
        // Editing must be enabled via specific toggle or context.
        /*
        if (!this.isLocked) {
             if (!layer.editing) {
                 // [GIS Pure MapLibre v5.0] L.Edit.* removed - use AoTMapLibreDraw for editing
                 // Lazy Init Editing Handler
                 try {
                     // if (layer._aotType === 'Marker') layer.editing = new AoTMapLibreDraw.Edit.Marker(layer);
                     // else if (layer._aotType === 'Circle') layer.editing = new AoTMapLibreDraw.Edit.Circle(layer);
                     // else if (layer._aotType === 'Polyline' || layer._aotType === 'Polygon') layer.editing = new AoTMapLibreDraw.Edit.Poly(layer);
                 } catch (e) { }
             }
             
             if (layer.editing) {
                 layer.editing.enable();
             }
        }
        */
    }

    _resetActiveLayer() {
        if (this.activeLayer) {
            // [New] Disable Editing
            if (this.activeLayer.editing && this.activeLayer.editing.enabled()) {
                this.activeLayer.editing.disable();
            }

            // Restore visual style (inactive)
            if (this.ui) this.ui._setLayerStyle(this.activeLayer, false);
            this.activeLayer = null;
        }

        // Update Panel (Clear selection context)
        if (this.panel) {
            this.panel.render(this.activeMode, null);
        }
    }
}

window.AoTGeoDesign = AoTGeoDesign;
