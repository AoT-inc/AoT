/**
 * Shared Controller for AoT Map Search
 * Handles the interaction between the Search Web Component, the Map, and the UI (Toggle Button, Overlay).
 */
(function() {
    if (window.AoTMapSearchController) return;

    class AoTMapSearchController {
        /**
         * @param {L.Map} map Leaflet Map instance
         * @param {Object} config Configuration object
         * @param {string} config.searchId ID of the <aot-map-search-fixed> element
         * @param {string} config.toggleBtnId ID of the button to toggle search
         * @param {string} config.overlayId ID of the container overlay
         * @param {string} [config.inputLatId] ID of Latitude Input (optional)
         * @param {string} [config.inputLngId] ID of Longitude Input (optional)
         * @param {L.Marker} [marker] Optional Leaflet marker to update instead of creating new
         */
        constructor(map, config, marker = null) {
            // console.log("[SearchController] Initializing with config:", config);
            this.map = map;
            this.searchComp = document.getElementById(config.searchId);
            this.toggleBtn = document.getElementById(config.toggleBtnId);
            this.overlay = document.getElementById(config.overlayId);
            this.inputLatId = config.inputLatId;
            this.inputLngId = config.inputLngId;
            this.marker = marker;

            /*
            console.log("[SearchController] Elements found:", {
                searchComp: !!this.searchComp,
                toggleBtn: !!this.toggleBtn,
                overlay: !!this.overlay
            });
            */

            this.init();
        }

        init() {
            if (this.toggleBtn && this.overlay) {
                // console.log("[SearchController] Adding click listener to toggle button");
                this.toggleBtn.addEventListener('click', () => {
                    // console.log("[SearchController] Toggle button clicked");
                    this.toggle();
                });
            } else {
                // console.error("[SearchController] Missing Toggle Button or Overlay elements!");
            }

            if (this.searchComp) {
                this.searchComp.addEventListener('location-selected', (e) => this.onLocationSelected(e));
                
                // [Context-Aware Search]
                // 1. Listen for Base Layer Changes
                this.map.on('baselayerchange', (e) => {
                    // Leaflet 'baselayerchange' event gives { layer: ILayer, name: string }
                    // Our AoTMapLoader attaches 'aot_id' (or 'aot_base_id') and 'aot_channel_id' to the layer instance.
                    const layer = e.layer;
                    if (layer && layer.aot_base_id) {
                        this.searchComp.setLayerId(layer.aot_base_id);
                    } else if (layer && layer.aot_id) {
                         this.searchComp.setLayerId(layer.aot_id);
                    } else {
                        // Fallback or Unknown (e.g. OSM Default)
                        this.searchComp.setLayerId(null);
                    }
                });

                // 2. Initial Layer Detection
                // If map already has a base layer (AoTMapLoader usually sets it)
                this.map.eachLayer((layer) => {
                    // Active base layers usually have 'aot_base_id' and are TileLayers
                    // This loop might find overlays too, but we prioritize base logic or last added.
                    // Better: Check activeBaseLayer if exposed, or rely on properties.
                    if (layer.aot_base_id && (layer.options && !layer.options.role || layer.options.role === 'base')) {
                        this.searchComp.setLayerId(layer.aot_base_id);
                    }
                });
            }
        }

        toggle() {
            // console.log("[SearchController] Toggling overlay. Current classes:", this.overlay.classList);
            if (this.overlay.classList.contains('d-none')) {
                this.overlay.classList.remove('d-none');
                // Force display to ensure it's visible if something else is hiding it
                this.overlay.style.display = 'flex';
                if (this.toggleBtn) this.toggleBtn.classList.add('text-primary');

                // [Fix] Auto-Focus Input
                if (this.searchComp && this.searchComp.shadowRoot) {
                    const input = this.searchComp.shadowRoot.getElementById('input');
                    if (input) {
                        setTimeout(() => input.focus(), 50); // Slight delay for visibility render
                    }
                }
            } else {
                this.overlay.classList.add('d-none');
                this.overlay.style.display = ''; // Reset inline style
                if (this.toggleBtn) this.toggleBtn.classList.remove('text-primary');
            }
        }

        onLocationSelected(e) {
            const { lat, lng, name } = e.detail || {};

            if (isNaN(lat) || isNaN(lng) || lat == null || lng == null) {
                console.error('[SearchController] invalid coordinates:', e.detail);
                return;
            }

            // Detect MapLibre shim: _originalMap is set by AoTMapLibreCompatShim
            const nativeMap = this.map._originalMap || null;
            const isMapLibre = !!nativeMap;

            // 1. Map Action — MapLibre uses {center:[lng,lat]} (lng first); Leaflet uses [lat,lng]
            if (isMapLibre) {
                nativeMap.flyTo({ center: [lng, lat], zoom: 16, duration: 1 });
            } else {
                this.map.flyTo([lat, lng], 16);
            }

            // 2. Marker / Popup
            if (this.marker) {
                this.marker.setLatLng([lat, lng]);
                if (this.marker.getPopup()) this.marker.setPopupContent(name);
                else this.marker.bindPopup(name);
                this.marker.openPopup();
            } else if (isMapLibre && window.maplibregl) {
                // MapLibre popup — auto-closes after 4s
                const popup = new maplibregl.Popup({ closeOnClick: true, offset: [0, -6] })
                    .setLngLat([lng, lat])
                    .setHTML('<div style="font-size:13px;max-width:220px;">' + name + '</div>')
                    .addTo(nativeMap);
                setTimeout(() => { try { popup.remove(); } catch (ex) {} }, 4000);
            }

            // 3. Form Update (if configured)
            if (this.inputLatId && this.inputLngId) {
                const latInput = document.getElementById(this.inputLatId);
                const lngInput = document.getElementById(this.inputLngId);
                if (latInput) latInput.value = lat;
                if (lngInput) lngInput.value = lng;
            }

            // 4. Close UI
            this.toggle();
        }
    }

    // Export for global usage
    window.AoTMapSearchController = AoTMapSearchController;
})();
