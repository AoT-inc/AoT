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

  if ($ && $.ajaxTransport) {
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
  }

  // ── 직접 호출용 배치 API ───────────────────────────────────────────────
  //
  // 위 transport 는 jQuery 로 나가는 /last·/past GET 만 가로챈다. 그런데
  // `/data_batch` 를 **직접 POST 하는 곳이 셋** 더 있다(지도 위젯 값 갱신 ·
  // 시설 센서 라벨 · 지도 팝업). 그 셋은 서로를 모르므로, 같은 지도를 보는
  // 지도 위젯이 3개인 대시보드에서는 거의 같은 항목 목록이 3벌 나갔다
  // (라즈베리파이 실측: 한 틱에 POST 3회, 각 ~2초).
  //
  // postItems() 는 짧은 창 안의 호출을 모아 **항목 단위로 중복을 제거한 뒤**
  // 한 번만 보내고, 각 호출자에게는 자기가 요청한 순서 그대로 돌려준다.
  // 위젯 셋이 같은 측정을 물으면 서버로 나가는 항목은 하나다.
  var _postQueue = [];
  var _postTimer = null;

  function _itemKey(it) {
    return [it.kind, it.unique_id, it.measure_type, it.measurement_id, it.period].join('|');
  }

  function _postChunks(merged) {
    var chunks = [];
    for (var i = 0; i < merged.length; i += MAX_PER_BATCH) {
      chunks.push(merged.slice(i, i + MAX_PER_BATCH));
    }
    return Promise.all(chunks.map(function (chunk) {
      return fetch('/data_batch', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
        body: JSON.stringify({ items: chunk })
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          var res = (j && Array.isArray(j.results)) ? j.results : null;
          // 길이가 다르면 어느 결과가 어느 항목인지 알 수 없다 — 억지로 맞추면
          // 값이 엉뚱한 장치에 붙는다. 실패로 처리해 호출자의 폴백에 맡긴다.
          if (!res || res.length !== chunk.length) return null;
          return res;
        })
        .catch(function () { return null; });
    })).then(function (parts) {
      if (parts.some(function (p) { return p === null; })) return null;
      return [].concat.apply([], parts);
    });
  }

  function _flushPost() {
    _postTimer = null;
    var pending = _postQueue;
    _postQueue = [];
    if (!pending.length) return;

    var seen = {};
    var merged = [];
    pending.forEach(function (job) {
      job.idx = job.items.map(function (it) {
        var k = _itemKey(it);
        if (!(k in seen)) { seen[k] = merged.length; merged.push(it); }
        return seen[k];
      });
    });

    _postChunks(merged).then(function (all) {
      pending.forEach(function (job) {
        // 실패는 `null` 로 돌려준다 — 직접 fetch 하던 시절과 같은 신호라
        // 호출부의 기존 폴백(낱개 재조회 등)이 그대로 돈다.
        job.resolve(all ? job.idx.map(function (i) { return all[i]; }) : null);
      });
    });
  }

  /**
   * postItems(items) -> Promise<results[] | null>
   *
   * items: [{ kind, unique_id, measure_type, measurement_id, period }, ...]
   * 반환 배열은 요청한 items 와 **같은 길이·같은 순서**다.
   */
  function postItems(items) {
    items = items || [];
    if (!items.length) return Promise.resolve([]);
    return new Promise(function (resolve) {
      _postQueue.push({ items: items, resolve: resolve });
      if (!_postTimer) _postTimer = setTimeout(_flushPost, WINDOW_MS);
    });
  }

  window.AoTDataBatch = { postItems: postItems };
})(window.jQuery);
