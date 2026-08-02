/* i18n lookup: resolves window._IEC[key] (gettext-injected) with English fallback */
function _T(k,f){var d=(typeof window!=="undefined"&&window._IEC)||{};return (d[k]!=null&&d[k]!=="")?d[k]:f;}
// aot-facility-design.js — Facility Design page (PRD/DESIGN-GEO-FACILITY-001)

// ── EnvelopeUI ────────────────────────────────────────────────────────────────
// Manages cover layers, vent stages, and curtain config for the Envelope section.
(function () {
  'use strict';

  var COVERS_OUTER = [
    { v: 'vinyl_single', l: 'vinyl_single' },
    { v: 'vinyl_double', l: 'vinyl_double' },
    { v: 'po_film',      l: 'po_film' },
    { v: 'polycarbonate', l: 'polycarbonate' },
    { v: 'glass',        l: 'glass' }
  ];
  var COVERS_INNER = [
    { v: 'vinyl_single',     l: 'vinyl_single' },
    { v: 'non_woven_fabric', l: 'non_woven_fabric' },
    { v: 'pe_film',          l: 'pe_film' },
    { v: 'polycarbonate',    l: 'polycarbonate' },
    { v: 'air_cushion',      l: 'air_cushion' }
  ];

  var _layers = [
    { id: 'outer', type: 'full', role: 'outer', cover: 'vinyl_double' }
  ];

  function _sel(opts, selected) {
    return opts.map(function (o) {
      return '<option value="' + o.v + '"' + (o.v === selected ? ' selected' : '') + '>' + o.l + '</option>';
    }).join('');
  }

  function _uid() {
    return 'L' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
  }

  function _notify() {
    document.dispatchEvent(new CustomEvent('envelope-changed'));
  }

  // ── Layer card renderer ────────────────────────────────────
  function _renderLayers() {
    var container = document.getElementById('envelope-layers-list');
    if (!container) return;
    container.innerHTML = '';

    _layers.forEach(function (layer) {
      var card = document.createElement('div');
      card.className = 'env-layer-card';
      card.setAttribute('data-layer-id', layer.id);
      card.style.cssText = 'border:1px solid var(--aot-border-light);border-radius:10px;padding:0.55rem 0.75rem;margin-bottom:8px;';

      if (layer.type === 'full') {
        var covers = layer.role === 'outer' ? COVERS_OUTER : COVERS_INNER;
        var label  = layer.role === 'outer' ? _T('env_outer_full','Outer (full)') : _T('env_inner_full','Inner (full)');
        var icon   = layer.role === 'outer' ? '🏠' : '🪟';
        var airgapHtml = (layer.role === 'inner')
          ? '<span style="font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);white-space:nowrap;margin-left:4px;">'+_T('insp_airgap','Airgap')+'&nbsp;' +
            '<input type="number" class="env-layer-airgap form-control aot-modern-input" data-layer-id="' + layer.id + '" ' +
            'value="' + (layer.air_gap_m != null ? layer.air_gap_m : 0.5) + '" step="0.1" min="0.1" ' +
            'style="width:58px;height:28px;display:inline-block;">&nbsp;m</span>'
          : '';
        var removeBtn = (layer.role !== 'outer')
          ? '<button class="btn btn-sm btn-outline-danger" style="margin-left:auto;padding:0 8px;height:28px;font-size:var(--aot-font-size-sm);" ' +
            'onclick="EnvelopeUI.removeLayer(\'' + layer.id + '\')">✕</button>'
          : '';
        card.innerHTML =
          '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
          '<span style="font-weight:700;font-size:var(--aot-font-size-sm);flex:0 0 auto;">' + icon + ' ' + label + '</span>' +
          '<select class="form-control aot-modern-select env-layer-cover" data-layer-id="' + layer.id + '" ' +
          'style="flex:1;max-width:180px;height:30px;font-size:var(--aot-font-size-sm);">' +
          _sel(covers, layer.cover) + '</select>' +
          airgapHtml + removeBtn + '</div>';

      } else if (layer.type === 'side_only') {
        // Model uses pure XYZ axis labels. x_pos/x_neg = long side walls,
        // y_pos/y_neg = gable end walls. Legacy compass strings are accepted
        // and translated to axis labels for backward compatibility.
        var sideLabels = { x_neg: 'X−', x_pos: 'X+', y_pos: 'Y+', y_neg: 'Y−' };
        var _toAxis = function (s) {
          if (s === 'south') return 'y_pos'; if (s === 'north') return 'y_neg';
          if (s === 'east')  return 'x_pos'; if (s === 'west')  return 'x_neg';
          return s;
        };
        var _layerSides = (layer.sides || []).map(_toAxis);
        var sidesHtml = ['x_neg', 'x_pos', 'y_pos', 'y_neg'].map(function (s) {
          var checked = _layerSides.indexOf(s) >= 0 ? ' checked' : '';
          return '<label style="font-size:var(--aot-font-size-sm);cursor:pointer;display:flex;align-items:center;gap:4px;">' +
            '<input type="checkbox" class="env-layer-side" data-layer-id="' + layer.id + '" value="' + s + '"' + checked + '>' +
            sideLabels[s] + '</label>';
        }).join('');
        card.innerHTML =
          '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
          '<span style="font-weight:700;font-size:var(--aot-font-size-sm);flex:0 0 auto;">'+_T('env_side_reinf','Side reinforcement')+'</span>' +
          '<select class="form-control aot-modern-select env-layer-cover" data-layer-id="' + layer.id + '" ' +
          'style="width:140px;height:30px;font-size:var(--aot-font-size-sm);">' + _sel(COVERS_OUTER, layer.cover) + '</select>' +
          '<div style="display:flex;gap:8px;align-items:center;">' + sidesHtml + '</div>' +
          '<span style="font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);white-space:nowrap;">'+_T('insp_width','Width')+'&nbsp;' +
          '<input type="number" class="env-layer-thickness form-control aot-modern-input" data-layer-id="' + layer.id + '" ' +
          'value="' + (layer.thickness_m || 1.0) + '" step="0.1" min="0.1" style="width:52px;height:28px;display:inline-block;">&nbsp;m</span>' +
          '<button class="btn btn-sm btn-outline-danger" style="margin-left:auto;padding:0 8px;height:28px;font-size:var(--aot-font-size-sm);" ' +
          'onclick="EnvelopeUI.removeLayer(\'' + layer.id + '\')">✕</button></div>';

      } else if (layer.type === 'front_only') {
        var frontLabels = { y_pos: 'Y+', y_neg: 'Y−' };
        var _toAxisF = function (s) {
          if (s === 'south') return 'y_pos'; if (s === 'north') return 'y_neg';
          return s;
        };
        var _layerFrontSides = (layer.sides || []).map(_toAxisF);
        var frontSidesHtml = ['y_pos', 'y_neg'].map(function (s) {
          var checked = _layerFrontSides.indexOf(s) >= 0 ? ' checked' : '';
          return '<label style="font-size:var(--aot-font-size-sm);cursor:pointer;display:flex;align-items:center;gap:4px;">' +
            '<input type="checkbox" class="env-layer-front-side" data-layer-id="' + layer.id + '" value="' + s + '"' + checked + '>' +
            frontLabels[s] + '</label>';
        }).join('');
        card.innerHTML =
          '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
          '<span style="font-weight:700;font-size:var(--aot-font-size-sm);flex:0 0 auto;">'+_T('env_front_reinf','Front reinforcement')+'</span>' +
          '<div style="display:flex;gap:8px;align-items:center;">' + frontSidesHtml + '</div>' +
          '<span style="font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);white-space:nowrap;">'+_T('insp_depth','Depth')+'&nbsp;' +
          '<input type="number" class="env-layer-depth form-control aot-modern-input" data-layer-id="' + layer.id + '" ' +
          'value="' + (layer.depth_m || 3.0) + '" step="0.5" min="0.5" style="width:52px;height:28px;display:inline-block;">&nbsp;m</span>' +
          '<button class="btn btn-sm btn-outline-danger" style="margin-left:auto;padding:0 8px;height:28px;font-size:var(--aot-font-size-sm);" ' +
          'onclick="EnvelopeUI.removeLayer(\'' + layer.id + '\')">✕</button></div>';
      }
      container.appendChild(card);
    });

    var hasInner = _layers.some(function (l) { return l.role === 'inner'; });
    var addInnerBtn = document.getElementById('btn-add-inner-layer');
    if (addInnerBtn) {
      addInnerBtn.disabled = hasInner;
      addInnerBtn.style.opacity = hasInner ? '0.4' : '';
    }
  }

  // ── Vent stage renderer ────────────────────────────────────
  function _renderVentStages(existingStages) {
    var stageCount = parseInt(
      ((document.querySelector('input[name="vent-stages"]:checked') || {}).value || '1'), 10);
    var container = document.getElementById('vent-stage-rows');
    if (!container) return;
    if (stageCount < 2) { container.innerHTML = ''; return; }

    var prev = [];
    container.querySelectorAll('.vent-stage-row').forEach(function (r, i) {
      prev[i] = {
        height_m:    parseFloat((r.querySelector('.vent-stage-height') || {}).value) || 1.2,
        from_floor_m: parseFloat((r.querySelector('.vent-stage-floor') || {}).value) || (i === 0 ? 0.3 : 1.6)
      };
    });
    var src = existingStages || prev;
    var defaults = [{ height_m: 1.2, from_floor_m: 0.3 }, { height_m: 1.2, from_floor_m: 1.6 }];
    var names = [_T('stage_lower','Lower'), _T('stage_upper','Upper')];
    container.innerHTML = '';
    for (var i = 0; i < stageCount; i++) {
      var v = src[i] || defaults[i];
      var row = document.createElement('div');
      row.className = 'aot-modal-option-row vent-stage-row';
      row.style.cssText = 'padding-left:0.5rem;border-bottom:none;';
      row.innerHTML =
        '<div class="aot-modal-option-label" style="font-size:var(--aot-font-size-sm);font-weight:500;color:var(--aot-color-text-secondary);">' + names[i] + '</div>' +
        '<div style="display:flex;gap:8px;align-items:center;font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);">' +
        ''+_T('height','height')+'&nbsp;<input type="number" class="form-control aot-modern-input vent-stage-height" value="' + v.height_m +
        '" step="0.1" min="0.1" style="width:58px;height:28px;display:inline-block;">&nbsp;m' +
        '&nbsp;&nbsp;'+_T('vent_start','Start')+'&nbsp;<input type="number" class="form-control aot-modern-input vent-stage-floor" value="' + v.from_floor_m +
        '" step="0.1" min="0" style="width:58px;height:28px;display:inline-block;">&nbsp;m</div>';
      container.appendChild(row);
    }
  }

  // ── Public API ─────────────────────────────────────────────
  function addSideOnlyLayer() {
    _layers.push({ id: _uid(), type: 'side_only', role: 'reinforcement',
      cover: 'pe_film', sides: ['x_pos', 'x_neg'], thickness_m: 1.0, height_m: 2.0 });
    _renderLayers();
    _notify();
  }

  function addFrontOnlyLayer() {
    _layers.push({ id: _uid(), type: 'front_only', role: 'reinforcement',
      sides: ['y_pos', 'y_neg'], depth_m: 3.0 });
    _renderLayers();
    _notify();
  }

  function addInnerLayer() {
    if (_layers.some(function (l) { return l.role === 'inner'; })) return;
    _layers.push({ id: _uid(), type: 'full', role: 'inner',
      cover: 'non_woven_fabric', air_gap_m: 0.5 });
    _renderLayers();
    _notify();
  }

  function removeLayer(id) {
    _layers = _layers.filter(function (l) { return l.id !== id; });
    _renderLayers();
    _notify();
  }

  function onVentToggle() {
    var enabled = !!((document.getElementById('outer-side-vent') || {}).checked);
    var detail = document.getElementById('outer-side-vent-detail');
    if (detail) detail.style.display = enabled ? '' : 'none';
    _notify();
  }

  function onRoofVentToggle() {
    var enabled = !!((document.getElementById('outer-roof-vent') || {}).checked);
    var detail = document.getElementById('outer-roof-vent-detail');
    if (detail) detail.style.display = enabled ? '' : 'none';
    _notify();
  }

  // Shade-curtain toggle had no handler previously, so envelope-changed did
  // not fire and _renderEnvelopeFittings was skipped. Without an envelope
  // fitting the hardcoded fallback (buildCurtain w=totalWidth*0.02) rendered
  // a thin sliver at the left edge — the "stray long thin model on one side of the outer ceiling".
  function onCurtainShadeToggle() {
    _notify();
  }

  function onCurtainCeilingToggle() {
    var enabled = !!((document.getElementById('curtain-thermal-ceiling') || {}).checked);
    var detail = document.getElementById('curtain-ceiling-detail');
    if (detail) detail.style.display = enabled ? '' : 'none';
    _notify();
  }

  function onCurtainWallToggle() {
    var enabled = !!((document.getElementById('curtain-thermal-wall') || {}).checked);
    var detail = document.getElementById('curtain-wall-detail');
    if (detail) detail.style.display = enabled ? '' : 'none';
    _notify();
  }

  // ── Read UI → envelope object ──────────────────────────────
  function read() {
    _layers = _layers.map(function (layer) {
      var coverEl = document.querySelector('.env-layer-cover[data-layer-id="' + layer.id + '"]');
      if (coverEl) layer.cover = coverEl.value;
      if (layer.type === 'full' && layer.role === 'inner') {
        var agEl = document.querySelector('.env-layer-airgap[data-layer-id="' + layer.id + '"]');
        if (agEl) layer.air_gap_m = parseFloat(agEl.value) || 0.5;
      }
      if (layer.type === 'side_only') {
        layer.sides = [];
        document.querySelectorAll('.env-layer-side[data-layer-id="' + layer.id + '"]:checked')
          .forEach(function (el) { layer.sides.push(el.value); });
        var tEl = document.querySelector('.env-layer-thickness[data-layer-id="' + layer.id + '"]');
        if (tEl) layer.thickness_m = parseFloat(tEl.value) || 1.0;
      }
      if (layer.type === 'front_only') {
        layer.sides = [];
        document.querySelectorAll('.env-layer-front-side[data-layer-id="' + layer.id + '"]:checked')
          .forEach(function (el) { layer.sides.push(el.value); });
        var dEl = document.querySelector('.env-layer-depth[data-layer-id="' + layer.id + '"]');
        if (dEl) layer.depth_m = parseFloat(dEl.value) || 3.0;
      }
      return layer;
    });

    var ventEnabled = !!((document.getElementById('outer-side-vent') || {}).checked);
    var stageCount  = parseInt(
      ((document.querySelector('input[name="vent-stages"]:checked') || {}).value || '1'), 10);
    var ventStages = [];
    var stageIds = ['lower', 'upper'];
    document.querySelectorAll('.vent-stage-row').forEach(function (row, i) {
      ventStages.push({
        id: stageIds[i] || ('stage' + i),
        height_m:    parseFloat((row.querySelector('.vent-stage-height') || {}).value) || 1.2,
        from_floor_m: parseFloat((row.querySelector('.vent-stage-floor') || {}).value) || 0.3
      });
    });
    if (ventStages.length === 0) ventStages = [{ id: 'lower', height_m: 1.2, from_floor_m: 0.3 }];

    var roofEnabled  = !!((document.getElementById('outer-roof-vent') || {}).checked);
    var roofPlacement = ((document.querySelector('input[name="roof-vent-placement"]:checked') || {}).value) || 'center';
    var ceilEnabled  = !!((document.getElementById('curtain-thermal-ceiling') || {}).checked);
    var ceilLayers   = parseInt(
      ((document.querySelector('input[name="curtain-ceiling-layers"]:checked') || {}).value || '1'), 10);
    var wallEnabled  = !!((document.getElementById('curtain-thermal-wall') || {}).checked);
    var shadeEnabled = !!((document.getElementById('curtain-shade') || {}).checked);

    return {
      layers: JSON.parse(JSON.stringify(_layers)),
      side_vent: { outer: { enabled: ventEnabled, stages: ventStages } },
      roof_vent: { outer: { enabled: roofEnabled, placement: roofPlacement } },
      curtain: {
        thermal_ceiling: { enabled: ceilEnabled, layers: ceilLayers },
        thermal_wall:    { enabled: wallEnabled },
        shade:           { enabled: shadeEnabled }
      }
    };
  }

  // ── Fill UI from envelope object (old or new format) ──────
  function fill(env) {
    if (!env) return;
    if (env.layer_count != null && !env.layers) env = _migrate(env);

    _layers = (Array.isArray(env.layers) && env.layers.length > 0)
      ? JSON.parse(JSON.stringify(env.layers))
      : [{ id: 'outer', type: 'full', role: 'outer', cover: 'vinyl_double' }];
    _renderLayers();

    // side vent
    var sv = (env.side_vent && env.side_vent.outer) || {};
    var ventEl = document.getElementById('outer-side-vent');
    if (ventEl) ventEl.checked = !!sv.enabled;
    var ventDetail = document.getElementById('outer-side-vent-detail');
    if (ventDetail) ventDetail.style.display = sv.enabled ? '' : 'none';

    var stages = sv.stages || [];
    var stageCount = Math.max(stages.length, 1);
    var stageRadio = document.querySelector('input[name="vent-stages"][value="' + stageCount + '"]');
    if (stageRadio) {
      stageRadio.checked = true;
      document.querySelectorAll('input[name="vent-stages"]').forEach(function (r) {
        var lbl = r.parentElement;
        if (lbl) { if (r.checked) lbl.classList.add('active'); else lbl.classList.remove('active'); }
      });
    }
    _renderVentStages(stages);

    // roof vent
    var rv = (env.roof_vent && env.roof_vent.outer) || {};
    var roofEl = document.getElementById('outer-roof-vent');
    if (roofEl) roofEl.checked = !!rv.enabled;
    var roofDetail = document.getElementById('outer-roof-vent-detail');
    if (roofDetail) roofDetail.style.display = rv.enabled ? '' : 'none';
    var roofPlaceR = document.querySelector('input[name="roof-vent-placement"][value="' + (rv.placement || 'center') + '"]');
    if (roofPlaceR) {
      roofPlaceR.checked = true;
      document.querySelectorAll('input[name="roof-vent-placement"]').forEach(function (r) {
        var lbl = r.parentElement;
        if (lbl) { if (r.checked) lbl.classList.add('active'); else lbl.classList.remove('active'); }
      });
    }

    // curtain
    var curtain = env.curtain || {};
    var tc = curtain.thermal_ceiling || {};
    var tw = curtain.thermal_wall    || {};
    var sh = curtain.shade           || {};

    var ceilEl = document.getElementById('curtain-thermal-ceiling');
    if (ceilEl) ceilEl.checked = !!tc.enabled;
    var ceilDetail = document.getElementById('curtain-ceiling-detail');
    if (ceilDetail) ceilDetail.style.display = tc.enabled ? '' : 'none';
    var ceilR = document.querySelector('input[name="curtain-ceiling-layers"][value="' + (tc.layers || 1) + '"]');
    if (ceilR) ceilR.checked = true;

    var wallEl = document.getElementById('curtain-thermal-wall');
    if (wallEl) wallEl.checked = !!tw.enabled;

    var shadeEl = document.getElementById('curtain-shade');
    if (shadeEl) shadeEl.checked = !!sh.enabled;
  }

  // ── Migrate old flat envelope → new layers format ─────────
  function _migrate(old) {
    var layers = [{ id: 'outer', type: 'full', role: 'outer',
      cover: (old.outer && old.outer.cover_material) || 'vinyl_double' }];
    if ((old.layer_count || 1) >= 2 && old.inner) {
      layers.push({ id: 'inner', type: 'full', role: 'inner',
        cover: old.inner.cover_material || 'non_woven_fabric',
        air_gap_m: old.inner.air_gap_m || 0.5 });
    }
    var oSV = (old.outer && old.outer.side_vent) || {};
    var oRV = (old.outer && old.outer.roof_vent) || {};
    var oc  = old.curtain || {};
    return {
      layers: layers,
      side_vent: { outer: { enabled: !!oSV.enabled,
        stages: [{ id: 'lower', height_m: 1.2, from_floor_m: 0.3 }] } },
      roof_vent: { outer: { enabled: !!oRV.enabled } },
      curtain: {
        thermal_ceiling: { enabled: !!oc.thermal, layers: 1 },
        thermal_wall:    { enabled: false, sides: [] },
        shade:           { enabled: !!oc.shade }
      }
    };
  }

  // ── Init (called from DOMContentLoaded) ───────────────────
  function init() {
    _renderLayers();
    _renderVentStages();

    document.querySelectorAll('input[name="vent-stages"]').forEach(function (r) {
      r.addEventListener('change', function () {
        document.querySelectorAll('input[name="vent-stages"]').forEach(function (rr) {
          var lbl = rr.parentElement;
          if (lbl) { if (rr.checked) lbl.classList.add('active'); else lbl.classList.remove('active'); }
        });
        _renderVentStages();
        // Stage count/height does not change 3D geometry — emit lightweight event
        // so compute runs but the WebGL scene is NOT disposed and rebuilt.
        document.dispatchEvent(new CustomEvent('envelope-data-changed'));
      });
    });

    // Delegate events for dynamically created layer inputs
    document.addEventListener('change', function (e) {
      if (!e.target) return;
      if (e.target.classList.contains('env-layer-cover')      ||
          e.target.classList.contains('env-layer-side')       ||
          e.target.classList.contains('env-layer-front-side') ||
          e.target.name === 'curtain-ceiling-layers' ||
          e.target.name === 'roof-vent-placement') {
        // Keep .active class in sync for roof-vent-placement radios so the
        // bootstrap btn-group highlight reflects the current selection.
        if (e.target.name === 'roof-vent-placement') {
          document.querySelectorAll('input[name="roof-vent-placement"]').forEach(function (r) {
            var lbl = r.parentElement;
            if (lbl) { if (r.checked) lbl.classList.add('active'); else lbl.classList.remove('active'); }
          });
        }
        _notify();
      }
    });
    document.addEventListener('input', function (e) {
      if (!e.target) return;
      if (e.target.classList.contains('env-layer-airgap')    ||
          e.target.classList.contains('env-layer-thickness')  ||
          e.target.classList.contains('env-layer-depth')      ||
          e.target.classList.contains('env-layer-height')) {
        _notify();
      }
      if (e.target.classList.contains('vent-stage-height')    ||
          e.target.classList.contains('vent-stage-floor')) {
        document.dispatchEvent(new CustomEvent('envelope-data-changed'));
      }
    });
  }

  window.EnvelopeUI = {
    addSideOnlyLayer:  addSideOnlyLayer,
    addFrontOnlyLayer: addFrontOnlyLayer,
    addInnerLayer:     addInnerLayer,
    removeLayer:      removeLayer,
    onVentToggle:     onVentToggle,
    onRoofVentToggle: onRoofVentToggle,
    onCurtainCeilingToggle: onCurtainCeilingToggle,
    onCurtainWallToggle:    onCurtainWallToggle,
    onCurtainShadeToggle:   onCurtainShadeToggle,
    read: read,
    fill: fill,
    init: init
  };
})();

