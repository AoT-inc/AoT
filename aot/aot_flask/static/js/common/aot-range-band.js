/**
 * aot-range-band.js
 *
 * **권장 범위만 끈다. 넘으면 안 되는 선은 거기서 파생한다.** `AoTViz.band` 의 입력형.
 * 설계: `docs/design/env-coordinator-settings-redesign.md` §3-5.
 *
 * ## 왜
 *
 * 온도만 해도 네 칸이었다 — 하한·상한(넘으면 안 되는 선)과 권장 하한·상한.
 * 그런데 사용자가 **답할 수 있는 질문은 하나뿐**이다: "이 작물을 몇 도에서
 * 몇 도로 기를 것인가." 넘으면 안 되는 선은 그 범위에서 여유를 둔 값이지,
 * 따로 생각해서 넣는 값이 아니다.
 *
 * 그래서 손잡이는 **둘**이고(권장 하한·상한), 하드 임계는 ∓여유로 따라온다.
 *
 *     10   ░░░░ 15 ▓▓▓▓▓ 권장 ▓▓▓▓▓ 30 ░░░░   40 °C
 *          └ 여유 ┘                  └ 여유 ┘
 *
 * 이렇게 하면 권장 범위가 하드 임계 밖으로 나가는 상태가 **만들어지지 않는다** —
 * 그것을 알리려고 저장 시 경고까지 만들어야 했던 문제가 사라진다(2026-08-26).
 *
 * ## ⚠ 저장은 그대로 **숫자 네 칸**이다
 *
 * 이 컨트롤은 그 칸들 위에 얹힌 조작기다. 따로 저장하는 값이 없으므로 어긋날
 * 두 번째 값이 없다(`actuation_profile` 의 실수를 반복하지 않는다).
 */
