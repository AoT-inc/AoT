/*
 * AoT polling visibility manager — battery optimization Step 2-A / Step 6 / Step 7
 *
 * [Step 2-A] Pause all setInterval polling when the page is in the background (document.hidden).
 * [Step 6]   Double the polling interval when low-power/data-saver mode is detected (halves battery/cellular load).
 * [Step 7]   On entering the background, add the aot-hidden class to document.documentElement
 *            to pause infinite animations such as .fa-spin via CSS.
 *
 * Operating principles:
 *  - Globally wrap setInterval/clearInterval to control all 21 widget types without modification.
 *  - The handle returned to the caller stays stable across pause/resume.
 *  - Non-function callbacks (string eval form) are not tracked and pass through natively.
 *  - Must be loaded before any other script (top of layout head).
 *
 * [Reconnect storm fix] Pausing is reason-based: the page is paused while ANY reason
 *  is active. The visibility manager uses the 'hidden' reason; aot-server-health.js uses
 *  the 'serverdown' reason to stop the polling flood while the server is unreachable.
 *  Exposed as window.AoTPoll = { pauseFor, resumeFor, isPaused }.
 */
(function () {
  if (window.__aotPollMgr) return;
  window.__aotPollMgr = true;

  var nativeSet = window.setInterval;
  var nativeClear = window.clearInterval;

  var registry = new Map();  // handle -> { fn, delay, extra, realId }
  var paused = false;
  var seq = 2000000000;      // synthetic handle for intervals registered while hidden

  /* ─── Step 6: adaptive interval multiplier ────────────────────── */
  var delayMult = 1;

  function calcDelayMult() {
    var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (!conn) return 1;
    if (conn.saveData) return 2;
    var t = conn.effectiveType || '';
    if (t === 'slow-2g' || t === '2g') return 2;
    return 1;
  }

  function applyDelayMult(newMult) {
    if (newMult === delayMult) return;
    delayMult = newMult;
    // Reschedule all running intervals (apply the new multiplier)
    registry.forEach(function (rec, handle) {
      if (rec.realId != null) {
        nativeClear.call(window, rec.realId);
        rec.realId = nativeSet.apply(window, [rec.fn, rec.delay * delayMult].concat(rec.extra));
      }
    });
  }

  delayMult = calcDelayMult();

  var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (conn) {
    conn.addEventListener('change', function () {
      if (!paused) applyDelayMult(calcDelayMult());
      else delayMult = calcDelayMult(); // while paused, only update the multiplier; applied on resume
    });
  }
  /* ────────────────────────────────────────────────────────────── */

  function realSet(rec) {
    return nativeSet.apply(window, [rec.fn, rec.delay * delayMult].concat(rec.extra));
  }

  window.setInterval = function (fn, delay) {
    if (typeof fn !== 'function') {
      return nativeSet.apply(window, arguments);
    }
    var extra = Array.prototype.slice.call(arguments, 2);
    var rec = { fn: fn, delay: delay, extra: extra, realId: null };
    var handle;
    if (paused) {
      handle = ++seq;
    } else {
      rec.realId = realSet(rec);
      handle = rec.realId;
    }
    registry.set(handle, rec);
    return handle;
  };

  window.clearInterval = function (handle) {
    var rec = registry.get(handle);
    if (rec) {
      registry.delete(handle);
      if (rec.realId != null) nativeClear.call(window, rec.realId);
      return;
    }
    return nativeClear.call(window, handle);
  };

  // Reason-based pausing: paused while any reason is active.
  var pauseReasons = Object.create(null);

  function doPause() {
    if (paused) return;
    paused = true;
    registry.forEach(function (rec) {
      if (rec.realId != null) { nativeClear.call(window, rec.realId); rec.realId = null; }
    });
  }

  function doResume() {
    if (!paused) return;
    paused = false;
    delayMult = calcDelayMult(); // apply the latest multiplier on resume
    registry.forEach(function (rec) {
      if (rec.realId == null) { rec.realId = realSet(rec); }
    });
  }

  function recompute() {
    var shouldPause = false;
    for (var k in pauseReasons) { if (pauseReasons[k]) { shouldPause = true; break; } }
    if (shouldPause) doPause(); else doResume();
  }

  function pauseFor(reason) { pauseReasons[reason] = true; recompute(); }
  function resumeFor(reason) { delete pauseReasons[reason]; recompute(); }

  // Backwards-compatible aliases (visibility uses the 'hidden' reason).
  function pauseAll() { pauseFor('hidden'); }
  function resumeAll() { resumeFor('hidden'); }

  window.AoTPoll = {
    pauseFor: pauseFor,
    resumeFor: resumeFor,
    isPaused: function () { return paused; }
  };

  /* ─── Step 7: pause CSS animations while hidden ───────────────── */
  (function injectHiddenStyle() {
    var s = document.createElement('style');
    s.textContent =
      '.aot-hidden .fa-spin,' +
      '.aot-hidden [class*="fa-spin"],' +
      '.aot-hidden .spinner-border,' +
      '.aot-hidden .spinner-grow {' +
      'animation-play-state:paused!important}';
    (document.head || document.documentElement).appendChild(s);
  })();

  function setHiddenClass(hidden) {
    if (hidden) {
      document.documentElement.classList.add('aot-hidden');
    } else {
      document.documentElement.classList.remove('aot-hidden');
    }
  }
  /* ────────────────────────────────────────────────────────────── */

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      pauseAll();
      setHiddenClass(true);
    } else {
      resumeAll();
      setHiddenClass(false);
    }
  });

  if (document.hidden) {
    pauseReasons['hidden'] = true;
    paused = true;
    setHiddenClass(true);
  }
})();
