# coding=utf-8
#
#  AoT_plot.py — 구획(작기) 종합 모니터링 위젯
#
#  ## 왜 지도 위젯과 따로 있는가
#
#  지도 위젯은 **다용도**다 — "어디에 무엇이 있나" 를 답하고, 구획은 눌러야
#  나오며 팝업은 하나씩 열렸다 닫힌다. 이 위젯은 **목적 기반**이다: 재배·육종
#  처럼 목적물 하나를 계속 들여다보는 일에서, 그 구획의 지표를 대시보드에
#  상주시킨다.
#
#  그래서 **장치 제어는 담지 않는다.** 액추에이터·릴레이는 지도·시설 위젯의
#  일이고 여기 있는 것은 목적물의 상태와 그 일정뿐이다. 겹치면 같은 것을 두
#  위젯이 다르게 말하게 된다.
#
#  ## 화면의 계약
#
#  본체의 네 묶음은 **읽기 전용**이다. 고치는 일은 [편집] 모달 안에서만, 그것도
#  [저장]을 눌러야 나간다 — 단계 목표는 제어가 읽는 값이라
#  (`effective_stages → stage_of → control_targets`) 대시보드에서 스치듯 바뀌면
#  안 된다.
#
#  구현은 `static/js/widgets/AoT_plot/aot-plot-widget.js` 에 있다.
#
import json
import logging

from flask_babel import lazy_gettext

logger = logging.getLogger(__name__)


def execute_at_modification(mod_widget, request_form, custom_options_presave,
                            custom_options_postsave):
    """설정 폼 저장 — **선언하지 않은 값을 지우지 않는다.**

    고른 구획(`plot_uuid`)은 위젯 본체의 선택 상자가 `/save_widget_custom_options`
    로 직접 남긴다. 옵션 폼에는 그 칸이 없으므로(사람은 UUID 를 고르지 않는다),
    폼 저장이 기존 값 위에 postsave 만 덮어써야 그 선택이 살아남는다. 통째로
    갈아 끼우면 설정을 한 번 저장할 때마다 보고 있던 구획이 사라진다.
    """
    options = {}
    try:
        if mod_widget.custom_options:
            options = (json.loads(mod_widget.custom_options)
                       if isinstance(mod_widget.custom_options, str)
                       else dict(mod_widget.custom_options))
    except Exception:                                       # noqa: BLE001
        options = {}

    final = options.copy()
    if custom_options_postsave:
        for key, value in custom_options_postsave.items():
            final[key] = value
    return True, True, mod_widget, final


def widget_variables(widget_unique_id, widget_options):
    """템플릿 변수 — 저장된 선택과 표시 토글.

    구획 목록은 **여기서 만들지 않는다.** 위젯이 `/api/geo/plots` 를 직접 받고,
    그 응답은 같은 대시보드의 지도 위젯과 공유 캐시를 지난다(`AoTGeoData`) —
    서버가 따로 실어 보내면 그 한 번이 캐시를 비껴가고, 위젯이 열려 있는 동안
    목록이 낡아도 갱신할 길이 없다.

    권한도 여기서 판정하지 않는다. 구획을 고칠 수 있는가는 **그 구획 응답**이
    `can_edit` 으로 말한다(`/api/geo/plot/<uuid>`) — 위젯이 따로 판정하면 두
    곳이 갈리고, 그 갈라짐은 "눌러도 403" 으로만 드러난다.
    """
    options = widget_options or {}
    return {
        'plot_uuid': options.get('plot_uuid') or '',
        'refresh_minutes': options.get('refresh_minutes', 5),
        'gauge': options.get('gauge') or 'VPD',
        'show_progress': options.get('show_progress', True),
        'show_env': options.get('show_env', True),
        'show_trend': options.get('show_trend', True),
        'show_gdd': options.get('show_gdd', True),
    }


