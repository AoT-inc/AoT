/**
 * aot-scale-input.js
 *
 * 정할 수 없는 숫자를 **눈금**으로 묻는다. `AoTViz` 의 입력형이다.
 * 설계: `docs/design/env-coordinator-settings-redesign.md` §3-5 (단계 C′).
 *
 * ## 왜
 *
 * `emergency_deviation_mult` 에 3.0 을 넣을지 4.0 을 넣을지 사용자는 **답할 수
 * 없다.** 빈칸에 숫자를 요구하면 아무것도 못 하거나 아무 값이나 넣는다. 눈금은
 * 답할 수 있는 질문("느긋하게 ↔ 민감하게")으로 바꾼다.
 *
 * ## ⚠ 저장은 **실제 값** 하나다 — 단계 이름을 저장하지 않는다
 *
 * `actuation_profile` 이 정확히 그 실수를 했다: 모드 문자열과 숫자를 따로
 * 저장해 둘이 어긋났고, 쿠마모토의 `actuation_period_sec=1200` 은 실제로는
 * 쓰이지 않는 죽은 값이었다(profile 이 'gentle' 이라 코드가 그 칸을 안 봤다).
 *
 * 그래서 여기서는 **폼 필드가 하나뿐**이다 — 원래의 숫자 input. 눈금은 그
 * 위에 얹힌 조작기이고, 누르면 그 input 의 값을 바꾼다. 어긋날 두 번째 값이
 * 없다.
 *
 * 값이 어느 단계와도 안 맞으면 '직접 지정' 으로 보인다 — 눈금을 없애지 않는다.
 * 없애면 직접 지정에서 되돌아올 길이 사라진다.
 */