// ── ActuatorUI ────────────────────────────────────────────────────────────────
// Manages actuator instances: kind, device mapping, mount position, specs.
(function () {
  'use strict';

  var _instances = [];   // array of actuator objects
  var _devices   = [];   // available output devices from /api/geo/devices

  // Mount targets use axis-based labels (x_pos/x_neg = long walls,
  // y_pos/y_neg = gable end walls). Legacy compass-named values from saved
  // facilities are translated to axis labels at the consumer site.
  var KIND_META = {
    side_window_motor:    { label: _T('am_side_window_motor','Side window motor'),    icon: '🪟', specs: ['stroke_m','speed_m_per_min'],       mount: ['y_neg','y_pos','x_pos','x_neg'], useStage: true },
    roof_vent_motor:      { label: _T('am_roof_vent_motor','Roof vent motor'),  icon: '🔲', specs: ['stroke_m','speed_m_per_min'],       mount: ['y_neg','y_pos','x_pos','x_neg','roof'] },
    thermal_curtain_motor:{ label: _T('am_thermal_curtain_motor','Thermal curtain motor'),icon: '🪢', specs: ['speed_m_per_min','coverage_pct'],   mount: ['ceiling','y_neg','y_pos','x_pos','x_neg'], useStage: true },
    shade_curtain_motor:  { label: _T('am_shade_curtain_motor','Shade curtain motor'),icon: '🪢', specs: ['speed_m_per_min','coverage_pct'],   mount: ['ceiling'] },
    exhaust_fan:          { label: _T('am_exhaust_fan','Exhaust fan'),       icon: '💨', specs: ['airflow_cmh','power_w'],            mount: ['y_neg','y_pos','x_pos','x_neg','roof'], useElevation: true },
    circulation_fan:      { label: _T('am_circ_fan','Circulation fan'),       icon: '🌀', specs: ['airflow_cmh','power_w'],            mount: ['y_neg','y_pos','x_pos','x_neg','roof','ceiling'], useElevation: true },
    heater:               { label: _T('m_heater','Heater'),         icon: '🔥', specs: ['capacity_kw','fuel'],               mount: [] },
    cooler:               { label: _T('am_cooler','Cooler'),       icon: '❄️', specs: ['capacity_kw','power_w'],            mount: [] },
    heat_pump:            { label: _T('am_heat_pump','Heat pump'),     icon: '⚡', specs: ['capacity_kw','power_w'],            mount: [] },
    irrigation_valve:     { label: _T('am_irr_valve','Irrigation valve'),     icon: '💧', specs: ['flow_lph','pressure_kpa'],          mount: [] }
  };

  var SPEC_META = {
    stroke_m:         { label: _T('spec_stroke','Stroke'), unit: 'm',      type: 'number', step: 0.1, min: 0.1 },
    speed_m_per_min:  { label: _T('spec_speed','Speed'), unit: 'm/min',  type: 'number', step: 0.1, min: 0.1 },
    coverage_pct:     { label: _T('spec_coverage','Coverage'), unit: '%',    type: 'number', step: 1,   min: 0, max: 100 },
    airflow_cmh:      { label: _T('spec_airflow','Airflow'), unit: '㎥/h',   type: 'number', step: 100, min: 0 },
    power_w:          { label: _T('spec_power','Power'), unit: 'W',      type: 'number', step: 10,  min: 0 },
    capacity_kw:      { label: _T('spec_capacity','Capacity'), unit: 'kW',     type: 'number', step: 0.1, min: 0 },
    fuel:             { label: _T('spec_fuel','Fuel'), unit: '',       type: 'select', options: ['gas','oil','electric','biomass'] },
    flow_lph:         { label: _T('spec_flow_lph','Flow'), unit: 'L/h',    type: 'number', step: 10,  min: 0 },
    pressure_kpa:     { label: _T('spec_pressure','Pressure'), unit: 'kPa',    type: 'number', step: 1,   min: 0 }
  };

  // Wall labels use XYZ axis identifiers. Compass aliases retained for legacy
  // saved data that still references north/south/east/west.
  var WALL_LABELS = {
    x_neg: 'X−', x_pos: 'X+', y_pos: 'Y+', y_neg: 'Y−',
    roof: _T('f_roof','Roof'), ceiling: _T('env_ceiling','Ceiling'),
    north: 'Y−', south: 'Y+', east: 'X+', west: 'X−'
  };
  var STAGE_OPTIONS = ['lower','upper','single'];

  function _uid() {
    return 'A' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
  }

  function _notify() {
    document.dispatchEvent(new CustomEvent('actuator-changed'));
  }

  // ── Device <select> options html ──────────────────────────
  function _deviceOptions(selectedUuid) {
    var html = '<option value="">'+_T('unlinked','— Unlinked —')+'</option>';
    _devices.forEach(function (d) {
      var sel = d.unique_id === selectedUuid ? ' selected' : '';
      html += '<option value="' + d.unique_id + '"' + sel + '>' +
        (d.name || d.unique_id) + ' (' + (d.type || '') + ')</option>';
    });
    return html;
  }

  // ── Render a single actuator card ─────────────────────────
  function _cardHtml(act) {
    var meta = KIND_META[act.kind] || { label: act.kind, icon: '⚙️', specs: [], mount: [] };
    var id   = act.id;

    // Device row
    var html = '<div class="act-card" data-act-id="' + id + '" ' +
      'style="border:1px solid var(--aot-border-light);border-radius:10px;padding:0.55rem 0.75rem;margin-bottom:8px;">';

    // Header: icon + label + remove
    html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">' +
      '<span style="font-size:var(--aot-font-size-base);">' + meta.icon + '</span>' +
      '<span style="font-weight:700;font-size:var(--aot-font-size-sm);flex:1;">' + meta.label + '</span>' +
      '<button class="btn btn-sm btn-outline-danger" style="padding:0 7px;height:26px;font-size:var(--aot-font-size-sm);" ' +
      'onclick="ActuatorUI.remove(\'' + id + '\')">✕</button></div>';

    // Row 1: device selector
    html += '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px;">' +
      '<span style="font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);white-space:nowrap;">'+_T('insp_device','Device:')+'</span>' +
      '<select class="form-control aot-modern-select act-device" data-act-id="' + id + '" ' +
      'style="flex:1;min-width:160px;height:28px;font-size:var(--aot-font-size-sm);">' +
      _deviceOptions(act.device_uuid) + '</select></div>';

    // Row 2: mount (wall) + elevation
    if (meta.mount && meta.mount.length > 0) {
      var mountSel = '<select class="form-control aot-modern-select act-mount-wall" data-act-id="' + id + '" ' +
        'style="width:90px;height:28px;font-size:var(--aot-font-size-sm);">';
      meta.mount.forEach(function (w) {
        mountSel += '<option value="' + w + '"' + (w === (act.mount && act.mount.wall) ? ' selected' : '') + '>' +
          (WALL_LABELS[w] || w) + '</option>';
      });
      mountSel += '</select>';

      var elevHtml = '';
      if (meta.useElevation) {
        var elev = (act.mount && act.mount.elevation_m != null) ? act.mount.elevation_m : '';
        elevHtml = '<span style="font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);white-space:nowrap;margin-left:4px;">'+_T('height','height')+'&nbsp;' +
          '<input type="number" class="form-control aot-modern-input act-mount-elev" data-act-id="' + id + '" ' +
          'value="' + elev + '" step="0.1" min="0" style="width:55px;height:28px;display:inline-block;">&nbsp;m</span>';
      }

      var stageHtml = '';
      if (meta.useStage) {
        var stageSel = '<select class="form-control aot-modern-select act-stage-ref" data-act-id="' + id + '" ' +
          'style="width:80px;height:28px;font-size:var(--aot-font-size-sm);">' +
          '<option value="">—</option>';
        STAGE_OPTIONS.forEach(function (s) {
          stageSel += '<option value="' + s + '"' + (s === act.stage_ref ? ' selected' : '') + '>' + s + '</option>';
        });
        stageSel += '</select>';
        stageHtml = '<span style="font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);margin-left:4px;">'+_T('insp_stage','Stage:')+'&nbsp;</span>' + stageSel;
      }

      html += '<div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin-bottom:4px;">' +
        '<span style="font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);">'+_T('insp_location','Location:')+'</span>' + mountSel + elevHtml + stageHtml + '</div>';
    }

    // Row 3: specs
    if (meta.specs && meta.specs.length > 0) {
      html += '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
        '<span style="font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);">'+_T('insp_perf','Performance:')+'</span>';
      meta.specs.forEach(function (sk) {
        var sm = SPEC_META[sk];
        if (!sm) return;
        var val = (act.specs && act.specs[sk] != null) ? act.specs[sk] : '';
        if (sm.type === 'select') {
          var optHtml = sm.options.map(function (o) {
            return '<option value="' + o + '"' + (o === val ? ' selected' : '') + '>' + o + '</option>';
          }).join('');
          html += '<span style="font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);white-space:nowrap;">' + sm.label + ':&nbsp;' +
            '<select class="form-control aot-modern-select act-spec" data-act-id="' + id + '" data-spec-key="' + sk + '" ' +
            'style="width:90px;height:26px;font-size:var(--aot-font-size-sm);">' + optHtml + '</select></span>';
        } else {
          html += '<span style="font-size:var(--aot-font-size-sm);color:var(--aot-color-text-secondary);white-space:nowrap;">' + sm.label + ':&nbsp;' +
            '<input type="number" class="form-control aot-modern-input act-spec" data-act-id="' + id + '" data-spec-key="' + sk + '" ' +
            'value="' + val + '" step="' + sm.step + '" min="' + (sm.min || 0) + '" ' +
            (sm.max != null ? 'max="' + sm.max + '" ' : '') +
            'style="width:68px;height:26px;display:inline-block;">&nbsp;' + sm.unit + '</span>';
        }
      });
      html += '</div>';
    }

    html += '</div>';
    return html;
  }

  // ── Re-render all cards ───────────────────────────────────
  function _render() {
    var container = document.getElementById('actuator-list');
    if (!container) return;
    if (_instances.length === 0) {
      container.innerHTML = '<div style="color:var(--aot-color-text-secondary);font-size:var(--aot-font-size-sm);padding:0.4rem 0;">'+_T('no_actuators','No actuators. Add one below.')+'</div>';
      return;
    }
    container.innerHTML = _instances.map(_cardHtml).join('');
  }

  // ── Public API ─────────────────────────────────────────────
  function add(kind) {
    var meta = KIND_META[kind] || {};
    var defaultMount = (meta.mount && meta.mount[0]) || null;
    _instances.push({
      id: _uid(), kind: kind, device_uuid: null,
      stage_ref: null,
      mount: defaultMount ? { wall: defaultMount } : {},
      specs: {}
    });
    _render();
    _notify();
  }

  function remove(id) {
    _instances = _instances.filter(function (a) { return a.id !== id; });
    _render();
    _notify();
  }

  function setDevices(devices) {
    _devices = devices || [];
    _render();
  }

  // Sync DOM → _instances, then return copy
  function read() {
    _instances = _instances.map(function (act) {
      var devEl  = document.querySelector('.act-device[data-act-id="' + act.id + '"]');
      var wallEl = document.querySelector('.act-mount-wall[data-act-id="' + act.id + '"]');
      var elevEl = document.querySelector('.act-mount-elev[data-act-id="' + act.id + '"]');
      var stgEl  = document.querySelector('.act-stage-ref[data-act-id="' + act.id + '"]');
      if (devEl)  act.device_uuid = devEl.value || null;
      if (wallEl) act.mount = act.mount || {};
      if (wallEl) act.mount.wall = wallEl.value || null;
      if (elevEl && elevEl.value !== '') act.mount.elevation_m = parseFloat(elevEl.value);
      if (stgEl)  act.stage_ref = stgEl.value || null;
      act.specs = act.specs || {};
      document.querySelectorAll('.act-spec[data-act-id="' + act.id + '"]').forEach(function (el) {
        var sk = el.dataset.specKey;
        if (!sk) return;
        var sm = SPEC_META[sk];
        if (sm && sm.type === 'select') {
          act.specs[sk] = el.value || null;
        } else {
          act.specs[sk] = el.value !== '' ? parseFloat(el.value) : null;
        }
      });
      return act;
    });
    return JSON.parse(JSON.stringify(_instances));
  }

  function fill(actuators) {
    if (!actuators) return;
    // Handle old dict format {key: device_uuid}
    if (!Array.isArray(actuators)) {
      _instances = [];
      Object.entries(actuators).forEach(function (entry) {
        var key = entry[0], uuid = entry[1];
        if (!uuid) return;
        var kind = key; // keep old key as kind (best-effort)
        _instances.push({ id: _uid(), kind: kind, device_uuid: uuid, stage_ref: null, mount: {}, specs: {} });
      });
    } else {
      _instances = JSON.parse(JSON.stringify(actuators));
      // Ensure each has id
      _instances.forEach(function (a) { if (!a.id) a.id = _uid(); });
    }
    _render();
  }

  function init() {
    _render();
    // Delegate change/input events for dynamically created actuator inputs
    document.addEventListener('change', function (e) {
      if (!e.target) return;
      if (e.target.classList.contains('act-device')     ||
          e.target.classList.contains('act-mount-wall') ||
          e.target.classList.contains('act-stage-ref')  ||
          (e.target.classList.contains('act-spec') && e.target.tagName === 'SELECT')) {
        _notify();
      }
    });
    document.addEventListener('input', function (e) {
      if (!e.target) return;
      if (e.target.classList.contains('act-mount-elev') ||
          (e.target.classList.contains('act-spec') && e.target.type === 'number')) {
        _notify();
      }
    });
  }

  // Lightweight accessor for FittingsUI's actuator dropdown.
  // Returns a shallow snapshot of {id, kind, name(label or kind+#)}.
  function getAll() {
    return _instances.map(function (a, i) {
      var meta = KIND_META[a.kind] || {};
      var label = (a.name && a.name.trim()) || ((meta.label || a.kind) + ' #' + (i + 1));
      return { id: a.id, kind: a.kind, label: label, icon: meta.icon || '⚙️' };
    });
  }

  window.ActuatorUI = {
    add: add, remove: remove,
    setDevices: setDevices,
    getAll: getAll,
    read: read, fill: fill, init: init
  };
})();

