/**
 * aot-geo-geometry.js
 * Geometry Operations for AoTGeoDesign
 */

class AoTGeoGeometry {
    constructor(parent) {
        this.parent = parent;
        this._isInternalAction = false;
    }

    /**
     * Entry point for geometry operations
     */
    handleGeometryOp(op, feature, data = null) {
        if (!window.AoTMapUtils) return;

        if (op === 'hide-label') { this.parent._toggleLengthLabels(); return; }
        if (op === 'hide-site-label') { this.parent._toggleSiteLabels(); return; }
        if (op === 'hide-zone-label') { this.parent._toggleZoneLabels(); return; }
        if (op === 'hide-pipe-label') { this.parent._togglePipeLabels(); return; }
        if (op === 'hide-sprinkler-points') { this.parent._toggleSprinklerPoints(data); return; }
        if (op === 'hide-connection-points') { this.parent._toggleConnectionPoints(data); return; }

        if (!feature) return;

        // clear-equip doesn't need the layer object — handle it before the layer lookup
        // so a missing layer reference doesn't silently block equipment clearing.
        if (op === 'clear-equip') {
            try {
                let targetFeature = feature;
                const fType = feature.properties?.aot_type;
                if (fType === 'equipment' || fType === 'connection' || fType === 'aot_device') {
                    const parentId = feature.properties.parent_node_id || feature.properties.zone_id;
                    if (parentId) {
                        const parentLayer = this._findLayerByUuid(parentId) || this._findInLayerStorage(parentId);
                        if (parentLayer) targetFeature = parentLayer.feature;
                    } else if (window.turf) {
                        const center = window.turf.center(feature);
                        const parentPoly = this._findContainerPolygon(center);
                        if (parentPoly) targetFeature = parentPoly;
                    }
                }
                this.parent.clearEquipments(targetFeature, data || 'all');
            } catch (e) {
                if (this.parent.ui) this.parent.ui.showToast((_('operation_error') || 'Error: ') + e.message, 'error');
            }
            return;
        }

        // console.log(`[AoTGeoGeometry] Executing ${op} on feature:`, feature.properties.node_id, data);
        let layer = this._findLayerByUuid(feature.properties.node_id);
        if (!layer) return;

        try {
            switch (op) {
                case 'extend':
                    if (feature.geometry.type !== 'LineString') {
                        this.parent.ui.showToast(_('extend_only_line'), 'warning');
                        return;
                    }
                    this.performExtend(layer);
                    break;

                case 'trim':
                    if (feature.geometry.type !== 'LineString') {
                        this.parent.ui.showToast(_('trim_only_line'), 'warning');
                        return;
                    }
                    this.performTrim(layer);
                    break;

                case 'offset':
                    const def = feature.geometry.type === 'Polygon' ? -1.0 : 1.0;
                    const msg = feature.geometry.type === 'Polygon' ?
                        _('offset_prompt_polygon') :
                        _('offset_prompt_line');

                    const val = prompt(msg, def);
                    if (val) {
                        const dist = parseFloat(val);
                        if (isNaN(dist)) return;
                        this.performOffset(layer, dist);
                    }
                    break;

                case 'merge':
                    this.parent.ui.showToast(_('select_merge_target'), 'warning');
                    this.parent.pendingOp = { type: 'merge', targetLayer: layer };
                    L.DomUtil.addClass(this.parent.map._container, 'crosshair-cursor');
                    break;

                case 'sub':
                    this.parent.ui.showToast(_('select_subtract_target'), 'warning');
                    this.parent.pendingOp = { type: 'sub', targetLayer: layer };
                    L.DomUtil.addClass(this.parent.map._container, 'crosshair-cursor');
                    break;

            }
        } catch (e) {
            // console.error("Geometry Op Error:", e);
            // console.error(e);
            this.parent.ui.showToast(_('operation_error') + e.message, 'error');
        }
    }

    _findLayerByUuid(uuid) {
        let found = null;
        if (window.AoTMapEditor?.featureGroup) {
            window.AoTMapEditor.featureGroup.eachLayer(l => {
                if (l.feature?.properties?.node_id === uuid) found = l;
            });
        }
        if (found) return found;
        return this._findInLayerStorage(uuid);
    }

    _findInLayerStorage(uuid) {
        let found = null;
        Object.values(this.parent.layerStorage).forEach(group => {
            if (found) return;
            group.eachLayer(l => {
                if (l.feature?.properties?.node_id === uuid) found = l;
            });
        });
        return found;
    }

    performOffset(layer, distance) {
        const geojson = layer.toGeoJSON();
        let buffered = null;

        if (geojson.geometry.type === 'Polygon') {
            buffered = window.turf.buffer(geojson, distance, { units: 'meters' });
        } else if (geojson.geometry.type === 'LineString') {
            buffered = window.turf.lineOffset(geojson, distance, { units: 'meters' });
        }

        if (buffered) {
            // Pure MapLibre: Convert GeoJSON coords to lat/lng pairs manually (replaces L.GeoJSON.coordsToLatLngs)
            const coordsToLatLngs = (coords, levels) => {
                const latlngs = [];
                for (let i = 0; i < coords.length; i++) {
                    const coord = coords[i];
                    if (levels > 0) {
                        latlngs.push(coordsToLatLngs(coord, levels - 1));
                    } else {
                        latlngs.push({ lat: coord[1], lng: coord[0] });
                    }
                }
                return latlngs;
            };
            if (buffered.geometry.type === 'Polygon') {
                const coords = buffered.geometry.coordinates;
                const latlngs = coordsToLatLngs(coords, 1);
                layer.setLatLngs(latlngs);
            } else if (buffered.geometry.type === 'LineString') {
                const coords = buffered.geometry.coordinates;
                const latlngs = coordsToLatLngs(coords, 0);
                layer.setLatLngs(latlngs);
            }

            // Pure MapLibre: Dispatch MapLibre Draw edited event
            this.parent.map.fire('edit', { layer: layer });
            // console.log("[GeoOp] Offset Applied");
        }
    }

    performExtend(layer) {
        const line = layer.toGeoJSON();
        const center = window.turf.centroid(line);

        let parentParams = this._findContainerPolygon(center);
        if (!parentParams) {
            alert(_('parent_polygon_not_found'));
            return;
        }

        const extended = window.AoTMapUtils.extendLineToBoundary(line, parentParams);
        if (extended) {
            // Pure MapLibre: Convert coords to lat/lng pairs manually
            const coords = extended.geometry.coordinates;
            const latlngs = coords.map(coord => ({ lat: coord[1], lng: coord[0] }));
            layer.setLatLngs(latlngs);
            // Pure MapLibre: Dispatch MapLibre Draw edited event
            this.parent.map.fire('edit', { layer: layer });
            // console.log("[GeoOp] Extend Applied");
        } else {
            this.parent.ui.showToast(_('no_boundary_intersection'), 'warning');
        }
    }

    performTrim(layer) {
        const line = layer.toGeoJSON();
        const center = window.turf.centroid(line);

        let parentParams = this._findContainerPolygon(center);
        if (!parentParams) {
            this.parent.ui.showToast(_('parent_polygon_not_found'), 'warning');
            return;
        }

        const trimmed = window.AoTMapUtils.trimLine(line, parentParams);
        if (trimmed) {
            if (trimmed.geometry.type === 'LineString') {
                // Pure MapLibre: Convert coords to lat/lng pairs manually
                const coords = trimmed.geometry.coordinates;
                const latlngs = coords.map(coord => ({ lat: coord[1], lng: coord[0] }));
                layer.setLatLngs(latlngs);
                // Pure MapLibre: Dispatch MapLibre Draw edited event
                this.parent.map.fire('edit', { layer: layer });
            } else {
                this.parent.ui.showToast(_('multiline_not_supported'), 'warning');
            }
        } else {
            this.parent.ui.showToast(_('trim_error_or_none'), 'warning');
        }
    }

    performMerge(baseLayer, targetLayer) {
        if (!window.turf) return;
        if (baseLayer === targetLayer) { this.parent.ui.showToast(_('merge_self_error'), 'warning'); return; }
 
        // console.log("[Merge] Executing Union...");
        try {
            const wasEditing = (baseLayer.editing && baseLayer.editing.enabled());
            if (wasEditing) baseLayer.editing.disable();

            const rawB = baseLayer.toGeoJSON ? baseLayer.toGeoJSON() : null;
            const rawT = targetLayer.toGeoJSON ? targetLayer.toGeoJSON() : null;

            if (wasEditing) baseLayer.editing.enable();

            const bGeo = this._normalizeToFeature(rawB);
            const tGeo = this._normalizeToFeature(rawT);

            if (!bGeo || !tGeo) throw new Error("Invalid Layer Objects");

            let union = null;
            try {
                union = window.turf.union(bGeo, tGeo);
            } catch (e) {
                // Fallback for older turf versions or complex geometries
                const fc = window.turf.featureCollection([bGeo, tGeo]);
                union = window.turf.union(fc);
            }

            if (!union) {
                this.parent.ui.showToast(_('merge_failed_turf'), 'error');
                return;
            }

            this.applyGeometryResult(baseLayer, targetLayer, union, "Union");
 
        } catch (e) {
            // console.error("[Merge] Error:", e);
            this.parent.ui.showToast(_('merge_error') + e.message, 'error');
        }
    }