WIDGET_HEAD_HTML = """
{#- 공용 프리미티브(밴드·불릿·기간 바·편차 축)는 layout 이 이미 싣는다
    (`components/aot-dataviz.css`). 여기서 다시 걸지 않는다. -#}

{#- **카드 골격**(`.aot-ov-card-title` + `.aot-ov-block`) — 지도·시설 모달이
    쓰는 것과 같은 파일이다. 이것을 안 싣고 위젯이 자기 여백·배경을 적으면
    같은 성격의 화면이 앱 안에서 저마다 다른 카드가 된다. -#}
<link rel="stylesheet" href="{{ url_for('static', filename='css/widget/aot-sensor-label.css') }}">

{#- 편집 모달의 세 파일 — `/plots` 페이지와 **같은 정의**다. 하나라도 빠지면
    골격만 같고 긴 제목이 잘리거나 단계 트랙이 통째로 안 그려진다. -#}
<link rel="stylesheet" href="{{ url_for('static', filename='css/components/aot-stage-track.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/components/aot-drawer-form.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/components/aot-plot-form.css') }}">

<script src="{{ asset('aot-plot-widget') }}"></script>

<style>
  /* 여기 남는 것은 **이 위젯에만 있는 것**뿐이다 — 카드·여백·글자 크기는
     전부 공용 규칙(`.aot-ov-block` 등)이 정한다. 위젯이 그것을 다시 적으면
     같은 성격의 화면이 앱 안에서 저마다 다른 여백을 갖는다. */

  /* 카드 안 기준 글자 — **위젯 스케일**이다(`widget/aot-widget-typography.css`:
     sm 12 · md 14 · lg 24). `.aot-ov-block` 은 모달용이라 기준이
     `--aot-font-size-base`(15.2px)인데, 그대로 두면 라벨-값 한 줄이 39px 이
     되어 값 네 개에 카드가 한 뼘 커진다(2026-08-28 실측). 크기만 위젯
     기준으로 낮춘다 — 여백·정렬·구분선은 공용 규칙 그대로다. */
  .aot-plotw .aot-ov-block { font-size: var(--aot-fs-md); }

  /* 머리(선택 + 편집)는 고정, 본체만 흐른다.
     좌우 여백은 **카드와 같은 값**이다(--aot-space-4) — 안 주면 머리줄만
     카드 경계에 붙어 아래 카드들과 세로선이 안 맞는다. */
  .aot-plotw { display: flex; flex-direction: column; height: 100%; }
  .aot-plotw-head {
    display: flex;
    align-items: center;
    gap: var(--aot-space-2);
    padding: 0 var(--aot-space-4) var(--aot-space-3);
    flex: 0 0 auto;
  }
  .aot-plotw-pick { flex: 1 1 auto; min-width: 0; }

  /* 본체는 스크롤하되 **스크롤바는 보이지 않는다**(앱 전역 규칙). */
  .aot-plotw-body {
    flex: 1 1 auto;
    overflow-y: auto;
    scrollbar-width: none;
    -ms-overflow-style: none;
  }
  .aot-plotw-body::-webkit-scrollbar { width: 0; height: 0; display: none; }
  /* 마지막 카드의 아래 여백은 카드가 아니라 본체 끝이 정한다. */
  .aot-plotw-body > .aot-ov-block:last-child { margin-bottom: 0; }

  /* 전환 대기 — 카드 안에서 한 줄로 선다(카드 자체는 공용 규칙이 그린다). */
  .aot-plotw-ask {
    display: flex;
    align-items: center;
    gap: var(--aot-space-2);
    flex-wrap: wrap;
  }
  .aot-plotw-ask-text { flex: 1 1 auto; min-width: 0; }
  .aot-plotw-ask-date { width: auto; flex: 0 0 auto; }

  /* 지침 — **두 줄까지만**. 전문은 title 과 편집 모달에 있다. */
  .aot-plotw-guide {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    color: var(--aot-color-text-secondary);
  }

  /* 단계 세부 — 축 **바로** 아래. 기본은 현재 단계이고, 축에서 다른 구간을
     누르면 그 단계로 바뀐다.
     ⚠ 여백을 벌리지 않는다. 한때 위아래 16px + 구분선을 줬다가 되돌렸다 —
     축과 그 단계의 내용은 **한 덩이**라 떼어 놓을 이유가 없고, 벌린 만큼
     카드만 커졌다(2026-08-28 지적). */
  .aot-plotw-stage { margin-top: var(--aot-space-2); }
  .aot-plotw-stage-head {
    display: flex;
    align-items: baseline;
    gap: var(--aot-space-2);
    flex-wrap: wrap;
    font-size: var(--aot-font-size-xs);
    color: var(--aot-color-text-secondary);
  }
  .aot-plotw-stage-head b {
    font-size: var(--aot-font-size-sm);
    color: var(--aot-color-text-primary);
  }
  /* [지금 단계로] — 글자 링크다. 버튼 모양을 주면 카드 안에 누를 것이 둘
     (편집·되돌리기)이 되어 무엇이 주된 행동인지 흐려진다. */
  .aot-plotw-stage-back {
    margin-left: auto;
    padding: 0;
    border: 0;
    background: none;
    color: var(--aot-color-text-secondary);
    text-decoration: underline;
    font-size: var(--aot-font-size-xs);
    cursor: pointer;
  }
  .aot-plotw-stage .aot-plotw-guide { margin-top: var(--aot-space-1); }

  /* 단계 목표 · 나머지 환경값 — **한 행에 칩으로 나열한다.**
     핵심(게이지)만 한 줄을 쓰고, 곁들이는 값은 줄을 늘리지 않는다.

     ⚠ 항목마다 줄을 잡지 않는다(공용 라벨-값 행으로 한 줄씩 세워 봤다가
       되돌렸다 — 값 네 개에 카드가 네 줄 커졌다). 그렇다고 글자만 흘려 두지도
       않는다(그것은 밋밋해서 쌍의 경계가 안 보였다). **칩 하나에 한 쌍**이다.

     칩은 앱 공용(`.aot-tag` · `.aot-tag-list`, aot-modal-modern.css)을 쓴다 —
     모양·배경·라운드를 이 위젯이 새로 정하지 않는다. 여기서 더하는 것은 셋뿐:
       · 크기를 위젯 스케일(--aot-fs-sm)로 — 공용 칩은 모달 기준이다
       · 숫자 폭 고정 — 자릿수가 달라도 값이 흔들리지 않는다
       · 칩 안에서 이름과 값의 무게를 가른다 */
  .aot-plotw-list {
    align-items: baseline;
    gap: var(--aot-space-1) var(--aot-space-2);
    margin-top: var(--aot-space-2);
  }
  .aot-plotw-list .aot-tag {
    display: inline-flex;
    align-items: baseline;
    gap: 0.35em;
    font-size: var(--aot-fs-sm);
    font-variant-numeric: tabular-nums;
  }
  .aot-plotw-list i {
    font-style: normal;
    color: var(--aot-color-text-secondary);
  }
  .aot-plotw-list b {
    font-weight: 600;
    color: var(--aot-color-text-primary);
  }
  /* 곡선을 따르는 항목 — 값 자리에 **곡선 이름**이 온다. 숫자와 같은 무게로
     세우면 이름이 값으로 읽힌다(그 항목은 아직 숫자가 정해진 것이 아니다). */
  .aot-plotw-list em {
    font-style: normal;
    color: var(--aot-color-text-secondary);
  }

  /* 추세 방향 — 칩과 게이지 값 옆에 붙는다(`↑`/`↓`).
     이 카드에는 스파크라인이 설 자리가 없다(줄을 늘리지 않는다). 그런데 여기서
     정말 필요한 것은 모양이 아니라 **방향**이다: 습도가 범위 위로 벗어나 있는데
     더 오르는 중인지 내려오는 중인지가 다음 행동을 가른다. */
  .aot-plotw-trend {
    font-style: normal;
    margin-left: 0.25em;
    font-weight: 400;
    color: var(--aot-color-text-secondary);
  }

  .aot-plotw-empty { padding: var(--aot-space-5) 0; text-align: center; }

  /* bootstrap-select 는 `<select>` 의 클래스를 **감싸는 div 에도 복사**한다.
     그래서 `.aot-modern-select` 의 테두리와 화살표가 껍데기에 한 벌, 안쪽
     버튼에 또 한 벌 그려져 **테두리 두 겹·화살표 두 개**가 된다.

     ⚠ 껍데기에서 걷는 것은 **장식뿐이다.** 예전에는 `height`·`padding` 까지
     함께 0 으로 만들었는데, 그러면 공용 규칙의 **컨트롤 크기(32px)까지 죽어**
     안쪽 버튼이 브라우저 기본값(38px · 16px)으로 섰다 — 옆의 [편집](32px ·
     sm)과 높이도 글자도 어긋났다(2026-08-28 실측). 크기는 공용 값을 안쪽
     버튼에 그대로 얹는다.
     `!important` 인 이유: 공용 규칙이 장식을 `!important` 로 못박고 있다. */
  .aot-plotw-head .bootstrap-select.aot-modern-select {
    background-image: none !important;
    border: 0 !important;
    padding: 0 !important;
    height: 32px !important;
  }
  /* 실제로 누르는 것은 안쪽 버튼이다 — 앱의 입력·선택 컨트롤과 **같은 치수**
     (aot-modal-modern.css: 높이 32 · 줄높이 30 · 좌우 1rem · 글자 sm). */
  .aot-plotw-head .bootstrap-select > button.dropdown-toggle {
    height: 32px;
    line-height: 30px;
    padding: 0 1rem;
    font-size: var(--aot-font-size-sm);
  }
  /* 목록은 카드 밖(body)에 붙으므로(`data-container`) 최소 폭을 준다. */
  .bootstrap-select.aot-plotw-pick .dropdown-menu { min-width: 16rem; }
</style>
"""

