/**
 * aot-geo-ui.js
 * UI & Theme Management for AoTGeoDesign
 */

class AoTGeoUI {
    constructor(parent) {
        this.parent = parent;
        this._bindEvents();
    }

    _bindEvents() {
        window.addEventListener('aot:editor:state', (e) => {
             const detail = e.detail || {};
             const container = document.getElementById('draw-tools-container');
             if (!container) return;

             // 1. Reset all draw buttons
             container.querySelectorAll('.btn-white').forEach(b => b.classList.remove('active', 'text-primary'));

             // 2. Activate specific button if shape is active
             if (detail.activeShape) {
                 // Try to find button with matching icon or title logic, or better yet, identify by consistent method.
                 // In updateDrawControls, we didn't set IDs. We can match by click handler closure... wait.
                 // We need to re-render or identifying buttons. 
                 // Let's rely on the fact that we can fix updateDrawControls to add data-attributes, 
                 // OR simply search by unique property if possible. 
                 
                 // Ideally we should have added data-action to buttons. 
                 // Since we can't change the HTML structure easily without re-viewing updateDrawControls source,
                 // let's assume we will add data-action in updateDrawControl first.
                 
                 // Wait, I should add data-action to buttons in updateDrawControls first? 
                 // Or I can select by some other means?
                 // Let's modify updateDrawControls to add data-action first in a separate step? 
                 // No, I can do it in the same file if I am careful.
                 
                 // Actually, looking at the previous file content of aot-geo-ui.js:
                 // The buttons are created in `updateDrawControls`. 
                 // I should modify `updateDrawControls` to add `data-action` to the buttons.
                 
                 // BUT for this specific replacement, I am in _bindEvents.
                 // I will assume buttons have `data-action`.
                 const btn = container.querySelector(`button[data-action="${detail.activeShape}"]`);
                 if (btn) btn.classList.add('active', 'text-primary');
             }
        });
    }

    /**
     * Show Toast Notification
     * @param {string} message - Message body
     * @param {string} type - 'success', 'info', 'warning', 'error'
     * @param {string} title - Optional title
     */
    showToast(message, type = 'info', title = '') {
        if (typeof window.showToast !== 'undefined') {
            window.showToast(message, type);
            return;
        }

        // 0. Check Global Settings (injected in layout)
        const settings = window.AoTGlobalSettings || {};
        
        let shouldHide = false;
        if (type === 'success' && settings.hide_success) shouldHide = true;
        if (type === 'info' && settings.hide_info) shouldHide = true;
        
        // Quirk: Flash messages use 'hide_alert_warning' for both warning AND error
        if ((type === 'warning' || type === 'error') && settings.hide_warning) shouldHide = true;
        
        if (shouldHide) {
            // console.log(`[AoTGeoUI] Toast hidden by setting (${type}): ${message}`);
            return;
        }

        // 1. Show Toastr
        if (typeof toastr !== 'undefined') {
            toastr[type](message, title);
        } else {
            // console.warn("[AoTGeoUI] Toastr not loaded. Fallback log:", message);
            // Fallback for critical errors if toastr missing (should not happen in AoT)
            if (type === 'error') alert(message); 
        }
    }
    /**
     * Apply Global Theme Configuration
     * Generates CSS Variables for colors and tone & manner logic.
     */
    applyThemeConfig() {
        // [Fix] Ensure AOT_GEO_CONFIG exists to prevent crash
        if (!window.AOT_GEO_CONFIG) window.AOT_GEO_CONFIG = {};
        if (!window.AOT_GEO_CONFIG.theme_config) window.AOT_GEO_CONFIG.theme_config = {};
        
        const theme = window.AOT_GEO_CONFIG.theme_config;
        
        // console.log("[AoTGeoUI] Applying Theme Config:", theme);
        
        const root = document.documentElement;
        
        // Helper: Hex to RGB
        const autoHexToRgb = (hex) => {
             // Remove #
             hex = String(hex).replace('#', '');
             if (hex.length === 3) hex = hex.split('').map(c => c+c).join('');
             const r = parseInt(hex.substring(0,2), 16) || 0;
             const g = parseInt(hex.substring(2,4), 16) || 0;
             const b = parseInt(hex.substring(4,6), 16) || 0;
             return `${r}, ${g}, ${b}`;
        };
        
        // 1. Apply Main Colors & Sub Colors
        const applyColor = (key, cssVar, fallback) => {
            const hex = theme[key] || fallback;
            const rgb = autoHexToRgb(hex);
            
            // Main Color
            root.style.setProperty(cssVar, hex);
            
            // RGB for Opacity usage
            root.style.setProperty(`${cssVar}-rgb`, rgb);
            
            // Generated Sub-Colors (Tone & Manner)
            root.style.setProperty(`${cssVar}-bg`, `rgba(${rgb}, 0.1)`);
            root.style.setProperty(`${cssVar}-hover`, `rgba(${rgb}, 0.8)`);
            root.style.setProperty(`${cssVar}-sub`, `rgba(${rgb}, 0.2)`);
        };
        
        // Standard Tiers with Fallbacks
        applyColor('site', '--theme-site', '#DF5353');
        applyColor('zone', '--theme-zone', '#28a745');
        applyColor('facility', '--theme-facility', '#82898f');
        applyColor('equipment', '--theme-equipment', '#007bff');
        applyColor('device', '--theme-device', '#995aff');
        
        // Sub-types (Inputs/Outputs/Functions)
        applyColor('input', '--theme-input', '#995aff');
        applyColor('output', '--theme-output', '#995aff');
        applyColor('function', '--theme-function', '#995aff');
        
        // 2. Apply Panel Styles (RGBA)
        const panelHex = theme.panel_bg || '#ffffff';
        const panelRgb = autoHexToRgb(panelHex); 
        let opacity = 0.9; 
        
        if (theme.panel_opacity) {
            opacity = parseInt(theme.panel_opacity) / 100;
        }
        
        root.style.setProperty('--panel-bg-rgba', `rgba(${panelRgb}, ${opacity})`);
        root.style.setProperty('--panel-bg', panelHex);
        root.style.setProperty('--panel-opacity', opacity);
    }

