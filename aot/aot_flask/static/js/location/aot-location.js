/**
 * AoT Location Picker Logic
 * Pure MapLibre GL implementation (Leaflet-free)
 */

class AoTLocationPicker {
    constructor(mapId, options = {}) {
        this.mapId = mapId;
        this.map = null;
        this.marker = null;

        this.initialLat = options.lat || 37.5665;
        this.initialLng = options.lng || 126.9780;
        this.hasInitial = !isNaN(options.lat) && !isNaN(options.lng);
    }

    init() {
        console.log("AoTLocationPicker initializing (Pure MapLibre)...");

        // 1. Check MapLibre availability
        if (typeof maplibregl === 'undefined') {
            console.error('MapLibre GL not loaded!');
            return;
        }

        // 2. Initialize MapLibre Map
        this.map = new maplibregl.Map({
            container: this.mapId,
            style: {
                version: 8,
                sources: {
                    'osm': {
                        type: 'raster',
                        tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'],
                        tileSize: 256,
                        attribution: '© OpenStreetMap'
                    }
                },
                layers: [{
                    id: 'osm',
                    type: 'raster',
                    source: 'osm',
                    minzoom: 0,
                    maxzoom: 19
                }]
            },
            center: [this.initialLng, this.initialLat],
            zoom: 13
        });

        // 3. Add navigation control
        this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

        // 4. Initial Marker
        if (this.hasInitial) {
            this._placeMarker(this.initialLng, this.initialLat);
        }

        // 5. Bind Events
        this.map.on('click', (e) => {
            this._placeMarker(e.lngLat.lng, e.lngLat.lat);
        });

        document.getElementById('btn-confirm-location').addEventListener('click', () => {
            this._confirmSelection();
        });
    }

    _placeMarker(lng, lat) {
        // Remove existing marker
        if (this.marker) {
            this.marker.remove();
        }

        // Create new marker element
        const el = document.createElement('div');
        el.style.cssText = `
            width: 24px;
            height: 24px;
            background-color: #995aff;
            border: 3px solid white;
            border-radius: 50%;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
            cursor: move;
        `;

        // Create draggable marker
        this.marker = new maplibregl.Marker({
            element: el,
            draggable: true
        })
        .setLngLat([lng, lat])
        .addTo(this.map);

        // Handle drag events
        this.marker.on('dragstart', () => {
            this.map.dragPan.disable();
        });

        this.marker.on('dragend', () => {
            this.map.dragPan.enable();
            const pos = this.marker.getLngLat();
            this._updateUI(pos.lat, pos.lng);
        });

        this.map.flyTo([lat, lng], this.map.getZoom());
        this._updateUI(lat, lng);
    }

    _updateUI(lat, lng) {
        const display = document.getElementById('selected-coords');
        display.innerText = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
        display.classList.remove('text-danger');
        display.classList.add('text-success');

        document.getElementById('btn-confirm-location').disabled = false;
    }

    _confirmSelection() {
        if (!this.marker) return;

        const pos = this.marker.getLngLat();
        const result = { lat: pos.lat, lng: pos.lng };

        console.log("Location Selected:", result);

        // Communication Strategy:
        // 1. If opened via window.open (popup), use window.opener
        // 2. If iframe, use window.parent
        // 3. Else, maybe just alert/console for now (standalone mode)

        if (window.opener && !window.opener.closed) {
            // Send message
            window.opener.postMessage({ type: 'AOT_LOCATION_SELECTED', payload: result }, '*');
            window.close();
        } else {
            alert(`Selected: ${result.lat}, ${result.lng}\n(No parent window found to return value)`);
        }
    }
}
