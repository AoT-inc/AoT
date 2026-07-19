/**
 * aot-geo-devices.js
 * Device Integration and Management for AoTGeoDesign
 */

class AoTGeoDevices {
    constructor(parent) {
        this.parent = parent;
        this.map = parent.map; 
        this.layers = []; // Initialize layers array
        
        // Active Device State
        this.activeDevice = null;
        this._colorSaveTimer = null; // Debounce for color saving

        // Reload devices when tab becomes visible (handles name changes from other tabs/pages)
        this._visibilityHandler = () => {
            if (document.visibilityState === 'visible' && this.parent.currentMapUuid) {
                this.loadMapDevices();
            }
        };
        document.addEventListener('visibilitychange', this._visibilityHandler);
    }

    destroy() {
        document.removeEventListener('visibilitychange', this._visibilityHandler);
    }

    /**
     * Load Map Devices from API
     */
    loadMapDevices() {
        if (!this.parent.currentMapUuid) {
            // console.warn("Cannot load devices: No Map UUID");
            return;
        }

 
        // console.log(`[GeoDevices] Loading devices for Map UUID: ${this.parent.currentMapUuid}`);
        $.ajax({
            url: `/api/geo/devices?map_uuid=${this.parent.currentMapUuid}`, // [Fix] Pass map_uuid to get overlays
            method: 'GET',
            success: (res) => {
                if (res.ok && res.devices) {
                    // [Fix] Remove client-side filtering to allow "Palette" behavior (Show All System Devices)
                    // The Backend now returns all devices. We render what we have.
                    // 'is_on_map' or valid coordinates will determine visibility.
                    this._renderDevices(res.devices);
                }
            },
            error: (e) => {
                console.error('[GeoDevices] loadMapDevices failed:', e.status, e.responseText);
            }
        });
    }

    _renderDevices(devices) {
        // Clear existing
        if (this.parent.layerStorage['aot_device']) {
            this.parent.layerStorage['aot_device'].clearLayers();
            // Ensure group is still connected to map after clear (refresh persistence fix)
            if (!this.parent.map.hasLayer(this.parent.layerStorage['aot_device'])) {
                this.parent.map.addLayer(this.parent.layerStorage['aot_device']);
            }
        } else {
            this.parent.layerStorage['aot_device'] = new AoTGeoLayerGroup('aot_device');
            this.parent.layerStorage['aot_device'].addTo(this.parent.map);
        }

        // [Fix] Support Multiple Markers per Device (Per Channel)
        const uniqueDevs = new Map();
        devices.forEach(dev => {
            // [Fix] Use 'unique_id' (which is uuid::ch) as the unique key to allow multiple channels for one device
            const key = dev.unique_id;
            
            if (!uniqueDevs.has(key)) {
                // [Fix] Map device_name to name if name is missing
                const devObj = { ...dev };
                if (!devObj.name && devObj.device_name) devObj.name = devObj.device_name;
                uniqueDevs.set(key, devObj);
            }
        });

        uniqueDevs.forEach(dev => {
            // [Fix] Only render markers for devices specifically added to this map design
            // (prevents unselected channels from appearing if the base device has global coordinates)
            // [Fix] Use null-safe check — lat/lng of 0 would fail falsy test
            if (dev.lat != null && dev.lng != null && dev.is_on_map) {
                this.createDeviceMarker(dev);
            }
        });

        // Refresh visibility
        if (this.parent.panel && typeof this.parent.panel.refreshDeviceVisibility === 'function') {
            this.parent.panel.refreshDeviceVisibility(); // Callback to Panel if exists
        }
    }