    /**
     * [Fix] Mode-Aware Pane Interactivity (Pointer-Events Control)
     * Disables pointer events on HIGHER panes to allow selection of LOWER layers 
     * while maintaining the strict 1-5 visual stacking order.
     */
    updatePaneInteractivity(activeMode) {
        if (!this.parent.map) return;
        // console.log(`[AoTGeoUI] Updating Interactivity for Mode: ${activeMode}`);

        // Map Mode to its threshold Z-Index
        const modeZ = {
            'site': 350,
            'zone': 360,
            'facility': 400,
            'equipment': 450,
            'connection': 455,
            'device': 460,
            'aot_device': 460
        };

        const currentThreshold = modeZ[activeMode] || 0;
        const map = this.parent.map;

        // [New] All Panes to manage including standard Leaflet panes
        const panes = [
            { name: 'tilePane', z: 200 },    // Base (Always auto)
            { name: 'sitePane', z: 350 },
            { name: 'zonePane', z: 360 },
            { name: 'infraPane', z: 370 },
            { name: 'facilityPane', z: 400 },
            { name: 'overlayPane', z: 401 }, // Slightly above facility
            { name: 'equipmentPane', z: 450 },
            { name: 'connectionPane', z: 455 },
            { name: 'devicePane', z: 460 },
            { name: 'markerPane', z: 600 },
            { name: 'shadowPane', z: 500 },
            { name: 'labelPane', z: 650 },
            { name: 'tooltipPane', z: 650 },
            { name: 'popupPane', z: 700 }
        ];

        panes.forEach(p => {
            const paneEl = map.getPane(p.name);
            if (paneEl) {
                // Logic: Panes HIGHER than current mode must be transparent
                // Exception: tilePane (200) always auto
                if (p.name === 'tilePane') {
                    paneEl.style.pointerEvents = 'auto';
                } else if (p.z > currentThreshold) {
                    // console.log(`[PaneManager] ${p.name} -> none (Target: ${currentThreshold})`);
                    paneEl.style.pointerEvents = 'none';
                } else {
                    // console.log(`[PaneManager] ${p.name} -> auto (Target: ${currentThreshold})`);
                    paneEl.style.pointerEvents = 'auto';
                }
            }
        });
    }

