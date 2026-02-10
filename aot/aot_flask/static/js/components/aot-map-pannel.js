(function () {
  if (customElements.get('aot-map-panel')) return;

  class AotMapPanel extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._body = null;
      this._inner = null;
      this._checkbox = null;
      this._toggleEnabled = false;
    }

    static get observedAttributes() {
      return ['title'];
    }

    connectedCallback() {
      this.render();
    }

    attributeChangedCallback(name, oldValue, newValue) {
      if (name === 'title' && this.shadowRoot) {
        const titleEl = this.shadowRoot.querySelector('.panel-title');
        if (titleEl) titleEl.textContent = newValue || '';
      } else {
        this.render();
      }
    }

    static get toggleCssUrl() {
      return '/static/css/components/btn-toggle.css';
    }

    render() {
      const title = this.getAttribute('title') || '';
      const hasControls = !!this.querySelector('[slot="controls"]');
      const hasContent = this._hasAssignedContent();
      this._toggleEnabled = this.hasAttribute('toggle');
      const isPlain = this.hasAttribute('plain');
      const toggleCheckedAttr = this.getAttribute('toggle-checked');
      const toggleChecked = this._toggleEnabled ? (toggleCheckedAttr === 'true') : true;
      const toggleCss = AotMapPanel.toggleCssUrl;

      const styles = `
      @import url('${toggleCss}');
      :host {
        display: block;
        background: ${isPlain ? 'transparent' : '#fff'};
        border-radius: ${isPlain ? '0' : '8px'};
        border: ${isPlain ? 'none' : '1px solid rgba(0,0,0,0.06)'};
        box-shadow: ${isPlain ? 'none' : '0 2px 6px rgba(15,32,43,0.06)'};
        padding: 1em;
        color: var(--aot-text-color, #1f2a37);
        font-family: inherit;
        box-sizing: border-box;
      }
      .panel-header {
        display: flex;
        align-items: center;
        gap: 1em;
        padding: 0.5em 0;
      }
      .panel-title {
        flex: 1;
        font-size: 1.2em;
        font-weight: 600;
        line-height: 1.2;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .panel-controls {
        display: flex;
        align-items: center;
        gap: 0.5em;
        margin-left: auto;
      }
      .panel-divider {
        border-top: 1px solid rgba(0,0,0,0.08);
        margin: 0.5em 0;
        display: none;
      }
      .panel-body {
        padding: 0.5em 0;
        overflow: hidden;
        max-height: none;
      }
      .panel-body.collapsible {
        max-height: 0;
        opacity: 0;
        transition: max-height 0.25s ease, opacity 0.25s ease, padding 0.2s ease;
        padding: 0;
        margin: 0;
      }
      .panel-body.collapsible.active {
        opacity: 1;
        padding: 0.5em 0;
        display: block;
      }
      .panel-body.empty {
        display: none;
      }
      .panel-divider.hidden {
        display: none;
      }
      .body-inner {
        display: block;
      }
      ::slotted([slot="controls"]) {
        display: inline-flex;
        justify-content: flex-end;
        width: 100%;
      }
    `;

      this.shadowRoot.innerHTML = `
      <style>${styles}</style>
      <div class="panel-header">
        <div class="panel-title" title="${title}">${title}</div>
        ${this._toggleEnabled || hasControls ? `
          <div class="panel-controls">
            ${this._toggleEnabled ? `
              <label class="switch mb-0">
                <input type="checkbox" ${toggleChecked ? 'checked' : ''}>
                <span class="slider"></span>
              </label>
            ` : ''}
            ${hasControls ? '<slot name="controls"></slot>' : ''}
          </div>
        ` : ''}
      </div>
      <div class="panel-divider ${hasContent ? '' : 'hidden'}"></div>
      <div class="panel-body ${this._toggleEnabled ? 'collapsible' : ''} ${hasContent ? '' : 'empty'}">
        <div class="body-inner"><slot name="content"></slot></div>
      </div>
    `;

      this._divider = this.shadowRoot.querySelector('.panel-divider');
      this._body = this.shadowRoot.querySelector('.panel-body');
      this._inner = this._body ? this._body.querySelector('.body-inner') : null;
      this._checkbox = this.shadowRoot.querySelector('.switch input');

      const slot = this.shadowRoot.querySelector('slot[name="content"]');
      if (slot) {
        slot.addEventListener('slotchange', () => {
          if (this._toggleEnabled) {
            const checked = this._checkbox ? this._checkbox.checked : false;
            this._applyToggleState(checked, { immediate: true });
          }
        });
      }

      if (this._toggleEnabled && this._checkbox) {
        this._checkbox.removeEventListener('change', this._boundToggleHandler);
        this._boundToggleHandler = () => this._handleToggle();
        this._checkbox.addEventListener('change', this._boundToggleHandler);
      }

      requestAnimationFrame(() => {
        this._applyToggleState(toggleChecked, { immediate: true });
      });
    }

    _handleToggle() {
      const checked = !!(this._checkbox && this._checkbox.checked);
      this.setAttribute('toggle-checked', checked ? 'true' : 'false');
      this._applyToggleState(checked);
      this.dispatchEvent(new CustomEvent('panel-toggle', {
        detail: { enabled: checked },
        bubbles: true
      }));
    }

    _applyToggleState(checked, options = {}) {
      if (!this._body) return;
      if (!this._hasAssignedContent()) {
        if (this._divider) this._divider.style.display = 'none';
        this._body.style.display = 'none';
        return;
      }
      if (!this._toggleEnabled) {
        this._body.classList.remove('collapsible', 'active');
        this._body.style.maxHeight = 'none';
        if (this._divider) {
          this._divider.style.display = this._body ? 'block' : 'none';
        }
        return;
      }

      const immediate = !!options.immediate;
      const body = this._body;
      if (this._divider) {
        this._divider.style.display = checked ? 'block' : 'none';
      }

      clearTimeout(this._collapseTimer);
      if (checked) {
        body.hidden = false;
        body.style.display = 'block';
        body.classList.add('active');
        body.setAttribute('aria-hidden', 'false');
        const target = this._measureContentHeight();
        const safeTarget = target > 0 ? target : 1;
        body.style.maxHeight = `${safeTarget}px`;
        if (immediate) {
          body.style.maxHeight = 'none';
        } else {
          this._collapseTimer = setTimeout(() => {
            if (this._body && this._checkbox && this._checkbox.checked) {
              this._body.style.maxHeight = 'none';
            }
          }, 280);
        }
      } else {
        const currentHeight = this._measureContentHeight();
        body.style.maxHeight = `${currentHeight}px`;
        body.setAttribute('aria-hidden', 'true');
        requestAnimationFrame(() => {
          if (!this._body) return;
          this._body.classList.remove('active');
          this._body.style.maxHeight = '0px';
        });
        this._collapseTimer = setTimeout(() => {
          if (!this._body) return;
          this._body.style.display = 'none';
          this._body.hidden = true;
        }, immediate ? 0 : 260);
      }
    }

    _measureContentHeight() {
      if (!this._body) return 0;
      const body = this._body;
      const prevDisplay = body.style.display;
      const prevMaxHeight = body.style.maxHeight;
      const prevHidden = body.hidden;

      body.style.display = 'block';
      body.hidden = false;
      body.style.maxHeight = 'none';
      const height = body.scrollHeight;

      body.style.maxHeight = prevMaxHeight || '';
      body.style.display = prevDisplay || '';
      body.hidden = prevHidden;
      return height;
    }

    _hasAssignedContent() {
      const nodes = Array.from(this.childNodes || []);
      return nodes.some((node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          return node.textContent.trim().length > 0;
        }
        return true;
      });
    }
  }

  customElements.define('aot-map-panel', AotMapPanel);
})();
