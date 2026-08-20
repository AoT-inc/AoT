// sensor-ranges-ui.js — extracted from templates/pages/geo/geo_facility.html (2026-07-31).
// SensorRangesUI — sensor label colour ranges.
// Loaded as part of the geo-facility bundle, after aot-facility-design.js,
// so FittingsUI/EnvelopeUI and the _IEC/_COMM string catalogs already exist.

/* ── SensorRangesUI — label color range settings (independent of sensor devices) ──
   Edits facility.view_options.sensor_ranges.
   A representative setting defined once per facility by measurement "item", not per individual sensor/channel.
   Format: { <matchKey>: { label, unit, stages:[5-stage upper limits], colors:[5 colors] } }
   - The user can directly change each stage color and upper limit.
   - Measurement items (match keys) can be added/removed as desired.
   Sensor labels in the widgets (AoT_facility border / AoT_map background) reference stages/colors
   automatically according to each channel measurement type (key).
   The default color palette is kept identical to the widget BAND_PALETTE.
──────────────────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  // Global palette for the 5-stage measurement ranges: reads --aot-band-1..5 CSS
  // tokens (settings/custom_ui band_1..5 로 사용자 정의 가능) with literal fallbacks.
  // cold (low) → optimal → hot (high)
  var PALETTE = (function () {
    var defaults = ['#2DB4FF', '#54BCC1', '#32c85a', '#FEAE5F', '#CF5C58'];
    try {
      var cs = getComputedStyle(document.documentElement);
      return defaults.map(function (c, i) {
        var v = cs.getPropertyValue('--aot-band-' + (i + 1)).trim();
        return v || c;
      });
    } catch (e) { return defaults; }
  })();

  // Items with reversed meaning (e.g. humidity) use the reversed palette
  var REVERSE_KEYS = { RH: true };
  function _paletteFor(key) {
    return REVERSE_KEYS[key] ? PALETTE.slice().reverse() : PALETTE.slice();
  }

  // Known measurement item catalog (key = sensor channel measurement-type identifier)
  var CATALOG = [
    { key: 'T',        label: (window._ ? window._('Temperature') : 'Temperature'), unit: '°C',   stages: [10, 18, 26, 34, 45] },
    { key: 'RH',       label: (window._ ? window._('Humidity') : 'Humidity'), unit: '%',    stages: [40, 55, 70, 85, 100] },
    { key: 'VPD',      label: 'VPD',  unit: 'kPa',  stages: [0.4, 0.8, 1.2, 1.6, 3.0] },
    { key: 'light',    label: (window._ ? window._('Solar') : 'Solar'), unit: 'W/m²', stages: [200, 400, 600, 800, 1200] },
    { key: 'wind_ms',  label: (window._ ? window._('Wind speed') : 'Wind speed'), unit: 'm/s',  stages: [2, 4, 6, 9, 15] },
    { key: 'CO2',      label: 'CO2',  unit: 'ppm',  stages: [400, 600, 800, 1000, 1500] },
    { key: 'wind_deg', label: (window._ ? window._('Wind direction') : 'Wind direction'), unit: '°',    stages: [72, 144, 216, 288, 360] },
    { key: 'rain_mm',  label: (window._ ? window._('Precipitation') : 'Precipitation'), unit: 'mm',   stages: [1, 5, 10, 20, 50] },
  ];

  // Initially active items (same as existing behavior)
  var DEFAULT_KEYS = ['T', 'RH', 'VPD', 'light', 'wind_ms'];

  var _entries = [];  // [{ key, label, unit, stages:[5], colors:[5] }] — order preserved

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                           .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  function _clone(o) { return JSON.parse(JSON.stringify(o)); }
  function _catalog(key) { return CATALOG.filter(function (c) { return c.key === key; })[0] || null; }

  function _defaultEntry(key, label, unit, stages) {
    var c = _catalog(key);
    return {
      key:    key,
      label:  label || (c && c.label) || key,
      unit:   unit  != null ? unit : (c ? c.unit : ''),
      stages: (stages || (c && c.stages) || [0, 0, 0, 0, 0]).slice(0, 5),
      colors: _paletteFor(key),
    };
  }

  /* Inject from outside (FacilityUI.fill()). null/empty → build default items.
     Also handles the legacy format ({key:[5 numbers]}) for compatibility. */
  function fill(obj) {
    _entries = [];
    if (obj && typeof obj === 'object' && Object.keys(obj).length) {
      Object.keys(obj).forEach(function (key) {
        var v = obj[key];
        if (Array.isArray(v)) {
          // Legacy: only the upper-limit array stored, without colors
          _entries.push(_defaultEntry(key, null, null, v.map(Number)));
        } else if (v && Array.isArray(v.stages)) {
          var colors = (Array.isArray(v.colors) && v.colors.length === 5)
            ? v.colors.slice() : PALETTE.slice();
          _entries.push({
            key:    key,
            label:  v.label || (_catalog(key) || {}).label || key,
            unit:   v.unit  != null ? v.unit : ((_catalog(key) || {}).unit || ''),
            stages: v.stages.slice(0, 5).map(Number),
            colors: colors,
          });
        }
      });
    }
    if (!_entries.length) {
      DEFAULT_KEYS.forEach(function (k) { _entries.push(_defaultEntry(k)); });
    }
    render();
  }

  /* Called on save — returns { key: {label, unit, stages, colors} } */
  function read() {
    var out = {};
    _entries.forEach(function (e) {
      if (!e.key) return;
      out[e.key] = {
        label:  e.label,
        unit:   e.unit,
        stages: e.stages.map(Number),
        colors: e.colors.slice(),
      };
    });
    return out;
  }

  function _entry(key) {
    return _entries.filter(function (e) { return e.key === key; })[0] || null;
  }

  function render() {
    var list = document.getElementById('sensor-ranges-list');
    if (!list) return;
    if (!_entries.length) fill(null);

    list.innerHTML = '';
    _entries.forEach(function (e) {
      var card = document.createElement('div');
      card.dataset.rangeKey = e.key;
      card.className = 'fac-range-card';

      // Header: name/unit + delete
      var head =
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">' +
          '<div style="font-weight:600;font-size:var(--aot-font-size-sm);">' + _esc(e.label) +
            ' <span style="color:var(--aot-color-text-secondary);font-weight:400;font-size:var(--aot-font-size-xs);">' + _esc(e.unit) +
            ' · <code style="font-size:var(--aot-font-size-xs);color:var(--aot-color-text-secondary);">' + _esc(e.key) + '</code></span></div>' +
          '<button type="button" data-del class="btn aot-pill-btn aot-pill-btn-danger">' + (window._ ? window._('Delete') : 'Delete') + '</button>' +
        '</div>';

      // 5 stages: color + upper limit
      var cols = '';
      for (var i = 0; i < 5; i++) {
        cols +=
          '<div style="flex:1;min-width:60px;text-align:center;">' +
            '<div style="font-size:var(--aot-font-size-xs);color:var(--aot-color-text-secondary);margin-bottom:4px;">' + (window._ ? window._('Stage') : 'Stage') + ' ' + (i + 1) + '</div>' +
            '<input type="color" class="fac-range-color" data-cidx="' + i + '" value="' + _esc(e.colors[i] || PALETTE[i]) + '"> ' +
            '<input type="number" class="form-control aot-modern-input fac-range-limit" data-sidx="' + i + '" step="any" value="' + e.stages[i] + '" ' +
              'title="' + (window._ ? window._('Stage') : 'Stage') + ' ' + (i + 1) + ' ' + (window._ ? window._('upper limit') : 'upper limit') + '">' +
          '</div>';
      }
      card.innerHTML = head +
        '<div style="display:flex;gap:8px;align-items:flex-start;">' + cols + '</div>';
      list.appendChild(card);

      card.querySelector('[data-del]').addEventListener('click', function (ev) {
        ev.stopPropagation();
        _entries = _entries.filter(function (x) { return x.key !== e.key; });
        render();
        _refreshAddSelect();
        _dispatch();
      });
      card.querySelectorAll('input[data-cidx]').forEach(function (inp) {
        inp.addEventListener('input', function (ev) {
          ev.stopPropagation();
          var ent = _entry(e.key); if (!ent) return;
          ent.colors[parseInt(inp.dataset.cidx, 10)] = inp.value;
          _dispatch();
        });
      });
      card.querySelectorAll('input[data-sidx]').forEach(function (inp) {
        inp.addEventListener('input', function (ev) {
          ev.stopPropagation();
          var ent = _entry(e.key); if (!ent) return;
          var n = parseFloat(inp.value);
          if (!isNaN(n)) ent.stages[parseInt(inp.dataset.sidx, 10)] = n;
          _dispatch();
        });
      });
    });

    _refreshAddSelect();
  }

  /* Refresh select with catalog items that can be added (excluding existing keys) */
  function _refreshAddSelect() {
    var sel = document.getElementById('sensor-ranges-add-select');
    if (!sel) return;
    var existing = {};
    _entries.forEach(function (e) { existing[e.key] = true; });
    var opts = [];
    CATALOG.forEach(function (c) {
      if (!existing[c.key]) {
        opts.push('<option value="' + _esc(c.key) + '">' + _esc(c.label) +
          ' (' + _esc(c.unit) + ')</option>');
      }
    });
    opts.push('<option value="__custom__">' + (window._ ? window._('Custom entry…') : 'Custom entry…') + '</option>');
    sel.innerHTML = opts.join('');
    _toggleCustom();
  }

  function _toggleCustom() {
    var sel    = document.getElementById('sensor-ranges-add-select');
    var custom = document.getElementById('sensor-ranges-custom');
    if (!sel || !custom) return;
    custom.style.display = (sel.value === '__custom__') ? '' : 'none';
  }

  function _addFromSelect() {
    var sel = document.getElementById('sensor-ranges-add-select');
    if (!sel) return;
    var key = sel.value;
    if (key === '__custom__') { _toggleCustom(); return; }
    if (!key || _entry(key)) return;
    _entries.push(_defaultEntry(key));
    render();
    _dispatch();
  }

  function _addCustom() {
    var keyEl   = document.getElementById('sr-custom-key');
    var labelEl = document.getElementById('sr-custom-label');
    var unitEl  = document.getElementById('sr-custom-unit');
    if (!keyEl) return;
    var key = (keyEl.value || '').trim();
    if (!key) { keyEl.focus(); return; }
    if (_entry(key)) { alert((window._ ? window._('This match key already exists: ') : 'This match key already exists: ') + key); return; }
    _entries.push(_defaultEntry(key,
      (labelEl && labelEl.value.trim()) || key,
      (unitEl && unitEl.value.trim()) || '',
      null));
    if (keyEl)   keyEl.value = '';
    if (labelEl) labelEl.value = '';
    if (unitEl)  unitEl.value = '';
    render();
    _dispatch();
  }

  function _dispatch() {
    document.dispatchEvent(new CustomEvent('sensor-ranges-changed'));
  }

  function _resetAll() {
    _entries = DEFAULT_KEYS.map(function (k) { return _defaultEntry(k); });
    render();
    _dispatch();
  }

  function init() {
    var resetBtn = document.getElementById('btn-sensor-ranges-reset');
    if (resetBtn) resetBtn.addEventListener('click', _resetAll);

    var addBtn = document.getElementById('btn-sensor-ranges-add');
    if (addBtn) addBtn.addEventListener('click', _addFromSelect);

    var customBtn = document.getElementById('btn-sr-custom-add');
    if (customBtn) customBtn.addEventListener('click', _addCustom);

    var sel = document.getElementById('sensor-ranges-add-select');
    if (sel) sel.addEventListener('change', _toggleCustom);

    // Step bar replaced the old config tabs — refresh when this step opens.
    var tabBtn = document.querySelector('.fac-step[data-step="connect"]');
    if (tabBtn) tabBtn.addEventListener('click', render);

    if (!_entries.length) fill(null);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.SensorRangesUI = { fill: fill, read: read, render: render };
})();
