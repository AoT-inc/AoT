/* =========================================================
 * aot-modal-scroll-lock.js
 * 1) Bootstrap 4 _setScrollbar no-op 패치 (데스크탑 시프트 방지)
 * 2) iOS Safari 배경 스크롤 차단
 *
 * [데스크탑 시프트 원인]
 * html { overflow-y: scroll } 로 html 이 항상 스크롤 컨테이너이므로
 * body overflow:hidden(.modal-open)이 뷰포트 폭에 영향을 주지 않는다.
 * Bootstrap 4 는 이 상황을 인식하지 못하고 body.paddingRight += scrollbarWidth
 * 를 실행해 오히려 콘텐츠를 17px 줄인다 → gridShift=-17px 시프트 발생.
 * _setScrollbar/_resetScrollbar 를 no-op 으로 패치해 이를 차단한다.
 *
 * [iOS 배경 스크롤]
 * iOS Safari 는 body.modal-open { overflow:hidden } 만으로는
 * 모달 뒤 페이지의 터치 스크롤이 막히지 않는다.
 * 모달이 열릴 때 body 를 position:fixed 로 고정한다.
 * ========================================================= */

/* ---- 모달 열림 시 body 폭 고정 + Bootstrap padding 보정 차단 (전 플랫폼 공통) ---- */
/*
 * 문제: 모달 열림 시 body.overflow:hidden 이 뷰포트 스크롤바를 사라지게 해
 *   1) 뷰포트가 ~17px 넓어지고 body(max-width:100vw)가 팽창
 *   2) Bootstrap이 이를 body.paddingRight += scrollbarWidth 로 보정하는데
 *      이 보정이 오히려 내부 콘텐츠를 17px 줄여버림 → 시프트 발생
 * 해결:
 *   show.bs.modal 직전에 body 의 현재 offsetWidth 를 px 단위로 고정 →
 *   스크롤바 소멸 후에도 body 가 팽창하지 않음.
 *   Bootstrap _setScrollbar/_resetScrollbar no-op → 불필요한 padding 보정 차단.
 *   hidden.bs.modal 에서 고정 해제.
 */
(function patchBootstrapScrollbar() {
  var pinned = false;
  var savedWidth = '';

  function pinBody() {
    if (pinned) { return; }
    var w = document.body.offsetWidth;
    savedWidth = document.body.style.width;
    document.body.style.setProperty('width', w + 'px', 'important');
    pinned = true;
  }

  function unpinBody() {
    if (!pinned) { return; }
    if (savedWidth) {
      document.body.style.setProperty('width', savedWidth);
    } else {
      document.body.style.removeProperty('width');
    }
    pinned = false;
  }

  function patch() {
    if (!window.jQuery || !window.jQuery.fn.modal) { return false; }
    var Modal = window.jQuery.fn.modal.Constructor;
    if (!Modal || !Modal.prototype) { return false; }
    Modal.prototype._setScrollbar   = function () { pinBody(); };
    Modal.prototype._resetScrollbar = function () { unpinBody(); };
    return true;
  }

  if (!patch()) {
    document.addEventListener('DOMContentLoaded', patch);
  }
})();

/* ---- iOS Safari 배경 스크롤 차단 ---- */
(function () {
  'use strict';

  // iOS(iPhone/iPad)에서만 적용. 다른 플랫폼은 기존 overflow:hidden 으로 충분하며
  // position:fixed 를 적용하면 오히려 스크롤 위치가 튀는 부작용이 있다.
  var ua = navigator.userAgent || '';
  var isIOS = /iP(hone|od|ad)/.test(ua) ||
    // iPadOS 13+ 는 Mac 으로 위장 → touch 지원으로 판별
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

  if (!isIOS) { return; }

  var depth = 0;        // 현재 열린 모달 수
  var savedScrollY = 0; // 잠금 시점의 스크롤 위치

  function lock() {
    if (depth === 0) {
      savedScrollY = window.scrollY || window.pageYOffset || 0;
      var body = document.body;
      body.style.position = 'fixed';
      body.style.top = (-savedScrollY) + 'px';
      body.style.left = '0';
      body.style.right = '0';
      body.style.width = '100%';
    }
    depth++;
  }

  function unlock() {
    depth = Math.max(0, depth - 1);
    if (depth === 0) {
      var body = document.body;
      body.style.position = '';
      body.style.top = '';
      body.style.left = '';
      body.style.right = '';
      body.style.width = '';
      // 보존했던 위치로 즉시 복원
      window.scrollTo(0, savedScrollY);
    }
  }

  // Bootstrap 4 모달 이벤트(jQuery 네임스페이스 이벤트)에 바인딩.
  // shown/hidden(애니메이션 완료) 대신 show/hide(시작) 시점에 잠그면
  // 모달 표시 애니메이션 중에도 배경이 움직이지 않는다.
  function bind() {
    if (!window.jQuery) { return false; }
    var $ = window.jQuery;
    $(document)
      .on('show.bs.modal', lock)
      .on('hide.bs.modal', unlock);
    return true;
  }

  if (!bind()) {
    // jQuery 가 아직 로드되지 않았으면 DOM ready 후 재시도
    document.addEventListener('DOMContentLoaded', bind);
  }
})();
