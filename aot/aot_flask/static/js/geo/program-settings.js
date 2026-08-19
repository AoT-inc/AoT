// program-settings.js — 설정 > 프로그램(관리 프로그램) 화면.
//
// **식생은 대상 중 하나일 뿐이다**(kind). 같은 구조가 가축·시설물·도로에도
// 쓰이므로 이 화면은 종류를 가진 프로그램 전체를 다룬다.
//
// 골격은 input 페이지와 같다(`aot-entry-*`): "고르고 추가" 줄 + 항목 목록 +
// 항목을 누르면 그 자리에서 펼쳐 고친다.
//
// ## 여기서 하지 않는 것
//
// - **검증을 다시 구현하지 않는다.** 단계 기간·순서 규칙은 서버
//   (`program_io._clean_stages`)가 정본이고, 화면은 그 오류 메시지를 그대로
//   보인다. 두 곳에서 검증하면 반드시 갈린다.
// - **내장·외부를 고치는 길을 만들지 않는다.** 편집 버튼 자체가 없다(서버도
//   거절한다). 고치려면 복제한다 — 그러지 않으면 업그레이드가 수정을 덮어쓴다.
(function () {
  'use strict';

  function _T(k, f) {
    var d = (typeof window !== 'undefined' && window._PROG) || {};
    return (d[k] != null && d[k] !== '') ? d[k] : f;
  }

  function _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                '"': '&quot;', "'": '&#39;' })[c];
    });
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
    }).then(function (r) {
      return r.json().catch(function () { return {}; })
        .then(function (d) { return { status: r.status, data: d }; });
    });
  }

  function _toast(msg, level) {
    if (window.showToast) window.showToast(msg, level || 'info');
  }

  var State = { programs: [], templates: [], methods: [], functions: [],
                openId: null };

  // ── 로드 ──────────────────────────────────────────────────────────────
  function load() {
    return Promise.all([
      fetch('/api/geo/programs', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).catch(function () { return null; }),
      // 템플릿은 **DB 에 깔려 있지 않다** — 필요할 때 골라 자기 것으로 만든다.
      fetch('/api/geo/program-templates', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).catch(function () { return null; }),
      // 목표 곡선으로 걸 Method 목록. 만드는 것은 설정 > 메서드가 맡는다.
      fetch('/api/geo/target-methods', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).catch(function () { return null; }),
      // 자원으로 걸 Function 목록. 만드는 것은 설정 > 함수가 맡는다.
      fetch('/api/geo/resource-functions', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).catch(function () { return null; })
    ]).then(function (res) {
      State.programs = (res[0] && res[0].ok) ? (res[0].programs || []) : [];
      State.templates = (res[1] && res[1].ok) ? (res[1].templates || []) : [];
      State.methods = (res[2] && res[2].ok) ? (res[2].methods || []) : [];
      State.functions = (res[3] && res[3].ok) ? (res[3].functions || []) : [];
      renderBase();
      renderList();
    });
  }

  /**
   * 추가 줄의 선택지 — 빈 것 / 템플릿 / 내 프로그램 복제.
   *
   * **빈 프로그램이 기본**이다. 대부분의 사용자는 자기 대상 하나를 만들 뿐이고,
   * 남의 작물 목록을 먼저 지나치게 하면 안 된다. 템플릿은 "예시로 시작하고
   * 싶을 때" 고른다.
   */
  function renderBase() {
    var sel = document.getElementById('veg-base');
    if (!sel) return;
    var html = '<option value="">' + _esc(_T('empty_base', 'Empty program')) +
               '</option>';
    if (State.templates.length) {
      html += '<optgroup label="' + _esc(_T('from_template', 'From a template')) + '">';
      State.templates.forEach(function (t) {
        html += '<option value="tpl:' + _esc(t.key) + '">' + _esc(t.name) +
                ' (' + _esc(_T('n_stages', '{n} stages')
                            .replace('{n}', String(t.stage_count || 0))) + ')</option>';
      });
      html += '</optgroup>';
    }
    if (State.programs.length) {
      html += '<optgroup label="' + _esc(_T('copy_mine', 'Copy one of mine')) + '">';
      State.programs.forEach(function (p) {
        html += '<option value="' + _esc(p.unique_id) + '">' +
                _esc(p.name + (p.variety ? ' · ' + p.variety : '')) + '</option>';
      });
      html += '</optgroup>';
    }
    sel.innerHTML = html;
  }

  // ── 목록 ──────────────────────────────────────────────────────────────
  function _sourceBadge(p) {
    // 출처가 신뢰를 정한다 — 그래서 목록에서 바로 보여야 한다.
    var label = { builtin: 'built-in', external: 'external', user: 'user',
                  ai: 'AI' }[p.source] || p.source;
    var cls = (p.source === 'ai' && !p.usable_for_control)
      ? 'badge-warning' : 'badge-secondary';
    return '<span class="badge ' + cls + ' aot-badge-inline">' +
           _esc(label) + '</span>';
  }

  var _KINDS = ['vegetation', 'livestock', 'facility', 'other'];

  function _kindLabel(k) {
    return _T('kind_' + (k || 'vegetation'), k || 'vegetation');
  }

  function _rowHtml(p) {
    var meta = [
      _esc(_kindLabel(p.kind)),
      _esc(p.subject) + (p.variety ? ' · ' + _esc(p.variety) : ''),
      _esc(_T('n_stages', '{n} stages').replace('{n}', String(p.stage_count || 0))),
      p.total_days
        ? _esc(_T('n_days', '{n} days').replace('{n}', String(p.total_days)))
        : ''
    ].filter(Boolean).join(' · ');

    var actions = '';
    if (p.editable) {
      actions += '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
                 'data-act="edit">' + _esc(_T('edit', 'Edit')) + '</button>';
    }
    actions += '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
               'data-act="copy">' + _esc(_T('copy', 'Copy')) + '</button>';
    if (p.editable) {
      actions += '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
                 'data-act="delete">' + _esc(_T('del', 'Delete')) + '</button>';
    }

    var warn = '';
    if (p.source === 'ai' && !p.usable_for_control) {
      warn = '<div class="aot-modal-body-text">' +
             _esc(_T('needs_review', 'Made by AI — check it before control.')) +
             ' <button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
             'data-act="review">' + _esc(_T('mark_reviewed', 'Mark as checked')) +
             '</button></div>';
    }

    return '<div class="aot-entry-item" data-uuid="' + _esc(p.unique_id) + '" ' +
             'data-config-uid="' + _esc(p.unique_id) + '">' +
             '<div class="aot-entry-content-item aot-col-name">' +
               '<div class="form-control aot-entry-name-input">' +
                 _sourceBadge(p) + ' ' + _esc(p.name) +
               '</div>' +
             '</div>' +
             '<div class="aot-entry-content-item aot-col-uuid">' +
               '<span class="aot-modal-body-text">' + meta + '</span>' +
             '</div>' +
             '<div class="aot-entry-actions aot-col-action">' + actions + '</div>' +
             warn +
           '</div>';
  }

  function renderList() {
    var box = document.getElementById('veg-list');
    if (!box) return;
    if (!State.programs.length) {
      box.innerHTML = '<div class="aot-modal-container">' +
                      '<div class="aot-modal-body-text">' +
                      _esc(_T('empty', 'No programs yet.')) + '</div></div>';
      return;
    }
    box.innerHTML = State.programs.map(_rowHtml).join('');
  }

  // ── 편집 ──────────────────────────────────────────────────────────────
  // 단계 목표 — 키는 서버(`_TARGET_FIELDS`)와 **같은 어휘**여야 한다. 화면이
  // 자기 이름을 쓰면 저장은 되는데 읽는 쪽이 못 알아본다.
  var _TARGETS = [
    ['temp_day',   'temp_day',   '°C'],
    ['temp_night', 'temp_night', '°C'],
    ['rh',         'rh',         '%'],
    ['co2',        'co2',        'ppm'],
    ['dli',        'dli',        'mol/m²/d'],
    ['vpd',        'vpd',        'kPa']
  ];

  function _targetInputs(t) {
    t = t || {};
    return _TARGETS.map(function (f) {
      var val = (t[f[0]] == null) ? '' : t[f[0]];
      return '<label class="veg-target-field">' +
               '<span class="aot-modal-body-text">' +
                 _esc(_T('t_' + f[1], f[1])) + ' <em>' + _esc(f[2]) + '</em></span>' +
               '<input type="number" step="any" class="form-control aot-modern-input" ' +
                 'data-tf="' + f[0] + '" value="' + _esc(String(val)) + '">' +
             '</label>';
    }).join('');
  }

  // 자원(관수·시비) — 이 단계에 쓰는 Function. **선언일 뿐이고 프로그램이 켜지
  // 않는다**(물이 나오는 일이라 사람이 구획 모달에서 [적용]을 누른다).
  //
  // 함수 목록은 드로어를 열 때 한 번 받는다(State.functions).
  var _RES_ROLES = ['irrigation', 'fertigation', 'other'];

  function _resourceRows(items) {
    var list = State.functions || [];
    if (!list.length) return '';
    var cur = {};
    (items || []).forEach(function (it) {
      if (typeof it === 'string') cur[it] = 'other';
      else if (it && it.id) cur[it.id] = it.role || 'other';
    });
    var rows = _RES_ROLES.map(function (role) {
      var opts = '<option value="">' + _esc(_T('res_none', 'None')) + '</option>';
      list.forEach(function (f) {
        var sel = (cur[f.unique_id] === role) ? ' selected' : '';
        opts += '<option value="' + _esc(f.unique_id) + '"' + sel + '>' +
                _esc(f.name || f.unique_id) + '</option>';
      });
      return '<div class="aot-modal-option-row">' +
             '<div class="aot-modal-option-label">' +
               _esc(_T('res_' + role, role)) + '</div>' +
             '<div class="aot-modal-option-control">' +
               '<select class="form-control aot-modern-input" ' +
                 'data-rf="' + role + '">' + opts + '</select></div></div>';
    }).join('');
    return '<div class="aot-modal-option-row"><div class="aot-modal-option-label">' +
           _esc(_T('resources', 'Resources')) + '</div><div></div></div>' + rows +
           '<div class="aot-modal-body-text">' +
             _esc(_T('resources_note',
                     'Declared only. Functions are not switched on or off automatically.')) +
           '</div>';
  }

  function _stageRow(st) {
    st = st || { key: '', name: '', days: '' };
    var hasT = st.targets && Object.keys(st.targets).length;
    return '<div class="veg-stage-block">' +
           '<div class="aot-modal-option-row veg-stage-row">' +
             '<div class="aot-modal-option-control">' +
               '<input type="text" class="form-control aot-modern-input" ' +
                 'data-sf="name" placeholder="' + _esc(_T('stage_name', 'Stage name')) +
                 '" value="' + _esc(st.name || '') + '">' +
             '</div>' +
             '<div class="aot-modal-option-control">' +
               '<input type="text" class="form-control aot-modern-input" ' +
                 'data-sf="key" placeholder="' + _esc(_T('stage_key', 'Key')) +
                 '" value="' + _esc(st.key || '') + '">' +
             '</div>' +
             '<div class="aot-modal-option-control">' +
               '<input type="number" min="1" class="form-control aot-modern-input" ' +
                 'data-sf="days" placeholder="' + _esc(_T('until_end', 'until the end')) +
                 '" value="' + (st.days == null ? '' : st.days) + '">' +
             '</div>' +
             // 적산온도(GDD). 비우면 날짜로 넘어간다 — 한 단계라도 비면 서버가
             // GDD 판정을 통째로 포기하므로(두 기준을 한 프로그램에 섞지 않는다)
             // 전부 채우거나 전부 비우는 것이 맞다.
             '<div class="aot-modal-option-control">' +
               '<input type="number" min="1" step="any" class="form-control aot-modern-input" ' +
                 'data-sf="gdd" placeholder="' + _esc(_T('by_days', 'by days')) +
                 '" value="' + (st.gdd == null ? '' : st.gdd) + '">' +
             '</div>' +
             '<div class="aot-modal-option-control">' +
               '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
                 'data-act="stage-targets">' + _esc(_T('targets', 'Targets')) +
                 (hasT ? ' ●' : '') + '</button> ' +
               '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
                 'data-act="stage-del">×</button>' +
             '</div>' +
           '</div>' +
           // 목표는 기본으로 접어 둔다 — 7단계면 여섯 칸씩 42개가 한 화면에
           // 펼쳐져 정작 단계 구조가 안 보인다. 값이 있는 단계는 ● 로 표시한다.
           '<div class="veg-stage-targets"' + (hasT ? '' : ' style="display:none"') + '>' +
             _targetInputs(st.targets) +
             '<div class="aot-modal-body-text">' +
               _esc(_T('targets_note',
                       'Used for display and advice. Control is not changed automatically.')) +
             '</div>' +
             _resourceRows(st.functions) +
           '</div>' +
           '</div>';
  }

  /**
   * 설정 드로어를 연다.
   *
   * **서버에서 다시 읽어 채운다.** 목록의 요약본으로 채우면 단계·목표가 없고,
   * 무엇보다 다른 창에서 바뀐 값을 못 본 채 저장해 덮어쓸 수 있다.
   *
   * 드로어의 값은 저장을 눌러야 반영된다 — 잘못 고치고 닫으면 원래 값이 남는다.
   */
  function openEditor(uuid) {
    var modal = document.getElementById('veg-drawer');
    var host = document.getElementById('veg-drawer-body');
    if (!modal || !host) return;
    State.openId = uuid;
    modal.setAttribute('data-config-uid-target', uuid);
    host.innerHTML = '<div class="aot-modal-body-text">…</div>';
    if (window.jQuery) window.jQuery(modal).modal('show');

    fetch('/api/geo/program/' + encodeURIComponent(uuid),
          { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res || !res.ok) {
          host.innerHTML = '<div class="aot-modal-body-text">' +
                           _esc(_T('save_failed', 'Load failed')) + '</div>';
          return;
        }
        var p = res.program;
        var ro = !p.editable;
        // 읽기 전용이면 저장 버튼을 숨긴다 — 눌러도 서버가 거절하는 버튼을
        // 보여 주는 것은 사용자에게 거짓말이다.
        var saveBtn = document.getElementById('veg-drawer-save');
        if (saveBtn) saveBtn.style.display = ro ? 'none' : '';
        var title = document.getElementById('vegDrawerLabel');
        if (title) title.textContent = p.name || '';
        var _row = function (label, field, value) {
          return '<div class="aot-modal-option-row">' +
            '<div class="aot-modal-option-label">' + _esc(label) + '</div>' +
            '<div class="aot-modal-option-control"><input type="text" ' +
              'class="form-control aot-modern-input" data-pf="' + field + '" value="' +
              _esc(value || '') + '"' + (ro ? ' disabled' : '') + '></div></div>';
        };
        // 대상은 **목록에서 고른다.** 자유 텍스트로 두면 다른 대상으로 바꿀 때
        // 매번 철자를 맞춰 적어야 하고, 한 글자만 달라도 같은 대상으로 묶이지
        // 않는다. 목록에 없는 것은 "직접 입력" 으로 넣는다.
        //
        // 잘못 골라도 **저장을 누르기 전까지는 원래 값이 남는다**(드로어 방식).
        // 기준온도(GDD base). 비우면 단계는 날짜로 넘어간다 — **지어내지
        // 않는다**(작물마다 다르고, 틀리면 적산이 통째로 어긋나는데 에러가 나지
        // 않는다). `photosynthesis.T_base` 로 저장한다: 그 JSON 이 이미
        // "FunctionCropPreset 과 같은 키" 라는 계약을 갖고 있고 거기에 T_base 가
        // 있다 — 새 키를 만들면 같은 값이 두 이름을 갖는다.
        var tBase = (p.photosynthesis || {}).T_base;
        var tBaseRow = '<div class="aot-modal-option-row">' +
          '<div class="aot-modal-option-label">' +
            _esc(_T('t_base', 'Base temperature')) + '</div>' +
          '<div class="aot-modal-option-control"><input type="number" step="any" ' +
            'class="form-control aot-modern-input" data-tbase="1" placeholder="' +
            _esc(_T('by_days', 'by days')) + '" value="' +
            (tBase == null ? '' : _esc(String(tBase))) + '"' +
            (ro ? ' disabled' : '') + '></div></div>';

        // 자동 승인(P7). **기본은 꺼짐** — 켜져 있는 것이 기본이면 사람이 아무
        // 결정도 하지 않았는데 단계가 스스로 넘어간다.
        var autoRow = '<div class="aot-modal-option-row">' +
          '<div class="aot-modal-option-label">' +
            _esc(_T('auto_advance', 'Advance stages automatically')) + '</div>' +
          '<div class="aot-modal-option-control">' +
            '<input type="checkbox" data-auto="1"' +
            (p.auto_advance ? ' checked' : '') + (ro ? ' disabled' : '') +
            '></div></div>';

        var head = _row(_T('name', 'Name'), 'name', p.name) +
                   _kindRow(p, ro) +
                   _subjectRow(p, ro) +
                   _row(_T('variety', 'Variety'), 'variety', p.variety) +
                   tBaseRow +
                   autoRow +
                   '<div class="aot-modal-body-text">' +
                     _esc(_T('auto_advance_note',
                       'Stages are recorded without asking. The date comes ' +
                       'from the data, not from when you happen to look.')) +
                   '</div>' +
                   '<div class="aot-modal-body-text">' +
                     _esc(_T('gdd_note',
                       'With a base temperature and a GDD per stage, stages ' +
                       'advance on accumulated heat instead of the calendar.')) +
                   '</div>';

        var stages = (p.stages || []).map(_stageRow).join('');
        var curves = _curveSection(p, ro);
        // 저장·닫기는 **드로어 푸터**가 맡는다(input 페이지와 같은 자리).
        // 본문에 또 두면 같은 일을 하는 버튼이 두 벌이 된다.
        var actions = ro
          ? '<div class="aot-modal-body-text">' +
            _esc(_T('read_only', 'Built-in programs are read-only. Copy it.')) +
            '</div>'
          : '<div class="aot-ov-desc-actions">' +
            '<button type="button" class="btn aot-pill-btn" data-act="stage-add">' +
            _esc(_T('add_stage', 'Add stage')) + '</button></div>';

        // 열 머리 — 값이 차 있으면 placeholder 가 안 보여 어느 칸이 무엇인지
        // 알 수 없다. 기간 칸은 비우면 "끝까지" 라는 것을 여기서 밝힌다.
        var thead = '<div class="aot-modal-option-row veg-stage-head">' +
          '<div class="aot-modal-option-control aot-modal-body-text">' +
            _esc(_T('stage_name', 'Stage name')) + '</div>' +
          '<div class="aot-modal-option-control aot-modal-body-text">' +
            _esc(_T('stage_key', 'Key')) + '</div>' +
          '<div class="aot-modal-option-control aot-modal-body-text">' +
            _esc(_T('stage_days', 'Days')) + ' · ' +
            _esc(_T('until_end', 'blank = until the end')) + '</div>' +
          '<div class="aot-modal-option-control aot-modal-body-text">' +
            _esc(_T('stage_gdd', 'GDD')) + '</div>' +
          '<div class="aot-modal-option-control"></div></div>';

        host.innerHTML = '<div class="aot-modal-container">' + head + curves +
                         (ro ? '' : thead) +
                         '<div class="veg-stages">' + stages + '</div>' +
                         actions + '</div>';
      });
  }

  /**
   * 대상 종류(kind) 줄.
   *
   * 식생만 다루던 화면이 아니다 — 가축·시설물·도로도 같은 구조로 관리한다.
   * 소비처는 자기 종류만 고른다(식생 구획은 `plot` 만 본다).
   */
  function _kindRow(p, ro) {
    var cur = p.kind || 'vegetation';
    var sel = '<select class="form-control aot-modern-input" data-pf="kind"' +
              (ro ? ' disabled' : '') + '>';
    _KINDS.forEach(function (k) {
      sel += '<option value="' + k + '"' + (k === cur ? ' selected' : '') + '>' +
             _esc(_kindLabel(k)) + '</option>';
    });
    sel += '</select>';
    return '<div class="aot-modal-option-row">' +
           '<div class="aot-modal-option-label">' + _esc(_T('kind', 'Kind')) +
           '</div><div class="aot-modal-option-control">' + sel + '</div></div>';
  }

  /**
   * 대상(subject) 줄 — 목록 + 직접 입력.
   *
   * 선택지는 **이미 쓰이고 있는 대상**(내 프로그램들)과 템플릿의 대상을 합친 것이다.
   * 새 대상을 쓰는 사람도 있으므로 "직접 입력" 을 항상 남긴다 — AoT 는 농장 전용이
   * 아니라 어떤 대상이 올지 코드가 다 알 수 없다.
   */
  function _subjectRow(p, ro) {
    var seen = {}, opts = [];
    State.programs.forEach(function (x) { if (x.subject) seen[x.subject] = 1; });
    State.templates.forEach(function (t) { if (t.subject) seen[t.subject] = 1; });
    if (p.subject) seen[p.subject] = 1;
    Object.keys(seen).sort().forEach(function (k) { opts.push(k); });

    var sel = '<select class="form-control aot-modern-input" data-pf="subject"' +
              (ro ? ' disabled' : '') + '>';
    opts.forEach(function (k) {
      sel += '<option value="' + _esc(k) + '"' +
             (k === p.subject ? ' selected' : '') + '>' + _esc(k) + '</option>';
    });
    sel += '<option value="__custom__">' +
           _esc(_T('subject_custom', 'Enter a new one…')) + '</option></select>' +
           '<input type="text" class="form-control aot-modern-input veg-subject-custom" ' +
             'data-pf="subject_custom" style="display:none" placeholder="' +
             _esc(_T('subject', 'Applies to')) + '"' + (ro ? ' disabled' : '') + '>';

    return '<div class="aot-modal-option-row">' +
           '<div class="aot-modal-option-label">' + _esc(_T('subject', 'Applies to')) +
           '</div><div class="aot-modal-option-control">' + sel + '</div></div>';
  }

  /** 편집기를 화면 안으로 들이고 이름 칸에 커서를 둔다. */
  function focusName(uuid) {
    var host = document.getElementById('veg-drawer-body');
    if (!host) return;
    // openEditor 가 비동기로 채우므로 조금 기다렸다 잡는다.
    setTimeout(function () {
      var input = host.querySelector('[data-pf="name"]');
      if (!input) return;
      try { input.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
      input.focus();
      input.select();
    }, 250);
  }

  /**
   * 목표 곡선 — 항목마다 Method 를 걸 수 있다.
   *
   * 단계별 목표는 **계단**이다(그 단계 내내 같은 값). 실제 재배는 주차마다 조금씩
   * 옮겨 가는 쪽이 많고, AoT 에는 그것을 표현하는 수단이 이미 있다(Method).
   * **곡선이 있으면 곡선이 이긴다** — 단계 값은 곡선이 없는 항목에만 쓰인다.
   *
   * Method 가 하나도 없으면 섹션을 내지 않는다. 고를 것이 없는 칸은 화면만
   * 길게 만들고, 만드는 곳은 여기가 아니다(설정 > 메서드).
   */
  function _curveSection(p, ro) {
    if (!State.methods.length) return '';
    var cur = p.target_methods || {};
    var rows = _TARGETS.map(function (f) {
      var opts = '<option value="">' + _esc(_T('curve_none', 'Fixed value')) +
                 '</option>';
      State.methods.forEach(function (m) {
        opts += '<option value="' + _esc(m.unique_id) + '"' +
                (cur[f[0]] === m.unique_id ? ' selected' : '') + '>' +
                _esc(m.name) + '</option>';
      });
      return '<label class="veg-target-field">' +
               '<span class="aot-modal-body-text">' +
                 _esc(_T('t_' + f[1], f[1])) + '</span>' +
               '<select class="form-control aot-modern-input" data-cf="' + f[0] + '"' +
                 (ro ? ' disabled' : '') + '>' + opts + '</select>' +
             '</label>';
    }).join('');
    return '<div class="aot-modal-option-row aot-full-width-row">' +
             '<div class="aot-modal-option-label">' +
               _esc(_T('curves', 'Target curves')) +
               '<div class="aot-modal-body-text">' +
                 _esc(_T('curves_note',
                         'A curve overrides the stage value for that item. ' +
                         'Time runs from the start date.')) +
               '</div>' +
             '</div>' +
             '<div class="veg-stage-targets">' + rows + '</div>' +
           '</div>';
  }

  function collect(host) {
    var out = { stages: [] };
    host.querySelectorAll('[data-pf]').forEach(function (el) {
      out[el.getAttribute('data-pf')] = (el.value || '').trim() || null;
    });
    // "직접 입력" 을 골랐으면 그 칸의 값이 대상이다. 비어 있으면 **아무것도
    // 보내지 않는다** — 부분 저장 규칙상 키가 없으면 서버가 기존 값을 지킨다.
    if (out.subject === '__custom__') {
      if (out.subject_custom) out.subject = out.subject_custom;
      else delete out.subject;
    }
    delete out.subject_custom;

    // 기준온도는 photosynthesis JSON 안에 넣는다. **비우면 키를 지운다** —
    // 남겨 두면 "예전에 넣었던 값" 이 계속 GDD 판정에 쓰인다.
    var au = host.querySelector('[data-auto]');
    if (au) out.auto_advance = !!au.checked;

    var tb = host.querySelector('[data-tbase]');
    if (tb) {
      var photo = {};
      var raw = (tb.value || '').trim();
      if (raw !== '') photo.T_base = raw;
      out.photosynthesis = Object.keys(photo).length ? photo : null;
    }

    var curves = {};
    host.querySelectorAll('[data-cf]').forEach(function (el) {
      if (el.value) curves[el.getAttribute('data-cf')] = el.value;
    });
    // 곡선 칸이 화면에 있을 때만 보낸다 — 없는 화면에서 보내면 부분 저장이
    // 멀쩡한 설정을 지운다.
    if (host.querySelector('[data-cf]')) out.targets_methods = curves;

    host.querySelectorAll('.veg-stage-block').forEach(function (block) {
      var st = {};
      block.querySelectorAll('[data-sf]').forEach(function (el) {
        st[el.getAttribute('data-sf')] = (el.value || '').trim();
      });
      // 기간을 비우면 "끝까지" 다 — 서버가 마지막 자리에서만 허용한다.
      st.days = st.days === '' ? null : st.days;
      // 적산온도는 비우면 **키를 보내지 않는다.** null 로 보내면 "0" 과
      // "미지정" 이 구분되지 않는다(목표값과 같은 규율).
      if (st.gdd === '') delete st.gdd;
      var t = {};
      block.querySelectorAll('[data-tf]').forEach(function (el) {
        var v = (el.value || '').trim();
        // 빈 칸은 **보내지 않는다** — 0 과 미지정을 구분해야 한다.
        if (v !== '') t[el.getAttribute('data-tf')] = v;
      });
      if (Object.keys(t).length) st.targets = t;
      var fns = [];
      block.querySelectorAll('[data-rf]').forEach(function (el) {
        if (el.value) fns.push({ id: el.value, role: el.getAttribute('data-rf') });
      });
      // 빈 목록은 **키를 보내지 않는다** — 부분 저장 규칙상 키가 없으면 서버가
      // 기존 값을 지킨다(목표·적산온도와 같은 규율).
      if (fns.length) st.functions = fns;
      if (st.key || st.name) out.stages.push(st);
    });
    return out;
  }

  // ── 배선 ──────────────────────────────────────────────────────────────
  function wire() {
    var addBtn = document.getElementById('veg-add');
    if (addBtn) addBtn.addEventListener('click', function () {
      var base = (document.getElementById('veg-base') || {}).value || '';
      var done = function (r) {
        if (r.status >= 400 || !r.data.ok) {
          _toast((r.data && r.data.message) || _T('save_failed', 'Save failed'), 'error');
          return;
        }
        // **추가하면 바로 고칠 수 있어야 한다.** 목록에 한 줄이 늘어난 것만으로는
        // 사용자가 "이제 뭘 해야 하나" 를 알 수 없다 — 편집기를 열고 이름 칸으로
        // 데려간다(추가한 직후 가장 먼저 바꾸는 것이 이름이다).
        var newId = r.data.program.unique_id;
        load().then(function () { openEditor(newId); focusName(newId); });
      };
      if (base.indexOf('tpl:') === 0) {
        _api('POST', '/api/geo/program',
             { template_key: base.slice(4) }).then(done);
      } else if (base) {
        _api('POST', '/api/geo/program/' + encodeURIComponent(base) + '/clone', {})
          .then(done);
      } else {
        // 빈 프로그램도 단계 하나는 있어야 저장된다(서버 규칙) — 그 하나를
        // 채워서 만든다. 빈 목록을 주고 오류를 보이는 것보다 낫다.
        _api('POST', '/api/geo/program', {
          name: _T('new_program', 'New program'),
          subject: _T('new_subject', 'unnamed'),
          stages: [{ key: 'stage_1', name: _T('stage_name', 'Stage'), days: null }]
        }).then(done);
      }
    });

    var saveBtn = document.getElementById('veg-drawer-save');
    if (saveBtn) saveBtn.addEventListener('click', function () {
      var host = document.getElementById('veg-drawer-body');
      var uuid = State.openId;
      if (!host || !uuid) return;
      _api('POST', '/api/geo/program/' + encodeURIComponent(uuid),
           collect(host)).then(function (r) {
        if (r.status >= 400 || !r.data.ok) {
          _toast((r.data && r.data.message) || _T('save_failed', 'Save failed'), 'error');
          return;
        }
        _toast(_T('saved', 'Saved.'), 'success');
        if (window.jQuery) {
          window.jQuery(document.getElementById('veg-drawer')).modal('hide');
        }
        State.openId = null;
        load();
      });
    });

    var list = document.getElementById('veg-list');
    if (!list) return;
    list.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-act]');
      if (!btn) return;
      var act = btn.dataset.act;
      var item = btn.closest('[data-uuid]');
      var host = btn.closest('[data-detail]');
      var uuid = (item && item.dataset.uuid) || (host && host.dataset.detail);
      if (!uuid) return;

      if (act === 'edit') {
        openEditor(uuid);
      } else if (act === 'copy') {
        _api('POST', '/api/geo/program/' + encodeURIComponent(uuid) + '/clone', {})
          .then(function (r) {
            if (r.status >= 400 || !r.data.ok) {
              _toast((r.data && r.data.message) || _T('save_failed', 'Save failed'), 'error');
              return;
            }
            State.openId = r.data.program.unique_id;
            load();
          });
      } else if (act === 'delete') {
        if (!window.confirm(_T('del_confirm', 'Delete this program?'))) return;
        _api('DELETE', '/api/geo/program/' + encodeURIComponent(uuid))
          .then(function (r) {
            if (r.status >= 400 || !r.data.ok) {
              _toast((r.data && r.data.message) || _T('delete_failed', 'Delete failed'), 'error');
              return;
            }
            if (State.openId === uuid) State.openId = null;
            load();
          });
      } else if (act === 'review') {
        _api('POST', '/api/geo/program/' + encodeURIComponent(uuid),
             { reviewed: true }).then(function () { load(); });
      }
    });

    var drawerBody = document.getElementById('veg-drawer-body');
    if (drawerBody) drawerBody.addEventListener('change', function (e) {
      var el = e.target;
      if (!el || el.getAttribute('data-pf') !== 'subject') return;
      var custom = drawerBody.querySelector('.veg-subject-custom');
      if (custom) custom.style.display = (el.value === '__custom__') ? '' : 'none';
      if (el.value === '__custom__' && custom) custom.focus();
    });

    // 드로어 안의 단계 조작 — 목록과 다른 DOM 이라 따로 위임한다.
    var drawer = document.getElementById('veg-drawer-body');
    if (drawer) drawer.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-act]');
      if (!btn) return;
      var act = btn.dataset.act;
      if (act === 'stage-add') {
        drawer.querySelector('.veg-stages')
              .insertAdjacentHTML('beforeend', _stageRow(null));
      } else if (act === 'stage-targets') {
        var blk = btn.closest('.veg-stage-block');
        var box = blk && blk.querySelector('.veg-stage-targets');
        if (box) box.style.display = (box.style.display === 'none') ? '' : 'none';
      } else if (act === 'stage-del') {
        var row = btn.closest('.veg-stage-block');
        if (row) row.remove();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { wire(); load(); });
  } else {
    wire(); load();
  }
})();
