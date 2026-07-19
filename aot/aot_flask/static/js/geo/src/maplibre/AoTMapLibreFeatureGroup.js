/**
 * AoTMapLibreFeatureGroup.js
 * MapLibre GL 피처 그룹 관리 모듈 (Leaflet.FeatureGroup 호환)
 * 
 * @version 1.0.0
 * @author AoT Team
 */

(function(global) {
  'use strict';

  /**
   * AoTMapLibreFeatureGroup Class
   * 다중 피처 그룹핑, 그룹 단위 표시/숨김, 스타일 일괄 적용
   */
  class AoTMapLibreFeatureGroup {
    /**
     * Create a new FeatureGroup
     */
    constructor() {
      this._layers = new Map();
      this._map = null;
      this._eventHandlers = {};
      this._style = {};
      this._visible = true;
    }

    // ========== Layer Management ==========

    /**
     * Add a layer to the group
     * @param {Object} layer - AoTMapLibreLayer or compatible object
     * @returns {AoTMapLibreFeatureGroup}
     */
    addLayer(layer) {
      const id = layer._sourceId || layer.id || 'layer-' + Date.now();
      this._layers.set(id, layer);
      
      // If already attached to map, add to map
      if (this._map && layer.addTo) {
        layer.addTo(this._map);
      }
      
      return this;
    }

    /**
     * Remove a layer from the group
     * @param {Object} layer - Layer to remove
     * @returns {AoTMapLibreFeatureGroup}
     */
    removeLayer(layer) {
      const id = layer._sourceId || layer.id;
      if (this._layers.has(id)) {
        const l = this._layers.get(id);
        if (l.remove) l.remove();
        this._layers.delete(id);
      }
      return this;
    }

    /**
     * Remove layer by ID
     * @param {string} id - Layer ID
     * @returns {AoTMapLibreFeatureGroup}
     */
    removeLayerById(id) {
      const layer = this._layers.get(id);
      if (layer) {
        if (layer.remove) layer.remove();
        this._layers.delete(id);
      }
      return this;
    }

    /**
     * Clear all layers
     * @returns {AoTMapLibreFeatureGroup}
     */
    clearLayers() {
      this._layers.forEach(layer => {
        if (layer.remove) layer.remove();
      });
      this._layers.clear();
      return this;
    }

    /**
     * Get all layers
     * @returns {Array}
     */
    getLayers() {
      return Array.from(this._layers.values());
    }

    /**
     * Get layer by ID
     * @param {string} id - Layer ID
     * @returns {Object|null}
     */
    getLayer(id) {
      return this._layers.get(id) || null;
    }

    /**
     * Has layer?
     * @param {Object} layer
     * @returns {boolean}
     */
    hasLayer(layer) {
      const id = layer._sourceId || layer.id;
      return this._layers.has(id);
    }

    // ========== Map Attachment ==========

    /**
     * Add group to map
     * @param {maplibregl.Map} map - MapLibre map instance
     * @returns {AoTMapLibreFeatureGroup}
     */
    addTo(map) {
      this._map = map;
      this._layers.forEach(layer => {
        if (layer.addTo) layer.addTo(map);
      });
      return this;
    }

    // ========== Iteration ==========

    /**
     * Iterate over all layers
     * @param {Function} callback - (layer, id) => void
     * @returns {AoTMapLibreFeatureGroup}
     */
    eachLayer(callback) {
      this._layers.forEach((layer, id) => callback(layer, id));
      return this;
    }

    // ========== Bounds ==========

    /**
     * Get combined bounds of all layers
     * @returns {Object|null}
     */
    getBounds() {
      const boundsList = [];
      
      this._layers.forEach(layer => {
        if (layer.getBounds) {
          const b = layer.getBounds();
          if (b && b.isValid && b.isValid()) {
            boundsList.push(b);
          }
        }
      });

      if (boundsList.length === 0) return null;

      let minLng = Infinity, minLat = Infinity;
      let maxLng = -Infinity, maxLat = -Infinity;

      boundsList.forEach(b => {
        const sw = b.getSouthWest(), ne = b.getNorthEast();
        minLng = Math.min(minLng, sw.lng);
        maxLng = Math.max(maxLng, ne.lng);
        minLat = Math.min(minLat, sw.lat);
        maxLat = Math.max(maxLat, ne.lat);
      });

      return {
        _southWest: { lat: minLat, lng: minLng },
        _northEast: { lat: maxLat, lng: maxLng },
        getSouthWest: function() { return this._southWest; },
        getNorthEast: function() { return this._northEast; },
        isValid: function() { return minLng !== Infinity; }
      };
    }

    /**
     * Fit map to bounds
     * @param {Object} options - FitBounds options
     * @returns {AoTMapLibreFeatureGroup}
     */
    fitBounds(options = {}) {
      const bounds = this.getBounds();
      if (bounds && this._map) {
        this._map.fitBounds([
          [bounds._southWest.lng, bounds._southWest.lat],
          [bounds._northEast.lng, bounds._northEast.lat]
        ], options);
      }
      return this;
    }

    // ========== Visibility ==========

    /**
     * Show all layers
     * @returns {AoTMapLibreFeatureGroup}
     */
    show() {
      this._visible = true;
      this._layers.forEach(layer => {
        if (layer.show) layer.show();
      });
      return this;
    }

    /**
     * Hide all layers
     * @returns {AoTMapLibreFeatureGroup}
     */
    hide() {
      this._visible = false;
      this._layers.forEach(layer => {
        if (layer.hide) layer.hide();
      });
      return this;
    }

    /**
     * Toggle visibility
     * @returns {AoTMapLibreFeatureGroup}
     */
    toggleVisibility() {
      return this._visible ? this.hide() : this.show();
    }

    // ========== Style ==========

    /**
     * Set style for all layers
     * @param {Object} style - Style object
     * @returns {AoTMapLibreFeatureGroup}
     */
    setStyle(style) {
      this._style = Object.assign({}, this._style, style);
      this._layers.forEach(layer => {
        if (layer.setStyle) layer.setStyle(style);
      });
      return this;
    }

    // ========== GeoJSON Export ==========

    /**
     * Export as GeoJSON
     * @returns {Object}
     */
    toGeoJSON() {
      const features = [];
      
      this._layers.forEach(layer => {
        if (layer.toGeoJSON) {
          const data = layer.toGeoJSON();
          if (data && data.features) {
            features.push(...data.features);
          }
        }
      });

      return { type: 'FeatureCollection', features: features };
    }

    // ========== Event System ==========

    /**
     * Add event listener
     * @param {string} eventType
     * @param {Function} handler
     * @returns {AoTMapLibreFeatureGroup}
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
     * @returns {AoTMapLibreFeatureGroup}
     */
    off(eventType, handler) {
      if (this._eventHandlers[eventType]) {
        this._eventHandlers[eventType] = this._eventHandlers[eventType].filter(h => h !== handler);
      }
      return this;
    }

    /**
     * Fire event
     * @param {string} eventType
     * @param {Object} data
     * @returns {AoTMapLibreFeatureGroup}
     */
    fire(eventType, data) {
      if (this._eventHandlers[eventType]) {
        this._eventHandlers[eventType].forEach(handler => {
          try {
            handler(data);
          } catch (e) {
            console.error(`[AoTMapLibreFeatureGroup] Event handler error:`, e);
          }
        });
      }
      return this;
    }

    // ========== Cleanup ==========

    /**
     * Remove all layers and cleanup
     */
    remove() {
      this.clearLayers();
      this._map = null;
    }
  }

  // Export
  global.AoTMapLibreFeatureGroup = AoTMapLibreFeatureGroup;

})(typeof window !== 'undefined' ? window : global);
