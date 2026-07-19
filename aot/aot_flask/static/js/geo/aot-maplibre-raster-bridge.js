/**
 * aot-maplibre-raster-bridge.js
 * Leaflet ↔ MapLibre Bridge Layer for Synchronized Raster Map Display
 *
 * [FIX] Patch MapLibre Evented for callInitHooks compatibility
 */
(function() {
  'use strict';
  if (typeof maplibregl !== 'undefined' && maplibregl.Evented) {
    if (!maplibregl.Evented.prototype.callInitHooks) {
      maplibregl.Evented.prototype.callInitHooks = function() {
        // MapLibre doesn't use this init hooks pattern
        // Added for compatibility with Leaflet/Class.js code
      };
    }
  }
})();

/**
 * Leaflet ↔ MapLibre Bridge Layer for Synchronized Raster Map Display
 *
 * This module provides a bridge layer that synchronizes:
 * - Coordinate system (lat/lng) between Leaflet and MapLibre
 * - Zoom level synchronization
 * - Panning/drag synchronization
 * - WMS raster layer bridging
 * - Leaflet.Draw compatible layer switching
 *
 * @module AoTMapBridge
 * @version 1.1.0
 * @requires Leaflet 1.x, MapLibre-GL
 *
 * @example
 * // Initialize bridge between Leaflet and MapLibre maps
 * const bridge = AoTMapBridge.create({
 *   leaflet: leafletMap,
 *   maplibre: maplibreMap,
 *   syncZoom: true,
 *   syncPan: true,
 *   syncCenter: true
 * });
 *
 * @example
 * // Add WMS raster layer to MapLibre
 * bridge.addWMSLayer('my-wms', {
 *   url: 'https://example.com/wms',
 *   layers: 'mylayer',
 *   format: 'image/png',
 *   transparent: true
 * });
 *
 * @example
 * // Leaflet.Draw compatible layer switching
 * bridge.addTileLayer('osm', {
 *   url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
 *   attribution: '© OpenStreetMap'
 * });
 * bridge.switchBaseLayer('osm');
 */

