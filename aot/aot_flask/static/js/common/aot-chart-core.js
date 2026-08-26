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
    AoTChart.applyLangDefaults();
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

  // ----- 날짜·시간 현지화 -------------------------------------------------
  //
  // Highcharts 는 월/요일 이름과 날짜 라벨 서식을 **영어로 하드코딩**해 들고 있다
  // (lang.months = "January February …", xAxis 일 라벨 = '%e. %b').
  // 그래서 앱 UI 를 한국어로 써도 그래프 축은 "5. Aug", 툴팁은 "August 5, 2026"
  // 으로 나왔다. 위젯마다 lang 을 따로 넣으면 화면마다 갈리므로 여기 한 곳에서만
  // 세운다 — layout 이 심어 주는 전역 번역 함수 window._() 를 그대로 쓴다.
  //
  // 서식 문자열(`%e. %b` 등)까지 번역 대상인 이유: 이름만 바꾸면 "5. 8월" 처럼
  // 어순이 영어로 남는다. 로케일마다 연·월·일 순서가 다르므로 서식 자체가
  // 번역돼야 한다.

  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November', 'December'];
  const SHORT_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday',
                    'Thursday', 'Friday', 'Saturday'];
  const SHORT_WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  /** 전역 번역 함수. 카탈로그가 아직 없으면 영어 원문 그대로. */
  function t(key) {
    return (typeof window._ === 'function') ? window._(key) : key;
  }
  AoTChart.t = t;

  /**
   * 번역된 날짜·시간 서식 문자열 (Highcharts strftime 문법).
   * msgid 는 Highcharts 기본값 그대로라, 번역이 없는 언어는 원래 모습으로 남는다.
   */
  AoTChart.dateFormats = function () {
    return {
      dayLabel: t('%e. %b'),          // 축: 일/주 눈금
      monthLabel: t("%b '%y"),        // 축: 월 눈금
      yearLabel: '%Y',
      dateTime: t('%Y-%m-%d %H:%M:%S'),   // 툴팁: 전체 일시
      date: t('%Y-%m-%d'),                // 툴팁: 날짜만
      time: '%H:%M'
    };
  };

  /**
   * 타임스탬프(ms)를 현지화된 일시 문자열로. opts.ms=true 면 밀리초까지.
   * 그래프 툴팁의 `Highcharts.dateFormat('%B %e, %Y %H:%M:%S.', x)` 하드코딩을
   * 대체한다.
   */
  AoTChart.formatDateTime = function (timestamp, opts) {
    opts = opts || {};
    const f = AoTChart.dateFormats();
    let out = (typeof window.Highcharts !== 'undefined')
      ? window.Highcharts.dateFormat(f.dateTime, timestamp)
      : new Date(timestamp).toISOString();
    if (opts.ms) {
      const ms = new Date(timestamp).getMilliseconds();
      out += '.' + String(ms).padStart(3, '0');
    }
    return out;
  };

  /**
   * Highcharts 전역 lang·날짜 라벨 서식을 현재 언어로 세운다.
   * applyGlobalDefaults() 가 자동으로 부른다.
   */
  AoTChart.applyLangDefaults = function () {
    if (AoTChart._langApplied || typeof window.Highcharts === 'undefined') return;
    AoTChart._langApplied = true;

    // Highcharts 의 `%e`(일)는 한 자리 날짜 앞에 공백을 넣는다. 영어 기본값
    // '%e. %b' 에서는 라벨 맨 앞이라 눈에 안 띄지만, 날짜가 가운데 오는 언어에서는
    // "8월  5일" 처럼 사이가 벌어진다. 한 자리 날짜를 안 채우도록 바꾼다 —
    // 다른 토큰(%d)은 0 을 채우므로 "8월 05일" 이 되어 더 나쁘다.
    // 차트의 Time 인스턴스(this)를 거쳐야 useUTC/타임존 설정을 따라간다.
    window.Highcharts.dateFormats.e = function (timestamp) {
      return this.get('Date', new this.Date(timestamp));
    };

    const f = AoTChart.dateFormats();
    // 기본 툴팁용 서식 묶음. msgid 는 Highcharts 기본값 그대로다.
    const fmt = {
      ms: t('%A, %b %e, %H:%M:%S.%L'),
      sec: t('%A, %b %e, %H:%M:%S'),
      time: t('%A, %b %e, %H:%M'),
      date: t('%A, %b %e, %Y'),
      dateShort: t('%A, %b %e'),
      week: t('Week from %A, %b %e, %Y'),
      month: t('%B %Y')
    };
    window.Highcharts.setOptions({
      lang: {
        months: MONTHS.map(t),
        shortMonths: SHORT_MONTHS.map(t),
        weekdays: WEEKDAYS.map(t),
        shortWeekdays: SHORT_WEEKDAYS.map(t),
        rangeSelectorZoom: t('Zoom'),
        resetZoom: t('Reset zoom'),
        resetZoomTitle: t('Reset zoom level 1:1'),
        loading: t('Loading...'),
        noData: t('No data to display')
      },
      xAxis: {
        dateTimeLabelFormats: {
          day: { main: f.dayLabel },
          week: { main: f.dayLabel },
          month: { main: f.monthLabel },
          year: { main: f.yearLabel }
        }
      },
      // 자체 formatter 가 없는 차트(지도 위젯의 베이 모달·팝업 인라인 차트 등)가
      // 쓰는 기본 툴팁 서식. 이름만 번역하면 "수요일, 8월 13, 14:20" 처럼 어순이
      // 영어로 남으므로 서식 자체를 번역 대상으로 둔다. msgid 는 Highcharts
      // 기본값 그대로이고, 조각을 이어붙이면 어순을 바꾼 번역에서 깨지므로
      // 단위별로 완성된 서식 하나씩을 쓴다.
      tooltip: {
        dateTimeLabelFormats: {
          millisecond: fmt.ms,
          second: fmt.sec,
          minute: fmt.time,
          hour: fmt.time,
          day: fmt.date,
          week: fmt.week,
          month: fmt.month,
          year: '%Y'
        }
      },
      // **여기까지만 하면 지도 모달 툴팁은 안 바뀐다.** 데이터가 묶인(dataGrouping)
      // 시리즈는 툴팁 머리글을 tooltip.dateTimeLabelFormats 가 아니라 이쪽에서
      // 가져온다 — 값도 `[전체, 시작, 끝]` 3원소 배열이라 모양까지 다르다.
      // 실측으로 확인했다(베이 모달이 5분 묶음이라 "12:30-12:34" 로 나온다).
      plotOptions: {
        series: {
          dataGrouping: {
            dateTimeLabelFormats: {
              millisecond: [fmt.ms, fmt.ms, '-%H:%M:%S.%L'],
              second: [fmt.sec, fmt.sec, '-%H:%M:%S'],
              minute: [fmt.time, fmt.time, '-%H:%M'],
              hour: [fmt.time, fmt.time, '-%H:%M'],
              day: [fmt.date, fmt.dateShort, '-' + fmt.date],
              week: [fmt.week, fmt.dateShort, '-' + fmt.date],
              month: [fmt.month, '%B', '-' + fmt.month],
              year: ['%Y', '%Y', '-%Y']
            }
          }
        }
      }
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

  // ----- 지속시간(초) 값 표시 ---------------------------------------------
  //
  // 출력(액추에이터)의 작동 시간은 `duration_time` 측정으로 단위가 's' 다.
  // 그대로 찍으면 "4234 s" 라 사람이 읽어서 시:분:초를 암산해야 했다.
  // 단위가 's' 인 값은 축 눈금·툴팁·범례 어디서든 HH:MM:SS 로 쓴다.
  //
  // 초 → HH:MM:SS 의 정본은 aot-time-utils.js(window.AoTTime)다. 여기 폴백을
  // 두는 이유는 chart-core 가 layout 밖(위젯 head)에서도 실리기 때문이고,
  // 폴백이 정본과 갈라지지 않도록 서식은 한 줄로만 유지한다.

  AoTChart.isDurationUnit = function (unit) {
    if (window.AoTTime && window.AoTTime.isDurationUnit) {
      return window.AoTTime.isDurationUnit(unit);
    }
    return String(unit == null ? '' : unit).trim() === 's';
  };

  AoTChart.formatDuration = function (seconds) {
    if (window.AoTTime && window.AoTTime.formatDuration) {
      return window.AoTTime.formatDuration(seconds);
    }
    let total = Number(seconds);
    if (!isFinite(total) || total < 0) total = 0;
    const pad = function (n) { return n < 10 ? '0' + n : String(n); };
    return pad(Math.floor(total / 3600)) + ':' +
           pad(Math.floor((total % 3600) / 60)) + ':' +
           pad(Math.floor(total % 60));
  };

  /**
   * 시리즈 값 한 개를 화면 문자열로. 단위가 초면 HH:MM:SS(단위 접미사 없음),
   * 아니면 기존대로 숫자 + 단위.
   *   value    : 값
   *   suffix   : 시리즈의 tooltipOptions.valueSuffix (' °C', ' s' …)
   *   decimals : 소수 자릿수 (기본 2)
   */
  AoTChart.formatSeriesValue = function (value, suffix, decimals) {
    if (AoTChart.isDurationUnit(suffix)) {
      return AoTChart.formatDuration(value);
    }
    const dec = (decimals == null) ? 2 : decimals;
    const num = (typeof window.Highcharts !== 'undefined')
      ? window.Highcharts.numberFormat(value, dec)
      : String(value);
    return num + (suffix || '');
  };

  /** 툴팁/범례에서 포인트 하나를 그대로 넘길 때 쓰는 편의 래퍼. */
  AoTChart.formatPointValue = function (point, decimals) {
    const opts = (point.series && point.series.tooltipOptions) || {};
    const dec = (decimals != null) ? decimals
              : (opts.valueDecimals != null ? opts.valueDecimals : 2);
    return AoTChart.formatSeriesValue(point.y, opts.valueSuffix || '', dec);
  };

  // ----- 플롯 영역 높이 고정 ----------------------------------------------
  //
  // Highcharts 의 `chart.height` 는 **전체** 높이라 레전드·x축 라벨이 그 안에서
  // 자리를 먹는다. 그래서 시리즈가 늘어 레전드가 두세 줄이 되면 정작 그래프가
  // 눌린다. 지도 위젯 베이 모달 실측: 폭 308px·5시리즈에서 전체 191px 중 플롯이
  // 108px 뿐이었고, 시리즈가 적고 폭이 넓으면 230px 가까이 나왔다 — 같은 화면을
  // 열 때마다 그래프 크기가 두 배 넘게 달라져 값을 눈으로 비교할 수 없었다.
  //
  // 그래서 **플롯 높이를 목표로 잡고 전체 높이를 거기에 맞춰 늘린다.** 레전드가
  // 커지면 카드가 그만큼 길어질 뿐, 그래프 자체는 늘 같은 높이다.
  //
  // 레전드 높이는 렌더해 봐야 알 수 있으므로(줄바꿈이 폭에 달렸다) 생성 시점에
  // 계산할 수 없다 — render 이벤트에서 실측하고 그만큼 되키운다.

  const PLOT_LOCK_TOLERANCE = 1;   // 1px 미만 차이는 무시(진동 방지)
  const PLOT_LOCK_MAX_PASSES = 4;  // 되키움이 레전드 줄바꿈을 다시 바꿀 수 있다

  /**
   * chart 의 플롯(그리는 영역) 높이를 targetPx 로 고정한다.
   * chart.events.render 에서 호출한다 — 데이터·레전드·폭이 바뀔 때마다 다시 맞는다.
   */
  AoTChart.lockPlotHeight = function (chart, targetPx) {
    if (!chart || !targetPx || !chart.plotHeight) return;
    if (chart._aotPlotBusy) return;                     // setSize 재진입 방지

    // 목표나 폭이 바뀌면 되키움 횟수를 새로 센다
    if (chart._aotPlotTarget !== targetPx || chart._aotPlotWidth !== chart.chartWidth) {
      chart._aotPlotTarget = targetPx;
      chart._aotPlotWidth = chart.chartWidth;
      chart._aotPlotPasses = 0;
    }
    const diff = targetPx - chart.plotHeight;
    if (Math.abs(diff) <= PLOT_LOCK_TOLERANCE) return;
    if (chart._aotPlotPasses >= PLOT_LOCK_MAX_PASSES) return;
    chart._aotPlotPasses += 1;

    chart._aotPlotBusy = true;
    try {
      chart.setSize(null, chart.chartHeight + diff, false);
    } finally {
      chart._aotPlotBusy = false;
    }
  };

  // ----- 분할 툴팁의 시각 머리글을 위로 ------------------------------------
  //
  // Highstock 은 `tooltip.split` 이 기본 true 다. 시리즈 값은 각 선 옆에 붙고,
  // 시각(머리글)은 **x축 아래**에 따로 놓인다. 그 자리가 x축 눈금 라벨과 레전드
  // 위라서, 지도 위젯 모달에서 커서를 올리면 시각 상자가 레전드의 값들을 가렸다.
  //
  // Highcharts 가 머리글을 위로 올리는 조건은 `xAxis[0].opposite` 하나뿐인데
  // (renderSplit 의 headerTop), 그걸 켜면 x축 눈금 라벨까지 위로 옮겨간다.
  // 그래서 렌더 뒤에 머리글 상자만 플롯 안쪽 위로 옮긴다.
  //
  // 자리는 플롯 **안쪽 위**다. 위에 여백을 예약해 보기도 했는데, 툴팁을 띄우지
  // 않는 대부분의 시간에는 그냥 빈 공간이라 되돌렸다 — 툴팁이 그래프 위를 잠깐
  // 덮는 것은 정상 동작이고, 문제였던 것은 플롯 **바깥** 컨텐츠를 가리는 쪽이다.
  //
  // **anchorY 를 건드리지 말 것.** 말풍선 꼬리 방향은 Highcharts 의 callout 심볼이
  // anchorY 와 상자의 관계로 정한다 — `anchorY <= 상자top` 이면 위쪽 꼬리,
  // `anchorY >= 상자bottom` 이면 아래쪽 꼬리다. Highcharts 가 머리글에 넣어 두는
  // anchorY 는 플롯 중앙이므로, 상자가 아래에 있을 때는 자연히 위를 가리켰다.
  // 상자를 위로 올리면 그대로 아래를 가리켜야 맞는데, 꼬리를 없앨 셈으로
  // anchorY 를 상자 안(=상자top)에 넣었더니 '위쪽 꼬리' 조건에 걸려 꼬리가
  // 그래프 반대쪽을 향했다. 그래서 원래 anchorY 를 **새 y 기준으로 다시 넣는다** —
  // 심볼이 쓰는 값은 (anchorY - 상자y) 라, y 만 바꾸면 옛 기준으로 굳는다.
  //
  // 프로토타입이 아니라 **차트 인스턴스의 refresh 만** 감싼다(다른 차트 영향 없음).
  // Highcharts 내부(tooltip.tt)가 바뀌면 조용히 원래 자리로 돌아간다.

  AoTChart.splitTooltipHeaderTop = function (chart) {
    const tip = chart && chart.tooltip;
    if (!tip || tip._aotHeaderTop) return;
    if (!tip.options || tip.options.split === false) return;
    tip._aotHeaderTop = true;
    const origRefresh = tip.refresh;
    tip.refresh = function () {
      origRefresh.apply(this, arguments);
      try {
        const header = this.tt;   // renderSplit 이 머리글 라벨을 여기에 둔다
        if (!header || !header.attr || !header.element) return;
        // 정말 머리글인지 클래스로 확인한다 — Highcharts 내부가 바뀌어 tt 가
        // 다른 상자를 가리키게 되면, 엉뚱한 값 상자를 위로 옮겨 버린다.
        const cls = header.element.getAttribute('class') || '';
        if (cls.indexOf('highcharts-tooltip-header') === -1) return;
        const y = chart.plotTop + 2;
        if (header.attr('y') === y) return;
        // anchorY 는 Highcharts 가 잡아 둔 값(플롯 중앙)을 그대로 다시 넣는다.
        // 값은 같지만 새 y 기준으로 다시 계산돼야 꼬리가 아래(그래프 쪽)를 본다.
        header.attr({ y: y, anchorY: header.anchorY });
      } catch (e) { /* 위치 보정 실패는 툴팁 자체를 막지 않는다 */ }
    };
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
    const axis = Object.assign(base, opts.extra || {});
    // 지속시간 축은 눈금도 HH:MM:SS 로. extra 가 labels 를 통째로 갈아끼우는
    // 호출부(graph-async)가 있어 **병합 뒤에** 얹는다. Highcharts 는 labels.format
    // 이 있으면 formatter 를 무시하므로 그 자리도 비운다.
    if (AoTChart.isDurationUnit(opts.unit) || AoTChart.isDurationUnit(opts.id)) {
      axis.labels = Object.assign({}, axis.labels);
      delete axis.labels.format;
      axis.labels.formatter = function () {
        return AoTChart.formatDuration(this.value);
      };
    }
    return axis;
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

  // ── 야간 음영 ────────────────────────────────────────────────────────────
  // 그래프는 하루를 균일한 축으로 그리지만 작물이 겪는 하루는 그렇지 않다.
  // 온도가 떨어진 구간이 밤이라 그런 것인지 차광 때문인지, 습도가 오른 시각이
  // 일몰 직후인지 한밤중인지는 축만 봐서는 알 수 없다. 보이는 구간의 밤을
  // 서버(/sun_bands, 태양시 커널)에서 받아 plotBand 로 깐다.
  const NIGHT_BAND_ID_PREFIX = 'aot-night-';
  const _nightCache = {};   // chartKey -> {key, bands}
  const _nightPending = {}; // chartKey -> true (요청 중복 방지)

  function _nightBandColor() {
    const probe = getComputedStyle(document.documentElement)
      .getPropertyValue('--aot-color-night-band');
    return (probe && probe.trim()) || 'rgba(120, 130, 150, 0.10)';
  }

  AoTChart.applyNightShading = function (chart, opts) {
    if (!chart || !chart.xAxis || !chart.xAxis[0]) return;
    opts = opts || {};
    const axis = chart.xAxis[0];
    const extremes = axis.getExtremes();
    let min = extremes.min, max = extremes.max;
    if (min == null || max == null || !(max > min)) return;

    // 축 범위를 분 단위로 반올림해 캐시 키를 만든다 — 마우스 드래그 중
    // 매 프레임 요청하지 않도록.
    const bucket = 60 * 1000;
    const key = Math.round(min / bucket) + ':' + Math.round(max / bucket) +
                ':' + (opts.targetId || '');
    const chartKey = chart.renderTo && chart.renderTo.id || 'chart';

    const cached = _nightCache[chartKey];
    if (cached && cached.key === key) {
      _drawNightBands(chart, cached.bands);
      return;
    }
    if (_nightPending[chartKey]) return;
    _nightPending[chartKey] = true;

    const params = new URLSearchParams({
      start: String(Math.round(min)),
      end: String(Math.round(max))
    });
    if (opts.targetId) params.set('target_id', opts.targetId);

    fetch('/sun_bands?' + params.toString(), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { bands: [] }; })
      .then(function (data) {
        const bands = (data && data.bands) || [];
        _nightCache[chartKey] = { key: key, bands: bands };
        _drawNightBands(chart, bands);
      })
      .catch(function () { /* 음영은 보조 정보 — 실패해도 그래프는 그대로 */ })
      .then(function () { _nightPending[chartKey] = false; });
  };

  function _drawNightBands(chart, bands) {
    const axis = chart.xAxis[0];
    if (!axis) return;
    (axis.plotLinesAndBands || []).slice().forEach(function (band) {
      if (band.id && String(band.id).indexOf(NIGHT_BAND_ID_PREFIX) === 0) {
        axis.removePlotBand(band.id);
      }
    });
    const color = _nightBandColor();
    bands.forEach(function (pair, i) {
      axis.addPlotBand({
        id: NIGHT_BAND_ID_PREFIX + i,
        from: pair[0],
        to: pair[1],
        color: color,
        zIndex: 0
      });
    });
  }
})(window);
