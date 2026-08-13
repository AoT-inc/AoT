// 주기 폴링 GET 을 조건부 요청으로 바꾸는 투명 레이어.
//
// 대시보드 위젯 상당수가 $.getJSON 으로 같은 엔드포인트를 5~30초마다 다시 부르는데,
// 실측해 보면 폴링 사이에 응답이 그대로인 경우가 대부분이다. 그래도 폰은 매번
// 라디오를 깨우고 같은 JSON 을 다시 파싱한다
// (.local/reports/mobile-battery-heat-audit-20260813.md).
//
// 이 레이어는 URL 별로 직전 ETag 와 **파싱된** 응답을 들고 있다가
//   - 요청에 If-None-Match 를 실어 보내고,
//   - 304 가 오면 보관해 둔 파싱 결과로 성공 처리한다.
// 위젯 핸들러는 아무 수정 없이 그대로 돈다 — 사라지는 것은 본문 전송과 JSON.parse 다.
// (핸들러의 재렌더까지 없애지는 못한다. 그건 호출부가 "안 바뀜"을 알아야 하는데,
//  그 경로는 지도 위젯의 /api/geo/devices 처럼 개별로 처리한다.)
//
// aot-data-batch.js 와 같은 $.ajaxTransport 방식이다. 그쪽이 /last|/past 를 먼저
// 가져가고, 여기서는 그 외의 **명시적으로 등록된** 경로만 다룬다 — 모든 GET 을
// 가로채면 한 번 어긋났을 때 어디가 원인인지 찾기 어려워진다.
(function ($) {
  if (!$ || !$.ajaxTransport) return;
  if (window.AoTConditionalGetInstalled) return;
  window.AoTConditionalGetInstalled = true;

  // 등록 기준: (1) 주기 폴링된다 (2) 서버가 ETag 를 준다 (3) 응답이 자주 안 바뀐다.
  // 셋 중 하나라도 아니면 넣지 말 것 — 특히 (2)가 없으면 매번 200 이라 무의미하고,
  // 캐시만 들고 있게 되어 메모리만 쓴다.
  var PATTERNS = [
    /^\/function_status_activated\//
  ];

  var store = {};   // url -> { etag, data }

  function matches(path) {
    for (var i = 0; i < PATTERNS.length; i++) {
      if (PATTERNS[i].test(path)) return true;
    }
    return false;
  }

  function copy(data) {
    // 핸들러가 응답을 제자리에서 고치는 경우가 있어 보관본을 그대로 넘기지 않는다.
    // 5KB 남짓 복제는 같은 크기의 JSON.parse 보다 훨씬 싸다.
    try { return structuredClone(data); } catch (e) { return data; }
  }

  $.ajaxTransport('+json', function (options) {
    if ((options.type || 'GET').toUpperCase() !== 'GET') return;
    var url = options.url || '';
    if (!matches(url.split('?')[0])) return;

    var aborted = false;
    var controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;

    return {
      send: function (headers, complete) {
        var rec = store[url];
        var h = {};
        if (rec && rec.etag) h['If-None-Match'] = rec.etag;

        // cache:'no-store' — 브라우저 HTTP 캐시가 조건부 요청을 가로채면 304 가
        // 여기까지 오지 않고 200(캐시본)으로 둔갑해, 본문을 도로 파싱하게 된다.
        fetch(url, {
          credentials: 'same-origin',
          cache: 'no-store',
          headers: h,
          signal: controller ? controller.signal : undefined
        }).then(function (r) {
          if (aborted) return;
          if (r.status === 304 && rec) {
            complete(200, 'success', { json: copy(rec.data) }, 'Content-Type: application/json');
            return;
          }
          if (r.status === 304) {
            // 검증자와 보관본이 어긋났다 — 검증자를 버리고 이번 주기는 건너뛴다.
            delete store[url];
            complete(204, 'nocontent', { json: null }, 'Content-Type: application/json');
            return;
          }
          if (r.status === 204) {
            complete(204, 'nocontent', { json: null }, 'Content-Type: application/json');
            return;
          }
          if (!r.ok) { complete(r.status, 'error'); return; }
          var tag = r.headers.get('ETag');
          return r.json().then(function (data) {
            if (aborted) return;
            if (tag) store[url] = { etag: tag, data: data };
            complete(200, 'success', { json: data }, 'Content-Type: application/json');
          });
        }).catch(function () {
          if (!aborted) complete(0, 'error');
        });
      },
      abort: function () {
        aborted = true;
        if (controller) { try { controller.abort(); } catch (e) {} }
      }
    };
  });
})(window.jQuery);
