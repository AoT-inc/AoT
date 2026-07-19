/**
 * Raster Bridge Layer for AoT
 * Renders Leaflet/raster tile layers on top of MapLibre-GL map.
 * Also provides bidirectional sync between Leaflet and MapLibre maps.
 *
 * @module AoT-RasterBridge / AoTMapBridge
 * @version 1.1.0
 */

(function(global) {
  'use strict';

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
      var self = this;
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
    var self = this;
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
    var self = this;

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
    var self = this;

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
