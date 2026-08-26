/* 구획의 단계 일정 편집 — **관리 프로그램 드로어와 같은 문법**.
 *
 * ## 이 파일이 있는 이유
 *
 * 프로그램은 표준을 정하고, 구획은 그 표준을 **참조만** 한다 — 경계는 구획이
 * 갖는다(P8). 같은 프로그램을 쓰는 두 구획이 서로 다른 일정을 갖는 것이
 * 정상이라, "이 구획의 육묘를 닷새 더" 는 프로그램이 아니라 여기서 고칠 일이다.
 * 그렇게 고친 결과가 쓸 만하면 그것을 새 프로그램으로 등록한다.
 *
 * ## 왜 프로그램 페이지를 따르는가
 *
 * 지도 위젯의 구획 팝업에도 단계 편집이 있지만 그것은 **지도에서 할 수 있는
 * 간단한 처리**다. 이 페이지는 작기를 짜는 전문적인 자리이고, 그 일에는
 * 프로그램 페이지가 이미 답을 갖고 있다:
 *
 *   - **막대가 곧 메뉴다.** 트랙의 구간을 누르면 그 단계 하나만 아래에서
 *     편집한다. 가로 막대(비율)와 세로 목록(편집)을 따로 두면 같은 것을 두
 *     방향으로 두 번 그리는 셈이라, 고치려면 막대에서 위치를 찾고 목록에서
 *     이름을 다시 찾아야 한다.
 *   - **정본은 DOM 이 아니라 `State.stages` 다.** 다른 단계로 옮길 때 지금
 *     패널을 읽어 배열에 넣고(`readPanel`), 저장도 그 배열에서 만든다. 이
 *     순서를 놓치면 방금 적은 것이 조용히 사라진다.
 *   - **값은 [저장]을 눌러야 반영된다.** 그래서 잘못 고쳐도 닫으면 원래 값이
 *     남는다. 단계마다 저장 버튼을 두면 한 드로어에 저장 규칙이 둘이 된다.
 *
 * 겉모양은 전부 공용이다 — 트랙은 `components/aot-stage-track.css`(프로그램
 * 페이지와 같은 파일), 행은 `aot-modal-option-row`, 토글은 `btn-toggle`.
 *
 * ## 무엇이 여기 없는가
 *
 * 목표·자원·적산온도·단계 식별 코드는 **프로그램의 것**이다(프로그램 페이지에서
 * 정한다). 구획이 갖는 것은 경계(기간)와 이 자리에서의 지침뿐이다.
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

  /* 프로그램 드로어와 **같은 골격·같은 클래스**(`program-settings.js` 의
     `_group`/`_box`/`_optRow`/`_wideRow`). 클래스를 하나라도 빼면 그 골격을
     성립시키는 규칙(`components/aot-drawer-form.css`)이 안 걸려, 긴 제목이
     잘리고 설명이 컨트롤 열에 찌그러진다 — 실제로 그렇게 만들어 봤다. */
  function _group(title, note) {
    return '<div class="aot-modal-group-title">' + _esc(title) + '</div>' +
           (note ? '<div class="aot-modal-body-text aot-drawer-group-note">' +
                   _esc(note) + '</div>' : '');
  }

  function _box(inner) {
    return '<div class="aot-modal-container">' + inner + '</div>';
  }

  /** 1행 [제목][컨트롤] · 2행 [설명]. 설명은 **행 안·라벨 밖** 세 번째
   *  자식이라야 구분선이 제목과 설명을 가르지 않는다. */
  function _optRow(label, note, control) {
    return '<div class="aot-modal-option-row aot-drawer-row">' +
           '<div class="aot-modal-option-label">' + _esc(label) + '</div>' +
           '<div class="aot-modal-option-control">' + control + '</div>' +
           (note ? '<div class="aot-modal-body-text aot-drawer-row-note">' +
                   _esc(note) + '</div>' : '') +
           '</div>';
  }

  /** 컨트롤이 전체 폭을 쓰는 행(여러 줄 입력). 순서는 제목 → 설명 → 컨트롤 —
   *  여러 줄 입력은 제목과 나란히 설 수 없으므로 설명을 먼저 읽고 쓰게 한다. */
  function _wideRow(label, note, control) {
    return '<div class="aot-modal-option-row aot-drawer-row aot-drawer-row-wide">' +
           '<div class="aot-modal-option-label">' + _esc(label) + '</div>' +
           (note ? '<div class="aot-modal-body-text aot-drawer-row-note">' +
                   _esc(note) + '</div>' : '') +
           '<div class="aot-modal-option-control">' + control + '</div>' +
           '</div>';
  }

  function _toggle(attrs, on) {
    return '<label class="btn-toggle mb-0">' +
             '<input type="checkbox" class="btn-toggle-input" ' + attrs +
               (on ? ' checked' : '') + '>' +
             '<span class="btn-toggle-slider">' +
               '<span class="btn-toggle-thumb"></span></span>' +
           '</label>';
  }

  // ── 상태 ──────────────────────────────────────────────────────────────

  var State = {
    plot: null,
    stages: [],      // 편집 중인 정본
    orig: [],        // 저장할 때 무엇이 바뀌었는지 가릴 기준
    removed: [],     // 뺀 단계의 key (저장할 때 지운다)
    cur: 0,
    autoAdvance: false
  };

  /** 서버가 준 일정을 편집용 배열로. **깊은 사본**이다 — 원본을 그대로 고치면
   *  무엇이 바뀌었는지 가릴 기준이 사라진다. */
  function _copy(list) {
    return (list || []).map(function (s) {
      return {
        key: s.key || '', name: s.name || '', days: (s.days == null ? '' : String(s.days)),
        guidance: s.guidance || '', starts_on: s.starts_on || '',
        editable: !!s.editable, removable: !!s.removable,
        state: s.state || '', isNew: false
      };
    });
  }

  function load(p) {
    State.plot = p || {};
    State.stages = _copy(p && p.stage_schedule);
    State.orig = _copy(p && p.stage_schedule);
    State.removed = [];
    State.autoAdvance = !!(p && p.auto_advance);
    // 지금 진행 중인 단계를 먼저 편다 — 사람이 이 창을 여는 이유가 대개
    // "지금/다음에 무엇을 하나" 라서, 첫 단계를 펴 두면 매번 옮겨야 한다.
    var cur = 0;
    State.stages.forEach(function (s, i) { if (s.state === 'current') cur = i; });
    State.cur = cur;
  }

  function has() { return State.stages.length > 0; }

  // ── 트랙 ──────────────────────────────────────────────────────────────

  /**
   * 단계 트랙 — **막대가 곧 메뉴다**(프로그램 페이지 `_trackHtml` 과 같은 구조).
   *
   * 폭은 비율이되 최소폭이 있다(CSS `min-width`) — 7일짜리 단계를 비율 그대로
   * 두면 이름도 안 보이고 누르기도 어렵다. 비율 감각보다 조작 가능성이 먼저다.
   *
   * 순서는 여기서 끌어 바꾸지 않는다(`--fixed`). 구획의 단계 순서는 이미 지나간
   * 경계가 고정하고 있어서, 끌어 옮기면 지나간 일을 다시 쓰는 셈이 된다 —
   * 그것은 원장(확인·되돌리기)이 하는 일이다.
   */
  function _trackHtml() {
    var stages = State.stages;
    if (!stages.length) return '';

    var known = [];
    stages.forEach(function (st) {
      var d = parseFloat(st.days);
      if (isFinite(d) && d > 0) known.push(d);
    });
    var sum = 0;
    known.forEach(function (d) { sum += d; });
    var avg = known.length ? (sum / known.length) : 1;

    var openEnd = false;
    var spans = stages.map(function (st) {
      var d = parseFloat(st.days);
      var ok = isFinite(d) && d > 0;
      if (!ok) openEnd = true;
      return ok ? d : Math.max(avg, 1);
    });
    var total = 0;
    spans.forEach(function (x) { total += x; });

    // 기간을 비운 마지막 단계("끝까지")는 길이를 모른다. 자리는 주되 **총합에는
    // 더하지 않는다** — 더하면 화면의 총 일수가 거짓말이 된다.
    var text = sum ? _t('%(n)s days').replace('%(n)s', String(Math.round(sum))) : '';
    if (openEnd) {
      text = text ? (text + ' · ' + _t('until the end')) : _t('until the end');
    }

    var segs = stages.map(function (st, i) {
      var d = parseFloat(st.days);
      var w = total > 0 ? (spans[i] / total) * 100 : (100 / stages.length);
      var days = (isFinite(d) && d > 0) ? String(d) : _t('until the end');
      var name = st.name || _t('Stage name');
      return '<button type="button" class="aot-stage-seg' +
               (i === State.cur ? ' is-current' : '') +
               (st.state === 'done' ? ' is-done' : '') +
               '" style="flex:1 1 ' + w.toFixed(2) + '%"' +
               ' data-act="stage-pick" data-stage-i="' + i + '"' +
               ' title="' + _esc(name + ' · ' + days) + '"' +
               ' aria-pressed="' + (i === State.cur) + '">' +
               '<span class="aot-stage-seg-name">' + _esc(name) + '</span>' +
               '<span class="aot-stage-seg-bar"></span>' +
               '<span class="aot-stage-seg-days">' + _esc(days) + '</span>' +
             '</button>';
    }).join('');

    // 겉모양은 공용 기간 바 그대로다 — 컨테이너에 `aot-viz` 를 붙여 그 토큰
    // (트랙 굵기·구간 색·표면색·다크 override)을 상속받는다.
    return '<div class="aot-viz aot-stage-track-wrap">' +
             '<div class="aot-viz-head">' +
               '<span class="aot-viz-label">' + _esc(_t('Whole run')) + '</span>' +
               '<span class="aot-viz-value">' + _esc(text) + '</span>' +
             '</div>' +
             '<div class="aot-stage-track aot-stage-track--fixed" role="tablist">' +
               segs + '</div>' +
           '</div>';
  }

  // ── 고른 단계의 설정 ──────────────────────────────────────────────────

  /**
   * 화면에 **한 벌만** 있다. 단계마다 블록을 만들어 쌓으면 여섯 단계가 세로
   * 공간을 전부 차지하고, 그중 하나만 쓰면서 나머지가 자리를 차지한다.
   *
   * 고칠 수 있는 것은 **아직 오지 않은 경계뿐**이다(`editable`) — 지나간 경계를
   * 옮기는 일은 원장이 하는 일이고, 두 수단이 같은 값을 다투면 무엇이 정본인지
   * 알 수 없다. 지침은 지나간 단계에도 적을 수 있다(관찰의 기록이다).
   */
  function _panelHtml() {
    var st = State.stages[State.cur];
    if (!st) return '';

    var nameRow = _optRow(_t('Stage name'), '',
      '<input type="text" class="form-control aot-modern-input" data-sf="name"' +
      (st.isNew ? '' : ' disabled') +
      ' value="' + _esc(st.name) + '">');

    var daysRow = _optRow(_t('Days'),
      st.editable ? _t('How long this stage lasts, counted from when the one before it ended. Leave the last one blank to run until the end.')
                  : _t('Already past — this boundary is fixed.'),
      '<input type="number" min="1" step="1" class="form-control aot-modern-input"' +
      ' data-sf="days" placeholder="' + _esc(_t('until the end')) + '"' +
      (st.editable ? '' : ' disabled') +
      ' value="' + _esc(st.days) + '">');

    // 시작일은 **결과**다(입력이 아니다). 기간을 고치면 여기가 따라 바뀐다 —
    // 날짜를 직접 받으면 "육묘를 닷새 더" 를 말하려고 사람이 덧셈을 해야 한다.
    var startRow = st.starts_on
      ? _optRow(_t('Start date'), '',
                '<span class="aot-modal-body-text">' + _esc(st.starts_on) + '</span>')
      : '';

    var guideRow = _wideRow(_t('Guidance'),
      _t('Shown on the map when someone opens a plot that is in this stage.'),
      '<textarea class="form-control aot-modern-input aot-drawer-textarea"' +
      ' rows="4" data-guidance' +
      ' placeholder="' + _esc(_t('What to do in this stage, here.')) + '">' +
      _esc(st.guidance) + '</textarea>');

    var del = st.removable
      ? '<div class="aot-stage-actions">' +
        '<button type="button" class="btn aot-pill-btn aot-pill-btn-sm"' +
        ' data-act="stage-del">' + _esc(_t('Remove stage')) + '</button></div>'
      : '';

    return '<div class="aot-stage-panel" data-stage-panel>' +
             nameRow + daysRow + startRow + guideRow + del +
           '</div>';
  }

  /** 지금 패널의 값을 `State.stages[cur]` 에 넣는다 — **정본은 그 배열이다.** */
  function readPanel(host) {
    var st = State.stages[State.cur];
    var panel = host && host.querySelector('[data-stage-panel]');
    if (!st || !panel) return;
    panel.querySelectorAll('[data-sf]').forEach(function (el) {
      if (el.disabled) return;         // 못 고치는 칸은 읽지 않는다
      st[el.getAttribute('data-sf')] = (el.value || '').trim();
    });
    // 지침은 **빈 문자열도 담는다** — 지운 것을 반영해야 한다.
    var g = panel.querySelector('[data-guidance]');
    if (g) st.guidance = g.value || '';
  }

  // ── 본문 ──────────────────────────────────────────────────────────────

  /**
   * ⚠ **"프로그램" 요약 카드를 여기 두지 않는다.**
   *
   * 지도 위젯 팝업에는 그런 카드가 있다(이름·단계 수·전체 기간). 거기서는
   * 필요하다 — 그 창은 읽는 자리라 "무엇을 근거로 기르고 있나" 를 어딘가는
   * 말해야 한다. 여기는 **고치는 자리**고, 그 셋이 전부 이미 화면에 있다:
   * 프로그램 이름은 [기본 정보]의 드롭다운이, 단계 수와 전체 기간은 바로 아래
   * 트랙이 말한다. 같은 값을 두 번 내면 사용자는 어느 쪽이 정본인지 매번
   * 확인하게 된다.
   */
  function html() {
    if (!has()) return '';
    return _group(_t('Stage schedule'),
                  _t('The programme is a reference. Changing one stage moves the ones after it.')) +
      _box('<div class="aot-stage-track-host">' + _trackHtml() + '</div>' +
           '<div class="aot-stage-add-row aot-stage-actions">' +
             '<button type="button" class="btn aot-pill-btn" data-act="stage-add">' +
             _esc(_t('Add stage')) + '</button></div>' +
           '<div class="aot-stage-panel-host">' + _panelHtml() + '</div>' +
           // 자동 승인은 **구획**의 성질이다(P8) — 같은 프로그램을 쓰는 두
           // 구획이 다른 답을 갖는 것이 정상이라 프로그램이 아니라 여기서 정한다.
           _optRow(_t('Advance stages automatically'), '',
                   _toggle('data-plot-auto', State.autoAdvance)));
  }

  /** 트랙과 패널을 함께 다시 그린다(이름·기간을 고치면 폭과 숫자가 따라온다). */
  function redraw(host) {
    if (!host) return;
    var t = host.querySelector('.aot-stage-track-host');
    if (t) {
      t.innerHTML = _trackHtml();
      var cur = t.querySelector('.aot-stage-seg.is-current');
      if (cur && cur.scrollIntoView) {
        try { cur.scrollIntoView({ block: 'nearest', inline: 'nearest' }); } catch (e) {}
      }
    }
    var b = host.querySelector('.aot-stage-panel-host');
    if (b) b.innerHTML = _panelHtml();
  }

  // ── 배선 ──────────────────────────────────────────────────────────────

  function wire(host) {
    if (!host) return;
    host.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-act]');
      if (!btn || !host.contains(btn)) return;
      var act = btn.getAttribute('data-act');

      if (act === 'stage-pick') {
        // **옮기기 전에 지금 패널을 읽는다** — 안 읽으면 방금 적은 것이 사라진다.
        readPanel(host);
        State.cur = parseInt(btn.getAttribute('data-stage-i'), 10) || 0;
        redraw(host);
      } else if (act === 'stage-add') {
        // 새 단계는 **고른 단계 바로 뒤**에 들어간다 — 늘 맨 끝에만 붙으면
        // 중간을 둘로 나눌 때 옮기는 일이 한 번 더 생긴다.
        readPanel(host);
        var at = Math.min(State.cur + 1, State.stages.length);
        State.stages.splice(at, 0, {
          key: '', name: '', days: '7', guidance: '', starts_on: '',
          editable: true, removable: true, state: 'future', isNew: true
        });
        State.cur = at;
        redraw(host);
        var f = host.querySelector('[data-sf="name"]');
        if (f) f.focus();
      } else if (act === 'stage-del') {
        var st = State.stages[State.cur];
        if (!st) return;
        if (!root.confirm(_t('Remove this stage from this plot?'))) return;
        // 이미 서버에 있는 단계는 저장할 때 지운다 — 여기서 바로 지우면
        // "닫으면 원래대로" 라는 이 드로어의 약속이 깨진다.
        if (!st.isNew && st.key) State.removed.push(st.key);
        State.stages.splice(State.cur, 1);
        State.cur = Math.max(0, State.cur - 1);
        redraw(host);
      }
    });

    var auto = host.querySelector('[data-plot-auto]');
    if (auto) auto.addEventListener('change', function () {
      State.autoAdvance = !!auto.checked;
    });
  }

  // ── 저장 ──────────────────────────────────────────────────────────────

  /**
   * 바뀐 것만 서버에 보낸다.
   *
   * 순서가 중요하다: **빼기 → 더하기 → 기간 → 지침**. 단계 집합이 먼저 정해져야
   * 그 다음 호출들이 가리키는 키가 존재한다.
   *
   * 기간은 `{days: {키: 일수}}` 로 **한 번에** 보낸다 — 서버가 그렇게 받는다
   * (경계 둘을 옮긴 결과가 반쪽만 남으면 안 된다).
   *
   * @param api  (method, url, body) -> Promise<{status, data}>
   * @returns Promise<{ok, message}>
   */
  function save(host, api) {
    readPanel(host);
    var uuid = (State.plot || {}).unique_id;
    if (!uuid) return Promise.resolve({ ok: true });
    var base = '/api/geo/plot/' + encodeURIComponent(uuid);
    var origByKey = {};
    State.orig.forEach(function (s) { origByKey[s.key] = s; });

    var chain = Promise.resolve({ ok: true });
    function step(fn) {
      chain = chain.then(function (prev) {
        if (!prev.ok) return prev;             // 처음 실패에서 멈춘다
        return fn();
      });
    }
    function check(res) {
      if (res.status >= 400 || !res.data.ok) {
        return { ok: false, message: res.data.message || _t('Save failed') };
      }
      return { ok: true };
    }

    // 1) 뺀 단계
    State.removed.forEach(function (key) {
      step(function () {
        return api('DELETE', base + '/stages/' + encodeURIComponent(key)).then(check);
      });
    });

    // 2) 더한 단계 — 이름·기간·지침을 한 번에 실어 보낸다(서버가 받는다).
    State.stages.forEach(function (st, i) {
      if (!st.isNew) return;
      var after = (i > 0) ? (State.stages[i - 1].key || '') : '';
      step(function () {
        return api('POST', base + '/stages', {
          name: st.name, days: st.days || null,
          guidance: st.guidance || '', after: after || undefined
        }).then(check);
      });
    });

    // 3) 기간 — 고칠 수 있는 것 중 바뀐 것만, 한 번에.
    var days = {};
    var anyDays = false;
    State.stages.forEach(function (st) {
      if (st.isNew || !st.editable || !st.key) return;
      var was = origByKey[st.key];
      if (!was || String(was.days) === String(st.days)) return;
      if (st.days === '') return;              // 빈 칸은 "끝까지" — 서버가 다룬다
      days[st.key] = st.days;
      anyDays = true;
    });
    if (anyDays) {
      step(function () {
        return api('POST', base + '/schedule', { days: days }).then(check);
      });
    }

    // 4) 지침 — 단계마다 따로 받는 엔드포인트라 바뀐 것만 보낸다.
    State.stages.forEach(function (st) {
      if (st.isNew || !st.key) return;
      var was = origByKey[st.key];
      if (was && (was.guidance || '') === (st.guidance || '')) return;
      step(function () {
        return api('POST', base + '/stage-guidance',
                   { stage_key: st.key, guidance: st.guidance }).then(check);
      });
    });

    return chain;
  }

  /** 기본 정보 저장에 실어 보낼 구획 자신의 값. */
  function plotFields() {
    return { auto_advance: State.autoAdvance };
  }

  /** 저장하지 않은 편집이 남아 있나 — [프로그램으로 등록] 이 먼저 저장할지 정한다. */
  function dirty(host) {
    if (host) readPanel(host);
    if (State.removed.length) return true;
    if (State.stages.length !== State.orig.length) return true;
    var origByKey = {};
    State.orig.forEach(function (s) { origByKey[s.key] = s; });
    return State.stages.some(function (st) {
      if (st.isNew) return true;
      var was = origByKey[st.key];
      if (!was) return true;
      return String(was.days) !== String(st.days) ||
             (was.guidance || '') !== (st.guidance || '');
    }) || State.autoAdvance !== !!(State.plot || {}).auto_advance;
  }

  root.AoTPlotStages = {
    load: load, has: has, html: html, wire: wire, redraw: redraw,
    readPanel: readPanel, save: save, plotFields: plotFields, dirty: dirty
  };
})(window);
