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
 *   buildNoteSection(uniqueKey, devName)
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

  function _buildActRow(sk, s, ct, canCtrl, lastCmd) {
    var name     = _esc(s.name || sk);
    var _tr      = function (x) { return (window._ ? window._(x) : x); };
    var curPct   = s.percent != null ? parseFloat(s.percent) : (s.on ? 100 : 0);

    // ── ON/OFF binary: 공용 슬라이드 토글, 제목 오른쪽 끝 정렬 ───────────────
    if (ct === 'binary') {
      var ctrl = canCtrl
        ? _slideToggle('aot-act-toggle-right', 'aot-act-toggle-input', sk, !!s.on)
        : '<span class="aot-act-val-ro aot-act-toggle-right ' +
          (s.on ? 'aot-act-on' : 'aot-act-off') + '">' +
          (s.on ? 'ON' : 'OFF') + '</span>';
      return '<div class="aot-act-row" data-slot="' + _esc(sk) + '">' +
             '<div class="aot-act-line">' +
             (canCtrl ? _dragHandle() : '') +
             '<span class="aot-act-name">' + name + '</span>' + ctrl +
             '</div></div>';
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

      return '<div class="aot-act-row" data-slot="' + _esc(sk) + '">' +
             '<div class="aot-act-line">' +
             (canCtrl ? _dragHandle() : '') +
             '<span class="aot-act-name">' + name + '</span>' + btns +
             '</div>' +
             '<div class="aot-act-row-top">' +
             '<span class="aot-act-val-current">' + _esc(info) + '</span><span></span>' +
             '</div>' + sliderHtml + '</div>';
    }

    // ── PWM slider (기존 유지) ───────────────────────────────────────────────
    var globalTarget = (window._aotActuatorTargetPct &&
                        window._aotActuatorTargetPct[sk.split('::')[0]] !== undefined)
                       ? window._aotActuatorTargetPct[sk.split('::')[0]] : null;
    var thumbPct = globalTarget !== null ? globalTarget : curPct;

    var inner = '<span class="aot-act-name">' + name + '</span>' +
                '<div class="aot-act-row-top">' +
                '<span class="aot-act-val">' + curPct.toFixed(0) + '%</span>' +
                '<span></span></div>';
    if (canCtrl) {
      inner += '<input type="range" class="aot-act-slider" min="0" max="100" step="1"' +
               ' value="' + thumbPct.toFixed(0) + '"' +
               ' data-slot="' + _esc(sk) + '" data-ct="' + ct + '">';
    }
    return '<div class="aot-act-row" data-slot="' + _esc(sk) + '">' +
           (canCtrl ? _dragHandle() : '') + inner + '</div>';
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
  // Note section is NOT included — call buildNoteSection separately and append.
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

  // ── buildNoteSection ──────────────────────────────────────────────────────
  // Build the "Create Note" button + preview div HTML shared across popup types.
  // The preview div always has id="note-prev-{uniqueKey}" so the caller's
  // fetchLastNote() can look it up by document.getElementById.
  function buildNoteSection(uniqueKey, devName) {
    var notePreviewId = 'note-prev-' + _esc(String(uniqueKey));
    var safeName      = String(devName || '').replace(/'/g, "\\'");
    var openAction    = 'window.dispatchEvent(new CustomEvent(\'open-notes\',' +
                        '{detail:{targetId:\'' + _esc(String(uniqueKey)) + '\',' +
                        'targetType:\'device\',name:\'' + safeName + '\'}}))';
    return '<hr class="aot-popup-divider">' +
           '<button class="aot-popup-btn aot-popup-btn--primary aot-popup-btn--full" onclick="' + openAction + '">' +
           (window._ ? window._('Create Note') : 'Create Note') + '</button>' +
           '<div id="' + notePreviewId + '" class="aot-popup-note-preview">' +
           '<span style="color:#ccc;font-style:italic;">...</span></div>';
  }

  // ── [현황] 탭 빌더들 ────────────────────────────────────────────────────────
  // env_summary(데몬 사이클 스냅샷) + status 를 4블록으로 요약 렌더.
  // 규격 정보는 의도적으로 배제 — "지금 무슨 일이 일어나는가"만.

  function _t(s) { return (window._ ? window._(s) : s); }

  // [현황] 표시 정책 상수 — 본문에 숫자를 직접 박지 않는다.
  var TREND_LOOKAHEAD_MIN = 15;   // 추세 선형 외삽 구간 (분)
  var TREND_DELTA_CAP     = 5;    // 외삽 표시값 상한 (과신 방지)
  var NOTES_MAX           = 2;    // 노트 미리보기 개수
  var NOTE_TEXT_MAX       = 60;   // 노트 본문 미리보기 글자 수
  var NOTE_THUMBS_MAX     = 4;    // 노트 첨부 썸네일 개수

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

  // 노트 블록 자리 — 목록은 호출자가 /notes/target/<uuid> 로 비동기 채움.
  // 제목 행 우측의 노트창 호출 버튼(.aot-ov-notes-open)은 호출자가
  // open-notes CustomEvent 디스패치로 wire 한다 (조회 + 작성 패널).
  function _ovNotesBlock() {
    return '<div class="aot-ov-block aot-ov-notes">' +
           '<div class="aot-ov-sec-title aot-ov-sec-title--row">' +
           '<span>' + _esc(_t('Notes')) + '</span>' +
           '<button type="button" class="aot-ov-notes-open">' +
           _esc(_t('Create Note')) + '</button>' +
           '</div>' +
           '<div class="aot-ov-notes-list"><span class="aot-ov-muted">…</span></div>' +
           '</div>';
  }

  // 노트 목록 채우기 — buildOverviewSection 렌더 후 호출.
  //   listEl: .aot-ov-notes-list, notes: /notes/target 응답 배열 (최신순)
  function fillOverviewNotes(listEl, notes, onOpenAll) {
    if (!listEl) return;
    if (!Array.isArray(notes) || !notes.length) {
      listEl.innerHTML = '<span class="aot-ov-muted">' +
                         _esc(_t('No records')) + '</span>';
      return;
    }
    var html = '';
    notes.slice(0, NOTES_MAX).forEach(function (n) {
      var d = '';
      try {
        var dt = new Date(n.date_time);
        if (!isNaN(dt)) d = (dt.getMonth() + 1) + '/' + dt.getDate();
      } catch (e) {}
      var txt = String(n.note || '').replace(/\s+/g, ' ').slice(0, NOTE_TEXT_MAX);

      // 첨부 처리: 이미지 → 썸네일(최대 4), 그 외 파일 → 개수 표기
      var files = String(n.files || '').split(',')
        .map(function (t) { return t.trim(); }).filter(Boolean);
      var imgs = files.filter(function (f) {
        return /\.(jpg|jpeg|png|gif|webp|bmp|heic)$/i.test(f);
      });
      var otherCnt = files.length - imgs.length;
      var att = '';
      if (imgs.length) {
        att += '<div class="aot-ov-note-thumbs">' +
               imgs.slice(0, NOTE_THUMBS_MAX).map(function (f) {
                 return '<img src="/note_attachment/' + _esc(f) + '" alt="" loading="lazy">';
               }).join('') +
               (imgs.length > NOTE_THUMBS_MAX
                 ? '<span class="aot-ov-muted">+' + (imgs.length - NOTE_THUMBS_MAX) +
                   '</span>' : '') +
               '</div>';
      }
      if (otherCnt > 0) {
        att += '<div class="aot-ov-note-files">' + _esc(_t('Attachments')) + ' ' + otherCnt + '</div>';
      }

      html += '<div class="aot-ov-note">' +
              '<div class="aot-ov-note-row">' +
              '<span class="aot-ov-note-date">' + _esc(d) + '</span>' +
              '<span class="aot-ov-note-text">' + (_esc(txt) ||
                ('<span class="aot-ov-muted">' + _esc(_t('Attachments')) + '</span>')) + '</span>' +
              '</div>' + att + '</div>';
    });
    if (onOpenAll) {
      html += '<button type="button" class="aot-popup-btn aot-ov-notes-all">' +
              _esc(_t('View All')) + '</button>';
    }
    listEl.innerHTML = html;
    if (onOpenAll) {
      var btn = listEl.querySelector('.aot-ov-notes-all');
      if (btn) btn.addEventListener('click', onOpenAll);
    }
  }

  // Zone [현황] 탭 HTML 빌더 — 대표사진 + 구역 정보 + 노트 블록.
  //   zone: api_geo_zone_contents 응답의 zone 객체
  //         { unique_id, name, site_name, area_m2, counts, photo_url, can_edit }
  function buildZoneOverviewHtml(zone) {
    zone = zone || {};
    var html = '';
    var counts = zone.counts || {};

    // 대표사진 블록
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

    // 구역 정보
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

    // 노트 블록 (목록은 호출자가 /notes/target/<uuid>로 비동기 채움)
    html += _ovNotesBlock();

    return html;
  }

  window.AoTMapPopup = {
    positionDots:      positionDots,
    buildActuatorCat:  buildActuatorCat,
    buildActuatorTabs: buildActuatorTabs,
    buildSensorTabs:   buildSensorTabs,
    wire:              wire,
    buildInput:       buildInput,
    buildNoteSection: buildNoteSection,
    buildSectionNav:       buildSectionNav,
    buildOverviewSection:  buildOverviewSection,
    buildAboutSection:     buildAboutSection,
    fillOverviewNotes:     fillOverviewNotes,
    buildZoneOverviewHtml: buildZoneOverviewHtml
  };

})();
