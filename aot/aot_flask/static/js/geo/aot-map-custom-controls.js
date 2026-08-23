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
                        panel.classList.toggle('has-summary', has);
                        summaryRow.style.display = has ? '' : 'none';
                        if (!has) {
                            summaryRow.innerHTML = '';
                            if (!hasMeasurements) panel.style.display = 'none';
                            return;
                        }
                        let html = '';
                        if (title) {
                            html += '<span class="aot-meas-summary-title">' + _escSum(title) + '</span>';
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
                                    '<span class="aot-meas-summary-label" title="' + _escSum(it.label) + '">' + _escSum(it.label) + '</span> ' +
                                    '<span class="' + valClass + '">' + valHtml + '</span>' +
                                    '</span>';
                        });
                        summaryRow.innerHTML = html;
                        // data-aot-hidden: set by the toolbar hide toggle — the
                        // user's explicit hide wins over summary auto-show.
                        if (panel.dataset.aotHidden !== '1') panel.style.display = '';
                    },
                    updateValue: function(id, value, unit) {
                        const entry = items[id];
                        if (!entry) return;
                        const { valSpan, isBearing } = entry;
                        if (value !== undefined && value !== null && value !== '') {
                            if (isBearing) {
                                const deg = parseFloat(value);
                                if (!isNaN(deg)) {
                                    valSpan.style.transform = 'rotate(' + deg + 'deg)';
                                }
                            } else {
                                valSpan.innerText = typeof value === 'number' ? parseFloat(value.toFixed(2)) : value;
                            }
                        } else {
                            if (!isBearing) valSpan.innerText = '-';
                        }
                    },
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
