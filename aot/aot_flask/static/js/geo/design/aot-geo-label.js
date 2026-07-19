/**
 * aot-geo-label.js
 * Handles Label Creation, Styling, and Management
 */

class AoTGeoLabel {
    constructor(parent) {
        this.parent = parent;
    }

    /**
     * Create Auto Label for Sites/Zones (Area & Name)
     */
    createAutoLabel(parentLayer, name, areaText) {
        try {
            if (!window.turf) throw new Error("Turf.js not loaded");

            // Calculate Position
            let geojson = parentLayer.toGeoJSON();
            let parentType = 'site'; // Default

            // Handle Circle (MapLibre compatibility: check _aotType or feature properties)
            if (parentLayer._aotType === 'Circle' || (parentLayer.feature && parentLayer.feature.properties && parentLayer.feature.properties.is_circle)) {
                let center = parentLayer.getLatLng ? parentLayer.getLatLng() : { lat: 0, lng: 0 };
                if (!center || !center.lat || !center.lng) {
                    // Try to get from geometry centroid
                    if (parentLayer.feature && parentLayer.feature.geometry && parentLayer.feature.geometry.type === 'Point') {
                        center = { lat: parentLayer.feature.geometry.coordinates[1], lng: parentLayer.feature.geometry.coordinates[0] };
                    } else {
                        center = { lat: 0, lng: 0 };
                    }
                }
                let radius = parentLayer.getRadius ? parentLayer.getRadius() : 100;
                if (!radius && parentLayer.feature && parentLayer.feature.properties && parentLayer.feature.properties.radius) {
                    radius = parentLayer.feature.properties.radius;
                }
                if (center.lat !== 0 || center.lng !== 0) {
                    geojson = window.turf.circle([center.lng, center.lat], radius || 100, { steps: 16, units: 'meters' });
                }
            }

            // Determine Parent Type for Offset
            if (name.toLowerCase().includes('zone')) parentType = 'zone';
            else if (parentLayer.feature && parentLayer.feature.properties && parentLayer.feature.properties.aot_type) {
                parentType = parentLayer.feature.properties.aot_type;
            }

            const bbox = window.turf.bbox(geojson);

            // Offset Logic (Lat/Lng degrees)
            // 1 deg Lat ~= 111,000 meters
            // 20m ~= 0.00018 deg, 10m ~= 0.00009 deg
            let latOffset = 0.00018; // Default 20m (Site)
            if (parentType === 'zone') latOffset = 0.00009; // 10m (Zone)

            // [Fix] Check for Duplicate Labels (Prevent Double Labeling on Load/Save)
            const parentIdToCheck = parentLayer.feature?.properties?.node_id;
            if (parentIdToCheck && this.parent.layerStorage['label_aux']) {
                let exists = false;
                this.parent.layerStorage['label_aux'].eachLayer(l => {
                    if (l.feature?.properties?.parent_node_id === parentIdToCheck) exists = true;
                });
                if (exists) {
                    // console.log("[AutoLabel] Label already exists for parent. Skipping creation.");
                    return;
                }
            }

            // [Improvement] Better Initial Position (Centroid if possible)
            let initialPos = [bbox[3] + latOffset, bbox[0]];
            try {
                const centroid = window.turf.centroid(geojson);
                if (centroid && centroid.geometry && centroid.geometry.coordinates) {
                    initialPos = [centroid.geometry.coordinates[1], centroid.geometry.coordinates[0]];
                }
            } catch (e) { /* Fallback to bbox topLeft */ }

            // Z-Index Priority: Site/Zone (Top) > Device > Length
            const marker = new AoTGeoMarker(initialPos, { zIndexOffset: 5000, draggable: true });

            // Assign Unique ID and all properties BEFORE rendering/adding to map
            const newNodeId = window.uuidv4 ? window.uuidv4() : 'lab-xxxx-xxxx'.replace(/[x]/g, () => (Math.random() * 16 | 0).toString(16));

            marker.feature = marker.feature || {};
            marker.feature.properties = marker.feature.properties || {};
            marker.feature.properties.node_id = newNodeId;
            marker.feature.properties.aot_type = 'label_aux';
            marker.feature.properties.label_name = name;
            marker.feature.properties.label_area = areaText;
            marker.feature.properties.parent_type = parentType;

            // [Fix] Mark as Dirty for Delta Save
            if (this.parent.dirtyNodeIds) {
                this.parent.dirtyNodeIds.add(newNodeId);
            }

            // Link to Parent Layer for Cascading Delete (Persistent UUID)
            if (parentLayer.feature && parentLayer.feature.properties && parentLayer.feature.properties.node_id) {
                const pProps = parentLayer.feature.properties;
                marker.feature.properties.parent_node_id = pProps.node_id;
                if (this.parent.dirtyNodeIds) this.parent.dirtyNodeIds.add(pProps.node_id);
            }

            // Link Click to Parent Activation (MapLibre native events)
            marker._parentLayer = parentLayer;
            marker.on('click', (e) => {
                e.stopPropagation();
                this.parent._setActiveLayer(parentLayer);
            });

            // [Fix] Set icon BEFORE adding to map so the correct HTML element is used.
            this.convertToLabel(marker);

            // [Fix] Ensure label_aux storage exists
            if (!this.parent.layerStorage['label_aux']) {
                this.parent.layerStorage['label_aux'] = new AoTGeoLayerGroup('label_aux');
            }
            const labelGroup = this.parent.layerStorage['label_aux'];

            // Register in group for storage/save tracking
            labelGroup._layers = labelGroup._layers || new Map();
            labelGroup._layers.set(marker._layerId, marker);
            marker._map = this.parent.map;

            // [Fix] Directly create and add the native MapLibre DOM marker.
            // AoTGeoLayerGroup.addLayer() defers rendering through isStyleLoaded() checks
            // that may not fire again. Bypass it entirely for immediate rendering.
            if (!marker._mlDomMarker && window.maplibregl && this.parent.map) {
                const nativeMap = this.parent.map._originalMap
                    || (this.parent.map.getNativeMap && this.parent.map.getNativeMap())
                    || this.parent.map._mlMap
                    || this.parent.map;
                const iconEl = marker._icon && marker._icon.createIcon
                    ? marker._icon.createIcon()
                    : (() => { const d = document.createElement('div'); d.style.cssText = 'width:0;height:0;overflow:visible;'; return d; })();
                marker._markerEl = iconEl;
                marker._mlDomMarker = new window.maplibregl.Marker({ element: iconEl, anchor: 'center', draggable: true })
                    .setLngLat([marker._latlng.lng, marker._latlng.lat])
                    .addTo(nativeMap);
                marker._mlDomMarker.on('dragend', () => {
                    const pos = marker._mlDomMarker.getLngLat();
                    marker._latlng = { lat: pos.lat, lng: pos.lng };
                    if (marker.feature && marker.feature.geometry) {
                        marker.feature.geometry.coordinates = [pos.lng, pos.lat];
                    }
                    marker.fire('dragend');
                });
            }

            // [Fix] Immediate Save to ensure persistence
            // console.log("[AutoLabel] Auto-saving new label...");
            this.parent.saveDesign(['label_aux'], true);

        } catch (e) {
            console.error("[AutoLabel] Auto Label Creation Failed:", e);
        }
    }

