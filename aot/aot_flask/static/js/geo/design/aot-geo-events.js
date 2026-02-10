/**
 * aot-geo-events.js
 * Event Binding and Handling for AoTGeoDesign
 */

class AoTGeoEvents {
    constructor(parent) {
        this.parent = parent;
    }

    /**
     * Bind All Main Map and UI Events
     */
    bindEvents() {
        // console.log("[AoTGeoEvents] Binding Events...");
        const p = this.parent;

        // Mode Switching
        // Mode Switching
        // [Legacy] Removed - Handled by AoTGeoPanel internal binding (data-nav-mode)
        // document.querySelectorAll('.mode-tab').forEach(tab => { ... });

        // Initialize Equipment Sub-Tabs
        // [Legacy] Removed - Handled by AoTGeoPanel dynamic rendering
        // p._initEquipmentSubTabs();
        // p._initDeviceSubTabs();

        // Auto Save View State (Debounced)
        p.debouncedSave = p._debounce(p._autoSaveState, 1000);
        p.map.on('moveend zoomend overlayadd overlayremove', () => p.debouncedSave());

        // External Map Tools
        const bindIfExists = (id, handler) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('click', handler);
        };

        bindIfExists('tool-zoom-in', () => p.map.zoomIn());
        bindIfExists('tool-zoom-out', () => p.map.zoomOut());

        // Location Tools
        bindIfExists('tool-fullscreen', () => {
            const el = document.getElementById('geo-design-wrapper');
            if (!document.fullscreenElement) {
                el.requestFullscreen().catch(err => { /* console.error(err); */ });
            } else {
                document.exitFullscreen();
            }
        });
        // bindIfExists('tool-search', () => {
        //     const overlay = document.getElementById('search-overlay');
        //     if (overlay) overlay.classList.toggle('d-none');
        // });
        bindIfExists('tool-locate', () => p.map.locate({ setView: true, maxZoom: 16 }));
        bindIfExists('tool-reset', () => {
            const bounds = window.AoTMapEditor.featureGroup.getBounds();
            if (bounds.isValid()) p.map.fitBounds(bounds, { padding: [50, 50] });
            else p.map.setView([36.5, 127.5], 7);
        });

        // Toggle Tools
        bindIfExists('tool-lock', () => p.toggleLock());
        bindIfExists('tool-hide', () => p.toggleHide());
        bindIfExists('tool-site-list', () => p.ui.toggleSiteList());

        // Save
        const saveGlobal = document.getElementById('btn-save-global');
        if (saveGlobal) saveGlobal.addEventListener('click', () => p.saveDesign());

        // Map Selector (Dropdown)
        $('#map-selector').on('changed.bs.select', (e, clickedIndex, isSelected, previousValue) => {
            const val = $(e.target).val();
            if (val === 'new') {
                p.resetDesign();
                // [New] Trigger immediate creation
                p.ui.showToast(_('creating_new_map'), 'info');
                p.saveDesign(); // Will redirect upon completion
            } else if (val) {
                p.loadMap(val);
                $('#btn-edit-map-name').removeClass('d-none');
                $('#btn-delete-map').show();
            } else {
                $('#btn-delete-map').hide();
            }
        });

        // Delete Map Button
        $('#btn-delete-map').on('click', () => {
            if (p.currentMapUuid && confirm(_('confirm_delete_map'))) {
                p.deleteMap(p.currentMapUuid);
            }
        });

        // Edit Name Button
        $('#btn-edit-map-name').on('click', () => {
            const newName = prompt(_('enter_new_map_name'), p.currentMapName);
            if (newName && newName.trim() !== "") {
                const finalName = newName.trim();
                if (!p.currentMapUuid) {
                    this.parent.ui.showToast(_('unsaved_map_warning'), 'warning');
                    return;
                }
                window.AoTMapData.saveMapDesign(p.currentMapUuid, finalName, {})
                    .then(res => {
                        if (res.ok) {
                            p.currentMapName = finalName;
                            p.lastLoadedName = finalName;
                            const sel = $('#map-selector');
                            const opt = sel.find(`option[value="${p.currentMapUuid}"]`);
                            if (opt.length) opt.text(finalName);
                            sel.selectpicker('refresh');
                        } else {
                            this.parent.ui.showToast(_('rename_failed') + ": " + (res.message || "Unknown Error"), 'error');
                        }
                    })
                    .catch(err => {
                        // console.error("Rename Error:", err);
                        // console.error(err);
                        this.parent.ui.showToast(_('rename_error'), 'error');
                    });
            }
        });

