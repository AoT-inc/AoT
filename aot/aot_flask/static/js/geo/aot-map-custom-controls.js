/**
 * aot-map-custom-controls.js
 * Custom controls for AoT Map Widget (MapLibre Compatible)
 * Includes: SiteListControl, MeasureControl, MemoControl, MeasurementPanel
 * @version 2.0.0 - MapLibre migration
 */

(function () {
    if (window.AoTMapCustomControlsLoaded) return;

    // Wait for either L (Leaflet shim) or maplibregl
    var waitCount = 0;
    var maxWait = 100;

    function checkAndInit() {
        // Prefer MapLibre when available — L may be a compat shim, not real Leaflet
        if (typeof maplibregl !== 'undefined') {
            initMapLibreControls();
            return;
        }
        if (typeof L !== 'undefined' && L.Control && L.Control.extend) {
            initLeafletControls();
            return;
        }
        waitCount++;
        if (waitCount < maxWait) {
            setTimeout(checkAndInit, 50);
        }
    }

    checkAndInit();

    /**
     * MapLibre Native Custom Controls
     */
    function initMapLibreControls() {
        window.AoTMapCustomControlsLoaded = true;

        /**
         * SiteListControl for MapLibre - HTML Overlay based
         * Displays a list of sites and allows flying to them.
         */
        window.AoTMapCustomControls = {
            /**
             * Create Site List Control
             * @param {maplibregl.Map} map
             * @param {Object} options
             */
            createSiteListControl: function(map, options) {
                options = options || {};
                const mapContainer = map.getContainer();

                // Create main container
                const container = document.createElement('div');
                container.className = 'aot-map-site-list-control-container d-flex flex-column mt-2 aot-ml-10';
                container.style.cssText = 'position: absolute; top: 10px; left: 50px; z-index: 20;';

                // Create button
                const btn = document.createElement('a');
                btn.href = '#';
                btn.className = 'btn btn-white btn-circle shadow-sm d-flex align-items-center justify-content-center';
                if (window.AoTSetTitle) window.AoTSetTitle(btn, window._ ? window._('Site List') : 'Site List'); else btn.title = window._ ? window._('Site List') : 'Site List';
                btn.setAttribute('role', 'button');

                const icon = document.createElement('i');
                icon.className = 'fas fa-list aot-map-btn-icon';
                btn.appendChild(icon);

                // Create overlay list
                const listOverlay = document.createElement('div');
                listOverlay.className = 'aot-map-site-list-overlay';
                listOverlay.style.cssText = 'display: none; position: absolute; top: 100%; left: 0; background: var(--panel-bg-rgba, rgba(255,255,255,0.9)); border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.2); padding: 10px; min-width: 200px; overflow-y: auto; z-index: 40;';

                container.appendChild(btn);
                container.appendChild(listOverlay);

                // Adjust list height to fit widget (map container) height
                const adjustOverlayHeight = function() {
                    const btnRect = btn.getBoundingClientRect();
                    const containerRect = mapContainer.getBoundingClientRect();
                    const available = containerRect.bottom - btnRect.bottom - 10;
                    listOverlay.style.maxHeight = Math.max(80, available) + 'px';
                };

                // Click handler
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    const isOpening = listOverlay.style.display === 'none';
                    listOverlay.style.display = isOpening ? 'block' : 'none';
                    if (isOpening) adjustOverlayHeight();
                });

                if (map && typeof map.on === 'function') {
                    map.on('resize', function() {
                        if (listOverlay.style.display === 'block') adjustOverlayHeight();
                    });
                }
                if (typeof ResizeObserver !== 'undefined') {
                    const ro = new ResizeObserver(function() {
                        if (listOverlay.style.display === 'block') adjustOverlayHeight();
                    });
                    ro.observe(mapContainer);
                }

                // Update list
                const updateList = function() {
                    if (!options.sites || options.sites.length === 0) {
                        listOverlay.innerHTML = '<div style="color:var(--aot-color-text-secondary,#999); font-size:12px;">' + (window._ ? window._('No registered sites.') : 'No sites') + '</div>';
                        return;
                    }

                    listOverlay.innerHTML = '<div style="font-weight:bold; padding-bottom:5px; border-bottom:1px solid #eee; margin-bottom:5px;">' + (window._ ? window._('Site List') : 'Sites') + '</div>';

                    options.sites.forEach(function(site) {
                        const item = document.createElement('div');
                        item.className = 'site-item';
                        item.innerText = site.name;
                        item.style.cssText = 'padding: 5px; cursor: pointer;';
                        item.addEventListener('click', function() {
                            if (site.lat && site.lng) {
                                map.flyTo({ lng: site.lng, lat: site.lat }, site.zoom || 17);
                                listOverlay.style.display = 'none';
                            }
                        });
                        listOverlay.appendChild(item);
                    });
                };

                // Initial update
                if (options.sites) updateList();

                // Close on outside click
                document.addEventListener('click', function(e) {
                    if (!container.contains(e.target)) {
                        listOverlay.style.display = 'none';
                    }
                });

                mapContainer.style.position = 'relative';
                mapContainer.appendChild(container);

                return {
                    container: container,
                    updateSites: function(sites) {
                        options.sites = sites;
                        updateList();
                    }
                };
            },

            /**
             * Create Measurement Tool Control (MapLibre).
             * Click button → cursor crosshair + cancel popup on the LEFT.
             * Click on map → drop a waypoint. Each segment is drawn as an
             * SVG polyline with a running total distance tooltip near the
             * last point. Cancel ends measurement and clears all visuals.
             * Reprojection on map move/zoom keeps everything aligned.
             */
            createMeasureControl: function(map, options) {
                const mapContainer = map.getContainer();
                mapContainer.style.position = mapContainer.style.position || 'relative';
                const SVG_NS = 'http://www.w3.org/2000/svg';
                let isActive = false;
                let points = [];          // {lng, lat}
                let markerEls = [];       // dot DOM elements
                let cursorPoint = null;   // {lng, lat} live cursor while active

                // ------ Toolbar button (top-right) ------
                const container = document.createElement('div');
                container.className = 'aot-custom-toolbar mt-2 aot-mr-10';
                container.style.cssText = 'position:absolute; top:10px; right:10px; display:flex; flex-direction:column; gap:5px; z-index:20;';

                const btn = document.createElement('a');
                btn.href = '#';
                btn.className = 'btn btn-white btn-circle';
                if (window.AoTSetTitle) window.AoTSetTitle(btn, window._ ? window._('Distance measurement') : 'Measure'); else btn.title = window._ ? window._('Distance measurement') : 'Measure';
                btn.setAttribute('role', 'button');
                const icon = document.createElement('i');
                icon.className = 'fas fa-ruler-combined aot-map-btn-icon';
                btn.appendChild(icon);
                container.appendChild(btn);

                // ------ SVG overlay (for the polyline) ------
                const svg = document.createElementNS(SVG_NS, 'svg');
                svg.style.cssText = 'position:absolute; left:0; top:0; width:100%; height:100%; pointer-events:none; z-index:50; display:none;';
                const poly = document.createElementNS(SVG_NS, 'polyline');
                poly.setAttribute('stroke', '#e74c3c');
                poly.setAttribute('stroke-width', '2.5');
                poly.setAttribute('stroke-dasharray', '6 4');
                poly.setAttribute('fill', 'none');
                svg.appendChild(poly);
                mapContainer.appendChild(svg);

                // ------ Distance tooltip ------
                const distTip = document.createElement('div');
                distTip.style.cssText = 'display:none; position:absolute; background:white; padding:4px 10px; border-radius:4px; box-shadow:0 2px 4px rgba(0,0,0,0.25); font-size:12px; z-index:55; white-space:nowrap; pointer-events:none; font-weight:600; color:var(--aot-color-text-primary,#333);';
                mapContainer.appendChild(distTip);

                // ------ Cancel popup (LEFT side) ------
                const cancelBox = document.createElement('div');
                cancelBox.style.cssText = 'display:none; position:absolute; top:10px; left:10px; background:var(--panel-bg-rgba, rgba(255,255,255,0.9)); padding:8px 12px; border-radius:6px; box-shadow:0 2px 6px rgba(0,0,0,0.2); font-size:12px; z-index:55; display:none; align-items:center; gap:8px;';
                const cancelMsg = document.createElement('span');
                cancelMsg.textContent = window._ ? window._('Click on the map to measure') : 'Click on the map to measure';
                cancelMsg.style.color = 'var(--aot-color-text-primary, #333)';
                const cancelBtn = document.createElement('button');
                cancelBtn.type = 'button';
                cancelBtn.className = 'btn btn-sm btn-outline-secondary';
                cancelBtn.textContent = window._ ? window._('Cancel') : 'Cancel';
                cancelBtn.style.cssText = 'padding:2px 10px; font-size:12px; border-radius:4px;';
                cancelBox.appendChild(cancelMsg);
                cancelBox.appendChild(cancelBtn);
                mapContainer.appendChild(cancelBox);

                // ------ Helpers ------
                function haversine(p1, p2) {
                    const R = 6371000;
                    const dLat = (p2.lat - p1.lat) * Math.PI / 180;
                    const dLng = (p2.lng - p1.lng) * Math.PI / 180;
                    const a = Math.sin(dLat / 2) ** 2
                            + Math.cos(p1.lat * Math.PI / 180) * Math.cos(p2.lat * Math.PI / 180)
                            * Math.sin(dLng / 2) ** 2;
                    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
                }
                function fmtDist(m) {
                    return m >= 1000 ? (m / 1000).toFixed(2) + ' km' : m.toFixed(1) + ' m';
                }

                // Re-project + redraw everything from the points array.
                function redraw() {
                    // Markers
                    markerEls.forEach(function(el, i) {
                        const p = points[i];
                        if (!p) return;
                        const xy = map.project([p.lng, p.lat]);
                        el.style.left = xy.x + 'px';
                        el.style.top  = xy.y + 'px';
                    });
                    // Polyline
                    if (points.length === 0) {
                        svg.style.display = 'none';
                        distTip.style.display = 'none';
                        return;
                    }
                    const coords = points.map(function(p) {
                        const xy = map.project([p.lng, p.lat]);
                        return xy.x + ',' + xy.y;
                    });
                    if (cursorPoint && isActive) {
                        const xy = map.project([cursorPoint.lng, cursorPoint.lat]);
                        coords.push(xy.x + ',' + xy.y);
                    }
                    if (coords.length >= 2) {
                        poly.setAttribute('points', coords.join(' '));
                        svg.style.display = 'block';
                    } else {
                        svg.style.display = 'none';
                    }
                    // Total distance
                    let total = 0;
                    for (let i = 0; i < points.length - 1; i++) total += haversine(points[i], points[i + 1]);
                    if (cursorPoint && isActive && points.length > 0) total += haversine(points[points.length - 1], cursorPoint);
                    if ((points.length >= 1 && cursorPoint && isActive) || points.length >= 2) {
                        const last = (cursorPoint && isActive) ? cursorPoint : points[points.length - 1];
                        const xy = map.project([last.lng, last.lat]);
                        distTip.style.left = (xy.x + 12) + 'px';
                        distTip.style.top  = (xy.y - 28) + 'px';
                        distTip.textContent = fmtDist(total);
                        distTip.style.display = 'block';
                    } else {
                        distTip.style.display = 'none';
                    }
                }

                function addPoint(lngLat) {
                    points.push({ lng: lngLat.lng, lat: lngLat.lat });
                    const dot = document.createElement('div');
                    dot.style.cssText = 'position:absolute; width:10px; height:10px; background:#fff; border:2px solid #e74c3c; border-radius:50%; transform:translate(-50%,-50%); z-index:52; pointer-events:none; box-shadow:0 1px 2px rgba(0,0,0,0.3);';
                    mapContainer.appendChild(dot);
                    markerEls.push(dot);
                    redraw();
                }

                function clearMeasure() {
                    points = [];
                    markerEls.forEach(function(el) { el.remove(); });
                    markerEls = [];
                    cursorPoint = null;
                    svg.style.display = 'none';
                    distTip.style.display = 'none';
                    poly.setAttribute('points', '');
                }

                function setActive(active) {
                    isActive = active;
                    if (active) {
                        btn.classList.add('active');
                        mapContainer.style.cursor = 'crosshair';
                        cancelBox.style.display = 'flex';
                    } else {
                        btn.classList.remove('active');
                        mapContainer.style.cursor = '';
                        cancelBox.style.display = 'none';
                        clearMeasure();
                    }
                }

                // ------ Event wiring ------
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    setActive(!isActive);
                });
                cancelBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    setActive(false);
                });

                const onMapClick = function(e) {
                    if (!isActive) return;
                    addPoint(e.lngLat);
                };
                const onMapMove = function(e) {
                    if (!isActive) return;
                    cursorPoint = { lng: e.lngLat.lng, lat: e.lngLat.lat };
                    redraw();
                };
                const onMapMoveEnd = function() { redraw(); };

                map.on('click', onMapClick);
                map.on('mousemove', onMapMove);
                map.on('move', onMapMoveEnd);
                map.on('zoom', onMapMoveEnd);

                mapContainer.appendChild(container);

                return {
                    container: container,
                    clear: clearMeasure,
                    destroy: function() {
                        map.off('click', onMapClick);
                        map.off('mousemove', onMapMove);
                        map.off('move', onMapMoveEnd);
                        map.off('zoom', onMapMoveEnd);
                        clearMeasure();
                        container.remove();
                        if (svg.parentNode) svg.parentNode.removeChild(svg);
                        if (distTip.parentNode) distTip.parentNode.removeChild(distTip);
                        if (cancelBox.parentNode) cancelBox.parentNode.removeChild(cancelBox);
                    }
                };
            },

            /**
             * Create Memo/Note Control
             */
            createMemoControl: function(map, options) {
                const mapContainer = map.getContainer();
                let isActive = false;

                const container = document.createElement('div');
                container.className = 'aot-custom-toolbar mt-2 aot-mr-10';
                container.style.cssText = 'position: absolute; top: 60px; right: 10px; z-index: 20;';

                const btn = document.createElement('a');
                btn.href = '#';
                btn.className = 'btn btn-white btn-circle';
                if (window.AoTSetTitle) window.AoTSetTitle(btn, window._ ? window._('Add note') : 'Add Note'); else btn.title = window._ ? window._('Add note') : 'Add Note';
                btn.setAttribute('role', 'button');

                const icon = document.createElement('i');
                icon.className = 'fas fa-sticky-note aot-map-btn-icon';
                btn.appendChild(icon);
                container.appendChild(btn);

                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    isActive = !isActive;

                    if (isActive) {
                        btn.classList.add('active');
                        mapContainer.style.cursor = 'copy';
                    } else {
                        btn.classList.remove('active');
                        mapContainer.style.cursor = '';
                    }
                });

                const onClick = function(e) {
                    if (!isActive) return;

                    const uniqueLocId = 'loc_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
                    if (window.dispatchEvent) {
                        window.dispatchEvent(new CustomEvent('open-notes', {
                            detail: {
                                targetId: uniqueLocId,
                                targetType: 'map_location',
                                gps_lat: e.lngLat.lat,
                                gps_lng: e.lngLat.lng,
                                name: window._ ? window._('New Note') : 'New Note'
                            }
                        }));
                    }

                    // Auto-exit
                    isActive = false;
                    btn.classList.remove('active');
                    mapContainer.style.cursor = '';
                    map.off('click', onClick);
                };

                map.on('click', onClick);

                mapContainer.style.position = 'relative';
                mapContainer.appendChild(container);

                return {
                    container: container,
                    destroy: function() {
                        map.off('click', onClick);
                        container.remove();
                    }
                };
            },

            /**
             * Create Layer Control
             * Toggle visibility of different layer types (equipment, structure, etc.)
             */
            createLayerControl: function(map, options) {
                options = options || {};
                const mapContainer = map.getContainer();

                // Create container
                const container = document.createElement('div');
                container.className = 'aot-custom-toolbar mt-2 aot-mr-10';
                container.style.cssText = 'position: absolute; top: 110px; right: 10px; z-index: 20;';

                // Create button
                const btn = document.createElement('a');
                btn.href = '#';
                btn.className = 'btn btn-white btn-circle';
                if (window.AoTSetTitle) window.AoTSetTitle(btn, window._ ? window._('Layers') : 'Layers'); else btn.title = window._ ? window._('Layers') : 'Layers';
                btn.setAttribute('role', 'button');

                const icon = document.createElement('i');
                icon.className = 'fas fa-layer-group aot-map-btn-icon';
                btn.appendChild(icon);
                container.appendChild(btn);

                // Create layer panel
                const panel = document.createElement('div');
                panel.className = 'aot-layer-control-panel';
                panel.style.cssText = 'display: none; position: absolute; top: 100%; right: 0; background: var(--panel-bg-rgba, rgba(255,255,255,0.9)); border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.2); padding: 10px; min-width: 180px; overflow-y: auto; z-index: 30;';

                // Layer type definitions
                const layerTypes = [
                    { id: 'equipment', label: (window._ ? window._('Equipment') : 'Equipment'), icon: 'fa-cog' },
                    { id: 'structure', label: (window._ ? window._('Structure') : 'Structure'), icon: 'fa-building' },
                    { id: 'boundary', label: (window._ ? window._('Boundary') : 'Boundary'), icon: 'fa-border-style' },
                    { id: 'label', label: (window._ ? window._('Label') : 'Label'), icon: 'fa-tag' },
                    { id: 'device', label: (window._ ? window._('Device') : 'Device'), icon: 'fa-microchip' },
                    // 식생 구획(작기). 레이어 id 가 'aot-plot-*' 라
                    // getLayerIdsByType('plot') 이 그대로 찾아 끈다.
                    { id: 'plot', label: (window._ ? window._('Plot') : 'Plot'), icon: 'fa-vector-square' }
                ];

                // Create layer items
                layerTypes.forEach(function(lyr) {
                    const item = document.createElement('div');
                    item.className = 'aot-layer-item';
                    item.style.cssText = 'display: flex; align-items: center; padding: 6px 8px; cursor: pointer; border-radius: 3px;';
                    item.dataset.layerId = lyr.id;

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.checked = true;
                    checkbox.style.cssText = 'margin-right: 8px;';
                    checkbox.dataset.layerId = lyr.id;

                    const iconEl = document.createElement('i');
                    iconEl.className = 'fas ' + lyr.icon;
                    iconEl.style.cssText = 'margin-right: 8px; width: 16px;';

                    const label = document.createElement('span');
                    label.innerText = lyr.label;
                    label.style.cssText = 'font-size: 13px;';

                    item.appendChild(checkbox);
                    item.appendChild(iconEl);
                    item.appendChild(label);

                    // Click handler
                    item.addEventListener('click', function(e) {
                        if (e.target === checkbox) return;
                        checkbox.checked = !checkbox.checked;
                        toggleLayer(lyr.id, checkbox.checked);
                    });

                    checkbox.addEventListener('change', function() {
                        toggleLayer(lyr.id, checkbox.checked);
                    });

                    panel.appendChild(item);
                });

                // Toggle visibility function
                function toggleLayer(layerId, visible) {
                    // Dispatch event for AoTGeoDesign to handle
                    if (window.dispatchEvent) {
                        window.dispatchEvent(new CustomEvent('layer-toggle', {
                            detail: { layerId: layerId, visible: visible }
                        }));
                    }

                    // Direct MapLibre layer handling
                    try {
                        const layerIds = getLayerIdsByType(layerId);
                        layerIds.forEach(function(lid) {
                            if (map.getLayer(lid)) {
                                map.setLayoutProperty(lid, 'visibility', visible ? 'visible' : 'none');
                            }
                        });
                    } catch (e) {
                        // Layer not found, try via AoTGeoDesign
                        if (window.AoTGeoDesign && window.AoTGeoDesign.toggleLayerVisibility) {
                            window.AoTGeoDesign.toggleLayerVisibility(layerId, visible);
                        }
                    }
                }

                function getLayerIdsByType(type) {
                    var prefix = 'aot-' + type;
                    var ids = [];
                    if (map.style && map.style._layers) {
                        Object.keys(map.style._layers).forEach(function(key) {
                            if (key.startsWith(prefix) || key.indexOf(type) !== -1) {
                                ids.push(key);
                            }
                        });
                    }
                    return ids;
                }

                container.appendChild(panel);

                // Adjust panel height to fit widget (map container) height
                function adjustPanelHeight() {
                    var btnRect = btn.getBoundingClientRect();
                    var containerRect = mapContainer.getBoundingClientRect();
                    var available = containerRect.bottom - btnRect.bottom - 10;
                    panel.style.maxHeight = Math.max(80, available) + 'px';
                }

                // Toggle panel on button click
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    var isOpen = panel.style.display === 'block';
                    panel.style.display = isOpen ? 'none' : 'block';
                    if (!isOpen) adjustPanelHeight();
                });

                if (map && typeof map.on === 'function') {
                    map.on('resize', function() {
                        if (panel.style.display === 'block') adjustPanelHeight();
                    });
                }
                if (typeof ResizeObserver !== 'undefined') {
                    var ro = new ResizeObserver(function() {
                        if (panel.style.display === 'block') adjustPanelHeight();
                    });
                    ro.observe(mapContainer);
                }

                // Close on outside click
                document.addEventListener('click', function(e) {
                    if (!container.contains(e.target)) {
                        panel.style.display = 'none';
                    }
                });

                mapContainer.style.position = 'relative';
                mapContainer.appendChild(container);

                return {
                    container: container,
                    panel: panel,
                    toggle: function(layerId, visible) {
                        toggleLayer(layerId, visible);
                    },
                    destroy: function() {
                        container.remove();
                    }
                };
            },

            /**
             * Create Layer Control
             * Toggle visibility of different layer types (equipment, structure, etc.)
             */
            createLayerControl: function(map, options) {
                options = options || {};
                const mapContainer = map.getContainer();

                // Create container
                const container = document.createElement('div');
                container.className = 'aot-custom-toolbar mt-2 aot-mr-10';
                container.style.cssText = 'position: absolute; top: 110px; right: 10px; z-index: 20;';

                // Create button
                const btn = document.createElement('a');
                btn.href = '#';
                btn.className = 'btn btn-white btn-circle';
                if (window.AoTSetTitle) window.AoTSetTitle(btn, window._ ? window._('Layers') : 'Layers'); else btn.title = window._ ? window._('Layers') : 'Layers';
                btn.setAttribute('role', 'button');

                const icon = document.createElement('i');
                icon.className = 'fas fa-layer-group aot-map-btn-icon';
                btn.appendChild(icon);
                container.appendChild(btn);

                // Create layer panel
                const panel = document.createElement('div');
                panel.className = 'aot-layer-control-panel';
                panel.style.cssText = 'display: none; position: absolute; top: 100%; right: 0; background: var(--panel-bg-rgba, rgba(255,255,255,0.9)); border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.2); padding: 10px; min-width: 180px; overflow-y: auto; z-index: 30;';

                // Layer type definitions
                const layerTypes = [
                    { id: 'equipment', label: (window._ ? window._('Equipment') : 'Equipment'), icon: 'fa-cog' },
                    { id: 'structure', label: (window._ ? window._('Structure') : 'Structure'), icon: 'fa-building' },
                    { id: 'boundary', label: (window._ ? window._('Boundary') : 'Boundary'), icon: 'fa-border-style' },
                    { id: 'label', label: (window._ ? window._('Label') : 'Label'), icon: 'fa-tag' },
                    { id: 'device', label: (window._ ? window._('Device') : 'Device'), icon: 'fa-microchip' },
                    // 식생 구획(작기). 레이어 id 가 'aot-plot-*' 라
                    // getLayerIdsByType('plot') 이 그대로 찾아 끈다.
                    { id: 'plot', label: (window._ ? window._('Plot') : 'Plot'), icon: 'fa-vector-square' }
                ];

                // Create layer items
                layerTypes.forEach(function(lyr) {
                    const item = document.createElement('div');
                    item.className = 'aot-layer-item';
                    item.style.cssText = 'display: flex; align-items: center; padding: 6px 8px; cursor: pointer; border-radius: 3px;';
                    item.dataset.layerId = lyr.id;

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.checked = true;
                    checkbox.style.cssText = 'margin-right: 8px;';
                    checkbox.dataset.layerId = lyr.id;

                    const iconEl = document.createElement('i');
                    iconEl.className = 'fas ' + lyr.icon;
                    iconEl.style.cssText = 'margin-right: 8px; width: 16px;';

                    const label = document.createElement('span');
                    label.innerText = lyr.label;
                    label.style.cssText = 'font-size: 13px;';

                    item.appendChild(checkbox);
                    item.appendChild(iconEl);
                    item.appendChild(label);

                    // Click handler
                    item.addEventListener('click', function(e) {
                        if (e.target === checkbox) return;
                        checkbox.checked = !checkbox.checked;
                        toggleLayer(lyr.id, checkbox.checked);
                    });

                    checkbox.addEventListener('change', function() {
                        toggleLayer(lyr.id, checkbox.checked);
                    });

                    panel.appendChild(item);
                });

                // Toggle visibility function
                function toggleLayer(layerId, visible) {
                    // Dispatch event for AoTGeoDesign to handle
                    if (window.dispatchEvent) {
                        window.dispatchEvent(new CustomEvent('layer-toggle', {
                            detail: { layerId: layerId, visible: visible }
                        }));
                    }

                    // Direct MapLibre layer handling
                    try {
                        const layerIds = getLayerIdsByType(layerId);
                        layerIds.forEach(function(lid) {
                            if (map.getLayer(lid)) {
                                map.setLayoutProperty(lid, 'visibility', visible ? 'visible' : 'none');
                            }
                        });
                    } catch (e) {
                        // Layer not found, try via AoTGeoDesign
                        if (window.AoTGeoDesign && window.AoTGeoDesign.toggleLayerVisibility) {
                            window.AoTGeoDesign.toggleLayerVisibility(layerId, visible);
                        }
                    }
                }

                function getLayerIdsByType(type) {
                    var prefix = 'aot-' + type;
                    var ids = [];
                    if (map.style && map.style._layers) {
                        Object.keys(map.style._layers).forEach(function(key) {
                            if (key.startsWith(prefix) || key.indexOf(type) !== -1) {
                                ids.push(key);
                            }
                        });
                    }
                    return ids;
                }

                container.appendChild(panel);

                // Adjust panel height to fit widget (map container) height
                function adjustPanelHeight() {
                    var btnRect = btn.getBoundingClientRect();
                    var containerRect = mapContainer.getBoundingClientRect();
                    var available = containerRect.bottom - btnRect.bottom - 10;
                    panel.style.maxHeight = Math.max(80, available) + 'px';
                }

                // Toggle panel on button click
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    var isOpen = panel.style.display === 'block';
                    panel.style.display = isOpen ? 'none' : 'block';
                    if (!isOpen) adjustPanelHeight();
                });

                if (map && typeof map.on === 'function') {
                    map.on('resize', function() {
                        if (panel.style.display === 'block') adjustPanelHeight();
                    });
                }
                if (typeof ResizeObserver !== 'undefined') {
                    var ro = new ResizeObserver(function() {
                        if (panel.style.display === 'block') adjustPanelHeight();
                    });
                    ro.observe(mapContainer);
                }

                // Close on outside click
                document.addEventListener('click', function(e) {
                    if (!container.contains(e.target)) {
                        panel.style.display = 'none';
                    }
                });

                mapContainer.style.position = 'relative';
                mapContainer.appendChild(container);

                return {
                    container: container,
                    panel: panel,
                    toggle: function(layerId, visible) {
                        toggleLayer(layerId, visible);
                    },
                    destroy: function() {
                        container.remove();
                    }
                };
            },

            /**
             * Create Measurement Panel (Bottom Center)
             * Displays real-time measurement values
             */
            createMeasurementPanel: function(map, options) {
                options = options || {};
                const mapContainer = map.getContainer();
                const isDock = options.dock === true;

                const panel = document.createElement('div');
                panel.className = 'aot-measurement-panel' + (isDock ? ' aot-meas-dock' : '');
                // Dock mode: full-width bar flush to the widget bottom edge —
                // positioning comes from the .aot-meas-dock CSS class, so the
                // inline style skips the centered-float left/transform/max-width.
                // No inline gap either: the panel's children are the two ROWS
                // (summary/body) — an inline gap would override the 2px
                // .has-summary row gap that the fixed panel height is computed
                // from (item spacing lives on the rows in CSS).
                panel.style.cssText = isDock
                    ? 'position: absolute; display: flex; align-items: center; overflow-x: auto; z-index: 10;'
                    : 'position: absolute; left: 50%; transform: translateX(-50%); display: flex; gap: 15px; align-items: center; overflow-x: auto; z-index: 10; max-width: calc(100% - 40px);';

                const hasMeasurements = !!(options.measurements && options.measurements.length);
                if (!hasMeasurements) {
                    panel.style.display = 'none';
                }

                // Collapse handle (dock mode only) — shrinks the dock to a slim bar.
                // Applied before append so the initial state does not flash.
                let collapsed = false;
                let collapseBtn = null;
                function _applyCollapsed(c, fireCallback) {
                    collapsed = !!c;
                    panel.classList.toggle('aot-dock-collapsed', collapsed);
                    if (collapseBtn) {
                        const icon = collapseBtn.querySelector('i');
                        if (icon) icon.className = collapsed ? 'fas fa-chevron-up' : 'fas fa-chevron-down';
                        const lbl = collapsed
                            ? (window._ ? window._('Expand panel') : 'Expand panel')
                            : (window._ ? window._('Collapse panel') : 'Collapse panel');
                        collapseBtn.setAttribute('aria-label', lbl);
                        if (window.AoTSetTitle) window.AoTSetTitle(collapseBtn, lbl); else collapseBtn.title = lbl;
                    }
                    if (fireCallback && typeof options.onCollapsedChange === 'function') {
                        try { options.onCollapsedChange(collapsed); } catch (e) {}
                    }
                }
                if (isDock) {
                    collapseBtn = document.createElement('button');
                    collapseBtn.type = 'button';
                    collapseBtn.className = 'aot-dock-collapse-btn';
                    collapseBtn.innerHTML = '<i class="fas fa-chevron-down"></i>';
                    collapseBtn.addEventListener('click', function(e) {
                        e.stopPropagation();
                        _applyCollapsed(!collapsed, true);
                    });
                    panel.appendChild(collapseBtn);
                    _applyCollapsed(options.collapsed === true, false);
                }

                // Relative font balance (dock mode only): wheel-scrolling over
                // the left handle trades text size between the control summary
                // row (top) and the measurement row (bottom), proportionally to
                // the scroll amount. balance in [-1, 1] maps linearly to
                // complementary scales summing to 2 — control:measurement goes
                // from 0.5:1.5 (balance -1) through 1:1 (0) to 1.5:0.5 (+1) —
                // so one side grows exactly as much as the other shrinks and
                // the panel size stays constant (fixed heights in map.css).
                // Scroll up grows control text; scroll down grows measurement
                // text. Persistence is the caller's job via onBalanceChange.
                const BAL_RANGE = 1;
                let balance = parseFloat(options.balance);
                if (!isFinite(balance)) balance = 0;
                function _applyBalance(b, fireCallback) {
                    balance = Math.min(BAL_RANGE, Math.max(-BAL_RANGE, b));
                    panel.style.setProperty('--aot-meas-sum-scale', String(1 + 0.5 * balance));
                    panel.style.setProperty('--aot-meas-body-scale', String(1 - 0.5 * balance));
                    if (fireCallback && typeof options.onBalanceChange === 'function') {
                        try { options.onBalanceChange(balance); } catch (e) {}
                    }
                }
                if (isDock) {
                    const scaleHandle = document.createElement('div');
                    scaleHandle.className = 'aot-meas-scale-handle';
                    const hLbl = window._ ? window._('Scroll to resize text') : 'Scroll to resize text';
                    if (window.AoTSetTitle) window.AoTSetTitle(scaleHandle, hLbl); else scaleHandle.title = hLbl;
                    scaleHandle.setAttribute('aria-label', hLbl);
                    // Scroll deltas only accumulate while scrolling; the new
                    // balance is applied once, 0.5s after the last scroll
                    // event, so the panel does not resize/jitter mid-scroll.
                    let pendingBalance = balance;
                    let applyTimer = null;
                    function _queueBalance(delta) {
                        pendingBalance = Math.min(BAL_RANGE, Math.max(-BAL_RANGE,
                            pendingBalance + delta));
                        if (applyTimer) clearTimeout(applyTimer);
                        applyTimer = setTimeout(function() {
                            _applyBalance(pendingBalance, true);
                        }, 500);
                    }
                    scaleHandle.addEventListener('wheel', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        // Step proportional to wheel delta: smooth for
                        // trackpads, ~6% of the range per mouse-wheel notch.
                        _queueBalance(-e.deltaY * 0.0015);
                    }, { passive: false });
                    // Touch (mobile): vertical drag on the handle. Drag up
                    // grows control text, drag down grows measurement text —
                    // same direction as wheel scrolling.
                    let _touchY = null;
                    scaleHandle.addEventListener('touchstart', function(e) {
                        if (e.touches.length === 1) _touchY = e.touches[0].clientY;
                    }, { passive: true });
                    scaleHandle.addEventListener('touchmove', function(e) {
                        if (_touchY === null || e.touches.length !== 1) return;
                        e.preventDefault();
                        e.stopPropagation();
                        const y = e.touches[0].clientY;
                        // Full range sweep over ~330px of drag
                        _queueBalance(-(y - _touchY) * 0.006);
                        _touchY = y;
                    }, { passive: false });
                    scaleHandle.addEventListener('touchend', function() { _touchY = null; });
                    scaleHandle.addEventListener('touchcancel', function() { _touchY = null; });
                    panel.appendChild(scaleHandle);
                    _applyBalance(balance, false);
                    pendingBalance = balance;
                }

                // Summary row (top): facility control summary for the facility
                // nearest to the map center. Hidden until setSummary() is called.
                const summaryRow = document.createElement('div');
                summaryRow.className = 'aot-meas-summary-row';
                summaryRow.style.display = 'none';
                panel.appendChild(summaryRow);

                // Tap/click on a clipped control name shows a floating bubble
                // with the full name (title attr is hover-only, useless on
                // touch). Appended to body so the panel's overflow:hidden
                // cannot clip it; auto-hides shortly after.
                function _showSummaryTip(lbl) {
                    let tip = document.getElementById('aot-meas-sum-tip');
                    if (!tip) {
                        tip = document.createElement('div');
                        tip.id = 'aot-meas-sum-tip';
                        tip.className = 'aot-meas-sum-tip';
                        document.body.appendChild(tip);
                    }
                    tip.textContent = lbl.getAttribute('title') || lbl.textContent;
                    tip.style.display = 'block';
                    const r = lbl.getBoundingClientRect();
                    const tw = tip.offsetWidth, th = tip.offsetHeight;
                    const left = Math.max(4, Math.min(window.innerWidth - tw - 4, r.left + r.width / 2 - tw / 2));
                    tip.style.left = left + 'px';
                    tip.style.top = Math.max(4, r.top - th - 6) + 'px';
                    clearTimeout(tip._hideTimer);
                    tip._hideTimer = setTimeout(function() { tip.style.display = 'none'; }, 1800);
                }
                summaryRow.addEventListener('click', function(e) {
                    const lbl = e.target && e.target.closest && e.target.closest('.aot-meas-summary-label');
                    if (!lbl) return;
                    if (lbl.scrollWidth <= lbl.clientWidth + 1) return; // not clipped
                    _showSummaryTip(lbl);
                });

                // Body row (bottom): user-configured measurement items.
                const bodyRow = document.createElement('div');
                bodyRow.className = 'aot-meas-body-row';
                panel.appendChild(bodyRow);

                mapContainer.style.position = 'relative';
                mapContainer.appendChild(panel);

                const items = {};
                const itemElements = [];

                if (options.measurements) {
                    // [Sorting] Priority order: light (일조) first, then VPD,
                    // then everything else in the user's original order.
                    const lightSortPatterns = [
                        'solar', 'irradiance', 'radiation', 'sunlight',
                        'lux', 'light', '일조', '조도', '광량'
                    ];
                    const vpdSortPatterns = [
                        'vapor_pressure_deficit',
                        'vaper_pressure_decifit',
                        'vapor_pressure_deficite',
                        'vapor pressure deficit',
                        'vaper pressure deficit',
                        'vpd'
                    ];
                    function _sortRank(m) {
                        const n = (m.name || '').toLowerCase().trim();
                        if (lightSortPatterns.some(function(p) { return n.includes(p); })) return 0;
                        if (vpdSortPatterns.some(function(p) { return n.includes(p); })) return 1;
                        return 2;
                    }
                    const sortedMeasurements = [...options.measurements].sort(function(a, b) {
                        return _sortRank(a) - _sortRank(b);
                    });

                    // [Formatting] VPD name normalization pattern (includes similar names)
                    const vpdDisplayPatterns = [
                        'vapor_pressure_deficit',
                        'vaper_pressure_decifit',
                        'vapor_pressure_deficite',
                        'vapor pressure deficit',
                        'vaper pressure deficit'
                    ];

                    sortedMeasurements.forEach(function(m) {
                        // Resolve display unit: aotMapUnits has proper symbols (m/s, °C, etc.)
                        const resolvedUnit = (window.aotMapUnits && window.aotMapUnits[m.id]) || m.unit || '';
                        // Bearing detection: by unit, or by measurement/device
                        // name (sensors often report wind direction in plain
                        // degrees, and the user may name either the channel or
                        // the device "풍향").
                        const mNameLower = ((m.name || '') + ' ' + (m.device_name || '')).toLowerCase();
                        const isBearing = (resolvedUnit === 'bearing' || m.unit === 'bearing' ||
                            mNameLower.includes('풍향') ||
                            mNameLower.includes('방위') ||
                            mNameLower.includes('wind_dir') ||
                            mNameLower.includes('winddir') ||
                            mNameLower.includes('wind direction') ||
                            mNameLower.includes('wind_bearing') ||
                            mNameLower.includes('wind_deg'));

                        const item = document.createElement('div');
                        item.className = 'aot-measurement-item';
                        item.style.cssText = 'display: flex; flex-direction: column; align-items: center; min-width: 80px;';

                        const valueDiv = document.createElement('div');
                        valueDiv.className = 'aot-meas-value';
                        valueDiv.style.cssText = 'font-size: 1.5em; font-weight: bold; color: var(--aot-color-text-primary, #333);';

                        const valueSpan = document.createElement('span');

                        if (isBearing) {
                            // Wind direction arrow: rotated ↑ character
                            valueSpan.style.cssText = 'display:inline-block; transition:transform 0.4s ease;';
                            valueSpan.innerText = '↑';
                            const initVal = (m.value !== undefined && m.value !== null && m.value !== '-') ? parseFloat(m.value) : NaN;
                            if (!isNaN(initVal)) {
                                valueSpan.style.transform = 'rotate(' + initVal + 'deg)';
                            }
                        } else {
                            valueSpan.innerText = (m.value !== undefined && m.value !== null && m.value !== '') ? m.value : '-';
                        }

                        valueDiv.appendChild(valueSpan);

                        // Unit label (hidden for bearing)
                        if (resolvedUnit && !isBearing) {
                            const unitSpan = document.createElement('span');
                            unitSpan.className = 'aot-meas-unit';
                            unitSpan.style.cssText = 'font-size: 0.5em; font-weight: normal; color: var(--aot-color-text-secondary, #666); margin-left: 2px;';
                            unitSpan.innerText = resolvedUnit;
                            valueDiv.appendChild(unitSpan);
                        }

                        const nameRow = document.createElement('div');
                        nameRow.className = 'aot-meas-name-row';
                        nameRow.style.cssText = 'font-size: 0.75em; color: var(--aot-color-text-secondary, #666); margin-top: 2px;';

                        const nameSpan = document.createElement('span');
                        nameSpan.className = 'aot-meas-name';
                        let displayName = m.name || '';
                        if (vpdDisplayPatterns.some(function(p) { return displayName.toLowerCase().includes(p); })) {
                            displayName = 'VPD';
                        }
                        nameSpan.innerText = displayName;
                        nameRow.appendChild(nameSpan);

                        item.appendChild(valueDiv);
                        item.appendChild(nameRow);
                        bodyRow.appendChild(item);

                        items[m.id] = { valSpan: valueSpan, config: m, isBearing: isBearing };
                        itemElements.push(item);
                    });
                }

                function _escSum(s) {
                    return String(s == null ? '' : s)
                        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                }

                /* 사용자 지정 이름(시설명·장치명)을 **그릴 때 이미 번역해서** 넣는다.
                 *
                 * 이것이 없으면 순서가 "원문으로 그림 → 번역기가 되씀" 이 되어,
                 * 이 행이 다시 그려질 때마다 원문이 한 프레임 보였다가 번역본으로
                 * 바뀐다 — 그것이 번역을 켰을 때만 보이던 패널 깜빡임이다
                 * (실측: 원문 `イチゴ`·`バルブ1` 이 찍혔다가 `딸기`·`밸브1` 로).
                 *
                 * 값이 하나만 바뀌어도 행은 통째로 다시 그려지므로(키가 값까지
                 * 포함한다) 이름 열 개가 매번 함께 깜빡였다. 여기서 번역본을 넣으면
                 * 다시 그려도 이름은 처음부터 최종 모습이라 깜빡일 것이 없다.
                 *
                 * ⚠ `title` 속성에는 **원문**을 남긴다. 번역 사전에 없는 이름은
                 * 그대로 나오는데, 툴팁까지 번역본으로 덮으면 원문을 확인할 길이
                 * 사라진다 — 번역기 자신도 원문을 되돌릴 수 있게 기록해 둔다.
                 *
                 * 번역이 꺼져 있거나(`isOff`) 사전에 없으면 원문을 그대로 돌려주므로
                 * 이 호출은 그때 아무 일도 하지 않는다. */
                function _nameSum(s) {
                    var t = s;
                    try {
                        if (window.AoTUserI18n && window.AoTUserI18n.translate) {
                            t = window.AoTUserI18n.translate(s);
                        }
                    } catch (e) { t = s; }
                    return _escSum(t);
                }

                // Last rendered content, so a repeat call with identical data (a poll
                // tick or a moveend landing back on the same facility) is a no-op
                // instead of tearing down and rebuilding the row — that rebuild is
                // what makes the panel look like it "trembles" while panning.
                let _lastSummaryKey = null;

                return {
                    panel: panel,
                    setCollapsed: function(c) { if (isDock) _applyCollapsed(c, false); },
                    isCollapsed: function() { return collapsed; },
                    setBalance: function(b) { if (isDock) _applyBalance(parseFloat(b) || 0, false); },
                    getBalance: function() { return balance; },
                    // items: [{label, value}], title: facility name (optional).
                    // Empty items hides the summary row (and the panel when there
                    // are no measurement items either).
                    setSummary: function(items, title) {
                        const has = Array.isArray(items) && items.length > 0;
                        const key = has
                            ? String(title || '') + '|' + items.map(function(it) {
                                return it.label + ':' + (it.value != null ? it.value : (it.on ? '1' : '0'));
                            }).join(',')
                            : '';
                        if (key === _lastSummaryKey) return;
                        _lastSummaryKey = key;

                        panel.classList.toggle('has-summary', has);
                        summaryRow.style.display = has ? '' : 'none';
                        if (!has) {
                            summaryRow.innerHTML = '';
                            if (!hasMeasurements) panel.style.display = 'none';
                            return;
                        }
                        let html = '';
                        if (title) {
                            html += '<span class="aot-meas-summary-title">' + _nameSum(title) + '</span>';
                        }
                        items.forEach(function(it) {
                            // Binary controls ({on: bool}) render as a round
                            // indicator instead of ON/OFF text; the dot is
                            // em-sized inside the value span so it follows
                            // the control value scale.
                            // Binary items ({on: bool, no value}) → dot indicator
                            // Numeric items ({value: string, on?: bool}) → number text, red when on
                            var hasDot = (it.value == null && typeof it.on === 'boolean');
                            var valHtml = hasDot
                                ? '<span class="aot-meas-summary-dot ' + (it.on ? 'is-on' : 'is-off') + '"></span>'
                                : _escSum(it.value);
                            var valClass = 'aot-meas-summary-value' +
                                (!hasDot && it.on ? ' is-on' : '');
                            // Long control names are clipped with an ellipsis
                            // (CSS max-width); keep the full name in a tooltip.
                            html += '<span class="aot-meas-summary-item">' +
                                    '<span class="aot-meas-summary-label" title="' + _escSum(it.label) + '">' + _nameSum(it.label) + '</span> ' +
                                    '<span class="' + valClass + '">' + valHtml + '</span>' +
                                    '</span>';
                        });
                        summaryRow.innerHTML = html;
                        // data-aot-hidden: set by the toolbar hide toggle — the
                        // user's explicit hide wins over summary auto-show.
                        if (panel.dataset.aotHidden !== '1') panel.style.display = '';
                    },
                    // 값이 그대로면 DOM 을 건드리지 않는다.
                    //
                    // `innerText` 대입은 **같은 글자를 넣어도** 기존 텍스트 노드를
                    // 버리고 새로 만든다. 이 패널은 주기적으로(기본 refreshSeconds)
                    // 항목마다 한 번씩 불리므로, 값이 안 바뀐 사이클에도 항목 수만큼
                    // 교체가 일어난다 — 실측(Kumamoto, 40초): 값 칸에서 childList
                    // 변경 4건이 그것이었다.
                    //
                    // 눈에 띄는 깜빡임이 아니더라도 공짜가 아니다: 이름 번역
                    // (`aot-user-i18n.js`)이 MutationObserver 로 document.body 를
                    // 보고 있어서, 의미 없는 변경 하나하나가 그 관찰자를 깨우고
                    // 서브트리를 다시 훑게 만든다.
                    //
                    // 마지막으로 **쓴 값**을 기억해 견준다(DOM 을 읽지 않는다) —
                    // 숫자 칸은 번역 대상이 아니지만, 규칙을 한 가지로 두는 편이
                    // 나중에 번역되는 칸이 생겨도 안전하다.
                    updateValue: function(id, value, unit) {
                        const entry = items[id];
                        if (!entry) return;
                        const { valSpan, isBearing } = entry;
                        if (value !== undefined && value !== null && value !== '') {
                            if (isBearing) {
                                const deg = parseFloat(value);
                                if (!isNaN(deg)) {
                                    const t = 'rotate(' + deg + 'deg)';
                                    if (entry._lastTransform !== t) {
                                        entry._lastTransform = t;
                                        valSpan.style.transform = t;
                                    }
                                }
                            } else {
                                const txt = String(typeof value === 'number'
                                    ? parseFloat(value.toFixed(2)) : value);
                                if (entry._lastText !== txt) {
                                    entry._lastText = txt;
                                    valSpan.innerText = txt;
                                }
                            }
                        } else {
                            if (!isBearing && entry._lastText !== '-') {
                                entry._lastText = '-';
                                valSpan.innerText = '-';
                            }
                        }
                    },
                    destroy: function() {
                        panel.remove();
                    }
                };
            },


            /**
             * Create Time Dock (top center)
             *
             * 지도 중심 좌표의 현지 시각·일출·일몰을 상단 가장자리에 붙은 독으로
             * 보여준다. 하단 측정값 독(createMeasurementPanel)을 위아래로 뒤집은
             * 형태이고 셀 구조(.aot-measurement-item / .aot-meas-value /
             * .aot-meas-name-row)를 그대로 공유한다 — 한 지도 안에서 값을 읽는
             * 방식이 두 가지가 되면 안 된다.
             *
             * **이 팩토리는 서버를 부르지 않는다.** 시각 자료(tz·일출·일몰)는
             * 호출부가 /api/geo/local_time 에서 받아 update() 로 넣어 주고,
             * 여기서는 그것을 초당 다시 그리기만 한다. 시계가 서버 폴링이 되면
             * 지도 위젯 하나가 초당 요청 하나를 만든다.
             *
             * options: { scale, onScaleChange(scale), locale }
             * 반환:    { panel, update(payload), tick()->stale, getScale, setScale, destroy }
             */
            createTimeDock: function(map, options) {
                options = options || {};
                const mapContainer = map.getContainer();
                const _t = function(s) { return window._ ? window._(s) : s; };

                const panel = document.createElement('div');
                panel.className = 'aot-measurement-panel aot-time-dock';
                // 자료가 오기 전에는 빈 알약을 띄우지 않는다. update() 가 켠다.
                panel.style.display = 'none';

                // ── 크기 손잡이(좌하단 원형 버튼) ──────────────────────────────
                // 측정값 독의 글자 균형 손잡이(.aot-meas-scale-handle)와 같은
                // 조작을 시계에 준다: 손잡이 위에서 휠(모바일은 세로 드래그).
                // 다만 여기서 움직이는 것은 두 행의 '균형' 이 아니라 독 전체의
                // 크기다 — 시계는 행이 하나뿐이라 나눠 줄 상대가 없고, 사람이
                // 원하는 것도 "멀리서도 보이게 크게" 이기 때문이다.
                // 배율은 덧셈이 아니라 곱으로 움직인다(exp): 작을 때는 잘게,
                // 클 때는 성큼 — 어느 크기에서도 휠 한 칸의 체감이 같다.
                const SCALE_MIN = 0.7;
                const SCALE_MAX = 2.4;
                let scale = parseFloat(options.scale);
                if (!isFinite(scale)) scale = 1;

                function _applyScale(s, fireCallback) {
                    scale = Math.min(SCALE_MAX, Math.max(SCALE_MIN, s));
                    panel.style.setProperty('--aot-time-scale', String(scale));
                    if (fireCallback && typeof options.onScaleChange === 'function') {
                        try { options.onScaleChange(scale); } catch (e) {}
                    }
                }

                const scaleHandle = document.createElement('button');
                scaleHandle.type = 'button';
                scaleHandle.className = 'aot-time-scale-handle';
                const hLbl = _t('Scroll to resize the clock');
                if (window.AoTSetTitle) window.AoTSetTitle(scaleHandle, hLbl); else scaleHandle.title = hLbl;
                scaleHandle.setAttribute('aria-label', hLbl);
                // 버튼이지만 눌러서 하는 일은 없다 — 폼 제출/지도 클릭으로 새지 않게 막는다.
                scaleHandle.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                });
                scaleHandle.addEventListener('wheel', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    _applyScale(scale * Math.exp(-e.deltaY * 0.0012), true);
                }, { passive: false });
                // 터치: 손잡이 위 세로 드래그. 위로 끌면 커진다(휠 방향과 같다).
                let _touchY = null;
                scaleHandle.addEventListener('touchstart', function(e) {
                    if (e.touches.length === 1) _touchY = e.touches[0].clientY;
                }, { passive: true });
                scaleHandle.addEventListener('touchmove', function(e) {
                    if (_touchY === null || e.touches.length !== 1) return;
                    e.preventDefault();
                    e.stopPropagation();
                    const y = e.touches[0].clientY;
                    _applyScale(scale * Math.exp(-(y - _touchY) * 0.005), true);
                    _touchY = y;
                }, { passive: false });
                scaleHandle.addEventListener('touchend', function() { _touchY = null; });
                scaleHandle.addEventListener('touchcancel', function() { _touchY = null; });
                panel.appendChild(scaleHandle);
                _applyScale(scale, false);

                // ── 칸 ────────────────────────────────────────────────────────
                const row = document.createElement('div');
                row.className = 'aot-meas-body-row';
                panel.appendChild(row);

                // 일출·일몰 아이콘. FontAwesome 무료판에는 일출/일몰 전용 글리프가
                // 없어(fa-sunrise/fa-sunset 은 유료) 여기서 직접 그린다. currentColor
                // 로 칠하고 크기를 em 으로 두었으므로 문자 보조색과 시계 크기를
                // 그대로 따라간다.
                //
                // 지평선 하나와 화살표 하나뿐이다. 해 모양(반원)까지 그려 넣어 봤지만
                // 13px 에서는 획이 뭉쳐 오히려 읽기 어려웠다 — 옆에 시각이 붙어 있는
                // 자리에서 필요한 것은 '해가 뜨는가 지는가' 한 가지뿐이다.
                const _SUN_PATHS = {
                    sunrise: ['M3 20h18', 'M12 4v11', 'M7.5 8.5L12 4l4.5 4.5'],
                    sunset: ['M3 20h18', 'M12 4v11', 'M7.5 10.5L12 15l4.5-4.5']
                };
                const SVG_NS = 'http://www.w3.org/2000/svg';

                function _sunIcon(kind) {
                    const key = (kind === 'sunset') ? 'sunset' : 'sunrise';
                    const label = (key === 'sunset') ? _t('Sunset') : _t('Sunrise');
                    const svg = document.createElementNS(SVG_NS, 'svg');
                    svg.setAttribute('class', 'aot-time-icon');
                    svg.setAttribute('viewBox', '0 0 24 24');
                    svg.setAttribute('fill', 'none');
                    svg.setAttribute('stroke', 'currentColor');
                    svg.setAttribute('stroke-width', '2');
                    svg.setAttribute('stroke-linecap', 'round');
                    svg.setAttribute('stroke-linejoin', 'round');
                    // 글자를 아이콘으로 바꾼 자리다 — 읽어 주는 쪽과 마우스를 올린
                    // 쪽에는 원래의 말이 그대로 남아 있어야 한다.
                    svg.setAttribute('role', 'img');
                    svg.setAttribute('aria-label', label);
                    const title = document.createElementNS(SVG_NS, 'title');
                    title.textContent = label;
                    svg.appendChild(title);
                    _SUN_PATHS[key].forEach(function(d) {
                        const path = document.createElementNS(SVG_NS, 'path');
                        path.setAttribute('d', d);
                        svg.appendChild(path);
                    });
                    return svg;
                }

                function _cell(extraClass) {
                    const item = document.createElement('div');
                    item.className = 'aot-measurement-item aot-time-item' +
                        (extraClass ? ' ' + extraClass : '');
                    const valueDiv = document.createElement('div');
                    valueDiv.className = 'aot-meas-value';
                    const valueSpan = document.createElement('span');
                    valueDiv.appendChild(valueSpan);
                    const nameRow = document.createElement('div');
                    nameRow.className = 'aot-meas-name-row';
                    const nameSpan = document.createElement('span');
                    nameSpan.className = 'aot-meas-name';
                    nameRow.appendChild(nameSpan);
                    // 이름이 위, 값이 아래다 — 측정값 독(값이 위)과 반대로 놓는다.
                    // 이 독은 위 가장자리에 고정돼 아래로 자라므로, 움직이지 않는
                    // 기준선은 위쪽이다. 거기에는 크기가 변하지 않는 이름줄을 두고,
                    // 크기 손잡이로 커지고 작아지는 시각은 아래로 늘어나게 한다.
                    item.appendChild(nameRow);
                    item.appendChild(valueDiv);
                    row.appendChild(item);

                    let iconKind = null;
                    return {
                        item: item,
                        value: valueSpan,
                        name: nameSpan,
                        /** 이름줄을 일출/일몰 아이콘으로 채운다(글자는 비운다). */
                        setIcon: function(kind) {
                            const key = (kind === 'sunset') ? 'sunset' : 'sunrise';
                            if (iconKind === key) return;   // 초당 다시 그리므로 같은 것은 두 번 만들지 않는다
                            iconKind = key;
                            nameSpan.innerText = '';
                            const old = nameRow.querySelector('.aot-time-icon');
                            if (old) nameRow.removeChild(old);
                            nameRow.appendChild(_sunIcon(key));
                        },
                        /** 이름줄을 글자로 채운다(아이콘은 걷어낸다). */
                        setText: function(text) {
                            if (iconKind !== null) {
                                iconKind = null;
                                const old = nameRow.querySelector('.aot-time-icon');
                                if (old) nameRow.removeChild(old);
                            }
                            if (nameSpan.innerText !== text) nameSpan.innerText = text;
                        }
                    };
                }

                // 세 칸이고, 왼쪽에서 오른쪽으로 시간이 흐른다: 직전 사건 → 지금 →
                // 다음 사건. 즉 낮에는 `일출 · 지금 · 일몰`, 밤에는 `일몰 · 지금 ·
                // 일출` 이 된다. 오늘의 일출·일몰을 고정 순서로 늘어놓지 않는 이유가
                // 여기 있다 — 밤 10시에 "오늘 일출 06:41" 은 이미 지난 이야기고,
                // 그 자리에 있어야 하는 것은 내일 일출이다.
                //
                // 양옆 칸은 글자 크기도, 값의 글자 수(HH:MM)도, 이름의 글자 수도
                // 같다. 그래서 폭이 서로 같고, 결과적으로 **현재 시각이 독의 정중앙**
                // 에 선다 — 칸을 하나 더 붙이면 그 대칭이 깨진다.
                const cPrev = _cell();
                const cClock = _cell('aot-time-clock');
                const cNext = _cell();
                const cPolar = _cell();

                // ── 상태 ──────────────────────────────────────────────────────
                let data = null;
                // 서버 시각 − 브라우저 시각. 브라우저 시계가 틀어져 있어도 독은
                // 서버(=농장 기록)와 같은 시각을 말해야 한다.
                let skewMs = 0;
                // Intl 포맷터는 만드는 비용이 있고 초당 다시 그리므로 tz 별로 캐시한다.
                let fmtCache = { tz: null, time: null, date: null };
                let browserDateFmt = null;

                function _fmts(tz) {
                    if (fmtCache.tz !== tz) {
                        let time = null, date = null;
                        try {
                            time = new Intl.DateTimeFormat(options.locale || undefined, {
                                timeZone: tz, hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
                            });
                            // en-CA 는 YYYY-MM-DD 를 준다 — 서버의 local_date 와
                            // 그대로 비교하기 위한 것이지 사람에게 보일 값이 아니다.
                            date = new Intl.DateTimeFormat('en-CA', {
                                timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit'
                            });
                        } catch (e) {
                            // Intl 이 모르는 tz 이름(오래된 브라우저 등) — 아래에서
                            // 서버가 준 오프셋으로 직접 계산한다.
                            time = null;
                            date = null;
                        }
                        fmtCache = { tz: tz, time: time, date: date };
                    }
                    return fmtCache;
                }

                function _hhmm(ms) {
                    if (ms === null || ms === undefined || !data) return '—';
                    const f = _fmts(data.tz).time;
                    if (f) {
                        try { return f.format(new Date(ms)); } catch (e) {}
                    }
                    const d = new Date(ms + (data.utc_offset_minutes || 0) * 60000);
                    return ('0' + d.getUTCHours()).slice(-2) + ':' + ('0' + d.getUTCMinutes()).slice(-2);
                }

                function _localDate(ms) {
                    if (!data) return null;
                    const f = _fmts(data.tz).date;
                    if (f) {
                        try { return f.format(new Date(ms)); } catch (e) {}
                    }
                    return new Date(ms + (data.utc_offset_minutes || 0) * 60000)
                        .toISOString().slice(0, 10);
                }

                function _browserDate(ms) {
                    if (!browserDateFmt) {
                        try {
                            browserDateFmt = new Intl.DateTimeFormat('en-CA', {
                                year: 'numeric', month: '2-digit', day: '2-digit'
                            });
                        } catch (e) { return null; }
                    }
                    try { return browserDateFmt.format(new Date(ms)); } catch (e) { return null; }
                }

                /** events 에서 지금을 사이에 둔 {prev, next} 한 쌍. 서버가 시각순으로 보낸다. */
                function _around(now) {
                    const evs = (data && Array.isArray(data.events)) ? data.events : [];
                    let prev = null, next = null;
                    for (let i = 0; i < evs.length; i++) {
                        const e = evs[i];
                        if (!e || typeof e.at !== 'number') continue;
                        if (e.at <= now) prev = e;
                        else if (next === null) next = e;
                    }
                    return { prev: prev, next: next };
                }


                function _render() {
                    if (!data) {
                        panel.style.display = 'none';
                        return;
                    }
                    panel.style.display = '';
                    const now = Date.now() + skewMs;

                    // 1) 현재 시각 — 이름줄은 평소에 비워 둔다.
                    //
                    // 시간대 약칭('KST')을 적어 두지 않는 이유: 이 독에서 사람이
                    // 읽는 것은 시각 하나이고, 그 옆에 늘 붙어 있는 넉 자는 읽히지
                    // 않으면서 자리만 차지한다. 시간대는 마우스를 올리면 전체 이름
                    // (Asia/Seoul)으로 나온다.
                    cClock.value.innerText = _hhmm(now);

                    // 다만 **지도 중심의 현지 날짜가 이 브라우저의 날짜와 다를 때**는
                    // 날짜를 적는다. 날짜변경선을 넘겼다는 것은 시각만 봐서는 알 수
                    // 없고, 모르면 그냥 틀린 값으로 읽히기 때문이다.
                    const ld = _localDate(now);
                    const bd = _browserDate(now);
                    if (ld && bd && ld !== bd) {
                        const dp = ld.split('-');
                        cClock.setText(parseInt(dp[1], 10) + '/' + parseInt(dp[2], 10));
                    } else {
                        cClock.setText('');
                    }

                    const tzTip = data.tz_resolved
                        ? (data.tz + (data.tz_abbrev ? ' (' + data.tz_abbrev + ')' : ''))
                        : _t('Timezone for this location could not be resolved — showing the farm timezone.');
                    if (window.AoTSetTitle) window.AoTSetTitle(cClock.item, tzTip);
                    else cClock.item.title = tzTip;

                    // 직전(왼쪽) / 다음(오른쪽) / 다음까지 남은 시간(맨 오른쪽).
                    const polar = (data.status === 'always_day' || data.status === 'always_night');
                    const known = !polar && data.status !== 'unknown';
                    const around = known ? _around(now) : { prev: null, next: null };

                    cPolar.item.style.display = polar ? '' : 'none';
                    if (polar) {
                        cPolar.value.innerText = '—';
                        // 극야·백야에는 대응하는 아이콘이 없다 — 글자로 적는다.
                        cPolar.setText(data.status === 'always_day'
                            ? _t('Midnight sun') : _t('Polar night'));
                    }

                    if (around.prev) {
                        cPrev.value.innerText = _hhmm(around.prev.at);
                        cPrev.setIcon(around.prev.kind);
                        cPrev.item.style.display = '';
                    } else {
                        // 목록 안에 지나간 사건이 없다(첫 조회 직후의 드문 경계).
                        // 빈 칸을 세워 두지 않고 그냥 뺀다 — 그러면 시계가 왼쪽
                        // 끝에 서고, 그것 자체가 "아직 아무 일도 없었다" 는 뜻이다.
                        cPrev.item.style.display = 'none';
                    }

                    if (around.next) {
                        cNext.value.innerText = _hhmm(around.next.at);
                        cNext.setIcon(around.next.kind);
                        cNext.item.style.display = '';
                    } else {
                        cNext.item.style.display = 'none';
                    }
                }

                /** 서버 자료를 다시 받아야 하는가. */
                function _isStale() {
                    if (!data) return true;
                    const now = Date.now() + skewMs;
                    // 현지 자정을 넘겼다 — 오늘의 일출/일몰이 어제 것이 되었다.
                    const ld = _localDate(now);
                    if (ld && data.local_date && ld !== data.local_date) return true;
                    // 사건 목록이 바닥났다 — 어제~모레 한 벌을 다 써 버린 경우다.
                    // 사건 하나가 지나는 것만으로는 다시 받지 않는다: 다음 것이
                    // 이미 목록 안에 있기 때문이다(서버가 나흘치를 보낸다).
                    // 극야·백야에는 사건 자체가 없으므로 이 검사를 건너뛴다 —
                    // 안 그러면 목록이 빈 채로 영원히 '낡음' 이 된다.
                    if (data.status === 'normal' && !_around(now).next) return true;
                    return false;
                }

                mapContainer.style.position = mapContainer.style.position || 'relative';
                mapContainer.appendChild(panel);

                return {
                    panel: panel,
                    update: function(payload) {
                        data = payload || null;
                        if (data && typeof data.server_epoch_ms === 'number') {
                            const skew = data.server_epoch_ms - Date.now();
                            // 1초 미만은 보정하지 않는다 — 그 정도는 왕복 지연이지
                            // 시계 오차가 아니고, 매 갱신마다 흔들리면 초가 튄다.
                            skewMs = Math.abs(skew) < 1000 ? 0 : skew;
                        }
                        _render();
                    },
                    /** 1초마다 호출. 서버 자료를 다시 받아야 하면 true 를 돌려준다. */
                    tick: function() {
                        _render();
                        return _isStale();
                    },
                    getScale: function() { return scale; },
                    setScale: function(s) { _applyScale(s, false); },
                    destroy: function() {
                        panel.remove();
                    }
                };
            },

            /**
             * Add standard custom controls to map
             */
            addStandardCustomControls: function(map, options) {
                const controls = [];

                if (options.includeSiteList !== false) {
                    const siteList = this.createSiteListControl(map, { sites: options.sites || [] });
                    controls.push(siteList);
                }

                if (options.includeMeasure !== false) {
                    const measure = this.createMeasureControl(map);
                    controls.push(measure);
                }

                if (options.includeMemo !== false) {
                    const memo = this.createMemoControl(map);
                    controls.push(memo);
                }

                if (options.includeLayer !== false) {
                    const layer = this.createLayerControl(map);
                    controls.push(layer);
                }

                return controls;
            }
        };

        // Expose factories
        window.AoTMapCustomControls.createSiteList = function(map, opts) {
            return window.AoTMapCustomControls.createSiteListControl(map, opts);
        };
        window.AoTMapCustomControls.createMeasure = function(map, opts) {
            return window.AoTMapCustomControls.createMeasureControl(map, opts);
        };
        window.AoTMapCustomControls.createMemo = function(map, opts) {
            return window.AoTMapCustomControls.createMemoControl(map, opts);
        };
        window.AoTMapCustomControls.createLayer = function(map, opts) {
            return window.AoTMapCustomControls.createLayerControl(map, opts);
        };
        // NOTE: do NOT alias createMeasurementPanel — it is already defined on
        // the object literal above. Reassigning it here to a wrapper that calls
        // window.AoTMapCustomControls.createMeasurementPanel produced infinite
        // recursion and was the root cause of the measurement panel never
        // rendering in vector mode.
    }

    /**
     * Leaflet Compatibility (Backward compatible L.Control-based controls)
     */
    function initLeafletControls() {
        if (typeof L === 'undefined' || !L.Control) return;

        // Placeholder - Leaflet controls already exist in original file
        // This function exists for compatibility with L.Control.extend pattern
        window.AoTMapCustomControlsLoaded = true;

        // Initialize original L.Control-based controls if L is fully available
        // The original code remains as fallback
    }

})();
