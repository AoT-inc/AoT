/**
 * aot-map-controls.js
 * Map Controls for AoT Map Widget (MapLibre Compatible)
 * Updated from Leaflet to MapLibre GL native controls + HTML overlays.
 * @version 2.0.0 - MapLibre migration
 */

(function () {
    if (window.AoTMapControls) return;

    // Wait for either L (Leaflet shim) or maplibregl to be available
    var waitCount = 0;
    var maxWait = 100;

    function checkAndInit() {
        if (typeof L !== 'undefined' && L.Control && L.Control.extend) {
            initWithLeaflet();
            return;
        }
        if (typeof maplibregl !== 'undefined') {
            initWithMapLibre();
            return;
        }
        waitCount++;
        if (waitCount < maxWait) {
            setTimeout(checkAndInit, 50);
        }
    }

    // Start checking
    checkAndInit();

    /**
     * MapLibre Native Controls Initializer
     */
    function initWithMapLibre() {
        window.AoTMapControls = {
            /**
             * Get compatibility helpers for map type
             * @param {maplibregl.Map|L.Map} map
             */
            _getMapType: function(map) {
                if (typeof maplibregl !== 'undefined' && map instanceof maplibregl.Map) {
                    return 'maplibre';
                }
                if (map && map._isAoTShim) {
                    return 'shim';
                }
                return 'leaflet';
            },

            /**
             * Add Navigation Control (Zoom +/- buttons)
             * @param {maplibregl.Map|L.Map} map
             * @param {string} position - 'top-left', 'top-right', 'bottom-left', 'bottom-right'
             */
            addNavigationControl: function(map, position) {
                const type = this._getMapType(map);
                if (type === 'maplibre' || type === 'shim') {
                    if (!map.hasControl || !map.hasControl(new maplibregl.NavigationControl())) {
                        map.addControl(new maplibregl.NavigationControl({
                            showCompass: true,
                            showZoom: true,
                            visualizePitch: true
                        }), position || 'top-left');
                    }
                } else if (typeof L !== 'undefined') {
                    map.addControl(new L.Control.Zoom({ position: position || 'topleft' }));
                }
            },

            /**
             * Add Scale Control
             * @param {maplibregl.Map|L.Map} map
             */
            addScaleControl: function(map) {
                const type = this._getMapType(map);
                if (type === 'maplibre' || type === 'shim') {
                    map.addControl(new maplibregl.ScaleControl({
                        maxWidth: 100,
                        unit: 'metric'
                    }), 'bottom-left');
                } else if (typeof L !== 'undefined') {
                    map.addControl(L.control.scale({ metric: true, imperial: false }));
                }
            },

            /**
             * Add Attribution Control
             * @param {maplibregl.Map|L.Map} map
             */
            addAttributionControl: function(map) {
                const type = this._getMapType(map);
                if (type === 'maplibre' || type === 'shim') {
                    map.addControl(new maplibregl.AttributionControl({
                        compact: true
                    }), 'bottom-right');
                } else if (typeof L !== 'undefined') {
                    L.control.attribution({ prefix: false }).addTo(map);
                }
            },

            /**
             * Custom HTML-based Tool Button
             * @param {maplibregl.Map|L.Map} map
             * @param {Object} options - { iconClass, title, onClick, position }
             */
            createToolButton: function(map, options) {
                const mapContainer = map.getContainer();
                const pos = options.position || 'top-left';

                // Create button element
                const btn = document.createElement('a');
                btn.href = '#';
                btn.className = 'aot-custom-btn';
                if (window.AoTSetTitle) window.AoTSetTitle(btn, options.title); else btn.title = options.title || '';
                btn.setAttribute('role', 'button');

                const icon = document.createElement('i');
                icon.className = options.iconClass + ' aot-map-btn-icon';
                btn.appendChild(icon);

                // Style
                btn.style.cssText = `
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    width: 34px;
                    height: 34px;
                    border-radius: 4px;
                    background: white;
                    border: 1px solid #ddd;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    cursor: pointer;
                    text-decoration: none;
                    color: #333;
                `;

                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    if (options.onClick) {
                        options.onClick(e, map);
                    }
                });

                // Create or find container
                let container = mapContainer.querySelector('.aot-custom-toolbar.' + pos);
                if (!container) {
                    container = document.createElement('div');
                    container.className = 'aot-custom-toolbar ' + pos;
                    container.style.cssText = `
                        position: absolute;
                        ${pos.includes('top') ? 'top' : 'bottom'}: 10px;
                        ${pos.includes('left') ? 'left' : 'right'}: 10px;
                        display: flex;
                        flex-direction: column;
                        gap: 5px;
                        z-index: var(--aot-z-fixed-panel);
                    `;
                    mapContainer.style.position = 'relative';
                    mapContainer.appendChild(container);
                }

                container.appendChild(btn);
                return btn;
            },

            /**
             * Create Fullscreen Toggle Button
             */
            addFullscreenButton: function(map) {
                const self = this;
                return this.createToolButton(map, {
                    iconClass: 'fas fa-expand',
                    title: window._ ? window._('Fullscreen') : 'Fullscreen',
                    position: 'top-left',
                    onClick: function(e, map) {
                        const canvas = map.getContainer();
                        const elem = canvas.closest('.aot-map-container') || canvas;
                        const doc = document;
                        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
                        const requestFullScreen = elem.requestFullscreen || elem.webkitRequestFullscreen ||
                                                   elem.mozRequestFullScreen || elem.msRequestFullscreen;

                        if (isIOS || !requestFullScreen) {
                            // Pseudo-fullscreen (iOS / browsers without the Fullscreen API).
                            // The map container lives inside a grid-stack-item whose CSS `transform`
                            // (and other transformed ancestors) both create a stacking context AND,
                            // on iOS Safari, become the containing block for `position: fixed`.
                            // That traps the fullscreen map below the navbar/dash-tabs and offsets
                            // it downward. Reparenting the container to <body> escapes every
                            // ancestor stacking context / transform, so `position: fixed` resolves
                            // against the viewport and the map covers the whole screen on top.
                            const isEntering = !elem.classList.contains('aot-map-pseudo-fullscreen');
                            if (isEntering) {
                                if (!elem._aotFsPlaceholder) {
                                    const ph = document.createComment('aot-fs-placeholder');
                                    elem._aotFsPlaceholder = ph;
                                    if (elem.parentNode) elem.parentNode.insertBefore(ph, elem);
                                }
                                document.body.appendChild(elem);
                                elem.classList.add('aot-map-pseudo-fullscreen');
                                document.body.classList.add('aot-map-fullscreen-active');
                            } else {
                                elem.classList.remove('aot-map-pseudo-fullscreen');
                                document.body.classList.remove('aot-map-fullscreen-active');
                                // Restore the container to its original DOM position.
                                const ph = elem._aotFsPlaceholder;
                                if (ph && ph.parentNode) {
                                    ph.parentNode.insertBefore(elem, ph);
                                    ph.parentNode.removeChild(ph);
                                }
                                elem._aotFsPlaceholder = null;
                            }
                            // MapLibre must re-measure after the DOM move / size change.
                            setTimeout(function () { try { map.resize(); } catch (err) {} }, 50);
                        } else if (!doc.fullscreenElement) {
                            requestFullScreen.call(elem);
                        } else {
                            doc.exitFullscreen && doc.exitFullscreen();
                        }
                    }
                });
            },

            /**
             * Create Search Toggle Button
             */
            addSearchButton: function(map, options) {
                return this.createToolButton(map, {
                    iconClass: 'fas fa-search',
                    title: window._ ? window._('Address Search') : 'Search',
                    position: 'top-left',
                    onClick: function(e, map) {
                        const targetId = options && options.searchTargetId ? options.searchTargetId : 'map-search-overlay';
                        const el = document.getElementById(targetId);
                        if (el) {
                            el.style.display = el.style.display === 'none' ? 'block' : 'none';
                            if (el.style.display === 'block') {
                                setTimeout(function() {
                                    const searchEl = el.querySelector('aot-map-search-fixed');
                                    if (searchEl && searchEl.shadowRoot) {
                                        const inp = searchEl.shadowRoot.getElementById('input');
                                        if (inp) inp.focus();
                                    }
                                }, 100);
                            }
                        }
                    }
                });
            },

            /**
             * Create Location Button (Geolocation)
             */
            addLocationButton: function(map, options) {
                const self = this;
                let locationMarker = null;
                let locationCircle = null;

                // Geolocation events
                if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition(function(pos) {
                        const lng = pos.coords.longitude;
                        const lat = pos.coords.latitude;
                        const radius = pos.coords.accuracy;

                        if (locationMarker) map.removeLayer(locationMarker);
                        if (locationCircle) map.removeLayer(locationCircle);

                        // Use MapLibre or Leaflet marker
                        const center = { lng: lng, lat: lat };
                        map.flyTo(center, 16);

                        // Add marker circle (simplified)
                        if (map._isAoTShim) {
                            // MapLibre shim
                            console.log('[AoTMapControls] Location found:', lat, lng);
                        }
                    }, function(err) {
                        console.warn('[AoTMapControls] Location error:', err.message);
                        if (window.AoTMapApp && window.AoTMapApp.showToast) {
                            const msg = window._ ? window._('Location check failed: ') : 'Location failed: ';
                            window.AoTMapApp.showToast(msg + err.message, 'error');
                        }
                    });
                }

                return this.createToolButton(map, {
                    iconClass: 'fas fa-location-arrow',
                    title: window._ ? window._('Current Location') : 'My Location',
                    position: 'top-left',
                    onClick: function(e, map) {
                        if (navigator.geolocation) {
                            navigator.geolocation.getCurrentPosition(function(pos) {
                                const center = { lng: pos.coords.longitude, lat: pos.coords.latitude };
                                map.flyTo(center, 16);
                            }, function(err) {
                                if (window.AoTMapApp && window.AoTMapApp.showToast) {
                                    const msg = window._ ? window._('Location check failed: ') : 'Location failed: ';
                                    window.AoTMapApp.showToast(msg + err.message, 'error');
                                }
                            });
                        }
                    }
                });
            },

            /**
             * Create Lock/Hide Controls Panel
             */
            addStateControls: function(map, options) {
                const self = this;
                options = options || {};
                let isLocked = options.isLocked || false;
                let isHidden = options.isHidden || false;

                const createBtn = function(iconClass, title, onClick) {
                    return self.createToolButton(map, {
                        iconClass: iconClass,
                        title: title,
                        position: 'topleft',
                        onClick: onClick
                    });
                };

                // Lock button
                const lockBtn = createBtn(
                    isLocked ? 'fas fa-lock' : 'fas fa-unlock',
                    window._ ? (isLocked ? window._('Unlock Map') : window._('Lock Map')) : (isLocked ? 'Unlock' : 'Lock'),
                    function(e, map) {
                        isLocked = !isLocked;
                        const newIcon = isLocked ? 'fas fa-lock' : 'fas fa-unlock';
                        const iconEl = lockBtn.querySelector('i');
                        if (iconEl) iconEl.className = newIcon + ' aot-map-btn-icon';

                        // Apply map interaction restrictions
                        if (map.setDraggable) {
                            map.setDraggable(!isLocked);
                        }
                        if (map.scrollZoom && isLocked) {
                            map.scrollZoom.disable();
                        } else if (map.scrollZoom && !isLocked) {
                            map.scrollZoom.enable();
                        }

                        if (options.onLockChange) options.onLockChange(isLocked);
                    }
                );
                lockBtn.classList.add('aot-lock-btn');

                // Hide button
                const hideBtn = createBtn(
                    'fas fa-grip-horizontal',
                    window._ ? (isHidden ? window._('Show Controls') : window._('Hide Controls')) : (isHidden ? 'Show' : 'Hide'),
                    function(e, map) {
                        isHidden = !isHidden;
                        const iconEl = hideBtn.querySelector('i');
                        if (iconEl) { iconEl.className = 'fas fa-grip-horizontal aot-map-btn-icon'; iconEl.style.opacity = isHidden ? '0.35' : ''; }

                        // Hide/show all controls
                        const controls = map.getContainer().querySelectorAll('.maplibregl-ctrl, .leaflet-control, .aot-custom-toolbar');
                        controls.forEach(function(c) {
                            if (isHidden) {
                                c.style.display = 'none';
                            } else {
                                c.style.display = '';
                            }
                        });

                        if (options.onHideChange) options.onHideChange(isHidden);
                    }
                );

                return { lockBtn: lockBtn, hideBtn: hideBtn };
            },

            /**
             * Add RainViewer Radar Toggle
             */
            addRainViewerButton: function(map, uid) {
                return this.createToolButton(map, {
                    iconClass: 'fas fa-cloud-rain',
                    title: window._ ? window._('RainViewer Radar') : 'Radar',
                    position: 'top-left',
                    onClick: function(e, map) {
                        if (window.AoTMapApp && window.AoTMapApp[uid] && window.AoTMapApp[uid].rainviewerController) {
                            window.AoTMapApp[uid].rainviewerController.toggle();
                        }
                    }
                });
            },

            /**
             * Standard controls set for AoT Map
             */
            addStandardControls: function(map, callbacks, uid) {
                this.addNavigationControl(map, 'top-right');
                this.addFullscreenButton(map);
                this.addSearchButton(map, callbacks);
                this.addLocationButton(map, callbacks);

                if (callbacks && callbacks.onReset) {
                    this.createToolButton(map, {
                        iconClass: 'fas fa-undo',
                        title: window._ ? window._('Reset') : 'Reset',
                        position: 'top-left',
                        onClick: callbacks.onReset
                    });
                }

                if (uid) {
                    this.addRainViewerButton(map, uid);
                }

                this.addStateControls(map, callbacks);
            },

            /**
             * Disable/Enable all map controls
             */
            toggleTools: function(enabled) {
                const controls = document.querySelectorAll('.aot-custom-btn, .maplibregl-ctrl button, .leaflet-control button');
                controls.forEach(function(c) {
                    if (enabled) {
                        c.classList.remove('disabled');
                        c.style.pointerEvents = '';
                        c.style.opacity = '';
                    } else {
                        c.classList.add('disabled');
                        c.style.pointerEvents = 'none';
                    }
                });
            }
        };
    }

    /**
     * Leaflet Compatibility Initializer (for L.Control based controls)
     */
    function initWithLeaflet() {
        // Legacy Leaflet controls for backward compatibility
        if (typeof L === 'undefined' || !L.Control) return;

        window.AoTMapControls = window.AoTMapControls || {};

        // Copy over Leaflet-based controls if they exist
        if (L.Control.Zoom) {
            window.AoTMapControls.ZoomControl = L.Control.Zoom;
        }

        // Copy methods that wrap Leaflet
        const compat = {
            addNavigationControl: function(map, position) {
                if (map.addControl && L.Control.Zoom) {
                    map.addControl(new L.Control.Zoom({ position: position || 'topleft' }));
                }
            }
        };

        // Extend with Leaflet methods if not already defined
        Object.keys(compat).forEach(function(key) {
            if (!window.AoTMapControls[key]) {
                window.AoTMapControls[key] = compat[key];
            }
        });
    }

})();
