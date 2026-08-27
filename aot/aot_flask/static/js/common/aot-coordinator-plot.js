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
  /** 설정 행과 같은 골격의 한 줄. `summary` 모드 전용. */
  function _sumRow(label, value) {
    return '<div class="aot-modal-option-row">' +
           '<div class="aot-modal-option-label">' + _esc(label) + '</div>' +
           '<div class="aot-modal-option-control">' + value + '</div></div>';
  }

  /* ── 요약 모드 (`data-summary="1"`) ───────────────────────────────────────
   *
   * 자리는 설정 화면의 **[연동 시설] 바로 아래**다. 시설을 고르면 따라오는
   * 정보이므로 고르기 전에 읽힐 이유가 없다 — 2026-08-27 사용자 지적:
   * *"시설 옵션에서 시설을 선택하면 해당 시설에 달려오는 정보이므로 그 이후에
   * 짧은 요약만 제공하는 게 나아보임."*
   *
   * 그래서 표가 아니라 **두 줄**이다. 자세한 표는 시설 화면이 맡는다.
   *
   * ⚠ 후보가 둘 이상일 때의 [이걸로] 버튼은 요약에도 남긴다 — 그것이 이
   *   블록의 유일한 쓰기이고, 대체 수단(`source_plot_id`)은 [고급] 안에 있다.
   *   여기서 빼면 막다른 안내가 된다.
   */
  function _renderSummary(el, d) {
    if (!d.plot) {
      if (d.reason === 'ambiguous' && d.can_pick) {
        var h = '<div class="aot-coord-plot-note">' + _esc(_reasonText(d)) +
                '</div>';
        (d.candidates || []).forEach(function (c) {
          h += '<div class="aot-coord-plot-cand">' +
               '<span>' + _esc(c.subject || c.name || '') +
               (c.program_name ? ' \u00b7 ' + _esc(c.program_name) : '') + '</span>' +
               '<button type="button" class="btn aot-pill-btn aot-coord-plot-pick"' +
               ' data-plot="' + _esc(c.unique_id) + '">' +
               _esc(_t('Follow this one')) + '</button></div>';
        });
        el.innerHTML = h;
        _wirePick(el);
        return;
      }
      // 시설을 아직 안 골랐거나 붙일 구획이 없다 — 바로 위 칸이 그 말을 이미
      // 하고 있으므로 **아무것도 내지 않는다.**
      el.innerHTML = '';
      return;
    }
    var p = d.plot;
    var what = (p.subject || p.name || '');
    if (p.variety) what += ' (' + p.variety + ')';
    if (d.stage && d.stage.name) {
      what += ' \u00b7 ' + d.stage.name +
              (d.stage.index ? ' (' + d.stage.index + '/' + d.stage.total + ')' : '');
    }
    var out = _sumRow(_t('Growing'), _esc(what));

    var vals = (d.targets || []).map(function (r) {
      return (r.label || r.key) + ' ' +
             (r.method_id ? (r.method_name || _t('curve'))
                          : _num(r.value) + (r.unit ? ' ' + r.unit : ''));
    });
    if ((d.unmapped || []).length) {
      vals.push(_t('For reference') + ' ' + d.unmapped.map(function (u) {
        return (u.label || u.key) + ' ' + _num(u.value) +
               (u.unit ? ' ' + u.unit : '');
      }).join(' \u00b7 '));
    }
    if (vals.length) out += _sumRow(_t('Targets'), _esc(vals.join('  \u00b7  ')));
    if (d.pinned_missing) {
      out += '<div class="aot-coord-plot-note">' +
             _esc(_t('The plot you pinned is no longer here.')) + '</div>';
    }
    el.innerHTML = out;
  }

  function render(el, d) {
    if (el.getAttribute('data-summary') === '1') return _renderSummary(el, d);
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

    // ⚠ **문장으로 변명하지 말 것.** 예전에는 참고값 앞에 "이 코디네이터는
    //   VPD 를 목표로 하므로 아래는 여기 설정이 아닙니다" 를 붙였는데,
    //   *"여기 설정이 아닌데 여기서 설정한다는 거야? 이런 설명이면 이 정보는
    //   왜 여기에 표시하는 거지?"* 가 됐다(2026-08-27). 설명이 길수록 왜 여기
    //   있는지가 더 흐려진다.
    //
    //   지금은 **표 안의 한 줄**이다 — 라벨이 "참고용" 이면 그 줄이 목표가
    //   아니라는 사실을 문장 없이 말한다. 무엇을 목표로 삼는지는 표 아래
    //   한 문장이 한 번만 말한다.
    if ((d.targets || []).length || (d.unmapped || []).length) {
      var rows = (d.targets || []).map(_rowHtml).join('');
      if ((d.unmapped || []).length) {
        rows += '<tr><td>' + _esc(_t('For reference')) + '</td><td>' +
                '<span class="aot-ov-muted">' +
                d.unmapped.map(function (u) {
                  return _esc((u.label || u.key) + ' ' + _num(u.value) +
                              (u.unit ? ' ' + u.unit : ''));
                }).join(' · ') + '</span></td></tr>';
      }
      html += '<table class="aot-coord-plot-table"><tbody>' + rows +
              '</tbody></table>';
    } else {
      html += '<div class="aot-coord-plot-note">' +
              _esc(_reasonText(d)) + '</div>';
    }

    html += '<div class="aot-coord-plot-note">' +
            _esc(_t('Aims at photosynthesis (VPD); other values are used as reference. Targets come from the program.')) +
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
