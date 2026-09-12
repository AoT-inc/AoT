# coding=utf-8
#
#  AoT_plot.py — 구획(작기) 종합 모니터링 위젯
#
#  ## 왜 지도 위젯과 따로 있는가
#
#  지도 위젯은 **다용도**다 — "어디에 무엇이 있나" 를 답하고, 구획은 눌러야
#  나오며 팝업은 하나씩 열렸다 닫힌다. 이 위젯은 **목적 기반**이다: 재배·육종
#  처럼 목적물을 계속 들여다보는 일에서, 구획의 지표를 대시보드에 상주시킨다.
#
#  그래서 **장치 제어는 담지 않는다.** 액추에이터·릴레이는 지도·시설 위젯의
#  일이고 여기 있는 것은 목적물의 상태와 그 일정뿐이다. 겹치면 같은 것을 두
#  위젯이 다르게 말하게 된다.
#
#  ## 두 단 — [구획 목록] → [구역 상세] (2026-09-11)
#
#  예전에는 한 구획의 묶음(단계·환경·추세·노트)을 세로로 늘어놓아 위젯이
#  스크롤 한 번에 끝나지 않았다. 이제 **높이는 고정**이고 볼 것은 옮겨 가서
#  본다 — 목록에서 카드를 누르면 상세, 상세의 [←] 로 목록. 상세의 머리와 탭은
#  지도 위젯 구획 모달의 것을 그대로 쓴다. 마지막 위치는 위젯에 남는다.
#
#  ## 화면의 계약
#
#  본체는 **읽기 전용**이다. 고치는 일은 [편집] 모달 안에서만, 그것도 [저장]을
#  눌러야 나간다 — 단계 목표는 제어가 읽는 값이라
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

    고른 구획(`plot_uuid`)과 마지막 위치(`nav_view`·`nav_tab`)는 위젯 본체가
    `/save_widget_custom_options` 로 직접 남긴다. 옵션 폼에는 그 칸이 없으므로
    (사람은 UUID 를 고르지 않는다), 폼 저장이 기존 값 위에 postsave 만 덮어써야
    그 값들이 살아남는다. 통째로 갈아 끼우면 설정을 한 번 저장할 때마다 보고
    있던 자리가 사라진다.
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
    """템플릿 변수 — 저장된 자리와 표시 토글.

    구획 목록은 **여기서 만들지 않는다.** 위젯이 `/api/geo/plots` 를 직접 받고,
    그 응답은 공유 캐시를 지난다(`AoTGeoData`) — 서버가 따로 실어 보내면 그 한
    번이 캐시를 비껴가고, 위젯이 열려 있는 동안 목록이 낡아도 갱신할 길이 없다.

    권한도 여기서 판정하지 않는다. 구획을 고칠 수 있는가는 **그 구획 응답**이
    `can_edit` 으로 말한다(`/api/geo/plot/<uuid>`) — 위젯이 따로 판정하면 두
    곳이 갈리고, 그 갈라짐은 "눌러도 403" 으로만 드러난다.
    """
    options = widget_options or {}
    return {
        'plot_uuid': options.get('plot_uuid') or '',
        'refresh_minutes': options.get('refresh_minutes', 5),
        # 환경 탭의 보기 단위. `''`(오늘) | `'day'` | `'week'`.
        # **폼에는 없다**(`plot_uuid` 와 같은 자리) — 사람은 탭 줄에서
        # 고르고, 그 선택이 `/save_widget_custom_options` 로 직접 남는다.
        'env_mode': options.get('env_mode') or '',
        # 마지막 위치 — 선 화면(`'list'` | `'detail'`)과 상세의 탭
        # (`'stage'` | `'env'` | `'notes'`). 역시 **폼에는 없다**: 본체가 옮겨
        # 다닐 때 직접 남기고, 새로고침하면 그 자리로 선다. 모르는 값은 JS 가
        # 목록·[단계]로 눕힌다(설정 JSON 은 사람이 손으로 고칠 수 있는 자리다).
        'nav_view': options.get('nav_view') or 'list',
        'nav_tab': options.get('nav_tab') or 'stage',
        # 목록을 좁히는 지도·대지(unique_id). 비면 재배 중인 구획 전부.
        'site_filter': options.get('site_filter') or '',
        'show_progress': options.get('show_progress', True),
        'show_env': options.get('show_env', True),
        'show_trend': options.get('show_trend', True),
        'show_gdd': options.get('show_gdd', True),
    }


