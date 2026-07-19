/**
 * Vector Layer Manager for AoT
 * Handles vector tile layers with MapLibre-GL integration
 *
 * @module AoT-VectorLayerManager
 * @version 1.1.0
 */

(function(global) {
  'use strict';

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