    /**
     * Convert Marker to Label Style (HTML Icon)
     * Handles styling, drag events, and context menu blocking
     */
    convertToLabel(layer) {
        // Get Content
        const props = layer.feature.properties;
        const name = props.label_name || props.label_text || 'Label';
        const area = props.label_area || '';

        // 1. Style: Match Color based on Parent Type
        let parentType = props.parent_type;

        // Auto-Infer from Name if missing (Legacy Support)
        if (!parentType) {
            const lowerName = name.toLowerCase();
            if (lowerName.includes('zone') || lowerName.includes('구역') || lowerName.includes('구획')) parentType = 'zone';
            else if (lowerName.includes('site') || lowerName.includes('대지')) parentType = 'site';
        }

        let color = '#333';
        const targetType = parentType || props.aot_type;
        const config = window.AOT_GEO_CONFIG?.theme_config || {};

        if (targetType === 'site') color = config.site || '#DF5353';
        else if (targetType === 'zone') color = config.zone || '#28a745';
        else if (targetType === 'facility') color = config.facility || '#82898f';
        else if (targetType === 'equipment') color = config.equipment || '#007bff';
        else if (targetType === 'device' || targetType === 'aot_device') color = config.device || '#995aff';

        this.updateLabelIcon(layer, name, area, color);

        props.is_label = true;
        props.label_name = name;

        // 2. Interaction: Native Drag and Drop (MapLibre compatibility)
        if (layer._aotType === 'Marker' || (layer.feature && layer.feature.properties && layer.feature.properties.aot_type === 'label_aux')) {
            if (layer.draggable) {
                layer.draggable = true;
            }
            // Enable draggable for MapLibre markers
            if (layer.options) {
                layer.options.draggable = true;
            }
        }

        if (layer.dragging) {
            layer.dragging.enable();
        }

        layer.off('dragend');
        layer.on('dragend', () => {
            const latlng = layer.getLatLng();
            if (layer.feature && layer.feature.geometry) {
                layer.feature.geometry.coordinates = [latlng.lng, latlng.lat];
            }

            // [Fix] Add to Dirty Set for Immediate Auto-Save
            const nid = layer.feature?.properties?.node_id;
            if (nid && this.parent.dirtyNodeIds) {
                this.parent.dirtyNodeIds.add(nid);
            }

            // Auto Save Position
            // console.log("[AutoSave] Label Moved. Saving...");
            this.parent.saveDesign(['label_aux'], true); // Only need to save labels
        });

        // Block Right Click (MapLibre native events)
        layer.off('contextmenu');
        layer.on('contextmenu', (e) => {
            e.stopPropagation();
            e.preventDefault();
        });

        // Interaction: Double Click to Edit Name
        layer.off('dblclick');
        layer.on('dblclick', (e) => {
            if (e && e.stopPropagation) e.stopPropagation();
            this.renameLabel(layer);
        });

        // [Fix] AoTGeoMarker.on() only stores handlers — does NOT bind to DOM.
        // Bind dblclick directly to the marker element so the user actually triggers it.
        const labelEl = layer._markerEl || (layer.getElement && layer.getElement());
        if (labelEl && !labelEl._aotLabelDomBound) {
            labelEl._aotLabelDomBound = true;
            labelEl.style.pointerEvents = 'auto';
            labelEl.style.cursor = 'pointer';
            labelEl.addEventListener('dblclick', (ev) => {
                ev.stopPropagation();
                ev.preventDefault();
                this.renameLabel(layer);
            });
            labelEl.addEventListener('click', (ev) => {
                ev.stopPropagation();
                // Activate parent layer (matches createAutoLabel intent)
                if (layer._parentLayer && this.parent._setActiveLayer) {
                    this.parent._setActiveLayer(layer._parentLayer);
                }
            });
            labelEl.addEventListener('contextmenu', (ev) => {
                ev.stopPropagation();
                ev.preventDefault();
            });
        }

        // Mobile / Popup Renaming Support
        // Bind Popup (Input Field + Save Button)
        const popupContent = document.createElement('div');
        popupContent.className = 'p-2 text-center';
        popupContent.style.minWidth = '180px';
        popupContent.innerHTML = `
            <div class="mb-2">
                <input type="text" class="form-control form-control-sm text-center font-weight-bold" id="label-name-input" value="${name}" placeholder="${window._ ? window._('Enter name') : 'Enter name'}">
            </div>
            <div class="d-flex gap-1 justify-content-center">
                 <button class="btn btn-sm btn-primary flex-fill" id="btn-save-label" style="font-size: 11px;">${window._ ? window._('Save') : 'Save'}</button>
            </div>
        `;

        layer.bindPopup(popupContent, { closeButton: false, offset: [0, -20] });

        layer.off('popupopen');
        layer.on('popupopen', () => {
            const btnSave = popupContent.querySelector('#btn-save-label');
            const inputName = popupContent.querySelector('#label-name-input');

            // Focus input (Mobile friendly?)
            if (inputName) {
                setTimeout(() => {
                    inputName.focus();
                    inputName.select(); // [Improvement] Auto-select text for easy overwrite
                }, 100);

                // Handle Enter Key
                inputName.onkeydown = (e) => {
                    if (e.key === 'Enter') {
                        btnSave.click();
                    }
                };
                
                // [Fix] Auto-Save on Blur (Clicking away)
                inputName.onblur = () => {
                     // Wait slightly to allow 'Cancel' or other clicks to register if needed? 
                     // Usually Blur -> Save is standard for in-place edit.
                     // But popup might close? Popup closes on outside click anyway.
                     // If popup closes on outside click, this blur might trigger before destruction?
                     // Let's safe guard.
                     if (inputName.value) {
                         const newName = inputName.value.trim();
                         if (newName && newName !== name) {
                             this.applyLabelRename(layer, newName);
                         }
                     }
                };
            }

            if (btnSave) {
                btnSave.onclick = (ev) => {
                    if (ev && ev.stopPropagation) ev.stopPropagation();
                    const newName = inputName ? inputName.value.trim() : '';
                    if (newName) {
                        this.applyLabelRename(layer, newName);
                        layer.closePopup();
                    } else {
                        this.parent.ui.showToast(_('enter_name_please'), 'warning');
                    }
                };
            }
        });
    }

