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
// 노트 진입점은 이 파일이 함께 내보내는 window.AoTNotesBlock 하나다
// (html/fill/wire). 지도 팝업·모달과 시설 센서 팝업이 같은 블록을 쓴다 —
// 자세한 배경은 그 선언부 주석 참조.
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

  // ─── 노트 블록 (window.AoTNotesBlock) ──────────────────────────────────────
  //
  // **노트로 들어가는 문은 앱 전체에 이 한 벌뿐이다.** 예전에는 부르는 자리마다
  // 자기 버튼을 그렸다: 시설·구역·장치 모달은 32px 테두리 알약("노트 작성하기")에
  // 목록 밑에 26px 전체폭 버튼("View All", 번역 없음)이 하나 더 붙었고, 라벨
  // 팝업과 센서 팝업은 전체폭 딥그린 슬래브("메모 열기"/"노트 작성하기")였다.
  // 같은 창 안에서도 바로 위 [편집] 버튼(.aot-ov-pill)과 높이·모양이 달랐고,
  // 필지 모달은 노트 목록만 있고 문이 아예 없었다.
  //
  // 그래서 골격·문구·배선을 여기 하나로 모은다. 스타일은 새로 만들지 않고
  // 같은 모달의 [사진 변경]·[편집]·[저장]과 **같은 .aot-ov-pill** 을 쓴다.
  // 목록 항목을 눌러도 같은 곳이 열리므로 목록 아래 버튼은 없앴다 — 같은 동작을
  // 하는 문이 한 블록에 둘일 이유가 없다.
  //
  // 이 파일에 두는 이유: 지도 위젯(aot-map-popup 경유)과 시설 위젯(센서 팝업)이
  // 함께 싣는 유일한 공용 모듈이라서다. 한쪽에만 두면 다시 두 벌이 된다.
  var NOTES_MAX       = 2;    // 미리보기 개수
  var NOTE_TEXT_MAX   = 60;   // 본문 미리보기 글자 수
  var NOTE_THUMBS_MAX = 4;    // 첨부 썸네일 개수

  function notesBlockHtml() {
    return '<div class="aot-ov-block aot-ov-notes">' +
             '<div class="aot-ov-sec-title aot-ov-sec-title--row">' +
               '<span>' + _escape(_t('Notes')) + '</span>' +
               '<button type="button" class="aot-ov-pill aot-ov-notes-open">' +
               _escape(_t('Open Notes')) + '</button>' +
             '</div>' +
             '<div class="aot-ov-notes-list"><span class="aot-ov-muted">…</span></div>' +
           '</div>';
  }

  // 미리보기 목록을 그린다. notes 는 /notes/target/<uuid> 응답(최신순).
  function fillNotesList(listEl, notes) {
    if (!listEl) return;
    if (!Array.isArray(notes) || !notes.length) {
      listEl.innerHTML = '<span class="aot-ov-muted">' +
                         _escape(_t('No notes written')) + '</span>';
      return;
    }
    var html = '';
    notes.slice(0, NOTES_MAX).forEach(function (n) {
      // 날짜는 **장치 현지 시각**으로 읽는다. 브라우저 시각대로 찍으면, 다른
      // 지역 농장을 원격으로 보는 사람에게 자정 언저리 노트의 날짜가 하루씩
      // 어긋난다. /notes/target 이 그 노트가 속한 곳의 tz(date_tz)를 함께 준다.
      var d = '';
      try {
        var dt = new Date(n.date_time);
        if (!isNaN(dt)) {
          if (n.date_tz && window.AoTTz && window.AoTTz.formatDevice) {
            // opts.fmt 가 Intl 옵션 자리다 — 옵션을 바로 넘기면 무시되고
            // 기본 datetimeShort 가 나온다.
            d = window.AoTTz.formatDevice(n.date_time, n.date_tz,
                  { fmt: { month: 'numeric', day: 'numeric' } });
          }
          if (!d) d = (dt.getMonth() + 1) + '/' + dt.getDate();
        }
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
                 return '<img src="/note_attachment/' + _escape(f) + '" alt="" loading="lazy">';
               }).join('') +
               (imgs.length > NOTE_THUMBS_MAX
                 ? '<span class="aot-ov-muted">+' + (imgs.length - NOTE_THUMBS_MAX) +
                   '</span>' : '') +
               '</div>';
      }
      if (otherCnt > 0) {
        att += '<div class="aot-ov-note-files">' + _escape(_t('Attachments')) +
               ' ' + otherCnt + '</div>';
      }

      html += '<div class="aot-ov-note">' +
              '<div class="aot-ov-note-row">' +
              '<span class="aot-ov-note-date">' + _escape(d) + '</span>' +
              '<span class="aot-ov-note-text">' + (_escape(txt) ||
                ('<span class="aot-ov-muted">' + _escape(_t('Attachments')) + '</span>')) + '</span>' +
              '</div>' + att + '</div>';
    });
    listEl.innerHTML = html;
  }

  // 블록을 배선한다 — 버튼·목록 항목 클릭 → 노트 패널, 그리고 미리보기 로드.
  //   target : { targetId, targetType, name }
  //   opts.beforeOpen : 패널을 열기 전에 부를 것(팝업/모달 닫기 등).
  //                     노트 패널은 z-index 최상위라 모달 위에 뜨지 않는다.
  //   opts.cache      : { html: '<이전 렌더>' } — 주기 갱신하는 창(시설 모달은
  //                     30초)에서 깜빡임을 막는다. 이전 내용을 먼저 그려 두고
  //                     새 응답이 **실제로 달라졌을 때만** 교체한다.
  function wireNotesBlock(scopeEl, target, opts) {
    if (!scopeEl || !target || !target.targetId) return;
    opts = opts || {};

    function open() {
      if (typeof opts.beforeOpen === 'function') {
        try { opts.beforeOpen(); } catch (e) {}
      }
      window.dispatchEvent(new CustomEvent('open-notes', { detail: {
        targetId:   target.targetId,
        targetType: target.targetType || 'device',
        name:       target.name || ''
      } }));
    }

    var btn = scopeEl.querySelector('.aot-ov-notes-open');
    if (btn) btn.addEventListener('click', open);

    var listEl = scopeEl.querySelector('.aot-ov-notes-list');
    if (!listEl) return;
    // 목록은 컨테이너 하나에만 리스너를 단다. 항목마다 달면 갱신할 때마다 다시
    // 달아야 하고, 한 경로에서 빠뜨리면 그 창에서만 항목 클릭이 조용히 죽는다.
    listEl.addEventListener('click', function (e) {
      if (e.target && e.target.closest && e.target.closest('.aot-ov-note')) open();
    });

    var cache = opts.cache;
    if (cache && cache.html) listEl.innerHTML = cache.html;

    fetch('/notes/target/' + encodeURIComponent(target.targetId))
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (notes) {
        if (!listEl.isConnected) return;
        var tmp = document.createElement('div');
        fillNotesList(tmp, notes);
        if (cache) {
          if (tmp.innerHTML === cache.html) return;
          cache.html = tmp.innerHTML;
        }
        listEl.innerHTML = tmp.innerHTML;
      })
      .catch(function () {});
  }

  window.AoTNotesBlock = {
    html: notesBlockHtml,
    fill: fillNotesList,
    wire: wireNotesBlock
  };

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
      '</div>' + _detailBodyHtml() +
      ((opts.note && opts.note.targetId) ? notesBlockHtml() : '');

    _popupEl.querySelector('.aot-sensor-popup-close').addEventListener('click', closePopup);
    if (opts.note && opts.note.targetId) {
      wireNotesBlock(_popupEl, opts.note);
    }
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
      s.src = '/static/js/vendor/user_js/highstock-9.1.2.js?v=' + (window.AOT_ASSET_V || '');
      s.async = true;
      s.onload = function () { resolve(true); };
      s.onerror = function () { resolve(false); };
      document.head.appendChild(s);
    });
    return _hcLoading;
  }

  var _PALETTE_LIGHT = ['#FEA60B','#8BC1C1','#93B261','#F4D624','#DF5353','#008DDE','#7cb5ec','#434348','#90ed7d','#f7a35c','#8085e9','#f15c80','#e4d354','#2b908f','#f45b5b','#91e8e1'];
  var _PALETTE_DARK  = ['#FEA60B','#8BC1C1','#93B261','#F4D624','#DF5353','#008DDE','#2b908f','#90ee7e','#f45b5b','#7798BF','#aaeeee','#ff0066','#eeaaee','#55BF3B','#DF5353','#7798BF','#aaeeee'];

  // ─── 플롯 높이 고정 ────────────────────────────────────────────────────────
  // 그래프 영역(플롯)의 높이는 시리즈 수·모달 폭과 무관하게 늘 같아야 한다.
  // 값을 눈으로 비교하는 화면이라 세로 축척이 열 때마다 달라지면 못 읽는다.
  var PLOT_H = 190;              // 센서 이력 차트 플롯 높이(px)
  var PLOT_H_OUTPUT = 130;       // 장치 작동 이력 차트 플롯 높이(px)
  var PLOT_CHROME_GUESS = 60;    // 첫 페인트용 어림값(레전드+x축 라벨)

  function _lockPlot(chart, plotH) {
    if (window.AoTChart && window.AoTChart.lockPlotHeight) {
      window.AoTChart.lockPlotHeight(chart, plotH);
    }
  }

  // Highstock 분할 툴팁의 시각 머리글은 기본이 x축 **아래**라 레전드·아래 컨텐츠를
  // 가린다. 플롯 위쪽으로 올린다 (자세한 배경은 aot-chart-core 쪽 주석).
  function _headerTop(chart) {
    if (window.AoTChart && window.AoTChart.splitTooltipHeaderTop) {
      window.AoTChart.splitTooltipHeaderTop(chart);
    }
  }

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
  //   opts        : { hours = 24, plotHeight = PLOT_H, heightScale = 1 }
  //
  // **플롯 높이는 고정이다.** 예전에는 전체 높이를 폭에서 뽑고(width*0.62,
  // 180~320 클램프) 그 안에서 레전드가 자리를 먹어, 같은 화면인데도 그래프가
  // 108px~230px 로 두 배 넘게 오락가락했다 — 채널이 많은 센서일수록, 그리고
  // 모달이 좁을수록 작아졌다. 이제 플롯 높이를 목표로 잡고 레전드가 커지면
  // 카드가 그만큼 길어진다(AoTChart.lockPlotHeight).
  //
  // heightScale: 그래프가 주인공인 호스트(센서 전용 모달)가 플롯을 키우는 배수.
  // 구역/시설 모달은 액추에이터 목록과 공간을 나눠 쓰므로 기본값 1 을 유지한다.
  // 차트 없이 문구만 남는 상태 — absolute 를 풀고 **자기 자리를 차지하게** 한다.
  //
  // `.aot-sensor-popup-chart-status` 가 absolute 인 것은 로딩 중 차트 **위에**
  // 얹히기 위해서다. 그릴 차트가 아예 없으면 그 전제가 사라지는데, 그대로 두면
  // 부모 높이가 0이 되어 문구가 아래 내용 위로 겹친다. 컨테이너마다 CSS 로
  // 막으면(예전에 chart-wrap 하나에만 :has() 로 막았다) 새 컨테이너가 생길
  // 때마다 같은 겹침이 재발한다 — 문구 자신이 알고 있게 한다.
  function _standaloneStatus(statusEl, text) {
    if (!statusEl) return;
    statusEl.classList.add('is-standalone');
    statusEl.textContent = text;
  }

  // ── 채널별 이력을 **한 번의 왕복**으로 ────────────────────────────────────
  //
  // 예전에는 채널마다 `/past/<dev>/input/<meas>/<sec>` 를 낱개로 쳤다. 온습도
  // 노드 하나가 6채널이면 차트 한 개에 요청 6건이고, 브라우저의 오리진당 ~6
  // 연결 상한에 그대로 걸린다 — 폰에서는 그만큼 라디오를 깨운다.
  //
  // `/data_batch` 는 이미 `kind:'past'` 를 받고 응답 모양(`[[ts,value],…]`)도
  // 같다. 대시보드 위젯들은 jQuery transport(`aot-data-batch.js`)가 자동으로
  // 묶어 주는데, 이 함수는 `fetch` 를 쓰므로 그 경로를 타지 못한다 — 그래서
  // 직접 부른다.
  //
  // **배치가 실패해도 차트가 비면 안 된다.** 실패하면 예전 낱개 경로로
  // 되돌아간다(`aot-data-batch.js` 의 directFallback 과 같은 태도).
  // 한 요청에 담는 채널 수의 상한.
  //
  // 서버(`data_batch`)가 past 항목을 **동시에** 처리하므로(_run_past_jobs,
  // 워커 8) 묶는다고 직렬로 길어지지 않는다. 그래서 서버 워커 수에 맞춘다 —
  // 한 요청이 곧 한 번의 동시 실행 파도가 된다.
  //
  // 실측(로컬, 6채널 · 각 7회 중앙값): 배치 1연결 **172ms** vs 낱개 6연결
  // 199ms. 서버를 병렬화하기 전에는 반대였다(197 vs 155) — 그때는 한 응답이
  // 6배로 직렬화됐다.
  var _PAST_BATCH_MAX = 8;

  function _pastUrl(j, past) {
    return '/past/' + encodeURIComponent(j.sensor.device_id) +
           '/input/' + encodeURIComponent(j.ch.measurement_id) + '/' + past;
  }

  function _fetchPastOneByOne(jobs, past) {
    return Promise.all(jobs.map(function (j) {
      return fetch(_pastUrl(j, past), { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; });
    }));
  }

  function _fetchPastSeries(jobs, past) {
    if (!jobs.length) return Promise.resolve([]);
    if (jobs.length === 1) return _fetchPastOneByOne(jobs, past);

    var chunks = [];
    for (var i = 0; i < jobs.length; i += _PAST_BATCH_MAX) {
      chunks.push(jobs.slice(i, i + _PAST_BATCH_MAX));
    }
    var csrfEl = document.querySelector('meta[name="csrf-token"]');
    var csrf = csrfEl ? csrfEl.getAttribute('content') : '';

    return Promise.all(chunks.map(function (chunk) {
      return fetch('/data_batch', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({
          items: chunk.map(function (j) {
            return { kind: 'past', unique_id: j.sensor.device_id,
                     measure_type: 'input',
                     measurement_id: j.ch.measurement_id, period: String(past) };
          })
        })
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          // 길이가 안 맞으면 정렬이 깨진 것이다 — 그 조각만 낱개로 다시 받는다.
          // 잘못 정렬된 시리즈를 그리면 온도 자리에 습도가 들어간다.
          var res = d && d.results;
          if (!Array.isArray(res) || res.length !== chunk.length) {
            return _fetchPastOneByOne(chunk, past);
          }
          return res;
        })
        .catch(function () { return _fetchPastOneByOne(chunk, past); });
    })).then(function (parts) {
      return parts.reduce(function (a, b) { return a.concat(b); }, []);
    });
  }

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
      _standaloneStatus(statusEl, _t('No Measurements'));
      return;
    }
    var multiSensor = Object.keys(nameSet).length > 1;
    var past = Math.round((opts.hours || 24) * 3600);
    var _rNowMs = Date.now();
    var _rMinMs = _rNowMs - past * 1000;

    _fetchPastSeries(jobs, past).then(function (responses) {
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
        // 빈 차트 박스를 남기면 안 된다 — 상태 문구가 absolute 라 그 박스는
        // 높이를 못 갖고, 문구는 바깥 조상 기준으로 퍼져 **아래 장치 목록 위에
        // 겹쳐 앉는다**(실측 118px). 위 `!jobs.length` 와 같은 처리를 한다.
        chartEl.remove();
        _standaloneStatus(statusEl, _t('No data'));
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
          var plotH = Math.round((opts.plotHeight || PLOT_H) * (opts.heightScale || 1));
          // 첫 페인트용 어림값. render 에서 실측해 정확히 맞춘다.
          var h = plotH + PLOT_CHROME_GUESS;
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
              chart: {
                height: h,
                spacing: [4, 4, 4, 4],
                events: {
                  render: function () { _lockPlot(this, plotH); }
                }
              },
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
                  // chart-core 가 없는 상황에서도 범례가 죽으면 안 된다 —
                  // labelFormatter 가 던지면 차트 전체가 안 그려진다.
                  var shown = (window.AoTChart && window.AoTChart.formatSeriesValue)
                    ? window.AoTChart.formatSeriesValue(lastVal, unit, dec)
                    : window.Highcharts.numberFormat(lastVal, dec) + unit;
                  return this.name + ': <b>' + shown + '</b>';
                },
                itemStyle: { fontSize: '1em' },   // AoT_graph 기본값(1.0em)과 동일
                margin: 4, padding: 2
              },
              xAxis: { type: 'datetime', min: _rMinMs, max: _rNowMs, labels: { style: { fontSize: '9px' } } },
              yAxis: yAxes,
              tooltip: { shared: true, valueDecimals: 2 },
              series: series
            });
            // 시각 머리글을 x축 아래에서 플롯 위쪽으로 (레전드를 가리지 않게)
            _headerTop(containerEl._aotChart);
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
  //   opts        : { plotHeight = PLOT_H_OUTPUT }  — 플롯 높이는 폭과 무관하게 고정
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
        var plotH = opts.plotHeight || PLOT_H_OUTPUT;
        var h = plotH + PLOT_CHROME_GUESS;
        try {
          containerEl._aotChart = window.Highcharts.stockChart(containerEl, {
            chart: {
              height: h,
              spacing: [4, 4, 4, 4],
              events: {
                render: function () { _lockPlot(this, plotH); }
              }
            },
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
          _headerTop(containerEl._aotChart);
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