    /**
     * Place Device on Map (from Panel or Initial Load)
     */
    placeDeviceOnMap(device, latlng = null) {
        if (!this.parent.layerStorage['aot_device']) {
            this.parent.layerStorage['aot_device'] = new AoTGeoLayerGroup('aot_device').addTo(this.parent.map);
        }

        // Check if already exists
        const existing = this.findDeviceMarker(device.unique_id);
        if (existing) {
            if (latlng) {
                // Move it
                existing.setLatLng(latlng);
                this._saveDeviceLocation(device, latlng); // Auto-save on manual place
                // Pan to it
                this.parent.map.panTo(latlng);
            } else {
                // Just Pan
                this.parent.map.panTo(existing.getLatLng());
            }
            // Flash effect?
            return;
        }

        // Create New
        const center = latlng || this.parent.map.getCenter();
        const marker = this.createDeviceMarker(device, center);

        // Save initial location
        this._saveDeviceLocation(device, center);
    }

    /**
     * Check if device is already utilized on the map
     */
    isDeviceOnMap(uniqueId) {
        return !!this.findDeviceMarker(uniqueId);
    }

    findDeviceMarker(uniqueId) {
        let found = null;
        if (this.parent.layerStorage['aot_device']) {
            this.parent.layerStorage['aot_device'].eachLayer(l => {
                const featId = l.feature?.properties?.unique_id;
                if (!featId) return;

                // [Fix] Robust Matching (Round 19): Handle 'uuid' vs 'uuid::0' consistency
                const normalize = id => (id && String(id).endsWith('::0')) ? id.slice(0, -3) : id;
                if (normalize(featId) === normalize(uniqueId)) {
                    found = l;
                }
            });
        }
        return found;
    }

    /**
     * Remove Device from Map (and reset location in DB)
     */
    removeDeviceFromMap(uniqueId) {
        const layersToRemove = [];

        // 1. Storage
        if (this.parent.layerStorage['aot_device']) {
            this.parent.layerStorage['aot_device'].eachLayer(l => {
                if (l.feature?.properties?.unique_id === uniqueId) {
                    layersToRemove.push({ layer: l, group: this.parent.layerStorage['aot_device'] });
                }
            });
        }

        // 2. Editor
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            window.AoTMapEditor.featureGroup.eachLayer(l => {
                if (l.feature?.properties?.unique_id === uniqueId) {
                    layersToRemove.push({ layer: l, group: window.AoTMapEditor.featureGroup });
                }
            });
        }

        let removedCount = 0;
        layersToRemove.forEach(item => {
            const l = item.layer;
            const group = item.group;

            // [Sync] Persist removal to backend
            const type = l.feature.properties.device_type;
            // console.log(`[Remove] Removing layer for ${uniqueId} from ${group === this.parent.layerStorage['aot_device'] ? 'Storage' : 'Editor'}, Syncing removal...`);
 
            if (type) {
                this._saveDeviceLocation(
                    { unique_id: uniqueId, type: type },
                    { lat: null, lng: null }
                );
            }

            group.removeLayer(l);
            removedCount++;
        });
 