WIDGET_BODY_HTML = """
<div id="aot-plot-{{each_widget.unique_id}}" class="aot-plotw">
  <div class="aot-plotw-head">
    {#- 구획은 **여기서** 바꾼다 — 설정을 열지 않는다. 관심 대상은 자주 옮겨
        다니는데 그때마다 설정 모달을 여는 것은 모니터링이 아니다.

        ⚠ **id 로 찾아야 한다.** layout 이 로드 때 `.aot-modern-select` 를 전부
        bootstrap-select 로 바꾸는데(layout.html), 그러면 같은 클래스가 감싸는
        `<div>` 에도 복사돼 클래스로 찾으면 껍데기가 잡힌다 — 거기에 옵션을
        넣으면 목록이 통째로 글자로 쏟아진다(실제로 그랬다). -#}
    {#- `data-live-search` — 구획이 수십 개인 농장이 정상이라, 목록만으로는
        찾는 것을 못 찾는다. 검색창이 붙으면 작물명 몇 글자로 좁혀진다.
        `data-size` — 한 번에 여덟 줄까지만 편다(그 아래는 스크롤).
        `data-container="body"` — 위젯 카드가 `overflow:auto` 라 카드 안에서
        펴면 목록이 잘리고, 잘린 목록이 카드 내용 위에 겹쳐 읽히지 않는다.
        몸통에 붙여 카드 밖으로 나오게 한다.

        ⚠ `title` 은 주지 않는다. bootstrap-select 는 그 값을 **자리막이 항목**
        으로 앞에 끼우고, 새로 고칠 때마다 그것이 선택돼 버튼에 "구획" 만 남는다
        (고른 구획은 멀쩡히 그려지는데 이름만 안 나온다). 읽어 주는 이름은
        `aria-label` 이 맡는다. -#}
    <select id="aot-plot-pick-{{each_widget.unique_id}}"
            class="form-control aot-modern-select aot-plotw-pick"
            data-live-search="true" data-size="8" data-container="body"
            aria-label="{{ _('Plot') }}"></select>
    <button type="button" class="btn aot-pill-btn aot-pill-btn-sm aot-plotw-edit"
            hidden>{{ _('Edit') }}</button>
  </div>
  <div class="aot-plotw-body"></div>
</div>

{#- 편집 모달 — 본문은 `/plots` 드로어와 **같은 두 컴포넌트**(`AoTPlotForm` ·
    `AoTPlotStages`)가 채운다. 셸만 다르다: 대시보드는 자기 드로어 모드를
    돌리고 있어(dashboard.js `UIFixes.widgetDrawerMode`) 여기서
    `.aot-widget-drawer` 를 쓰면 body 클래스가 이중으로 토글된다. -#}
<div class="modal fade aot-option-modal" id="aot-plot-modal-{{each_widget.unique_id}}"
     tabindex="-1" role="dialog" aria-hidden="true">
  <div class="modal-dialog modal-lg aot-modal-dialog" role="document">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">{{ _('Plot') }}</h5>
        <button type="button" class="close" data-dismiss="modal"
                aria-label="{{ _('Close') }}">
          <span aria-hidden="true">&times;</span>
        </button>
      </div>
      <div class="modal-body aot-drawer-rows"></div>
      <div class="modal-footer">
        <button type="button" class="btn aot-pill-btn"
                data-dismiss="modal">{{ _('Close') }}</button>
        <button type="button"
                class="btn aot-pill-btn aot-pill-btn-primary aot-plotw-save">
          {{ _('Save') }}</button>
      </div>
    </div>
  </div>
</div>

<script>
  (function () {
    var uid = '{{each_widget.unique_id}}';
    var opts = {
      plotUuid: {{ (widget_variables.plot_uuid or '')|tojson }},
      refreshMin: {{ widget_variables.refresh_minutes|int }},
      gauge: {{ (widget_variables.gauge or 'VPD')|tojson }},
      showProgress: {{ 'true' if widget_variables.show_progress else 'false' }},
      showEnv:      {{ 'true' if widget_variables.show_env else 'false' }},
      showTrend:    {{ 'true' if widget_variables.show_trend else 'false' }},
      showGdd:      {{ 'true' if widget_variables.show_gdd else 'false' }}
    };
    function go() {
      if (window.AoTPlotWidget) { window.AoTPlotWidget.init(uid, opts); return true; }
      return false;
    }
    // 위젯은 대시보드가 조각으로 덧붙이기도 한다(장치 추가 직후) — 그때는
    // DOMContentLoaded 가 이미 지나 있어 리스너만으로는 영영 안 돈다.
    if (!go()) {
      document.addEventListener('DOMContentLoaded', go);
    }
  })();
</script>
"""

WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_plot',
    'widget_name': lazy_gettext('AoT Plot'),
    'widget_library': '',
    'no_class': True,

    'message': lazy_gettext(
        'One plot at a glance: stage timeline, targets against current '
        'readings, trends, and accumulated heat. Edit its schedule, guidance '
        'and targets from here.'),

    # 폰에서 한 줄에 하나 — 네 묶음이 서는 화면이라 반으로 접히면 축이 뭉갠다.
    'mobile_full_width': True,

    # 세로를 짧게 잡는다 — 이 카드는 한 줄(진행) + 타일 두어 줄이면 끝이고,
    # 남는 높이는 여백이 되어 대시보드의 다른 위젯을 아래로 민다.
    'widget_width': 12,
    'widget_height': 6,

    'generate_page_variables': widget_variables,
    'execute_at_modification': execute_at_modification,

    # 고른 구획(`plot_uuid`)은 **여기 없다.** 사람은 UUID 를 고르지 않고,
    # 관심 대상은 위젯 본체의 선택 상자로 바꾼다(그쪽이 직접 저장한다).
    'custom_options': [
        {
            'type': 'header',
            'name': lazy_gettext('What to monitor')
        },
        {
            'id': 'show_progress',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Progress'),
            'phrase': lazy_gettext(
                'Stage timeline with today and past transitions marked.')
        },
        {
            'id': 'show_env',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Targets vs now'),
            'phrase': lazy_gettext(
                'Current readings against the targets and limits this stage '
                'declares. One gets the gauge, the rest are listed as text.')
        },
        {
            'id': 'show_trend',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Trends'),
            'phrase': lazy_gettext(
                'Fills the rows that have no axis with a recent trend line. '
                'Needs the targets block.')
        },
        {
            'id': 'show_gdd',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Accumulated heat'),
            'phrase': lazy_gettext(
                'How far this stage has come in growing degree days. Shown '
                'only when the programme declares a base temperature.')
        },
        {
            'id': 'gauge',
            'type': 'select',
            'default_value': 'VPD',
            'options_select': [
                ('VPD', lazy_gettext('VPD')),
                ('T', lazy_gettext('Temperature')),
                ('RH', lazy_gettext('Humidity')),
                ('soil', lazy_gettext('Soil moisture')),
            ],
            'name': lazy_gettext('Gauge metric'),
            'phrase': lazy_gettext(
                'Which measurement gets the gauge. The rest are listed as '
                'text. If this plot does not measure it, the first one with '
                'a range is shown instead.')
        },
        {
            'type': 'header',
            'name': lazy_gettext('General')
        },
        {
            'id': 'refresh_minutes',
            'type': 'integer',
            'default_value': 5,
            'name': lazy_gettext('Refresh Interval'),
            'phrase': lazy_gettext(
                'Minutes between reloads. Stages move by the day, so short '
                'intervals only add load.')
        },
    ],

    'widget_dashboard_head': WIDGET_HEAD_HTML,
    'widget_dashboard_title_bar': """
    <span class="aot-w-title" style="padding-right:0.5em">{{each_widget.name}}</span>
    """,
    'widget_dashboard_body': WIDGET_BODY_HTML,
    'widget_dashboard_js_ready': '',
    'widget_dashboard_js_ready_end': '',
}
