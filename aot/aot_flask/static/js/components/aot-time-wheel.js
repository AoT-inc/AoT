/*
 * AoT Time Wheel — shared infinite drum-wheel time picker (hh:mm:ss)
 * Reusable across widgets. Paired with /static/css/components/aot-time-wheel.css
 *
 * Usage:
 *   AoTTimeWheel.open({
 *     value: 3600,            // seconds (number) or "HH:MM:SS" string
 *     title: 'Run',           // modal heading
 *     max: 86399,             // optional upper bound in seconds (default 23:59:59)
 *     onConfirm: function(totalSeconds, hms){ ... }
 *   });
 *
 * Helpers: AoTTimeWheel.toSeconds("01:02:03"), AoTTimeWheel.toHMS(3723)
 *
 * The wheel repeats each range many times so scrolling never reaches an edge;
 * it silently recenters to the middle block (a whole-cycle shift is visually
 * identical), giving an endless-wheel feel. Native scroll + CSS scroll-snap
 * drive both touch drag and mouse wheel.
 */
(function(){
  if (window.AoTTimeWheel) { return; }   // define once (shared across widgets)

  var ITEM_H = 36;            // px per row (must match CSS .aot-wheel-item height)
  var ANGLE_PER_ROW = 20;     // deg of drum tilt per row
  var REPEAT = 11;            // odd number of repeated blocks
  var MID = Math.floor(REPEAT / 2);
  var WINDOW = 6;             // rows styled above/below center
  var HMS_MAX = 86399;        // 23:59:59

  var el = null;              // singleton overlay element
  var target = null;          // { onConfirm, max }
  var snapTimers = {};
  var raf = {};

  function pad2(n){ return (n < 10 ? '0' : '') + n; }
  function clampSec(s, max){
    s = parseInt(s, 10);
    if (!isFinite(s) || s < 0) { s = 0; }
    if (s > max) { s = max; }
    return s;
  }
  function toHMS(totalSec){
    var s = clampSec(totalSec, HMS_MAX);
    return pad2(Math.floor(s / 3600)) + ':' + pad2(Math.floor((s % 3600) / 60)) + ':' + pad2(s % 60);
  }
  function toSeconds(v){
    if (typeof v === 'number') { return v; }
    var parts = String(v || '').split(':');
    var hh = parseInt(parts[0], 10) || 0;
    var mm = parseInt(parts[1], 10) || 0;
    var ss = parts.length > 2 ? (parseInt(parts[2], 10) || 0) : 0;
    return (hh * 3600) + (mm * 60) + ss;
  }

  function buildColumn(name, count){
    var html = '<div class="aot-wheel-pad"></div>';
    var totalRows = count * REPEAT;
    for (var i = 0; i < totalRows; i++){
      var val = i % count;
      html += '<div class="aot-wheel-item" data-idx="' + i + '" data-val="' + val + '">' + pad2(val) + '</div>';
    }
    html += '<div class="aot-wheel-pad"></div>';
    return '<div class="aot-wheel-col" data-col="' + name + '" data-count="' + count + '">' + html + '</div>';
  }

  function ensureEl(){
    if (el && document.body.contains(el)) { return el; }
    var wrap = document.createElement('div');
    wrap.className = 'aot-wheel-backdrop';
    wrap.id = 'aot_time_wheel';
    wrap.innerHTML =
      '<div class="aot-wheel-panel">' +
        '<div class="aot-wheel-title"></div>' +
        '<div class="aot-wheel-cols">' +
          buildColumn('hh', 24) +
          '<span class="aot-wheel-sep">:</span>' +
          buildColumn('mm', 60) +
          '<span class="aot-wheel-sep aot-wheel-sep-ss">:</span>' +
          buildColumn('ss', 60) +
          '<div class="aot-wheel-band"></div>' +
        '</div>' +
        '<div class="aot-wheel-actions">' +
          '<button type="button" class="btn aot-pill-btn aot-wheel-cancel"></button>' +
          '<button type="button" class="btn aot-pill-btn aot-pill-btn-secondary aot-wheel-reset"></button>' +
          '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary aot-wheel-ok"></button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(wrap);
    el = wrap;
    var cols = el.querySelectorAll('.aot-wheel-col');
    for (var i = 0; i < cols.length; i++){
      cols[i]._items = cols[i].querySelectorAll('.aot-wheel-item');
      cols[i]._count = parseInt(cols[i].getAttribute('data-count'), 10);
      cols[i]._range = null;
    }
    wireEvents();
    return el;
  }

  function colByName(name){ return el.querySelector('.aot-wheel-col[data-col="' + name + '"]'); }
  function rawIndex(col){ return Math.round(col.scrollTop / ITEM_H); }
  function selectedVal(col){
    var c = col._count;
    return ((rawIndex(col) % c) + c) % c;
  }
  function scrollToVal(col, val, smooth){
    var raw = MID * col._count + val;
    var top = raw * ITEM_H;
    if (smooth && col.scrollTo) { col.scrollTo({ top: top, behavior: 'smooth' }); }
    else { col.scrollTop = top; }
    render(col);
  }
  function loopRecenter(col){
    var count = col._count;
    var oneCycle = count * ITEM_H;
    var block = Math.floor((col.scrollTop / ITEM_H) / count);
    if (block < 2 || block > (REPEAT - 3)) {
      var within = col.scrollTop - block * oneCycle;
      col.scrollTop = MID * oneCycle + within;
    }
  }
  // Drum render — rotateX only (vertical fold, no horizontal motion), windowed.
  function render(col){
    var items = col._items;
    if (!items) { return; }
    var center = col.scrollTop / ITEM_H;
    var sel = Math.round(center);
    var lo = Math.max(0, sel - WINDOW);
    var hi = Math.min(items.length - 1, sel + WINDOW);
    var prev = col._range;
    if (prev){
      for (var p = prev[0]; p <= prev[1]; p++){
        if (p < lo || p > hi){ items[p].style.visibility = 'hidden'; items[p].classList.remove('is-selected'); }
      }
    }
    for (var i = lo; i <= hi; i++){
      var it = items[i];
      var offset = i - center;
      var abs = Math.abs(offset);
      it.style.visibility = 'visible';
      it.style.transform = 'rotateX(' + (-offset * ANGLE_PER_ROW) + 'deg)';
      it.style.opacity = Math.max(0.12, 1 - abs * 0.26).toFixed(3);
      it.classList.toggle('is-selected', i === sel);
    }
    col._range = [lo, hi];
  }

  function wireEvents(){
    var cols = el.querySelectorAll('.aot-wheel-col');
    Array.prototype.forEach.call(cols, function(col){
      col.addEventListener('scroll', function(){
        var key = col.getAttribute('data-col');
        loopRecenter(col);
        if (!raf[key]) {
          raf[key] = requestAnimationFrame(function(){ raf[key] = null; render(col); });
        }
        if (snapTimers[key]) { clearTimeout(snapTimers[key]); }
        snapTimers[key] = setTimeout(function(){ render(col); }, 90);
      });
    });
    el.addEventListener('click', function(e){
      var item = e.target.closest && e.target.closest('.aot-wheel-item');
      if (item) {
        var col = item.closest('.aot-wheel-col');
        var raw = parseInt(item.getAttribute('data-idx'), 10);
        col.scrollTo ? col.scrollTo({ top: raw * ITEM_H, behavior: 'smooth' }) : (col.scrollTop = raw * ITEM_H);
        return;
      }
      if (e.target.classList.contains('aot-wheel-cancel')) { close(); return; }
      if (e.target.classList.contains('aot-wheel-reset')) { reset(); return; }
      if (e.target.classList.contains('aot-wheel-ok')) { commit(); return; }
      if (e.target === el) { close(); }
    });
    // Block background page scroll/rubber-band on touch outside the columns.
    el.addEventListener('touchmove', function(e){
      if (!(e.target.closest && e.target.closest('.aot-wheel-col'))) { e.preventDefault(); }
    }, { passive: false });
  }

  function tr(key, fallback){
    try { return (typeof window._ === 'function') ? window._(key) : fallback; }
    catch (e) { return fallback; }
  }

  function open(opts){
    opts = opts || {};
    ensureEl();
    var fields = (opts.fields === 'hm') ? 'hm' : 'hms';   // 'hm' hides the seconds column
    target = { onConfirm: opts.onConfirm, max: (typeof opts.max === 'number' ? opts.max : HMS_MAX), fields: fields };
    el.querySelector('.aot-wheel-title').textContent = opts.title || tr('Time', 'Time');
    el.querySelector('.aot-wheel-cancel').textContent = tr('Cancel', 'Cancel');
    el.querySelector('.aot-wheel-reset').textContent = tr('Reset', 'Reset');
    el.querySelector('.aot-wheel-ok').textContent = tr('Save', 'Save');
    // Show/hide the seconds column + its separator per mode
    var ssCol = colByName('ss');
    var ssSep = el.querySelector('.aot-wheel-sep-ss');
    var hide = (fields === 'hm');
    if (ssCol) { ssCol.style.display = hide ? 'none' : ''; }
    if (ssSep) { ssSep.style.display = hide ? 'none' : ''; }

    var total = clampSec(toSeconds(opts.value), target.max);
    var hh = Math.floor(total / 3600);
    var mm = Math.floor((total % 3600) / 60);
    var ss = total % 60;

    el.classList.add('is-open');
    document.body.classList.add('aot-wheel-lock');
    requestAnimationFrame(function(){
      scrollToVal(colByName('hh'), hh, false);
      scrollToVal(colByName('mm'), mm, false);
      if (!hide) { scrollToVal(ssCol, ss, false); }
    });
  }
  function close(){
    if (el) { el.classList.remove('is-open'); }
    document.body.classList.remove('aot-wheel-lock');
    target = null;
  }
  function reset(){
    if (!target || !el) { return; }
    var hm = (target.fields === 'hm');
    scrollToVal(colByName('hh'), 0, true);
    scrollToVal(colByName('mm'), 0, true);
    if (!hm) { scrollToVal(colByName('ss'), 0, true); }
  }
  function commit(){
    if (!target || !el) { close(); return; }
    var hm = (target.fields === 'hm');
    var hh = selectedVal(colByName('hh'));
    var mm = selectedVal(colByName('mm'));
    var ss = hm ? 0 : selectedVal(colByName('ss'));
    var total = clampSec((hh * 3600) + (mm * 60) + ss, target.max);
    var cb = target.onConfirm;
    var display = hm ? (pad2(hh) + ':' + pad2(mm)) : toHMS(total);
    close();
    if (typeof cb === 'function') { cb(total, display); }
  }

  // Embed the wheel INLINE into a container (no overlay, no buttons) so it can
  // live inside another panel. Returns a handle with read() -> total seconds.
  function mountInline(container, opts){
    if (!container) { return null; }
    opts = opts || {};
    var fields = (opts.fields === 'hm') ? 'hm' : 'hms';
    var max = (typeof opts.max === 'number') ? opts.max : HMS_MAX;
    var hide = (fields === 'hm');
    container.innerHTML =
      '<div class="aot-wheel-cols">' +
        buildColumn('hh', 24) +
        '<span class="aot-wheel-sep">:</span>' +
        buildColumn('mm', 60) +
        '<span class="aot-wheel-sep aot-wheel-sep-ss">:</span>' +
        buildColumn('ss', 60) +
        '<div class="aot-wheel-band"></div>' +
      '</div>';
    var wrap = container.querySelector('.aot-wheel-cols');
    var cols = wrap.querySelectorAll('.aot-wheel-col');
    for (var i = 0; i < cols.length; i++){
      cols[i]._items = cols[i].querySelectorAll('.aot-wheel-item');
      cols[i]._count = parseInt(cols[i].getAttribute('data-count'), 10);
      cols[i]._range = null;
    }
    var byName = function(n){ return wrap.querySelector('.aot-wheel-col[data-col="' + n + '"]'); };
    var lsnap = {}, lraf = {};
    Array.prototype.forEach.call(cols, function(col){
      col.addEventListener('scroll', function(){
        var key = col.getAttribute('data-col');
        loopRecenter(col);
        if (!lraf[key]) { lraf[key] = requestAnimationFrame(function(){ lraf[key] = null; render(col); }); }
        if (lsnap[key]) { clearTimeout(lsnap[key]); }
        lsnap[key] = setTimeout(function(){ render(col); }, 90);
      });
      col.addEventListener('click', function(e){
        var item = e.target.closest && e.target.closest('.aot-wheel-item');
        if (item) { var raw = parseInt(item.getAttribute('data-idx'), 10); col.scrollTo ? col.scrollTo({ top: raw * ITEM_H, behavior: 'smooth' }) : (col.scrollTop = raw * ITEM_H); }
      });
    });
    var ssCol = byName('ss'), ssSep = wrap.querySelector('.aot-wheel-sep-ss');
    if (ssCol) { ssCol.style.display = hide ? 'none' : ''; }
    if (ssSep) { ssSep.style.display = hide ? 'none' : ''; }
    var total = clampSec(toSeconds(opts.value), max);
    var hh = Math.floor(total / 3600), mm = Math.floor((total % 3600) / 60), ss = total % 60;
    requestAnimationFrame(function(){
      scrollToVal(byName('hh'), hh, false);
      scrollToVal(byName('mm'), mm, false);
      if (!hide) { scrollToVal(ssCol, ss, false); }
    });
    return {
      read: function(){
        var h = selectedVal(byName('hh')), m = selectedVal(byName('mm')), s = hide ? 0 : selectedVal(byName('ss'));
        return clampSec((h * 3600) + (m * 60) + s, max);
      }
    };
  }

  window.AoTTimeWheel = {
    open: open,
    close: close,
    mount: mountInline,
    toSeconds: toSeconds,
    toHMS: toHMS
  };
})();
