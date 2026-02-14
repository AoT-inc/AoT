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

        // Layer Storage (Separated by Mode for Isolation)
        this.layerStorage = {
            'site': new L.FeatureGroup(),
            'zone': new L.FeatureGroup(),
            'device': new L.FeatureGroup(), // Legacy/Generic
            'facility': new L.FeatureGroup(),
            'equipment': new L.FeatureGroup(),
            'connection': new L.FeatureGroup(), // [Fix] Add dedicated storage for fittings
            'aot_device': new L.FeatureGroup(),
            'infra_blob': new L.FeatureGroup(),
            'reference': new L.FeatureGroup(), // User Draw Reference Lines
            'label_aux': new L.FeatureGroup() // Protected Labels
        };
        
        // [Optimization] Dirty Tracking for Delta Save
        this.dirtyNodeIds = new Set();
        this.deletedNodeIds = new Set(); // Tracks node_ids (str) or db_ids (int)

        this.isLoading = false; // [Fix] Clear loading state on start
        this.loadingOverlay = null;

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



    _initMap() {
        // 1. Initialize Map via Loader
        // Disable default zoom control because we have external buttons
        const mapInit = AoTMapLoader.initMap(this.mapId, 'default', {
            zoomControl: false,
            tap: false, // [Fix] iOS Touch fix (prevents double-tap issues and ghost clicks)
            scrollWheelZoom: true // [Fix V15] Ensure Scroll Zoom is enabled by default
        });

        this.map = mapInit.map;

        this.baseMaps = mapInit.baseLayers;
        this.overlayMaps = mapInit.overlays;
        const layerControl = mapInit.layerControl;

        // [Persistence] Restore Base Layer Preference
        try {
            const savedBaseLayerName = localStorage.getItem('aot_geo_design_basemap');
            // console.log("[GeoDesign] Saved Base Layer:", savedBaseLayerName);

            if (savedBaseLayerName && this.baseMaps[savedBaseLayerName]) {
                const layer = this.baseMaps[savedBaseLayerName];
                // If loader already added a DIFFERENT base layer, remove it to prevent double attribution
                if (mapInit.activeLayer && mapInit.activeLayer !== layer) {
                    // console.log("[GeoDesign] Removing loader fallback layer:", mapInit.activeLayer);
                    this.map.removeLayer(mapInit.activeLayer);
                }

                if (this.map && !this.map.hasLayer(layer)) {
                    this.map.addLayer(layer);
                }
            } else {
                // If no saved preference, respect what loader picked (default/fallback)
                // No action needed.
            }
        } catch (e) { /* console.warn("Restore BaseMap failed", e); */ }

        // [Persistence] Save Preference
        this.map.on('baselayerchange', (e) => {
            localStorage.setItem('aot_geo_design_basemap', e.name);
        });

        // 2. Initialize Editor
        const featureGroup = new L.FeatureGroup().addTo(this.map);
        this.featureGroup = featureGroup; // Critical for proper tracking
        window.AoTMapEditor.init(this.map, featureGroup);

        // [Fix V21] Custom Panes for Z-Index Management
        // Order: Site (350) < Zone (360) < Connection (440) < Equipment (450) < Device (460) < Label (650) < Overlay (Search) (2000)
        // Default Marker Pane is 600, Overlay Pane is 400.
        // We want Sites/Zones strictly below standard overlays.
        const createPane = (name, zIndex) => {
            if (!this.map.getPane(name)) {
                this.map.createPane(name);
                this.map.getPane(name).style.zIndex = zIndex;
            }
        };
        createPane('sitePane', 350);
        createPane('zonePane', 360);
        createPane('infraPane', 370);
        createPane('facilityPane', 400); // [Fix] User Req: Facility (3)
        createPane('equipmentPane', 450); // [Fix] User Req: Equipment (4)
        createPane('connectionPane', 455); // ABOVE Equipment
        createPane('devicePane', 460);    // [Fix] User Req: Device (5)
        createPane('labelPane', 650); // Above markers

        // [Fix V11] Ensure pendingOp is cleared when drawing stops (Repeat Mode support)
        if (this.map) {
             this.map.on(L.Draw.Event.DRAWSTOP, () => {
                 // console.log("[GeoDesign] Draw Stopped (EventListener). Clearing pendingOp.");
                 this._resetPendingOp();
             });
        }

        // Assign Panes to Storage Groups
        // Must clear existing layers if this is called late? (Init only)
        this.layerStorage['site'].options.pane = 'sitePane';
        this.layerStorage['zone'].options.pane = 'zonePane';
        this.layerStorage['facility'].options.pane = 'facilityPane'; // [Fix] Assign Pane
        this.layerStorage['infra_blob'].options.pane = 'infraPane';
        this.layerStorage['connection'].options.pane = 'connectionPane';
        this.layerStorage['equipment'].options.pane = 'equipmentPane';
        this.layerStorage['aot_device'].options.pane = 'devicePane';
        this.layerStorage['device'].options.pane = 'devicePane';
        this.layerStorage['label_aux'].options.pane = 'labelPane';
        this.layerStorage['reference'].options.pane = 'infraPane';


        // 3. Move/Style Layer Control (Specific to Design Page Layout)
        if (layerControl) {
            const controlContainer = layerControl.getContainer();
            // [Fix] Target External Container First (Z-Index 2500)
            const externalContainer = document.getElementById('external-layer-control');
            let targetContainer = externalContainer || document.querySelector('.map-tools-right');

            if (targetContainer && controlContainer) {
                if (externalContainer) {
                    // Start of External: append
                    targetContainer.appendChild(controlContainer);
                    // Reset Styles for external flow
                    controlContainer.style.margin = '0';
                    controlContainer.style.position = 'relative';
                } else {
                    // Fallback to tools right (Legacy)
                    targetContainer.prepend(controlContainer);
                }

                // Use Controls Helper to style it (Generic)
                if (window.AoTMapControls && window.AoTMapControls.styleLayerControl) {
                    window.AoTMapControls.styleLayerControl(controlContainer);
                }
            }
        }
    }

    // [Feature V23] Explicit Layer Order Management
    _enforceLayerOrder() {
        if (!this.map) return;
        
        // Z-Index Management (Leaflet FeatureGroups don't have explicit zIndex, rely on add order or bringToFront)
        // Order: Base < Standard Overlays (Cadastral) < Site < Zone < Pipe < Device < Label
        
        // 1. Bring Overlays to front (if tile layers)
        Object.values(this.overlayMaps).forEach(l => {
            if (this.map.hasLayer(l) && l.bringToFront) l.bringToFront();
        });

        // 2. Storage Groups (Order: Site < Zone < Facility < Equipment < Connection < Device)
        const order = ['infra_blob', 'site', 'zone', 'facility', 'equipment', 'connection', 'reference', 'device', 'aot_device', 'label_aux'];
        
        order.forEach(k => {
            const g = this.layerStorage[k];
            if (g && this.map.hasLayer(g)) {
                g.bringToFront();
            }
        });

        // 3. Editor (Active) - NO LONGER forced to absolute top.
        // It stays in its assigned Mode Pane (Site/Zone/etc)
        // This ensures the 1-5 visual stacking remains stable.
        /*
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            window.AoTMapEditor.featureGroup.bringToFront();
        }
        */
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
                        background: rgba(255, 255, 255, 0.6); z-index: 2000;
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
            const paneName = (mode === 'site' ? 'sitePane' : 
                             (mode === 'zone' ? 'zonePane' : 
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

        // [Fix V20] Ensure Editor is always on top (Z-Index Fix)
        // Storage layers added during context switch might cover the Editor group (Leaflet Add Order).
        // This fixes the "Cannot select shapes on first entry" issue.
        this._enforceLayerOrder();

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
            const devType = this.devices.activeDevice.type;
            const functionTypes = ['trigger', 'pid', 'conditional', 'custom', 'generic_function'];
            let savedColor = devType ? localStorage.getItem(`aot_config_color_${devType}`) : null;
            if (!savedColor && functionTypes.includes(devType)) {
                savedColor = localStorage.getItem('aot_config_color_function');
            }
            const themeColor = savedColor || '#995aff';

            if (layer.setStyle) {
                layer.setStyle({ color: themeColor, fillColor: themeColor });
            }
        } else if (type && ['site', 'zone', 'facility', 'equipment'].includes(type)) {
            // Apply Theme Color for Standard Types
            const appTheme = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
            const themeColor = appTheme[type] || localStorage.getItem(`aot_config_color_${type}`) || 
                              (type === 'site' ? '#DF5353' : (type === 'zone' ? '#28a745' : (type === 'equipment' ? '#007bff' : '#82898f')));

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
                            // We could restrict reference to Zone only as per user request ("대지/구획 등 부모 도형이 없는") -> Usually Zone.
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
            if (layer instanceof L.Polyline && !(layer instanceof L.Polygon)) {
                // Do nothing for lines
            } else {
                let areaDisplay = '';
                try {
                    if (!window.turf) throw new Error("Turf.js not loaded");

                    let geojson = layer.toGeoJSON();
                    // Handle Circle for Area Calc
                    if (layer instanceof L.Circle) {
                        const center = layer.getLatLng();
                        const radius = layer.getRadius();
                        geojson = window.turf.circle([center.lng, center.lat], radius, { steps: 64, units: 'meters' });
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
        // alert("기준선을 그릴 구획 내부를 클릭하여 시작하세요. (더블클릭으로 종료)");
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
            console.log("[GeoDesign] pendingOp set to create_ref_line");
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

    async generatePipes(parentFeature, config) {
        if (this.modules) return await this.modules.generatePipes(parentFeature, config);
    }


    generateSprinklers(targetFeature, config) {
        if (this.modules) this.modules.generateSprinklers(targetFeature, config);
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
        // console.log(`[Load] Loading Features for UUID: ${mapUuid}`);

        try {
            this._clearLayers();
            window.AoTMapEditor.clear(); // Clear editor's feature group

            // Parallelize Bulk Overlay Loading and Device Loading
            const [allFeatures, _] = await Promise.all([
                window.AoTMapData.loadOverlays(mapUuid), // Fetch ALL overlays in one go
                this._loadMapDevices(mapUuid)           // Parallelize device loading
            ]);

            if (!allFeatures || allFeatures.length === 0) {
                // console.log("[Load] No features found.");
                return;
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

                // [Fix] Block 'connection' features (Ephemereal).
                // They must be rebuilt by rebuildConnections() to ensure correct state.
                if (type === 'connection' || props.aot_type === 'connection') {
                    return false;
                }

                return true;
            });

            if (validFeatures.length > 0) {
                L.geoJSON(validFeatures, {
                    pointToLayer: (feature, latlng) => {
                        const props = feature.properties || {};
                        const isSprinkler = (props.aot_type === 'equipment' && props.sub_type === 'sprinkler') || (props.aot_type === 'sprinkler');
                        const isCoverage = (props.aot_type === 'equipment' && props.sub_type === 'sprinkler_coverage');

                        if (isSprinkler) {
                            return L.circleMarker(latlng, {
                                radius: 2,
                                color: '#007bff',
                                fillColor: '#007bff',
                                fillOpacity: 1,
                                interactive: false
                            });
                        }
                        if (isCoverage) {
                            return L.circle(latlng, {
                                radius: props.radius || 10,
                                color: '#007bff',
                                weight: 1,
                                fillOpacity: 0.1,
                                dashArray: '3, 3',
                                interactive: false
                            });
                        }
                        return L.marker(latlng);
                    },
                    onEachFeature: (f, l) => {
                        l.feature = l.feature || { type: 'Feature', properties: {} };
                        l.feature.properties = l.feature.properties || {};
                        const type = l.feature.properties.aot_type || 'feature';
                        this._processLoadedFeature(l, type);
                    }
                });
            }

            // Finalize: Setup Active Mode
            // This will handle moving layers to Editor and ensuring storage groups are visible.
            this._switchLayerContext(null, this.activeMode);

            // Cleanup Orphans (Fix for Black Labels)
            if (this.labels) this.labels.cleanupOrphanLabels();

            // Update Design Info
            setTimeout(() => {
                if (this.geometry) this.geometry.recalculateSpatialRelationships();
                this.updateDesignInfo();
            }, 300); // Trigger after load

        } finally {
            // [Fix] Release isLoading BEFORE slow background tasks
            // This allows saves (ghost prevention now handled by Interaction Overlay)
            this.isLoading = false;
            this._toggleInteraction(true); // Unlock Interaction

            // [New] Ensure Layer Order (Editor Group on Top)
            this._enforceLayerOrder();

            // [New] Load Map Devices (Real Devices linked via location) as background task
            this._loadMapDevices(mapUuid);
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
            // console.warn("[Load] Blocked: Already loading a map.");
            return;
        }

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
            if (s.center && s.zoom) this.map.setView(s.center, s.zoom);

            // 2. Load Data first, THEN Apply Mode/Layers
            this._loadAllFeatures(uuid).then(() => {
                // console.log("[Load] Features Loaded. Restoring State (Mode/Layers)...");
                this._applyState(s);
                // Force Update UI Counters (Repair Data first)
                this._repairLoadedData();

                // [Fix] Force 'Site' mode entry on load to ensure UI tools are ready
                setTimeout(() => {
                    this.setMode('site');
                }, 500);
            });
        };

        // 1. Load View State
        if (state) {
            applyFullState(state);
            this._updateUIHeader();
        } else {
            // Updated: loadMapDesign now returns {uuid, name, state}
            window.AoTMapData.loadMapDesign(uuid).then(resp => {
                const s = resp.state || {}; // Extract state
                const n = resp.name || _('design_map_new'); // Extract name

                // Update Name State from DB
                this.currentMapName = n;
                this.lastLoadedName = n;

                applyFullState(s);
                this._updateUIHeader();
            }).catch(err => {
                // console.warn("[GeoDesign] Load failed (First Access?). Auto-initializing and Saving...", err);
 
                // Auto-Init Defaults
                if (!this.currentMapName || this.currentMapName === "Design Map" || this.currentMapName === _('design_map_new')) {
                    this.currentMapName = _('design_map_new');
                }
                this.lastLoadedName = this.currentMapName;
                this._updateUIHeader();

                // Initialize empty state (loads empty features)
                applyFullState({});

                // Auto-Save to Create Entry
                this.saveDesign().then(() => {
                    this.ui.showToast(_('new_map_autosaved'), 'success');
                });
            });
        }
    }

    _applyState(state) {
        if (!state) return;

        // 1. Center & Zoom
        if (state.center && state.zoom) this.map.setView(state.center, state.zoom);

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
        if (state.active_base_id) {
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
        if (state.active_overlays) {
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
        // console.log("[Geo] Clearing all layers...");
        // 1. Clear Storage
        Object.keys(this.layerStorage).forEach(k => {
            this.layerStorage[k].clearLayers();
            if (this.map.hasLayer(this.layerStorage[k])) {
                this.map.removeLayer(this.layerStorage[k]);
            }
        });
        // 2. Clear Editor
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

            // Pan/Zoom
            if (targetLayer.getBounds) {
                this.map.flyToBounds(targetLayer.getBounds(), { padding: [50, 50], maxZoom: 20, duration: 0.5 });
            } else if (targetLayer.getLatLng) {
                this.map.flyTo(targetLayer.getLatLng(), 20, { duration: 0.5 });
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
                    // [Fix] Auto-Color for New Shapes
                    const devType = props.device_type;
                    if (devType) {
                        let savedColor = localStorage.getItem(`aot_config_color_${devType}`);
                        if (!savedColor && ['trigger', 'pid', 'conditional', 'custom', 'generic_function'].includes(devType)) {
                            savedColor = localStorage.getItem('aot_config_color_function');
                        }
                        if (savedColor) {
                            props.color = savedColor;
                            // Apply style immediately if supported
                            if (l.setStyle) {
                                l.setStyle({ color: savedColor, fillColor: savedColor });
                            }
                        }
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
                // console.log(`[Switch] Moving ${layers.length} layers to Editor for: ${newMode}`);
 
                layers.forEach(l => {
                    window.AoTMapEditor.featureGroup.addLayer(l);
                    // [Fix] SOLID style for regular active shapes (not highlighted orange)
                    this.ui._setLayerStyle(l, false); 
                });

                // Clear storage (temporarily empty while in Editor)
                storageGroup.clearLayers();
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
                 devGroup.clearLayers();
            }

            // [New] Reference Line Editing in Equipment Mode
            // Allow Reference Lines to be edited/deleted when in 'equipment' mode (for Pipe drawing)
            if (newMode === 'equipment' && this.layerStorage['reference']) {
                 const refGroup = this.layerStorage['reference'];
                 if (this.map.hasLayer(refGroup)) this.map.removeLayer(refGroup);
                 
                 const layers = Array.from(refGroup.getLayers());
                 layers.forEach(l => {
                     window.AoTMapEditor.featureGroup.addLayer(l);
                     this.ui._setLayerStyle(l, true); // Active style for reference too? Or keep distinct?
                     // Keep default style but allow interaction
                 });
                 refGroup.clearLayers();
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
        Object.entries(this.overlayMaps).forEach(([n, l]) => { if (this.map.hasLayer(l)) activeOverlays.push(n); });

        let activeBase = null;
        Object.entries(this.baseMaps).forEach(([n, l]) => { if (this.map.hasLayer(l)) activeBase = n; });

        const state = {
            center: this.map.getCenter(),
            zoom: this.map.getZoom(),
            locked: this.isLocked,
            hidden: this.isHidden,
            active_overlays: activeOverlays,
            active_base_layer: activeBase,
            theme_config: this.theme_config || {} // [New] Persist Map-Specific Theme
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

                    if (forcedType && l.feature.properties.aot_type !== 'label_aux') {
                        l.feature.properties.aot_type = forcedType;
                    }

                    // Circle-to-Polygon conversion
                    if (l instanceof L.Circle) {
                        const currentType = l.feature.properties.aot_type || forcedType;
                        const isDevice = (currentType === 'device' || currentType === 'aot_device' || l.feature.properties.device_id);
                        if (window.turf) {
                            const center = l.getLatLng();
                            const radius = l.getRadius();
                            if (isDevice) {
                                l.feature.geometry = { type: 'Point', coordinates: [center.lng, center.lat] };
                            } else {
                                const polyGeo = window.turf.circle([center.lng, center.lat], radius, { steps: 64, units: 'meters' });
                                l.feature.geometry = polyGeo.geometry;
                            }
                            l.feature.properties.is_circle = true;
                            l.feature.properties.radius = radius;
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
                            if (l instanceof L.Marker && l.feature?.properties?.unique_id) return;
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
                    const typesToSync = targetTypes || ['site', 'zone', 'infra_blob', 'facility', 'equipment', 'label_aux', 'device', 'reference', 'aot_device'];
                    typesToSync.forEach(type => {
                        savePromises.push(window.AoTMapData.saveOverlays(this.currentMapUuid, type, categorized[type] || []));
                    });

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

        // 2. Clear Active Editor
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

        // [New] Real-time Update Listener
        window.addEventListener('aot:editor:created', (e) => {
            // Only update if it's an equipment (pipe/sprinkler) or relevant type
            const type = e.detail?.aotType;
            const layer = e.detail?.layer;

            if (['equipment', 'pipe_branch', 'pipe_main', 'sprinkler'].includes(type) || type === 'aot_device') {
                
                // [Fix] Immediate Color Application for New Device Shapes
                if (type === 'aot_device' && layer && layer.feature && layer.feature.properties) {
                    const props = layer.feature.properties;
                    // Try getting sub-mode from Panel (e.g., 'input', 'output')
                    // Panel stores subMode in navStack or we can guess from context?
                    // Actually, createDeviceMarker logic sets device_type. But for shapes?
                    // If shape, we might rely on what Panel set as 'sub_type' in startDraw options.
                    // But startDraw options usually set 'aot_type'. 
                    // Let's check if we can get the active sub-mode from UI?
                    // Accessing UI directly: this.ui.getDeviceSubMode()
                    
                    let devType = props.device_type;
                    if (!devType && this.ui && this.ui.getDeviceSubMode) {
                        devType = this.ui.getDeviceSubMode();
                        props.device_type = devType; // Save it
                    }

                    if (devType) {
                        let savedColor = localStorage.getItem(`aot_config_color_${devType}`);
                         if (!savedColor && ['trigger', 'pid', 'conditional', 'custom', 'generic_function'].includes(devType)) {
                            savedColor = localStorage.getItem('aot_config_color_function');
                        }
                        
                        if (savedColor) {
                             props.color = savedColor;
                             if (layer.setStyle) {
                                 layer.setStyle({ color: savedColor, fillColor: savedColor, fillOpacity: 0.5 });
                             }
                        }
                    }
                }

                // console.log("[GeoDesign] Shape Created/Edited. Updating Information...");
                this.updateDesignInfo();
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
                    // Reload Page to refresh list (Simplest way for now)
                    location.reload();
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

        // Use Leaflet handlers directly
        const handlers = ['dragging', 'touchZoom', 'doubleClickZoom', 'scrollWheelZoom', 'boxZoom', 'keyboard'];
        handlers.forEach(h => {
            this.isLocked ? this.map[h].disable() : this.map[h].enable();
        });
        if (this.map.tap) this.isLocked ? this.map.tap.disable() : this.map.tap.enable();

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
            btn.innerHTML = '<i class="fas fa-eye-slash text-muted"></i>';
        } else {
            targets.forEach(el => el.classList.remove('d-none'));
            if (leftGroup) Array.from(leftGroup.children).forEach(c => c.classList.remove('d-none'));
            btn.innerHTML = '<i class="fas fa-eye"></i>';
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
                if (layer instanceof L.Circle) {
                    const center = layer.getLatLng();
                    const radius = layer.getRadius();
                    geojson = window.turf.circle([center.lng, center.lat], radius, { steps: 64, units: 'meters' });
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

    _toggleLengthLabels() {
        if (!this.map) return;
        const container = this.map.getContainer();
        if (container.classList.contains('aot-hide-labels')) {
            container.classList.remove('aot-hide-labels');
            // console.log("[GeoDesign] Labels Shown");
        } else {
            container.classList.add('aot-hide-labels');
            // console.log("[GeoDesign] Labels Hidden");

            // Inject CSS if needed (One-time)
            if (!document.getElementById('aot-hide-label-style')) {
                const style = document.createElement('style');
                style.id = 'aot-hide-label-style';
                style.innerHTML = `
                    .aot-hide-labels .aot-measure-label,
                    .aot-hide-labels .aot-pipe-label,
                    .aot-hide-labels .leaflet-tooltip { 
                        display: none !important; 
                    }
                `;
                document.head.appendChild(style);
            }
        }
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
        // 1. Handle Aot-Device subtypes UI (Icons/Labels in Devices Module)
        if (['input', 'output', 'function'].includes(type) && this.devices) {
            this.devices.updateDeviceColor(type, color);
        }

        const isDeviceSubtype = ['input', 'output', 'function'].includes(type);
        const functionTypes = ['trigger', 'pid', 'conditional', 'custom', 'generic_function'];

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
                    if (type === 'function') match = functionTypes.includes(devType);
                    else match = (devType === type);
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

        // RECOVER CIRCLE (If saved as converted polygon OR Point+Radius)
        if (props.is_circle) {
            let center = null;
            const radius = props.radius;

            if (props.center_lat && props.center_lng) {
                center = [props.center_lat, props.center_lng];
            } else if (window.turf && f.geometry.type === 'Polygon') {
                const centroid = window.turf.centroid(f);
                center = [centroid.geometry.coordinates[1], centroid.geometry.coordinates[0]];
            } else if (f.geometry.type === 'Point') {
                // [New] Direct Point Recovery
                center = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
            }

            if (center && radius) {
                const circleLayer = L.circle(center, { 
                    radius: radius,
                    interactive: (props.sub_type !== 'sprinkler_coverage') // Keep coverage circles non-interactive
                });
                circleLayer.feature = JSON.parse(JSON.stringify(l.feature)); // Keep original feature data
                
                // [Fix] Ensure feature geometry reflects the Circle if accidentally lost or if we want consistency?
                // Actually, for Point storage, keeping Point geometry in feature is fine as long as we render Circle.
                // But Leaflet Draw acts on the layer type. 
                
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
            // Check if it's a shape (not a marker/point from device loc)
            // Even if it is a Point, if it's from _loadAllFeatures, it's an overlay.
            // But usually overlay points are filtered.
            // Safest: Route ALL 'aot_device' overlays to 'device' storage.
            targetKey = 'device';
            // Normalize type to 'device' to ensure consistency
            l.feature.properties.aot_type = 'device';
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
            // Priority: Saved Property Color > Device Type Config > Default
            let color;
            const isDevice = (aotType === 'device' || aotType === 'aot_device');
            if (isDevice) {
                const devType = l.feature.properties.device_type;
                // [Fix] Apply Saved/Configured Color
                let savedColor = devType ? localStorage.getItem(`aot_config_color_${devType}`) : null;
                if (!savedColor && ['trigger', 'pid', 'conditional', 'custom', 'generic_function'].includes(devType)) {
                    savedColor = localStorage.getItem('aot_config_color_function');
                }
                if (l.feature.properties.color) savedColor = l.feature.properties.color; // Prioritize saved prop if exists

                const finalColor = savedColor || '#995aff';
                l.feature.properties.color = finalColor; // Sync back
                color = finalColor;
            } else {
                color = l.feature.properties.color;
            }

            if (!color && l.feature.properties.device_type) {
                const dType = l.feature.properties.device_type;
                color = localStorage.getItem(`aot_config_color_${dType}`);
                if (!color && ['trigger', 'pid', 'conditional', 'custom', 'generic_function'].includes(dType)) {
                    color = localStorage.getItem('aot_config_color_function');
                }
            }
            color = color || '#995aff'; 

            // Apply Style
            if (l.setStyle) {
                l.setStyle({ 
                    color: color,
                    fillColor: color,
                    fillOpacity: 0.5,
                    weight: 3
                }); 
            }
            // Ensure property is synced for future saves
            // [Fix] Do NOT stamp the theme color back into the property. 
            // This prevents "baking in" the theme color, allowing dynamic updates if the theme changes later.
            // l.feature.properties.color = color;
        }

        if (isLabel) {
            if (this.labels) {
                this.labels.convertToLabel(l);
                if (!this.layerStorage['label_aux'].hasLayer(l)) {
                     this.layerStorage['label_aux'].addLayer(l);
                }
                // Force visibility
                if (!this.map.hasLayer(this.layerStorage['label_aux'])) {
                    this.map.addLayer(this.layerStorage['label_aux']);
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
                        // [Fix] Enforce Pane
                        if (storageGroup && storageGroup.options.pane) {
                            l.options.pane = storageGroup.options.pane;
                        } else if (targetKey && this.layerStorage[targetKey] && this.layerStorage[targetKey].options.pane) {
                            l.options.pane = this.layerStorage[targetKey].options.pane;
                        }

                        if (!window.AoTMapEditor.featureGroup.hasLayer(l)) {
                             window.AoTMapEditor.featureGroup.addLayer(l);
                             this.ui._setLayerStyle(l, false); 
                        }
                    }
                } else {
                    if (storageGroup && !storageGroup.hasLayer(l)) {
                        // [Fix] Enforce Pane
                        if (storageGroup.options.pane) {
                             l.options.pane = storageGroup.options.pane;
                        }

                        storageGroup.addLayer(l);
                        // Ensure storage group is visible on map (Passive Layers)
                        if (!this.map.hasLayer(storageGroup)) {
                            this.map.addLayer(storageGroup);
                        }
                        this.ui._setLayerStyle(l, false);
                    }
                }

            // Initial Style: (Already handled in if/else above)
            // this.ui._setLayerStyle(l, false);

            // Labels
            if (this.geometry) {
                if (['site', 'zone'].includes(type) || ['site', 'zone'].includes(targetKey)) {
                    this.geometry.updateMeasurementLabels(l);
                }
                this.geometry.updatePipeLabels(l);
            }

            // Guard: Sprinkler Coverage - Do not add interactive events for coverage circles
            if (l.feature.properties.sub_type === 'sprinkler_coverage') {
                return;
            }

            // Updated Event Handler (Compatible with Prop Changes)
            l.on('click', (e) => {
                // [Fix] Allow selection if Mode matches OR if in Equipment Mode selecting Site/Zone OR Device Mode selecting Device
                const fType = l.feature.properties.aot_type;
                const isAllowed = (this.activeMode === fType) 
                    || (this.activeMode === 'equipment' && ['site', 'zone'].includes(fType))
                    || (this.activeMode === 'aot_device' && fType === 'device');

                if (!isAllowed) return; // Allow bubble for drawing tools

                // [Fix] Bubbling Protection: If we are DRAWING, do NOT stop propagation.
                // Stopping propagation here prevents the map from receiving the click and finishing the draw/rectangle/circle.
                if (window.AoTMapEditor && window.AoTMapEditor.activeShape) {
                    // console.log("[GeoDesign] Click bubbling allowed for drawing tool.");
                    return; 
                }

                L.DomEvent.stopPropagation(e);

                // INTERCEPT: Merge/Subtract Pending Op
                if (this.pendingOp && ['merge', 'sub'].includes(this.pendingOp.type)) {
                    const isPolygon = (l instanceof L.Polygon) || (l.feature.geometry.type === 'Polygon');
                    if (isPolygon) {
                        if (this.pendingOp.type === 'merge') this.geometry.handleGeometryOp('merge', this.pendingOp.targetLayer, l);
                        else if (this.pendingOp.type === 'sub') this.geometry.handleGeometryOp('sub', this.pendingOp.targetLayer, l);

                        this.pendingOp = null;
                        L.DomUtil.removeClass(this.map._container, 'crosshair-cursor');
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
                    || (this.activeMode === 'equipment' && ['site', 'zone'].includes(fType))
                    || (this.activeMode === 'aot_device' && fType === 'device');
                if (isAllowed) {
                    L.DomEvent.stopPropagation(e);
                }
            });

            // [New] Marker Interaction (Popup) - Unified
            if (l instanceof L.Marker && l.feature.properties.aot_type !== 'label_aux') {
                l.on('dblclick', (e) => {
                    L.DomEvent.stopPropagation(e);
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
        // console.log("[GeoDesign] Setting Active Layer:", layer.feature?.properties?.node_id);
        
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
                 // Lazy Init Editing Handler
                 try {
                     if (layer instanceof L.Marker) layer.editing = new L.Edit.Marker(layer);
                     else if (layer instanceof L.Circle) layer.editing = new L.Edit.Circle(layer);
                     else if (layer instanceof L.Polyline || layer instanceof L.Polygon) layer.editing = new L.Edit.Poly(layer);
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
