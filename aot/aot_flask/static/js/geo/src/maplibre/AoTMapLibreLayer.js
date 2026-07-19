/**
 * AoTMapLibreLayer.js
 * MapLibre GL 레이어 관리 모듈
 * 
 * @version 1.0.0
 * @author AoT Team
 * @requires maplibre-gl, turf (optional)
 */

(function(global) {
  'use strict';

  /**
   * AoTMapLibreLayer Class
   * GeoJSON 소스/레이어 관리, 피처 렌더링, 필터/쿼리 기능
   */
  class AoTMapLibreLayer {
    /**
     * Create a new AoTMapLibreLayer instance
     * @param {maplibregl.Map} map - MapLibre map instance
     * @param {Object} options - Configuration options
     */
    constructor(map, options = {}) {
      this._map = map;
      this._sourceId = null;
      this._layerIds = [];
      this._options = Object.assign({}, this._getDefaultOptions(), options);
      this._eventHandlers = {};
      this._popup = null;
      this._popupContent = null;
      this._tooltipContent = null;
      this._style = null;
      this._visible = true;
      this._geojson = null;
      this._selectedFeatures = new Set();
    }

    /**
     * Get default options
     * @private
     */
    _getDefaultOptions() {
      return {
        // Styling
        colors: {
          fill: '#995aff',
          stroke: '#995aff',
          circle: '#995aff'
        },
        fillOpacity: 0.2,
        strokeWidth: 2,
        circleRadius: 6,
        // Rendering options
        interactive: true,
        uniqueField: 'id',
        // Filter
        filter: null,
        // Callbacks
        onClick: null,
        onHover: null,
        onCreate: null,
        onEdit: null,
        onDelete: null
      };
    }

    // ========== Static Factory Methods ==========

    /**
     * Create layer from GeoJSON object
     * @param {maplibregl.Map} map - MapLibre map instance
     * @param {Object} geojson - GeoJSON FeatureCollection or Feature
     * @param {Object} options - Layer options
     * @returns {AoTMapLibreLayer}
     */
    static fromGeoJSON(map, geojson, options = {}) {
      const layer = new AoTMapLibreLayer(map, options);
      layer._geojson = geojson;
      return layer;
    }

    // ========== Lifecycle ==========

    /**
     * Add layer to map
     * @returns {AoTMapLibreLayer}
     */
    addTo(map) {
      if (map) this._map = map;
      if (!this._map) {
        console.error('[AoTMapLibreLayer] Map not available');
        return this;
      }

      this._addSource();
      this._addLayers();
      this._bindEvents();
      this._fire('add', { layer: this });
      
      return this;
    }

    /**
     * Remove layer from map
     * @returns {AoTMapLibreLayer}
     */
    remove() {
      // Remove click/hover handlers
      this._unbindEvents();

      // Remove all layers
      this._layerIds.forEach(id => {
        if (this._map && this._map.getLayer(id)) {
          this._map.removeLayer(id);
        }
      });
      this._layerIds = [];

      // Remove source
      if (this._map && this._sourceId && this._map.getSource(this._sourceId)) {
        this._map.removeSource(this._sourceId);
      }
      this._sourceId = null;

      // Close popup
      if (this._popup) {
        this._popup.remove();
        this._popup = null;
      }

      this._fire('remove', { layer: this });
      return this;
    }

    /**
     * Add GeoJSON source
     * @private
     */
    _addSource() {
      const id = 'aot-layer-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
      this._sourceId = id;

      // Ensure proper GeoJSON structure
      let data = this._geojson;
      if (!data) {
        data = { type: 'FeatureCollection', features: [] };
      } else if (data.type === 'Feature') {
        data = { type: 'FeatureCollection', features: [data] };
      }

      this._map.addSource(id, {
        type: 'geojson',
        data: data,
        promoteId: this._options.uniqueField
      });
    }

    /**
     * Add render layers based on geometry types
     * @private
     */
    _addLayers() {
      if (!this._style) {
        this._style = this._getDefaultStyle();
      }

      // Fill layer for polygons
      if (this._hasGeometryType('Polygon')) {
        this._addFillLayer();
        this._addStrokeLayer();
      }

      // Line layer for LineStrings
      if (this._hasGeometryType('LineString')) {
        this._addLineLayer();
      }

      // Circle layer for Points
      if (this._hasGeometryType('Point')) {
        this._addCircleLayer();
      }
    }

    /**
     * Get default style
     * @private
     */
    _getDefaultStyle() {
      const colors = this._options.colors;
      return {
        fill: {
          'fill-color': colors.fill,
          'fill-opacity': this._options.fillOpacity
        },
        stroke: {
          'line-color': colors.stroke,
          'line-width': this._options.strokeWidth
        },
        circle: {
          'circle-color': colors.circle,
          'circle-radius': this._options.circleRadius,
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ffffff'
        }
      };
    }

    /**
     * Check if GeoJSON contains specific geometry type
     * @private
     */
    _hasGeometryType(type) {
      if (!this._geojson || !this._geojson.features) return false;
      return this._geojson.features.some(f => f.geometry && f.geometry.type === type);
    }

    /**
     * Add fill layer for polygons
     * @private
     */
    _addFillLayer() {
      const fillId = this._sourceId + '-fill';
      this._layerIds.push(fillId);
      
      this._map.addLayer({
        id: fillId,
        type: 'fill',
        source: this._sourceId,
        filter: ['==', '$type', 'Polygon'],
        paint: this._style.fill
      });
    }

    /**
     * Add stroke layer for polygons
     * @private
     */
    _addStrokeLayer() {
      const strokeId = this._sourceId + '-stroke';
      this._layerIds.push(strokeId);
      
      this._map.addLayer({
        id: strokeId,
        type: 'line',
        source: this._sourceId,
        filter: ['==', '$type', 'Polygon'],
        paint: this._style.stroke
      });
    }

    /**
     * Add line layer for LineStrings
     * @private
     */
    _addLineLayer() {
      const lineId = this._sourceId + '-line';
      this._layerIds.push(lineId);
      
      this._map.addLayer({
        id: lineId,
        type: 'line',
        source: this._sourceId,
        filter: ['==', '$type', 'LineString'],
        paint: this._style.stroke
      });
    }

    /**
     * Add circle layer for points
     * @private
     */
    _addCircleLayer() {
      const circleId = this._sourceId + '-circle';
      this._layerIds.push(circleId);
      
      this._map.addLayer({
        id: circleId,
        type: 'circle',
        source: this._sourceId,
        filter: ['==', '$type', 'Point'],
        paint: this._style.circle
      });
    }

    // ========== Event Binding ==========

    /**
     * Bind click and hover events
     * @private
     */
    _bindEvents() {
      if (!this._map || !this._options.interactive) return;

      // Click handler
      this._map.on('click', this._layerIds, (e) => {
        const features = e.features;
        if (features && features.length > 0) {
          this._handleClick(e, features[0]);
        }
      });

      // Hover handlers
      this._layerIds.forEach(id => {
        // Mouse enter
        this._map.on('mouseenter', id, () => {
          this._map.getCanvas().style.cursor = 'pointer';
        });
        
        // Mouse leave
        this._map.on('mouseleave', id, () => {
          this._map.getCanvas().style.cursor = '';
        });
      });

      // Hover click (for tooltips)
      this._map.on('click', this._layerIds, (e) => {
        if (this._tooltipContent) {
          this._showTooltip(e.lngLat, this._tooltipContent);
        }
      });
    }

    /**
     * Unbind events
     * @private
     */
    _unbindEvents() {
      // Events are automatically cleaned up when layers are removed
    }

    /**
     * Handle feature click
     * @private
     */
    _handleClick(e, feature) {
      // Store selected features
      this._selectedFeatures.clear();
      this._selectedFeatures.add(feature.id || feature.properties?.id);

      // Callback
      if (this._options.onClick) {
        this._options.onClick({
          layer: this,
          feature: feature,
          latlng: { lat: e.lngLat.lat, lng: e.lngLat.lng }
        });
      }

      this._fire('click', {
        layer: this,
        feature: feature,
        latlng: { lat: e.lngLat.lat, lng: e.lngLat.lng }
      });

      // Show popup if bound
      if (this._popupContent) {
        this._showPopup(e.lngLat, feature);
      }
    }

    /**
     * Show popup
     * @private
     */
    _showPopup(lngLat, feature) {
      if (this._popup) this._popup.remove();

      const content = typeof this._popupContent === 'function' 
        ? this._popupContent(feature) 
        : this._popupContent;

      this._popup = new maplibregl.Popup({ closeButton: true, closeOnClick: true })
        .setLngLat([lngLat.lng || lngLat.lng, lngLat.lat])
        .setHTML(content)
        .addTo(this._map);
    }

    /**
     * Show tooltip
     * @private
     */
    _showTooltip(lngLat, content) {
      // For now, use popup for tooltips (can be customized)
      if (this._popup) this._popup.remove();
      
      const tooltipContent = typeof content === 'function' 
        ? content() 
        : content;

      this._popup = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        offset: 15
      })
        .setLngLat([lngLat.lng || lngLat.lng, lngLat.lat])
        .setHTML(tooltipContent)
        .addTo(this._map);

      // Auto-close after delay
      setTimeout(() => {
        if (this._popup) {
          this._popup.remove();
          this._popup = null;
        }
      }, 3000);
    }

    // ========== Public API ==========

    /**
     * Get GeoJSON data
     * @returns {Object}
     */
    toGeoJSON() {
      if (!this._geojson) {
        return { type: 'FeatureCollection', features: [] };
      }
      return this._geojson.type === 'FeatureCollection' 
        ? this._geojson 
        : { type: 'FeatureCollection', features: [this._geojson] };
    }

    /**
     * Set GeoJSON data
     * @param {Object} geojson
     * @returns {AoTMapLibreLayer}
     */
    setGeoJSON(geojson) {
      this._geojson = geojson;
      if (this._sourceId) {
        const source = this._map?.getSource(this._sourceId);
        if (source && source.type === 'geojson') {
          source.setData(geojson);
        }
      }
      return this;
    }

    /**
     * Get bounds of all features
     * @returns {Object|null}
     */
    getBounds() {
      const fc = this.toGeoJSON();
      if (!fc.features || fc.features.length === 0) return null;

      let minLng = Infinity, minLat = Infinity;
      let maxLng = -Infinity, maxLat = -Infinity;

      const processCoords = (coords) => {
        if (typeof coords[0] === 'number') {
          minLng = Math.min(minLng, coords[0]);
          maxLng = Math.max(maxLng, coords[0]);
          minLat = Math.min(minLat, coords[1]);
          maxLat = Math.max(maxLat, coords[1]);
        } else {
          coords.forEach(processCoords);
        }
      };

      fc.features.forEach(f => {
        if (f.geometry && f.geometry.coordinates) {
          processCoords(f.geometry.coordinates);
        }
      });

      if (minLng === Infinity) return null;

      // Return Leaflet-compatible bounds format
      return {
        _southWest: { lat: minLat, lng: minLng },
        _northEast: { lat: maxLat, lng: maxLng },
        getSouthWest: function() { return this._southWest; },
        getNorthEast: function() { return this._northEast; },
        isValid: function() { return minLng !== Infinity; }
      };
    }

    /**
     * Fit map to layer bounds
     * @param {Object} options - FitBounds options
     * @returns {AoTMapLibreLayer}
     */
    fitBounds(options = {}) {
      const bounds = this.getBounds();
      if (bounds) {
        this._map.fitBounds([[bounds._southWest.lng, bounds._southWest.lat], 
                             [bounds._northEast.lng, bounds._northEast.lat]], options);
      }
      return this;
    }

    // ========== Popup/Tooltip API (Leaflet-compatible) ==========

    /**
     * Bind popup to layer (Leaflet API)
     * @param {string|Function} content - HTML content or content generator
     * @returns {AoTMapLibreLayer}
     */
    bindPopup(content) {
      this._popupContent = content;
      return this;
    }

    /**
     * Open popup at specific location
     * @param {Object} latlng - {lat, lng}
     * @param {string} content - HTML content
     * @returns {AoTMapLibreLayer}
     */
    openPopup(latlng, content) {
      if (this._popup) this._popup.remove();
      
      this._popup = new maplibregl.Popup({ closeButton: true, closeOnClick: true })
        .setLngLat([latlng.lng, latlng.lat])
        .setHTML(content)
        .addTo(this._map);
      
      return this;
    }

    /**
     * Close popup
     * @returns {AoTMapLibreLayer}
     */
    closePopup() {
      if (this._popup) {
        this._popup.remove();
        this._popup = null;
      }
      return this;
    }

    /**
     * Bind tooltip to layer (Leaflet API)
     * @param {string|Function} content - Tooltip content
     * @param {Object} options - Tooltip options
     * @returns {AoTMapLibreLayer}
     */
    bindTooltip(content, options = {}) {
      this._tooltipContent = content;
      this._tooltipOptions = options;
      return this;
    }

    // ========== Style API ==========

    /**
     * Set layer style
     * @param {Object} style - Style object
     * @returns {AoTMapLibreLayer}
     */
    setStyle(style) {
      this._style = Object.assign({}, this._style, style);
      
      // Update paint properties
      if (style.colors) {
        this._options.colors = Object.assign({}, this._options.colors, style.colors);
      }

      this._layerIds.forEach(id => {
        if (!this._map.getLayer(id)) return;

        // Update fill style
        if (id.endsWith('-fill') && this._style.fill) {
          Object.entries(this._style.fill).forEach(([prop, value]) => {
            this._map.setPaintProperty(id, prop, value);
          });
        }

        // Update stroke/line style
        if ((id.endsWith('-stroke') || id.endsWith('-line')) && this._style.stroke) {
          Object.entries(this._style.stroke).forEach(([prop, value]) => {
            this._map.setPaintProperty(id, prop, value);
          });
        }

        // Update circle style
        if (id.endsWith('-circle') && this._style.circle) {
          Object.entries(this._style.circle).forEach(([prop, value]) => {
            this._map.setPaintProperty(id, prop, value);
          });
        }
      });

      return this;
    }

    // ========== Visibility ==========

    /**
     * Show layer
     * @returns {AoTMapLibreLayer}
     */
    show() {
      this._visible = true;
      this._layerIds.forEach(id => {
        if (this._map.getLayer(id)) {
          this._map.setLayoutProperty(id, 'visibility', 'visible');
        }
      });
      return this;
    }

    /**
     * Hide layer
     * @returns {AoTMapLibreLayer}
     */
    hide() {
      this._visible = false;
      this._layerIds.forEach(id => {
        if (this._map.getLayer(id)) {
          this._map.setLayoutProperty(id, 'visibility', 'none');
        }
      });
      return this;
    }

    /**
     * Toggle visibility
     * @returns {AoTMapLibreLayer}
     */
    toggleVisibility() {
      return this._visible ? this.hide() : this.show();
    }

    // ========== Filter/Query ==========

    /**
     * Set layer filter
     * @param {Array} filter - MapLibre filter expression
     * @returns {AoTMapLibreLayer}
     */
    setFilter(filter) {
      this._options.filter = filter;
      this._layerIds.forEach(id => {
        if (this._map.getLayer(id)) {
          this._map.setFilter(id, filter);
        }
      });
      return this;
    }

    /**
     * Query features at point
     * @param {Array} point - [x, y] screen coordinates
     * @returns {Array}
     */
    queryRenderedFeatures(point) {
      return this._map.queryRenderedFeatures(point, { layers: this._layerIds });
    }

    /**
     * Get layer IDs
     * @returns {Array}
     */
    getLayerIds() {
      return [...this._layerIds];
    }

    /**
     * Get source ID
     * @returns {string|null}
     */
    getSourceId() {
      return this._sourceId;
    }

    // ========== Event System ==========

    /**
     * Add event listener
     * @param {string} eventType
     * @param {Function} handler
     * @returns {AoTMapLibreLayer}
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
     * @returns {AoTMapLibreLayer}
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
            console.error(`[AoTMapLibreLayer] Event handler error (${eventType}):`, e);
          }
        });
      }
    }

    // ========== Utility ==========

    /**
     * Iterate over features
     * @param {Function} callback - (feature, index) => void
     * @returns {AoTMapLibreLayer}
     */
    eachFeature(callback) {
      const fc = this.toGeoJSON();
      if (fc.features) {
        fc.features.forEach((feature, index) => callback(feature, index));
      }
      return this;
    }
  }

  // Export
  global.AoTMapLibreLayer = AoTMapLibreLayer;

})(typeof window !== 'undefined' ? window : global);
