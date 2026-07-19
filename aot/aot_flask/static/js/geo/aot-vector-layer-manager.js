/**
 * Vector Layer Manager for AoT
 * Handles vector tile layers with MapLibre-GL integration
 *
 * @module AoT-VectorLayerManager
 * @version 1.1.0
 */

(function(global) {
  'use strict';

  // [FIX] Patch MapLibre Evented to add callInitHooks for Leaflet compatibility
  // MapLibre's Evented doesn't have callInitHooks, but some AoT code expects it
  if (typeof maplibregl !== 'undefined' && maplibregl.Evented) {
    if (!maplibregl.Evented.prototype.callInitHooks) {
      maplibregl.Evented.prototype.callInitHooks = function() {
        // No-op: MapLibre doesn't use this pattern
        // Added for compatibility with code that expects this method
      };
    }
  }

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
        return false;
      }
      this.map = map;
      this.initialized = true;
      return true;
    }

    /**
     * Add a vector tile layer from GIS input configuration.
     * @param {Object} gisConfig - GIS input configuration from backend
     * @returns {boolean} Success status
     */
    addLayer(gisConfig) {
      if (!this.initialized || !this.map) {
        return false;
      }

      const layerId = gisConfig.unique_id || 'vector_' + Date.now();

      if (this.layers.has(layerId)) {
        return false;
      }

      const type = gisConfig.type || 'vector';

      if (type === 'vector') {
        return this._addVectorLayer(layerId, gisConfig);
      } else if (type === 'tile' || type === 'wms') {
        return this._addRasterBridgeLayer(layerId, gisConfig);
      } else if (type === 'raster') {
        // Handle RainViewer raster overlays
        if (gisConfig.provider === 'rainviewer') {
          return this.addRainViewerSource(layerId, gisConfig);
        } else {
          // Generic raster source
          return this._addRasterBridgeLayer(layerId, gisConfig);
        }
      }

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
        return false;
      }
      if (!options || !options.tiles) {
        return false;
      }
      if (this.map.getSource(sourceId)) {
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
        return false;
      }
      if (this.map.getSource(sourceId)) {
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
        return false;
      }
      if (!this.map.getSource(sourceId)) {
        return false;
      }
      if (this.map.getLayer(layerId)) {
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

      return true;
    }

    /**
     * Add a RainViewer radar overlay as a raster tile source.
     * Supports both raster mode (Leaflet) and vector mode (MapLibre).
     * @param {string} sourceId - Unique source identifier
     * @param {Object} rainviewerConfig - RainViewer configuration
     * @param {string} rainviewerConfig.url - Tile URL pattern with {ts} placeholder
     * @param {string} [rainviewerConfig.colorScheme='2'] - Color scheme (2=Universal Blue)
     * @param {boolean} [rainviewerConfig.smoothing=true] - Enable smoothing
     * @param {number} [rainviewerConfig.opacity=0.7] - Overlay opacity
     * @param {number} [rainviewerConfig.maxZoom=7] - Maximum zoom level
     * @returns {boolean} Success
     */
    addRainViewerSource(sourceId, rainviewerConfig) {
      if (!this.initialized || !this.map) {
        return false;
      }
      
      var config = rainviewerConfig || {};
      var url = config.url || 'https://tilecache.rainviewer.com/v2/radar/{ts}/256/{z}/{x}/{y}/2/1_1.png';
      var opacity = config.opacity !== undefined ? config.opacity : 0.7;
      var maxZoom = config.maxZoom !== undefined ? config.maxZoom : 7;
      
      // Add raster source with timestamp placeholder
      // Note: {ts} will be replaced by RainViewer animation controller
      var tileUrl = url.replace('{ts}', config.currentTimestamp || '1609401600');
      
      this.map.addSource(sourceId, {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: 256,
        minzoom: 0,
        maxzoom: maxZoom,
        bounds: [-180, -85.0511, 180, 85.0511], // Global coverage
        attribution: '&copy; <a href="https://www.rainviewer.com/">RainViewer</a>'
      });

      // Add raster layer on top of base map
      this.map.addLayer({
        id: sourceId + '_layer',
        type: 'raster',
        source: sourceId,
        paint: {
          'raster-opacity': opacity,
          'raster-saturation': 0,
          'raster-contrast': 0
        }
      });

      var layerEntry = {
        id: sourceId,
        type: 'raster',
        provider: 'rainviewer',
        url: url,
        currentTimestamp: config.currentTimestamp || null,
        colorScheme: config.colorScheme || '2',
        smoothing: config.smoothing !== false,
        name: config.name || 'RainViewer Radar',
        visible: true,
        opacity: opacity,
        maxZoom: maxZoom,
        frameInterval: config.frameInterval || 600, // 10 minutes
        totalFrames: config.totalFrames || 12, // 2 hours
        animationPlaying: false,
        animationTimer: null
      };

      this.layers.set(sourceId, layerEntry);
      return true;
    }

    /**
     * Update RainViewer tile URL with new timestamp.
     * @param {string} sourceId - Source ID
     * @param {number} timestamp - Unix timestamp
     */
    updateRainViewerTimestamp(sourceId, timestamp) {
      var layer = this.layers.get(sourceId);
      if (!layer || layer.provider !== 'rainviewer') {
        return false;
      }

      layer.currentTimestamp = timestamp;
      var newUrl = layer.url.replace('{ts}', timestamp.toString());

      // Update source tiles
      if (this.map && this.map.getSource(sourceId)) {
        this.map.getSource(sourceId).setTiles([newUrl]);
      }
      return true;
    }

    /**
     * Start RainViewer radar animation.
     * @param {string} sourceId - Source ID
     * @param {number[]} timestamps - Array of Unix timestamps
     * @param {number} [interval=600] - Frame interval in ms
     */
    startRainViewerAnimation(sourceId, timestamps, interval) {
      var layer = this.layers.get(sourceId);
      if (!layer || layer.provider !== 'rainviewer') {
        return false;
      }

      // Stop existing animation
      this.stopRainViewerAnimation(sourceId);

      var currentIndex = 0;
      var self = this;
      interval = interval || layer.frameInterval || 600;

      layer.animationPlaying = true;
      layer.animationTimer = setInterval(function() {
        currentIndex = (currentIndex + 1) % timestamps.length;
        self.updateRainViewerTimestamp(sourceId, timestamps[currentIndex]);
      }, interval);

      return true;
    }

    /**
     * Stop RainViewer radar animation.
     * @param {string} sourceId - Source ID
     */
    stopRainViewerAnimation(sourceId) {
      var layer = this.layers.get(sourceId);
      if (!layer) return false;

      if (layer.animationTimer) {
        clearInterval(layer.animationTimer);
        layer.animationTimer = null;
      }
      layer.animationPlaying = false;
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
        return false;
      }
      if (!maptilerConfig || !maptilerConfig.apiKey) {
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
      return true;
    }

    /**
     * Remove a layer.
     * @param {string} layerId - Layer ID to remove
     */
    removeLayer(layerId) {
      if (!this.layers.has(layerId) && !this.sources.has(layerId)) {
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

      return true;
    }

    /**
     * Set active base layer.
     * @param {string} layerId - Layer ID to activate
     */
    setActiveLayer(layerId) {
      this.activeLayerId = layerId;
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
     * Add a raster tile source (XYZ/WMS/etc) as a MapLibre raster source.
     * Supports RainViewer, GeoServer, and other XYZ/WMS tile providers.
     * @param {string} sourceId - Unique source identifier
     * @param {Object} options - Raster source options
     * @param {string} options.url - Tile URL pattern (supports {z}/{x}/{y})
     * @param {number} [options.tileSize=256] - Tile size
     * @param {number} [options.minzoom=0] - Minimum zoom
     * @param {number} [options.maxzoom=18] - Maximum zoom
     * @param {number} [options.opacity=1.0] - Layer opacity
     * @param {boolean} [options.visible=true] - Initial visibility
     * @param {string} [options.attribution=''] - Attribution string
     * @returns {boolean} Success
     */
    addRasterSource(sourceId, options) {
      if (!this.initialized || !this.map) {
        return false;
      }

      var opts = options || {};
      var url = opts.url;
      if (!url) {
        return false;
      }

      // Build MapLibre raster source config
      var sourceConfig = {
        type: 'raster',
        tiles: [url],
        tileSize: opts.tileSize || 256,
        minzoom: opts.minzoom !== undefined ? opts.minzoom : 0,
        maxzoom: opts.maxzoom !== undefined ? opts.maxzoom : 18,
        attribution: opts.attribution || ''
      };

      // Handle WMS-style URLs
      if (opts.type === 'wms' && opts.params) {
        // WMS sources use a different approach - we'll create tiles from WMS GetMap
        sourceConfig.type = 'raster';
        // For WMS, we need to construct the URL properly
        // This is a simplified version; full WMS support may need additional handling
      }

      // Remove existing source if present
      if (this.map.getSource(sourceId)) {
        this.map.removeSource(sourceId);
      }

      // Add source
      this.map.addSource(sourceId, sourceConfig);

      // Add raster layer
      var layerId = sourceId + '_layer';
      if (this.map.getLayer(layerId)) {
        this.map.removeLayer(layerId);
      }

      this.map.addLayer({
        id: layerId,
        type: 'raster',
        source: sourceId,
        paint: {
          'raster-opacity': opts.opacity !== undefined ? opts.opacity : 1.0
        },
        layout: {
          visibility: opts.visible !== false ? 'visible' : 'none'
        }
      });

      // Store layer info
      var layerEntry = {
        id: sourceId,
        type: 'raster',
        provider: opts.provider || 'xyz',
        url: url,
        name: opts.name || sourceId,
        visible: opts.visible !== false,
        opacity: opts.opacity !== undefined ? opts.opacity : 1.0,
        maxZoom: opts.maxzoom || 18
      };

      this.layers.set(sourceId, layerEntry);
      this.sources.set(sourceId, { type: 'raster', config: sourceConfig });

      return true;
    }

    /**
     * Add an image overlay (non-tiled image) to the map.
     * Useful for static overlays like legends or static map images.
     * @param {string} imageId - Unique image identifier
     * @param {Object} options - Image options
     * @param {string} options.url - Image URL
     * @param {number[]} options.coordinates - [[tl_lng, tl_lat], [tr_lng, tr_lat], [br_lng, br_lat], [bl_lng, bl_lat]]
     * @param {number} [options.opacity=1.0] - Image opacity
     * @returns {Promise<boolean>}
     */
    addImageOverlay(imageId, options) {
      var self = this;
      return new Promise(function(resolve, reject) {
        if (!self.initialized || !self.map) {
          resolve(false);
          return;
        }

        var opts = options || {};
        if (!opts.url || !opts.coordinates) {
          resolve(false);
          return;
        }

        // Load the image
        self.map.loadImage(opts.url, function(error, image) {
          if (error) {
            reject(error);
            return;
          }

          // Add image to map
          if (!self.map.hasImage(imageId)) {
            self.map.addImage(imageId, image);
          }

          // Add source
          var sourceConfig = {
            type: 'image',
            url: opts.url,
            coordinates: opts.coordinates
          };

          if (self.map.getSource(imageId)) {
            self.map.removeSource(imageId);
          }

          self.map.addSource(imageId, sourceConfig);

          // Add layer
          var layerId = imageId + '_image_layer';
          if (self.map.getLayer(layerId)) {
            self.map.removeLayer(layerId);
          }

          self.map.addLayer({
            id: layerId,
            type: 'raster',
            source: imageId,
            paint: {
              'raster-opacity': opts.opacity !== undefined ? opts.opacity : 1.0
            }
          });

          // Store layer info
          self.layers.set(imageId, {
            id: imageId,
            type: 'image',
            name: opts.name || imageId,
            visible: true,
            opacity: opts.opacity !== undefined ? opts.opacity : 1.0
          });

          resolve(true);
        });
      });
    }

    /**
     * Add terrain source for 3D terrain visualization.
     * @param {Object} options - Terrain options
     * @param {string} [options.url] - Terrain tiles JSON URL
     * @param {string} [options.apiKey] - API key for terrain tiles
     * @param {number} [options.exaggeration=1.5] - Terrain exaggeration factor
     * @returns {boolean} Success
     */
    addTerrain(options) {
      if (!this.initialized || !this.map) {
        return false;
      }

      var opts = options || {};
      var apiKey = opts.apiKey || (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.keys && window.AOT_GEO_CONFIG.keys.maptiler) || '';

      // Build terrain source
      var sourceId = opts.sourceId || 'terrain-source';
      var terrainUrl = opts.url || 'https://api.maptiler.com/tiles/terrain-rgb-v2/tiles.json?key=' + apiKey;

      try {
        // Check if source already exists
        if (this.map.getSource(sourceId)) {
          this.map.removeSource(sourceId);
        }

        // Add terrain raster-dem source
        this.map.addSource(sourceId, {
          type: 'raster-dem',
          url: terrainUrl,
          tileSize: 256,
          maxzoom: 14
        });

        // Set terrain
        this.map.setTerrain({
          source: sourceId,
          exaggeration: opts.exaggeration !== undefined ? opts.exaggeration : 1.5
        });

        // Add hillshade layer if not exists
        var hillshadeId = 'terrain-hillshade';
        if (!this.map.getLayer(hillshadeId)) {
          this.map.addLayer({
            id: hillshadeId,
            source: sourceId,
            type: 'hillshade',
            layout: { visibility: 'visible' },
            paint: {
              'hillshade-shadow-color': '#473B24',
              'hillshade-illumination-anchor': 'map',
              'hillshade-exaggeration': opts.hillshadeExaggeration || 0.5
            }
          }, 'waterway-label');
        }

        return true;
      } catch (e) {
        return false;
      }
    }

    /**
     * Remove terrain from the map.
     * @returns {boolean} Success
     */
    removeTerrain() {
      if (!this.map) return false;

      try {
        this.map.setTerrain(null);

        if (this.map.getLayer('terrain-hillshade')) {
          this.map.removeLayer('terrain-hillshade');
        }

        if (this.map.getSource('terrain-source')) {
          this.map.removeSource('terrain-source');
        }

        return true;
      } catch (e) {
        return false;
      }
    }

    /**
     * Set map pitch (vertical tilt for 3D effect).
     * @param {number} pitch - Pitch in degrees (0=top-down, max 85)
     * @returns {boolean} Success
     */
    setPitch(pitch) {
      if (!this.map) {
        return false;
      }
      pitch = Math.max(0, Math.min(85, parseFloat(pitch) || 0));
      try {
        this.map.setPitch(pitch);
        return true;
      } catch (e) {
        return false;
      }
    }

    /**
     * Set map bearing (rotation/north direction).
     * @param {number} bearing - Bearing in degrees (0=North up)
     * @returns {boolean} Success
     */
    setBearing(bearing) {
      if (!this.map) {
        return false;
      }
      bearing = parseFloat(bearing) || 0;
      try {
        this.map.setBearing(bearing);
        return true;
      } catch (e) {
        return false;
      }
    }

    /**
     * Set both pitch and bearing together (for smooth 3D transition).
     * @param {number} pitch - Pitch in degrees (0=flat)
     * @param {number} bearing - Bearing in degrees
     * @param {Object} [options] - Transition options
     * @param {number} [options.duration=1000] - Animation duration in ms
     * @returns {boolean} Success
     */
    set3DCamera(pitch, bearing, options) {
      if (!this.map) {
        return false;
      }
      pitch = Math.max(0, Math.min(85, parseFloat(pitch) || 0));
      bearing = parseFloat(bearing) || 0;
      var opts = options || {};
      var duration = opts.duration !== undefined ? opts.duration : 1000;

      try {
        this.map.easeTo({
          pitch: pitch,
          bearing: bearing,
          duration: duration
        });
        return true;
      } catch (e) {
        return false;
      }
    }

    /**
     * Reset 3D camera to default (pitch=0, bearing=0).
     * @param {Object} [options] - Transition options
     * @param {number} [options.duration=1000] - Animation duration in ms
     * @returns {boolean} Success
     */
    reset3DCamera(options) {
      return this.set3DCamera(0, 0, options);
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
    }
  }

  // Export as global factory + flat-method compat shim.
  //
  // Older callers (e.g. aot-map-widget-vector.js) invoke
  // `window.AoTVectorLayerManager.init(map)` / `.addLayer(...)` directly,
  // assuming a singleton. We keep `create()` / `bind()` for new code and
  // additionally expose `init` / `addLayer` / `removeLayer` / `dispose`
  // that proxy to a lazily-created singleton.
  var _singleton = null;
  function _ensure() {
    if (!_singleton) _singleton = new VectorLayerManager();
    return _singleton;
  }

  global.AoTVectorLayerManager = {
    create: function() {
      return new VectorLayerManager();
    },
    bind: function(map) {
      var manager = new VectorLayerManager();
      manager.init(map);
      return manager;
    },
    // ---- Flat-method compat shim (delegates to singleton) ----
    init: function(map) {
      return _ensure().init(map);
    },
    addLayer: function(gisConfig) {
      return _ensure().addLayer(gisConfig);
    },
    removeLayer: function(layerId) {
      var m = _ensure();
      return typeof m.removeLayer === 'function' ? m.removeLayer(layerId) : false;
    },
    dispose: function() {
      if (_singleton && typeof _singleton.dispose === 'function') {
        _singleton.dispose();
      }
      _singleton = null;
    },
    _instance: function() { return _singleton; }
  };

})(window);
