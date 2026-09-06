# coding=utf-8
"""위젯 UI 규약 회귀 가드.

배경:
    위젯이 필요할 때마다 하나씩 만들어지면서 톤앤매너가 갈라져 있었다.
    2026-09-06 에 정리했는데(`docs/design/widget-uiux-unification-plan.md`),
    고쳐 놓고 다음 위젯이 또 벗어나면 몇 달 뒤 같은 문서를 다시 쓰게 된다.

    이 파일은 그때 세운 **다섯 가지 계약**만 지킨다. 취향이 아니라
    "실제로 화면이 어긋났던" 것들이다:

    1. 제목은 셸이 그린다 — 위젯이 자기 이름 span 을 만들지 않는다.
       (예전: 21종이 각자 만들었고 클래스를 빠뜨린 위젯의 제목만 13.6px/400,
        나머지는 14px/600 이었다.)
    2. 글자 크기는 사다리에서 고른다 — 절대 크기(px·rem)를 직접 적지 않는다.
       위젯 파이썬 파일 **과** `static/css/widget/*.css` 둘 다 본다(위젯의 화면이
       반씩 나뉘어 있어 한쪽만 지키면 다른 쪽으로 샌다).
       벗어나야 할 이유가 있으면 `/* 사다리 예외: <이유> */` 로 적는다 —
       이유 없이(또는 열 글자 미만으로) 적으면 검사가 그대로 막는다.
       (예전: 3단 사다리를 선언해 놓고 화면에는 8가지 크기가 나왔다.)
    3. 컨트롤 높이·모서리도 사다리에서 고른다.
       (예전: 높이 7가지·모서리 5가지가 섞여 있었다.)
    4. 크기 토큰은 한 곳에서만 정의한다 — 뒤에 로드되는 파일이 덮어쓰면
       앞의 값은 죽는다. (예전: `--aot-btn-height` 36px 은 한 번도 안 쓰였다.)
    5. 설정 UI 는 표준 옵션 행을 쓰고, 표준 렌더러가 이미 그리는 필드를
       위젯이 또 그리지 않는다.
       (예전: 풍향 위젯이 같은 필드를 두 번 그려 뒤엣것이 저장되지 않았다.)

    무거운 앱/DB 컨텍스트 없이 돌도록 소스 정적 분석만 쓴다.
"""
import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WIDGET_DIR = REPO / "aot" / "widgets"
CSS_DIR = REPO / "aot" / "aot_flask" / "static" / "css"

# WIDGET_INFORMATION 안에서 화면 조각을 담는 키들
TEMPLATE_KEYS = (
    "widget_dashboard_head",
    "widget_dashboard_title_bar",
    "widget_dashboard_body",
    "widget_dashboard_js",
    "widget_dashboard_js_ready",
    "widget_dashboard_js_ready_end",
    "widget_dashboard_configure_options",
)

SKIP_STEMS = {"__init__", "base_widget"}


def _widget_files():
    return sorted(p for p in WIDGET_DIR.glob("*.py") if p.stem not in SKIP_STEMS)


