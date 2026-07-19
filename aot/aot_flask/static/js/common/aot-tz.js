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
  var meta = document.querySelector && document.querySelector('meta[name="aot-fallback-tz"]');
  if (meta && meta.content) {
    FALLBACK_TZ = meta.content;
  }

  function viewerTz() {
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
    relative: relative,
    viewerTz: viewerTz,
    fallbackTz: function () { return FALLBACK_TZ; },
    applyToDom: applyToDom,
    FORMATS: FORMATS
  };
})(window);
