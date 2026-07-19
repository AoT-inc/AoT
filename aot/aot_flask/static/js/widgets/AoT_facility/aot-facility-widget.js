// aot-facility-widget.js — Dashboard widget controller (3D, Three.js, IEC)
// PRD/DESIGN-GEO-FACILITY-001 · MVP v3
(function () {
  'use strict';

  const STATE = {};  // { [widgetId]: { vars, threeCtx, runtime, setpoints, layerVis } }

  var _LAYER_LABELS = {
    envelope: (window._ ? window._('Envelope') : 'Envelope'),
    opening:  (window._ ? window._('Window') : 'Window'),
    climate:  (window._ ? window._('Climate') : 'Climate'),
    sensor:   (window._ ? window._('Sensor') : 'Sensor'),
    fixture:  (window._ ? window._('Lighting') : 'Lighting'),
    irrig:    (window._ ? window._('Irrigation') : 'Irrigation')
  };

  // ── Entry point ──────────────────────────────────────────────────────────────
  function init(widgetId) {
    const varsEl = document.getElementById('aot-facility-vars-' + widgetId);
    if (!varsEl) return;
    let vars;
    try { vars = JSON.parse(varsEl.textContent); }
    catch (e) { console.error('[AoT Facility] vars parse failed', e); return; }

    STATE[widgetId] = {
      vars, threeCtx: null, runtime: null, setpoints: vars.setpoints || null,
      layerVis: { envelope: true, opening: true, climate: true, sensor: true, fixture: true, irrig: true },
    };

    if (!vars.facility) return;

    const isControl = vars.displayMode === 'control';

    // Wait for Three.js + AoTFacility3D to be ready, then start
    _ensureThree(function () {
      _initScene(widgetId);

      // IEC control modules
      if (isControl) {
        if (vars.showStatus && window.AoTFacilityStatus) {
          AoTFacilityStatus.start(widgetId, vars.facility.unique_id, vars.functionUuid || '');
        }
        if (vars.showSetpoints && vars.canControl && window.AoTFacilitySetpoints) {
          AoTFacilitySetpoints.bind(widgetId, vars.facility.unique_id, vars.setpoints);
          if (vars.setpoints) {
            AoTFacilitySetpoints.updateEnvColors(widgetId, {}, vars.setpoints);
          }
        }
        if (vars.showControls && window.AoTFacilityControlGrid) {
          AoTFacilityControlGrid.bind(widgetId, vars.facility.unique_id, vars.canControl);
        }
      }

      // AoTActuatorPanel: common to viewer/control modes — always attach when showControls=true.
      // Calling update() without attach early-returns due to missing STATE,
      // so the panel would stay stuck on "Loading..." forever.
      if (vars.showControls && window.AoTActuatorPanel) {
        var panelEl = document.getElementById('aot-act-panel-' + widgetId);
        if (panelEl) {
          AoTActuatorPanel.attach(widgetId, panelEl, vars.facility.unique_id, vars.canControl);
        }
      }

      _initLayerToggles(widgetId);
      _initResizeHandle(widgetId);
      _refreshRuntime(widgetId);
      if (vars.showAiAdvice) _renderAdvice(widgetId);

      if (vars.period && vars.period > 0) {
        STATE[widgetId].refreshTimer = setInterval(function () {
          if (document.hidden) return;
          _refreshRuntime(widgetId);
          if (vars.showAiAdvice) _renderAdvice(widgetId);
        }, vars.period * 1000);
      }
    });
  }

  // ── Three.js readiness check ──────────────────────────────────────────────────
  function _ensureThree(cb) {
    if (window.THREE && window.AoTFacility3D) { cb(); return; }

    if (!window.THREE && !document.querySelector('script[src*="three.min.js"]')) {
      var s = document.createElement('script');
      s.src = '/static/js/widgets/AoT_facility/three.min.js';
      document.head.appendChild(s);
    }

    var tries = 0;
    var poll = setInterval(function () {
      if ((window.THREE && window.AoTFacility3D) || ++tries > 60) {
        clearInterval(poll);
        if (window.THREE && window.AoTFacility3D) cb();
        else console.error('[AoT Facility] THREE or AoTFacility3D not available after 6s');
      }
    }, 100);
  }

  // ── Camera state helpers (localStorage persistence) ─────────────────────────
  function _camStorageKey(facilityUuid) {
    return 'aot-fac-cam-' + facilityUuid;
  }

  function _captureCam(ctx) {
    if (!ctx || !ctx.camera || !ctx.controls) return null;
    return {
      px: ctx.camera.position.x, py: ctx.camera.position.y, pz: ctx.camera.position.z,
      tx: ctx.controls.target.x, ty: ctx.controls.target.y, tz: ctx.controls.target.z
    };
  }

  function _applyCam(ctx, s) {
    if (!ctx || !ctx.camera || !ctx.controls || !s) return;
    ctx.camera.position.set(s.px, s.py, s.pz);
    ctx.controls.target.set(s.tx, s.ty, s.tz);
    ctx.controls.update();
    if (ctx.requestRender) ctx.requestRender();
  }

  function _saveCamToStorage(ctx, facilityUuid) {
    var s = _captureCam(ctx);
    if (!s) return;
    try { localStorage.setItem(_camStorageKey(facilityUuid), JSON.stringify(s)); } catch (e) {}
  }

  function _restoreCamFromStorage(ctx, facilityUuid) {
    try {
      var raw = localStorage.getItem(_camStorageKey(facilityUuid));
      if (!raw) return;
      _applyCam(ctx, JSON.parse(raw));
    } catch (e) {}
  }

  // ── Build / rebuild 3D scene ─────────────────────────────────────────────────
  function _initScene(widgetId) {
    const { vars, runtime } = STATE[widgetId];
    const canvas = document.getElementById('aot-facility-canvas-' + widgetId);
    if (!canvas || !window.AoTFacility3D) return;

    if (STATE[widgetId].threeCtx) {
      STATE[widgetId].threeCtx.dispose();
    }

    const ctx = window.AoTFacility3D.buildScene(canvas, vars.facility, runtime, { renderMode: vars.renderMode3d || 'default' });
    STATE[widgetId].threeCtx = ctx;

    // Restore saved camera view from localStorage on initial load
    _restoreCamFromStorage(ctx, vars.facility.unique_id);

    // Expose scene for hotspot sensor-color updates
    if (!window._aotFacilityScenes) window._aotFacilityScenes = {};
    window._aotFacilityScenes[widgetId] = ctx.scene;

    // Re-apply saved layer visibility (e.g. after runtime-triggered rebuild)
    _applyLayerVis(widgetId, ctx);

    // Attach hotspots in control mode
    if (vars.displayMode === 'control' && window.AoTFacilityHotspot) {
      AoTFacilityHotspot.attach(ctx, vars.facility, widgetId);
    }

    // Attach sensor labels (HTML overlay)
    if (window.AoTSensorLabels) {
      AoTSensorLabels.attach(widgetId, ctx, vars.facility, vars.sensorLabelOpts || {});
    }
  }

  // ── Layer toggle strip ─────────────────────────────────────────────────────
  function _initLayerToggles(widgetId) {
    var strip = document.getElementById('aot-3d-layers-' + widgetId);
    if (!strip) {
      // Build toggle strip dynamically below the 3D canvas heading
      var wrap = document.getElementById('aot-facility-canvas-' + widgetId);
      if (!wrap) return;
      var parent = wrap.closest('.aot-fac-section');
      if (!parent) return;
      strip = document.createElement('div');
      strip.id = 'aot-3d-layers-' + widgetId;
      strip.className = 'aot-3d-layer-strip';
      // Insert between h6 and .aot-facility-3d-wrap
      var h6 = parent.querySelector('h6');
      if (h6 && h6.nextSibling) {
        parent.insertBefore(strip, h6.nextSibling);
      } else {
        parent.insertBefore(strip, wrap.parentNode);
      }
    }

    // Build buttons
    var layerVis = STATE[widgetId].layerVis;
    var html = '';
    Object.keys(_LAYER_LABELS).forEach(function (cat) {
      var active = layerVis[cat] !== false ? ' aot-layer-on' : '';
      html += '<button class="aot-layer-btn' + active + '" data-cat="' + cat + '" data-wid="' + widgetId + '">' +
              _LAYER_LABELS[cat] + '</button>';
    });
    strip.innerHTML = html;

    strip.addEventListener('click', function (e) {
      var btn = e.target.closest('.aot-layer-btn');
      if (!btn) return;
      var cat = btn.dataset.cat;
      var wid = btn.dataset.wid;
      var st  = STATE[wid];
      if (!st) return;
      st.layerVis[cat] = !st.layerVis[cat];
      btn.classList.toggle('aot-layer-on', !!st.layerVis[cat]);
      if (st.threeCtx && st.threeCtx.setCategoryVisibility) {
        st.threeCtx.setCategoryVisibility(cat, !!st.layerVis[cat]);
      }
    });
  }

  function _applyLayerVis(widgetId, ctx) {
    if (!ctx || !ctx.setCategoryVisibility) return;
    var layerVis = STATE[widgetId] && STATE[widgetId].layerVis;
    if (!layerVis) return;
    Object.keys(layerVis).forEach(function (cat) {
      if (!layerVis[cat]) ctx.setCategoryVisibility(cat, false);
    });
  }

  // ── 3D canvas resize handle ───────────────────────────────────────────────────
  function _initResizeHandle(widgetId) {
    var handle = document.getElementById('aot-fac-3d-rh-' + widgetId);
    var wrap   = document.getElementById('aot-facility-3d-wrap-' + widgetId);
    if (!handle || !wrap) return;

    var storageKey = 'aot-fac-3dh-' + widgetId;
    var savedH = parseInt(localStorage.getItem(storageKey), 10);
    if (savedH && savedH >= 150) wrap.style.height = savedH + 'px';

    var startY, startH;

    function onMove(e) {
      var y = e.touches ? e.touches[0].clientY : e.clientY;
      var newH = Math.max(150, startH + (y - startY));
      wrap.style.height = newH + 'px';
      window.dispatchEvent(new Event('resize'));
    }
    function onUp() {
      var h = parseInt(wrap.style.height, 10);
      if (h) try { localStorage.setItem(storageKey, h); } catch (e) {}
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup',   onUp);
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend',  onUp);
    }

    handle.addEventListener('mousedown', function (e) {
      e.preventDefault();
      startH = wrap.getBoundingClientRect().height;
      startY = e.clientY;
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup',   onUp);
    });
    handle.addEventListener('touchstart', function (e) {
      startH = wrap.getBoundingClientRect().height;
      startY = e.touches[0].clientY;
      document.addEventListener('touchmove', onMove, { passive: true });
      document.addEventListener('touchend',  onUp);
    }, { passive: true });
  }

  // ── Fetch runtime data ────────────────────────────────────────────────────────
  async function _refreshRuntime(widgetId) {
    const { vars } = STATE[widgetId];
    const uuid = vars.facility.unique_id;
    const statusEl = document.getElementById('aot-facility-status-' + widgetId);
    const isControl = vars.displayMode === 'control';

    try {
      const resp = await fetch('/api/aot/facility/' + uuid + '/runtime');
      if (!resp.ok) throw new Error(resp.status);
      const data = await resp.json();
      STATE[widgetId].runtime = data;

      _updateEnvPanel(widgetId, data);
      _publishAiContext(widgetId, data);

      // Update § B setpoint colors
      if (isControl && window.AoTFacilitySetpoints) {
        const sp = STATE[widgetId].setpoints;
        AoTFacilitySetpoints.updateEnvColors(widgetId, data.indoor || {}, sp);
      }

      // Update § D actuator grid
      if (isControl && vars.showControls && window.AoTFacilityControlGrid) {
        const outdoor = data.outdoor || {};
        AoTFacilityControlGrid.update(
          widgetId, uuid, data.actuator_states || {},
          vars.canControl, outdoor.temp_c, data.actuator_order || []
        );
      }

      // Update 3D hotspot sensor status
      if (isControl && window.AoTFacilityHotspot && data.sensors) {
        const statusMap = {};
        (data.sensors.detail || []).forEach(function (s) {
          statusMap[s.role] = s.status || 'valid';
        });
        AoTFacilityHotspot.updateSensorStatus(widgetId, statusMap);
      }

      // Rebuild scene with live actuator states — save camera before, restore after.
      if (window.AoTFacility3D) {
        try {
          const canvas = document.getElementById('aot-facility-canvas-' + widgetId);
          if (canvas) {
            // Save camera position before dispose so the view is preserved across rebuilds
            var savedCam = _captureCam(STATE[widgetId].threeCtx);
            if (savedCam) {
              try { localStorage.setItem(_camStorageKey(uuid), JSON.stringify(savedCam)); } catch (e) {}
            }
            if (STATE[widgetId].threeCtx) STATE[widgetId].threeCtx.dispose();
            const ctx = window.AoTFacility3D.buildScene(canvas, vars.facility, data, { renderMode: vars.renderMode3d || 'default' });
            STATE[widgetId].threeCtx = ctx;
            // Restore camera (in-memory first, then localStorage fallback)
            if (savedCam) _applyCam(ctx, savedCam);
            else _restoreCamFromStorage(ctx, uuid);
            if (window._aotFacilityScenes) window._aotFacilityScenes[widgetId] = ctx.scene;
            if (isControl && window.AoTFacilityHotspot) {
              AoTFacilityHotspot.attach(ctx, vars.facility, widgetId);
            }
            if (window.AoTSensorLabels) {
              AoTSensorLabels.attach(widgetId, ctx, vars.facility, vars.sensorLabelOpts || {});
            }
          }
        } catch (e3d) {
          console.warn('[AoT Facility] 3D scene build failed (continuing without 3D):', e3d);
        }
      }

      // Push latest fitting sensor channel values to label overlay
      if (window.AoTSensorLabels && Array.isArray(data.fitting_sensors)) {
        AoTSensorLabels.updateValues(widgetId, data.fitting_sensors);
      }

      // Update actuator group panel
      if (window.AoTActuatorPanel) {
        AoTActuatorPanel.update(widgetId, data.actuator_states || {}, data.actuator_order || []);
      }

      if (statusEl) statusEl.textContent = new Date().toLocaleTimeString();
    } catch (e) {
      console.warn('[AoT Facility] runtime fetch failed', e);
      if (statusEl) statusEl.textContent = (window._ ? window._('Connection error') : 'Connection error');
    }
  }

  // ── Environment panel update ──────────────────────────────────────────────────
  function _updateEnvPanel(widgetId, runtime) {
    const envEl = document.getElementById('aot-facility-env-' + widgetId);
    if (!envEl) return;

    const outdoor = runtime.outdoor || {};
    const indoor  = runtime.indoor  || {};

    const vals = {
      indoor_vpd:      indoor.vpd_kpa     != null ? indoor.vpd_kpa.toFixed(2)     + ' kPa' : '— kPa',
      indoor_temp:     indoor.temp_c      != null ? indoor.temp_c.toFixed(1)      + ' °C'  : '— °C',
      indoor_humidity: indoor.humidity_pct != null ? indoor.humidity_pct.toFixed(0) + ' %'   : '— %',
      indoor_co2:      indoor.co2_ppm     != null ? indoor.co2_ppm.toFixed(0)     + ' ppm' : '— ppm',
      outdoor_temp:    outdoor.temp_c     != null ? outdoor.temp_c.toFixed(1)     + ' °C'  : '— °C',
      wind:            outdoor.wind_ms    != null ? outdoor.wind_ms.toFixed(1)    + ' m/s' : '— m/s',
      solar:           outdoor.solar_wm2  != null ? outdoor.solar_wm2.toFixed(0)  + ' W/m²': '— W/m²',
    };

    Object.entries(vals).forEach(([key, val]) => {
      const cell = envEl.querySelector('[data-key="' + key + '"]');
      if (cell) {
        const valEl = cell.querySelector('.env-value');
        if (valEl) valEl.textContent = val;
      }
    });
  }

  // ── AI context publication ─────────────────────────────────────────────────────
  function _publishAiContext(widgetId, runtime) {
    const { vars } = STATE[widgetId];
    const f = vars.facility;
    if (!f) return;

    if (!window.AOT_AI_CONTEXT) window.AOT_AI_CONTEXT = {};
    if (!window.AOT_AI_CONTEXT.facility) window.AOT_AI_CONTEXT.facility = {};

    window.AOT_AI_CONTEXT.facility[widgetId] = {
      facility: {
        name:         f.name,
        preset:       f.preset,
        structure:    f.structure,
        bay_count:    f.bay_count,
        orientation_deg: (f.geometry_3d || {}).orientation_deg,
        geometry: {
          span_m:    (f.geometry_3d || {}).span_width_m,
          eave_m:    (f.geometry_3d || {}).eave_height_m,
          ridge_m:   (f.geometry_3d || {}).ridge_height_m,
          length_m:  (f.geometry_3d || {}).length_m,
          roof_type: (f.geometry_3d || {}).roof_type,
        },
        envelope: {
          layers:          (f.envelope || {}).layer_count,
          outer_cover:     ((f.envelope || {}).outer || {}).cover_material,
          side_vent:       (((f.envelope || {}).outer || {}).side_vent || {}).enabled,
          roof_vent:       (((f.envelope || {}).outer || {}).roof_vent || {}).enabled,
          thermal_curtain: ((f.envelope || {}).curtain || {}).thermal,
          shade_curtain:   ((f.envelope || {}).curtain || {}).shade,
        },
      },
      capacity: f.computed || {},
      runtime: {
        outdoor:   (runtime || {}).outdoor       || {},
        indoor:    (runtime || {}).indoor        || {},
        actuators: (runtime || {}).actuator_states || {},
      },
      setpoints: STATE[widgetId].setpoints || {},
      ts: new Date().toISOString(),
    };
  }

  // ── AI advice cards (§ E) ─────────────────────────────────────────────────────
  async function _renderAdvice(widgetId) {
    const adviceEl = document.getElementById('aot-facility-advice-' + widgetId);
    if (!adviceEl) return;
    const facility = STATE[widgetId].vars.facility;
    if (!facility) return;

    const cards = [
      {
        cls: 'now', horizon: 'now', confidence: 0.84,
        title: (window._ ? window._('Immediate action') : 'Immediate action'),
        actions: (window._ ? window._('Recommend closing the side window motor') : 'Recommend closing the side window motor'),
        reason: (window._ ? window._('Outside temperature dropping + wind speed rising') : 'Outside temperature dropping + wind speed rising'),
        effect: (window._ ? window._('Expected reduction in heat loss') : 'Expected reduction in heat loss'),
        commands: [{ kind: 'side_window_motor', action: 'off' }],
      },
      {
        cls: 'h1', horizon: '1h', confidence: 0.72,
        title: (window._ ? window._('Within 1 hour') : 'Within 1 hour'),
        actions: (window._ ? window._('Prepare to deploy the thermal curtain') : 'Prepare to deploy the thermal curtain'),
        reason: (window._ ? window._('Outside temperature drop forecast after sunset') : 'Outside temperature drop forecast after sunset'),
        effect: (window._ ? window._('Heating load -25%') : 'Heating load -25%'),
        commands: [{ kind: 'thermal_curtain_motor', action: 'on' }],
      },
      {
        cls: 'h6', horizon: '6h', confidence: 0.65,
        title: (window._ ? window._('Within 6 hours') : 'Within 6 hours'),
        actions: (window._ ? window._('Brief 30% ventilation at dawn') : 'Brief 30% ventilation at dawn'),
        reason: (window._ ? window._('Predicted rise in dew point') : 'Predicted rise in dew point'),
        effect: (window._ ? window._('Suppress condensation risk') : 'Suppress condensation risk'),
        commands: [{ kind: 'side_window_motor', action: 'set', pct: 30 }],
      },
    ];

    adviceEl.innerHTML = cards.map(function (a) {
      return '<div class="advice-card ' + a.cls + '">' +
        '<div class="advice-title">' + a.title +
          '<span class="advice-conf">' + (window._ ? window._('Confidence') : 'Confidence') + ' ' + Math.round(a.confidence * 100) + '%</span>' +
        '</div>' +
        '<div class="advice-actions">' + _esc(a.actions) + '</div>' +
        '<div class="advice-reason">'  + _esc(a.reason)  + '</div>' +
        '<div class="advice-effect">'  + _esc(a.effect)  + '</div>' +
        '<div class="advice-buttons">' +
          '<button class="approve aot-fac-approve"' +
            ' data-widget="'   + _esc(widgetId)               + '"' +
            ' data-facility="' + _esc(facility.unique_id)      + '"' +
            ' data-horizon="'  + _esc(a.horizon)               + '"' +
            ' data-commands="' + _esc(JSON.stringify(a.commands || [])) + '"' +
            '>' + (window._ ? window._('Approve and apply') : 'Approve and apply') + '</button>' +
          '<button onclick="window.aotFacilityModify(\'' + a.horizon + '\')">' + (window._ ? window._('Modify') : 'Modify') + '</button>' +
          '<button onclick="window.aotFacilityIgnore(\'' + a.horizon + '\')">' + (window._ ? window._('Ignore') : 'Ignore') + '</button>' +
        '</div>' +
      '</div>';
    }).join('');
  }

  function _esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }

  // ── Approval handler (event delegation) ──────────────────────────────────────
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.aot-fac-approve');
    if (!btn) return;

    var facilityUuid = btn.dataset.facility;
    var horizon      = btn.dataset.horizon;
    var commands     = [];
    try { commands = JSON.parse(btn.dataset.commands || '[]'); } catch (_) {}

    var label   = {
      now:  (window._ ? window._('Immediate action') : 'Immediate action'),
      '1h': (window._ ? window._('Within 1 hour') : 'Within 1 hour'),
      '6h': (window._ ? window._('Within 6 hours') : 'Within 6 hours')
    }[horizon] || horizon;
    var summary = commands.map(function (c) {
      return c.kind + ' → ' + c.action + (c.pct != null ? ' ' + c.pct + '%' : '');
    }).join(', ');

    if (!confirm((window._ ? window._('Apply this AI recommendation?') : 'Apply this AI recommendation?') + '\n[' + label + '] ' + summary)) return;

    btn.disabled = true;
    fetch('/api/geo/facility/' + facilityUuid + '/apply', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ horizon: horizon, commands: commands }),
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.ok) {
        btn.textContent = (window._ ? window._('Applied') : 'Applied');
      } else {
        var msg = (window._ ? window._('Partially failed') : 'Partially failed') + ' (' + data.applied + ' ' + (window._ ? window._('succeeded') : 'succeeded') + ')';
        if (data.failed && data.failed.length) {
          msg += '\n' + data.failed.map(function (f) {
            return '· ' + f.kind + ': ' + f.reason;
          }).join('\n');
        }
        alert(msg);
        btn.disabled = false;
      }
    })
    .catch(function (err) {
      alert((window._ ? window._('Error') : 'Error') + ': ' + err);
      btn.disabled = false;
    });
  });

  window.aotFacilityModify = function (horizon) { alert((window._ ? window._('Modify feature — next phase') : 'Modify feature — next phase') + ' (' + horizon + ')'); };
  window.aotFacilityIgnore = function (horizon) { alert((window._ ? window._('Ignore logged (mock)') : 'Ignore logged (mock)') + ' (' + horizon + ')'); };

  window.initAoTFacilityWidget = init;

  window.destroyAoTFacilityWidget = function (widgetId) {
    var state = STATE[widgetId];
    if (!state) return;
    if (state.refreshTimer) { clearInterval(state.refreshTimer); state.refreshTimer = null; }
    if (state.threeCtx) { state.threeCtx.dispose(); state.threeCtx = null; }
    delete STATE[widgetId];
  };
})();
