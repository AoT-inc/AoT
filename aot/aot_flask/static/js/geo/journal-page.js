// journal-page.js — 일지 허브 페이지의 폼 상호작용.
//
// 책임은 셋뿐이다: (1) site/zone 을 고르면 그 자리의 작기 이력을 드릴다운으로
// 보여준다(§7), (2) 작기를 고르면 기간을 자동 채운다(사람이 손대지 않았을
// 때만), (3) "일지 생성" 을 fetch 로 보내고 성공하면 그 permalink 로 이동한다.
//
// 카드 목록 자체는 서버가 렌더한다(journal.html) — 목록을 다시 JS 로 그리지
// 않는다. 여기서 하는 일은 각 카드의 요약(JSON)을 사람이 읽는 문장으로
// 바꾸는 것뿐이다.
(function (root) {
  'use strict';

  var _t = function (s) { return (root._ ? root._(s) : s); };

  function _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ── 카드 요약 문장 조립 ──────────────────────────────────────────────────
  //
  // `summary` 는 숫자만 담은 JSON 이다(routes_geo_journal.py 의 §7 정정 참조).
  // 완성된 문장을 저장하지 않는 이유는 그 문장이 생성 시점의 언어로 굳기
  // 때문이다 — 여기서 뷰어의 언어로 매번 새로 조립한다.
  function _summaryText(raw) {
    if (!raw) return '';
    var s;
    try { s = JSON.parse(raw); } catch (e) { return ''; }
    var gran = s.granularity === 'week' ? _t('Weekly') : _t('Daily');
    var parts = [gran,
                _t('%(n)s periods').replace('%(n)s', String(s.buckets)),
                _t('%(n)s notes').replace('%(n)s', String(s.notes))];
    return parts.join(' · ');
  }

  function _renderCardSummaries(root_) {
    var els = (root_ || document).querySelectorAll('.aot-plots-meta[data-summary]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      el.textContent = _summaryText(el.getAttribute('data-summary'));
    }
  }

  // ── 허브 폼 ──────────────────────────────────────────────────────────────

  function initHub(opts) {
    opts = opts || {};
    _renderCardSummaries(document);

    var areaSel = document.getElementById('journal-area');
    var plotRow = document.getElementById('journal-plot-row');
    var plotSel = document.getElementById('journal-plot');
    var plotNote = document.getElementById('journal-plot-note');
    var startInput = document.getElementById('journal-start');
    var endInput = document.getElementById('journal-end');
    var errorEl = document.getElementById('journal-form-error');
    var genBtn = document.getElementById('journal-generate');
    if (!areaSel || !genBtn) return;

    var plotHistory = [];   // 마지막으로 받은 이력(§7) — 생성 시 kind 판정에 쓴다
    var datesTouched = false;
    startInput.addEventListener('input', function () { datesTouched = true; });
    endInput.addEventListener('input', function () { datesTouched = true; });

    function _clearError() {
      errorEl.style.display = 'none';
      errorEl.textContent = '';
    }

    function _showError(msg) {
      errorEl.textContent = msg || _t('Something went wrong.');
      errorEl.style.display = '';
    }

    areaSel.addEventListener('change', function () {
      _clearError();
      plotSel.innerHTML = '<option value="">' + _esc(_t('Whole area')) + '</option>';
      plotHistory = [];
      var areaId = areaSel.value;
      if (!areaId) {
        plotRow.style.display = 'none';
        plotNote.style.display = 'none';
        return;
      }
      plotRow.style.display = '';
      fetch(opts.historyUrlBase + '?area_id=' + encodeURIComponent(areaId))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data.ok) return;
          plotHistory = data.plots || [];
          plotHistory.forEach(function (p) {
            var opt = document.createElement('option');
            opt.value = p.unique_id;
            var label = p.label || p.unique_id;
            if (p.variety) label += ' (' + p.variety + ')';
            if (p.ongoing) label += ' — ' + _t('ongoing');
            opt.textContent = label;
            plotSel.appendChild(opt);
          });
          if (data.note) {
            plotNote.textContent = data.note;
            plotNote.style.display = '';
          }
        })
        .catch(function () { /* 목록만 비어 있을 뿐, 폼은 계속 쓸 수 있다 */ });
    });

    plotSel.addEventListener('change', function () {
      var plot = plotHistory.filter(function (p) { return p.unique_id === plotSel.value; })[0];
      if (!plot || datesTouched) return;
      // 사람이 아직 기간을 안 건드렸으면 이력의 기간으로 채운다(§7).
      if (plot.started_on) startInput.value = plot.started_on;
      var end = plot.ended_on || plot.expected_end_on;
      if (end) endInput.value = end;
      else if (!plot.ongoing) { /* 끝난 것도 예정도 없으면 손대지 않는다 */ }
      datesTouched = false;   // 자동 채움은 "손댔다" 로 치지 않는다
    });

    genBtn.addEventListener('click', function () {
      _clearError();
      var areaId = areaSel.value;
      if (!areaId) { _showError(_t('Select an area first.')); return; }
      var kind = areaSel.options[areaSel.selectedIndex].getAttribute('data-kind');
      var targetType = plotSel.value ? 'plot' : kind;
      var targetId = plotSel.value || areaId;
      var start = startInput.value, end = endInput.value;
      if (!start || !end) { _showError(_t('Enter both a start and an end date.')); return; }

      genBtn.disabled = true;
      fetch(opts.createUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_type: targetType, target_id: targetId, start: start, end: end
        })
      })
        .then(function (r) { return r.json().then(function (body) {
          return { status: r.status, body: body };
        }); })
        .then(function (res) {
          if (res.body && res.body.ok && res.body.url) {
            root.location.href = res.body.url;
            return;
          }
          _showError((res.body && res.body.message) || _t('Something went wrong.'));
          genBtn.disabled = false;
        })
        .catch(function () {
          _showError(_t('Something went wrong.'));
          genBtn.disabled = false;
        });
    });
  }

  root.AoTJournalPage = { initHub: initHub, renderCardSummaries: _renderCardSummaries };
})(typeof window !== 'undefined' ? window : this);
