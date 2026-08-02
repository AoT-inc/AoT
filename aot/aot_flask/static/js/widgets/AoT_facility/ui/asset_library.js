// ui/asset_library.js — Asset library component (page & modal modes)
// Exposes window.AoTAssetLibrary.
// mode='page'  → standalone listing (already handled in geo_model_assets.html inline JS)
// mode='modal' → called from facility § 3D Preview inline button
(function (global) {
  'use strict';

  let _config = {};
  let _onSelect = null;   // callback(asset) when user clicks "Use in this facility"

  function init(config) {
    _config = config || {};
  }

  /**
   * Open asset library as a modal overlay.
   * @param {function} onSelect  called with selected asset dict
   */
  function openModal(onSelect) {
    _onSelect = onSelect;
    let modal = document.getElementById('aot-asset-lib-modal');
    if (!modal) modal = _buildModal();
    _show(modal, true);
    _loadAndRender(modal.querySelector('#aot-lib-grid'), modal.querySelector('#aot-lib-search'));
  }

  function closeModal() {
    const modal = document.getElementById('aot-asset-lib-modal');
    if (modal) _show(modal, false);
  }

  // Bootstrap when it is there (the app ships it everywhere), plain class
  // toggle otherwise so this stays usable outside the app shell.
  function _show(modal, on) {
    if (global.jQuery && global.jQuery.fn && global.jQuery.fn.modal) {
      global.jQuery(modal).modal(on ? 'show' : 'hide');
    } else {
      modal.classList.toggle('show', on);
      modal.style.display = on ? 'block' : 'none';
    }
  }

  // Shared modal shell (.aot-option-modal) instead of a hand-rolled overlay —
  // same chrome, theming and close behaviour as every other dialog in the app.
  // Card/grid styling lives in static/css/pages/geo-facility.css.
  function _buildModal() {
    const t = (s) => (global._ ? global._(s) : s);
    const modal = document.createElement('div');
    modal.id = 'aot-asset-lib-modal';
    modal.className = 'modal fade aot-option-modal';
    modal.tabIndex = -1;
    modal.setAttribute('role', 'dialog');
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered" role="document">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">${t('3D Asset Library')}</h5>
            <button type="button" class="close" data-dismiss="modal" aria-label="${t('Close')}">
              <span aria-hidden="true">&times;</span>
            </button>
          </div>
          <div class="modal-body">
            <input class="aot-lib-search" id="aot-lib-search" type="text" placeholder="${t('Search by name…')}">
            <div class="aot-lib-grid" id="aot-lib-grid"></div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-sm btn-outline-secondary" data-dismiss="modal">${t('Close')}</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    return modal;
  }

  let _allAssets = [];
  function _loadAndRender(grid, searchEl) {
    grid.innerHTML = '<div style="color:var(--aot-color-text-secondary);text-align:center;padding:2rem;grid-column:1/-1">' + (global._ ? global._('Loading…') : 'Loading…') + '</div>';
    fetch('/api/geo/model_assets')
      .then(r => r.json())
      .then(function (data) {
        _allAssets = data;
        _renderGrid(grid, data);
        if (searchEl) {
          searchEl.oninput = function () {
            const q = searchEl.value.toLowerCase();
            _renderGrid(grid, q ? _allAssets.filter(a => a.name.toLowerCase().includes(q)) : _allAssets);
          };
        }
      })
      .catch(function () {
        grid.innerHTML = '<div style="color:var(--aot-color-danger);grid-column:1/-1;text-align:center;padding:1rem">' + (global._ ? global._('Failed to load') : 'Failed to load') + '</div>';
      });
  }

  function _renderGrid(grid, assets) {
    grid.innerHTML = '';
    if (!assets.length) {
      grid.innerHTML = '<div style="color:var(--aot-color-text-secondary);text-align:center;padding:2rem;grid-column:1/-1">' + (global._ ? global._('No assets registered.') : 'No assets registered.') + '</div>';
      return;
    }
    assets.forEach(function (a) {
      const card = document.createElement('div');
      card.className = 'aot-lib-card';

      const thumb = document.createElement('div');
      thumb.className = 'aot-lib-thumb';
      if (a.preview_png && a.preview_status === 'ok') {
        const img = document.createElement('img');
        img.src = '/static/' + a.preview_png;
        img.alt = a.name;
        thumb.appendChild(img);
      } else {
        thumb.innerHTML = '<span style="font-size:var(--aot-fs-value)">📦</span>';
      }

      const name = document.createElement('div');
      name.className = 'aot-lib-name';
      name.textContent = a.name;

      const kind = document.createElement('div');
      kind.className = 'aot-lib-kind';
      kind.textContent = {
        primitive: (global._ ? global._('Primitive') : 'Primitive'),
        extruded_polygon: (global._ ? global._('Extruded') : 'Extruded'),
        imported_gltf: 'GLTF'
      }[a.kind] || a.kind;

      card.append(thumb, name, kind);
      card.addEventListener('click', function () {
        closeModal();
        if (_onSelect) _onSelect(a);
      });
      grid.appendChild(card);
    });
  }

  global.AoTAssetLibrary = { init, openModal, closeModal };
})(window);
