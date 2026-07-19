/**
 * aot-map-loader.js
 * Standardized Map Initialization for AoT
 * Handles Global Configuration, Settings, and Layer Loading
 */

// [Iteration 16] Emergency Master Shield Guard
// Ensures that DomUtil.remove is patched even if parent layout globalization was bypassed.
(function() {
    function applyShield() {
        if (typeof L !== 'undefined' && L.DomUtil && L.DomUtil.remove) {
            if (L.DomUtil.__AOT_MASTER_SHIELD) return;
            L.DomUtil.__AOT_MASTER_SHIELD = true;
            const origRem = L.DomUtil.remove;
            L.DomUtil.remove = function(el) {
                if (!el) return;
                try {
                    if (typeof el === 'object' && ('parentNode' in el) && el.parentNode) {
                        origRem.call(L.DomUtil, el); 
                    }
                } catch(e) { /* Silent */ }
            };
        }
    }
    applyShield();
    // Re-check after 500ms just in case L was re-loaded
    setTimeout(applyShield, 500);
})();

/**
 * [AoT] Bing Maps / QuadKey Support
 * Extends L.TileLayer to support {q} placeholder which converts (x, y, z) to QuadKey.
 */
if (typeof L !== 'undefined') {
    L.TileLayer.QuadKey = L.TileLayer.extend({
        getTileUrl: function (coords) {
            var i = coords.z, x = coords.x, y = coords.y;
            var quadKey = "";
            for (var j = i; j > 0; j--) {
                var digit = 0;
                var mask = 1 << (j - 1);
                if ((x & mask) != 0) digit += 1;
                if ((y & mask) != 0) digit += 2;
                quadKey += digit;
            }
            // Use parent's getTileUrl but replace {q} with calculated quadKey
            return L.TileLayer.prototype.getTileUrl.call(this, coords).replace('{q}', quadKey);
        }
    });
    L.tileLayer.quadKey = function(url, options) {
        return new L.TileLayer.QuadKey(url, options);
    };
}

