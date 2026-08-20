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

  // Big-Leaf 모델 상수 — 이름은 서버·제어와 같다(`CropParams`).
  var _PHOTO_FIELDS = [
    { key: 'A_max',    tkey: 'p_amax',  label: 'Max photosynthesis', unit: 'µmol/m²/s' },
    { key: 'K_L',      tkey: 'p_kl',    label: 'Light half-saturation', unit: 'µmol/m²/s' },
    { key: 'K_C',      tkey: 'p_kc',    label: 'CO2 half-saturation', unit: 'ppm' },
    { key: 'T_opt',    tkey: 'p_topt',  label: 'Optimum temperature', unit: '°C' },
    { key: 'T_sigma',  tkey: 'p_tsig',  label: 'Temperature width', unit: '°C' },
    { key: 'VPD_half', tkey: 'p_vpdh',  label: 'VPD half-saturation', unit: 'kPa' },
    { key: 'dli_target', tkey: 'p_dli', label: 'Suggested DLI', unit: 'mol/m²/d' },
    { key: 'gdd_daily',  tkey: 'p_gdd', label: 'Suggested GDD per day', unit: '°C·d/d' }
  ];

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

  var State = { programs: [], templates: [], methods: [], defs: [], measurements: [], fixedDefs: {}, functions: [],
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
      // 목표 항목이 고를 수 있는 측정 종류(센서가 쓰는 어휘 그대로).
      fetch('/api/geo/target-measurements', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).catch(function () { return null; }),
      // 자원으로 걸 Function 목록. 만드는 것은 설정 > 함수가 맡는다.
      fetch('/api/geo/resource-functions', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).catch(function () { return null; })
    ]).then(function (res) {
      State.programs = (res[0] && res[0].ok) ? (res[0].programs || []) : [];
      State.templates = (res[1] && res[1].ok) ? (res[1].templates || []) : [];
      State.methods = (res[2] && res[2].ok) ? (res[2].methods || []) : [];
      State.measurements = (res[3] && res[3].ok) ? (res[3].measurements || []) : [];
      State.fixedDefs = (res[3] && res[3].ok) ? (res[3].fixed_defs || {}) : {};
      State.functions = (res[4] && res[4].ok) ? (res[4].functions || []) : [];
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
    // selectpicker 는 원본 select 를 **복제해** 자기 목록을 그린다. innerHTML 을
    // 갈아끼운 뒤 알리지 않으면 화면에는 옛 목록(여기서는 "불러오는 중…")이
    // 그대로 남는다 — 값은 바뀌는데 보이는 것만 낡는 종류라 알아채기 어렵다.
    if (window.jQuery && window.jQuery.fn && window.jQuery.fn.selectpicker) {
      window.jQuery(sel).selectpicker('refresh');
    }
  }

  // ── 목록 ──────────────────────────────────────────────────────────────

  /** 대상·품종 라벨은 종류에 따라 달라진다(common/aot-plot-labels.js).
   *
   * 구획과 **같은 말**을 써야 한다 — 프로그램의 `subject` 와 구획의 `subject` 는
   * 문자열로 맞춰 붙이므로, 두 화면이 그 칸을 다른 이름으로 부르면 "이 대상이
   * 저 적용 대상인가" 를 사람이 매번 다시 확인하게 된다. */
  function _subjectLabel(p) {
    var k = (p && p.kind) || 'vegetation';
    return window.AoTPlotLabels ? window.AoTPlotLabels.subject(k)
                                : _T('subject', 'Applies to');
  }
  function _varietyLabel(p) {
    var k = (p && p.kind) || 'vegetation';
    return window.AoTPlotLabels ? window.AoTPlotLabels.variety(k)
                                : _T('variety', 'Variety');
  }

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

  var _KINDS = ['vegetation', 'livestock', 'facility', 'other'];

  /**
   * 지금 편집 중인 프로그램의 종류 — **화면을 종류에 맞추는 기준**.
   *
   * 광합성 모델 상수·기준온도(GDD)·관수/시비는 전부 **식물 개념**이다. 축사
   * 프로그램에 "광합성 지수" 가 떠 있으면 그것을 본 사람은 무엇을 적어야 할지
   * 알 수 없고, 알 수 없는 칸이 있으면 화면 전체를 못 믿는다.
   *
   * 드로어를 열 때 정해지고, 종류를 바꾸면 그 자리에서 다시 그린다.
   */
  var _kindNow = 'vegetation';
  function _isVeg() { return _kindNow === 'vegetation'; }

  function _kindLabel(k) {
    return _T('kind_' + (k || 'vegetation'), k || 'vegetation');
  }

  /**
   * 목록 카드 — **input 페이지 카드와 같은 골격**이다.
   *
   *   [≡ 핸들] [이름] [부가정보] [톱니]
   *
   * 그 배치는 이유가 있어 정해진 것이다: 좁은 화면에서 밀리는 것은 **버튼 수**
   * 이므로, 카드에는 자주 쓰는 것 하나(편집=톱니)만 두고 나머지(삭제·복제)는
   * 드로어 푸터로 내린다. 예전에는 [편집][복제][삭제] 셋이 카드에 있어 모바일
   * 에서 이름과 부가정보를 밀어냈다.
   *
   * 이름 앞에 출처 배지를 붙이지 않는다 — 한 열에는 한 정보만 둔다(배지가 이름
   * 앞에 오면 열 간격이 카드마다 달라진다). 출처는 부가정보 줄로 옮긴다.
   */
  function _rowHtml(p) {
    var meta = [
      _esc(_kindLabel(p.kind)),
      _esc(p.subject) + (p.variety ? ' · ' + _esc(p.variety) : ''),
      _esc(_T('n_stages', '{n} stages').replace('{n}', String(p.stage_count || 0))),
      p.total_days
        ? _esc(_T('n_days', '{n} days').replace('{n}', String(p.total_days)))
        : '',
      p.source && p.source !== 'user' ? _esc(_sourceLabel(p)) : ''
    ].filter(Boolean).join(' · ');

    var warn = '';
    if (p.source === 'ai' && !p.usable_for_control) {
      warn = '<div class="aot-modal-body-text">' +
             _esc(_T('needs_review', 'Made by AI — check it before control.')) +
             ' <button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
             'data-act="review">' + _esc(_T('mark_reviewed', 'Mark as checked')) +
             '</button></div>';
    }

    return '<div class="aot-entry-item row small-gutters" data-uuid="' +
             _esc(p.unique_id) + '" data-config-uid="' + _esc(p.unique_id) + '">' +
             '<div class="aot-entry-drag-handle"><i class="fa fa-grip-lines"></i></div>' +
             '<div class="aot-entry-content-item aot-col-name">' +
               '<div class="form-control aot-entry-name-input" title="' +
                 _esc(p.name) + '">' + _esc(p.name) + '</div>' +
             '</div>' +
             '<div class="aot-entry-content-item aot-col-uuid">' +
               '<span class="aot-modal-body-text" title="' + meta + '">' +
                 meta + '</span>' +
             '</div>' +
             // 편집은 톱니 하나 — input 카드와 같다. 읽기 전용 프로그램에도
             // 띄운다(드로어가 값을 보여 주고 저장 버튼만 숨긴다).
             '<div class="aot-entry-settings">' +
               '<a class="btn p-0" role="button" data-act="edit" ' +
                 'title="' + _esc(_T('edit', 'Edit')) + '">' +
                 '<i class="fas fa-cog"></i></a>' +
             '</div>' +
             warn +
           '</div>';
  }

  /** 출처 표시 — 이름 앞이 아니라 부가정보 줄에 둔다. */
  function _sourceLabel(p) {
    return _T('source_' + p.source, p.source);
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
  // 단계 목표 — **어휘를 화면이 갖지 않는다.** 항목 정의는 프로그램마다 다르고
  // (종류별 고정 항목 + 사용자가 만든 항목) 서버가 `target_defs` 로 준다. 여기에
  // 목록을 또 적어 두면 항목을 늘릴 때 한쪽만 늘어난다 — 이 저장소가 반복해서
  // 겪은 실패다.
  //
  // 숨긴 항목(`hidden`)은 입력칸을 내지 않는다. 실제 시설이 모든 항목을 재지
  // 못하는 것은 당연하고, 안 쓰는 칸이 계속 보이는 것은 "없는 것을 채우라" 는
  // 압박이 된다.
  function _visibleDefs() {
    return (State.defs || []).filter(function (d) { return !d.hidden; });
  }

  /**
   * 단계의 목표 칸 — **이 단계에서 따로 정한 항목만** 낸다.
   *
   * 예전에는 항목 전부를 단계마다 그렸다. 4단계 × 6항목이면 빈 칸 24개가 나오고,
   * 그중 대부분은 쓰지 않거나 같은 값을 옮겨 적는 자리였다 — 실제로 만들어 보면
   * 여기서 그만두게 된다.
   *
   * 값은 **프로그램 항목에 한 번** 적고(기본값), 달라지는 단계에서만 덮어쓴다.
   * 그래서 이 자리의 기본 상태는 **비어 있음**이고, 덮어쓸 항목은 아래 고르기로
   * 하나씩 꺼낸다.
   */
  function _targetInputs(t) {
    t = t || {};
    var defs = _visibleDefs();
    if (!defs.length) return '';

    var rows = defs.filter(function (d) { return t[d.key] != null; })
      .map(function (d) {
        var unit = d.unit ? (' <em>' + _esc(d.unit) + '</em>') : '';
        return '<label class="veg-target-field">' +
                 '<span class="aot-modal-body-text">' +
                   _esc(d.label || d.key) + unit + '</span>' +
                 '<input type="number" step="any" class="form-control aot-modern-input" ' +
                   'data-tf="' + _esc(d.key) + '" value="' + _esc(String(t[d.key])) + '">' +
               '</label>';
      }).join('');

    // 아직 덮어쓰지 않은 항목만 고르기에 남긴다.
    var rest = defs.filter(function (d) { return t[d.key] == null; });
    var picker = '';
    if (rest.length) {
      var opts = '<option value="">' +
                 _esc(_T('override_pick', 'Set a different value here…')) +
                 '</option>';
      rest.forEach(function (d) {
        var base = (d['default'] == null) ? '' :
                   ' (' + _T('default_is', 'default {v}')
                            .replace('{v}', String(d['default'])) + ')';
        opts += '<option value="' + _esc(d.key) + '">' +
                _esc((d.label || d.key) + base) + '</option>';
      });
      picker = '<select class="form-control aot-modern-input" data-tf-add>' +
               opts + '</select>';
    }
    return rows + picker;
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
    // 관수·시비는 **식물 개념**이다. 축사·시설에 그 칸을 내면 무엇을 걸어야
    // 할지 알 수 없다. 가축용 역할 어휘(급이·급수 등)를 지어내지는 않는다 —
    // 근거 없는 어휘는 한 번 퍼지면 되돌리기 어렵다. 그때는 역할 없는 자원
    // 하나만 남긴다(`other`).
    var roles = _isVeg() ? _RES_ROLES : ['other'];
    var rows = roles.map(function (role) {
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

  /**
   * 단계 한 항목 — **접힌 요약 + 펼친 상세**.
   *
   * 표(한 줄에 다섯 칸)를 버린 이유는 폭이다. 드로어는 520px 로 **고정**돼 있고
   * (`--aot-wdrawer-w`, 페이지를 정확히 그만큼 밀어내므로 뷰포트를 따라 커지면
   * 안 된다) 5열은 860px 를 요구했다 — 실제로 [목표]·[×] 버튼이 화면 밖
   * 253px 에 놓여 **누를 수 없었다.**
   *
   * 그래서 화면 폭으로 분기하지 않는다. 모바일(309px)과 드로어(454px)는 둘 다
   * 좁은 단일 컬럼이고, 좁은 쪽 하나에 맞추면 양쪽이 함께 맞는다. 분기를 늘리면
   * 지금처럼 한쪽만 고쳐진다.
   *
   * 접힌 줄이 **요약을 겸한다** — 단계 구조(순서·기간·설정 유무)를 한눈에 보는
   * 목적은 그대로 유지된다. 한 번에 한 단계만 펼치므로 7단계 × 여러 칸이 동시에
   * 쏟아지지 않는다.
   */
  function _stageRow(st, open) {
    st = st || { key: '', name: '', days: '' };
    var hasT = !!(st.targets && Object.keys(st.targets).length);
    var hasF = !!(st.functions && st.functions.length);
    return '<div class="veg-stage-block' + (open ? ' is-open' : '') + '">' +
           _stageSummary(st, hasT, hasF) +
           '<div class="veg-stage-detail"' + (open ? '' : ' hidden') + '>' +
             _stageField(_T('stage_name', 'Stage name'), 'name', 'text',
                         st.name, '') +
             _stageField(_T('stage_key', 'Key'), 'key', 'text', st.key, '') +
             '<div class="veg-stage-nums">' +
               _stageField(_T('stage_days', 'Days'), 'days', 'number',
                           st.days, _T('until_end', 'until the end')) +
               // 적산온도는 기준온도(광합성 파라미터)와 짝이라 식생에서만 뜻이
               // 있다. 축사 단계에 GDD 칸이 있으면 무엇을 적어야 할지 알 수 없다.
               (_isVeg()
                 ? _stageField(_T('stage_gdd', 'GDD'), 'gdd', 'number',
                               st.gdd, _T('by_days', 'by days'))
                 : '') +
             '</div>' +
             '<div class="veg-stage-sub">' + _esc(_T('targets', 'Targets')) + '</div>' +
             '<div class="veg-stage-targets">' + _targetInputs(st.targets) + '</div>' +
             '<div class="aot-modal-body-text">' +
               _esc(_T('targets_note',
                       'Used for display and advice. Control is not changed automatically.')) +
             '</div>' +
             // 단계 지침 — 이 시기에 무엇을 어떻게 하는가. AI 가 그대로 인용하고,
             // AI 를 안 쓰는 사용자도 구획 모달에서 읽는다.
             '<div class="veg-stage-sub">' +
               _esc(_T('guidance', 'Guidance')) + '</div>' +
             '<textarea class="form-control aot-modern-input veg-guidance" ' +
               'rows="4" data-guidance placeholder="' +
               _esc(_T('guidance_ph',
                       'What matters in this stage — watering, ventilation, ' +
                       'things to watch for.')) + '">' +
               _esc(st.guidance || '') + '</textarea>' +
             _resourceRows(st.functions) +
             // 삭제는 **펼친 안**에 둔다. 접힌 줄의 × 는 좁은 폭에서 오터치를
             // 부르고, 되돌릴 수단이 없다.
             '<div class="aot-ov-desc-actions">' +
               '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
                 'data-act="stage-del">' +
                 _esc(_T('stage_delete', 'Delete this stage')) + '</button>' +
             '</div>' +
           '</div></div>';
  }

  /** 접힌 줄 — 이름과 요약. 이 줄 전체가 펼치기 버튼이다. */
  function _stageSummary(st, hasT, hasF) {
    var bits = [];
    if (st.days != null && st.days !== '') {
      bits.push(_T('n_days', '{n} days').replace('{n}', String(st.days)));
    } else {
      bits.push(_T('until_end', 'until the end'));
    }
    if (st.gdd != null && st.gdd !== '') bits.push(st.gdd + ' GDD');
    if (hasT) bits.push(_T('targets', 'Targets'));
    if (hasF) bits.push(_T('resources', 'Resources'));
    return '<button type="button" class="veg-stage-summary" data-act="stage-toggle">' +
           '<span class="veg-stage-caret" aria-hidden="true"></span>' +
           '<span class="veg-stage-title">' +
             _esc(st.name || st.key || _T('stage_name', 'Stage name')) + '</span>' +
           '<span class="veg-stage-meta">' + _esc(bits.join(' \u00b7 ')) + '</span>' +
           '</button>';
  }

  /** 라벨 위, 입력 아래. 520px 에서 label|value 2열은 값이 너무 좁다. */
  function _stageField(label, field, type, value, placeholder) {
    var attrs = (type === 'number') ? ' min="1" step="any"' : '';
    return '<label class="veg-stage-field">' +
           '<span>' + _esc(label) + '</span>' +
           '<input type="' + type + '"' + attrs +
             ' class="form-control aot-modern-input" data-sf="' + field + '"' +
             ' placeholder="' + _esc(placeholder || '') + '"' +
             ' value="' + _esc(value == null ? '' : String(value)) + '">' +
           '</label>';
  }

  /**
   * 설정 드로어를 연다.
   *
   * **서버에서 다시 읽어 채운다.** 목록의 요약본으로 채우면 단계·목표가 없고,
   * 무엇보다 다른 창에서 바뀐 값을 못 본 채 저장해 덮어쓸 수 있다.
   *
   * 드로어의 값은 저장을 눌러야 반영된다 — 잘못 고치고 닫으면 원래 값이 남는다.
   */
  /** 드로어를 닫는다 — 삭제·복제 뒤에는 열려 있을 대상이 사라지거나 바뀐다. */
  function _closeDrawer() {
    var modal = document.getElementById('veg-drawer');
    if (modal && window.jQuery) window.jQuery(modal).modal('hide');
  }

  /**
   * 설정 드로어를 연다.
   *
   * `pending` 은 **저장하지 않고 다시 그릴 때** 이어받을 편집 중인 값이다
   * (종류를 바꿨을 때). 서버에서 다시 읽되 화면 값은 사람이 방금 적은 것을
   * 쓴다 — 저장을 강요하지 않으면서 화면만 종류에 맞춘다.
   */
  var _pendingKind = null;

  function openEditor(uuid, pending) {
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
        // 다시 그리기라면 사람이 방금 적은 값이 이긴다(서버 값으로 되돌리면
        // 종류 하나 바꾸는 데 입력이 날아간다).
        if (pending) {
            if (_pendingKind) { p.kind = _pendingKind; _pendingKind = null; }
            ['name', 'subject', 'variety'].forEach(function (k) {
              if (pending[k] != null) p[k] = pending[k];
            });
            if (pending.stages && pending.stages.length) p.stages = pending.stages;
            if (pending.target_defs) p.target_defs = pending.target_defs;
        }

        // ⚠ **읽는 것보다 먼저 세운다.** 이 둘은 아래에서 단계·목표·머리 블록을
        // 그릴 때 전부 쓰인다(`_isVeg()`·`_targetInputs`). 뒤에 두면 이번 렌더가
        // **직전 프로그램의 값**으로 그려지고, 종류를 바꿔도 첫 번에는 광합성
        // 칸이 그대로 남았다가 한 번 더 바꿔야 사라진다.
        //
        // 화면을 종류에 맞추는 기준. 식물 개념(광합성·기준온도·관수/시비)은
        // 식생에서만 낸다.
        _kindNow = p.kind || 'vegetation';
        // 항목 정의는 **서버가 정본**이다(고정 항목이 빠져 있으면 서버가
        // 되돌려 놓는다). 화면은 받은 것을 그대로 들고 있다가 저장 때 돌려준다.
        State.defs = (p.target_defs || []).map(function (d) { return d; });

        var ro = !p.editable;
        // 읽기 전용이면 저장 버튼을 숨긴다 — 눌러도 서버가 거절하는 버튼을
        // 보여 주는 것은 사용자에게 거짓말이다.
        var saveBtn = document.getElementById('veg-drawer-save');
        if (saveBtn) saveBtn.style.display = ro ? 'none' : '';
        // 내장·외부는 지울 수도 없다. **복제는 남긴다** — 고치는 유일한 길이다.
        var delBtn = document.getElementById('veg-drawer-del');
        if (delBtn) delBtn.style.display = ro ? 'none' : '';
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
        var tBaseRow0 = '<div class="aot-modal-option-row">' +
          '<div class="aot-modal-option-label">' +
            _esc(_T('t_base', 'Base temperature')) + '</div>' +
          '<div class="aot-modal-option-control"><input type="number" step="any" ' +
            'class="form-control aot-modern-input" data-tbase="1" placeholder="' +
            _esc(_T('by_days', 'by days')) + '" value="' +
            (tBase == null ? '' : _esc(String(tBase))) + '"' +
            (ro ? ' disabled' : '') + '></div></div>';

        // 광합성 모델 상수. **접어 둔다** — 대부분의 사람은 손대지 않고,
        // 템플릿에서 만들면 이미 채워져 있다. 여기 있는 이유는 이것이 작물
        // 지식이기 때문이다: 예전에는 코디네이터 설정에서 코드에 박힌 작물
        // 5종 중 하나를 고르게 해, 같은 작물을 두 곳에서 정해야 했다.
        var photoRows = _PHOTO_FIELDS.map(function (f) {
          var v = (p.photosynthesis || {})[f.key];
          return '<div class="aot-modal-option-row">' +
            '<div class="aot-modal-option-label">' + _esc(_T(f.tkey, f.label)) +
              ' <span class="aot-prog-unit">' + _esc(f.unit) + '</span></div>' +
            '<div class="aot-modal-option-control"><input type="number" ' +
              'step="any" class="form-control aot-modern-input" data-photo="' +
              f.key + '" value="' + (v == null ? '' : _esc(String(v))) + '"' +
              (ro ? ' disabled' : '') + '></div></div>';
        }).join('');
        var photoBlock0 =
          '<details class="aot-prog-photo"><summary>' +
            _esc(_T('photo_model', 'Photosynthesis model')) +
          '</summary>' +
          '<div class="aot-modal-body-text">' +
            _esc(_T('photo_note',
              'Used only when the coordinator runs photosynthesis-oriented ' +
              'control. Leave them alone unless you have measured values — ' +
              'templates come filled in.')) +
          '</div>' + photoRows + '</details>';

        // 자동 승인(P7). **기본은 꺼짐** — 켜져 있는 것이 기본이면 사람이 아무
        // 결정도 하지 않았는데 단계가 스스로 넘어간다.
        var autoRow = '<div class="aot-modal-option-row">' +
          '<div class="aot-modal-option-label">' +
            _esc(_T('auto_advance', 'Advance stages automatically')) + '</div>' +
          '<div class="aot-modal-option-control">' +
            '<input type="checkbox" data-auto="1"' +
            (p.auto_advance ? ' checked' : '') + (ro ? ' disabled' : '') +
            '></div></div>';

        // 기준온도·적산온도·광합성 모델은 **식물 개념**이다. 종류가 식생이
        // 아니면 아예 내지 않는다 — 축사 프로그램에서 "광합성 지수" 를 본
        // 사람은 무엇을 적어야 할지 알 수 없고, 알 수 없는 칸이 하나 있으면
        // 화면 전체를 못 믿게 된다.
        var vegOnly = _isVeg()
          ? (tBaseRow0 +
             '<div class="aot-modal-body-text">' +
               _esc(_T('gdd_note',
                 'With a base temperature and a GDD per stage, stages ' +
                 'advance on accumulated heat instead of the calendar.')) +
             '</div>' + photoBlock0)
          : '';

        var head = _row(_T('name', 'Name'), 'name', p.name) +
                   _kindRow(p, ro) +
                   _subjectRow(p, ro) +
                   _row(_varietyLabel(p), 'variety', p.variety) +
                   autoRow +
                   '<div class="aot-modal-body-text">' +
                     _esc(_T('auto_advance_note',
                       'Stages are recorded without asking. The date comes ' +
                       'from the data, not from when you happen to look.')) +
                   '</div>' +
                   vegOnly;

        // `map` 은 index 를 두 번째 인자로 넘긴다 — 그대로 두면 첫 단계만
        // 접히고 나머지가 전부 펼쳐진다(open 으로 읽힌다).
        var stages = (p.stages || []).map(function (st) {
          return _stageRow(st);
        }).join('');
        var defsBlock = '<div class="veg-defs">' + _targetDefsSection(ro) + '</div>';
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

        // 단계를 어떻게 나눌지 모르는 사람에게 **나누지 않아도 된다**고 먼저
        // 말한다. 모르는 대상(축산 등)을 맡은 사람은 여기서 그만두는데, 사실
        // 단계 하나짜리 프로그램도 완전히 정상이다.
        //
        // 계절로 나누는 것을 특히 말린다 — 단계는 **시작일로부터의 경과일**이라
        // 시작일이 다르면 계절과 어긋나고, 해가 바뀌면 더 밀린다.
        var stageNote = ro ? '' :
          '<div class="aot-modal-body-text">' +
            _esc(_T('stages_note',
                    'One stage is fine. Split only where management actually ' +
                    'changes — stages run on days elapsed from the start date, ' +
                    'so they do not line up with calendar seasons.')) +
          '</div>';

        // 열 머리는 두지 않는다 — 접힌 항목에는 열이 없다. 각 칸의 라벨은
        // 펼친 상세에 값 위로 붙는다(`_stageField`).
        host.innerHTML = '<div class="aot-modal-container">' + head + defsBlock + curves +
                         '<div class="veg-stage-sub">' +
                         _esc(_T('stages', 'Stages')) + '</div>' + stageNote +
                         '<div class="veg-stages">' + stages + '</div>' +
                         actions + '</div>';
      });
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
             _esc(_subjectLabel(p)) + '"' + (ro ? ' disabled' : '') + '>';

    return '<div class="aot-modal-option-row">' +
           '<div class="aot-modal-option-label">' + _esc(_subjectLabel(p)) +
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
  /**
   * 목표 항목 관리 — 무엇을 목표로 삼을지 사람이 정한다.
   *
   * ## 고정 항목은 지우지 못하고 **숨긴다**
   *
   * 실제 시설이 모든 항목을 재거나 제어하지 못하는 것은 당연하다(노지 상추에
   * CO₂ 센서가 없는 것이 정상이다). 그래서 안 쓰는 항목은 숨겨 화면에서 치운다 —
   * 지우지 않는 이유는 어휘가 프로그램마다 달라지면 제어·AI 가 `co2` 를 못 찾기
   * 때문이고, 숨기기로 충분한 이유는 지운 것과 비운 것이 하류에서 똑같이
   * "값 없음" 이기 때문이다. 나중에 센서를 달면 되살릴 수 있다.
   *
   * ## 사용자 항목은 지울 수 있다
   *
   * 지울 때 **그 항목의 단계 값도 함께 지운다** — 남겨 두면 서버가 "정의에 없는
   * 값" 으로 거절한다(고아 값에는 화면에 그릴 라벨도 단위도 없다).
   */
  function _targetDefsSection(ro) {
    var defs = State.defs || [];
    var rows = defs.map(function (d, i) {
      var meta = [d.unit, d.measurement ? _T('measured', 'measured') : null]
        .filter(Boolean).join(' · ');
      // 값은 **여기 한 번** 적는다. 단계마다 다시 적게 하면 4단계 × 6항목이
      // 빈 칸 24개가 되고, 그중 대부분은 같은 값을 옮겨 적는 자리가 된다.
      var dval = (d['default'] == null) ? '' : d['default'];
      var valBox = '<input type="number" step="any" ' +
        'class="form-control aot-modern-input veg-def-val" ' +
        'data-def-val="' + _esc(d.key) + '" value="' + _esc(String(dval)) + '" ' +
        'placeholder="' + _esc(_T('unset', 'not set')) + '"' +
        (ro ? ' disabled' : '') + '>';

      var right = d.fixed
        ? '<label class="aot-modal-body-text">' +
            '<input type="checkbox" data-def-hide="' + _esc(d.key) + '"' +
            (d.hidden ? ' checked' : '') + (ro ? ' disabled' : '') + '> ' +
            _esc(_T('hide', 'Hide')) + '</label>'
        : (ro ? '' :
           '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
           'data-act="def-del" data-key="' + _esc(d.key) + '">' +
           _esc(_T('del', 'Delete')) + '</button>');
      return '<div class="aot-modal-option-row veg-def-row' +
               (d.hidden ? ' is-hidden' : '') + '" data-def-i="' + i + '">' +
               '<div class="aot-modal-option-label">' + _esc(d.label || d.key) +
                 (meta ? ' <span class="aot-modal-body-text">' + _esc(meta) +
                         '</span>' : '') + '</div>' +
               '<div class="aot-modal-option-control veg-def-ctl">' +
                 valBox + right + '</div>' +
             '</div>';
    }).join('');

    var adder = '';
    if (!ro) {
      // **자주 쓰는 것을 앞에 둔다.** 97개를 이름순으로만 늘어놓으면 온실·축사에서
      // 실제로 쓰는 대여섯 개를 찾는 데 목록을 다 훑어야 한다. 순서를 정하는 것일
      // 뿐 값을 정하는 것이 아니라, 어느 종류에나 같은 목록을 쓴다.
      var common = ['temperature', 'humidity', 'co2', 'vapor_pressure_deficit',
                    'radiation', 'light', 'speed', 'pressure', 'soil_moisture_cb',
                    'electrical_conductivity', 'ion_concentration'];
      var byKey = {};
      (State.measurements || []).forEach(function (m) { byKey[m.key] = m; });
      var opts = '<option value="">' +
                 _esc(_T('no_measurement', 'Reference target only')) +
                 '</option>';
      var seen = {};
      opts += '<optgroup label="' + _esc(_T('common', 'Common')) + '">';
      common.forEach(function (k) {
        if (!byKey[k]) return;
        seen[k] = 1;
        opts += '<option value="' + _esc(k) + '">' + _esc(byKey[k].name) + '</option>';
      });
      opts += '</optgroup><optgroup label="' + _esc(_T('all_items', 'All')) + '">';
      (State.measurements || []).forEach(function (m) {
        if (seen[m.key]) return;
        opts += '<option value="' + _esc(m.key) + '">' + _esc(m.name) + '</option>';
      });
      opts += '</optgroup>';

      // 이름·단위는 **측정 종류를 고르면 따라온다**(`def-meas` 핸들러). 셋을 다
      // 손으로 적게 하면 항목 하나 만드는 데 드는 품이 커서 아무도 안 만든다.
      // 고른 뒤에 이름을 자기 말로 바꾸는 것은 자유다.
      adder = '<div class="veg-def-add">' +
        '<select class="form-control aot-modern-input" data-def-new="measurement">' +
          opts + '</select>' +
        '<input type="text" class="form-control aot-modern-input" data-def-new="label" ' +
          'placeholder="' + _esc(_T('item_name', 'Item name')) + '">' +
        '<input type="text" class="form-control aot-modern-input" data-def-new="unit" ' +
          'placeholder="' + _esc(_T('item_unit', 'Unit')) + '">' +
        '<button type="button" class="btn aot-pill-btn" data-act="def-add">' +
          _esc(_T('add_item', 'Add item')) + '</button>' +
        '</div>';
    }

    return '<div class="veg-stage-sub">' +
             _esc(_T('target_items', 'Target items')) + '</div>' +
           '<div class="aot-modal-body-text">' +
             _esc(_T('target_items_note',
                     'Pick what this programme aims for. Items with a ' +
                     'measurement type are followed by the system; the rest ' +
                     'stand as reference targets you meet your own way. Hide ' +
                     'what you do not use, and leave anything blank you have ' +
                     'not decided.')) +
           '</div>' + rows + adder;
  }

  function _curveSection(p, ro) {
    if (!State.methods.length) return '';
    var cur = p.target_methods || {};
    var defs = _visibleDefs();
    if (!defs.length) return '';
    var rows = defs.map(function (d) {
      var opts = '<option value="">' + _esc(_T('curve_none', 'Fixed value')) +
                 '</option>';
      State.methods.forEach(function (m) {
        opts += '<option value="' + _esc(m.unique_id) + '"' +
                (cur[d.key] === m.unique_id ? ' selected' : '') + '>' +
                _esc(m.name) + '</option>';
      });
      return '<label class="veg-target-field">' +
               '<span class="aot-modal-body-text">' +
                 _esc(d.label || d.key) + '</span>' +
               '<select class="form-control aot-modern-input" data-cf="' + _esc(d.key) + '"' +
                 (ro ? ' disabled' : '') + '>' + opts + '</select>' +
             '</label>';
    }).join('');
    // 제목·설명을 **라벨 열 안에** 넣지 않는다. 공용 option-row 의 라벨 열은
    // 좁아서(모바일에서 ~10자) "곡선을 연결하면 그 / 항목은 단계 값 대신" 처럼
    // 끊긴다. 단계 상세와 같은 골격 — 제목 줄, 설명 줄, 그리고 격자.
    return '<div class="veg-stage-sub">' + _esc(_T('curves', 'Target curves')) +
           '</div>' +
           '<div class="aot-modal-body-text">' +
             _esc(_T('curves_note',
                     'A curve overrides the stage value for that item. ' +
                     'Time runs from the start date.')) +
           '</div>' +
           '<div class="veg-stage-targets">' + rows + '</div>';
  }

  /**
   * 항목 정의 섹션과 각 단계의 목표 칸을 다시 그린다.
   *
   * **이미 입력된 값을 보존한다** — 항목 하나를 더했다고 사람이 적어 둔 단계
   * 값이 사라지면 그건 저장 전에 데이터를 잃는 것이다. 그래서 지금 화면의
   * 값을 읽어 두었다가 새로 그린 칸에 되돌려 놓는다.
   */
  function _redrawDefs(drawer) {
    var keep = [];
    drawer.querySelectorAll('.veg-stage-block').forEach(function (block) {
      var vals = {};
      block.querySelectorAll('[data-tf]').forEach(function (el) {
        if ((el.value || '').trim() !== '') vals[el.getAttribute('data-tf')] = el.value;
      });
      keep.push(vals);
    });

    var box = drawer.querySelector('.veg-defs');
    if (box) box.innerHTML = _targetDefsSection(false);

    drawer.querySelectorAll('.veg-stage-block').forEach(function (block, i) {
      var host = block.querySelector('.veg-stage-targets');
      if (!host) return;
      host.innerHTML = _targetInputs(keep[i] || {});
    });
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

    // 기준온도와 모델 상수는 같은 JSON 에 담긴다. **비운 칸은 키를 지운다** —
    // 남겨 두면 "예전에 넣었던 값" 이 계속 쓰인다.
    var tb = host.querySelector('[data-tbase]');
    if (tb) {
      var photo = {};
      var raw = (tb.value || '').trim();
      if (raw !== '') photo.T_base = raw;
      host.querySelectorAll('[data-photo]').forEach(function (el) {
        var v = (el.value || '').trim();
        if (v !== '') photo[el.getAttribute('data-photo')] = v;
      });
      out.photosynthesis = Object.keys(photo).length ? photo : null;
    }

    var curves = {};
    host.querySelectorAll('[data-cf]').forEach(function (el) {
      if (el.value) curves[el.getAttribute('data-cf')] = el.value;
    });
    // 곡선 칸이 화면에 있을 때만 보낸다 — 없는 화면에서 보내면 부분 저장이
    // 멀쩡한 설정을 지운다.
    if (host.querySelector('[data-cf]')) out.targets_methods = curves;

    // 항목 정의 — 숨김 상태를 화면에서 읽어 얹는다. 정의 섹션이 있는 화면에서만
    // 보낸다(없는 화면에서 보내면 부분 저장이 멀쩡한 정의를 지운다).
    if (host.querySelector('.veg-def-row') || host.querySelector('[data-def-new]')) {
      var hides = {};
      host.querySelectorAll('[data-def-hide]').forEach(function (el) {
        hides[el.getAttribute('data-def-hide')] = !!el.checked;
      });
      var vals = {};
      host.querySelectorAll('[data-def-val]').forEach(function (el) {
        vals[el.getAttribute('data-def-val')] = (el.value || '').trim();
      });
      out.target_defs = (State.defs || []).map(function (d) {
        var c = {};
        Object.keys(d).forEach(function (k) { c[k] = d[k]; });
        if (hides.hasOwnProperty(d.key)) c.hidden = hides[d.key];
        // 빈 칸은 **키를 지운다** — 남겨 두면 예전 기본값이 계속 쓰인다.
        if (vals.hasOwnProperty(d.key)) {
          if (vals[d.key] === '') delete c['default'];
          else c['default'] = vals[d.key];
        }
        return c;
      });
    }

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
        // 빈 칸은 **보내지 않는다** — 0 과 미지정을 구분해야 한다. 비어 있는
        // 것은 정상이다(그 시설이 그 항목을 재지 못하는 일이 흔하다).
        if (v !== '') t[el.getAttribute('data-tf')] = v;
      });
      if (Object.keys(t).length) st.targets = t;
      // 지침은 **빈 문자열도 보낸다** — 지운 것을 반영해야 하기 때문이다(값이
      // 있는 칸과 달리 "미지정" 과 "빈 글" 을 구분할 이유가 없다).
      var gel = block.querySelector('[data-guidance]');
      if (gel) st.guidance = gel.value || '';
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
        //
        // **종류를 만들 때 고른다.** 만든 뒤에 바꾸게 하면 식생 고정 항목 여섯이
        // 먼저 들어왔다가 종류를 바꿀 때 빠지고, 값을 이미 적었다면 그 전환이
        // 거절된다 — 축사 프로그램 하나 만드는 데 거쳐야 할 단계가 늘어난다.
        _api('POST', '/api/geo/program', {
          name: _T('new_program', 'New program'),
          subject: _T('new_subject', 'unnamed'),
          kind: (document.getElementById('veg-kind') || {}).value || 'vegetation',
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
      // 푸터의 삭제·복제는 카드 밖에 있다 — 지금 열려 있는 프로그램이 대상이다.
      var uuid = (item && item.dataset.uuid) || (host && host.dataset.detail)
                 || State.openId;
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
            _closeDrawer();
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
            _closeDrawer();
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
    // 측정 종류를 고르면 **이름과 단위가 따라온다.** 비어 있을 때만 채운다 —
    // 사람이 이미 자기 말로 적었으면 그것을 덮지 않는다.
    var drawerEl = document.getElementById('veg-drawer-body');
    if (drawerEl) drawerEl.addEventListener('change', function (e) {
      var el = e.target;
      // **종류를 바꾸면 화면이 바로 따라온다.** 저장해야 반영되면, 축사로
      // 바꾼 사람이 광합성 칸을 그대로 보면서 "이걸 어떻게 하지" 를 먼저 만난다.
      // 편집 중인 값은 서버에 저장하지 않고 드로어만 다시 그린다.
      if (el && el.getAttribute && el.getAttribute('data-pf') === 'kind') {
        var uid = State.openId;
        if (uid) {
          var pending = collect(document.getElementById('veg-drawer-body'));
          _pendingKind = el.value;
          // **서버와 같은 규칙으로** 정의를 다시 세운다: 새 종류의 고정 항목 +
          // 사람이 만든 항목. 이전 종류의 고정 항목은 따라오지 않는다(따라오면
          // 축사 화면에 DLI 가 "사용자 항목" 으로 남는다). 이미 적어 둔 기본값과
          // 숨김은 키가 같은 항목에 한해 이어받는다.
          var prev = {};
          (pending.target_defs || []).forEach(function (d) { prev[d.key] = d; });
          var next = (State.fixedDefs[el.value] || []).map(function (d) {
            var c = {}; Object.keys(d).forEach(function (k) { c[k] = d[k]; });
            var was = prev[d.key];
            if (was) {
              c.hidden = !!was.hidden;
              if (was['default'] != null) c['default'] = was['default'];
            }
            return c;
          });
          (pending.target_defs || []).forEach(function (d) {
            if (!d.fixed) next.push(d);
          });
          pending.target_defs = next;
          openEditor(uid, pending);
        }
        return;
      }
      // 단계에서 덮어쓸 항목을 고르면 그 자리에 칸이 생긴다.
      if (el && el.hasAttribute && el.hasAttribute('data-tf-add') && el.value) {
        var blk = el.closest('.veg-stage-block');
        var host = blk && blk.querySelector('.veg-stage-targets');
        if (host) {
          var cur = {};
          host.querySelectorAll('[data-tf]').forEach(function (x) {
            if ((x.value || '').trim() !== '') cur[x.getAttribute('data-tf')] = x.value;
          });
          var d = (State.defs || []).filter(function (x) {
            return x.key === el.value; })[0];
          // 기본값이 있으면 그것을 넣고 시작한다 — 빈 칸에서 시작하면 "덮어쓴다"
          // 는 뜻이 아니라 "비운다" 로 읽힌다.
          cur[el.value] = (d && d['default'] != null) ? d['default'] : '';
          host.innerHTML = _targetInputs(cur);
          var added = host.querySelector('[data-tf="' + el.value + '"]');
          if (added) added.focus();
        }
        return;
      }
      if (!el || el.getAttribute('data-def-new') !== 'measurement') return;
      var m = (State.measurements || []).filter(function (x) {
        return x.key === el.value;
      })[0];
      if (!m) return;
      var box = el.closest('.veg-def-add');
      if (!box) return;
      var lab = box.querySelector('[data-def-new="label"]');
      var uni = box.querySelector('[data-def-new="unit"]');
      if (lab && !(lab.value || '').trim()) lab.value = m.name || '';
      if (uni && !(uni.value || '').trim()) uni.value = (m.units || [])[0] || '';
    });

    var drawer = document.getElementById('veg-drawer-body');
    if (drawer) drawer.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-act]');
      if (!btn) return;
      var act = btn.dataset.act;
      if (act === 'def-add') {
        // 키는 이름에서 만든다(서버 규칙: 소문자로 시작하는 영문·숫자·밑줄).
        // 만들 수 없으면 순번으로 떨어진다 — 사람에게 키를 묻지 않는다.
        var lab = (drawer.querySelector('[data-def-new="label"]') || {}).value || '';
        lab = lab.trim();
        if (!lab) return;
        var key = lab.toLowerCase().replace(/[^a-z0-9_]+/g, '_')
                     .replace(/^_+|_+$/g, '').slice(0, 32);
        if (!/^[a-z]/.test(key)) key = 'item_' + ((State.defs || []).length + 1);
        if ((State.defs || []).some(function (d) { return d.key === key; })) {
          _toast(_T('dup_item', 'That item already exists.'), 'error');
          return;
        }
        var unitEl = drawer.querySelector('[data-def-new="unit"]');
        var measEl = drawer.querySelector('[data-def-new="measurement"]');
        State.defs = (State.defs || []).concat([{
          key: key, label: lab,
          unit: (unitEl && unitEl.value || '').trim() || null,
          measurement: (measEl && measEl.value) || null,
          shape: 'instant', min: null, max: null,
          fixed: false, hidden: false
        }]);
        _redrawDefs(drawer);
        return;
      } else if (act === 'def-del') {
        var dk = btn.getAttribute('data-key');
        // **그 항목의 단계 값도 함께 지운다** — 남겨 두면 서버가 "정의에 없는
        // 값" 으로 거절한다. 몇 개를 지우는지 먼저 말한다(조용히 지우지 않는다).
        var hit = 0;
        drawer.querySelectorAll('[data-tf="' + dk + '"]').forEach(function (el) {
          if ((el.value || '').trim() !== '') hit += 1;
        });
        var msg = hit
          ? _T('del_item_values', 'Delete this item? {n} stage value(s) will be removed.')
              .replace('{n}', String(hit))
          : _T('del_item', 'Delete this item?');
        if (!window.confirm(msg)) return;
        State.defs = (State.defs || []).filter(function (d) { return d.key !== dk; });
        drawer.querySelectorAll('[data-tf="' + dk + '"]').forEach(function (el) {
          el.value = '';
        });
        _redrawDefs(drawer);
        return;
      } else if (act === 'stage-add') {
        drawer.querySelector('.veg-stages')
              .insertAdjacentHTML('beforeend', _stageRow(null, true));
      } else if (act === 'stage-toggle') {
        // 한 번에 하나만 펼친다 — 7단계가 동시에 펼쳐지면 표로 돌아간 것과 같다.
        var blk = btn.closest('.veg-stage-block');
        var opening = blk && blk.hasAttribute('data-collapsed') === false
                          && !blk.classList.contains('is-open');
        drawer.querySelectorAll('.veg-stage-block.is-open').forEach(function (b) {
          if (b === blk) return;
          b.classList.remove('is-open');
          var d = b.querySelector('.veg-stage-detail');
          if (d) d.hidden = true;
        });
        if (blk) {
          var open = !blk.classList.contains('is-open');
          blk.classList.toggle('is-open', open);
          var det = blk.querySelector('.veg-stage-detail');
          if (det) det.hidden = !open;
        }
        void opening;
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
