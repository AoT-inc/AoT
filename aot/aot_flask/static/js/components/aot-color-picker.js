(function () {
    if (customElements.get('aot-color-picker')) return;

    class AoTColorPicker extends HTMLElement {
        static get observedAttributes() {
            return ['value', 'label', 'name', 'presets', 'direction'];
        }

        static closeActive(instance) {
            if (AoTColorPicker._openInstance && AoTColorPicker._openInstance !== instance) {
                AoTColorPicker._openInstance.closePanel();
            }
        }

        constructor() {
            super();
            this.attachShadow({ mode: 'open' });
            this._presets = ['#008dde', '#DAF2E6', '#F4D624', '#FEA60B', '#DF5353'];
            this._value = this._presets[0];
            this._name = '';
            this._direction = 'bottom';
            this._boundDocClick = this.handleDocumentClick.bind(this);
            this._syncRetry = null;
        }

        get value() { return this.getAttribute('value'); }
        set value(val) { this.setAttribute('value', val); }

        connectedCallback() {
            this.render();
            this.attachEvents();
            this.setupSyncTarget();
        }

        disconnectedCallback() {
            this.closePanel();
            if (this._syncRetry) {
                cancelAnimationFrame(this._syncRetry);
                this._syncRetry = null;
            }
            if (this._syncTargetEl && this._syncHandler) {
                this._syncTargetEl.removeEventListener('input', this._syncHandler);
                this._syncTargetEl.removeEventListener('change', this._syncHandler);
            }
        }

        attributeChangedCallback(name, oldValue, newValue) {
            if (oldValue === newValue) return;
            if (name === 'value') {
                this._value = newValue;
                this.updateUI();
            } else if (name === 'presets') {
                try {
                    this._presets = JSON.parse(newValue);
                    this.renderPresets();
                } catch (e) {
                    console.warn('AoTColorPicker: invalid presets JSON', e);
                }
            } else if (name === 'name') {
                this._name = newValue || '';
                const hidden = this.shadowRoot.querySelector('input[type="hidden"]');
                if (hidden) hidden.name = this._name;
            } else if (name === 'label') {
                const labelEl = this.shadowRoot.querySelector('.color-value-label');
                if (labelEl) labelEl.textContent = (newValue || this._value).toUpperCase();
            } else if (name === 'direction') {
                this._direction = this.normalizeDirection(newValue);
                const root = this.shadowRoot.querySelector('.aot-color-picker');
                if (root) root.dataset.direction = this._direction;
            }
        }

        normalizeDirection(dir) {
            const allowed = ['top', 'bottom', 'left', 'right'];
            const lower = (dir || '').toLowerCase();
            return allowed.includes(lower) ? lower : 'bottom';
        }

        render() {
            this._name = this.getAttribute('name') || '';
            this._direction = this.normalizeDirection(this.getAttribute('direction'));
            const label = this.getAttribute('label') || '';
            this._value = this.getAttribute('value') || this._value;

            this.shadowRoot.innerHTML = `
      <style>
      :host { --aot-color-ring: #d5dae3; --aot-color-ring-active: #1a73e8; --aot-color-shadow: rgba(15, 23, 42, 0.2); display: inline-flex; font-family: inherit; }
      .aot-color-picker { position: relative; display: inline-flex; align-items: center; gap: 0.6em; min-height: 32px; }
      .current-shell { width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--aot-color-ring); padding: 2px; display: flex; align-items: center; justify-content: center; transition: border-color 0.2s ease, box-shadow 0.2s ease; }
      .aot-color-picker.open .current-shell { border-color: var(--aot-color-ring-active); box-shadow: 0 0 0 2px rgba(26, 115, 232, 0.2); }
      .current-color-button { width: 28px; height: 28px; border-radius: 50%; border: none; cursor: pointer; background: var(--aot-color-value, #008dde); transition: transform 0.2s ease; }
      .current-color-button:focus-visible { outline: 2px solid var(--aot-color-ring-active); outline-offset: 2px; }
      .current-color-button:hover { transform: scale(1.05); }
      .color-value-label { font-size: 0.85rem; font-weight: 600; letter-spacing: 0.02em; color: #374151; min-width: 62px; }
      .swatch-panel { position: absolute; display: flex; align-items: center; gap: 0.65em; padding: 0.55em 0.9em; border-radius: 24px; background: #fff; border: 1px solid #dfe3eb; box-shadow: 0 15px 35px rgba(15, 23, 42, 0.25); opacity: 0; pointer-events: none; transform: translateY(6px); transition: opacity 0.25s ease, transform 0.25s ease; z-index: 1200; }
      .aot-color-picker.open .swatch-panel { opacity: 1; pointer-events: auto; }
      .aot-color-picker[data-direction="bottom"] .swatch-panel { top: calc(100% + 12px); left: 50%; transform: translate(-50%, 6px); }
      .aot-color-picker.open[data-direction="bottom"] .swatch-panel { transform: translate(-50%, 0); }
      .aot-color-picker[data-direction="top"] .swatch-panel { bottom: calc(100% + 12px); left: 50%; transform: translate(-50%, -6px); }
      .aot-color-picker.open[data-direction="top"] .swatch-panel { transform: translate(-50%, 0); }
      .aot-color-picker[data-direction="left"] .swatch-panel { right: calc(100% + 12px); top: 50%; transform: translate(-6px, -50%); }
      .aot-color-picker.open[data-direction="left"] .swatch-panel { transform: translate(0, -50%); }
      .aot-color-picker[data-direction="right"] .swatch-panel { left: calc(100% + 12px); top: 50%; transform: translate(6px, -50%); }
      .aot-color-picker.open[data-direction="right"] .swatch-panel { transform: translate(0, -50%); }
      .preset-list { display: flex; gap: 0.35em; }
      .preset-swatch, .custom-swatch { width: 28px; height: 28px; border-radius: 50%; border: 1px solid #cfd5df; background: var(--swatch-color, transparent); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease; }
      .preset-swatch:hover, .custom-swatch:hover { transform: scale(1.12); border-color: var(--aot-color-ring-active); }
      .preset-swatch.is-active { border-color: var(--aot-color-ring-active); box-shadow: 0 0 0 2px rgba(26, 115, 232, 0.25); }
      .custom-swatch { background: conic-gradient(red, yellow, lime, aqua, blue, magenta, red); position: relative; overflow: hidden; }
      .custom-color-input { appearance: none; position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }
      </style>
      <div class="aot-color-picker" data-direction="${this._direction}">
        <div class="current-shell">
          <button type="button" class="current-color-button" aria-label="${label || window._('select_color')}"
            style="background:${this._value}; background-color:${this._value}; --aot-color-value:${this._value};"></button>
        </div>
        <div class="swatch-panel">
          <div class="preset-list"></div>
          <label class="custom-swatch" aria-label="${window._('custom_color')}">
            <input type="color" class="custom-color-input" value="${this._value}">
          </label>
        </div>
      </div>
      <input type="hidden" name="${this._name}" value="${this._value}">
    `;
            this.renderPresets();
            this.updateUI();
        }

        renderPresets() {
            const list = this.shadowRoot.querySelector('.preset-list');
            if (!list) return;
            list.innerHTML = '';
            const colors = this._presets.slice(0, 5);
            colors.forEach(color => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'preset-swatch';
                btn.dataset.color = color;
                btn.style.setProperty('--swatch-color', color);
                btn.title = color;
                btn.addEventListener('click', (evt) => {
                    evt.preventDefault();
                    evt.stopPropagation();
                    this.setColor(color, { close: true, source: 'preset-click' });
                });
                list.appendChild(btn);
            });
            this.updateSwatchState();
        }

        attachEvents() {
            const trigger = this.shadowRoot.querySelector('.current-color-button');
            const customInput = this.shadowRoot.querySelector('.custom-color-input');
            if (trigger) {
                trigger.addEventListener('click', (e) => {
                    e.preventDefault();
                    this.togglePanel();
                });
            }
            if (customInput) {
                customInput.addEventListener('input', (e) => {
                    this.setColor(e.target.value, { close: false, silent: true, source: 'custom-input' });
                });
                customInput.addEventListener('change', (e) => {
                    this.setColor(e.target.value, { close: true, source: 'custom-change' });
                });
            }
        }

        togglePanel() {
            if (this._isOpen) {
                this.closePanel();
            } else {
                AoTColorPicker.closeActive(this);
                this.openPanel();
            }
        }

        openPanel() {
            const root = this.shadowRoot.querySelector('.aot-color-picker');
            if (!root) return;
            root.classList.add('open');
            this._isOpen = true;
            AoTColorPicker._openInstance = this;
            document.addEventListener('click', this._boundDocClick, true);
        }

        closePanel() {
            const root = this.shadowRoot.querySelector('.aot-color-picker');
            if (root) root.classList.remove('open');
            this._isOpen = false;
            if (AoTColorPicker._openInstance === this) {
                AoTColorPicker._openInstance = null;
            }
            document.removeEventListener('click', this._boundDocClick, true);
        }

        handleDocumentClick(event) {
            const path = event.composedPath ? event.composedPath() : [];
            if (path.includes(this) || path.includes(this.shadowRoot)) return;
            this.closePanel();
        }

        setColor(color, options = {}) {
            if (!color) return;
            this._value = color;
            if (this.getAttribute('value') !== color) {
                this.setAttribute('value', color);
            }
            console.log('[ColorPicker] setColor', {
                picker: this.getAttribute('data-sync-target') || '(no target)',
                value: color,
                source: options.source || 'unknown',
                options: options
            });
            this.updateUI();
            this.updateSyncTarget(color, options);

            if (!options.silent) {
                this.dispatchEvent(new CustomEvent('input', { detail: { value: color } }));
                this.dispatchEvent(new Event('change', { bubbles: true }));
            }

            if (options.close) {
                this.closePanel();
            }
        }

        updateUI() {
            const btn = this.shadowRoot.querySelector('.current-color-button');
            const hidden = this.shadowRoot.querySelector('input[type="hidden"]');
            const customInput = this.shadowRoot.querySelector('.custom-color-input');
            if (btn) {
                btn.style.setProperty('--aot-color-value', this._value);
                btn.style.background = this._value;
                btn.style.backgroundColor = this._value;
            }
            if (hidden) hidden.value = this._value;
            if (customInput && customInput.value !== this._value) {
                customInput.value = this._value;
            }
            this.updateSwatchState();
        }

        updateSwatchState() {
            const buttons = this.shadowRoot.querySelectorAll('.preset-swatch');
            if (!buttons) return;
            const val = (this._value || '').toLowerCase();
            buttons.forEach(btn => {
                const matches = btn.dataset.color && btn.dataset.color.toLowerCase() === val;
                btn.classList.toggle('is-active', matches);
            });
        }

        setupSyncTarget() {
            const targetId = this.getAttribute('data-sync-target');
            if (!targetId) return;

            const attach = () => {
                const target = document.getElementById(targetId);
                if (!target) {
                    this._syncRetry = requestAnimationFrame(attach);
                    return;
                }
                const handler = () => {
                    const val = target.value;
                    if (val && val !== this._value) {
                        this._value = val;
                        this.updateUI();
                    }
                };
                if (target.dataset) {
                    target.dataset.aotNativePicker = '1';
                }
                handler();
                target.addEventListener('input', handler);
                target.addEventListener('change', handler);
                this._syncTargetEl = target;
                this._syncHandler = handler;
                if (this._syncRetry) {
                    cancelAnimationFrame(this._syncRetry);
                    this._syncRetry = null;
                }
            };

            attach();
        }

        updateSyncTarget(color, options = {}) {
            const targetId = this.getAttribute('data-sync-target');
            if (!targetId) return;
            const target = document.getElementById(targetId);
            if (!target) return;
            if (target.value !== color) {
                target.value = color;
            }
            if (target.dataset) {
                const stamp = Date.now();
                target.dataset.aotPickerValue = color;
                target.dataset.aotPickerStamp = String(stamp);
                target.dataset.aotPickerGuard = '1';
                if (!target.dataset.aotPickerSource) {
                    const pickerId = this.getAttribute('id') || this.getAttribute('data-sync-target') || '';
                    target.dataset.aotPickerSource = pickerId;
                }
                if (target.__aotPickerGuardTimer) {
                    clearTimeout(target.__aotPickerGuardTimer);
                }
                target.__aotPickerGuardTimer = setTimeout(() => {
                    if (!target.dataset) return;
                    const currentStamp = parseInt(target.dataset.aotPickerStamp || '0', 10);
                    if (!currentStamp) {
                        target.dataset.aotPickerGuard = '';
                        return;
                    }
                    if (Date.now() - currentStamp >= 400) {
                        target.dataset.aotPickerGuard = '';
                    }
                }, 600);
            }
            console.log('[ColorPicker] updateSyncTarget', {
                targetId,
                value: color
            });

            // [Fix] Dispatch events so listeners (like MapClient) catch the change
            if (!options.silent) {
                target.dispatchEvent(new Event('input', { bubbles: true }));
                target.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }
    }

    customElements.define('aot-color-picker', AoTColorPicker);
})();