(function(global) {
  'use strict';

  /**
   * AoT Map Bridge Namespace
   * @namespace AoTMapBridge
   */
  const AoTMapBridge = {
    /** @type {Map<string, BridgeInstance>} Active bridge instances */
    instances: new Map(),

    /** @type {number} Default sync throttle delay (ms) */
    DEFAULT_THROTTLE: 16,

    /** @type {string} Bridge instance ID counter */
    _instanceCounter: 0,

    /** @type {Object} Default tile layer templates */
    DEFAULT_TILE_LAYERS: {
      osm: {
        url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attribution: '© OpenStreetMap',
        maxZoom: 19,
        subdomains: ['a', 'b', 'c']
      },
      satellite: {
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attribution: '© Esri',
        maxZoom: 19
      },
      terrain: {
        url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        attribution: '© OpenTopoMap',
        maxZoom: 17,
        subdomains: ['a', 'b', 'c']
      }
    }
  };

  /**
   * Bridge Instance Class
   * Manages synchronization between Leaflet and MapLibre maps
   */
  class BridgeInstance {
    /**
     * Create a new bridge instance
     * @param {Object} config - Bridge configuration
     * @param {L.Map} config.leaflet - Leaflet map instance
     * @param {maplibregl.Map} config.maplibre - MapLibre map instance
     * @param {boolean} [config.syncZoom=true] - Enable zoom synchronization
     * @param {boolean} [config.syncPan=true] - Enable pan synchronization
     * @param {boolean} [config.syncCenter=true] - Enable center synchronization
     * @param {boolean} [config.leafletMaster=true] - Leaflet is the master (source of truth)
     * @param {number} [config.throttle=16] - Throttle delay for sync events
     */
    constructor(config) {
      this.id = 'bridge_' + (AoTMapBridge._instanceCounter++);
      this.leafletMap = config.leaflet;
      this.maplibreMap = config.maplibre;
      this.options = {
        syncZoom: config.syncZoom !== false,
        syncPan: config.syncPan !== false,
        syncCenter: config.syncCenter !== false,
        leafletMaster: config.leafletMaster !== false,
        throttle: config.throttle || AoTMapBridge.DEFAULT_THROTTLE
      };

      // Event tracking to prevent infinite loops
      this._syncing = false;
      this._leafletSyncing = false;
      this._maplibreSyncing = false;

      // Throttle timers
      this._throttleTimer = null;
      this._lastSync = 0;

      // WMS layer storage
      this.wmsLayers = new Map();

      // Tile layer storage (Leaflet.Draw compatible)
      this.tileLayers = new Map();
      this._activeBaseLayer = null;
      this._baseLayerSourceId = 'bridge_base_layer_source';
      this._baseLayerLayerId = 'bridge_base_layer';

      // Overlay layer storage (Leaflet.Draw compatible)
      this.overlayLayers = new Map();

      // Event callbacks (Leaflet.Draw compatible)
      this._eventCallbacks = {};

      // Initialize synchronization
      this._bindEvents();
    }

    /**
     * Bind synchronization events to both maps
     * @private
     */
    _bindEvents() {
      const opts = this.options;

      // Leaflet event handlers
      if (opts.syncZoom || opts.syncPan || opts.syncCenter) {
        this.leafletMap.on('moveend', this._onLeafletMoveEnd.bind(this));
        this.leafletMap.on('zoomend', this._onLeafletZoomEnd.bind(this));
        this.leafletMap.on('dragend', this._onLeafletDragEnd.bind(this));
      }

      // MapLibre event handlers
      if (opts.syncZoom || opts.syncPan || opts.syncCenter) {
        this.maplibreMap.on('moveend', this._onMapLibreMoveEnd.bind(this));
        this.maplibreMap.on('zoomend', this._onMapLibreZoomEnd.bind(this));
        this.maplibreMap.on('dragend', this._onMapLibreDragEnd.bind(this));
      }
    }

    /**
     * Throttle function to prevent excessive sync calls
     * @private
     */
    _throttle(callback) {
      const now = Date.now();
      if (now - this._lastSync < this.options.throttle) {
        clearTimeout(this._throttleTimer);
        this._throttleTimer = setTimeout(() => {
          this._lastSync = Date.now();
          callback();
        }, this.options.throttle);
      } else {
        this._lastSync = now;
        callback();
      }
    }

    /**
     * Sync from Leaflet to MapLibre
     * @private
     */
    _syncLeafletToMapLibre() {
      if (this._maplibreSyncing) return;
      this._leafletSyncing = true;

      try {
        const center = this.leafletMap.getCenter();
        const zoom = this.leafletMap.getZoom();

        // Convert Leaflet LatLng to MapLibre format [lng, lat]
        const maplibreCenter = [center.lng, center.lat];

        // Sync center
        if (this.options.syncCenter || this.options.syncPan) {
          this.maplibreMap.setCenter(maplibreCenter);
        }

        // Sync zoom
        if (this.options.syncZoom) {
          this.maplibreMap.setZoom(zoom);
        }
      } catch (e) {
        console.error('[AoTMapBridge] Leaflet->MapLibre sync error:', e);
      } finally {
        this._leafletSyncing = false;
      }
    }

    /**
     * Sync from MapLibre to Leaflet
     * @private
     */
    _syncMapLibreToLeaflet() {
      if (this._leafletSyncing) return;
      this._maplibreSyncing = true;

      try {
        const center = this.maplibreMap.getCenter();
        const zoom = this.maplibreMap.getZoom();

        // Convert MapLibre center to Leaflet format [lat, lng]
        const leafletCenter = L.latLng(center.lat, center.lng);

        // Sync center
        if (this.options.syncCenter || this.options.syncPan) {
          this.leafletMap.setView(leafletCenter, zoom);
        }

        // Sync zoom
        if (this.options.syncZoom) {
          this.leafletMap.setZoom(zoom);
        }
      } catch (e) {
        console.error('[AoTMapBridge] MapLibre->Leaflet sync error:', e);
      } finally {
        this._maplibreSyncing = false;
      }
    }

    // Leaflet event handlers
    _onLeafletMoveEnd(e) {
      if (!this.options.leafletMaster) return;
      this._throttle(() => this._syncLeafletToMapLibre());
    }

    _onLeafletZoomEnd(e) {
      if (!this.options.leafletMaster) return;
      this._throttle(() => this._syncLeafletToMapLibre());
    }

    _onLeafletDragEnd(e) {
      if (!this.options.leafletMaster) return;
      this._throttle(() => this._syncLeafletToMapLibre());
    }

    // MapLibre event handlers
    _onMapLibreMoveEnd(e) {
      if (this.options.leafletMaster) return;
      this._throttle(() => this._syncMapLibreToLeaflet());
    }

    _onMapLibreZoomEnd(e) {
      if (this.options.leafletMaster) return;
      this._throttle(() => this._syncMapLibreToLeaflet());
    }

    _onMapLibreDragEnd(e) {
      if (this.options.leafletMaster) return;
      this._throttle(() => this._syncMapLibreToLeaflet());
    }

    /**
     * Add WMS raster layer to MapLibre
     * @param {string} id - Layer identifier
     * @param {Object} options - WMS options
     * @param {string} options.url - WMS service URL
     * @param {string} options.layers - Comma-separated layer names
     * @param {string} [options.format='image/png'] - Image format
     * @param {boolean} [options.transparent=true] - Transparent background
     * @param {Object} [options.paintOptions={}] - Additional paint options
     * @returns {string} Layer ID
     */
    addWMSLayer(id, options) {
      const sourceId = 'wms_' + id + '_source';
      const layerId = 'wms_' + id + '_layer';

      // Check if source already exists
      if (this.maplibreMap.getSource(sourceId)) {
        console.warn('[AoTMapBridge] WMS source ' + sourceId + ' already exists');
        return layerId;
      }

      // Build WMS URL with parameters
      const params = new URLSearchParams({
        service: 'WMS',
        version: '1.1.1',
        request: 'GetMap',
        layers: options.layers,
        format: options.format || 'image/png',
        transparent: options.transparent !== false,
        width: 256,
        height: 256
      });

      // Add bbox for tile coordinates
      const wmsUrl = options.url + '?' + params.toString() + '&bbox={bbox-epsg-3857}';

      // Add raster source
      this.maplibreMap.addSource(sourceId, {
        type: 'raster',
        tiles: [wmsUrl],
        tileSize: 256,
        attribution: options.attribution || ''
      });

      // Add raster layer
      this.maplibreMap.addLayer({
        id: layerId,
        type: 'raster',
        source: sourceId,
        paint: Object.assign({
          'raster-opacity': options.opacity || 0.8,
          'raster-saturation': 0,
          'raster-contrast': 0
        }, options.paintOptions || {})
      });

      // Store reference
      this.wmsLayers.set(id, {
        sourceId: sourceId,
        layerId: layerId,
        options: options
      });

      console.log('[AoTMapBridge] WMS layer added: ' + id);
      return layerId;
    }

    /**
     * Remove WMS layer from MapLibre
     * @param {string} id - Layer identifier
     */
    removeWMSLayer(id) {
      const layer = this.wmsLayers.get(id);
      if (!layer) {
        console.warn('[AoTMapBridge] WMS layer ' + id + ' not found');
        return;
      }

      try {
        if (this.maplibreMap.getLayer(layer.layerId)) {
          this.maplibreMap.removeLayer(layer.layerId);
        }
        if (this.maplibreMap.getSource(layer.sourceId)) {
          this.maplibreMap.removeSource(layer.sourceId);
        }
        this.wmsLayers.delete(id);
        console.log('[AoTMapBridge] WMS layer removed: ' + id);
      } catch (e) {
        console.error('[AoTMapBridge] Error removing WMS layer ' + id + ':', e);
      }
    }

    /**
     * Set WMS layer visibility
     * @param {string} id - Layer identifier
     * @param {boolean} visible - Show/hide layer
     */
    setWMSLayerVisibility(id, visible) {
      const layer = this.wmsLayers.get(id);
      if (!layer) {
        console.warn('[AoTMapBridge] WMS layer ' + id + ' not found');
        return;
      }

      try {
        this.maplibreMap.setLayoutProperty(
          layer.layerId,
          'visibility',
          visible ? 'visible' : 'none'
        );
      } catch (e) {
        console.error('[AoTMapBridge] Error setting WMS visibility for ' + id + ':', e);
      }
    }

    /**
     * Set WMS layer opacity
     * @param {string} id - Layer identifier
     * @param {number} opacity - Opacity value (0-1)
     */
    setWMSLayerOpacity(id, opacity) {
      const layer = this.wmsLayers.get(id);
      if (!layer) {
        console.warn('[AoTMapBridge] WMS layer ' + id + ' not found');
        return;
      }

      try {
        this.maplibreMap.setPaintProperty(layer.layerId, 'raster-opacity', opacity);
      } catch (e) {
        console.error('[AoTMapBridge] Error setting WMS opacity for ' + id + ':', e);
      }
    }

    // ============================================
    // Leaflet.Draw Compatible Layer API
    // ============================================

    /**
     * Add a tile layer (Leaflet.Draw compatible)
     * @param {string} id - Layer identifier
     * @param {Object} options - Tile layer options
     * @param {string} options.url - Tile URL template
     * @param {string} [options.attribution] - Attribution text
     * @param {number} [options.maxZoom] - Maximum zoom level
     * @param {Array<string>} [options.subdomains] - Subdomains
     * @param {boolean} [options.isBaseLayer=true] - Set as base layer
     * @returns {string} Layer ID
     */
    addTileLayer(id, options, isBaseLayer = true) {
      if (isBaseLayer) {
        return this._addBaseTileLayer(id, options);
      } else {
        return this._addOverlayTileLayer(id, options);
      }
    }

    /**
     * Add base tile layer to MapLibre
     * @private
     */
    _addBaseTileLayer(id, options) {
      // If this is the first base layer, set it up
      if (!this.maplibreMap.getSource(this._baseLayerSourceId)) {
        this._initBaseLayerSource(options);
        this.tileLayers.set(id, { options: options, isBase: true });
        this._activeBaseLayer = id;
      } else {
        // Store for later switching
        this.tileLayers.set(id, { options: options, isBase: true });
      }

      console.log('[AoTMapBridge] Base tile layer added: ' + id);
      return id;
    }

    /**
     * Initialize base layer source
     * @private
     */
    _initBaseLayerSource(options) {
      const url = this._processTileUrl(options.url, options.subdomains);

      if (!this._isValidTileUrl(url)) {
        console.warn('[AoTMapBridge] Skipping base layer — invalid/empty tile URL:',
          JSON.stringify(options.url));
        return;
      }

      try {
        this.maplibreMap.addSource(this._baseLayerSourceId, {
          type: 'raster',
          tiles: [url],
          tileSize: 256,
          attribution: options.attribution || '',
          maxzoom: options.maxZoom || 19
        });

        this.maplibreMap.addLayer({
          id: this._baseLayerLayerId,
          type: 'raster',
          source: this._baseLayerSourceId,
          paint: {
            'raster-opacity': 1
          }
        }, 'waterway-label'); // Insert before labels
      } catch (e) {
        console.error('[AoTMapBridge] Error initializing base layer:', e);
      }
    }

    /**
     * Process tile URL with subdomain replacement
     * @private
     */
    _processTileUrl(url, subdomains) {
      if (subdomains && subdomains.length > 0) {
        const firstSubdomain = subdomains[0];
        return url.replace('{s}', firstSubdomain);
      }
      return url;
    }

    /**
     * Validate a raster tile URL template before handing it to MapLibre.
     *
     * 빈/잘못된 URL 을 tiles:[''] 로 넘기면 MapLibre 워커가 보이는 타일마다
     * 빈 URL 을 요청하고, 빈 URL 은 '현재 페이지'(대시보드 HTML, 1.3MB)로
     * 해소된다 → 타일 수만큼 대시보드 페이지를 재요청해 워커 풀을 포화시키고
     * 모달 등 사용자 상호작용을 수 초간 지연시킨다. XYZ 는 {z}/{x}/{y},
     * WMS 는 {bbox} 플레이스홀더가 반드시 있어야 한다.
     * @private
     */
    _isValidTileUrl(url) {
      if (!url || typeof url !== 'string') return false;
      const u = url.trim();
      if (!u) return false;
      const hasXYZ = u.indexOf('{z}') !== -1 && u.indexOf('{x}') !== -1 &&
                     (u.indexOf('{y}') !== -1 || u.indexOf('{-y}') !== -1);
      const hasBbox = u.toLowerCase().indexOf('{bbox') !== -1;
      return hasXYZ || hasBbox;
    }

    /**
     * Add overlay tile layer
     * @private
     */
    _addOverlayTileLayer(id, options) {
      const sourceId = 'overlay_' + id + '_source';
      const layerId = 'overlay_' + id + '_layer';

      if (this.maplibreMap.getSource(sourceId)) {
        console.warn('[AoTMapBridge] Overlay source ' + sourceId + ' already exists');
        return layerId;
      }

      const url = this._processTileUrl(options.url, options.subdomains);

      if (!this._isValidTileUrl(url)) {
        console.warn('[AoTMapBridge] Skipping overlay layer — invalid/empty tile URL:',
          JSON.stringify(options.url));
        return layerId;
      }

      try {
        this.maplibreMap.addSource(sourceId, {
          type: 'raster',
          tiles: [url],
          tileSize: 256,
          attribution: options.attribution || '',
          maxzoom: options.maxZoom || 19
        });

        this.maplibreMap.addLayer({
          id: layerId,
          type: 'raster',
          source: sourceId,
          paint: {
            'raster-opacity': options.opacity || 0.8
          }
        });

        this.overlayLayers.set(id, {
          sourceId: sourceId,
          layerId: layerId,
          options: options
        });

        console.log('[AoTMapBridge] Overlay tile layer added: ' + id);
        return layerId;
      } catch (e) {
        console.error('[AoTMapBridge] Error adding overlay layer ' + id + ':', e);
        return null;
      }
    }

    /**
     * Switch base layer (Leaflet.Draw compatible API)
     * @param {string} id - Layer identifier to switch to
     * @returns {boolean} Success status
     */
    switchBaseLayer(id) {
      const layer = this.tileLayers.get(id);
      if (!layer) {
        console.warn('[AoTMapBridge] Base layer ' + id + ' not found');
        return false;
      }

      if (!layer.isBase) {
        console.warn('[AoTMapBridge] Layer ' + id + ' is not a base layer');
        return false;
      }

      if (id === this._activeBaseLayer) {
        console.log('[AoTMapBridge] Layer ' + id + ' is already active');
        return true;
      }

      try {
        // Remove old layer if it exists in style
        if (this.maplibreMap.getLayer(this._baseLayerLayerId)) {
          this.maplibreMap.removeLayer(this._baseLayerLayerId);
        }

        // Remove old source
        if (this.maplibreMap.getSource(this._baseLayerSourceId)) {
          this.maplibreMap.removeSource(this._baseLayerSourceId);
        }

        // Reinitialize with new options
        this._initBaseLayerSource(layer.options);
        this._activeBaseLayer = id;

        console.log('[AoTMapBridge] Switched to base layer: ' + id);
        return true;
      } catch (e) {
        console.error('[AoTMapBridge] Error switching base layer:', e);
        return false;
      }
    }

    /**
     * Get active base layer ID
     * @returns {string|null}
     */
    getActiveBaseLayer() {
      return this._activeBaseLayer;
    }

    /**
     * Remove tile layer
     * @param {string} id - Layer identifier
     * @returns {boolean} Success status
     */
    removeTileLayer(id) {
      const layer = this.tileLayers.get(id);
      if (!layer) {
        console.warn('[AoTMapBridge] Tile layer ' + id + ' not found');
        return false;
      }

      if (layer.isBase) {
        console.warn('[AoTMapBridge] Cannot remove base layer directly. Use switchBaseLayer instead.');
        return false;
      }

      const overlay = this.overlayLayers.get(id);
      if (overlay) {
        try {
          if (this.maplibreMap.getLayer(overlay.layerId)) {
            this.maplibreMap.removeLayer(overlay.layerId);
          }
          if (this.maplibreMap.getSource(overlay.sourceId)) {
            this.maplibreMap.removeSource(overlay.sourceId);
          }
          this.overlayLayers.delete(id);
          this.tileLayers.delete(id);
          console.log('[AoTMapBridge] Tile layer removed: ' + id);
          return true;
        } catch (e) {
          console.error('[AoTMapBridge] Error removing tile layer:', e);
          return false;
        }
      }

      this.tileLayers.delete(id);
      return true;
    }

    /**
     * Set overlay layer visibility (Leaflet.Draw compatible)
     * @param {string} id - Layer identifier
     * @param {boolean} visible - Show/hide layer
     */
    setOverlayVisibility(id, visible) {
      const overlay = this.overlayLayers.get(id);
      if (!overlay) {
        console.warn('[AoTMapBridge] Overlay ' + id + ' not found');
        return;
      }

      try {
        this.maplibreMap.setLayoutProperty(
          overlay.layerId,
          'visibility',
          visible ? 'visible' : 'none'
        );
        console.log('[AoTMapBridge] Overlay ' + id + ' visibility:', visible);
      } catch (e) {
        console.error('[AoTMapBridge] Error setting overlay visibility:', e);
      }
    }

    /**
     * Set overlay opacity
     * @param {string} id - Layer identifier
     * @param {number} opacity - Opacity value (0-1)
     */
    setOverlayOpacity(id, opacity) {
      const overlay = this.overlayLayers.get(id);
      if (!overlay) {
        console.warn('[AoTMapBridge] Overlay ' + id + ' not found');
        return;
      }

      try {
        this.maplibreMap.setPaintProperty(overlay.layerId, 'raster-opacity', opacity);
      } catch (e) {
        console.error('[AoTMapBridge] Error setting overlay opacity:', e);
      }
    }

    /**
     * Add image overlay (Leaflet.Draw compatible)
     * @param {string} id - Layer identifier
     * @param {string} url - Image URL
     * @param {Array} bounds - [[south, west], [north, east]]
     * @param {Object} [options={}] - Additional options
     * @returns {string} Layer ID
     */
    addImageOverlay(id, url, bounds, options = {}) {
      const sourceId = 'image_' + id + '_source';
      const layerId = 'image_' + id + '_layer';

      if (this.maplibreMap.getSource(sourceId)) {
        console.warn('[AoTMapBridge] Image source ' + sourceId + ' already exists');
        return layerId;
      }

      try {
        // Add image to map
        this.maplibreMap.addImage(id + '_image', url, { pixelRatio: 1 });

        // Add raster source with image
        this.maplibreMap.addSource(sourceId, {
          type: 'image',
          url: url,
          coordinates: [
            [bounds[0][1], bounds[0][0]], // SW [lng, lat]
            [bounds[1][1], bounds[0][0]], // SE
            [bounds[1][1], bounds[1][0]], // NE
            [bounds[0][1], bounds[1][0]]  // NW
          ]
        });

        // Add layer
        this.maplibreMap.addLayer({
          id: layerId,
          type: 'raster',
          source: sourceId,
          paint: {
            'raster-opacity': options.opacity || 0.8
          }
        });

        this.tileLayers.set(id, {
          sourceId: sourceId,
          layerId: layerId,
          options: { ...options, url: url, bounds: bounds },
          isBase: false,
          isImage: true
        });

        console.log('[AoTMapBridge] Image overlay added: ' + id);
        return layerId;
      } catch (e) {
        console.error('[AoTMapBridge] Error adding image overlay:', e);
        return null;
      }
    }

    // ============================================
    // Leaflet.Draw Event Compatibility
    // ============================================

    /**
     * Fire a custom event (Leaflet.Draw style)
     * @param {string} eventType - Event type
     * @param {Object} data - Event data
     */
    fire(eventType, data) {
      const callbacks = this._eventCallbacks[eventType] || [];
      callbacks.forEach(cb => {
        try {
          cb(data);
        } catch (e) {
          console.error('[AoTMapBridge] Event callback error:', e);
        }
      });
      console.log('[AoTMapBridge] Event fired: ' + eventType);
    }

    /**
     * Register event listener (Leaflet.Draw compatible)
     * @param {string} eventType - Event type
     * @param {Function} callback - Callback function
     */
    on(eventType, callback) {
      if (!this._eventCallbacks[eventType]) {
        this._eventCallbacks[eventType] = [];
      }
      this._eventCallbacks[eventType].push(callback);
    }

    /**
     * Remove event listener
     * @param {string} eventType - Event type
     * @param {Function} callback - Callback to remove
     */
    off(eventType, callback) {
      const callbacks = this._eventCallbacks[eventType] || [];
      const idx = callbacks.indexOf(callback);
      if (idx !== -1) {
        callbacks.splice(idx, 1);
      }
    }

    // ============================================
    // Coordinate Conversion Utilities
    // ============================================

    /**
     * Convert Leaflet LatLngBounds to MapLibre bounds
     * @param {L.LatLngBounds} bounds - Leaflet bounds
     * @returns {Array<Array<number>>} [[sw_lng, sw_lat], [ne_lng, ne_lat]]
     */
    leafletBoundsToMapLibre(bounds) {
      return [
        [bounds.getWest(), bounds.getSouth()],
        [bounds.getEast(), bounds.getNorth()]
      ];
    }

    /**
     * Get current synchronization state
     * @returns {Object} Sync state info
     */
    getSyncState() {
      const leafletCenter = this.leafletMap.getCenter();
      const maplibreCenter = this.maplibreMap.getCenter();
      const leafletZoom = this.leafletMap.getZoom();
      const maplibreZoom = this.maplibreMap.getZoom();

      return {
        leaflet: {
          center: { lat: leafletCenter.lat, lng: leafletCenter.lng },
          zoom: leafletZoom
        },
        maplibre: {
          center: { lat: maplibreCenter.lat, lng: maplibreCenter.lng },
          zoom: maplibreZoom
        },
        isSynced: Math.abs(leafletCenter.lat - maplibreCenter.lat) < 0.0001 &&
                  Math.abs(leafletCenter.lng - maplibreCenter.lng) < 0.0001 &&
                  Math.abs(leafletZoom - maplibreZoom) < 0.1,
        master: this.options.leafletMaster ? 'leaflet' : 'maplibre'
      };
    }

    /**
     * Force synchronization from master to slave
     */
    forceSync() {
      if (this.options.leafletMaster) {
        this._syncLeafletToMapLibre();
      } else {
        this._syncMapLibreToLeaflet();
      }
    }

    /**
     * Destroy the bridge and remove all event listeners
     */
    destroy() {
      // Clear throttle timer
      if (this._throttleTimer) {
        clearTimeout(this._throttleTimer);
      }

      // Remove WMS layers
      this.wmsLayers.forEach(function(layer, id) {
        this.removeWMSLayer(id);
      }.bind(this));

      // Remove overlay tile layers
      this.overlayLayers.forEach(function(overlay, id) {
        try {
          if (this.maplibreMap.getLayer(overlay.layerId)) {
            this.maplibreMap.removeLayer(overlay.layerId);
          }
          if (this.maplibreMap.getSource(overlay.sourceId)) {
            this.maplibreMap.removeSource(overlay.sourceId);
          }
        } catch (e) {}
      }.bind(this));

      // Remove base layer
      try {
        if (this.maplibreMap.getLayer(this._baseLayerLayerId)) {
          this.maplibreMap.removeLayer(this._baseLayerLayerId);
        }
        if (this.maplibreMap.getSource(this._baseLayerSourceId)) {
          this.maplibreMap.removeSource(this._baseLayerSourceId);
        }
      } catch (e) {}

      // Clear map references
      this.leafletMap = null;
      this.maplibreMap = null;

      // Clear event callbacks
      this._eventCallbacks = {};

      // Remove from global instances
      AoTMapBridge.instances.delete(this.id);

      console.log('[AoTMapBridge] Bridge ' + this.id + ' destroyed');
    }
  }

  /**
   * Create a new bridge instance
   * @param {Object} config - Bridge configuration
   * @returns {BridgeInstance} Bridge instance
   */
  AoTMapBridge.create = function(config) {
    // Validate required parameters
    if (!config.leaflet) {
      throw new Error('[AoTMapBridge] Leaflet map instance is required');
    }
    if (!config.maplibre) {
      throw new Error('[AoTMapBridge] MapLibre map instance is required');
    }

    // Create new bridge instance
    const bridge = new BridgeInstance(config);

    // Store in instances map
    this.instances.set(bridge.id, bridge);

    console.log('[AoTMapBridge] Bridge created: ' + bridge.id);
    return bridge;
  };

  /**
   * Get a bridge instance by ID
   * @param {string} id - Bridge instance ID
   * @returns {BridgeInstance|null}
   */
  AoTMapBridge.get = function(id) {
    return this.instances.get(id) || null;
  };

  /**
   * Get all active bridge instances
   * @returns {Array<BridgeInstance>}
   */
  AoTMapBridge.getAll = function() {
    return Array.from(this.instances.values());
  };

  /**
   * Destroy all bridge instances
   */
  AoTMapBridge.destroyAll = function() {
    this.instances.forEach(function(bridge) { bridge.destroy(); });
    console.log('[AoTMapBridge] All bridges destroyed');
  };

  /**
   * Convert Leaflet bounds to MapLibre bounds
   * @param {L.LatLngBounds} bounds - Leaflet bounds
   * @returns {Array<Array<number>>} [[sw_lng, sw_lat], [ne_lng, ne_lat]]
   */
  AoTMapBridge.leafletBoundsToMapLibre = function(bounds) {
    return [
      [bounds.getWest(), bounds.getSouth()],
      [bounds.getEast(), bounds.getNorth()]
    ];
  };

  /**
   * Convert MapLibre bounds to Leaflet bounds
   * @param {Array<Array<number>>} bounds - [[sw_lng, sw_lat], [ne_lng, ne_lat]]
   * @returns {L.LatLngBounds} Leaflet bounds
   */
  AoTMapBridge.maplibreBoundsToLeaflet = function(bounds) {
    return L.latLngBounds(
      [bounds[0][1], bounds[0][0]], // SW
      [bounds[1][1], bounds[1][0]]  // NE
    );
  };

  /**
   * Convert Leaflet LatLng to MapLibre coordinate
   * @param {L.LatLng} latlng - Leaflet LatLng
   * @returns {Array<number>} [lng, lat]
   */
  AoTMapBridge.leafletToMapLibre = function(latlng) {
    return [latlng.lng, latlng.lat];
  };

  /**
   * Convert MapLibre coordinate to Leaflet LatLng
   * @param {Array<number>} coords - [lng, lat]
   * @returns {L.LatLng} Leaflet LatLng
   */
  AoTMapBridge.maplibreToLeaflet = function(coords) {
    return L.latLng(coords[1], coords[0]);
  };

  // ================================================================
  // EPSG:5179 (Korea 2000 / Central Belt 2010) Coordinate Transform
  // Enables seamless overlay of Korean national GIS data on MapLibre
  // (EPSG:3857 Web Mercator) base maps.
  //
  // Transformation path: EPSG:5179 → WGS84 (EPSG:4326) → EPSG:3857
  // Uses proj4js when available; falls back to an inline GRS80-based
  // 7-parameter Helmert transformation.
  // ================================================================

  /**
   * EPSG:5179 projection parameters (GRS80 ellipsoid, Korea 2000 / Central Belt).
   * @private
   */
  AoTMapBridge._EPSG_5179 = {
    a: 6378137.0,           // GRS80 semi-major axis (m)
    f: 1 / 298.257222101,  // GRS80 flattening
    // Helmert-7 params (ITRF to GRS80, approximate; fine for display use)
    dx: -0.00328, dy: 0.00379, dz: 0.00226,
    rx: 0.000091, ry: 0.000147, rz: 0.000059,  // arc-seconds
    ds: 0.0000091                              // scale factor (ppm)
  };

  /**
   * Convert EPSG:5179 [x_katec, y_katec] to EPSG:3857 [lng, latMerc].
   *
   * @param {number} x - EPSG:5179 easting (Korea Central Belt X)
   * @param {number} y - EPSG:5179 northing (Korea Central Belt Y)
   * @returns {Array<number>} [lng, lat] in EPSG:3857 (Web Mercator)
   */
  AoTMapBridge.epsg5179To3857 = function(x, y) {
    var wgs84 = AoTMapBridge.epsg5179ToWgs84(x, y);
    if (!wgs84) return null;
    return AoTMapBridge.wgs84To3857(wgs84[0], wgs84[1]);
  };

  /**
   * Convert EPSG:5179 [x_katec, y_katec] to WGS84 [lng, lat].
   *
   * @param {number} x - EPSG:5179 easting
   * @param {number} y - EPSG:5179 northing
   * @returns {Array<number>|null} [lng, lat] in WGS84 (EPSG:4326)
   */
  AoTMapBridge.epsg5179ToWgs84 = function(x, y) {
    try {
      var p = AoTMapBridge._EPSG_5179;
      // Geocentric GRS80 coordinates
      var grc = AoTMapBridge._geocentricFromProjection(x, y, 0, p.a, p.f);
      // Helmert-7 to WGS84 (ITRF)
      var wgs = AoTMapBridge._helmert7(
        grc[0], grc[1], grc[2],
        p.dx, p.dy, p.dz, p.rx, p.ry, p.rz, p.ds
      );
      // Geodetic (lat, lon, h)
      return AoTMapBridge._geodeticFromGeocentric(wgs[0], wgs[1], wgs[2], p.a, p.f);
    } catch (e) {
      console.warn('[AoTMapBridge.epsg5179ToWgs84] Transform error:', e);
      return null;
    }
  };

  /**
   * Convert WGS84 [lng, lat] to EPSG:5179 [x_katec, y_katec].
   *
   * @param {number} lng - WGS84 longitude
   * @param {number} lat - WGS84 latitude
   * @returns {Array<number>|null} [x, y] in EPSG:5179
   */
  AoTMapBridge.wgs84ToEpsg5179 = function(lng, lat) {
    try {
      var p = AoTMapBridge._EPSG_5179;
      // Geocentric from WGS84
      var wgs = AoTMapBridge._geocentricFromGeodetic(lng, lat, 0, p.a, p.f);
      // Inverse Helmert-7 (sign flip on rotation + scale)
      var grc = AoTMapBridge._helmert7(
        wgs[0], wgs[1], wgs[2],
        -p.dx, -p.dy, -p.dz, -p.rx, -p.ry, -p.rz, -p.ds
      );
      // GRS80 projected → EPSG:5179 (Transverse Mercator, Central Meridian 127°E)
      return AoTMapBridge._tmInverse(grc[0], grc[1], grc[2], p.a, p.f, 127.0, 38.0);
    } catch (e) {
      console.warn('[AoTMapBridge.wgs84ToEpsg5179] Transform error:', e);
      return null;
    }
  };

  /**
   * Convert WGS84 [lng, lat] to EPSG:3857 [lng, latMercator].
   *
   * @param {number} lng - WGS84 longitude
   * @param {number} lat - WGS84 latitude
   * @returns {Array<number>} [lng, latMerc] in EPSG:3857
   */
  AoTMapBridge.wgs84To3857 = function(lng, lat) {
    var latRad = lat * Math.PI / 180;
    return [
      lng * 20037508.342789 / 180,
      Math.log(Math.tan(Math.PI / 4 + latRad / 2)) * 6378137.0
    ];
  };

  /**
   * Convert EPSG:3857 [lng, latMerc] to WGS84 [lng, lat].
   *
   * @param {number} lngMerc - EPSG:3857 easting
   * @param {number} latMerc - EPSG:3857 northing
   * @returns {Array<number>} [lng, lat] in WGS84
   */
  AoTMapBridge.epsg3857ToWgs84 = function(lngMerc, latMerc) {
    return [
      lngMerc / (20037508.342789 / 180),
      (2 * Math.atan(Math.exp(latMerc / 6378137.0)) - Math.PI / 2) * 180 / Math.PI
    ];
  };

  /**
   * Transform an array of coordinates from EPSG:5179 to EPSG:3857.
   *
   * @param {Array<Array<number>>|Array<number>} coords - [x, y] or [[x,y], ...]
   * @returns {Array<Array<number>>|Array<number>|null} Transformed coords
   */
  AoTMapBridge.transformCoords5179To3857 = function(coords) {
    if (typeof coords[0] === 'number') {
      return AoTMapBridge.epsg5179To3857(coords[0], coords[1]);
    }
    if (Array.isArray(coords[0])) {
      return coords.map(function(c) {
        return AoTMapBridge.epsg5179To3857(c[0], c[1]);
      });
    }
    return null;
  };

  /**
   * Transform bounding box from EPSG:5179 to EPSG:3857.
   *
   * @param {Array<number>} bbox5179 - [minX, minY, maxX, maxY] in EPSG:5179
   * @returns {Array<Array<number>>} [[sw_lng, sw_lat], [ne_lng, ne_lat]] in EPSG:3857
   */
  AoTMapBridge.transformBounds5179To3857 = function(bbox5179) {
    var sw = AoTMapBridge.epsg5179To3857(bbox5179[0], bbox5179[1]);
    var ne = AoTMapBridge.epsg5179To3857(bbox5179[2], bbox5179[3]);
    if (!sw || !ne) return null;
    return [sw, ne];
  };

  // ---- Private helpers -------------------------------------------------

  /**
   * Convert projected (TM) coords to geocentric GRS80.
   * @private
   */
  AoTMapBridge._tmInverse = function(x, y, h, a, f, L0, N0) {
    // Transverse Mercator inverse (Redfearn formula simplified)
    var e2 = 2 * f - f * f;
    var e4 = e2 * e2, e6 = e4 * e2;
    var n = f / (1 - f);
    var n2 = n * n, n3 = n2 * n, n4 = n3 * n;
    var L0r = L0 * Math.PI / 180;
    var k0 = 1.0;
    var FE = 200000; // false easting
    var FN = 600000; // false northing (for central belt)
    var xadj = x - FE;
    var yadj = y - FN;
    var M0 = AoTMapBridge._meridianArc(N0, a, f, e2, n, n2, n3, n4, L0r);
    var M = M0 + yadj / k0;
    var sigma = M / (a * (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256));
    var mu = sigma * (1 + 0.75 * n2 + 0.9375 * (n3 + n4));
    var e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
    var phi1 = mu + (1.5 * e1 - 0.84375 * e1 * e1 * e1) * Math.sin(2 * mu)
      + (1.3125 * e1 * e1 - 0.046875 * e1 * e1 * e1 * e1) * Math.sin(4 * mu);
    var sinPhi1 = Math.sin(phi1), cosPhi1 = Math.cos(phi1);
    var t1 = sinPhi1 / cosPhi1;
    var N1 = a / Math.sqrt(1 - e2 * sinPhi1 * sinPhi1);
    var T1 = t1 * t1;
    var C1 = e2 / (1 - e2) * cosPhi1 * cosPhi1;
    var R1 = a * (1 - e2) / Math.pow(1 - e2 * sinPhi1 * sinPhi1, 1.5);
    var D = xadj / (N1 * k0);
    var lat = phi1 - (N1 * t1 / R1) * (D * D / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * n2) * D * D * D * D / 24
      + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * C1 * C1 - 3 * n4) * Math.pow(D, 6) / 720);
    var lon = (D - (1 + 2 * T1 + C1) * D * D * D / 6
      + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * n2 + 24 * T1 * T1) * Math.pow(D, 5) / 120) / cosPhi1 / N1;
    return [(lon + L0r) * 180 / Math.PI, lat * 180 / Math.PI];
  };

  AoTMapBridge._meridianArc = function(N0, a, f, e2, n, n2, n3, n4, L0r) {
    var A0 = 1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256;
    var A2 = 3 / 8 * (e2 + e2 * e2 / 4 + 15 / 128 * e6);
    var A4 = 15 / 256 * (e4 + e2 * e6 / 4 + 7 / 256 * e6 * e2);
    var A6 = 35 / 3072 * e6;
    return a * (A0 * N0 - A2 * Math.sin(2 * N0) + A4 * Math.sin(4 * N0) - A6 * Math.sin(6 * N0));
  };

  AoTMapBridge._geocentricFromProjection = function(x, y, h, a, f) {
    var e2 = 2 * f - f * f;
    var Lr = x * Math.PI / 180;
    var lat = y * Math.PI / 180;
    var sinLat = Math.sin(lat), cosLat = Math.cos(lat);
    var N = a / Math.sqrt(1 - e2 * sinLat * sinLat);
    return [
      (N + h) * cosLat * Math.cos(Lr),
      (N + h) * cosLat * Math.sin(Lr),
      (N * (1 - e2) + h) * sinLat
    ];
  };

  AoTMapBridge._geodeticFromGeocentric = function(X, Y, Z, a, f) {
    var e2 = 2 * f - f * f;
    var p = Math.sqrt(X * X + Y * Y);
    var lon = Math.atan2(Y, X);
    var lat = Math.atan2(Z, p * (1 - e2));
    for (var i = 0; i < 5; i++) {
      var sinLat = Math.sin(lat), N = a / Math.sqrt(1 - e2 * sinLat * sinLat);
      lat = Math.atan2(Z + e2 * N * sinLat, p);
    }
    return [lon * 180 / Math.PI, lat * 180 / Math.PI];
  };

  AoTMapBridge._geocentricFromGeodetic = function(lon, lat, h, a, f) {
    var e2 = 2 * f - f * f;
    var lr = lat * Math.PI / 180, Lr = lon * Math.PI / 180;
    var sinLat = Math.sin(lr), cosLat = Math.cos(lr);
    var N = a / Math.sqrt(1 - e2 * sinLat * sinLat);
    return [
      (N + h) * cosLat * Math.cos(Lr),
      (N + h) * cosLat * Math.sin(Lr),
      (N * (1 - e2) + h) * sinLat
    ];
  };

  AoTMapBridge._helmert7 = function(X, Y, Z, dx, dy, dz, rx, ry, rz, ds) {
    // rx, ry, rz in arc-seconds → radians
    var rxr = rx * Math.PI / 180 / 3600;
    var ryr = ry * Math.PI / 180 / 3600;
    var rzr = rz * Math.PI / 180 / 3600;
    var s = ds * 1e-6 + 1;
    return [
      dx + s * (X + rzr * Y - ryr * Z),
      dy + s * (-rzr * X + Y + rxr * Z),
      dz + s * (ryr * X - rxr * Y + Z)
    ];
  };

  /**
   * Get default tile layer configurations
   * @returns {Object} Default tile layer templates
   */
  AoTMapBridge.getDefaultTileLayers = function() {
    return Object.assign({}, this.DEFAULT_TILE_LAYERS);
  };

  /**
   * Register a custom tile layer template
   * @param {string} name - Layer name
   * @param {Object} config - Layer configuration
   */
  AoTMapBridge.registerTileLayer = function(name, config) {
    this.DEFAULT_TILE_LAYERS[name] = config;
    console.log('[AoTMapBridge] Registered tile layer: ' + name);
  };

  // ============================================================
  // AoTRasterBridge — single MapLibre raster overlay bridge
  // Mirrors src/layers/raster-bridge.js factory signature.
  // Usage: AoTRasterBridge.create(maplibreMapInstance)
  // ============================================================
  global.AoTRasterBridge = {
    create: function(maplibreMap) {
      // AoTRasterBridge manages raster overlays on a single MapLibre map.
      // Internally we create a minimal Leaflet map in the same container
      // so BridgeInstance's addRasterLayer/addWMSLayer work unchanged.
      if (!maplibreMap || typeof L === 'undefined') {
        console.error('[AoTRasterBridge] maplibre-gl and Leaflet (L) are required');
        return null;
      }
      var container = maplibreMap.getContainer();
      if (!container) {
        console.error('[AoTRasterBridge] MapLibre container not found');
        return null;
      }
      var leafletMap = L.map(container, {
        crs: L.CRS.EPSG3857,
        attributionControl: false,
        zoomControl: false,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
        touchZoom: false,
        keyboard: false
      });
      // Sync the Leaflet overlay to the MapLibre view immediately
      function syncView() {
        var center = maplibreMap.getCenter();
        var zoom = maplibreMap.getZoom();
        var bearing = maplibreMap.getBearing();
        var pitch = maplibreMap.getPitch();
        leafletMap.setView([center.lat, center.lng], zoom);
        if (bearing !== 0 || pitch !== 0) {
          var el = leafletMap.getContainer();
          if (el) el.style.transform = 'rotate(' + bearing + 'deg)';
        }
      }
      maplibreMap.on('move', syncView);
      maplibreMap.on('zoom', syncView);
      maplibreMap.on('rotate', syncView);
      syncView();

      var bridge = new BridgeInstance({
        leaflet: leafletMap,
        maplibre: maplibreMap,
        syncZoom: false,
        syncPan: false,
        syncCenter: false,
        leafletMaster: true
      });
      bridge._leafletMap = leafletMap;
      bridge._maplibreMap = maplibreMap;

      // Extend with raster-specific methods (mirrors RasterBridge from src/layers/raster-bridge.js)
      bridge.transformCoord = function(lng, lat) {
        var dL = 0.00011053;
        var dP = 0.00006320;
        var wgsLng = lng - dL;
        var wgsLat = lat - dP;
        var x = wgsLng * 20037508.34 / 180;
        var y = Math.log(Math.tan((90 + wgsLat) * Math.PI / 360)) * 6378137.0;
        return { lng: x, lat: y };
      };

      return bridge;
    }
  };

  // Export to global scope
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = AoTMapBridge;
  } else {
    global.AoTMapBridge = AoTMapBridge;
  }

})(typeof window !== 'undefined' ? window : this);
