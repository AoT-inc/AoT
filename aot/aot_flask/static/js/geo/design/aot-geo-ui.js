/**
 * aot-geo-ui.js
 * UI & Theme Management for AoTGeoDesign
 */

/**
 * 아직 장치가 배정되지 않은 담당 구역의 색 — 장치 종류 어느 것과도 겹치지 않는
 * 중립 회색이라야 "배정됨 / 미배정" 이 색으로 갈린다. 장치 팔레트
 * (`AoTGeoTheme`)에 넣지 않는 이유는 이것이 **장치 종류가 아니라 상태**여서다.
 */
const UNASSIGNED_AREA_COLOR = '#9e9e9e';

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

             // 2. Activate specific draw button if shape is active
             if (detail.activeShape) {
                 const btn = container.querySelector(`button[data-action="${detail.activeShape}"]`);
                 if (btn) btn.classList.add('active', 'text-primary');
             }

             // 3. Sync edit/delete button state (MapLibre fallback doesn't fire draw:editstart/stop)
             this.updateEditorButtons({ edit: !!detail.edit, delete: !!detail.delete });
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

        // 예전에는 여기서 theme_config 를 localStorage.aot_config_color_<type> 로
        // 미러링했다. 렌더 경로 절반이 localStorage 를 먼저 읽었기 때문인데, 미러는
        // theme[t] 가 있을 때만 덮어써서 설정에서 빠진 키(예: function)는 브라우저에
        // 남은 옛 값이 계속 이겼고, PC 마다 색이 달랐다. 이제 모든 렌더 경로가
        // AoTGeoTheme 로 theme_config 를 직접 읽으므로 미러가 필요 없다.
        // 남아 있는 옛 키는 여기서 지운다(설치본마다 1회, 조용히).
        try {
            ['site', 'zone', 'facility', 'equipment', 'device', 'input', 'output', 'function'].forEach((t) => {
                localStorage.removeItem('aot_config_color_' + t);
            });
        } catch (e) {}

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
        
        // 기본값은 AoTGeoTheme.DEFAULTS 한 벌뿐이다(위젯도 같은 값을 쓴다).
        const D = window.AoTGeoTheme.DEFAULTS;
        applyColor('site', '--theme-site', D.site);
        applyColor('zone', '--theme-zone', D.zone);
        applyColor('facility', '--theme-facility', D.facility);
        applyColor('equipment', '--theme-equipment', D.equipment);
        applyColor('device', '--theme-device', D.device);
        applyColor('plot', '--theme-plot', D.plot);

        // Sub-types (Inputs/Outputs/Functions) — 미설정이면 장치 공통색으로 수렴.
        window.AoTGeoTheme.DEVICE_KEYS.forEach((k) => {
            applyColor(k, `--theme-${k}`, theme.device || D.device);
        });
        
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
     * [MapLibre] Updated for MapLibre GL compatibility
     */
    updatePaneInteractivity(activeMode) {
        if (!this.parent.map) return;

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

        // [MapLibre] Check if this is a MapLibre map or Leaflet map
        const map = this.parent.map;
        const isMapLibre = map && map.addSource;

        if (isMapLibre) {
            // [MapLibre] Layer ordering is handled by layer order in style
            // For interactivity control, we rely on MapLibre's built-in handling
            // This may need custom implementation based on specific needs
            // console.log(`[AoTGeoUI] MapLibre detected - pane interactivity handled differently`);
            return;
        }

        // [Leaflet] Standard pane-based approach
        if (typeof map.getPane !== 'function') {
            console.warn('[AoTGeoUI] Map does not support getPane() - skipping pane interactivity');
            return;
        }

        // [Leaflet] All Panes to manage including standard Leaflet panes
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
                    paneEl.style.pointerEvents = 'none';
                } else {
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
        } else if (this.parent.activeMode === 'plot') {
            // 면적 있는 도형만. 식생 구획은 폴리곤이어야 하고(VP-1), 점·선은
            // 구획이 될 수 없다 — 서버도 같은 규칙으로 거부한다.
            addTool('far fa-square', window._('Rectangle'), 'rectangle');
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
                    // [Fix] Sprinkler deletion: move coverage circles to featureGroup so they can be selected
                    if (!window.AoTMapEditor.deleteEnabled && this.parent.activeMode === 'equipment' && this.parent.layerStorage['equipment']) {
                        const equipLayers = this.parent.layerStorage['equipment'].getLayers();
                        equipLayers.forEach(l => {
                            const st = l.feature?.properties?.sub_type;
                            if (st === 'sprinkler_coverage' || st === 'sprinkler') {
                                if (l.setStyle) l.setStyle({ interactive: true });
                                this.parent.layerStorage['equipment'].removeLayer(l);
                                window.AoTMapEditor.featureGroup.addLayer(l);
                            }
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

        // 숨겨 둔 레이어는 다시 켜지 않는다.
        //
        // 이 함수는 `updateLayerStyles()`/`_swapStorageLayers()` 를 통해 **모드를
        // 바꿀 때마다** 모든 레이어에 대해 불리고, 그 과정에서 GL 레이어의
        // visibility 를 'visible' 로 되돌린다. 여기서 숨김을 다시 적용하지 않으면
        // 사용자가 감춘 도형이 다른 모드로 갔다 오는 것만으로 되살아난다.
        //
        // 아래의 connection·plot early-return 보다 **먼저** 판단해야 한다 —
        // 그 두 종류는 여기서 스타일을 안 칠하고 빠져나가므로, 뒤에 두면 장비
        // 연결부와 식생이 숨김에서 빠진다.
        if (this.parent && this.parent._applyVisibilityToLayer) {
            this.parent._applyVisibilityToLayer(layer);
            if (this.parent._isLayerHidden && this.parent._isLayerHidden(layer)) return;
        }

        // [Fix] Exempt Connections/Fittings from Theme Styling
        // They have specific colors assigned at creation (mT=Orange, bT=Yellow, etc)
        if (type === 'connection' || ['mT', 'mbT', 'bT', 'mE', 'bE', 'tee', 'elbow'].includes(subType)) {
            return;
        }

        // 색은 theme_config 하나에서만 나온다(AoTGeoTheme). 예전에는 여기서
        // localStorage.aot_config_color_<devType> 를 먼저 읽어, 브라우저에 남은
        // 옛 값이 저장된 테마를 이기곤 했다.
        const T = window.AoTGeoTheme;

        // Default Colors (Theme Hex)
        let color = '#3388ff'; // Default Blue
        if (type === 'site') color = T.color('site');
        else if (type === 'zone') color = T.color('zone');
        // 식생 구획의 스타일 정본은 plot 모듈이다 — 개별 색
        // (GeoPlot.color)과 모드별 강조(활성 모드에서 진하게)를 함께
        // 봐야 하는데 여기서는 그 둘을 알 수 없다.
        //
        // 위임하지 않고 여기서 색만 칠하면 **모드 전환 때마다 강조가 풀린다** —
        // updateLayerStyles() 가 모든 레이어를 훑으며 이 함수를 부르기 때문에,
        // 식생 모드에 처음 들어온 직후 강조가 사라지고 "나갔다 다시 들어와야
        // 강조된다" 는 증상이 된다.
        else if (type === 'plot') {
            const veg = this.parent && this.parent.plot;
            const uuid = props.plot_uuid;
            if (veg && uuid) {
                veg._styleLayer(layer, veg.data.get(uuid));
                return;
            }
            color = T.color('plot');
        }
        else if (type === 'facility') color = T.color('facility');
        else if (type === 'equipment') color = T.color('equipment');
        else if (type === 'aot_device' || type === 'device') {
             let devType = props.device_type;
             // Fallback: Lookup from Markers if device_type missing
             if (!devType && this.parent.devices && props.device_id) {
                  const marker = this.parent.devices.findDeviceMarker(props.device_id);
                  if (marker && marker.feature && marker.feature.properties) {
                      devType = marker.feature.properties.device_type;
                  }
             }
             // **배정된 장치가 없으면 중립색**으로 둔다.
             //
             // `deviceColor(undefined)` 는 복합장치(device_unit) 색으로 떨어지는데,
             // 그 색은 함수(function) 색과도 같다. 그대로 쓰면 "아직 장치가 없는
             // 구역" 과 "함수가 배정된 구역" 이 화면에서 똑같아 보여서, 색으로
             // 배정 상태를 읽을 수 없다 — 색을 장치 종류에 맞추는 목적 자체가
             // 사라진다. 미배정은 회색으로 두어 한눈에 갈리게 한다
             // (패널의 "장치 미연결" 목록과 같은 개념).
             const isAssigned = !!(devType || props.device_id);
             color = isAssigned ? T.deviceColor(devType) : UNASSIGNED_AREA_COLOR;
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
                    color: activeColor, weight: isMainPipe ? 4 : 2, dashArray: null, fillOpacity: 0.6, opacity: 1.0
                });
            }
            if(layer.bringToFront) layer.bringToFront();
        } else {
            if (type === 'reference') {
                 layer.setStyle({
                    color: '#FFA500', weight: 4, dashArray: [4, 8], opacity: 1.0, fill: false
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
                const dashArray = isCoverage ? [3, 3] :
                                 ((isPipe || isActiveMode) ? null : [5, 5]);

                // [New] Drip Override
                let finalColor = color;
                // 지금 모드의 도형은 **테두리를 굵게** 해서 그 종류의 색이
                // 드러나게 한다. 예전에는 채움 투명도(0.1↔0.3)만 달라서, 옅은
                // 색이나 위성사진 위에서는 어느 것이 지금 만지는 종류인지
                // 구분되지 않았다 — 색은 같은데 두께가 같으니 테두리가 정보를
                // 주지 못했다. 배관·커버리지는 원래 두께가 의미를 가지므로
                // (주배관 4 / 커버리지 1) 그대로 둔다.
                let finalWeight = isMainPipe ? 4
                                : (isCoverage ? 1 : (isActiveMode ? 4 : 2));

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
            if (popover._outsideClickHandler) {
                document.removeEventListener('click', popover._outsideClickHandler, true);
                popover._outsideClickHandler = null;
            }
            return;
        }

        popover.style.display = 'block';
        popover.style.top = btn.offsetTop + 'px';
        this._registerOutsideClick(popover, 'tool-site-list');
        listUl.innerHTML = '';

        const sites = [];
        const seen = new Set();
        const diag = { scanned: 0, byType: {}, sources: [] };

        const collect = (group, label) => {
            if (!group) { diag.sources.push(label + ':null'); return; }
            if (typeof group.eachLayer !== 'function') {
                diag.sources.push(label + ':no-eachLayer');
                return;
            }
            let count = 0;
            try {
                group.eachLayer(l => {
                    count++;
                    diag.scanned++;
                    try {
                        const t = l?.feature?.properties?.aot_type || '(none)';
                        diag.byType[t] = (diag.byType[t] || 0) + 1;
                        if (t === 'site') {
                            const id = l.feature.properties.node_id || l.feature.properties.db_id;
                            const key = id || JSON.stringify(l.feature.properties.name);
                            if (!seen.has(key)) {
                                seen.add(key);
                                sites.push(l);
                            }
                        }
                    } catch (e) {}
                });
            } catch (e) {}
            diag.sources.push(label + ':' + count);
        };

        // Scan every possible location — layers move between storage and featureGroup
        // depending on current mode and async timing
        const storage = this.parent.layerStorage || {};
        Object.entries(storage).forEach(([k, g]) => collect(g, 'storage.' + k));
        const ed = window.AoTMapEditor;
        diag.editorState = {
            hasEditor: !!ed,
            hasFG: !!(ed && ed.featureGroup),
            fgType: ed && ed.featureGroup ? typeof ed.featureGroup : 'n/a',
            fgKeys: ed && ed.featureGroup ? Object.keys(ed.featureGroup).slice(0, 8) : null,
            fgLayersLen: ed && ed.featureGroup && Array.isArray(ed.featureGroup.layers) ? ed.featureGroup.layers.length : 'n/a',
            drawMgr: !!(ed && ed.drawManager),
            currentType: ed ? ed.currentType : null
        };
        if (ed && ed.featureGroup) {
            collect(ed.featureGroup, 'featureGroup');
        } else {
            diag.sources.push('featureGroup:MISSING');
        }

        // Also probe MapLibre Draw source directly (sites may live there if drawn this session)
        try {
            const dm = ed && ed.drawManager;
            if (dm && typeof dm.getAll === 'function') {
                const fc = dm.getAll();
                const feats = (fc && fc.features) || [];
                diag.drawManagerFeatures = feats.length;
                feats.forEach(f => {
                    const t = f?.properties?.aot_type || '(none)';
                    diag.byType['DM:' + t] = (diag.byType['DM:' + t] || 0) + 1;
                    if (t === 'site') {
                        const id = f.properties.node_id || f.properties.db_id;
                        const key = id || JSON.stringify(f.properties.name);
                        if (!seen.has(key)) {
                            seen.add(key);
                            sites.push({ feature: f, _fromDrawManager: true });
                        }
                    }
                });
            }
        } catch (e) { diag.drawManagerError = e.message; }

        // Probe MapLibre native sources for any feature with name/site-ish props.
        // Sites may have been rendered directly via map.addSource without going
        // through AoTGeoLayerGroup or AoTMapEditor.
        try {
            const ml = (this.parent.map && this.parent.map._originalMap) || this.parent.map;
            if (ml && typeof ml.getStyle === 'function') {
                const style = ml.getStyle();
                const sources = style && style.sources ? style.sources : {};
                diag.mlSourceCount = Object.keys(sources).length;
                diag.mlSourcesWithSite = [];
                Object.keys(sources).forEach(srcName => {
                    const src = sources[srcName];
                    let feats = [];
                    if (src.type === 'geojson' && src.data && src.data.features) {
                        feats = src.data.features;
                    }
                    feats.forEach(f => {
                        const props = f && f.properties ? f.properties : {};
                        const t = props.aot_type;
                        if (t === 'site' || (props.sub_type === 'site') ||
                            (typeof props.name === 'string' && /site|대지/i.test(props.name))) {
                            diag.mlSourcesWithSite.push(srcName + ':' + (props.name || props.node_id || '?'));
                            const key = props.node_id || props.db_id || JSON.stringify(props.name);
                            if (!seen.has(key)) {
                                seen.add(key);
                                sites.push({
                                    feature: f,
                                    _fromMapLibre: true,
                                    getBounds: null
                                });
                            }
                        }
                    });
                });
            }
        } catch (e) { diag.mlError = e.message; }

        // Probe AoTMapEditor.layers (the v2 internal Map of layer IDs)
        try {
            const ed2 = window.AoTMapEditor;
            if (ed2 && ed2.layers && typeof ed2.layers.forEach === 'function') {
                let cnt = 0;
                ed2.layers.forEach((layer, id) => {
                    cnt++;
                    const t = layer?.feature?.properties?.aot_type;
                    diag.byType['EDLY:' + (t || '(none)')] = (diag.byType['EDLY:' + (t || '(none)')] || 0) + 1;
                    if (t === 'site') {
                        const props = layer.feature.properties;
                        const key = props.node_id || props.db_id || JSON.stringify(props.name);
                        if (!seen.has(key)) {
                            seen.add(key);
                            sites.push(layer);
                        }
                    }
                });
                diag.editorLayersCount = cnt;
            }
        } catch (e) { diag.edLyError = e.message; }

        console.log('[SiteList] Found sites:', sites.length,
            '| activeMode:', this.parent.activeMode,
            '| sources:', diag.sources.join(', '),
            '| byType:', JSON.stringify(diag.byType),
            '| editor:', JSON.stringify(diag.editorState),
            '| dmFeatures:', diag.drawManagerFeatures ?? 'n/a',
            '| mlSources:', diag.mlSourceCount ?? 'n/a',
            '| mlWithSite:', JSON.stringify(diag.mlSourcesWithSite || []),
            '| edLayersCnt:', diag.editorLayersCount ?? 'n/a',
            '| errs:', diag.mlError || diag.edLyError || diag.drawManagerError || 'none');

        if (sites.length === 0) {
            listUl.innerHTML = `<li class="list-group-item text-muted text-center py-2">${window._('No Sites Found')}</li>`;
        } else {
            sites.sort((a, b) => {
                const nA = a.feature.properties.name || '';
                const nB = b.feature.properties.name || '';
                return nA.localeCompare(nB);
            });

            sites.forEach(l => {
                const name = l.feature.properties.name || window._('Unnamed Site');
                const li = document.createElement('li');
                li.className = 'list-group-item list-group-item-action py-2 px-3';
                li.style.cursor = 'pointer';
                li.innerText = name;
                li.onclick = () => {
                    popover.style.display = 'none';
                    try {
                        const geom = l.feature && l.feature.geometry;
                        if (geom && window.turf) {
                            const bbox = window.turf.bbox(l.feature);
                            this.parent.map.fitBounds(
                                [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
                                { padding: 60, maxZoom: 18 }
                            );
                        } else if (l.getBounds) {
                            const b = l.getBounds();
                            if (b && b.isValid && b.isValid()) {
                                const sw = b.getSouthWest(), ne = b.getNorthEast();
                                this.parent.map.fitBounds(
                                    [[sw.lng, sw.lat], [ne.lng, ne.lat]], { padding: 60, maxZoom: 18 }
                                );
                            }
                        }
                    } catch (e) {}
                    try { this.parent._setActiveLayer(l); } catch (e) {}
                };
                listUl.appendChild(li);
            });
        }
    }
}

// Initialize layer panel container (the tool-layers HTML button already exists, so create only the panel)
AoTGeoUI.prototype.initLegacyLayerButtons = function() {
    // Append to geo-design-wrapper (not geo-map which has overflow:hidden from MapLibre)
    const container = document.getElementById('geo-design-wrapper') || document.getElementById('geo-map');
    if (!container) return;

    // Clean up previous duplicate buttons
    ['base-map-btn', 'layers-btn', 'aot-legacy-layer-btns'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.remove();
    });

    // Create the panel if it does not exist
    if (!document.getElementById('aot-legacy-layer-panel')) {
        const layerPanel = document.createElement('div');
        layerPanel.id = 'aot-legacy-layer-panel';
        layerPanel.className = 'aot-legacy-layer-panel';
        // Position beside the tool-layers button: same top as button (10px), to its left (right:45px)
        layerPanel.style.cssText = 'display:none;position:absolute;top:10px;right:45px;left:auto;background:white;padding:10px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.25);z-index:var(--aot-z-fixed-panel);max-height:300px;overflow-y:auto;min-width:200px;';
        container.appendChild(layerPanel);
    }


    // Auto-restore last active layer from localStorage
    const savedId = localStorage.getItem('aot_active_base_id');
    const savedType = localStorage.getItem('aot_active_base_type');
    const savedVectorUrl = localStorage.getItem('aot_active_vector_style');
    if (savedId || savedVectorUrl) {
        const geoLayers = window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.layers;
        if (geoLayers && geoLayers.length) {
            const self = this;
            // Snapshot the current style URL so tryRestore can detect if the user (or another
            // call) has already switched channels before the 300ms delay fires.
            const initialStyleUrl = self.parent._activeVectorStyleUrl;
            const tryRestore = () => {
                const mlMap = self.parent?.map?._originalMap || self.parent?.map;
                if (!mlMap) return;
                // Skip if the style has already changed since we scheduled this — means
                // _restoreLayerState already ran, or the user manually switched channels.
                if (self.parent._activeVectorStyleUrl !== initialStyleUrl) return;
                if (savedType === 'raster' && savedId) {
                    const savedLayer = geoLayers.find(l => l.id === savedId);
                    if (savedLayer) {
                        self._restoreLayerState(savedLayer, 'raster');
                    }
                } else if ((savedType === 'vector' || savedType === 'vector_channel') && savedId) {
                    const savedLayer = geoLayers.find(l => l.id === savedId);
                    if (savedLayer && savedLayer.url && savedLayer.url !== self.parent._activeVectorStyleUrl) {
                        self._restoreLayerState(savedLayer, 'vector');
                    }
                }
            };
            const mlMap = self.parent?.map?._originalMap || self.parent?.map;
            if (mlMap) {
                if (mlMap.isStyleLoaded()) setTimeout(tryRestore, 300);
                else mlMap.once('load', () => setTimeout(tryRestore, 300));
            }
        }
    }
};

// Restore a saved layer state without requiring the panel to be open.
// Called on page load by initLegacyLayerButtons to re-activate the last used layer.
AoTGeoUI.prototype._restoreLayerState = function(layer, type) {
    const mlMap = this.parent?.map?._originalMap || this.parent?.map;
    if (!mlMap || !layer) return;

    const baseStyleIds = (this.parent && this.parent._baseStyleLayerIds) || [];

    const _hideVectorBase = () => {
        baseStyleIds.forEach(id => {
            try { mlMap.setLayoutProperty(id, 'visibility', 'none'); } catch(e) {}
        });
    };

    if (type === 'raster') {
        let url = (layer.url || '');
        url = url.replace(/\{r\}/g, '');
        const tiles = url.includes('{s}')
            ? ['a', 'b', 'c'].map(s => url.replace(/\{s\}/g, s))
            : (layer.type === 'wms'
                ? [`/api/geo/proxy/wms/${encodeURIComponent(layer.id)}?BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256`]
                : [url]);

        try {
            if (!mlMap.getSource(layer.id)) {
                mlMap.addSource(layer.id, { type: 'raster', tiles: tiles, tileSize: 256 });
            }
            const lyId = layer.id + '_layer';
            const allLayers = (mlMap.getStyle() || {}).layers || [];
            const firstAot = allLayers.find(sl => !baseStyleIds.includes(sl.id));
            const beforeId = firstAot ? firstAot.id : (allLayers.length > 0 ? allLayers[0].id : undefined);
            if (!mlMap.getLayer(lyId)) {
                mlMap.addLayer({ id: lyId, type: 'raster', source: layer.id, layout: { visibility: 'visible' } }, beforeId);
            } else {
                mlMap.setLayoutProperty(lyId, 'visibility', 'visible');
            }
            _hideVectorBase();
            this.parent._activeRasterBaseId = layer.id;
        } catch(e) { console.warn('[LayerPanel] restoreLayerState raster error:', e.message); }

    } else if (type === 'vector' && layer.url) {
        const self = this;
        const FALLBACK = 'https://demotiles.maplibre.org/style.json';
        const center = mlMap.getCenter();
        const zoom = mlMap.getZoom();

        // Snapshot current user layers (AoT features) before style switch
        const curStyle = mlMap.getStyle() || {};
        const curSources = curStyle.sources || {};
        const curLayers = curStyle.layers || [];
        const userLayers = curLayers.filter(sl => !baseStyleIds.includes(sl.id));
        const userSourceIds = new Set(userLayers.map(sl => sl.source).filter(Boolean));
        const userSources = {};
        userSourceIds.forEach(sid => { if (curSources[sid]) userSources[sid] = curSources[sid]; });

        // Register BEFORE setStyle to avoid missing a cached-style synchronous fire.
        let _handled = false;
        let _restoreFallback = null;
        const _onLoad = () => {
            if (_handled) return;
            _handled = true;
            clearTimeout(_restoreFallback);
            // Stop any ongoing camera animation before restoring position.
            try { mlMap.stop(); } catch(e) {}
            mlMap.jumpTo({ center, zoom });
            self.parent._baseStyleLayerIds = (mlMap.getStyle().layers || []).map(sl => sl.id);
            self.parent._activeVectorStyleUrl = layer.url;
            self.parent._activeRasterBaseId = null;
            Object.entries(userSources).forEach(([sid, def]) => {
                try { if (!mlMap.getSource(sid)) mlMap.addSource(sid, def); } catch(e) {}
            });
            userLayers.forEach(sl => {
                try { if (!mlMap.getLayer(sl.id)) mlMap.addLayer(sl); } catch(e) {}
            });
        };
        mlMap.once('style.load', _onLoad);
        // Use a timeout fallback — idle can fire from a prior render cycle and run _onLoad
        // before the new style is ready, capturing wrong layer IDs as _baseStyleLayerIds.
        _restoreFallback = setTimeout(() => {
            if (!_handled && mlMap.isStyleLoaded()) _onLoad();
        }, 3000);
        try { mlMap.setStyle(layer.url, { diff: false }); } catch(e) {
            clearTimeout(_restoreFallback);
            mlMap.off('style.load', _onLoad);
            return;
        }
        // Do NOT add a catch-all once('error') — tile/glyph 404s are normal and
        // must not switch to the demotiles fallback (which shows a bare world map).
    }
};

// Base Map switching
AoTGeoUI.prototype._cycleBaseMap = function() {
    if (!this.parent?.map) return;
    this.showToast((window._ ? window._('Vector mode: style switching supported') : 'Vector mode: style switching supported'), 'info');
};

// Shared helper: register outside-click listener that closes a panel.
// Removes itself once the panel is hidden.
AoTGeoUI.prototype._registerOutsideClick = function(panel, toggleBtnId) {
    if (panel._outsideClickHandler) {
        document.removeEventListener('click', panel._outsideClickHandler, true);
    }
    const handler = (e) => {
        const toggleBtn = toggleBtnId ? document.getElementById(toggleBtnId) : null;
        if (panel.contains(e.target) || (toggleBtn && toggleBtn.contains(e.target))) return;
        panel.style.display = 'none';
        document.removeEventListener('click', handler, true);
        panel._outsideClickHandler = null;
    };
    panel._outsideClickHandler = handler;
    // Defer so the click that opened the panel doesn't immediately close it
    setTimeout(() => document.addEventListener('click', handler, true), 0);
};

// Toggle layer panel
AoTGeoUI.prototype._toggleLayerPanel = function() {
    const panel = document.getElementById('aot-legacy-layer-panel');
    if (!panel) return;

    const isHidden = panel.style.display === 'none';
    panel.style.display = isHidden ? 'block' : 'none';

    if (!isHidden) {
        // Closing — remove any pending outside-click listener
        if (panel._outsideClickHandler) {
            document.removeEventListener('click', panel._outsideClickHandler, true);
            panel._outsideClickHandler = null;
        }
        return;
    }

    // Opening — register outside-click listener
    this._registerOutsideClick(panel, 'tool-layers');

    const geoLayers = window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.layers;
    if (!geoLayers || geoLayers.length === 0) {
        panel.innerHTML = '<div style="padding:10px;color:#666;">' + (window._ ? window._('No active layers') : 'No active layers') + '</div>';
        return;
    }

    const self = this;
    const mlMap = this.parent?.map?._originalMap || this.parent?.map;

    // -- Helpers ----------------------------------------------------------

    // IDs of all layers that belong to the CURRENT vector style.
    // Read dynamically so that after a setStyle() channel switch the new style's
    // IDs are used, preventing old channel layers from being mistaken as user layers.
    const _getBaseStyleIds = () => (self.parent && self.parent._baseStyleLayerIds) || [];

    // The raster layer ID for a GeoLayer entry (unique_id + '_layer').
    const _rasterLayerId = (id) => {
        try { return mlMap && mlMap.getLayer(id + '_layer') ? id + '_layer' : null; } catch(e) { return null; }
    };

    // Is a GeoLayer currently visible on the map?
    const _isVisible = (l) => {
        const lid = _rasterLayerId(l.id);
        if (!lid) return false;
        try { return mlMap.getLayoutProperty(lid, 'visibility') !== 'none'; } catch(e) { return true; }
    };

    // Convert a GeoLayer entry to MapLibre-compatible tile URL array.
    // WMS → server-side proxy (handles CORS + injects LAYERS/KEY).
    // XYZ → strip Leaflet {r}, expand {s} subdomains.
    const _toMapLibreTiles = (l) => {
        if (l.type === 'wms') {
            return [`/api/geo/proxy/wms/${encodeURIComponent(l.id)}?BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256`];
        }
        let url = (l.url || '').replace(/\{r\}/g, '');
        if (url.includes('{s}')) {
            return ['a', 'b', 'c'].map(s => url.replace(/\{s\}/g, s));
        }
        return [url];
    };

    // Parse the 4 corner coordinates of an `image` overlay layer (drone/aerial
    // photo). Returns null when missing/invalid so callers can bail out.
    const _imageCoords = (l) => {
        var coords = (l.options || {}).coordinates;
        if (typeof coords === 'string') {
            try { coords = JSON.parse(coords); } catch (e) { coords = null; }
        }
        return (coords && coords.length === 4) ? coords : null;
    };

    // Is this image overlay in tiled (XYZ pyramid) mode? Large images are tiled
    // server-side and rendered as a raster tile source, not a single image.
    const _isTiled = (l) => {
        const o = l.options || {};
        return l.type === 'image' && o.render_mode === 'tiled' && !!o.tile_url;
    };

    // Ensure a MapLibre source exists for the given GeoLayer. Aerial/drone photo
    // overlays (type 'image') are georeferenced `image` sources defined by 4
    // corner coordinates — NOT a tile pyramid; tiling the single image would
    // wallpaper it across the map. Large images that were tiled server-side, and
    // all other overlays, are raster tile sources.
    const _ensureSource = (l) => {
        if (mlMap.getSource(l.id)) return;
        if (_isTiled(l)) {
            const o = l.options || {};
            const spec = { type: 'raster', tiles: [o.tile_url], tileSize: 256 };
            const mn = parseInt(o.minzoom, 10); if (!isNaN(mn)) spec.minzoom = mn;
            const mx = parseInt(o.maxzoom, 10); if (!isNaN(mx)) spec.maxzoom = mx;
            mlMap.addSource(l.id, spec);
            return;
        }
        if (l.type === 'image') {
            const coords = _imageCoords(l);
            const imgUrl = (l.options || {}).image_url || l.url;
            if (!imgUrl || !coords) return;
            mlMap.addSource(l.id, { type: 'image', url: imgUrl, coordinates: coords });
            return;
        }
        mlMap.addSource(l.id, { type: 'raster', tiles: _toMapLibreTiles(l), tileSize: 256 });
    };

    // Hide all current vector-style layers so a raster base can be the sole visual.
    // AoT feature layers (added after style load) are NOT in _getBaseStyleIds() → stay visible.
    const _hideVectorBase = () => {
        _getBaseStyleIds().forEach(id => {
            try { mlMap.setLayoutProperty(id, 'visibility', 'none'); } catch(e) {}
        });
    };

    // Restore all current vector-style layers.
    const _showVectorBase = () => {
        _getBaseStyleIds().forEach(id => {
            try { mlMap.setLayoutProperty(id, 'visibility', 'visible'); } catch(e) {}
        });
    };

    // Deactivate whichever raster base is currently on, if any.
    const _deactivateRasterBase = () => {
        const prev = self.parent && self.parent._activeRasterBaseId;
        if (prev) {
            try { mlMap.setLayoutProperty(prev + '_layer', 'visibility', 'none'); } catch(e) {}
            self.parent._activeRasterBaseId = null;
        }
    };

    // Activate a raster base: hide vector style, add raster layer just below AoT features.
    const _activateRasterBase = (l) => {
        if (!mlMap || (!l.url && l.type !== 'wms')) return;
        try {
            _ensureSource(l);
            const lyId = l.id + '_layer';
            // Insert point: right before the first layer NOT in the original style
            // (i.e. the first AoT feature layer). This keeps AoT features above the raster.
            const allLayers = (mlMap.getStyle() || {}).layers || [];
            const firstAot = allLayers.find(sl => !_getBaseStyleIds().includes(sl.id));
            // When no AoT feature layers exist yet, insert at bottom (index 0) not top (undefined).
            const beforeId = firstAot ? firstAot.id : (allLayers.length > 0 ? allLayers[0].id : undefined);

            if (!mlMap.getLayer(lyId)) {
                mlMap.addLayer({ id: lyId, type: 'raster', source: l.id,
                    layout: { visibility: 'visible' } }, beforeId);
            } else {
                mlMap.setLayoutProperty(lyId, 'visibility', 'visible');
                if (beforeId) { try { mlMap.moveLayer(lyId, beforeId); } catch(e) {} }
            }
            _hideVectorBase();
            self.parent._activeRasterBaseId = l.id;
            try {
                localStorage.setItem('aot_active_base_id', l.id);
                localStorage.setItem('aot_active_base_type', 'raster');
            } catch(e) {}
        } catch(e) { console.warn('[LayerPanel] activateRasterBase error:', e.message); }
    };

    // Restore vector base (used when the "vector" radio or deactivating raster).
    const _restoreVectorBase = () => {
        _deactivateRasterBase();
        _showVectorBase();
        try {
            localStorage.setItem('aot_active_base_type', 'vector_default');
            localStorage.removeItem('aot_active_base_id');
        } catch(e) {}
    };

    // Add / show an overlay layer (renders on top of everything, no viewport conflict).
    // Image overlays render via a `type: 'raster'` MapLibre layer on top of the
    // georeferenced `image` source created in _ensureSource (same as tile rasters).
    const _addOverlay = (l) => {
        if (!mlMap || (!l.url && l.type !== 'wms' && !_isTiled(l))) return;
        if (l.type === 'image' && !_isTiled(l) && !_imageCoords(l)) return;
        try {
            _ensureSource(l);
            const lyId = l.id + '_layer';
            if (!mlMap.getLayer(lyId)) {
                const layerDef = { id: lyId, type: 'raster', source: l.id,
                    layout: { visibility: 'visible' } };
                if (l.type === 'image') {
                    let op = parseFloat((l.options || {}).opacity);
                    if (isNaN(op)) op = 0.85;
                    layerDef.paint = { 'raster-opacity': op, 'raster-fade-duration': 0 };
                }
                mlMap.addLayer(layerDef);
            } else {
                mlMap.setLayoutProperty(lyId, 'visibility', 'visible');
            }
        } catch(e) { console.warn('[LayerPanel] addOverlay error:', e.message); }
    };

    const _hideOverlay = (l) => {
        const lid = _rasterLayerId(l.id);
        if (lid) { try { mlMap.setLayoutProperty(lid, 'visibility', 'none'); } catch(e) {} }
    };

    // Switch the MapLibre base style (vector-type base layers).
    // Snapshots user-added layers before setStyle() and re-adds them after load
    // so drawn AoT features are preserved across vector channel switches.
    const _switchVectorBase = (l) => {
        if (!mlMap || !l.url) return;
        _deactivateRasterBase();
        const center = mlMap.getCenter();
        const zoom = mlMap.getZoom();
        const FALLBACK = 'https://demotiles.maplibre.org/style.json';

        // Snapshot all user-added layers/sources (not part of the base vector style).
        const baseIdsNow = _getBaseStyleIds();
        const curStyle = mlMap.getStyle() || {};
        const curSources = curStyle.sources || {};
        const curLayers = curStyle.layers || [];
        const userLayers = curLayers.filter(sl => !baseIdsNow.includes(sl.id));
        const userSourceIds = new Set(userLayers.map(sl => sl.source).filter(Boolean));
        const userSources = {};
        userSourceIds.forEach(sid => { if (curSources[sid]) userSources[sid] = curSources[sid]; });

        // IMPORTANT: Register style.load listener BEFORE calling setStyle.
        // If the style URL is browser-cached, MapLibre may fire style.load synchronously
        // during setStyle(), causing a listener registered afterward to miss the event.
        let _styleLoadHandled = false;
        let _fallbackTimer = null;
        const _onStyleLoad = () => {
            if (_styleLoadHandled) return;
            _styleLoadHandled = true;
            clearTimeout(_fallbackTimer);
            // Stop any ongoing camera animation (e.g. the style's default center/zoom flyTo
            // that MapLibre starts when applying a new style) before restoring our camera.
            try { mlMap.stop(); } catch(e) {}
            mlMap.jumpTo({ center, zoom });
            // Update base style snapshot and active URL for subsequent panel opens.
            const newBaseIds = (mlMap.getStyle().layers || []).map(sl => sl.id);
            self.parent._baseStyleLayerIds = newBaseIds;
            self.parent._activeVectorStyleUrl = l.url;
            self.parent._activeRasterBaseId = null;
            try {
                localStorage.setItem('aot_active_base_id', l.id);
                localStorage.setItem('aot_active_base_type', 'vector_channel');
                localStorage.setItem('aot_active_vector_style', l.url);
                localStorage.removeItem('aot_active_raster_base');
            } catch(e) {}
            // Re-add user sources then layers in original order.
            Object.entries(userSources).forEach(([sid, def]) => {
                try { if (!mlMap.getSource(sid)) mlMap.addSource(sid, def); } catch(e) {}
            });
            userLayers.forEach(sl => {
                try { if (!mlMap.getLayer(sl.id)) mlMap.addLayer(sl); } catch(e) {}
            });
        };
        mlMap.once('style.load', _onStyleLoad);
        // Fallback: idle can fire from a prior render cycle before the new style loads,
        // so use a timeout instead to avoid running _onStyleLoad with stale style state.
        _fallbackTimer = setTimeout(() => {
            if (!_styleLoadHandled && mlMap.isStyleLoaded()) _onStyleLoad();
        }, 3000);

        try { mlMap.setStyle(l.url, { diff: false }); } catch(e) {
            clearTimeout(_fallbackTimer);
            mlMap.off('style.load', _onStyleLoad);
            self.showToast((window._ ? window._('Failed to switch map style: ') : 'Failed to switch map style: ') + (e.message || ''), 'error'); return;
        }
        // NOTE: Do NOT add a catch-all once('error') here.
        // Individual tile/glyph 404s are normal during rendering and must not trigger
        // a style fallback — doing so would load demotiles and show a bare world map.
    };

    // -- Build a lookup map for the change handler ------------------------
    const layerById = {};
    geoLayers.forEach(l => { layerById[l.id] = l; });

    // -- Render panel -----------------------------------------------------
    panel.innerHTML = '';
    const groups = { base: [], overlay: [] };
    geoLayers.forEach(l => { groups[l.role === 'base' ? 'base' : 'overlay'].push(l); });

    // Determine which base is currently active to pre-check its radio.
    // Memory state takes priority; fall back to localStorage on first panel open after reload.
    let activeRasterBaseId = self.parent && self.parent._activeRasterBaseId;
    let activeVectorChannelId = null;
    if (!activeRasterBaseId) {
        const savedType = localStorage.getItem('aot_active_base_type');
        const savedId = localStorage.getItem('aot_active_base_id');
        if (savedType === 'raster' && savedId) {
            activeRasterBaseId = savedId;
        } else if (savedType === 'vector_channel' && savedId) {
            activeVectorChannelId = savedId;
        }
    } else {
        const savedType = localStorage.getItem('aot_active_base_type');
        const savedId = localStorage.getItem('aot_active_base_id');
        if (savedType === 'vector_channel' && savedId) {
            activeVectorChannelId = savedId;
        }
    }
    const vectorIsActive = !activeRasterBaseId;

    const labelMap = { base: (window._ ? window._('Base Map') : 'Base Map'), overlay: (window._ ? window._('Overlay') : 'Overlay') };
    ['base', 'overlay'].forEach(role => {
        if (groups[role].length === 0) return;
        const groupDiv = document.createElement('div');
        groupDiv.style.marginBottom = '8px';
        groupDiv.innerHTML = '<div style="font-weight:bold;padding:2px 0;color:#444;font-size:11px;' +
            'text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #eee;margin-bottom:4px;">' +
            labelMap[role] + '</div>';

        if (role === 'base') {
            // All base layers are mutually exclusive → radio buttons.
            // vector-type layers represent the loaded base style; selecting them restores vector.
            // No synthetic "__vector_default__" needed — the real vector layer IS that option.
            groups[role].forEach(l => {
                const isActive = l.type === 'vector'
                    ? (activeVectorChannelId ? l.id === activeVectorChannelId : vectorIsActive)
                    : (l.id === activeRasterBaseId);
                const itemDiv = document.createElement('div');
                itemDiv.style.padding = '3px 0';
                itemDiv.innerHTML = '<label style="cursor:pointer;display:flex;align-items:center;gap:6px;">' +
                    '<input type="radio" name="aot-lp-base"' + (isActive ? ' checked' : '') +
                    ' data-layer-id="' + l.id + '" data-layer-type="' + l.type + '"> ' +
                    '<span style="font-size:13px;">' + (l.name || l.id) + '</span></label>';
                groupDiv.appendChild(itemDiv);
            });
        } else {
            // Overlay layers: checkboxes, independent.
            groups[role].forEach(l => {
                const visible = _isVisible(l);
                const itemDiv = document.createElement('div');
                itemDiv.style.padding = '3px 0';
                itemDiv.innerHTML = '<label style="cursor:pointer;display:flex;align-items:center;gap:6px;">' +
                    '<input type="checkbox"' + (visible ? ' checked' : '') +
                    ' data-layer-id="' + l.id + '"> ' +
                    '<span style="font-size:13px;">' + (l.name || l.id) + '</span></label>';
                groupDiv.appendChild(itemDiv);
            });
        }

        panel.appendChild(groupDiv);
    });

    // -- 도형 그룹 --------------------------------------------------------
    //
    // 모드별 "지도에서 보기" 를 여기에도 낸다. 설정 드로어의 스위치와 **같은
    // 상태**(`_hiddenShapeTypes` / `vis_shape_<모드>`)를 보고 쓰므로 두 곳이
    // 어긋나지 않는다 — 배경지도를 고르러 온 김에 도형도 끄고 켤 수 있게
    // 하려는 것이지, 별도의 표시 상태를 하나 더 만드는 것이 아니다.
    const design = self.parent;
    if (design && design.shapeTypesForMode && design.setShapeTypeVisibility) {
        const MODES = [
            ['site', window._ ? window._('Site') : 'Site'],
            ['zone', window._ ? window._('Zone') : 'Zone'],
            ['facility', window._ ? window._('Facility') : 'Facility'],
            ['plot', window._ ? window._('Plot') : 'Plot'],
            ['equipment', window._ ? window._('Equipment') : 'Equipment'],
            ['aot_device', window._ ? window._('Device') : 'Device'],
        ];
        const shapeDiv = document.createElement('div');
        shapeDiv.style.marginBottom = '8px';
        shapeDiv.innerHTML = '<div style="font-weight:bold;padding:2px 0;color:#444;font-size:11px;' +
            'text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #eee;margin-bottom:4px;">' +
            (window._ ? window._('Shapes') : 'Shapes') + '</div>';
        MODES.forEach(([mode, label]) => {
            const visible = !design.shapeTypesForMode(mode)
                .some(t => design.isShapeTypeHidden(t));
            const itemDiv = document.createElement('div');
            itemDiv.style.padding = '3px 0';
            itemDiv.innerHTML = '<label style="cursor:pointer;display:flex;align-items:center;gap:6px;">' +
                '<input type="checkbox"' + (visible ? ' checked' : '') +
                ' data-shape-mode="' + mode + '"> ' +
                '<span style="font-size:13px;">' + label + '</span></label>';
            shapeDiv.appendChild(itemDiv);
        });
        panel.appendChild(shapeDiv);
    }

    // -- Event handler ----------------------------------------------------
    panel.onchange = function(e) {
        const input = e.target;
        if (input.type !== 'checkbox' && input.type !== 'radio') return;

        // 도형 표시 — 드로어 스위치와 같은 경로로 보낸다(저장·복원 포함).
        if (input.dataset.shapeMode) {
            const mode = input.dataset.shapeMode;
            const visible = input.checked;
            if (design.setShapeTypeVisibility) design.setShapeTypeVisibility(mode, visible);
            if (design.panel && design.panel._handleThemeColorChange) {
                design.panel._handleThemeColorChange(`vis_shape_${mode}`, visible);
            }
            // 드로어가 같은 모드를 열어 두고 있으면 스위치도 함께 움직인다.
            const drawerToggle = document.getElementById('shape-visible-toggle');
            if (drawerToggle && drawerToggle.dataset.shapeType === mode) {
                drawerToggle.checked = visible;
            }
            return;
        }

        const map = self.parent?.map?._originalMap || self.parent?.map;
        if (!map) return;

        if (input.type === 'radio') {
            const lid = input.dataset.layerId;
            const l = layerById[lid];
            if (!l) return;
            if (l.type === 'vector') {
                // If this channel's style URL differs from the currently loaded one, switch it
                // (preserving AoT feature layers). Otherwise just show the vector base.
                const loadedUrl = self.parent._activeVectorStyleUrl;
                if (l.url && l.url !== loadedUrl) {
                    _switchVectorBase(l);
                } else {
                    _restoreVectorBase();
                }
            } else {
                // Raster base: deactivate current, activate new
                _deactivateRasterBase();
                _activateRasterBase(l);
            }
            // Close panel after selecting a base layer
            panel.style.display = 'none';
            if (panel._outsideClickHandler) {
                document.removeEventListener('click', panel._outsideClickHandler, true);
                panel._outsideClickHandler = null;
            }
        } else {
            // Overlay checkbox
            const l = layerById[input.dataset.layerId];
            if (!l) return;
            if (input.checked) { _addOverlay(l); } else { _hideOverlay(l); }
        }
    };
};