    performSubtract(baseLayer, targetLayer) {
        if (!window.turf) return;
        if (baseLayer === targetLayer) { this.parent.ui.showToast(_('subtract_self_error'), 'warning'); return; }
 
        // console.log("[Sub] Executing Difference...");
        try {
            const wasEditing = (baseLayer.editing && baseLayer.editing.enabled());
            if (wasEditing) baseLayer.editing.disable();

            const rawB = baseLayer.toGeoJSON ? baseLayer.toGeoJSON() : null;
            const rawT = targetLayer.toGeoJSON ? targetLayer.toGeoJSON() : null;

            if (wasEditing) baseLayer.editing.enable();

            const bGeo = this._normalizeToFeature(rawB);
            const tGeo = this._normalizeToFeature(rawT);

            if (!bGeo || !tGeo) throw new Error("Invalid Layer Objects");

            let diff = null;
            try {
                diff = window.turf.difference(bGeo, tGeo);
            } catch (e) {
                diff = window.turf.difference(window.turf.featureCollection([bGeo, tGeo]));
            }

            if (!diff) {
                this.parent.ui.showToast(_('subtract_failed_turf'), 'error');
                return;
            }

            this.applyGeometryResult(baseLayer, targetLayer, diff, "Diff");
 
        } catch (e) {
            // console.error("[Sub] Error:", e);
            this.parent.ui.showToast(_('subtract_error') + e.message, 'error');
        }
    }

    applyGeometryResult(baseLayer, targetLayer, newFeature, suffix) {
        const parentProps = baseLayer.feature.properties;
        newFeature.properties = JSON.parse(JSON.stringify(parentProps));

        let area = 0;
        let areaDisplay = "0 m²";
        if (window.turf) {
            try {
                area = window.turf.area(newFeature);
                newFeature.properties.area = area;
                areaDisplay = Math.round(area) + ' m²';
            } catch (e) { /* console.warn("Area calc error", e); */ }
        }

        const baseId = parentProps.node_id;
        const targetId = targetLayer.feature?.properties?.node_id;

        const labelGroup = this.parent.layerStorage['label_aux'];
        if (labelGroup) {
            labelGroup.eachLayer(l => {
                const pid = l.feature.properties.parent_node_id;

                if (pid === targetId) {
                    labelGroup.removeLayer(l);
                    this.parent.map.removeLayer(l);
                }

                if (pid === baseId) {
                    const name = newFeature.properties.label_name || 'Site';
                    l.feature.properties.label_name = name;
                    l.feature.properties.label_area = areaDisplay;
                    l.feature.properties.text_content = `${name}\n${areaDisplay}`;

                    let color = baseLayer.options.color || baseLayer.options.fillColor;
                    if (!color && baseLayer.feature && baseLayer.feature.properties) {
                        color = baseLayer.feature.properties.color;
                    }
                    if (!color) color = '#FFC107';

                    this.parent._updateLabelIcon(l, name, areaDisplay, color);
                }
            });
        }

        try {
            const tempLayer = AoTGeoLayer.fromGeoJSON(newFeature);
            const newLayer = tempLayer[0];

            if (newLayer) {
                newLayer.feature = newFeature;
                window.AoTMapEditor.featureGroup.addLayer(newLayer);

                this.parent._setLayerStyle(newLayer, true);
                this.parent._setActiveLayer(newLayer);
 
            } else {
                // console.error("[GeoOp] Failed layer creation");
            }
        } catch (errAdd) {
            // console.error("[GeoOp] Add Error:", errAdd);
        }

        this.removeLayerSafe(baseLayer);
        this.removeLayerSafe(targetLayer);

        this.parent.saveDesign(['site', 'zone', 'label_aux'], true);
    }

    removeLayerSafe(layer) {
        if (window.AoTMapEditor.featureGroup.hasLayer(layer)) {
            window.AoTMapEditor.featureGroup.removeLayer(layer);
        } else {
            const type = layer.feature.properties.aot_type;
            if (this.parent.layerStorage[type]) {
                this.parent.layerStorage[type].removeLayer(layer);
                this.parent.map.removeLayer(layer);
            }
        }
    }

