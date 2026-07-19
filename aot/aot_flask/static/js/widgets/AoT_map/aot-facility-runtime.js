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
// Because the actuator poller runs every >=5s and the sensor poller every
// >=30s, the 8s TTL means the sensor poller almost always reuses the actuator
// poller's fresh data instead of issuing its own request -> 2N drops toward N.
//
// Runtime data (actuator on/off, sensor readings) changes slowly, so serving
// data up to TTL_MS old in the labels is acceptable.
(function () {
  if (window.AoTFacilityRuntime) return;

  var TTL_MS = 8000;
  var _cache = {};     // uuid -> { ts, data }
  var _inflight = {};  // uuid -> Promise

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
    var p = fetch('/api/aot/facility/' + encodeURIComponent(uuid) + '/runtime')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d) _cache[uuid] = { ts: Date.now(), data: d };
        delete _inflight[uuid];
        return d;
      })
      .catch(function () { delete _inflight[uuid]; return null; });
    if (!force) _inflight[uuid] = p;
    return p;
  }

  function invalidate(uuid) {
    if (uuid) { delete _cache[uuid]; }
    else { _cache = {}; }
  }

  window.AoTFacilityRuntime = { get: get, invalidate: invalidate };
})();