    /**
     * Update/Render Dynamic Draw Tools on the right side of the map
     */
    updateDrawControls() {
        const container = document.getElementById('draw-tools-container');
        if (!container) return;
        container.innerHTML = '';

        // 1. Draw Group
        const drawGroup = document.createElement('div');
        drawGroup.className = 'tool-group shadow-sm mb-2';

        const drawTools = [];
        const addTool = (icon, title, action) => {
            drawTools.push({ icon, title, action });
        };

        if (this.parent.activeMode === 'site' || this.parent.activeMode === 'zone') {
            addTool('far fa-square', window._('Rectangle'), 'rectangle');
            addTool('far fa-circle', window._('Circle'), 'circle');
            addTool('fas fa-draw-polygon', window._('Polygon'), 'polygon');
        } else if (this.parent.activeMode === 'device' || ['facility', 'equipment', 'aot_device'].includes(this.parent.activeMode)) {
            addTool('fas fa-slash', window._('Line'), 'polyline');
            addTool('far fa-square', window._('Rectangle'), 'rectangle');
            addTool('far fa-circle', window._('Circle'), 'circle');
            addTool('fas fa-draw-polygon', window._('Polygon'), 'polygon');
            addTool('fas fa-map-marker-alt', window._('Marker'), 'marker');
            addTool('fas fa-font', window._('Label'), 'label'); 
        }

        drawTools.forEach(t => {
            const btn = document.createElement('button');
            btn.className = 'btn btn-white';
            btn.dataset.action = t.action; // [Fix] Identify button for UI Sync
            btn.title = t.title;
            btn.innerHTML = `<i class="${t.icon}"></i>`;
            
            btn.onclick = () => {
                // Toggle Logic
                if (window.AoTMapEditor.activeShape === t.action) {
                    // console.log(`[GeoDesign] Canceling Active Draw: ${t.action}`);
                    window.AoTMapEditor.stopAll();
                    btn.classList.remove('active', 'text-primary'); // Visual Feedback
                } else {
                     if (this.parent.activeMode === 'equipment' && t.action === 'polyline') {
                        this.parent.startDrawBranchPipe(); 
                    } else {
                        window.AoTMapEditor.startDraw(t.action);
                    }
                    // Visual Feedback (Simplified - ideally listen to state event, but immediate feedback is good)
                    // Clear others
                    container.querySelectorAll('.btn-white').forEach(b => b.classList.remove('active', 'text-primary'));
                    btn.classList.add('active', 'text-primary');
                }
            };
            drawGroup.appendChild(btn);
        });
        container.appendChild(drawGroup);

        // 2. Edit Group Container (Relative for positioning sub-menu)
        const editContainer = document.createElement('div');
        editContainer.className = 'position-relative'; // Bootstrap class for relative positioning
        editContainer.style.marginBottom = '0.5rem'; // Spacing
        
        const editGroup = document.createElement('div');
        editGroup.className = 'tool-group shadow-sm';
        
        const editTools = [
            { icon: 'fas fa-edit', title: window._('Edit Layers'), action: 'edit' },
            { icon: 'fas fa-trash-alt', title: window._('Delete Layers'), action: 'delete' }
        ];

        editTools.forEach(t => {
            const btn = document.createElement('button');
            btn.className = 'btn btn-white tool-btn-' + t.action; 
            btn.title = t.title;
            btn.innerHTML = `<i class="${t.icon}"></i>`;
            btn.onclick = () => {
                if (t.action === 'edit') window.AoTMapEditor.toggleEdit();
                if (t.action === 'delete') {
                    if (!window.AoTMapEditor.deleteEnabled && this.parent.layerStorage['label_aux']) {
                        const auxLayers = this.parent.layerStorage['label_aux'].getLayers();
                        auxLayers.forEach(l => {
                            const pType = l.feature?.properties?.parent_type;
                            if (pType === this.parent.activeMode) {
                                this.parent.layerStorage['label_aux'].removeLayer(l);
                                window.AoTMapEditor.featureGroup.addLayer(l);
                            }
                        });
                    }
                    
                    if (!window.AoTMapEditor.deleteEnabled && this.parent.activeMode === 'equipment' && this.parent.layerStorage['reference']) {
                         const refLayers = this.parent.layerStorage['reference'].getLayers();
                         refLayers.forEach(l => {
                             this.parent.layerStorage['reference'].removeLayer(l);
                             window.AoTMapEditor.featureGroup.addLayer(l);
                         });
                    }
                    window.AoTMapEditor.toggleDelete();
                }
            };
            editGroup.appendChild(btn);
        });
        
        editContainer.appendChild(editGroup);

        // 3. Sub-Action Group (Absolute Left)
        const actionGroup = document.createElement('div');
        actionGroup.className = 'tool-group shadow-sm';
        actionGroup.id = 'editor-actions';
        // Style: Absolute Position Left, Gray Background, Row Layout
        actionGroup.style.position = 'absolute';
        actionGroup.style.top = '0';
        actionGroup.style.right = '100%'; // Push to left of container
        actionGroup.style.marginRight = '10px'; // Gap
        actionGroup.style.backgroundColor = '#f0f0f0'; // Gray Background
        actionGroup.style.display = 'none'; // Hidden by default
        actionGroup.style.flexDirection = 'row'; // Horizontal buttons
        actionGroup.style.padding = '2px';
        actionGroup.style.whiteSpace = 'nowrap';
        
        editContainer.appendChild(actionGroup);
        container.appendChild(editContainer);
    }

