// commissioning.js — extracted from templates/pages/geo/geo_facility.html (2026-07-31).
// Device check (commissioning): runs a short actuator test sequence and records the operator verdict.
// Loaded as part of the geo-facility bundle, after aot-facility-design.js,
// so FittingsUI/EnvelopeUI and the _IEC/_COMM string catalogs already exist.

(function () {
  'use strict';

  var _facilityUuid = null;
  var _checkId      = null;
  var _pollTimer    = null;
  var _verdicts     = {};

  function initComm(facilityUuid, actuators) {
    _facilityUuid = facilityUuid;
    _checkId      = null;
    _verdicts     = {};

    // Show panel
    var panel = document.getElementById('comm-panel');
    if (panel) panel.style.display = '';

    // Render device list
    var listEl = document.getElementById('comm-act-list');
    if (!listEl) return;
    listEl.innerHTML = '';

    if (!actuators || !actuators.length) {
      listEl.innerHTML = '<span style="color:var(--aot-color-text-secondary);font-size:var(--aot-font-size-sm);">' + _COMM.no_devices + '</span>';
      return;
    }

    actuators.forEach(function (act) {
      var item = document.createElement('label');
      item.className = 'comm-act-item';
      item.dataset.id = act.actuator_id || act.device_uuid || '';
      item.dataset.kind = act.kind || '';
      item.innerHTML =
        '<input type="checkbox" value="' + (act.actuator_id || act.device_uuid || '') + '">' +
        '<span>' + _escHtml(act.name || act.kind || act.actuator_id || '') + '</span>' +
        '<span style="color:var(--aot-color-text-secondary);font-size:var(--aot-font-size-xs);margin-left:auto;">' + _escHtml(act.kind || '') + '</span>';
      item.querySelector('input').addEventListener('change', function () {
        item.classList.toggle('checked', this.checked);
        _updateStartBtn();
      });
      listEl.appendChild(item);
    });

    _updateStartBtn();
    _resetToSetup();
  }

  function _updateStartBtn() {
    var btn = document.getElementById('btn-comm-start');
    if (!btn) return;
    var any = document.querySelectorAll('#comm-act-list input[type=checkbox]:checked').length > 0;
    btn.disabled = !any;
  }

  // ── Select all ────────────────────────────────────────────────────────────
  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'btn-comm-select-all') {
      document.querySelectorAll('#comm-act-list input[type=checkbox]').forEach(function (cb) {
        cb.checked = true;
        var item = cb.closest('.comm-act-item');
        if (item) item.classList.add('checked');
      });
      _updateStartBtn();
    }
  });

  // ── Start check ───────────────────────────────────────────────────────────
  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'btn-comm-start') {
      _startCheck();
    }
  });

  function _startCheck() {
    if (!_facilityUuid) return;
    var ids = [];
    document.querySelectorAll('#comm-act-list input[type=checkbox]:checked').forEach(function (cb) {
      if (cb.value) ids.push(cb.value);
    });
    if (!ids.length) return;

    var btn = document.getElementById('btn-comm-start');
    if (btn) { btn.disabled = true; btn.textContent = _COMM.starting; }

    fetch('/api/geo/facility/' + _facilityUuid + '/commissioning/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({actuator_ids: ids}),
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) { alert(d.message || _COMM.start_failed); _resetBtnStart(); return; }
      _checkId = d.check_id;
      _showRunning();
      _pollResult();
    })
    .catch(function (err) { alert(_COMM.error_prefix + err); _resetBtnStart(); });
  }

  function _resetBtnStart() {
    var btn = document.getElementById('btn-comm-start');
    if (btn) { btn.disabled = false; btn.textContent = _COMM.start_check; }
  }

  // ── Polling ───────────────────────────────────────────────────────────────
  function _pollResult() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(function () {
      if (!_checkId || !_facilityUuid) return;
      fetch('/api/geo/facility/' + _facilityUuid + '/commissioning/' + _checkId)
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) return;
          _renderProgress(d);
          _renderResults(d.results || []);
          if (d.overall_status === 'awaiting_verdict' || d.overall_status === 'completed') {
            clearInterval(_pollTimer);
            _pollTimer = null;
          }
        })
        .catch(function () {});
    }, 3000);
  }

  // ── Progress display ──────────────────────────────────────────────────────
  function _renderProgress(data) {
    var prog = data.progress || {};
    var done  = prog.done || 0;
    var total = prog.total || 1;
    var pct   = Math.round(done / total * 100);
    var fill  = document.getElementById('comm-progress-fill');
    var text  = document.getElementById('comm-progress-text');
    if (fill) fill.style.width = pct + '%';

    var statusMap = {
      running:          _COMM.status_running + ' (' + done + '/' + total + ')',
      awaiting_verdict: _COMM.status_awaiting,
      completed:        _COMM.status_completed,
      error:            _COMM.status_error + (data.error_msg || ''),
    };
    if (text) text.textContent = statusMap[data.overall_status] || data.overall_status;
  }

  // ── Result card rendering ─────────────────────────────────────────────────
  function _renderResults(results) {
    var container = document.getElementById('comm-results-list');
    if (!container) return;

    results.forEach(function (r) {
      var cardId = 'comm-card-' + r.actuator_id;
      var existing = document.getElementById(cardId);

      var html = _buildCard(r);
      if (existing) {
        existing.outerHTML = html;
      } else {
        container.insertAdjacentHTML('beforeend', html);
      }

      // Rebind verdict button events
      var card = document.getElementById(cardId);
      if (card) _bindVerdictBtns(card, r.actuator_id);
    });
  }

  function _buildCard(r) {
    var statusLabel = {ok:_COMM.label_ok, warn:_COMM.label_warn, fail:_COMM.label_fail, pending:_COMM.label_pending, running:_COMM.label_running}[r.status] || r.status;
    // Shared status badge; 'pending' has no variant (the base look is neutral).
    var _ST = { ok:'aot-status-ok', warn:'aot-status-warn', fail:'aot-status-fail',
                running:'aot-status-running' };
    var statusClass = _ST[r.status || 'pending'] || '';

    var metricsHtml = '';
    if (r.baseline && Object.keys(r.baseline).length) {
      var parts = [];
      Object.keys(r.baseline).forEach(function (v) {
        var base = r.baseline[v];
        var resp = (r.response || {})[v];
        var exp  = (r.expected_response || {})[v];
        var lag  = r.response_lag_s;
        var noiseVal = (r.noise_level || {})[v];
        var unit = {T:'°C', RH:'%', CO2:'ppm'}[v] || '';
        var txt = v + ': ' + _COMM.baseline + ' <span>' + _fmt(base) + unit + '</span>';
        if (resp !== undefined && resp !== null) {
          var sign = resp > 0 ? '+' : '';
          txt += ', ' + _COMM.response + ' <span>' + sign + _fmt(resp) + unit + '</span>';
        }
        if (exp !== undefined && exp !== null) {
          var esign = exp > 0 ? '+' : '';
          txt += ', ' + _COMM.expected + ' <span>' + esign + _fmt(exp) + unit + '</span>';
        }
        if (lag !== undefined && lag !== null) {
          txt += ', ' + _COMM.delay + ' <span>' + Math.round(lag) + 's</span>';
        }
        if (noiseVal !== undefined && noiseVal !== null) {
          txt += ', ' + _COMM.noise + ' ±<span>' + _fmt(noiseVal) + unit + '</span>';
        }
        parts.push('<div class="comm-metric">' + txt + '</div>');
      });
      metricsHtml = '<div class="comm-metric-row">' + parts.join('') + '</div>';
    }

    var dispatchHtml = '';
    if (r.dispatch_ok === false) {
      dispatchHtml = '<div style="color:var(--aot-tint-warning-fg);font-size:var(--aot-font-size-xs);margin-top:4px;">' + _COMM.dispatch_fail + '</div>';
    }

    var dirHtml = '';
    if (r.direction_match === false) {
      dirHtml = '<div style="color:var(--aot-tint-warning-fg);font-size:var(--aot-font-size-xs);margin-top:4px;">' + _COMM.dir_mismatch + '</div>';
    }

    var verdictHtml = '';
    var showVerdict = r.status && r.status !== 'pending' && r.status !== 'running';
    if (showVerdict) {
      var selected = _verdicts[r.actuator_id] || r.verdict || '';
      var opts = [
        {v:'ok',       label:_COMM.verdict_ok,       hint:_COMM.verdict_ok_hint},
        {v:'sensor',   label:_COMM.verdict_sensor,   hint:_COMM.verdict_sensor_hint},
        {v:'device',   label:_COMM.verdict_device,   hint:_COMM.verdict_device_hint},
        {v:'external', label:_COMM.verdict_external, hint:_COMM.verdict_external_hint},
        {v:'skip',     label:_COMM.verdict_skip,     hint:_COMM.verdict_skip_hint},
      ];
      var btnHtml = opts.map(function (o) {
        var sel = selected === o.v ? ' selected-' + o.v : '';
        return '<button type="button" class="btn aot-pill-btn comm-verdict-btn' +
          (sel ? ' aot-pill-btn-primary' : '') + '" data-verdict="' + o.v +
          '" title="' + _escHtml(o.hint) + '">' + _escHtml(o.label) + '</button>';
      }).join('');

      var appliedHtml = '';
      if (r.applied_settings && r.applied_settings.length) {
        var items = r.applied_settings.map(function (s) {
          return '<div class="comm-action-item"><span class="comm-action-icon">&#10003;</span><span>' + _escHtml(s) + '</span></div>';
        }).join('');
        appliedHtml = '<div class="comm-actions-applied">' + items + '</div>';
      }

      verdictHtml =
        '<div class="comm-verdict-form">' +
          '<div class="comm-verdict-label">' + _COMM.verdict_label + '</div>' +
          '<div class="comm-verdict-btns" data-actuator="' + r.actuator_id + '">' + btnHtml + '</div>' +
          '<input type="text" class="form-control aot-modern-input comm-note-input" placeholder="' + _escHtml(_COMM.note_placeholder) + '" ' +
                 'id="comm-note-' + r.actuator_id + '" value="">' +
          '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary comm-verdict-submit" ' +
                  'data-actuator="' + r.actuator_id + '" style="font-size:var(--aot-font-size-xs);"' +
                  (selected ? '' : ' disabled') + '>' + _COMM.apply_verdict + '</button>' +
          appliedHtml +
        '</div>';
    }

    return '<div class="aot-modal-container comm-result-card" id="comm-card-' + r.actuator_id + '">' +
      '<div class="aot-modal-detail-head comm-result-header">' +
        '<span>' + _escHtml(r.name || r.actuator_id) + '</span>' +
        '<span class="aot-status-badge ' + statusClass + '">' + statusLabel + '</span>' +
      '</div>' +
      '<div class="comm-result-body">' +
        metricsHtml +
        dispatchHtml +
        dirHtml +
        verdictHtml +
      '</div>' +
    '</div>';
  }

  // ── Verdict button event binding ──────────────────────────────────────────
  function _bindVerdictBtns(card, actuatorId) {
    var btnsRow = card.querySelector('.comm-verdict-btns[data-actuator="' + actuatorId + '"]');
    if (!btnsRow) return;

    btnsRow.querySelectorAll('.comm-verdict-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var v = btn.dataset.verdict;
        _verdicts[actuatorId] = v;

        // Selection indication — the shared button's own selected variant.
        btnsRow.querySelectorAll('.comm-verdict-btn').forEach(function (b) {
          b.classList.remove('aot-pill-btn-primary');
        });
        btn.classList.add('aot-pill-btn-primary');

        // Enable submit button
        var submitBtn = card.querySelector('.comm-verdict-submit[data-actuator="' + actuatorId + '"]');
        if (submitBtn) submitBtn.disabled = false;
      });
    });

    var submitBtn = card.querySelector('.comm-verdict-submit[data-actuator="' + actuatorId + '"]');
    if (submitBtn) {
      submitBtn.addEventListener('click', function () {
        _submitVerdict(actuatorId);
      });
    }
  }

  // ── Submit verdict ────────────────────────────────────────────────────────
  function _submitVerdict(actuatorId) {
    var verdict = _verdicts[actuatorId];
    if (!verdict) return;
    var noteEl = document.getElementById('comm-note-' + actuatorId);
    var note   = noteEl ? noteEl.value : '';

    var submitBtn = document.querySelector('.comm-verdict-submit[data-actuator="' + actuatorId + '"]');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = _COMM.applying; }

    fetch('/api/geo/facility/' + _facilityUuid + '/commissioning/' + _checkId + '/verdict', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({actuator_id: actuatorId, verdict: verdict, note: note}),
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) { alert(d.message || _COMM.submit_failed); if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = _COMM.apply_verdict; } return; }
      if (submitBtn) { submitBtn.textContent = _COMM.apply_done; submitBtn.style.background = 'var(--aot-btn-bg-primary)'; submitBtn.style.borderColor = 'var(--aot-btn-border-primary)'; }
      var card = document.getElementById('comm-card-' + actuatorId);
      if (card && d.actions && d.actions.length) {
        var existing = card.querySelector('.comm-actions-applied');
        var items = d.actions.map(function (a) {
          return '<div class="comm-action-item"><span class="comm-action-icon">&#10003;</span><span>' + _escHtml(a.description || '') + '</span></div>';
        }).join('');
        var html = '<div class="comm-actions-applied">' + items + '</div>';
        if (existing) {
          existing.outerHTML = html;
        } else {
          var form = card.querySelector('.comm-verdict-form');
          if (form) form.insertAdjacentHTML('beforeend', html);
        }
      }
    })
    .catch(function (err) {
      alert(_COMM.error_prefix + err);
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = _COMM.apply_verdict; }
    });
  }

  // ── Initialize / reset ────────────────────────────────────────────────────
  function _showRunning() {
    var setup   = document.getElementById('comm-setup');
    var running = document.getElementById('comm-running');
    if (setup)   setup.style.display   = 'none';
    if (running) running.style.display = '';
    var list = document.getElementById('comm-results-list');
    if (list) list.innerHTML = '';
  }

  function _resetToSetup() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    _checkId  = null;
    _verdicts = {};
    var setup   = document.getElementById('comm-setup');
    var running = document.getElementById('comm-running');
    if (setup)   setup.style.display   = '';
    if (running) running.style.display = 'none';
    var list = document.getElementById('comm-results-list');
    if (list) list.innerHTML = '';
    var fill = document.getElementById('comm-progress-fill');
    if (fill) fill.style.width = '0%';
    _resetBtnStart();
  }

  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'btn-comm-reset') {
      _resetToSetup();
    }
  });

  // ── Utils ─────────────────────────────────────────────────────────────────
  function _fmt(v) {
    if (v === null || v === undefined) return '-';
    return parseFloat(v).toFixed(2);
  }

  function _escHtml(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── Facility load hook: aot-facility-design.js dispatches the facilityLoaded event ──
  document.addEventListener('facilityLoaded', function (e) {
    var d = e.detail || {};
    var uuid = d.facility_uuid || d.unique_id || '';
    // actuators: normalize to [{actuator_id, kind, name}] form
    var acts = [];
    var raw = d.actuators || [];
    if (Array.isArray(raw)) {
      raw.forEach(function (a) {
        var id = a.actuator_id || a.device_uuid || '';
        if (id) acts.push({actuator_id: id, kind: a.kind || '', name: a.name || a.kind || id});
      });
    } else if (typeof raw === 'object') {
      Object.keys(raw).forEach(function (slot) {
        var id = raw[slot];
        if (id) acts.push({actuator_id: id, kind: slot, name: slot});
      });
    }
    if (uuid) initComm(uuid, acts);
  });

  // When facility_uuid is in the URL, load actuators from the integration API
  (function () {
    var vars = JSON.parse((document.getElementById('facility-page-vars') || {}).textContent || '{}');
    var fuid = vars.facility_uuid;
    if (!fuid) return;

    fetch('/api/geo/facility/' + fuid + '/integration')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) return;
        var acts = [];
        var ar = d.actuator_roles || [];
        ar.forEach(function (a) {
          var id = a.actuator_id || a.device_uuid || '';
          if (id) acts.push({actuator_id: id, kind: a.kind || '', name: a.name || a.kind || id});
        });
        initComm(fuid, acts);
      })
      .catch(function () {});
  })();

})();
