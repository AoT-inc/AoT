// Dashboard data-request coalescer.
//
// Every value/gauge/indicator widget polls /last/<id>/<type>/<mid>/<period>
// and every graph widget polls /past/<id>/<type>/<mid>/<seconds>, each on its
// own timer. On a busy dashboard that is dozens-to-hundreds of GETs per tick;
// the browser's ~6-connection-per-origin cap serialises them into a long queue
// and the page paints blank while it drains.
//
// This installs a jQuery ajax transport that intercepts those GETs, holds them
// for a short coalescing window, and POSTs them together to /data_batch — one
// round trip instead of N. Each original $.ajax / $.getJSON call resolves from
// its slice of the batch reply, so widget success/error handlers run unchanged
// (status 204 = no data is preserved). No widget code changes are required, and
// future widgets hitting /last or /past are covered automatically.
//
// Only input|function|output|pid are intercepted. /past/<id>/tag/... (graph
// note markers) is left to the original endpoint, which the batch route does
// not handle.
(function ($) {
  if (!$ || !$.ajaxTransport) return;
  if (window.AoTDataBatchInstalled) return;
  window.AoTDataBatchInstalled = true;

  // /last/<uid>/<type>/<mid>/<period>  or  /past/<uid>/<type>/<mid>/<seconds>
  var RE = /^\/(last|past)\/([^/?]+)\/(input|function|output|pid)\/([^/?]+)\/([^/?]+)$/;
  var WINDOW_MS = 40;     // collect a tick's requests, then flush as one POST
  var MAX_PER_BATCH = 250; // stay under the server's per-request item cap
  var JSON_CT = 'Content-Type: application/json';

  var queue = [];
  var timer = null;

  function csrfToken() {
    var el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute('content') : '';
  }

  // Re-issue one queued request against its original endpoint. Used when the
  // batch call fails so a transient /data_batch error never blanks widgets —
  // behaviour degrades to exactly the pre-batch path.
  function directFallback(rec) {
    if (rec.aborted) return;
    fetch(rec.url, { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 204) {
          rec.complete(204, 'nocontent', { json: null }, JSON_CT);
          return null;
        }
        return r.json().then(function (j) {
          rec.complete(200, 'success', { json: j }, JSON_CT);
        });
      })
      .catch(function () { rec.complete(0, 'error'); });
  }

  function dispatch(rec, payload) {
    if (rec.aborted) return;
    // null / undefined => server had no data for this item => 204, matching the
    // single-item endpoints. Widget handlers branch on jqXHR.status === 204.
    if (payload == null) {
      rec.complete(204, 'nocontent', { json: null }, JSON_CT);
    } else {
      rec.complete(200, 'success', { json: payload }, JSON_CT);
    }
  }

  function flushChunk(batch) {
    var items = batch.map(function (rec) {
      return {
        kind: rec.kind,
        unique_id: rec.parts[2],
        measure_type: rec.parts[3],
        measurement_id: rec.parts[4],
        period: rec.parts[5]
      };
    });
    $.ajax({
      url: '/data_batch',
      method: 'POST',
      contentType: 'application/json',
      dataType: 'json',
      headers: { 'X-CSRFToken': csrfToken() },
      data: JSON.stringify({ items: items })
    }).done(function (resp) {
      var results = (resp && resp.results) || [];
      batch.forEach(function (rec, i) { dispatch(rec, results[i]); });
    }).fail(function () {
      batch.forEach(directFallback);
    });
  }

  function flush() {
    timer = null;
    var pending = queue;
    queue = [];
    for (var i = 0; i < pending.length; i += MAX_PER_BATCH) {
      flushChunk(pending.slice(i, i + MAX_PER_BATCH));
    }
  }

  $.ajaxTransport('+*', function (options) {
    var type = (options.type || 'GET').toUpperCase();
    if (type !== 'GET') return;            // POST/etc. -> default transport
    var url = options.url || '';
    var path = url.split('?')[0];
    var m = RE.exec(path);
    if (!m) return;                        // not a /last|/past data call

    var rec = { parts: m, kind: m[1], url: url, aborted: false };
    return {
      send: function (headers, completeCallback) {
        rec.complete = completeCallback;
        queue.push(rec);
        if (!timer) timer = setTimeout(flush, WINDOW_MS);
      },
      abort: function () { rec.aborted = true; }
    };
  });
})(window.jQuery);