// ── FittingsUI ────────────────────────────────────────────────────────────────
// Manages user-placed fittings (windows, doors, fixtures, sensors, ad-hoc devices)
// rendered as boxes in the 3D scene. Position/size are absolute (m) from facility origin.
(function () {
  'use strict';

  var KIND_META = {
    window:           { label: _T('m_window','Window'),       icon: '[W]', color: '#2DB4FF', defaults: { w: 1.2,  h: 1.0,  d: 0.05 } },
    door:             { label: _T('m_door','Door'),     icon: '[D]', color: '#5E6B64', defaults: { w: 1.0,  h: 2.0,  d: 0.05 } },
    side_window:      { label: _T('m_side_window','Side Window'),       icon: '[S]', color: '#54BCC1', defaults: { w: 3.0,  h: 0.8,  d: 0.05 } },
    curtain:          { label: _T('m_curtain','Curtain'),       icon: '[C]', color: '#FEAE5F', defaults: { w: 3.0,  h: 2.5,  d: 0.02 } },
    shade_curtain:    { label: _T('m_shade','Shade'),       icon: '[X]', color: '#13261B', defaults: { w: 3.0,  h: 2.5,  d: 0.02 } },
    fan:              { label: _T('m_fan','Fan'),         icon: '[F]', color: '#54BCC1', defaults: { w: 0.8,  h: 0.8,  d: 0.3  } },
    heater:           { label: _T('m_heater','Heater'),       icon: '[H]', color: '#CF5C58', defaults: { w: 0.6,  h: 0.6,  d: 0.4  } },
    sensor:           { label: _T('m_sensor','Sensor'),       icon: '[T]', color: '#6277C7', defaults: { w: 0.15, h: 0.15, d: 0.1  } },
    fixture:          { label: _T('m_fixture','Fixture'),       icon: '[G]', color: '#64C762', defaults: { w: 1.0,  h: 1.0,  d: 1.0  } },
    // ── Irrigation devices ─────────────────────────────────────────────────────────────
    // Colors all follow the theme_config.equipment keys in geo/design (resolved by the renderer).
    irrigation_layer:      { label: _T('m_irr_layer','Irrigation Layer'),   icon: '[L]', color: null, defaults: { w: 0, h: 0, d: 0 } },
    irrigation_pipe:       { label: _T('m_irr_pipe','Pipe'),          icon: '[-]', color: null, defaults: { w: 0, h: 0, d: 0 } },
    irrigation_connection: { label: _T('m_irr_conn','Pipe Connection'),       icon: '[+]', color: null, defaults: { w: 0, h: 0, d: 0 } },
    irrigation_device:     { label: _T('m_irr_device','Irrigation Device'),      icon: '[*]', color: null, defaults: { w: 0, h: 0, d: 0 } },
    irrigation_valve:      { label: _T('m_irr_valve','Irrigation Valve'),     icon: '[V]', color: null, defaults: { w: 0.15, h: 0.15, d: 0.15 } },
  };

  var _fittings    = [];
  var _selectedId  = null;

  function _getSel() { return _fittings.find(function (x) { return x.id === _selectedId; }); }

  // Input channel choices — injected by page_facility() via Jinja2 (system-standard pattern).
  // Format: [{value: '{input_id},{meas_id}', item: 'display label'}, ...]
  // measurement_id → raw measurement slug for type auto-detection.
  var _inputChoices = (window.FAC_INPUT_CHOICES || []);
  var _measIdSlug   = (window.FAC_MEAS_ID_SLUG  || {});
  // Device-grouped channel data for 2-step sensor installer UI.
  var _inputDevices    = (window.FAC_INPUT_DEVICES    || []);
  var _functionDevices = (window.FAC_FUNCTION_DEVICES || []);

  function _findDevice(deviceId) {
    return _inputDevices.find(function (d) { return d.input_id === deviceId; }) ||
           _functionDevices.find(function (d) { return d.input_id === deviceId; }) || null;
  }

  var OutputCache = { list: [], loaded: false };

  // measurement slug → measurement_type key used by facility_sensors
  var _MEAS_TYPE_MAP = {
    temperature: 'temperature', temp: 'temperature', temp_c: 'temperature',
    humidity: 'humidity', humidity_pct: 'humidity', relative_humidity: 'humidity',
    co2: 'co2', co2_ppm: 'co2', carbon_dioxide: 'co2',
    vpd: 'vpd', vpd_kpa: 'vpd', vapor_pressure_deficit: 'vpd',
    light: 'light', solar: 'light', solar_wm2: 'light', irradiance: 'light',
    ppfd: 'light', lux: 'light', par: 'light', radiation: 'light',
    wind_speed: 'wind_speed', wind: 'wind_speed', wind_ms: 'wind_speed', windspeed: 'wind_speed',
    speed: 'wind_speed',
    wind_direction: 'wind_direction', wind_dir: 'wind_direction',
    wind_bearing: 'wind_direction', wind_deg: 'wind_direction', direction: 'wind_direction',
    rain: 'rain', rainfall: 'rain', rainrate: 'rain', rain_rate: 'rain',
    precipitation: 'rain', length: 'rain', depth: 'rain',
  };

  function _loadOutputs(force) {
    if (OutputCache.loaded && !force) return Promise.resolve(OutputCache.list);
    return fetch('/api/geo/outputs', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { ok: false }; })
      .then(function (j) {
        OutputCache.list   = (j && j.ok && Array.isArray(j.outputs)) ? j.outputs : [];
        OutputCache.loaded = true;
        return OutputCache.list;
      })
      .catch(function () { OutputCache.list = []; OutputCache.loaded = true; return []; });
  }

  function _uid() {
    return 'F' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
  }

  function _notify() {
    document.dispatchEvent(new CustomEvent('fittings-changed'));
  }

  // ── List rendering — right-side panel inside 3D viewport ───────────────────
  // ── 3D display filter ─────────────────────────────────────────────────────
  // This panel used to be a second component list: every fitting listed with
  // select and delete, duplicating the components table in the step drawer and
  // giving selection two places to drift out of sync. The one job it does that
  // the table cannot is deciding what the 3D view shows, so that is all it does
  // now — one row per category with a count and an on/off eye.
  function _renderList() {
    var container = document.getElementById('fit-list-items');
    var counter   = document.getElementById('fit-list-count');
    if (!container) return;

    var CAT_DEFS = [
      { key: 'envelope', label: _T('envelope','Envelope'),     kinds: null,   isMatch: function (f) { return f.source === 'envelope'; }, n: 0 },
      { key: 'opening',  label: _T('sec_openings','Openings'),   kinds: ['window','door','side_window'], n: 0 },
      { key: 'climate',  label: _T('env_vent_curtain','Vent/Curtain'), kinds: ['fan','heater','fogger','curtain','shade_curtain'], n: 0 },
      { key: 'sensor',   label: _T('m_sensor','Sensor'),     kinds: ['sensor'], n: 0 },
      { key: 'fixture',  label: _T('m_fixture','Fixture'),     kinds: ['fixture'], n: 0 },
      { key: 'irrig',    label: _T('m_irr_device','Irrigation Device'), kinds: null,   isMatch: function (f) { return f.kind === 'irrigation_layer'; }, n: 0 }
    ];

    function _catFor(f) {
      if (f.source === 'envelope') return CAT_DEFS[0];
      for (var i = 1; i < CAT_DEFS.length; i++) {
        var c = CAT_DEFS[i];
        if (c.isMatch && c.isMatch(f)) return c;
        if (c.kinds && c.kinds.indexOf(f.kind) !== -1) return c;
      }
      return null;
    }

    // Irrigation pieces are counted under their layer's category rather than
    // dropped, so the row's number matches what the eye actually hides.
    var IRR_CHILD = ['irrigation_pipe', 'irrigation_valve',
                     'irrigation_connection', 'irrigation_device'];
    _fittings.forEach(function (f) {
      if (IRR_CHILD.indexOf(f.kind) !== -1) { CAT_DEFS[5].n++; return; }
      var cat = _catFor(f);
      if (cat) cat.n++;
    });

    var shown = CAT_DEFS.filter(function (c) { return c.n > 0; });
    if (counter) {
      var hidden = shown.filter(function (c) { return !_getCategoryVisible(c.key); }).length;
      var hidTxt = (window._ ? window._('%(n)s hidden') : '%(n)s hidden').replace('%(n)s', hidden);
      counter.textContent = hidden ? '(' + hidTxt + ')' : '';
    }

    if (!shown.length) {
      container.innerHTML = '<div class="fit-list-empty">' + _T('no_fittings','No fittings added yet.') + '</div>';
      return;
    }

    container.innerHTML = shown.map(function (cat) {
      var visible = _getCategoryVisible(cat.key);
      return '<div class="fit-cat-row' + (visible ? '' : ' is-off') + '" data-cat="' + cat.key + '" ' +
        'title="' + (visible ? _T('cat_hide','Hide category') : _T('cat_show','Show category')) + '" ' +
        'onclick="FittingsUI.toggleCategoryVisibility(\'' + cat.key + '\');">' +
        '<span class="fit-cat-eye">' + (visible ? '\u25c9' : '\u25cb') + '</span>' +
        '<span class="fit-cat-name">' + cat.label + '</span>' +
        '<span class="fit-cat-count">' + cat.n + '</span>' +
      '</div>';
    }).join('');
  }

  // ── Inspector rendering — bottom strip showing selected fitting's props ────
  // Shared option rows carry display:flex !important, so an inline display:none
  // never hides them — aot-modal-modern.css ships .aot-modal-option-row.d-none
  // for exactly this. Route every conditional row through it.
  function _rowShow(el, on) {
    if (!el) return;
    el.classList.toggle('d-none', !on);
    el.style.removeProperty('display');
  }

  function _renderInspector() {
    var empty   = document.getElementById('fi-empty');
    var content = document.getElementById('fi-content');
    if (!empty || !content) return;
    var f = _fittings.find(function (x) { return x.id === _selectedId; });
    if (!f) {
      empty.style.display = '';
      content.style.display = 'none';
      return;
    }
    empty.style.display = 'none';
    content.style.display = '';

    var meta = KIND_META[f.kind] || KIND_META.fixture;
    var iconEl = document.getElementById('fi-icon');
    if (iconEl) iconEl.textContent = meta.icon;

    var isEnvItem = (f.source === 'envelope');

    // Actuator dropdown filler — shared by the irrigation-layer branch below and
    // the normal-fitting path, which return at different points.
    function _fillActuatorSelect(fit) {
      var actSel = document.getElementById('fi-actuator');
      if (!actSel) return;
      var outList = OutputCache.list || [];
      var aOpts;
      if (outList.length === 0) {
        aOpts = ['<option value="">'+_T('no_outputs','— No outputs (add at Setup → Output) —')+'</option>'];
      } else {
        aOpts = ['<option value="">'+_T('— None —','— None —')+'</option>'];
        outList.forEach(function (out) {
          var sel = (fit.actuator_id === out.unique_id) ? ' selected' : '';
          var label = (out.name || 'Output') + (out.output_type ? ' (' + out.output_type + ')' : '');
          aOpts.push('<option value="' + out.unique_id + '"' + sel + '>' + label + '</option>');
        });
      }
      actSel.innerHTML = aOpts.join('');
      actSel.value = fit.actuator_id || '';
    }

    // ── Irrigation-layer-only inspector ────────────────────────────────────────────
    var irrLayerGroup = document.getElementById('fi-group-irr-layer');
    var irrPipeGroup  = document.getElementById('fi-group-irr-pipe');
    var isIrrLayer = (f.kind === 'irrigation_layer');
    var isIrrPipe  = (f.kind === 'irrigation_pipe');
    _rowShow(irrLayerGroup, isIrrLayer);
    _rowShow(irrPipeGroup, isIrrPipe);
    if (isIrrLayer || isIrrPipe) {
      var nmEl = document.getElementById('fi-name');
      if (nmEl && nmEl.value !== (f.name || '')) nmEl.value = f.name || '';
      ['fi-x','fi-y','fi-z','fi-w','fi-h','fi-d','fi-rot'].forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) return;
        var row = el.closest && el.closest('.aot-modal-option-row');
        if (row) row.style.display = 'none';
      });
      var kindRow = (document.getElementById('fi-kind') || {}).closest && document.getElementById('fi-kind').closest('.aot-modal-option-row');
      _rowShow(kindRow, false);
      // Irrigation layers DO bind an actuator — the valve or pump that opens the
      // whole circuit. The backend has always read layer.actuator_id (it derives
      // per-actuator flow and nozzle wetting from it), but this inspector used to
      // hide the dropdown, so there was no way to set it and the binding stayed
      // empty forever. Pipes have no actuator semantics, so they stay hidden.
      var actG = document.getElementById('fi-group-actuator');
      var inpG = document.getElementById('fi-group-input');
      if (actG) actG.style.display = isIrrLayer ? '' : 'none';
      if (isIrrLayer) _fillActuatorSelect(f);
      if (inpG) inpG.style.display = 'none';
      var chsG = document.getElementById('fi-group-channels');
      if (chsG) chsG.style.display = 'none';
      var inheritRow = document.getElementById('fi-group-inherit');
      _rowShow(inheritRow, false);
      if (isIrrLayer) {
        var hEl = document.getElementById('fi-irr-height');
        if (hEl && hEl.value !== String(f.height_m != null ? f.height_m : 2.0)) {
          hEl.value = f.height_m != null ? f.height_m : 2.0;
        }
      }
      if (isIrrPipe) {
        var rEl = document.getElementById('fi-irr-radius');
        if (rEl && rEl.value !== String(f.radius != null ? f.radius : 0.025)) {
          rEl.value = f.radius != null ? f.radius : 0.025;
        }
        var nSegs = Array.isArray(f.segments) ? f.segments.length : 0;
        var segLabel = document.getElementById('fi-irr-segs');
        if (segLabel) segLabel.textContent = nSegs + _T('stage_word',' stage');
      }
      return;
    }

    // Hide irrigation-only group when a normal fitting is selected (avoids leftovers after switching from irrigation)
    _rowShow(irrLayerGroup, false);
    _rowShow(irrPipeGroup, false);

    // Populate inputs (programmatic — must not retrigger 'input' loop)
    var setVal = function (id, v) {
      var el = document.getElementById(id);
      if (!el) return;
      if (el.value !== String(v)) el.value = v;
    };
    setVal('fi-name', f.name || '');
    var kindEl = document.getElementById('fi-kind');
    if (kindEl) kindEl.value = f.kind;
    setVal('fi-x', f.position.x != null ? f.position.x : 0);
    setVal('fi-y', f.position.z != null ? f.position.z : 0); // user Y = depth = Three.js Z
    setVal('fi-z', f.position.y != null ? f.position.y : 0); // user Z = height      = Three.js Y
    setVal('fi-w', f.size.w != null ? f.size.w : 1);
    setVal('fi-h', f.size.h != null ? f.size.h : 1);
    // Restore all standard geometry rows (may have been hidden by irrigation selection)
    ['fi-x','fi-y','fi-z','fi-w','fi-h','fi-d','fi-rot'].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      var row = el.closest && el.closest('.aot-modal-option-row');
      if (row) row.style.display = '';
    });
    setVal('fi-d', f.size.d != null ? f.size.d : 0.1);
    setVal('fi-rot', f.rotation_deg || 0);

    // Inheritance checkbox — visible only when this fitting belongs to a
    // link_group with more than one member (i.e. it's a true replica). For
    // standalone fittings the row is hidden to avoid confusion.
    var inheritRow = document.getElementById('fi-group-inherit');
    var inheritEl  = document.getElementById('fi-inherit');
    if (inheritRow && inheritEl) {
      var groupSize = 0;
      if (f.link_group) {
        _fittings.forEach(function (g) {
          if (g.link_group === f.link_group) groupSize++;
        });
      }
      if (groupSize > 1) {
        _rowShow(inheritRow, true);
        inheritEl.checked = (f.inherit_size !== false);
        var actEl2 = document.getElementById('fi-inherit-act');
        if (actEl2) actEl2.checked = (f.inherit_actuator !== false);
        var cntEl = document.getElementById('fi-group-count');
        if (cntEl) {
          cntEl.textContent = (window._ ? window._('%(n)s created together').replace('%(n)s', groupSize)
                                        : groupSize + ' created together');
        }
      } else {
        _rowShow(inheritRow, false);
      }
    }

    // For envelope-derived items, hide kind-change and delete (those are controlled by envelope settings)
    var kindRow = (document.getElementById('fi-kind') || {}).closest && document.getElementById('fi-kind').closest('.aot-modal-option-row');
    _rowShow(kindRow, !isEnvItem);
    // Only an envelope item can be detached from automatic geometry.
    var autoRow = document.getElementById('fi-group-auto-geom');
    _rowShow(autoRow, isEnvItem && f._auto_geom === false);
    var delBtn = document.getElementById('fi-delete');
    if (delBtn && delBtn.closest('.aot-modal-option-row')) delBtn.closest('.aot-modal-option-row').style.display = isEnvItem ? 'none' : '';

    // Restore geometry rows (always visible)
    ['fi-x', 'fi-y', 'fi-z', 'fi-w', 'fi-h', 'fi-d', 'fi-rot'].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      var row = el.closest && el.closest('.aot-modal-option-row');
      if (row) row.style.display = '';
    });

    // Sensors bind to an Input (measurement source), other fittings bind to an
    // Actuator (output device). Toggle the two dropdown groups accordingly.
    var actGroup         = document.getElementById('fi-group-actuator');
    var inpGroup         = document.getElementById('fi-group-input');
    var channelsGroup    = document.getElementById('fi-group-channels');
    var sensorRoleGroup  = document.getElementById('fi-group-sensor-role');
    var measTypeGroup    = document.getElementById('fi-group-measurement-type');
    var fanRoleGroup     = document.getElementById('fi-group-fan-role');
    var isSensor = (f.kind === 'sensor');
    var isFan    = (f.kind === 'fan');
    _rowShow(actGroup, !isSensor);
    _rowShow(inpGroup, isSensor);
    _rowShow(channelsGroup, isSensor && !!f.input_id);
    _rowShow(sensorRoleGroup, isSensor);
    if (measTypeGroup)   measTypeGroup.style.display   = isSensor ? '' : 'none';
    // Fan role (circulation/exhaust/intake) — maps a generic 'fan' fitting to a
    // concrete env-control actuator kind when bound directly via actuator_id.
    _rowShow(fanRoleGroup, isFan);
    if (isFan) {
      var fanRoleSel = document.getElementById('fi-fan-role');
      if (fanRoleSel) fanRoleSel.value = f.fan_role || 'circulation_fan';
    }

    if (!isSensor) {
      _fillActuatorSelect(f);
    } else {
      // Step 1: Populate device dropdown (Input + Function groups).
      var devSel = document.getElementById('fi-device');
      if (devSel) {
        var dOpts = ['<option value="">'+_T('— None —','— None —')+'</option>'];
        if (_inputDevices.length === 0 && _functionDevices.length === 0) {
          dOpts = ['<option value="">'+_T('no_devices_opt','— No devices (add at Setup → Input/Function) —')+'</option>'];
        } else {
          if (_inputDevices.length > 0) {
            dOpts.push('<optgroup label="Input">');
            _inputDevices.forEach(function (dev) {
              var sel = (f.input_id === dev.input_id) ? ' selected' : '';
              dOpts.push('<option value="' + dev.input_id + '"' + sel + '>' + dev.name + ' (' + dev.channels.length + 'ch)</option>');
            });
            dOpts.push('</optgroup>');
          }
          if (_functionDevices.length > 0) {
            dOpts.push('<optgroup label="Function">');
            _functionDevices.forEach(function (dev) {
              var sel = (f.input_id === dev.input_id) ? ' selected' : '';
              dOpts.push('<option value="' + dev.input_id + '"' + sel + '>' + dev.name + ' (' + dev.channels.length + 'ch)</option>');
            });
            dOpts.push('</optgroup>');
          }
        }
        devSel.innerHTML = dOpts.join('');
        devSel.value = f.input_id || '';
      }

      // Step 2: Render channel checkboxes for the selected device.
      _renderChannelCheckboxes(f);

      // sensor_role: indoor (default) | outdoor
      var roleSel = document.getElementById('fi-sensor-role');
      if (roleSel) roleSel.value = f.sensor_role || 'indoor';

      // measurement_type: hidden field kept for legacy compatibility
      var measTypeSel = document.getElementById('fi-measurement-type');
      if (measTypeSel) measTypeSel.value = f.measurement_type || '';
    }
  }

  function _render() {
    _renderList();
    _renderInspector();
  }

  // Render channel checkboxes for the selected sensor fitting.
  // Called from _renderInspector() and from the device-change event handler.
  // Custom dropdown for channel multi-select.
  // Uses position:fixed so it escapes the inspector's overflow:hidden container.
  var _chDropdownOpen = false;

  function _closeChDropdown() {
    var dd = document.getElementById('fi-ch-dropdown');
    if (dd) dd.style.display = 'none';
    _chDropdownOpen = false;
  }

  function _updateChBtn(f) {
    var btn = document.getElementById('fi-ch-btn');
    if (!btn) return;
    var chs = Array.isArray(f && f.channel_measurements) ? f.channel_measurements : [];
    if (chs.length === 0) {
      btn.textContent = _T('Select Channel','Select Channel');
    } else if (chs.length === 1) {
      var dev = f.input_id && _findDevice(f.input_id);
      var ch  = dev && dev.channels.find(function (c) { return c.measurement_id === chs[0].measurement_id; });
      btn.textContent = ch ? (ch.measurement || ch.measurement_id) : chs[0].measurement_id;
    } else {
      btn.textContent = chs.length + _T('selected_word','selected');
    }
  }

  function _renderChannelCheckboxes(f) {
    var grp = document.getElementById('fi-group-channels');
    var btn = document.getElementById('fi-ch-btn');
    var dd  = document.getElementById('fi-ch-dropdown');
    if (!btn || !dd) return;

    var devId = f ? (f.input_id || '') : '';
    var dev   = devId && _findDevice(devId);

    if (!dev || !dev.channels || dev.channels.length === 0) {
      _closeChDropdown();
      if (grp) grp.style.display = devId ? '' : 'none';
      _updateChBtn(f);
      return;
    }
    if (grp) grp.style.display = '';
    _updateChBtn(f);

    // Build dropdown content
    var selectedIds = {};
    var chs = Array.isArray(f.channel_measurements) ? f.channel_measurements : [];
    if (chs.length === 0 && f.measurement_id) {
      chs = [{ measurement_id: f.measurement_id, measurement_type: f.measurement_type || null }];
    }
    chs.forEach(function (c) { selectedIds[c.measurement_id] = true; });

    var rows = dev.channels.map(function (ch) {
      var mtype   = _MEAS_TYPE_MAP[(ch.measurement || '').toLowerCase()] || '';
      var unitStr = ch.unit ? ' (' + ch.unit + ')' : '';
      var label   = (mtype ? '[' + mtype + '] ' : '') + (ch.measurement || ch.measurement_id) + unitStr;
      var chkd    = selectedIds[ch.measurement_id] ? ' checked' : '';
      var cid     = 'fi-ch-' + ch.measurement_id;
      return '<label class="ch-item" for="' + cid + '">' +
        '<input type="checkbox" id="' + cid + '" data-meas-id="' + ch.measurement_id + '" data-mtype="' + mtype + '"' + chkd + '>' +
        '<span>' + label + '</span>' +
        '</label>';
    });
    dd.innerHTML = rows.join('');

    // Checkbox change → update fitting data
    dd.querySelectorAll('input[type="checkbox"]').forEach(function (chk) {
      chk.addEventListener('change', function () {
        var fitting = _getSel(); if (!fitting) return;
        var newChs = [];
        dd.querySelectorAll('input[type="checkbox"]:checked').forEach(function (c) {
          newChs.push({ measurement_id: c.dataset.measId, measurement_type: c.dataset.mtype || null });
        });
        fitting.channel_measurements = newChs;
        fitting.measurement_id   = newChs.length > 0 ? newChs[0].measurement_id : null;
        fitting.measurement_type = newChs.length > 0 ? (newChs[0].measurement_type || null) : null;
        _updateChBtn(fitting);
        _renderList();
        document.dispatchEvent(new CustomEvent('fittings-data-changed'));
      });
    });

    // Button toggle — position dropdown with fixed coords above the button
    btn.onclick = function (e) {
      e.stopPropagation();
      if (_chDropdownOpen) { _closeChDropdown(); return; }
      var rect = btn.getBoundingClientRect();
      dd.style.display = 'block';
      dd.style.left    = rect.left + 'px';
      // Open upward from button
      dd.style.top     = (rect.top - dd.offsetHeight - 4) + 'px';
      // Clamp to viewport if it would go above screen
      var top = rect.top - dd.offsetHeight - 4;
      if (top < 8) top = rect.bottom + 4;
      dd.style.top = top + 'px';
      _chDropdownOpen = true;
    };
  }

  // Close channel dropdown when clicking outside
  document.addEventListener('click', function (e) {
    if (!_chDropdownOpen) return;
    var dd  = document.getElementById('fi-ch-dropdown');
    var btn = document.getElementById('fi-ch-btn');
    if (dd && !dd.contains(e.target) && e.target !== btn) _closeChDropdown();
  });

  // Read the current facility dimensions from the form (best-effort fallback).
  function _facilityDims() {
    var span    = parseFloat((document.getElementById('span-width')   || {}).value) || 7;
    var length  = parseFloat((document.getElementById('length-m')     || {}).value) || 30;
    var eaveH   = parseFloat((document.getElementById('eave-height')  || {}).value) || 2;
    var ridgeH  = parseFloat((document.getElementById('ridge-height') || {}).value) || 4;
    var bay     = parseInt(  (document.getElementById('bay-count')    || {}).value, 10) || 1;
    var spacing = parseFloat((document.getElementById('spacing-m')    || {}).value) || 0;
    var struct  = ((document.querySelector('input[name="structure"]:checked') || {}).value) || 'single';
    var totalWidth = (struct === 'connected')
      ? span * bay
      : span * bay + spacing * (bay - 1);
    return { span:span, length:length, eaveH:eaveH, ridgeH:ridgeH, bayCount:bay, totalWidth:totalWidth };
  }

  // Sensible default position per kind, so a freshly-added fitting is visible
  // in the centre of the facility (not buried at the corner).
  function _defaultPlacement(kind) {
    var d = _facilityDims();
    var cx = d.totalWidth / 2, cz = d.length / 2;
    switch (kind) {
      case 'curtain':  // ceiling-mounted, lies horizontal under the eaves
        return { position: { x: cx, y: d.eaveH + 0.05, z: cz }, surface_normal: [0, 1, 0] };
      case 'fan':
        return { position: { x: cx, y: d.eaveH * 0.7, z: cz }, surface_normal: null };
      case 'heater':
        return { position: { x: Math.max(cx - 1, 0.5), y: 0.4, z: cz - 1 }, surface_normal: null };
      case 'sensor':
        return { position: { x: cx, y: d.eaveH * 0.6, z: cz }, surface_normal: null };
      case 'fixture':
        return { position: { x: cx, y: d.eaveH * 0.7, z: cz }, surface_normal: null };
      default:
        return { position: { x: cx, y: d.eaveH / 2, z: cz }, surface_normal: null };
    }
  }

  function add(kind) {
    var meta  = KIND_META[kind] || KIND_META.fixture;
    var place = _defaultPlacement(kind);
    var id    = _uid();
    var f = {
      id: id, kind: kind, name: '',
      position: place.position,
      size:     { w: meta.defaults.w, h: meta.defaults.h, d: meta.defaults.d },
      rotation_deg: 0,
      surface_normal: place.surface_normal,
      // Sensors bind to an Input (measurement source); other kinds bind to an
      // Actuator. Both fields exist on every fitting but only one is meaningful
      // per kind — kept side-by-side for spec stability across kind changes.
      actuator_id: null,
      input_id: null,
      channel_measurements: [],
    };
    _fittings.push(f);
    _selectedId = id;
    _render();
    // Delta event so the 3D scene can add ONE mesh without a full rebuild.
    document.dispatchEvent(new CustomEvent('fitting-added',
      { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
    _notify();
    return id;
  }

  // Programmatic fitting creation — used by face-click placement from 3D scene.
  // pos: {x,y,z} in facility-local meters · rot: degrees around Y
  // size?: {w,h,d} (default = KIND_META.defaults) · faceLabel?: prepended to name
  // surface_normal?: [nx,ny,nz] — face normal in world space, used to orient
  //                   the box flush with curved/sloped surfaces (e.g. arch roof).
  // link_group?: string — fittings sharing a group sync size/rotation/kind/name.
  function addAt(kind, pos, rot, size, faceLabel, surface_normal, link_group, replica_info) {
    var meta = KIND_META[kind] || KIND_META.fixture;
    var sz = size || meta.defaults;
    var id = _uid();
    var posY = pos.y || 0;
    // If placing on the ground (no normal, very low y), lift to half-height so
    // the box sits on the floor instead of half-buried.
    if (!surface_normal && posY < 0.1) {
      posY = (sz.h || meta.defaults.h) / 2;
    }
    var f = {
      id: id,
      kind: kind,
      name: faceLabel ? (faceLabel + ' ' + meta.label) : '',
      position: { x: pos.x || 0, y: posY, z: pos.z || 0 },
      size:     { w: sz.w || meta.defaults.w, h: sz.h || meta.defaults.h, d: sz.d || meta.defaults.d },
      rotation_deg: rot || 0,
      surface_normal: (surface_normal && surface_normal.length === 3) ? surface_normal : null,
      link_group: link_group || null,
      actuator_id: null,   // user assigns via inspector — same actuator can drive many fittings
      input_id: null,      // sensor fittings: bound Input device (measurement source)
      channel_measurements: [],  // sensor fittings: [{measurement_id, measurement_type}]
      replica_info: replica_info || null   // metadata for position-propagation within link_group
    };
    _fittings.push(f);
    _selectedId = id;  // auto-select newly placed fitting
    _render();
    document.dispatchEvent(new CustomEvent('fitting-added',
      { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
    _notify();
    return id;
  }

  // Generate symmetric/multi-bay replicas for a face-click placement.
  // Each item carries a replica_info describing its transformation relative to
  // a shared "master local frame", so position edits can later be propagated
  // across the group with the correct mirror/bay offset.
  function _generateReplicas(face_raw, position, surface_normal, dims) {
    var out = [];
    var sn = surface_normal || [0, 0, 1];
    if (!dims) {
      return [{ position: position, surface_normal: sn,
                replica_info: { face: face_raw || 'unknown' } }];
    }
    var sp = (dims.span || 7) + (dims.effectiveSpacing || 0);
    var bayCount = Math.max(parseInt(dims.bayCount, 10) || 1, 1);
    var totalWidth = dims.totalWidth || ((dims.span || 7) * bayCount);
    var length = dims.length || 30;
    var span = dims.span || 7;

    if (face_raw === 'roof') {
      var bay_idx = Math.floor(position.x / sp);
      if (bay_idx < 0) bay_idx = 0;
      if (bay_idx >= bayCount) bay_idx = bayCount - 1;
      var local_x = position.x - bay_idx * sp;
      var mirror_local_x = span - local_x;
      // Only skip mirror when click is EXACTLY at ridge (floating-point equality).
      // A 5 cm threshold caused mirrors to be suppressed when users click on the
      // flat-looking arch top near the ridge, which is the typical skylight zone.
      var isRidge = Math.abs(mirror_local_x - local_x) < 0.001;
      for (var b = 0; b < bayCount; b++) {
        out.push({
          position: { x: b * sp + local_x, y: position.y, z: position.z },
          surface_normal: [sn[0], sn[1], sn[2]],
          replica_info: { face: 'roof', bay: b, x_mirror: false }
        });
        if (!isRidge) {
          out.push({
            position: { x: b * sp + mirror_local_x, y: position.y, z: position.z },
            surface_normal: [-sn[0], sn[1], sn[2]],
            replica_info: { face: 'roof', bay: b, x_mirror: true }
          });
        }
      }
    } else if (face_raw === 'x_pos' || face_raw === 'x_neg' || face_raw === 'east' || face_raw === 'west') {
      out.push({ position: position, surface_normal: sn,
                 replica_info: { face: face_raw, x_mirror_wall: false } });
      if (Math.abs(position.x - totalWidth / 2) > 0.05) {
        out.push({
          position: { x: totalWidth - position.x, y: position.y, z: position.z },
          surface_normal: [-sn[0], sn[1], sn[2]],
          replica_info: { face: face_raw, x_mirror_wall: true }
        });
      }
    } else if (face_raw === 'y_pos' || face_raw === 'y_neg' || face_raw === 'south' || face_raw === 'north') {
      out.push({ position: position, surface_normal: sn,
                 replica_info: { face: face_raw, z_mirror_wall: false } });
      if (Math.abs(position.z - length / 2) > 0.05) {
        out.push({
          position: { x: position.x, y: position.y, z: length - position.z },
          surface_normal: [sn[0], sn[1], -sn[2]],
          replica_info: { face: face_raw, z_mirror_wall: true }
        });
      }
    } else {
      out.push({ position: position, surface_normal: sn,
                 replica_info: { face: face_raw || 'unknown' } });
    }
    return out;
  }

  // Propagate shared properties (size, rotation, kind, name) to all members
  // of a linked group when one member is edited. Position is NOT propagated —
  // each replica keeps its own (mirrored / per-bay) position.
  //
  // Inheritance opt-out: members with inherit_size === false are skipped so
  // the user can detach individual replicas from the group via the inspector
  // checkbox. If the SOURCE has inherit_size=false the propagation is
  // suppressed entirely (the edit applies to that one fitting only).
  function _syncGroup(sourceId) {
    var src = _fittings.find(function (f) { return f.id === sourceId; });
    if (!src || !src.link_group) return false;
    if (src.inherit_size === false) return false;
    var groupId = src.link_group;
    var changed = false;
    _fittings.forEach(function (f) {
      if (f.id === sourceId || f.link_group !== groupId) return;
      if (f.inherit_size === false) return;   // detached replica
      f.kind = src.kind;
      f.name = src.name;
      f.size = { w: src.size.w, h: src.size.h, d: src.size.d };
      f.rotation_deg = src.rotation_deg;
      changed = true;
    });
    return changed;
  }

  // Wiring follows the same instance rule as geometry: components generated
  // together share one actuator unless a member is explicitly detached. Doing it
  // per fitting meant re-picking the same output 16 times for one roof vent row.
  function _syncActuatorGroup(sourceId) {
    var src = _fittings.find(function (f) { return f.id === sourceId; });
    if (!src || !src.link_group) return [];
    if (src.inherit_actuator === false) return [];
    var changed = [];
    _fittings.forEach(function (f) {
      if (f.id === sourceId || f.link_group !== src.link_group) return;
      if (f.inherit_actuator === false) return;   // detached member
      if (f.actuator_id === src.actuator_id) return;
      f.actuator_id = src.actuator_id;
      changed.push(f.id);
    });
    return changed;
  }

  function remove(id) {
    var target = _fittings.find(function (f) { return f.id === id; });
    var toRemove = [id];
    // cascade: remove all child pipes when removing an irrigation layer
    if (target && target.kind === 'irrigation_layer') {
      _fittings.forEach(function (f) {
        if (f.layer_id === id) toRemove.push(f.id);
      });
    }
    toRemove.forEach(function (rid) {
      _fittings = _fittings.filter(function (f) { return f.id !== rid; });
      if (_selectedId === rid) _selectedId = null;
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: rid } }));
    });
    _render();
    _notify();
  }

  function select(id) {
    _selectedId = (_selectedId === id) ? null : id;
    _render();
    document.dispatchEvent(new CustomEvent('fitting-selection-changed', { detail: { id: _selectedId } }));
  }

  function getSelectedId() { return _selectedId; }

  function read() {
    _fittings = _fittings.map(function (f) {
      var nm = document.querySelector('.fit-name[data-fit-id="' + f.id + '"]');
      if (nm) f.name = nm.value || '';
      ['x','y','z'].forEach(function (ax) {
        var el = document.querySelector('.fit-pos[data-fit-id="' + f.id + '"][data-axis="' + ax + '"]');
        if (el && el.value !== '') f.position[ax] = parseFloat(el.value);
      });
      ['w','h','d'].forEach(function (ax) {
        var el = document.querySelector('.fit-size[data-fit-id="' + f.id + '"][data-axis="' + ax + '"]');
        if (el && el.value !== '') f.size[ax] = parseFloat(el.value);
      });
      var rot = document.querySelector('.fit-rot[data-fit-id="' + f.id + '"]');
      if (rot && rot.value !== '') f.rotation_deg = parseFloat(rot.value) || 0;
      return f;
    });
    // Envelope-derived items are regenerated from the envelope settings on load,
    // so they are not persisted — EXCEPT the ones carrying a user decision that
    // regeneration cannot reproduce:
    //   • actuator_id / input_id — the wiring
    //   • _auto_geom === false   — size/position edited by hand (the envelope no
    //     longer drives it, so dropping the row would silently undo the edit)
    //   • inherit_* === false    — detached from its instance group
    return JSON.parse(JSON.stringify(_fittings.filter(function (f) {
      if (f.source !== 'envelope') return true;
      return !!(f.actuator_id || f.input_id) ||
             f._auto_geom === false ||
             f.inherit_size === false ||
             f.inherit_actuator === false;
    })));
  }

  // readAll includes envelope-derived items — used for 3D scene building only, not for saving
  function readAll() {
    return JSON.parse(JSON.stringify(_fittings));
  }

  function fill(fittings) {
    // Preserve existing envelope-derived items across fill() calls
    var envItems = _fittings.filter(function (f) { return f.source === 'envelope'; });
    _fittings = Array.isArray(fittings)
      ? JSON.parse(JSON.stringify(fittings))
      : [];
    _fittings.forEach(function (f) {
      if (!f.id) f.id = _uid();
      f.position = f.position || { x: 0, y: 0, z: 0 };
      f.size     = f.size     || { w: 1, h: 1, d: 0.1 };
      if (f.rotation_deg == null) f.rotation_deg = 0;
      // Migrate legacy single-channel sensor to channel_measurements array.
      // Also handles the case where channel_measurements=[] but measurement_id is set
      // (data saved by old code that initialized [] but set measurement_id separately).
      if (f.kind === 'sensor') {
        var hasChs = Array.isArray(f.channel_measurements) && f.channel_measurements.length > 0;
        if (!hasChs && f.measurement_id) {
          f.channel_measurements = [{ measurement_id: f.measurement_id, measurement_type: f.measurement_type || null }];
        } else if (!Array.isArray(f.channel_measurements)) {
          f.channel_measurements = [];
        }
      }
    });
    _fittings = envItems.concat(_fittings);
    _selectedId = null;
    _render();
  }

  // ── Sync envelope-derived virtual fittings ────────────────────────────────
  // Items now arrive PRE-COMPUTED from the caller (geo_facility.html's
  // _renderEnvelopeFittings) with full geometry:
  //   { id, kind, label, position:{x,y,z}, size:{w,h,d}, surface_normal?, rotation_deg? }
  // syncEnvelopeItems is now a thin add/update/remove function:
  //   • New IDs: insert and dispatch fitting-added (incremental scene add)
  //   • Existing IDs (with _auto_geom !== false): update geometry, dispatch
  //     aot-fitting-geometry / aot-fitting-transform for live update
  //   • Stale IDs: drop and dispatch fitting-removed
  function syncEnvelopeItems(items) {
    var incoming = Array.isArray(items) ? items : [];
    var incomingIds = incoming.map(function (x) { return x.id; });

    // Collect orphans (envelope fittings whose ids are no longer in incoming)
    // BEFORE removing them — their actuator_id/input_id bindings need to be
    // transferred to matching new incoming items so user-assigned bindings
    // survive envelope id regeneration (e.g. across save/load cycles).
    var orphans = _fittings.filter(function (f) {
      return f.source === 'envelope' && incomingIds.indexOf(f.id) < 0;
    });

    // Match an incoming item to an orphan by (kind, link_group, approximate
    // position). link_group is the strongest signal since replicated envelope
    // items share it; we then disambiguate by spatial proximity.
    function _findOrphan(item) {
      var pos = item.position || { x: 0, y: 0, z: 0 };
      var kind = item.kind || 'fixture';
      var lg = item.link_group || null;
      var best = null, bestD = Infinity;
      for (var i = 0; i < orphans.length; i++) {
        var o = orphans[i];
        if (!o || o._adopted) continue;
        if (o.kind !== kind) continue;
        if ((o.link_group || null) !== lg) continue;
        var op = o.position || { x: 0, y: 0, z: 0 };
        var dx = (op.x || 0) - pos.x;
        var dy = (op.y || 0) - pos.y;
        var dz = (op.z || 0) - pos.z;
        var d = dx*dx + dy*dy + dz*dz;
        if (d < bestD) { bestD = d; best = o; }
      }
      return best;
    }

    // Remove stale envelope items no longer active
    var removedIds = [];
    _fittings = _fittings.filter(function (f) {
      if (f.source !== 'envelope') return true;
      if (incomingIds.indexOf(f.id) >= 0) return true;
      removedIds.push(f.id);
      return false;
    });
    removedIds.forEach(function (id) {
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: id } }));
    });

    // Add new items / update auto-geom items
    incoming.forEach(function (item) {
      if (!item || !item.id) return;
      var existing = _fittings.find(function (f) { return f.id === item.id; });
      var pos  = item.position || { x: 0, y: 0, z: 0 };
      var size = item.size     || { w: 1, h: 1, d: 0.1 };
      var sn   = (Array.isArray(item.surface_normal) && item.surface_normal.length === 3)
        ? item.surface_normal.slice() : null;
      var rot  = parseFloat(item.rotation_deg) || 0;

      if (!existing) {
        // Try to inherit bindings from an orphaned envelope fitting whose id
        // was regenerated (kind + link_group + nearest position match).
        var adopt = _findOrphan(item);
        if (adopt) adopt._adopted = true;
        var newFit = {
          id:             item.id,
          source:         'envelope',
          kind:           item.kind || 'fixture',
          name:           item.label || (adopt ? adopt.name : ''),
          position:       { x: pos.x, y: pos.y, z: pos.z },
          size:           { w: size.w, h: size.h, d: size.d },
          rotation_deg:   rot,
          surface_normal: sn,
          _auto_geom:     adopt ? (adopt._auto_geom !== false) : true,
          actuator_id:    adopt ? (adopt.actuator_id || null) : null,
          input_id:       adopt ? (adopt.input_id || null) : null,
          // Replicated envelope items share a link_group so editing one
          // propagates size/kind to its siblings. Inheritance ON by default;
          // the user can opt-out per-fitting via the inspector checkbox.
          link_group:     item.link_group || null,
          inherit_size:   adopt ? (adopt.inherit_size !== false) : true
        };
        _fittings.unshift(newFit);
        document.dispatchEvent(new CustomEvent('fitting-added',
          { detail: { fitting: JSON.parse(JSON.stringify(newFit)) } }));
        return;
      }

      // Existing item — refresh label/kind always; refresh geometry only when auto.
      existing.name = item.label || existing.name;
      if (item.kind && item.kind !== existing.kind) {
        existing.kind = item.kind;
      }
      // Carry through link_group changes (e.g. envelope settings changed
      // grouping rules). inherit_size is a user preference — preserved as-is.
      if (item.link_group !== undefined && item.link_group !== existing.link_group) {
        existing.link_group = item.link_group;
      }
      if (existing._auto_geom === false) return;

      var sizeChanged =
        Math.abs((existing.size.w || 0) - size.w) > 0.005 ||
        Math.abs((existing.size.h || 0) - size.h) > 0.005 ||
        Math.abs((existing.size.d || 0) - size.d) > 0.005;
      var posChanged =
        Math.abs((existing.position.x || 0) - pos.x) > 0.005 ||
        Math.abs((existing.position.y || 0) - pos.y) > 0.005 ||
        Math.abs((existing.position.z || 0) - pos.z) > 0.005;
      var snBefore = JSON.stringify(existing.surface_normal || null);
      var snAfter  = JSON.stringify(sn);
      var normalChanged = snBefore !== snAfter;

      if (sizeChanged) {
        existing.size = { w: size.w, h: size.h, d: size.d };
        document.dispatchEvent(new CustomEvent('aot-fitting-geometry',
          { detail: { id: existing.id, size: existing.size } }));
      }
      if (posChanged) {
        existing.position = { x: pos.x, y: pos.y, z: pos.z };
        document.dispatchEvent(new CustomEvent('aot-fitting-transform',
          { detail: { id: existing.id, position: existing.position, rotation_deg: existing.rotation_deg } }));
      }
      if (normalChanged) {
        existing.surface_normal = sn;
        // surface_normal change requires the mesh to be re-created so the basis
        // is recomputed. Remove + add re-uses the incremental scene path.
        document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: existing.id } }));
        document.dispatchEvent(new CustomEvent('fitting-added',
          { detail: { fitting: JSON.parse(JSON.stringify(existing)) } }));
      }
    });

    _render();
  }

  // ── Inspector input wiring — bidirectional binding with selected fitting ───
  function _bindInspectorInputs() {
    // Detaching happens mid-edit, so the "back to automatic" row has to appear
    // then — _renderInspector only runs on selection.
    function _detachEnvelope(f) {
      if (!f || f.source !== 'envelope') return;
      f._auto_geom = false;
      _rowShow(document.getElementById('fi-group-auto-geom'), true);
    }
    function _onTransform() {
      var f = _getSel(); if (!f) return;
      // User explicitly editing — detach from auto-dim tracking
      _detachEnvelope(f);
      f.position.x = parseFloat((document.getElementById('fi-x') || {}).value) || 0;
      f.position.z = parseFloat((document.getElementById('fi-y') || {}).value) || 0; // user Y -> Three.js Z
      f.position.y = parseFloat((document.getElementById('fi-z') || {}).value) || 0; // user Z -> Three.js Y
      f.rotation_deg = parseFloat((document.getElementById('fi-rot') || {}).value) || 0;

      var dirty = [{ id: f.id, position: f.position, rotation_deg: f.rotation_deg }];

      // Propagate to other group members using replica_info (per-bay + mirror).
      // Rotation always copies; position is reflected/translated based on each
      // replica's transformation relative to a shared local frame.
      if (f.link_group) {
        var others = _fittings.filter(function (g) {
          return g.link_group === f.link_group && g.id !== f.id;
        });
        if (others.length > 0) {
          var dims = _facilityDims();
          var sp = dims.span + 0;  // connected mode default; spacing handled below if set
          var span = dims.span;
          var totalW = dims.totalWidth;
          var length = dims.length;
          var fInfo = f.replica_info || {};

          // Recover the master-local position implied by THIS fitting's new pos.
          // (Whichever fitting the user edits acts as the new reference.)
          var masterLocalX = f.position.x;
          if (fInfo.face === 'roof') {
            var fBay = fInfo.bay != null ? fInfo.bay : Math.floor(f.position.x / sp);
            var fLocalX = f.position.x - fBay * sp;
            masterLocalX = fInfo.x_mirror ? (span - fLocalX) : fLocalX;
          } else if (fInfo.x_mirror_wall) {
            masterLocalX = totalW - f.position.x;
          }
          var masterZ = fInfo.z_mirror_wall ? (length - f.position.z) : f.position.z;

          others.forEach(function (g) {
            var gInfo = g.replica_info || {};
            // Always propagate rotation
            g.rotation_deg = f.rotation_deg;
            // Position propagation requires compatible face
            if (gInfo.face === 'roof' && fInfo.face === 'roof') {
              var gLocalX = gInfo.x_mirror ? (span - masterLocalX) : masterLocalX;
              g.position = {
                x: (gInfo.bay || 0) * sp + gLocalX,
                y: f.position.y,
                z: f.position.z
              };
            } else if (['x_pos','x_neg','east','west'].indexOf(gInfo.face) >= 0 &&
                       ['x_pos','x_neg','east','west'].indexOf(fInfo.face) >= 0) {
              g.position = {
                x: gInfo.x_mirror_wall ? (totalW - masterLocalX) : masterLocalX,
                y: f.position.y,
                z: f.position.z
              };
            } else if (['y_pos','y_neg','south','north'].indexOf(gInfo.face) >= 0 &&
                       ['y_pos','y_neg','south','north'].indexOf(fInfo.face) >= 0) {
              g.position = {
                x: f.position.x,
                y: f.position.y,
                z: gInfo.z_mirror_wall ? (length - masterZ) : masterZ
              };
            } else {
              // Unknown / legacy: keep position, only rotation propagates
            }
            dirty.push({ id: g.id, position: g.position, rotation_deg: g.rotation_deg });
          });
        }
      }

      // Emit one in-place transform event per dirty fitting (no scene rebuild)
      dirty.forEach(function (d) {
        document.dispatchEvent(new CustomEvent('aot-fitting-transform', { detail: d }));
      });
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    }
    function _onSize() {
      var f = _getSel(); if (!f) return;
      // User explicitly editing — detach from auto-dim tracking
      _detachEnvelope(f);
      f.size.w = Math.max(parseFloat((document.getElementById('fi-w') || {}).value) || 0.1, 0.02);
      f.size.h = Math.max(parseFloat((document.getElementById('fi-h') || {}).value) || 0.1, 0.02);
      f.size.d = Math.max(parseFloat((document.getElementById('fi-d') || {}).value) || 0.1, 0.02);
      // Sync size to linked group members + emit transform event for each.
      // _syncGroup respects inherit_size — members opted-out (or a detached
      // source) won't be updated, so syncIds is built from those that
      // actually received the new size.
      var syncIds = [f.id];
      if (f.link_group && f.inherit_size !== false) {
        _syncGroup(f.id);
        _fittings.forEach(function (g) {
          if (g.link_group !== f.link_group || g.id === f.id) return;
          if (g.inherit_size === false) return;
          syncIds.push(g.id);
        });
      }
      syncIds.forEach(function (id) {
        document.dispatchEvent(new CustomEvent('aot-fitting-geometry', {
          detail: { id: id, size: f.size }
        }));
      });
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    }
    function _onInherit() {
      var f = _getSel(); if (!f) return;
      var cb = document.getElementById('fi-inherit');
      if (!cb) return;
      f.inherit_size = !!cb.checked;
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    }
    function _onMeta() {
      var f = _getSel(); if (!f) return;
      f.name = (document.getElementById('fi-name') || {}).value || '';
      var newKind = (document.getElementById('fi-kind') || {}).value;
      var kindChanged = (newKind && newKind !== f.kind);
      f.kind = newKind || f.kind;
      if (f.link_group) _syncGroup(f.id);
      _renderList();           // list labels may have changed
      // Kind toggles sensor/non-sensor → actuator vs input dropdown swap.
      if (kindChanged) _renderInspector();
      if (kindChanged) {
        // Color/material depends on kind — recreate THIS mesh in-place (no full rebuild)
        document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: f.id } }));
        document.dispatchEvent(new CustomEvent('fitting-added',
          { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
        // If linked group, also recreate every member's mesh
        if (f.link_group) {
          _fittings.forEach(function (g) {
            if (g.link_group === f.link_group && g.id !== f.id) {
              document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: g.id } }));
              document.dispatchEvent(new CustomEvent('fitting-added',
                { detail: { fitting: JSON.parse(JSON.stringify(g)) } }));
            }
          });
        }
        document.dispatchEvent(new CustomEvent('fittings-data-changed'));
      } else {
        document.dispatchEvent(new CustomEvent('fittings-data-changed'));
      }
    }

    ['fi-x','fi-y','fi-z','fi-rot'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('input', _onTransform);
    });
    ['fi-w','fi-h','fi-d'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('input', _onSize);
    });
    var inheritEl = document.getElementById('fi-inherit');
    if (inheritEl) inheritEl.addEventListener('change', _onInherit);
    var inheritActEl = document.getElementById('fi-inherit-act');
    if (inheritActEl) inheritActEl.addEventListener('change', function () {
      var f = _getSel(); if (!f) return;
      f.inherit_actuator = !!inheritActEl.checked;
      // Re-linking adopts the group's current actuator immediately, otherwise
      // the checkbox would look linked while the wiring still differed.
      if (f.inherit_actuator && f.link_group) {
        var peer = _fittings.find(function (g) {
          return g.link_group === f.link_group && g.id !== f.id && g.inherit_actuator !== false;
        });
        if (peer) f.actuator_id = peer.actuator_id;
        var sel = document.getElementById('fi-actuator');
        if (sel) sel.value = f.actuator_id || '';
      }
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    });
    var nm = document.getElementById('fi-name');
    if (nm) nm.addEventListener('input', _onMeta);
    var kd = document.getElementById('fi-kind');
    if (kd) kd.addEventListener('change', _onMeta);
    var del = document.getElementById('fi-delete');
    if (del) del.addEventListener('click', function () {
      if (_selectedId) remove(_selectedId);
    });

    // ── Irrigation layer height binding ────────────────────────────────────────────────
    var hEl = document.getElementById('fi-irr-height');
    if (hEl) hEl.addEventListener('input', function () {
      var f = _getSel(); if (!f || f.kind !== 'irrigation_layer') return;
      var v = parseFloat(hEl.value);
      if (isNaN(v) || v < 0) return;
      setLayerHeight(f.id, v);
    });
    var rEl = document.getElementById('fi-irr-radius');
    if (rEl) rEl.addEventListener('input', function () {
      var f = _getSel(); if (!f || f.kind !== 'irrigation_pipe') return;
      var v = parseFloat(rEl.value);
      if (isNaN(v) || v <= 0) return;
      f.radius = v;
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: f.id } }));
      document.dispatchEvent(new CustomEvent('fitting-added',   { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    });

    // Actuator dropdown — propagated across the link_group by default; a member
    // opts out with the "제어장치 연동" checkbox.
    var actSel = document.getElementById('fi-actuator');
    if (actSel) actSel.addEventListener('change', function () {
      var f = _getSel(); if (!f) return;
      f.actuator_id = actSel.value || null;
      _syncActuatorGroup(f.id);
      _renderList();
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    });

    // Device dropdown — selecting a device resets channel_measurements and shows checkboxes.
    var devSel = document.getElementById('fi-device');
    if (devSel) devSel.addEventListener('change', function () {
      var f = _getSel(); if (!f) return;
      f.input_id           = devSel.value || null;
      f.channel_measurements = [];
      f.measurement_id     = null;
      f.measurement_type   = null;
      _renderChannelCheckboxes(f);
      _renderList();
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    });

    // sensor_role dropdown — indoor / outdoor
    var roleSel = document.getElementById('fi-sensor-role');
    if (roleSel) roleSel.addEventListener('change', function () {
      var f = _getSel(); if (!f) return;
      f.sensor_role = roleSel.value || 'indoor';
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    });

    // fan_role dropdown — circulation / exhaust / intake (env-control mapping)
    var fanRoleSel = document.getElementById('fi-fan-role');
    if (fanRoleSel) fanRoleSel.addEventListener('change', function () {
      var f = _getSel(); if (!f) return;
      f.fan_role = fanRoleSel.value || 'circulation_fan';
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    });

    // measurement_type dropdown
    var measTypeSel = document.getElementById('fi-measurement-type');
    if (measTypeSel) measTypeSel.addEventListener('change', function () {
      var f = _getSel(); if (!f) return;
      f.measurement_type = measTypeSel.value || null;
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
    });
  }

  function init() {
    _render();
    _bindInspectorInputs();

    // Input choices are injected server-side (FAC_INPUT_CHOICES) — no fetch needed.
    // Fetch Output device list once for actuator inspector dropdowns.
    _loadOutputs().then(function () {
      if (_selectedId) _renderInspector();
      _renderList();
    });

    // External 3D click → select the matching item in the list
    document.addEventListener('aot-fitting-clicked', function (e) {
      var id = e.detail && e.detail.id;
      if (id) select(id);
    });

    // The fitting actuator dropdown now binds directly to the global Output
    // device list (not the facility-local ActuatorUI instances), so we no
    // longer need to refresh or prune anything when ActuatorUI changes.

    // External face-click placement from 3D scene → spawn fitting(s).
    // Wall/roof clicks: generate symmetric + per-bay replicas, all sharing one
    // link_group. Device drag-place: single fitting, no replication.
    document.addEventListener('aot-facility-add-fitting', function (e) {
      var d = e.detail; if (!d || !d.kind || !d.position) return;

      var replicas;
      if (d.is_device || !d.face_raw) {
        // Devices: single fitting at click point, no replication.
        replicas = [{ position: d.position, surface_normal: d.surface_normal }];
      } else {
        replicas = _generateReplicas(d.face_raw, d.position, d.surface_normal, d.facility_dims);
      }

      var groupId = (replicas.length > 1) ? _uid() : null;
      replicas.forEach(function (r) {
        addAt(d.kind, r.position, d.rotation_deg, d.size, d.face,
              r.surface_normal, groupId, r.replica_info);
      });
    });
  }

  // ── Catalog import: pull equipment features from geo/design ───────────────
  function _featureCentroid(geom) {
    if (!geom || !geom.coordinates) return null;
    var coords = [];
    function _walk(c) {
      if (!c) return;
      if (typeof c[0] === 'number') { coords.push(c); return; }
      c.forEach(_walk);
    }
    _walk(geom.coordinates);
    if (coords.length === 0) return null;
    var sx = 0, sy = 0;
    coords.forEach(function (p) { sx += p[0]; sy += p[1]; });
    return [sx / coords.length, sy / coords.length];
  }

  function _featureSizeM(geom, latC) {
    // Approximate bounding-box size in meters
    if (!geom || !geom.coordinates) return null;
    var coords = [];
    function _walk(c) {
      if (!c) return;
      if (typeof c[0] === 'number') { coords.push(c); return; }
      c.forEach(_walk);
    }
    _walk(geom.coordinates);
    if (coords.length < 2) return null;
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    coords.forEach(function (p) {
      if (p[0] < minX) minX = p[0]; if (p[0] > maxX) maxX = p[0];
      if (p[1] < minY) minY = p[1]; if (p[1] > maxY) maxY = p[1];
    });
    var M_PER_DEG_LAT = 111320.0;
    var M_PER_DEG_LNG = M_PER_DEG_LAT * Math.cos((latC || 0) * Math.PI / 180);
    var w = (maxX - minX) * M_PER_DEG_LNG;
    var d = (maxY - minY) * M_PER_DEG_LAT;
    return { w: Math.max(w, 0.1), d: Math.max(d, 0.1) };
  }

  // Convert feature geometry → fitting position (facility-local meters)
  function _featureToFittingPos(feature, facCenter, facOrientDeg) {
    if (!feature || !feature.geometry || !facCenter) return { x: 0, y: 0, z: 0 };
    var fc = _featureCentroid(feature.geometry);
    if (!fc) return { x: 0, y: 0, z: 0 };
    var latC = facCenter[1];
    var M_PER_DEG_LAT = 111320.0;
    var M_PER_DEG_LNG = M_PER_DEG_LAT * Math.cos(latC * Math.PI / 180);
    var dx_m = (fc[0] - facCenter[0]) * M_PER_DEG_LNG;
    var dy_m = (fc[1] - facCenter[1]) * M_PER_DEG_LAT;
    // Inverse-rotate around facility origin to convert world meters → local
    var theta = -((facOrientDeg || 0) * Math.PI / 180);
    var cosT = Math.cos(theta), sinT = Math.sin(theta);
    var lx = dx_m * cosT - dy_m * sinT;
    var lz = dx_m * sinT + dy_m * cosT;
    return { x: lx, z: lz };
  }

  function _kindFromFeature(feature) {
    var p = (feature && feature.properties) || {};
    var k = String(p.kind || p.aot_kind || p.equipment_type || p.feature_type || '').toLowerCase();
    if (k.includes('side_window') || k.includes('측창')) return 'side_window';
    if (k.includes('window') || k.includes('vent') || k.includes(_T('env_win_short','Win'))) return 'window';
    if (k.includes('door') || k.includes(_T('env_door_short','Door'))) return 'door';
    if (k.includes('curtain') || k.includes('커튼')) return 'curtain';
    if (k.includes('fan') || k.includes('팬'))    return 'fan';
    if (k.includes('heater') || k.includes('히터')) return 'heater';
    if (k.includes('sensor') || k.includes('센서')) return 'sensor';
    return 'fixture';
  }

  async function importFromCatalog(geoId, facCenter, facOrientDeg) {
    if (!geoId) { alert(_T('select_map_first','Please select a map first.')); return; }
    try {
      var res = await fetch('/api/geo/overlays?map_uuid=' + encodeURIComponent(geoId) +
                            '&type=equipment', { credentials: 'same-origin' });
      var json = await res.json();
      var features = (json && json.features) || [];
      if (features.length === 0) { alert(_T('catalog_empty','No equipment in catalog.')); return; }
      _openCatalogPicker(features, facCenter, facOrientDeg);
    } catch (e) {
      alert(_T('catalog_fail','Catalog load failed: ') + e.message);
    }
  }

  function _openCatalogPicker(features, facCenter, facOrientDeg) {
    // Remove existing
    var prev = document.getElementById('fittings-catalog-modal');
    if (prev) prev.remove();

    var overlay = document.createElement('div');
    overlay.id = 'fittings-catalog-modal';
    // Shared modal shell (.aot-option-modal), same as every other dialog.
    overlay.className = 'modal fade aot-option-modal';
    overlay.tabIndex = -1;
    overlay.setAttribute('role', 'dialog');
    overlay.innerHTML =
      '<div class="modal-dialog modal-dialog-centered" role="document">' +
        '<div class="modal-content">' +
          '<div class="modal-header">' +
            '<h5 class="modal-title">' + _T('catalog_title','Equipment Catalog') + '</h5>' +
            '<button type="button" class="close" data-dismiss="modal" aria-label="Close">' +
              '<span aria-hidden="true">&times;</span></button>' +
          '</div>' +
          '<div class="modal-body">' +
            '<div class="aot-modal-body-text mb-2">' + _T('catalog_hint','Select equipment from the current map to add as a fitting.') + '</div>' +
            '<div id="cat-list" class="fac-catalog-list"></div>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    var listEl = overlay.querySelector('#cat-list');
    features.forEach(function (feat) {
      var p = feat.properties || {};
      var name = p.name || p.label || ('Feature #' + (p.db_id || ''));
      var inferredKind = _kindFromFeature(feat);
      var size = _featureSizeM(feat.geometry, facCenter ? facCenter[1] : 37.5);
      var sizeStr = size ? (size.w.toFixed(1) + '×' + size.d.toFixed(1) + 'm') : '?';
      var h = parseFloat(p.height_m) || null;
      var el = parseFloat(p.elevation_m) || 0;

      var item = document.createElement('div');
      item.className = 'fac-catalog-item';
      item.innerHTML =
        '<span class="fac-catalog-item-text"><b>' + name + '</b>' +
        '<br><small>' + inferredKind + ' · ' + sizeStr +
        (h ? ' · '+_T('height','height')+' ' + h + 'm' : '') + '</small></span>' +
        '<button class="btn aot-pill-btn aot-pill-btn-primary">'+_T('import_btn','Import')+'</button>';
      item.addEventListener('click', function () {
        var pos = _featureToFittingPos(feat, facCenter, facOrientDeg);
        var sz = size || { w: 1, h: 1, d: 1 };
        var heightM = h || (KIND_META[inferredKind] || KIND_META.fixture).defaults.h;
        _fittings.push({
          id: _uid(),
          kind: inferredKind,
          name: name,
          position: { x: pos.x || 0, y: el + heightM / 2, z: pos.z || 0 },
          size:     { w: sz.w, h: heightM, d: sz.d },
          rotation_deg: 0,
          source_feature_uuid: p.node_id || p.unique_id || null
        });
        _render();
        _notify();
        _closeCatalog(overlay);
      });
      listEl.appendChild(item);
    });

    // Drop the node once hidden so a re-open always renders fresh contents.
    if (window.jQuery && jQuery.fn && jQuery.fn.modal) {
      jQuery(overlay).on('hidden.bs.modal', function () { overlay.remove(); }).modal('show');
    } else {
      overlay.classList.add('show');
      overlay.style.display = 'block';
      overlay.addEventListener('click', function (e) { if (e.target === overlay) overlay.remove(); });
    }
  }

  function _closeCatalog(overlay) {
    if (window.jQuery && jQuery.fn && jQuery.fn.modal) jQuery(overlay).modal('hide');
    else overlay.remove();
  }

  // Aggregate count + size summary by kind ──────────────────
  function aggregate() {
    var byKind = {};
    var totalArea = 0;
    _fittings.forEach(function (f) {
      var k = f.kind || 'fixture';
      if (!byKind[k]) byKind[k] = { count: 0, area_m2: 0, volume_m3: 0 };
      byKind[k].count += 1;
      var area = (f.size.w || 0) * (f.size.d || 0);
      byKind[k].area_m2 += area;
      byKind[k].volume_m3 += area * (f.size.h || 0);
    });
    return { total: _fittings.length, by_kind: byKind, total_area_m2: Object.values(byKind).reduce(function (s, v) { return s + v.area_m2; }, 0) };
  }

  // ── Irrigation layer management ─────────────────────────────────────────────────────────

  function addIrrigationLayer() {
    var id = _uid();
    var d  = _facilityDims();
    var layerCount = _fittings.filter(function (f) { return f.kind === 'irrigation_layer'; }).length;
    var f = {
      id: id,
      kind: 'irrigation_layer',
      name: _T('m_irr_layer','Irrigation Layer')+' ' + (layerCount + 1),
      height_m: 2.0,
      // Color is taken by the renderer from AOT_GEO_CONFIG.theme_config.equipment.
      color: null,
      visible: true,
      position: { x: d.totalWidth / 2, y: 2.0, z: d.length / 2 },
      size: { w: 0.1, h: 0.1, d: 0.1 },
      rotation_deg: 0,
      surface_normal: null,
      actuator_id: null,
      input_id: null
    };
    _fittings.push(f);
    _selectedId = id;
    _render();
    document.dispatchEvent(new CustomEvent('fitting-added', { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
    _notify();
    return id;
  }

  // segments: [{from:[x,y,z], to:[x,y,z], is_vertical_seg}]
  // opts: { sub_type: 'main'|'branch'|'riser', is_vertical, draw_id, radius, name }
  // Compat: if the third argument is a boolean, interpret it as isVertical(=riser) (legacy callers).
  function addIrrigationPipe(layerId, segments, opts) {
    var layer = _fittings.find(function (f) { return f.id === layerId; });
    if (!layer || layer.kind !== 'irrigation_layer') return null;
    if (opts === true || opts === false) opts = { is_vertical: !!opts };
    opts = opts || {};
    var isVertical = !!opts.is_vertical;
    var subType = opts.sub_type || (isVertical ? 'riser' : 'branch');
    var id = _uid();
    var pipeName = opts.name
      || (isVertical ? _T('irr_vpipe','Vertical pipe')
          : (subType === 'main' ? _T('irr_main','Main pipe') : _T('irr_branch','Branch pipe')));
    var f = {
      id: id,
      kind: 'irrigation_pipe',
      layer_id: layerId,
      name: pipeName,
      sub_type: subType,             // 'main' | 'branch' | 'riser'
      segments: Array.isArray(segments) ? segments : [],
      radius: opts.radius != null ? opts.radius : (subType === 'main' ? 0.04 : 0.025),
      is_vertical: isVertical,
      draw_id: opts.draw_id || null, // tracks a single drawing session (to distinguish elbow vs tee)
      connected_main_id: null,       // filled by rebuildConnections
      position: { x: 0, y: layer.height_m || 2.0, z: 0 },
      size: { w: 0.05, h: 0.05, d: 0.05 },
      rotation_deg: 0,
      surface_normal: null,
      actuator_id: null,
      input_id: null
    };
    _fittings.push(f);
    _selectedId = id;
    _render();
    document.dispatchEvent(new CustomEvent('fitting-added', { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
    _notify();
    return id;
  }

  // ── Multi-click drawing API ───────────────────────────────────────────────────
  // startPipe(layerId, subType, firstPoint) -> pipeId (segments=[], keeps only the first point)
  // extendPipe(pipeId, nextPoint) -> add a point to segments (continues from the previous endpoint or the first point)
  // finishPipe(pipeId) -> removes if segs is empty. Otherwise triggers a connection rebuild.
  function startPipe(layerId, subType, firstPoint, drawId) {
    var layer = _fittings.find(function (f) { return f.id === layerId; });
    if (!layer || layer.kind !== 'irrigation_layer') return null;
    var id = addIrrigationPipe(layerId, [], {
      sub_type: subType,
      draw_id: drawId || _uid()
    });
    var pipe = _fittings.find(function (f) { return f.id === id; });
    if (pipe) pipe._pending_start = [firstPoint[0], firstPoint[1], firstPoint[2]];
    return id;
  }

  function extendPipe(pipeId, nextPoint) {
    var pipe = _fittings.find(function (f) { return f.id === pipeId; });
    if (!pipe || pipe.kind !== 'irrigation_pipe') return;
    var segs = Array.isArray(pipe.segments) ? pipe.segments : [];
    var start;
    if (segs.length === 0) {
      start = pipe._pending_start || [0, pipe.position.y || 2.0, 0];
    } else {
      start = segs[segs.length - 1].to;
    }
    var p1 = [nextPoint[0], nextPoint[1], nextPoint[2]];
    var dx = p1[0] - start[0], dz = p1[2] - start[2];
    if (Math.sqrt(dx*dx + dz*dz) < 0.05) return; // ignore micro-clicks
    segs.push({ from: start.slice(), to: p1, is_vertical_seg: false });
    pipe.segments = segs;
    delete pipe._pending_start;
    document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: pipe.id } }));
    document.dispatchEvent(new CustomEvent('fitting-added',   { detail: { fitting: JSON.parse(JSON.stringify(pipe)) } }));
    _render();
    _notify();
  }

  function finishPipe(pipeId) {
    var pipe = _fittings.find(function (f) { return f.id === pipeId; });
    if (!pipe) return;
    if (!pipe.segments || pipe.segments.length === 0) {
      remove(pipeId);
      return;
    }
    delete pipe._pending_start;
    rebuildIrrigationConnections(pipe.layer_id);
  }

  // ── Intersection detection + trim + connection (tee) insertion ────────────────────────────────────
  // Check all main<->branch pipe pairs within the same layer (xz plane projection).
  // If a branch overshoots the main, trim it at the intersection.
  // Auto-insert a sub_type='mbT' (main-branch tee) connection feature at the intersection.
  function rebuildIrrigationConnections(layerId) {
    // 1. Remove existing connections (for this layer)
    var toRemove = _fittings.filter(function (f) {
      return f.kind === 'irrigation_connection' && f.layer_id === layerId;
    }).map(function (f) { return f.id; });
    toRemove.forEach(function (id) {
      _fittings = _fittings.filter(function (f) { return f.id !== id; });
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: id } }));
    });

    var pipes = _fittings.filter(function (f) {
      return f.kind === 'irrigation_pipe' && f.layer_id === layerId && !f.is_vertical;
    });

    // 2. For each branch pipe, check intersection with the main -> trim + insert tee
    pipes.forEach(function (p) { p.connected_main_id = null; });

    for (var i = 0; i < pipes.length; i++) {
      for (var j = i + 1; j < pipes.length; j++) {
        var a = pipes[i], b = pipes[j];
        if (a.sub_type === 'main' && b.sub_type === 'main') continue; // main-to-main handled separately, deferred
        var inter = _findFirstIntersection(a, b);
        if (!inter) continue;
        var main = (a.sub_type === 'main') ? a : (b.sub_type === 'main' ? b : null);
        var branch = (main === a) ? b : (main === b ? a : null);
        if (main && branch) {
          _trimBranchAtPoint(branch, inter);
          branch.connected_main_id = main.id;
          _insertConnectionNode(layerId, inter, 'mbT');
        } else {
          _insertConnectionNode(layerId, inter, 'bT');
        }
      }
    }

    // 3. Auto-connect vertical riser <-> horizontal pipe
    // If a vertical pipe (is_vertical) top point [x, layerH, z] lies on some horizontal pipe,
    // insert a connection node at that position. Simple elbow marker (riser-tee).
    var risers = _fittings.filter(function (f) {
      return f.kind === 'irrigation_pipe' && f.layer_id === layerId && f.is_vertical;
    });
    risers.forEach(function (r) {
      var segs = r.segments || [];
      if (!segs.length) return;
      var top = segs[0].to;       // riser top point
      if (!top) return;
      var rx = top[0], rz = top[2];
      // Check whether the riser top point lies on each horizontal pipe segment (xz plane)
      for (var pi = 0; pi < pipes.length; pi++) {
        var p = pipes[pi];
        var ps = p.segments || [];
        var matched = false;
        for (var si = 0; si < ps.length; si++) {
          var s = ps[si];
          var ax = s.from[0], az = s.from[2], bx = s.to[0], bz = s.to[2];
          var ddx = bx - ax, ddz = bz - az;
          var lenSq = ddx*ddx + ddz*ddz;
          if (lenSq < 1e-9) continue;
          var t = ((rx - ax) * ddx + (rz - az) * ddz) / lenSq;
          if (t < -0.01 || t > 1.01) continue;
          var ex = ax + t * ddx, ez = az + t * ddz;
          // Match if the riser top is within 8cm of the segment
          if ((ex - rx)*(ex - rx) + (ez - rz)*(ez - rz) <= 0.08*0.08) {
            _insertConnectionNode(layerId, top, p.sub_type === 'main' ? 'mT' : 'bT');
            r.connected_main_id = (p.sub_type === 'main') ? p.id : null;
            matched = true;
            break;
          }
        }
        if (matched) break;
      }
    });

    // 4. Rebuild meshes for trimmed branches + new connection features
    pipes.forEach(function (p) {
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: p.id } }));
      document.dispatchEvent(new CustomEvent('fitting-added',   { detail: { fitting: JSON.parse(JSON.stringify(p)) } }));
    });
    _render();
    _notify();
  }

  // Check all segment pairs of two pipes for intersection in the xz plane. Returns the nearest intersection.
  function _findFirstIntersection(p1, p2) {
    var s1 = p1.segments || [], s2 = p2.segments || [];
    for (var i = 0; i < s1.length; i++) {
      for (var j = 0; j < s2.length; j++) {
        var pt = _segIntersectXZ(s1[i], s2[j]);
        if (pt) return pt; // [x, y, z]
      }
    }
    return null;
  }

  // xz-plane intersection of segments A(from->to), B(from->to).
  function _segIntersectXZ(a, b) {
    if (!a || !b || !a.from || !a.to || !b.from || !b.to) return null;
    var x1 = a.from[0], z1 = a.from[2], x2 = a.to[0], z2 = a.to[2];
    var x3 = b.from[0], z3 = b.from[2], x4 = b.to[0], z4 = b.to[2];
    var denom = (x1 - x2) * (z3 - z4) - (z1 - z2) * (x3 - x4);
    if (Math.abs(denom) < 1e-9) return null;
    var t = ((x1 - x3) * (z3 - z4) - (z1 - z3) * (x3 - x4)) / denom;
    var u = -((x1 - x2) * (z1 - z3) - (z1 - z2) * (x1 - x3)) / denom;
    // Endpoint coincidence (tolerance 1e-6) is not treated as an intersection (vertex of a continuous polyline)
    var eps = 1e-6;
    if (t < -eps || t > 1 + eps || u < -eps || u > 1 + eps) return null;
    if (t < eps || t > 1 - eps) {
      if (u < eps || u > 1 - eps) return null; // endpoints meet: handled in a separate elbow branch
    }
    var x = x1 + t * (x2 - x1);
    var z = z1 + t * (z2 - z1);
    var y = a.from[1]; // same layer, so assume same height
    return [x, y, z];
  }

  // Split the branch at pt -> trim the shorter side (overshoot) and keep the longer side.
  // Same policy as geo/design `_trimOvershoot`: if the shorter side is meaningfully large (>=1m AND >= longer*0.45)
  // treat both sides as valid and do not trim.
  function _trimBranchAtPoint(branch, pt) {
    var segs = branch.segments || [];
    if (!segs.length) return false;
    var px = pt[0], pz = pt[2];

    // 1. Find the intersecting segment i + parameter t
    var foundI = -1, foundT = 0;
    for (var i = 0; i < segs.length; i++) {
      var s = segs[i];
      var ax = s.from[0], az = s.from[2], bx = s.to[0], bz = s.to[2];
      var dx = bx - ax, dz = bz - az;
      var lenSq = dx*dx + dz*dz;
      if (lenSq < 1e-9) continue;
      var t = ((px - ax) * dx + (pz - az) * dz) / lenSq;
      if (t < 1e-6 || t > 1 - 1e-6) continue;
      var ex = ax + t * dx, ez = az + t * dz;
      if ((ex - px) * (ex - px) + (ez - pz) * (ez - pz) > 0.01) continue;
      foundI = i; foundT = t; break;
    }
    if (foundI < 0) return false;

    function _segLen(s) {
      var ddx = s.to[0] - s.from[0], ddz = s.to[2] - s.from[2];
      return Math.sqrt(ddx*ddx + ddz*ddz);
    }

    // 2. Compute before / after lengths relative to the intersection
    var sI = segs[foundI];
    var sILen = _segLen(sI);
    var lenBefore = sILen * foundT;
    var lenAfter  = sILen * (1 - foundT);
    for (var k = 0; k < foundI; k++) lenBefore += _segLen(segs[k]);
    for (var k = foundI + 1; k < segs.length; k++) lenAfter += _segLen(segs[k]);

    // 3. If both sides are meaningfully large, do not trim (geo/design policy)
    var shortLen = Math.min(lenBefore, lenAfter);
    var longLen  = Math.max(lenBefore, lenAfter);
    if (shortLen >= 1.0 && shortLen >= longLen * 0.45) return false;

    // 4. Keep the longer side — cut off the shorter side (overshoot)
    var midY = (sI.from[1] != null) ? sI.from[1] : (sI.to[1] || 0);
    if (lenBefore >= lenAfter) {
      // keep before: segs[0..foundI-1] + (from -> pt)
      var newSeg = { from: sI.from.slice(), to: [px, midY, pz], is_vertical_seg: false };
      branch.segments = segs.slice(0, foundI).concat([newSeg]);
    } else {
      // keep after: (pt -> to) + segs[foundI+1..]
      var newSeg = { from: [px, midY, pz], to: sI.to.slice(), is_vertical_seg: false };
      branch.segments = [newSeg].concat(segs.slice(foundI + 1));
    }
    return true;
  }

  function _insertConnectionNode(layerId, pt, subType) {
    var id = _uid();
    var conn = {
      id: id,
      kind: 'irrigation_connection',
      layer_id: layerId,
      sub_type: subType, // 'mbT' | 'mT' | 'bT' | 'mE' | 'bE'
      position: { x: pt[0], y: pt[1], z: pt[2] },
      size: { w: 0.08, h: 0.08, d: 0.08 },
      rotation_deg: 0,
      surface_normal: null
    };
    _fittings.push(conn);
    document.dispatchEvent(new CustomEvent('fitting-added', { detail: { fitting: JSON.parse(JSON.stringify(conn)) } }));
  }

  // Get the pipe height (y). For horizontal pipes, every segment y = layer height.
  function _pipeHeight(pipe, layer, pt) {
    if (layer && layer.height_m != null) return parseFloat(layer.height_m) || 2.0;
    if (pt && pt[1] != null) return parseFloat(pt[1]) || 2.0;
    return (pipe && pipe.position && pipe.position.y) || 2.0;
  }

  // Auto-connect two pipes at different levels with a vertical pipe.
  //   aId/bId : pipe fitting id
  //   aPt/bPt : the clicked point on each pipe [x, y, z]
  // The vertical riser stands at the first pipe click point (xz), connecting the two pipe heights,
  // and auto-inserts connection points (tee) at both ends (each pipe layer height).
  function connectPipesVertical(aId, aPt, bId, bPt) {
    var a = _fittings.find(function (f) { return f.id === aId && f.kind === 'irrigation_pipe'; });
    var b = _fittings.find(function (f) { return f.id === bId && f.kind === 'irrigation_pipe'; });
    if (!a || !b || a.id === b.id) return null;
    var la = _fittings.find(function (f) { return f.id === a.layer_id; });
    var lb = _fittings.find(function (f) { return f.id === b.layer_id; });
    var ya = _pipeHeight(a, la, aPt);
    var yb = _pipeHeight(b, lb, bPt);
    if (Math.abs(ya - yb) < 0.05) return null; // same height — vertical connection is meaningless

    // Riser position: first pipe click point xz (guaranteed to be on that pipe)
    var rx = (aPt && aPt[0] != null) ? aPt[0] : 0;
    var rz = (aPt && aPt[2] != null) ? aPt[2] : 0;
    var yLow  = Math.min(ya, yb);
    var yHigh = Math.max(ya, yb);
    // The riser belongs to the lower pipe layer.
    var lowLayerId = (ya <= yb) ? a.layer_id : b.layer_id;

    var id = addIrrigationPipe(lowLayerId, [
      { from: [rx, yLow, rz], to: [rx, yHigh, rz], is_vertical_seg: true }
    ], { is_vertical: true, sub_type: 'riser', name: _T('irr_vconnect','Level connection') });

    var riser = _fittings.find(function (f) { return f.id === id; });
    if (riser) {
      riser.link_a_id  = a.id;
      riser.link_b_id  = b.id;
      riser.level_low  = yLow;
      riser.level_high = yHigh;
    }

    // Connection points (tee) at both ends — inserted at each pipe layer height
    _insertConnectionNode(a.layer_id, [rx, ya, rz], a.sub_type === 'main' ? 'mT' : 'bT');
    _insertConnectionNode(b.layer_id, [rx, yb, rz], b.sub_type === 'main' ? 'mT' : 'bT');

    _render();
    _notify();
    return id;
  }

  function setLayerHeight(layerId, newHeight) {
    var layer = _fittings.find(function (f) { return f.id === layerId; });
    if (!layer || layer.kind !== 'irrigation_layer') return;
    var oldH = layer.height_m || 2.0;
    layer.height_m = newHeight;
    layer.position.y = newHeight;
    // move all child pipes to new height
    _fittings.forEach(function (f) {
      if (f.kind !== 'irrigation_pipe' || f.layer_id !== layerId) return;
      f.position.y = newHeight;
      if (Array.isArray(f.segments)) {
        f.segments = f.segments.map(function (seg) {
          var fr = seg.from ? seg.from.slice() : [0, oldH, 0];
          var to = seg.to   ? seg.to.slice()   : [0, oldH, 0];
          if (!seg.is_vertical_seg) {
            fr[1] = newHeight;
            to[1] = newHeight;
          } else {
            // vertical risers: keep from Y=0, update to Y
            to[1] = newHeight;
          }
          return { from: fr, to: to, is_vertical_seg: seg.is_vertical_seg };
        });
      }
      // rebuild mesh in-place
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: f.id } }));
      document.dispatchEvent(new CustomEvent('fitting-added',   { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
    });
    // Irrigation devices (sprinkler/drip) move along too
    _fittings.forEach(function (f) {
      if (f.kind !== 'irrigation_device' || f.layer_id !== layerId) return;
      if (f.position) f.position.y = newHeight;
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: f.id } }));
      document.dispatchEvent(new CustomEvent('fitting-added',   { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
    });
    // Connection points (tee/elbow) move along too
    _fittings.forEach(function (f) {
      if (f.kind !== 'irrigation_connection' || f.layer_id !== layerId) return;
      if (f.position) f.position.y = newHeight;
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: f.id } }));
      document.dispatchEvent(new CustomEvent('fitting-added',   { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
    });
    // Valves move along too
    _fittings.forEach(function (f) {
      if (f.kind !== 'irrigation_valve' || f.layer_id !== layerId) return;
      if (f.position) f.position.y = newHeight;
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: f.id } }));
      document.dispatchEvent(new CustomEvent('fitting-added',   { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
    });
    // rebuild layer marker
    document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: layerId } }));
    document.dispatchEvent(new CustomEvent('fitting-added',   { detail: { fitting: JSON.parse(JSON.stringify(layer)) } }));
    _render();
    _notify();
  }

  function getActiveLayerId() {
    if (!_selectedId) return null;
    var f = _fittings.find(function (x) { return x.id === _selectedId; });
    if (!f) return null;
    if (f.kind === 'irrigation_layer') return f.id;
    if (f.kind === 'irrigation_pipe' && f.layer_id) return f.layer_id;
    return null;
  }

  // position: {x, y, z}  opts: { sub_type: 'sprinkler'|'drip', pipe_id, flow_lph }
  function addIrrigationDevice(layerId, position, opts) {
    var layer = _fittings.find(function (f) { return f.id === layerId; });
    if (!layer || layer.kind !== 'irrigation_layer') return null;
    opts = opts || {};
    var id = _uid();
    var subType = opts.sub_type || 'sprinkler';
    var orientation = (opts.orientation === 'up') ? 'up' : 'down';
    var f = {
      id: id,
      kind: 'irrigation_device',
      layer_id: layerId,
      pipe_id: opts.pipe_id || null,
      name: subType === 'drip' ? _T('Drip','Drip') : (orientation === 'up' ? _T('irr_up_spr','Up sprinkler') : _T('Sprinkler','Sprinkler')),
      sub_type: subType,
      orientation: orientation,
      flow_lph: opts.flow_lph || 850,
      radius_m: opts.radius_m != null ? opts.radius_m : 11,
      position: { x: position.x, y: position.y, z: position.z },
      size: { w: 0.05, h: 0.05, d: 0.05 },
      rotation_deg: 0,
      surface_normal: null,
      actuator_id: null,
      input_id: null
    };
    _fittings.push(f);
    document.dispatchEvent(new CustomEvent('fitting-added', { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
    _notify();
    return id;
  }

  // Valve attached to pipeId (optional). If position is unset: midpoint of the pipe first segment, or layer center if no pipe.
  // opts: { valve_type: 'on_off'|'proportional', default_state: 'closed'|'open', name, t }
  function addIrrigationValve(layerId, pipeId, position, opts) {
    var layer = _fittings.find(function (f) { return f.id === layerId; });
    if (!layer || layer.kind !== 'irrigation_layer') return null;
    opts = opts || {};
    var pipe = pipeId ? _fittings.find(function (f) { return f.id === pipeId && f.kind === 'irrigation_pipe'; }) : null;
    var pos = position;
    if (!pos && pipe && Array.isArray(pipe.segments) && pipe.segments.length > 0) {
      var seg = pipe.segments[0];
      var fr = seg.from || [0,0,0], to = seg.to || [0,0,0];
      var t = (typeof opts.t === 'number') ? opts.t : 0.5;
      pos = { x: fr[0] + (to[0]-fr[0])*t, y: fr[1] + (to[1]-fr[1])*t, z: fr[2] + (to[2]-fr[2])*t };
    }
    if (!pos) pos = { x: layer.position.x, y: layer.height_m || 2.0, z: layer.position.z };
    var id = _uid();
    var valveType = (opts.valve_type === 'proportional') ? 'proportional' : 'on_off';
    var f = {
      id: id,
      kind: 'irrigation_valve',
      layer_id: layerId,
      pipe_id: pipe ? pipe.id : null,
      attach_t: (typeof opts.t === 'number') ? opts.t : (pipe ? 0.5 : null),
      name: opts.name || (_T('irr_valve_word','Valve')+' ' + (_fittings.filter(function (x) { return x.kind === 'irrigation_valve' && x.layer_id === layerId; }).length + 1)),
      valve_type: valveType,
      default_state: opts.default_state || 'closed',
      flow_coeff_kv: null,
      // Downstream pipe (shutoff/regulation target). If unset, auto-inferred (may be filled during rebuildConnections).
      controls: {
        downstream_pipe_ids: [],
        mode: 'auto'
      },
      position: { x: pos.x, y: pos.y, z: pos.z },
      size: { w: 0.15, h: 0.15, d: 0.15 },
      rotation_deg: 0,
      surface_normal: null,
      actuator_id: null,
      input_id: null
    };
    _fittings.push(f);
    _selectedId = id;
    _render();
    document.dispatchEvent(new CustomEvent('fitting-added', { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
    _notify();
    return id;
  }

  // Remove all pipes/devices/connections/valves in the layer (keep the layer itself)
  function clearIrrigationPipes(layerId) {
    var toRemove = _fittings.filter(function (f) {
      return f.layer_id === layerId &&
        (f.kind === 'irrigation_pipe' || f.kind === 'irrigation_device' ||
         f.kind === 'irrigation_connection' || f.kind === 'irrigation_valve');
    }).map(function (f) { return f.id; });
    toRemove.forEach(function (id) {
      _fittings = _fittings.filter(function (f) { return f.id !== id; });
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: id } }));
    });
    _notify();
  }

  // Stats: for each branch pipe in the layer { no, length_m, emitters, flow_lph, flow_lpm }
  function getIrrigationStats(layerId) {
    var pipes = _fittings.filter(function (f) {
      return f.layer_id === layerId && f.kind === 'irrigation_pipe' && !f.is_vertical;
    });
    var devices = _fittings.filter(function (f) {
      return f.layer_id === layerId && f.kind === 'irrigation_device';
    });
    return pipes.map(function (pipe, idx) {
      var segs = Array.isArray(pipe.segments) ? pipe.segments : [];
      var len = segs.reduce(function (acc, s) {
        var dx = s.to[0] - s.from[0], dz = s.to[2] - s.from[2];
        return acc + Math.sqrt(dx * dx + dz * dz);
      }, 0);
      var pipeDevices = devices.filter(function (d) { return d.pipe_id === pipe.id; });
      var emitters = pipeDevices.length;
      var flow_lph = pipeDevices.reduce(function (acc, d) { return acc + (parseFloat(d.flow_lph) || 0); }, 0);
      return {
        no: idx + 1,
        name: pipe.name || (_T('m_irr_pipe','Pipe')+' ' + (idx + 1)),
        length_m: Math.round(len * 10) / 10,
        emitters: emitters,
        flow_lph: Math.round(flow_lph),
        flow_lpm: Math.round(flow_lph / 60 * 10) / 10
      };
    });
  }

  // ── Category visibility — persisted via localStorage + facility spec ──────────────────
  var _CAT_KEYS = ['envelope','opening','climate','sensor','fixture','irrig'];
  var _catVisState = (function () {
    var s = {};
    _CAT_KEYS.forEach(function (k) { s[k] = true; });
    return s;
  })();
  var _facilityUuidForVis = null;
  function _visLsKey() {
    return 'facility-3d-cat-vis-' + (_facilityUuidForVis || 'default');
  }
  function _loadVisFromLocalStorage() {
    try {
      var raw = window.localStorage && localStorage.getItem(_visLsKey());
      if (!raw) return;
      var obj = JSON.parse(raw);
      _CAT_KEYS.forEach(function (k) { if (obj && typeof obj[k] === 'boolean') _catVisState[k] = obj[k]; });
    } catch (e) {}
  }
  function _saveVisToLocalStorage() {
    try {
      if (window.localStorage) localStorage.setItem(_visLsKey(), JSON.stringify(_catVisState));
    } catch (e) {}
  }
  function _getCategoryVisible(cat) {
    return _catVisState.hasOwnProperty(cat) ? !!_catVisState[cat] : true;
  }
  function setCategoryVisibility(cat, visible) {
    if (!_catVisState.hasOwnProperty(cat)) return;
    _catVisState[cat] = !!visible;
    _saveVisToLocalStorage();
    // The 3D viewport is bridged via events (geo_facility.html calls _ctx.setCategoryVisibility)
    document.dispatchEvent(new CustomEvent('aot-facility-cat-visibility-changed', {
      detail: { category: cat, visible: !!visible, state: Object.assign({}, _catVisState) }
    }));
    _renderList();
  }
  function toggleCategoryVisibility(cat) {
    setCategoryVisibility(cat, !_getCategoryVisible(cat));
  }
  function getCategoryVisibility() { return Object.assign({}, _catVisState); }
  function loadCategoryVisibility(state, facilityUuid) {
    if (facilityUuid) _facilityUuidForVis = facilityUuid;
    _loadVisFromLocalStorage();   // localStorage takes priority
    if (state && typeof state === 'object') {
      // Prefer the facility spec value over localStorage — it is an explicitly saved value
      _CAT_KEYS.forEach(function (k) {
        if (typeof state[k] === 'boolean') _catVisState[k] = state[k];
      });
    }
    _renderList();
  }

  window.FittingsUI = {
    add: add, addAt: addAt, remove: remove, select: select,
    getSelectedId: getSelectedId,
    importFromCatalog: importFromCatalog,
    aggregate: aggregate,
    syncEnvelopeItems: syncEnvelopeItems,
    read: read, readAll: readAll, fill: fill, init: init,
    getInputList: function () { return _inputChoices; },
    // Category visibility
    getCategoryVisibility: getCategoryVisibility,
    setCategoryVisibility: setCategoryVisibility,
    toggleCategoryVisibility: toggleCategoryVisibility,
    loadCategoryVisibility: loadCategoryVisibility,
    // Irrigation devices
    addIrrigationLayer: addIrrigationLayer,
    addIrrigationPipe: addIrrigationPipe,
    addIrrigationDevice: addIrrigationDevice,
    addIrrigationValve: addIrrigationValve,
    clearIrrigationPipes: clearIrrigationPipes,
    getIrrigationStats: getIrrigationStats,
    setLayerHeight: setLayerHeight,
    getActiveLayerId: getActiveLayerId,
    startPipe: startPipe,
    extendPipe: extendPipe,
    finishPipe: finishPipe,
    connectPipesVertical: connectPipesVertical,
    rebuildIrrigationConnections: rebuildIrrigationConnections,
    updateFittingPosition: function (id, pos) {
      var f = _fittings.find(function (x) { return x.id === id; });
      if (!f || !pos) return;
      // Same rule the inspector fields follow: a hand-moved envelope item stops
      // tracking the envelope, otherwise the next regeneration silently undoes
      // the drag.
      if (f.source === 'envelope') f._auto_geom = false;
      f.position.x = pos.x != null ? pos.x : f.position.x;
      f.position.y = pos.y != null ? pos.y : f.position.y;
      f.position.z = pos.z != null ? pos.z : f.position.z;
    },
    // Change a fitting's kind with the same side effects the inspector applies:
    // group sync, list refresh and an in-place mesh recreation (colour and
    // geometry depend on kind). Without this, changing kind anywhere else
    // leaves a stale 3D mesh behind.
    // Put an envelope item back under automatic geometry. Editing size or
    // position detaches it; without a way back the only remedy would be to
    // toggle the whole envelope feature off and on.
    setAutoGeom: function (id, on) {
      var f = _fittings.find(function (x) { return x.id === id; });
      if (!f || f.source !== 'envelope') return false;
      f._auto_geom = (on !== false);
      return true;
    },
    setKind: function (id, kind) {
      var f = _fittings.find(function (x) { return x.id === id; });
      if (!f || !kind || f.kind === kind) return false;
      f.kind = kind;
      if (f.link_group) _syncGroup(f.id);
      _renderList();
      document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: f.id } }));
      document.dispatchEvent(new CustomEvent('fitting-added',
        { detail: { fitting: JSON.parse(JSON.stringify(f)) } }));
      if (f.link_group) {
        _fittings.forEach(function (g) {
          if (g.link_group === f.link_group && g.id !== f.id) {
            document.dispatchEvent(new CustomEvent('fitting-removed', { detail: { id: g.id } }));
            document.dispatchEvent(new CustomEvent('fitting-added',
              { detail: { fitting: JSON.parse(JSON.stringify(g)) } }));
          }
        });
      }
      document.dispatchEvent(new CustomEvent('fittings-data-changed'));
      return true;
    },
    // Actuator options for the component table (same source the inspector uses)
    getOutputList: function () { return (OutputCache.list || []).slice(); },
    patchFitting: function (id, props) {
      var f = _fittings.find(function (x) { return x.id === id; });
      if (!f) return false;
      Object.keys(props).forEach(function (k) { f[k] = props[k]; });
      if ('actuator_id' in props) _syncActuatorGroup(id);
      // Keep channel_measurements[0] in sync with top-level sensor channel fields
      // so facility_integration.py (which prefers channel_measurements) sees the change.
      if (f.kind === 'sensor' && ('measurement_id' in props || 'measurement_type' in props)) {
        if (!Array.isArray(f.channel_measurements)) f.channel_measurements = [];
        if (f.channel_measurements.length === 0) f.channel_measurements.push({});
        if ('measurement_id'   in props) f.channel_measurements[0].measurement_id   = props.measurement_id;
        if ('measurement_type' in props) f.channel_measurements[0].measurement_type = props.measurement_type;
      }
      return true;
    }
  };
})();

