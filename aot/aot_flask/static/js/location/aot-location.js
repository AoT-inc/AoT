/**
 * AoT Location Picker Logic
 * Simplified map interaction for selecting coordinates.
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
        console.log("AoTLocationPicker initializing...");

        // 1. Initialize Leaflet Map
        this.map = L.map(this.mapId).setView([this.initialLat, this.initialLng], 13);

        // Base Layer (OSM)
        // Ideally should respect global settings, but hardcoded for MVP simplicity/robustness
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap'
        }).addTo(this.map);

        // 2. Initial Marker
        if (this.hasInitial) {
            this._placeMarker(this.initialLat, this.initialLng);
        }

        // 3. Bind Events
        this.map.on('click', (e) => {
            this._placeMarker(e.latlng.lat, e.latlng.lng);
        });

        document.getElementById('btn-confirm-location').addEventListener('click', () => {
            this._confirmSelection();
        });
    }

    _placeMarker(lat, lng) {
        if (this.marker) {
            this.marker.setLatLng([lat, lng]);
        } else {
            this.marker = L.marker([lat, lng], { draggable: true }).addTo(this.map);
            this.marker.on('dragend', (e) => {
                const pos = e.target.getLatLng();
                this._updateUI(pos.lat, pos.lng);
            });
        }
        this.map.panTo([lat, lng]);
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

        const pos = this.marker.getLatLng();
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
