/* /logview — 로그 뷰어 클라이언트.
 *
 * 서버는 /logview/data 로 구조화된 항목(ts/level/logger/message/raw)을 준다.
 * 이 파일이 하는 일: 필터 상태를 URL 에 유지, 폴링(라이브 테일), 렌더링·선택,
 * 그리고 선택한 줄을 전역 AI 채팅에 넘기는 것.
 *
 * 폴링은 조건부 요청이다(서버가 ETag 를 준다). 304 면 아무것도 하지 않는데,
 * 이 응답에 실린 것이 로그 내용 전부라 건너뛰어도 놓치는 갱신이 없다 —
 * "304 로 건너뛸 것은 그 응답에 실린 것뿐" 규칙을 만족한다.
 */
(function () {
  'use strict';

  var cfgEl = document.getElementById('aot-logview-config');
  if (!cfgEl) return;

  var CFG = JSON.parse(cfgEl.textContent);

  function t(key) {
    return (typeof window._ === 'function') ? window._(key) : key;
  }

  var els = {
    source: document.getElementById('logview-source'),
    level: document.getElementById('logview-level'),
    search: document.getElementById('logview-search'),
    lines: document.getElementById('logview-lines'),
    live: document.getElementById('logview-live'),
    refresh: document.getElementById('logview-refresh'),
    download: document.getElementById('logview-download'),
    pane: document.getElementById('logview-pane'),
    origin: document.getElementById('logview-origin'),
    count: document.getElementById('logview-count'),
    updated: document.getElementById('logview-updated'),
    notice: document.getElementById('logview-notice'),
    aibar: document.getElementById('logview-aibar'),
    aihint: document.getElementById('logview-aihint'),
    selectionClear: document.getElementById('logview-clear-selection')
  };

  var POLL_MS = 5000;

  var state = {
    entries: [],          // 화면에 있는 항목(오래된 것 → 최신)
    selected: [],         // 선택된 인덱스
    lastIndex: null,      // shift-클릭 범위의 앵커
    offset: null,         // 증분 읽기 기준 바이트 위치
    etag: null,
    requestKey: '',       // 필터 지문 — 바뀌면 증분·ETag 를 버린다
    timer: null,
    inFlight: false,
    pending: null         // 요청 중에 들어온 재요청(겹치면 버리지 않고 이어 돈다)
  };

  // --- 유틸 -------------------------------------------------------------

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // 날짜와 시각을 따로 내보낸다 — 폰에서는 CSS 가 날짜만 접는다. 하나로
  // 붙여 두면 좁은 화면에서 타임스탬프가 두 줄로 접혀 행 높이가 들쭉날쭉해진다.
  function splitTs(ts) {
    if (!ts) return {date: '', time: ''};
    var m = /^\d{4}-(\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})/.exec(ts);
    return m ? {date: m[1], time: m[2]} : {date: '', time: ts};
  }

  function currentFilters() {
    return {
      source: els.source.value,
      level: els.level.value,
      search: els.search.value.trim(),
      lines: els.lines.value
    };
  }

  function filterKey(f) {
    return [f.source, f.level, f.search, f.lines].join('');
  }

  function buildQuery(f, extra) {
    var params = new URLSearchParams();
    params.set('source', f.source);
    if (f.level) params.set('level', f.level);
    if (f.search) params.set('search', f.search);
    params.set('lines', f.lines);
    if (extra && extra.offset != null) params.set('offset', String(extra.offset));
    return params.toString();
  }

  function syncUrl(f) {
    var params = new URLSearchParams();
    params.set('source', f.source);
    if (f.level) params.set('level', f.level);
    if (f.search) params.set('search', f.search);
    if (f.lines !== String(CFG.defaultLines)) params.set('lines', f.lines);
    if (els.live.checked) params.set('live', '1');
    var url = window.location.pathname + '?' + params.toString();
    window.history.replaceState(null, '', url);
    els.download.href = '/logview/download?' + buildQuery(f);
  }

  // --- 렌더 -------------------------------------------------------------

  function isPinnedToBottom() {
    var pane = els.pane;
    return (pane.scrollHeight - pane.scrollTop - pane.clientHeight) < 24;
  }

  function highlight(text, needle) {
    var safe = escapeHtml(text);
    if (!needle) return safe;
    var escaped = escapeHtml(needle).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    try {
      return safe.replace(new RegExp(escaped, 'gi'), function (hit) {
        return '<mark>' + hit + '</mark>';
      });
    } catch (err) {
      return safe;
    }
  }

  function rowHtml(entry, index, needle) {
    var level = (entry.level || '').toUpperCase();
    var cls = level ? (' lv-' + level.toLowerCase()) : '';
    var selected = state.selected.indexOf(index) !== -1 ? ' is-selected' : '';
    var ts = splitTs(entry.ts);
    return '<div class="aot-log-row' + cls + selected + '" data-index="' + index + '">' +
      '<span class="aot-log-ts"><span class="aot-log-date">' +
      escapeHtml(ts.date) + '</span>' + escapeHtml(ts.time) + '</span>' +
      '<span class="aot-log-level">' + escapeHtml(level) + '</span>' +
      '<span class="aot-log-logger" title="' + escapeHtml(entry.logger || '') + '">' +
      escapeHtml(entry.logger || '') + '</span>' +
      '<span class="aot-log-msg">' + highlight(entry.message || '', needle) + '</span>' +
      '</div>';
  }

  function render(pinBottom) {
    var needle = els.search.value.trim();
    if (!state.entries.length) {
      els.pane.innerHTML = '<div class="aot-log-empty">' +
        escapeHtml(t('No log entries match the current filter.')) + '</div>';
    } else {
      var html = new Array(state.entries.length);
      for (var i = 0; i < state.entries.length; i++) {
        html[i] = rowHtml(state.entries[i], i, needle);
      }
      els.pane.innerHTML = html.join('');
    }
    if (pinBottom) els.pane.scrollTop = els.pane.scrollHeight;
    updateSelectionUi();
  }

  function updateSelectionUi() {
    if (!els.aibar) return;
    var count = state.selected.length;
    var errors = 0;
    var warnings = 0;
    for (var i = 0; i < state.entries.length; i++) {
      var level = (state.entries[i].level || '').toUpperCase();
      if (level === 'ERROR' || level === 'CRITICAL') errors++;
      else if (level === 'WARNING') warnings++;
    }
    var hint;
    if (count) {
      hint = t('%d line(s) selected. The selected lines are sent to the AI.')
        .replace('%d', count);
    } else if (errors || warnings) {
      hint = t('Nothing selected — the AI gets the errors and warnings currently in view (%e error(s), %w warning(s)). Click a line to pick it; shift-click for a range.')
        .replace('%e', errors).replace('%w', warnings);
    } else {
      hint = t('Nothing selected — the AI gets the lines currently in view. Click a line to pick it; shift-click for a range.');
    }
    els.aihint.textContent = hint;
    if (els.selectionClear) {
      els.selectionClear.classList.toggle('is-hidden', !count);
    }
  }

  function setStatus(payload) {
    els.origin.textContent = payload.origin || '';
    els.count.textContent = t('%d entries').replace('%d', state.entries.length);
    els.updated.textContent = t('Updated') + ' ' +
      new Date().toLocaleTimeString();

    var messages = [];
    var isError = false;
    if (payload.error) {
      messages.push(payload.error);
      isError = true;
    }
    if (payload.truncated) {
      messages.push(t('Scan limit reached — older matching lines exist but were not read. Narrow the search or pick a more specific log source.'));
    }
    if (messages.length) {
      els.notice.className = 'aot-log-notice' + (isError ? ' is-error' : '');
      els.notice.textContent = messages.join(' ');
    } else {
      els.notice.className = 'aot-log-notice is-hidden';
      els.notice.textContent = '';
    }
  }

  // --- 데이터 -----------------------------------------------------------

  function load(options) {
    options = options || {};
    if (state.inFlight) {
      // 그냥 버리면 마지막 필터 변경이 통째로 반영되지 않는다 — 검색어를 빠르게
      // 타이핑하면 디바운스가 끝난 요청이 앞선 요청과 겹쳐, 화면이 옛 결과에
      // 멈춘 채 남는다(에러 없음). 겹치면 버리지 말고 끝난 뒤 한 번 더 돈다.
      state.pending = options;
      return;
    }
    state.pending = null;

    var filters = currentFilters();
    var key = filterKey(filters);
    var incremental = options.incremental && key === state.requestKey &&
      state.offset != null;

    if (key !== state.requestKey) {
      // 필터가 바뀌면 검증자와 캐시를 함께 버린다. 하나만 버리면 다음 요청이
      // 옛 ETag 로 304 를 받아 갱신이 통째로 비는 자리다.
      state.requestKey = key;
      state.etag = null;
      state.offset = null;
      incremental = false;
    }

    var url = '/logview/data?' + buildQuery(filters,
      incremental ? {offset: state.offset} : null);

    var headers = {};
    if (state.etag) headers['If-None-Match'] = state.etag;

    state.inFlight = true;
    // cache:'no-store' — 브라우저 HTTP 캐시가 조건부 요청을 가로채 200(캐시본)
    // 으로 둔갑시키면 본문을 도로 파싱하게 되어 아끼려던 것을 그대로 쓴다.
    fetch(url, {headers: headers, cache: 'no-store', credentials: 'same-origin'})
      .then(function (res) {
        if (res.status === 304) return null;
        state.etag = res.headers.get('ETag');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (payload) {
        if (!payload) return;   // 304 — 로그에 새로 붙은 것이 없다
        apply(payload, incremental);
      })
      .catch(function (err) {
        els.notice.className = 'aot-log-notice is-error';
        els.notice.textContent = t('Failed to load the log') + ': ' + err.message;
      })
      .then(function () {
        state.inFlight = false;
        if (state.pending) load(state.pending);
      });
  }

  function apply(payload, wantedIncremental) {
    var pin = isPinnedToBottom() || !state.entries.length;
    var maxRows = parseInt(els.lines.value, 10) || CFG.defaultLines;

    if (wantedIncremental && payload.incremental) {
      if (payload.entries.length) {
        state.entries = state.entries.concat(payload.entries);
        if (state.entries.length > maxRows) {
          var drop = state.entries.length - maxRows;
          state.entries = state.entries.slice(drop);
          // 앞이 잘리면 선택 인덱스도 같이 밀어야 엉뚱한 줄이 선택된 것으로
          // 보인다. 범위를 벗어난 것은 버린다.
          state.selected = state.selected
            .map(function (i) { return i - drop; })
            .filter(function (i) { return i >= 0; });
        }
      }
    } else {
      state.entries = payload.entries || [];
      state.selected = [];
      state.lastIndex = null;
    }

    state.offset = (payload.offset != null) ? payload.offset : null;
    render(pin);
    setStatus(payload);
  }

  // --- 라이브 테일 -------------------------------------------------------

  function startLive() {
    stopLive();
    // setInterval 은 aot-poll-visibility.js 가 감싸 공통 격자에 정렬한다 —
    // 여기서 직접 setTimeout 체인을 만들면 그 정렬 밖으로 빠진다.
    state.timer = window.setInterval(function () {
      load({incremental: true});
    }, POLL_MS);
  }

  function stopLive() {
    if (state.timer) {
      window.clearInterval(state.timer);
      state.timer = null;
    }
  }

  // --- 선택 -------------------------------------------------------------

  function toggleSelection(index, withShift) {
    if (withShift && state.lastIndex != null) {
      var start = Math.min(state.lastIndex, index);
      var end = Math.max(state.lastIndex, index);
      state.selected = [];
      for (var i = start; i <= end; i++) state.selected.push(i);
    } else {
      var at = state.selected.indexOf(index);
      if (at === -1) state.selected.push(index);
      else state.selected.splice(at, 1);
      state.lastIndex = index;
    }
    var rows = els.pane.querySelectorAll('.aot-log-row');
    for (var r = 0; r < rows.length; r++) {
      var idx = parseInt(rows[r].getAttribute('data-index'), 10);
      rows[r].classList.toggle('is-selected', state.selected.indexOf(idx) !== -1);
    }
    updateSelectionUi();
  }

  // --- AI ---------------------------------------------------------------

  var AI_EXCERPT_MAX = 120;

  function excerptLines() {
    var picked;
    if (state.selected.length) {
      picked = state.selected.slice().sort(function (a, b) { return a - b; })
        .map(function (i) { return state.entries[i]; })
        .filter(Boolean);
    } else {
      // 선택이 없으면 화면에 있는 것 중 오류·경고를 우선한다. 그것도 없으면
      // 최근 줄. 전체를 통째로 보내면 정작 물어보려던 줄이 묻힌다.
      picked = state.entries.filter(function (e) {
        var level = (e.level || '').toUpperCase();
        return level === 'ERROR' || level === 'CRITICAL' || level === 'WARNING';
      });
      if (!picked.length) picked = state.entries;
    }
    return picked.slice(-AI_EXCERPT_MAX).map(function (e) { return e.raw; });
  }

  function askAi(question) {
    var lines = excerptLines();
    if (!lines.length) {
      if (window.showToast) {
        window.showToast(t('There are no log lines to ask about.'), 'info');
      }
      return;
    }

    var errors = 0;
    var warnings = 0;
    state.entries.forEach(function (e) {
      var level = (e.level || '').toUpperCase();
      if (level === 'ERROR' || level === 'CRITICAL') errors++;
      else if (level === 'WARNING') warnings++;
    });

    var sourceLabel = els.source.options[els.source.selectedIndex].text;

    window.dispatchEvent(new CustomEvent('open-ai-chat', {
      detail: {
        name: sourceLabel,
        targetType: 'log',
        autoMessage: question,
        log_excerpt: {
          source: els.source.value,
          source_label: sourceLabel,
          lines: lines,
          error_count: errors,
          warning_count: warnings
        }
      }
    }));
  }

  // --- 배선 -------------------------------------------------------------

  function reload() {
    stopLive();
    load({incremental: false});
    if (els.live.checked) startLive();
    syncUrl(currentFilters());
  }

  function debounce(fn, wait) {
    var handle = null;
    return function () {
      if (handle) window.clearTimeout(handle);
      handle = window.setTimeout(fn, wait);
    };
  }

  els.source.addEventListener('change', reload);
  els.level.addEventListener('change', reload);
  els.lines.addEventListener('change', reload);
  els.search.addEventListener('input', debounce(reload, 350));
  els.search.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); reload(); }
  });
  els.refresh.addEventListener('click', function () {
    load({incremental: false});
  });
  els.live.addEventListener('change', function () {
    if (els.live.checked) startLive(); else stopLive();
    syncUrl(currentFilters());
  });

  els.pane.addEventListener('click', function (e) {
    var row = e.target.closest ? e.target.closest('.aot-log-row') : null;
    if (!row) return;
    toggleSelection(parseInt(row.getAttribute('data-index'), 10), e.shiftKey);
  });

  if (els.selectionClear) {
    els.selectionClear.addEventListener('click', function () {
      state.selected = [];
      state.lastIndex = null;
      var rows = els.pane.querySelectorAll('.aot-log-row.is-selected');
      for (var i = 0; i < rows.length; i++) rows[i].classList.remove('is-selected');
      updateSelectionUi();
    });
  }

  // 버튼이 보낼 질문 문장은 템플릿이 이미 번역해서 data 속성에 넣어 둔다
  // (서버 렌더 문구라 pybabel 이 템플릿에서 그대로 추출한다).
  var aiButtons = document.querySelectorAll('[data-logview-ask]');
  for (var b = 0; b < aiButtons.length; b++) {
    aiButtons[b].addEventListener('click', function (e) {
      askAi(e.currentTarget.getAttribute('data-logview-ask'));
    });
  }

  // 탭을 떠나면 폴링을 멈춘다. aot-poll-visibility 가 숨은 탭의 타이머를
  // 늦추기는 하지만, 로그 폴링은 화면에 안 보이면 완전히 멈춰도 잃는 것이 없다.
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stopLive();
    else if (els.live.checked) { load({incremental: true}); startLive(); }
  });

  // 초기 상태는 URL 쿼리에서 복원한다 — 필터가 걸린 화면을 그대로 공유하거나
  // 새로고침해도 같은 것이 보여야 한다. 소스만 서버가 이미 선택해 뒀다
  // (알 수 없는 id 면 기본 소스로 되돌려 놓기 때문).
  (function restoreFromUrl() {
    var params = new URLSearchParams(window.location.search);
    var level = (params.get('level') || '').toUpperCase();
    if (level && els.level.querySelector('option[value="' + level + '"]')) {
      els.level.value = level;
    }
    var search = params.get('search');
    if (search) els.search.value = search;
    var lines = params.get('lines');
    if (lines && els.lines.querySelector('option[value="' + lines + '"]')) {
      els.lines.value = lines;
    }
    els.live.checked = params.get('live') === '1';
  })();

  syncUrl(currentFilters());
  load({incremental: false});
  if (els.live.checked) startLive();
})();