    /**
     * Update Editor Action Buttons (Save/Cancel/Clear)
     */
    updateEditorButtons(state) {
        const editBtn = document.querySelector('.tool-btn-edit');
        const delBtn = document.querySelector('.tool-btn-delete');
        const actionGroup = document.getElementById('editor-actions');
        
        if (!actionGroup) return;

        if (editBtn) editBtn.classList.remove('text-primary');
        if (delBtn) delBtn.classList.remove('text-danger');

        if (!state.edit && !state.delete) {
            actionGroup.style.display = 'none';
            actionGroup.innerHTML = '';
            return;
        }

        // Dynamic Positioning
        let targetBtn = null;
        if (state.edit) targetBtn = editBtn;
        if (state.delete) targetBtn = delBtn;

        if (targetBtn) {
            // Calculate center alignment
            // Container is relative. editBtn is inside editGroup (child of container).
            // We need offset relative to container. 
            // offsetTop of btn is relative to editGroup. editGroup is at 0,0 of editContainer (mostly).
            const btnTop = targetBtn.offsetTop;
            const btnHeight = targetBtn.offsetHeight;
            const menuHeight = 24; // User requested 24px
            
            // Center the 24px menu against the button
            const topPos = btnTop + (btnHeight - menuHeight) / 2;
            
            actionGroup.style.top = `${topPos}px`;
            actionGroup.style.height = `${menuHeight}px`;
            actionGroup.style.alignItems = 'center';
            actionGroup.style.padding = '0 5px';
            actionGroup.style.borderRadius = '12px'; // Round feel
        }

        actionGroup.style.display = 'flex';
        actionGroup.innerHTML = '';

        if (state.edit) {
            if (editBtn) editBtn.classList.add('text-primary');
            this.renderActionButtons(actionGroup, 'edit');
        }

        if (state.delete) {
            if (delBtn) delBtn.classList.add('text-danger');
            this.renderActionButtons(actionGroup, 'delete');
        }
    }

    /**
     * Render Save/Cancel/Clear Buttons
     */
    renderActionButtons(container, mode) {
        // Common Style for 24px height
        const btnStyle = 'font-size: 0.8em; padding: 0 6px; min-width: auto; line-height: 22px; height: 100%; border: none;';

        // Save
        const saveBtn = document.createElement('button');
        saveBtn.className = 'btn btn-sm btn-link font-weight-bold';
        saveBtn.style.cssText = btnStyle + 'color: black;'; // Black
        saveBtn.innerHTML = window._('Save');
        saveBtn.onclick = () => window.AoTMapEditor.saveActions();
        container.appendChild(saveBtn);

        // Cancel
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn btn-sm btn-link';
        cancelBtn.style.cssText = btnStyle + 'color: #555;'; // Dark Gray
        cancelBtn.innerHTML = window._('Cancel');
        cancelBtn.onclick = () => window.AoTMapEditor.cancelActions();
        container.appendChild(cancelBtn);

        // Clear All (Delete Mode Only)
        if (mode === 'delete') {
            const clearBtn = document.createElement('button');
            clearBtn.className = 'btn btn-sm btn-link border-left ml-1 pl-2';
            clearBtn.style.cssText = btnStyle + 'color: black;'; // Black
            clearBtn.innerHTML = window._('Clear All');
            clearBtn.onclick = () => {
                if(this.parent.layerStorage['label_aux']) {
                    const auxLayers = this.parent.layerStorage['label_aux'].getLayers();
                    auxLayers.forEach(l => {
                        const pType = l.feature?.properties?.parent_type;
                        if (pType === this.parent.activeMode) {
                            window.AoTMapEditor.featureGroup.addLayer(l);
                            this.parent.layerStorage['label_aux'].removeLayer(l);
                        }
                    });
                }
                window.AoTMapEditor.markAllDeleted();
            };
            container.appendChild(clearBtn);
        }
    }

