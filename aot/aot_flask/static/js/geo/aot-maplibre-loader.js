/**
 * aot-maplibre-loader.js
 * Pure MapLibre GL Map Loader for AoT
 * Replaces Leaflet-based map initialization with full 3D support
 *
 * Features:
 * - Pure MapLibre initialization (no Leaflet dependency)
 * - Full pitch/bearing/terrain 3D support
 * - Vector tile layers (MapTiler, etc.)
 * - Raster overlays (RainViewer, GeoServer, etc.)
 * - GeoJSON overlays
 *
 * @version 1.1.0 - Added isStyleLoaded polyfill
 * @requires maplibre-gl
 */

(function(global) {
    'use strict';

    // ============================================================
    // MAPLIBRE POLYFILL - aot-maplibre-patches.js 로 이전(멱등 apply).
    // 로드 순서/지연 로드와 무관하게 maplibre 존재 시 패치를 보장한다.
    // ============================================================
    if (global.AoTMapLibrePatches && typeof global.AoTMapLibrePatches.apply === 'function') {
        global.AoTMapLibrePatches.apply();
    }

    /**
     * AoT MapLibre Loader
     * Centralized map initialization for AoT GIS system
     */
    const AoTMapLibreLoader = {

        /** @type {maplibregl.Map|null} */
        _instance: null,

        /** @type {string|null} */
        _containerId: null,

        /** @type {boolean} */
        _initialized: false,

        /** @type {Object} Default configuration */
        _defaultConfig: {
            center: [126.9780, 37.5665], // Seoul
            zoom: 12,
            maxZoom: 22,
            minZoom: 0,
            pitch: 0,
            bearing: 0,
            attributionControl: true,
            maplibreLogo: true
        },

        /**
         * Initialize a pure MapLibre map
         * @param {string} containerId - DOM element ID for map container
         * @param {Object} options - Initialization options
         * @returns {maplibregl.Map|null}
         */
        initMap: function(containerId, options = {}) {
            if (typeof maplibregl === 'undefined') {
                console.error('[AoTMapLibreLoader] MapLibre GL not loaded');
                return null;
            }

            // Get global config
            const globalConfig = window.AOT_GEO_CONFIG || {};
            const settings = globalConfig;

            // Helper: Strict False check
            const isTrue = (val, def = true) => {
                if (val === false || val === 'false' || val === 0 || val === '0') return false;
                if (val === true || val === 'true' || val === 1 || val === '1') return true;
                return def;
            };

            // Resolve configuration
            const defaultLat = parseFloat(settings.default_lat) || 37.5665;
            const defaultLng = parseFloat(settings.default_lng) || 126.9780;
            const defaultZoom = parseFloat(settings.zoom) || 12;
            const maxZoom = parseInt(settings.max_zoom) || 22;

            // Build map options
            const mapOptions = {
                container: containerId,
                center: [defaultLng, defaultLat], // MapLibre uses [lng, lat]
                zoom: defaultZoom,
                maxZoom: maxZoom,
                minZoom: 0,
                pitch: options.pitch || 0,
                bearing: options.bearing || 0,
                attributionControl: isTrue(settings.attribution_control, true),
                maplibreLogo: true,
                antialias: true,
                // preserveDrawingBuffer 는 매 프레임 GPU 드로잉 버퍼를 보존하느라
                // "GPU stall due to ReadPixels" 를 유발한다(특히 3D facility 커스텀
                // 레이어와 함께). 맵 이미지 export(toDataURL/toBlob) 기능이 없으므로
                // 불필요 — maplibre 기본값(false)으로 두어 렌더 스톨을 제거한다.
                // (저사양 GPU 에서 모달 클릭 등 상호작용 지연의 원인)
                preserveDrawingBuffer: false
            };

            // Merge with any custom options
            Object.assign(mapOptions, options);

            // Create map instance
            try {
                this._instance = new maplibregl.Map(mapOptions);
                this._containerId = containerId;
                this._initialized = true;

                // Add navigation controls
                if (isTrue(settings.show_navigation, true)) {
                    this._instance.addControl(new maplibregl.NavigationControl({
                        showCompass: true,
                        showZoom: true,
                        visualizePitch: true
                    }), 'top-right');
                }

                // Add attribution control
                if (isTrue(settings.attribution_control, true)) {
                    this._instance.addControl(new maplibregl.AttributionControl({
                        compact: true
                    }), 'bottom-right');
                }

                // Add scale control
                if (isTrue(settings.show_scale, false)) {
                    this._instance.addControl(new maplibregl.ScaleControl({
                        maxWidth: 100,
                        unit: 'metric'
                    }), 'bottom-left');
                }

                // Add terrain control for 3D
                if (isTrue(settings.enable_terrain, true)) {
                    this._addTerrainSupport();
                }

                console.log('[AoTMapLibreLoader] Map initialized:', containerId);
                return this._instance;

            } catch (e) {
                console.error('[AoTMapLibreLoader] Error creating map:', e);
                return null;
            }
        },

        /**
         * Add 3D terrain support to the map
         * @private
         */
        _addTerrainSupport: function() {
            if (!this._instance) return;

            // Add terrain source for 3D terrain visualization
            // Using MapTiler terrain tiles (or OpenMapTiles terrain)
            const globalConfig = window.AOT_GEO_CONFIG || {};

            // Only add terrain if explicitly enabled
            if (globalConfig.enable_terrain !== true) return;

            // Get terrain source from config or use default
            const terrainSource = globalConfig.terrain_source || {
                type: 'raster-dem',
                url: 'https://api.maptiler.com/tiles/terrain-rgb-v2/tiles.json?key=' + (globalConfig.keys && globalConfig.keys.maptiler || ''),
                tileSize: 256,
                maxzoom: 14
            };

            try {
                this._instance.addSource('mapbox-dem', terrainSource);

                // Add terrain layer for 3D effect
                this._instance.setTerrain({ source: 'mapbox-dem', exaggeration: 1.5 });

                // Add hillshade layer for better 3D visualization
                this._instance.addLayer({
                    id: 'hillshade',
                    source: 'mapbox-dem',
                    type: 'hillshade',
                    layout: { visibility: 'visible' },
                    paint: {
                        'hillshade-shadow-color': '#473B24',
                        'hillshade-illumination-anchor': 'map',
                        'hillshade-exaggeration': 0.5
                    }
                }, 'waterway-label');

                console.log('[AoTMapLibreLoader] Terrain support enabled');
            } catch (e) {
                console.warn('[AoTMapLibreLoader] Could not add terrain:', e.message);
            }
        },

        /**
         * Add a vector tile base layer
         * @param {string} styleUrl - Style JSON URL or style object
         * @param {Object} options - Layer options
         * @returns {Promise<boolean>}
         */
        addVectorBaseLayer: function(styleUrl, options = {}) {
            if (!this._instance) {
                console.error('[AoTMapLibreLoader] Map not initialized');
                return Promise.resolve(false);
            }

            return new Promise((resolve, reject) => {
                try {
                    this._instance.on('load', () => {
                        this._instance.setStyle(styleUrl, {
                            ...options,
                            transformRequest: (url, resourceType) => {
                                // Handle API key injection
                                const globalConfig = window.AOT_GEO_CONFIG || {};
                                if (url.includes('api.maptiler.com') && globalConfig.keys && globalConfig.keys.maptiler) {
                                    const separator = url.includes('?') ? '&' : '?';
                                    url += separator + 'key=' + globalConfig.keys.maptiler;
                                }
                                return { url };
                            }
                        });

                        // Re-add terrain after style change
                        if (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.enable_terrain) {
                            this._instance.once('styledata', () => {
                                this._addTerrainSupport();
                            });
                        }

                        resolve(true);
                    });

                    // If already loaded
                    if (this._instance.isStyleLoaded()) {
                        this._instance.setStyle(styleUrl, options);
                        resolve(true);
                    }
                } catch (e) {
                    console.error('[AoTMapLibreLoader] Error adding vector layer:', e);
                    reject(e);
                }
            });
        },

        /**
         * Add a raster tile layer
         * @param {string} sourceId - Unique source identifier
         * @param {string} tileUrl - XYZ tile URL pattern
         * @param {Object} options - Source options
         * @returns {boolean}
         */
        addRasterSource: function(sourceId, tileUrl, options = {}) {
            if (!this._instance) {
                console.error('[AoTMapLibreLoader] Map not initialized');
                return false;
            }

            const defaultOptions = {
                type: 'raster',
                tiles: [tileUrl],
                tileSize: 256,
                minzoom: 0,
                maxzoom: 18,
                attribution: options.attribution || ''
            };

            const sourceConfig = Object.assign({}, defaultOptions, options);

            try {
                // Remove existing source if present
                if (this._instance.getSource(sourceId)) {
                    this._instance.removeSource(sourceId);
                }

                this._instance.addSource(sourceId, sourceConfig);

                // Add raster layer
                const layerId = sourceId + '_layer';
                if (!this._instance.getLayer(layerId)) {
                    this._instance.addLayer({
                        id: layerId,
                        type: 'raster',
                        source: sourceId,
                        paint: {
                            'raster-opacity': options.opacity || 1.0,
                            'raster-saturation': 0,
                            'raster-contrast': 0
                        },
                        layout: {
                            visibility: options.visible !== false ? 'visible' : 'none'
                        }
                    });
                }

                console.log('[AoTMapLibreLoader] Raster source added:', sourceId);
                return true;
            } catch (e) {
                console.error('[AoTMapLibreLoader] Error adding raster source:', e);
                return false;
            }
        },

        /**
         * Add GeoJSON data as a source and layer
         * @param {string} sourceId - Unique source identifier
         * @param {Object|string} geojson - GeoJSON object or URL
         * @param {Object} layerConfig - Layer configuration
         * @returns {boolean}
         */
        addGeoJSON: function(sourceId, geojson, layerConfig = {}) {
            if (!this._instance) {
                console.error('[AoTMapLibreLoader] Map not initialized');
                return false;
            }

            const defaultLayerConfig = {
                type: 'circle',
                paint: {
                    'circle-radius': 6,
                    'circle-color': '#ff7800',
                    'circle-opacity': 0.8,
                    'circle-stroke-width': 2,
                    'circle-stroke-color': '#ffffff'
                }
            };

            try {
                const mergedConfig = Object.assign({}, defaultLayerConfig, layerConfig);

                // Add source
                const sourceConfig = {
                    type: 'geojson',
                    data: typeof geojson === 'string' ? geojson : geojson
                };

                if (this._instance.getSource(sourceId)) {
                    this._instance.removeSource(sourceId);
                }

                this._instance.addSource(sourceId, sourceConfig);

                // Add layer
                const layerId = sourceId + '_layer';
                if (!this._instance.getLayer(layerId)) {
                    this._instance.addLayer(Object.assign({ id: layerId, source: sourceId }, mergedConfig));
                }

                console.log('[AoTMapLibreLoader] GeoJSON added:', sourceId);
                return true;
            } catch (e) {
                console.error('[AoTMapLibreLoader] Error adding GeoJSON:', e);
                return false;
            }
        },

        /**
         * Get the current map instance
         * @returns {maplibregl.Map|null}
         */
        getMap: function() {
            return this._instance;
        },

        /**
         * Check if map is initialized
         * @returns {boolean}
         */
        isInitialized: function() {
            return this._initialized && this._instance !== null;
        },

        /**
         * Fly to a location
         * @param {number[]} lngLat - [lng, lat]
         * @param {number} zoom - Target zoom
         * @param {Object} options - FlyTo options
         */
        flyTo: function(lngLat, zoom, options = {}) {
            if (!this._instance) return;

            this._instance.flyTo({
                center: lngLat,
                zoom: zoom,
                ...options
            });
        },

        /**
         * Set map pitch (vertical tilt)
         * @param {number} pitch - Pitch in degrees (0-85)
         */
        setPitch: function(pitch) {
            if (!this._instance) return;
            this._instance.setPitch(pitch);
        },

        /**
         * Set map bearing (rotation)
         * @param {number} bearing - Bearing in degrees
         */
        setBearing: function(bearing) {
            if (!this._instance) return;
            this._instance.setBearing(bearing);
        },

        /**
         * Fit bounds to show specific area
         * @param {number[]} bounds - [west, south, east, north]
         * @param {Object} options - FitBounds options
         */
        fitBounds: function(bounds, options = {}) {
            if (!this._instance) return;

            this._instance.fitBounds(bounds, {
                padding: options.padding || 50,
                maxZoom: options.maxZoom || 16,
                ...options
            });
        },

        /**
         * Resize the map (call after container size changes)
         */
        resize: function() {
            if (this._instance) {
                this._instance.resize();
            }
        },

        /**
         * Clean up and remove the map
         */
        destroy: function() {
            if (this._instance) {
                this._instance.remove();
                this._instance = null;
                this._initialized = false;
                this._containerId = null;
                console.log('[AoTMapLibreLoader] Map destroyed');
            }
        }
    };

    // Export globally
    global.AoTMapLibreLoader = AoTMapLibreLoader;

    // Also expose factory pattern for compatibility
    global.AoTMapLibreLoader.create = function(containerId, options) {
        return AoTMapLibreLoader.initMap(containerId, options);
    };

})(window);
