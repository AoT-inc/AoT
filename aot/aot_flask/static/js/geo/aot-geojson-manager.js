/**
 * AoT GeoJSON Manager
 * Handles GeoJSON overlay layers (sites, zones, facilities) for MapLibre
 * 
 * @requires maplibregl
 */

(function(global) {
    'use strict';

    var AoTGeoJSONManager = function(map) {
        this.map = map;
        this.layers = {};
        this.sources = {};
        this.initialized = false;
    };

    /**
     * Initialize manager with a MapLibre map instance
     */
    AoTGeoJSONManager.prototype.init = function(map) {
        if (!map || typeof map.addSource !== 'function') {
            console.error('[AoTGeoJSONManager] Invalid map instance');
            return false;
        }
        this.map = map;
        this.initialized = true;
        console.log('[AoTGeoJSONManager] Initialized');
        return true;
    };

    /**
     * Add a GeoJSON layer from URL
     */
    AoTGeoJSONManager.prototype.addGeoJSONFromURL = function(layerId, url, options) {
        if (!this.initialized) {
            console.error('[AoTGeoJSONManager] Not initialized');
            return false;
        }

        options = options || {};
        var self = this;

        fetch(url)
            .then(function(response) {
                if (!response.ok) throw new Error('Network error');
                return response.json();
            })
            .then(function(geojson) {
                self.addGeoJSON(layerId, geojson, options);
            })
            .catch(function(err) {
                console.error('[AoTGeoJSONManager] Failed to load GeoJSON:', err);
            });

        return true;
    };

    /**
     * Add a GeoJSON layer from object
     */
    AoTGeoJSONManager.prototype.addGeoJSON = function(layerId, geojson, options) {
        if (!this.initialized) {
            console.error('[AoTGeoJSONManager] Not initialized');
            return false;
        }

        options = options || {};
        var sourceId = 'geojson-' + layerId;

        // Remove existing if present
        if (this.sources[layerId]) {
            this.removeLayer(layerId);
        }

        // Add source
        this.map.addSource(sourceId, {
            type: 'geojson',
            data: geojson
        });
        this.sources[layerId] = sourceId;

        // Determine geometry types present
        var hasPolygons = false;
        var hasLines = false;
        var hasPoints = false;

        if (geojson.features) {
            geojson.features.forEach(function(f) {
                if (f.geometry) {
                    var type = f.geometry.type;
                    if (type === 'Polygon' || type === 'MultiPolygon') hasPolygons = true;
                    if (type === 'LineString' || type === 'MultiLineString') hasLines = true;
                    if (type === 'Point' || type === 'MultiPoint') hasPoints = true;
                }
            });
        }

        var fillColor = options.fillColor || options.color || '#FF0000';
        var lineColor = options.lineColor || options.color || '#FF0000';
        var fillOpacity = options.fillOpacity !== undefined ? options.fillOpacity : 0.2;
        var lineWidth = options.lineWidth || 2;

        // Add fill layer for polygons
        if (hasPolygons) {
            this.map.addLayer({
                id: layerId + '-fill',
                type: 'fill',
                source: sourceId,
                filter: ['any', ['==', '$type', 'Polygon'], ['==', '$type', 'MultiPolygon']],
                paint: {
                    'fill-color': ['get', 'color'] || fillColor,
                    'fill-opacity': fillOpacity
                },
                layout: {
                    'visibility': options.visible !== false ? 'visible' : 'none'
                }
            });
        }

        // Add line layer for boundaries
        if (hasLines || hasPolygons) {
            this.map.addLayer({
                id: layerId + '-line',
                type: 'line',
                source: sourceId,
                filter: ['any', 
                    ['==', '$type', 'Polygon'], 
                    ['==', '$type', 'MultiPolygon'],
                    ['==', '$type', 'LineString'], 
                    ['==', '$type', 'MultiLineString']
                ],
                paint: {
                    'line-color': ['get', 'stroke'] || lineColor,
                    'line-width': lineWidth,
                    'line-dasharray': options.dashArray || [1]
                },
                layout: {
                    'visibility': options.visible !== false ? 'visible' : 'none'
                }
            });
        }

        // Add symbol layer for labels
        if (options.showLabels && hasPoints) {
            this.map.addLayer({
                id: layerId + '-label',
                type: 'symbol',
                source: sourceId,
                filter: ['==', '$type', 'Point'],
                layout: {
                    'text-field': ['get', options.labelField || 'name'],
                    'text-font': ['Noto Sans Regular'],
                    'text-size': 12,
                    'text-offset': [0, 1],
                    'text-anchor': 'top'
                },
                paint: {
                    'text-color': '#333',
                    'text-halo-color': '#fff',
                    'text-halo-width': 2
                }
            });
        }

        // Add circle layer for points
        if (hasPoints && !options.hidePoints) {
            this.map.addLayer({
                id: layerId + '-circle',
                type: 'circle',
                source: sourceId,
                filter: ['any', ['==', '$type', 'Point'], ['==', '$type', 'MultiPoint']],
                paint: {
                    'circle-color': fillColor,
                    'circle-radius': options.radius || 6,
                    'circle-stroke-color': '#fff',
                    'circle-stroke-width': 2
                }
            });
        }

        this.layers[layerId] = geojson;
        console.log('[AoTGeoJSONManager] Layer added:', layerId);
        return true;
    };

    /**
     * Update GeoJSON data
     */
    AoTGeoJSONManager.prototype.updateData = function(layerId, geojson) {
        if (!this.initialized) return false;
        
        var sourceId = this.sources[layerId];
        if (sourceId && this.map.getSource(sourceId)) {
            this.map.getSource(sourceId).setData(geojson);
            this.layers[layerId] = geojson;
            return true;
        }
        return false;
    };

    /**
     * Remove a layer
     */
    AoTGeoJSONManager.prototype.removeLayer = function(layerId) {
        if (!this.initialized) return false;

        var layerIds = [layerId + '-fill', layerId + '-line', layerId + '-label', layerId + '-circle'];
        
        layerIds.forEach(function(id) {
            if (this.map.getLayer(id)) {
                this.map.removeLayer(id);
            }
        }.bind(this));

        var sourceId = this.sources[layerId];
        if (sourceId && this.map.getSource(sourceId)) {
            this.map.removeSource(sourceId);
        }

        delete this.layers[layerId];
        delete this.sources[layerId];
        
        return true;
    };

    /**
     * Set layer visibility
     */
    AoTGeoJSONManager.prototype.setVisibility = function(layerId, visible) {
        if (!this.initialized) return false;

        var visibility = visible ? 'visible' : 'none';
        var layerIds = [layerId + '-fill', layerId + '-line', layerId + '-label'];

        layerIds.forEach(function(id) {
            if (this.map.getLayer(id)) {
                this.map.setLayoutProperty(id, 'visibility', visibility);
            }
        }.bind(this));

        return true;
    };

    /**
     * Highlight features
     */
    AoTGeoJSONManager.prototype.highlightFeature = function(layerId, featureId) {
        if (!this.initialized) return;

        // Store original colors, then highlight
        this._highlightedFeatures = this._highlightedFeatures || {};
        
        var sourceId = this.sources[layerId];
        if (!sourceId) return;

        var self = this;
        
        // Find and highlight feature
        var geojson = this.layers[layerId];
        if (geojson && geojson.features) {
            geojson.features.forEach(function(f) {
                if (f.id === featureId || f.properties?.id === featureId) {
                    self._highlightedFeatures[layerId] = f;
                    // Apply highlight style
                    if (self.map.getLayer(layerId + '-fill')) {
                        self.map.setPaintProperty(layerId + '-fill', 'fill-opacity', 0.5);
                    }
                    if (self.map.getLayer(layerId + '-line')) {
                        self.map.setPaintProperty(layerId + '-line', 'line-width', 4);
                    }
                }
            });
        }
    };

    /**
     * Clear all layers
     */
    AoTGeoJSONManager.prototype.clearAll = function() {
        var layerIds = Object.keys(this.layers);
        var self = this;
        
        layerIds.forEach(function(layerId) {
            self.removeLayer(layerId);
        });
    };

    // Export
    global.AoTGeoJSONManager = AoTGeoJSONManager;

    // Convenience function (ensure AoT namespace exists)
    global.AoT = global.AoT || {};
    global.AoT.loadGeoJSON = function(map, layerId, geojson, options) {
        var manager = new AoTGeoJSONManager(map);
        manager.init(map);
        manager.addGeoJSON(layerId, geojson, options);
        return manager;
    };

})(window);