def _templates(path):
    """WIDGET_INFORMATION 의 템플릿 문자열들을 {키: 내용} 으로 돌려준다.

    모듈을 import 하지 않는다 — 위젯 모듈은 flask/DB 를 끌고 온다. AST 만 쓴다.

    ⚠ **모듈 수준 상수를 따라가야 한다.** 큰 위젯 셋(`AoT_map`·`AoT_facility`·
    `AoT_plot`)은 화면 조각이 길어서 모듈 수준 `WIDGET_HEAD_HTML` 상수로 빼 두고
    딕셔너리에는 이름만 적는다. 리터럴만 보면 **그 셋이 통째로 검사 밖**에
    놓인다 — 처음 만들 때 실제로 그랬고, 그래서 AoT_map 이 거는 CSS 세 개가
    중복 로드된 채 남아 있었다(2026-09-06 실측에서 드러났다).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    # 1) 모듈 수준의 `NAME = "문자열"` 을 먼저 모은다
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = node.value.value

    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and k.value in TEMPLATE_KEYS):
                continue
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out[k.value] = v.value
            elif isinstance(v, ast.Name) and v.id in consts:   # 2) 이름이면 따라간다
                out[k.value] = consts[v.id]
    return out


def _strip_comments(text):
    """Jinja 주석·HTML 주석·CSS 주석·JS 줄주석을 지운다.

    규약 위반을 세는 것이지 **설명을 세는 것이 아니다.** 주석에 옛 값을
    적어 두는 것은 오히려 권장한다(왜 그렇게 됐는지가 거기 있다).
    """
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return text


# ---------------------------------------------------------------- 계약 1


def test_widgets_do_not_draw_their_own_title():
    """제목 span 은 셸(dashboard_entry.html)만 그린다."""
    offenders = []
    for path in _widget_files():
        for key, tpl in _templates(path).items():
            if 'class="aot-w-title"' in _strip_comments(tpl):
                offenders.append(f"{path.name}:{key}")
    assert not offenders, (
        "위젯이 제목 span 을 직접 그리고 있다. 이름은 셸이 그린다 — "
        "`widget_dashboard_title_bar` 에는 이름 옆 부가물(상태·도구)만 넣을 것: "
        + ", ".join(offenders)
    )


# ---------------------------------------------------------------- 계약 2

WIDGET_CSS_DIR = CSS_DIR / "widget"

# 절대 크기(px·rem)만 본다. `em` 은 **다른 장치**다 — 아래 "왜 em 은 봐주는가" 참조.
_ABS_FONT_SIZE = re.compile(r"font-size:\s*(?!var\()([0-9.]*[0-9](?:px|rem))")

# 예외 표시. 값 바로 앞이나 같은 줄 뒤에 이유와 함께 적는다.
#     /* 사다리 예외: SVG 배지 숫자 — 사다리 최소(11.2px)로는 원 밖으로 넘친다 */
#     font-size: 9px;
_EXEMPT = re.compile(r"사다리\s*예외\s*:\s*(\S[^*/\n]{9,})")


def _abs_font_size_offenders(text, label):
    """절대 글자 크기 중 **이유가 적히지 않은** 것만 돌려준다.

    ## 왜 `em` 은 보지 않는가

    `em` 은 "사다리에서 고르는 크기" 가 아니라 **담는 상자를 따라가는 장치**다.
    `aot-sensor-label.css` 가 그 예다: 팝업 껍데기 하나에 px 기준(데스크탑 14px,
    480px 이하 16px)을 박고 안쪽은 전부 `em` 이라, 기준 하나만 바꾸면 구역·시설·
    사이트 목록 팝업의 글자가 **비율을 유지한 채** 함께 커진다. 그 값들을 전역
    rem 사다리로 끌어오면 그 되먹임이 끊긴다 — 실제로 그렇게 했다가
    "화면마다 비율이 어긋난다" 로 되돌린 기록이 같은 파일 주석에 있다.

    그래서 검사는 **체인의 뿌리**(px·rem)만 본다. 뿌리가 사다리에 있으면
    가지(em)는 저절로 사다리 위에 선다.
    """
    offenders = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        # 주석만 있는 줄은 건너뛴다(설명에 적힌 옛 값을 위반으로 세지 않는다)
        stripped = re.sub(r"/\*.*?\*/", "", line, flags=re.S)
        for m in _ABS_FONT_SIZE.finditer(stripped):
            window = "\n".join(lines[max(0, i - 6):i + 1])
            if _EXEMPT.search(window):
                continue
            offenders.append(f"{label}:{i + 1} → {m.group(1)}")
    return offenders


def test_no_literal_font_sizes_in_widgets():
    """위젯 파이썬 파일 안의 CSS."""
    offenders = []
    for path in _widget_files():
        for key, tpl in _templates(path).items():
            offenders += _abs_font_size_offenders(tpl, f"{path.name}:{key}")
    assert not offenders, (
        "위젯에 글자 크기가 직접 적혀 있다. 사다리에서 고르거나"
        "(--aot-font-size-2xs/xs/sm/base/lg/xl · 역할 이름 --aot-fs-*), "
        "사다리를 벗어나야 할 이유가 있으면 `/* 사다리 예외: … */` 로 적을 것: "
        + ", ".join(offenders)
    )


def test_no_literal_font_sizes_in_widget_css():
    """`static/css/widget/*.css` — 위젯 전용 CSS 파일.

    위젯의 화면은 파이썬 파일 안 `<style>` 과 이 디렉터리에 반씩 나뉘어 있다.
    한쪽만 지키면 다른 쪽으로 새 나간다.

    ⚠ 이 검사는 **위젯 CSS 까지만** 본다. 테마 파일
    (`bootstrap-4-themes/aot.css` 등)과 페이지 CSS 는 앱 전체 스타일 감사의
    범위이고, 그쪽은 규모가 다르다(별건).
    """
    offenders = []
    for css in sorted(WIDGET_CSS_DIR.glob("*.css")):
        offenders += _abs_font_size_offenders(
            css.read_text(encoding="utf-8"), css.name)
    assert not offenders, (
        "위젯 CSS 에 글자 크기가 직접 적혀 있다. 사다리에서 고르거나 "
        "`/* 사다리 예외: … */` 로 이유를 적을 것: " + ", ".join(offenders)
    )


# ---------------------------------------------------------------- 계약 3

# 컨트롤(버튼·입력칸)의 높이/모서리. 타일·카드·배지는 아직 사다리가 없어 제외한다
# (WP8 미결 — `docs/design/widget-uiux-unification-plan.md` 참조).
_CONTROL_SELECTOR = re.compile(r"\.[a-z0-9_-]*(?:btn|button|pill|trigger|input)[a-z0-9_-]*\s*[,{]", re.I)
_HEIGHT_LITERAL = re.compile(r"(?<!-)\bheight:\s*(?!var\()(?!auto)(?!100%)(?!inherit)([0-9.]+px)")


def _control_blocks(css_text):
    """`.xxx-btn { ... }` 처럼 컨트롤로 보이는 규칙 블록만 골라 준다."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css_text):
        selector, body = m.group(1), m.group(2)
        if _CONTROL_SELECTOR.search(selector):
            yield selector.strip()[:60], body


