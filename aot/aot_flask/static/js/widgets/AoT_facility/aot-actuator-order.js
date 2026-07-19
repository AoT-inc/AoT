// aot-actuator-order.js
// Shared actuator/device control-list ordering for AoT facility lists.
//
// Used by three renderers that all display the same per-facility actuators:
//   · aot-map-popup.js            (AoT_map facility actuator popup)
//   · aot-facility-actuator-panel.js (grouped actuator panel)
//   · aot-facility-control-grid.js   (IEC § D control grid)
//
// Ordering policy:
//   1. Default sort = letters → numbers (natural sort). 'win2' < 'win10'.
//   2. When the user drag-reorders, the order is saved on the server per facility (view_options.actuator_order).
//   3. If a saved order exists, use it; newly added slots are appended after it in natural-sort order.
//
// Saved order is a FLAT list of slot_keys shared by every list of one facility.
//
// Public API: window.AoTActuatorOrder = {
//   naturalCompare(a, b)
//   order(allSlots, savedOrder, nameOf)            → full ordered slot list
//   reorder(allSlots, savedOrder, nameOf, newSeq)  → new full order to persist
//   makeSortable(containerEl, opts)
//   save(facilityUuid, order)                      → Promise
//   getCache(facilityUuid) / setCache(facilityUuid, order)
// }
(function () {
  'use strict';

  // facility_uuid → [slot_key, ...]  (last known saved order, updated on save)
  var _cache = {};

  function getCache(facilityUuid) {
    return _cache[facilityUuid] || null;
  }
  function setCache(facilityUuid, order) {
    if (facilityUuid) _cache[facilityUuid] = Array.isArray(order) ? order.slice() : null;
  }

  // ── Natural alphanumeric compare (letters → numbers) ───────────────────────────────
  // Splits each string into alternating text / number chunks so that numeric
  // chunks compare by value (win2 < win10) and text chunks compare lexically.
  function naturalCompare(a, b) {
    a = String(a == null ? '' : a);
    b = String(b == null ? '' : b);
    var re = /(\d+)|(\D+)/g;
    var ax = a.toLowerCase().match(re) || [];
    var bx = b.toLowerCase().match(re) || [];
    for (var i = 0; i < ax.length && i < bx.length; i++) {
      var an = ax[i], bn = bx[i];
      var aNum = /^\d/.test(an), bNum = /^\d/.test(bn);
      if (aNum && bNum) {
        var d = parseInt(an, 10) - parseInt(bn, 10);
        if (d !== 0) return d;
      } else if (an !== bn) {
        return an < bn ? -1 : 1;
      }
    }
    return ax.length - bx.length;
  }

  // ── order ───────────────────────────────────────────────────────────────────
  // Build the authoritative full ordering of allSlots:
  //   · slots present in savedOrder first, in saved sequence
  //   · remaining slots appended, natural-sorted by display name
  //   nameOf(slot) → display string used for the natural fallback sort.
  function order(allSlots, savedOrder, nameOf) {
    var present = {};
    (allSlots || []).forEach(function (s) { present[s] = true; });
    var seen = {};
    var out = [];

    (savedOrder || []).forEach(function (s) {
      if (present[s] && !seen[s]) { out.push(s); seen[s] = true; }
    });

    var rest = (allSlots || []).filter(function (s) { return !seen[s]; });
    rest.sort(function (a, b) {
      return naturalCompare(
        nameOf ? nameOf(a) : a,
        nameOf ? nameOf(b) : b
      );
    });
    return out.concat(rest);
  }

  // ── reorder ───────────────────────────────────────────────────────────────
  // The user dragged the slots of ONE list into newSeq. Produce a new full
  // order to persist: only the dragged slots move — they are re-slotted into
  // the positions they previously occupied within the full order, so slots
  // belonging to other lists/groups keep their absolute positions.
  function reorder(allSlots, savedOrder, nameOf, newSeq) {
    var full = order(allSlots, savedOrder, nameOf);
    var inSeq = {};
    (newSeq || []).forEach(function (s) { inSeq[s] = true; });

    var positions = [];
    for (var i = 0; i < full.length; i++) {
      if (inSeq[full[i]]) positions.push(i);
    }
    // Assign the new sequence into those positions, preserving count alignment.
    for (var k = 0; k < positions.length && k < newSeq.length; k++) {
      full[positions[k]] = newSeq[k];
    }
    return full;
  }

  // ── makeSortable ────────────────────────────────────────────────────────────
  // Pointer-based drag-reordering of rows inside containerEl. Starts only from the
  // handle (horizontal 2-line grip). HTML5 native DnD can conflict with widget movement
  // or fail to start in the gridstack widget / map popup context, so it's implemented
  // directly with pointer events.
  //   opts.itemSelector    default '[data-slot]'
  //   opts.handleSelector  drag-start handle (default '.aot-act-drag-handle')
  //   opts.groupSelector   optional — reorder only within the same group
  //   opts.onReorder(newSeq)  called on drop with the new slot order of the affected scope (group/container)
  //
  // Listeners are delegated to the container, so one binding suffices even when rows re-render on polling.
  function makeSortable(containerEl, opts) {
    opts = opts || {};
    if (!containerEl || containerEl._aotSortableBound) return;
    containerEl._aotSortableBound = true;

    var itemSel   = opts.itemSelector  || '[data-slot]';
    var handleSel = opts.handleSelector || '.aot-act-drag-handle';
    var groupSel  = opts.groupSelector || null;

    var dragEl = null;
    var scopeEl = null;

    function _y(e) {
      return (e.touches && e.touches[0]) ? e.touches[0].clientY : e.clientY;
    }

    function _onDown(e) {
      // Left-click/touch only. Acts only when started from the handle.
      if (e.type === 'mousedown' && e.button !== 0) return;
      var handle = e.target.closest(handleSel);
      if (!handle || !containerEl.contains(handle)) return;
      var item = handle.closest(itemSel);
      if (!item || !containerEl.contains(item)) return;

      e.preventDefault();
      e.stopPropagation();   // block propagation to gridstack widget move/resize

      dragEl  = item;
      scopeEl = groupSel ? (item.closest(groupSel) || containerEl) : containerEl;
      item.classList.add('aot-act-dragging');

      document.addEventListener('mousemove', _onMove, true);
      document.addEventListener('mouseup',   _onUp,   true);
      document.addEventListener('touchmove', _onMove, { passive: false, capture: true });
      document.addEventListener('touchend',  _onUp,   true);
    }

    function _onMove(e) {
      if (!dragEl) return;
      e.preventDefault();
      var y = _y(e);
      var rows = scopeEl.querySelectorAll(itemSel);
      for (var i = 0; i < rows.length; i++) {
        var s = rows[i];
        if (s === dragEl) continue;
        var r = s.getBoundingClientRect();
        if (y >= r.top && y <= r.bottom) {
          var after = y > (r.top + r.height / 2);
          s.parentNode.insertBefore(dragEl, after ? s.nextSibling : s);
          break;
        }
      }
    }

    function _onUp() {
      if (!dragEl) return;
      document.removeEventListener('mousemove', _onMove, true);
      document.removeEventListener('mouseup',   _onUp,   true);
      document.removeEventListener('touchmove', _onMove, true);
      document.removeEventListener('touchend',  _onUp,   true);

      dragEl.classList.remove('aot-act-dragging');
      var scope = scopeEl;
      dragEl = null;
      scopeEl = null;

      if (typeof opts.onReorder === 'function' && scope) {
        var seq = [].map.call(scope.querySelectorAll(itemSel), function (el) {
          return el.dataset.slot;
        }).filter(Boolean);
        opts.onReorder(seq);
      }
    }

    containerEl.addEventListener('mousedown',  _onDown);
    containerEl.addEventListener('touchstart', _onDown, { passive: false });
  }

  // ── save ────────────────────────────────────────────────────────────────────
  function _csrf() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return (meta && meta.getAttribute('content')) || '';
  }

  function save(facilityUuid, orderList) {
    setCache(facilityUuid, orderList);
    return fetch('/api/aot/facility/' + encodeURIComponent(facilityUuid) + '/actuator_order', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': _csrf() },
      body:    JSON.stringify({ order: orderList || [] }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (!d || !d.ok) console.warn('[ActuatorOrder] save failed', d && d.message); return d; })
      .catch(function (e) { console.error('[ActuatorOrder] save error', e); });
  }

  window.AoTActuatorOrder = {
    naturalCompare: naturalCompare,
    order:          order,
    reorder:        reorder,
    makeSortable:   makeSortable,
    save:           save,
    getCache:       getCache,
    setCache:       setCache,
  };
})();
