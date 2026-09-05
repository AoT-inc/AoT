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
        # 환경 카드의 보기 단위. `''`(오늘) | `'day'` | `'week'`.
        # **폼에는 없다**(`plot_uuid` 와 같은 자리) — 사람은 카드 머리줄에서
        # 고르고, 그 선택이 `/save_widget_custom_options` 로 직접 남는다.
        'env_mode': options.get('env_mode') or '',
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

  /* 컨테이너 경계 — **테두리 한 줄**이다.
     
     공용 `.aot-ov-block` 은 `border: none` 이다. 모달에서는 카드가 배경 보조색
     위에 얹혀 **면 대비**로 경계가 서기 때문인데(그 규칙의 주석: "카드 배경 =
     배경 기본 (모달 페이지 배경인 배경 보조와 대비)"), 위젯 내부는 배경 기본색
     한 겹이라 그 대비가 없다.
     
     면을 한 겹 더 깔아 대비를 만드는 방법을 썼다가 물렸다(030d86ec → c30aede6)
     — 위젯 안에서 면을 나누면 대시보드의 다른 위젯과 어긋난다. 그래서 배경은
     그대로 두고 **선으로만** 경계를 세운다. 시설 위젯이 안쪽 상자에 쓰는 것과
     같은 톤이다(`aot-facility-widget.css`: `1px solid var(--aot-border-light)`).
     
     ⚠ 공용 규칙을 고치지 않는다 — 모달은 면 대비로 이미 성립하고, 거기에
       선까지 그으면 한 경계에 표시가 둘이 된다. 이 위젯 안에서만 얹는다.
     
     ⚠ **`border` 가 아니라 `box-shadow` 링이다.** 테두리를 쓰면 그 1px 이
       박스 안쪽 내용을 그만큼 밀어, 제목(30px)과 박스 안 첫 글자(31px)가
       어긋난다(2026-09-05 실측). 제목의 좌우 여백이 박스의 안여백과 같아야
       한다는 규칙이 1px 때문에 깨지는 것이다. 링은 레이아웃을 차지하지 않아
       두 좌표가 그대로 남고, 라운드(16px)도 따라온다.

     ⚠ 공용 `.aot-ov-block` 은 그림자를 쓰지 않는다(확인함) — 덮어쓸 것이 없다.
       쓰기 시작하면 여기서 합쳐 적을 것. */
  .aot-plotw-body .aot-ov-block {
    box-shadow: 0 0 0 1px var(--aot-border-light);
  }

  /* ⚠ **카드 제목의 좌우 여백을 건드리지 말 것.** 그것이 정렬 규칙이다.

     제목은 박스 **밖**에 있고 박스는 자기 안여백(`--aot-space-4`)만큼 글을
     들여 쓴다. 공용 규칙이 제목에 **같은 값**을 주는 이유가 그것이다 —
     `.aot-ov-card-title { padding: 0 var(--aot-space-4) }`. 그래서 제목의
     첫 글자와 박스 안 첫 글자가 같은 세로선에 선다(오른쪽 손잡이도 마찬가지:
     [오늘][일간][주간] 이 박스 안 값의 오른쪽 끝과 맞는다).

     한때 본체에 좌우 여백을 주면서 이 값을 0 으로 눕혔는데, 그러면 제목이
     박스 **바깥선**에 붙어 안쪽 글보다 16px 왼쪽으로 나간다(2026-09-05). */

  /* 마지막 카드의 아래 여백 — 본체의 아래 패딩이 0 이라 카드 자신의
     `margin-bottom` 이 그 몫을 한다. 지우지 않는다(지우면 마지막 카드가
     들어간 면의 바닥에 닿는다). */

  /* 머리(선택 + 편집)는 고정, 본체만 흐른다.
     좌우 여백은 **카드와 같은 값**이다(--aot-space-4) — 안 주면 머리줄만
     카드 경계에 붙어 아래 카드들과 세로선이 안 맞는다. */
  .aot-plotw { display: flex; flex-direction: column; height: 100%; }
  /* 좌우 여백은 **본체의 여백 + 카드의 안여백**이다. 머리줄은 본체 밖이라
     본체의 여백을 못 받으므로 여기서 두 몫을 함께 적는다 — 그래야 선택 상자의
     왼쪽 모서리가 카드 안 첫 글자와 같은 세로선에 선다(안 맞추면 머리줄만
     카드보다 12px 왼쪽으로 나간다). */
  .aot-plotw-head {
    display: flex;
    align-items: center;
    gap: var(--aot-space-2);
    padding: 0 calc(var(--aot-space-3) + var(--aot-space-4)) var(--aot-space-3);
    flex: 0 0 auto;
  }
  .aot-plotw-pick { flex: 1 1 auto; min-width: 0; }

  /* 본체는 스크롤하되 **스크롤바는 보이지 않는다**(앱 전역 규칙).

     ⚠ **들어간 면 위에 카드를 얹는다**(모달과 같은 관계).
     `.aot-ov-block` 은 `--aot-surface-card`(흰색)로 칠해져 있고, 그것이
     카드로 보이는 것은 **그 아래 면이 `--aot-surface-body` 일 때뿐**이다
     (그 규칙의 주석이 "모달 페이지 배경인 배경 보조와 대비" 라고 적고 있다).
     그런데 대시보드 위젯의 바탕(`.grid-stack-item-content`)은 흰색이라,
     흰 카드가 흰 바탕에 얹혀 **경계가 통째로 사라져 있었다**(2026-09-05 실측:
     블록 `#ffffff` · 위젯 바탕 `#ffffff`). 카드마다 배경·라운드·안여백이 이미
     있었는데 보이지만 않았던 것이다.

     좌우 여백은 카드가 바탕에 닿지 않게 하는 몫이다 — 없으면 들어간 면이
     위아래로만 보여 카드가 아니라 띠로 읽힌다. */
  /* ⚠ **배경을 여기서 칠하지 않는다.** 한때 본체를 `--aot-surface-body`(배경
     보조)로 눕혀 흰 카드가 카드로 보이게 했는데, 위젯 안에서 면을 두 겹으로
     나누는 것은 대시보드의 다른 위젯과 어긋난다 — 위젯 내부는 **배경 기본색
     한 겹**이다(2026-09-05 결정). 카드 경계가 안 보이는 문제는 배경이 아닌
     다른 수단으로 다룬다.

     같은 이유로 좌우 여백도 주지 않는다. 여백을 주면 카드가 안쪽으로
     들어가고, 제목의 공용 여백(아래 주석)과 더해져 정렬이 두 번 밀린다. */
  /* ⚠ **좌우 여백은 여기(본체)에 준다 — 껍데기가 아니라.**
     
     이 요소는 스크롤 컨테이너라(`overflow-y: auto`) 자기 **패딩 상자**에서
     내용을 자른다. 카드가 본체와 폭이 같으면 카드의 경계선(`box-shadow` 링)이
     정확히 그 자름선 위에 놓여 **좌우만 안 보인다**(위아래는 스크롤 영역 안이라
     남는다). 실제로 그랬다 — 껍데기에 여백을 줬더니 카드와 본체가 둘 다
     26~702 가 되어 링의 1px 이 잘렸다(2026-09-05).
     
     본체에 주면 자름선은 바깥(14~714)에 있고 카드는 안쪽(26~702)이라 링이
     산다. 값은 옆 위젯의 같은 자리에서 가져왔다(`.seq-widget-container`:
     `padding: 10px 12px`) — 나란히 서는 물건이라 가장자리 여백이 다르면
     그것부터 눈에 띈다.
     
     ⚠ 그 대신 **머리줄이 따로 맞춰야 한다** — 머리줄은 본체 밖이라 이 여백을
       못 받는다(아래 `.aot-plotw-head`). */
  .aot-plotw-body {
    flex: 1 1 auto;
    overflow-y: auto;
    padding: 0 var(--aot-space-3) var(--aot-space-3);
    scrollbar-width: none;
    -ms-overflow-style: none;
  }
  .aot-plotw-body::-webkit-scrollbar { width: 0; height: 0; display: none; }
  /* 마지막 카드의 아래 여백은 카드가 아니라 **본체 끝**이 정한다(위 padding).
     카드 자신의 `margin-bottom`(16px)을 그대로 두면 본체 여백과 더해져 아래만
     28px 이 된다 — 머리줄이 만드는 위쪽 틈(space-3)과 어긋난다. 지금은 위아래
     둘 다 12px 이다. */
  .aot-plotw-body > .aot-ov-card:last-child .aot-ov-block:last-child,
  .aot-plotw-body > .aot-ov-block:last-child { margin-bottom: 0; }
  /* 어떤 자식도 부모보다 넓어질 수 없다 — flex 자식의 기본 `min-width: auto`
     가 이 위젯에서 폭이 새는 통로다(위 `.aot-plotw-list .aot-tag` 주석). */
  .aot-plotw, .aot-plotw-body, .aot-plotw-stage,
  .aot-plotw-stage-head, .aot-plotw-stage-head > * { min-width: 0; }
  .aot-plotw-body { overflow-x: hidden; }


  /* 카드 사이 가로 구분선은 두지 않는다. 한 번 넣었다가 뺐고(2026-09-05),
     그 자리를 배경 대비로 대신했다가 그것도 물렸다 — 위젯 내부는 배경 기본색
     한 겹이다(위 `.aot-plotw-body` 주석). 지금 카드를 나누는 것은 제목과
     박스 사이 여백뿐이다. */

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

     예전에는 `-webkit-line-clamp: 2` 로 두 줄만 보이고 나머지는 `title` 에만
     있었다 — 폰에는 `title` 이 없어 사실상 읽을 길이 없었다. 상자가 높이를
     잠그므로 clamp 는 중복이고, 이제 스크롤로 전문을 읽는다.

     스크롤바는 보이지 않는다(앱 전역 규칙). `overscroll-behavior: contain` 은
     상자 끝에서 스크롤이 위젯 본체로 넘어가지 않게 한다 — 안 주면 지침을 끝까지
     내린 순간 카드 전체가 함께 움직인다. */
  .aot-plotw-guidebox {
    /* 줄 간격을 **여기서 정한다.** 상자 높이가 `줄간격 × 줄수` 라, 줄 간격이
       바깥(본문 기본값)에서 오면 그 둘이 어긋나 두 번째 줄의 아랫부분이
       잘린다 — 처음에 1.5 로 계산해 놓고 실제 줄 간격은 1.8 이라 8px 이
       모자랐다(2026-09-05 실측: 상자 42px 대 내용 50px). 같은 변수를 두 곳이
       쓰게 해서 다시 어긋날 수 없게 한다. */
    --aot-plotw-guide-lh: 1.8;
    --aot-plotw-guide-lines: 2;
    line-height: var(--aot-plotw-guide-lh);
    height: calc(var(--aot-fs-md) * var(--aot-plotw-guide-lh)
                 * var(--aot-plotw-guide-lines));
    /* 목표 칩과 붙어 있으면 칩의 조밀함에 글이 딸려 읽힌다 — 칩 줄이 위에서
       받는 간격(space-2)보다 한 칸 더 벌려 "여기부터 문장" 을 표시한다. */
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
     ⚠ 여백을 벌리지 않는다. 한때 위아래 16px + 구분선을 줬다가 되돌렸다 —
     축과 그 단계의 내용은 **한 덩이**라 떼어 놓을 이유가 없고, 벌린 만큼
     카드만 커졌다(2026-08-28 지적). */
  /* ⚠ **높이를 예약한다.** 단계마다 목표 개수·지침 유무가 달라, 그대로 두면
     축을 누를 때마다 아래 카드가 밀린다. 머리줄 1 + 칩 1 + 지침 2 = 네 줄
     어치를 잡아 두고, 모자란 단계에서는 빈 자리로 남긴다 — 흔들리는 것보다
     빈 것이 낫다. (`min-height` 라 목표가 아주 많은 단계는 그만큼 늘어난다.) */
  .aot-plotw-stage {
    margin-top: var(--aot-space-2);
    /* 바닥 = 머리줄 + (간격 + 목표 칩 한 줄) + (간격 + 지침 상자).
       목표가 하나도 없는 단계는 칩 줄을 아예 안 그리는데(JS), 그때도 이
       바닥이 있어 카드가 짧아지지 않는다. */
    min-height: calc(var(--aot-font-size-xs) * 1.8
                     + var(--aot-space-2) + 1.6rem
                     + var(--aot-space-3)
                     + var(--aot-fs-md) * 1.8 * 2);
  }
  /* 어느 단계에도 지침이 없는 구획 — 지침 상자를 아예 안 내므로(JS
     `anyGuide`) 그 몫도 예약하지 않는다. 예약해 두면 두 줄이 통째로 죽은
     공간이 된다. 흔들림 걱정은 없다: 그런 구획은 **모든** 단계가 상자를
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
    /* ⚠ **줄 상자를 키우지 않는다.** 이 요소는 현재 단계에서만 없는데(이름은
       축의 머리줄이 이미 말한다), 큰 글자의 줄 상자가 그대로 줄 높이가 되면
       머리줄이 21.6px ↔ 24.5px 로 오간다 — 축을 누를 때마다 카드가 2.9px 씩
       밀리는 그 "미세한 레이아웃 변화" 다(2026-09-05 로컬 실측).
       `line-height: 1` 이면 이 글자의 상자가 옆 글자(21.6px)보다 작아져 줄
       높이를 정하는 쪽이 늘 옆 글자가 된다. 글자 크기는 그대로다 —
       baseline 정렬이라 위치도 그대로다. */
    line-height: 1;
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
  /* 현재 단계에서는 **감추되 자리는 남긴다.** `display:none` 으로 빼면 다른
     단계를 고르는 순간 버튼이 새로 생기며 머리줄이 밀린다. */
  .aot-plotw-stage-back.is-idle { visibility: hidden; }
  /* (옛 `.aot-plotw-guide` 간격 규칙은 상자로 옮겼다 — 위
     `.aot-plotw-guidebox { margin-top }`. 클래스 이름이 바뀐 뒤 이 선택자는
     아무것도 고르지 못해 간격이 0 이 돼 있었다.) */

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
  /* ⚠ **칩이 카드보다 넓어질 수 없게 한다.** 공용 `.aot-tag` 는
     `white-space: nowrap` 인데 flex 아이템의 기본 `min-width: auto` 와 만나면
     콘텐츠 폭 아래로 줄어들지 않는다 — 곡선을 따르는 목표는 값 자리에 **곡선
     이름**이 오므로("야간 저온 감응 곡선 v2") 그 이름 하나가 카드 폭을 넘겼고,
     단계마다 목표 구성이 달라 **단계를 바꿀 때 좌우폭이 변했다**(2026-09-05).
     넘치면 칩 안에서 자르고 전문은 `title` 이 진다(JS `_pair`).

     공용 `.aot-tag` 자체는 고치지 않는다 — 모달·설정 화면이 같은 칩을 쓰는데
     거기서는 잘릴 일이 없고, 공용 규칙을 이 위젯 사정으로 바꾸면 그 화면들이
     함께 바뀐다. 좁히는 것은 이 위젯의 목록뿐이다. */
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
     세우면 이름이 값으로 읽힌다(그 항목은 아직 숫자가 정해진 것이 아니다). */
  .aot-plotw-list em {
    font-style: normal;
    color: var(--aot-color-text-secondary);
  }

  /* (`.aot-plotw-trend` — 방향 화살표 규칙은 없앴다. 환경 카드가 공용
     빌더로 바뀌면서 축 없는 줄은 스파크라인이, 축 있는 줄은 `scaleNote` 가
     추세를 맡는다.) */

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
      envMode: {{ (widget_variables.env_mode or '')|tojson }},
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

    # 세로를 짧게 잡던 것을 되돌린다(2026-09-05). "진행 한 줄 + 타일 두어 줄"
    # 이던 시절의 값(6)인데, 환경 카드가 지도 구획 모달과 같은 빌더로 바뀌면서
    # 측정마다 자기 줄을 갖게 됐다(DLI·적산온도 포함). 6 이면 새로 놓은 위젯이
    # 첫 두 줄만 보이고 나머지는 스크롤 안으로 숨어 "고장 난 것" 처럼 보인다.
    # 12 는 실사용에서 나온 값이다 — 사용자가 이 위젯을 직접 11칸으로 늘려
    # 쓰고 있었다(2026-09-05 로컬 실측, 측정 5줄짜리 구획).
    'widget_width': 12,
    'widget_height': 12,

    'generate_page_variables': widget_variables,
    'execute_at_modification': execute_at_modification,

    # 고른 구획(`plot_uuid`)과 환경 카드의 보기 단위(`env_mode`)는 **여기
    # 없다.** 사람은 UUID 를 고르지 않고, 둘 다 위젯 본체에서 바꾼다(그쪽이
    # 직접 저장한다). 폼에 같은 항목을 두면 본체와 폼이 같은 키를 다투게 되고,
    # 폼을 한 번 저장할 때마다 본체에서 고른 것이 되돌아간다.
    'custom_options': [
        {
            'type': 'header',
            'name': lazy_gettext('What to monitor')
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
    'widget_dashboard_title_bar': """
    <span class="aot-w-title" style="padding-right:0.5em">{{each_widget.name}}</span>
    """,
    'widget_dashboard_body': WIDGET_BODY_HTML,
    'widget_dashboard_js_ready': '',
    'widget_dashboard_js_ready_end': '',
}
