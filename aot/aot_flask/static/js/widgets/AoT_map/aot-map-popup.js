/**
 * aot-map-popup.js
 * Shared popup utilities for the AoT Map widget.
 *
 * Holds the HTML builders, dot-positioning, and event-wiring that the widget's
 * popups share, in a single authoritative module.
 *
 * Public API: window.AoTMapPopup = {
 *   positionDots(containerEl)
 *   wire(containerEl, onControl, lastCmdRef)
 * }
 *
 * @version 1
 */
(function () {
  'use strict';

  // 한 번만 정의한다 — 이 모듈은 순수 빌더라 두 번 실행해도 결과는 같지만,
  // 구획 위젯(AoT_plot)이 [환경] 블록 하나를 쓰려고 같은 파일을 자기 번들에
  // 담고 있어 지도 위젯과 한 대시보드에 서면 두 번 돈다. 가드는 그 두 번째를
  // 건너뛴다(두 벌은 같은 소스에서 나온 같은 코드다).
  if (window.AoTMapPopup) return;

  // Half of the 16 px thumb — used by the dot-left formula.
  var THUMB_R = 8;

  // Drag handle (same horizontal 2-line grip icon as the system card layout).
  // title is rendered in the current language via the window._ translation system at call time.
  function _dragHandle() {
    return '<span class="aot-act-drag-handle" title="' +
      (window._ ? window._('Reorder') : 'Reorder') +
      '"><i class="fa fa-grip-lines"></i></span>';
  }

  // HTML-escape a value for safe insertion into attribute / content.
  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  // Map act.control_type to 'value' | 'pwm' | 'binary'.
  function _ctrlType(act) {
    var ct = act && act.control_type;
    if (ct === 'value') return 'value';
    if (ct === 'pwm')   return 'pwm';
    return 'binary';
  }

  // ── positionDots ───────────────────────────────────────────────────────────
  // Position every .aot-3way-current-dot inside containerEl so it sits at the
  // current-value position along the range track.
  // Safe to call before layout: retries on the next animation frame if
  // offsetWidth is still 0 (e.g. popup just inserted into DOM).
  function positionDots(containerEl) {
    var needRetry = false;
    containerEl.querySelectorAll('.aot-3way-slider[data-current]').forEach(function (slider) {
      var dot = slider.parentElement &&
                slider.parentElement.querySelector('.aot-3way-current-dot');
      if (!dot) return;
      // 숨김 pane(display:none) 안의 슬라이더는 건너뜀 — pane 활성화 시
      // 호출자가 positionDots 를 다시 부른다.
      if (slider.offsetParent === null) return;
      var cur = parseFloat(slider.dataset.current || 0);
      var w   = slider.parentElement.offsetWidth;
      if (!w) { needRetry = true; return; }
      dot.style.left = (THUMB_R + (cur / 100) * (w - THUMB_R * 2)) + 'px';
    });

    // 재시도는 컨테이너당 rAF 1회만 예약 + 횟수 제한.
    // (이전 구현은 폭 0 슬라이더마다 전체 positionDots 를 예약해
    //  프레임당 콜백이 N배씩 늘었다 — 액추에이터가 많은 시설에서
    //  팝업을 열면 탭이 프리징되던 원인.)
    if (!needRetry) { containerEl._aotDotRafTries = 0; return; }
    if (containerEl._aotDotRaf) return;
    containerEl._aotDotRafTries = (containerEl._aotDotRafTries || 0) + 1;
    if (containerEl._aotDotRafTries > 60) { containerEl._aotDotRafTries = 0; return; }
    containerEl._aotDotRaf = requestAnimationFrame(function () {
      containerEl._aotDotRaf = null;
      positionDots(containerEl);
    });
  }

  // 빈 상태도 제목을 달아 내보낸다 — 안내문만 떠 있으면 "무엇이 없다는
  // 것인지" 를 화면이 말해 주지 못한다(현황 pane 의 블록들과 같은 골격).
  function _emptyBlock(title, msg) {
    return '<div class="aot-ov-card-title">' + _esc(title) + '</div>' +
           '<div class="aot-ov-block aot-ov-inactive">' +
           '<div class="aot-ov-muted">' + _esc(msg) + '</div></div>';
  }

  // Build only the actuator rows for one category (no header). Returns '' when
  // the category has no actuators.
  function _buildCatRows(catKey, states, canCtrl, lastCmd, catKeyFn, savedOrder) {
    var allSlots = Object.keys(states);
    var ordered  = (window.AoTActuatorOrder)
      ? window.AoTActuatorOrder.order(allSlots, savedOrder, function (sk) {
          return (states[sk] && states[sk].name) || sk;
        })
      : allSlots;
    var slotKeys = ordered.filter(function (sk) {
      return catKeyFn(states[sk].kind || '') === catKey;
    });
    if (!slotKeys.length) return '';
    var html = '';
    slotKeys.forEach(function (sk) {
      html += _buildActRow(sk, states[sk], _ctrlType(states[sk]), canCtrl, lastCmd);
    });
    return html;
  }

  // 탭 이름이 [환경·제어]이므로 카드가 그 둘을 가른다. **비어 있을 때만 제목을
  // 내면 안 된다** — 값이 붙는 순간 제목이 사라져, 같은 자리가 상태에 따라 다른
  // 화면이 된다(예전 동작). 어휘는 네 모달이 하나를 쓴다: 환경 / 제어.
  // ── buildActuatorTabs ───────────────────────────────────────────────────────
  // Build a single tabbed popup body covering every category that has at least
  // one actuator. Replaces the old "one chip per category" UI where each chip
  // opened its own popup. One control label → one popup → tabs per group.
  //
  //   activeCatKey  string|null  category to show first (defaults to first
  //                              available); ignored if it has no actuators
  //   cats          array        [{ key, label }, ...] in display order
  //   states/canCtrl/lastCmd/catKeyFn/savedOrder  see _buildCatRows
  //
  // Structure:
  //   .aot-act-tabs[data-active-cat]
  //     .aot-act-tabs-nav    → .aot-act-tab-btn[data-cat] (one per available cat)
  //     .aot-act-tabs-body[data-cat]  → rows for the active category
  function buildActuatorTabs(activeCatKey, cats, states, canCtrl, lastCmd, catKeyFn, savedOrder) {
    var counts = {};
    Object.keys(states).forEach(function (sk) {
      var c = catKeyFn(states[sk].kind || '');
      counts[c] = (counts[c] || 0) + 1;
    });
    var avail = cats.filter(function (c) { return (counts[c.key] || 0) > 0; });
    if (!avail.length) {
      return _emptyBlock(_t('Control'), _t('No actuators'));
    }
    // Resolve active tab: keep requested one if it still has actuators.
    var active = avail.some(function (c) { return c.key === activeCatKey; })
      ? activeCatKey : avail[0].key;

    var nav = '<div class="aot-act-tabs-nav">';
    avail.forEach(function (c) {
      nav += '<button type="button" class="aot-act-tab-btn' +
             (c.key === active ? ' active' : '') + '" data-cat="' + _esc(c.key) + '">' +
             _esc(c.label) + ' <span class="aot-act-tab-count">' + counts[c.key] + '</span>' +
             '</button>';
    });
    nav += '</div>';

    var body = '<div class="aot-act-tabs-body" data-cat="' + _esc(active) + '">' +
               _buildCatRows(active, states, canCtrl, lastCmd, catKeyFn, savedOrder) +
               '</div>';

    return '<div class="aot-ov-card-title">' + _esc(_t('Control')) + '</div>' +
           '<div class="aot-act-tabs" data-active-cat="' + _esc(active) + '">' +
           nav + body + '</div>';
  }

  // ── buildSensorTabs ─────────────────────────────────────────────────────────
  // Tabbed popup body for a facility's fitting sensors, one tab per measurement
  // key (VPD first), rows = sensor name + current value. Mirrors the control
  // popup structure (buildActuatorTabs) and reuses the same .aot-act-* classes.
  //
  //   activeKey  string|null   measurement key of the tab to show first
  //   sensors    array         runtime fitting_sensors[] entries
  var _SENSOR_KEY_ORDER = ['VPD', 'T', 'RH', 'CO2', 'light', 'wind_ms', 'wind_deg'];

  function buildSensorTabs(activeKey, sensors) {
    var groups = {};   // key → [{ fittingId, name, valStr, stale }]
    (sensors || []).forEach(function (s) {
      (s.channels || []).forEach(function (c) {
        if (!c || c.value == null) return;
        var k = c.key || c.measurement_type || '?';
        (groups[k] = groups[k] || []).push({
          fittingId: s.fitting_id,
          name:      s.name || s.fitting_id,
          valStr:    window.AoTSensorLabel ? window.AoTSensorLabel.formatChannel(c) : String(c.value),
          stale:     !!c.stale
        });
      });
    });
    var keys = Object.keys(groups);
    if (!keys.length) {
      return _emptyBlock(_t('Environment'), _t('No Measurements'));
    }
    keys.sort(function (a, b) {
      var ia = _SENSOR_KEY_ORDER.indexOf(a), ib = _SENSOR_KEY_ORDER.indexOf(b);
      if (ia === -1) ia = 99; if (ib === -1) ib = 99;
      return ia !== ib ? ia - ib : a.localeCompare(b);
    });
    var active = keys.indexOf(activeKey) !== -1 ? activeKey : keys[0];

    var nav = '<div class="aot-act-tabs-nav">';
    keys.forEach(function (k) {
      var disp = window.AoTSensorLabel ? window.AoTSensorLabel.keyDisplay(k) : k;
      nav += '<button type="button" class="aot-act-tab-btn' +
             (k === active ? ' active' : '') + '" data-cat="' + _esc(k) + '">' +
             _esc(disp) + ' <span class="aot-act-tab-count">' + groups[k].length + '</span>' +
             '</button>';
    });
    nav += '</div>';

    var rows = '';
    groups[active].forEach(function (r) {
      rows += '<div class="aot-act-row aot-sensor-tab-row" data-fitting="' + _esc(r.fittingId) + '">' +
              '<span class="aot-act-name">' + _esc(r.name) + '</span>' +
              '<span class="aot-act-val-ro' + (r.stale ? ' aot-stale' : '') + '">' + _esc(r.valStr) + '</span>' +
              '</div>';
    });

    return '<div class="aot-ov-card-title">' + _esc(_t('Environment')) + '</div>' +
           '<div class="aot-act-tabs" data-active-cat="' + _esc(active) + '">' +
           nav + '<div class="aot-act-tabs-body" data-cat="' + _esc(active) + '">' + rows + '</div></div>';
  }

  // 공용 슬라이드 토글 (components/aot-toggle.css — AoT_timer 등과 동일 마크업)
  function _slideToggle(extraCls, inputCls, sk, on, dataAttrs) {
    return '<label class="btn-toggle ' + extraCls + '">' +
           '<input type="checkbox" class="btn-toggle-input ' + inputCls + '"' +
           ' data-slot="' + _esc(sk) + '"' + (dataAttrs || '') +
           (on ? ' checked' : '') + '>' +
           '<span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>' +
           '</label>';
  }

  // 시작/종료 예약 버튼. 실제 제어 대상 UUID/채널은 slot_key(`<uuid>::<ch>`)가
  // 아니라 상태에 실린 output_uuid 를 우선한다 — 시설 슬롯 키는 UUID 와 다를 수
  // 있다(actuators_resolved.slot_key).
  // 시작/종료 예약 버튼 — **여기가 유일한 생성처다.**
  // 예전에는 시설 행·구역 목록·장치 모달이 각자 만들어서, 같은 버튼이 어떤
  // 곳은 "설정", 어떤 곳은 "시작/종료 시각 설정"으로 보였다. 문구만 맞추면
  // 다음에 또 갈라지므로 버튼 자체를 하나로 묶는다.
  // 라벨은 짧게(좁은 행에 들어가야 한다), 무엇을 여는지는 title 로 말한다.
  function scheduleButtonHtml(opts) {
    opts = opts || {};
    var _tr = function (x) { return (window._ ? window._(x) : x); };
    return '<button type="button" class="aot-act-pbtn aot-output-settings"' +
           ' data-output-id="' + _esc(opts.outputId || '') + '"' +
           ' data-channel="' + _esc(String(opts.channel == null ? 0 : opts.channel)) + '"' +
           ' data-output-name="' + _esc(opts.name || '') + '"' +
           ' title="' + _esc(_tr('Set start/end time')) + '">' +
           _esc(_tr('Settings')) + '</button>';
  }

  // 슬롯 키에서 실제 제어 대상(uuid/채널)을 뽑는다 — 예약 버튼과 시간 칸이
  // 같은 대상을 가리켜야 한다.
  function _slotIds(sk, s) {
    return {
      oid: (s && s.output_uuid) || String(sk).split('::')[0],
      ch:  (s && s.channel != null) ? s.channel
           : (String(sk).indexOf('::') > -1 ? String(sk).split('::')[1] : 0)
    };
  }

  function _scheduleBtn(sk, s) {
    var id = _slotIds(sk, s);
    return scheduleButtonHtml({ outputId: id.oid, channel: id.ch,
                                name: (s && s.name) || sk });
  }

  // ── 출력 행 공용 2행 골격 ──────────────────────────────────────────────────
  //
  //   1행: [드래그] 이름 ..................... 주 제어(슬라이드 토글/3버튼)
  //   2행: 작동·예약 시간 ..................... 설정(예약 버튼 / 슬라이더)
  //
  // on/off·PWM·개폐형이 각각 1행·3행·2행이라 목록에서 줄 높이가 들쭉날쭉했고,
  // "언제부터 켜져 있나"는 마커 팝업에만 있어 구역·시설 목록에서는 알 수 없었다.
  // 종류가 달라도 **같은 자리에 같은 것**이 오도록 골격을 하나로 둔다:
  // 왼쪽은 언제나 정체·상태, 오른쪽은 언제나 조작이다.
  //
  // opts: { slot, name, drag, primary, meta, settings }
  //   primary  1행 우측 HTML (없으면 빈칸)
  //   meta     2행 좌측 HTML (작동/예약 시간 — 없으면 '—')
  //   settings 2행 우측 HTML (예약 버튼·슬라이더 등)
  function buildOutputRow(opts) {
    opts = opts || {};
    var meta = opts.meta || '<span class="aot-act-meta-dim">—</span>';
    // note: 2행에서 **자기 줄을 갖는** 칸(관수 영향 범위 등).
    // `meta` 에 이어붙이면 `.aot-act-meta-text` 안쪽이라 flex 자식이 아니고,
    // 그러면 줄바꿈 규칙이 안 먹어 시간 숫자에 그대로 달라붙는다
    // (실제로 "05:51:59함께 적심: …" 로 나갔다).
    var second = (opts.meta || opts.settings || opts.note)
      ? '<div class="aot-act-meta">' +
          '<span class="aot-act-meta-text">' + meta + '</span>' +
          '<span class="aot-act-meta-ctrl">' + (opts.settings || '') + '</span>' +
          (opts.note || '') +
        '</div>'
      : '';
    return '<div class="aot-act-row" data-slot="' + _esc(opts.slot || '') + '">' +
             '<div class="aot-act-line">' +
               (opts.drag ? _dragHandle() : '') +
               // rawName: 이름 옆에 배지 같은 마크업을 붙이는 호출부용.
               // 그 호출부가 **직접 이스케이프한다** — 기본은 계속 이스케이프다.
               '<span class="aot-act-name"' + (opts.nameAttrs || '') + '>' +
               (opts.rawName ? (opts.name || '') : _esc(opts.name || '')) +
               '</span>' +
               (opts.primary || '') +
             '</div>' + second +
           '</div>';
  }

  // ── 스코프 배지 — "이 장치가 왜 여기 보이나" ──────────────────────────────
  //
  // 식생 모달에만 붙는다. 구역은 빌려오는 것이 없어 서버가 scope 를 안 주고,
  // 그러면 이 함수도 빈 문자열을 돌려준다(구역 화면은 그대로).
  //
  //   plot        구획 안에 있다 → 배지 없음(기본이라 말할 것이 없다)
  //   zone        소속 구역의 것을 빌려 본다
  //   irrigation  구획에도 구역에도 없지만 이 구획을 적신다
  //
  // 'zone' 을 말하지 않으면 사용자는 구획마다 따로 잰 값으로 읽는다.
  function scopeBadgeHtml(scope, distanceM, reason) {
    if (scope === 'nearest') {
      // 거리를 배지 글자로 쓴다 — 좁은 센서 탭에도 들어가고, "왜 여기 있나"
      // 보다 "얼마나 떨어져 있나" 가 값을 믿을지 정하는 근거다.
      // 이유는 title 로 붙인다 — 없어서인지, 있는데 죽어서인지는 다른 사건이다.
      var d = (distanceM != null) ? Math.round(distanceM) + 'm' : _t('nearest');
      var why = (reason === 'stale')
        ? _t('The sensor in this plot is not reporting — showing the closest one')
        : _t('Nothing in this plot — showing the closest one');
      return ' <span class="aot-act-tag aot-scope-nearest" title="' +
             _esc(why) + '">' + _esc(d) + '</span>';
    }
    // 'plot' 과 'irrigation' 에는 배지를 달지 않는다.
    //
    // 'irrigation' 은 **마커가 구획 밖에 있다**는 뜻일 뿐인데, 화면에서는
    // 기능 분류처럼 읽혔다. 실제로 같은 밸브 v341 이 어떤 구획에서는 [관수]
    // 이고 다른 구획에서는 아무 표시가 없었다(마커가 그 폴리곤 안에 들어갔다는
    // 이유뿐이다). "v331 96.4% / v332 [관수] 3.6%" 는 v331 이 관수용이 아닌
    // 것처럼 읽힌다 — 둘 다 밸브다.
    //
    // 왜 여기 있고 얼마나 중요한지는 바로 아래 줄의 덮는 비율이 이미 말한다.
    // 'nearest' 만 배지를 갖는 이유도 같다: 거리는 비율이 대신 말해 주지
    // 못하는, 값을 믿을지 정하는 근거다.
    return '';
  }

  // 값을 못 주는 센서 표시 — 목록에서 빼지 않는다. 빼면 고장이 화면에서
  // 사라져 아무도 고치지 않는다.
  function noDataBadgeHtml(on) {
    if (!on) return '';
    return ' <span class="aot-act-tag aot-scope-nodata" title="' +
           _esc(_t('This sensor is not reporting right now')) + '">' +
           _esc(_t('no data')) + '</span>';
  }

  // ── 영향 범위 — "켜면 무엇이 함께 영향을 받는가" ──────────────────────────
  //
  // **구역 모달과 식생 모달 양쪽에 들어간다.** 겹침이 정상인 도메인이라(간작·
  // 혼작) 한 장치가 여러 구획에 걸치는 것이 예외가 아니라 기본인데, 한쪽
  // 화면에만 알리면 "구역에서 켜면 안전하다"는 잘못된 대비가 생긴다.
  //
  // ⚠ **"적신다" 고 쓰지 말 것.** 이 판정의 근거는 *장치 영역 도형이 구획과
  // 겹친다* 하나뿐이다 — 그 장치가 관수 장치라는 근거는 어디에도 없다(실측:
  // 이 지도의 영역 장치는 전부 `output_type='virtual_on_off_single'`, 즉 범용
  // on/off 다. 'v341' 같은 이름은 그 농장의 작명일 뿐 시스템이 읽는 값이
  // 아니다). 관수인지 조명인지 환기인지 모르는 채 "물" 을 말하면, 다른 종류의
  // 장치를 쓰는 농장에서 화면이 그냥 거짓말이 된다.
  //
  // 접거나 툴팁으로 숨기지 말 것 — 켜는 순간 되돌릴 수 없는 장치가 있다.
  //
  //   coveragePct  이 구획이 그 장치 영역에 얼마나 덮이는가(식생 모달에만
  //                온다). 낮은 값을 감추면 구획 단위로 작동했다고 오해한다.
  function coverageHtml(alsoCovers, coveragePct) {
    var parts = [];
    if (coveragePct != null) {
      // `%%` 를 쓰지 말 것 — 여기는 printf 가 아니라 문자열 치환이라 그대로
      // 두 개가 찍힌다(실제로 "75.9%%" 로 나갔다).
      parts.push('<span class="aot-act-cover-pct">' +
                 _esc(_t('{pct} of this plot')
                      .replace('{pct}', String(coveragePct) + '%')) + '</span>');
    }
    if (alsoCovers && alsoCovers.length) {
      // 개수와 목록을 같이 쓰지 않는다 — 목록을 다 보여주므로 "3곳" 은
      // 같은 말을 두 번 하는 것이고, 좁은 2행에서 자리만 먹는다.
      parts.push('<span class="aot-act-cover-also">' +
                 _esc(_t('Also covers')) + ': ' +
                 _esc(alsoCovers.join(', ')) + '</span>');
    }
    if (!parts.length) return '';
    return '<span class="aot-act-coverage">' + parts.join(' · ') + '</span>';
  }

  // ── 작동 시간 한 칸 (공용) ─────────────────────────────────────────────────
  //
  //   꺼짐 → 마지막 작동 시간(흐림) / 켜짐 → 그 자리가 곧 흐르는 타이머(강조)
  //
  // **여기가 유일한 생성처이자 유일한 갱신처다.** 예전에는 시설이 정적
  // 스냅샷을, 구역이 "열 때 한 번 채우고 끝"을, 장치 모달만 살아 움직이는
  // 타이머를 각자 그렸다. 그래서 같은 장치가 세 화면에서 세 가지로 보였고,
  // 구역 목록은 눈앞에서 장치를 켜도 시간이 그대로 멈춰 있었다.
  //
  // 문구("마지막 작동"/"실행 중")는 두지 않는다 — 어느 쪽인지는 같은 행의
  // 토글과 색이 이미 말하고, 좁은 2행에서 다섯 글자는 정작 읽어야 할 숫자를
  // 밀어낸다. 대신 숫자를 키우고, 무엇인지는 title 로 남긴다.
  //
  //   opts: { outputId, channel, runtime:{elapsed_sec,last_duration_sec}, on,
  //           deferLast }
  //   deferLast  마지막 작동 시간이 별도 배치로 뒤따라올 때(구역 목록).
  //              켜져 있지도 않은 칸마다 낱개 요청을 보내지 않게 한다.
  // 상위로 가는 화살표 글리프 대신 **그린 아이콘**을 쓴다.
  //
  // `←`(U+2190)는 글꼴이 그리는 문자라 굵기를 정할 수 없다. 본문용 글꼴에서는
  // 획이 가늘고 화살촉이 뭉툭해, 원형 배경 위에 놓으면 배경만 보이고 화살표는
  // 눈에 들어오지 않았다. 획 굵기·끝 모양을 직접 정할 수 있는 선(셰브론)으로
  // 바꾼다 — `currentColor` 라 색은 버튼 규칙을 그대로 따른다.
  function upIconHtml() {
    return '<svg class="aot-modal-up-icon" viewBox="0 0 24 24" aria-hidden="true"' +
           ' fill="none" stroke="currentColor" stroke-width="2.6"' +
           ' stroke-linecap="round" stroke-linejoin="round">' +
           '<path d="M14.5 5.5 8 12l6.5 6.5"/></svg>';
  }

  // 같은 칸이 **다시 그려질 때** 값을 잃지 않게 하는 기억.
  //
  // 제어 영역은 상태 폴링마다 통째로 다시 그려진다(`.aot-act-tabs` 교체). 그때
  // 새 HTML 의 시간 칸은 값이 없어 `—`(또는 켜져 있으면 `…`)로 시작하고, 곧이어
  // 서버 왕복이 돌아와 실제 시간이 채워진다 — 실측 115ms. 값 자체는 맞지만
  // 사용자 눈에는 **주기마다 시간이 사라졌다 나타나는 깜빡임**이다.
  //
  // 마지막 작동 시간과 가동 시작 시각은 다시 그리는 사이에 변하지 않는다.
  // 그러니 마지막으로 알던 값을 슬롯 키에 남겨 두고, 새로 그릴 때 그것으로
  // 첫 화면을 채운다. 서버 응답이 오면 평소대로 덮어쓴다(값의 정본은 그대로
  // 서버다 — 여기 있는 것은 왕복 동안 보여 줄 직전 값일 뿐이다).
  var _slotMemo = Object.create(null);   // 'oid::ch' → { last, startEpoch }
  function _memoKey(oid, ch) {
    return String(oid || '') + '::' + String(ch == null ? 0 : ch);
  }
  function _memoPut(oid, ch, patch) {
    if (!oid) return;
    var k = _memoKey(oid, ch);
    var m = _slotMemo[k] || (_slotMemo[k] = {});
    if (patch.last != null) m.last = patch.last;
    if ('startEpoch' in patch) m.startEpoch = patch.startEpoch;
  }
  function _memoGet(oid, ch) { return _slotMemo[_memoKey(oid, ch)] || null; }

  function timeSlotHtml(opts) {
    var _tr = function (x) { return (window._ ? window._(x) : x); };
    opts = opts || {};
    var rt   = opts.runtime || {};
    var on   = !!(opts.on || (rt.elapsed_sec != null && rt.elapsed_sec > 0));
    var last = (rt.last_duration_sec != null) ? rt.last_duration_sec : null;
    var memo = _memoGet(opts.outputId, opts.channel);
    if (last == null && memo && memo.last != null) last = memo.last;
    var txt;
    if (on) {
      if (rt.elapsed_sec != null && rt.elapsed_sec > 0) {
        txt = _fmtDur(rt.elapsed_sec);
      } else if (memo && memo.startEpoch) {
        // 가동 중인 칸은 시작 시각만 알면 지금 경과를 그 자리에서 계산할 수
        // 있다 — 스톱워치가 첫 tick 을 놓을 때까지 `…` 를 보이지 않는다.
        var el0 = Math.floor(Date.now() / 1000) - memo.startEpoch;
        txt = (el0 > 0) ? _fmtDur(el0) : '…';
      } else {
        txt = '…';
      }
    } else {
      txt = (last != null && last > 0) ? _fmtDur(last) : '—';
    }
    _scheduleSlotSweep();
    return '<span class="aot-act-time aot-timer-display' +
           (on ? ' aot-act-time-on' : '') + '"' +
           ' data-out="' + _esc(opts.outputId || '') + '"' +
           ' data-ch="' + _esc(String(opts.channel == null ? 0 : opts.channel)) + '"' +
           ' data-run="' + (on ? '1' : '0') + '"' +
           (last != null ? ' data-last="' + _esc(String(last)) + '"' : '') +
           (opts.deferLast ? ' data-deferlast="1"' : '') +
           ' title="' + _esc(_tr(on ? 'Running' : 'Last run')) + '">' +
           _esc(txt) + '</span>';
  }

  // 상태 폴링이 부르는 갱신구. 켜짐/꺼짐이 **바뀐 때만** 갈아 끼운다 —
  // 폴링마다 register 하면 스톱워치가 매번 다시 맞춰져 초가 튄다.
  //   st: { countsRuntime, startEpoch }
  function applyTimeSlot(el, st) {
    if (!el) return;
    var _tr = function (x) { return (window._ ? window._(x) : x); };
    var on    = !!(st && st.countsRuntime);
    var first = (el._aotSwOn === undefined);
    if (!first && el._aotSwOn === on) return;
    el._aotSwOn = on;
    el.dataset.run = on ? '1' : '0';
    el.classList.toggle('aot-act-time-on', on);
    el.title = _tr(on ? 'Running' : 'Last run');

    var oid = el.dataset.out || '';
    var ch  = el.dataset.ch || '0';
    if (!oid) return;

    if (!on) {
      // 스톱워치에서 이 칸을 뗀다 — 안 떼면 매 tick 마다 "00:00:00" 이
      // 마지막 작동 시간을 덮어쓴다.
      if (window.AoTStopwatchManager && window.AoTStopwatchManager.unregister) {
        window.AoTStopwatchManager.unregister(oid + '::' + ch, el);
      }
      if (first && el.dataset.deferlast === '1') return;  // 배치가 채운다
      if (first && el.dataset.last !== undefined) {
        var s0 = parseInt(el.dataset.last, 10);
        el.textContent = (isNaN(s0) || s0 <= 0) ? '—' : _fmtDur(s0);
        return;
      }
      fillLastDuration(el);
      return;
    }

    if (st && st.startEpoch) { _regSlot(el, oid, ch, st.startEpoch); return; }
    // 시작 시각을 모르는 채 등록하면 스톱워치가 **직전 가동의** startMs 를
    // 그대로 물고 있어, 첫 sync 가 돌아올 때까지 엉뚱한 경과가 뜬다.
    fetch('/output_started_at_public/' + encodeURIComponent(oid) + '/' +
          encodeURIComponent(ch))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!el._aotSwOn || !document.body.contains(el)) return;
        var se = null;
        if (d) {
          if (d.started_at_epoch) se = d.started_at_epoch;
          else if (d.elapsed_sec > 0 && d.server_now_epoch) {
            se = d.server_now_epoch - d.elapsed_sec;
          }
        }
        _regSlot(el, oid, ch, se);
      })
      .catch(function () {
        if (el._aotSwOn) _regSlot(el, oid, ch, null);
      });
  }

  function _regSlot(el, oid, ch, startEpoch) {
    if (startEpoch) _memoPut(oid, ch, { startEpoch: startEpoch });
    if (!window.AoTStopwatchManager) return;
    window.AoTStopwatchManager.register(oid, ch, true, startEpoch || null,
                                        el, 7000, false);
  }

  function fillLastDuration(el) {
    var oid = el.dataset.out || '', ch = el.dataset.ch || '0';
    if (!oid) return;
    fetch('/output_last_duration_public/' + encodeURIComponent(oid) + '/' +
          encodeURIComponent(ch))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        // 그 사이 다시 켜졌으면 타이머가 이 칸의 주인이다.
        if (!d || el._aotSwOn || !document.body.contains(el)) return;
        var s = parseInt(d.last_duration_sec, 10);
        el.dataset.last = isNaN(s) ? '0' : String(s);
        if (!isNaN(s)) _memoPut(oid, ch, { last: s });
        delete el.dataset.deferlast;
        el.textContent = (isNaN(s) || s <= 0) ? '—' : _fmtDur(s);
      })
      .catch(function () {});
  }

  // 배치로 받아 온 runtime 을 칸에 심는다(구역 목록). 켜져 있는 칸은
  // 건드리지 않는다 — 거기는 스톱워치가 주인이다.
  function seedTimeSlot(el, rt) {
    if (!el) return;
    rt = rt || {};
    if (rt.last_duration_sec != null) {
      el.dataset.last = String(rt.last_duration_sec);
      _memoPut(el.dataset.out, el.dataset.ch, { last: rt.last_duration_sec });
    }
    delete el.dataset.deferlast;
    if (el._aotSwOn) return;
    var s = parseInt(el.dataset.last, 10);
    el.textContent = (isNaN(s) || s <= 0) ? '—' : _fmtDur(s);
  }

  // innerHTML 으로 꽂힌 칸을 스톱워치에 물린다.
  //
  // 호출처가 이미 여섯 곳이고 앞으로 더 는다. 저마다 배선을 기억하게 두면
  // 한 곳만 빠뜨려도 그 화면의 시간만 조용히 멈춘다 — 구역 목록이 정확히
  // 그랬다. 그래서 **생성이 곧 예약**이다: timeSlotHtml 이 문서 전체 훑기를
  // 한 번 걸어 두고, 아직 배선 안 된 칸(_aotSwOn 미정)만 붙잡는다.
  function wireTimeSlots(root) {
    var scope = root || document;
    var els = scope.querySelectorAll('.aot-act-time[data-out]');
    Array.prototype.forEach.call(els, function (el) {
      applyTimeSlot(el, { countsRuntime: el.dataset.run === '1' });
    });
  }

  var _slotSweep = null;
  function _scheduleSlotSweep() {
    if (_slotSweep) return;
    _slotSweep = setTimeout(function () {
      _slotSweep = null;
      wireTimeSlots(document);
    }, 0);
  }

  // 예약 시각 한 줄 — 시간 칸 옆에 덧붙는다. 시간 칸이 "지금/방금"을 말하고
  // 이쪽이 "다음"을 말한다.
  //
  // rtKey(`<uuid>::<채널>`)를 주면 내용이 없어도 **빈 칸을 남긴다.** 예약을 저장한
  // 직후 그 자리를 찾아 갈아 끼우려면(refreshOutputScheduleLabel) 자리가 먼저
  // 있어야 한다 — 예약이 없을 때 아무것도 안 그리면 갱신할 대상이 없어서 모달을
  // 닫았다 열 때까지 방금 넣은 예약이 안 보인다. 구역 모달은 이미 자기 칸을
  // 갖고 있으므로 키 없이 부른다(중첩 방지).
  function nextRunHtml(rt, rtKey) {
    var _tr = function (x) { return (window._ ? window._(x) : x); };
    var inner = (rt && rt.next_schedule)
      // 타이머 시간 바로 옆이므로 구분선을 세우고 여백을 둔다(.aot-act-meta-sep).
      // 예약 시각은 .aot-act-time 을 써서 타이머 표시와 같은 크기·색으로 보인다 —
      // 예전에는 .aot-act-meta-dim 이라 더 작고 흐려서 다른 종류의 정보처럼 읽혔다.
      ? '<span class="aot-act-meta-sep">|</span>' +
        '<span class="aot-act-time">' + _esc(_tr('Next run')) + ' ' +
        _esc(rt.next_schedule) + '</span>'
      : '';
    if (!rtKey) return inner;
    return '<span class="aot-act-rt" data-rt-key="' + _esc(rtKey) + '">' + inner + '</span>';
  }

  // 한 장치의 런타임(작동 중 여부·예약 목록)을 서버에서 읽는다. 배치 엔드포인트를
  // 항목 하나로 쓴다 — 예약 상황과 행 라벨이 **같은 조회**에서 나와야 한쪽만
  // 갱신되는 순간이 없다. force 성 요구이므로 조건부 요청을 걸지 않는다.
  function _outputRuntime(outputId, channel) {
    var ch = parseInt(channel || 0, 10) || 0;
    return fetch('/api/geo/output_runtimes', {
      method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrf() },
      body: JSON.stringify({ items: [{ id: outputId, channel: ch }] })
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        return (j && j.ok && j.runtimes) ? j.runtimes[outputId + '::' + ch] : null;
      })
      .catch(function () { return null; });
  }

  // '예약 상황' 블록 — 시작·종료·작동 시간을 한 줄씩. 예약이 여러 건이면 모두
  // 보여준다(취소 버튼도 각각). 지금 작동 중이면 그 사실을 위에 먼저 놓는다 —
  // 즉시 실행은 예약 목록에 남지 않으므로 여기 없으면 아무 흔적이 없다.
  function _schedStateHtml(rt) {
    var rows = (rt && rt.schedules) || [];
    var running = !!(rt && rt.elapsed_sec);
    var html = '<div class="aot-act-group-header">' + _esc(_t('Schedule status')) + '</div>';
    if (running) {
      html += '<div class="aot-ov-row"><span>' + _esc(_t('Running')) + '</span><span>' +
              _esc(_t('Elapsed')) + ' ' + _esc(_fmtDur(rt.elapsed_sec)) + '</span></div>' +
              '<div class="aot-wheel-actions" style="margin-top:6px">' +
              '<button type="button" class="btn aot-pill-btn aot-sched-off">' +
              _esc(_t('Turn off now')) + '</button></div>';
    }
    if (!rows.length) {
      if (!running) {
        html += '<div class="aot-ov-muted" style="text-align:center">' +
                _esc(_t('No schedule')) + '</div>';
      }
      return html;
    }
    rows.forEach(function (s) {
      html += '<div class="aot-ov-row"><span>' + _esc(_t('Start time')) + '</span><span>' +
              _esc(s.start || '—') + '</span></div>' +
              '<div class="aot-ov-row"><span>' + _esc(_t('End time')) + '</span><span>' +
              _esc(s.end || _t('no auto off')) + '</span></div>' +
              '<div class="aot-ov-row"><span>' + _esc(_t('Run time')) + '</span><span>' +
              _esc(s.duration_sec ? _fmtRunLen(s.duration_sec) : '—') + '</span></div>' +
              '<div class="aot-wheel-actions" style="margin-top:6px">' +
              '<button type="button" class="btn aot-pill-btn aot-sched-drop" data-job-id="' +
              _esc(String(s.job_id)) + '">' + _esc(_t('Cancel schedule')) +
              '</button></div>';
      // 서버가 상한을 넘겼다고 알려 주면 그 사실을 적는다 — 목록만 잘라 보이면
      // 화면이 "이게 전부" 라고 거짓말한다.
      if (s.more) {
        html += '<div class="aot-ov-muted" style="text-align:center">…</div>';
      }
    });
    return html;
  }

  // 블록 안의 [예약 취소]·[지금 끄기] 배선. 되돌린 뒤에는 서버를 다시 읽어
  // 블록을 그린다 — 클라이언트가 결과를 짐작해 그리면 실패한 취소가 성공처럼
  // 보인다.
  function _wireSchedState(stateEl, statusEl, outputId, channel, reload) {
    if (!stateEl || stateEl._wired) return;
    stateEl._wired = true;
    stateEl.addEventListener('click', function (e) {
      var drop = e.target.closest('.aot-sched-drop');
      var off  = e.target.closest('.aot-sched-off');
      if (!drop && !off) return;
      var btn = drop || off;
      btn.disabled = true;
      if (statusEl) statusEl.textContent = _t('Saving...');
      var pr = drop
        ? fetch('/api/v1/scheduler/jobs/' + encodeURIComponent(btn.dataset.jobId),
                { method: 'DELETE', headers: { 'X-CSRFToken': _csrf() } })
        : fetch('/api/geo/output/' + encodeURIComponent(outputId) + '/state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrf() },
            body: JSON.stringify({ state: false, channel: channel || 0 }) });
      pr.then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          if (statusEl) {
            statusEl.textContent = drop ? _t('Schedule canceled') : _t('Turned off');
          }
          refreshOutputScheduleLabel(outputId, channel);
          return reload();
        })
        .catch(function () {
          btn.disabled = false;
          if (statusEl) statusEl.textContent = _t('Failed');
        });
    });
  }

  // 예약을 저장·취소한 직후 그 장치의 '다음 예약'·시간 칸을 즉시 갱신한다.
  // 화면 세 곳(시설 모달·구역 모달·마커 팝업)이 같은 자리를 다르게 렌더하므로
  // 호출부마다 배선하지 않고 **문서 전체에서 그 키를 가진 칸**을 갱신한다.
  // 예약 라벨은 서버가 PENDING 잡을 보고 만들므로 저장 직후 값이 곧 정답이다.
  function refreshOutputScheduleLabel(outputId, channel) {
    if (!outputId) return Promise.resolve();
    var ch = parseInt(channel || 0, 10) || 0;
    var key = outputId + '::' + ch;
    return fetch('/api/geo/output_runtimes', {
      method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrf() },
      body: JSON.stringify({ items: [{ id: outputId, channel: ch }] })
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.ok) return;
        var rt = j.runtimes[key];
        document.querySelectorAll('.aot-act-rt[data-rt-key="' + key + '"]')
          .forEach(function (cell) {
            cell.innerHTML = nextRunHtml(rt);
            var row = cell.closest('.aot-act-row');
            if (row) { seedTimeSlot(row.querySelector('.aot-act-time'), rt); }
          });
      })
      .catch(function () {});
  }

  // 초 → "HH:MM:SS". 공용 AoTTime.formatDuration 을 그대로 쓴다 — 장치 마커
  // 팝업의 작동 시간 스톱워치와 같은 표기여야 하고, 시/분/초를 단어로 쓰면
  // 언어마다 msgid 가 세 개 더 생긴다.
  function _fmtDur(sec) {
    if (window.AoTTime && window.AoTTime.formatDuration) {
      return window.AoTTime.formatDuration(Math.max(0, Math.round(+sec || 0)));
    }
    var t = Math.max(0, Math.round(+sec || 0));
    var p = function (n) { return n < 10 ? '0' + n : String(n); };
    return p(Math.floor(t / 3600)) + ':' + p(Math.floor((t % 3600) / 60)) +
           ':' + p(t % 60);
  }

  function _buildActRow(sk, s, ct, canCtrl, lastCmd) {
    var _tr      = function (x) { return (window._ ? window._(x) : x); };
    var curPct   = s.percent != null ? parseFloat(s.percent) : (s.on ? 100 : 0);

    // ── ON/OFF binary: 1행 이름+토글 / 2행 작동·예약 시간 + [설정] ───────────
    // [설정] = 시작/종료 예약. on/off 장치에만 붙인다 — 개폐율(value)·PWM 은
    // "언제부터 언제까지 켬"이라는 duration 의미가 성립하지 않는다.
    if (ct === 'binary') {
      var bid = _slotIds(sk, s);
      return buildOutputRow({
        slot: sk,
        name: s.name || sk,
        drag: canCtrl,
        primary: canCtrl
          ? _slideToggle('aot-act-toggle-right', 'aot-act-toggle-input', sk, !!s.on)
          : '<span class="aot-act-val-ro aot-act-toggle-right ' +
            (s.on ? 'aot-act-on' : 'aot-act-off') + '">' +
            (s.on ? 'ON' : 'OFF') + '</span>',
        meta: timeSlotHtml({ outputId: bid.oid, channel: bid.ch,
                             runtime: s.runtime, on: !!s.on }) +
              nextRunHtml(s.runtime, bid.oid + '::' + bid.ch),
        settings: canCtrl ? _scheduleBtn(sk, s) : ''
      });
    }

    // ── Paired actuator (value): 닫힘/중지/열림 3버튼 (output 카드 스타일) ───
    if (ct === 'value') {
      var lastPct = s.last_target_pct != null ? parseFloat(s.last_target_pct) : null;
      var lastSrc = s.last_target_source || null;
      var info = _tr('Current') + ' ' + curPct.toFixed(0) + '%';
      if (lastPct !== null) {
        var srcLabel = lastSrc === 'manual' ? _tr('Manual')
                     : lastSrc === 'system' ? _tr('System')
                     : _tr('Target');
        info = srcLabel + ' ' + lastPct.toFixed(0) + '% · ' + info;
      }
      var btns = canCtrl
        ? '<div class="aot-act-3btn">' +
          '<button type="button" class="aot-act-pbtn' + (curPct <= 1 ? ' active' : '') +
          '" data-slot="' + _esc(sk) + '" data-action="close">' + _esc(_tr('Close')) + '</button>' +
          '<button type="button" class="aot-act-pbtn" data-slot="' + _esc(sk) +
          '" data-action="stop">' + _esc(_tr('Stop')) + '</button>' +
          '<button type="button" class="aot-act-pbtn' + (curPct >= 99 ? ' active' : '') +
          '" data-slot="' + _esc(sk) + '" data-action="open">' + _esc(_tr('Open')) + '</button>' +
          '</div>'
        : '';

      // 미세 개방률 조절용 3way 슬라이더 (버튼과 병행 — 현재 위치 dot 포함)
      var sliderHtml = '';
      if (canCtrl) {
        var cachedPct = (lastCmd && lastCmd[sk] !== undefined) ? lastCmd[sk] : null;
        var globalT = (window._aotActuatorTargetPct &&
                       window._aotActuatorTargetPct[sk.split('::')[0]] !== undefined)
                      ? window._aotActuatorTargetPct[sk.split('::')[0]] : null;
        var thumb = globalT !== null ? globalT
                  : cachedPct !== null ? cachedPct
                  : (lastPct !== null ? lastPct : curPct);
        sliderHtml = '<div class="aot-3way-slider-wrap">' +
                     '<input type="range" class="aot-3way-slider" min="0" max="100" step="1"' +
                     ' value="' + thumb.toFixed(0) + '"' +
                     ' data-slot="' + _esc(sk) + '" data-ct="value"' +
                     ' data-current="' + curPct.toFixed(0) + '"' +
                     ' style="--aot-current-pct:' + curPct.toFixed(0) + '%">' +
                     '<div class="aot-3way-current-dot"></div></div>';
      }

      return buildOutputRow({
        slot: sk,
        name: s.name || sk,
        drag: canCtrl,
        primary: btns,
        meta: '<span class="aot-act-val-current">' + _esc(info) + '</span>',
        settings: sliderHtml
      });
    }

    // ── PWM slider (기존 유지) ───────────────────────────────────────────────
    var globalTarget = (window._aotActuatorTargetPct &&
                        window._aotActuatorTargetPct[sk.split('::')[0]] !== undefined)
                       ? window._aotActuatorTargetPct[sk.split('::')[0]] : null;
    var thumbPct = globalTarget !== null ? globalTarget : curPct;
    var pid = _slotIds(sk, s);

    return buildOutputRow({
      slot: sk,
      name: s.name || sk,
      drag: canCtrl,
      primary: '<span class="aot-act-val">' + curPct.toFixed(0) + '%</span>',
      // 듀티가 0 보다 크면 돌고 있는 것이다 — PWM 도 "얼마나 돌았나"를 묻는다.
      meta: timeSlotHtml({ outputId: pid.oid, channel: pid.ch,
                           runtime: s.runtime, on: curPct > 0 }),
      settings: canCtrl
        ? '<input type="range" class="aot-act-slider" min="0" max="100" step="1"' +
          ' value="' + thumbPct.toFixed(0) + '"' +
          ' data-slot="' + _esc(sk) + '" data-ct="' + ct + '">'
        : ''
    });
  }

  // ── wire ──────────────────────────────────────────────────────────────────
  // Attach delegated listeners for actuator sliders and ON/OFF buttons inside
  // containerEl.  Designed for facility-level popups (vector widget).
  //
  //   onControl(slotKey, action, percent)  called on every user command
  //   lastCmdRef = { set(slot, val) }      optional slider-value cache
  function wire(containerEl, onControl, lastCmdRef) {
    // Live label update while dragging
    containerEl.addEventListener('input', function (e) {
      var el = e.target;
      if (!el.classList.contains('aot-act-slider') &&
          !el.classList.contains('aot-3way-slider')) return;
      var v   = parseFloat(el.value);
      var row = el.closest('.aot-act-row');
      var valEl = row && row.querySelector('.aot-act-val');
      if (valEl) valEl.textContent = v.toFixed(0) + '%';
    });

    // Command send on drag-end (+ 슬라이드 토글 on/off)
    containerEl.addEventListener('change', function (e) {
      var el = e.target;
      if (el.classList.contains('aot-act-toggle-input')) {
        var onState = el.checked;
        var bs = el.dataset.slot ? el.dataset.slot.split('::')[0] : null;
        if (bs) {
          window._aotActuatorTargetPct = window._aotActuatorTargetPct || {};
          window._aotActuatorTargetPct[bs] = onState ? 100 : 0;
        }
        if (lastCmdRef) lastCmdRef.set(el.dataset.slot, onState ? 100 : 0);
        onControl(el.dataset.slot, onState ? 'on' : 'off', null);
        return;
      }
      if (!el.classList.contains('aot-act-slider') &&
          !el.classList.contains('aot-3way-slider')) return;
      var val = parseFloat(el.value);
      // Global target value cache - shared with the device popup slider
      var baseSlot = el.dataset.slot ? el.dataset.slot.split('::')[0] : null;
      if (baseSlot) { window._aotActuatorTargetPct = window._aotActuatorTargetPct || {}; window._aotActuatorTargetPct[baseSlot] = val; }
      if (lastCmdRef) lastCmdRef.set(el.dataset.slot, val);
      onControl(el.dataset.slot, 'set', val);
    });

    // ON/OFF + 닫힘/중지/열림 buttons
    containerEl.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-action]');
      if (!btn || !btn.dataset.slot) return;
      var action = btn.dataset.action;
      var baseSlotBtn = btn.dataset.slot.split('::')[0];
      window._aotActuatorTargetPct = window._aotActuatorTargetPct || {};

      if (action === 'open' || action === 'close' || action === 'stop') {
        // Paired actuator: output 카드와 동일한 의미
        // (open → 100%, close → 0%, stop → 정지)
        if (action === 'open') {
          window._aotActuatorTargetPct[baseSlotBtn] = 100;
          if (lastCmdRef) lastCmdRef.set(btn.dataset.slot, 100);
          onControl(btn.dataset.slot, 'set', 100);
        } else if (action === 'close') {
          window._aotActuatorTargetPct[baseSlotBtn] = 0;
          if (lastCmdRef) lastCmdRef.set(btn.dataset.slot, 0);
          onControl(btn.dataset.slot, 'set', 0);
        } else {
          onControl(btn.dataset.slot, 'off', null);
        }
        var grp = btn.closest('.aot-act-3btn');
        if (grp) {
          grp.querySelectorAll('.aot-act-pbtn').forEach(function (b) {
            b.classList.toggle('active', b === btn && action !== 'stop');
          });
        }
        return;
      }

      // Legacy on/off buttons
      window._aotActuatorTargetPct[baseSlotBtn] = (action === 'on') ? 100 : 0;
      onControl(btn.dataset.slot, action, null);
      var wrap = btn.closest('.aot-act-toggle-wrap');
      if (wrap) {
        wrap.querySelectorAll('[data-action]').forEach(function (b) {
          b.classList.toggle('active', b === btn);
        });
      }
    });
  }

  // ── [현황] 탭 빌더들 ────────────────────────────────────────────────────────
  // env_summary(데몬 사이클 스냅샷) + status 를 4블록으로 요약 렌더.
  // 규격 정보는 의도적으로 배제 — "지금 무슨 일이 일어나는가"만.

  function _t(s) { return (window._ ? window._(s) : s); }

  // [현황] 표시 정책 상수 — 본문에 숫자를 직접 박지 않는다.
  var TREND_LOOKAHEAD_MIN = 15;   // 추세 선형 외삽 구간 (분)
  var TREND_DELTA_CAP     = 5;    // 외삽 표시값 상한 (과신 방지)

  // 값은 전역 번역 카탈로그의 영어 msgid — 출력 시 _t() 로 감싼다.
  var _MODE_LABELS = {
    cooling:      'Cooling', heating: 'Heating', humidify: 'Humidify',
    dehumidify:   'Dehumidify', co2_enrich: 'CO2 Enrichment',
    conservation: 'Conservation', emergency: 'Emergency',
    degraded:     'Partial Control', natural: 'Natural Ventilation',
    unattainable: 'Target Unattainable'
  };
  // ⚠ **서버가 두 어휘를 쓴다.** `limiting_factor` 는 'water' 라고 부르고
  // `commands[].var`(var_source)는 같은 축을 'vpd' 라고 부른다. 둘 다 여기
  // 담는다 — 예전에는 'water' 만 있어서 [시설 세부]의 근거 줄이 "목표를 좇는
  // 중 (vpd)" 처럼 내부 키를 그대로 노출했다.
  var _LIMIT_LABELS = {
    light: 'Light Level', co2: 'CO2', temperature: 'Temperature',
    water: 'Water (VPD)', vpd: 'Water (VPD)', humidity: 'Humidity'
  };
  // 액추에이터 종류 라벨. **키는 서버 어휘(`_KIND_CAPABILITIES`)와 같아야 한다** —
  // 예전에는 여기 'heating'/'cooling'/'humidifier' 라고 적혀 있어 서버가 보내는
  // heater/cooler/fogger 가 하나도 안 맞았고, 화면에 내부 키가 그대로 떴다
  // (커튼만 우연히 일치했다). 회귀는 `test_map_popup_kind_labels.py` 가 잡는다.
  var _KIND_LABELS = {
    opening: 'Opening', curtain: 'Curtain', shade: 'Shade',
    heater: 'Heater', cooler: 'Cooler', fogger: 'Fogger',
    co2_injector: 'CO2 Injector', lighting: 'Lighting',
    circulation_fan: 'Circulation Fan', exhaust_fan: 'Exhaust Fan',
    intake_fan: 'Intake Fan'
  };

  // 섹션 탭 내비 — [현황](동적) / [환경·제어](센서+제어) / [개요](정적)
  //
  // `secs` 를 넘기면 그 목록으로 그린다. 계층마다 탭 수가 달라도(식생은 아직
  // [환경·제어]가 없다) **내비 빌더는 하나여야 한다** — 계층별로 자기 내비를
  // 손으로 그리기 시작하면 탭 키·순서·클래스가 조용히 갈리고, 구역이 시설과
  // 탭을 맞추느라 한 번 겪은 일이 그대로 재발한다.
  function buildSectionNav(active, secs) {
    // 기본값의 마지막 탭 이름이 **'설정'** 인 것은 **구획 모달 기준**이다. 거기
    // 마지막 탭에 들어 있는 것은 이름·기간·프로그램·몫을 고치는 **편집 폼**이라,
    // '개요' 라는 이름은 "읽기만 하는 요약" 을 약속하고 배신한다.
    //
    // ⚠ **다른 계층은 이 기본값을 쓰면 안 된다.** 구역·대지·시설의 마지막 탭은
    // 기초 정보를 담는 자리이고(시설: 사진·크기·면적·용적·설명), 편집은 그
    // 옆에 붙은 버튼 몇 개다. 자주 볼 것이 아니라 마지막에 둔 것이지 "설정하러
    // 가는 곳" 이 아니다 — 셋 다 `secs` 로 'About' 을 넘긴다.
    // 규칙은 하나다: **편집 폼이 본체인 곳만 '설정'.**
    // (2026-08-26: 시설이 기본값을 쓰고 있어 같은 자리의 탭 이름이 계층마다
    //  갈려 있었다 — 구역·대지는 '개요', 시설·구획은 '설정'.)
    //
    // 키(`about`)는 그대로 둔다 — 위젯 옵션(`popup_default_tab`)에 저장된 값이라
    // 바꾸면 기존 대시보드가 존재하지 않는 탭을 요구하게 된다.
    secs = secs || [
      { key: 'overview', label: 'Overview' },
      { key: 'envctl',   label: 'Environment & Control' },
      { key: 'about',    label: 'Settings' }
    ];
    var html = '<div class="aot-act-tabs-nav aot-bay-popup-nav">';
    secs.forEach(function (s) {
      html += '<button type="button" class="aot-act-tab-btn' +
              (s.key === active ? ' active' : '') +
              '" data-sec="' + s.key + '">' + _esc(_t(s.label)) + '</button>';
    });
    return html + '</div>';
  }

  // ── 섹션 탭 전환 (구역·필지·베이·구획이 공유) ──────────────────────────
  // 셋이 각자 같은 토글을 들고 있었다. 탭을 하나 더 붙이거나 활성 표시 규칙을
  // 바꾸면 세 곳을 고쳐야 하는데, 한 곳을 빠뜨려도 **그 계층에서만** 달라 보여
  // 화면으로는 알아채기 어렵다.
  //
  // `navEl` 을 주면 그 안의 버튼만 토글한다 — 한 모달에 nav 가 둘 이상 있을 때
  // (베이) 남의 nav 까지 끄지 않기 위해서다. pane 은 언제나 모달 전체에서 고른다.
  function activateSection(scopeEl, key, navEl) {
    if (!scopeEl || !key) return;
    var btns = (navEl || scopeEl).querySelectorAll('.aot-act-tab-btn[data-sec]');
    Array.prototype.forEach.call(btns, function (b) {
      b.classList.toggle('active', b.dataset.sec === key);
    });
    Array.prototype.forEach.call(
      scopeEl.querySelectorAll('.aot-bay-popup-pane'), function (p) {
        p.style.display = (p.dataset.pane === key) ? '' : 'none';
      });
  }

  // 탭 전환 **말고는 할 일이 없는** 모달용 배선(필지). 전환 뒤에 다른 일이
  // 붙는 모달(구역·베이)은 자기 리스너 안에서 `activateSection` 만 부른다.
  function wireSectionTabs(scopeEl) {
    if (!scopeEl || scopeEl._sectionTabsWired) return;
    scopeEl._sectionTabsWired = true;
    scopeEl.addEventListener('click', function (e) {
      var btn = e.target.closest('.aot-bay-popup-nav .aot-act-tab-btn[data-sec]');
      if (!btn || !scopeEl.contains(btn)) return;
      activateSection(scopeEl, btn.dataset.sec, btn.closest('.aot-bay-popup-nav'));
    });
  }

  // ── 시설 대표사진 / 치수 / 설명 블록 (섹션탭 바로 아래, 현황 pane 최상단) ──
  //   info: GET /api/aot/facility/<uuid>/info 응답
  function _ovInfoBlocks(info) {
    if (!info || !info.ok) return '';
    var html = '';

    // 대표사진 + 등록/변경 버튼 (editor 이상)
    if (info.photo_url || info.can_edit) {
      html += '<div class="aot-ov-card-title">' + _esc(_t('Photo')) + '</div>' +
              '<div class="aot-ov-block aot-ov-photo-wrap">';
      if (info.photo_url) {
        html += '<div class="aot-ov-photo"><img src="' + _esc(info.photo_url) +
                '" alt="" loading="lazy"></div>';
      }
      if (info.can_edit) {
        html += '<div class="aot-ov-photo-actions">' +
                '<input type="file" class="aot-ov-photo-input" accept="image/*"' +
                ' style="display:none">' +
                '<button type="button" class="aot-ov-pill aot-ov-photo-btn">' +
                _esc(info.photo_url ? _t('Change Photo') : _t('Add Photo')) +
                '</button></div>';
      }
      html += '</div>';
    }

    // 시설 정보: 크기 / 면적 / 부피(추정)
    var d = info.dims || {};
    var rows = '';
    function _row(label, val) {
      return '<div class="aot-ov-row"><span>' + _esc(label) + '</span><span>' +
             _esc(val) + '</span></div>';
    }
    if (d.span_width_m && d.length_m) {
      var size = d.span_width_m + ' × ' + d.length_m + ' m';
      if (d.ridge_height_m) size += ' · H ' + d.ridge_height_m + ' m';
      if (d.bay_count > 1) size += ' · ' + d.bay_count + ' ' + _t('bays');
      rows += _row(_t('Dimensions'), size);
    }
    if (d.area_m2)   rows += _row(_t('Area'), d.area_m2 + ' m²');
    if (d.volume_m3) rows += _row(d.estimated ? _t('Interior Volume (est.)') : _t('Interior Volume'),
                                  d.volume_m3 + ' m³');
    if (rows) {
      html += '<div class="aot-ov-card-title">' +
              _esc(_t('Facility Information')) + '</div>' +
              '<div class="aot-ov-block aot-ov-dims">' + rows + '</div>';
    }

    html += buildDescriptionHtml(info.description, info.can_edit);
    return html;
  }

  // ── 곧 닥칠 기상 위험 ────────────────────────────────────────────────
  //
  // **시설과 노지가 같은 렌더러를 쓴다.** 같은 사실을 계층마다 다른 문장으로
  // 적으면 사용자는 그것이 다른 이야기인 줄 안다. 판정도 서버 한 곳이다
  // (`weather_hazards`, 제어가 읽는 예보와 같은 파일).
  //
  // 낡은 예보로는 아무 말도 하지 않는다 — 6개월 지난 예보로 "오늘 밤 서리"
  // 라고 말하면 사람은 그 말을 믿고 행동한다.
  var _HAZARD_LABELS = {
    freeze: 'Freezing', frost: 'Frost', heat: 'Extreme heat',
    wind: 'Strong wind', heavy_rain: 'Heavy rain', rain: 'Rain', snow: 'Snow'
  };

  function buildHazardsHtml(hz) {
    var items = (hz && hz.items) || [];
    if (!items.length) return '';
    var rows = items.map(function (h) {
      var when = h.in_h <= 0
        ? _t('now')
        : _t('in %(n)s h').replace('%(n)s', String(h.in_h));
      var val = (h.value != null)
        ? ' · ' + (+h.value).toFixed(h.unit === 'm/s' ? 1 : 0) + (h.unit || '')
        : '';
      return '<div class="aot-ov-row aot-hz aot-hz--' + _esc(h.severity) +
             '"><span>' + _esc(_t(_HAZARD_LABELS[h.kind] || h.kind)) +
             '</span><span>' + _esc(when + val) + '</span></div>';
    }).join('');
    return '<div class="aot-ov-card-title">' + _esc(_t('Coming weather')) +
           '</div><div class="aot-ov-block aot-ov-hazards">' + rows + '</div>';
  }

  // ── 마지막 관수 ──────────────────────────────────────────────────────
  //
  // "오늘 물을 줬던가" 는 화면을 열자마자 답이 나와야 하는 질문이다. 시설·노지가
  // **같은 한 줄**을 쓴다 — 판정도 서버 한 곳(`irrigation_status`).
  //
  // 근거가 없으면(무엇이 관수인지 모르면) 아무것도 그리지 않는다. 그때
  // "기록 없음" 이라고 적으면 사용자는 장치가 안 돈 줄 안다.
  function buildIrrigationHtml(irr) {
    if (!irr) return '';
    var right;
    if (irr.at == null) {
      right = _t('no run in the last 30 days');
    } else {
      var h = irr.hours_ago;
      var when = (h != null && h < 1)
        ? _t('%(n)s min ago').replace('%(n)s', String(Math.max(1, Math.round(h * 60))))
        : _t('%(n)s h ago').replace('%(n)s',
              String(h != null ? (h < 24 ? Math.round(h) : Math.round(h / 24) * 24) : '?'));
      right = when;
      if (irr.duration_s) {
        right += ' · ' + _t('%(n)s min').replace(
                   '%(n)s', String(Math.max(1, Math.round(irr.duration_s / 60))));
      }
    }
    // ── 이름은 그 장치가 **실제로 하는 일**을 따른다 (2026-08-26) ──────────
    // 관수 목록은 fitting 종류(`irrigation_valve`)만 보므로, 습윤형 스프링클러가
    // 달린 밸브도 여기 잡힌다. 그런데 환경 제어는 같은 장치를 **가습기**로
    // 쓴다 — "마지막 관수 밸브3" 이라고 적으면 가습용으로 설정해 둔 사용자가
    // 자기가 무엇을 설정했는지 의심하게 된다. 서버가 노즐로 판정한
    // `wetting` 을 그대로 따른다.
    //
    // 한 줄짜리 블록이다 — 제목을 따로 두면 "마지막 분무 / 마지막 분무" 가 된다.
    return '<div class="aot-ov-block aot-ov-row aot-ov-irrigation"><span>' +
           _esc(irr.wetting ? _t('Last misting') : _t('Last watering')) +
           (irr.device ? ' <span class="aot-ov-muted">' + _esc(irr.device) +
                         '</span>' : '') +
           '</span><span>' + _esc(right) + '</span></div>';
  }

  // buildOverviewSection(env, status, opts)
  //   env    GET /api/aot/facility/<uuid>/env_summary 응답
  //   status GET /api/aot/facility/<uuid>/status 응답 (null 허용)
  //   opts   { canToggle: bool, info: /info 응답, facilityName: str }
  function buildOverviewSection(env, status, opts) {
    opts = opts || {};
    var fn      = env && env.function;
    var summary = env && env.summary;
    var stale   = !env || env.stale;
    var html    = '';

    // 자동 제어를 켜고 끄는 토글은 여기 두지 않는다. 붙이고 켜는 것은 시설
    // 설정에서 하는 일이고, [현황]은 "지금 어떤가" 만 말한다 — 응답이 없다는
    // 것은 상태이므로 아래에 남는다.
    if (!fn) {
      return html + _ovNotesBlock();
    }

    // 목표는 **현재값 옆**에 붙는다(`buildEnvNowHtml`). 목표만 따로 표로
    // 늘어놓으면 "그래서 지금 맞나" 에 답하지 못한 채 칸만 차지한다.
    // 전체 목표 목록은 그것을 정하는 곳(함수 설정)에서 본다.

    // ── 게이트로 멈춘 것은 **응답 없음이 아니다** (2026-08-26) ─────────────
    // 안전 게이트가 걸리면 코디네이터는 L1~L3 앞에서 반환하므로 요약의 환경
    // 값이 갱신되지 않는다. 그것을 "응답 없음" 으로 읽으면, 가장 알려야 할
    // 순간에 화면이 정반대를 말한다 — 제어는 매 사이클 정상 실행 중이고
    // 이유도 분명한데(비·돌풍·폭염) 사용자는 고장으로 읽는다. 게다가 **진짜로
    // 죽었을 때와 구분되지 않는다**(실측: 강우 게이트 45분).
    // 서버가 `gate_only` 로 그 사실을 실어 보낸다.
    var gateOnly = summary && summary.gate_only;
    if (gateOnly) {
      var g = summary.gate || {};
      var why = (g.reasons || []).map(function (r) {
        return _t(_GATE_REASON_TEXT[r] || r);
      }).join(' \u00b7 ') || _t('A safety gate is holding the controls');
      html += '<div class="aot-ov-card-title">' + _esc(_t('Automatic control')) +
              '</div><div class="aot-ov-block">' +
              '<div class="aot-ov-why aot-ov-gate">' + _esc(why) + '</div>' +
              // 환경 값이 이 사이클의 것이 아님을 말한다 — 안 말하면 낡은
              // 값을 지금 값으로 읽는다.
              // ⚠ **'아래' 라고 쓰지 말 것.** 이 카드는 [환경] **뒤**에 오므로
              //   가리키는 방향이 반대다. 게다가 카드 순서는 시설 구성에 따라
              //   달라진다 — 위치를 가리키는 말은 언젠가 틀린다(2026-08-26).
              '<div class="aot-ov-muted">' +
              _esc(_t('Environment readings were taken just before this.')) +
              '</div></div>';
      return html + _ovNotesBlock();
    }

    if (stale || !summary) {
      var msg = !fn.active ? _t('Automatic control inactive')
                           : _t('Automatic control not responding (no cycle in 5 minutes)');
      html += '<div class="aot-ov-card-title">' + _esc(_t('Automatic control')) +
              '</div><div class="aot-ov-block aot-ov-inactive">' +
              '<div class="aot-ov-muted">' + _esc(msg) + '</div>';
      var rs = (status && status.reasons) || [];
      if (rs.length) {
        html += '<div class="aot-ov-reasons">' + rs.map(_esc).join('<br>') + '</div>';
      }
      return html + '</div>' + _ovNotesBlock();
    }

    // 날짜는 [현황]에 두지 않는다. 시작일은 [구획] 의 기간 축이 보이고,
    // 제어 종료일은 설정이다 — 그 날이 지나 실제로 멈추면 아래 "응답 없음 ·
    // 비활성" 이 말한다. 남은 날수는 오늘 할 일을 바꾸지 않는다.

    // ── 상태 요약 블록은 없앴다 ──────────────────────────────────────────
    // "유지 · 일부만 제어" 는 내부 운전 모드 어휘라 뜻이 전달되지 않았다.
    // 그 블록에서 값이 있던 셋은 각자 제 자리로 갔다:
    //   편차     → 현재값 옆(`buildEnvNowHtml`)
    //   센서 결함 → 현재 블록 머리("센서 응답 4/5")
    //   안전 게이트 → 제어 상태 블록 맨 위(제어가 막힌 이유이므로)
    // 추세·예보 선행은 제어 내부 사정이라 [현황]에서 뺐다.

    // 광합성 지표는 [환경] 카드가 함께 낸다(`buildEnvNowHtml`) — 그 줄들도
    // 전부 "지금 값 / 목표" 라 같은 질문에 답한다. 카드를 갈라 두면 사용자가
    // 환경 하나를 읽으려고 두 카드를 오가야 했다(2026-08-26 지적).

    // ── 블록 3: 제어 상태 (환기/팬/커튼 등 의미 단위) ───────────────────
    // 제목 옆 [설정] — 감출 수 있는 것은 아래 **환기 면적·장치 개도**뿐이다.
    // 편차·안전 게이트는 목록에 없다(`controlRowChoices` 주석).
    // 감출 항목이 없으므로 [설정] 버튼도 없다 — 아래 둘(못 따라감·안전
    // 게이트)은 목록에 넣지 않는다(`controlRowChoices` 주석).
    var _strain0 = summary.strain;
    var _gate0   = summary.gate || {};
    var _hasCtrl = !!((_strain0 && _strain0.var) || _gate0.triggered);
    if (_hasCtrl) {
    html += '<div class="aot-ov-card-title">' +
            _esc(_t('Control Status')) + '</div>' +
            '<div class="aot-ov-block aot-ov-ctrl">';
    // **설비가 못 따라가고 있으면 그렇다고 말한다.** "냉각기 100%" 만 보여
    // 주면 그것이 좋은 신호인지 나쁜 신호인지 알 수 없다 — 최대로 밀고 있는데도
    // 편차가 안 줄면 사람이 할 판단(차광을 더 치든, 목표를 낮추든)이 생긴다.
    var strain = summary.strain;
    if (strain && strain.var) {
      var vlabel = _t(_LIMIT_LABELS[strain.var] ||
                      { temperature: 'Temperature', humidity: 'Humidity',
                        vpd: 'Water (VPD)', co2: 'CO2' }[strain.var] || strain.var);
      var msg2;
      if (strain.reason === 'no_actuator') {
        msg2 = _t('%(var)s is off target and there is no device here that can move it')
                 .replace('%(var)s', vlabel);
      } else if (strain.reason === 'limit_breached') {
        // ⚠ '목표를 못 따라간다' 가 아니다. 이 변수는 제어 목표가 아니라
        //   사용자가 정한 **선**이고(VPD 직접 제어 모드), 제어 중심은 그
        //   방향을 요구하지 않고 있을 수 있다 — 그래도 선을 넘은 채라는
        //   사실은 말해야 한다(2026-08-26).
        msg2 = _t('%(var)s has been past the limit you set for %(min)s min')
                 .replace('%(var)s', vlabel)
                 .replace('%(min)s', String(Math.round((strain.since_s || 0) / 60)));
      } else {
        var kindNames = (strain.kinds || []).map(function (k) {
          return _t(_KIND_LABELS[k] || k);
        }).join(' · ');
        msg2 = _t('%(kinds)s at full output for %(min)s min, %(var)s still off target')
                 .replace('%(kinds)s', kindNames)
                 .replace('%(min)s', String(Math.round((strain.since_s || 0) / 60)))
                 .replace('%(var)s', vlabel);
      }
      // ⚠ **문장은 값이 아니다.** `.aot-ov-row` 는 「이름 | 값」 두 칸이라
      //   오른쪽 칸이 우측 정렬로 접힌다 — 긴 문장을 넣었더니 "수분(VPD)가
      //   목표를 벗어났는데 이를 / 움직일 장치가 없습니다" 로 들쭉날쭉하게
      //   찢어졌다(2026-08-26 영양 지적). 설명 문구는 [시설 세부]가 쓰는
      //   `.aot-ov-why` 하나로 통일한다 — 같은 성격의 글이 화면마다 다른
      //   모양으로 서면 사용자는 둘이 다른 것인 줄 안다.
      // ⚠ **'못 따라감' 이라는 앞말을 다시 붙이지 말 것.** 두 칸이던 시절의
      //   이름 칸이었는데, 한 문단이 된 뒤로는 뒤 문장이 이미 같은 말을 하고
      //   있어 "못 따라감 · …가 목표를 벗어났지만…" 처럼 겹쳐 읽힌다
      //   (2026-08-26 지적). 무슨 카드인지는 제목이 말한다.
      html += '<div class="aot-ov-why aot-ov-strain">' + _esc(msg2) + '</div>';
    }

    // 안전 게이트가 걸렸으면 **맨 위**에 말한다 — 아래 숫자들이 왜 그런지의
    // 이유이고, 사람이 지금 알아야 할 것도 그것이다(바람 때문에 창을 못 연다).
    var gate = summary.gate || {};
    if (gate.triggered) {
      // 설명이 없을 때 '활성' 만 적으면 문장이 아니다 — 상태 칸이던 시절의
      // 낱말이라 한 문단 안에서는 뚝 끊긴다(2026-08-26 지적).
      html += '<div class="aot-ov-why aot-ov-gate">' +
              (gate.description
                 ? _esc(_t('Safety Gate')) + ' \u00b7 ' + _esc(gate.description)
                 : _esc(_t('A safety gate is holding the controls'))) + '</div>';
    }
    // ── 환기 면적도 [시설 세부]로 옮겼다 (2026-08-26) ─────────────────────
    // "831.7 / 831.7 m²" 를 3초에 읽고 판단할 사람은 없다. 그 숫자가 필요해
    // 지는 것은 "왜 더 못 여나" 를 물을 때이고, 그 질문에 답하는 자리는
    // 장치별 근거가 있는 [시설 세부]다.
    //
    // 그래서 이 카드에는 **문제 신호만** 남는다 — 못 따라감과 안전 게이트.
    // 둘 다 없으면 카드 자체가 나오지 않는다. 이상이 없다는 것을 굳이 한 줄로
    // 적으면, 매번 읽어야 하는 줄이 하나 늘 뿐 판단은 바뀌지 않는다.
    var V = window.AoTViz;
    html += '</div>';
    }

    return html + _ovNotesBlock();
  }


  // ── [시설 세부] 탭 ─────────────────────────────────────────────────────────
  // [현황]이 "지금 괜찮은가" 를 3초에 답하는 자리라면, 여기는 **"왜 이렇게 하고
  // 있나"** 를 묻고 들어오는 자리다. 이상할 때만 열린다.
  //
  // 이 탭이 생기기 전, 서버는 매 사이클 `commands[]`(장치별 개도 + **근거코드**
  // + 어느 변수 때문인지)를 브라우저까지 보내 놓고 화면은 통째로 버리고 있었다.
  // 그래서 "냉방기 100%" 는 보이는데 **왜** 100% 인지는 로그를 파야 알 수 있었다.
  //
  // 모드·제한인자는 여기에도 두지 않는다 — 2026-08-20 에 [현황]에서 걷어낸
  // 이유가 "내부 운전 모드 어휘라 뜻이 전달되지 않는다" 였고, 탭을 옮긴다고
  // 그것이 해결되지 않는다. 같은 정보를 전달 가능한 형태로 주는 방법이
  // **근거코드를 문장으로 푸는 것**이다.

  // 근거코드 → 사람이 읽는 문장. 키는 `log_channels.REASON_*` 와 같아야 한다.
  // ⚠ 숫자를 그대로 노출하지 않는다. 모르는 코드는 줄 자체를 비운다 —
  // "근거 15" 라고 적으면 사용자는 그것이 오류 코드인 줄 안다.
  // ⚠ **정상 동작에는 근거를 적지 않는다.** 0·1·2(범위 안·목표 추종·보조)는
  // 제어기가 당연히 하는 일이라, 적어 봐야 "그렇게 작동하는 게 당연한데" 로
  // 읽힌다(2026-08-26 지적). 여기 남는 것은 **뜻밖의 이유**뿐이다 — 왜 안
  // 움직이나, 왜 막혔나, 왜 반대인가. 그것이 이 카드가 답할 질문이다.
  // 안전 게이트 사유 → 문장. 서버는 코드(`rain`·`wind` …)를 보내고 화면이
  // 번역한다 — 이어 붙은 문자열을 그대로 그리면 번역할 수 없다.
  // ⚠ 여기 없는 코드가 오면 코드가 그대로 보인다. `safety_gates` 에 사유를
  //   추가하면 이 표에도 넣을 것(`test_map_popup_labels` 가 고정한다).
  var _GATE_REASON_TEXT = {
    rain:                 'Rain — vents closed',
    wind:                 'High wind — vents closed',
    ext_context_expired:  'Outdoor readings expired — holding position',
    int_sensor_expired:   'Indoor readings expired — holding position',
    heat_emergency:       'Extreme heat — everything is being used to cool',
    cold_emergency:       'Extreme cold — everything is being used to warm',
    nursery_fog_sunburn:  'Misting is locked out to avoid leaf scorch',
    // ⚠ **`nursery_fog_sunburn` 과 뭉치지 말 것.** 습윤형 분무 잠금은 사유가
    //   둘이다 — 광량 임계(진짜 일소)와 저녁 시간대(잎마름병 방지, 광량과
    //   무관)는 동시에 참일 이유가 없다. 뭉치면 비 오는 밤에도 "햇빛에 잎이
    //   델 수 있어" 가 나간다(2026-08-28 사용자 지적 — 실제로 그렇게 나갔다:
    //   강우+저녁 차단이 겹친 사이클에서 두 안내가 나란히 떴다).
    nursery_fog_evening:  'Misting is locked out overnight to keep leaves dry'
  };

  var _REASON_TEXT = {
    10: 'Running it would move this the wrong way',
    11: 'It would upset another reading',
    12: 'A safety gate is holding this',
    13: 'The last command did not reach the device',
    14: 'A safety gate adjusted this',
    // ⚠ 15 는 `REASON_NO_GRADIENT` — "구동력 없음, 내외부 차이 부족으로
    //   효과 없음" 이다. 예전 문구('Doing all it can here' = "할 수 있는 만큼
    //   하고 있습니다")는 **뜻이 반대**였다. 그 장치는 애쓰고 있는 것이 아니라
    //   지금 아무 효과가 없어서 안전 위치로 물러나는 중이다(2026-08-26 지적).
    //   최대 출력에 닿아 있는 경우는 `_REASON_TEXT_FULL[15]` 가 따로 말한다.
    15: 'Nothing this device can change right now',
    16: 'Holding position until the outdoor reading returns',
    // ⚠ 15 와 뭉치지 말 것 — 15 는 "밀어도 안 움직인다", 17 은 "지금 밀
    //   방향이 아니다" 다. 0% 로 쉬는 난방기에게 15 의 문구("할 수 있는 만큼
    //   하고 있습니다")를 붙이면 정반대의 말이 된다(2026-08-26).
    17: 'Resting — the opposite direction is needed right now',
    // ⚠ 1(PRIMARY)과 뭉치지 말 것 — 1 은 "지금 이 편차가 이 값을 시킨다" 인데
    //   18 은 **아무도 밀고 있지 않다**. 목표를 지나쳐 있어 스스로 물러나는
    //   중이다. 뭉쳐 있던 동안 화면은 "적정 VPD 인데 냉방 100%" 를 PRIMARY 로
    //   설명했고, 그래서 왜 그런지 아무도 알 수 없었다(2026-08-26 영양).
    18: 'Target reached — easing off',
    // ⚠ 15 와 뭉치지 말 것 — 15 는 "밀어도 안 움직인다" 이고 19 는 "지금은
    //   열지 않기로 했다" 다. 뒤는 사용자가 켠 옵션의 결과이므로 화면이 그렇게
    //   말해야 "왜 밤에 창이 안 열리나" 에 답이 있다.
    19: 'Closed for the night — heating and cooling take over',
    20: 'Set by hand',
    // ── 오버라이드가 값을 바꾼 경우 ───────────────────────────────────────
    // 서버가 **값과 같은 시점의 근거**를 보낸다(`_build_cycle_summary`).
    // 이 키들은 숫자가 아니라 문자열이다 — 코디네이터 밖에서 정해진 값이라
    // 근거코드 체계를 공유하지 않는다.
    // ⚠ 여기 없는 이름이 오면 화면은 아무 설명도 못 한다. 서버에서 새 강제를
    //   만들면 이 표에도 넣을 것(`test_map_popup_labels` 가 고정한다).
    temp_max:  'Indoor temperature is over the limit you set',
    temp_min:  'Indoor temperature is under the limit you set',
    humid_max: 'Humidity is over the limit you set',
    humid_min: 'Humidity is under the limit you set',
    light_max: 'Light is over the limit you set',
    light_min: 'Light is under the limit you set',
    nursery_fog_derate: 'Easing off the misting as the sun climbs',
    fog_humidity_ceiling: 'Humidity is already high, so the misting is held'
  };
  // 같은 근거라도 **어디에 서 있느냐**로 뜻이 갈린다. 창이 활짝 열린 채
  // "쓸 만한 차이가 없음" 이라고 적으면 장치가 일하기 싫어하는 것처럼 읽힌다
  // — 실제로는 **최대로 밀고 있는데 그 이상 낼 것이 없는** 상태다
  // (2026-08-26 지적). 반대로 닫혀 있으면 "지금 움직여도 소용없다" 가 맞다.
  var _FULL_OUTPUT_PCT = 95.0;
  var _REASON_TEXT_FULL = {
    15: 'Fully open and giving all it can'
  };
  // 근거를 한 번 더 풀어야 뜻이 서는 것.
  var _REASON_HINT = {
    16: 'Opening or closing on a guess would do more harm than waiting'
  };

  /* 시설 세부 — env_summary 를 근거 중심으로 편다.
   *   env  GET /api/aot/facility/<uuid>/env_summary 응답
   *   opts { } (예약)
   */
  function buildFacilityDetailSection(env, opts) {
    opts = opts || {};
    // 장치 이름·실제 개도는 **런타임 상태**(`/runtime` actuator_states)에 있고
    // 명령·근거는 **요약**(env_summary)에 있다. 둘을 잇는 키가 다르다 —
    // 런타임은 slot_key 또는 **전체 uuid**, 요약은 slot_key 또는 **uuid 앞 8자**
    // 다(`p.slot_key || p.actuator_id[:8]`). 그래서 접두로 잇는다.
    // ⚠ 서버가 두 어휘를 쓰는 한 여기서 한 번만 잇는다 — 잇는 코드가 두 벌이
    // 되면 한쪽만 고쳐진 채로 이름이 빈 화면이 나온다.
    var states = opts.states || {};
    var byPrefix = {};
    Object.keys(states).forEach(function (k) {
      byPrefix[k] = states[k];
      var u = states[k].output_uuid;
      if (u) byPrefix[String(u).slice(0, 8)] = states[k];
    });
    function _live(slotKey) {
      return byPrefix[slotKey] || null;
    }
    var summary = env && env.summary;
    var stale   = !env || env.stale;
    if (!summary || stale) {
      // [현황]이 이미 "응답 없음" 을 말한다 — 여기서 또 말하면 같은 사실이
      // 두 탭에서 두 번 나온다. 비어 있다는 것만 조용히 알린다.
      return _emptyBlock(_t('Facility detail'),
                        _t('No control cycle to explain yet.'));
    }
    var V = window.AoTViz;
    // ── 게이트로 멈춘 사이클도 **설명할 것이 있다** (2026-08-26) ────────────
    // 안전 게이트는 L1~L3 를 건너뛰므로 목표·편차가 없다. 그렇다고 "설명할
    // 제어 사이클이 없습니다" 는 틀린 말이다 — 장치들이 지금 그 값인 이유가
    // 어느 때보다 분명하다(비가 와서 닫았다). 그 문장을 맨 위에 두고, 아래는
    // 평소대로 장치별로 편다(게이트가 강제한 명령이 `commands` 에 있다).
    // ⚠ **게이트 안내를 여기 두지 말 것** (2026-08-26 지적).
    // [현황]이 이미 같은 문장을 말한다. 여기 한 번 더 얹으면 같은 사실이 두
    // 탭에서 두 번 나오는데, 이 탭에는 그 문장을 뒷받침할 맥락이 없어
    // "설명 없이 놓인 문구" 로 읽힌다. 중요한 안내가 설 자리는 [현황]이다.
    // 이 탭에서 장치가 왜 그 값인지는 **각 카드의 근거**가 말한다
    // (`_reasonNote` → reason 12 "안전 게이트가 잡고 있습니다").
    var html = '';

    // ── 장치별 근거 ─────────────────────────────────────────────────────────
    // [현황]의 '장치별 개도' 는 **종류별 평균**(outputs_by_kind)이라 "개구부
    // 100%" 까지만 말한다. 여기는 **장치 하나하나**다 — 측창 우는 100%인데
    // 천창은 0% 인 것, 그리고 그 차이의 이유가 이 자리에서만 보인다.
    // "열린 면적 / 전체 면적" 한 조각 — 시설 합계와 장치별 줄이 **같은 모양**을
    // 쓴다. 두 곳이 따로 문자열을 만들면 소수 자릿수와 단위 위치가 갈린다.
    function _areaText(open_m2, total_m2) {
      if (!(total_m2 > 0)) return '';
      return open_m2.toFixed(1) + ' / ' + total_m2.toFixed(1) + ' m\u00b2';
    }

    /* on/off 장치의 작동 시간과 **그것을 견줄 기준**.
     *
     * ⚠ "24시간 중 0.6시간" 은 아무 말도 하지 않는다 — 난방기의 하루 0.6시간은
     *   여름이면 흔한 일이고 겨울이면 고장 신호다. 24시간은 비교 기준이 아니라
     *   그냥 하루의 길이다(2026-08-26 지적). 기준은 **그 장치 자신의 최근
     *   실적**에서 온다(서버 `_history_cached`).
     *
     * ⚠ **이 줄에서 "지금 켜졌나" 는 값이 아니다.** 줄 전체가 "얼마나 일했나"
     *   를 답하는데 1행만 순간 상태(켜짐/꺼짐)를 말하면, 값과 축이 서로 다른
     *   것을 가리킨다(2026-08-26 지적). 켜짐 여부는 [환경·제어] 탭의 토글과
     *   하단 독이 이미 말한다.
     *
     *     1행 값   = 오늘 누적 작동 시간
     *     초록     = 왼쪽부터 **평소(최근 7일 일평균)** 까지 채운 길이
     *     세로선   = 오늘 누적       — 초록 끝보다 왼쪽이면 평소보다 덜 돌았다
     *     축의 끝  = 기준을 **올림**한 시간 (오늘이 더 크면 오늘을 올림)
     *     3행      = 왼쪽 마지막 작동 · 오른쪽 "평소 N시간"
     *
     * ⚠ **밴드다, 불릿이 아니다.** 이 모달의 환경 줄이 전부 밴드라 사용자는
     *   초록을 "기준", 세로선을 "지금" 으로 읽는다. 불릿(막대=값, 눈금=목표)
     *   으로 그렸더니 정확히 **반대로** 읽혔다(2026-08-26 지적).
     *
     * ⚠ 기준을 눈금 위 라벨로 따로 세우지 말 것 — 3행에 왼쪽·오른쪽이 이미
     *   있어 가운데 절대배치 라벨을 더하면 셋이 포개진다("평소 2.8시간 시간").
     *
     * ⚠ 기준이 없으면(기록 2일 미만) **축을 그리지 않는다.** 없는 축을 지어내면
     *   바로 그 24시간짜리 거짓말로 되돌아간다. 그때는 누적 시간만 적는다.
     */
    function _dutyOf(lv) {
      if (!lv || lv.duty_24h_s == null) return null;
      var h = Number(lv.duty_24h_s) / 3600;
      if (lv.duty_avg_s == null) {
        return { h: h, hasBase: false, note: '' };
      }
      var avgH = Number(lv.duty_avg_s) / 3600;
      // 축의 끝은 **올림한 시간**이다 — 2.8시간이면 3시간. 눈금이 딱 떨어져야
      // 길이를 어림할 수 있고, 오늘이 기준을 넘으면 축도 따라 올라간다
      // (고정 축이면 세로선이 축을 뚫고 나가 얼마나 넘었는지가 안 보인다).
      var axisH = Math.max(1, Math.ceil(Math.max(avgH, h)));
      return { h: h, avgH: avgH, axisH: axisH, hasBase: true,
               note: _t('usually %(h)s h').replace('%(h)s', avgH.toFixed(1)) };
    }

    // 환기 면적 — 개구부 총량 대비 열린 면적. 장치별 개도(그 장치가 몇 %)와
    // **다른 값**이라 라벨로 구분한다.
    function _ventRows() {
      var v = summary.vent || {};
      if (!(v.total_area_m2 > 0)) return [];
      // ⚠ 줄의 골격은 셋이 같다(components/aot-dataviz.css):
      //   1행 이름 + **지금 값**  ·  2행 트랙  ·  3행 범위·기타
      // 전에는 "/ 831.7 m² · 100%" 를 1행 값 옆(valueSub)에 붙였는데, 그것은
      // 지금 값이 아니라 **축과 비율**이라 3행 몫이다 — 다른 줄과 골격이
      // 갈렸다(2026-08-26 지적).
      // 1행은 **비율**이다 — 다른 줄이 전부 %로 서므로 여기만 m² 를 크게
      // 적으면 눈이 한 번 더 환산해야 한다. 실제 면적은 3행 오른쪽에 둔다
      // (장치별 줄도 같은 구성이다 — `_areaNote`).
      var eff = (v.effective_area_m2 != null ? v.effective_area_m2 : 0);
      return [V
        ? V.bullet({ label: _t('Vent area open'),
                     value: eff, min: 0, max: v.total_area_m2,
                     valueText: (v.open_ratio_pct != null
                                 ? v.open_ratio_pct.toFixed(0)
                                 : (eff / v.total_area_m2 * 100).toFixed(0)),
                     valueSub: '%',
                     scaleNote: _areaText(eff, v.total_area_m2) })
        : _pRow(_t('Vent area open'), _esc(_areaText(eff, v.total_area_m2)))];
    }

    // 그 장치가 **지금 실제로** 몇 %인가 — 명령이 아니라 상태다.
    //
    // ⚠ **on/off 장치는 `percent` 가 null 이다.** 데몬이 돌려주는 상태가
    //   'on'/'off' 문자열이라 서버가 숫자로 못 바꾼다(routes_geo 의 `pct`).
    //   그것을 "모름" 으로 두고 명령값으로 폴백했더니 **꺼져 있는 냉방기가
    //   100% 로 보였고**(2026-08-26 지적), 같은 폴백을 쓰던 요약과 설명문도
    //   "3대 중 2대 가동" · "난방과 냉방이 서로 맞서고 있다" 를 함께 지어냈다.
    //   켜짐 여부는 `on` 이 말한다.
    // ⚠ **판정을 여기 하나로 둔다.** 네 자리가 각자 폴백을 들고 있어서, 장치
    //   줄만 고쳤을 때 그 줄은 0% 인데 바로 위 요약은 "가동 중" 이라고 말했다 —
    //   같은 카드 안에서 서로 다른 답이 나온 셈이다.
    function _actualOf(lv) {
      if (lv && lv.percent != null) return Number(lv.percent);
      if (lv && typeof lv.on === 'boolean') return lv.on ? 100 : 0;
      return null;
    }

    // ── 집계 막대는 **같은 단위로 더해지는 무리**에만 ────────────────────
    // 환기에는 '열린 환기 면적' 이 있다 — 창 셋의 개도는 m² 로 실제로 더해지고,
    // 그 합이 곧 물리량이다. 냉난방·가습은 그렇지 않다: 난방기·냉방기·가습기는
    // 공통 단위가 없어서 셋을 하나로 뭉치면 아무것도 가리키지 않는다.
    //
    // 예전에는 여기에 '가동 출력' 이라는 막대가 있었고 값은 **지금 개도의 평균**
    // 이었다. on/off 장치는 0 아니면 100 이라, 난방기 하나가 켜진 상태가
    // "33%" 로 나왔다 — 셋이 3분의 1씩 돌고 있다는 뜻으로 읽히지만 그런 일은
    // 일어나지 않았다(2026-08-26 지적). 지금 몇 대가 도는지는 **문장**이 말한다
    // (`_domainNote`), 각 장치가 얼마나 일했는지는 **그 장치 줄**이 말한다.
    //
    // ⚠ 이 자리에 다시 평균 막대를 넣지 말 것. 넣으려면 먼저 "그 무리가 공유하는
    //   단위가 무엇인가" 에 답해야 한다 — 답이 없으면 그 막대도 없다.

    // 근거가 하나도 없을 때(=전부 정상 동작) 그 무리가 **지금 무엇을 하고
    // 있는지**를 한 줄로 말한다. 아무 말도 없으면 막대만 남아, 왜 이 카드가
    // [시설 세부]에 있는지 알 수 없다.
    function _domainNote(key, list) {
      if (key !== 'hvac') return '';
      var byKind = {};
      list.forEach(function (c) {
        var lv = _live(c.slot_key);
        var a = _actualOf(lv);
        var v = (a != null) ? a : (c.pct != null ? c.pct : 0);
        if (v > 0) byKind[c.kind] = Math.max(byKind[c.kind] || 0, v);
      });
      // ⚠ **맞서는 짝이 함께 돌고 있으면 그것부터 말한다.** 난방과 냉방이
      // 동시에 100% 인 것은 정상 동작이 아니라 에너지를 서로 상쇄하며 버리는
      // 상태인데, 막대만 보면 둘 다 "잘 돌고 있다" 로 보인다.
      if (byKind.heater && byKind.cooler) {
        // ⚠ 설명 문구는 **한 스타일**이다. 무리마다 다른 클래스를 붙였더니
        // 카드마다 글자 굵기가 달라 보였다(2026-08-26 지적) — 무엇이 더
        // 중요한지는 **문장이** 말하지 클래스가 말하지 않는다.
        return '<div class="aot-ov-why">' +
               _esc(_t('Heating and cooling are both running against each other')) +
               '</div>';
      }
      var doing = [];
      if (byKind.heater) doing.push(_t('warming'));
      if (byKind.cooler) doing.push(_t('cooling'));
      if (byKind.fogger) doing.push(_t('adding moisture'));
      if (!doing.length) {
        return '<div class="aot-ov-why">' + _esc(_t('Nothing running right now')) +
               '</div>';
      }
      // 몇 대가 도는지는 걷어낸 막대가 달고 있던 말이다 — 막대는 뜻이 없었지만
      // 이 사실은 있다. 문장 뒤에 붙인다.
      var running = 0;
      list.forEach(function (c) {
        var a = _actualOf(_live(c.slot_key));
        if ((a != null ? a : (c.pct != null ? c.pct : 0)) > 0) running += 1;
      });
      return '<div class="aot-ov-why">' +
             _esc(_t('Currently %(what)s').replace('%(what)s', doing.join(' \u00b7 ')) +
                  ' \u00b7 ' +
                  _t('%(on)s of %(all)s running')
                    .replace('%(on)s', String(running))
                    .replace('%(all)s', String(list.length))) +
             '</div>';
    }

    // 마지막 작동 — **모든 장치**가 갖는다(`/runtime` 의 last_run_at).
    // 예전에는 관수 payload 하나만 보고 이름이 맞는 한 대에만 붙였는데, 같은
    // 목록의 나머지는 그 칸이 비어 "왜 이것만 나오나" 가 됐다(2026-08-26 지적).
    // 쉬고 있는 장치일수록 이 값이 필요하다 — 지금 0% 인 것이 방금 껐기
    // 때문인지 며칠째 안 돈 것인지가 갈린다.
    function _lastRunOf(lv) {
      var at = lv && lv.last_run_at;
      if (!at) return '';
      var h = (Date.now() / 1000 - Number(at)) / 3600;
      if (h < 0) return '';
      if (h < 1) {
        return _t('%(n)s min ago').replace(
          '%(n)s', String(Math.max(1, Math.round(h * 60))));
      }
      if (h < 24) {
        return _t('%(n)s h ago').replace('%(n)s', String(Math.round(h)));
      }
      return _t('%(n)s d ago').replace('%(n)s', String(Math.round(h / 24)));
    }

    var cmds = summary.commands || [];
    if (cmds.length) {

      var _rowOf = function (c) {
        var kindLabel = _t(_KIND_LABELS[c.kind] || c.kind || '');
        var lv = _live(c.slot_key);
        // 이름은 런타임의 것을 쓴다. 요약의 slot_key 는 uuid 앞 8자인 경우가
        // 많아, 그대로 쓰면 개구부 셋이 전부 '개구부' 로 보인다 — 서로 다른
        // 값을 갖는 장치들이 한 이름으로 뭉쳐 이 카드의 존재 이유가 없어진다.
        var label = (lv && lv.name) ||
                    (c.slot_key && !/^[0-9a-f]{8}$/.test(c.slot_key)
                       ? c.slot_key : kindLabel);
        // 근거 + 그 근거를 만든 변수. 변수는 근거가 '목표를 좇는 중' 일 때만
        // 뜻이 있다 — 안전 게이트가 건 값에 "VPD 때문" 을 붙이면 거짓이 된다.
        // ⚠ `pct` 가 **null** 이면 "이번 사이클에 명령하지 않았다" 는 뜻이다
        //   (안전 게이트가 건드리지 않은 장치). 0 으로 읽으면 "0% 를 명령했다"
        //   가 되어 아래 명령 대조가 거짓말을 한다 — 켜져 있는 난방기에
        //   "명령 0%" 가 붙는다(2026-08-26).
        var commanded = (c.pct != null);
        var pctv = commanded ? c.pct : 0;
        // ── 명령 대 실제 ────────────────────────────────────────────────────
        // 막대는 **실제**를 그리고 눈금(target)이 **명령**이다. 둘이 벌어져
        // 있으면 그 간극이 그림으로 바로 보인다 — 2026-08-26 에 반나절을 태운
        // 버그가 정확히 이것이었다(코디네이터가 24.6% 를 명령했는데 장치는
        // 5.0%. 풍향 가중치가 코디네이터 밖에서 곱해지고 있었다).
        // 실제를 모르면 명령만 그린다 — 없는 값을 0 으로 그리면 "장치가 꺼져
        // 있다" 는 거짓말이 된다.
        // on/off 장치의 처리는 `_actualOf` 에 있다(그 주석 참조).
        var actual = _actualOf(lv);
        // ⚠ 골격은 다른 줄과 같다 — 1행은 **지금 값**만, 명령·마지막 작동은
        // 3행이다. 마지막 작동을 별도 줄로 냈더니 장치 하나가 두 줄을 차지해
        // 목록이 늘어졌다(2026-08-26 지적). 그것은 이 장치에 딸린 곁가지라
        // 자기 줄을 가질 만한 것이 아니다.
        // 3행 — 왼쪽에 마지막 작동·명령(`scaleLead`), 오른쪽에 면적(`scaleNote`).
        // ⚠ **`scale` 에 넣지 말 것.** 그 배열은 *축의 눈금*이라, 목표가 축 끝에
        //   붙는 줄에서는 그쪽 끝 항목이 CSS 로 감춰진다 — 창이 100% 로 열린
        //   동안에만 '마지막 작동' 이 사라졌다(2026-08-26). 덧말은 자기 슬롯이
        //   있고, 왼쪽 것들은 **한 조각**으로 합친다.
        // ── on/off 장치는 **축이 다르다** (2026-08-26) ──────────────────────
        // 비례 장치(개구부·PWM)는 지금 개도가 곧 "얼마나" 라 막대가 그것을
        // 그리면 된다. on/off 장치에는 그런 양이 없다 — 켜짐은 0 아니면 100
        // 이라, 같은 막대에 그리면 "난방기가 100% 출력" 처럼 읽히지만 실은
        // "켜져 있다" 뿐이다. 그 장치의 "얼마나" 는 **시간축**에 있다:
        // 지난 24시간 중 실제로 돈 시간을 막대에 채운다.
        //
        // ⚠ **골격은 다른 줄과 똑같다.** 축만 바뀔 뿐 자리는 그대로다 —
        //   3행 오른쪽은 언제나 「지금 값 / 전체」이고, 개구부의
        //   "831.7 / 831.7 m²" 와 같은 자리에 "0.5 / 24시간" 이 선다.
        //   왼쪽은 마지막 작동(+명령)이다. 이것을 왼쪽에 몰아넣으면 오른쪽이
        //   비어 그 줄만 다른 규칙으로 서 있게 된다(2026-08-26 지적).
        //
        // 가동률을 모르면(자료 없음) 막대를 그리지 않는다 — 0% 로 그리면 하루
        // 종일 쉰 장치와 구분되지 않는다.
        var isBinary = !!(lv && lv.control_type === 'binary');
        var duty = isBinary ? _dutyOf(lv) : null;
        var left = [];
        var run = _lastRunOf(lv);
        if (run) left.push(_t('Last run') + ' ' + run);
        // 명령과 실제가 다를 때만 명령을 적는다. on/off 는 %가 뜻이 없으므로
        // 같은 말을 켜짐/꺼짐으로 한다.
        if (commanded && actual != null && Math.abs(actual - pctv) >= 1) {
          left.push(_t('commanded') + ' ' +
                    (isBinary ? (pctv > 0 ? _t('Powered on') : _t('Powered off'))
                              : pctv.toFixed(0) + '%'));
        }
        var lead = left.join(' \u00b7 ');
        // 3행 오른쪽 — 개구부는 면적, on/off 는 작동 시간. **같은 자리**이고
        // 둘 다 「지금 값 / 축의 끝」이다.
        var rightNote = isBinary
          ? (duty ? duty.note : '')
          : ((c.area_m2 && actual != null)
               ? _areaText(c.area_m2 * actual / 100, c.area_m2) : '');
        var shown = (actual != null ? actual : pctv);
        // 명령도 없고 실제도 모르면 그릴 것이 없다 — 0% 로 그리면 "꺼져 있다"
        // 는 거짓말이 된다.
        if (!commanded && actual == null) return '';
        var body = V
          ? (isBinary
              // 밴드 — 초록이 '평소', 세로선이 '오늘'. 기준이 없으면 값도
              // 주지 않는다(축을 지어내지 않는다).
              ? V.band({ label: label,
                         // ⚠ **옛 그림 그대로**(초록 면 + 세로선 마커).
                         // 여기서 초록은 목표가 아니라 **평소 가동시간**이고
                         // 길이 자체가 뜻이라, 다른 줄처럼 선 둘로 못 옮긴다.
                         okZone: true,
                         value: (duty && duty.hasBase) ? duty.h : null,
                         min: 0,
                         max: (duty && duty.hasBase) ? duty.axisH : undefined,
                         // 왼쪽 끝부터 평소까지 채운다 — 초록의 **길이**가 기준
                         // 이고, 세로선이 그보다 왼쪽이면 평소보다 덜 돌았다.
                         okMin: (duty && duty.hasBase) ? 0 : undefined,
                         okMax: (duty && duty.hasBase) ? duty.avgH : undefined,
                         valueText: (duty ? duty.h.toFixed(1) : '\u2014'),
                         valueSub: _t('hours'),
                         scaleLead: lead, scaleNote: rightNote })
              : V.bullet({ label: label,
                           value: shown,
                           target: ((commanded && actual != null)
                                    ? pctv : undefined),
                           min: 0, max: 100,
                           valueText: shown.toFixed(0), valueSub: '%',
                           scaleLead: lead, scaleNote: rightNote }))
          : _pRow(label, _esc(isBinary
                              ? (duty ? duty.h.toFixed(1) : '\u2014')
                              : shown.toFixed(0) + '%'));
        return body;
      };
      // 같은 근거를 장치마다 되풀이하지 않는다. 개구부 셋이 모두 같은 이유로
      // 그 값이면 그 문장은 **한 번**이면 된다 — 셋에 붙이면 같은 줄이 세 번
      // 나와 정작 다른 장치의 다른 이유가 파묻힌다(2026-08-26 지적).
      var _reasonNote = function (list) {
        var codes = {};
        list.forEach(function (c) { if (_REASON_TEXT[c.reason]) codes[c.reason] = 1; });
        var keys = Object.keys(codes);
        if (!keys.length) return '';
        return keys.map(function (r) {
          var n = list.filter(function (c) { return String(c.reason) === r; });
          // 무리 전체가 같은 이유면 장치 이름을 다시 적지 않는다.
          var who = (n.length === list.length) ? '' :
                    n.map(function (c) {
                      var lv = _live(c.slot_key);
                      return (lv && lv.name) || c.slot_key;
                    }).join(' \u00b7 ') + ': ';
          // 그 이유에 해당하는 장치가 **전부 최대 출력**이면 문장을 바꾼다.
          var allFull = n.every(function (c) {
            var lv = _live(c.slot_key);
            var a = _actualOf(lv);
            var v = (a != null) ? a : (c.pct != null ? c.pct : 0);
            return v >= _FULL_OUTPUT_PCT;
          });
          var msg = (allFull && _REASON_TEXT_FULL[r]) || _REASON_TEXT[r];
          return '<div class="aot-ov-why">' + _esc(who + _t(msg)) +
                 (!allFull && _REASON_HINT[r]
                    ? ' \u00b7 ' + _esc(_t(_REASON_HINT[r])) : '') +
                 '</div>';
        }).join('');
      };
      // ── 도메인마다 **별도 카드** ─────────────────────────────────────────
      // 이 탭이 답하는 질문이 "왜 이렇게 하고 있나" 이므로, 무리를 짓는 기준도
      // 제어기가 실제로 쓰는 경계여야 한다 — **부하분담이 도메인 안에서만**
      // 일어난다(2026-08-26 `types.ACTUATOR_DOMAIN`). 창끼리는 서로의 기여를
      // 보고 조율하지만 공조는 그것을 모른다. 그 경계가 곧 "왜" 의 경계다.
      //
      // 한 카드에 소제목으로 나누는 것보다 카드를 나눈다 — 무리마다 근거가
      // 따로 붙으므로, 한 컨테이너 안에서는 어느 근거가 어느 무리의 것인지
      // 눈으로 이어붙여야 한다.
      //
      // ⚠ **`types.ACTUATOR_DOMAIN` 과 같은 배정이어야 한다.** 갈리면 화면이
      //   설명하는 무리와 제어기가 실제로 묶는 무리가 달라진다 —
      //   `test_map_popup_labels.py` 가 소스로 고정한다.
      var _catOrder = [
        { key: 'vent',   label: 'Ventilation', kinds: ['opening', 'exhaust_fan', 'intake_fan'] },
        { key: 'screen', label: 'Screens',     kinds: ['curtain', 'shade'] },
        // ⚠ 'Climate' 를 쓰지 않는다 — 그 msgid 는 장치 분류 화면에서 '기후장치'
        //   로 번역돼 있어 여기 붙이면 뜻이 어긋난다. 뜻이 다르면 msgid 를 나눈다.
        { key: 'hvac',   label: 'Heating, cooling and misting',
          kinds: ['heater', 'cooler', 'fogger'] },
        { key: 'aux',    label: 'Other',       kinds: null }
      ];
      var _bucket = {};
      cmds.forEach(function (c) {
        var key = 'facility';
        for (var i = 0; i < _catOrder.length; i++) {
          if (_catOrder[i].kinds &&
              _catOrder[i].kinds.indexOf(c.kind) !== -1) { key = _catOrder[i].key; break; }
        }
        (_bucket[key] = _bucket[key] || []).push(c);
      });
      _catOrder.forEach(function (g) {
        var list = _bucket[g.key] || [];
        if (!list.length) return;
        // ── 무리의 **요약이 먼저, 장치별이 나중** ──────────────────────────
        // 그 무리가 지금 통틀어 어떤 상태인지(환기 면적)를 먼저 보고, 그
        // 다음에 장치 하나하나를 본다. 요약을 맨 아래 두었더니 장치는 위에
        // 있는데 총량이 화면 끝에 떨어져 같이 읽어야 할 둘이 갈렸다
        // (2026-08-26 지적). 요약을 갖는 무리는 **환기 하나뿐**이다 —
        // 위 `집계 막대는 …` 주석 참조.
        var head = (g.key === 'vent') ? _ventRows() : [];
        var note = _reasonNote(list) || _domainNote(g.key, list);
        // ── 설명이 **맨 위** ─────────────────────────────────────────────
        // 이 카드가 답하는 것은 "왜 이렇게 하고 있나" 다. 그 답을 숫자 뒤에
        // 두면 사용자는 막대를 먼저 읽고 스스로 해석한 뒤에야 설명을 만난다 —
        // 순서가 거꾸로다. 문장 먼저, 그 근거가 되는 요약과 장치별이 뒤다
        // (2026-08-26 지적).
        html += '<div class="aot-ov-card-title">' + _esc(_t(g.label)) + '</div>' +
                '<div class="aot-ov-block">' +
                note +
                // 요약과 장치별을 **한 묶음**에 넣는다 — 줄 사이 간격(32px)과
                // 가로 구분선은 `.aot-viz + .aot-viz` 가 준다(dataviz 규약).
                // 따로 감싸면 그 규칙이 끊겨 두 덩어리가 붙어 보인다.
                (V ? V.group(head.concat(list.map(_rowOf)))
                   : head.concat(list.map(_rowOf)).join('')) +
                '</div>';
      });
    }

    // 추세는 [현황]의 [환경] 카드가 그린다 — 값과 방향은 함께 읽어야
    // 뜻이 서기 때문이다(`buildEnvNowHtml` 의 추세 주석). 여기 두었더니
    // 둘이 탭으로 갈렸다(2026-08-26 지적).
    var ff = summary.feedforward || {};
    if (ff.active) {
      html += '<div class="aot-ov-card-title">' + _esc(_t('Acting on the forecast')) +
              '</div><div class="aot-ov-block">' +
              '<div class="aot-ov-why">' + _esc(ff.reason || '') + '</div>' +
              '</div>';
    }

    if (!html) {
      return _emptyBlock(_t('Facility detail'),
                        _t('No control cycle to explain yet.'));
    }
    return html;
  }

  // [개요] 섹션 — 정적 정보: 대표사진 / 시설 정보 / 설명 / 노트.
  //   info: GET /api/aot/facility/<uuid>/info 응답
  /**
   * 설명 블록 — **시설·필지가 같은 모양을 쓴다.**
   *
   * 예전에는 시설 전용이었다(`_ovInfoBlocks` 안). 필지에 같은 것을 다시 적으면
   * 두 벌이 되고, [편집] 버튼 자리나 [취소]/[저장] 순서가 화면마다 갈린다 —
   * 이 파일이 반복해서 겪은 실패다.
   *
   * 저장 배선은 호출자가 붙인다(엔드포인트가 다르다: 시설은
   * `/api/aot/facility/<uuid>/info`, 도형은 `/api/geo/shape/<uuid>/description`).
   * 마크업과 클래스 이름은 같으므로 배선 코드도 같은 모양이 된다.
   */
  function buildDescriptionHtml(description, canEdit) {
    var descView = description
      ? _esc(description)
      : '<span class="aot-ov-muted">' + _esc(_t('No description')) + '</span>';
    // [편집]은 **블록 맨 아래 오른쪽**이다(.aot-ov-actions). 제목 줄은 무엇인지
    // 말하는 자리이고 버튼은 다 읽은 뒤 누르는 것이라, 행동은 시선이 끝나는 곳에
    // 모은다 — 구획 [편집]·[구획 추가]·[노트 열기]와 같은 규칙이다.
    return '<div class="aot-ov-card-title">' + _esc(_t('Description')) + '</div>' +
           '<div class="aot-ov-block aot-ov-desc">' +
           // 원본을 함께 남긴다 — [취소] 가 화면 글자를 되읽으면 "설명 없음"
           // 이라는 **안내 문구**가 본문으로 저장된다.
           '<div class="aot-ov-desc-view" data-raw="' + _esc(description || '') +
           '">' + descView + '</div>' +
           (canEdit
             ? '<div class="aot-ov-desc-editwrap" style="display:none">' +
               '<textarea class="aot-ov-desc-input" rows="3" maxlength="2000">' +
               _esc(description || '') + '</textarea>' +
               // [취소] [저장] 순. **오른쪽 끝이 기본 동작**이다 — 같은 모달의
               // 구획 편집·구획 생성·단계 확인 폼이 전부 이 순서다.
               '<div class="aot-ov-desc-actions">' +
               '<button type="button" class="aot-ov-pill aot-ov-desc-cancel">' +
               _esc(_t('Cancel')) + '</button>' +
               '<button type="button" class="aot-ov-pill aot-ov-pill--primary ' +
               'aot-ov-desc-save">' + _esc(_t('Save')) + '</button>' +
               '</div></div>' +
               '<div class="aot-ov-actions">' +
               '<button type="button" class="aot-ov-pill aot-ov-desc-edit">' +
               _esc(_t('Edit')) + '</button></div>'
             : '') +
           '</div>';
  }

  function buildAboutSection(info) {
    return _ovInfoBlocks(info);
  }

  // 노트 블록 — 골격·문구·배선은 전부 공용 컴포넌트(AoTNotesBlock, sensor-label.js)
  // 한 곳에 있다. 여기서 자체 마크업을 다시 짜지 말 것: 그렇게 갈라져서 창마다
  // 노트 버튼 모양과 문구가 달랐다. 호출자는 렌더 뒤 AoTNotesBlock.wire() 를 부른다.
  function _ovNotesBlock() {
    return window.AoTNotesBlock ? window.AoTNotesBlock.html() : '';
  }

  // ── 모달 제목줄 (site·zone·facility 공용) ─────────────────────────────────
  //
  //   [← 상위]  이름  [상태 점]
  //
  // 계층마다 헤더 HTML 을 따로 짜던 것을 하나로 모은 것이다. 따로 짜면 상위
  // 이동 화살표를 하나 추가할 때 세 군데를 고쳐야 하고, 실제로 한 곳은 빠졌다.
  //
  // opts: { name, up: bool, status: 'ok'|'warning'|'fault'|'empty'|null }
  function buildModalHeader(opts) {
    opts = opts || {};
    // aria-label 은 종류를 가리지 않는 'Go up' 하나다 — 상위가 필지일 수도
    // 구역일 수도 시설일 수도 있어서(장치 모달), 문구를 종류마다 나누면
    // msgid 가 셋으로 늘고 정작 어느 것이 뜰지는 데이터가 정한다.
    // 구체적인 상위 이름은 버튼의 title 로 붙인다(_wireUpBtn).
    var up = opts.up
      ? '<button type="button" class="aot-modal-up" hidden aria-label="' +
        _esc(_t('Go up')) + '">' + upIconHtml() + '</button>'
      : '';
    return '<div class="aot-sensor-popup-header">' + up +
             '<span class="aot-modal-heading">' +
               '<span class="aot-sensor-popup-title">' +
               _esc(opts.name || '') + '</span>' +
               statusDotHtml(opts.status) +
             '</span>' +
           '</div>';
  }

  // 상태 점 — **주의·이상일 때만 보인다.**
  // 정상까지 초록 점을 찍으면 매일 보는 표식이 하나 늘 뿐이고, 정작 봐야 할
  // 붉은 점이 그 속에 묻힌다(센서 응답 수를 모자랄 때만 적는 것과 같은 규칙).
  // 판정은 서버가 필지·구역·시설 모두 같은 함수로 낸다.
  var _STATUS_WORD = { fault: 'Fault', warning: 'Attention' };
  function statusDotHtml(status) {
    var word = _STATUS_WORD[status];
    if (!word) return '';
    return '<span class="aot-status-dot is-' + status + '" title="' +
           _esc(_t(word)) + '" aria-label="' + _esc(_t(word)) + '"></span>';
  }

  // 렌더 뒤 상태가 도착했을 때 제목줄에 점을 넣는다.
  function applyStatusDot(scopeEl, status) {
    if (!scopeEl) return;
    var head = scopeEl.querySelector('.aot-modal-heading');
    if (!head) return;
    var old = head.querySelector('.aot-status-dot');
    if (old) old.remove();
    var html = statusDotHtml(status);
    if (html) head.insertAdjacentHTML('beforeend', html);
  }

  // 빈 상태 한 줄 — 계층마다 "장치 없음"/"기능 없음"/"No records" 가 서로
  // 다른 마크업이었다. 문구는 호출자가 정하고 생김새는 여기서 하나로 둔다.
  function emptyLine(msg) {
    return '<div class="aot-ov-empty">' + _esc(msg) + '</div>';
  }

  // 현재 환경 블록 — 구역·시설 [현황] 공용.
  //
  //   env: { readings: [{key, value, unit, n}], sensors: {valid, total} }
  //
  // 값은 채널 종류별 평균이고, 순서는 서버가 대표값 우선순위대로 정렬해 보낸다.
  // 센서가 아예 없으면 블록을 그리지 않는다 — "—" 만 남은 빈 상자는 값이 없다는
  // 사실을 알리기보다 화면만 차지한다.
  //
  // 응답 수(valid/total)는 **모자랄 때만** 적는다. 전부 살아 있을 때 "3/3"을
  // 붙이면 매일 보는 숫자가 하나 느는 것뿐이고, 정작 봐야 할 "2/3"이 그 속에 묻힌다.
  // 대표 측정 지정 — **값 자체가 버튼이다.**
  //
  // 서버는 VPD>T>RH>CO2>... 라는 고정 우선순위의 첫 항목을 대표로 내세우고
  // (site_summary.SENSOR_KEY_PRIORITY), 그 대표값이 곧 지도 구역 라벨에 뜨는
  // 값이다. 토양수분을 보려고 온 사람에게 그 순서는 남의 기준이다.
  //
  // 고르는 자리를 따로 만들지 않았다. 사람이 이미 보고 있는 숫자를 누르면
  // 그것이 대표가 되고, 어느 것이 대표인지는 배경으로 남는다. 순서는 건드리지
  // 않는다 — 누를 때마다 항목이 자리를 옮기면 다음 클릭이 어디로 갈지 모른다.
  //
  //   opts.repKey     지금 대표로 지정된 key(배경 표시)
  //   opts.selectable 누를 수 있는가(edit_settings 권한자만)
  // 측정 키 → 목표·편차 키. 서버가 두 어휘를 쓰므로 여기서 한 번만 잇는다.
  // 측정 키 → **목표** 어휘. 온도·습도는 여기 없다(2026-08-20).
  //
  // 시설 코디네이터의 summary.targets 에는 temperature·humidity 도 들어 있지만
  // 그것은 목표가 아니다 — `build_env_target` 의 주석이 못 박고 있다:
  //   "R3: T/RH 는 호출자가 constraint 로 별도 관리(이 함수는 추적 목표용
  //    변수만 반환)"
  // 실제로 VPD 를 1차 목표로 쓰는 코디네이터에서는 T/RH 가 guide 대역의
  // **중앙값**으로 계산된 보조값이라, 그것을 "목표" 라고 적으면 아무도 정한 적
  // 없는 숫자가 목표로 둔갑한다(실측: 상추 육묘장이 "목표 32.0°C" 를 띄우고
  // 있었는데 프로그램의 그 단계는 주간 25 · 야간 15 였다).
  //
  // 온도·습도가 정말로 정해진 것은 **한계**다 — _NOW_TO_LIMIT 로 따로 받아
  // 선으로 긋는다.
  // 값이 하나뿐인 기준(목표·단일 한계)을 구간으로 펼치는 폭. **이 화면의
  // 약속이지 프로그램이 말한 값이 아니다** — 프로그램에 허용 오차 칸이 생기면
  // 그 값이 이것을 대신해야 한다.
  var _ENV_SINGLE_TOL = 0.10;

  var _NOW_TO_TARGET = { CO2: 'co2', VPD: 'vpd' };
  var _NOW_TO_LIMIT  = { T: 'temperature', RH: 'humidity' };

  /* 환경 값 한 줄 — **밴드 바**(components/aot-dataviz.css).
   *
   * 예전에는 큰 숫자 카드였다. 25.1°C 만 보면 좋은지 나쁜지 알 수 없어서 목표와
   * 편차를 작은 글씨로 아래 두 줄에 더 달았는데, 그러면 한 항목이 네 줄이 되고
   * "그래서 지금 괜찮은가" 는 여전히 사람이 빼기를 해야 나왔다. 값을 축 위의
   * 위치로 바꾸면 그 계산이 사라진다.
   *
   * 축과 적정 구간은 **밴드 색과 같은 표**에서 온다
   * (AoTMapSensorLabels.bandScale → DEFAULT_RANGES 또는 시설의 sensor_ranges).
   * 화면이 범위를 따로 들면 라벨 색과 축이 곧 갈린다.
   *
   * 축을 모르는 지표(기본 범위가 없는 CO2 등)는 **축을 지어내지 않고** 값만
   * 낸다(AoTViz.value) — 같은 머리줄을 쓰므로 줄이 어긋나지 않는다.
   *
   * 대표 측정 지정(rep_key)은 그대로다: 바깥 래퍼가 .aot-env-now-item 이고
   * wireEnvNowPick 이 그것을 찾는다.
   */
  /* 광합성에 직접 얽힌 값을 위로 올린다 — VPD · 일사 · CO2.
   *
   * 나머지(온도·습도·풍속…)가 덜 중요한 것이 아니라, 이 셋이 **지금 광합성이
   * 되고 있는가** 를 직접 말하는 값이라 먼저 보인다. 온도·습도는 그 셋을 만드는
   * 조건에 가깝다.
   *
   * **데이터가 있는 것만 올라간다.** 목록에 없는 키는 자리를 만들지 않는다 —
   * 빈 줄을 위에 두면 "있어야 하는데 없다" 로 읽히고, 실제로는 그 시설에 그
   * 센서가 없을 뿐이다.
   *
   * 나머지는 서버가 준 순서를 그대로 지킨다(안정 정렬). 서버 순서에는 대표값
   * 우선 같은 판단이 이미 들어 있어, 여기서 다시 섞으면 그 판단이 사라진다.
   */
  var _ENV_LEAD_KEYS = ['VPD', 'light', 'DLI', 'CO2'];

  function _envNowOrder(readings) {
    var lead = [], rest = [];
    readings.forEach(function (r) {
      (_ENV_LEAD_KEYS.indexOf(r.key) >= 0 ? lead : rest).push(r);
    });
    lead.sort(function (a, b) {
      return _ENV_LEAD_KEYS.indexOf(a.key) - _ENV_LEAD_KEYS.indexOf(b.key);
    });
    return lead.concat(rest);
  }

  // 측정 키 → 추세 키·자릿수. VPD 는 서버가 추세를 내지 않는다(파생값이라
  // T·RH 추세가 이미 그 방향을 말한다).
  //
  // ⚠ **모듈 스코프에 둔다.** 처음에는 `buildEnvNowHtml` 안에 두었는데, 이 값을
  // 쓰는 곳은 그 함수가 아니라 **행 빌더**(`_envNowRowHtml`)라 클로저가 닿지
  // 않았다 — `_trendNote is not defined` 로 환경 카드가 통째로 안 그려졌다
  // (에러는 호출부 try 가 삼켜 화면에는 "카드 없음" 으로만 보였다).
  // 맑은 날 정오의 전천일사에 해당하는 PPFD [µmol/m²/s]. 광량 트랙의 축 끝이다
  // — 그날의 최대치가 아니라 **사람이 아는 상한**이라야 값이 커도 축이 흔들리지
  // 않는다(축이 값 따라 늘면 언제나 절반쯤에 서 있는 것처럼 보인다).
  var _LIGHT_FULL_SUN = 2000;

  var _TREND_OF = { T: ['T_per_min', ' \u00b0C/min', 2],
                    RH: ['RH_per_min', ' %/min', 2],
                    CO2: ['CO2_per_min', ' ppm/min', 1] };

  function _trendNote(key, trend) {
    var spec = _TREND_OF[key];
    if (!spec) return '';
    var val = (trend || {})[spec[0]];
    if (val == null) return '';
    // 반올림해서 0 으로 보일 값은 내지 않는다 — "→ 0" 은 아무 말도 아니다.
    var eps = Math.pow(10, -spec[2]) / 2;
    if (Math.abs(val) < eps) return '';
    return (val > 0 ? '\u2191' : '\u2193') + ' ' +
           Math.abs(val).toFixed(spec[2]) + spec[1];
  }

  /* 환경 줄 하나의 **판정**을 낸다 — 그림은 그리지 않는다.
   *
   * ## 왜 그림과 갈라 두는가
   *
   * 이 판정에는 이 화면이 여러 번 데어 가며 굳힌 규칙이 들어 있다:
   *
   *   - 온도·습도는 **목표가 아니라 한계**다(`_NOW_TO_LIMIT`). 목표 칸에
   *     넣으면 아무도 정한 적 없는 숫자가 목표로 둔갑한다.
   *   - 프로그램이 값을 정했으면 앱 기본 밴드를 그리지 않는다(두 기준을
   *     동시에 말하게 된다).
   *   - 곡선이 걸린 항목은 구간을 비우고 곡선 이름만 적는다.
   *   - 값이 하나뿐이면 ±10% 를 구간으로 삼는다 — 이 화면의 약속이다.
   *
   * 이 판정을 화면마다 다시 조립하면 그 넷을 각자 틀린다. 그래서 **판정은
   * 여기 하나**, 그림은 부르는 쪽이 자기 자리에 맞게 그린다 — 큰 모달은
   * 밴드 줄로(`_envNowRowHtml`), 좁은 위젯은 타일로(`AoTViz.tile`).
   *
   * 반환: `{key, name, dec, unit, valueText, value, stale, hasAxis,
   *         min, max, okMin, okMax, anchorText, anchorAt, methodName,
   *         trendNote}` — 값이 없으면 null.
   */
  function envRowSpec(r, opts) {
    opts = opts || {};
    var SL = window.AoTSensorLabel;
    var ML = window.AoTMapSensorLabels;
    if (!r || r.value == null) return null;
    var dec  = (SL && SL.defaultDecimals) ? SL.defaultDecimals(r.key) : 1;
    var name = (SL && SL.keyDisplay) ? SL.keyDisplay(r.key) : r.key;
    // 단위 정규화는 공용 함수 하나만 쓴다(값 라벨·차트 레전드와 같은 판단).
    var unit = (SL && SL.displayUnit) ? SL.displayUnit(r.unit)
                                      : String(r.unit || '').trim();

    var tkey = _NOW_TO_TARGET[r.key];
    var tval = tkey ? (opts.targets || {})[tkey] : null;
    // 한계 — 프로그램이 "이 안에서" 를 말한 값들. 값이 둘이면 상·하한,
    // 하나면 그 자리 하나(어느 쪽인지는 아무도 선언한 적이 없다).
    var lkey = _NOW_TO_LIMIT[r.key];
    var lims = lkey ? ((opts.limits || {})[lkey] || null) : null;
    if (lims && !lims.length) lims = null;
    // 목표가 **곡선**으로 정해진 항목 — 숫자가 없다. 그 자리에 앱 기본 구간을
    // 그리면 곡선이 다스리는 값에 다른 기준을 겹쳐 말하게 된다. 구간을 비우고
    // "곡선을 따름" 만 적는다.
    //
    // ⚠ 코디네이터가 붙어 있으면 곡선이 풀린 **현재 값**이 목표로 들어온다
    // (summary.targets). 그때는 tval 이 있으므로 이 분기에 오지 않는다.
    var mname = (tkey && (opts.targetMethods || {})[tkey]) || null;

    // **프로그램이 그 항목의 값을 정했으면 프로그램이 이긴다.** 앱 기본 밴드
    // (DEFAULT_RANGES)는 일반 온실을 가정한 값이라, 프로그램이 단계별로 정한
    // 것과 다르면 화면이 두 기준을 동시에 말하게 된다 — 사람은 어느 쪽을 믿을지
    // 알 수 없다. 그래서 목표가 있으면 **적정 구간을 그리지 않고** 목표 하나만
    // 기준으로 세운다. 범위를 지어내지 않는 이유: 프로그램이 주는 것은 값 하나이지
    // 폭이 아니다(허용 오차는 아무도 선언한 적이 없다).
    //
    // 같은 이유로 범위 밖 표시(is-out)도 하지 않는다 — 목표와 다르다는 것은
    // "벗어났다" 가 아니라 "여기서 저기까지" 다. 그 거리는 마커와 목표 눈금
    // 사이가 이미 보여 준다.
    var sc = (ML && ML.bandScale) ? ML.bandScale(r.key, opts.ranges) : null;
    var spec = { key: r.key, name: name, dec: dec, unit: unit,
                 valueText: (+r.value).toFixed(dec), value: +r.value,
                 stale: !!r.stale, hasAxis: false,
                 methodName: null, anchorText: null, anchorAt: null,
                 trendNote: _trendNote(r.key, opts.trend) };
    if (sc) {
      // 판정 축과 같은 공간으로 환산한 뒤 위치를 잡는다(Pa 로 저장된 VPD 등).
      var v = ML.bandValue ? ML.bandValue(r.key, +r.value, r.unit) : +r.value;
      // 가운데 눈금은 **그 줄의 기준**이다 — 목표가 설정돼 있으면 그것이
      // 기준이고(사람이 정한 값이 밴드 기본값을 이긴다), 없으면 적정 범위다.
      // ── 초록 구간을 어디서 얻는가 ──────────────────────────────────────
      //
      // 출처는 넷이지만 **그리는 방법은 하나**다: 초록 면. 프로그램이 정한
      // 것이든 앱 기본값이든 뜻이 같으면(= "여기면 된다") 모양도 같아야 한다.
      // 한때 프로그램 값만 선으로 따로 그렸는데, 한 줄에 선이 셋(하한·지금·
      // 상한) 서면 어느 것이 지금인지 모양이 말해 주지 못했다.
      //
      // **값이 하나뿐이면 그 값을 가운데로 ±10% 를 구간으로 잡는다.**
      // 프로그램이 주는 것은 대부분 값 하나이고(습도·VPD·CO2), 폭이 없으면
      // 그릴 구간도 없다 — 그러면 그 줄은 "지금 어떤가" 에 답하지 못한다.
      // 10% 는 이 화면의 **약속**이지 프로그램이 말한 값이 아니다.
      var anchorText, anchorAt, okLo = null, okHi = null;
      var _norm = function (v) {
        return ML.bandValue ? ML.bandValue(r.key, +v, r.unit) : +v;
      };
      // 값 하나 → 가운데로 보고 ±TOL. 0 이면 폭이 0 이라 구간을 만들지 않는다.
      var _spread = function (center) {
        var c = _norm(center);
        if (!isFinite(c) || c === 0) return;
        var d = Math.abs(c) * _ENV_SINGLE_TOL;
        okLo = c - d; okHi = c + d;
      };

      if (tval != null) {
        anchorText = _t('target') + ' ' + (+tval).toFixed(dec);
        anchorAt = _norm(tval);
        _spread(tval);
      } else if (mname) {
        // 곡선은 지금 값을 여기서 구할 수 없다 — 가운데가 없으니 구간도 없다.
        anchorText = mname ? _t('Follows curve: {name}').replace('{name}', mname)
                           : _t('Follows a curve');
        anchorAt = null;
      } else if (lims && lims.length >= 2) {
        var _l = lims.map(_norm);
        okLo = Math.min.apply(null, _l);
        okHi = Math.max.apply(null, _l);
        anchorText = _t('Range') + ' ' +
                     lims.map(function (v) { return _fmtBand(+v, dec); })
                         .join('\u2013');
        anchorAt = (okLo + okHi) / 2;
      } else if (lims) {
        anchorText = _t('Range') + ' ' + _fmtBand(+lims[0], dec);
        anchorAt = _norm(lims[0]);
        _spread(lims[0]);
      } else {
        okLo = sc.okMin; okHi = sc.okMax;
        anchorText = _fmtBand(sc.okMin, dec) + '\u2013' + _fmtBand(sc.okMax, dec);
        anchorAt = null;                 // band() 가 적정 구간 중앙에 붙인다
      }
      spec.hasAxis = true;
      spec.value = v;                    // 판정 축으로 환산한 값
      spec.min = sc.min; spec.max = sc.max;
      spec.okMin = okLo; spec.okMax = okHi;
      spec.anchorText = anchorText;
      spec.anchorAt = anchorAt;
      spec.methodName = mname || null;
    }
    return spec;
  }

  /* 지금 값 줄(`r.key`) ↔ 주간 계열 짝짓기.
   *
   * **키 어휘가 둘이다.** 지금 값은 채널 표시 키(`T`·`RH`·`VPD`, 매핑에 없는
   * 채널은 사람이 붙인 이름)로 오고 계열은 measurement 이름으로 온다. 그래서
   * **서버가 후보를 함께 싣는다**(`now_keys`) — 여기서 이름을 다시 만들면
   * 규칙이 두 벌이 되고, 갈라지는 날 조용히 안 맞는다.
   *
   * 실외(outdoor) 계열은 짝짓지 않는다. 카드의 지금 값 줄은 실내 기준이라,
   * 같은 measurement 라는 이유로 실외 계열을 붙이면 안쪽 값 위에 바깥
   * 그림이 그려진다. */
  function _weekSeriesFor(key, week) {
    if (!key || !week || !week.length) return null;
    for (var i = 0; i < week.length; i++) {
      var w = week[i];
      if (String(w.scope || 'indoor') !== 'indoor') continue;
      var keys = w.now_keys || [];
      for (var j = 0; j < keys.length; j++) {
        if (String(keys[j]) === String(key)) return w;
      }
    }
    return null;
  }

  /* 값 풍선 문구 — **빌더는 문구를 만들지 않는다**(dataviz 규약)는 규칙이
   * 있어 부르는 쪽인 여기서 만든다. 짚었을 때 최저~최고와 평균을 함께 준다:
   * 막대는 진폭만 그리므로 가운데가 어디였는지는 여기서만 알 수 있다. */
  function _weekTip(p, name, unit) {
    if (!p || p.avg == null && p.min == null) return null;
    var u = unit ? ' ' + unit : '';
    var span = (p.min != null && p.max != null && p.max > p.min)
      ? p.min + '~' + p.max + u : null;
    var avg = (p.avg != null) ? _t('mean') + ' ' + p.avg + u : null;
    return [p.label, span, avg].filter(Boolean).join(' \u00b7 ');
  }

  function _envNowRowHtml(r, opts) {
    opts = opts || {};
    var V = window.AoTViz;
    var s = envRowSpec(r, opts);
    if (!s) return '';
    var isRep = !!(opts.repKey && r.key === opts.repKey);
    // 지정 가능할 때만 버튼처럼 보이게 한다 — 권한이 없는 사람에게 눌리는
    // 시늉을 보여 주면 눌러 보고 아무 일도 안 일어나는 것을 겪는다.
    var hint = isRep ? _t('Representative measurement')
                     : (opts.selectable ? _t('Set as representative') : '');
    var name = s.name, dec = s.dec, unit = s.unit;

    var inner;
    var wk = _weekSeriesFor(r.key, opts.week);
    if (V && wk && V.range) {
      // ── 지난 며칠 안에서 오늘은 어디인가 ─────────────────────────────
      //
      // 지금 값 하나만 그리던 자리다. 그런데 그것은 같은 모달의 [환경·제어]
      // 탭이 24시간 그래프로 이미 답한다 — 사용자 지적: *"사실상 환경/제어
      // 탭에서 지금 상태를 거의 다 확인할 수 있는 중복 데이터를 다른 형식으로
      // 보여주는 것 뿐임"*. 이 줄이 따로 있을 이유는 **더 넓은 창**이다.
      //
      // 머리줄의 숫자는 여전히 **지금 값**이다(계열의 대표값이 아니라) —
      // "지금 몇 도인가" 를 잃지 않으면서 그 옆에 지난 며칠을 세운다.
      inner = V.range({
        label: name,
        valueText: s.valueText, valueSub: unit, stale: s.stale,
        scale: wk.scale, targets: wk.targets, bars: !!wk.bars,
        points: (wk.points || []).map(function (p) {
          return { label: p.label, min: p.min, max: p.max, avg: p.avg,
                   tip: _weekTip(p, name, unit) };
        })
      });
    } else if (V && s.hasAxis) {
      inner = V.band({
        label: name,
        value: s.value,
        valueText: s.valueText,
        valueSub: unit,
        min: s.min, max: s.max,
        okMin: s.okMin, okMax: s.okMax,
        stale: s.stale,
        // **축의 끝을 적지 않는다.** 밴드 축의 양 끝(10~45°C 등)은 5단계 색을
        // 나누려고 정한 값이라 사람이 읽을 뜻이 없고, 기준 라벨이 그 자리로
        // 움직이다 보면 끝 숫자와 겹쳐 "0.40 0.80–1.20" 처럼 한 덩어리로
        // 읽힌다. 이 줄에서 알아야 하는 것은 **기준과 지금 위치**뿐이다.
        scale: [ { text: s.anchorText, anchor: true, at: s.anchorAt } ],
        // ── 3행 오른쪽: 이 측정의 **추세** ────────────────────────────────
        // 값과 방향은 함께 읽어야 뜻이 선다 — 32.8°C 가 괜찮은지는 오르는
        // 중인지 내리는 중인지로 갈린다. 카드 하나로 몰아 두면 어느 줄의
        // 추세인지 눈으로 이어붙여야 하지만, 여기서는 자기 값 바로 아래다
        // (2026-08-26 지적).
        scaleNote: s.trendNote
      });
    } else if (V) {
      // 축을 만들 수 없는 지표 — 값만 낸다. 다만 **추세는 범위를 몰라도 그릴 수
      // 있으므로**, 최근 값이 도착하면 이 자리를 스파크라인으로 바꾼다
      // (fillEnvSparklines). 표식만 남기고 여기서 조회하지 않는다 — 빌더는
      // 순수 함수다.
      inner = V.value({ label: name, valueText: s.valueText,
                        valueSub: unit, stale: s.stale,
                        className: 'aot-viz--sparkable' });
    } else {
      inner = _pRow(name, _esc(s.valueText + ' ' + unit));
    }

    return '<div class="aot-env-now-item' +
             (isRep ? ' is-rep' : '') +
             (opts.selectable ? ' is-selectable' : '') + '"' +
             ' data-rep-key="' + _esc(r.key) + '"' +
             (hint ? ' title="' + _esc(hint) + '"' : '') +
             (opts.selectable ? ' role="button" tabindex="0"' : '') + '>' +
             inner + '</div>';
  }

  // ── 카드 항목 고르기 ───────────────────────────────────────────────────
  //
  // 시설이 커지면 [현재]와 [제어 상태]에 줄이 계속 늘어난다 — 센서를 하나 더
  // 달거나 액추에이터 종류가 하나 늘 때마다다. 그런데 **무엇이 볼 값인지는
  // 그 자리를 쓰는 사람만 안다**(노지에 실내 습도, 창이 없는 시설에 환기 면적).
  // 그래서 화면이 순서를 더 똑똑하게 정하려 애쓰는 대신, 빼는 손잡이를 준다.
  //
  // **거르는 것은 화면이 한다.** 서버는 감춘 항목도 계속 보낸다 — 응답에서
  // 빼 버리면 설정 창이 "무엇을 감출 수 있는지" 를 목록으로 만들 수 없어
  // 다시 켤 방법이 사라진다.
  /* 카드 제목 옆 손잡이 — **글자가 아니라 점 세 개**다.
   *
   * "설정" 이라고 적으면 카드마다 제목 옆에 글자가 하나씩 더 서서, 제목줄이
   * 두 낱말로 읽힌다("현재 설정"). 카드에서 읽어야 할 것은 제목과 값이지
   * 손잡이가 아니다. 점 세 개는 어느 언어에서도 같은 폭이고 번역이 필요 없다.
   *
   * **글자를 지웠으니 이름은 `aria-label` 이 진다** — 그림만 남은 버튼은
   * 스크린리더에서 "버튼" 으로만 읽힌다. `title` 은 마우스에게만 보인다. */
  function _cardCfgBtn(card) {
    var label = _t('Choose which items to show');
    return '<button type="button" class="aot-ov-cardcfg"' +
           ' data-card-cfg="' + _esc(card) + '"' +
           ' aria-label="' + _esc(label) + '"' +
           ' title="' + _esc(label) + '">' +
           '\u22ef</button>';
  }

  function _hiddenSet(list) {
    var out = {};
    (list || []).forEach(function (k) { out[k] = true; });
    return out;
  }

  /* 이 카드가 **지금 낼 수 있는** 줄 전부 — 감춘 것도 들어간다.
   *
   * 있지도 않은 항목까지 늘어놓지 않는 이유: 목록이 그 시설에 없는 센서로
   * 채워지면 사용자는 "여기 CO2 가 있었나" 를 먼저 의심한다. 반대로 감춘
   * 것을 빼면 다시 켤 수단이 없어진다. 그래서 기준은 "값이 오는가" 하나다.
   *
   * `extras` — 측정값이 아니라 파생값이라 `readings` 에 없는 줄(DLI·GDD).
   * 호출부가 **실제로 값을 낼 수 있을 때만**(`usable`) 채워서 넘긴다 — 여기서
   * 무조건 추가하면 위 "있지도 않은 항목" 규칙이 이 두 줄에서만 깨진다. */
  function envRowChoices(readings, extras) {
    var SL = window.AoTSensorLabel;
    var base = _envNowOrder(readings || []).map(function (r) {
      return { key: r.key,
               label: (SL && SL.keyDisplay) ? SL.keyDisplay(r.key) : r.key };
    });
    return base.concat(extras || []);
  }

  /* 제어 상태 카드의 줄. **경고는 목록에 없다** — 편차("못 따라감")와 안전
   * 게이트는 아래 숫자들이 왜 그런지의 이유라, 감출 수 있게 하면 카드가
   * 거짓말을 한다(냉각기 100% 만 남고 그것이 나쁜 신호라는 사실이 사라진다). */
  function controlRowChoices(summary) {
    summary = summary || {};
    var out = [];
    if ((summary.vent || {}).total_area_m2 > 0) {
      out.push({ key: 'vent', label: _t('Vent area open') });
    }
    Object.keys(summary.outputs_by_kind || {}).forEach(function (k) {
      out.push({ key: k, label: _t(_KIND_LABELS[k] || k) });
    });
    return out;
  }

  /* 설정 창 본문 — 예약 창과 **같은 골격**이다(스크롤 페인 + modal-footer).
   * opts: { title, items:[{key,label}], hidden:[key] } */
  function buildRowPickerHtml(opts) {
    opts = opts || {};
    var hidden = _hiddenSet(opts.hidden);
    var rows = (opts.items || []).map(function (it) {
      // 토글이 켜짐 = **보인다**. 감춤을 켜는 형태로 두면 "숨김 끄기" 를
      // 읽어야 하는 이중부정이 된다.
      return '<div class="aot-modal-option-row">' +
             '<div class="aot-modal-option-label">' + _esc(it.label) + '</div>' +
             '<div class="aot-modal-option-control">' +
             _slideToggle('aot-rowpick-toggle', '', it.key, !hidden[it.key],
                          ' data-row-key="' + _esc(it.key) + '"') +
             '</div></div>';
    }).join('');

    return buildModalHeader({ name: opts.title || _t('Settings') }) +
           '<div class="aot-bay-popup-pane">' +
             (rows
               ? '<div class="aot-modal-container">' + rows + '</div>'
               : '<div class="aot-ov-muted">' +
                 _esc(_t('Nothing to show here yet.')) + '</div>') +
           '</div>' +
           '<div class="modal-footer">' +
           '<button type="button" class="btn aot-pill-btn aot-rowpick-cancel">' +
             _esc(_t('Close')) + '</button>' +
           '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary ' +
             'aot-rowpick-save">' + _esc(_t('Save')) + '</button>' +
           '</div>';
  }

  /* 설정 창에서 꺼 둔 항목의 key 목록 — 저장할 값 그대로. */
  function readRowPicker(root) {
    var out = [];
    (root ? root.querySelectorAll('.aot-rowpick-toggle input') : []).forEach(
      function (inp) {
        if (!inp.checked && inp.dataset.rowKey) out.push(inp.dataset.rowKey);
      });
    return out;
  }

  /* 카드 제목의 [설정] 클릭 → onOpen(card).
   *
   * **`cards` 로 자기 카드만 건다.** 카드마다 목록의 출처가 다르고([현재]는
   * 측정값, [제어 상태]는 코디네이터 요약) 갱신 주기도 달라 거는 쪽이 둘이다.
   * 한쪽이 pane 안의 버튼을 전부 걸어 버리면 남의 카드에 **빈 목록을 아는
   * 핸들러**가 붙고, 나중에 제대로 건 핸들러와 둘이 같은 창을 서로 밀어낸다.
   *
   * 이미 건 버튼은 다시 걸지 않는다 — [현황]은 30초마다 다시 그려지는데,
   * 내용이 같으면 DOM 을 그대로 두므로(깜빡임 방지) 리스너만 쌓인다. */
  function wireCardConfig(root, cards, onOpen) {
    if (!root) return;
    (cards || []).forEach(function (card) {
      var btn = root.querySelector('[data-card-cfg="' + card + '"]');
      if (!btn || btn.dataset.cfgBound) return;
      btn.dataset.cfgBound = '1';
      btn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        onOpen(card);
      });
    });
  }

  // 축 눈금 숫자 — 정수는 소수점을 붙이지 않는다(0.4 는 붙이고 10 은 안 붙인다).
  function _fmtBand(v, dec) {
    if (v == null || isNaN(v)) return '';
    return (Math.abs(v - Math.round(v)) < 1e-9) ? String(Math.round(v))
                                                : (+v).toFixed(dec);
  }

  function buildEnvNowHtml(env, opts) {
    env = env || {};
    opts = opts || {};
    var readings = env.readings || [];
    var sensors = env.sensors || {};
    // **빈 블록을 통째로 지우지 않는다.** 예전에는 센서가 하나도 없으면 제목까지
    // 사라져, 사용자는 "현재" 라는 칸이 있다는 것조차 몰랐다 — 붙일 센서가 없는
    // 것인지 화면이 덜 그려진 것인지 구분할 수 없다.
    var _empty = (!readings.length && !sensors.total);

    // ── 적산온도(GDD)·광합성 지표(DLI) — 구획 기준 실측 (2026-08-30) ──────
    //
    // 아래 `_ph.dli_today`(광합성 블록)와 **다른 값이다** — 그쪽은 env_
    // coordinator 사이클 적분이라 자동제어 Function 이 있는 시설에서만 있고,
    // 이 값(`opts.dli`/`opts.gdd`)은 `plot_context.gdd_accumulated`/
    // `dli_accumulated` 로 구획 하나(또는 시설이면 그 시설의 대표 구획)
    // 기준으로 늘 계산된다 — 코디네이터 없는 시설·노지 구획에도 뜬다.
    //
    // `usable` 이 아니면(센서 없음·프로그램 없음 등) 이 카드에 아예 없는
    // 항목으로 본다 — 다른 측정 줄과 같은 "값이 오는가" 기준([설정] 목록
    // 주석 참조). **`hidden` 은 usable 과 별개로도 가린다** — 사람이 끈
    // 것은 값이 있어도 안 보인다(다른 측정 줄과 동일).
    var _dliUsable = !!(window.AoTViz && (opts.dli || {}).usable &&
                        (opts.dli || {}).value != null);
    var _gddUsable = !!(window.AoTViz && (opts.gdd || {}).usable &&
                        (opts.gdd || {}).value != null);

    var head = '<div class="aot-ov-card-title aot-ov-card-title--row">' +
               '<span>' + _esc(_t('Environment')) + '</span>' +
               '<span class="aot-ov-title-actions">';
    if (sensors.total && sensors.valid < sensors.total) {
      // 'Sensors' 를 쓰지 않는다 — 그 msgid 는 설정 화면에서 "센서류"(장치 분류)
      // 로 번역돼 있어 "센서류 2/3" 이 된다. 뜻이 다르면 msgid 를 나눈다.
      head += '<span class="aot-ov-degraded">' +
              _esc(_t('Sensors responding')) + ' ' +
              sensors.valid + '/' + sensors.total +
              '</span>';
    }
    // 낼 줄이 하나도 없으면 [설정]도 두지 않는다 — 열어 봐야 빈 목록이다.
    if (opts.configurable && (readings.length || _dliUsable || _gddUsable)) {
      head += _cardCfgBtn('now');
    }
    head += '</span></div>';

    // **감추는 것은 여기서만 한다.** 서버는 감춘 항목도 계속 보낸다(설정 창이
    // 목록을 만들려면 그래야 한다).
    var hidden = _hiddenSet(opts.hidden);
    var shown = readings.filter(function (r) { return !hidden[r.key]; });

    // 이 둘은 **0 에서 목표까지 채우는 값**이다(오늘의 DLI·재배 시작일부터의
    // 누적 GDD) — `AoTViz.bullet()` 자신의 예시가 "누적 GDD" 를 정확히 이
    // 용도로 든다("쌓아서 도달하는 목표에만 쓴다"). `value()`(트랙 없는 값만)
    // 대신 이걸 쓰면 채워진 만큼이 곧 "목표까지 얼마나 왔나" 를 보여준다.
    //
    // 시간창이 서로 다르다는 것을 **단위 옆 괄호가 아니라** 눈금 줄의 덧말
    // (`scaleLead`)로 말한다 — 한 줄에 라벨·값·단위·주석을 다 우겨넣으면
    // 읽기 전에 먼저 걸러내야 한다.
    var _dliRowHtml = '';
    var _gddRowHtml = '';
    if (_dliUsable && !hidden.DLI) {
      var _dli = opts.dli;
      _dliRowHtml = '<div class="aot-env-now-item">' + window.AoTViz.bullet({
        label: _t('DLI'),
        value: _dli.value, target: _dli.target,
        valueText: String(_dli.value),
        valueSub: (_dli.target != null ? ' / ' + _dli.target : '') + ' mol/m²',
        scaleLead: _t('Today'),
        scaleNote: _dli.assumed ? _t('Estimated') : null
      }) + '</div>';
    }
    // ── 못 낼 때는 **왜인지 말한다** ──────────────────────────────────
    //
    // 예전에는 `usable` 이 아니면 줄을 통째로 지웠다. 그런데 실측에서 구획
    // 44개 중 **36개가 그 상태**였고(프로그램 없음 19 · 기준온도 없음 11 ·
    // 자료 부족 5 · 온도 센서 없음 1), 화면에는 아무것도 안 나오니 "적산온도가
    // 계산되지 않는다" 로 읽힌다 — 실제로 그 보고를 받았다. 계산은 맞게 돌고
    // 있었고, 없는 것은 **근거**였다.
    //
    // 다만 이유마다 사람이 할 일이 다르므로 문장도 다르다. `no-program` 은
    // 여기서 말하지 않는다 — 프로그램 칸이 이미 비어 있어 같은 말을 두 번
    // 하게 된다.
    var _gddReason = (opts.gdd || {}).reason;
    if (!_gddUsable && !hidden.GDD && _gddReason && _gddReason !== 'no-program'
        && _gddReason !== 'too-early' && _gddReason !== 'not-started') {
      var _why = null;
      if (_gddReason === 'no-t-base') {
        // 지어내지 않는다 — 작물마다 다르고, 틀리면 적산이 통째로 어긋나는데
        // 에러가 안 난다. 어디서 정하는지를 알려주는 것이 할 수 있는 전부다.
        _why = _t('Set a base temperature in the program to see this.');
      } else if (_gddReason === 'no-temperature-sensor') {
        _why = _t('No temperature sensor covers this plot.');
      } else if (_gddReason === 'low-coverage') {
        // **값은 있다.** 숨기면 사람은 고장으로 읽는다 — 오래된 값을 숨기지
        // 않고 흐리게 두는 규칙(측정값 신선도)과 같은 판단이다.
        _why = _t('%(v)s so far, but only %(pct)s of the days have data.')
                 .replace('%(v)s', String((opts.gdd || {}).value))
                 .replace('%(pct)s', String((opts.gdd || {}).coverage_pct) + '%');
      }
      if (_why) {
        _gddRowHtml = '<div class="aot-ov-now-note">' +
                      _esc(_t('GDD')) + ' — ' + _esc(_why) + '</div>';
      }
    }
    if (_gddUsable && !hidden.GDD) {
      var _gdd = opts.gdd;
      // 목표(target) — 프로그램의 하루 권장 GDD × 지난 날수(plot_context.
      // gdd_accumulated 가 이미 환산해 낸다). 없는 프로그램도 정상이라
      // 그때는 DLI 처럼 현재값만 보인다.
      _gddRowHtml = '<div class="aot-env-now-item">' + window.AoTViz.bullet({
        label: _t('GDD'),
        value: _gdd.value, target: _gdd.target,
        valueText: String(_gdd.value),
        valueSub: (_gdd.target != null ? ' / ' + _gdd.target : '') + ' °C·d',
        scaleLead: _t('Cumulative since start')
      }) + '</div>';
    }

    var body;
    if (shown.length || _dliRowHtml || _gddRowHtml) {
      var _rows = _envNowOrder(shown)
        .map(function (r) { return _envNowRowHtml(r, opts); });
      // 둘 다 카드 맨 위, DLI 바로 아래에 GDD — 목표 대비 진행을 보여주는
      // 파생값 둘을 나란히 묶어 다른 측정 줄과 구분한다.
      var _derived = [_dliRowHtml, _gddRowHtml].filter(Boolean);
      _rows = _derived.concat(_rows);
      body = '<div class="aot-env-now aot-viz-group">' + _rows.join('') + '</div>';
    } else if (readings.length || _dliUsable || _gddUsable) {
      // 값은 오는데 전부 꺼 둔 상태(DLI/GDD 도 포함). "측정값 없음" 이라고
      // 적으면 센서가 죽은 줄 안다 — 그것은 지금 상태가 아니라 사용자가 정한
      // 것이다.
      body = '<div class="aot-ov-muted">' +
             _esc(_t('All items in this card are hidden.')) + '</div>';
    } else {
      body = '<div class="aot-ov-muted">' +
             _esc(_empty ? _t('No sensors are linked to this place yet.')
                         : _t('No sensor readings')) + '</div>';
    }

    // 바깥 — 시설에만 있다(구역은 실내/실외 구분이 없다). 한 줄로 붙이는 이유:
    // 안이 더운 것이 문제인지 그냥 바깥이 더운 날인지는 둘을 나란히 놔야
    // 판단할 수 있는데, 값을 크게 넣으면 실내값과 구분이 안 된다.
    // ── 광합성 지표도 이 카드다 (2026-08-26) ──────────────────────────────
    // 따로 카드를 두었는데 그 안의 줄도 전부 "지금 값 / 목표" 였다 — [환경]과
    // 같은 질문에 답하면서 카드만 갈라져 있었다.
    // 남는 것은 **센서로 재지 못하는 축**뿐이다 — 광량·CO2·DLI·효율.
    //
    // ⚠ **공용 프리미티브로 만든다**(components/aot-dataviz.css 규약).
    // 축을 그릴 수 있으면 `band`, 없으면 `value` 다. 손수 `.aot-ov-row` 를
    // 짜면 같은 카드 안에서 글자 크기가 위 측정줄과 갈리고, 줄 사이 간격과
    // 가로 구분선을 주는 `.aot-viz + .aot-viz` 규칙도 안 걸린다.
    var _V   = window.AoTViz;
    var _ph  = opts.photo || {};
    var _pht = opts.targets || {};
    var _phOpt = _ph.opt || {};
    var _phRows = [];
    // ⚠ **줄은 `.aot-env-now-item` 으로 감싼다**(aot-sensor-label.css 규약).
    // 줄 사이 구분선은 `.aot-env-now-item + .aot-env-now-item::before` 가
    // 그린다 — 감싸지 않으면 위 측정줄들과 나란히 서면서 선만 빠진다.
    function _phItem(inner) {
      _phRows.push('<div class="aot-env-now-item">' + inner + '</div>');
    }
    function _phValue(label, cur, target, unit) {
      if (cur == null && target == null) return;
      _phItem(_V.value({
        label: label,
        valueText: (cur != null ? String(cur) : '\u2014') +
                   (target != null ? ' / ' + target : ''),
        valueSub: unit
      }));
    }
    if (_ph.enabled && _V) {
      // 광량은 실외 일사에서 오므로 값이 늘 있다 — 축을 그릴 수 있으면 그린다.
      // 축의 끝은 **맑은 날 정오**(_LIGHT_FULL_SUN)로 고정한다. 그날 최대치로
      // 잡으면 축이 값 따라 늘어 언제나 절반쯤에 서 있는 것처럼 보인다.
      // 기준선은 작물의 광 반포화 상수(K_L) — 목표라기보다 **넘어야 할 선**이다.
      if (_ph.light != null) {
        var _lmax = Math.max(_LIGHT_FULL_SUN, _ph.light * 1.1);
        // ── 광량도 **적정 구간**으로 그린다 (2026-08-26) ──────────────────
        // 사람이 이 줄에서 알고 싶은 것은 "지금 정상 범위인가" 다. 기준선 하나
        // ("반포화 100")로는 그 답이 안 나온다 — 100 보다 크면 좋은 건지,
        // 얼마나 커야 충분한지, 너무 큰 건 아닌지를 말하지 못한다.
        //
        // 구간은 지어내지 않는다. 시스템이 이미 `K_L`(광 반포화 상수)을 주고
        // 있고, 광 응답이 직각쌍곡선(A/A_max = L/(K_L+L))이라 거기서 나온다:
        //
        //     L = 1×K_L  → 최대의 50%   ← 이 아래는 광이 확실한 제한 인자
        //     L = 3×K_L  → 75%
        //     L = 9×K_L  → 90%          ← 이 위로는 두 배 늘려도 5% 남짓
        //
        // 그래서 **K_L ~ 9×K_L** 을 적정 구간으로 둔다. 위쪽 끝을 두는 이유는
        // 남는 광이 공짜가 아니기 때문이다 — 그만큼 열이 되고, 광저해도 온다.
        // 온도·습도 줄과 같은 `okMin/okMax` 를 쓰므로 그림도 같다.
        var _lk  = _phOpt.light_k;
        var _lok = (_lk != null && _lk > 0)
                     ? { lo: _lk, hi: Math.min(_lk * 9, _lmax) } : null;
        _phItem(_V.band({
          label: _t('Light Level'),
          // ⚠ `value` 를 반드시 준다 — `valueText` 만 주면 마커를 놓을 자리를
          //   몰라 `is-empty` 로 빈 트랙이 나온다(실제로 그렇게 나왔다).
          value: _ph.light, valueText: String(_ph.light),
          valueSub: ' \u00b5mol/m\u00b2/s', min: 0, max: _lmax,
          okMin: _lok ? _lok.lo : null, okMax: _lok ? _lok.hi : null,
          // ⚠ **`at` 를 주지 않는다.** `band()` 의 `at` 은 **축 위의 값**이고
          // (`pct(it.at, min, max)` 로 환산한다) 백분율이 아니다. 여기서는
          // 백분율을 넘기고 있어서 그 숫자가 다시 값으로 읽혔다 — 구간
          // 100~2000 의 한가운데(57.5%)가 축 0~2000 위의 값 57.5, 즉
          // **2.9% 자리**가 되어 라벨이 카드 왼쪽 끝에 붙었다.
          //
          // 기준이 적정 구간뿐일 때는 `at` 을 비우는 것이 이 카드의 규약이다
          // — 온·습도·VPD 줄도 그렇게 하고(`anchorAt = null`), `band()` 가
          // 초록 구간 한가운데에 붙인다. 값을 손으로 계산하면 그 계산이
          // `band()` 의 것과 갈릴 자리가 하나 더 생긴다.
          scale: (_lok
                  ? [{ text: _t('Range') + ' ' +
                             Math.round(_lok.lo) + '\u2013' + Math.round(_lok.hi),
                       anchor: true }]
                  : [])
        }));
      }
      // ⚠ **CO2 는 잴 수 없으면 내지 않는다.** "— / 600" 은 목표만 알려 줄 뿐
      // 지금 어떤지는 아무 말도 못 한다 — 값이 없는 칸이 남아 사용자가 매번
      // "왜 비어 있지" 를 다시 묻게 된다(2026-08-26 지적).
      if (_ph.co2 != null) {
        _phValue('CO2', _ph.co2, _pht.co2 != null ? _pht.co2 : _phOpt.co2_k, ' ppm');
      }
      _phValue('DLI', _ph.dli_today, _ph.dli_target, ' mol/m\u00b2/d');
      if (_ph.rate_rel_pct != null) {
        _phItem(_V.value({ label: _t('Photosynthesis rate'),
                           valueText: String(_ph.rate_rel_pct), valueSub: '%' }));
      }
    }
    // 측정 줄과 **같은 묶음**에 넣는다 — 줄 사이 간격(32px)과 가로 구분선은
    // `.aot-viz + .aot-viz` 가 준다. 따로 감싸면 그 규칙이 끊긴다.
    if (_phRows.length && body.slice(-6) === '</div>') {
      body = body.slice(0, -6) + _phRows.join('') + '</div>';
    }

    var outdoor = (env.outdoor || []).filter(function (r) {
      return r && r.value != null;
    });
    if (outdoor.length) {
      body += '<div class="aot-ov-trend">' + _esc(_t('Outdoor')) + ' ' +
              outdoor.map(function (r) {
                var dec = (window.AoTSensorLabel && window.AoTSensorLabel.defaultDecimals)
                  ? window.AoTSensorLabel.defaultDecimals(r.key) : 1;
                return _esc((+r.value).toFixed(dec) + (r.unit || ''));
              }).join(' · ') + '</div>';
    }
    // 식별 클래스 — 폴링마다 이 블록만 골라 비교·교체하기 위한 것이다
    // (없으면 [현황] 전체를 갈아엎어야 하고, 그러면 화면이 깜빡인다).
    //
    // **제목·박스를 `.aot-ov-card` 하나로 감싼다.** 제목이 박스 밖으로
    // 나가며(2026-08-20) 이 함수의 반환값이 형제 노드 둘(제목 div + 박스
    // div)이 됐다 — 호출부가 이 문자열을 그대로 `html +=` 로 이어붙이는
    // 자리는 문제가 없지만, `_prependFacilityEnvNow`(시설 위젯)처럼
    // **독립 조각으로 파싱해 `firstElementChild` 하나만 꺼내 교체**하는
    // 자리는 제목 div만 남고 박스(진짜 값)는 통째로 버려진다 — 시설
    // [현재] 카드가 스타일도 내용도 깨진 것으로 보였던 원인이 이것이다.
    // 감싸면 파싱해도 뿌리 노드가 하나라 안전하다.
    return '<div class="aot-ov-card">' + head +
           '<div class="aot-ov-block aot-ov-envnow">' + body + '</div></div>';
  }

  // 현재 블록의 값 클릭 → 대표 지정. onPick(key|null) 로 넘긴다.
  //
  // 이미 대표인 것을 다시 누르면 **해제**다(null). 지정을 되돌릴 방법이 없으면
  // 한 번 잘못 누른 사람이 원래대로 돌아갈 길이 없다.
  // 배경은 서버 응답을 기다리지 않고 먼저 옮긴다 — 누른 것이 바로 켜지지
  // 않으면 안 눌린 줄 알고 다시 누른다. 실패하면 onPick 쪽이 되돌린다.
  //
  // **한 root 에 한 번만 건다.** 시설 [현황]은 30초마다 다시 렌더되는데
  // pane 요소 자체는 그대로 재사용된다 — 렌더마다 리스너를 더하면 클릭 한 번에
  // 핸들러가 두 번 돌아 지정을 켰다 껐다 해서 **해제가 안 먹는다**(실제로
  // 겪음). 콜백만 갈아 끼우고 리스너는 최초 한 번만 건다.
  /* 축이 없는 줄을 **스파크라인**으로 바꾼다.
   *
   * 축(적정 범위)을 만들 수 없는 지표는 값 하나로는 좋은지 나쁜지 말할 수 없다.
   * 그런데 추세는 범위를 몰라도 그릴 수 있다 — "612ppm" 은 판단할 수 없어도
   * "오르는 중" 은 값 몇 개면 보인다.
   *
   * ## 센서가 **하나일 때만** 그린다
   *
   * `readings` 의 값은 그 key 를 가진 센서들의 **평균**이다(`n` 이 그 개수).
   * n>1 인데 센서 하나의 이력을 그리면 위의 숫자와 아래 선이 서로 다른 것을
   * 말하게 된다 — 평균은 올라가는데 선은 내려가는 화면이 나올 수 있다.
   * 이력을 평균 내어 맞출 수도 있지만, 그러면 화면이 서버의 집계 규칙(신선도
   * 판정 포함)을 다시 구현하는 것이 된다.
   *
   * ## 조회는 한 번에 묶는다
   *
   * `/data_batch` 의 `kind:'past'` 를 쓴다(센서 팝업 차트와 같은 경로).
   * 실패하면 조용히 지나간다 — 스파크라인은 덤이고, 없다고 값이 사라지면 안 된다.
   */
  var _SPARK_PAST_S = 6 * 3600;      // 6시간 — 하루 주기 센서도 두어 점은 잡힌다
  var _SPARK_MAX_PTS = 24;           // 좁은 폭에 24점이면 모양이 다 보인다

  // **순환값은 선으로 그리지 않는다.** 풍향 359° 와 0° 는 1도 차이인데 세로축
  // 에서는 정반대 끝에 놓인다 — 바람이 거의 안 바뀌어도 화면은 위아래로 요동친다.
  // 순환값의 추세를 그리려면 다른 그림(장미도·화살표)이 필요하고, 그것은 이
  // 프리미티브가 하는 일이 아니다.
  var _SPARK_SKIP_KEYS = { wind_deg: true };

  function _parseFirst(html) {
    var d = document.createElement('div');
    d.innerHTML = html;
    return d.firstElementChild;
  }

  function fillEnvSparklines(root, sensors, readings) {
    var V = window.AoTViz;
    if (!root || !V || !V.spark) return;
    var items = root.querySelectorAll('.aot-env-now-item');
    if (!items.length) return;

    var byKey = {};
    (readings || []).forEach(function (r) { byKey[r.key] = r; });

    var jobs = [];
    [].forEach.call(items, function (el) {
      if (!el.querySelector('.aot-viz--sparkable')) return;
      var key = el.dataset.repKey;
      if (_SPARK_SKIP_KEYS[key]) return;    // 순환값(위 주석)
      var r = byKey[key];
      if (!r || r.n !== 1) return;          // 평균이면 그리지 않는다(위 주석)
      for (var i = 0; i < (sensors || []).length; i++) {
        var sen = sensors[i];
        var chs = (sen && sen.channels) || [];
        for (var c = 0; c < chs.length; c++) {
          if (chs[c].key === key && chs[c].measurement_id) {
            jobs.push({ el: el, key: key, reading: r,
                        device_id: sen.unique_id,
                        measurement_id: chs[c].measurement_id });
            return;
          }
        }
      }
    });
    if (!jobs.length) return;

    var csrfEl = document.querySelector('meta[name="csrf-token"]');
    var items = jobs.map(function (j) {
      return { kind: 'past', unique_id: j.device_id,
               measure_type: 'input',
               measurement_id: j.measurement_id,
               period: String(_SPARK_PAST_S) };
    });
    // 공유 코얼레서 경유(없으면 예전 경로). 팝업은 지도 위젯의 값 갱신과 거의
    // 같은 순간에 뜨는 일이 많아, 같은 창에서 항목이 겹치면 한 번으로 합쳐진다.
    var sent = (window.AoTDataBatch && window.AoTDataBatch.postItems)
      ? window.AoTDataBatch.postItems(items).then(function (res) {
          return res ? { results: res } : null;
        })
      : fetch('/data_batch', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json',
                     'X-CSRFToken': csrfEl ? csrfEl.getAttribute('content') : '' },
          body: JSON.stringify({ items: items })
        }).then(function (r) { return r.ok ? r.json() : null; });

    sent
      .then(function (d) {
        var res = d && d.results;
        // 길이가 안 맞으면 정렬이 깨진 것이다 — 잘못 짝지어 그리면 CO2 자리에
        // 이슬점 모양이 들어간다. 그럴 바에는 안 그린다.
        if (!Array.isArray(res) || res.length !== jobs.length) return;
        jobs.forEach(function (j, i) {
          var series = res[i];
          if (!Array.isArray(series) || series.length < 2) return;
          var pts = series.map(function (p) {
            return Array.isArray(p) ? Number(p[1]) : Number(p);
          }).filter(function (v) { return isFinite(v); });
          if (pts.length < 2) return;
          if (pts.length > _SPARK_MAX_PTS) {
            // 균등 솎기 — 마지막 점(지금)은 반드시 남긴다.
            var step = pts.length / _SPARK_MAX_PTS, out = [];
            for (var k = 0; k < _SPARK_MAX_PTS; k++) {
              out.push(pts[Math.min(pts.length - 1, Math.floor(k * step))]);
            }
            out[out.length - 1] = pts[pts.length - 1];
            pts = out;
          }
          var oldEl = j.el.querySelector('.aot-viz--sparkable');
          if (!oldEl) return;
          var dec = (window.AoTSensorLabel && window.AoTSensorLabel.defaultDecimals)
                    ? window.AoTSensorLabel.defaultDecimals(j.key) : 1;
          var name = (window.AoTSensorLabel && window.AoTSensorLabel.keyDisplay)
                     ? window.AoTSensorLabel.keyDisplay(j.key) : j.key;
          var unit = (window.AoTSensorLabel && window.AoTSensorLabel.displayUnit)
                     ? window.AoTSensorLabel.displayUnit(j.reading.unit)
                     : (j.reading.unit || '');
          var node = _parseFirst(V.spark({
            label: name, valueText: (+j.reading.value).toFixed(dec),
            valueSub: unit, points: pts, stale: !!j.reading.stale
          }));
          if (node) oldEl.replaceWith(node);
        });
      })
      .catch(function () { /* 덤이다 — 실패해도 값은 그대로 남는다 */ });
  }

  function wireEnvNowPick(root, onPick) {
    if (!root || typeof onPick !== 'function') return;
    root._aotEnvPick = onPick;
    if (root._aotEnvPickWired) return;
    root._aotEnvPickWired = true;
    function pick(item) {
      var key = item.dataset.repKey;
      if (!key) return;
      var wasRep = item.classList.contains('is-rep');
      root.querySelectorAll('.aot-env-now-item.is-rep').forEach(function (el) {
        el.classList.remove('is-rep');
      });
      if (!wasRep) item.classList.add('is-rep');
      // 최신 콜백을 부른다 — 재렌더로 갈아 끼워졌을 수 있다.
      root._aotEnvPick(wasRep ? null : key);
    }
    root.addEventListener('click', function (e) {
      var item = e.target.closest('.aot-env-now-item.is-selectable');
      if (item && root.contains(item)) pick(item);
    });
    root.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var item = e.target.closest('.aot-env-now-item.is-selectable');
      if (item && root.contains(item)) { e.preventDefault(); pick(item); }
    });
  }

  // Zone [현황] 탭 — 지금 어떤가. 시설 [현황]과 같은 순서다(현재 환경 → 노트).
  //   zone: api_geo_zone_contents 응답의 zone 객체
  //         { unique_id, name, site_name, area_m2, counts, env, photo_url, can_edit }
  //
  // 사진·면적·개수는 여기 있지 않다 — [개요]로 옮겼다. 예전에는 이 탭 이름이
  // [상태]인데 내용은 정적 인벤토리여서, "지금 괜찮은가"를 물으러 온 사용자가
  // 면적과 개수를 읽고 나가야 했다.
  function buildZoneStatusHtml(zone, opts) {
    zone = zone || {};
    // 예정과 노트는 **한 블록**이다 — 식생과 같은 빌더. 계층마다 다른 모양을
    // 쓰면 사용자는 화면을 옮길 때마다 어디에 무엇이 있는지 다시 찾아야 한다.
    // **순서는 개념 계층이다** — 위치·시간 → 데이터 → 제어 → 기록물.
    // 큰 것에서 작은 것으로, 상위에서 하위로. 예전에는 "얼마나 행동을
    // 부르는가" 로 정렬했는데, 그 판단이 바뀔 때마다 순서가 흔들렸다.
    // 시설 [현황]도 같은 계층을 쓴다(계층이 같아야 사용자가 옮겨 다녀도
    // 같은 자리에서 같은 것을 찾는다).
    return buildZonePlotsHtml(zone.allocation) +
           buildEnvNowHtml(zone.env, opts) +
           buildRecordBlock(zone.schedule);
  }

  // ── 기록 — 예정과 지난 것을 한 블록에 ──────────────────────────────────
  //
  // **입구가 하나다.** 예전에는 같은 탭에 [추가](일정)와 [노트 열기]가 따로
  // 있어서, 사용자가 쓰기 **전에** "이건 노트인가 일정인가" 를 먼저 답해야
  // 했다. 그 구분은 저장 테이블 이름이지 사람이 아는 구분이 아니다 — 실제로
  // `action_type='note'` 인 일정과 `category='schedule'` 인 노트가 둘 다
  // 실데이터에 있다(계획서 §0).
  //
  // 읽기도 한 블록이다: 위가 예정, 아래가 지난 것(노트).
  //
  // **여기에 입력 폼은 없다.** 한때 '언제' 가 비면 노트, 채우면 예정으로
  // 갈리는 폼을 여기 뒀는데, 그것도 결국 **쓰기 전에** 사용자에게 종류를
  // 물었다(날짜 칸을 채울지 말지). 지금은 노트에만 쓰고, 쓴 뒤에 한 구간을
  // 골라 시각을 준다(노트 패널의 [이 부분을 예정으로]). 진입점은 하나다.
  //
  // **지나간 예정은 여기 넣지 않는다.** 지난 일정의 대부분은 기계가 남긴 실행
  // 기록이고(전체의 77%), 넣으면 사람이 쓴 것이 그대로 묻힌다 — 그것을 기본
  // 숨김으로 이미 정했다(/scheduler 토글). 여기서 되살리면 그 결정이 무의미해진다.
  //
  // 노트 부분은 **공용 컴포넌트가 그대로 그린다**(AoTNotesBlock.html({sub:true})).
  // 여기서 직접 그리면 노트로 들어가는 문이 두 벌이 된다.
  function buildRecordBlock(sched, opts) {
    opts = opts || {};
    var items = [].concat((sched && sched.own) || [],
                          (sched && sched.devices) || []);
    items.sort(function (a, b) {
      return String(a.when || '').localeCompare(String(b.when || ''));
    });

    // `.aot-ov-card` 로 제목+박스를 감싼다 — `_appendFacilitySchedule`(시설
    // 위젯)가 독립 조각으로 파싱해 `firstElementChild` 하나만 교체하므로,
    // 감싸지 않으면 제목 div만 남고 실제 기록·노트는 통째로 사라진다
    // (buildEnvNowHtml 의 같은 주석 참조).
    var html = '<div class="aot-ov-card">' +
      // 제목은 **'노트'** 다. '기록' 은 이 블록이 담는 것(예정·노트)을 아우르는
      // 말이지만, 사용자가 이 자리에서 하는 일은 노트를 읽고 쓰는 것 하나다 —
      // 다른 이름으로 부르면 [노트 열기] 버튼과 제목이 서로 다른 것을 가리키는
      // 것처럼 읽힌다. 모달마다 같은 말을 쓴다.
      '<div class="aot-ov-card-title">' + _esc(_t('Notes')) + '</div>' +
      '<div class="aot-ov-block aot-ov-record">';

    html += '<div class="aot-ov-sub-title">' + _esc(_t('Coming up')) + '</div>';
    if (!items.length) {
      html += '<div class="aot-ov-muted">' +
              _esc(_t('Nothing scheduled yet.')) + '</div>';
    }
    items.forEach(function (it) {
      html += '<div class="aot-ov-row"><span>' + _esc(it.content || '—') +
              (it.worker ? ' <span class="aot-ov-muted">· ' +
                           _esc(it.worker) + '</span>' : '') +
              '</span><span>' + _esc(_fmtWhen(it.when)) + '</span></div>';
    });

    // 표시 상한을 넘겼으면 **넘겼다고 말한다.** 안 그러면 사용자는 보이는
    // 것이 전부라고 읽고, "없는 것" 과 "안 보여준 것" 이 같은 화면이 된다.
    var total = (sched && sched.total) || 0;
    if (total > items.length) {
      html += '<div class="aot-ov-muted">' +
              _esc(_t('%(n)s more').replace('%(n)s',
                                            String(total - items.length))) +
              '</div>';
    }

    // 지난 것 = 노트. 소제목 단으로 낮춰 이 블록 안에 넣는다.
    html += (window.AoTNotesBlock
      ? window.AoTNotesBlock.html({ sub: true, title: _t('Up to now') })
      : '');
    return html + '</div></div>';
  }

  // ISO(앵커 tz 포함) → 사람이 읽는 짧은 시각. 오늘이면 시각만 낸다 —
  // 매 줄에 같은 날짜를 반복하면 정작 봐야 할 시간이 묻힌다.
  function _fmtWhen(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    var hm = String(d.getHours()).padStart(2, '0') + ':' +
             String(d.getMinutes()).padStart(2, '0');
    var now = new Date();
    if (d.toDateString() === now.toDateString()) return hm;
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + hm;
  }

  // ── 지금 심겨 있는 것 (구역 [현황]) ────────────────────────────────────────
  //
  // 농장 지도인데 계층 어디에도 작물이 없었다 — 구역 모달은 센서·장치·기능만
  // 알고 무엇이 자라는지는 몰랐다.
  //
  // **합계를 내지 않는다.** 겹침이 정상이라(간작·혼작, VP-3) 비율의 합이 100%를
  // 넘는 것이 맞는데, 합계를 띄우면 사용자는 그것을 오류로 읽는다. 미배정은
  // 서버가 **합집합**으로 뺀 값을 그대로 쓴다(단순 합으로 빼면 음수가 된다).
  function buildZonePlotsHtml(alloc) {
    if (!alloc) return '';
    var items = alloc.plots || [];
    var html = '<div class="aot-ov-card-title">' +
               _esc(_t('Plots')) + '</div>' +
               '<div class="aot-ov-block aot-ov-zone-plots">';

    if (!items.length) {
      html += '<div class="aot-ov-muted">' +
              _esc(_t('Nothing recorded in this zone.')) + '</div></div>';
      return html;
    }

    items.forEach(function (p) {
      var right = [];
      if (p.days_since_planted != null) {
        right.push(_esc(_t('Day %(n)s')
                        .replace('%(n)s', String(p.days_since_planted))));
      }
      // 면적이 아니라 **단계**를 낸다(2026-08-20). 면적은 심고 나면 안 바뀌어
      // 아무 날에 봐도 같은 숫자다 — [현황]은 "지금 어떤가" 를 묻는 자리인데
      // 거기서 변하지 않는 값이 가장 넓은 자리를 차지하고 있었다. 단계는 날마다
      // 옮겨 가고, 그것이 이 구역에서 지금 무슨 일이 일어나는지 말한다.
      //
      // 면적은 사라지지 않는다 — 구획 모달과 이 블록 아래의 '미배정' 줄이
      // 갖는다(그쪽은 "이 구역에 남은 자리" 라 구역 단위에서 뜻이 있다).
      //
      // 시설의 구획 목록과 **같은 어휘**다(buildFacilityPlotsHtml).
      // **단계 이름만.** 순번(3/6)은 목록에서 뜻을 만들지 못한다 — 전체가 몇
      // 단계인지 아는 사람만 읽을 수 있고, 여러 줄이 나란히 서면 서로 다른
      // 프로그램의 숫자가 비교되는 것처럼 보인다. 순번은 구획 모달이 갖는다.
      if (p.stage_name) right.push(_esc(p.stage_name));
      // 줄을 누르면 그 구획 모달로 내려간다(필지 → 구역과 같은 규약).
      html += '<div class="aot-ov-row aot-ov-plot-link' +
              (p.planned ? ' aot-ov-row--planned' : '') + '" ' +
              'data-plot-uuid="' + _esc(p.unique_id) + '" ' +
              'style="cursor:pointer"><span>' +
              _esc(p.subject || p.name || '—') +
              (p.variety ? ' <span class="aot-ov-muted">· ' +
                           _esc(p.variety) + '</span>' : '') +
              _plannedBadge(p) +
              '</span><span>' + right.join(' · ') + '</span></div>';
    });

    if (alloc.unassigned_m2 != null) {
      // 반올림해서 0%가 되면 퍼센트를 아예 뺀다 — "4.4 m² (0%)" 는 계산이
      // 틀린 것처럼 읽힌다. 남은 것이 있다는 사실은 면적이 이미 말한다.
      var _p = (alloc.zone_area_m2 > 0)
        ? Math.round(alloc.unassigned_m2 / alloc.zone_area_m2 * 100) : 0;
      var pct = _p > 0 ? ' (' + _p + '%)' : '';
      html += '<div class="aot-ov-row aot-ov-muted"><span>' +
              _esc(_t('Unassigned')) + '</span><span>' +
              _esc(Number(alloc.unassigned_m2).toLocaleString() + ' m²' + pct) +
              '</span></div>';
    }
    return html + '</div>';
  }

  // Zone [개요] 탭 — 이것의 정체는 무엇인가. 시설 [개요]와 같은 순서다
  // (사진 → 치수·소속 → 설명). 구역에는 설명 필드가 없어 두 블록뿐이다.
  /**
   * 시설(구역) 모달의 "지금 심겨 있는 것" — **제어 → 식생** 방향.
   *
   * 설정값을 보는 화면이 무엇을 기르는지 함께 말해야 그 값의 근거가 생긴다 —
   * 같은 25도가 상추에는 높고 토마토에는 적정이다. 이것이 없으면 식생은 기록으로
   * 남고 제어 화면과 만나지 않는다.
   *
   * `rows` 는 시설 런타임의 `plots`(시설 전체). 구역 뷰에서는 그 구역 것과
   * **구역이 지정되지 않은 것**(= 시설 전체에 심은 것)을 함께 낸다 — 그 작물도
   * 이 구역에서 자라고 있다(서버 `plots_in_facility` 와 같은 규칙).
   *
   * 면적·치수는 내지 않는다. 시설은 노지형·베드형·수직형에 따라 같은 바닥
   * 면적의 재배 규모가 전혀 다르다(서버도 내지 않는다).
   */
  // 기간 축 — 시작·현재·단계 경계를 한 줄로 보인다.
  //
  // 텍스트("8/17 시작 · 4일차 · 생육기 2/3")는 사람이 머릿속에서 배치해야
  // 알 수 있지만, 축은 보는 순간 안다. 계산은 서버가 한다
  // (`plot_context.timeline`) — 단계 길이·기준점·"끝까지" 처리가 전부 그쪽
  // 규칙이라 여기서 다시 조립하면 두 곳이 곧 갈린다.
  function _timelineHtml(tl) {
    if (!tl || !(tl.stages || []).length) return '';
    var pct = (tl.today_pct == null) ? 0 : tl.today_pct;
    var over = pct > 100;
    var V = window.AoTViz;
    if (!V) return '';          // 프리미티브가 없으면 축을 그리지 않는다
    // 목록 안의 한 줄이라 **머리줄(이름·값)을 만들지 않는다** — 바로 위에
    // 작물명과 일수가 이미 있고, 여기서 또 내면 같은 말이 두 번 선다.
    return V.timeline({
      segments: tl.stages.map(function (st) {
        return {
          span: Math.max(0, (st.to_pct || 0) - (st.from_pct || 0)),
          name: st.name,
          current: !!st.current
        };
      }),
      positionPct: Math.min(100, Math.max(0, pct)),
      scale: [
        String(tl.start || '').replace(/-/g, '/'),
        { text: over ? _t('Past the planned end') : _t('Today'), anchor: true },
        tl.end ? String(tl.end).replace(/-/g, '/') : _t('open-ended')
      ]
    });
  }

  // 구역 총량의 단위 어휘(p6_50). 자유 문자열을 쓰지 않는 이유는 번역과 집계가
  // 곧 갈리기 때문이다 — 어휘는 서버(`plot_context._CAPACITY_UNITS`)와 같은 다섯
  // 개로 고정하고 여기서는 표시 문구만 만든다.
  /**
   * 칸 아래 한 줄 안내 — **막다른 곳에 길을 놓는다.**
   *
   * 폼이 고를 수만 있고 만들 수는 없는 것들이 있다(프로그램·구역). 사용자는
   * 목록에 없는 것을 만나면 어디로 가야 하는지 모른 채 막힌다 — 그 순간 화면이
   * 알려 주지 않으면 기능이 없는 것과 같다.
   *
   * `href` 가 있으면 링크, 없으면 설명만. **링크는 설계 화면에 갈 수 있는
   * 사람에게만 보인다**(`can_design`) — 권한 없이 누르면 리다이렉트만 되고
   * 무엇이 잘못됐는지 알 수 없다.
   */
  function _fieldHint(text, href, canDesign) {
    if (!text) return '';
    var inner = _esc(text);
    if (href && canDesign) {
      inner = '<a href="' + _esc(href) + '">' + inner + '</a>';
    } else if (href && !canDesign) {
      return '';                 // 갈 수 없는 곳은 아예 말하지 않는다
    }
    return '<div class="aot-modal-option-row aot-ov-field-hint">' +
           '<div class="aot-modal-option-label"></div>' +
           '<div class="aot-modal-option-control">' + inner + '</div></div>';
  }

  /** 총량 칸의 라벨 — **단위에 따라 달라진다.**
   *
   * 예전에는 그냥 "전체" 였는데, 전체 면적을 적으라는 것인지 배정된 수량을
   * 적으라는 것인지 알 수 없다는 지적을 받았다. 단위를 이미 골랐으므로 그것을
   * 라벨에 넣으면 문장이 스스로 설명한다 — "전체 베드 수".
   */
  function _capTotalLabel(unit) {
    switch (unit) {
      case 'row':   return _t('Total rows');
      case 'tray':  return _t('Total trays');
      case 'area':  return _t('Total area (m\u00b2)');
      case 'house': return _t('Total houses');
      default:      return _t('Total beds');
    }
  }

  function _capUnitLabel(unit) {
    switch (unit) {
      case 'row':   return _t('rows');
      case 'tray':  return _t('trays');
      case 'area':  return _t('m\u00b2');
      case 'house': return _t('houses');
      default:      return _t('beds');
    }
  }

  /** 몫 한 조각 — "4/12 베드 · 33%" 또는 "33%". 없으면 빈 문자열. */
  function allocationText(a) {
    if (!a) return '';
    if (a.amount != null && a.total) {
      var s = a.amount + '/' + a.total + ' ' + _capUnitLabel(a.unit);
      if (a.percent != null) s += ' \u00b7 ' + a.percent + '%';
      return s;
    }
    if (a.amount != null) return String(a.amount);   // 총량을 아직 안 적었다
    if (a.percent != null) return a.percent + '%';
    return '';
  }

  // 아직 시작 전이라는 표식. **날짜가 아니라 남은 날**로 쓴다 — 날짜는 사람이
  // 오늘과 빼야 하고, 목록의 모든 줄에서 그 뺄셈이 반복된다.
  function _plannedBadge(p) {
    if (!p || !p.planned) return '';
    return ' <span class="aot-ov-planned">' +
           _esc(p.days_until_start != null
                ? _t('In %(n)s days').replace('%(n)s', String(p.days_until_start))
                : _t('Planned')) + '</span>';
  }

  function buildFacilityPlotsHtml(rows, bayId, opts) {
    opts = opts || {};
    var items = (rows || []).filter(function (p) {
      return !bayId || !p.bay_id || p.bay_id === bayId;
    });
    // 아무것도 없고 **심을 권한도 없으면** 블록을 만들지 않는다 — 창고·기계고처럼
    // 심는 것이 없는 시설에서 빈 칸이 매번 자리를 차지한다.
    //
    // 권한이 있으면 비어 있어도 낸다. 시설 구획은 기하를 그리지 않으므로 여기서
    // 만들 수 있어야 하고, 그러지 않으면 **지도만 쓰는 사람은 온실 식생을 아예
    // 관리할 수 없다** — 시설 편집기(geo/facility)까지 갈 수 있는 계정만 심을 수
    // 있게 되기 때문이다.
    if (!items.length && !opts.canEdit) return '';

    // `.aot-ov-card` 로 제목+박스를 감싼다 — `_appendFacilityPlots`(시설
    // 위젯)가 독립 조각으로 파싱해 `firstElementChild` 하나만 교체하므로,
    // 감싸지 않으면 제목 div만 남고 실제 구획 목록은 통째로 사라진다
    // (buildEnvNowHtml 의 같은 주석 참조).
    var html = '<div class="aot-ov-card">' +
               '<div class="aot-ov-card-title">' + _esc(_t('Plot')) + '</div>' +
               '<div class="aot-ov-block aot-ov-facility-plots">';
    if (!items.length) {
      html += '<div class="aot-ov-muted">' +
              _esc(_t('Nothing recorded here yet.')) + '</div>';
    }
    items.forEach(function (p) {
      var right = [];
      // **아직 시작 전이면 그 사실을 먼저 말한다.** 자라는 것과 예정된 것이 같은
      // 줄로 읽히면 "이 동에 지금 무엇이 있나" 라는 이 목록의 질문에 틀린 답을
      // 하게 된다. 날짜가 아니라 남은 날로 쓴다 — 날짜는 사람이 오늘과 빼야
      // 하고, 그 뺄셈이 목록의 모든 줄에서 반복된다.
      if (!p.planned && p.days_since_planted != null) {
        right.push(_esc(_t('Day %(n)s').replace('%(n)s',
                                                String(p.days_since_planted))));
      }
      // 단계는 일수보다 사람에게 직접적이다("32일차" 보다 "영양생장기").
      // 순번은 빼는 것이 구역 목록과 같은 규칙이다(위 주석) — 두 목록이
      // 달라지면 사용자가 옮겨 다닐 때마다 다시 읽어야 한다.
      if (p.stage_name) right.push(_esc(p.stage_name));
      // 몫 — 같은 구역에 여럿이면 이것이 서로를 가르는 유일한 표시다.
      var _al = allocationText(p.allocation);
      if (_al) right.push(_esc(_al));
      // 구역 뷰에서 "시설 전체" 인 것은 그렇다고 밝힌다 — 그러지 않으면 이 구역
      // 전용으로 읽힌다.
      if (bayId && !p.bay_id) right.push(_esc(_t('Whole facility')));
      html += '<div class="aot-ov-row aot-ov-plot-link' +
              (p.planned ? ' aot-ov-row--planned' : '') + '" ' +
              'data-plot-uuid="' + _esc(p.unique_id) + '" ' +
              'style="cursor:pointer"><span>' +
              _esc(p.subject || p.name || '—') +
              (p.variety ? ' <span class="aot-ov-muted">· ' +
                           _esc(p.variety) + '</span>' : '') +
              _plannedBadge(p) +
              '</span><span>' + right.join(' · ') + '</span></div>';
      html += _timelineHtml(p.timeline);
    });

    if (opts.canEdit) {
      // 심기 폼 — **공용 컴포넌트 한 벌**(`common/aot-plot-form.js`)을 쓴다.
      // 예전에는 이 화면·시설 편집기·geo/design 이 각자 적고 있어서 필드 집합이
      // 서로 달랐다(몫은 여기만, 프로그램은 여기만 없었다).
      // 기하를 묻지 않는 것이 시설 구획의 핵심이다: 구역을 고르는 것이 자리를
      // 정하는 일이다 — 그것은 `target: 'facility'` 가 정한다.
      var _fr = function (label, control) {
        return '<div class="aot-modal-option-row">' +
               '<div class="aot-modal-option-label">' + _esc(label) + '</div>' +
               '<div class="aot-modal-option-control">' + control + '</div></div>';
      };
      var formRows = (window.AoTPlotForm && window.AoTPlotForm.rowsHtml)
        ? window.AoTPlotForm.rowsHtml({
            attr: 'data-nf',
            target: 'facility',
            bays: opts.bays || [],
            bayId: bayId,
            capacities: opts.capacities || {},
            canDesign: opts.canDesign,
            today: opts.today || ''
          })
        : '';

      // 남은 몫 + 총량 설정. 총량이 없으면 "적어 두면 4/12 로 읽힌다" 를
      // 사람이 알 길이 없으므로 **없을 때도** 설정 버튼을 낸다.
      var capRow = '<div class="aot-ov-alloc-bar">' +
                   '<span class="aot-ov-muted aot-ov-alloc-left"></span>' +
                   '<button type="button" class="aot-ov-pill aot-ov-cap-edit">' +
                   _esc(_t('Bay capacity')) + '</button></div>' +
                   '<div class="aot-ov-cap-wrap" style="display:none">' +
                   '<div class="aot-modal-container">' +
                   _fr(_t('Unit'),
                       '<select class="aot-modern-input form-control" data-cf="unit">' +
                       '<option value="bed">' + _esc(_t('beds')) + '</option>' +
                       '<option value="row">' + _esc(_t('rows')) + '</option>' +
                       '<option value="tray">' + _esc(_t('trays')) + '</option>' +
                       '<option value="area">' + _esc(_t('m²')) + '</option>' +
                       '<option value="house">' + _esc(_t('houses')) + '</option>' +
                       '</select>') +
                   ('<div class="aot-modal-option-row">' +
                    '<div class="aot-modal-option-label aot-ov-cap-total-label">' +
                    _esc(_capTotalLabel('bed')) + '</div>' +
                    '<div class="aot-modal-option-control">' +
                    '<input type="number" min="0" step="any" ' +
                    'class="aot-modern-input form-control" data-cf="total" value="">' +
                    '</div></div>') +
                   '</div>' +
                   '<div class="aot-ov-desc-actions">' +
                   '<button type="button" class="aot-ov-pill aot-ov-cap-cancel">' +
                   _esc(_t('Cancel')) + '</button>' +
                   '<button type="button" class="aot-ov-pill aot-ov-pill--primary ' +
                   'aot-ov-cap-save">' + _esc(_t('Save')) + '</button>' +
                   '</div></div>';

      html += capRow +
              '<div class="aot-ov-actions">' +
              '<button type="button" class="aot-ov-pill aot-ov-plot-add">' +
              _esc(_t('Add a plot')) + '</button></div>' +
              '<div class="aot-ov-plot-new-wrap" style="display:none">' +
              '<div class="aot-modal-container">' + formRows +
              '</div>' +
              '<div class="aot-ov-desc-actions">' +
              '<button type="button" class="aot-ov-pill aot-ov-plot-new-cancel">' +
              _esc(_t('Cancel')) + '</button>' +
              '<button type="button" class="aot-ov-pill aot-ov-pill--primary ' +
              'aot-ov-plot-new-save">' + _esc(_t('Save')) + '</button>' +
              '</div></div>';
    }
    return html + '</div></div>';
  }

  // 대상·품종 라벨은 **종류에 따라 달라진다**(common/aot-plot-labels.js).
  // "품종" 은 생물에만 맞는 말이라 도로·시설물 구획에서는 틀린 말이 된다.
  function _plotSubjectLabel(p) {
    var k = (p && p.kind) || 'vegetation';
    return window.AoTPlotLabels ? window.AoTPlotLabels.subject(k)
                                : _t('What is here');
  }
  function _plotVarietyLabel(p) {
    var k = (p && p.kind) || 'vegetation';
    return window.AoTPlotLabels ? window.AoTPlotLabels.variety(k)
                                : _t('Variety');
  }

  /** 대상 종류 select — `GeoProgram.kind` 와 같은 어휘.
   *
   * 구획을 만드는 화면이 종류를 못 고르면 서버가 받는 축이 화면에 없는
   * 반쪽이 된다(가축 프로그램을 만들어도 붙일 구획을 만들 수 없다).
   */
  function _kindSelect(attr, cur) {
    var labels = { vegetation: _t('Vegetation'), livestock: _t('Livestock'),
                   facility: _t('Facility'), other: _t('Other') };
    var out = '<select class="aot-modern-input form-control" ' + attr + '>';
    ['vegetation', 'livestock', 'facility', 'other'].forEach(function (k) {
      out += '<option value="' + k + '"' +
             (k === (cur || 'vegetation') ? ' selected' : '') + '>' +
             _esc(labels[k]) + '</option>';
    });
    return out + '</select>';
  }

  function buildZoneAboutHtml(zone) {
    zone = zone || {};
    var html = '';
    var counts = zone.counts || {};

    if (zone.photo_url || zone.can_edit) {
      html += '<div class="aot-ov-card-title">' + _esc(_t('Photo')) + '</div>' +
              '<div class="aot-ov-block aot-ov-photo-wrap">';
      if (zone.photo_url) {
        html += '<div class="aot-ov-photo"><img src="' + _esc(zone.photo_url) +
                '" alt="" loading="lazy"></div>';
      }
      if (zone.can_edit) {
        html += '<div class="aot-ov-photo-actions">' +
                '<input type="file" class="aot-ov-photo-input" accept="image/*"' +
                ' style="display:none">' +
                '<button type="button" class="aot-ov-pill aot-ov-photo-btn">' +
                _esc(zone.photo_url ? _t('Change Photo') : _t('Add Photo')) +
                '</button></div>';
      }
      html += '</div>';
    }

    function _zrow(label, val) {
      return '<div class="aot-ov-row"><span>' + _esc(label) + '</span>' +
             '<span>' + _esc(String(val)) + '</span></div>';
    }
    var rows = '';
    if (zone.site_name) rows += _zrow(_t('Site'), zone.site_name);
    if (zone.area_m2 != null) rows += _zrow(_t('Area'), (+zone.area_m2).toLocaleString() + ' m²');
    rows += _zrow(_t('Sensors'), String(counts.sensors || 0));
    rows += _zrow(_t('Devices'), String(counts.outputs || 0));
    rows += _zrow(_t('Functions'), String(counts.functions || 0));
    // 제목 없는 블록은 사진 블록 아래에 다섯 줄이 떠 있는 모양이 된다 —
    // 구획 모달의 "구획 정보" 와 같은 자리이므로 같은 방식으로 이름을 준다.
    html += '<div class="aot-ov-card-title">' + _esc(_t('Zone information')) +
            '</div><div class="aot-ov-block aot-ov-dims">' + rows + '</div>';

    return html;
  }

  // ── 장치(Output) 시작/종료 예약 ─────────────────────────────────────────────
  // 구역 모달에만 있던 "설정" 창을 공용화한 것. 구역·시설·장치 마커 팝업이
  // 모두 이 하나를 호출한다.
  //
  // 저장 경로는 두 갈래다.
  //  - 시작이 사실상 "지금"(≤60초 뒤): 데몬에 바로 duration 제어를 보낸다.
  //  - 시작이 미래: **서버 스케줄러**(/api/v1/scheduler/propose)에 등록한다.
  //    예전 구현은 setTimeout 이라 탭을 닫으면 그대로 사라졌다 — 등록해두고
  //    브라우저를 닫아도 실행되는 것이 사용자가 "예약"으로 기대하는 동작이다.
  //    등록이 실패한 경우에만 예전의 탭 바인딩 방식으로 폴백하고, 그때는
  //    "탭을 열어두어야 한다"고 분명히 알린다.
  //
  //   opts = { shell(html) → popup, outputId, channel, name, onApplied }
  //     shell : 중앙 모달 셸 팩토리(위젯의 _showFacilityCenterOverlay)
  // outputId → 마지막으로 고른 **작동 시간**(초). 새로고침하면 사라진다.
  // 종료 '시각' 을 기억하던 것을 바꿨다 — 같은 장치를 늘 같은 길이로 돌리는 쪽이
  // 흔하고("이건 항상 10분"), 시각을 기억하면 다음 날엔 이미 지난 시각이 된다.
  var _durMemory = {};

  function _csrf() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return (meta && meta.getAttribute('content')) || '';
  }

  function _pad2(n) { return (n < 10 ? '0' : '') + n; }

  // Date → 'YYYY-MM-DDTHH:MM' (naive wall clock, 오프셋 없음).
  // 스케줄러는 이 문자열을 **장치 로컬 시각**으로 해석한다
  // (routes_scheduler.api_propose_job → wall_to_utc, timezone-management.md §6).
  function _wallClockString(d) {
    return d.getFullYear() + '-' + _pad2(d.getMonth() + 1) + '-' + _pad2(d.getDate()) +
           'T' + _pad2(d.getHours()) + ':' + _pad2(d.getMinutes());
  }

  /**
   * 작기 종료 — **끝내는 일과 이어가는 일을 한 창에서** 정한다.
   *
   * 예전에는 `confirm()` 한 줄이었고 문구가 "지도에서 사라지고 이력으로만
   * 남습니다" 였다. 둘 다 틀렸다:
   *
   *  - 도형은 **지워지지 않는다.** `end_plot` 은 행도 기하도 남기고 종료일만
   *    적는다. 그런데 문구가 삭제로 읽혀 사람이 종료를 못 눌렀다.
   *  - 수확이 끝났다고 그 자리가 없어지지 않는다 — 휴지기·정지·다음 작기가
   *    이어진다. 종료와 생성을 따로 하게 두면 그 사이에 도형을 다시 그리고
   *    몫을 다시 적어야 하고(노지는 측량까지), 그 왕복이 곧 자리를 잃는 것이다.
   *
   * 그래서 [비워 둔다 / 쉬어 간다 / 이어서 심는다] 셋 중 하나를 고르게 한다.
   * 뒤 둘은 서버가 한 번에 처리한다(`/succeed`).
   */
  function openPlotEnd(opts) {
    opts = opts || {};
    var shell = opts.shell;
    var p = opts.plot || {};
    if (!shell || !p.unique_id) return;

    var today = new Date();
    var iso = function (d) {
      return d.getFullYear() + '-' +
             String(d.getMonth() + 1).padStart(2, '0') + '-' +
             String(d.getDate()).padStart(2, '0');
    };
    var endDefault = iso(today);

    var progOpts = '<option value="">' + _esc(_t('No program')) + '</option>';
    (p.program_choices || []).forEach(function (x) {
      progOpts += '<option value="' + _esc(x.unique_id) + '"' +
                  (x.unique_id === p.program_uuid ? ' selected' : '') + '>' +
                  _esc(x.name + (x.variety ? ' · ' + x.variety : '')) +
                  '</option>';
    });

    var _row = function (label, control) {
      return '<div class="aot-modal-option-row">' +
             '<div class="aot-modal-option-label">' + _esc(label) + '</div>' +
             '<div class="aot-modal-option-control">' + control + '</div></div>';
    };
    var _choice = function (val, label, note) {
      return '<label class="aot-pe-choice">' +
             '<input type="radio" name="aot-pe-next" value="' + val + '"' +
             (val === 'none' ? ' checked' : '') + '>' +
             '<span class="aot-pe-choice-text"><b>' + _esc(label) + '</b>' +
             (note ? '<span class="aot-ov-muted">' + _esc(note) + '</span>' : '') +
             '</span></label>';
    };

    var html =
      buildModalHeader({ name: _t('End this plot') + ' — ' + (p.subject || p.name || '') }) +
      '<div class="aot-bay-popup-pane">' +
        '<div class="aot-ov-block">' +
          _row(_t('End date'),
               '<input type="date" class="aot-modern-input form-control ' +
               'aot-pe-end" value="' + endDefault + '">') +
          _row(_t('Reason'),
               '<select class="aot-modern-input form-control aot-pe-reason">' +
               '<option value="harvested">' + _esc(_t('Harvested')) + '</option>' +
               '<option value="failed">' + _esc(_t('Lost')) + '</option>' +
               '<option value="replaced">' + _esc(_t('Replaced')) + '</option>' +
               '<option value="removed">' + _esc(_t('Removed')) + '</option>' +
               '</select>') +
        '</div>' +
        // **자리는 남는다.** 그 사실을 문장 하나로 먼저 말한다 — 이 창에서
        // 사람이 가장 알고 싶은 것이 "지워지나" 이기 때문이다.
        '<div class="aot-ov-card-title">' + _esc(_t('And then?')) + '</div>' +
        '<div class="aot-ov-block">' +
          '<div class="aot-ov-muted aot-pe-note">' +
            _esc(_t('The plot stays as history either way. Nothing is deleted.')) +
          '</div>' +
          _choice('none', _t('Leave it empty'),
                  _t('The place is free for something else.')) +
          _choice('rest', _t('Rest for a while'),
                  _t('Same place, no program — while it rests or gets ready.')) +
          _choice('next', _t('Start the next one'),
                  _t('Same place and share — pick what comes next.')) +
          '<div class="aot-pe-next-fields" style="display:none">' +
            _row(_t('Item'),
                 '<input type="text" class="aot-modern-input form-control ' +
                 'aot-pe-subject" value="">') +
            _row(_t('Program'),
                 '<select class="aot-modern-input form-control aot-pe-prog">' +
                 progOpts + '</select>') +
            _row(_t('Start date'),
                 '<input type="date" class="aot-modern-input form-control ' +
                 'aot-pe-start" value="">') +
          '</div>' +
        '</div>' +
        '<div class="aot-pe-status aot-ov-muted" style="text-align:center"></div>' +
      '</div>' +
      '<div class="modal-footer">' +
        '<button type="button" class="btn aot-pill-btn aot-pe-cancel">' +
          _esc(_t('Cancel')) + '</button>' +
        '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary ' +
          'aot-pe-ok">' + _esc(_t('End')) + '</button>' +
      '</div>';

    var popup = shell(html, 'plot-end-' + p.unique_id);
    var el = popup.getElement();
    var q = function (sel) { return el.querySelector(sel); };
    var endIn = q('.aot-pe-end');
    var fields = q('.aot-pe-next-fields');
    var subjIn = q('.aot-pe-subject');
    var progIn = q('.aot-pe-prog');
    var startIn = q('.aot-pe-start');
    var status = q('.aot-pe-status');

    // **"휴경" 은 중립어가 아니다** — 경작을 전제한 말이라 축사·시설에는 틀리다.
    // 종류마다 부르는 말이 따로 있고, 그 표는 `AoTPlotLabels` 한 곳에 있다.
    var restName = (window.AoTPlotLabels && window.AoTPlotLabels.resting)
      ? window.AoTPlotLabels.resting(p.kind) : _t('Resting');

    var mode = function () {
      var r = el.querySelector('input[name="aot-pe-next"]:checked');
      return r ? r.value : 'none';
    };
    // 시작일 기본값은 **종료 다음 날**이다. 같은 날로 두면 하루가 두 작기에
    // 걸치는데, 이 도메인은 겹침이 정상이라 서버가 막지 않는다 — 기본값이
    // 잘못되면 조용히 이상한 이력이 쌓인다.
    var nextDay = function () {
      var d = new Date((endIn.value || endDefault) + 'T00:00:00');
      if (isNaN(d)) return endDefault;
      d.setDate(d.getDate() + 1);
      return iso(d);
    };
    var sync = function () {
      var m = mode();
      fields.style.display = (m === 'next') ? '' : 'none';
      startIn.value = nextDay();
      // 이름은 **고쳐 쓸 수 있는 기본값**이다. 화면이 정한 말을 데이터에 박아
      // 넣지 않는다(휴지기를 부르는 말이 곳마다 다르다 — 정지·건조·전작 정리).
      //
      // 비워 두면 안 된다: 제출은 빈 칸을 원본 품목으로 폴백하므로, 화면은
      // 비었는데 저장되는 값은 다른 것이 된다.
      if (m === 'rest') {
        if (!subjIn.value || subjIn.value === p.subject) {
          subjIn.value = restName;
        }
      } else if (m === 'next') {
        if (!subjIn.value || subjIn.value === restName) {
          subjIn.value = p.subject || '';
        }
      }
    };
    el.querySelectorAll('input[name="aot-pe-next"]').forEach(function (r) {
      r.addEventListener('change', sync);
    });
    endIn.addEventListener('change', sync);
    sync();

    q('.aot-pe-cancel').addEventListener('click', function () {
      try { popup.remove(); } catch (e) {}
    });

    q('.aot-pe-ok').addEventListener('click', function () {
      var btn = this;
      var m = mode();
      var body = {
        ended_on: endIn.value || endDefault,
        reason: q('.aot-pe-reason').value || 'harvested'
      };
      var url = '/api/geo/plot/' + encodeURIComponent(p.unique_id) + '/end';
      if (m !== 'none') {
        url = '/api/geo/plot/' + encodeURIComponent(p.unique_id) + '/succeed';
        body.started_on = startIn.value || nextDay();
        if (m === 'rest') {
          body.subject = subjIn.value || restName;
          // 프로그램 **없음**을 명시한다. 키를 빼면 서버는 물려받는다.
          body.program_uuid = null;
          body.variety = null;
        } else {
          body.subject = subjIn.value || p.subject || '';
          body.program_uuid = progIn.value || null;
        }
      }
      btn.disabled = true;
      status.textContent = '';
      if (typeof opts.submit === 'function') {
        opts.submit(url, body, function (err) {
          btn.disabled = false;
          if (err) { status.textContent = err; return; }
          try { popup.remove(); } catch (e) {}
          if (typeof opts.onDone === 'function') opts.onDone(m);
        });
      }
    });
    return popup;
  }

  function openOutputSchedule(opts) {
    opts = opts || {};
    var shell = opts.shell;
    var outputId = opts.outputId;
    if (!shell || !outputId) return;
    if (!window.AoTTimeWheel) {
      console.warn('[AoT Map] AoTTimeWheel module not loaded');
      return;
    }
    var channel = parseInt(opts.channel || 0, 10) || 0;
    var name = opts.name || '';
    var now = new Date();
    var nowSec = (now.getHours() * 3600) + (now.getMinutes() * 60);
    var lastDur = Object.prototype.hasOwnProperty.call(_durMemory, outputId)
      ? _durMemory[outputId] : 0;

    // 입력은 '시작 시각 + 작동 시간'. 예전에는 시작/종료 두 시각이었는데, 장치에
    // 실제로 보내는 값은 duration 이라 사용자에게 역산을 시키는 셈이었고, 종료가
    // 시작보다 이르면 코드가 "다음 날이겠지" 라고 짐작해야 했다. 작동 시간을 직접
    // 받으면 그 짐작이 사라진다. 종료 시각은 아래 미리보기로 보여준다 — 종료로
    // 생각하는 사람도 답을 얻지만 입력하지는 않는다.
    var html =
      buildModalHeader({ name: name }) +
      // 본문은 공용 스크롤 페인 안에, 버튼은 그 **밖에** 둔다. 공용 중앙 모달은
      // 높이가 min(80vh,760px) 로 고정이고 overflow:hidden 이라, 본문이 넘치면
      // 조용히 잘리는 곳이 하필 저장 버튼이다(세로가 짧은 창에서 실제로 잘렸다).
      '<div class="aot-bay-popup-pane">' +
        '<div class="aot-wheel-pair">' +
          '<div>' +
            '<div class="aot-act-group-header">' + _esc(_t('Start time')) + '</div>' +
            '<div class="aot-sched-wheel aot-sched-wheel-start"></div>' +
          '</div>' +
          '<div>' +
            '<div class="aot-act-group-header">' + _esc(_t('Run time')) + '</div>' +
            '<div class="aot-sched-wheel aot-sched-wheel-dur"></div>' +
          '</div>' +
        '</div>' +
        '<div class="aot-ov-muted" style="text-align:center;margin:.2rem 0 .5rem">' +
        _esc(_t('00:00 = run indefinitely (no auto off)')) + '</div>' +
        '<div class="aot-sched-preview" style="text-align:center;margin:0 0 .5rem"></div>' +
        '<div class="aot-sched-warn"></div>' +
        '<div class="aot-sched-status aot-ov-muted" style="text-align:center;margin:0 0 .4rem"></div>' +
        // 지금 이 장치에 무엇이 걸려 있는지 — 저장 결과도 여기에 반영된다.
        // 별도 결과 화면을 띄우지 않는 이유: 창을 갈아 끼우면 방금 무엇을
        // 고쳤는지 대조할 수 없고, 다시 열었을 때 그 정보가 사라진다.
        '<div class="aot-sched-state"></div>' +
      '</div>' +
      // 하단은 설정 모달(.aot-option-modal)의 푸터를 그대로 쓴다 — 같은 클래스이면
      // 높이 50px·안전영역(iOS 홈 인디케이터) 여백·모바일 규칙까지 함께 따라온다.
      // 규칙은 aot-modal-modern.css 에서 .aot-center-modal 로 확장했다(복제 아님).
      // 순서·문구도 그쪽과 같게: [닫기][저장]. '취소' 가 아니라 '닫기' 인 이유는
      // 저장해도 창이 남기 때문이고, 바로 위 '예약 취소' 와도 구분된다.
      //
      // **기본 동작 하나만 강조한다.** 예전에는 [닫기]까지 primary 라 딥그린 두
      // 개가 나란히 서서, 오른쪽 끝이 기본 동작이라는 것이 화면에 안 보였다.
      // 같은 골격을 쓰는 geo/design 구획 모달이 이미 이 형태다(취소는 평범,
      // 저장만 primary) — 여기만 어긋나 있었다.
      '<div class="modal-footer">' +
      '<button type="button" class="btn aot-pill-btn aot-sched-cancel">' + _esc(_t('Close')) + '</button>' +
      '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary aot-sched-save">' + _esc(_t('Save')) + '</button>' +
      '</div>';

    var popup = shell(html, 'output-sched-' + outputId);
    var el = popup.getElement();
    var startWheel = window.AoTTimeWheel.mount(el.querySelector('.aot-sched-wheel-start'),
      { value: nowSec, fields: 'hm', onChange: function () { renderPreview(); } });
    var durWheel = window.AoTTimeWheel.mount(el.querySelector('.aot-sched-wheel-dur'),
      { value: lastDur, fields: 'hm', onChange: function () { renderPreview(); } });
    var previewEl = el.querySelector('.aot-sched-preview');
    var statusEl = el.querySelector('.aot-sched-status');
    var stateEl = el.querySelector('.aot-sched-state');
    var saveBtn = el.querySelector('.aot-sched-save');
    var cancelBtn = el.querySelector('.aot-sched-cancel');
    var warnEl = el.querySelector('.aot-sched-warn');
    var wheelsSeeded = false;
    // 겹침 판정용 — 서버가 말한 기존 예약.
    var known = [];

    // 서버에서 지금 상태를 가져와 '예약 상황' 블록을 그린다. 저장·취소 직후에도
    // 같은 함수를 부른다 — 화면에 보이는 예약은 언제나 **서버가 말한 것**이다.
    // 브라우저에 담아 두면 다른 사람·다른 기기에서 안 보이고, 예약은 브라우저를
    // 닫아도 실행되므로 화면만 모르는 상태가 된다.
    function loadState(seedWheels) {
      return _outputRuntime(outputId, channel).then(function (rt) {
        if (!stateEl.isConnected) return;
        stateEl.innerHTML = _schedStateHtml(rt);
        // 예약이 걸려 있으면 휠을 그 값으로 맞춘다 — 다시 열었을 때 걸려 있는
        // 예약이 곧 현재 설정으로 보이는 것이 자연스럽다. 한 번만 한다(저장
        // 직후에 다시 맞추면 사용자가 고르던 값을 덮어쓴다).
        known = (rt && rt.schedules) || [];
        renderPreview();
        var first = (rt && rt.schedules && rt.schedules[0]) || null;
        if (seedWheels && !wheelsSeeded && first && first.start_epoch) {
          wheelsSeeded = true;
          var d = new Date(first.start_epoch * 1000);
          startWheel.set(d.getHours() * 3600 + d.getMinutes() * 60);
          durWheel.set(first.duration_sec || 0);
          renderPreview();
        }
        _wireSchedState(stateEl, statusEl, outputId, channel, loadState);
      })
      // 조용히 실패하면 "예약 상황" 이 빈 채로 남아 예약이 없는 것과 구별되지
      // 않는다. 실제로 그랬다 — set() 이 없던 옛 캐시본에서 TypeError 가 나
      // 블록만 그려지고 휠 반영이 멈췄는데 화면에는 아무 표시가 없었다.
      .catch(function (e) {
        if (statusEl) statusEl.textContent = _t('Failed');
        try { console.warn('[AoT Map] schedule state load failed', e); } catch (_e) {}
      });
    }
    loadState(true);

    // 고른 값이 실제로 무엇을 뜻하는지 저장 전에 보여준다 — 시작이 이미 지난
    // 시각이면 "지금", 작동 시간 0 이면 자동 꺼짐 없음.
    function renderPreview() {
      if (!previewEl) return;
      var plan = _planSchedule(startWheel.read(), durWheel.read());
      var when = plan.immediate ? _t('immediately') : _fmtClock(plan.start);
      var line = when + ' → ' +
        (plan.durationSec === null
          ? _t('no auto off')
          : _fmtClock(plan.end) + ' (' + _fmtRunLen(plan.durationSec) + ')');
      previewEl.textContent = line;
      // 겹쳐도 막지 않는다(일부러 겹치게 두어야 하는 사정이 있다). 대신 실제로
      // 어떻게 되는지 미리 말한다 — 겹친 구간에서는 **먼저 끝나는 타이머**에
      // 함께 꺼진다(실측: 20초 예약이 도는 중 60초 명령을 주면 60초가 아니라
      // 20초 만료에 꺼졌다. 데몬이 이미 흐른 시간을 이어받아 계산한다).
      if (warnEl) {
        var ov = _overlapInfo(plan, known);
        warnEl.textContent = !ov ? ''
          : (ov.offAt
              ? _t('Overlaps an existing schedule — turns off at %(time)s')
                  .replace('%(time)s', _fmtClock(ov.offAt))
              : _t('Overlaps an existing schedule'));
      }
    }
    renderPreview();
    // 휠의 onChange 로만 다시 그린다. 예전에는 팝업의 click/touchend/wheel 을 받아
    // 그렸는데, 항목을 탭하면 smooth 스크롤이 **그 이벤트 뒤에** 진행되므로 그
    // 시점의 값은 아직 이전 선택이다 — 미리보기가 한 칸씩 늦게 따라왔다
    // (00:01 을 골라도 '자동 꺼짐 없음', 다시 00:00 으로 오면 직전 길이가 보였다).
    // 값이 확정되는 시점을 아는 곳은 휠뿐이다.
    // 초 단위로 흐르는 '지금' 도 미리보기에 걸려 있다(시작이 현재 분이면 즉시 실행).

    cancelBtn.addEventListener('click', function () { popup.remove(); });
    saveBtn.addEventListener('click', function () {
      var startSec = startWheel.read();
      var durSec = durWheel.read();
      _durMemory[outputId] = durSec;
      saveBtn.disabled = true;
      statusEl.textContent = _t('Saving...');
      _applySchedule(outputId, channel, name, startSec, durSec)
        .then(function (res) {
          // 창을 갈아 끼우지 않는다. 예전에는 결과 전용 화면으로 바꿨는데,
          // 방금 무엇을 고쳤는지 대조할 수 없고 다시 열면 그 정보가 사라졌다.
          // 지금은 한 줄 상태 + 아래 '예약 상황' 블록(서버에서 다시 읽은 것)이
          // 답한다 — 즉시 실행이라 예약 목록에 안 남는 경우도 그 블록의
          // '작동 중' 으로 드러난다.
          saveBtn.disabled = false;
          statusEl.textContent = (res && res.mode === 'scheduled')
            ? _t('Schedule registered')
            : (res && res.mode === 'tab-timer')
              ? _t('Scheduled — keep this tab open until the start time.')
              : _t('Turned on now');
          refreshOutputScheduleLabel(outputId, channel);
          loadState(false);
          if (typeof opts.onApplied === 'function') opts.onApplied(res);
        })
        .catch(function (e) {
          saveBtn.disabled = false;
          statusEl.textContent = (e && e.message) || _t('Failed');
        });
    });
  }

  function _fmtClock(d) {
    if (!(d instanceof Date)) return '';
    return _pad2(d.getHours()) + ':' + _pad2(d.getMinutes());
  }

  // 고른 작동 시간은 **휠과 같은 자리수**로 보여준다. _fmtDur 은 실제로 흐른
  // 시간(마지막 작동 시간)을 위한 HH:MM:SS 포맷터라, 분 단위로 고른 값에 쓰면
  // 설정하지도 않은 초 자리가 보인다("1분" 을 골랐는데 00:01:00).
  function _fmtRunLen(sec) {
    var t = Math.max(0, Math.round(+sec || 0));
    return _pad2(Math.floor(t / 3600)) + ':' + _pad2(Math.floor((t % 3600) / 60));
  }

  // 고른 구간이 기존 예약과 겹치는지. 겹치면 그 구간에서 먼저 끝나는 타이머의
  // 시각을 함께 돌려준다 — 사용자가 고른 종료 시각이 아니라 그때 꺼진다.
  // 작동 시간 00:00(무한)은 끝이 없으므로 이후 모든 예약과 겹친다.
  function _overlapInfo(plan, known) {
    if (!known || !known.length) return null;
    var s = plan.start.getTime();
    var e = (plan.durationSec === null) ? Infinity : plan.end.getTime();
    var ends = [];
    known.forEach(function (k) {
      if (!k || !k.start_epoch) return;
      var ks = k.start_epoch * 1000;
      // 지금 화면에 보이는 그 예약(= 방금 저장한 것)과 자기 자신을 겹친다고 하지
      // 않는다. **이 창에서 만든 예약 전부를 빼면 안 된다** — 하나 저장한 뒤 다른
      // 시각을 고를 때 그 예약과의 겹침을 못 보게 된다(실제로 그랬다).
      // 판정 기준은 "고른 구간과 정확히 같은가" 하나다.
      var sameStart = Math.abs(ks - s) < 60000;
      var sameDur = ((k.duration_sec || null) === plan.durationSec);
      if (sameStart && sameDur) return;
      var ke = k.duration_sec ? (ks + k.duration_sec * 1000) : Infinity;
      if (ks < e && s < ke) { ends.push(ke); }
    });
    if (!ends.length) return null;
    ends.push(e);
    var first = Math.min.apply(null, ends);
    return { offAt: isFinite(first) ? new Date(first) : null };
  }

  // 고른 시작 시각(초)+작동 시간(초) → 실제로 언제 무엇이 일어나는지.
  // UI 미리보기와 저장이 **같은 함수**를 쓴다 — 둘이 갈리면 화면에 보인 것과
  // 등록된 것이 달라진다.
  function _planSchedule(startSec, durSec) {
    var nowMs = Date.now();
    var n = new Date(nowMs);
    var start = new Date(n.getFullYear(), n.getMonth(), n.getDate(),
      Math.floor(startSec / 3600), Math.floor((startSec % 3600) / 60), 0, 0);
    var immediate = false;
    // 이미 지난 시각을 골랐다면 "지금" 으로 본다 — 다음 날로 밀지 않는다.
    if (start.getTime() < nowMs) { start = new Date(nowMs); immediate = true; }
    var durationSec = (durSec && durSec > 0) ? durSec : null;   // 00:00 = 무한
    var delaySec = Math.max(0, Math.round((start.getTime() - nowMs) / 1000));
    // 임계값은 "지금/과거를 골랐다" 만 걸러낼 만큼만. 휠이 분 단위라 '다음 분'
    // 선택의 실제 지연은 1~59초이고, 예전 60초 임계값은 그것을 전부 삼켰다.
    if (delaySec <= 5) immediate = true;
    return {
      start: start,
      end: (durationSec === null) ? null : new Date(start.getTime() + durationSec * 1000),
      durationSec: durationSec,
      delaySec: delaySec,
      immediate: immediate
    };
  }

  // 시작 시각 + 작동 시간 → 실제 제어 또는 예약 등록.
  // 계획은 _planSchedule 한 곳에서만 계산한다(미리보기와 동일한 값).
  // 작동 시간 00:00 = 무한 작동 → duration 을 아예 보내지 않는다.
  function _applySchedule(outputId, channel, name, startSec, durSec) {
    var plan = _planSchedule(startSec, durSec);
    // 결과 화면이 되돌리기(예약 취소 / 지금 끄기)에 쓸 정보를 함께 실어 보낸다.
    var base = { start: plan.start, end: plan.end, durationSec: plan.durationSec,
                 outputId: outputId, channel: channel };
    function merge(res) {
      for (var k in base) if (!(k in res)) res[k] = base[k];
      return res;
    }
    if (plan.immediate) {
      return _fireNow(outputId, channel, plan.durationSec).then(merge);
    }
    return _proposeJob(outputId, channel, name, plan.start, plan.durationSec)
      .then(merge)
      .catch(function () {
        // 스케줄러 등록 실패(권한 등) → 탭 바인딩 폴백.
        return merge(_fallbackTimer(outputId, channel, plan.durationSec, plan.delaySec));
      });
  }

  function _fireNow(outputId, channel, durationSec) {
    var body = { state: true, channel: channel };
    if (durationSec !== null) body.duration = durationSec;
    return fetch('/api/geo/output/' + encodeURIComponent(outputId) + '/state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrf() },
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) throw new Error((j && j.error) || _t('Failed'));
        return { mode: 'now' };
      });
  }

  function _proposeJob(outputId, channel, name, start, durationSec) {
    var params = { state: 'on', channel: channel };
    if (durationSec !== null) params.amount = durationSec;
    return fetch('/api/v1/scheduler/propose', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrf() },
      body: JSON.stringify({
        action_type: 'output',
        target_id: outputId,
        params: params,
        schedule_time: _wallClockString(start),
        duration_sec: durationSec || 0,
        // reasoning 은 DB 에 그대로 저장돼 Scheduler 페이지에 뜬다 —
        // 로케일에 따라 값이 달라지지 않도록 영어 고정.
        reasoning: 'Scheduled from the map widget' + (name ? ' — ' + name : '')
      })
    })
      .then(function (r) {
        if (!r.ok) throw new Error('scheduler HTTP ' + r.status);
        return r.json();
      })
      .then(function (j) {
        if (j && j.error) throw new Error(j.error);
        return { mode: 'scheduled', job: j,
                 info: _t('Scheduled. It runs even if this tab is closed.') };
      });
  }

  function _fallbackTimer(outputId, channel, durationSec, delaySec) {
    if (!window.confirm(_t('Could not save a server schedule. Turn on at the chosen time using this browser tab instead? The tab must stay open until then.'))) {
      throw new Error(_t('Cancelled'));
    }
    setTimeout(function () { _fireNow(outputId, channel, durationSec).catch(function () {}); },
               delaySec * 1000);
    return { mode: 'tab-timer',
             warn: _t('Scheduled — keep this tab open until the start time.') };
  }

  // ── 식생 구획(작기) 모달 ────────────────────────────────────────────────
  //
  // geo/design 은 도형을 만들고 고치는 곳이고, **운영 정보는 여기가 맡는다**
  // (구역·시설 모달과 같은 역할 분담). 그래서 작물·기간 같은 사실과 노트·이력을
  // 함께 싣는다.
  //
  // 셸은 위젯의 `_showFacilityCenterOverlay`(중앙 모달) 를 쓴다 — 팝업 말풍선은
  // 폭이 좁아 이력 목록이 들어가지 않는다.
  //
  // 노트 블록은 공용 컴포넌트(_ovNotesBlock → AoTNotesBlock)를 그대로 쓴다.
  // 여기서 자체 노트 마크업을 다시 짜지 말 것.
  // 탭 구성 — 시설·구역과 **같은 세 키**(overview/envctl/about). 위젯 옵션
  // popup_default_tab 이 그대로 걸린다.
  var _PLANTING_SECS = [
    { key: 'overview', label: 'Overview' },
    { key: 'envctl',   label: 'Environment & Control' },
    // 위 `buildSectionNav` 기본값과 **같은 이름**이어야 한다 — 구획만 다른
    // 이름을 쓰면 계층을 오갈 때마다 같은 자리의 탭을 다시 읽어야 한다.
    { key: 'about',    label: 'Settings' }
  ];

  // 위젯 옵션 popup_default_tab 은 세 키를 쓰는데 식생은 그중 둘만 갖는다 —
  // 'envctl' 로 설정된 대시보드에서 식생을 열면 존재하지 않는 탭을 요구받는다.
  // 그때는 조용히 [현황]으로 떨어뜨린다(빈 화면보다 낫다).
  function plotDefaultSec(want) {
    for (var i = 0; i < _PLANTING_SECS.length; i++) {
      if (_PLANTING_SECS[i].key === want) return want;
    }
    return 'overview';
  }

  // 기존 모달의 행 마크업과 같은 것을 쓴다(buildAboutSection 의 _row).
  function _pRow(label, val) {
    return '<div class="aot-ov-row"><span>' + _esc(label) + '</span><span>' +
           val + '</span></div>';
  }

  // 로딩 자리막이. 바 개수는 **부르는 쪽이 정한다** — 자리막이가 들어설 내용보다
  // 짧으면 값이 오는 순간 창이 튀고, 길어도 마찬가지라 자리마다 다른 것이 맞다.
  // 여기서 한곳에 두는 것은 **모양**이다(예전에는 구역용과 베이용 두 벌이 따로
  // 있었고, 한쪽에만 바가 하나 더 붙은 채 갈라져 있었다).
  function skeleton(widths) {
    var w = widths || ['w60', 'w80', 'w40'];
    var html = '<div class="aot-ov-skel">';
    w.forEach(function (c) { html += '<div class="aot-ov-skel-bar ' + c + '"></div>'; });
    return html + '</div>';
  }

  // nav 와 **짝**이다. 한쪽만 공용으로 두면 탭을 늘릴 때 pane 쪽만 각자 짓게 되어
  // 다시 갈라진다(실제로 구역·필지가 그 상태였다).
  function sectionPane(key, active, inner) {
    return '<div class="aot-bay-popup-pane" data-pane="' + key + '"' +
           (key === active ? '' : ' style="display:none"') + '>' + inner + '</div>';
  }
  var _pPane = sectionPane;

  // 구획 모달의 **자리막이**. 값이 오기 전까지 보이는 화면이다.
  //
  // 구획 창은 `/api/geo/plot/<uuid>` 를 받은 **뒤에** 열렸다 — 그 왕복 동안
  // 화면에는 아무 일도 일어나지 않아, 누른 사람은 눌린 줄을 모른다. 구역·시설
  // 창은 이미 껍데기를 먼저 띄우고 자리막이를 보인다(`_buildZoneSkel`).
  //
  // 껍데기는 **진짜 창과 같은 것**이어야 한다(같은 헤더·같은 탭) — 도착하는
  // 순간 창이 다시 그려지는 것처럼 보이면 자리막이를 두는 뜻이 없다.
  function buildPlotModalSkeleton(name, opts) {
    opts = opts || {};
    var defSec = plotDefaultSec(opts.defaultTab);
    return buildModalHeader({ name: name || _t('Plot'), up: true,
                              status: null }) +
           buildSectionNav(defSec, _PLANTING_SECS) +
           // 바 넷 — [현황]에 들어설 것이 사진·진행·환경·노트라 그만큼 길다.
           // 짧게 두면 값이 오는 순간 창이 튄다.
           _pPane('overview', defSec, skeleton(['w60', 'w80', 'w40', 'w80'])) +
           _pPane('envctl',   defSec, '') +
           _pPane('about',    defSec, '');
  }

  function buildPlotModal(p, opts) {
    p = p || {};
    opts = opts || {};
    var defSec = plotDefaultSec(opts.defaultTab);
    // up: 소속 구역으로 올라간다. 버튼은 hidden 으로 자리만 잡고, 상위가
    // 확인되면 위젯이 드러낸다(_wireUpBtn) — 구역을 못 찾은 구획에서는 눌러도
    // 아무 일 없는 버튼이 남지 않는다.
    return buildModalHeader({ name: p.name || p.subject || _t('Plot'),
                              up: true, status: null }) +
           buildSectionNav(defSec, _PLANTING_SECS) +
           _pPane('overview', defSec, _plotOverviewHtml(p)) +
           // [환경·제어]는 별도 조회(/contents)라 빈 칸으로 열어 두고
           // 도착하면 채운다 — 그 왕복 때문에 모달 전체를 늦추지 않는다.
           _pPane('envctl',   defSec, '') +
           _pPane('about',    defSec, _plotAboutHtml(p));
  }

  // ── [현황] — 지금 이 구획이 어떤 상태인가 ────────────────────────────────
  //
  // **중심은 노트다.** 현 상황(관찰·작업·사진)을 말할 수 있는 것은 노트뿐이고,
  // 그것이 이 탭에 오는 이유다.
  //
  // 예전에는 여기에 "이 구획 안의 센서 · 1" 같은 **개수**와 밸브 커버리지
  // 목록이 있었다. 둘 다 "어떤 장치로 관리하느냐" 인데 그건 [환경·제어]가
  // 값·스코프 배지·영향 범위까지 제대로 낸다 — 여기 있던 것은 값도 없이
  // 장치 이야기만 하면서 정작 봐야 할 노트를 아래로 밀어냈다.
  // ── 진행 — 재배 기간과 현재 단계를 **막대 두 개**로 답한다 ──────────────
  //
  // 예전에는 네 줄의 라벨-값 텍스트였다("경과 일수 22일차" · "남은 일수 19일" ·
  // "단계 착과기 (3/6)" · "다음 단계 비대기 · 4일 남음"). 숫자는 다 있었지만
  // "지금 어디쯤인가" 는 사람이 머릿속에서 나누기를 해야 나왔다. 값을 위치로
  // 바꾸면 그 계산이 사라진다.
  //
  // 공용 프리미티브(AoTViz, static/js/common/aot-dataviz.js)를 쓴다 — 색·간격·
  // 굵기 규칙은 전부 거기에 있고 여기서는 **무엇을 어디에 대응시킬지**만 정한다.
  // 규약: docs/design/dataviz-primitives.md
  //
  // 초록 구간은 "여기까지 왔다"(경과분), 마커는 오늘이다. 두 막대가 같은 문법을
  // 쓰므로 위아래로 나란히 놓아도 서로 다른 그림으로 읽히지 않는다.
  function _plotProgressHtml(p) {
    var V = window.AoTViz;
    // 번들에 프리미티브가 없으면 **옛 텍스트 행으로 되돌아간다.** 조용히 빈
    // 칸을 내면 진행 정보가 통째로 사라진 것을 아무도 모른다.
    if (!V) return _plotProgressRows(p);

    var rows = [];
    var stg = p.stage;
    var tl  = p.timeline;

    // ⓪ 아직 시작 전(계획) — **축은 그대로 그린다.** 계획을 세우는 사람이 알고
    //    싶은 것은 "언제부터" 만이 아니라 "어떤 단계로 얼마나" 이고, 그 구조는
    //    프로그램에 이미 있다. 축을 빼면 그것을 볼 자리가 어디에도 없다.
    //
    //    다만 **오늘 마커도 현재 단계 강조도 두지 않는다.** 아직 아무 단계도
    //    아니라서, 마커를 왼쪽 끝에 세우면 "이제 막 시작했다" 로 읽힌다.
    //    (서버가 `today_pct: null` · 모든 단계 `current: false` 로 낸다.)
    //    값 자리와 눈금 가운데가 "며칠 뒤 시작" 을 말한다.
    if (p.planned) {
      var untilTxt = (p.days_until_start != null)
        ? _t('Starts in %(n)s days').replace('%(n)s', String(p.days_until_start))
        : _t('Planned');
      if (tl && (tl.stages || []).length) {
        rows.push(V.timeline({
          label: _t('Plan'),
          valueText: untilTxt,
          valueSub: tl.total_days ? ('/ ' + String(tl.total_days)) : '',
          segments: tl.stages.map(function (st) {
            return {
              span: Math.max(0, (st.to_pct || 0) - (st.from_pct || 0)),
              name: st.name
              // `current` 를 주지 않는다 — 아직 아무 단계도 아니다.
            };
          }),
          // 마커 없음. `AoTViz` 는 위치가 null 이면 그리지 않는다.
          positionPct: null,
          scale: [
            _axisDate(tl.start || p.started_on),
            // anchor 로 두지 않는다 — 가리킬 지점이 축 위에 없다. 흐름에 두면
            // 세 칸이 고르게 놓여 가운데가 실제 가운데다.
            untilTxt,
            _axisDate(tl.end || p.expected_end_on) || _t('open-ended')
          ]
        }));
      } else {
        // 프로그램이 없는 계획 — 단계가 없으니 날짜만 말한다.
        rows.push(_pRow(_t('Starts on'), _esc(p.started_on || '—')));
        if (p.days_until_start != null) {
          rows.push(_pRow(_t('Until start'),
                          _esc(_t('%(n)s days').replace('%(n)s',
                               String(p.days_until_start)))));
        }
      }
      return V.group(rows);
    }

    // ① 기간 축 — **서버가 만든 단계 목록을 그대로 쓴다**(plot_context.timeline).
    //    단계 길이·기준점(P5)·"끝까지" 처리가 전부 서버 규칙이라, 여기서 다시
    //    조립하면 두 곳이 곧 갈린다. 단계 이름은 트랙 위에 늘어선다.
    if (tl && (tl.stages || []).length) {
      var pct = (tl.today_pct == null) ? 0 : tl.today_pct;
      var over = pct > 100;                 // 예정을 넘겼다 — 자르되 사실은 말한다
      rows.push(V.timeline({
        label: p.ended_on ? _t('Grown for') : _t('Days elapsed'),
        valueText: (p.ended_on ? _t('%(n)s days') : _t('Day %(n)s'))
                   .replace('%(n)s', String(tl.elapsed_days)),
        valueSub: tl.total_days ? ('/ ' + String(tl.total_days)) : '',
        segments: tl.stages.map(function (st) {
          return {
            span: Math.max(0, (st.to_pct || 0) - (st.from_pct || 0)),
            name: st.name,
            current: !!st.current
          };
        }),
        positionPct: Math.min(100, Math.max(0, pct)),
        // 눈금 문자열은 AoTViz 가 이스케이프한다 — 여기서 또 하면 &amp; 가 뜬다.
        scale: [
          _axisDate(tl.start),
          { text: _t('Today'), anchor: true },
          _axisDate(tl.end) || _t('open-ended')
        ]
      }));
      // 예정을 넘긴 사실은 **자르지 않고 말한다**(넘겼다는 것 자체가 정보다).
      // 눈금의 '오늘' 자리에 넣지 않는 이유: 그 자리는 좁고, 문장이 들어가면
      // 양쪽 날짜를 가린다.
      if (over) {
        rows.push('<div class="aot-ov-muted">' +
                  _esc(_t('Past the planned end')) + '</div>');
      }
    } else {
      // 프로그램이 없는 구획 — 단계는 없지만 "얼마나 왔나" 는 여전히 답할 수
      // 있다. 예정을 지난 작기(days_to_expected_end < 0)는 남은 칸이 없다:
      // 음수를 폭으로 넘기면 막대가 뒤집히므로 0 으로 눕히고 마커를 끝에 둔다.
      var el = p.days_since_planted, left = p.days_to_expected_end;
      if (el != null && el >= 0) {
        var rest = (left != null && left > 0) ? left : 0;
        var span = el + rest;
        if (span > 0) {
          rows.push(V.timeline({
            label: p.ended_on ? _t('Grown for') : _t('Days elapsed'),
            valueText: (p.ended_on ? _t('%(n)s days') : _t('Day %(n)s'))
                       .replace('%(n)s', String(el)),
            valueSub: rest ? ('/ ' + String(span)) : '',
            segments: [{ span: el, current: true }, { span: rest }],
            positionPct: (el / span) * 100,
            scale: [
              _axisDate(p.started_on) || _t('Start'),
              { text: (left != null && left < 0)
                  ? _t('%(n)s days overdue').replace('%(n)s', String(-left))
                  : _t('Today'),
                anchor: true },
              _axisDate(p.expected_end_on) || _t('Expected end')
            ]
          }));
        }
      }
    }

    // ② 다음 단계까지 — 축이 "어디쯤" 을 답하고, 이 줄이 "얼마나 남았나" 를
    //    답한다. 판정 축이 둘이다(날짜 / GDD): 서버가 source 로 알려 주므로
    //    여기서 다시 판단하지 않고 **있는 쪽의 값만** 쓴다.
    if (stg && stg.state === 'running' && stg.pending) {
      // 파생은 다음 단계를 가리키는데 사람이 아직 확인하지 않았다(P8). 단계는
      // 넘어가지 않았다 — 그 사실을 말하지 않으면 화면은 "왜 안 넘어가지" 가 된다.
      rows.push(_pRow(_t('Next stage'),
                      _esc((stg.pending.stage_name || '\u2014') + ' \u00b7 ' +
                           _t('waiting for your confirmation'))));
    } else if (stg && stg.state === 'running') {
      var remain = null;
      if (stg.source === 'gdd') {
        if (stg.gdd_left != null) {
          remain = _t('in {n} GDD').replace('{n}', String(stg.gdd_left));
        }
      } else if (stg.days_left != null) {
        remain = _t('in %(n)s days').replace('%(n)s', String(stg.days_left));
      }
      if (remain) {
        rows.push(_pRow(_t('Next stage'),
                        _esc((stg.next_name || '\u2014') + ' \u00b7 ' + remain)));
      }
    } else if (stg && stg.state === 'not_started') {
      rows.push(_pRow(_t('Current stage'), _esc(_t('Not started yet'))));
    } else if (stg && stg.state === 'past_end') {
      rows.push(_pRow(_t('Current stage'), _esc(_t('Past the programme end'))));
    }

    if (!rows.length) return '';
    return V.group(rows);
  }

  // AoTViz 가 없을 때의 되돌림 — 옛 라벨-값 행 그대로. 막대가 못 그려지는
  // 상황에서도 숫자는 남아야 한다.
  function _plotProgressRows(p) {
    var html = '';
    // 계획은 위 `_plotProgressHtml` 과 같은 것을 말한다 — 폴백만 다르게 두면
    // 프리미티브가 없는 환경에서 그 구획이 빈 카드로 보인다.
    if (p.planned) {
      html += _pRow(_t('Starts on'), _esc(p.started_on || '—'));
      if (p.days_until_start != null) {
        html += _pRow(_t('Until start'),
                      _esc(_t('%(n)s days').replace('%(n)s',
                           String(p.days_until_start))));
      }
      return html;
    }
    if (p.days_since_planted != null) {
      var n = String(p.days_since_planted);
      html += _pRow(p.ended_on ? _t('Grown for') : _t('Days elapsed'),
                    _esc((p.ended_on ? _t('%(n)s days') : _t('Day %(n)s'))
                         .replace('%(n)s', n)));
    }
    var d = p.days_to_expected_end;
    if (p.expected_end_on && d != null) {
      html += _pRow(_t('Days left'),
                    _esc(d >= 0
                      ? _t('%(n)s days').replace('%(n)s', String(d))
                      : _t('%(n)s days overdue').replace('%(n)s', String(-d))));
    }
    var stg = p.stage;
    if (stg && stg.state === 'running') {
      html += _pRow(_t('Current stage'),
                    _esc(stg.name || stg.key || '') +
                    ' <span class="aot-ov-muted">(' + stg.index + '/' +
                    stg.total + ')</span>');
      if (stg.pending) {
        html += _pRow(_t('Next stage'),
                      _esc((stg.pending.stage_name || '\u2014') + ' \u00b7 ' +
                           _t('waiting for your confirmation')));
      } else if (stg.days_left != null) {
        html += _pRow(_t('Next stage'),
                      _esc((stg.next_name || '\u2014') + ' \u00b7 ' +
                           _t('in %(n)s days').replace('%(n)s',
                                String(stg.days_left))));
      } else if (stg.source === 'gdd' && stg.gdd_left != null) {
        html += _pRow(_t('Next stage'),
                      _esc((stg.next_name || '\u2014') + ' \u00b7 ' +
                           _t('in {n} GDD').replace('{n}',
                                String(stg.gdd_left))));
      }
    } else if (stg && stg.state === 'not_started') {
      html += _pRow(_t('Current stage'), _esc(_t('Not started yet')));
    } else if (stg && stg.state === 'past_end') {
      html += _pRow(_t('Current stage'), _esc(_t('Past the programme end')));
    }
    return html;
  }

  // 단계 지침은 재배 지침서에서 옮겨 온 산문이라 길다(서버가 4000자까지 받는다).
  // 펼친 채로 두면 [진행] 카드 하나가 화면을 넘겨 그 아래 [환경]·[노트]가 밀린다.
  // 그래서 **접어 둔다** — 있다는 사실은 버튼이 말하고, 읽을 사람만 편다.
  //
  // `<details>` 를 쓰는 이유는 상태가 DOM 에 있어서다. 펼침을 JS 로 관리하면
  // 이 pane 이 다시 그려질 때(폴링) 되살리는 코드가 따로 필요하고, 그 코드가
  // 빠지면 "펼쳐 놓았는데 30초마다 접힌다" 가 된다.
  // 노트에 붙은 **마지막 사진**. 목록이 아니라 한 장이다 — 여러 장을 늘어놓으면
  // 그 아래 [진행]·[환경] 이 화면 밖으로 밀리고, "지금 어떻게 생겼나" 라는 질문에는
  // 가장 최근 한 장이면 답이 된다. 나머지는 [노트] 가 갖는다.
  //
  // **사진이 없으면 아무것도 내지 않는다**(대부분의 구획이 그렇다). 빈 카드는
  // 자리만 차지하고 아무 말도 하지 않는다.
  var _PHOTO_EXT = /\.(png|jpe?g|gif|webp|bmp|heic|heif)$/i;

  function latestNotePhoto(notes) {
    if (!Array.isArray(notes)) return null;
    for (var i = 0; i < notes.length; i++) {          // 응답이 최신순이다
      var f = (notes[i] && notes[i].files) || '';
      var parts = String(f).split(',');
      for (var j = 0; j < parts.length; j++) {
        var rel = parts[j].trim();
        // 동영상도 같은 칸에 담긴다 — 사진만 고른다(재생 UI 를 여기 두지 않는다).
        if (rel && _PHOTO_EXT.test(rel)) {
          return { url: '/note_attachment/' + rel, note: notes[i] };
        }
      }
    }
    return null;
  }

  function buildPhotoCardHtml(photo) {
    if (!photo) return '';
    return '<div class="aot-ov-card-title">' + _esc(_t('Latest photo')) + '</div>' +
           '<div class="aot-ov-block aot-ov-photo">' +
           '<img src="' + _esc(photo.url) + '" alt="" loading="lazy">' +
           '</div>';
  }

  // 축 눈금의 날짜. **한 곳에서 정한다** — 분기마다 적으면 같은 축에 두 형식이
  // 선다(실측: 시작 '2026/09/22' 옆에 종료 '2027-01-18'). 연도를 남기는 것이
  // 핵심이다: 해를 넘기는 작기(월동·과수)에서 '12/20 → 3/15' 는 거꾸로 읽힌다.
  function _axisDate(v) {
    return v ? String(v).replace(/-/g, '/') : '';
  }

  function _plotGuidanceHtml(stg) {
    if (!stg || !stg.guidance) return '';
    // **버튼 뒤에 두지 않는다.** 지금 단계에 무엇을 해야 하는지는 축을 본 그
    // 자리에서 바로 읽혀야 하는 것이고, 한 번 더 눌러야 나오면 아무도 읽지
    // 않는다(AI 를 안 쓰는 사용자에게는 여기가 유일한 자리다).
    return '<div class="aot-ov-guidance aot-ov-guidance-inline">' +
           _esc(stg.guidance) + '</div>';
  }

  function _plotOverviewHtml(p) {
    // 제목은 목록 쪽('심겨 있는 것')과 달라야 한다 — 같은 말을 쓰면 블록
    // 제목과 첫 행 라벨이 겹쳐 "심겨 있는 것 / 심은 것" 으로 읽힌다.
    // 최신 사진 — 카드 **위**에 둔다. 이 화면에서 가장 먼저 확인하는 것이
    // "지금 어떻게 생겼나" 이고, 그 답은 숫자가 아니라 사진이다. 값은 별도
    // 조회(노트)라 자리만 잡고 위젯이 채운다([현재] 자리와 같은 방식).
    var html = '<div data-slot="photo"></div>';

    html += '<div class="aot-ov-card-title">' + _esc(_t('Progress')) +
            '</div><div class="aot-ov-block">';

    // 대상·시작일·예상 종료일은 [개요] 가 맡는다 — 바뀌지 않는 사실이고,
    // 두 탭에 같은 행을 두면 어느 쪽이 정본인지 사람이 매번 확인하게 된다.
    html += _plotProgressHtml(p);
    var _stg = p.stage;
    html += _plotGddRows(_stg);
    // 단계 지침 — 타임라인 바로 아래, **같은 카드 안**이다. 이 시기에 무엇이
    // 중요한지는 단계를 본 그 자리에서 읽혀야 한다(AI 를 안 쓰는 사용자에게는
    // 여기가 유일한 자리다).
    html += _plotGuidanceHtml(_stg);
    html += '</div>';

    // 현재 환경 — 구역·시설 [현황]과 **같은 자리, 같은 블록**이다. 값은 별도
    // 조회(/contents)라 여기서는 자리만 잡아 두고 위젯이 채운다. 자리를 비워
    // 두는 이유: 도착 순서에 따라 블록이 위아래로 튀면 사용자가 읽던 줄이
    // 움직인다.
    html += '<div data-slot="envnow"></div>';

    /* **숫자만 보이면 사람이 "이대로 돌고 있다" 로 읽는다.**
     *
     * 프로그램 목표는 이제 [현재] 의 눈금으로 들어간다(값 옆 `목표 25`).
     * 그런데 프로그램은 함수를 스스로 켜지 않는다(P6) — 그 사실이 화면에
     * 없으면 실제 제어와 다른데도 확인할 생각을 안 하게 된다. [목표] 카드를
     * 없애면서 이 문장이 갈 곳이 여기밖에 없다.
     *
     * **시설·구역 [현재] 에는 붙이지 않는다.** 그쪽 목표는 코디네이터가 실제로
     * 쫓는 값이라(`summary.targets`) 같은 문장이 거짓이 된다. 그래서 공용
     * 빌더(`buildEnvNowHtml`)가 아니라 구획 쪽에서만 붙인다. */
    if (_stg && (_stg.targets || []).length) {
      html += '<div class="aot-ov-muted aot-ov-targets-note">' +
              // msgid 는 한 줄 리터럴로 둔다 — 이어붙이면 추출기가 못 읽어
              // 그 문구만 영어로 나온다(project_i18n_babel_footguns).
              _esc(_t('Targets are shown for reference. Control is not changed automatically.')) +
              '</div>';
    }

    // 단계 전환 제안·목표·자원 — 전부 **지금** 의 값이다. 프로그램이 무엇인지
    // (이름·단계 수·전체 기간)는 바뀌지 않는 사실이라 [개요] 가 갖는다.
    var _ask = _plotStageProposalHtml(p);
    if (_ask) {
      html += '<div class="aot-ov-card-title">' + _esc(_t('Stage change')) +
              '</div><div class="aot-ov-block">' + _ask + '</div>';
    }
    // ── [목표] 카드는 없앴다 (2026-08-20) ───────────────────────────────
    //
    // [현재] 가 값 옆에 목표를 함께 세우게 되면서(`buildEnvNowHtml` 의
    // anchor 눈금) 두 카드가 거의 같은 말을 하게 됐다 — 같은 지표가 두 번
    // 나오면 사용자는 어느 쪽이 정본인지 매번 확인한다.
    //
    // 게다가 이 카드는 **재는 센서가 없는 항목까지** 늘어놓았다(관수량·EC 등
    // `t.observable === false`). 지금 값과 나란히 놓을 수 없는 줄이라, 남는
    // 것은 "목표 숫자 목록" 뿐이고 그것은 프로그램 설정 화면이 이미 보여 준다.
    //
    // 목표가 사라진 것은 아니다 — 지금 값이 있는 항목은 [현재] 의 눈금이
    // 그대로 답한다("그래서 지금 맞나" 까지 함께).
    //
    // 단계 일정은 **[설정]** 에 있다(기본 정보 다음). [현황]은 "지금 어떤가" 를
    // 답하는 자리고, 일정을 짜는 것은 그 구획을 어떻게 기를지 정하는 일이라
    // 작물·기간·프로그램을 고치는 자리와 함께 있어야 한다.
    var _rs = _plotStageResourceRows(_stg);
    if (_rs) {
      html += '<div class="aot-ov-card-title">' + _esc(_t('Resources')) +
              '</div><div class="aot-ov-block">' + _rs + '</div>';
    }

    // 물 줄 수단이 없다 — 장치 목록이 아니라 **빠진 것**을 알리는 줄이다.
    // 정상일 때는 나오지 않으므로 평소 화면을 어지럽히지 않는다.
    html += _plotNoValveHtml(p);

    // 기록 — 예정과 노트가 **한 블록**이다. 진입점도 하나(계획서 Phase 2).
    // 네 계층 중 여기서 먼저 시험한다 — 한 번에 퍼뜨리면 되돌릴 지점이 없다.
    html += buildRecordBlock(p.schedule, { addable: p.active !== false });
    return html;
  }

  // 구획에 걸친 **장치 영역**에 장치가 배정돼 있지 않으면 알린다.
  // 장치 목록을 내는 것이 아니다(그건 [환경·제어]) — "손댈 수단이 아직 없다"
  // 는 상태를 말하는 것이고, 그래서 [현황]에 있다.
  //
  // 여기서도 "관수" 라고 쓰지 않는다 — 그 영역이 물을 주는 것인지 시스템은
  // 모른다(coverageHtml 주석 참조).
  function _plotNoValveHtml(p) {
    var valves = p.valves;
    if (!Array.isArray(valves)) return '';
    var open = valves.filter(function (v) { return v.unassigned; });
    if (!open.length) return '';
    return '<div class="aot-ov-block aot-ov-plot-novalve">' +
           '<div class="aot-ov-muted">' +
           _esc(_t('A device area over this plot has no device assigned yet.')) +
           '</div></div>';
  }


  // ── [개요] — 잘 안 변하는 사실 + 편집 ───────────────────────────────────
  function _plotAboutHtml(p) {
    // 보기와 편집을 같은 블록에 두고 토글한다(구역 모달의 설명 편집과 같은
    // 방식: aot-ov-desc-*). geo/design 은 도형만 다루므로 **작물·기간을 고치는
    // 자리는 여기다.**
    // 제목은 첫 행 라벨('심은 것')과 달라야 한다 — 같으면 "심은 것 / 심은 것"
    // 으로 읽힌다([현황]에서 한 번 겪은 것과 같은 문제).
    var html = _plotDimsHtml(p) +
            '<div class="aot-ov-card-title">' + _esc(_t('Basics')) + '</div>' +
            '<div class="aot-ov-block aot-ov-plot-info">';

    html += '<div class="aot-ov-plot-view">';
    html += _pRow(_plotSubjectLabel(p), _esc(p.subject || '—') +
                   (p.variety ? ' · ' + _esc(p.variety) : ''));
    if (p.name) html += _pRow(_t('Plot name'), _esc(p.name));
    html += _pRow(_t('Start date'), _esc(p.started_on || '—'));
    if (p.expected_end_on) {
      html += _pRow(_t('Expected end'), _esc(p.expected_end_on));
    }
    if (p.ended_on) html += _pRow(_t('Ended'), _esc(p.ended_on));
    html += '</div>';

    // 편집 폼 (기본 숨김). 기하는 여기서 고치지 않는다 — 도형은 geo/design 이다.
    //
    // 골격은 **AoT 현대화 모달 스타일**을 그대로 쓴다:
    //   aot-modal-container > aot-modal-option-row (label / control) + aot-modern-input
    // 그래야 입력창 가로폭이 자동으로 맞고(개별 width 지정 금지), 색 입력도
    // 공용 pill 형태(aot-detail-field-color)로 충분히 커진다.
    var _v = function (x) { return _esc(x == null ? '' : x); };
    var _fRow = function (label, control) {
      return '<div class="aot-modal-option-row">' +
             '<div class="aot-modal-option-label">' + _esc(label) + '</div>' +
             '<div class="aot-modal-option-control">' + control + '</div></div>';
    };
    var _inp = function (field, type, val) {
      var html = '<input type="' + type + '" class="aot-modern-input form-control" ' +
                 'data-pf="' + field + '" value="' + _v(val) + '">';
      // 종료일은 비울 수 있어야 한다("종료 미정" 이 정상인 대상이 있다). iOS 는
      // 날짜 입력을 비울 수단을 주지 않으므로 [지우기] 를 함께 낸다 — 마크업은
      // 공용 폼의 것을 그대로 빌린다(`AoTPlotForm.clearableDate`).
      if (type === 'date' && field !== 'started_on' &&
          window.AoTPlotForm && window.AoTPlotForm.clearableDate) {
        return window.AoTPlotForm.clearableDate(html, field);
      }
      return html;
    };

    // 시설 구획은 **구역이 곧 위치**다. 노지 구획은 도형을 옮겨 자리를 바꾸지만
    // (그 편집은 geo/design 이다), 시설 구획에서 자리를 바꾸는 일은 구역을 고르는
    // 일이라 여기서 할 수 있어야 한다 — 그러지 않으면 온실 구획만 위치를 못 고쳐
    // 시설 편집기까지 다녀와야 한다.
    //
    // 빈 값은 "시설 전체" 다(다동에서만 의미가 있다). 종료된 작기의 이동은 서버가
    // 거부한다(VP-6) — 위치가 바뀌면 "작년에 여기 뭐가 있었나" 의 답이 달라진다.
    var _bayRow = '';
    if (p.location_source === 'facility' && (p.facility_bays || []).length) {
        var opts = '<option value=""' + (p.bay_id ? '' : ' selected') + '>' +
                   _esc(_t('Whole facility')) + '</option>';
        p.facility_bays.forEach(function (b) {
            opts += '<option value="' + _esc(b.id) + '"' +
                    (b.id === p.bay_id ? ' selected' : '') + '>' +
                    _esc(b.name || b.id) + '</option>';
        });
        _bayRow = _fRow(_t('Zone'),
                        '<select class="aot-modern-input form-control" ' +
                        'data-pf="bay_id">' + opts + '</select>') +
                  _fieldHint(_t('Facility settings'),
                             '/geo/facility', p.can_design);
    }

    // 재배 프로그램 — 선택지는 위젯이 `p.program_choices` 로 실어 준다(모달은
    // 스스로 조회하지 않는다: 빌더는 순수 함수로 두고 조회는 위젯이 맡는 것이
    // 이 파일의 규약이다).
    //
    // ⚠ **등록된 프로그램이 없어도 줄을 낸다.** 예전에는 선택지가 비면 줄 자체를
    // 빼서, 프로그램을 한 번도 만들지 않은 설치에서는 "프로그램" 이라는 낱말이
    // 화면 어디에도 없었다. 사용자는 그것을 **기능이 없다/고장났다** 로 읽는다 —
    // 2026-08-23 실제로 "구버전 모달이 떴다 · 프로그램 연동이 안 된다" 는 보고가
    // 왔고, 코드는 최신이었고 다른 것은 `geo_program` 이 0건이라는 사실뿐이었다.
    // "없는 것" 과 "안 보여준 것" 이 같은 화면이 되면 안 된다.
    var _progChoices = p.program_choices || [];
    var curP = (p.program && p.program.unique_id) || '';
    var po = '<option value="">' + _esc(_t('No program')) + '</option>';
    _progChoices.forEach(function (x) {
        po += '<option value="' + _esc(x.unique_id) + '"' +
              (x.unique_id === curP ? ' selected' : '') + '>' +
              _esc(x.name + (x.variety ? ' · ' + x.variety : '')) + '</option>';
    });
    var _progRow = _fRow(_t('Program'),
                         '<select class="aot-modern-input form-control" ' +
                         'data-pf="program_uuid">' + po + '</select>') +
                   // 하나도 없을 때야말로 만들러 갈 길을 보여야 한다.
                   _fieldHint(_progChoices.length
                                  ? _t('Create a new program')
                                  : _t('No programs yet — create one'),
                              '/geo/programs', p.can_design);

    // 구역 안에서의 몫(p6_50) — 시설 구획에만 있다. 노지 구획은 면적이 도형에서
    // 나오므로 몫을 따로 적으면 정본이 둘이 된다(서버도 거절한다).
    var _allocRow = '';
    if (p.facility_uuid && p.location_source !== 'own') {
        var _a = p.allocation || {};
        var _cap = (_a.total != null)
            ? ('/ ' + _a.total + ' ' + _capUnitLabel(_a.unit)) : '%';
        var _av = (_a.amount != null) ? _a.amount
                  : (_a.percent != null ? _a.percent : '');
        _allocRow = _fRow(_t('Share'),
                          '<span class="aot-ov-alloc-input">' +
                          '<input type="number" min="0" step="any" ' +
                          'class="aot-modern-input form-control" ' +
                          'data-pf="allocation_value" value="' + _esc(String(_av)) +
                          '"><span class="aot-ov-alloc-suffix">' + _esc(_cap) +
                          '</span></span>');
    }

    html += '<div class="aot-ov-plot-edit-wrap" style="display:none">' +
            '<div class="aot-modal-container">' +
            _bayRow +
            _allocRow +
            _fRow(_t('Kind'), _kindSelect('data-pf="kind"', p.kind)) +
            _progRow +
            _fRow(_plotSubjectLabel(p), _inp('subject', 'text', p.subject)) +
            _fRow(_plotVarietyLabel(p), _inp('variety', 'text', p.variety)) +
            _fRow(_t('Plot name'), _inp('name', 'text', p.name)) +
            _fRow(_t('Start date'), _inp('started_on', 'date', p.started_on)) +
            _fRow(_t('Expected end'), _inp('expected_end_on', 'date', p.expected_end_on)) +
            '<div class="aot-modal-option-row">' +
            '<div class="aot-modal-option-label">' + _esc(_t('Colour')) + '</div>' +
            '<div class="aot-modal-option-control aot-modal-detail-field aot-detail-field-color">' +
            '<input type="color" class="aot-modern-input form-control" data-pf="color" value="' +
            _v(p.color || '#6a8f3c') + '"></div></div>' +
            '</div>' +
            // [작기 종료]는 되돌릴 수 없는 동작이라 **기본 동작 옆에 두지 않는다** —
            // 왼쪽 끝으로 떼어 놓는다(`--apart`). 오른쪽 끝은 언제나 [저장]이다.
            '<div class="aot-ov-desc-actions">' +
            (p.active ? '<button type="button" class="aot-ov-pill aot-ov-pill--apart ' +
                        'aot-ov-plot-end">' + _esc(_t('End plot')) + '</button>' : '') +
            '<button type="button" class="aot-ov-pill aot-ov-plot-cancel">' +
            _esc(_t('Cancel')) + '</button>' +
            '<button type="button" class="aot-ov-pill aot-ov-pill--primary aot-ov-plot-save">' +
            _esc(_t('Save')) + '</button>' +
            '</div></div>';
    // [편집]은 보기·폼 **아래** 오른쪽. 시설 [설명] 편집과 같은 자리다.
    html += '<div class="aot-ov-actions">' +
            '<button type="button" class="aot-ov-pill aot-ov-plot-edit">' +
            _esc(_t('Edit')) + '</button></div>';
    html += '</div>';

    // 단계 일정 — **기본 정보 바로 다음**이다. 작물·시작일 다음에 오는 질문이
    // "그래서 언제 무엇을 하나" 이고, 그 답을 고치는 자리가 여기다.
    var _sched = _plotScheduleHtml(p);
    if (_sched) {
      html += '<div class="aot-ov-card-title">' + _esc(_t('Stage schedule')) +
              '</div><div class="aot-ov-block">' + _sched + '</div>';
    }

    html += _plotProgramHtml(p);
    html += _plotPlaceHtml(p);

    // 이 자리 이력 — 연작 장해·윤작 판단의 근거. 도형과 함께 잘 안 변하는
    // 사실이라 [개요]에 둔다(채우는 것은 fillPlotHistory).
    html += '<div class="aot-ov-card-title">' + _esc(_t('History here')) + '</div>' +
            '<div class="aot-ov-block aot-ov-plot-history">' +
            '<div class="aot-ov-plot-history-list">' +
            '<span class="aot-ov-muted">…</span></div></div>';
    return html;
  }



  // 재배 프로그램 — "무엇을 근거로 기르고 있나".
  //
  // P1 은 **무엇을 따르는지까지**다. 현재 단계·목표 적용은 이후 단계에서 붙는다 —
  // 여기서 단계를 지어내 보여주면 사람이 그것을 판정 결과로 읽는다.
  //
  // 프로그램이 지워졌으면 그 사실을 말한다(조용히 빈칸으로 두면 "원래 없었다"로
  // 읽혀 다시 고를 생각을 못 한다).
  var _RESOURCE_ROLES = {
    irrigation: 'Irrigation', fertigation: 'Fertigation', other: 'Other'
  };

  // 못 찾은 이유 → 사람이 무엇을 고쳐야 하는지. 빈칸으로 두면 "자원이 없는
  // 프로그램" 으로 읽혀 아무도 배치를 확인하지 않는다.
  var _RESOURCE_REASONS = {
    'not-placed':    'No device for this here yet',
    'no-facility':   'Outdoor plots cannot resolve this yet',
    'no-vocabulary': 'This role has no device type yet'
  };

  function _plotStageResourceRows(stg) {
    var list = (stg && stg.resources) || [];
    if (!list.length) return '';
    var rows = '';
    var needsApply = false;
    list.forEach(function (r) {
      var label = _t(_RESOURCE_ROLES[r.role] || 'Other');
      var val;
      if (!r.found) {
        // **없음을 조용히 넘기지 않는다.** 프로그램은 역할만 선언하고 함수는
        // 현장이 푼다(P6 재설계) — 그래서 여기서 말할 수 있는 사실이 하나
        // 늘었다: "이 단계는 관수를 요구하는데 이 자리에 관수 장치가 없다".
        val = '<span class="aot-ov-muted">' +
              _esc(_t(_RESOURCE_REASONS[r.reason] || 'Not found here')) +
              '</span>';
      } else {
        // 여럿 잡히는 것은 정상이다(밸브가 여럿인 시설). 무엇이 도는지 목록이
        // 말한다 — 그중 하나를 골라 켜는 것은 사람의 몫이다.
        var names = (r.functions || []).map(function (f) {
          return _esc(f.name || '');
        }).join(', ');
        if (r.active) {
          val = names + ' · ' + _esc(_t('running'));
        } else {
          needsApply = true;
          val = names + ' · <span class="aot-ov-muted">' +
                _esc(_t('stopped')) + '</span>';
        }
      }
      rows += _pRow(label, val);
    });
    if (needsApply) {
      rows += '<div class="aot-ov-desc-actions">' +
              '<button type="button" class="aot-ov-pill aot-ov-pill--primary ' +
                'aot-ov-plot-res-apply">' + _esc(_t('Apply')) + '</button>' +
              '</div>';
    }
    return rows;
  }

  // 단계 전환 제안 — **승인은 기준점을 옮긴다.**
  //
  // 확인하면 그 날부터 남은 단계가 다시 계산된다. 그래서 날짜를 고칠 수 있게
  // 둔다: 계산이 제안한 날과 사람이 관찰한 날이 다를 수 있고, 그 차이가 이후
  // 계산 전체를 좌우한다(docs/design/program-layer.md §P5).
  function _plotStageProposalHtml(p) {
    var pp = p && p.stage_proposal;
    if (!pp) return '';
    // 한 행에 입력과 버튼을 밀어 넣지 않는다 — 라벨/값 두 칸짜리 행이라
    // 좁은 폭에서 줄이 깨진다. 액션은 아래 줄에 따로 둔다(생성 폼과 같은 골격).
    return '<div class="aot-ov-plot-stage-ask" ' +
             'data-stage-key="' + _esc(pp.stage_key || '') + '" ' +
             'data-stage-source="' + _esc(pp.source || '') + '">' +
             '<div class="aot-ov-row">' +
               '<span>' + _esc(_t('Stage change')) + '</span>' +
               '<span>' + _esc(pp.stage_name || pp.stage_key || '') + '</span>' +
             '</div>' +
             '<div class="aot-ov-desc-actions">' +
               '<input type="date" class="form-control aot-modern-input ' +
                 'aot-ov-plot-stage-date" value="' +
                 _esc(pp.started_on || '') + '">' +
               '<button type="button" class="aot-ov-pill aot-ov-pill--primary ' +
                 'aot-ov-plot-stage-ok">' + _esc(_t('Confirm')) + '</button>' +
               // 같은 날짜 칸을 나눠 쓴다 — [확인] 은 "그 날 넘어갔다"(사실),
               // [연기] 는 "그 날 넘어갈 것"(계획). 같은 질문의 두 답이라
               // 입력이 둘일 이유가 없다.
               '<button type="button" class="aot-ov-pill ' +
                 'aot-ov-plot-stage-defer" title="' +
                 _esc(_t('Move this change to the date shown, without recording it as done.')) +
                 '">' + _esc(_t('Postpone')) + '</button>' +
             '</div></div>';
  }

  // 단계 일정 (P8) — **프로그램은 참고고 경계는 구획이 갖는다.**
  //
  // 고치는 값은 **기간(일)** 이다. 날짜를 직접 받으면 사람이 계산해야 한다 —
  // "육묘를 닷새 더" 를 말하려고 정식일을 머릿속에서 더하고, 뒤 단계까지 보려면
  // 그 덧셈을 다섯 번 더 한다. 프로그램이 이미 단계마다 며칠로 적으므로 같은
  // 어휘를 쓴다. 날짜는 그 옆에 **결과로** 보인다(입력이 아니다).
  //
  // 고칠 수 있는 것은 아직 오지 않은 경계뿐이다. 지나간 경계를 옮기는 일은
  // 원장(확인·되돌리기)이 하는 일이고, 두 수단이 같은 값을 다투면 무엇이
  // 정본인지 알 수 없다.
  function _plotScheduleHtml(p) {
    var list = (p && p.stage_schedule) || [];
    if (!list.length) return '';

    var rows = list.map(function (st) {
      var key = _esc(st.key || '');
      var days = (st.days == null) ? '' : String(st.days);
      var shown = (st.days == null)
        ? _esc(_t('until the end'))
        : _esc(_t('%(n)s days').replace('%(n)s', days));

      // 1행 — 이름과 [편집]. 버튼은 이 창의 공용 pill 이다(새로 만들지 않는다).
      var head = '<div class="aot-ov-row">' +
                 '<span>' + _esc(st.name || st.key || '') + '</span>' +
                 '<span><button type="button" class="aot-ov-pill ' +
                   'aot-ov-sched-edit" data-stage-key="' + key + '">' +
                   _esc(_t('Edit')) + '</button></span></div>';

      // 2행 — 시작일과 기간. 평소에는 **읽는 값**이고, [편집] 을 눌러야 입력이
      // 된다. 늘 입력칸으로 두면 여섯 줄이 전부 폼처럼 보여, 일정을 확인하러
      // 온 사람이 무엇을 고칠 참인지부터 헷갈린다.
      var right = '<span class="aot-ov-sched-days-view">' + shown + '</span>';
      if (st.editable) {
        right += '<span class="aot-ov-sched-days-edit" hidden>' +
                 '<input type="number" min="1" step="1" ' +
                 'class="form-control aot-modern-input aot-ov-sched-days" ' +
                 'data-stage-key="' + key + '" value="' + _esc(days) + '"> ' +
                 _esc(_t('days')) + '</span>';
      }
      var body = '<div class="aot-ov-row">' +
                 '<span class="aot-ov-muted">' +
                   _esc(st.starts_on || '\u2014') + '</span>' +
                 '<span>' + right + '</span></div>';

      // 편집 칸 — 기간과 지침을 함께 고치고 [저장] 하나로 보낸다. 저장 버튼이
      // 단계마다 둘이면 어느 것이 무엇을 저장하는지 매번 확인하게 된다.
      var drop = st.removable
        ? '<button type="button" class="aot-ov-pill aot-ov-pill--apart ' +
          'aot-ov-sched-drop" data-stage-key="' + key + '">' +
          _esc(_t('Remove stage')) + '</button>'
        : '';
      var edit = '<div class="aot-ov-sched-edit-wrap" hidden>' +
                 '<textarea class="aot-ov-desc-input aot-ov-sched-guide" ' +
                   'rows="3" data-stage-key="' + key + '" placeholder="' +
                   _esc(_t('What to do in this stage, here.')) + '">' +
                   _esc(st.guidance || '') + '</textarea>' +
                 '<div class="aot-ov-desc-actions">' + drop +
                 '<button type="button" class="aot-ov-pill ' +
                   'aot-ov-pill--primary aot-ov-sched-save" ' +
                   'data-stage-key="' + key + '">' + _esc(_t('Save')) +
                   '</button>' +
                 '</div></div>';

      return '<div class="aot-ov-sched-item">' + head + body + edit + '</div>';
    }).join('');

    // 단계 더하기 — 여는 줄은 폼 푸터가 아니라 `.aot-ov-actions` 다([편집]과
    // 같은 자리).
    var add = '<div class="aot-ov-sched-item aot-ov-sched-add">' +
              '<div class="aot-ov-actions">' +
              '<button type="button" class="aot-ov-pill aot-ov-sched-addopen">' +
              _esc(_t('Add stage')) + '</button></div>' +
              '<div class="aot-ov-sched-add-wrap" hidden>' +
              '<div class="aot-ov-row">' +
              '<span><input type="text" class="form-control aot-modern-input ' +
                'aot-ov-sched-newname" placeholder="' +
                _esc(_t('Stage name')) + '"></span>' +
              '<span><input type="number" min="1" step="1" ' +
                'class="form-control aot-modern-input aot-ov-sched-days ' +
                'aot-ov-sched-newdays" value="7"> ' + _esc(_t('days')) +
                '</span></div>' +
              '<div class="aot-ov-desc-actions">' +
              '<button type="button" class="aot-ov-pill aot-ov-pill--primary ' +
                'aot-ov-sched-addgo">' + _esc(_t('Add')) + '</button>' +
              '</div></div></div>';

    // 자동 승인은 **구획**의 성질이다(P8) — 같은 프로그램을 쓰는 두 구획이
    // 다른 답을 갖는 것이 정상이라 프로그램이 아니라 여기서 정한다.
    var auto = '<div class="aot-ov-row aot-ov-sched-auto">' +
               '<span>' + _esc(_t('Advance stages automatically')) + '</span>' +
               '<span>' + _slideToggle('', 'aot-ov-plot-auto', 'auto',
                                       !!p.auto_advance, '') + '</span></div>';

    return '<div class="aot-ov-plot-sched">' + rows + add + auto +
           '<div class="aot-ov-muted">' +
           _esc(_t('The programme is a reference. Changing one stage moves the ones after it.')) +
           '</div></div>';
  }

  // 확인된 전환 이력. **무른 것도 낸다** — "확인했다가 물렀다" 는 사실 자체가
  // 이력이고, 숨기면 같은 판단을 다시 하게 된다.
  function _plotStageHistoryHtml(p) {
    var hist = (p && p.stage_history) || [];
    if (!hist.length) return '';
    var live = hist.filter(function (h) { return !h.undone; });
    var lines = hist.map(function (h) {
      return '<div class="aot-ov-row' + (h.undone ? ' aot-ov-muted' : '') + '">' +
             '<span>' + _esc(h.started_on || '') + '</span>' +
             '<span>' + _esc(h.stage_key || '') +
               (h.auto ? ' · ' + _esc(_t('auto')) : '') +
               (h.undone ? ' · ' + _esc(_t('undone')) : '') + '</span></div>';
    }).join('');
    // 되돌리기는 **마지막 것만** — 여러 개를 임의로 무르면 기준점이 어디인지
    // 사람이 추적할 수 없다.
    var undo = live.length
      ? '<div class="aot-ov-actions">' +
        '<button type="button" class="aot-ov-pill aot-ov-plot-stage-undo">' +
        _esc(_t('Undo last')) + '</button></div>'
      : '';
    return '<div class="aot-ov-sub-title">' + _esc(_t('Stage log')) + '</div>' +
           lines + undo;
  }

  // 적산온도 — **무엇으로 단계를 판정했는지**를 말한다.
  //
  // 날짜로 되돌아간 경우 그 사실만 알면 고칠 수가 없다. 그래서 이유를 함께
  // 낸다(기준온도 없음 · 센서 없음 · 자료 부족). 아무 근거도 없는 경우
  // (프로그램에 GDD 목표 자체가 없음)에는 줄을 내지 않는다 — 쓰지도 않는
  // 기능의 상태를 모든 구획에 띄우면 화면만 길어진다.
  var _GDD_REASONS = {
    'no-t-base': 'No base temperature set',
    'no-temperature-sensor': 'No temperature sensor for this plot',
    'low-coverage': 'Not enough temperature history',
    'no-start-date': 'No start date',
    'not-started': 'Not started yet',
    'too-early': 'Not started yet'
  };

  function _plotGddRows(stg) {
    var g = stg && stg.gdd;
    if (!g) return '';
    if (g.usable) {
      var val = String(g.value) + ' \u00b0C\u00b7d';
      if (g.coverage_pct != null && g.coverage_pct < 100) {
        val += ' <span class="aot-ov-muted">(' +
               _t('Days covered: {n}').replace('{n}',
                   String(g.coverage_pct) + '%') +
               ')</span>';
      }
      return _pRow(_t('Accumulated heat'), val);
    }
    var why = _GDD_REASONS[g.reason];
    if (!why) return '';
    return _pRow(_t('Accumulated heat'),
                 '<span class="aot-ov-muted">' +
                 _esc(_t('By days') + ' \u00b7 ' + _t(why)) + '</span>');
  }

  function _plotProgramHtml(p) {
    var pr = p.program;
    if (!pr) return '';
    var rows;
    if (pr.missing) {
      rows = '<div class="aot-ov-muted">' +
             _esc(_t('The program this plot followed is gone. Pick another.')) +
             '</div>';
    } else {
      // **바뀌지 않는 사실만.** 현재 단계·적산온도·목표·자원·전환 제안은 전부
      // "지금" 의 값이라 [현황] 이 갖는다 — 두 탭에 같은 것을 두면 어느 쪽이
      // 정본인지 사람이 매번 확인하게 된다.
      rows = _pRow(_t('Name'), _esc(pr.name || '—'));
      rows += _pRow(_t('Stage count'), _esc(String(pr.stage_count || 0)));
      if (pr.total_days) {
        rows += _pRow(_t('Programme length'),
                      _esc(_t('%(n)s days').replace('%(n)s', String(pr.total_days))));
      }
      // 프로그램이 그 뒤 갱신됐다는 사실만 알린다 — 해석은 고정 버전으로 한다.
      if (pr.newer_version) {
        rows += '<div class="aot-ov-muted">' +
                _esc(_t('A newer version of this program exists (not applied).')) +
                '</div>';
      }
      rows += _plotStageHistoryHtml(p);
      // 이 구획의 일정을 프로그램으로 — **이 카드의 맨 아래**다. 무엇을
      // 따르고 있는지 말하는 자리이므로, "이것을 프로그램으로 만든다" 도 같은
      // 자리에서 이어진다. 여닫는 방식은 단계 [편집]과 같다.
      rows += '<div class="aot-ov-actions">' +
              '<button type="button" class="aot-ov-pill aot-ov-sched-regopen">' +
              _esc(_t('Register as programme')) + '</button></div>' +
              '<div class="aot-ov-sched-reg-wrap" hidden>' +
              '<input type="text" class="form-control aot-modern-input ' +
                'aot-ov-sched-regname" placeholder="' +
                _esc(_t('Programme name')) + '">' +
              '<div class="aot-ov-desc-actions">' +
              '<button type="button" class="aot-ov-pill aot-ov-pill--primary ' +
                'aot-ov-sched-reggo">' + _esc(_t('Register')) + '</button>' +
              '</div></div>' +
              // 등록하고 나면 여기에 **단계별 목표 옆의 실측**이 들어온다
              // (`AoTTargetReview`). 등록한 자리에서 바로 보여야 그 숫자로
              // 목표를 고칠지 판단할 수 있다 — 다른 화면으로 옮기면 안 본다.
              '<div class="aot-ov-sched-reg-review" hidden></div>';
    }
    return '<div class="aot-ov-card-title">' + _esc(_t('Program')) +
           '</div><div class="aot-ov-block">' + rows + '</div>';
  }

  // 시설 구획의 자리 — 좌표가 아니라 **이름**이 위치다.
  //
  // 온실 구획은 기하를 그리지 않는다. 위치의 정본이 구역 자체이고("3동"), 지도
  // 폴리곤은 그 구역에서 파생한 표시용이다. 그래서 여기서 말해야 하는 것은
  // 면적이 아니라 **어느 시설의 어느 구역인가**다.
  //
  // 면적·치수를 내지 않는 이유도 한 줄로 밝힌다. 값이 그냥 비어 있으면 사람은
  // "아직 계산 안 됐나" 로 읽는데, 실제로는 낼 수 없는 값이다 — 시설은
  // 노지형·베드형·수직형에 따라 같은 바닥 면적의 재배 규모가 몇 배씩 다르다.
  function _plotPlaceHtml(p) {
    if (p.location_source !== 'facility') return '';
    // 시설과 구역을 **두 행으로** 낸다. "온실1 · 3동" 처럼 이어붙이면 한 열에
    // 두 정보가 들어가고, 열 라벨이 어느 쪽을 가리키는지 흐려진다.
    // 행 라벨은 블록 제목("위치")과 달라야 한다 — 같은 말이 두 번 나오면
    // 사용자는 그것을 오류로 읽는다.
    var rows = _pRow(_t('Facility'), _esc(p.facility_name || '—'));
    if (p.bay_name) rows += _pRow(_t('Zone'), _esc(p.bay_name));
    return '<div class="aot-ov-card-title">' + _esc(_t('Where')) + '</div>' +
           '<div class="aot-ov-block">' +
           rows +
           '<div class="aot-ov-muted">' +
           _esc(_t('Floor area alone does not tell you how much fits inside a facility — record the layout (beds, rows, tiers) in the notes.')) +
           '</div></div>';
  }

  // 구획 정보 — 면적과 치수. 면적만으로는 방향이 있는 질문("몇 줄 들어가나")에
  // 답할 수 없어서 서버가 최소회전 외접사각형의 두 변을 함께 준다.
  //
  // ⚠ `dims.shape_note` 를 여기 그대로 띄우지 말 것 — 그것은 AI 에게 "이 숫자를
  // 보고할 때 이렇게 말하라" 고 지시하는 문장이라, 사용자가 자기에게 하는 말이
  // 아닌 지시문을 읽게 된다. 사람에게는 `rect_fill_pct` 를 근거로 이 자리의
  // 문구를 따로 만든다.
  //
  // 식재량(줄 수·그루 수)은 아직 싣지 않는다 — 간격을 받는 칸이 화면에 없고,
  // 간격 없이는 서버도 세지 않는다(capacity_estimate 는 None 을 돌려준다).
  function _plotDimsHtml(p) {
    var d = p.dims;
    var rows = '';
    if (p.area_m2 != null) {
      rows += _pRow(_t('Area'), _esc(Number(p.area_m2).toLocaleString() + ' m²'));
    }
    if (d && d.width_m != null && d.length_m != null) {
      rows += _pRow(_t('Dimensions'),
                    _esc(d.length_m + ' × ' + d.width_m + ' m'));
    }
    if (!rows) return '';
    var note = '';
    // 서버의 경고 기준(_SHAPE_WARN_RATIO 1.3 = 채움 약 77%)과 같은 선을 쓴다.
    if (d && d.rect_fill_pct != null && d.rect_fill_pct < 77) {
      // msgid 는 한 줄 리터럴로 둔다 — 문자열을 이어붙이면 babel 추출이
      // 조각을 따로 잡거나 아예 놓쳐, 번역이 있는데도 영어가 나온다.
      note = '<div class="aot-ov-muted">' +
             _esc(_t('This plot is not rectangular, so these dimensions are the enclosing rectangle — the usable area is smaller.')) +
             '</div>';
    }
    return '<div class="aot-ov-card-title">' + _esc(_t('Plot information')) +
           '</div><div class="aot-ov-block">' + rows + note + '</div>';
  }

  // 이력 목록을 채운다. rows 는 /api/geo/plots/history 의 history 배열.
  function fillPlotHistory(scopeEl, rows, currentUuid) {
    if (!scopeEl) return;
    var list = scopeEl.querySelector('.aot-ov-plot-history-list');
    if (!list) return;
    var others = (rows || []).filter(function (r) { return r.unique_id !== currentUuid; });
    if (!others.length) {
      list.innerHTML = '<span class="aot-ov-muted">' +
                       _esc(_t('No past plots on this spot.')) + '</span>';
      return;
    }
    var html = '';
    others.forEach(function (h) {
      var period = (h.started_on || '?') + ' → ' + (h.ended_on || _t('ongoing'));
      html += '<div class="aot-ov-row"><span>' + _esc(h.subject) +
              (h.variety ? ' · ' + _esc(h.variety) : '') + '</span><span>' +
              _esc(period) + '</span></div>';
    });
    list.innerHTML = html;
  }

  window.AoTMapPopup = {
    buildPlotModal:  buildPlotModal,
    buildPlotModalSkeleton: buildPlotModalSkeleton,
    latestNotePhoto:    latestNotePhoto,
    buildPhotoCardHtml: buildPhotoCardHtml,
    buildFacilityPlotsHtml: buildFacilityPlotsHtml,
    fillPlotHistory: fillPlotHistory,
    positionDots:      positionDots,
    openOutputSchedule: openOutputSchedule,
    openPlotEnd:        openPlotEnd,
    buildActuatorTabs: buildActuatorTabs,
    emptyBlock:        _emptyBlock,
    buildSensorTabs:   buildSensorTabs,
    wire:              wire,
    buildSectionNav:       buildSectionNav,
    activateSection:       activateSection,
    wireSectionTabs:       wireSectionTabs,
    sectionPane:           sectionPane,
    skeleton:              skeleton,
    buildOverviewSection:  buildOverviewSection,
    buildFacilityDetailSection: buildFacilityDetailSection,
    buildHazardsHtml:      buildHazardsHtml,
    buildIrrigationHtml:   buildIrrigationHtml,
    buildAboutSection:     buildAboutSection,
    buildZoneStatusHtml:   buildZoneStatusHtml,
    buildRecordBlock:      buildRecordBlock,
    buildZoneAboutHtml:    buildZoneAboutHtml,
    buildDescriptionHtml:  buildDescriptionHtml,
    buildEnvNowHtml:       buildEnvNowHtml,
    // 환경 줄의 **판정만** — 좁은 화면이 자기 그림을 그리되 목표/한계 구분은
    // 여기 하나를 쓰게 하려는 것이다(envRowSpec 주석 참조).
    envRowSpec:            envRowSpec,
    envRowChoices:         envRowChoices,
    controlRowChoices:     controlRowChoices,
    buildRowPickerHtml:    buildRowPickerHtml,
    readRowPicker:         readRowPicker,
    wireCardConfig:        wireCardConfig,
    fillEnvSparklines:     fillEnvSparklines,
    wireEnvNowPick:        wireEnvNowPick,
    buildModalHeader:      buildModalHeader,
    scopeBadgeHtml:        scopeBadgeHtml,
    noDataBadgeHtml:       noDataBadgeHtml,
    coverageHtml:          coverageHtml,
    applyStatusDot:        applyStatusDot,
    emptyLine:             emptyLine,
    buildOutputRow:        buildOutputRow,
    scheduleButtonHtml:    scheduleButtonHtml,
    timeSlotHtml:          timeSlotHtml,
    upIconHtml:            upIconHtml,
    applyTimeSlot:         applyTimeSlot,
    seedTimeSlot:          seedTimeSlot,
    nextRunHtml:           nextRunHtml
  };

})();