WIDGET_HEAD_HTML = """
{#- 공용 프리미티브(밴드·불릿·기간 바·편차 축)는 layout 이 이미 싣는다
    (`components/aot-dataviz.css`). 여기서 다시 걸지 않는다. -#}

{#- **카드 골격**(`.aot-ov-card-title` + `.aot-ov-block`)과 **상세의 머리**
    (`.aot-sensor-popup-header` · `.aot-modal-up`) — 지도·시설 모달이 쓰는 것과
    같은 파일이다. 이것을 안 싣고 위젯이 자기 여백·배경을 적으면 같은 성격의
    화면이 앱 안에서 저마다 다른 카드가 된다. -#}
{% if "css_sensor_label" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/widget/aot-sensor-label.css') }}">
{% set _dummy = dashboard_dict.update({"css_sensor_label": 1}) %}
{% endif %}

{#- **탭**(`.aot-act-tabs-nav` · `.aot-act-tab-btn`)의 기본 모습 — 지도·시설
    위젯 모달의 탭과 같은 규칙이 여기 있다. 그 위젯들이 먼저 걸었으면 다시
    걸지 않는다. -#}
{% if "css_facility_widget" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/widget/aot-facility-widget.css') }}">
{% set _dummy = dashboard_dict.update({"css_facility_widget": 1}) %}
{% endif %}

{#- 편집 모달의 세 파일 — `/plots` 페이지와 **같은 정의**다. 하나라도 빠지면
    골격만 같고 긴 제목이 잘리거나 단계 트랙이 통째로 안 그려진다. -#}
<link rel="stylesheet" href="{{ url_for('static', filename='css/components/aot-stage-track.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/components/aot-drawer-form.css') }}">
{#- AoT_map 위젯도 이 파일을 건다 — 먼저 그린 쪽만 걸리게 한다. -#}
{% if "css_plot_form" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/components/aot-plot-form.css') }}">
{% set _dummy = dashboard_dict.update({"css_plot_form": 1}) %}
{% endif %}

{#- widget-shared — **지도 위젯(AoT_map)과 나눠 쓰는 소스.** 반드시 아래
    aot-plot-widget 보다 먼저. 이 위젯이 쓰는 것 거의 전부가 여기 있다
    (plot-labels · plot-form · dataviz · sensor-label · geo-data · map-sensor-labels · popup).
    예전에는 같은 442KB 를 지도 위젯 번들도 사본으로 담고 있어, 한 대시보드에 두
    위젯이 서면 두 벌을 받았다. 자세한 경위는 AoT_map.py 의 같은 자리 주석. -#}
<script src="{{ asset('widget-shared') }}"></script>
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

  /* 컨테이너 경계 — **테두리 한 줄**이다.

     공용 `.aot-ov-block` 은 `border: none` 이다. 모달에서는 카드가 배경 보조색
     위에 얹혀 **면 대비**로 경계가 서는데, 위젯 내부는 배경 기본색 한 겹이라
     그 대비가 없다. 면을 한 겹 더 까는 방법은 물렸다(030d86ec → c30aede6) —
     위젯 안에서 면을 나누면 대시보드의 다른 위젯과 어긋난다.

     ⚠ **`border` 가 아니라 `box-shadow` 링이다.** 테두리를 쓰면 그 1px 이
       박스 안쪽 내용을 그만큼 밀어, 제목과 박스 안 첫 글자가 1px 어긋난다
       (2026-09-05 실측). 링은 레이아웃을 차지하지 않고, 라운드도 따라온다.
     ⚠ 공용 규칙을 고치지 않는다 — 모달은 면 대비로 이미 성립한다. */
  .aot-plotw-body .aot-ov-block {
    box-shadow: 0 0 0 1px var(--aot-border-light);
  }

  /* ⚠ **카드 제목의 좌우 여백을 건드리지 말 것.** 그것이 정렬 규칙이다 —
     `.aot-ov-card-title { padding: 0 var(--aot-space-4) }` 가 박스의 안여백과
     같은 값이라 제목의 첫 글자와 박스 안 첫 글자가 같은 세로선에 선다. */

  /* ── 껍데기 ─────────────────────────────────────────────────────────────
     목록과 상세는 **같은 자리에 번갈아 선다**(한쪽은 `hidden`). 지우지 않고
     감추는 것은, 목록의 스크롤 자리와 상세의 캐시가 그대로 남아야 오갈 때
     다시 그리지 않기 때문이다.
     위젯 높이는 고정이다 — 넘치는 것은 각 화면의 본체(`.aot-plotw-body`)
     안에서만 흐른다. */
  .aot-plotw { display: flex; flex-direction: column; height: 100%; }
  .aot-plotw > [hidden] { display: none; }
  .aot-plotw-detail {
    display: flex;
    flex-direction: column;
    flex: 1 1 auto;
    min-height: 0;
  }

  /* 본체 — 스크롤하되 **스크롤바는 보이지 않는다**(앱 전역 규칙).

     ⚠ **배경은 배경 기본색이다**(2026-09-11 사용자 결정·정정 — 처음에는
       이 자리에 컨트롤 면색을 발랐는데, 그것은 **[환경] 카드 쪽**(아래
       `.aot-plotw .aot-ov-envnow`)의 몫이었다. 본체는 위젯 바탕
       (`--aot-surface-card`, settings/custom_ui `bd_primary`, 기본값
       `#FFFFFF`)으로 되돌린다 — 카드가 도드라지는 것은 카드 자신의 색이
       하는 일이지, 본체가 짙어져서 하는 일이 아니다.
     ⚠ **좌우 여백은 여기(본체)에 준다 — 껍데기가 아니라.** 이 요소는 스크롤
       컨테이너라 자기 패딩 상자에서 내용을 자른다. 카드가 본체와 폭이 같으면
       카드의 링이 정확히 그 자름선 위에 놓여 **좌우만 안 보인다**(2026-09-05).
       값은 옆 위젯의 같은 자리에서 가져왔다(`.seq-widget-container`:
       `padding: 10px 12px`).
     ⚠ **위쪽 여백도 조금은 필요하다.** 카드 경계는 `border` 가 아니라
       `box-shadow` 링이라(아래 `.aot-ov-block` 규칙) 카드 박스 **밖으로**
       1px 번진다. 위 여백이 0이면 스크롤 컨테이너의 자름선이 그 1px 바로 위에
       서서 첫 카드([구획 목록]의 첫 카드, [환경·단계] 탭의 첫 카드 모두)의
       윗변만 잘린다(2026-09-11 실측) — 좌우와 같은 함정, 다른 축.
       `--aot-space-1`(4px)이면 넉넉하다(사다리 최소단).
     ⚠ 그 대신 **머리·탭 줄이 따로 맞춰야 한다** — 둘은 본체 밖이라 이 여백을
       못 받는다(아래 `.aot-plotw-tabbar`). */
  .aot-plotw-body {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    background: var(--aot-surface-card);
    padding: var(--aot-space-1) var(--aot-space-3) var(--aot-space-3);
    scrollbar-width: none;
    -ms-overflow-style: none;
  }
  .aot-plotw-body::-webkit-scrollbar { width: 0; height: 0; display: none; }
  /* [환경] 카드는 배경 기본색이다(2026-09-11 정정 — 한때 컨트롤 면색을
     발랐었다). 별도 규칙을 두지 않는다 — `.aot-ov-envnow` 가 얹는
     `.aot-ov-block`이 앱 전역 규칙으로 이미 흰색(`--aot-surface-card`)을
     칠하므로, 여기서는 그 기본값을 그대로 둔다([단계] 박스만 예외로
     컨트롤 면색을 쓴다 — 아래 `.aot-plotw-stagebox`). */
  /* [노트] 카드 박스(`.aot-ov-block.aot-ov-record` — `aot-map-popup.js`
     `buildRecordBlock` 이 낸다)는 배경 기본색이다(2026-09-11 정정).

     한때 그 바깥 래퍼(`.aot-ov-card`)에 배경 기본색을, 이 박스엔 컨트롤
     면색을 발라 pane([환경]과 함께 컨트롤 면색)과의 사이에 흰 층을 두려고
     했다 — 그런데 이 카드는 제목을 지운 구조라(탭 이름과 겹쳐 CSS 로
     감춘 것, 아래 `.aot-ov-card-title` 규칙) 래퍼와 박스가 완전히 같은
     자리·같은 크기로 겹친다. 박스가 래퍼를 100% 덮으므로 **어느 쪽에
     발라도 실제로 보이는 것은 박스 색 하나뿐**이었다(2026-09-11 실측:
     두 요소의 렌더 크기가 픽셀 단위로 동일). 그래서 래퍼는 걷어내고
     (더 아래 `.aot-ov-card` 규칙 없음) **보이는 층인 박스 자신**에 배경
     기본색을 직접 준다 — pane(컨트롤 면색) 위에 흰 카드로 도드라진다. */
  .aot-plotw .aot-ov-record {
    background: var(--aot-surface-card);
  }
  /* [단계] 카드 박스(`.aot-ov-block.aot-plotw-stagebox` — `aot-plot-widget.js`
     `renderDetail` 이 낸다)는 컨트롤 면색이다(2026-09-11). 이 탭은 애초에
     `.aot-ov-card` 래퍼 자체가 없어(본문이 `.aot-ov-block` 하나뿐) 위
     [노트]와 같은 겹침 문제가 성립하지 않는다 — 박스 자신에 바로 칠하면
     그대로 보인다. */
  .aot-plotw .aot-plotw-stagebox {
    background: var(--aot-surface-control);
  }
  /* 마지막 카드의 아래 여백은 카드가 아니라 **본체 끝**이 정한다(위 padding).
     카드 자신의 `margin-bottom` 을 그대로 두면 본체 여백과 더해져 아래만
     두 배가 된다. */
  .aot-plotw-cards > .aot-plotw-card:last-child,
  .aot-plotw-body > .aot-bay-popup-pane > .aot-ov-block:last-child,
  .aot-plotw-body > .aot-bay-popup-pane > .aot-ov-card:last-child > .aot-ov-block:last-child,
  .aot-plotw-body > .aot-bay-popup-pane > [data-slot]:last-child > .aot-ov-card > .aot-ov-block:last-child {
    margin-bottom: 0;
  }
  /* 어떤 자식도 부모보다 넓어질 수 없다 — flex 자식의 기본 `min-width: auto`
     가 이 위젯에서 폭이 새는 통로다(아래 `.aot-plotw-list .aot-tag` 주석). */
  .aot-plotw, .aot-plotw-body, .aot-plotw-stage,
  .aot-plotw-stage-head, .aot-plotw-stage-head > * { min-width: 0; }
  .aot-plotw-body { overflow-x: hidden; }

  /* ── [구획 목록] ─────────────────────────────────────────────────────────
     카드 하나 = 1행 이름 ─── 진행률 · 2행 심플 축(현재 단계 초록, 오늘 마커
     없음). 축과 진행률은 지도 구획 모달과 같은 빌더가 낸다
     (`buildPlotProgressHtml(p, {simple})` · `plotProgressPct`).
     카드는 `<button>` 이다 — 키보드로 닿아야 하고, 읽어 주는 이름이 곧
     "이름 · 진행률" 이다. 모양은 공용 카드(`.aot-ov-block`)에서 오고 여기서는
     버튼의 기본 꾸밈만 걷는다. */
  .aot-plotw .aot-plotw-card {
    display: block;
    width: 100%;
    border: 0;
    text-align: start;
    font-family: inherit;
    line-height: inherit;
    color: inherit;
    cursor: pointer;
  }
  /* 호버는 환경 줄의 "누를 수 있다" 와 같은 면(`--aot-bg-active`)이다. */
  @media (hover: hover) {
    .aot-plotw .aot-plotw-card:hover { background: var(--aot-bg-active); }
  }
  /* 1행 — 이름은 왼쪽, 진행률은 오른쪽(읽고 → 값). 이름이 길면 이름이
     줄어든다 — 숫자는 줄지 않는다. 아래 여백이 space-1 인 것은 압축 트랙이
     스스로 위에 space-1 을 두기 때문이다(합해서 space-2). */
  .aot-plotw-card-head {
    display: flex;
    align-items: baseline;
    gap: var(--aot-space-3);
    margin-bottom: var(--aot-space-1);
  }
  .aot-plotw-card-pct { flex: 0 0 auto; }
  .aot-plotw-card-name {
    flex: 1 1 auto;
    min-width: 0;
    font-weight: 600;
    color: var(--aot-color-text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* ── [구역 상세] 머리 — 지도 위젯 구획 모달의 제목줄 ────────────────────
     마크업은 공용 빌더(`buildModalHeader`)가 낸다: [← 상위] 이름. 치수도 그
     모달의 것 그대로다(`.aot-center-modal > .aot-sensor-popup-header`:
     높이 36 · 좌우 36 예약 · 아래 6 + 구분선). 좌우 36 을 비우고 [←] 가 그만큼
     왼쪽으로 물러나는(`.aot-modal-up { margin-left: -36px }`) 짝이라, 이름이
     위젯 한가운데 선다.
     글자 기준을 위젯 쪽 14px 로 못박는다 — 제목(1.3em)이 카드 안 글자
     기준을 따라가면 모달보다 작아진다(모달 헤더도 같은 이유로 기준을 고정). */
  .aot-plotw-detail .aot-sensor-popup-header {
    flex: 0 0 auto;
    min-height: 36px;
    margin: 0 var(--aot-space-3) var(--aot-space-1);
    padding: 0 36px 6px;
    border-bottom: 1px solid var(--aot-border-light);
    font-size: var(--aot-font-size-sm);
  }

  /* ── 탭 줄 — 지도 모달의 탭 + 오른쪽 손잡이 ───────────────────────────
     탭은 공용 빌더(`buildSectionNav`)가 낸다. 오른쪽에는 **그 탭의 손잡이**가
     선다 — [단계]의 [편집], [환경]의 [오늘][일간][주간]. 읽고 → 행동, 행동은
     오른쪽이다(ui-guide §3-2).
     구분선은 탭 줄 전체(손잡이까지)에 긋는다. 탭 목록의 선을 그대로 두면
     손잡이 밑에서 선이 끊긴다.
     좌우 여백은 본체와 같은 값이다(--aot-space-3) — 본체 밖이라 따로 적는다.
     안 맞추면 탭만 카드보다 12px 왼쪽으로 나간다.

     ⚠ **좁아지면 손잡이가 아랫줄로 내려간다**(오른쪽 정렬, ui-guide §4-6
       "컨트롤은 줄어들지 않는다"). 폰(위젯 280px)에서 탭 셋(200px) 옆에
       [오늘][일간][주간](87px)을 한 줄에 두면 [노트] 탭이 손잡이 밑으로 반쯤
       숨었다(2026-09-11 실측). 줄바꿈은 탭 목록의 **기본 폭**(글자 폭)으로
       판단하므로 넓은 화면에서는 그대로 한 줄이다. */
  .aot-plotw-tabbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--aot-space-1) var(--aot-space-2);
    flex: 0 0 auto;
    margin: 0 var(--aot-space-3) var(--aot-space-3);
    padding-bottom: var(--aot-space-1);
    border-bottom: 1px solid var(--aot-border-light);
  }
  .aot-plotw-tabnav { flex: 1 1 auto; min-width: 0; }
  /* 탭 목록은 줄바꿈하지 않고 끌어서 넘긴다(ui-guide §4-6, `.aot-act-tabs-nav`
     는 `aot-drag-scroll` 의 대상이다). 글자 기준은 머리와 같은 이유로 14px. */
  .aot-plotw-tabnav > .aot-act-tabs-nav {
    margin: 0;
    padding: 0;
    border-bottom: 0;
    max-height: none;
    overflow-x: auto;
    overflow-y: hidden;
    font-size: var(--aot-font-size-sm);
  }
  .aot-plotw-tabacts {
    flex: 0 0 auto;
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: var(--aot-space-2);
  }
  .aot-plotw-tabacts > [hidden] { display: none; }

  /* pane 은 모달에서는 자기가 스크롤하지만(`.aot-bay-popup-pane`), 여기서는
     본체가 스크롤한다 — pane 이 또 스크롤하면 두 겹이 된다.

     ⚠ **배경을 칠하지 않는다**(2026-09-11 정정 — 한때 컨트롤 면색을
       발랐었다). pane 은 각진 사각형이고 본체(`.aot-plotw-body`)의 위쪽
       여백은 링 하나만 지킬 만큼만 얇다(`--aot-space-1`, 4px) — 그런데
       위젯 바깥 껍데기(대시보드 카드)는 그보다 큰 반지름으로 둥글다.
       pane 을 칠하면 그 각진 모서리가 둥근 껍데기의 곡선 **밖으로**
       튀어나온다(실측: 폰 화면 캡처에서 위쪽 두 모서리가 사각으로
       비어져 나왔다). 색은 **실제로 둥근 모서리를 가진 것**(각 탭의 카드
       박스 — `.aot-ov-envnow`·`.aot-ov-record`·`.aot-plotw-stagebox`, 전부
       `--aot-radius-lg` 가 있다)에만 준다 — pane 은 그 색들이 놓이는
       투명한 자리일 뿐이다. */
  .aot-plotw-body > .aot-bay-popup-pane {
    overflow: visible;
    flex: none;
  }
  /* [노트] 탭의 노트 카드 제목 — 탭 이름이 이미 "노트" 다. 같은 말을 탭과
     카드가 연달아 하지 않게 카드 쪽을 걷는다(최신 사진의 제목은 남는다 —
     그것은 탭과 다른 말이다). */
  .aot-plotw-body > [data-pane="notes"] > .aot-ov-card > .aot-ov-card-title {
    display: none;
  }

  /* ── [환경] 한 장에 세 줄, 넘치면 좌우로 넘긴다 ──────────────────────
     줄 수가 구획마다 달라(DLI·GDD·측정 대여섯) 세로로 늘어놓으면 위젯 높이가
     그만큼 는다. 세 줄씩 장으로 묶고(JS `ENV_PER_PAGE`) 장은 가로로 넘긴다.

     · **한 장이 폭 전체**이고 스냅이 장의 시작에 걸린다(`mandatory` +
       `stop: always`) — 넘기다 멈춰도 두 장이 반씩 걸쳐 서지 않고, 한 번에
       한 장만 넘어간다.
     · 스크롤러는 박스의 **안여백까지** 넓힌다(음수 마진). 줄
       (`.aot-env-now-item`)은 호버 면을 위해 좌우로 8px 내미는데, 박스 안쪽
       폭에서 자르면 그 몫이 잘린다. 장이 같은 값을 안여백으로 되돌려 글자의
       세로선은 박스 안 다른 글자와 같다.
     · 마우스로 끄는 동안에는 스냅을 끈다(`aot-drag-scroll` 이 끄는 동안
       루트에 `aot-drag-scrolling` 을 단다). 켜 두면 `scrollLeft` 대입마다
       제자리로 튀어 끌리지 않는다 — 놓으면 JS 가 가까운 장으로 붙인다. */
  .aot-plotw-pages {
    display: flex;
    overflow-x: auto;
    overflow-y: hidden;
    scroll-snap-type: x mandatory;
    overscroll-behavior-x: contain;
    margin: 0 calc(-1 * var(--aot-space-4));
    scrollbar-width: none;
    -ms-overflow-style: none;
  }
  .aot-plotw-pages::-webkit-scrollbar { width: 0; height: 0; display: none; }
  .aot-drag-scrolling .aot-plotw-pages { scroll-snap-type: none; }
  .aot-plotw .aot-plotw-pages > .aot-plotw-page {
    flex: 0 0 100%;
    box-sizing: border-box;
    min-width: 0;
    padding: 0 var(--aot-space-4);
    scroll-snap-align: start;
    scroll-snap-stop: always;
    /* **세로 가운데 정렬**(2026-09-11). `.aot-plotw-pages` 는 flex 행이라
       기본 `align-items: stretch` 로 이 요소가 **가장 키 큰 형제 장만큼**
       늘어난다 — 카드 높이가 장을 넘길 때마다 흔들리지 않게 하려던 것인데,
       그 부작용으로 줄 수가 적거나 짧은(가로 밴드) 장에는 내용 아래로 죽은
       공간이 통째로 남았다(실측: 5줄짜리 구획, 2장(3+2)에서 둘째 장이
       114px 남았다 — 셋째 줄이 없거나 세로형(막대) 대신 가로형이라 첫 장보다
       짧을 때). 장의 **키는 그대로 두고**(카드 높이는 안 흔들려야 한다)
       내용만 그 안에서 가운데로 옮긴다 — 남는 공간이 위아래로 갈라져
       바닥에만 몰리지 않는다. */
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  /* 페이지 표시 — 넘길 것이 더 있다는 유일한 표시이자, **눌러서 그 장으로
     넘어가는 손잡이**다(2026-09-11: 처음엔 장식이었다가, 눌러 이동하게
     됐다). 카드 **밖**, 카드와 본체 바닥 사이에 선다(카드 안에 있으면
     "카드에 속한 숫자" 처럼 읽힌다 — JS `_paginateEnv` 가 `.aot-ov-card`
     다음 자리에 심는다). 색은 새로 들이지 않고 이미 있는 상태색을 쓴다
     (settings/custom_ui `bg_active`/`bg_inactive` — IEC 포커스 행·PID
     컨테이너 배경과 같은 값). */
  .aot-plotw-pagedots {
    display: flex;
    justify-content: center;
    align-items: center;
    /* 사다리 예외: 점 사이 간격은 짚는 자리(아래 `--aot-plotw-dot-hit`)가
       서로 겹치지 않을 만큼 벌려야 한다 — `--aot-space-1`(4px)이면 이웃
       짚는 자리가 겹쳐 경계 근처를 누르면 어느 점이 눌렸는지 모호해진다
       (2026-09-11 실측). */
    gap: var(--aot-space-3);
    margin-top: var(--aot-space-2);
  }
  /* 점은 `<button>` 이다(누르는 것이라 `<span>` 이 아니다). **보이는 점은
     8px, 짚는 자리는 그보다 두 배**(음수 마진으로 되돌려 배치는 8px
     짜리였을 때와 같다 — 지도 위젯 잠금 아이콘과 같은 기법,
     widget-conventions.md "짚는 자리를 넓힐 때는 바깥으로 넓힌다").
     `background-clip: content-box` 로 칠은 안쪽 8px 에만 남기고
     패딩(짚는 자리 몫)은 투명하게 둔다.

     사다리 예외: 표적 최소(`2.75rem`, ui-guide §3-1)를 그대로 쓰지 않는다
     — 점들이 서로 가까이 붙어 있어서(캐러셀 페이지 표시의 통상적인 모양)
     44px 짚는 자리를 각각 두면 이웃과 겹친다(2026-09-11 실측: 간격
     4px 에서 32px 겹침). 겹치면 경계 근처 클릭이 어느 점으로 갈지
     모호해져, 표적을 키운 목적(더 쉽게 누르기)에 반한다. 16px 는 이웃과
     안 겹치면서(위 간격과 짝) 8px 보다는 넉넉하다. */
  .aot-plotw-pagedots > button {
    --aot-plotw-dot: 8px;
    --aot-plotw-dot-hit: 16px;
    width: var(--aot-plotw-dot-hit);
    height: var(--aot-plotw-dot-hit);
    margin: calc((var(--aot-plotw-dot) - var(--aot-plotw-dot-hit)) / 2);
    padding: calc((var(--aot-plotw-dot-hit) - var(--aot-plotw-dot)) / 2);
    flex: 0 0 auto;
    border: 0;
    border-radius: 50%;
    background-color: var(--aot-bg-inactive);
    background-clip: content-box;
    cursor: pointer;
  }
  .aot-plotw-pagedots > button.is-active {
    background-color: var(--aot-bg-active);
    cursor: default;
  }

  /* 전환 대기 — 카드 안에서 한 줄로 선다(카드 자체는 공용 규칙이 그린다). */
  .aot-plotw-ask {
    display: flex;
    align-items: center;
    gap: var(--aot-space-2);
    flex-wrap: wrap;
  }
  .aot-plotw-ask-text { flex: 1 1 auto; min-width: 0; }
  .aot-plotw-ask-date { width: auto; flex: 0 0 auto; }

  /* 지침 — **높이가 정해진 상자**다. 넘치는 글은 상자 안에서만 흐른다.

     ⚠ 지침이 없는 단계에서도 **자리를 지킨다**(JS 가 빈 상자를 낸다). 단계마다
       글이 있고 없고·길고 짧고가 다른데 그 차이가 카드 높이로 새어 나가면,
       축을 한 번 누를 때마다 아래 카드가 밀린다.

     스크롤바는 보이지 않는다(앱 전역 규칙). `overscroll-behavior: contain` 은
     상자 끝에서 스크롤이 위젯 본체로 넘어가지 않게 한다. */
  .aot-plotw-guidebox {
    /* 줄 간격을 **여기서 정한다.** 상자 높이가 `줄간격 × 줄수` 라, 줄 간격이
       바깥에서 오면 둘이 어긋나 두 번째 줄의 아랫부분이 잘린다(2026-09-05
       실측: 상자 42px 대 내용 50px). */
    --aot-plotw-guide-lh: 1.8;
    --aot-plotw-guide-lines: 2;
    line-height: var(--aot-plotw-guide-lh);
    height: calc(var(--aot-fs-md) * var(--aot-plotw-guide-lh)
                 * var(--aot-plotw-guide-lines));
    margin-top: var(--aot-space-3);
    overflow-y: auto;
    overscroll-behavior: contain;
    color: var(--aot-color-text-secondary);
    scrollbar-width: none;
    -ms-overflow-style: none;
  }
  .aot-plotw-guidebox::-webkit-scrollbar { width: 0; height: 0; display: none; }

  /* 단계 세부 — 축 **바로** 아래. 기본은 현재 단계이고, 축에서 다른 구간을
     누르면 그 단계로 바뀐다.
     ⚠ **높이를 예약한다.** 단계마다 목표 개수·지침 유무가 달라, 그대로 두면
     축을 누를 때마다 아래 카드가 밀린다. 머리줄 1 + 칩 1 + 지침 2 = 네 줄
     어치를 잡아 두고, 모자란 단계에서는 빈 자리로 남긴다. */
  .aot-plotw-stage {
    margin-top: var(--aot-space-2);
    min-height: calc(var(--aot-font-size-xs) * 1.8
                     + var(--aot-space-2) + 1.6rem
                     + var(--aot-space-3)
                     + var(--aot-fs-md) * 1.8 * 2);
  }
  /* 어느 단계에도 지침이 없는 구획 — 지침 상자를 아예 안 내므로(JS
     `anyGuide`) 그 몫도 예약하지 않는다. 그런 구획은 **모든** 단계가 상자를
     안 내므로 어느 단계를 골라도 높이가 같다. */
  .aot-plotw-stage.is-noguide {
    min-height: calc(var(--aot-font-size-xs) * 1.8
                     + var(--aot-space-2) + 1.6rem);
  }
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
    /* ⚠ **줄 상자를 키우지 않는다.** 큰 글자의 줄 상자가 그대로 줄 높이가
       되면 머리줄이 21.6px ↔ 24.5px 로 오가 축을 누를 때마다 카드가 밀린다
       (2026-09-05 로컬 실측). */
    line-height: 1;
  }
  /* [지금 단계로] — 글자 링크다. 버튼 모양을 주면 카드 안에 누를 것이 둘이
     되어 무엇이 주된 행동인지 흐려진다. */
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
  /* 현재 단계에서는 **감추되 자리는 남긴다.** `display:none` 으로 빼면 다른
     단계를 고르는 순간 버튼이 새로 생기며 머리줄이 밀린다. */
  .aot-plotw-stage-back.is-idle { visibility: hidden; }

  /* 단계 목표 — **한 행에 칩으로 나열한다.** 칩은 앱 공용(`.aot-tag` ·
     `.aot-tag-list`)을 쓰고 여기서는 셋만 더한다: 크기를 위젯 스케일로 · 숫자
     폭 고정 · 칩 안에서 이름과 값의 무게를 가른다. */
  .aot-plotw-list {
    align-items: baseline;
    gap: var(--aot-space-1) var(--aot-space-2);
    margin-top: var(--aot-space-2);
  }
  /* ⚠ **칩이 카드보다 넓어질 수 없게 한다.** 공용 `.aot-tag` 는 `nowrap` 인데
     flex 아이템의 `min-width: auto` 와 만나면 곡선 이름 하나가 카드 폭을 넘겨,
     단계를 바꿀 때 좌우폭이 변했다(2026-09-05). 넘치면 칩 안에서 자르고
     전문은 `title` 이 진다(JS `_pair`). */
  .aot-plotw-list .aot-tag {
    display: inline-flex;
    align-items: baseline;
    gap: 0.35em;
    font-size: var(--aot-fs-sm);
    font-variant-numeric: tabular-nums;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
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
     세우면 이름이 값으로 읽힌다. */
  .aot-plotw-list em {
    font-style: normal;
    color: var(--aot-color-text-secondary);
  }

  .aot-plotw-empty { padding: var(--aot-space-5) 0; text-align: center; }
</style>
"""