    /**
     * Rename Label (Inline Popup near the marker)
     */
    renameLabel(layer) {
        const currentName = layer.feature.properties.label_name || '';
        // Walk wrapper chain to find native MapLibre Map (must have .transform for Popup.addTo)
        const findNativeMap = (m) => {
            let cur = m;
            for (let i = 0; i < 5 && cur; i++) {
                if (cur.transform && cur.getContainer) return cur; // native MapLibre Map
                cur = cur._mlMap || cur._map || null;
            }
            return null;
        };
        const nativeMap = findNativeMap(this.parent.map);

        // Fallback to native prompt if MapLibre Popup unavailable
        if (!window.maplibregl || !nativeMap || !layer.getLatLng) {
            const newName = prompt(_('edit_label_name'), currentName);
            if (newName !== null && newName.trim() !== "") {
                this.applyLabelRename(layer, newName.trim());
            }
            return;
        }

        // Close any existing rename popup for this layer
        if (layer._renamePopup) {
            try { layer._renamePopup.remove(); } catch(e) {}
            layer._renamePopup = null;
        }

        const latlng = layer.getLatLng();
        const wrapper = document.createElement('div');
        wrapper.className = 'p-2 text-center aot-label-rename';
        wrapper.style.minWidth = '180px';
        const safeName = String(currentName).replace(/"/g, '&quot;');
        wrapper.innerHTML = `
            <div class="mb-2">
                <input type="text" class="form-control form-control-sm text-center font-weight-bold" value="${safeName}" placeholder="${window._ ? window._('Enter name') : 'Enter name'}">
            </div>
            <div class="d-flex gap-1 justify-content-center">
                <button class="btn btn-sm btn-primary flex-fill" style="font-size: 11px;">${window._ ? window._('Save') : 'Save'}</button>
            </div>
        `;

        // Stop wrapper events from leaking to the map (prevents accidental dblclick re-trigger)
        ['click', 'dblclick', 'mousedown', 'mouseup'].forEach(evt => {
            wrapper.addEventListener(evt, (e) => e.stopPropagation());
        });

        const popup = new window.maplibregl.Popup({
            closeButton: true,
            closeOnClick: false,
            anchor: 'bottom',
            offset: [0, -25],
            className: 'aot-label-rename-popup'
        })
            .setLngLat([latlng.lng, latlng.lat])
            .setDOMContent(wrapper)
            .addTo(nativeMap);

        layer._renamePopup = popup;
        popup.on('close', () => { if (layer._renamePopup === popup) layer._renamePopup = null; });

        const input = wrapper.querySelector('input');
        const btnSave = wrapper.querySelector('button');

        const commit = () => {
            const newName = input ? input.value.trim() : '';
            if (newName && newName !== currentName) {
                this.applyLabelRename(layer, newName);
            }
            popup.remove();
        };

        // Focus + select after popup is in DOM
        setTimeout(() => { if (input) { input.focus(); input.select(); } }, 50);

        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); commit(); }
                else if (e.key === 'Escape') { e.preventDefault(); popup.remove(); }
            });
        }
        if (btnSave) {
            btnSave.addEventListener('click', (e) => { e.stopPropagation(); commit(); });
        }
    }

    /**
     * Apply Rename Logic & Sync with Parent
     */
    applyLabelRename(layer, newName) {
        // 1. Update Label Itself
        layer.feature.properties.label_name = newName;
        this.convertToLabel(layer);

        // [Fix] Mark Label as Dirty for Delta Save
        if (layer.feature.properties.node_id && this.parent.dirtyNodeIds) {
            this.parent.dirtyNodeIds.add(layer.feature.properties.node_id);
        }

        // 2. Sync with Parent (Robust Lookup)
        const parentId = layer.feature.properties.parent_node_id;
        let parentLayer = null;

        if (parentId) {
            parentLayer = layer._parentLayer; // Try direct reference first

            // If reference missing, search storage
            if (!parentLayer) {
                const findInGroup = (group) => {
                    let found = null;
                    if (group) group.eachLayer(l => {
                        if (l.feature?.properties?.node_id === parentId) found = l;
                    });
                    return found;
                };

                parentLayer = findInGroup(this.parent.layerStorage['site']) ||
                    findInGroup(this.parent.layerStorage['zone']) ||
                    findInGroup(window.AoTMapEditor.featureGroup);
            }
 
            if (parentLayer && parentLayer.feature && parentLayer.feature.properties) {
                // console.log(`[GeoDesign] Syncing Rename to Parent: ${parentId} -> ${newName}`);
                parentLayer.feature.properties.name = newName; // Primary
                parentLayer.feature.properties.label = newName; // Fallback
                parentLayer.feature.properties.label_name = newName; // Fallback
                
                // [Fix] Mark Parent as Dirty!
                // Critical: 'saveDesign' with isAutoSave=true ONLY saves items in dirtyNodeIds.
                // We MUST add the parent ID here so the Site object is included in the delta save.
                if (this.parent.dirtyNodeIds) {
                    this.parent.dirtyNodeIds.add(parentId);
                }
            }
        }

        // [Fix] Batch Save: Save Label + Parent (if exists) in one go
        const typesToSave = ['label_aux'];
        if (parentLayer && parentLayer.feature.properties.aot_type) {
            typesToSave.push(parentLayer.feature.properties.aot_type);
        }
        
        // Console log for debugging
        // console.log("[AutoSave] Saving Rename Changes:", typesToSave);
        this.parent.saveDesign(typesToSave, true);

        // Refresh Design Info immediately to reflect name change
        if (this.parent.updateDesignInfo) this.parent.updateDesignInfo();
    }

    /**
     * Update Label Icon HTML
     */
    updateLabelIcon(layer, name, area, color) {
        // Background = Color, Text = White
        const bgStyle = color ? `background-color: ${color}; color: white; border-color: ${color};` : `background-color: white; border-color: #333;`;

        const htmlContent = area
            ? `<div style="font-weight:bold;">${name}</div><div style="font-size:0.9em; opacity:0.9;">${area}</div>`
            : `<div style="font-weight:bold;">${name}</div>`;

        // MapLibre-compatible: Create div element directly instead of L.divIcon
        const iconEl = document.createElement('div');
        const parentType = layer.feature?.properties?.parent_type;
        const typeClass = parentType === 'zone' ? 'aot-zone-label' : parentType === 'site' ? 'aot-site-label' : '';
        iconEl.className = typeClass ? `geo-label-marker ${typeClass}` : 'geo-label-marker';
        iconEl.innerHTML = '<div class="p-1 rounded shadow-sm text-center" style="width: max-content; min-width: auto; font-size:12px; line-height:1.2; white-space: nowrap; border: 1px solid; ' + bgStyle + '; transform: translate(-50%, -50%);">' + htmlContent + '</div>';
        iconEl.style.cssText = 'width:0; height:0; overflow:visible;';

        // Create AoTGeoMarker-compatible icon
        const icon = {
            createIcon: function() { return iconEl; },
            options: {
                className: 'geo-label-marker',
                iconSize: [0, 0],
                iconAnchor: [0, 0]
            }
        };

        // Critical Fix: Only markers support setIcon - use AoTGeoMarker method
        if (layer.setIcon && typeof layer.setIcon === 'function') {
            layer.setIcon(icon);
        } else if (layer._setIcon && typeof layer._setIcon === 'function') {
            // AoTGeoMarker uses _setIcon
            layer._setIcon(icon);
        } else {
            // Fallback: store icon for later application
            layer._storedIcon = icon;
        }
    }

    /**
     * Cleanup Orphan Labels
     * Removes labels that have lost their parent features.
     */
    cleanupOrphanLabels() {
        // console.log("[Cleanup] Checking for orphan labels...");
        const labelGroup = this.parent.layerStorage['label_aux'];
        if (!labelGroup) return;

        // 1. Collect Valid Parent IDs
        const validParentIds = new Set();
        // [Fix] Include 'equipment' (pipes) and 'facility' to prevent deleting their labels
        const typesToCheck = ['site', 'zone', 'device', 'infra_blob', 'equipment', 'facility', 'aot_device'];

        typesToCheck.forEach(type => {
            if (this.parent.layerStorage[type]) {
                this.parent.layerStorage[type].eachLayer(l => {
                    const id = l.feature?.properties?.node_id;
                    if (id) validParentIds.add(id);
                });
            }
        });

        // [Fix] Check ALL Editor Layers Globally (valid parents regardless of type/mode)
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
             window.AoTMapEditor.featureGroup.eachLayer(l => {
                 const id = l.feature?.properties?.node_id;
                 if (id) validParentIds.add(id);
             });
        }
        // 2. Identify and Remove Orphans
        // All labels whose parent shape is not found are orphans — including DB-persisted ones.
        // cleanupOrphanLabels() is called after all shapes finish loading, so validParentIds is
        // complete. Orphan DB rows are tracked in deletedNodeIds and purged via saveDesign.
        const layersToRemove = [];
        labelGroup.eachLayer(l => {
            const props = l.feature?.properties || {};
            const parentId = props.parent_node_id;

            if (!parentId || !validParentIds.has(parentId)) {
                layersToRemove.push(l);
            }
        });

        layersToRemove.forEach(l => {
            const props = l.feature?.properties || {};
            const lnid = props.node_id;
            if (lnid && this.parent.deletedNodeIds) {
                this.parent.deletedNodeIds.add(lnid);
            }
            // Remove MapLibre DOM marker first
            if (l._mlDomMarker) {
                try { l._mlDomMarker.remove(); l._mlDomMarker = null; } catch(e) {}
            }
            // Remove MapLibre source+layer if present
            if (l._layerId && this.parent.map) {
                const lSrcId = 'aot-source-' + l._layerId;
                try { if (this.parent.map.getLayer(l._layerId)) this.parent.map.removeLayer(l._layerId); } catch(e) {}
                try { if (this.parent.map.getSource(lSrcId)) this.parent.map.removeSource(lSrcId); } catch(e) {}
            }
            // AoTGeoMarker cleanup
            if (typeof l.remove === 'function') { try { l.remove(); } catch(e) {} }
            labelGroup.removeLayer(l);
            if (this.parent.map.hasLayer(l)) this.parent.map.removeLayer(l);
        });
        if (layersToRemove.length > 0) {
            console.log(`[Cleanup] ${layersToRemove.length} orphan labels removed. Syncing with DB...`);
            this.parent.saveDesign(['label_aux'], true);
        }
    }
}
