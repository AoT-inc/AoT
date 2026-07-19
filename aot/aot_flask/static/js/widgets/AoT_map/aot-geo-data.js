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
    var p = fetch(url)
      .then(function (r) {
        var ok = r.ok, status = r.status;
        return r.json().catch(function () { return null; })
          .then(function (j) {
            return { ts: Date.now(), ok: ok, status: status, json: j };
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
    if (url) { delete _cache[url]; }
    else { _cache = {}; }
  }

  window.AoTGeoData = { get: get, prefetch: prefetch, invalidate: invalidate };
})();