WIDGET_BODY_HTML = """
<div id="aot-plot-{{each_widget.unique_id}}" class="aot-plotw">
  {#- [구획 목록] — 지금 기르는 구획마다 카드 하나. 누르면 [구역 상세].
      카드는 JS 가 채운다(`renderList`). -#}
  <div class="aot-plotw-body aot-plotw-cards" data-role="list"></div>

  {#- [구역 상세] — 머리([←] 이름)와 탭은 JS 가 지도 모달의 공용 빌더로
      그린다(`buildModalHeader` · `buildSectionNav`). 여기는 자리만 잡는다.
      탭 줄 오른쪽은 그 탭의 손잡이 자리다: [단계]의 [편집], [환경]의
      [오늘][일간][주간](`data-role="range"` — 환경 카드 머리줄에서 옮겨 온다). -#}
  <div class="aot-plotw-detail" data-role="detail" hidden>
    <div data-role="head"></div>
    <div class="aot-plotw-tabbar">
      <div class="aot-plotw-tabnav" data-role="nav"></div>
      <div class="aot-plotw-tabacts">
        <button type="button" class="btn aot-pill-btn aot-pill-btn-sm aot-plotw-edit"
                hidden>{{ _('Edit') }}</button>
        <span class="aot-ov-title-actions" data-role="range" hidden></span>
      </div>
    </div>
    <div class="aot-plotw-body" data-role="panes"></div>
  </div>
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
      envMode: {{ (widget_variables.env_mode or '')|tojson }},
      navView: {{ (widget_variables.nav_view or 'list')|tojson }},
      navTab: {{ (widget_variables.nav_tab or 'stage')|tojson }},
      siteFilter: {{ (widget_variables.site_filter or '')|tojson }},
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

    # 폰에서 한 줄에 하나 — 반으로 접히면 탭 줄과 축이 뭉갠다.
    'mobile_full_width': True,

    # **높이는 고정이다**(2026-09-11). 내용은 탭과 장으로 나뉘어 이 높이 안에서
    # 옮겨 다니며 본다 — 머리 + 탭 줄 + [환경] 한 장(세 줄, [오늘])이 스크롤
    # 없이 서는 값이다. 실측(칸 25px · 셸 61px): [환경] 456px ≈ 21칸, [단계]
    # 410px ≈ 19칸 → 한 칸 여유를 두어 22. [일간]·[주간] 은 줄마다 세로 도표라
    # 더 길고, 그때는 탭 본체 안에서 흐른다.
    'widget_width': 12,
    'widget_height': 22,

    'generate_page_variables': widget_variables,
    'execute_at_modification': execute_at_modification,

    # 고른 구획(`plot_uuid`) · 환경 탭의 보기 단위(`env_mode`) · 마지막 위치
    # (`nav_view` · `nav_tab`)는 **여기 없다.** 사람은 UUID 를 고르지 않고,
    # 모두 위젯 본체에서 바꾼다(그쪽이 직접 저장한다). 폼에 같은 항목을 두면
    # 본체와 폼이 같은 키를 다투게 되고, 폼을 한 번 저장할 때마다 본체에서
    # 고른 것이 되돌아간다.
    'custom_options': [
        {
            'type': 'header',
            'name': lazy_gettext('What to monitor')
        },
        {
            # 목록을 지도 하나, 또는 그 안의 대지 하나로 좁힌다. 농장이 지도
            # 여럿·대지 여럿이면 재배 중인 구획이 수십 개라, 한 곳을 지켜보는
            # 대시보드에 남의 대지 구획까지 늘어선다.
            #
            # 타입은 `select_device` 다 — 저장 경로(`custom_options_return_json`)
            # 가 아는 타입이어야 값이 남는다. 선택지는 `'GeoScope'` 가 지도 →
            # 그 안의 대지 두 층으로 그린다(Custom_Options.html · 선택지는
            # `routes_dashboard._geo_scope_choices`).
            'id': 'site_filter',
            'type': 'select_device',
            'options_select': ['GeoScope'],
            'default_value': '',
            'name': lazy_gettext('Map or site'),
            'phrase': lazy_gettext(
                'Show only the plots in this map or site. Leave empty to show '
                'every plot in progress.')
        },
        {
            'id': 'show_progress',
            'type': 'bool',
            'default_value': True,
            # 프로그램·일지와 **같은 msgid** 다(`Program stages` → "단계").
            # ⚠ `Stages`·`Stage` 를 쓰지 말 것 — 시설의 측창 개폐 단수가 이미
            #   쓰고 있어 한국어가 "단" 한 글자로 나온다.
            'name': lazy_gettext('Program stages'),
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
                'declares — the same card the map widget shows, including '
                'DLI and accumulated heat. [7 Days] turns each row into the '
                'range it moved through over the last week.')
        },
        {
            'id': 'show_trend',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Trends'),
            'phrase': lazy_gettext(
                'Fills the rows that have no range of their own (CO2, soil '
                'moisture, dew point) with a recent trend line. Needs the '
                'targets block.')
        },
        {
            'id': 'show_gdd',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Accumulated heat'),
            'phrase': lazy_gettext(
                'How far this stage has come towards the next one in growing '
                'degree days. Shown only when the programme moves stages by '
                'GDD. The running total since planting is a row in the '
                'environment card instead, and follows that card\'s settings.')
        },
        # 게이지 지표 선택(`gauge`)은 **없앴다**(2026-09-05). 환경 카드가
        # 지도 구획 모달과 같은 빌더(`AoTMapPopup.buildEnvNowHtml`)를 쓰면서
        # **모든 측정이 자기 축을 갖게** 되어, "어느 하나를 게이지로" 라는
        # 물음 자체가 없어졌다. 저장돼 있던 값은 그대로 남지만 아무도 읽지
        # 않는다(`execute_at_modification` 이 선언하지 않은 값을 지우지
        # 않으므로, 되살릴 일이 생기면 그 값이 아직 거기 있다).
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
    'widget_dashboard_title_bar': """""",
    'widget_dashboard_body': WIDGET_BODY_HTML,
    'widget_dashboard_js_ready': '',
    'widget_dashboard_js_ready_end': '',
}
