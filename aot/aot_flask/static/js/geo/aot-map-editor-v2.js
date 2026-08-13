/**
 * aot-map-editor-v2.js
 * Design & Editor Module using MapLibre Draw (AoTDrawManager)
 * Handles drawing, styling, and managing features (shapes).
 * 
 * Migrated from Leaflet.Draw to MapLibre Draw for vector map support.
 */

const AoTMapEditor = {
    map: null,                    // MapLibre map instance
    featureGroup: null,           // Feature collection for storage
    drawManager: null,            // AoTDrawManager instance
    editEnabled: false,
    deleteEnabled: false,
    activeShape: null,            // Track active shape name for toggle UI

    // State
    currentType: 'site',          // site, zone, facility, equipment, aot_device
    currentDrawingType: null,     // Track drawing type (label, etc.)
    
    // Flag to track if double click zoom was disabled during polyline draw
    _wasDoubleClickZoomEnabled: false,

    // Styles
    styles: {
        site: { color: '#DF5353', weight: 4, fill: false },                    // Red (User Theme)
        zone: { color: '#28a745', weight: 2, fill: false, dashArray: '5,5' },  // Green Dashed
        facility: { color: '#82898f', weight: 3, fill: true, fillOpacity: 0.2 }, // Grey (Infrastructure)
        equipment: { color: '#007bff', weight: 3, fill: true, fillOpacity: 0.2 }, // Blue (Water/System)
        aot_device: { color: '#995aff', weight: 2, fill: true, fillOpacity: 0.5 }, // Purple (AoT)
        reference: { color: '#ff00ff', weight: 4, dashArray: '10, 10', fill: false, opacity: 1.0 } // Magenta Dashed (Reference)
    },

    /**
     * Initialize Editor
     * @param {maplibregl.Map} map - MapLibre map instance
     * @param {Object} featureGroup - Feature group (or FeatureCollection) for storing features
     */
    init: function(map, featureGroup) {
        this.map = map;
        this.featureGroup = featureGroup;

        // Check if any DrawManager is available
        const hasDrawManager =
            typeof AoTDrawManager !== 'undefined' ||
            typeof AoTMapLibreDrawManager !== 'undefined' ||
            typeof MapLibreDraw !== 'undefined';

        if (!hasDrawManager) {
            console.error('[AoTMapEditor] No DrawManager loaded. Please include maplibre-draw.js');
            return;
        }

        // 1. Apply Theme Config
        this._applyThemeConfig();

        // 2. Initialize DrawManager
        this._initDrawManager();

        // 3. Bind events
        this._bindEvents();

    },

    /**
     * Initialize AoTDrawManager
     * @private
     */
    _initDrawManager: function() {
        // Get current style color for the current type
        const currentStyle = this.styles[this.currentType] || { color: '#995aff' };

        // Create draw manager instance - prefer native MapLibreDraw
        const DrawManagerClass = window.AoTMapLibreDrawManager || window.AoTDrawManager || window.MapLibreDraw;

        if (!DrawManagerClass) {
            console.error('[AoTMapEditor] No DrawManager available. Please include maplibre-draw.js');
            return;
        }

        // Options for draw manager
        const options = {
            color: currentStyle.color,
            fill: currentStyle.fill !== false,
            fillOpacity: currentStyle.fillOpacity || 0.2,
            lineWidth: currentStyle.weight || 2,
            polyline: true,
            polygon: true,
            rectangle: true,
            circle: true,
            marker: true,
            trash: true
        };

        // Check for static getDefault factory method
        if (typeof DrawManagerClass.getDefault === 'function') {
            // Use factory method
            this.drawManager = DrawManagerClass.getDefault(this.map, options);
        } else {
            // Direct constructor
            this.drawManager = new DrawManagerClass(this.map, options);
            
            // Call init if exists (instance method, not static)
            if (typeof this.drawManager.init === 'function') {
                this.drawManager.init();
            }
        }

        // Add feature group for layer storage
        this.layers = new Map();

        // Bind draw manager events to editor events
        if (this.drawManager) {
            this.drawManager.on('create', (data) => this._onDrawCreated(data.feature || data));
            this.drawManager.on('edit', (data) => this._onDrawEdited(data.features || [data]));
            this.drawManager.on('delete', (data) => this._onDrawDeleted(data.features || [data]));
            this.drawManager.on('modechange', (data) => {
                if (data.mode === 'simple_select') {
                    this.activeShape = null;
                    this.currentDrawingType = null;
                    if (this._wasDoubleClickZoomEnabled) {
                        this.map.doubleClickZoom.enable();
                        this._wasDoubleClickZoomEnabled = false;
                    }
                    this._triggerStateChange();
                }
            });
        }

    },

    _applyThemeConfig: function() {
        // 그리는 중의 기본 스타일. 이 파일은 번들 밖에서 먼저 로드되지만 이
        // 함수는 호출 시점에 참조하므로 헬퍼가 이미 올라와 있다(방어적 가드 유지).
        const T = window.AoTGeoTheme;
        if (!T) return;

        // 새 도형은 아직 장치 종류를 모른다 — 장치 공통색으로 그리고, 장치에
        // 연결되는 순간 종류별 색으로 다시 칠해진다(aot-geo-modules.js).
        const updateColor = (type, colorKey) => {
            if (this.styles[type]) {
                this.styles[type].color = T.color(colorKey);
            }
        };

        updateColor('site', 'site');
        updateColor('zone', 'zone');
        updateColor('facility', 'facility');
        updateColor('equipment', 'equipment');
        updateColor('aot_device', 'device');
    },

    /**
     * Set Current Drawing Type
     * @param {string} type - Drawing type (site, zone, facility, equipment, aot_device)
     */
    setType: function(type) {
        this.currentType = type;
        
        // Update draw manager style
        if (this.drawManager) {
            const style = this.styles[type] || { color: '#995aff' };
            this.drawManager.setStyle({
                color: style.color,
                fillColor: style.fill !== false ? style.color : 'transparent',
                fillOpacity: style.fillOpacity || 0.2,
                weight: style.weight || 2
            });
        }
        
        this._triggerStateChange();
    },

    /**
     * Stop All Active Tools (Draw/Edit/Delete)
     * Enforces mutual exclusivity.
     * @param {string} except - Tool to keep active ('draw', 'edit', 'delete')
     */
    stopAll: function(except = null) {
        // 1. Stop Drawing
        if (this.activeShape && except !== 'draw') {
            if (this.drawManager) {
                this.drawManager.disableDraw();
            }
            this.activeShape = null;
            this.currentDrawingType = null;
            
            // Restore DoubleClickZoom if it was disabled for polyline
            if (this._wasDoubleClickZoomEnabled) {
                this.map.doubleClickZoom.enable();
                this._wasDoubleClickZoomEnabled = false;
            }
        }
        
        // 2. Stop Edit
        if (this.editEnabled && except !== 'edit') {
            this.toggleEdit(false);
        }
        
        // 3. Stop Delete
        if (this.deleteEnabled && except !== 'delete') {
            this.toggleDelete(false);
        }
        
        this._triggerStateChange();
    },

    /**
     * Start Drawing a Shape
     * @param {string} shape - 'polyline', 'polygon', 'rectangle', 'circle', 'marker', 'label'
     */
    startDraw: function(shape) {
        console.log(`[AoTMapEditor] startDraw(${shape}) triggered.`);
        
        // Stop other modes first
        this.stopAll('draw');

        // DrawManager 검사가 **activeShape 설정보다 먼저**여야 한다.
        //
        // 순서가 반대면 초기화 전에 도구를 누른 사용자가 영구히 그릴 수 없게
        // 된다: activeShape 만 설정된 채 return 하므로 버튼은 켜진 것처럼
        // 보이는데 drawManager 의 _currentDrawType 은 null 이고, 그 다음부터는
        // 툴바의 토글 로직(activeShape === shape → stopAll)이 매번 "취소"로
        // 해석해 다시 시작되지 않는다. 콘솔 에러 한 줄 말고는 아무 표시도 없다.
        // 페이지 로드 직후 몇 초 안에 도구를 누르면 실제로 재현된다.
        if (!this.drawManager) {
            console.error('[AoTMapEditor] DrawManager not initialized');
            if (window.showToast) {
                window.showToast(
                    (window._ ? window._('Map is still loading. Try again in a moment.')
                              : 'Map is still loading. Try again in a moment.'),
                    'warning');
            }
            return;
        }

        this.activeShape = shape;
        this.currentDrawingType = shape === 'label' ? 'label' : null;
        console.log(`[AoTMapEditor] activeShape set to: ${this.activeShape}`);

        // Disable double click zoom for polyline (prevents premature finish)
        if (shape === 'polyline') {
            // MapLibre uses handler.isEnabled(), Leaflet uses handler.enabled()
            const dzoom = this.map.doubleClickZoom;
            const isEnabled = dzoom
                ? (typeof dzoom.isEnabled === 'function' ? dzoom.isEnabled()
                  : typeof dzoom.enabled === 'function' ? dzoom.enabled()
                  : true)
                : false;
            this._wasDoubleClickZoomEnabled = isEnabled;
            if (isEnabled && dzoom && dzoom.disable) dzoom.disable();
        }

        // Enable appropriate draw mode
        switch (shape) {
            case 'polyline':
                this.drawManager.enablePolyline();
                break;
            case 'polygon':
                this.drawManager.enablePolygon();
                break;
            case 'rectangle':
                this.drawManager.enableRectangle();
                break;
            case 'circle':
                this.drawManager.enableCircle();
                break;
            case 'marker':
            case 'label':
                this.drawManager.enableMarker();
                break;
            default:
                console.warn('[AoTMapEditor] Unknown shape:', shape);
                return;
        }

        this._triggerStateChange();
    },

    /**
     * Toggle Edit Mode
     * @param {boolean|null} force - Force enable/disable
     */
    toggleEdit: function(force = null) {
        const shouldEnable = (force !== null) ? force : !this.editEnabled;
        
        if (shouldEnable) {
            this.stopAll('edit');
        }

        if (shouldEnable) {
            if (this.drawManager) this.drawManager.enableEdit();
            this.editEnabled = true;
        } else {
            if (this.drawManager && this.drawManager.disableEdit) this.drawManager.disableEdit();
            this.editEnabled = false;
        }

        this._triggerStateChange();
    },

    /**
     * Toggle Delete Mode
     * @param {boolean|null} force - Force enable/disable
     */
    toggleDelete: function(force = null) {
        const shouldEnable = (force !== null) ? force : !this.deleteEnabled;

        if (shouldEnable) {
            this.stopAll('delete');
        }

        if (shouldEnable) {
            if (this.drawManager) this.drawManager.enableDelete();
            this.deleteEnabled = true;
            this._pendingDeletes = []; // start fresh snapshot for this session
        } else {
            if (this.drawManager && this.drawManager.disableDelete) this.drawManager.disableDelete();
            this.deleteEnabled = false;
        }

        this._triggerStateChange();
    },

    // --- Actions ---

    /**
     * Save Edit/Delete Actions — commit changes and exit mode
     *
     * IMPORTANT: must use isAutoSave=false (full save), NOT delta save.
     * Delta save relies on dirtyNodeIds/deletedNodeIds which may already be
     * cleared by auto-saves triggered during the edit/delete session.
     * Full save sends ALL current features for the affected types — deleted
     * features are absent → backend removes them; edited features carry the
     * updated geometry → backend upserts them.
     */
    saveActions: function() {
        if (this.editEnabled) {
            if (this.drawManager && this.drawManager.disableEdit) this.drawManager.disableEdit();
            this.editEnabled = false;
        }
        if (this.deleteEnabled) {
            if (this.drawManager && this.drawManager.disableDelete) this.drawManager.disableDelete();
            this.deleteEnabled = false;
            this._pendingDeletes = []; // commit — discard the snapshot
        }
        this._triggerStateChange();
        if (window.geoDesign && typeof window.geoDesign.saveDesign === 'function') {
            // Full save (isAutoSave=false): sends complete current state to backend.
            // targetTypes=null → syncs all types, guaranteeing deletions and edits persist
            // regardless of whether delta-save auto-saves already ran mid-session.
            window.geoDesign.saveDesign(null, false);
        }
    },

    /**
     * Cancel Edit/Delete Actions — revert edits, exit mode
     */
    cancelActions: function() {
        if (this.editEnabled) {
            // Revert: restore original feature geometry stored at selection time
            const dm = this.drawManager;
            if (dm && dm._editState && dm._editState.origFeature && dm._editState.selectedLayer) {
                const orig = JSON.parse(dm._editState.origFeature);
                const layer = dm._editState.selectedLayer;
                layer.feature = orig;
                // Polyline (pipe) renders via shared RenderBucket — revert through bucket
                if (layer._aotType === 'Polyline' && layer._getBucketCategory) {
                    try {
                        const category = layer._getBucketCategory();
                        const bucket = window.RenderBucket && window.RenderBucket.get(layer._map, category);
                        if (bucket) bucket.upsert(layer._layerId, layer._toBucketGeoJSON ? layer._toBucketGeoJSON() : orig);
                    } catch(e) {}
                    // Also revert the outline highlight source if present
                    try {
                        if (dm.map && dm.map.getSource('_aot-edit-select-outline-src')) {
                            dm.map.getSource('_aot-edit-select-outline-src').setData(orig);
                        }
                    } catch(e) {}
                } else {
                    const srcId = 'aot-source-' + layer._layerId;
                    try {
                        if (dm.map && dm.map.getSource(srcId)) dm.map.getSource(srcId).setData(orig);
                    } catch(e) {}
                }
                // Also clear dirtyNodeIds for this feature so auto-save doesn't re-save old geometry
                const nid = orig.properties && (orig.properties.node_id || orig.properties.db_id);
                if (nid && window.geoDesign && window.geoDesign.dirtyNodeIds) {
                    window.geoDesign.dirtyNodeIds.delete(nid);
                }
            }
            if (dm && dm.disableEdit) dm.disableEdit();
            this.editEnabled = false;
        }
        if (this.deleteEnabled) {
            if (this.drawManager && this.drawManager.disableDelete) this.drawManager.disableDelete();
            this.deleteEnabled = false;

            const design = window.geoDesign;

            // Restore layers deleted during this session (buffered, not yet saved to server)
            if (this._pendingDeletes && this._pendingDeletes.length > 0 && design) {
                this._pendingDeletes.forEach(({ layer, nid }) => {
                    // Remove from deletion queue so they're not sent to server
                    if (nid) design.deletedNodeIds.delete(nid);
                    // [Fix] Also clear from deferred aot_device delete set (cancel must fully undo)
                    if (nid && design._deferredAotDeviceNids) design._deferredAotDeviceNids.delete(nid);
                    // Re-add to featureGroup (triggers addTo → re-creates GL source/layer)
                    if (this.featureGroup && this.featureGroup.addLayer) this.featureGroup.addLayer(layer);
                    // Re-add to correct layerStorage group
                    const aotType = layer.feature?.properties?.aot_type;
                    if (aotType && design.layerStorage && design.layerStorage[aotType]) {
                        design.layerStorage[aotType].addLayer(layer);
                    }
                });
                this._pendingDeletes = [];
            }

            // Restore label_aux layers that were moved to featureGroup when delete mode started
            if (design && design.layerStorage && design.layerStorage['label_aux'] && this.featureGroup) {
                const toRestore = [];
                this.featureGroup.eachLayer(l => {
                    if (l.feature?.properties?.aot_type === 'label_aux') toRestore.push(l);
                });
                toRestore.forEach(l => {
                    this.featureGroup.removeLayer(l);
                    design.layerStorage['label_aux'].addLayer(l);
                });
            }
        }
        this._triggerStateChange();
    },

    /**
     * Delete all features in featureGroup (Clear All)
     */
    markAllDeleted: function() {
        if (!this.deleteEnabled) return;
        if (!this.featureGroup) return;
        const layers = this.featureGroup.layers ? [...this.featureGroup.layers] : [];
        const dm = this.drawManager;
        layers.forEach(layer => {
            if (!layer || !layer._layerId) return;
            const mlId = layer._layerId;
            const srcId = 'aot-source-' + mlId;
            try {
                if (dm && dm.map) {
                    if (dm.map.getLayer(mlId))  dm.map.removeLayer(mlId);
                    if (dm.map.getSource(srcId)) dm.map.removeSource(srcId);
                }
            } catch(e) {}
            this.featureGroup.removeLayer(layer);
            if (layer.feature && layer.feature.id) this.layers.delete(layer.feature.id);
            // Fire per-layer delete event
            if (dm) dm._onDrawDelete([layer.feature || { id: mlId, type: 'Feature', geometry: null, properties: {} }]);
        });
        this._triggerStateChange();
    },

    /**
     * Apply Style based on type
     * @param {Object} layer - Layer object
     * @param {string} type - Feature type
     */
    applyStyle: function(layer, type) {
        const style = this.styles[type] || this.styles.site;
        if (layer.setStyle) {
            layer.setStyle(style);
        }
    },

    /**
     * Clear All Features
     */
    clear: function() {
        if (this.drawManager) {
            if (this.drawManager.clearAll) {
                this.drawManager.clearAll();
            } else if (this.drawManager.deleteAll) {
                this.drawManager.deleteAll();
            }
        }
        if (this.layers) {
            this.layers.clear();
        }
        // Reset featureGroup reference array only — GL layer cleanup is the caller's
        // responsibility (via _clearLayers / resetDesign) to avoid removing GL layers
        // that are still owned by storageGroup during a mode switch.
        if (this.featureGroup) {
            this.featureGroup.layers = [];
        }
    },

    /**
     * Get All Features as GeoJSON
     * @returns {Object} GeoJSON FeatureCollection
     */
    getGeoJSON: function() {
        if (this.drawManager) {
            return this.drawManager.getGeoJSON();
        }
        return { type: 'FeatureCollection', features: [] };
    },

    /**
     * Load Features from GeoJSON
     * @param {Object|string} geojson - GeoJSON data
     */
    loadGeoJSON: function(geojson) {
        if (this.drawManager) {
            if (typeof geojson === 'string') {
                geojson = JSON.parse(geojson);
            }
            this.drawManager.addGeoJSON(geojson);
        }
    },

    /**
     * Internal Event Binding
     * @private
     */
    _bindEvents: function() {
        // Listen for state changes from draw manager
        this.map.on('draw:selectionchange', (e) => {
            // Selection change handling
        });

        // Listen for map drawstop (Escape key, etc.)
        this.map.on('draw.modechange', (e) => {
            if (e.mode === 'simple_select') {
                this.activeShape = null;
                this.currentDrawingType = null;
                
                // Restore DoubleClickZoom
                if (this._wasDoubleClickZoomEnabled) {
                    this.map.doubleClickZoom.enable();
                    this._wasDoubleClickZoomEnabled = false;
                }
                
                this._triggerStateChange();
            }
        });
    },

    /**
     * Handle draw created event from DrawManager
     * @private
     */
    _onDrawCreated: function(feature) {
        const type = this.currentType;

        // Ensure feature has top-level id
        if (!feature.id) {
            feature.id = feature.properties?.id || ('drawn-' + Date.now());
        }
        feature.properties = feature.properties || {};
        feature.properties.aot_type = type;

        // Create a proper AoTGeoLayer so _onShapeCreated can render it
        let layer = null;
        if (window.AoTGeoLayer && window.AoTGeoLayer.fromGeoJSON) {
            const layers = window.AoTGeoLayer.fromGeoJSON(feature);
            layer = layers && layers[0];
        }

        // Fallback wrapper if AoTGeoLayer unavailable
        if (!layer) {
            layer = {
                feature: feature,
                toGeoJSON: () => feature,
                setStyle: (style) => { feature.properties.style = style; }
            };
        }
        layer.feature = feature;

        this.applyStyle(layer, type);
        if (feature.id) this.layers.set(feature.id, layer);

        const geomType = feature.geometry ? feature.geometry.type : 'Polygon';
        const drawType = feature.properties.drawType ||
            (geomType === 'LineString' ? 'polyline' : geomType === 'Point' ? 'marker' : 'polygon');

        // Fire draw:created BEFORE adding to featureGroup so that aot-geo-events.js →
        // modules.js.onShapeCreated can set sub_type and route to the correct storage
        // group (pipe-main / pipe-branch bucket).  Adding to featureGroup first would
        // render the layer in the wrong 'line-generic' bucket before sub_type is known.
        this.map.fire('draw:created', { layer, layerType: drawType });

        // Fallback: if no storage group claimed the layer (e.g. unknown aot_type or
        // modules.js not loaded), render via featureGroup so the shape is never invisible.
        const _inStorage = this.layerStorage &&
            Object.values(this.layerStorage).some(
                g => g && typeof g.hasLayer === 'function' && g.hasLayer(layer));
        if (!_inStorage && this.featureGroup) {
            this.featureGroup.addLayer(layer);
        }

        // aot:editor:created → aot-geo-design-v3.js listener (for device color etc.)
        window.dispatchEvent(new CustomEvent('aot:editor:created', {
            detail: { layer, type: geomType, aotType: type,
                      drawingType: this.currentDrawingType || drawType, feature }
        }));

        this.currentDrawingType = null;
        console.log(`[AoTMapEditor] Created ${type}:`, feature.id);
    },

    /**
     * Handle draw edited event from AoTDrawManager
     * @private
     */
    _onDrawEdited: function(features) {
        const editedFeatures = Array.isArray(features) ? features : (features.features || [features]);

        // Resolve raw GeoJSON features → actual layer objects so aot-geo-events.js
        // draw:edited handler gets full layer objects (needed for updateMeasurementLabels,
        // updatePipeLabels, detectAndHandleConnections, processPipeTrimming, etc.)
        const layerList = [];
        editedFeatures.forEach(f => {
            if (!f) return;
            let layer = null;
            // 1. Check editor's own layer map (layers created this session)
            if (f.id) layer = this.layers.get(f.id);
            // 2. Search all layerStorage groups (server-loaded layers)
            if (!layer && this.layerStorage) {
                const node_id = f.properties && f.properties.node_id;
                for (const group of Object.values(this.layerStorage)) {
                    if (!group || typeof group.eachLayer !== 'function') continue;
                    group.eachLayer(l => {
                        if (layer) return;
                        if (!l || !l.feature) return;
                        if ((f.id && l.feature.id === f.id) ||
                            (node_id && l.feature.properties && l.feature.properties.node_id === node_id)) {
                            layer = l;
                        }
                    });
                    if (layer) break;
                }
            }
            if (layer) layerList.push(layer);
        });

        // Fire draw:edited on map → aot-geo-events.js (labels, connections, pipe trimming, save)
        if (layerList.length > 0) {
            const layersShim = { eachLayer: (fn) => layerList.forEach(fn) };
            this.map.fire('draw:edited', { layers: layersShim });
        }

        // Dispatch window event for design-v3.js save hook
        window.dispatchEvent(new CustomEvent('aot:editor:edited', {
            detail: { layers: editedFeatures, features: editedFeatures }
        }));

        console.log('[AoTMapEditor] Edited features:', editedFeatures.length);
    },

    /**
     * Handle draw deleted event from DrawManager
     * @private
     */
    _onDrawDeleted: function(features) {
        const deletedFeatures = Array.isArray(features) ? features : (features.features || [features]);

        // Remove from layer storage
        deletedFeatures.forEach(feature => {
            if (feature && feature.id) {
                this.layers.delete(feature.id);
            }
        });

        // Dispatch Custom Event for external hooks
        const event = new CustomEvent('aot:editor:deleted', {
            detail: {
                layers: deletedFeatures,
                features: deletedFeatures
            }
        });
        window.dispatchEvent(event);

        console.log('[AoTMapEditor] Deleted features:', deletedFeatures.length);
    },

    /**
     * Trigger state change event for UI updates
     * @private
     */
    _triggerStateChange: function() {
        const event = new CustomEvent('aot:editor:state', {
            detail: {
                edit: this.editEnabled,
                delete: this.deleteEnabled,
                activeShape: this.activeShape,
                currentType: this.currentType
            }
        });
        window.dispatchEvent(event);
    }
};

// Leaflet.Draw compatibility shim (for code that still references L.Draw.*)
if (typeof L !== 'undefined') {
    L.Draw = L.Draw || {};
    L.Draw.Event = L.Draw.Event || {
        CREATED: 'draw:created',
        EDITED: 'draw:edited',
        DELETED: 'draw:deleted',
        DRAWSTART: 'draw:drawstart',
        DRAWSTOP: 'draw:drawstop',
        EDITSTART: 'draw:editstart',
        EDITSTOP: 'draw:editstop'
    };
    
    // Compatibility: L.EditToolbar
    L.EditToolbar = L.EditToolbar || {};
    L.EditToolbar.Edit = function() { 
        return { 
            enable: () => {}, 
            disable: () => {}, 
            save: () => {}, 
            revertLayers: () => {} 
        }; 
    };
    L.EditToolbar.Delete = function() { 
        return { 
            enable: () => {}, 
            disable: () => {}, 
            save: () => {}, 
            revertLayers: () => {} 
        }; 
    };
}

window.AoTMapEditor = AoTMapEditor;
