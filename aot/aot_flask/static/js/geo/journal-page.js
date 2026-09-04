// journal-page.js — 일지 허브 페이지의 폼 상호작용.
//
// 책임은 넷이다: (1) 구획을 **이름으로 바로 찾는다**(1차 경로), (2) 대상을
// 고르면 기간을 자동으로 채운다 — 구획은 작기 날짜로, 대지·구역은 자료가 실제로
// 시작된 날로, (3) "일지 생성" 을 fetch 로 보내고 성공하면 permalink 로 이동,
// (4) 카드 삭제.
//
// 카드 목록 자체는 서버가 렌더한다(journal.html) — 목록을 다시 JS 로 그리지
// 않는다. 여기서 하는 일은 각 카드의 요약(JSON)을 사람이 읽는 문장으로
// 바꾸는 것뿐이다.
//
// ## 구획 검색은 /plots 와 같은 방식이다
//
// `/api/geo/plots?include_ended=1` 를 한 번 받아 클라이언트에서 거른다 —
// 새 검색 엔드포인트를 만들지 않는다. 훑는 필드도 `plots-page.js` 의
// `_matches()` 와 같게 맞춘다(작물·품종·이름·시설·동·구역·대지·지도·프로그램).
// 갈라지면 같은 것을 찾는데 화면마다 다른 결과가 나온다.
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
    var gran = s.granularity === 'month' ? _t('Monthly')
             : s.granularity === 'week' ? _t('Weekly') : _t('Daily');
    var parts = [gran,
                _t('%(n)s periods').replace('%(n)s', String(s.buckets)),
                _t('%(n)s notes').replace('%(n)s', String(s.notes))];
    return parts.join(' · ');
  }

  function _renderCardSummaries(root_) {
    var els = (root_ || document).querySelectorAll('[data-summary]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      el.textContent = _summaryText(el.getAttribute('data-summary'));
    }
  }

  // ── 구획 검색 ────────────────────────────────────────────────────────────

  // `plots-page.js` 의 `_matches` 와 같은 필드를 훑는다. uuid 는 넣지 않는다
  // (사람이 그것으로 찾지 않고, 넣으면 무관한 항목이 걸린다).
  function _matches(p, q) {
    if (!q) return true;
    return [p.subject, p.variety, p.name, p.facility_name, p.bay_name,
            p.map_name, p.site_name, p.zone_name, (p.program || {}).name]
      .some(function (x) { return x && String(x).toLowerCase().indexOf(q) >= 0; });
  }

  function _where(p) {
    var bits = [];
    if (p.facility_name) {
      bits.push(p.facility_name);
      if (p.bay_name && p.bay_name !== p.facility_name) bits.push(p.bay_name);
    } else {
      if (p.zone_name) bits.push(p.zone_name);
      else if (p.site_name) bits.push(p.site_name);
      if (p.map_name) bits.push(p.map_name);
    }
    return bits.join(' · ');
  }

  function _plotLabel(p) {
    var label = p.name || p.subject || '';
    if (p.variety) label += ' (' + p.variety + ')';
    return label;
  }

  // ── 허브 폼 ──────────────────────────────────────────────────────────────

  function initHub(opts) {
    opts = opts || {};
    _renderCardSummaries(document);

    var searchInput = document.getElementById('journal-plot-search');
    var resultsBox = document.getElementById('journal-plot-results');
    var chosenBox = document.getElementById('journal-plot-chosen');
    var chosenName = document.getElementById('journal-plot-chosen-name');
    var clearBtn = document.getElementById('journal-plot-clear');
    var areaSel = document.getElementById('journal-area');
    var startInput = document.getElementById('journal-start');
    var endInput = document.getElementById('journal-end');
    var errorEl = document.getElementById('journal-form-error');
    var noteEl = document.getElementById('journal-plot-note');
    var genBtn = document.getElementById('journal-generate');

    _wireDelete();
    if (!genBtn) return;

    var plots = [];          // 전체 구획(한 번만 받는다)
    var chosen = null;       // 고른 구획
    var datesTouched = false;
    var measBlock = document.getElementById('journal-meas-block');

    // 스코프별 제목. 구획에 실내 센서와 기상대가 **둘 다** 있으면 그룹이
    // 둘로 나뉘어 각각 이 제목을 단다 — 하나로 뭉치면 체크박스도 하나뿐이라
    // "기상 쪽 온도만 뺀다" 를 표현할 수 없다(`_wanted_measurement` 의 실측
    // 사고 참고). 한쪽뿐이거나 대지·구역이면 서버가 그룹을 하나만 보낸다.
    function _groupTitle(scope) {
      if (scope === 'outdoor') return _t('Weather station measurements to include');
      if (scope === 'indoor') return _t('On-site sensor measurements to include');
      return _t('Measurements to include');
    }

    // 실을 측정값. 대상을 고를 때마다 서버가 그 대상이 **실제로 재는 것**만,
    // 스코프별로 나눠 내려준다 — 전체 어휘를 보여주면 고를 수 있는 것과 값이
    // 나오는 것이 달라져, 골랐는데 빈 문서를 받는다.
    //
    // ⚠ **그룹마다 별도 `<details>` 를 만든다.** 예전에는 한 목록에 실내·기상
    //   채널이 같은 이름(`temperature`)으로 섞여 있어, 기상 쪽을 빼려고 체크를
    //   풀면 실내 채널까지 함께 빠졌다 — 체크박스가 이름 하나에 하나뿐이었기
    //   때문이다. 스코프마다 목록을 가르면 값(`key`)도 서버가 이미
    //   `'outdoor:temperature'` 처럼 갈라 보내므로 저절로 독립된다.
    function _renderMeasurements(groups) {
      if (!measBlock) return;
      groups = (groups || []).filter(function (g) {
        return g && g.measurements && g.measurements.length;
      });
      if (!groups.length) {
        measBlock.style.display = 'none';
        measBlock.innerHTML = '';
        return;
      }
      measBlock.innerHTML = groups.map(function (g) {
        var on = g.measurements.filter(function (m) { return m.default; }).length;
        var list = g.measurements.map(function (m) {
          return '<label class="' + (m.diagnostic ? 'is-diagnostic' : '') + '">' +
                 '<input type="checkbox" value="' + _esc(m.key) + '"' +
                 (m.default ? ' checked' : '') + '>' +
                 '<span>' + _esc(m.label || m.key) + '</span>' +
                 '</label>';
        }).join('');
        return '<details class="aot-journal-meas-block" open>' +
               '<summary><span>' + _esc(_groupTitle(g.scope)) + '</span>' +
               '<span class="text-muted small aot-journal-meas-count">' +
               _esc(_t('%(on)s of %(all)s')
                    .replace('%(on)s', String(on))
                    .replace('%(all)s', String(g.measurements.length))) +
               '</span></summary>' +
               '<div class="aot-journal-meas-list">' + list + '</div>' +
               '</details>';
      }).join('');
      measBlock.style.display = '';
    }

    // 그룹이 여럿이라 카운트 배지도 그룹마다 다시 세야 한다 — `<details>`
    // 하나의 목록만 보면 다른 그룹 배지가 그대로 남는다.
    function _updateMeasCounts() {
      if (!measBlock) return;
      var blocks = measBlock.querySelectorAll('.aot-journal-meas-block');
      for (var i = 0; i < blocks.length; i++) {
        var boxes = blocks[i].querySelectorAll('input[type=checkbox]');
        var on = blocks[i].querySelectorAll('input[type=checkbox]:checked');
        var badge = blocks[i].querySelector('.aot-journal-meas-count');
        if (badge) {
          badge.textContent = _t('%(on)s of %(all)s')
            .replace('%(on)s', String(on.length)).replace('%(all)s', String(boxes.length));
        }
      }
    }

    function _selectedMeasurements() {
      if (!measBlock) return null;
      var boxes = measBlock.querySelectorAll('input[type=checkbox]');
      if (!boxes.length) return null;   // 목록을 못 받았다 = 서버 기본에 맡긴다
      return [].slice.call(boxes)
        .filter(function (b) { return b.checked; })
        .map(function (b) { return b.value; });
    }

    if (measBlock) {
      // 위임 — 그룹은 대상을 바꿀 때마다 통째로 다시 그려지므로 각 체크박스에
      // 직접 붙이면 다시 그릴 때마다 리스너를 새로 달아야 한다.
      measBlock.addEventListener('change', _updateMeasCounts);
    }

    if (startInput) startInput.addEventListener('input', function () { datesTouched = true; });
    if (endInput) endInput.addEventListener('input', function () { datesTouched = true; });

    function _clearError() {
      if (!errorEl) return;
      errorEl.style.display = 'none';
      errorEl.textContent = '';
    }

    function _showError(msg) {
      if (!errorEl) return;
      errorEl.textContent = msg || _t('Something went wrong.');
      errorEl.style.display = '';
    }

    function _note(msg) {
      if (!noteEl) return;
      if (!msg) { noteEl.style.display = 'none'; return; }
      noteEl.textContent = msg;
      noteEl.style.display = '';
    }

    // 구획 목록은 진입 시 한 번만 받는다.
    if (opts.plotsUrl) {
      fetch(opts.plotsUrl)
        .then(function (r) { return r.json(); })
        .then(function (data) { if (data && data.ok) plots = data.plots || []; })
        .catch(function () { /* 검색만 비고 폼은 계속 쓸 수 있다 */ });
    }

    function _renderResults() {
      if (!resultsBox) return;
      var q = (searchInput.value || '').trim().toLowerCase();
      // 빈 검색어에도 목록을 보여준다 — 무엇을 칠 수 있는지 모르는 사람에게
      // 빈 상자를 내밀면 기능이 없는 것으로 읽힌다.
      var rows = plots.filter(function (p) { return _matches(p, q); }).slice(0, 40);
      if (!rows.length) {
        resultsBox.innerHTML = '<div class="aot-plots-empty">' +
                               _esc(_t('No plots found.')) + '</div>';
        resultsBox.style.display = '';
        return;
      }
      resultsBox.innerHTML = rows.map(function (p) {
        return '<button type="button" class="aot-journal-result" data-id="' +
               _esc(p.unique_id) + '">' +
               '<span>' + _esc(_plotLabel(p)) +
               (p.ended_on ? '' : ' <em>' + _esc(_t('ongoing')) + '</em>') + '</span>' +
               '<span class="aot-journal-result-where">' + _esc(_where(p)) + '</span>' +
               '</button>';
      }).join('');
      resultsBox.style.display = '';
    }

    // 대상 하나 → 기간 하한 + 측정값 선택지. 구획과 대지·구역이 **같은**
    // 엔드포인트를 쓴다 — 둘이 갈리면 한쪽만 목록을 못 받는 일이 생긴다.
    function _loadTargetInfo(kind, id, fillDates) {
      if (!opts.targetInfoUrl) return;
      fetch(opts.targetInfoUrl + '?target_type=' + encodeURIComponent(kind) +
            '&target_id=' + encodeURIComponent(id))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data || !data.ok) return;
          // 그룹 제목은 `_renderMeasurements` 가 스코프마다 정한다 — 대상을
          // 바꿔 가며 고를 때 앞 대상의 그룹이 그대로 남지 않도록 항상
          // 통째로 다시 그린다.
          _renderMeasurements(data.measurement_groups);
          if (!fillDates || datesTouched) return;
          if (data.first_date) {
            if (startInput) startInput.value = data.first_date;
            if (endInput) endInput.value = new Date().toISOString().slice(0, 10);
            _note(_t('Data for this area starts on %(d)s.')
                    .replace('%(d)s', data.first_date));
          } else {
            _note(_t('No measurements found for this area yet.'));
          }
        })
        // 편의 기능이라 실패해도 막지 않는다 — 사람이 직접 넣으면 된다.
        .catch(function () { _note(''); });
    }

    function _choose(plot) {
      chosen = plot;
      if (chosenName) chosenName.textContent = _plotLabel(plot) + ' — ' + _where(plot);
      if (chosenBox) chosenBox.style.display = '';
      if (searchInput) searchInput.style.display = 'none';
      if (resultsBox) resultsBox.style.display = 'none';
      if (areaSel) areaSel.value = '';       // 두 경로를 동시에 고르지 않는다
      _clearError();
      _note('');

      // 사람이 아직 기간을 안 건드렸으면 작기 기간으로 채운다.
      if (datesTouched) return;
      if (plot.started_on && startInput) startInput.value = plot.started_on;
      var end = plot.ended_on || plot.expected_end_on;
      if (endInput) endInput.value = end || new Date().toISOString().slice(0, 10);

      // 기간은 작기 날짜로 이미 채웠으므로 날짜는 건드리지 않는다.
      _loadTargetInfo('plot', plot.unique_id, false);
    }

    if (searchInput) {
      searchInput.addEventListener('focus', _renderResults);
      searchInput.addEventListener('input', _renderResults);
    }

    if (resultsBox) {
      resultsBox.addEventListener('click', function (ev) {
        var btn = ev.target.closest('.aot-journal-result');
        if (!btn) return;
        var plot = plots.filter(function (p) { return p.unique_id === btn.dataset.id; })[0];
        if (plot) _choose(plot);
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        chosen = null;
        if (chosenBox) chosenBox.style.display = 'none';
        if (searchInput) { searchInput.style.display = ''; searchInput.value = ''; searchInput.focus(); }
        _renderMeasurements(null);
      });
    }

    // ── 대지·구역(2차 경로) ────────────────────────────────────────────────
    //
    // 구획과 달리 시작 날짜가 없다. 그래서 자료가 **실제로 언제부터** 있는지를
    // 서버에 물어 채운다 — 없으면 사람이 감으로 넣게 되고, 실측에서 그 결과가
    // "10개 버킷 중 7개가 빈" 문서였다.
    if (areaSel) {
      areaSel.addEventListener('change', function () {
        _clearError();
        if (!areaSel.value) return;
        // 두 경로를 동시에 고르지 않는다.
        chosen = null;
        if (chosenBox) chosenBox.style.display = 'none';
        if (searchInput) { searchInput.style.display = ''; searchInput.value = ''; }
        if (resultsBox) resultsBox.style.display = 'none';

        var kind = areaSel.options[areaSel.selectedIndex].getAttribute('data-kind');
        _note(_t('Looking up when data starts…'));
        _loadTargetInfo(kind, areaSel.value, true);
      });
    }

    // ── 생성 ───────────────────────────────────────────────────────────────
    genBtn.addEventListener('click', function () {
      _clearError();
      var targetType, targetId;
      if (chosen) {
        targetType = 'plot';
        targetId = chosen.unique_id;
      } else if (areaSel && areaSel.value) {
        targetType = areaSel.options[areaSel.selectedIndex].getAttribute('data-kind');
        targetId = areaSel.value;
      } else {
        _showError(_t('Pick a plot, or a site or zone.'));
        return;
      }
      var start = startInput ? startInput.value : '';
      var end = endInput ? endInput.value : '';
      if (!start || !end) { _showError(_t('Enter both a start and an end date.')); return; }

      var measurements = _selectedMeasurements();
      if (measurements !== null && !measurements.length) {
        _showError(_t('Pick at least one measurement.'));
        return;
      }

      var payload = {
        target_type: targetType, target_id: targetId, start: start, end: end
      };
      // 빈 값은 보내지 않는다 = '자동'(서버가 정하던 예전 동작).
      var granSel = document.getElementById('journal-gran');
      if (granSel && granSel.value) payload.granularity = granSel.value;
      // `null` 이면 보내지 않는다 = 서버 기본(진단 채널만 제외)에 맡긴다.
      if (measurements !== null) payload.measurements = measurements;

      genBtn.disabled = true;
      fetch(opts.createUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
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

  // ── 삭제 ─────────────────────────────────────────────────────────────────
  //
  // 되돌릴 수 없는 생성은 사용자가 시도 자체를 꺼리게 만든다. 낮은 빈도의
  // 자기 생성물 삭제라 확인은 `window.confirm` 으로 충분하다(별도 모달을
  // 만들면 이 화면 하나를 위한 문법이 하나 더 는다).
  function _wireDelete() {
    var list = document.getElementById('journal-list');
    if (!list) return;
    list.addEventListener('click', function (ev) {
      var btn = ev.target.closest('.aot-journal-row-del');
      if (!btn) return;
      ev.preventDefault();
      if (!root.confirm(_t('Delete this journal? This cannot be undone.'))) return;
      btn.disabled = true;
      fetch(btn.dataset.url, { method: 'DELETE', headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (body) {
          if (body && body.ok) {
            var row = btn.closest('.aot-journal-row');
            if (row) row.remove();
            return;
          }
          root.alert((body && body.message) || _t('Something went wrong.'));
          btn.disabled = false;
        })
        .catch(function () {
          root.alert(_t('Something went wrong.'));
          btn.disabled = false;
        });
    });
  }

  root.AoTJournalPage = { initHub: initHub, renderCardSummaries: _renderCardSummaries };
})(typeof window !== 'undefined' ? window : this);
