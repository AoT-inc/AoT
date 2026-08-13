/*
 * AoT polling visibility manager — battery optimization Step 2-A / Step 6 / Step 7
 *
 * [Step 2-A] Pause all setInterval polling when the page is in the background (document.hidden).
 * [Step 6]   Double the polling interval when low-power/data-saver mode is detected (halves battery/cellular load).
 * [Step 7]   On entering the background, add the aot-hidden class to document.documentElement
 *            to pause infinite animations such as .fa-spin via CSS.
 *
 * Operating principles:
 *  - Globally wrap setInterval/clearInterval to control all 21 widget types without modification.
 *  - The handle returned to the caller stays stable across pause/resume.
 *  - Non-function callbacks (string eval form) are not tracked and pass through natively.
 *  - Must be loaded before any other script (top of layout head).
 *
 * [Reconnect storm fix] Pausing is reason-based: the page is paused while ANY reason
 *  is active. The visibility manager uses the 'hidden' reason; aot-server-health.js uses
 *  the 'serverdown' reason to stop the polling flood while the server is unreachable.
 *  Exposed as window.AoTPoll = { pauseFor, resumeFor, isPaused }.
 */
(function () {
  if (window.__aotPollMgr) return;
  window.__aotPollMgr = true;

  var nativeSet = window.setInterval;
  var nativeClear = window.clearInterval;
  var nativeTimeout = window.setTimeout;
  var nativeClearTimeout = window.clearTimeout;

  var registry = new Map();  // handle -> { fn, delay, extra, realId, aligned }
  var paused = false;
  var seq = 2000000000;      // synthetic handle (native ids are never handed out — see below)

  /* ─── Step 6: adaptive interval multiplier ────────────────────── */
  var delayMult = 1;

  function calcDelayMult() {
    var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (!conn) return 1;
    if (conn.saveData) return 2;
    var t = conn.effectiveType || '';
    if (t === 'slow-2g' || t === '2g') return 2;
    return 1;
  }

  function applyDelayMult(newMult) {
    if (newMult === delayMult) return;
    delayMult = newMult;
    // Reschedule all running intervals (apply the new multiplier)
    registry.forEach(function (rec) {
      if (rec.realId != null) {
        stopTimer(rec);
        startTimer(rec);
      }
    });
  }

  delayMult = calcDelayMult();

  var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (conn) {
    conn.addEventListener('change', function () {
      if (!paused) applyDelayMult(calcDelayMult());
      else delayMult = calcDelayMult(); // while paused, only update the multiplier; applied on resume
    });
  }
  /* ────────────────────────────────────────────────────────────── */

  /* ─── 폴링 위상 정렬 (라디오 wakeup 코얼레싱) ───────────────────
   *
   * 위젯마다 자기가 초기화된 시각에 setInterval 을 걸기 때문에, 주기가 같아도
   * 발화 위상이 제각각이다. 5초 폴링 세 개가 각각 다른 오프셋에서 터지면 폰은
   * 5초 안에 라디오를 세 번 깨운다. 셀룰러는 요청이 끝나도 5~10초 동안 고전력
   * 상태로 남으므로(RRC tail), 이 흩어짐이 곧 발열이다.
   *
   * 그래서 발화 시점을 페이지 공통 격자(EPOCH + k×delay)에 스냅한다. 주기가
   * 배수 관계면(5/10/30/60초 — 실제로 위젯들이 쓰는 값들) 긴 주기는 항상 짧은
   * 주기가 이미 쓰는 tick 위에 떨어져, 자기 몫의 wakeup 을 새로 만들지 않는다.
   *
   * setInterval 대신 매번 다음 경계를 다시 예약하는 setTimeout 을 쓴다 —
   * setInterval 은 드리프트가 누적돼 오래 열어 둔 대시보드에서 정렬이 풀린다.
   *
   * 짧은 주기(ALIGN_MIN_MS 미만)는 대상이 아니다. 애니메이션·시계 틱 용도라
   * 정렬해도 얻는 것이 없고 스케줄 오버헤드만 는다.
   */
  var ALIGN_MIN_MS = 2000;
  var ALIGN_EPOCH = Date.now();

  function scheduleAligned(rec) {
    var delay = rec.delay * delayMult;
    var phase = ((Date.now() - ALIGN_EPOCH) % delay + delay) % delay;
    var wait = delay - phase;
    if (wait <= 0) wait += delay;
    rec.realId = nativeTimeout.call(window, function () {
      // 다음 경계를 **먼저** 예약한다. 콜백이 오래 걸려도 위상이 밀리지 않고,
      // 콜백이 던져도 루프가 죽지 않는다(native setInterval 과 같은 성질).
      scheduleAligned(rec);
      rec.lastRun = Date.now();
      rec.fn.apply(window, rec.extra);
    }, wait);
  }

  function startTimer(rec) {
    var delay = rec.delay * delayMult;
    if (!(delay >= ALIGN_MIN_MS)) {
      rec.aligned = false;
      // 추가 인자는 native 에 넘기지 않고 직접 적용한다 — lastRun 을 기록해야
      // 게이트가 풀릴 때 "한 주기 이상 쉬었는가" 를 판정할 수 있다.
      rec.realId = nativeSet.call(window, function () {
        rec.lastRun = Date.now();
        rec.fn.apply(window, rec.extra);
      }, delay);
      return;
    }
    rec.aligned = true;
    scheduleAligned(rec);
  }

  // 이 레코드가 지금 돌아야 하는가 — 전역 일시정지와 위젯 뷰포트 게이트의 논리곱.
  function shouldRun(rec) {
    if (paused) return false;
    if (rec.widget == null) return true;
    return isWidgetVisible(rec.widget);
  }

  function stopTimer(rec) {
    if (rec.realId == null) return;
    if (rec.aligned) nativeClearTimeout.call(window, rec.realId);
    else nativeClear.call(window, rec.realId);
    rec.realId = null;
  }
  /* ────────────────────────────────────────────────────────────── */

  /* ─── 위젯 뷰포트 게이팅 ────────────────────────────────────────
   *
   * 예전에는 "보이는가" 판정이 document.hidden(탭 전체) 하나뿐이었다. 폰에서
   * 대시보드는 세로로 길어(실측 375px 폭에서 3,550px) 위젯 11개 중 화면에 드는
   * 것은 한둘인데, 나머지가 전부 계속 폴링하고 Highcharts 를 다시 그렸다.
   * 레포 전체에 IntersectionObserver 사용처가 0건이었다.
   *
   * 이제 각 위젯의 grid-stack-item 을 관찰해, 화면 밖이면 그 위젯이 등록한
   * 인터벌을 멈춘다. 귀속은 dashboard_entry.html 이 위젯의 ready_end 를 실행하는
   * 동안 enterWidget/exitWidget 으로 표시해 준다 — 그 구간에 등록된 인터벌이
   * 그 위젯의 것이다. 위젯 코드는 건드리지 않는다.
   *
   * **한계:** 나중에(비동기 콜백·팝업 열기 등) 등록되는 인터벌은 귀속되지 않아
   * 게이트를 타지 않는다. 지도 위젯이 그 경우라 거기에는 자체 뷰포트 검사를
   * 따로 뒀다(aot-map-widget-vector.js `_isWidgetVisible`).
   *
   * rootMargin 으로 화면 밖 한 화면쯤은 미리 깨워 둔다 — 스크롤해서 도달한
   * 순간 빈 위젯을 보는 것보다 낫다.
   */
  var GATE_ROOT_MARGIN = '300px 0px';
  var gates = Object.create(null);   // uid -> { visible, recs: [], el }
  var currentWidget = null;
  var observer = null;

  function gateFor(uid) {
    if (!gates[uid]) gates[uid] = { visible: true, recs: [], el: null };
    return gates[uid];
  }

  function isWidgetVisible(uid) {
    var g = gates[uid];
    // 모르는 위젯은 "보인다" 로 본다. 관찰이 아직 첫 콜백을 못 받은 구간에서
    // 멈춰 버리면 최초 데이터가 늦어진다.
    return g ? g.visible : true;
  }

  function onGateChange(uid, visible) {
    var g = gates[uid];
    if (!g || g.visible === visible) return;
    g.visible = visible;
    g.recs.forEach(function (rec) {
      if (visible) {
        if (rec.realId == null && shouldRun(rec)) {
          startTimer(rec);
          // 멈춰 있던 동안 데이터가 낡았다. 한 주기를 통째로 기다리게 하지 않고
          // 즉시 한 번 채운다 — 단, 한 주기 이상 쉬었을 때만. 스크롤을 위아래로
          // 흔들 때마다 요청이 튀어나오는 것을 막는다.
          var delay = rec.delay * delayMult;
          if (rec.lastRun == null || (Date.now() - rec.lastRun) >= delay) {
            rec.lastRun = Date.now();
            try { rec.fn.apply(window, rec.extra); } catch (e) {}
          }
        }
      } else {
        stopTimer(rec);
      }
    });
  }

  function ensureObserver() {
    if (observer || typeof IntersectionObserver === 'undefined') return observer;
    observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var uid = entry.target.getAttribute('data-aot-poll-widget');
        if (uid) onGateChange(uid, entry.isIntersecting);
      });
    }, { rootMargin: GATE_ROOT_MARGIN });
    return observer;
  }

  function enterWidget(uid, el) {
    if (!uid) return;
    currentWidget = uid;
    var g = gateFor(uid);
    if (!g.el) {
      el = el || document.getElementById('gridstack_widget_' + uid);
      if (el) {
        g.el = el;
        el.setAttribute('data-aot-poll-widget', uid);
        var io = ensureObserver();
        if (io) io.observe(el);
      }
    }
  }

  function exitWidget() { currentWidget = null; }
  /* ────────────────────────────────────────────────────────────── */

  window.setInterval = function (fn, delay) {
    if (typeof fn !== 'function') {
      return nativeSet.apply(window, arguments);
    }
    var extra = Array.prototype.slice.call(arguments, 2);
    var rec = {
      fn: fn, delay: delay, extra: extra, realId: null, aligned: false,
      widget: currentWidget,   // ready_end 구간에 등록됐다면 그 위젯의 것
      lastRun: null
    };
    if (rec.widget) gateFor(rec.widget).recs.push(rec);
    // 핸들은 **항상** 합성값이다. 정렬 경로에서는 realId 가 tick 마다 새로 발급되므로
    // 그것을 핸들로 쓰면, 옛 핸들 번호가 재사용되는 순간 다른 레코드가 레지스트리에서
    // 덮어써져 원래 타이머가 영영 clear 되지 않는다.
    var handle = ++seq;
    if (shouldRun(rec)) startTimer(rec);
    registry.set(handle, rec);
    return handle;
  };

  window.clearInterval = function (handle) {
    var rec = registry.get(handle);
    if (rec) {
      registry.delete(handle);
      stopTimer(rec);
      if (rec.widget && gates[rec.widget]) {
        var list = gates[rec.widget].recs;
        var i = list.indexOf(rec);
        if (i >= 0) list.splice(i, 1);
      }
      return;
    }
    return nativeClear.call(window, handle);
  };

  // Reason-based pausing: paused while any reason is active.
  var pauseReasons = Object.create(null);

  function doPause() {
    if (paused) return;
    paused = true;
    registry.forEach(stopTimer);
  }

  function doResume() {
    if (!paused) return;
    paused = false;
    delayMult = calcDelayMult(); // apply the latest multiplier on resume
    // 탭이 돌아와도 **화면 밖 위젯은 그대로 재운다** — 전역 일시정지가 풀렸다고
    // 뷰포트 게이트까지 풀리면 게이팅이 탭 전환 한 번에 무력화된다.
    registry.forEach(function (rec) {
      if (rec.realId == null && shouldRun(rec)) startTimer(rec);
    });
  }

  function recompute() {
    var shouldPause = false;
    for (var k in pauseReasons) { if (pauseReasons[k]) { shouldPause = true; break; } }
    if (shouldPause) doPause(); else doResume();
  }

  function pauseFor(reason) { pauseReasons[reason] = true; recompute(); }
  function resumeFor(reason) { delete pauseReasons[reason]; recompute(); }

  // Backwards-compatible aliases (visibility uses the 'hidden' reason).
  function pauseAll() { pauseFor('hidden'); }
  function resumeAll() { resumeFor('hidden'); }

  window.AoTPoll = {
    pauseFor: pauseFor,
    resumeFor: resumeFor,
    isPaused: function () { return paused; },
    // 뷰포트 게이팅. enterWidget/exitWidget 은 dashboard_entry.html 이 위젯의
    // ready_end 를 감쌀 때 부른다. isWidgetVisible 은 비동기로 타이머를 거는
    // 위젯(지도)이 자기 판단에 쓰라고 공개한다.
    enterWidget: enterWidget,
    exitWidget: exitWidget,
    isWidgetVisible: isWidgetVisible
  };

  /* ─── Step 7: pause CSS animations while hidden ───────────────── */
  (function injectHiddenStyle() {
    var s = document.createElement('style');
    s.textContent =
      '.aot-hidden .fa-spin,' +
      '.aot-hidden [class*="fa-spin"],' +
      '.aot-hidden .spinner-border,' +
      '.aot-hidden .spinner-grow {' +
      'animation-play-state:paused!important}';
    (document.head || document.documentElement).appendChild(s);
  })();

  function setHiddenClass(hidden) {
    if (hidden) {
      document.documentElement.classList.add('aot-hidden');
    } else {
      document.documentElement.classList.remove('aot-hidden');
    }
  }
  /* ────────────────────────────────────────────────────────────── */

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      pauseAll();
      setHiddenClass(true);
    } else {
      resumeAll();
      setHiddenClass(false);
    }
  });

  if (document.hidden) {
    pauseReasons['hidden'] = true;
    paused = true;
    setHiddenClass(true);
  }
})();
