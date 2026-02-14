/**
 * Geo Settings Page Logic
 * Handles initialization, custom controls, and form synchronization.
 */
document.addEventListener('DOMContentLoaded', function () {
    // Check if Config is loaded
    if (!window.AOT_GEO_CONFIG) {
        // console.error("AOT_GEO_CONFIG is missing. Map cannot be initialized.");
        return;
    }

    // --- 1. Settings & State ---
    // [Fix] config IS the settings object. Flat structure.
    const settings = window.AOT_GEO_CONFIG || {};

    // Store Saved Values for Reset (Source of Truth: Server Config)
    const savedLat = parseFloat(settings.default_lat) || 37.5665;
    const savedLng = parseFloat(settings.default_lng) || 126.9780;
    const savedZoom = parseFloat(settings.zoom) || 12;

    // --- 2. Initialize Map ---
    // Ensure AoTMapLoader is loaded
    if (typeof AoTMapLoader === 'undefined') {
        // console.error("AoTMapLoader is not loaded.");
        return;
    }

    // Use 'geo_setting_map' preset
    // No need to pass default center/zoom/maxZoom overrides from DOM Inputs
    // The Loader now reads them from AOT_GEO_CONFIG automatically.
    const mapInit = AoTMapLoader.initMap('setting-map', 'geo_setting_map');

    const { map, layerControl } = mapInit;


    // Scale is now added by AoTMapLoader globally (Bottom-Right)

    // Add Copyright
    if (window.AoTMapUtils && window.AoTMapUtils.addCopyrightControl) {
        window.AoTMapUtils.addCopyrightControl(map);
    }

    // --- 3. Initialize Page Logic ---
    AoTGeoSettings.init(map, layerControl, { savedLat, savedLng, savedZoom });
});