    _normalizeToFeature(geojson) {
        if (!geojson) return null;

        let feature = geojson;
        if (geojson.type === 'FeatureCollection') {
            const poly = geojson.features.find(f => f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon');
            if (poly) feature = poly;
            else if (geojson.features.length > 0) feature = geojson.features[0];
            else return null;
        }
        else if (geojson.type === 'Polygon' || geojson.type === 'MultiPolygon' || geojson.type === 'LineString') {
            feature = {
                type: 'Feature',
                properties: {},
                geometry: geojson
            };
        }

        if (feature && feature.geometry && feature.geometry.type === 'MultiPolygon') {
            if (feature.geometry.coordinates && feature.geometry.coordinates.length > 0) {
                const coords = JSON.parse(JSON.stringify(feature.geometry.coordinates[0]));
                feature = {
                    type: 'Feature',
                    properties: feature.properties || {},
                    geometry: {
                        type: 'Polygon',
                        coordinates: coords
                    }
                };
            }
        }

        return feature;
    }

    _findContainerPolygon(centerPt) {
        const candidates = [];
        window.AoTMapEditor.featureGroup.eachLayer(l => {
            if (l.feature?.geometry?.type === 'Polygon') candidates.push(l.toGeoJSON());
        });
        if (this.parent.layerStorage['zone']) {
            this.parent.layerStorage['zone'].eachLayer(l => candidates.push(l.toGeoJSON()));
        }
        if (this.parent.layerStorage['site']) {
            this.parent.layerStorage['site'].eachLayer(l => candidates.push(l.toGeoJSON()));
        }

        for (const poly of candidates) {
            if (window.turf.booleanPointInPolygon(centerPt, poly)) {
                return poly;
            }
        }
        return null;
    }

    /**
     * Selection Logic
     */
    selectConnectedLines(startLayer) {
        if (this.parent.selectedRefLines && this.parent.selectedRefLines.includes(startLayer) && this.parent.selectedRefLines.length === 1) {
            this.clearRefSelection();
            return;
        }

        this.clearRefSelection();

        const pool = [];
        const collect = (group) => {
            if (!group) return;
            group.eachLayer(l => {
                if (l.feature?.geometry?.type === 'LineString') pool.push(l);
            });
        };
        collect(window.AoTMapEditor.featureGroup);
        if (this.parent.layerStorage['site']) collect(this.parent.layerStorage['site']);
        if (this.parent.layerStorage['zone']) collect(this.parent.layerStorage['zone']);

        const connected = new Set();
        const queue = [startLayer];
        connected.add(startLayer);

        while (queue.length > 0) {
            const current = queue.pop();
            const currGeo = current.toGeoJSON();

            pool.forEach(candidate => {
                if (connected.has(candidate)) return;
                const candGeo = candidate.toGeoJSON();
                if (window.turf.booleanIntersects(currGeo, candGeo)) {
                    connected.add(candidate);
                    queue.push(candidate);
                }
            });
        }
 
        this.parent.selectedRefLines = Array.from(connected);
        // console.log(`[Selection] Chains found: ${this.parent.selectedRefLines.length} lines`);
 
        this.parent.selectedRefLines.forEach(l => {
            if (l.setStyle) {
                l.setStyle({ color: '#ff0000', weight: 5, opacity: 1.0 });
                if (l.bringToFront) l.bringToFront();
            }
        });
    }

    clearRefSelection() {
        if (this.parent.selectedRefLines) {
            this.parent.selectedRefLines.forEach(l => {
                if (l.setStyle) l.setStyle({ color: '#3388ff', weight: 3, opacity: 0.8, dashArray: null });
            });
        }
        this.parent.selectedRefLines = [];
    }

    updateShapeMetrics(layer) {
        if (!layer || !layer.feature || !layer.feature.properties) return;
        const props = layer.feature.properties;
        const type = props.aot_type;

        if (['site', 'zone'].includes(type) && window.turf) {
            let areaDisplay = '';
            try {
                let geojson = layer.toGeoJSON();
                const geomType = layer._aotType || (layer.feature?.geometry?.type);
                const isCircle = geomType === 'Circle' || (layer.feature?.properties?.is_circle);
                if (isCircle) {
                    const center = layer.getLatLng();
                    const radius = layer.getRadius();
                    geojson = window.turf.circle([center.lng, center.lat], radius, { steps: 16, units: 'meters' });
                }

                const area = window.turf.area(geojson);
                areaDisplay = Math.round(area) + ' m²';
                props.area = area;

                const uuid = props.node_id;
                let linkedLabel = null;

                window.AoTMapEditor.featureGroup.eachLayer(l => {
                    if (l.feature?.properties?.parent_node_id === uuid) linkedLabel = l;
                });
                if (!linkedLabel && this.parent.layerStorage['label_aux']) {
                    this.parent.layerStorage['label_aux'].eachLayer(l => {
                        if (l.feature?.properties?.parent_node_id === uuid) linkedLabel = l;
                    });
                }

                if (linkedLabel) {
                    const labelName = linkedLabel.feature.properties.label_name || props.name || "Label";
                    let color = '#333';
                    if (type === 'site') color = '#ffcc00';
                    else if (type === 'zone') color = '#28a745';
                    this.parent._updateLabelIcon(linkedLabel, labelName, areaDisplay, color);
                }
            } catch (e) {
                // console.warn("[Metrics] Update Failed:", e);
            }
        }
        this.updateMeasurementLabels(layer);
    }

    updateMeasurementLabels(layer) {
        // Pure MapLibre: Use _aotType check instead of instanceof L.Polyline/L.Circle
        const geomType = layer._aotType || (layer.feature?.geometry?.type);
        const isPolylineNotPolygon = geomType === 'LineString';
        const isCircle = geomType === 'Circle' || (layer.feature?.properties?.is_circle);

        if (isPolylineNotPolygon) return;
        if (layer._measurementLabels) {
            const labelAux = this.parent.layerStorage['label_aux'];
            layer._measurementLabels.forEach(l => {
                if (labelAux && labelAux.hasLayer(l)) labelAux.removeLayer(l);
                else if (l._mlDomMarker) { l._mlDomMarker.remove(); l._mlDomMarker = null; }
            });
        }
        layer._measurementLabels = [];
        if (!layer.getLatLngs && !isCircle) return;

        const aotType = layer.feature?.properties?.aot_type;
        const subType = layer.feature?.properties?.sub_type;
        const isPipe = aotType === 'equipment' && (subType === 'pipe_main' || subType === 'pipe_branch');
        if (!['site', 'zone'].includes(aotType) && !isPipe) return;

        const createLabelMarker = (lat, lng, text) => {
            const config = window.AOT_GEO_CONFIG?.theme_config || {};
            let borderColor = '#999';
            if (aotType === 'site') borderColor = config.site || '#DF5353';
            else if (aotType === 'zone') borderColor = config.zone || '#28a745';
            else if (isPipe) borderColor = config.equipment || '#007bff';

            const typeClass = aotType === 'site' ? 'aot-site-label' : aotType === 'zone' ? 'aot-zone-label' : '';
            const cssClass = `aot-measure-label${typeClass ? ' ' + typeClass : ''}`;
            const iconHtml = `<div style="position: absolute; top:0; left:0; transform: translate(-50%, -50%); background: white; padding: 1px 4px; border: 1px solid ${borderColor}; border-radius: 3px; font-family: sans-serif; font-size: 11px; color: #333; box-shadow: 1px 1px 2px rgba(0,0,0,0.15); white-space: nowrap; cursor: pointer;">${text}</div>`;
            const label = new AoTGeoMarker([lat, lng], {
                icon: {
                    className: cssClass,
                    html: iconHtml,
                    createIcon() {
                        const el = document.createElement('div');
                        el.className = cssClass;
                        el.style.cssText = 'width:0;height:0;overflow:visible;';
                        el.innerHTML = iconHtml;
                        return el;
                    }
                },
                interactive: true,
                zIndexOffset: 0
            });
            const parentId = layer.feature?.properties?.node_id;
            label.feature = {
                type: 'Feature',
                properties: {
                    aot_type: 'label_dynamic',
                    no_save: true,
                    parent_node_id: parentId,
                    parent_type: aotType
                }
            };
            label.on('click', (e) => {
                const fType = layer.feature?.properties?.aot_type;
                const isAllowed = (this.parent.activeMode === fType)
                    || (this.parent.activeMode === 'equipment' && ['site', 'zone'].includes(fType))
                    || (this.parent.activeMode === 'aot_device' && fType === 'device');
                if (!isAllowed) return;
                if (e && e.stopPropagation) e.stopPropagation();
                this.parent._setActiveLayer(layer);
            });
            return label;
        };

        if (isCircle) {
            let radius = 0; let center = null;
            if (geomType === 'Circle' && layer.getRadius) { radius = layer.getRadius(); center = layer.getLatLng(); }
            else {
                try {
                    const area = window.turf.area(layer.toGeoJSON());
                    radius = Math.sqrt(area / Math.PI);
                    center = layer.getBounds().getCenter();
                } catch (e) { return; }
            }
            if (radius > 0) {
                const diameter = (radius * 2).toFixed(1);
                let lat = center.lat; let lng = center.lng;
                if (window.turf) {
                    const p = window.turf.point([center.lng, center.lat]);
                    const offsetDist = (aotType === 'site') ? 0.01 : 0.005;
                    const dest = window.turf.destination(p, (radius / 1000) + offsetDist, 0, { units: 'kilometers' });
                    lng = dest.geometry.coordinates[0]; lat = dest.geometry.coordinates[1];
                }
                layer._measurementLabels.push(createLabelMarker(lat, lng, `Ø ${diameter}m`));
            }
        } else {
            let latlngs = layer.getLatLngs();
            while (Array.isArray(latlngs) && latlngs.length > 0 && Array.isArray(latlngs[0])) latlngs = latlngs[0];
            if (!Array.isArray(latlngs) || latlngs.length < 3) return;
            const hasTurf = !!window.turf;
            let center = null;
            if (hasTurf) {
                try {
                    const poly = layer.toGeoJSON();
                    center = window.turf.centroid(poly.geometry || poly);
                } catch (e) { }
            }
            for (let i = 0; i < latlngs.length; i++) {
                const p1 = latlngs[i]; const p2 = latlngs[(i + 1) % latlngs.length];
                const dist = p1.distanceTo(p2);
                if (dist < 1) continue;
                let lblLat = (p1.lat + p2.lat) / 2; let lblLng = (p1.lng + p2.lng) / 2;
                if (hasTurf && center) {
                    const angle = Math.atan2(lblLat - center.geometry.coordinates[1], lblLng - center.geometry.coordinates[0]);
                    const offset = 0.00005;
                    lblLat += Math.sin(angle) * offset; lblLng += Math.cos(angle) * offset;
                }
                layer._measurementLabels.push(createLabelMarker(lblLat, lblLng, `${dist.toFixed(1)}m`));
            }
        }

        const storage = this.parent.layerStorage['label_aux'];
        const ensureStorageMap = () => {
            if (storage && !storage._map && this.parent.map) {
                storage._map = this.parent.map;
                if (!this.parent.map.hasLayer(storage)) this.parent.map.addLayer(storage);
            }
        };
        const showLabels = () => {
            ensureStorageMap();
            const nativeMap = this.parent.map && (
                this.parent.map._originalMap
                || (this.parent.map.getNativeMap && this.parent.map.getNativeMap())
                || this.parent.map._mlMap
                || this.parent.map);
            layer._measurementLabels.forEach(l => {
                if (storage) { if (!storage.hasLayer(l)) storage.addLayer(l); }
                else if (this.parent.map) l.addTo(this.parent.map);
                // Direct DOM marker creation fallback — ensures markers are visible
                // even when AoTGeoLayerGroup.doAdd() doesn't fire (e.g. style-load timing
                // race on old-version shapes loaded via _pendingLabelUpdates flush).
                if (!l._mlDomMarker && window.maplibregl && nativeMap) {
                    const el = l._icon?.createIcon?.() || (() => {
                        const d = document.createElement('div');
                        d.style.cssText = 'width:0;height:0;overflow:visible;';
                        return d;
                    })();
                    l._markerEl = el;
                    l._mlDomMarker = new window.maplibregl.Marker({ element: el, anchor: 'center', draggable: false })
                        .setLngLat([l._latlng.lng, l._latlng.lat])
                        .addTo(nativeMap);
                }
            });
        };
        const hideLabels = () => {
            layer._measurementLabels.forEach(l => {
                if (storage && storage.hasLayer(l)) storage.removeLayer(l);
                else if (l._mlDomMarker) { l._mlDomMarker.remove(); }
            });
        };

        // Remove stale movestart/moveend handlers — display is managed by _setDetailLabelVisibility
        if (this.parent.map) {
            if (layer._measurementLabelMoveHandler) this.parent.map.off('movestart', layer._measurementLabelMoveHandler);
            if (layer._measurementLabelIdleHandler) this.parent.map.off('moveend', layer._measurementLabelIdleHandler);
            layer._measurementLabelMoveHandler = null;
            layer._measurementLabelIdleHandler = null;
        }

        layer.off('add', showLabels); layer.off('remove', hideLabels);
        layer.on('add', showLabels); layer.on('remove', hideLabels);
        // Show labels when any map reference is available
        if (layer._map || (storage && storage._map) || this.parent.map) showLabels();
    }

    /**
     * [OBSOLETE V4] processPipeTrimming is now handled by rebuildConnections and _trimOvershoot.
     * Keeping as stub for safety if called elsewhere.
     */
    processPipeTrimming(mainPipeLayer) {
        if (!mainPipeLayer || !mainPipeLayer.feature || !mainPipeLayer.feature.geometry) return;
        if (this._isInternalAction) return;
        this._isInternalAction = true;

        try {
            // Find all branch pipes that might intersect this main pipe
            const branches = [];
            const collect = (group) => {
                if (!group) return;
                group.eachLayer(l => {
                    if (l === mainPipeLayer) return;
                    const props = l.feature?.properties;
                    if (props && props.sub_type === 'pipe_branch') {
                        branches.push(l);
                    }
                });
            };
            collect(this.parent.layerStorage['equipment']);
            collect(window.AoTMapEditor.featureGroup);

            const mainBbox = mainPipeLayer.getBounds();
            branches.forEach(branch => {
                if (mainBbox.intersects(branch.getBounds())) {
                    // Focus on detecting and handling connection (which includes trimming)
                    this._detectConnectionBetween(mainPipeLayer, branch, true);
                }
            });
        } finally {
            this._isInternalAction = false;
        }
    }


    updatePipeLabels(layer) {
        if (!layer) return;
        // [Fix] Ensure Feature Geometry exists (L.Draw sometimes delays it)
        if (!layer.feature || !layer.feature.geometry) {
            if (layer.toGeoJSON) {
                const geo = layer.toGeoJSON();
                layer.feature = layer.feature || { type: 'Feature', properties: {} };
                layer.feature.geometry = geo.geometry;
            } else return;
        }

        const props = layer.feature.properties || {};
        if (props.sub_type !== 'pipe_main' && props.sub_type !== 'pipe_branch') return;

        // [Fix] Remove map check to ensure labels are created even if layer is briefly detached
        // We will rely on layer.on('add') and layer.on('remove') to manage actual map presence.
        if (layer._pipeLabel) {
            if (this.parent.map.hasLayer(layer._pipeLabel)) this.parent.map.removeLayer(layer._pipeLabel);
            layer._pipeLabel = null;
        }
        let length = 0; let center = null;
        if (window.turf) {
            try {
                const geo = layer.toGeoJSON();
                length = window.turf.length(geo, { units: 'meters' });
                center = window.turf.along(geo, length / 2, { units: 'meters' });
            } catch (e) { return; }
        } else return;

        if (length >= 5.0) {
            const formattedLen = length.toFixed(1);
            const lat = center.geometry.coordinates[1]; const lng = center.geometry.coordinates[0];
            
            const config = window.AOT_GEO_CONFIG?.theme_config || {};
            const themeColor = config.equipment || '#007bff';

            const pipeIconHtml = `<div style="background: ${themeColor}; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-family: sans-serif; white-space: nowrap; box-shadow: 1px 1px 2px rgba(0,0,0,0.2); transform: translate(-50%, -50%); border: 1px solid white; display: inline-block; width: max-content;">${formattedLen}</div>`;
            const label = new AoTGeoMarker([lat, lng], {
                icon: {
                    className: 'aot-pipe-label',
                    html: pipeIconHtml,
                    createIcon() {
                        const el = document.createElement('div');
                        el.className = 'aot-pipe-label';
                        el.style.cssText = 'width:0;height:0;overflow:visible;';
                        el.innerHTML = pipeIconHtml;
                        return el;
                    }
                },
                interactive: false, zIndexOffset: 0
            });
            label.feature = {
                type: 'Feature',
                properties: {
                    aot_type: 'label_dynamic',
                    no_save: true,
                    parent_node_id: props.node_id // [Fix] Link to parent pipe
                }
            };

            const storage = this.parent.layerStorage['label_aux'];

            // Manage Storage/Map Presence
            if (storage) {
                storage.addLayer(label);
            } else {
                label.addTo(this.parent.map);
            }

            layer._pipeLabel = label;

            // Safety Listeners
            layer.on('add', () => {
                if (layer._pipeLabel && !this.parent.map.hasLayer(layer._pipeLabel)) {
                    if (storage) storage.addLayer(layer._pipeLabel);
                    else layer._pipeLabel.addTo(this.parent.map);
                }
            });
            layer.on('remove', () => {
                // [Fix] Safe Removal: Wait one tick to see if layer is moved to another group (e.g. Editor)
                setTimeout(() => {
                    // If layer is back on map (in any group), do not remove label
                    if (this.parent.map.hasLayer(layer)) return;
                    
                    if (layer._pipeLabel) {
                        if (storage) storage.removeLayer(layer._pipeLabel);
                        else this.parent.map.removeLayer(layer._pipeLabel);
                    }
                }, 0);
            });
        }
    }

    recalculateSpatialRelationships() {
        if (!window.turf) return;
        const allSites = []; const allZones = []; const allEquipment = []; const processedIds = new Set();
        const collect = (layer, bucket, filterType) => {
            const id = layer.feature?.properties?.node_id;
            if (!id || processedIds.has(id)) return;
            const type = layer.feature?.properties?.aot_type;
            const subType = layer.feature?.properties?.sub_type || layer.feature?.properties?.feature_type;
            if (filterType === 'container') {
                if (type === 'site' || type === 'zone') {
                    // Pre-calculate BBox for optimization
                    layer._bbox = window.turf.bbox(layer.feature);
                    bucket.push(layer); 
                    processedIds.add(id); 
                }
            } else if (filterType === 'item') {
                if (type === 'equipment' || type === 'aot_device' || subType === 'sprinkler' || (subType && subType.startsWith('pipe'))) { bucket.push(layer); processedIds.add(id); }
            }
        };
        processedIds.clear();
        this.parent.layerStorage['site'].eachLayer(l => collect(l, allSites, 'container'));
        this.parent.layerStorage['zone'].eachLayer(l => collect(l, allZones, 'container'));
        if (window.AoTMapEditor?.featureGroup) {
            window.AoTMapEditor.featureGroup.eachLayer(l => {
                if (l.feature?.properties?.aot_type === 'zone' || l.feature?.properties?.aot_type === 'site') collect(l, (l.feature.properties.aot_type === 'site' ? allSites : allZones), 'container');
                else collect(l, allEquipment, 'item');
            });
        }
        this.parent.layerStorage['equipment'].eachLayer(l => collect(l, allEquipment, 'item'));
        this.parent.layerStorage['aot_device'].eachLayer(l => collect(l, allEquipment, 'item'));

        const _closeRings = (feature) => {
            if (!feature || !feature.geometry) return;
            const closeRing = (ring) => {
                if (ring.length > 1 && (ring[0][0] !== ring[ring.length-1][0] || ring[0][1] !== ring[ring.length-1][1])) ring.push(ring[0]);
            };
            if (feature.geometry.type === 'Polygon') feature.geometry.coordinates.forEach(closeRing);
            else if (feature.geometry.type === 'MultiPolygon') feature.geometry.coordinates.forEach(p => p.forEach(closeRing));
        };
        const checkIn = (pt, container) => {
            const bbox = container._bbox;
            if (bbox && (pt[0] < bbox[0] || pt[0] > bbox[2] || pt[1] < bbox[1] || pt[1] > bbox[3])) return false;
            try {
                _closeRings(container.feature);
                return window.turf.booleanPointInPolygon(window.turf.point(pt), container.feature);
            } catch (_) { return false; }
        };

        allEquipment.forEach(item => {
            if (!item.feature || !item.feature.geometry) return;
            const props = item.feature.properties;
            const subType = props.sub_type || props.feature_type;
            const center = window.turf.center(item.feature).geometry.coordinates;

            let bestZone = null; let bestSite = null;
            for (const zone of allZones) { if (checkIn(center, zone)) { bestZone = zone; break; } }
            if (!bestZone) { for (const site of allSites) { if (checkIn(center, site)) { bestSite = site; break; } } }

            if (bestZone) {
                const zoneId = bestZone.feature.properties.node_id;
                if (subType === 'sprinkler') props.zone_id = zoneId;
                else props.parent_node_id = zoneId;
            } else if (bestSite) {
                const siteId = bestSite.feature.properties.node_id;
                props.parent_node_id = siteId;
                if (subType === 'sprinkler') props.zone_id = null;
            } else {
                if (subType === 'sprinkler') props.zone_id = null;
                props.parent_node_id = null;
            }
        });
        // console.log(`[GeoDesign] Optimized Spatial Re-parenting completed for ${allEquipment.length} items.`);
 
        // Also Rebuild Connections
        this.rebuildConnections();
    }

    rebuildConnections() {
        if (this._isInternalAction) return;
        this._isInternalAction = true;

        try {
            // [V5 Fix] Reverting the restrictive global branch scan from V4.
            this._needsSave = false;
            // console.log("[PipeSystem] Rebuilding all connections...");

            // Phase 3: Replace ALL connection dots in one setData call — no per-dot remove/add churn.
            // 1. Collect current dot features for the replaceCategory call
            const existingFC = { type: 'FeatureCollection', features: [] };
            const collectExisting = (group) => {
                if (!group) return;
                group.eachLayer(l => {
                    const props = l.feature?.properties || l.options;
                    const isConn = props?.aot_type === 'connection'
                        || ['mT', 'mbT', 'bT', 'mE', 'bE', 'tee', 'elbow', 'connection'].includes(props?.sub_type);
                    if (isConn && l.feature) {
                        existingFC.features.push(JSON.parse(JSON.stringify(l.feature)));
                    }
                });
            };
            collectExisting(this.parent.layerStorage['equipment']);
            collectExisting(this.parent.layerStorage['connection']);
            collectExisting(window.AoTMapEditor.featureGroup);

            // 2. Clear wrapper layers from groups (bucket side is cleared by replaceCategory below)
            const clearWrapperLayers = (group) => {
                if (!group) return;
                const toRemove = [];
                group.eachLayer(l => {
                    const props = l.feature?.properties || l.options;
                    const isConn = props?.aot_type === 'connection'
                        || ['mT', 'mbT', 'bT', 'mE', 'bE', 'tee', 'elbow', 'connection'].includes(props?.sub_type);
                    if (isConn) toRemove.push(l);
                });
                toRemove.forEach(l => group.removeLayer(l));
            };
            clearWrapperLayers(this.parent.layerStorage['connection']);
            clearWrapperLayers(this.parent.layerStorage['equipment']);
            clearWrapperLayers(window.AoTMapEditor.featureGroup);

            // 3. Replace the bucket FC (clears all old dots from GL in one setData, no addLayer/removeLayer)
            const connGroup = this.parent.layerStorage['connection'];
            const bucket = connGroup ? RenderBucket.get(connGroup, 'connection-dot') : null;
            if (bucket) {
                bucket.replaceCategory('connection-dot', { type: 'FeatureCollection', features: [] });
            }

            // 4. Collect Pipes
            const pipes = [];
            const collectPipes = (group) => {
                if (!group) return;
                group.eachLayer(l => {
                    const props = l.feature?.properties;
                    if (props && props.sub_type && props.sub_type.startsWith('pipe')) {
                        if (props.connected_main_id) delete props.connected_main_id;
                        pipes.push(l);
                    }
                });
            };
            collectPipes(this.parent.layerStorage['equipment']);
            collectPipes(window.AoTMapEditor.featureGroup);

            // 5. Pairwise Check (Unique) with Spatial Filtering (BBox)
            for (let i = 0; i < pipes.length; i++) {
                const p1 = pipes[i];
                const bbox1 = p1.getBounds();

                for (let j = i + 1; j < pipes.length; j++) {
                    const p2 = pipes[j];
                    if (p1.feature.properties.node_id === p2.feature.properties.node_id) continue;

                    // Spatial Filter: Only check intersection if Bounding Boxes overlap
                    if (bbox1 && p2.getBounds() && bbox1.intersects(p2.getBounds())) {
                        this._detectConnectionBetween(p1, p2, true);
                    }
                }
            }

            // 6. Sync final state to bucket: gather all wrapper-layer features now in the group
            if (connGroup) {
                const finalFC = { type: 'FeatureCollection', features: [] };
                connGroup.eachLayer(l => {
                    if (l.feature) finalFC.features.push(JSON.parse(JSON.stringify(l.feature)));
                });
                const finalBucket = RenderBucket.get(connGroup, 'connection-dot');
                if (finalBucket) {
                    finalBucket.replaceCategory('connection-dot', finalFC);
                }
            }
        } finally {
            this._isInternalAction = false;
            // [V4 Fix] If any trimming occurred during rebuild, trigger save now.
            if (this._needsSave) {
                 // console.log("[PipeSystem] Trimming occurred during rebuild. Triggering AutoSave.");
                 this.parent.saveDesign(null, true);
                 this._needsSave = false;
            }
            // [Fix] Safety-net: apply zoom visibility after GL layers are guaranteed to exist.
            // _desiredVisibility handles the synchronous path; setTimeout(1000) catches the
            // 800ms-deferred doAdd() fallback path (style-not-yet-loaded at creation time).
            const _parent = this.parent;
            setTimeout(() => {
                if (_parent._applyConnectionVisibility) {
                    const _mlMap = (_parent.map && _parent.map._originalMap) || _parent.map;
                    const _minZ = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.equipment_cull_zoom != null)
                        ? window.AOT_GEO_CONFIG.equipment_cull_zoom : 15;
                    const _zoom = _mlMap && _mlMap.getZoom ? _mlMap.getZoom() : 99;
                    _parent._applyConnectionVisibility(_zoom >= _minZ);
                }
            }, 1000);
        }
    }

