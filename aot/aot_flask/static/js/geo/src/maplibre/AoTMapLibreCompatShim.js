/**
 * AoTMapLibreCompatShim.js
 * Leaflet API compatibility shim - provides the Leaflet API on top of MapLibre
 * 
 * @version 1.0.0
 * @author AoT Team
 * @requires AoTMapLibreCore, AoTMapLibreLayer, AoTGeoCompatibility
 */

(function(global) {
  'use strict';

  /**
   * AoTMapLibreCompatShim
   * Provides Leaflet-style L.* APIs using MapLibre underneath
   */
  class AoTMapLibreCompatShim {
    /**
     * Initialize the compatibility shim
     * @param {maplibregl.Map} map - MapLibre map instance
     */
    constructor(map) {
      this._map = map;
      this._initialized = false;
    }

    /**
     * Initialize shim
     */
    init() {
      if (this._initialized) return;
      this._setupLeafletNamespace();
      this._initialized = true;
    }

    /**
     * Leaflet eachLayer compatible method
     * Iterates MapLibre GL layers the Leaflet way
     * @param {Function} callback - callback to run for each layer
     */
    eachLayer(callback) {
      var style = this._map && this._map.getStyle ? this._map.getStyle() : null;
      if (style && style.layers) {
        style.layers.forEach(layer => {
          callback(layer);
        });
      }
      return this;
    }

    /**
     * Leaflet hasLayer() compatible - uses Shim._addedLayers
     * MapLibre has no hasLayer(), so use the layer set managed by the shim
     */
    hasLayer(layer) {
      if (!layer) return false;
      const id = typeof layer === 'string' ? layer : (layer._layerId || layer.id);
      return this._addedLayers && this._addedLayers.has(id);
    }

    /**
     * MapLibre GL isStyleLoaded polyfill
     * Checks whether the style has loaded
     */
    isStyleLoaded() {
      return this._map && this._map.isStyleLoaded ? this._map.isStyleLoaded() : false;
    }

    /**
     * Get underlying MapLibre map instance
     * @returns {maplibregl.Map} MapLibre map instance
     */
    getNativeMap() {
      return this._map;
    }

    /**
     * Leaflet getCenter() polyfill
     * MapLibre: { lng, lat } → Leaflet: { lat, lng }
     */
    getCenter() {
      var c = this._map && this._map.getCenter ? this._map.getCenter() : { lat: 0, lng: 0 };
      return { lat: c.lat, lng: c.lng };
    }

    /**
     * Leaflet getZoom() polyfill
     */
    getZoom() {
      return this._map && this._map.getZoom ? this._map.getZoom() : 0;
    }

    /**
     * Leaflet addLayer() compatible - uses MapLibre's addLayer/Source
     */
    addLayer(layer) {
      if (!layer) return this;
      const id = layer._layerId || layer.id || ('layer-' + Math.random().toString(36).substr(2, 9));
      
      // Register in Shim._addedLayers
      if (!this._addedLayers) this._addedLayers = new Map();
      this._addedLayers.set(id, layer);
      layer._map = this._map;
      
      // For an AoTGeoLayerGroup, add each child to MapLibre
      if (layer._layers instanceof Map) {
        layer._layers.forEach((l, lid) => this.addLayer(l));
        return this;
      }
      
      // Add source and layer to MapLibre
      if (this._map) {
        const mlMap = this._map._mlMap || this._map;
        
        // Skip if already added
        if (mlMap.getLayer(id)) return this;
        
        // For a GeoJSON layer, add the source first
        if (layer.toGeoJSON || layer.feature) {
          const sourceId = 'aot-source-' + id;
          if (!mlMap.getSource(sourceId)) {
            const geojson = layer.toGeoJSON ? layer.toGeoJSON() : layer.feature;
            mlMap.addSource(sourceId, { type: 'geojson', data: geojson });
          }
          const geomType = layer.geometry ? layer.geometry.type : (layer.feature ? layer.feature.geometry?.type : null);
          let layerType = 'circle';
          let paint = { 'circle-radius': 6, 'circle-color': '#3388ff' };
          if (geomType && geomType.includes('Line')) {
            layerType = 'line'; paint = { 'line-color': '#3388ff', 'line-width': 2 };
          } else if (geomType && geomType.includes('Polygon')) {
            layerType = 'fill'; paint = { 'fill-color': '#3388ff', 'fill-opacity': 0.3 };
          }
          mlMap.addLayer({ id, type: layerType, source: sourceId, paint });
        }
      }
      return this;
    }

    /**
     * Leaflet removeLayer() compatible - uses MapLibre's removeLayer/Source
     */
    removeLayer(layer) {
      if (!layer) return this;
      const id = typeof layer === 'string' ? layer : (layer._layerId || layer.id);
      
      // Remove from Shim._addedLayers
      if (this._addedLayers) this._addedLayers.delete(id);
      
      // For an AoTGeoLayerGroup, remove all child layers
      if (layer._layers instanceof Map) {
        layer._layers.forEach((l, lid) => this.removeLayer(l));
        return this;
      }
      
      // Remove from MapLibre
      if (this._map) {
        const mlMap = this._map._mlMap || this._map;
        if (mlMap.getLayer(id)) mlMap.removeLayer(id);
        const sourceId = 'aot-source-' + id;
        if (mlMap.getSource(sourceId)) mlMap.removeSource(sourceId);
      }
      return this;
    }

    /**
     * Leaflet getLayers() compatible - returns from Shim._addedLayers
     */
    getLayers() {
      if (!this._addedLayers) return [];
      return Array.from(this._addedLayers.values());
    }

    /**
     * Setup global L namespace with MapLibre-backed implementations
     * @private
     */
    _setupLeafletNamespace() {
      const self = this;

      // Ensure L namespace exists
      global.L = global.L || {};

      // ========== L.DomUtil ==========
      global.L.DomUtil = {
        addClass: function(el, className) {
          if (el && el.classList) {
            el.classList.add(className);
          }
        },
        removeClass: function(el, className) {
          if (el && el.classList) {
            el.classList.remove(className);
          }
        },
        hasClass: function(el, className) {
          return el && el.classList && el.classList.contains(className);
        },
        setPosition: function(el, position) {
          if (el && position) {
            el.style.left = position.x + 'px';
            el.style.top = position.y + 'px';
          }
        }
      };

      // ========== L.GeoJSON ==========
      global.L.GeoJSON = {
        coordsToLatLngs: function(coords, levelsDeep, reverse) {
          if (levelsDeep === undefined) levelsDeep = 0;
          if (reverse === undefined) reverse = false;
          
          let lat, lng;

          if (levelsDeep === 0) {
            if (!reverse) {
              return [coords[1], coords[0]]; // [lat, lng]
            }
            return [coords[0], coords[1]];
          }

          const result = [];
          for (let i = 0, len = coords.length; i < len; i++) {
            if (levelsDeep === 1 && !reverse) {
              // Polygon: coords[i] is ring [lng, lat]
              result.push([coords[i][1], coords[i][0]]);
            } else {
              result.push(this.coordsToLatLngs(coords[i], levelsDeep - 1, reverse));
            }
          }
          return result;
        },

        coordsToLatLng: function(coords, reverse) {
          if (reverse === undefined) reverse = false;
          if (reverse) {
            return [coords[0], coords[1]];
          }
          return [coords[1], coords[0]];
        },

        latLngToCoords: function(latlng, reverse) {
          if (reverse === undefined) reverse = false;
          if (reverse) {
            return [latlng.lat, latlng.lng];
          }
          return [latlng.lng, latlng.lat];
        },

        latLngsToCoords: function(latlngs, levelsDeep, closed) {
          if (levelsDeep === undefined) levelsDeep = 0;
          if (closed === undefined) closed = false;
          
          const coords = [];
          for (let i = 0, len = latlngs.length; i < len; i++) {
            if (levelsDeep > 0) {
              coords.push(this.latLngsToCoords(latlngs[i], levelsDeep - 1, closed));
            } else {
              coords.push([latlngs[i].lng || latlngs[i][1], latlngs[i].lat || latlngs[i][0]]);
            }
          }
          
          // Close the ring for polygons
          if (closed && levelsDeep > 0) {
            const first = coords[0];
            const last = coords[coords.length - 1];
            if (first[0] !== last[0] || first[1] !== last[1]) {
              coords.push(coords[0]);
            }
          }
          
          return coords;
        }
      };

      // ========== L.Draw.Event ==========
      global.L.Draw = global.L.Draw || {};
      global.L.Draw.Event = {
        CREATED: 'draw:created',
        EDITED: 'draw:edited',
        DELETED: 'draw:deleted',
        DRAWSTART: 'draw:drawstart',
        DRAWSTOP: 'draw:drawstop',
        EDITSTART: 'draw:editstart',
        EDITSTOP: 'draw:editstop',
        DELETESTART: 'draw:deletestart',
        DELETESTOP: 'draw:deletestop'
      };

      // ========== L.layerGroup ==========
      global.L.layerGroup = function(layers) {
        return {
          _layers: [],
          addLayer: function(layer) {
            this._layers.push(layer);
            if (layer.addTo && self._map) {
              layer.addTo(self._map);
            }
            return this;
          },
          removeLayer: function(layer) {
            this._layers = this._layers.filter(l => l !== layer);
            if (layer.remove) layer.remove();
            return this;
          },
          clearLayers: function() {
            this._layers.forEach(l => {
              if (l.remove) l.remove();
            });
            this._layers = [];
            return this;
          },
          getLayers: function() {
            return this._layers;
          },
          eachLayer: function(fn) {
            this._layers.forEach(l => fn(l));
            return this;
          },
          getLayer: function(id) {
            return this._layers.find(l => l._leaflet_id === id) || null;
          },
          hasLayer: function(layer) {
            return this._layers.includes(layer);
          },
          addTo: function(map) {
            this._map = map;
            this._layers.forEach(l => {
              if (l.addTo) l.addTo(map);
            });
            return this;
          }
        };
      };

      // ========== L.featureGroup ==========
      global.L.featureGroup = function(layers) {
        const group = global.L.layerGroup(layers);
        // Add getBounds method for AoTGeoDesign compatibility
        group.getBounds = function() {
          const bounds = [];
          this._layers.forEach(l => {
            if (l.getBounds) {
              const b = l.getBounds();
              if (b && b.isValid && b.isValid()) bounds.push(b);
            }
          });

          if (bounds.length === 0) return null;

          let minLng = Infinity, minLat = Infinity;
          let maxLng = -Infinity, maxLat = -Infinity;

          bounds.forEach(b => {
            const sw = b.getSouthWest(), ne = b.getNorthEast();
            minLng = Math.min(minLng, sw.lng);
            maxLng = Math.max(maxLng, ne.lng);
            minLat = Math.min(minLat, sw.lat);
            maxLat = Math.max(maxLat, ne.lat);
          });

          return {
            _southWest: { lat: minLat, lng: minLng },
            _northEast: { lat: maxLat, lng: maxLng },
            getSouthWest: function() { return this._southWest; },
            getNorthEast: function() { return this._northEast; },
            isValid: function() { return minLng !== Infinity; }
          };
        };

        return group;
      };

      // ========== L.FeatureGroup Class (for new L.FeatureGroup()) ==========
      global.L.FeatureGroup = class LeafletFeatureGroup {
        constructor() {
          this._layers = new Map();
          this._map = null;
          this._leaflet_id = global.L.stamp ? global.L.stamp(this) : Math.random().toString(36).substr(2, 9);
        }

        addLayer(layer) {
          if (!layer) return this;
          const id = layer._leaflet_id || layer._layerId || Math.random().toString(36).substr(2, 9);
          layer._leaflet_id = id;
          this._layers.set(id, layer);
          if (this._map && layer.addTo) {
            layer.addTo(this._map);
          }
          return this;
        }

        removeLayer(layer) {
          if (!layer) return this;
          const id = typeof layer === 'string' ? layer : (layer._leaflet_id || layer._layerId);
          this._layers.delete(id);
          if (layer.remove) layer.remove();
          return this;
        }

        clearLayers() {
          this._layers.forEach(l => {
            if (l.remove) l.remove();
          });
          this._layers.clear();
          return this;
        }

        getLayer(id) {
          return this._layers.get(id);
        }

        getLayers() {
          return Array.from(this._layers.values());
        }

        hasLayer(layer) {
          if (!layer) return false;
          const id = typeof layer === 'string' ? layer : (layer._leaflet_id || layer._layerId);
          return this._layers.has(id);
        }

        eachLayer(fn, context) {
          this._layers.forEach((l, id) => {
            try {
              fn.call(context || this, l);
            } catch (e) {}
          });
          return this;
        }

        addTo(map) {
          this._map = map;
          this._layers.forEach(l => {
            if (l.addTo) l.addTo(map);
          });
          return this;
        }

        getBounds() {
          const bounds = [];
          this._layers.forEach(l => {
            if (l.getBounds) {
              const b = l.getBounds();
              if (b && b.isValid && b.isValid()) bounds.push(b);
            }
          });

          if (bounds.length === 0) return null;

          let minLng = Infinity, minLat = Infinity;
          let maxLng = -Infinity, maxLat = -Infinity;

          bounds.forEach(b => {
            const sw = b.getSouthWest(), ne = b.getNorthEast();
            minLng = Math.min(minLng, sw.lng);
            maxLng = Math.max(maxLng, ne.lng);
            minLat = Math.min(minLat, sw.lat);
            maxLat = Math.max(maxLat, ne.lat);
          });

          return {
            _southWest: { lat: minLat, lng: minLng },
            _northEast: { lat: maxLat, lng: maxLng },
            getSouthWest: function() { return this._southWest; },
            getNorthEast: function() { return this._northEast; },
            isValid: function() { return minLng !== Infinity; }
          };
        }
      };

      // ========== L.Circle ==========
      global.L.Circle = class LeafletCircle {
        constructor(latlng, options = {}) {
          this._latlng = latlng;
          this._radius = options.radius || 100;
          this._options = options;
          this._map = null;
          this._layer = null;
          this._feature = {
            type: 'Feature',
            geometry: {
              type: 'Point',
              coordinates: [latlng.lng, latlng.lat]
            },
            properties: {
              radius: this._radius,
              is_circle: true,
              ...options
            }
          };
        }

        addTo(map) {
          this._map = map;
          // Create a circle using turf.js
          if (global.turf) {
            const circle = global.turf.circle(
              [this._latlng.lng, this._latlng.lat],
              this._radius,
              { steps: 64, units: 'meters' }
            );
            this._feature = circle;
            this._feature.properties = {
              ...this._feature.properties,
              ...this._options,
              is_circle: true,
              center: [this._latlng.lng, this._latlng.lat],
              radius: this._radius
            };
          }
          return this;
        }

        getLatLng() { return this._latlng; }
        getRadius() { return this._radius; }
        setRadius(r) { this._radius = r; return this; }
        
        toGeoJSON() { return this._feature; }
        remove() { return this; }
        
        getBounds() {
          if (!global.turf) return null;
          const buffered = global.turf.circle(
            [this._latlng.lng, this._latlng.lat],
            this._radius,
            { steps: 32, units: 'meters' }
          );
          const bbox = global.turf.bbox(buffered);
          return {
            _southWest: { lat: bbox[1], lng: bbox[0] },
            _northEast: { lat: bbox[3], lng: bbox[2] },
            getSouthWest: function() { return this._southWest; },
            getNorthEast: function() { return this._northEast; },
            isValid: function() { return true; }
          };
        }
      };

      // ========== L.CircleMarker ==========
      global.L.circleMarker = function(latlng, options = {}) {
        return {
          _latlng: latlng,
          _options: options,
          _map: null,
          feature: {
            type: 'Feature',
            geometry: {
              type: 'Point',
              coordinates: [latlng.lng || latlng[1], latlng.lat || latlng[0]]
            },
            properties: options
          },
          addTo: function(map) {
            this._map = map;
            return this;
          },
          getLatLng: function() { return this._latlng; },
          setLatLng: function(latlng) {
            this._latlng = latlng;
            this.feature.geometry.coordinates = [latlng.lng || latlng[1], latlng.lat || latlng[0]];
            return this;
          },
          setRadius: function(r) {
            this._options.radius = r;
            this.feature.properties.radius = r;
            return this;
          },
          setStyle: function(style) {
            this._options = { ...this._options, ...style };
            this.feature.properties = { ...this.feature.properties, ...style };
            return this;
          },
          toGeoJSON: function() { return this.feature; },
          remove: function() { return this; }
        };
      };

      // ========== L.marker ==========
      global.L.marker = function(latlng, options = {}) {
        return {
          _latlng: latlng,
          _options: options,
          _map: null,
          _icon: options.icon || null,
          feature: {
            type: 'Feature',
            geometry: {
              type: 'Point',
              coordinates: [latlng.lng || latlng[1], latlng.lat || latlng[0]]
            },
            properties: options
          },
          addTo: function(map) {
            this._map = map;
            return this;
          },
          getLatLng: function() { return this._latlng; },
          setLatLng: function(latlng) {
            this._latlng = latlng;
            this.feature.geometry.coordinates = [latlng.lng || latlng[1], latlng.lat || latlng[0]];
            return this;
          },
          setIcon: function(icon) {
            this._icon = icon;
            return this;
          },
          bindPopup: function(content) {
            this._popupContent = content;
            return this;
          },
          bindTooltip: function(content) {
            this._tooltipContent = content;
            return this;
          },
          openPopup: function() {
            if (this._popupContent && this._map) {
              // _latlng may be an array [lat, lng] or an object {lat, lng}
              const ll = this._latlng;
              const pLng = ll.lng !== undefined ? ll.lng : ll[1];
              const pLat = ll.lat !== undefined ? ll.lat : ll[0];
              new maplibregl.Popup()
                .setLngLat([pLng, pLat])
                .setHTML(typeof this._popupContent === 'function' ? this._popupContent() : this._popupContent)
                .addTo(this._map);
            }
            return this;
          },
          toGeoJSON: function() { return this.feature; },
          remove: function() { return this; }
        };
      };

      // ========== L.divIcon ==========
      global.L.divIcon = function(options = {}) {
        return {
          options: options,
          createIcon: function() {
            const el = document.createElement('div');
            if (options.className) el.className = options.className;
            if (options.html) el.innerHTML = options.html;
            if (options.iconSize) {
              el.style.width = options.iconSize[0] + 'px';
              el.style.height = options.iconSize[1] + 'px';
            }
            if (options.iconAnchor) {
              el.style.marginLeft = -options.iconAnchor[0] + 'px';
              el.style.marginTop = -options.iconAnchor[1] + 'px';
            }
            return el;
          },
          createShadow: function() {
            return this.createIcon();
          }
        };
      };

      // ========== L.polyline ==========
      global.L.polyline = function(latlngs, options = {}) {
        return {
          _latlngs: latlngs,
          _options: options,
          _map: null,
          feature: {
            type: 'Feature',
            geometry: {
              type: 'LineString',
              coordinates: latlngs.map(ll => [ll.lng || ll[1], ll.lat || ll[0]])
            },
            properties: options
          },
          addTo: function(map) {
            this._map = map;
            return this;
          },
          getLatLngs: function() { return this._latlngs; },
          setLatLngs: function(latlngs) {
            this._latlngs = latlngs;
            this.feature.geometry.coordinates = latlngs.map(ll => [ll.lng || ll[1], ll.lat || ll[0]]);
            return this;
          },
          setStyle: function(style) {
            this._options = { ...this._options, ...style };
            this.feature.properties = { ...this.feature.properties, ...style };
            return this;
          },
          toGeoJSON: function() { return this.feature; },
          remove: function() { return this; }
        };
      };

      // ========== L.polygon ==========
      global.L.polygon = function(latlngs, options = {}) {
        const poly = global.L.polyline(latlngs, options);
        poly.feature.geometry.type = 'Polygon';
        
        // Close the ring if not already closed
        const coords = poly.feature.geometry.coordinates;
        if (coords.length > 0) {
          const ring = coords[0];
          const first = ring[0];
          const last = ring[ring.length - 1];
          if (first[0] !== last[0] || first[1] !== last[1]) {
            ring.push([...first]);
          }
        }
        
        return poly;
      };

      // ========== L.geoJSON ==========
      global.L.geoJSON = function(geojson, options = {}) {
        const self2 = this;
        
        const layer = {
          _geojson: geojson,
          _options: options,
          _layers: [],
          _map: null,
          feature: geojson,
          
          addTo: function(map) {
            this._map = map;
            
            // Create layers for each feature based on geometry type
            if (geojson && geojson.features) {
              geojson.features.forEach((feat, idx) => {
                let layer2;
                const geomType = feat.geometry.type;
                const coords = feat.geometry.coordinates;
                
                // Convert coordinates to Leaflet format
                let latlngs;
                
                if (geomType === 'Point') {
                  latlngs = [coords[1], coords[0]];
                  layer2 = global.L.circleMarker(latlngs, feat.properties);
                } else if (geomType === 'LineString') {
                  latlngs = coords.map(c => [c[1], c[0]]);
                  layer2 = global.L.polyline(latlngs, feat.properties);
                } else if (geomType === 'Polygon') {
                  latlngs = coords[0].map(c => [c[1], c[0]]);
                  layer2 = global.L.polygon(latlngs, feat.properties);
                }
                
                if (layer2) {
                  layer2.feature = feat;
                  this._layers.push(layer2);
                  
                  // Call pointToLayer if provided
                  if (options.pointToLayer) {
                    layer2 = options.pointToLayer(feat, latlngs, layer2) || layer2;
                  }
                  
                  // Call onEachFeature if provided
                  if (options.onEachFeature) {
                    options.onEachFeature(feat, layer2);
                  }
                }
              });
            }
            
            return this;
          },
          
          getLayers: function() {
            return this._layers;
          },
          
          getLayer: function(id) {
            return this._layers.find(l => l._leaflet_id === id) || null;
          },
          
          eachLayer: function(fn) {
            this._layers.forEach(l => fn(l));
            return this;
          },
          
          toGeoJSON: function() { return this._geojson; },
          
          remove: function() {
            this._layers.forEach(l => l.remove && l.remove());
            return this;
          }
        };
        
        return layer;
      };

      // ========== L.point ==========
      global.L.point = function(x, y, round) {
        return {
          x: round ? Math.round(x) : x,
          y: round ? Math.round(y) : y
        };
      };

      // ========== L.DomEvent ==========
      global.L.DomEvent = {
        stopPropagation: function(e) {
          if (e && e.stopPropagation) e.stopPropagation();
        },
        preventDefault: function(e) {
          if (e && e.preventDefault) e.preventDefault();
        },
        addListener: function(el, type, fn) {
          if (el.addEventListener) {
            el.addEventListener(type, fn, false);
          } else if (el.attachEvent) {
            el.attachEvent('on' + type, fn);
          }
          return this;
        },
        removeListener: function(el, type, fn) {
          if (el.removeEventListener) {
            el.removeEventListener(type, fn, false);
          } else if (el.detachEvent) {
            el.detachEvent('on' + type, fn);
          }
          return this;
        },
        on: function(el, type, fn) {
          return this.addListener(el, type, fn);
        },
        off: function(el, type, fn) {
          return this.removeListener(el, type, fn);
        },
        disableScrollPropagation: function(el) {
          // Polyfill for Leaflet's L.DomEvent.disableScrollPropagation
          if (el) {
            this.on(el, 'mousewheel', this.stopPropagation);
            this.on(el, 'DOMMouseScroll', this.stopPropagation);
          }
          return this;
        },
        disableClickPropagation: function(el) {
          // Polyfill for Leaflet's L.DomEvent.disableClickPropagation
          if (el) {
            this.on(el, 'click', this.stop);
            this.on(el, 'mousedown', this.stop);
            this.on(el, 'touchstart', this.stop);
          }
          return this;
        }
      };

      // ========== L.latLngBounds ==========
      global.L.latLngBounds = function(latlngs) {
        let minLat = Infinity, maxLat = -Infinity;
        let minLng = Infinity, maxLng = -Infinity;
        
        latlngs.forEach(ll => {
          const lat = ll.lat || ll[0];
          const lng = ll.lng || ll[1];
          minLat = Math.min(minLat, lat);
          maxLat = Math.max(maxLat, lat);
          minLng = Math.min(minLng, lng);
          maxLng = Math.max(maxLng, lng);
        });
        
        return {
          _southWest: { lat: minLat, lng: minLng },
          _northEast: { lat: maxLat, lng: maxLng },
          getSouthWest: function() { return this._southWest; },
          getNorthEast: function() { return this._northEast; },
          isValid: function() { return minLat !== Infinity; }
        };
      };

      // ========== L.latLng ==========
      global.L.latLng = function(lat, lng) {
        return { lat: lat, lng: lng };
      };

      // ========== L.Control ==========
      global.L.Control = class LeafletControl {
        constructor(options) {
          this.options = options || {};
          this._container = null;
        }

        getPosition() {
          return this.options.position || 'topright';
        }

        setPosition(position) {
          this.options.position = position;
          return this;
        }

        addTo(map) {
          this._map = map;
          this.onAdd(map);
          return this;
        }

        onAdd(map) {
          this._container = global.L.DomUtil.create('div', 'leaflet-control');
          return this._container;
        }

        onRemove(map) {
          if (this._container && this._container.parentNode) {
            this._container.parentNode.removeChild(this._container);
          }
        }
      };

      // ========== L.Control.extend (for creating custom controls) ==========
      global.L.Control.extend = function(childDef) {
        const parentDef = global.L.Control;

        class ExtendedControl extends parentDef {
          constructor(options) {
            super(options);
            // Initialize child-specific options
          }
        }

        // Copy prototype methods from childDef
        Object.keys(childDef).forEach(key => {
          if (key !== 'constructor') {
            ExtendedControl.prototype[key] = childDef[key];
          }
        });

        return ExtendedControl;
      };

      // ========== L.Draw (for compatibility with draw events) ==========
      global.L.Draw = global.L.Draw || {};
      global.L.Draw.Event = {
        CREATED: 'draw:created',
        EDITED: 'draw:edited',
        DELETED: 'draw:deleted',
        DRAWSTART: 'draw:drawstart',
        DRAWSTOP: 'draw:drawstop',
        EDITSTART: 'draw:editstart',
        EDITSTOP: 'draw:editstop',
        DELETESTART: 'draw:deletestart',
        DELETESTOP: 'draw:deletestop'
      };

      // ========== L.tileLayer ==========
      global.L.tileLayer = {
        quadKey: function(url, options) {
          return {
            addTo: function(map) {
              // MapLibre handles this differently
              return this;
            },
            remove: function() { return this; }
          };
        }
      };

      // ========== L.map (Fallback - wraps MapLibre map) ==========
      global.L.map = function(containerId, options) {
        console.warn('[AoTMapLibreCompatShim] L.map fallback used - MapLibre map should be initialized instead');
        const mapInstance = global.AoTMapLibre?.map || (global.AoTMapLibre && global.AoTMapLibre.init ? global.AoTMapLibre.init(containerId, options) : null);
        if (!mapInstance) {
          // Create minimal fallback
          return {
            _map: null,
            setView: function() { return this; },
            addLayer: function() { return this; },
            on: function() { return this; },
            getCenter: function() { return { lat: 37.5665, lng: 126.9780 }; },
            getZoom: function() { return 13; },
            eachLayer: function(callback) {
              // In MapLibre GL, use getStyle().layers
              if (this._map && this._map.getStyle && this._map.getStyle().layers) {
                this._map.getStyle().layers.forEach(layer => {
                  callback(layer);
                });
              }
              return this;
            },
            remove: function() { return this; }
          };
        }
        // Wrap mapInstance with eachLayer support
        mapInstance._map = mapInstance;
        mapInstance.eachLayer = function(callback) {
          if (this._map && this._map.getStyle && this._map.getStyle().layers) {
            this._map.getStyle().layers.forEach(layer => {
              callback(layer);
            });
          }
          return this;
        };
        return mapInstance;
      };

    }

    /**
     * Destroy the shim
     */
    destroy() {
      // Cleanup if needed
      this._initialized = false;
    }
  }

  // Export
  global.AoTMapLibreCompatShim = AoTMapLibreCompatShim;

})(typeof window !== 'undefined' ? window : global);