        // Data Export Buttons


        // Map Background Click
        p.map.on('click', (e) => {
            // [Fix] Deactivate Active Device if clicked on empty space
            // [Fix] Block deactivation if drawing/editing is in progress (prevents Polygon clicks from canceling device mode)
            
            // [Fix V11] Robust Drawing Detection
            // Check activeShape, activeDrawer, edit/delete modes, AND Leaflet.Draw internal state (checking for toolbar actions or if map has drawing class)
            let isDrawing = window.AoTMapEditor && (
                window.AoTMapEditor.activeShape || 
                window.AoTMapEditor.activeDrawer || 
                window.AoTMapEditor.editEnabled || 
                window.AoTMapEditor.deleteEnabled
            );
            
            // Fallback: Check if activeDrawer is actually present on map or enabled
            if (window.AoTMapEditor && window.AoTMapEditor.activeDrawer && window.AoTMapEditor.activeDrawer._enabled) {
                isDrawing = true;
            }
            
            console.log(`[GeoEvents] Map Click Detected. isDrawing: ${isDrawing}, activeLayer: ${p.activeLayer ? 'Yes' : 'No'}, Locked: ${p.isLocked}`);

            if (p.activeLayer && !p.isLocked && !isDrawing) {
                console.log("[GeoEvents] Resetting active layer due to map click.");
                p._resetActiveLayer();
            }
            
            if (!isDrawing && p.devices && p.devices.activeDevice) {
                console.log("[GeoEvents] Deactivating device due to map click.");
                p.devices.deactivateDevice();
            }
        });

        // Editor Sync
        p.map.on('draw:created', (e) => {
            console.log("[GeoEvent] draw:created triggered. Type:", e.layerType);
            p._onShapeCreated(e.layer, p.activeMode, e.layerType);
        });
        
        // [Fix] Geoman Support (pm:create)
        p.map.on('pm:create', (e) => {
             // console.log("[GeoEvent] pm:create triggered");
             // Geoman structure: e.layer, e.shape
             p._onShapeCreated(e.layer, p.activeMode, e.shape);
        });

        p.map.on('draw:edited', (e) => {
            const editedLayers = e.layers;
            const modifiedTypes = new Set();
            editedLayers.eachLayer((layer) => {
                if (p.geometry) p.geometry.updateMeasurementLabels(layer);
                if (p.geometry) {
                    p.geometry.updatePipeLabels(layer);
                    p.geometry.detectAndHandleConnections(layer);
                }
                const t = layer.feature?.properties?.aot_type;
                const nid = layer.feature?.properties?.node_id;
                if (t) modifiedTypes.add(t);
                if (nid) p.dirtyNodeIds.add(nid);
            });
            if (p.geometry) p.geometry.recalculateSpatialRelationships();
            if (modifiedTypes.has('equipment')) {
                window.AoTMapEditor.featureGroup.eachLayer(l => {
                    if (l.feature?.properties?.sub_type === 'pipe_main') {
                        if (p.geometry) p.geometry.processPipeTrimming(l);
                    }
                });
            }
            p.saveDesign(Array.from(modifiedTypes), true);
            p.updateDesignInfo();

            // [Auto-Regen] If Main Pipe is Moved, Re-generate Branches
            if (modifiedTypes.has('equipment')) {
                // Find edited main pipe
                let mainPipe = null;
                editedLayers.eachLayer(l => {
                    if (l.feature?.properties?.sub_type === 'pipe_main') mainPipe = l;
                });

                if (mainPipe && p.modules && p.modules.generatePipes) {
                    // [V17 Fix] Anti-Recursion: Only trigger if not already regenerating
                    if (p._isAutoRegenerating) return;

                    // Find parent Zone/Site
                    const mainGeo = mainPipe.toGeoJSON();
                    const center = window.turf.center(mainGeo);
                    
                    let parentZone = null;
                    const findParent = (group) => {
                        if (!group || parentZone) return;
                        group.eachLayer(l => {
                            if (parentZone) return;
                            if (l.feature?.properties?.gen_config_pipe) { // Must have config
                                const poly = l.toGeoJSON();
                                if (window.turf.booleanPointInPolygon(center, poly)) {
                                    parentZone = l.feature; // Use feature for generation
                                }
                            }
                        });
                    };
                    if (p.layerStorage['zone']) findParent(p.layerStorage['zone']);
                    if (p.layerStorage['site']) findParent(p.layerStorage['site']);

                    if (parentZone) {
                        const config = parentZone.properties.gen_config_pipe;
                        
                        // [V9 Fix] Conditional Regen: Only if connected branches exist
                        const mainNodeId = mainPipe.feature.properties.node_id;
                        let hasConnectedBranches = false;
                        
                        // Scan equipment for connected branches
                        if (p.layerStorage['equipment']) {
                            p.layerStorage['equipment'].eachLayer(l => {
                                if (l.feature?.properties?.sub_type === 'pipe_branch' && 
                                    l.feature?.properties?.connected_main_id === mainNodeId) {
                                    hasConnectedBranches = true;
                                }
                            });
                        }

                        if (hasConnectedBranches) {
                            p._isAutoRegenerating = true;
                            setTimeout(() => {
                                p.modules.generatePipes(parentZone, config);
                                setTimeout(() => { p._isAutoRegenerating = false; }, 1000); // Cooldown
                            }, 300);
                        }
                    }
                }
            }
        });