def test_control_heights_come_from_tokens():
    offenders = []
    for path in _widget_files():
        for key, tpl in _templates(path).items():
            for selector, body in _control_blocks(_strip_comments(tpl)):
                for m in _HEIGHT_LITERAL.finditer(body):
                    offenders.append(f"{path.name}:{key} `{selector}` → {m.group(1)}")
    assert not offenders, (
        "컨트롤 높이가 직접 적혀 있다. --aot-btn-height 를 쓸 것 "
        "(작은 단이 필요하면 토큰 파일에서 갈라 놓는다): " + ", ".join(offenders)
    )


# ---------------------------------------------------------------- 계약 4

_SIZE_TOKENS = (
    "--aot-btn-height",
    "--aot-btn-padding-x",
    "--aot-btn-font-size",
    "--aot-font-size-sm",
    "--aot-fs-md",
)


@pytest.mark.parametrize("token", _SIZE_TOKENS)
def test_size_token_defined_once(token):
    """크기 토큰은 한 곳에서만 정의한다.

    뒤에 로드되는 파일이 같은 이름을 다시 정의하면 앞의 값은 조용히 죽는다 —
    `--aot-btn-height` 가 실제로 그랬다(36px 이라고 적혀 있었지만 테마 두 곳이
    32px 로 덮어써서 36px 은 한 번도 화면에 나온 적이 없다).
    """
    pattern = re.compile(r"^\s*" + re.escape(token) + r"\s*:", re.M)
    found = []
    for css in sorted(CSS_DIR.rglob("*.css")):
        if "vendor" in css.parts or css.name.endswith(".min.css"):
            continue
        text = re.sub(r"/\*.*?\*/", "", css.read_text(encoding="utf-8"), flags=re.S)
        found += [str(css.relative_to(CSS_DIR))] * len(pattern.findall(text))
    assert len(found) == 1, (
        f"{token} 이 {len(found)}곳에서 정의됐다 ({', '.join(found) or '없음'}). "
        "크기 토큰은 aot-theme-variables.css 한 곳에서만 정한다."
    )


# ---------------------------------------------------------------- 계약 5


