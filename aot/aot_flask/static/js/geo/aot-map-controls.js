/**
 * aot-map-controls.js
 * Contains reusable configuration for Leaflet Map Controls.
 * Exposed as global object AoTMapControls.
 * Updated to match Geo Design styles (White Round Buttons, Shadow).
 */

(function () {
    if (window.AoTMapControls) return;

    // [Iteration 16] Leadlet Availability Check: Wait until L is available globally
    if (typeof L === 'undefined') {
        setTimeout(arguments.callee, 50);
        return;
    }

    window.AoTMapControls = {
        /**
         * Custom Zoom Control (+/- buttons)
         * Style: Vertical Group, White Buttons, Shadow
         */
        ZoomControl: L.Control.extend({
            options: { position: 'topleft' },
            onAdd: function (map) {
                const container = L.DomUtil.create('div', 'leaflet-bar d-flex flex-column');
                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.disableScrollPropagation(container);

                const createBtn = (iconClass, title, onClick) => {
                    const btn = L.DomUtil.create('a', 'aot-custom-btn', container);
                    btn.href = '#';
                    btn.role = 'button';
                    btn.title = title;
                    const icon = L.DomUtil.create('i', iconClass + ' aot-map-btn-icon', btn);
                    
                    L.DomEvent.on(btn, 'click', (e) => {
                        L.DomEvent.stop(e);
                        onClick(e);
                    });
                    return btn;
                };

                createBtn('fas fa-plus', window._('Zoom In'), () => map.zoomIn());
                createBtn('fas fa-minus', window._('Zoom Out'), () => map.zoomOut());

                return container;
            }
        }),

        ToolsControl: L.Control.extend({
            options: { position: 'topleft' },
            onAdd: function (map) {
                const container = L.DomUtil.create('div', 'leaflet-bar d-flex flex-column mt-2');
                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.disableScrollPropagation(container);
                const opts = this.options;

                const createBtn = (iconClass, title, onClick) => {
                    const btn = L.DomUtil.create('a', 'aot-custom-btn', container);
                    btn.href = '#';
                    btn.role = 'button';
                    btn.title = title;
                    const icon = L.DomUtil.create('i', iconClass + ' aot-map-btn-icon', btn);

                    L.DomEvent.on(btn, 'click', (e) => {
                        L.DomEvent.stop(e);
                        onClick(e);
                    });
                    return btn;
                };

                // Fullscreen
                createBtn('fas fa-expand', window._('Fullscreen'), () => {
                    const canvas = map.getContainer();
                    // [Fix] Request fullscreen for the parent container so siblings (like search-overlay) are visible
                    const elem = canvas.closest('.aot-map-container') || canvas;
                    const doc = window.document;
                    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
                    const requestFullScreen = elem.requestFullscreen || elem.webkitRequestFullscreen || elem.mozRequestFullScreen || elem.msRequestFullscreen;
                    const exitFullScreen = doc.exitFullscreen || doc.webkitExitFullscreen || doc.webkitCancelFullScreen || doc.mozCancelFullScreen || doc.msExitFullscreen;
                    const getFullScreenElement = () => doc.fullscreenElement || doc.webkitFullscreenElement || doc.mozFullScreenElement || doc.msFullscreenElement;

                    const toggleCssMode = () => {
                        const fsClass = 'aot-map-pseudo-fullscreen';
                        const bodyFsClass = 'aot-map-fullscreen-active';
                        const parentItem = elem.closest('.grid-stack-item');
                        
                        if (elem.classList.contains(fsClass)) {
                            elem.classList.remove(fsClass);
                            document.body.classList.remove(bodyFsClass);
                            if (parentItem) parentItem.classList.remove('aot-fs-parent');
                            // [Fix] Fallback for non-gridstack pages (e.g. geo/design)
                            else {
                                const cleanWrapper = document.querySelector('.aot-map-container');
                                if(cleanWrapper) cleanWrapper.classList.remove('aot-fs-parent');
                            }
                        } else {
                            elem.classList.add(fsClass);
                            document.body.classList.add(bodyFsClass);
                            if (parentItem) parentItem.classList.add('aot-fs-parent');
                            // [Fix] Fallback for non-gridstack pages
                            else {
                                const cleanWrapper = document.querySelector('.aot-map-container');
                                if(cleanWrapper) cleanWrapper.classList.add('aot-fs-parent');
                            }
                        }
                        setTimeout(() => map.invalidateSize(), 150);
                    };

                    if (isIOS || !requestFullScreen) {
                        toggleCssMode();
                    } else if (!getFullScreenElement()) {
                        const p = requestFullScreen.call(elem);
                        if (p && typeof p.catch === 'function') {
                            p.catch(() => toggleCssMode());
                        }
                    } else {
                        if (exitFullScreen) exitFullScreen.call(doc);
                        else {
                            elem.classList.remove('aot-map-pseudo-fullscreen');
                            document.body.classList.remove('aot-map-fullscreen-active');
                        }
                    }
                });

                // Search
                createBtn('fas fa-search', window._('Address Search'), () => {
                    if (opts.onSearch) opts.onSearch();
                    else {
                        const targetId = opts.searchTargetId || 'map-search-overlay';
                        const el = document.getElementById(targetId);
                        if (el) {
                            const isNone = el.style.display === 'none';
                            el.style.display = isNone ? 'block' : 'none';
                            if (isNone) {
                                setTimeout(() => {
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

                // Locate
                createBtn('fas fa-location-arrow', window._('Current Location'), () => {
                    if (opts.onLocate) opts.onLocate();
                    else {
                        map.locate({ setView: true, maxZoom: 16 });
                    }
                });

                // [New] Handle Location Found
                map.on('locationfound', (e) => {
                    const radius = e.accuracy / 2;
                    if(window.currentLocMarker) map.removeLayer(window.currentLocMarker);
                    if(window.currentLocCircle) map.removeLayer(window.currentLocCircle);

                    window.currentLocMarker = L.marker(e.latlng).addTo(map)
                        .bindPopup(window._('Current Location') + " (" + radius.toFixed(0) + "m within)").openPopup();
                    window.currentLocCircle = L.circle(e.latlng, radius).addTo(map);
                });

                map.on('locationerror', (e) => {
                    if (window.AoTMapApp && window.AoTMapApp.showToast) {
                        window.AoTMapApp.showToast(window._("Location check failed: ") + e.message, "error");
                    } else {
                        alert(window._("Location check failed: ") + e.message);
                    }
                });

                // Reset
                createBtn('fas fa-undo', window._('Reset'), () => {
                    if (opts.onReset) opts.onReset();
                });

                return container;
            }
        }),

        StateControl: L.Control.extend({
            options: {
                position: 'topleft',
                onLockChange: null,
                onHideChange: null,
                isLocked: false,
                isHidden: false
            },
            onAdd: function (map) {
                // Removed leaflet-bar, use flex column
                const container = L.DomUtil.create('div', 'd-flex flex-column mt-3');
                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.disableScrollPropagation(container);
                const opts = this.options;

                const createBtn = (iconClass, title, onClick) => {
                    // Circle Button Style
                    const btn = L.DomUtil.create('a', 'btn btn-white btn-circle bg-white shadow-sm d-flex align-items-center justify-content-center mb-2', container);
                    btn.href = '#';
                    btn.role = 'button';
                    btn.title = title;
                    const icon = L.DomUtil.create('i', iconClass + ' aot-map-btn-icon', btn);

                    L.DomEvent.on(btn, 'click', (e) => {
                        L.DomEvent.stop(e);
                        onClick(e, btn);
                    });
                    return btn;
                };

                // Lock
                let isLocked = opts.isLocked || false;
                // Default: Unlock (open) -> Click -> Lock
                const lockBtn = createBtn(isLocked ? 'fas fa-lock' : 'fas fa-unlock', isLocked ? window._('Unlock Map') : window._('Lock Map'), (e, btn) => {
                    isLocked = !isLocked;
                    this._updateLock(map, isLocked, btn);
                    if (opts.onLockChange) opts.onLockChange(isLocked);
                });
                lockBtn.classList.add('aot-lock-btn'); // [New] Identify for hiding

                if (isLocked) this._updateLock(map, true, lockBtn);

                // Hide
                let isHidden = opts.isHidden || false;
                // Default: Eye (visible) -> Click -> Eye Slash (hidden)
                const hideBtn = createBtn(isHidden ? 'fas fa-eye-slash' : 'fas fa-eye', isHidden ? window._('Show Controls') : window._('Hide Controls'), (e, btn) => {
                    isHidden = !isHidden;
                    this._updateHide(map, isHidden, btn, container);
                    if (opts.onHideChange) opts.onHideChange(isHidden);
                });

                if (isHidden) {
                    setTimeout(() => this._updateHide(map, true, hideBtn, container), 100);
                }

                return container;
            },

            _updateLock: function (map, isLocked, btn) {
                // [Robust] Force Icon Update via InnerHTML
                if (isLocked) {
                    map.dragging.disable();
                    map.touchZoom.disable();
                    map.doubleClickZoom.disable();
                    map.scrollWheelZoom.disable();
                    
                    btn.innerHTML = '<i class="fas fa-lock aot-map-btn-icon"></i>';
                    
                    btn.title = window._('Unlock Map');
                    btn.classList.add('active'); 
                    
                    // [Style] Dark Gray Background for Lock Emphasis
                    btn.classList.remove('bg-white'); 
                    btn.classList.remove('text-primary');
                    btn.style.backgroundColor = '#555555'; // Dark Gray
                    btn.style.color = '#ffffff'; // White Icon
                    btn.style.borderColor = '#555555';
                } else {
                    map.dragging.enable();
                    map.touchZoom.enable();
                    map.doubleClickZoom.enable();
                    map.scrollWheelZoom.enable();
                    
                    btn.innerHTML = '<i class="fas fa-unlock aot-map-btn-icon"></i>';
                    
                    btn.title = window._('Lock Map');
                    btn.classList.remove('active');
                    
                    // [Style] Restore White Background
                    btn.style.backgroundColor = '';
                    btn.style.color = '';
                    btn.style.borderColor = '';
                    btn.classList.add('bg-white');
                }
            },

            _updateHide: function (map, isHidden, btn, container) {
                const mapContainer = map.getContainer();
                const controls = mapContainer.querySelectorAll('.leaflet-control');
                
                // [Fix] Robust hiding of Lock Button using !important
                const lockBtn = container.querySelector('.aot-lock-btn');
                if (lockBtn) {
                    if (isHidden) lockBtn.style.setProperty('display', 'none', 'important');
                    else lockBtn.style.removeProperty('display');
                }
                
                controls.forEach(c => {
                    if (c.contains(container)) return; 
                    const isKeeper = c.classList.contains('leaflet-control-layers') ||
                        c.classList.contains('leaflet-control-attribution') ||
                        c.classList.contains('aot-map-site-list-control-container') ||
                        c.classList.contains('aot-legend-container');
                    if (isKeeper) return;

                    if (isHidden) {
                        const displayed = c.style.display !== 'none';
                        if (displayed) {
                            c.style.setProperty('display', 'none', 'important');
                            c.classList.add('aot-hidden-temp');
                        }
                    } else {
                        if (c.classList.contains('aot-hidden-temp')) {
                            c.style.removeProperty('display');
                            c.classList.remove('aot-hidden-temp');
                        }
                    }
                });

                // [Robust] Force Icon Update via InnerHTML
                const iconClass = isHidden ? 'fas fa-eye-slash' : 'fas fa-eye';
                btn.innerHTML = `<i class="${iconClass} aot-map-btn-icon"></i>`;
                
                btn.title = isHidden ? window._('Show Controls') : window._('Hide Controls');
                if (isHidden) {
                    btn.classList.add('active');
                    btn.classList.add('text-primary'); // Visual Feedback
                } else {
                    btn.classList.remove('active');
                    btn.classList.remove('text-primary');
                }
            }
        }),

        styleLayerControl: function (container) {
            // No-op: Let Leaflet native styles apply.
            // This ensures consistent size, shape (square), and shadow with other leaflet-bar controls.
            if (!container) return;
            // Optionally ensure it has shadow-sm if we wanted to match User's "Zoom" but User said "Zoom z-depth is Low"
            // Native leaflet-control-layers usually has standard leaflet shadow.
        },

        /**
         * Helper to add a group of controls commonly used
         * Includes handling the placement of Layer Control if provided
         */
        addStandardControls: function (map, callbacks = {}, layerControl = null) {
            map.addControl(new this.ZoomControl());
            map.addControl(new this.ToolsControl(callbacks));
            map.addControl(new this.StateControl());

            // Style Layer Control if it exists and is in the DOM
            if (layerControl) {
                const container = layerControl.getContainer();
                this.styleLayerControl(container);
            }
        },

        /**
         * Disable/Enable all map controls and drawing tools
         * @param {boolean} enabled 
         */
        toggleTools: function (enabled) {
            const selector = '.leaflet-control button, .leaflet-control a';
            const controls = document.querySelectorAll(selector);
            controls.forEach(c => {
                if (enabled) {
                    c.classList.remove('disabled');
                    c.style.removeProperty('pointer-events');
                    c.style.removeProperty('opacity');
                } else {
                    c.classList.add('disabled');
                }
            });
        }
    };
})();
