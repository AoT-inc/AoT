class AoTGeoPanel {
    constructor(containerId, geoDesign) {
        // Target the tiered navigation panel
        this.container = document.getElementById('nav-mode-panel');
        this.viewport = document.getElementById('nav-tier-viewport');
        this.geoDesign = geoDesign;

        this.currentMode = 'site';
        this.selectedFeature = null;

        // Config State
        this.pipeConfig = { spacing: 14.0, angle: 0, offset: 0, is90Deg: false };
        this.sprinklerConfig = { interval: 14.0, radius: 11.0, flow: 850, pressure: 2.0 };
        this.dripConfig = { interval: 0.3, flow: 1.0, pressure: 1.0 };
        const theme = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
        this.isLabelHidden = theme.hide_label === 'true' || theme.hide_label === true;

        // Navigation State
        this.navStack = ['main', 'site']; // Current drill-down path (Init with 'site' to show sub-menu)
        this.deviceCat = null; // supply, filter, valve, conn
        this.deviceSubMode = 'input'; // input, output, function
        this.irrigationType = 'sprinkler'; // sprinkler, drip
        this.irrigationSettingsOpen = true; // Auto-open settings
        this._isDragging = false; // Mouse drag state helper

        this.lastStack = []; // track for animations

        // Bind event for vertical swipe/scroll handling
        if (this.viewport) {
            this.viewport.addEventListener('scroll', this._handleVerticalScroll.bind(this));
        }

        // [Refined] Initial Scroll Check
        this._updateScrollLock();

        // [Fix] V8: Prevent Map Zoom when scrolling panel (MouseWheel)
        if (this.viewport && typeof L !== 'undefined') {
            L.DomEvent.disableScrollPropagation(this.viewport);
            L.DomEvent.disableClickPropagation(this.viewport);
        }

        // Initialize with default mode if needed
        // Note: geoDesign will likely call setMode later, but we can init default here.
    }

    /**
     * Entry point for rendering. Synchronizes state and triggers the tiered render loop.
     */
    render(mode = null, feature = this.selectedFeature) {
        if (!this.viewport) return;

        // Mode Switch Detection: Reset stack if mode changes explicitly
        // [Refined] Option 2: Tier 1 Maintained, Tier 2 Drills Down
        if (mode && mode === this.currentMode) {
            // [Reset Logic] If deep in sub-menu (Stack > 3), and clicking parent mode, reset to defaults
            // e.g. clicking 'Equipment' while in 'Supply' -> Reset to 'Equipment > Pipe' (Default)
            if (this.navStack.length > 3) {
                if (mode === 'equipment') this.navStack = ['main', 'equipment', 'pipe'];
                if (mode === 'aot_device') this.navStack = ['main', 'aot_device', 'output'];
            }
        }

        if (mode && mode !== this.currentMode) {
            this.currentMode = mode;
            if (mode === 'main') {
                this.navStack = ['main'];
            } else {
                this.navStack = ['main', mode];
            }

            // [Refined] Auto-Drill Defaults
            // [Fix V19] Trigger detailed view immediately for complex modes
            if (mode === 'equipment') {
                this.navStack = ['main', 'equipment', 'pipe']; // Default to Pipe
            }
            else if (mode === 'aot_device') {
                this.navStack = ['main', 'aot_device', 'input']; // Default to Input
            }
        }

        // ... (Theme apply unchanged) ...

        this._applyThemeColor(this.currentMode);
        this.selectedFeature = feature;

        // [Sync Logic] Restore synchronization:
        // 1. If no feature, reset to defaults
        // 2. If feature has properties, merge them into local config
        if (feature && feature.properties) {
            if (feature.properties.gen_config_pipe) {
                // Parse if string (DB serialization quirk check)
                let cfg = feature.properties.gen_config_pipe;
                if (typeof cfg === 'string') { try { cfg = JSON.parse(cfg); } catch (e) { } }
                Object.assign(this.pipeConfig, cfg);
            }
            if (feature.properties.gen_config_sprinkler) {
                let cfg = feature.properties.gen_config_sprinkler;
                if (typeof cfg === 'string') { try { cfg = JSON.parse(cfg); } catch (e) { } }
                Object.assign(this.sprinklerConfig, cfg);
            }
            if (feature.properties.gen_config_drip) {
                let cfg = feature.properties.gen_config_drip;
                if (typeof cfg === 'string') { try { cfg = JSON.parse(cfg); } catch (e) { } }
                Object.assign(this.dripConfig, cfg);
            }
        } else {
            // Reset to defaults when no feature is selected
            this._resetConfigs();
        }

        try {
            this._suppressScroll = true;

            // [New] Animation Logic (Horizontal Slide for Tier 1 <-> Tier 2, Instant for others)
            // Define 'Deep' modes that trigger main slide animation
            const deepModes = ['equipment', 'aot_device'];
            const isDeep = (stack) => stack.length > 1 && deepModes.includes(stack[1]);

            const prevDeep = isDeep(this.lastStack);
            const currDeep = isDeep(this.navStack);

            let isAnim = false;
            let leaveClass = '';
            let enterClass = '';

            // 1. Enter Deep Mode (Shallow -> Deep)
            if (!prevDeep && currDeep) {
                isAnim = true;
                leaveClass = 'slide-next-leave';
                enterClass = 'slide-next-enter';
            }
            // 2. Exit Deep Mode (Deep -> Shallow)
            else if (prevDeep && !currDeep) {
                isAnim = true;
                leaveClass = 'slide-back-leave';
                enterClass = 'slide-back-enter';
            }
            // 3. Else (Deep -> Deep, Shallow -> Shallow) -> Instant

            // Store old elements
            const oldTiers = Array.from(this.viewport.children);
            
            if (isAnim) {
                // Apply Leaving Class
                oldTiers.forEach(t => t.classList.add(leaveClass));
            } else {
                // Instant Removal
                oldTiers.forEach(t => t.remove());
            }

            const simpleModes = ['site', 'zone', 'facility'];
            let tiersToRender = [];

            if (this.navStack.length <= 1) {
                // Root
                tiersToRender = [{ id: 'main', index: 0, isBack: false }];
            } else if (simpleModes.includes(this.currentMode)) {
                // Simple
                tiersToRender.push({ id: 'main', index: 0, isBack: false });
                tiersToRender.push({ id: this.currentMode, index: 1, isBack: false });
            } else {
                // Complex (Option 2 Logic)
                const headerIndex = 1;
                const isDeep = this.navStack.length > 3;

                tiersToRender.push({ id: this.navStack[headerIndex], index: headerIndex, isBack: true });

                if (this.navStack.length > 2) {
                    // Tier 2 (Leaf)
                    const leafIndex = this.navStack.length - 1;
                    tiersToRender.push({ id: this.navStack[leafIndex], index: leafIndex, isBack: false });
                }
            }

            // Create new tiers
            const newTierEls = tiersToRender.map((tierObj) => {
                const tierEl = document.createElement('div');
                tierEl.className = 'nav-tier';
                if (isAnim) tierEl.classList.add(enterClass);

                tierEl.dataset.tierId = tierObj.id;
                tierEl.dataset.index = tierObj.index;

                let content = this._getTierContent(tierObj.id, tierObj.index);

                // [Refined] Inject Back Button if this is the Header Tier (Tier 1 in Modal)
                if (tierObj.isBack) {
                    // Prepend Back Button
                    const iconClass = tierObj.index > 1 ? 'fa-arrow-up' : 'fa-arrow-left';
                    const backBtn = `<div class="btn-nav-back" data-nav-action="back"><i class="fas ${iconClass}"></i></div>`;
                    content = backBtn + content;
                }

                // [Refined] Wrap content in inner container for safe centering
                tierEl.innerHTML = `<div class="nav-tier-inner">${content}</div>`;

                // [Feature] Mouse Drag Scrolling
                this._attachDragScroll(tierEl);
                this._bindNavEvents(tierEl);

                return tierEl;
            });

            // Append New Tiers
            newTierEls.forEach(el => this.viewport.appendChild(el));

            // Execute Animation
            if (isAnim) {
                // Clean Old Tiers after transition
                setTimeout(() => {
                    oldTiers.forEach(t => t.remove());
                }, 400); // Match CSS transition duration

                // Trigger New Tier Entry
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        newTierEls.forEach(el => el.classList.remove(enterClass));
                    });
                });
            } else {
                // Already clean. No animation needed.
            }

            this.lastStack = [...this.navStack];
            this._updateScrollLock();
            this._scrollToActiveTier();
            setTimeout(() => { this._suppressScroll = false; }, 600); // [Fix] Allow smooth scroll to finish
        } catch (e) {
            // console.error("[AoTGeoPanel] Render Error:", e);
            this.viewport.innerHTML = `<div class="text-danger p-2 small">Render Error: ${e.message}</div>`;
        }
    }

    /**
     * Centers the view. (Obsolete Row Logic Removed).
     * Since we only render visible tiers, just ensure top alignment.
     */
    _scrollToActiveTier() {
        if (this.viewport) this.viewport.scrollTop = 0;
    }

    /**
     * Generates HTML content for a specific tier ID.
     */
    _getTierContent(tierId, index) {
        let html = '';
        // [Refined] Legacy Back Button Block Removed (Handled by render() injection)

        switch (tierId) {
            // --- Tier 1: Main Tabs ---
            case 'main':
                html += `
                    <div class="mode-tab ${this.currentMode === 'site' ? 'active' : ''}" data-nav-mode="site">${_('Site')}</div>
                    <div class="mode-tab ${this.currentMode === 'zone' ? 'active' : ''}" data-nav-mode="zone">${_('Zone')}</div>
                    <div class="mode-tab ${this.currentMode === 'facility' ? 'active' : ''}" data-nav-mode="facility">${_('Facility')}</div>
                    <div class="mode-tab ${this.currentMode === 'equipment' ? 'active' : ''}" data-nav-mode="equipment">${_('Equipment')}</div>
                    <div class="mode-tab ${this.currentMode === 'aot_device' ? 'active' : ''}" data-nav-mode="aot_device">${_('A')}</div>
                `;
                break;

            case 'site': case 'zone': case 'facility':
                const currentType = tierId;
                const config = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const activeColor = config[currentType] || (currentType === 'site' ? '#DF5353' : (currentType === 'zone' ? '#28a745' : '#82898f'));

                html += `
                    <!-- Theme Color Picker (26px Circle) -->
                    <div style="width: 26px; height: 26px; border-radius: 50%; overflow: hidden; border: none; margin: 0 8px 0 4px; flex-shrink: 0; box-shadow: 0 0 0 1px rgba(0,0,0,0.1);">
                        <input type="color" id="theme-color-picker" data-type="${currentType}" value="${activeColor}" style="width: 140%; height: 140%; margin: -20%; cursor: pointer; border: none; padding: 0;">
                    </div>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-union">${_('Union')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-diff">${_('Subtract')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-hide-label" style="min-width: 70px;">${this.isLabelHidden ? _('Show length') : _('Hide length')}</button>
                `;
                break;

            // --- Tier 2: Equipment Root ---
            case 'equipment':
                const eqConfig = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const eqColor = eqConfig['equipment'] || '#007bff';

                html += `
                    <!-- Theme Color Picker (26px Circle) -->
                    <div style="width: 26px; height: 26px; border-radius: 50%; overflow: hidden; border: none; margin: 0 8px 0 4px; flex-shrink: 0; box-shadow: 0 0 0 1px rgba(0,0,0,0.1);">
                        <input type="color" id="theme-color-picker" data-type="equipment" value="${eqColor}" style="width: 140%; height: 140%; margin: -20%; cursor: pointer; border: none; padding: 0;">
                    </div>
                    <div class="mode-tab ${this._isActivePath('device') ? 'active' : ''}" data-nav-sub="device">${_('Device')}</div>
                    <div class="mode-tab ${this._isActivePath('pipe') ? 'active' : ''}" data-nav-sub="pipe">${_('Pipe')}</div>
                    <div class="mode-tab ${this._isActivePath('sprinkler') ? 'active' : ''}" data-nav-sub="sprinkler">${_('Irrigation')}</div>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-hide-label" style="min-width: 70px;">${this.isLabelHidden ? _('Show length') : _('Hide length')}</button>
                `;
                break;

            // --- Tier 2: Aot Device Root ---
            case 'aot_device':
                html += `
                    <div class="mode-tab ${this._isActivePath('input') ? 'active' : ''}" data-nav-sub="input">${_('Input')}</div>
                    <div class="mode-tab ${this._isActivePath('output') ? 'active' : ''}" data-nav-sub="output">${_('Output')}</div>
                    <div class="mode-tab ${this._isActivePath('function') ? 'active' : ''}" data-nav-sub="function">${_('Function')}</div>
                `;
                break;

            // --- Tier 3: Aot Device Actions ---
            case 'input': case 'output': case 'function':
                const type = tierId;
                
                const appTheme = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const serverColor = appTheme[type];
                
                const savedColor = serverColor || (type === 'function' ? '#995aff' : getComputedStyle(document.documentElement).getPropertyValue('--theme-device').trim() || '#9013FE');
                const savedVisValue = appTheme[`vis_${type}`];
                const isVisible = (savedVisValue === undefined || savedVisValue === null) ? true : (savedVisValue === 'true' || savedVisValue === true);

                html += `
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-device-list">${_('Selection list')} ></button>
                    
                    <!-- Color Picker (26px Circle) -->
                    <div style="position: relative; width: 26px; height: 26px; border-radius: 50%; overflow: hidden; border: 1px solid #ddd; margin: 0 4px;">
                        <input type="color" id="device-color-picker" value="${savedColor}" style="position: absolute; top: -50%; left: -50%; width: 200%; height: 200%; padding: 0; margin: 0; cursor: pointer;">
                    </div>

                    <!-- Slide Toggle Switch -->
                    <label class="switch" style="margin-left: 8px;">
                        <input type="checkbox" id="device-visible-toggle" ${isVisible ? 'checked' : ''}>
                        <span class="slider round"></span>
                    </label>
                `;
                break;

            // --- Tier 3: Equipment > Device Categories ---
            case 'device':
                html += `
                    <div class="mode-tab ${this._isActivePath('supply') ? 'active' : ''}" data-nav-cat="supply">${_('Water supply')}</div>
                    <div class="mode-tab ${this._isActivePath('filter') ? 'active' : ''}" data-nav-cat="filter">${_('Filter')}</div>
                    <div class="mode-tab ${this._isActivePath('valve') ? 'active' : ''}" data-nav-cat="valve">${_('Valve')}</div>
                    <div class="mode-tab ${this._isActivePath('conn') ? 'active' : ''}" data-nav-cat="conn">${_('Connection')}</div>
                `;
                break;

            // --- Tier 3: Equipment > Pipe Actions ---
            case 'pipe':
                html += `
                    <button class="btn btn-aot-pill btn-aot-outline" data-nav-sub="pipe_settings">${_('Settings')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-draw-ref">${_('Reference line')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-draw-main">${_('Main pipe')}</button>
                    <button class="btn btn-aot-pill btn-aot-action font-weight-bold" id="btn-gen-pipe">${_('Generate')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline ${this.pipeConfig.is90Deg ? 'active' : ''}" id="btn-90deg">${_('90 degree')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-clear-equip" data-clear-mode="all">${_('Reset')}</button>
                `;
                break;

            // --- Tier 3: Equipment > Irrigation (Shared Controller) ---
            case 'sprinkler':
                html += `
                    <button class="btn btn-aot-pill btn-aot-outline ${this.irrigationType === 'sprinkler' ? 'active' : ''}" id="btn-set-sprinkler">${_('Sprinkler')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline ${this.irrigationType === 'drip' ? 'active' : ''}" id="btn-set-drip">${_('Drip')}</button>
                    <button class="btn btn-aot-pill btn-aot-action font-weight-bold" id="btn-gen-irrigation">${_('Generate')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-clear-equip" data-clear-mode="sprinkler">${_('Reset')}</button>
                `;

                // Separator
                html += `<div style="width: 1px; height: 16px; background: #ddd; margin: 0 8px;"></div>`;
                if (this.irrigationType === 'sprinkler') {

                    html += `
                        <div class="d-flex align-items-center">
                            <span style="font-size: 11px; font-weight: bold; color: #666; margin-right: 4px;">${_('Spacing')}</span>
                            <input type="number" class="form-control-compact" id="sp-interval" value="${this.sprinklerConfig.interval}" style="width: 50px; margin-right: 8px;">
                            
                            <span style="font-size: 11px; font-weight: bold; color: #666; margin-right: 4px;">${_('Radius')}</span>
                            <input type="number" class="form-control-compact" id="sp-radius" value="${this.sprinklerConfig.radius}" style="width: 50px; margin-right: 8px;">
                            
                            <span style="font-size: 11px; font-weight: bold; color: #666; margin-right: 4px;">${_('Flow rate')}</span>
                            <input type="number" class="form-control-compact" id="sp-flow" value="${this.sprinklerConfig.flow}" style="width: 50px; margin-right: 8px;">
                            
                            <span style="font-size: 11px; font-weight: bold; color: #666; margin-right: 4px;">${_('Pressure')}</span>
                            <input type="number" class="form-control-compact" id="sp-pressure" value="${this.sprinklerConfig.pressure}" style="width: 50px; margin-right: 8px;">
                        </div>
                    `;
                } else {
                    html += `
                         <div class="d-flex align-items-center">
                            <span style="font-size: 11px; font-weight: bold; color: #666; margin-right: 4px;">${_('Spacing')}</span>
                            <input type="number" class="form-control-compact" id="dp-interval" value="${this.dripConfig.interval}" style="width: 50px; margin-right: 8px;">
                            
                            <span style="font-size: 11px; font-weight: bold; color: #666; margin-right: 4px;">${_('Flow rate')}</span>
                            <input type="number" class="form-control-compact" id="dp-flow" value="${this.dripConfig.flow}" style="width: 50px; margin-right: 8px;">
                            
                            <span style="font-size: 11px; font-weight: bold; color: #666; margin-right: 4px;">${_('Pressure')}</span>
                            <input type="number" class="form-control-compact" id="dp-pressure" value="${this.dripConfig.pressure}" style="width: 50px; margin-right: 8px;">
                        </div>
                    `;
                }
                break;



            // --- Tier 4: Irrigation Settings (Dynamic) ---


            // --- Tier 4: Device Items ---
            case 'supply': html += `<button class="btn btn-aot-pill btn-aot-outline" data-device-item="river">${_('River')}</button><button class="btn btn-aot-pill btn-aot-outline" data-device-item="tank">${_('Water tank')}</button><button class="btn btn-aot-pill btn-aot-outline" data-device-item="pump">${_('Pump')}</button>`; break;
            case 'filter': html += `<button class="btn btn-aot-pill btn-aot-outline" data-device-item="disc">${_('Disc')}</button><button class="btn btn-aot-pill btn-aot-outline" data-device-item="screen">${_('Screen')}</button><button class="btn btn-aot-pill btn-aot-outline" data-device-item="sand">${_('Sand')}</button>`; break;
            case 'valve': html += `<button class="btn btn-aot-pill btn-aot-outline" data-device-item="union">${_('Union valve')}</button><button class="btn btn-aot-pill btn-aot-outline" data-device-item="m-single">${_('Adapter valve')}</button><button class="btn btn-aot-pill btn-aot-outline" data-device-item="f-single">${_('Inline valve')}</button><button class="btn btn-aot-pill btn-aot-outline" data-device-item="reducer">${_('Reducer')}</button>`; break;
            case 'conn': html += `<button class="btn btn-aot-pill btn-aot-outline" data-device-item="suction">${_('Suction')}</button><button class="btn btn-aot-pill btn-aot-outline" data-device-item="elbow">${_('Elbow')}</button><button class="btn btn-aot-pill btn-aot-outline" data-device-item="tee">${_('Tee')}</button><button class="btn btn-aot-pill btn-aot-outline" data-device-item="reducer">${_('Reducer')}</button>`; break;

            // --- Tier 4: Pipe Settings ---
            case 'pipe_settings':
                const isDesktop = window.innerWidth > 768;
                if (isDesktop) {
                    html += `
                        <div class="d-flex align-items-center bg-white rounded-pill px-2 border mr-2" style="height: 28px; min-width: 95px;">
                            <span class="small text-muted mr-1">${_('spacing')}</span>
                            <input type="number" step="0.5" class="form-control-compact border-0 p-0" id="pipe-spacing" value="${this.pipeConfig.spacing}" style="width: 50px;">
                        </div>
                        <div class="d-flex align-items-center bg-light rounded-pill px-2 mr-2" style="height: 28px; flex: 2; min-width: 320px;">
                            <span class="small font-weight-bold text-muted mr-1" style="white-space: nowrap;">${_('Angle')}</span>
                            <input type="range" class="custom-range flex-fill" id="pipe-angle" min="-90" max="90" step="1" value="${this.pipeConfig.angle}">
                            <span class="small font-weight-bold ml-1 text-primary" id="val-angle" style="min-width: 32px; text-align: right;">${this.pipeConfig.angle}°</span>
                        </div>
                        <div class="d-flex align-items-center bg-light rounded-pill px-2" style="height: 28px; flex: 2; min-width: 320px;">
                            <span class="small font-weight-bold text-muted mr-1" style="white-space: nowrap;">${_('Offset')}</span>
                            <input type="range" class="custom-range flex-fill" id="pipe-offset" min="-15" max="15" step="0.5" value="${this.pipeConfig.offset}">
                            <span class="small font-weight-bold ml-1 text-primary" id="val-offset" style="min-width: 42px; text-align: right;">${this.pipeConfig.offset}m</span>
                        </div>
                    `;
                } else {
                    html += `
                        <div class="d-flex align-items-center bg-white rounded-pill px-2 border mr-1" style="height: 28px;">
                            <span class="small text-muted mr-1">${_('spacing')}</span>
                            <input type="number" step="0.5" class="form-control-compact border-0 p-0" id="pipe-spacing" value="${this.pipeConfig.spacing}">
                        </div>
                        <button class="btn btn-aot-pill btn-aot-outline" data-nav-sub="pipe_angle">${_('Angle')} ></button>
                        <button class="btn btn-aot-pill btn-aot-outline" data-nav-sub="pipe_offset">${_('Offset')} ></button>
                    `;
                }
                break;

            // --- Tier 5: Pipe Sliders ---
            case 'pipe_angle':
                html += `
                    <div class="d-flex align-items-center bg-light rounded-pill px-2 mx-1" style="height: 28px; width: calc(100% - 10px); min-width: 280px;">
                        <span class="small font-weight-bold text-muted mr-1" style="white-space: nowrap;">${_('angle')}</span>
                        <input type="range" class="custom-range flex-fill" id="pipe-angle" min="-90" max="90" step="1" value="${this.pipeConfig.angle}">
                        <span class="small font-weight-bold ml-1 text-primary" id="val-angle" style="min-width: 32px; text-align: right;">${this.pipeConfig.angle}°</span>
                    </div>
                `;
                break;
            case 'pipe_offset':
                html += `
                    <div class="d-flex align-items-center bg-light rounded-pill px-2 mx-1" style="height: 28px; width: calc(100% - 10px); min-width: 280px;">
                        <span class="small font-weight-bold text-muted mr-1" style="white-space: nowrap;">${_('Offset')}</span>
                        <input type="range" class="custom-range flex-fill" id="pipe-offset" min="-15" max="15" step="0.5" value="${this.pipeConfig.offset}">
                        <span class="small font-weight-bold ml-1 text-primary" id="val-offset" style="min-width: 42px; text-align: right;">${this.pipeConfig.offset}m</span>
                    </div>
                `;
                break;

            // [Legacy] sprinkler_set/drip_set removed, merged into 'irrigation_settings'

        }

        return html;
    }

    _isActivePath(key) {
        // Check if the key exists anywhere in the navigation stack
        return this.navStack.includes(key);
    }

    _bindNavEvents(rootEl = this.viewport) {
        // Navigation: Tier 1 (Main Modes)
        rootEl.querySelectorAll('[data-nav-mode]').forEach(el => {
            el.onclick = () => {
                if (this._isDragging) return;
                const mode = el.dataset.navMode;
                // [Refined] Delegate to render(mode) to handle Auto-Drill Defaults
                this.render(mode);
                if (this.geoDesign && this.geoDesign.setMode) this.geoDesign.setMode(mode);
            };
        });

        // Navigation: Drill-down
        rootEl.querySelectorAll('[data-nav-sub], [data-nav-cat]').forEach(el => {
            el.onclick = () => {
                if (this._isDragging) return;
                const targetId = el.dataset.navSub || el.dataset.navCat;
                // [Refined] Get source tier index to determine depth
                const tierEl = el.closest('.nav-tier');
                const sourceIndex = tierEl ? parseInt(tierEl.dataset.index) : (this.navStack.length - 1);

                this._navigateToTier(targetId, sourceIndex);
            };
        });

        // Navigation: Back Action
        // Navigation: Back Action
        rootEl.querySelectorAll('[data-nav-action="back"]').forEach(el => {
            el.onclick = () => {
                if (this._isDragging) return;
                // [Refined] Context-Aware Back Logic
                const tierEl = el.closest('.nav-tier');
                const tierIndex = tierEl ? parseInt(tierEl.dataset.index) : 1;

                // Tier 1 Back Button (Left Arrow) -> Always Exit to Main
                if (tierIndex === 1) {
                    this.render('site');
                    if (this.geoDesign && this.geoDesign.setMode) {
                        this.geoDesign.setMode('site');
                    }
                } else {
                    // Tier 2 Back Button (Up Arrow) -> Drill Up (Pop Stack)
                    this._popTier();
                }
            };
        });

        // --- Core Functional Bindings ---

        // Geometry Ops
        const btnUnion = rootEl.querySelector('#btn-union');
        if (btnUnion) btnUnion.onclick = () => this._handleGeometryOp('merge');
        const btnDiff = rootEl.querySelector('#btn-diff');
        if (btnDiff) btnDiff.onclick = () => this._handleGeometryOp('sub');
        const btnHide = rootEl.querySelector('#btn-hide-label');
        if (btnHide) btnHide.onclick = () => {
            this.isLabelHidden = !this.isLabelHidden;
            this._handleThemeColorChange('hide_label', this.isLabelHidden);
            this._handleGeometryOp('hide-label');
            this.render();
        };

        // Pipe Settings
        const pipeSp = rootEl.querySelector('#pipe-spacing');
        if (pipeSp) pipeSp.onchange = (e) => {
            this.pipeConfig.spacing = parseFloat(e.target.value);
            this._triggerPipeGen();
        };

        const pipeAng = rootEl.querySelector('#pipe-angle');
        if (pipeAng) {
            // [Fix] oninput: Update UI only (Responsive)
            pipeAng.oninput = (e) => {
                this.pipeConfig.angle = parseInt(e.target.value);
                const val = rootEl.querySelector('#val-angle');
                if (val) val.innerText = `${this.pipeConfig.angle}°`;
            };
            // [Fix] onchange: Trigger Server Request only on release (MouseUp/TouchEnd)
            pipeAng.onchange = (e) => {
                this._triggerPipeGen();
            };
        }

        const pipeOff = rootEl.querySelector('#pipe-offset');
        if (pipeOff) {
            // [Fix] oninput: Update UI only
            pipeOff.oninput = (e) => {
                this.pipeConfig.offset = parseFloat(e.target.value);
                const val = rootEl.querySelector('#val-offset');
                if (val) val.innerText = `${this.pipeConfig.offset}m`;
            };
            // [Fix] onchange: Trigger Server Request only on release
            pipeOff.onchange = (e) => {
                this._triggerPipeGen();
            };
        }

        // Pipe Actions
        const btn90 = rootEl.querySelector('#btn-90deg');
        if (btn90) btn90.onclick = () => {
            // [Fix] Toggle 90-degree offset flag ONLY.
            // Backend handles (angle + 90) logic. Incrementing angle here caused 180deg total turn.
            this.pipeConfig.is90Deg = !this.pipeConfig.is90Deg;

            this.render();
            this._triggerPipeGen();
        };
        const btnRef = rootEl.querySelector('#btn-draw-ref');
        if (btnRef) btnRef.onclick = () => this.geoDesign.startDraw('polyline', { type: 'ref_line' });
        const btnMainP = rootEl.querySelector('#btn-draw-main');
        if (btnMainP) btnMainP.onclick = () => this.geoDesign.startDraw('polyline', { type: 'main_pipe' });
        const btnGenPipes = rootEl.querySelector('#btn-gen-pipe');
        if (btnGenPipes) btnGenPipes.onclick = () => this._triggerPipeGen();
        const btnClear = rootEl.querySelectorAll('#btn-clear-equip');
        btnClear.forEach(btn => {
            btn.onclick = () => {
                // [Fix] Robust Mode Detection via Attribute
                const mode = btn.dataset.clearMode || 'all';
                this._handleGeometryOp('clear-equip', mode);
            };
        });

        // Irrigation Toggles
        const btnSetSp = rootEl.querySelector('#btn-set-sprinkler');
        if (btnSetSp) btnSetSp.onclick = () => { this.irrigationType = 'sprinkler'; this.render(); };

        const btnSetDr = rootEl.querySelector('#btn-set-drip');
        if (btnSetDr) btnSetDr.onclick = () => { this.irrigationType = 'drip'; this.render(); };

        // Irrigation Inputs
        ['interval', 'radius', 'flow', 'pressure'].forEach(key => {
            const el = rootEl.querySelector(`[id="sp-${key}"]`);
            if (el) el.onchange = (e) => {
                this.sprinklerConfig[key] = parseFloat(e.target.value);
                this._triggerIrrigationGen();
            };

            const elD = rootEl.querySelector(`[id="dp-${key}"]`);
            if (elD) elD.onchange = (e) => {
                this.dripConfig[key] = parseFloat(e.target.value);
                this._triggerIrrigationGen();
            };
        });

        // Shared Generate Button
        const btnGenIrr = rootEl.querySelector('#btn-gen-irrigation');
        if (btnGenIrr) btnGenIrr.onclick = () => this._triggerIrrigationGen();

        // Device Modal
        const btnList = rootEl.querySelector('#btn-device-list');
        if (btnList) btnList.onclick = () => {
            // Determine subMode from navStack (it's the current tier)
            const subMode = this.navStack[this.navStack.length - 1]; // e.g., 'input'
            this._openDeviceModal(subMode);
        };

        // Device Color Picker (Input/Output/Function)
        const deviceColorPicker = rootEl.querySelector('#device-color-picker');
        if (deviceColorPicker) {
            deviceColorPicker.oninput = (e) => {
                const color = e.target.value;
                const subMode = this.navStack[this.navStack.length - 1]; // e.g., 'input'
                if (this.geoDesign && this.geoDesign.setDeviceLabelColor) {
                    this.geoDesign.setDeviceLabelColor(subMode, color);
                }
            };
            deviceColorPicker.onchange = (e) => {
                const subMode = this.navStack[this.navStack.length - 1];
                this._handleThemeColorChange(subMode, e.target.value);
            };
        }

        // Tier 2 Theme Color Picker (Site, Zone, Facility, Equipment)
        const themeColorPicker = rootEl.querySelector('#theme-color-picker');
        if (themeColorPicker) {
            themeColorPicker.oninput = (e) => {
                const color = e.target.value;
                const type = themeColorPicker.dataset.type;
                // Live update CSS, Map Layers, and UI without saving to server
                this._handleThemeColorChange(type, color, true);
            };
            themeColorPicker.onchange = (e) => {
                const type = themeColorPicker.dataset.type;
                this._handleThemeColorChange(type, e.target.value, false);
            };
        }

        // Device Visibility Toggle
        const toggleVis = rootEl.querySelector('#device-visible-toggle');
        if (toggleVis) {
            toggleVis.onchange = (e) => {
                const isVisible = e.target.checked;
                const subMode = this.navStack[this.navStack.length - 1]; // e.g., 'input'
                this._handleThemeColorChange(`vis_${subMode}`, isVisible);
                if (this.geoDesign && this.geoDesign.setDeviceVisibility) {
                    this.geoDesign.setDeviceVisibility(subMode, isVisible);
                }
            };
        }

        // Device Items (Place on Map)
        rootEl.querySelectorAll('[data-device-item]').forEach(el => {
            el.onclick = () => {
                const item = el.dataset.deviceItem;
                if (window.showToast) window.showToast(`${item} ${_('Placement mode')}`, 'info');

                if (this.geoDesign && this.geoDesign.startDraw) {
                    // Map item to drawing context (Default: Equipment Marker with sub_type)
                    this.geoDesign.startDraw('marker', { type: 'equipment', sub_type: item });
                }
            };
        });
    }

    _navigateToTier(targetId, sourceIndex) {
        // Cut stack at source level and append new target
        // e.g. [main, equipment, device] (len 3). Click in Tier 1 (equipment).
        // sourceIndex = 1. Slice(0, 2) -> [main, equipment]. Push target.
        // Result: [main, equipment, pipe].

        // Prevent redundant render if clicking active tab
        // Prevent redundant render if clicking active tab, UNLESS we are deep in sub-menu
        const currentNext = this.navStack[sourceIndex + 1];
        if (currentNext === targetId && this.navStack.length === sourceIndex + 2) return;

        this.navStack = this.navStack.slice(0, sourceIndex + 1);
        this.navStack.push(targetId);

        // [Refined] Auto-Open Settings when entering Sprinkler mode
        // [Refined] Auto-Load Default: If Sprinkler Mode, reset irrigationType but don't drill down
        if (targetId === 'sprinkler' && this.irrigationType !== 'sprinkler') {
            this.irrigationType = 'sprinkler';
        }
        if (targetId === 'sprinkler_settings') this.irrigationType = 'sprinkler';
        if (targetId === 'drip_settings') this.irrigationType = 'drip';

        this.render();
    }

    _popTier() {
        if (this.navStack.length > 1) {
            const popped = this.navStack.pop();

            // [Refined] Coupled Tier Logic:
            // If we are popping 'irrigation_settings' (Tier 4), we essentially want to exit Sprinkler Mode (Tier 3).
            // So we pop 'sprinkler' as well.


            this.render();
        }
    }

    _handleVerticalScroll() {
        if (!this.viewport) return;
        const scrollTop = this.viewport.scrollTop;
        const tierHeight = 38; // [Refined] 28px + 10px

        // "Swipe Up" to go back
        // If we scroll UP significantly past the target scroll point, it means user wants to see previous.
        // Current Target Y is (N-2)*40.
        // If scrollTop < (N-2)*40 - Threshold, then POP.

        if (this._suppressScroll) return; // [Fix] Ignore system-dimmed scrolls (render)

        if (this.navStack.length > 2) { // Only if we have history beyond main+1
            const targetY = (this.navStack.length - 2) * tierHeight;
            // [Tuned] Increased threshold to 25px (more intent required)
            // Added check to ensure we are actually scrolling UP (scrollTop < previous) - simple check
            const threshold = 25;
            if (scrollTop < targetY - threshold) {
                // Debounce simple accidental scrolls
                if (!this._scrollDebounce) {
                    this._scrollDebounce = true;
                    this._popTier();
                    setTimeout(() => this._scrollDebounce = false, 800); // Increased cooldown
                }
            }
        }
    }

    /**
     * Attaches mouse drag-to-scroll functionality to a nav-tier element.
     */
    _attachDragScroll(el) {
        let isDown = false;
        let startX;
        let scrollLeft;

        el.addEventListener('mousedown', (e) => {
            // [Bugfix] Ignore drag if clicking on slider/input to allow native range interaction
            if (e.target.tagName === 'INPUT' && (e.target.type === 'range' || e.target.type === 'number')) return;
            
            isDown = true;
            // el.style.cursor = 'grabbing'; // Optional: visual cue
            startX = e.pageX - el.offsetLeft;
            scrollLeft = el.scrollLeft;
            this._isDragging = false; // Reset start
        });

        el.addEventListener('mouseleave', () => {
            isDown = false;
            // el.style.cursor = 'grab';
        });

        el.addEventListener('mouseup', () => {
            isDown = false;
            // el.style.cursor = 'grab';
            // Allow a small tick for click to fire if not dragging, 
            // but here we rely on _isDragging being set in mousemove
            // Reset _isDragging after a short delay so click handlers tracking it can see it
            setTimeout(() => { this._isDragging = false; }, 50);
        });

        el.addEventListener('mousemove', (e) => {
            if (!isDown) return;
            e.preventDefault(); // Prevent text selection
            const x = e.pageX - el.offsetLeft;
            const walk = (x - startX) * 2; // Scroll-fast speed

            // Threshold to consider it a drag
            if (Math.abs(walk) > 5) {
                this._isDragging = true;
            }

            el.scrollLeft = scrollLeft - walk;
        });
    }

    _triggerPipeGen() {
        if (!this.selectedFeature) {
            if (this.geoDesign.ui) this.geoDesign.ui.showToast(_('Please select a Zone first.'), 'warning');
            return;
        }

        // [Fix] Ensure target is a container (Site/Zone)
        const type = this.selectedFeature.properties?.aot_type;
        if (type !== 'site' && type !== 'zone') {
             if (this.geoDesign.ui) this.geoDesign.ui.showToast(_('Branch pipe requires Zone or Site.'), 'warning');
             return;
        }

        this.geoDesign.generatePipes(this.selectedFeature, this.pipeConfig);
    }

    _triggerIrrigationGen() {
        if (!this.selectedFeature) {
            if (this.geoDesign.ui) this.geoDesign.ui.showToast(_('Please select a Zone first.'), 'warning');
            return;
        }

        const currentId = this.selectedFeature.properties?.node_id;
        // console.log(`[GeoPanel] Triggering Gen for: ${currentId}. Last Gen ID: ${this._lastGenFeatureId}`);

        if (this.irrigationType === 'sprinkler') {
            // [New] Sequential Click Logic for Reverse Generation
            if (this._lastGenFeatureId === currentId) {
                // Toggle isReverse
                this.sprinklerConfig.isReverse = !this.sprinklerConfig.isReverse;
                // console.log(`[GeoPanel] Sequential click detected. Toggling isReverse to: ${this.sprinklerConfig.isReverse}`);
                if (this.geoDesign.ui) {
                     this.geoDesign.ui.showToast(this.sprinklerConfig.isReverse ? _('Reverse Layout') : _('Forward Layout'), 'info');
                }
            } else {
                // console.log(`[GeoPanel] New feature selected or first click. Setting isReverse to false.`);
                this.sprinklerConfig.isReverse = false; // Reset for new feature
                this._lastGenFeatureId = currentId;
            }

            // Ensure isReverse is explicitly in the passed config
            const fullConfig = {
                ...this.sprinklerConfig,
                isReverse: this.sprinklerConfig.isReverse === true
            };
            // console.log("[GeoPanel] Calling generateSprinklers with config:", fullConfig);
            this.geoDesign.generateSprinklers(this.selectedFeature, fullConfig);
        } else {
            // [New] Drip System Generation
            // console.log("[GeoPanel] Generating Drip Logic...");
            this.geoDesign.modules.generateDrip(this.selectedFeature, this.dripConfig);
        }
    }

    _resetConfigs() {
        // console.log("[GeoPanel] Resetting configs to defaults");
        this.pipeConfig = { spacing: 14.0, angle: 0, offset: 0, is90Deg: false };
        this.sprinklerConfig = { interval: 14.0, radius: 11.0, flow: 850, pressure: 2.0 };
        this.dripConfig = { interval: 0.3, flow: 1.0, pressure: 1.0 };
    }

    /**
     * [New] Premium Animation Helper: Applies splitting classes to buttons
     */
    _applySplitEffect(tierEl) {
        tierEl.classList.add('splitting');
        const buttons = Array.from(tierEl.querySelectorAll('.mode-tab'));
        const activeBtn = buttons.find(b => b.classList.contains('active'));
        if (!activeBtn) return;

        const activeIdx = buttons.indexOf(activeBtn);
        buttons.forEach((btn, idx) => {
            if (idx < activeIdx) btn.classList.add('split-left');
            else if (idx > activeIdx) btn.classList.add('split-right');
        });
    }

    _handleGeometryOp(opId, data = null) {
        if (this.geoDesign && this.geoDesign.handleGeometryOp) {
            this.geoDesign.handleGeometryOp(opId, this.selectedFeature, data);
        }
    }

    /**
     * [Refined] Locks vertical scroll if content fits in panel (<= 2 tiers).
     * Prevents "swipe-to-scroll" on buttons, improving clickability.
     */
    _updateScrollLock() {
        if (!this.viewport) return;
        const totalTiers = this.navStack.length; // Use navStack length as proxy for tiers logic
        if (totalTiers <= 2) {
            this.viewport.style.overflowY = 'hidden';
            this.viewport.scrollTop = 0; // Ensure reset
        } else {
            this.viewport.style.overflowY = 'auto';
        }
    }

    // --- Device Modal Logic ---
    _openDeviceModal(subMode) {
        $('#deviceSelectModal').remove();
        const modalHtml = `
            <div class="modal fade" id="deviceSelectModal" tabindex="-1">
                <div class="modal-dialog" style="max-width: 600px; width: calc(100% - 30px); margin: 30px auto;">
                    <div class="modal-content" style="border-radius: 20px; overflow: hidden; height: auto;">
                        <div class="modal-header border-0 bg-light">
                            <h5 class="modal-title font-weight-bold">${_ (subMode)} ${_('Select')}</h5>
                            <button type="button" class="close" data-dismiss="modal">&times;</button>
                        </div>
                        <div class="modal-body p-4">
                            <input type="text" class="form-control mb-3" id="deviceSearch" placeholder="${_('Search Device...')}" style="height: 38px; border-radius: 19px;">
                            <div id="deviceList" class="list-group" style="max-height: 400px; overflow-y: auto;"></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        this._loadDevices(() => this._renderModalContent(subMode));
        $('#deviceSelectModal').modal('show');
    }

    _loadDevices(callback) {
        if (this.allDevices) {
            if (typeof callback === 'function') callback();
            return;
        }
        $.get('/api/geo/devices', (res) => {
            if (res && res.ok) {
                this.allDevices = res.devices;
                if (typeof callback === 'function') callback();
            }
        });
    }

    _renderModalContent(subMode) {
        const container = document.getElementById('deviceList');
        if (!container || !this.allDevices) return;
        container.innerHTML = '';

        let targetTypes = [subMode];
        if (subMode === 'function') targetTypes = ['function', 'pid', 'trigger', 'conditional', 'custom'];

        const filtered = this.allDevices.filter(d => targetTypes.includes(d.type));

        const uniqueItems = new Map();

        filtered.forEach(dev => {
            // [Fix] Separate Grouping Logic for Inputs and Outputs
            // Outputs: Must show per channel (uuid::ch)
            // Inputs: Currently grouped by Device (Device Unit)
            const isOutput = (dev.type === 'output');
            const isInput = (dev.type === 'input');
            
            // For Outputs, use channel-specific unique_id. For others, maintain device_unique_id grouping if needed,
            // but the user specifically requested channel-level for outputs.
            const key = isOutput ? dev.unique_id : dev.device_unique_id;

            if (!uniqueItems.has(key)) {
                // Construct display item
                uniqueItems.set(key, {
                    ...dev,
                    unique_id: key, 
                    name: dev.name || dev.device_name || 'Unknown Device'
                });
            }
        });
        uniqueItems.forEach(dev => {
            const isOnMap = this.geoDesign.devices && this.geoDesign.devices.isDeviceOnMap(dev.unique_id);
            const item = document.createElement('div');
            item.className = `list-group-item d-flex justify-content-between align-items-center mb-1 border rounded-pill px-4 ${isOnMap ? 'bg-light border-primary' : ''}`;
            item.innerHTML = `
                <span class="font-weight-600">${dev.name}</span>
                <label class="btn-toggle mb-0">
                    <input type="checkbox" class="btn-toggle-input" ${isOnMap ? 'checked' : ''}>
                    <div class="btn-toggle-slider"><div class="btn-toggle-thumb"></div></div>
                </label>
            `;
            item.querySelector('input').onchange = (e) => {
                const checked = e.target.checked;
                if (checked) {
                    this.geoDesign.devices.placeDeviceOnMap(dev);
                    item.classList.add('bg-light', 'border-primary');
                } else {
                    this.geoDesign.devices.removeDeviceFromMap(dev.unique_id);
                    item.classList.remove('bg-light', 'border-primary');
                }
            };
            container.appendChild(item);
        });
    }

    // --- External Navigation Control ---

    setEquipmentSubMode(subMode) {
        // Map tab names if necessary, but currently they match (device, pipe, sprinkler)
        if (['device', 'pipe', 'sprinkler'].includes(subMode)) {
            // Ensure we are in equipment mode
            if (this.currentMode !== 'equipment') this.currentMode = 'equipment';
            this.navStack = ['main', 'equipment', subMode];
            this.render();
        }
    }

    setDeviceSubMode(subMode) {
        if (['input', 'output', 'function'].includes(subMode)) {
            if (this.currentMode !== 'aot_device') this.currentMode = 'aot_device';
            this.navStack = ['main', 'aot_device', subMode];
            this.render();
        }
    }

    getDeviceSubMode() {
        // Check if we are in aot_device and have a 3rd tier
        if (this.currentMode === 'aot_device' && this.navStack.length >= 3) {
            return this.navStack[2];
        }
        return 'input'; // Default
    }

    _handleThemeColorChange(type, color, skipSave = false) {
        // 1. Sync Local State
        if (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) {
            window.AOT_GEO_CONFIG.theme_config[type] = color;
        }
        
        // [New] Sync to GeoDesign instance for map-specific persistence
        if (this.geoDesign) {
            if (!this.geoDesign.theme_config) this.geoDesign.theme_config = {};
            this.geoDesign.theme_config[type] = color;
        }

        // 2. Apply to UI immediately via AoTGeoUI (updates CSS vars, RGB, etc.)
        if (this.geoDesign && this.geoDesign.ui && this.geoDesign.ui.applyThemeConfig) {
            this.geoDesign.ui.applyThemeConfig();
        }
        
        // [New] Instantly update all existing shapes on map
        if (this.geoDesign && this.geoDesign.updateLayerStylesByType) {
            this.geoDesign.updateLayerStylesByType(type, color);
        }
        
        // Refresh panel's active theme color variable
        this._applyThemeColor(this.currentMode);

        if (skipSave) return;

        // 3. Save to Server
        const formData = new FormData();
        formData.append(`theme_${type}`, color);

        // [Fix] Add CSRF Token
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

        fetch('/geo/setting', {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken
            }
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                // console.log(`[GeoPanel] Theme Color (${type}) saved to server.`);
            }
        })
        .catch(err => {
            // console.error(`[GeoPanel] Error saving theme color:`, err);
        });
    }

    _applyThemeColor(mode) {
        // Map mode to CSS variable name (defined in aot-geo-ui.js root vars)
        // Default: --theme-site (#DF5353)
        let themeVar = '--theme-site';
        if (mode === 'zone') themeVar = '--theme-zone';
        else if (mode === 'facility') themeVar = '--theme-facility';
        else if (mode === 'equipment') themeVar = '--theme-equipment';
        else if (mode === 'aot_device') themeVar = '--theme-device';

        // Get actual color value from root to pass to local var
        const rootStyle = getComputedStyle(document.documentElement);
        const color = rootStyle.getPropertyValue(themeVar).trim();

        if (this.container) {
            this.container.style.setProperty('--active-theme-color', color || 'var(' + themeVar + ')');
            
            // [New] Forward RGB and Alpha vars for sub-elements
            const rgb = rootStyle.getPropertyValue(themeVar + '-rgb').trim();
            if (rgb) {
                this.container.style.setProperty('--active-theme-rgb', rgb);
            }
        }

        // [New] Apply Panel Background & Opacity from Global Theme Config
        this._applyPanelTheme();
    }

    _applyPanelTheme() {
        // [Fix] Always Use CSS Variable computed in AoTGeoUI.applyThemeConfig
        // This makes the transition instant and reliable.
        const bgStyle = 'var(--panel-bg-rgba, rgba(255,255,255,0.9))';

        // 1. Apply to Mode Panel (this.container)
        if (this.container) {
            this.container.style.backgroundColor = bgStyle;
            this.container.style.backdropFilter = 'blur(10px)'; // [Premium] Slightly more blur
        }

        // 2. Apply to Map Tools in Geo Design
        // Target standard buttons and specifically the layer control
        const targets = document.querySelectorAll(
            '.map-tools-left .btn, ' + 
            '.map-tools-right .btn, ' + 
            '.map-tools-right .btn-circle, ' +
            '.leaflet-control-zoom-in, ' +
            '.leaflet-control-zoom-out, ' +
            '.leaflet-control-layers, ' + 
            '.leaflet-control-layers-toggle' 
        );

        targets.forEach(el => {
            // Apply if it's a "white" button or a leaflet control
            // Also explicitly check for layer toggle
            if (el.classList.contains('btn-white') || 
                el.classList.contains('bg-white') || 
                el.classList.contains('leaflet-control-layers') ||
                el.classList.contains('leaflet-control-zoom-in') ||
                el.classList.contains('leaflet-control-zoom-out') ||
                el.classList.contains('leaflet-control-layers-toggle')) {
                
                el.style.backgroundColor = bgStyle;
                el.style.borderColor = 'rgba(0,0,0,0.1)';
                el.style.backdropFilter = 'blur(10px)';
            }
        });
    }
}
// Export for global access
window.AoTGeoPanel = AoTGeoPanel;
