(function () {
    if (customElements.get('aot-size-picker')) return;
    class AotSizePicker extends HTMLElement {
        constructor() {
            super();
            this.attachShadow({ mode: 'open' });

            const template = document.createElement('template');
            template.innerHTML = `
            <style>
              :host {
                display: block;
              }
              select {
                width: 100%;
              }
            </style>
            <select class="form-control form-control-sm" id="select">
              <option value="1">1 (Very Small)</option>
              <option value="2">2 (Small)</option>
              <option value="3" selected>3 (Normal)</option>
              <option value="4">4 (Large)</option>
              <option value="5">5 (Very Large)</option>
            </select>
          `;
            this.shadowRoot.appendChild(template.content.cloneNode(true));
            this._value = '3';
        }

        connectedCallback() {
            this.selectEl = this.shadowRoot.getElementById('select');

            const initialValue = this.getAttribute('value');
            if (initialValue) {
                this.value = initialValue;
            }

            this.selectEl.addEventListener('change', (e) => {
                this.value = e.target.value;
                this.dispatchEvent(new Event('change', { bubbles: true }));
            });

            // External style injection (bootstrap)
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = 'https://cdn.jsdelivr.net/npm/bootstrap@4.6.2/dist/css/bootstrap.min.css';
            this.shadowRoot.appendChild(link);
        }

        get value() {
            return this._value;
        }

        set value(val) {
            this._value = val;
            if (this.selectEl) {
                this.selectEl.value = val;
            }
            if (this.hasAttribute('name')) {
                let hidden = this.querySelector('input[type="hidden"]');
                if (!hidden) {
                    hidden = document.createElement('input');
                    hidden.type = 'hidden';
                    hidden.name = this.getAttribute('name');
                    this.appendChild(hidden);
                }
                hidden.value = val;
            }
        }

        static get observedAttributes() {
            return ['value'];
        }

        attributeChangedCallback(name, oldValue, newValue) {
            if (name === 'value' && oldValue !== newValue) {
                this.value = newValue;
            }
        }
    }

    customElements.define('aot-size-picker', AotSizePicker);
})();
