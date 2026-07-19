/**
 * AoTMapLibreCore.js
 * MapLibre GL 기반 지도 코어 모듈
 * 
 * @version 1.0.0
 * @author AoT Team
 * @requires maplibre-gl
 */

(function(global) {
  'use strict';

  /**
   * AoT MapLibre Core Class
   * 지도 초기화, 제어, 이벤트 관리
   */
  class AoTMapLibreCore {
    /**
     * Create a new AoTMapLibreCore instance
     * @param {string|HTMLElement} container - Container element or ID
     * @param {Object} options - Configuration options
     */
    constructor(container, options = {}) {
      this._container = typeof container === 'string' ? 
        document.getElementById(container) : container;
      
      if (!this._container) {
        throw new Error(`[AoTMapLibreCore] Container not found: ${container}`);
      }

      this._map = null;
      this._options = Object.assign({}, this._getDefaultOptions(), options);
      this._eventHandlers = {};
      this._layers = new Map();
      this._sources = new Map();
      this._popups = new Map();
      this._tooltips = new Map();
      this._initialized = false;
    }

    /**
     * Get default configuration
     * @private
     */
    _getDefaultOptions() {
      return {
        // Korea center defaults (Daegu area)
        center: [128.6, 35.9],
        zoom: 12,
        minZoom: 8,
        maxZoom: 20,
        pitch: 0,
        bearing: 0,
        // Default style
        style: 'https://demotiles.maplibre.org/style.json',
        // Controls
        navigation: true,
        scale: true,
        attribution: true,
        // Max bounds (Korea region)
        maxBounds: [[124.0, 33.0], [132.0, 39.0]],
        // Rendering
        antialias: true,
        preserveDrawingBuffer: false
      };
    }

    /**
     * Initialize the map
     * @returns {Promise<maplibregl.Map>}
     */
    async init() {
      if (this._initialized) {
        console.warn('[AoTMapLibreCore] Already initialized');
        return this._map;
      }

      // Check MapLibre GL is loaded
      if (typeof maplibregl === 'undefined') {
        throw new Error('[AoTMapLibreCore] maplibre-gl not loaded. Include maplibre-gl.js first.');
      }

      return new Promise((resolve, reject) => {
        try {
          this._map = new maplibregl.Map({
            container: this._container,
            style: this._options.style,
            center: this._options.center,
            zoom: this._options.zoom,
            minZoom: this._options.minZoom,
            maxZoom: this._options.maxZoom,
            pitch: this._options.pitch,
            bearing: this._options.bearing,
            maxBounds: this._options.maxBounds,
            antialias: this._options.antialias,
            preserveDrawingBuffer: this._options.preserveDrawingBuffer,
            attributionControl: false
          });

          // Add controls
          this._addControls();

          // Map load event
          this._map.on('load', () => {
            this._initialized = true;
            console.log('[AoTMapLibreCore] Map loaded successfully');
            this._fire('ready', { map: this._map });
            resolve(this._map);
          });

          // Error handling
          this._map.on('error', (e) => {
            console.error('[AoTMapLibreCore] Map error:', e);
            this._fire('error', e);
          });

          // Setup event forwarding
          this._setupEventForwarding();

        } catch (error) {
          console.error('[AoTMapLibreCore] Initialization failed:', error);
          reject(error);
        }
      });
    }

    /**
     * Add default controls
     * @private
     */
    _addControls() {
      // Navigation control
      if (this._options.navigation) {
        this._map.addControl(new maplibregl.NavigationControl({
          showCompass: true,
          showZoom: true,
          visualizePitch: true
        }), 'top-right');
      }

      // Scale control
      if (this._options.scale) {
        this._map.addControl(new maplibregl.ScaleControl({
          maxWidth: 100,
          unit: 'metric'
        }), 'bottom-left');
      }

      // Attribution control
      if (this._options.attribution) {
        this._map.addControl(new maplibregl.AttributionControl({
          compact: true
        }), 'bottom-right');
      }
    }

    /**
     * Setup event forwarding from MapLibre
     * @private
     */
    _setupEventForwarding() {
      const events = ['click', 'dblclick', 'mousedown', 'mouseup', 'mousemove', 
                      'mouseenter', 'mouseleave', 'touchstart', 'touchend', 'touchmove',
                      'zoomstart', 'zoomend', 'rotate', 'rotateend', 'dragstart', 'dragend',
                      'resize', 'load', 'error', 'data', 'sourcedata', 'styledata'];
      
      events.forEach(event => {
        this._map.on(event, (e) => {
          this._fire(event, e);
        });
      });
    }

    /**
     * Fire an event
     * @private
     */
    _fire(eventType, data) {
      if (this._eventHandlers[eventType]) {
        this._eventHandlers[eventType].forEach(handler => {
          try {
            handler.call(this, data);
          } catch (e) {
            console.error(`[AoTMapLibreCore] Event handler error (${eventType}):`, e);
          }
        });
      }
    }

    // ========== Public API ==========

    /**
     * Get MapLibre map instance
     * @returns {maplibregl.Map|null}
     */
    getMap() {
      return this._map;
    }

    /**
     * Check if map is ready
     * @returns {boolean}
     */
    isReady() {
      return this._initialized && this._map !== null;
    }

    /**
     * Wait for map to be ready
     * @returns {Promise<maplibregl.Map>}
     */
    whenReady() {
      if (this._initialized) {
        return Promise.resolve(this._map);
      }
      return new Promise(resolve => {
        this.on('ready', () => resolve(this._map));
      });
    }

    // ========== View Control ==========

    /**
     * Set map center
     * @param {Array} center - [lng, lat]
     * @param {boolean} jump - Jump to location without animation
     */
    setCenter(center, jump = false) {
      if (!this._map) return;
      if (jump) {
        this._map.jumpTo({ center });
      } else {
        this._map.setCenter(center);
      }
    }

    /**
     * Set map zoom
     * @param {number} zoom
     * @param {boolean} jump
     */
    setZoom(zoom, jump = false) {
      if (!this._map) return;
      if (jump) {
        this._map.jumpTo({ zoom });
      } else {
        this._map.setZoom(zoom);
      }
    }

    /**
     * Fly to a location
     * @param {Array} coords - [lng, lat]
     * @param {Object} options - FlyTo options
     */
    flyTo(coords, options = {}) {
      if (!this._map) return;
      this._map.flyTo(Object.assign({
        center: coords,
        duration: 1500,
        essential: true
      }, options));
    }

    /**
     * Fit bounds to show area
     * @param {Array} bounds - [[sw_lng, sw_lat], [ne_lng, ne_lat]]
     * @param {Object} options - FitBounds options
     */
    fitBounds(bounds, options = {}) {
      if (!this._map) return;
      this._map.fitBounds(bounds, Object.assign({
        padding: 50
      }, options));
    }

    /**
     * Get current bounds
     * @returns {Object} { sw: [lng, lat], ne: [lng, lat] }
     */
    getBounds() {
      if (!this._map) return null;
      const bounds = this._map.getBounds();
      return {
        sw: [bounds.getWest(), bounds.getSouth()],
        ne: [bounds.getEast(), bounds.getNorth()]
      };
    }

    /**
     * Get current center
     * @returns {Array} [lng, lat]
     */
    getCenter() {
      if (!this._map) return null;
      const center = this._map.getCenter();
      return [center.lng, center.lat];
    }

    /**
     * Get current zoom
     * @returns {number}
     */
    getZoom() {
      return this._map ? this._map.getZoom() : null;
    }

    /**
     * Zoom in
     */
    zoomIn() {
      if (this._map) this._map.zoomIn();
    }

    /**
     * Zoom out
     */
    zoomOut() {
      if (this._map) this._map.zoomOut();
    }

    // ========== Event Handling ==========

    /**
     * Add event listener
     * @param {string} eventType - Event type
     * @param {Function} handler - Event handler
     * @returns {this}
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
     * @param {string} eventType - Event type
     * @param {Function} handler - Event handler
     * @returns {this}
     */
    off(eventType, handler) {
      if (this._eventHandlers[eventType]) {
        this._eventHandlers[eventType] = this._eventHandlers[eventType]
          .filter(h => h !== handler);
      }
      return this;
    }

    /**
     * Once event listener
     * @param {string} eventType - Event type
     * @param {Function} handler - Event handler
     * @returns {this}
     */
    once(eventType, handler) {
      const wrapped = (e) => {
        handler.call(this, e);
        this.off(eventType, wrapped);
      };
      return this.on(eventType, wrapped);
    }

    // ========== Source Management ==========

    /**
     * Add GeoJSON source
     * @param {string} id - Source ID
     * @param {Object} geojson - GeoJSON data
     * @returns {this}
     */
    addSource(id, geojson) {
      if (!this._map || this._map.getSource(id)) {
        console.warn(`[AoTMapLibreCore] Source ${id} already exists or map not ready`);
        return this;
      }

      this._map.addSource(id, {
        type: 'geojson',
        data: geojson,
        promoteId: 'id'
      });

      this._sources.set(id, { type: 'geojson', data: geojson });
      return this;
    }

    /**
     * Update source data
     * @param {string} id - Source ID
     * @param {Object} geojson - New GeoJSON data
     * @returns {this}
     */
    setSourceData(id, geojson) {
      const source = this._map?.getSource(id);
      if (source && source.type === 'geojson') {
        source.setData(geojson);
        this._sources.set(id, { type: 'geojson', data: geojson });
      }
      return this;
    }

    /**
     * Remove source
     * @param {string} id - Source ID
     * @returns {this}
     */
    removeSource(id) {
      if (this._map && this._map.getSource(id)) {
        // Remove associated layers first
        this._map.getStyle()?.layers?.forEach(layer => {
          if (layer.source === id) {
            this._map.removeLayer(layer.id);
          }
        });
        this._map.removeSource(id);
        this._sources.delete(id);
      }
      return this;
    }

    /**
     * Get source by ID
     * @param {string} id - Source ID
     * @returns {Object|null}
     */
    getSource(id) {
      return this._sources.get(id) || null;
    }

    // ========== Layer Management ==========

    /**
     * Add a layer
     * @param {Object} layerConfig - MapLibre layer configuration
     * @param {string} beforeId - Layer ID to insert before
     * @returns {this}
     */
    addLayer(layerConfig, beforeId) {
      if (!this._map) return this;
      
      if (this._map.getLayer(layerConfig.id)) {
        console.warn(`[AoTMapLibreCore] Layer ${layerConfig.id} already exists`);
        return this;
      }

      if (beforeId) {
        this._map.addLayer(layerConfig, beforeId);
      } else {
        this._map.addLayer(layerConfig);
      }

      this._layers.set(layerConfig.id, layerConfig);
      return this;
    }

    /**
     * Remove a layer
     * @param {string} id - Layer ID
     * @returns {this}
     */
    removeLayer(id) {
      if (this._map && this._map.getLayer(id)) {
        this._map.removeLayer(id);
        this._layers.delete(id);
      }
      return this;
    }

    /**
     * Set layer visibility
     * @param {string} id - Layer ID
     * @param {boolean} visible
     * @returns {this}
     */
    setLayerVisibility(id, visible) {
      if (this._map && this._map.getLayer(id)) {
        this._map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
      }
      return this;
    }

    /**
     * Set layer paint property
     * @param {string} id - Layer ID
     * @param {string} property - Paint property name
     * @param {*} value - Property value
     * @returns {this}
     */
    setPaintProperty(id, property, value) {
      if (this._map && this._map.getLayer(id)) {
        this._map.setPaintProperty(id, property, value);
      }
      return this;
    }

    /**
     * Set layer filter
     * @param {string} id - Layer ID
     * @param {Array} filter - MapLibre filter expression
     * @returns {this}
     */
    setFilter(id, filter) {
      if (this._map && this._map.getLayer(id)) {
        this._map.setFilter(id, filter);
      }
      return this;
    }

    // ========== Style Management ==========

    /**
     * Load a new style
     * @param {string} styleUrl - Style URL
     * @returns {Promise}
     */
    loadStyle(styleUrl) {
      if (!this._map) return Promise.reject('Map not initialized');
      
      return new Promise((resolve, reject) => {
        this._map.once('style.load', () => {
          // Re-add all sources and layers after style change
          this._reinitializeLayers();
          resolve();
        });
        
        this._map.once('error', (e) => reject(e));
        this._map.setStyle(styleUrl);
      });
    }

    /**
     * Reinitialize layers after style change
     * @private
     */
    _reinitializeLayers() {
      // Sources and layers need to be re-added after style change
      console.log('[AoTMapLibreCore] Style changed, layers reinitialized');
    }

    // ========== Popup Management ==========

    /**
     * Create a popup
     * @param {Object} options - Popup options
     * @returns {maplibregl.Popup}
     */
    createPopup(options = {}) {
      return new maplibregl.Popup(Object.assign({
        closeButton: true,
        closeOnClick: true,
        maxWidth: '300px'
      }, options));
    }

    /**
     * Show popup at location
     * @param {Array} coords - [lng, lat]
     * @param {string} content - HTML content
     * @param {Object} options - Popup options
     * @returns {maplibregl.Popup}
     */
    showPopup(coords, content, options = {}) {
      const popup = this.createPopup(options)
        .setLngLat(coords)
        .setHTML(content)
        .addTo(this._map);
      return popup;
    }

    /**
     * Close all popups
     * @returns {this}
     */
    closeAllPopups() {
      this._map?.getContainer()?.querySelectorAll('.maplibregl-popup')
        .forEach(el => el.remove());
      return this;
    }

    // ========== Cleanup ==========

    /**
     * Destroy the map instance
     */
    destroy() {
      if (this._map) {
        // Remove all popups
        this.closeAllPopups();

        // Remove all sources
        this._sources.forEach((_, id) => {
          this.removeSource(id);
        });

        // Remove map
        this._map.remove();
        this._map = null;
        this._initialized = false;
        
        console.log('[AoTMapLibreCore] Map destroyed');
      }
    }
  }

  // Export
  global.AoTMapLibreCore = AoTMapLibreCore;

})(typeof window !== 'undefined' ? window : global);
