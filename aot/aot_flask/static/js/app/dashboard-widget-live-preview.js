/**
 * dashboard-widget-live-preview.js
 *
 * Live, auto-saving widget settings — no explicit Save, no page reload.
 *
 *  - Changing an option in a widget's settings modal immediately (debounced)
 *    persists it AND re-renders that widget in place. Closing the modal needs no
 *    Save; a page refresh keeps the change because it is already saved.
 *  - A "되돌리기" (Undo) button restores the widget to the state it was in when
 *    the modal was opened — a safety net for a bad change. It re-saves that
 *    baseline (so it also survives refresh) and resets the option controls.
 *  - The original Save submit button is hidden for these widgets; Enter in a
 *    field no longer triggers a full-page submit.
 *
 * Scoped to LIVE_PREVIEW_TYPES. Chart widgets (REINIT_TYPES) also re-run their
 * idempotent js_ready_end init script to redraw with the new options.
 *
 * Keying: settings modal (#modal_config_<uid>) and widget wrapper
 * (#gridstack_widget_<uid>) are both keyed by widget unique_id, so they pair up
 * even after fixModalZIndex() reparents the modal onto <body>.
 */
(function () {
  'use strict';
  if (typeof window.jQuery === 'undefined') { return; }
  var $ = window.jQuery;

  var LIVE_PREVIEW_TYPES = [
    // SAFE-SWAP: server-rendered display body, JS only fills values by id — a body
    // swap is enough; the existing polling interval keeps writing to the new nodes.
    'widget_measurement', 'widget_measurement_multi', 'widget_indicator',
    'widget_spacer', 'widget_python_code', 'widget_function_status',
    'AoT_weather_fcst_announcement', 'AoT_camera', 'widget_camera',
    // REINIT: body is a chart/interactive canvas rebuilt by an idempotent
    // js_ready_end (destroys prior instance / clears its intervals before rebuild).
    'AoT_gauge_angular', 'AoT_graph', 'AoT_wind_angular',
    'AoT_timer', 'widget_trigger_sequence',
    // Interactive widgets made idempotent (interval stores + namespaced/delegated
    // handler rebinds + chart/instance destroy before rebuild).
    'widget_notice', 'AoT_pid', 'widget_calendar',
    // Legacy Highcharts widgets (same idempotent preamble as AoT_gauge/graph).
    'widget_gauge_angular', 'widget_gauge_solid', 'widget_graph_synchronous',
    // Controllers / PWM slider / advice: interval stores + document-delegated
    // (or namespaced .off().on()) handlers that survive a body swap. ai_insight
    // uses inline onclick + global fns only, so a plain body swap suffices.
    'widget_output_pwm_slider', 'widget_controller_activate_deactivate',
    'AoT_controller_act_deact', 'AoT_advice', 'AoT_ai_insight'
  ];
  // Widgets whose body is filled by a js_ready_end init script (chart/interactive),
  // so swapping the body isn't enough — the returned (idempotent) js_ready_end must
  // be re-executed to redraw with the new options. Each of these re-runs cleanly:
  // destroys the prior chart/instance and/or clears its stored intervals + handlers.
  var REINIT_TYPES = [
    'AoT_gauge_angular', 'AoT_graph', 'AoT_wind_angular',
    'AoT_timer', 'widget_trigger_sequence',
    'widget_notice', 'AoT_pid', 'widget_calendar',
    'widget_gauge_angular', 'widget_gauge_solid', 'widget_graph_synchronous',
    // Re-run js_ready_end to restart polling / rebind delegated handlers with the
    // new options. (AoT_ai_insight is NOT here: its js_ready_end is empty; a body
    // swap alone suffices.)
    'widget_output_pwm_slider', 'widget_controller_activate_deactivate',
    'AoT_controller_act_deact', 'AoT_advice'
  ];
  var DEBOUNCE_MS = 450;

  var timers = {};          // uid -> debounce timer id
  var seq = {};             // uid -> monotonically increasing request id (stale-guard)
  var suppress = {};        // uid -> suppress change->autosave (during programmatic field reset)
  var baselineData = {};    // uid -> form serialization at open (for undo POST)
  var baselineSnap = {};    // uid -> [[el, value|checked], ...] at open (for undo field reset)
  var lastToastAt = 0;

  function formOf(uid) { return document.getElementById('mod_widget_form_' + uid); }

  function widgetTypeOf(uid) {
    var form = formOf(uid);
    if (!form) { return null; }
    var t = form.querySelector('input[name="widget_type"]');
    return t ? t.value : null;
  }

  function containerOf(uid) {
    var wrap = document.getElementById('gridstack_widget_' + uid);
    return wrap ? wrap.querySelector('[id^="container-graph-"]') : null;
  }

  function fieldValue(form, name) {
    var el = form ? form.querySelector('input[name="' + name + '"]') : null;
    return el ? el.value : '';
  }

  function toast(msg, kind) {
    if (!window.showToast) { return; }
    var now = (new Date()).getTime();
    if (now - lastToastAt < 1200) { return; }   // throttle auto-save chatter
    lastToastAt = now;
    window.showToast(msg, kind || 'success');
  }

  // Preserve the text of leaf data elements (value/timestamp spans, etc.) across a
  // body swap so the currently-shown reading doesn't blank until the next tick.
  function snapshotDynamicText(container) {
    var map = {};
    container.querySelectorAll('[id]').forEach(function (el) {
      if (el.children.length === 0 && el.textContent.trim() !== '') {
        map[el.id] = el.innerHTML;
      }
    });
    return map;
  }

  function restoreDynamicText(container, map) {
    Object.keys(map).forEach(function (id) {
      var el = container.querySelector('[id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
      if (el && el.textContent.trim() === '') { el.innerHTML = map[id]; }
    });
  }

  // innerHTML insertion does NOT execute inline <script> nodes; replace each so
  // the browser runs it (mirrors output.html initNewWidgetScripts).
  function reexecScripts(container) {
    container.querySelectorAll('script').forEach(function (old) {
      var s = document.createElement('script');
      if (old.src) { s.src = old.src; } else { s.textContent = old.textContent; }
      old.parentNode.replaceChild(s, old);
    });
  }

  function swapBody(container, html) {
    var dyn = snapshotDynamicText(container);
    container.innerHTML = html;
    restoreDynamicText(container, dyn);
    reexecScripts(container);
  }

  // Run a script string in global scope so it can reach the page's top-level
  // `widget`/`Highcharts`/`AoTChart` bindings (a classic <script> shares the
  // global lexical environment).
  function execGlobalScript(text) {
    if (!text || !text.trim()) { return; }
    var s = document.createElement('script');
    // Wrap in an IIFE to match how dashboard_entry.html runs js_ready_end (inside
    // a $(document).ready(function(){...}) callback): this scopes top-level
    // var/const/function the same way AND makes a top-level `return;` (some
    // widgets guard with one) valid instead of a SyntaxError. Assignments to the
    // page's global `widget[]` still resolve to the outer binding from inside.
    s.textContent = '(function(){\n' + text + '\n})();';
    document.body.appendChild(s);
    s.parentNode.removeChild(s);
  }

  function applyFragment(uid, type, data) {
    var container = containerOf(uid);
    if (!container || !data || typeof data.html !== 'string') { return; }
    swapBody(container, data.html);
    if (REINIT_TYPES.indexOf(type) !== -1 && typeof data.js_ready_end === 'string') {
      execGlobalScript(data.js_ready_end);
    }
    if (data.name != null) {
      var titleEl = document.querySelector(
        '#gridstack_widget_' + uid + ' .widget-title .aot-w-title, ' +
        '#gridstack_widget_' + uid + ' .widget-title .widget-title-bar');
      if (titleEl) { titleEl.textContent = data.name; }
    }
  }

  // Persist the current (or given) form state via the real save path and re-render
  // in place. `data` overrides the form serialization (used by undo). A per-uid
  // sequence guards against an earlier request landing after a later one.
  function save(uid, type, data, onOk) {
    var form = formOf(uid);
    if (!form) { return; }
    var mySeq = (seq[uid] = (seq[uid] || 0) + 1);
    $.ajax({
      type: 'POST',
      url: form.getAttribute('action'),
      headers: { 'X-CSRFToken': fieldValue(form, 'csrf_token') },
      data: (data != null ? data : $(form).serialize()) + '&widget_mod=1&ajax_live=1',
      success: function (resp) {
        if (mySeq !== seq[uid]) { return; }   // a newer save superseded this one
        applyFragment(uid, type, resp);
        if (typeof onOk === 'function') { onOk(resp); }
      },
      error: function () { toast('저장 실패', 'error'); }
    });
  }

  function scheduleAutoSave(uid, type) {
    clearTimeout(timers[uid]);
    timers[uid] = setTimeout(function () {
      save(uid, type, null, function () { toast('저장됨', 'success'); });
    }, DEBOUNCE_MS);
  }

  function captureFields(form) {
    var snap = [];
    form.querySelectorAll('input, select, textarea').forEach(function (el) {
      var isToggle = (el.type === 'checkbox' || el.type === 'radio');
      snap.push([el, isToggle ? el.checked : el.value]);
    });
    return snap;
  }

  // Reset option controls to a captured snapshot WITHOUT re-triggering autosave.
  function restoreFields(uid, snap) {
    suppress[uid] = true;
    try {
      snap.forEach(function (p) {
        var el = p[0];
        if (el.type === 'checkbox' || el.type === 'radio') {
          if (el.checked !== p[1]) { el.checked = p[1]; }
        } else if (el.value !== p[1]) {
          el.value = p[1];
        }
      });
      if ($.fn.selectpicker) {
        $(formOf(uid)).find('.selectpicker').selectpicker('refresh');
      }
    } finally {
      suppress[uid] = false;
    }
  }

  // Undo: restore the widget to the state it had when the modal was opened, and
  // persist that baseline so it also survives a refresh.
  function undo(uid, type) {
    if (baselineData[uid] == null) { return; }
    clearTimeout(timers[uid]);
    save(uid, type, baselineData[uid], function () {
      toast('되돌렸습니다', 'info');
    });
    if (baselineSnap[uid]) { restoreFields(uid, baselineSnap[uid]); }
  }

  // Inject a "되돌리기" button into the modal footer and hide the now-redundant
  // Save submit button (changes auto-save).
  function setupFooter(uid, type, modal) {
    var footer = modal.querySelector('.modal-footer');
    var saveBtn = document.getElementById('widget_mod_' + uid);
    if (saveBtn) { saveBtn.style.display = 'none'; }
    if (!footer || footer.querySelector('.aot-live-undo')) { return; }
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn aot-pill-btn aot-pill-btn-primary aot-live-undo';
    btn.textContent = '되돌리기';
    btn.title = '이 설정 창을 연 시점으로 되돌립니다';
    btn.addEventListener('click', function () { undo(uid, type); });
    footer.insertBefore(btn, footer.firstChild);
  }

  $(document).on('shown.bs.modal', function (ev) {
    var modal = ev.target;
    var m = /^modal_config_(.+)$/.exec(modal.id || '');
    if (!m) { return; }
    var uid = m[1];
    var type = widgetTypeOf(uid);
    if (LIVE_PREVIEW_TYPES.indexOf(type) === -1) { return; }
    if (modal.dataset.livePreviewBound === '1') { return; }

    var form = formOf(uid);
    var container = containerOf(uid);
    if (!form || !container) { return; }

    // Baseline = state at open, for the undo safety net.
    baselineData[uid] = $(form).serialize();
    baselineSnap[uid] = captureFields(form);

    // Auto-save on any option change (debounced).
    $(form).on('change.livePreview input.livePreview',
      'input, select, textarea', function () {
        if (suppress[uid]) { return; }
        scheduleAutoSave(uid, type);
      });

    // Enter (or the hidden widget_mod submit) must not trigger a full-page POST;
    // changes already auto-save. Delete/Duplicate submits are left to default.
    $(form).on('submit.livePreview', function (e) {
      var submitter = e.originalEvent && e.originalEvent.submitter;
      var name = submitter ? submitter.getAttribute('name') : null;
      if (name === 'widget_duplicate' || name === 'widget_delete') { return; }
      e.preventDefault();
      $(modal).modal('hide');
    });

    setupFooter(uid, type, modal);
    modal.dataset.livePreviewBound = '1';
  });

  // =========================================================================
  // AoT_map: partial auto-save of SAFE options only.
  //
  // The map is a maplibre WebGL widget and is deliberately NOT in
  // LIVE_PREVIEW_TYPES — a body swap would tear down the GL context (its
  // teardown, destroyAoTMapVectorWidget, is never called on swap). So instead of
  // re-rendering, a changed SAFE option is persisted on its own via
  // /save_widget_custom_options (arbitrary partial merge — the same endpoint the
  // in-map layer/lock/label toggles already use), with no reload and no map
  // rebuild. A few options reachable from outside the map bundle are also applied
  // live (camera via the public map API; label master via the instance-exposed
  // inst._setLabel). DESTRUCTIVE options (map source / mode) are left to the Save
  // button. `map_uuid` is NEVER sent in a partial save (it would reset the view).
  // =========================================================================
  // [Simplification] max_measure_age/input_update_interval/label_spacing/
  // popup_default_tab/most sensor_label_* were removed from the settings form
  // (constant-ized in maps.py widget_vars) and dropped from here too — no form
  // field means this list entry would just never match. show_labels/
  // ai_advice_enabled/period/overlay_data_only are now the "basic view" and are
  // safe/non-destructive, so they belong here same as before.
  var MAP_SAFE_KEYS = {
    period: 1,
    fallback_latitude: 1, fallback_longitude: 1,
    default_zoom: 1, default_pitch: 1, default_bearing: 1,
    active_layers: 1, selected_base_layer: 1, ai_advice_enabled: 1,
    show_labels: 1, overlay_data_only: 1,
    enable_label_collision: 1,
    global_label_size: 1, label_priority_facility: 1,
    sensor_label_style: 1, sensor_popup_enabled: 1,
    show_site_shape: 1, show_zone_shape: 1, show_facility_shape: 1,
    show_equipment_shape: 1, show_device_shapes: 1, show_drawn_shapes: 1,
    device_shape_opacity: 1,
    // Live-capable via the map's own maplibre API (setTerrain), so auto-saved too.
    enable_3d_terrain: 1,
    // Device Filter + Measurement Panel — previously excluded (only took effect
    // after the full Save button / page reload). Both are live-appliable via
    // instance hooks the map exposes (_fetchAndRenderDevices /
    // _refreshMeasurementPanel — see mapLiveApply below), so they belong here now.
    device_selection_input: 1, device_selection_output: 1, device_selection_function: 1,
    measurements_input: 1, measurements_output: 1, measurements_function: 1
  };

  var DEVICE_SELECTION_KEYS = {
    device_selection_input: 1, device_selection_output: 1, device_selection_function: 1
  };
  var MEASUREMENT_PANEL_KEYS = {
    measurements_input: 1, measurements_output: 1, measurements_function: 1
  };

  // Modal show_*_shape option key -> the map's internal shape-category key (_CAT_DEFS).
  var MAP_SHAPE_CAT = {
    show_site_shape: 'land', show_zone_shape: 'zone', show_facility_shape: 'facility',
    show_equipment_shape: 'equipment', show_device_shapes: 'device', show_drawn_shapes: 'drawn'
  };

  // Options _sensorLabelOpts() (aot-map-widget-vector.js) reads to build the sensor
  // marker re-attach config — one re-attach call live-applies all of these.
  // [Simplification] Sub-keys without a form field anymore (max_channels/decimals/
  // size/bg/fg/offset_y/opacity/label_spacing — now fixed constants in maps.py)
  // removed; _sensorLabelOpts() still reads them off the instance vars with its
  // own built-in fallback defaults, matching the constants.
  var MAP_SENSOR_LABEL_KEYS = {
    sensor_label_style: 1, sensor_popup_enabled: 1,
    enable_label_collision: 1, label_priority_facility: 1
  };

  function mapFieldValue(el) {
    if (el.type === 'checkbox') { return el.checked; }
    // Native .value on a multi-select only returns the FIRST selected option —
    // Device Filter / Measurement Panel are all select[multiple] (bootstrap-select).
    if (el.tagName === 'SELECT' && el.multiple) {
      return Array.prototype.map.call(el.selectedOptions || [], function (o) { return o.value; });
    }
    var v = el.value;
    if (el.type === 'number' || (v !== '' && /^-?\d+(\.\d+)?$/.test(v))) {
      var n = parseFloat(v);
      if (!isNaN(n)) { return n; }
    }
    return v;
  }

  // Read a select[multiple]'s currently selected values straight from the DOM
  // by field name — used to gather sibling fields (e.g. the other two Device
  // Filter selects) that didn't just change but are needed to compute a
  // combined value.
  function mapMultiSelectValues(form, name) {
    var el = form.querySelector('[name="' + name + '"]');
    if (!el) { return []; }
    return Array.prototype.map.call(el.selectedOptions || [], function (o) { return o.value; }).filter(Boolean);
  }

  function mapSaveOption(uid, key, value, csrf) {
    var opts = {}; opts[key] = value;
    $.ajax({
      type: 'POST', url: '/save_widget_custom_options',
      headers: { 'X-CSRFToken': csrf }, contentType: 'application/json',
      data: JSON.stringify({ widget_id: uid, options: opts }),
      error: function () { if (window.showToast) { window.showToast('저장 실패', 'error'); } }
    });
  }

  // Live-apply the option to the running map instance (no rebuild). Uses the
  // public maplibre API and the setters the map exposes on its instance (the same
  // ones its in-map toggles use). Options without a live path here still auto-save
  // and appear on the next refresh. `form` is only needed by Device Filter (it has
  // to combine all three sibling selects, not just the one that changed).
  function mapLiveApply(uid, key, value, form) {
    var inst = window.AoTWidgetInstances && window.AoTWidgetInstances[uid];
    if (!inst) { return; }
    try {
      if (DEVICE_SELECTION_KEYS[key] && form && typeof inst._fetchAndRenderDevices === 'function') {
        // Combine all three device_selection_* selects into one list — this is
        // the Device Filter's EXCLUDE list (see utils_geo.collect_devices
        // docstring: selecting a device here hides it, everything else placed
        // on the map still shows), the same shape /api/geo/devices expects.
        var excludeIds = mapMultiSelectValues(form, 'device_selection_input')
          .concat(mapMultiSelectValues(form, 'device_selection_output'))
          .concat(mapMultiSelectValues(form, 'device_selection_function'));
        if (inst.vars && inst.vars.vars) {
          inst.vars.vars.device_ids = excludeIds.join(',');
          inst.vars.vars.map_device_ids = excludeIds.join(',');
        }
        inst._fetchAndRenderDevices();
      }
      else if (MEASUREMENT_PANEL_KEYS[key] && form && typeof inst._refreshMeasurementPanel === 'function') {
        var body = {};
        ['measurements_input', 'measurements_output', 'measurements_function'].forEach(function (k) {
          body[k] = mapMultiSelectValues(form, k);
        });
        $.ajax({
          type: 'POST', url: '/api/widget/aot_map/' + encodeURIComponent(uid) + '/measurements_panel',
          contentType: 'application/json', data: JSON.stringify(body)
        }).done(function (data) {
          if (data && data.status === 'success') { inst._refreshMeasurementPanel(data.measurements_map || {}); }
        });
      }
      else if (inst.map && key === 'default_zoom') { inst.map.easeTo({ zoom: parseFloat(value) }); }
      else if (inst.map && key === 'default_pitch') { inst.map.easeTo({ pitch: parseFloat(value) }); }
      else if (inst.map && key === 'default_bearing') { inst.map.easeTo({ bearing: parseFloat(value) }); }
      else if (key === 'show_labels' && typeof inst._setLabel === 'function' && inst._labelKeys) {
        inst._labelKeys.forEach(function (k) { inst._setLabel(k, !value); });
      }
      // Shape category toggles (show_*_shape) -> the map's own shape toggle.
      // Update the live options object FIRST: turning a category on that had
      // no MapLibre layer yet makes _applyShapeVisible create it on demand
      // (aot-map-widget-vector.js _ensureShapeLayer), and that creation path
      // re-checks _boolOpt(key) against this same object (wOpts === inst.vars.
      // vars) — without this write it would still read the stale pre-toggle
      // value and skip drawing (reproduced live: Zone Shape silently no-op'd
      // because _ensureZoneShapeLayer's own show_zone_shape re-check saw false).
      else if (MAP_SHAPE_CAT[key] && typeof inst._applyShapeVisible === 'function') {
        if (inst.vars && inst.vars.vars) { inst.vars.vars[key] = value; }
        inst._applyShapeVisible(MAP_SHAPE_CAT[key], !!value);
      }
      // Refresh interval -> restart the map's polling with the new period.
      else if (key === 'period' && typeof inst._setupRefresh === 'function') {
        inst._setupRefresh(parseFloat(value) || 0);
      }
      // 3D terrain -> maplibre setTerrain (add the DEM source on first enable).
      else if (key === 'enable_3d_terrain' && inst.map) {
        if (value) {
          if (!inst.map.getSource('mapbox-dem')) {
            inst.map.addSource('mapbox-dem', { type: 'raster-dem', url: 'https://demotiles.maplibre.org/terrain-tiles/tiles.json', tileSize: 256 });
          }
          inst.map.setTerrain({ source: 'mapbox-dem', exaggeration: 1.5 });
        } else {
          inst.map.setTerrain(null);
        }
      }
      // Overlay layer selection (comma-separated names) -> the layer panel's own
      // add/remove-layer logic, diffed against the currently active set.
      else if (key === 'active_layers' && typeof inst._setActiveOverlayNames === 'function') {
        var names = Array.isArray(value) ? value : String(value || '').split(',');
        inst._setActiveOverlayNames(names.map(function (s) { return String(s).trim(); }).filter(Boolean));
      }
      // Base map switch -> the layer panel's own base-radio logic (setStyle+rehydrate
      // for vector styles, raster activation otherwise).
      else if (key === 'selected_base_layer' && typeof inst._switchBaseLayer === 'function') {
        inst._switchBaseLayer(String(value || ''));
      }
      // Sensor-label style/behavior options: update the shared options object the
      // map reads from, then re-attach (idempotent — attach() detaches first).
      // One mechanism covers 12 modal options at once.
      else if (MAP_SENSOR_LABEL_KEYS[key] && typeof inst._reattachSensorLabels === 'function') {
        if (inst.vars && inst.vars.vars) { inst.vars.vars[key] = value; }
        inst._reattachSensorLabels();
      }
      // Measurement-panel refresh period -> restart its own polling loop in place.
      else if (key === 'input_update_interval' && typeof inst._setPanelRefreshInterval === 'function') {
        inst._setPanelRefreshInterval(value);
      }
    } catch (e) { /* ignore */ }
  }

  // Re-sync the settings-modal form to the DB's CURRENT custom_options every
  // time it opens. The form body is a page-load snapshot (cloned once from
  // an inert <template> — see dashboard_entry.html), but AoT_map can also be
  // changed from its own in-map controls (shape/layer/label toggles all call
  // /save_widget_custom_options directly, bypassing this form entirely), so
  // a modal left un-opened since page load can show stale values. Runs on
  // EVERY open, not gated behind the change-listener's one-time bind below.
  function syncMapFormToServer(uid, form) {
    fetch('/get_widget_custom_options/' + encodeURIComponent(uid))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || data.status !== 'success') { return; }
        var options = data.custom_options || {};
        Object.keys(options).forEach(function (name) {
          var els = form.querySelectorAll('[name="' + name + '"]');
          if (!els.length) { return; }
          var value = options[name];
          els.forEach(function (el) {
            if (el.type === 'checkbox') {
              el.checked = (value === true || value === 'true');
              return;
            }
            if (el.tagName === 'SELECT' && el.multiple) {
              var wanted = Array.isArray(value) ? value.map(String)
                : String(value == null ? '' : value).split(',').map(function (s) { return s.trim(); }).filter(Boolean);
              Array.prototype.forEach.call(el.options, function (opt) {
                opt.selected = wanted.indexOf(opt.value) !== -1;
              });
              if (window.jQuery) { window.jQuery(el).selectpicker('refresh'); }
              return;
            }
            el.value = (value == null) ? '' : value;
            if (el.tagName === 'SELECT' && window.jQuery && window.jQuery(el).hasClass('selectpicker')) {
              window.jQuery(el).selectpicker('refresh');
            }
          });
        });
      })
      .catch(function (e) { });
  }

  $(document).on('shown.bs.modal', function (ev) {
    var modal = ev.target;
    var m = /^modal_config_(.+)$/.exec(modal.id || '');
    if (!m) { return; }
    var uid = m[1];
    if (widgetTypeOf(uid) !== 'AoT_map') { return; }
    var form = formOf(uid);
    if (!form) { return; }

    syncMapFormToServer(uid, form);

    if (modal.dataset.mapAutosaveBound === '1') { return; }
    var csrf = fieldValue(form, 'csrf_token');
    var mapTimers = {};

    $(form).on('change.mapsave input.mapsave', 'input, select, textarea', function () {
      var name = this.getAttribute('name');
      if (!name || !MAP_SAFE_KEYS[name]) { return; }   // destructive/other → Save button
      var value = mapFieldValue(this);
      clearTimeout(mapTimers[name]);
      mapTimers[name] = setTimeout(function () {
        mapSaveOption(uid, name, value, csrf);
        mapLiveApply(uid, name, value, form);
        if (window.showToast) { window.showToast('저장됨', 'success'); }
      }, 400);
    });

    modal.dataset.mapAutosaveBound = '1';
  });
})();