if (!window.AoTMapLoader) {
    window.AoTMapLoader = {

    /**
     * Initializes a Leaflet map with standard AoT configuration
     * @param {string} containerId - DOM ID of map container
     * @param {Object} overrideOptions - Optional overrides 
     *        { lat, lng, zoom, layerType: 'xyz'|'wms', layers: [] }
     * @returns {Object} { map, baseLayers, activeLayer }
     */
    /**
     * Initialize Leaflet Map
     * @param {string} containerId - DOM ID of map container
     * @param {string} mapType - Preset type ('geo_setting_map', 'geo_input_map', 'general_map')
     * @param {object} customOptions - Overrides for Leaflet options
     * @returns {object} { map, baseLayers }
     */
    initMap: function (containerId, mapType = 'default', customOptions = {}) {
        // 1. Resolve Config & Presets
        const config = window.AOT_GEO_CONFIG || {};
        // [Fix] config IS the settings object (flat structure from backend). 
        // There is no nested 'settings' key.
        const settings = config;

        // Helper: Strict False check (handles 0, 'false', false)
        // Default is true if undefined, unless logic says otherwise
        const isTrue = (val, def = true) => {
            if (val === false || val === 'false' || val === 0 || val === '0') return false;
            if (val === true || val === 'true' || val === 1 || val === '1') return true;
            return def;
        };

        // Base Options (Global preferences from Config)
        // [New Logic] Read Positional Settings from Config (Source of Truth)
        // Robust parsing: Handle 0 value correctly (don't fallback on 0).
        let defaultLat = parseFloat(settings.default_lat);
        if (isNaN(defaultLat)) defaultLat = 37.5665;

        let defaultLng = parseFloat(settings.default_lng);
        if (isNaN(defaultLng)) defaultLng = 126.9780;

        let defaultZoom = parseFloat(settings.zoom);
        if (isNaN(defaultZoom)) defaultZoom = 12;

        let maxZoom = parseInt(settings.max_zoom);
        if (isNaN(maxZoom)) maxZoom = 25;

        const globalOptions = {
            center: [defaultLat, defaultLng],
            zoom: defaultZoom,
            maxZoom: maxZoom,
            preferCanvas: isTrue(settings.prefer_canvas, true),
            fadeAnimation: isTrue(settings.tile_fade_animation, true),
            zoomAnimation: isTrue(settings.tile_fade_animation, true),
            markerZoomAnimation: isTrue(settings.tile_fade_animation, true),
            zoomSnap: isTrue(settings.smooth_zoom, true) ? 0.25 : 1,
            zoomDelta: isTrue(settings.smooth_zoom, true) ? 0.25 : 1,
            attributionControl: false
        };

        // Presets per Map Type
        const presets = {
            'geo_setting_map': {
                zoomControl: false, // Custom controls used
                scrollWheelZoom: true,
                doubleClickZoom: true,
                dragging: true
            },
            'geo_input_map': {
                zoomControl: true,
                scrollWheelZoom: true,
                doubleClickZoom: true,
                dragging: true,
                trackResize: true
            },
            'general_map': {
                zoomControl: true,
                scrollWheelZoom: true,
                dragging: true
            },
            'default': {
                zoomControl: true
            }
        };

        const presetOptions = presets[mapType] || presets['default'];

        // Merge: Global Defaults < Preset < Custom Overrides
        const finalOptions = Object.assign({}, globalOptions, presetOptions, customOptions);

        // [Fix] Remove 'layers' from options passed to L.map
        // Leaflet expects 'layers' to be an array of ILayer objects, but we pass config objects.
        // We will handle layer addition manually in Step 3.
        const mapOptions = { ...finalOptions };
        delete mapOptions.layers;

        // 2. Create Map (Pure MapLibre GL via AoTMapLibreLoader)
        let map = null;
        if (typeof AoTMapLibreLoader !== 'undefined') {
            // Use pure MapLibre loader for 3D support (pitch, bearing, terrain)
            const mlMap = AoTMapLibreLoader.initMap(containerId, {
                center: [defaultLng, defaultLat],
                zoom: defaultZoom,
                maxZoom: maxZoom,
                pitch: mapOptions.pitch || 0,
                bearing: mapOptions.bearing || 0,
                zoomControl: mapOptions.zoomControl !== false,
                scrollWheelZoom: mapOptions.scrollWheelZoom !== false
            });
            // Wrap the MapLibre map in L.map-compatible interface
            if (mlMap && typeof L !== 'undefined' && L.Map) {
                // Create L.map wrapper and inject the MapLibre map
                map = L.map(containerId, mapOptions);
                // Replace the internally-created MapLibre map with the AoTMapLibreLoader one
                if (map._mlMap && map._mlMap.remove) {
                    map._mlMap.remove(); // Remove the auto-created one
                }
                map._mlMap = mlMap; // Use the AoTMapLibreLoader's map (3D-ready)
                // Re-sync events
                const self = map;
                mlMap.on('click', (e) => self._emit('click', { latlng: new L.LatLng(e.lngLat.lat, e.lngLat.lng) }));
                mlMap.on('dblclick', (e) => self._emit('dblclick', { latlng: new L.LatLng(e.lngLat.lat, e.lngLat.lng) }));
                mlMap.on('contextmenu', (e) => self._emit('contextmenu', { latlng: new L.LatLng(e.lngLat.lat, e.lngLat.lng) }));
                mlMap.on('zoom', () => self._emit('zoom'));
                mlMap.on('move', () => self._emit('move'));
                mlMap.on('moveend', () => self._emit('moveend'));
                mlMap.on('layeradd', (e) => self._emit('layeradd', { layer: e.layer }));
                mlMap.on('overlayadd', (e) => self._emit('overlayadd', { layer: e.layer }));
                mlMap.on('overlayremove', (e) => self._emit('overlayremove', { layer: e.layer }));
                mlMap.on('resize', () => self._emit('resize'));
            } else if (mlMap) {
                map = mlMap; // Use MapLibre map directly as fallback
            }
        }
        // Fallback: Use L.map shim (MapLibre-backed)
        if (!map && typeof L !== 'undefined' && typeof L.map !== 'undefined') {
            map = L.map(containerId, mapOptions);
        }
        if (!map) {
            return { map: null, baseLayers: {}, overlays: {}, activeLayer: null, layerControl: null };
        }

        // [New] Virtual Layers for "Data Only" mode
        map.aotVirtualLayers = [];

        // [Fix] Add Attribution Control EARLY (Before layers)
        // This ensures layers added in step 3 register their attribution correctly.
        // User requested Bottom-Left.
        // Z-Index: Set lower than tools (which are usually 1000+ or handled by containers).
        // [Fix] Add Attribution Control via Central Utility
        // This ensures consistent behavior (VWorld Logo injection, positioning)
        if (window.AoTMapUtils && window.AoTMapUtils.addCopyrightControl) {
            window.AoTMapUtils.addCopyrightControl(map);
        } else if (map._mlMap && maplibregl && maplibregl.AttributionControl) {
            // MapLibre: use native attribution
            map._mlMap.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
        } else if (typeof L !== 'undefined' && L.control && L.control.attribution) {
            // Fallback: L shim attribution
            L.control.attribution({ prefix: false, position: 'bottomleft' }).addTo(map);
        }

        // 3. Add Layers (Base Maps & Overlays)
        // Allow override from customOptions (e.g. for Preview Map to be clean)
        const layers = (customOptions.layers !== undefined) ? customOptions.layers : (config.layers || []);
        map.aotBaseMaps = {};
        map.aotOverlayMaps = {};
        let activeBaseLayer = null;

        // Helper to get or create Layer Control
        let layerControl = null;
        const ensureLayerControl = () => {
            if (!layerControl) {
                // Create if not exists (showing whatever base/overlays we have so far)
                if (Object.keys(map.aotBaseMaps).length > 0 || Object.keys(map.aotOverlayMaps).length > 0) {
                    if (map._mlMap && maplibregl && maplibregl.NavigationControl) {
                        // MapLibre: use navigation control instead of layer switcher
                        // Layer management is handled via source/layer visibility
                        map._mlMap.addControl(new maplibregl.NavigationControl({ showCompass: true, showZoom: true }), 'top-right');
                    }
                    layerControl = L.control.layers(map.aotBaseMaps, map.aotOverlayMaps).addTo(map);
                }
            }
            return layerControl;
        };

        layers.forEach(l => {
            let layerFunc = null;
            let finalUrl = l.url;
            const finalOpts = { ...l.options };

            // [Common] Relative Date Calculation
            // Supports keywords: today, 1_day_ago, 2_days_ago, 7_days_ago
            if (finalOpts.date_mode) {
                const mode = finalOpts.date_mode;
                const now = new Date();
                let dateStr = 'default';

                if (mode === 'today') {
                    dateStr = now.toISOString().split('T')[0];
                } else if (mode === '1_day_ago') {
                    now.setDate(now.getDate() - 1);
                    dateStr = now.toISOString().split('T')[0];
                } else if (mode === '2_days_ago') {
                    now.setDate(now.getDate() - 2);
                    dateStr = now.toISOString().split('T')[0];
                } else if (mode === '7_days_ago') {
                    now.setDate(now.getDate() - 7);
                    dateStr = now.toISOString().split('T')[0];
                } else if (mode === 'custom' && finalOpts.target_date) {
                    dateStr = finalOpts.target_date;
                }

                if (dateStr !== 'default') {
                    finalOpts.time = dateStr;
                }
            }

            // [Fix] Generic Placeholder Replacement from finalOpts
            // This replaces {time}, {layer}, {style}, {tilematrixset}, etc.
            if (finalUrl && finalOpts) {
                Object.keys(finalOpts).forEach(key => {
                    const val = finalOpts[key];
                    if (typeof val === 'string' || typeof val === 'number') {
                        // Use regex for global replacement of {key}
                        finalUrl = finalUrl.split('{' + key + '}').join(val);
                    }
                });
            }

            // Resolve API Keys (Explicit fallback if not in options)
            if (l.api_key) {
                finalUrl = finalUrl.split('{api_key}').join(l.api_key)
                                   .split('{key}').join(l.api_key)
                                   .split('{accessToken}').join(l.api_key);
                finalOpts['accessToken'] = l.api_key;
                finalOpts['key'] = l.api_key;
                finalOpts['apikey'] = l.api_key;
            } else if (config.keys) {
                const kf = l.key_field || (l.requires_key ? 'default' : null);
                if (kf && config.keys[kf]) {
                    const k = config.keys[kf];
                    finalUrl = finalUrl.split('{api_key}').join(k)
                                       .split('{key}').join(k)
                                       .split('{accessToken}').join(k);
                }
            }

            // [Fix] Inject Attribution from Layer Config if available
            if (l.attribution && !finalOpts.attribution) {
                finalOpts.attribution = l.attribution;
            }

            // [New Logic] Digital Zoom Handling
            const useDigital = isTrue(settings.digital_zoom, true);
            if (useDigital) {
                // Ensure number formatting (handle string inputs from config)
                let layerMax = finalOpts.maxZoom;
                if (layerMax !== undefined) layerMax = parseInt(layerMax, 10);

                let layerNative = finalOpts.maxNativeZoom;
                if (layerNative !== undefined) layerNative = parseInt(layerNative, 10);

                // If native max is missing or invalid
                if (layerNative === undefined || isNaN(layerNative)) {
                    // Infers from maxZoom if available (e.g. Esri=17)
                    if (layerMax !== undefined && !isNaN(layerMax)) {
                        finalOpts.maxNativeZoom = layerMax;
                    } else {
                        finalOpts.maxNativeZoom = 19; // Default Standard
                    }
                } else {
                    // Explicit native max exists
                    finalOpts.maxNativeZoom = layerNative;
                }

                // Debug Log for Esri (or high diff layers)
                if (l.name && (l.name.includes('Esri') || l.name.includes('Satellite'))) {
                    /* console.log(`[AoTMapLoader] Digital Zoom Active for ${l.name}:`, {
                        native: finalOpts.maxNativeZoom,
                        scalingTo: finalOptions.maxZoom,
                        configMax: finalOpts.maxZoom
                    }); */
                }

                // Force global max to allow scaling
                finalOpts.maxZoom = finalOptions.maxZoom;
            }

            // [Fix] RainViewer Global Support - Vector Mode (MapLibre) and Raster Mode (Leaflet)
            // RainViewer provides historical radar data via PNG tiles
            if (finalUrl && finalUrl.includes('{ts}')) {
                // Fetch timestamp metadata from backend proxy
                fetch('/api/geo/proxy/rainviewer/meta')
                    .then(r => {
                        if (!r.ok) throw new Error("RainViewer API error");
                        return r.json();
                    })
                    .then(data => {
                        // Extract timestamps for animation
                        let timestamps = [];
                        if (data.radar && data.radar.past) {
                            data.radar.past.forEach(item => {
                                if (item.time) timestamps.push(item.time);
                            });
                        }
                        
                        if (timestamps.length === 0) {
                            return;
                        }
                        
                        // Get the most recent timestamp
                        const lastTs = timestamps[timestamps.length - 1];
                        const realUrl = finalUrl.replace('{ts}', lastTs);
                        
                        // Check if we're in vector mode (MapLibre) or raster mode (Leaflet)
                        if (typeof window.AoTVectorLayerManager !== 'undefined' && 
                            window.AOT_GEO_CONFIG && 
                            window.AOT_GEO_CONFIG.geo_mode === 'vector') {
                            
                            // === Vector Mode: Use MapLibre raster source ===
                            if (typeof maplibregl !== 'undefined') {
                                const vectorManager = window.AoTVectorLayerManager.bind(map);
                                
                                // Configure RainViewer for MapLibre
                                const rainviewerConfig = {
                                    url: finalUrl,
                                    currentTimestamp: lastTs,
                                    colorScheme: l.color_scheme || '2',
                                    smoothing: l.smoothing !== false,
                                    opacity: finalOpts.opacity || 0.7,
                                    maxZoom: finalOpts.maxNativeZoom || 7,
                                    frameInterval: 600,
                                    totalFrames: timestamps.length
                                };
                                
                                vectorManager.addRainViewerSource(l.id, rainviewerConfig);
                                
                                // Store reference for animation control
                                map.aotVectorLayerManager = vectorManager;
                                map.aotRainViewerTimestamps = timestamps;
                                
                                
                                // Auto-start animation if visible
                                if (l.visible !== false) {
                                    setTimeout(() => {
                                        if (vectorManager.layers.has(l.id)) {
                                            vectorManager.startRainViewerAnimation(l.id, timestamps, 600);
                                        }
                                    }, 1000);
                                }
                            } else {
                            }
                        } else if (window.L && typeof L !== 'undefined') {
                            // === Raster Mode: Use Leaflet ===
                            let rvLayer = null;
                            if (l.type === 'xyz') rvLayer = L.tileLayer(realUrl, finalOpts);
                            else if (l.type === 'wms') rvLayer = L.tileLayer.wms(realUrl, finalOpts);

                            if (rvLayer) {
                                rvLayer.aot_id = l.id;
                                rvLayer.aot_base_id = l.base_id || l.id;
                                rvLayer.name = l.name;
                                if (l.legend) {
                                    rvLayer.aot_legend = l.legend;
                                }

                                map.aotOverlayMaps[l.name] = rvLayer;

                                let shouldAdd = false;
                                if (l.visible !== undefined && l.visible !== null) {
                                    shouldAdd = (l.visible === true || l.visible === 'true');
                                } else {
                                    shouldAdd = (l.is_active || l.is_default);
                                }

                                if (shouldAdd) {
                                    rvLayer.addTo(map);
                                }

                                const ctl = ensureLayerControl();
                                if (ctl) {
                                    ctl.addOverlay(rvLayer, l.name);
                                } else {
                                    layerControl = L.control.layers(map.aotBaseMaps, map.aotOverlayMaps).addTo(map);
                                }
                                
                                if (shouldAdd && typeof updateLegendAndSyncPanel === 'function') {
                                    updateLegendAndSyncPanel();
                                }
                                
                            }
                        } else {
                        }
                    }).catch(e => { 
                    });
                return; // Skip sync creation
            }

            // [Fix] Skip invalid URLs with unreplaced placeholders to prevent crash
            if (finalUrl && finalUrl.match(/\{(x|y|z|s|r|q)\}/) === null && finalUrl.match(/\{([a-zA-Z0-9_]+)\}/)) {
                // URL has placeholders OTHER than x,y,z,s,r (e.g. {key}, {style} missing)
                // console.warn("[AoTMapLoader] Skipping layer with unreplaced placeholders:", l.name, finalUrl);
                return;
            }

            if (l.type === 'vector' && finalUrl) {
                // Vector tile layer via MapLibre GL (rendered inside Leaflet via bridge)
                if (typeof L.MapLibreGL !== 'undefined') {
                    layerFunc = L.maplibreGL({
                        style: finalUrl,
                        attribution: finalOpts.attribution || l.attribution || ''
                    });
                } else {
                    // Bridge not loaded: fall back to blank placeholder so the map still opens
                }
            } else if (l.type === 'xyz' && finalUrl) {
                // [New] Check for QuadKey placeholder
                if (finalUrl.indexOf('{q}') !== -1) {
                    layerFunc = L.tileLayer.quadKey(finalUrl, finalOpts);
                } else {
                    layerFunc = L.tileLayer(finalUrl, finalOpts);
                }
            } else if (l.type === 'wms' && finalUrl) {
                layerFunc = L.tileLayer.wms(finalUrl, finalOpts);
            } else if (l.type === 'none') {
                // Data-only layer (e.g. KMA Weather): no tile overlay, legend only.
                // Empty LayerGroup acts as a valid Leaflet layer so it registers in the
                // layer control and fires overlayadd/overlayremove for legend toggling.
                layerFunc = L.layerGroup([]);
            } else if (l.data || l.type === 'geojson') {
                // [New] GeoJSON Support
                // If backend provided data content (e.g. SGIS stats), render it as GeoJSON
                try {
                    layerFunc = L.geoJSON(l.data, {
                        onEachFeature: function (feature, layer) {
                            if (feature.properties && feature.properties.popupContent) {
                                layer.bindPopup(feature.properties.popupContent);
                            }
                        },
                        pointToLayer: function (feature, latlng) {
                            // Simple Circle Marker
                            return L.circleMarker(latlng, {
                                radius: 8,
                                fillColor: "#ff7800",
                                color: "#000",
                                weight: 1,
                                opacity: 1,
                                fillOpacity: 0.8
                            });
                        }
                    });
                } catch (e) {
                }
            } else if (l.type === 'image' && finalOpts.render_mode === 'tiled' && finalOpts.tile_url) {
                // [New] Large aerial/drone photo rendered as an XYZ tile pyramid
                // (zoom-responsive) instead of a single image source. Plain
                // Leaflet tile layer; opacity + native zoom carried from options.
                try {
                    let tOpts = { ...finalOpts };
                    let tOpacity = parseFloat(finalOpts.opacity);
                    if (!isNaN(tOpacity)) tOpts.opacity = tOpacity;
                    let mnz = parseInt(finalOpts.minzoom, 10);
                    let mxz = parseInt(finalOpts.maxzoom, 10);
                    if (!isNaN(mnz)) tOpts.minNativeZoom = mnz;
                    if (!isNaN(mxz)) tOpts.maxNativeZoom = mxz;
                    layerFunc = L.tileLayer(finalOpts.tile_url, tOpts);
                } catch (e) {
                    // Never let a tiled-overlay error abort the rest of the loop.
                }
            } else if (l.type === 'image' && finalUrl) {
                // [New] Aerial / drone photo overlay.
                // Rendered directly on the underlying MapLibre map as a
                // georeferenced `image` source (4 corner coordinates). A
                // lightweight, empty Leaflet layerGroup is used purely as the
                // toggle handle in the layer control; the actual MapLibre
                // source/layer is added/removed by the image-overlay helpers
                // wired into overlayadd/overlayremove below.
                try {
                    let imgCoords = finalOpts.coordinates;
                    if (typeof imgCoords === 'string') {
                        try { imgCoords = JSON.parse(imgCoords); } catch (e) { imgCoords = null; }
                    }
                    if (imgCoords && imgCoords.length === 4) {
                        layerFunc = L.layerGroup([]);
                        let imgOpacity = parseFloat(finalOpts.opacity);
                        if (isNaN(imgOpacity)) imgOpacity = 0.85;
                        layerFunc._aotImage = {
                            id: l.id,
                            url: finalUrl,
                            coordinates: imgCoords,
                            opacity: imgOpacity,
                            visible: (l.visible === true || l.visible === 'true')
                        };
                    }
                } catch (e) {
                    // Never let an image-overlay error abort the rest of the loop.
                }
            }

            if (layerFunc) {
                // Attach Metadata for Persistence Tracking
                layerFunc.aot_id = l.id; // Unique GeoLayer ID (Exploded if applicable)
                layerFunc.aot_base_id = l.base_id || l.id; // [Fix] Track DB ID
                layerFunc.name = l.name; // [Fix] Store name for virtual layer persistence

                // [New] Attach Legend Data
                if (l.legend) {
                    layerFunc.aot_legend = l.legend;
                }

                if (l.channel_id !== undefined) {
                    layerFunc.aot_channel_id = l.channel_id;
                }

                // Check if Base Layer
                // Support both legacy 'is_base' and new 'role' property
                const isBase = (l.is_base === true) || (l.role === 'base');

                if (isBase) {
                    map.aotBaseMaps[l.name] = layerFunc;

                    const isExplicit = (l.visible === true || l.visible === 'true');

                    if (isExplicit) {
                        // Found saved preference: Replace any existing active layer
                        if (activeBaseLayer) {
                            map.removeLayer(activeBaseLayer);
                        }
                        layerFunc.addTo(map);
                        activeBaseLayer = layerFunc;
                        activeBaseLayer.isExplicit = true;
                    } else {
                        // Not explicit: Default to first base layer appearing (Fallback)
                        if (!activeBaseLayer) {
                            layerFunc.addTo(map);
                            activeBaseLayer = layerFunc;
                            activeBaseLayer.isFallback = true;
                        } else if (activeBaseLayer.isFallback === true) {
                            // Keep fallback until explicit found
                        }
                    }
                } else {
                    map.aotOverlayMaps[l.name] = layerFunc;
                    // Overlays are usually OFF by default unless specified
                    // Check if explicit active flag or strictly overlay role with active flag

                    // [Fix] Respect explicit 'visible' property from backend (User Preference)
                    let shouldAdd = false;
                    if (l.visible !== undefined && l.visible !== null) {
                        shouldAdd = (l.visible === true || l.visible === 'true');
                    } else {
                        // Fallback to legacy is_active behavior
                        shouldAdd = (l.is_active || l.is_default);
                    }

                    if (shouldAdd) {
                        // [New] Overlay Data Only Support
                        // If enabled, we do NOT add to map (no tiles), but track it for Legends.
                        if (customOptions.overlayDataOnly) {
                            // console.log(`[AoTMapLoader] "${l.name}" added as Data-Only layer.`);
                            map.aotVirtualLayers.push(layerFunc);
                            // Note: No 'layeradd' event fired, so we must trigger updateLegend manually at end.
                        } else {
                            layerFunc.addTo(map);
                        }
                    }
                }
            }
        });

        // Fallback: If no BASE layer found, add Default OSM
        if (!activeBaseLayer) {
            // [UX] Demote to info/log to avoid user panic. It is standard behavior.
            // console.log("[AoTMapLoader] Using fallback OSM (No custom base layer active).");
 
            // Check Digital Zoom for Fallback
            const useDigital = isTrue(settings.digital_zoom, true);
            const osmOpts = {
                attribution: '© OpenStreetMap'
            };

            if (useDigital) {
                osmOpts.maxNativeZoom = 19;
                osmOpts.maxZoom = globalOptions.maxZoom || 25;
            } else {
                osmOpts.maxZoom = 19;
            }

            const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', osmOpts);
            osm.addTo(map);
            activeBaseLayer = osm;
            map.aotBaseMaps['OpenStreetMap'] = osm;
        }

        // 4. Add Layer Control
        // [UX] Always add if we have at least one layer (even if just Fallback OSM).
        // This ensures the "Layer Manager" icon appears, confirming it's working.
        if (Object.keys(map.aotBaseMaps).length > 0 || Object.keys(map.aotOverlayMaps).length > 0) {
            layerControl = L.control.layers(map.aotBaseMaps, map.aotOverlayMaps).addTo(map);
        }

        // 5. Add Legend Control (Generic)
        const legendControl = L.control({ position: 'bottomright' });

        legendControl.onAdd = function (map) {
            const div = L.DomUtil.create('div', 'aot-legend-container');
            div.style.display = 'none'; // Hidden by default

            // Note: Styles are now handled in map.css (.aot-legend-container)
            // margins are handled by .leaflet-bottom .leaflet-control spacing or CSS.

            return div;
        };
        legendControl.addTo(map);

        // [Fix] Add wrapper class for mobile positioning control
        if (legendControl.getContainer()) {
            legendControl.getContainer().classList.add('aot-legend-wrapper-control');
        }

        // Helper: Refresh Legend Content
        let legendMoveListener = null;

        const updateLegend = () => {
            const container = legendControl.getContainer();

            // Clear previous move listener
            if (legendMoveListener) {
                map.off('moveend', legendMoveListener);
                legendMoveListener = null;
            }

            if (!container) return;
            container.innerHTML = ''; // Reset
            container.style.display = 'none';

            // Find all visible layers with a legend (Map Layers + Virtual Layers)
            const targetLayers = [];

            // 1. Visible Map Layers
            map.eachLayer(layer => {
                if (layer.aot_legend) {
                    targetLayers.push(layer);
                }
            });

            // 2. Virtual Data Layers
            if (map.aotVirtualLayers && map.aotVirtualLayers.length > 0) {
                map.aotVirtualLayers.forEach(layer => {
                    if (layer.aot_legend) {
                        targetLayers.push(layer);
                    }
                });
            }
 
            // console.log("[LegendDebug] Layers with legends found:", targetLayers.length);
 
            if (targetLayers.length === 0) {
                return;
            }

            container.style.display = 'block';

            // Render Stacked Legends
            targetLayers.forEach((layer, index) => {
                const legendData = layer.aot_legend;
                const wrapper = L.DomUtil.create('div', 'aot-legend-item-wrapper');

                if (legendData.type === 'html') {
                    wrapper.innerHTML = legendData.content;

                    // Inject API Key into Value Box for Dynamic Fetching
                    const valueBox = wrapper.querySelector('.aot-legend-value-box');
                    const apiKey = layer.options ? (layer.options.apiKey || layer.options.api_key) : null;

                    if (valueBox && apiKey) {
                        valueBox.dataset.apiKey = apiKey;
                    }

                } else if (legendData.type === 'img') {
                    wrapper.innerHTML = `<img src="${legendData.url}" alt="Legend" style="max-width:100%;">`;
                }

                container.appendChild(wrapper);
            });

            // Setup Dynamic Updater
            const fetchAllValues = () => {
                // [Fix] Visibility Guard to prevent fetching when hidden
                if (container.offsetParent === null) return;

                const boxes = container.querySelectorAll('.aot-legend-value-box');
                if (boxes.length === 0) return;

                const center = map.getCenter();

                boxes.forEach(box => {
                    const apiKey = box.dataset.apiKey; // Optional now
                    const paramPath = box.getAttribute('data-api-param'); // Required
                    const customUrl = box.getAttribute('data-api-url');   // Optional
                    const valueText = box.querySelector('.aot-legend-value-text');

                    if (!valueText || !paramPath) return;

                    // Determine URL
                    let url = '';
                    if (customUrl) {
                        // Round to 3 decimal places (~111m precision) to maximise cache hits.
                        // ISRIC SoilGrids native resolution is ~250m, so this loses no useful precision.
                        const rLat = Math.round(center.lat * 1000) / 1000;
                        const rLng = Math.round(center.lng * 1000) / 1000;
                        url = customUrl.replace('{lat}', rLat)
                            .replace('{lon}', rLng)
                            .replace('{lng}', rLng)
                            .replace('{apiKey}', apiKey || '');
                    } else {
                        if (!apiKey) return;
                        url = `https://api.openweathermap.org/data/2.5/weather?lat=${center.lat}&lon=${center.lng}&appid=${apiKey}&units=metric`;
                    }

                    /* 
```javascript
                    // [Temporarily Unblocked per user request]
                    if (url.includes('isric.org')) {
                        valueText.innerText = '-';
                        return;
                    }
                    */

                    valueText.innerText = '...';

                    // [Fix] Use AoTAPIManager for caching and deduplication
                    const requestPromise = window.AoTAPIManager 
                        ? window.AoTAPIManager.request(url)
                        : fetch(url).then(r => r.json());
                    
                    requestPromise.then(data => {
                            const keys = paramPath.split('.');
                            let val = data;
                            for (let k of keys) {
                                if (val && k in val) {
                                    val = val[k];
                                } else if (val && !isNaN(parseInt(k)) && Array.isArray(val)) {
                                    val = val[parseInt(k)];
                                } else {
                                    val = undefined;
                                    break;
                                }
                            }

                            if (val !== undefined && val !== null) {
                                let finalVal = parseFloat(val);
                                
                                const dFactor = box.getAttribute('data-d-factor');
                                if (dFactor) {
                                    finalVal = finalVal / parseFloat(dFactor);
                                }

                                valueText.innerText = Math.round(finalVal * 100) / 100;
                            } else {
                                valueText.innerText = '-';
                            }
                        })
                        .catch(err => {
                            valueText.innerText = 'Error';
                            valueText.title = 'Failed to fetch data. Check console.';
                        });
                });
            };

            // Register Listener (Debounced)
            let debounceTimer;
            legendMoveListener = () => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    fetchAllValues();
                }, 500);
            };
            map.on('moveend', legendMoveListener);

            // Initial Fetch (Delayed to prevent thread blocking during load)
            setTimeout(fetchAllValues, 200);
        };

        // Listeners for Layer Changes
        const updateLegendAndSyncPanel = () => {
            updateLegend();
            // [Fix] Also sync MeasurementPanel layout for side-by-side desktop view
            if (map._aotMeasurementPanel) {
                map._aotMeasurementPanel.adjustLayout();
            }
        };

        // [Fix] Overlay Data Only Interceptor
        // Intercepts layer control events to prevent tile display in overlay_data_only mode
        map._aotOverlayDataOnly = !!customOptions.overlayDataOnly;

        if (map._aotOverlayDataOnly) {
            map.on('overlayadd', function(e) {
                // Intercept all overlay adds: remove tile layer from map, add to virtual layers
                map.removeLayer(e.layer);
                if (!map.aotVirtualLayers) map.aotVirtualLayers = [];
                map.aotVirtualLayers.push(e.layer);
                updateLegendAndSyncPanel();
            });

            map.on('overlayremove', function(e) {
                // Remove from virtual layers array if present
                if (map.aotVirtualLayers) {
                    const idx = map.aotVirtualLayers.indexOf(e.layer);
                    if (idx !== -1) {
                        map.aotVirtualLayers.splice(idx, 1);
                        updateLegendAndSyncPanel();
                    }
                }
            });
        }

        map.on('overlayadd', updateLegendAndSyncPanel);
        map.on('overlayremove', updateLegendAndSyncPanel);
        map.on('layerremove', updateLegendAndSyncPanel);

        // Also initial update
        setTimeout(updateLegendAndSyncPanel, 300);

        // [New] Aerial / drone photo image overlays.
        // Drawn directly on the underlying MapLibre map as georeferenced `image`
        // sources. The Leaflet layerGroup handle (created in the layer loop)
        // drives visibility via overlayadd/overlayremove. Helpers are also
        // exposed on the map so the config / correction UI can refresh a live
        // overlay's corners or opacity without a full reload.
        const _mlForImg = map._mlMap || map.maplibreMap || null;
        const _aotImgIds = (id) => ({
            srcId: 'aot_imgov_' + id,
            lyrId: 'aot_imgov_' + id + '_layer'
        });
        const _aotImgAdd = (ov) => {
            if (!_mlForImg || !ov || !ov.coordinates) return;
            const run = () => {
                try {
                    const { srcId, lyrId } = _aotImgIds(ov.id);
                    if (_mlForImg.getLayer(lyrId)) _mlForImg.removeLayer(lyrId);
                    if (_mlForImg.getSource(srcId)) _mlForImg.removeSource(srcId);
                    _mlForImg.addSource(srcId, {
                        type: 'image',
                        url: ov.url,
                        coordinates: ov.coordinates
                    });
                    _mlForImg.addLayer({
                        id: lyrId,
                        type: 'raster',
                        source: srcId,
                        paint: {
                            'raster-opacity': (ov.opacity != null ? ov.opacity : 0.85),
                            'raster-fade-duration': 0
                        }
                    });
                } catch (e) {
                    console.warn('[AoTMapLoader] image overlay add failed:', e);
                }
            };
            if (_mlForImg.isStyleLoaded && _mlForImg.isStyleLoaded()) run();
            else _mlForImg.once('load', run);
        };
        const _aotImgRemove = (ov) => {
            if (!_mlForImg || !ov) return;
            try {
                const { srcId, lyrId } = _aotImgIds(ov.id);
                if (_mlForImg.getLayer(lyrId)) _mlForImg.removeLayer(lyrId);
                if (_mlForImg.getSource(srcId)) _mlForImg.removeSource(srcId);
            } catch (e) { /* already gone */ }
        };
        // Live-update helpers for the correction UI (coords drag / opacity slider).
        map._aotImageOverlayAdd = _aotImgAdd;
        map._aotImageOverlayRemove = _aotImgRemove;
        map._aotImageOverlaySetCoords = (id, coordinates) => {
            if (!_mlForImg) return;
            try {
                const { srcId } = _aotImgIds(id);
                const src = _mlForImg.getSource(srcId);
                if (src && src.setCoordinates) src.setCoordinates(coordinates);
            } catch (e) { /* not yet added */ }
        };
        map._aotImageOverlaySetOpacity = (id, opacity) => {
            if (!_mlForImg) return;
            try {
                const { lyrId } = _aotImgIds(id);
                if (_mlForImg.getLayer(lyrId)) {
                    _mlForImg.setPaintProperty(lyrId, 'raster-opacity', opacity);
                }
            } catch (e) { /* not yet added */ }
        };

        map.on('overlayadd', (e) => {
            if (e && e.layer && e.layer._aotImage) _aotImgAdd(e.layer._aotImage);
        });
        map.on('overlayremove', (e) => {
            if (e && e.layer && e.layer._aotImage) _aotImgRemove(e.layer._aotImage);
        });
        // Initial render for image overlays that are visible at load.
        Object.keys(map.aotOverlayMaps).forEach((name) => {
            const lf = map.aotOverlayMaps[name];
            if (lf && lf._aotImage && lf._aotImage.visible) _aotImgAdd(lf._aotImage);
        });


        // Return standard object
        return {
            map: map,
            baseLayers: map.aotBaseMaps,
            overlays: map.aotOverlayMaps,
            activeLayer: activeBaseLayer,
            layerControl: layerControl
        };
    },

    /**
     * Toggles a device ON/OFF via API
     * Supports both Outputs and Functions
     * @param {string} deviceId - Unique ID of device
     * @param {boolean} state - Target state
     * @param {number} channel - Optional channel index
     * @param {string} deviceType - 'output' or 'function'
     */
    toggleDevice: function (deviceId, state, channel = 0, deviceType = 'output') {
        if (channel === 'undefined' || channel === 'null' || !channel) channel = 0;
        
        let baseId = deviceId;
        if (deviceId && deviceId.indexOf('::') !== -1) {
            baseId = deviceId.split('::')[0];
        }

        if (deviceType === 'function') {
            // Function toggle logic (Activate/Deactivate)
            const formData = new FormData();
            formData.append('function_id', baseId);
            if (state) {
                formData.append('function_activate', 'True');
            } else {
                formData.append('function_deactivate', 'True');
            }

            fetch('/function_submit', {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                // console.log(`[AoTMapLoader] Function control success:`, data);
            })
            .catch(err => {
                // console.error(`[AoTMapLoader] Function control error:`, err);
            });
            return;
        }

        // Default Output logic
        const payload = { state: state, channel: channel };
        fetch(`/api/outputs/${baseId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/vnd.aot.v1+json',
                'Accept': 'application/vnd.aot.v1+json'
            },
            body: JSON.stringify(payload)
        })
            .then(res => {
                if (!res.ok) {
                    // If not found in outputs, it might be a function. 
                    // Functional control via routes_function /function_submit might be needed
                    // but that requires a form-encoded payload.
                    // For now, we assume simple output control as requested.
                    // console.warn(`[AoTMapLoader] Control failed for ${deviceId}`, res.status);
                }
                return res.json();
            })
            .then(data => {
                // console.log(`[AoTMapLoader] Control response for ${deviceId}:`, data);
                // Optionally trigger a global refresh or wait for polling
            })
            .catch(err => { /* console.error(`[AoTMapLoader] Control error:`, err); */ });
    },

    /**
     * commandActuator: control a 3-way actuator output (Open/Stop/Close/goto).
     * Maps logical actions to the /api/outputs/<id> POST payload:
     *   - 'open'  -> position: 100
     *   - 'close' -> position: 0
     *   - 'stop'  -> state: false
     *   - 'goto'  -> position: <value 0..100>
     * Also primes _pending_command on the marker (10s local override) so polled
     * server state cannot snap the UI back before the command takes effect.
     *
     * @param {string} deviceId
     * @param {string} action one of 'open' | 'close' | 'stop' | 'goto'
     * @param {number|null} value target position (0-100) when action === 'goto' (otherwise ignored)
     * @param {number|string} channel
     * @param {string} widgetUniqueId widget instance id (used to locate marker for pending guard)
     */
    commandActuator: function (deviceId, action, value, channel = 0, widgetUniqueId = null) {
        if (channel === 'undefined' || channel === 'null' || !channel) channel = 0;

        let baseId = deviceId;
        if (deviceId && deviceId.indexOf('::') !== -1) {
            baseId = deviceId.split('::')[0];
        }

        const payload = { channel: channel };
        let optimisticPos = null;
        if (action === 'open') {
            payload.position = 100;
            optimisticPos = 100;
        } else if (action === 'close') {
            payload.position = 0;
            optimisticPos = 0;
        } else if (action === 'stop') {
            payload.state = false;
        } else if (action === 'goto') {
            const v = parseFloat(value);
            if (isNaN(v)) return;
            payload.position = Math.max(0, Math.min(100, v));
            optimisticPos = payload.position;
        } else {
            return;
        }

        // Global target-value cache — shared with the facility popup slider
        if (optimisticPos !== null) {
            window._aotActuatorTargetPct = window._aotActuatorTargetPct || {};
            window._aotActuatorTargetPct[baseId] = optimisticPos;
        }

        try {
            if (widgetUniqueId && window.AoTMapApp && window.AoTMapApp[widgetUniqueId]) {
                const m = window.AoTMapApp[widgetUniqueId].deviceMarkers[deviceId];
                if (m) {
                    m.options._pending_command = Date.now();
                    if (optimisticPos !== null) {
                        m.options.position_pct = optimisticPos;
                    }
                    if (action === 'stop') {
                        m.options.is_active = false;
                    } else if (optimisticPos !== null) {
                        m.options.is_active = (optimisticPos > 0);
                        m.options.last_status_change = m.options.is_active ? Math.floor(Date.now() / 1000) : null;
                    }
                }
            }
        } catch (e) { /* noop */ }

        fetch(`/api/outputs/${baseId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/vnd.aot.v1+json',
                'Accept': 'application/vnd.aot.v1+json'
            },
            body: JSON.stringify(payload)
        })
            .then(res => res.json())
            .catch(() => {});
    },

    /**
     * Formats duration in seconds to HH:MM:SS
     */
    formatDuration: function (seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        return [h, m, s].map(v => v < 10 ? "0" + v : v).join(":");
    },

    /**
     * Updates duration displays on popups
     * Called by polling logic in widgets
     */
    updateDurations: function (deviceMarkers) {
        if (!window.AoTStopwatchManager) return;
        
        Object.keys(deviceMarkers).forEach(id => {
            const marker = deviceMarkers[id];
            const durEl = document.getElementById(`dur-${id}`);
            if (durEl) {
                const channel = marker.options.channel_id || 0;
                const isActive = !!marker.options.is_active;
                const lastStatusChange = marker.options.last_status_change || null;
                
                // [Runtime Service] Always register to sync state (Active/Idle) with the manager
                window.AoTStopwatchManager.register(id, channel, isActive, lastStatusChange, durEl);
            }
        });
    },

    /**
     * =====================================================
     * VECTOR MAP: Initialize MapLibre GL-based vector map
     * =====================================================
     * Overlays a MapLibre GL vector layer on top of a Leaflet map.
     * Compatible with existing Leaflet layers.
     *
     * @param {L.Map} leafletMap - existing Leaflet map instance
     * @param {Object} options - vector map options
     * @param {string} [options.style] - MapLibre style URL
     * @param {Array} [options.center] - [lng, lat] default center
     * @param {number} [options.zoom] - zoom level
     * @returns {maplibregl.Map|null} MapLibre map instance
     */
    initVectorMap: function(leafletMap, options = {}) {
        
        // Check MapLibre GL
        if (typeof maplibregl === 'undefined') {
            return null;
        }

        // Check the Leaflet-MapLibre-GL plugin
        if (typeof L.MapLibreGL === 'undefined') {
            return null;
        }

        // Create the MapLibre vector map container
        const container = leafletMap.getContainer();
        const rect = container.getBoundingClientRect();
        
        // Create the MapLibre GL map
        const maplibreOptions = {
            container: {
                create: function() {
                    const div = document.createElement('div');
                    div.style.position = 'absolute';
                    div.style.top = '0';
                    div.style.left = '0';
                    div.style.width = '100%';
                    div.style.height = '100%';
                    div.style.zIndex = '1'; // Below the Leaflet tiles
                    div.className = 'maplibre-vector-layer';
                    container.appendChild(div);
                    return div;
                }
            },
            // MapTiler API v2: /maps/ not /styles/
        style: options.style || (options.apiKey 
            ? `https://api.maptiler.com/maps/streets/style.json?key=${options.apiKey}` 
            : 'https://demotiles.maplibre.org/style.json'),
            center: options.center || [126.978, 37.5665],
            zoom: options.zoom || 12,
            attributionControl: false,
            interactive: false // Prevent interference with Leaflet events
        };
        
        let maplibreMap = null;
        
        try {
            // Create the MapLibre map (temporary container)
            const tempContainer = document.createElement('div');
            tempContainer.style.position = 'absolute';
            tempContainer.style.top = '0';
            tempContainer.style.left = '0';
            tempContainer.style.width = '100%';
            tempContainer.style.height = '100%';
            tempContainer.style.zIndex = '1';
            tempContainer.className = 'maplibre-vector-layer';
            container.appendChild(tempContainer);
            
            maplibreMap = new maplibregl.Map({
                container: tempContainer,
                style: maplibreOptions.style,
                center: maplibreOptions.center,
                zoom: maplibreOptions.zoom,
                attributionControl: false,
                interactive: false
            });
            
            // Sync the MapLibre map size to Leaflet
            maplibreMap.on('load', function() {
                // Sync Leaflet and MapLibre coordinates
                const syncMap = function() {
                    const center = leafletMap.getCenter();
                    const zoom = leafletMap.getZoom();
                    maplibreMap.jumpTo({
                        center: [center.lng, center.lat],
                        zoom: zoom,
                        bearing: leafletMap.getBearing(),
                        pitch: leafletMap.getPitch()
                    });
                };
                
                // Sync on Leaflet events
                leafletMap.on('move', syncMap);
                leafletMap.on('zoom', syncMap);
                leafletMap.on('resize', syncMap);

                // Initial sync
                syncMap();
                
            });
            
            // Initialize VectorLayerManager (create + bind in one step)
            if (window.AoTVectorLayerManager && window.AoTVectorLayerManager.bind) {
                const vlm = window.AoTVectorLayerManager.bind(maplibreMap);
            }
            
            // Initialize RasterBridge
            if (window.AoTRasterBridge) {
                window.AoTRasterBridge.create(maplibreMap);
            }
            
            // Store maplibreMap on the Leaflet map
            leafletMap.maplibreMap = maplibreMap;
            
            return maplibreMap;
            
        } catch (error) {
            return null;
        }
    },
    
    /**
     * =====================================================
     * VECTOR SOURCE: Add a vector source
     * =====================================================
     * Adds a vector tile source to the MapLibre map.
     *
     * @param {string} sourceId - source ID
     * @param {Object} options - source options
     * @param {string[]} options.tiles - array of vector tile URLs
     * @param {string} [options.type='vector'] - source type
     * @param {number} [options.minzoom=0] - minimum zoom
     * @param {number} [options.maxzoom=14] - maximum zoom
     * @returns {boolean} whether it succeeded
     */
    addVectorSource: function(sourceId, options) {
        if (window.AoTVectorLayerManager) {
            return window.AoTVectorLayerManager.addVectorSource(sourceId, options);
        }
        return false;
    },
    
    /**
     * =====================================================
     * VECTOR LAYER: Add a vector layer
     * =====================================================
     * Adds a vector layer to the MapLibre map.
     *
     * @param {string} layerId - layer ID
     * @param {string} sourceId - source ID
     * @param {Object} style - layer style
     * @returns {boolean} whether it succeeded
     */
    addVectorLayer: function(layerId, sourceId, style) {
        if (window.AoTVectorLayerManager) {
            return window.AoTVectorLayerManager.addStyledLayer(layerId, sourceId, style);
        }
        return false;
    }
};

