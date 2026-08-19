class AoTGeoPanel {
    constructor(containerId, geoDesign) {
        // 하단 가로바 — **모드 탭('main' tier)만** 여기 남는다.
        this.container = document.getElementById('nav-mode-panel');
        this.viewport = document.getElementById('nav-tier-viewport');
        // 모드별 설정 tier 는 지도를 가리지 않는 오른쪽 드로어로 간다
        // (골격: geo_design.html 의 #geo-settings-drawer, 스타일·열림동작은
        // aot-modal-modern.css / common/aot-widget-drawer.js 공용).
        this.drawer = document.getElementById('geo-settings-drawer');
        this.drawerBody = document.getElementById('geo-settings-drawer-body');
        this.drawerTitle = document.getElementById('geo-settings-drawer-title');
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
            // ── 두 곳에 나눠 그린다 ──────────────────────────────────────
            //
            //   하단 가로바 : 'main' tier(모드 탭)만. **항상** 보인다.
            //   설정 드로어 : 그 모드의 설정 tier(index 1 이상).
            //
            // 예전에는 둘 다 하단바 2줄에 욱여넣었다. 그래서 배관 각도 슬라이더는
            // min-width 320px 를 잡아야 했고, 식생 분할은 자리가 없어 지도를 덮는
            // 모달로 빠져 있었다 — 설정을 만지는 동안 그 결과를 볼 수 없다는 것이
            // 문제였다. 드로어는 지도를 덮지 않고 밀어내므로 둘 다 해결된다.
            //
            // 모드 전환 슬라이드 애니메이션도 함께 걷어냈다. 그것은 하단바가
            // 얕은/깊은 tier 사이를 갈아끼울 때 쓰던 것인데, 이제 하단바 내용은
            // 모드 탭 하나로 고정이라 갈아끼울 것이 없다(드로어는 자기 슬라이드가
            // 있다).
            this.viewport.innerHTML = '';
            this.viewport.appendChild(this._buildTier({ id: 'main', index: 0 }));

            // 설정 tier: navStack[1] 이 모드, 그보다 깊으면 잎(leaf)까지 둘.
            // 예전에는 simple(site/zone/facility)과 complex(equipment 등)를 갈라
            // 처리했는데, 하단바에서 'main' 을 빼고 나니 둘이 같은 모양이 된다.
            const settingsTiers = [];
            if (this.navStack.length > 1) {
                settingsTiers.push({ id: this.navStack[1], index: 1 });
                if (this.navStack.length > 2) {
                    const leafIndex = this.navStack.length - 1;
                    // 되돌아갈 중간 tier 가 있을 때만 뒤로 버튼을 낸다. 예전에는
                    // tier 1 에 "모드 목록으로" 버튼이 있었지만, 모드 탭이 이제
                    // 하단바에 늘 떠 있으므로 그 버튼은 갈 곳이 없어졌다.
                    settingsTiers.push({
                        id: this.navStack[leafIndex],
                        index: leafIndex,
                        isBack: this.navStack.length > 3,
                    });
                }
            }

            if (this.drawerBody) {
                this.drawerBody.innerHTML = '';
                settingsTiers.forEach(t => this.drawerBody.appendChild(this._buildTier(t)));
            }
            if (this.drawerTitle) {
                this.drawerTitle.textContent = this._modeLabel(this.currentMode);
            }
            // 설정이 없는 상태(모드 미선택)에서 드로어가 열려 있으면 빈 창이 남는다.
            if (!settingsTiers.length) this.closeSettings();

            this.lastStack = [...this.navStack];
        } catch (e) {
            // console.error("[AoTGeoPanel] Render Error:", e);
            this.viewport.innerHTML = `<div class="text-danger p-2 small">Render Error: ${e.message}</div>`;
        }
    }

    /** tier 하나를 DOM 으로. 하단바와 드로어가 같은 골격을 쓴다. */
    _buildTier({ id, index, isBack }) {
        const tierEl = document.createElement('div');
        tierEl.className = 'nav-tier';
        tierEl.dataset.tierId = id;
        tierEl.dataset.index = index;

        let content = this._getTierContent(id, index);
        if (isBack) {
            content = '<div class="btn-nav-back" data-nav-action="back">' +
                      '<i class="fas fa-arrow-up"></i></div>' + content;
        }
        tierEl.innerHTML = `<div class="nav-tier-inner">${content}</div>`;

        this._attachDragScroll(tierEl);
        this._bindNavEvents(tierEl);
        // 분할 폼은 자기 입력들을 스스로 배선한다(라이브 미리보기까지).
        // tier id 로 판정하지 않는다 — 분할 폼은 'plot' tier 안에 바로
        // 이어 붙으므로(더 이상 별도 'split' tier 가 아니다), 내용에 그 폼의
        // 표식(zone_id select)이 있는지로 판정하는 편이 실제로 맞다.
        const veg = this.geoDesign && this.geoDesign.plot;
        if (veg && veg.bindSplitPanel && tierEl.querySelector('[data-veg-split="zone_id"]')) {
            veg.bindSplitPanel(tierEl);
        }
        const ds = this.geoDesign && this.geoDesign.deviceSplit;
        if (ds && ds.bindPanel && tierEl.querySelector('[data-devsplit="zone_id"]')) {
            ds.bindPanel(tierEl);
        }
        return tierEl;
    }

    /** 드로어 제목에 쓰는 모드 이름 — 하단바 탭과 같은 문구를 쓴다. */
    _modeLabel(mode) {
        const labels = {
            site: _('Site'), zone: _('Zone'), facility: _('Facility'),
            plot: _('Plot'), equipment: _('Equipment'),
            aot_device: _('A'),
        };
        return labels[mode] || _('Settings');
    }

    /**
     * 설정 드로어를 연다.
     *
     * **첫 렌더에서는 부르지 않는다** — 페이지를 열자마자 지도가 드로어 폭만큼
     * 밀려 있으면 지도를 보러 온 사람에게 설명되지 않는다. 모드 탭을 실제로
     * 누를 때만 연다(`_bindNavEvents` 의 `data-nav-mode` 핸들러).
     */
    openSettings() {
        if (!this.drawer || !window.jQuery) return;
        if (!this.drawerBody || !this.drawerBody.children.length) return;
        window.jQuery(this.drawer).modal('show');
    }

    closeSettings() {
        if (!this.drawer || !window.jQuery) return;
        window.jQuery(this.drawer).modal('hide');
    }

    // ── 드로어 마크업 헬퍼 ──────────────────────────────────────────────
    //
    // 설정이 하단 가로바에 있던 시절에는 자리가 없어 라벨을 지우고(11px 회색
    // 글씨), 값 칸을 50px 로 줄이고, 토글은 눌릴 때마다 글자가 바뀌는 pill 로
    // 압축했다. 드로어(520px 세로)는 그럴 이유가 없다 — geo/facility 설정과
    // 같은 골격(`aot-modal-group-title` + `aot-modal-container` +
    // `aot-modal-option-row`)으로 라벨과 값을 나란히 둔다.
    //
    // ⚠ 여기서 만드는 요소의 **id 와 data 속성은 바꾸지 말 것.** `_bindNavEvents`
    //   가 그것으로 찾는다 — 겉모습만 바꾸고 동작은 그대로 두는 것이 이 헬퍼의 목적이다.

    /** 설정 묶음 제목. */
    _group(title) {
        return `<div class="aot-modal-group-title">${title}</div>`;
    }

    /**
     * 라벨 + 컨트롤 한 줄. `hint` 는 라벨 아래 설명.
     *
     * 버튼 묶음이 들어오면 줄을 **세로로 쌓는다** — 버튼 서너 개를 라벨 옆
     * 좁은 칸에 밀어 넣으면 오른쪽에서 어색하게 감긴다.
     */
    _row(label, control, hint) {
        const stack = control.indexOf('aot-geo-btn-row') !== -1
            ? ' aot-geo-row-stack' : '';
        return `
            <div class="aot-modal-option-row${stack}">
                <div class="aot-modal-option-label">${label}${
                    hint ? `<div class="aot-modal-body-text">${hint}</div>` : ''}</div>
                <div class="aot-modal-option-control">${control}</div>
            </div>`;
    }

    /** 색 피커 한 줄 — 예전에는 라벨 없는 26px 동그라미만 떠 있었다. */
    _colorRow(id, attrs, value, label) {
        return this._row(label || _('Colour'),
            `<input type="color" class="aot-geo-color-input" id="${id}" ${attrs}
                    value="${value}">`);
    }

    /**
     * 켜고 끄는 스위치 한 줄 — 눌릴 때마다 글자가 바뀌는 pill 을 대신한다.
     *
     * 골격은 공용 토글(`components/aot-toggle.css` 의 `.btn-toggle`)이다.
     * layout 이 전역으로 싣고 설정 화면들이 이미 이것을 쓴다 — 이 페이지에만
     * 있는 `.switch`(aot-base-ui.css) 를 쓰면 같은 뜻의 스위치가 화면마다
     * 다르게 생긴다.
     */
    _switchRow(id, checked, label, hint, attrs) {
        return this._row(label,
            `<label class="btn-toggle mb-0">
                 <input type="checkbox" class="btn-toggle-input" id="${id}"
                        ${attrs || ''} ${checked ? 'checked' : ''}>
                 <span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>
             </label>`, hint);
    }

    /**
     * 그 종류의 도형을 지도에서 보일지 — 모드마다 같은 자리에 둔다.
     *
     * 길이 라벨 토글과 짝이 되는 스위치다(라벨만 끄는 것과 도형째 감추는 것은
     * 다른 요구다 — 다른 모드를 손볼 때 이 모드 도형이 눈에 걸리지 않게 한다).
     * 저장 키는 `vis_shape_<type>` 로, 장치 쪽 `vis_<type>` 와 겹치지 않는다.
     */
    _shapeVisibilityRow(type) {
        const cfg = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config)
            ? window.AOT_GEO_CONFIG.theme_config : {};
        const saved = cfg[`vis_shape_${type}`];
        const visible = (saved === undefined || saved === null)
            ? true : (saved === 'true' || saved === true);
        return this._switchRow('shape-visible-toggle', visible, _('Show on map'),
            _('Hides this kind of shape while you work on another mode.'),
            `data-shape-type="${type}"`);
    }

    /** 숫자 입력 한 줄. `unit` 은 값 뒤에 붙는 단위. */
    _numberRow(id, value, label, unit, step) {
        return this._row(label,
            `<div class="aot-geo-input-unit">
                 <input type="number" class="aot-modern-input form-control"
                        id="${id}" value="${value}"${step ? ` step="${step}"` : ''}>
                 ${unit ? `<span class="aot-geo-unit">${unit}</span>` : ''}
             </div>`);
    }

    /** 슬라이더 한 줄 — 값이 라벨 옆에 함께 뜬다. */
    _sliderRow(id, valueId, value, label, unit, min, max, step) {
        return this._row(
            `${label} <span class="aot-geo-slider-value" id="${valueId}">${value}${unit}</span>`,
            `<input type="range" class="custom-range" id="${id}"
                    min="${min}" max="${max}" step="${step}" value="${value}">`);
    }

    /** 버튼·탭을 감싸는 줄 — 드로어에서 자연스럽게 감싸도록 한다. */
    _btnRow(inner) {
        return `<div class="aot-geo-btn-row">${inner}</div>`;
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
                    <div class="mode-tab ${this.currentMode === 'plot' ? 'active' : ''}" data-nav-mode="plot">${_('Plot')}</div>
                    <div class="mode-tab ${this.currentMode === 'equipment' ? 'active' : ''}" data-nav-mode="equipment">${_('Equipment')}</div>
                    <div class="mode-tab ${this.currentMode === 'aot_device' ? 'active' : ''}" data-nav-mode="aot_device">${_('A')}</div>
                `;
                break;

            case 'site': {
                const config = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const activeColor = config['site'] || '#DF5353';
                html += this._group(_('Basic settings')) +
                    `<div class="aot-modal-container">` +
                    this._colorRow('theme-color-picker', 'data-type="site"', activeColor) +
                    this._shapeVisibilityRow('site') +
                    this._switchRow('btn-hide-type-label', !this.isSiteLabelHidden,
                                    _('Show length labels'),
                                    _('Shows the measured length of each edge on the map.')) +
                    this._row(_('Add from Address'),
                        `<button class="btn aot-pill-btn" id="btn-add-from-address">${
                            _('Search')}</button>`,
                        _('Looks up a parcel by address and draws its boundary for you.')) +
                    `</div>`;
                break;
            }

            case 'zone': {
                const config = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const activeColor = config['zone'] || '#28a745';
                html += this._group(_('Basic settings')) +
                    `<div class="aot-modal-container">` +
                    this._colorRow('theme-color-picker', 'data-type="zone"', activeColor) +
                    this._shapeVisibilityRow('zone') +
                    this._switchRow('btn-hide-type-label', !this.isZoneLabelHidden,
                                    _('Show length labels'),
                                    _('Shows the measured length of each edge on the map.')) +
                    `</div>`;
                break;
            }

            case 'facility': {
                const config = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const activeColor = config['facility'] || '#82898f';
                html += this._group(_('Basic settings')) +
                    `<div class="aot-modal-container">` +
                    this._colorRow('theme-color-picker', 'data-type="facility"', activeColor) +
                    this._shapeVisibilityRow('facility') +
                    this._switchRow('btn-hide-type-label', !this.isFacilityLabelHidden,
                                    _('Show length labels'),
                                    _('Shows the measured length of each edge on the map.')) +
                    this._row(_('Facility Design'),
                        `<button class="btn aot-pill-btn" id="btn-facility-design">${
                            _('Open')}</button>`,
                        _('Design the structure, covering and actuators of the selected facility.')) +
                    `</div>`;
                break;
            }

            // --- Tier 2: 식생 구획(작기) ---
            // 색 피커의 data-type 은 'plot' — theme_config 의 키와 같아야
            // 하고, 그 기본값은 aot-geo-theme-colors.js 의 DEFAULTS 한 벌뿐이다.
            // 여기에 새 폴백 색을 적지 말 것.
            case 'plot': {
                const vegConfig = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const vegColor = vegConfig['plot'] ||
                    (window.AoTGeoTheme ? window.AoTGeoTheme.DEFAULTS.plot : '#6a8f3c');
                // 그리기·편집·삭제는 **오른쪽 그리기 컨트롤 패널**이 담당한다
                // (다른 도형과 같다). 여기에 같은 기능의 버튼을 또 두면 진입점이
                // 둘로 갈린다. 이 티어에는 종류별 설정(색)만 둔다.
                //
                // **분할 폼은 "열기" 버튼 없이 바로 이어 붙인다.** 예전에는
                // 여기 "구획으로 나누기 → 열기" 버튼이 있어 별도 tier 로
                // 들어가야 했는데, 식생 드로어를 여는 것 자체가 대개 분할을
                // 하려는 것이다 — 버튼을 한 번 더 누르게 하는 것은 중복이다.
                // 내용·배선은 여전히 plot 모듈이 쥔다(폼이 지도의 미리보기
                // 점선·기준선과 한 몸이라 패널이 흉내 낼 수 있는 것이 아니다).
                html += this._group(_('Basic settings')) +
                    `<div class="aot-modal-container">` +
                    this._colorRow('theme-color-picker', 'data-type="plot"', vegColor) +
                    this._shapeVisibilityRow('plot') +
                    `</div>`;
                const veg = this.geoDesign && this.geoDesign.plot;
                html += (veg && veg.splitPanelHtml) ? veg.splitPanelHtml() : '';
                break;
            }

            // --- Tier 2: Equipment Root ---
            case 'equipment':
                const eqConfig = (window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.theme_config) ? window.AOT_GEO_CONFIG.theme_config : {};
                const eqColor = eqConfig['equipment'] || '#007bff';

                html += this._group(_('Basic settings')) +
                    `<div class="aot-modal-container">` +
                    this._colorRow('theme-color-picker', 'data-type="equipment"', eqColor) +
                    this._shapeVisibilityRow('equipment') +
                    this._row(_('What to place'), this._btnRow(`
                        <div class="mode-tab ${this._isActivePath('device') ? 'active' : ''}" data-nav-sub="device">${_('Device')}</div>
                        <div class="mode-tab ${this._isActivePath('pipe') ? 'active' : ''}" data-nav-sub="pipe">${_('Pipe')}</div>
                        <div class="mode-tab ${this._isActivePath('sprinkler') ? 'active' : ''}" data-nav-sub="sprinkler">${_('Irrigation')}</div>
                    `)) +
                    `</div>` +
                    this._group(_('Show on map')) +
                    `<div class="aot-modal-container">` +
                    this._switchRow('btn-hide-pipe-label', !this.isPipeLabelHidden,
                                    _('Pipe labels')) +
                    this._switchRow('btn-hide-sprinkler-points', !this.isSprinklerPointsHidden,
                                    _('Sprinklers')) +
                    this._switchRow('btn-hide-connection-points', !this.isConnectionPointsHidden,
                                    _('Joints')) +
                    `</div>`;
                break;

            // --- Tier 2: Aot Device Root ---
            case 'aot_device': {
                html += this._group(_('Basic settings')) +
                    `<div class="aot-modal-container">` +
                    this._shapeVisibilityRow('aot_device') +
                    this._row(_('Device kind'), this._btnRow(`
                        <div class="mode-tab ${this._isActivePath('input') ? 'active' : ''}" data-nav-sub="input">${_('Input')}</div>
                        <div class="mode-tab ${this._isActivePath('output') ? 'active' : ''}" data-nav-sub="output">${_('Output')}</div>
                        <div class="mode-tab ${this._isActivePath('function') ? 'active' : ''}" data-nav-sub="function">${_('Function')}</div>
                        <div class="mode-tab ${this._isActivePath('device_unit') ? 'active' : ''}" data-nav-sub="device_unit">${_('Device')}</div>
                    `));
                // 선택된 구역 폴리곤이 있으면 그 자리의 배정을 바로 연다.
                // 없을 때 버튼만 띄우면 눌러도 "먼저 구역을 고르세요" 밖에 못 한다.
                if (this._selectedAreaShapeId()) {
                    html += this._row(_('Assign device'),
                        `<button class="btn aot-pill-btn aot-pill-btn-primary" id="btn-bind-area">${
                            _('Assign')}</button>`,
                        _('Assigns a device to the zone you selected on the map.'));
                }
                html += this._row(_('Places with no device'),
                        `<button class="btn aot-pill-btn" id="btn-unbound-slots">${
                            _('Show')}</button>`,
                        _('Lists the zones that still have no device assigned.')) +
                    `</div>`;
                // 구역 나누기 — 식생 모드와 같은 자리, 같은 흐름.
                // site/zone 을 골라 잘라서 장치 담당 구역을 얻는다.
                {
                    const ds = this.geoDesign && this.geoDesign.deviceSplit;
                    html += (ds && ds.panelHtml) ? ds.panelHtml() : '';
                }
                break;
            }

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

                html += this._group(
                        type === 'input' ? _('Input')
                        : type === 'output' ? _('Output') : _('Function')) +
                    `<div class="aot-modal-container">` +
                    this._colorRow('device-color-picker', '', savedColor) +
                    this._switchRow('device-visible-toggle', isVisible,
                                    _('Show on map')) +
                    this._row(_('Selection list'),
                        `<button class="btn aot-pill-btn" id="btn-device-list">${
                            _('Open')}</button>`,
                        _('Pick which devices of this kind appear on the map.')) +
                    `</div>`;
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
                html += this._group(_('Device')) +
                    `<div class="aot-modal-container">` +
                    this._colorRow('device-color-picker', '', devColor) +
                    this._switchRow('device-visible-toggle', devVisible,
                                    _('Show on map')) +
                    this._row(_('Selection list'),
                        `<button class="btn aot-pill-btn" id="btn-device-list">${
                            _('Open')}</button>`,
                        _('Pick which devices of this kind appear on the map.')) +
                    `</div>`;
                break;
            }

            // --- Tier 3: Equipment > Device Categories ---
            case 'device':
                html += this._group(_('Device')) +
                    `<div class="aot-modal-container">` +
                    this._row(_('Category'), this._btnRow(`
                        <div class="mode-tab ${this._isActivePath('supply') ? 'active' : ''}" data-nav-cat="supply">${_('Water supply')}</div>
                        <div class="mode-tab ${this._isActivePath('filter') ? 'active' : ''}" data-nav-cat="filter">${_('Filter')}</div>
                        <div class="mode-tab ${this._isActivePath('valve') ? 'active' : ''}" data-nav-cat="valve">${_('Valve')}</div>
                        <div class="mode-tab ${this._isActivePath('conn') ? 'active' : ''}" data-nav-cat="conn">${_('Connection')}</div>
                    `), _('Choose a category, then pick the part to place on the map.')) +
                    `</div>`;
                break;

            // --- Tier 3: Equipment > Pipe Actions ---
            case 'pipe':
                html += this._group(_('Pipe')) +
                    `<div class="aot-modal-container">` +
                    this._row(_('Draw'), this._btnRow(`
                        <button class="btn aot-pill-btn" id="btn-draw-ref">${_('Reference line')}</button>
                        <button class="btn aot-pill-btn" id="btn-draw-main">${_('Main pipe')}</button>
                    `), _('Draw the reference line and the main pipe first — branches are generated from them.')) +
                    this._switchRow('btn-90deg', this.pipeConfig.is90Deg,
                                    _('Branch at 90 degrees'),
                                    _('Lays branches square to the main pipe instead of following the reference line.')) +
                    this._row(_('Spacing and angle'),
                        `<button class="btn aot-pill-btn" data-nav-sub="pipe_settings">${
                            _('Open')}</button>`) +
                    `</div>` +
                    `<div class="aot-modal-container">` +
                    this._row(_('Generate branches'),
                        `<button class="btn aot-pill-btn aot-pill-btn-primary" id="btn-gen-pipe">${
                            _('Generate')}</button>`) +
                    this._row(_('Reset'),
                        `<button class="btn aot-pill-btn" id="btn-clear-equip" data-clear-mode="all">${
                            _('Reset')}</button>`,
                        _('Removes the generated pipes so you can start over.')) +
                    `</div>`;
                break;

            // --- Tier 3: Equipment > Irrigation (Shared Controller) ---
            case 'sprinkler': {
                const isSp = this.irrigationType === 'sprinkler';
                html += this._group(_('Irrigation')) +
                    `<div class="aot-modal-container">` +
                    this._row(_('Type'), this._btnRow(`
                        <button class="btn aot-pill-btn ${isSp ? 'aot-pill-btn-primary' : ''}" id="btn-set-sprinkler">${_('Sprinkler')}</button>
                        <button class="btn aot-pill-btn ${!isSp ? 'aot-pill-btn-primary' : ''}" id="btn-set-drip">${_('Drip')}</button>
                    `)) +
                    `</div>` +
                    this._group(isSp ? _('Sprinkler') : _('Drip')) +
                    `<div class="aot-modal-container">`;
                if (isSp) {
                    html += this._numberRow('sp-interval', this.sprinklerConfig.interval,
                                            _('Spacing'), 'm', '0.5') +
                            this._numberRow('sp-radius', this.sprinklerConfig.radius,
                                            _('Radius'), 'm', '0.5') +
                            this._numberRow('sp-flow', this.sprinklerConfig.flow,
                                            _('Flow rate'), 'L/h', '10') +
                            this._numberRow('sp-pressure', this.sprinklerConfig.pressure,
                                            _('Pressure'), 'bar', '0.1');
                } else {
                    html += this._numberRow('dp-interval', this.dripConfig.interval,
                                            _('Spacing'), 'm', '0.1') +
                            this._numberRow('dp-flow', this.dripConfig.flow,
                                            _('Flow rate'), 'L/h', '0.1') +
                            this._numberRow('dp-pressure', this.dripConfig.pressure,
                                            _('Pressure'), 'bar', '0.1');
                }
                html += `</div>` +
                    `<div class="aot-modal-container">` +
                    this._row(_('Generate'),
                        `<button class="btn aot-pill-btn aot-pill-btn-primary" id="btn-gen-irrigation">${
                            _('Generate')}</button>`) +
                    this._row(_('Reset'),
                        `<button class="btn aot-pill-btn" id="btn-clear-equip" data-clear-mode="sprinkler">${
                            _('Reset')}</button>`) +
                    `</div>`;
                break;
            }



            // --- Tier 4: Irrigation Settings (Dynamic) ---


            // --- Tier 4: Device Items ---
            // 부품 목록 — 누르면 지도에 그 부품을 놓는다. 종류가 몇 개뿐이라
            // 라벨 한 줄로 감싸는 것보다 버튼을 그대로 늘어놓는 편이 읽기 쉽다.
            case 'supply': case 'filter': case 'valve': case 'conn': {
                const items = {
                    supply: [['river', _('River')], ['tank', _('Water tank')], ['pump', _('Pump')]],
                    filter: [['disc', _('Disc')], ['screen', _('Screen')], ['sand', _('Sand')]],
                    valve: [['union', _('Union valve')], ['m-single', _('Adapter valve')],
                            ['f-single', _('Inline valve')], ['reducer', _('Reducer')]],
                    conn: [['suction', _('Suction')], ['elbow', _('Elbow')],
                           ['tee', _('Tee')], ['reducer', _('Reducer')]],
                }[tierId];
                const titles = {
                    supply: _('Water supply'), filter: _('Filter'),
                    valve: _('Valve'), conn: _('Connection'),
                };
                html += this._group(titles[tierId]) +
                    `<div class="aot-modal-container">` +
                    this._row(_('Place on map'), this._btnRow(items.map(
                        ([k, label]) => `<button class="btn aot-pill-btn" data-device-item="${k}">${label}</button>`
                    ).join('')), _('Pick a part, then click the map to place it.')) +
                    `</div>`;
                break;
            }

            // --- Tier 4: Pipe Settings ---
            // 예전에는 여기서 화면 폭을 재어(`window.innerWidth > 768`) 폰이면
            // 슬라이더 대신 `pipe_angle`/`pipe_offset` 하위 tier 로 들어가는
            // 버튼을 냈다. 하단 가로바에 슬라이더 둘이 안 들어갔기 때문인데,
            // 드로어는 폰에서도 화면을 다 쓰므로 그 우회가 필요 없어졌다 —
            // 두 하위 tier 와 함께 지웠다.
            case 'pipe_settings':
                html += this._group(_('Spacing and angle')) +
                    `<div class="aot-modal-container">` +
                    this._numberRow('pipe-spacing', this.pipeConfig.spacing,
                                    _('Spacing'), 'm', '0.5') +
                    this._sliderRow('pipe-angle', 'val-angle', this.pipeConfig.angle,
                                    _('Angle'), '°', -90, 90, 1) +
                    this._sliderRow('pipe-offset', 'val-offset', this.pipeConfig.offset,
                                    _('Offset'), 'm', -15, 15, 0.5) +
                    `<div class="aot-modal-body-text">${
                        _('The map updates as you drag — branches follow the reference line at this angle.')}</div>` +
                    `</div>`;
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
                // 탭을 누르는 것이 그 모드의 설정을 여는 동작이다 — 하단바에는
                // 이제 탭만 있으므로, 열지 않으면 설정에 닿을 길이 없다.
                this.openSettings();
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
                // 드로어 안의 drill-up 하나뿐이다. 예전에는 tier 1 의 뒤로
                // 버튼이 "모드 목록으로" 였지만, 모드 탭이 이제 하단바에 늘 떠
                // 있어 그 버튼은 render() 에서 더 이상 만들지 않는다.
                this._popTier();
            };
        });

        // --- Core Functional Bindings ---

        // Address Import (Site tier)
        const btnAddFromAddress = rootEl.querySelector('#btn-add-from-address');
        if (btnAddFromAddress) btnAddFromAddress.onclick = () => {
            const modal = document.getElementById('modal-parcel-import');
            if (modal && window.$) $(modal).modal('show');
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

        // 도형 종류 표시/숨김 (site/zone/facility/plot/equipment)
        const toggleShapeVis = rootEl.querySelector('#shape-visible-toggle');
        if (toggleShapeVis) {
            toggleShapeVis.onchange = (e) => {
                const shapeType = e.target.dataset.shapeType;
                const isVisible = e.target.checked;
                // 장치 쪽 `vis_<type>` 와 키를 나눈다 — 'equipment' 처럼 이름이
                // 겹치는 축이 있어, 같은 키를 쓰면 서로의 상태를 덮어쓴다.
                this._handleThemeColorChange(`vis_shape_${shapeType}`, isVisible);
                if (this.geoDesign && this.geoDesign.setShapeTypeVisibility) {
                    this.geoDesign.setShapeTypeVisibility(shapeType, isVisible);
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
        else if (mode === 'plot') themeVar = '--theme-plot';
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
