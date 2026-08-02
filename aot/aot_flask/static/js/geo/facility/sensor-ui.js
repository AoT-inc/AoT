// sensor-ui.js — extracted from templates/pages/geo/geo_facility.html (2026-07-31).
// SensorUI — the sensor table in the equipment-layout step, mirroring sensor fittings placed in 3D.
// Loaded as part of the geo-facility bundle, after aot-facility-design.js,
// so FittingsUI/EnvelopeUI and the _IEC/_COMM string catalogs already exist.

(function () {
  'use strict';

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // Every component of the facility, including the ones the envelope generates
  // (roof vents, side windows, curtains). Those used to be excluded, which left
  // them reachable only as an on/off toggle in the envelope step — selecting one
  // in 3D opened nothing, because the placement panel mounts under a table row
  // and they had no row. Irrigation pieces stay out: they are managed as a layer
  // in the 3D tools, not as individual components.
  var _HIDDEN_KINDS = ['irrigation_layer','irrigation_pipe','irrigation_device',
                       'irrigation_valve','irrigation_connection'];
  function _getComponents() {
    if (!window.FittingsUI || !FittingsUI.readAll) return [];
    return FittingsUI.readAll().filter(function (f) {
      return _HIDDEN_KINDS.indexOf(f.kind) === -1;
    });
  }
  function _isEnvelope(f) { return !!f && f.source === 'envelope'; }

  // Components generated together are one instance — an edit to any of them
  // applies to all. The row says so, otherwise a list of 16 roof vents reads as
  // 16 separate things to fill in.
  function _groupNote(f) {
    if (!f || !f.link_group || !window.FittingsUI || !FittingsUI.readAll) return '';
    var n = FittingsUI.readAll().filter(function (g) { return g.link_group === f.link_group; }).length;
    if (n < 2) return '';
    var detached = (f.inherit_size === false) && (f.inherit_actuator === false);
    if (detached) return ' · ' + (window._ ? window._('detached') : 'detached');
    var label = (window._ ? window._('%(n)s linked') : '%(n)s linked').replace('%(n)s', n);
    return ' · ' + label;
  }

  // Kind catalogue for the table. Each entry declares what the row should
  // offer, which is what makes the columns react to the selected type.
  var _KINDS = [
    {v:'sensor',      l:(window._ ? window._('Sensor') : 'Sensor'),           detail:'channel', role:'sensor'},
    {v:'fan',         l:(window._ ? window._('Fan') : 'Fan'),                 detail:'actuator', role:'fan'},
    {v:'heater',      l:(window._ ? window._('Heater') : 'Heater'),           detail:'actuator', role:null},
    {v:'fogger',      l:(window._ ? window._('Humidifier') : 'Humidifier'),   detail:'actuator', role:null},
    {v:'curtain',     l:(window._ ? window._('Curtain') : 'Curtain'),         detail:'actuator', role:null},
    {v:'window',      l:(window._ ? window._('Window') : 'Window'),           detail:'actuator', role:null},
    {v:'side_window', l:(window._ ? window._('Side Window') : 'Side Window'), detail:'actuator', role:null},
    {v:'door',        l:(window._ ? window._('Door') : 'Door'),               detail:'actuator', role:null},
    {v:'fixture',     l:(window._ ? window._('Fixture') : 'Fixture'),         detail:'actuator', role:null}
  ];
  function _kindDef(kind) {
    return _KINDS.filter(function (k) { return k.v === kind; })[0] ||
           {v:kind, l:kind, detail:'actuator', role:null};
  }
  function _kindOptHtml(cur) {
    var known = _KINDS.some(function (k) { return k.v === cur; });
    var opts = _KINDS.map(function (k) {
      return '<option value="' + _esc(k.v) + '"' + (k.v === cur ? ' selected' : '') + '>' + _esc(k.l) + '</option>';
    });
    if (!known && cur) opts.unshift('<option value="' + _esc(cur) + '" selected>' + _esc(cur) + '</option>');
    return opts.join('');
  }
  function _actuatorOptHtml(cur) {
    var list = (window.FittingsUI && FittingsUI.getOutputList) ? FittingsUI.getOutputList() : [];
    var opts = ['<option value="">' + (window._ ? window._('— None —') : '— None —') + '</option>'];
    list.forEach(function (o) {
      opts.push('<option value="' + _esc(o.unique_id) + '"' + (o.unique_id === cur ? ' selected' : '') + '>' +
                _esc(o.name || o.unique_id) + '</option>');
    });
    return opts.join('');
  }
  function _fanRoleOptHtml(cur) {
    var roles = [['circulation_fan', window._ ? window._('Circulation Fan') : 'Circulation Fan'],
                 ['exhaust_fan',     window._ ? window._('Exhaust Fan') : 'Exhaust Fan'],
                 ['intake_fan',      window._ ? window._('Intake Fan') : 'Intake Fan']];
    return roles.map(function (r) {
      return '<option value="' + r[0] + '"' + (r[0] === cur ? ' selected' : '') + '>' + _esc(r[1]) + '</option>';
    }).join('');
  }

  // Channel dropdown HTML — system-standard format: value='{input_id},{meas_id}'.
  // Combine Input + Function choices (distinguished by label)
  var _inputChoices = (window.FAC_INPUT_CHOICES || []).concat(window.FAC_FUNCTION_CHOICES || []);
  var _measIdSlug   = window.FAC_MEAS_ID_SLUG  || {};
  var _MTYPE_MAP = {
    temperature:'temperature', temp:'temperature',
    humidity:'humidity', relative_humidity:'humidity',
    co2:'co2', carbon_dioxide:'co2',
    vpd:'vpd', vapor_pressure_deficit:'vpd',
    light:'light', ppfd:'light', lux:'light', radiation:'light',
    wind_speed:'wind_speed', wind:'wind_speed', speed:'wind_speed',
    wind_direction:'wind_direction', wind_dir:'wind_direction', direction:'wind_direction',
    rain:'rain', rainfall:'rain', rainrate:'rain', precipitation:'rain', length:'rain', depth:'rain',
  };

  var _SENSOR_MTYPE_OPTS = [
    {value: '',               label: (window._ ? window._('— Auto —') : '— Auto —')},
    {value: 'temperature',    label: (window._ ? window._('Temperature') : 'Temperature')},
    {value: 'humidity',       label: (window._ ? window._('Humidity') : 'Humidity')},
    {value: 'co2',            label: 'CO2'},
    {value: 'vpd',            label: (window._ ? window._('Vapor pressure deficit (VPD)') : 'Vapor pressure deficit (VPD)')},
    {value: 'light',          label: (window._ ? window._('Solar radiation') : 'Solar radiation')},
    {value: 'wind_speed',     label: (window._ ? window._('Wind speed') : 'Wind speed')},
    {value: 'wind_direction', label: (window._ ? window._('Wind direction') : 'Wind direction')},
    {value: 'rain',           label: (window._ ? window._('Precipitation') : 'Precipitation')},
  ];
  function _sensorMtypeOptHtml(cur) {
    return _SENSOR_MTYPE_OPTS.map(function (o) {
      return '<option value="' + _esc(o.value) + '"' + (o.value === cur ? ' selected' : '') + '>' + _esc(o.label) + '</option>';
    }).join('');
  }

  function _channelOptHtml(selectedInputId, selectedMeasId) {
    var curVal = (selectedInputId && selectedMeasId) ? (selectedInputId + ',' + selectedMeasId) : '';
    var opts = ['<option value="">' + (window._ ? window._('— Select channel —') : '— Select channel —') + '</option>'];
    _inputChoices.forEach(function (ch) {
      var sel = ch.value === curVal ? ' selected' : '';
      var slug = _measIdSlug[(ch.value || '').split(',')[1]] || '';
      var mtype = _MTYPE_MAP[slug.toLowerCase()] || '';
      opts.push(
        '<option value="' + _esc(ch.value) + '"' + sel +
        ' data-mtype="' + _esc(mtype) + '">' +
        _esc(ch.item) +
        '</option>'
      );
    });
    return opts.join('');
  }

  function _switchTo3d() {
    // Placing a sensor happens on the 3D stage, which the layout step shows.
    if (window.FacilityStep) FacilityStep.set('fittings');
  }

  function _activateSensorTool() {
    var btn = document.querySelector('#facility-3d-tools .tool-btn[data-tool="sensor"]');
    if (btn) btn.click();
  }


  // Active kind tab. Null means "all" — used while nothing is placed yet.
  var _activeKind = null;

  function _renderKindTabs(all) {
    var bar = document.getElementById('fac-kind-tabs');
    if (!bar) return;
    // Only show tabs for kinds that actually exist, so the bar stays short.
    var counts = {};
    all.forEach(function (f) { counts[f.kind] = (counts[f.kind] || 0) + 1; });
    var kinds = _KINDS.filter(function (k) { return counts[k.v]; });
    if (!kinds.length) { bar.innerHTML = ''; _activeKind = null; return; }
    if (!kinds.some(function (k) { return k.v === _activeKind; })) _activeKind = kinds[0].v;

    bar.innerHTML = kinds.map(function (k) {
      // Shared pill button, selected state included — same as the step bar.
      return '<button type="button" class="btn aot-pill-btn fac-kind-tab' +
             (k.v === _activeKind ? ' active aot-pill-btn-primary' : '') +
             '" data-kind="' + _esc(k.v) + '" role="tab">' + _esc(k.l) +
             '<span class="aot-tag">' + counts[k.v] + '</span></button>';
    }).join('');
    Array.prototype.forEach.call(bar.querySelectorAll('.fac-kind-tab'), function (b) {
      b.addEventListener('click', function () {
        _activeKind = b.dataset.kind;
        render();
      });
    });
    _syncAddKind();
  }

  // Adding while viewing a tab should default to that tab's type — otherwise
  // the new item lands in a group you are not looking at.
  function _syncAddKind() {
    var sel = document.getElementById('fac-add-kind');
    if (!sel || !_activeKind) return;
    sel.value = _activeKind;
    // bootstrap-select draws its own button; setting .value alone leaves the
    // visible label showing the previous type.
    if (window.jQuery && jQuery(sel).data('selectpicker')) {
      try { jQuery(sel).selectpicker('render'); } catch (e) { /* not enhanced */ }
    }
  }

  // Move the placement panel to sit directly under the selected row, so the
  // list and its 3D settings stay in one place instead of being separate
  // sections the user has to scroll between.
  function _mountPlacement(tr, f) {
    var insp = document.getElementById('facility-3d-inspector');
    if (!insp || !tr || !tr.parentNode) return;
    var holder = document.createElement('tr');
    holder.className = 'fac-place-row';
    holder.dataset.placeFor = f.id;
    var td = document.createElement('td');
    td.colSpan = 2;
    holder.appendChild(td);
    tr.parentNode.insertBefore(holder, tr.nextSibling);
    td.appendChild(insp);
    insp.style.display = '';
  }

  function _unmountPlacement() {
    var insp = document.getElementById('facility-3d-inspector');
    var host = document.getElementById('fac-place-home');
    if (insp && host && insp.parentNode !== host) host.appendChild(insp);
  }

  function render() {
    var tbody    = document.getElementById('sensor-config-tbody');
    var emptyRow = document.getElementById('sensor-config-empty');
    if (!tbody) return;

    var all = _getComponents();
    _renderKindTabs(all);
    var sensors = _activeKind ? all.filter(function (f) { return f.kind === _activeKind; }) : all;

    // Detach the placement panel before wiping rows so it is never destroyed
    _unmountPlacement();
    Array.from(tbody.querySelectorAll('tr[data-sensor-id], tr.fac-place-row')).forEach(function (tr) { tbody.removeChild(tr); });
    if (emptyRow) emptyRow.style.display = all.length ? 'none' : '';

    sensors.forEach(function (f) {
      var def = _kindDef(f.kind);
      var isSelected = window.FittingsUI && FittingsUI.getSelectedId && FittingsUI.getSelectedId() === f.id;
      var tr = document.createElement('tr');
      tr.dataset.sensorId = f.id;
      tr.style.cssText = 'border-bottom:1px solid var(--aot-border-light);cursor:pointer;';
      if (isSelected) tr.classList.add('is-selected');

      var isEnv = _isEnvelope(f);
      tr.innerHTML =
        '<td style="padding:5px 8px;">' +
          // The envelope owns these names — it regenerates them whenever the
          // cover settings change, so an edit here would not survive.
          (isEnv
            ? '<div>' + _esc(f.label || f.name || def.l) + '</div>' +
              '<span class="fac-cell-note">' +
                (window._ ? window._('From envelope') : 'From envelope') +
                (f._auto_geom === false
                  ? ' · ' + (window._ ? window._('manual size') : 'manual size')
                  : '') +
                _groupNote(f) +
              '</span>'
            : '<input type="text" data-field="name" value="' + _esc(f.name || '') + '" ' +
                'class="aot-modern-input" ' +
                'placeholder="' + _esc(def.l) + '">' +
              (_groupNote(f) ? '<span class="fac-cell-note">' + _groupNote(f).replace(/^ · /, '') + '</span>' : '')) +
        '</td>' +

        // Link: a measurement channel for sensors, an actuator for everything else
        '<td style="padding:5px 8px;">' +
          (def.detail === 'channel'
            ? ((f.channel_measurements && f.channel_measurements.length > 1)
                ? '<span class="fac-cell-note">' +
                    (window._ ? window._('Multiple channels — edit in the inspector') : 'Multiple channels — edit in the inspector') +
                  '</span>'
                : '<select data-channel class="form-control aot-modern-select fac-cell-select">' +
                    _channelOptHtml(f.input_id || '', f.measurement_id || '') +
                  '</select>')
            : '<select data-field="actuator_id" class="form-control aot-modern-select fac-cell-select">' +
                _actuatorOptHtml(f.actuator_id || '') +
              '</select>') +
          (def.role === 'sensor'
            ? '<select data-field="measurement_type" class="form-control aot-modern-select fac-cell-select" style="margin-top:4px;">' +
                _sensorMtypeOptHtml(f.measurement_type || '') +
              '</select>' +
              '<select data-field="sensor_role" class="form-control aot-modern-select fac-cell-select" style="margin-top:4px;">' +
                '<option value="indoor"'  + (f.sensor_role !== 'outdoor' ? ' selected' : '') + '>' + (window._ ? window._('Indoor') : 'Indoor') + '</option>' +
                '<option value="outdoor"' + (f.sensor_role === 'outdoor'  ? ' selected' : '') + '>' + (window._ ? window._('Outdoor') : 'Outdoor') + '</option>' +
              '</select>'
            : def.role === 'fan'
              ? '<select data-field="fan_role" class="form-control aot-modern-select fac-cell-select" style="margin-top:4px;">' +
                  _fanRoleOptHtml(f.fan_role || 'circulation_fan') +
                '</select>'
              : '') +
        '</td>';

      tbody.appendChild(tr);

      // Edit name (envelope rows show a fixed label instead of an input)
      var nameEl = tr.querySelector('[data-field="name"]');
      if (nameEl) {
      nameEl.addEventListener('input', function (e) {
        e.stopPropagation();
        // Patch the model as they type, but do NOT broadcast — the listener
        // re-renders the table and would blow away the focused input.
        if (window.FittingsUI && FittingsUI.patchFitting)
          FittingsUI.patchFitting(f.id, {name: nameEl.value});
      });
      nameEl.addEventListener('change', function (e) {
        e.stopPropagation();
        document.dispatchEvent(new CustomEvent('fittings-data-changed'));
      });
      }

      // Actuator (non-sensor components)
      var actEl = tr.querySelector('[data-field="actuator_id"]');
      if (actEl) {
        actEl.addEventListener('change', function (e) {
          e.stopPropagation();
          if (window.FittingsUI && FittingsUI.patchFitting)
            FittingsUI.patchFitting(f.id, {actuator_id: actEl.value || null});
          document.dispatchEvent(new CustomEvent('fittings-data-changed'));
        });
      }

      // Fan role
      var fanEl = tr.querySelector('[data-field="fan_role"]');
      if (fanEl) {
        fanEl.addEventListener('change', function (e) {
          e.stopPropagation();
          if (window.FittingsUI && FittingsUI.patchFitting)
            FittingsUI.patchFitting(f.id, {fan_role: fanEl.value || 'circulation_fan'});
          document.dispatchEvent(new CustomEvent('fittings-data-changed'));
        });
      }

      // Change location (indoor/outdoor) — sensors only
      var roleEl = tr.querySelector('[data-field="sensor_role"]');
      if (roleEl) roleEl.addEventListener('change', function (e) {
        e.stopPropagation();
        if (window.FittingsUI && FittingsUI.patchFitting)
          FittingsUI.patchFitting(f.id, {sensor_role: roleEl.value || 'indoor'});
        document.dispatchEvent(new CustomEvent('fittings-data-changed'));
      });

      // Channel selection — split value='{input_id},{meas_id}' and store each field
      var chSel   = tr.querySelector('[data-channel]');
      var mtypeSel = tr.querySelector('[data-field="measurement_type"]');
      if (chSel) chSel.addEventListener('change', function (e) {
        e.stopPropagation();
        var parts = (chSel.value || '').split(',');
        var opt   = chSel.options[chSel.selectedIndex];
        var mtype = (opt && opt.dataset.mtype) || '';
        if (window.FittingsUI && FittingsUI.patchFitting)
          FittingsUI.patchFitting(f.id, {
            input_id:       parts[0] || null,
            measurement_id: parts[1] || null,
            measurement_type: mtype || null,
          });
        if (mtypeSel) mtypeSel.value = mtype;
        document.dispatchEvent(new CustomEvent('fittings-data-changed'));
      });

      // Manually set measurement type
      if (mtypeSel) {
        mtypeSel.addEventListener('change', function (e) {
          e.stopPropagation();
          if (window.FittingsUI && FittingsUI.patchFitting)
            FittingsUI.patchFitting(f.id, {measurement_type: mtypeSel.value || null});
          document.dispatchEvent(new CustomEvent('fittings-data-changed'));
        });
      }

      // No per-row 3D/delete buttons: selecting the row already activates the
      // component in the 3D view, and the placement accordion carries Delete.

      // Row click → 3D selection highlight
      tr.addEventListener('click', function (e) {
        // A click on one of the row's own controls is an edit, not a selection.
        // Treating it as one re-rendered the table out from under the control:
        // opening the channel picker destroyed the <select> mid-click, so the
        // list flashed open and vanished.
        if (e.target.closest('input, select, textarea, button, label, .bootstrap-select')) return;
        // FittingsUI.select() toggles, so clicking the already-selected row
        // would clear it and the placement panel would empty for no visible
        // reason. Clicking a row always means "edit this one".
        var cur = (window.FittingsUI && FittingsUI.getSelectedId) ? FittingsUI.getSelectedId() : null;
        if (cur === f.id) return;   // already the selected row — nothing to redraw
        if (window.FittingsUI && FittingsUI.select) FittingsUI.select(f.id);
        Array.from(tbody.querySelectorAll('tr[data-sensor-id]')).forEach(function (r) {
          r.classList.toggle('is-selected', r.dataset.sensorId === f.id);
        });
        // The selection change re-renders the table (fitting-selection-changed),
        // which is what moves the accordion under this row.
        setTimeout(_syncSelectionLabel, 0);
      });

      if (isSelected) _mountPlacement(tr, f);
    });

    // Selected item filtered out by the active tab → keep the panel parked
    if (!tbody.querySelector('tr.fac-place-row')) _unmountPlacement();
    _syncSelectionLabel();
  }


  // Name the component the placement panel is editing — clicking a row changes
  // that panel, and without a label the change reads as a random menu swap.
  // The accordion sits directly under the selected row, which already shows the
  // name and type — repeating them inside the panel was pure duplication.
  function _syncSelectionLabel() { /* intentionally empty */ }

  function _getFitting(id) {
    if (!window.FittingsUI || !FittingsUI.readAll) return null;
    return FittingsUI.readAll().find(function (x) { return x.id === id; }) || null;
  }

  function _addComponent() {
    // Create it outright: arming the 3D tool alone left the button looking
    // dead, because the drawer sits over the scene the user had to click.
    var sel = document.getElementById('fac-add-kind');
    var kind = (sel && sel.value) || 'sensor';
    if (window.FittingsUI && FittingsUI.add) {
      FittingsUI.add(kind);
      render();
      return;
    }
    _switchTo3d();
    setTimeout(_activateSensorTool, 80);
  }

  function _fillAddKinds() {
    var sel = document.getElementById('fac-add-kind');
    if (!sel || sel.options.length) return;
    sel.innerHTML = _KINDS.map(function (k) {
      return '<option value="' + _esc(k.v) + '">' + _esc(k.l) + '</option>';
    }).join('');
  }

  function init() {
    var addBtn = document.getElementById('btn-sensor-add');
    if (addBtn) addBtn.addEventListener('click', _addComponent);
    _fillAddKinds();

    // The accordion's Delete removes the fitting; rebuild the list so the row
    // and its accordion disappear together.
    document.addEventListener('fitting-removed', function () { setTimeout(render, 0); });
    document.addEventListener('fittings-data-changed', _syncSelectionLabel);
    document.addEventListener('fittings-changed', _syncSelectionLabel);
    document.addEventListener('fittings-data-changed', function () {
      var tab = document.getElementById('fac-tab-sensors');
      if (!tab || !tab.classList.contains('active')) return;
      // render() rebuilds the rows and moves the placement panel into the new
      // one, which blurs whatever is focused inside it. The inspector fires on
      // 'input', so redrawing here cost the user their focus after every single
      // keystroke in a size or position field. While the caret is in there the
      // table waits; the 'change' below redraws once the field is committed.
      if (document.activeElement &&
          document.activeElement.closest &&
          document.activeElement.closest('#facility-3d-inspector')) return;
      render();
    });

    // Field committed (blur / Enter) — now it is safe to redraw the row so its
    // summary text catches up.
    document.addEventListener('change', function (e) {
      if (!e.target || !e.target.closest || !e.target.closest('#facility-3d-inspector')) return;
      var tab = document.getElementById('fac-tab-sensors');
      if (tab && tab.classList.contains('active')) setTimeout(render, 0);
    });

    // Selection can change from the 3D view too — clicking a component there
    // selects it, clicking it again clears it. Without this the placement
    // accordion stays open under a row that is no longer selected.
    document.addEventListener('fitting-selection-changed', function () {
      var tab = document.getElementById('fac-tab-sensors');
      if (tab && tab.classList.contains('active')) render();
    });

    document.addEventListener('fitting-added', function (e) {
      if (e.detail && e.detail.fitting && e.detail.fitting.kind === 'sensor') {
        var tab = document.getElementById('fac-tab-sensors');
        if (tab && tab.classList.contains('active')) render();
      }
    });

    // Every route into this step must refresh the table: the step bar, the
    // Next/Prev buttons, 3D selection auto-focus, and the reload that follows
    // a save. The bridge emits fac-step-changed for all of them.
    document.addEventListener('fac-step-changed', function (e) {
      if (!e.detail || e.detail.step === 'fittings') render();
    });
    document.addEventListener('facility-loaded', function () {
      setTimeout(render, 60);
    });
  }

  // Exposed so other modules can refresh the table
  window.SensorUI = { render: render };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
