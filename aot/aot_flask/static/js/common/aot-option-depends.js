/**
 * aot-option-depends.js
 *
 * `depends_on` 이 걸린 옵션 행을, 그 대상 옵션이 켜졌을 때만 보인다.
 * 설계: `docs/design/env-coordinator-settings-redesign.md` §3-2 (단계 B).
 *
 * ## 왜 있나
 *
 * 야간 파킹을 쓰지 않는 사람에게도 기준·오프셋·시작·종료 4개가 늘 보였다.
 * 켜지도 않은 기능의 하위 설정이 화면을 채우면, 사용자는 **자기가 안 쓰는
 * 것까지 정해야 하는 줄 안다.**
 *
 * ## ⚠ 값은 계속 제출된다
 *
 * 행을 감출 뿐 input 을 지우거나 disable 하지 않는다. 지우면 토글을 껐다 켤
 * 때 그 설정이 사라지는데 **에러가 안 난다** — 이 레포가 여러 번 데인 모양이다
 * (`display:none` 안의 hidden input 도 제출된다는 사실이 여기서는 이점이다).
 */
(function () {
  'use strict';

  function isOn(el) {
    if (!el) return false;
    if (el.type === 'checkbox' || el.type === 'radio') return !!el.checked;
    var v = String(el.value == null ? '' : el.value).trim();
    return v !== '' && v !== '0' && v !== 'false';
  }

  function apply(row, source) {
    // ⚠ `hidden` 속성이 아니라 클래스 — 부트스트랩 그리드가 `display` 를
    //    다시 정하는 자리가 있어 인라인 스타일이 안전하다.
    row.style.display = isOn(source) ? '' : 'none';
  }

  function wire(row) {
    if (row._aotDependsWired) return;
    var id = row.getAttribute('data-depends-on');
    var source = id ? document.getElementById(id) : null;
    if (!source) return;          // 대상이 이 화면에 없으면 **감추지 않는다**
    row._aotDependsWired = true;
    var run = function () { apply(row, source); };
    source.addEventListener('change', run);
    source.addEventListener('input', run);
    if (window.jQuery) { window.jQuery(source).on('change', run); }
    run();
  }

  function init(root) {
    (root || document).querySelectorAll('[data-depends-on]').forEach(wire);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); });
  } else {
    init();
  }
  window.AoTOptionDepends = {init: init};
})();
