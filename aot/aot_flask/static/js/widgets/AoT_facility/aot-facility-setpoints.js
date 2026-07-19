// aot-facility-setpoints.js — IEC setpoints via env-cell popup
// Param names match env_coordinator custom_options 1:1.
(function () {
  'use strict';

  // Groups of params shown in each env-cell popup
  var POPUP_GROUPS = {
    vpd: {
      title: 'VPD Target',
      rows: [
        { param: 'target_vpd_kpa', label: 'VPD target', unit: 'kPa', min: 0.1, max: 3.0, step: 0.05,
          fmt: function(v){ return v.toFixed(2); }, curId: 'iec-sp-cur-vpd', lblId: null },
      ],
    },
    temp: {
      title: 'Temperature Setpoints',
      rows: [
        { param: 'guide_t_min_c', label: 'Guide T min', unit: '°C', min: 0, max: 40, step: 0.5,
          fmt: function(v){ return v.toFixed(1); }, curId: 'iec-sp-cur-gtmin', lblId: null },
        { param: 'guide_t_max_c', label: 'Guide T max', unit: '°C', min: 0, max: 45, step: 0.5,
          fmt: function(v){ return v.toFixed(1); }, curId: 'iec-sp-cur-gtmax', lblId: null },
        { param: 'temp_min_c',    label: 'Safety T min', unit: '°C', min: -10, max: 40, step: 0.5,
          fmt: function(v){ return v.toFixed(1); }, curId: 'iec-sp-cur-tmin', lblId: null, safety: true },
        { param: 'temp_max_c',    label: 'Safety T max', unit: '°C', min: 0, max: 50, step: 0.5,
          fmt: function(v){ return v.toFixed(1); }, curId: 'iec-sp-cur-tmax', lblId: null, safety: true },
      ],
    },
    rh: {
      title: 'Humidity Setpoints',
      rows: [
        { param: 'guide_rh_min_pct', label: 'Guide RH min', unit: '%', min: 10, max: 95, step: 1,
          fmt: function(v){ return String(Math.round(v)); }, curId: 'iec-sp-cur-grhmin', lblId: null },
        { param: 'guide_rh_max_pct', label: 'Guide RH max', unit: '%', min: 10, max: 99, step: 1,
          fmt: function(v){ return String(Math.round(v)); }, curId: 'iec-sp-cur-grhmax', lblId: null },
        { param: 'humid_min_pct', label: 'Safety RH min', unit: '%', min: 10, max: 95, step: 1,
          fmt: function(v){ return String(Math.round(v)); }, curId: 'iec-sp-cur-hmin', lblId: null, safety: true },
        { param: 'humid_max_pct', label: 'Safety RH max', unit: '%', min: 10, max: 99, step: 1,
          fmt: function(v){ return String(Math.round(v)); }, curId: 'iec-sp-cur-hmax', lblId: null, safety: true },
      ],
    },
    co2: {
      title: 'CO₂ Target',
      rows: [
        { param: 'target_co2_ppm', label: 'CO₂ target', unit: 'ppm', min: 300, max: 2000, step: 50,
          fmt: function(v){ return String(Math.round(v)); }, curId: 'iec-sp-cur-co2', lblId: null },
      ],
    },
  };

  // Current setpoints cache per widget
  var _cache = {};

  function bind(widgetId, facilityUuid, initialSetpoints) {
    _cache[widgetId] = initialSetpoints || {};

    var popup    = document.getElementById('iec-sp-popup-'       + widgetId);
    var closeBtn = document.getElementById('iec-sp-popup-close-' + widgetId);
    if (!popup) return;

    // Close popup
    if (closeBtn) {
      closeBtn.addEventListener('click', function () { _hidePopup(popup); });
    }
    document.addEventListener('click', function (e) {
      if (popup.style.display !== 'none' && !popup.contains(e.target) && !e.target.closest('[data-sp-key]')) {
        _hidePopup(popup);
      }
    }, true);

    // Open popup on env-cell click
    var envEl = document.getElementById('aot-facility-env-' + widgetId);
    if (!envEl) return;
    envEl.addEventListener('click', function (e) {
      var cell = e.target.closest('[data-sp-key]');
      if (!cell) return;
      var key = cell.dataset.spKey;
      var group = POPUP_GROUPS[key];
      if (!group) return;
      _showPopup(popup, cell, group, widgetId, facilityUuid);
    });
  }

  function _showPopup(popup, anchor, group, widgetId, facilityUuid) {
    var titleEl = document.getElementById('iec-sp-popup-title-' + widgetId);
    var rowsEl  = document.getElementById('iec-sp-popup-rows-'  + widgetId);
    var msgEl   = document.getElementById('iec-sp-popup-msg-'   + widgetId);
    if (titleEl) titleEl.textContent = group.title;
    if (msgEl)   msgEl.textContent = '';

    var sp = _cache[widgetId] || {};
    var html = '';
    group.rows.forEach(function (row) {
      var curVal = sp[row.param];
      var curStr = curVal != null ? row.fmt(curVal) : '—';
      var sepClass = row.safety ? ' style="margin-top:.5rem;padding-top:.4rem;border-top:1px solid var(--aot-border-light)"' : '';
      html += '<div class="iec-sp-popup-row"' + sepClass + '>' +
              '<span class="iec-sp-popup-label">' + _esc(row.label) + ' <em style="font-style:normal;opacity:.6">' + _esc(row.unit) + '</em></span>' +
              '<span class="iec-sp-popup-cur" id="iec-sp-popup-cur-' + widgetId + '-' + row.param + '">' + _esc(curStr) + '</span>' +
              '<input type="number" class="iec-sp-popup-input"' +
              ' id="iec-sp-popup-inp-' + widgetId + '-' + row.param + '"' +
              ' min="' + row.min + '" max="' + row.max + '" step="' + row.step + '"' +
              ' placeholder="' + row.min + '–' + row.max + '">' +
              '<button class="iec-sp-popup-set" data-param="' + row.param + '"' +
              ' data-wid="' + widgetId + '" data-facility="' + facilityUuid + '">' +
              'Set</button>' +
              '</div>';
    });
    if (rowsEl) rowsEl.innerHTML = html;

    // Position near anchor
    var rect = anchor.getBoundingClientRect();
    popup.style.display = 'block';
    var pw = popup.offsetWidth || 260;
    var ph = popup.offsetHeight || 160;
    var left = Math.min(rect.left, window.innerWidth - pw - 8);
    var top  = rect.bottom + 4;
    if (top + ph > window.innerHeight) top = rect.top - ph - 4;
    popup.style.left = Math.max(4, left) + 'px';
    popup.style.top  = Math.max(4, top)  + 'px';

    // Bind Set buttons
    popup.addEventListener('click', _onSetClick);
    popup._cleanupSet = function () { popup.removeEventListener('click', _onSetClick); };
  }

  function _onSetClick(e) {
    var btn = e.target.closest('.iec-sp-popup-set');
    if (!btn) return;

    var param    = btn.dataset.param;
    var wid      = btn.dataset.wid;
    var facility = btn.dataset.facility;
    if (!param || !facility) return;

    // Find matching row meta
    var rowMeta = null;
    Object.keys(POPUP_GROUPS).forEach(function (k) {
      POPUP_GROUPS[k].rows.forEach(function (r) { if (r.param === param) rowMeta = r; });
    });
    if (!rowMeta) return;

    var inputEl = document.getElementById('iec-sp-popup-inp-' + wid + '-' + param);
    var msgEl   = document.getElementById('iec-sp-popup-msg-' + wid);
    if (!inputEl) return;

    var raw = inputEl.value.trim();
    if (raw === '') { _showMsg(msgEl, (window._ ? window._('Enter a value') : 'Enter a value'), 'err'); return; }
    var v = parseFloat(raw);
    if (isNaN(v) || v < rowMeta.min || v > rowMeta.max) {
      _showMsg(msgEl, param + ': ' + (window._ ? window._('must be within range') : 'must be within range') + ' ' + rowMeta.min + ' – ' + rowMeta.max, 'err');
      return;
    }

    btn.disabled = true;
    var body = {};
    body[param] = v;

    fetch('/api/aot/facility/' + facility + '/setpoints', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.ok) {
        var sp = data.setpoints || {};
        _cache[wid] = sp;
        var curEl = document.getElementById('iec-sp-popup-cur-' + wid + '-' + param);
        if (curEl) curEl.textContent = rowMeta.fmt(v);
        inputEl.value = '';
        _showMsg(msgEl, (window._ ? window._('Saved') : 'Saved'), 'ok');
        _updateEnvLabels(wid, sp);
      } else {
        _showMsg(msgEl, (data.errors || [data.message]).join(', '), 'err');
      }
      btn.disabled = false;
    })
    .catch(function (err) {
      _showMsg(msgEl, 'Error: ' + err, 'err');
      btn.disabled = false;
    });
  }

  function _hidePopup(popup) {
    popup.style.display = 'none';
    if (popup._cleanupSet) { popup._cleanupSet(); popup._cleanupSet = null; }
  }

  function _showMsg(el, text, type) {
    if (!el) return;
    el.textContent = text;
    el.style.color = type === 'err' ? '#e53935' : '#43a047';
    clearTimeout(el._timer);
    el._timer = setTimeout(function () { el.textContent = ''; }, 3000);
  }

  // Update § B env-cell labels and deviation colors
  function updateEnvColors(widgetId, indoor, setpoints) {
    if (!setpoints) return;
    _cache[widgetId] = setpoints;
    _updateEnvLabels(widgetId, setpoints);

    var envEl = document.getElementById('aot-facility-env-' + widgetId);
    if (!envEl) return;

    var vpd_target = setpoints.target_vpd_kpa;
    _colorCell(envEl, 'indoor_vpd', indoor.vpd_kpa, vpd_target, 0.1, false);

    var t_min = setpoints.guide_t_min_c != null ? setpoints.guide_t_min_c : 12.0;
    var t_max = setpoints.guide_t_max_c != null ? setpoints.guide_t_max_c : 32.0;
    _colorCellRange(envEl, 'indoor_temp', indoor.temp_c, t_min, t_max);

    var rh_min = setpoints.guide_rh_min_pct != null ? setpoints.guide_rh_min_pct : 40.0;
    var rh_max = setpoints.guide_rh_max_pct != null ? setpoints.guide_rh_max_pct : 85.0;
    _colorCellRange(envEl, 'indoor_humidity', indoor.humidity_pct, rh_min, rh_max);

    var co2_target = setpoints.target_co2_ppm != null ? setpoints.target_co2_ppm : 1000.0;
    _colorCell(envEl, 'indoor_co2', indoor.co2_ppm, co2_target, 100, true);
  }

  function _colorCell(envEl, key, val, target, tol, co2Mode) {
    var cell = envEl.querySelector('[data-key="' + key + '"]');
    if (!cell) return;
    cell.classList.remove('env-ok', 'env-warn', 'env-err');
    if (val == null || target == null) return;
    if (co2Mode) {
      if (val <= target)             cell.classList.add('env-ok');
      else if (val <= target * 1.1)  cell.classList.add('env-warn');
      else                           cell.classList.add('env-err');
    } else {
      var dev = Math.abs(val - target);
      if (dev <= tol)        cell.classList.add('env-ok');
      else if (dev <= 2*tol) cell.classList.add('env-warn');
      else                   cell.classList.add('env-err');
    }
  }

  function _colorCellRange(envEl, key, val, lo, hi) {
    var cell = envEl.querySelector('[data-key="' + key + '"]');
    if (!cell) return;
    cell.classList.remove('env-ok', 'env-warn', 'env-err');
    if (val == null) return;
    var band = (hi - lo) * 0.1;
    if (val >= lo && val <= hi)                    cell.classList.add('env-ok');
    else if (val >= lo - band && val <= hi + band) cell.classList.add('env-warn');
    else                                           cell.classList.add('env-err');
  }

  function _updateEnvLabels(widgetId, sp) {
    if (!sp) return;
    var lblVpd    = document.getElementById('iec-sp-lbl-vpd-'     + widgetId);
    var lblTguide = document.getElementById('iec-sp-lbl-tguide-'  + widgetId);
    var lblRHguide= document.getElementById('iec-sp-lbl-rhguide-' + widgetId);
    var lblCo2    = document.getElementById('iec-sp-lbl-co2-'     + widgetId);

    if (lblVpd && sp.target_vpd_kpa != null)
      lblVpd.textContent = 'target ' + sp.target_vpd_kpa.toFixed(2) + ' kPa';
    if (lblTguide && sp.guide_t_min_c != null && sp.guide_t_max_c != null)
      lblTguide.textContent = sp.guide_t_min_c.toFixed(0) + '–' + sp.guide_t_max_c.toFixed(0) + '°C';
    if (lblRHguide && sp.guide_rh_min_pct != null && sp.guide_rh_max_pct != null)
      lblRHguide.textContent = Math.round(sp.guide_rh_min_pct) + '–' + Math.round(sp.guide_rh_max_pct) + '%';
    if (lblCo2 && sp.target_co2_ppm != null)
      lblCo2.textContent = 'target ' + Math.round(sp.target_co2_ppm) + ' ppm';
  }

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  window.AoTFacilitySetpoints = { bind: bind, updateEnvColors: updateEnvColors };
})();
