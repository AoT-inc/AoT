/**
 * AoT Map Configuration UI Logic
 * Handles lazy loading of options and color picker synchronization.
 */

// AoT Map Configuration Logic
// Handles synchronization between the live widget map and the configuration form.

// [New] Auto-Initialization Trigger
// Automatically detects when a widget configuration modal opens and initializes the map config sync.
$(document).ready(function() {
    $(document).on('show.bs.modal', '.modal', function (event) {
        const modalId = $(this).attr('id');
        
        // [Verified Detection] Check for standard AoT Widget Config Modal ID: modal_config_{UID}
        if (modalId && modalId.startsWith('modal_config_')) {
            const uid = modalId.replace('modal_config_', '');
            
            // Check if this UID belongs to an existing Map Widget App
            // This ensures we only auto-init for Map Widgets, not other types
            if (window.AoTMapApp && window.AoTMapApp[uid]) {
                console.log(`[AoT Map Config] Auto-initializing config for Map Widget: ${uid}`);
                if (window.initAoTMapConfig) {
                    window.initAoTMapConfig(uid, null); 
                }
            }
        }
    });
});

window.initAoTMapConfigUI = function(uid, currentMap) {
    // 1. Color Picker Synchronization
    const picker = document.getElementById('device-shape-color-picker-' + uid);
    const textInput = document.getElementById('device-shape-color-' + uid);
    
    if (picker && textInput) {
        // Unbind previous listeners to avoid duplicates if re-opened
        // (Though typically unique_id wrapper is re-rendered)
        
        picker.oninput = function() {
            textInput.value = picker.value;
        };
        
        textInput.onchange = function() {
            // Validate hex format
            if (/^#[0-9A-F]{6}$/i.test(textInput.value)) {
                picker.value = textInput.value;
            }
        };
    }

    // 2. Delegate to existing map initialization if present
    if (window.initAoTMapConfig) {
        window.initAoTMapConfig(uid, currentMap);
    }

    // 3. Lazy Load Config Options
    // Check global cache first
    if (window.AOT_MAP_CONFIG_CACHE) {
        populateMapConfigSelects(uid, window.AOT_MAP_CONFIG_CACHE, currentMap);
        return;
    }
    
    if (window.AOT_MAP_CONFIG_LOADING) {
         // Retry in 500ms
         setTimeout(() => window.initAoTMapConfigUI(uid, currentMap), 500);
         return;
    }
    
    window.AOT_MAP_CONFIG_LOADING = true;

    $.ajax({
        url: '/api/widget/aot_map/config_options',
        method: 'GET',
        success: function(data) {
            window.AOT_MAP_CONFIG_CACHE = data;
            window.AOT_MAP_CONFIG_LOADING = false;
            
            // Populate for THIS widget
            populateMapConfigSelects(uid, data, currentMap);
        },
        error: function(err) {
            console.error("Failed to load map config options", err);
            window.AOT_MAP_CONFIG_LOADING = false;
        }
    });
};

