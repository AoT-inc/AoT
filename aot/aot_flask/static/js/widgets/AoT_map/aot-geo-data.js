// Shared geo-data provider.
//
// Each AoT_map widget instance independently fetches the same heavy GeoJSON
// endpoints on init — /api/geo/sites, /zones, /facility/list and
// /api/geo/overlays?map_uuid=<uuid>&type=<...>. With N map widgets pointing at
// the SAME map on one dashboard that is N identical requests per endpoint,
// fired together at page load.
//
// The previous in-file prefetch (__aotGeoPrefetch in aot-map-widget-vector.js)
// could not dedup across instances: it cached an in-flight Response, and a
// Response body can only be read once, so it was handed out exactly once and
// then re-fetched for the next consumer.
//
// This provider mirrors AoTFacilityRuntime: it caches the PARSED JSON (not the
// Response), so N widgets share one network request + one parse:
//   - in-flight dedup: concurrent get(url) calls share ONE fetch,
//   - short TTL cache: a later caller within TTL_MS reuses the parsed result.
// Geo overlays change rarely (manual edits in the geo designer), so serving
// data up to TTL_MS old is acceptable.
//
// get(url) resolves to a Response-like shim { ok, status, json() } so existing
// call sites (res.ok / await res.json()) work unchanged. json() resolves to the
// cached parsed object (shared by reference — consumers must treat it as
// read-only, which the map layer/label code already does).
(function () {
  if (window.AoTGeoData) return;

  var TTL_MS = 10000;
  var _cache = {};     // url -> { ts, ok, status, json }
  var _inflight = {};  // url -> Promise<entry>

  function shim(entry) {
    return {
      ok: entry.ok,
      status: entry.status,
      json: function () { return Promise.resolve(entry.json); }
    };
  }

  // get(url, { force }) -> Promise<{ ok, status, json() }>
  function get(url, opts) {
    var force = !!(opts && opts.force);
    var now = Date.now();
    if (!force) {
      var c = _cache[url];
      if (c && (now - c.ts) < TTL_MS) return Promise.resolve(shim(c));
      if (_inflight[url]) return _inflight[url].then(shim);
    }
    /* ── 조건부 요청은 **우리가 직접** 한다 (2026-09-04) ──────────────────
     *
     * `/api/geo/devices` 는 서버가 ETag 를 붙인다(`utils_http.json_conditional`
     * — 실측상 폴링 사이에 66~125KB 가 바이트까지 같아서 도입한 것이다).
     * 그런데 여기서는 `fetch(url)` 을 그냥 불러 **브라우저 HTTP 캐시에
     * 맡기고 있었다.** 그것이 이 저장소가 금지하는 형태다:
     *
     *   "cache:'no-store' 로 부를 것. 안 그러면 브라우저 HTTP 캐시가 조건부
     *    요청을 가로채 200(캐시본)으로 둔갑시켜, 본문을 도로 파싱한다 —
     *    아끼려던 것을 그대로 쓴다." (`aot-conditional-get.js`)
     *
     * 그래서 아끼는 것이 하나도 없었다. `AoTFacilityRuntime` 은 같은 자리를
     * 이미 제대로 하고 있었고(그 모듈이 정본이다), 여기만 빠져 있었다.
     *
     * ⚠ **`force` 에는 조건을 걸지 않는다.** force 는 "권위 있는 최신
     *   스냅샷" 요구다(제어 명령 직후). 조건부로 보내면 304 가 돌아와 캐시본을
     *   그대로 쓰게 되어 그 요구를 정면으로 배신한다.
     *
     * ⚠ **304 로 건너뛰는 것은 그 응답에 실린 것뿐이다.** 여기 응답은 목록
     *   전체라 "그 목록이 그대로다" 를 뜻한다 — 그래서 보관본을 그대로 돌려줘도
     *   된다. 다른 것(측정값 등)까지 함께 건너뛰면 안 된다. */
    var prev = _cache[url];
    var headers = {};
    if (!force && prev && prev.etag) headers['If-None-Match'] = prev.etag;
    var p = fetch(url, { credentials: 'same-origin', cache: 'no-store',
                         headers: headers })
      .then(function (r) {
        if (r.status === 304) {
          if (prev && prev.json != null) {
            // 여전히 유효하다 — TTL 을 갱신하고 보관본을 그대로 쓴다.
            prev.ts = Date.now();
            return prev;
          }
          // 검증자는 있는데 대조할 보관본이 없다 = 둘이 어긋났다. 검증자를
          // 버려 다음 호출이 무조건 요청으로 새로 받게 한다(스스로 풀린다).
          if (_cache[url]) delete _cache[url].etag;
          return { ts: Date.now(), ok: false, status: 304, json: null };
        }
        var ok = r.ok, status = r.status;
        var tag = (r.headers && r.headers.get) ? r.headers.get('ETag') : null;
        return r.json().catch(function () { return null; })
          .then(function (j) {
            return { ts: Date.now(), ok: ok, status: status, etag: tag, json: j };
          });
      })
      .then(function (entry) {
        if (entry.ok) _cache[url] = entry;
        delete _inflight[url];
        return entry;
      })
      .catch(function () {
        delete _inflight[url];
        // Network/parse failure: surface a not-ok shim so callers bail cleanly.
        return { ts: Date.now(), ok: false, status: 0, json: null };
      });
    if (!force) _inflight[url] = p;
    return p.then(shim);
  }

  // Prime the cache for a list of GET urls without consuming them (warm fetch).
  function prefetch(urls) {
    (urls || []).forEach(function (u) {
      var c = _cache[u];
      if (c && (Date.now() - c.ts) < TTL_MS) return;
      if (_inflight[u]) return;
      get(u);  // populates _inflight/_cache via the shared path
    });
  }

  function invalidate(url) {
    // 보관본과 검증자(ETag)는 **한 덩어리**로 버린다 — 여기서는 둘이 같은
    // 항목에 들어 있어 자동으로 그렇게 된다. 나중에 따로 두게 되면 반드시
    // 함께 버릴 것: 보관본만 지우면 다음 요청이 옛 검증자를 싣고 나가 304 를
    // 받는데 대조할 것이 없어, 갱신이 한 주기 통째로 빈다.
    if (url) { delete _cache[url]; }
    else { _cache = {}; }
  }

  window.AoTGeoData = { get: get, prefetch: prefetch, invalidate: invalidate };
})();
