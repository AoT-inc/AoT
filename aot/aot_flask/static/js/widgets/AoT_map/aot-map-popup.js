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
    var second = (opts.meta || opts.settings)
      ? '<div class="aot-act-meta">' +
          '<span class="aot-act-meta-text">' + meta + '</span>' +
          '<span class="aot-act-meta-ctrl">' + (opts.settings || '') + '</span>' +
        '</div>'
      : '';
    return '<div class="aot-act-row" data-slot="' + _esc(opts.slot || '') + '">' +
             '<div class="aot-act-line">' +
               (opts.drag ? _dragHandle() : '') +
               '<span class="aot-act-name"' + (opts.nameAttrs || '') + '>' +
               _esc(opts.name || '') + '</span>' +
               (opts.primary || '') +
             '</div>' + second +
           '</div>';
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
  function nextRunHtml(rt) {
    var _tr = function (x) { return (window._ ? window._(x) : x); };
    if (!rt || !rt.next_schedule) return '';
    return ' <span class="aot-act-meta-dim">' + _esc(_tr('Next run')) + ' ' +
           _esc(rt.next_schedule) + '</span>';
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
              nextRunHtml(s.runtime),
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
  function buildSectionNav(active) {
    var secs = [
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
    return buildEnvNowHtml(zone.env, opts) + _ovNotesBlock();
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
  var _endMemory = {};   // outputId → 마지막 종료 시각(초). 새로고침하면 사라짐.

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
    var now = new Date();
    var nowSec = (now.getHours() * 3600) + (now.getMinutes() * 60);
    var lastEndSec = Object.prototype.hasOwnProperty.call(_endMemory, outputId)
      ? _endMemory[outputId] : 0;

    var html =
      '<div class="aot-sensor-popup-header"><b>' + _esc(opts.name || '') + '</b></div>' +
      '<div class="aot-act-group-header">' + _esc(_t('Start time')) + '</div>' +
      '<div class="aot-sched-wheel aot-sched-wheel-start"></div>' +
      '<div class="aot-act-group-header">' + _esc(_t('End time')) + '</div>' +
      '<div class="aot-sched-wheel aot-sched-wheel-end"></div>' +
      '<div class="aot-ov-muted" style="text-align:center;margin:.2rem 0 .5rem">' +
      _esc(_t('00:00 = run indefinitely (no auto off)')) + '</div>' +
      '<div class="aot-sched-status aot-ov-muted" style="text-align:center;margin:0 0 .4rem"></div>' +
      '<div class="aot-wheel-actions">' +
      '<button type="button" class="btn aot-pill-btn aot-sched-cancel">' + _esc(_t('Cancel')) + '</button>' +
      '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary aot-sched-save">' + _esc(_t('Save')) + '</button>' +
      '</div>';

    var popup = shell(html, 'output-sched-' + outputId);
    var el = popup.getElement();
    var startWheel = window.AoTTimeWheel.mount(el.querySelector('.aot-sched-wheel-start'),
      { value: nowSec, fields: 'hm' });
    var endWheel = window.AoTTimeWheel.mount(el.querySelector('.aot-sched-wheel-end'),
      { value: lastEndSec, fields: 'hm' });
    var statusEl = el.querySelector('.aot-sched-status');
    var saveBtn = el.querySelector('.aot-sched-save');

    el.querySelector('.aot-sched-cancel').addEventListener('click', function () { popup.remove(); });
    saveBtn.addEventListener('click', function () {
      var startSec = startWheel.read();
      var endSec = endWheel.read();
      _endMemory[outputId] = endSec;
      saveBtn.disabled = true;
      statusEl.textContent = _t('Saving...');
      _applySchedule(outputId, channel, opts.name || '', startSec, endSec)
        .then(function (res) {
          popup.remove();
          if (res.warn && window.showToast) window.showToast(res.warn, 'warning');
          else if (res.info && window.showToast) window.showToast(res.info, 'info');
          if (typeof opts.onApplied === 'function') opts.onApplied(res);
        })
        .catch(function (e) {
          saveBtn.disabled = false;
          statusEl.textContent = (e && e.message) || _t('Failed');
        });
    });
  }

  // 시작/종료(하루 안의 시:분) → 실제 제어 또는 예약 등록.
  // 종료 00:00 = 무한 작동(자동 꺼짐 없음) → duration 을 아예 보내지 않는다.
  function _applySchedule(outputId, channel, name, startSec, endSec) {
    var nowMs = Date.now();
    var n = new Date(nowMs);
    var start = new Date(n.getFullYear(), n.getMonth(), n.getDate(),
      Math.floor(startSec / 3600), Math.floor((startSec % 3600) / 60), 0, 0);
    // 이미 지난 시각을 골랐다면 "지금"으로 간주 — 다음 날로 밀지 않는다.
    if (start.getTime() < nowMs) start = new Date(nowMs);

    var durationSec = null;
    if (endSec !== 0) {
      var end = new Date(n.getFullYear(), n.getMonth(), n.getDate(),
        Math.floor(endSec / 3600), Math.floor((endSec % 3600) / 60), 0, 0);
      if (end.getTime() <= start.getTime()) end.setDate(end.getDate() + 1);
      durationSec = Math.round((end.getTime() - start.getTime()) / 1000);
    }
    var delaySec = Math.max(0, Math.round((start.getTime() - nowMs) / 1000));

    if (delaySec <= 60) return _fireNow(outputId, channel, durationSec);
    return _proposeJob(outputId, channel, name, start, durationSec)
      .catch(function () {
        // 스케줄러 등록 실패(MCP 서버 미설정/권한 등) → 탭 바인딩 폴백.
        return _fallbackTimer(outputId, channel, durationSec, delaySec);
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

  window.AoTMapPopup = {
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
    buildZoneAboutHtml:    buildZoneAboutHtml,
    buildEnvNowHtml:       buildEnvNowHtml,
    wireEnvNowPick:        wireEnvNowPick,
    buildModalHeader:      buildModalHeader,
    applyStatusDot:        applyStatusDot,
    emptyLine:             emptyLine,
    buildOutputRow:        buildOutputRow,
    scheduleButtonHtml:    scheduleButtonHtml,
    timeSlotHtml:          timeSlotHtml,
    applyTimeSlot:         applyTimeSlot,
    seedTimeSlot:          seedTimeSlot,
    wireTimeSlots:         wireTimeSlots,
    nextRunHtml:           nextRunHtml
  };

})();
