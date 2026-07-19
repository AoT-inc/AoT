/*
 * AoT server-health watchdog — reconnect-storm fix.
 *
 * Problem this solves:
 *   When the server goes down (e.g. host reboot, Docker not yet up), every open
 *   dashboard keeps firing its widget/daemon setInterval polls. None of them back
 *   off, so the moment the server returns, dozens of queued polls hit at once —
 *   a self-inflicted "too many requests" stampede that can knock the freshly
 *   recovered server over again and break re-login.
 *
 * Strategy (clean single-reload instead of per-widget backoff):
 *   1. Watch ALL jQuery AJAX calls. N consecutive *connection* failures
 *      (status 0 / 502 / 503 / 504) => declare the server "down".
 *   2. On "down": pause every registered poll via AoTPoll.pauseFor('serverdown')
 *      so the page stops hammering. No blocking overlay is shown — the daemon/app
 *      state is surfaced only by tinting the nav-bar brand-link background
 *      (see layout.html AoTBrandStatus / check_daemon_status → #brand-link).
 *   3. While down, probe reachability with a SINGLE request on exponential
 *      backoff (2s → 4s → … → 30s) against an auth-independent static asset.
 *   4. First successful probe => one clean location.reload(): fresh session,
 *      fresh CSRF, no widget stampede.
 *
 * Requires jQuery (load after it) and aot-poll-visibility.js (for AoTPoll).
 */
(function () {
  if (window.__aotServerHealth) return;
  window.__aotServerHealth = true;

  if (typeof window.jQuery === 'undefined') return;
  var $ = window.jQuery;

  var FAIL_THRESHOLD = 2;       // consecutive connection failures before declaring down
  var BACKOFF_START = 2000;     // first reachability probe delay
  var BACKOFF_MAX = 30000;      // cap probe interval
  var PROBE_TIMEOUT = 5000;     // give up on a single probe after this

  var failCount = 0;
  var down = false;
  var backoff = BACKOFF_START;
  var probeTimer = null;

  function isConnFailure(jqXHR, textStatus) {
    if (!jqXHR) return false;
    // Aborted requests (navigation, manual abort) are not server failures.
    if (textStatus === 'abort' || jqXHR.statusText === 'abort') return false;
    var s = jqXHR.status;
    return s === 0 || s === 502 || s === 503 || s === 504;
  }

  $(document).ajaxError(function (event, jqXHR, settings, thrownError) {
    if (down) return;
    if (isConnFailure(jqXHR, thrownError)) {
      failCount++;
      if (failCount >= FAIL_THRESHOLD) enterDown();
    } else {
      failCount = 0;  // a real HTTP response means the server is reachable
    }
  });

  $(document).ajaxSuccess(function () { failCount = 0; });

  function enterDown() {
    if (down) return;
    down = true;
    if (window.AoTPoll && window.AoTPoll.pauseFor) {
      window.AoTPoll.pauseFor('serverdown');
    }
    // Reflect the down state on the nav-bar logo right away instead of waiting
    // for the next check_daemon_status poll (up to 15s away). App/server
    // unreachable maps to the gray brand-link tint, mirroring
    // check_daemon_status's error handler. No network request needed.
    if (window.AoTBrandStatus) window.AoTBrandStatus.set('app');
    backoff = BACKOFF_START;
    scheduleProbe();
  }

  function scheduleProbe() {
    // Native setTimeout (not wrapped by the poll manager) so probing continues while paused.
    probeTimer = window.setTimeout(doProbe, backoff);
  }

  function doProbe() {
    var img = new Image();
    var settled = false;
    var to = window.setTimeout(function () {
      if (settled) return;
      settled = true;
      onProbeFail();
    }, PROBE_TIMEOUT);

    img.onload = function () {
      if (settled) return;
      settled = true;
      window.clearTimeout(to);
      onRecovered();
    };
    img.onerror = function () {
      if (settled) return;
      settled = true;
      window.clearTimeout(to);
      onProbeFail();
    };
    // Auth-independent reachability probe with a cache-buster.
    img.src = '/static/img/logo.svg?healthz=' + (new Date().getTime());
  }

  function onProbeFail() {
    backoff = Math.min(backoff * 2, BACKOFF_MAX);
    scheduleProbe();
  }

  function onRecovered() {
    // No user-facing message — the nav-bar logo already reflects the state.
    // One clean reload — replaces the page so back-button doesn't return to the stale state.
    window.location.reload();
  }
})();
