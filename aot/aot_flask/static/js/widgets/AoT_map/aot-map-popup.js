/**
 * aot-map-popup.js
 * Shared popup utilities for AoT Map widgets (v3 + vector).
 *
 * Extracts the duplicated HTML builders, dot-positioning, and event-wiring
 * that previously existed separately in aot-map-widget-v3.js and
 * aot-map-widget-vector.js into a single authoritative module.
 *
 * Public API: window.AoTMapPopup = {
 *   positionDots(containerEl)
 *   buildActuatorCat(catKey, catLabel, states, canCtrl, lastCmd, catKeyFn, savedOrder?)
 *   wire(containerEl, onControl, lastCmdRef)
 *   buildInput(devName, measurements, devId)
 * }
 *
 * @version 1
 */
(function () {
  'use strict';

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

  // ── buildActuatorCat ───────────────────────────────────────────────────────
  // Build the innerHTML for a facility-level actuator category popup.
  //
  //   catKey    string  category key (e.g. 'envelope')
  //   catLabel  string  display label
  //   states    object  { slotKey: { name, kind, control_type, percent,
  //                                   last_target_pct, last_target_source, on } }
  //   canCtrl   bool    whether the current user may send control commands
  //   lastCmd   object  { slotKey: cachedPercent }  (JS-session slider cache)
  //   catKeyFn  function(kind) → catKey  (caller supplies its own mapping)
  //   savedOrder array  user-defined slot order (flat list, all categories)
  function buildActuatorCat(catKey, catLabel, states, canCtrl, lastCmd, catKeyFn, savedOrder) {
    var rows = _buildCatRows(catKey, states, canCtrl, lastCmd, catKeyFn, savedOrder);
    if (!rows) {
      return '<div class="aot-act-empty">' + (window._ ? window._('No actuators') : 'No actuators') + '</div>';
    }
    return '<div class="aot-act-group-header" data-cat="' + _esc(catKey) + '">' +
           _esc(catLabel) + '</div>' + rows;
  }

  // Build only the actuator rows for one category (no header). Returns '' when
  // the category has no actuators. Shared by buildActuatorCat + buildActuatorTabs.
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

  // ── buildActuatorTabs ───────────────────────────────────────────────────────
  // Build a single tabbed popup body covering every category that has at least
  // one actuator. Replaces the old "one chip per category" UI where each chip
  // opened its own popup. One control label → one popup → tabs per group.
  //
  //   activeCatKey  string|null  category to show first (defaults to first
  //                              available); ignored if it has no actuators
  //   cats          array        [{ key, label }, ...] in display order
  //   states/canCtrl/lastCmd/catKeyFn/savedOrder  same as buildActuatorCat
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
      return '<div class="aot-act-empty">' + (window._ ? window._('No actuators') : 'No actuators') + '</div>';
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

    return '<div class="aot-act-tabs" data-active-cat="' + _esc(active) + '">' +
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
      return '<div class="aot-act-empty">' + (window._ ? window._('No Measurements') : 'No Measurements') + '</div>';
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

    return '<div class="aot-act-tabs" data-active-cat="' + _esc(active) + '">' +
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
                 _esc(_t('%(pct)s% of this plot')
                      .replace('%(pct)s', String(coveragePct))) + '</span>');
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
  function timeSlotHtml(opts) {
    var _tr = function (x) { return (window._ ? window._(x) : x); };
    opts = opts || {};
    var rt   = opts.runtime || {};
    var on   = !!(opts.on || (rt.elapsed_sec != null && rt.elapsed_sec > 0));
    var last = (rt.last_duration_sec != null) ? rt.last_duration_sec : null;
    var txt;
    if (on) {
      txt = (rt.elapsed_sec != null && rt.elapsed_sec > 0)
        ? _fmtDur(rt.elapsed_sec) : '…';
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

  // ── buildInput ────────────────────────────────────────────────────────────
  // Build the popup body HTML for an input device (v3 device-level popup).
  // The returned HTML starts with the title div and ends after the measurements.
  // 노트 블록은 포함하지 않는다 — 필요하면 AoTNotesBlock.html() 을 덧붙인다.
  //
  //   devName       string
  //   measurements  array of { id, meas_name|name, last_value, unit }
  //   devId         device ID string (used to build span IDs for live refresh)
  function buildInput(devName, measurements, devId) {
    var html = '<div class="aot-popup-title">' + _esc(devName) + '</div>' +
               '<hr class="aot-popup-divider">';
    if (!measurements || !measurements.length) {
      return html + '<div class="text-muted">' +
             (window._ ? window._('No Measurements') : 'No Measurements') + '</div>';
    }
    measurements.forEach(function (m) {
      var mName   = m.meas_name || m.name || '';
      var mVal    = (m.last_value !== undefined && m.last_value !== null && m.last_value !== '')
                  ? m.last_value : 'N/A';
      var unitStr = m.unit || '';
      if (unitStr === 'bearing') unitStr = '';

      html += '<div class="aot-popup-row">' +
              '<span class="aot-popup-row-label">' + _esc(mName) + '</span>' +
              '<span style="text-align:right;white-space:nowrap;flex:0 0 auto;">' +
              '<span id="popup-val-' + _esc(String(devId)) + '-' + _esc(String(m.id)) + '"' +
              ' class="aot-popup-row-value">' + _esc(String(mVal)) + '</span>' +
              (unitStr ? '<span class="aot-popup-unit">' + _esc(unitStr) + '</span>' : '') +
              '</span></div>';
    });
    return html;
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
  var _LIMIT_LABELS = {
    light: 'Light Level', co2: 'CO2', temperature: 'Temperature',
    water: 'Water (VPD)', humidity: 'Humidity'
  };
  var _KIND_LABELS = {
    opening: 'Opening', curtain: 'Curtain', shade: 'Shade',
    heating: 'Heating', cooling: 'Cooling',
    circulation_fan: 'Circulation Fan', exhaust_fan: 'Exhaust Fan',
    lighting: 'Lighting', irrigation: 'Irrigation',
    humidifier: 'Humidifier', dehumidifier: 'Dehumidifier', co2: 'CO2'
  };

  // 섹션 탭 내비 — [현황](동적) / [환경·제어](센서+제어) / [개요](정적)
  //
  // `secs` 를 넘기면 그 목록으로 그린다. 계층마다 탭 수가 달라도(식생은 아직
  // [환경·제어]가 없다) **내비 빌더는 하나여야 한다** — 계층별로 자기 내비를
  // 손으로 그리기 시작하면 탭 키·순서·클래스가 조용히 갈리고, 구역이 시설과
  // 탭을 맞추느라 한 번 겪은 일이 그대로 재발한다.
  function buildSectionNav(active, secs) {
    secs = secs || [
      { key: 'overview', label: 'Overview' },
      { key: 'envctl',   label: 'Environment & Control' },
      { key: 'about',    label: 'About' }
    ];
    var html = '<div class="aot-act-tabs-nav aot-bay-popup-nav">';
    secs.forEach(function (s) {
      html += '<button type="button" class="aot-act-tab-btn' +
              (s.key === active ? ' active' : '') +
              '" data-sec="' + s.key + '">' + _esc(_t(s.label)) + '</button>';
    });
    return html + '</div>';
  }

  // 추세 선형 외삽 텍스트 (15분, 상한 캡 ±5) — 과신 방지용 "단순 추세" 표기.
  function _trendText(label, perMin, unit) {
    if (perMin == null || !isFinite(perMin)) return '';
    var d = perMin * TREND_LOOKAHEAD_MIN;
    if (Math.abs(d) < 0.05) return '';
    if (d > TREND_DELTA_CAP) d = TREND_DELTA_CAP;
    if (d < -TREND_DELTA_CAP) d = -TREND_DELTA_CAP;
    var dir = d > 0 ? _t('rising') : _t('falling');
    return _t('%(label)s %(dir)s, about %(delta)s expected in %(min)s min')
      .replace('%(label)s', label)
      .replace('%(dir)s', dir)
      .replace('%(min)s', String(TREND_LOOKAHEAD_MIN))
      .replace('%(delta)s', (d > 0 ? '+' : '') + d.toFixed(1) + unit);
  }

  function _devRow(label, dev, unit) {
    if (dev == null || !isFinite(dev)) return '';
    var s = (dev > 0 ? '+' : '') + (+dev).toFixed(1);
    return '<span class="aot-ov-dev">' + _esc(label) + ' ' + s + unit + '</span>';
  }

  // ── 시설 대표사진 / 치수 / 설명 블록 (섹션탭 바로 아래, 현황 pane 최상단) ──
  //   info: GET /api/aot/facility/<uuid>/info 응답
  function _ovInfoBlocks(info) {
    if (!info || !info.ok) return '';
    var html = '';

    // 대표사진 + 등록/변경 버튼 (editor 이상)
    if (info.photo_url || info.can_edit) {
      html += '<div class="aot-ov-block aot-ov-photo-wrap">' +
              '<div class="aot-ov-sec-title">' + _esc(_t('Photo')) + '</div>';
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
      html += '<div class="aot-ov-block aot-ov-dims">' +
              '<div class="aot-ov-sec-title">' +
              _esc(_t('Facility Information')) + '</div>' + rows + '</div>';
    }

    // 설명 (편집/저장은 editor 이상 — can_edit)
    var descView = info.description
      ? _esc(info.description)
      : '<span class="aot-ov-muted">' + _esc(_t('No description')) + '</span>';
    html += '<div class="aot-ov-block aot-ov-desc">' +
            '<div class="aot-ov-sec-title aot-ov-sec-title--row">' +
            '<span>' + _esc(_t('Description')) + '</span>' +
            (info.can_edit
              ? '<button type="button" class="aot-ov-pill aot-ov-desc-edit">' +
                _esc(_t('Edit')) + '</button>'
              : '') +
            '</div>' +
            '<div class="aot-ov-desc-view">' + descView + '</div>' +
            (info.can_edit
              ? '<div class="aot-ov-desc-editwrap" style="display:none">' +
                '<textarea class="aot-ov-desc-input" rows="3" maxlength="2000">' +
                _esc(info.description || '') + '</textarea>' +
                '<div class="aot-ov-desc-actions">' +
                '<button type="button" class="aot-ov-pill aot-ov-desc-save">' +
                _esc(_t('Save')) + '</button>' +
                '<button type="button" class="aot-ov-pill aot-ov-desc-cancel">' +
                _esc(_t('Cancel')) + '</button>' +
                '</div></div>'
              : '') +
            '</div>';
    return html;
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

    // ── 블록 0: IEC 헤더 (시설 전체 표기 + 자동제어 토글) ────────────────
    html += '<div class="aot-ov-block aot-ov-iec">';
    if (fn) {
      html += '<span class="aot-ov-fn-name">' + _esc(_t(fn.name || '')) + '</span>';
      if (opts.canToggle) {
        // 공용 슬라이드 토글 (AoT_timer 등과 동일한 btn-toggle 컴포넌트)
        html += '<label class="btn-toggle aot-iec-toggle">' +
                '<input type="checkbox" class="btn-toggle-input aot-iec-toggle-input"' +
                ' data-active="' + (fn.active ? '1' : '0') + '"' +
                (fn.active ? ' checked' : '') + '>' +
                '<span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>' +
                '</label>';
      } else {
        html += '<span class="aot-act-val-ro">' +
                _esc(fn.active ? _t('Auto Control On') : _t('Auto Control Off')) + '</span>';
      }
    }
    html += '</div>';

    if (!fn) {
      html += '<div class="aot-ov-block aot-ov-inactive">' +
              _esc(_t('No automatic control is linked to this facility')) + '</div>';
      return html + _ovNotesBlock();
    }
    if (stale || !summary) {
      var msg = !fn.active ? _t('Automatic control inactive')
                           : _t('Automatic control not responding (no cycle in 5 minutes)');
      html += '<div class="aot-ov-block aot-ov-inactive">' + _esc(msg);
      var rs = (status && status.reasons) || [];
      if (rs.length) {
        html += '<div class="aot-ov-reasons">' + rs.map(_esc).join('<br>') + '</div>';
      }
      return html + '</div>' + _ovNotesBlock();
    }

    // ── 블록 0.5: Growth Schedule (Env Coordinator 일정 + 현재 주차) ─────
    var sch = summary.schedule || {};
    if (sch.start) {
      var _d = function (v) { return String(v || '').replace(/-/g, '/'); };
      html += '<div class="aot-ov-block aot-ov-schedule">' +
              '<div class="aot-ov-sec-title">' + _esc(_t('Growth Schedule')) + '</div>' +
              '<div class="aot-ov-row"><span>' + _esc(_t('Start Date')) +
              '</span><span>' + _esc(_d(sch.start)) + '</span></div>' +
              '<div class="aot-ov-row"><span>' + _esc(_t('End Date')) +
              '</span><span>' + _esc(sch.end ? _d(sch.end) : '—') + '</span></div>';
      if (sch.week != null) {
        html += '<div class="aot-ov-row"><span>' + _esc(_t('Current')) +
                '</span><span>' +
                _esc(_t('Week %(n)s').replace('%(n)s',
                     String(Math.floor(sch.week) + 1))) +
                '</span></div>';
      }
      html += '</div>';
    }

    // ── 블록 1: 현재 상태 요약 (운전 모드 + 추세 + 예보 선행) ───────────
    var modeStr = (summary.modes || []).map(function (m) {
      return _t(_MODE_LABELS[m] || m);
    }).join(' · ');
    var line = modeStr || _t('Idle (within target range)');
    if (summary.limiting_factor) {
      line += ' — ' + _t('Limiting factor') + ': ' +
              _t(_LIMIT_LABELS[summary.limiting_factor] ||
                 summary.limiting_factor);
    }
    html += '<div class="aot-ov-block aot-ov-modes">' +
            '<div class="aot-ov-sec-title">' + _esc(_t('Status Summary')) + '</div>' +
            '<div class="aot-ov-modes-line">' + _esc(line) + '</div>';
    // 목표 대비 편차 — "지금 얼마나 벗어나 있나". 운전 모드는 무엇을 하는
    // 중인지만 말하고 추세는 어디로 가는지만 말해서, 정작 벗어난 폭은 어디에도
    // 없었다. 서버는 계속 보내고 있었고 렌더 함수(_devRow)도 있었는데 부르는
    // 곳이 없는 죽은 코드였다.
    var dv = summary.deviation || {};
    var devs = [
      _devRow(_t('Temperature'), dv.temperature, '°C'),
      _devRow(_t('Humidity'), dv.humidity, '%'),
      _devRow('VPD', dv.vpd, ' kPa'),
      _devRow('CO2', dv.co2, ' ppm')
    ].filter(Boolean);
    if (devs.length) {
      html += '<div class="aot-ov-trend">' + _esc(_t('Deviation from target')) +
              devs.join('') + '</div>';
    }

    var tr = summary.trend || {};
    var t1 = _trendText(_t('Temperature'), tr.T_per_min, '°C');
    var t2 = _trendText(_t('Humidity'), tr.RH_per_min, '%');
    [t1, t2].forEach(function (t) {
      if (t) html += '<div class="aot-ov-trend">' + _esc(t) + '</div>';
    });
    var ff = summary.feedforward || {};
    if (ff.active && ff.reason) {
      html += '<div class="aot-ov-ff">' + _esc(_t('Forecast Feedforward')) + ': ' +
              _esc(ff.reason) + '</div>';
    }
    html += '</div>';

    // ── 블록 2: 광합성 목표 대비 (시설의 최우선 목표) ───────────────────
    // 행 순서: 효율 → 광량 → VPD → CO2 → 온도 → 습도 → DLI.
    // 값이 있는 행만 출력 (테스트 환경은 설정·센서가 부족할 수 있음).
    var ph  = summary.photo || {};
    var tgt = summary.targets || {};
    var opt = ph.opt || {};
    var phRows = '';
    function _vs(label, cur, target, unit) {
      if (cur == null && target == null) return '';
      var c = cur != null ? String(cur) : '—';
      var g = target != null ? String(target) : '—';
      return '<div class="aot-ov-row"><span>' + _esc(label) + '</span><span>' +
             _esc(c + ' / ' + g + (unit || '')) + '</span></div>';
    }
    if (ph.rate_rel_pct != null) {
      phRows += '<div class="aot-ov-row"><span>' + _esc(_t('Photosynthesis rate')) +
                '</span><span>' + _esc(ph.rate_rel_pct + '%') + '</span></div>';
    }
    // 목표값은 summary.targets(매 사이클 산출 — VPD/CO2 메서드 곡선이면
    // 그 시점의 메서드 값, 온/습도는 VPD 분해 결과) 우선.
    // 작물 상수(opt.*)는 환경 목표가 없을 때의 참고값 폴백.
    phRows += _vs(_t('Light Level'), ph.light, opt.light_k, '');
    phRows += _vs('VPD', ph.vpd, tgt.vpd != null ? tgt.vpd : opt.vpd_half, ' kPa');
    phRows += _vs('CO2', ph.co2, tgt.co2 != null ? tgt.co2 : opt.co2_k, ' ppm');
    phRows += _vs(_t('Temperature'), ph.temp,
                  tgt.temperature != null ? tgt.temperature : opt.t_opt, '°C');
    phRows += _vs(_t('Humidity'), ph.rh, tgt.humidity, '%');
    phRows += _vs('DLI', ph.dli_today, ph.dli_target, '');
    if (phRows) {
      html += '<div class="aot-ov-block aot-ov-photo-goal">' +
              '<div class="aot-ov-sec-title aot-ov-sec-title--row">' +
              '<span>' + _esc(_t('Photosynthesis')) +
              (ph.crop ? ' · ' + _esc(ph.crop) : '') + '</span>' +
              '<span class="aot-ov-muted">' + _esc(_t('Current / Target')) +
              '</span></div>' +
              (ph.enabled ? '' :
                '<div class="aot-ov-muted">' +
                _esc(_t('Photosynthesis mode disabled')) + '</div>') +
              phRows + '</div>';
    }

    // ── 블록 3: 제어 상태 (환기/팬/커튼 등 의미 단위) ───────────────────
    html += '<div class="aot-ov-block aot-ov-ctrl">' +
            '<div class="aot-ov-sec-title">' + _esc(_t('Control Status')) + '</div>';
    var v = summary.vent || {};
    if (v.total_area_m2 > 0) {
      html += '<div class="aot-ov-row"><span>' + _esc(_t('Ventilation')) + '</span><span>' +
              _esc((v.effective_area_m2 != null ? v.effective_area_m2.toFixed(1) : '?') +
              ' m² (' + (v.open_ratio_pct != null ? v.open_ratio_pct.toFixed(0) : '?') +
              '%)') + '</span></div>';
    }
    var gate = summary.gate || {};
    if (gate.triggered) {
      html += '<div class="aot-ov-row aot-ov-gate"><span>' + _esc(_t('Safety Gate')) +
              '</span><span>' + _esc(gate.description || _t('Active')) + '</span></div>';
    }
    var obk = summary.outputs_by_kind || {};
    Object.keys(obk).forEach(function (k) {
      if (k === 'opening') return;   // 환기 행과 중복
      html += '<div class="aot-ov-row"><span>' +
              _esc(_t(_KIND_LABELS[k] || k)) + '</span><span>' +
              _esc(obk[k].toFixed(0) + '%') + '</span></div>';
    });
    html += '</div>';

    return html + _ovNotesBlock();
  }

  // [개요] 섹션 — 정적 정보: 대표사진 / 시설 정보 / 설명 / 노트.
  //   info: GET /api/aot/facility/<uuid>/info 응답
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
        _esc(_t('Go up')) + '">&#x2190;</button>'
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
  function buildEnvNowHtml(env, opts) {
    env = env || {};
    opts = opts || {};
    var readings = env.readings || [];
    var sensors = env.sensors || {};
    if (!readings.length && !sensors.total) return '';

    var head = '<div class="aot-ov-sec-title aot-ov-sec-title--row">' +
               '<span>' + _esc(_t('Now')) + '</span>';
    if (sensors.total && sensors.valid < sensors.total) {
      // 'Sensors' 를 쓰지 않는다 — 그 msgid 는 설정 화면에서 "센서류"(장치 분류)
      // 로 번역돼 있어 "센서류 2/3" 이 된다. 뜻이 다르면 msgid 를 나눈다.
      head += '<span class="aot-ov-degraded">' +
              _esc(_t('Sensors responding')) + ' ' +
              sensors.valid + '/' + sensors.total +
              '</span>';
    }
    head += '</div>';

    var body;
    if (readings.length) {
      body = '<div class="aot-env-now">' + readings.map(function (r) {
        var dec = (window.AoTSensorLabel && window.AoTSensorLabel.defaultDecimals)
          ? window.AoTSensorLabel.defaultDecimals(r.key) : 1;
        var name = (window.AoTSensorLabel && window.AoTSensorLabel.keyDisplay)
          ? window.AoTSensorLabel.keyDisplay(r.key) : r.key;
        // 단위 정규화는 공용 함수 하나만 쓴다(값 라벨·차트 레전드와 같은 판단).
        var unit = (window.AoTSensorLabel && window.AoTSensorLabel.displayUnit)
          ? window.AoTSensorLabel.displayUnit(r.unit)
          : String(r.unit || '').trim();
        var isRep = !!(opts.repKey && r.key === opts.repKey);
        // 지정 가능할 때만 버튼처럼 보이게 한다 — 권한이 없는 사람에게 눌리는
        // 시늉을 보여 주면 눌러 보고 아무 일도 안 일어나는 것을 겪는다.
        var hint = isRep ? _t('Representative measurement')
                         : (opts.selectable ? _t('Set as representative') : '');
        return '<div class="aot-env-now-item' +
                 (isRep ? ' is-rep' : '') +
                 (opts.selectable ? ' is-selectable' : '') + '"' +
                 ' data-rep-key="' + _esc(r.key) + '"' +
                 (hint ? ' title="' + _esc(hint) + '"' : '') +
                 (opts.selectable ? ' role="button" tabindex="0"' : '') + '>' +
                 '<div class="aot-env-now-val">' +
                 _esc((+r.value).toFixed(dec)) +
                 '<span class="aot-env-now-unit">' + _esc(unit) + '</span>' +
                 '</div>' +
                 '<div class="aot-env-now-key">' + _esc(name) + '</div>' +
               '</div>';
      }).join('') + '</div>';
    } else {
      body = '<div class="aot-ov-muted">' + _esc(_t('No sensor readings')) + '</div>';
    }

    // 바깥 — 시설에만 있다(구역은 실내/실외 구분이 없다). 한 줄로 붙이는 이유:
    // 안이 더운 것이 문제인지 그냥 바깥이 더운 날인지는 둘을 나란히 놔야
    // 판단할 수 있는데, 값을 크게 넣으면 실내값과 구분이 안 된다.
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
    return '<div class="aot-ov-block">' + head + body + '</div>';
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
    return buildEnvNowHtml(zone.env, opts) +
           buildZonePlantingsHtml(zone.allocation) +
           buildScheduleHtml(zone.schedule, { addable: !!(opts && opts.canAdd) }) +
           _ovNotesBlock();
  }

  // ── 다가오는 일정 ─────────────────────────────────────────────────────────
  //
  // **하나의 목록이다.** 예전에는 이것을 '농작업' 과 '장치 예약' 으로 갈랐는데
  // 둘 다 틀렸다:
  //
  //  1. 시스템에 그런 구분이 없다. 전부 같은 `SchedulerJobMeta` 이고, 내가
  //     가른 축은 실은 **대상이 도형이냐 장치냐** 였다. 그걸 일의 종류인 것처럼
  //     이름 붙이면 화면이 없는 개념을 있는 것처럼 말한다.
  //  2. '농작업' 은 용도를 농업으로 못 박는 말이다. 이 소프트웨어는 온실·축사만
  //     아니라 공원·시설물·교통에도 쓴다고 이미 정해 두었다(landing 문구).
  //
  // 구분이 필요하면 줄 자체가 말한다 — 담당자가 있으면 사람이 하는 일이고,
  // 'On (20min)' 이면 장치가 하는 일이다.
  //
  //   opts.addable  추가 버튼을 헤더에 단다(구획 모달). 이때는 목록이 비어도
  //                 블록을 그린다 — 안 그러면 더할 자리가 아예 없어진다.
  function buildScheduleHtml(sched, opts) {
    opts = opts || {};
    var items = [].concat((sched && sched.own) || [],
                          (sched && sched.devices) || []);
    if (!items.length && !opts.addable) return '';

    items.sort(function (a, b) {
      return String(a.when || '').localeCompare(String(b.when || ''));
    });

    var html = '<div class="aot-ov-block aot-ov-schedule-upcoming">' +
      '<div class="aot-ov-sec-title' +
      (opts.addable ? ' aot-ov-sec-title--row' : '') + '">' +
      '<span>' + _esc(_t('Coming up')) + '</span>' +
      (opts.addable
        ? '<button type="button" class="aot-ov-pill aot-ov-sched-open">' +
          _esc(_t('Add')) + '</button>'
        : '') + '</div>';

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
    return html + (opts.addable ? _scheduleFormHtml() : '') + '</div>';
  }


  // 일정 추가 폼 배선 — **네 계층 공통**(대지·구역·식생·시설).
  //
  // 대상은 uuid 로 넘긴다. 이름으로 고르지 않는 이유는 서버 주석에 있다 —
  // 같은 작물이 두 곳에 있으면 이름만으로는 못 고른다.
  //
  //   onSaved(schedule)  저장 뒤 갱신 방법은 계층마다 다르다(모달을 다시 열기도
  //                      하고, 블록만 갈아 끼우기도 한다) — 호출자가 정한다.
  function wireScheduleAdd(scopeEl, opts) {
    opts = opts || {};
    var wrap = scopeEl && scopeEl.querySelector('.aot-ov-schedule-upcoming');
    if (!wrap || wrap._schedWired) return;
    var form = wrap.querySelector('.aot-ov-sched-form');
    var open = wrap.querySelector('.aot-ov-sched-open');
    if (!form || !open || !opts.targetId) return;
    wrap._schedWired = true;

    function show(on) {
      form.style.display = on ? '' : 'none';
      open.style.display = on ? 'none' : '';
      if (on) {
        var c = form.querySelector('[data-sf="content"]');
        if (c) c.focus();
      }
    }
    open.addEventListener('click', function () { show(true); });
    var cancel = wrap.querySelector('.aot-ov-sched-cancel');
    if (cancel) cancel.addEventListener('click', function () { show(false); });

    var save = wrap.querySelector('.aot-ov-sched-save');
    if (!save) return;
    save.addEventListener('click', function () {
      var payload = { target_id: opts.targetId };
      form.querySelectorAll('[data-sf]').forEach(function (el) {
        payload[el.getAttribute('data-sf')] = el.value || '';
      });
      if (!payload.content || !payload.date) {
        if (window.showToast) {
          window.showToast(_t('Enter a date and what to do'), 'warning');
        }
        return;
      }
      save.disabled = true;
      var meta = document.querySelector('meta[name="csrf-token"]');
      fetch('/api/geo/schedule', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json',
                   'X-Requested-With': 'XMLHttpRequest',
                   'X-CSRFToken': meta ? meta.getAttribute('content') : '' },
        body: JSON.stringify(payload)
      })
        .then(function (r) { return r.json().catch(function () { return null; }); })
        .then(function (d) {
          save.disabled = false;
          if (!d || !d.ok) {
            if (window.showToast) {
              window.showToast((d && d.message) || _t('Save failed'), 'error');
            }
            return;
          }
          if (opts.onSaved) opts.onSaved(d.schedule);
        })
        .catch(function () { save.disabled = false; });
    });
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

    var html = '<div class="aot-ov-block aot-ov-record">' +
      '<div class="aot-ov-sec-title">' + _esc(_t('Records')) + '</div>';

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

    // 지난 것 = 노트. 소제목 단으로 낮춰 이 블록 안에 넣는다.
    html += (window.AoTNotesBlock
      ? window.AoTNotesBlock.html({ sub: true, title: _t('Up to now') })
      : '');
    return html + '</div>';
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
  function buildZonePlantingsHtml(alloc) {
    if (!alloc) return '';
    var items = alloc.plantings || [];
    var html = '<div class="aot-ov-block aot-ov-zone-plantings">' +
               '<div class="aot-ov-sec-title">' +
               _esc(_t('Growing now')) + '</div>';

    if (!items.length) {
      html += '<div class="aot-ov-muted">' +
              _esc(_t('Nothing is planted in this zone.')) + '</div></div>';
      return html;
    }

    items.forEach(function (p) {
      var right = [];
      if (p.days_since_planted != null) {
        right.push(_esc(_t('Day %(n)s')
                        .replace('%(n)s', String(p.days_since_planted))));
      }
      if (p.area_m2 != null) {
        var a = Number(p.area_m2).toLocaleString() + ' m²';
        if (p.ratio_pct != null) a += ' (' + p.ratio_pct + '%)';
        right.push(_esc(a));
      }
      // 줄을 누르면 그 구획 모달로 내려간다(필지 → 구역과 같은 규약).
      html += '<div class="aot-ov-row aot-ov-planting-link" ' +
              'data-planting-uuid="' + _esc(p.unique_id) + '" ' +
              'style="cursor:pointer"><span>' +
              _esc(p.crop || p.name || '—') +
              (p.variety ? ' <span class="aot-ov-muted">· ' +
                           _esc(p.variety) + '</span>' : '') +
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
  function buildZoneAboutHtml(zone) {
    zone = zone || {};
    var html = '';
    var counts = zone.counts || {};

    if (zone.photo_url || zone.can_edit) {
      html += '<div class="aot-ov-block aot-ov-photo-wrap">' +
              '<div class="aot-ov-sec-title">' + _esc(_t('Photo')) + '</div>';
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
    html += '<div class="aot-ov-block aot-ov-dims">' + rows + '</div>';

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
      '<div class="aot-sensor-popup-header"><b>' + _esc(name) + '</b></div>' +
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
      '<div class="modal-footer">' +
      '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary aot-sched-cancel">' + _esc(_t('Close')) + '</button>' +
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
    { key: 'about',    label: 'About' }
  ];

  // 위젯 옵션 popup_default_tab 은 세 키를 쓰는데 식생은 그중 둘만 갖는다 —
  // 'envctl' 로 설정된 대시보드에서 식생을 열면 존재하지 않는 탭을 요구받는다.
  // 그때는 조용히 [현황]으로 떨어뜨린다(빈 화면보다 낫다).
  function plantingDefaultSec(want) {
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

  function _pPane(key, active, inner) {
    return '<div class="aot-bay-popup-pane" data-pane="' + key + '"' +
           (key === active ? '' : ' style="display:none"') + '>' + inner + '</div>';
  }

  function buildPlantingModal(p, opts) {
    p = p || {};
    opts = opts || {};
    var defSec = plantingDefaultSec(opts.defaultTab);
    // up: 소속 구역으로 올라간다. 버튼은 hidden 으로 자리만 잡고, 상위가
    // 확인되면 위젯이 드러낸다(_wireUpBtn) — 구역을 못 찾은 구획에서는 눌러도
    // 아무 일 없는 버튼이 남지 않는다.
    return buildModalHeader({ name: p.name || p.crop || _t('Planting'),
                              up: true, status: null }) +
           buildSectionNav(defSec, _PLANTING_SECS) +
           _pPane('overview', defSec, _plantingOverviewHtml(p)) +
           // [환경·제어]는 별도 조회(/contents)라 빈 칸으로 열어 두고
           // 도착하면 채운다 — 그 왕복 때문에 모달 전체를 늦추지 않는다.
           _pPane('envctl',   defSec, '') +
           _pPane('about',    defSec, _plantingAboutHtml(p));
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
  function _plantingOverviewHtml(p) {
    // 제목은 목록 쪽('심겨 있는 것')과 달라야 한다 — 같은 말을 쓰면 블록
    // 제목과 첫 행 라벨이 겹쳐 "심겨 있는 것 / 심은 것" 으로 읽힌다.
    var html = '<div class="aot-ov-block">' +
               '<div class="aot-ov-sec-title">' + _esc(_t('This plot')) +
               '</div>';

    html += _pRow(_t('Planted'), _esc(p.crop || '—') +
                  (p.variety ? ' · ' + _esc(p.variety) : ''));

    // 재배 일수 — 심은 날이 1일차(서버 elapsed_days 가 정본).
    //
    // 끝난 작기는 **기간**이지 나이가 아니다. 같은 숫자라도 "60일차"(지금 60일째
    // 자라는 중)와 "60일"(60일간 길렀다)은 다른 말이라, 종료된 작기에 '일차'를
    // 쓰면 아직 자라고 있는 것처럼 읽힌다.
    if (p.days_since_planted != null) {
      var n = String(p.days_since_planted);
      html += _pRow(p.ended_on ? _t('Grown for') : _t('Days since planting'),
                    _esc((p.ended_on ? _t('%(n)s days') : _t('Day %(n)s'))
                         .replace('%(n)s', n)));
    }
    html += _pRow(_t('Planted on'), _esc(p.planted_on || '—'));

    // 예상 종료까지 — 지난 것을 숨기지 않는다. 늦어지고 있다는 것 자체가
    // 사용자가 봐야 할 사실이다.
    if (p.expected_end_on) {
      var due = _esc(p.expected_end_on);
      var d = p.days_to_expected_end;
      if (d != null) {
        due += ' <span class="aot-ov-muted">(' +
               (d >= 0
                 ? _esc(_t('in %(n)s days').replace('%(n)s', String(d)))
                 : _esc(_t('%(n)s days overdue').replace('%(n)s',
                        String(-d)))) + ')</span>';
      }
      html += _pRow(_t('Expected end'), due);
    }
    if (p.ended_on) html += _pRow(_t('Ended'), _esc(p.ended_on));
    html += '</div>';

    // 물 줄 수단이 없다 — 장치 목록이 아니라 **빠진 것**을 알리는 줄이다.
    // 정상일 때는 나오지 않으므로 평소 화면을 어지럽히지 않는다.
    html += _plantingNoValveHtml(p);

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
  function _plantingNoValveHtml(p) {
    var valves = p.valves;
    if (!Array.isArray(valves)) return '';
    var open = valves.filter(function (v) { return v.unassigned; });
    if (!open.length) return '';
    return '<div class="aot-ov-block aot-ov-planting-novalve">' +
           '<div class="aot-ov-muted">' +
           _esc(_t('A device area over this plot has no device assigned yet.')) +
           '</div></div>';
  }


  // ── 일정 추가 폼 ─────────────────────────────────────────────────────────
  //
  // **구획을 직접 겨냥하는 유일한 경로다.** 이름 리졸버는 그대로 구역을
  // 돌려준다(설계 §이름 해석) — 이름만으로 고르면 같은 작물이 두 구역에 있을
  // 때 엉뚱한 곳에 조용히 남기 때문이다. 이 폼은 사람이 그 구획의 모달을 열어
  // 놓고 쓰므로 고를 것이 없다.
  //
  // 새 모달을 띄우지 않는다 — 모달 위에 모달을 쌓지 않는다는 규약이 있고,
  // 입력이 네 칸뿐이라 접힌 폼으로 충분하다.
  function _scheduleFormHtml() {
    var _v = function (x) { return _esc(x == null ? '' : x); };
    var _row = function (label, ctrl) {
      return '<div class="aot-modal-option-row">' +
             '<div class="aot-modal-option-label">' + _esc(label) + '</div>' +
             '<div class="aot-modal-option-control">' + ctrl + '</div></div>';
    };
    var _in = function (f, t) {
      return '<input type="' + t + '" class="aot-modern-input form-control" ' +
             'data-sf="' + f + '">';
    };
    // 기본 날짜는 내일 — 오늘 잡는 일보다 앞으로 잡는 일이 많다.
    var d = new Date(Date.now() + 86400000);
    var def = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') +
              '-' + String(d.getDate()).padStart(2, '0');

    return '<div class="aot-ov-sched-form" style="display:none">' +
      '<div class="aot-modal-container">' +
      _row(_t('Date'), '<input type="date" class="aot-modern-input form-control"' +
           ' data-sf="date" value="' + _v(def) + '">') +
      _row(_t('Time'), '<input type="time" class="aot-modern-input form-control"' +
           ' data-sf="time" value="07:00">') +
      _row(_t('What'), _in('content', 'text')) +
      _row(_t('Worker'), _in('worker', 'text')) +
      '</div>' +
      '<div class="aot-ov-desc-actions">' +
      '<button type="button" class="btn aot-pill-btn aot-ov-sched-cancel">' +
      _esc(_t('Cancel')) + '</button>' +
      '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary aot-ov-sched-save">' +
      _esc(_t('Save')) + '</button>' +
      '</div></div>';
  }

  // ── [개요] — 잘 안 변하는 사실 + 편집 ───────────────────────────────────
  function _plantingAboutHtml(p) {
    // 보기와 편집을 같은 블록에 두고 토글한다(구역 모달의 설명 편집과 같은
    // 방식: aot-ov-desc-*). geo/design 은 도형만 다루므로 **작물·기간을 고치는
    // 자리는 여기다.**
    // 제목은 첫 행 라벨('심은 것')과 달라야 한다 — 같으면 "심은 것 / 심은 것"
    // 으로 읽힌다([현황]에서 한 번 겪은 것과 같은 문제).
    var html = '<div class="aot-ov-block aot-ov-planting-info">' +
            '<div class="aot-ov-sec-title aot-ov-sec-title--row">' +
            '<span>' + _esc(_t('Basics')) + '</span>' +
            '<button type="button" class="aot-ov-pill aot-ov-planting-edit">' +
            _esc(_t('Edit')) + '</button></div>';

    html += '<div class="aot-ov-planting-view">';
    html += _pRow(_t('Planted'), _esc(p.crop || '—') +
                   (p.variety ? ' · ' + _esc(p.variety) : ''));
    if (p.name) html += _pRow(_t('Plot name'), _esc(p.name));
    html += _pRow(_t('Planted on'), _esc(p.planted_on || '—'));
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
      return '<input type="' + type + '" class="aot-modern-input form-control" ' +
             'data-pf="' + field + '" value="' + _v(val) + '">';
    };

    html += '<div class="aot-ov-planting-edit-wrap" style="display:none">' +
            '<div class="aot-modal-container">' +
            _fRow(_t('Planted'), _inp('crop', 'text', p.crop)) +
            _fRow(_t('Variety'), _inp('variety', 'text', p.variety)) +
            _fRow(_t('Plot name'), _inp('name', 'text', p.name)) +
            _fRow(_t('Planted on'), _inp('planted_on', 'date', p.planted_on)) +
            _fRow(_t('Expected end'), _inp('expected_end_on', 'date', p.expected_end_on)) +
            '<div class="aot-modal-option-row">' +
            '<div class="aot-modal-option-label">' + _esc(_t('Colour')) + '</div>' +
            '<div class="aot-modal-option-control aot-modal-detail-field aot-detail-field-color">' +
            '<input type="color" class="aot-modern-input form-control" data-pf="color" value="' +
            _v(p.color || '#6a8f3c') + '"></div></div>' +
            '</div>' +
            '<div class="aot-ov-desc-actions">' +
            '<button type="button" class="btn aot-pill-btn aot-ov-planting-cancel">' +
            _esc(_t('Cancel')) + '</button>' +
            '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary aot-ov-planting-save">' +
            _esc(_t('Save')) + '</button>' +
            (p.active ? '<button type="button" class="btn aot-pill-btn aot-ov-planting-end">' +
                        _esc(_t('End planting')) + '</button>' : '') +
            '</div></div>';
    html += '</div>';

    html += _plantingDimsHtml(p);

    // 이 자리 이력 — 연작 장해·윤작 판단의 근거. 도형과 함께 잘 안 변하는
    // 사실이라 [개요]에 둔다(채우는 것은 fillPlantingHistory).
    html += '<div class="aot-ov-block aot-ov-planting-history">' +
            '<div class="aot-ov-sec-title">' + _esc(_t('History here')) + '</div>' +
            '<div class="aot-ov-planting-history-list">' +
            '<span class="aot-ov-muted">…</span></div></div>';
    return html;
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
  function _plantingDimsHtml(p) {
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
    return '<div class="aot-ov-block">' +
           '<div class="aot-ov-sec-title">' + _esc(_t('Plot information')) +
           '</div>' + rows + note + '</div>';
  }

  // 이력 목록을 채운다. rows 는 /api/geo/plantings/history 의 history 배열.
  function fillPlantingHistory(scopeEl, rows, currentUuid) {
    if (!scopeEl) return;
    var list = scopeEl.querySelector('.aot-ov-planting-history-list');
    if (!list) return;
    var others = (rows || []).filter(function (r) { return r.unique_id !== currentUuid; });
    if (!others.length) {
      list.innerHTML = '<span class="aot-ov-muted">' +
                       _esc(_t('No past plantings on this spot.')) + '</span>';
      return;
    }
    var html = '';
    others.forEach(function (h) {
      var period = (h.planted_on || '?') + ' → ' + (h.ended_on || _t('ongoing'));
      html += '<div class="aot-ov-row"><span>' + _esc(h.crop) +
              (h.variety ? ' · ' + _esc(h.variety) : '') + '</span><span>' +
              _esc(period) + '</span></div>';
    });
    list.innerHTML = html;
  }

  window.AoTMapPopup = {
    buildPlantingModal:  buildPlantingModal,
    plantingDefaultSec:  plantingDefaultSec,
    fillPlantingHistory: fillPlantingHistory,
    positionDots:      positionDots,
    openOutputSchedule: openOutputSchedule,
    buildActuatorCat:  buildActuatorCat,
    buildActuatorTabs: buildActuatorTabs,
    buildSensorTabs:   buildSensorTabs,
    wire:              wire,
    buildInput:       buildInput,
    buildSectionNav:       buildSectionNav,
    buildOverviewSection:  buildOverviewSection,
    buildAboutSection:     buildAboutSection,
    buildZoneStatusHtml:   buildZoneStatusHtml,
    buildScheduleHtml:     buildScheduleHtml,
    wireScheduleAdd:       wireScheduleAdd,
    buildRecordBlock:      buildRecordBlock,
    buildZoneAboutHtml:    buildZoneAboutHtml,
    buildEnvNowHtml:       buildEnvNowHtml,
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
    applyTimeSlot:         applyTimeSlot,
    seedTimeSlot:          seedTimeSlot,
    wireTimeSlots:         wireTimeSlots,
    nextRunHtml:           nextRunHtml,
    refreshOutputScheduleLabel: refreshOutputScheduleLabel
  };

})();
