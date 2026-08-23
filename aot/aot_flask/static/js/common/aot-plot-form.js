/* 구획 등록·편집 폼 — **한 벌만 둔다.**
 *
 * 이 폼은 네 화면에 나온다:
 *
 *   geo/design 식생 모드 · geo/facility 식생 스텝 ·
 *   지도 위젯 시설 모달의 [구획 추가] · 지도 위젯 구획 모달의 편집
 *
 * 화면마다 각자 적고 있었고, 그래서 **필드 집합이 서로 달랐다.** 몫
 * (`allocation`, p6_50)은 지도 위젯 둘에만 있어서, 시설 편집기에서 만든 구획은
 * 몫이 빈 채로 남고 채우려면 다른 화면으로 옮겨 가야 했다 — 그런데 화면 어디에도
 * 그 사실이 적혀 있지 않다. 프로그램 선택은 반대로 시설 모달에만 없었다.
 *
 * 한 곳에서 필드를 정의하면 새 필드를 넣을 때 네 곳을 기억할 필요가 없다.
 * `aot-plot-labels.js` 가 라벨에 대해 이미 같은 판단을 했고, 이 파일은 그
 * 나머지(필드 목록·수집·배선)를 맡는다.
 *
 * ## 렌더까지 공유하는 이유
 *
 * 네 화면의 골격이 이미 같다 — `.aot-modal-option-row` + `.aot-modern-input`.
 * 그래서 "필드 정의만 공유하고 렌더는 각자" 로 두면 **같은 것을 네 번 적는
 * 상태가 그대로 남는다.** 다른 것은 필드 속성 이름뿐이라(`data-nf`/`data-f`/
 * `data-veg-field`) 그것만 `ctx.attr` 로 받는다.
 *
 * ## 화면이 정하는 것과 이 파일이 정하는 것
 *
 * | | 누가 |
 * |---|---|
 * | 어떤 필드가 있는가 · 순서 · 타입 | **이 파일** |
 * | 시설 구획인가 노지인가(`target`) | 화면 |
 * | 선택지(구역·프로그램·총량) | 화면이 `ctx` 로 넘긴다 |
 * | 저장 요청 · 성공 후 처리 | 화면 |
 *
 * 선택지를 이 파일이 조회하지 않는 것은 `aot-map-popup.js` 의 규약과 같다 —
 * 빌더는 순수 함수로 두고 조회는 화면이 맡는다(그쪽이 캐시를 갖고 있다).
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

  function _labels(kind) {
    // **기본값을 빠뜨리면 라벨이 'other' 로 떨어진다** — 종류를 아직 안 고른
    // 새 폼에서 "품목/품종" 대신 "대상/세부 구분" 이 뜬다(kind select 의
    // 기본값은 vegetation 인데 라벨만 중립어가 되어 서로 어긋난다).
    kind = kind || 'vegetation';
    var L = root.AoTPlotLabels;
    return {
      subject: L ? L.subject(kind) : _t('Item'),
      variety: L ? L.variety(kind) : _t('Variety')
    };
  }

  // 대상 종류 — `GeoProgram.kind` 와 같은 어휘. 여기서 한 벌만 갖는다.
  var KINDS = [
    ['vegetation', 'Vegetation'],
    ['livestock',  'Livestock'],
    ['facility',   'Facility'],
    ['other',      'Other']
  ];

  // 구역 총량의 단위 — 서버 어휘(`plot_context._CAPACITY_UNITS`)와 짝이다.
  function capUnitLabel(unit) {
    switch (unit) {
      case 'row':   return _t('rows');
      case 'tray':  return _t('trays');
      case 'area':  return _t('m²');
      case 'house': return _t('houses');
      default:      return _t('beds');
    }
  }

  /**
   * 필드 정본.
   *
   *   key     페이로드 키(= 필드 속성 값)
   *   type    text | date | color | kind | select | alloc
   *   label   문자열 또는 (ctx) => 문자열
   *   when    'facility' 면 시설 구획에서만 (구역·몫)
   *   opt     화면이 `ctx.include` 로 켜야 나오는 필드(이름·색)
   *   hint    칸 아래 한 줄 — 설계 화면 링크는 권한이 있을 때만 보인다
   */
  var FIELDS = [
    { key: 'bay_id', type: 'select', label: 'Zone', when: 'facility', group: 'where',
      hint: { text: 'Facility settings', href: '/geo/facility' } },
    { key: 'kind', type: 'kind', label: 'Kind', group: 'what' },
    { key: 'subject', type: 'text', group: 'what',
      label: function (ctx) { return _labels(ctx.kind).subject; } },
    { key: 'variety', type: 'text', group: 'what',
      label: function (ctx) { return _labels(ctx.kind).variety; } },
    { key: 'name', type: 'text', label: 'Plot name', opt: true, group: 'what' },
    { key: 'program_uuid', type: 'select', label: 'Program', group: 'program',
      hint: { text: 'Create a new program', href: '/geo/programs' } },
    { key: 'started_on', type: 'date', label: 'Start date', group: 'when' },
    { key: 'expected_end_on', type: 'date', label: 'Expected end', group: 'when' },
    // 몫은 **시설 구획에만** 있다. 노지 구획은 면적이 도형에서 나오므로 몫을
    // 적으면 정본이 둘이 되고, 서버(`plot_io._resolve_allocation`)가 거절한다.
    { key: 'allocation_value', type: 'alloc', label: 'Share', when: 'facility',
      group: 'where' },
    { key: 'color', type: 'color', label: 'Colour', opt: true, group: 'look' }
  ];

  // 그룹 제목 — `ctx.groups` 가 켜진 화면(모달이 큰 geo/design)만 쓴다.
  // 순서는 이 배열이 정한다.
  var GROUPS = [
    ['where',   'Where'],
    ['what',    'This plot'],
    ['program', 'Program'],
    ['when',    'Dates'],
    ['look',    'Appearance']
  ];

  function _row(label, control, extraClass) {
    return '<div class="aot-modal-option-row' +
           (extraClass ? ' ' + extraClass : '') + '">' +
           '<div class="aot-modal-option-label">' + label + '</div>' +
           '<div class="aot-modal-option-control">' + control + '</div></div>';
  }

  /** 칸 아래 한 줄 안내. 갈 수 없는 곳은 **아예 말하지 않는다.** */
  function _hint(h, ctx) {
    if (!h) return '';
    if (h.href && !ctx.canDesign) return '';
    var inner = _esc(_t(h.text));
    if (h.href) inner = '<a href="' + _esc(h.href) + '">' + inner + '</a>';
    return '<div class="aot-modal-option-row aot-ov-field-hint">' +
           '<div class="aot-modal-option-label"></div>' +
           '<div class="aot-modal-option-control">' + inner + '</div></div>';
  }

  // 총량이 없을 때만 뜬다(`wire` 가 토글). 미리 자리를 잡아 두는 이유는
  // 나중에 보일 때 레이아웃이 튀지 않게 하기 위해서다.
  function _allocHintHtml() {
    return '<div class="aot-modal-option-row aot-ov-field-hint ' +
           'aot-ov-alloc-hint" style="display:none">' +
           '<div class="aot-modal-option-label"></div>' +
           '<div class="aot-modal-option-control">' +
           _esc(_t('Set the bay capacity below to enter it as a count')) +
           '</div></div>';
  }

  function _visible(ctx) {
    var facility = ctx.target === 'facility';
    var include = ctx.include || [];
    return FIELDS.filter(function (f) {
      if (f.when === 'facility' && !facility) return false;
      if (f.opt && include.indexOf(f.key) < 0) return false;
      if (ctx.omit && ctx.omit.indexOf(f.key) >= 0) return false;
      return true;
    });
  }

  /**
   * 기존 값 꺼내기 — **응답의 모양과 폼의 키가 다른 둘**을 여기서 잇는다.
   *
   * 서버는 몫을 dict(`allocation: {amount|percent}`)로, 프로그램을 객체
   * (`program: {unique_id}`)로 내보낸다. 폼은 각각 `allocation_value` ·
   * `program_uuid` 라는 한 칸이다. 이 매핑이 없으면 **편집 폼이 빈 칸으로
   * 열리고**, 사람이 그대로 저장하면 적어 둔 값이 지워진다 — 에러 없이.
   */
  function _valueOf(f, ctx) {
    var v = ctx.values || {};
    if (f.key === 'allocation_value') {
      var a = v.allocation;
      if (!a || typeof a !== 'object') return '';
      return (a.amount != null) ? a.amount
           : (a.percent != null ? a.percent : '');
    }
    if (f.key === 'program_uuid') {
      return v.program_uuid || (v.program && v.program.unique_id) || '';
    }
    return v[f.key];
  }

  function _control(f, ctx) {
    var attr = ctx.attr || 'data-pf';
    var val = _valueOf(f, ctx);
    var a = attr + '="' + f.key + '"';

    if (f.type === 'kind') {
      var o = '';
      KINDS.forEach(function (k) {
        o += '<option value="' + k[0] + '"' +
             (k[0] === (ctx.kind || 'vegetation') ? ' selected' : '') + '>' +
             _esc(_t(k[1])) + '</option>';
      });
      return '<select class="aot-modern-input form-control" ' + a + '>' + o + '</select>';
    }

    if (f.key === 'bay_id') {
      // "시설 전체" 는 다동에서만 뜻이 있다(단동은 구역이 하나뿐이라 고를 것이
      // 없다). 서버가 단동을 실제 구역 id 로 정정하므로 값 자체는 안전하다.
      var bays = ctx.bays || [];
      var cur = val != null ? val : ctx.bayId;
      var s = '<option value=""' + (cur ? '' : ' selected') + '>' +
              _esc(_t('Whole facility')) + '</option>';
      bays.forEach(function (b) {
        s += '<option value="' + _esc(b.id) + '"' +
             (b.id === cur ? ' selected' : '') + '>' +
             _esc(b.name || b.id) + '</option>';
      });
      return '<select class="aot-modern-input form-control" ' + a + '>' + s + '</select>';
    }

    if (f.key === 'program_uuid') {
      // 선택지는 **비운 채로** 낸다 — 화면이 `wire()` 에서 채운다. 목록은
      // 종류에 따라 달라지고, 종류가 다른 프로그램을 붙이면 서버가 거절한다.
      var po = '<option value="">' + _esc(_t('No program')) + '</option>';
      (ctx.programs || []).forEach(function (p) {
        po += '<option value="' + _esc(p.unique_id) + '"' +
              (p.unique_id === val ? ' selected' : '') + '>' +
              _esc(p.name + (p.variety ? ' · ' + p.variety : '')) + '</option>';
      });
      return '<select class="aot-modern-input form-control" ' + a + '>' + po + '</select>';
    }

    if (f.type === 'alloc') {
      // 입력은 **숫자 하나**다. 그것이 수량인지 비율인지는 그 구역에 총량이
      // 적혀 있는지가 정하고, 접미 표시가 그 사실을 말한다(`wire` 가 갱신한다).
      return '<span class="aot-ov-alloc-input">' +
             '<input type="number" min="0" step="any" ' +
             'class="aot-modern-input form-control" ' + a +
             ' value="' + _esc(val == null ? '' : val) + '">' +
             '<span class="aot-ov-alloc-suffix"></span></span>';
    }

    var type = (f.type === 'color') ? 'color' : (f.type === 'date' ? 'date' : 'text');
    var v = val;
    if (v == null || v === '') {
      if (f.key === 'started_on') v = ctx.today || '';
      else if (f.key === 'color') v = ctx.defaultColor || '';
      else v = '';
    }
    var input = '<input type="' + type + '" class="aot-modern-input form-control' +
                (f.type === 'color' ? ' aot-detail-field-color' : '') + '" ' + a +
                ' value="' + _esc(v) + '">';

    // 시작일에는 [지우기] 를 붙이지 않는다 — 그 값은 비어 있으면 안 된다.
    if (f.type === 'date' && f.key !== 'started_on') {
      return clearableDate(input, f.key);
    }
    return input;
  }

  /**
   * **비울 수 있는 날짜 입력.**
   *
   * iOS Safari 의 날짜 입력에는 값을 비우는 수단이 없다. 피커를 열면 오늘이
   * 선택된 채로 뜨고, 그 상태에서 닫기만 해도 그 날짜가 들어간다 — 피커의
   * [재설정]도 입력을 비우지 않고 표시된 날짜를 넣는다. 그래서 "종료 미정"
   * (과수·다년생은 그것이 정상이다)으로 되돌릴 방법이 화면에 없었다.
   *
   * 구획 모달은 아직 자기 입력 빌더를 갖고 있어(공용 폼으로 옮기기 전이다)
   * 이 조각을 빌려 쓴다. 마크업이 한 곳이어야 두 화면의 x 가 같은 자리에 같은
   * 크기로 선다.
   */
  function clearableDate(inputHtml, key) {
    return '<span class="aot-pf-date">' + inputHtml +
           '<button type="button" class="aot-pf-date-clear"' +
           ' data-pf-clear="' + _esc(key) + '"' +
           ' title="' + _esc(_t('Clear')) + '"' +
           ' aria-label="' + _esc(_t('Clear')) + '">&#x2715;</button></span>';
  }

  /** [지우기] 배선. `wire()` 가 부르고, 공용 폼을 안 쓰는 화면은 직접 부른다. */
  function wireDateClear(root_, attr) {
    attr = attr || 'data-pf';
    Array.prototype.forEach.call(
      root_.querySelectorAll('[data-pf-clear]'), function (btn) {
        if (btn._pfWired) return;
        btn._pfWired = true;
        var key = btn.getAttribute('data-pf-clear');
        var input = root_.querySelector('[' + attr + '="' + key + '"]');
        if (!input) { btn.remove(); return; }
        // 값이 있을 때만 보인다: 빈 칸 옆의 x 는 누를 것이 없는 버튼이다.
        var sync = function () { btn.hidden = !input.value; };
        btn.addEventListener('click', function () {
          input.value = '';
          // 값이 사라진 것을 다른 배선(라벨·힌트)도 알아야 한다.
          input.dispatchEvent(new Event('change', { bubbles: true }));
          sync();
          input.focus();
        });
        input.addEventListener('change', sync);
        input.addEventListener('input', sync);
        sync();
      });
  }

  /**
   * 폼 본문. 감싸는 컨테이너·버튼은 화면이 붙인다.
   *
   * `ctx.groups` 가 참이면 그룹 제목(`.aot-modal-group-title`)과 컨테이너로
   * 묶어서 낸다 — 모달이 큰 화면(geo/design)에서 읽기를 돕는다. 작은 폼은
   * 평평한 편이 낫다(제목이 행보다 많아진다).
   */
  function rowsHtml(ctx) {
    ctx = ctx || {};
    if (ctx.groups) return _groupedHtml(ctx);
    var html = '';
    _visible(ctx).forEach(function (f) { html += _fieldHtml(f, ctx); });
    return html;
  }

  function _fieldHtml(f, ctx) {
    var label = (typeof f.label === 'function') ? f.label(ctx) : _t(f.label);
    var html = _row(_esc(label), _control(f, ctx)) + _hint(f.hint, ctx);
    if (f.type === 'alloc') html += _allocHintHtml();
    return html;
  }

  function _groupedHtml(ctx) {
    var visible = _visible(ctx);
    var html = '';
    GROUPS.forEach(function (g) {
      var mine = visible.filter(function (f) { return (f.group || 'what') === g[0]; });
      if (!mine.length) return;
      html += '<div class="aot-modal-group-title">' + _esc(_t(g[1])) + '</div>' +
              '<div class="aot-modal-container">';
      mine.forEach(function (f) { html += _fieldHtml(f, ctx); });
      html += '</div>';
    });
    return html;
  }

  /**
   * DOM → 저장 페이로드.
   *
   * `allocation` 만 모양이 다르다 — 서버가 dict 로 받고, 수량인지 비율인지는
   * **그 구역에 총량이 있는지**가 정한다. 화면이 접미로 보인 것과 같은 기준이라야
   * 사람이 본 것과 저장되는 것이 어긋나지 않는다.
   */
  function collect(root_, ctx) {
    ctx = ctx || {};
    var attr = ctx.attr || 'data-pf';
    var out = {};
    Array.prototype.forEach.call(root_.querySelectorAll('[' + attr + ']'), function (el) {
      out[el.getAttribute(attr)] = el.value || '';
    });

    if ('allocation_value' in out) {
      var av = out.allocation_value;
      delete out.allocation_value;
      if (av === '' || av == null) {
        out.allocation = null;                  // 비우면 지운다
      } else {
        var cap = capacityFor(ctx, out.bay_id);
        out.allocation = cap ? { amount: av } : { percent: av };
      }
    }
    return out;
  }

  function capacityFor(ctx, bayId) {
    var caps = ctx.capacities || {};
    return caps[bayId || ctx.bayId || ''] || caps[ctx.bayId] || null;
  }

  /**
   * 살아 움직이는 부분 — 종류↔프로그램, 몫 접미·안내.
   *
   * `ctx.loadPrograms(kind) -> Promise<list>` 를 주면 종류가 바뀔 때 프로그램
   * 목록을 갈아 끼운다. 폼 전체를 다시 그리지 않는 이유는 이 폼이 5초 폴링이
   * 도는 화면에도 있기 때문이다 — 통째로 갈아끼우면 그대로 깜빡임이 된다.
   */
  function wire(root_, ctx) {
    ctx = ctx || {};
    var attr = ctx.attr || 'data-pf';
    var q = function (k) { return root_.querySelector('[' + attr + '="' + k + '"]'); };
    var selKind = q('kind');
    var selProg = q('program_uuid');
    var selBay = q('bay_id');
    var alloIn = q('allocation_value');
    var alloSuf = root_.querySelector('.aot-ov-alloc-suffix');
    var alloHint = root_.querySelector('.aot-ov-alloc-hint');

    wireDateClear(root_, attr);

    var filled = false;          // 첫 채움인가(기존 선택을 되살릴 때만 쓴다)
    var fillPrograms = function () {
      if (!selProg || typeof ctx.loadPrograms !== 'function') return;
      var kind = (selKind && selKind.value) || ctx.kind || 'vegetation';
      ctx.loadPrograms(kind).then(function (list) {
        if (selKind && (selKind.value || 'vegetation') !== kind) return;  // 그 사이 또 바뀜
        var html = '<option value="">' + _esc(_t('No program')) + '</option>';
        (list || []).forEach(function (x) {
          html += '<option value="' + _esc(x.unique_id) + '">' +
                  _esc(x.name + (x.variety ? ' · ' + x.variety : '')) + '</option>';
        });
        // 종류가 바뀌면 옛 종류의 프로그램은 더 못 쓴다 — 비워 둔다.
        //
        // 다만 **첫 채움에서는 기존 선택을 되살린다.** 편집 폼은 선택지가 아직
        // 없을 때 그려질 수 있고(목록이 왕복 중), 그때 비워 두면 프로그램이
        // 붙어 있는 구획을 열었을 뿐인데 "프로그램 없음" 으로 바뀐다 — 그대로
        // 저장하면 조용히 떼어진다.
        var keep = (!filled && ctx.values)
          ? (ctx.values.program_uuid ||
             (ctx.values.program && ctx.values.program.unique_id) || '')
          : '';
        if (selProg.innerHTML !== html) selProg.innerHTML = html;
        if (keep) selProg.value = keep;
        filled = true;
      });
    };

    var syncAlloc = function () {
      if (!alloSuf) return;
      var cap = capacityFor(ctx, selBay ? selBay.value : null);
      alloSuf.textContent = cap
        ? ('/ ' + cap.total + ' ' + capUnitLabel(cap.unit)) : '%';
      if (alloIn) alloIn.setAttribute('max', cap ? String(cap.total) : '100');
      if (alloHint) alloHint.style.display = cap ? 'none' : '';
    };

    // 종류가 바뀌면 대상·품종 라벨도 따라간다 — "품종" 은 생물에만 맞는 말이라
    // 시설물을 고른 채 그대로 두면 화면이 틀린 말을 한다.
    var syncLabels = function () {
      var kind = (selKind && selKind.value) || 'vegetation';
      var L = _labels(kind);
      [['subject', L.subject], ['variety', L.variety]].forEach(function (pair) {
        var el = q(pair[0]);
        var row = el && el.closest('.aot-modal-option-row');
        var lab = row && row.querySelector('.aot-modal-option-label');
        if (lab) lab.textContent = pair[1];
      });
    };

    if (selKind) {
      selKind.addEventListener('change', function () {
        fillPrograms();
        syncLabels();
      });
    }
    if (selBay) selBay.addEventListener('change', syncAlloc);

    fillPrograms();
    syncAlloc();
    return { refresh: function () { fillPrograms(); syncAlloc(); syncLabels(); } };
  }

  root.AoTPlotForm = {
    FIELDS: FIELDS,
    KINDS: KINDS,
    rowsHtml: rowsHtml,
    collect: collect,
    wire: wire,
    capUnitLabel: capUnitLabel,
    // 공용 폼을 아직 안 쓰는 화면(구획 모달)이 같은 조각을 빌려 쓴다.
    clearableDate: clearableDate,
    wireDateClear: wireDateClear
  };
})(window);
