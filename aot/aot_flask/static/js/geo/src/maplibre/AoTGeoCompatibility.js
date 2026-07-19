/**
 * AoTGeoCompatibility.js
 * GeoJSON 호환성 및 좌표계 변환 모듈
 * 
 * @version 1.0.0
 * @author AoT Team
 * @requires turf (optional)
 */

(function(global) {
  'use strict';

  /**
   * AoTGeoCompatibility Class
   * 기존 GeoJSON 데이터 형식 호환, 좌표계 변환, turf.js 래퍼
   */
  class AoTGeoCompatibility {
    /**
     * Create a new compatibility layer
     */
    constructor() {
      this._turf = null;
      this._initialized = false;
    }

    /**
     * Initialize turf.js
     * @returns {Promise<void>}
     */
    async init() {
      if (this._initialized) return;

      // Check if turf is already loaded
      if (typeof global.turf !== 'undefined') {
        this._turf = global.turf;
        this._initialized = true;
        return;
      }

      // Try to load turf.js
      await this._loadTurf();
      this._initialized = true;
    }

    /**
     * Load turf.js from CDN
     * @private
     */
    _loadTurf() {
      return new Promise((resolve) => {
        if (typeof global.turf !== 'undefined') {
          this._turf = global.turf;
          resolve();
          return;
        }

        const script = document.createElement('script');
        script.src = '/static/js/common/turf.min.js';
        script.async = true;
        script.onload = () => {
          this._turf = global.turf;
          resolve();
        };
        script.onerror = () => {
          console.warn('[AoTGeoCompatibility] Failed to load turf.js');
          resolve();
        };
        document.head.appendChild(script);
      });
    }

    /**
     * Check if turf is available
     * @returns {boolean}
     */
    hasTurf() {
      return this._turf !== null;
    }

    // ========== Turf.js Wrapper Methods ==========

    /**
     * Get turf instance
     * @returns {Object}
     */
    turf() {
      return this._turf;
    }

    /**
     * Calculate centroid
     * @param {Object} geojson
     * @returns {Object}
     */
    centroid(geojson) {
      if (!this._turf) return null;
      try {
        return this._turf.centroid(geojson);
      } catch (e) {
        console.error('[AoTGeoCompatibility] centroid error:', e);
        return null;
      }
    }

    /**
     * Calculate bounding box
     * @param {Object} geojson
     * @returns {Array} [minX, minY, maxX, maxY]
     */
    bbox(geojson) {
      if (!this._turf) return null;
      try {
        return this._turf.bbox(geojson);
      } catch (e) {
        console.error('[AoTGeoCompatibility] bbox error:', e);
        return null;
      }
    }

    /**
     * Calculate bounding box as bounds object
     * @param {Object} geojson
     * @returns {Object}
     */
    bounds(geojson) {
      const bbox = this.bbox(geojson);
      if (!bbox) return null;
      return {
        sw: [bbox[0], bbox[1]],
        ne: [bbox[2], bbox[3]],
        getSouthWest: function() { return { lat: this.sw[1], lng: this.sw[0] }; },
        getNorthEast: function() { return { lat: this.ne[1], lng: this.ne[0] }; },
        isValid: function() { return bbox[0] !== Infinity; }
      };
    }

    /**
     * Create buffer around geometry
     * @param {Object} geojson
     * @param {number} distance - Buffer distance in meters
     * @param {Object} options
     * @returns {Object}
     */
    buffer(geojson, distance, options = {}) {
      if (!this._turf) return null;
      try {
        return this._turf.buffer(geojson, distance, Object.assign({ units: 'meters' }, options));
      } catch (e) {
        console.error('[AoTGeoCompatibility] buffer error:', e);
        return null;
      }
    }

    /**
     * Calculate area
     * @param {Object} geojson
     * @returns {number} Area in square meters
     */
    area(geojson) {
      if (!this._turf) return 0;
      try {
        return this._turf.area(geojson);
      } catch (e) {
        console.error('[AoTGeoCompatibility] area error:', e);
        return 0;
      }
    }

    /**
     * Check if two geometries intersect
     * @param {Object} geojson1
     * @param {Object} geojson2
     * @returns {boolean}
     */
    intersects(geojson1, geojson2) {
      if (!this._turf) return false;
      try {
        return this._turf.booleanIntersects(geojson1, geojson2);
      } catch (e) {
        return false;
      }
    }

    /**
     * Check if geometry contains point
     * @param {Object} polygon
     * @param {Object} point
     * @returns {boolean}
     */
    contains(polygon, point) {
      if (!this._turf) return false;
      try {
        return this._turf.booleanPointInPolygon(point, polygon);
      } catch (e) {
        return false;
      }
    }

    /**
     * Check if geometry is within another
     * @param {Object} inner
     * @param {Object} outer
     * @returns {boolean}
     */
    within(inner, outer) {
      if (!this._turf) return false;
      try {
        return this._turf.booleanWithin(inner, outer);
      } catch (e) {
        return false;
      }
    }

    /**
     * Create circle from center and radius
     * @param {Array} center - [lng, lat]
     * @param {number} radius - Radius in meters
     * @param {Object} options
     * @returns {Object}
     */
    circle(center, radius, options = {}) {
      if (!this._turf) return null;
      try {
        return this._turf.circle(center, radius, Object.assign({
          steps: 64,
          units: 'meters'
        }, options));
      } catch (e) {
        console.error('[AoTGeoCompatibility] circle error:', e);
        return null;
      }
    }

    /**
     * Offset a line
     * @param {Object} geojson - LineString or Polygon
     * @param {number} distance - Offset distance in meters
     * @param {Object} options
     * @returns {Object}
     */
    lineOffset(geojson, distance, options = {}) {
      if (!this._turf) return null;
      try {
        return this._turf.lineOffset(geojson, distance, Object.assign({
          units: 'meters'
        }, options));
      } catch (e) {
        console.error('[AoTGeoCompatibility] lineOffset error:', e);
        return null;
      }
    }

    /**
     * Union multiple geometries
     * @param {Array} geometries
     * @returns {Object}
     */
    union(geometries) {
      if (!this._turf || geometries.length === 0) return null;
      try {
        let result = geometries[0];
        for (let i = 1; i < geometries.length; i++) {
          result = this._turf.union(result, geometries[i]);
        }
        return result;
      } catch (e) {
        console.error('[AoTGeoCompatibility] union error:', e);
        return null;
      }
    }

    /**
     * Difference between two geometries
     * @param {Object} geojson1
     * @param {Object} geojson2
     * @returns {Object}
     */
    difference(geojson1, geojson2) {
      if (!this._turf) return null;
      try {
        return this._turf.difference(geojson1, geojson2);
      } catch (e) {
        console.error('[AoTGeoCompatibility] difference error:', e);
        return null;
      }
    }

    /**
     * Intersection between two geometries
     * @param {Object} geojson1
     * @param {Object} geojson2
     * @returns {Object}
     */
    intersection(geojson1, geojson2) {
      if (!this._turf) return null;
      try {
        return this._turf.intersect(geojson1, geojson2);
      } catch (e) {
        console.error('[AoTGeoCompatibility] intersection error:', e);
        return null;
      }
    }

    /**
     * Calculate distance between two points
     * @param {Array} from - [lng, lat]
     * @param {Array} to - [lng, lat]
     * @param {string} units
     * @returns {number}
     */
    distance(from, to, units = 'meters') {
      if (!this._turf) return 0;
      try {
        return this._turf.distance(from, to, { units: units });
      } catch (e) {
        return 0;
      }
    }

    /**
     * Simplify geometry
     * @param {Object} geojson
     * @param {number} tolerance
     * @param {Object} options
     * @returns {Object}
     */
    simplify(geojson, tolerance, options = {}) {
      if (!this._turf) return geojson;
      try {
        return this._turf.simplify(geojson, Object.assign({
          tolerance: tolerance,
          highQuality: true
        }, options));
      } catch (e) {
        return geojson;
      }
    }

    /**
     * Smooth geometry
     * @param {Object} geojson
     * @param {Object} options
     * @returns {Object}
     */
    smooth(geojson, options = {}) {
      if (!this._turf) return geojson;
      try {
        return this._turf.smooth(geojson, options);
      } catch (e) {
        return geojson;
      }
    }

    // ========== Coordinate System Conversion (EPSG:4326 <-> EPSG:5179) ==========

    /**
     * Convert EPSG:5179 (Korea Central Belt) to EPSG:4326 (WGS84)
     * Simplified conversion using proj4js if available
     * @param {number} x - Easting (EPSG:5179)
     * @param {number} y - Northing (EPSG:5179)
     * @returns {Array} [lng, lat] (EPSG:4326)
     */
    static proj5179To4326(x, y) {
      // If proj4 is available, use it
      if (typeof global.proj4 !== 'undefined') {
        const result = global.proj4('EPSG:5179', 'EPSG:4326', [x, y]);
        return result;
      }

      // Fallback: approximate conversion
      // This is a rough approximation and should be replaced with proper transformation
      console.warn('[AoTGeoCompatibility] proj4 not available, using approximate conversion');
      
      // Korea Central Belt (EPSG:5179) to WGS84 (EPSG:4326)
      // Approximate parameters
      const deltaX = -115.74;
      const deltaY = 474.99;
      const deltaZ = -413.36;
      const scaleFactor = 0.99999579;
      const rotationAlpha = -0.0000004788;
      const rotationBeta = 0.0000001929;
      const rotationGamma = 0.0000002195;

      // Simplified transformation
      const dx = x - 500000; // Remove false easting
      const adjustedX = x * scaleFactor + deltaX + rotationAlpha * y - rotationBeta * (y - 600000);
      const adjustedY = y * scaleFactor + deltaY + rotationBeta * dx - rotationGamma * dx;
      
      // Rough approximation based on typical Korea region
      const baseLng = 127.0;
      const baseLat = 36.0;
      
      // This is highly inaccurate, recommend installing proj4
      return [
        baseLng + (x - 500000) * 0.00001,
        baseLat + (y - 600000) * 0.000008
      ];
    }

    /**
     * Convert EPSG:4326 (WGS84) to EPSG:5179 (Korea Central Belt)
     * @param {number} lng - Longitude
     * @param {number} lat - Latitude
     * @returns {Array} [x, y] (EPSG:5179)
     */
    static proj4326To5179(lng, lat) {
      // If proj4 is available, use it
      if (typeof global.proj4 !== 'undefined') {
        const result = global.proj4('EPSG:4326', 'EPSG:5179', [lng, lat]);
        return result;
      }

      // Fallback: approximate reverse conversion
      console.warn('[AoTGeoCompatibility] proj4 not available, using approximate reverse conversion');
      
      return [
        500000 + (lng - 127.0) * 100000,
        600000 + (lat - 36.0) * 125000
      ];
    }

    /**
     * Convert GeoJSON coordinates from EPSG:5179 to EPSG:4326
     * @param {Object} geojson
     * @returns {Object}
     */
    static convertGeoJSON5179To4326(geojson) {
      if (!geojson || !geojson.features) return geojson;

      const convertCoords = (coords) => {
        if (typeof coords[0] === 'number') {
          // [x, y] -> [lng, lat]
          return AoTGeoCompatibility.proj5179To4326(coords[0], coords[1]);
        }
        return coords.map(convertCoords);
      };

      return {
        ...geojson,
        features: geojson.features.map(feature => ({
          ...feature,
          geometry: {
            ...feature.geometry,
            coordinates: convertCoords(feature.geometry.coordinates)
          }
        }))
      };
    }

    /**
     * Convert GeoJSON coordinates from EPSG:4326 to EPSG:5179
     * @param {Object} geojson
     * @returns {Object}
     */
    static convertGeoJSON4326To5179(geojson) {
      if (!geojson || !geojson.features) return geojson;

      const convertCoords = (coords) => {
        if (typeof coords[0] === 'number') {
          // [lng, lat] -> [x, y]
          return AoTGeoCompatibility.proj4326To5179(coords[0], coords[1]);
        }
        return coords.map(convertCoords);
      };

      return {
        ...geojson,
        features: geojson.features.map(feature => ({
          ...feature,
          geometry: {
            ...feature.geometry,
            coordinates: convertCoords(feature.geometry.coordinates)
          }
        }))
      };
    }

    // ========== GeoJSON Utilities ==========

    /**
     * Ensure GeoJSON is a FeatureCollection
     * @param {Object} geojson
     * @returns {Object}
     */
    static ensureFeatureCollection(geojson) {
      if (!geojson) {
        return { type: 'FeatureCollection', features: [] };
      }
      if (geojson.type === 'FeatureCollection') {
        return geojson;
      }
      if (geojson.type === 'Feature') {
        return { type: 'FeatureCollection', features: [geojson] };
      }
      return { type: 'FeatureCollection', features: [] };
    }

    /**
     * Get feature by ID
     * @param {Object} geojson
     * @param {string} id
     * @returns {Object|null}
     */
    static getFeatureById(geojson, id) {
      const fc = AoTGeoCompatibility.ensureFeatureCollection(geojson);
      return fc.features.find(f => 
        f.id === id || 
        f.properties?.id === id || 
        f.properties?.node_id === id
      ) || null;
    }

    /**
     * Add or update feature in GeoJSON
     * @param {Object} geojson
     * @param {Object} feature
     * @returns {Object}
     */
    static upsertFeature(geojson, feature) {
      const fc = AoTGeoCompatibility.ensureFeatureCollection(geojson);
      const idx = fc.features.findIndex(f => 
        f.id === feature.id || 
        f.properties?.id === feature.id ||
        f.properties?.node_id === feature.properties?.node_id
      );

      if (idx >= 0) {
        fc.features[idx] = feature;
      } else {
        fc.features.push(feature);
      }

      return fc;
    }

    /**
     * Remove feature from GeoJSON by ID
     * @param {Object} geojson
     * @param {string} id
     * @returns {Object}
     */
    static removeFeatureById(geojson, id) {
      const fc = AoTGeoCompatibility.ensureFeatureCollection(geojson);
      fc.features = fc.features.filter(f => 
        f.id !== id && 
        f.properties?.id !== id && 
        f.properties?.node_id !== id
      );
      return fc;
    }

    /**
     * Filter features by property
     * @param {Object} geojson
     * @param {string} key
     * @param {*} value
     * @returns {Object}
     */
    static filterByProperty(geojson, key, value) {
      const fc = AoTGeoCompatibility.ensureFeatureCollection(geojson);
      return {
        type: 'FeatureCollection',
        features: fc.features.filter(f => f.properties && f.properties[key] === value)
      };
    }

    /**
     * Merge multiple FeatureCollections
     * @param {Array} collections
     * @returns {Object}
     */
    static merge(...collections) {
      const features = [];
      collections.forEach(col => {
        if (col && col.features) {
          features.push(...col.features);
        }
      });
      return { type: 'FeatureCollection', features: features };
    }

    /**
     * Validate GeoJSON
     * @param {Object} geojson
     * @returns {{valid: boolean, errors: Array}}
     */
    static validate(geojson) {
      const errors = [];

      if (!geojson) {
        errors.push('GeoJSON is null or undefined');
        return { valid: false, errors };
      }

      if (geojson.type === 'FeatureCollection') {
        if (!Array.isArray(geojson.features)) {
          errors.push('FeatureCollection must have features array');
        }
      } else if (geojson.type !== 'Feature') {
        errors.push('GeoJSON must be FeatureCollection or Feature');
      }

      return { valid: errors.length === 0, errors };
    }
  }

  // Export
  global.AoTGeoCompatibility = AoTGeoCompatibility;

  // Static properties for coordinate system reference
  AoTGeoCompatibility.CRS = {
    WGS84: 'EPSG:4326',
    KOREA_CENTRAL: 'EPSG:5179',
    WTM: 'EPSG:5186'
  };

})(typeof window !== 'undefined' ? window : global);