    _setLayerStyle(layer, isActive) {
        if (!layer || !layer.setStyle) return;

        const props = layer.feature?.properties || {};
        const type = props.aot_type;
        const subType = props.sub_type;
        
        // [Fix] Exempt Connections/Fittings from Theme Styling
        // They have specific colors assigned at creation (mT=Orange, bT=Yellow, etc)
        if (type === 'connection' || ['mT', 'mbT', 'bT', 'mE', 'bE', 'tee', 'elbow'].includes(subType)) {
            return;
        }

        // Helper to get Theme Color (Hex) - Bypasses Canvas var() issues
        const getThemeColor = (k, defaultHex) => {
            if (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config && window.AOT_GEO_CONFIG.theme_config[k]) {
                return window.AOT_GEO_CONFIG.theme_config[k];
            }
            return defaultHex;
        };

        // Default Colors (Theme Hex)
        let color = '#3388ff'; // Default Blue
        if (type === 'site') color = getThemeColor('site', '#DF5353'); 
        else if (type === 'zone') color = getThemeColor('zone', '#28a745'); 
        else if (type === 'facility') color = getThemeColor('facility', '#82898f');
        else if (type === 'equipment') color = getThemeColor('equipment', '#007bff');
        else if (type === 'aot_device') {
            const devType = props.device_type;
            const functionTypes = ['trigger', 'pid', 'conditional', 'custom', 'generic_function'];
            let savedColor = devType ? localStorage.getItem(`aot_config_color_${devType}`) : null;
            if (!savedColor && functionTypes.includes(devType)) {
                savedColor = localStorage.getItem('aot_config_color_function');
            }
            color = savedColor || getThemeColor('device', '#995aff'); 
        }
        else if (type === 'device') {
             let devType = props.device_type;
             // Fallback: Lookup from Markers if device_type missing
             if (!devType && this.parent.devices && props.device_id) {
                  const marker = this.parent.devices.findDeviceMarker(props.device_id);
                  if (marker && marker.feature && marker.feature.properties) {
                      devType = marker.feature.properties.device_type;
                  }
             }
             
             const functionTypes = ['trigger', 'pid', 'conditional', 'custom', 'generic_function'];
             let savedColor = devType ? localStorage.getItem(`aot_config_color_${devType}`) : null;
             if (!savedColor && functionTypes.includes(devType)) {
                 savedColor = localStorage.getItem('aot_config_color_function');
             }
             color = savedColor || '#007bff'; 
        } 
        
        const isMainPipe = (subType === 'pipe_main');
        const isPipe = (subType === 'pipe_branch' || isMainPipe);

        if (isActive) {
            if (type === 'reference') {
                layer.setStyle({
                    color: '#FFA500', weight: 5, dashArray: '4, 8', opacity: 1.0, fill: false
                });
            } else {
                let activeColor = '#ff7800';
                // [New] Drip Active Color
                if (props.is_drip) activeColor = '#333333'; // Dark Gray for active drip

                layer.setStyle({
                    color: activeColor, weight: isMainPipe ? 6 : 4, dashArray: null, fillOpacity: 0.6, opacity: 1.0
                });
            }
            if(layer.bringToFront) layer.bringToFront();
        } else {
            if (type === 'reference') {
                 layer.setStyle({
                    color: '#FFA500', weight: 4, dashArray: '4, 8', opacity: 1.0, fill: false
                });
            } else {
                const isActiveMode = (type === this.parent.activeMode);
                const isCoverage = (subType === 'sprinkler_coverage');
                const isDrip = props.is_drip; // [New]

                // [Standard] Active: 0.3 / Solid, Inactive: 0.1 / Dashed
                const fillOpacity = isCoverage ? 0.2 : (isActiveMode ? 0.3 : 0.1);
                
                // [Fix] Rules:
                // 1. Coverage: always dashed (3,3)
                // 2. Pipes (isPipe): always solid (null)
                // 3. Active Mode: always solid (null)
                // 4. Inactive Site/Zone/Facility: dashed (5,5)
                const dashArray = isCoverage ? '3, 3' : 
                                 ((isPipe || isActiveMode) ? null : '5, 5');

                // [New] Drip Override
                let finalColor = color;
                let finalWeight = isMainPipe ? 5 : (isCoverage ? 1 : 2.5);

                if (isDrip) {
                    finalColor = '#000000'; // Black
                    finalWeight = 4; // Thicker
                }

                layer.setStyle({
                    color: finalColor,
                    fillColor: finalColor,
                    weight: finalWeight,
                    opacity: isCoverage ? 0.8 : 1.0,
                    dashArray: dashArray,
                    fillOpacity: fillOpacity
                });
            }
        }
    }
    updateLayerStyles() {
        if (!this.parent.layerStorage) return;
        
        // Delegate to centralized _setLayerStyle for all layers in storage
        Object.keys(this.parent.layerStorage).forEach(key => {
            const group = this.parent.layerStorage[key];
            if (this.parent.map.hasLayer(group)) {
                 group.eachLayer(layer => {
                     this._setLayerStyle(layer, false);
                 });
            }
        });
        
        // Refresh styles for layers currently in the Editor
        // [Fix] Do NOT force active style (orange) for everything in editor group.
        // Only the specific activeLayer should be active.
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
             window.AoTMapEditor.featureGroup.eachLayer(layer => {
                  // Check if this is the currently active layer
                  const isActive = (this.parent.activeLayer && layer === this.parent.activeLayer);
                  this._setLayerStyle(layer, isActive);
             });
        }
        
