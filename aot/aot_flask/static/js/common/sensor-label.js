// sensor-label.js — Shared utilities for facility sensor labels & popup.
// Consumers: aot-facility-sensor-labels.js, AoT_map sensor labels.
//
// Public API: window.AoTSensorLabel = {
//   formatChannel(ch, decimals)      → "24.3°C"
//   formatLabel(channels, opts)      → "24.3°C / 65%" or "...+"
//   openPopup(sensor, opts)          → opens singleton detail popup (24h chart)
//   closePopup()
// }
(function () {
  'use strict';

  var _DEFAULT_DECIMALS = {
    T: 1, RH: 1, CO2: 0, VPD: 2, light: 0, wind_ms: 1, wind_deg: 0
  };

  // channel.key → display name in the popup legend (uses the key as-is if no mapping)
  // Values are output in the current language via the window._ translation system.
  var _t = function (s) { return (window._ ? window._(s) : s); };
  var _KEY_DISPLAY = {
    T:        _t('Temperature'),
    RH:       _t('Humidity'),
    CO2:      'CO₂',
    VPD:      'VPD',
    light:    _t('Light'),
    wind_ms:  _t('Wind Speed'),
    wind_deg: _t('Wind Direction'),
  };

  function _fmtNumber(v, decimals) {
    if (v == null || isNaN(v)) return '—';
    var d = decimals != null ? decimals : 1;
    return (+v).toFixed(d);
  }

  function formatChannel(ch, decimals) {
    if (!ch || ch.value == null) return '—';
    var d = decimals != null ? decimals : (_DEFAULT_DECIMALS[ch.key] != null ? _DEFAULT_DECIMALS[ch.key] : 1);
    return _fmtNumber(ch.value, d) + (ch.unit || '');
  }

  function formatLabel(channels, opts) {
    opts = opts || {};
    var maxN = opts.maxChannels || 2;
    var dec  = opts.decimals;
    if (!Array.isArray(channels) || !channels.length) return '—';
    var renderable = channels.filter(function (c) { return c.value != null; });
    if (!renderable.length) return '—';
    var shown = renderable.slice(0, maxN).map(function (c) {
      return formatChannel(c, dec);
    }).join(' / ');
    return renderable.length > maxN ? shown + ' +' : shown;
  }

  // ─── Popup (per-widget — appended to host element, not document.body) ──────
  // Each widget owns one popup instance keyed by its host element. Clicking
  // outside the popup closes it. The popup never escapes the host bounds.
  var _popups = new WeakMap();   // hostEl → popupEl
  var _activePopup = null;       // {popupEl, hostEl, outsideHandler}

  function _ensurePopup(hostEl) {
    var popupEl = _popups.get(hostEl);
    if (popupEl) return popupEl;
    // Host must be a positioned ancestor so absolute children stay inside.
    var cs = window.getComputedStyle(hostEl);
    if (cs.position === 'static') hostEl.style.position = 'relative';
    popupEl = document.createElement('div');
    popupEl.className = 'aot-sensor-popup aot-sensor-popup-scoped';
    hostEl.appendChild(popupEl);
    _popups.set(hostEl, popupEl);
    return popupEl;
  }

  function closePopup() {
    if (_activePopup) {
      if (_activePopup.outsideHandler) {
        document.removeEventListener('mousedown', _activePopup.outsideHandler, true);
        document.removeEventListener('touchstart', _activePopup.outsideHandler, true);
      }
      if (_activePopup.modalOverlay) {
        // Modal: remove the entire screen-centered overlay
        try { _activePopup.modalOverlay.remove(); } catch (e) {}
        document.body.style.overflow = '';
      } else if (_activePopup.popupEl) {
        _activePopup.popupEl.style.display = 'none';
      }
    }
    _activePopup = null;
  }

  // Create a screen-centered fixed modal overlay (same UX as the control label popup).
  // Returns: { overlay, box } — box is the .aot-sensor-popup body container.
  function _buildModalOverlay() {
    var overlay = document.createElement('div');
    overlay.className = 'aot-sensor-modal-overlay';
    var box = document.createElement('div');
    box.className = 'aot-sensor-popup aot-sensor-popup--modal';
    box.style.display = 'block';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    return { overlay: overlay, box: box };
  }

  function _positionPopup(popupEl, hostEl, anchorEvent) {
    if (!popupEl || !hostEl) return;
    var pad = 6;
    var hostRect = hostEl.getBoundingClientRect();
    var pw = popupEl.offsetWidth  || Math.min(420, hostRect.width  - 2*pad);
    var ph = popupEl.offsetHeight || Math.min(280, hostRect.height - 2*pad);
    var x, y;
    if (anchorEvent && typeof anchorEvent.clientX === 'number') {
      // Convert page-coords to host-local
      x = anchorEvent.clientX - hostRect.left + 8;
      y = anchorEvent.clientY - hostRect.top  + 8;
    } else {
      x = (hostRect.width  - pw) / 2;
      y = (hostRect.height - ph) / 2;
    }
    // Clamp inside host bounds
    x = Math.max(pad, Math.min(x, hostRect.width  - pw - pad));
    y = Math.max(pad, Math.min(y, hostRect.height - ph - pad));
    popupEl.style.left = x + 'px';
    popupEl.style.top  = y + 'px';
    // Cap dimensions to host
    popupEl.style.maxWidth  = Math.max(120, hostRect.width  - 2*pad) + 'px';
    popupEl.style.maxHeight = Math.max(120, hostRect.height - 2*pad) + 'px';
  }

  function _resolveHost(opts) {
    if (opts && opts.host instanceof Element) return opts.host;
    if (opts && typeof opts.host === 'string') {
      var el = document.getElementById(opts.host) || document.querySelector(opts.host);
      if (el) return el;
    }
    if (opts && opts.anchorEvent && opts.anchorEvent.target) {
      var t = opts.anchorEvent.target;
      // Walk up from the clicked label to find the widget container
      var host = t.closest && (
        t.closest('.aot-facility-container') ||
        t.closest('.aot-map-container') ||
        t.closest('.dashboard-widget') ||
        t.closest('[data-widget-host]')
      );
      if (host) return host;
    }
    return document.body;
  }

  function _escape(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }

  function _formatTs(iso) {
    if (!iso) return '—';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleString();
    } catch (e) { return iso; }
  }

  // ─── Shared detail body (24h chart + measurement legend) ───────────────────
  // Single source of truth for the sensor-popup composition so any host (the
  // facility modal popup AND the map input-device popup) renders identically.

  // Legend row: color dot + measurement name + current value + unit.
  function _legendRowsHtml(channels, opts) {
    opts = opts || {};
    var colors = _chartColors();
    return (channels || []).map(function (c, i) {
      var stale = c.stale ? ' aot-stale' : '';
      var color = colors[i % colors.length];
      var dispName = _KEY_DISPLAY[c.key] || _escape(c.key || c.measurement_type || '');
      var dec = opts.decimals != null ? opts.decimals
              : (_DEFAULT_DECIMALS[c.key] != null ? _DEFAULT_DECIMALS[c.key] : 1);
      var valStr = _fmtNumber(c.value, dec);
      var unit = _escape(c.unit || '');
      // data-mid lets _renderHistory backfill the latest value from the 24h
      // series when the channel arrived without a current value (e.g. map input
      // devices, whose measurements_map carries no last_value).
      var mid = _escape(c.measurement_id != null ? String(c.measurement_id) : '');
      return '<div class="aot-spop-legend-row' + stale + '">' +
        '<span class="aot-spop-legend-dot" style="background:' + color + ';"></span>' +
        '<span class="aot-spop-legend-name">' + dispName + '</span>' +
        '<span class="aot-spop-legend-val"' + (mid ? ' data-mid="' + mid + '"' : '') +
          ' data-dec="' + dec + '">' +
          '<span class="aot-spop-legend-num">' + _escape(valStr) + '</span>' +
          (unit ? '<span class="aot-spop-legend-unit"> ' + unit + '</span>' : '') +
        '</span>' +
      '</div>';
    }).join('');
  }

  // Chart wrap + legend (no title/close — caller owns the chrome).
  function _detailBodyHtml(sensor, opts) {
    var legendRows = _legendRowsHtml((sensor && sensor.channels) || [], opts);
    return '<div class="aot-sensor-popup-chart-wrap">' +
        '<div id="aot-sensor-popup-chart" style="width:100%;"></div>' +
        '<div class="aot-sensor-popup-chart-status">loading…</div>' +
      '</div>' +
      '<div class="aot-spop-legend">' +
        (legendRows || '<span class="aot-spop-legend-empty">—</span>') +
      '</div>';
  }

  // Optional note footer — shared so the facility sensor popup and the map
  // input-device popup stay one component. note: { targetId, name, targetType }.
  // Reuses the existing shared popup button + note-preview classes (map.css):
  // .aot-popup-btn--primary (AoT brand primary) and .aot-popup-note-preview —
  // no bespoke styling, same as every other map popup's Create Note button.
  function _noteSectionHtml(note) {
    if (!note || !note.targetId) return '';
    return '<hr class="aot-popup-divider">' +
      '<button type="button" class="aot-popup-btn aot-popup-btn--primary aot-popup-btn--full">' +
        _escape(_t('Create Note')) + '</button>' +
      '<div class="aot-popup-note-preview">' +
        '<span style="color:#ccc;font-style:italic;">…</span></div>';
  }

  function _wireNoteSection(scopeEl, note) {
    if (!note || !note.targetId) return;
    var btn = scopeEl.querySelector('.aot-popup-btn--primary');
    if (btn) {
      btn.addEventListener('click', function () {
        window.dispatchEvent(new CustomEvent('open-notes', { detail: {
          targetId:   note.targetId,
          targetType: note.targetType || 'device',
          name:       note.name || ''
        } }));
      });
    }
    var prev = scopeEl.querySelector('.aot-popup-note-preview');
    if (prev) {
      fetch('/notes/target/' + encodeURIComponent(note.targetId))
        .then(function (r) { return r.json(); })
        .then(function (notes) {
          if (Array.isArray(notes) && notes.length) {
            prev.textContent = notes[0].note || '';
          } else {
            prev.innerHTML = '<span style="color:#ccc;font-style:italic;">' +
              _escape(_t('No Notes')) + '</span>';
          }
        })
        .catch(function () {});
    }
  }

  function openPopup(sensor, opts) {
    opts = opts || {};
    closePopup();  // ensure single active popup across widgets

    var modal = !!opts.modal;
    var hostEl = null, popupEl, modalOverlay = null;
    if (modal) {
      var m = _buildModalOverlay();
      modalOverlay = m.overlay;
      popupEl = m.box;
    } else {
      hostEl  = _resolveHost(opts);
      popupEl = _ensurePopup(hostEl);
      popupEl.style.display = 'block';
    }
    var _popupEl = popupEl;  // alias for the original code below

    // Layout order: title → chart → measurement legend (chart + legend shared
    // with the map input-device popup via _detailBodyHtml).
    // comm_fault (set by the caller from /inputstate — see
    // io_link_health_infra_plan.md) highlights the name label itself with the
    // shared global warning tint — same treatment as the Input/Output/Function
    // list-page cards (window.AoTOutputState.paintNameWarning). Inline style
    // with !important, not a CSS class: a class-based version of this exact
    // highlight silently lost a specificity/!important tie against this
    // page's own name-label rules on some pages — see paintNameWarning()'s
    // comment in aot-output-state.js for the full story.
    var titleStyle = sensor.comm_fault
      ? ' style="background-color:var(--aot-tint-warning-bg) !important;color:var(--aot-tint-warning-fg) !important;"'
      : '';
    var titleAttr = sensor.comm_fault ? ' title="' + _escape(_t('No Response')) + '"' : '';

    _popupEl.innerHTML =
      '<div class="aot-sensor-popup-header">' +
        '<span class="aot-sensor-popup-title"' + titleStyle + titleAttr + '>' + _escape(sensor.name || sensor.fitting_id) + '</span>' +
        '<button class="aot-sensor-popup-close" type="button" aria-label="close">&#x2715;</button>' +
      '</div>' + _detailBodyHtml(sensor, opts) + _noteSectionHtml(opts.note);

    _popupEl.querySelector('.aot-sensor-popup-close').addEventListener('click', closePopup);
    _wireNoteSection(_popupEl, opts.note);

    if (modal) {
      document.body.style.overflow = 'hidden';
      // Centered modal: close on backdrop click. No separate position calculation needed.
      modalOverlay.addEventListener('click', function (e) {
        if (e.target === modalOverlay) closePopup();
      });
      _activePopup = { popupEl: _popupEl, modalOverlay: modalOverlay };
    } else {
      _positionPopup(_popupEl, hostEl, opts.anchorEvent);
      // outside-click / outside-touch closes the popup
      var outsideHandler = function (e) {
        if (!_popupEl.contains(e.target)) closePopup();
      };
      _activePopup = { popupEl: _popupEl, hostEl: hostEl, outsideHandler: outsideHandler };
      setTimeout(function () {
        document.addEventListener('mousedown', outsideHandler, true);
        document.addEventListener('touchstart', outsideHandler, true);
      }, 0);
    }

    _renderHistory(sensor, _popupEl);
  }

  // ─── Lazy-load Highstock (shared with AoT_graph widget) ────────────────────
  var _hcLoading = null;
  function _ensureHighcharts() {
    if (window.Highcharts && window.Highcharts.stockChart) return Promise.resolve(true);
    if (_hcLoading) return _hcLoading;
    _hcLoading = new Promise(function (resolve) {
      var s = document.createElement('script');
      s.src = '/static/js/vendor/user_js/highstock-9.1.2.js';
      s.async = true;
      s.onload = function () { resolve(true); };
      s.onerror = function () { resolve(false); };
      document.head.appendChild(s);
    });
    return _hcLoading;
  }

  // ─── 24h history via existing /past endpoint (per channel) ─────────────────
  function _renderHistory(sensor, popupEl) {
    var chartEl  = popupEl.querySelector('#aot-sensor-popup-chart');
    var statusEl = popupEl.querySelector('.aot-sensor-popup-chart-status');
    if (!chartEl || !sensor.device_id) {
      if (statusEl) statusEl.textContent = 'no device';
      return;
    }

    var channels = (sensor.channels || []).filter(function (c) { return c.measurement_id; });
    if (!channels.length) {
      if (statusEl) statusEl.textContent = 'no channels';
      return;
    }

    var past = 86400;  // 1 day in seconds
    var _nowMs = Date.now();
    var _minMs = _nowMs - past * 1000;
    var requests = channels.map(function (ch) {
      var url = '/past/' + encodeURIComponent(sensor.device_id) +
                '/input/' + encodeURIComponent(ch.measurement_id) +
                '/' + past;
      return fetch(url).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
    });

    Promise.all(requests).then(function (responses) {
      var series = [];
      responses.forEach(function (rows, i) {
        var ch = channels[i];
        if (!rows || !Array.isArray(rows) || !rows.length) return;
        // /past returns [[isoTs, value], ...]
        var data = rows.map(function (row) {
          // /past returns [unix_seconds, value]. Skip null rows (aggregateWindow empty buckets).
          if (row[1] == null) return null;
          var t = (typeof row[0] === 'number') ? row[0] * 1000 : new Date(row[0]).getTime();
          return [t, +row[1]];
        }).filter(function (p) { return p != null && !isNaN(p[0]) && !isNaN(p[1]); })
          .sort(function (a, b) { return a[0] - b[0]; });
        if (!data.length) return;
        series.push({
          name: (ch.key || ch.measurement_type || 'channel ' + (i + 1)) + (ch.unit ? ' (' + ch.unit + ')' : ''),
          data: data,
          yAxis: i,
          tooltip: { valueSuffix: ' ' + (ch.unit || '') }
        });
        // Backfill a missing legend value from the latest series point. Only
        // fills rows still showing the placeholder so a live value is never
        // overwritten by the (delayed) aggregated history bucket.
        if (ch.measurement_id != null) {
          var numEl = popupEl.querySelector(
            '.aot-spop-legend-val[data-mid="' + ch.measurement_id + '"] .aot-spop-legend-num');
          if (numEl && (!numEl.textContent || numEl.textContent === '—')) {
            var valEl = numEl.parentElement;
            var dec = valEl && valEl.dataset.dec != null ? parseInt(valEl.dataset.dec, 10) : 1;
            numEl.textContent = _fmtNumber(data[data.length - 1][1], isNaN(dec) ? 1 : dec);
          }
        }
      });

      if (!series.length) {
        if (statusEl) statusEl.textContent = 'no data in last 24h';
        return;
      }

      _ensureHighcharts().then(function (ok) {
        if (!ok || !window.Highcharts) {
          if (statusEl) statusEl.textContent = 'Highcharts load failed';
          return;
        }
        _drawChart(chartEl, statusEl, series, { min: _minMs, max: _nowMs });
      });
    });
  }

  var _PALETTE_LIGHT = ['#FEA60B','#8BC1C1','#93B261','#F4D624','#DF5353','#008DDE','#7cb5ec','#434348','#90ed7d','#f7a35c','#8085e9','#f15c80','#e4d354','#2b908f','#f45b5b','#91e8e1'];
  var _PALETTE_DARK  = ['#FEA60B','#8BC1C1','#93B261','#F4D624','#DF5353','#008DDE','#2b908f','#90ee7e','#f45b5b','#7798BF','#aaeeee','#ff0066','#eeaaee','#55BF3B','#DF5353','#7798BF','#aaeeee'];

  function _chartColors() {
    var isDark = document.documentElement.classList.contains('dark') ||
                 document.body.classList.contains('dark') ||
                 (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    return isDark ? _PALETTE_DARK : _PALETTE_LIGHT;
  }

  function _drawChart(chartEl, statusEl, series, xRange) {
    // Fixed 1.6:1 (width:height) aspect — keeps the chart short so a growing
    // legend stays readable. Read the actual width after layout completes.
    // xRange: optional { min, max } in ms — enforces explicit x-axis window.
    requestAnimationFrame(function () {
      var w = chartEl.offsetWidth || 280;

      var yAxes = series.map(function (s, i) {
        return {
          title:  { text: null },
          labels: { enabled: false },
          opposite: i % 2 === 1
        };
      });

      // Fixed 1.6:1 (width:height) ratio.
      var chartH = Math.round(w / 1.6);
      var xAxisOpts = { type: 'datetime', labels: { style: { fontSize: '9px' } } };
      if (xRange) {
        if (xRange.min != null) xAxisOpts.min = xRange.min;
        if (xRange.max != null) xAxisOpts.max = xRange.max;
      }
      var chartOpts = {
        colors: _chartColors(),
        chart: { height: chartH, spacing: [4, 4, 4, 4] },
        rangeSelector: { enabled: false },
        navigator: { enabled: false },
        scrollbar: { enabled: false },
        credits: { enabled: false },
        exporting: { enabled: false },
        navigation: { buttonOptions: { enabled: false } },
        legend: { enabled: false },
        xAxis: xAxisOpts,
        yAxis: yAxes,
        tooltip: { shared: true, valueDecimals: 2 },
        series: series
      };

      try {
        window.Highcharts.stockChart(chartEl, chartOpts);
        if (statusEl) statusEl.style.display = 'none';
      } catch (e) {
        if (statusEl) statusEl.textContent = 'chart error: ' + e.message;
      }
    });
  }

  // ─── Inline multi-sensor history chart ──────────────────────────────────────
  // Renders a 24h history chart for SEVERAL sensors into containerEl (no popup,
  // no per-sensor click). Series = sensor × channel; one hidden y-axis per
  // measurement key so same-kind series share a scale. Used by the AoT_map bay
  // modal; reusable by any widget that has runtime fitting_sensors[] entries.
  //
  //   containerEl : target element (content replaced)
  //   sensors     : runtime fitting_sensors[] entries ({device_id, name, channels[]})
  //   opts        : { hours = 24, height = width*0.62 (180..320 clamp) }
  function renderHistory(containerEl, sensors, opts) {
    opts = opts || {};
    containerEl.innerHTML =
      '<div class="aot-spop-inline-chart" style="width:100%;"></div>' +
      '<div class="aot-sensor-popup-chart-status">loading…</div>';
    var chartEl  = containerEl.querySelector('.aot-spop-inline-chart');
    var statusEl = containerEl.querySelector('.aot-sensor-popup-chart-status');

    var jobs = [];
    var nameSet = {};
    (sensors || []).forEach(function (s) {
      if (!s || !s.device_id) return;
      nameSet[s.name || s.fitting_id || ''] = true;
      (s.channels || []).forEach(function (ch) {
        if (ch && ch.measurement_id) jobs.push({ sensor: s, ch: ch });
      });
    });
    if (!jobs.length) {
      statusEl.textContent = _t('No Measurements');
      return;
    }
    var multiSensor = Object.keys(nameSet).length > 1;
    var past = Math.round((opts.hours || 24) * 3600);
    var _rNowMs = Date.now();
    var _rMinMs = _rNowMs - past * 1000;

    var requests = jobs.map(function (j) {
      var url = '/past/' + encodeURIComponent(j.sensor.device_id) +
                '/input/' + encodeURIComponent(j.ch.measurement_id) +
                '/' + past;
      return fetch(url).then(function (r) { return r.ok ? r.json() : null; })
                       .catch(function () { return null; });
    });

    Promise.all(requests).then(function (responses) {
      var axisIndex = {}, axisCount = 0;
      var series = [];
      responses.forEach(function (rows, i) {
        if (!rows || !Array.isArray(rows) || !rows.length) return;
        var j = jobs[i];
        var data = rows.map(function (row) {
          if (row[1] == null) return null;
          var t = (typeof row[0] === 'number') ? row[0] * 1000 : new Date(row[0]).getTime();
          return [t, +row[1]];
        }).filter(function (p) { return p != null && !isNaN(p[0]) && !isNaN(p[1]); })
          .sort(function (a, b) { return a[0] - b[0]; });
        if (!data.length) return;
        var key = j.ch.key || j.ch.measurement_type || '?';
        if (axisIndex[key] == null) axisIndex[key] = axisCount++;
        var disp = _KEY_DISPLAY[key] || key;
        series.push({
          name: (multiSensor ? (j.sensor.name || '') + ' ' : '') + disp,
          data: data,
          yAxis: axisIndex[key],
          tooltip: { valueSuffix: ' ' + (j.ch.unit || '') }
        });
      });

      if (!series.length) {
        statusEl.textContent = 'no data in last 24h';
        return;
      }

      _ensureHighcharts().then(function (ok) {
        if (!ok || !window.Highcharts) {
          statusEl.textContent = 'Highcharts load failed';
          return;
        }
        if (window.AoTChart && window.AoTChart.applyGlobalDefaults) {
          window.AoTChart.applyGlobalDefaults();
        }
        requestAnimationFrame(function () {
          var w = chartEl.offsetWidth || 300;
          var h = opts.height ||
                  Math.max(180, Math.min(320, Math.round(w * 0.62)));
          var yAxes = [];
          for (var a = 0; a < axisCount; a++) {
            yAxes.push({ title: { text: null }, labels: { enabled: false },
                         opposite: a % 2 === 1 });
          }
          try {
            // 차트 인스턴스를 컨테이너에 노출 — 맵 팝업의 액추에이터
            // 오버레이(시리즈 추가)가 접근한다. 기존 동작 불변.
            containerEl._aotChart = window.Highcharts.stockChart(chartEl, {
              colors: _chartColors(),
              chart: { height: h, spacing: [4, 4, 4, 4] },
              rangeSelector: { enabled: false },
              navigator: { enabled: false },
              scrollbar: { enabled: false },
              credits: { enabled: false },
              exporting: { enabled: false },
              navigation: { buttonOptions: { enabled: false } },
              // 레전드: AoT_graph 위젯 기본 구성 — 시리즈명 + 마지막 값(굵게)+단위
              legend: {
                enabled: true,
                useHTML: true,
                labelFormatter: function () {
                  var lastVal = this.yData && this.yData.length
                    ? this.yData[this.yData.length - 1] : null;
                  var unit = (this.tooltipOptions && this.tooltipOptions.valueSuffix) || '';
                  if (lastVal == null) return this.name;
                  return this.name + ': <b>' +
                    window.Highcharts.numberFormat(lastVal, 2) + unit + '</b>';
                },
                itemStyle: { fontSize: '1em' },   // AoT_graph 기본값(1.0em)과 동일
                margin: 4, padding: 2
              },
              xAxis: { type: 'datetime', min: _rMinMs, max: _rNowMs, labels: { style: { fontSize: '9px' } } },
              yAxis: yAxes,
              tooltip: { shared: true, valueDecimals: 2 },
              series: series
            });
            statusEl.style.display = 'none';
          } catch (e) {
            statusEl.textContent = 'chart error: ' + e.message;
          }
        });
      });
    });
  }

  window.AoTSensorLabel = {
    formatChannel: formatChannel,
    formatLabel:   formatLabel,
    openPopup:     openPopup,
    closePopup:    closePopup,
    renderHistory: renderHistory,
    keyDisplay:    function (key) { return _KEY_DISPLAY[key] || key || ''; },
    defaultDecimals: function (key) {
      return _DEFAULT_DECIMALS[key] != null ? _DEFAULT_DECIMALS[key] : 1;
    }
  };
})();
