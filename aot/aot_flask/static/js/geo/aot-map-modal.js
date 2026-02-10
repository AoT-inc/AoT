/**
 * AoT Map Modal Controller
 * Wraps logic for initializing maps within Bootstrap modals (Input/Output/Function options).
 */
(function() {
    if (window.AoTMapModalController) return;

    class AoTMapModalController {
    constructor(options) {
        this.options = options || {};
        this.mapId = this.options.mapId;
        this.uniqueId = this.options.uniqueId;
        this.latId = this.options.latId;
        this.lngId = this.options.lngId;
        this.initLat = this.options.initLat;
        this.initLng = this.options.initLng;
        this.zoom = this.options.zoom;
        this.formId = this.options.formId;
        this.mapConfigId = this.options.mapConfigId;

        // Dependencies

        // Dependencies
        this.marker = null;
        this.map = null;

        this._init();
    }

    _init() {
        // Resolve Global Defaults
        const config = window.AOT_GEO_CONFIG || {};
        const defaultLat = parseFloat(config.default_lat) || 37.5665;
        const defaultLng = parseFloat(config.default_lng) || 126.9780;
        const defaultZoom = parseFloat(config.zoom) || 13;

        // Fetch Data Attributes (if options are missing)
        const $el = $(`#${this.mapId}`);

        // [Fix] Mark as initialized to prevent double init
        if ($el.hasClass('aot-map-init-done')) return;
        $el.addClass('aot-map-init-done');

        // [Fix] Resolve missing options from Data Attributes (Auto-Init Support)
        if (!this.uniqueId) this.uniqueId = $el.data('unique-id');
        if (!this.latId) this.latId = $el.data('lat-id');
        if (!this.lngId) this.lngId = $el.data('lng-id');
        if (!this.formId) this.formId = $el.data('form-id');
        if (!this.options.type && $el.data('type')) this.options.type = $el.data('type');
        if (!this.mapConfigId) this.mapConfigId = $el.data('map-config-id');

        // Helper to parse 'null' string or actual null
        const parseVal = (val, def) => {
            if (val === 'null' || val === null || val === undefined) return def;
            return parseFloat(val);
        };

        // Priority: Option > Data Attribute > Global Default
        let lat = this.initLat;
        if (lat === undefined) lat = parseVal($el.data('init-lat'), defaultLat);

        let lng = this.initLng;
        if (lng === undefined) lng = parseVal($el.data('init-lng'), defaultLng);

        let zoom = this.zoom;
        if (zoom === undefined) zoom = parseVal($el.data('zoom'), defaultZoom);

        // Fallback for strict nulls from options
        if (lat === null) lat = defaultLat;
        if (lng === null) lng = defaultLng;

        const safeZoom = zoom || defaultZoom;

        // Initialize Map
        const mapInit = AoTMapLoader.initMap(this.mapId, 'geo_input_map', {
            center: [lat, lng],
            zoom: safeZoom,
            zoomControl: false, // 기본 줌 컨트롤 비활성화 (커스텀 버튼 사용)
            doubleClickZoom: false // 위치 이동 기능과 충돌 방지
        });
        this.map = mapInit.map;

        // Add Copyright
        if (window.AoTMapUtils && window.AoTMapUtils.addCopyrightControl) {
            window.AoTMapUtils.addCopyrightControl(this.map);
        }

        if (mapInit.layerControl && window.AoTMapControls && window.AoTMapControls.styleLayerControl) {
            window.AoTMapControls.styleLayerControl(mapInit.layerControl.getContainer());
        }

        // [Fix Iteration 4] Performance-oriented resize
        // Use requestAnimationFrame to catch the first render frame
        const forceResize = () => {
            if (this.map) {
                const container = this.map.getContainer();
                if (container.offsetWidth > 0 && container.offsetHeight > 0) {
                    requestAnimationFrame(() => {
                        this.map.invalidateSize();
                    });
                }
            }
        };
        // Attempt resize shortly after init, but rely on binding events for modal show
        requestAnimationFrame(forceResize);

        // Initialize Marker as a Label (divIcon)
        const initialName = this._getDeviceName() || "Device";
        this.marker = L.marker([lat, lng], {
            draggable: true,
            icon: L.divIcon({
                className: 'aot-map-label-marker',
                html: `<div class="label-box" style="
                    background: white; 
                    padding: 4px 10px; 
                    border-radius: 20px; 
                    border: 2px solid #3366ff; 
                    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                    white-space: nowrap;
                    width: max-content;
                    font-weight: 600;
                    color: #333;
                    font-size: 13px;
                    transform: translate(-50%, -50%);
                ">${initialName}</div>`,
                iconSize: null,
                iconAnchor: [0, 0]
            })
        }).addTo(this.map);

        this.drawnItems = new L.FeatureGroup();
        this.map.addLayer(this.drawnItems);
        this._initDrawControl();

        // Load Saved Shapes
        // Load Saved Shapes (Priority: API > Data Attribute)
        if (this.uniqueId && this.mapConfigId) {
             this._loadShapesFromAPI();
        } else {
             const shapesData = $el.attr('data-shapes');
             if (shapesData && shapesData !== 'None' && shapesData !== 'null') {
                 this._loadShapes(shapesData);
             }
        }

        // Bind Events
        this._bindMapEvents();
        this._bindZoomEvents(); // 추가
        this._bindSearch();
        this._bindLabelSync();
        this._bindModalEvents();
        this._bindCenterTool(); // 추가: 중심 이동 툴
    }

    _loadShapes(jsonString) {
        try {
            const shapes = JSON.parse(jsonString);
            if (Array.isArray(shapes)) {
                shapes.forEach(shape => {
                    const layer = L.geoJSON(shape, {
                        onEachFeature: (feature, layer) => {
                            // Restore ID
                            if (feature.properties && feature.properties.id) {
                                layer.aotId = feature.properties.id;
                            }
                            this.drawnItems.addLayer(layer);
                        }
                    });
                });
                // console.log(`[AoTMapModal] Loaded ${shapes.length} shapes.`);
            }
        } catch (e) {
            // console.error('[AoTMapModal] Failed to parse shapes data:', e);
        }
    }

    _initDrawControl() {
        if (!L.Control.Draw) return;

        // Initialize Draw Control
        const drawControl = new L.Control.Draw({
            draw: {
                polyline: {
                    shapeOptions: { color: '#f357a1', weight: 4 }
                },
                polygon: {
                    allowIntersection: false,
                    showArea: true,
                    shapeOptions: { color: '#bada55' }
                },
                rectangle: {
                    shapeOptions: { clickable: false }
                },
                circle: {
                    shapeOptions: { clickable: false }
                },
                marker: false, // 기존 위치 마커와 혼동 방지
                circlemarker: false
            },
            edit: {
                featureGroup: this.drawnItems,
                remove: true
            },
            position: 'topright' // 오른쪽 컨트롤러 위치
        });

        this.map.addControl(drawControl);

        // Event Handlers
        const self = this;
        this.map.on(L.Draw.Event.CREATED, function (e) {
            const type = e.layerType;
            const layer = e.layer;

            // ID 부여 (UUID v4-like or timestamp)
            const id = 'shape_' + new Date().getTime() + '_' + Math.random().toString(36).substr(2, 9);
            layer.aotId = id; // Store ID on layer logic
 
            // console.log(`[AoTMapModal] Shape Created: ${type}, ID: ${id}`);
 
            self.drawnItems.addLayer(layer);
            self._saveShapes();
        });

        this.map.on(L.Draw.Event.EDITED, function (e) {
            // console.log(`[AoTMapModal] Shapes Edited`);
            self._saveShapes();
        });
 
        this.map.on(L.Draw.Event.DELETED, function (e) {
            // console.log(`[AoTMapModal] Shapes Deleted`);
            self._saveShapes();
        });
    }

    /**
     * 그려진 도형 정보를 수집하여 저장합니다.
     */
    _saveShapes() {
        if (!this.uniqueId) return;

        const shapes = [];
        this.drawnItems.eachLayer(function (layer) {
            if (layer instanceof L.Marker) return; // Skip markers if any separate ones exist

            // Convert to GeoJSON
            let geoJson = layer.toGeoJSON();
            // Add custom ID
            geoJson.properties = geoJson.properties || {};
            if (layer.aotId) {
                 geoJson.properties.id = layer.aotId;
            } else if (layer.feature && layer.feature.properties && layer.feature.properties.id) {
                 geoJson.properties.id = layer.feature.properties.id;
            }
            shapes.push(geoJson);
        });

        const shapesJson = JSON.stringify(shapes);

        // 1. Update Hidden Input for Form Submission
        const $mapEl = $(`#${this.mapId}`);
        const $container = $mapEl.closest('.modal-content, .grid-stack-item-content, form');
        
        // Find specific hidden input for this device
        let $hiddenInput = $container.find(`input[name="drawing_shapes"]`);
        if (!$hiddenInput.length) {
             $hiddenInput = $(`#input-drawing-shapes-${this.uniqueId}`);
        }
        
        if ($hiddenInput.length) {
            $hiddenInput.val(shapesJson).trigger('change');
        }

        // 2. Real-time API Save (Target: GeoShape Table)
        if (this.mapConfigId) {
            const features = [];
            this.drawnItems.eachLayer(layer => {
                if (layer instanceof L.Marker) return;
                let geoJson = layer.toGeoJSON();
                geoJson.properties = geoJson.properties || {};
                if (layer.aotId) geoJson.properties.id = layer.aotId;
                if (layer.dbId) geoJson.properties.db_id = layer.dbId; // Critical for Update
                features.push(geoJson);
            });

            $.ajax({
                url: '/api/geo/overlays',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({
                    map_uuid: this.mapConfigId,
                    type: 'device',
                    device_id: this.uniqueId,
                    features: features
                }),
                success: (res) => { 
                    // console.log('[AoTMapModal] Shapes saved to GeoShape table'); 
                },
                error: (xhr) => { 
                    // console.error('[AoTMapModal] Save failed:', xhr); 
                }
            });
        }
    }

    _loadShapesFromAPI() {
        if (!this.uniqueId || !this.mapConfigId) return;
        
        // console.log(`[AoTMapModal] Loading shapes from API for device: ${this.uniqueId}`);
        $.ajax({
            url: '/api/geo/overlays',
            method: 'GET',
            data: {
                map_uuid: this.mapConfigId,
                type: 'device',
                device_id: this.uniqueId
            },
            success: (res) => {
                if (res && res.features) {
                    this._renderGeoJSON(res.features);
                }
            },
            error: (e) => {
                // console.error('[AoTMapModal] Load Error:', e)
            }
        });
    }

    _renderGeoJSON(features) {
         if (Array.isArray(features)) {
            features.forEach(shape => {
                L.geoJSON(shape, {
                    style: (feature) => {
                        let color = '#3388ff'; // Default Blue
                        const devType = feature.properties.device_type;
                        if (devType) {
                            const functionTypes = ['trigger', 'pid', 'conditional', 'custom', 'generic_function'];
                            let savedColor = localStorage.getItem(`aot_config_color_${devType}`);
                            if (!savedColor && functionTypes.includes(devType)) {
                                savedColor = localStorage.getItem('aot_config_color_function');
                            }
                            if (savedColor) color = savedColor;
                        }
                        return { 
                            color: color, 
                            weight: 2, 
                            opacity: 1, 
                            fillOpacity: 0.2 
                        };
                    },
                    onEachFeature: (feature, layer) => {
                         // Restore IDs
                         if (feature.properties) {
                             if (feature.properties.id) layer.aotId = feature.properties.id;
                             if (feature.properties.db_id) layer.dbId = feature.properties.db_id;
                         }
                         this.drawnItems.addLayer(layer);
                    }
                });
            });
            // console.log(`[AoTMapModal] Rendered ${features.length} shapes.`);
         }
    }

    _getDeviceName() {
        let $input = null;
        
        // Strategy 1: Form ID
        if (this.formId) {
            const $form = $(`#${this.formId}`);
            $input = $form.find('.input-device-name');
            if (!$input.length) $input = $form.find('input[name="device_name"]');
            if (!$input.length) $input = $form.find('input[name="name"]');
        }

        // Strategy 2: Relative (Fallback)
        if ((!$input || !$input.length) && this.mapId) {
            const $mapEl = $(`#${this.mapId}`);
            const $container = $mapEl.closest('.modal-content, .grid-stack-item-content, form'); // Broaden search
            if ($container.length) {
                $input = $container.find('.input-device-name');
                if (!$input.length) $input = $container.find('input[name="device_name"]');
                if (!$input.length) $input = $container.find('input[name="name"]');
            }
        }

        return ($input && $input.length) ? $input.val() : null;
    }

    _bindMapEvents() {
        const self = this;

        // Drag End -> Update Input Fields
        this.marker.on('dragend', function (e) {
            const ll = self.marker.getLatLng();
            self._updateInputs(ll.lat, ll.lng);
        });

        // Map Click (Single) -> Move Marker (UI Feedback)
        this.map.on('click', function (e) {
            self.marker.setLatLng(e.latlng);
            self._updateInputs(e.latlng.lat, e.latlng.lng);
        });

        // Map Double Click -> Move Marker & Update (UX requirement)
        this.map.on('dblclick', function (e) {
            self.marker.setLatLng(e.latlng);
            self._updateInputs(e.latlng.lat, e.latlng.lng);
            self.map.panTo(e.latlng);
        });
    }

    _updateInputs(lat, lng) {
        // 1. Update by specific ID (Hidden Fields usually)
        if (this.latId) {
            const $el = $(`#${this.latId}`);
            if ($el.length) $el.val(lat.toFixed(6)).trigger('change');
        }
        if (this.lngId) {
            const $el = $(`#${this.lngId}`);
            if ($el.length) $el.val(lng.toFixed(6)).trigger('change');
        }

        // 2. Update by Name within Scope (Visible Fields usually)
        // This handles cases where user sees a visible input (e.g., Custom Option) that isn't the primary ID
        const $mapEl = $(`#${this.mapId}`);
        const $container = $mapEl.closest('.modal-content, .grid-stack-item-content, form, .card-body');
        
        if ($container.length) {
            // Update all inputs named 'latitude' or 'longitude' in this context
            $container.find('input[name="latitude"], input[name$="latitude"]').not(`#${this.latId}`).val(lat.toFixed(6)).trigger('change');
            $container.find('input[name="longitude"], input[name$="longitude"]').not(`#${this.lngId}`).val(lng.toFixed(6)).trigger('change');
        }

        // [KMA Auto-fill] Check if nx/ny fields exist in the same container and update them
        this._updateKmaGrid(lat, lng);

        // 실시간 DB 저장 연동
        this._saveLocation(lat, lng);
    }

    /**
     * KMA 기상청 격자 좌표(nx, ny) 자동 변환 및 입력
     * Backend API (/api/tools/kma_lookup) 사용
     */
    _updateKmaGrid(lat, lng) {
        if (!this.mapId) return;
        const $mapEl = $(`#${this.mapId}`);
        const $container = $mapEl.closest('.modal-content, .grid-stack-item-content, form, .card-body');
        
        if (!$container.length) return;

        // Find potential NX/NY inputs (broad search: 'nx', 'custom_options-nx', 'custom_options[nx]')
        // Note: Using multiple selectors to cover various form structures
        const $nx = $container.find('input[name="nx"], input[name$="nx"], input[name*="[nx]"]');
        const $ny = $container.find('input[name="ny"], input[name$="ny"], input[name*="[ny]"]');

        if ($nx.length || $ny.length) {
            // console.log(`[AoTMapModal] Found KMA grid inputs, requesting lookup...`);
            $.ajax({
                url: '/api/tools/kma_lookup',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ lat: lat, lon: lng }),
                success: (res) => {
                    if (res && res.ok) {
                        if ($nx.length) $nx.val(res.nx).trigger('change');
                        if ($ny.length) $ny.val(res.ny).trigger('change');
                        // console.log(`[AoTMapModal] Auto-filled KMA Grid: ${res.nx}, ${res.ny}`);
                    }
                }
            });
        }
    }

    /**
     * 실시간 위치 정보를 백엔드 DB 컬럼에 직접 저장합니다.
     */
    _saveLocation(lat, lng) {
        if (!this.uniqueId || !this.options.type) return;
 
        // console.log(`[AoTMapModal] Requesting real-time location save for ${this.options.type}: ${this.uniqueId}`);
 
        $.ajax({
            url: '/api/geo/device/location',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                unique_id: this.uniqueId,
                type: this.options.type,
                lat: lat,
                lng: lng
            }),
            success: (res) => {
                if (res && res.ok) {
                    // console.log(`[AoTMapModal] Location saved to DB: ${lat}, ${lng}`);
                } else {
                    // console.error(`[AoTMapModal] DB Save failed:`, res ? res.message : 'Unknown error');
                }
            },
            error: (xhr) => {
                // console.error(`[AoTMapModal] API Error:`, xhr.statusText);
            }
        });
    }

    _bindZoomEvents() {
        const $btnIn = $(`#btn-zoom-in-${this.uniqueId}`);
        const $btnOut = $(`#btn-zoom-out-${this.uniqueId}`);
        
        if ($btnIn.length) $btnIn.on('click', () => this.map.zoomIn());
        if ($btnOut.length) $btnOut.on('click', () => this.map.zoomOut());
    }

    _bindCenterTool() {
        const btnId = `btn-center-label-${this.uniqueId}`;
        const $btn = $(`#${btnId}`);
        if ($btn.length) {
            $btn.on('click', () => {
                const center = this.map.getCenter();
                this.marker.setLatLng(center);
                this._updateInputs(center.lat, center.lng);
                // console.log(`[AoTMapModal] Label moved to map center: ${center.lat}, ${center.lng}`);
            });
        }
    }

    _bindSearch() {
        if (window.AoTMapSearchController) {
            new AoTMapSearchController(this.map, {
                searchId: `search-comp-${this.uniqueId}`,
                toggleBtnId: `btn-search-${this.uniqueId}`,
                overlayId: `search-overlay-${this.uniqueId}`,
                inputLatId: this.latId,
                inputLngId: this.lngId
            }, this.marker);
        }
    }

    _bindLabelSync() {
        let $nameInput = null;

        // Strategy 1: Form ID
        if (this.formId) {
            const $form = $(`#${this.formId}`);
            $nameInput = $form.find('.input-device-name');
            if (!$nameInput.length) $nameInput = $form.find('input[name="device_name"]');
            if (!$nameInput.length) $nameInput = $form.find('input[name="name"]');
        }

        // Strategy 2: Relative (Fallback)
        if ((!$nameInput || !$nameInput.length) && this.mapId) {
            const $mapEl = $(`#${this.mapId}`);
            const $container = $mapEl.closest('.modal-content, .grid-stack-item-content, form');
            if ($container.length) {
                // console.log(`[AoTMapModal] Using relative lookup for device name sync: ${this.uniqueId}`);
                $nameInput = $container.find('.input-device-name');
                if (!$nameInput.length) $nameInput = $container.find('input[name="device_name"]');
                if (!$nameInput.length) $nameInput = $container.find('input[name="name"]');
            }
        }
        
        const self = this;

        if ($nameInput && $nameInput.length) {
            const updateLabel = () => {
                const name = $nameInput.val() || "Device";
                
                // Update divIcon content
                const html = `<div class="label-box" style="
                    background: white; 
                    padding: 4px 10px; 
                    border-radius: 20px; 
                    border: 2px solid #3366ff; 
                    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                    white-space: nowrap;
                    width: max-content;
                    font-weight: 600;
                    color: #333;
                    font-size: 13px;
                    transform: translate(-50%, -50%);
                ">${name}</div>`;
                
                self.marker.setIcon(L.divIcon({
                    className: 'aot-map-label-marker',
                    html: html,
                    iconSize: null,
                    iconAnchor: [0, 0]
                }));
            };

            $nameInput.on('keyup change', () => {
                updateLabel();
            });
            updateLabel(); // Initial execution

            // Double Click on Label -> Prompt for Edit
            this.marker.on('dblclick', (e) => {
                L.DomEvent.stopPropagation(e);
                const currentName = $nameInput.val();
                const newName = prompt("라벨 명칭 수정:", currentName);
                if (newName !== null) {
                    $nameInput.val(newName).trigger('change');
                }
            });
        }
    }

    _bindModalEvents() {
        const self = this;
        const $modal = $(`#${this.mapId}`).closest('.modal');
        const mapContainer = document.getElementById(this.mapId);

        const resizeMap = () => {
            if (self.map) {
                const container = self.map.getContainer();
                // [Fix Iteration 4] Only invalidate if container has size
                if (container.offsetWidth > 0 && container.offsetHeight > 0) {
                    requestAnimationFrame(() => {
                        self.map.invalidateSize();
                        if (self.marker) self.map.panTo(self.marker.getLatLng());
                    });
                } else {
                    // Fallback: If size is 0 (still hidden?), try once more after a standard transition time
                    // but do NOT poll aggressively.
                    setTimeout(() => {
                         if (self.map) self.map.invalidateSize();
                    }, 200);
                }
            }
        };

        // 1. Traditional Modal Events
        if ($modal.length) {
            $modal.on('shown.bs.modal', resizeMap);
            if ($modal.hasClass('show')) resizeMap();
        }

        // 2. Modern ResizeObserver
        if (mapContainer && window.ResizeObserver) {
            this.resizeObserver = new ResizeObserver(entries => {
                for (let entry of entries) {
                    const { width, height } = entry.contentRect;
                    if (width > 0 && height > 0) {
                        // Use RAF to decouple from Observer loop
                        requestAnimationFrame(() => {
                             if (self.map) {
                                 self.map.invalidateSize();
                                 // Optional: Center marker if present to fixing panning issues
                                 // if (self.marker) self.map.panTo(self.marker.getLatLng());
                             }
                        });
                    }
                }
            });
            this.resizeObserver.observe(mapContainer);
        }
    }

    /**
     * Scans the document for uninitialized map containers and initializes them.
     */
    static initAll() {
        $('.map-container').not('.aot-map-init-done').each(function() {
            const $el = $(this);
            const id = $el.attr('id');
            if (id) {
                // console.log(`[AoTMapModal] Auto-initializing map: ${id}`);
                new AoTMapModalController({ mapId: id });
            }
        });
    }
}

// Make globally available
window.AoTMapModalController = AoTMapModalController;

})();
