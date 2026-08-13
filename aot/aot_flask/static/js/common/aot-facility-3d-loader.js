/*
 * AoT 3D 시설 스택 지연 로더.
 *
 * three.min.js(654KB) + aot-facility-3d.js(158KB) + aot-facility-map-3d.js(19KB)
 * = 831KB. 예전에는 AoT_map 위젯이 이 셋을 `document.write` 로 **무조건** 끌어왔다.
 * 지도 위젯을 하나라도 올린 대시보드는 3D 시설을 한 번도 안 열어도 831KB 를 받고,
 * 파싱하고, 컴파일했다 — 게다가 document.write 는 파서를 멈춰 세운다. 모바일에서
 * 이 비용이 그대로 발열로 나온다(.local/reports/mobile-battery-heat-audit-20260813.md).
 *
 * 이제 `ensure()` 가 **실제로 3D 시설을 그려야 할 때** 한 번만 로드한다.
 * 지도에 3D 지오메트리를 가진 시설이 하나도 없으면 831KB 는 영영 안 받는다.
 *
 * 다른 경로(AoT_facility 위젯의 _ensureThree, geo/design 페이지)가 같은 파일을
 * 이미 넣어 뒀을 수 있으므로, 주입 전에 전역과 <script> 태그를 모두 확인한다 —
 * 태그만 있고 전역이 아직 없으면 중복 주입하지 않고 전역이 뜰 때까지 기다린다.
 */
(function (global) {
  'use strict';
  if (global.AoTFacility3DLoader) return;

  var STACK = [
    { src: '/static/js/widgets/AoT_facility/three.min.js?v=2',        name: 'THREE' },
    { src: '/static/js/widgets/AoT_facility/aot-facility-3d.js?v=36', name: 'AoTFacility3D' },
    { src: '/static/js/geo/aot-facility-map-3d.js?v=28',              name: 'AoTFacilityMap3D' }
  ];

  var WAIT_TIMEOUT_MS = 15000;
  var WAIT_POLL_MS = 50;

  var pending = null;

  function waitForGlobal(name) {
    return new Promise(function (resolve, reject) {
      if (global[name]) { resolve(); return; }
      var waited = 0;
      var t = setInterval(function () {
        if (global[name]) { clearInterval(t); resolve(); return; }
        waited += WAIT_POLL_MS;
        if (waited >= WAIT_TIMEOUT_MS) {
          clearInterval(t);
          reject(new Error('[AoTFacility3DLoader] timeout waiting for ' + name));
        }
      }, WAIT_POLL_MS);
    });
  }

  function inject(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      // async=false 로 두어야 주입 순서대로 실행된다(three → facility-3d → map-3d).
      s.async = false;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error('[AoTFacility3DLoader] load failed: ' + src)); };
      (document.head || document.documentElement).appendChild(s);
    });
  }

  function ensureOne(entry) {
    if (global[entry.name]) return Promise.resolve();
    var file = entry.src.split('?')[0].split('/').pop();
    if (document.querySelector('script[src*="' + file + '"]')) {
      // 다른 경로가 이미 넣었다 — 두 벌 받지 말고 전역이 뜰 때까지 기다린다.
      return waitForGlobal(entry.name);
    }
    return inject(entry.src).then(function () { return waitForGlobal(entry.name); });
  }

  function isLoaded() {
    for (var i = 0; i < STACK.length; i++) {
      if (!global[STACK[i].name]) return false;
    }
    return true;
  }

  function ensure() {
    if (isLoaded()) return Promise.resolve();
    if (pending) return pending;
    pending = STACK.reduce(function (chain, entry) {
      return chain.then(function () { return ensureOne(entry); });
    }, Promise.resolve()).catch(function (e) {
      // 실패는 캐시하지 않는다 — 다음 호출에서 다시 시도할 수 있어야 한다.
      pending = null;
      throw e;
    });
    return pending;
  }

  global.AoTFacility3DLoader = { ensure: ensure, isLoaded: isLoaded };
})(window);
