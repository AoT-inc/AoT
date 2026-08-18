/* 노트를 저장하기 전에, 이번 편집으로 **구간이 사라지는 예정**이 있으면 묻는다.
 *
 * 묻지 않고 취소하면 오타 하나 고치다 잡아둔 약속이 사라지고, 묻지 않고
 * 남기면 본문에 없는 약속이 조용히 남는다. 둘 다 사용자가 모르는 채로
 * 일어나므로, 판정만 서버가 하고(POST /notes/<id>/orphaned) 결정은 사람이 한다.
 *
 * **저장 전에** 묻는 이유: 저장한 뒤 물으면 사용자는 이미 없어진 글을 보며
 * 무엇을 지웠는지 기억해내야 한다.
 *
 * 실패하면 **막지 않고 그냥 저장시킨다.** 이 확인은 편의이지 안전장치가
 * 아니다 — 판정 요청이 실패했다고 사람의 글 저장을 막으면, 고칠 수 없는
 * 화면이 된다(고아는 노트 패널에 계속 드러나므로 나중에도 정리할 수 있다).
 */
(function (global) {
  'use strict';

  function _t(s) { return (global._ ? global._(s) : s); }

  function _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;',
               '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function _whenText(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    var p = function (n) { return String(n).padStart(2, '0'); };
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' +
           p(d.getHours()) + ':' + p(d.getMinutes());
  }

  function init(opts) {
    opts = opts || {};
    var form = document.querySelector('form[action^="/note_edit/"]');
    var body = document.querySelector('#note, [name="note"]');
    if (!form || !body || !opts.noteId) return;

    var modalEl = document.getElementById('modal_note_orphaned');
    var listEl = document.getElementById('note_orphaned_list');
    if (!modalEl || !listEl) return;

    var pending = [];      // 이번 편집으로 사라지는 링크들
    var passthrough = false;

    function showModal(on) {
      if (global.jQuery) { global.jQuery(modalEl).modal(on ? 'show' : 'hide'); }
      else { modalEl.style.display = on ? 'block' : 'none'; }
    }

    function submitNow() {
      passthrough = true;
      // requestSubmit 이 없으면 submit() — 그 경우 이 핸들러를 다시 타지
      // 않으므로 passthrough 와 무관하게 한 번만 나간다.
      if (form.requestSubmit) form.requestSubmit();
      else form.submit();
    }

    function dropLinks(cancelJob, done) {
      var left = pending.length;
      if (!left) { done(); return; }
      pending.forEach(function (l) {
        fetch('/notes/link/' + encodeURIComponent(l.link_id) +
              (cancelJob ? '?cancel_job=1' : ''), {
          method: 'DELETE', credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest',
                     'X-CSRFToken': opts.csrf || '' }
        }).catch(function () {}).then(function () {
          if (--left === 0) done();
        });
      });
    }

    document.getElementById('note_orphaned_keep')
      .addEventListener('click', function () {
        // 링크만 끊는다 — 예정은 /scheduler 에 그대로 남는다.
        dropLinks(false, function () { showModal(false); submitNow(); });
      });

    document.getElementById('note_orphaned_cancel')
      .addEventListener('click', function () {
        dropLinks(true, function () { showModal(false); submitNow(); });
      });

    form.addEventListener('submit', function (e) {
      if (passthrough) return;
      // 삭제·취소 버튼으로 낸 제출은 본문 저장이 아니다.
      var by = e.submitter || document.activeElement;
      var byName = by && by.getAttribute && by.getAttribute('name');
      if (byName && byName !== 'note_save') return;

      e.preventDefault();
      fetch('/notes/' + encodeURIComponent(opts.noteId) + '/orphaned', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json',
                   'X-Requested-With': 'XMLHttpRequest',
                   'X-CSRFToken': opts.csrf || '' },
        body: JSON.stringify({ note: body.value || '' })
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          pending = (d && d.orphaned) || [];
          if (!pending.length) { submitNow(); return; }
          listEl.innerHTML = pending.map(function (l) {
            return '<div class="aot-modal-option-row">' +
                   '<div class="aot-modal-option-label">' +
                   _esc(_whenText(l.when)) + '</div>' +
                   '<div class="aot-modal-option-control">' +
                   _esc(l.text) + '</div></div>';
          }).join('');
          showModal(true);
        })
        .catch(function () { submitNow(); });   // 판정 실패는 저장을 막지 않는다
    });
  }

  global.AoTNoteOrphanedLinks = { init: init };
})(window);
