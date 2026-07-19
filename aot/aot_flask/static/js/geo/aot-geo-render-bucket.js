/**
 * aot-geo-render-bucket.js
 * RenderBucket: Category-based layer consolidation for MapLibre GL
 *
 * Instead of 1 source + 1 layer per AoTGeoCircle/CircleMarker instance,
 * RenderBucket maps all instances of the same category to a SINGLE source+layer.
 * This reduces MapLibre layer count from O(n) to O(c) where c = category count.
 *
 * Categories:
 *   'sprinkler-coverage'  — AoTGeoCircle (meter-based radius via circle-radius zoom expr)
 *   'sprinkler-dot'       — AoTGeoCircleMarker (pixel-based radius)
 *   'pipe-main'           — LineString (pipe_main) — blue, thick
 *   'pipe-branch'         — LineString (pipe_branch) — lighter blue, thinner
 *   'pipe-reference'      — LineString (reference_line) — dashed
 *   'line-generic'        — LineString (fallback) — gray, thin
 *   'connection-line'      — AoTGeoPolyline (Phase 2)
 *   'connection-dot'       — Connection dots: mT, mbT, tee, elbow, etc. (Phase 3)
 *
 * Usage:
 *   const bucket = RenderBucket.get(map, 'sprinkler-coverage');
 *   bucket.upsert(featureId, featureGeoJSON);
 *   bucket.setStyle(featureId, { color: '#ff0000', radius: 50 });
 *   bucket.flush();  // commits all pending changes
 *
 * @version 1.2.0 [Phase 2+ — AoTGeoLayerGroup as registry key, robust init retry]
 * @requires maplibre-gl
 */

