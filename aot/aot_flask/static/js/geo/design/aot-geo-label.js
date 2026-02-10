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

            // Handle Circle
            if (parentLayer instanceof L.Circle) {
                const center = parentLayer.getLatLng();
                const radius = parentLayer.getRadius();
                geojson = window.turf.circle([center.lng, center.lat], radius, { steps: 64, units: 'meters' });
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
            const marker = L.marker(initialPos, { zIndexOffset: 5000, draggable: true });

            // [Fix] Ensure label_aux storage exists
            if (!this.parent.layerStorage['label_aux']) {
                this.parent.layerStorage['label_aux'] = L.layerGroup();
                this.parent.map.addLayer(this.parent.layerStorage['label_aux']);
            }

            // Add to Label Storage (Protected), NOT Editable Group
            this.parent.layerStorage['label_aux'].addLayer(marker);

            // Force visibility check
            if (!this.parent.map.hasLayer(this.parent.layerStorage['label_aux'])) {
                this.parent.map.addLayer(this.parent.layerStorage['label_aux']);
            }

            // Assign Unique ID
            const newNodeId = window.uuidv4 ? window.uuidv4() : 'lab-xxxx-xxxx'.replace(/[x]/g, () => (Math.random() * 16 | 0).toString(16));

            marker.feature = marker.feature || {};
            marker.feature.properties = marker.feature.properties || {};
            marker.feature.properties.node_id = newNodeId;
            marker.feature.properties.aot_type = 'label_aux';

            // [Fix] Mark as Dirty for Delta Save
            if (this.parent.dirtyNodeIds) {
                this.parent.dirtyNodeIds.add(newNodeId);
            }

            // Set Data
            marker.feature.properties.label_name = name;
            marker.feature.properties.label_area = areaText;
            marker.feature.properties.parent_type = parentType;

            // Link to Parent Layer for Cascading Delete (Persistent UUID)
            if (parentLayer.feature && parentLayer.feature.properties && parentLayer.feature.properties.node_id) {
                const pProps = parentLayer.feature.properties;
                marker.feature.properties.parent_node_id = pProps.node_id;
                
                // [Fix] REMOVED center_lat/lng sync to parent property.
                // This property was causing the widget to generate an "Auto Label" 
                // at the top-left because the widget logic prioritized it incorrectly.
                // We now rely on the label_aux marker's own geometry.
                
                if (this.parent.dirtyNodeIds) this.parent.dirtyNodeIds.add(pProps.node_id);
            }

            // Link Click to Parent Activation
            marker._parentLayer = parentLayer;
            marker.on('click', (e) => {
                L.DomEvent.stopPropagation(e);
                this.parent._setActiveLayer(parentLayer);
            });

            // Render
            this.convertToLabel(marker);

            // [Fix] Immediate Save to ensure persistence
            // console.log("[AutoLabel] Auto-saving new label...");
            this.parent.saveDesign(['label_aux'], true);

        } catch (e) {
            // console.error("Auto Label Creation Failed:", e);
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

        // 2. Interaction: Native Drag and Drop
        if (layer instanceof L.Marker) {
            layer.options.draggable = true;
            // Force initialize dragging handler if it doesn't exist (e.g. for markers from L.geoJSON)
            if (layer._map && !layer.dragging && L.Handler.MarkerDrag) {
                layer.dragging = new L.Handler.MarkerDrag(layer);
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

        // Block Right Click
        layer.off('contextmenu');
        layer.on('contextmenu', (e) => {
            L.DomEvent.stopPropagation(e);
            L.DomEvent.preventDefault(e);
        });

        // Interaction: Double Click to Edit Name
        layer.off('dblclick');
        layer.on('dblclick', (e) => {
            L.DomEvent.stopPropagation(e);
            this.renameLabel(layer);
        });

        // Mobile / Popup Renaming Support
        // Bind Popup (Input Field + Save Button)
        const popupContent = document.createElement('div');
        popupContent.className = 'p-2 text-center';
        popupContent.style.minWidth = '180px';
        popupContent.innerHTML = `
            <div class="mb-2">
                <input type="text" class="form-control form-control-sm text-center font-weight-bold" id="label-name-input" value="${name}" placeholder="이름 입력">
            </div>
            <div class="d-flex gap-1 justify-content-center">
                 <button class="btn btn-sm btn-primary flex-fill" id="btn-save-label" style="font-size: 11px;">저장 (Save)</button>
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
                    L.DomEvent.stopPropagation(ev);
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
     * Rename Label (Prompt)
     */
    renameLabel(layer) {
        const currentName = layer.feature.properties.label_name;
        const newName = prompt(_('edit_label_name'), currentName);
        if (newName !== null && newName.trim() !== "") {
            this.applyLabelRename(layer, newName);
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

        const icon = L.divIcon({
            className: 'geo-label-marker',
            // [Fix] Width: Fit Content (no min-width, nowrap)
            // [Fix] Centering: translate(-50%, -50%) ensures the label stays centered on the point without hardcoded anchors.
            html: `<div class="p-1 rounded shadow-sm text-center" style="width: max-content; min-width: auto; font-size:12px; line-height:1.2; white-space: nowrap; border: 1px solid; ${bgStyle}; transform: translate(-50%, -50%);">${htmlContent}</div>`,
            iconSize: [0, 0],
            iconAnchor: [0, 0]
        });

        // Critical Fix: Only markers support setIcon
        if (layer.setIcon) {
            layer.setIcon(icon);
        } else {
            console.warn("[GeoLabel] unexpected layer type for label (no setIcon):", layer);
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
        const layersToRemove = [];
        labelGroup.eachLayer(l => {
            const parentId = l.feature?.properties?.parent_node_id;

            // Criteria for Deletion:
            // - Has parent_id but parent not found (Broken Link)
            // - No parent_id (Unknown origin, likely error fallback)
            // - Name is "Label" (Default) AND parent missing (Strong indicator of error)
 
            if (!parentId || !validParentIds.has(parentId)) {
                // console.warn(`[Cleanup] Removing Orphan Label: ${l.feature?.properties?.label_name || 'Unnamed'} (Parent: ${parentId})`);
                layersToRemove.push(l);
            }
        });

        layersToRemove.forEach(l => {
            labelGroup.removeLayer(l);
            // Also remove from map if visible
            if (this.parent.map.hasLayer(l)) this.parent.map.removeLayer(l);
        }); 
        if (layersToRemove.length > 0) {
            // console.log(`[Cleanup] ${layersToRemove.length} orphan labels removed. Syncing with DB...`);
            this.parent.saveDesign(['label_aux'], true);
        }
    }
}
