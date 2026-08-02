// weather-ui.js — extracted from templates/pages/geo/geo_facility.html (2026-07-31).
// WeatherUI — weather/forecast channel bindings.
// Loaded as part of the geo-facility bundle, after aot-facility-design.js,
// so FittingsUI/EnvelopeUI and the _IEC/_COMM string catalogs already exist.

/* ── WeatherUI — weather/forecast binding tab ──────────────────────────────
   Edits facility.weather_bindings.
   Each item: {id, name, measurement_type, input_uuid, measurement_id}
   On save, collected via FacilityUI.readWeatherBindings() and included in the payload.
──────────────────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  var _bindings = [];  // [{id, name, measurement_type, input_uuid, measurement_id}]

  var FORECAST_TYPES = [
    { value: 'forecast_temperature',        label: (window._ ? window._('Temperature (°C)') : 'Temperature (°C)') },
    { value: 'forecast_humidity',           label: (window._ ? window._('Humidity (%)') : 'Humidity (%)') },
    { value: 'forecast_wind_speed',         label: (window._ ? window._('Wind speed (m/s)') : 'Wind speed (m/s)') },
    { value: 'forecast_precipitation_prob', label: (window._ ? window._('Precipitation probability (%)') : 'Precipitation probability (%)') },
    { value: 'forecast_precipitation',      label: (window._ ? window._('Precipitation (mm)') : 'Precipitation (mm)') },
    { value: 'forecast_solar',              label: (window._ ? window._('Solar radiation (W/m²)') : 'Solar radiation (W/m²)') },
  ];

  function _uid() {
    return 'wb-' + Math.random().toString(36).slice(2, 9);
  }

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                           .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* Inject binding list from outside (on FacilityUI.fill() call) */
  function fill(bindings) {
    _bindings = (bindings || []).map(function (b) {
      return {
        id:               b.id || _uid(),
        name:             b.name || '',
        measurement_type: b.measurement_type || '',
        input_uuid:       b.input_uuid || '',
        measurement_id:   b.measurement_id || '',
      };
    });
    render();
  }

  /* Called on save — returns current state */
  function read() {
    return _bindings.map(function (b) {
      return {
        name:             b.name,
        measurement_type: b.measurement_type,
        input_uuid:       b.input_uuid,
        measurement_id:   b.measurement_id,
      };
    });
  }

  /* Build channel-selection <option> HTML (_inputChoices is shared with SensorUI) */
  function _channelOptHtml(curInputId, curMeasId) {
    var curVal = curInputId && curMeasId ? curInputId + ',' + curMeasId : '';
    var opts = ['<option value="">' + (window._ ? window._('— Select Input channel —') : '— Select Input channel —') + '</option>'];
    if (typeof _inputChoices !== 'undefined') {
      _inputChoices.forEach(function (ch) {
        var sel = ch.value === curVal ? ' selected' : '';
        opts.push('<option value="' + _esc(ch.value) + '"' + sel + '>' + _esc(ch.item) + '</option>');
      });
    }
    return opts.join('');
  }

  /* Build measurement-item <option> HTML */
  function _typeOptHtml(curType) {
    return FORECAST_TYPES.map(function (t) {
      var sel = t.value === curType ? ' selected' : '';
      return '<option value="' + _esc(t.value) + '"' + sel + '>' + _esc(t.label) + '</option>';
    }).join('');
  }

  function render() {
    var tbody    = document.getElementById('weather-config-tbody');
    var emptyRow = document.getElementById('weather-config-empty');
    if (!tbody) return;

    Array.from(tbody.querySelectorAll('tr[data-wb-id]')).forEach(function (tr) {
      tbody.removeChild(tr);
    });
    if (emptyRow) emptyRow.style.display = _bindings.length ? 'none' : '';

    _bindings.forEach(function (b) {
      var tr = document.createElement('tr');
      tr.dataset.wbId = b.id;
      tr.style.cssText = 'border-bottom:1px solid var(--aot-border-light);';

      tr.innerHTML =
        '<td style="padding:5px 8px;">' +
          '<input type="text" data-field="name" value="' + _esc(b.name) + '" ' +
            'class="aot-modern-input" ' +
            'placeholder="' + (window._ ? window._('Service name') : 'Service name') + '">' +
        '</td>' +
        '<td style="padding:5px 8px;">' +
          '<select data-field="measurement_type" style="width:100%;font-size:var(--aot-font-size-sm);">' +
            _typeOptHtml(b.measurement_type) +
          '</select>' +
        '</td>' +
        '<td style="padding:5px 8px;">' +
          '<select data-channel style="width:100%;font-size:var(--aot-font-size-sm);">' +
            _channelOptHtml(b.input_uuid, b.measurement_id) +
          '</select>' +
        '</td>' +
        '<td style="padding:5px 8px;text-align:center;">' +
          '<button type="button" data-del ' +
            'class="btn aot-pill-btn aot-pill-btn-primary" ' +
            'title="' + (window._ ? window._('Delete') : 'Delete') + '">X</button>' +
        '</td>';

      tbody.appendChild(tr);

      /* Edit name */
      tr.querySelector('[data-field="name"]').addEventListener('input', function (e) {
        e.stopPropagation();
        var bv = _binding(b.id); if (!bv) return;
        bv.name = e.target.value;
        _dispatch();
      });

      /* Select measurement item */
      tr.querySelector('[data-field="measurement_type"]').addEventListener('change', function (e) {
        e.stopPropagation();
        var bv = _binding(b.id); if (!bv) return;
        bv.measurement_type = e.target.value;
        _dispatch();
      });

      /* Select Input channel */
      tr.querySelector('[data-channel]').addEventListener('change', function (e) {
        e.stopPropagation();
        var bv = _binding(b.id); if (!bv) return;
        var parts = (e.target.value || '').split(',');
        bv.input_uuid    = parts[0] || '';
        bv.measurement_id = parts[1] || '';
        _dispatch();
      });

      /* Delete */
      tr.querySelector('[data-del]').addEventListener('click', function (e) {
        e.stopPropagation();
        _bindings = _bindings.filter(function (x) { return x.id !== b.id; });
        render();
        _dispatch();
      });
    });
  }

  function _binding(id) {
    return _bindings.find(function (x) { return x.id === id; }) || null;
  }

  function _dispatch() {
    document.dispatchEvent(new CustomEvent('weather-bindings-changed'));
  }

  function _addBinding() {
    _bindings.push({
      id: _uid(), name: '', measurement_type: '', input_uuid: '', measurement_id: '',
    });
    render();
    _dispatch();
  }

  function init() {
    var addBtn = document.getElementById('btn-weather-add');
    if (addBtn) addBtn.addEventListener('click', _addBinding);

    // Step bar replaced the old config tabs — refresh when this step opens.
    var tabBtn = document.querySelector('.fac-step[data-step="connect"]');
    if (tabBtn) tabBtn.addEventListener('click', render);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.WeatherUI = { fill: fill, read: read, render: render };
})();
