/* 단계별 **목표 옆에 이 구획이 실제로 잰 값**을 그린다.
 *
 * 왜. 단계 일수는 [프로그램으로 등록]이 현장 실측으로 갱신해 주는데 목표값은
 * 원본 그대로 복사됐다 — 되먹임 고리가 한쪽만 열려 있었다. 서버가 등록
 * 응답에 `target_review` 를 실어 보내므로(`plot_io.save_as_program`), 화면은
 * 그것을 등록한 자리에서 바로 보여 준다. 숫자를 보고 목표를 고칠지는 사람이
 * 정한다 — 여기서 판정하지 않는다.
 *
 * ⚠ **새 CSS 를 만들지 않고, 어느 화면에서나 서는 것만 쓴다.** 처음엔 지도
 *   개요 카드의 `.aot-ov-*` 로 짰는데 그 규칙은 `aot-sensor-label.css` 에 있고
 *   그 파일은 **구획 페이지에 안 실린다** — 브라우저로 확인하니 두 칸이 접혀
 *   한 줄씩 흘렀다. 그래서 레이아웃이 layout.html 이 늘 싣는
 *   `aot-modal-modern.css` 의 현대화 모달 골격(`aot-modal-*`)으로 왔다.
 *
 * ⚠ **센서를 가로질러 평균하지 않는다.** 캐노피 안팎이 다른 값을 내는 것이
 *   정상이라, 값이 갈리면 센서마다 한 줄씩 낸다 — 하나로 접으면 어느 센서도
 *   말하지 않은 숫자가 화면에 선다(서버가 그래서 `suggest` 를 비운다).
 */
(function (root) {
  'use strict';

  function _t(k) { return (root._ ? root._(k) : k); }

  function _esc(x) {
    return String(x == null ? '' : x).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function _row(name, value) {
    // 「이름 | 값」 두 칸 — `.aot-modal-option-row` 가 flex·space-between 이다.
    // 값 칸에 `.aot-modal-option-control` 을 쓰지 않는 이유는 그 클래스가
    // **입력 컨트롤 폭**으로 고정돼 있어서다(여기 값은 글자다).
    return '<div class="aot-modal-option-row">' +
           '<span class="aot-modal-option-label">' + _esc(name) + '</span>' +
           '<span class="aot-modal-body-text">' + _esc(value) + '</span></div>';
  }

  /** `target_review` → HTML 문자열. 보일 것이 없으면 빈 문자열. */
  function html(review) {
    var blocks = [];
    (review || []).forEach(function (stage) {
      var rows = [];
      (stage.items || []).forEach(function (item) {
        var sensors = item.sensors || [];
        if (!sensors.length) return;      // 그 단계에 잰 것이 없다 — 빈 줄을 만들지 않는다
        var target = (item.target == null) ? '' : String(item.target) + ' → ';
        var unit = item.unit ? (' ' + item.unit) : '';
        if (sensors.length === 1) {
          rows.push(_row(item.label || item.key,
                         target + sensors[0].median + unit));
          return;
        }
        sensors.forEach(function (s) {
          rows.push(_row((item.label || item.key) + ' · ' + s.sensor,
                         target + s.median + unit));
        });
      });
      if (!rows.length) return;
      blocks.push('<div class="aot-modal-subgroup-title">' +
                  _esc(stage.name || '') + '</div>' +
                  '<div class="aot-modal-option-group">' + rows.join('') +
                  '</div>');
    });
    if (!blocks.length) return '';
    // ⚠ **문장은 값이 아니다.** 두 칸짜리 행의 오른쪽에 긴 문장을 넣으면
    //   우측 정렬로 들쭉날쭉하게 찢어진다(개요 카드가 적어 둔 2026-08-26
    //   지적). 설명은 본문 한 문단으로 따로 세운다.
    return '<div class="aot-modal-group-title">' +
           _esc(_t('Target vs what this plot measured')) + '</div>' +
           '<div class="aot-modal-body-text">' +
           _esc(_t('The second number is the median of the daily values in ' +
                   'that stage, per sensor. Showing it changes nothing.')) +
           '</div>' + blocks.join('');
  }

  /** 컨테이너에 그려 넣는다. 보일 것이 없으면 비우고 감춘다. */
  function render(container, review) {
    if (!container) return false;
    var out = html(review);
    container.innerHTML = out;
    container.hidden = !out;
    return !!out;
  }

  root.AoTTargetReview = { html: html, render: render };
})(typeof window !== 'undefined' ? window : this);
