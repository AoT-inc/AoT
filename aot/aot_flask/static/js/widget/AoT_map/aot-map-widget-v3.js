/**
 * AoT Map Widget JavaScript (v3)
 * Externalized from AoT_map.py for better maintainability.
 */


;(function() {

    "use strict";


    // [Iteration 16] Emergency Master Shield Guard
    ;(function() {

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
                console.log("[AoT] Emergency Master Shield Activated (Widget)");
            }
        }
        applyShield();
        setTimeout(applyShield, 500);
    })();

    // --- DASHBOARD WIDGET LOGIC ---
    window.initAoTMapWidget = function(uniqueId) {
        let widgetId, mapId, contentMapUuid, refreshSeconds, devices, vars, theme, layers, geoConfig, isLocked, hideControls;
        let widgetMap = null;
        let deviceMarkers = {};
        window.AoTMapApp = window.AoTMapApp || {};
        // Isolate marker storage per widgetId/uniqueId
        window.AoTMapApp[uniqueId] = window.AoTMapApp[uniqueId] || {};
        window.AoTMapApp[uniqueId].deviceMarkers = deviceMarkers;
        // window.AoTMapApp.deviceMarkers = deviceMarkers; // [BUG] Removed global overwrite to prevent collision between multiple widgets

        let isResizing = false; // [Fix] Moved to top to prevent ReferenceError in early renderOverlays calls
        let deviceShapes = {}; 
        let shapeGroup = L.featureGroup(); // [Iteration 5] Persistent group for shapes
        
        // [Optimization] Use MarkerClusterGroup for devices if available
        // [Refactor] Moved to helper to allow toggling via options
        // [Optimization] Use MarkerClusterGroup for devices if available
        // [Refactor] Generic Factory for Cluster Layers (Device, Site, Zone)
        function createClusterLayer(type, enableClustering) {
            if (enableClustering && typeof L.markerClusterGroup === 'function') {
                return L.markerClusterGroup({
                    disableClusteringAtZoom: 20, 
                    chunkedLoading: false, 
                    // [Fix] Link Cluster Radius to Label Spacing
                    maxClusterRadius: (vars.label_spacing && parseInt(vars.label_spacing) > 0) ? parseInt(vars.label_spacing) : 120, 
                    spiderfyOnMaxZoom: true,
                    // [Fix] Site/Zone usually don't need spiderfy as much, but consistent behavior is good.
                    spiderfyDistanceMultiplier: 2, 
                    spiderLegPolylineOptions: { weight: 1.5, color: '#666', opacity: 0.5 },
                    zoomToBoundsOnClick: true,
                    removeOutsideVisibleBounds: false,
                    animate: true,
                    showCoverageOnHover: false,
                    
                    // [New] Custom Cluster Styling per Type
                    iconCreateFunction: function(cluster) {
                        const count = cluster.getChildCount();
                        
                        // Resolve Color: User -> Theme -> CSS Primary -> Fallback
                        let bgColor = vars.cluster_color;
                        if (!bgColor && theme && theme.primary) bgColor = theme.primary;
                        if (!bgColor) {
                            try {
                                const cssPrimary = getComputedStyle(document.documentElement).getPropertyValue('--primary').trim();
                                if (cssPrimary) bgColor = cssPrimary;
                            } catch(e) {}
                        }
                        if (!bgColor) bgColor = '#995aff'; 

                        // Shape & Z-Index Logic
                        let borderRadius = '50%'; // Device (Circle)
                        let zIdx = 0; // Default (Leaflet determines)

                        if (type === 'site_zone') {
                            borderRadius = '4px'; // Square
                            // Use Site Theme if available
                            if (theme && theme.site) bgColor = theme.site;
                        } else if (type === 'site') {
                            borderRadius = '4px'; 
                        } else if (type === 'zone') {
                            borderRadius = '8px'; 
                        }

                        // [UI] 28px Base Size
                        const style = `
                            background-color: ${bgColor}; 
                            width: 28px; 
                            height: 28px; 
                            border-radius: ${borderRadius}; 
                            border: 2px solid #ffffff;
                            display: flex; 
                            justify-content: center; 
                            align-items: center; 
                            color: #ffffff; 
                            font-weight: bold; 
                            font-family: 'Inter', sans-serif;
                            font-size: 11px; 
                            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
                        `;

                        return L.divIcon({
                            html: `<div style="${style}">${count}</div>`,
                            className: `aot-cluster-marker-${type}`, 
                            iconSize: L.point(28, 28),
                            iconAnchor: [14, 14] 
                        });
                    }
                });
            } else {
                if (enableClustering) console.warn("[AoT Map] L.markerClusterGroup not found. Clustering disabled.");
                return L.layerGroup();
            }
        }

        
        // [Req] Merged Site/Zone Layer
        let labelLayers = { siteZone: L.layerGroup(), device: L.layerGroup() };
        
        // [Stopwatch Refinement] Server Clock Offset logic from AoT_timer.py
        let tm_serverNowOffsetMs = 0;
        function tm_updateServerNowOffsetFromResponse(res) {
            try {
                const dateHdr = res.headers.get('date');
                if (!dateHdr) return;
                const srvMs = Date.parse(dateHdr);
                if (!isNaN(srvMs)) {
                    const off = srvMs - Date.now();
                    // Max ±120s drift allowed; otherwise ignore
                    if (Math.abs(off) <= 120000) {
                        tm_serverNowOffsetMs = off;
                    }
                }
            } catch (e) {}
        }
        function tm_nowServerMs() {
            return Date.now() + (Math.abs(tm_serverNowOffsetMs) <= 120000 ? tm_serverNowOffsetMs : 0);
        }

        // [Standardized Toast Notification]
        // 서버 설정(AoTGlobalSettings)에 따라 토스트 메시지 출력 여부를 결정합니다.
        // 임의로 수정하지 마십시오. (Requested by User)
        function showToast(msg, type = 'info') {
          // 1. 서버 전역 설정 체크
          if (window.AoTGlobalSettings) {
              if (type === 'success' && window.AoTGlobalSettings.hide_success) return;
              if (type === 'info' && window.AoTGlobalSettings.hide_info) return;
              if (type === 'warning' && window.AoTGlobalSettings.hide_warning) return;
          }
          // 2. Toastr 라이브러리 호출
          if (typeof toastr !== 'undefined') {
            toastr[type](msg);
          } else {
            console.log(`[AoT Map] ${type}: ${msg}`);
          }
        }

        window.AoTMapApp = window.AoTMapApp || {};
        window.AoTMapApp.showToast = showToast;

        // [Restored Helper] getUnifiedDeviceColor
        // Defines color priority: Device Label Color > User Option > Theme > Default
        // [Fix] Added 'vars' argument to ensure access even if scope is tricky
        function getUnifiedDeviceColor(type, dev, vars) {
            const trace = { type, devId: dev?.unique_id, labelColor: dev?.label_color, varColor: vars?.device_shape_color };
            
            // [Fix] Priority 1: Widget Theme (Specific Type or Generic aot_device)
            const activeTheme = (vars && vars.theme) ? vars.theme : (typeof theme !== 'undefined' ? theme : null);
            if (activeTheme) {
                 // Try specific type first (input, output, function)
                 if (activeTheme[`${type}-color`]) return activeTheme[`${type}-color`];
                 if (activeTheme[type]) return activeTheme[type];
                 // Try generic aot_device
                 if (activeTheme['aot_device-color']) return activeTheme['aot_device-color'];
                 if (activeTheme['aot_device']) return activeTheme['aot_device'];
                 // Default device key
                 if (activeTheme.device) return activeTheme.device;
            }

            // [Fix] Priority 2: Device-Specific override (Manual Label Color)
            if (dev && dev.label_color) {
                return dev.label_color;
            }

            // [Fix] Priority 3: Backend Dynamic Status Color (Blue/Gray etc)
            const backendColor = (dev && (dev.color || dev.marker_color)) ? (dev.color || dev.marker_color) : null;
            if (backendColor && backendColor.trim()) {
                return backendColor;
            }
            
            // Priority 4: Widget Variable Color
            if (vars && vars.device_shape_color) {
                return vars.device_shape_color;
            }
            
            // [Fix] Fallback to Theme Default before hardcoding
            if (activeTheme && activeTheme.device) return activeTheme.device;

            return '#3388ff';
        }

        /**
         * [New] Unified ID Matcher (Round 18)
         * Matches uuid::0 to uuid AND uuid to uuid::0 bidirectionally.
         */
        function findLiveDevice(searchId, liveDevices) {
            if (!searchId || !liveDevices) return null;
            const sId = String(searchId);
            const baseId = sId.split('::')[0];
            const is0 = sId.endsWith('::0') || !sId.includes('::');

            const matches = liveDevices.filter(d => {
                const dId = String(d.id || d.unique_id || "");
                const dBase = dId.split('::')[0];
                const dIs0 = dId.endsWith('::0') || !dId.includes('::');

                if (dId === sId) return true;
                if (dBase === baseId && is0 && dIs0) return true;
                return false;
            });

            if (matches.length === 0) return null;
            
            // [Fix] Prioritize activated ones (Round 19)
            // If multiple roles (Input/Output) match, we MUST return one that is 'activated'
            // so that shapes (renderOverlays) and markers (renderDevices fallback) use the visible role.
            const activated = matches.find(d => d.is_activated !== false && d.is_activated !== 'false');
            return activated || matches[0];
        }

        // [Helper] Hex to RGBA (Required for Shadow Logic)
        window.AoTMapApp.hexToRgba = function(hex, alpha) {
            // If hex is null, use primary theme color or default
            if (!hex) hex = '#3388ff'; 
            hex = hex.replace('#', '');
            if (hex.length === 3) hex = hex.split('').map(c => c+c).join('');
            const r = parseInt(hex.substring(0,2), 16);
            const g = parseInt(hex.substring(2,4), 16);
            const b = parseInt(hex.substring(4,6), 16);
            return `rgba(${r}, ${g}, ${b}, ${alpha})`;
        };

        // [Fix] Inject stability CSS to prevent label jumping
        if (!document.getElementById('aot-map-stability-style')) {
            const style = document.createElement('style');
            style.id = 'aot-map-stability-style';
            style.textContent = `
                .aot-map-loading-labels .aot-map-label,
                .aot-map-loading-labels .leaflet-marker-icon:not(.aot-device-icon),
                .aot-map-loading-labels .leaflet-marker-shadow {
                    display: none !important;
                }
            `;
            document.head.appendChild(style);
        }

        function initWidget() {
            if (!window.L || !window.AoTMapLoader || !window.AoTMapData || !window.AoTMapControls) {
                setTimeout(initWidget, 100);
                return;
            }

            let widgetData;
            try {
                const dataEl = document.getElementById('aot-map-vars-' + uniqueId);
                if (!dataEl) return;
                widgetData = JSON.parse(dataEl.textContent);
            } catch (e) {
                console.error("Failed to parse widget data", e);
                return;
            }
            if (!widgetData) return;

            console.log("[AoT Map Debug] Initializing Widget with data:", widgetData);

            ({ widgetId, mapId, contentMapUuid, refreshSeconds, devices, vars, theme, layers, geoConfig, isLocked, hideControls } = widgetData);

            console.log("[AoT Map Debug] Extracted - theme:", theme, "geoConfig:", geoConfig);
            
            // [Fix] vars.all_measurements_map is now provided by Backend (maps.py)
            
            if (geoConfig) {
                window.AOT_GEO_CONFIG = geoConfig;
            }

            // [Fix] Initialize Device Layer based on Collision Option
            // Note: Default is true in backend.
            const enableClustering = (vars.enable_label_collision !== false);
            
            // [Req] Full Clustering for Site/Zone (Merged Group)
            labelLayers.device = createClusterLayer('device', enableClustering);
            labelLayers.siteZone = createClusterLayer('site_zone', enableClustering);

            // [Fix] Ensure theme is populated from geoConfig if not provided directly
            theme = theme || {};
            if (geoConfig && geoConfig.theme_config) {
                theme = Object.assign({}, geoConfig.theme_config, theme);
            }
            
            if (typeof layers === 'string') {
                layers = layers.split(',').map(s => s.trim()).filter(s => s);
            } else if (!Array.isArray(layers)) {
                layers = [];
            }
            
            const canvasId = mapId + '-canvas';

            function applyTheme(config) {
                if (!config || !config.theme_config) return;
                const tConfig = config.theme_config; // [Fix] Renamed to avoid shadowing outer 'theme'
                const root = document.getElementById(mapId) || document.documentElement;

                function hexToRgb(hex) {
                    hex = hex.replace('#', '');
                    if (hex.length === 3) hex = hex.split('').map(c => c+c).join('');
                    const r = parseInt(hex.substring(0,2), 16);
                    const g = parseInt(hex.substring(2,4), 16);
                    const b = parseInt(hex.substring(4,6), 16);
                    return `${r}, ${g}, ${b}`;
                }

                if (tConfig.panel_bg) {
                    const hex = tConfig.panel_bg;
                    const rgb = hexToRgb(hex); 
                    let opacity = 0.9; 
                    if (tConfig.panel_opacity) opacity = parseInt(tConfig.panel_opacity) / 100;
                    
                    root.style.setProperty('--panel-bg-rgba', `rgba(${rgb}, ${opacity})`);
                    root.style.setProperty('--panel-bg', hex);
                    root.style.setProperty('--panel-opacity', opacity);

                    const rgbArr = rgb.split(',').map(Number);
                    const luma = 0.2126 * rgbArr[0] + 0.7152 * rgbArr[1] + 0.0722 * rgbArr[2];
                    if (luma < 128) {
                        root.style.setProperty('--panel-text', '#ffffff');
                        root.style.setProperty('--panel-border', 'rgba(255,255,255,0.2)');
                    } else {
                        root.style.setProperty('--panel-text', '#333333');
                        root.style.setProperty('--panel-border', '#f0f0f0');
                    }
                }
            }
            
            if (geoConfig) applyTheme(geoConfig);

            const initResult = window.AoTMapLoader.initMap(canvasId, 'general_map', {
                zoomControl: false, 
                hideUi: vars.hide_ui,
                overlayDataOnly: vars.overlay_data_only,
                layers: layers,
                preferCanvas: true // [GeoDesign Match] Use Canvas for rendering performance and stability
            });
            widgetMap = initResult.map;
            
            if (window.AoTMapAlignment) {
                // [Fix] Pass label_spacing for collision margin configuration
                const margin = vars.label_spacing ? parseInt(vars.label_spacing) : 2;
                window.AoTMapAlignment.init(uniqueId, widgetMap, { 
                    enabled: vars.enable_label_collision,
                    padding: margin 
                });
            }
            
            const baseLayers = initResult.baseLayers;
            const overlayLayers = initResult.overlays;
            const layerControl = initResult.layerControl;

            const initialCenter = vars.fallback_center || vars.map_default_center;
            const initialZoom = vars.map_default_zoom || 15;

            console.log(`[AoT Map Debug] Init View. fallback_center: ${JSON.stringify(vars.fallback_center)}, initialCenter: ${JSON.stringify(initialCenter)}, initialZoom: ${initialZoom}`);

            if (initialCenter && Array.isArray(initialCenter) && initialCenter.length === 2 && 
                Number.isFinite(parseFloat(initialCenter[0])) && Number.isFinite(parseFloat(initialCenter[1]))) {
                widgetMap.setView(initialCenter, initialZoom);
            }

            // [Iteration 16] Hybrid Localization Check
            // Prioritize server preference, then last LOCAL choice in this browser
            let activeBaseName = vars.selected_base_layer;
            const localBase = localStorage.getItem('aot_map_last_basemap');
            
            if (!activeBaseName && localBase && baseLayers[localBase]) {
                activeBaseName = localBase;
                widgetMap.addLayer(baseLayers[localBase]);
            }

            if (!widgetMap) return;

            if (window.AoTMapControls) {
                // Initialize Search Controller
                if (window.AoTMapSearchController) {
                    widgetMap.searchController = new window.AoTMapSearchController(widgetMap, {
                        searchId: 'search-comp-' + uniqueId,
                        toggleBtnId: null, // Button managed via callbacks.onSearch
                        overlayId: 'search-overlay-' + uniqueId
                    });
                }

                const callbacks = {
                    onSearch: () => {
                        if (widgetMap.searchController) {
                            widgetMap.searchController.toggle();
                        } else {
                            const el = document.getElementById('search-overlay-' + uniqueId);
                            if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
                        }
                    },
                    onReset: () => {
                        if (vars.map_default_center) widgetMap.flyTo(vars.map_default_center, vars.map_default_zoom || 15);
                    },
                    onLockChange: (locked) => {
                        isLocked = locked;
                        saveMapState(true);
                    },
                    onHideChange: (hidden) => {
                        hideControls = hidden;
                        saveMapState(true);
                    }
                };
                
                const stateOpts = { isLocked: isLocked, isHidden: hideControls };
                
                widgetMap.addControl(new window.AoTMapControls.ZoomControl());
                widgetMap.addControl(new window.AoTMapControls.ToolsControl(callbacks));
                
                if (window.L.control.siteList) {
                    const sites = vars.sites_in_map || [];
                    widgetMap.siteListControl = window.L.control.siteList({ sites: sites });
                    widgetMap.addControl(widgetMap.siteListControl);
                }
                if (window.L.control.measure) widgetMap.addControl(window.L.control.measure());
                if (window.L.control.memo) widgetMap.addControl(window.L.control.memo());
                
                const stateControl = new window.AoTMapControls.StateControl(Object.assign({}, stateOpts, {
                    onLockChange: callbacks.onLockChange,
                    onHideChange: callbacks.onHideChange
                }));
                widgetMap.addControl(stateControl);

                const panelMeasurements = [];
                const rawMeasMap = vars.measurements_map || {};
                Object.keys(rawMeasMap).forEach(devId => {
                    const measList = rawMeasMap[devId];
                    if (Array.isArray(measList)) {
                        measList.forEach(m => {
                            // [New] Lookup Device Name for Panel Display
                            let devName = null;
                            const devObj = (devices || []).find(d => d.device_unique_id === devId);
                            if (devObj) devName = devObj.device_name || devObj.name;

                            panelMeasurements.push({
                                id: m.id || `${devId}_0`, 
                                device_unique_id: m.device_unique_id || devId,
                                device_type: m.device_type,
                                devId: devId,
                                device_name: m.device_name || devName, // Prefer backend provided name
                                name: m.name || m.device_name || devName || m.label || "Measurement", 
                                unit: m.unit || "",
                                value: m.last_value || "-"
                            });
                        });
                    }

                });
                

                
                panelMeasurements.sort((a, b) => {
                    const nameA = a.device_name || a.name || "";
                    const nameB = b.device_name || b.name || "";
                    return nameA.localeCompare(nameB, undefined, { numeric: true, sensitivity: 'base' });
                });

                if (panelMeasurements.length > 0) {
                     widgetMap.measurementPanel = window.L.control.measurementPanel({
                         measurements: panelMeasurements,
                         updateInterval: vars.input_update_interval || 300,
                         maxAge: vars.max_measure_age || 300
                     });
                     widgetMap.measurementPanel.addTo(widgetMap);

                }



                if (layerControl) {
                    window.AoTMapControls.styleLayerControl(layerControl.getContainer());
                }
            }

            // [Fix] Expose Map Instance and Layers for Live Options Sync
            if (window.AoTMapApp && window.AoTMapApp[uniqueId]) {
                window.AoTMapApp[uniqueId].map = widgetMap;
                window.AoTMapApp[uniqueId].baseLayers = baseLayers;
                window.AoTMapApp[uniqueId].overlayLayers = overlayLayers;
                window.AoTMapApp[uniqueId].overlayFeatures = []; // Store features for lookup
                
                // [Expose] State for Update Functions
                window.AoTMapApp[uniqueId].vars = vars;
                window.AoTMapApp[uniqueId].devices = devices;

                // [Feature] Update Label Name (Renaming from Popup)
                window.AoTMapApp[uniqueId].updateLabelName = function(targetId, targetType, newName) {
                    const features = window.AoTMapApp[uniqueId].overlayFeatures || [];
                    const feature = features.find(f => {
                         const p = f.properties || {};
                         return String(p.db_id) === String(targetId) || String(p.node_id) === String(targetId) || String(p.unique_id) === String(targetId);
                    });

                    if (!feature) {
                        alert("Error: Feature not found in memory.");
                        return;
                    }

                    // Update local property
                    if (!feature.properties) feature.properties = {};
                    feature.properties.label_name = newName;
                    feature.properties.name = newName; // Dual update for consistency

                    // Check if AoTMapData is available
                    if (window.AoTMapData && window.AoTMapData.saveDelta && contentMapUuid) {
                        window.AoTMapData.saveDelta(contentMapUuid, { upserts: [feature] })
                            .then(res => {
                                if (res && (res.status === 'success' || res.ok)) {
                                    window.AoTMapApp.showToast("Label updated successfully", 'success');
                                    // Refresh map to show new label (lazy way: reload widget or re-render)
                                    // ideally re-render overlays.
                                    // For now, reload window or trigger refresh if possible.
                                    // Re-triggering overlay fetch:
                                    // We can just call renderOverlays if we have the list, but we updated the local object.
                                    // To fully refresh, we might need to fetch again.
                                    // Let's try to update the Marker UI directly if possible? 
                                    // Too complex to find specific marker. 
                                    // Let's rely on standard "refresh" or just let the user know.
                                    // Actually, we can trigger the widget init again?
                                    // Better: simply reload page for now or let the periodic refresh handle it?
                                    // The widget refreshes devices, not overlays usually.
                                    // Let's re-fetch overlays.
                                    
                                     if (contentMapUuid) {
                                        fetch(`/api/geo/overlays?map_uuid=${contentMapUuid}`)
                                            .then(r => r.json())
                                            .then(d => {
                                                if (d.features) renderOverlays(d.features, vars);
                                            });
                                     }

                                } else {
                                    alert("Update failed: " + (res.message || "Unknown error"));
                                }
                            })
                            .catch(err => {
                                console.error(err);
                                alert("Update failed. Check console.");
                            });
                    } else {
                        console.warn("[AoT Map] Save capability missing (AoTMapData or contentMapUuid).");
                        // Just update UI locally if backend save impossible
                        renderOverlays(features, vars); 
                    }
                };
            }
            
            // [Fix] Add Merged Layer
            labelLayers.siteZone.addTo(widgetMap);
            labelLayers.device.addTo(widgetMap);
            shapeGroup.addTo(widgetMap); // Add persistent shape group immediately

            if (window.AoTMapAlignment) {
                // [Priority Update] Device (1) > Site/Zone (3)
                // [Fix] Pass 'enableClustering' (isCluster) flag to Site/Zone to prevent Collision Hiding
                window.AoTMapAlignment.registerGroup(uniqueId, 'device', labelLayers.device, 1, enableClustering);
                window.AoTMapAlignment.registerGroup(uniqueId, 'site_zone', labelLayers.siteZone, 3, enableClustering);
            }

            if (contentMapUuid) {
                fetch(`/api/geo/overlays?map_uuid=${contentMapUuid}`)
                    .then(res => res.json())
                    .then(data => {
                        if (data.features) {
                            // [Iteration 19] Client-side Site List Population (Optimization)
                            // Filter only "site" shapes as requested by user.
                            const sites = [];
                            data.features.forEach(f => {
                                const p = f.properties || {};
                                const t = (p.aot_type || "").toLowerCase();
                                if (t === 'site') {
                                    // Calculate center
                                    let lat = null, lng = null;
                                    if (p.center_lat && p.center_lng) {
                                        lat = parseFloat(p.center_lat); lng = parseFloat(p.center_lng);
                                    } else if (f.geometry) {
                                        const layer = L.GeoJSON.geometryToLayer(f);
                                        if (layer.getBounds) {
                                            const center = layer.getBounds().getCenter();
                                            lat = center.lat; lng = center.lng;
                                        } else if (layer.getLatLng) {
                                            const latlng = layer.getLatLng();
                                            lat = latlng.lat; lng = latlng.lng;
                                        }
                                    }
                                    
                                    if (lat !== null && lng !== null) {
                                        sites.push({
                                            name: p.label_name || p.name || `Site ${p.db_id}`,
                                            lat: lat,
                                            lng: lng,
                                            zoom: 17
                                        });
                                    }
                                }
                            });
                            
                            // Rehydrate the Site List Control if we found sites
                            if (sites.length > 0 && window.L.control.siteList) {
                                // If a control already exists (added with empty list), remove it
                                // We didn't save the reference earlier, so we need to find it or remove known one.
                                // NOTE: The earlier code `widgetMap.addControl(window.L.control.siteList({ sites: sites }));` 
                                // adds it to the map but doesn't expose a global reference easily.
                                // However, Leaflet controls are in widgetMap._controlCorners or similar.
                                // Better strategy: Since we just added it empty in init, let's remove it if we can find it.
                                // Actually, `siteList` usually adds a class.
                                
                                // Safest: If we saved it to `widgetMap.siteListControl` (we didn't yet), we could remove.
                                // Since we didn't refactor the init code yet to save it:
                                // Let's try to update it if the control supports it, OR we modify init logic?
                                // Let's MODIFY the init logic below to save the reference, then we can use it here.
                                
                                if (widgetMap.siteListControl) {
                                    widgetMap.removeControl(widgetMap.siteListControl);
                                }
                                widgetMap.siteListControl = window.L.control.siteList({ sites: sites });
                                widgetMap.addControl(widgetMap.siteListControl);
                            }

                            // Store features globally for update logic
                            if (window.AoTMapApp[uniqueId]) {
                                window.AoTMapApp[uniqueId].overlayFeatures = data.features;
                            }
                            renderOverlays(data.features, vars);
                            
                            // Note: renderOverlays now internally triggers renderDevices to ensure sync (Shimmy Fix in renderOverlays).
                            // Duplicate call removed to prevent race conditions/flickering.
                        }
                    }).catch(err => console.error("Overlay load error:", err));
            }

            renderDevices(devices, vars);

            // [Map Notes] Fetch and Render Logic
            function renderMapNotes() {
                return fetch('/notes/geo')
                    .then(res => res.json())
                    .then(notes => {
                        if (!Array.isArray(notes)) return;
                        
                        // Create layer group if not exists
                        if (!labelLayers.notes) {
                            labelLayers.notes = L.layerGroup().addTo(widgetMap);
                        } else {
                            labelLayers.notes.clearLayers();
                        }
                        
                        notes.forEach(note => {
                            if (note.gps_lat && note.gps_lng) {
                                const lat = parseFloat(note.gps_lat);
                                const lng = parseFloat(note.gps_lng);
                                if (isNaN(lat) || isNaN(lng)) return;

                                const icon = L.divIcon({
                                    className: 'map-note-icon',
                                    html: `<div style="background:var(--gray-dark); border:2px solid var(--white); border-radius:50%; width:24px; height:24px; display:flex; justify-content:center; align-items:center; box-shadow:0 2px 5px rgba(0,0,0,0.3); color:var(--white); transform: translate(-50%, -50%);"><i class="fas fa-map-pin" style="font-size:12px;"></i></div>`,
                                    iconSize: [0, 0], // Use 0,0 and CSS translate for centering to avoid offset issues
                                    iconAnchor: [0, 0]
                                });
                                
                                const marker = L.marker([lat, lng], {icon: icon});
                // [New] Update Map Note Name API Call
                window.AoTMapApp[uniqueId].updateMapNoteName = function(noteId, newName) {
                    fetch(`/notes/update/${noteId}`, {
                        method: 'POST',
                        headers: { 
                            'Content-Type': 'application/json',
                            'X-CSRFToken': window.AoTMapData ? window.AoTMapData.getCsrfToken() : ''
                        },
                        body: JSON.stringify({ name: newName })
                    })
                    .then(r => r.json())
                    .then(d => {
                        if (d.error) alert("Error: " + d.error);
                        else {
                            // window.AoTMapApp.showToast("Note updated", 'success');
                            // Refresh notes
                             if (window.AoTMapApp[uniqueId].renderMapNotes) window.AoTMapApp[uniqueId].renderMapNotes();
                        }
                    })
                    .catch(e => alert("Update failed: " + e));
                };

                // [Modified] Use Popup for Map Notes (Consistent with Labels)
                // Use note.unique_id for RENAMING (Specific Note)
                // Use note.target_id for OPENING THREAD (Location)
                const noteId = note.unique_id; 
                const tId = note.target_id || note.unique_id;
                
                // Note: API returns 'user' as the name/title field (legacy mapping)
                const currentName = note.user || 'Map Note'; 
                const safeName = (currentName).replace(/'/g, "\\'");
                
                const openNoteAction = `window.dispatchEvent(new CustomEvent('open-notes', { detail: { targetId: '${tId}', targetType: 'map_location', name: '${safeName}' } }))`;
                
                // [Modified] Remove Note from Map (Hide) API
                window.AoTMapApp[uniqueId].deleteMapNote = function(noteId) {
                    if(!confirm(_('confirm_remove_pin'))) return;
                    
                    fetch('/notes/toggle_map_visibility', {
                        method: 'POST',
                        headers: { 
                            'Content-Type': 'application/json',
                            'X-CSRFToken': window.AoTMapData ? window.AoTMapData.getCsrfToken() : ''
                        },
                        body: JSON.stringify({ unique_id: noteId, visible: false })
                    })
                    .then(r => r.json())
                    .then(d => {
                        if (d.error) alert("Error: " + d.error);
                        else {
                            if (window.AoTMapApp[uniqueId].renderMapNotes) window.AoTMapApp[uniqueId].renderMapNotes();
                        }
                    })
                    .catch(e => alert("Remove failed: " + e));
                };

                // [New] Toggle Edit Mode
                window.AoTMapApp[uniqueId].toggleNoteEditMode = function(noteId) {
                    const v = document.getElementById(`note-row2-view-${noteId}`);
                    const e = document.getElementById(`note-row2-edit-${noteId}`);
                    if (v && e) {
                        if (v.style.display === 'none') {
                           v.style.display = 'block';
                           e.style.display = 'none';
                        } else {
                           v.style.display = 'none';
                           e.style.display = 'block';
                        }
                    }
                };

                // Enable Input
                const renameAction = `window.AoTMapApp['${uniqueId}'].updateMapNoteName('${noteId}', document.getElementById('rename-input-${noteId}').value)`;
                
                const deleteAction = `window.AoTMapApp['${uniqueId}'].deleteMapNote('${noteId}')`;
                const toggleAction = `window.AoTMapApp['${uniqueId}'].toggleNoteEditMode('${noteId}')`;

                marker.bindPopup(() => {
                     // Fetch Last Note Title (Async) - purely for preview
                     setTimeout(() => {
                         fetch(`/notes/target/${tId}`)
                            .then(r => r.json())
                            .then(notes => {
                                const el = document.getElementById(`last-note-title-${noteId}`); // Use noteId for unique DOM ID
                                if (el) {
                                    if (notes && notes.length > 0) {
                                        el.innerText = notes[0].note.substring(0, 30) + (notes[0].note.length > 30 ? '...' : '');
                                        el.style.color = '#555';
                                    } else {
                                        el.innerText = _('no_notes');
                                        el.style.color = '#ccc';
                                    }
                                }
                            })
                            .catch(() => {});
                     }, 100);

                     return `
                        <div style="min-width: 180px; padding: 5px;">
                            <!-- Row 1: Name + Edit Button -->
                            <div class="aot-popup-title" style="font-size: 1.4em; font-weight: bold; margin: 0; line-height: 1.2; word-break: break-all; text-align: left; padding-top: 15px; margin-bottom: 8px; color: #333; display: flex; justify-content: space-between; align-items: start;">
                                <span>${safeName}</span>
                                <button class="btn btn-sm btn-link" onclick="${toggleAction}" style="padding: 0; font-size: 0.6em; color: #999; text-decoration: none;">${_('edit')}</button>
                            </div>
                            
                            <hr style="margin: 8px 0; border-top: 1px solid #eee;">
                            
                            <!-- Row 2 View: Create Link + Status -->
                            <div id="note-row2-view-${noteId}" style="display: flex; flex-direction: column; gap: 6px;">
                                <button class="btn btn-primary" style="border-radius: 14px; height: 28px; width: 100%; font-size: 0.9em; display: flex; align-items: center; justify-content: center; padding: 0;"
                                    onclick="${openNoteAction}">
                                    <i class="fas fa-clipboard mr-2"></i> ${window._('Open Notes')}
                                </button>
                                <div id="last-note-title-${noteId}" style="font-size: 0.85em; color: #888; padding-left: 4px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;">
                                    ${window._('Loading')}
                                </div>
                            </div>
                            
                            <!-- Row 2 Edit: Rename Input + Save + Delete -->
                            <div id="note-row2-edit-${noteId}" style="display: none;">
                                <div style="display: flex; gap: 6px; margin-bottom: 8px; align-items: stretch;">
                                    <input type="text" id="rename-input-${noteId}" value="${safeName}" class="form-control" style="flex:1; padding: 2px 6px; font-size: 0.95em;">
                                    <button class="btn btn-sm btn-primary" style="padding: 2px 8px; white-space: nowrap;" onclick="${renameAction}">${window._('Save')}</button>
                                </div>
                                <button class="btn btn-danger btn-block btn-sm" onclick="${deleteAction}">${window._('Remove from Map')}</button>
                            </div>
                        </div>
                     `;
                }, {
                    className: 'aot-map-popup',
                    minWidth: 160,
                    maxWidth: 200
                });
                marker.addTo(labelLayers.notes);
                            }
                        });
                    }).catch(e => {
                        console.error("[AoT Map] renderMapNotes error:", e);
                    });
            }
            // Poll for updates every 30s
            let notePollTimer = null;
            function pollMapNotes() {
                renderMapNotes().finally(() => {
                    notePollTimer = setTimeout(pollMapNotes, 30000);
                });
            }

            pollMapNotes();

            // [Fix] Expose renderMapNotes for external triggers (Note Creation)
            if (window.AoTMapApp[uniqueId]) {
                window.AoTMapApp[uniqueId].renderMapNotes = renderMapNotes;
            }
            
            // [Fix] Listen for global Note Save event (if any) or generic refresh trigger
            window.addEventListener('aot-refresh-map-notes', renderMapNotes);

            // [Optimization] Async Fetch
            if (vars.async_devices) {
                console.log("[AoT Map] Fetching devices asynchronously...");
                // [Fix] Pass Map UUID *AND* Device IDs *AND* include_all for Filtering
                let filteredUrl = contentMapUuid 
                    ? `/api/geo/devices?map_uuid=${contentMapUuid}` 
                    : '/api/geo/devices';
                
                const separator = filteredUrl.includes('?') ? '&' : '?';
                const params = [];
                // [Fix] map_device_ids contains union of manual + measurement devices
                const fetchIds = vars.map_device_ids || vars.device_ids;
                if (fetchIds) {
                    params.push(`device_ids=${encodeURIComponent(fetchIds)}`);
                }
                if (vars.include_all_devices !== undefined) {
                    params.push(`include_all=${vars.include_all_devices}`);
                }
                
                if (params.length > 0) {
                    filteredUrl += (filteredUrl.includes('?') ? '&' : '?') + params.join('&');
                }

                console.log("[AoT Map] Async Fetch URL:", filteredUrl);

                fetch(filteredUrl)
                    .then(res => res.json())
                    .then(data => {
                        if (data.ok && data.devices) {
                            console.log(`[AoT Map] Async load complete. Rerendering ${data.devices.length} devices.`);
                            devices = data.devices;
                            
                            // [Fix] Merge new measurements map from API for Popups
                            if (data.all_measurements_map) {
                                vars.all_measurements_map = data.all_measurements_map;
                                // Fallback for backward compatibility
                                if (!vars.measurements_map) vars.measurements_map = data.all_measurements_map;
                            }

                             renderDevices(devices, vars);
                            
                            // [Fix] Re-render Overlays after Async Load (Round 19)
                            // Overlays rely on the updated 'devices' list for activation checks (findLiveDevice).
                            if (window.AoTMapApp[uniqueId].overlayFeatures) {
                                renderOverlays(window.AoTMapApp[uniqueId].overlayFeatures, vars);
                            }
                            
                            // Re-trigger status polling with new device list
                            if (pollOutputTimer) clearTimeout(pollOutputTimer);
                            if (pollInputTimer) clearTimeout(pollInputTimer);
                            pollOutputStatus();
                            pollInputStatus();
                        }
                    })
                    .catch(err => console.error("[AoT Map] Async fetch failed", err));
            }

            let debounceTimer = null;
            const debouncedResize = () => {
                if (debounceTimer) clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    if (widgetMap) {
                        isResizing = true; // Set flag before invalidateSize
                        widgetMap.invalidateSize();
                        // [Fix] Force projection update for SVG layers to prevent distortion
                        if (widgetMap._onMoveEnd) widgetMap._onMoveEnd();
                        // Trigger renderOverlays to ensure everything is synced to new size
                        if (typeof renderOverlays === 'function' && window.AoTMapApp[uniqueId].overlayFeatures) {
                            renderOverlays(window.AoTMapApp[uniqueId].overlayFeatures, vars);
                        }
                        if (window.AoTMapAlignment) window.AoTMapAlignment.updateAlignment();
                        console.log(`[AoT Map ${uniqueId}] Reflow completed (debounced)`);
                        // Reset flag after moveend has been processed
                        setTimeout(() => { isResizing = false; }, 100);
                    }
                }, 350); // CSS Transition is 0.3s, so 350ms is safe
            };

            const resizeObserver = new ResizeObserver(() => {
                debouncedResize();
            });
            const mEl = document.getElementById(mapId);
            if (mEl) resizeObserver.observe(mEl);

            // [New] Expose reflow for manual dashboard triggers
            window.AoTMapApp[uniqueId].reflow = debouncedResize;

            // [New] Register to global window.widget for dashboard.js compatibility
            window.widget = window.widget || {};
            window.widget[widgetId] = window.AoTMapApp[uniqueId];

            let pollOutputTimer = null;
            let pollInputTimer = null;

            function pollOutputStatus() {
                const outputs = devices.filter(d => d.type === 'output');
                if (outputs.length > 0) {
                    if (window.AoTMapLoader && window.AoTMapLoader.updateDurations) {
                        window.AoTMapLoader.updateDurations(deviceMarkers);
                    }
                    if (window.AoTMapAlignment) window.AoTMapAlignment.updateAlignment();
                    
                    const promises = outputs.map(dev => updateMarkerStatus(dev.id));
                    Promise.all(promises).finally(() => {
                        pollOutputTimer = setTimeout(pollOutputStatus, refreshSeconds * 1000);
                    });
                } else {
                    pollOutputTimer = setTimeout(pollOutputStatus, refreshSeconds * 1000);
                }
            }

            function pollInputStatus() {
                const inputs = devices.filter(d => d.type === 'input' || d.type === 'function');
                if (inputs.length > 0) {
                    const promises = inputs.map(dev => updateMarkerStatus(dev.id));
                    Promise.all(promises).finally(() => {
                        pollInputTimer = setTimeout(pollInputStatus, (vars.input_update_interval || 300) * 1000);
                    });
                } else {
                    pollInputTimer = setTimeout(pollInputStatus, (vars.input_update_interval || 300) * 1000);
                }
            }
            
            pollOutputStatus();
            pollInputStatus();

            let lastSavedState = {};
            let saveTimeout = null;
            let isInitiallyLoaded = false;
            setTimeout(() => { isInitiallyLoaded = true; }, 2000); // 2s Grace period for SAVING ONLY
            (function initLastState() {
                const defCent = vars.fallback_center || vars.map_default_center || [0,0];
                
                // [Iteration 15] Strictly separate Base and Overlay names for initialization
                // This must match the logic in saveMapState to prevent redundant saves on load.
                const activeOverlayNames = (layers || [])
                    .filter(l => (l.is_base !== true && l.role !== 'base') && (l.visible || l.is_active))
                    .map(l => l.name)
                    .sort();

                let activeBaseName = vars.selected_base_layer || null;
                if (!activeBaseName) {
                    // Fallback to the first visible base layer if selected_base_layer isn't set
                    const visibleBase = (layers || []).find(l => (l.is_base === true || l.role === 'base') && (l.visible || l.is_active));
                    if (visibleBase) activeBaseName = visibleBase.name;
                }

                lastSavedState = {
                    fallback_latitude: parseFloat(defCent[0] || 0).toFixed(6),
                    fallback_longitude: parseFloat(defCent[1] || 0).toFixed(6),
                    default_zoom: Number(vars.map_default_zoom || 15),
                    active_layers: activeOverlayNames.join(','),
                    selected_base_layer: activeBaseName,
                    map_locked: !!isLocked,
                    hide_controls: !!hideControls
                };
            })();

            function saveMapState(immediate = false) {
                if (!isInitiallyLoaded && !immediate) return; // Prevent "Seoul Reversion" due to early auto-save
                if (saveTimeout) clearTimeout(saveTimeout);
                const center = widgetMap.getCenter();
                const zoom = widgetMap.getZoom();
                const activeOverlays = [];
                Object.entries(overlayLayers).forEach(([name, layer]) => {
                    if (widgetMap.hasLayer(layer)) activeOverlays.push(name);
                });
                
                let activeBase = null;
                Object.entries(baseLayers).forEach(([name, layer]) => {
                    if (widgetMap.hasLayer(layer)) activeBase = name;
                });

                const currentState = {
                    fallback_latitude: center.lat.toFixed(6),
                    fallback_longitude: center.lng.toFixed(6),
                    default_zoom: zoom,
                    active_layers: activeOverlays.sort().join(','),
                    selected_base_layer: activeBase,
                    map_locked: !!isLocked,
                    hide_controls: !!hideControls
                };


                const runSave = () => {
                    const changedOptions = {};
                    let hasChanged = false;

                    for (const key in currentState) {
                        // [Fix] Reduce tolerance to 0.000001 (~0.1m) to capture precise moves.
                        if (key === 'fallback_latitude' || key === 'fallback_longitude') {
                            const oldVal = parseFloat(lastSavedState[key]);
                            const newVal = parseFloat(currentState[key]);
                            if (Math.abs(newVal - oldVal) < 0.000001) continue;
                        }
                        
                        if (currentState[key] !== lastSavedState[key]) {
                            if (key === 'active_layers') changedOptions[key] = activeOverlays;
                            else changedOptions[key] = currentState[key];
                            hasChanged = true;
                        }
                    }

                    const syncToDOM = () => {
                        document.querySelectorAll(`[id$="_default_zoom"]`).forEach(el => { if(el.id.includes(uniqueId)) el.value = currentState.default_zoom; });
                        document.querySelectorAll(`[id$="_fallback_latitude"]`).forEach(el => { if(el.id.includes(uniqueId)) el.value = currentState.fallback_latitude; });
                        document.querySelectorAll(`[id$="_fallback_longitude"]`).forEach(el => { if(el.id.includes(uniqueId)) el.value = currentState.fallback_longitude; });
                    };

                    if (!hasChanged) {
                        // console.log("[AoT Map] No state change detected, skipping save");
                        syncToDOM();
                        return;
                    }
                    console.log("[AoT Map] State change detected:", changedOptions);
                    syncToDOM();

                    fetch('/save_widget_custom_options', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ widget_id: widgetId, options: changedOptions })
                        }).then(res => res.json())
                          .then(data => {
                              if (data.status === 'success') {
                                  lastSavedState = Object.assign({}, currentState);
                              }
                          }).catch(err => console.error("[AoTMap] Persistence Error", err));
                };

                // [Fix] Debounce delay optimized to 200ms for responsiveness (v4)
                if (immediate) runSave();
                else saveTimeout = setTimeout(runSave, 200); 
            }
            widgetMap.on('moveend zoomend baselayerchange overlayadd overlayremove', (e) => {
                if (isResizing && (e.type === 'moveend' || e.type === 'zoomend')) {
                    console.log("[AoT Map] Skipping save - triggered by window resize");
                    return;
                }
                
                if (e.type === 'baselayerchange') {
                    console.log("[AoT Map] Base layer switched to:", e.name);
                    // [Iteration 16] Hybrid Persistence: Instant Local + Permanent DB
                    localStorage.setItem('aot_map_last_basemap', e.name);
                    saveMapState(true); // Immediate save for layer changes
                } else {
                    // [Fix] Use debounced save for move/zoom to prevent ERR_INSUFFICIENT_RESOURCES
                    // Window resize triggers moveend but doesn't change center/zoom, so it will be filtered out
                    saveMapState(false); // Debounced save
                }
            });

            // [New] Modal/Form Integration for definitive Zoom Persistence
            // 1. Sync current map state when the Modal is fully opened (inputs are reachable)
            $(document).on('shown.bs.modal', `#modal_config_${uniqueId}`, function () {
                console.log(`[AoT Map] Modal shown for ${uniqueId}. Syncing current view.`);
                saveMapState(true); // Triggers DOM update
            });

            // 2. Pre-Submit Safeguard: Sync when Save button is clicked
            // [Fix] Attach to both the submit event and the specific Save button to be sure
            $(`#mod_widget_form_${uniqueId}`).on('submit', function() {
                console.log(`[AoT Map] Form submit detected for ${uniqueId}. Performing final view sync.`);
                saveMapState(true);
            });
            $(`input[name="widget_mod"], #widget_mod_${uniqueId}`).on('click', function() {
                console.log(`[AoT Map] Save button clicked for ${uniqueId}. Synchronizing DOM.`);
                saveMapState(true);
            });
        }

        function isValidGeometry(g) {
            if (!g || typeof g !== 'object') return false;
            const isCoord = (arr) => {
                if (!Array.isArray(arr) || arr.length < 2) return false;
                const lng = arr[0]; const lat = arr[1];
                if (typeof lng !== 'number' || !Number.isFinite(lng)) return false;
                if (typeof lat !== 'number' || !Number.isFinite(lat)) return false;
                // Strict lat/lng bounds check
                if (Math.abs(lat) > 86 || Math.abs(lng) > 181) return false; 
                // Ensure they aren't [0,0] if that's considered placeholder, but we allow 0,0 for now
                return true;
            };
            const isArrayOf = (arr, checkFn, minLen = 1) => Array.isArray(arr) && arr.length >= minLen && arr.every(checkFn);

            if (g.type === 'Point') return isCoord(g.coordinates);
            else if (g.type === 'MultiPoint') return isArrayOf(g.coordinates, isCoord, 1);
            else if (g.type === 'LineString') return isArrayOf(g.coordinates, isCoord, 2);
            else if (g.type === 'MultiLineString') return isArrayOf(g.coordinates, line => isArrayOf(line, isCoord, 2), 1);
            else if (g.type === 'Polygon') return isArrayOf(g.coordinates, ring => isArrayOf(ring, isCoord, 3), 1);
            else if (g.type === 'MultiPolygon') return isArrayOf(g.coordinates, poly => isArrayOf(poly, ring => isArrayOf(ring, isCoord, 3), 1), 1);
            else if (g.type === 'GeometryCollection') {
                 if (!g.geometries || !Array.isArray(g.geometries)) return false;
                 return g.geometries.every(isValidGeometry);
            }
            return false;
        }

        function renderOverlays(features, vars, explicitDevices) {
            if (!widgetMap) return;
            
            // 1. Zoom Animation Guard / Readiness Check
            const size = widgetMap.getSize();
            const po = widgetMap.getPixelOrigin();
            const pb = widgetMap.getPixelBounds();
            const isAnimating = widgetMap._animatingZoom;

            // [Iteration 11] Relaxed Guard: Don't wait for _renderer or exact PixelBounds for the logic to start.
            // These will be checked inside the atomic loop if needed, but we shouldn't stall here.
            if (isAnimating || size.x <= 0 || size.y <= 0 || !widgetMap.getBounds().isValid() || !po || po.x === undefined) {
                 if (size.x > 0 && !isAnimating) widgetMap.invalidateSize();
                 // Use requestAnimationFrame for snappier retry instead of fixed 200ms
                 requestAnimationFrame(() => renderOverlays(features, vars));
                 return;
            }

            // console.log(`[AoT Map] Starting render for ${features.length} features`);

            // [New] Prepare Allowed IDs Set for Filtering
            const allowedIds = new Set();
            const fetchIds = vars.map_device_ids || vars.device_ids;
            if (fetchIds && vars.include_all_devices !== true) {
                const parts = String(fetchIds).split(',');
                parts.forEach(id => {
                    const trimmed = id.trim();
                    if (trimmed) {
                        allowedIds.add(trimmed);
                        // Also add base ID for flexibility (e.g. dev::0 -> dev)
                        if (trimmed.includes('::')) allowedIds.add(trimmed.split('::')[0]);
                    }
                });
            }
            const isStrictFiltering = (allowedIds.size > 0 && vars.include_all_devices !== true);
            const liveDevices = (window.AoTMapApp && window.AoTMapApp[uniqueId] && window.AoTMapApp[uniqueId].devices) ? window.AoTMapApp[uniqueId].devices : (vars.devices || []);

            // Cleanup
            shapeGroup.clearLayers();
            deviceShapes = {}; 
            // [Req] Merged Site/Zone Layer
            // [Optimization] We don't clear labelLayers immediately if we want to avoid flicker
            // But for correctness with new data, we clear them.
            // [Fix] Hide layers initially to prevent "jump" during stable move
            // LayerGroup doesn't have setOpacity, so we use a CSS class on the map container
            const widgetEl = document.getElementById('aot-map-widget-' + uniqueId);
            if (widgetEl) widgetEl.classList.add('aot-map-loading-labels');
            
            labelLayers.siteZone.clearLayers();

            const explicitLabelsByNode = new Set();
            const explicitLabelsByDb = new Set();
            features.forEach(f => {
                const p = f.properties || {};
                const t = (p.aot_type || "").toLowerCase();
                if (t === 'label_aux') {
                    if (p.parent_node_id) explicitLabelsByNode.add(p.parent_node_id);
                    // [Fix] Stringify DB ID for consistent set lookup
                    if (p.parent_id) explicitLabelsByDb.add(String(p.parent_id));
                    
                    // [Fix] label_for is sometimes used as a backward compatible link
                    if (p.label_for) explicitLabelsByNode.add(p.label_for);
                }
            });

            const featuresToRender = [];
            features.forEach(f => {
                const props = f.properties || {};
                const type = (props.aot_type || "").toLowerCase();
                const name = props.label_name || props.name || props.node_id;
                const geometryType = f.geometry ? f.geometry.type : null;
                const nodeIdStr = String(props.node_id || "");
                
                // [New] Strict Device Filtering & Activation Lookup (Unified Round 18)
                const isDeviceRel = (type === 'device' || type === 'aot_device' || type === 'input' || type === 'output' || type === 'function');
                
                // [1] Find Live Device using Unified Matcher
                // [Fix] Prefer explicit device_id + channel_id over random node_id (Phase 2)
                let searchId = nodeIdStr; // Fallback
                if (isDeviceRel && props.device_id) {
                    searchId = (props.channel_id !== undefined && props.channel_id !== null && props.channel_id !== '') 
                             ? `${props.device_id}::${props.channel_id}` 
                             : props.device_id;
                }
                const liveDev = isDeviceRel ? findLiveDevice(searchId, liveDevices) : null;

                // [2] Selection Filter
                if (isStrictFiltering && isDeviceRel) {
                    if (!liveDev) return; // Not in selection
                }

                // [3] Activation Check
                const isActivated = !isDeviceRel || (liveDev && liveDev.is_activated !== false && liveDev.is_activated !== 'false');
                if (!isActivated) return; // Strict Hiding for unactivated channels

                // Handle Labels
                let labelAdded = false;
                if (type === 'site' && vars.show_site_label) {
                    if (!explicitLabelsByNode.has(props.node_id) && !explicitLabelsByDb.has(String(props.db_id))) {
                        addPriorityLabel(f, name, 'site-label', labelLayers.siteZone);
                        labelAdded = true;
                    }
                } else if (type === 'zone' && vars.show_zone_label) {
                    if (!explicitLabelsByNode.has(props.node_id) && !explicitLabelsByDb.has(String(props.db_id))) {
                        addPriorityLabel(f, name, 'zone-label', labelLayers.siteZone);
                        labelAdded = true;
                    }
                } else if (isDeviceRel && vars.show_device_labels) {
                    const isGhostName = (!name || name === 'New aot_device' || name === 'Undefined' || name === 'undefined' || name === 'Label');
                    if (isGhostName) return;

                    // [Fix] Marker Deduplication using Unified Matcher logic
                    let hasMarker = deviceMarkers[nodeIdStr] || deviceMarkers[props.node_id];
                    if (!hasMarker && liveDev) {
                         const existingMarker = deviceMarkers[String(liveDev.id)] || deviceMarkers[String(liveDev.unique_id)];
                         if (existingMarker) hasMarker = true;
                    }

                    if (props.node_id && !hasMarker && !explicitLabelsByNode.has(props.node_id) && !explicitLabelsByDb.has(String(props.db_id))) {
                        addPriorityLabel(f, name, 'device-label', labelLayers.device);
                        labelAdded = true;
                    }
                } else if (type === 'label_aux') {
                    if (!name || name === 'Label' || name === 'Undefined' || name === 'undefined') return;
                    const pType = props.parent_type || 'zone';
                    let show = (pType === 'site' && vars.show_site_label) || (pType === 'zone' && vars.show_zone_label) || (vars.show_length_label && name && name.includes('m'));
                    if (show) {
                         addPriorityLabel(f, name, 'custom-label', labelLayers.siteZone);
                         labelAdded = true;
                    }
                }

                // Determine Visibility for Shapes/Points
                let shouldRenderShape = false;
                if (type === 'site') shouldRenderShape = vars.show_site_shape;
                else if (type === 'zone') shouldRenderShape = vars.show_zone_shape;
                else if (type === 'facility') shouldRenderShape = vars.show_facility_shape;
                else if (type === 'equipment') shouldRenderShape = vars.show_equipment_shape;
                else if (isDeviceRel) shouldRenderShape = vars.show_device_shapes;
                else shouldRenderShape = vars.show_drawn_shapes;

                if (shouldRenderShape) {
                    // [Fix] Ghost Shape Prevention
                    if (geometryType === 'Point' && !props.is_circle && (type === 'site' || type === 'zone')) return;
                    const markerExists = nodeIdStr ? (deviceMarkers[nodeIdStr] || (liveDev && deviceMarkers[String(liveDev.id)])) : null;
                    if (geometryType === 'Point' && (labelAdded || markerExists) && !props.is_circle) return;

                    if (isValidGeometry(f.geometry)) featuresToRender.push(f);
                }
            });

            // console.log(`[AoT Map] Filtered to ${featuresToRender.length} features to render`);
            // [Fix] Do NOT return early here. Even if 0 shapes, we must continue to clear shapeGroup and trigger alignment.

            // [Iteration 11] Centralized Styling Logic
            function computeFeatureStyle(feature, dev) {
                const p = feature.properties || {};
                const t = (p.aot_type || "").toLowerCase();
                let themeColor = null;

                if (t === 'site') themeColor = theme.site;
                else if (t === 'zone') themeColor = theme.zone;
                else if (t === 'facility') themeColor = theme.facility;
                else if (t === 'equipment') themeColor = theme.equipment;
                else if (t === 'device' || t === 'aot_device' || t === 'input' || t === 'output' || t === 'function') {
                    const dT = (p.device_type || t || 'device').toLowerCase();
                    themeColor = vars.device_shape_color || theme[dT] || theme[p.device_type] || theme.device || '#995aff';
                }

                // [Fix] Prioritize Theme Color for Device Shapes (as requested)
                // If it is a device/aot_device and themeColor is resolved, use it.
                // Otherwise fallback to stored property color.
                let color;
                if ((t === 'device' || t === 'aot_device' || t === 'input' || t === 'output' || t === 'function') && themeColor) {
                    color = themeColor;
                } else {
                    color = p.stroke_color || p.color || themeColor || theme.device || '#3388ff';
                }
                
                // [Iteration 17] Facility Styling (Sprinkler & Main Pipe) Priority Check
                // Enhanced Type Checks (include sprinkler_coverage)
                const isSprinkler = (t === 'sprinkler' || t === '스프링클러' || p.sub_type === 'sprinkler' || p.sub_type === 'sprinkler_coverage' || p.device_type === 'sprinkler');
                const isMainPipe = (p.type === '주배관' || p.sub_type === 'pipe_main');

                let dashArray = p.dash_array || (t === 'zone' ? '5, 5' : null);
                let weight = p.weight || 2;
                let strokeOpacity = 1.0; 
                let fillOpacity = 0.3; // Default

                if (isSprinkler) {
                    dashArray = '5, 5'; // Dashed border
                    fillOpacity = 0.2;  // Transparency 0.2
                    strokeOpacity = 0.2; // Transparency 0.2
                    weight = 1;         // Half thickness (1)
                } 
                else if (isMainPipe) {
                    weight = (p.weight || 2) * 2; // Double weight
                     if (p.fill_opacity !== undefined) fillOpacity = parseFloat(p.fill_opacity);
                }
                 else {
                    // Generic Logic for Devices if NOT a sprinkler
                    if (t === 'device' || t === 'aot_device' || t === 'input' || t === 'output' || t === 'function') {
                       // [Fix] Dynamic Opacity for Devices (Strict 0.9 for ON)
                       // [v9] Handle both bool and string status
                       // [v10] Use Live Device Status if available (Phase 3)
                       const isLiveON = (dev && (dev.is_activated !== false && dev.is_activated !== 'false') && (dev.status === 'active' || dev.status === 'on' || dev.status === 'ON' || dev.is_active === true || dev.is_active === 'true'));
                       const isActive = isLiveON || (p.is_active === true || p.is_active === 'true' || p.status === 'active' || p.status === 'on' || p.status === 'ON');
                       
                       // Base opacity from vars or default 0.2
                       let baseOp = 0.2;
                       if (vars && vars.device_shape_opacity !== undefined) {
                           baseOp = parseInt(vars.device_shape_opacity) / 100;
                       }
                       
                       if (isActive) {
                           fillOpacity = 0.9;
                           strokeOpacity = 0.9;
                       } else {
                           fillOpacity = (p.fill_opacity !== undefined) ? parseFloat(p.fill_opacity) : baseOp;
                           strokeOpacity = (p.opacity !== undefined) ? parseFloat(p.opacity) : 0.5;
                       }
                    } else if (p.fill_opacity !== undefined) {
                        fillOpacity = parseFloat(p.fill_opacity);
                    }
                }

                return {
                    color: color,
                    fillColor: p.fill_color || color,
                    weight: weight,
                    opacity: strokeOpacity,
                    fillOpacity: fillOpacity,
                    dashArray: dashArray,
                    interactive: true,
                    noClip: true,
                    smoothFactor: 1.5
                };
            }

            // 2. Rendering Loop (Iteration 11: Consistent Styling)
            const newShapes = [];
            featuresToRender.forEach(f => {
                try {
                    const props = f.properties || {};
                    const type = (props.aot_type || "").toLowerCase();
                    const isDeviceRel = (type === 'device' || type === 'aot_device' || type === 'input' || type === 'output' || type === 'function');
                    const nodeIdStr = String(props.node_id || "");

                    // [Live Status Lookup] Recalculate liveDev for style and indexing (Phase 3)
                    let searchId = nodeIdStr; // Fallback
                    if (isDeviceRel && props.device_id) {
                        searchId = (props.channel_id !== undefined && props.channel_id !== null && props.channel_id !== '') 
                                 ? `${props.device_id}::${props.channel_id}` 
                                 : props.device_id;
                    }
                    const liveDev = isDeviceRel ? findLiveDevice(searchId, liveDevices) : null;

                    const styleConfig = computeFeatureStyle(f, liveDev);
                    
                    const geojsonLayer = L.geoJSON(f, {
                        style: () => styleConfig,
                        pointToLayer: (feature, latlng) => {
                            const p = feature.properties || {};
                            if (p.is_circle) {
                                const r = Math.max(0.1, parseFloat(p.radius) || 10);
                                return L.circle(latlng, Object.assign({ radius: r }, styleConfig));
                            }
                            // [Iteration 17] Sprinkler Point Rendering (if no circle property but known radius needed)
                            // Often sprinklers are Points with radius in config. If is_circle is missing, we might assume circle.
                            // But usually logic sets is_circle. We trust is_circle property for now.
                            return L.marker(latlng, { icon: L.divIcon({ className: 'hidden' }), interactive: false });
                        }
                    });

                    geojsonLayer.eachLayer(layerInstance => {
                        let l = layerInstance;
                        
                        // Circle Recovery (Polygon to Circle)
                        if (props.is_circle && !(l instanceof L.Circle)) {
                            let center = null;
                            if (props.center_lat !== undefined && props.center_lng !== undefined) {
                                center = L.latLng(parseFloat(props.center_lat), parseFloat(props.center_lng));
                            } else if (f.geometry.type === 'Point' && f.geometry.coordinates) {
                                center = L.latLng(f.geometry.coordinates[1], f.geometry.coordinates[0]);
                            } else if (l.getBounds && l.getBounds().isValid()) {
                                center = l.getBounds().getCenter();
                            }

                            if (center && !isNaN(center.lat) && !isNaN(center.lng)) {
                                l = L.circle(center, Object.assign({ 
                                    radius: parseFloat(props.radius) || 10
                                }, styleConfig));
                            }
                        }

                        if (l) {
                            l.feature = f;
                            // [Iteration 11] Hardened Instance Shielding
                            if (l._clipPoints) {
                                l._clipPoints = function() {
                                    this._parts = this._rings || [];
                                };
                            }
                            if (l._empty) {
                                l._empty = function() {
                                    // Never mark as empty to force a render attempt if geometry exists
                                    try {
                                        if (this._pxBounds && this._pxBounds.min) return false;
                                        if (this._project) this._project();
                                        return !this._pxBounds || !this._pxBounds.min;
                                    } catch(e) { return false; }
                                };
                            }
                            l.options.noClip = true;

                             if (type === 'device' || type === 'aot_device' || type === 'input' || type === 'output' || type === 'function') {
                                const ids = [props.unique_id, props.node_id, props.device_id, props.db_id];
                                // [Fix] Add Live Device IDs to mapping for real-time polling updates (Phase 3)
                                if (liveDev) {
                                    if (liveDev.id) ids.push(String(liveDev.id));
                                    if (liveDev.unique_id) ids.push(String(liveDev.unique_id));
                                }
                                ids.forEach(rawId => {
                                    if (rawId !== undefined && rawId !== null) {
                                        const sId = String(rawId);
                                        if (!deviceShapes[sId]) deviceShapes[sId] = [];
                                        deviceShapes[sId].push(l);
                                    }
                                });
                            }
                            newShapes.push(l);
                        }
                    });
                } catch (e) {
                    console.error("Individual feature preparation failed (Iteration 10):", e, f);
                }
            });

            // Final Shielded Atomic Addition
            shapeGroup.clearLayers();
            newShapes.forEach(l => {
                try {
                    if (l && l.addTo) {
                        l.addTo(shapeGroup);
                    }
                } catch (e) {
                    console.error("Atomic add crash (intercepted):", e);
                }
            });

            // [Fix] Trigger alignment immediately (v4) to prevent "one beat late" rendering
            if (window.AoTMapAlignment) {
                if (widgetMap && !widgetMap._animatingZoom && !isResizing) {
                    // Two-phase alignment to ensure DOM elements are attached but not yet painted in old positions
                    window.AoTMapAlignment.updateAlignment();
                    requestAnimationFrame(() => {
                        if (window.AoTMapAlignment) window.AoTMapAlignment.updateAlignment();
                    });
                }
            }
        }

        function addPriorityLabel(feature, text, className, group) {
            let center = null;
            try {
                const geom = feature.geometry, props = feature.properties || {};
                const isManualLabel = (props.aot_type === 'label_aux');
                
                // [Priority 1] Explicit Center Lat/Lng (Stored in Geo Design features)
                // [Fix] ONLY use for non-manual labels or if point geometry is missing
                if (!isManualLabel && props.center_lat !== undefined && props.center_lng !== undefined && props.center_lat !== null && props.center_lng !== null) {
                    center = L.latLng(parseFloat(props.center_lat), parseFloat(props.center_lng));
                }
                // [Priority 2] Point Geometry (Highest priority for Manual Labels)
                else if (geom && geom.type === 'Point' && geom.coordinates && geom.coordinates.length >= 2) {
                    center = L.latLng(parseFloat(geom.coordinates[1]), parseFloat(geom.coordinates[0]));
                }
                // [Priority 3] Latitude/Longitude (Alternative naming)
                else if (props.latitude !== undefined && props.longitude !== undefined && props.latitude !== null && props.longitude !== null) {
                    center = L.latLng(parseFloat(props.latitude), parseFloat(props.longitude));
                } 
                // [Priority 4] Lat/Lng (Short naming)
                else if (props.lat !== undefined && props.lng !== undefined && props.lat !== null && props.lng !== null) {
                    center = L.latLng(parseFloat(props.lat), parseFloat(props.lng));
                }
                
                // [Fallback 1] Centroid of Shape
                if (!center && geom && geom.coordinates) {
                    const temp = L.geoJSON(feature), bounds = temp.getBounds();
                    if (bounds.isValid()) center = bounds.getCenter();
                }
            } catch (e) {}

            if (!center) return;
            const props = feature.properties || {};
            const targetType = (props.aot_type === 'label_aux' && props.parent_type) ? props.parent_type : props.aot_type;
            let color = '#333';
            if (targetType === 'site') color = theme.site || '#DF5353';
            else if (targetType === 'zone') color = theme.zone || '#28a745';
            else if (targetType === 'facility') color = theme.facility || '#82898f';
            else if (targetType === 'equipment') color = theme.equipment || '#007bff';
            else if (targetType === 'input') color = theme.input || theme.device || '#3388ff';
            else if (targetType === 'output') color = theme.output || theme.device || '#3388ff';
            else if (targetType === 'function') color = theme.function || theme.device || '#3388ff';
            else if (targetType === 'device' || targetType === 'aot_device') color = theme.device || '#995aff';
            
            // [Fix] Adaptive Text Color (Black if bright, White if dark)
            let textColor = 'white';
            const hexMatch = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(color);
            if (hexMatch) {
                const r = parseInt(hexMatch[1], 16);
                const g = parseInt(hexMatch[2], 16);
                const b = parseInt(hexMatch[3], 16);
                const yiq = ((r * 299) + (g * 587) + (b * 114)) / 1000;
                if (yiq >= 150) textColor = 'black'; // Threshold 150 for "very bright"
            }

            // [Fix] Site/Zone Label Position & Size Improvements
            let fontSize = 12; // Default px base
            let fontEm = '1.0';

            if (targetType === 'site') {
                fontEm = vars.site_label_size || '1.2';
            } else if (targetType === 'zone') {
                fontEm = vars.zone_label_size || '1.0';
            }

            // [Fix] Priority Position: prioritize geo/design defined points (label_aux or property coords)
            // Existing logic already attempts to find coords in props.
            
            const bgStyle = `background-color: ${color}; color: ${textColor}; border-color: ${color};`;
            
            // [Modified] Popup Interaction for Label (Rename & Note)
            const tId = props.db_id || props.node_id || props.unique_id || text;
            const tType = targetType || 'site';
            const safeName = (text || '').replace(/'/g, "\\'"); // Escaped for JS string in onclick

            // UI Construction
            
            // Note Create Action
            const openNoteAction = `window.dispatchEvent(new CustomEvent('open-notes', { detail: { targetId: '${tId}', targetType: '${tType}', name: '${safeName}' } }))`;

            // Rename Action
            // Access updateLabelName via global scope
            const renameAction = `window.AoTMapApp['${uniqueId}'].updateLabelName('${tId}', '${tType}', document.getElementById('rename-input-${tId}').value)`;

            // HTML for Marker (Visual Label) - No onclick
            // [Fix] Added 'marker-pill' class to ensure aot-map-alignment.js treats it as centered
            const html = `<div class="aot-label-content marker-pill p-1 rounded shadow-sm text-center" 
                               style="width: max-content; font-size:${fontEm}em; line-height:1.2; white-space: nowrap; border: 1px solid; ${bgStyle}; margin: 0; transform: translate(-50%, -50%); pointer-events: auto; display: flex; align-items: center; justify-content: center; cursor: pointer;">
                        <span style="font-weight:bold;">${text}</span>
                    </div>`;

            const icon = L.divIcon({ 
                className: 'geo-label-marker', 
                html: html, 
                iconSize: [0, 0], 
                iconAnchor: [0, 0] 
            });

            // [Fix] Apply Z-Index Priority (Output > Input > Site > Zone)
            let zOffset = 500; // Default (Zone)
            if (targetType === 'output') zOffset = 10000;
            else if (targetType === 'input' || targetType === 'function') zOffset = 5000;
            else if (targetType === 'site') zOffset = 1000;
            else if (targetType === 'zone') zOffset = 500;

            // [Fix] interactive: true to allow Popup
            const labelMarker = L.marker(center, { icon: icon, interactive: true, zIndexOffset: zOffset }).addTo(group);
            labelMarker.aot_name = text;

            // Bind Popup
            labelMarker.bindPopup(() => {
                 // Fetch Last Note Title (Async)
                 setTimeout(() => {
                     fetch(`/notes/target/${tId}`)
                        .then(r => r.json())
                        .then(notes => {
                            const el = document.getElementById(`last-note-title-${tId}`);
                            if (el) {
                                if (notes && notes.length > 0) {
                                    el.innerText = notes[0].note.substring(0, 30) + (notes[0].note.length > 30 ? '...' : '');
                                    el.style.color = '#555';
                                } else {
                                    el.innerText = window._('No notes written');
                                    el.style.color = '#ccc';
                                }
                            }
                        })
                        .catch(() => {});
                 }, 100);

                 return `
                    <div style="min-width: 180px; padding: 5px;">
                        <!-- Row 1: Name (Read-Only) - Device Style -->
                        <div class="aot-popup-title" style="font-size: 1.4em; font-weight: bold; margin: 0; line-height: 1.2; word-break: break-all; text-align: left; padding-top: 15px; margin-bottom: 8px; color: #333;">
                            ${text}
                        </div>
                        
                        <hr style="margin: 8px 0; border-top: 1px solid #eee;">
                        
                        <!-- Row 2: Note -->
                        <div style="display: flex; flex-direction: column; gap: 6px;">
                            <button class="btn btn-primary" style="border-radius: 14px; height: 28px; width: 100%; font-size: 0.9em; display: flex; align-items: center; justify-content: center; padding: 0;"
                                onclick="${openNoteAction}">
                                <i class="fas fa-clipboard mr-2"></i> ${window._('Open Notes')}
                            </button>
                            <div id="last-note-title-${tId}" style="font-size: 0.85em; color: #888; padding-left: 4px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;">
                                ${window._('Loading...')}
                            </div>
                        </div>
                    </div>
                 `;
            }, {
                className: 'aot-map-popup',
                minWidth: 160,
                maxWidth: 200
            });
        }

        function renderDevices(devices, vars) {
             // [Fix] Sync uniqueId devices reference
             if (window.AoTMapApp && window.AoTMapApp[uniqueId]) {
                 window.AoTMapApp[uniqueId].devices = devices;
             }
            // [New] Prepare Allowed IDs Set for Filtering
            const allowedIds = new Set();
            const fetchIds = vars.map_device_ids || vars.device_ids;
            if (fetchIds && vars.include_all_devices !== true) {
                const parts = String(fetchIds).split(',');
                parts.forEach(id => {
                    const trimmed = id.trim();
                    if (trimmed) {
                        allowedIds.add(trimmed);
                        if (trimmed.includes('::')) allowedIds.add(trimmed.split('::')[0]);
                    }
                });
            }
            const isStrictFiltering = (allowedIds.size > 0 && vars.include_all_devices !== true);

            labelLayers.device.clearLayers();
            const processedBaseIds = new Set();

            devices.forEach(dev => {
                if (!dev.lat || !dev.lng) return;

                // [New] Strict Device Filtering
                if (isStrictFiltering) {
                    const devId = String(dev.id || dev.device_id || dev.unique_id || dev.db_id);
                    const baseId = devId.split('::')[0];
                    if (!allowedIds.has(devId) && !allowedIds.has(baseId)) {
                        return; // Skip this device marker
                    }
                }
                
                // [Fix] Deduplication Logic
                // If a device has multiple channels (e.g. dev_id::0, dev_id::1), they share the same base ID.
                // We only want to render the label once per physical device location.
                const devIdKey = dev.device_id || dev.device_unique_id || (dev.unique_id ? dev.unique_id.split('::')[0] : dev.id.split('::')[0]);
                if (vars.show_device_labels) {
                    if (processedBaseIds.has(dev.id)) return; // [Fix] Deduplicate by Full ID (including channel) to allow per-channel labels
                    processedBaseIds.add(dev.id);
                }

                // [Fix] Strengthen isON check
                const isStatusON = (dev.status === 'active' || dev.status === 'on' || dev.status === 'ON' || dev.is_active === true || dev.is_active === 'true' || dev.is_activated === true || dev.is_activated === 'true');
                // Output is "Activated" if selected. We only care about is_activated for visibility.
                const isActivated = (dev.is_activated !== false && dev.is_activated !== 'false');
                const isON = isStatusON || (dev.type === 'output' || dev.device_type === 'output');
                
                // [Req] Exclude Inactive Channels from markers (Strict)
                if (!isActivated) return;
                // [Fix] Use Unified Color Logic
                const userColor = getUnifiedDeviceColor(dev.device_type || dev.type, dev, vars);

                if (vars.show_device_labels) {
                    // devIdKey is already defined above
                    // [Fix] Prefer ALL measurements map (from Backend) if available, otherwise fallback to selected map
                    const targetMap = (vars && vars.all_measurements_map) ? vars.all_measurements_map : (vars && vars.measurements_map ? vars.measurements_map : {});
                    const devMeas = targetMap[devIdKey] ? targetMap[devIdKey] : [];
                    
                    // [Fix] Zero Value Handling: Explicitly check for undefined/null, do NOT use || 'N/A' which clobbers 0.
                    let firstVal = 'N/A';
                    let unit = '';
                    
                    if (devMeas.length > 0) {
                        // [Fix] Find measurement matching current channel_id
                        const m = devMeas.find(meas => parseInt(meas.channel) === parseInt(dev.channel_id)) || devMeas[0];
                        if (m && m.last_value !== undefined && m.last_value !== null && m.last_value !== '') {
                            firstVal = m.last_value;
                        }
                        // Unit Lookup
                        if (m) {
                            unit = (window.aotMapUnits && window.aotMapUnits[m.id]) ? window.aotMapUnits[m.id] : (m.unit || '');
                        }
                        if (unit === 'bearing') unit = ''; // Formatting
                    }
                    // [Removed Duplicate currentStyle declaration]
                    let baseSize = 12;
                    if (dev.font_size) {
                        const scale = parseInt(dev.font_size);
                        if (!isNaN(scale)) baseSize = 12 + ((scale - 1) * 4); 
                    }
                    const displayName = dev.device_name || dev.name;
                    // [Fix] Ghost Label Prevention: Skip if name is missing
                    if (!displayName || displayName.trim() === '') return;

                    // [Req] New Label Format: "Name Value Unit" (Space separated, Unit 0.5x size)
                    // [Refactor] Use Spans for Updateability (applyDeviceStatusStyle)
                    // Structure: <Name> <ValContainer><Val><Unit></ValContainer>
                    
                    const showValue = (firstVal !== undefined && firstVal !== null && firstVal !== 'N/A' && firstVal !== '');
                    const valueDisplay = showValue ? 'inline' : 'none';
                    
                    const finalLabelContent = `
                        <span class="dev-name">${displayName}</span>
                        <span class="dev-val-group" style="display: ${valueDisplay}; margin-left: 4px;">
                            <span class="dev-value">${firstVal}</span>
                            <span class="dev-unit" style="font-size: 0.5em; margin-left: 2px;">${unit}</span>
                        </span>`;
                    
                    // [Fix] Ghost Label Prevention: Skip if name is missing
                    if (!displayName || displayName.trim() === '') return;

                    // [v4] Enhanced Styling: On state gets darker shadow (lower transparency) of theme color
                    const shadowColorOff = window.AoTMapApp.hexToRgba(userColor, 0.3); // [Fix] Use theme color for OFF shadow too
                    const shadowColorOn = window.AoTMapApp.hexToRgba(userColor, 0.6);  // [v6] 0.6 opacity for on state
                    
                    const currentStyle = isON 
                        ? `background-color: ${userColor}; color: #ffffff; border: 2px solid #ffffff !important; box-shadow: 0 4px 12px ${shadowColorOn} !important;` 
                        : `background-color: #f8f9fa; color: #000000; border: 2px solid ${userColor} !important; box-shadow: 0 2px 5px ${shadowColorOff} !important;`;
                    
                    
                    // [Refactor] label_spacing is now used for Collision Margin (Alignment), not inner padding.
                    // Internal padding is handled by CSS (.marker-pill class).
                    
                    const labelHtml = `<div class="aot-label-content marker-pill ${isON ? 'device-on' : ''}" style="${currentStyle} font-size: ${baseSize}px; width: max-content; white-space: nowrap; margin: 0; ${dev.label_style || ''}">
                                <div style="line-height: 1.2;">${finalLabelContent}</div>
                            </div>`;
                    const centeredIcon = L.divIcon({ 
                        className: 'geo-label-marker', 
                        html: labelHtml, 
                        iconSize: [0, 0], 
                        iconAnchor: [0, 0] 
                    });

                    // [Fix] Apply Z-Index Priority (Output > Input)
                    // Output (10000) > Input/Function (5000)
                    let zOffset = 5000;
                    if (dev.type === 'output') zOffset = 10000;
                    else if (dev.type === 'input' || dev.type === 'function') zOffset = 5000;

                    const labelMarker = L.marker([dev.lat, dev.lng], { icon: centeredIcon, interactive: true, zIndexOffset: zOffset }).addTo(labelLayers.device);
                    labelMarker.aot_name = displayName;
                    labelMarker.options.id = dev.id;
                    labelMarker.options.device_unique_id = devIdKey;
                    labelMarker.userColor = userColor;
                    labelMarker.baseSize = baseSize;
                    
                    // [Fix] Store Metadata for persistence re-rendering
                    labelMarker.drawMeta = {
                        name: displayName,
                        unit: unit,
                        labelStyle: dev.label_style || '',
                        baseSize: baseSize
                    };

                    labelMarker.options.is_active = isON;
                    labelMarker.options.last_status_change = dev.last_status_change;
                    bindDevicePopup(labelMarker, dev, vars);
                    labelMarker.bindPopup(labelMarker.getPopup().getContent(), { 
                        className: 'aot-map-popup', 
                        minWidth: 160, 
                        maxWidth: 200 
                    });
                    deviceMarkers[dev.id] = labelMarker;
                    // [Fix] Immediate status reflection
                    applyDeviceStatusStyle(dev.id, isON, firstVal, unit); // Pass Unit explicitly for first render fallback
                } else {
                    // [Fix] Hide Dot Marker if Device already has a Shape (Polygon/Line)
                    // This prevents the "Dot" from appearing on top of the Zone/Device Polygon when labels are off.
                    const hasShape = deviceShapes[String(dev.id)] || deviceShapes[String(devIdKey)] || (dev.unique_id && deviceShapes[String(dev.unique_id)]);
                    if (hasShape) return;

                    const circleMarker = L.circleMarker([dev.lat, dev.lng], { radius: 8, fillColor: isON ? userColor : "#999", color: "#fff", weight: 2, opacity: 1, fillOpacity: dev.opacity || (isON ? 0.8 : 0.2), last_status_change: dev.last_status_change, is_active: isON }).addTo(labelLayers.device);
                    bindDevicePopup(circleMarker, dev, vars);
                    circleMarker.bindPopup(circleMarker.getPopup().getContent(), { 
                        className: 'aot-map-popup', 
                        minWidth: 160, 
                        maxWidth: 200 
                    });
                    deviceMarkers[dev.id] = circleMarker;
                    circleMarker.userColor = userColor;
                    // [Fix] Immediate status reflection
                    applyDeviceStatusStyle(dev.id, isON);
                }
            });
            if (window.AoTMapAlignment) window.AoTMapAlignment.updateAlignment();
        }

        function bindDevicePopup(marker, dev, vars) {
            marker.bindPopup(() => {
                const isON = (typeof marker.options.is_active !== 'undefined') ? marker.options.is_active : (dev.status === 'active');
                const uniqueKey = dev.device_id || dev.device_unique_id || (dev.unique_id ? dev.unique_id.split('::')[0] : dev.id.split('::')[0]);
                
                // [New] Note Section HTML builder
                const notePreviewId = `note-prev-${uniqueKey}`;
                const noteSectionHtml = `
                    <hr style="margin: 8px 0; border: 0; border-top: 1px solid #eee;">
                    <button class="btn btn-primary" style="border-radius: 14px; height: 28px; width: 100%; font-size: 0.9em; display: flex; align-items: center; justify-content: center; padding: 0;"
                         onclick="window.dispatchEvent(new CustomEvent('open-notes', { detail: { targetId: '${uniqueKey}', targetType: 'device', name: '${(dev.device_name || dev.name || '').replace(/'/g, "\\'")}' } }))">
                        <i class="fas fa-clipboard mr-2"></i> ${window._('Create Note')}
                    </button>
                    <div id="${notePreviewId}" style="font-size: 0.9em; color: #666; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; min-height: 1.2em; line-height: 1.4; margin-top: 6px;">
                        <span style="color: #ccc; font-style: italic;">...</span>
                    </div>
                `;

                // [New] Fetch Note Logic
                const fetchLastNote = () => {
                    fetch(`/notes/target/${uniqueKey}`)
                        .then(r => r.json())
                        .then(notes => {
                            const el = document.getElementById(notePreviewId);
                            if (el) {
                                if (notes && notes.length > 0) {
                                    el.innerText = notes[0].note;
                                    el.style.fontStyle = 'normal';
                                    el.style.color = '#666';
                                } else {
                                    el.innerHTML = `<span style="color: #ccc; font-style: italic;">${window._('No Notes')}</span>`;
                                }
                            }
                        })
                        .catch(e => {
                             const el = document.getElementById(notePreviewId);
                             if (el) el.innerHTML = `<span style="color: #ccc;">${window._('Load Failed')}</span>`;
                        });
                };

                const notesBtnHtml = `<button onclick="console.log('Notes Click:', '${uniqueKey}'); window.dispatchEvent(new CustomEvent('open-notes', { detail: { targetId: '${uniqueKey}', targetType: 'device', name: '${(dev.device_name || dev.name || '').replace(/'/g, "\\'")}' } }))" class="btn btn-sm btn-outline-secondary" style="padding: 2px 6px; margin-left: 5px; border-radius: 4px; border-color: #ccc; color: #666;" title="Notes"><i class="fas fa-sticky-note"></i></button>`;
                const canControl = (dev.type === 'output' || dev.type === 'function');
                
                // [Custom Popup for Input]
                if (dev.type === 'input') {
                    // [Fix] Use dev.device_name (raw name) if available
                    const displayName = dev.device_name || dev.name;
                    const devNameHtml = `<div class="aot-popup-title">${displayName}</div>`;
                    let bodyHtml = '';
                    
                    // [Fix] Use device_id for lookup (provided by API), fallback to unique_id matching
                    // [Fix] Use device_id for lookup (provided by API), fallback to unique_id matching
                    const devIdKey = dev.device_id || dev.device_unique_id || (dev.unique_id ? dev.unique_id.split('::')[0] : dev.id.split('::')[0]);
                    
                    // [Fix] Prefer ALL measurements map (from Backend) if available, otherwise fallback to selected map
                    const targetMap = (vars && vars.all_measurements_map) ? vars.all_measurements_map : (vars && vars.measurements_map ? vars.measurements_map : {});
                    const devMeas = targetMap[devIdKey] ? targetMap[devIdKey] : [];
                    
                    if (devMeas.length > 0) {
                        devMeas.forEach(m => {
                            const mName = m.meas_name || m.name || ''; 
                            const mVal = (m.last_value !== undefined && m.last_value !== null && m.last_value !== '') ? m.last_value : 'N/A';
                            let unitStr = (window.aotMapUnits && window.aotMapUnits[m.id]) ? window.aotMapUnits[m.id] : (m.unit || '');
                            
                            // [Formatting] Hide 'bearing' unit
                            if (unitStr === 'bearing') unitStr = '';

                            // [Fix] Refined Popup Layout (2026-01-16 Iteration 5)
                            // Font Size restored to 1.2em (Strict User Requirement)
                            // Wrapper min-width removed to prevent overflow.
                            bodyHtml += `
                                <div class="aot-popup-row" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px dotted #eee; padding-bottom: 4px;">
                                    <span style="font-weight: normal; font-size: 1.2em; color: #333; flex: 1; padding-right: 4px; line-height: 1.2; min-width: 0; word-break: break-word;">${mName}</span>
                                    <span style="text-align: right; white-space: nowrap; flex: 0 0 auto;">
                                        <span id="popup-val-${dev.id}-${m.id}" style="font-weight: bold; font-size: 1.2em; color: #000;">${mVal}</span>
                                        <span class="aot-popup-unit" style="font-size: 0.9em; margin-left: 2px; color: #555;">${unitStr}</span>
                                    </span>
                                </div>
                            `;
                        });
                    } else {
                        bodyHtml = `<div class="text-muted">${window._('No Measurements')}</div>`;
                    }
                    
                    // [Fix] Attach popupopen listener to fetch fresh data
                    marker.on('popupopen', () => {
                        // [New] Fetch Note
                        fetchLastNote();

                        if (devMeas.length > 0) {
                            devMeas.forEach(m => {
                                // Fetch URL: /last/<unique_id>/<type>/<meas_id>/<max_age>
                                const url = `/last/${devIdKey}/input/${m.id}/300`;
                                const valEl = document.getElementById(`popup-val-${dev.id}-${m.id}`);
                                
                                if (valEl) {
                                    fetch(url)
                                        .then(res => (res.status === 200) ? res.json() : null)
                                        .then(data => {
                                            // Handle Array format [epoch, value] which is common in AoT API
                                            let val = null;
                                            if (Array.isArray(data) && data.length >= 2) val = data[1];
                                            else if (data && data.value !== undefined) val = data.value;

                                            if (val !== undefined && val !== null) {
                                                // Rounding logic for floats
                                                if (typeof val === 'number' && !Number.isInteger(val)) {
                                                    val = parseFloat(val.toFixed(2));
                                                }
                                                valEl.innerText = val;
                                            }
                                        })
                                        .catch(() => {});
                                }
                            });
                        }
                    });

                    // [Fix] Remove hardcoded min-width to allow Leaflet maxWidth to control size
                    // [Mod] Injected Note Section
                    return `<div>${devNameHtml}<hr style="margin: 8px 0;">${bodyHtml}${noteSectionHtml}</div>`;
                }

                // [Custom Popup for Output/Function]
                // [Modified Layout 2026-01-16]
                // Row 1: Name (Left) + Slide Toggle (Right)
                // Row 2: Working Time (Left Label, Right Value)
                // Row 3: Last Duration (Left Label, Right Value)

                // 1. Header Row
                const toggleId = `toggle-${dev.id}`;
                const durId = `dur-${dev.id}`;
                
                // Toggle Button HTML (Slide Switch)
                // Positioned to the right. 
                // [Fix] Restore original onchange logic + Add _pending_toggle to prevent server overwrite
                const btnHtml = `
                    <label class="btn-toggle" style="margin-bottom: 0;">
                        <input type="checkbox" id="${toggleId}" class="btn-toggle-input" ${isON ? 'checked' : ''} ${canControl ? '' : 'disabled'}
                               onchange="let m=window.AoTMapApp['${uniqueId}'].deviceMarkers['${dev.id}']; if(m){ m.options._pending_toggle=Date.now(); m.options.is_active=this.checked; m.options.last_status_change=this.checked?Math.floor(Date.now()/1000):null; if(window.AoTStopwatchManager) { let th=(m.options.refresh_seconds?parseFloat(m.options.refresh_seconds):5.0)+1.0; window.AoTStopwatchManager.register('${dev.id}', '${dev.channel_id || 0}', this.checked, m.options.last_status_change, document.getElementById('dur-${dev.id}'), th*1000, true); } } window.AoTMapLoader.toggleDevice('${dev.id}', this.checked, '${(dev.channel_id && dev.channel_id !== 'undefined') ? dev.channel_id : 0}', '${dev.type}')">
                        <span class="btn-toggle-slider">
                            <span class="btn-toggle-thumb"></span>
                        </span>
                    </label>
                `;

                // Flex Container for Header
                // [Modified Layout]
                // Removed padding-right.
                // We will add padding-top to the *wrapper* (see html variable construction below) 
                // to push this row DOWN, leaving the Close button (absolute top-right) in its own visual space "Row 1".
                // [Fix] Added gap: 10px to ensure minimum spacing between Name and Toggle button (approx. popup margin size).
                const headerHtml = `
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 10px;">
                        <div class="aot-popup-title" style="font-size: 1.4em; font-weight: bold; margin: 0; line-height: 1.2; word-break: break-all;">${dev.name}</div>
                        <div style="display: flex; align-items: center; flex: 0 0 auto;">
                            ${btnHtml}
                        </div>
                    </div>
                `;

                // 2. Info Rows
                const formatTime = (sec) => {
                    // [Fix] Default to 00:00:00 instead of --- as requested
                    if (sec === undefined || sec === null || isNaN(sec)) return '00:00:00';
                    const s = parseInt(sec, 10);
                    const h = Math.floor(s / 3600).toString().padStart(2, '0');
                    const m = Math.floor((s % 3600) / 60).toString().padStart(2, '0');
                    const second = (s % 60).toString().padStart(2, '0');
                    return `${h}:${m}:${second}`;
                };

                const lastDurStr = formatTime(dev.last_duration);

                // Info Container
                let infoHtml = `
                    <div style="border-top: 1px solid #eee; padding-top: 8px;">
                        <!-- Working Time -->
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                            <span style="font-weight: bold; color: #555;">${window._('Current Work Time')}</span>
                            <span id="${durId}" class="aot-timer-display" style="font-family: monospace; font-size: 1.1em; font-weight: bold;">00:00:00</span>
                        </div>
                        <!-- Last Time -->
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-weight: bold; color: #555;">${window._('Last Work Time')}</span>
                            <span id="last-dur-${dev.id}" style="font-family: monospace; font-size: 1.1em; color: #777;">${lastDurStr}</span>
                        </div>
                    </div>
                `;

                // Close the main container div
                // [Fix] Added padding-top: 15px to create visual space for the Close button above the header content.
                // [Mod] Injected Note Section
                let html = `<div style="min-width: 180px; padding-top: 15px;">${headerHtml}${infoHtml}${noteSectionHtml}</div>`;

                // [Stopwatch Timer Logic - Refactored to use Centralized Manager]
                marker.on('popupopen', function() {
                    // [New] Fetch Note
                    fetchLastNote();

                    const el = document.getElementById(`dur-${dev.id}`);
                    if (!el || !window.AoTStopwatchManager) return;

                    const isActive = !!marker.options.is_active;
                    // Check if isActive is false
                    const startEpoch = isActive ? (marker.options.last_status_change || null) : null;
                    const channel = (dev.channel_id && dev.channel_id !== 'undefined') ? dev.channel_id : 0;
                    
                    // Calculation for threshold included in register call handled by updateMarkerStatus/onchange usually
                    // For popup open, we rely on the manager to have the state or sync.
                    // We just re-register to bind the element.
                    // We can pass the threshold here too if available in options.
                    let th = 7000;
                    if (marker.options && marker.options.refresh_seconds) {
                        th = (parseFloat(marker.options.refresh_seconds) + 1.0) * 1000;
                    }
                    // console.log(`[AoT Map Debug] popupopen triggering Register...`);
                    // Pass isUserAction = false (popup open is passive)
                    window.AoTStopwatchManager.register(dev.id, channel, isActive, startEpoch, el, th, false);
                    
                    // [Fix] Also trigger a fetch for last duration immediately on popup open
                    const lastDurEl = document.getElementById(`last-dur-${dev.id}`);
                    if (lastDurEl) {
                         const baseId = dev.id.split('::')[0];
                         fetch(`/output_last_duration_public/${baseId}/${channel}`)
                            .then(r => r.json())
                            .then(d => {
                                if (d && d.last_duration_sec !== undefined) {
                                    dev.last_duration = d.last_duration_sec; // Update cache
                                    lastDurEl.innerText = formatTime(d.last_duration_sec);
                                }
                            }).catch(()=>{});
                    }
                });

                return html + `</div>`;
            });
        }
        function applyDeviceStatusStyle(devId, isActive, val) {
            const marker = deviceMarkers[devId]; if (!marker) return;
            const dev = devices.find(d => d.id === devId); if (!dev) return;

            const sDevId = String(devId);
            let baseId = sDevId;
            if (sDevId.indexOf('::') !== -1) {
                baseId = sDevId.split('::')[0];
            }

            const isOutput = (dev.type === 'output' || dev.device_type === 'output' || (dev.type && String(dev.type).toLowerCase() === 'output'));
            const uc = getUnifiedDeviceColor(dev.device_type || dev.type, dev, vars);

            // 1. Label Styling (DivIcon based)
            // [Fix] Cluster Persistence: We MUST update the Icon itself, not just the DOM element.
            // If we only update DOM, the changes are lost when the marker is clustered/unclustered.
            
            if (marker.drawMeta) {
                // It's a Label Marker (Input/Output/Function with Label)
                const meta = marker.drawMeta;
                const baseSize = meta.baseSize || 12;
                
                // Shadow / Border Colors
                const shadowColorOff = window.AoTMapApp.hexToRgba(uc, 0.3);
                const shadowColorOn = window.AoTMapApp.hexToRgba(uc, 0.6);

                const currentStyle = isActive 
                        ? `background-color: ${uc}; color: #ffffff; border: 2px solid #ffffff !important; box-shadow: 0 4px 12px ${shadowColorOn} !important;` 
                        : `background-color: #f8f9fa; color: #000000; border: 2px solid ${uc} !important; box-shadow: 0 2px 5px ${shadowColorOff} !important;`;
                
                // Value & Unit Handling
                const safeVal = (val !== undefined && val !== null && val !== 'N/A') ? val : '';
                const showValue = (safeVal !== '');
                const valueDisplay = showValue ? 'inline' : 'none';
                const unitStr = meta.unit || '';

                const finalLabelContent = `
                        <span class="dev-name">${meta.name}</span>
                        <span class="dev-val-group" style="display: ${valueDisplay}; margin-left: 4px;">
                            <span class="dev-value">${safeVal}</span>
                            <span class="dev-unit" style="font-size: 0.5em; margin-left: 2px;">${unitStr}</span>
                        </span>`;
                
                // Reconstruct HTML
                const labelHtml = `<div class="aot-label-content marker-pill ${isActive ? 'device-on' : ''}" style="${currentStyle} font-size: ${baseSize}px; width: max-content; white-space: nowrap; margin: 0; pointer-events: auto; ${meta.labelStyle}">
                                <div style="line-height: 1.2;">${finalLabelContent}</div>
                            </div>`;
                
                // Update Icon (Persist State)
                const newIcon = L.divIcon({ 
                    className: 'geo-label-marker', 
                    html: labelHtml, 
                    iconSize: [0, 0], 
                    iconAnchor: [0, 0] 
                });
                
                marker.setIcon(newIcon);

            } else if (marker.setStyle) {
                // CircleMarker or similar
                marker.setStyle({
                    fillColor: isActive ? (marker.userColor || uc) : "#999",
                    fillOpacity: isActive ? 0.8 : 0.2
                });
            }

            // 2. Shape Styling (Polylines / Polygons)
            let shapes = deviceShapes[sDevId] || deviceShapes[baseId];
            if (shapes) {
                if (!Array.isArray(shapes)) shapes = [shapes];
                const baseOp = (vars && vars.device_shape_opacity !== undefined) ? (parseInt(vars.device_shape_opacity) / 100) : 0.2;
                const targetOpacity = isActive ? 0.9 : baseOp;

                shapes.forEach(sh => {
                    if (!sh || !sh.setStyle) return;
                    try {
                        sh.setStyle({
                            fillColor: uc,
                            color: uc,
                            fillOpacity: targetOpacity,
                            opacity: isActive ? 0.9 : 0.5
                        });
                        // Fallback for groups
                        if (sh.invoke) sh.invoke('setStyle', {
                            fillOpacity: targetOpacity,
                            opacity: isActive ? (sh instanceof L.Polyline && !(sh instanceof L.Polygon) ? 1.0 : 0.9) : 0.5
                        });
                    } catch (e) {}
                });
            }

            // 3. Persistent state on marker
            marker.options.is_active = isActive;
        }


        function updateMarkerStatus(devId) {
            const marker = deviceMarkers[devId]; if (!marker) return Promise.resolve();
            const dev = devices.find(d => d.id === devId); if (!dev) return Promise.resolve();
            const isOutput = (dev.type === 'output' || dev.device_type === 'output' || (dev.type && String(dev.type).toLowerCase() === 'output'));
            let apiPath = '';
            let sDevId = String(devId);
            let baseId = sDevId;
            if (sDevId.indexOf('::') !== -1) {
                baseId = sDevId.split('::')[0];
            }
            if (isOutput) apiPath = `/outputstate_unique_id/${baseId}/${dev.channel_id || '0'}`;
            else {
                const devMeas = vars.measurements_map[baseId] || [];
                const measId = devMeas.length > 0 ? devMeas[0].id : null;
                // [Fix] If no measurements configured, we might still want to fetch status (active/idle) 
                // but we need a valid measId for /last API. 
                // For input devices without measurement panel selection, we exit, 
                // BUT we still want applyDeviceStatusStyle to be called if possible.
                if (measId) apiPath = `/last/${baseId}/${dev.type}/${measId}/${vars.max_measure_age || 300}`;
            }

            if (!apiPath) {
                // If no API path resolved, at least ensure current state is reflected
                applyDeviceStatusStyle(devId, !!marker.options.is_active); 
                return Promise.resolve();
            }
            return fetch(apiPath).then(res => res.status === 204 ? null : res.json()).then(data => {
                let isActive = false, val = 'N/A';
                if (isOutput) isActive = (data === 'on' || data === true || data === 1);
                else if (data && Array.isArray(data) && data.length >= 2) { 
                    isActive = true; 
                    val = data[1]; 
                } else if (data && data.value !== undefined && data.value !== null) {
                    isActive = true;
                    val = data.value;
                }
                
                // [Fix] Update Last Duration periodically if popup is open
                let durationPromise = Promise.resolve();
                if (dev.type === 'output') {
                    const lastDurEl = document.getElementById(`last-dur-${dev.id}`);
                    if (lastDurEl && document.body.contains(lastDurEl)) {
                         // Only fetch if element exists (popup open)
                         durationPromise = fetch(`/output_last_duration_public/${baseId}/${dev.channel_id || '0'}`)
                            .then(r => r.json())
                            .then(d => {
                                if (d && d.last_duration_sec !== undefined) {
                                    dev.last_duration = d.last_duration_sec;
                                    const s = parseInt(d.last_duration_sec, 10);
                                    if (!isNaN(s)) {
                                        const h = Math.floor(s / 3600).toString().padStart(2, '0');
                                        const m = Math.floor((s % 3600) / 60).toString().padStart(2, '0');
                                        const sec = (s % 60).toString().padStart(2, '0');
                                        lastDurEl.innerText = `${h}:${m}:${sec}`;
                                    }
                                }
                            }).catch(()=>{});
                    }
                }
                
                return durationPromise.then(() => {
                    // [Sync Persistence] Do not let server state overwrite local state if toggle was recent (<10s)
                    // [Sync Persistence] Smart Sync Logic
                    if (marker.options._pending_toggle) {
                        const elapsed = Date.now() - marker.options._pending_toggle;
                        
                        if (isActive === !!marker.options.is_active) { 
                            delete marker.options._pending_toggle;
                            applyDeviceStatusStyle(devId, isActive, val);
                        } 
                        else {
                            const timeoutMs = (refreshSeconds ? parseFloat(refreshSeconds) : 5) * 1000;
                            if (elapsed > (timeoutMs + 1000)) {
                                 console.log(`[AoT Map] Toggle sync timed out (${elapsed}ms). Reverting to server state.`);
                                 delete marker.options._pending_toggle;
                                 applyDeviceStatusStyle(devId, isActive, val);
                            }
                        }
                    } else {
                        applyDeviceStatusStyle(devId, isActive, val);
                    }
                    
                    // [Sync Measurement Panel]
                    if (widgetMap.measurementPanel && widgetMap.measurementPanel.updateValue && dev.type !== 'output') {
                        const devMeas = vars.measurements_map[baseId] || [];
                        devMeas.forEach(m => {
                            if (val !== 'N/A' && m.id === devMeas[0].id) {
                                let unit = window.aotMapUnits ? window.aotMapUnits[m.id] : (m.unit || '');
                                widgetMap.measurementPanel.updateValue(m.id, val, unit);
                            }
                        });
                    }

                    const toggleBtn = document.getElementById(`toggle-${sDevId}`);
                    if (toggleBtn) toggleBtn.checked = isActive;
                });
            }).catch(e => {
                console.error(`[AoT Map] updateMarkerStatus error for ${devId}:`, e);
            });
        }


        initWidget();
    };

    // [Cleanup 2026-01-18] Removed conflicting Config Panel logic. 
    // Logic now resides exclusively in aot-map-config.js.

})();

