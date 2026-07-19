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

        this._bindFullscreenModalFix();
        // bindIfExists('tool-search', () => {
        //     const overlay = document.getElementById('search-overlay');
        //     if (overlay) overlay.classList.toggle('d-none');
        // });
        bindIfExists('tool-locate', () => {
            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(
                    pos => p.map.flyTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: 16 }),
                    err => console.warn('[GeoDesign] Location error:', err.message)
                );
            }
        });
        bindIfExists('tool-reset', () => {
            try {
                const bounds = window.AoTMapEditor && window.AoTMapEditor.featureGroup
                    ? window.AoTMapEditor.featureGroup.getBounds()
                    : null;
                if (bounds && bounds.isValid && bounds.isValid()) {
                    const sw = bounds.getSouthWest();
                    const ne = bounds.getNorthEast();
                    p.map.fitBounds([[sw.lng, sw.lat], [ne.lng, ne.lat]], { padding: 50 });
                } else {
                    p.map.flyTo({ center: [127.5, 36.5], zoom: 7 });
                }
            } catch (e) {
                p.map.flyTo({ center: [127.5, 36.5], zoom: 7 });
            }
        });

        // Toggle Tools
        bindIfExists('tool-lock', () => p.toggleLock());
        bindIfExists('tool-hide', () => p.toggleHide());
        bindIfExists('tool-site-list', () => p.ui.toggleSiteList());
        bindIfExists('tool-layers', () => p.ui._toggleLayerPanel());

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


        // Map Background Click (MapLibre-compatible)
        p.map.on('click', (e) => {
            // Skip if a layer click handler already handled this event (prevents double-fire)
            if (e.originalEvent && e.originalEvent._aotLayerHandled) return;

            // [Fix] Deactivate Active Device if clicked on empty space
            // [Fix] Block deactivation if drawing/editing is in progress (prevents Polygon clicks from canceling device mode)

            // [Fix V11] Robust Drawing Detection
            // Check activeShape, activeDrawer, edit/delete modes
            // MapLibre Note: activeDrawer._enabled check is simplified as _activeMode check
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

            // [MapLibre] Check draw manager state if available
            if (!isDrawing && window.AoTDrawManager) {
                const dm = window.AoTDrawManager.getDefault(p.map);
                if (dm && dm.isDrawing()) {
                    isDrawing = true;
                }
            }


            // [Fix] Sprinkler delete: click on coverage circle in delete mode
            if (window.AoTMapEditor?.deleteEnabled && p.activeMode === 'equipment') {
                // Helper: distance in meters between two [lng, lat] points (simple equirectangular)
                const _meterDist = (lng1, lat1, lng2, lat2) => {
                    const R = 6371000;
                    const dLat = (lat2 - lat1) * Math.PI / 180;
                    const dLng = (lng2 - lng1) * Math.PI / 180 * Math.cos((lat1 + lat2) / 2 * Math.PI / 180);
                    return R * Math.sqrt(dLat * dLat + dLng * dLng);
                };

                // Get click geographic coordinates
                const clickLng = e.lngLat?.lng;
                const clickLat = e.lngLat?.lat;

                let coverageLayer = null;

                // 1. Try queryRenderedFeatures (fast, works when bucket layer is visible)
                if (!coverageLayer && typeof p.map.queryRenderedFeatures === 'function' && e.point) {
                    const bbox = [[e.point.x - 8, e.point.y - 8], [e.point.x + 8, e.point.y + 8]];
                    let hits = [];
                    try { hits = p.map.queryRenderedFeatures(bbox, { layers: ['aot-bucket-sprinkler-coverage'] }); } catch(_) {}
                    if (hits.length > 0) {
                        const nodeId = hits[0].properties?.node_id;
                        if (nodeId) {
                            const scanForNode = (group) => {
                                if (!group?.eachLayer) return;
                                group.eachLayer(l => {
                                    if (!coverageLayer && l.feature?.properties?.node_id === nodeId) coverageLayer = l;
                                });
                            };
                            if (window.AoTMapEditor.featureGroup) scanForNode(window.AoTMapEditor.featureGroup);
                            if (!coverageLayer) scanForNode(p.layerStorage['equipment']);
                        }
                    }
                }

                // 2. Spatial fallback: scan featureGroup/storage for closest coverage circle
                if (!coverageLayer && clickLng != null && clickLat != null) {
                    let minDist = Infinity;
                    const checkCoverage = (group) => {
                        if (!group?.eachLayer) return;
                        group.eachLayer(l => {
                            if (l.feature?.properties?.sub_type !== 'sprinkler_coverage') return;
                            const coords = l.feature?.geometry?.coordinates || (l._latlng ? [l._latlng.lng, l._latlng.lat] : null);
                            const radius = l.feature?.properties?.radius || l._radius || 0;
                            if (!coords || !radius) return;
                            const dist = _meterDist(clickLng, clickLat, coords[0], coords[1]);
                            if (dist <= radius && dist < minDist) {
                                minDist = dist;
                                coverageLayer = l;
                            }
                        });
                    };
                    if (window.AoTMapEditor?.featureGroup) checkCoverage(window.AoTMapEditor.featureGroup);
                    if (!coverageLayer) checkCoverage(p.layerStorage['equipment']);
                }

                if (coverageLayer) {
                    const featureToDelete = coverageLayer.feature || { type: 'Feature', properties: { node_id: null, sub_type: 'sprinkler_coverage', aot_type: 'equipment' }, geometry: null };
                    // Direct RenderBucket removal — featureGroup.removeLayer only removes from JS array, not from GL render
                    if (window.RenderBucket && coverageLayer._layerId) {
                        const covBucket = window.RenderBucket.get(p.map, 'sprinkler-coverage');
                        if (covBucket) covBucket.remove(coverageLayer._layerId);
                        // Also remove sprinkler-dot (head marker) sharing the same node_id
                        const headNodeId = featureToDelete.properties?.node_id;
                        if (headNodeId) {
                            const dotBucket = window.RenderBucket.get(p.map, 'sprinkler-dot');
                            if (dotBucket) {
                                const scanDot = (group) => {
                                    if (!group?.eachLayer) return;
                                    group.eachLayer(l => {
                                        if (l.feature?.properties?.node_id === headNodeId && l._layerId) {
                                            dotBucket.remove(l._layerId);
                                        }
                                    });
                                };
                                if (window.AoTMapEditor?.featureGroup) scanDot(window.AoTMapEditor.featureGroup);
                                scanDot(p.layerStorage['equipment']);
                            }
                        }
                    }
                    // Flush immediately — RAF-deferred flush can be race-cancelled by a subsequent upsert
                    if (window.RenderBucket) {
                        const _covB = window.RenderBucket.get(p.map, 'sprinkler-coverage');
                        const _dotB = window.RenderBucket.get(p.map, 'sprinkler-dot');
                        if (_covB) _covB.flush();
                        if (_dotB) _dotB.flush();
                    }
                    // Remove from tracking arrays
                    if (window.AoTMapEditor?.featureGroup?.removeLayer) window.AoTMapEditor.featureGroup.removeLayer(coverageLayer);
                    if (p.layerStorage['equipment']?.removeLayer) p.layerStorage['equipment'].removeLayer(coverageLayer);
                    // Fire aot:editor:deleted — reverse cascade removes the associated head layer object + saves
                    window.dispatchEvent(new CustomEvent('aot:editor:deleted', {
                        detail: { features: [featureToDelete], layers: [featureToDelete] }
                    }));
                    if (e.originalEvent) e.originalEvent._aotLayerHandled = true;
                    return;
                }
            }

            // [MapLibre] Try shape selection via queryRenderedFeatures before resetting
            if (!isDrawing && !p.isLocked && typeof p.map.queryRenderedFeatures === 'function') {
                const bbox = [[e.point.x - 6, e.point.y - 6], [e.point.x + 6, e.point.y + 6]];
                const activeMode = p.activeMode;
                // Pipes/lines render in shared RenderBucket layers — must query bucket IDs, not per-instance
                const BUCKET_LINE_IDS = ['aot-bucket-pipe-main', 'aot-bucket-pipe-branch', 'aot-bucket-line-generic', 'aot-bucket-pipe-reference'];
                const BUCKET_PREFIX = 'aot-bucket-';

                // Build lookup maps and selIds in a single pass over all relevant layers
                const selIds = new Set();
                const layerByLayerId = new Map();  // per-instance _layerId → layer
                const layerByNodeId  = new Map();  // node_id/db_id → layer (for bucket hits)

                const indexLayer = (l) => {
                    if (!l || !l._layerId) return;
                    const fType = l.feature && l.feature.properties && l.feature.properties.aot_type;
                    const modeOk = !fType
                        || (fType === activeMode)
                        || (activeMode === 'aot_device' && fType === 'device')
                        || (activeMode === 'equipment' && ['site', 'zone', 'reference', 'equipment'].includes(fType));
                    if (!modeOk) return;
                    layerByLayerId.set(l._layerId, l);
                    const nodeId = l.feature && l.feature.properties && (l.feature.properties.node_id || l.feature.properties.db_id);
                    if (nodeId) layerByNodeId.set(String(nodeId), l);
                    if (l._aotType === 'Polyline') {
                        BUCKET_LINE_IDS.forEach(id => selIds.add(id));
                    } else {
                        selIds.add(l._layerId);
                    }
                };
                const indexGroup = (group) => {
                    if (!group || !group.eachLayer) return;
                    group.eachLayer(indexLayer);
                };

                const _editorFG = window.AoTMapEditor && window.AoTMapEditor.featureGroup;
                if (_editorFG && _editorFG.layers) _editorFG.layers.forEach(indexLayer);
                indexGroup(p.layerStorage[activeMode]);
                if (activeMode === 'aot_device') indexGroup(p.layerStorage['device']);
                if (activeMode === 'equipment') {
                    indexGroup(p.layerStorage['reference']);
                    indexGroup(p.layerStorage['site']);
                    indexGroup(p.layerStorage['zone']);
                }

                // Resolve a queryRenderedFeatures hit → AoTGeoLayer object
                const resolveHit = (hit) => {
                    const lid = hit.layer && hit.layer.id;
                    if (!lid) return null;
                    if (lid.startsWith(BUCKET_PREFIX)) {
                        const nid = hit.properties && (hit.properties.node_id || hit.properties.db_id);
                        return nid ? (layerByNodeId.get(String(nid)) || null) : null;
                    }
                    return layerByLayerId.get(lid) || null;
                };

                // Exception: site/zone are read-only selection targets in equipment mode
                const isException = (l) => {
                    if (!l) return false;
                    const ft = l.feature && l.feature.properties && l.feature.properties.aot_type;
                    return (activeMode === 'equipment' && ['site', 'zone'].includes(ft));
                };

                if (selIds.size > 0) {
                    let hits = [];
                    try { hits = p.map.queryRenderedFeatures(bbox, { layers: Array.from(selIds) }); } catch (_) {}
                    if (hits.length > 0) {
                        // Prioritize active-mode shapes over exception shapes (site/zone in equipment mode)
                        let found = null;
                        for (const hit of hits) {
                            const candidate = resolveHit(hit);
                            if (!candidate) continue;
                            if (!found || (!isException(candidate) && isException(found))) {
                                found = candidate;
                                if (!isException(found)) break;
                            }
                        }

                        if (found) {
                            // equipment mode selecting site/zone: selection only, no edit
                            const fType = found.feature && found.feature.properties && found.feature.properties.aot_type;
                            const isReadOnly = (activeMode === 'equipment' && ['site', 'zone'].includes(fType));
                            if (p.activeLayer === found) {
                                p._resetActiveLayer();
                            } else {
                                p._setActiveLayer(found, isReadOnly);
                            }
                            if (e.originalEvent) e.originalEvent._aotLayerHandled = true;
                            return;
                        }
                    }
                }
            }

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

                // Cascade: remove auto-labels linked by parent_node_id.
                // Labels may be in layerStorage['label_aux'] OR moved to featureGroup during delete mode.
                if (nid) {
                    const removeLabel = (lbl, grp) => {
                        const lnid = lbl.feature?.properties?.node_id;
                        if (lnid) p.deletedNodeIds.add(lnid);
                        if (lbl._mlDomMarker) { lbl._mlDomMarker.remove(); lbl._mlDomMarker = null; }
                        if (grp && grp.removeLayer) grp.removeLayer(lbl);
                        if (p.map.hasLayer(lbl)) p.map.removeLayer(lbl);
                    };
                    const scanGroup = (grp) => {
                        if (!grp || !grp.eachLayer) return;
                        const found = [];
                        grp.eachLayer(lbl => {
                            if (lbl.feature?.properties?.aot_type === 'label_aux' &&
                                lbl.feature?.properties?.parent_node_id === nid) found.push(lbl);
                        });
                        found.forEach(lbl => removeLabel(lbl, grp));
                    };
                    scanGroup(p.layerStorage['label_aux']);
                    scanGroup(window.AoTMapEditor?.featureGroup);
                }

                // Check if pipe
                if (s && s.startsWith('pipe')) pipeDeleted = true;
            });

            // [Fix] Update Connections (Tees/Elbows) immediately
            if (pipeDeleted && p.geometry) {
                p.geometry.rebuildConnections();
            }

            // During an active delete session (deleteEnabled), defer the final save to
            // saveActions(). This allows cancelActions() to restore deleted layers without
            // the server having already persisted the deletion.
            if (!window.AoTMapEditor?.deleteEnabled) {
                p.saveDesign(Array.from(deletedTypes), true);
            }
            p.updateDesignInfo();
        });

        p.map.on('draw:editstart', () => { window.AoTMapEditor.editEnabled = true; p.ui.updateEditorButtons({ edit: true, delete: false }); });
        p.map.on('draw:editstop', () => { window.AoTMapEditor.editEnabled = false; p.ui.updateEditorButtons({ edit: false, delete: false }); });
        p.map.on('draw:deletestart', () => { window.AoTMapEditor.deleteEnabled = true; p.ui.updateEditorButtons({ edit: false, delete: true }); });
        p.map.on('draw:deletestop', () => { window.AoTMapEditor.deleteEnabled = false; p.ui.updateEditorButtons({ edit: false, delete: false }); });
    }

    /**
     * Native Fullscreen API puts #geo-design-wrapper in the browser's top-layer;
     * Bootstrap modals/backdrops opened while it's active are siblings appended
     * to <body> and render behind it regardless of z-index. Reparent them into
     * the fullscreen element for the duration of the modal, then restore.
     */
    _bindFullscreenModalFix() {
        if (window._aotFsModalFixBound || !window.$) return;
        window._aotFsModalFixBound = true;
        const $doc = $(document);

        function restoreModal(modal) {
            const parent = modal._aotFsOriginalParent;
            modal._aotFsOriginalParent = null;
            modal._aotFsOriginalNext = null;
            if (!parent || !parent.isConnected) return;
            try {
                const next = modal._aotFsOriginalNext;
                if (next && next.parentNode === parent) {
                    parent.insertBefore(modal, next);
                } else {
                    parent.appendChild(modal);
                }
            } catch (e) { /* DOM may have shifted underneath; leave modal where it is */ }
        }

        // layout.html's global "GridStack Modal Fix" (show.bs.modal handler that
        // force-moves every modal to <body>) also runs on this event and — since
        // it's bound later, at document-ready — executes after this handler would,
        // undoing an in-place move. Do the reparent on 'shown.bs.modal' instead:
        // it fires once Bootstrap's own show sequence (and that fix) has settled,
        // so this is the last thing to touch the modal's position.
        $doc.on('shown.bs.modal', '.modal', function () {
            const fsEl = document.fullscreenElement;
            if (fsEl && !fsEl.contains(this)) {
                try {
                    this._aotFsOriginalParent = this.parentNode;
                    this._aotFsOriginalNext = this.nextSibling;
                    fsEl.appendChild(this);
                    const backdrops = document.querySelectorAll('.modal-backdrop');
                    const backdrop = backdrops[backdrops.length - 1];
                    if (backdrop && backdrop.parentNode !== fsEl) fsEl.insertBefore(backdrop, this);
                } catch (e) { this._aotFsOriginalParent = null; this._aotFsOriginalNext = null; }
            }
        });

        $doc.on('hidden.bs.modal', '.modal', function () { restoreModal(this); });

        document.addEventListener('fullscreenchange', () => {
            if (document.fullscreenElement) return;
            document.querySelectorAll('.modal').forEach(restoreModal);
        });
    }
}

window.AoTGeoEvents = AoTGeoEvents;
