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
  'use strict';

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
      var self = this;
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