/**
 * =====================================================
 * GIS INPUT PREVIEW: Settings preview
 * =====================================================
 * Provides a layer preview on the GIS Input settings page.
 * Defined as an object/function so AoTGeoInputPreview.load(uniqueId) can be called.
 */
var AoTGeoInputPreview = function() {
    return true;
};

/**
 * Validation and preview when GIS Input settings change
 * @param {string} uniqueId - input unique ID
 */
AoTGeoInputPreview.load = function(uniqueId) {
    
    // Find the matching input item in the gridstack container
    var inputContainer = document.getElementById('gridstack_input_' + uniqueId);
    if (!inputContainer) {
        return false;
    }
    
    // Determine the input type (from the data-input-type attribute or input_name)
    var inputType = inputContainer.getAttribute('data-input-type') || '';
    var inputName = inputContainer.getAttribute('data-input-name') || '';
    
    
    // For MapTiler Vector, check the API Key
    if (inputName === 'MapTiler Vector' || inputName.toLowerCase().includes('maptiler')) {
        var apiKeyInput = inputContainer.querySelector('[name*="api_key"], [name*="apikey"], [name*="apiKey"]');
        if (apiKeyInput && !apiKeyInput.value.trim()) {
            // Continue saving even if the API Key is empty (the save button is handled separately)
        }
    }
    
    // For RainViewer, check the API status
    if (inputName === 'RainViewer Radar' || inputName.toLowerCase().includes('rainviewer')) {
    }
    
    return true;
};

}
