/**
 * aot-map-utils.js
 * Geometric Utilities for AoT Geo Design
 * Dependencies: Turf.js (window.turf)
 */

const AoTMapUtils = {

    /**
     * Checks if Turf.js is loaded
     */
    _checkTurf: function () {
        if (!window.turf) {
            // console.error("Turf.js is not loaded. Geometric operations will fail.");
            return false;
        }
        return true;
    },

    /**
     * Extend a line to the boundary of a polygon
     * @param {Feature<LineString>} line 
     * @param {Feature<Polygon>} boundary 
     * @returns {Feature<LineString>|null} Extended Line or null if no intersection
     */
    extendLineToBoundary: function (line, boundary) {
        if (!this._checkTurf()) return null;

        try {
            // 1. Get Line Coordinates
            const geom = line.geometry || line;
            const coords = geom.coordinates;
            if (!coords || !Array.isArray(coords) || coords.length < 2) return null;

            const start = coords[0];
            const end = coords[coords.length - 1];

            // 2. Extrapolate endpoints far enough to ensure intersection
            // Calculate bearing with validation
            const isValid = (p) => Array.isArray(p) && p.length >= 2 && typeof p[0] === 'number' && typeof p[1] === 'number';
            if (!isValidPt(start) || !isValidPt(end)) {
                // console.error("[GeoUtil] Malformed coordinates for bearing:", start, end);
                return null;
            }
            const bearing = window.turf.bearing(start, end);

            // Create a long line in both directions (e.g. 1km - enough for site scale)
            // We extend from the "end" forward, and from "start" backward
            const extDist = 1; // km

            const newEnd = window.turf.destination(end, extDist, bearing).geometry.coordinates;
            const newStart = window.turf.destination(start, extDist, bearing - 180).geometry.coordinates;

            const longLine = window.turf.lineString([newStart, newEnd]);

            // 3. Find Intersections with Boundary
            // Note: lineIntersect returns points where lines cross
            // We need to handle complex polygons (holes, concave)
            const intersects = window.turf.lineIntersect(longLine, boundary);

            if (!intersects || intersects.features.length < 2) {
                // console.warn("[GeoUtil] Cannot extend - fewer than 2 intersection points found.");
                return null;
            }

            // 4. Filter segment strictly inside the polygon
            // lineSplit might retain parts outside. 
            // Better approach: Use lineSplit on the longLine by the boundary
            // Then select the segment that is 'within' the polygon.

            // However, lineSplit with polygon is not direct in Turf v6. It splits Line by Line (polygon text).
            // Convert polygon to lines
            const boundaryLine = window.turf.polygonToLine(boundary);
            const split = window.turf.lineSplit(longLine, boundaryLine);

            if (!split || split.features.length === 0) return null;

            // Find the segment that contains the original center or is roughly inside
            // Or just check which segment is 'within' or contains original points?
            // "Trimming" logic acts here: We want the part INSIDE.

            let bestSegment = null;
            let maxLen = -1;

            split.features.forEach(seg => {
                // Check mid point of segment
                const mid = window.turf.midpoint(
                    window.turf.point(seg.geometry.coordinates[0]),
                    window.turf.point(seg.geometry.coordinates[seg.geometry.coordinates.length - 1])
                );

                if (window.turf.booleanPointInPolygon(mid, boundary)) {
                    // This segment is inside. 
                    // If multiple (concave), picking logic is complex. 
                    // For now, assume simple convex-ish or pick longest matching original vector logic.
                    // Or pick the one closest to original line? 
                    // Simpler: Just union all inside segments?

                    const len = window.turf.length(seg);
                    if (len > maxLen) {
                        maxLen = len;
                        bestSegment = seg;
                    }
                }
            });

            return bestSegment; // Returns the trimmed, extended line fitting inside

        } catch (e) {
            // console.error("[GeoUtil] extendLine Error:", e);
            return null;
        }
    },

    /**
     * Trim a line to fit within a polygon (Clipping)
     * @param {Feature<LineString>} line 
     * @param {Feature<Polygon>} boundary 
     * @returns {Feature<LineString>|FeatureCollection|null}
     */
    trimLine: function (line, boundary) {
        if (!this._checkTurf()) return null;
        try {
            // 1. Flatten MultiLineString input
            const geom = line.geometry || line;
            if (geom.type === 'MultiLineString') {
                const results = [];
                geom.coordinates.forEach(coords => {
                    const part = window.turf.lineString(coords);
                    const trimmed = this.trimLine(part, boundary);
                    if (trimmed) {
                        if (trimmed.type === 'FeatureCollection') {
                            trimmed.features.forEach(f => results.push(f));
                        } else {
                            results.push(trimmed);
                        }
                    }
                });
                if (results.length === 0) return null;
                return window.turf.featureCollection(results);
            }

            // 2. Initial check: Is the line completely inside or outside?
            const boundaryLine = window.turf.polygonToLine(boundary);
            const intersects = window.turf.lineIntersect(line, boundaryLine);

            if (intersects.features.length === 0) {
                // No intersections: strictly inside or strictly outside.
                // Check a sample point (midpoint)
                const mid = window.turf.along(line, window.turf.length(line, { units: 'kilometers' }) / 2, { units: 'kilometers' });
                if (window.turf.booleanPointInPolygon(mid, boundary)) {
                    return line;
                }
                return null;
            }

            // 3. Robust Split: Slice the line by the boundary
            const split = window.turf.lineSplit(line, boundaryLine);
            if (!split || split.features.length === 0) {
                // Edge case: if split fails despite intersections, fallback to boolean check on original
                return null;
            }

            // 4. Verify each segment
            const segmentsInside = [];
            split.features.forEach(seg => {
                const sLen = window.turf.length(seg);
                if (sLen < 0.0001) return; // Skip tiny noise segments

                // Check midpoint of this segment
                const mid = window.turf.along(seg, sLen / 2);
                if (window.turf.booleanPointInPolygon(mid, boundary)) {
                    segmentsInside.push(seg);
                }
            });

            if (segmentsInside.length === 0) return null;
            if (segmentsInside.length === 1) return segmentsInside[0];
            return window.turf.featureCollection(segmentsInside);

        } catch (e) {
            // console.error("[GeoUtil] trimLine Error:", e);
            return null;
        }
    },

    /**
     * Trim a line by another line (Intersection based)
     * Splits 'line' by 'cutter' and returns the valid segment.
     * @param {Feature<LineString>} line To be trimmed
     * @param {Feature<LineString>} cutter The cutting line
     * @param {string} keepSide 'longer'|'shorter' Default 'longer'
     */
    trimLineByLine: function (line, cutter, keepSide = 'longer') {
        if (!this._checkTurf()) return null;
        try {
            const split = window.turf.lineSplit(line, cutter);
            if (!split || split.features.length < 2) return line;

            let bestSeg = null;
            let targetLen = (keepSide === 'longer') ? -1 : Infinity;

            split.features.forEach(seg => {
                const len = window.turf.length(seg);
                if (keepSide === 'longer') {
                    if (len > targetLen) {
                        targetLen = len;
                        bestSeg = seg;
                    }
                } else {
                    if (len < targetLen) {
                        targetLen = len;
                        bestSeg = seg;
                    }
                }
            });

            return bestSeg || line;
        } catch (e) {
            // console.error("[GeoUtil] trimLineByLine Error:", e);
            return line;
        }
    },

    /**
     * Create Parallel Offset
     * @param {Feature<LineString>} line 
     * @param {number} distance (meters)
     * @returns {Feature<LineString>}
     */
    offsetLine: function (line, distance) {
        if (!this._checkTurf()) return null;
        try {
            // turf.lineOffset takes distance in units (default km)
            return window.turf.lineOffset(line, distance, { units: 'meters' });
        } catch (e) {
            // console.error("[GeoUtil] offsetLine Error:", e);
            return null;
        }
    },

    /**
     * Boolean Operations for Polygons
     * @param {string} op 'union'|'difference'|'intersect'
     * @param {Feature<Polygon>} poly1 
     * @param {Feature<Polygon>} poly2 
     */
    booleanOp: function (op, poly1, poly2) {
        if (!this._checkTurf()) return null;
        try {
            if (op === 'union') return window.turf.union(poly1, poly2);
            if (op === 'difference') return window.turf.difference(poly1, poly2);
            if (op === 'intersect') return window.turf.intersect(poly1, poly2);
            return null;
        } catch (e) {
            // console.error(`[GeoUtil] ${op} Error:`, e);
            return null;
        }
    },

    /**
     * Translate a feature (rigid body motion, visual parallelism)
     * @param {Feature} feature 
     * @param {number} distance (meters)
     * @param {number} bearing (degrees)
     */
    translateFeature: function (feature, distance, bearing) {
        if (!this._checkTurf()) return null;

        // 1. Handle Negative Distance
        let actualDist = distance;
        let actualBearing = bearing;
        if (distance < 0) {
            actualDist = Math.abs(distance);
            actualBearing = (bearing + 180) % 360;
        }

        // 2. Use Fixed-Vector Translation (Visual Parallelism)
        // Instead of calculating destination for every point (spherical distortion),
        // we find a common [dLng, dLat] shift based on the centroid.
        // This preserves the "Map Shape" exactly and maintains visual spacing.
        try {
            const centroid = window.turf.centroid(feature);
            const centerCoords = centroid.geometry.coordinates;
            const dest = window.turf.destination(centroid, actualDist, actualBearing, { units: 'meters' });

            const dLng = dest.geometry.coordinates[0] - centerCoords[0];
            const dLat = dest.geometry.coordinates[1] - centerCoords[1];

            const cloned = JSON.parse(JSON.stringify(feature));
            const walk = (coords) => {
                if (typeof coords[0] === 'number' && typeof coords[1] === 'number') {
                    // Apply common vector
                    coords[0] += dLng;
                    coords[1] += dLat;
                } else if (Array.isArray(coords)) {
                    coords.forEach(walk);
                }
            };

            const geom = cloned.geometry || cloned;
            if (geom.coordinates) {
                walk(geom.coordinates);
            } else if (cloned.features) { // FeatureCollection
                cloned.features.forEach(f => walk(f.geometry.coordinates));
            }

            return cloned;
        } catch (e) {
            // console.error("[GeoUtil] translateFeature Error:", e);
            return null;
        }
    },

    /**
     * Get Longest Edge of a Polygon
     * Used for Automatic Reference Line
     * @param {Feature<Polygon>} poly 
     * @returns {Feature<LineString>}
     */
    getLongestEdge: function (poly) {
        if (!this._checkTurf()) return null;
        try {
            let coords;
            const type = poly.geometry.type;

            if (type === 'Polygon') {
                coords = poly.geometry.coordinates[0]; // Outer ring
            } else if (type === 'LineString') {
                coords = poly.geometry.coordinates; // Line points
            } else {
                // console.warn("[GeoUtil] getLongestEdge: Unsupported type", type);
                return null;
            }

            let maxLen = -1;
            let bestEdge = null;

            for (let i = 0; i < coords.length - 1; i++) {
                const start = coords[i];
                const end = coords[i + 1];

                // Point validation for edge
                if (!start || !end || start.length < 2 || end.length < 2) continue;
                if (start[0] === end[0] && start[1] === end[1]) continue; // Skip zero-length edge

                const lineFeature = window.turf.lineString([start, end]);
                const len = window.turf.length(lineFeature, { units: 'meters' });

                if (len > maxLen) {
                    maxLen = len;
                    bestEdge = lineFeature;
                }
            }
            return bestEdge;
        } catch (e) {
            // console.error("[GeoUtil] getLongestEdge Error:", e);
            return null;
        }
    },

    /**
     * Extend a Polyline (LineString) to the boundaries of a Polygon.
     * Logic: Projects the start point backwards and end point forwards.
     * @param {Feature<LineString>} line 
     * @param {Feature<Polygon>} boundary 
     * @param {boolean} skipTrim If true, returns the huge extended line without clipping (for offset generation)
     * @param {number} fixedBearing Optional. If provided, used for both extensions (start and end).
     * @returns {Feature<LineString>|null} Extended LineString
     */
    extendPolylineToBoundary: function (line, boundary, skipTrim = false, fixedBearing = null) {
        if (!this._checkTurf()) return null;
        try {
            // Handle Feature vs Geometry
            const geom = line.geometry || line;
            const coords = geom.coordinates;
            if (!coords || coords.length < 2) return null;

            // 1. Extend Start Backward
            const startPt = coords[0];
            const nextPt = coords[1];

            // Point validation
            const isValidPt = (p) => Array.isArray(p) && p.length >= 2 && typeof p[0] === 'number' && typeof p[1] === 'number';
            if (!isValidPt(startPt) || !isValidPt(nextPt)) {
                // console.error("[GeoUtil] Malformed coordinates for extension:", startPt, nextPt);
                return null;
            }

            // Direction pointing OUT from start
            const startBearing = (fixedBearing !== null) ? (fixedBearing - 180) : window.turf.bearing(nextPt, startPt);
            const extStart = window.turf.destination(startPt, 1, startBearing, { units: 'kilometers' }).geometry.coordinates;

            // 2. Extend End Forward
            const endPt = coords[coords.length - 1];
            const prevPt = coords[coords.length - 2];

            if (!isValidPt(endPt) || !isValidPt(prevPt)) {
                // console.error("[GeoUtil] Malformed coordinates for extension:", prevPt, endPt);
                return null;
            }

            // Direction pointing OUT from end
            const endBearing = (fixedBearing !== null) ? fixedBearing : window.turf.bearing(prevPt, endPt);
            const extEnd = window.turf.destination(endPt, 1, endBearing, { units: 'kilometers' }).geometry.coordinates;

            // 3. Construct Full Extended Line
            // Original middle points + new extremes
            const newCoords = [extStart, ...coords, extEnd];
            const extendedLine = window.turf.lineString(newCoords);

            if (skipTrim) return extendedLine;

            // 4. Clip to Boundary (Trim)
            return this.trimLine(extendedLine, boundary);

        } catch (e) {
            // console.error("[GeoUtil] extendPolyline Error:", e);
            return null;
        }
    },
    /**
     * Calculate Statistics for features within a Polygon
     * @param {Feature<Polygon>} polygon 
     * @param {Object} layerStorage Access to all layers
     * @returns {Object} Stats { area, pipeMainLen, pipeBranchLen, emitters, input, output, function, waterUsage }
     */
    /**
     * Calculate Statistics for features within a Polygon
     * @param {Object|Array} layerStorage Access to all layers OR pre-filtered array of layers
     * @returns {Object} Stats { area, pipeMainLen, pipeBranchLen, emitters, input, output, function, waterUsage }
     */
    calculatePolygonStats: function (polygon, layerStorage) {
        if (!polygon || !polygon.geometry || !polygon.geometry.type) {
            return {
                area: 0, pipeMainLen: 0, pipeBranchLen: 0, pipeMainCount: 0, pipeBranchCount: 0,
                connections: { mT: 0, mE: 0, mC: 0, mbT: 0, bT: 0, bE: 0, bC: 0 },
                pipeDetails: [], objects: { pipes: [], sprinklers: [] },
                emitters: 0, input: 0, output: 0, function: 0, waterUsage: 0
            };
        }
        if (!this._checkTurf()) return null;

        const stats = {
            area: 0, pipeMainLen: 0, pipeBranchLen: 0, pipeMainCount: 0, pipeBranchCount: 0,
            connections: { mT: 0, mE: 0, mC: 0, mbT: 0, mbE: 0, bT: 0, bE: 0, bC: 0 },
            pipeDetails: [], objects: { pipes: [], sprinklers: [] },
            emitters: 0, input: 0, output: 0, function: 0, waterUsage: 0
        };

        try {
            const polyId = polygon.properties.node_id;
            const isSitePoly = (polygon.properties.aot_type === 'site');

            // 1. Area calculation
            const areaM2 = window.turf.area(polygon);
            stats.area = parseFloat(areaM2.toFixed(2));

            // [Optimization] Bounding Box filtering (padded ~11m)
            const polyBbox = window.turf.bbox(polygon);
            const pad = 0.0001; 
            const polyBboxPad = [polyBbox[0] - pad, polyBbox[1] - pad, polyBbox[2] + pad, polyBbox[3] + pad];

            const isPointInBbox = (pt) => {
                return pt[0] >= polyBboxPad[0] && pt[0] <= polyBboxPad[2] &&
                       pt[1] >= polyBboxPad[1] && pt[1] <= polyBboxPad[3];
            };

            const isInside = (pt) => {
                if (!isPointInBbox(pt)) return false;
                return window.turf.booleanPointInPolygon(window.turf.point(pt), polygon);
            };

            const checkAttribution = (l) => {
                if (!l.feature || !l.feature.geometry) return { include: false, fullLength: false };
                const props = l.feature.properties || {};
                const pid = props.parent_node_id;
                const zid = props.zone_id;

                // [New] Force Include (for Nearest Neighbor assignment)
                if (props._force_include) {
                    return { include: true, fullLength: false };
                }

                // ID Match (Logical Ownership)
                if (isSitePoly) {
                    if (pid === polyId) return { include: true, fullLength: false };
                } else {
                    if (pid === polyId || zid === polyId) return { include: true, fullLength: true };
                }

                // Spatial Check with BBox filtering
                if (l.feature.geometry.type === 'Point') {
                    if (isInside(l.feature.geometry.coordinates)) return { include: true, fullLength: false };
                } else {
                    try {
                        const featBbox = window.turf.bbox(l.feature);
                        if (!(featBbox[0] > polyBboxPad[2] || featBbox[2] < polyBboxPad[0] ||
                              featBbox[1] > polyBboxPad[3] || featBbox[3] < polyBboxPad[1])) {
                            if (window.turf.booleanIntersects(l.feature, polygon)) return { include: true, fullLength: false };
                        }
                    } catch(e) {}
                }
                return { include: false, fullLength: false };
            };

            const getLength = (line, full) => {
                if (full) return window.turf.length(line, { units: 'meters' });
                const trimmed = this.trimLine(line, polygon);
                if (!trimmed) return 0;
                if (trimmed.type === 'FeatureCollection') {
                    let total = 0;
                    trimmed.features.forEach(f => total += window.turf.length(f, { units: 'meters' }));
                    return total;
                }
                return window.turf.length(trimmed, { units: 'meters' });
            };

            const coordMap = {};
            const addNode = (coords, subType) => {
                const key = `${coords[0].toFixed(7)},${coords[1].toFixed(7)}`;
                if (!coordMap[key]) coordMap[key] = { count: 0, types: [] };
                coordMap[key].count++;
                coordMap[key].types.push(subType);
            };

            const processLayer = (l) => {
                const props = l.feature.properties;
                const attr = checkAttribution(l);
                if (!attr.include) return;

                if (props.sub_type === 'pipe_main' || props.sub_type === 'pipe_branch') {
                    const len = getLength(l.feature, attr.fullLength);
                    if (len > 0) {
                        const lenFixed = parseFloat(len.toFixed(2));
                        if (props.sub_type === 'pipe_main') { stats.pipeMainCount++; stats.pipeMainLen += lenFixed; }
                        else { stats.pipeBranchCount++; stats.pipeBranchLen += lenFixed; }
                        
                        const pipeObj = {
                            type: props.sub_type === 'pipe_main' ? '주배관' : '가지관',
                            length: lenFixed,
                            name: props.name || (props.sub_type === 'pipe_main' ? 'Main' : 'Branch'),
                            uniqueId: props.node_id,
                            feature: l.feature,
                            sub_type: props.sub_type
                        };

                        // [New] Drip Logic
                        if (props.is_drip) {
                            pipeObj.type += ' (점적)';
                            pipeObj.isDrip = true;
                            
                            const dConfig = props.drip_config || {};
                            const interval = parseFloat(dConfig.interval) || 1.0;
                            const flow = parseFloat(dConfig.flow) || 0;
                            
                            // Emitter Count = Length / Interval
                            const dripCount = Math.floor(lenFixed / interval);
                            const dripUsage = dripCount * flow;

                            pipeObj.dripCount = dripCount;
                            pipeObj.dripFlow = dripUsage;

                            stats.emitters += dripCount;
                            stats.waterUsage += dripUsage;
                        }

                        stats.pipeDetails.push(pipeObj);
                        stats.objects.pipes.push(pipeObj);
                        
                        // Node collection for Ends
                        const coords = l.feature.geometry.coordinates;
                        if (coords && coords.length >= 2) {
                            const start = coords[0];
                            const end = coords[coords.length - 1];
                            if (isInside(start)) addNode(start, props.sub_type);
                            if (isInside(end)) addNode(end, props.sub_type);
                        }
                    }
                } else if (props.aot_type === 'connection' || props.sub_type === 'tee' || props.sub_type === 'elbow') {
                    const code = props.sub_type || '';
                    let fitType = code.endsWith('T') ? 'tee' : (code.endsWith('E') ? 'elbow' : props.sub_type);
                    
                    // [Fix] mbT Specific Handling
                    if (code === 'mbT' || code === 'mbE') {
                        fitType = 'mixed'; // Custom type marker
                    }

                    if (fitType === 'tee' || fitType === 'elbow' || fitType === 'mixed') {
                        if (!stats.objects.fittings) stats.objects.fittings = [];
                        stats.objects.fittings.push({ type: fitType, feature: l.feature, explicitMain: code.startsWith('m'), sub_type: props.sub_type });
                    }
                } else {
                    const isSprinkler = props.sub_type === 'sprinkler' || props.device_type === 'sprinkler' || props.aot_type === 'sprinkler' || (props.aot_type === 'equipment' && props.sub_type === 'sprinkler');
                    if (isSprinkler) {
                        stats.emitters++;
                        stats.waterUsage += (parseFloat(props.flow) || parseFloat(props.flow_rate) || 0);
                        stats.objects.sprinklers.push(l.feature);
                    }

                    const type = props.device_type;
                    if (type === 'input') stats.input++;
                    else if (type === 'output') stats.output++;
                    else if (['function', 'trigger', 'pid', 'conditional', 'custom', 'generic_function', 'script'].includes(type)) stats.function++;
                }
            };

            const processedIds = new Set();
            if (Array.isArray(layerStorage)) {
                 layerStorage.forEach(l => {
                    const id = l.feature?.properties?.node_id;
                    if (id && !processedIds.has(id)) { processedIds.add(id); processLayer(l); }
                });
            } else {
                const tryP = (l) => {
                    const id = l.feature?.properties?.node_id;
                    if (id && !processedIds.has(id)) { processedIds.add(id); processLayer(l); }
                };
                if (window.AoTMapEditor?.featureGroup) window.AoTMapEditor.featureGroup.eachLayer(tryP);
                ['equipment', 'aot_device', 'connection'].forEach(k => { if (layerStorage[k]) layerStorage[k].eachLayer(tryP); });
            }

            // Post-Process Classification
            if (stats.objects.fittings) {
                stats.objects.fittings.forEach(fit => {
                    const st = fit.sub_type;
                    
                    // [Fix] Explicit count for mbT and mbE
                    if (st === 'mbT') {
                        stats.connections.mbT++;
                        return;
                    }
                    if (st === 'mbE') {
                        stats.connections.mbE++; // Explicitly track mbE
                        return;
                    }

                    if (st && stats.connections[st] !== undefined) stats.connections[st]++;
                    else {
                        if (fit.type === 'tee') { if (fit.explicitMain) stats.connections.mT++; else stats.connections.bT++; }
                        else if (fit.type === 'elbow') { if (fit.explicitMain) stats.connections.mE++; else stats.connections.bE++; }
                    }
                });
            }

            // End Detection
            Object.keys(coordMap).forEach(key => {
                if (coordMap[key].count === 1) {
                    const [x, y] = key.split(',').map(Number);
                    const pt = window.turf.point([x, y]);
                    let hasFitting = false;
                    for (const fit of (stats.objects.fittings || [])) {
                        if (window.turf.distance(pt, fit.feature, { units: 'meters' }) < 0.3) { hasFitting = true; break; }
                    }
                    if (!hasFitting) {
                        if (coordMap[key].types.includes('pipe_main')) stats.connections.mC++;
                        else stats.connections.bC++;
                    }
                }
            });

            stats.pipeMainLen = parseFloat(stats.pipeMainLen.toFixed(1));
            stats.pipeBranchLen = parseFloat(stats.pipeBranchLen.toFixed(1));
            stats.waterUsage = parseFloat(stats.waterUsage.toFixed(1));

        } catch (e) { console.error("[DesignStats] Error:", e); }
        return stats;
    },

    /**
     * Helper to associate sprinklers to nearest pipes
     * @param {Array} pipes - List of pipe objects { length, feature, ... }
     * @param {Array} sprinklers - List of sprinkler features
     */
    mapSprinklersToPipes: function (pipes, sprinklers) {
        // Init stats
        pipes.forEach(p => {
            // [Fix] Preserve Drip Stats if present
            p.sprinklerCount = p.dripCount || 0;
            p.waterUsage = p.dripFlow || 0;
        });

        if (!window.turf) return pipes;

        sprinklers.forEach(sp => {
            let nearestPipe = null;
            let minDist = Infinity;

            // Find nearest pipe
            pipes.forEach(p => {
                if (!p.feature) return;
                try {
                    // dist is in km by default in turf
                    const dist = window.turf.pointToLineDistance(sp, p.feature, { units: 'meters' });
                    if (dist < minDist) {
                        minDist = dist;
                        nearestPipe = p;
                    }
                } catch (e) { }
            });

            // Threshold (e.g. 1 meter? or simply nearest?)
            // If nearest is reasonably close (e.g. < 5m) assume connected?
            // User surely places them "on" the line, but slight offset exists.
            if (nearestPipe && minDist < 10.0) {
                nearestPipe.sprinklerCount++;
                const flow = parseFloat(sp.properties?.flow || sp.properties?.flow_rate || 0);
                nearestPipe.waterUsage += flow;
            }
        });

        // [Update] REMOVED Local Aggregation.
        // Global aggregation is handled in `aot-geo-stats.js` `updateDesignInfo`.
        // Doing it here caused double counting.

        return pipes;
    },

    /**
     * Add Copyright Control to Map (Bottom Center)
     * Uses Leaflet's native Attribution Control but styles it to be centered.
     * @param {L.Map} map
     */
    addCopyrightControl: function (map) {
        if (!map) return;

        // 1. Check if attribution control exists, if not add it (without 'Leaflet' prefix)
        // [Refactor] User requested Bottom-Left positioning. Using standard Leaflet control.
        let attrib = map.attributionControl;
        if (!attrib) {
            attrib = L.control.attribution({ prefix: false, position: 'bottomleft' }).addTo(map);
        } else {
            attrib.setPrefix(false);
            attrib.setPosition('bottomleft');
        }

        // Ensure visibility
        const container = attrib.getContainer();
        if (container) {
            container.style.display = 'block';
            container.style.fontSize = '11px'; // Keep readable size
        }

        // 2. [Fix] VWorld Copyright Injection (For Legacy Layers without explicit attribution)
        // Checks any added layer. If URL matches VWorld, injects the Logo attribution.
        const vworldAttr = '<a href="https://www.vworld.kr/" target="_blank"><img src="https://www.vworld.kr/img/img_opentype01.png" alt="Vworld" style="height:28px;"></a>';
        
        const checkLayer = (e) => {
            const layer = e.layer;
            if (layer && layer._url && (layer._url.indexOf('vworld.kr') !== -1 || (layer.options && layer.options.id === 'vworld'))) {
                // Add Image Attribution
                map.attributionControl.addAttribution(vworldAttr);
            }
        };

        const removeLayerCheck = (e) => {
             const layer = e.layer;
             if (layer && layer._url && (layer._url.indexOf('vworld.kr') !== -1 || (layer.options && layer.options.id === 'vworld'))) {
                 map.attributionControl.removeAttribution(vworldAttr);
             }
        };

        map.on('layeradd', checkLayer);
        map.on('layerremove', removeLayerCheck);
        
        // Check existing layers immediately
        map.eachLayer(layer => {
            checkLayer({ layer: layer });
        });
    }
};

window.AoTMapUtils = AoTMapUtils;
