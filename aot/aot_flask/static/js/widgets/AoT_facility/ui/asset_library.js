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
    modal.classList.add('open');
    _loadAndRender(modal.querySelector('#aot-lib-grid'), modal.querySelector('#aot-lib-search'));
  }

  function closeModal() {
    const modal = document.getElementById('aot-asset-lib-modal');
    if (modal) modal.classList.remove('open');
  }

  function _buildModal() {
    const backdrop = document.createElement('div');
    backdrop.id = 'aot-asset-lib-modal';
    backdrop.style.cssText = [
      'display:none','position:fixed','inset:0','background:rgba(0,0,0,0.45)',
      'z-index:var(--aot-z-modal)','align-items:center','justify-content:center',
    ].join(';');
    backdrop.classList.add; // kept for classList.add/remove 'open' toggle

    const style = document.createElement('style');
    style.textContent = `
      #aot-asset-lib-modal.open { display:flex !important; }
      .aot-lib-box { background:#fff; border-radius:12px; padding:1.25rem;
        width:560px; max-width:95vw; max-height:80vh; display:flex; flex-direction:column;
        box-shadow:0 8px 32px rgba(0,0,0,0.2); }
      .aot-lib-box h4 { font-size:var(--aot-fs-title); font-weight:var(--aot-fw-bold); margin:0 0 0.75rem; }
      .aot-lib-search { width:100%; padding:0.38rem 0.65rem; border:1px solid #ccc;
        border-radius:6px; font-size:var(--aot-fs-body); margin-bottom:0.85rem; box-sizing:border-box; }
      .aot-lib-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(120px,1fr));
        gap:0.65rem; overflow-y:auto; flex:1; padding-right:4px; }
      .aot-lib-card { border:1px solid #e5e7eb; border-radius:8px; padding:0.6rem;
        cursor:pointer; transition:box-shadow 0.15s; }
      .aot-lib-card:hover { box-shadow:0 2px 8px rgba(0,112,243,0.2); border-color:#0070f3; }
      .aot-lib-thumb { width:100%; aspect-ratio:1; background:#f3f4f6; border-radius:5px;
        display:flex; align-items:center; justify-content:center; overflow:hidden; margin-bottom:0.4rem; }
      .aot-lib-thumb img { width:100%; height:100%; object-fit:cover; }
      .aot-lib-name { font-size:var(--aot-fs-label); font-weight:var(--aot-fw-semibold); color:#222; word-break:break-all; }
      .aot-lib-kind { font-size:var(--aot-fs-caption); color:#888; }
      .aot-lib-footer { display:flex; justify-content:flex-end; margin-top:0.85rem; }
      .aot-lib-close { background:#f0f0f0; color:#333; border:1px solid #ccc;
        padding:0.38rem 0.9rem; border-radius:6px; cursor:pointer; font-size:var(--aot-fs-label); }
    `;
    document.head.appendChild(style);

    const box = document.createElement('div');
    box.className = 'aot-lib-box';
    box.innerHTML = `
      <h4>${global._ ? global._('3D Asset Library') : '3D Asset Library'}</h4>
      <input class="aot-lib-search" id="aot-lib-search" type="text" placeholder="${global._ ? global._('Search by name…') : 'Search by name…'}">
      <div class="aot-lib-grid" id="aot-lib-grid"></div>
      <div class="aot-lib-footer">
        <button class="aot-lib-close" onclick="AoTAssetLibrary.closeModal()">${global._ ? global._('Close') : 'Close'}</button>
      </div>
    `;

    backdrop.appendChild(box);
    backdrop.addEventListener('click', function (e) {
      if (e.target === backdrop) closeModal();
    });
    document.body.appendChild(backdrop);
    return backdrop;
  }

  let _allAssets = [];
  function _loadAndRender(grid, searchEl) {
    grid.innerHTML = '<div style="color:#aaa;text-align:center;padding:2rem;grid-column:1/-1">' + (global._ ? global._('Loading…') : 'Loading…') + '</div>';
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
        grid.innerHTML = '<div style="color:#e53935;grid-column:1/-1;text-align:center;padding:1rem">' + (global._ ? global._('Failed to load') : 'Failed to load') + '</div>';
      });
  }

  function _renderGrid(grid, assets) {
    grid.innerHTML = '';
    if (!assets.length) {
      grid.innerHTML = '<div style="color:#aaa;text-align:center;padding:2rem;grid-column:1/-1">' + (global._ ? global._('No assets registered.') : 'No assets registered.') + '</div>';
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
