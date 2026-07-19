// aot-facility-sensor-labels.js — HTML overlay sensor labels for the 3D scene.
//
// Public API: window.AoTSensorLabels = {
//   attach(widgetId, ctx, facility, opts)   — bind to scene; rebuilds on each call
//   updateValues(widgetId, fittingSensors)  — refresh label values
//   detach(widgetId)
// }
(function () {
  'use strict';

  // widgetId → { overlayEl, labels:[{el, fittingId, sensor, posVec}], rafId, ctx, opts, facility }
  var STATE = {};

  // ── Label color bands (5 levels) ────────────────────────────────────────────────
  // Upper bounds of the 5 levels for each measurement. The label border is colored by the band the value falls into.
  // Default used when facility.view_options.sensor_ranges is absent. Keep in sync with the
  // SensorRangesUI defaults in the design panel (geo_facility.html).
  // Global palette for the 5 measurement bands: reads --aot-band-1..5 CSS tokens
  // (settings/custom_ui band_1..5 로 사용자 정의 가능) with literal fallbacks.
  var BAND_PALETTE = (function () {
    var defaults = ['#2DB4FF', '#54BCC1', '#32c85a', '#FEAE5F', '#CF5C58'];
    try {
      var cs = getComputedStyle(document.documentElement);
      return defaults.map(function (c, i) {
        var v = cs.getPropertyValue('--aot-band-' + (i + 1)).trim();
        return v || c;
      });
    } catch (e) { return defaults; }
  })();
  var DEFAULT_RANGES = {
    T:       [10, 18, 26, 34, 45],
    RH:      [40, 55, 70, 85, 100],
    VPD:     [0.4, 0.8, 1.2, 1.6, 3.0],
    light:   [200, 400, 600, 800, 1200],
    wind_ms: [2, 4, 6, 9, 15]
  };

  // Items with inverted meaning (e.g. humidity) use the default palette reversed
  var REVERSE_KEYS = { RH: true };
  function _defColors(key) {
    return REVERSE_KEYS[key] ? BAND_PALETTE.slice().reverse() : BAND_PALETTE;
  }

  // Resolve key → { stages:[5], colors:[5] }. Supports the new format ({stages,colors}),
  // the old format (array), and unset (defaults). Returns null when no match.
  function _resolveBand(key, ranges) {
    var def = ranges && ranges[key];
    if (Array.isArray(def)) return { stages: def, colors: _defColors(key) };
    if (def && Array.isArray(def.stages)) {
      return {
        stages: def.stages,
        colors: (Array.isArray(def.colors) && def.colors.length) ? def.colors : _defColors(key)
      };
    }
    var d = DEFAULT_RANGES[key];
    return d ? { stages: d, colors: _defColors(key) } : null;
  }

  // key/value → band color. Returns null for items with no range set (not colored).
  function _bandColor(key, value, ranges) {
    if (value == null || isNaN(value)) return null;
    var b = _resolveBand(key, ranges);
    if (!b || !b.stages.length) return null;
    for (var i = 0; i < b.stages.length; i++) {
      var hi = parseFloat(b.stages[i]);
      if (isNaN(hi)) continue;
      if (value <= hi) return b.colors[Math.min(i, b.colors.length - 1)];
    }
    // Above the last level's upper bound → top band color
    return b.colors[b.colors.length - 1];
  }

  // Border colored by the label's representative channel (first channel with a value and a defined band).
  function _applyBandColor(el, channels, ranges) {
    var color = null;
    for (var i = 0; i < (channels || []).length; i++) {
      var c = channels[i];
      if (!c || c.value == null) continue;
      color = _bandColor(c.key, +c.value, ranges);
      if (color) break;
    }
    // box-shadow ring — doesn't change box size, so label position stays stable
    el.style.boxShadow = color ? ('0 0 0 2px ' + color) : '';
  }

  function _overlayEl(widgetId) {
    return document.getElementById('aot-sensor-labels-' + widgetId);
  }

  // position may be {x,y,z} object (current schema) or [x,y,z] array (legacy)
  function _posToXYZ(p) {
    if (!p) return null;
    if (Array.isArray(p)) {
      if (p.length < 3) return null;
      return [parseFloat(p[0]) || 0, parseFloat(p[1]) || 0, parseFloat(p[2]) || 0];
    }
    if (typeof p === 'object' && (p.x != null || p.y != null || p.z != null)) {
      return [parseFloat(p.x) || 0, parseFloat(p.y) || 0, parseFloat(p.z) || 0];
    }
    return null;
  }

  function _sensorFittings(facility) {
    var f = facility && facility.fittings;
    if (!Array.isArray(f)) return [];
    return f.filter(function (x) {
      return x && x.kind === 'sensor' && _posToXYZ(x.position);
    });
  }

  function _applyStyle(el, opts) {
    el.style.background = opts.bg || 'rgba(15,23,42,0.78)';
    el.style.color      = opts.fg || '#f8fafc';
    el.style.fontSize   = (opts.size_em || 0.85) + 'em';
    el.style.opacity    = opts.opacity != null ? opts.opacity : 0.7;
  }

  function _initSinglePopupHandler() {
    if (window._aotSensorLabelEscBound) return;
    window._aotSensorLabelEscBound = true;
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && window.AoTSensorLabel) window.AoTSensorLabel.closePopup();
    });
  }

  function attach(widgetId, ctx, facility, opts) {
    opts = opts || {};
    detach(widgetId);

    if (opts.show === false) { return; }

    var overlay = _overlayEl(widgetId);
    if (!overlay) { console.warn('[AoTSensorLabels] overlay element missing:', 'aot-sensor-labels-' + widgetId); return; }
    if (!ctx || !ctx.camera || !ctx.renderer) {
      console.warn('[AoTSensorLabels] ctx incomplete', { hasCamera: !!(ctx && ctx.camera), hasRenderer: !!(ctx && ctx.renderer) });
      return;
    }

    var fittings = _sensorFittings(facility);
    if (!fittings.length) return;

    var labels = fittings.map(function (f) {
      var el = document.createElement('div');
      el.className = 'aot-sensor-label';
      el.dataset.fittingId = f.id;
      _applyStyle(el, opts);
      el.textContent = '—';
      if (opts.popup !== false) {
        el.classList.add('aot-sensor-label-clickable');
        el.addEventListener('click', function (ev) {
          ev.stopPropagation();
          var st = STATE[widgetId];
          if (!st) return;
          var sensor = (st.sensorsByFitting && st.sensorsByFitting[f.id])
            || _fallbackSensor(f);
          if (window.AoTSensorLabel) {
            var host = document.getElementById('aot-facility-' + widgetId)
                    || (overlay && overlay.parentNode);
            window.AoTSensorLabel.openPopup(sensor, {
              decimals: opts.decimals,
              anchorEvent: ev,
              host: host
            });
          }
        });
      }
      overlay.appendChild(el);

      var xyz = _posToXYZ(f.position) || [0, 0, 0];
      var pos = new window.THREE.Vector3(
        xyz[0],
        xyz[1] + (opts.offset_y || 0),
        xyz[2]
      );
      return { el: el, fittingId: f.id, fitting: f, posVec: pos };
    });

    STATE[widgetId] = {
      overlayEl: overlay,
      labels: labels,
      sensorsByFitting: {},
      ctx: ctx,
      opts: opts,
      facility: facility,
      rafId: null
    };
    _initSinglePopupHandler();
    _loop(widgetId);
  }

  function _fallbackSensor(fitting) {
    return {
      fitting_id: fitting.id,
      name: fitting.name || fitting.id,
      position: fitting.position,
      sensor_role: fitting.sensor_role || 'indoor',
      device_id: fitting.input_id || '',
      device_name: null,
      channels: []
    };
  }

  function _loop(widgetId) {
    var st = STATE[widgetId];
    if (!st) return;
    var canvas = st.ctx.renderer && st.ctx.renderer.domElement;
    if (!canvas) return;

    var v = new window.THREE.Vector3();

    function step() {
      var st2 = STATE[widgetId];
      if (!st2) return;
      var rect = canvas.getBoundingClientRect();
      var parentRect = st2.overlayEl.getBoundingClientRect();
      // overlay is positioned over the canvas via CSS (absolute 0,0,0,0 inside .aot-facility-3d-wrap)
      var W = rect.width, H = rect.height;

      st2.labels.forEach(function (lab) {
        v.copy(lab.posVec);
        v.project(st2.ctx.camera);
        if (v.z > 1 || v.z < -1) {
          lab.el.style.display = 'none';
          return;
        }
        var x = (v.x * 0.5 + 0.5) * W;
        var y = (-v.y * 0.5 + 0.5) * H;
        lab.el.style.display = '';
        lab.el.style.transform = 'translate(' + x + 'px,' + y + 'px) translate(-50%,-100%)';
      });
      st2.rafId = requestAnimationFrame(step);
    }
    st.rafId = requestAnimationFrame(step);
  }

  function updateValues(widgetId, fittingSensors) {
    var st = STATE[widgetId];
    if (!st) return;

    var byId = {};
    (fittingSensors || []).forEach(function (s) { byId[s.fitting_id] = s; });
    st.sensorsByFitting = byId;

    var opts = st.opts || {};
    st.labels.forEach(function (lab) {
      var sensor = byId[lab.fittingId];
      if (!sensor || !sensor.channels) {
        lab.el.textContent = '—';
        lab.el.classList.remove('aot-stale');
        lab.el.style.boxShadow = '';
        return;
      }
      lab.el.textContent = window.AoTSensorLabel
        ? window.AoTSensorLabel.formatLabel(sensor.channels, {
            maxChannels: opts.max_channels || 1,
            decimals:    opts.decimals
          })
        : '—';
      var anyValid = sensor.channels.some(function (c) { return c.valid; });
      lab.el.classList.toggle('aot-stale', !anyValid);
      // Label coloring based on the measurement band
      _applyBandColor(lab.el, sensor.channels, opts.ranges);
    });
  }

  function detach(widgetId) {
    var st = STATE[widgetId];
    if (!st) return;
    if (st.rafId) cancelAnimationFrame(st.rafId);
    if (st.overlayEl) st.overlayEl.innerHTML = '';
    delete STATE[widgetId];
  }

  window.AoTSensorLabels = {
    attach: attach,
    updateValues: updateValues,
    detach: detach
  };
})();