def _option_ids(path):
    """custom_options 중 **표준 렌더러가 실제로 그리는** 옵션의 id."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ids = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        pairs = {
            k.value: v.value
            for k, v in zip(node.keys, node.values)
            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
        }
        opt_id, opt_type = pairs.get("id"), pairs.get("type")
        if opt_id and opt_type not in (None, "hidden", "header", "collapse_start", "collapse_end"):
            ids.append(opt_id)
    return set(ids)


def test_configure_options_do_not_duplicate_standard_fields():
    """위젯이 표준 렌더러가 이미 그리는 필드를 또 그리지 않는다.

    같은 `name` 의 입력이 둘이면 저장 때 **앞의 것만** 반영된다 — 뒤엣것을
    고친 사용자는 값이 안 바뀌는 것을 본다(풍향 위젯이 실제로 그랬다).
    """
    offenders = []
    for path in _widget_files():
        tpl = _templates(path).get("widget_dashboard_configure_options", "")
        if not tpl:
            continue
        emitted = set(re.findall(r'name="([a-zA-Z0-9_]+)"', _strip_comments(tpl)))
        dup = sorted(_option_ids(path) & emitted)
        if dup:
            offenders.append(f"{path.name} → {dup}")
    assert not offenders, (
        "설정 UI 가 custom_options 로 이미 그려지는 필드를 다시 그린다. "
        "위젯이 직접 그려야 하는 칸은 `type: 'hidden'` 으로 선언할 것: "
        + ", ".join(offenders)
    )


def test_configure_options_use_the_modern_option_row():
    """설정 UI 는 부트스트랩 격자가 아니라 표준 옵션 행을 쓴다."""
    legacy = re.compile(r'class="[^"]*\b(form-row|col-auto|control-label)\b')
    offenders = []
    for path in _widget_files():
        tpl = _templates(path).get("widget_dashboard_configure_options", "")
        if not tpl:
            continue
        hits = {m.group(1) for m in legacy.finditer(_strip_comments(tpl))}
        if hits:
            offenders.append(f"{path.name} → {sorted(hits)}")
    assert not offenders, (
        "설정 UI 에 부트스트랩 격자 마크업이 남아 있다. "
        "`aot-modal-option-row` + `aot-modal-option-label` + "
        "`aot-modal-option-control` 을 쓸 것: " + ", ".join(offenders)
    )


# ---------------------------------------------------------------- 접근성 최소선


def test_no_keyboard_unreachable_click_targets():
    """`<div onclick>` 처럼 키보드로 닿을 수 없는 조작 대상을 만들지 않는다."""
    pattern = re.compile(r"<(div|span|td|li)\b(?:(?!>).)*onclick=", re.S | re.I)
    offenders = []
    for path in _widget_files():
        for key, tpl in _templates(path).items():
            for m in pattern.finditer(_strip_comments(tpl)):
                if 'role="button"' not in m.group(0):
                    offenders.append(f"{path.name}:{key} <{m.group(1)}>")
    assert not offenders, (
        "키보드로 닿을 수 없는 조작 대상이 있다. `<button>` 을 쓰거나 "
        "role=\"button\" + tabindex=\"0\" + Enter/Space 처리를 붙일 것: "
        + ", ".join(offenders)
    )


# ---------------------------------------------------------------- 중복 로드

LAYOUT = REPO / "aot" / "aot_flask" / "templates" / "layout.html"


def test_widgets_do_not_relink_globally_loaded_css():
    """layout.html 이 이미 싣는 CSS 를 위젯이 또 걸지 않는다.

    예전에는 `aot-toggle.css` 가 한 대시보드의 head 에 **4번** 있었다
    (layout 1 + 위젯 3). `widget_function_status` 는 그것을 body 에 걸어서
    **위젯 인스턴스마다** 한 번씩 더 내려갔다.
    """
    layout_css = set(re.findall(r"css/([a-z0-9/_.-]+\.css)", LAYOUT.read_text(encoding="utf-8")))
    offenders = []
    for path in _widget_files():
        for key, tpl in _templates(path).items():
            for href in re.findall(r'href="[^"]*css/([a-z0-9/_.-]+\.css)', _strip_comments(tpl)):
                if href in layout_css:
                    offenders.append(f"{path.name}:{key} → {href}")
    assert not offenders, (
        "layout.html 이 이미 싣는 CSS 를 위젯이 다시 건다: " + ", ".join(offenders)
    )


def test_widget_css_links_are_load_guarded():
    """여러 위젯이 같은 CSS 를 걸 때는 `dashboard_dict` 가드를 쓴다.

    head 는 **위젯 종류마다 한 번** 렌더되므로, 같은 파일을 세 위젯이 걸면
    세 번 내려간다. `{% if "key" not in dashboard_dict %}` 로 한 번만 걸리게 한다
    (`highstock` 이 예전부터 쓰던 방식이다).
    """
    seen = {}
    for path in _widget_files():
        for key, tpl in _templates(path).items():
            for href in re.findall(r'href="[^"]*css/([a-z0-9/_.-]+\.css)', _strip_comments(tpl)):
                seen.setdefault(href, []).append((path.name, key, tpl))
    offenders = []
    for href, uses in seen.items():
        if len(uses) < 2:
            continue
        for name, key, tpl in uses:
            # ⚠ **링크 한 줄 단위**로 본다. 예전에는 "블록 어딘가에 dashboard_dict
            # 가 있으면 통과" 였는데, 그러면 같은 head 안에서 어떤 링크는 걸려
            # 있고 어떤 링크는 안 걸려 있어도 지나간다 — AoT_map 이 실제로
            # 그랬다(가드 셋을 붙였는데 aot-plot-form.css 만 맨몸이었다).
            lines = _strip_comments(tpl).splitlines()
            for i, line in enumerate(lines):
                if href not in line:
                    continue
                window = "\n".join(lines[max(0, i - 4):i + 1])
                if "dashboard_dict" not in window:
                    offenders.append(f"{name}:{key} → {href}")
                    break
    assert not offenders, (
        "여러 위젯이 같은 CSS 를 가드 없이 건다(그만큼 중복 로드된다): "
        + ", ".join(offenders)
    )
