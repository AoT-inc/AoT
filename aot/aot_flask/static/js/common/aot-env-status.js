/**
 * aot-env-status.js
 *
 * 통합환경제어 설정 화면의 **머리말** — 지금 무엇을 하고 있고 목표는 어디 있나.
 * 설계: `docs/design/env-coordinator-settings-redesign.md` §3-1 (단계 A).
 *
 * ## 왜 있나
 *
 * 설정 화면이 "어떤 값을 설정했나" 만 보여 주고 **"그래서 어떻게 도는가" 는
 * 다른 화면(지도 위젯 모달)에 있었다.** 62개를 설정하고 저장했는데 결과를
 * 확인할 방법이 없으면 설정이 맞는지 알 수 없고, **확인할 수 없는 것은 믿을
 * 수 없다.**
 *
 * 그리고 목표(VPD·온도 곡선)는 이 화면이 아니라 **구획에 붙은 프로그램**이
 * 갖는데, 화면이 그 사실을 말하지 않아 사용자가 "몇 도로 맞출까" 를 여기서
 * 찾으면 영영 못 찾는다.
 *
 * ## ⚠ 못 도는 상태도 말한다
 *
 * 침묵하면 "아직 안 붙었다" 와 "붙었는데 안 돈다" 를 구분할 수 없다. 시설
 * 미선택 · 응답 없음 · 비활성을 각각 다른 문장으로 말한다.
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

  /** 상대 시각 — "3분 전". 절대 시각은 이 자리에서 읽을 이유가 없다. */
  function ago(ts) {
    if (!ts) return '';
    var s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 60)   return _t('%(n)s s ago').replace('%(n)s', s);
    if (s < 3600) return _t('%(n)s min ago').replace('%(n)s', Math.round(s / 60));
    return _t('%(n)s h ago').replace('%(n)s', Math.round(s / 3600));
  }

  var KIND_LABEL = {
    opening: 'Vents', heater: 'Heating', cooler: 'Cooling',
    fogger: 'Misting', curtain: 'Curtain', shade: 'Shade',
    exhaust_fan: 'Exhaust fan', intake_fan: 'Intake fan',
    circulation_fan: 'Circulation fan', lighting: 'Lighting',
    co2_injector: 'CO₂'
  };

  // ⚠ **새 CSS 를 만들지 않는다.** 이 화면의 공용 골격(`aot-modal-*`)을 그대로
  //    쓴다 — 설정 행과 같은 자리·같은 간격이라야 머리말이 이 화면의 일부로
  //    읽힌다. 자체 클래스를 만들면 화면마다 모양이 갈린다.

  function line(text, muted) {
    return '<div class="aot-modal-option-row"><div class="aot-modal-body-text">' +
           esc(text) + '</div></div>';
  }

  /** 라벨 + 값 한 줄 — 설정 행과 같은 골격. */
  function row(label, value, raw) {
    return '<div class="aot-modal-option-row">' +
           '<div class="aot-modal-option-label">' + esc(label) + '</div>' +
           '<div class="aot-modal-option-control">' +
           (raw ? value : esc(value)) + '</div></div>';
  }

  /* ── 여긴 **설정하는 곳**이다 ─────────────────────────────────────────
   *
   * 2026-08-27 사용자 지적: *"옵션 초반에 정보가 너무 많아. 이미 설정에서
   * 사용자가 결정하는데 여기서 또 안내하고 있어. 여긴 설정하는 곳이지
   * 확인하는 곳은 아니야."*
   *
   * 예전에는 카드 둘(지금 · 목표는 어디서 정하나)이 변수마다 한 줄씩,
   * 구획마다 한 줄씩 냈다 — 설정을 시작하기 전에 열 줄을 읽어야 했다.
   * 지금은 **두 줄**이고, 자리도 맨 위가 아니라 [연동 시설] **바로 아래**다
   * (*"설정하고 그 위치에서 확인"*).
   *
   * 그래도 지우지 않는 이유: 시설을 안 고르면 나머지 설정이 전부 무의미한데,
   * 침묵하면 사용자가 다 채우고도 왜 안 도는지 모른다.
   */

  /** 한 줄로 잇는다 — 라벨 + 값들. 값이 없으면 아무것도 안 낸다. */
  function compact(label, parts) {
    if (!parts.length) return '';
    return row(label, parts.join('  ·  '));
  }

  /* ── 구획이 **끝나는 날** ────────────────────────────────────────────────
   *
   * 2026-09-01 부로 코디네이터에는 "이 날 이후 제어 정지" 라는 별도 옵션
   * (`schedule_end_time`)이 없다 — 구획을 새로 심어도 그 날짜를 사람이 다시
   * 고치기 전까지 계속 멈춰 있던 것이 실제 사고였다(2026-08-30 영양·
   * 쿠마모토, 구획을 갈아 심었는데도 8월 31일 종료로 굳어 있었다). 이제
   * 지속 여부는 구획 자체가 정한다 — 구획이 끝나면(또는 없으면) 코디네이터는
   * **멈추지 않고** guide 범위로 계속 돈다. 그래서 이 줄은 "제어가 멈춘다"
   * 가 아니라 **"이 구획이 끝난다"**(그 뒤엔 다음 구획이나 guide 범위로
   * 넘어간다)는 사실만 말한다.
   *
   * `end_confirmed` 로 확정(구획의 `ended_on`, 사람이 수확 등으로 확정한
   * 날)과 예상(`expected_end_on`, 진행 중인 구획의 어림값)을 가른다 — 어림값을
   * 확정처럼 말하면 예상이 며칠 어긋날 때마다 화면이 거짓말을 한 셈이 된다.
   *
   * ⚠ **평소에는 아무 말도 하지 않는다.** 늘 보이면 그냥 한 줄이 되어, 정작
   *   임박했을 때 눈에 안 띈다. 2주 안쪽일 때만 말한다(지난 날짜는 R2 가
   *   이미 그 구획을 걷어내 `sched.end` 자체가 안 온다).
   */
  var _ENDS_SOON_DAYS = 14;

  function endsLine(d) {
    var sched = (((d.env || {}).summary || {}).schedule) || {};
    var raw = sched.end;
    if (!raw) return '';
    var t = Date.parse(raw + 'T23:59:59');
    if (isNaN(t)) return '';
    var days = Math.floor((t - Date.now()) / 86400000);
    if (days > _ENDS_SOON_DAYS || days < 0) return '';
    var txt = sched.end_confirmed
      ? _t('Ends on {date}').replace('{date}', raw)
      : _t('Expected to end around {date}').replace('{date}', raw);
    return row(_t('This plot'), esc(txt), true);
  }

  function nowLine(d) {
    var env = d.env || {};
    var fn = env.function;
    if (!fn) return line(_t('No integrated environment control is linked to this facility.'));
    if (!fn.active) {
      var other = env.other_coordinator;
      // 같은 시설을 가리키는 코디네이터가 둘일 때 — 왜 꺼져 있는데 시설은
      // 돌고 있는지 답이 없으면 사용자가 스위치를 찾아 헤맨다.
      if (other && other.name) {
        return line(_t('Control is switched off. This facility is run by: {name}')
                    .replace('{name}', other.name));
      }
      return line(_t('Control is switched off.'));
    }
    if (env.stale) {
      // ⚠ "응답 없음" 과 "꺼짐" 은 다른 사실이다. 뭉치면 스위치를 찾아 헤맨다.
      // ⚠ **"몇 분" 이라고 말하지 말 것.** 기준은 `max(300초, 제어주기×3)` 이라
      //   10분 주기 코디네이터에서는 30분이다 — 뭉뚱그리면 사용자가 3분 뒤에
      //   다시 보고 "여전히 멈춰 있다" 고 판단한다. 서버가 보낸 실제 기준을 쓴다.
      var after = Number(env.stale_after_s);
      if (isFinite(after) && after > 0) {
        return line(_t('Control seems stopped — no decision for over {n} min.')
                    .replace('{n}', String(Math.round(after / 60))));
      }
      return line(_t('Control seems stopped — no recent decision.'));
    }
    var s = env.summary || {};
    var dev = s.deviation || {}, tg = s.targets || {}, parts = [];
    Object.keys(dev).forEach(function (k) {
      var target = tg[k], delta = Number(dev[k]);
      if (target == null || isNaN(delta)) return;
      // 편차는 측정−목표다. 사용자에게는 "지금 값 → 목표" 가 읽기 쉽다.
      var cur = Math.round((Number(target) + delta) * 100) / 100;
      parts.push(k.toUpperCase() + ' ' + cur + '\u2192' + target);
    });
    var kinds = s.outputs_by_kind || {};
    Object.keys(kinds).sort().forEach(function (k) {
      parts.push(_t(KIND_LABEL[k] || k) + ' ' + Math.round(Number(kinds[k])) + '%');
    });
    if (env.last_cycle_ts) parts.push(ago(env.last_cycle_ts));
    return parts.length ? compact(_t('Now'), parts)
                        : line(_t('Has not run a cycle yet.'));
  }


  function render(el, d) {
    if (!d || !d.ok) {
      el.innerHTML = line(_t('Could not read the current state.'));
      return;
    }
    if (!d.facility) {
      // 시설 미선택 — **아무것도 내지 않는다.** 바로 위가 [연동 시설] 이라
      // 고르라는 말이 그 자리에 이미 있다. 예전에는 맨 위에 있어서 안내가
      // 필요했다.
      el.innerHTML = '';
      return;
    }
    // 구획·목표는 바로 아래 요약이 말한다 — 같은 사실을 두 곳이
    // 각자 적으면 어느 쪽이 최신인지 사람이 판단해야 한다.
    el.innerHTML = nowLine(d) + endsLine(d);
  }

  function load(el) {
    var uid = el.getAttribute('data-function-id');
    if (!uid) return;
    el.innerHTML = '';   // 로딩 문구도 소음이다 — 두 줄짜리를 기다릴 이유가 없다
    fetch('/api/aot/coordinator/' + encodeURIComponent(uid) + '/overview',
          {cache: 'no-store', credentials: 'same-origin'})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { render(el, d); })
      .catch(function () { render(el, null); });
  }

  function init(root) {
    (root || document).querySelectorAll('.aot-env-status').forEach(function (el) {
      if (el._aotEnvWired) return;
      el._aotEnvWired = true;
      load(el);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); });
  } else {
    init();
  }
  // 설정 폼은 나중에 DOM 에 꽂히기도 한다(함수 카드를 펼칠 때).
  window.AoTEnvStatus = {init: init, reload: load};
})();
