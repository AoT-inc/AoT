/*
 * AoT CSRF token refresh — keeps long-open pages valid.
 *
 * WTF_CSRF_TIME_LIMIT is bounded (12h), not None. A token embedded in a page
 * left open longer than that would otherwise fail on submit with a hard
 * error (the reason it used to be set to None at all). Instead of removing
 * the expiry, this file periodically re-signs the token in the background
 * and patches every place it's embedded in the current page:
 *   - <meta name="csrf-token"> (read by JS/AJAX callers for X-CSRFToken)
 *   - every <input name="csrf_token"> hidden field (server-rendered forms)
 *
 * Uses window.setInterval so aot-poll-visibility.js's pause/resume (hidden
 * tab, server-down backoff) applies here too — no separate battery/
 * reconnect-storm handling needed.
 *
 * Requires aot-poll-visibility.js loaded first (for the setInterval wrap);
 * degrades to plain setInterval if it isn't (still correct, just not
 * visibility-paused).
 */
(function () {
  if (window.__aotCsrfRefresh) return;
  window.__aotCsrfRefresh = true;

  var REFRESH_MS = 20 * 60 * 1000; // 20 min — comfortably under the 12h server-side limit

  function applyToken(token) {
    if (!token) return;
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) meta.setAttribute('content', token);
    var fields = document.querySelectorAll('input[name="csrf_token"]');
    for (var i = 0; i < fields.length; i++) {
      fields[i].value = token;
    }
  }

  function refresh() {
    fetch('/csrf-token', {credentials: 'same-origin'})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) applyToken(data.csrf_token); })
      .catch(function () { /* transient network/server-down — next tick retries */ });
  }

  setInterval(refresh, REFRESH_MS);
})();
