// aot-facility-status.js — IEC § 0 Status Strip  v2
// Polls /api/aot/facility/<uuid>/status every 5 seconds.
// start(widgetId, facilityUuid, functionUuid) — functionUuid forwarded as query param.
(function () {
  'use strict';

  var _timers = {};

  function start(widgetId, facilityUuid, functionUuid) {
    if (_timers[widgetId]) return;

    var baseUrl = '/api/aot/facility/' + facilityUuid + '/status';
    var url = functionUuid ? baseUrl + '?function_uuid=' + encodeURIComponent(functionUuid) : baseUrl;

    function _tick() {
      fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (d) { _render(widgetId, d); })
        .catch(function () { _renderError(widgetId); });
    }

    _tick();
    _timers[widgetId] = setInterval(_tick, 5000);
  }

  function stop(widgetId) {
    clearInterval(_timers[widgetId]);
    delete _timers[widgetId];
  }

  function _render(widgetId, data) {
    var badge   = document.getElementById('iec-badge-' + widgetId);
    var reasons = document.getElementById('iec-reasons-' + widgetId);
    var ts      = document.getElementById('iec-ts-' + widgetId);
    if (!badge) return;

    var level = data.level || 'idle';
    badge.className = 'iec-badge ' + level;
    badge.textContent = level.toUpperCase();

    if (reasons) {
      var parts = [];
      if (data.function_name) parts.push(data.function_name);
      if (data.function_stale) parts.push(window._ ? window._('No response') : 'No response');
      var reasonList = data.reasons || [];
      reasonList.forEach(function (r) { parts.push(r); });
      reasons.textContent = parts.join(' · ');
    }

    if (ts) {
      var suffix = (data.active_count != null)
        ? ' · ' + data.active_count + '/' + data.total_count + ' active'
        : '';
      ts.textContent = new Date().toLocaleTimeString() + suffix;
    }
  }

  function _renderError(widgetId) {
    var badge = document.getElementById('iec-badge-' + widgetId);
    if (!badge) return;
    badge.className = 'iec-badge idle';
    badge.textContent = 'ERR';
    var ts = document.getElementById('iec-ts-' + widgetId);
    if (ts) ts.textContent = (window._ ? window._('Connection error') : 'Connection error');
  }

  window.AoTFacilityStatus = { start: start, stop: stop };
})();