(function(global) {
    'use strict';

    // =====================================================
    // RenderBucket Registry (AoTGeoLayerGroup → category → bucket)
    // =====================================================
    // Registry: native maplibregl.Map → { category → RenderBucket }
    // Key is ALWAYS the native map (resolved via _resolveNativeMap in get/destroyMap/destroy).
    // This ensures LayerGroup, compat shim, and native map references all share one bucket per category.
    const _registry = new WeakMap();

    // _getCategoryMap — always takes the canonical key (native map) as argument
    function _getCategoryMap(key) {
        if (!_registry.has(key)) {
            _registry.set(key, new Map());
        }
        return _registry.get(key);
    }

    // =====================================================
    // Default layer specs per category
    // =====================================================
    const DEFAULT_LAYER_SPECS = {
        'sprinkler-coverage': {
            // fill type: ground-plane polygon, perspective-correct when map is pitched.
            // Single shared source+layer keeps MapLibre layer count O(c), not O(n).
            // minzoomFromConfig: hidden below AOT_GEO_CONFIG.equipment_cull_zoom.
            type: 'fill',
            id: 'aot-bucket-sprinkler-coverage',
            sourceId: 'aot-bucket-src-sprinkler-coverage',
            minzoomFromConfig: 'equipment_cull_zoom',
            minzoomDefault: 15,
            paint: {
                'fill-color': ['coalesce', ['get', 'fillColor'], ['get', 'color'], '#007bff'],
                'fill-opacity': ['coalesce', ['get', 'fillOpacity'], 0.3],
                'fill-outline-color': ['coalesce', ['get', 'strokeColor'], ['get', 'color'], '#007bff']
            },
            layout: { visibility: 'visible' }
        },
        'sprinkler-dot': {
            type: 'circle',
            id: 'aot-bucket-sprinkler-dot',
            sourceId: 'aot-bucket-src-sprinkler-dot',
            paint: {
                'circle-radius': ['coalesce', ['get', 'radius'], 3],
                'circle-color': ['coalesce', ['get', 'color'], '#DF5353'],
                'circle-opacity': ['coalesce', ['get', 'fillOpacity'], 1],
                'circle-stroke-width': 0
            },
            layout: { visibility: 'none' }
        },
        'pipe-main': {
            type: 'line',
            id: 'aot-bucket-pipe-main',
            sourceId: 'aot-bucket-src-pipe-main',
            minzoomFromConfig: 'equipment_cull_zoom',
            minzoomDefault: 15,
            paint: {
                'line-color': ['coalesce', ['get', 'color'], '#007bff'],
                'line-width': ['coalesce', ['get', 'weight'], 4],
                'line-opacity': ['coalesce', ['get', 'opacity'], 1]
            },
            layout: { visibility: 'visible' }
        },
        'pipe-branch': {
            type: 'line',
            id: 'aot-bucket-pipe-branch',
            sourceId: 'aot-bucket-src-pipe-branch',
            minzoomFromConfig: 'equipment_cull_zoom',
            minzoomDefault: 15,
            paint: {
                'line-color': ['coalesce', ['get', 'color'], '#0099ff'],
                'line-width': ['coalesce', ['get', 'weight'], 2],
                'line-opacity': ['coalesce', ['get', 'opacity'], 1]
            },
            layout: { visibility: 'visible' }
        },
        'pipe-reference': {
            type: 'line',
            id: 'aot-bucket-pipe-reference',
            sourceId: 'aot-bucket-src-pipe-reference',
            minzoomFromConfig: 'equipment_cull_zoom',
            minzoomDefault: 15,
            paint: {
                'line-color': ['coalesce', ['get', 'color'], '#999999'],
                'line-width': ['coalesce', ['get', 'weight'], 1],
                'line-opacity': ['coalesce', ['get', 'opacity'], 0.5],
                'line-dasharray': [4, 3]
            },
            layout: { visibility: 'visible' }
        },
        'line-generic': {
            type: 'line',
            id: 'aot-bucket-line-generic',
            sourceId: 'aot-bucket-src-line-generic',
            paint: {
                'line-color': ['coalesce', ['get', 'color'], '#888888'],
                'line-width': ['coalesce', ['get', 'weight'], 2],
                'line-opacity': ['coalesce', ['get', 'opacity'], 1]
            },
            layout: { visibility: 'visible' }
        },
        'connection-line': {
            type: 'line',
            id: 'aot-bucket-connection-line',
            sourceId: 'aot-bucket-src-connection-line',
            minzoomFromConfig: 'equipment_cull_zoom',
            minzoomDefault: 15,
            paint: {
                'line-color': ['coalesce', ['get', 'color'], '#888888'],
                'line-width': ['coalesce', ['get', 'weight'], 1],
                'line-opacity': ['coalesce', ['get', 'opacity'], 0.6],
                'line-dasharray': [1, 0]
            },
            layout: { visibility: 'visible' }
        },
        'connection-dot': {
            type: 'circle',
            id: 'aot-bucket-connection-dot',
            sourceId: 'aot-bucket-src-connection-dot',
            minzoomFromConfig: 'equipment_cull_zoom',
            minzoomDefault: 15,
            paint: {
                'circle-radius': ['match', ['get', 'sub_type'],
                                 'mT', 5, 'mbT', 5, 'bT', 4, 'tee', 5, 'elbow', 4,
                                 /* default */ 4],
                'circle-color': ['coalesce', ['get', 'color'], '#666666'],
                'circle-stroke-width': 0
            },
            layout: { visibility: 'visible' }
        }
    };

    // =====================================================
    // RenderBucket Class
    // =====================================================
    class RenderBucket {
        // Normalize to native map as stable, unique registry key.
        // All callers (LayerGroup, compat shim, native map) resolve to the same
        // native maplibregl.Map instance, so they share exactly one bucket per category.
        static get(container, category, customSpec) {
            if (!container) return null;
            const nativeMap = _resolveNativeMap(container);
            const registryKey = nativeMap || container;
            const catMap = _getCategoryMap(registryKey);
            if (!catMap.has(category)) {
                const spec = customSpec || DEFAULT_LAYER_SPECS[category];
                if (!spec) {
                    console.warn('[RenderBucket] No spec for category:', category);
                    return null;
                }
                const bucket = new RenderBucket(container, category, spec);
                catMap.set(category, bucket);
            }
            return catMap.get(category);
        }

        static resolveMLMap(map) {
            return _resolveNativeMap(map);
        }

        static destroyMap(map) {
            if (!map) return;
            const key = _resolveNativeMap(map) || map;
            if (_registry.has(key)) {
                const catMap = _registry.get(key);
                catMap.forEach(b => b.destroy());
                catMap.clear();
                _registry.delete(key);
            }
        }

        // FIX: Constructor now takes container (AoTGeoLayerGroup) as first param
        // mlMap resolution happens in _ensureSourceAndLayer
        constructor(container, category, layerSpec) {
            this._container = container;  // AoTGeoLayerGroup or native map — registry key
            this._mlMap = null;            // Native map — resolved in _ensureSourceAndLayer
            this._category = category;
            this._spec = layerSpec;
            this._sourceId = layerSpec.sourceId;
            this._layerId = layerSpec.id;
            this._features = new Map();
            this._pendingUpserts = new Map();
            this._pendingRemovals = new Set();
            this._pendingStylePatches = new Map();
            this._rafId = null;
            this._destroyed = false;
            this._initialized = false;
            this._initAttempts = 0;  // FIX Bug 4: Track retry attempts
            this._flush = this._flush.bind(this);
        }

        upsert(featureId, feature) {
            if (this._destroyed) return;
            const merged = JSON.parse(JSON.stringify(feature));
            merged.properties = Object.assign({}, feature.properties || {});
            this._pendingUpserts.set(featureId, merged);
            this._pendingRemovals.delete(featureId);
            this._scheduleFlush();
        }

        remove(featureId) {
            if (this._destroyed) return;
            this._pendingRemovals.add(featureId);
            this._pendingUpserts.delete(featureId);
            this._scheduleFlush();
        }

        setStyle(featureId, styleProps) {
            if (this._destroyed) return;
            const existing = this._pendingStylePatches.get(featureId) || {};
            this._pendingStylePatches.set(featureId, Object.assign(existing, styleProps));
            this._scheduleFlush();
        }

        flush() {
            this._flush();
        }

        /**
         * replaceCategory — Replace the entire feature collection in one setData call.
         * Used by rebuildConnections() to eliminate addLayer/removeLayer churn when
         * connection dots change (e.g., after pipe trim).
         *
         * @param {string} category  - Not used here; matches call signature from geometry.js
         * @param {FeatureCollection} newFC - { type:'FeatureCollection', features:[...] }
         */
        replaceCategory(category, newFC) {
            if (this._destroyed) return;
            this._features.clear();
            this._pendingUpserts.clear();
            this._pendingRemovals.clear();
            this._pendingStylePatches.clear();

            if (newFC && newFC.features) {
                newFC.features.forEach(f => {
                    const id = f.properties?.node_id || f.id || 'conn-' + Math.random().toString(36).substr(2, 9);
                    this._features.set(id, JSON.parse(JSON.stringify(f)));
                });
            }

            this._scheduleFlush();
        }

        // FIX: Updated to resolve native map for cleanup
        destroy() {
            if (this._destroyed) return;
            this._destroyed = true;
            if (this._rafId) {
                cancelAnimationFrame(this._rafId);
                this._rafId = null;
            }

            // FIX: Resolve native map for cleanup
            const lg = this._container;
            const mlMap = lg && (lg._originalMap || (lg.getNativeMap && lg.getNativeMap()) || lg._mlMap) || lg;

            if (mlMap) {
                try {
                    if (mlMap.getLayer && mlMap.getLayer(this._layerId)) {
                        mlMap.removeLayer(this._layerId);
                    }
                    if (mlMap.getSource && mlMap.getSource(this._sourceId)) {
                        mlMap.removeSource(this._sourceId);
                    }
                } catch (e) {}
            }

            this._features.clear();
            this._pendingUpserts.clear();
            this._pendingRemovals.clear();
            this._pendingStylePatches.clear();

            const _nativeKey = _resolveNativeMap(this._container) || this._container;
            if (_registry.has(_nativeKey)) {
                _registry.get(_nativeKey).delete(this._category);
            }
        }

        get layerId() { return this._layerId; }
        get sourceId() { return this._sourceId; }
        get size() { return this._features.size; }
        has(featureId) { return this._features.has(featureId) || this._pendingUpserts.has(featureId); }

        eachFeature(callback) {
            this._features.forEach((feature, id) => callback(feature, id));
        }

        _scheduleFlush() {
            if (this._rafId !== null) return;
            this._rafId = requestAnimationFrame(this._flush);
        }

        _flush() {
            this._rafId = null;
            if (this._destroyed) return;

            this._ensureSourceAndLayer();

            const mlMap = this._mlMap;
            // Gate on _initialized (source+layer exist), NOT isStyleLoaded().
            // isStyleLoaded() temporarily returns false while MapLibre processes
            // addSource/addLayer calls from other layers — causing a race where
            // the bucket source exists but _flush exits early and never calls setData.
            if (!mlMap || !this._initialized) return;

            this._pendingStylePatches.forEach((patch, fid) => {
                const upserted = this._pendingUpserts.get(fid);
                if (upserted) {
                    Object.assign(upserted.properties, patch);
                } else {
                    // Patch existing feature in place — without this, setStyle calls
                    // that occur after the initial upsert (e.g. ui._setLayerStyle on
                    // existing pipes) silently fail to update color/weight/etc.
                    const existing = this._features.get(fid);
                    if (existing) {
                        Object.assign(existing.properties, patch);
                    }
                }
            });
            this._pendingStylePatches.clear();

            const fc = { type: 'FeatureCollection', features: [] };

            this._pendingRemovals.forEach(id => this._features.delete(id));
            this._pendingRemovals.clear();

            this._pendingUpserts.forEach((feature, id) => {
                this._features.set(id, feature);
            });
            this._pendingUpserts.clear();

            this._features.forEach(f => fc.features.push(f));

            try {
                const src = mlMap.getSource(this._sourceId);
                if (src) {
                    src.setData(fc);
                } else {
                    console.warn('[RenderBucket] source not found:', this._sourceId, '(initialized=', this._initialized, ')');
                }
            } catch (e) {
                console.warn('[RenderBucket] setData error:', e.message);
            }
        }

        // FIX Bug 4: Robust init with retry logic and isStyleLoaded re-check
        _ensureSourceAndLayer() {
            if (this._initialized && this._initAttempts === 0) return;

            const spec = this._spec;
            const sourceId = this._sourceId;
            const layerId = this._layerId;
            const MAX_INIT_RETRIES = 5;

            const doInit = () => {
                if (this._destroyed) return;

                const mlMap = this._mlMap;
                if (!mlMap) return;

                // FIX: Check isStyleLoaded before each retry
                if (mlMap.isStyleLoaded && !mlMap.isStyleLoaded()) {
                    // Bucket init may run before the style finishes loading. Quick retries
                    // first; if still not ready, wait for the map to go 'idle' (style fully
                    // loaded/rendered) and re-attempt with a fresh budget instead of giving
                    // up. Fixes "map style not ready ... giving up" on slow loads and on
                    // style reloads (mode switch / setStyle), which previously left buckets
                    // (connection-dot, pipe-branch, ...) uncreated so their shapes never rendered.
                    if (this._initAttempts < MAX_INIT_RETRIES) {
                        this._initAttempts++;
                        setTimeout(doInit, 200);
                    } else if ((this._idleWaits = (this._idleWaits || 0) + 1) <= 20) {
                        this._initAttempts = 0;
                        if (mlMap.once) mlMap.once('idle', doInit);
                        else setTimeout(doInit, 500);
                    } else {
                        console.warn('[RenderBucket] map style not ready after extended waits, giving up: ' + sourceId);
                    }
                    return;
                }
                this._initAttempts = 0;
                this._idleWaits = 0;

                // Source creation
                if (!mlMap.getSource(sourceId)) {
                    try {
                        mlMap.addSource(sourceId, {
                            type: 'geojson',
                            data: { type: 'FeatureCollection', features: [] }
                        });
                    } catch (e) {
                        console.warn('[RenderBucket] addSource error (' + sourceId + '):', e.message);
                        if (this._initAttempts < MAX_INIT_RETRIES) {
                            this._initAttempts++;
                            this._initialized = false;
                            setTimeout(doInit, 500);
                        }
                        return;
                    }
                }

                // Layer creation — remove stale layer if type changed (e.g. fill→circle across deploys)
                const existingLayer = mlMap.getLayer(layerId);
                if (existingLayer && existingLayer.type !== spec.type) {
                    try { mlMap.removeLayer(layerId); } catch(re) {}
                }

                if (!mlMap.getLayer(layerId)) {
                    try {
                        const layerDef = {
                            id: layerId,
                            type: spec.type,
                            source: sourceId,
                            paint: Object.assign({}, spec.paint),
                            layout: Object.assign({}, spec.layout || {})
                        };
                        // minzoomFromConfig: dynamically read AOT_GEO_CONFIG (e.g. equipment_cull_zoom)
                        if (spec.minzoomFromConfig) {
                            const cfg = (typeof window !== 'undefined' && window.AOT_GEO_CONFIG) || {};
                            const z = cfg[spec.minzoomFromConfig];
                            layerDef.minzoom = (z != null) ? z : (spec.minzoomDefault != null ? spec.minzoomDefault : 0);
                        } else if (spec.minzoom != null) {
                            layerDef.minzoom = spec.minzoom;
                        }
                        mlMap.addLayer(layerDef);
                        this._initialized = true;

                        // Flush pending data now that source+layer exist
                        this._scheduleFlush();
                    } catch (e) {
                        console.warn('[RenderBucket] addLayer error (' + layerId + '):', e.message);
                        if (this._initAttempts < MAX_INIT_RETRIES) {
                            this._initAttempts++;
                            this._initialized = false;
                            setTimeout(doInit, 500);
                        }
                        return;
                    }
                } else {
                    this._initialized = true;
                    // Layer already existed with correct type — flush pending data
                    this._scheduleFlush();
                }
            };

            // Resolve native map via shared helper (handles AoTGeoLayerGroup._map._originalMap chain).
            // Always re-resolve — _container may be a shim that becomes wired up later.
            const nativeMap = _resolveNativeMap(this._container);
            this._mlMap = nativeMap;

            if (!this._mlMap) {
                // Native map not yet available — retry shortly
                setTimeout(() => { if (!this._destroyed) this._ensureSourceAndLayer(); }, 200);
                return;
            }

            // Single-fire guard so 'load' event AND timeout fallback don't both run doInit.
            // Without this fallback, if the 'load' event already fired before once() registered,
            // the bucket would never initialize (was the pipe-main bug: _initialized stuck false,
            // _pendingUpserts piling up indefinitely).
            let _initFired = false;
            const safeDoInit = () => {
                if (_initFired || this._destroyed) return;
                _initFired = true;
                doInit();
            };

            if (this._mlMap.isStyleLoaded && this._mlMap.isStyleLoaded()) {
                safeDoInit();
            } else {
                if (this._mlMap.once) {
                    this._mlMap.once('load', safeDoInit);
                }
                setTimeout(safeDoInit, 500);
            }
        }
    }

    // _resolveNativeMap — resolves any container to the native maplibregl.Map instance
    function _resolveNativeMap(container) {
        if (!container) return null;
        if (container._originalMap) return container._originalMap;
        if (container.getNativeMap) return container.getNativeMap();
        if (container._mlMap) return container._mlMap;
        if (container.addSource && container.loaded) return container; // native map
        if (container._isAoTLayerGroup && container._map) return _resolveNativeMap(container._map);
        if (container._aotLayer && container._aotLayer._map) return _resolveNativeMap(container._aotLayer._map);
        if (container._map && typeof container._map.addSource === 'function') return _resolveNativeMap(container._map);
        return null;
    }

    // Keep _resolveMLMap for backward compatibility (alias)
    function _resolveMLMap(map) {
        return _resolveNativeMap(map);
    }

    global.RenderBucket = RenderBucket;


})(window);