    /**
     * Scoped Rebuild: Only verify connections for pipes in the vicinity of targetLayer.
     * This avoids massive O(N^2) overhead for large maps.
     * @param {L.Layer} targetLayer - The newly drawn or modified pipe.
     */
    rebuildConnectionsScoped(targetLayer, allLayers = null) {
        if (!targetLayer || this._isInternalAction) return;
        this._isInternalAction = true;

        try {
            // [Optimization] Calculate union bounds if multiple layers provided
            let bounds = targetLayer.getBounds();
            if (allLayers && Array.isArray(allLayers)) {
                allLayers.forEach(l => {
                    if (l.getBounds) bounds.extend(l.getBounds());
                });
            }
            bounds = bounds.pad(0.1); // Add small safety margin

            // Phase 3: use bucket.replaceCategory — no per-dot remove/add churn.
            // 1. Collect existing dot features within bounds for the replaceCategory call
            const existingFC = { type: 'FeatureCollection', features: [] };
            const collectExisting = (group) => {
                if (!group) return;
                group.eachLayer(l => {
                    const props = l.feature?.properties || l.options;
                    const isConn = props?.aot_type === 'connection'
                        || ['mT', 'mbT', 'bT', 'mE', 'bE', 'tee', 'elbow', 'connection'].includes(props?.sub_type);
                    const inBounds = l.getLatLng ? bounds.contains(l.getLatLng()) : true;
                    if (isConn && l.feature && inBounds) {
                        existingFC.features.push(JSON.parse(JSON.stringify(l.feature)));
                    }
                });
            };
            collectExisting(this.parent.layerStorage['equipment']);
            collectExisting(this.parent.layerStorage['connection']);
            collectExisting(window.AoTMapEditor.featureGroup);

            // 2. Remove wrapper layers from groups within bounds
            const clearLocalWrappers = (group) => {
                if (!group) return;
                const toRemove = [];
                group.eachLayer(l => {
                    const props = l.feature?.properties || l.options;
                    const isConn = props?.aot_type === 'connection'
                        || ['mT', 'mbT', 'bT', 'mE', 'bE', 'tee', 'elbow', 'connection'].includes(props?.sub_type);
                    const inBounds = l.getLatLng ? bounds.contains(l.getLatLng()) : false;
                    if (isConn && inBounds) toRemove.push(l);
                });
                toRemove.forEach(l => group.removeLayer(l));
            };
            clearLocalWrappers(this.parent.layerStorage['connection']);
            clearLocalWrappers(this.parent.layerStorage['equipment']);
            clearLocalWrappers(window.AoTMapEditor.featureGroup);

            // 3. Replace bucket FC (clear scoped dots from GL in one setData)
            const connGroup = this.parent.layerStorage['connection'];
            const bucket = connGroup ? RenderBucket.get(connGroup, 'connection-dot') : null;
            if (bucket) {
                bucket.replaceCategory('connection-dot', { type: 'FeatureCollection', features: [] });
            }

            // 4. Collect local pipes within bounds
            const localPipes = [];
            const collectLocalPipes = (group) => {
                if (!group) return;
                group.eachLayer(l => {
                    const props = l.feature?.properties;
                    if (props && props.sub_type && props.sub_type.startsWith('pipe')) {
                        if (l.getBounds().intersects(bounds)) {
                            localPipes.push(l);
                        }
                    }
                });
            };
            collectLocalPipes(this.parent.layerStorage['equipment']);
            collectLocalPipes(window.AoTGeoEditor?.featureGroup);
            collectLocalPipes(window.AoTMapEditor?.featureGroup);

            // 5. Pairwise check limited to the scope
            for (let i = 0; i < localPipes.length; i++) {
                for (let j = i + 1; j < localPipes.length; j++) {
                    const p1 = localPipes[i];
                    const p2 = localPipes[j];
                    if (p1 === p2) continue;
                    if (p1.feature?.properties?.node_id === p2.feature?.properties?.node_id) continue;

                    this._detectConnectionBetween(p1, p2, true);
                }
            }

            // 6. Sync final state to bucket
            if (connGroup) {
                const finalFC = { type: 'FeatureCollection', features: [] };
                connGroup.eachLayer(l => {
                    if (l.feature) finalFC.features.push(JSON.parse(JSON.stringify(l.feature)));
                });
                const finalBucket = RenderBucket.get(connGroup, 'connection-dot');
                if (finalBucket) {
                    finalBucket.replaceCategory('connection-dot', finalFC);
                }
            }
        } finally {
            this._isInternalAction = false;
            const _parent = this.parent;
            setTimeout(() => {
                if (_parent._applyConnectionVisibility) {
                    const _mlMap = (_parent.map && _parent.map._originalMap) || _parent.map;
                    const _minZ = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.equipment_cull_zoom != null)
                        ? window.AOT_GEO_CONFIG.equipment_cull_zoom : 15;
                    const _zoom = _mlMap && _mlMap.getZoom ? _mlMap.getZoom() : 99;
                    _parent._applyConnectionVisibility(_zoom >= _minZ);
                }
            }, 1000);
        }
    }

    _detectConnectionBetween(layerA, layerB, isSilent = false) {
        try {
            const geoA = layerA.toGeoJSON();
            const geoB = layerB.toGeoJSON();
            let intersection = window.turf.lineIntersect(geoA, geoB);

            // Fallback for Touching (Snap) if no intersection found
            if (!intersection || intersection.features.length === 0) {
                const touchPt = this._findTouchingPoint(geoA, geoB);
                if (touchPt) {
                    intersection = { features: [touchPt] };
                }
            }

            if (intersection && intersection.features.length > 0) {
                intersection.features.forEach(pt => {
                    this._analyzeIntersection(layerA, layerB, pt, geoA, geoB, isSilent);
                });
            }
        } catch (e) { }
    }

    // New Helper: Check if endpoints touch the other line
    _findTouchingPoint(geoA, geoB) {
        if (!window.turf) return null;
        const check = (pt, line) => {
            // Use Turf point-to-line distance for robust match
            const dist = window.turf.pointToLineDistance(window.turf.point(pt), line, { units: 'meters' });
            // Tolerance matching _isEndpoint (0.05m - reduced from 0.3m)
            if (dist < 0.05) return window.turf.point(pt);
            return null;
        };
        const coordsA = geoA.geometry.coordinates;
        const startA = coordsA[0];
        const endA = coordsA[coordsA.length - 1];

        let match = check(startA, geoB) || check(endA, geoB);
        if (match) return match;

        const coordsB = geoB.geometry.coordinates;
        const startB = coordsB[0];
        const endB = coordsB[coordsB.length - 1];

        return check(startB, geoA) || check(endB, geoA);
    }

    /**
     * Pipe System Logic: Connection Detection (Tee / Elbow)
     */
    detectAndHandleConnections(newLayer) {
        if (!window.turf || !newLayer) return;
        this.rebuildConnectionsScoped(newLayer);
    }

    /**
     * Selective Splitting: Only split pipe at vertices where angle is 80-110 degrees.
     * This preserves curves (angles outside this range) while enabling Elbow detection.
     */
    processSelectiveSplitting(layer) {
        if (!window.turf || !layer || !layer.toGeoJSON) return null;
        const geo = layer.toGeoJSON();
        if (geo.geometry.type !== 'LineString') return null;

        const coords = geo.geometry.coordinates;
        if (coords.length < 3) return null; // No internal vertices to split

        // Ensure Draw ID exists for inheritance
        if (!layer.feature.properties._aot_draw_id) {
            layer.feature.properties._aot_draw_id = window.uuidv4 ? window.uuidv4() : 'draw-' + Math.random().toString(36).substr(2, 9);
        }

        const splitIndices = [];
        for (let i = 1; i < coords.length - 1; i++) {
            const p1 = coords[i - 1];
            const p2 = coords[i]; // Potential elbow
            const p3 = coords[i + 1];

            // Calculate angle at vertex p2
            const bearing1 = window.turf.bearing(window.turf.point(p2), window.turf.point(p1));
            const bearing2 = window.turf.bearing(window.turf.point(p2), window.turf.point(p3));
            let angle = Math.abs(bearing1 - bearing2);
            if (angle > 180) angle = 360 - angle;

            // Elbow Threshold: 45 - 135 degrees (Relaxed)
            if (angle >= 45 && angle <= 135) {
                splitIndices.push(i);
                // console.log(`[PipeSystem] Selective Split identified at vertex ${i} (Angle: ${angle.toFixed(1)}deg)`);
            }
        }

        if (splitIndices.length === 0) return null;

        // Perform splits (starting from the last to preserve indices)
        const newSegments = [];
        const baseProps = JSON.parse(JSON.stringify(layer.feature.properties));
        const subType = baseProps.sub_type;

        // Remove original
        this.removeLayerSafe(layer);

        let currentCoords = [...coords];
        
        let startIdx = 0;
        for (let i = 0; i < splitIndices.length; i++) {
            const splitIdx = splitIndices[i];
            const segment = currentCoords.slice(startIdx, splitIdx + 1);
            if (segment.length >= 2) {
                newSegments.push(this._createNewSegmentLayer(segment, baseProps));
            }
            startIdx = splitIdx;
        }
        // Last segment
        const lastSegment = currentCoords.slice(startIdx);
        if (lastSegment.length >= 2) {
            newSegments.push(this._createNewSegmentLayer(lastSegment, baseProps));
        }

        return newSegments;
    }

    _createNewSegmentLayer(coords, baseProps) {
        const cleanedCoords = this._cleanCoordinates(coords);
        if (cleanedCoords.length < 2) return null;

        const segmentGeo = { type: 'LineString', coordinates: cleanedCoords };
        const props = JSON.parse(JSON.stringify(baseProps));
        props.node_id = window.uuidv4 ? window.uuidv4() : 'pipe-seg-' + Math.random().toString(36).substr(2, 9);
        
        const feature = { type: 'Feature', properties: props, geometry: segmentGeo };
        const newLayerArr = AoTGeoLayer.fromGeoJSON(feature);
        const newLayer = newLayerArr[0];
        newLayer.feature = feature;

        // Add to storage & map
        if (this.parent.layerStorage['equipment']) this.parent.layerStorage['equipment'].addLayer(newLayer);
        if (window.AoTMapEditor?.featureGroup) window.AoTMapEditor.featureGroup.addLayer(newLayer);
        if (!this.parent.map.hasLayer(newLayer)) newLayer.addTo(this.parent.map);

        return newLayer;
    }

    _analyzeIntersection(layerA, layerB, pointFeature, geoA, geoB, isSilent = false) {
        const ptCoords = pointFeature.geometry.coordinates;
        const isEndpointA = this._isEndpoint(ptCoords, geoA);
        const isEndpointB = this._isEndpoint(ptCoords, geoB);

        const angle = this._calculateIntersectionAngle(geoA, geoB, ptCoords);
        if (angle === null) return;

        // [User Request V4] Elbow Threshold: 45 - 135 degrees
        const isValidAngle = (angle >= 45 && angle <= 135);
        if (!isValidAngle) {
            // console.log(`[PipeSystem] Intersection skipped (Angle: ${angle.toFixed(1)}deg)`);
            return;
        }

        const propsA = layerA.feature.properties;
        const propsB = layerB.feature.properties;
        const subA = propsA.sub_type || '';
        const subB = propsB.sub_type || '';
        
        // Determine Hierarchy (m=Main, b=Branch) - [V8 Sync with geo0102]
        let prefix = 'b';
        if (subA === 'pipe_main' && subB === 'pipe_main') prefix = 'm';
        else if (subA === 'pipe_main' || subB === 'pipe_main') prefix = 'mb';
        
        // Strict guard: only proceed if both are recognized pipes
        if (!subA.startsWith('pipe') || !subB.startsWith('pipe')) return;
 
        // console.log(`[PipeSystem] Analyzing Junction: Type=${prefix}, Angle=${angle.toFixed(1)}deg, EndA=${isEndpointA}, EndB=${isEndpointB}`);
        
        // [Logic Fix] Always attempt trimming for overlaps regardless of endpoint status
        // This ensures that even small overshoots (0.1m - 0.3m) are removed if they part of a 'cross'.
        const changed = this._trimOvershoot(layerA, layerB, ptCoords, true);
        if (changed) {
            // console.log("[PipeSystem] Trimming resolved overlap. Creating Tee marker.");
            const color = this._getTeeColor(prefix, layerA, layerB, subA);
            this.createConnectionDot(ptCoords[1], ptCoords[0], `${prefix}T`, color);
            
            // Link branch to main if applicable
            if (prefix === 'mb') {
                const main = (layerA.feature.properties.sub_type === 'pipe_main') ? layerA : layerB;
                const branch = (layerA.feature.properties.sub_type === 'pipe_main') ? layerB : layerA;
                branch.feature.properties.connected_main_id = main.feature.properties.node_id;
            }
            return;
        }

        if (isEndpointA && isEndpointB) {
            const drawIdA = layerA.feature.properties._aot_draw_id;
            const drawIdB = layerB.feature.properties._aot_draw_id;

            if (drawIdA && drawIdB && drawIdA === drawIdB) {
                // Same drawing operation -> Elbow
                // console.log(`[PipeSystem] Creating Elbow Marker (${prefix}E)`);
                const color = (prefix === 'm') ? '#000000' : '#888888';
                this.createConnectionDot(ptCoords[1], ptCoords[0], `${prefix}E`, color);
            } else {
                // Different operations or overlapping at endpoint -> Tee
                // console.log(`[PipeSystem] Creating Tee Marker (Endpoint Overlay -> ${prefix}T)`);
                const color = this._getTeeColor(prefix, layerA, layerB, subA);
                this.createConnectionDot(ptCoords[1], ptCoords[0], `${prefix}T`, color);
                
                if (prefix === 'mb') {
                    const main = (subA === 'pipe_main') ? layerA : layerB;
                    const branch = (subA === 'pipe_main') ? layerB : layerA;
                    branch.feature.properties.connected_main_id = main.feature.properties.node_id;
                }
            }
        } else if (isEndpointA || isEndpointB) {
            // T-Shape -> Tee
            // console.log(`[PipeSystem] Creating Tee Marker (${prefix}T)`);
            const color = this._getTeeColor(prefix, layerA, layerB, subA);
            this.createConnectionDot(ptCoords[1], ptCoords[0], `${prefix}T`, color);

            if (prefix === 'mb') {
                const main = (subA === 'pipe_main') ? layerA : layerB;
                const branch = (subA === 'pipe_main') ? layerB : layerA;
                branch.feature.properties.connected_main_id = main.feature.properties.node_id;
            }
        }
    }

    _isEndpoint(pt, lineGeo) {
        const coords = lineGeo.geometry.coordinates;
        const start = coords[0];
        const end = coords[coords.length - 1];
        
        const ptTurf = window.turf.point(pt);
        const distStart = window.turf.distance(ptTurf, window.turf.point(start), { units: 'meters' });
        const distEnd = window.turf.distance(ptTurf, window.turf.point(end), { units: 'meters' });
        
        return (distStart < 0.05 || distEnd < 0.05);
    }

    _calculateIntersectionAngle(geoA, geoB, ptCoords) {
        try {
            const pt = window.turf.point(ptCoords);

            const getVectorPoint = (geo) => {
                const coords = geo.geometry.coordinates;
                // Path 1: Simple 2-point segment (Common for split pipes)
                if (coords.length === 2) {
                    const d0 = window.turf.distance(pt, window.turf.point(coords[0]), { units: 'meters' });
                    const d1 = window.turf.distance(pt, window.turf.point(coords[1]), { units: 'meters' });
                    // Pick the coordinate that is further away from the intersection point
                    return (d0 > d1) ? coords[0] : coords[1];
                }

                // Path 2: Multi-segment pipe (Common for main pipes)
                // We need to find the segment that contains the point and get its vector
                for (let i = 0; i < coords.length - 1; i++) {
                    const p1 = coords[i];
                    const p2 = coords[i + 1];
                    const seg = window.turf.lineString([p1, p2]);
                    const distToSeg = window.turf.pointToLineDistance(pt, seg, { units: 'meters' });
                    
                    if (distToSeg < 0.5) {
                        // Found the right segment. Use its dominant endpoint as vector.
                        const d1 = window.turf.distance(pt, window.turf.point(p1), { units: 'meters' });
                        const d2 = window.turf.distance(pt, window.turf.point(p2), { units: 'meters' });
                        return (d1 > d2) ? p1 : p2;
                    }
                }
                return coords[0];
            };

            const vA = getVectorPoint(geoA);
            const vB = getVectorPoint(geoB);

            if (!vA || !vB) return null;

            // [Critial V6 Fix] Do NOT return null for tiny distances.
            // Small overshoots are the MOST important ones to trim. 
            // If distance is too small to calculate bearing, use a fallback bearing (0 or segment angle).
            const distA = window.turf.distance(pt, window.turf.point(vA), { units: 'meters' });
            const distB = window.turf.distance(pt, window.turf.point(vB), { units: 'meters' });
            
            if (distA < 0.0001 || distB < 0.0001) {
                 // Too close for bearing. We can't determine angle, but we shouldn't block trimming.
                 // Return a dummy 90 degree angle to pass the Elbow check and allow _trimOvershoot.
                 return 90; 
            }

            const bearingA = window.turf.bearing(pt, window.turf.point(vA));
            const bearingB = window.turf.bearing(pt, window.turf.point(vB));
            
            if (isNaN(bearingA) || isNaN(bearingB)) return null;

            let diff = Math.abs(bearingA - bearingB);
            if (diff > 180) diff = 360 - diff;
            return diff;
        } catch (e) { 
            // console.warn("[PipeSystem] Angle calculation skipped (geometry edge case)");
            return null; 
        }
    }

    /**
     * [V7 Robust Trim] Implementation based on AoT_v1 Snapping logic.
     * This replaces the unstable vertex-based logic in previous dev versions.
     */
    _trimOvershoot(layerA, layerB, ptCoords, emitEvent = true) {
        const typeA = layerA.feature.properties.sub_type;
        const typeB = layerB.feature.properties.sub_type;
        const isMainA = (typeA === 'pipe_main');
        const isMainB = (typeB === 'pipe_main');

        const scanAndSplit = (layer) => {
            try {
                const geo = layer.toGeoJSON();
                const pt = window.turf.point(ptCoords);
                
                // [V7 Critical] Snap to ensure split works even if point is slightly off
                const snapped = window.turf.nearestPointOnLine(geo, pt);
                
                // LineSplit splits line by point
                const split = window.turf.lineSplit(geo, snapped);
                
                if (!split || split.features.length < 2) return null;
                
                // Return parts with lengths
                return split.features.map(f => ({ 
                    feature: f, 
                    len: window.turf.length(f, { units: 'meters' }) 
                }));
            } catch (e) {
                console.warn("[PipeTrim] Split failed:", e);
                return null;
            }
        };

        let candidates = [];
        // Hierarchy: If one is main, only trim the branch
        if (isMainA && !isMainB) {
            const partsB = scanAndSplit(layerB);
            if (partsB) candidates = partsB.map(p => ({ ...p, layer: layerB, source: partsB }));
        } else if (!isMainA && isMainB) {
            const partsA = scanAndSplit(layerA);
            if (partsA) candidates = candidates.concat(partsA.map(p => ({ ...p, layer: layerA, source: partsA })));
        } else {
            // Both same type: pick shortest
            const partsA = scanAndSplit(layerA);
            if (partsA) candidates = candidates.concat(partsA.map(p => ({ ...p, layer: layerA, source: partsA })));
            const partsB = scanAndSplit(layerB);
            if (partsB) candidates = candidates.concat(partsB.map(p => ({ ...p, layer: layerB, source: partsB })));
        }

        if (candidates.length === 0) return false;

        // [V11 Fix] Selection Logic: Only segments that contain one of the original endpoints should be trimmed.
        // This prevents erroneous trimming of the middle segment of a branch.
        const validOvershoots = candidates.filter(cand => {
            const lineGeo = cand.layer.toGeoJSON();
            const coords = lineGeo.geometry.coordinates;
            const start = coords[0];
            const end = coords[coords.length - 1];
            
            const partCoords = cand.feature.geometry.coordinates;
            const pStart = partCoords[0];
            const pEnd = partCoords[partCoords.length - 1];

            // Use Turf distance for robust coordinate matching (0.01m tolerance)
            const d11 = window.turf.distance(window.turf.point(pStart), window.turf.point(start), { units: 'meters' });
            const d12 = window.turf.distance(window.turf.point(pStart), window.turf.point(end), { units: 'meters' });
            const d21 = window.turf.distance(window.turf.point(pEnd), window.turf.point(start), { units: 'meters' });
            const d22 = window.turf.distance(window.turf.point(pEnd), window.turf.point(end), { units: 'meters' });

            const matchStart = (d11 < 0.01 || d21 < 0.01);
            const matchEnd = (d12 < 0.01 || d22 < 0.01);
            
            return matchStart || matchEnd;
        });


        if (validOvershoots.length === 0) return false;

        validOvershoots.sort((a, b) => a.len - b.len);
        const shortest = validOvershoots[0];

        // Safety: Don't trim 0m segments (vertex match)
        if (shortest.len < 0.01) return false; 

        const maxLen = Math.max(...shortest.source.map(p => p.len));
        
        // [V18 Fix] 10m Absolute Threshold + 0.45 Ratio
        const isSignificant = (shortest.len >= 10.0 && shortest.len >= maxLen * 0.45);

        if (isSignificant) {
            return false;
        }

        const layerToModify = shortest.layer;
        
        // [Fix] Robust selection of part to KEEP.
        const remainingParts = shortest.source.filter(p => p !== shortest);
        remainingParts.sort((a, b) => b.len - a.len);
        
        const keepPart = remainingParts.length > 0 ? remainingParts[0] : null;

        if (keepPart) {
            const cleanedCoords = this._cleanCoordinates(keepPart.feature.geometry.coordinates);
            if (cleanedCoords.length < 2) {
                this.removeLayerSafe(layerToModify);
                
                // [V11 Deletion Persistence]
                const nid = layerToModify.feature?.properties?.node_id;
                if (nid) {
                    if (this.parent.deletedNodeIds) this.parent.deletedNodeIds.add(nid);
                    this.parent.dirtyNodeIds.delete(nid);
                }
                return true;
            }

            // Pure MapLibre: Convert coords to lat/lng pairs manually
            layerToModify.setLatLngs(cleanedCoords.map(coord => ({ lat: coord[1], lng: coord[0] })));
            layerToModify.feature.geometry = { type: 'LineString', coordinates: cleanedCoords };
            if (this.updatePipeLabels) this.updatePipeLabels(layerToModify);
            
            // [V11 Persistence Fix] ALWAYS mark as dirty if modified, 
            // even if internal, to ensure it hits the next save cycle.
            const node_id = layerToModify.feature?.properties?.node_id;
            if (node_id) {
                this.parent.dirtyNodeIds.add(node_id);
            }

            if (emitEvent && !this._isInternalAction) {
                // Immediate manual save
                this.parent.saveDesign(null, true);
                // Pure MapLibre: Dispatch MapLibre Draw edited event
                this.parent.map.fire('edit', { layer: layerToModify });
            } else if (emitEvent) {
                // Deferred save for batch operations
                this._needsSave = true;
            }
            return true;
        }
        return false;

    }


    _getTeeColor(prefix, layerA, layerB, subA) {
        // Tee dot color follows the pipe theme color of the dominant pipe at the junction.
        // - prefix='m'  (main+main):    use a main pipe's color
        // - prefix='mb' (main+branch):  use the main pipe's color
        // - prefix='b'  (branch+branch): use a branch pipe's color
        const pickColor = (layer, subType) => {
            return layer?._styleCache?.color
                || layer?.feature?.properties?.color
                || (subType === 'pipe_main' ? '#007bff' : '#0099ff');
        };
        if (prefix === 'm') {
            return pickColor(layerA, layerA?.feature?.properties?.sub_type);
        }
        if (prefix === 'mb') {
            const main = (subA === 'pipe_main') ? layerA : layerB;
            return pickColor(main, 'pipe_main');
        }
        return pickColor(layerA, layerA?.feature?.properties?.sub_type);
    }

    createConnectionDot(lat, lng, typeCode, color) {
        // Phase 3: Use bucket.upsert directly — no per-instance AoTGeoCircleMarker.
        // This avoids addLayer/removeLayer churn on every rebuildConnections call.
        const _nodeId = 'conn-' + Math.random().toString(36).substr(2, 9);
        const connFeature = {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [lng, lat] },
            properties: {
                aot_type: 'connection',
                sub_type: typeCode,  // mT, mE, tee, elbow, etc.
                no_save: true,
                node_id: _nodeId,
                color: color,
                // _layerId mirrors node_id for bucket upsert key
                _layerId: _nodeId
            }
        };

        // Upsert into connection-dot bucket
        const bucket = RenderBucket.get(this.parent.layerStorage['connection'], 'connection-dot');
        if (bucket) {
            bucket.upsert(_nodeId, connFeature);
        }

        // Also register with AoTGeoLayerGroup so eachLayer() still returns this connection dot
        if (this.parent.layerStorage['connection']) {
            const connGroup = this.parent.layerStorage['connection'];

            // Create a minimal lightweight wrapper so eachLayer() finds it.
            // We do NOT create an AoTGeoCircleMarker (no _toBucketGeoJSON) — the actual
            // rendering is handled exclusively by the bucket. The wrapper's only job is
            // to satisfy layerStorage['connection'].eachLayer() which other code uses.
            const wrapperLayer = {
                _layerId: _nodeId,
                _aotType: 'CircleMarker',
                feature: connFeature,
                _map: null,
                _styleCache: { color: color, fillColor: color, fillOpacity: 1.0 },
                _options: { radius: 4, interactive: false, className: 'aot-connection-dot' },
                _toBucketGeoJSON: function() { return connFeature; },
                toGeoJSON: function() { return connFeature; },
                getLatLng: function() { return { lat: lat, lng: lng }; },
                setStyle: function() { return this; },
                on: function() { return this; },
                off: function() { return this; },
                fire: function() { return this; }
            };
            connGroup.addLayer(wrapperLayer);

            // Ensure group is registered with the map so GL layers are actually rendered
            if (!this.parent.map.hasLayer(connGroup)) {
                this.parent.map.addLayer(connGroup);
            }
        } else {
            // Fallback: direct bucket upsert if connection group not available
            if (bucket) {
                bucket.upsert(_nodeId, connFeature);
            }
        }

        return null; // No marker object returned — callers must not rely on it
    }

    /**
     * Handle Valve Placement: Snap to Pipe & Split
     */
    handleValvePlacement(valveLayer) {
        if (!window.turf || !valveLayer) return;

        const valveGeo = valveLayer.toGeoJSON();
        const pt = valveGeo.geometry.coordinates; // [lng, lat]

        let nearestDist = Infinity;
        let nearestPipe = null;
        let snapPoint = null;

        const checkPipe = (pipeLayer) => {
            const pipeGeo = pipeLayer.toGeoJSON();
            try {
                const snapped = window.turf.nearestPointOnLine(pipeGeo, window.turf.point(pt));
                const dist = window.turf.distance(window.turf.point(pt), snapped, { units: 'meters' });

                if (dist < 0.5 && dist < nearestDist) { // 50cm Threshold
                    nearestDist = dist;
                    nearestPipe = pipeLayer;
                    snapPoint = snapped;
                }
            } catch (e) { /* console.warn("Valve snap check failed:", e); */ }
        };

        // Scan Pipes
        if (window.AoTMapEditor.featureGroup) {
            window.AoTMapEditor.featureGroup.eachLayer(l => {
                if (l.feature?.properties?.sub_type?.startsWith('pipe')) checkPipe(l);
            });
        }
        if (this.parent.layerStorage['equipment']) {
            this.parent.layerStorage['equipment'].eachLayer(l => {
                if (l.feature?.properties?.sub_type?.startsWith('pipe')) checkPipe(l);
            });
        }
 
        if (nearestPipe && snapPoint) {
            // console.log(`[Valve] Snapping to pipe ${nearestPipe.feature.properties.node_id} (Dist: ${nearestDist.toFixed(2)}m)`);
 
            // 1. Move Valve to Snap Point
            const newLng = snapPoint.geometry.coordinates[0];
            const newLat = snapPoint.geometry.coordinates[1];
            valveLayer.setLatLng([newLat, newLng]);
            valveLayer.feature.geometry.coordinates = [newLng, newLat]; // Update GeoJSON ref

            // 2. Split Logic
            // Check if point is strictly ON line (not endpoint)
            const pipeGeo = nearestPipe.toGeoJSON();
            const start = pipeGeo.geometry.coordinates[0];
            const end = pipeGeo.geometry.coordinates[pipeGeo.geometry.coordinates.length - 1];

            // Tolerance dependent on pipe length? Just usage distance.
            const isStart = window.turf.distance(snapPoint, window.turf.point(start), { units: 'meters' }) < 0.05;
            const isEnd = window.turf.distance(snapPoint, window.turf.point(end), { units: 'meters' }) < 0.05;
 
            if (!isStart && !isEnd) {
                // Split!
                // console.log("[Valve] Splitting pipe...");
                const line = window.turf.lineString(pipeGeo.geometry.coordinates);
                const split = window.turf.lineSplit(line, snapPoint);

                if (split.features.length >= 2) {
                    const seg1 = split.features[0];
                    const seg2 = split.features[1];

                    // Setup Seg 2 (New Pipe)
                    const newLoopArr = AoTGeoLayer.fromGeoJSON(seg2);
                    const newLoop = newLoopArr[0];
                    const props = JSON.parse(JSON.stringify(nearestPipe.feature.properties)); // Clone props
                    props.node_id = window.uuidv4 ? window.uuidv4() : 'pipe-' + Date.now();
                    newLoop.feature = { type: 'Feature', margin: 0, properties: props, geometry: seg2.geometry };

                    // Add to map/storage
                    if (this.parent.layerStorage['equipment']) {
                        this.parent.layerStorage['equipment'].addLayer(newLoop);
                        // if nearestPipe was in Editor, add new one to Editor instead?
                        if (window.AoTMapEditor.featureGroup.hasLayer(nearestPipe)) {
                            window.AoTMapEditor.featureGroup.addLayer(newLoop);
                        }
                    }
                    if (this.parent.map.hasLayer(this.parent.layerStorage['equipment'])) {
                        newLoop.addTo(this.parent.map);
                    } else if (window.AoTMapEditor.featureGroup.hasLayer(nearestPipe)) {
                        newLoop.addTo(this.parent.map);
                    }

                    // Update Original Pipe (Seg 1)
                    // Pure MapLibre: Convert coords to lat/lng pairs manually
                    nearestPipe.setLatLngs(seg1.geometry.coordinates.map(coord => ({ lat: coord[1], lng: coord[0] })));
                    nearestPipe.feature.geometry = seg1.geometry;

                    // Add Labels Logic (Recalculate length labels)
                    this.updatePipeLabels(nearestPipe);
                    this.updatePipeLabels(newLoop);
 
                    // console.log(`[Valve] Pipe Split. New ID: ${props.node_id}`);
                }
            } else {
                // console.log("[Valve] Placed at endpoint. No split needed.");
            }
        }
    }

    /**
     * Helper: Clean coordinates to remove consecutive duplicates.
     * Prevents "Invalid Geometry" errors on the backend due to zero-length segments or duplicate points.
     */
    _cleanCoordinates(coords) {
        if (!coords || coords.length < 2) return coords;
        const cleaned = [coords[0]];
        for (let i = 1; i < coords.length; i++) {
            const p1 = coords[i - 1];
            const p2 = coords[i];
            const dist = Math.sqrt(Math.pow(p1[0] - p2[0], 2) + Math.pow(p1[1] - p2[1], 2));
            // Tiny threshold (degrees, roughly < 1cm)
            if (dist > 1e-8) {
                cleaned.push(p2);
            }
        }
        return cleaned;
    }

    /**
     * Helper: Check if a segment is too short to be meaningful.
     */
    _isZeroLength(coords) {
        if (!coords || coords.length < 2) return true;
        try {
            const line = window.turf.lineString(coords);
            const len = window.turf.length(line, { units: 'meters' });
            return len < 0.1; // 10cm threshold
        } catch (e) {
            return true;
        }
    }
}
