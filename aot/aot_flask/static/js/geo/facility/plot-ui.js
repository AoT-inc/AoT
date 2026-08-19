// plot-ui.js — 시설 편집기의 "식생" 스텝.
//
// 시설 구획은 **기하를 그리지 않는다.** 위치의 정본이 구역 자체이기 때문이다
// (docs/design/geo-vegetation-planting.md §시설 구획 — 위치의 정본은 부모다).
// 그래서 이 화면에는 그리기 도구가 없고, 구역을 고르고 작물을 적는 것이 전부다.
//
// ## 여기서 하지 않는 것
//
// - **운영 정보**(노트·이력·센서 값·제어)를 두지 않는다. 이 페이지는 도형과
//   설비를 정의하는 곳이고, 일반 사용자는 여기 오지 않는다 — 그쪽은 대시보드
//   위젯의 구획 모달이 맡는다(geo/design 과 같은 분담).
// - **면적·식재량을 보여주지 않는다.** 시설은 노지형·베드형·수직형에 따라 같은
//   바닥 면적의 재배 규모가 전혀 다르다. 서버도 내지 않는다.
//
// ## 저장은 시설 저장과 **분리**돼 있다
//
// 여기의 모든 작업은 즉시 `/api/geo/plot` 을 지난다. 시설 저장 페이로드에
// 실어 보내지 않는다 — `save_facility` 가 전량교체 저장이라, 거기에 식생을
// 얹으면 시설을 저장할 때마다 "페이로드에 없는 것 = 지운 것" 이 될 위험이 생긴다
// (`saveOverlays` 가 식생을 자기 것으로 착각하면 안 되는 것과 같은 이유).
(function () {
  'use strict';

  function _T(k, f) {
    var d = (typeof window !== 'undefined' && window._IEC) || {};
    return (d[k] != null && d[k] !== '') ? d[k] : f;
  }

  function _csrf() {
    var el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute('content') : '';
  }

  function _api(method, url, body) {
    return fetch(url, {
      method: method,
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': _csrf()
      },
      body: body ? JSON.stringify(body) : undefined
    }).then(function (res) {
      return res.json().catch(function () { return {}; })
        .then(function (data) { return { status: res.status, data: data }; });
    });
  }

  function _today() {
    // 로컬 날짜. toISOString() 은 UTC 라 한국 오전에는 하루 전이 나오고,
    // 파종일이 하루 어긋나면 생육일수가 통째로 밀린다.
    var d = new Date();
    var p = function (n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }

  function _toast(msg, level) {
    if (window.showToast) window.showToast(msg, level || 'info');
  }

  function _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  var State = {
    programs: {},      // 종류별 관리 프로그램 선택지 (종류마다 한 번만 받는다)
    facilityUuid: null,
    mapUuid: null,
    bays: [],        // [{id, name}]
    rows: [],        // GeoPlot dict
    editing: null,   // 편집 중인 구획 uuid (신규는 null)
    formBay: null    // 폼이 열려 있는 구역 id (null = 폼 닫힘)
  };

  // ── 로드 ──────────────────────────────────────────────────────────────
  /**
   * 시설이 바뀔 때마다 호출된다. `facility` 는 `/api/geo/facility/<uuid>` 의
   * dict — `bay_slices` 가 구역 목록의 정본이다(서버가 만든다).
   */
  function setFacility(facility) {
    facility = facility || {};
    State.facilityUuid = facility.unique_id || null;
    State.mapUuid = facility.geo_id || null;
    State.bays = (facility.bay_slices || []).map(function (s) {
      return { id: s.id, name: s.name };
    });
    // 치수를 아직 안 넣어 슬라이스를 못 만드는 시설도 구역 하나는 있어야
    // 작물을 적을 수 있다 — 단동은 서버가 'bay_1' 로 채운다.
    if (!State.bays.length) {
      State.bays = [{ id: 'bay_1',
                      name: facility.name || _T('zone_bay', 'Bay') + ' 1' }];
    }
    State.editing = null;
    State.formBay = null;
    loadPrograms('vegetation').then(render);
    reload();
  }

  /**
   * 재배 프로그램 목록을 한 번만 받아 둔다.
   *
   * 프로그램은 자주 바뀌지 않고 구획마다 같은 목록을 쓰므로, 폼을 열 때마다
   * 다시 받을 이유가 없다. 새로 만든 프로그램은 페이지를 다시 열면 잡힌다.
   */
  function loadPrograms(kind) {
    // **종류별로 캐시한다.** 한 벌만 두면 종류를 바꾼 뒤 목록이 옛 종류의
    // 것으로 남고, 그것을 고른 저장을 서버가 거절한다 — 화면에 보이는
    // 선택지가 저장되지 않는 상태가 된다.
    kind = kind || 'vegetation';
    if (State.programs[kind]) return Promise.resolve(State.programs[kind]);
    return fetch('/api/geo/programs?kind=' + encodeURIComponent(kind),
                 { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        State.programs[kind] = (res && res.ok) ? (res.programs || []) : [];
        return State.programs[kind];
      })
      .catch(function () { State.programs[kind] = []; return State.programs[kind]; });
  }

  /** 대상 종류 select — `GeoProgram.kind` 와 같은 어휘. */
  function _kindRow(r) {
    var labels = { vegetation: _T('kind_vegetation', 'Vegetation'),
                   livestock: _T('kind_livestock', 'Livestock'),
                   facility: _T('kind_facility', 'Facility'),
                   other: _T('kind_other', 'Other') };
    var cur = r.kind || 'vegetation';
    var opts = '';
    ['vegetation', 'livestock', 'facility', 'other'].forEach(function (k) {
      opts += '<option value="' + k + '"' + (k === cur ? ' selected' : '') + '>' +
              _esc(labels[k]) + '</option>';
    });
    return '<div class="aot-modal-option-row">' +
           '<label class="aot-modal-option-label">' + _T('plot_kind', 'Kind') + '</label>' +
           '<div class="aot-modal-option-control">' +
           '<select class="form-control aot-modern-input" data-f="kind">' +
           opts + '</select></div></div>';
  }

  function reload() {
    if (!State.facilityUuid || !State.mapUuid) {
      State.rows = [];
      render();
      return Promise.resolve();
    }
    var url = '/api/geo/plots?map_uuid=' +
      encodeURIComponent(State.mapUuid) + '&facility_uuid=' +
      encodeURIComponent(State.facilityUuid);
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        State.rows = (res && res.ok) ? (res.plots || []) : [];
        render();
      })
      .catch(function () { State.rows = []; render(); });
  }

  // ── 렌더 ──────────────────────────────────────────────────────────────
  function _rowsFor(bayId) {
    return State.rows.filter(function (r) {
      // 다동에서 bay_id 가 비어 있으면 "시설 전체" 라, 어느 구역에도 속하지
      // 않는다. 아래에서 따로 묶어 보여 준다.
      return r.bay_id === bayId;
    });
  }

  function _wholeFacilityRows() {
    return State.rows.filter(function (r) { return !r.bay_id; });
  }

  function _plotLine(r) {
    var bits = [_esc(r.subject)];
    if (r.variety) bits.push(_esc(r.variety));
    var days = (r.days_since_planted != null)
      ? _T('plot_day_n', 'Day {n}').replace('{n}', r.days_since_planted)
      : '';
    // 프로그램을 따르고 있으면 그 사실을 보인다 — 목표가 어디서 오는지가
    // 값 자체만큼 중요하다.
    if (r.program && r.program.name) bits.push(_esc(r.program.name));
    // 프로그램이 있으면 지금 어느 단계인지가 일수보다 직접적이다.
    if (r.stage && r.stage.state === 'running') {
      bits.push(_esc(r.stage.name) + ' ' + r.stage.index + '/' + r.stage.total);
    }
    return '' +
      '<div class="aot-modal-detail-field fac-plot-row" data-uuid="' + _esc(r.unique_id) + '">' +
        '<label>' + bits.join(' · ') + '</label>' +
        '<div class="fac-plot-row-meta">' +
          '<span class="aot-modal-body-text">' + _esc(r.started_on || '') +
            (days ? ' · ' + _esc(days) : '') + '</span>' +
          '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" data-act="edit">' +
            _T('edit', 'Edit') + '</button>' +
          '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" data-act="end">' +
            _T('plot_end', 'End') + '</button>' +
          '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" data-act="delete">' +
            _T('delete', 'Delete') + '</button>' +
        '</div>' +
      '</div>';
  }

  /**
   * 재배 프로그램 선택 줄.
   *
   * 프로그램이 있으면 단계·기간·목표가 여기서 따라온다 — 사람이 적는 것은
   * 작물·품종·파종일·프로그램 넷뿐이 된다. 없으면 종전대로 동작하므로 빈 값이
   * 기본이다("프로그램 없음").
   *
   * 목록이 비어 있으면(시드 전) 줄 자체를 내지 않는다 — 고를 것이 없는 칸은
   * 화면만 길게 만든다.
   */
  function _programRow(r) {
    var list = State.programs[(r && r.kind) || 'vegetation'] || [];
    if (!list.length) return '';
    var cur = (r && r.program && r.program.unique_id) || '';
    var opts = '<option value="">' +
               _T('plot_program_none', 'No program') + '</option>';
    list.forEach(function (p) {
      var label = _esc(p.name) +
                  (p.variety ? ' · ' + _esc(p.variety) : '') +
                  (p.stage_count ? ' (' + p.stage_count +
                   _T('plot_stage_unit', ' stages') + ')' : '');
      opts += '<option value="' + _esc(p.unique_id) + '"' +
              (p.unique_id === cur ? ' selected' : '') + '>' + label + '</option>';
    });
    return '<div class="aot-modal-option-row">' +
           '<label class="aot-modal-option-label">' +
           _T('plot_program', 'Program') + '</label>' +
           '<div class="aot-modal-option-control">' +
           '<select class="form-control aot-modern-input" data-f="program_uuid">' +
           opts + '</select></div></div>';
  }

  function _form(bayId) {
    var r = State.editing
      ? State.rows.filter(function (x) { return x.unique_id === State.editing; })[0]
      : null;
    r = r || {};
    return '' +
      '<div class="aot-modal-container fac-plot-form" data-bay="' + _esc(bayId || '') + '">' +
        _kindRow(r) +
        '<div class="aot-modal-option-row">' +
          '<label class="aot-modal-option-label">' + _T('plot_subject', 'What is here') + '</label>' +
          '<div class="aot-modal-option-control">' +
            '<input type="text" class="form-control aot-modern-input" data-f="subject" value="' +
              _esc(r.subject || '') + '" placeholder="' + _T('plot_subject', 'What is here') + '">' +
          '</div>' +
        '</div>' +
        '<div class="aot-modal-option-row">' +
          '<label class="aot-modal-option-label">' + _T('plot_variety', 'Variety') + '</label>' +
          '<div class="aot-modal-option-control">' +
            '<input type="text" class="form-control aot-modern-input" data-f="variety" value="' +
              _esc(r.variety || '') + '">' +
          '</div>' +
        '</div>' +
        '<div class="aot-modal-option-row">' +
          '<label class="aot-modal-option-label">' + _T('plot_started_on', 'Start date') + '</label>' +
          '<div class="aot-modal-option-control">' +
            '<input type="date" class="form-control aot-modern-input" data-f="started_on" value="' +
              _esc(r.started_on || _today()) + '">' +
          '</div>' +
        '</div>' +
        _programRow(r) +
        '<div class="aot-modal-option-row">' +
          '<label class="aot-modal-option-label">' + _T('plot_expected_end', 'Expected end') + '</label>' +
          '<div class="aot-modal-option-control">' +
            '<input type="date" class="form-control aot-modern-input" data-f="expected_end_on" value="' +
              _esc(r.expected_end_on || '') + '">' +
          '</div>' +
        '</div>' +
        '<div class="aot-modal-option-row" style="border-bottom:none;">' +
          '<div class="aot-modal-option-label"></div>' +
          '<div class="aot-modal-option-control">' +
            '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary" data-act="save">' +
              _T('save', 'Save') + '</button> ' +
            '<button type="button" class="btn aot-pill-btn" data-act="cancel">' +
              _T('cancel', 'Cancel') + '</button>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  function _bayBlock(bay) {
    var rows = _rowsFor(bay.id);
    var body = rows.length
      ? '<div class="aot-modal-detail-fields">' + rows.map(_plotLine).join('') + '</div>'
      : '<div class="aot-modal-body-text">' + _T('plot_empty', 'Nothing recorded here yet.') + '</div>';
    var form = (State.formBay === bay.id) ? _form(bay.id) : '';
    return '' +
      '<div class="aot-modal-group-title">' + _esc(bay.name || bay.id) + '</div>' +
      '<div class="aot-modal-container" data-bay="' + _esc(bay.id) + '">' +
        body +
        (form ? '' :
          '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" data-act="add">' +
            _T('plot_add', 'Add a plot') + '</button>') +
      '</div>' + form;
  }

  function render() {
    var box = document.getElementById('fac-plot-body');
    if (!box) return;

    if (!State.facilityUuid) {
      // 구획은 시설에 매달리므로 시설이 저장돼 있어야 만들 수 있다. 숨기지 않고
      // 이유를 말한다 — 빈 화면은 고장으로 읽힌다(check 스텝과 같은 태도).
      box.innerHTML = '<div class="aot-modal-container"><div class="aot-modal-body-text">' +
        _T('plot_save_first', 'Save the facility first, then record what is in each zone.') +
        '</div></div>';
      return;
    }

    var html = State.bays.map(_bayBlock).join('');

    var whole = _wholeFacilityRows();
    if (whole.length) {
      html += '<div class="aot-modal-group-title">' +
        _T('plot_whole_facility', 'Whole facility') + '</div>' +
        '<div class="aot-modal-container"><div class="aot-modal-detail-fields">' +
        whole.map(_plotLine).join('') + '</div></div>';
    }
    box.innerHTML = html;
  }

  // ── 동작 ──────────────────────────────────────────────────────────────
  function _readForm(formEl) {
    var out = {};
    formEl.querySelectorAll('[data-f]').forEach(function (el) {
      out[el.dataset.f] = (el.value || '').trim() || null;
    });
    return out;
  }

  function _save(formEl) {
    var bayId = formEl.dataset.bay || null;
    var values = _readForm(formEl);
    if (!values.subject) {
      _toast(_T('plot_subject_required', 'Enter what is here.'), 'warning');
      return;
    }
    var payload = {
      map_uuid: State.mapUuid,
      facility_uuid: State.facilityUuid,
      bay_id: bayId,
      subject: values.subject,
      variety: values.variety,
      started_on: values.started_on || _today(),
      expected_end_on: values.expected_end_on
    };
    payload.kind = values.kind || 'vegetation';
    // 선택지가 없는 화면(시드 전)에서는 키 자체를 보내지 않는다 — 보내면
    // 부분 저장 규칙상 "프로그램 해제"로 읽힌다.
    if ((State.programs[payload.kind] || []).length) {
      payload.program_uuid = values.program_uuid || '';
    }
    if (State.editing) {
      payload.unique_id = State.editing;
      // 수정에서는 시설·구역을 함께 보낸다 — 구역 이동을 허용하기 위해서다.
      // 종료된 작기의 이동은 서버가 거부한다(VP-6).
    }
    _api('POST', '/api/geo/plot', payload).then(function (r) {
      if (r.status >= 400 || !r.data.ok) {
        _toast(r.data.message || _T('save_failed', 'Save failed'), 'error');
        return;
      }
      State.editing = null;
      State.formBay = null;
      _toast(_T('saved', 'Saved.'), 'success');
      reload();
    });
  }

  function _end(uuid) {
    if (!window.confirm(_T('plot_end_confirm',
        'End this plot? The record stays as history.'))) return;
    _api('POST', '/api/geo/plot/' + encodeURIComponent(uuid) + '/end', {})
      .then(function (r) {
        if (r.status >= 400 || !r.data.ok) {
          _toast(r.data.message || _T('save_failed', 'Save failed'), 'error');
          return;
        }
        reload();
      });
  }

  function _delete(uuid) {
    // 정상 종료는 `end` 다. 이것은 잘못 적은 것을 없애는 경로라, 이력이 사라진다는
    // 것을 문구로 구분해 말한다.
    if (!window.confirm(_T('plot_delete_confirm',
        'Delete this record? Use "End" instead if it was actually grown — deleting removes it from the history.'))) return;
    _api('DELETE', '/api/geo/plot/' + encodeURIComponent(uuid))
      .then(function (r) {
        if (r.status >= 400 || !r.data.ok) {
          _toast(r.data.message || _T('delete_failed', 'Delete failed'), 'error');
          return;
        }
        reload();
      });
  }

  /**
   * 첫 화면을 채운다.
   *
   * `facility-loaded` 만 믿으면 안 된다 — 편집기가 페이지 로드 중에 시설을 열면
   * 그 이벤트는 이 모듈이 붙기 전에 이미 지나갔을 수 있고, 그러면 식생 스텝은
   * **아무것도 없는 빈 칸**으로 열린다(빈 화면은 고장으로 읽힌다). 지금 열려
   * 있는 시설을 직접 물어 초기 상태를 만든다.
   */
  function initFromCurrent() {
    var uuid = (window.FacilityIO && typeof FacilityIO.current === 'function')
      ? FacilityIO.current() : null;
    if (!uuid) { render(); return; }        // 저장 전 — 안내 문구를 띄운다
    fetch('/api/geo/facility/' + encodeURIComponent(uuid),
          { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) { setFacility((j && j.ok && j.facility) || {}); })
      .catch(function () { render(); });
  }

  function wire() {
    var box = document.getElementById('fac-plot-body');
    if (!box || box.dataset.wired) return;
    box.dataset.wired = '1';

    // 종류를 바꾸면 프로그램 목록이 따라와야 한다 — 안 따라오면 옛 종류의
    // 프로그램이 선택지로 남고, 그것을 고른 저장을 서버가 거절한다.
    // 위임으로 듣는다: 폼은 render() 가 매번 다시 그려서 요소가 바뀐다.
    box.addEventListener('change', function (e) {
      var sel = e.target;
      if (!sel || sel.getAttribute('data-f') !== 'kind') return;
      var form = sel.closest('.fac-plot-form');
      if (!form) return;
      loadPrograms(sel.value).then(function () {
        // 폼 전체를 다시 그리지 않는다 — 사람이 이미 적어 넣은 값이 날아간다.
        // 프로그램 줄만 갈아 끼우고, 종류가 바뀌었으니 선택은 비운다.
        var row = form.querySelector('[data-f="program_uuid"]');
        var list = State.programs[sel.value] || [];
        if (!row) { render(); return; }
        var opts = '<option value="">' +
                   _T('plot_program_none', 'No program') + '</option>';
        list.forEach(function (p) {
          opts += '<option value="' + _esc(p.unique_id) + '">' +
                  _esc(p.name) + (p.variety ? ' · ' + _esc(p.variety) : '') +
                  '</option>';
        });
        if (row.innerHTML !== opts) row.innerHTML = opts;
      });
    });

    box.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-act]');
      if (!btn) return;
      var act = btn.dataset.act;
      var form = btn.closest('.fac-plot-form');
      if (act === 'save' && form) { _save(form); return; }
      if (act === 'cancel') {
        State.editing = null; State.formBay = null; render(); return;
      }
      var container = btn.closest('[data-bay]');
      if (act === 'add' && container) {
        State.editing = null;
        State.formBay = container.dataset.bay;
        render();
        return;
      }
      var row = btn.closest('.fac-plot-row');
      if (!row) return;
      var uuid = row.dataset.uuid;
      if (act === 'edit') {
        var rec = State.rows.filter(function (x) { return x.unique_id === uuid; })[0];
        State.editing = uuid;
        State.formBay = (rec && rec.bay_id) || (container && container.dataset.bay) || null;
        render();
      } else if (act === 'end') {
        _end(uuid);
      } else if (act === 'delete') {
        _delete(uuid);
      }
    });
  }

  function boot() { wire(); initFromCurrent(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // 편집기가 시설을 열 때(신규 포함) 실려 오는 dict 를 그대로 받는다.
  document.addEventListener('facility-loaded', function (e) {
    setFacility((e.detail && e.detail.facility) || {});
  });

  // 저장은 구역 구성을 바꿀 수 있다(bay 수·분할/병합). 그래서 폼 값이 아니라
  // **저장된 시설**을 다시 읽어 구역 목록을 맞춘다 — 구역이 사라졌는데 목록에
  // 남아 있으면 없는 구역에 작물을 적게 된다.
  document.addEventListener('facility-saved', function (e) {
    var uuid = e.detail && e.detail.facility_uuid;
    if (!uuid) return;
    fetch('/api/geo/facility/' + encodeURIComponent(uuid),
          { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.ok && j.facility) setFacility(j.facility);
      })
      .catch(function () { /* 조회 실패는 다음 로드에서 회복된다 */ });
  });

  /**
   * 새 구역 구성으로 저장하면 **갈 곳을 잃는** 활성 구획 목록.
   *
   * 저장 후에 서버도 같은 판정을 해서 응답에 싣지만(정본), 그때는 이미 바뀐
   * 뒤다. 사람이 결정할 기회를 주려면 저장 **전**에 물어야 한다.
   *
   * 구역이 지정되지 않은 구획(시설 전체)은 대상이 아니다 — 구역 구성이 어떻게
   * 바뀌든 시설 전체라는 자리는 사라지지 않는다.
   */
  function orphansFor(validBayIds) {
    var valid = validBayIds || [];
    if (!valid.length) return [];          // 판정 근거 없음 — 묻지 않는다
    return (State.rows || []).filter(function (r) {
      return r.bay_id && valid.indexOf(r.bay_id) === -1;
    }).map(function (r) {
      return { subject: r.subject, bay_id: r.bay_id, unique_id: r.unique_id };
    });
  }

  window.FacilityPlotUI = {
    setFacility: setFacility,
    reload: reload,
    orphansFor: orphansFor,
    // 시설을 새로 만들거나 지운 직후처럼 "아직 없음" 상태로 되돌린다.
    clear: function () { setFacility({}); }
  };
})();
