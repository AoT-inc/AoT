// sensor-label.js — Shared utilities for facility sensor labels & popup.
// Consumers: aot-facility-sensor-labels.js, AoT_map sensor labels.
//
// Public API: window.AoTSensorLabel = {
//   formatChannel(ch, decimals)      → "24.3°C"
//   formatLabel(channels, opts)      → "24.3°C / 65%" or "...+"
//   openPopup(sensor, opts)          → opens singleton detail popup (24h chart)
//   closePopup()
//   renderHistory(el, sensors, opts) → inline 24h sensor chart
//   renderOutputHistory(el, hist, name, opts) → inline output run-history chart
//   isMetaChannel(ch)                → rssi/snr/battery 인가 (값 표시 대상 아님)
//   linkBadgesHtml(status)           → 배터리·신호 배지 HTML ('' 이면 그릴 것 없음)
//   fillLinkBadges(scopeEl, status)  → scopeEl 안의 배지 슬롯을 채운다
//   fetchStatus(ids)                 → POST /api/geo/link_status
// }
//
// 차트는 renderHistory / renderOutputHistory **둘뿐**이다. 팝업마다 자체
// Highstock 호출을 두던 시절엔 같은 화면 안에서도 축·툴팁·레전드가 조금씩
// 다른 그래프가 나왔다. openPopup 도 자기 차트·자기 레전드를 그리지 않고
// renderHistory 를 그대로 호출한다 — 구역/시설 모달과 같은 그래프다.
(function () {
  'use strict';

  var _DEFAULT_DECIMALS = {
    T: 1, RH: 1, CO2: 0, VPD: 2, light: 0, wind_ms: 1, wind_deg: 0, P: 0
  };

  // channel.key → display name in the popup legend (uses the key as-is if no mapping)
  // Values are output in the current language via the window._ translation system.
  var _t = function (s) { return (window._ ? window._(s) : s); };
  var _KEY_DISPLAY = {
    T:        _t('Temperature'),
    RH:       _t('Humidity'),
    CO2:      'CO₂',
    VPD:      'VPD',
    light:    _t('Light'),
    wind_ms:  _t('Wind Speed'),
    wind_deg: _t('Wind Direction'),
    P:        _t('Pressure'),
    rssi:     'RSSI',
    snr:      'SNR',
    battery:  _t('Battery'),
  };

  // ── 메타 채널 ───────────────────────────────────────────────────────────────
  // 환경값이 아니라 장치 자신의 상태(전파세기·잡음비·배터리)를 말하는 채널.
  // 이제 배지 아이콘으로 그리므로 값 라벨·이력 그래프에서는 뺀다. 두 곳에 다
  // 나오면 같은 사실이 두 번 보이고, 특히 라벨은 "첫 값 있는 채널"을 쓰기 때문에
  // HB 채널이 0번인 노드는 지도에 온도 대신 배터리 전압이 찍혔다.
  // 키 목록은 서버(facility_sensors.META_CHANNEL_KEYS)와 같아야 한다.
  var _META_KEYS = { rssi: true, snr: true, battery: true };

  function isMetaChannel(ch) {
    return !!(ch && _META_KEYS[ch.key]);
  }

  function _fmtNumber(v, decimals) {
    if (v == null || isNaN(v)) return '—';
    var d = decimals != null ? decimals : 1;
    return (+v).toFixed(d);
  }

  // 표시용 단위. 저장값 'none' 은 "단위 없음"을 뜻하는 값이지 화면에 쓸 글자가
  // 아니다 — 그대로 붙이면 무차원 채널(토양 정전용량 등)이 "522.0none" 이 된다.
  // 값·라벨·레전드가 모두 여기를 거치게 해서 한 곳에서만 판단한다.
  function displayUnit(u) {
    var s = String(u == null ? '' : u).trim();
    return s.toLowerCase() === 'none' ? '' : s;
  }

  function formatChannel(ch, decimals) {
    if (!ch || ch.value == null) return '—';
    var d = decimals != null ? decimals : (_DEFAULT_DECIMALS[ch.key] != null ? _DEFAULT_DECIMALS[ch.key] : 1);
    return _fmtNumber(ch.value, d) + displayUnit(ch.unit);
  }

  function formatLabel(channels, opts) {
    opts = opts || {};
    var maxN = opts.maxChannels || 2;
    var dec  = opts.decimals;
    if (!Array.isArray(channels) || !channels.length) return '—';
    var renderable = channels.filter(function (c) {
      return c.value != null && !isMetaChannel(c);
    });
    if (!renderable.length) return '—';
    // 잘린 채널이 있어도 ' +' 를 붙이지 않는다. 라벨은 좁아서 그 한 글자가
    // 숫자를 밀어내는데, 정작 "뒤에 더 있다"는 사실만으로는 아무 판단도 할 수
    // 없다 — 더 보려면 어차피 눌러서 팝업을 연다.
    return renderable.slice(0, maxN).map(function (c) {
      return formatChannel(c, dec);
    }).join(' / ');
  }

  // ─── Popup (per-widget — appended to host element, not document.body) ──────
  // Each widget owns one popup instance keyed by its host element. Clicking
  // outside the popup closes it. The popup never escapes the host bounds.
  var _popups = new WeakMap();   // hostEl → popupEl
  var _activePopup = null;       // {popupEl, hostEl, outsideHandler}
  var _popupToken = 0;           // 열 때마다 증가 — 늦게 도착한 비동기 응답 폐기용

  function _ensurePopup(hostEl) {
    var popupEl = _popups.get(hostEl);
    if (popupEl) return popupEl;
    // Host must be a positioned ancestor so absolute children stay inside.
    var cs = window.getComputedStyle(hostEl);
    if (cs.position === 'static') hostEl.style.position = 'relative';
    popupEl = document.createElement('div');
    popupEl.className = 'aot-sensor-popup aot-sensor-popup-scoped';
    hostEl.appendChild(popupEl);
    _popups.set(hostEl, popupEl);
    return popupEl;
  }

  function closePopup() {
    if (_activePopup) {
      if (_activePopup.outsideHandler) {
        document.removeEventListener('mousedown', _activePopup.outsideHandler, true);
        document.removeEventListener('touchstart', _activePopup.outsideHandler, true);
      }
      if (_activePopup.modalOverlay) {
        // Modal: remove the entire screen-centered overlay
        try { _activePopup.modalOverlay.remove(); } catch (e) {}
        document.body.style.overflow = '';
      } else if (_activePopup.popupEl) {
        _activePopup.popupEl.style.display = 'none';
      }
      // 호출자 정리 훅 (지도 마커의 "앞으로 고정" 해제 등). null 로 만들기 전에
      // 지역 변수에 옮겨 둔다 — 훅 안에서 다시 openPopup 을 부를 수도 있다.
      var _onClose = _activePopup.onClose;
      _activePopup = null;
      if (typeof _onClose === 'function') { try { _onClose(); } catch (e) {} }
      return;
    }
    _activePopup = null;
  }

  // Create a screen-centered fixed modal overlay (same UX as the control label popup).
  // Returns: { overlay, box } — box is the .aot-sensor-popup body container.
  function _buildModalOverlay() {
    var overlay = document.createElement('div');
    overlay.className = 'aot-sensor-modal-overlay';
    var box = document.createElement('div');
    box.className = 'aot-sensor-popup aot-sensor-popup--modal';
    box.style.display = 'block';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    return { overlay: overlay, box: box };
  }

  function _positionPopup(popupEl, hostEl, anchorEvent) {
    if (!popupEl || !hostEl) return;
    var pad = 6;
    var hostRect = hostEl.getBoundingClientRect();
    var pw = popupEl.offsetWidth  || Math.min(420, hostRect.width  - 2*pad);
    var ph = popupEl.offsetHeight || Math.min(280, hostRect.height - 2*pad);
    var x, y;
    if (anchorEvent && typeof anchorEvent.clientX === 'number') {
      // Convert page-coords to host-local
      x = anchorEvent.clientX - hostRect.left + 8;
      y = anchorEvent.clientY - hostRect.top  + 8;
    } else {
      x = (hostRect.width  - pw) / 2;
      y = (hostRect.height - ph) / 2;
    }
    // Clamp inside host bounds
    x = Math.max(pad, Math.min(x, hostRect.width  - pw - pad));
    y = Math.max(pad, Math.min(y, hostRect.height - ph - pad));
    popupEl.style.left = x + 'px';
    popupEl.style.top  = y + 'px';
    // Cap dimensions to host
    popupEl.style.maxWidth  = Math.max(120, hostRect.width  - 2*pad) + 'px';
    popupEl.style.maxHeight = Math.max(120, hostRect.height - 2*pad) + 'px';
  }

  function _resolveHost(opts) {
    if (opts && opts.host instanceof Element) return opts.host;
    if (opts && typeof opts.host === 'string') {
      var el = document.getElementById(opts.host) || document.querySelector(opts.host);
      if (el) return el;
    }
    if (opts && opts.anchorEvent && opts.anchorEvent.target) {
      var t = opts.anchorEvent.target;
      // Walk up from the clicked label to find the widget container
      var host = t.closest && (
        t.closest('.aot-facility-container') ||
        t.closest('.aot-map-container') ||
        t.closest('.dashboard-widget') ||
        t.closest('[data-widget-host]')
      );
      if (host) return host;
    }
    return document.body;
  }

  function _escape(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }

  function _formatTs(iso) {
    if (!iso) return '—';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleString();
    } catch (e) { return iso; }
  }

  // ─── Shared detail body ────────────────────────────────────────────────────
  // 차트 하나뿐이다. 예전에는 여기서 값 레전드(색 점 + 이름 + 현재값)를 일반
  // 텍스트로 따로 그렸는데, 구역/시설 모달의 그래프는 Highstock 레전드가
  // "이름: 마지막값 단위"를 굵게 보여준다 — 같은 장치를 어디서 여느냐에 따라
  // 레전드 생김새가 달랐다. 이제 renderHistory 의 공용 레전드 하나만 쓴다.
  function _detailBodyHtml() {
    return '<div class="aot-sensor-popup-chart-wrap"></div>';
  }

  // Optional note footer — shared so the facility sensor popup and the map
  // input-device popup stay one component. note: { targetId, name, targetType }.
  // Reuses the existing shared popup button + note-preview classes (map.css):
  // .aot-popup-btn--primary (AoT brand primary) and .aot-popup-note-preview —
  // no bespoke styling, same as every other map popup's Create Note button.
  function _noteSectionHtml(note) {
    if (!note || !note.targetId) return '';
    return '<hr class="aot-popup-divider">' +
      '<button type="button" class="aot-popup-btn aot-popup-btn--primary aot-popup-btn--full">' +
        _escape(_t('Create Note')) + '</button>' +
      '<div class="aot-popup-note-preview">' +
        '<span style="color:#ccc;font-style:italic;">…</span></div>';
  }

  function _wireNoteSection(scopeEl, note) {
    if (!note || !note.targetId) return;
    var btn = scopeEl.querySelector('.aot-popup-btn--primary');
    if (btn) {
      btn.addEventListener('click', function () {
        window.dispatchEvent(new CustomEvent('open-notes', { detail: {
          targetId:   note.targetId,
          targetType: note.targetType || 'device',
          name:       note.name || ''
        } }));
      });
    }
    var prev = scopeEl.querySelector('.aot-popup-note-preview');
    if (prev) {
      fetch('/notes/target/' + encodeURIComponent(note.targetId))
        .then(function (r) { return r.json(); })
        .then(function (notes) {
          if (Array.isArray(notes) && notes.length) {
            prev.textContent = notes[0].note || '';
          } else {
            prev.innerHTML = '<span style="color:#ccc;font-style:italic;">' +
              _escape(_t('No Notes')) + '</span>';
          }
        })
        .catch(function () {});
    }
  }

  // ─── 배터리 / 통신품질 배지 ────────────────────────────────────────────────
  // 지도 위젯의 세 모달(입력 센서 / 출력·함수 팝업 / aot_device 라벨 팝업)이
  // **같은 한 함수**로 그린다. 팝업마다 자기 아이콘을 그리기 시작하면 이 파일
  // 머리말이 경고하는 "그래프 난립"이 배지에서 그대로 재현된다.
  //
  // 계약: 헤더에 <span class="aot-link-badges-slot"></span> 만 넣어두고,
  // 상태가 도착하면 fillLinkBadges(scopeEl, status) 를 부른다. 상태가 없거나
  // 근거 채널이 없으면 아무것도 그리지 않는다 — 빈 배터리 아이콘은 "정보 없음"이
  // 아니라 "0%"로 읽힌다.
  // 등급 문구는 switch 로 편다 — 배열 인덱싱(_t(TABLE[lv]))으로 쓰면 babel 의
  // JS 추출기가 리터럴을 못 봐서 번역 카탈로그에 영영 안 올라간다.
  function _levelText(lv) {
    switch (lv) {
      case 1:  return (window._ ? window._('Weak')   : 'Weak');
      case 2:  return (window._ ? window._('Medium') : 'Medium');
      case 3:  return (window._ ? window._('Strong') : 'Strong');
      default: return (window._ ? window._('No Response') : 'No Response');
    }
  }

  function _batteryBadge(bat) {
    if (!bat) return '';
    var pct    = (bat.percent == null) ? null : Math.round(bat.percent);
    var isBool = String(bat.unit || '').toLowerCase() === 'bool';
    // 채움 폭은 몸통 내부(2..28)에 대응. bool 은 가득/빈 둘 중 하나다.
    var ratio  = (pct == null) ? 0 : Math.max(0, Math.min(100, pct)) / 100;
    var w      = (26 * ratio).toFixed(1);
    var low    = (pct != null && pct <= 20);

    var title = (window._ ? window._('Battery') : 'Battery') + ': ' +
      (isBool ? (ratio ? (window._ ? window._('Normal') : 'Normal')
                       : (window._ ? window._('Low') : 'Low'))
              : (pct == null ? '—' : pct + '%'));
    if (bat.raw != null && bat.unit && !isBool) {
      title += ' (' + _fmtNumber(bat.raw, 2) + ' ' + bat.unit + ')';
    }
    if (bat.stale) title += ' · ' + (window._ ? window._('No Response') : 'No Response');

    // 숫자는 bool(가득/빈만 의미 있음)과 환산 불가(퍼센트로 말할 수 없음)에서
    // 찍지 않는다. 억지로 0/100 을 찍으면 화면이 조용히 거짓말을 한다.
    var num = (isBool || pct == null) ? '' :
      '<text x="15" y="12" text-anchor="middle" class="aot-link-badge-num">' +
      pct + '</text>';

    return '<span class="aot-link-badge aot-link-badge--battery' +
      (low ? ' is-low' : '') + (bat.stale ? ' is-stale' : '') +
      '" title="' + _escape(title) + '" aria-label="' + _escape(title) + '">' +
      '<svg viewBox="0 0 34 16" width="34" height="16" aria-hidden="true">' +
      '<rect x="0.7" y="1.7" width="28.6" height="12.6" rx="3" ry="3"' +
      ' fill="none" stroke="currentColor" stroke-width="1.4"/>' +
      '<rect x="30.5" y="5.5" width="3" height="5" rx="1" ry="1" fill="currentColor"/>' +
      (w > 0 ? '<rect x="2" y="3" width="' + w + '" height="10" rx="1.5" ry="1.5"' +
               ' fill="currentColor" opacity="0.28"/>' : '') +
      num + '</svg></span>';
  }

  function _signalBadge(link) {
    if (!link) return '';
    var lv = parseInt(link.level, 10);
    if (isNaN(lv)) lv = 0;

    var parts = [];
    if (link.rssi != null) parts.push('RSSI ' + _fmtNumber(link.rssi, 0) + ' dBm');
    if (link.snr  != null) parts.push('SNR ' + _fmtNumber(link.snr, 1) + ' dB');
    var title = (window._ ? window._('Signal') : 'Signal') + ': ' +
      _levelText(lv) + (parts.length ? ' — ' + parts.join(', ') : '');

    var bars = '';
    var geom = [[1, 10, 3.4, 5], [6.6, 6.5, 3.4, 8.5], [12.2, 3, 3.4, 12]];
    for (var i = 0; i < 3; i++) {
      var g = geom[i];
      bars += '<rect x="' + g[0] + '" y="' + g[1] + '" width="' + g[2] +
              '" height="' + g[3] + '" rx="1" ry="1" fill="currentColor"' +
              ' opacity="' + (i < lv ? '1' : '0.22') + '"/>';
    }
    return '<span class="aot-link-badge aot-link-badge--signal' +
      (lv ? '' : ' is-fault') + (link.stale ? ' is-stale' : '') +
      '" title="' + _escape(title) + '" aria-label="' + _escape(title) + '">' +
      '<svg viewBox="0 0 17 16" width="17" height="16" aria-hidden="true">' +
      bars + '</svg></span>';
  }

  function linkBadgesHtml(status) {
    if (!status) return '';
    var html = _signalBadge(status.link) + _batteryBadge(status.battery);
    return html ? '<span class="aot-link-badges">' + html + '</span>' : '';
  }

  function fillLinkBadges(scopeEl, status) {
    if (!scopeEl) return;
    var slot = scopeEl.querySelector
      ? scopeEl.querySelector('.aot-link-badges-slot') : null;
    if (!slot) return;
    slot.innerHTML = linkBadgesHtml(status);
  }

  // POST /api/geo/link_status — 배치. 모달은 1건만 보내지만 마커까지 확장해도
  // N+1 이 되지 않게 처음부터 배치 계약으로 둔다.
  function fetchStatus(ids) {
    var list = Array.isArray(ids) ? ids : [ids];
    list = list.filter(Boolean);
    if (!list.length) return Promise.resolve({});
    var meta = document.querySelector('meta[name="csrf-token"]');
    return fetch('/api/geo/link_status', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': (meta && meta.getAttribute('content')) || ''
      },
      body: JSON.stringify({ ids: list })
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { return (j && j.status) || {}; })
      .catch(function () { return {}; });
  }

  function openPopup(sensor, opts) {
    opts = opts || {};
    closePopup();  // ensure single active popup across widgets

    var modal = !!opts.modal;
    var hostEl = null, popupEl, modalOverlay = null;
    if (modal) {
      var m = _buildModalOverlay();
      modalOverlay = m.overlay;
      popupEl = m.box;
    } else {
      hostEl  = _resolveHost(opts);
      popupEl = _ensurePopup(hostEl);
      popupEl.style.display = 'block';
    }
    var _popupEl = popupEl;  // alias for the original code below

    // Layout order: title → chart(+공용 레전드) → 노트.
    // comm_fault (set by the caller from /inputstate — see
    // io_link_health_infra_plan.md) highlights the name label itself with the
    // shared danger tint — same treatment as the map popups
    // (window.AoTOutputState.paintNameWarning), and the same fact the 0-bar
    // signal badge in this very header shows, so the two must not disagree on
    // colour. Danger, not warning: the warning pair belongs to "unverified
    // running" and is user-configurable under that name — see paintNameWarning()
    // in aot-output-state.js. Inline style with !important, not a CSS class:
    // a class-based version of this exact highlight silently lost a
    // specificity/!important tie against this page's own name-label rules on
    // some pages — that comment has the full story.
    var titleStyle = sensor.comm_fault
      ? ' style="background-color:var(--aot-tint-danger-bg) !important;color:var(--aot-tint-danger-fg) !important;"'
      : '';
    var titleAttr = sensor.comm_fault ? ' title="' + _escape(_t('No Response')) + '"' : '';

    _popupEl.innerHTML =
      '<div class="aot-sensor-popup-header">' +
        '<span class="aot-sensor-popup-title"' + titleStyle + titleAttr + '>' + _escape(sensor.name || sensor.fitting_id) + '</span>' +
        '<span class="aot-link-badges-slot"></span>' +
        '<button class="aot-sensor-popup-close" type="button" aria-label="close">&#x2715;</button>' +
      '</div>' + _detailBodyHtml() + _noteSectionHtml(opts.note);

    _popupEl.querySelector('.aot-sensor-popup-close').addEventListener('click', closePopup);
    _wireNoteSection(_popupEl, opts.note);
    var _chartWrap = _popupEl.querySelector('.aot-sensor-popup-chart-wrap');

    // 배터리·통신 배지. 호출부가 이미 상태를 들고 있으면(지도 Input 마커는
    // /inputstate 와 함께 받는다) 그걸 쓰고, 없으면 device_id 로 직접 조회한다 —
    // 시설 fitting 센서 라벨처럼 호출부가 상태를 모르는 경로도 배선 없이 동작한다.
    // 비모달 팝업은 host 당 엘리먼트를 재사용하므로(_ensurePopup) 엘리먼트 동일성
    // 만으로는 "같은 팝업"을 판별할 수 없다 — 열 때마다 토큰을 새로 찍는다.
    var _token = ++_popupToken;
    _popupEl._aotPopupToken = _token;
    if (opts.status) {
      fillLinkBadges(_popupEl, opts.status);
    } else if (opts.status !== false && sensor.device_id) {
      (function (targetEl, devId, token) {
        fetchStatus(devId).then(function (all) {
          // 그 사이 팝업이 닫히거나 다른 장치로 바뀌었으면 버린다.
          if (targetEl._aotPopupToken !== token) return;
          fillLinkBadges(targetEl, all[devId]);
        });
      }(_popupEl, sensor.device_id, _token));
    }

    if (modal) {
      document.body.style.overflow = 'hidden';
      // Centered modal: close on backdrop click. No separate position calculation needed.
      modalOverlay.addEventListener('click', function (e) {
        if (e.target === modalOverlay) closePopup();
      });
      _activePopup = { popupEl: _popupEl, modalOverlay: modalOverlay, onClose: opts.onClose };
    } else {
      _positionPopup(_popupEl, hostEl, opts.anchorEvent);
      // outside-click / outside-touch closes the popup
      var outsideHandler = function (e) {
        if (!_popupEl.contains(e.target)) closePopup();
      };
      _activePopup = { popupEl: _popupEl, hostEl: hostEl, outsideHandler: outsideHandler, onClose: opts.onClose };
      setTimeout(function () {
        document.addEventListener('mousedown', outsideHandler, true);
        document.addEventListener('touchstart', outsideHandler, true);
      }, 0);
    }

    // 구역/시설 모달과 완전히 같은 호출 — 레전드도 그 그래프의 것을 그대로 쓴다.
    // 다만 이 모달은 센서 데이터 전용이라 그래프 영역을 1.5배로 잡는다:
    // 공용 레전드가 차트 높이 안에서 자리를 먹어 플롯이 너무 납작해진다.
    if (_chartWrap) {
      renderHistory(_chartWrap, [sensor], {
        decimals: opts.decimals,
        heightScale: opts.heightScale != null ? opts.heightScale : 1.5
      });
    }
  }

  // ─── Lazy-load Highstock (shared with AoT_graph widget) ────────────────────
  var _hcLoading = null;
  function _ensureHighcharts() {
    if (window.Highcharts && window.Highcharts.stockChart) return Promise.resolve(true);
    if (_hcLoading) return _hcLoading;
    _hcLoading = new Promise(function (resolve) {
      var s = document.createElement('script');
      s.src = '/static/js/vendor/user_js/highstock-9.1.2.js';
      s.async = true;
      s.onload = function () { resolve(true); };
      s.onerror = function () { resolve(false); };
      document.head.appendChild(s);
    });
    return _hcLoading;
  }

  var _PALETTE_LIGHT = ['#FEA60B','#8BC1C1','#93B261','#F4D624','#DF5353','#008DDE','#7cb5ec','#434348','#90ed7d','#f7a35c','#8085e9','#f15c80','#e4d354','#2b908f','#f45b5b','#91e8e1'];
  var _PALETTE_DARK  = ['#FEA60B','#8BC1C1','#93B261','#F4D624','#DF5353','#008DDE','#2b908f','#90ee7e','#f45b5b','#7798BF','#aaeeee','#ff0066','#eeaaee','#55BF3B','#DF5353','#7798BF','#aaeeee'];

  function _chartColors() {
    var isDark = document.documentElement.classList.contains('dark') ||
                 document.body.classList.contains('dark') ||
                 (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    return isDark ? _PALETTE_DARK : _PALETTE_LIGHT;
  }

  // ─── Inline multi-sensor history chart ──────────────────────────────────────
  // Renders a 24h history chart for SEVERAL sensors into containerEl (no popup,
  // no per-sensor click). Series = sensor × channel; one hidden y-axis per
  // measurement key so same-kind series share a scale. Used by the AoT_map bay
  // modal; reusable by any widget that has runtime fitting_sensors[] entries.
  //
  //   containerEl : target element (content replaced)
  //   sensors     : runtime fitting_sensors[] entries ({device_id, name, channels[]})
  //   opts        : { hours = 24, height = width*0.62 (180..320 clamp),
  //                   heightScale = 1 (그 기본 높이의 배수) }
  //
  // heightScale: 레전드는 차트 높이 **안에서** 자리를 먹으므로, 채널이 많은
  // 센서일수록 플롯 영역이 눌린다. 센서 전용 모달처럼 그래프가 주인공인
  // 호스트는 이 배수로 플롯 영역을 넓힌다. (구역/시설 모달은 액추에이터 목록과
  // 공간을 나눠 써야 하므로 기본값 1 을 유지한다.)
  function renderHistory(containerEl, sensors, opts) {
    opts = opts || {};
    containerEl.innerHTML =
      '<div class="aot-spop-inline-chart" style="width:100%;"></div>' +
      '<div class="aot-sensor-popup-chart-status">loading…</div>';
    var chartEl  = containerEl.querySelector('.aot-spop-inline-chart');
    var statusEl = containerEl.querySelector('.aot-sensor-popup-chart-status');

    var jobs = [];
    var nameSet = {};
    (sensors || []).forEach(function (s) {
      if (!s || !s.device_id) return;
      nameSet[s.name || s.fitting_id || ''] = true;
      (s.channels || []).forEach(function (ch) {
        // 메타 채널(rssi/snr/battery)은 배지로 그린다 — 시리즈에서 뺀다.
        // 여기 하나만 막으면 입력 모달·구역 모달·시설 모달·bay 모달이 전부
        // 걸린다(차트가 이 함수 하나뿐이다).
        if (ch && ch.measurement_id && !isMetaChannel(ch)) jobs.push({ sensor: s, ch: ch });
      });
    });
    if (!jobs.length) {
      // 메타 채널만 가진 장치(하트비트 전용 노드 등)가 여기로 온다. 빈 차트 박스를
      // 남기면 "로딩이 안 끝났나" 로 보이므로 통째로 치운다 — 배지만 남는다.
      chartEl.remove();
      statusEl.textContent = _t('No Measurements');
      return;
    }
    var multiSensor = Object.keys(nameSet).length > 1;
    var past = Math.round((opts.hours || 24) * 3600);
    var _rNowMs = Date.now();
    var _rMinMs = _rNowMs - past * 1000;

    var requests = jobs.map(function (j) {
      var url = '/past/' + encodeURIComponent(j.sensor.device_id) +
                '/input/' + encodeURIComponent(j.ch.measurement_id) +
                '/' + past;
      return fetch(url).then(function (r) { return r.ok ? r.json() : null; })
                       .catch(function () { return null; });
    });

    Promise.all(requests).then(function (responses) {
      var axisIndex = {}, axisCount = 0;
      var series = [];
      responses.forEach(function (rows, i) {
        if (!rows || !Array.isArray(rows) || !rows.length) return;
        var j = jobs[i];
        var data = rows.map(function (row) {
          if (row[1] == null) return null;
          var t = (typeof row[0] === 'number') ? row[0] * 1000 : new Date(row[0]).getTime();
          return [t, +row[1]];
        }).filter(function (p) { return p != null && !isNaN(p[0]) && !isNaN(p[1]); })
          .sort(function (a, b) { return a[0] - b[0]; });
        if (!data.length) return;
        var key = j.ch.key || j.ch.measurement_type || '?';
        if (axisIndex[key] == null) axisIndex[key] = axisCount++;
        var disp = _KEY_DISPLAY[key] || key;
        series.push({
          name: (multiSensor ? (j.sensor.name || '') + ' ' : '') + disp,
          data: data,
          yAxis: axisIndex[key],
          // 레전드 자리수는 측정 종류를 따른다 — 전부 소수 2자리로 고정하면
          // 기압이 "1 008.00 Pa", CO2 가 "412.00 ppm" 처럼 읽힌다.
          custom: { aotDecimals: (opts.decimals != null ? opts.decimals
                     : (_DEFAULT_DECIMALS[key] != null ? _DEFAULT_DECIMALS[key] : 1)) },
          // 단위 없는 채널(예: 풍향)에 ' ' 만 붙어 "302 " 처럼 끝나지 않게.
          // displayUnit 을 거치는 이유는 저장 단위가 'none' 인 채널 때문이다 —
          // 그대로 쓰면 레전드가 "토양 정전용량: 522.0 none" 이 된다.
          tooltip: { valueSuffix: displayUnit(j.ch.unit) ? (' ' + displayUnit(j.ch.unit)) : '' }
        });
      });

      if (!series.length) {
        statusEl.textContent = _t('No data');
        return;
      }

      _ensureHighcharts().then(function (ok) {
        if (!ok || !window.Highcharts) {
          statusEl.textContent = 'Highcharts load failed';
          return;
        }
        if (window.AoTChart && window.AoTChart.applyGlobalDefaults) {
          window.AoTChart.applyGlobalDefaults();
        }
        requestAnimationFrame(function () {
          var w = chartEl.offsetWidth || 300;
          var h = opts.height ||
                  Math.round(Math.max(180, Math.min(320, Math.round(w * 0.62))) *
                             (opts.heightScale || 1));
          var yAxes = [];
          for (var a = 0; a < axisCount; a++) {
            yAxes.push({ title: { text: null }, labels: { enabled: false },
                         opposite: a % 2 === 1 });
          }
          try {
            // 차트 인스턴스를 컨테이너에 노출 — 맵 팝업의 액추에이터
            // 오버레이(시리즈 추가)가 접근한다. 기존 동작 불변.
            containerEl._aotChart = window.Highcharts.stockChart(chartEl, {
              colors: _chartColors(),
              chart: { height: h, spacing: [4, 4, 4, 4] },
              rangeSelector: { enabled: false },
              navigator: { enabled: false },
              scrollbar: { enabled: false },
              credits: { enabled: false },
              exporting: { enabled: false },
              navigation: { buttonOptions: { enabled: false } },
              // 레전드: AoT_graph 위젯 기본 구성 — 시리즈명 + 마지막 값(굵게)+단위
              legend: {
                enabled: true,
                useHTML: true,
                labelFormatter: function () {
                  var lastVal = this.yData && this.yData.length
                    ? this.yData[this.yData.length - 1] : null;
                  var unit = (this.tooltipOptions && this.tooltipOptions.valueSuffix) || '';
                  if (lastVal == null) return this.name;
                  var dec = (this.options.custom && this.options.custom.aotDecimals != null)
                    ? this.options.custom.aotDecimals : 2;
                  return this.name + ': <b>' +
                    window.Highcharts.numberFormat(lastVal, dec) + unit + '</b>';
                },
                itemStyle: { fontSize: '1em' },   // AoT_graph 기본값(1.0em)과 동일
                margin: 4, padding: 2
              },
              xAxis: { type: 'datetime', min: _rMinMs, max: _rNowMs, labels: { style: { fontSize: '9px' } } },
              yAxis: yAxes,
              tooltip: { shared: true, valueDecimals: 2 },
              series: series
            });
            statusEl.style.display = 'none';
          } catch (e) {
            statusEl.textContent = 'chart error: ' + e.message;
          }
        });
      });
    });
  }

  // ─── Output(장치) 작동 이력 차트 ─────────────────────────────────────────────
  // 센서 차트와 같은 모듈에 두는 이유: 팝업마다 자기 Highstock 옵션을 들고 있으면
  // 축·툴팁·색이 조금씩 어긋난 그래프가 늘어난다. 구역 모달의 독립 차트, 시설
  // 모달, 장치 마커 팝업이 모두 이 함수 하나를 쓴다.
  //
  //   containerEl : 대상 엘리먼트 (내용 교체)
  //   hist        : /api/geo/output/<uuid>/history 응답 {series_type, points[[sec,v]]}
  //   name        : 시리즈 이름 (장치명)
  //   opts        : { height }
  function renderOutputHistory(containerEl, hist, name, opts) {
    opts = opts || {};
    var isOnOff = hist && hist.series_type === 'onoff';
    var pts = ((hist && hist.points) || []).map(function (p) {
      return [p[0] * 1000, p[1]];
    }).sort(function (a, b) { return a[0] - b[0]; });

    if (!pts.length) {
      containerEl.innerHTML = '<span class="aot-ov-muted" style="padding:8px;display:block">' +
                              _escape(_t('No data')) + '</span>';
      return;
    }

    _ensureHighcharts().then(function (ok) {
      if (!ok || !window.Highcharts) {
        containerEl.innerHTML = '<span class="aot-ov-muted" style="padding:8px;display:block">' +
                                'Highcharts load failed</span>';
        return;
      }
      if (window.AoTChart && window.AoTChart.applyGlobalDefaults) {
        window.AoTChart.applyGlobalDefaults();
      }
      requestAnimationFrame(function () {
        var w = containerEl.offsetWidth || 280;
        var h = opts.height || Math.max(120, Math.min(200, Math.round(w * 0.46)));
        try {
          containerEl._aotChart = window.Highcharts.stockChart(containerEl, {
            chart: { height: h, spacing: [4, 4, 4, 4] },
            rangeSelector: { enabled: false },
            navigator: { enabled: false },
            scrollbar: { enabled: false },
            credits: { enabled: false },
            exporting: { enabled: false },
            legend: { enabled: false },
            xAxis: { type: 'datetime', labels: { style: { fontSize: '9px' } } },
            yAxis: {
              min: 0, title: { text: null },
              labels: {
                enabled: true,
                style: { fontSize: '9px' },
                formatter: isOnOff
                  ? function () { return this.value + 'm'; }
                  : function () { return this.value + '%'; }
              },
              gridLineWidth: 1
            },
            tooltip: { valueDecimals: 1,
                       valueSuffix: isOnOff ? (' ' + _t('min')) : ' %' },
            series: [{
              name: name,
              type: isOnOff ? 'column' : 'line',
              step: isOnOff ? undefined : 'left',
              data: pts,
              maxPointWidth: isOnOff ? 3 : undefined,
              borderWidth: isOnOff ? 0 : undefined,
              color: '#4a90d9'
            }]
          });
        } catch (e) {}
      });
    });
  }

  window.AoTSensorLabel = {
    formatChannel: formatChannel,
    formatLabel:   formatLabel,
    openPopup:     openPopup,
    closePopup:    closePopup,
    renderHistory: renderHistory,
    renderOutputHistory: renderOutputHistory,
    isMetaChannel:    isMetaChannel,
    displayUnit:      displayUnit,
    linkBadgesHtml: linkBadgesHtml,
    fillLinkBadges: fillLinkBadges,
    fetchStatus:      fetchStatus,
    keyDisplay:    function (key) { return _KEY_DISPLAY[key] || key || ''; },
    defaultDecimals: function (key) {
      return _DEFAULT_DECIMALS[key] != null ? _DEFAULT_DECIMALS[key] : 1;
    }
  };
})();