        p.map.on('draw:deleted', (e) => {
            const deletedLayers = e.layers;
            const deletedTypes = new Set();
            let pipeDeleted = false;

            deletedLayers.eachLayer((l) => {
                const props = l.feature?.properties;
                const t = props?.aot_type;
                const s = props?.sub_type;
                const nid = props?.node_id;
                const dbid = props?.db_id;

                if (t) deletedTypes.add(t);
                if (nid) p.deletedNodeIds.add(nid);
                else if (dbid) p.deletedNodeIds.add(dbid); 

                // [Fix] Deletion Persistence: Remove from Storage explicitly
                if (t && p.layerStorage[t] && p.layerStorage[t].hasLayer(l)) {
                    p.layerStorage[t].removeLayer(l);
                }

                // Cleanup associated labels
                if (l._measurementLabels) l._measurementLabels.forEach(lbl => {
                    lbl.remove();
                    if (p.layerStorage['label_aux'] && p.layerStorage['label_aux'].hasLayer(lbl)) {
                        p.layerStorage['label_aux'].removeLayer(lbl);
                    }
                });
                if (l._pipeLabel) {
                    l._pipeLabel.remove();
                    if (p.layerStorage['label_aux'] && p.layerStorage['label_aux'].hasLayer(l._pipeLabel)) {
                        p.layerStorage['label_aux'].removeLayer(l._pipeLabel);
                    }
                }

                // Check if pipe
                if (s && s.startsWith('pipe')) pipeDeleted = true;
            });

            // [Fix] Update Connections (Tees/Elbows) immediately
            if (pipeDeleted && p.geometry) {
                p.geometry.rebuildConnections();
            }

            p.saveDesign(Array.from(deletedTypes), true);
            p.updateDesignInfo();
        });

        p.map.on('draw:editstart', () => { window.AoTMapEditor.editEnabled = true; p.ui.updateEditorButtons({ edit: true, delete: false }); });
        p.map.on('draw:editstop', () => { window.AoTMapEditor.editEnabled = false; p.ui.updateEditorButtons({ edit: false, delete: false }); });
        p.map.on('draw:deletestart', () => { window.AoTMapEditor.deleteEnabled = true; p.ui.updateEditorButtons({ edit: false, delete: true }); });
        p.map.on('draw:deletestop', () => { window.AoTMapEditor.deleteEnabled = false; p.ui.updateEditorButtons({ edit: false, delete: false }); });
    }
}

window.AoTGeoEvents = AoTGeoEvents;
