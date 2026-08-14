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

        // 색 해석은 AoTGeoTheme 하나로 (도형·라벨·위젯과 같은 규칙).
        const themeColor = window.AoTGeoTheme.deviceColor(devType);

        // 처음부터 감춘 채로 만든다 — "일단 보이게 만들고 나중에 끄기" 는
        // 사용자가 꺼 둔 장치가 로딩 때 한 번 번쩍이는 원인이다(설정은 지도가
        // 만들어지기 전에 이미 읽혀 있다, AoTGeoDesign 생성자 참조).
        const isVisible = !(this.parent && this.parent.isShapeTypeHidden &&
                            this.parent.isShapeTypeHidden('aot_device'));

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

        // 색 해석은 AoTGeoTheme 하나로 (도형·라벨·위젯과 같은 규칙).
        const themeColor = window.AoTGeoTheme.deviceColor(devType);

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

        // 세부 타입 → 테마 키 변환은 AoTGeoTheme 한 곳에서 한다. 예전에는
        // 'function' 만 특별 취급하고 나머지는 문자열 비교였는데, 복합장치는
        // device_type='device' / 테마 키 'device_unit' 이라 그 비교로는
        // 영원히 걸리지 않는다.
        const isMatch = (l) => {
            const type = l.feature?.properties?.device_type;
            if (!type) return false;
            return window.AoTGeoTheme.normalizeDeviceType(type) === targetType;
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

    /**
     * 장치 **종류별**(입력/출력/함수/복합) 표시 토글.
     *
     * 여기서 직접 감추지 않는다 — 상태만 바꾸고 반영은 모드 토글과 **같은
     * 경로**(`_applyShapeVisibility`)에 맡긴다.
     *
     * 예전에는 이 함수가 자기만의 방식으로 감췄다: 레이어를 그룹에서 **물리적으로
     * 빼내 곁주머니(`_hiddenLayerBag`)에 넣고**, 다시 켤 때 집어넣으며 opacity/
     * display 를 되살렸다. 그래서 모드 토글("aot device 지도에서 보기")과 겹치면
     * 서로를 덮어썼다:
     *
     *   - 종류를 감추면 그 레이어는 그룹에서 사라져, 모드 토글이 아예 보지
     *     못한다(상태가 두 곳으로 갈린다).
     *   - 종류를 다시 켜면 **모드가 꺼져 있는지 보지 않고** 되살려서, 감춰 둔
     *     장치가 되살아난다.
     *   - 게다가 `_isLayerHidden` 은 종류별 상태를 `AOT_GEO_CONFIG.theme_config`
     *     **스냅샷**에서 읽었다 — 화면에서 방금 바꾼 값이 아니라 페이지를 열 때의
     *     값이라, 다음 반영에서 옛 상태로 되돌려 버렸다.
     *
     * 이제 종류별 상태는 `parent._hiddenDeviceKinds` 한 곳에 살고, 감추는 방법도
     * 하나뿐이다(GL visibility / DOM display). 두 토글은 AND 로 합쳐진다 —
     * 둘 중 하나라도 끄면 안 보인다.
     */
    setDeviceTypeVisibility(targetType, isVisible) {
        if (!targetType) return;
        const parent = this.parent;
        if (!parent._hiddenDeviceKinds) parent._hiddenDeviceKinds = new Set();
        if (isVisible) parent._hiddenDeviceKinds.delete(targetType);
        else parent._hiddenDeviceKinds.add(targetType);

        // 곁주머니는 더 쓰지 않는다. 이전 판에서 빼둔 레이어가 남아 있으면
        // 그룹에 돌려놓는다 — 안 그러면 그 장치는 영영 안 보인다.
        this._drainHiddenLayerBag();

        parent._applyShapeVisibility();
    }

    /** 옛 곁주머니에 남은 레이어를 원래 그룹으로 돌려놓는다(한 번만 의미 있다). */
    _drainHiddenLayerBag() {
        const bag = this.parent._hiddenLayerBag;
        if (!bag) return;
        Object.keys(bag).forEach(k => {
            (bag[k] || []).forEach(({ group, layer }) => {
                try { if (group && group.addLayer) group.addLayer(layer); } catch (e) {}
            });
            bag[k] = [];
        });
    }
}
