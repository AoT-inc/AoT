// aot-facility-layer-panel.js
// Provides the facility map with the same functionality as the geo/design map-layer panel.
// Uses State.map (MapLibre GL), State._baseStyleLayerIds, window.AOT_GEO_CONFIG.layers.
(function () {
  'use strict';

  function initFacilityLayerPanel(State) {
    const container = document.getElementById('facility-map-canvas');
    if (!container || document.getElementById('facility-layer-btn')) return;

    // -- Create button -----------------------------------------------------------
    const btn = document.createElement('button');
    btn.id = 'facility-layer-btn';
    btn.className = 'btn btn-white btn-circle';
    btn.title = (window._ ? window._('Map Layers') : 'Map Layers');
    btn.style.cssText = [
      'position:absolute', 'top:10px', 'right:10px', 'z-index:var(--aot-z-fixed-panel)',
      'width:32px', 'height:32px', 'padding:0', 'border-radius:50%',
      'background:#fff', 'border:2px solid rgba(0,0,0,.15)',
      'box-shadow:0 1px 4px rgba(0,0,0,.2)', 'cursor:pointer',
      'display:flex', 'align-items:center', 'justify-content:center'
    ].join(';');
    btn.innerHTML = '<i class="fas fa-layer-group" style="font-size:13px;color:#555;"></i>';
    container.style.position = 'relative';
    container.appendChild(btn);

    // -- Create panel ------------------------------------------------------------
    const panel = document.createElement('div');
    panel.id = 'facility-layer-panel';
    panel.style.cssText = [
      'display:none', 'position:absolute', 'top:10px', 'right:45px',
      'background:white', 'padding:10px', 'border-radius:8px',
      'box-shadow:0 2px 8px rgba(0,0,0,.25)', 'z-index:var(--aot-z-fixed-panel)',
      'max-height:300px', 'overflow-y:auto', 'min-width:200px'
    ].join(';');
    container.appendChild(panel);

    btn.addEventListener('click', () => togglePanel());

    function togglePanel() {
      const hidden = panel.style.display === 'none';
      panel.style.display = hidden ? 'block' : 'none';
      if (hidden) {
        renderPanel();
        registerOutsideClick();
      }
    }

    function registerOutsideClick() {
      const handler = (e) => {
        if (panel.contains(e.target) || btn.contains(e.target)) return;
        panel.style.display = 'none';
        document.removeEventListener('click', handler, true);
      };
      setTimeout(() => document.addEventListener('click', handler, true), 0);
    }

    // -- Render layer panel (same logic as geo/design _toggleLayerPanel) ---------
    function renderPanel() {
      const geoLayers = window.AOT_GEO_CONFIG && window.AOT_GEO_CONFIG.layers;
      if (!geoLayers || geoLayers.length === 0) {
        panel.innerHTML = '<div style="padding:10px;color:#666;">' + (window._ ? window._('No active layers') : 'No active layers') + '</div>';
        return;
      }

      const mlMap = State.map;
      const _getBaseStyleIds = () => State._baseStyleLayerIds || [];

      const _rasterLayerId = (id) => {
        try { return mlMap && mlMap.getLayer(id + '_layer') ? id + '_layer' : null; } catch(e) { return null; }
      };

      const _isVisible = (l) => {
        const lid = _rasterLayerId(l.id);
        if (!lid) return false;
        try { return mlMap.getLayoutProperty(lid, 'visibility') !== 'none'; } catch(e) { return true; }
      };

      const _toMapLibreTiles = (l) => {
        if (l.type === 'wms') {
          return [`/api/geo/proxy/wms/${encodeURIComponent(l.id)}?BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256`];
        }
        let url = (l.url || '').replace(/\{r\}/g, '');
        if (url.includes('{s}')) return ['a', 'b', 'c'].map(s => url.replace(/\{s\}/g, s));
        return [url];
      };

      // 빈 타일 URL(tiles:[''])은 MapLibre 워커가 보이는 타일마다 빈 URL 을
      // 요청하게 만들고, 빈 URL 은 '현재 페이지'(대시보드 HTML, 1.3MB)로
      // 해소된다 → 타일 수만큼 페이지 재요청 → 워커 풀 포화 → 모달 등 클릭
      // 상호작용이 수 초 지연. XYZ({z}/{x}/{y}) 또는 WMS({bbox}) 플레이스홀더가
      // 있는 유효 URL 만 소스로 추가한다.
      const _validTiles = (tiles) => Array.isArray(tiles) && tiles.length > 0 &&
        tiles.every(u => typeof u === 'string' && u.trim() &&
          ((u.indexOf('{z}') !== -1 && u.indexOf('{x}') !== -1 &&
            (u.indexOf('{y}') !== -1 || u.indexOf('{-y}') !== -1)) ||
           u.toLowerCase().indexOf('{bbox') !== -1));

      const _ensureSource = (l) => {
        if (!mlMap.getSource(l.id)) {
          const tiles = _toMapLibreTiles(l);
          if (!_validTiles(tiles)) {
            console.warn('[FacilityLayerPanel] Skipping layer — invalid/empty tile URL:', l.id, JSON.stringify(l.url));
            return;
          }
          mlMap.addSource(l.id, { type: 'raster', tiles: tiles, tileSize: 256 });
        }
      };

      const _hideVectorBase = () => {
        _getBaseStyleIds().forEach(id => {
          try { mlMap.setLayoutProperty(id, 'visibility', 'none'); } catch(e) {}
        });
      };

      const _showVectorBase = () => {
        _getBaseStyleIds().forEach(id => {
          try { mlMap.setLayoutProperty(id, 'visibility', 'visible'); } catch(e) {}
        });
      };

      const _deactivateRasterBase = () => {
        const prev = State._activeRasterBaseId;
        if (prev) {
          try { mlMap.setLayoutProperty(prev + '_layer', 'visibility', 'none'); } catch(e) {}
          State._activeRasterBaseId = null;
        }
      };

      const _activateRasterBase = (l) => {
        if (!mlMap || (!l.url && l.type !== 'wms')) return;
        try {
          _ensureSource(l);
          const lyId = l.id + '_layer';
          const allLayers = (mlMap.getStyle() || {}).layers || [];
          const firstAot = allLayers.find(sl => !_getBaseStyleIds().includes(sl.id));
          const beforeId = firstAot ? firstAot.id : (allLayers.length > 0 ? allLayers[0].id : undefined);
          if (!mlMap.getLayer(lyId)) {
            mlMap.addLayer({ id: lyId, type: 'raster', source: l.id,
              layout: { visibility: 'visible' } }, beforeId);
          } else {
            mlMap.setLayoutProperty(lyId, 'visibility', 'visible');
            if (beforeId) { try { mlMap.moveLayer(lyId, beforeId); } catch(e) {} }
          }
          _hideVectorBase();
          State._activeRasterBaseId = l.id;
          try {
            localStorage.setItem('aot_active_base_id', l.id);
            localStorage.setItem('aot_active_base_type', 'raster');
          } catch(e) {}
        } catch(e) { console.warn('[FacilityLayerPanel] activateRasterBase error:', e.message); }
      };

      const _restoreVectorBase = () => {
        _deactivateRasterBase();
        _showVectorBase();
        try {
          localStorage.setItem('aot_active_base_type', 'vector_default');
          localStorage.removeItem('aot_active_base_id');
        } catch(e) {}
      };

      const _switchVectorBase = (l) => {
        if (!mlMap || !l.url) return;
        _deactivateRasterBase();
        const center = mlMap.getCenter();
        const zoom = mlMap.getZoom();
        const baseIdsNow = _getBaseStyleIds();
        const curStyle = mlMap.getStyle() || {};
        const curSources = curStyle.sources || {};
        const curLayers = curStyle.layers || [];
        const userLayers = curLayers.filter(sl => !baseIdsNow.includes(sl.id));
        const userSourceIds = new Set(userLayers.map(sl => sl.source).filter(Boolean));
        const userSources = {};
        userSourceIds.forEach(sid => { if (curSources[sid]) userSources[sid] = curSources[sid]; });

        let _handled = false;
        let _fallback = null;
        const _onLoad = () => {
          if (_handled) return;
          _handled = true;
          clearTimeout(_fallback);
          try { mlMap.stop(); } catch(e) {}
          mlMap.jumpTo({ center, zoom });
          State._baseStyleLayerIds = (mlMap.getStyle().layers || []).map(sl => sl.id);
          State._activeVectorStyleUrl = l.url;
          State._activeRasterBaseId = null;
          try {
            localStorage.setItem('aot_active_base_id', l.id);
            localStorage.setItem('aot_active_base_type', 'vector_channel');
            localStorage.setItem('aot_active_vector_style', l.url);
            localStorage.removeItem('aot_active_raster_base');
          } catch(e) {}
          Object.entries(userSources).forEach(([sid, def]) => {
            try { if (!mlMap.getSource(sid)) mlMap.addSource(sid, def); } catch(e) {}
          });
          userLayers.forEach(sl => {
            try { if (!mlMap.getLayer(sl.id)) mlMap.addLayer(sl); } catch(e) {}
          });
        };
        mlMap.once('style.load', _onLoad);
        _fallback = setTimeout(() => { if (!_handled && mlMap.isStyleLoaded()) _onLoad(); }, 3000);
        try { mlMap.setStyle(l.url, { diff: false }); } catch(e) {
          clearTimeout(_fallback);
          mlMap.off('style.load', _onLoad);
        }
      };

      const _addOverlay = (l) => {
        if (!mlMap || (!l.url && l.type !== 'wms')) return;
        try {
          _ensureSource(l);
          const lyId = l.id + '_layer';
          if (!mlMap.getLayer(lyId)) {
            mlMap.addLayer({ id: lyId, type: 'raster', source: l.id, layout: { visibility: 'visible' } });
          } else {
            mlMap.setLayoutProperty(lyId, 'visibility', 'visible');
          }
        } catch(e) { console.warn('[FacilityLayerPanel] addOverlay error:', e.message); }
      };

      const _hideOverlay = (l) => {
        const lid = _rasterLayerId(l.id);
        if (lid) { try { mlMap.setLayoutProperty(lid, 'visibility', 'none'); } catch(e) {} }
      };

      const layerById = {};
      geoLayers.forEach(l => { layerById[l.id] = l; });

      let activeRasterBaseId = State._activeRasterBaseId;
      let activeVectorChannelId = null;
      if (!activeRasterBaseId) {
        const savedType = localStorage.getItem('aot_active_base_type');
        const savedId = localStorage.getItem('aot_active_base_id');
        if (savedType === 'raster' && savedId) activeRasterBaseId = savedId;
        else if (savedType === 'vector_channel' && savedId) activeVectorChannelId = savedId;
      } else {
        const savedType = localStorage.getItem('aot_active_base_type');
        const savedId = localStorage.getItem('aot_active_base_id');
        if (savedType === 'vector_channel' && savedId) activeVectorChannelId = savedId;
      }
      const vectorIsActive = !activeRasterBaseId;

      panel.innerHTML = '';
      const groups = { base: [], overlay: [] };
      geoLayers.forEach(l => { groups[l.role === 'base' ? 'base' : 'overlay'].push(l); });

      const labelMap = { base: (window._ ? window._('Base Map') : 'Base Map'), overlay: (window._ ? window._('Overlay') : 'Overlay') };
      ['base', 'overlay'].forEach(role => {
        if (groups[role].length === 0) return;
        const groupDiv = document.createElement('div');
        groupDiv.style.marginBottom = '8px';
        groupDiv.innerHTML = '<div style="font-weight:bold;padding:2px 0;color:#444;font-size:11px;' +
          'text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #eee;margin-bottom:4px;">' +
          labelMap[role] + '</div>';

        if (role === 'base') {
          groups[role].forEach(l => {
            const isActive = l.type === 'vector'
              ? (activeVectorChannelId ? l.id === activeVectorChannelId : vectorIsActive)
              : (l.id === activeRasterBaseId);
            const itemDiv = document.createElement('div');
            itemDiv.style.padding = '3px 0';
            itemDiv.innerHTML = '<label style="cursor:pointer;display:flex;align-items:center;gap:6px;">' +
              '<input type="radio" name="fac-lp-base"' + (isActive ? ' checked' : '') +
              ' data-layer-id="' + l.id + '" data-layer-type="' + l.type + '"> ' +
              '<span style="font-size:13px;">' + (l.name || l.id) + '</span></label>';
            groupDiv.appendChild(itemDiv);
          });
        } else {
          groups[role].forEach(l => {
            const visible = _isVisible(l);
            const itemDiv = document.createElement('div');
            itemDiv.style.padding = '3px 0';
            itemDiv.innerHTML = '<label style="cursor:pointer;display:flex;align-items:center;gap:6px;">' +
              '<input type="checkbox"' + (visible ? ' checked' : '') +
              ' data-layer-id="' + l.id + '"> ' +
              '<span style="font-size:13px;">' + (l.name || l.id) + '</span></label>';
            groupDiv.appendChild(itemDiv);
          });
        }
        panel.appendChild(groupDiv);
      });

      panel.onchange = function(e) {
        const input = e.target;
        if (input.type !== 'checkbox' && input.type !== 'radio') return;
        if (input.type === 'radio') {
          const l = layerById[input.dataset.layerId];
          if (!l) return;
          if (l.type === 'vector') {
            const loadedUrl = State._activeVectorStyleUrl;
            if (l.url && l.url !== loadedUrl) _switchVectorBase(l);
            else _restoreVectorBase();
          } else {
            _deactivateRasterBase();
            _activateRasterBase(l);
          }
          panel.style.display = 'none';
        } else {
          const l = layerById[input.dataset.layerId];
          if (!l) return;
          if (input.checked) _addOverlay(l); else _hideOverlay(l);
        }
      };
    }

  }

  window.FacilityLayerPanel = { init: initFacilityLayerPanel };
})();
