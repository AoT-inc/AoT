/* 구획 운영 페이지(`/plots`) — 전체 목록·검색·편집.
 *
 * ## 이 화면이 있는 이유
 *
 * 구획의 중간 지점은 지도 위젯 모달이고 그 판단은 유지된다(일반 사용자의
 * 세계는 대시보드다). 다만 모달은 **하나의 대상**을 다루기에 적합하고, 구획은
 * 수가 느는 대상이라 곧 감당이 안 된다 — "이번 철에 무엇을 어디에 심었나" 는
 * 지도를 세 번 오가며 답할 질문이 아니다.
 *
 * ## 폼을 여기서 다시 적지 않는다
 *
 * 편집 모달의 본문은 공용 컴포넌트(`common/aot-plot-form.js`)가 만든다. 이
 * 화면이 자기 폼을 적으면 4단계에서 한 벌로 모은 것이 **네 벌째로 갈린다** —
 * 이 문서가 없애려던 상태 그대로다.
 *
 * ## 권한
 *
 * 목록은 누구나 본다(보기는 전원 공개, 그룹은 조작만 제한한다). 편집 가능
 * 여부는 서버가 판정해 내려준 값(`can_edit`)만 쓴다 — 화면이 스스로 판단하면
 * 곧 갈라지고, 그 갈라짐은 "눌러도 403" 으로만 드러난다.
 */
