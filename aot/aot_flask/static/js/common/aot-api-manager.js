// Shared HTTP request de-duplicator + short-TTL cache.
//
// **이 모듈은 원래 없었다.** 세 곳이 이미
//
//     window.AoTAPIManager ? window.AoTAPIManager.request(url) : fetch(url)...
//
// 로 부르고 있었고 한 곳에는 "[Fix] Use AoTAPIManager for caching and
// deduplication" 이라는 주석까지 있었는데, 정작 `AoTAPIManager` 를 정의하는
// 코드가 저장소 어디에도 없었다. 가드가 있으니 에러도 경고도 나지 않고 전부
// 생 fetch 로 조용히 폴백했다 — **중복제거가 되고 있다고 믿을 근거만 남고
// 실제로는 하나도 되지 않는** 상태였다.
//
// 실측(라즈베리파이, 김제 대시보드): 지도 범례가 같은 URL 을 **4번** 부른다.
// `gis_openweather.py` 가 같은 `data-api-url` 을 가진 값 박스를 5개 만들고
// (온도·풍속·구름·강수·기압), 소비 코드가 `boxes.forEach` 로 **박스마다**
// 요청하기 때문이다. 한 응답에서 필드 5개를 뽑으면 될 것을 5번 받는다.
// 게다가 이 URL 은 서버가 외부(openweathermap/open-meteo)로 나가는 프록시라
// 왕복이 실측 1.7초다.
//
// 설계는 형제 모듈 `widgets/AoT_map/aot-geo-data.js`(AoTGeoData)와 같다:
//   - 진행 중 합치기: 동시에 들어온 같은 URL 은 **하나의 fetch** 를 나눠 쓴다,
//   - 짧은 TTL 캐시: 그 뒤 TTL 안의 호출은 파싱된 결과를 재사용한다.
//
// AoTGeoData 와 다른 점 둘:
//   1. 반환이 Response 유사 shim 이 아니라 **파싱된 JSON 자체**다. 기존 호출부
//      계약이 그렇다(`request(url).then(data => data.main.temp)`).
//   2. TTL 이 10초가 아니라 60초다. 이쪽은 **외부 API** 를 대신 부르는 프록시라
//      왕복이 비싸고, 값(기상·토양)은 분 단위로도 거의 안 변한다. 지도 중심이
//      바뀌면 URL 의 좌표가 바뀌어 자연히 캐시가 갈리므로, 오래된 값을 엉뚱한
//      자리에 보여줄 위험은 TTL 이 아니라 URL 이 막는다.
(function () {
  if (window.AoTAPIManager) return;

  var TTL_MS = 60000;
  var _cache = {};     // url -> { ts, json }
  var _inflight = {};  // url -> Promise<json>

  function _isGet(init) {
    if (!init) return true;
    return String(init.method || 'GET').toUpperCase() === 'GET';
  }

  // 실패 응답은 **캐시하지 않는다.** 캐시하면 한 번의 일시적 오류가 TTL 동안
  // 굳어, 서비스가 돌아와도 화면은 계속 '-' 를 보여준다.
  function _fetchJson(url, init) {
    return fetch(url, init).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, json: j }; });
    });
  }

  /**
   * request(url[, init]) -> Promise<parsedJson>
   *
   * 기존 호출부와 계약이 같다. 실패 시 거부(reject)하는 것도 예전
   * `fetch(url).then(r => r.json())` 과 같아, 호출부의 .catch 가 그대로 돈다.
   */
  function request(url, init) {
    // **GET 만 묶는다.** POST 는 같은 URL 이라도 본문이 다르면 다른 요청이라,
    // URL 로만 캐시하면 검색어 A 의 답이 검색어 B 에게 간다(/api/geo/search 가
    // 정확히 그 형태다).
    if (!_isGet(init)) {
      return _fetchJson(url, init).then(function (r) { return r.json; });
    }

    var now = Date.now();
    var c = _cache[url];
    if (c && (now - c.ts) < TTL_MS) return Promise.resolve(c.json);
    if (_inflight[url]) return _inflight[url];

    var p = _fetchJson(url, init)
      .then(function (r) {
        if (r.ok) _cache[url] = { ts: Date.now(), json: r.json };
        delete _inflight[url];
        return r.json;
      })
      .catch(function (e) {
        delete _inflight[url];
        throw e;
      });

    _inflight[url] = p;
    return p;
  }

  function invalidate(url) {
    if (url) delete _cache[url];
    else _cache = {};
  }

  window.AoTAPIManager = { request: request, invalidate: invalidate };
})();
