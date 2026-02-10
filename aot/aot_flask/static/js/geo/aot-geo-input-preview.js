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
        form.find('.gis-custom-option').not('[data-is-channel="true"]').each(function () {
            const name = $(this).attr('name');
            if (name) {
                if ($(this).attr('type') === 'checkbox') {
                    if ($(this).is(':checked')) {
                        if (!globalOptions[name]) globalOptions[name] = [];
                        globalOptions[name].push($(this).val());
                    }
                } else {
                    globalOptions[name] = $(this).val();
                }
            }
        });

        // 2. Initialize Map
        if (container._leaflet_id && !this.previewMaps[uuid]) {
            container.innerHTML = '';
            container._leaflet_id = null;
        }

        if (!this.previewMaps[uuid]) {
            try {
                /*
                // [Debug] Log Map Init Options
                console.log("[AoTGeoInputPreview] Init Map Options:", { 
                    smooth_zoom: window.AOT_GEO_CONFIG?.smooth_zoom,
                    digital_zoom: window.AOT_GEO_CONFIG?.digital_zoom
                });
                */
                const initResult = AoTMapLoader.initMap(containerId, 'geo_input_map', { layers: [] });
                this.previewMaps[uuid] = initResult.map;
                
                // Add Copyright
                if (window.AoTMapUtils && window.AoTMapUtils.addCopyrightControl) {
                    window.AoTMapUtils.addCopyrightControl(this.previewMaps[uuid]);
                }
            } catch (e) {
                // console.error("Map init failed:", e);
                return;
            }
        }

        const map = this.previewMaps[uuid];
        
        // [Fix] Invalidate Size for Modal Rendering
        // Ensure map renders correctly after modal transition
        setTimeout(() => {
            map.invalidateSize();
        }, 200);

        // 3. Clear Previous Layers & Control
        // Remove Layer Control if exists
        if (this.previewLayerControl && this.previewLayerControl[uuid]) {
            try { map.removeControl(this.previewLayerControl[uuid]); } catch (e) { }
            delete this.previewLayerControl[uuid];
        }

        if (this.previewLayers[uuid] && Array.isArray(this.previewLayers[uuid])) {
            this.previewLayers[uuid].forEach(layer => {
                try { map.removeLayer(layer); } catch (e) { }
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

        // Prevent stacking listeners
        map.off('overlayadd');
        map.off('overlayremove');
        map.off('baselayerchange');

        map.on('overlayadd', function (e) { updateVisibility(e.layer, true); });
        map.on('overlayremove', function (e) { updateVisibility(e.layer, false); });

        map.on('baselayerchange', function (e) {
            // New Base Layer Active
            updateVisibility(e.layer, true);

            // Deactivate others
            // Iterate all baseMaps
            for (const layer of Object.values(baseMaps)) {
                if (layer !== e.layer && layer.aot_channel_id) {
                    updateVisibility(layer, false);
                }
            }
        });

        // [Fix] Reinforce Attribution Early
        if (window.AoTMapUtils && window.AoTMapUtils.addCopyrightControl) {
            window.AoTMapUtils.addCopyrightControl(map);
        }
        // We initialize generic OSM if base layer role, to allow switching back?
        // No, preview focuses on the input.

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
                        finalUrl = finalUrl.replace(new RegExp('\{' + key + '\}', 'gi'), val);
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
            
            // [Fix] Default fallback for {ts} (common in WMTS/VWorld)
            if (finalUrl.match(/\{ts\}/i) && !itemOptions.ts) {
                // console.warn("[AoTGeoInputPreview] TS missing, defaulting to GoogleMapsCompatible");
                itemOptions.ts = 'GoogleMapsCompatible';
                finalUrl = finalUrl.replace(/\{ts\}/gi, 'GoogleMapsCompatible');
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

            // [Fix] Digital Zoom Logic
            // Force maxZoom to be high enough (e.g. 19 or global mapMaxZoom) to allow digital stretching
            // if maxNativeZoom is set.
            if (itemOptions.maxNativeZoom) {
                 // Use global config if available or default 25
                 const mapMaxZoom = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.maxZoom) ? window.AOT_GEO_CONFIG.maxZoom : 25;
                 
                 if (!itemOptions.maxZoom || itemOptions.maxZoom <= itemOptions.maxNativeZoom) {
                      itemOptions.maxZoom = mapMaxZoom;
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

            const layer = this._createLayer(uuid, layerType, finalUrl, defaultOptions, itemOptions);

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

        // 6. Add Layer Control
        // Check if we have multiple layers or at least one to show control
        if (Object.keys(baseMaps).length > 0 || Object.keys(overlayMaps).length > 0) {
            const layerControl = L.control.layers(baseMaps, overlayMaps, { collapsed: false }).addTo(map);
            if (!this.previewLayerControl) this.previewLayerControl = {};
            this.previewLayerControl[uuid] = layerControl;

            // Apply AoT Styling
            if (window.AoTMapControls && window.AoTMapControls.styleLayerControl) {
                window.AoTMapControls.styleLayerControl(layerControl.getContainer());
            }
        }
    },

    /**
     * Create Layer Object (Refactored from _renderLayer)
     * @private
     */
    _createLayer: function (uuid, layerType, finalUrl, defaultOptions, finalOptions) {
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



        try {
            let layer;
            if (layerType === 'wms') {
                const wmsOptions = {
                    format: 'image/png',
                    transparent: true,
                    attribution: 'Preview'
                };
                Object.assign(wmsOptions, defaultOptions, finalOptions);
                // if (!wmsOptions.layers) return null; // WMS requires layers param usually
                layer = L.tileLayer.wms(finalUrl, wmsOptions);
            } else {
                const tileOpts = {
                    maxZoom: 18,
                    attribution: 'Preview'
                };
                Object.assign(tileOpts, defaultOptions, finalOptions);
                layer = L.tileLayer(finalUrl, tileOpts);
            }

            layer.on('tileerror', function (e) {
                let failUrl = e.url; // Sometimes provided
                if (!failUrl && e.coords && layer.getTileUrl) {
                    failUrl = layer.getTileUrl(e.coords);
                }
                if (!failUrl && e.tile) failUrl = e.tile.src;
                
                console.error("[AoTGeoInputPreview] Tile Loading Failed:", e.error, "URL:", failUrl);
            });
            
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
        // Deprecated inner usage, redirected to create logic for consistency
        const layer = this._createLayer(uuid, layerType, finalUrl, defaultOptions, finalOptions);
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