(function (root) {
  'use strict';

  function _t(key) {
    var fn = root._;
    return (typeof fn === 'function') ? fn(key) : key;
  }

  function _esc(x) {
    return String(x == null ? '' : x).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function _csrf() {
    var el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute('content') : '';
  }

  var S = {
    canEdit: false,
    canDesign: false,
    rows: [],
    programs: {},        // kind → list (공용 폼이 loadPrograms 로 받아 간다)
    facilities: {},      // facility_uuid → {bays, capacities}
    editing: null        // 편집 중인 구획 uuid (신규는 null)
  };

  var el = {};

  // ── 데이터 ────────────────────────────────────────────────────────────
  function loadPrograms(kind) {
    kind = kind || 'vegetation';
    if (S.programs[kind]) return Promise.resolve(S.programs[kind]);
    return fetch('/api/geo/programs?kind=' + encodeURIComponent(kind),
                 { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        S.programs[kind] = (res && res.ok) ? (res.programs || []) : [];
        return S.programs[kind];
      })
      .catch(function () { S.programs[kind] = []; return S.programs[kind]; });
  }

  function reload() {
    var qs = [];
    var mapId = el.map.value;
    if (mapId) qs.push('map_uuid=' + encodeURIComponent(mapId));
    if (el.ended.checked) qs.push('include_ended=1');
    // 계획(시작 전)은 **언제나** 받는다. 지도는 안 그리지만 이 화면은 목록이고,
    // 앞으로 심을 것이 빠지면 계획을 세운 사람이 자기가 만든 것을 어디서도 못
    // 찾는다(예전에는 [종료 포함] 을 켜야 겨우 보였다 — 종료와 예정이 같은
    // 칸에 있으니 찾을 이유가 없는 자리였다).
    qs.push('include_planned=1');
    el.list.innerHTML = '<div class="aot-plots-empty">' +
                        _esc(el.list.dataset.loading || '') + '</div>';
    // cache:'no-store' — 저장 직후 다시 부르는 경로가 있다. 브라우저 휴리스틱
    // 캐시가 옛 사본을 주면 "저장했는데 목록이 그대로" 가 된다.
    return fetch('/api/geo/plots' + (qs.length ? '?' + qs.join('&') : ''),
                 { cache: 'no-store', credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        S.rows = (res && res.ok) ? (res.plots || []) : [];
        render();
      })
      .catch(function () { S.rows = []; render(); });
  }

  /** 시설 구획을 편집하려면 그 시설의 구역·총량이 필요하다(몫 접미). */
  function loadFacility(uuid) {
    if (!uuid) return Promise.resolve(null);
    if (S.facilities[uuid]) return Promise.resolve(S.facilities[uuid]);
    return fetch('/api/geo/facility/' + encodeURIComponent(uuid),
                 { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        var f = (res && (res.facility || res)) || {};
        S.facilities[uuid] = {
          bays: (f.bay_slices || []).map(function (s) {
            return { id: s.id, name: s.name };
          }),
          capacities: f.bay_capacities || {}
        };
        return S.facilities[uuid];
      })
      .catch(function () {
        S.facilities[uuid] = { bays: [], capacities: {} };
        return S.facilities[uuid];
      });
  }

  // ── 목록 ──────────────────────────────────────────────────────────────
  function _matches(p) {
    var kind = el.kind.value;
    if (kind && (p.kind || 'vegetation') !== kind) return false;
    var q = (el.q.value || '').trim().toLowerCase();
    if (!q) return true;
    // 사람이 기억하는 말로 찾는다 — 작물·품종·이름·시설·지도. uuid 는 넣지
    // 않는다(사람이 그것으로 찾지 않고, 넣으면 무관한 항목이 걸린다).
    return [p.subject, p.variety, p.name, p.facility_name, p.bay_name,
            p.map_name, (p.program || {}).name]
      .some(function (x) { return x && String(x).toLowerCase().indexOf(q) >= 0; });
  }

  function _where(p) {
    // 어디에 있는가 — 시설 구획은 시설·구역, 노지는 지도.
    var bits = [];
    if (p.facility_name) {
      bits.push(p.facility_name);
      if (p.bay_name && p.bay_name !== p.facility_name) bits.push(p.bay_name);
    }
    if (p.map_name) bits.push(p.map_name);
    return bits.join(' · ');
  }

  function _rowHtml(p) {
    var right = [];
    if (p.days_since_planted != null) {
      right.push(_t('Day %(n)s').replace('%(n)s', String(p.days_since_planted)));
    }
    if (p.stage && p.stage.state === 'running' && p.stage.name) {
      right.push(p.stage.name);
    }
    var alloc = (root.AoTPlotForm && p.allocation)
      ? _allocText(p.allocation) : '';
    if (alloc) right.push(alloc);
    if (p.area_m2 != null) right.push(Number(p.area_m2).toLocaleString() + ' m²');
    // 종료된 작기는 목록에서 그 사실이 **먼저** 보여야 한다 — 안 그러면
    // 이력을 켠 사람이 지금 자라는 것으로 읽는다.
    var ended = p.ended_on
      ? '<span class="aot-plots-ended-badge">' + _esc(_t('Ended')) + '</span>' : '';
    // 아직 시작 전 — 종료와 **같은 자리**에 둔다(둘 다 "지금 자라는 것이
    // 아니다" 를 말한다). 남은 날을 함께 적는 이유는 날짜만으로는 사람이
    // 오늘과 빼야 하고, 목록의 모든 줄에서 그 뺄셈이 반복되기 때문이다.
    var planned = p.planned
      ? '<span class="aot-plots-planned-badge">' +
        _esc(p.days_until_start != null
             ? _t('In %(n)s days').replace('%(n)s', String(p.days_until_start))
             : _t('Planned')) + '</span>' : '';

    return '<div class="aot-plots-row" data-uuid="' + _esc(p.unique_id) + '">' +
           '<div class="aot-plots-main">' +
           '<span class="aot-plots-subject">' + _esc(p.subject || p.name || '—') +
           '</span>' +
           (p.variety ? '<span class="aot-plots-variety">' + _esc(p.variety) +
                        '</span>' : '') +
           ended + planned +
           '<span class="aot-plots-where">' + _esc(_where(p)) + '</span>' +
           '</div>' +
           '<div class="aot-plots-meta">' + _esc(right.join(' · ')) + '</div>' +
           (S.canEdit
             ? '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm ' +
               'aot-plots-edit">' + _esc(_t('Edit')) + '</button>'
             : '') +
           '</div>';
  }

  function _allocText(a) {
    if (!a) return '';
    if (a.amount != null && a.total) {
      return a.amount + '/' + a.total + ' ' +
             root.AoTPlotForm.capUnitLabel(a.unit) +
             (a.percent != null ? ' · ' + a.percent + '%' : '');
    }
    if (a.percent != null) return a.percent + '%';
    if (a.amount != null) return String(a.amount);
    return '';
  }

  function render() {
    var rows = S.rows.filter(_matches);
    el.count.textContent = _t('%(n)s items').replace('%(n)s', String(rows.length));
    if (!rows.length) {
      el.list.innerHTML = '<div class="aot-plots-empty">' +
                          _esc(el.list.dataset.empty || '') + '</div>';
      return;
    }
    el.list.innerHTML = rows.map(_rowHtml).join('');
  }

  // ── 편집 ──────────────────────────────────────────────────────────────
  function openEdit(p) {
    p = p || {};
    S.editing = p.unique_id || null;
    var facUuid = p.facility_uuid || null;
    loadFacility(facUuid).then(function (fac) {
      var ctx = {
        attr: 'data-pf',
        // 시설이 붙어 있으면 시설 구획이다 — 구역·몫이 나온다. 새로 만들 때는
        // 노지로 시작한다(지도에 그리는 것은 이 화면의 일이 아니다).
        target: facUuid ? 'facility' : 'ground',
        values: p,
        kind: p.kind || 'vegetation',
        bays: fac ? fac.bays : [],
        capacities: fac ? fac.capacities : {},
        bayId: p.bay_id || null,
        programs: S.programs[p.kind || 'vegetation'] || [],
        include: ['name'],
        canDesign: S.canDesign,
        today: _today(),
        loadPrograms: loadPrograms
      };
      el.editBody.innerHTML = '<div class="aot-modal-container">' +
        root.AoTPlotForm.rowsHtml(ctx) + '</div>';
      el.editTitle.textContent = p.unique_id
        ? (p.subject || _t('Plot')) : _t('Add a plot');
      el.editBody._ctx = ctx;
      root.AoTPlotForm.wire(el.editBody, ctx);
      if (root.jQuery) root.jQuery('#plotEditModal').modal('show');
    });
  }

  function save() {
    var ctx = el.editBody._ctx || { attr: 'data-pf' };
    var payload = root.AoTPlotForm.collect(el.editBody, ctx);
    if (!payload.subject) {
      _toast(_t('Enter what is planted.'), 'warning');
      return;
    }
    if (S.editing) payload.unique_id = S.editing;
    // 새로 만들 때는 지도가 필요하다. 시설을 고른 경우에는 서버가 시설에서
    // 지도를 안다(`plot_io.save_plot`) — 그래서 여기서는 필터의 지도만 쓴다.
    if (!S.editing && !payload.facility_uuid) {
      var mapId = el.map.value;
      if (!mapId) {
        // 지도 없이 노지 구획을 만들 수는 없다(기하가 어디에 그려질지 모른다).
        // 이 화면은 도형을 그리지 않으므로, 새로 만들기는 시설 구획만 받는다.
        _toast(_t('Pick a map first.'), 'warning');
        return;
      }
      payload.map_uuid = mapId;
    }
    fetch('/api/geo/plot', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json',
                 'X-Requested-With': 'XMLHttpRequest',
                 'X-CSRFToken': _csrf() },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (j) {
        if (!j || !j.ok) {
          // 서버가 거절한 이유를 그대로 보인다 — 권한이든 검증이든 화면이
          // 지어내지 않는다(원칙 4).
          _toast((j && j.message) || _t('Save failed'), 'error');
          return;
        }
        if (root.jQuery) root.jQuery('#plotEditModal').modal('hide');
        _toast(_t('Saved.'), 'success');
        reload();
      })
      .catch(function () { _toast(_t('Save failed'), 'error'); });
  }

  function _today() {
    var d = new Date();
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }

  function _toast(msg, level) {
    if (root.showToast) root.showToast(msg, level || 'info');
  }

  // ── 배선 ──────────────────────────────────────────────────────────────
  function init(opts) {
    opts = opts || {};
    S.canEdit = !!opts.canEdit;
    S.canDesign = !!opts.canDesign;

    el.q = document.getElementById('plot-q');
    el.map = document.getElementById('plot-map');
    el.kind = document.getElementById('plot-kind');
    el.ended = document.getElementById('plot-ended');
    el.count = document.getElementById('plot-count');
    el.list = document.getElementById('plot-list');
    el.editBody = document.getElementById('plot-edit-body');
    el.editTitle = document.getElementById('plot-edit-title');
    if (!el.list) return;

    // 검색·종류는 **받아 둔 목록 안에서** 거른다(왕복 없음). 지도·이력은
    // 서버가 정하는 축이라 다시 받는다.
    el.q.addEventListener('input', render);
    el.kind.addEventListener('change', render);
    el.map.addEventListener('change', reload);
    el.ended.addEventListener('change', reload);

    var btnNew = document.getElementById('plot-new');
    if (btnNew) btnNew.addEventListener('click', function () { openEdit(null); });

    var btnSave = document.getElementById('plot-edit-save');
    if (btnSave) btnSave.addEventListener('click', save);

    // 목록은 매번 다시 그려지므로 위임으로 듣는다.
    el.list.addEventListener('click', function (e) {
      var btn = e.target.closest('.aot-plots-edit');
      if (!btn) return;
      var row = btn.closest('.aot-plots-row');
      var uuid = row && row.dataset.uuid;
      var p = S.rows.filter(function (x) { return x.unique_id === uuid; })[0];
      if (p) openEdit(p);
    });

    loadPrograms('vegetation');
    reload();
  }

  root.AoTPlots = { init: init, reload: reload };
})(window);
