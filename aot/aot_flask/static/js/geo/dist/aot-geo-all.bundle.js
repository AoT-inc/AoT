var AoTGeo = (function (exports) {
	'use strict';

	var commonjsGlobal = typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : typeof global !== 'undefined' ? global : typeof self !== 'undefined' ? self : {};

	var maplibreCore = {exports: {}};

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

	(function (module) {
		(function(global) {

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
		  if (module.exports) {
		    module.exports = AoTMapLibre;
		  } else {
		    global.AoTMapLibre = AoTMapLibre;
		  }

		})(typeof window !== 'undefined' ? window : commonjsGlobal); 
	} (maplibreCore));

	/**
	 * Vector Layer Manager for AoT
	 * Handles vector tile layers with MapLibre-GL integration
	 *
	 * @module AoT-VectorLayerManager
	 * @version 1.1.0
	 */

	(function(global) {

	  /**
	   * Vector Layer Manager Class
	   * Manages multiple vector tile layers on a MapLibre map
	   */
	  class VectorLayerManager {
	    constructor() {
	      /** @type {maplibregl.Map|null} */
	      this.map = null;

	      /** @type {Map<string, Object>} */
	      this.layers = new Map();

	      /** @type {Map<string, Object>} */
	      this.sources = new Map();

	      /** @type {string|null} */
	      this.activeLayerId = null;

	      /** @type {boolean} */
	      this.initialized = false;

	      /** @type {Object} Default AoT layer styles */
	      this._styles = this._loadDefaultStyles();
	    }

	    /**
	     * Load default AoT layer styles.
	     * @private
	     * @returns {Object} Default style definitions
	     */
	    _loadDefaultStyles() {
	      return {
	        device: {
	          type: 'symbol',
	          layout: {
	            'icon-image': 'marker-icon',
	            'icon-size': 1.2,
	            'text-field': ['get', 'name'],
	            'text-font': ['Noto Sans Regular'],
	            'text-offset': [0, 1.5],
	            'text-anchor': 'top'
	          },
	          paint: {
	            'text-color': '#333',
	            'text-halo-color': '#fff',
	            'text-halo-width': 2
	          }
	        },
	        facility: {
	          type: 'fill',
	          paint: {
	            'fill-color': '#82898f',
	            'fill-opacity': 0.2
	          }
	        },
	        zone: {
	          type: 'line',
	          paint: {
	            'line-color': '#28a745',
	            'line-width': 2,
	            'line-dasharray': [2, 2]
	          }
	        },
	        site: {
	          type: 'line',
	          paint: {
	            'line-color': '#DF5353',
	            'line-width': 4
	          }
	        }
	      };
	    }

	    /**
	     * Initialize with a MapLibre map instance.
	     * @param {maplibregl.Map} map - MapLibre map instance
	     * @returns {boolean}
	     */
	    init(map) {
	      if (!map || typeof map.addSource !== 'function') {
	        console.error('[VectorLayerManager] Invalid map instance');
	        return false;
	      }
	      this.map = map;
	      this.initialized = true;
	      console.log('[VectorLayerManager] Initialized');
	      return true;
	    }

	    /**
	     * Add a vector tile layer from GIS input configuration.
	     * @param {Object} gisConfig - GIS input configuration from backend
	     * @returns {boolean} Success status
	     */
	    addLayer(gisConfig) {
	      if (!this.initialized || !this.map) {
	        console.error('[VectorLayerManager] Not initialized');
	        return false;
	      }

	      const layerId = gisConfig.unique_id || 'vector_' + Date.now();

	      if (this.layers.has(layerId)) {
	        console.warn('[VectorLayerManager] Layer ' + layerId + ' already exists');
	        return false;
	      }

	      const type = gisConfig.type || 'vector';

	      if (type === 'vector') {
	        return this._addVectorLayer(layerId, gisConfig);
	      } else if (type === 'tile' || type === 'wms') {
	        return this._addRasterBridgeLayer(layerId, gisConfig);
	      }

	      console.warn('[VectorLayerManager] Unsupported layer type: ' + type);
	      return false;
	    }

	    /**
	     * Add a raw vector tile source to the MapLibre map.
	     * @param {string} sourceId - Unique source identifier
	     * @param {Object} options - Source options
	     * @param {string[]} options.tiles - Tile URL patterns
	     * @param {number} [options.minzoom=0] - Min zoom
	     * @param {number} [options.maxzoom=14] - Max zoom
	     * @param {string} [options.attribution=''] - Attribution string
	     * @returns {boolean} Success
	     */
	    addVectorSource(sourceId, options) {
	      if (!this.initialized || !this.map) {
	        console.error('[VectorLayerManager] Not initialized');
	        return false;
	      }
	      if (!options || !options.tiles) {
	        console.error('[VectorLayerManager.addVectorSource] tiles array is required');
	        return false;
	      }
	      if (this.map.getSource(sourceId)) {
	        console.warn('[VectorLayerManager.addVectorSource] Source ' + sourceId + ' already exists');
	        return false;
	      }

	      var sourceConfig = {
	        type: 'vector',
	        tiles: options.tiles,
	        minzoom: options.minzoom !== undefined ? options.minzoom : 0,
	        maxzoom: options.maxzoom !== undefined ? options.maxzoom : 14,
	        attribution: options.attribution || ''
	      };

	      this.map.addSource(sourceId, sourceConfig);
	      this.sources.set(sourceId, { type: 'vector', config: sourceConfig });
	      console.log('[VectorLayerManager.addVectorSource] Added source: ' + sourceId);
	      return true;
	    }

	    /**
	     * Add a GeoJSON source and optional styled layers.
	     * @param {string} sourceId - Unique source identifier
	     * @param {Object|string} geojson - GeoJSON object or URL string
	     * @returns {boolean} Success
	     */
	    addGeoJSONSource(sourceId, geojson) {
	      if (!this.initialized || !this.map) {
	        console.error('[VectorLayerManager] Not initialized');
	        return false;
	      }
	      if (this.map.getSource(sourceId)) {
	        console.warn('[VectorLayerManager.addGeoJSONSource] Source ' + sourceId + ' already exists');
	        return false;
	      }

	      var sourceConfig;
	      if (typeof geojson === 'string') {
	        sourceConfig = { type: 'geojson', data: geojson };
	      } else {
	        sourceConfig = { type: 'geojson', data: geojson };
	      }

	      this.map.addSource(sourceId, sourceConfig);
	      this.sources.set(sourceId, { type: 'geojson', config: sourceConfig });
	      console.log('[VectorLayerManager.addGeoJSONSource] Added GeoJSON source: ' + sourceId);
	      return true;
	    }

	    /**
	     * Add a styled layer on top of an existing source.
	     * @param {string} sourceId - Source to attach layer to
	     * @param {string} layerId - Unique layer identifier
	     * @param {string} styleType - Style key from _loadDefaultStyles (device, facility, zone, site)
	     * @param {Object} [paint={}] - Paint overrides
	     * @param {Object} [layout={}] - Layout overrides
	     * @returns {boolean} Success
	     */
	    addStyledLayer(sourceId, layerId, styleType, paint, layout) {
	      if (!this.initialized || !this.map) {
	        console.error('[VectorLayerManager] Not initialized');
	        return false;
	      }
	      if (!this.map.getSource(sourceId)) {
	        console.error('[VectorLayerManager.addStyledLayer] Source ' + sourceId + ' not found');
	        return false;
	      }
	      if (this.map.getLayer(layerId)) {
	        console.warn('[VectorLayerManager.addStyledLayer] Layer ' + layerId + ' already exists');
	        return false;
	      }

	      paint = paint || {};
	      layout = layout || {};
	      var baseStyle = this._styles[styleType] || this._styles.zone;

	      var layerConfig = {
	        id: layerId,
	        source: sourceId,
	        type: baseStyle.type
	      };

	      if (baseStyle.layout) {
	        layerConfig.layout = Object.assign({}, baseStyle.layout, layout);
	      }
	      if (baseStyle.paint) {
	        layerConfig.paint = Object.assign({}, baseStyle.paint, paint);
	      }

	      // Apply filter for fill/line layers to match geometry type
	      if (baseStyle.type === 'fill') {
	        layerConfig.filter = ['==', '$type', 'Polygon'];
	      } else if (baseStyle.type === 'line') {
	        layerConfig.filter = ['in', '$type', 'LineString', 'Polygon'];
	      }

	      this.map.addLayer(layerConfig);

	      var entry = {
	        id: layerId,
	        sourceId: sourceId,
	        type: baseStyle.type,
	        styleType: styleType,
	        visible: true,
	        opacity: 1.0
	      };
	      this.layers.set(layerId, entry);
	      console.log('[VectorLayerManager.addStyledLayer] Added styled layer: ' + layerId + ' (style: ' + styleType + ')');
	      return true;
	    }

	    /**
	     * Add vector tile layer (internal).
	     * @private
	     */
	    _addVectorLayer(layerId, config) {
	      var styleUrl = config.url;
	      var apiKey = config.api_key || '';

	      if (!styleUrl) {
	        console.error('[VectorLayerManager] No style URL provided');
	        return false;
	      }

	      var finalUrl = styleUrl;
	      if (apiKey && finalUrl.indexOf('{api_key}') !== -1) {
	        finalUrl = finalUrl.replace('{api_key}', apiKey);
	      }

	      if (config.tileUrl) {
	        var tileUrl = config.tileUrl;
	        if (apiKey && tileUrl.indexOf('{api_key}') !== -1) {
	          tileUrl = tileUrl.replace('{api_key}', apiKey);
	        }

	        this.map.addSource(layerId, {
	          type: 'vector',
	          tiles: [tileUrl],
	          minzoom: 0,
	          maxzoom: 14
	        });
	      }

	      this.layers.set(layerId, {
	        id: layerId,
	        type: 'vector',
	        styleUrl: finalUrl,
	        name: config.name || layerId,
	        visible: config.options && config.options.visible !== false,
	        opacity: (config.options && config.options.opacity) || 1.0
	      });

	      console.log('[VectorLayerManager] Added vector layer: ' + layerId);
	      return true;
	    }

	    /**
	     * Add raster bridge layer (internal).
	     * @private
	     */
	    _addRasterBridgeLayer(layerId, config) {
	      this.layers.set(layerId, {
	        id: layerId,
	        type: 'raster-bridge',
	        url: config.url,
	        name: config.name || layerId,
	        visible: config.options && config.options.visible !== false,
	        opacity: (config.options && config.options.opacity) || 1.0
	      });

	      console.log('[VectorLayerManager] Added raster bridge layer: ' + layerId);
	      return true;
	    }

	    /**
	     * Add a MapTiler vector tile source.
	     * @param {string} sourceId - Unique source identifier
	     * @param {Object} maptilerConfig - MapTiler configuration
	     * @param {string} maptilerConfig.apiKey - MapTiler API key
	     * @param {string} [maptilerConfig.style='streets'] - Style name
	     * @param {string} [maptilerConfig.language='auto'] - Label language
	     * @param {number} [maptilerConfig.minZoom=0] - Min zoom
	     * @param {number} [maptilerConfig.maxZoom=14] - Max zoom
	     * @returns {boolean} Success
	     */
	    addMaptilerSource(sourceId, maptilerConfig) {
	      if (!this.initialized || !this.map) {
	        console.error('[VectorLayerManager] Not initialized');
	        return false;
	      }
	      if (!maptilerConfig || !maptilerConfig.apiKey) {
	        console.error('[VectorLayerManager.addMaptilerSource] apiKey is required');
	        return false;
	      }

	      var style = maptilerConfig.style || 'streets';
	      var language = maptilerConfig.language || 'auto';
	      var minZoom = maptilerConfig.minZoom !== undefined ? maptilerConfig.minZoom : 0;
	      var maxZoom = maptilerConfig.maxZoom !== undefined ? maptilerConfig.maxZoom : 14;
	      var apiKey = maptilerConfig.apiKey;

	      var tileUrl = 'https://api.maptiler.com/tiles/' + style + '/v2/{z}/{x}/{y}.pbf?key=' + apiKey;

	      this.map.addSource(sourceId, {
	        type: 'vector',
	        tiles: [tileUrl],
	        minzoom: minZoom,
	        maxzoom: maxZoom,
	        attribution: '&copy; <a href="https://www.maptiler.com/">MapTiler</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
	      });

	      var layerEntry = {
	        id: sourceId,
	        type: 'vector',
	        provider: 'maptiler',
	        style: style,
	        language: language,
	        name: maptilerConfig.name || ('MapTiler ' + style),
	        visible: true,
	        opacity: 1.0
	      };

	      this.layers.set(sourceId, layerEntry);
	      console.log('[VectorLayerManager.addMaptilerSource] Added MapTiler source: ' + sourceId + ' (style: ' + style + ')');
	      return true;
	    }

	    /**
	     * Remove a layer.
	     * @param {string} layerId - Layer ID to remove
	     */
	    removeLayer(layerId) {
	      if (!this.layers.has(layerId) && !this.sources.has(layerId)) {
	        console.warn('[VectorLayerManager] Layer/Source ' + layerId + ' not found');
	        return false;
	      }

	      // Remove map layers attached to this source
	      if (this.map) {
	        var self = this;
	        this.map.getStyle && this.map.getStyle().layers && this.map.getStyle().layers.forEach(function(l) {
	          if (l.source === layerId) {
	            if (self.map.getLayer(l.id)) self.map.removeLayer(l.id);
	          }
	        });
	        if (this.map.getSource(layerId)) {
	          this.map.removeSource(layerId);
	        }
	      }

	      this.layers.delete(layerId);
	      this.sources.delete(layerId);

	      if (this.activeLayerId === layerId) {
	        this.activeLayerId = null;
	      }

	      console.log('[VectorLayerManager] Removed layer: ' + layerId);
	      return true;
	    }

	    /**
	     * Set active base layer.
	     * @param {string} layerId - Layer ID to activate
	     */
	    setActiveLayer(layerId) {
	      this.activeLayerId = layerId;
	      console.log('[VectorLayerManager] Active layer set to: ' + layerId);
	    }

	    /**
	     * Toggle layer visibility for both vector sources and styled layers.
	     * @param {string} layerId - Layer ID
	     * @param {boolean} visible - Visibility state
	     */
	    setLayerVisibility(layerId, visible) {
	      var layer = this.layers.get(layerId);
	      var source = this.sources.get(layerId);

	      if (!layer && !source) {
	        console.warn('[VectorLayerManager] Layer ' + layerId + ' not found');
	        return false;
	      }

	      if (layer) {
	        layer.visible = visible;
	      }

	      if (!this.map) return true;

	      // 1. Toggle source-level layers from style JSON
	      if (this.map.getStyle && this.map.getStyle().layers) {
	        var self = this;
	        this.map.getStyle().layers.forEach(function(l) {
	          if (l.source === layerId) {
	            self.map.setLayoutProperty(l.id, 'visibility', visible ? 'visible' : 'none');
	          }
	        });
	      }

	      // 2. Toggle direct vector source visibility via paint opacity fallback
	      if (source && source.type === 'vector') {
	        var self2 = this;
	        var opacityValue = visible ? (layer ? layer.opacity : 1.0) : 0;
	        if (this.map.getStyle && this.map.getStyle().layers) {
	          this.map.getStyle().layers.forEach(function(l) {
	            if (l.source === layerId && l.type === 'raster') {
	              self2.map.setPaintProperty(l.id, 'raster-opacity', opacityValue);
	            }
	          });
	        }
	      }

	      // 3. Toggle explicitly added styled layers
	      if (this.map.getLayer(layerId)) {
	        this.map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
	      }

	      console.log('[VectorLayerManager] Layer ' + layerId + ' visibility: ' + visible);
	      return true;
	    }

	    /**
	     * Set layer opacity.
	     * @param {string} layerId - Layer ID
	     * @param {number} opacity - Opacity value (0-1)
	     */
	    setLayerOpacity(layerId, opacity) {
	      var layer = this.layers.get(layerId);
	      if (!layer && !this.sources.has(layerId)) {
	        console.warn('[VectorLayerManager] Layer ' + layerId + ' not found');
	        return false;
	      }

	      opacity = Math.max(0, Math.min(1, opacity));
	      if (layer) {
	        layer.opacity = opacity;
	      }

	      if (this.map) {
	        // Apply to all layers sharing this source
	        if (this.map.getStyle && this.map.getStyle().layers) {
	          var self = this;
	          this.map.getStyle().layers.forEach(function(l) {
	            if (l.source === layerId) {
	              var paintProp = self._getOpacityPaintProperty(l.type);
	              if (paintProp) {
	                self.map.setPaintProperty(l.id, paintProp, opacity);
	              }
	            }
	          });
	        }
	        // Apply to direct layer
	        if (this.map.getLayer(layerId)) {
	          var paintProp2 = this._getOpacityPaintProperty(this.map.getLayer(layerId).type);
	          if (paintProp2) {
	            this.map.setPaintProperty(layerId, paintProp2, opacity);
	          }
	        }
	      }

	      return true;
	    }

	    /**
	     * Get the paint property name for opacity per layer type.
	     * @private
	     */
	    _getOpacityPaintProperty(type) {
	      var map = {
	        'fill': 'fill-opacity',
	        'line': 'line-opacity',
	        'symbol': 'text-opacity',
	        'circle': 'circle-opacity',
	        'raster': 'raster-opacity',
	        'heatmap': 'heatmap-opacity',
	        'hillshade': 'hillshade-shadow-opacity',
	        'background': 'background-opacity'
	      };
	      return map[type] || null;
	    }

	    /**
	     * Apply a new style URL to a layer.
	     * @param {string} layerId - Layer ID
	     * @param {string} styleUrl - New style URL
	     */
	    applyStyle(layerId, styleUrl) {
	      var layer = this.layers.get(layerId);
	      if (!layer) {
	        console.error('[VectorLayerManager] Layer ' + layerId + ' not found');
	        return false;
	      }

	      layer.styleUrl = styleUrl;
	      if (layer.type === 'vector' && this.map) {
	        this.map.setStyle(styleUrl);
	      }
	      return true;
	    }

	    /**
	     * Register a click event handler on one or more layers.
	     * @param {string[]} layerIds - Array of layer IDs to listen on
	     * @param {Function} callback - (features, lngLat) => void
	     */
	    onLayerClick(layerIds, callback) {
	      var self = this;
	      layerIds.forEach(function(id) {
	        if (!self.map) return;
	        self.map.on('click', id, function(e) {
	          callback(e.features, e.lngLat);
	        });
	        self.map.on('mouseenter', id, function() {
	          if (self.map) self.map.getCanvas().style.cursor = 'pointer';
	        });
	        self.map.on('mouseleave', id, function() {
	          if (self.map) self.map.getCanvas().style.cursor = '';
	        });
	      });
	    }

	    /**
	     * Set a filter expression on a layer.
	     * @param {string} layerId - Layer ID
	     * @param {Array} filter - MapLibre filter expression
	     */
	    setFilter(layerId, filter) {
	      if (this.map && this.map.getLayer(layerId)) {
	        this.map.setFilter(layerId, filter);
	        console.log('[VectorLayerManager] Filter set on ' + layerId);
	        return true;
	      }
	      return false;
	    }

	    /**
	     * Get all registered layers.
	     * @returns {Array} Array of layer configs
	     */
	    getLayers() {
	      return Array.from(this.layers.values());
	    }

	    /**
	     * Get all registered sources.
	     * @returns {Array} Array of source configs
	     */
	    getSources() {
	      return Array.from(this.sources.values());
	    }

	    /**
	     * Get layer by ID.
	     * @param {string} layerId - Layer ID
	     * @returns {Object|null} Layer config or null
	     */
	    getLayer(layerId) {
	      return this.layers.get(layerId) || null;
	    }

	    /**
	     * Dispose and cleanup.
	     */
	    dispose() {
	      var self = this;
	      this.layers.forEach(function(layer, id) {
	        self.removeLayer(id);
	      });
	      this.layers.clear();
	      this.sources.clear();
	      this.map = null;
	      this.initialized = false;
	      console.log('[VectorLayerManager] Disposed');
	    }
	  }

	  // Export as global factory.
	  // Guard: do NOT overwrite a newer version that already exposes flat methods
	  // (init, addLayer, …) — e.g. aot-vector-layer-manager.js loaded earlier.
	  if (!global.AoTVectorLayerManager || typeof global.AoTVectorLayerManager.init !== 'function') {
	    global.AoTVectorLayerManager = {
	      create: function() {
	        return new VectorLayerManager();
	      },
	      bind: function(map) {
	        var manager = new VectorLayerManager();
	        manager.init(map);
	        return manager;
	      }
	    };
	  }

	})(window);

	/**
	 * Raster Bridge Layer for AoT
	 * Renders Leaflet/raster tile layers on top of MapLibre-GL map.
	 * Also provides bidirectional sync between Leaflet and MapLibre maps.
	 *
	 * @module AoT-RasterBridge / AoTMapBridge
	 * @version 1.1.0
	 */

	(function(global) {

	  /**
	   * EPSG:5179 (Korean Central Belt 2010) to EPSG:3857 (Web Mercator) transformer.
	   * Uses proj4js if available; falls back to approximate linear transform.
	   *
	   * @param {number} lng - Longitude in EPSG:5179
	   * @param {number} lat - Latitude in EPSG:5179
	   * @returns {{lng: number, lat: number}} EPSG:3857 coordinates
	   */
	  function transformEPSG5179To3857(lng, lat) {
	    if (typeof proj4 !== 'undefined') {
	      try {
	        var result = proj4('EPSG:5179', 'EPSG:3857', [lng, lat]);
	        return { lng: result[0], lat: result[1] };
	      } catch (e) {
	        console.warn('[RasterBridge] proj4 transform failed, using approximate:', e);
	      }
	    }
	    var dL = 0.00011053;
	    var dP = 0.00006320;
	    var wgsLng = lng - dL;
	    var wgsLat = lat - dP;
	    var x = wgsLng * 20037508.34 / 180;
	    var y = Math.log(Math.tan((90 + wgsLat) * Math.PI / 360)) * 6378137.0;
	    return { lng: x, lat: y };
	  }

	  /**
	   * RasterBridge Class
	   * Bridges Leaflet raster layers with MapLibre-GL.
	   */
	  class RasterBridge {

	    /**
	     * @param {maplibregl.Map} map - MapLibre map instance
	     */
	    constructor(map) {
	      this.map = map;
	      this.bridges = new Map();
	      this.container = null;
	      this._createContainer();
	    }

	    /**
	     * Transform a single coordinate pair (EPSG:5179 → EPSG:3857).
	     * @param {number} lng
	     * @param {number} lat
	     * @returns {{lng: number, lat: number}}
	     */
	    transformCoord(lng, lat) {
	      return transformEPSG5179To3857(lng, lat);
	    }

	    /**
	     * Transform an array of coordinates.
	     * @param {Array} coords
	     * @returns {Array}
	     */
	    transformCoords(coords) {
	      var self = this;
	      if (typeof coords[0] === 'number') {
	        var p = this.transformCoord(coords[0], coords[1]);
	        return [p.lng, p.lat];
	      } else if (Array.isArray(coords) && typeof coords[0] === 'object') {
	        return coords.map(function(c) {
	          if (typeof c[0] === 'number') return self.transformCoords(c);
	          return c;
	        });
	      }
	      return coords;
	    }

	    /**
	     * Create overlay container.
	     * @private
	     */
	    _createContainer() {
	      if (!this.map) return;
	      this.container = document.createElement('div');
	      this.container.className = 'aot-raster-bridge';
	      this.container.style.position = 'absolute';
	      this.container.style.top = '0';
	      this.container.style.left = '0';
	      this.container.style.width = '100%';
	      this.container.style.height = '100%';
	      this.container.style.pointerEvents = 'none';
	      this.container.style.zIndex = '1';
	      var mapContainer = this.map.getContainer();
	      if (mapContainer) mapContainer.appendChild(this.container);
	    }

	    /**
	     * Add a raster layer (Leaflet TileLayer) to the bridge.
	     * @param {string} id
	     * @param {string} url
	     * @param {Object} options
	     * @returns {boolean}
	     */
	    addRasterLayer(id, url, options) {
	      options = options || {};
	      if (!this.container || typeof L === 'undefined') {
	        console.error('[RasterBridge] Container or Leaflet not available');
	        return false;
	      }
	      if (this.bridges.has(id)) {
	        console.warn('[RasterBridge] Layer ' + id + ' already exists');
	        return false;
	      }
	      var overlayMap = L.map(this.container, {
	        crs: L.CRS.EPSG3857,
	        attributionControl: false,
	        zoomControl: false,
	        dragging: false,
	        scrollWheelZoom: false,
	        doubleClickZoom: false,
	        touchZoom: false,
	        keyboard: false
	      });
	      this._syncView(overlayMap);
	      var tileLayer = L.tileLayer(url, {
	        opacity: options.opacity || 1.0,
	        maxZoom: options.maxZoom || 19,
	        attribution: options.attribution || ''
	      }).addTo(overlayMap);
	      this.bridges.set(id, {
	        map: overlayMap,
	        tileLayer: tileLayer,
	        visible: true,
	        opacity: options.opacity || 1.0
	      });
	      console.log('[RasterBridge] Added raster layer: ' + id);
	      return true;
	    }

	    /**
	     * Sync Leaflet view with MapLibre map.
	     * @private
	     */
	    _syncView(overlayMap) {
	      var self = this;
	      var updateView = function() {
	        if (!self.map) return;
	        var center = self.map.getCenter();
	        var zoom = self.map.getZoom();
	        var bearing = self.map.getBearing();
	        var pitch = self.map.getPitch();
	        overlayMap.setView([center.lat, center.lng], zoom);
	        if (bearing !== 0 || pitch !== 0) {
	          var container = overlayMap.getContainer();
	          container.style.transform = 'rotate(' + bearing + 'deg)';
	        }
	      };
	      this.map.on('move', updateView);
	      this.map.on('zoom', updateView);
	      this.map.on('rotate', updateView);
	    }

	    /**
	     * Remove a raster layer.
	     * @param {string} id
	     */
	    removeRasterLayer(id) {
	      if (!this.bridges.has(id)) {
	        console.warn('[RasterBridge] Layer ' + id + ' not found');
	        return false;
	      }
	      var bridge = this.bridges.get(id);
	      bridge.map.remove();
	      this.bridges.delete(id);
	      console.log('[RasterBridge] Removed raster layer: ' + id);
	      return true;
	    }

	    /**
	     * Set layer visibility.
	     * @param {string} id
	     * @param {boolean} visible
	     */
	    setVisibility(id, visible) {
	      if (!this.bridges.has(id)) return false;
	      var bridge = this.bridges.get(id);
	      bridge.visible = visible;
	      bridge.tileLayer.setOpacity(visible ? bridge.opacity : 0);
	      return true;
	    }

	    /**
	     * Set layer opacity.
	     * @param {string} id
	     * @param {number} opacity
	     */
	    setOpacity(id, opacity) {
	      if (!this.bridges.has(id)) return false;
	      var bridge = this.bridges.get(id);
	      bridge.opacity = opacity;
	      if (bridge.visible) bridge.tileLayer.setOpacity(opacity);
	      return true;
	    }

	    /**
	     * Dispose and cleanup.
	     */
	    dispose() {
	      this.bridges.forEach(function(bridge) {
	        bridge.map.remove();
	      });
	      this.bridges.clear();
	      if (this.container && this.container.parentNode) {
	        this.container.parentNode.removeChild(this.container);
	      }
	      this.container = null;
	      this.map = null;
	    }
	  }

	  // ============================================================
	  // AoTMapBridge — Bidirectional Leaflet ↔ MapLibre Bridge
	  // Full API expected by test_bridge.html
	  // ============================================================

	  /**
	   * AoTMapBridge: Bidirectional synchronization bridge between Leaflet and MapLibre maps.
	   * Supports tile layers, WMS overlays, base layer switching, and view synchronization.
	   */
	  var _bridgeIdCounter = 0;

	  /**
	   * @param {Object} config
	   * @param {L.Map} config.leaflet - Leaflet map instance
	   * @param {maplibregl.Map} config.maplibre - MapLibre map instance
	   * @param {boolean} [config.syncZoom=true]
	   * @param {boolean} [config.syncPan=true]
	   * @param {boolean} [config.syncCenter=true]
	   * @param {boolean} [config.leafletMaster=true]
	   * @param {number} [config.throttle=16]
	   */
	  function AoTMapBridge(config) {
	    config = config || {};
	    this.id = 'AoTMapBridge_' + (++_bridgeIdCounter);
	    this.leaflet = config.leaflet;
	    this.maplibre = config.maplibre;
	    this.syncZoom = config.syncZoom !== false;
	    this.syncPan = config.syncPan !== false;
	    this.syncCenter = config.syncCenter !== false;
	    this.leafletMaster = config.leafletMaster !== false;
	    this.throttle = config.throttle || 16;

	    this._tileLayers = new Map();   // { key: { layer: L.TileLayer, isBase: bool } }
	    this._wmsLayers = new Map();    // { key: L.TileLayer.WMS }
	    this._activeBase = null;
	    this._listeners = {};
	    this._boundSync = null;
	    this._syncing = false;

	    this._init();
	  }

	  AoTMapBridge.prototype._init = function() {
	    var self = this;
	    if (!this.leaflet || !this.maplibre) {
	      console.error('[AoTMapBridge] Both leaflet and maplibre maps are required');
	      return;
	    }

	    this._boundSync = function() { self._sync(); };

	    if (this.leafletMaster) {
	      this.leaflet.on('move', this._boundSync);
	      this.leaflet.on('zoom', this._boundSync);
	    } else {
	      this.maplibre.on('move', this._boundSync);
	      this.maplibre.on('zoom', this._boundSync);
	    }

	    // Ensure sizes are initialized
	    if (this.leaflet) this.leaflet.invalidateSize();
	    if (this.maplibre) this.maplibre.resize();

	    console.log('[AoTMapBridge] Initialized (master: ' + (this.leafletMaster ? 'Leaflet' : 'MapLibre') + ')');
	  };

	  /**
	   * Synchronize slave map to master map.
	   * @private
	   */
	  AoTMapBridge.prototype._sync = function() {
	    var self = this;
	    if (this._syncing) return;
	    this._syncing = true;
	    setTimeout(function() {
	      try {
	        if (self.leafletMaster) {
	          if (self.syncZoom || self.syncPan || self.syncCenter) {
	            var center = self.leaflet.getCenter();
	            var zoom = self.leaflet.getZoom();
	            self.maplibre.jumpTo({
	              center: [center.lng, center.lat],
	              zoom: zoom,
	              animate: false
	            });
	          }
	        } else {
	          if (self.syncZoom || self.syncPan || self.syncCenter) {
	            var c = self.maplibre.getCenter();
	            var z = self.maplibre.getZoom();
	            self.leaflet.setView([c.lat, c.lng], z, { animate: false });
	          }
	        }
	      } finally {
	        self._syncing = false;
	      }
	    }, this.throttle);
	  };

	  /**
	   * Force immediate sync.
	   */
	  AoTMapBridge.prototype.forceSync = function() {
	    this._syncing = false;
	    this._sync();
	  };

	  /**
	   * Get current sync state.
	   * @returns {Object}
	   */
	  AoTMapBridge.prototype.getSyncState = function() {
	    var lCenter = this.leaflet ? this.leaflet.getCenter() : { lat: 0, lng: 0 };
	    var lZoom = this.leaflet ? this.leaflet.getZoom() : 0;
	    var mCenter = this.maplibre ? this.maplibre.getCenter() : { lat: 0, lng: 0 };
	    var mZoom = this.maplibre ? this.maplibre.getZoom() : 0;

	    var isSynced =
	      Math.abs(lCenter.lat - mCenter.lat) < 0.0001 &&
	      Math.abs(lCenter.lng - mCenter.lng) < 0.0001 &&
	      Math.abs(lZoom - mZoom) < 0.1;

	    return {
	      isSynced: isSynced,
	      master: this.leafletMaster ? 'leaflet' : 'maplibre',
	      leaflet: { center: lCenter, zoom: lZoom },
	      maplibre: { center: mCenter, zoom: mZoom }
	    };
	  };

	  /**
	   * Add a tile layer (Leaflet XYZ) to the bridge.
	   * @param {string} key
	   * @param {Object} config - { url, attribution, opacity, maxZoom }
	   * @param {boolean} [isBase=true] - If true, replaces current base layer
	   */
	  AoTMapBridge.prototype.addTileLayer = function(key, config, isBase) {
	    isBase = isBase !== false;
	    if (!this.leaflet) return false;

	    if (this._tileLayers.has(key)) {
	      console.warn('[AoTMapBridge] Tile layer ' + key + ' already exists');
	      return false;
	    }

	    var layer = L.tileLayer(config.url, {
	      opacity: config.opacity || 1.0,
	      maxZoom: config.maxZoom || 19,
	      attribution: config.attribution || ''
	    });

	    if (isBase) {
	      // Remove existing base layer
	      if (this._activeBase && this._tileLayers.has(this._activeBase)) {
	        var old = this._tileLayers.get(this._activeBase);
	        old.layer.remove();
	      }
	      layer.addTo(this.leaflet);
	      this._activeBase = key;
	    }

	    this._tileLayers.set(key, { layer: layer, isBase: isBase, config: config });
	    console.log('[AoTMapBridge] Added tile layer: ' + key + ' (base: ' + isBase + ')');
	    return true;
	  };

	  /**
	   * Remove a tile layer.
	   * @param {string} key
	   */
	  AoTMapBridge.prototype.removeTileLayer = function(key) {
	    if (!this._tileLayers.has(key)) return false;
	    var entry = this._tileLayers.get(key);
	    entry.layer.remove();
	    if (this._activeBase === key) this._activeBase = null;
	    this._tileLayers.delete(key);
	    console.log('[AoTMapBridge] Removed tile layer: ' + key);
	    return true;
	  };

	  /**
	   * Switch active base tile layer.
	   * @param {string} key
	   */
	  AoTMapBridge.prototype.switchBaseLayer = function(key) {
	    if (!this._tileLayers.has(key)) {
	      console.warn('[AoTMapBridge] Tile layer ' + key + ' not found');
	      return false;
	    }

	    // Hide current base
	    if (this._activeBase && this._tileLayers.has(this._activeBase)) {
	      var old = this._tileLayers.get(this._activeBase);
	      old.layer.remove();
	    }

	    // Show new base
	    var entry = this._tileLayers.get(key);
	    entry.layer.addTo(this.leaflet);
	    this._activeBase = key;

	    this._emit('layer:switch', { layer: key });
	    console.log('[AoTMapBridge] Switched base layer to: ' + key);
	    return true;
	  };

	  /**
	   * Get the active base layer key.
	   * @returns {string|null}
	   */
	  AoTMapBridge.prototype.getActiveBaseLayer = function() {
	    return this._activeBase;
	  };

	  /**
	   * Set overlay layer visibility.
	   * @param {string} key
	   * @param {boolean} visible
	   */
	  AoTMapBridge.prototype.setOverlayVisibility = function(key, visible) {
	    if (!this._tileLayers.has(key)) return false;
	    var entry = this._tileLayers.get(key);
	    if (entry.isBase) return false;
	    if (visible) {
	      entry.layer.addTo(this.leaflet);
	    } else {
	      entry.layer.remove();
	    }
	    return true;
	  };

	  /**
	   * Set overlay layer opacity.
	   * @param {string} key
	   * @param {number} opacity
	   */
	  AoTMapBridge.prototype.setOverlayOpacity = function(key, opacity) {
	    if (!this._tileLayers.has(key)) return false;
	    var entry = this._tileLayers.get(key);
	    entry.layer.setOpacity(opacity);
	    return true;
	  };

	  /**
	   * Add a WMS layer.
	   * @param {string} key
	   * @param {Object} config - { url, layers, attribution }
	   */
	  AoTMapBridge.prototype.addWMSLayer = function(key, config) {
	    if (!this.leaflet) return false;
	    if (this._wmsLayers.has(key)) {
	      console.warn('[AoTMapBridge] WMS layer ' + key + ' already exists');
	      return false;
	    }

	    var layer = L.tileLayer.wms(config.url, {
	      layers: config.layers || '',
	      format: 'image/png',
	      transparent: true,
	      opacity: config.opacity || 0.8,
	      attribution: config.attribution || ''
	    });

	    layer.addTo(this.leaflet);
	    this._wmsLayers.set(key, layer);
	    this._emit('overlay:add', { layer: key, config: config });
	    console.log('[AoTMapBridge] Added WMS layer: ' + key);
	    return true;
	  };

	  /**
	   * Remove a WMS layer.
	   * @param {string} key
	   */
	  AoTMapBridge.prototype.removeWMSLayer = function(key) {
	    if (!this._wmsLayers.has(key)) return false;
	    var layer = this._wmsLayers.get(key);
	    layer.remove();
	    this._wmsLayers.delete(key);
	    this._emit('overlay:remove', { layer: key });
	    console.log('[AoTMapBridge] Removed WMS layer: ' + key);
	    return true;
	  };

	  /**
	   * Set WMS layer opacity.
	   * @param {string} key
	   * @param {number} opacity
	   */
	  AoTMapBridge.prototype.setWMSLayerOpacity = function(key, opacity) {
	    if (!this._wmsLayers.has(key)) return false;
	    var layer = this._wmsLayers.get(key);
	    layer.setOpacity(opacity);
	    return true;
	  };

	  /**
	   * Register an event listener.
	   * @param {string} event
	   * @param {Function} callback
	   */
	  AoTMapBridge.prototype.on = function(event, callback) {
	    if (!this._listeners[event]) this._listeners[event] = [];
	    this._listeners[event].push(callback);
	  };

	  /**
	   * Emit an event.
	   * @private
	   */
	  AoTMapBridge.prototype._emit = function(event, data) {
	    var callbacks = this._listeners[event] || [];
	    callbacks.forEach(function(cb) {
	      try { cb(data); } catch (e) { console.error(e); }
	    });
	  };

	  /**
	   * Destroy the bridge and clean up all layers.
	   */
	  AoTMapBridge.prototype.destroy = function() {

	    // Remove tile layers
	    this._tileLayers.forEach(function(entry) {
	      entry.layer.remove();
	    });
	    this._tileLayers.clear();

	    // Remove WMS layers
	    this._wmsLayers.forEach(function(layer) {
	      layer.remove();
	    });
	    this._wmsLayers.clear();

	    // Detach sync listeners
	    if (this._boundSync) {
	      if (this.leafletMaster && this.leaflet) {
	        this.leaflet.off('move', this._boundSync);
	        this.leaflet.off('zoom', this._boundSync);
	      } else if (!this.leafletMaster && this.maplibre) {
	        this.maplibre.off('move', this._boundSync);
	        this.maplibre.off('zoom', this._boundSync);
	      }
	    }

	    this._listeners = {};
	    console.log('[AoTMapBridge] Destroyed');
	  };

	  // ============================================================
	  // Global exports
	  // ============================================================

	  /**
	   * AoTRasterBridge — single MapLibre map bridge for raster overlays.
	   * @param {maplibregl.Map} map
	   * @returns {RasterBridge}
	   */
	  global.AoTRasterBridge = {
	    create: function(map) {
	      return new RasterBridge(map);
	    }
	  };

	  /**
	   * AoTMapBridge — bidirectional Leaflet ↔ MapLibre bridge factory.
	   * @param {Object} config
	   * @returns {AoTMapBridge}
	   */
	  global.AoTMapBridge = function(config) {
	    return new AoTMapBridge(config);
	  };
	  global.AoTMapBridge.create = function(config) {
	    return new AoTMapBridge(config);
	  };

	})(window);

	/**
	 * MapLibre Draw Module for AoT
	 * Integrates drawing tools with MapLibre-GL using @maplibre/maplibre-gl-draw
	 * 
	 * @module AoT-MapLibreDraw
	 * @version 1.0.0
	 * @requires maplibre-gl
	 * @requires @maplibre/maplibre-gl-draw
	 */

	(function(global) {

	  /**
	   * MapLibre Draw Manager
	   * Handles geometry drawing on MapLibre maps
	   */
	  class MapLibreDraw {
	    /**
	     * @param {maplibregl.Map} map - MapLibre map instance
	     * @param {Object} options - Configuration options
	     */
	    constructor(map, options = {}) {
	      this.map = map;
	      this.draw = null;
	      this.options = {
	        displayControlsDefault: false,
	        controls: {
	          point: true,
	          line_string: true,
	          polygon: true,
	          trash: true
	        },
	        defaultColor: '#3bb2d0',
	        styles: options.styles || null,
	        ...options
	      };
	      this._initialized = false;
	      this._listeners = [];
	    }

	    /**
	     * Initialize the draw control.
	     * Attempts to load @maplibre/maplibre-gl-draw from CDN if not already available.
	     * @param {Object} [initOptions] - Optional init options
	     * @param {boolean} [initOptions.autoLoadDraw=true] - Automatically load Draw CDN if missing
	     * @param {Function} [initOptions.onReady] - Callback when fully initialized
	     * @returns {Promise<boolean>|boolean} Async init returns Promise; sync fallback returns boolean
	     */
	    init(initOptions) {
	      if (this._initialized) {
	        console.warn('[MapLibreDraw] Already initialized');
	        return false;
	      }

	      initOptions = initOptions || {};
	      var autoLoadDraw = initOptions.autoLoadDraw !== false;

	      if (typeof maplibregl === 'undefined') {
	        console.error('[MapLibreDraw] MapLibre-GL not loaded. Include maplibre-gl.js first.');
	        return false;
	      }

	      // Check if Draw is available
	      if (typeof MapLibreDrawControl === 'undefined') {
	        if (autoLoadDraw) {
	          var self = this;
	          // Attempt CDN load of @maplibre/maplibre-gl-draw
	          this._loadDrawFromCDN().then(function(loaded) {
	            if (loaded) {
	              self._initWithDraw();
	            } else {
	              console.warn('[MapLibreDraw] Draw CDN load failed. Using fallback mode.');
	              self._initFallback();
	            }
	          }).catch(function() {
	            console.warn('[MapLibreDraw] Draw CDN load error. Using fallback mode.');
	            self._initFallback();
	          });
	          // Return true to indicate async init started
	          return true;
	        } else {
	          console.warn('[MapLibreDraw] @maplibre/maplibre-gl-draw not loaded. Using fallback mode.');
	          this._initFallback();
	          return true;
	        }
	      }

	      // Draw already available
	      return this._initWithDraw() ? true : false;
	    }

	    /**
	     * Load @maplibre/maplibre-gl-draw from unpkg CDN.
	     * @private
	     * @returns {Promise<boolean>} Resolves true if MapLibreDrawControl becomes available
	     */
	    _loadDrawFromCDN() {
	      return new Promise(function(resolve) {
	        // Use AOT_MAP_LOADER if available (deduplicates concurrent loads)
	        if (typeof window.AOT_MAP_LOADER !== 'undefined' && window.AOT_MAP_LOADER.loadMapLibreDraw) {
	          window.AOT_MAP_LOADER.loadMapLibreDraw({ version: '1.4.3' })
	            .then(function() { resolve(true); })
	            .catch(function() { resolve(false); });
	          return;
	        }

	        // Manual CDN load fallback
	        var version = '1.4.3';
	        var cdnBase = 'https://unpkg.com';

	        // Inject CSS
	        if (!document.querySelector('link[href*="maplibre-gl-draw"]')) {
	          var link = document.createElement('link');
	          link.rel = 'stylesheet';
	          link.href = cdnBase + '/@maplibre/maplibre-gl-draw@' + version + '/dist/maplibre-gl-draw.css';
	          document.head.appendChild(link);
	        }

	        var script = document.createElement('script');
	        script.src = cdnBase + '/@maplibre/maplibre-gl-draw@' + version + '/dist/maplibre-gl-draw.js';
	        script.async = true;
	        script.onload = function() {
	          resolve(typeof window.MapLibreDrawControl !== 'undefined');
	        };
	        script.onerror = function() {
	          resolve(false);
	        };
	        document.head.appendChild(script);
	      });
	    }

	    /**
	     * Initialize with MapLibreDrawControl (after confirmed availability).
	     * @private
	     * @returns {boolean} Success
	     */
	    _initWithDraw() {
	      try {
	        // Handle both MapLibreDrawControl (from @maplibre/maplibre-gl-draw)
	        // and legacy MapDraw or MapboxDraw alternatives
	        var DrawClass = window.MapLibreDrawControl;
	        if (!DrawClass) {
	          DrawClass = window.MapboxDrawControl || window.MapDraw;
	          if (DrawClass) {
	            console.log('[MapLibreDraw] Using legacy draw class:', DrawClass.name || 'anonymous');
	          }
	        }
	        if (!DrawClass) {
	          console.warn('[MapLibreDraw] No draw control class found. Using fallback mode.');
	          this._initFallback();
	          return false;
	        }
	        this.draw = new DrawClass(this.options);
	        this.map.addControl(this.draw, 'top-left');
	        this._initialized = true;

	        // Setup event listeners
	        this._setupListeners();

	        console.log('[MapLibreDraw] Initialized with @maplibre/maplibre-gl-draw v1.4.3');
	        return true;
	      } catch (error) {
	        console.error('[MapLibreDraw] Failed to initialize draw control:', error);
	        this._initFallback();
	        return false;
	      }
	    }

	    /**
	     * Fallback mode using simple click handlers
	     * @private
	     */
	    _initFallback() {
	      this._fallbackMode = true;
	      this._currentMode = null;
	      this._drawnFeatures = [];
	      this._markers = [];
	      this._initialized = true;
	      
	      // Add draw toolbar
	      this._createFallbackToolbar();
	      
	      console.log('[MapLibreDraw] Initialized in fallback mode');
	    }

	    /**
	     * Create fallback toolbar
	     * @private
	     */
	    _createFallbackToolbar() {
	      const toolbar = document.createElement('div');
	      toolbar.className = 'aot-maplibre-draw-toolbar';
	      toolbar.innerHTML = `
        <button class="draw-btn" data-mode="point" title="Add Point">
          <svg width="18" height="18" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4" fill="currentColor"/></svg>
        </button>
        <button class="draw-btn" data-mode="line" title="Add Line">
          <svg width="18" height="18" viewBox="0 0 24 24"><path d="M3 21 L21 3" stroke="currentColor" stroke-width="3"/></svg>
        </button>
        <button class="draw-btn" data-mode="polygon" title="Add Polygon">
          <svg width="18" height="18" viewBox="0 0 24 24"><polygon points="12,2 22,20 2,20" fill="none" stroke="currentColor" stroke-width="2"/></svg>
        </button>
        <button class="draw-btn" data-mode="delete" title="Delete Selected">
          <svg width="18" height="18" viewBox="0 0 24 24"><path d="M6 6 L18 18 M18 6 L6 18" stroke="currentColor" stroke-width="3"/></svg>
        </button>
      `;
	      
	      // Add to map
	      const container = this.map.getContainer();
	      container.parentElement.appendChild(toolbar);
	      
	      // Bind events
	      toolbar.querySelectorAll('.draw-btn').forEach(btn => {
	        btn.addEventListener('click', (e) => {
	          const mode = e.currentTarget.dataset.mode;
	          this.setMode(mode);
	        });
	      });
	      
	      this._toolbar = toolbar;
	    }

	    /**
	     * Set drawing mode
	     * @param {string} mode - Drawing mode (point, line, polygon, delete, simple_select, direct_select)
	     */
	    setMode(mode) {
	      this._currentMode = mode;
	      
	      // Update toolbar UI
	      if (this._toolbar) {
	        this._toolbar.querySelectorAll('.draw-btn').forEach(btn => {
	          btn.classList.toggle('active', btn.dataset.mode === mode);
	        });
	      }

	      if (this._fallbackMode) {
	        this._handleFallbackMode(mode);
	      } else if (this.draw) {
	        this.draw.changeMode(mode);
	      }
	    }

	    /**
	     * Handle fallback mode
	     * @private
	     */
	    _handleFallbackMode(mode) {
	      // Remove existing click handler
	      if (this._clickHandler) {
	        this.map.off('click', this._clickHandler);
	        this._clickHandler = null;
	      }

	      switch(mode) {
	        case 'point':
	          this._clickHandler = (e) => this._addPoint(e.lngLat);
	          this.map.on('click', this._clickHandler);
	          this.map.getCanvas().style.cursor = 'crosshair';
	          break;
	        case 'line':
	        case 'polygon':
	          // For line/polygon, we'd need more complex handling
	          // Simplified: single click adds point, double-click ends
	          this._clickHandler = (e) => this._addVertex(e.lngLat);
	          this.map.on('click', this._clickHandler);
	          this.map.getCanvas().style.cursor = 'crosshair';
	          break;
	        default:
	          this.map.getCanvas().style.cursor = '';
	      }
	    }

	    /**
	     * Add point marker
	     * @private
	     */
	    _addPoint(lngLat) {
	      const el = document.createElement('div');
	      el.className = 'aot-draw-point';
	      el.style.width = '12px';
	      el.style.height = '12px';
	      el.style.background = '#3bb2d0';
	      el.style.borderRadius = '50%';
	      el.style.border = '2px solid white';
	      
	      const marker = new maplibregl.Marker({ element: el })
	        .setLngLat(lngLat)
	        .addTo(this.map);
	      
	      this._markers.push(marker);
	      this._drawnFeatures.push({
	        type: 'Feature',
	        geometry: {
	          type: 'Point',
	          coordinates: [lngLat.lng, lngLat.lat]
	        }
	      });
	      
	      this._emit('draw.create', this._drawnFeatures);
	    }

	    /**
	     * Add vertex for line/polygon
	     * @private
	     */
	    _addVertex(lngLat) {
	      // Simplified vertex addition
	      console.log('[MapLibreDraw] Vertex added at:', lngLat);
	    }

	    /**
	     * Get all drawn features
	     * @returns {GeoJSON.FeatureCollection}
	     */
	    getAll() {
	      if (this._fallbackMode) {
	        return {
	          type: 'FeatureCollection',
	          features: this._drawnFeatures
	        };
	      } else if (this.draw) {
	        return this.draw.getAll();
	      }
	      return { type: 'FeatureCollection', features: [] };
	    }

	    /**
	     * Get selected features
	     * @returns {GeoJSON.FeatureCollection}
	     */
	    getSelected() {
	      if (this.draw) {
	        return this.draw.getSelected();
	      }
	      return { type: 'FeatureCollection', features: [] };
	    }

	    /**
	     * Delete selected features
	     */
	    deleteSelected() {
	      if (this.draw) {
	        this.draw.deleteSelected();
	      } else {
	        this._markers.forEach(m => m.remove());
	        this._markers = [];
	        this._drawnFeatures = [];
	      }
	    }

	    /**
	     * Clear all drawn features
	     */
	    deleteAll() {
	      if (this.draw) {
	        this.draw.deleteAll();
	      } else {
	        this._markers.forEach(m => m.remove());
	        this._markers = [];
	        this._drawnFeatures = [];
	      }
	      this._emit('draw.delete');
	    }

	    /**
	     * Add a feature programmatically
	     * @param {GeoJSON.Feature} feature - Feature to add
	     */
	    add(feature) {
	      if (this.draw) {
	        this.draw.add(feature);
	      } else {
	        this._drawnFeatures.push(feature);
	      }
	    }

	    /**
	     * Setup event listeners
	     * @private
	     */
	    _setupListeners() {
	      if (!this.draw) return;

	      this.draw.on('draw.create', (e) => {
	        this._emit('draw.create', e.features);
	      });

	      this.draw.on('draw.update', (e) => {
	        this._emit('draw.update', e.features);
	      });

	      this.draw.on('draw.delete', (e) => {
	        this._emit('draw.delete', e.features);
	      });

	      this.draw.on('draw.selectionchange', (e) => {
	        this._emit('draw.selectionchange', e.features);
	      });
	    }

	    /**
	     * Add event listener
	     * @param {string} event - Event name
	     * @param {Function} callback - Callback function
	     */
	    on(event, callback) {
	      this._listeners.push({ event, callback });
	    }

	    /**
	     * Emit event
	     * @private
	     */
	    _emit(event, data) {
	      this._listeners
	        .filter(l => l.event === event)
	        .forEach(l => l.callback(data));
	    }

	    /**
	     * Dispose and cleanup
	     */
	    dispose() {
	      if (this.draw) {
	        this.map.removeControl(this.draw);
	        this.draw = null;
	      }
	      
	      if (this._toolbar && this._toolbar.parentNode) {
	        this._toolbar.parentNode.removeChild(this._toolbar);
	      }
	      
	      this._markers.forEach(m => m.remove());
	      this._markers = [];
	      this._drawnFeatures = [];
	      this._listeners = [];
	      this._initialized = false;
	    }
	  }

	  // Export
	  global.AoTMapLibreDraw = {
	    /**
	     * Create a new MapLibreDraw instance
	     * @param {maplibregl.Map} map - MapLibre map instance
	     * @param {Object} options - Configuration options
	     * @returns {MapLibreDraw}
	     */
	    create: function(map, options) {
	      return new MapLibreDraw(map, options);
	    }
	  };

	})(window);

	/**
	 * Map Dependency Loader
	 * Handles parallel loading of Leaflet, Leaflet Draw, and internal map scripts.
	 */
	(function (window) {

	    window.aotScriptLoaders = window.aotScriptLoaders || {};
	    window.aotCssLoaders = window.aotCssLoaders || {};
	    const DEFAULT_BUNDLE = '/static/js/map/bundles/aot-map-bundle.js?v=force_reload';

	    function loadScript(src) {
	        if (window.aotScriptLoaders[src]) {
	            return window.aotScriptLoaders[src];
	        }
	        const promise = new Promise(function (resolve, reject) {
	            if (document.querySelector('script[src="' + src + '"]')) {
	                resolve();
	                return;
	            }
	            const script = document.createElement('script');
	            script.src = src;
	            script.async = true;
	            script.onload = resolve;
	            script.onerror = reject;
	            document.head.appendChild(script);
	        });
	        window.aotScriptLoaders[src] = promise;
	        return promise;
	    }

	    function loadModule(src) {
	        if (window.aotScriptLoaders[src]) {
	            return window.aotScriptLoaders[src];
	        }
	        const promise = import(src).catch(function (err) {
	            console.error('Failed to load module:', src, err);
	            throw err;
	        });
	        window.aotScriptLoaders[src] = promise;
	        return promise;
	    }

	    function loadCss(href) {
	        if (window.aotCssLoaders[href]) return;
	        if (document.querySelector('link[href*="' + href + '"]')) {
	            window.aotCssLoaders[href] = true;
	            return;
	        }
	        const css = document.createElement('link');
	        css.rel = 'stylesheet';
	        css.href = href;
	        document.head.appendChild(css);
	        window.aotCssLoaders[href] = true;
	    }

	    /**
	     * Loads Leaflet, Leaflet Draw, MapLibre-GL, and optional internal scripts in sequence.
	     * [GIS Pure MapLibre v4.0] Leaflet CSS is loaded in layout.html or not at all.
	     * Leaflet Draw CSS not needed - MapLibre Draw is used instead.
	     * @param {Object} config - Configuration object
	     * @param {string} config.bundleUrl - URL for unified AoT map bundle (defaults to /static/js/map/bundles/aot-map-bundle.js)
	     * @param {boolean} config.enableVector - Enable MapLibre-GL vector tile support (default: true)
	     * @param {boolean} [config.loadLeaflet=false] - Load Leaflet (not required for MapLibre-only pages)
	     * @returns {Promise} Resolves when all scripts are loaded
	     */
	    function loadMapDependencies(config) {
	        config = config || {};
	        var loadLeaflet = config.loadLeaflet === true;

	        // 1. Start loading MapLibre-GL CSS (Priority for 3D)
	        loadCss('/static/vendor/maplibre-gl-4.1.2/maplibre-gl.css?v=' + (window.AOT_ASSET_V || ''));

	        // 1b. [GIS Pure MapLibre v4.0] Leaflet CSS no longer loaded by default
	        // If explicitly requested, load for backward compatibility only
	        if (loadLeaflet) {
	            loadCss('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');
	        }

	        // 2. Load MapLibre-GL JS (Vector Tile Support - Required for 3D)
	        var pMapLibre = loadScript('/static/vendor/maplibre-gl-4.1.2/maplibre-gl.js?v=' + (window.AOT_ASSET_V || ''));

	        // 2b. Load Leaflet only if explicitly requested (backward compatibility)
	        var pLeaflet = Promise.resolve();
	        if (loadLeaflet) {
	            pLeaflet = loadScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js');
	            // 3. After Leaflet, load Leaflet Draw (only if Leaflet is loaded)
	            pLeaflet = pLeaflet.then(function() {
	                return loadScript('https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js')
	                    .catch(function(err) { console.error('Failed to load Leaflet.draw:', err); });
	            }).catch(function(err) { console.error('Failed to load Leaflet:', err); });
	        }

	        // 5. Load MapClient (only if Leaflet is loaded)
	        var pClient = Promise.resolve();
	        if (loadLeaflet) {
	            pClient = pLeaflet.then(function() {
	                return loadScript('/static/js/map/bundles/aot-map-client.js?v=' + (window.AOT_ASSET_V || ''))
	                    .catch(function(err) { console.error('Failed to load MapClient:', err); });
	            });
	        }

	        const bundleUrl = config.bundleUrl || DEFAULT_BUNDLE;
	        // [GIS Pure MapLibre v4.0] ES Module Bundle may not be needed for MapLibre-only pages
	        var pBundle = Promise.resolve();
	        {
	            pBundle = Promise.all([pLeaflet, pClient, pMapLibre]).then(function() {
	                return loadModule(bundleUrl);
	            });
	        }

	        // 6. Wait for ALL scripts (MapLibre is now the priority)
	        return Promise.all([pLeaflet, pClient, pBundle, pMapLibre]);
	    }

	    /**
	     * Explicitly load MapLibre-GL JS and CSS from CDN.
	     * Resolves immediately if already loaded; handles concurrent calls via deduplication.
	     * Includes fallback handling when CDN load fails.
	     *
	     * @param {Object} [config] - Loader configuration
	     * @param {string} [config.version='4.1.2'] - MapLibre version
	     * @param {string} [config.cdnBase='https://unpkg.com'] - CDN base URL
	     * @param {number} [config.timeout=15000] - Timeout in ms
	     * @returns {Promise<boolean>} Resolves true when maplibregl is available; rejects on failure
	     */
	    function loadMapLibre(config) {
	        config = config || {};
	        var version = config.version || '4.1.2';
	        var cdnBase = config.cdnBase || 'https://unpkg.com';
	        var timeout = config.timeout || 15000;

	        // Already loaded — resolve immediately
	        if (typeof window.maplibregl !== 'undefined') {
	            console.log('[AOT_MAP_LOADER.loadMapLibre] maplibregl already loaded (version: ' + window.maplibregl.version + ')');
	            return Promise.resolve(true);
	        }

	        // Deduplicate concurrent calls
	        if (window.__aotMapLibreLoadPromise) {
	            return window.__aotMapLibreLoadPromise;
	        }

	        window.__aotMapLibreLoadPromise = new Promise(function(resolve, reject) {
	            var timer = setTimeout(function() {
	                reject(new Error('[AOT_MAP_LOADER.loadMapLibre] CDN load timed out after ' + timeout + 'ms'));
	            }, timeout);

	            var cssUrl = cdnBase + '/maplibre-gl@' + version + '/dist/maplibre-gl.css';
	            var jsUrl  = cdnBase + '/maplibre-gl@' + version + '/dist/maplibre-gl.js';

	            // Load CSS first, then JS
	            loadCss(cssUrl).then(function() {
	                return loadScript(jsUrl);
	            }).then(function() {
	                clearTimeout(timer);
	                if (typeof window.maplibregl === 'undefined') {
	                    reject(new Error('[AOT_MAP_LOADER.loadMapLibre] Script loaded but window.maplibregl is undefined — CDN returned an invalid file'));
	                } else {
	                    console.log('[AOT_MAP_LOADER.loadMapLibre] Loaded maplibregl version: ' + window.maplibregl.version);
	                    resolve(true);
	                }
	            }).catch(function(err) {
	                clearTimeout(timer);
	                reject(err);
	            });
	        });

	        return window.__aotMapLibreLoadPromise;
	    }

	    /**
	     * Load @maplibre/maplibre-gl-draw plugin from CDN.
	     * Requires maplibregl to be loaded first (call loadMapLibre first).
	     *
	     * @param {Object} [config] - Loader configuration
	     * @param {string} [config.version='1.4.3'] - Draw plugin version
	     * @param {string} [config.cdnBase='https://unpkg.com'] - CDN base URL
	     * @returns {Promise<boolean>} Resolves true when MapLibreDrawControl is available
	     */
	    function loadMapLibreDraw(config) {
	        config = config || {};
	        var version = config.version || '1.4.3';
	        var cdnBase = config.cdnBase || 'https://unpkg.com';

	        if (typeof window.MapLibreDrawControl !== 'undefined') {
	            console.log('[AOT_MAP_LOADER.loadMapLibreDraw] MapLibreDrawControl already loaded');
	            return Promise.resolve(true);
	        }

	        if (typeof window.maplibregl === 'undefined') {
	            return Promise.reject(new Error('[AOT_MAP_LOADER.loadMapLibreDraw] maplibregl must be loaded first'));
	        }

	        if (window.__aotMapLibreDrawLoadPromise) {
	            return window.__aotMapLibreDrawLoadPromise;
	        }

	        window.__aotMapLibreDrawLoadPromise = new Promise(function(resolve, reject) {
	            var cssUrl = cdnBase + '/@maplibre/maplibre-gl-draw@' + version + '/dist/maplibre-gl-draw.css';
	            var jsUrl  = cdnBase + '/@maplibre/maplibre-gl-draw@' + version + '/dist/maplibre-gl-draw.js';

	            // Inject CSS (non-blocking)
	            if (!document.querySelector('link[href*="maplibre-gl-draw"]')) {
	                var link = document.createElement('link');
	                link.rel = 'stylesheet';
	                link.href = cssUrl;
	                document.head.appendChild(link);
	            }

	            // Load JS
	            var script = document.createElement('script');
	            script.src = jsUrl;
	            script.async = true;
	            script.onload = function() {
	                if (typeof window.MapLibreDrawControl !== 'undefined') {
	                    console.log('[AOT_MAP_LOADER.loadMapLibreDraw] Loaded MapLibreDrawControl v' + version);
	                    resolve(true);
	                } else {
	                    reject(new Error('[AOT_MAP_LOADER.loadMapLibreDraw] Script loaded but MapLibreDrawControl not found'));
	                }
	            };
	            script.onerror = function() {
	                reject(new Error('[AOT_MAP_LOADER.loadMapLibreDraw] Failed to load: ' + jsUrl));
	            };
	            document.head.appendChild(script);
	        });

	        return window.__aotMapLibreDrawLoadPromise;
	    }

	    /**
	     * Load both MapLibre-GL core and the Draw plugin sequentially.
	     * Resolves even if Draw fails (fallback mode will be used by MapLibreDraw).
	     *
	     * @param {Object} [config] - Combined loader config (same as loadMapLibre)
	     * @param {boolean} [config.loadDraw=true] - Also load draw plugin
	     * @returns {Promise<Object>} Resolves { maplibre: true, draw: true|false }
	     */
	    function loadVectorDependencies(config) {
	        config = config || {};
	        var loadDraw = config.loadDraw !== false;

	        return loadMapLibre(config).then(function() {
	            if (loadDraw) {
	                return loadMapLibreDraw(config).catch(function(err) {
	                    console.warn('[AOT_MAP_LOADER] MapLibreDraw load failed (fallback mode will be used):', err.message);
	                    return false;
	                });
	            }
	            return false;
	        }).then(function(drawLoaded) {
	            return { maplibre: true, draw: drawLoaded };
	        });
	    }

	    window.AOT_MAP_LOADER = {
	        loadMapDependencies: loadMapDependencies,
	        loadMapLibre: loadMapLibre,
	        loadMapLibreDraw: loadMapLibreDraw,
	        loadVectorDependencies: loadVectorDependencies,
	        loadScript: loadScript,
	        loadCss: loadCss,
	        loadModule: loadModule,
	        isMapLibreLoaded: function() {
	            return typeof window.maplibregl !== 'undefined';
	        },
	        isLeafletLoaded: function() {
	            return typeof L !== 'undefined';
	        }
	    };

	})(window);

	/**
	 * AoT Geo JavaScript Bundle
	 * Main Entry Point - Vector Transition Modules
	 * 
	 * IIFE 소스 파일을 직접 import하여 번들에 포함
	 */


	// ============================================================
	// Vector Transition Module Exports (window에서 참조)
	// ============================================================
	const AoTMapLibre = window.AoTMapLibre;
	const VectorLayerManager = window.AoTVectorLayerManager;
	const RasterBridge = window.AoTRasterBridge;
	const MapBridge = window.AoTMapBridge;
	const MapLibreDraw = window.AoTMapLibreDraw;
	const AOT_MAP_LOADER = window.AOT_MAP_LOADER;

	exports.AOT_MAP_LOADER = AOT_MAP_LOADER;
	exports.AoTMapLibre = AoTMapLibre;
	exports.MapBridge = MapBridge;
	exports.MapLibreDraw = MapLibreDraw;
	exports.RasterBridge = RasterBridge;
	exports.VectorLayerManager = VectorLayerManager;

	return exports;

})({});
//# sourceMappingURL=aot-geo-all.bundle.js.map
