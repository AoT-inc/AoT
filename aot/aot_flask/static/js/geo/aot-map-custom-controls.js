/**
 * aot-map-custom-controls.js
 * Custom Leaflet controls for AoT Map Widget.
 * Includes: SiteListControl, MeasureControl, MemoControl
 * Updated to match Geo Design styles (White Round Buttons, Shadow).
 */

(function () {
    if (window.AoTMapCustomControlsLoaded) return;

    // [Iteration 16] Leadlet Availability Check: Wait until L is available globally
    if (typeof L === 'undefined') {
        setTimeout(arguments.callee, 50);
        return;
    }

    window.AoTMapCustomControlsLoaded = true;

    /**
     * SiteListControl - Displays a list of sites and allows flying to them.
     * Style: White Button, Shadow
     */
    L.Control.SiteListControl = L.Control.extend({
        options: {
            position: 'topleft',
            sites: [] 
        },

        onAdd: function (map) {
            this._map = map;
            const container = L.DomUtil.create('div', 'aot-map-site-list-control-container d-flex flex-column mt-2 aot-ml-10');
            this._container = container;

            L.DomEvent.disableClickPropagation(container);
            L.DomEvent.disableScrollPropagation(container);

            const btn = L.DomUtil.create('a', 'btn btn-white btn-circle bg-white shadow-sm d-flex align-items-center justify-content-center', container);
            btn.href = '#';
            btn.title = _('Site List');
            btn.role = 'button';
            this._btn = btn;

            L.DomUtil.create('i', 'fas fa-list aot-map-btn-icon', btn);

            const listOverlay = L.DomUtil.create('div', 'aot-map-site-list-overlay', container);
            this._listOverlay = listOverlay;

            this._onDocumentClick = (e) => {
                if (!this._container || !this._listOverlay) return;
                if (!this._container.contains(e.target) && this._listOverlay.classList.contains('active')) {
                    this._listOverlay.classList.remove('active');
                }
            };
            document.addEventListener('click', this._onDocumentClick);

            L.DomEvent.on(btn, 'click', (e) => {
                L.DomEvent.stop(e); 
                const isOpening = !this._listOverlay.classList.contains('active');
                
                if (isOpening) {
                    this._updateList();
                    this._listOverlay.classList.add('active');
                } else {
                    this._listOverlay.classList.remove('active');
                }
            });

            return container;
        },

        onRemove: function (map) {
            if (this._onDocumentClick) {
                document.removeEventListener('click', this._onDocumentClick);
            }
        },

        _updateList: function () {
            if (!this._listOverlay || !this._map || !this._container) return;
            
            // [Fix] Smart Vertical Positioning with !important overrides
            const container = this._map.getContainer();
            const mapRect = container.getBoundingClientRect();
            const btnRect = this._btn.getBoundingClientRect();
            
            const spaceBelow = mapRect.bottom - btnRect.bottom;
            const spaceAbove = btnRect.top - mapRect.top;
            
            // Priority: downward if spaceBelow > 200, otherwise check if spaceAbove is better
            if (spaceBelow < 200 && spaceAbove > spaceBelow) {
                // Open upwards: Position it above the button
                this._listOverlay.style.setProperty('top', 'auto', 'important');
                this._listOverlay.style.setProperty('bottom', 'calc(100% + 5px)', 'important');
                this._listOverlay.style.setProperty('max-height', Math.max(100, spaceAbove - 20) + 'px', 'important');
            } else {
                // Open downwards: Position it starting from top of relative container
                this._listOverlay.style.setProperty('top', '0', 'important');
                this._listOverlay.style.setProperty('bottom', 'auto', 'important');
                this._listOverlay.style.setProperty('max-height', Math.max(100, spaceBelow - 20) + 'px', 'important');
            }

            this._listOverlay.innerHTML = '<div style="font-weight:bold; padding-bottom:5px; border-bottom:1px solid #eee; margin-bottom:5px;">' + _('Site List') + '</div>';
            
            if (!this.options.sites || this.options.sites.length === 0) {
                this._listOverlay.innerHTML += '<div style="color:#999; font-size:12px;">' + _('No registered sites.') + '</div>';
                return;
            }

            this.options.sites.forEach(site => {
                const item = L.DomUtil.create('div', 'site-item', this._listOverlay);
                item.innerText = site.name;

                L.DomEvent.on(item, 'click', (e) => {
                    L.DomEvent.stop(e);
                    if (site.lat && site.lng) {
                        this._map.flyTo([site.lat, site.lng], site.zoom || 17);
                        this._listOverlay.classList.remove('active');
                    }
                });
            });
        }
    });

    /**
     * MeasureControl - Simple ruler tool.
     * Style: White Button, Shadow, Active State
     */
    L.Control.MeasureControl = L.Control.extend({
        options: {
            position: 'topright'
        },

        onAdd: function (map) {
            const container = L.DomUtil.create('div', 'leaflet-bar aot-custom-toolbar d-flex flex-column mt-2 aot-mr-10');

            const btn = L.DomUtil.create('a', 'aot-custom-btn', container);
            btn.href = '#';
            btn.title = _('Distance measurement');
            btn.role = 'button';
            
            const icon = L.DomUtil.create('i', 'fas fa-ruler-combined aot-map-btn-icon', btn);

            let isActive = false;
            let points = [];
            let line = null;
            let markers = [];
            let tooltip = null;

            // [Fix] SafePolyline to catch renderer crashes (Bounds errors)
            // This wrapper ensures that if Leaflet's internal bounds calculation fails, the app doesn't crash.
            const SafePolyline = L.Polyline.extend({
                _update: function () {
                    try {
                        L.Polyline.prototype._update.call(this);
                    } catch (e) {
                        // console.warn("[SafePolyline] Update error ignored:", e);
                    }
                },
                _clipPoints: function () {
                    try {
                        L.Polyline.prototype._clipPoints.call(this);
                    } catch (e) {
                        // console.warn("[SafePolyline] Clip error ignored:", e);
                    }
                }
            });

            const clearMeasure = () => {
                if (line) map.removeLayer(line);
                markers.forEach(m => map.removeLayer(m));
                if (tooltip) map.removeLayer(tooltip);
                // [New] Clear temp layers
                if (window.measureGuideLine) map.removeLayer(window.measureGuideLine);
                if (window.measureTooltip) map.removeLayer(window.measureTooltip);
                points = [];
                markers = [];
                line = null;
                tooltip = null;
                window.measureGuideLine = null;
                window.measureTooltip = null;
            };

            const updateMeasure = () => {
                if (points.length < 2) return;

                if (line) map.removeLayer(line);
                if (line) map.removeLayer(line);
                if (line) map.removeLayer(line);
                line = new SafePolyline(points, { 
                    color: '#e74c3c', 
                    weight: 3
                }).addTo(map);

                // Calculate total distance
                let totalDist = 0;
                for (let i = 0; i < points.length - 1; i++) {
                    totalDist += map.distance(points[i], points[i + 1]);
                }

                const distStr = totalDist > 1000 ? (totalDist / 1000).toFixed(2) + ' km' : totalDist.toFixed(1) + ' m';

                // Ensure tooltip exists
                if (!tooltip) {
                    tooltip = L.tooltip({ 
                        permanent: true, 
                        direction: 'right', 
                        className: 'measure-tooltip',
                        offset: [10, 0]
                    });
                    tooltip.setLatLng(points[points.length - 1]);
                    tooltip.addTo(map);
                } else {
                    tooltip.setLatLng(points[points.length - 1]);
                }
                
                tooltip.setContent(_('Distance') + ': ' + distStr);
            };

            btn.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                isActive = !isActive;

                if (isActive) {
                    btn.classList.add('active'); // CSS handles background/color
                    map.getContainer().style.cursor = 'crosshair';
                    map.on('click', onClick);
                    map.on('mousemove', onMouseMove); // [New]
                    
                    // Show toast if available
                    if (window.AoTMapApp && window.AoTMapApp.showToast) {
                        window.AoTMapApp.showToast(_("Distance measurement mode active. Click on map."), "info");
                    }
                } else {
                    btn.classList.remove('active');
                    map.getContainer().style.cursor = '';
                    map.off('click', onClick);
                    map.off('mousemove', onMouseMove); // [New]
                    clearMeasure();
                }
            };

            const onClick = (e) => {
                if (!e || !e.latlng) return;
                // [Fix] Strict Validation
                if (typeof e.latlng.lat !== 'number' || typeof e.latlng.lng !== 'number') return;

                try {
                    points.push(e.latlng);
                    
                    // [Fix] Use L.marker with DivIcon instead of L.circleMarker to avoid SVG Renderer Bounds errors
                    const dotIcon = L.divIcon({
                        className: '', // No default class
                        html: `<div style="width: 8px; height: 8px; background-color: white; border: 2px solid #e74c3c; border-radius: 50%;"></div>`,
                        iconSize: [8, 8],
                        iconAnchor: [4, 4]
                    });

                    const marker = L.marker(e.latlng, { icon: dotIcon }).addTo(map);
                    markers.push(marker);
                    updateMeasure();
                } catch (err) {
                    // console.error("[MeasureControl] Error adding point:", err);
                }
            };

            // [New] Mouse Move Handler for Guide Line
            const onMouseMove = (e) => {
                if (!e || !e.latlng) return;
                if (points.length === 0) return;

                const lastPoint = points[points.length - 1];
                const currentPoint = e.latlng;
                
                // Temporary Guide Line
                if (window.measureGuideLine) map.removeLayer(window.measureGuideLine);
                window.measureGuideLine = new SafePolyline([lastPoint, currentPoint], { 
                    color: '#e74c3c', 
                    weight: 2, 
                    dashArray: '5, 5', 
                    opacity: 0.6
                }).addTo(map);

                // Calculate distances
                let pastDist = 0;
                for (let i = 0; i < points.length - 1; i++) {
                    pastDist += map.distance(points[i], points[i + 1]);
                }
                const currentSegDist = map.distance(lastPoint, currentPoint);
                const totalDist = pastDist + currentSegDist;

                const distStr = totalDist > 1000 ? (totalDist / 1000).toFixed(2) + ' km' : totalDist.toFixed(1) + ' m';

                // Temporary Tooltip
                if (window.measureTooltip) map.removeLayer(window.measureTooltip);
                window.measureTooltip = L.tooltip({ 
                    permanent: true, 
                    direction: 'right', 
                    className: 'measure-tooltip-temp',
                    offset: [10, 0]
                })
                .setLatLng(currentPoint)
                .setContent(_('Total distance') + ': ' + distStr)
                .addTo(map);
            };

            // Hook up mousemove
            // Logic updated in btn.onclick below

            return container;
        }
    });

    /**
     * MemoControl - Allows placing custom text labels.
     * Style: White Button, Shadow, Active State
     */
    L.Control.MemoControl = L.Control.extend({
        options: {
            position: 'topright'
        },

        onAdd: function (map) {
            const container = L.DomUtil.create('div', 'leaflet-bar aot-custom-toolbar d-flex flex-column mt-2 aot-mr-10');

            const btn = L.DomUtil.create('a', 'aot-custom-btn', container);
            btn.href = '#';
            btn.title = _('Add note');
            btn.role = 'button';

            const icon = L.DomUtil.create('i', 'fas fa-sticky-note aot-map-btn-icon', btn);

            let isActive = false;

            btn.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                isActive = !isActive;

                if (isActive) {
                    btn.classList.add('active');
                    map.getContainer().style.cursor = 'copy';
                    map.on('click', onClick);
                } else {
                    btn.classList.remove('active');
                    map.getContainer().style.cursor = '';
                    map.off('click', onClick);
                }
            };

            const onClick = (e) => {
                if (window.dispatchEvent) {
                    const uniqueLocId = 'loc_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
                    window.dispatchEvent(new CustomEvent('open-notes', { 
                        detail: { 
                            targetId: uniqueLocId, 
                            targetType: 'map_location',
                            gps_lat: e.latlng.lat,
                            gps_lng: e.latlng.lng,
                            name: _('New Note')
                        } 
                    }));

                    // [Fix] Auto-exit mode after one click
                    isActive = false;
                    btn.classList.remove('active');
                    map.getContainer().style.cursor = '';
                    map.off('click', onClick);
                }
            };

            return container;
        }
    });
    
    /**
     * MeasurementPanel - Bottom Center Panel for Real-time Values
     * Style: White/Transparent Panel, Large Text, Horizontal Scroll
     */
    L.Control.MeasurementPanel = L.Control.extend({
        options: {
            position: 'bottomleft', // We manually position with CSS to center bottom
            measurements: [], // Array of { id, device_unique_id, device_type, name, unit, value }
            updateInterval: 300, // Seconds
            maxAge: 300 // Seconds
        },

        onAdd: function (map) {
            this._panel = L.DomUtil.create('div', 'aot-measurement-panel', map.getContainer());
            this._map = map;
            map._aotMeasurementPanel = this; // Store instance for sync
            L.DomEvent.disableClickPropagation(this._panel);
            L.DomEvent.disableScrollPropagation(this._panel); 

            // [New] Desktop Drag-to-Scroll Implementation
            let isDown = false;
            let startX;
            let scrollLeft;

            this._panel.addEventListener('mousedown', (e) => {
                isDown = true;
                this._panel.classList.add('active'); // Optional: for cursor grabbing
                this._panel.style.cursor = 'grabbing';
                startX = e.pageX - this._panel.offsetLeft;
                scrollLeft = this._panel.scrollLeft;
            });

            this._panel.addEventListener('mouseleave', () => {
                isDown = false;
                this._panel.style.cursor = 'grab';
            });

            this._panel.addEventListener('mouseup', () => {
                isDown = false;
                this._panel.style.cursor = 'grab';
            });

            this._panel.addEventListener('mousemove', (e) => {
                if (!isDown) return;
                e.preventDefault();
                const x = e.pageX - this._panel.offsetLeft;
                const walk = (x - startX) * 1.5; // Scroll-fast factor
                this._panel.scrollLeft = scrollLeft - walk;
            });
            
            // Set initial cursor
            this._panel.style.cursor = 'grab';

            if (!this.options.measurements || this.options.measurements.length === 0) {
                this._panel.style.display = 'none';
            }

            this.items = {};
            this._itemElements = [];
            
            // [Sorting] Sort measurements to display VPD first
            const vpdPatterns = [
                'vapor_pressure_deficit',
                'vaper_pressure_decifit',
                'vapor_pressure_deficite',
                'vapor pressure deficit',
                'vaper pressure deficit',
                'vpd'
            ];
            
            const sortedMeasurements = [...this.options.measurements].sort((a, b) => {
                const aName = (a.name || '').toLowerCase().trim();
                const bName = (b.name || '').toLowerCase().trim();
                
                const aIsVPD = vpdPatterns.some(p => aName.includes(p));
                const bIsVPD = vpdPatterns.some(p => bName.includes(p));
                
                if (aIsVPD && !bIsVPD) return -1;  // a comes first
                if (!aIsVPD && bIsVPD) return 1;   // b comes first
                return 0;  // maintain original order
            });
            
            sortedMeasurements.forEach((m, index) => {
                // Separator Logic moved to adjustLayout
                
                // [Fix] Do NOT append to _panel here.
                const item = L.DomUtil.create('div', 'aot-measurement-item'); 
                this._itemElements.push(item);
                
                // Value Row (Container for Value + Unit)
                const valDiv = L.DomUtil.create('div', 'aot-meas-value', item);
                valDiv.id = `meas-val-${m.id}`;
                
                // Value Span (Holds the number)
                const valSpan = L.DomUtil.create('span', '', valDiv);
                valSpan.innerText = (m.value !== undefined && m.value !== null && m.value !== '') ? m.value : '-';
                
                // Unit Span (Inline, 1/2 size, normal weight)
                // [Formatting] Hide unit if it is 'bearing'
                // [Fix] Avoid Double Unit Display (Init Phase)
                const isPureNumberInit = (val) => {
                     if (val === null || val === undefined) return false;
                     const s = String(val).trim().replace(/,/g, '');
                     return !isNaN(Number(s)) && s !== '';
                };
                
                // Only show unit if value is pure number AND unit is not bearing
                const shouldShowUnit = (m.unit && m.unit !== 'bearing') && isPureNumberInit(m.value);

                if (shouldShowUnit) {
                    const unitSpan = L.DomUtil.create('span', 'aot-meas-unit', valDiv);
                    unitSpan.innerText = m.unit; 
                    unitSpan.id = `meas-unit-${m.id}`;
                }

                // Name Row
                const row = L.DomUtil.create('div', 'aot-meas-name-row', item);
                
                if (m.name) {
                     const nameEl = L.DomUtil.create('span', 'aot-meas-name', row);
                     
                     let finalName = m.name;
                     
                     // [Formatting] 1. For INPUT/FUNCTION types, HIDE the [CH#] prefix if present
                     // This must happen BEFORE mapping checks (e.g. VPD) so that the check matches correctly.
                     if (m.device_type === 'input' || m.device_type === 'function') {
                         finalName = finalName.replace(/^\[CH\d+\]\s*/i, '');
                     }

                     // [Formatting] 2. Mapping for VPD (including common typos and spaces)
                     const vpdPatterns = [
                         'vapor_pressure_deficit', 
                         'vaper_pressure_decifit', 
                         'vapor_pressure_deficite',
                         'vapor pressure deficit',
                         'vaper pressure deficit'
                     ];
                     if (vpdPatterns.some(p => finalName.toLowerCase().includes(p))) {
                         finalName = 'VPD';
                     }

                     // [Formatting] 3. Prefer Device Name only
                     // [User Request] For Output (and duration_time), strictly use Device Name if available
                     const isDuration = (finalName.indexOf('duration_time') !== -1);
                     if ((m.device_type === 'output' || isDuration) && m.device_name) {
                         nameEl.innerText = m.device_name;
                     } 
                     else {
                         nameEl.innerText = finalName;
                     }
                }

                this.items[m.id] = { valSpan: valSpan, config: m };
            });
            
            // Bind Resize
            this._onResize = this.adjustLayout.bind(this);
            map.on('resize', this._onResize);
            
            // Initial adjustment (wait for render)
            setTimeout(() => this.adjustLayout(), 100);

            // Start Polling if interval > 0
            if (this.options.updateInterval > 0) {
                this.startPolling();
            }

            // [New] ResizeObserver for Real-time Legend monitoring
            // Monitors the map container for legend appearance/disappearance
            this._legendObserver = new ResizeObserver((entries) => {
                // Throttle adjustLayout to avoid thrashing
                if (this._resizeTimeout) clearTimeout(this._resizeTimeout);
                this._resizeTimeout = setTimeout(() => this.adjustLayout(), 50);
            });
            
            // Observe the map container (to catch when child legend is added/resized)
            // Ideally we observe the legend itself, but it might not exist yet.
            // Observing map container + checking legend in adjustLayout is safer.
            // But better: try to find existing legend and observe it, or observe map mutation?
            // Simple approach: Observe map container resize (already handled by map.on('resize'))
            // AND Observe legend specifically if found.
            
            const legend = map.getContainer().querySelector('.aot-legend-container');
            if (legend) {
                this._legendObserver.observe(legend);
            } else {
                // If not found, use MutationObserver to wait for it (optional, but robust)
                this._mutationObserver = new MutationObserver((mutations) => {
                    mutations.forEach((mutation) => {
                         if (mutation.addedNodes.length) {
                             const newLegend = map.getContainer().querySelector('.aot-legend-container');
                             if (newLegend) {
                                  this._legendObserver.observe(newLegend);
                                  this.adjustLayout();
                             }
                         }
                    });
                });
                this._mutationObserver.observe(map.getContainer(), { childList: true, subtree: true });
            }


            // Return dummy container for Leaflet Control API
            return L.DomUtil.create('div');
        },

        onRemove: function(map) {
            this.stopPolling();
            map.off('resize', this._onResize);
            
            if (this._legendObserver) {
                this._legendObserver.disconnect();
                this._legendObserver = null;
            }
            if (this._mutationObserver) {
                this._mutationObserver.disconnect();
                this._mutationObserver = null;
            }

            if (this._panel) {
                L.DomUtil.remove(this._panel);
                this._panel = null;
            }
        },

        adjustLayout: function() {
            if (!this._panel || !this._itemElements || this._itemElements.length === 0) return;
            const map = this._map;
            if (!map) return;

            const mapWidth = map.getSize().x;
            
            // [Fix] Use window.innerWidth to match CSS @media (max-width: 768px)
            // CSS treats < 768px as mobile. JS should effectively agree.
            const isDesktop = window.innerWidth > 768;
            
            // [New] Side-by-Side Desktop Logic
            const legend = map.getContainer().querySelector('.aot-legend-container');
            
            // [Safety] Even if isDesktop (window wise), if map container is too narrow, enforce mobile stack
            // to prevent squishing the panel into 0 width.
            const isMapTooNarrow = mapWidth < 350; 

            if (isDesktop && !isMapTooNarrow && legend && legend.style.display !== 'none') {
                // [Fix] Use getBoundingClientRect for accurate width including borders/padding
                const rect = legend.getBoundingClientRect();
                const legendWidth = rect.width || legend.offsetWidth || 260; 
                const sideMargins = 20; // 10px left + 10px right for widget edges
                
                // [Fix] Panel width = Total Width - Legend Width - Side Margins - 4px (Gap)
                this._panel.style.maxWidth = `${mapWidth - legendWidth - sideMargins - 4}px`;
                
                // [New] Dynamic Alignment: Left-align if legend is visible
                this._panel.classList.add('left-aligned');
            } else {
                this._panel.style.maxWidth = `calc(100% - 20px)`;
                
                // [New] Dynamic Alignment: Center if no legend
                this._panel.classList.remove('left-aligned');
            }

            // Helper to get CSS padding
            const style = window.getComputedStyle(this._panel);
            const availableContentWidth = (mapWidth - 20) - 10; 

            // 1. Determine N (Target Count per Page)
            const targetItemWidth = 100; // Use 120px as target width for calculation
            const sepTotalW = 11; 
            
            let N = Math.floor((availableContentWidth + sepTotalW) / (targetItemWidth + sepTotalW));
            if (N < 1) N = 1;

            // [New] Width Logic:
            const totalItems = this._itemElements.length;
            if (totalItems <= N) {
                this._panel.style.width = 'auto';
            } else {
                this._panel.style.width = 'calc(100% - 20px)';
            }
            
            // 2. Rebuild DOM into Pages
            this._panel.innerHTML = ''; 
            
            let currentItemIndex = 0;
            while (currentItemIndex < totalItems) {
                const page = L.DomUtil.create('div', 'aot-meas-page', this._panel);
                
                // Add up to N items to this page
                for (let i = 0; i < N && currentItemIndex < totalItems; i++) {
                    if (i > 0) {
                        L.DomUtil.create('div', 'aot-meas-separator', page);
                    }
                    
                    const item = this._itemElements[currentItemIndex];
                    page.appendChild(item); 
                    
                    // [Fix] Enforce minimum width for horizontal scroll to trigger
                    item.style.width = ''; 
                    item.style.flex = '1';
                    item.style.minWidth = '100px';

                    currentItemIndex++;
                }
            }
        },

        updateValue: function (id, value, unit) {
            if (this.items && this.items[id]) {
                const item = this.items[id];
                const valSpan = item.valSpan;
                const config = item.config;
                
                // Resolve Unit (from mapping if not provided)
                // We resolve this early to use in Wind Direction detection
                let targetUnit = unit;
                if (!targetUnit && window.aotMapUnits && window.aotMapUnits[id]) {
                    targetUnit = window.aotMapUnits[id];
                }
                // Fallback to config unit if defined
                if (!targetUnit && config.unit) {
                    targetUnit = config.unit;
                }

                // [Formatting] Check if Wind Direction
                const nameLower = (config.name || '').toLowerCase();
                const unitLower = (targetUnit || '').toLowerCase();
                
                // 1. Explicit Matches
                let isWindDirection = nameLower.includes('wind direction') || nameLower.includes('풍향');
                
                // 2. Scored Match (User Request: 2+ of Name='wind', Unit='direction', Unit='bearing')
                if (!isWindDirection) {
                    let score = 0;
                    if (nameLower.includes('wind')) score++;
                    if (unitLower.includes('direction')) score++;
                    if (unitLower.includes('bearing')) score++;
                    
                    if (score >= 2) isWindDirection = true;
                }

                // Update Value
                if (value !== undefined && value !== null && value !== '' && value !== 'N/A') {
                    if (isWindDirection) {
                        // Wind Direction: Show Arrow
                        valSpan.innerText = '';
                        valSpan.innerHTML = ''; 
                        
                        const arrow = L.DomUtil.create('i', 'fas fa-long-arrow-alt-up', valSpan);
                        // Rotation: 0 deg = North (Up).
                        // [Fix] Rotate 180 deg to show Flow Direction (0 N -> Points S)
                        arrow.style.transform = `rotate(${value + 180}deg)`;
                        arrow.style.display = 'inline-block';
                        arrow.style.fontSize = 'inherit';
                        // [Fix] Prevent clipping when rotated close to 90/270 deg
                        arrow.style.margin = '0 6px';
                        
                        valSpan.title = `${value}°`;
                    } else {
                        // Standard Value
                        let displayVal = value;
                        
                        // [Formatting] Output values as HH:MM:SS
                        if (config.device_type === 'output') {
                            displayVal = this._formatTime(value);
                        } else if (typeof value === 'number' && !Number.isInteger(value)) {
                             displayVal = parseFloat(value.toFixed(2));
                        }
                        
                        valSpan.innerText = displayVal;
                        valSpan.title = '';

                        // [Fix] Dynamic Font Sizing for Output Panel (More Aggressive)
                        // Heuristic: Base font is 1.8em. We need to fit ~100px.
                        // 00:00:00 is 8 chars.
                        const len = String(displayVal).length;
                        if (len >= 10) valSpan.style.fontSize = '0.65em';
                        else if (len >= 7) valSpan.style.fontSize = '0.75em'; // 00:00:00 fits here (~1.35em effective)
                        else valSpan.style.fontSize = ''; // Reset to CSS default
                    }
                } else {
                    valSpan.innerText = '-';
                    valSpan.innerHTML = '-'; 
                    valSpan.style.fontSize = '';
                }

                // Update Unit (Dynamic Creation/Update)
                // [Formatting] Hide 'bearing'
                // Also hide if unit is 'direction' AND it is actively being used as Wind Direction arrow?
                // User requirement was "Unit Mapping - 'bearing': do not output". 
                // For this new case, if unit is 'direction' and it's wind, maybe we should hide it too?
                // The user only explicitly said "bearing: do not output". 
                // However, usually arrows don't need units.
                // Let's stick to strict user request: "Unit Mapping - 'bearing': do not output".
                
                if (targetUnit && targetUnit !== 'bearing') {
                     let unitSpan = document.getElementById(`meas-unit-${id}`);
                     if (!unitSpan) {
                         unitSpan = L.DomUtil.create('span', 'aot-meas-unit', valSpan.parentElement); 
                         unitSpan.id = `meas-unit-${id}`;
                     }
                     
                     if (unitSpan.innerText !== targetUnit) {
                         unitSpan.innerText = targetUnit;
                     }

                     // [Fix] Avoid Double Unit Display
                     // If displayVal is NOT a pure number (e.g. "1.2 Pa" or "1.1 m_s"), hide the unit span.
                     // Exception: Allow commas (1,000)
                     const isPureNumber = (val) => {
                         if (val === null || val === undefined) return false;
                         const s = String(val).trim().replace(/,/g, '');
                         return !isNaN(Number(s)) && s !== '';
                     };

                     // Determine if we show unit
                     // If value is missing ('-'), we usually hide unit or show it? 
                     // Usually hide if no value. But existing logic didn't explicit hide.
                     // The logic below: if pure number, show unit. Else hide.
                     // If value is empty/null, valSpan is '-'. Not pure number. So unit hidden.
                     // If 'isWindDirection' (arrow), unit hidden.
                     
                     if (isWindDirection) {
                         unitSpan.style.display = 'none';
                     } else if (isPureNumber(displayVal)) {
                         unitSpan.style.display = ''; 
                     } else {
                         unitSpan.style.display = 'none';
                     }

                } else {
                    const existing = document.getElementById(`meas-unit-${id}`);
                    if (existing) existing.style.display = 'none';
                }
            }
        },

        startPolling: function() {
            this.stopPolling();
            
            const poll = () => {
                this.fetchAll().finally(() => {
                    this._timer = setTimeout(poll, this.options.updateInterval * 1000);
                });
            };
            
            poll();
        },

        stopPolling: function() {
            if (this._timer) {
                clearTimeout(this._timer);
                this._timer = null;
            }
        },

        fetchAll: function() {
            if (!this.items) return Promise.resolve();
            
            const promises = Object.values(this.items).map(item => {
                const cfg = item.config;
                if (cfg && cfg.device_unique_id && cfg.device_type && cfg.id) {
                    return this.fetchData(cfg);
                }
                return Promise.resolve();
            });
            return Promise.all(promises);
        },

        fetchData: function(cfg) {
            // [New] Output Duration Logic
            if (cfg.device_type === 'output') {
                 let baseId = cfg.device_unique_id;
                 let channel = 0;
                 if (baseId.includes('::')) {
                     const parts = baseId.split('::');
                     baseId = parts[0];
                     channel = parts[1];
                 }
                 
                 const url = `/output_last_duration_public/${baseId}/${channel}`;
                 
                 return fetch(url)
                    .then(r => r.json())
                    .then(d => {
                        if (d && d.last_duration_sec !== undefined) {
                            this.updateValue(cfg.id, d.last_duration_sec);
                        } else {
                            this.updateValue(cfg.id, null);
                        }
                    })
                    .catch(e => {
                        // console.error(`[MeasurementPanel] Output Fetch Error ${cfg.id}:`, e);
                    });
            }

            // Standard Sensor Logic
            let maxAge = this.options.maxAge;
            if (!maxAge || maxAge <= 0) maxAge = 300;
 
            const url = `/last/${cfg.device_unique_id}/${cfg.device_type}/${cfg.id}/${maxAge}`;
            
            return fetch(url)
                .then(res => {
                    if (res.status === 204 || res.status === 404) return null;
                    return res.json();
                })
                .then(data => {
                    // Format: [epoch, value]
                    if (Array.isArray(data) && data.length >= 2) {
                        this.updateValue(cfg.id, data[1]);
                    } else if (data && data.value !== undefined) {
                         this.updateValue(cfg.id, data.value);
                    } else {
                        // NO DATA or Timed out
                        this.updateValue(cfg.id, null);
                    }
                })
                .catch(err => {
                    // console.error(`[MeasurementPanel] Fetch Error for ${cfg.id}:`, err);
                });
        },

        _formatTime: function (seconds) {
            if (seconds === undefined || seconds === null || seconds === '') return '-';
            const s = Math.floor(Number(seconds));
            if (isNaN(s)) return seconds;

            const hrs = Math.floor(s / 3600);
            const mins = Math.floor((s % 3600) / 60);
            const secs = s % 60;

            return [
                hrs.toString().padStart(2, '0'),
                mins.toString().padStart(2, '0'),
                secs.toString().padStart(2, '0')
            ].join(':');
        }
    });

    // Expose Factories
    L.control.siteList = function (opts) { return new L.Control.SiteListControl(opts); };
    L.control.measure = function (opts) { return new L.Control.MeasureControl(opts); };
    L.control.memo = function (opts) { return new L.Control.MemoControl(opts); };
    /**
     * ToggleMeasurementPanel - Toggle visibility of the Measurement Panel.
     * Style: White Button, Shadow, Chevron Icon
     * Logic: Matches Geo Design 'tool-toggle-panel' but adapted for BOTTOM panel.
     * - Top Panel (Geo Design): Visible=Down (Expanded Down), Hidden=Up.
     * - Bottom Panel (Here): Visible=Up (Expanded Up), Hidden=Down.
     * - Uses MutationObserver to verify state changes from external sources.
     */
    L.Control.ToggleMeasurementPanel = L.Control.extend({
        options: {
            position: 'topright'
        },

        onAdd: function (map) {
            const container = L.DomUtil.create('div', 'leaflet-bar aot-custom-toolbar d-flex flex-column mt-2 aot-ml-10');

            const btn = L.DomUtil.create('a', 'aot-custom-btn', container);
            btn.href = '#';
            btn.role = 'button';
            
            const icon = L.DomUtil.create('i', 'fas aot-map-btn-icon', btn);

            // Function to update button state based on ACTUAL panel visibility
            const updateState = () => {
                if (!map.measurementPanel || !map.measurementPanel._panel) return;
                
                const panelEl = map.measurementPanel._panel;
                // Check computed style or inline style
                const isHidden = (panelEl.style.display === 'none');

                if (isHidden) {
                    // State: Hidden (Collapsed at Bottom)
                    // Action: Show (Expand Up)
                    // Icon: Down (Matches 'Collapsed' state or simple 'Show' direction for some, 
                    // but usually strictly inverted to visible=up)
                    // Let's stick to: Visible=UP (Expanded Up), Hidden=DOWN (Collapsed Down)
                    icon.className = 'fas fa-chevron-down aot-map-btn-icon';
                    btn.title = _('Show panel');
                    btn.dataset.hidden = 'true';
                } else {
                    // State: Visible (Expanded Up)
                    // Action: Hide (Collapse Down)
                    // Icon: Up (Indicates "It is Up")
                    icon.className = 'fas fa-chevron-up aot-map-btn-icon';
                    btn.title = _('Hide panel');
                    btn.dataset.hidden = 'false';
                }
            };

            // 1. Initial Update
            // Defer slightly to ensure panel might be ready? No, direct check is fine.
            setTimeout(updateState, 0);

            // 2. Click Handler
            btn.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();

                if (map.measurementPanel && map.measurementPanel._panel) {
                    const panelEl = map.measurementPanel._panel;
                    const isHidden = (panelEl.style.display === 'none');

                    if (isHidden) {
                        panelEl.style.display = ''; // Show
                        map.fire('resize');
                    } else {
                        panelEl.style.display = 'none'; // Hide
                    }
                    // State update handled by MutationObserver or manual call
                    updateState();
                }
            };

            // 3. MutationObserver for External Changes
            if (map.measurementPanel && map.measurementPanel._panel) {
                const observer = new MutationObserver((mutations) => {
                    mutations.forEach((mutation) => {
                        if (mutation.type === 'attributes' && (mutation.attributeName === 'style' || mutation.attributeName === 'class')) {
                            updateState();
                        }
                    });
                });
                
                observer.observe(map.measurementPanel._panel, { attributes: true });
                
                // Cleanup on remove? Leaflet controls usually don't get removed often, 
                // but good practice might be to store observer.
                this._observer = observer;
            } else {
                // If panel adds later? (Unlikely for this widget structure)
                // We can retry or hook into map init? 
                // For now, assume panel exists as they are added in order.
            }

            return container;
        },

        onRemove: function(map) {
            if (this._observer) {
                this._observer.disconnect();
            }
        }
    });

    L.control.measurementPanel = function (opts) { return new L.Control.MeasurementPanel(opts); };
    L.control.toggleMeasurementPanel = function (opts) { return new L.Control.ToggleMeasurementPanel(opts); };

})();