// ── Main facility design logic ─────────────────────────────────────────────────
(function () {
  'use strict';

  const State = {
    map: null,
    outerGeometry: null,
    facilityUuid: null,
    availableOutputs: [],
    center: null,           // [lng, lat] — facility center on the map
    orientationDeg: 0,      // 0~359, rotation around center
    placeMode: false,       // true while waiting for a single click to set center
    sites: [],              // site features for the active map
    selectedSiteUuid: null, // GeoShape unique_id of the selected site
    _baseStyleLayerIds: []  // snapshot of base style layer IDs for layer panel
  };

  // State lives inside this IIFE, so the page's inline scripts cannot reach the
  // map. The facility page hides the map while other steps are shown, and a
  // MapLibre map created (or left) in a hidden container keeps a stale canvas
  // size until it is told to re-measure — expose just that.
  // Switching facilities used to be a page navigation, which closed the step
  // drawer and lost the current step. These do it in place.
  window.FacilityIO = {
    select: selectFacility,
    create: newFacility
  };

  window.FacilityMapAPI = {
    resize: function () {
      if (State.map && typeof State.map.resize === 'function') State.map.resize();
    },
    isReady: function () { return !!State.map; },
    // Has the facility been placed on the map yet? The step bar uses this to
    // flag the position step as incomplete.
    hasCenter: function () { return !!State.center; }
  };

  const SITE_SRC = 'map-sites';
  const SITE_LYR_FILL = 'map-sites-fill';
  const SITE_LYR_LINE = 'map-sites-line';

  // CARTO Voyager raster fallback (used when AOT_GEO_CONFIG has no usable layer)
  const FALLBACK_RASTER_STYLE = {
    version: 8,
    sources: {
      basemap: {
        type: 'raster',
        tiles: [
          'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
          'https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
          'https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
          'https://d.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png'
        ],
        tileSize: 256,
        maxzoom: 19,
        attribution: '© OpenStreetMap © CARTO'
      }
    },
    layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }]
  };

  /**
   * Resolve a MapLibre style spec from window.AOT_GEO_CONFIG (same source of truth
   * as /geo/design). Tries:
   *   1. config.layers[*]: first enabled raster (xyz/wms/tile)
   *   2. config.providers.osm or .raster URL pattern
   *   3. CARTO Voyager fallback (cached above)
   */
  function resolveBaseStyle() {
    const cfg = window.AOT_GEO_CONFIG || {};
    const layers = Array.isArray(cfg.layers) ? cfg.layers : [];

    // 1. First active raster layer (xyz/wms/tile)
    for (const L of layers) {
      if (L && L.enabled === false) continue;
      const t = String(L.type || '').toLowerCase();
      const opts = L.options || L;
      const url = opts.url || opts.tileUrl || opts.tiles || L.url;
      if (url && (t.includes('xyz') || t.includes('tile') || t.includes('raster') || t.includes('osm'))) {
        return rasterStyleFromUrl(Array.isArray(url) ? url : [url], opts.attribution || L.attribution);
      }
    }

    // 2. providers fallback
    const providers = cfg.providers || {};
    for (const key of ['osm', 'raster', 'base', 'default']) {
      const p = providers[key];
      const url = (p && (p.url || p.tileUrl)) || null;
      if (url) {
        return rasterStyleFromUrl([url], (p && p.attribution) || '');
      }
    }

    // 3. fallback
    console.warn('[facility] AOT_GEO_CONFIG has no usable raster layer; using CARTO Voyager fallback.');
    return FALLBACK_RASTER_STYLE;
  }

  function rasterStyleFromUrl(tiles, attribution) {
    return {
      version: 8,
      sources: {
        basemap: {
          type: 'raster',
          tiles: tiles,
          tileSize: 256,
          maxzoom: 19,
          attribution: attribution || ''
        }
      },
      layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }]
    };
  }

  document.addEventListener('DOMContentLoaded', async function () {
    const vars = JSON.parse(document.getElementById('facility-page-vars').textContent);
    State.facilityUuid = vars.facility_uuid || null;

    if (window.EnvelopeUI)  EnvelopeUI.init();
    if (window.ActuatorUI)  ActuatorUI.init();
    if (window.FittingsUI)  FittingsUI.init();
    initMap();
    bindEventHandlers();
    await loadOutputs();

    if (State.facilityUuid) {
      await loadFacility(State.facilityUuid);
      loadIntegration(State.facilityUuid);
    }
    // After map style/sources ready, populate facility-prod + sites for the active map.
    State.map.on('load', () => {
      const sel = document.getElementById('map-selector');
      const initialGeoId = (sel && sel.value) || null;
      if (initialGeoId) {
        loadSavedFacilities(initialGeoId);
        loadSites(initialGeoId);
      }
    });
    debouncedCompute();
  });

  // =========================================================
  // Map
  // =========================================================
  function initMap() {
    const cfg = window.AOT_GEO_CONFIG || {};
    const initLat  = parseFloat(cfg.default_lat)  || 37.5665;
    const initLng  = parseFloat(cfg.default_lng)  || 126.9780;
    const initZoom = parseFloat(cfg.zoom)         || 13;

    State.map = new maplibregl.Map({
      container: 'facility-map-canvas',
      style: resolveBaseStyle(),
      center: [initLng, initLat],
      zoom: initZoom,
      maxZoom: 19,             // basemap tiles end at z=19
      pitch: 45,               // start in 3D camera so extrusion is visible
      bearing: 0,
      doubleClickZoom: false   // legacy; no-op since draw mode removed
    });
    State.map.addControl(
      new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }),
      'top-left'
    );

    State.map.on('load', async () => {
      try {
      // ============================================================
      // facility-prod: All saved facilities for this map (3D footprints)
      // ============================================================
      // Capture base style layer IDs BEFORE adding any facility/site layers so that
      // FacilityLayerPanel correctly identifies which layers belong to the base style.
      // If captured after, facility-prod layers are mistakenly treated as base layers
      // and are not restored after a base-map style switch — causing fill-extrusion
      // to re-appear as visible after the switch.
      State._baseStyleLayerIds = (State.map.getStyle().layers || []).map(l => l.id);

      State.map.addSource('facility-prod', { type: 'geojson', data: emptyFC() });
      State.map.addLayer({
        id: 'facility-prod-fill', type: 'fill', source: 'facility-prod',
        paint: { 'fill-color': '#5E6B64', 'fill-opacity': 0.15 }
      });
      State.map.addLayer({
        id: 'facility-prod-line', type: 'line', source: 'facility-prod',
        paint: { 'line-color': '#13261B', 'line-width': 1.5 }
      });
      State.map.addLayer({
        id: 'facility-prod-3d', type: 'fill-extrusion', source: 'facility-prod',
        layout: { visibility: 'none' },   // hidden: Three.js overlay replaces this
        paint: {
          'fill-extrusion-color': '#5E6B64',
          'fill-extrusion-height': ['coalesce', ['get', 'height_m'], 4],
          'fill-extrusion-base':   ['coalesce', ['get', 'base_m'], 0],
          'fill-extrusion-opacity': 0.55
        }
      });

      // ============================================================
      // map-sites: Site shapes belonging to the active map (toggle layer)
      // ============================================================

      State.map.addSource(SITE_SRC, { type: 'geojson', data: emptyFC() });
      State.map.addLayer({
        id: SITE_LYR_FILL, type: 'fill', source: SITE_SRC,
        paint: { 'fill-color': '#FEA60B', 'fill-opacity': 0.15 }
      });
      State.map.addLayer({
        id: SITE_LYR_LINE, type: 'line', source: SITE_SRC,
        paint: { 'line-color': '#FEAE5F', 'line-width': 2, 'line-dasharray': [2, 1] }
      });

      // ============================================================
      // facility-preview: Currently-edited facility (highlight color)
      // ============================================================
      State.map.addSource('facility-preview', { type: 'geojson', data: emptyFC() });
      State.map.addLayer({
        id: 'facility-preview-fill', type: 'fill', source: 'facility-preview',
        paint: { 'fill-color': '#2DB4FF', 'fill-opacity': 0.18 }
      });
      State.map.addLayer({
        id: 'facility-preview-line', type: 'line', source: 'facility-preview',
        paint: { 'line-color': '#13261B', 'line-width': 2.5 }
      });
      State.map.addLayer({
        id: 'facility-preview-3d', type: 'fill-extrusion', source: 'facility-preview',
        layout: { visibility: 'none' },   // hidden: Three.js overlay replaces this
        paint: {
          'fill-extrusion-color': '#13261B',
          'fill-extrusion-height': ['coalesce', ['get', 'height_m'], 4],
          'fill-extrusion-base':   ['coalesce', ['get', 'base_m'], 0],
          'fill-extrusion-opacity': 0.7
        }
      });

      // Initialize the map layer panel (same feature as geo/design)
      if (window.FacilityLayerPanel) FacilityLayerPanel.init(State);

      // Hover popup for saved facilities
      State.map.on('click', 'facility-prod-fill', onProdFacilityClick);
      State.map.on('mouseenter', 'facility-prod-fill', () => {
        State.map.getCanvas().style.cursor = 'pointer';
      });
      State.map.on('mouseleave', 'facility-prod-fill', () => {
        if (!State.placeMode) State.map.getCanvas().style.cursor = '';
      });

      // Register Three.js 3D overlay — hides fill-extrusion boxes, uses real mesh
      if (window.AoTFacilityMap3D) {
        AoTFacilityMap3D.attach(State.map, []);
      }

      // Push preloaded geometry to preview source
      if (State.outerGeometry) {
        rebuildOuterGeometry();
      }
      } catch (e) {
        console.error('[facility] map load handler error:', e);
      }
    });

    // Click/dblclick listeners — registered immediately (no race with 'load')
    State.map.on('click', onMapClick);
    State.map.on('dblclick', onMapDblClick);

    document.getElementById('map-selector').addEventListener('change', (e) => {
      const opt = e.target.selectedOptions[0];
      if (!opt) return;
      const lat = parseFloat(opt.dataset.lat);
      const lng = parseFloat(opt.dataset.lng);
      const zoom = parseFloat(opt.dataset.zoom) || 13;
      if (!isNaN(lat) && !isNaN(lng)) {
        State.map.flyTo({ center: [lng, lat], zoom });
      }
      // Reload saved facilities + sites for the newly selected map
      loadSavedFacilities(opt.value);
      loadSites(opt.value);
    });

    const siteSel = document.getElementById('site-selector');
    if (siteSel) siteSel.addEventListener('change', (e) => onSiteChange(e.target.value));
  }

  function emptyFC() {
    return { type: 'FeatureCollection', features: [] };
  }

  function setOuterGeometry(geom, props) {
    State.outerGeometry = geom;
    const fc = geom
      ? { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: geom, properties: props || {} }] }
      : emptyFC();
    if (State.map && State.map.getSource('facility-preview')) {
      State.map.getSource('facility-preview').setData(fc);
    }
    _update3DPreview();
  }

  // =========================================================
  // Saved facilities (facility-prod source)
  // =========================================================
  async function loadSavedFacilities(geoId) {
    if (!State.map || !State.map.getSource('facility-prod')) return;
    if (!geoId) {
      State.map.getSource('facility-prod').setData(emptyFC());
      return;
    }
    try {
      const url = '/api/geo/facility/list?geo_id=' + encodeURIComponent(geoId);
      const res = await fetch(url, { credentials: 'same-origin' });
      const json = await res.json();
      if (!json.ok) return;
      const prodFacilities = (json.facilities || [])
        .filter(f => f.unique_id !== State.facilityUuid);  // exclude facility under edit
      const features = prodFacilities.map(toProdFeature).filter(Boolean);
      State.map.getSource('facility-prod').setData({
        type: 'FeatureCollection', features: features
      });
      _load3DProdFacilities(prodFacilities);
    } catch (e) {
      console.warn('[facility] loadSavedFacilities failed:', e);
    }
  }

  function toProdFeature(f) {
    const geom = f.outer_feature && f.outer_feature.geometry;
    if (!geom) return null;
    const g3d = f.geometry_3d || {};
    return {
      type: 'Feature',
      geometry: geom,
      properties: {
        facility_uuid: f.unique_id,
        name: f.name,
        preset: f.preset,
        structure: f.structure,
        bay_count: f.bay_count,
        height_m: g3d.ridge_height_m || 4,
        eave_h: g3d.eave_height_m || 2,
        base_m: 0
      }
    };
  }

  function onProdFacilityClick(e) {
    const ft = e.features && e.features[0];
    if (!ft) return;
    const p = ft.properties || {};
    const structureLabel = p.structure === 'connected'
      ? ' · connected ×' + p.bay_count
      : ' · single';
    const html =
      '<div style="font-size:var(--aot-font-size-sm)"><strong>' + (p.name || '(unnamed)') + '</strong>' +
      '<br><small>' + (p.preset || '') + structureLabel + '</small>' +
      '<br><a href="?facility_uuid=' + p.facility_uuid + '">Edit</a></div>';
    new maplibregl.Popup({ closeOnClick: true })
      .setLngLat(e.lngLat)
      .setHTML(html)
      .addTo(State.map);
  }

  // =========================================================
  // Sites for the active map (Phase B — site selector)
  // =========================================================
  // layout_default.html upgrades every .aot-modern-select into a bootstrap-select
  // at load, and that widget renders its own copy of the option list. Rewriting
  // the <select> from JS leaves the visible list stale: the site picker offered
  // only "Select a Map first" while the select underneath already held every
  // site of the chosen map. Anything that repopulates such a select has to say so.
  function _syncPicker(el) {
    if (!el || !window.jQuery) return;
    try {
      if (jQuery(el).data('selectpicker')) jQuery(el).selectpicker('refresh');
    } catch (e) { /* not enhanced — the native select is already correct */ }
  }

  async function loadSites(geoId) {
    const sel = document.getElementById('site-selector');
    if (!sel) return;
    State.sites = [];
    State.selectedSiteUuid = null;
    sel.innerHTML = '';
    updateSiteLayerData();

    if (!geoId) {
      sel.disabled = true;
      sel.innerHTML = '<option value="" disabled selected>' + _tr('Select a Map first') + '</option>';
      _syncPicker(sel);
      return;
    }
    try {
      const url = '/api/geo/overlays?map_uuid=' + encodeURIComponent(geoId) + '&type=site';
      const res = await fetch(url, { credentials: 'same-origin' });
      const json = await res.json();
      const features = (json && json.features) || [];
      State.sites = features;
      updateSiteLayerData();

      if (features.length === 0) {
        sel.disabled = true;
        sel.innerHTML = '<option value="" disabled selected>' + _tr('No sites in this map') + '</option>';
        _syncPicker(sel);
        return;
      }
      sel.disabled = false;
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = _tr('— Select a Site —');
      placeholder.selected = true;
      sel.appendChild(placeholder);
      features.forEach((f) => {
        const props = f.properties || {};
        const opt = document.createElement('option');
        opt.value = props.unique_id || props.db_id || '';
        opt.textContent = props.name || ('Site #' + (props.db_id || ''));
        sel.appendChild(opt);
      });
      _syncPicker(sel);
    } catch (e) {
      console.warn('[facility] loadSites failed:', e);
      sel.disabled = true;
      sel.innerHTML = '<option value="" disabled selected>' + _tr('Failed to load sites') + '</option>';
      _syncPicker(sel);
    }
  }

  function onSiteChange(siteIdValue) {
    State.selectedSiteUuid = siteIdValue || null;
    if (!siteIdValue) return;
    const ft = State.sites.find((f) => {
      const p = f.properties || {};
      return String(p.unique_id) === siteIdValue || String(p.db_id) === siteIdValue;
    });
    if (!ft || !ft.geometry || !State.map) return;
    try {
      const bounds = geometryBounds(ft.geometry);
      if (bounds) State.map.fitBounds(bounds, { padding: 80, duration: 500, maxZoom: 18 });
    } catch (e) { /* ignore */ }
  }

  // =========================================================
  // Map-sites source update (called after loadSites)
  // =========================================================
  function updateSiteLayerData() {
    if (!State.map || !State.map.getSource) return;
    const src = State.map.getSource(SITE_SRC);
    if (!src) return;
    const feats = (State.sites || []).filter(f => f && f.geometry);
    src.setData({ type: 'FeatureCollection', features: feats });
  }

  // =========================================================
  // Place-on-Map mode + parametric rectangle generation
  // =========================================================
  function startPlaceMode() {
    State.placeMode = true;
    if (State.map) {
      State.map.getCanvas().style.cursor = 'crosshair';
      // dragPan steals 'click' on tiny mouse movement — disable for the placement click
      State.map.dragPan.disable();
      State.map.boxZoom.disable();
      State.map.scrollZoom.disable();
      State.map.touchZoomRotate.disable();
    }
    showToast('Click on the map to set the facility center');
  }

  function finishPlaceMode() {
    State.placeMode = false;
    if (State.map) {
      State.map.getCanvas().style.cursor = '';
      State.map.dragPan.enable();
      State.map.boxZoom.enable();
      State.map.scrollZoom.enable();
      State.map.touchZoomRotate.enable();
    }
  }

  function onMapClick(e) {
    if (!State.placeMode) return;
    State.center = [e.lngLat.lng, e.lngLat.lat];
    rebuildOuterGeometry();
    finishPlaceMode();
    debouncedCompute();
  }

  function onMapDblClick(e) {
    // No-op — kept for backward compat with previous draw-mode listeners
  }

  /** Build outer GeoJSON from form: dimensions + center + orientation + structure/bays/spacing. */
  function rebuildOuterGeometry() {
    if (!State.center) return;
    const span = parseFloat(document.getElementById('span-width').value) || 7;
    const length = parseFloat(document.getElementById('length-m').value) || 30;
    const ridgeH = parseFloat(document.getElementById('ridge-height').value) || 4;
    const eaveH  = parseFloat(document.getElementById('eave-height').value) || 2;
    const struct = (document.querySelector('input[name="structure"]:checked') || {}).value || 'single';
    const bayCount = Math.max(parseInt(document.getElementById('bay-count').value, 10) || 1, 1);
    const spacing = parseFloat((document.getElementById('spacing-m') || {}).value) || 0;
    const deg = Number.isFinite(State.orientationDeg) ? State.orientationDeg : 0;

    let geom;
    if (struct === 'single' && bayCount > 1) {
      // N detached single-bay greenhouses arranged in a row with `spacing` between
      geom = buildMultiRectGeoJSON(State.center, span, length, bayCount, spacing, deg);
    } else {
      // Single (1 bay) OR Connected (one envelope spanning all bays)
      const W = struct === 'connected' ? span * bayCount : span;
      geom = buildRotatedRectGeoJSON(State.center, W, length, deg);
    }
    setOuterGeometry(geom, { height_m: ridgeH, eave_h: eaveH, base_m: 0 });
  }

  /** One rotated rectangle (Polygon) at center. */
  function buildRotatedRectGeoJSON(center, W_m, L_m, deg) {
    const ring = rotatedRectRing(center, 0, 0, W_m, L_m, deg);
    return { type: 'Polygon', coordinates: [ring] };
  }

  /** N rotated rectangles arranged along the span axis (MultiPolygon).
   * The group is rotated together by `deg`, so each bay shares the same orientation.
   */
  function buildMultiRectGeoJSON(center, span, length, count, spacing, deg) {
    const totalSpan = span * count + spacing * (count - 1);
    const halfTotal = totalSpan / 2;
    const polygons = [];
    for (let i = 0; i < count; i++) {
      const offX = -halfTotal + span / 2 + i * (span + spacing);
      const ring = rotatedRectRing(center, offX, 0, span, length, deg);
      polygons.push([ring]);
    }
    return { type: 'MultiPolygon', coordinates: polygons };
  }

  /** Build a single ring (closed) for a rectangle whose local center is offset
   * by (offX, offY) from `center`, then rotate the whole thing by `deg` around `center`. */
  function rotatedRectRing(center, offX, offY, W_m, L_m, deg) {
    const cLng = center[0], cLat = center[1];
    const halfW = W_m / 2, halfL = L_m / 2;
    const localCorners = [
      [offX - halfW, offY - halfL],
      [offX + halfW, offY - halfL],
      [offX + halfW, offY + halfL],
      [offX - halfW, offY + halfL]
    ];
    const theta = (deg || 0) * Math.PI / 180;
    const cosT = Math.cos(theta), sinT = Math.sin(theta);
    const M_PER_DEG_LAT = 111320.0;
    const M_PER_DEG_LNG = M_PER_DEG_LAT * Math.cos(cLat * Math.PI / 180);
    const ring = localCorners.map(function (c) {
      const dx = c[0], dy = c[1];
      const rx = dx * cosT - dy * sinT;
      const ry = dx * sinT + dy * cosT;
      return [cLng + rx / M_PER_DEG_LNG, cLat + ry / M_PER_DEG_LAT];
    });
    ring.push(ring[0]);
    return ring;
  }

  /** Collect every coordinate of a (Multi)Polygon's outer ring(s). */
  function geometryAllCoords(geom) {
    if (!geom) return [];
    if (geom.type === 'Polygon') {
      return (geom.coordinates && geom.coordinates[0]) || [];
    }
    if (geom.type === 'MultiPolygon') {
      const all = [];
      const polys = geom.coordinates || [];
      for (let i = 0; i < polys.length; i++) {
        const ring = polys[i] && polys[i][0];
        if (ring && ring.length) {
          for (let j = 0; j < ring.length; j++) all.push(ring[j]);
        }
      }
      return all;
    }
    return [];
  }

  /** Collect each outer ring separately (one array per polygon). */
  function geometryRings(geom) {
    if (!geom) return [];
    if (geom.type === 'Polygon') {
      const ring = geom.coordinates && geom.coordinates[0];
      return ring && ring.length ? [ring] : [];
    }
    if (geom.type === 'MultiPolygon') {
      const rings = [];
      const polys = geom.coordinates || [];
      for (let i = 0; i < polys.length; i++) {
        const ring = polys[i] && polys[i][0];
        if (ring && ring.length) rings.push(ring);
      }
      return rings;
    }
    return [];
  }

  function polygonCentroid(geom) {
    const rings = geometryRings(geom);
    if (!rings.length) return null;
    let sx = 0, sy = 0, n = 0;
    // Each ring is closed (last == first); skip the duplicate per ring so
    // MultiPolygon middle rings don't double-count their closing point.
    for (let r = 0; r < rings.length; r++) {
      const ring = rings[r];
      const limit = ring.length > 1 ? ring.length - 1 : ring.length;
      for (let i = 0; i < limit; i++) {
        sx += ring[i][0]; sy += ring[i][1]; n++;
      }
    }
    return n > 0 ? [sx / n, sy / n] : null;
  }

  /** Compute bounds covering all polygons (single or multi). */
  function geometryBounds(geom) {
    const coords = geometryAllCoords(geom);
    if (coords.length === 0) return null;
    const b = new maplibregl.LngLatBounds(coords[0], coords[0]);
    for (let i = 1; i < coords.length; i++) b.extend(coords[i]);
    return b;
  }

  // =========================================================
  // Actuators
  // =========================================================
  async function loadOutputs() {
    try {
      const res = await fetch('/api/geo/devices', { credentials: 'same-origin' });
      const json = await res.json();
      const list = json.devices || json || [];
      State.availableOutputs = list.filter((d) => {
        const t = (d.type || '').toLowerCase();
        return ['output', 'function', 'custom_controller', 'custom', 'pid'].includes(t);
      });
      if (window.ActuatorUI) ActuatorUI.setDevices(State.availableOutputs);
    } catch (e) {
      console.warn('[facility] loadOutputs failed:', e);
    }
  }

  // =========================================================
  // Form ↔ State
  // =========================================================
  // =========================================================
  // ZoneUI — bay 분할/통합 구역 편집기 (#zone-editor-container)
  // =========================================================
  // 구역 = 연속된 bay 범위. bay 사이 경계(boundary)를 클릭해 분할(실선)/
  // 통합(점선)을 토글한다. 기본값은 bay 당 1구역 (기존 동작과 동일).
  // 저장 형식: facility.bays = [{id, name, crop, bay_start, bay_end}]
  //   id 는 'bay_<s>' (단일) / 'bay_<s>_<e>' (병합) — env_coordinator 의
  //   bay_scope 입력과 지도 위젯 구역 칩이 이 id 를 사용한다.
  window.ZoneUI = (function () {
    var _bayCount = 1;
    var _boundaries = new Set();   // 분할 경계: bay b 와 b+1 사이 (1..N-1)
    var _names = {};               // zone bay_start → 사용자 지정 이름

    function _esc(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function _N() {
      var el = document.getElementById('bay-count');
      return Math.max(parseInt(el ? el.value : '1', 10) || 1, 1);
    }

    // 경계 집합 → 구역 목록 파생 (항상 1..N 전체를 빈틈없이 커버)
    function zones() {
      var list = [], start = 1;
      for (var i = 1; i <= _bayCount; i++) {
        if (i === _bayCount || _boundaries.has(i)) {
          var id = (start === i) ? 'bay_' + start : 'bay_' + start + '_' + i;
          var range = (start === i) ? String(start) : start + '-' + i;
          list.push({
            bay_start: start, bay_end: i, id: id,
            default_name: _T('zone_bay', 'Bay') + ' ' + range
          });
          start = i + 1;
        }
      }
      return list;
    }

    function read() {
      if (_bayCount < 2) return [];
      return zones().map(function (z) {
        return {
          id: z.id,
          name: _names[z.bay_start] || null,
          crop: null,
          bay_start: z.bay_start,
          bay_end: z.bay_end
        };
      });
    }

    function load(metas, bayCount) {
      _bayCount = Math.max(parseInt(bayCount, 10) || _N(), 1);
      _boundaries = new Set();
      _names = {};
      var valid = [];
      (metas || []).forEach(function (m) {
        if (!m) return;
        var s = parseInt(m.bay_start, 10), e = parseInt(m.bay_end, 10);
        if (s >= 1 && e >= s && e <= _bayCount) valid.push({ s: s, e: e, name: m.name });
      });
      if (valid.length) {
        valid.forEach(function (z) {
          if (z.e < _bayCount) _boundaries.add(z.e);
          if (z.name) _names[z.s] = z.name;
        });
      } else {
        for (var i = 1; i < _bayCount; i++) _boundaries.add(i);   // 기본: bay 당 1구역
      }
      render();
    }

    // bay-count 입력 변경 시: 기존 분할 유지, 새 bay 는 독립 구역으로 추가,
    // 줄어들면 범위 밖 경계 제거.
    function syncBayCount() {
      var n = _N();
      if (n === _bayCount) return;
      var nb = new Set();
      _boundaries.forEach(function (b) { if (b < n) nb.add(b); });
      for (var b = _bayCount; b >= 1 && b < n; b++) nb.add(b);
      _boundaries = nb;
      _bayCount = n;
      render();
    }

    function render() {
      var box = document.getElementById('zone-editor-container');
      var bar = document.getElementById('zone-segment-bar');
      var list = document.getElementById('zone-name-list');
      if (!box || !bar || !list) return;
      if (_bayCount < 2) { box.classList.add('d-none'); return; }
      box.classList.remove('d-none');

      var zs = zones();
      var zi = 0, html = '';
      for (var b = 1; b <= _bayCount; b++) {
        if (b > zs[zi].bay_end) zi++;
        html += '<div class="zone-bay-cell zone-c' + (zi % 6) + '">' + b + '</div>';
        if (b < _bayCount) {
          var split = _boundaries.has(b);
          html += '<div class="zone-boundary' + (split ? ' split' : '') + '" data-b="' + b + '"' +
                  ' title="' + _esc(split ? _T('zone_merge', 'Merge zones') : _T('zone_split', 'Split zones')) + '"></div>';
        }
      }
      bar.innerHTML = html;

      list.innerHTML = zs.map(function (z, i) {
        var range = (z.bay_start === z.bay_end) ? String(z.bay_start) : z.bay_start + '–' + z.bay_end;
        return '<div class="zone-name-row">' +
          '<span class="zone-chip zone-c' + (i % 6) + '" title="ID: ' + _esc(z.id) + '">' + range + '</span>' +
          '<input type="text" class="form-control aot-modern-input zone-name-input" data-start="' + z.bay_start + '"' +
          ' placeholder="' + _esc(z.default_name) + '"' +
          ' value="' + _esc(_names[z.bay_start] || '') + '">' +
          '</div>';
      }).join('');
    }

    function bind() {
      var bar = document.getElementById('zone-segment-bar');
      var list = document.getElementById('zone-name-list');
      if (bar && !bar._zoneWired) {
        bar._zoneWired = true;
        bar.addEventListener('click', function (e) {
          var bd = e.target.closest('.zone-boundary');
          if (!bd) return;
          var b = parseInt(bd.dataset.b, 10);
          if (_boundaries.has(b)) _boundaries.delete(b); else _boundaries.add(b);
          render();
        });
      }
      if (list && !list._zoneWired) {
        list._zoneWired = true;
        list.addEventListener('input', function (e) {
          var inp = e.target.closest('.zone-name-input');
          if (!inp) return;
          var s = parseInt(inp.dataset.start, 10);
          var v = inp.value.trim();
          if (v) _names[s] = v; else delete _names[s];
        });
      }
      var bc = document.getElementById('bay-count');
      if (bc && !bc._zoneWired) {
        bc._zoneWired = true;
        bc.addEventListener('input', syncBayCount);
      }
    }

    return { read: read, load: load, bind: bind, syncBayCount: syncBayCount };
  })();

  function readForm() {
    const data = {
      facility_uuid: State.facilityUuid || undefined,
      geo_id: document.getElementById('map-selector').value,
      site_shape_uuid: State.selectedSiteUuid || '',
      name: document.getElementById('facility-name').value || 'New Facility',
      preset: document.getElementById('facility-preset').value,
      structure: (document.querySelector('input[name="structure"]:checked') || {}).value || 'single',
      bay_count: parseInt(document.getElementById('bay-count').value, 10) || 1,
      outer_geometry: State.outerGeometry,
      geometry_3d: {
        span_width_m: parseFloat(document.getElementById('span-width').value) || 7,
        eave_height_m: parseFloat(document.getElementById('eave-height').value) || 2,
        ridge_height_m: parseFloat(document.getElementById('ridge-height').value) || 4,
        length_m: parseFloat(document.getElementById('length-m').value) || 30,
        orientation_deg: State.orientationDeg || 0,
        roof_type: (document.getElementById('roof-type') || {}).value || 'arch',
        spacing_m: parseFloat((document.getElementById('spacing-m') || {}).value) || 0,
        center_lng: State.center ? State.center[0] : null,
        center_lat: State.center ? State.center[1] : null,
      },
      envelope:  window.EnvelopeUI  ? EnvelopeUI.read()  : {},
      actuators: window.ActuatorUI  ? ActuatorUI.read()  : [],
      fittings:  window.FittingsUI  ? FittingsUI.read()  : [],
      view_options: {
        category_visibility: (window.FittingsUI && FittingsUI.getCategoryVisibility)
          ? FittingsUI.getCategoryVisibility() : {},
        // Sensor label color bands (5-step upper bounds per measurement item) — widgets read this to color labels
        sensor_ranges: (window.SensorRangesUI && SensorRangesUI.read)
          ? SensorRangesUI.read() : undefined,
      },
      weather_bindings: window.WeatherUI ? WeatherUI.read() : [],
      groups:           window.GroupUI   ? GroupUI.read()   : {},
      // 구역(zone) 정의 — bay 범위 병합/분할 (ZoneUI). bay 1개면 [].
      bays:             window.ZoneUI    ? ZoneUI.read()    : [],
    };
    return data;
  }

  function fillForm(f) {
    State.facilityUuid = f.unique_id;
    State.outerGeometry = (f.outer_feature && f.outer_feature.geometry) || null;
    setOuterGeometry(State.outerGeometry);

    document.getElementById('facility-name').value = f.name || '';
    document.getElementById('facility-preset').value = f.preset || 'standard_arch';
    _syncPicker(document.getElementById('facility-preset'));
    document.querySelectorAll('input[name="structure"]').forEach((r) => {
      r.checked = (r.value === f.structure);
    });
    document.getElementById('bay-count').value = f.bay_count || 1;
    if (window.ZoneUI) ZoneUI.load(f.bays || [], f.bay_count || 1);
    if (f.geo_id) {
      document.getElementById('map-selector').value = f.geo_id;
      _syncPicker(document.getElementById('map-selector'));
      // Reload sites for this map so the site-selector can be restored below
      loadSites(f.geo_id).then(() => {
        if (f.parent_site_uuid) {
          const sel = document.getElementById('site-selector');
          if (sel) {
            sel.value = f.parent_site_uuid;
            State.selectedSiteUuid = f.parent_site_uuid;
            _syncPicker(sel);
          }
        }
      });
      // facility-prod also needs to refresh for the loaded map
      loadSavedFacilities(f.geo_id);
    }

    if (f.geometry_3d) {
      document.getElementById('span-width').value = f.geometry_3d.span_width_m || 7;
      document.getElementById('eave-height').value = f.geometry_3d.eave_height_m || 2;
      document.getElementById('ridge-height').value = f.geometry_3d.ridge_height_m || 4;
      document.getElementById('length-m').value = f.geometry_3d.length_m || 30;
      const roofSel = document.getElementById('roof-type');
      if (roofSel) { roofSel.value = f.geometry_3d.roof_type || 'arch'; _syncPicker(roofSel); }
      const spacingEl = document.getElementById('spacing-m');
      if (spacingEl) spacingEl.value = (f.geometry_3d.spacing_m != null ? f.geometry_3d.spacing_m : 1.0);
      State.orientationDeg = f.geometry_3d.orientation_deg || 0;
      const slider = document.getElementById('orientation-slider');
      const orientInput = document.getElementById('orientation-input');
      const orientValue = document.getElementById('orientation-value');
      if (slider) slider.value = State.orientationDeg;
      if (orientInput) orientInput.value = State.orientationDeg;
      if (orientValue) orientValue.textContent = State.orientationDeg;
    }
    // Restore the exact saved center. Prefer the persisted geometry_3d.center_*
    // (authoritative, no round-trip drift); fall back to the polygon centroid
    // only for legacy records saved before center was persisted.
    const savedLng = f.geometry_3d ? f.geometry_3d.center_lng : null;
    const savedLat = f.geometry_3d ? f.geometry_3d.center_lat : null;
    if (savedLng != null && savedLat != null) {
      State.center = [savedLng, savedLat];
    } else if (State.outerGeometry) {
      State.center = polygonCentroid(State.outerGeometry);
    }
    if (f.envelope && window.EnvelopeUI) {
      EnvelopeUI.fill(f.envelope);
    }
    if (f.actuators && window.ActuatorUI) {
      ActuatorUI.fill(f.actuators);
    }
    if (window.FittingsUI) {
      FittingsUI.fill(f.fittings || []);
      // Apply saved view_options.category_visibility (use localStorage only if absent)
      if (FittingsUI.loadCategoryVisibility) {
        var vo = (f.view_options && f.view_options.category_visibility) || null;
        FittingsUI.loadCategoryVisibility(vo, f.unique_id);
      }
      _renderFittingsAggregate();
    }
    if (window.WeatherUI) WeatherUI.fill(f.weather_bindings || []);
    if (window.GroupUI)   GroupUI.fill(f.groups || {});
    if (window.SensorRangesUI) {
      SensorRangesUI.fill((f.view_options && f.view_options.sensor_ranges) || null);
    }
    if (f.computed) updatePreview(f.computed);

    handleStructureChange();

    // Re-emit the SAVED polygon with height_m/eave_h in properties so the 3D
    // extrusion layer picks up the correct ridge height. We intentionally do NOT
    // call rebuildOuterGeometry() here: regenerating the polygon from center
    // round-trips the coordinates and accumulates drift across edit/save cycles.
    // Preserving the stored outerGeometry keeps placement fixed.
    if (State.outerGeometry) {
      const ridgeH = parseFloat(document.getElementById('ridge-height').value) || 4;
      const eaveH  = parseFloat(document.getElementById('eave-height').value) || 2;
      setOuterGeometry(State.outerGeometry, { height_m: ridgeH, eave_h: eaveH, base_m: 0 });
    }

    // Recenter map on outer polygon (cap zoom at 18 to avoid OSM/CARTO 404 at z=20)
    // Supports both Polygon and MultiPolygon (Phase C: single + bays > 1).
    if (State.outerGeometry && State.map) {
      const bounds = geometryBounds(State.outerGeometry);
      if (bounds) {
        const doFit = (label) => {
          try {
            State.map.fitBounds(bounds, { padding: 60, duration: 0, maxZoom: 18 });
          } catch (e) {}
        };
        // Immediate (works if style/style-data is already loaded)
        doFit('immediate');
        // Safety net: fire on first idle in case the immediate call lost a race
        // with style loading or pending source data.
        try { State.map.once('idle', () => doFit('idle')); } catch (e) {}
      } else {
        console.warn('[facility v3] empty bounds for geometry', State.outerGeometry);
      }
    } else {
      console.warn('[facility v3] fillForm: no outerGeometry or map',
                   { hasGeom: !!State.outerGeometry, hasMap: !!State.map });
    }

    // Notify 3D preview to rebuild with the newly loaded facility data.
    // The uuid tells listeners whether this is a saved facility or the blank
    // form started by "New Facility" — the step ring rules differ.
    document.dispatchEvent(new CustomEvent('facility-loaded', {
      detail: { facility_uuid: f.unique_id || null }
    }));
  }

  // =========================================================
  // Compute (debounced)
  // =========================================================
  let computeTimer = null;
  function debouncedCompute() {
    clearTimeout(computeTimer);
    computeTimer = setTimeout(doCompute, 500);
  }

  async function doCompute() {
    const data = readForm();
    if (!data.outer_geometry) return;
    try {
      const res = await fetch('/api/geo/facility/compute', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (res.status === 501) {
        // P4 facility_calc not yet available — leave preview as is
        return;
      }
      const json = await res.json();
      if (json.ok) updatePreview(json.computed);
    } catch (e) {
      console.warn('[facility] compute failed:', e);
    }
  }

  function updatePreview(c) {
    if (!c) return;
    const set = (id, val, unit) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (val == null) { el.textContent = '— ' + unit; return; }
      el.textContent = (typeof val === 'number' ? val.toFixed(1) : val) + ' ' + unit;
    };
    set('pv-floor', c.floor_m2, 'm²');
    set('pv-volume', c.volume_m3, 'm³');
    set('pv-glazing', c.glazing_m2, 'm²');
    set('pv-vent', c.vent_open_m2, 'm²');
    // Heating: prefer nameplate (kW from actuators) if present, else theoretical load
    const heatingVal = (c.nameplate_heating_kw > 0) ? c.nameplate_heating_kw : c.heating_kw;
    const heatingEl = document.getElementById('pv-heating');
    if (heatingEl) {
      const ratio = c.heating_kw > 0 ? (heatingVal / c.heating_kw) : null;
      heatingEl.textContent = (heatingVal != null ? heatingVal.toFixed(1) : '—') + ' kW';
      heatingEl.title = c.nameplate_heating_kw > 0
        ? _T('nameplate','Nameplate')+': ' + c.nameplate_heating_kw.toFixed(1) + ' kW  /  '+_T('calc_label','calc')+': ' + c.heating_kw.toFixed(1) + ' kW' +
          (ratio != null ? ' (' + Math.round(ratio * 100) + '%)' : '')
        : _T('hint_heater','Theoretical value. Shows nameplate when heater capacity is set on actuator.');
    }
    const coolingVal = (c.nameplate_cooling_kw > 0) ? c.nameplate_cooling_kw : c.cooling_kw;
    const coolingEl = document.getElementById('pv-cooling');
    if (coolingEl) {
      coolingEl.textContent = (coolingVal != null ? coolingVal.toFixed(1) : '—') + ' kW';
      coolingEl.title = c.nameplate_cooling_kw > 0
        ? _T('nameplate','Nameplate')+': ' + c.nameplate_cooling_kw.toFixed(1) + ' kW  /  '+_T('calc_label','calc')+': ' + c.cooling_kw.toFixed(1) + ' kW'
        : _T('hint_cooler','Theoretical value. Shows nameplate when cooler capacity is set on actuator.');
    }
    if (c.ach_total != null) {
      set('pv-ach', c.ach_total, '/h');
    } else if (c.ach_m3h != null && c.volume_m3) {
      set('pv-ach', c.ach_m3h / c.volume_m3, '/h');
    }

    // Render fittings/actuator summary panel if present
    const sumEl = document.getElementById('pv-summary');
    if (sumEl) {
      const lines = [];
      if (c.fittings_count > 0) {
        var KMAP = { window:_T('m_window','Window'), door:_T('m_door','Door'), side_window:_T('m_side_window','Side Window'),
          curtain:_T('m_curtain','Curtain'), shade_curtain:_T('m_shade','Shade'), fan:_T('m_fan','Fan'),
          heater:_T('m_heater','Heater'), sensor:_T('m_sensor','Sensor'), fixture:_T('m_fixture','Fixture'),
          irrigation_layer:_T('m_irr_layer','Irrigation Layer'), irrigation_pipe:_T('m_irr_pipe','Pipe'),
          irrigation_connection:_T('m_irr_conn','Pipe Connection'), irrigation_device:_T('m_irr_device','Irrigation Device'),
          irrigation_valve:_T('m_irr_valve','Irrigation Valve') };
        const parts = Object.entries(c.fittings_by_kind || {}).map(([k, v]) => (KMAP[k] || k) + ' ' + v);
        lines.push(_T('installed','Installed') + ': ' + c.fittings_count + ' · ' + parts.join(', ') + ' · ' + c.fittings_total_area_m2 + 'm²');
      }
      if (c.actuator_counts && Object.keys(c.actuator_counts).length > 0) {
        var aLabels = { side_window_motor:_T('am_side_window_motor','Side window motor'), roof_vent_motor:_T('am_roof_vent_motor','Roof vent motor'),
                          thermal_curtain_motor:_T('am_thermal_curtain_motor','Thermal curtain motor'),
                          exhaust_fan:_T('am_exhaust_fan','Exhaust fan'), circulation_fan:_T('am_circ_fan','Circulation fan'),
                          heater:_T('m_heater','Heater'), cooler:_T('am_cooler','Cooler'),
                          heat_pump:_T('am_heat_pump','Heat pump'), irrigation_valve:_T('am_irr_valve','Irrigation valve') };
        const aParts = Object.entries(c.actuator_counts).map(([k, v]) => (aLabels[k] || k) + ' ' + v);
        lines.push(_T('actuators_word','Actuators') + ': ' + aParts.join(', '));
      }
      sumEl.innerHTML = lines.length ? lines.join('<br>') : '';
    }
  }

  // =========================================================
  // Save / Load
  // =========================================================
  async function saveFacility() {
    const data = readForm();
    if (!data.geo_id) { alert('Please select a map first.'); return; }
    if (!data.outer_geometry) { alert('Use "Place on Map" to set the facility location first.'); return; }

    try {
      const res = await fetch('/api/geo/facility', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      const json = await res.json();
      if (json.ok) {
        State.facilityUuid = json.facility_uuid;
        showToast('Saved.');
        // Saving used to reload the page, which closed the step drawer and threw
        // away the step the user was on. Everything the reload was for is done
        // here instead: the URL, the page vars the delete path reads, the saved
        // list, and the integration panel.
        _syncFacilityRef(json.facility_uuid);
        _upsertFacilityListItem(json.facility_uuid, data);
        loadIntegration(json.facility_uuid);
        document.dispatchEvent(new CustomEvent('facility-saved', {
          detail: { facility_uuid: json.facility_uuid }
        }));
        if (window.FacilityStep && FacilityStep.refreshCheckLock) FacilityStep.refreshCheckLock();
      } else {
        alert('Save failed: ' + (json.message || 'unknown error'));
      }
    } catch (e) {
      alert('Save error: ' + e.message);
    }
  }

  // Keep every place that remembers "which facility is open" in step, without
  // navigating: the address bar (so reload/bookmark still work), the page-vars
  // blob the 3D bridge reads, and the highlight in the saved list.
  // The page's own catalog function; the modules extracted from this file all
  // reach for window._ the same way.
  function _tr(s) { return window._ ? window._(s) : s; }

  function _syncFacilityRef(uuid) {
    try {
      const url = new URL(window.location.href);
      if (uuid) url.searchParams.set('facility_uuid', uuid);
      else url.searchParams.delete('facility_uuid');
      window.history.replaceState({}, '', url.toString());
    } catch (e) { /* history unavailable — the rest still applies */ }

    const varsEl = document.getElementById('facility-page-vars');
    if (varsEl) {
      try {
        const pv = JSON.parse(varsEl.textContent || '{}');
        pv.facility_uuid = uuid || null;
        varsEl.textContent = JSON.stringify(pv);
      } catch (e) { /* leave it alone rather than write garbage */ }
    }

    document.querySelectorAll('.facility-list-item').forEach((el) => {
      el.classList.toggle('active', !!uuid && el.dataset.uuid === uuid);
    });
  }

  // After a save, the list must show the new name — and a brand-new facility
  // must appear in it at all, since there is no reload to rebuild it.
  function _upsertFacilityListItem(uuid, data) {
    const list = document.getElementById('facility-list');
    if (!list) return;
    const sub = (data.preset || '') + ' · ' + (data.structure || '') +
                (data.structure === 'connected' ? ' (N=' + (data.bay_count || 1) + ')' : '');
    let item = list.querySelector('.facility-list-item[data-uuid="' + uuid + '"]');
    if (!item) {
      const empty = list.querySelector('.text-muted');
      if (empty && !list.querySelector('.facility-list-item')) empty.remove();
      item = document.createElement('div');
      item.className = 'facility-list-item';
      item.dataset.uuid = uuid;
      item.innerHTML =
        '<div class="fac-item-info"><div class="fac-item-name"></div>' +
        '<small class="text-muted fac-item-sub"></small></div>' +
        '<button class="btn aot-pill-btn aot-pill-btn-primary fac-item-del" data-uuid="' + uuid + '"></button>';
      // Same behaviour the template gives its own rows.
      item.setAttribute('onclick', 'FacilityIO.select(this.dataset.uuid)');
      const del = item.querySelector('.fac-item-del');
      del.textContent = _tr('Delete');
      del.title = _tr('Delete facility');
      del.setAttribute('onclick',
        'event.stopPropagation(); facilityDelete(this.dataset.uuid, this.dataset.name)');
      list.appendChild(item);
    }
    item.querySelector('.fac-item-name').textContent = data.name || '';
    item.querySelector('.fac-item-sub').textContent = sub;
    const del = item.querySelector('.fac-item-del');
    if (del) del.dataset.name = data.name || '';
    // The highlight is applied by uuid, so it has to run once the row exists.
    _syncFacilityRef(uuid);
  }

  // Open a saved facility without leaving the page. fillForm() is the same
  // routine the initial ?facility_uuid= load uses, so switching in place goes
  // through exactly one code path.
  async function selectFacility(uuid) {
    if (!uuid || uuid === State.facilityUuid) return;
    await loadFacility(uuid);
    loadIntegration(uuid);
    _syncFacilityRef(uuid);
  }

  // Start a blank facility in place. Every section is passed an explicit empty
  // value — envelope and actuators are only filled when present, so omitting
  // them would silently carry the previous facility's settings into the new one.
  function newFacility() {
    fillForm({
      unique_id: null,
      name: '',
      preset: 'standard_arch',
      structure: 'single',
      bay_count: 1,
      bays: [],
      outer_feature: null,
      geometry_3d: {},
      envelope: {},
      actuators: {},
      fittings: [],
      weather_bindings: [],
      groups: {}
    });
    State.facilityUuid = null;
    _syncFacilityRef(null);
    const panel = document.getElementById('integ-panel');
    if (panel) panel.style.display = 'none';
    if (window.FacilityStep) FacilityStep.set('basic');
  }

  async function loadFacility(uuid) {
    try {
      const res = await fetch('/api/geo/facility/' + uuid, { credentials: 'same-origin' });
      const json = await res.json();
      if (json.ok && json.facility) fillForm(json.facility);
    } catch (e) {
      console.warn('[facility] loadFacility failed:', e);
    }
  }

  // =========================================================
  // Event handlers
  // =========================================================
  function bindEventHandlers() {
    // structure radio: toggle bay-count input + rebuild rect (W = span × bays)
    document.querySelectorAll('input[name="structure"]').forEach((r) => {
      r.addEventListener('change', () => {
        handleStructureChange();
        rebuildOuterGeometry();
        debouncedCompute();
      });
    });
    // EnvelopeUI / ActuatorUI / FittingsUI fire custom events → trigger compute
    document.addEventListener('envelope-changed',       debouncedCompute);
    document.addEventListener('envelope-data-changed',  debouncedCompute); // compute only, no 3D rebuild
    document.addEventListener('actuator-changed',       debouncedCompute);
    document.addEventListener('fittings-changed',       debouncedCompute);
    // Aggregate panel was retired with the legacy Fittings form section.
    // (FittingsUI.aggregate() is still public for compute summary use.)

    // Bridge so the 3D tool palette's catalog button can resolve State.center.
    // wireTools() in geo_facility.html passes facCenter=null; intercept here
    // and inject State.center if available.
    document.addEventListener('aot-facility-need-center', function (e) {
      if (e.detail && typeof e.detail.cb === 'function') {
        e.detail.cb(State.center || null, State.orientationDeg || 0);
      }
    });

    // Roof vent toggle (not managed by EnvelopeUI's _notify, wire directly)
    const roofVentEl = document.getElementById('outer-roof-vent');
    if (roofVentEl) roofVentEl.addEventListener('change', debouncedCompute);
    const shadeEl = document.getElementById('curtain-shade');
    if (shadeEl) shadeEl.addEventListener('change', debouncedCompute);

    // Fields that change footprint dimensions OR 3D height → rebuild + recompute
    // (heights propagate to the fill-extrusion layer via properties)
    const dimensionFields = [
      'span-width', 'length-m', 'bay-count', 'spacing-m',
      'eave-height', 'ridge-height'
    ];
    dimensionFields.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('input', () => {
        rebuildOuterGeometry();
        debouncedCompute();
      });
    });

    // Roof type — affects compute (and dashboard mimic) but not footprint
    const roofSel = document.getElementById('roof-type');
    if (roofSel) roofSel.addEventListener('change', debouncedCompute);

    // Orientation slider + numeric input — bidirectional sync
    const slider = document.getElementById('orientation-slider');
    const orientInput = document.getElementById('orientation-input');
    const orientValue = document.getElementById('orientation-value');
    function setOrientation(deg, syncSlider, syncInput) {
      const d = ((parseFloat(deg) || 0) % 360 + 360) % 360;
      State.orientationDeg = d;
      if (syncSlider && slider) slider.value = d;
      if (syncInput && orientInput) orientInput.value = d;
      if (orientValue) orientValue.textContent = Math.round(d);
      rebuildOuterGeometry();
      debouncedCompute();
    }
    if (slider) slider.addEventListener('input', (e) => setOrientation(e.target.value, false, true));
    if (orientInput) orientInput.addEventListener('change', (e) => setOrientation(e.target.value, true, false));

    // Place-on-map button (replaces old draw-polygon flow)
    const placeBtn = document.getElementById('btn-place-on-map');
    if (placeBtn) placeBtn.addEventListener('click', startPlaceMode);
    document.getElementById('btn-clear-shape').addEventListener('click', () => {
      setOuterGeometry(null);
      State.center = null;
      finishPlaceMode();
    });
    document.getElementById('btn-save-facility').addEventListener('click', saveFacility);

    // 구역 편집기: 경계 토글/이름 입력/bay-count 연동 + 신규 시설 기본값
    if (window.ZoneUI) { ZoneUI.bind(); ZoneUI.load(null); }

    const integRefreshBtn = document.getElementById('btn-integ-refresh');
    if (integRefreshBtn) {
      integRefreshBtn.addEventListener('click', () => loadIntegration(State.facilityUuid));
    }
  }

  function _renderFittingsAggregate() {
    const el = document.getElementById('fittings-aggregate');
    if (!el || !window.FittingsUI) return;
    const agg = FittingsUI.aggregate();
    if (agg.total === 0) { el.innerHTML = ''; return; }
    const KIND_LABELS = {
      window:_T('m_window','Window'), door:_T('m_door','Door'), curtain:_T('m_curtain','Curtain'),
      fan:_T('m_fan','Fan'), heater:_T('m_heater','Heater'), sensor:_T('m_sensor','Sensor'), fixture:_T('m_fixture','Fixture')
    };
    const parts = Object.entries(agg.by_kind).map(([k, v]) =>
      (KIND_LABELS[k] || k) + ' ' + v.count + ' (' + '㎡)');
    el.innerHTML =
      '<b>'+_T('total_word','Total')+' ' + agg.total + ' '+_T('items_word','items')+'</b> · ' + parts.join(' · ') +
      ' · '+_T('total_area','total area')+' ' + agg.total_area_m2.toFixed(1) + '㎡';
  }

  function handleStructureChange() {
    const sel = document.querySelector('input[name="structure"]:checked');
    const v = sel ? sel.value : 'single';
    // Bays count is meaningful for both single (detached row) and connected
    const bayBox = document.getElementById('bay-count-container');
    if (bayBox) bayBox.classList.remove('d-none');
    // Spacing only applies to detached single-bay rows (connected bays share walls)
    const spacingBox = document.getElementById('spacing-container');
    if (spacingBox) spacingBox.classList.toggle('d-none', v !== 'single');
  }

  // =========================================================
  // 3D overlay helpers (AoTFacilityMap3D integration)
  // =========================================================
  function _readFacilitySpec() {
    return {
      unique_id: State.facilityUuid || 'preview',
      preset:    document.getElementById('facility-preset').value || 'standard_arch',
      structure: (document.querySelector('input[name="structure"]:checked') || {}).value || 'single',
      bay_count: Math.max(parseInt(document.getElementById('bay-count').value, 10) || 1, 1),
      geometry_3d: {
        span_width_m:    parseFloat(document.getElementById('span-width').value)  || 7,
        eave_height_m:   parseFloat(document.getElementById('eave-height').value) || 2,
        ridge_height_m:  parseFloat(document.getElementById('ridge-height').value) || 4,
        length_m:        parseFloat(document.getElementById('length-m').value)    || 30,
        orientation_deg: State.orientationDeg || 0,
        roof_type:       (document.getElementById('roof-type') || {}).value || 'arch',
        spacing_m:       parseFloat((document.getElementById('spacing-m') || {}).value) || 0,
      },
      envelope: window.EnvelopeUI ? EnvelopeUI.read() : {},
    };
  }

  function _update3DPreview() {
    if (!window.AoTFacilityMap3D) return;
    if (!State.outerGeometry || !State.center) {
      AoTFacilityMap3D.clearPreview();
      return;
    }
    AoTFacilityMap3D.setPreview(_readFacilitySpec(), State.center);
  }

  function _load3DProdFacilities(facilities) {
    if (!window.AoTFacilityMap3D) return;
    AoTFacilityMap3D.loadProd(facilities || []);
  }

  // =========================================================
  // C1: IEC integrated summary panel
  // =========================================================
  var _INTEG_KIND_LABELS = {
    opening:_T('k_opening','Opening'), circulation_fan:_T('k_circ_fan','Circulation fan'), exhaust_fan:_T('k_exhaust_fan','Exhaust fan'),
    heater:_T('k_heater','Heater'), cooler:_T('k_cooler','Cooler'), fogger:_T('k_fogger','Humidifier'), co2_injector:'CO₂',
    shade:_T('k_shade','Shade'), curtain:_T('k_curtain','Curtain'), lighting:_T('k_lighting','Lighting'),
  };
  const _INTEG_FACE_LABELS = {
    x_neg:'X−', x_pos:'X+', y_pos:'Y+', y_neg:'Y−', roof:_T('f_roof','Roof'), floor:_T('f_floor','Floor'),
    // Legacy compass aliases
    south:'Y+', north:'Y−', east:'X+', west:'X−',
  };

  function _integFmt(v, d) {
    return (v != null && !isNaN(v)) ? Number(v).toFixed(d) : '—';
  }
  function _integEsc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function _renderIntegration(d) {
    const cm = d.capacity_meta || {};
    var _src = String(cm.vent_open_source || '');
    const srcCls = _src.indexOf('fitting') >= 0 ? ' aot-tag-ok' : (_src.indexOf('envelope') >= 0 ? ' aot-tag-warn' : '');
    const srcLbl = _src ? _src : _T('none','None');

    // ── capacity meta strip ──
    let html = '<div class="integ-meta-strip">';
    html += '<span>'+_T('volume','Volume')+' <b>' + _integFmt(cm.volume_m3, 1) + ' m³</b></span>';
    html += '<span>'+_T('envelope','Envelope')+' <b>' + _integFmt(cm.envelope_m2, 1) + ' m²</b></span>';
    html += '<span>'+_T('u_eff','U-effective')+' <b>' + _integFmt(cm.u_effective, 3) + '</b></span>';
    html += '<span>'+_T('vent_area','Vent area')+' <b>' + _integFmt(cm.vent_open_m2, 2) + ' m²</b>'
          + ' <span class="aot-tag' + srcCls + '">' + _integEsc(srcLbl) + '</span></span>';
    html += '</div>';

    // ── actuators_resolved ──
    const acts = d.actuators_resolved || [];
    if (acts.length) {
      html += '<div class="integ-section-label">'+_T('sec_actuators','Actuator links')+' (' + acts.length + ')</div>';
      html += '<table class="aot-module-table integ-table"><thead><tr>'
            + '<th>Output</th><th>Kind</th><th>Slot</th><th>Vent m²</th><th>Fitting</th>'
            + '</tr></thead><tbody>';
      acts.forEach(a => {
        const kindLbl = _INTEG_KIND_LABELS[a.kind] || (a.kind || '—');
        const ventStr = a.vent_openings_area_m2 > 0 ? a.vent_openings_area_m2.toFixed(2) : '—';
        const fitCnt  = (a.fitting_ids || []).length || '—';
        html += '<tr>'
              + '<td>' + _integEsc(a.output_name || a.output_uuid) + '</td>'
              + '<td>' + _integEsc(kindLbl) + '</td>'
              + '<td class="integ-slot">' + _integEsc(a.slot_key || '—') + '</td>'
              + '<td>' + ventStr + '</td>'
              + '<td>' + fitCnt + '</td>'
              + '</tr>';
      });
      html += '</tbody></table>';
    }

    // ── vent_openings pills ──
    const vos = d.vent_openings || [];
    if (vos.length) {
      html += '<div class="integ-section-label">'+_T('sec_openings','Openings')+' (' + vos.length + ')</div>';
      html += '<div class="aot-tag-list">';
      vos.forEach(v => {
        const face = _INTEG_FACE_LABELS[v.face] || (v.face || '?');
        html += '<span class="aot-tag">' + _integEsc(face) + ' ' + (v.area_m2 || 0).toFixed(2) + ' m²</span>';
      });
      html += '</div>';
    }

    // ── sensors_resolved ──
    const sensors = d.sensors_resolved || [];
    if (sensors.length) {
      html += '<div class="integ-section-label">'+_T('sec_sensors','Sensor links')+' (' + sensors.length + ')</div>';
      html += '<table class="aot-module-table integ-table"><thead><tr><th>'+_T('th_sensor','Sensor')+'</th><th>Input</th></tr></thead><tbody>';
      sensors.forEach(s => {
        const inputLbl = s.input_name || (s.input_uuid ? s.input_uuid.slice(0, 8) + '…' : '—');
        html += '<tr><td>' + _integEsc(s.name || s.fitting_id) + '</td><td>' + _integEsc(inputLbl) + '</td></tr>';
      });
      html += '</tbody></table>';
    }

    // ── irrigation_summary (irrigation system flow aggregation) ──
    const irr = d.irrigation_summary || {};
    const irrLayers = irr.layers || [];
    if (irrLayers.length) {
      html += '<div class="integ-section-label">'+_T('sec_irrigation','Irrigation system')+' (' + irrLayers.length + ' '+_T('layer_word','layer')+')</div>';
      irrLayers.forEach(function (L) {
        const t = L.totals || {};
        const hStr = L.height_m != null ? (' · '+_T('height','height')+' ' + Number(L.height_m).toFixed(1) + 'm') : '';
        html += '<div style="font-size:var(--aot-font-size-sm);font-weight:600;margin:4px 0 2px;color:var(--aot-color-brand-primary);">'
              + _integEsc(L.name || _T('irr_layer','Irrigation layer')) + hStr
              + ' <span style="color:var(--aot-color-text-secondary);font-weight:400;">('+_T('pipe_word','pipes')+' ' + (L.pipe_count||0)
              + ' · '+_T('nozzle_word','nozzles')+' ' + (L.device_count||0) + ')</span></div>';
        if ((L.pipes || []).length) {
          html += '<table class="aot-module-table integ-table"><thead><tr>'
                + '<th>No.</th><th>'+_T('th_pipe','Pipe')+'</th><th>'+_T('th_length_m','Length (m)')+'</th><th>'+_T('th_nozzle','Nozzles')+'</th><th>'+_T('th_flow_lph','Flow (L/h)')+'</th><th>'+_T('th_flow_lpm','Flow (L/min)')+'</th>'
                + '</tr></thead><tbody>';
          L.pipes.forEach(function (p) {
            html += '<tr>'
                  + '<td>' + p.no + '</td>'
                  + '<td>' + _integEsc(p.name) + '</td>'
                  + '<td>' + _integFmt(p.length_m, 2) + '</td>'
                  + '<td>' + (p.emitters || 0) + '</td>'
                  + '<td>' + _integFmt(p.flow_lph, 1) + '</td>'
                  + '<td>' + _integFmt(p.flow_lpm, 2) + '</td>'
                  + '</tr>';
          });
          html += '<tr style="background:var(--aot-color-brand-accent);font-weight:600;">'
                + '<td colspan="2">'+_T('subtotal','Subtotal')+'</td>'
                + '<td>' + _integFmt(t.length_m, 2) + '</td>'
                + '<td>' + (t.emitters || 0) + '</td>'
                + '<td>' + _integFmt(t.flow_lph, 1) + '</td>'
                + '<td>' + _integFmt(t.flow_lpm, 2) + '</td>'
                + '</tr>';
          html += '</tbody></table>';
        }
      });
      const gt = irr.totals || {};
      html += '<div class="integ-meta-strip" style="margin-top:8px;">'
            + '<span>'+_T('tot_length','Total pipe length')+' <b>' + _integFmt(gt.length_m, 1) + ' m</b></span>'
            + '<span>'+_T('tot_nozzle','Total nozzles')+' <b>' + (gt.emitters || 0) + '</b></span>'
            + '<span>'+_T('tot_flow','Total flow')+' <b>' + _integFmt(gt.flow_lph, 0) + ' L/h</b></span>'
            + '<span>'+_T('per_min','Per minute')+' <b>' + _integFmt(gt.flow_lpm, 1) + ' L/min</b></span>'
            + '</div>';
    }

    if (!acts.length && !vos.length && !sensors.length && !irrLayers.length) {
      html += '<div class="integ-empty">'+_T('empty','No linked actuators/sensors. Place fittings and save to reflect them.')+'</div>';
    }

    html += '<div class="integ-note">'+_T('note','IEC integration data is reflected after saving.')+'</div>';
    return html;
  }

  async function loadIntegration(uuid) {
    if (!uuid) return;
    const panel = document.getElementById('integ-panel');
    const body  = document.getElementById('integ-body');
    if (!panel || !body) return;
    panel.style.display = '';
    body.innerHTML = '<span class="integ-loading">'+_T('integ_loading','Loading integration data…')+'</span>';
    try {
      const res  = await fetch('/api/geo/facility/' + uuid + '/integration', { credentials: 'same-origin' });
      const json = await res.json();
      body.innerHTML = json.ok ? _renderIntegration(json) : '<span class="integ-error">'+_T('load_fail','Load failed: ') + _integEsc(json.message || '') + '</span>';
    } catch (e) {
      body.innerHTML = '<span class="integ-error">'+_T('integ_error','Error: ') + _integEsc(e.message) + '</span>';
    }
  }

  function showToast(msg) {
    const t = document.createElement('div');
    t.textContent = msg;
    t.style.cssText =
      'position:fixed;bottom:30px;right:30px;background:var(--aot-color-brand-primary);color:var(--aot-color-text-tertiary);' +
      'padding:.6rem 1.2rem;border-radius:6px;z-index:var(--aot-z-toast);' +
      'font-size:var(--aot-font-size-base);box-shadow:var(--aot-shadow-md);';
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2500);
  }
})();