(function () {
  'use strict';

  function _t(s) { return window._ ? window._(s) : s; }
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;',
              '"': '&quot;', "'": '&#39;'}[c];
    });
  }

  function steps(el) {
    try {
      return JSON.parse(el.getAttribute('data-steps') || '[]');
    } catch (e) { return []; }
  }

  /** 현재 값이 어느 단계인가 → index | -1(직접 지정). */
  function pickedIndex(list, value) {
    for (var i = 0; i < list.length; i++) {
      if (Number(list[i][0]) === Number(value)) return i;
    }
    return -1;
  }

  function render(el) {
    var input = el._input;
    var list  = el._steps;
    var value = Number(input.value);
    var idx   = pickedIndex(list, value);
    var lo    = el.getAttribute('data-axis-low')  || '';
    var hi    = el.getAttribute('data-axis-high') || '';
    var unit  = el.getAttribute('data-unit') || '';

    var label = (idx >= 0) ? list[idx][1] : _t('Custom');
    var shown = isFinite(value) ? (value + (unit ? ' ' + unit : '')) : '';

    var html = '<div class="aot-viz aot-viz--band aot-viz--scale-input' +
               (idx < 0 ? ' aot-viz--custom' : '') + '">';
    html += '<div class="aot-viz-head">' +
            '<span class="aot-viz-label">' + esc(el._label) + '</span>' +
            '<span class="aot-viz-value">' + esc(label) +
            (shown ? ' <small>' + esc(shown) + '</small>' : '') +
            '</span></div>';
    html += '<div class="aot-viz-track">';
    for (var i = 0; i < list.length; i++) {
      var p = list.length > 1 ? (i * 100 / (list.length - 1)) : 50;
      html += '<button type="button" class="aot-viz-step' +
              (i === idx ? ' is-picked' : '') +
              '" style="--aot-viz-pos:' + p.toFixed(2) + '"' +
              ' data-i="' + i + '" title="' + esc(list[i][1]) + '"' +
              ' aria-label="' + esc(list[i][1]) + '"></button>';
    }
    html += '</div>';
    // 양 끝은 **트레이드오프**다. "약하게/강하게" 만으로는 무엇이 강해지는지
    // 모른다 — 사용자가 이해하는 두 가지 사이의 축이어야 한다.
    if (lo || hi) {
      html += '<div class="aot-viz-scale"><span>' + esc(lo) +
              '</span><span class="aot-viz-scale-note">' + esc(hi) +
              '</span></div>';
    }
    html += '</div>';
    el._view.innerHTML = html;
  }

  /* ── 핵심 옵션(그룹) ──────────────────────────────────────────────────
   * 로봇 청소기의 운전모드다 — 한 번 고르면 그 그룹의 세부 값이 함께 바뀐다.
   *
   * ⚠ **그룹 선택을 저장하지 않는다.** 폼 필드는 여전히 세부 옵션들뿐이고,
   *   지금 어느 단계인지는 **그 값들에서 되짚는다**. 모드를 따로 저장하면
   *   둘이 어긋나고, 어긋나면 어느 쪽이 이기는지 화면에 안 보인다
   *   (`actuation_profile` 이 그 실수를 했다).
   * ⚠ 되짚기라서 어느 단계와도 안 맞으면 **'직접 지정'** 이다. 세부 값을
   *   직접 고치면 자연히 그렇게 된다 — 그것이 정상이고, 사용자가 자기 결정을
   *   덮어쓰이지 않았다는 신호이기도 하다.
   */
  function memberInput(el, oid) {
    return document.getElementById((el.getAttribute('data-prefix') || '') + oid);
  }

  function sameValue(a, b) {
    var na = Number(a), nb = Number(b);
    if (isFinite(na) && isFinite(nb)) return na === nb;
    return String(a) === String(b);
  }

  /** 지금 값들이 어느 단계인가 → index | -1. */
  function groupIndex(el) {
    var list = el._steps;
    for (var i = 0; i < list.length; i++) {
      var vals = list[i][1], ok = true;
      for (var oid in vals) {
        var inp = memberInput(el, oid);
        // 그 옵션이 이 화면에 없으면 **판정에서 뺀다** — 없는 것을 불일치로
        // 세면 어떤 단계와도 안 맞아 늘 '직접 지정' 이 된다.
        if (!inp) continue;
        if (!sameValue(inp.value, vals[oid])) { ok = false; break; }
      }
      if (ok) return i;
    }
    return -1;
  }

  function renderGroup(el) {
    var list = el._steps;
    var idx  = groupIndex(el);
    var lo   = el.getAttribute('data-axis-low')  || '';
    var hi   = el.getAttribute('data-axis-high') || '';
    var hint = el.getAttribute('data-hint') || '';

    var html = '<div class="aot-viz aot-viz--band aot-viz--scale-input' +
               (idx < 0 ? ' aot-viz--custom' : '') + '">';
    html += '<div class="aot-viz-head">' +
            '<span class="aot-viz-label">' + esc(el._label) + '</span>' +
            '<span class="aot-viz-value">' +
            esc(idx >= 0 ? list[idx][0] : _t('Custom')) + '</span></div>';
    html += '<div class="aot-viz-track">';
    for (var i = 0; i < list.length; i++) {
      var p = list.length > 1 ? (i * 100 / (list.length - 1)) : 50;
      html += '<button type="button" class="aot-viz-step' +
              (i === idx ? ' is-picked' : '') +
              '" style="--aot-viz-pos:' + p.toFixed(2) + '"' +
              ' data-i="' + i + '" title="' + esc(list[i][0]) + '"' +
              ' aria-label="' + esc(list[i][0]) + '"></button>';
    }
    html += '</div>';
    if (lo || hi) {
      html += '<div class="aot-viz-scale"><span>' + esc(lo) +
              '</span><span class="aot-viz-scale-note">' + esc(hi) +
              '</span></div>';
    }
    if (hint) {
      html += '<div class="aot-modal-body-text aot-scale-hint">' +
              esc(hint) + '</div>';
    }
    el._view.innerHTML = html + '</div>';
  }

  function wireGroup(el) {
    el._steps = steps(el);
    el._label = el.getAttribute('data-label') || '';
    el._view  = ensureView(el);

    el._view.addEventListener('click', function (ev) {
      var b = ev.target.closest('.aot-viz-step');
      if (!b) return;
      ev.preventDefault();
      var vals = (el._steps[Number(b.getAttribute('data-i'))] || [])[1];
      if (!vals) return;
      for (var oid in vals) {
        var inp = memberInput(el, oid);
        if (!inp) continue;              // 없는 옵션은 건너뛴다
        inp.value = vals[oid];
        // 세부 옵션의 **자기 이벤트**로 알린다 — 그 값에 붙은 다른 장치
        // (개별 눈금·`depends_on`)가 그것을 듣고 있다.
        inp.dispatchEvent(new Event('change', {bubbles: true}));
      }
      renderGroup(el);
    });

    // 세부 값을 직접 고치면 핵심 옵션이 따라온다 — 두 표현이 같은 값을 본다.
    el._steps.forEach(function (st) {
      for (var oid in st[1]) {
        var inp = memberInput(el, oid);
        if (!inp || inp._aotGroupWatched) continue;
        inp._aotGroupWatched = true;
        var run = function () { renderGroup(el); };
        inp.addEventListener('change', run);
        inp.addEventListener('input', run);
      }
    });
    renderGroup(el);
  }

  function ensureView(el) {
    var view = el.querySelector(':scope > .aot-scale-view');
    if (!view) {
      view = document.createElement('div');
      view.className = 'aot-scale-view';
      el.appendChild(view);
    }
    return view;
  }

  function wire(el) {
    if (el._aotScaleWired) return;
    if (el.classList.contains('aot-scale-group')) {
      el._aotScaleWired = true;
      wireGroup(el);
      return;
    }
    var id = el.getAttribute('data-for');
    var input = id ? document.getElementById(id) : null;
    // ⚠ 대상 숫자 칸이 없으면 **아무것도 하지 않는다.** 눈금만 그리면 누를
    //   때마다 아무 데도 안 쓰이는 조작이 된다.
    if (!input) return;
    el._aotScaleWired = true;
    el._input = input;
    el._steps = steps(el);
    el._label = el.getAttribute('data-label') || '';

    // ⚠ 뷰를 **다시 만들지 않는다**(`ensureView`). `init` 은 설정 폼이 나중에
    //   DOM 에 꽂힐 때 다시 불린다 — 그때마다 append 하면 같은 눈금이 두 벌
    //   그려지고, 두 번째를 눌러도 첫 번째가 안 바뀌어 "눌러도 안 먹는다".
    el._view = ensureView(el);

    el._view.addEventListener('click', function (ev) {
      var b = ev.target.closest('.aot-viz-step');
      if (!b) return;
      ev.preventDefault();
      var i = Number(b.getAttribute('data-i'));
      if (!el._steps[i]) return;
      input.value = el._steps[i][0];
      // 원래 칸이 진짜 값이다 — 바뀐 것을 그 칸의 이벤트로 알린다
      // (`depends_on` 같은 다른 장치가 그 이벤트를 듣고 있다).
      input.dispatchEvent(new Event('change', {bubbles: true}));
      render(el);
    });
    // 숫자 칸을 직접 고쳐도 눈금이 따라온다 — 두 표현이 같은 값을 본다.
    input.addEventListener('change', function () { render(el); });
    input.addEventListener('input',  function () { render(el); });
    render(el);
  }

  /* ── [고급] 스위치 ────────────────────────────────────────────────────
   * 눈금은 **요약**이고 숫자 칸은 그 값이다. 정밀하게 고치려는 사람이 값을
   * 다른 화면에서 찾게 하면 요약과 값이 갈라진다(설계문서 D6).
   *
   * ⚠ **옵션마다 토글을 두지 않는다** — 51개면 토글이 51개다. 화면 하나의
   *   스위치가 모든 눈금에 숫자 칸을 함께 연다.
   * ⚠ **한 번에 펼친다**(D13) — 고급을 켰는데 또 세부 메뉴를 열라고 하면
   *   스위치가 일을 절반만 한 것이다. 접힌 묶음도 같이 연다.
   * ⚠ 상태는 **브라우저에만** 둔다. 설정으로 저장하면 "이 함수는 고급 모드"
   *   라는 없던 상태가 생기고, 같은 화면을 두 사람이 다르게 본다.
   */
  var KEY = 'aot_scale_advanced';

  function applyAdvanced(form, on) {
    form.classList.toggle('aot-advanced', on);
    if (on) {
      form.querySelectorAll('.collapse:not(.show)').forEach(function (c) {
        c.classList.add('show');
        var a = document.querySelector('[href="#' + c.id + '"]');
        if (a) a.classList.remove('collapsed');
      });
    }
  }

  function ensureSwitch(form) {
    if (form._aotAdvWired) return;
    form._aotAdvWired = true;
    var host = form.querySelector('.aot-scale-input');
    if (!host) return;
    var on = false;
    try { on = window.localStorage.getItem(KEY) === '1'; } catch (e) { on = false; }

    var row = document.createElement('div');
    row.className = 'aot-modal-option-row aot-advanced-switch';
    row.innerHTML =
      '<div class="aot-modal-option-label">' + esc(_t('Advanced')) + '</div>' +
      '<div class="aot-modal-option-control"><label class="btn-toggle mb-0">' +
      '<input type="checkbox" class="btn-toggle-input aot-advanced-input"' + (on ? ' checked' : '') +
      '><div class="btn-toggle-slider"></div></label></div>';
    var anchor = host.closest('.aot-modal-option-row') || host;
    var box = anchor.parentNode;
    box.insertBefore(row, box.firstChild);

    var cb = row.querySelector('input');
    cb.addEventListener('change', function () {
      try { window.localStorage.setItem(KEY, cb.checked ? '1' : '0'); }
      catch (e) { /* 저장 못 해도 이번 화면에서는 동작한다 */ }
      applyAdvanced(form, cb.checked);
    });
    applyAdvanced(form, on);
  }

  function init(root) {
    var scope = root || document;
    scope.querySelectorAll('.aot-scale-input').forEach(wire);
    scope.querySelectorAll('form').forEach(function (f) {
      if (f.querySelector('.aot-scale-input')) ensureSwitch(f);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); });
  } else {
    init();
  }
  window.AoTScaleInput = {init: init};
})();