// Implement the missing initialization logic
window.initAoTMapConfig = function(uid, currentMap) {
    const $modal = $('#modal_config_' + uid);
    const mapSelect = document.getElementById('map-select-base-' + uid);
    
    // [Fix] Target framework-generated inputs by name, SCOPED TO MODAL
    const findInput = (nameSuffix) => {
        if ($modal.length) {
            let found = $modal.find(`input[name="custom_option_${nameSuffix}"]`);
            if (found.length) return found[0];
            found = $modal.find(`input[name$="${nameSuffix}"]`);
            if (found.length) return found[0];
        }
        // Last resort: search entire document if modal not found
        return document.querySelector(`input[name="custom_option_${nameSuffix}"]`);
    };

    const latInput = findInput('fallback_latitude');
    const lngInput = findInput('fallback_longitude');
    const zoomInput = findInput('default_zoom');

    console.log("[AoT Map Config] UID: " + uid + " CurrentMap: " + currentMap + " latInputFound: " + !!latInput);

    // [Fix] Logic extracted to function for immediate execution
    const syncMapStateToForm = function() {
        if (window.AoTMapApp && window.AoTMapApp[uid] && window.AoTMapApp[uid].map) {
             const map = window.AoTMapApp[uid].map;
             const center = map.getCenter();
             const zoom = map.getZoom();
             
             // [Fix] Update ALL matching inputs (if duplicates exist)
             const updateAll = (suffix, val) => {
                 // Try multiple selector patterns including just name=suffix
                 const selector = `input[name="custom_option_${suffix}"], input[name="${suffix}"]`;
                 const inputs = $modal.find(selector);
                 
                 if (inputs.length > 0) {
                    console.log(`[AoT Map Config] Updating ${suffix} to:`, val);
                    inputs.val(val);
                 } else {
                    console.warn(`[AoT Map Config] Input not found for: ${suffix} (Selector: ${selector})`);
                 }
             };

             updateAll('fallback_latitude', center.lat.toFixed(6));
             updateAll('fallback_longitude', center.lng.toFixed(6));
             updateAll('default_zoom', zoom);
             updateAll('map_default_zoom', zoom); // Some templates might use this name

             // Sync Layers
             if (window.AoTMapApp[uid].baseLayers) {
                 let activeBase = "";
                 for (let name in window.AoTMapApp[uid].baseLayers) {
                     if (map.hasLayer(window.AoTMapApp[uid].baseLayers[name])) {
                         activeBase = name;
                         break;
                     }
                 }
                 updateAll('selected_base_layer', activeBase);
             }

             if (window.AoTMapApp[uid].overlayLayers) {
                 let activeOverlays = [];
                 for (let name in window.AoTMapApp[uid].overlayLayers) {
                     if (map.hasLayer(window.AoTMapApp[uid].overlayLayers[name])) {
                         activeOverlays.push(name);
                     }
                 }
                 updateAll('active_layers', activeOverlays.join(','));
             }
        }
    };

    if ($modal.length) {
        $modal.off('show.bs.modal', syncMapStateToForm); // Prevent duplicates
        $modal.on('show.bs.modal', syncMapStateToForm);
        
        // [Critical Fix] Execute immediately if this function was called (e.g. by auto-init on show)
        // This ensures the form is filled even if the 'show.bs.modal' event has already bubbled past the modal.
        syncMapStateToForm();
    }

    if (mapSelect) {
        $(mapSelect).on('changed.bs.select', function (e, clickedIndex, isSelected, previousValue) {
            // [Fix] Only update if USER explicitly clicked an option.
            // Programmatic changes (init/refresh) should not reset the form.
            if (clickedIndex === undefined && !e.originalEvent) return;

            const selectedOption = $(this).find('option:selected');
            const center = selectedOption.data('center'); // [lat, lng] array
            const zoom = selectedOption.data('zoom');
            
            if (center && center.length === 2 && latInput && lngInput) {
                latInput.value = center[0];
                lngInput.value = center[1];
            }
            if (zoom && zoomInput) {
                zoomInput.value = zoom;
            }
        });
    }
};

