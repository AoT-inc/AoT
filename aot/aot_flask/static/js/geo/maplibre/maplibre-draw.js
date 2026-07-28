/**
 * maplibre-draw.js
 * MapLibre GL Draw Module for AoT GIS
 * 
 * Implements drawing tools for MapLibre GL JS with Leaflet.Draw API compatibility.
 * Supports: Point, LineString, Polygon, Rectangle, Circle, Edit, Delete modes.
 * 
 * @module AoT-MapLibreDraw
 * @version 2.0.0
 * @requires maplibre-gl
 * @requires @maplibre/maplibre-gl-draw
 */

(function(global) {
  'use strict';

  /**
   * MapLibre Draw Manager
   * Handles geometry drawing on MapLibre maps with Leaflet.Draw compatibility
   */
  class MapLibreDraw {
    /**
     * @param {maplibregl.Map} map - MapLibre map instance
     * @param {Object} options - Configuration options
     */
    constructor(map, options = {}) {
      this.map = map;
      this.draw = null;
      this._fallbackMode = false;
      this._initialized = false;
      this._activeMode = null;
      this._drawnFeatures = [];
      this._markers = [];
      this._eventHandlers = {};
      this._layers = new Map();
      this._isDragging = false;
      this._dragStart = null;
      
      this.options = Object.assign({}, this._getDefaultOptions(), options);
      
      if (options.color) {
        this.options.defaultColor = options.color;
      }
    }

    /**
     * Get default configuration
     * @private
     */
    _getDefaultOptions() {
      return {
        displayControlsDefault: false,
        controls: {
          point: true,
          line_string: true,
          polygon: true,
          trash: true
        },
        defaultColor: '#3bb2d0',
        fillColor: '#3bb2d0',
        fillOpacity: 0.2,
        lineWidth: 2,
        radius: 6,
        polyline: true,
        polygon: true,
        rectangle: true,
        circle: true,
        marker: true,
        trash: true,
        edit: true
      };
    }

    /**
     * Initialize the draw control
     * @param {Object} [initOptions] - Optional init options
     * @returns {Promise<boolean>|boolean}
     */
    init(initOptions) {
      if (this._initialized) {
        console.warn('[MapLibreDraw] Already initialized');
        return true;
      }

      initOptions = initOptions || {};
      var autoLoadDraw = initOptions.autoLoadDraw !== false;

      if (typeof maplibregl === 'undefined') {
        console.error('[MapLibreDraw] MapLibre-GL not loaded. Include maplibre-gl.js first.');
        return false;
      }

      if (typeof MapLibreDrawControl === 'undefined') {
        // Initialize fallback immediately so draw buttons respond instantly.
        // Waiting for async CDN load causes a window where setMode() silently does nothing.
        this._initFallback();
        return true;
      }

      this._initWithDrawControl();
      return true;
    }

    /**
     * Load @maplibre/maplibre-gl-draw from CDN
     * @private
     */
    _loadDrawFromCDN() {
      var self = this;
      return new Promise(function(resolve) {
        if (typeof window.AOT_MAP_LOADER !== 'undefined' && window.AOT_MAP_LOADER.loadMapLibreDraw) {
          window.AOT_MAP_LOADER.loadMapLibreDraw({ version: '1.4.3' })
            .then(function() { resolve(true); })
            .catch(function() { resolve(false); });
          return;
        }

        var version = '1.4.3';
        var cdnBase = 'https://unpkg.com';

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
     * Initialize with MapLibreDrawControl
     * @private
     */
    _initWithDrawControl() {
      try {
        var DrawClass = window.MapLibreDrawControl;
        if (!DrawClass) {
          console.warn('[MapLibreDraw] MapLibreDrawControl not found. Using fallback mode.');
          this._initFallback();
          return;
        }

        this.draw = new DrawClass({
          displayControlsDefault: this.options.displayControlsDefault,
          controls: this.options.controls,
          styles: this._getDrawStyles()
        });

        this.map.addControl(this.draw, 'top-left');
        this._initialized = true;
        this._fallbackMode = false;
        this._setupListeners();

        console.log('[MapLibreDraw] Initialized with @maplibre/maplibre-gl-draw v1.4.3');
      } catch (error) {
        console.error('[MapLibreDraw] Failed to initialize draw control:', error);
        this._initFallback();
      }
    }

    /**
     * Initialize fallback mode
     * @private
     */
    _initFallback() {
      this._fallbackMode = true;
      this._currentDrawType = null;
      this._tempCoords = [];
      this._initialized = true;
      this._bindFallbackEvents();
      // Skip _createFallbackUI — AoT has its own draw buttons injected by aot-geo-ui.js
    }

    /**
     * Get draw styles
     * @private
     */
    _getDrawStyles() {
      var color = this.options.defaultColor;
      var fillColor = this.options.fillColor || color;
      return [
        { id: 'gl-draw-point', type: 'circle', filter: ['all', ['==', '$type', 'Point']],
          paint: { 'circle-radius': this.options.radius || 6, 'circle-color': color, 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 }},
        { id: 'gl-draw-line', type: 'line', filter: ['all', ['==', '$type', 'LineString'], ['!=', 'mode', 'static']],
          paint: { 'line-color': color, 'line-width': this.options.lineWidth || 2, 'line-dasharray': [2, 2] }},
        { id: 'gl-draw-polygon-fill', type: 'fill', filter: ['all', ['==', '$type', 'Polygon'], ['!=', 'mode', 'static']],
          paint: { 'fill-color': fillColor, 'fill-opacity': this.options.fillOpacity || 0.2 }},
        { id: 'gl-draw-polygon-stroke', type: 'line', filter: ['all', ['==', '$type', 'Polygon'], ['!=', 'mode', 'static']],
          paint: { 'line-color': color, 'line-width': this.options.lineWidth || 2 }},
        { id: 'gl-draw-vertex', type: 'circle', filter: ['all', ['==', '$type', 'Point'], ['==', 'meta', 'vertex']],
          paint: { 'circle-radius': 5, 'circle-color': '#fff', 'circle-stroke-color': color, 'circle-stroke-width': 2 }},
        { id: 'gl-draw-midpoint', type: 'circle', filter: ['all', ['==', '$type', 'Point'], ['==', 'meta', 'midpoint']],
          paint: { 'circle-radius': 4, 'circle-color': color }}
      ];
    }

    /**
     * Setup event listeners
     * @private
     */
    _setupListeners() {
      var self = this;
      this.map.on('draw.create', function(e) { self._onDrawCreate(e.features); });
      this.map.on('draw.update', function(e) { self._onDrawUpdate(e.features); });
      this.map.on('draw.delete', function(e) { self._onDrawDelete(e.features); });
      this.map.on('draw.selectionchange', function(e) { self._onSelectionChange(e.features); });
      this.map.on('draw.modechange', function(e) {
        self._activeMode = e.mode;
        self._fire('modechange', { mode: e.mode });
      });
    }

    /**
     * Bind fallback mode events
     * @private
     */
    _bindFallbackEvents() {
      var self = this;

      // Click: add vertices for polygon/polyline, or place marker
      this._clickHandler = function(e) {
        if (!self._currentDrawType) return;
        if (self._isDragging) return; // ignore spurious click after drag
        if (self._ignoreNextClick) { self._ignoreNextClick = false; return; } // dblclick guard
        var coords = [e.lngLat.lng, e.lngLat.lat];
        if (self._currentDrawType === 'marker') {
          self._addPointMarker(coords);
          self._finishDraw('Point', coords);
          self._setMapInteractions(true);
        } else if (self._currentDrawType === 'polygon' || self._currentDrawType === 'polyline') {
          self._tempCoords.push(coords);
          self._updatePolylinePreview(e.lngLat);
        }
      };

      // Mousedown: start drag for rectangle/circle
      this._mousedownHandler = function(e) {
        if (!self._currentDrawType) return;
        if (self._currentDrawType !== 'rectangle' && self._currentDrawType !== 'circle') return;
        e.preventDefault();
        self._dragStart = e.lngLat;
        self._isDragging = true;
      };

      // Mousemove: live preview while dragging or drawing polyline/polygon
      this._mousemoveHandler = function(e) {
        self._lastMouseLngLat = e.lngLat;
        if (self._isDragging && self._dragStart) {
          self._updateDragPreview(e.lngLat);
        } else if ((self._currentDrawType === 'polyline' || self._currentDrawType === 'polygon') && self._tempCoords.length > 0) {
          self._updatePolylinePreview(e.lngLat);
        }
      };

      // Mouseup: finish rectangle/circle
      this._mouseupHandler = function(e) {
        if (!self._isDragging || !self._dragStart) return;
        self._isDragging = false;
        var start = self._dragStart;
        var end = e.lngLat;
        self._dragStart = null;
        self._clearDragPreview();

        if (self._currentDrawType === 'rectangle') {
          var rcoords = self._makeViewportRectCoords(start, end);
          self._finishDraw('Polygon', [rcoords]);
        } else if (self._currentDrawType === 'circle') {
          self._finishCircle(start, end);
        }
        self._setMapInteractions(true);
      };

      // Dblclick: finish polygon/polyline
      // Note: dblclick fires after two click events; suppress the 2nd click to avoid duplicate vertex
      this._dblclickHandler = function(e) {
        if (!self._currentDrawType) return;
        if (self._currentDrawType !== 'polygon' && self._currentDrawType !== 'polyline') return;
        e.preventDefault();
        self._ignoreNextClick = true;
        self._clearPolylinePreview();
        // Browser fires click→click→dblclick; the 2nd click already added a duplicate coord.
        // Pop it if the last two coords are identical.
        var tc = self._tempCoords;
        if (tc.length >= 2) {
          var last = tc[tc.length - 1];
          var prev = tc[tc.length - 2];
          if (last[0] === prev[0] && last[1] === prev[1]) {
            tc.pop();
          }
        }
        if (tc.length >= 2) {
          var type = self._currentDrawType === 'polyline' ? 'LineString' : 'Polygon';
          var coords = type === 'Polygon' ? [tc.concat([tc[0]])] : tc;
          self._finishDraw(type, coords);
          self._setMapInteractions(true);
        }
      };

      // Right-click (contextmenu): finish polygon/polyline drawing.
      // Unlike dblclick this does NOT add a vertex, so no duplicate-coord cleanup is needed.
      this._contextmenuHandler = function(e) {
        if (!self._currentDrawType) return;
        if (self._currentDrawType !== 'polygon' && self._currentDrawType !== 'polyline') return;
        if (e && e.preventDefault) e.preventDefault();
        if (e && e.originalEvent && e.originalEvent.preventDefault) e.originalEvent.preventDefault();
        self._commitPolyDraw();
      };

      // Escape: finish the current polygon/polyline if it has enough vertices,
      // otherwise cancel the in-progress draw entirely.
      // Backspace: remove the last placed vertex (undo last point).
      this._drawKeydownHandler = function(ev) {
        if (!self._currentDrawType) return;

        if (ev.key === 'Backspace' || ev.keyCode === 8) {
          if (self._currentDrawType === 'polygon' || self._currentDrawType === 'polyline') {
            if (self._tempCoords && self._tempCoords.length > 0) {
              self._tempCoords.pop();
              // Refresh preview with current cursor position (use last known mouse pos if available)
              if (self._lastMouseLngLat) {
                self._updatePolylinePreview(self._lastMouseLngLat);
              } else if (self._tempCoords.length === 0) {
                self._clearPolylinePreview();
              }
            }
          }
          return;
        }

        if (ev.key !== 'Escape' && ev.keyCode !== 27) return;
        if (self._currentDrawType === 'polygon' || self._currentDrawType === 'polyline') {
          if (!self._commitPolyDraw()) {
            // Not enough vertices to commit → cancel
            self._clearPolylinePreview();
            self._setMapInteractions(true);
          }
        } else {
          // Cancel any other in-progress draw (rectangle/circle/marker)
          self._clearDragPreview();
          self._clearPolylinePreview();
          self._setMapInteractions(true);
        }
      };

      this.map.on('click',     this._clickHandler);
      this.map.on('mousedown', this._mousedownHandler);
      this.map.on('mousemove', this._mousemoveHandler);
      this.map.on('mouseup',   this._mouseupHandler);
      this.map.on('dblclick',  this._dblclickHandler);
      this.map.on('contextmenu', this._contextmenuHandler);
      document.addEventListener('keydown', this._drawKeydownHandler);
    }

    /** Commit the in-progress polygon/polyline draw.
     *  Returns true if a shape was committed, false if there were too few vertices.
     *  Used by both right-click (contextmenu) and Escape finishers. */
    _commitPolyDraw() {
      if (this._currentDrawType !== 'polygon' && this._currentDrawType !== 'polyline') return false;
      this._clearPolylinePreview();
      var tc = this._tempCoords || [];
      var minPts = this._currentDrawType === 'polygon' ? 3 : 2;
      if (tc.length < minPts) return false;
      var type = this._currentDrawType === 'polyline' ? 'LineString' : 'Polygon';
      var coords = type === 'Polygon' ? [tc.concat([tc[0]])] : tc;
      this._finishDraw(type, coords);
      this._setMapInteractions(true);
      return true;
    }

    /** Enable or disable map pan/drag/rotate interactions */
    _setMapInteractions(enable) {
      if (enable) {
        this.map.dragPan.enable();
        this.map.boxZoom.enable();
        this.map.dragRotate.enable();
        this.map.getCanvas().style.cursor = '';
        this._currentDrawType = null;
        this._isDragging = false;
        this._dragStart = null;
        this._ignoreNextClick = false;
        this._clearPolylinePreview();
        // Notify AoTMapEditor that drawing ended → clears activeShape
        this._fire('modechange', { mode: 'simple_select' });
      } else {
        this.map.dragPan.disable();
        this.map.boxZoom.disable();
        this.map.dragRotate.disable();
      }
    }

    /** Build a rectangle aligned to the current viewport (rotates with map bearing).
     *  Corners are computed in screen space, then unprojected back to lng/lat,
     *  so a rotated map produces a rotated geographic rectangle. */
    _makeViewportRectCoords(startLngLat, endLngLat) {
      var p1 = this.map.project(startLngLat);
      var p2 = this.map.project(endLngLat);
      var corners = [
        { x: p1.x, y: p1.y },
        { x: p2.x, y: p1.y },
        { x: p2.x, y: p2.y },
        { x: p1.x, y: p2.y },
        { x: p1.x, y: p1.y }
      ];
      var self = this;
      return corners.map(function (c) {
        var ll = self.map.unproject([c.x, c.y]);
        return [ll.lng, ll.lat];
      });
    }

    /** Generate a geographically correct circle polygon from center to edge point.
     *  Compensates for Mercator longitude compression so the result is a true circle. */
    _makeCircleCoords(center, edge, steps) {
      steps = steps || 64;
      // Convert lng/lat offset to approximate meters (equirectangular)
      var cosLat = Math.cos(center.lat * Math.PI / 180);
      var metersPerDegLat = 111320;
      var dLng = (edge.lng - center.lng) * cosLat * metersPerDegLat;
      var dLat = (edge.lat - center.lat) * metersPerDegLat;
      var radiusM = Math.sqrt(dLng * dLng + dLat * dLat);

      // Use turf if available (most accurate)
      if (window.turf && window.turf.circle) {
        var fc = window.turf.circle([center.lng, center.lat], radiusM, { steps: steps, units: 'meters' });
        return fc.geometry.coordinates[0];
      }

      // Fallback: manual projection-corrected ring
      var coords = [];
      for (var i = 0; i <= steps; i++) {
        var angle = (i / steps) * 2 * Math.PI;
        coords.push([
          center.lng + (radiusM * Math.cos(angle)) / (cosLat * metersPerDegLat),
          center.lat + (radiusM * Math.sin(angle)) / metersPerDegLat
        ]);
      }
      return coords;
    }

    /** Render live drag preview as a temporary MapLibre source+layers */
    _updateDragPreview(lngLat) {
      var color = this.options.defaultColor;
      var s = this._dragStart;
      var geom;
      if (this._currentDrawType === 'rectangle') {
        geom = { type: 'Polygon', coordinates: [this._makeViewportRectCoords(s, lngLat)] };
      } else if (this._currentDrawType === 'circle') {
        geom = { type: 'Polygon', coordinates: [this._makeCircleCoords(s, lngLat)] };
      }
      if (!geom) return;
      var feature = { type: 'Feature', geometry: geom, properties: {} };
      try {
        if (this.map.getSource('_aot-draw-preview')) {
          this.map.getSource('_aot-draw-preview').setData(feature);
        } else {
          this.map.addSource('_aot-draw-preview', { type: 'geojson', data: feature });
          this.map.addLayer({ id: '_aot-draw-preview-fill', type: 'fill',
            source: '_aot-draw-preview',
            paint: { 'fill-color': color, 'fill-opacity': 0.15 } });
          this.map.addLayer({ id: '_aot-draw-preview-line', type: 'line',
            source: '_aot-draw-preview',
            paint: { 'line-color': color, 'line-width': 2, 'line-dasharray': [3, 2] } });
        }
      } catch(e) {}
    }

    /** Remove the temporary drag preview layers/source */
    _clearDragPreview() {
      try {
        if (this.map.getLayer('_aot-draw-preview-fill')) this.map.removeLayer('_aot-draw-preview-fill');
        if (this.map.getLayer('_aot-draw-preview-line')) this.map.removeLayer('_aot-draw-preview-line');
        if (this.map.getSource('_aot-draw-preview')) this.map.removeSource('_aot-draw-preview');
      } catch(e) {}
    }

    /** Render live polyline/polygon preview during vertex-by-vertex drawing */
    _updatePolylinePreview(cursorLngLat) {
      if (!this._tempCoords || this._tempCoords.length === 0) return;
      var color = this.options.defaultColor || '#3388ff';
      var coords = this._tempCoords.slice();
      // Append current cursor position as the "ghost" next vertex
      if (cursorLngLat) coords = coords.concat([[cursorLngLat.lng, cursorLngLat.lat]]);
      if (coords.length < 2) return;
      var feature = { type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: {} };
      try {
        if (this.map.getSource('_aot-poly-preview')) {
          this.map.getSource('_aot-poly-preview').setData(feature);
        } else {
          this.map.addSource('_aot-poly-preview', { type: 'geojson', data: feature });
          this.map.addLayer({ id: '_aot-poly-preview-line', type: 'line',
            source: '_aot-poly-preview',
            paint: { 'line-color': color, 'line-width': 2, 'line-dasharray': [4, 3] } });
          // Vertex dots
          this.map.addLayer({ id: '_aot-poly-preview-pts', type: 'circle',
            source: '_aot-poly-preview',
            paint: { 'circle-radius': 4, 'circle-color': color, 'circle-stroke-width': 1, 'circle-stroke-color': '#fff' } });
        }
      } catch(e) {}
    }

    /** Remove polyline/polygon preview layers/source */
    _clearPolylinePreview() {
      try {
        if (this.map.getLayer('_aot-poly-preview-pts')) this.map.removeLayer('_aot-poly-preview-pts');
        if (this.map.getLayer('_aot-poly-preview-line')) this.map.removeLayer('_aot-poly-preview-line');
        if (this.map.getSource('_aot-poly-preview')) this.map.removeSource('_aot-poly-preview');
      } catch(e) {}
    }

    /**
     * Create fallback UI
     * @private
     */
    _createFallbackUI() {
      var container = this.map.getContainer();
      var toolbar = document.createElement('div');
      toolbar.className = 'aot-maplibre-draw-toolbar';
      toolbar.innerHTML = 
        '<button class="draw-btn" data-mode="point" title="Add Point"><svg width="18" height="18" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4" fill="currentColor"/></svg></button>' +
        '<button class="draw-btn" data-mode="line" title="Add Line"><svg width="18" height="18" viewBox="0 0 24 24"><path d="M3 21 L21 3" stroke="currentColor" stroke-width="3" fill="none"/></svg></button>' +
        '<button class="draw-btn" data-mode="polygon" title="Add Polygon"><svg width="18" height="18" viewBox="0 0 24 24"><polygon points="12,3 22,18 2,18" fill="none" stroke="currentColor" stroke-width="2"/></svg></button>' +
        '<button class="draw-btn" data-mode="circle" title="Add Circle"><svg width="18" height="18" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/></svg></button>';
      var self = this;
      toolbar.querySelectorAll('.draw-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
          self.setMode(e.currentTarget.dataset.mode);
        });
      });
      container.parentElement.appendChild(toolbar);
      this._toolbar = toolbar;
    }

    /**
     * Add point marker
     * @private
     */
    _addPointMarker(coords) {
      var el = document.createElement('div');
      el.className = 'aot-draw-point-marker';
      el.style.cssText = 'width:12px;height:12px;background:' + this.options.defaultColor + ';border-radius:50%;border:2px solid white;cursor:pointer;';
      var marker = new maplibregl.Marker({ element: el }).setLngLat(coords).addTo(this.map);
      this._markers.push(marker);
    }

    /**
     * Finish drawing
     * @private
     */
    _finishDraw(type, coords) {
      var feature = {
        type: 'Feature',
        geometry: { type: type, coordinates: coords },
        properties: { id: 'draw-' + Date.now(), drawType: this._currentDrawType }
      };
      this._drawnFeatures.push(feature);
      this._currentDrawType = null;
      this._tempCoords = [];
      this._onDrawCreate([feature]);
    }

    /** Finish circle drawing: store as Point + radius (compact), not a polygon */
    _finishCircle(center, edge) {
      var cosLat = Math.cos(center.lat * Math.PI / 180);
      var metersPerDegLat = 111320;
      var dLng = (edge.lng - center.lng) * cosLat * metersPerDegLat;
      var dLat = (edge.lat - center.lat) * metersPerDegLat;
      var radiusM = Math.sqrt(dLng * dLng + dLat * dLat);
      if (radiusM < 0.1) return; // ignore accidental clicks

      var feature = {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [center.lng, center.lat] },
        properties: {
          id: 'draw-' + Date.now(),
          drawType: 'circle',
          is_circle: true,
          radius: radiusM
        }
      };
      this._drawnFeatures.push(feature);
      this._currentDrawType = null;
      this._tempCoords = [];
      this._onDrawCreate([feature]);
    }

    // ========== Event Handlers ==========

    _onDrawCreate(features) {
      var self = this;
      features.forEach(function(feature) {
        self._drawnFeatures.push(feature);
        self._fire('create', { feature: feature, features: features });
      });
    }

    _onDrawUpdate(features) {
      this._fire('edit', { features: features });
    }

    _onDrawDelete(features) {
      var self = this;
      features.forEach(function(feature) {
        var idx = self._drawnFeatures.findIndex(function(f) { return f.id === feature.id; });
        if (idx !== -1) self._drawnFeatures.splice(idx, 1);
      });
      this._fire('delete', { features: features });
    }

    _onSelectionChange(features) {
      this._fire('selectionchange', { features: features });
    }

    // ========== Public API - Drawing Mode Control ==========

    setMode(mode) {
      this._activeMode = mode;
      if (this._fallbackMode) {
        var _typeMap = {
          'draw_polygon':     'polygon',
          'draw_line_string': 'polyline',
          'draw_point':       'marker',
          'simple_select':    null,
          'direct_select':    null
        };
        var drawType = (mode in _typeMap) ? _typeMap[mode] : mode;
        this._currentDrawType = drawType;
        this._tempCoords = [];
        this._isDragging = false;
        this._dragStart = null;
        this._ignoreNextClick = false;
        this._clearDragPreview();
        this._clearPolylinePreview();
        if (drawType) {
          this._setMapInteractions(false);
          this.map.getCanvas().style.cursor = 'crosshair';
        } else {
          this._setMapInteractions(true);
        }
      } else if (this.draw) {
        this.draw.changeMode(mode);
      }
      this._fire('modechange', { mode: mode });
    }

    enablePolyline()  { this.setMode('draw_line_string'); }
    enablePolygon()   { this.setMode('draw_polygon'); }
    enableRectangle() { this._fallbackMode ? this.setMode('rectangle') : this.setMode('draw_polygon'); }
    enableCircle()    { this._fallbackMode ? this.setMode('circle')    : this.setMode('draw_polygon'); }
    enableMarker()    { this.setMode('draw_point'); }
    enablePoint()     { this.enableMarker(); }

    enableEdit() {
      this._disableDeleteFallback();
      if (!this._fallbackMode && this.draw) {
        var features = this.draw.getAll();
        if (features.features.length > 0) {
          this.draw.changeMode('direct_select', { featureId: features.features[0].id });
        } else {
          this.draw.changeMode('simple_select');
        }
      }
      this._startEditFallback(); // Always register fallback edit for AoTGeoLayer shapes
      this._activeMode = 'edit';
      // Workflow "select then edit": if a shape was already selected on the map before
      // the user pressed the Edit tool, bridge it straight into vertex-editing instead
      // of forcing a second click.
      try {
        var _design = window.geoDesign;
        var _active = _design && _design.activeLayer;
        if (_active && _active._layerId && !this._isCoverageLayer(_active)) {
          this.editSelectLayerDirect(_active);
        }
      } catch (e) {}
    }

    enableDelete() {
      this._disableEditFallback();
      if (!this._fallbackMode && this.draw) {
        this.draw.changeMode('simple_select');
      }
      this._startDeleteFallback(); // Always register fallback delete for AoTGeoLayer shapes
      this._activeMode = 'delete';
    }

    disableEdit() {
      if (this._fallbackMode) this._disableEditFallback();
      else if (this.draw) this.draw.changeMode('simple_select');
      if (this._activeMode === 'edit') this._activeMode = null;
    }

    disableDelete() {
      if (this._fallbackMode) this._disableDeleteFallback();
      else if (this.draw) this.draw.changeMode('simple_select');
      if (this._activeMode === 'delete') this._activeMode = null;
    }

    disableDraw() {
      this._tempCoords = [];
      this._clearDragPreview();
      if (this.draw) this.draw.changeMode('simple_select');
      if (this._fallbackMode) {
        this._setMapInteractions(true);
        this._disableEditFallback();
        this._disableDeleteFallback();
      } else {
        this.map.getCanvas().style.cursor = '';
      }
      this._activeMode = null;
    }

    // ========== Fallback Edit Mode ==========

    _startEditFallback() {
      var self = this;
      this._editState = { selectedLayer: null, selectedLayerId: null, vertexDragging: false, vertexIdx: null, ringIdx: 0, origFeature: null };
      this.map.getCanvas().style.cursor = 'pointer';

      this._editClickHandler = function(e) {
        if (self._editState.vertexDragging) return;
        // Ignore clicks on vertex/midpoint handles (handled by mousedown)
        var hbox = [[e.point.x - 12, e.point.y - 12], [e.point.x + 12, e.point.y + 12]];
        if (self.map.getLayer('_aot-edit-vertices')) {
          var vf = [];
          try { vf = self.map.queryRenderedFeatures(hbox, { layers: ['_aot-edit-vertices'] }); } catch(e0) {}
          if (vf.length > 0) return;
        }
        if (self.map.getLayer('_aot-edit-midpoints')) {
          var mf = [];
          try { mf = self.map.queryRenderedFeatures(hbox, { layers: ['_aot-edit-midpoints'] }); } catch(e0) {}
          if (mf.length > 0) return;
        }
        var ids = self._getFallbackLayerIds();
        if (!ids.length) { self._editDeselect(); return; }
        // Use bbox so clicks near shape edges also register.
        // Thin pipe lines are hard to hit precisely, so use a generous tolerance.
        var bbox = [[e.point.x - 9, e.point.y - 9], [e.point.x + 9, e.point.y + 9]];
        var hits = [];
        try { hits = self.map.queryRenderedFeatures(bbox, { layers: ids }); } catch(e1) {}
        var layer = hits.length ? self._getLayerByHit(hits[0]) : null;
        // Fallback: thin pipe lines often miss the pixel-based query — find the
        // geometrically nearest pipe within a forgiving pixel radius.
        if (!layer) layer = self._findNearestLineLayer(e.point, 12);
        if (!layer) { self._editDeselect(); return; }
        if (self._editState.selectedLayer === layer) return;
        self.editSelectLayerDirect(layer);
      };

      this._editVtxMousedownHandler = function(e) {
        if (!self.map.getLayer('_aot-edit-vertices')) return;
        var vbox = [[e.point.x - 12, e.point.y - 12], [e.point.x + 12, e.point.y + 12]];
        // Check regular vertex handles first
        var vf = self.map.queryRenderedFeatures(vbox, { layers: ['_aot-edit-vertices'] });
        if (vf.length) {
          var p = vf[0].properties;
          self._editState.vertexDragging = true;
          self._editState.vertexIdx = p.vtxIdx;
          self._editState.ringIdx = p.ringIdx || 0;
          self._editState.polyIdx = p.polyIdx || 0;
          self.map.dragPan.disable();
          self.map.dragRotate.disable();
          e.preventDefault();
          return;
        }
        // Check midpoint handles — insert new vertex then drag it
        if (!self.map.getLayer('_aot-edit-midpoints')) return;
        var mf = self.map.queryRenderedFeatures(vbox, { layers: ['_aot-edit-midpoints'] });
        if (!mf.length) return;
        var mp = mf[0].properties;
        var layer = self._editState.selectedLayer;
        if (!layer || !layer.feature || !layer.feature.geometry) return;
        var geom = layer.feature.geometry;
        var segStart = mp.segStart;
        var ridx = mp.ringIdx || 0;
        var pidx = mp.polyIdx || 0;
        var insertIdx = segStart + 1;
        var midCoord = [mp.midLng, mp.midLat];
        if (geom.type === 'Polygon') {
          geom.coordinates[ridx].splice(insertIdx, 0, midCoord.slice());
        } else if (geom.type === 'MultiPolygon') {
          geom.coordinates[pidx][ridx].splice(insertIdx, 0, midCoord.slice());
        } else if (geom.type === 'LineString') {
          geom.coordinates.splice(insertIdx, 0, midCoord.slice());
        } else {
          return;
        }
        self._editState.vertexDragging = true;
        self._editState.vertexIdx = insertIdx;
        self._editState.ringIdx = ridx;
        self._editState.polyIdx = pidx;
        self.map.dragPan.disable();
        self.map.dragRotate.disable();
        e.preventDefault();
      };

      this._editVtxMousemoveHandler = function(e) {
        if (!self._editState.vertexDragging) return;
        var layer = self._editState.selectedLayer;
        if (!layer || !layer.feature || !layer.feature.geometry) return;
        var geom = layer.feature.geometry;
        var idx = self._editState.vertexIdx;
        var ridx = self._editState.ringIdx;
        var pidx = self._editState.polyIdx || 0;
        var nc = [e.lngLat.lng, e.lngLat.lat];
        if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
          var ring = geom.type === 'MultiPolygon' ? geom.coordinates[pidx][ridx] : geom.coordinates[ridx];
          ring[idx] = nc;
          // Keep ring closed
          if (idx === 0) ring[ring.length - 1] = nc;
          else if (idx === ring.length - 1) ring[0] = nc;
        } else if (geom.type === 'LineString') {
          geom.coordinates[idx] = nc;
        }
        // Polyline (pipe) renders via shared RenderBucket — update bucket, not per-instance source
        if (layer._aotType === 'Polyline' && layer._getBucketCategory) {
          try {
            var category = layer._getBucketCategory();
            var bucket = window.RenderBucket && window.RenderBucket.get(layer._map, category);
            if (bucket) bucket.upsert(layer._layerId, layer._toBucketGeoJSON ? layer._toBucketGeoJSON() : layer.feature);
          } catch(be) {}
          // Also update the dedicated outline source so the selection highlight follows the vertex drag
          try {
            if (self.map.getSource('_aot-edit-select-outline-src')) self.map.getSource('_aot-edit-select-outline-src').setData(layer.feature);
          } catch(oe) {}
        } else {
          var srcId = 'aot-source-' + layer._layerId;
          if (self.map.getSource(srcId)) self.map.getSource(srcId).setData(layer.feature);
        }
        self._renderEditVertices(layer);
      };

      this._editVtxMouseupHandler = function() {
        if (!self._editState.vertexDragging) return;
        self._editState.vertexDragging = false;
        self._editState.vertexIdx = null;
        self.map.dragPan.enable();
        self.map.dragRotate.enable();
        var layer = self._editState.selectedLayer;
        if (layer && layer.feature) {
          // Mark the edited feature dirty for backend persistence (delta save)
          var design = window.geoDesign;
          var props = layer.feature.properties || {};
          var nid = props.node_id || props.db_id || layer.feature.id;
          if (design && design.dirtyNodeIds && nid) {
            design.dirtyNodeIds.add(nid);
          } else if (!nid) {
            console.warn('[MapLibreDraw] Edited feature has no node_id/db_id/id — cannot persist', layer.feature);
          }
          self._onDrawUpdate([layer.feature]);
          // Trigger save via aot:editor:edited — the design-v3.js listener calls saveDesign()
          // which runs a delta upsert using dirtyNodeIds. This is the correct persistence path
          // for fallback edit mode (MapLibre native draw doesn't fire draw:editvertex for our shapes).
          try {
            window.dispatchEvent(new CustomEvent('aot:editor:edited', {
              detail: { features: [layer.feature] }
            }));
          } catch(e) {}
        }
      };

      this.map.on('click',     this._editClickHandler);
      this.map.on('mousedown', this._editVtxMousedownHandler);
      this.map.on('mousemove', this._editVtxMousemoveHandler);
      this.map.on('mouseup',   this._editVtxMouseupHandler);

      // Layer-specific click handlers for direct hit (bypasses queryRenderedFeatures)
      this._editLayerHandlers = new Map();
      var ids = this._getFallbackLayerIds();
      ids.forEach(function(mlId) {
        var handler = function(ev) {
          var layer = (mlId.indexOf('aot-bucket-') === 0 && ev && ev.features && ev.features[0])
            ? self._getLayerByHit(ev.features[0])
            : self._getLayerByMlId(mlId);
          if (!layer) return;
          self.editSelectLayerDirect(layer);
          if (ev && ev.preventDefault) ev.preventDefault();
        };
        try { self.map.on('click', mlId, handler); } catch(e) {}
        self._editLayerHandlers.set(mlId, handler);
      });
    }

    _disableEditFallback() {
      this._editDeselect();
      if (this._editClickHandler)        { this.map.off('click',     this._editClickHandler);        this._editClickHandler = null; }
      if (this._editVtxMousedownHandler) { this.map.off('mousedown', this._editVtxMousedownHandler); this._editVtxMousedownHandler = null; }
      if (this._editVtxMousemoveHandler) { this.map.off('mousemove', this._editVtxMousemoveHandler); this._editVtxMousemoveHandler = null; }
      if (this._editVtxMouseupHandler)   { this.map.off('mouseup',   this._editVtxMouseupHandler);   this._editVtxMouseupHandler = null; }
      if (this._editLayerHandlers) {
        var self2 = this;
        this._editLayerHandlers.forEach(function(handler, mlId) {
          try { self2.map.off('click', mlId, handler); } catch(e) {}
        });
        this._editLayerHandlers.clear();
        this._editLayerHandlers = null;
      }
      this.map.dragPan.enable();
      this.map.getCanvas().style.cursor = '';
    }

    _editSelectLayer(mlLayerId) {
      this._editDeselect();
      var layer = this._getLayerByMlId(mlLayerId);
      if (!layer) return;
      if (this._isCoverageLayer(layer)) return;
      this._editState.selectedLayer = layer;
      this._editState.selectedLayerId = mlLayerId;
      this._editState.origFeature = JSON.stringify(layer.feature);
      var srcId = 'aot-source-' + mlLayerId;
      try {
        if (this.map.getLayer('_aot-edit-select-outline')) this.map.removeLayer('_aot-edit-select-outline');
        this.map.addLayer({ id: '_aot-edit-select-outline', type: 'line', source: srcId,
          paint: { 'line-color': '#ff9900', 'line-width': 3, 'line-dasharray': [4, 2] } });
      } catch(e) {}
      this._renderEditVertices(layer);
    }

    _editDeselect() {
      this._clearEditVertices();
      try { if (this.map.getLayer('_aot-edit-select-outline')) this.map.removeLayer('_aot-edit-select-outline'); } catch(e) {}
      try { if (this.map.getSource('_aot-edit-select-outline-src')) this.map.removeSource('_aot-edit-select-outline-src'); } catch(e) {}
      if (this._editState) {
        this._editState.selectedLayer = null;
        this._editState.selectedLayerId = null;
        this._editState.origFeature = null;
      }
      if (this._activeMode === 'edit') this.map.getCanvas().style.cursor = 'pointer';
    }

    _ensureVertexIcon() {
      if (this.map.hasImage('_aot-vertex-square')) return;
      var size = 14;
      var data = new Uint8Array(size * size * 4);
      for (var y = 0; y < size; y++) {
        for (var x = 0; x < size; x++) {
          var i = (y * size + x) * 4;
          var isBorder = (x <= 1 || x >= size - 2 || y <= 1 || y >= size - 2);
          if (isBorder) {
            // orange border #ff9900
            data[i] = 255; data[i+1] = 153; data[i+2] = 0; data[i+3] = 255;
          } else {
            // white fill
            data[i] = 255; data[i+1] = 255; data[i+2] = 255; data[i+3] = 255;
          }
        }
      }
      try { this.map.addImage('_aot-vertex-square', { width: size, height: size, data: data }); } catch(e) {}
    }

    _renderEditVertices(layer) {
      var geom = layer.feature && layer.feature.geometry;
      if (!geom) return;
      var vertices = [];
      var midpoints = [];
      var addVtx = function(coord, vtxIdx, ringIdx, polyIdx) {
        vertices.push({ type: 'Feature', geometry: { type: 'Point', coordinates: coord },
          properties: { vtxIdx: vtxIdx, ringIdx: ringIdx, polyIdx: polyIdx || 0 } });
      };
      var addMid = function(c1, c2, segStart, ringIdx, polyIdx) {
        var mid = [(c1[0] + c2[0]) / 2, (c1[1] + c2[1]) / 2];
        midpoints.push({ type: 'Feature', geometry: { type: 'Point', coordinates: mid },
          properties: { isMidpoint: true, segStart: segStart, ringIdx: ringIdx, polyIdx: polyIdx || 0, midLng: mid[0], midLat: mid[1] } });
      };
      if (geom.type === 'Polygon') {
        geom.coordinates.forEach(function(ring, ri) {
          for (var i = 0; i < ring.length - 1; i++) {
            addVtx(ring[i], i, ri, 0);
            addMid(ring[i], ring[i + 1], i, ri, 0);
          }
        });
      } else if (geom.type === 'MultiPolygon') {
        geom.coordinates.forEach(function(poly, pi) {
          poly.forEach(function(ring, ri) {
            for (var i = 0; i < ring.length - 1; i++) {
              addVtx(ring[i], i, ri, pi);
              addMid(ring[i], ring[i + 1], i, ri, pi);
            }
          });
        });
      } else if (geom.type === 'LineString') {
        geom.coordinates.forEach(function(c, i) {
          addVtx(c, i, 0);
          if (i < geom.coordinates.length - 1) addMid(c, geom.coordinates[i + 1], i, 0);
        });
      } else if (geom.type === 'Point') {
        addVtx(geom.coordinates, 0, 0);
      }
      var fc = { type: 'FeatureCollection', features: vertices };
      var mfc = { type: 'FeatureCollection', features: midpoints };
      // Render endpoint markers as squares (symbol layer)
      this._ensureVertexIcon();
      try {
        if (this.map.getSource('_aot-edit-vertices-src')) {
          this.map.getSource('_aot-edit-vertices-src').setData(fc);
        } else {
          this.map.addSource('_aot-edit-vertices-src', { type: 'geojson', data: fc });
          this.map.addLayer({ id: '_aot-edit-vertices', type: 'symbol', source: '_aot-edit-vertices-src',
            layout: { 'icon-image': '_aot-vertex-square', 'icon-size': 1, 'icon-allow-overlap': true, 'icon-ignore-placement': true } });
        }
      } catch(e) {}
      // Render midpoint markers as circles
      if (midpoints.length > 0) {
        try {
          if (this.map.getSource('_aot-edit-midpoints-src')) {
            this.map.getSource('_aot-edit-midpoints-src').setData(mfc);
          } else {
            this.map.addSource('_aot-edit-midpoints-src', { type: 'geojson', data: mfc });
            this.map.addLayer({ id: '_aot-edit-midpoints', type: 'circle', source: '_aot-edit-midpoints-src',
              paint: { 'circle-radius': 5, 'circle-color': '#ffffff', 'circle-stroke-color': '#ff9900', 'circle-stroke-width': 2 } });
          }
        } catch(e) {}
      } else {
        // Clear midpoints if no segments (e.g. Point type)
        try {
          if (this.map.getLayer('_aot-edit-midpoints')) this.map.removeLayer('_aot-edit-midpoints');
          if (this.map.getSource('_aot-edit-midpoints-src')) this.map.removeSource('_aot-edit-midpoints-src');
        } catch(e) {}
      }
    }

    _clearEditVertices() {
      try {
        if (this.map.getLayer('_aot-edit-vertices'))    this.map.removeLayer('_aot-edit-vertices');
        if (this.map.getSource('_aot-edit-vertices-src')) this.map.removeSource('_aot-edit-vertices-src');
        if (this.map.getLayer('_aot-edit-midpoints'))   this.map.removeLayer('_aot-edit-midpoints');
        if (this.map.getSource('_aot-edit-midpoints-src')) this.map.removeSource('_aot-edit-midpoints-src');
      } catch(e) {}
    }

    // ========== Fallback Delete Mode ==========

    _startDeleteFallback() {
      var self = this;
      this.map.getCanvas().style.cursor = 'pointer';
      this._deleteClickHandler = function(e) {
        // Delete only the TOPMOST shape under the cursor, one per click (see _deleteAtPoint).
        self._deleteAtPoint(e.point, e.originalEvent, null);
      };
      this.map.on('click', this._deleteClickHandler);

      // Layer-specific click handlers for direct hit (bypasses queryRenderedFeatures)
      this._deleteLayerHandlers = new Map();
      var ids = this._getFallbackLayerIds();
      ids.forEach(function(mlId) {
        var handler = function(ev) {
          // Direct-hit backup for the map-level handler. Routes through the same
          // single-shot resolver so overlapping shapes delete one (topmost) at a time.
          var fallback = (mlId.indexOf('aot-bucket-') === 0 && ev && ev.features && ev.features[0])
            ? self._getLayerByHit(ev.features[0])
            : self._getLayerByMlId(mlId);
          self._deleteAtPoint(ev.point, ev && ev.originalEvent, fallback);
          if (ev && ev.preventDefault) ev.preventDefault();
        };
        try { self.map.on('click', mlId, handler); } catch(e) {}
        self._deleteLayerHandlers.set(mlId, handler);
      });

      // DOM click handlers for label_aux markers (HTML elements, not GL layers)
      this._deleteLabelHandlers = new Map();
      var _addLabelHandlers = function(group) {
        if (!group || !group.eachLayer) return;
        group.eachLayer(function(l) {
          if (!l.feature || l.feature.properties.aot_type !== 'label_aux') return;
          var el = l._markerEl || (l._mlDomMarker && l._mlDomMarker.getElement && l._mlDomMarker.getElement());
          if (!el || self._deleteLabelHandlers.has(l._layerId)) return;
          var labelHandler = function(ev) {
            ev.stopPropagation();
            ev.preventDefault();
            self.deleteLayerDirect(l);
          };
          el.style.cursor = 'pointer';
          el.addEventListener('click', labelHandler);
          self._deleteLabelHandlers.set(l._layerId, { el: el, handler: labelHandler, origCursor: el.style.cursor });
        });
      };
      var _design = window.geoDesign;
      _addLabelHandlers(_design && _design.layerStorage && _design.layerStorage['label_aux']);
      _addLabelHandlers(window.AoTMapEditor && window.AoTMapEditor.featureGroup);
    }

    // Single resolver for a delete-mode click. Overlapping shapes each fire their own
    // GL click handler; a shared per-click token (the DOM event) lets only the first
    // act, and we resolve the visually TOPMOST shape (queryRenderedFeatures is z-ordered)
    // so lower shapes survive and are removed one-by-one on subsequent clicks.
    _deleteAtPoint(point, oe, fallback) {
      if (oe && this._deleteClickToken === oe) return; // this physical click already handled
      var layer = this._resolveTopmostDeleteLayer(point) || fallback || this._findNearestLineLayer(point, 12);
      if (!layer) return;
      if (oe) this._deleteClickToken = oe;
      this._deleteLayerWithBookkeeping(layer);
    }

    // Topmost shape under the cursor via z-ordered pixel query. ±9px tolerance so thin
    // pipe lines and shape edges register reliably.
    _resolveTopmostDeleteLayer(point) {
      var ids = this._getFallbackLayerIds();
      if (!ids.length) return null;
      var bbox = [[point.x - 9, point.y - 9], [point.x + 9, point.y + 9]];
      var hits = [];
      try { hits = this.map.queryRenderedFeatures(bbox, { layers: ids }); } catch(e) {}
      return hits.length ? this._getLayerByHit(hits[0]) : null;
    }

    // Delete one layer with full bookkeeping: undo buffer, deletedNodeIds, cascade to
    // linked labels and sprinkler coverage/head. (Extracted from the per-layer handler
    // so both the map-level and layer-level delete paths share identical behavior.)
    _deleteLayerWithBookkeeping(layer) {
      var self = this;
      if (!layer) return;
      // Track for backend persistence
      var props = layer.feature && layer.feature.properties;
      var nid = props && (props.node_id || props.db_id);
      var aotType = props && props.aot_type;
      var design = window.geoDesign;
      // Buffer this deletion so cancelActions() can restore the layer
      var ed = window.AoTMapEditor;
      if (ed && ed.deleteEnabled && ed._pendingDeletes) {
        ed._pendingDeletes.push({ layer: layer, nid: nid });
      }
      if (design) {
        if (nid && design.deletedNodeIds && design.deletedNodeIds.add) design.deletedNodeIds.add(nid);
        if (aotType) {
          design._pendingDeletedTypes = design._pendingDeletedTypes || new Set();
          design._pendingDeletedTypes.add(aotType);
        }
        // Cascade delete: remove linked labels (parent_node_id === nid)
        // Labels may be in layerStorage['label_aux'] OR moved to featureGroup during delete mode
        if (nid && design) {
          var _removeLabel = function(ll, grp) {
            var lnid = ll.feature && ll.feature.properties && ll.feature.properties.node_id;
            if (lnid) design.deletedNodeIds.add(lnid);
            design._pendingDeletedTypes = design._pendingDeletedTypes || new Set();
            design._pendingDeletedTypes.add('label_aux');
            if (ll._mlDomMarker) { try { ll._mlDomMarker.remove(); } catch(e) {} ll._mlDomMarker = null; }
            if (ll._layerId) {
              var lSrcId = 'aot-source-' + ll._layerId;
              try { if (self.map.getLayer(ll._layerId)) self.map.removeLayer(ll._layerId); } catch(e) {}
              try { if (self.map.getSource(lSrcId)) self.map.removeSource(lSrcId); } catch(e) {}
            }
            if (typeof ll.remove === 'function') { try { ll.remove(); } catch(e) {} }
            if (grp && grp.removeLayer) grp.removeLayer(ll);
          };
          var _scanGroupForLabels = function(grp) {
            if (!grp || !grp.eachLayer) return;
            var found = [];
            grp.eachLayer(function(ll) {
              if (ll.feature && ll.feature.properties &&
                  ll.feature.properties.aot_type === 'label_aux' &&
                  ll.feature.properties.parent_node_id === nid) {
                found.push(ll);
              }
            });
            found.forEach(function(ll) { _removeLabel(ll, grp); });
          };
          if (design.layerStorage) _scanGroupForLabels(design.layerStorage['label_aux']);
          _scanGroupForLabels(window.AoTMapEditor && window.AoTMapEditor.featureGroup);
        }
      }
      self.deleteLayerDirect(layer);
      // Cascade (reverse): if a coverage circle was deleted, also mark linked sprinkler head for DB deletion
      // The head is invisible (blocked from loading) but its node_id must be purged from the DB.
      if (props && props.sub_type === 'sprinkler_coverage' && design) {
        var covCoords = layer.feature && layer.feature.geometry && layer.feature.geometry.coordinates;
        var allSources = [window.AoTMapEditor && window.AoTMapEditor.featureGroup].concat(
          design.layerStorage ? Object.values(design.layerStorage) : []
        );
        allSources.forEach(function(grp) {
          if (!grp || !grp.eachLayer) return;
          grp.eachLayer(function(ll) {
            var lp = ll.feature && ll.feature.properties;
            if (!lp || lp.sub_type !== 'sprinkler') return;
            var lc = ll.feature && ll.feature.geometry && ll.feature.geometry.coordinates;
            if (covCoords && lc &&
                Math.abs(lc[0] - covCoords[0]) < 1e-9 &&
                Math.abs(lc[1] - covCoords[1]) < 1e-9) {
              var lnid = lp.node_id || lp.db_id;
              if (lnid && design.deletedNodeIds) design.deletedNodeIds.add(lnid);
            }
          });
        });
      }
      // Cascade: if a sprinkler head was deleted, also remove its coverage circle from the map
      if (props && props.sub_type === 'sprinkler' && design && design.layerStorage) {
        var headCoords = layer.feature && layer.feature.geometry && layer.feature.geometry.coordinates;
        var headParent = props.parent_node_id;
        var equipGroup = design.layerStorage['equipment'];
        if (equipGroup && equipGroup.eachLayer) {
          var coverageToRemove = [];
          equipGroup.eachLayer(function(cl) {
            var cp = cl.feature && cl.feature.properties;
            if (!cp || cp.sub_type !== 'sprinkler_coverage') return;
            if (headParent && cp.parent_node_id !== headParent) return;
            var cc = cl.feature && cl.feature.geometry && cl.feature.geometry.coordinates;
            if (headCoords && cc &&
                Math.abs(cc[0] - headCoords[0]) < 1e-9 &&
                Math.abs(cc[1] - headCoords[1]) < 1e-9) {
              coverageToRemove.push(cl);
            }
          });
          coverageToRemove.forEach(function(cl) {
            var clId = cl._layerId;
            var clSrcId = 'aot-source-' + clId;
            try { if (self.map.getLayer(clId)) self.map.removeLayer(clId); } catch(e) {}
            try { if (self.map.getSource(clSrcId)) self.map.removeSource(clSrcId); } catch(e) {}
            var cnid = cl.feature && cl.feature.properties && cl.feature.properties.node_id;
            if (cnid && design.deletedNodeIds) design.deletedNodeIds.add(cnid);
            equipGroup.removeLayer(cl);
          });
        }
      }
    }

    _disableDeleteFallback() {
      if (this._deleteClickHandler) {
        this.map.off('click', this._deleteClickHandler);
        this._deleteClickHandler = null;
      }
      if (this._deleteLayerHandlers) {
        var self2 = this;
        this._deleteLayerHandlers.forEach(function(handler, mlId) {
          try { self2.map.off('click', mlId, handler); } catch(e) {}
        });
        this._deleteLayerHandlers.clear();
        this._deleteLayerHandlers = null;
      }
      if (this._deleteLabelHandlers) {
        this._deleteLabelHandlers.forEach(function(item) {
          try { item.el.removeEventListener('click', item.handler); } catch(e) {}
          item.el.style.cursor = 'pointer';
        });
        this._deleteLabelHandlers.clear();
        this._deleteLabelHandlers = null;
      }
      this._deleteClickToken = null;
      this.map.getCanvas().style.cursor = '';
    }

    // ========== Fallback Edit/Delete Helpers ==========

    _isCoverageLayer(l) {
      return l && l.feature && l.feature.properties && l.feature.properties.sub_type === 'sprinkler_coverage';
    }

    _isModeAllowedStrict(fType, activeMode) {
      if (!activeMode || !fType) return true;
      return (activeMode === fType)
          || (activeMode === 'aot_device' && fType === 'device')
          || (activeMode === 'equipment' && ['reference', 'connection'].includes(fType));
    }

    _getFallbackLayerIds() {
      var ids = new Set();
      var self = this;
      var ed = window.AoTMapEditor;
      var activeMode = (window.geoDesign && window.geoDesign.activeMode) || null;
      // Pipes render in shared RenderBucket layers — must use bucket IDs, not per-instance _layerId
      // Only add bucket IDs that actually exist as MapLibre style layers (prevents queryRenderedFeatures throw)
      var ALL_BUCKET_LINE_IDS = ['aot-bucket-pipe-main', 'aot-bucket-pipe-branch', 'aot-bucket-line-generic', 'aot-bucket-pipe-reference'];

      var _bucketExists = function(id) { try { return !!(self.map.getLayer && self.map.getLayer(id)); } catch(e) { return false; } };

      var scanLayer = function(l) {
        if (!l || !l._layerId) return;
        // Coverage circles are deletable (not editable) — do NOT exclude them here
        var fType = l.feature && l.feature.properties && l.feature.properties.aot_type;
        if (!self._isModeAllowedStrict(fType, activeMode)) return;
        if (l._aotType === 'Polyline') {
          ALL_BUCKET_LINE_IDS.forEach(function(id) { if (_bucketExists(id)) ids.add(id); });
        } else {
          ids.add(l._layerId);
        }
      };

      var fg = ed && ed.featureGroup;
      if (fg && fg.layers) fg.layers.forEach(scanLayer);
      var ls = ed && ed.layerStorage;
      if (ls) {
        Object.values(ls).forEach(function(group) {
          if (!group || !group.eachLayer) return;
          group.eachLayer(scanLayer);
        });
      }
      return Array.from(ids);
    }

    // Screen-space distance (px) from point p to segment a→b.
    _distToSegment(p, a, b) {
      var dx = b.x - a.x, dy = b.y - a.y;
      var l2 = dx * dx + dy * dy;
      if (l2 === 0) return Math.hypot(p.x - a.x, p.y - a.y);
      var t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2;
      t = Math.max(0, Math.min(1, t));
      return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
    }

    // Geometry-based nearest-pipe finder. queryRenderedFeatures only hits the few
    // rendered pixels of a thin line, so clicks just beside a pipe miss. This projects
    // each pipe's LineString to screen space and returns the closest layer within maxPx.
    // Mode-filtered identically to _getFallbackLayerIds so it can't select shapes from
    // an inactive mode.
    _findNearestLineLayer(point, maxPx) {
      var self = this;
      var ed = window.AoTMapEditor;
      var activeMode = (window.geoDesign && window.geoDesign.activeMode) || null;
      var best = null;
      var bestDist = (maxPx != null ? maxPx : 12);
      var consider = function(l) {
        if (!l || !l._layerId || l._aotType !== 'Polyline') return;
        var fType = l.feature && l.feature.properties && l.feature.properties.aot_type;
        if (!self._isModeAllowedStrict(fType, activeMode)) return;
        var geom = l.feature && l.feature.geometry;
        if (!geom) return;
        var lines = geom.type === 'MultiLineString' ? geom.coordinates
                  : (geom.type === 'LineString' ? [geom.coordinates] : null);
        if (!lines) return;
        for (var li = 0; li < lines.length; li++) {
          var coords = lines[li];
          for (var i = 0; i < coords.length - 1; i++) {
            var a, b;
            try {
              a = self.map.project({ lng: coords[i][0], lat: coords[i][1] });
              b = self.map.project({ lng: coords[i + 1][0], lat: coords[i + 1][1] });
            } catch (e) { continue; }
            var d = self._distToSegment(point, a, b);
            if (d < bestDist) { bestDist = d; best = l; }
          }
        }
      };
      var fg = ed && ed.featureGroup;
      if (fg && fg.layers) fg.layers.forEach(consider);
      var ls = ed && ed.layerStorage;
      if (ls) {
        Object.keys(ls).forEach(function(k) {
          var g = ls[k];
          if (g && g.eachLayer) g.eachLayer(consider);
        });
      }
      return best;
    }

    _getLayerByHit(hit) {
      if (!hit) return null;
      var mlLayerId = hit.layer && hit.layer.id;
      if (!mlLayerId) return null;
      // Bucket layer hit: find AoTGeoLayer by node_id/db_id in feature properties
      if (mlLayerId.indexOf('aot-bucket-') === 0) {
        var props = hit.properties || {};
        var nodeId = props.node_id || props.db_id;
        if (!nodeId) return null;
        var nodeStr = String(nodeId);
        var ed = window.AoTMapEditor;
        var fg = ed && ed.featureGroup;
        if (fg && fg.layers) {
          for (var i = 0; i < fg.layers.length; i++) {
            var l = fg.layers[i];
            if (l && l.feature && l.feature.properties) {
              var lp = l.feature.properties;
              if (String(lp.node_id) === nodeStr || String(lp.db_id) === nodeStr) return l;
            }
          }
        }
        var ls = ed && ed.layerStorage;
        if (ls) {
          var found = null;
          Object.values(ls).forEach(function(group) {
            if (found || !group || !group.eachLayer) return;
            group.eachLayer(function(layer) {
              if (found || !layer || !layer.feature) return;
              var lp = layer.feature.properties || {};
              if (String(lp.node_id) === nodeStr || String(lp.db_id) === nodeStr) found = layer;
            });
          });
          if (found) return found;
        }
        return null;
      }
      return this._getLayerByMlId(mlLayerId);
    }

    _getLayerByMlId(mlLayerId) {
      var ed = window.AoTMapEditor;
      // featureGroup first
      var fg = ed && ed.featureGroup;
      if (fg && fg.layers) {
        for (var i = 0; i < fg.layers.length; i++) {
          if (fg.layers[i] && fg.layers[i]._layerId === mlLayerId) return fg.layers[i];
        }
      }
      // layerStorage (loaded shapes)
      var ls = ed && ed.layerStorage;
      if (ls) {
        var found = null;
        Object.values(ls).forEach(function(group) {
          if (found || !group || !group.eachLayer) return;
          group.eachLayer(function(l) {
            if (!found && l && l._layerId === mlLayerId) found = l;
          });
        });
        if (found) return found;
      }
      return null;
    }

    // ========== Public API - Direct Layer Actions ==========

    editSelectLayerDirect(layer) {
      if (!layer || !layer._layerId) return;
      if (this._isCoverageLayer(layer)) return;
      // Block cross-mode edit selection
      var _fType = layer.feature && layer.feature.properties && layer.feature.properties.aot_type;
      var _activeMode = (window.geoDesign && window.geoDesign.activeMode) || null;
      if (_activeMode && !this._isModeAllowedStrict(_fType, _activeMode)) return;
      // Ensure edit fallback state exists (in case enableEdit was via different path)
      if (!this._editState) this._editState = { selectedLayer: null, selectedLayerId: null, vertexDragging: false, vertexIdx: null, ringIdx: 0, origFeature: null };
      this._editDeselect();
      var mlLayerId = layer._layerId;
      this._editState.selectedLayer = layer;
      this._editState.selectedLayerId = mlLayerId;
      this._editState.origFeature = JSON.stringify(layer.feature);
      try {
        if (this.map.getLayer('_aot-edit-select-outline')) this.map.removeLayer('_aot-edit-select-outline');
        if (this.map.getSource('_aot-edit-select-outline-src')) this.map.removeSource('_aot-edit-select-outline-src');
        // Polyline renders in shared bucket — create a dedicated GeoJSON source for the outline
        var outlineSrcId;
        if (layer._aotType === 'Polyline') {
          var outlineData = layer.feature || { type: 'Feature', geometry: { type: 'LineString', coordinates: [] }, properties: {} };
          this.map.addSource('_aot-edit-select-outline-src', { type: 'geojson', data: outlineData });
          outlineSrcId = '_aot-edit-select-outline-src';
        } else {
          var srcId = 'aot-source-' + mlLayerId;
          outlineSrcId = this.map.getSource(srcId) ? srcId : null;
        }
        if (outlineSrcId) {
          this.map.addLayer({ id: '_aot-edit-select-outline', type: 'line', source: outlineSrcId,
            paint: { 'line-color': '#ff9900', 'line-width': 3, 'line-dasharray': [4, 2] } });
        }
      } catch(e) {}
      this._renderEditVertices(layer);
    }

    deleteLayerDirect(layer) {
      if (!layer || !layer._layerId) return;
      // Buffer deletion for cancelActions() restore (only when in an active delete session)
      var _ed = window.AoTMapEditor;
      if (_ed && _ed.deleteEnabled && _ed._pendingDeletes) {
        var _nid = layer.feature && layer.feature.properties && (layer.feature.properties.node_id || layer.feature.properties.db_id);
        // Avoid duplicate buffering (layer click handler may have already buffered it)
        var alreadyBuffered = _ed._pendingDeletes.some(function(e) { return e.layer === layer; });
        if (!alreadyBuffered) {
          _ed._pendingDeletes.push({ layer: layer, nid: _nid });
        }
      }
      var mlId = layer._layerId;
      var srcId = 'aot-source-' + mlId;
      // Per-instance GL layer removal (polygons/points)
      try { if (this.map.getLayer(mlId))  this.map.removeLayer(mlId);  } catch(e) {}
      try { if (this.map.getSource(srcId)) this.map.removeSource(srcId); } catch(e) {}
      try { if (this.map.getLayer(mlId + '-outline')) this.map.removeLayer(mlId + '-outline'); } catch(e) {}
      // Polyline (pipe) → remove from shared RenderBucket for visual deletion
      if (layer._aotType === 'Polyline' && layer._getBucketCategory && layer._map) {
        try {
          var category = layer._getBucketCategory();
          var bucket = window.RenderBucket && window.RenderBucket.get(layer._map, category);
          if (bucket) bucket.remove(layer._layerId);
        } catch(be) {}
      }
      var fg = window.AoTMapEditor && window.AoTMapEditor.featureGroup;
      if (fg && fg.removeLayer) fg.removeLayer(layer);
      var ed = window.AoTMapEditor;
      if (ed && ed.layers && layer.feature && layer.feature.id) ed.layers.delete(layer.feature.id);
      // Synchronously drop the layer from every layerStorage group as well.
      // The aot:editor:deleted listener also clears layerStorage, but it runs async —
      // switching tools before it fires can re-render the shape from storage (the
      // "deleted pipe reappears" bug). Removing here makes deletion immediate & durable.
      var ls = ed && ed.layerStorage;
      if (ls) {
        Object.keys(ls).forEach(function(k) {
          var group = ls[k];
          if (group && group.hasLayer && group.removeLayer && group.hasLayer(layer)) {
            group.removeLayer(layer);
          }
        });
      }
      // Fire draw:deleted on map → aot-geo-events.js / design-v3.js persistence handler
      // IMPORTANT: shim.fire is not delegated to native map — use _originalMap directly
      try {
        var _fg = { eachLayer: function(fn) { fn(layer); } };
        var _fireMap = (this.map && (this.map._originalMap || this.map));
        if (_fireMap && _fireMap.fire) _fireMap.fire('draw:deleted', { layers: _fg });
      } catch(e2) {}
      this._onDrawDelete([layer.feature || { id: mlId, type: 'Feature', geometry: null, properties: {} }]);
    }

    // ========== Public API - Feature Management ==========

    getAll() {
      if (this._fallbackMode) return { type: 'FeatureCollection', features: this._drawnFeatures };
      return this.draw ? this.draw.getAll() : { type: 'FeatureCollection', features: [] };
    }

    getSelected() {
      return this.draw ? this.draw.getSelected() : { type: 'FeatureCollection', features: [] };
    }

    getSelectedIds() {
      return this.draw ? this.draw.getSelectedIds() : [];
    }

    deleteSelected() {
      if (this.draw) {
        var selected = this.draw.getSelectedIds();
        if (selected.length > 0) this.draw.delete(selected);
      }
    }

    deleteAll() {
      if (this.draw) this.draw.deleteAll();
      this._drawnFeatures = [];
      this._markers.forEach(function(m) { m.remove(); });
      this._markers = [];
    }

    add(feature) {
      if (this.draw) {
        var ids = this.draw.add(feature);
        if (ids && ids.length > 0) {
          this._drawnFeatures.push(feature);
          return ids[0];
        }
      }
      return null;
    }

    addGeoJSON(data) {
      if (typeof data === 'string') data = JSON.parse(data);
      var features = data.features || [];
      var ids = [], self = this;
      features.forEach(function(feature) {
        var id = self.add(feature);
        if (id) ids.push(id);
      });
      return ids;
    }

    clearAll() {
      this.deleteAll();
      this._fire('clear', {});
    }

    // ========== Public API - Layer Management ==========

    getLayers() {
      var self = this;
      var geojson = this.getAll();
      return geojson.features.map(function(f) {
        return {
          feature: f,
          toGeoJSON: function() { return f; },
          getLatLng: function() {
            if (f.geometry.type === 'Point') return { lat: f.geometry.coordinates[1], lng: f.geometry.coordinates[0] };
            return null;
          },
          setStyle: function(style) { f.properties = f.properties || {}; f.properties.style = style; }
        };
      });
    }

    addLayer(layer) {
      if (layer.feature && layer.feature.id) this._layers.set(layer.feature.id, layer);
    }

    // ========== Public API - Style ==========

    setStyle(style) {
      if (style.color) this.options.defaultColor = style.color;
      if (style.fillColor) this.options.fillColor = style.fillColor;
      if (style.fillOpacity) this.options.fillOpacity = style.fillOpacity;
      if (style.weight) this.options.lineWidth = style.weight;
    }

    // ========== Public API - Event Handling ==========

    on(event, callback) {
      if (!this._eventHandlers[event]) this._eventHandlers[event] = [];
      this._eventHandlers[event].push(callback);
    }

    off(event, callback) {
      if (this._eventHandlers[event]) {
        this._eventHandlers[event] = this._eventHandlers[event].filter(function(h) { return h !== callback; });
      }
    }

    _fire(event, data) {
      if (this._eventHandlers[event]) {
        var self = this;
        this._eventHandlers[event].forEach(function(handler) {
          try { handler(data); } catch (e) { console.error('[MapLibreDraw] Event handler error:', e); }
        });
      }
    }

    // ========== Utility Methods ==========

    isReady() { return this._initialized; }
    isDrawing() { return this._activeMode !== null && this._activeMode !== 'simple_select'; }
    getMode() { return this._activeMode; }
    getCount() { return this._drawnFeatures.length; }

    // ========== Cleanup ==========

    destroy() {
      if (this.draw && this.map) {
        this.map.removeControl(this.draw);
        this.draw = null;
      }
      if (this._clickHandler) {
        this.map.off('click', this._clickHandler);
        this._clickHandler = null;
      }
      if (this._toolbar && this._toolbar.parentNode) {
        this._toolbar.parentNode.removeChild(this._toolbar);
      }
      this._markers.forEach(function(m) { m.remove(); });
      this._markers = [];
      this._drawnFeatures = [];
      this._eventHandlers = {};
      this._layers.clear();
      this._initialized = false;
    }
  }

  // ========== AoTMapLibreDrawManager ==========

  var AoTMapLibreDrawManager = {
    instances: new Map(),
    DEFAULT_ID: 'default',
    _instanceCounter: 0,

    init: function(containerId, map, config) {
      if (!map) throw new Error('[AoTMapLibreDrawManager] Map instance is required');
      var id = 'draw_' + (this._instanceCounter++);
      var instance = new MapLibreDraw(map, config);
      instance.init();
      this.instances.set(id, instance);
      return instance;
    },

    get: function(id) {
      return this.instances.get(id || this.DEFAULT_ID) || null;
    },

    getDefault: function(map, config) {
      var instance = this.instances.get(this.DEFAULT_ID);
      if (!instance) instance = this.init(this.DEFAULT_ID, map, config);
      return instance;
    },

    destroyAll: function() {
      this.instances.forEach(function(instance) { instance.destroy(); });
    }
  };

  // Export
  global.MapLibreDraw = MapLibreDraw;
  global.AoTMapLibreDraw = MapLibreDraw;
  global.AoTMapLibreDrawManager = AoTMapLibreDrawManager;

})(typeof window !== 'undefined' ? window : global);
