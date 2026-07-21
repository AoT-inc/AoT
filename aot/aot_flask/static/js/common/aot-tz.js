/*!
 * aot-tz.js - Frontend timezone display utility
 *
 * Single source of truth for converting backend timestamps to user-visible
 * strings.  All backend timestamps are UTC (with or without explicit offset).
 *
 *   Storage:  UTC                        (server)
 *   Display:  device-local OR viewer-local  (browser)
 *
 * Usage:
 *   AoTTz.formatDevice(iso, deviceTz)              // device current location
 *   AoTTz.formatViewer(iso)                        // browser local
 *   AoTTz.format(iso, { tz: 'Asia/Seoul', fmt: 'datetime' })
 *
 * Globals: window.AoTTz
 * Optional bootstrap: <meta name="aot-fallback-tz" content="UTC">
 */
(function (root) {
  'use strict';

  var FALLBACK_TZ = 'UTC';
  var USER_TZ = null;   // logged-in user's personal display tz (User.timezone), if set
  if (document.querySelector) {
    var meta = document.querySelector('meta[name="aot-fallback-tz"]');
    if (meta && meta.content) { FALLBACK_TZ = meta.content; }
    var umeta = document.querySelector('meta[name="aot-user-tz"]');
    if (umeta && umeta.content) { USER_TZ = umeta.content; }
  }

  // "Viewer" tz for personal displays: the user's configured personal tz wins
  // (a deliberate preference — e.g. while travelling), else the browser's own
  // tz, else the system fallback. Device/operational displays are unaffected —
  // they pass an explicit tz via formatDevice(). (timezone-management.md §7)
  function viewerTz() {
    if (USER_TZ) return USER_TZ;
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || FALLBACK_TZ; }
    catch (e) { return FALLBACK_TZ; }
  }

  /**
   * Parse a backend timestamp into a Date.  If string has no offset/Z,
   * assume UTC (backend convention).
   */
  function parse(input) {
    if (input == null || input === '') return null;
    if (input instanceof Date) return isNaN(input.getTime()) ? null : input;
    if (typeof input === 'number') {
      // epoch seconds vs ms
      var d = new Date(input < 1e12 ? input * 1000 : input);
      return isNaN(d.getTime()) ? null : d;
    }
    var s = String(input).trim();
    if (!s) return null;
    // If string lacks timezone info, append Z (UTC)
    var hasTz = /[zZ]$|[+\-]\d{2}:?\d{2}$/.test(s);
    if (!hasTz) {
      // Replace space separator with T
      s = s.replace(' ', 'T') + 'Z';
    }
    var d2 = new Date(s);
    return isNaN(d2.getTime()) ? null : d2;
  }

  var FORMATS = {
    datetime: { year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                hour12: false, timeZoneName: 'short' },
    datetimeShort: { year: 'numeric', month: '2-digit', day: '2-digit',
                     hour: '2-digit', minute: '2-digit', hour12: false },
    date:     { year: 'numeric', month: '2-digit', day: '2-digit' },
    time:     { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false },
    timeShort:{ hour: '2-digit', minute: '2-digit', hour12: false }
  };

  function format(input, opts) {
    opts = opts || {};
    var d = parse(input);
    if (!d) return '';
    var tz = opts.tz || viewerTz();
    var fmtKey = opts.fmt || 'datetimeShort';
    var fmt = (typeof fmtKey === 'string') ? (FORMATS[fmtKey] || FORMATS.datetimeShort) : fmtKey;
    var locale = opts.locale || (navigator.language || 'en-US');
    try {
      return new Intl.DateTimeFormat(locale, Object.assign({ timeZone: tz }, fmt)).format(d);
    } catch (e) {
      // Invalid TZ name → fallback to viewer
      try {
        return new Intl.DateTimeFormat(locale, Object.assign({ timeZone: viewerTz() }, fmt)).format(d);
      } catch (e2) {
        return d.toISOString();
      }
    }
  }

  function formatDevice(input, deviceTz, opts) {
    return format(input, Object.assign({ tz: deviceTz || FALLBACK_TZ }, opts || {}));
  }

  // Offset (ms) of `tz` from UTC at the given instant.
  function tzOffsetMs(date, tz) {
    try {
      var dtf = new Intl.DateTimeFormat('en-US', {
        timeZone: tz, hourCycle: 'h23',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      });
      var p = {};
      dtf.formatToParts(date).forEach(function (x) { p[x.type] = x.value; });
      var asUTC = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
      return asUTC - date.getTime();
    } catch (e) { return 0; }
  }

  /**
   * Interpret a NAIVE wall-clock string ("2026-07-22T06:00" / "2026-07-22 06:00")
   * AS a wall clock in `tz`, and return the corresponding absolute instant (Date).
   * This is the inverse of formatDevice — "06:00 at the device" → the UTC moment.
   * Handles DST by refining the offset once. Returns null on parse failure.
   */
  function wallToInstant(wall, tz) {
    if (!wall) return null;
    var m = String(wall).trim().match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
    if (!m) return null;
    var y = +m[1], mo = +m[2], d = +m[3], h = +m[4], mi = +m[5], s = +(m[6] || 0);
    if (!tz) return new Date(y, mo - 1, d, h, mi, s);  // no tz → browser-local
    var guess = Date.UTC(y, mo - 1, d, h, mi, s);
    var off = tzOffsetMs(new Date(guess), tz);
    var inst = guess - off;
    var off2 = tzOffsetMs(new Date(inst), tz);   // DST edge refine
    if (off2 !== off) inst = guess - off2;
    return new Date(inst);
  }

  function formatViewer(input, opts) {
    return format(input, Object.assign({ tz: viewerTz() }, opts || {}));
  }

  /**
   * Relative time ("3 minutes ago"). Negative = future.
   */
  function relative(input, opts) {
    opts = opts || {};
    var d = parse(input);
    if (!d) return '';
    var diffSec = Math.round((Date.now() - d.getTime()) / 1000);
    var abs = Math.abs(diffSec);
    var locale = opts.locale || (navigator.language || 'en-US');
    var rtf;
    try { rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }); }
    catch (e) { return format(input, opts); }
    if (abs < 60)         return rtf.format(-diffSec, 'second');
    if (abs < 3600)       return rtf.format(-Math.round(diffSec / 60), 'minute');
    if (abs < 86400)      return rtf.format(-Math.round(diffSec / 3600), 'hour');
    if (abs < 86400 * 30) return rtf.format(-Math.round(diffSec / 86400), 'day');
    return format(input, opts);
  }

  /**
   * Auto-render any element with [data-aot-ts] attribute.
   *   <span data-aot-ts="2026-05-06T12:34:56+00:00"
   *         data-aot-tz="Asia/Seoul"           (optional, default: viewer)
   *         data-aot-fmt="datetime"            (optional)
   *         data-aot-relative="true">          (optional)
   *   </span>
   */
  function applyToDom(scope) {
    var root = scope || document;
    var nodes = root.querySelectorAll('[data-aot-ts]');
    nodes.forEach(function (el) {
      var iso = el.getAttribute('data-aot-ts');
      var tz = el.getAttribute('data-aot-tz');
      var fmt = el.getAttribute('data-aot-fmt');
      var rel = el.getAttribute('data-aot-relative') === 'true';
      var out = rel ? relative(iso, { tz: tz, fmt: fmt })
                    : format(iso, { tz: tz, fmt: fmt });
      el.textContent = out;
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { applyToDom(); });
  } else {
    setTimeout(function () { applyToDom(); }, 0);
  }

  root.AoTTz = {
    parse: parse,
    format: format,
    formatDevice: formatDevice,
    formatViewer: formatViewer,
    wallToInstant: wallToInstant,
    relative: relative,
    viewerTz: viewerTz,
    fallbackTz: function () { return FALLBACK_TZ; },
    applyToDom: applyToDom,
    FORMATS: FORMATS
  };
})(window);
