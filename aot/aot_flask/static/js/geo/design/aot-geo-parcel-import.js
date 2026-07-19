// aot-geo-parcel-import.js
// VWorld address -> parcel polygon -> AoT Site conversion module
// @module AoTParcelImport
// @version 20260506a

const AoTParcelImport = {
    _previewFeatures: [],   // Array of GeoJSON Features currently being previewed
    _mapInstance: null,     // maplibre Map instance injected from outside
    SOURCE_ID: 'aot-parcel-preview',
    FILL_ID: 'aot-parcel-preview-fill',
    LINE_ID: 'aot-parcel-preview-line',

    /** Initialize: inject map instance */
    init: function(map) { this._mapInstance = map; },

    /** Look up parcel by a single address - API Key is automatically taken from the server VWorld GIS Input settings */
    searchAddress: async function(address) {
        const resp = await fetch('/api/geo/parcel/from_address', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': window._csrf || ''},
            body: JSON.stringify({address})
        });
        return resp.json();
    },

    /** Batch lookup from CSV file - API Key is automatically taken from the server VWorld GIS Input settings */
    uploadCsv: async function(file) {
        const fd = new FormData();
        fd.append('file', file);
        const resp = await fetch('/api/geo/parcel/from_csv', {
            method: 'POST',
            headers: {'X-CSRFToken': window._csrf || ''},
            body: fd
        });
        return resp.json();
    },

    /** Show preview layer on the map */
    showPreview: function(features) {
        this._previewFeatures = features;
        const map = this._mapInstance;
        if (!map) return;
        const geojson = {type: 'FeatureCollection', features: features};
        const doAdd = () => {
            if (map.getSource(this.SOURCE_ID)) {
                map.getSource(this.SOURCE_ID).setData(geojson);
            } else {
                map.addSource(this.SOURCE_ID, {type: 'geojson', data: geojson});
                map.addLayer({id: this.FILL_ID, type: 'fill', source: this.SOURCE_ID,
                    paint: {'fill-color': '#DF5353', 'fill-opacity': 0.25}});
                map.addLayer({id: this.LINE_ID, type: 'line', source: this.SOURCE_ID,
                    paint: {'line-color': '#DF5353', 'line-width': 2}});
            }
            // Move to the full extent
            if (features.length > 0) {
                try {
                    const bounds = features.reduce((b, f) => {
                        const coords = this._flatCoords(f.geometry);
                        coords.forEach(c => b.extend(c));
                        return b;
                    }, new maplibregl.LngLatBounds());
                    map.fitBounds(bounds, {padding: 60, maxZoom: 19});
                } catch(e) {}
            }
        };
        if (map.isStyleLoaded()) doAdd(); else map.once('load', doAdd);
    },

    /** Remove preview */
    clearPreview: function() {
        this._previewFeatures = [];
        const map = this._mapInstance;
        if (!map) return;
        try { if(map.getLayer(this.FILL_ID)) map.removeLayer(this.FILL_ID); } catch(e){}
        try { if(map.getLayer(this.LINE_ID)) map.removeLayer(this.LINE_ID); } catch(e){}
        try { if(map.getSource(this.SOURCE_ID)) map.removeSource(this.SOURCE_ID); } catch(e){}
    },

    /** Union adjacent polygons (turf.js v7 API: single featureCollection argument) */
    mergeAdjacent: function(features) {
        if (!window.turf || features.length <= 1) return features;
        try {
            // turf v7: union(FeatureCollection) - not (a, b) two args like v6
            const fc = turf.featureCollection(features.map(f => {
                // Only Polygon/MultiPolygon can be unioned - preserve properties
                return turf.feature(f.geometry, f.properties || {});
            }));
            const merged = turf.union(fc);
            if (!merged) throw new Error('union returned null');
            // Name: first parcel + N others
            const name = (features[0].properties && features[0].properties.name) || (window._ ? window._('Site') : 'Site');
            const extra = features.length > 1 ? ` ${window._ ? window._('and') : 'and'} ${features.length - 1} ${window._ ? window._('others') : 'others'}` : '';
            merged.properties = merged.properties || {};
            merged.properties.name = name + extra;
            return [merged];
        } catch(e) {
            console.warn('[AoTParcelImport] turf.union failed:', e);
            return features;
        }
    },

    /** Save as Site (single or merged result) */
    saveAsSite: async function(feature, name, mapUuid) {
        const resp = await fetch('/api/geo/parcel/save_as_site', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': window._csrf || ''},
            body: JSON.stringify({feature, name, map_uuid: mapUuid})
        });
        return resp.json();
    },

    /** Extract coordinate array from geometry (for bounds calculation) */
    _flatCoords: function(geometry) {
        if (!geometry) return [];
        const flatten = (arr) => {
            if (!Array.isArray(arr)) return [];
            if (typeof arr[0] === 'number') return [arr];
            return arr.flatMap(flatten);
        };
        return flatten(geometry.coordinates);
    }
};

window.AoTParcelImport = AoTParcelImport;
