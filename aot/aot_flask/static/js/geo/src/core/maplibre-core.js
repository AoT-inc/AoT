/**
 * AoT MapLibre Core Module
 * MapLibre-GL JS 기반 지도 초기화 및 컨트롤 모듈
 * 
 * @module aot-maplibre-core
 * @version 1.0.0
 * @author AoT Team
 * 
 * @example
 * // Basic initialization
 * AoTMapLibre.init('map-container');
 * 
 * @example
 * // With options
 * AoTMapLibre.init('map-container', {
 *   center: [128.6, 35.9],
 *   zoom: 12,
 *   style: 'https://demotiles.maplibre.org/style.json'
 * });
 */

(function(global) {
  'use strict';

  /**
   * AoT MapLibre Core Namespace
   * @namespace AoTMapLibre
   */
  const AoTMapLibre = {
    /** @type {maplibregl.Map|null} */
    map: null,
    
    /** @type {Object} Default configuration */
    config: {
      // Korea center (Daegu area)
      center: [128.6, 35.9],
      zoom: 12,
      // Default style (OpenMapTiles)
      style: 'https://demotiles.maplibre.org/style.json',
      // Container ID
      container: null,
      // Navigation controls
      navigation: true,
      // Attribution
      attribution: true,
      // Max bounds for Korea region
      maxBounds: [[124.0, 33.0], [132.0, 39.0]]
    },
    
    /** @type {boolean} Initialization flag */
    initialized: false
  };

  /**
   * Initialize the map
   * 
   * @param {string|HTMLElement} container - Container element or ID
   * @param {Object} [options={}] - Configuration options
   * @param {Array} [options.center] - [lng, lat] center coordinates
   * @param {number} [options.zoom] - Initial zoom level
   * @param {string} [options.style] - Map style URL
   * @param {boolean} [options.navigation] - Enable navigation controls
   * @returns {maplibregl.Map} Map instance
   * 
   * @example
   * AoTMapLibre.init('map', { zoom: 10 });
   */
  AoTMapLibre.init = function(container, options = {}) {
    // Merge options with defaults
    const config = Object.assign({}, this.config, options);
    
    // Get container element
    let containerEl;
    if (typeof container === 'string') {
      containerEl = document.getElementById(container);
      if (!containerEl) {
        console.error(`[AoTMapLibre] Container not found: ${container}`);
        return null;
      }
    } else {
      containerEl = container;
    }
    
    // Check if already initialized
    if (this.initialized && this.map) {
      console.warn('[AoTMapLibre] Map already initialized. Use .reinit() to recreate.');
      return this.map;
    }
    
    // Validate maplibre-gl is loaded
    if (typeof maplibregl === 'undefined') {
      console.error('[AoTMapLibre] maplibre-gl not loaded. Include maplibre-gl.js first.');
      return null;
    }
    
    try {
      // Create map instance
      this.map = new maplibregl.Map({
        container: containerEl,
        style: config.style,
        center: config.center,
        zoom: config.zoom,
        maxBounds: config.maxBounds,
        attributionControl: config.attribution
      });
      
      // Add navigation controls
      if (config.navigation) {
        this.map.addControl(new maplibregl.NavigationControl(), 'top-right');
      }
      
      // Map load event
      this.map.on('load', () => {
        console.log('[AoTMapLibre] Map loaded successfully');
        this.initialized = true;
        
        // Dispatch custom event
        containerEl.dispatchEvent(new CustomEvent('aot-maplibre-ready', {
          detail: { map: this.map }
        }));
      });
      
      // Error handling
      this.map.on('error', (e) => {
        console.error('[AoTMapLibre] Map error:', e);
      });
      
      return this.map;
      
    } catch (error) {
      console.error('[AoTMapLibre] Initialization failed:', error);
      return null;
    }
  };

  /**
   * Reinitialize the map (destroys existing and creates new)
   * 
   * @param {string|HTMLElement} container - Container element or ID
   * @param {Object} [options={}] - Configuration options
   * @returns {maplibregl.Map|null}
   */
  AoTMapLibre.reinit = function(container, options = {}) {
    this.destroy();
    return this.init(container, options);
  };

  /**
   * Destroy the map instance
   */
  AoTMapLibre.destroy = function() {
    if (this.map) {
      this.map.remove();
      this.map = null;
      this.initialized = false;
      console.log('[AoTMapLibre] Map destroyed');
    }
  };

  /**
   * Load a custom map style
   * 
   * @param {string} styleUrl - URL to map style JSON
   * @param {Function} [onComplete] - Callback when style is loaded
   * @param {Function} [onError] - Callback on error
   */
  AoTMapLibre.loadStyle = function(styleUrl, onComplete, onError) {
    if (!this.map) {
      console.error('[AoTMapLibre] Map not initialized');
      return;
    }
    
    this.map.setStyle(styleUrl);
    
    if (onComplete) {
      this.map.once('style.load', onComplete);
    }
    
    if (onError) {
      this.map.once('error', onError);
    }
  };

  /**
   * Add a tile layer
   * 
   * @param {string} id - Layer ID
   * @param {string} sourceUrl - Tile source URL
   * @param {Object} [paintOptions={}] - Paint options for the layer
   * @returns {maplibregl.Map} Map instance for chaining
   */
  AoTMapLibre.addTileLayer = function(id, sourceUrl, paintOptions = {}) {
    if (!this.map) {
      console.error('[AoTMapLibre] Map not initialized');
      return null;
    }
    
    if (this.map.getSource(id)) {
      console.warn(`[AoTMapLibre] Source ${id} already exists`);
      return this.map;
    }
    
    this.map.addSource(id, {
      type: 'raster',
      tiles: [sourceUrl],
      tileSize: 256
    });
    
    this.map.addLayer({
      id: id + '-layer',
      type: 'raster',
      source: id,
      paint: Object.assign({
        'raster-opacity': 0.8
      }, paintOptions)
    });
    
    return this.map;
  };

  /**
   * Fly to a location
   * 
   * @param {Array} coords - [lng, lat] coordinates
   * @param {number} [zoom=15] - Target zoom level
   * @param {Object} [options={}] - FlyTo options
   */
  AoTMapLibre.flyTo = function(coords, zoom = 15, options = {}) {
    if (!this.map) {
      console.error('[AoTMapLibre] Map not initialized');
      return;
    }
    
    this.map.flyTo(Object.assign({
      center: coords,
      zoom: zoom,
      duration: 1500
    }, options));
  };

  /**
   * Fit bounds to show area
   * 
   * @param {Array} bounds - [[sw_lng, sw_lat], [ne_lng, ne_lat]]
   * @param {Object} [options={}] - FitBounds options
   */
  AoTMapLibre.fitBounds = function(bounds, options = {}) {
    if (!this.map) {
      console.error('[AoTMapLibre] Map not initialized');
      return;
    }
    
    this.map.fitBounds(bounds, Object.assign({
      padding: 50
    }, options));
  };

  /**
   * Add GeoJSON layer
   * 
   * @param {string} id - Layer ID
   * @param {Object|string} geojson - GeoJSON object or URL
   * @param {Object} [paint={}] - Paint options
   * @param {string} [type='fill'] - Layer type (fill, line, circle, etc.)
   */
  AoTMapLibre.addGeoJSONLayer = function(id, geojson, paint = {}, type = 'fill') {
    if (!this.map) {
      console.error('[AoTMapLibre] Map not initialized');
      return;
    }
    
    // Add source if doesn't exist
    if (!this.map.getSource(id)) {
      const sourceConfig = typeof geojson === 'string' 
        ? { type: 'geojson', data: geojson }
        : { type: 'geojson', data: geojson };
      
      this.map.addSource(id, sourceConfig);
    }
    
    // Add layer
    if (!this.map.getLayer(id + '-layer')) {
      this.map.addLayer({
        id: id + '-layer',
        type: type,
        source: id,
        paint: paint
      });
    }
  };

  /**
   * Get map instance
   * @returns {maplibregl.Map|null}
   */
  AoTMapLibre.getMap = function() {
    return this.map;
  };

  /**
   * Check if map is initialized
   * @returns {boolean}
   */
  AoTMapLibre.isReady = function() {
    return this.initialized && this.map !== null;
  };

  /**
   * Korean map style configuration
   * @type {Object}
   */
  AoTMapLibre.STYLES = {
    // OpenMapTiles (demo)
    DEMO: 'https://demotiles.maplibre.org/style.json',
    
    // VWorld (Korean base map - requires API key in production)
    VWORLD_BASE: 'https://api.vworld.kr/req/wmts/1.0.0/{API_KEY}/base/{z}/{y}/{x}.png',
    
    // Custom styled examples can be added here
    DARK: 'https://tiles.stadiamaps.com/styles/alidade_smooth_dark.json'
  };

  /**
   * Predefined Korean locations
   * @type {Object}
   */
  AoTMapLibre.LOCATIONS = {
    SEOUL: { center: [126.9780, 37.5665], zoom: 11 },
    BUSAN: { center: [129.0756, 35.1796], zoom: 11 },
    DAEGU: { center: [128.6, 35.9], zoom: 12 },
    INCHEON: { center: [126.7052, 37.4563], zoom: 11 },
    GWANGJU: { center: [126.8977, 35.1540], zoom: 11 },
    DAEJEON: { center: [127.3850, 36.3504], zoom: 11 },
    ULSAN: { center: [129.3167, 35.5667], zoom: 11 },
    SEJONG: { center: [127.2493, 36.48], zoom: 12 }
  };

  // Export to global scope
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = AoTMapLibre;
  } else {
    global.AoTMapLibre = AoTMapLibre;
  }

})(typeof window !== 'undefined' ? window : this);
