/**
 * AoT Map Modal Controller (MapLibre / Vector)
 * Wraps logic for initializing maps within Bootstrap modals (Input/Output/Function options).
 *
 * Migrated from Leaflet to native MapLibre-GL (no L.* dependencies, no AoTMapLoader).
 * Drawing uses AoTMapLibreDraw if available; otherwise drawing is silently skipped.
 */
(function () {
    if (window.AoTMapModalController) return;

    var DEFAULT_STYLE = {
        version: 8,
        sources: {
            'osm-base': {
                type: 'raster',
                tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                tileSize: 256,
                attribution: '© OpenStreetMap'
            }
        },
        layers: [{ id: 'osm-base', type: 'raster', source: 'osm-base' }]
    };

    function buildLabelEl(name) {
        var wrap = document.createElement('div');
        wrap.className = 'aot-map-label-marker';
        wrap.innerHTML =
            '<div class="label-box" style="' +
                'background:white;padding:4px 10px;border-radius:20px;' +
                'border:2px solid #3366ff;box-shadow:0 2px 6px rgba(0,0,0,0.3);' +
                'white-space:nowrap;width:max-content;font-weight:600;' +
                'color:#333;font-size:13px;cursor:move;' +
            '">' + (name || 'Device') + '</div>';
        return wrap;
    }

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

            this.map = null;
            this.marker = null;
            this.draw = null;

            this._init();
        }

        _init() {
            const config = window.AOT_GEO_CONFIG || {};
            const defaultLat = parseFloat(config.default_lat) || 37.5665;
            const defaultLng = parseFloat(config.default_lng) || 126.9780;
            const defaultZoom = parseFloat(config.zoom) || 13;

            const $el = $('#' + this.mapId);
            if (!$el.length) return;
            if ($el.hasClass('aot-map-init-done')) return;
            $el.addClass('aot-map-init-done');

            // For the same mapId (= same card), destroy the previous controller first if it is still alive.
            // When saving refreshModalOptions, the map macro <script> re-runs and the old #map_X
            // gets replaced, but the old controller remains, duplicating map/markers and leaking the WebGL context.
            AoTMapModalController._instances = AoTMapModalController._instances || {};
            const _prev = AoTMapModalController._instances[this.mapId];
            if (_prev && _prev !== this) {
                try { if (typeof _prev.destroy === 'function') _prev.destroy(); } catch (e) { /* silent */ }
            }
            AoTMapModalController._instances[this.mapId] = this;

            if (!this.uniqueId) this.uniqueId = $el.data('unique-id');
            if (!this.latId) this.latId = $el.data('lat-id');
            if (!this.lngId) this.lngId = $el.data('lng-id');
            if (!this.formId) this.formId = $el.data('form-id');
            if (!this.options.type && $el.data('type')) this.options.type = $el.data('type');
            if (!this.mapConfigId) this.mapConfigId = $el.data('map-config-id');

            const parseVal = (val, def) => {
                if (val === 'null' || val === null || val === undefined) return def;
                const n = parseFloat(val);
                return isNaN(n) ? def : n;
            };

            let lat = (this.initLat === undefined) ? parseVal($el.data('init-lat'), defaultLat) : this.initLat;
            let lng = (this.initLng === undefined) ? parseVal($el.data('init-lng'), defaultLng) : this.initLng;
            let zoom = (this.zoom === undefined) ? parseVal($el.data('zoom'), defaultZoom) : this.zoom;

            if (lat === null || isNaN(lat)) lat = defaultLat;
            if (lng === null || isNaN(lng)) lng = defaultLng;
            const safeZoom = zoom || defaultZoom;

            if (typeof maplibregl === 'undefined') {
                console.error('[AoTMapModal] maplibre-gl not loaded');
                return;
            }

            try {
                this.map = new maplibregl.Map({
                    container: this.mapId,
                    style: DEFAULT_STYLE,
                    center: [lng, lat],
                    zoom: safeZoom,
                    doubleClickZoom: false,
                    attributionControl: false
                });
            } catch (e) {
                console.error('[AoTMapModal] Map create failed:', e);
                return;
            }

            try {
                this.map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
            } catch (e) { /* silent */ }

            // Force resize after initial mount
            requestAnimationFrame(() => {
                try { this.map.resize(); } catch (e) { /* silent */ }
            });

            // Marker as a label (draggable)
            const initialName = this._getDeviceName() || 'Device';
            const labelEl = buildLabelEl(initialName);
            this.marker = new maplibregl.Marker({ element: labelEl, draggable: true, anchor: 'center' })
                .setLngLat([lng, lat])
                .addTo(this.map);

            this._attachLabelDblClick(labelEl);

            // Drawing tools intentionally disabled in option modals (location-pick only).

            this._bindMapEvents();
            this._bindZoomEvents();
            this._bindSearch();
            this._bindLabelSync();
            this._bindModalEvents();
            this._bindCenterTool();
        }

        _initDrawControl() {
            if (!window.AoTMapLibreDraw || typeof window.AoTMapLibreDraw.create !== 'function') return;
            try {
                this.draw = window.AoTMapLibreDraw.create(this.map, {
                    displayControlsDefault: false,
                    controls: { polygon: true, line_string: true, point: false, trash: true }
                });
                if (this.draw && typeof this.draw.init === 'function') {
                    Promise.resolve(this.draw.init({ autoLoadDraw: true })).then(() => {
                        if (typeof this.draw.on === 'function') {
                            this.draw.on('draw.create', () => this._saveShapes());
                            this.draw.on('draw.update', () => this._saveShapes());
                            this.draw.on('draw.delete', () => this._saveShapes());
                        }
                    });
                }
            } catch (e) {
                console.warn('[AoTMapModal] Draw init failed:', e);
            }
        }

        _loadShapes(jsonString) {
            try {
                const shapes = JSON.parse(jsonString);
                if (Array.isArray(shapes) && this.draw) {
                    shapes.forEach((shape) => {
                        try { this.draw.add(shape); } catch (e) { /* silent */ }
                    });
                }
            } catch (e) { /* silent */ }
        }

        _renderGeoJSON(features) {
            if (!Array.isArray(features) || !this.draw) return;
            features.forEach((shape) => {
                try { this.draw.add(shape); } catch (e) { /* silent */ }
            });
        }

        _saveShapes() {
            if (!this.uniqueId) return;
            const fc = (this.draw && typeof this.draw.getAll === 'function') ? this.draw.getAll() : { features: [] };
            const features = (fc && fc.features) || [];
            const shapesJson = JSON.stringify(features);

            const $mapEl = $('#' + this.mapId);
            const $container = $mapEl.closest('.modal-content, .grid-stack-item-content, form');
            let $hiddenInput = $container.find('input[name="drawing_shapes"]');
            if (!$hiddenInput.length) $hiddenInput = $('#input-drawing-shapes-' + this.uniqueId);
            if ($hiddenInput.length) $hiddenInput.val(shapesJson).trigger('change');

            if (this.mapConfigId) {
                $.ajax({
                    url: '/api/geo/overlays',
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({
                        map_uuid: this.mapConfigId,
                        type: 'device',
                        device_id: this.uniqueId,
                        features: features
                    })
                });
            }
        }

        _loadShapesFromAPI() {
            if (!this.uniqueId || !this.mapConfigId) return;
            $.ajax({
                url: '/api/geo/overlays',
                method: 'GET',
                data: { map_uuid: this.mapConfigId, type: 'device', device_id: this.uniqueId },
                success: (res) => {
                    if (res && res.features) this._renderGeoJSON(res.features);
                }
            });
        }

        _getDeviceName() {
            let $input = null;
            if (this.formId) {
                const $form = $('#' + this.formId);
                $input = $form.find('.input-device-name');
                if (!$input.length) $input = $form.find('input[name="device_name"]');
                if (!$input.length) $input = $form.find('input[name="name"]');
            }
            if ((!$input || !$input.length) && this.mapId) {
                const $mapEl = $('#' + this.mapId);
                const $container = $mapEl.closest('.modal-content, .grid-stack-item-content, form');
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
            this.marker.on('dragend', function () {
                const ll = self.marker.getLngLat();
                self._updateInputs(ll.lat, ll.lng);
            });
            this.map.on('click', function (e) {
                // Skip if a draw mode is active
                if (self.draw && self.draw.draw && typeof self.draw.draw.getMode === 'function') {
                    try {
                        const mode = self.draw.draw.getMode();
                        if (mode && mode !== 'simple_select' && mode !== 'static') return;
                    } catch (ex) { /* silent */ }
                }
                self.marker.setLngLat([e.lngLat.lng, e.lngLat.lat]);
                self._updateInputs(e.lngLat.lat, e.lngLat.lng);
            });
            this.map.on('dblclick', function (e) {
                self.marker.setLngLat([e.lngLat.lng, e.lngLat.lat]);
                self._updateInputs(e.lngLat.lat, e.lngLat.lng);
                self.map.panTo([e.lngLat.lng, e.lngLat.lat]);
            });
        }

        _updateInputs(lat, lng) {
            if (this.latId) {
                const $el = $('#' + this.latId);
                if ($el.length) $el.val(lat.toFixed(6)).trigger('change');
            }
            if (this.lngId) {
                const $el = $('#' + this.lngId);
                if ($el.length) $el.val(lng.toFixed(6)).trigger('change');
            }

            const $mapEl = $('#' + this.mapId);
            const $container = $mapEl.closest('.modal-content, .grid-stack-item-content, form, .card-body');
            if ($container.length) {
                $container.find('input[name="latitude"], input[name$="latitude"]').not('#' + this.latId).val(lat.toFixed(6)).trigger('change');
                $container.find('input[name="longitude"], input[name$="longitude"]').not('#' + this.lngId).val(lng.toFixed(6)).trigger('change');
            }

            this._updateKmaGrid(lat, lng);
            this._saveLocation(lat, lng);
        }

        _updateKmaGrid(lat, lng) {
            if (!this.mapId) return;
            const $mapEl = $('#' + this.mapId);
            const $container = $mapEl.closest('.modal-content, .grid-stack-item-content, form, .card-body');
            if (!$container.length) return;
            const $nx = $container.find('input[name="nx"], input[name$="nx"], input[name*="[nx]"]');
            const $ny = $container.find('input[name="ny"], input[name$="ny"], input[name*="[ny]"]');
            if ($nx.length || $ny.length) {
                $.ajax({
                    url: '/api/tools/kma_lookup',
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ lat: lat, lon: lng }),
                    success: (res) => {
                        if (res && res.ok) {
                            if ($nx.length) $nx.val(res.nx).trigger('change');
                            if ($ny.length) $ny.val(res.ny).trigger('change');
                        }
                    }
                });
            }
        }

        _saveLocation(lat, lng) {
            if (!this.uniqueId || !this.options.type) return;
            $.ajax({
                url: '/api/geo/device/location',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({
                    unique_id: this.uniqueId,
                    type: this.options.type,
                    lat: lat,
                    lng: lng
                })
            });
        }

        _bindZoomEvents() {
            const $btnIn = $('#btn-zoom-in-' + this.uniqueId);
            const $btnOut = $('#btn-zoom-out-' + this.uniqueId);
            if ($btnIn.length) $btnIn.on('click', () => this.map.zoomIn());
            if ($btnOut.length) $btnOut.on('click', () => this.map.zoomOut());
        }

        _bindCenterTool() {
            const $btn = $('#btn-center-label-' + this.uniqueId);
            if ($btn.length) {
                $btn.on('click', () => {
                    const c = this.map.getCenter();
                    this.marker.setLngLat([c.lng, c.lat]);
                    this._updateInputs(c.lat, c.lng);
                });
            }
        }

        _bindSearch() {
            if (!window.AoTMapSearchController) return;
            const native = this.map;
            // Shim: AoTMapSearchController checks `_originalMap` to detect MapLibre.
            const shimMap = {
                _originalMap: native,
                on: (ev, cb) => native.on(ev, cb),
                eachLayer: () => { /* no-op for MapLibre */ },
                flyTo: (opts) => native.flyTo(opts)
            };
            const self = this;
            const markerShim = {
                setLatLng: (latlng) => {
                    const lat = Array.isArray(latlng) ? latlng[0] : latlng.lat;
                    const lng = Array.isArray(latlng) ? latlng[1] : latlng.lng;
                    self.marker.setLngLat([lng, lat]);
                    self._updateInputs(lat, lng);
                },
                getPopup: () => self.marker.getPopup ? self.marker.getPopup() : null,
                setPopupContent: (html) => {
                    const p = self.marker.getPopup ? self.marker.getPopup() : null;
                    if (p) p.setHTML(html);
                },
                bindPopup: (html) => {
                    if (typeof self.marker.setPopup === 'function') {
                        self.marker.setPopup(new maplibregl.Popup({ offset: 12 }).setHTML(html));
                    }
                },
                openPopup: () => {
                    if (typeof self.marker.togglePopup === 'function') self.marker.togglePopup();
                }
            };
            try {
                new AoTMapSearchController(shimMap, {
                    searchId: 'search-comp-' + this.uniqueId,
                    toggleBtnId: 'btn-search-' + this.uniqueId,
                    overlayId: 'search-overlay-' + this.uniqueId,
                    inputLatId: this.latId,
                    inputLngId: this.lngId
                }, markerShim);
            } catch (e) {
                console.warn('[AoTMapModal] Search bind failed:', e);
            }
        }

        _attachLabelDblClick(labelEl) {
            const self = this;
            labelEl.addEventListener('dblclick', function (e) {
                e.stopPropagation();
                const $nameInput = self._findNameInput();
                if (!$nameInput || !$nameInput.length) return;
                const currentName = $nameInput.val();
                const newName = prompt((window._ ? window._('Edit label name:') : 'Edit label name:'), currentName);
                if (newName !== null) $nameInput.val(newName).trigger('change');
            });
        }

        _findNameInput() {
            let $nameInput = null;
            if (this.formId) {
                const $form = $('#' + this.formId);
                $nameInput = $form.find('.input-device-name');
                if (!$nameInput.length) $nameInput = $form.find('input[name="device_name"]');
                if (!$nameInput.length) $nameInput = $form.find('input[name="name"]');
            }
            if ((!$nameInput || !$nameInput.length) && this.mapId) {
                const $mapEl = $('#' + this.mapId);
                const $container = $mapEl.closest('.modal-content, .grid-stack-item-content, form');
                if ($container.length) {
                    $nameInput = $container.find('.input-device-name');
                    if (!$nameInput.length) $nameInput = $container.find('input[name="device_name"]');
                    if (!$nameInput.length) $nameInput = $container.find('input[name="name"]');
                }
            }
            return $nameInput;
        }

        _bindLabelSync() {
            const $nameInput = this._findNameInput();
            if (!$nameInput || !$nameInput.length) return;

            const updateLabel = () => {
                // Even after the modal is closed and destroy()ed, a handler still attached to the input
                // may fire, so guard against null marker (prevents TypeError crash)
                if (!this.marker) return;
                const elNode = this.marker.getElement();
                if (!elNode) return;
                const name = $nameInput.val() || 'Device';
                const box = elNode.querySelector('.label-box');
                if (box) {
                    box.textContent = name;
                } else {
                    elNode.innerHTML = buildLabelEl(name).innerHTML;
                }
            };

            // Repeatedly opening/closing the modal accumulates handlers on the same input
            // (symptom: "settings dialog call count increasing"), causing duplicate firing/crashes.
            // Remove existing bindings via namespace first, then rebind,
            // and keep a reference so it can be released in destroy().
            this._$labelInput = $nameInput;
            $nameInput.off('keyup.aotlabel change.aotlabel')
                      .on('keyup.aotlabel change.aotlabel', updateLabel);
            updateLabel();
        }

        _bindModalEvents() {
            const self = this;
            const $modal = $('#' + this.mapId).closest('.modal');
            const mapContainer = document.getElementById(this.mapId);

            const resizeMap = () => {
                if (!self.map) return;
                requestAnimationFrame(() => {
                    try {
                        self.map.resize();
                        if (self.marker) self.map.panTo(self.marker.getLngLat());
                    } catch (e) { /* silent */ }
                });
            };

            if ($modal.length) {
                $modal.on('shown.bs.modal.aotmap', resizeMap);
                if ($modal.hasClass('show')) resizeMap();
            }

            if (mapContainer && window.ResizeObserver) {
                this.resizeObserver = new ResizeObserver((entries) => {
                    for (let i = 0; i < entries.length; i++) {
                        const r = entries[i].contentRect;
                        if (r.width > 0 && r.height > 0) {
                            requestAnimationFrame(() => {
                                try { if (self.map) self.map.resize(); } catch (e) { /* silent */ }
                            });
                        }
                    }
                });
                this.resizeObserver.observe(mapContainer);
            }
        }

        /**
         * Release the WebGL context and all bound resources so the browser can
         * reclaim the GPU slot. Call from the modal's hidden.bs.modal handler
         * to avoid hitting the per-browser WebGL context cap (~16).
         */
        destroy() {
            try { if (this.resizeObserver) this.resizeObserver.disconnect(); } catch (e) { /* silent */ }
            this.resizeObserver = null;

            const $el = $('#' + this.mapId);
            const $modal = $el.closest('.modal');
            if ($modal.length) {
                try { $modal.off('.aotmap'); } catch (e) { /* silent */ }
            }

            // Release the label sync handler - if not released, dead handlers accumulate
            // and cause a null marker crash on the next 'change'.
            try { if (this._$labelInput) this._$labelInput.off('keyup.aotlabel change.aotlabel'); } catch (e) { /* silent */ }
            this._$labelInput = null;

            try { if (this.marker && typeof this.marker.remove === 'function') this.marker.remove(); } catch (e) { /* silent */ }
            this.marker = null;

            try { if (this.draw && typeof this.draw.destroy === 'function') this.draw.destroy(); } catch (e) { /* silent */ }
            this.draw = null;

            try { if (this.map && typeof this.map.remove === 'function') this.map.remove(); } catch (e) { /* silent */ }
            this.map = null;

            // Unregister itself from the registry (only if it was registered)
            try {
                if (AoTMapModalController._instances &&
                    AoTMapModalController._instances[this.mapId] === this) {
                    delete AoTMapModalController._instances[this.mapId];
                }
            } catch (e) { /* silent */ }

            $el.removeClass('aot-map-init-done');
        }

        /**
         * Scans the document for uninitialized map containers and initializes them.
         * Skips containers inside Bootstrap modals — those use lazy init bound to
         * shown.bs.modal so they don't exhaust the WebGL context pool on page load.
         */
        static initAll() {
            $('.map-container').not('.aot-map-init-done').each(function () {
                const $el = $(this);
                if ($el.closest('.modal').length) return; // lazy-init owned by macro
                const id = $el.attr('id');
                if (id) new AoTMapModalController({ mapId: id });
            });
        }
    }

    window.AoTMapModalController = AoTMapModalController;
})();
