/**
 * AoTMapLibreTooltip.js
 * MapLibre GL 툴팁 모듈 (Leaflet.Tooltip 호환)
 * 
 * @version 1.0.0
 * @author AoT Team
 */

(function(global) {
  'use strict';

  /**
   * AoTMapLibreTooltip Class
   * Leaflet 스타일 bindTooltip API 제공
   */
  class AoTMapLibreTooltip {
    /**
     * Create a new Tooltip
     * @param {Object} options - Tooltip options
     */
    constructor(options = {}) {
      this._options = Object.assign({}, this._getDefaultOptions(), options);
      this._map = null;
      this._tooltip = null;
      this._content = null;
      this._sourceLayer = null;
      this._eventHandlers = {};
      this._permanent = this._options.permanent || false;
    }

    /**
     * Get default options
     * @private
     */
    _getDefaultOptions() {
      return {
        closeButton: false,
        closeOnClick: false,
        showOnHover: true,
        offset: [0, 10],
        direction: 'top',
        permanent: false,
        sticky: false,
        opacity: 0.9,
        className: 'aot-maplibre-tooltip',
        maxWidth: 200,
        minWidth: 50
      };
    }

    // ========== Static Factory ==========

    /**
     * Create tooltip instance
     * @param {Object} options
     * @returns {AoTMapLibreTooltip}
     */
    static create(options = {}) {
      return new AoTMapLibreTooltip(options);
    }

    // ========== Lifecycle ==========

    /**
     * Add tooltip to map
     * @param {maplibregl.Map} map
     * @returns {AoTMapLibreTooltip}
     */
    addTo(map) {
      this._map = map;
      return this;
    }

    /**
     * Set map reference
     * @param {maplibregl.Map} map
     * @returns {AoTMapLibreTooltip}
     */
    setMap(map) {
      this._map = map;
      return this;
    }

    // ========== Content ==========

    /**
     * Set tooltip content
     * @param {string|Function} content - HTML content or content generator
     * @returns {AoTMapLibreTooltip}
     */
    setContent(content) {
      this._content = content;
      if (this._tooltip) {
        const html = typeof content === 'function' ? content() : content;
        this._tooltip.setHTML(html);
      }
      return this;
    }

    /**
     * Set HTML content
     * @param {string} html
     * @returns {AoTMapLibreTooltip}
     */
    setHTML(html) {
      return this.setContent(html);
    }

    // ========== Leaflet API Compatibility ==========

    /**
     * Bind tooltip to a layer (Leaflet API)
     * @param {string|Function} content - Tooltip content
     * @param {Object} options - Tooltip options
     * @returns {AoTMapLibreTooltip}
     */
    bindTooltip(content, options = {}) {
      this._content = content;
      this._options = Object.assign({}, this._options, options);
      this._bound = true;
      return this;
    }

    /**
     * Open tooltip (Leaflet API)
     * @param {Object} layer - Source layer
     * @param {Object} latlng - Optional location
     * @returns {AoTMapLibreTooltip}
     */
    openTooltip(layer, latlng) {
      if (!this._map) {
        console.warn('[AoTMapLibreTooltip] Map not set');
        return this;
      }

      // Get location
      let location = latlng;
      if (!location && layer) {
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
        console.warn('[AoTMapLibreTooltip] No location specified');
        return this;
      }

      // Create tooltip if needed
      if (!this._tooltip) {
        this._tooltip = new maplibregl.Popup(Object.assign({}, this._options, {
          closeButton: false,
          closeOnClick: false
        }))
          .setLngLat(this._normalizeLatLng(location));
        
        const html = typeof this._content === 'function' ? this._content(layer) : this._content;
        if (html) {
          this._tooltip.setHTML(html);
        }
        
        this._tooltip.addTo(this._map);
      } else {
        this._tooltip.setLngLat(this._normalizeLatLng(location));
        if (!this._tooltip.isOpen()) {
          this._tooltip.addTo(this._map);
        }
      }

      this._sourceLayer = layer;
      this._fire('open', { tooltip: this, layer: layer });
      
      return this;
    }

    /**
     * Close tooltip (Leaflet API)
     * @returns {AoTMapLibreTooltip}
     */
    closeTooltip() {
      if (this._tooltip) {
        this._tooltip.remove();
        this._fire('close', { tooltip: this });
      }
      return this;
    }

    /**
     * Toggle tooltip (Leaflet API)
     * @param {Object} layer
     * @param {Object} latlng
     * @returns {AoTMapLibreTooltip}
     */
    toggleTooltip(layer, latlng) {
      if (this._tooltip && this._tooltip.isOpen()) {
        return this.closeTooltip();
      } else {
        return this.openTooltip(layer, latlng);
      }
    }

    /**
     * Check if tooltip is open
     * @returns {boolean}
     */
    isOpen() {
      return this._tooltip && this._tooltip.isOpen();
    }

    // ========== Helper Methods ==========

    /**
     * Normalize lat/lng to [lng, lat] format
     * @private
     */
    _normalizeLatLng(latlng) {
      if (Array.isArray(latlng)) {
        if (latlng.length === 2 && typeof latlng[0] === 'number') {
          return latlng;
        }
        return latlng[0] || latlng;
      }
      if (typeof latlng.lat === 'number' && typeof latlng.lng === 'number') {
        return [latlng.lng, latlng.lat];
      }
      return latlng;
    }

    // ========== Event System ==========

    /**
     * Add event listener
     * @param {string} eventType
     * @param {Function} handler
     * @returns {AoTMapLibreTooltip}
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
     * @returns {AoTMapLibreTooltip}
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
            console.error(`[AoTMapLibreTooltip] Event handler error:`, e);
          }
        });
      }
    }

    // ========== Cleanup ==========

    /**
     * Remove tooltip from map
     * @returns {AoTMapLibreTooltip}
     */
    remove() {
      if (this._tooltip) {
        this._tooltip.remove();
        this._tooltip = null;
      }
      return this;
    }

    /**
     * Get underlying MapLibre popup (tooltip uses popup internally)
     * @returns {maplibregl.Popup|null}
     */
    getPopup() {
      return this._tooltip;
    }

    /**
     * Destroy tooltip
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
  global.AoTMapLibreTooltip = AoTMapLibreTooltip;

})(typeof window !== 'undefined' ? window : global);
