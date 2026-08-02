// group-ui.js — extracted from templates/pages/geo/geo_facility.html (2026-07-31).
// GroupUI — actuator groups (symmetric / stacked / multi-stage).
// Loaded as part of the geo-facility bundle, after aot-facility-design.js,
// so FittingsUI/EnvelopeUI and the _IEC/_COMM string catalogs already exist.

/* ── GroupUI — actuator group tab ──────────────────────────────────────────
   Edits the facility.groups JSON.
   Format: { group_id: { mode, leader, members[], threshold_pct } }

   Modes:
     symmetric   — follower = leader value (same opening ratio)
     stacked     — if leader > threshold_pct, follower = leader - threshold_pct
     multi_stage — open inner→outer, close outer→inner
──────────────────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  var _groups = [];   // [{id, mode, leader, members[], threshold_pct}]
  var _outputs = [];  // [{unique_id, name, output_type}] — /api/geo/outputs cache

  var GROUP_MODES = [
    { value: 'symmetric',   label: (window._ ? window._('Synchronous (symmetric)') : 'Synchronous (symmetric)') },
    { value: 'stacked',     label: (window._ ? window._('Stacked (stacked)') : 'Stacked (stacked)') },
    { value: 'multi_stage', label: (window._ ? window._('Staged (multi_stage)') : 'Staged (multi_stage)') },
  ];

  function _uid() {
    return 'G' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
  }

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _loadOutputs(cb) {
    if (_outputs.length) { cb(_outputs); return; }
    fetch('/api/geo/outputs', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { ok: false }; })
      .then(function (j) {
        _outputs = (j && j.ok && Array.isArray(j.outputs)) ? j.outputs : [];
        cb(_outputs);
      })
      .catch(function () { cb([]); });
  }

  function _outputName(uid) {
    var o = _outputs.find(function (x) { return x.unique_id === uid; });
    return o ? o.name : uid.slice(0, 8);
  }

  function render() {
    var tbody    = document.getElementById('group-config-tbody');
    var emptyRow = document.getElementById('group-config-empty');
    if (!tbody) return;

    Array.from(tbody.querySelectorAll('tr[data-group-id]')).forEach(function (tr) { tbody.removeChild(tr); });
    if (emptyRow) emptyRow.style.display = _groups.length ? 'none' : '';

    _groups.forEach(function (g) {
      var tr = document.createElement('tr');
      tr.dataset.groupId = g.id;
      
      // Mode select HTML
      var modeOpts = GROUP_MODES.map(function (m) {
        return '<option value="' + _esc(m.value) + '"' + (m.value === g.mode ? ' selected' : '') + '>' + _esc(m.label) + '</option>';
      }).join('');

      // Leader select HTML
      var leaderOpts = '<option value="">' + (window._ ? window._('— Select —') : '— Select —') + '</option>' + _outputs.map(function (o) {
        return '<option value="' + _esc(o.unique_id) + '"' + (o.unique_id === g.leader ? ' selected' : '') + '>' + _esc(o.name) + '</option>';
      }).join('');

      // Show followers (excluding leader)
      var followers = (g.members || []).filter(function (m) { return m !== g.leader; });
      var followerNames = followers.map(function (m) { return _outputName(m); }).join(', ') || '—';

      tr.innerHTML =
        '<td>' +
          '<input type="text" data-field="name" value="' + _esc(g.name || g.id) + '" ' +
            'class="aot-modern-input" placeholder="' + (window._ ? window._('Group name') : 'Group name') + '">' +
        '</td>' +
        '<td>' +
          '<select data-field="mode" class="aot-modern-select fac-cell-select">' + modeOpts + '</select>' +
        '</td>' +
        '<td>' +
          '<select data-field="leader" class="aot-modern-select fac-cell-select">' + leaderOpts + '</select>' +
        '</td>' +
        '<td>' +
          '<button type="button" data-members class="btn aot-pill-btn">' +
            _esc(followerNames) +
          '</button>' +
        '</td>' +
        '<td>' +
          '<input type="number" data-field="threshold_pct" value="' + (g.threshold_pct || 50) + '" min="0" max="100" ' +
            'class="aot-modern-input fac-cell-num"' +
            (g.mode !== 'stacked' ? ' disabled' : '') + '>' +
        '</td>' +
        '<td class="text-center">' +
          '<button type="button" data-del class="btn aot-pill-btn aot-pill-btn-primary">X</button>' +
        '</td>';

      tbody.appendChild(tr);

      // Edit name
      tr.querySelector('[data-field="name"]').addEventListener('input', function (e) {
        var gv = _groups.find(function (x) { return x.id === g.id; }); if (!gv) return;
        gv.name = e.target.value;
      });

      // Change mode
      tr.querySelector('[data-field="mode"]').addEventListener('change', function (e) {
        var gv = _groups.find(function (x) { return x.id === g.id; }); if (!gv) return;
        gv.mode = e.target.value;
        var thr = tr.querySelector('[data-field="threshold_pct"]');
        if (thr) thr.disabled = (gv.mode !== 'stacked');
      });

      // Change leader
      tr.querySelector('[data-field="leader"]').addEventListener('change', function (e) {
        var gv = _groups.find(function (x) { return x.id === g.id; }); if (!gv) return;
        gv.leader = e.target.value;
        // Add the leader to members if not present
        if (gv.leader && !gv.members.includes(gv.leader)) gv.members.unshift(gv.leader);
      });

      // Select followers (member edit popup)
      tr.querySelector('[data-members]').addEventListener('click', function () {
        _openMembersModal(g.id, tr.querySelector('[data-members]'));
      });

      // Threshold
      tr.querySelector('[data-field="threshold_pct"]').addEventListener('input', function (e) {
        var gv = _groups.find(function (x) { return x.id === g.id; }); if (!gv) return;
        gv.threshold_pct = parseFloat(e.target.value) || 50;
      });

      // Delete
      tr.querySelector('[data-del]').addEventListener('click', function () {
        _groups = _groups.filter(function (x) { return x.id !== g.id; });
        render();
      });
    });
  }

  // Member selection dropdown (inline checkboxes)
  function _openMembersModal(gid, btn) {
    var existing = document.getElementById('group-members-dropdown');
    if (existing) { existing.remove(); if (existing.dataset.gid === gid) return; }

    var gv = _groups.find(function (x) { return x.id === gid; }); if (!gv) return;

    var dd = document.createElement('div');
    dd.id = 'group-members-dropdown';
    dd.dataset.gid = gid;
    dd.className = 'fac-dropdown-panel';

    var rows = _outputs.map(function (o) {
      var checked = (gv.members || []).includes(o.unique_id) ? ' checked' : '';
      var isLeader = o.unique_id === gv.leader;
      return '<label class="ch-item">' +
        '<input type="checkbox" data-uid="' + _esc(o.unique_id) + '"' + checked + (isLeader ? ' disabled' : '') + '>' +
        '<span>' + _esc(o.name) + (isLeader ? ' <em class="text-muted">(' + (window._ ? window._('Leader') : 'Leader') + ')</em>' : '') + '</span>' +
        '</label>';
    }).join('');
    dd.innerHTML = rows + '<div class="text-right mt-2 px-2"><button type="button" id="group-members-done" ' +
      'class="btn aot-pill-btn aot-pill-btn-primary">' + (window._ ? window._('Done') : 'Done') + '</button></div>';

    var rect = btn.getBoundingClientRect();
    // Viewport coordinates: the panel is position:fixed like the channel picker,
    // so it escapes the drawer's scrolling/overflow instead of being clipped by it.
    dd.style.top  = (rect.bottom + 4) + 'px';
    dd.style.left = rect.left + 'px';
    document.body.appendChild(dd);

    dd.querySelector('#group-members-done').addEventListener('click', function () {
      var checked = Array.from(dd.querySelectorAll('input[data-uid]:checked')).map(function (c) { return c.dataset.uid; });
      // The leader is always included
      if (gv.leader && !checked.includes(gv.leader)) checked.unshift(gv.leader);
      gv.members = checked;
      dd.remove();
      render();
    });

    // Close on outside click
    setTimeout(function () {
      document.addEventListener('click', function _close(e) {
        if (!dd.contains(e.target) && e.target !== btn) { dd.remove(); document.removeEventListener('click', _close); }
      });
    }, 50);
  }

  function fill(groupsObj) {
    _groups = [];
    if (groupsObj && typeof groupsObj === 'object') {
      Object.keys(groupsObj).forEach(function (gid) {
        var gc = groupsObj[gid];
        _groups.push({
          id:            gid,
          name:          gc.name || gid,
          mode:          gc.mode || 'symmetric',
          leader:        gc.leader || '',
          members:       gc.members || [],
          threshold_pct: parseFloat(gc.threshold_pct) || 50,
        });
      });
    }
    _loadOutputs(render);
  }

  function read() {
    var result = {};
    _groups.forEach(function (g) {
      if (!g.leader || g.members.length < 2) return;
      result[g.id] = {
        name:          g.name || g.id,
        mode:          g.mode,
        leader:        g.leader,
        members:       g.members,
        threshold_pct: g.threshold_pct,
      };
    });
    return result;
  }

  function init() {
    var addBtn = document.getElementById('btn-add-group');
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        _loadOutputs(function () {
          _groups.push({
            id:            _uid(),
            name:          (window._ ? window._('New group') : 'New group'),
            mode:          'symmetric',
            leader:        '',
            members:       [],
            threshold_pct: 50,
          });
          render();
        });
      });
    }

    // Step bar replaced the old config tabs — refresh when this step opens.
    var tabBtn = document.querySelector('.fac-step[data-step="connect"]');
    if (tabBtn) {
      tabBtn.addEventListener('click', function () {
        _loadOutputs(render);
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.GroupUI = { fill: fill, read: read, render: render };
})();