        // And the Active Layer specifically (redundant safety)
        if (this.parent.activeLayer) {
             this._setLayerStyle(this.parent.activeLayer, true);
        }
    }
    toggleSiteList() {
        const popover = document.getElementById('site-list-popover');
        const listUl = document.getElementById('site-list-ul');
        const btn = document.getElementById('tool-site-list');
        
        if (!popover || !listUl || !btn) return;

        const isHidden = (popover.style.display === 'none');
        if (!isHidden) {
            popover.style.display = 'none';
            return;
        }

        // Show
        popover.style.display = 'block';
        popover.style.top = btn.offsetTop + 'px'; // Align with button
        listUl.innerHTML = '';

        const sites = [];
        const seen = new Set();
        
        const collect = (group) => {
            if (!group) return;
            group.eachLayer(l => {
                if (l.feature?.properties?.aot_type === 'site') {
                    const id = l.feature.properties.node_id;
                    if (!seen.has(id)) {
                        seen.add(id);
                        sites.push(l);
                    }
                }
            });
        };

        collect(this.parent.layerStorage['site']);
        if (window.AoTMapEditor?.featureGroup) collect(window.AoTMapEditor.featureGroup);

        if (sites.length === 0) {
            listUl.innerHTML = `<li class="list-group-item text-muted text-center py-2">${window._('No Sites Found')}</li>`;
        } else {
            // Sort by Name
            sites.sort((a, b) => {
                const nA = a.feature.properties.name || window._('Site');
                const nB = b.feature.properties.name || window._('Site');
                return nA.localeCompare(nB);
            });

            sites.forEach(l => {
                const name = l.feature.properties.name || window._('Unnamed Site');
                const li = document.createElement('li');
                li.className = 'list-group-item list-group-item-action py-2 px-3 cursor-pointer';
                li.style.cursor = 'pointer';
                li.innerText = name;
                li.onclick = () => {
                    this.parent.map.fitBounds(l.getBounds(), { padding: [50, 50] });
                    this.parent._setActiveLayer(l); // Optional: select it
                    popover.style.display = 'none';
                };
                listUl.appendChild(li);
            });
        }
    }
}
