/**
 * AoTMapLibrePopup.js
 * MapLibre GL 팝업 모듈 (Leaflet.Popup 호환)
 * 
 * @version 1.0.0
 * @author AoT Team
 */

(function(global) {
  'use strict';

  /**
   * AoTMapLibrePopup Class
   * Leaflet 스타일 bindPopup/openPopup/closePopup API 제공
   */
  class AoTMapLibrePopup {
    /**
     * Create a new Popup
     * @param {Object} options - Popup options
     */
    constructor(options = {}) {
      this._options = Object.assign({}, this._getDefaultOptions(), options);
      this._map = null;
      this._popup = null;
      this._content = null;
      this._latlng = null;
      this._sourceLayer = null;
      this._eventHandlers = {};
    }

    /**
     * Get default options
     * @private
     */
    _getDefaultOptions() {
      return {
        closeButton: true,
        closeOnClick: true,
        maxWidth: 300,
        minWidth: 100,
        className: '',
        offset: [0, 0]
      };
    }

    // ========== Static Factory ==========

    /**
     * Create popup instance
     * @param {Object} options
     * @returns {AoTMapLibrePopup}
     */
    static create(options = {}) {
      return new AoTMapLibrePopup(options);
    }

    // ========== Lifecycle ==========

    /**
     * Add popup to map
     * @param {maplibregl.Map} map
     * @returns {AoTMapLibrePopup}
     */
    addTo(map) {
      this._map = map;
      return this;
    }

    /**
     * Set map reference
     * @param {maplibregl.Map} map
     * @returns {AoTMapLibrePopup}
     */
    setMap(map) {
      this._map = map;
      return this;
    }

    // ========== Content ==========

    /**
     * Set popup content
     * @param {string|Function} content - HTML content or content generator
     * @returns {AoTMapLibrePopup}
     */
    setContent(content) {
      this._content = content;
      if (this._popup) {
        const html = typeof content === 'function' ? content() : content;
        this._popup.setHTML(html);
      }
      return this;
    }

    /**
     * Set HTML content (alias for setContent)
     * @param {string} html
     * @returns {AoTMapLibrePopup}
     */
    setHTML(html) {
      return this.setContent(html);
    }

    // ========== Position ==========

    /**
     * Set popup location
     * @param {Array|Object} latlng - [lng, lat] or {lat, lng}
     * @returns {AoTMapLibrePopup}
     */
    setLatLng(latlng) {
      this._latlng = this._normalizeLatLng(latlng);
      if (this._popup) {
        this._popup.setLngLat(this._latlng);
      }
      return this;
    }

    /**
     * Normalize lat/lng to [lng, lat] format
     * @private
     */
    _normalizeLatLng(latlng) {
      if (Array.isArray(latlng)) {
        // [lng, lat] format
        if (latlng.length === 2 && typeof latlng[0] === 'number') {
          return latlng;
        }
        // [[lng, lat]] format (polygon ring)
        return latlng[0] || latlng;
      }
      // {lat, lng} format
      if (typeof latlng.lat === 'number' && typeof latlng.lng === 'number') {
        return [latlng.lng, latlng.lat];
      }
      // {lat, lng} with different property names
      if (typeof latlng.latitude === 'number' && typeof latlng.longitude === 'number') {
        return [latlng.longitude, latlng.latitude];
      }
      return latlng;
    }

    // ========== Leaflet API Compatibility ==========

    /**
     * Bind popup to a layer (Leaflet API)
     * @param {string|Function} content - Popup content
     * @returns {AoTMapLibrePopup}
     */
    bindPopup(content) {
      this._content = content;
      this._bound = true;
      return this;
    }

    /**
     * Open popup (Leaflet API)
     * @param {Object} layer - Source layer
     * @param {Object} latlng - Optional location
     * @returns {AoTMapLibrePopup}
     */
    openPopup(layer, latlng) {
      if (!this._map) {
        console.warn('[AoTMapLibrePopup] Map not set');
        return this;
      }

      // Get location
      let location = latlng;
      if (!location && layer) {
        // Try to get from layer
        if (layer.getLatLng) {
          location = layer.getLatLng();
        } else if (layer.feature && layer.feature.geometry && layer.feature.geometry.type === 'Point') {
          const coords = layer.feature.geometry.coordinates;
          location = { lat: coords[1], lng: coords[0] };
        }
      }

      if (!location && this._latlng) {
        location = this._latlng;
      }

      if (!location) {
        console.warn('[AoTMapLibrePopup] No location specified');
        return this;
      }

      // Create popup if needed
      if (!this._popup) {
        this._popup = new maplibregl.Popup(this._options)
          .setLngLat(this._normalizeLatLng(location));
        
        const html = typeof this._content === 'function' ? this._content(layer) : this._content;
        if (html) {
          this._popup.setHTML(html);
        }
        
        this._popup.addTo(this._map);
      } else {
        this._popup.setLngLat(this._normalizeLatLng(location));
        if (!this._popup.isOpen()) {
          this._popup.addTo(this._map);
        }
      }

      this._sourceLayer = layer;
      this._fire('open', { popup: this, layer: layer });
      
      return this;
    }

    /**
     * Close popup (Leaflet API)
     * @returns {AoTMapLibrePopup}
     */
    closePopup() {
      if (this._popup) {
        this._popup.remove();
        this._fire('close', { popup: this });
      }
      return this;
    }

    /**
     * Toggle popup (Leaflet API)
     * @param {Object} layer
     * @param {Object} latlng
     * @returns {AoTMapLibrePopup}
     */
    togglePopup(layer, latlng) {
      if (this._popup && this._popup.isOpen()) {
        return this.closePopup();
      } else {
        return this.openPopup(layer, latlng);
      }
    }

    /**
     * Check if popup is open
     * @returns {boolean}
     */
    isOpen() {
      return this._popup && this._popup.isOpen();
    }

    // ========== Direct MapLibre Methods ==========

    /**
     * Show popup at specific location on map
     * @param {Array|Object} coords - [lng, lat] or {lat, lng}
     * @param {string} content - HTML content
     * @returns {AoTMapLibrePopup}
     */
    showAt(coords, content) {
      if (!this._map) {
        console.warn('[AoTMapLibrePopup] Map not set');
        return this;
      }

      this._popup = new maplibregl.Popup(this._options)
        .setLngLat(this._normalizeLatLng(coords))
        .setHTML(content || this._content || '')
        .addTo(this._map);

      return this;
    }

    /**
     * Update popup position
     * @param {Array|Object} coords
     * @returns {AoTMapLibrePopup}
     */
    updatePosition(coords) {
      if (this._popup) {
        this._popup.setLngLat(this._normalizeLatLng(coords));
      }
      return this;
    }

    // ========== Event System ==========

    /**
     * Add event listener
     * @param {string} eventType
     * @param {Function} handler
     * @returns {AoTMapLibrePopup}
     */
    on(eventType, handler) {
      if (!this._eventHandlers[eventType]) {
        this._eventHandlers[eventType] = [];
      }
      this._eventHandlers[eventType].push(handler);
      return this;
    }

    /**
     * Remove event listener
     * @param {string} eventType
     * @param {Function} handler
     * @returns {AoTMapLibrePopup}
     */
    off(eventType, handler) {
      if (this._eventHandlers[eventType]) {
        this._eventHandlers[eventType] = this._eventHandlers[eventType].filter(h => h !== handler);
      }
      return this;
    }

    /**
     * Fire event
     * @private
     */
    _fire(eventType, data) {
      if (this._eventHandlers[eventType]) {
        this._eventHandlers[eventType].forEach(handler => {
          try {
            handler(data);
          } catch (e) {
            console.error(`[AoTMapLibrePopup] Event handler error:`, e);
          }
        });
      }
    }

    // ========== Cleanup ==========

    /**
     * Remove popup from map
     * @returns {AoTMapLibrePopup}
     */
    remove() {
      if (this._popup) {
        this._popup.remove();
        this._popup = null;
      }
      return this;
    }

    /**
     * Get underlying MapLibre popup
     * @returns {maplibregl.Popup|null}
     */
    getPopup() {
      return this._popup;
    }

    /**
     * Destroy popup
     */
    destroy() {
      this.remove();
      this._map = null;
      this._content = null;
      this._sourceLayer = null;
      this._eventHandlers = {};
    }
  }

  // Export
  global.AoTMapLibrePopup = AoTMapLibrePopup;

})(typeof window !== 'undefined' ? window : global);
