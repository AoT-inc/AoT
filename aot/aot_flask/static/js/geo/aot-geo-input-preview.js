/**
 * AoT Geo Input Preview Module
 * Handles loading of preview maps in the Geo Input Modal.
 */

const AoTGeoInputPreview = {
    // State
    previewMaps: {},
    previewLayers: {},

    /**
     * initialize global event listeners
     */
    init: function () {
        // Global Delegation: Check for Modal Show
        // Since modals are dynamically ID'd, we don't know them in advance.
        // We can listen to document 'shown.bs.modal' but we need to know if it's OUR modal.
        // The modals have id "modal_config_{uuid}"

        // Wait for DOM
        document.addEventListener('DOMContentLoaded', () => {
            // JQuery Bootstrap Event
            $(document).on('shown.bs.modal', '.modal', function (e) {
                const id = e.target.id;
                if (id && id.startsWith('modal_config_')) {
                    const uuid = id.replace('modal_config_', '');
                    // [Debug] Log Modal Open Request
                    const form = $('#form_config_' + uuid);
                    const nameVal = form.find('input[name="name"]').val();
                    // console.log("[Debug] Modal Opened. Name Input Value:", nameVal);
                    AoTGeoInputPreview.load(uuid);
                }
            });
        });

        // Expose to window for inline onlick calls if any (e.g. Refresh Button)
        window.loadPreview = this.load.bind(this);
    },

    /**
     * Load Preview Map for a given Input UUID
     * @param {string} uuid
     */
    load: function (uuid) {
        const containerId = 'preview_map_' + uuid;
        const container = document.getElementById(containerId);

        if (!container) return;

        const urlTemplate = container.getAttribute('data-url-template');

        // [RainViewer] Pre-fetch latest radar timestamp ({ts} placeholder).
        // Reference: https://www.rainviewer.com/api/weather-maps-api.html
        // - meta.radar.past[] / nowcast[] each have { time:int, path:"/v2/radar/<id>" }
        // - URL template here uses just "<id>" segment, so we extract the trailing path.
        // - Public API is CORS-enabled; backend proxy is used only as fallback.
        if (urlTemplate && /rainviewer\.com/i.test(urlTemplate) && /\{ts\}/i.test(urlTemplate)
            && !this._rainviewerTs && !this._rainviewerTsFetching) {
            this._rainviewerTsFetching = true;
            const _extractTs = (meta) => {
                if (!meta || !meta.radar) return null;
                const past = meta.radar.past || [];
                const nowcast = meta.radar.nowcast || [];
                const last = past.length ? past[past.length - 1] : (nowcast.length ? nowcast[0] : null);
                if (!last) return null;
                if (last.path) {
                    // path is "/v2/radar/<id>" — keep only the last segment for our template.
                    const parts = String(last.path).split('/').filter(Boolean);
                    return parts.length ? parts[parts.length - 1] : null;
                }
                if (last.time) return String(last.time);
                return null;
            };
            const _tryUrl = (url) => fetch(url, { credentials: 'omit' })
                .then(r => r.ok ? r.json() : null)
                .catch(() => null);
            // Direct first; fall back to backend proxy if blocked or upstream down.
            _tryUrl('https://api.rainviewer.com/public/weather-maps.json')
                .then(meta => meta || _tryUrl('/api/geo/proxy/rainviewer/meta'))
                .then(meta => {
                    const ts = _extractTs(meta);
                    if (ts) this._rainviewerTs = ts;
                })
                .then(() => {
                    this._rainviewerTsFetching = false;
                    if (this._rainviewerTs) {
                        this.load(uuid);
                    } else {
                        console.warn('[AoTGeoInputPreview] RainViewer timestamp unavailable; preview suppressed.');
                    }
                });
            return; // Defer until timestamp is resolved.
        }

        const layerType = container.getAttribute('data-layer-type') || 'xyz';
        const layerRole = container.getAttribute('data-layer-role') || 'base'; // New Attribute
        const defaultOptionsRaw = container.getAttribute('data-leaflet-options');
        const keyField = container.getAttribute('data-key-field');
        const legendRaw = container.getAttribute('data-legend');

        let defaultOptions = {};
        let legendData = null;
        try {
            if (defaultOptionsRaw && defaultOptionsRaw !== 'None') {
                defaultOptions = JSON.parse(defaultOptionsRaw);
            }
        } catch (e) {
            // console.error("Bad JSON options", e);
        }

        try {
            if (legendRaw && legendRaw !== 'None' && legendRaw !== 'null') {
                legendData = JSON.parse(legendRaw);
                // console.log("[AoTGeoInputPreview] Parsed Legend Data:", legendData);
            }
        } catch (e) {
            // console.warn("Bad JSON legend", e);
        }

        const form = $('#form_config_' + uuid);
        let savedOptions = {};
        try {
            const savedRaw = form.attr('data-saved-options');
            if (savedRaw && savedRaw !== 'None' && savedRaw !== 'null') {
                savedOptions = JSON.parse(savedRaw);
            }
        } catch (e) {
            // console.warn("Saved opts parse fail or empty");
        }

        const globalOptions = {};

        // 1. Gather Global Options (Non-channel)
        // Bool toggles (.btn-toggle-input) are scalar '1'/'0' so URL placeholders like
        // {smoothing} resolve to the numeric form RainViewer/etc. expect. Multi-value
        // checkboxes without that class still accumulate as arrays for backwards-compat.
        form.find('.gis-custom-option').not('[data-is-channel="true"]').each(function () {
            const name = $(this).attr('name');
            if (!name) return;
            const $this = $(this);
            if ($this.attr('type') === 'checkbox') {
                if ($this.hasClass('btn-toggle-input')) {
                    globalOptions[name] = $this.is(':checked') ? '1' : '0';
                } else if ($this.is(':checked')) {
                    if (!globalOptions[name]) globalOptions[name] = [];
                    globalOptions[name].push($this.val());
                }
            } else {
                globalOptions[name] = $this.val();
            }
        });

        // 2. Initialize Map
        if (!this.previewMaps[uuid]) {
            try {
                const config = window.AOT_GEO_CONFIG || {};
                const camMaxZoom = parseInt(config.max_zoom, 10) || 25;

                // Per-input default center/zoom overrides global AOT_GEO_CONFIG
                // (e.g. GSI Japan maps use Tokyo instead of the Seoul default)
                let initCenter = [parseFloat(config.default_lng) || 126.9780, parseFloat(config.default_lat) || 37.5665];
                let initZoom = parseFloat(config.zoom) || 6;
                const rawCenter = container.getAttribute('data-default-center');
                const rawZoom = container.getAttribute('data-default-zoom');
                if (rawCenter) {
                    try {
                        const parsed = JSON.parse(rawCenter);
                        if (Array.isArray(parsed) && parsed.length === 2) initCenter = parsed;
                    } catch (_) {}
                }
                if (rawZoom) {
                    const z = parseFloat(rawZoom);
                    if (!isNaN(z)) initZoom = z;
                }

                const previewMap = new maplibregl.Map({
                    container: containerId,
                    style: { version: 8, sources: {}, layers: [] },
                    center: initCenter,
                    zoom: initZoom,
                    minZoom: 0,
                    maxZoom: camMaxZoom,
                    transformRequest: function(url, resourceType) {
                        // Domains that require server-side proxying due to CORS / Referer restrictions.
                        const PROXY_DOMAINS = [
                            'gibs.earthdata.nasa.gov',
                            'map.pstatic.net',   // Naver — blocks cross-origin + checks Referer
                            'daumcdn.net',        // Kakao — CORS restricted
                        ];
                        if (PROXY_DOMAINS.some(d => url.includes(d))) {
                            return { url: '/api/geo/tile_proxy?url=' + encodeURIComponent(url) };
                        }
                        // Upgrade remaining HTTP tile requests to HTTPS (Mixed Content guard).
                        if (url.startsWith('http://') && window.location.protocol === 'https:') {
                            return { url: 'https://' + url.slice(7) };
                        }
                        return { url: url };
                    }
                });
                this.previewMaps[uuid] = previewMap;
            } catch (e) {
                return;
            }
        }

        const map = this.previewMaps[uuid];
        
        // [Fix] Resize map for Modal Rendering
        setTimeout(() => {
            map.resize();
        }, 200);

        // 3. Clear Previous Layers & Control
        // Remove DOM-based Layer Control if exists
        if (this.previewLayerControl && this.previewLayerControl[uuid]) {
            try {
                const dom = this.previewLayerControl[uuid]._dom;
                if (dom && dom.parentNode) dom.parentNode.removeChild(dom);
            } catch (e) { /* silent */ }
            delete this.previewLayerControl[uuid];
        }

        if (this.previewLayers[uuid] && Array.isArray(this.previewLayers[uuid])) {
            this.previewLayers[uuid].forEach(layer => {
                try { if (layer && typeof layer.remove === 'function') layer.remove(); } catch (e) { }
            });
        }
        this.previewLayers[uuid] = [];

        // 4. Identify Checked Channels
        const checkedChannels = form.find('input.gis-custom-option:checked').filter(function () {
            return $(this).attr('data-is-channel') === 'true';
        });

        // [Fallthrough] If no channels checked, stop here
        if (checkedChannels.length === 0 && form.find('input[data-is-channel="true"]').length > 0) {
            // console.log("[AoTGeoInputPreview] No channels selected. Map cleared.");
            return;
        }

        // 5. Render Layers
        const renderQueue = [];

        if (checkedChannels.length > 0) {
            checkedChannels.each(function () {
                const chInput = $(this);
                // Extract Name for Layer Control - Updated to support .row structure
                let chName = chInput.closest('.aot-modal-container, .row').find('input[name^="channel_name_"]').val();
                if (!chName) chName = chInput.val(); // Fallback to Channel ID (e.g. C01)
                if (!chName) chName = 'Layer';

                renderQueue.push({
                    name: chName,
                    chInput: chInput,
                    options: Object.assign({}, globalOptions)
                });
            });
        } else {
            // Single Mode
            renderQueue.push({
                name: 'Preview',
                chInput: null,
                options: globalOptions
            });
        }

        // Prepare Control Objects
        const baseMaps = {};
        const overlayMaps = {};
        let activeBaseLayer = null;

        // Listeners for Persistence
        const updateVisibility = (layer, visible) => {
            let inputName = null;
            if (layer.aot_channel_id) {
                inputName = 'channel_visible_' + layer.aot_channel_id;
            } else if (layer.aot_layer_key) {
                // Single Layer Key
                inputName = layer.aot_layer_key;
            }

            if (inputName) {
                let hiddenInput = form.find('input[name="' + inputName + '"]');
                if (hiddenInput.length === 0) {
                    hiddenInput = $('<input>').attr({
                        type: 'hidden',
                        name: inputName,
                        class: 'gis-custom-option' // [Fix] Include in globalOptions gathering
                    }).appendTo(form);
                }
                hiddenInput.val(visible ? 'true' : 'false');
            }
        };

        // [MapLibre] Leaflet's 'overlayadd' / 'overlayremove' / 'baselayerchange'
        // events don't exist on maplibregl.Map — visibility persistence is driven
        // directly from the layer-control toggles below.

        // [Fix] Reinforce Attribution Early
        if (window.AoTMapUtils && window.AoTMapUtils.addCopyrightControl) {
            window.AoTMapUtils.addCopyrightControl(map);
        }

        // [Overlay Mode] When this preview is for an overlay-role layer, render an
        // OSM raster baseline below all overlays so users see geographic context.
        const _OSM_BASE_ID = 'aot-preview-osm-base';
        const _ensureOsmBase = () => {
            const add = () => {
                if (!map.getSource(_OSM_BASE_ID)) {
                    map.addSource(_OSM_BASE_ID, {
                        type: 'raster',
                        tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
                                'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
                                'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png'],
                        tileSize: 256,
                        attribution: '© OpenStreetMap',
                        maxzoom: 19
                    });
                }
                if (!map.getLayer(_OSM_BASE_ID)) {
                    map.addLayer({ id: _OSM_BASE_ID, type: 'raster', source: _OSM_BASE_ID });
                }
            };
            if (map.isStyleLoaded()) add(); else map.once('load', add);
        };
        if (layerRole === 'overlay') _ensureOsmBase();

        renderQueue.forEach((item, index) => {
            let finalUrl = urlTemplate;
            const itemOptions = item.options;

            // Resolve placeholders from Channel Data
            if (item.chInput) {
                const attributes = item.chInput[0].attributes;
                for (let i = 0; i < attributes.length; i++) {
                    const attr = attributes[i];
                    if (attr.name.startsWith('data-replace-')) {
                        const key = attr.name.replace('data-replace-', '');
                        let val = attr.value;
                        // Channel's url_template overrides the container's default_url directly
                        if (key === 'url_template' && /^https?:\/\//i.test(val)) {
                            finalUrl = val;
                        } else {
                            finalUrl = finalUrl.replace(new RegExp('\\{' + key + '\\}', 'gi'), val);
                        }
                        itemOptions[key] = val;
                    }
                }
            }
            
            // [Fallback] Manually check for 'layer' replacement if not found
            if (finalUrl.match(/\{layer\}/i) && !itemOptions.layer) {
                // Try to find layer name from channel info if not in attributes
                 // We can't access ch_info here easily in JS unless passed.
                 // But wait, if ch_info has 'layer', it SHOULD be in data-replace-layer.
                 
                 // DEBUG: Maybe attr name is case sensitive? 'data-replace-LAYER'?
                 // HTML attributes are lowercased by browser.
                 // So data-replace-LAYER -> data-replace-layer.
                 // key becomes 'layer'.
                 // RegExp is now 'gi', so it should match {LAYER}.
                 
                 // If failure persists, it means `data-replace-layer` is NOT in HTML attribute list.
            }
            
             // [Fix] Handle Numeric and normal placeholders
             
             // [Common] Relative Date Calculation
             // Supports keywords: today, 1_day_ago, 2_days_ago, 7_days_ago
             if (itemOptions.date_mode) {
                 const mode = itemOptions.date_mode;
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
                 } else if (mode === 'custom' && itemOptions.target_date) {
                     dateStr = itemOptions.target_date;
                 }

                 if (dateStr !== 'default') {
                     itemOptions.time = dateStr;
                 }
             }

            // [Fix] Handle Case-Insensitive HTML Attributes & numeric parsing
            // Map lowercase keys back to Leaflet CamelCase
            const keyMap = {
                'maxnativezoom': 'maxNativeZoom',
                'minzoom': 'minZoom',
                'maxzoom': 'maxZoom',
                'tilematrixset': 'tileMatrixSet'
            };

            // Normalize Keys and Types in itemOptions
            Object.keys(itemOptions).forEach(k => {
                const mk = keyMap[k];
                if (mk) {
                     itemOptions[mk] = Number(itemOptions[k]) || itemOptions[k];
                }
                if (k === 'maxnativezoom' || k === 'minzoom' || k === 'maxzoom') {
                    itemOptions[keyMap[k]] = Number(itemOptions[k]);
                }
            });

            // [Fix] Map Common Aliases for URL Placeholders
            if (itemOptions.tileMatrixSet && !itemOptions.ts) itemOptions.ts = itemOptions.tileMatrixSet;
            if (itemOptions.ts && !itemOptions.tileMatrixSet) itemOptions.tileMatrixSet = itemOptions.ts;
            
            // [{ts} Disambiguation]
            // {ts} is overloaded across providers:
            //   - WMTS/VWorld → tileMatrixSet name (default GoogleMapsCompatible)
            //   - RainViewer  → latest radar timestamp from weather-maps.json
            // Detect by URL host; pre-fetched timestamps live on globalOptions.ts.
            if (finalUrl.match(/\{ts\}/i) && !itemOptions.ts) {
                if (/rainviewer\.com/i.test(finalUrl)) {
                    const rvTs = this._rainviewerTs || null;
                    if (rvTs) {
                        itemOptions.ts = rvTs;
                        finalUrl = finalUrl.replace(/\{ts\}/gi, rvTs);
                    }
                    // If no timestamp yet, leave placeholder; the async prefetch below
                    // will trigger another load() once it resolves.
                } else {
                    itemOptions.ts = 'GoogleMapsCompatible';
                    finalUrl = finalUrl.replace(/\{ts\}/gi, 'GoogleMapsCompatible');
                }
            }

            // [Fix] Default fallback for {tilematrixset}
            if (finalUrl.match(/\{tilematrixset\}/i) && !itemOptions.tileMatrixSet) {
                 itemOptions.tileMatrixSet = 'GoogleMapsCompatible';
                 finalUrl = finalUrl.replace(/\{tilematrixset\}/gi, 'GoogleMapsCompatible');
            }

            // [Fix] Default fallback for {ext} (defaults to png)
            if (finalUrl.match(/\{ext\}/i) && !itemOptions.ext) {
                 itemOptions.ext = 'png';
                 finalUrl = finalUrl.replace(/\{ext\}/gi, 'png');
            }
            
            // [Fix] Default fallback for {style} (defaults to default)
            if (finalUrl.match(/\{style\}/i) && !itemOptions.style) {
                 itemOptions.style = 'default';
                 finalUrl = finalUrl.replace(/\{style\}/gi, 'default');
            }

            if (itemOptions.name && !itemOptions.layer) itemOptions.layer = itemOptions.name; // Fallback for {layer}

            // [Digital Zoom] Mirrors GeoSetting.digital_zoom + max_zoom from AOT_GEO_CONFIG.
            // When digital_zoom is on, the camera is allowed to zoom past the source's
            // native maxzoom (MapLibre overzooms tiles automatically). When off, the
            // display ceiling is clamped to the source's maxNativeZoom.
            if (itemOptions.maxNativeZoom) {
                const cfg = window.AOT_GEO_CONFIG || {};
                const mapMaxZoom = parseInt(cfg.max_zoom, 10) || 25;
                const digitalZoomOn = (cfg.digital_zoom !== false); // default true
                const targetCap = digitalZoomOn ? mapMaxZoom : parseInt(itemOptions.maxNativeZoom, 10);
                if (!itemOptions.maxZoom || itemOptions.maxZoom <= itemOptions.maxNativeZoom) {
                    itemOptions.maxZoom = targetCap;
                }
            }
            
            // Resolve remaining regular placeholders
            for (const [key, val] of Object.entries(itemOptions)) {
                finalUrl = finalUrl.replace(new RegExp('\{' + key + '\}', 'gi'), val);
            }

            // Global Key injection
            if (keyField && window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.keys) {
                const globalKey = window.AOT_GEO_CONFIG.keys[keyField];
                if (globalKey) {
                    finalUrl = finalUrl.replace(/\{(api_key|key|accessToken)\}/gi, globalKey);
                    itemOptions['accessToken'] = globalKey;
                    itemOptions['key'] = globalKey;
                    itemOptions['apikey'] = globalKey;
                }
            }
            
            // [Fix] V-World Satellite Extension Logic (Client-Side HTTPS)
            // Satellite tiles are JPEG, but default template is PNG.
            // We use the direct HTTPS endpoint now (no proxy), so just fix the extension.
            if (finalUrl.indexOf('vworld.kr') !== -1) {
                if (itemOptions.layer === 'Satellite' || (item.name && item.name.indexOf('Satellite') !== -1)) {
                    // Replace .png with .jpeg
                    finalUrl = finalUrl.replace('.png', '.jpeg');
                    // Ensure we use the 1.0.0 WMTS endpoint just in case (usually template handles it)
                }
            }

            // [Fix] Handle {time} placeholder if missing (e.g. NASA GIBS)
            if (finalUrl.indexOf('{time}') !== -1 && (!itemOptions.time || itemOptions.time === '')) {
                // NASA GIBS supports 'default' to get latest
                itemOptions.time = 'default';
                finalUrl = finalUrl.split('{time}').join('default');
                // console.log("[AoTGeoInputPreview] Auto-filled time=default for:", item.name);
            }

            // [Per-Channel Type Override] Some providers (e.g. VWorld) mix WMTS + WMS
            // channels in a single input. The input-level data-layer-type is the default,
            // but a channel can declare data-replace-type="wms" to override it.
            // Similarly, data-replace-url overrides the base URL for that channel.
            let effectiveType = layerType;
            let effectiveUrl = finalUrl;
            if (itemOptions.type && itemOptions.type !== layerType) {
                effectiveType = itemOptions.type;
                // If channel also provides a custom base URL, use it.
                if (itemOptions.url) {
                    effectiveUrl = itemOptions.url;
                    // Re-apply option substitutions on the new base URL.
                    for (const [k, v] of Object.entries(itemOptions)) {
                        if (typeof v === 'string' || typeof v === 'number') {
                            effectiveUrl = effectiveUrl.replace(new RegExp('\\{' + k + '\\}', 'gi'), String(v));
                        }
                    }
                    // Also inject API key if keyField present.
                    if (keyField && window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.keys) {
                        const gk = window.AOT_GEO_CONFIG.keys[keyField];
                        if (gk) effectiveUrl = effectiveUrl.replace(/\{(api_key|key|accessToken)\}/gi, gk);
                    }
                }
            }

            // [WMS Handling] Mirrors geo/design: proxy for CORS + OSM base for overlay context.
            // WMS channels (e.g. VWorld overlays) cannot be fetched directly from browser
            // due to CORS; route through backend proxy which reconstructs the GetMap request.
            // Also add an OSM raster base so overlays have geographic context behind them —
            // the container data-layer-role is 'base' for VWorld so _ensureOsmBase() is not
            // called at load time; we call it here per-channel when the effective type is WMS.
            if (effectiveType === 'wms') {
                if (/^https?:\/\//i.test(effectiveUrl)) {
                    const channelId = item.chInput ? item.chInput.val() : null;
                    const proxyUuid = channelId ? uuid + '_' + channelId : uuid;
                    effectiveUrl = '/api/geo/proxy/wms/' + encodeURIComponent(proxyUuid);
                }
                _ensureOsmBase();
            }

            const layer = this._createLayer(uuid, map, effectiveType, effectiveUrl, defaultOptions, itemOptions);

            if (layer) {
                this.previewLayers[uuid].push(layer);

                // Attach Channel ID for tracking (Unified for Base/Overlay)
                if (item.chInput) {
                    layer.aot_channel_id = item.chInput.val();
                } else {
                    // Single Layer Mode
                    layer.aot_layer_key = 'layer_visible';
                }

                // [New] Attach Legend Data (Inherited from Container)
                if (legendData) {
                    layer.aot_legend = legendData;
                }

                // Add to Maps for Control
                if (layerRole === 'base') {
                    baseMaps[item.name] = layer;

                    // Check Saved Visibility
                    let isExplicit = false;
                    const chId = layer.aot_channel_id;
                    const layerKey = layer.aot_layer_key;

                    let key = null;
                    if (chId) key = 'channel_visible_' + chId;
                    else if (layerKey) key = layerKey;

                    if (key) {
                        let savedVal = globalOptions[key];
                        if (savedVal === undefined) savedVal = savedOptions[key];
 
                        // console.log(`[Debug] Checking Base Visibility. Link: ${key}, Saved: ${savedVal}, ChId: ${chId}`);
 
                        if (savedVal === 'true' || savedVal === true) {
                            isExplicit = true;
                        }
                    }

                    if (isExplicit) {
                        if (activeBaseLayer) map.removeLayer(activeBaseLayer);
                        layer.addTo(map);
                    } else if (!activeBaseLayer && index === renderQueue.length - 1) {
                        // Fallback: If no explicit base layer found up to end, add the last one?
                        // Actually, we process sequentially. We don't know if future one is valid.
                        // But standard fallback is usually First or Last.
                        // Code logic: Add last one if nothing active.
                        layer.addTo(map);
                        activeBaseLayer = layer;
                    }
                } else {
                    // Overlay
                    overlayMaps[item.name] = layer;

                    // Check Saved Visibility
                    // Default to FALSE (Unchecked on load)
                    let shouldBeVisible = false;
                    const chId = layer.aot_channel_id;
                    const layerKey = layer.aot_layer_key;

                    let key = null;
                    if (chId) key = 'channel_visible_' + chId;
                    else if (layerKey) key = layerKey;

                    if (key) {
                        // Check globalOptions (live inputs) OR savedOptions (db)
                        // Priority: Live Input (if exists) -> Saved Option -> Default

                        let savedVal = globalOptions[key];
                        if (savedVal === undefined) savedVal = savedOptions[key];

                        // If savedVal exists, respect it. 'true' means visible.
                        if (savedVal === 'true' || savedVal === true) shouldBeVisible = true;
                        // If undefined/empty/false, remains false.

                        // Ensure hidden input exists for next save with current state
                        const inputName = key;
                        if (form.find('input[name="' + inputName + '"]').length === 0) {
                            $('<input>').attr({
                                type: 'hidden',
                                name: inputName,
                                class: 'gis-custom-option', // [Fix] Include in globalOptions
                                value: shouldBeVisible ? 'true' : 'false'
                            }).appendTo(form);
                        }
                    }

                    if (shouldBeVisible) {
                        layer.addTo(map);
                    }
                }
            }
        });

        // [Layer Control] Build a floating channel selector — base radio + overlay
        // checkboxes — and persist toggles via updateVisibility.
        this._renderLayerControl(uuid, map, baseMaps, overlayMaps, activeBaseLayer, layerRole, updateVisibility);

    },

    /**
     * Render Layer Control button + panel (replaces Leaflet L.control.layers).
     * @private
     */
    _renderLayerControl: function (uuid, map, baseMaps, overlayMaps, activeBaseLayer, layerRole, updateVisibility) {
        if (!this.previewLayerControl) this.previewLayerControl = {};

        const containerId = 'preview_map_' + uuid;
        const mapContainer = document.getElementById(containerId);
        if (!mapContainer) return;

        // Remove any prior control DOM
        if (this.previewLayerControl[uuid] && this.previewLayerControl[uuid]._dom) {
            try { this.previewLayerControl[uuid]._dom.remove(); } catch (e) { /* silent */ }
        }

        const baseEntries = Object.keys(baseMaps);
        const overlayEntries = Object.keys(overlayMaps);
        if (baseEntries.length === 0 && overlayEntries.length === 0) return;

        // Wrapper button + panel, positioned inside the map container (top-right).
        const wrap = document.createElement('div');
        wrap.className = 'aot-preview-layer-control';
        wrap.style.cssText = 'position:absolute;top:10px;right:10px;z-index:5;font-size:13px;';

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'aot-preview-layer-control-btn';
        btn.title = 'Layers';
        btn.style.cssText = 'width:34px;height:34px;border-radius:6px;border:1px solid #ccc;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,0.15);cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;';
        btn.innerHTML = '<i class="fas fa-layer-group" style="color:#444;"></i>';

        const panel = document.createElement('div');
        panel.className = 'aot-preview-layer-control-panel';
        panel.style.cssText = 'display:none;margin-top:6px;background:#fff;border:1px solid #ccc;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.15);min-width:180px;max-height:260px;overflow:auto;padding:8px 10px;';

        // Helper to build a row
        const _row = (input, labelText) => {
            const row = document.createElement('label');
            row.style.cssText = 'display:flex;align-items:center;gap:6px;margin:4px 0;cursor:pointer;font-weight:400;';
            row.appendChild(input);
            const span = document.createElement('span');
            span.textContent = labelText;
            row.appendChild(span);
            return row;
        };

        // Base section
        if (baseEntries.length > 0) {
            const head = document.createElement('div');
            head.textContent = 'Base';
            head.style.cssText = 'font-weight:600;color:#666;margin:2px 0 4px;font-size:11px;text-transform:uppercase;';
            panel.appendChild(head);

            const groupName = 'aot-preview-base-' + uuid;
            baseEntries.forEach((name) => {
                const layer = baseMaps[name];
                const radio = document.createElement('input');
                radio.type = 'radio';
                radio.name = groupName;
                if (layer === activeBaseLayer) radio.checked = true;
                radio.addEventListener('change', () => {
                    if (!radio.checked) return;
                    baseEntries.forEach((other) => {
                        const lyr = baseMaps[other];
                        const isThis = (lyr === layer);
                        if (typeof lyr.setVisibility === 'function') lyr.setVisibility(isThis);
                        updateVisibility(lyr, isThis);
                    });
                });
                panel.appendChild(_row(radio, name));
            });
        }

        // Overlay section
        if (overlayEntries.length > 0) {
            if (baseEntries.length > 0) {
                const sep = document.createElement('div');
                sep.style.cssText = 'border-top:1px solid #eee;margin:6px 0;';
                panel.appendChild(sep);
            }
            const head = document.createElement('div');
            head.textContent = 'Overlay';
            head.style.cssText = 'font-weight:600;color:#666;margin:2px 0 4px;font-size:11px;text-transform:uppercase;';
            panel.appendChild(head);

            overlayEntries.forEach((name) => {
                const layer = overlayMaps[name];
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.checked = !!layer._added;
                cb.addEventListener('change', () => {
                    if (typeof layer.setVisibility === 'function') layer.setVisibility(cb.checked);
                    updateVisibility(layer, cb.checked);
                });
                panel.appendChild(_row(cb, name));
            });
        }

        btn.addEventListener('click', () => {
            panel.style.display = (panel.style.display === 'none') ? 'block' : 'none';
        });

        wrap.appendChild(btn);
        wrap.appendChild(panel);

        // Map container needs relative positioning so absolute child anchors correctly
        if (window.getComputedStyle(mapContainer).position === 'static') {
            mapContainer.style.position = 'relative';
        }
        mapContainer.appendChild(wrap);

        this.previewLayerControl[uuid] = { _dom: wrap };
    },

    /**
     * Create Layer Object (Refactored from _renderLayer)
     * @private
     */
    _createLayer: function (uuid, map, layerType, finalUrl, defaultOptions, finalOptions) {
        // [Fix] Generic Placeholder Replacement from Options
        if (finalUrl && finalOptions) {
            Object.keys(finalOptions).forEach(key => {
                let val = finalOptions[key];
                
                if (typeof val === 'string' || typeof val === 'number') {
                    finalUrl = finalUrl.replace(new RegExp('\{' + key + '\}', 'gi'), val);
                }
            });
        }

        // Validation Checks
        const checkUrl = finalUrl.replace(/\{(x|y|z|s|r)\}/gi, '');
        let placeholderMatch = checkUrl.match(/\{([a-zA-Z0-9_]+)\}/);

        if (placeholderMatch) {
            console.error("[AoTGeoInputPreview] Validation Failed: URL contains unreplaced placeholder:", placeholderMatch[0]);
            console.warn("Final URL was:", checkUrl);
            console.warn("Input Options (Processed):", finalOptions);
            return null;
        }



        // [MapLibre] Resolve effective source-side native maxzoom/minzoom.
        // Source 'maxzoom' = the highest zoom for which the server actually provides tiles.
        // MapLibre overzooms (digital zoom) beyond this automatically — the camera's maxZoom
        // is set separately on the Map instance from AOT_GEO_CONFIG.max_zoom.
        // Channel definitions provide maxNativeZoom (preferred) or maxZoom; no URL parsing.
        const _resolveSourceZoom = (opts) => {
            opts = opts || {};
            let nz = opts.maxNativeZoom;
            if (nz === undefined || nz === null) nz = opts.maxzoom;
            if (nz === undefined || nz === null) nz = opts.maxZoom;
            if (nz === undefined || nz === null || isNaN(nz)) nz = 18;

            let minz = opts.minZoom;
            if (minz === undefined || minz === null) minz = opts.minzoom;
            if (minz === undefined || minz === null || isNaN(minz)) minz = 0;
            return { minzoom: parseInt(minz, 10) || 0, maxzoom: parseInt(nz, 10) };
        };

        // [MapLibre] Build a WMS GetMap tile URL with {bbox-epsg-3857} placeholder.
        // MapLibre raster sources don't synthesize WMS requests like L.tileLayer.wms;
        // we serialize the GetMap params here and let MapLibre substitute the bbox per tile.
        const _buildWmsUrl = (baseUrl, opts) => {
            opts = opts || {};
            const params = {
                service: 'WMS',
                request: 'GetMap',
                layers: opts.layers || '',
                styles: opts.styles || '',
                format: opts.format || 'image/png',
                transparent: (opts.transparent === false ? 'false' : 'true'),
                version: opts.version || '1.1.1',
                width: opts.tileSize || 256,
                height: opts.tileSize || 256
            };
            if (String(params.version).indexOf('1.3') === 0) {
                params.crs = opts.crs || 'EPSG:3857';
            } else {
                params.srs = opts.srs || opts.crs || 'EPSG:3857';
            }
            // Pass-through any extra WMS params from options (e.g. ISRIC mapserv 'map').
            const exclude = ['attribution', 'opacity', 'tileSize', 'maxNativeZoom', 'maxZoom', 'maxzoom', 'minZoom', 'minzoom', 'name', 'detectRetina', 'subdomains', 'crs', 'srs'];
            Object.keys(opts).forEach(k => {
                if (k in params || exclude.indexOf(k) !== -1) return;
                const v = opts[k];
                if (v === null || v === undefined || typeof v === 'object' || typeof v === 'function') return;
                params[k] = v;
            });
            const parts = [];
            Object.keys(params).forEach(k => {
                parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(String(params[k])));
            });
            // bbox is a MapLibre placeholder — keep literal, do not URL-encode.
            parts.push('bbox={bbox-epsg-3857}');
            const sep = (baseUrl.indexOf('?') >= 0) ? '&' : '?';
            return baseUrl + sep + parts.join('&');
        };

        // [MapLibre] Resolve Leaflet-style {s} subdomain and {r} retina tokens.
        // MapLibre does not interpret these — must expand/replace before passing tiles[].
        const _resolveTileUrls = (url, opts) => {
            // {r}: '@2x' on retina displays, empty otherwise. Leaflet's `detectRetina` semantics.
            const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
            const retinaSuffix = (opts && opts.detectRetina && dpr > 1) ? '@2x' : '';
            let resolved = url.replace(/\{r\}/gi, retinaSuffix);

            // {s}: expand to multiple URLs so MapLibre rotates subdomains via tiles[]
            if (/\{s\}/i.test(resolved)) {
                let subs = (opts && opts.subdomains) || ['a', 'b', 'c'];
                if (typeof subs === 'string') subs = subs.split('');
                if (!Array.isArray(subs) || subs.length === 0) subs = ['a', 'b', 'c'];
                return subs.map(s => resolved.replace(/\{s\}/gi, s));
            }
            return [resolved];
        };

        try {
            let layer;
            if (layerType === 'vector') {
                // [MapLibre] Vector GL style — load style.json directly via map.setStyle().
                // MapTiler / Mapbox style URLs return JSON, not image tiles.
                // Using them as raster source causes InvalidStateError (image decode failure).
                if (typeof maplibregl !== 'undefined') {
                    const styleUrl = finalUrl;
                    layer = {
                        _type: 'vector',
                        _added: false,
                        addTo: (m) => {
                            try {
                                m.setStyle(styleUrl);
                                layer._added = true;
                            } catch (e) {
                                console.warn('[AoTGeoInputPreview] vector setStyle failed:', e);
                            }
                            return layer;
                        },
                        remove: () => {
                            // Reset to blank style on removal
                            try { map.setStyle({ version: 8, sources: {}, layers: [] }); } catch (e) {}
                            layer._added = false;
                        },
                        setVisibility: (visible) => {
                            if (visible) layer.addTo(map);
                            else layer.remove();
                        }
                    };
                }
            } else if (layerType === 'wms') {
                const wmsOptions = {
                    format: 'image/png',
                    transparent: true,
                    attribution: 'Preview'
                };
                Object.assign(wmsOptions, defaultOptions, finalOptions);

                // [MapLibre] WMS support for MapLibre
                if (typeof maplibregl !== 'undefined') {
                    const sourceId = 'preview-wms-' + uuid + '-' + (Math.random().toString(36).substr(2, 6));
                    layer = {
                        _sourceId: sourceId,
                        _layerId: sourceId,
                        _type: 'wms',
                        _options: wmsOptions,
                        _added: false,
                        addTo: (m) => {
                            const doAdd = () => {
                                if (!m.getSource(sourceId)) {
                                    // If finalUrl is a backend proxy path, append BBOX/size params directly.
                                    // The proxy handles all WMS parameters server-side; browser only supplies bbox.
                                    const tileSize = wmsOptions.tileSize || 256;
                                    const wmsTile = /^\/api\//.test(finalUrl)
                                        ? finalUrl + '?BBOX={bbox-epsg-3857}&WIDTH=' + tileSize + '&HEIGHT=' + tileSize
                                        : _buildWmsUrl(finalUrl, wmsOptions);
                                    m.addSource(sourceId, { type: 'raster', tiles: [wmsTile], tileSize: tileSize });
                                }
                                if (!m.getLayer(sourceId)) {
                                    m.addLayer({ id: sourceId, type: 'raster', source: sourceId, paint: { 'raster-opacity': wmsOptions.opacity || 1.0 } });
                                }
                                layer._added = true;
                            };
                            if (m.isStyleLoaded()) doAdd(); else m.once('load', doAdd);
                            return layer;
                        },
                        remove: () => {
                            try { if (map.getLayer(sourceId)) map.removeLayer(sourceId); } catch(e) {}
                            try { if (map.getSource(sourceId)) map.removeSource(sourceId); } catch(e) {}
                            layer._added = false;
                        },
                        setVisibility: (visible) => {
                            const apply = () => {
                                if (!layer._added) {
                                    if (visible) layer.addTo(map);
                                    return;
                                }
                                try {
                                    map.setLayoutProperty(sourceId, 'visibility', visible ? 'visible' : 'none');
                                } catch (e) { /* silent */ }
                            };
                            if (map.isStyleLoaded()) apply(); else map.once('load', apply);
                        }
                    };
                }
            } else {
                const tileOpts = {
                    maxZoom: 18,
                    attribution: 'Preview'
                };
                Object.assign(tileOpts, defaultOptions, finalOptions);

                // [MapLibre] XYZ tile support
                if (typeof maplibregl !== 'undefined') {
                    const sourceId = 'preview-xyz-' + uuid + '-' + (Math.random().toString(36).substr(2, 6));
                    layer = {
                        _sourceId: sourceId,
                        _layerId: sourceId,
                        _type: 'xyz',
                        _options: tileOpts,
                        _added: false,
                        addTo: (m) => {
                            const doAdd = () => {
                                if (!m.getSource(sourceId)) {
                                    const zb = _resolveSourceZoom(tileOpts);
                                    m.addSource(sourceId, { type: 'raster', tiles: _resolveTileUrls(finalUrl, tileOpts), scheme: tileOpts.tms ? 'tms' : 'xyz', tileSize: tileOpts.tileSize || 256, minzoom: zb.minzoom, maxzoom: zb.maxzoom });
                                }
                                if (!m.getLayer(sourceId)) {
                                    m.addLayer({ id: sourceId, type: 'raster', source: sourceId, paint: { 'raster-opacity': tileOpts.opacity || 1.0 } });
                                }
                                layer._added = true;
                            };
                            if (m.isStyleLoaded()) doAdd(); else m.once('load', doAdd);
                            return layer;
                        },
                        remove: () => {
                            try { if (map.getLayer(sourceId)) map.removeLayer(sourceId); } catch(e) {}
                            try { if (map.getSource(sourceId)) map.removeSource(sourceId); } catch(e) {}
                            layer._added = false;
                        },
                        setVisibility: (visible) => {
                            const apply = () => {
                                if (!layer._added) {
                                    if (visible) layer.addTo(map);
                                    return;
                                }
                                try {
                                    map.setLayoutProperty(sourceId, 'visibility', visible ? 'visible' : 'none');
                                } catch (e) { /* silent */ }
                            };
                            if (map.isStyleLoaded()) apply(); else map.once('load', apply);
                        }
                    };
                }
            }

            // [MapLibre] tileerror handler
            if (map && typeof map.on === 'function') {
                map.on('error', function (e) {
                    console.error("[AoTGeoInputPreview] Tile Loading Failed:", e.error);
                });
            }
            
            console.info("[AoTGeoInputPreview] Layer Created:", {
                 name: finalOptions.name || 'Layer',
                 url: finalUrl,
                 options: finalOptions
            });

            return layer;

        } catch (e) {
            // console.error("Leaflet Error:", e);
            return null;
        }
    },

    // Kept for backward compatibility if called directly
    _renderLayer: function (uuid, map, layerType, finalUrl, defaultOptions, finalOptions) {
        const layer = this._createLayer(uuid, map, layerType, finalUrl, defaultOptions, finalOptions);
        if (layer) layer.addTo(map);
    },

    /**
     * Refresh Preview for a specific Channel (Legacy alias, now just triggers load)
     * @param {string} uuid 
     * @param {string} channelId 
     */
    refreshChannel: function (uuid, channelId) {
        this.load(uuid);
    }
};

// Auto-Initialize
AoTGeoInputPreview.init();