function populateMapConfigSelects(uid, data, savedMapId) {
    // Helper to populate a selectpicker and preserve selection
    // Helper to populate a selectpicker and preserve selection
    var updateSelect = function(domId, items) {
        var $sel = $('#' + domId);
        if ($sel.length === 0) return;
        
        var rawIds = $('#aot-map-device-ids-' + uid).val();
        var allSavedIds = rawIds ? rawIds.split(',').map(s => s.trim()) : [];
        
        var savedIds = [];
        
        // Measurement specifically targets their own fields
        if (domId.indexOf('map-select-meas-input') !== -1) {
            var raw = $('#aot-map-meas-input-' + uid).val();
            savedIds = raw ? raw.split(',').map(s => s.trim()) : [];
        } else if (domId.indexOf('map-select-meas-output') !== -1) {
            var raw = $('#aot-map-meas-output-' + uid).val();
            savedIds = raw ? raw.split(',').map(s => s.trim()) : [];
        } else if (domId.indexOf('map-select-meas-function') !== -1) {
            var raw = $('#aot-map-meas-function-' + uid).val();
            savedIds = raw ? raw.split(',').map(s => s.trim()) : [];
        } else {
            // [Fix] For deviceSelectors, use exact matching (no expansion)
            // This prevents Output selections (uuid::0) from checking Input boxes (uuid)
            savedIds = allSavedIds;
        }

        $sel.empty();
        items.forEach(function(item) {
             var isSel = savedIds.includes(String(item.id));
             var txt = item.name + (item.has_coords === false ? ' [좌표 없음]' : '');
             var opt = new Option(txt, item.id, false, isSel);
             $sel.append(opt);
        });
        
        try { $sel.selectpicker('refresh'); } catch(e) { }
    };
    
    // 1. Populate all dropdowns first (Sequentially but silently)
    updateSelect('map-select-inputs-' + uid, data.available_inputs);
    updateSelect('map-select-outputs-' + uid, data.available_outputs);
    updateSelect('map-select-functions-' + uid, data.available_functions);
    updateSelect('map-select-meas-input-' + uid, data.available_measurements_input);
    updateSelect('map-select-meas-output-' + uid, data.available_measurements_output);
    updateSelect('map-select-meas-function-' + uid, data.available_measurements_function);

    // 2. Attach Sync Listeners AFTER all are populated to avoid race conditions
    var deviceSelectors = [
        '#map-select-inputs-' + uid, 
        '#map-select-outputs-' + uid, 
        '#map-select-functions-' + uid
    ].join(',');

    $(deviceSelectors).on('changed.bs.select', function() {
        var d1 = $('#map-select-inputs-' + uid).val() || [];
        var d2 = $('#map-select-outputs-' + uid).val() || [];
        var d3 = $('#map-select-functions-' + uid).val() || [];
        var distinctIds = [...new Set([].concat(d1, d2, d3))].filter(x => x);
        console.log("[AoT Config] Devices synced to hidden input. Count:", distinctIds.length);
        $('#aot-map-device-ids-' + uid).val(distinctIds.join(','));
    });

    $('#map-select-meas-input-' + uid).on('changed.bs.select', function() {
        $('#aot-map-meas-input-' + uid).val(($(this).val() || []).join(','));
    });
    $('#map-select-meas-output-' + uid).on('changed.bs.select', function() {
        $('#aot-map-meas-output-' + uid).val(($(this).val() || []).join(','));
    });
    $('#map-select-meas-function-' + uid).on('changed.bs.select', function() {
        $('#aot-map-meas-function-' + uid).val(($(this).val() || []).join(','));
    });
    
    // Update Maps Dropdown
    var $mapSel = $('#map-select-base-' + uid);
    if ($mapSel.length) {
        $mapSel.empty();
        
        // Add localized default option
        var defaultText = $mapSel.data('placeholder') || '지도 선택';
        $mapSel.append(new Option(defaultText, '')); 
        
        data.available_maps.forEach(function(m) {
            // [Fix] Robust selection check: trim and case-insensitive
            const cleanSaved = String(savedMapId || "").trim().toLowerCase();
            const cleanCurrent = String(m.id || "").trim().toLowerCase();
            const isSel = (cleanSaved && cleanCurrent === cleanSaved);

            var opt = $('<option>', { 
                value: m.id, 
                text: m.name, 
                selected: isSel 
            });
            opt.attr('data-center', JSON.stringify([m.latitude, m.longitude]));
            opt.attr('data-zoom', m.zoom);
            $mapSel.append(opt);
        });
        
        try {
            $mapSel.selectpicker('refresh');
        } catch(e) { }
    }
}
