/**
 * aot-modal-enhance.js — AJAX 로 갈아 끼운 옵션 영역을 **다시 꾸민다**.
 *
 * 서버가 내는 것은 껍데기다. `.aot-scale-input` · `.aot-range-band` ·
 * `.aot-env-status` 는 빈 컨테이너로 나가고, 그 안의 `.aot-viz`(눈금·핸들·
 * 밴드·현재값)는 **클라이언트가 만든다**. 그 초기화는 각 모듈이
 * `DOMContentLoaded` 에 한 번 붙는 것이 전부라, 나중에 AJAX 로 꽂은 HTML 은
 * 아무도 꾸며 주지 않는다.
 *
 * 증상: **저장하면 모달 내용이 사라진다. 새로고침하면 정상.**
 * 실측(2026-08-28, 코디네이터 설정): 페이지 로드 후 `.aot-viz` 14개 —
 * 저장 뒤 AJAX 로 받은 같은 영역은 `.aot-viz` **0개**. 껍데기 수는 같다
 * (`.aot-scale-input` 10 · `.aot-range-band` 4 · `.aot-env-status` 1).
 * 즉 사라진 것이 아니라 **한 번도 그려지지 않은** 것이고, 남는 것은 맨 숫자
 * 입력뿐이라 화면이 텅 빈 것처럼 보인다.
 *
 * 넣는 방법은 각 호출부가 `replaceWith` 로 이미 정해 두었다(조각의 뿌리가
 * 컨테이너와 **같은 id** 라, `.html()` 로 넣으면 저장할 때마다 같은 id 가 한
 * 겹씩 깊어진다 — `getElementById` 는 바깥 것만 돌려주므로 안쪽은 손이 닿지
 * 않게 된다). 여기는 넣은 **뒤**를 맡는다.
 *
 * ⚠ **옵션 영역을 AJAX 로 갈아 끼우는 새 자리를 만들면 여기를 부를 것.**
 * 지금 호출부는 셋이다(function · input · output 의 `refreshModalOptions`).
 * 각자 `selectpicker()` 만 다시 부르고 있었는데, 그 목록에 모듈을 하나씩
 * 더하는 방식으로는 새 모듈이 생길 때마다 세 곳이 조용히 갈라진다.
 */
(function () {
    'use strict';

    // 초기화 순서는 **페이지 로드 때와 같아야 한다** — layout 의 script 순서가
    // 곧 DOMContentLoaded 처리 순서다. 다르게 부르면 새로고침했을 때와 저장했을
    // 때의 화면이 미묘하게 달라지고, 그 차이는 재현 조건이 붙어 진단이 어렵다.
    //
    // ⚠ **이 목록은 손으로 유지한다 — 빠뜨리면 그 종류만 조용히 안 그려진다.**
    //   처음에 넷만 적었다가 `.aot-coord-plot`(재배 중·목표 두 줄)을 빠뜨려,
    //   고친 뒤에도 그 두 줄만 계속 사라졌다. 그래서
    //   `test_modal_enhance_covers_every_decorator` 가 옵션 화면을 꾸미는
    //   모듈 전수와 이 목록을 대조한다.
    //
    // `root` 가 false 인 것은 그 모듈의 진입점이 범위를 못 받는다는 뜻이다
    // (문서 전체를 훑는다). 새로 만드는 모듈은 `init(root)` 를 갖출 것 —
    // 범위를 못 받으면 모달 하나를 고칠 때 화면의 모든 것이 다시 그려진다.
    var MODULES = [
        {name: 'AoTBaySelect',       fn: 'init', root: true},
        {name: 'AoTEnvStatus',       fn: 'init', root: true},
        {name: 'AoTOptionDepends',   fn: 'init', root: true},
        {name: 'AoTScaleInput',      fn: 'init', root: true},
        {name: 'AoTRangeBand',       fn: 'init', root: true},
        {name: 'AoTCoordinatorPlot', fn: 'scan', root: false}
    ];

    function _el(target) {
        if (!target) return null;
        return target.jquery ? target[0] : target;
    }

    /** 이 뿌리 아래를 페이지 로드 직후와 같은 상태로 꾸민다. */
    function apply(target) {
        var el = _el(target);
        if (!el) return;

        if (window.jQuery) {
            try { window.jQuery(el).find('.selectpicker').selectpicker(); } catch (e) {}
        }
        MODULES.forEach(function (spec) {
            var mod = window[spec.name];
            if (!mod || typeof mod[spec.fn] !== 'function') return;
            // 한 모듈이 실패해도 나머지는 꾸며야 한다 — 하나 때문에 전부 맨
            // 입력으로 남으면 고친 것이 무의미해진다.
            try { spec.root ? mod[spec.fn](el) : mod[spec.fn](); } catch (e) {
                if (window.console) {
                    console.warn('[AoTModalEnhance] ' + spec.name + ' 초기화 실패', e);
                }
            }
        });
    }

    window.AoTModalEnhance = {apply: apply};
})();
