/**
 * aot-bay-select.js
 *
 * `select_bay` 옵션 — 연결된 시설의 구역(bay) 목록을 그 자리에서 채운다.
 *
 * ## 왜 있나
 *
 * 통합환경제어의 `bay_scope` 는 자유 텍스트였다. 오타 하나가 "이 구역만
 * 제어한다" 를 무너뜨리는데 화면에는 아무 표시도 안 났다(2026-08-26).
 * 선택지를 주면 틀릴 자리가 없어진다.
 *
 * ## 두 가지를 지킨다
 *
 * 1. **저장된 값을 지우지 않는다.** 목록을 못 받아도(시설 미선택·통신 실패)
 *    템플릿이 넣어 둔 현재 값 옵션이 그대로 남는다. 빈 select 를 제출하면
 *    사용자가 손대지도 않은 구역 설정이 지워진다.
 * 2. **없는 구역도 보인다.** 저장된 값이 목록에 없으면(구역이 지워졌거나 시설을
 *    바꿨다) 그 항목을 지우지 않고 표시를 붙여 남긴다 — 조용히 사라지면
 *    사용자는 자기가 무엇을 골랐는지 알 수 없고, 서버는 그 값으로 "아무것도
 *    맡지 않음" 판정을 내린다.
 */
(function () {
  'use strict';

  var CACHE = {};          // facility uuid → Promise<[{id,name}]>

  function _t(s) { return window._ ? window._(s) : s; }

  function _bays(facilityUuid) {
    if (!facilityUuid) return Promise.resolve([]);
    if (!CACHE[facilityUuid]) {
      CACHE[facilityUuid] = fetch(
        '/api/aot/facility/' + encodeURIComponent(facilityUuid) + '/bays',
        { cache: 'no-store', credentials: 'same-origin' }
      ).then(function (r) { return r.ok ? r.json() : null; })
       .then(function (j) { return (j && j.ok && j.bays) ? j.bays : []; })
       .catch(function () { return []; });
    }
    return CACHE[facilityUuid];
  }

  function _fill(sel, bays) {
    // 현재 값은 **비우기 전에** 잡는다 — 아래에서 options 를 갈아엎는다.
    var cur = sel.getAttribute('data-bay-current') || sel.value || '';
    sel.innerHTML = '';

    var blank = document.createElement('option');
    blank.value = '';
    blank.textContent = _t('Entire facility');
    sel.appendChild(blank);

    var seen = false;
    bays.forEach(function (b) {
      if (!b || !b.id) return;
      var o = document.createElement('option');
      o.value = b.id;
      o.textContent = b.name || b.id;
      if (b.id === cur) { o.selected = true; seen = true; }
      sel.appendChild(o);
    });

    // ⚠ 목록에 없는 저장값은 **지우지 않고 표시해 남긴다.**
    if (cur && !seen) {
      var o2 = document.createElement('option');
      o2.value = cur;
      o2.textContent = cur + ' — ' + _t('not in this facility');
      o2.selected = true;
      sel.appendChild(o2);
    }
    if (!cur) blank.selected = true;
  }

  function _wire(sel) {
    if (sel._aotBayWired) return;
    sel._aotBayWired = true;

    var srcId = sel.getAttribute('data-bay-source');
    var src = srcId ? document.getElementById(srcId) : null;

    function refresh() {
      _bays(src ? src.value : '').then(function (bays) { _fill(sel, bays); });
    }
    if (src) {
      // 시설을 바꾸면 목록도 따라간다. 이때 **현재 값을 붙잡아 두지 않는다** —
      // 다른 시설의 구역 id 를 그대로 들고 있으면 "이 시설에 없음" 으로만
      // 보이는데, 사용자가 방금 시설을 바꾼 것이므로 그건 알려 줄 사실이다.
      src.addEventListener('change', refresh);
      if (window.jQuery) { window.jQuery(src).on('change', refresh); }
    }
    refresh();
  }

  function init(root) {
    (root || document).querySelectorAll('select.aot-bay-select').forEach(_wire);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); });
  } else {
    init();
  }
  // 설정 모달은 나중에 DOM 에 꽂히기도 한다(위젯 추가 등).
  window.AoTBaySelect = { init: init };
})();
