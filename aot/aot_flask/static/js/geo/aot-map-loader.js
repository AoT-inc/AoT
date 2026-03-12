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
            console.log("[AoT] Emergency Master Shield Activated");
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

        // 2. Create Map
        const map = L.map(containerId, mapOptions);

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
        } else {
            // Fallback if Utils not loaded
            L.control.attribution({ prefix: false, position: 'bottomleft' }).addTo(map);
        }

        // 3. Add Layers (Base Maps & Overlays)
        // Allow override from customOptions (e.g. for Preview Map to be clean)
        let layers = (config.layers || []);
        if (customOptions.layers !== undefined) {
            const selection = Array.isArray(customOptions.layers) ? customOptions.layers : [customOptions.layers];
            // [Fix] Handle selection of strings (names/ids) from Widget Persistence
            if (selection.length > 0 && typeof selection[0] === 'string') {
                layers = layers.map(l => {
                    const isSelected = selection.includes(l.name) || selection.includes(l.id) || selection.includes(l.base_id);
                    return { ...l, visible: isSelected };
                });
            } else {
                // Already a list of objects
                layers = selection;
            }
        }
        
        const baseMaps = {};
        const overlayMaps = {};
        let activeBaseLayer = null;

        // Helper to get or create Layer Control
        let layerControl = null;
        const ensureLayerControl = () => {
            if (!layerControl) {
                // Create if not exists (showing whatever base/overlays we have so far)
                if (Object.keys(baseMaps).length > 0 || Object.keys(overlayMaps).length > 0) {
                    layerControl = L.control.layers(baseMaps, overlayMaps).addTo(map);
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

            // [Fix] RainViewer Global Support
            if (finalUrl && finalUrl.includes('{ts}')) {
                // We need to fetch timestamp. Since initMap is sync, we fire async fetch.
                // Layer will appear later.
                // [Fix] Use Backend Proxy to avoid CORS/Network Block on Client
                fetch('/api/geo/proxy/rainviewer/meta')
                    .then(r => r.json())
                    .then(data => {
                        if (data.radar && data.radar.past && data.radar.past.length > 0) {
                            const lastTs = data.radar.past[data.radar.past.length - 1].time;
                            const realUrl = finalUrl.replace('{ts}', lastTs);

                            let rvLayer = null;
                            if (l.type === 'xyz') rvLayer = L.tileLayer(realUrl, finalOpts);
                            else if (l.type === 'wms') rvLayer = L.tileLayer.wms(realUrl, finalOpts);

                            if (rvLayer) {
                                // [Fix] Attach Metadata for Persistence & Legend
                                rvLayer.aot_id = l.id;
                                rvLayer.aot_base_id = l.base_id || l.id;
                                if (l.legend) {
                                    rvLayer.aot_legend = l.legend;
                                }

                                // [Fix] Update overlayMaps reference so Widget can track it
                                overlayMaps[l.name] = rvLayer;

                                // Add to map if active
                                // [Fix] Respect explicit 'visible' property from backend (User Preference)
                                let shouldAdd = false;
                                if (l.visible !== undefined && l.visible !== null) {
                                    shouldAdd = (l.visible === true || l.visible === 'true');
                                } else {
                                    shouldAdd = (l.is_active || l.is_default);
                                }

                                if (shouldAdd) {
                                    rvLayer.addTo(map);
                                }

                                // [Fix] Add to Layer Control dynamically
                                const ctl = ensureLayerControl();
                                if (ctl) {
                                    ctl.addOverlay(rvLayer, l.name);
                                } else {
                                    // If ensureLayerControl failed (empty maps initially), we create it now
                                    layerControl = L.control.layers(baseMaps, overlayMaps).addTo(map);
                                }
                                
                                // FORCE UPDATE LEGEND (Since overlayadd might have fired before legend data was ready if sync issues occurred, generally fine, but safe to call)
                                if (shouldAdd && typeof updateLegendAndSyncPanel === 'function') {
                                    updateLegendAndSyncPanel();
                                }
                            }
                        }
                    }).catch(e => { /* console.warn("RainViewer Global Load Failed", e); */ });
                return; // Skip sync creation
            }

            // [Fix] Skip invalid URLs with unreplaced placeholders to prevent crash
            if (finalUrl && finalUrl.match(/\{(x|y|z|s|r|q)\}/) === null && finalUrl.match(/\{([a-zA-Z0-9_]+)\}/)) {
                // URL has placeholders OTHER than x,y,z,s,r (e.g. {key}, {style} missing)
                // console.warn("[AoTMapLoader] Skipping layer with unreplaced placeholders:", l.name, finalUrl);
                return;
            }

            if (l.type === 'xyz' && finalUrl) {
                // [New] Check for QuadKey placeholder
                if (finalUrl.indexOf('{q}') !== -1) {
                    layerFunc = L.tileLayer.quadKey(finalUrl, finalOpts);
                } else {
                    layerFunc = L.tileLayer(finalUrl, finalOpts);
                }
            } else if (l.type === 'wms' && finalUrl) {
                layerFunc = L.tileLayer.wms(finalUrl, finalOpts);
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
                    console.warn("[AoTMapLoader] GeoJSON Render Error:", e);
                }
            }

            if (layerFunc) {
                // Attach Metadata for Persistence Tracking
                layerFunc.aot_id = l.id; // Unique GeoLayer ID (Exploded if applicable)
                layerFunc.aot_base_id = l.base_id || l.id; // [Fix] Track DB ID

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
                    baseMaps[l.name] = layerFunc;

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
                    overlayMaps[l.name] = layerFunc;
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
            baseMaps['OpenStreetMap'] = osm;
        }

        // 4. Add Layer Control
        // [UX] Always add if we have at least one layer (even if just Fallback OSM).
        // This ensures the "Layer Manager" icon appears, confirming it's working.
        if (Object.keys(baseMaps).length > 0 || Object.keys(overlayMaps).length > 0) {
            layerControl = L.control.layers(baseMaps, overlayMaps).addTo(map);
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
                        url = customUrl.replace('{lat}', center.lat)
                            .replace('{lon}', center.lng)
                            .replace('{lng}', center.lng)
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
                            console.warn('Legend Fetch Error:', url, err); 
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

        map.on('overlayadd', updateLegendAndSyncPanel);
        map.on('overlayremove', updateLegendAndSyncPanel);
        map.on('layerremove', updateLegendAndSyncPanel);
        
        // Also initial update
        setTimeout(updateLegendAndSyncPanel, 300);


        // Return standard object
        return {
            map: map,
            baseLayers: baseMaps,
            overlays: overlayMaps,
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
                
                // [Runtime Service] 항상 등록하여 상태(Active/Idle)를 매니저에 동기화
                window.AoTStopwatchManager.register(id, channel, isActive, lastStatusChange, durEl);
            }
        });
    }
};

}
