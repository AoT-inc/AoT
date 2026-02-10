/**
 * aot-map-editor.js
 * Design & Editor Module using Leaflet.Draw
 * Handles drawing, styling, and managing features (shapes).
 */

const AoTMapEditor = {
    map: null,
    featureGroup: null,
    drawControl: null,
    editHandler: null,
    deleteHandler: null,

    // State
    currentType: 'site', // site, zone, facility, equipment, aot_device
    editEnabled: false,
    deleteEnabled: false,
    activeDrawer: null, // [Fix] Track active drawer to disable it when switching

    // Styles
    styles: {
        site: { color: '#DF5353', weight: 4, fill: false }, // Red (User Theme)
        zone: { color: '#28a745', weight: 2, fill: false, dashArray: '5,5' }, // Green Dashed
        facility: { color: '#82898f', weight: 3, fill: true, fillOpacity: 0.2 }, // Grey (Infrastructure)
        equipment: { color: '#007bff', weight: 3, fill: true, fillOpacity: 0.2 }, // Blue (Water/System)
        aot_device: { color: '#995aff', weight: 2, fill: true, fillOpacity: 0.5 }, // Purple (AoT)
        reference: { color: '#ff00ff', weight: 4, dashArray: '10, 10', fill: false, opacity: 1.0 } // Magenta Dashed (Reference)
    },

    /**
     * Initialize Editor
     * @param {L.Map} map 
     * @param {L.FeatureGroup} featureGroup 
     */
    init: function (map, featureGroup) {
        this.map = map;
        this.featureGroup = featureGroup;

        // Ensure Leaflet.Draw is loaded
        if (!L.Control.Draw) {
            // console.error("Leaflet.Draw not loaded.");
            return;
        }
        
        // 1. Apply Theme Config
        this._applyThemeConfig();

        this._bindEvents();
    },
    
    _applyThemeConfig: function() {
        if (!window.AOT_GEO_CONFIG || !window.AOT_GEO_CONFIG.theme_config) return;
        
        const theme = window.AOT_GEO_CONFIG.theme_config;
        
        // Helper to update specific style if color exists
        const updateColor = (type, colorKey) => {
             if (theme[colorKey] && this.styles[type]) {
                 this.styles[type].color = theme[colorKey];
             }
        };
        
        updateColor('site', 'site');
        updateColor('zone', 'zone');
        updateColor('facility', 'facility');
        updateColor('equipment', 'equipment');
        updateColor('aot_device', 'device');
        
        // Note: Panel styles are handled by CSS variables or specific UI components (AoTGeoDesign)
        // console.log("[AoTMapEditor] Theme Applied:", theme);
    },

    /**
     * Set Current Drawing Type
     * @param {string} type 
     */
    setType: function (type) {
        this.currentType = type;
        // [Fix] Trigger state update on type change (UI Sync)
        this._triggerStateChange();
    },
    
    activeShape: null, // [New] Track active shape name for toggle UI

    /**
     * [Fix] Stop All Active Tools (Draw/Edit/Delete)
     * Enforces mutual exclusivity.
     */
    stopAll: function (except = null) {
        // 1. Stop Drawing - Always stop if any active drawer exists, unless specifically excepted
        if (this.activeDrawer && except !== 'draw') {
             console.log("[AoTMapEditor] Stopping Active Drawer. Trace:");
             console.trace();
             this.activeDrawer.disable();
             this.activeDrawer = null;
             this.activeShape = null; // Reset
        }
        
        // 2. Stop Edit
        if (this.editEnabled && except !== 'edit') {
             this.toggleEdit(false);
        }
        
        // 3. Stop Delete
        if (this.deleteEnabled && except !== 'delete') {
             this.toggleDelete(false);
        }
        
        // Notify State Change (useful for UI active class updates)
        this._triggerStateChange(); 
    },

    /**
     * Start Drawing a Shape
     * @param {string} shape - 'polyline', 'polygon', 'rectangle', 'circle', 'marker'
     */
    startDraw: function (shape) {
        console.log(`[AoTMapEditor] startDraw(${shape}) triggered.`);
        // [Fix] Stop other modes first
        this.stopAll('draw');

        this.activeShape = shape; // Track active shape
        console.log(`[AoTMapEditor] activeShape set to: ${this.activeShape}`);


        let drawer = null;
        const options = {
            shapeOptions: this.styles[this.currentType] || {},
            repeatMode: false // [Fix] Force Single Draw Mode
        };

        if (shape === 'polyline') {
            // [Fix V11-Final] Enforce "Desktop Mode" for Mac/Trackpad stability.
            // map.tap is false, so we should sync draw.touch to false to avoid double-handling.
            options.touch = false; 
            
            // [Fix] Standard Intersection Rule
            options.allowIntersection = true;
            options.drawError = { color: '#e1e100', message: 'ERROR: Intersection' };
            options.guidelineDistance = 10;

            // [Fix V14] No Fill for Polylines (Ghost Polygon Fix)
            if (options.shapeOptions) {
                options.shapeOptions.fill = false;
            }
            
            // [Revert] clickTolerance removed (Default is 10/20). High values might cause premature 'finish' clicks.
            
            // [Fix V5] Disable DoubleClickZoom during Polyline Draw
            // Rapid touches on mobile can be interpreted as double-click, finishing the line early.
            if (this.map.doubleClickZoom.enabled()) {
                this._wasDoubleClickZoomEnabled = true;
                this.map.doubleClickZoom.disable();
            } else {
                this._wasDoubleClickZoomEnabled = false;
            }

            drawer = new L.Draw.Polyline(this.map, options);
            
            // [Fix V13] Debounce & Protection
            // 1. Double-Click Block: Prevent rapid clicks being interpreted as "Double Click to Finish".
            // 2. Click-Through Block: Prevent "Finish" from triggering immediately after "Add Vertex".
            //    This happens if the click that places the point also hits the new marker (ghost click/propagation).
            
            const originalAddVertex = drawer.addVertex;
            const originalFinish = drawer._finishShape;
            
            drawer.lastVertexTime = 0; // State tracking

            drawer.addVertex = function(latlng) {
                // Log for debug
                // console.log("[AoTMapEditor] addVertex called");
                this.lastVertexTime = Date.now();
                originalAddVertex.call(this, latlng);
            };

            drawer._finishShape = function(e) {
                // 1. Block DblClick
                if (e && e.type === 'dblclick') {
                    console.log("[AoTMapEditor] Blocking Double-Click Finish.");
                    return; 
                }
                
                // 2. Block Rapid Finish (Click-Through)
                // If trying to finish within 500ms of adding a vertex, assume it's an accident.
                const now = Date.now();
                if (this.lastVertexTime && (now - this.lastVertexTime < 500)) {
                    console.log(`[AoTMapEditor] Blocking Rapid Finish (Delta: ${now - this.lastVertexTime}ms). Assumed accidental click-through.`);
                    return;
                }

                originalFinish.apply(this, arguments);
            };
        }
        else if (shape === 'polygon') drawer = new L.Draw.Polygon(this.map, options);
        else if (shape === 'rectangle') drawer = new L.Draw.Rectangle(this.map, options);
        else if (shape === 'circle') drawer = new L.Draw.Circle(this.map, options);
        else if (shape === 'marker') drawer = new L.Draw.Marker(this.map, options);
        else if (shape === 'label') {
             // Use Marker drawer but we will handle it specially in Created event
             // or we can use a DivIcon here to show what we are placing
             drawer = new L.Draw.Marker(this.map, {
                 icon: L.divIcon({
                     className: 'label-preview-icon',
                     html: '<i class="fas fa-font"></i>',
                     iconSize: [20, 20]
                 }),
                 repeatMode: false
             });
             this.currentDrawingType = 'label'; // Track that we are drawing a label
        }

        if (drawer) {
            this.activeDrawer = drawer; // [Fix] Track active drawer
            
            // [Fix V11] Delay enable to prevent immediate event capture (e.g. from the button click)
            // and ensure cleaner state.
            setTimeout(() => {
                if (this.activeDrawer === drawer) { // Check if still active
                    drawer.enable();
                    this._triggerStateChange(); 
                }
            }, 50);
        }
    },

    /**
     * Toggle Edit Mode
     * @param {boolean|null} force 
     */
    toggleEdit: function (force = null) {
        // [Fix] Stop others if enabling
        const shouldEnable = (force !== null) ? force : !this.editEnabled;
        if (shouldEnable) {
             this.stopAll('edit');
        }

        if (!this.editHandler) {
            this.editHandler = new L.EditToolbar.Edit(this.map, { featureGroup: this.featureGroup });
        }

        if (shouldEnable) {
            this.editHandler.enable();
            this.editEnabled = true;
        } else {
            this.editHandler.disable();
            this.editEnabled = false;
        }

        // Notify UI (Custom Event)
        this._triggerStateChange();
    },

    /**
     * Toggle Delete Mode
     * @param {boolean|null} force 
     */
    toggleDelete: function (force = null) {
        // [Fix] Stop others if enabling
        const shouldEnable = (force !== null) ? force : !this.deleteEnabled;
        if (shouldEnable) {
             this.stopAll('delete');
        }

        if (!this.deleteHandler) {
            this.deleteHandler = new L.EditToolbar.Delete(this.map, { featureGroup: this.featureGroup });
        }

        if (shouldEnable) {
            this.deleteHandler.enable();
            this.deleteEnabled = true;
        } else {
            this.deleteHandler.disable();
            this.deleteEnabled = false;
        }

        this._triggerStateChange();
    },

    // --- Actions ---
    saveActions: function () {
        if (this.editEnabled && this.editHandler) {
            this.editHandler.save();
            this.editHandler.disable();
            this.editEnabled = false;
        }
        if (this.deleteEnabled && this.deleteHandler) {
            this.deleteHandler.save();
            this.deleteHandler.disable();
            this.deleteEnabled = false;
        }
        this._triggerStateChange();
    },

    cancelActions: function () {
        if (this.editEnabled && this.editHandler) {
            this.editHandler.revertLayers();
            this.editHandler.disable();
            this.editEnabled = false;
        }
        if (this.deleteEnabled && this.deleteHandler) {
            this.deleteHandler.revertLayers();
            this.deleteHandler.disable();
            this.deleteEnabled = false;
        }
        this._triggerStateChange();
    },

    markAllDeleted: function() {
        if (!this.deleteEnabled || !this.deleteHandler) return;
        
        // Use getLayers() to create a snapshot Array.
        // Iterating featureGroup directly while removing layers causes skipping.
        const layers = this.featureGroup.getLayers();
        
        layers.forEach(layer => {
            if (this.deleteHandler._removeLayer) {
                // Mock an event object as Leaflet.Draw expects { target: layer }
                this.deleteHandler._removeLayer({ target: layer });
            }
        });
        this._triggerStateChange();
    },

    /**
     * Apply Style based on properties
     * @param {L.Layer} layer 
     * @param {string} type 
     */
    applyStyle: function (layer, type) {
        if (this.styles[type] && layer.setStyle) {
            layer.setStyle(this.styles[type]);
        }
    },

    /**
     * Clear All Features
     */
    clear: function () {
        this.featureGroup.clearLayers();
    },

    /**
     * Internal Event Binding
     */
    _bindEvents: function () {
        this.map.on(L.Draw.Event.CREATED, (e) => {
            const layer = e.layer;
            const type = this.currentType;

            // Save Metadata
            layer.feature = layer.feature || {};
            layer.feature.type = 'Feature';
            layer.feature.properties = layer.feature.properties || {};
            layer.feature.properties.aot_type = layer.feature.properties.aot_type || type;
            if (!layer.feature.properties.name) {
                layer.feature.properties.name = 'New ' + type; // Default Name
            }

            // Apply Style
            this.applyStyle(layer, type);

            // Add to Group
            this.featureGroup.addLayer(layer);
 
            // Notify Creation
            // console.log(`[AoTMapEditor] Created ${type}`, layer);
            
            // Dispatch Custom Event for external hooks (e.g. Turf calculation in Design)
            const event = new CustomEvent('aot:editor:created', {
                detail: { 
                    layer: layer, 
                    type: e.layerType, 
                    aotType: type,
                    drawingType: this.currentDrawingType || e.layerType 
                }
            });
            window.dispatchEvent(event);
            
            this.currentDrawingType = null; // Reset
        });

        // [Fix] Reset active state when drawing stops (e.g. finished or escaped)
        this.map.on(L.Draw.Event.DRAWSTOP, (e) => {
            // console.log("[AoTMapEditor] Draw Stopped");
            // [Fix V5] Restore DoubleClickZoom state
            if (this._wasDoubleClickZoomEnabled) {
                this.map.doubleClickZoom.enable();
                this._wasDoubleClickZoomEnabled = false; // Reset
            }

            this.activeShape = null;
            this.activeDrawer = null;
            this._triggerStateChange(); // Notify UI to update buttons
        });
    },

    _triggerStateChange: function () {
        const event = new CustomEvent('aot:editor:state', {
            detail: { 
                edit: this.editEnabled, 
                delete: this.deleteEnabled,
                activeShape: this.activeShape // [Fix] Expose active shape for UI Sync
            }
        });
        window.dispatchEvent(event);
    }
};

window.AoTMapEditor = AoTMapEditor;