        // console.log(`[Remove] Removed ${removedCount} layers for ${uniqueId}`);
        // Refresh Panel UI (check marks) logic is typically handled by Panel listening to events or callback,
        // but here we might rely on the Panel refreshing itself or being told.
        if (this.parent.panel && this.parent.panel._loadDevices) {
            // this.parent.panel._loadDevices(); // Aggressive reload? 
            // Maybe explicitly update UI state?
            // Since this operation is likely triggered FROM the panel (context menu), 
            // the panel might update itself after calling this. 
        }
    }

    _makeIcon(className, html) {
        return {
            className,
            html,
            createIcon() {
                const el = document.createElement('div');
                el.className = this.className || '';
                el.style.cssText = 'width:0;height:0;overflow:visible;';
                el.innerHTML = this.html || '';
                return el;
            }
        };
    }

    createDeviceMarker(dev, latlng = null) {
        const pos = latlng || [dev.lat, dev.lng];

        // Determine Border/Theme Color
        const devType = dev.type;
        const functionTypes = ['trigger', 'pid', 'conditional', 'custom', 'generic_function'];

        // [Fix] Centralized Theme Lookup (DB over localStorage)
        const theme = window.AOT_GEO_CONFIG?.theme_config || {};
        let themeColor = theme[devType] || theme['device'] || '#995aff';
        
        if (functionTypes.includes(devType)) {
            themeColor = theme['function'] || theme['device'] || themeColor;
        }

        // Check Initial Visibility (Always visible by default in Design Mode unless filtered)
        let isVisible = true;

        // Pill Style Icon
        const iconHtml = `<div class="aot-map-label-marker" style="
                    background: white; 
                    padding: 4px 10px; 
                    border-radius: 20px; 
                    border: 2px solid ${themeColor}; 
                    opacity: ${isVisible ? 1 : 0};
                    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                    white-space: nowrap;
                    width: max-content;
                    font-weight: 600;
                    color: #333;
                    font-size: 13px;
                    transform: translate(-50%, -50%);
                    display: ${isVisible ? 'flex' : 'none'};
                    align-items: center;
                    justify-content: center;
                ">${dev.name || 'Device'}</div>`;

        const marker = new AoTGeoMarker(pos, {
            draggable: !this.parent.isLocked && this.parent.activeMode === 'aot_device',
            icon: this._makeIcon('aot-device-marker-wrapper', iconHtml),
            zIndexOffset: 2000 // Middle Priority (Below Site Label, Above Length)
        });

        marker.feature = {
            type: 'Feature',
            properties: {
                aot_type: 'aot_device',
                unique_id: dev.unique_id,
                channel_id: dev.channel_id, // [New] Store channel_id for per-channel persistence
                node_id: dev.unique_id, // [Fix] Set node_id for Label Linking
                device_type: dev.type,
                name: dev.name
            }
        };

        // Standard dragend for direct location update
        marker.on('dragend', (e) => {
            const newPos = marker.getLatLng();
            this._saveDeviceLocation(dev, newPos);
        });

        // Click Handler for Activation
        marker.on('click', (e) => {
            if (e && e.stopPropagation) e.stopPropagation();

            // If already active, deactivate (Toggle)
            if (this.activeDevice && this.activeDevice.layer === marker) {
                this.deactivateDevice();
            } else {
                this.activateDevice(marker, dev);
            }
        });

        this.parent.layerStorage['aot_device'].addLayer(marker);

        // If hidden mode is on, hide it
        if (this.parent.isHidden) {
            if (this.parent.map.hasLayer(marker)) this.parent.map.removeLayer(marker);
        } else {
            if (!this.parent.map.hasLayer(this.parent.layerStorage['aot_device'])) {
                this.parent.map.addLayer(this.parent.layerStorage['aot_device']);
            }
        }

        return marker;
    }

    /**
     * Activate Device Logic
     */
    activateDevice(layer, device) {
        // 1. Deactivate current if exists
        this.deactivateDevice();

        // 2. Set Active State
        this.activeDevice = {
            layer: layer,
            unique_id: device.unique_id,
            channel_id: device.channel_id, // [New] Store channel_id for shape linking
            type: device.type,
            name: device.name
        };

        // 3. Apply Active Style (Invert colors)
        this._updateMarkerStyle(layer, true);

        // 4. Update UI Context (Toast)
        if (this.parent.ui) {
            this.parent.ui.showToast(`'${device.name}' 장치가 활성화되었습니다. 도형을 그리면 자동으로 연결됩니다.`, 'info');
        }
    }

    deactivateDevice() {
        if (!this.activeDevice) return;

        const layer = this.activeDevice.layer;
        
        // 1. Revert Style
        if (layer) {
            this._updateMarkerStyle(layer, false);
        }

        // 2. Clear State
        this.activeDevice = null;
        
        // 3. UI Update (Quietly)
    }

    _updateMarkerStyle(layer, isActive) {
        if (!layer || !layer.feature) return;
        
        const dev = {
            type: layer.feature.properties.device_type,
            name: layer.feature.properties.name
        };

        const devType = dev.type;
        const functionTypes = ['trigger', 'pid', 'conditional', 'custom', 'generic_function'];

        // [Fix] Centralized Theme Lookup
        const theme = window.AOT_GEO_CONFIG?.theme_config || {};
        let themeColor = theme[devType] || theme['device'] || '#995aff';
        
        if (functionTypes.includes(devType)) {
            themeColor = theme['function'] || theme['device'] || themeColor;
        }

        // Check visibility (Maintain current element display state)
        let isVisible = true;
        const el = layer.getElement ? layer.getElement() : null;
        if (el && el.style.display === 'none') isVisible = false;

        // Style Definition
        const style = isActive ? `
            background: ${themeColor}; 
            color: white;
            border: 2px solid white;
        ` : `
            background: white; 
            color: #333;
            border: 2px solid ${themeColor}; 
        `;

        const iconHtml = `<div class="aot-map-label-marker" style="
                    ${style}
                    padding: 4px 10px; 
                    border-radius: 20px; 
                    opacity: ${isVisible ? 1 : 0};
                    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                    white-space: nowrap;
                    width: max-content;
                    font-weight: 600;
                    font-size: 13px;
                    transform: translate(-50%, -50%);
                    display: ${isVisible ? 'flex' : 'none'};
                    align-items: center;
                    justify-content: center;
                ">${dev.name || 'Device'}</div>`;

        layer.setIcon(this._makeIcon('aot-device-marker-wrapper', iconHtml));
    }

    _saveDeviceLocation(dev, latlng) {
        if (!this.parent.currentMapUuid) {
            console.warn('[GeoDevices] _saveDeviceLocation: no currentMapUuid — location not persisted');
            return;
        }

        // latlng.lat/lng may be null for removal (deletes GeoShape on server)
        const lat = latlng?.lat ?? null;
        const lng = latlng?.lng ?? null;
        const isRemoval = lat == null || lng == null;

        const payload = {
            unique_id: dev.unique_id,
            channel_id: dev.channel_id ?? 0,
            type: dev.device_type || dev.type,
            lat,
            lng,
            map_uuid: this.parent.currentMapUuid
        };

        $.ajax({
            url: '/api/geo/device/location',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload),
            success: (res) => {
                if (res && res.ok) {
                    // [Fix] Do NOT call loadMapDevices() here — it would clear all markers via
                    // clearLayers() then re-render from server. Any server-side issue would
                    // cause the just-placed marker to disappear.
                    // The marker from createDeviceMarker() is already at the correct position.
                    // loadMapDevices() on page load restores server-side state authoritatively.
                    // Invalidate panel's device cache so next modal open fetches fresh data
                    if (this.parent.panel) this.parent.panel.allDevices = null;
                    // Refresh panel device list (updates checkmarks; cached if allDevices present)
                    if (this.parent.panel && typeof this.parent.panel.refreshDeviceVisibility === 'function') {
                        this.parent.panel.refreshDeviceVisibility();
                    }
                } else {
                    console.error('[GeoDevices] Save failed:', res ? res.message : 'Unknown');
                }
            },
            error: (xhr) => {
                console.error('[GeoDevices] Save API error:', xhr.status, xhr.statusText);
            }
        });
    }

    updateMarkersInteractivity() {
        const isDraggable = !this.parent.isLocked && this.parent.activeMode === 'aot_device';
        if (this.parent.layerStorage['aot_device']) {
            this.parent.layerStorage['aot_device'].eachLayer(l => {
                if (l.setDraggable) l.setDraggable(isDraggable);
            });
        }
    }

    updateDeviceColor(targetType, newColor) {
        // [Fix] Update Global Config for immediate use
        if (!window.AOT_GEO_CONFIG) window.AOT_GEO_CONFIG = {};
        if (!window.AOT_GEO_CONFIG.theme_config) window.AOT_GEO_CONFIG.theme_config = {};
        window.AOT_GEO_CONFIG.theme_config[targetType] = newColor;

        // Define Function Subtypes
        const functionTypes = ['function', 'trigger', 'pid', 'conditional', 'custom', 'generic_function'];

        // Helper to check type match
        const isMatch = (l) => {
            const type = l.feature?.properties?.device_type;
            if (!type) return false;
            // Exact match or Group match
            if (targetType === 'function') return functionTypes.includes(type);
            return type === targetType;
        };

        // Helper to update style
        const update = (l) => {
            if (isMatch(l)) {
                // Check if active layer to maintain active style
                const isActive = (this.parent.activeLayer === l || (this.activeDevice && this.activeDevice.layer === l));
                
                // [Fix] Update Vector Style
                if (typeof this.parent.ui._setLayerStyle === 'function') {
                    this.parent.ui._setLayerStyle(l, isActive);
                }

                // [Fix] Maintain current visibility
                let isVisible = true;
                const el = l.getElement ? l.getElement() : null;
                if (el && el.style.display === 'none') isVisible = false;

                // Update Icon Border (Since _setLayerStyle only handles vector style)
                if (l.setIcon) {
                    const style = isActive ? `
                        background: ${newColor}; 
                        color: white;
                        border: 2px solid white;
                    ` : `
                        background: white; 
                        color: #333;
                        border: 2px solid ${newColor}; 
                    `;

                    const iconHtml = `<div class="aot-map-label-marker" style="
                        ${style}
                        padding: 4px 10px; 
                        border-radius: 20px; 
                        opacity: ${isVisible ? 1 : 0};
                        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                        white-space: nowrap;
                        width: max-content;
                        font-weight: 600;
                        font-size: 13px;
                        transform: translate(-50%, -50%);
                        display: ${isVisible ? 'flex' : 'none'};
                        align-items: center;
                        justify-content: center;
                    ">${l.feature.properties.name || 'Device'}</div>`;

                    l.setIcon(this._makeIcon('aot-device-marker-wrapper', iconHtml));
                }
            }
        };

        // 1. Storage
        if (this.parent.layerStorage['aot_device']) {
            this.parent.layerStorage['aot_device'].eachLayer(update);
        }
        if (this.parent.layerStorage['device']) {
            this.parent.layerStorage['device'].eachLayer(update);
        }

        // Update Features on Map (Vector & Markers)
        if (this.parent.overlayMaps && this.parent.overlayMaps.aot_device) {
            this.parent.overlayMaps.aot_device.eachLayer(update);
        }
        
        // 2. Editor
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            window.AoTMapEditor.featureGroup.eachLayer(update);
        }

        // Color save is handled by _handleThemeColorChange in panel.js (via /api/geo/settings).
        // Removed duplicate debounced save here to prevent double POST.
    }

    setDeviceTypeVisibility(targetType, isVisible) {
        // [Fix] Skip localStorage, rely on application state or backend if needed.
        // For Design Mode, we typically want visibility to be session-based or linked to layers.

        const functionTypes = ['function', 'trigger', 'pid', 'conditional', 'custom', 'generic_function'];

        // [Perf] Sidebag holds layers physically removed from FeatureGroups while hidden.
        // Avoids CSS-only hiding that left SVG/GL nodes in the layer tree (caused viewport slowdown).
        if (!this.parent._hiddenLayerBag) this.parent._hiddenLayerBag = {};
        const bag = this.parent._hiddenLayerBag;
        if (!bag[targetType]) bag[targetType] = [];

        const isMatch = (l) => {
            let type = l.feature?.properties?.device_type;
            
            // [Fix] Fallback: If device_type missing on shape, lookup via device_id link
            if (!type && l.feature?.properties?.device_id) {
                const marker = this.findDeviceMarker(l.feature.properties.device_id);
                if (marker && marker.feature && marker.feature.properties) {
                    type = marker.feature.properties.device_type;
                }
            }
            
            if (!type) {
                // [Fix] If still not found, check if the layer itself is an aot_device marker
                if (l.feature?.properties?.aot_type === 'aot_device') {
                    type = l.feature.properties.device_type;
                }
            }

            if (!type) return false;
            if (targetType === 'function') return functionTypes.includes(type);
            return type === targetType;
        };

        const updateVisibility = (l) => {
            if (isMatch(l)) {
                if (isVisible) {
                    // [Fix] Safe call for Markers
                    if (l.setOpacity) l.setOpacity(1);

                    // Re-render Icon for Markers to ensure correct opacity in style string
                    if (l.setIcon) {
                        const props = l.feature.properties;
                        const type = props.device_type || targetType; // Fallback

                        const theme = window.AOT_GEO_CONFIG?.theme_config || {};
                        let themeColor = theme[type] || theme['device'] || '#995aff';
                        if (functionTypes.includes(type)) themeColor = theme['function'] || theme['device'] || themeColor;

                        // Check if active
                        const isActive = (this.parent.activeLayer === l || (this.activeDevice && this.activeDevice.layer === l));
                        const style = isActive ? `background: ${themeColor}; color: white; border: 2px solid white;` : `background: white; color: #333; border: 2px solid ${themeColor};`;

                        const iconHtml = `<div class="aot-map-label-marker" style="
                            ${style}
                            padding: 4px 10px; 
                            border-radius: 20px; 
                            opacity: 1;
                            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                            white-space: nowrap;
                            width: max-content;
                            font-weight: 600;
                            font-size: 13px;
                            transform: translate(-50%, -50%);
                            display: flex;
                            align-items: center;
                            justify-content: center;
                        ">${props.name || 'Device'}</div>`;

                        l.setIcon(this._makeIcon('aot-device-marker-wrapper', iconHtml));
                    }

                    // [Fix] Safe call for DOM elements
                    const el = l.getElement ? l.getElement() : null;
                    if (el) el.style.display = '';

                    // [Fix] Style for Vector Shapes (Paths)
                    if (l.setStyle) l.setStyle({ opacity: 1, fillOpacity: 0.6 });
                } else {
                    if (l.setOpacity) l.setOpacity(0);

                    const el = l.getElement ? l.getElement() : null;
                    if (el) el.style.display = 'none';

                    if (l.setStyle) l.setStyle({ opacity: 0, fillOpacity: 0 });
                }
            }
        };

        // [Perf] Physically remove hidden layers from their containers; restore from sidebag when shown.
        const removeHidden = (group) => {
            if (!group) return;
            const toRemove = [];
            group.eachLayer(l => {
                if (isMatch(l)) toRemove.push(l);
            });
            toRemove.forEach(layer => {
                group.removeLayer(layer);
                bag[targetType].push({ group, layer });
            });
        };
        const restoreHidden = () => {
            const remaining = [];
            bag[targetType].forEach(({ group, layer }) => {
                if (group && group.addLayer) {
                    group.addLayer(layer);
                    updateVisibility(layer);
                } else {
                    remaining.push({ group, layer });
                }
            });
            bag[targetType] = remaining;
        };

        if (isVisible) {
            restoreHidden();
            if (this.parent.layerStorage['aot_device']) this.parent.layerStorage['aot_device'].eachLayer(updateVisibility);
            if (this.parent.layerStorage['device']) this.parent.layerStorage['device'].eachLayer(updateVisibility);
            if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) window.AoTMapEditor.featureGroup.eachLayer(updateVisibility);
        } else {
            removeHidden(this.parent.layerStorage['aot_device']);
            removeHidden(this.parent.layerStorage['device']);
            if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
                removeHidden(window.AoTMapEditor.featureGroup);
            }
        }
    }
}
