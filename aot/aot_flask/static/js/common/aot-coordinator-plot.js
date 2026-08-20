/**
 * aot-coordinator-plot.js
 *
 * 코디네이터가 따르는 구획과 **지금 적용 중인 단계 목표**를 보인다.
 * 읽기 전용이다 — 목표는 프로그램에서 오고 제어가 매 사이클 그것을 읽는다.
 *
 * 유일한 쓰기는 후보가 둘 이상일 때의 기준 구획 지정이다(간작·혼작이 정상이라
 * 서버가 임의로 고르지 않는다).
 * 정본: docs/design/coordinator-plot-targets.md
 */
(function () {
  'use strict';

  function _t(s) { return (window._ ? window._(s) : s); }

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function _csrf() {
    var el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute('content') : '';
  }

  function _num(v) {
    if (v == null) return '—';
    var n = Number(v);
    if (!isFinite(n)) return '—';
    // 정수는 정수로 — 0.9 는 0.9, 800 은 800(800.0 이 아니라).
    return (Math.abs(n - Math.round(n)) < 1e-9) ? String(Math.round(n)) : String(n);
  }

  // 후보가 없거나 정해지지 않은 이유를 **말한다.** 빈 칸으로 두면 사용자는
  // 화면이 덜 그려진 것인지 붙일 것이 없는 것인지 구분할 수 없다.
  function _reasonText(d) {
    if (d.reason === 'no-facility') {
      return _t('Link a facility to see what this coordinator is growing.');
    }
    if (d.reason === 'none') {
      return _t('No plot is being grown in this scope right now.');
    }
    if (d.reason === 'ambiguous') {
      return _t('More than one plot is here — pick which one this coordinator follows.');
    }
    if (d.reason === 'no-program') {
      return _t('This plot has no program, so there are no stage targets to follow.');
    }
    if (d.reason === 'program-unreviewed') {
      return _t('The program was drafted by AI and has not been reviewed, so control does not use it.');
    }
    if (d.reason === 'no-stage') {
      return _t('The program has no stage running on this date.');
    }
    return _t('No targets — the coordinator holds its safety range only.');
  }

  function _stateNote(state) {
    if (state === 'method') return _t('Follows a curve');
    if (state === 'unset') return _t('Not set');
    return '';
  }

  function _rowHtml(r) {
    var val = r.method_id
      ? '<span class="aot-ov-muted">' +
        _esc(r.method_name
             ? _t('Follows curve: {name}').replace('{name}', r.method_name)
             : _t('Follows a curve')) + '</span>'
      : _esc(_num(r.value) + (r.unit ? ' ' + r.unit : ''));
    return '<tr><td>' + _esc(r.label || r.key) + '</td><td>' + val + '</td></tr>';
  }

  // compact = 지도 위젯의 시설 모달. 그 화면에는 [구획] 블록이 이미 있어
  // 무엇이 자라는지 말하고 있으므로, 여기서는 **목표 대비**만 낸다. 같은 사실을
  // 두 블록이 각자 적으면 어느 쪽이 최신인지 사람이 판단해야 한다.
  function render(el, d) {
    var compact = el.getAttribute('data-compact') === '1';
    var html = '<div class="aot-coord-plot-title">' +
               _esc(compact ? _t('Targets in effect')
                            : _t('Plot this coordinator follows')) + '</div>';

    if (!d.plot) {
      // compact 는 빈 상태를 내지 않는다 — [구획] 블록이 이미 말한다.
      if (compact) { el.remove(); return; }
      html += '<div class="aot-coord-plot-note">' + _esc(_reasonText(d)) + '</div>';
      if (d.reason === 'ambiguous' && d.can_pick) {
        // 고를 수 없으면 안내가 막다른 길이 된다 — 그 자리에서 정하게 한다.
        (d.candidates || []).forEach(function (c) {
          html += '<div class="aot-coord-plot-cand">' +
                  '<span>' + _esc(c.subject || c.name || '') +
                  (c.program_name ? ' · ' + _esc(c.program_name) : '') + '</span>' +
                  '<button type="button" class="btn aot-pill-btn aot-coord-plot-pick"' +
                  ' data-plot="' + _esc(c.unique_id) + '">' +
                  _esc(_t('Follow this one')) + '</button></div>';
        });
      }
      el.innerHTML = html;
      if (compact) el.classList.add('aot-ov-block');
      _wirePick(el);
      return;
    }
    if (compact && !(d.targets || []).length && !(d.unmapped || []).length) {
      el.remove();
      return;                       // 보일 것이 없으면 자리를 차지하지 않는다
    }

    var p = d.plot;
    var line = (p.subject || p.name || '');
    if (p.variety) line += ' (' + p.variety + ')';
    if (d.stage && d.stage.name) {
      line += ' · ' + d.stage.name +
              (d.stage.index ? ' (' + d.stage.index + '/' + d.stage.total + ')' : '');
    }
    if (p.days_since_planted != null) {
      line += ' · ' + _t('Day {n}').replace('{n}', p.days_since_planted);
    }
    if (!compact) {
      html += '<div class="aot-coord-plot-line">' + _esc(line) + '</div>';
    }
    // 지정한 구획이 사라져도 그 사실을 말한다 — 조용히 다른 구획으로 갈아타면
    // 사람은 자기가 고른 것이 아직 쓰인다고 믿는다.
    if (d.pinned_missing) {
      html += '<div class="aot-coord-plot-note">' +
              _esc(_t('The plot you pinned is no longer here.')) + '</div>';
    }

    if ((d.targets || []).length) {
      html += '<table class="aot-coord-plot-table"><tbody>' +
              d.targets.map(_rowHtml).join('') + '</tbody></table>';
    } else {
      html += '<div class="aot-coord-plot-note">' +
              _esc(_reasonText(d)) + '</div>';
    }

    if ((d.unmapped || []).length) {
      // 이 코디네이터는 온도·습도를 목표로 쓰지 않는다(그 칸은 한계다). 숨기면
      // "왜 안 잡히지" 가 되므로 참고로 보이고 이유를 적는다.
      html += '<div class="aot-coord-plot-note">' +
              _esc(_t('For reference — this coordinator aims at VPD, so these are not settings here.')) +
              ' ' +
              d.unmapped.map(function (u) {
                return _esc((u.label || u.key) + ' ' + _num(u.value) +
                            (u.unit ? ' ' + u.unit : ''));
              }).join(' · ') + '</div>';
    }

    html += '<div class="aot-coord-plot-note">' +
            _esc(_t('Targets come from the program. Safety limits below stay with this facility.')) +
            '</div>';
    el.innerHTML = html;
    // 내용을 그렸을 때만 블록 테두리를 붙인다(빈 상자 방지 — 시설 모달의
    // 앵커는 클래스 없이 나온다).
    if (compact) el.classList.add('aot-ov-block');
  }

  function _wirePick(el) {
    el.querySelectorAll('.aot-coord-plot-pick').forEach(function (b) {
      b.addEventListener('click', function () {
        b.disabled = true;
        fetch('/api/geo/coordinator/' +
              encodeURIComponent(el.getAttribute('data-function')) + '/reference-plot',
              { method: 'POST', credentials: 'same-origin', cache: 'no-store',
                headers: { 'Content-Type': 'application/json',
                           'X-CSRFToken': _csrf() },
                body: JSON.stringify({ plot_uuid: b.getAttribute('data-plot') }) })
          .then(function (r) { return r.json().catch(function () { return null; }); })
          .then(function (res) {
            if (!res || !res.ok) {
              b.disabled = false;
              if (window.showToast) {
                window.showToast((res && res.message) || _t('Could not save the choice.'),
                                 'error');
              }
              return;
            }
            el.dataset.loaded = '';
            load(el);
          })
          .catch(function () { b.disabled = false; });
      });
    });
  }

  function load(el) {
    var fid = el.getAttribute('data-function');
    if (!fid || el.dataset.loaded === '1') return;   // '' 로 비우면 다시 받는다
    el.dataset.loaded = '1';
    fetch('/api/geo/coordinator/' + encodeURIComponent(fid) + '/plot-targets',
          { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.ok) { el.remove(); return; }
        render(el, d);
      })
      .catch(function () { el.remove(); });
  }

  function scan() {
    document.querySelectorAll('.aot-coord-plot[data-function]').forEach(load);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scan);
  } else {
    scan();
  }
  window.AoTCoordinatorPlot = { scan: scan, render: render };
})();