(function () {
  'use strict';

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;',
              '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function num(v, d) { var n = Number(v); return isFinite(n) ? n : d; }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  /* 저장되는 값은 넷이지만 **끄는 것은 둘**이다 — 권장 하한·상한.
   * 넘으면 안 되는 선은 거기서 ∓여유로 따라온다. 사용자가 답할 수 있는
   * 질문은 "몇 도에서 몇 도로 기를 것인가" 하나이기 때문이다. */
  var ORDER = ['hardMin', 'guideMin', 'guideMax', 'hardMax'];
  var DRAG  = ['guideMin', 'guideMax'];

  function inputs(el) {
    var pre = el.getAttribute('data-prefix') || '';
    var map = {};
    ORDER.forEach(function (k) {
      var oid = el.getAttribute('data-' + k.toLowerCase());
      map[k] = oid ? document.getElementById(pre + oid) : null;
    });
    return map;
  }

  function values(el) {
    var m = el._inputs, v = {};
    ORDER.forEach(function (k) { v[k] = m[k] ? num(m[k].value, null) : null; });
    return v;
  }

  function limitsFor(el, key, v) {
    // 끄는 것은 권장 둘뿐이다 — 서로를 넘지 못하게만 막는다. 미는 것이 아니라
    // **막는 것**이다: 미는 쪽이 편해 보이지만, 손을 놓고 보면 건드린 적 없는
    // 값이 바뀌어 있다. 여유만큼은 축 안에 남겨 하드가 따라올 자리를 둔다.
    var m = el._margin;
    if (key === 'guideMin') {
      return [el._min + m, v.guideMax != null ? v.guideMax : el._max - m];
    }
    return [v.guideMin != null ? v.guideMin : el._min + m, el._max - m];
  }

  function pct(el, value) {
    return clamp((value - el._min) / (el._max - el._min) * 100, 0, 100);
  }

  function render(el) {
    var v = values(el);
    var unit = el.getAttribute('data-unit') || '';
    var hs = v.hardMin, he = v.hardMax, gs = v.guideMin, ge = v.guideMax;

    var html = '<div class="aot-viz aot-viz--band aot-viz--range-band">';
    html += '<div class="aot-viz-head"><span class="aot-viz-label">' +
            esc(el._label) + '</span><span class="aot-viz-value">' +
            esc((gs != null ? gs : '?') + '~' + (ge != null ? ge : '?') + unit) +
            (hs != null && he != null
               ? ' <small>' + esc(el._hardLabel + ' ' + hs + '~' + he + unit) +
                 '</small>'
               : '') +
            '</span></div>';
    html += '<div class="aot-viz-track">';
    if (hs != null && he != null) {
      html += '<div class="aot-viz-ok aot-viz-ok--hard" style="left:' +
              pct(el, hs).toFixed(2) + '%;width:' +
              (pct(el, he) - pct(el, hs)).toFixed(2) + '%"></div>';
    }
    if (gs != null && ge != null) {
      html += '<div class="aot-viz-ok aot-viz-ok--guide" style="left:' +
              pct(el, gs).toFixed(2) + '%;width:' +
              (pct(el, ge) - pct(el, gs)).toFixed(2) + '%"></div>';
    }
    DRAG.forEach(function (k) {
      if (v[k] == null) return;
      html += '<button type="button" class="aot-viz-step is-picked aot-viz-handle' +
              (k.indexOf('guide') === 0 ? ' is-guide' : '') +
              '" data-k="' + k + '" style="--aot-viz-pos:' +
              pct(el, v[k]).toFixed(2) + '" title="' + esc(v[k] + unit) +
              '" aria-label="' + esc(el._names[k] + ' ' + v[k] + unit) + '"></button>';
    });
    html += '</div>';
    html += '<div class="aot-viz-scale"><span>' + esc(el._min + unit) +
            '</span><span class="aot-viz-scale-note">' + esc(el._max + unit) +
            '</span></div>';
    el._view.innerHTML = html + '</div>';
  }

  /* ⚠ **한계는 언제나 권장을 따라온다.**
   *
   * 처음에는 "사용자가 하드를 직접 고쳤으면 안 따라온다" 로 만들었는데,
   * 기존 설치의 하드 값이 이미 `권장 ∓ 여유` 와 다르면(쿠마모토: 권장 12~32 ·
   * 하드 5~35) **처음부터 안 따라와서 기능이 죽은 것처럼 보였다.**
   *
   * 한계는 이 컨트롤이 **파생하는 값**이다 — 사용자가 답한 질문은 "몇 도에서
   * 몇 도로 기를 것인가" 하나이고, 한계는 거기서 여유를 둔 결과다. 독립적인
   * 값이 필요하면 [고급] 에서 고치면 되고, 다음에 권장을 끌면 다시 파생된다.
   * 그 사실을 힌트로 말한다 — 조용히 덮어쓰지 않는다.
   */

  function write(el, key, value) {
    var inp = el._inputs[key];
    if (!inp) return;
    var next = Math.round(value * 1e6) / 1e6;
    if (String(inp.value) === String(next)) return;
    inp.value = next;
    inp.dispatchEvent(new Event('change', {bubbles: true}));
  }

  function setValue(el, key, value) {
    if (!el._inputs[key]) return;
    var v = values(el);
    var lim = limitsFor(el, key, v);
    var step = el._step;
    var next = clamp(Math.round(value / step) * step, lim[0], lim[1]);
    next = Math.round(next * 1e6) / 1e6;
    write(el, key, next);
    var m = el._margin;
    if (key === 'guideMin') write(el, 'hardMin', clamp(next - m, el._min, el._max));
    if (key === 'guideMax') write(el, 'hardMax', clamp(next + m, el._min, el._max));
  }

  function wire(el) {
    if (el._aotRangeWired) return;
    el._inputs = inputs(el);
    // 하나라도 있어야 의미가 있다. 전부 없으면 **아무것도 그리지 않는다** —
    // 조작해도 아무 데도 안 쓰이는 컨트롤을 남기지 않는다.
    if (!DRAG.every(function (k) { return el._inputs[k]; })) return;
    el._aotRangeWired = true;
    el._min = num(el.getAttribute('data-min'), 0);
    el._max = num(el.getAttribute('data-max'), 100);
    el._step = num(el.getAttribute('data-step'), 1) || 1;
    el._label = el.getAttribute('data-label') || '';
    el._hardLabel = el.getAttribute('data-hard-label') || '';
    el._margin = num(el.getAttribute('data-margin'), 5);
    el._names = {
      hardMin: el.getAttribute('data-name-hardmin') || '',
      hardMax: el.getAttribute('data-name-hardmax') || '',
      guideMin: el.getAttribute('data-name-guidemin') || '',
      guideMax: el.getAttribute('data-name-guidemax') || ''
    };

    var view = el.querySelector(':scope > .aot-range-view');
    if (!view) {
      view = document.createElement('div');
      view.className = 'aot-range-view';
      el.appendChild(view);
    }
    el._view = view;

    var dragging = null;
    function posToValue(clientX) {
      var t = view.querySelector('.aot-viz-track');
      var r = t.getBoundingClientRect();
      var f = clamp((clientX - r.left) / r.width, 0, 1);
      return el._min + f * (el._max - el._min);
    }
    view.addEventListener('pointerdown', function (ev) {
      var h = ev.target.closest('.aot-viz-handle');
      if (!h) return;
      dragging = h.getAttribute('data-k');
      h.setPointerCapture && h.setPointerCapture(ev.pointerId);
      ev.preventDefault();
    });
    view.addEventListener('pointermove', function (ev) {
      if (!dragging) return;
      setValue(el, dragging, posToValue(ev.clientX));
      render(el);
    });
    var stop = function () { dragging = null; };
    view.addEventListener('pointerup', stop);
    view.addEventListener('pointercancel', stop);
    // 키보드로도 움직인다 — 끌기만 되면 손이 불편한 사람이 쓸 수 없다.
    view.addEventListener('keydown', function (ev) {
      var h = ev.target.closest('.aot-viz-handle');
      if (!h) return;
      var d = {ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1}[ev.key];
      if (!d) return;
      ev.preventDefault();
      var k = h.getAttribute('data-k');
      setValue(el, k, num(el._inputs[k].value, 0) + d * el._step);
      render(el);
      var again = view.querySelector('[data-k="' + k + '"]');
      if (again) again.focus();
    });

    // 숫자 칸을 직접 고쳐도 트랙이 따라온다.
    ORDER.forEach(function (k) {
      var inp = el._inputs[k];
      if (!inp) return;
      var run = function () { render(el); };
      inp.addEventListener('change', run);
      inp.addEventListener('input', run);
    });
    render(el);
  }

  function init(root) {
    (root || document).querySelectorAll('.aot-range-band').forEach(wire);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); });
  } else { init(); }
  window.AoTRangeBand = {init: init};
})();
