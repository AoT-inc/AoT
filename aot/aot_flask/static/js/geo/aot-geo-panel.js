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
        this.isSiteLabelHidden = true;
        this.isZoneLabelHidden = true;
        this.isFacilityLabelHidden = true;
        this.isPipeLabelHidden = true;
        this.isSprinklerPointsHidden = false;
        this.isConnectionPointsHidden = false;

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
        // [MapLibre] Use native DOM events instead of L.DomEvent
        if (this.viewport) {
            // Stop scroll propagation to prevent map zoom
            this.viewport.addEventListener('wheel', (e) => e.stopPropagation(), { passive: true });
            this.viewport.addEventListener('touchmove', (e) => e.stopPropagation(), { passive: true });
            this.viewport.addEventListener('mousedown', (e) => e.stopPropagation());
            this.viewport.addEventListener('click', (e) => e.stopPropagation());
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
                    <div class="mode-tab ${this.currentMode === 'vegetation' ? 'active' : ''}" data-nav-mode="vegetation">${_('Planting')}</div>
                    <div class="mode-tab ${this.currentMode === 'equipment' ? 'active' : ''}" data-nav-mode="equipment">${_('Equipment')}</div>
                    <div class="mode-tab ${this.currentMode === 'aot_device' ? 'active' : ''}" data-nav-mode="aot_device">${_('A')}</div>
                `;
                break;

            case 'site': {
                const config = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const activeColor = config['site'] || '#DF5353';
                html += `
                    <!-- Theme Color Picker (26px Circle) -->
                    <div style="width: 26px; height: 26px; border-radius: 50%; overflow: hidden; border: none; margin: 0 8px 0 4px; flex-shrink: 0; box-shadow: 0 0 0 1px rgba(0,0,0,0.1);">
                        <input type="color" id="theme-color-picker" data-type="site" value="${activeColor}" style="width: 140%; height: 140%; margin: -20%; cursor: pointer; border: none; padding: 0;">
                    </div>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-add-from-address">${_('Add from Address')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline ${this.isSiteLabelHidden ? 'active' : ''}" id="btn-hide-type-label" style="min-width: 70px;">${this.isSiteLabelHidden ? _('Show labels') : _('Hide labels')}</button>
                `;
                break;
            }

            case 'zone': {
                const config = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const activeColor = config['zone'] || '#28a745';
                html += `
                    <!-- Theme Color Picker (26px Circle) -->
                    <div style="width: 26px; height: 26px; border-radius: 50%; overflow: hidden; border: none; margin: 0 8px 0 4px; flex-shrink: 0; box-shadow: 0 0 0 1px rgba(0,0,0,0.1);">
                        <input type="color" id="theme-color-picker" data-type="zone" value="${activeColor}" style="width: 140%; height: 140%; margin: -20%; cursor: pointer; border: none; padding: 0;">
                    </div>
                    <button class="btn btn-aot-pill btn-aot-outline ${this.isZoneLabelHidden ? 'active' : ''}" id="btn-hide-type-label" style="min-width: 70px;">${this.isZoneLabelHidden ? _('Show labels') : _('Hide labels')}</button>
                `;
                break;
            }

            case 'facility': {
                const config = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const activeColor = config['facility'] || '#82898f';
                html += `
                    <!-- Theme Color Picker (26px Circle) -->
                    <div style="width: 26px; height: 26px; border-radius: 50%; overflow: hidden; border: none; margin: 0 8px 0 4px; flex-shrink: 0; box-shadow: 0 0 0 1px rgba(0,0,0,0.1);">
                        <input type="color" id="theme-color-picker" data-type="facility" value="${activeColor}" style="width: 140%; height: 140%; margin: -20%; cursor: pointer; border: none; padding: 0;">
                    </div>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-facility-design">${_('Facility Design')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline ${this.isFacilityLabelHidden ? 'active' : ''}" id="btn-hide-type-label" style="min-width: 70px;">${this.isFacilityLabelHidden ? _('Show labels') : _('Hide labels')}</button>
                `;
                break;
            }

            // --- Tier 2: 식생 구획(작기) ---
            // 색 피커의 data-type 은 'vegetation' — theme_config 의 키와 같아야
            // 하고, 그 기본값은 aot-geo-theme-colors.js 의 DEFAULTS 한 벌뿐이다.
            // 여기에 새 폴백 색을 적지 말 것.
            case 'vegetation': {
                const vegConfig = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const vegColor = vegConfig['vegetation'] ||
                    (window.AoTGeoTheme ? window.AoTGeoTheme.DEFAULTS.vegetation : '#6a8f3c');
                // 그리기·편집·삭제는 **오른쪽 그리기 컨트롤 패널**이 담당한다
                // (다른 도형과 같다). 여기에 같은 기능의 버튼을 또 두면 진입점이
                // 둘로 갈린다. 이 티어에는 종류별 설정(색)만 둔다.
                //
                // 분할은 예외다. 그것은 새 도형을 **그리는** 일이 아니라 이미
                // 그려 둔 구역을 고르는 일이라 그리기 도구에 자리가 없다.
                const veg = this.geoDesign && this.geoDesign.vegetation;
                const hasSplitPreview = !!(veg && veg.hasSplitPreview &&
                                           veg.hasSplitPreview());
                html += `
                    <div style="width: 26px; height: 26px; border-radius: 50%; overflow: hidden; border: none; margin: 0 8px 0 4px; flex-shrink: 0; box-shadow: 0 0 0 1px rgba(0,0,0,0.1);">
                        <input type="color" id="theme-color-picker" data-type="vegetation" value="${vegColor}" style="width: 140%; height: 140%; margin: -20%; cursor: pointer; border: none; padding: 0;">
                    </div>
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-veg-split">${_('Split into plots')}</button>
                `;
                // 미리보기가 떠 있는 동안에만 적용·취소가 나온다. 지도를 가리는
                // 모달이 아니라 여기 두는 이유는, 점선을 **보면서** 정해야 하기
                // 때문이다.
                if (hasSplitPreview) {
                    html += `
                        <button class="btn btn-aot-pill btn-aot-action font-weight-bold" id="btn-veg-split-apply">${_('Create plots')}</button>
                        <button class="btn btn-aot-pill btn-aot-outline" id="btn-veg-split-cancel">${_('Discard preview')}</button>
                        <span class="small text-muted ml-2">${veg.splitSummaryText()}</span>
                    `;
                }
                break;
            }

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
                    <button class="btn btn-aot-pill btn-aot-outline ${this.isPipeLabelHidden ? 'active' : ''}" id="btn-hide-pipe-label" style="min-width: 70px;">${this.isPipeLabelHidden ? _('Show pipe labels') : _('Hide pipe labels')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline ${this.isSprinklerPointsHidden ? 'active' : ''}" id="btn-hide-sprinkler-points" style="min-width: 70px;">${this.isSprinklerPointsHidden ? _('Show sprinklers') : _('Hide sprinklers')}</button>
                    <button class="btn btn-aot-pill btn-aot-outline ${this.isConnectionPointsHidden ? 'active' : ''}" id="btn-hide-connection-points" style="min-width: 70px;">${this.isConnectionPointsHidden ? _('Show joints') : _('Hide joints')}</button>
                `;
                break;

            // --- Tier 2: Aot Device Root ---
            case 'aot_device':
                html += `
                    <div class="mode-tab ${this._isActivePath('input') ? 'active' : ''}" data-nav-sub="input">${_('Input')}</div>
                    <div class="mode-tab ${this._isActivePath('output') ? 'active' : ''}" data-nav-sub="output">${_('Output')}</div>
                    <div class="mode-tab ${this._isActivePath('function') ? 'active' : ''}" data-nav-sub="function">${_('Function')}</div>
                    <div class="mode-tab ${this._isActivePath('device_unit') ? 'active' : ''}" data-nav-sub="device_unit">${_('Device')}</div>
                `;
                // 선택된 구역 폴리곤이 있으면 그 자리의 배정을 바로 연다.
                // 없을 때 버튼만 띄우면 눌러도 "먼저 구역을 고르세요" 밖에 못 한다.
                if (this._selectedAreaShapeId()) {
                    html += `<button class="btn btn-aot-pill btn-aot-action font-weight-bold" id="btn-bind-area">${_('Assign device')}</button>`;
                }
                html += `<button class="btn btn-aot-pill btn-aot-outline" id="btn-unbound-slots">${_('Places with no device')}</button>`;
                break;

            // --- Tier 3: Aot Device Actions ---
            case 'input': case 'output': case 'function':
                const type = tierId;
                
                const appTheme = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};

                // 피커에 표시할 현재 색 — 도형·마커와 같은 규칙으로 해석한다
                // (미설정이면 장치 공통색). 예전에는 여기만 --theme-device
                // computed 값이나 '#9013FE' 같은 별도 폴백을 써서, 피커가 지도에
                // 실제로 칠해진 색과 다른 색을 보여줬다.
                const savedColor = window.AoTGeoTheme.deviceColor(type, appTheme);
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

            // --- Tier 3: Aot Device > 복합장치(Device) ---
            // 티어 id 가 'device' 가 아니라 'device_unit' 인 이유: 'device' 는
            // 아래 Equipment > Device Categories 가 이미 쓰고 있고, 이 switch 는
            // 티어 id 만 보므로 같은 이름을 쓰면 두 화면이 서로를 덮는다.
            //
            // 색 키도 'device_unit' 이다. 'device' 를 쓰면 안 된다 — 그 키는
            // input/output/function 이 미설정일 때 수렴하는 **장치 공통색**
            // 이라, 복합장치 색을 바꾼 것이 나머지 종류의 폴백까지 바꾼다.
            case 'device_unit': {
                const devTheme = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const devColor = window.AoTGeoTheme.deviceColor('device', devTheme);
                const devVis = devTheme['vis_device_unit'];
                const devVisible = (devVis === undefined || devVis === null) ? true : (devVis === 'true' || devVis === true);
                html += `
                    <button class="btn btn-aot-pill btn-aot-outline" id="btn-device-list">${_('Selection list')} ></button>

                    <!-- Color Picker (26px Circle) -->
                    <div style="position: relative; width: 26px; height: 26px; border-radius: 50%; overflow: hidden; border: 1px solid #ddd; margin: 0 4px;">
                        <input type="color" id="device-color-picker" value="${devColor}" style="position: absolute; top: -50%; left: -50%; width: 200%; height: 200%; padding: 0; margin: 0; cursor: pointer;">
                    </div>

                    <label class="switch" style="margin-left: 8px;">
                        <input type="checkbox" id="device-visible-toggle" ${devVisible ? 'checked' : ''}>
                        <span class="slider round"></span>
                    </label>
                `;
                break;
            }

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

    /**
     * 티어 id → **장치 종류**(`collect_devices` 의 `type`).
     *
     * 이 페이지에는 비슷하지만 다른 어휘가 셋 있다. 헷갈리면 목록이 빈 채로
     * 뜨거나 색이 저장되지 않으므로 여기 적어 둔다:
     *
     *   티어 id   input / output / function / device_unit   (패널 내비게이션)
     *   테마 키   input / output / function / device_unit   (티어 id 와 같다)
     *   장치 종류 input / output / function / device        (서버가 내는 값)
     *
     * 즉 **색·표시 설정은 티어 id 를 그대로 쓰고, 장치를 조회할 때만** 이
     * 함수로 바꾼다. 복합장치 티어가 'device' 가 아닌 이유는 그 이름을
     * Equipment > Device Categories 가 이미 쓰기 때문이다.
     */
    _deviceTypeOfTier(tierId) {
        return tierId === 'device_unit' ? 'device' : tierId;
    }

    /**
     * 선택된 도형이 '구역 폴리곤'이면 그 GeoShape.unique_id, 아니면 null.
     *
     * 마커(점)는 제외한다 — 마커는 좌표의 문제이고(/api/geo/device/location),
     * 구역은 소속의 문제다. 프런트에서는 둘 다 aot_type='aot_device' 로 보일
     * 수 있어(get_overlays 가 'device'→'aot_device' 로 정규화한다) 종류
     * 문자열만으로는 갈리지 않는다. 그래서 기하로 가른다.
     */
    _selectedAreaShapeId() {
        const f = this.selectedFeature;
        if (!f || !f.properties) return null;
        const t = f.properties.aot_type;
        if (t !== 'device' && t !== 'aot_device') return null;
        if (f.geometry && f.geometry.type === 'Point') return null;
        const layer = this.geoDesign && this.geoDesign.activeLayer;
        if (layer && typeof layer.getLatLng === 'function'
            && typeof layer.getLatLngs !== 'function') return null;
        // shape_uuid 가 GeoShape.unique_id 다. node_id 는 클라이언트가 만든
        // 값이라 저장된 도형에서는 둘이 다르다 — node_id 를 배정 대상으로
        // 보내면 서버가 그 도형을 찾지 못한다. 아직 저장 전이라 shape_uuid
        // 가 없으면 node_id 로 보내고, 서버가 지도 안에서 찾아 준다.
        return f.properties.shape_uuid || f.properties.node_id || null;
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

        // Address Import (Site tier)
        const btnAddFromAddress = rootEl.querySelector('#btn-add-from-address');
        if (btnAddFromAddress) btnAddFromAddress.onclick = () => {
            const modal = document.getElementById('modal-parcel-import');
            if (modal && window.$) $(modal).modal('show');
        };

        // 식생 분할 (Planting tier) — 계산·그리기는 vegetation 모듈이 한다.
        // 패널은 진입점과 상태 표시만 맡는다.
        const veg = () => this.geoDesign && this.geoDesign.vegetation;
        const btnVegSplit = rootEl.querySelector('#btn-veg-split');
        if (btnVegSplit) btnVegSplit.onclick = () => {
            const v = veg();
            if (v && v.openSplitForm) v.openSplitForm();
        };
        const btnVegSplitApply = rootEl.querySelector('#btn-veg-split-apply');
        if (btnVegSplitApply) btnVegSplitApply.onclick = () => {
            const v = veg();
            if (v && v.applySplit) v.applySplit();
        };
        const btnVegSplitCancel = rootEl.querySelector('#btn-veg-split-cancel');
        if (btnVegSplitCancel) btnVegSplitCancel.onclick = () => {
            const v = veg();
            if (v && v.clearSplitPreview) v.clearSplitPreview();
        };

        // Facility Design navigation (Facility tier)
        const btnFacilityDesign = rootEl.querySelector('#btn-facility-design');
        if (btnFacilityDesign) btnFacilityDesign.onclick = () => { window.location.href = '/geo/facility'; };
        const btnHide = rootEl.querySelector('#btn-hide-label');
        if (btnHide) btnHide.onclick = () => {
            this.isLabelHidden = !this.isLabelHidden;
            this._handleThemeColorChange('hide_label', this.isLabelHidden);
            this._handleGeometryOp('hide-label');
            this.render();
        };

        const btnHideTypeLabel = rootEl.querySelector('#btn-hide-type-label');
        if (btnHideTypeLabel) btnHideTypeLabel.onclick = () => {
            const mode = this.currentMode;
            if (mode === 'site') {
                this.isSiteLabelHidden = !this.isSiteLabelHidden;
            } else if (mode === 'zone') {
                this.isZoneLabelHidden = !this.isZoneLabelHidden;
            } else if (mode === 'facility') {
                this.isFacilityLabelHidden = !this.isFacilityLabelHidden;
            }
            // Use 'hide-label' which routes to _toggleLengthLabels() — length labels only,
            // never touches name labels regardless of mode.
            this._handleGeometryOp('hide-label');
            this.render();
        };

        const btnHidePipeLabel = rootEl.querySelector('#btn-hide-pipe-label');
        if (btnHidePipeLabel) btnHidePipeLabel.onclick = () => {
            this.isPipeLabelHidden = !this.isPipeLabelHidden;
            this._handleGeometryOp('hide-pipe-label');
            this.render();
        };

        const btnHideSp = rootEl.querySelector('#btn-hide-sprinkler-points');
        if (btnHideSp) btnHideSp.onclick = () => {
            this.isSprinklerPointsHidden = !this.isSprinklerPointsHidden;
            this._handleGeometryOp('hide-sprinkler-points', !this.isSprinklerPointsHidden);
            this.render();
        };

        const btnHideConn = rootEl.querySelector('#btn-hide-connection-points');
        if (btnHideConn) btnHideConn.onclick = () => {
            this.isConnectionPointsHidden = !this.isConnectionPointsHidden;
            this._handleGeometryOp('hide-connection-points', !this.isConnectionPointsHidden);
            this.render();
        };

        // Pipe Settings
        const pipeSp = rootEl.querySelector('#pipe-spacing');
        if (pipeSp) {
            pipeSp.oninput = (e) => {
                const v = parseFloat(e.target.value);
                if (!Number.isFinite(v)) return;
                this.pipeConfig.spacing = v;
                this._renderLivePreview();
            };
            pipeSp.onchange = (e) => {
                const v = parseFloat(e.target.value);
                if (!Number.isFinite(v)) return;
                this.pipeConfig.spacing = v;
                this._commitFromLivePreview();
            };
        }

        const pipeAng = rootEl.querySelector('#pipe-angle');
        if (pipeAng) {
            pipeAng.oninput = (e) => {
                this.pipeConfig.angle = parseInt(e.target.value);
                const val = rootEl.querySelector('#val-angle');
                if (val) val.innerText = `${this.pipeConfig.angle}°`;
                this._renderLivePreview();
            };
            pipeAng.onchange = (e) => {
                this._commitFromLivePreview();
            };
        }

        const pipeOff = rootEl.querySelector('#pipe-offset');
        if (pipeOff) {
            pipeOff.oninput = (e) => {
                this.pipeConfig.offset = parseFloat(e.target.value);
                const val = rootEl.querySelector('#val-offset');
                if (val) val.innerText = `${this.pipeConfig.offset}m`;
                this._renderLivePreview();
            };
            pipeOff.onchange = (e) => {
                this._commitFromLivePreview();
            };
        }

        // Pipe Actions
        const btn90 = rootEl.querySelector('#btn-90deg');
        if (btn90) btn90.onclick = () => {
            // [Fix] Toggle 90-degree offset flag ONLY.
            // Backend handles (angle + 90) logic. Incrementing angle here caused 180deg total turn.
            this.pipeConfig.is90Deg = !this.pipeConfig.is90Deg;

            this.render();
            this._commitFromLivePreview();
        };
        const btnRef = rootEl.querySelector('#btn-draw-ref');
        if (btnRef) btnRef.onclick = () => this.geoDesign.startDraw('polyline', { type: 'ref_line' });
        const btnMainP = rootEl.querySelector('#btn-draw-main');
        if (btnMainP) btnMainP.onclick = () => this.geoDesign.startDraw('polyline', { type: 'main_pipe' });
        const btnGenPipes = rootEl.querySelector('#btn-gen-pipe');
        if (btnGenPipes) btnGenPipes.onclick = () => this._commitFromLivePreview();
        const btnClear = rootEl.querySelectorAll('#btn-clear-equip');
        btnClear.forEach(btn => {
            btn.onclick = () => {
                // [Fix] Robust Mode Detection via Attribute
                const mode = btn.dataset.clearMode || 'all';
                this._handleGeometryOp('clear-equip', mode);
                // Navigate back to equipment root after reset
                // clearMode='all' clears pipes + sprinklers (cascade), 'sprinkler' clears only sprinklers
                if (this.navStack.length > 2) this._popTier();
            };
        });

        // Irrigation Toggles
        const btnSetSp = rootEl.querySelector('#btn-set-sprinkler');
        if (btnSetSp) btnSetSp.onclick = () => { this.irrigationType = 'sprinkler'; this.render(); };

        const btnSetDr = rootEl.querySelector('#btn-set-drip');
        if (btnSetDr) btnSetDr.onclick = () => { this.irrigationType = 'drip'; this.render(); };

        // Irrigation Inputs — preview-only on every keystroke; commit (irrigation
        // scope only) on blur/Enter so we don't redundantly regen pipes.
        ['interval', 'radius', 'flow', 'pressure'].forEach(key => {
            const el = rootEl.querySelector(`[id="sp-${key}"]`);
            if (el) {
                el.oninput = (e) => {
                    const v = parseFloat(e.target.value);
                    if (!Number.isFinite(v)) return;
                    this.sprinklerConfig[key] = v;
                    this._renderLivePreview();
                };
                el.onchange = (e) => {
                    const v = parseFloat(e.target.value);
                    if (!Number.isFinite(v)) return;
                    this.sprinklerConfig[key] = v;
                    this._commitFromLivePreview('irrigation');
                };
            }

            const elD = rootEl.querySelector(`[id="dp-${key}"]`);
            if (elD) {
                elD.oninput = (e) => {
                    const v = parseFloat(e.target.value);
                    if (!Number.isFinite(v)) return;
                    this.dripConfig[key] = v;
                    this._renderLivePreview();
                };
                elD.onchange = (e) => {
                    const v = parseFloat(e.target.value);
                    if (!Number.isFinite(v)) return;
                    this.dripConfig[key] = v;
                    this._commitFromLivePreview('irrigation');
                };
            }
        });

        // Generate Irrigation button — explicit user intent: hide preview, commit irrigation.
        const btnGenIrr = rootEl.querySelector('#btn-gen-irrigation');
        if (btnGenIrr) btnGenIrr.onclick = () => {
            const preview = this._getPreview();
            if (preview) preview.hide();
            this._triggerIrrigationGen(); // allow reverse-toggle on real button click
        };

        // Device Modal
        const btnList = rootEl.querySelector('#btn-device-list');
        if (btnList) btnList.onclick = () => {
            // Determine subMode from navStack (it's the current tier)
            const subMode = this.navStack[this.navStack.length - 1]; // e.g., 'input'
            this._openDeviceModal(subMode);
        };

        // 공간 슬롯 ↔ 장치 배정 (geo_binding). 좌표를 다루는 위 목록과 다른 축이다.
        const btnBindArea = rootEl.querySelector('#btn-bind-area');
        if (btnBindArea) btnBindArea.onclick = () => {
            const shapeId = this._selectedAreaShapeId();
            if (!shapeId || !this.geoDesign || !this.geoDesign.binding) return;
            const props = (this.selectedFeature && this.selectedFeature.properties) || {};
            this.geoDesign.binding.openForShape(shapeId, {
                name: props.label_name || props.name || ''
            });
        };

        const btnUnbound = rootEl.querySelector('#btn-unbound-slots');
        if (btnUnbound) btnUnbound.onclick = () => {
            if (this.geoDesign && this.geoDesign.binding) {
                this.geoDesign.binding.openUnboundSlots();
            }
        };

        // 식생 — 패널에서 바로 그리기. 우측 툴바를 찾지 않아도 되게 한다.
        // 상위 zone 은 고르지 않는다: 그냥 그리면 서버가 공간 포함으로
        // 판정한다(equipment 와 같은 모델).
        // Device Color Picker (Input/Output/Function)
        const deviceColorPicker = rootEl.querySelector('#device-color-picker');
        if (deviceColorPicker) {
            deviceColorPicker.oninput = (e) => {
                const color = e.target.value;
                const subMode = this.navStack[this.navStack.length - 1]; // e.g., 'input'
                if (this.geoDesign && this.geoDesign.setDeviceLabelColor) {
                    this.geoDesign.setDeviceLabelColor(subMode, color);
                }
                // [Fix] 'change' 미발화 시에도 저장되도록 디바운스 자동저장 등록
                this._handleThemeColorChange(subMode, color, true);
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
                // 티어 id 가 곧 테마 키다(input/output/function/device_unit).
                // 여기서 장치 종류('device')로 바꾸면 저장 키와 렌더 키가
                // 갈려, 토글은 먹는데 새로고침하면 되돌아온다.
                const key = this.navStack[this.navStack.length - 1];
                this._handleThemeColorChange(`vis_${key}`, isVisible);
                if (this.geoDesign && this.geoDesign.setDeviceVisibility) {
                    this.geoDesign.setDeviceVisibility(key, isVisible);
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

        // Pass the live sprinkler config so auto-regen can recover when the
        // parent's saved gen_config_sprinkler is missing or stale — this is
        // what keeps sprinklers from disappearing when pipe spacing changes.
        // reloadAfter: after server save, full re-fetch + re-render so the new
        // pipes/sprinklers appear immediately (fixes "must refresh page" bug).
        this.geoDesign.generatePipes(this.selectedFeature, this.pipeConfig, {
            sprinklerConfigFallback: this.sprinklerConfig,
            reloadAfter: true
        });
    }

    /* ---------- Live Preview (client-side, no server roundtrip) ---------- */

    /** Lazy-construct the AoTGeoPreview overlay tied to the active map. */
    _getPreview() {
        if (!window.AoTGeoPreview) return null;
        if (!this._preview) {
            try { this._preview = new window.AoTGeoPreview(this.geoDesign); }
            catch (e) { this._preview = null; }
        }
        return this._preview;
    }

    /** Returns the irrigation config that should be reflected by the preview, or null. */
    _activeIrrigationConfigForPreview() {
        // Only show irrigation overlay while the user is on the Irrigation tier.
        // On the Pipe tier we just preview pipes (sprinklers stay as their saved render).
        const onIrrigationTier = this.navStack && this.navStack.includes('sprinkler');
        if (!onIrrigationTier) return null;
        return this.irrigationType === 'drip' ? this.dripConfig : this.sprinklerConfig;
    }

    /**
     * Render the transient preview from the current configs. Safe to call on
     * every keystroke / drag tick — it only updates GeoJSON sources, no server
     * call, no layerStorage mutation.
     */
    _renderLivePreview() {
        const preview = this._getPreview();
        if (!preview) return;
        if (!this.selectedFeature) return;
        const t = this.selectedFeature.properties && this.selectedFeature.properties.aot_type;
        if (t !== 'site' && t !== 'zone') return;

        const irrConfig = this._activeIrrigationConfigForPreview();
        const irrType = irrConfig ? this.irrigationType : null;
        try {
            preview.show(this.selectedFeature, this.pipeConfig, irrConfig, irrType);
        } catch (e) {
            // Preview must never throw out of an input handler.
        }
    }

    /**
     * Slider released / Enter pressed / Generate button clicked: drop the
     * preview overlay and run the real server-backed generation so persisted
     * geometry matches what the user just previewed.
     *
     * scope:
     *   'pipe' (default) — promote the *exact* preview pipes to persisted
     *                      layers via AoTGeoPreview.commitPipes(). This
     *                      bypasses /api/geo/generate-pipes entirely so the
     *                      committed state can never diverge from the preview
     *                      that was on screen.
     *   'irrigation'    — regenerate sprinklers/drip only, leave pipes as-is.
     *
     * After commit, a full _loadAllFeatures runs (same code path a page
     * refresh uses). The reload replaces every layer instance, so we capture
     * the current selection's node_id and re-bind it once loading completes —
     * otherwise selectedFeature would point at a detached layer and the next
     * edit would silently no-op.
     */
    _commitFromLivePreview(scope) {
        const preview = this._getPreview();
        const targetNodeId = this.selectedFeature && this.selectedFeature.properties
            && this.selectedFeature.properties.node_id;

        if (scope === 'irrigation') {
            if (preview) preview.hide();
            this._triggerIrrigationGen({ skipReverseToggle: true });
        } else if (preview && this.selectedFeature) {
            const t = this.selectedFeature.properties && this.selectedFeature.properties.aot_type;
            if (t !== 'site' && t !== 'zone') {
                if (this.geoDesign.ui) this.geoDesign.ui.showToast(_('Branch pipe requires Zone or Site.'), 'warning');
                return;
            }
            // Direct commit-from-preview: same client-side compute the user
            // saw, no server roundtrip, no rendering race.
            preview.commitPipes(this.selectedFeature, this.pipeConfig, {
                sprinklerConfigFallback: this.sprinklerConfig,
                reloadAfter: true
            }).catch(() => { /* errors surfaced via toast inside commitPipes */ });
        } else {
            // Preview unavailable (e.g. AoTGeoPreview failed to construct):
            // fall back to the legacy server-backed path.
            this._triggerPipeGen();
        }

        if (targetNodeId) this._scheduleReSelect(targetNodeId);
    }

    /**
     * Poll for the post-commit reload to finish, then re-select the same
     * Site/Zone so panel.selectedFeature points at the live, freshly-rendered
     * layer instance. Safe to call multiple times — each call cancels the
     * previous polling cycle.
     */
    _scheduleReSelect(nodeId) {
        if (this._reselectTimer) clearInterval(this._reselectTimer);
        if (this._reselectGiveUpTimer) clearTimeout(this._reselectGiveUpTimer);

        const start = Date.now();
        const poll = () => {
            if (Date.now() - start > 6000) {
                clearInterval(this._reselectTimer);
                this._reselectTimer = null;
                return;
            }
            // Wait for the load cycle that follows save to finish.
            if (this.geoDesign && this.geoDesign.isLoading) return;

            const layer = this._findLayerByNodeId(nodeId);
            if (!layer) return; // Reload may not have re-added it yet.

            clearInterval(this._reselectTimer);
            this._reselectTimer = null;
            try {
                if (typeof this.geoDesign._setActiveLayer === 'function') {
                    this.geoDesign._setActiveLayer(layer);
                }
                // _setActiveLayer typically re-renders the panel via this.panel.render(...).
                // Belt-and-suspenders: make sure selectedFeature is bound to the live layer.
                this.selectedFeature = layer.feature;
            } catch (e) { /* ignore */ }
        };
        this._reselectTimer = setInterval(poll, 150);
        // Hard ceiling to avoid leaking intervals if reload never happens.
        this._reselectGiveUpTimer = setTimeout(() => {
            if (this._reselectTimer) {
                clearInterval(this._reselectTimer);
                this._reselectTimer = null;
            }
        }, 6500);
    }

    /** Search every storage group for a layer with the given node_id. */
    _findLayerByNodeId(nodeId) {
        if (!nodeId || !this.geoDesign) return null;
        // Prefer the geometry helper if present — knows about all containers.
        try {
            if (this.geoDesign.geometry && typeof this.geoDesign.geometry._findLayerByUuid === 'function') {
                const l = this.geoDesign.geometry._findLayerByUuid(nodeId);
                if (l) return l;
            }
        } catch (e) {}
        const storage = this.geoDesign.layerStorage || {};
        for (const key of Object.keys(storage)) {
            const group = storage[key];
            if (!group || typeof group.eachLayer !== 'function') continue;
            let found = null;
            try {
                group.eachLayer(l => {
                    if (found) return;
                    if (l.feature && l.feature.properties && l.feature.properties.node_id === nodeId) {
                        found = l;
                    }
                });
            } catch (e) {}
            if (found) return found;
        }
        // Editor featureGroup as last resort.
        if (window.AoTMapEditor && window.AoTMapEditor.featureGroup) {
            let found = null;
            try {
                window.AoTMapEditor.featureGroup.eachLayer(l => {
                    if (found) return;
                    if (l.feature && l.feature.properties && l.feature.properties.node_id === nodeId) {
                        found = l;
                    }
                });
            } catch (e) {}
            if (found) return found;
        }
        return null;
    }

    _triggerIrrigationGen(opts = {}) {
        if (!this.selectedFeature) {
            if (this.geoDesign.ui) this.geoDesign.ui.showToast(_('Please select a Zone first.'), 'warning');
            return;
        }

        const currentId = this.selectedFeature.properties?.node_id;
        // console.log(`[GeoPanel] Triggering Gen for: ${currentId}. Last Gen ID: ${this._lastGenFeatureId}`);

        if (this.irrigationType === 'sprinkler') {
            // Reverse-toggle is reserved for explicit Generate button presses only.
            // Live config-edit calls (slider/number input) must NOT flip layout direction.
            if (!opts.skipReverseToggle) {
                if (this._lastGenFeatureId === currentId) {
                    this.sprinklerConfig.isReverse = !this.sprinklerConfig.isReverse;
                    if (this.geoDesign.ui) {
                         this.geoDesign.ui.showToast(this.sprinklerConfig.isReverse ? _('Reverse Layout') : _('Forward Layout'), 'info');
                    }
                } else {
                    this.sprinklerConfig.isReverse = false; // Reset for new feature
                    this._lastGenFeatureId = currentId;
                }
            } else {
                // Live preview: keep tracking the feature so the next manual click behaves correctly,
                // but never mutate isReverse here.
                this._lastGenFeatureId = currentId;
            }

            // Ensure isReverse is explicitly in the passed config
            const fullConfig = {
                ...this.sprinklerConfig,
                isReverse: this.sprinklerConfig.isReverse === true
            };
            // reloadAfter=true so the page reflects the saved sprinklers
            // immediately without a manual refresh.
            this.geoDesign.generateSprinklers(this.selectedFeature, fullConfig, true, { reloadAfter: true });
        } else {
            // Drip System Generation — same: reload after save commits.
            this.geoDesign.modules.generateDrip(this.selectedFeature, this.dripConfig, { reloadAfter: true });
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
                            <h5 class="modal-title font-weight-bold">${subMode === 'device_unit' ? _('Device') : _(subMode)} ${_('Select')}</h5>
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

        let targetTypes = [this._deviceTypeOfTier(subMode)];
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
        if (['input', 'output', 'function', 'device_unit'].includes(subMode)) {
            if (this.currentMode !== 'aot_device') this.currentMode = 'aot_device';
            this.navStack = ['main', 'aot_device', subMode];
            this.render();
        }
    }

    getDeviceSubMode() {
        // Check if we are in aot_device and have a 3rd tier
        // 티어 id 가 아니라 **장치 종류**를 돌려준다 — 호출자가 이 값을
        // feature.properties.device_type 에 그대로 심기 때문이다.
        if (this.currentMode === 'aot_device' && this.navStack.length >= 3) {
            return this._deviceTypeOfTier(this.navStack[2]);
        }
        return 'input'; // Default
    }

    _handleThemeColorChange(type, color, skipSave = false) {
        // 1. Sync Local State
        if (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) {
            window.AOT_GEO_CONFIG.theme_config[type] = color;
        }

        // 지도별 theme_config 축적은 제거했다. 색은 전역(GeoSetting.theme_config)
        // 한 곳에만 저장한다 — 예전에는 여기서 쌓인 부분 dict 가 지도 저장 때
        // GeoMap.state_json 에 함께 기록돼, 그 지도를 쓰는 위젯이 전역 대신
        // 그 옛 색을 따르는 갈래가 생겼다.

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

        // [Fix] 색상 저장이 오직 native <input type=color> 의 'change' 이벤트에만
        // 의존하면, 사용자가 피커를 닫으며 다른 곳(탭 전환·지도 클릭 등)을 눌러
        // 브라우저가 change 를 못 쐈을 때 조용히 저장이 스킵되고, 새로고침하면
        // 이전 색으로 "복구"된 것처럼 보이는 버그가 있었다. 'input'(실시간
        // 드래그 중) 에도 디바운스 자동저장을 걸어, change 유무와 무관하게
        // 사용자가 손을 뗀 뒤 잠깐 뒤엔 항상 서버에 반영되도록 이중 안전장치.
        if (skipSave) {
            if (!this._themeSaveDebounce) this._themeSaveDebounce = {};
            clearTimeout(this._themeSaveDebounce[type]);
            this._themeSaveDebounce[type] = setTimeout(() => {
                this._saveThemeColorToServer(type, color);
            }, 400);
            return;
        }

        if (this._themeSaveDebounce) clearTimeout(this._themeSaveDebounce[type]);
        this._saveThemeColorToServer(type, color);
    }

    _saveThemeColorToServer(type, color) {
        const formData = new FormData();
        formData.append(`theme_${type}`, color);

        // [Fix] Add CSRF Token
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

        fetch('/api/geo/settings', {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken
            }
        })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (!ok || !data.ok) {
                if (window.showToast) {
                    window.showToast((data && data.message) || (_('Failed to save theme color') || 'Failed to save theme color'), 'error');
                }
            }
        })
        .catch(err => {
            if (window.showToast) {
                window.showToast(_('Failed to save theme color') || 'Failed to save theme color', 'error');
            }
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