const AoTGeoSettings = {
    init: function (map, layerControl, defaults = {}) {
        this.map = map;
        this.layerControl = layerControl;
        this.defaults = defaults;
        this.initControls();
        this.initSync();
        this.initSync();
        this.initSearch();
        this.initThemeSettings();
    },

    initThemeSettings: function () {
        // --- Theme Configuration Logic ---
        const config = window.AOT_GEO_CONFIG || {};
        const theme = config.theme_config || {};

        // 1. Initialize Inputs from Config
        // [Fix] Do NOT overwrite with default (D.site) if config is missing. Rely on Jinja (Server-side) value.
        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el && val) el.value = val;
        };

        // Default Palette (Keep for Reset)
        const D = {
            site: '#DF5353',
            zone: '#28a745',
            facility: '#82898f',
            equipment: '#007bff',
            device: '#995aff',
            panel_bg: '#ffffff',
            panel_opacity: '90'
        };

        setVal('color-site', theme.site);
        setVal('color-zone', theme.zone);
        setVal('color-facility', theme.facility);
        setVal('color-equipment', theme.equipment);
        setVal('color-device', theme.device);
        setVal('color-panel-bg', theme.panel_bg);
        setVal('range-panel-opacity', theme.panel_opacity);

        // 2. Opacity Slider Display
        const rangeOp = document.getElementById('range-panel-opacity');
        const spanOp = document.getElementById('opacity-val');

        if (rangeOp && spanOp) {
            // Init text
            spanOp.textContent = rangeOp.value + '%';
            // Live Update
            rangeOp.addEventListener('input', () => {
                spanOp.textContent = rangeOp.value + '%';
            });
        }

        // 3. Reset Button
        const btnReset = document.getElementById('btn-reset-theme');
        if (btnReset) {
            btnReset.addEventListener('click', () => {
                if (!confirm(_('confirm_reset_theme'))) return;

                document.getElementById('color-site').value = D.site;
                document.getElementById('color-zone').value = D.zone;
                document.getElementById('color-facility').value = D.facility;
                document.getElementById('color-equipment').value = D.equipment;
                document.getElementById('color-device').value = D.device;
                document.getElementById('color-panel-bg').value = D.panel_bg;

                if (rangeOp) {
                    rangeOp.value = D.panel_opacity;
                    rangeOp.dispatchEvent(new Event('input')); // Update span
                }
            });
        }
    },

    initControls: function () {
        const map = this.map;
        const defaults = this.defaults;

        // --- Standard Tool Bindings (Matching logic from aot-geo-design.js) ---
        const bindIfExists = (id, handler) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('click', (e) => {
                e.preventDefault();
                handler(e);
            });
        };

        // Zoom
        bindIfExists('tool-zoom-in', () => map.zoomIn());
        bindIfExists('tool-zoom-out', () => map.zoomOut());

        // Fullscreen
        bindIfExists('tool-fullscreen', () => {
            // Use the card body wrapper or map container
            const elem = document.getElementById('setting-map');
            // Or the wrapper? Design uses 'geo-design-wrapper'.
            // Here map is inside .position-relative. Fullscreen on map container is usually safer for layout.
            if (!document.fullscreenElement) {
                elem.requestFullscreen().catch(err => {
                    // console.error(`Error attempting to enable full-screen mode: ${err.message}`);
                });
            } else {
                document.exitFullscreen();
            }
        });

        // Search Toggle (Overlay ID: setting-search-overlay)
        // bindIfExists('tool-search', () => {
        //      const overlay = document.getElementById('setting-search-overlay');
        //      if (overlay) {
        //          if (overlay.classList.contains('d-none')) {
        //              overlay.classList.remove('d-none');
        //              // Focus input
        //              setTimeout(() => {
        //                 const searchEl = overlay.querySelector('aot-map-search-fixed');
        //                 if (searchEl && searchEl.shadowRoot) {
        //                     const inp = searchEl.shadowRoot.getElementById('input');
        //                     if (inp) inp.focus();
        //                 }
        //              }, 100);
        //          } else {
        //              overlay.classList.add('d-none');
        //          }
        //      }
        // });

        // Locate
        bindIfExists('tool-locate', () => map.locate({ setView: true, maxZoom: 16 }));

        // Reset
        bindIfExists('tool-reset', () => {
            const lat = defaults.savedLat;
            const lng = defaults.savedLng;
            const zoom = defaults.savedZoom;
            if (lat !== undefined && lng !== undefined) {
                map.setView([lat, lng], zoom || 12);
            }
        });

        // --- Layer Control Placement ---
        // Use Shared Controls Helper to style it ONLY
        if (typeof AoTMapControls !== 'undefined') {
            // Do NOT call addStandardControls (it adds duplicate Leaflet controls)

            // [Sync Design] Move Layer Control to Custom Right Container
            if (this.layerControl) {
                const controlContainer = this.layerControl.getContainer();
                // Target: .map-tools-right inside the card
                // Use robust selector
                const targetContainer = document.querySelector('.map-tools-right');

                if (controlContainer && targetContainer) {
                    targetContainer.appendChild(controlContainer);
                    // Style it standardly
                    AoTMapControls.styleLayerControl(controlContainer);
                }
            }
        } else {
            // console.warn("AoTMapControls not loaded. Layer control styling might be missing.");
        }
    },

    initSearch: function () {
        if (window.AoTMapSearchController) {
            new AoTMapSearchController(this.map, {
                searchId: 'setting-search',
                toggleBtnId: 'tool-search', // Updated ID
                overlayId: 'setting-search-overlay',
                inputLatId: 'default_lat_input',
                inputLngId: 'default_lng_input'
            });
        }
    },

    initSync: function () {
        const map = this.map;

        // Map -> Inputs
        const updateInputs = () => {
            const center = map.getCenter();
            const zoom = map.getZoom();
            const latIn = document.getElementById('default_lat_input');
            const lngIn = document.getElementById('default_lng_input');
            const zoomIn = document.getElementById('default_zoom_input');

            const active = document.activeElement;

            // Only update if not currently focused (prevent fighting while typing)
            if (latIn && active !== latIn) latIn.value = center.lat.toFixed(6);
            if (lngIn && active !== lngIn) lngIn.value = center.lng.toFixed(6);
            if (zoomIn && active !== zoomIn) zoomIn.value = zoom.toFixed(1); // One decimal place is cleaner than many for Leaflet fractional zoom
        };

        // Use 'move' and 'zoom' for real-time updates during drag/animation
        map.on('move', updateInputs);
        map.on('zoom', updateInputs);

        // --- Layer Persistence Sync (New) ---
        // Create Hidden Input for Layer Mods
        const form = document.getElementById('geo_setting_form');
        let modInput = document.getElementById('layer_modifications');
        if (!modInput && form) {
            modInput = document.createElement('input');
            modInput.type = 'hidden';
            modInput.name = 'layer_modifications';
            modInput.id = 'layer_modifications';
            form.appendChild(modInput);
        }

        const layerMods = {};

        const updateMods = (layer, visible) => {
            if (!layer.aot_id) return;
            // [Fix] Use Base DB ID for persistence key, not exploded ID
            const modKey = layer.aot_base_id || layer.aot_id;

            if (!layerMods[modKey]) layerMods[modKey] = {};

            if (layer.aot_channel_id !== undefined) {
                layerMods[modKey]['channel_visible_' + layer.aot_channel_id] = (visible ? 'true' : 'false');
            } else {
                layerMods[modKey]['layer_visible'] = (visible ? 'true' : 'false');
            }
            // console.log("[GeoSetting] Layer Mod Update:", modKey, visible, layerMods);
            if (modInput) modInput.value = JSON.stringify(layerMods);
        };

        map.on('overlayadd', e => updateMods(e.layer, true));
        map.on('overlayremove', e => updateMods(e.layer, false));

        map.on('baselayerchange', e => {
            const activeLayer = e.layer;
            updateMods(activeLayer, true);

            // Deactivate other Base Layers
            // We iterate config to find potential base layers
            if (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.layers) {
                window.AOT_GEO_CONFIG.layers.forEach(l => {
                    const isBase = (l.is_base === true) || (l.role === 'base');
                    if (isBase) {
                        // If it's NOT the active layer (ID mismatch OR Channel mismatch)
                        // Note: activeLayer has aot_id and aot_channel_id
                        const matchId = (l.id === activeLayer.aot_id);

                        if (activeLayer.aot_channel_id) {
                            // Multi-channel scenario
                            // If this config layer IS the same ID, check channels
                            if (matchId) {
                                // Iterate channels? 
                                // Config layer structure: l.options (JSON string) -> has channels? 
                                // Actually we don't have parsed channels here easily.
                                // Simplification:
                                // If we switched base layer, we just mark the previously active one as Hidden?
                                // BUT we don't know which one was previously active easily.

                                // Strategy: Just mark 'layer_visible' = false for Single Base Layers that don't match.
                                // Strategy: Just mark 'layer_visible' = false for Single Base Layers that don't match.
                                if (!l.options || JSON.stringify(l.options).indexOf('channel_selector') === -1) {
                                    // Single Layer
                                    // If matched ID but we are in multi-channel active -> Conflict?
                                    // Just assume Single Base Layers for now.
                                }
                            } else {
                                // Different Layer ID. Identify if Single or Multi?
                                // Mark Single 'layer_visible' = false.
                                // Mark Known Channels as false?
                                // Hard to enumerate channels without parsing options.
                            }
                        } else {
                            // Active is Single Layer
                            if (!matchId) {
                                // Assuming l is also Single because multi-channel base layers are complex?
                                // Just mark layer_visible = false for safety.
                                if (!layerMods[l.id]) layerMods[l.id] = {};
                                layerMods[l.id]['layer_visible'] = 'false';
                            }
                        }
                    }
                });
                if (modInput) modInput.value = JSON.stringify(layerMods);
            }
        });

        // Inputs -> Map
        const updateMap = () => {
            const lat = parseFloat(document.getElementById('default_lat_input').value);
            const lng = parseFloat(document.getElementById('default_lng_input').value);
            const zoomVal = parseFloat(document.getElementById('default_zoom_input').value);

            if (!isNaN(lat) && !isNaN(lng)) {
                map.panTo([lat, lng]);
            }
            if (!isNaN(zoomVal)) {
                map.setZoom(zoomVal);
            }
        };

        const latInput = document.getElementById('default_lat_input');
        const lngInput = document.getElementById('default_lng_input');
        const zoomInput = document.getElementById('default_zoom_input');

        if (latInput) latInput.addEventListener('change', updateMap);
        if (lngInput) lngInput.addEventListener('change', updateMap);
        if (zoomInput) {
            zoomInput.addEventListener('input', updateMap);
            // Also listen to 'change' for spinner clicks if 'input' misses them (some browsers)
            zoomInput.addEventListener('change', updateMap);
        }

        // --- AJAX Submit (Prevent Reload) ---
        if (form) {
            // console.log("[GeoSetting] Attaching AJAX Submit Handler to #geo_setting_form");
            form.onsubmit = function (e) {
                e.preventDefault();

                // Collect Data
                const formData = new FormData(form);

                // Log for debug
                const modVal = document.getElementById('layer_modifications') ? document.getElementById('layer_modifications').value : "None";
                // console.log("[GeoSetting] Submitting Form. Layer Mods:", modVal);
 
                // Send AJAX
                fetch(window.location.href, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                })
                    .then(response => {
                        if (response.headers.get("content-type").indexOf("json") !== -1) {
                            return response.json();
                        } else {
                            // Fallback if backend didn't return JSON (e.g. error page)
                            return { status: 'error', message: 'Invalid response' };
                        }
                    })
                    .then(data => {
                        // console.log("[GeoSetting] Save Response:", data);
                        if (data.status === 'success') {
                            AoTGeoSettings.showToast(_('settings_saved'), 'success');
                        } else {
                        AoTGeoSettings.showToast(_('save_error'), 'error');
                        }
                    })
                    .catch(err => {
                        // console.error("[GeoSetting] Save Error:", err);
                        AoTGeoSettings.showToast(_('save_error_occurred'), 'error');
                    });


                return false;
            };
        }
    },
    showToast: function (message, type = 'info') {
        if (typeof window.showToast !== 'undefined') {
            window.showToast(message, type);
            return;
        }

        const settings = window.AoTGlobalSettings || {};
        let shouldHide = false;
        if (type === 'success' && settings.hide_success) shouldHide = true;
        if (type === 'info' && settings.hide_info) shouldHide = true;
        if ((type === 'warning' || type === 'error') && settings.hide_warning) shouldHide = true;

        if (shouldHide) return;

        if (typeof toastr !== 'undefined') toastr[type](message);
        else alert(message);
    }
};
