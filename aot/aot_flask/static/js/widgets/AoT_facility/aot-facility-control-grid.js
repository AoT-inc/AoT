// aot-facility-control-grid.js — IEC § D Actuator Control Grid
(function () {
  'use strict';

  // control_type is provided by the server (routes_geo.py api_facility_runtime)
  // 'pwm' → slider (percent), 'binary' → toggle (on/off)

  // Drag handle (same horizontal 2-line grip icon as the system card sorter).
  var _DRAG_HANDLE =
    '<span class="aot-act-drag-handle" title="' +
    (window._ ? window._('Reorder') : 'Reorder') +
    '"><i class="fa fa-grip-lines"></i></span>';

  function bind(widgetId, facilityUuid, canControl) {
    // Wire EStop / Restore AUTO buttons
    var estopBtn   = document.getElementById('iec-estop-'   + widgetId);
    var restoreBtn = document.getElementById('iec-restore-' + widgetId);

    if (estopBtn) {
      estopBtn.addEventListener('click', function () {
        _handleEstop(widgetId, facilityUuid);
      });
    }
    if (restoreBtn) {
      restoreBtn.addEventListener('click', function () {
        _handleRestore(widgetId, facilityUuid);
      });
    }
  }

  // Called by aot-facility-widget.js after each runtime refresh
  function update(widgetId, facilityUuid, actuatorStates, canControl, outdoorTemp, savedOrder) {
    var tbody = document.getElementById('iec-ctrl-tbody-' + widgetId);
    if (!tbody) return;

    var allSlots = Object.keys(actuatorStates);
    var cached   = window.AoTActuatorOrder && window.AoTActuatorOrder.getCache(facilityUuid);
    var order    = cached || savedOrder || [];
    var slots    = (window.AoTActuatorOrder)
      ? window.AoTActuatorOrder.order(allSlots, order, function (sk) {
          return (actuatorStates[sk] && actuatorStates[sk].name) || sk;
        })
      : allSlots;
    if (!slots.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-muted" style="font-size:var(--aot-fs-caption);padding:0.5rem">No actuators registered</td></tr>';
      return;
    }

    var rows = slots.map(function (slot) {
      var act   = actuatorStates[slot];
      var kind  = act.kind || slot;
      // 'pwm' (duty cycle) and 'value' (position, e.g. actuator_paired window/curtain motor)
      // are both 0-100% proportional control, so render them as sliders. Only pure on/off relays toggle.
      // (Previously only 'pwm' was a slider, so 'value' position actuators were handled as ON/OFF.)
      var isSlider = act.control_type === 'pwm' || act.control_type === 'value';
      // Position actuators use the last specified target (last_target_pct) as the slider base value.
      // During motor travel the current position (percent) differs from the target and the thumb jumps, so prefer the target.
      var pct;
      if (act.control_type === 'value' && act.last_target_pct != null) {
        pct = parseFloat(act.last_target_pct);
      } else {
        pct = act.percent != null ? act.percent : (act.on ? 100 : 0);
      }
      var src   = _srcLabel(act.source || 'auto');

      var valCell, ctrlCell;

      if (canControl) {
        if (isSlider) {
          valCell  = '<td class="iec-act-val">' + pct.toFixed(0) + '%</td>';
          ctrlCell = '<td><input type="range" class="iec-act-slider" min="0" max="100" step="1"' +
                     ' value="' + pct.toFixed(0) + '"' +
                     ' data-slot="' + _esc(slot) + '"' +
                     ' data-kind="' + _esc(kind) + '"' +
                     ' data-outdoor-temp="' + (outdoorTemp != null ? outdoorTemp : '') + '"' +
                     '></td>';
        } else {
          var chk = act.on ? 'checked' : '';
          valCell  = '<td class="iec-act-val">' + (act.on ? 'ON' : 'OFF') + '</td>';
          ctrlCell = '<td><label class="iec-act-toggle">' +
                     '<input type="checkbox" ' + chk +
                     ' data-slot="' + _esc(slot) + '"' +
                     ' data-kind="' + _esc(kind) + '">' +
                     '<span class="slider"></span></label></td>';
        }
      } else {
        valCell  = '<td class="iec-act-val">' + (isSlider ? pct.toFixed(0) + '%' : (act.on ? 'ON' : 'OFF')) + '</td>';
        ctrlCell = '';
      }

      var colspan = canControl ? '' : ' colspan="3"';
      return '<tr data-slot="' + _esc(slot) + '">' +
             '<td class="iec-act-name">' + (canControl ? _DRAG_HANDLE : '') + _esc(act.name || slot) + '</td>' +
             ctrlCell +
             valCell +
             '<td><span class="iec-act-src ' + src.cls + '">' + src.label + '</span></td>' +
             '</tr>';
    });

    tbody.innerHTML = rows.join('');

    // Row drag-reordering (edit-permitted users only). On drop, save the new order to the server.
    // makeSortable binds listeners only once per container, so the context is stored on tbody
    // for onReorder to reference the latest polled states/order.
    if (canControl && facilityUuid && window.AoTActuatorOrder) {
      tbody._aotOrderCtx = { states: actuatorStates, facilityUuid: facilityUuid, savedOrder: savedOrder || [] };
      window.AoTActuatorOrder.makeSortable(tbody, {
        itemSelector:   'tr[data-slot]',
        handleSelector: '.aot-act-drag-handle',
        onReorder: function (seq) {
          var ctx     = tbody._aotOrderCtx || {};
          var states  = ctx.states || {};
          var fac      = ctx.facilityUuid;
          var saved   = (window.AoTActuatorOrder.getCache(fac)) || ctx.savedOrder || [];
          var newFull = window.AoTActuatorOrder.reorder(Object.keys(states), saved, function (sk) {
            return (states[sk] && states[sk].name) || sk;
          }, seq);
          window.AoTActuatorOrder.save(fac, newFull);
        }
      });
    }

    // Event delegation for sliders and toggles
    tbody.addEventListener('input', _debounce(function (e) {
      var el = e.target;
      if (el.type === 'range') {
        _sendControl(facilityUuid, el.dataset.slot, 'set', parseFloat(el.value),
                     el.dataset.kind, el.dataset.outdoorTemp);
        var row = el.closest('tr');
        if (row) {
          var valEl = row.querySelector('.iec-act-val');
          if (valEl) valEl.textContent = parseFloat(el.value).toFixed(0) + '%';
        }
      }
    }, 500));

    tbody.addEventListener('change', function (e) {
      var el = e.target;
      if (el.type === 'checkbox') {
        _sendControl(facilityUuid, el.dataset.slot, el.checked ? 'on' : 'off',
                     null, el.dataset.kind, null);
        var row = el.closest('tr');
        if (row) {
          var valEl = row.querySelector('.iec-act-val');
          if (valEl) valEl.textContent = el.checked ? 'ON' : 'OFF';
        }
      }
    });
  }

  // Also render read-only view when canControl=false
  function updateReadOnly(widgetId, actuatorStates) {
    update(widgetId, null, actuatorStates, false, null);
  }

  function _sendControl(facilityUuid, slot, action, percent, kind, outdoorTemp) {
    // Client-side guard
    if (kind === 'side_window' && action === 'set' && percent > 50) {
      var ot = parseFloat(outdoorTemp);
      if (!isNaN(ot) && ot < 0) {
        if (!confirm('Safety: outdoor temp ' + ot + '°C — side window >' + percent + '% open. Proceed?')) {
          return;
        }
      }
    }

    fetch('/api/aot/facility/' + facilityUuid + '/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_key: slot, action: action, percent: percent, reason: 'manual' }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) console.warn('[IEC control]', d.message);
      })
      .catch(function (e) { console.error('[IEC control]', e); });
  }

  function _handleEstop(widgetId, facilityUuid) {
    var tbody = document.getElementById('iec-ctrl-tbody-' + widgetId);
    var names = [];
    if (tbody) {
      tbody.querySelectorAll('[data-slot]').forEach(function (row) {
        var nameEl = row.querySelector('.iec-act-name');
        if (nameEl) names.push(nameEl.textContent.trim());
      });
    }

    var msg = 'EMERGENCY STOP\n\nAffected actuators:\n' + names.map(function (n) { return '· ' + n; }).join('\n') +
              '\n\nType "STOP" to confirm:';
    var reply = prompt(msg);
    if (reply !== 'STOP') return;

    fetch('/api/aot/facility/' + facilityUuid + '/estop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: 'STOP' }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) alert('STOP applied: ' + d.applied + ' actuators set to safe state.');
        else alert('STOP failed: ' + (d.message || JSON.stringify(d)));
      })
      .catch(function (e) { alert('STOP error: ' + e); });
  }

  function _handleRestore(widgetId, facilityUuid) {
    if (!confirm('Restore AUTO control? Manual overrides will be released.')) return;
    // Restore AUTO — signal server (no estop, just log intent)
    fetch('/api/aot/facility/' + facilityUuid + '/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_key: '__all__', action: 'off', reason: 'restore_auto' }),
    }).catch(function () {});
    alert('AUTO control restored. Method/PID controllers are now active.');
  }

  function _srcLabel(src) {
    var map = {
      manual: { label: 'MANUAL', cls: 'iec-src-manual' },
      ai:     { label: 'AI',     cls: 'iec-src-ai'     },
      auto:   { label: 'AUTO',   cls: 'iec-src-auto'   },
      ext:    { label: 'EXT',    cls: 'iec-src-ext'    },
    };
    return map[src] || map.auto;
  }

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function _debounce(fn, ms) {
    var timer;
    return function () {
      var ctx = this, args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  window.AoTFacilityControlGrid = { bind: bind, update: update, updateReadOnly: updateReadOnly };
})();
