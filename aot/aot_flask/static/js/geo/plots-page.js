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

  /** 이 화면의 쓰기 경로 하나. `{status, data}` 로 풀어 준다 — 호출부마다
   *  `r.json()` 과 실패 판정을 다시 적으면 어느 한 곳이 조용히 빠진다.
   *  공용 단계 편집 블록(`AoTPlotStageEditor.wire`)에도 이것을 넘긴다. */
  function _api(method, url, body) {
    return fetch(url, {
      method: method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json',
                 'X-Requested-With': 'XMLHttpRequest',
                 'X-CSRFToken': _csrf() },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; })
        .then(function (d) { return { status: r.status, data: d || {} }; });
    }).catch(function () {
      return { status: 0, data: {} };
    });
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
    // **전부 받는다** — 좁히는 수단이 검색 하나뿐이라(필터 드롭다운을 없앴다),
    // 데이터가 빠져 있으면 아무리 쳐도 안 나온다. 지나간 것(종료)과 올 것
    // (계획)은 목록의 배지가 구분하므로 섞여 있어도 읽힌다.
    var qs = ['include_ended=1', 'include_planned=1'];
    el.list.innerHTML = '<div class="aot-plots-empty">' +
                        _esc(el.list.dataset.loading || '') + '</div>';
    // cache:'no-store' — 저장 직후 다시 부르는 경로가 있다. 브라우저 휴리스틱
    // 캐시가 옛 사본을 주면 "저장했는데 목록이 그대로" 가 된다.
    return fetch('/api/geo/plots?' + qs.join('&'),
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
  /** 검색 하나로 좁힌다 — 드롭다운 필터는 없앴다(템플릿 주석 참조). */
  function _matches(p) {
    var q = (el.q.value || '').trim().toLowerCase();
    if (!q) return true;
    // 사람이 기억하는 말로 찾는다 — 작물·품종·이름·시설·구역·대지·지도·프로그램.
    // uuid 는 넣지 않는다(사람이 그것으로 찾지 않고, 넣으면 무관한 항목이 걸린다).
    return [p.subject, p.variety, p.name, p.facility_name, p.bay_name,
            p.map_name, p.site_name, p.zone_name, (p.program || {}).name]
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

  // ── 편집 드로어 ────────────────────────────────────────────────────────
  //
  // 셸·문법은 **관리 프로그램 드로어와 같다**(`/geo/programs`). 같은 성격의 일
  // (재배 일정을 정하는 일)을 하는 두 화면이 서로 다른 모달 문법을 쓰면
  // 사용자가 화면마다 다시 배워야 한다.
  //
  // ⚠ 값은 **[저장]을 눌러야 반영된다** — 프로그램 드로어와 같은 약속이다.
  // 기본 정보와 단계 일정이 한 번에 나가므로, 한 드로어에 저장 규칙이 둘이 되는
  // 일이 없다.
  function openEdit(p) {
    p = p || {};
    if (!p.unique_id) return;
    S.editing = p.unique_id;
    var facUuid = p.facility_uuid || null;
    loadFacility(facUuid).then(function (fac) {
      var ctx = {
        attr: 'data-pf',
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

      // 그룹 제목 + 상자 — 프로그램 드로어의 `_group`/`_box` 와 같은 골격이다.
      var basics = '<div class="aot-modal-group-title">' + _esc(_t('Basics')) +
                   '</div><div class="aot-modal-container">' +
                   root.AoTPlotForm.rowsHtml(ctx) + '</div>';

      var stages = root.AoTPlotStages;
      stages.load(p);
      el.body.innerHTML = basics + stages.html();
      el.title.textContent = p.subject || p.name || _t('Plot');

      // 매번 드로어 본문을 통째로 다시 그리므로 이전 bootstrap-select DOM 도
      // 함께 사라진다 — `refresh` 가 아니라 새 초기화를 부른다. 이것이 없으면
      // 프로그램 select 는 bootstrap-select 자체 CSS(`select.selectpicker
      // { display: none }`)에 걸려 화면에서 통째로 사라진다.
      if (root.jQuery && root.jQuery.fn && root.jQuery.fn.selectpicker) {
        root.jQuery(el.body).find('.selectpicker').selectpicker();
      }

      var form = el.body.querySelector('.aot-modal-container');
      el.body._ctx = ctx;
      root.AoTPlotForm.wire(form, ctx);
      stages.wire(el.body);

      // 프로그램이 없으면 등록할 일정도 없다.
      if (el.btnReg) el.btnReg.hidden = !stages.has();

      if (root.jQuery) root.jQuery('#plot-drawer').modal('show');
    });
  }

  /** 기본 정보 + 단계 일정을 **한 번에** 저장한다. */
  function save() {
    var ctx = el.body._ctx || { attr: 'data-pf' };
    var form = el.body.querySelector('.aot-modal-container');
    var payload = root.AoTPlotForm.collect(form, ctx);
    if (!payload.subject) {
      _toast(_t('Enter what is planted.'), 'warning');
      return Promise.resolve(false);
    }
    payload.unique_id = S.editing;

    var stages = root.AoTPlotStages;
    // 구획 자신의 값(자동 전환)은 기본 정보와 같은 저장에 실린다.
    var extra = stages.plotFields();
    Object.keys(extra).forEach(function (k) { payload[k] = extra[k]; });

    // 프로그램을 바꾸면 일정이 통째로 그 프로그램의 것으로 바뀐다 — 옛 단계
    // 키를 가리키는 편집을 함께 보내면 서버가 없는 키로 거절한다.
    var was = (S.rows.filter(function (x) {
      return x.unique_id === S.editing;
    })[0] || {});
    var progChanged = (payload.program_uuid || '') !==
                      ((was.program || {}).unique_id || '');

    if (el.btnSave) el.btnSave.disabled = true;
    return _api('POST', '/api/geo/plot', payload).then(function (res) {
      if (res.status >= 400 || !res.data.ok) {
        // 서버가 거절한 이유를 그대로 보인다 — 권한이든 검증이든 화면이
        // 지어내지 않는다(원칙 4).
        return { ok: false, message: res.data.message || _t('Save failed') };
      }
      if (progChanged) return { ok: true };
      return stages.save(el.body, _api);
    }).then(function (out) {
      if (el.btnSave) el.btnSave.disabled = false;
      if (!out.ok) {
        _toast(out.message || _t('Save failed'), 'error');
        return false;
      }
      _toast(_t('Saved.'), 'success');
      return reload().then(function () { return true; });
    });
  }

  /** 이 구획의 일정을 프로그램으로 — 프로그램 드로어의 [복제]와 같은 성격이다.
   *
   * 등록은 **복사**다(서버가 지금 저장된 일정을 읽는다). 그래서 고치던 것이
   * 남아 있으면 먼저 저장한다 — 안 그러면 화면에서 본 것과 다른 것이 등록된다.
   * 이름은 서버가 짓는다(겹치면 번호를 붙인다) — 프로그램 페이지에서 고친다. */
  function registerAsProgram() {
    var stages = root.AoTPlotStages;
    var pre = stages.dirty(el.body) ? save() : Promise.resolve(true);
    pre.then(function (okToGo) {
      if (!okToGo) return;
      if (el.btnReg) el.btnReg.disabled = true;
      _api('POST', '/api/geo/plot/' + encodeURIComponent(S.editing) +
           '/save-as-program', {}).then(function (res) {
        if (el.btnReg) el.btnReg.disabled = false;
        if (res.status >= 400 || !res.data.ok) {
          _toast(res.data.message || _t('Save failed'), 'error');
          return;
        }
        // 만들어진 이름을 그대로 말한다 — 겹치면 서버가 번호를 붙이므로
        // 사용자가 짐작한 것과 다를 수 있다.
        var nm = (res.data.program || {}).name || '';
        _toast(_t('Registered as a programme: %(name)s').replace('%(name)s', nm),
               'success');
      });
    });
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
    el.count = document.getElementById('plot-count');
    el.list = document.getElementById('plot-list');
    el.body = document.getElementById('plot-drawer-body');
    el.title = document.getElementById('plotDrawerLabel');
    el.btnSave = document.getElementById('plot-drawer-save');
    el.btnReg = document.getElementById('plot-drawer-reg');
    if (!el.list) return;

    // 좁히는 수단은 검색 하나다 — **받아 둔 목록 안에서** 거른다(왕복 없음).
    el.q.addEventListener('input', render);

    if (el.btnSave) el.btnSave.addEventListener('click', function () {
      save().then(function (ok) {
        if (ok && root.jQuery) root.jQuery('#plot-drawer').modal('hide');
      });
    });
    if (el.btnReg) el.btnReg.addEventListener('click', registerAsProgram);

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
