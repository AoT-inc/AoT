/**
 * aot-chart-core.js — Highcharts 공용 헬퍼 (1st-party)
 *
 * Highcharts/Highstock 차트를 쓰는 모든 위젯·페이지가 공유하는 코어 유틸.
 * Highcharts 로드 이후라면 어디서든 사용 가능하며, 로드 시점에는
 * Highcharts를 참조하지 않으므로 include 순서에 민감하지 않다.
 *
 * 사용법:
 *   <script src="/static/js/vendor/user_js/highstock-9.1.2.js"></script>
 *   <script src="/static/js/common/aot-chart-core.js"></script>
 *
 *   // 1) 전역 기본값 (페이지당 1회, 중복 호출 안전)
 *   AoTChart.applyGlobalDefaults();
 *
 *   // 2) 스크롤 중 redraw 지연 (스크롤 jank 방지)
 *   AoTChart.deferWhileScrolling(function () { chart.redraw(); });
 *
 *   // 3) 다중 y축 자동 조정 — chart 이벤트에 연결
 *   new Highcharts.StockChart({
 *     chart: {
 *       events: {
 *         render: function () { AoTChart.axisAdjust(this, { hideOnMobile: true }); }
 *       }
 *     },
 *     yAxis: [ AoTChart.unitYAxis({ id: 'C', unit: '°C', fontSizeEm: 1.0 }), ... ]
 *   });
 */
