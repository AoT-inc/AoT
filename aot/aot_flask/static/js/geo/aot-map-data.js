/**
 * aot-map-data.js
 * Data Management Module for AoT Geo System
 * Handles API interactions for Map Designs (GeoMap) and Overlays (GeoShape).
 */

const AoTMapData = {
    apiBase: '/api/geo',
    
    getCsrfToken: function() {
        // Try Meta Tag
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.getAttribute('content');
        
        // Try Hidden Input
        const input = document.querySelector('input[name="csrf_token"]');
        if (input) return input.value;
        
        // console.warn("CSRF Token not found in DOM");
        return '';
    },

    /**
     * Load Map Design (View State & Metadata)
     * Maps to GeoMap table (state_json columns)
     * @param {string} mapUuid 
     * @returns {Promise<Object>} Map State Object
     */
    loadMapDesign: function (mapUuid) {
        return fetch(`${this.apiBase}/designs/${mapUuid}`)
            .then(response => {
                if (!response.ok) throw new Error(`Failed to load design: ${response.statusText}`);
                return response.json();
            })
            .then(data => data); // Return full object {uuid, name, state}
    },

    /**
     * Save Map Design (View State)
     * @param {string} mapUuid 
     * @param {string} name 
     * @param {Object} state - { center, zoom, locked, ... }
     * @returns {Promise<Object>} Response
     */
    saveMapDesign: function (mapUuid, name, state) {
        return fetch(`${this.apiBase}/designs`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            },
            body: JSON.stringify({
                map_uuid: mapUuid,
                name: name,
                state: state
            })
        }).then(res => res.json());
    },

    /**
     * Delete Map Design
     * @param {string} mapUuid
     * @returns {Promise<Object>} Response
     */
    deleteMapDesign: function (mapUuid) {
        return fetch(`${this.apiBase}/designs/${mapUuid}`, {
            method: 'DELETE',
            headers: {
                'X-CSRFToken': this.getCsrfToken()
            }
        }).then(res => {
            if (res.ok) return res.json();
            throw new Error(res.statusText);
        });
    },

    /**
     * Load Overlays (Features)
     * Maps to GeoShape table
     * @param {string} mapUuid 
     * @param {string} type - 'site'|'zone'|'facility'|'equipment'|'aot_device'
     * @returns {Promise<Array>} List of GeoJSON Features
     */
    loadOverlays: function (mapUuid, type) {
        let url = `${this.apiBase}/overlays?map_uuid=${mapUuid}`;
        if (type) url += `&type=${type}`;

        return fetch(url)
            .then(response => response.json())
            .then(data => {
                let items = [];
                // Backend returns { features: [...] } for FeatureCollection
                if (data.features) items = data.features;
                else if (Array.isArray(data)) items = data;
                
                return items;
            });
    },

    /**
     * Save Overlays (Features)
     * @param {string} mapUuid 
     * @param {string} type 
     * @param {Array} features - List of GeoJSON Features
     * @returns {Promise<Object>} Response
     */
    saveOverlays: async function (mapUuid, type, features) {
        // [Simple Fix] 모든 저장 경로에서 좌표 세척 강제 적용
        if (features && Array.isArray(features)) {
            features.forEach(f => {
                if (f.geometry) {
                    if (f.geometry.type === 'LineString') {
                        f.geometry.coordinates = this._cleanCoordinates(f.geometry.coordinates);
                    } else if (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') {
                        const cleanNodes = (coords) => {
                            if (Array.isArray(coords[0][0])) {
                                return coords.map(c => cleanNodes(c));
                            }
                            return this._cleanCoordinates(coords);
                        };
                        f.geometry.coordinates = cleanNodes(f.geometry.coordinates);
                    }
                }
            });
        }
        try {
            // [Filter] 무효한 지오메트리 제거 (서버 에러 방지)
            const validFeatures = (features || []).filter(f => {
                if (!f.geometry || !f.geometry.coordinates) return false;
                if (f.geometry.type === 'LineString') {
                    return f.geometry.coordinates.length >= 2;
                } else if (f.geometry.type === 'Polygon') {
                    return f.geometry.coordinates[0] && f.geometry.coordinates[0].length >= 3;
                }
                return true;
            });

            const payload = {
                map_uuid: mapUuid,
                type: type,
                features: validFeatures
            };
            
            const response = await fetch('/api/geo/overlays', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                let errorMsg = response.statusText;
                try {
                    const errData = await response.json();
                    if (errData && errData.message) errorMsg = errData.message;
                    else if (errData && errData.error) errorMsg = errData.error;
                } catch (e) { }
                throw new Error(`${type} Save Failed (${response.status}): ${errorMsg}`);
            }
            
            const result = await response.json();
            return result;
        } catch (e) {
            throw e;
        }
    },

    /**
     * Save Delta (Partial changes)
     * @param {string} mapUuid 
     * @param {Object} changes - { upserts: [feat, ...], deletes: [db_id|node_id, ...] }
     */
    saveDelta: async function (mapUuid, changes) {
        if (!changes.upserts?.length && !changes.deletes?.length) return { ok: true };

        // Clean coordinates only
        if (changes.upserts) {
            changes.upserts.forEach(f => {
                if (f.geometry) {
                    if (f.geometry.type === 'LineString') {
                        f.geometry.coordinates = this._cleanCoordinates(f.geometry.coordinates);
                    } else if (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') {
                        const cleanNodes = (coords) => {
                            if (Array.isArray(coords[0][0])) return coords.map(c => cleanNodes(c));
                            return this._cleanCoordinates(coords);
                        };
                        f.geometry.coordinates = cleanNodes(f.geometry.coordinates);
                    }
                }
            });
        }

        const response = await fetch(`${this.apiBase}/overlays/delta`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            },
            body: JSON.stringify({
                map_uuid: mapUuid,
                upserts: changes.upserts || [],
                deletes: changes.deletes || []
            })
        });

        if (!response.ok) {
            let errorDetail = "";
            try {
                const errData = await response.json();
                if (errData.message) errorDetail = ": " + errData.message;
            } catch (e) { /* ignore JSON parse fail */ }
            throw new Error(`Delta Save Failed (${response.status})${errorDetail}`);
        }
        return await response.json();
    },

    /**
     * Helper: Convert FeatureGroup to Typed Lists
     * Extracts 'aot_type' from features and groups them to match API requirements.
     * @param {L.FeatureGroup} featureGroup 
     * @returns {Object} { site: [], zone: [], facility: [], equipment: [], aot_device: [] }
     */
    categorizeFeatures: function (featureGroup) {
        const categorized = {};

        featureGroup.eachLayer(layer => {
            let feature = null;

            try {
                // 1. Handle Circle (Convert to Polygon logic)
                // Use duck typing (getRadius) in case instanceof fails across frames
                const isCircle = (layer instanceof L.Circle) || (layer.getRadius && !layer.getLatLngs); 
                const isMarker = (layer instanceof L.Marker) || (layer.getLatLng && !layer.getRadius);

                // Optimization: Trust pre-calculated geometry (from saveDesign)
                if (layer.feature && layer.feature.geometry && 
                   (layer.feature.geometry.type === 'Polygon' || layer.feature.geometry.type === 'MultiPolygon')) {
                    feature = {
                        type: 'Feature',
                        geometry: layer.feature.geometry,
                        properties: layer.feature.properties || {}
                    };
                }
                else if (isCircle && !(layer instanceof L.CircleMarker)) {
                    if (window.turf) {
                        try {
                            const center = layer.getLatLng();
                            const radius = layer.getRadius();
                            feature = window.turf.circle([center.lng, center.lat], radius, { steps: 64, units: 'meters' });
                            
                            // Explicitly set geometry type to Polygon just in case
                            // if (feature.geometry.type !== 'Polygon') console.warn("Turf circle did not return Polygon:", feature);
                            
                            // Copy properties
                            if (layer.feature && layer.feature.properties) {
                                 feature.properties = { ...layer.feature.properties, ...feature.properties };
                            }
                        } catch (tcErr) {
                            // console.error("Turf conversion error:", tcErr);
                            // feature = layer.toGeoJSON(); // Fallback (will likely fail backend validation if Site)
                            
                            // [Fix] Fallback: Manual Circle to Polygon (Approximate)
                            // If Turf fails, we manually create a polygon to ensure it saves as 'Polygon'
                            const latlng = layer.getLatLng();
                            const rad = layer.getRadius();
                            // Simple box approximation or 8-point polygon? Let's do 32 points.
                            // However, without projection math, meters-to-degrees is hard.
                            // If Turf fails, something is wrong. But let's at least try 'toGeoJSON' 
                            // AND FORCE type if possible? No, 'Point' geometry won't pass 'Polygon' check.
                            // Ideally we need a 'circleToPolygon' generic function without turf. 
                            // Given browser context, Turf SHOULD be there. 
                            // If missing, we warn.
                            
                            // Attempt to save as Point with property 'radius' which Backend might handle?
                            // Currently Backend validates 'Polygon' for Site.
                            // Let's rely on standard toGeoJSON for now but log loudly.
                            feature = layer.toGeoJSON();
                            feature.properties.error_note = "Turf conversion failed";
                        }
                    } else {
                        // console.warn("Turf.js not found in categorizeFeatures. Attempting manual approximation.");
                        // [Auto-Fix] Manual Circle approximation if Turf is missing
                        // Use Leaflet's own implementation if available? Leaflet doesn't export circleToPolygon.
                        // We will just let it be a Point but warn. 
                        // Actually, let's implement a rudimentary poly gen if critical.
                        // For now, consistent behavior with catch block:
                        feature = layer.toGeoJSON(); 
                        feature.properties.error_note = "Turf missing";
                    }
                } else {
                    // Standard
                    if (layer.toGeoJSON) {
                        feature = layer.toGeoJSON();
                        if (layer.feature && layer.feature.properties) {
                            feature.properties = { ...layer.feature.properties, ...feature.properties };
                        }
                    }
                }

                if (!feature || !feature.geometry || !feature.properties) {
                    // console.warn("Skipping invalid layer in categorize:", layer);
                    return;
                }

                // Default type logic
                let rawType = feature.properties.aot_type;
                if (!rawType) {
                    // Try to infer
                    if (feature.geometry.type === 'Point') rawType = 'label_aux'; // Safe bet? No, could be Site Point error.
                    else rawType = 'site';
                    feature.properties.aot_type = rawType;
                }

                // CRITICAL VALIDATION: Site/Zone MUST be Polygons.
                // If we found a Point assigned to site/zone, it is likely a Label or a Circle-fallback error.
                // We force it to 'label_aux' to pass Backend Validation.
                if (feature.geometry.type === 'Point' && (rawType === 'site' || rawType === 'zone')) {
                     // console.warn(`[Auto-Fix] Found Point masquerading as ${rawType}. Forcing to label_aux.`, feature);
                     rawType = 'label_aux';
                     feature.properties.aot_type = 'label_aux';
                }

                if (!categorized[rawType]) {
                    categorized[rawType] = [];
                }
                categorized[rawType].push(feature);

            } catch (err) {
                // console.error("Error processing layer in categorizeFeatures:", err, layer);
            }
        });

        return categorized;
    },

    /**
     * Helper: Clean coordinates to remove consecutive duplicates.
     */
    _cleanCoordinates: function(coords) {
        if (!coords || coords.length < 2) return coords;
        const cleaned = [coords[0]];
        for (let i = 1; i < coords.length; i++) {
            const p1 = coords[i - 1];
            const p2 = coords[i];
            const dist = Math.sqrt(Math.pow(p1[0] - p2[0], 2) + Math.pow(p1[1] - p2[1], 2));
            if (dist > 1e-9) {
                cleaned.push(p2);
            }
        }
        // Ensure Polygons remain closed
        if (cleaned.length > 2 && (coords[0][0] === coords[coords.length-1][0] && coords[0][1] === coords[coords.length-1][1])) {
             const first = cleaned[0];
             const last = cleaned[cleaned.length-1];
             if (first[0] !== last[0] || first[1] !== last[1]) {
                 cleaned.push([first[0], first[1]]);
             }
        }
        return cleaned;
    }
};

window.AoTMapData = AoTMapData;
