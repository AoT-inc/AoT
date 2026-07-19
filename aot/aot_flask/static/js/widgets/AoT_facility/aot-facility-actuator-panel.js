// aot-facility-actuator-panel.js
// Actuator group panel for AoT_facility widget.
//
// Actuators are grouped by kind (Window/Insulation/Shade/Irrigation/Other).
// Each actuator's control UI is determined by its output_type:
//   'value'  → position slider  (actuator_paired)
//   'pwm'    → duty_cycle slider
//   'wired'  / 'command' / other → ON / OFF buttons
//
// Public API:
//   AoTActuatorPanel.attach(widgetId, containerEl, facilityUuid, canControl)
//   AoTActuatorPanel.update(widgetId, actuatorStates, savedOrder?)
//   AoTActuatorPanel.detach(widgetId)
(function () {
  'use strict';

  var _KIND_GROUP = {
    'opening':   'Window',
    'curtain':   'Insulation',
    'shade':     'Shade',
    'irrigation':'Irrigation',
  };
  var _GROUPS_ORDER = ['Window', 'Insulation', 'Shade', 'Irrigation', 'Other'];

  // Localized display labels for the internal group keys above.
  var _GROUP_LABEL = {
    'Window':     (window._ ? window._('Window') : 'Window'),
    'Insulation': (window._ ? window._('Insulation') : 'Insulation'),
    'Shade':      (window._ ? window._('Shade') : 'Shade'),
    'Irrigation': (window._ ? window._('Irrigation') : 'Irrigation'),
    'Other':      (window._ ? window._('Other') : 'Other'),
  };

  // Drag handle (same horizontal 2-line grip icon as the system card sorter).
  var _DRAG_HANDLE =
    '<span class="aot-act-drag-handle" title="' +
    (window._ ? window._('Reorder') : 'Reorder') +
    '"><i class="fa fa-grip-lines"></i></span>';

  var STATE = {};

  function _group(kind) {
    return _KIND_GROUP[kind] || 'Other';
  }

  // Map the server-resolved control_type ('value' | 'pwm' | 'binary') to a UI control kind.
  //   value  → position (0-100% position slider, e.g. actuator_paired window/curtain)
  //   pwm    → pwm      (duty cycle slider)
  //   binary → binary   (ON/OFF button)
  // NOTE: previously act.output_type (module name, e.g. 'actuator_paired') was passed, so the
  //       'value' comparison always missed and position actuators were shown as ON/OFF only.
  function _ctrlType(controlType) {
    if (controlType === 'value') return 'position';
    if (controlType === 'pwm')   return 'pwm';
    return 'binary';
  }

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Public ────────────────────────────────────────────────────────────────

  function attach(widgetId, containerEl, facilityUuid, canControl) {
    STATE[widgetId] = {
      containerEl:  containerEl,
      facilityUuid: facilityUuid,
      canControl:   !!canControl,
    };
  }

  function update(widgetId, actuatorStates, savedOrder) {
    var st = STATE[widgetId];
    if (!st || !st.containerEl) return;

    actuatorStates = actuatorStates || {};
    // User-defined order (falls back to natural sort). Prefer the local cache right after a drag.
    if (savedOrder !== undefined) st.savedOrder = savedOrder;
    // Keep the latest states — makeSortable binds only once, so onReorder must reference
    // the current polled states (avoids closure staleness).
    st._states = actuatorStates;
    var cached = window.AoTActuatorOrder && window.AoTActuatorOrder.getCache(st.facilityUuid);
    var order  = cached || st.savedOrder || [];

    var allSlots   = Object.keys(actuatorStates);
    var orderedKeys = (window.AoTActuatorOrder)
      ? window.AoTActuatorOrder.order(allSlots, order, function (sk) {
          return (actuatorStates[sk] && actuatorStates[sk].name) || sk;
        })
      : allSlots;

    var groups = {};
    _GROUPS_ORDER.forEach(function (g) { groups[g] = []; });

    orderedKeys.forEach(function (slotKey) {
      var act = actuatorStates[slotKey];
      if (!act) return;
      var g = _group(act.kind || '');
      groups[g].push({ slotKey: slotKey, act: act });
    });

    var activeGroups = _GROUPS_ORDER.filter(function (g) { return groups[g].length > 0; });

    if (!activeGroups.length) {
      st.containerEl.innerHTML =
        '<div class="aot-act-empty">' +
        (window._ ? window._('No actuators registered') : 'No actuators registered') +
        '</div>';
      return;
    }

    var html = '';
    activeGroups.forEach(function (groupName) {
      html += '<div class="aot-act-group">' +
              '<div class="aot-act-group-header">' +
              _esc(_GROUP_LABEL[groupName] || groupName) + '</div>';
      groups[groupName].forEach(function (item) {
        html += _renderRow(item.slotKey, item.act, st.canControl, st._lastCmd);
      });
      html += '</div>';
    });

    st.containerEl.innerHTML = html;

    _positionCurrentDots(st.containerEl);
    if (st.canControl) {
      _wireEvents(st.containerEl, st.facilityUuid, widgetId);
      _wireSortable(widgetId);
    }
  }

  // Drag-reorder rows within a group (Window/Insulation/...). On drop, merge into the full order and save.
  // onReorder is fixed at first binding, so it always references the latest st._states.
  function _wireSortable(widgetId) {
    var st = STATE[widgetId];
    if (!st || !st.containerEl || !window.AoTActuatorOrder) return;
    window.AoTActuatorOrder.makeSortable(st.containerEl, {
      itemSelector:   '.aot-act-row[data-slot]',
      groupSelector:  '.aot-act-group',
      handleSelector: '.aot-act-drag-handle',
      onReorder: function (seq) {
        var states   = st._states || {};
        var saved    = (window.AoTActuatorOrder.getCache(st.facilityUuid)) || st.savedOrder || [];
        var newFull  = window.AoTActuatorOrder.reorder(Object.keys(states), saved, function (sk) {
          return (states[sk] && states[sk].name) || sk;
        }, seq);
        st.savedOrder = newFull;
        window.AoTActuatorOrder.save(st.facilityUuid, newFull);
      }
    });
  }

  function detach(widgetId) {
    delete STATE[widgetId];
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  function _renderRow(slotKey, act, canControl, lastCmd) {
    var ct      = _ctrlType(act.control_type || act.output_type || 'wired');
    var curPct  = act.percent        != null ? parseFloat(act.percent)        : (act.on ? 100 : 0);
    var lastPct = act.last_target_pct != null ? parseFloat(act.last_target_pct) : null;
    var lastSrc = act.last_target_source || null;
    var name    = _esc(act.name || slotKey);
    var isSlider = (ct === 'position' || ct === 'pwm');
    var isPaired = (ct === 'position');

    if (isSlider) {
      var sliderCls = isPaired ? 'aot-3way-slider' : 'aot-act-slider';
      // thumb priority: JS cache (last command) > user value > system value > current value
      var cachedPct = (lastCmd && lastCmd[slotKey] !== undefined) ? lastCmd[slotKey] : null;
      var thumbPct = isPaired
        ? (cachedPct !== null ? cachedPct
           : (lastPct !== null ? lastPct : curPct))
        : curPct;
      var sliderStyle = isPaired
        ? ' data-current="' + curPct.toFixed(0) + '" style="--aot-current-pct:' + curPct.toFixed(0) + '%"'
        : '';

      // Line 1: name
      var inner = '<span class="aot-act-name">' + name + '</span>';

      // Line 2: target (left, brand) / current (right, muted)  ← order swapped
      if (isPaired && (lastPct !== null || cachedPct !== null)) {
        // Show the last specified target (user or system) and its source.
        var srcLabel = lastSrc === 'manual' ? (window._ ? window._('Manual') : 'Manual') + ' '
                     : lastSrc === 'system' ? (window._ ? window._('System') : 'System') + ' '
                     : (window._ ? window._('Target') : 'Target') + ' ';
        var targetLabel = lastPct !== null ? (srcLabel + lastPct.toFixed(0) + '%')
                        : ((window._ ? window._('Target') : 'Target') + ' ' + thumbPct.toFixed(0) + '%');
        inner += '<div class="aot-act-row-top">' +
                 '<span class="aot-act-val">' + targetLabel + '</span>' +
                 '<span class="aot-act-val-current">' +
                 (window._ ? window._('Current') : 'Current') + ' ' + curPct.toFixed(0) + '%</span>' +
                 '</div>';
      } else {
        inner += '<div class="aot-act-row-top">' +
                 '<span class="aot-act-val">' + curPct.toFixed(0) + '%</span>' +
                 '<span></span></div>';
      }

      // Line 3: slider + current-value tick (actuator_paired only)
      if (canControl) {
        if (isPaired) {
          inner += '<div class="aot-3way-slider-wrap">' +
                   '<input type="range" class="' + sliderCls + '" min="0" max="100" step="1"' +
                   ' value="' + thumbPct.toFixed(0) + '"' +
                   ' data-slot="' + _esc(slotKey) + '" data-ct="' + ct + '"' +
                   sliderStyle + '>' +
                   '<div class="aot-3way-current-dot"></div>' +
                   '</div>';
        } else {
          inner += '<input type="range" class="' + sliderCls + '" min="0" max="100" step="1"' +
                   ' value="' + thumbPct.toFixed(0) + '"' +
                   ' data-slot="' + _esc(slotKey) + '" data-ct="' + ct + '"' +
                   sliderStyle + '>';
        }
      }
      return '<div class="aot-act-row" data-slot="' + _esc(slotKey) + '">' +
             (canControl ? _DRAG_HANDLE : '') + inner + '</div>';
    }

    var ctrl = '';
    if (canControl) {
      ctrl = '<div class="aot-act-toggle-wrap">' +
             '<button class="aot-act-btn' + (act.on ? ' active' : '') + '"' +
             ' data-slot="' + _esc(slotKey) + '" data-action="on">ON</button>' +
             '<button class="aot-act-btn' + (!act.on ? ' active' : '') + '"' +
             ' data-slot="' + _esc(slotKey) + '" data-action="off">OFF</button>' +
             '</div>';
    } else {
      ctrl = '<span class="aot-act-val-ro ' + (act.on ? 'aot-act-on' : 'aot-act-off') + '">' +
             (act.on ? 'ON' : 'OFF') + '</span>';
    }
    return '<div class="aot-act-row" data-slot="' + _esc(slotKey) + '">' +
           (canControl ? _DRAG_HANDLE : '') +
           '<span class="aot-act-name">' + name + '</span>' +
           ctrl +
           '</div>';
  }

  // ── Dot positioning ──────────────────────────────────────────────────────
  // Current-value circular dot position: apply the thumb radius (8px) as padding on both sides.
  // left = thumbR + (cur/100) * (wrapW - thumbD)

  function _positionCurrentDots(containerEl) {
    var THUMB_R = 8; // .aot-3way-slider thumb radius (16px / 2)
    containerEl.querySelectorAll('.aot-3way-slider[data-current]').forEach(function (slider) {
      var dot  = slider.parentElement && slider.parentElement.querySelector('.aot-3way-current-dot');
      if (!dot) return;
      var cur  = parseFloat(slider.dataset.current || 0);
      var wrap = slider.parentElement;
      var w    = wrap.offsetWidth;
      if (!w) {
        requestAnimationFrame(function () { _positionCurrentDots(containerEl); });
        return;
      }
      dot.style.left = (THUMB_R + (cur / 100) * (w - THUMB_R * 2)) + 'px';
    });
  }

  // ── Events ────────────────────────────────────────────────────────────────

  function _wireEvents(containerEl, facilityUuid, widgetId) {
    // Slider: show % while dragging + the Actuator Paired slider also updates the track fill
    containerEl.addEventListener('input', function (e) {
      var el = e.target;
      if (!el.classList.contains('aot-act-slider') &&
          !el.classList.contains('aot-3way-slider')) return;
      var v = parseFloat(el.value);
      var row = el.closest('.aot-act-row');
      var valEl = row && row.querySelector('.aot-act-val');
      if (valEl) valEl.textContent = v.toFixed(0) + '%';
    });

    // Slider: send set on mouseup/touchend (common to pwm slider + paired slider)
    containerEl.addEventListener('change', function (e) {
      var el = e.target;
      if (!el.classList.contains('aot-act-slider') &&
          !el.classList.contains('aot-3way-slider')) return;
      var val = parseFloat(el.value);
      // Cache the last command value — preserves thumb position on poll re-render
      var st = STATE[widgetId];
      if (st) {
        st._lastCmd = st._lastCmd || {};
        st._lastCmd[el.dataset.slot] = val;
      }
      _sendControl(facilityUuid, el.dataset.slot, 'set', val);
    });

    // ON/OFF buttons
    containerEl.addEventListener('click', function (e) {
      var btn = e.target.closest('.aot-act-btn');
      if (!btn) return;
      _sendControl(facilityUuid, btn.dataset.slot, btn.dataset.action, null);
      var wrap = btn.closest('.aot-act-toggle-wrap');
      if (wrap) {
        wrap.querySelectorAll('.aot-act-btn').forEach(function (b) {
          b.classList.toggle('active', b === btn);
        });
      }
    });
  }

  function _csrfHeader() {
    // The routes_geo blueprint has CSRF protection enabled — X-CSRFToken is required on POST requests
    var meta = document.querySelector('meta[name="csrf-token"]');
    return (meta && meta.getAttribute('content')) || '';
  }

  // ── API call ──────────────────────────────────────────────────────────────

  function _sendControl(facilityUuid, slotKey, action, percent) {
    fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) + '/control', {
      method:  'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken':  _csrfHeader(),
      },
      body:    JSON.stringify({
        slot_key: slotKey,
        action:   action,
        percent:  percent,
        reason:   'manual',
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (!d.ok) console.warn('[ActuatorPanel]', d.message); })
      .catch(function (e) { console.error('[ActuatorPanel]', e); });
  }

  window.AoTActuatorPanel = { attach: attach, update: update, detach: detach };
})();
