// Shared facility /runtime provider.
//
// The actuator-label poller (aot-map-widget-vector.js) and the sensor-label
// poller (aot-map-sensor-labels.js) BOTH hit the identical, heavy endpoint
// /api/aot/facility/<uuid>/runtime once per facility per cycle, returning the
// same payload. With N facilities and both overlays active that is 2N
// concurrent requests every cycle, fired simultaneously at page load.
//
// On a low-spec host (e.g. Raspberry Pi) the gunicorn thread pool is tiny, so
// that fan-out saturates the pool and starves user-initiated requests — the
// bay modal click then waits in the queue (observed 1s+, 4s+ when cold).
//
// This provider coalesces those requests:
//   - in-flight dedup: concurrent get(uuid) calls share ONE network request
//     (collapses the page-load burst across both modules),
//   - short TTL cache: a second caller within TTL_MS reuses the result.
// Both pollers now run every >=5s (2026-09-01 — the sensor-label poller used
// to floor at 30s, a leftover from before this cache existed; that made the
// facility environment markers visibly lag the actuator on/off chips even
// though both read the same cached response). With matched cadence, whichever
// module ticks first fills the cache and the other reuses it within TTL_MS ->
// 2N requests drop toward N regardless of which poller "wins" the race.
//
// Runtime data (actuator on/off, sensor readings) changes slowly, so serving
// data up to TTL_MS old in the labels is acceptable.
(function () {
  if (window.AoTFacilityRuntime) return;

  var TTL_MS = 8000;
  var _cache = {};     // uuid -> { ts, data }
  var _inflight = {};  // uuid -> Promise
  var _etag = {};      // uuid -> ETag of the last 200 response

  // get(uuid, { force }) -> Promise<runtimeData|null>
  // force=true bypasses cache + dedup (use after a control command when the
  // caller needs an authoritative post-action snapshot).
  function get(uuid, opts) {
    var force = !!(opts && opts.force);
    var now = Date.now();
    if (!force) {
      var c = _cache[uuid];
      if (c && (now - c.ts) < TTL_MS) return Promise.resolve(c.data);
      if (_inflight[uuid]) return _inflight[uuid];
    }
    // 조건부 요청: 직전 ETag 를 실어 보내고 304 면 본문도 파싱도 없다.
    // TTL(8초)이 걸러 주는 것은 "같은 주기 안의 중복 호출" 이고, 여기서 없애는 것은
    // "주기가 지났지만 내용은 그대로인 경우" 다 — 실측상 그쪽이 압도적으로 많다.
    // cache:'no-store' 는 브라우저 HTTP 캐시가 304 를 가로채 200(캐시본)으로
    // 둔갑시키는 것을 막는다. 그러면 파싱을 그대로 해서 아끼려던 것을 도로 쓴다.
    // force=true 는 "권위 있는 최신 스냅샷" 요구다(제어 명령 직후). 조건부로 보내면
    // 304 가 돌아와 캐시본을 그대로 쓰게 되어 요구를 배신한다 — 조건을 걸지 않는다.
    var headers = {};
    if (!force && _etag[uuid]) headers['If-None-Match'] = _etag[uuid];
    var p = fetch('/api/aot/facility/' + encodeURIComponent(uuid) + '/runtime',
                  { credentials: 'same-origin', cache: 'no-store', headers: headers })
      .then(function (r) {
        if (r.status === 304) {
          if (_cache[uuid]) {
            _cache[uuid].ts = Date.now();   // 여전히 유효하다 — TTL 을 갱신한다
            return _cache[uuid].data;
          }
          // 검증자는 있는데 대조할 캐시가 없다 = 둘이 어긋났다. 검증자를 버려
          // 다음 호출이 무조건 요청으로 새로 받게 한다(스스로 풀린다).
          delete _etag[uuid];
          return null;
        }
        if (!r.ok) return null;
        var tag = r.headers.get('ETag');
        return r.json().then(function (d) {
          if (d) { _cache[uuid] = { ts: Date.now(), data: d }; _etag[uuid] = tag; }
          return d;
        });
      })
      .then(function (d) {
        delete _inflight[uuid];
        return d;
      })
      .catch(function () { delete _inflight[uuid]; return null; });
    if (!force) _inflight[uuid] = p;
    return p;
  }

  function invalidate(uuid) {
    // ETag 도 함께 버려야 한다. 캐시만 지우면 다음 요청이 옛 검증자를 싣고 나가
    // 304 를 받는데 대조할 캐시가 없어 갱신이 한 주기 통째로 비어 버린다.
    if (uuid) { delete _cache[uuid]; delete _etag[uuid]; }
    else { _cache = {}; _etag = {}; }
  }

  window.AoTFacilityRuntime = { get: get, invalidate: invalidate };
})();
