(function () {
    if (customElements.get('aot-switch-row')) return;

    /**
     * AoT Switch Row Component
     * Displays a text label and a toggle switch on the same line.
     * 
     * Usage:
     * <aot-switch-row label="My Label" size="1.2em" checked></aot-switch-row>
     * 
     * Attributes:
     * - label: The text to display.
     * - size: Font size for the label (default: 1.5em).
     * - checked: Whether the switch is on.
     * - disabled: Whether the switch is disabled.
     * - name: Name for the internal checkbox.
     * - id: ID for the internal checkbox (optional).
     */
    const AOT_SWITCH_ROW_TOGGLE_CSS = '/static/css/components/btn-toggle.css';

    class AoTSwitchRow extends HTMLElement {
        static get observedAttributes() {
            return ['label', 'size', 'checked', 'disabled', 'name', 'id'];
        }

        constructor() {
            super();
            this._initialized = false;
        }

        connectedCallback() {
            AoTSwitchRow.ensureToggleCss();
            if (this._initialized) return;
            this._initialized = true;
            this.style.display = 'block';
            this.render();
        }

        static ensureToggleCss() {
            if (typeof document === 'undefined') return;
            if (document.querySelector('link[data-aot-toggle-css]')) return;
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = AOT_SWITCH_ROW_TOGGLE_CSS;
            link.setAttribute('data-aot-toggle-css', 'true');
            document.head.appendChild(link);
        }

        render() {
            // Use Light DOM to inherit global styles (Bootstrap, aot.css)
            const labelText = this.getAttribute('label') || '';
            const size = this.getAttribute('size') || '1.5em';
            const isChecked = this.hasAttribute('checked');
            const isDisabled = this.hasAttribute('disabled');
            const name = this.getAttribute('name') || '';
            const id = this.getAttribute('id') || '';

            this.innerHTML = `
      <div class="d-flex justify-content-between align-items-center w-100" style="padding: 1.5em 1em 1.5em 1em;">
        <span class="switch-label" style="font-size: ${size};">${labelText}</span>
        <label class="switch mb-0" onclick="event.stopPropagation();">
          <input type="checkbox"
            ${isChecked ? 'checked' : ''} 
            ${isDisabled ? 'disabled' : ''}
            ${name ? `name="${name}"` : ''}
            ${id ? `id="${id}"` : ''}>
          <span class="slider"></span>
        </label>
      </div>
    `;

            this._input = this.querySelector('input');
            this._labelSpan = this.querySelector('.switch-label');

            // Proxy change event
            this._input.addEventListener('change', (e) => {
                this.dispatchEvent(new Event('change', { bubbles: true }));
                // Update attribute to reflect state (optional, but good for styling/debugging)
                if (this._input.checked) {
                    this.setAttribute('checked', '');
                } else {
                    this.removeAttribute('checked');
                }
            });
        }

        attributeChangedCallback(name, oldValue, newValue) {
            if (!this._initialized) return;

            if (name === 'label' && this._labelSpan) {
                this._labelSpan.textContent = newValue;
            } else if (name === 'size' && this._labelSpan) {
                this._labelSpan.style.fontSize = newValue || '1.5em';
            } else if (name === 'checked' && this._input) {
                this._input.checked = newValue !== null;
            } else if (name === 'disabled' && this._input) {
                this._input.disabled = newValue !== null;
            } else if (name === 'name' && this._input) {
                this._input.name = newValue || '';
            } else if (name === 'id' && this._input) {
                this._input.id = newValue || '';
            }
        }

        get checked() {
            return this._input ? this._input.checked : this.hasAttribute('checked');
        }

        set checked(val) {
            if (val) {
                this.setAttribute('checked', '');
            } else {
                this.removeAttribute('checked');
            }
        }

        get value() {
            return this.getAttribute('value');
        }

        set value(val) {
            this.setAttribute('value', val);
        }
    }

    customElements.define('aot-switch-row', AoTSwitchRow);

})();
