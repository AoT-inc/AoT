/**
 * AoTMapLibreDrawTool.js
 * MapLibre GL 그리기 도구 모듈
 * 
 * @version 1.0.0
 * @author AoT Team
 * @requires maplibre-gl
 */

(function(global) {
  'use strict';

  /**
   * AoTMapLibreDrawTool Class
   * 점/선/면/사각형/원 그리기, 선택/편집/삭제
   */
  class AoTMapLibreDrawTool {
    /**
     * Create a new DrawTool instance
     * @param {maplibregl.Map} map - MapLibre map instance
     * @param {Object} options - Configuration options
     */
    constructor(map, options = {}) {
      this._map = map;
      this._options = Object.assign({}, this._getDefaultOptions(), options);
      this._drawControl = null;
      this._initialized = false;
      this._activeMode = null;
      this._eventHandlers = {};
      this._features = new Map();
      this._selectedFeatureId = null;
      this._style = this._getDefaultStyle();
    }

    /**
     * Get default options
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
        // Enable/disable specific shapes
        polyline: true,
        polygon: true,
        rectangle: true,
        circle: true,
        marker: true,
        trash: true
      };
    }

    /**
     * Get default style
     * @private
     */
    _getDefaultStyle() {
      const color = this._options.defaultColor;
      return {
        color: color,
        fillColor: color,
        fillOpacity: 0.2,
        weight: 2,
        radius: 6
      };
    }

    // ========== Initialization ==========

    /**
     * Initialize the draw tool
     * @returns {Promise<boolean>}
     */
    async init() {
      if (this._initialized) {
        console.warn('[AoTMapLibreDrawTool] Already initialized');
        return true;
      }

      if (typeof maplibregl === 'undefined') {
        console.error('[AoTMapLibreDrawTool] maplibre-gl not loaded');
        return false;
      }

      // Try to load @maplibre/maplibre-gl-draw
      const loaded = await this._loadDrawLibrary();
      
      if (loaded && typeof MapLibreDrawControl !== 'undefined') {
        this._initWithDrawControl();
      } else {
        console.warn('[AoTMapLibreDrawTool] Using fallback mode');
        this._initFallback();
      }

      this._initialized = true;
      return true;
    }

    /**
     * Load MapLibre Draw library
     * @private
     */
    _loadDrawLibrary() {
      return new Promise((resolve) => {
        // Check if already loaded
        if (typeof MapLibreDrawControl !== 'undefined') {
          resolve(true);
          return;
        }

        // Use AOT_MAP_LOADER if available
        if (typeof window.AOT_MAP_LOADER !== 'undefined' && window.AOT_MAP_LOADER.loadMapLibreDraw) {
          window.AOT_MAP_LOADER.loadMapLibreDraw({ version: '1.4.3' })
            .then(() => resolve(true))
            .catch(() => resolve(false));
          return;
        }

        // Manual CDN load
        const version = '1.4.3';
        const cdnBase = 'https://unpkg.com';

        // Inject CSS
        if (!document.querySelector('link[href*="maplibre-gl-draw"]')) {
          const link = document.createElement('link');
          link.rel = 'stylesheet';
          link.href = cdnBase + '/@maplibre/maplibre-gl-draw@' + version + '/dist/maplibre-gl-draw.css';
          document.head.appendChild(link);
        }

        // Inject JS
        const script = document.createElement('script');
        script.src = cdnBase + '/@maplibre/maplibre-gl-draw@' + version + '/dist/maplibre-gl-draw.js';
        script.async = true;
        script.onload = () => resolve(typeof MapLibreDrawControl !== 'undefined');
        script.onerror = () => resolve(false);
        document.head.appendChild(script);
      });
    }

    /**
     * Initialize with MapLibreDrawControl
     * @private
     */
    _initWithDrawControl() {
      try {
        this._drawControl = new MapLibreDrawControl({
          displayControlsDefault: this._options.displayControlsDefault,
          controls: this._options.controls,
          styles: this._getDrawStyles()
        });

        this._map.addControl(this._drawControl, 'top-left');
        this._bindDrawEvents();
        
        console.log('[AoTMapLibreDrawTool] Initialized with MapLibreDrawControl');
      } catch (error) {
        console.error('[AoTMapLibreDrawTool] Failed to initialize draw control:', error);
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
      
      // Bind fallback events
      this._bindFallbackEvents();
      
      console.log('[AoTMapLibreDrawTool] Initialized in fallback mode');
    }

    /**
     * Get draw styles for MapLibre Draw
     * @private
     */
    _getDrawStyles() {
      const color = this._style.color;
      return [
        // Points
        {
          id: 'gl-draw-point',
          type: 'circle',
          filter: ['all', ['==', '$type', 'Point']],
          paint: {
            'circle-radius': this._style.radius,
            'circle-color': color,
            'circle-stroke-color': '#fff',
            'circle-stroke-width': 2
          }
        },
        // Lines
        {
          id: 'gl-draw-line',
          type: 'line',
          filter: ['all', ['==', '$type', 'LineString']],
          paint: {
            'line-color': color,
            'line-width': this._style.weight,
            'line-dasharray': [2, 2]
          }
        },
        // Polygons fill
        {
          id: 'gl-draw-polygon-fill',
          type: 'fill',
          filter: ['all', ['==', '$type', 'Polygon']],
          paint: {
            'fill-color': color,
            'fill-opacity': this._style.fillOpacity
          }
        },
        // Polygons stroke
        {
          id: 'gl-draw-polygon-stroke',
          type: 'line',
          filter: ['all', ['==', '$type', 'Polygon']],
          paint: {
            'line-color': color,
            'line-width': this._style.weight
          }
        },
        // Vertex points
        {
          id: 'gl-draw-vertex',
          type: 'circle',
          filter: ['all', ['==', '$type', 'Point'], ['==', 'meta', 'vertex']],
          paint: {
            'circle-radius': 5,
            'circle-color': '#fff',
            'circle-stroke-color': color,
            'circle-stroke-width': 2
          }
        }
      ];
    }

    // ========== Fallback Event Handling ==========

    /**
     * Bind fallback drawing events
     * @private
     */
    _bindFallbackEvents() {
      // Click to add point
      this._map.on('click', (e) => {
        if (!this._fallbackMode || !this._currentDrawType) return;

        const coords = [e.lngLat.lng, e.lngLat.lat];
        
        if (this._currentDrawType === 'marker') {
          this._finishDraw('Point', coords);
        } else {
          this._tempCoords.push(coords);
          this._updateTempFeature();
        }
      });

      // Double click to finish
      this._map.on('dblclick', (e) => {
        if (!this._fallbackMode || !this._currentDrawType) return;
        
        if (this._currentDrawType === 'polyline' || this._currentDrawType === 'polygon') {
          e.preventDefault();
          if (this._tempCoords.length >= 2) {
            const type = this._currentDrawType === 'polyline' ? 'LineString' : 'Polygon';
            const coords = type === 'Polygon' ? [this._tempCoords] : this._tempCoords;
            this._finishDraw(type, coords);
          }
        }
      });
    }

    /**
     * Update temporary feature during drawing
     * @private
     */
    _updateTempFeature() {
      // Implementation depends on how temp features are shown
      // For now, just track coordinates
    }

    /**
     * Finish drawing
     * @private
     */
    _finishDraw(type, coords) {
      const feature = {
        type: 'Feature',
        geometry: {
          type: type,
          coordinates: coords
        },
        properties: {
          id: 'draw-' + Date.now(),
          drawType: this._currentDrawType
        }
      };

      this._features.set(feature.properties.id, feature);
      this._currentDrawType = null;
      this._tempCoords = [];

      this._fire('create', { feature: feature });
    }

    // ========== Draw Control Events ==========

    /**
     * Bind draw control events
     * @private
     */
    _bindDrawEvents() {
      if (!this._drawControl) return;

      this._map.on('draw.create', (e) => {
        e.features.forEach(feature => {
          this._features.set(feature.id, feature);
          this._fire('create', { feature: feature });
        });
      });

      this._map.on('draw.update', (e) => {
        e.features.forEach(feature => {
          this._features.set(feature.id, feature);
          this._fire('edit', { feature: feature });
        });
      });

      this._map.on('draw.delete', (e) => {
        e.features.forEach(feature => {
          this._features.delete(feature.id);
          this._fire('delete', { feature: feature });
        });
      });

      this._map.on('draw.selectionchange', (e) => {
        if (e.features.length > 0) {
          this._selectedFeatureId = e.features[0].id;
          this._fire('select', { feature: e.features[0] });
        } else {
          this._selectedFeatureId = null;
        }
      });

      this._map.on('draw.modechange', (e) => {
        this._activeMode = e.mode;
        this._fire('modechange', { mode: e.mode });
      });
    }

    // ========== Public API ==========

    /**
     * Enable point drawing
     */
    enablePoint() {
      if (this._fallbackMode) {
        this._currentDrawType = 'marker';
      } else if (this._drawControl) {
        this._drawControl.changeMode('draw_point');
      }
      this._activeMode = 'draw_point';
      return this;
    }

    /**
     * Enable line drawing
     */
    enableLine() {
      if (this._fallbackMode) {
        this._currentDrawType = 'polyline';
      } else if (this._drawControl) {
        this._drawControl.changeMode('draw_line_string');
      }
      this._activeMode = 'draw_line_string';
      return this;
    }

    /**
     * Enable polygon drawing
     */
    enablePolygon() {
      if (this._fallbackMode) {
        this._currentDrawType = 'polygon';
      } else if (this._drawControl) {
        this._drawControl.changeMode('draw_polygon');
      }
      this._activeMode = 'draw_polygon';
      return this;
    }

    /**
     * Enable rectangle drawing (if supported)
     */
    enableRectangle() {
      // MapLibre Draw doesn't have built-in rectangle, use polygon mode
      // or custom implementation
      this.enablePolygon();
      return this;
    }

    /**
     * Enable circle drawing (if supported)
     */
    enableCircle() {
      // Circle requires special handling
      this.enablePolygon();
      return this;
    }

    /**
     * Enable marker drawing
     */
    enableMarker() {
      return this.enablePoint();
    }

    /**
     * Disable drawing and return to select mode
     */
    disableDraw() {
      if (this._fallbackMode) {
        this._currentDrawType = null;
        this._tempCoords = [];
      } else if (this._drawControl) {
        this._drawControl.changeMode('simple_select');
      }
      this._activeMode = 'simple_select';
      return this;
    }

    /**
     * Enable edit mode
     */
    enableEdit() {
      if (this._drawControl) {
        this._drawControl.changeMode('direct_select', { featureId: this._selectedFeatureId });
      }
      return this;
    }

    /**
     * Enable delete mode
     */
    enableDelete() {
      if (this._drawControl) {
        this._drawControl.changeMode('simple_select');
      }
      return this;
    }

    /**
     * Delete selected feature
     */
    deleteSelected() {
      if (this._selectedFeatureId && this._drawControl) {
        this._drawControl.delete(this._selectedFeatureId);
      }
      return this;
    }

    /**
     * Get all drawn features
     * @returns {Object}
     */
    getAll() {
      if (this._fallbackMode) {
        return {
          type: 'FeatureCollection',
          features: Array.from(this._features.values())
        };
      }
      
      return this._drawControl ? this._drawControl.getAll() : 
        { type: 'FeatureCollection', features: [] };
    }

    /**
     * Get feature by ID
     * @param {string} id
     * @returns {Object|null}
     */
    get(id) {
      return this._features.get(id) || null;
    }

    /**
     * Add a feature programmatically
     * @param {Object} feature
     */
    add(feature) {
      if (this._drawControl) {
        this._drawControl.add(feature);
      }
      this._features.set(feature.id || feature.properties?.id, feature);
    }

    /**
     * Set style
     * @param {Object} style
     */
    setStyle(style) {
      this._style = Object.assign({}, this._style, style);
      
      // Update existing features if needed
      if (this._drawControl && this._drawControl.setFeatureProperty) {
        // Apply new style
      }
      
      return this;
    }

    /**
     * Get current mode
     * @returns {string}
     */
    getMode() {
      return this._activeMode;
    }

    /**
     * Clear all features
     */
    clear() {
      if (this._drawControl) {
        const all = this._drawControl.getAll();
        if (all.features.length > 0) {
          this._drawControl.deleteAll();
        }
      }
      this._features.clear();
      return this;
    }

    /**
     * Get draw control instance
     * @returns {Object}
     */
    getControl() {
      return this._drawControl;
    }

    // ========== Event System ==========

    /**
     * Add event listener
     * @param {string} eventType
     * @param {Function} handler
     * @returns {AoTMapLibreDrawTool}
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
     * @returns {AoTMapLibreDrawTool}
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
            console.error(`[AoTMapLibreDrawTool] Event handler error:`, e);
          }
        });
      }
    }

    // ========== Cleanup ==========

    /**
     * Destroy the draw tool
     */
    destroy() {
      if (this._drawControl && this._map) {
        this._map.removeControl(this._drawControl);
        this._drawControl = null;
      }
      this._features.clear();
      this._eventHandlers = {};
      this._initialized = false;
    }
  }

  // Static factory method
  AoTMapLibreDrawTool.create = async function(map, options = {}) {
    const tool = new AoTMapLibreDrawTool(map, options);
    await tool.init();
    return tool;
  };

  // Export
  global.AoTMapLibreDrawTool = AoTMapLibreDrawTool;

})(typeof window !== 'undefined' ? window : global);
