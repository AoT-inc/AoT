/**
 * aot-geo-layer.js
 * Pure MapLibre Layer Management for AoTGeoDesign
 * 
 * Provides Leaflet-compatible AoTGeoLayer / AoTGeoLayerGroup APIs backed by MapLibre GL.
 * This replaces the old leaflet-compat.js shim (which required window.L).
 * 
 * Features:
 * - AoTGeoLayerGroup (equivalent to L.FeatureGroup) with eachLayer(), addLayer(), removeLayer()
 * - AoTGeoLayer wrapper with setStyle(), toGeoJSON(), getBounds(), getLatLng(), getRadius(), on(), off()
 * - AoTGeoCircle, AoTGeoMarker, AoTGeoCircleMarker for point types
 * - AoTGeoLayer.fromGeoJSON() for L.geoJSON() replacement
 * - L.DomUtil / L.DomEvent compatibility stubs (mapped to native DOM)
 * 
 * Usage:
 *   const group = new AoTGeoLayerGroup();
 *   group.addLayer(new AoTGeoCircle([lat, lng], { radius: 100 })).addTo(map);
 *   group.eachLayer(l => { ... });
 * 
 * @version 1.0.0 [GIS Pure MapLibre v5.0]
 * @requires maplibre-gl
 */

(function(global) {
    'use strict';

    // =====================================================
    // AoTGeoLayer: Wraps a MapLibre layer with Leaflet-compatible API
    // =====================================================
    class AoTGeoLayer {
        constructor(mapLibreLayer, feature, map) {
            this._mlLayer = mapLibreLayer;   // The MapLibre layer object
            this.feature = feature || { type: 'Feature', properties: {}, geometry: null };
            this._map = map || null;
            this._eventHandlers = {};
            this._styleCache = {};

            // Layer ID for MapLibre source management
            this._layerId = mapLibreLayer?.id || ('aot-layer-' + Math.random().toString(36).substr(2, 9));

            // _aotType: Used for instanceof-equivalent type checks (replaces instanceof L.Circle/Polyline/etc.)
            const geomType = this.feature?.geometry?.type;
            if (geomType === 'Point') this._aotType = 'Marker';
            else if (geomType === 'LineString' || geomType === 'MultiLineString') this._aotType = 'Polyline';
            else if (geomType === 'Polygon' || geomType === 'MultiPolygon') this._aotType = 'Polygon';
            else this._aotType = 'Feature';

            // Attach layer ID back to ML layer for cross-referencing
            if (mapLibreLayer) {
                mapLibreLayer._aotLayer = this;
            }

            // ----- Leaflet-compatible Popup/Tooltip API -----
            this._popup = null;
            this._tooltip = null;
            this._popupContent = null;
            this._tooltipContent = null;
        }

        // ----- Leaflet Popup/Tooltip Methods (MapLibre-compatible) -----
        bindPopup(content, options) {
            this._popupContent = content;
            this._popupOptions = options || {};
            return this;
        }

        bindTooltip(content, options) {
            this._tooltipContent = content;
            this._tooltipOptions = options || {};
            return this;
        }

        unbindPopup() {
            this._popup = null;
            this._popupContent = null;
            return this;
        }

        unbindTooltip() {
            this._tooltip = null;
            this._tooltipContent = null;
            return this;
        }

        getPopup() {
            return this._popup;
        }

        getTooltip() {
            return this._tooltip;
        }

        openPopup(latlng) {
            if (!this._popupContent) return this;
            const pos = latlng || this.getLatLng();
            if (!pos) return this;

            // Create popup element
            const popupEl = document.createElement('div');
            popupEl.className = 'leaflet-popup aot-popup';
            popupEl.style.cssText = 'position:absolute;background:white;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,0.3);padding:10px;min-width:150px;z-index:var(--aot-z-dropdown);';

            const content = typeof this._popupContent === 'function'
                ? this._popupContent(this)
                : this._popupContent;

            if (typeof content === 'string') {
                popupEl.innerHTML = content;
            } else if (content && content.cloneNode) {
                popupEl.appendChild(content.cloneNode(true));
            } else {
                popupEl.innerHTML = String(content);
            }

            // Calculate position (simplified - would need map projection for accuracy)
            const mapContainer = this._map?._mlMap?.getContainer() || document.querySelector('.maplibregl-canvas')?.parentElement;
            if (mapContainer) {
                popupEl.style.left = '50%';
                popupEl.style.bottom = '20px';
                popupEl.style.transform = 'translateX(-50%)';
            }

            // Add close button
            const closeBtn = document.createElement('button');
            closeBtn.innerHTML = '×';
            closeBtn.style.cssText = 'position:absolute;top:2px;right:5px;background:none;border:none;font-size:18px;cursor:pointer;';
            closeBtn.onclick = () => this.closePopup();
            popupEl.appendChild(closeBtn);

            // Store reference
            this._popup = {
                element: popupEl,
                close: () => this.closePopup()
            };

            // Show popup
            const markerContainer = document.querySelector(`[data-aot-layer-id="${this._layerId}"]`) || mapContainer;
            if (markerContainer) {
                markerContainer.style.position = 'relative';
                markerContainer.appendChild(popupEl);
            }

            return this;
        }

        closePopup() {
            if (this._popup && this._popup.element) {
                this._popup.element.remove();
                this._popup = null;
            }
            return this;
        }

        togglePopup() {
            if (this._popup) {
                this.closePopup();
            } else {
                this.openPopup();
            }
            return this;
        }

        openTooltip(latlng) {
            if (!this._tooltipContent) return this;
            // Tooltip implementation similar to popup
            return this;
        }

        closeTooltip() {
            if (this._tooltip && this._tooltip.element) {
                this._tooltip.element.remove();
                this._tooltip = null;
            }
            return this;
        }

        toggleTooltip() {
            if (this._tooltip) {
                this.closeTooltip();
            } else {
                this.openTooltip();
            }
            return this;
        }

        setPopupContent(content) {
            this._popupContent = content;
            if (this._popup) {
                this.closePopup();
            }
            return this;
        }

        setTooltipContent(content) {
            this._tooltipContent = content;
            if (this._tooltip) {
                this.closeTooltip();
            }
            return this;
        }

        // ----- Geometry Access -----
        get id() { return this._layerId; }
        get geometry() { return this.feature?.geometry || null; }
        get properties() { return this.feature?.properties || {}; }
        
        toGeoJSON() {
            if (this.feature) return this.feature;
            // Fallback: reconstruct from layer type
            return { type: 'Feature', properties: this.properties, geometry: this.geometry };
        }

        getBounds() {
            if (!this._map || !this._mlLayer) return null;
            try {
                const source = this._map.getSource('aot-featured-source-' + this._layerId);
                if (source && source._data && source._data.bbox) {
                    const bbox = source._data.bbox;
                    const ne = { lat: bbox[3], lng: bbox[2] };
                    const sw = { lat: bbox[1], lng: bbox[0] };
                    return this._createBoundsObject(ne, sw);
                }
                // Use MapLibre query for bounds
                const data = this._map.querySourceFeatures('aot-featured-source-' + this._layerId);
                if (data && data.length > 0) {
                    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
                    data.forEach(f => {
                        if (f.geometry && f.geometry.coordinates) {
                            this._expandBounds(f.geometry.coordinates, [minX, minY, maxX, maxY]);
                        }
                    });
                    // This is approximate; for precise bounds we'd need turf.js
                    // For now, return a rough estimate using layer coordinates
                }
            } catch (e) {}
            // Fallback: return map center bounds
            if (this._map) {
                const c = this._map.getCenter();
                const ne = { lat: c.lat + 0.01, lng: c.lng + 0.01 };
                const sw = { lat: c.lat - 0.01, lng: c.lng - 0.01 };
                return this._createBoundsObject(ne, sw);
            }
            return null;
        }

        _createBoundsObject(ne, sw) {
            return {
                getNorthEast: () => ({ ...ne }),
                getSouthWest: () => ({ ...sw }),
                intersects: (other) => {
                    if (!other) return false;
                    const ne2 = typeof other.getNorthEast === 'function' ? other.getNorthEast() : other.getNorthEast;
                    const sw2 = typeof other.getSouthWest === 'function' ? other.getSouthWest() : other.getSouthWest;
                    if (!ne || !sw || !ne2 || !sw2) return false;
                    return !(ne.lat < sw2.lat || sw.lat > ne2.lat || ne.lng < sw2.lng || sw.lng > ne2.lng);
                },
                pad: (delta) => {
                    const latPad = (ne.lat - sw.lat) * delta;
                    const lngPad = (ne.lng - sw.lng) * delta;
                    return this._createBoundsObject(
                        { lat: ne.lat + latPad, lng: ne.lng + lngPad },
                        { lat: sw.lat - latPad, lng: sw.lng - lngPad }
                    );
                },
                extend: (other) => {
                    if (!other) return this._createBoundsObject(ne, sw);
                    const otherNe = typeof other.getNorthEast === 'function' ? other.getNorthEast() : other.getNorthEast;
                    const otherSw = typeof other.getSouthWest === 'function' ? other.getSouthWest() : other.getSouthWest;
                    if (!otherNe || !otherSw) return this._createBoundsObject(ne, sw);
                    return this._createBoundsObject(
                        { lat: Math.max(ne.lat, otherNe.lat), lng: Math.max(ne.lng, otherNe.lng) },
                        { lat: Math.min(sw.lat, otherSw.lat), lng: Math.min(sw.lng, otherSw.lng) }
                    );
                },
                getCenter: () => ({
                    lat: (ne.lat + sw.lat) / 2,
                    lng: (ne.lng + sw.lng) / 2
                }),
                contains: (latlng) => {
                    if (!latlng) return false;
                    const lat = typeof latlng.lat === 'function' ? latlng.lat() : latlng.lat;
                    const lng = typeof latlng.lng === 'function' ? latlng.lng() : latlng.lng;
                    if (lat == null || lng == null) return false;
                    return lat >= sw.lat && lat <= ne.lat && lng >= sw.lng && lng <= ne.lng;
                }
            };
        }

        // ----- Circle-specific -----
        getLatLng() {
            const geom = this.geometry;
            if (!geom) return null;
            if (geom.type === 'Point') {
                return { lat: geom.coordinates[1], lng: geom.coordinates[0], alt: geom.coordinates[2] || 0 };
            }
            // For Polygon/Circle approximation, return centroid
            if ((geom.type === 'Polygon' || geom.type === 'MultiPolygon') && window.turf) {
                try {
                    const centroid = window.turf.centroid(this.feature);
                    return { lat: centroid.geometry.coordinates[1], lng: centroid.geometry.coordinates[0], alt: 0 };
                } catch (e) {}
            }
            return { lat: 0, lng: 0, alt: 0 };
        }

        getLatLngs() {
            const geom = this.feature?.geometry;
            if (!geom) return [];
            const toLatLng = (c) => ({
                lat: c[1], lng: c[0],
                distanceTo(other) {
                    const R = 6371000;
                    const φ1 = this.lat * Math.PI / 180, φ2 = other.lat * Math.PI / 180;
                    const Δφ = (other.lat - this.lat) * Math.PI / 180;
                    const Δλ = (other.lng - this.lng) * Math.PI / 180;
                    const a = Math.sin(Δφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(Δλ/2)**2;
                    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
                }
            });
            if (geom.type === 'Polygon') return geom.coordinates.map(ring => ring.map(toLatLng));
            if (geom.type === 'MultiPolygon') return geom.coordinates.map(poly => poly.map(ring => ring.map(toLatLng)));
            if (geom.type === 'LineString') return geom.coordinates.map(toLatLng);
            return [];
        }

        getRadius() {
            return this.properties.radius || this._styleCache._radius || 0;
        }

        /**
         * Leaflet-compatible addTo() method
         * Adds this layer to a map or layer group
         */
        addTo(map) {
            if (!map) return this;
            
            // Delegate only to AoT layer group wrappers, NOT to native MapLibre maps.
            // maplibregl.Map also has addLayer(), so we use _isAoTLayerGroup to distinguish.
            if (map._isAoTLayerGroup) {
                map.addLayer(this);
                return this;
            }
            
            // Store reference to map
            this._map = map;
            
            // If this layer has a placeholder _mlLayer (created by fromGeoJSON), create actual MapLibre layer
            if (this._mlLayer && this.feature) {
                const mlMap = map._mlMap || map;
                const layerId = this._layerId;
                const sourceId = 'aot-source-' + layerId;
                const geomType = this.feature.geometry?.type;
                
                // Determine MapLibre layer type and paint properties
                let mlLayerType = 'fill';
                let paintProps = {};
                if (geomType === 'Point') {
                    mlLayerType = 'circle';
                    paintProps = { 'circle-radius': 6, 'circle-color': '#3388ff' };
                } else if (geomType === 'LineString' || geomType === 'MultiLineString') {
                    mlLayerType = 'line';
                    paintProps = { 'line-color': '#3388ff', 'line-width': 2 };
                } else if (geomType === 'Polygon' || geomType === 'MultiPolygon') {
                    mlLayerType = 'fill';
                    paintProps = { 'fill-color': '#3388ff', 'fill-opacity': 0.3 };
                }

                // Create source with feature data
                if (!mlMap.getSource(sourceId)) {
                    mlMap.addSource(sourceId, {
                        type: 'geojson',
                        data: this.feature
                    });
                }

                // Create layer if not exists
                if (!mlMap.getLayer(layerId)) {
                    mlMap.addLayer({
                        id: layerId,
                        type: mlLayerType,
                        source: sourceId,
                        paint: paintProps
                    });
                }

                // 폴리곤에는 fill 레이어 하나로는 테두리를 낼 수 없다(아래
                // `_ensurePolygonOutline` 설명 참조) — 병행 line 레이어를 만든다.
                if (geomType === 'Polygon' || geomType === 'MultiPolygon') {
                    AoTGeoLayer._ensurePolygonOutline(mlMap, layerId, sourceId);
                }
            }

            return this;
        }

        /**
         * 폴리곤 도형에 테두리 line 레이어를 짝지어 만든다.
         *
         * **MapLibre 의 `fill` 레이어에는 두께 있는 테두리가 없다.** `fill-outline-color`
         * 라는 속성이 있긴 하지만 항상 1px 고정이고 점선도 못 그린다 — 그래서
         * `setStyle()` 이 `weight`/`dashArray` 를 아무리 보내도(예전 코드는 이걸
         * `fill-width`/`fill-dasharray` 로 보냈는데, **그런 속성 자체가 없다** —
         * `setPaintProperty` 가 조용히 실패해 아무 효과가 없었다) 도형에 테두리가
         * 나타나지 않았다(활성 모드 강조는커녕 항상 테두리가 없었다).
         *
         * AoT_map 위젯(`aot-map-widget-vector.js`)은 애초에 이 문제가 없다 —
         * `sites-fill` + `sites-line` 처럼 종류마다 **두 레이어**를 만든다. 여기서도
         * 같은 규약(`<layerId>-line`)을 따른다 — 같은 도형인데 위젯에서는 테두리가
         * 보이고 geo/design 에서는 안 보였던 것이 이 차이 때문이었다.
         */
        /**
         * 폴리곤의 **짝 레이어를 함께 지운다** — 채움만 지우면 테두리가 허공에
         * 남는다(도형을 지웠는데 선만 남아 새로고침해야 사라지는 증상).
         *
         * `-3d`(시설 압출)도 같은 이유로 여기서 함께 지운다. 짝 레이어를 늘릴
         * 때는 반드시 이 함수에도 추가할 것 — 만드는 곳(`_ensurePolygonOutline`)
         * 과 지우는 곳이 갈리면 지울 때만 빠진다.
         */
        static _removeCompanionLayers(mlMap, layerId) {
            if (!mlMap || !layerId || typeof mlMap.removeLayer !== 'function') return;
            ['-line', '-3d'].forEach(suffix => {
                const id = layerId + suffix;
                try { if (mlMap.getLayer(id)) mlMap.removeLayer(id); } catch (e) { /* 이미 없음 */ }
            });
        }

        static _ensurePolygonOutline(mlMap, layerId, sourceId, visibility) {
            const lineId = layerId + '-line';
            if (mlMap.getLayer(lineId)) return;
            try {
                mlMap.addLayer({
                    id: lineId, type: 'line', source: sourceId,
                    // 채움과 **같은 프레임에** 표시 상태를 정한다 — 만든 뒤
                    // 끄면 그 사이 한 프레임 테두리만 번쩍인다.
                    layout: { visibility: visibility || 'visible' },
                    paint: { 'line-color': '#3388ff', 'line-width': 2, 'line-opacity': 1 }
                });
            } catch (e) { /* 스타일 준비 전이면 다음 addTo 에서 다시 시도된다 */ }
        }

        // ----- Styling (Leaflet-style → MapLibre paint) -----
        setStyle(style) {
            this._styleCache = Object.assign({}, style);
            if (!this._map) return this;

            // Use _layerId (actual MapLibre layer ID), not _mlLayer.id (placeholder)
            const layerId = this._layerId;
            const geomType = this.feature?.geometry?.type;
            const isPolygon = (geomType === 'Polygon' || geomType === 'MultiPolygon');

            // Determine layer type from geometry
            let layerType = 'fill';
            if (geomType === 'Point') layerType = 'circle';
            else if (geomType === 'LineString' || geomType === 'MultiLineString') layerType = 'line';
            else if (isPolygon) layerType = 'fill';

            try {
                const mlMap = this._map._mlMap || this._map;
                const paintProps = {};

                // 폴리곤은 fill 레이어에 **채움만** 낸다 — 테두리(color/weight/
                // dashArray)는 아래에서 병행 line 레이어로 보낸다. fill 레이어에는
                // 그런 속성이 없다(위 `_ensurePolygonOutline` 참조).
                if (isPolygon) {
                    if (style.fillColor || style.color) {
                        paintProps['fill-color'] = style.fillColor || style.color;
                    }
                    if (style.fillOpacity !== undefined) paintProps['fill-opacity'] = style.fillOpacity;
                } else {
                    if (style.color) paintProps[layerType + '-color'] = style.color;
                    if (style.fillColor) paintProps['fill-color'] = style.fillColor;
                    if (style.weight !== undefined) paintProps[layerType + '-width'] = style.weight;
                    if (style.opacity !== undefined) paintProps[layerType + '-opacity'] = style.opacity;
                    if (style.dashArray) paintProps[layerType + '-dasharray'] = style.dashArray;
                }
                if (style.radius !== undefined) paintProps['circle-radius'] = style.radius;

                if (Object.keys(paintProps).length > 0) {
                    mlMap.setLayoutProperty(layerId, 'visibility', 'visible');
                    Object.entries(paintProps).forEach(([prop, value]) => {
                        try {
                            mlMap.setPaintProperty(layerId, prop, value);
                        } catch (e) {}
                    });
                }

                if (isPolygon) {
                    const lineId = layerId + '-line';
                    if (mlMap.getLayer(lineId)) {
                        const lineProps = {};
                        if (style.color) lineProps['line-color'] = style.color;
                        if (style.weight !== undefined) lineProps['line-width'] = style.weight;
                        if (style.opacity !== undefined) lineProps['line-opacity'] = style.opacity;
                        mlMap.setLayoutProperty(lineId, 'visibility', 'visible');
                        Object.entries(lineProps).forEach(([prop, value]) => {
                            try { mlMap.setPaintProperty(lineId, prop, value); } catch (e) {}
                        });
                        // dashArray 는 없앨 때도 명시적으로 지워야 한다 — 예전 값이
                        // 남아 있으면 "실선으로 바꿔라" 는 요청이 무시된 것처럼 보인다.
                        try {
                            mlMap.setPaintProperty(lineId, 'line-dasharray',
                                                   style.dashArray || undefined);
                        } catch (e) {}
                    }
                }
            } catch (e) {
                // Silent fail for style updates on non-visible layers
            }
            return this;
        }

        // ----- Events (MapLibre-style, Leaflet-compatible) -----
        on(type, handler, context) {
            if (!this._mlLayer || !this._map) {
                // Store for later attachment
                this._eventHandlers[type] = this._eventHandlers[type] || [];
                this._eventHandlers[type].push({ handler, context });
                return this;
            }
            const wrappedHandler = (e) => {
                e.originalEvent = e.originalEvent || {};
                handler.call(context || this, e);
            };
            this._map.on(type, this._mlLayer.id, wrappedHandler);
            return this;
        }

        off(type, handler) {
            if (!this._mlLayer || !this._map) return this;
            this._map.off(type, this._mlLayer.id, handler);
            return this;
        }

        // Convenience
        bringToFront() {
            // moveLayer() serializes + re-renders the entire style for every call.
            // Connection dots are added last and already appear on top — no-op is safe.
        }

        // ----- Leaflet-compatible addTo() -----
        /**
         * Leaflet-compatible addTo() method
         * Adds this layer to a map or layer group
         * @param {Object} map - Map or layer group to add to
         * @returns {AoTGeoLayer} this
         */
        addTo(map) {
            if (!map) return this;

            // Only delegate to AoTGeoLayerGroup wrappers — NOT to the native MapLibre map or compat shim.
            // The shim also has addLayer() (delegated from native), so we must use _isAoTLayerGroup
            // to distinguish it from a real layer group. Without this guard,
            // shim.addLayer(polygon) → native MapLibre throws "Unknown layer type" and the polygon
            // is never rendered.
            if (map._isAoTLayerGroup) {
                map.addLayer(this);
                return this;
            }

            // Resolve native MapLibre instance (bypass compat shim).
            // The AoTMapLibreCompatShim stores the original map as _originalMap, not _map.
            let mlMap = null;
            if (map._originalMap) {
                // AoTMapLibreCompatShim — _originalMap is the real maplibregl.Map
                mlMap = map._originalMap;
            } else if (map._map) {
                mlMap = map._map;
            } else if (map.getNativeMap) {
                mlMap = map.getNativeMap();
            } else if (map.addSource) {
                // Direct MapLibre map
                mlMap = map;
            }

            // Store map reference (shim or native) for setStyle / event binding
            this._map = map;

            if (!mlMap || !this._mlLayer) return this;

            const layerId = this._layerId;
            const sourceId = 'aot-source-' + layerId;
            const feature = this.feature || this.toGeoJSON();
            const geomType = feature?.geometry?.type;

            // AoTGeoMarker: render as DOM marker (HTML icon), not as GL circle layer
            if (this._aotType === 'Marker') {
                if (!this._mlDomMarker && window.maplibregl) {
                    const latlng = this._latlng;
                    const el = this._icon?.createIcon?.() || (() => { const d = document.createElement('div'); d.style.cssText = 'width:0;height:0;overflow:visible;'; return d; })();
                    this._markerEl = el;
                    // 마커는 GL 이 아니라 DOM 이라 visibility 가 아니라 display
                    // 로 감춘다. 지도에 붙이기 **전에** 정해야 한번도 안 보인다.
                    if (this._desiredVisibility === 'none') el.style.display = 'none';
                    this._mlDomMarker = new window.maplibregl.Marker({ element: el, anchor: 'center', draggable: this._draggable })
                        .setLngLat([latlng.lng, latlng.lat])
                        .addTo(mlMap);
                    const _pt = this.feature?.properties?.parent_type;
                    el.style.zIndex = String(_pt === 'site' ? 5 : _pt === 'zone' ? 3 : 2);
                    this._mlDomMarker.on('dragend', () => {
                        const pos = this._mlDomMarker.getLngLat();
                        this._latlng = { lat: pos.lat, lng: pos.lng };
                        this.feature.geometry.coordinates = [pos.lng, pos.lat];
                        this.fire('dragend');
                    });
                    el.addEventListener('click', (domEvent) => {
                        const isDrawing = window.AoTMapEditor && (
                            window.AoTMapEditor.activeShape ||
                            window.AoTMapEditor.activeDrawer
                        );
                        if (!isDrawing) domEvent.stopPropagation();
                        this.fire('click', { originalEvent: domEvent, stopPropagation: () => domEvent.stopPropagation() });
                    });
                }
                return this;
            }

            // Determine layer spec from geometry
            let mlLayerType = 'fill';
            let paintProps = {};
            if (geomType === 'Point') {
                mlLayerType = 'circle';
                paintProps = { 'circle-radius': 6, 'circle-color': '#3388ff' };
            } else if (geomType === 'LineString' || geomType === 'MultiLineString') {
                // All LineStrings must render via line buckets (pipe-main/branch/reference/generic).
                // Per-instance line creation here would shadow bucket rendering with a stale
                // #3388ff width-2 line. AoTGeoPolyline.addTo() override handles bucket routing.
                return this;
            } else if (geomType === 'Polygon' || geomType === 'MultiPolygon') {
                // Block sprinkler coverage — must only render via the sprinkler-coverage bucket.
                const _bp = feature?.properties || {};
                if (_bp.is_circle || _bp.sub_type === 'sprinkler_coverage' || _bp.drawType === 'circle') {
                    return this;
                }
                mlLayerType = 'fill';
                paintProps = { 'fill-color': '#3388ff', 'fill-opacity': 0.3 };
            }
            const isPolygonGeom = (geomType === 'Polygon' || geomType === 'MultiPolygon');

            const doAddToMap = () => {
                if (!mlMap.getSource(sourceId)) {
                    try {
                        mlMap.addSource(sourceId, { type: 'geojson', data: feature });
                    } catch(e) {
                        console.warn('[AoTGeoLayer] addSource error:', e.message);
                        return;
                    }
                }
                if (!mlMap.getLayer(layerId)) {
                    try {
                        // 표시 상태는 **만들 때 함께** 정한다(그룹 경로와 같은
                        // 규칙) — 만든 뒤 끄면 그 사이 한 프레임이 그려진다.
                        mlMap.addLayer({
                            id: layerId, type: mlLayerType, source: sourceId,
                            paint: paintProps,
                            layout: { visibility: this._desiredVisibility || 'visible' }
                        });
                        // 이 그룹 경로가 geo/design 이 실제로 쓰는 주 생성 경로다
                        // (layerStorage[type].addLayer(layer)) — 테두리
                        // line 레이어도 여기서 만들어야 한다.
                        if (isPolygonGeom) {
                            AoTGeoLayer._ensurePolygonOutline(
                                mlMap, layerId, sourceId, this._desiredVisibility);
                        }
                        // Apply any style that was cached while the layer was pending
                        if (this._styleCache && Object.keys(this._styleCache).length > 0) {
                            this.setStyle(this._styleCache);
                        }
                    } catch(e) {
                        console.warn('[AoTGeoLayer] addLayer error:', layerId, e.message);
                    }
                }
            };

            if (mlMap.isStyleLoaded && mlMap.isStyleLoaded()) {
                doAddToMap();
            } else if (mlMap.once) {
                mlMap.once('load', doAddToMap);
            } else {
                setTimeout(doAddToMap, 500);
            }

            return this;
        }

        // ----- GeoJSON Feature Conversion -----
        _expandBounds(coords, bbox) {
            if (!coords) return;
            if (typeof coords[0] === 'number') {
                // Point
                bbox[0] = Math.min(bbox[0], coords[0]);
                bbox[1] = Math.min(bbox[1], coords[1]);
                bbox[2] = Math.max(bbox[2], coords[0]);
                bbox[3] = Math.max(bbox[3], coords[1]);
            } else {
                coords.forEach(c => this._expandBounds(c, bbox));
            }
        }
    }

    // =====================================================
    // AoTGeoLayerGroup: Manages multiple layers by category
    // Equivalent to L.FeatureGroup
    // =====================================================
    class AoTGeoLayerGroup {
        constructor(id, options) {
            this._id = id || ('aot-lg-' + Math.random().toString(36).substr(2, 9));
            this._layers = new Map(); // layerId → AoTGeoLayer
            this._map = null;
            this._isAoTLayerGroup = true; // Distinguish from native MapLibre map in addTo()
            this.options = Object.assign({ pane: 'overlayPane' }, options);
        }

        get id() { return this._id; }

        addLayer(layer) {
            if (!layer || !layer._layerId) return this;
            this._layers.set(layer._layerId, layer);
            layer._map = this._map;

            // Add to MapLibre map if map is available
            // Bucket-based types (Circle/CircleMarker/Polyline) have no _mlLayer — allow through explicitly
            const _isBucketType = layer._aotType === 'Circle' || layer._aotType === 'CircleMarker' || layer._aotType === 'Polyline';
            if (this._map && (layer._mlLayer || layer._aotType === 'Marker' || _isBucketType)) {
                // Resolve native MapLibre instance — bypass any compat shim, which may
                // not expose isStyleLoaded() and would force the wait-for-load path
                // even after load already fired (causing layers to never render).
                const mlMap = this._map._originalMap
                           || (this._map.getNativeMap && this._map.getNativeMap())
                           || this._map._mlMap
                           || this._map;
                const layerId = layer._layerId;
                const sourceId = 'aot-source-' + layerId;
                const geomType = layer.feature?.geometry?.type;

                // Helper to actually add to MapLibre
                const doAdd = () => {
                    // Connection dot detection: aot_type === 'connection' or known sub_types
                    const _isConnDot = (layer._aotType === 'CircleMarker' || layer._aotType === 'Marker')
                        && (layer.feature?.properties?.aot_type === 'connection'
                            || ['mT', 'mbT', 'bT', 'mE', 'bE', 'tee', 'elbow', 'connection'].includes(layer.feature?.properties?.sub_type));

                    // AoTGeoCircleMarker / AoTGeoMarker connection dots → 'connection-dot' bucket (Phase 3)
                    if (_isConnDot) {
                        layer._map = this._map;
                        const bucket = RenderBucket.get(this, 'connection-dot');
                        if (bucket) {
                            const connGeo = layer._toBucketGeoJSON ? layer._toBucketGeoJSON() : layer.toGeoJSON();
                            bucket.upsert(layer._layerId, connGeo);
                        }
                        return;
                    }

                    // AoTGeoCircle / AoTGeoCircleMarker: delegate to RenderBucket instead of per-instance source/layer
                    if ((layer._aotType === 'Circle' || layer._aotType === 'CircleMarker') && layer._toBucketGeoJSON) {
                        // Sprinkler head center dots are data-only — never render them.
                        // The coverage circle (AoTGeoCircle) handles all visual representation.
                        if (layer.feature?.properties?.sub_type === 'sprinkler') return;
                        layer._map = this._map;

                        // CircleMarker always goes to sprinkler-dot bucket.
                        // Circle goes to sprinkler-coverage bucket only when sub_type === 'sprinkler_coverage'.
                        // All other circles (site/zone/facility) render as per-instance fill layers so
                        // the activeMode visibility system applies to them, not the sprinkler toggle.
                        const isSprinklerBucket = layer._aotType === 'CircleMarker'
                            || layer.feature?.properties?.sub_type === 'sprinkler_coverage';

                        if (isSprinklerBucket) {
                            // Cleanup any pre-existing per-instance source/layer (from stale code paths)
                            // before routing to the bucket, or both would render simultaneously.
                            try { if (mlMap.getLayer(layerId)) mlMap.removeLayer(layerId); } catch(_) {}
                            try { if (mlMap.getSource(sourceId)) mlMap.removeSource(sourceId); } catch(_) {}
                            const category = layer._aotType === 'Circle' ? 'sprinkler-coverage' : 'sprinkler-dot';
                            const bucket = RenderBucket.get(this, category);
                            if (bucket) bucket.upsert(layer._layerId, layer._toBucketGeoJSON());
                            return;
                        }

                        // Non-sprinkler circle: per-instance fill with polygon approximation so
                        // the layer gets its own GL source+layer and participates in mode visibility.
                        // Use !getSource/!getLayer guards (not remove+recreate) to avoid flickering
                        // when the layer is moved between editor and storage on mode switches.
                        const renderPoly = layer._getRenderPolygon ? layer._getRenderPolygon() : layer._toBucketGeoJSON();
                        if (renderPoly) {
                            renderPoly.properties = Object.assign({}, layer.feature?.properties || {});
                            if (!mlMap.getSource(sourceId)) {
                                try { mlMap.addSource(sourceId, { type: 'geojson', data: renderPoly }); } catch(e) {
                                    if (e.message && e.message.includes('not done loading') && mlMap.once) {
                                        mlMap.once('idle', doAdd);
                                    } else {
                                        console.warn('[AoTGeoLayer] circle addSource error:', e.message);
                                    }
                                    return;
                                }
                            }
                            if (!mlMap.getLayer(layerId)) {
                                try {
                                    mlMap.addLayer({ id: layerId, type: 'fill', source: sourceId,
                                        // 원(구역·시설 등)도 같은 규칙 — 만들 때
                                        // 표시 상태를 함께 정해 번쩍임을 막는다.
                                        layout: { visibility: layer._desiredVisibility || 'visible' },
                                        paint: { 'fill-color': '#3388ff', 'fill-opacity': 0.3, 'fill-outline-color': '#3388ff' } });
                                    layer._mlLayer = { id: layerId };
                                    // Apply cached style (set by applyStyle() or setStyle() before GL
                                    // layer existed) so the theme color is visible immediately.
                                    if (layer._styleCache && Object.keys(layer._styleCache).length > 0) {
                                        layer.setStyle(layer._styleCache);
                                    }
                                } catch(e) { console.warn('[AoTGeoLayer] circle addLayer error:', e.message); }
                            }
                        }
                        return;
                    }

                    // AoTGeoPolyline (pipe_main / pipe_branch / reference_line / generic): delegate to RenderBucket
                    if (layer._aotType === 'Polyline' && layer._toBucketGeoJSON) {
                        layer._map = this._map;
                        // Cleanup pre-existing pl-{id} source/layer (created by stale base addTo path).
                        try { if (mlMap.getLayer(layerId)) mlMap.removeLayer(layerId); } catch(_) {}
                        try { if (mlMap.getSource(sourceId)) mlMap.removeSource(sourceId); } catch(_) {}
                        const category = layer._getBucketCategory ? layer._getBucketCategory() : 'line-generic';
                        const bucket = RenderBucket.get(this, category);
                        if (bucket) {
                            bucket.upsert(layer._layerId, layer._toBucketGeoJSON());
                        }
                        return;
                    }

                    // AoTGeoMarker: render as DOM marker (HTML icon), not as GL circle layer
                    // Handled before source creation — DOM markers don't need a GeoJSON source
                    if (layer._aotType === 'Marker') {
                        if (!layer._mlDomMarker && window.maplibregl) {
                            const latlng = layer._latlng || layer.getLatLng?.();
                            const el = layer._icon?.createIcon?.() || (() => { const d = document.createElement('div'); d.style.cssText = 'width:0;height:0;overflow:visible;'; return d; })();
                            layer._markerEl = el;
                            // 마커는 GL 이 아니라 DOM 이라 visibility 가 아니라
                            // display 로 감춘다. 지도에 붙이기 **전에** 정해야
                            // 한번도 안 보인다(붙인 뒤 끄면 한 프레임 깜빡인다).
                            if (layer._desiredVisibility === 'none') el.style.display = 'none';
                            const isLabelAux = layer.feature?.properties?.aot_type === 'label_aux';
                            layer._mlDomMarker = new window.maplibregl.Marker({ element: el, anchor: 'center', draggable: isLabelAux ? true : layer._draggable })
                                .setLngLat([latlng.lng, latlng.lat])
                                .addTo(mlMap);
                            const _pt = layer.feature?.properties?.parent_type;
                            el.style.zIndex = String(_pt === 'site' ? 5 : _pt === 'zone' ? 3 : 2);
                            layer._mlDomMarker.on('dragend', () => {
                                const pos = layer._mlDomMarker.getLngLat();
                                layer._latlng = { lat: pos.lat, lng: pos.lng };
                                if (layer.feature?.geometry) {
                                    layer.feature.geometry.coordinates = [pos.lng, pos.lat];
                                }
                                layer.fire('dragend');
                            });
                            el.addEventListener('click', (domEvent) => {
                                const isDrawing = window.AoTMapEditor && (
                                    window.AoTMapEditor.activeShape ||
                                    window.AoTMapEditor.activeDrawer
                                );
                                if (!isDrawing) domEvent.stopPropagation();
                                layer.fire('click', { originalEvent: domEvent, stopPropagation: () => domEvent.stopPropagation() });
                            });
                        }
                        return;
                    }

                    const feature = layer.feature || layer.toGeoJSON();

                    // Block ALL LineStrings from per-instance creation — they must render via line buckets.
                    // Without this, layers without _aotType='Polyline' (e.g. raw GeoJSON or stale state)
                    // would create #3388ff width-2 default lines that overlay the bucket-rendered pipes.
                    if (geomType === 'LineString' || geomType === 'MultiLineString') {
                        return;
                    }

                    // Block coverage circle Polygons — must only render via sprinkler-coverage bucket.
                    // Catches: is_circle flag, sprinkler_coverage sub_type, drawType='circle'.
                    if ((geomType === 'Polygon' || geomType === 'MultiPolygon') &&
                        (feature?.properties?.is_circle ||
                         feature?.properties?.sub_type === 'sprinkler_coverage' ||
                         feature?.properties?.drawType === 'circle')) {
                        return;
                    }

                    // Create GeoJSON source for this layer
                    if (!mlMap.getSource(sourceId)) {
                        try {
                            mlMap.addSource(sourceId, {
                                type: 'geojson',
                                data: feature
                            });
                        } catch (e) {
                            if (e.message && e.message.includes('not done loading') && mlMap.once) {
                                mlMap.once('idle', doAdd);
                            } else {
                                console.warn('[AoTGeoLayerGroup] addSource error:', e.message);
                            }
                            return;
                        }
                    }

                    // Determine MapLibre layer type
                    let mlLayerType = 'fill';
                    let paintProps = {};
                    if (geomType === 'Point') {
                        mlLayerType = 'circle';
                        const isConnectionDot = feature?.properties?.aot_type === 'connection';
                        if (isConnectionDot) {
                            const _minZ = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.equipment_cull_zoom != null)
                                ? window.AOT_GEO_CONFIG.equipment_cull_zoom : 15;
                            paintProps = {
                                'circle-radius': ['step', ['zoom'], 0, _minZ, layer._options?.radius || 4],
                                'circle-color': '#3388ff'
                            };
                        } else {
                            paintProps = { 'circle-radius': 4, 'circle-color': '#3388ff' };
                        }
                    } else if (geomType === 'LineString' || geomType === 'MultiLineString') {
                        mlLayerType = 'line';
                        paintProps = { 'line-color': '#3388ff', 'line-width': 2 };
                    } else if (geomType === 'Polygon' || geomType === 'MultiPolygon') {
                        mlLayerType = 'fill';
                        paintProps = { 'fill-color': '#3388ff', 'fill-opacity': 0.3 };
                    }
                    const isPolygonGeomIdle = (geomType === 'Polygon' || geomType === 'MultiPolygon');

                    const mlLayerSpec = {
                        id: layerId,
                        type: mlLayerType,
                        source: sourceId,
                        paint: paintProps,
                        // **표시 상태를 만들 때 함께 정한다.** 예전에는 일단
                        // 만들고 아래에서 `setLayoutProperty` 로 껐는데, 생성과
                        // 끄기 사이에 한 프레임이 그려지면 감춘 도형이 번쩍인다.
                        // layout 에 넣으면 그 레이어는 애초에 안 보이는 상태로
                        // 태어나므로 구조적으로 번쩍일 수가 없다.
                        layout: { visibility: layer._desiredVisibility || 'visible' }
                    };

                    if (!mlMap.getLayer(layerId)) {
                        try {
                            mlMap.addLayer(mlLayerSpec);
                            // 스타일이 아직 준비 전이라(`idle` 대기 경로) 여기서도
                            // 병행 line 레이어를 만들어야 한다 — 도형이 이 경로로
                            // 만들어지는 것은 지도 로드 초기(디자인 불러오기)라
                            // 빈도가 낮지 않다.
                            if (isPolygonGeomIdle) {
                                AoTGeoLayer._ensurePolygonOutline(
                                    mlMap, layerId, sourceId, layer._desiredVisibility);
                            }
                            // Apply cached style immediately after layer is created
                            if (layer._styleCache && Object.keys(layer._styleCache).length > 0) {
                                layer.setStyle(layer._styleCache);
                            }
                            // 표시 상태는 위 `mlLayerSpec.layout` 이 이미 정했다 —
                            // 여기서 다시 setLayoutProperty 를 부르지 않는다.
                        } catch (e) {
                            console.warn('[AoTGeoLayerGroup] addLayer error:', e.message);
                        }
                    }

                    // 3D extrusion overlay for facility shapes (Phase 2 — GEO-FACILITY-001)
                    // height_m / eave_h / base_m are injected into properties by
                    // GeoOverlayManager.get_overlays() via GeoFacility join.
                    const isFacility = feature?.properties?.aot_type === 'facility';
                    if (isFacility && (geomType === 'Polygon' || geomType === 'MultiPolygon')) {
                        const extrusionLayerId = layerId + '-3d';
                        if (!mlMap.getLayer(extrusionLayerId)) {
                            try {
                                mlMap.addLayer({
                                    id: extrusionLayerId,
                                    type: 'fill-extrusion',
                                    source: sourceId,
                                    layout: { visibility: 'none' },
                                    paint: {
                                        'fill-extrusion-color': '#82898f',
                                        'fill-extrusion-height': ['coalesce', ['get', 'height_m'], 4],
                                        'fill-extrusion-base':   ['coalesce', ['get', 'base_m'], 0],
                                        'fill-extrusion-opacity': 0.6
                                    }
                                });
                                if (layer._desiredVisibility) {
                                    try { mlMap.setLayoutProperty(extrusionLayerId, 'visibility', layer._desiredVisibility); } catch(_e) {}
                                }
                            } catch (e) {
                                console.warn('[AoTGeoLayerGroup] facility 3D layer error:', e.message);
                            }
                        }
                    }
                };

                // Check if style is loaded
                if (mlMap.isStyleLoaded && mlMap.isStyleLoaded()) {
                    doAdd();
                } else if (mlMap.once) {
                    // Wait for style to be ready.
                    // Guard against the race where 'load' already fired before once() is
                    // registered — in that case the callback never fires, so we add a
                    // setTimeout fallback that calls doAdd() if it still hasn't run.
                    let _doAddFired = false;
                    const _guardedDoAdd = () => { if (!_doAddFired) { _doAddFired = true; doAdd(); } };
                    mlMap.once('load', _guardedDoAdd);
                    setTimeout(_guardedDoAdd, 800);
                } else {
                    // Fallback: add after delay
                    setTimeout(doAdd, 500);
                }
            }
            return this;
        }

        removeLayer(layer) {
            if (!layer) return this;
            const key = typeof layer === 'string' ? layer : layer._layerId;
            const existing = this._layers.get(key);
            this._layers.delete(key);

            if (!existing) return this;
            existing._map = null;

            // DOM marker cleanup (AoTGeoMarker)
            if (existing._mlDomMarker) {
                existing._mlDomMarker.remove();
                existing._mlDomMarker = null;
                return this;
            }

            // RenderBucket cleanup (AoTGeoCircle / AoTGeoCircleMarker)
            if (existing._aotType === 'Circle' || existing._aotType === 'CircleMarker') {
                // Phase 3: connection dots use 'connection-dot' bucket, others use 'sprinkler-dot'
                const isConnDot = existing.feature?.properties?.aot_type === 'connection'
                    || ['mT', 'mbT', 'bT', 'mE', 'bE', 'tee', 'elbow', 'connection'].includes(existing.feature?.properties?.sub_type);
                const isSprinklerBucket = isConnDot
                    || existing._aotType === 'CircleMarker'
                    || existing.feature?.properties?.sub_type === 'sprinkler_coverage';

                if (isSprinklerBucket) {
                    const category = isConnDot ? 'connection-dot' : (existing._aotType === 'Circle' ? 'sprinkler-coverage' : 'sprinkler-dot');
                    const bucket = RenderBucket.get(this._map, category);
                    if (bucket) bucket.remove(existing._layerId);
                    return this;
                }
                // Non-sprinkler circle: fall through to standard GL layer removal below.
            }

            // RenderBucket cleanup (AoTGeoPolyline — pipe categories)
            if (existing._aotType === 'Polyline' && existing._getBucketCategory) {
                const category = existing._getBucketCategory();
                const bucket = RenderBucket.get(this._map, category);
                if (bucket) {
                    bucket.remove(existing._layerId);
                }
                return this;
            }

            // Remove GL layer from MapLibre map
            if (this._map && existing._mlLayer) {
                let mlMap = this._map._originalMap || (this._map.getNativeMap && this._map.getNativeMap()) || this._map._mlMap || this._map;
                if (mlMap && typeof mlMap.removeLayer === 'function') {
                    const layerId = existing._layerId;
                    // 짝 레이어(테두리 -line, 시설 압출 -3d)를 먼저 지운다 —
                    // 같은 소스를 쓰므로 남겨 두면 소스 제거가 막히고, 테두리만
                    // 허공에 남는다.
                    AoTGeoLayer._removeCompanionLayers(mlMap, layerId);
                    if (mlMap.getLayer(layerId)) mlMap.removeLayer(layerId);
                    const sourceId = 'aot-source-' + layerId;
                    if (mlMap.getSource(sourceId)) mlMap.removeSource(sourceId);
                }
            }
            return this;
        }

        hasLayer(layer) {
            if (!layer) return false;
            const key = typeof layer === 'string' ? layer : layer._layerId;
            return this._layers.has(key);
        }

        eachLayer(fn, context) {
            this._layers.forEach((layer, id) => {
                try {
                    fn.call(context || this, layer);
                } catch (e) {}
            });
            return this;
        }

        getLayer(id) {
            return this._layers.get(id);
        }

        getLayers() {
            return Array.from(this._layers.values());
        }

        clearLayers() {
            const mlMap = this._map && (this._map._originalMap || (this._map.getNativeMap && this._map.getNativeMap()) || this._map._mlMap || this._map);
            this._layers.forEach(layer => {
                // Remove DOM markers (AoTGeoMarker)
                if (layer._mlDomMarker) {
                    layer._mlDomMarker.remove();
                    layer._mlDomMarker = null;
                }
                // Remove GL source+layer from native MapLibre map
                if (mlMap && layer._layerId) {
                    const layerId = layer._layerId;
                    const sourceId = 'aot-source-' + layerId;
                    AoTGeoLayer._removeCompanionLayers(mlMap, layerId);
                    try { if (mlMap.getLayer && mlMap.getLayer(layerId)) mlMap.removeLayer(layerId); } catch(e) {}
                    try { if (mlMap.getSource && mlMap.getSource(sourceId)) mlMap.removeSource(sourceId); } catch(e) {}
                }
            });
            this._layers.clear();
            return this;
        }

        addTo(map) {
            this._map = map;
            this._layers.forEach(l => { l._map = map; });
            // Re-add all layers to register them with the new map
            this._layers.forEach(l => this.addLayer(l));
            return this;
        }

        // Convenience: forward to each layer
        setStyle(style) {
            this.eachLayer(l => { if (l.setStyle) l.setStyle(style); });
            return this;
        }

        bringToFront() {
            this.eachLayer(l => { if (l.bringToFront) l.bringToFront(); });
            return this;
        }
    }

    // =====================================================
    // AoTGeoCircle: Circle stored as Point+radius, rendered as polygon approximation
    // =====================================================
    class AoTGeoCircle extends AoTGeoLayer {
        constructor(latlng, options, radius) {
            const r = radius || (options ? options.radius : 100) || 100;
            const centerLng = latlng[1] !== undefined ? latlng[1] : latlng.lng;
            const centerLat = latlng[0] !== undefined ? latlng[0] : latlng.lat;

            // Storage format: Point + radius (compact, no polygon vertices)
            const pointFeature = {
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [centerLng, centerLat] },
                properties: { radius: r, is_circle: true }
            };

            super({ id: 'circle-' + Math.random().toString(36).substr(2, 9), type: 'fill' }, pointFeature);
            this._latlng = { lat: centerLat, lng: centerLng };
            this._radius = r;
            this._options = options || {};
            this._options.radius = r;
            this._aotType = 'Circle';
        }

        getLatLng() { return this._latlng; }
        getRadius() { return this._radius; }

        /** Generate polygon for MapLibre rendering only — NOT stored */
        _getRenderPolygon(steps) {
            steps = steps || 32;
            if (window.turf && window.turf.circle) {
                return window.turf.circle(
                    [this._latlng.lng, this._latlng.lat],
                    this._radius,
                    { steps, units: 'meters' }
                );
            }
            const cosLat = Math.cos(this._latlng.lat * Math.PI / 180);
            const mpd = 111320; // meters per degree lat
            const coords = [];
            for (let i = 0; i <= steps; i++) {
                const a = (i / steps) * 2 * Math.PI;
                coords.push([
                    this._latlng.lng + (this._radius * Math.cos(a)) / (cosLat * mpd),
                    this._latlng.lat + (this._radius * Math.sin(a)) / mpd
                ]);
            }
            return { type: 'Feature', geometry: { type: 'Polygon', coordinates: [coords] }, properties: {} };
        }

        addTo(map) {
            if (!map) return this;
            if (map._isAoTLayerGroup) { map.addLayer(this); return this; }
            this._map = map;
            if (this.feature?.properties?.sub_type === 'sprinkler_coverage') {
                const bucket = RenderBucket.get(map, 'sprinkler-coverage');
                if (bucket) bucket.upsert(this._layerId, this._toBucketGeoJSON());
            } else {
                // Non-sprinkler: per-instance fill with polygon approximation
                const mlMap = map._originalMap || (map.getNativeMap && map.getNativeMap()) || map._mlMap || map;
                const layerId = this._layerId;
                const sourceId = 'aot-source-' + layerId;
                const renderPoly = this._getRenderPolygon();
                if (renderPoly && mlMap && mlMap.addSource) {
                    renderPoly.properties = Object.assign({}, this.feature?.properties || {});
                    if (!mlMap.getSource(sourceId)) {
                        try { mlMap.addSource(sourceId, { type: 'geojson', data: renderPoly }); } catch(e) {}
                    }
                    if (!mlMap.getLayer(layerId)) {
                        try {
                            mlMap.addLayer({ id: layerId, type: 'fill', source: sourceId,
                                paint: { 'fill-color': '#3388ff', 'fill-opacity': 0.3, 'fill-outline-color': '#3388ff' } });
                            this._mlLayer = { id: layerId };
                        } catch(e) {}
                    }
                }
            }
            return this;
        }

        setRadius(r) {
            this._radius = r;
            this.feature.properties.radius = r;
            if (this._map && this._map._isAoTLayerGroup) {
                // delegated to group — bucket sync handled by group layer management
            }
            if (this._map) {
                if (this.feature?.properties?.sub_type === 'sprinkler_coverage') {
                    const bucket = RenderBucket.get(this._map, 'sprinkler-coverage');
                    if (bucket) {
                        bucket.setStyle(this._layerId, { radius: r });
                        bucket.upsert(this._layerId, this._toBucketGeoJSON());
                    }
                } else {
                    // Non-sprinkler: update per-instance GL source data
                    const mlMap = this._map._originalMap || this._map._mlMap || this._map;
                    const sourceId = 'aot-source-' + this._layerId;
                    const src = mlMap && mlMap.getSource && mlMap.getSource(sourceId);
                    if (src) {
                        const renderPoly = this._getRenderPolygon();
                        if (renderPoly) {
                            renderPoly.properties = Object.assign({}, this.feature?.properties || {});
                            src.setData(renderPoly);
                        }
                    }
                }
            }
        }

        setStyle(style) {
            this._styleCache = Object.assign({}, style);
            if (!this._map) return this;
            if (this.feature?.properties?.sub_type === 'sprinkler_coverage') {
                const bucket = RenderBucket.get(this._map, 'sprinkler-coverage');
                if (bucket) {
                    bucket.setStyle(this._layerId, {
                        color: style.fillColor || style.color,
                        fillColor: style.fillColor || style.color,
                        fillOpacity: style.fillOpacity,
                        strokeColor: style.color || style.fillColor,
                        strokeWidth: style.weight
                    });
                }
            } else {
                // Non-sprinkler: update per-instance GL fill paint properties directly.
                // Cannot use AoTGeoLayer.setStyle() here because that reads feature.geometry.type
                // ('Point') and would set circle-* paint properties instead of fill-*.
                const mlMap = this._map._originalMap || this._map._mlMap || this._map;
                if (mlMap && mlMap.setPaintProperty) {
                    const layerId = this._layerId;
                    try {
                        const fc = style.fillColor || style.color;
                        if (fc) {
                            mlMap.setPaintProperty(layerId, 'fill-color', fc);
                            mlMap.setPaintProperty(layerId, 'fill-outline-color', style.color || fc);
                        }
                        if (style.fillOpacity != null) mlMap.setPaintProperty(layerId, 'fill-opacity', style.fillOpacity);
                    } catch(e) {}
                }
            }
            return this;
        }

        /** Returns compact Point+radius GeoJSON (no polygon vertices stored) */
        toGeoJSON() {
            return {
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [this._latlng.lng, this._latlng.lat] },
                properties: Object.assign({}, this.feature.properties, { radius: this._radius, is_circle: true })
            };
        }

        /**
         * Internal: build the GeoJSON payload for RenderBucket.
         * Returns a Polygon feature (circle approximation) so the fill layer lies on the
         * map surface and correctly shows perspective distortion when the map is tilted.
         * (MapLibre `circle` type is screen-space and always faces the camera, which is
         *  unsuitable for ground-plane area rendering.)
         *
         * The polygon is rendered via a SINGLE shared bucket source+layer (one per category),
         * so we still get the O(c) MapLibre layer count benefit despite using fill geometry.
         */
        _toBucketGeoJSON() {
            const steps = this._options?.renderSteps || 32;
            const polyFeature = this._getRenderPolygon(steps);
            polyFeature.properties = Object.assign({}, this.feature?.properties || {}, {
                radius: this._radius,
                is_circle: true,
                color: this._styleCache?.color || this._styleCache?.fillColor || '#007bff',
                fillColor: this._styleCache?.fillColor || this._styleCache?.color || '#007bff',
                fillOpacity: this._styleCache?.fillOpacity !== undefined ? this._styleCache.fillOpacity : 0.3,
                strokeColor: this._styleCache?.color || this._styleCache?.fillColor || '#007bff',
                strokeWidth: this._styleCache?.weight !== undefined ? this._styleCache.weight : 1,
                strokeOpacity: this._styleCache?.opacity !== undefined ? this._styleCache.opacity : 0.8
            });
            return polyFeature;
        }
    }

    // =====================================================
    // AoTGeoCircleMarker: Small circle (map units, not meters)
    // =====================================================
    class AoTGeoCircleMarker extends AoTGeoLayer {
        constructor(latlng, options) {
            const feature = {
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [latlng[1] || latlng.lng, latlng[0] || latlng.lat] },
                properties: Object.assign({}, options, { _isCircleMarker: true })
            };
            super({ id: 'cm-' + Math.random().toString(36).substr(2, 9), type: 'circle' }, feature);
            this._latlng = { lat: latlng[0] || latlng.lat, lng: latlng[1] || latlng.lng };
            this._options = options || {};
            this._aotType = 'CircleMarker';  // Override for CircleMarker type checks
        }

        getLatLng() { return this._latlng; }
        getRadius() { return this._options.radius || 2; }

        setStyle(style) {
            // Merge into _styleCache for _toBucketGeoJSON
            this._styleCache = Object.assign({}, this._options, style);
            if (!this._map) return this;
            const bucket = RenderBucket.get(this._map, 'sprinkler-dot');
            if (bucket) {
                bucket.setStyle(this._layerId, {
                    color: style.color,
                    fillColor: style.fillColor,
                    fillOpacity: style.fillOpacity,
                    strokeColor: style.strokeColor
                });
            }
            return this;
        }

        setLatLng(latlng) {
            this._latlng = { lat: latlng.lat || latlng[0], lng: latlng.lng || latlng[1] };
            this.feature.geometry.coordinates = [this._latlng.lng, this._latlng.lat];
            if (this._map) {
                const bucket = RenderBucket.get(this._map, 'sprinkler-dot');
                if (bucket) {
                    bucket.upsert(this._layerId, this._toBucketGeoJSON());
                }
            }
            return this;
        }

        setRadius(r) {
            this._options.radius = r;
            this.feature.properties.radius = r;
            if (this._map) {
                const bucket = RenderBucket.get(this._map, 'sprinkler-dot');
                if (bucket) {
                    bucket.setStyle(this._layerId, { radius: r });
                    bucket.upsert(this._layerId, this._toBucketGeoJSON());
                }
            }
        }

        on(eventType, handler) {
            this._eventHandlers = this._eventHandlers || {};
            this._eventHandlers[eventType] = this._eventHandlers[eventType] || [];
            this._eventHandlers[eventType].push(handler);
            return this;
        }

        off(eventType, handler) {
            if (this._eventHandlers && this._eventHandlers[eventType]) {
                if (handler) {
                    this._eventHandlers[eventType] = this._eventHandlers[eventType].filter(h => h !== handler);
                } else {
                    delete this._eventHandlers[eventType];
                }
            }
            return this;
        }

        fire(eventType, data) {
            if (this._eventHandlers && this._eventHandlers[eventType]) {
                this._eventHandlers[eventType].forEach(h => {
                    try { h(data); } catch (e) { console.error(e); }
                });
            }
            return this;
        }

        getElement() {
            return document.querySelector(`[data-aot-cm-id="${this._layerId}"]`);
        }

        /** Add to map via RenderBucket (sprinkler-dot category) */
        addTo(map) {
            if (!map) return this;
            if (map._isAoTLayerGroup) { map.addLayer(this); return this; }
            // Sprinkler head center dot — data container only, never render
            if (this.feature?.properties?.sub_type === 'sprinkler') return this;
            this._map = map;
            const bucket = RenderBucket.get(map, 'sprinkler-dot');
            if (bucket) {
                bucket.upsert(this._layerId, this._toBucketGeoJSON());
            }
            return this;
        }

        /** Build GeoJSON payload for RenderBucket */
        _toBucketGeoJSON() {
            const style = this._styleCache || this._options || {};
            const props = Object.assign({}, this.feature.properties, {
                radius: this._options.radius || 2,
                color: style.color || '#DF5353',
                fillColor: style.fillColor || style.color || '#DF5353',
                fillOpacity: style.fillOpacity !== undefined ? style.fillOpacity : 1,
                strokeColor: style.strokeColor || style.color || '#DF5353',
                strokeWidth: style.strokeWidth !== undefined ? style.strokeWidth : 0
            });
            return {
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [this._latlng.lng, this._latlng.lat] },
                properties: props
            };
        }

        setRadius(r) {
            this._options.radius = r;
            this.feature.properties.radius = r;
            if (this._map) {
                const bucket = RenderBucket.get(this._map, 'sprinkler-dot');
                if (bucket) {
                    bucket.setStyle(this._layerId, { radius: r });
                    bucket.upsert(this._layerId, this._toBucketGeoJSON());
                }
            }
        }

        /** Returns compact Point GeoJSON for backend storage */
        toGeoJSON() {
            return {
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [this._latlng.lng, this._latlng.lat] },
                properties: Object.assign({}, this.feature.properties)
            };
        }
    }

    // =====================================================
    // AoTGeoMarker: Icon marker
    // =====================================================
    class AoTGeoMarker extends AoTGeoLayer {
        constructor(latlng, options) {
            const feature = {
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [latlng[1] || latlng.lng, latlng[0] || latlng.lat] },
                properties: Object.assign({}, options || {}, { _isMarker: true })
            };
            super({ id: 'mk-' + Math.random().toString(36).substr(2, 9), type: 'symbol' }, feature);
            this._latlng = { lat: latlng[0] || latlng.lat, lng: latlng[1] || latlng.lng };
            this._aotType = 'Marker';  // Override for Marker type checks
            this._options = options || {};
            this._draggable = options?.draggable || false;
            this._zIndexOffset = options?.zIndexOffset || 0;
            this._eventHandlers = {};
            this._icon = options?.icon || null;
        }

        getLatLng() { return this._latlng; }

        setLatLng(latlng) {
            this._latlng = { lat: latlng.lat || latlng[0], lng: latlng.lng || latlng[1] };
            this.feature.geometry.coordinates = [this._latlng.lng, this._latlng.lat];
            if (this._mlDomMarker) {
                this._mlDomMarker.setLngLat([this._latlng.lng, this._latlng.lat]);
            }
            if (this._map && this._map.fire) {
                this._map.fire('layerupdate', { layer: this });
            }
            return this;
        }

        setIcon(icon) {
            this._icon = icon;
            if (icon?.createIcon) {
                const newEl = icon.createIcon();
                if (this._mlDomMarker) {
                    // Replace content in existing DOM marker element.
                    // Do NOT replace style.cssText — MapLibre stores the marker's
                    // screen position in a CSS transform on this element. Overwriting
                    // cssText wipes the transform, teleporting the marker to top-left
                    // until the next map move triggers a repaint.
                    const existing = this._mlDomMarker.getElement();
                    if (existing) {
                        existing.innerHTML = newEl.innerHTML;
                        // Preserve MapLibre-managed classes (maplibregl-*) while
                        // replacing our custom classes. Without this, maplibregl-marker
                        // is removed, breaking the absolute positioning that puts the
                        // marker at the correct lat/lng.
                        const mlClasses = Array.from(existing.classList).filter(c => c.startsWith('maplibregl-'));
                        const newClasses = newEl.className ? newEl.className.split(' ').filter(c => c) : [];
                        existing.className = [...newClasses, ...mlClasses].join(' ');
                        // Only sync non-transform style properties
                        existing.style.overflow = newEl.style.overflow || 'visible';
                        existing.style.width = newEl.style.width || '0';
                        existing.style.height = newEl.style.height || '0';
                    }
                } else {
                    // Icon stored for use when addTo/addLayer is called later
                    this._markerEl = newEl;
                }
            }
            if (this._map && this._map.fire) {
                this._map.fire('layerupdate', { layer: this });
            }
            return this;
        }

        on(eventType, handler) {
            this._eventHandlers[eventType] = this._eventHandlers[eventType] || [];
            this._eventHandlers[eventType].push(handler);
            return this;
        }

        off(eventType, handler) {
            if (this._eventHandlers[eventType]) {
                if (handler) {
                    this._eventHandlers[eventType] = this._eventHandlers[eventType].filter(h => h !== handler);
                } else {
                    delete this._eventHandlers[eventType];
                }
            }
            return this;
        }

        fire(eventType, data) {
            if (this._eventHandlers[eventType]) {
                this._eventHandlers[eventType].forEach(h => {
                    try { h(data); } catch (e) { console.error(e); }
                });
            }
            return this;
        }

        getElement() {
            return document.querySelector(`[data-aot-marker-id="${this._layerId}"]`);
        }

        setDraggable(enabled) {
            this._draggable = enabled;
            if (this._mlDomMarker) {
                this._mlDomMarker.setDraggable(enabled);
            }
            return this;
        }
    }

    // =====================================================
    // AoTGeoPolyline / AoTGeoPolygon
    // =====================================================
    class AoTGeoPolyline extends AoTGeoLayer {
        constructor(coordinates, options) {
            const feature = {
                type: 'Feature',
                geometry: { type: 'LineString', coordinates: coordinates },
                properties: Object.assign({}, options || {})
            };
            super({ id: 'pl-' + Math.random().toString(36).substr(2, 9), type: 'line' }, feature);
            this._aotType = 'Polyline';
            this._styleCache = Object.assign({}, options || {});
        }

        /**
         * Determine the RenderBucket category from feature properties.sub_type.
         * Falls back to 'line-generic' for unknown LineString types.
         */
        _getBucketCategory() {
            const subType = this.feature?.properties?.sub_type || this._styleCache?.sub_type;
            if (subType === 'pipe_main')    return 'pipe-main';
            if (subType === 'pipe_branch') return 'pipe-branch';
            if (subType === 'reference_line') return 'pipe-reference';
            return 'line-generic';
        }

        /**
         * Build GeoJSON payload for RenderBucket upsert.
         * Includes all style + geometry properties needed by bucket paint expressions.
         */
        _toBucketGeoJSON() {
            const style = this._styleCache || {};
            const props = Object.assign({}, this.feature.properties || {}, {
                // style props for line paint expressions
                color: style.color || this.feature.properties?.color || this._getDefaultColor(),
                weight: style.weight !== undefined ? style.weight : this._getDefaultWeight(),
                opacity: style.opacity !== undefined ? style.opacity : 1,
                dashArray: style.dashArray || this.feature.properties?.dashArray || null
            });
            return {
                type: 'Feature',
                geometry: { type: 'LineString', coordinates: this.feature.geometry.coordinates },
                properties: props
            };
        }

        _getDefaultColor() {
            const subType = this.feature?.properties?.sub_type;
            if (subType === 'pipe_main')    return '#0099ff';
            if (subType === 'pipe_branch')  return '#007bff';
            if (subType === 'reference_line') return '#999999';
            return '#888888';
        }

        _getDefaultWeight() {
            const subType = this.feature?.properties?.sub_type;
            if (subType === 'pipe_main')    return 4;
            if (subType === 'pipe_branch')  return 2;
            if (subType === 'reference_line') return 1;
            return 2;
        }

        /**
         * setStyle — delegates to RenderBucket for bucket-registered layers.
         * Style is cached and patched into feature.properties so flush picks it up.
         */
        setStyle(style) {
            this._styleCache = Object.assign({}, this._styleCache || {}, style);
            if (!this._map) return this;
            const category = this._getBucketCategory();
            const bucket = RenderBucket.get(this._map, category);
            if (bucket && bucket.has(this._layerId)) {
                bucket.setStyle(this._layerId, {
                    color: style.color,
                    weight: style.weight,
                    opacity: style.opacity,
                    dashArray: style.dashArray
                });
            }
            // Fallback: if bucket not yet initialized, apply via base class
            // This handles the edge case where setStyle is called before the layer
            // is added to a bucket-registered group (e.g., before addTo/addLayer fires).
            if (!bucket || !bucket.has(this._layerId)) {
                // Delegate to base class setStyle which applies paint properties directly
                // to the GL layer (works for non-bucket paths or pre-initialization).
                return AoTGeoLayer.prototype.setStyle.call(this, style);
            }
            return this;
        }

        /**
         * addTo — for bucket categories (pipe_main, pipe_branch, reference_line, generic line),
         * delegate to RenderBucket instead of per-instance source/layer.
         */
        addTo(map) {
            if (!map) return this;
            if (map._isAoTLayerGroup) {
                map.addLayer(this);
                return this;
            }
            this._map = map;
            const category = this._getBucketCategory();
            const bucket = RenderBucket.get(map, category);
            if (bucket) {
                bucket.upsert(this._layerId, this._toBucketGeoJSON());
            }
            return this;
        }

        /**
         * setLatLngs — update LineString coordinates and sync to RenderBucket.
         * Called by geometry._trimOvershoot, processPipeTrimming, etc.
         */
        setLatLngs(latlngs) {
            if (!latlngs || !Array.isArray(latlngs)) return this;
            this.feature.geometry.coordinates = latlngs.map(ll =>
                [ll.lng !== undefined ? ll.lng : ll[1], ll.lat !== undefined ? ll.lat : ll[0]]
            );
            if (this._map) {
                const category = this._getBucketCategory();
                const bucket = RenderBucket.get(this._map, category);
                if (bucket) {
                    bucket.upsert(this._layerId, this._toBucketGeoJSON());
                }
            }
            return this;
        }

        /**
         * toGeoJSON — returns stored coordinates (no polygon expansion, unlike circles).
         */
        toGeoJSON() {
            return {
                type: 'Feature',
                geometry: Object.assign({}, this.feature.geometry),
                properties: Object.assign({}, this.feature.properties)
            };
        }
    }

    class AoTGeoPolygon extends AoTGeoLayer {
        constructor(coordinates, options) {
            // Ensure closed ring
            let coords = coordinates;
            if (coords && coords.length > 0) {
                const first = coords[0][0];
                const last = coords[coords.length - 1];
                if (first[0] !== last[0] || first[1] !== last[1]) {
                    coords = [...coords, [first[0], first[1]]];
                }
            }
            const feature = {
                type: 'Feature',
                geometry: { type: 'Polygon', coordinates: [coords] },
                properties: Object.assign({}, options || {})
            };
            super({ id: 'pg-' + Math.random().toString(36).substr(2, 9), type: 'fill' }, feature);
            this._aotType = 'Polygon';
        }

        addTo(map) {
            // Block sprinkler coverage polygons — must only render via the circle-type bucket.
            const props = this.feature?.properties || {};
            if (props.is_circle || props.sub_type === 'sprinkler_coverage' || props.drawType === 'circle') {
                return this;
            }
            return super.addTo(map);
        }
    }

    // =====================================================
    // L.geoJSON replacement: AoTGeoLayer.fromGeoJSON
    // =====================================================
    AoTGeoLayer.fromGeoJSON = function(geojson, options) {
        const opts = options || {};
        const layers = [];
        const features = geojson.features || (geojson.type === 'Feature' ? [geojson] : []);

        features.forEach((feature, idx) => {
            const geomType = feature.geometry?.type;
            const coords = feature.geometry?.coordinates;
            if (!coords) return;

            let layer;
            if (geomType === 'Point') {
                const props = feature.properties || {};
                if ((props.is_circle || props.drawType === 'circle' || props.sub_type === 'sprinkler_coverage') && props.radius) {
                    layer = new AoTGeoCircle([coords[1], coords[0]], { radius: props.radius }, props.radius);
                } else {
                    layer = new AoTGeoCircleMarker([coords[1], coords[0]], opts.circleMarkerOptions || {});
                }
            } else if (geomType === 'LineString') {
                layer = new AoTGeoPolyline(coords, opts.polylineOptions || {});
            } else if (geomType === 'Polygon' || geomType === 'MultiPolygon') {
                // Recover circle from Polygon-format storage: replace AoTGeoPolygon with
                // AoTGeoCircle directly so the polygon never enters loadedLayers and cannot
                // create a fill GL layer downstream. _processLoadedFeature will see Point
                // geometry and skip its own recovery path (no double-handling).
                const _polyProps = feature.properties || {};
                const _isCircleLike = (_polyProps.is_circle || _polyProps.drawType === 'circle' ||
                                       _polyProps.sub_type === 'sprinkler_coverage') && _polyProps.radius;
                if (_isCircleLike) {
                    let center;
                    if (_polyProps.center_lat != null && _polyProps.center_lng != null) {
                        center = [_polyProps.center_lat, _polyProps.center_lng];
                    } else if (window.turf && window.turf.centroid) {
                        const c = window.turf.centroid(feature);
                        center = [c.geometry.coordinates[1], c.geometry.coordinates[0]];
                    } else {
                        const ring = (geomType === 'MultiPolygon' ? coords[0]?.[0] : coords[0]) || [];
                        let sx = 0, sy = 0;
                        ring.forEach(p => { sx += p[0]; sy += p[1]; });
                        center = [sy / ring.length, sx / ring.length];
                    }
                    layer = new AoTGeoCircle(center, { radius: _polyProps.radius }, _polyProps.radius);
                } else if (geomType === 'Polygon') {
                    layer = new AoTGeoPolygon(coords, opts.polygonOptions || {});
                } else {
                    layer = new AoTGeoPolygon(coords[0] || [[0,0]], opts.polygonOptions || {});
                }
            } else if (geomType === 'MultiLineString') {
                layer = new AoTGeoPolyline(coords[0] || [[0,0]], opts.polylineOptions || {});
            }

            if (layer) {
                // For Polygon→Circle recovery, preserve the AoTGeoCircle's Point geometry.
                // Overwriting layer.feature with the original Polygon feature would cause:
                //   1) doAdd() to see Polygon geometry and (without guard) create fill layer
                //   2) _processLoadedFeature recovery to fire again, creating a 2nd circle
                if (layer._aotType === 'Circle' && (geomType === 'Polygon' || geomType === 'MultiPolygon')) {
                    if (feature.properties) {
                        Object.assign(layer.feature.properties, feature.properties);
                        // Re-assert Point invariant after property merge
                        layer.feature.properties.is_circle = true;
                    }
                } else {
                    layer.feature = JSON.parse(JSON.stringify(feature));
                    if (feature.properties) {
                        Object.assign(layer.feature.properties, feature.properties);
                    }
                }

                // pointToLayer MUST run before onEachFeature so callbacks receive the correct layer type.
                // (e.g. label_aux Points must be AoTGeoMarker before convertToLabel is called)
                if (opts.pointToLayer && geomType === 'Point') {
                    const ptLayer = opts.pointToLayer(feature, layer.getLatLng() || { lat: 0, lng: 0 });
                    if (ptLayer) {
                        ptLayer.feature = layer.feature;
                        layer = ptLayer;
                    }
                }

                layers.push(layer);

                if (opts.onEachFeature) {
                    opts.onEachFeature(feature, layer);
                }
            }
        });

        return layers;
    };

    // =====================================================
    // L.DomUtil / L.DomEvent compatibility (mapped to native DOM)
    // =====================================================
    const DomUtil = {
        addClass: function(el, name) {
            if (!el || !name) return;
            if (typeof el === 'string') el = document.getElementById(el);
            if (el && el.classList) el.classList.add(name);
        },
        removeClass: function(el, name) {
            if (!el || !name) return;
            if (typeof el === 'string') el = document.getElementById(el);
            if (el && el.classList) el.classList.remove(name);
        },
        create: function(tagName, className, container) {
            const el = document.createElement(tagName || 'div');
            if (className) el.className = className;
            if (container) container.appendChild(el);
            return el;
        },
        get: function(id) {
            return typeof id === 'string' ? document.getElementById(id) : id;
        },
        remove: function(el) {
            if (el && el.parentNode) el.parentNode.removeChild(el);
        },
        setTransform: function() {},
        setPosition: function() {}
    };

    const DomEvent = {
        on: function(el, type, fn, context) {
            if (!el || !type || !fn) return;
            if (typeof el === 'string') el = document.getElementById(el);
            if (el) el.addEventListener(type, fn.bind(context || this));
        },
        off: function(el, type, fn) {
            if (!el || !type || !fn) return;
            if (typeof el === 'string') el = document.getElementById(el);
            if (el) el.removeEventListener(type, fn);
        },
        stopPropagation: function(e) {
            if (e && e.stopPropagation) e.stopPropagation();
        },
        preventDefault: function(e) {
            if (e && e.preventDefault) e.preventDefault();
        },
        disableScrollPropagation: function() {},
        disableClickPropagation: function() {}
    };

    // =====================================================
    // Exports
    // =====================================================
    global.AoTGeoLayer = AoTGeoLayer;
    global.AoTGeoLayerGroup = AoTGeoLayerGroup;
    global.AoTGeoCircle = AoTGeoCircle;
    global.AoTGeoCircleMarker = AoTGeoCircleMarker;
    global.AoTGeoMarker = AoTGeoMarker;
    global.AoTGeoPolyline = AoTGeoPolyline;
    global.AoTGeoPolygon = AoTGeoPolygon;
    global.AoTDomUtil = DomUtil;
    global.AoTDomEvent = DomEvent;


})(window);