(function (window) {
  'use strict';

  const AoTChart = window.AoTChart = window.AoTChart || {};

  /**
   * Highcharts 전역 기본값: 로컬 타임존, 애니메이션 비활성,
   * 시리즈 색상 불투명도 0.6. 여러 위젯이 호출해도 1회만 적용된다.
   */
  AoTChart.applyGlobalDefaults = function () {
    if (AoTChart._defaultsApplied || typeof window.Highcharts === 'undefined') return;
    AoTChart._defaultsApplied = true;
    const Highcharts = window.Highcharts;
    Highcharts.setOptions({
      global: { useUTC: false },
      chart: { animation: false },
      plotOptions: { series: { animation: false } }
    });
    Highcharts.getOptions().colors = Highcharts.getOptions().colors.map(function (color) {
      return Highcharts.Color(color).setOpacity(0.6).get('rgba');
    });
  };

  // ----- 스크롤 jank 가드 -------------------------------------------------

  let scrollActive = false;
  let scrollTimer = null;
  let scrollHooked = false;

  function hookScroll() {
    if (scrollHooked) return;
    scrollHooked = true;
    window.addEventListener('scroll', function () {
      scrollActive = true;
      clearTimeout(scrollTimer);
      scrollTimer = setTimeout(function () { scrollActive = false; }, 150);
    }, { passive: true });
  }

  /** 사용자가 스크롤 중인지 여부 (150ms 디바운스). */
  AoTChart.isScrolling = function () {
    hookScroll();
    return scrollActive;
  };

  /**
   * 스크롤 중이면 fn 실행을 스크롤이 멎을 때까지 rAF로 미룬다.
   * 무거운 chart.redraw() 호출을 감싸는 용도.
   */
  AoTChart.deferWhileScrolling = function (fn) {
    hookScroll();
    if (scrollActive) {
      requestAnimationFrame(function () { AoTChart.deferWhileScrolling(fn); });
      return;
    }
    fn();
  };

  // ----- 다중 y축 자동 조정 -----------------------------------------------

  /**
   * 단위 타이틀을 가로로 눕혀 쓰는 y축 옵션 팩토리.
   * axisAdjust()와 짝을 이루는 기본 구성을 돌려준다 (필요 시 덮어쓰기).
   *
   * opts: { id, unit, fontSizeEm = 1.0, titleFontSizeEm = fontSizeEm,
   *         opposite = false, extra = {} }
   */
  AoTChart.unitYAxis = function (opts) {
    const fontSizeEm = opts.fontSizeEm || 1.0;
    const base = {
      title: {
        text: opts.unit,
        align: 'high',
        rotation: 0,
        offset: 0,
        y: -6,
        textAlign: 'center',
        reserveSpace: false,
        style: {
          fontSize: (opts.titleFontSizeEm || fontSizeEm) + 'em',
          color: 'var(--aot-color-text-secondary, #666666)',
          opacity: 0.8
        }
      },
      labels: {
        x: opts.opposite ? 8 : -8,
        style: { fontSize: fontSizeEm + 'em', color: 'var(--aot-color-text-secondary, #666666)' }
      },
      showEmpty: false,
      opposite: !!opts.opposite,
      id: opts.id
    };
    return Object.assign(base, opts.extra || {});
  };

  /**
   * 다중 y축 차트의 렌더 후처리. chart.events.render 에서 호출한다.
   *
   * 1. 모바일 토글: 차트 폭이 breakpoint(기본 480px) 미만이면 모든 축의
   *    틱 라벨과 단위 타이틀을 숨기고, 다시 넓어지면 복원한다.
   *    (Highcharts responsive 규칙은 다중 축 배열 옵션을 첫 축에만
   *    적용하고 복원도 실패하므로 직접 처리)
   * 2. 단위 배치: 각 y축의 단위 타이틀을 그 축의 최하단 틱 라벨 아래,
   *    x축 시간 라벨과 같은 행에 중앙 정렬로 배치한다. 첫 x축 라벨이나
   *    차트 왼쪽 경계, 이웃 단위와 겹치면 왼쪽으로 밀어 같은 행을 유지.
   *
   * opts: { hideOnMobile = true, breakpoint = 480 }
   */
  AoTChart.axisAdjust = function (chart, opts) {
    opts = opts || {};
    const hideOnMobile = opts.hideOnMobile !== false;
    const breakpoint = opts.breakpoint || 480;

    if (chart._aotAxisBusy) return;

    // 차트 초기화 시점에 컨테이너 레이아웃이 아직 확정되지 않으면(그리드 배치 등)
    // Highcharts가 실제보다 좁은 폭으로 크기를 고정해버릴 수 있다. redraw()는
    // 컨테이너를 재측정하지 않으므로, 최초 1회에 한해 실제 폭과 어긋나면 reflow로 바로잡는다.
    if (!chart._aotSizeChecked) {
      chart._aotSizeChecked = true;
      const containerWidth = chart.renderTo ? chart.renderTo.clientWidth : 0;
      if (containerWidth && Math.abs(containerWidth - chart.chartWidth) > 2) {
        chart.reflow();
        return;
      }
    }

    const hide = !!(hideOnMobile && chart.chartWidth < breakpoint);
    if (hide !== !!chart._aotAxesHidden) {
      chart._aotAxisBusy = true;
      chart.xAxis.concat(chart.yAxis).forEach(function (ax) {
        if ((ax.options.id || '').indexOf('navigator') === 0) return;
        ax.update({
          labels: { enabled: !hide },
          title: { style: { display: hide ? 'none' : '' } }
        }, false);
      });
      chart._aotAxesHidden = hide;
      chart.redraw();
      chart._aotAxisBusy = false;
    }
    if (hide) return;

    // x축 시간 라벨 행의 y, 그리고 첫 시간 라벨의 왼쪽 경계
    let xRowY = null, xRowLeft = null;
    const xa = chart.xAxis[0];
    if (xa && xa.tickPositions) {
      xa.tickPositions.forEach(function (pos) {
        const tick = xa.ticks[pos];
        if (!tick || !tick.label) return;
        const y = tick.label.attr('y');
        if (y <= 0) return;  // 화면 밖 라벨은 y -9999에 파킹됨
        if (xRowY === null) xRowY = y;
        const left = tick.label.attr('x') - tick.label.getBBox().width / 2;
        if (xRowLeft === null || left < xRowLeft) xRowLeft = left;
      });
    }
    if (xRowY === null) xRowY = chart.plotTop + chart.plotHeight + 16;

    const placed = [];
    chart.yAxis.forEach(function (ax) {
      const title = ax.axisTitle;
      if (!title || !ax.labelGroup) return;
      if ((ax.options.id || '').indexOf('navigator') === 0) return;
      if (!ax.tickPositions || !ax.tickPositions.length) return;
      const titleBox = title.getBBox();
      // 실제 렌더된 최하단 틱 라벨 (틱 위치 배열은 플롯 밖까지 포함될 수 있음)
      let bottomLabel = null, bottomLabelY = null;
      ax.tickPositions.forEach(function (pos) {
        const tick = ax.ticks[pos];
        if (!tick || !tick.label) return;
        const y = tick.label.attr('y');
        if (y >= chart.plotTop - 4 && (bottomLabelY === null || y > bottomLabelY)) {
          bottomLabelY = y;
          bottomLabel = tick.label;
        }
      });
      if (!bottomLabel) return;
      let x = bottomLabel.attr('x') - bottomLabel.getBBox().width / 2;
      if (xRowLeft !== null && x + titleBox.width / 2 > xRowLeft - 4) {
        x = xRowLeft - 4 - titleBox.width / 2;
      }
      if (x - titleBox.width / 2 < 2) x = 2 + titleBox.width / 2;
      placed.push({ title: title, x: x, y: xRowY, w: titleBox.width, h: titleBox.height });
    });

    // 겹침은 왼쪽으로 밀어 같은 행 유지
    placed.sort(function (a, b) { return b.x - a.x; });
    for (let i = 1; i < placed.length; i++) {
      const right = placed[i - 1], cur = placed[i];
      const maxX = right.x - right.w / 2 - 4 - cur.w / 2;
      if (cur.x > maxX) cur.x = Math.max(maxX, 2 + cur.w / 2);
    }
    placed.forEach(function (p) {
      p.title.attr({ x: p.x, y: p.y });
    });
  };
})(window);
