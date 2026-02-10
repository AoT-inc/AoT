(function () {
  if (customElements.get('aot-map-search')) return;
  const SEARCHBAR_CSS = `
  .searchbar {
    font-size: 14px;
    font-family: Arial, sans-serif;
    color: #202124;
    display: flex;
    z-index: 3;
    height: 44px;
    background: #fff;
    border: 1px solid #dfe1e5;
    box-shadow: none;
    border-radius: 24px;
    margin: 0 auto;
    width: 100%;
    max-width: 600px; /* Match overlay max-width */
  }

  .searchbar:hover {
    box-shadow: 0 1px 6px rgba(32, 33, 36, 0.28);
    border-color: transparent;
  }

  .searchbar-wrapper {
    flex: 1;
    display: flex;
    align-items: center;
    padding: 5px 8px 0 14px;
  }

  .searchbar-left {
    font-size: 14px;
    font-family: Arial, sans-serif;
    color: #202124;
    display: flex;
    align-items: center;
    padding-right: 13px;
    margin-top: -5px;
  }

  .search-icon-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .search-icon {
    margin-top: 3px;
    color: #9aa0a6;
    height: 20px;
    line-height: 20px;
    width: 20px;
  }

  .searchbar-icon {
    display: inline-block;
    fill: currentColor;
    height: 24px;
    line-height: 24px;
    position: relative;
    width: 24px;
  }

  .searchbar-center {
    display: flex;
    flex: 1;
    flex-wrap: wrap;
  }

  .searchbar-input-spacer {
    color: transparent;
    flex: 100%;
    white-space: pre;
    height: 34px;
    font-size: 16px;
  }

  .searchbar-input {
    background-color: transparent;
    border: none;
    margin: 0;
    padding: 0;
    color: rgba(0, 0, 0, 0.87);
    word-wrap: break-word;
    outline: none;
    display: flex;
    flex: 100%;
    margin-top: -37px;
    height: 34px;
    font-size: 16px;
    max-width: 100%;
    width: 100%;
  }

  .searchbar-right {
    display: flex;
    flex: 0 0 auto;
    margin-top: -5px;
    align-items: center;
    flex-direction: row;
    padding-right: 8px;
  }

  .voice-search {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    cursor: pointer;
    border-radius: 50%;
    transition: transform 0.2s ease, opacity 0.2s ease, background-color 0.2s ease;
  }

  .voice-search svg {
    width: 24px;
    height: 24px;
  }

  .voice-search:hover {
    background-color: rgba(66, 133, 244, 0.08);
    transform: scale(1.05);
  }

  .voice-search.disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .voice-search.active {
    animation: pulse 1.2s infinite;
  }

  @keyframes pulse {
    0% {
      transform: scale(1);
    }
    50% {
      transform: scale(1.08);
    }
    100% {
      transform: scale(1);
    }
  }
  `;

  const template = document.createElement('template');
  template.innerHTML = `
    <style>
      ${SEARCHBAR_CSS}

      :host {
        display: block;
        position: relative;
        width: 100%;
        max-width: 100%;
      }
      .searchbar-container {
        display: flex;
        justify-content: center;
        width: 100%;
      }
      .searchbar {
        width: 100%;
      }
      .results {
        position: absolute;
        top: calc(100% + 6px);
        left: 0;
        right: 0;
        z-index: 1050;
        background: #fff;
        border: 1px solid rgba(0,0,0,.125);
        border-radius: .25rem;
        box-shadow: 0 .5rem 1rem rgba(0,0,0,.15);
        display: none;
        max-height: 240px;
        overflow-y: auto;
      }
      .results.show {
        display: block;
      }
      .list-group-item {
        position: relative;
        display: block;
        padding: .75rem 1.25rem;
        background-color: #fff;
        border: 1px solid rgba(0,0,0,.125);
        cursor: pointer;
      }
      .list-group-item:hover {
        background-color: #f8f9fa;
      }
    </style>
    <div class="searchbar-container">
      <div class="searchbar">
        <div class="searchbar-wrapper">
          <div class="searchbar-left">
            <div class="search-icon-wrapper">
              <span class="search-icon searchbar-icon">
                <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
                  <path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"></path>
                </svg>
              </span>
            </div>
          </div>
          <div class="searchbar-center">
            <div class="searchbar-input-spacer" aria-hidden="true"></div>
            <input type="text" class="searchbar-input" id="input" maxlength="2048" autocapitalize="off" autocomplete="off" title="주소 검색" role="combobox" placeholder="주소를 입력하세요.">
          </div>
            <span class="voice-search" id="clear-btn" role="button" tabindex="0" aria-label="삭제">
              <svg viewBox="0 0 24 24" width="24" height="24">
                <path fill="#5f6368" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"></path>
              </svg>
            </span>
          </div>
        </div>
      </div>
    </div>
    <div class="results list-group" id="results"></div>
  `;

  class AotMapSearch extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.appendChild(template.content.cloneNode(true));
      this._debounceTimer = null;
      this._lastQuery = '';
    }

    connectedCallback() {
      this.inputEl = this.shadowRoot.getElementById('input');
      this.resultsEl = this.shadowRoot.getElementById('results');
      this.clearBtn = this.shadowRoot.getElementById('clear-btn');

      const placeholder = this.getAttribute('placeholder') || '주소를 입력하세요.';
      this.inputEl.placeholder = placeholder;

      this.inputEl.addEventListener('input', () => {
        this._updateClearButton();
        this._scheduleSearch();
      });
      this.inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this._scheduleSearch({ immediate: true });
        }
      });

      if (this.clearBtn) {
        const clearAction = (e) => {
          e.preventDefault();
          this.inputEl.value = '';
          this.inputEl.focus();
          this._updateClearButton();
          this.resultsEl.innerHTML = '';
          this.resultsEl.classList.remove('show');
          this._lastQuery = '';
        };
        this.clearBtn.addEventListener('click', clearAction);
        this.clearBtn.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            clearAction(e);
          }
        });
      }

      this._updateClearButton();
    }

    _updateClearButton() {
      if (this.clearBtn) {
        // Show button only if there is text? Or always show?
        // User request: "Change to X button, delete function".
        // Standard UX: Hide if empty.
        if (this.inputEl.value && this.inputEl.value.trim().length > 0) {
          this.clearBtn.style.visibility = 'visible';
        } else {
          this.clearBtn.style.visibility = 'hidden';
        }
      }
    }

    _scheduleSearch(options = {}) {
      const immediate = options.immediate;
      clearTimeout(this._debounceTimer);
      if (immediate) {
        this.search({ force: true });
      } else {
        this._debounceTimer = setTimeout(() => this.search(), 800);
      }
    }

    search(options = {}) {
      const query = this.inputEl.value.trim();
      if (!query) {
        this.resultsEl.classList.remove('show');
        this.resultsEl.innerHTML = '';
        this._lastQuery = '';
        return;
      }
      if (!options.force && query === this._lastQuery) return;
      this._lastQuery = query;

      const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&accept-language=ko`;

      fetch(url)
        .then(r => r.json())
        .then(data => {
          this.renderResults(data);
        })
        .catch(err => {
          console.error('Search failed', err);
        });
    }

    renderResults(data) {
      this.resultsEl.innerHTML = '';
      if (!data || !data.length) {
        this.resultsEl.classList.remove('show');
        return;
      }

      data.forEach(item => {
        const el = document.createElement('div');
        el.className = 'list-group-item list-group-item-action';
        el.textContent = item.display_name;
        el.addEventListener('click', () => {
          this.selectLocation(item);
        });
        this.resultsEl.appendChild(el);
      });
      this.resultsEl.classList.add('show');
    }

    selectLocation(item) {
      this.resultsEl.innerHTML = '';
      this.resultsEl.classList.remove('show');
      this.inputEl.value = item.display_name;
      this._lastQuery = item.display_name;
      this._updateClearButton();

      const lat = parseFloat(item.lat);
      const lng = parseFloat(item.lon);

      this.dispatchEvent(new CustomEvent('location-selected', {
        detail: { lat, lng, name: item.display_name },
        bubbles: true,
        composed: true
      }));
    }
  }

  customElements.define('aot-map-search', AotMapSearch);
})();
