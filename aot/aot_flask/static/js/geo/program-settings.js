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

  // ── 공용 골격 헬퍼 ──────────────────────────────────────────────────
  //
  // 이 화면은 **AoT 현대화 모달 골격**만 쓴다(`aot-modal-*` + `btn-toggle`).
  // 자체 행 모양을 하나 만들면 같은 드로어 안에 두 문법이 생기고, 공용 CSS 가
  // 갖고 있는 모바일 규칙이 그 한쪽에만 걸린다.

  /**
   * 한 줄 = 설정 하나. **1행 [제목][컨트롤] · 2행 [설명]** 이고, 구분선은 그
   * 둘을 감싼 행 아래에 온다.
   *
   * 설명이 행 **밖**에 있으면 공용 `aot-modal-option-row` 의 아래쪽 구분선이
   * 제목과 설명 사이를 갈라 설명이 **다음 항목의 것**처럼 읽힌다. 그렇다고
   * 라벨 **안**에 넣으면 라벨 열(160px 컨트롤을 뺀 나머지)에 갇혀 대여섯
   * 글자마다 끊긴다. 그래서 **행 안, 라벨 밖** 세 번째 자식으로 두고 `wrap`
   * 으로 다음 줄에 내린다 — 제목은 컨트롤과 나란히, 설명은 전체 폭.
   */
  function _optRow(label, note, control, cls, tip) {
    // `tip` 이면 설명을 줄로 내지 않고 **전역 툴팁**으로 붙인다 — 제목만으로
    // 뜻이 서는 스위치인데 설명이 늘 펼쳐져 있으면 화면만 길어진다.
    // (layout 의 tooltip 초기화가 `[data-toggle="tooltip"]` 을 잡는다.)
    var tipAttr = tip
      ? ' data-toggle="tooltip" title="' + _esc(note) + '"' : '';
    return '<div class="aot-modal-option-row veg-row' +
             (cls ? ' ' + cls : '') + '"' + tipAttr + '>' +
           '<div class="aot-modal-option-label">' + _esc(label) + '</div>' +
           '<div class="aot-modal-option-control">' + control + '</div>' +
           (note && !tip ? '<div class="aot-modal-body-text veg-row-note">' +
                   _esc(note) + '</div>' : '') +
           '</div>';
  }

  /**
   * 컨트롤이 전체 폭을 쓰는 행(여러 줄 입력). 순서는 제목 → 설명 → 컨트롤 이다
   * — 여러 줄 입력은 제목과 나란히 설 수 없으므로 설명을 먼저 읽고 쓰게 한다.
   */
  function _wideRow(label, note, control) {
    return '<div class="aot-modal-option-row veg-row veg-row-wide">' +
           '<div class="aot-modal-option-label">' + _esc(label) + '</div>' +
           (note ? '<div class="aot-modal-body-text veg-row-note">' +
                   _esc(note) + '</div>' : '') +
           '<div class="aot-modal-option-control">' + control + '</div>' +
           '</div>';
  }

  /**
   * 전역 슬라이드 토글(`components/aot-toggle.css`).
   *
   * 시스템 전체가 "쓸 것인가" 를 이 모양으로 말한다. 맨 체크박스를 쓰면 이
   * 화면만 다르게 보이고, 좁은 화면에서 손가락이 닿을 면적도 모자란다.
   * 예전에 자원 토글이 쓰던 `.aot-switch` 는 **저장소 어디에도 정의가 없어**
   * 아무 스타일도 안 걸린 맨 체크박스로 렌더됐다.
   */
  function _toggle(attrs, on, ro) {
    return '<label class="btn-toggle mb-0">' +
             '<input type="checkbox" class="btn-toggle-input" ' + attrs +
               (on ? ' checked' : '') + (ro ? ' disabled' : '') + '>' +
             '<span class="btn-toggle-slider">' +
               '<span class="btn-toggle-thumb"></span></span>' +
           '</label>';
  }

  /** 그룹 제목 — 상자(`aot-modal-container`) **밖**에 선다. 상자 경계가 곧
   *  "여기부터 여기까지가 한 덩이" 라는 말이 된다. */
  function _group(title, note) {
    return '<div class="aot-modal-group-title">' + _esc(title) + '</div>' +
           (note ? '<div class="aot-modal-body-text aot-prog-group-note">' +
                   _esc(note) + '</div>' : '');
  }

  /** 상자 하나. 그룹 안에서 성격이 갈리는 묶음마다 하나씩. */
  function _box(inner) {
    return '<div class="aot-modal-container">' + inner + '</div>';
  }

  /**
   * 단계 트랙 — **막대가 곧 메뉴다**.
   *
   * 예전에는 가로 막대(비율)와 세로 목록(편집)이 따로 있었다. 같은 것을 두 방향
   * 으로 두 번 그리는 셈이라, 어느 단계를 고치려면 막대에서 위치를 눈으로 찾고
   * 목록에서 그 이름을 다시 찾아 펼쳐야 했다 — 마우스가 왕복하고, 여섯 단계가
   * 세로 공간을 전부 차지했다.
   *
   * 지금은 막대의 구간이 곧 버튼이고, 고른 구간 **하나**만 아래에서 편집한다.
   * 순서는 구간을 끌어 옮긴다.
   *
   * ## 공용 `AoTViz.timeline()` 을 쓰지 않는 이유
   *
   * 그것은 **읽기 전용 시각화**다(지도 위젯의 작기 진행 바). 여기 필요한 것은
   * 고르고 끌 수 있는 **편집 컨트롤**이라 애초에 다른 물건이고, 상호작용을
   * 넣자고 공용 컴포넌트를 고치면 그 위젯까지 함께 흔들린다. 대신 색·높이는
   * 같은 토큰을 쓴다(`components/aot-dataviz.css` 와 나란히 보이게).
   *
   * ## 폭은 비율이되 **최소폭이 있다**
   *
   * 7일짜리 단계는 80일 중 8.75% 라 520px 드로어에서 45px 다. 그대로 두면 이름도
   * 안 보이고 끌기도 어렵다 — 비율 감각보다 **조작 가능성**이 먼저다.
   */
  function _trackHtml() {
    var stages = State.stages || [];
    if (!stages.length) return '';
    var known = [];
    stages.forEach(function (st) {
      var d = parseFloat(st && st.days);
      if (isFinite(d) && d > 0) known.push(d);
    });
    var sum = 0;
    known.forEach(function (d) { sum += d; });
    var avg = known.length ? (sum / known.length) : 1;
    var openEnd = false;
    var spans = stages.map(function (st) {
      var d = parseFloat(st && st.days);
      var ok = isFinite(d) && d > 0;
      if (!ok) openEnd = true;
      return ok ? d : Math.max(avg, 1);
    });
    var total = 0;
    spans.forEach(function (x) { total += x; });

    // 기간을 비운 마지막 단계("끝까지")는 길이를 모른다. 자리는 주되 **총합에는
    // 더하지 않는다** — 더하면 화면의 총 일수가 거짓말이 된다.
    var text = sum
      ? _T('n_days', '{n} days').replace('{n}', String(Math.round(sum))) : '';
    if (openEnd) {
      text = text ? (text + ' \u00b7 ' + _T('until_end', 'until the end'))
                  : _T('until_end', 'until the end');
    }

    var segs = stages.map(function (st, i) {
      var d = parseFloat(st && st.days);
      var w = total > 0 ? (spans[i] / total) * 100 : (100 / stages.length);
      var days = (isFinite(d) && d > 0) ? String(d)
                                        : _T('until_end', 'until the end');
      var name = (st && st.name) || _T('stage_name', 'Stage name');
      // 한 구간 = [이름 / 막대 조각 / 일수]. **버튼이지만 버튼처럼 그리지
      // 않는다** — 테두리도 배경도 없고, 보이는 것은 가운데 막대 조각뿐이라
      // 여섯 개가 이어져 하나의 트랙으로 읽힌다.
      return '<button type="button" class="veg-track-seg' +
               (i === State.curStage ? ' is-current' : '') +
               '" style="flex:1 1 ' + w.toFixed(2) + '%"' +
               ' data-act="stage-pick" data-stage-i="' + i + '"' +
               ' title="' + _esc(name + ' \u00b7 ' + days) + '"' +
               ' aria-pressed="' + (i === State.curStage) + '">' +
               '<span class="veg-track-name">' + _esc(name) + '</span>' +
               '<span class="veg-track-bar"></span>' +
               '<span class="veg-track-days">' + _esc(days) + '</span>' +
             '</button>';
    }).join('');

    // 겉모양은 공용 기간 바 그대로다 — 컨테이너에 `aot-viz` 를 함께 붙여
    // **그 토큰을 상속받는다**(트랙 굵기·구간 색·표면색·다크 override).
    // 색을 여기에 다시 적으면 공용 팔레트가 바뀔 때 이 화면만 남는다.
    return '<div class="aot-viz veg-track-wrap">' +
             '<div class="aot-viz-head">' +
               '<span class="aot-viz-label">' +
                 _esc(_T('total_span', 'Whole run')) + '</span>' +
               '<span class="aot-viz-value">' + _esc(text) + '</span>' +
             '</div>' +
             '<div class="veg-track" role="tablist">' + segs + '</div>' +
           '</div>';
  }

  /** 트랙만 다시 그린다(이름·기간을 고치는 즉시 폭과 숫자가 따라온다). */
  function _refreshTrack(host) {
    var box = host && host.querySelector('.veg-track-host');
    if (!box) return;
    box.innerHTML = _trackHtml();
    // 단계가 많으면 트랙이 가로로 넘친다 — 고른 구간이 화면 밖에 있으면
    // "아무것도 안 골랐다" 로 보인다.
    var cur = box.querySelector('.veg-track-seg.is-current');
    if (cur && cur.scrollIntoView) {
      try { cur.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
      catch (e) {}
    }
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

  var State = { programs: [], templates: [], methods: [], defs: [], measurements: [], fixedDefs: {},
               resourceDefs: [], tabs: [],
                // 편집 중인 단계의 **정본**. 화면에는 고른 단계 하나만 그리므로
                // DOM 을 정본으로 둘 수 없다 — 다른 단계로 옮기는 순간 그 값이
                // 사라진다. 패널을 떠날 때마다 여기로 읽어 넣는다.
                stages: [], curStage: 0,
                // "단계마다 다르게" — **화면 전용**이다(저장하지 않는다).
                perStageTargets: false, perStageRes: false,
                openId: null,
                // 초기 활성 탭은 서버가 렌더한 페이지가 안다(routes_geo.page_programs
                // 가 탭 부트스트랩과 백필까지 마친 뒤 넘겨준 탭).
                //
                // ⚠ 예전 주석은 "null 로 남는 경우는 사실상 없다" 고 적혀 있었는데
                // **틀렸다.** 새 설치에는 program 탭이 아예 없어 백필 자체가 돌지
                // 않았고, 그때 이 값이 null 이라 이름조차 저장되지 않았다. 서버가
                // 탭을 만들어 주도록 고쳤지만, 그 사람이 그 탭을 조작할 수 없으면
                // (그룹 스코프) 여전히 null 이 올 수 있다.
                activeTabId: (typeof window !== 'undefined' && window._PROG &&
                             window._PROG.currentTabId) || null,
                searchQuery: '' };

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
      // 자원 함수 목록은 **더 이상 받지 않는다**(P6 재설계, 2026-08-20).
      // 프로그램은 함수를 고르지 않는다 — 역할만 선언하고, 무엇이 그 일을 하는지는
      // 현장이 기하로 푼다. 고르는 칸이 없으니 목록도 필요 없다.
      Promise.resolve(null),
      // 탭 목록 — 드로어의 "탭 이동" 셀렉트가 쓴다. 탭바 자체는 서버가 렌더하지만
      // (macros/tabs.html), 드로어는 별도 DOM이라 같은 목록을 JS로도 갖고 있어야
      // 한다.
      fetch('/tab/list?page_type=program', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).catch(function () { return null; })
    ]).then(function (res) {
      State.programs = (res[0] && res[0].ok) ? (res[0].programs || []) : [];
      State.templates = (res[1] && res[1].ok) ? (res[1].templates || []) : [];
      State.methods = (res[2] && res[2].ok) ? (res[2].methods || []) : [];
      State.measurements = (res[3] && res[3].ok) ? (res[3].measurements || []) : [];
      State.fixedDefs = (res[3] && res[3].ok) ? (res[3].fixed_defs || {}) : {};
      State.tabs = (res[5] && res[5].success) ? (res[5].tabs || []) : [];
      renderBase();
      renderList();
    });
  }

  /**
   * 추가 줄의 선택지 — 빈 것 / 템플릿.
   *
   * **내 프로그램 복제는 여기 두지 않는다**(2026-08-21 제거). 복제는 카드를
   * 열면 드로어 푸터에 [복제] 로 있고, 같은 일을 하는 길이 둘이면 목록만
   * 길어진다 — 프로그램이 늘수록 이 드롭다운이 자기 프로그램으로 가득 찬다.
   *
   * 템플릿이 앞이다. AI 를 쓰지 않는 사용자에게 처음 만드는 부담을 덜어 줄
   * 수 있는 것은 템플릿뿐이라, 빈 프로그램부터 단계를 손으로 다 적게 하면
   * 거기서 그만두게 된다.
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
    sel.innerHTML = html;
    // selectpicker 는 원본 select 를 **복제해** 자기 목록을 그린다. innerHTML 을
    // 갈아끼운 뒤 알리지 않으면 화면에는 옛 목록(여기서는 "불러오는 중…")이
    // 그대로 남는다 — 값은 바뀌는데 보이는 것만 낡는 종류라 알아채기 어렵다.
    if (window.jQuery && window.jQuery.fn && window.jQuery.fn.selectpicker) {
      window.jQuery(sel).selectpicker('refresh');
    }
  }

  // ── 목록 ──────────────────────────────────────────────────────────────

  /** 품종 라벨은 종류에 따라 달라진다(common/aot-plot-labels.js) — 식생·가축은
   *  "품종", 시설은 "규격", 그 밖은 "세부 구분". 도로·구조물을 관리하는 화면이
   *  품종을 물으면 그 화면은 그냥 틀린 말을 한다. */
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
    return _optRow(_T('kind', 'Kind'), '', sel);
  }

  var _KINDS = ['vegetation', 'livestock', 'facility', 'other'];

  /**
   * 탭 이동 셀렉트 — **의도적으로 `data-pf`를 쓰지 않는다.**
   *
   * `collect()`는 `[data-pf]`를 전부 모아 메인 "저장" 버튼 페이로드에 합친다.
   * 내장·외부 프로그램은 그 필드들이 `disabled`라도 `el.value`는 여전히 읽히므로,
   * 탭 셀렉트를 그 흐름에 태우면 "저장"을 누를 때 콘텐츠 필드가 안 바뀐 값
   * 그대로 함께 전송되고, 서버의 `is_editable()` 게이트가 이를 걸러 저장 자체가
   * 막힌다 — 탭 이동은 콘텐츠 편집 가능 여부와 무관해야 하는데 얽혀버린다.
   * 그래서 이 셀렉트는 `change` 시 **자기 값만** 즉시 PATCH한다(아래 wire()).
   */
  function _tabRow(p) {
    var opts = (State.tabs || []).map(function (t) {
      return '<option value="' + _esc(t.unique_id) + '"' +
             (t.unique_id === p.tab_id ? ' selected' : '') + '>' +
             _esc(t.name) + '</option>';
    }).join('');
    return _optRow(_T('tab', 'Tab'), '',
      '<select class="form-control aot-modern-input" id="veg-tab-move">' +
      opts + '</select>');
  }

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
      // 품목은 빼고 품종만 — 드로어에서 못 고치는 값을 카드에 보이면 "이건
      // 어디서 바꾸나" 가 된다. 이름이 그 자리를 이미 말하고 있다.
      p.variety ? _esc(p.variety) : '',
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

  /** 지금 활성 탭에 속한 프로그램만. 탭 인프라 도입 전 레거시 NULL 행은
   * 서버(routes_geo.page_programs)가 페이지 로드 시점에 항상 먼저 기본 탭으로
   * 백필하므로, 여기서 다시 신경 쓰지 않는다. */
  function _byTab(p) {
    if (!State.activeTabId) return true;
    return p.tab_id === State.activeTabId;
  }

  /**
   * 이름·대상·품종뿐 아니라 **메모·근거·단계 지침 속 단어**로도 찾는다.
   * "습도" 처럼 지침에만 적혀 있고 제목에는 없는 말로도 찾을 수 있어야
   * 검색이 실제로 쓸모 있다 — 제목만 대상이면 프로그램 이름을 이미 아는
   * 사람만 쓸 수 있는 필터가 된다. `guidance_text`/`notes`/`source_note`
   * 는 서버가 목록 응답에도 함께 낸다(`program_io.to_dict`).
   *
   * 탭으로 이미 나뉜 목록 **안에서** 찾는 2차 필터라 서버 재조회는 하지
   * 않는다(이미 받아 온 State.programs에서 거름).
   */
  function _bySearch(p) {
    var q = (State.searchQuery || '').trim().toLowerCase();
    if (!q) return true;
    var hay = [p.name, p.subject, p.variety, p.notes, p.source_note,
               p.guidance_text].filter(Boolean).join(' ').toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function renderList() {
    var box = document.getElementById('veg-list');
    if (!box) return;
    var visible = State.programs.filter(_byTab).filter(_bySearch);
    if (!visible.length) {
      var msgKey = (State.searchQuery || '').trim() ? 'empty_search' : 'empty';
      var msgFallback = msgKey === 'empty_search'
        ? 'No programs match your search.' : 'No programs yet.';
      box.innerHTML = '<div class="aot-modal-container">' +
                      '<div class="aot-modal-body-text">' +
                      _esc(_T(msgKey, msgFallback)) + '</div></div>';
      return;
    }
    box.innerHTML = visible.map(_rowHtml).join('');
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
        // **한 줄에 하나** — 위쪽 목표 목록과 같은 골격이다. 격자로 두면 좁은
        // 폭에서 라벨과 칸이 어긋난다.
        return _optRow((d.label || d.key) + (d.unit ? ' (' + d.unit + ')' : ''), '',
          '<input type="number" step="any" class="form-control aot-modern-input" ' +
            'data-tf="' + _esc(d.key) + '" value="' + _esc(String(t[d.key])) + '">');
      }).join('');

    // 아직 덮어쓰지 않은 항목만 고르기에 남긴다.
    var rest = defs.filter(function (d) { return t[d.key] == null; });
    var picker = '';
    if (rest.length) {
      var opts = '<option value=""></option>';
      rest.forEach(function (d) {
        var base = (d['default'] == null) ? '' :
                   ' (' + _T('default_is', 'default {v}')
                            .replace('{v}', String(d['default'])) + ')';
        opts += '<option value="' + _esc(d.key) + '">' +
                _esc((d.label || d.key) + base) + '</option>';
      });
      picker = _optRow(_T('override_pick', 'Set a different value here…'), '',
        '<select class="form-control aot-modern-input" data-tf-add>' +
        opts + '</select>');
    }
    return rows + picker;
  }

  // 자원(관수·시비) — **역할 선언**이다(P6 재설계, 2026-08-20).
  //
  // 프로그램은 "이 작물은 관수를 쓴다" 까지만 말하고 **어느 함수가 그 일을 하는지
  // 적지 않는다.** 계획이 현장을 미리 지정하면 같은 프로그램을 두 번째 온실에서
  // 쓸 때 복제해야 하고, 그 순간 작물 지식이 두 벌이 되어 한쪽만 고쳐진다.
  // 무엇이 그 일을 하는지는 현장이 기하로 푼다(구획 모달이 보인다).
  //
  // 선언일 뿐이고 프로그램이 켜지 않는다 — 물이 나오는 일이라 사람이 누른다.
  var _RES_ROLES = ['irrigation', 'fertigation', 'other'];

  function _roleChoices() {
    // 관수·시비는 **식물 개념**이다. 축사·시설에 그 칸을 내면 무엇을 걸어야
    // 할지 알 수 없다. 가축용 역할 어휘(급이·급수 등)를 지어내지는 않는다 —
    // 근거 없는 어휘는 한 번 퍼지면 되돌리기 어렵다. 그때는 역할 없는 자원
    // 하나만 남긴다(`other`).
    return _isVeg() ? _RES_ROLES : ['other'];
  }

  /** 프로그램 레벨 — 이 프로그램이 쓰는 역할과 **단계 기본값**. */
  function _resourceDefsSection(ro) {
    var cur = {};
    (State.resourceDefs || []).forEach(function (d) {
      if (d && d.role) cur[d.role] = (d.default !== false);
    });
    return _roleChoices().map(function (role) {
      var on = Object.prototype.hasOwnProperty.call(cur, role);
      // **찾을 수 있는 역할과 적어 두기만 하는 역할을 구분해 말한다.** 지금
      // 현장 어휘가 있는 것은 관수뿐이다(`plot_context._ROLE_FITTING_KINDS` 는
      // `irrigation` 하나만 갖는다). 말하지 않으면 시비를 켜 둔 사람이 "왜
      // 아무 일도 안 일어나지" 를 혼자 헤맨다.
      var note = (role === 'irrigation')
        ? _T('res_resolved', 'Matched to irrigation valves on the facility plan.')
        : _T('res_intent_only', 'Recorded as intent — nothing to match it to yet.');
      return _optRow(_T('res_' + role, role), note,
                     _toggle('data-rdef="' + role + '"', on, ro));
    }).join('');
  }

  /** 단계 레벨 — 선언된 역할의 **on/off 덮어쓰기**만. */
  function _resourceRows(st) {
    var defs = (State.resourceDefs || []).filter(function (d) {
      return d && d.role;
    });
    if (!defs.length) return '';
    var over = (st && st.resources) || {};
    return defs.map(function (d) {
      var role = d.role;
      var base = (d.default !== false);
      var has = Object.prototype.hasOwnProperty.call(over, role);
      var on = has ? !!over[role] : base;
      // 기본값을 따르는 상태와 덮어쓴 상태를 **구분해 보인다** — 수확 전 단수
      // 처럼 일부러 끈 단계가 있고, 그것을 빈 칸으로 두면 실수와 구분되지 않는다.
      var note = has ? _T('res_overridden', 'set for this stage')
                     : _T('res_from_default', 'follows the programme');
      return _optRow(_T('res_' + role, role), note,
                     _toggle('data-rf="' + role + '"', on, false));
    }).join('');
  }

  /**
   * 고른 단계 하나의 설정 — 화면에 **한 벌만** 있다.
   *
   * 예전에는 단계마다 접힌 블록을 만들어 세로로 쌓았다. 여섯 단계면 여섯 벌이
   * DOM 에 있고, 그중 하나만 펼쳐 쓰면서 나머지가 자리를 차지했다. 게다가 가로
   * 막대(비율)와 세로 목록(편집)이 같은 것을 두 방향으로 두 번 그려, 어느
   * 단계를 고치려면 막대에서 위치를 찾고 목록에서 이름을 다시 찾아야 했다.
   *
   * 지금은 **트랙의 구간이 곧 메뉴**이고 고른 것 하나만 여기 그린다.
   *
   * ⚠ 그래서 **편집 중인 값의 정본이 DOM 이 아니라 `State.stages` 다.** 다른
   * 단계로 옮길 때 지금 패널을 읽어 거기에 넣고(`_readStagePanel`), 저장도 그
   * 배열에서 만든다. 이 순서를 놓치면 방금 적은 것이 조용히 사라진다.
   */
  function _stagePanel() {
    var st = (State.stages || [])[State.curStage];
    if (!st) return '';
    var res = _resourceRows(st);
    return '<div class="veg-stage-panel" data-stage-panel>' +
             // **한 줄에 설정 하나.** 같은 줄에 칸이 둘이면 어느 라벨이 어느
             // 칸의 것인지 한 번 확인하게 되고, 위쪽 기본 정보와 문법이 갈린다.
             _stageField(_T('stage_name', 'Stage name'), 'name', 'text',
                         st.name, '', '') +
             _stageField(_T('stage_days', 'Days'), 'days', 'number',
                         st.days, _T('until_end', 'until the end'),
                         _T('stage_days_note', '')) +
             // 적산온도는 기준온도(광합성 파라미터)와 짝이라 식생에서만 뜻이
             // 있다. 축사 단계에 GDD 칸이 있으면 무엇을 적어야 할지 알 수 없다.
             (_isVeg()
               ? _stageField(_T('stage_gdd', 'GDD'), 'gdd', 'number',
                             st.gdd, _T('by_days', 'by days'), '')
               : '') +
             // **지침이 단계의 주인공이다.** AI 가 일반 조언보다 이것을 우선하고
             // (tool_registry), **AI 를 쓰지 않아도** 지도에서 그 구획을 누르면
             // 사람이 읽는다(`aot-map-popup.js` 의 `.aot-ov-guidance`).
             _wideRow(_T('guidance', 'Guidance'), _T('guidance_note', ''),
                      '<textarea class="form-control aot-modern-input veg-guidance" ' +
                        'rows="4" data-guidance placeholder="' +
                        _esc(_T('guidance_ph', '')) + '">' +
                        _esc(st.guidance || '') + '</textarea>') +
             // 목표·자원은 "단계마다 다르게" 를 켰을 때만 나온다(`_applyPerStage`).
             '<div class="veg-stage-targets-block" hidden>' +
               '<div class="veg-stage-sub">' +
                 _esc(_T('stage_targets', 'Different in this stage')) + '</div>' +
               _targetInputs(st.targets) +
             '</div>' +
             (res ? '<div class="veg-stage-res-block" hidden>' +
                      '<div class="veg-stage-sub">' +
                        _esc(_T('resources', 'Resources')) + '</div>' + res +
                    '</div>' : '') +
             // 식별 코드는 **사람에게 물을 것이 아니다** — 비워 두면 이름에서
             // 만든다(`collect`). 그래도 칸을 남기는 이유는 이미 쓰이고 있는
             // 단계의 코드를 갈면 그동안 기록된 이력과의 연결이 끊기기 때문이다.
             '<details class="aot-prog-adv"><summary>' +
               _esc(_T('stage_key', 'Stage code')) + '</summary>' +
               '<div class="aot-modal-body-text veg-adv-note">' +
                 _esc(_T('stage_key_note', '')) + '</div>' +
               '<input type="text" class="form-control aot-modern-input" ' +
                 'data-sf="key" value="' + _esc(st.key || '') + '">' +
             '</details>' +
             // 순서는 **트랙에서 끌어** 바꾼다 — 버튼을 여기 두면 같은 일을
             // 하는 수단이 둘이 된다. 삭제만 남긴다.
             '<div class="aot-ov-desc-actions">' +
               '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
                 'data-act="stage-del">' +
                 _esc(_T('stage_delete', 'Delete this stage')) + '</button>' +
             '</div>' +
           '</div>';
  }

  /** 지금 패널의 값을 `State.stages[cur]` 에 넣는다 — **정본은 그 배열이다.** */
  function _readStagePanel(host) {
    var st = (State.stages || [])[State.curStage];
    var panel = host && host.querySelector('[data-stage-panel]');
    if (!st || !panel) return;
    panel.querySelectorAll('[data-sf]').forEach(function (el) {
      st[el.getAttribute('data-sf')] = (el.value || '').trim();
    });
    // 지침은 **빈 문자열도 담는다** — 지운 것을 반영해야 한다.
    var g = panel.querySelector('[data-guidance]');
    if (g) st.guidance = g.value || '';
    var t = {};
    panel.querySelectorAll('[data-tf]').forEach(function (el) {
      var v = (el.value || '').trim();
      // 빈 칸은 담지 않는다 — 0 과 미지정을 구분해야 한다.
      if (v !== '') t[el.getAttribute('data-tf')] = v;
    });
    st.targets = t;
    var base = {};
    (State.resourceDefs || []).forEach(function (d) {
      if (d && d.role) base[d.role] = (d.default !== false);
    });
    var r = {};
    panel.querySelectorAll('[data-rf]').forEach(function (el) {
      var role = el.getAttribute('data-rf');
      // 기본값과 같은 값은 담지 않는다 — 담으면 모든 단계가 덮어쓴 상태가 되어,
      // 나중에 프로그램 기본값을 바꿔도 단계들이 옛 값을 붙들고 있게 된다.
      if (el.checked !== base[role]) r[role] = el.checked;
    });
    st.resources = r;
  }

  /** 트랙과 패널을 함께 다시 그린다. */
  function _redrawStages(host) {
    if (!host) return;
    _refreshTrack(host);
    var box = host.querySelector('.veg-stage-panel-host');
    if (box) box.innerHTML = _stagePanel();
    _applyPerStage(host);
  }

  /**
   * "단계마다 다르게" 스위치를 화면에 반영한다.
   *
   * 끈 상태에서는 그 블록을 아예 내리고 **저장할 때도 보내지 않는다**
   * (`collect`) — 화면에서만 감추면 "안 쓰기로 했는데 값이 남아 있는" 상태가
   * 되어, 다음에 켜는 순간 잊고 있던 값이 되살아난다.
   */
  function _applyPerStage(host) {
    if (!host) return;
    host.querySelectorAll('.veg-stage-targets-block').forEach(function (el) {
      el.hidden = !State.perStageTargets;
    });
    host.querySelectorAll('.veg-stage-res-block').forEach(function (el) {
      el.hidden = !State.perStageRes;
    });
    // 켜 둔 역할이 하나도 없으면 단계에서 끄고 말고 할 것이 없다 — 그 스위치를
    // 남겨 두면 켜도 아무 일이 안 일어나는 죽은 토글이 된다.
    var perRes = host.querySelector('[data-per-res]');
    if (perRes) {
      var row = perRes.closest('.aot-modal-option-row');
      if (row) row.hidden = !host.querySelector('[data-rdef]:checked');
    }
  }

  /** 단계의 한 줄 = 설정 하나. 위쪽 기본 정보와 **같은 골격**을 쓴다. */
  function _stageField(label, field, type, value, placeholder, note) {
    var attrs = (type === 'number') ? ' min="1" step="any"' : '';
    return _optRow(label, note || '',
      '<input type="' + type + '"' + attrs +
        ' class="form-control aot-modern-input" data-sf="' + field + '"' +
        ' placeholder="' + _esc(placeholder || '') + '"' +
        ' value="' + _esc(value == null ? '' : String(value)) + '">');
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
    // 카드 목록의 "지금 열려있는 카드" 하이라이트는 공유 드로어 스크립트
    // (aot-widget-drawer.js)가 Bootstrap 의 `show.bs.modal` 이벤트에서만
    // 갱신한다. 이미 열려 있는 드로어에 `.modal('show')`를 다시 불러도
    // Bootstrap 은 그 이벤트를 다시 내지 않는다 — 그래서 드로어 안 내용은
    // 새 카드로 바뀌는데 목록의 하이라이트만 이전 카드에 남는다. 이 파일이
    // 정확히 그런 "카드마다 모달을 새로 만들지 않고 하나를 공유하는" 페이지라,
    // aot-widget-drawer.js 가 이 경우를 위해 미리 열어 둔 API 를 직접 부른다.
    if (window.AoTWidgetDrawer) window.AoTWidgetDrawer.activateByUid(uuid);

    fetch('/api/geo/program/' + encodeURIComponent(uuid),
          { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        // **응답 순서는 요청 순서와 다를 수 있다.** 카드를 빠르게 연달아
        // 열면(예: 1번 드로어가 아직 로딩 중일 때 2번을 클릭) 늦게 보낸
        // 요청이 먼저 도착할 수 있고, 그러면 이 콜백이 나중에 실행돼 방금
        // 연 카드의 화면을 예전 카드 내용으로 덮어쓴다 — 드로어는 열리는데
        // 카드가 안 바뀐 것처럼 보이는 버그가 바로 이것이었다. 이 요청을
        // 보낸 뒤로 다른 카드가 열렸으면(State.openId 가 이 uuid 와 다르면)
        // 이 응답은 이제 화면과 무관하니 버린다.
        if (State.openId !== uuid) return;
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
            // 종류를 바꿔 다시 그릴 때 **사람이 방금 적은 것이 이긴다.**
            // `notes`(의도)를 빠뜨리면 자기 말로 길게 적어 둔 것이 종류 하나
            // 바꾸는 순간 통째로 날아간다 — 저장 전이라 되돌릴 수단도 없다.
            ['name', 'subject', 'variety', 'notes'].forEach(function (k) {
              if (pending[k] != null) p[k] = pending[k];
            });
            if (pending.stages && pending.stages.length) p.stages = pending.stages;
            if (pending.target_defs) p.target_defs = pending.target_defs;
            if (pending.resource_defs) p.resource_defs = pending.resource_defs;
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
        // 자원 역할 정의(P6). 단계 화면이 이것을 보고 칸을 낸다 — **읽는 것보다
        // 먼저 세운다**(위 `_kindNow` 와 같은 이유: 뒤에 두면 이번 렌더가 직전
        // 프로그램의 역할로 그려진다).
        State.resourceDefs = (p.resource_defs || []).map(function (d) { return d; });

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

        // 단계는 **여기서 State 로 옮긴다** — 화면에는 고른 하나만 그리므로
        // DOM 을 정본으로 둘 수 없다. 사본을 만든다(서버 응답을 그대로 고치면
        // 취소하고 다시 열었을 때 옛 값이 남는다).
        State.stages = (p.stages || []).map(function (st) {
          var c = {};
          Object.keys(st || {}).forEach(function (k) { c[k] = st[k]; });
          return c;
        });
        State.curStage = 0;

        // 어느 항목이 **단계에서 실제로 쓰이는가** — 사용 토글의 초기 상태가
        // 이것을 본다. 값도 없고 아무 단계도 안 쓰는 항목을 켜 둘 이유가 없다.
        var usedKeys = {};
        State.stages.forEach(function (st) {
          Object.keys((st && st.targets) || {}).forEach(function (k) {
            usedKeys[k] = 1;
          });
        });
        State.defs.forEach(function (d) { d._used = !!usedKeys[d.key]; });

        // 단계마다 다르게 정하는가 — **화면 전용 상태**다(저장하지 않는다).
        // 실제로 다른 값이 하나라도 있으면 켜진 채로 시작한다.
        State.perStageTargets = Object.keys(usedKeys).length > 0;
        State.perStageRes = State.stages.some(function (st) {
          return st && st.resources && Object.keys(st.resources).length > 0;
        });

        var _row = function (label, note, field, value) {
          return _optRow(label, note,
            '<input type="text" class="form-control aot-modern-input" ' +
            'data-pf="' + field + '" value="' + _esc(value || '') + '"' +
            (ro ? ' disabled' : '') + '>');
        };

        // ── 1. 기본 ────────────────────────────────────────────────────
        // **품목(`subject`)·근거(`source_note`)는 여기서 묻지 않는다.** 품목은
        // 만들 때 정해지고(템플릿이면 그 대상, 빈 프로그램이면 이름) 뒤에 바꿀
        // 일이 없는데, 화면에 두면 "이름과 무엇이 다른가" 를 설명해야 하는 칸이
        // 하나 더 생긴다. 근거는 고칠 수 없는 값이라 칸처럼 두면 "여기서 뭘
        // 하라는 거지" 가 된다. 값은 그대로 유지된다(보내지 않으면 서버가 지킨다).
        //
        // 설명(`notes`)은 서버가 예전부터 받아 왔는데 **화면에만 없었다.**
        var intentRow = _wideRow(
          _T('intent', 'Description'), _T('intent_note', ''),
          '<textarea class="form-control aot-modern-input veg-intent" rows="3" ' +
            'data-pf-notes placeholder="' + _esc(_T('intent_ph', '')) + '"' +
            (ro ? ' disabled' : '') + '>' + _esc(p.notes || '') + '</textarea>');

        var gBasic =
          _group(_T('g_basic', 'Basics'), _T('g_basic_note', '')) +
          _box(_row(_T('name', 'Name'), '', 'name', p.name) +
               _row(_varietyLabel(p), '', 'variety', p.variety) +
               _tabRow(p) +
               _kindRow(p, ro) +
               intentRow);

        // ── 2. 단계 ────────────────────────────────────────────────────
        // 자동 승인(P7). **기본은 꺼짐** — 켜져 있는 것이 기본이면 사람이 아무
        // 결정도 하지 않았는데 단계가 스스로 넘어간다. 단계 목록과는 다른
        // 결정(언제 넘길지)이라 상자를 따로 둔다.
        var autoRow = _optRow(
          _T('auto_advance', 'Advance stages automatically'),
          _T('auto_advance_note', ''),
          _toggle('data-auto="1"', !!p.auto_advance, ro));

        // 단계 추가는 **트랙과 패널 사이의 한 행**이다.
        var actions = ro ? ''
          : '<div class="veg-stage-add-row aot-ov-desc-actions">' +
            '<button type="button" class="btn aot-pill-btn" data-act="stage-add">' +
            _esc(_T('add_stage', 'Add stage')) + '</button></div>';

        var gStages =
          _group(_T('stages', 'Program stages'), _T('stages_note', '')) +
          _box(autoRow) +
          _box('<div class="veg-track-host">' + _trackHtml() + '</div>' +
               actions +
               '<div class="veg-stage-panel-host">' + _stagePanel() + '</div>');

        // ── 3. 목표 ────────────────────────────────────────────────────
        // 설명은 상자 **밖**, 제목 바로 아래다. "단계마다 다른 값" 은 이름만으로
        // 뜻이 서므로 설명을 줄로 내지 않고 **툴팁**으로 붙인다(마지막 인자).
        var perTargetRow = ro ? '' : _optRow(
          _T('per_stage_targets', 'Use different values per stage'),
          _T('per_stage_targets_note', ''),
          _toggle('data-per-targets="1"', State.perStageTargets, false),
          '', true);
        var gTargets =
          _group(_T('g_targets', 'Targets'), _T('target_items_note', '')) +
          (perTargetRow ? _box(perTargetRow) : '') +
          _box('<div class="veg-defs">' + _targetDefsSection(ro) + '</div>');

        // ── 4. 자원 ────────────────────────────────────────────────────
        // 자원 역할은 **프로그램 레벨**이다. 단계는 그 선언을 켜고 끄기만 하는데,
        // 그 칸을 늘 내면 "여기서도 켜야 하나" 로 읽힌다 — 쓸 때만 낸다.
        var perResRow = ro ? '' : _optRow(
          _T('per_stage_res', 'Different per stage'),
          _T('per_stage_res_note', ''),
          _toggle('data-per-res="1"', State.perStageRes, false),
          '', true);
        var gRes =
          _group(_T('resources', 'Resources'), _T('resources_note_v2', '')) +
          _box('<div class="veg-resdefs">' + _resourceDefsSection(ro) + '</div>' +
               perResRow);

        // ── 5. 고급 ────────────────────────────────────────────────────
        // **여기 있는 것은 하나도 필요하지 않다.** 적산 기준온도·광합성 상수·
        // 목표 곡선은 전부 아는 사람만 쓰는 값인데, 예전에는 아는 칸들 사이에
        // 섞여 있어 모르는 칸 하나가 화면 전체를 못 믿게 만들었다.
        //
        // 기준온도는 비우면 단계가 날짜로 넘어간다 — **지어내지 않는다**(작물
        // 마다 다르고, 틀리면 적산이 통째로 어긋나는데 에러가 나지 않는다).
        // `photosynthesis.T_base` 로 저장한다: 그 JSON 이 이미 "FunctionCropPreset
        // 과 같은 키" 라는 계약을 갖고 있고 거기에 T_base 가 있다 — 새 키를
        // 만들면 같은 값이 두 이름을 갖는다.
        var tBase = (p.photosynthesis || {}).T_base;
        var tBaseRow0 = _optRow(
          _T('t_base', 'Heat unit base temperature'), _T('gdd_note', ''),
          '<input type="number" step="any" class="form-control aot-modern-input" ' +
            'data-tbase="1" placeholder="' +
            _esc(_T('by_days', 'by days')) + '" value="' +
            (tBase == null ? '' : _esc(String(tBase))) + '"' +
            (ro ? ' disabled' : '') + '>');

        // 광합성 모델 상수. **각 상수에 무엇을 뜻하는 수인지 한 줄씩 붙인다** —
        // 이름과 단위만 있으면(예전 상태) 값을 넣어야 할지 말지 판단할 근거가
        // 없다. 여기 있는 이유는 이것이 작물 지식이기 때문이다.
        var photoRows = _PHOTO_FIELDS.map(function (f) {
          var v = (p.photosynthesis || {})[f.key];
          return _optRow(_T(f.tkey, f.label),
            [_T(f.tkey + '_note', ''), f.unit].filter(Boolean).join(' \u00b7 '),
            '<input type="number" step="any" class="form-control aot-modern-input" ' +
              'data-photo="' + f.key + '" value="' +
              (v == null ? '' : _esc(String(v))) + '"' +
              (ro ? ' disabled' : '') + '>');
        }).join('');
        var photoBlock0 =
          '<details class="aot-prog-adv"><summary>' +
            _esc(_T('photo_model', 'Photosynthesis model')) + '</summary>' +
          '<div class="aot-modal-body-text veg-adv-note">' +
            _esc(_T('photo_note', '')) + '</div>' + photoRows + '</details>';

        // 기준온도·적산온도·광합성 모델은 **식물 개념**이다. 종류가 식생이
        // 아니면 아예 내지 않는다 — 축사 프로그램에서 "광합성 지수" 를 본
        // 사람은 무엇을 적어야 할지 알 수 없고, 알 수 없는 칸이 하나 있으면
        // 화면 전체를 못 믿게 된다.
        var vegOnly = _isVeg() ? (tBaseRow0 + photoBlock0) : '';
        // 목표 곡선도 고급이다 — 고를 Method 가 있어야 뜻이 있고(없으면 아예
        // 안 뜬다), "곡선이 있으면 단계 값을 이긴다" 는 규칙을 아는 사람만 쓴다.
        var curves = _curveSection(p, ro);
        var advInner = vegOnly + curves;
        var gAdvanced = advInner
          ? (_group(_T('g_advanced', 'Advanced settings'),
                    _T('g_advanced_note', '')) + _box(advInner))
          : '';

        var roNote = ro
          ? '<div class="aot-modal-body-text aot-prog-ro">' +
            _esc(_T('read_only', 'Built-in programs are read-only. Copy it.')) +
            '</div>'
          : '';

        host.innerHTML = roNote + gBasic + gStages + gTargets + gRes + gAdvanced;
        _applyPerStage(host);
      });
  }

  /**
   * 품목(`subject`)은 **드로어에서 묻지 않는다**(2026-08-21).
   *
   * 만들 때 정해진다 — 템플릿이면 그 대상, 빈 프로그램이면 이름과 같게. 값은
   * 그대로 유지된다: `collect` 가 보내지 않으면 서버가 기존 값을 지킨다(부분
   * 저장). 바꿔야 할 일이 생기면 AI 도구(`modify_program`)가 있다.
   */

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
      // 무엇을 말하는 줄인지 **행 안에서** 끝낸다.
      var meta = [d.unit,
                  d.measurement ? _T('measured', 'sensor-linked')
                                : _T('no_measurement', 'Reference target only')]
        .filter(Boolean).join(' \u00b7 ');
      var dval = (d['default'] == null) ? '' : d['default'];
      // **값도 없고 어느 단계에서도 안 쓰는 항목은 꺼진 채로 보인다.** 여섯
      // 항목이 값 없이 전부 켜져 있으면 "무엇을 하겠다는 것인지" 를 알 수 없다.
      var on = !d.hidden && (d['default'] != null || !!d._used);
      var valBox = '<input type="number" step="any" ' +
        'class="form-control aot-modern-input veg-def-val" ' +
        'data-def-val="' + _esc(d.key) + '" value="' + _esc(String(dval)) + '" ' +
        'aria-label="' + _esc(d.label || d.key) + '" ' +
        'placeholder="' + _esc(_T('unset', 'no target')) + '"' +
        (ro ? ' disabled' : '') + '>';

      // 고정 항목은 지우지 못하고 **끈다.** 예전에는 "숨기기" 체크박스였는데
      // 이중부정(체크하면 안 쓴다)이라 한 번 멈춰 읽어야 했다. 저장할 때 뜻을
      // 되돌린다(`hidden = !checked`).
      var right = d.fixed
        ? _toggle('data-def-use="' + _esc(d.key) + '"', on, ro)
        : (ro ? '' :
           '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm" ' +
           'data-act="def-del" data-key="' + _esc(d.key) + '">' +
           _esc(_T('del', 'Delete')) + '</button>');
      return '<div class="aot-modal-option-row veg-row veg-def-row' +
               (on ? '' : ' is-hidden') + '" data-def-i="' + i + '">' +
               '<div class="aot-modal-option-label">' +
                 _esc(d.label || d.key) + '</div>' +
               '<div class="aot-modal-option-control veg-def-ctl">' +
                 valBox + right + '</div>' +
               (meta ? '<div class="aot-modal-body-text veg-row-note">' +
                       _esc(meta) + '</div>' : '') +
             '</div>';
    }).join('');

    var adder = '';
    if (!ro) {
      // **자주 쓰는 것을 앞에 둔다.** 97개를 이름순으로만 늘어놓으면 실제로
      // 쓰는 대여섯 개를 찾는 데 목록을 다 훑어야 한다.
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

      // **1행 [제목][추가 버튼] · 2행 설명 · 3행 입력 셋.** 예전에는 제목도
      // 설명도 없이 칸 셋이 목록 아래에 갑자기 나타나, 위 항목들과 무엇이
      // 다른지 눌러 보기 전에는 알 수 없었다.
      //
      // 이름·단위는 **측정 종류를 고르면 따라온다**(`def-meas` 핸들러) — 셋을
      // 다 손으로 적게 하면 항목 하나 만드는 품이 커서 아무도 안 만든다.
      adder = '<div class="veg-def-adder">' +
        _optRow(_T('add_item_title', 'Add your own item'),
                _T('add_item_note', ''),
                '<button type="button" class="btn aot-pill-btn" data-act="def-add">' +
                  _esc(_T('add_item', 'Add item')) + '</button>') +
        '<div class="veg-def-add">' +
          '<select class="form-control aot-modern-input" data-def-new="measurement">' +
            opts + '</select>' +
          '<input type="text" class="form-control aot-modern-input" data-def-new="label" ' +
            'placeholder="' + _esc(_T('item_name', 'Item name')) + '">' +
          '<input type="text" class="form-control aot-modern-input" data-def-new="unit" ' +
            'placeholder="' + _esc(_T('item_unit', 'Unit')) + '">' +
        '</div></div>';
    }

    return rows + adder;
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
      // **한 줄에 하나.** 예전에는 3열 격자라 좁은 폭에서 라벨과 칸이 어긋났다.
      return _optRow(d.label || d.key, '',
        '<select class="form-control aot-modern-input" data-cf="' + _esc(d.key) + '"' +
          (ro ? ' disabled' : '') + '>' + opts + '</select>');
    }).join('');
    // 제목·설명을 **라벨 열 안에** 넣지 않는다. 공용 option-row 의 라벨 열은
    // 좁아서(폰에서 ~10자) "곡선을 연결하면 그 / 항목은 단계 값 대신" 처럼
    // 끊긴다. 단계 상세와 같은 골격 — 제목 줄, 설명 줄, 그리고 격자.
    return '<div class="veg-curves">' +
           '<div class="veg-stage-sub">' + _esc(_T('curves', 'Target curves')) +
           '</div>' +
           '<div class="aot-modal-body-text veg-adv-note">' +
             _esc(_T('curves_note',
                     'A curve overrides the stage value for that item. ' +
                     'Time runs from the start date.')) +
           '</div>' + rows + '</div>';
  }

  /**
   * 항목 정의 섹션과 지금 단계의 목표 칸을 다시 그린다.
   *
   * **이미 입력된 값을 보존한다** — 항목 하나를 더했다고 사람이 적어 둔 단계
   * 값이 사라지면 그건 저장 전에 데이터를 잃는 것이다. 화면의 값을 먼저
   * `State.stages` 로 읽어 넣고, 새로 그린 칸에 그것을 되돌려 놓는다.
   */
  function _redrawDefs(drawer) {
    _readStagePanel(drawer);

    // 사용 토글의 초기 상태가 `_used`(어느 단계에서 쓰이는가)를 보므로, 다시
    // 그리기 전에 **지금 값**으로 그것을 갱신한다. 안 하면 방금 적은 단계 값이
    // 있는데도 항목이 꺼진 채로 그려진다.
    var used = {};
    (State.stages || []).forEach(function (st) {
      Object.keys((st && st.targets) || {}).forEach(function (k) { used[k] = 1; });
    });
    (State.defs || []).forEach(function (d) { d._used = !!used[d.key]; });

    var box = drawer.querySelector('.veg-defs');
    if (box) box.innerHTML = _targetDefsSection(false);
    _redrawStages(drawer);
  }

  /**
   * 단계의 자원 칸을 다시 그린다 — 프로그램 레벨에서 역할을 켜고 끈 뒤.
   * 예전에는 저장하고 다시 열어야 나타나서, 방금 켠 관수를 단계에서 끄려면
   * 한 번 저장하고 돌아와야 했다.
   */
  function _redrawStageResources(host) {
    _readStagePanel(host);
    _redrawStages(host);
  }

  /**
   * 사람이 적은 이름 → 서버가 받는 키(소문자로 시작하는 영문·숫자·밑줄).
   *
   * 한글 이름은 규칙에 맞는 글자가 하나도 안 남으므로 순번으로 떨어진다 —
   * 그것으로 충분하다. 이 값은 **화면에 안 나오고** 단계 이력을 잇는 데만
   * 쓰인다(사람이 읽을 이름은 `name` 이 따로 있다).
   *
   * `taken` 에 이미 있는 키는 뒤에 숫자를 붙여 피한다.
   */
  function _keyFrom(name, done, taken) {
    var base = String(name || '').toLowerCase()
      .replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 32);
    if (!/^[a-z]/.test(base)) base = 'stage_' + ((done || []).length + 1);
    var k = base, n = 2;
    while (taken && taken[k]) { k = base + '_' + n; n += 1; }
    return k;
  }

  function collect(host) {
    var out = { stages: [] };
    host.querySelectorAll('[data-pf]').forEach(function (el) {
      out[el.getAttribute('data-pf')] = (el.value || '').trim() || null;
    });
    // 품목 칸은 화면에 없다 — 값이 실려 올 일이 없지만, 예전 마크업이 남은
    // 화면에서 빈 값이 실려 기존 값을 지우는 일이 없도록 **빈 값은 뺀다.**
    // 부분 저장 규칙상 키가 없으면 서버가 기존 값을 지킨다.
    if (!out.subject) delete out.subject;

    // 의도(`notes`) — **빈 문자열도 보낸다**(지침과 같은 규율). 지운 것을
    // 반영해야 하고, "미지정" 과 "빈 글" 을 구분할 이유가 없다. `data-pf` 를
    // 쓰지 않는 이유는 그쪽이 `.value` 를 그대로 trim 해 빈 값을 null 로
    // 바꿔 보내기 때문이다 — 그러면 서버가 "변경 없음" 으로 읽는다.
    var nt = host.querySelector('[data-pf-notes]');
    if (nt) out.notes = nt.value || '';

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
      // 화면은 **"사용"** 으로 묻고 저장은 `hidden` 으로 한다 — 뜻이 반대다.
      // 이중부정("숨기기" 체크박스)을 화면에서 걷어낸 대가로 여기서 한 번
      // 뒤집는다. 저장 어휘를 바꾸지 않는 이유는 `hidden` 이 서버·AI·구획
      // 모달이 이미 쓰는 말이기 때문이다.
      var hides = {};
      host.querySelectorAll('[data-def-use]').forEach(function (el) {
        hides[el.getAttribute('data-def-use')] = !el.checked;
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

    // 자원 역할 정의(프로그램 레벨). 체크된 역할만 담는다 — 안 쓰는 역할을
    // `default: false` 로 남겨 두면 단계 화면에 계속 칸이 나온다.
    var rdefs = [];
    host.querySelectorAll('[data-rdef]').forEach(function (el) {
      if (el.checked) rdefs.push({ role: el.getAttribute('data-rdef'),
                                   'default': true });
    });
    out.resource_defs = rdefs;

    // 자동 생성한 코드가 **이미 쓰인 코드와 겹치지 않게** 한다 — 사람이 앞
    // 단계에 손으로 `stage_2` 를 적어 둔 채 뒤 단계를 한글 이름으로 두면
    // 순번만으로는 부딪친다. 서버는 단계 키 중복을 막지 않으므로(목표 항목과
    // 달리) 여기서 피한다.
    var seenKeys = {};
    // 단계는 **`State.stages` 가 정본이다**(화면에는 고른 하나만 있다).
    // 지금 패널을 먼저 읽어 넣은 뒤 그 배열에서 만든다 — 이 순서를 놓치면
    // 마지막으로 고친 단계가 저장에서 빠진다.
    _readStagePanel(host);
    var seenKeys = {};
    (State.stages || []).forEach(function (src) {
      if (src && src.key) seenKeys[src.key] = 1;
    });
    (State.stages || []).forEach(function (src) {
      var st = {};
      ['key', 'name', 'days', 'gdd'].forEach(function (k) {
        if (src[k] != null) st[k] = src[k];
      });
      // 기간을 비우면 "끝까지" 다 — 서버가 마지막 자리에서만 허용한다.
      st.days = (st.days === '' || st.days == null) ? null : st.days;
      // 적산온도는 비우면 **키를 보내지 않는다.** null 로 보내면 "0" 과
      // "미지정" 이 구분되지 않는다(목표값과 같은 규율).
      if (st.gdd === '' || st.gdd == null) delete st.gdd;
      // 식별 코드는 **사람에게 묻지 않는다** — 비어 있으면 이름에서 만든다.
      // 서버는 `key` 를 필수로 보므로 여기서 채워 주지 않으면 거절된다.
      if (!st.key) {
        st.key = _keyFrom(st.name, out.stages, seenKeys);
        seenKeys[st.key] = 1;
      }
      // "단계마다 다르게" 가 꺼져 있으면 **아무것도 보내지 않는다** = 지운다.
      // 화면에서만 감추면 다음에 켜는 순간 잊고 있던 값이 되살아난다.
      if (State.perStageTargets !== false &&
          src.targets && Object.keys(src.targets).length) {
        st.targets = src.targets;
      }
      if (State.perStageRes !== false &&
          src.resources && Object.keys(src.resources).length) {
        st.resources = src.resources;
      }
      // 지침은 **빈 문자열도 보낸다** — 지운 것을 반영해야 한다.
      if (src.guidance != null) st.guidance = src.guidance;
      // 이후 단계가 쓸 필드는 그대로 보존한다(모르는 키를 버리지 않는다).
      ['tasks', 'functions'].forEach(function (k) {
        if (src[k] != null) st[k] = src[k];
      });
      if (st.key || st.name) out.stages.push(st);
    });
    return out;
  }

  // ── 배선 ──────────────────────────────────────────────────────────────
  function wire() {
    var searchBox = document.getElementById('veg-search');
    if (searchBox) searchBox.addEventListener('input', function () {
      State.searchQuery = searchBox.value || '';
      renderList();
    });

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
      // 지금 보고 있는 탭에 만든다 — 새로 만든 프로그램이 다른 탭에 가서
      // "방금 만들었는데 안 보인다" 가 되지 않게.
      if (base.indexOf('tpl:') === 0) {
        _api('POST', '/api/geo/program',
             { template_key: base.slice(4), tab_id: State.activeTabId }).then(done);
      } else if (base) {
        _api('POST', '/api/geo/program/' + encodeURIComponent(base) + '/clone',
             { tab_id: State.activeTabId }).then(done);
      } else {
        // 빈 프로그램도 단계 하나는 있어야 저장된다(서버 규칙) — 그 하나를
        // 채워서 만든다. 빈 목록을 주고 오류를 보이는 것보다 낫다.
        //
        // **종류는 여기서 안 묻는다.** 추가 줄에 별도 "종류" 선택지를 뒀던
        // 적이 있는데, "선택" 드롭다운 옆에 있어 그 목록을 거르는 필터처럼
        // 보였지만 실제로는 아무것도 거르지 않고 빈 프로그램에만 적용돼
        // "뭘 골라도 반영이 안 되는 죽은 선택지"로 읽혔다(사용자 지적).
        // 기본값 vegetation 으로 만들고, 다른 종류가 필요하면 추가 직후
        // 자동으로 열리는 드로어의 "종류" 칸(`_kindRow`)에서 바꾼다 —
        // 컨트롤 하나가 줄고, 실제로 바뀌는 자리에서만 고르게 된다.
        // 품목은 **이름과 같게** 만든다. 화면에서 묻지 않는 값이라 무언가
        // 채워야 하는데, 'unnamed' 같은 자리표시자를 넣으면 그 뒤로 아무도
        // 고칠 수 없는 이상한 값이 목록·AI 조회에 남는다.
        _api('POST', '/api/geo/program', {
          name: _T('new_program', 'New program'),
          subject: _T('new_program', 'New program'),
          stages: [{ key: 'stage_1', name: _T('stage_name', 'Stage'), days: null }],
          tab_id: State.activeTabId
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
    // 드로어 푸터(삭제·복제)는 `#veg-list` 의 자손이 아니라 형제다(`<main>`
    // 이후에 별도로 뜨는 모달) — 위임을 목록에만 걸면 버블링이 안 닿아 클릭이
    // 조용히 무반응이 된다. 같은 핸들러를 `#veg-drawer` 에도 건다: 아래
    // 분기가 처리하지 않는 act(stage-add 등, `#veg-drawer-body` 전용)는
    // 그대로 지나치므로 겹쳐 걸어도 안전하다.
    var listActHandler = function (e) {
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
        _api('POST', '/api/geo/program/' + encodeURIComponent(uuid) + '/clone',
             { tab_id: State.activeTabId })
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
    };
    if (list) list.addEventListener('click', listActHandler);
    var drawerEl0 = document.getElementById('veg-drawer');
    if (drawerEl0) drawerEl0.addEventListener('click', listActHandler);

    var drawerBody = document.getElementById('veg-drawer-body');
    if (drawerBody) drawerBody.addEventListener('change', function (e) {
      var el = e.target;
      if (!el) return;
      // 탭 이동 — 메인 저장 버튼과 분리된 자체 요청(위 _tabRow 주석 참조).
      // 읽기 전용(내장·외부) 프로그램도 이 경로로는 이동할 수 있다.
      if (el.id === 'veg-tab-move') {
        var uid = State.openId;
        if (!uid) return;
        _api('POST', '/api/geo/program/' + encodeURIComponent(uid),
             { tab_id: el.value }).then(function (r) {
          if (r.status >= 400 || !r.data.ok) {
            _toast((r.data && r.data.message) || _T('save_failed', 'Save failed'), 'error');
            return;
          }
          _toast(_T('saved', 'Saved.'), 'success');
          load();
        });
        return;
      }
    });

    // 기간을 고치거나 이름을 고치면 기간 바가 **그 자리에서** 따라 움직인다.
    // 저장 뒤에 반영되면 그 막대는 "고치기 전 상태" 를 계속 보여 주는 셈이라
    // 오히려 사람을 헷갈리게 한다. `change` 가 아니라 `input` 인 이유도 같다.
    if (drawerBody) drawerBody.addEventListener('input', function (e) {
      var el = e.target;
      if (!el || !el.getAttribute) return;
      var f = el.getAttribute('data-sf');
      // 트랙의 폭과 숫자가 **그 자리에서** 따라온다. 저장 뒤에 반영되면 그
      // 막대는 "고치기 전 상태" 를 계속 보여 주는 셈이라 오히려 헷갈린다.
      if (f === 'days' || f === 'name') {
        _readStagePanel(drawerBody);
        _refreshTrack(drawerBody);
      }
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
      // "단계마다 다르게" — 끄면 그 블록을 내리고 저장에서도 뺀다. 값이 이미
      // 있으면 **지워진다는 것을 먼저 말한다**(끄는 것만으로 값이 조용히
      // 사라지면 다음에 켰을 때 왜 비었는지 알 수 없다).
      if (el && el.hasAttribute && el.hasAttribute('data-per-targets')) {
        if (!el.checked) {
          var hasVals = [].filter.call(drawerEl.querySelectorAll('[data-tf]'),
            function (x) { return (x.value || '').trim() !== ''; }).length;
          if (hasVals && !window.confirm(
                _T('per_stage_off_confirm',
                   'Stage values will be removed. Continue?')
                  .replace('{n}', String(hasVals)))) {
            el.checked = true;
            return;
          }
        }
        State.perStageTargets = !!el.checked;
        _applyPerStage(drawerEl);
        return;
      }
      if (el && el.hasAttribute && el.hasAttribute('data-per-res')) {
        State.perStageRes = !!el.checked;
        _applyPerStage(drawerEl);
        return;
      }
      // 프로그램 레벨에서 자원 역할을 켜고 끄면 **단계의 자원 칸도 그 자리에서
      // 따라온다.** 예전에는 저장하고 다시 열어야 나타나서, 방금 켠 관수를
      // 단계에서 끄려면 한 번 저장하고 돌아와야 했다.
      if (el && el.hasAttribute && el.hasAttribute('data-rdef')) {
        var roles = [];
        drawerEl.querySelectorAll('[data-rdef]').forEach(function (x) {
          if (x.checked) roles.push({ role: x.getAttribute('data-rdef'),
                                      'default': true });
        });
        State.resourceDefs = roles;
        _redrawStageResources(drawerEl);
        return;
      }
      // 단계에서 덮어쓸 항목을 고르면 그 자리에 칸이 생긴다.
      if (el && el.hasAttribute && el.hasAttribute('data-tf-add') && el.value) {
        var host = el.closest('.veg-stage-targets-block');
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
          host.innerHTML = '<div class="veg-stage-sub">' +
            _esc(_T('stage_targets', 'Different in this stage')) + '</div>' +
            _targetInputs(cur);
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
        // 새 단계는 **고른 단계 바로 뒤**에 들어간다 — 늘 맨 끝에만 붙으면
        // 중간을 둘로 나눌 때 끌어 옮기는 일이 한 번 더 생긴다.
        _readStagePanel(drawer);
        var at = Math.min(State.curStage + 1, State.stages.length);
        State.stages.splice(at, 0, { key: '', name: '', days: '' });
        State.curStage = at;
        _redrawStages(drawer);
        var nameEl = drawer.querySelector('[data-stage-panel] [data-sf="name"]');
        if (nameEl) nameEl.focus();
      } else if (act === 'stage-pick') {
        // 트랙의 구간이 곧 메뉴다. **떠나기 전에 지금 패널을 읽어 둔다** —
        // 안 그러면 방금 적은 것이 사라진다.
        var i = parseInt(btn.getAttribute('data-stage-i'), 10);
        if (isNaN(i) || i === State.curStage) return;
        _readStagePanel(drawer);
        State.curStage = i;
        _redrawStages(drawer);
      } else if (act === 'stage-del') {
        if (!State.stages.length) return;
        State.stages.splice(State.curStage, 1);
        if (!State.stages.length) State.stages.push({ key: '', name: '', days: '' });
        State.curStage = Math.max(0, Math.min(State.curStage,
                                              State.stages.length - 1));
        _redrawStages(drawer);
      }
    });

    // ── 트랙에서 끌어 순서 바꾸기 ────────────────────────────────────
    //
    // 순서가 곧 진행 순서다(서버는 배열 순서를 그대로 읽는다). 기간을 비운
    // "끝까지" 단계는 마지막에만 올 수 있는데, **화면에서 미리 막지 않는다** —
    // 막으면 왜 안 되는지 알 길이 없다. 저장할 때 서버가 거절하고 이유를 말한다.
    //
    // **HTML5 네이티브 DnD 를 쓰지 않는다.** 이 저장소가 이미 그렇게 정했다
    // (`widgets/AoT_facility/aot-actuator-order.js` 의 주석): 위젯 이동·팝업
    // 안에서 시작조차 안 되는 경우가 있고, 무엇보다 **터치에서 안 된다** —
    // 폰에서 순서를 못 바꾸면 그 기능은 절반만 있는 것이다.
    //
    // 구간 전체가 손잡이라 클릭(고르기)과 겹친다. 그래서 **움직인 거리**로
    // 가른다: 임계값을 넘기 전에는 아무것도 아니고, 넘으면 그때부터 끌기다.
    if (drawer) {
      var DRAG_SLOP = 6;          // px — 손가락은 가만히 있어도 이만큼 흔들린다
      var dg = null;              // {from, startX, moved}

      var _x = function (e) {
        return (e.touches && e.touches[0]) ? e.touches[0].clientX : e.clientX;
      };

      var _onMove = function (e) {
        if (!dg) return;
        if (!dg.moved) {
          if (Math.abs(_x(e) - dg.startX) < DRAG_SLOP) return;
          dg.moved = true;
          var el = drawer.querySelector(
            '.veg-track-seg[data-stage-i="' + dg.from + '"]');
          if (el) el.classList.add('is-dragging');
        }
        e.preventDefault();       // 끌기 시작 뒤에만 — 그 전에는 스크롤을 막지 않는다
        var x = _x(e);
        var segs = drawer.querySelectorAll('.veg-track-seg');
        for (var i = 0; i < segs.length; i++) {
          var r = segs[i].getBoundingClientRect();
          if (x >= r.left && x <= r.right) {
            var to = parseInt(segs[i].getAttribute('data-stage-i'), 10);
            if (!isNaN(to) && to !== dg.from) {
              // 옮기기 전에 지금 패널을 읽어 둔다 — 편집 중인 단계가 끌리는
              // 것일 수도, 그 자리를 내주는 것일 수도 있다.
              _readStagePanel(drawer);
              var moved = State.stages.splice(dg.from, 1)[0];
              State.stages.splice(to, 0, moved);
              // 보고 있던 단계를 계속 본다(자리는 바뀌었어도 같은 단계다).
              if (State.curStage === dg.from) State.curStage = to;
              else if (dg.from < State.curStage && to >= State.curStage) State.curStage -= 1;
              else if (dg.from > State.curStage && to <= State.curStage) State.curStage += 1;
              dg.from = to;
              _redrawStages(drawer);
              var el2 = drawer.querySelector(
                '.veg-track-seg[data-stage-i="' + to + '"]');
              if (el2) el2.classList.add('is-dragging');
            }
            break;
          }
        }
      };

      var _onUp = function () {
        document.removeEventListener('mousemove', _onMove, true);
        document.removeEventListener('mouseup', _onUp, true);
        document.removeEventListener('touchmove', _onMove, { capture: true });
        document.removeEventListener('touchend', _onUp, true);
        drawer.querySelectorAll('.veg-track-seg.is-dragging').forEach(function (x) {
          x.classList.remove('is-dragging');
        });
        // 움직이지 않았으면 클릭으로 남긴다 — `stage-pick` 이 그것을 받는다.
        dg = null;
      };

      var _onDown = function (e) {
        if (e.type === 'mousedown' && e.button !== 0) return;
        var seg = e.target.closest && e.target.closest('.veg-track-seg');
        if (!seg || !drawer.contains(seg)) return;
        var i = parseInt(seg.getAttribute('data-stage-i'), 10);
        if (isNaN(i)) return;
        dg = { from: i, startX: _x(e), moved: false };
        document.addEventListener('mousemove', _onMove, true);
        document.addEventListener('mouseup', _onUp, true);
        document.addEventListener('touchmove', _onMove,
                                  { passive: false, capture: true });
        document.addEventListener('touchend', _onUp, true);
      };

      drawer.addEventListener('mousedown', _onDown);
      drawer.addEventListener('touchstart', _onDown, { passive: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { wire(); load(); });
  } else {
    wire(); load();
  }
})();
