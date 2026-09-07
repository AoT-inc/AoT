# coding=utf-8
"""앱 전체 CSS 규약 가드 — 글자 크기·모서리 사다리와 템플릿 인라인.

## 왜 위젯 가드와 따로 있는가

`test_widget_ui_conventions.py` 는 2026-09-06 위젯 통합 작업이 세운 계약을
지킨다. 그 검사는 범위를 **위젯 파이썬 + `static/css/widget/*.css`** 로 한정하고,
자기 주석에 그 이유를 적어 뒀다 — "테마 파일과 페이지 CSS 는 앱 전체 스타일
감사의 범위이고, 그쪽은 규모가 다르다".

이 파일이 그 나머지다. 검사 규칙은 **같은 함수를 그대로 가져다 쓴다**
(`_abs_font_size_offenders`). 규칙이 두 벌이 되면 한쪽만 고쳐지고, 그것이
애초에 사다리가 두 벌이 됐던 경위다.

## 왜 지금 켜는가 — 고치기 전에 켠다

대상에 위반이 152곳 남아 있다. 다 고친 뒤에 켜는 것이 깔끔해 보이지만,
그러면 고치는 동안 새것이 계속 들어온다. 위젯 작업에서 확인된 순서가 있다:
검사를 먼저 세우자 **그 검사가 곧바로 18곳을 더 잡았다.**

그래서 지금 수치를 상한으로 박고, 늘면 막는다. 상한은 **내려가기만 한다.**

## 상한을 만났을 때

새 위반이라면 사다리에서 고른다:

    --aot-font-size-2xs  0.7rem   11.2px   조밀한 상세 라벨
    --aot-font-size-xs   0.75rem  12px     캡션·타임스탬프·배지
    --aot-font-size-sm   0.875rem 14px     ← 기준. 제목·라벨·단위·본문
    --aot-font-size-base 1rem     16px     본문 강조
    --aot-font-size-lg   1.125rem 18px     값 한 단 아래
    --aot-font-size-xl   1.5rem   24px     측정값·게이지 중앙

역할 이름(`--aot-fs-title` · `--aot-fs-body` · `--aot-fs-value` …)은 위 단들을
가리키기만 한다. 읽기 쉬운 쪽을 쓴다.

사다리를 못 쓰는 자리라면 이유를 적는다. 열 글자 이상이어야 통과한다:

    /* 사다리 예외: 고정 크기 원형 배지 안의 SVG 숫자다. 최소단(11.2px)이면
       원 밖으로 넘친다 — 도형이 크기를 정하는 자리다. */
    font-size: 9px;

**상한부터 올리지 않는다.** 올려야 한다고 판단했다면 왜 그 자리가 사다리
밖이어야 하는지가 먼저 있어야 하고, 그 이유는 예외 주석으로 적을 수 있다.

## `em` 은 왜 안 보는가

`_abs_font_size_offenders` 의 독스트링에 있다. 요약하면 `em` 은 사다리에서
고르는 크기가 아니라 담는 상자를 따라가는 장치라, **체인의 뿌리**(px·rem)만
본다. 뿌리가 사다리에 있으면 가지는 저절로 사다리 위에 선다.
"""
import re
from pathlib import Path

from aot.tests.test_widget_ui_conventions import (
    _EXEMPT,
    _abs_font_size_offenders,
    _blank_comments,
)

CSS_DIR = Path(__file__).resolve().parents[2] / "aot" / "aot_flask" / "static" / "css"

# 서드파티 테마 20종. AoT 가 쓰기는 하지만 우리가 쓴 것이 아니라 받아 온 것이라
# 사다리를 강요하지 않는다. `aot.css` 만 우리 테마다.
_THIRD_PARTY_THEME_DIR = "bootstrap-4-themes"
_OUR_THEME = "aot.css"

# 디렉터리에 섞여 있는 vendor 파일들(라이선스 때문에 손대지 않는다).
_VENDOR_FILES = {"daterangepicker.css", "gridstack.css"}


def _target_css():
    """이 가드가 보는 CSS.

    제외:
      · `widget/`            — `test_widget_ui_conventions.py` 가 이미 본다
      · vendor · `*.min.css` · `datatables_2_2_2/`
      · 서드파티 부트스트랩 테마 20종(우리 `aot.css` 는 포함)
    """
    out = []
    for path in sorted(CSS_DIR.rglob("*.css")):
        parts = set(path.parts)
        if path.name.endswith(".min.css") or "vendor" in parts:
            continue
        if "datatables_2_2_2" in parts:
            continue
        if path.parent.name == "widget":
            continue
        if path.parent.name == _THIRD_PARTY_THEME_DIR and path.name != _OUR_THEME:
            continue
        if path.name in _VENDOR_FILES:
            continue
        out.append(path)
    return out


# 위반 수 상한. **내려가기만 한다.**
#
# 2026-09-06 에 이 표를 152곳으로 시작해 2026-09-07 에 **0 으로 비웠다.**
# 지금은 상한이 없으므로 절대 크기가 하나라도 들어오면 그 즉시 걸린다 —
# 표를 다시 채워 통과시키지 말 것. 사다리에서 고르거나, 사다리를 못 쓰는
# 자리면 `/* 사다리 예외: <이유> */` 로 이유를 적는 것이 답이다.
#
# 이 표는 큰 정리를 나눠서 할 때를 위한 장치다. 다시 필요해지면(예: 모서리
# 사다리를 새로 세울 때) 같은 방식으로 쓰되, 비우는 것을 끝으로 삼는다.
_FONT_SIZE_BUDGET = {}


def _current_counts():
    counts = {}
    detail = {}
    for path in _target_css():
        rel = str(path.relative_to(CSS_DIR))
        offenders = _abs_font_size_offenders(
            path.read_text(encoding="utf-8"), rel)
        if offenders:
            counts[rel] = len(offenders)
            detail[rel] = offenders
    return counts, detail


def test_font_size_ladder_does_not_regress():
    """페이지·테마 CSS 의 절대 글자 크기가 늘지 않는다."""
    counts, detail = _current_counts()

    grew = []
    for rel, n in sorted(counts.items()):
        cap = _FONT_SIZE_BUDGET.get(rel, 0)
        if n > cap:
            new = detail[rel][cap:] if cap else detail[rel]
            grew.append(f"{rel}: {cap} → {n} ({', '.join(new[:4])})")

    assert not grew, (
        "절대 글자 크기가 늘었다. 사다리에서 고르거나"
        "(--aot-font-size-2xs/xs/sm/base/lg/xl · 역할 이름 --aot-fs-*), "
        "사다리를 벗어나야 할 이유가 있으면 값 앞 여섯 줄 안에 "
        "`/* 사다리 예외: <열 글자 이상 이유> */` 로 적을 것. "
        "상한(_FONT_SIZE_BUDGET)부터 올리지 말 것 — 이 표는 내려가기만 한다: "
        + " | ".join(grew)
    )


def test_font_size_budget_is_not_stale():
    """고친 만큼 상한도 내려온다.

    상한이 실제보다 높게 남아 있으면 그만큼 새 위반이 조용히 들어올 자리가
    생긴다. 줄어든 것을 반영하지 않으면 이 검사가 알려 준다.
    """
    counts, _ = _current_counts()

    stale = []
    for rel, cap in sorted(_FONT_SIZE_BUDGET.items()):
        now = counts.get(rel, 0)
        if now < cap:
            stale.append(f"{rel}: 상한 {cap} → 실제 {now}")

    assert not stale, (
        "위반을 고쳤으면 _FONT_SIZE_BUDGET 도 그만큼 내릴 것 "
        "(0 이 되면 항목째 지운다). 남겨 두면 그 자리에 새것이 들어와도 "
        "안 걸린다: " + " | ".join(stale)
    )


def test_budget_entries_point_at_real_files():
    """상한 표에 없는 파일이 적혀 있지 않다(파일이 지워졌거나 이름이 바뀐 경우)."""
    known = {str(p.relative_to(CSS_DIR)) for p in _target_css()}
    missing = sorted(set(_FONT_SIZE_BUDGET) - known)
    assert not missing, (
        "_FONT_SIZE_BUDGET 이 이 가드의 대상이 아닌 파일을 가리킨다"
        "(삭제·이름 변경·제외 규칙 변경). 표에서 지울 것: " + ", ".join(missing)
    )


# ---------------------------------------------------------------- 모서리 사다리

# 절대 모서리(px·rem)만 본다. 사다리 밖에 두는 것은 **값이 아니라 모양**이라
# 애초에 이 패턴에 걸리지 않는다:
#   · `50%`      원형          · `0` / `0px`   모서리 없음
#   · `em`       상자 추종      · `inherit` / `calc()`
#   · `var(--aot-btn-pill-radius)` 알약
_ABS_RADIUS = re.compile(
    r"border-radius:\s*([^;}\n]+)")
_RADIUS_LITERAL = re.compile(r"(?<![\w.-])(\d*\.?\d+)(px|rem)(?![\w-])")

# 2026-09-07 에 세우면서 0 으로 시작했다. 상한을 두지 않는다 — 사다리를 만든
# 그 자리에서 전부 옮겼으므로 처음부터 걸릴 것이 없다.
_RADIUS_BUDGET = {}


# `var(--토큰, 8px)` 의 폴백 자리. 토큰이 앞에 있으므로 위반이 아니다
# (color-system.md §5 규칙 1 — 폴백 리터럴은 토큰 기본값과 같으면 허용).
_VAR_FALLBACK = re.compile(r"var\(\s*--[A-Za-z0-9-]+\s*,\s*([^)]*)\)")


def _abs_radius_offenders(text, label):
    """사다리를 벗어난 절대 모서리 중 **이유가 적히지 않은** 것."""
    offenders = []
    src = _blank_comments(text)
    lines = src.splitlines()
    raw_lines = text.splitlines()
    for i, line in enumerate(lines):
        for decl in _ABS_RADIUS.finditer(line):
            value = decl.group(1)
            base = decl.start(1)
            skip = [(base + m.start(1), base + m.end(1))
                    for m in _VAR_FALLBACK.finditer(value)]
            for lit in _RADIUS_LITERAL.finditer(value):
                pos = base + lit.start()
                if any(a <= pos < b for a, b in skip):
                    continue
                if float(lit.group(1)) == 0:
                    continue          # `0px` 은 모서리 없음
                window = "\n".join(raw_lines[max(0, i - 6):i + 1])
                if _EXEMPT.search(window):
                    continue
                offenders.append(f"{label}:{i + 1} → {lit.group(0)}")
    return offenders


def _current_radius_counts():
    counts, detail = {}, {}
    for path in _target_css():
        rel = str(path.relative_to(CSS_DIR))
        offenders = _abs_radius_offenders(path.read_text(encoding="utf-8"), rel)
        if offenders:
            counts[rel] = len(offenders)
            detail[rel] = offenders
    return counts, detail


def test_radius_ladder_does_not_regress():
    """모서리도 사다리에서 고른다.

        --aot-radius-xs   4px   작은 컨트롤·체크박스·인라인 칩
        --aot-radius-sm   8px   카드·툴팁·패널 — 가장 많이 쓰인 값
        --aot-radius-md  12px   큰 카드·배지·목록 패널
        --aot-radius-lg  16px   메시지 말풍선·알약형 입력칸
        --aot-radius-xl  20px   가장 큰 카드·강조 버튼

    모양은 사다리가 아니다 — 원형은 `50%`, 알약은 `--aot-btn-pill-radius`,
    없으면 `0`. 버튼 컨트롤은 `--aot-btn-radius`(18px)·`-sm`(16px) 을 쓴다.
    """
    counts, detail = _current_radius_counts()
    grew = []
    for rel, n in sorted(counts.items()):
        cap = _RADIUS_BUDGET.get(rel, 0)
        if n > cap:
            new = detail[rel][cap:] if cap else detail[rel]
            grew.append(f"{rel}: {cap} → {n} ({', '.join(new[:4])})")
    assert not grew, (
        "모서리가 사다리 밖으로 나갔다. 다섯 단에서 고르거나"
        "(--aot-radius-xs/sm/md/lg/xl), 모양이면 50% · "
        "var(--aot-btn-pill-radius) · 0 을 쓰거나, 그래도 벗어나야 하면 "
        "`/* 사다리 예외: <열 글자 이상 이유> */` 로 이유를 적을 것: "
        + " | ".join(grew)
    )


def test_radius_budget_is_not_stale():
    """모서리 상한도 내려가기만 한다."""
    counts, _ = _current_radius_counts()
    stale = [f"{rel}: 상한 {cap} → 실제 {counts.get(rel, 0)}"
             for rel, cap in sorted(_RADIUS_BUDGET.items())
             if counts.get(rel, 0) < cap]
    assert not stale, (
        "고쳤으면 _RADIUS_BUDGET 도 내릴 것: " + " | ".join(stale))


# ---------------------------------------------------------------- 크기 수정자

def test_pill_button_small_variant_is_wired_to_the_token():
    """`aot-pill-btn-sm` 은 정의가 있고, 치수를 **토큰에서** 읽는다.

    2026-09-06 위젯 작업이 "열 곳 넘게 쓰이는데 CSS 정의가 어디에도 없다" 고
    보고했다 — 클래스를 달아도 아무 일도 일어나지 않는 상태였다.

    고치는 방향이 둘이었다: 더 작은 치수를 지어내거나, 이음매만 만들거나.
    앞쪽은 요청도 없이 여섯 화면의 버튼을 작게 만든다. 그래서 뒤를 골랐고,
    이 검사가 그 선택을 잠근다:

      · 정의가 존재할 것 (다시 죽은 클래스가 되지 않게)
      · 리터럴이 아니라 `--aot-btn-height-sm` 을 읽을 것
        (토큰 한 곳만 갈라 놓으면 호출부 열한 곳이 함께 따라오도록)
    """
    css = (CSS_DIR / "aot-modal-modern.css").read_text(encoding="utf-8")
    marker = ".btn.aot-pill-btn.aot-pill-btn-sm"
    assert marker in css, (
        "aot-pill-btn-sm 정의가 사라졌다 — 호출부는 그대로라 "
        "클래스만 달고 아무 일도 안 일어나는 상태로 돌아간다")
    block = css.split(marker, 1)[1].split("}", 1)[0]
    assert "var(--aot-btn-height-sm)" in block, (
        "aot-pill-btn-sm 이 높이를 리터럴로 적고 있다. 토큰에서 읽을 것 — "
        "그래야 더 작은 단이 필요해질 때 토큰 한 곳만 갈라 놓으면 된다: " + block)


# ---------------------------------------------------------------- 템플릿 인라인

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "aot" / "aot_flask" / "templates"

_INLINE_STYLE = re.compile(r'style\s*=\s*"([^"]*)"')

# 사다리가 있는 속성만 본다.
_SIZED = ("font-size", "border-radius")
_COLORED = ("color", "background", "background-color", "border-color")


def _inline_offenders(text, label):
    """인라인 `style=` 에 리터럴로 적힌 글자 크기·모서리·색.

    ## 통과시키는 것

    · **Jinja 값**(`{{ }}` · `{% %}`) — 서버가 채우는 값이라 CSS 로 옮길 수
      없다. 막대 폭·브랜드 이미지 높이처럼 실제로 그런 자리가 있다.
    · **토큰**(`var(--aot-...)`) — 인라인이라도 사다리 위에 있으면 된다.
      이미 107곳이 그렇게 쓰고 있다.

    ## 일부러 안 보는 것 — 반투명 rgba()

    인라인 `rgba()` 35곳은 거의 전부 그림자와 스크림
    (`box-shadow: 0 8px 24px rgba(0,0,0,0.12)` · `background: rgba(0,0,0,0.5)`)
    이다. 그것들이 가야 할 **그림자·높이(elevation) 사다리는 아직 없다**
    (감사 기록: 그림자 토큰 11종 옆에 원시값 90종). 갈 곳이 없는 것을 막으면
    검사가 통과할 수 없는 요구를 하게 되므로, 그 사다리를 세울 때 함께 켠다.
    """
    offenders = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for sm in _INLINE_STYLE.finditer(line):
            value = sm.group(1)
            if "{{" in value or "{%" in value:
                continue
            for decl in value.split(";"):
                if ":" not in decl:
                    continue
                prop, raw = decl.split(":", 1)
                prop, raw = prop.strip().lower(), raw.strip()
                if "var(" in raw:
                    continue
                bad = ((prop in _SIZED and re.match(r"[\d.]+(px|rem)\b", raw))
                       or (prop in _COLORED and raw.startswith("#")))
                if not bad:
                    continue
                window = "\n".join(lines[max(0, i - 6):i + 1])
                if _EXEMPT.search(window):
                    continue
                offenders.append(f"{label}:{i + 1} -> {prop}: {raw[:24]}")
    return offenders


# 193 으로 시작해 **2026-09-07 에 0 으로 비웠다.** 상한이 없으므로 리터럴이
# 하나라도 들어오면 즉시 걸린다 — 표를 다시 채워 통과시키지 말 것.
#
# 비우는 데 쓴 방법 셋:
#   · 같은 것이 여러 곳에 복사돼 있으면 **공용 클래스**로 (도움말 아이콘 32곳)
#   · 규칙이 이미 CSS 에 있는데 호출부가 개별로 덮고 있으면 **CSS 를 고치고**
#     인라인을 걷어낸다 (navbar 드롭다운 12곳 — CSS 는 `border-radius: 0` 이라고
#     적혀 있는데 화면은 열아홉 곳의 인라인 때문에 둥글었다)
#   · 나머지는 **인라인인 채로 토큰만** 쓴다 (147곳). 인라인이라는 사실보다
#     값이 사다리 밖이라는 것이 문제였다.
# `user_templates/widget_template_*.html` 은 **생성물**이다 — aotflask 기동 시
# `aot/widgets/*.py` 에서 만들어지고 `.gitignore` 에 있다. 세지 않는다:
#
#   · 정본인 `.py` 를 이미 세고 있어 **한 위반을 두 번** 잡는다.
#   · 있다가 없다가 한다. 앱이 한 번이라도 뜬 작업본에는 있고 갓 clone 한
#     곳에는 없어, **같은 코드가 어떤 날은 통과하고 어떤 날은 실패**한다.
#     2026-09-07 에 실제로 그렇게 세 검사가 한꺼번에 붉어졌다 — 고칠 것은
#     위젯이 아니라 이 스캐너의 범위였다.
_GENERATED_TEMPLATE_DIR = "user_templates"


def _is_generated_template(rel_path):
    return rel_path.replace("\\", "/").startswith(_GENERATED_TEMPLATE_DIR + "/")


_INLINE_BUDGET = {}


def _current_inline_counts():
    counts, detail = {}, {}
    for path in sorted(TEMPLATE_DIR.rglob("*.html")):
        rel = str(path.relative_to(TEMPLATE_DIR))
        if _is_generated_template(rel):
            continue
        offenders = _inline_offenders(path.read_text(encoding="utf-8"), rel)
        if offenders:
            counts[rel] = len(offenders)
            detail[rel] = offenders
    return counts, detail


def test_inline_style_literals_do_not_regress():
    """템플릿 인라인에 글자 크기·모서리·색을 리터럴로 새로 적지 않는다.

    인라인은 CSS 파일 밖이라 사다리 검사가 닿지 않는 사각지대였다. 감사 시점에
    193곳이 있었고, 그 자리는 토큰 치환도 사다리 정리도 지나가지 않는다.

    고칠 곳으로 옮기는 것(계획 11번)과 별개로, **새로 늘지 않게** 먼저 막는다.
    """
    counts, detail = _current_inline_counts()
    grew = []
    for rel, n in sorted(counts.items()):
        cap = _INLINE_BUDGET.get(rel, 0)
        if n > cap:
            new = detail[rel][cap:] if cap else detail[rel]
            grew.append(f"{rel}: {cap} -> {n} ({', '.join(new[:3])})")
    assert not grew, (
        "템플릿 인라인에 리터럴 값이 늘었다. 공용 CSS 로 옮기거나, 인라인이어야 "
        "하면 토큰을 쓸 것(style 안에서도 var(--aot-font-size-sm) 이 된다 — "
        "이미 107곳이 그렇게 쓴다). 상한(_INLINE_BUDGET)부터 올리지 말 것: "
        + " | ".join(grew))


def test_inline_budget_is_not_stale():
    """인라인 상한도 내려가기만 한다."""
    counts, _ = _current_inline_counts()
    stale = [f"{rel}: 상한 {cap} -> 실제 {counts.get(rel, 0)}"
             for rel, cap in sorted(_INLINE_BUDGET.items())
             if counts.get(rel, 0) < cap]
    assert not stale, (
        "인라인을 정리했으면 _INLINE_BUDGET 도 그만큼 내릴 것 "
        "(0 이 되면 항목째 지운다): " + " | ".join(stale))


# ------------------------------------------------------------- !important 상한

# ## 왜 0 이 목표가 아닌가
#
# 앞의 세 상한(글자·모서리·인라인)은 0 으로 비웠다. 사다리에서 고르면 되는
# 일이었기 때문이다. `!important` 는 다르다 — 부트스트랩을 이겨야 하는 자리가
# 실제로 있고, 그 자리의 `!important` 는 소음이 아니라 **일을 하고 있다.**
#
# ## 무엇을 재서 걷어냈나 (2026-09-07)
#
# 추측으로 지우지 않았다. 브라우저에서 `!important` 를 실제로 떼고 계산된
# 스타일이 바뀌는지 쟀다. 22개 화면 · 모달 열린 상태 · 어두운 테마까지:
#
#     펼친 선언 3,887개 중
#       627 (16%)  떼면 화면이 바뀐다        — 진짜
#     1,606 (41%)  요소가 있는데도 안 바뀐다  — 소음
#     1,654 (43%)  그 요소가 한 번도 안 나옴  — 판정 불가
#
# 1~5차로 파일 17개에서 소스 725회를 걷어냈고, 편집본과 원본을 같은 페이지에
# 나란히 켜서 화면·상태 스물 몇 가지(모바일 폭 375px · 어두운 테마 · 모달 열린
# 상태 · 드롭다운 펼친 상태 · 실제 `:hover`)에서 **계산된 스타일 차이 0** 을
# 확인했다.
#
# ## ⚠ `@media` 안은 **그 조건에서** 재야 한다
#
# 조건부 블록은 그 조건이 성립하는 화면에서만 적용된다. 데스크톱 폭 하나에서
# 재면 좁은 화면·인쇄에서만 하는 일이 "아무 일도 안 함" 으로 보인다. 1차에서
# 실제로 39곳을 그렇게 지웠고 2차 검증에서 드러나 되돌렸다.
#
# 2026-09-07 5차에서 **폭 320·500·700·800·1400px 다섯 자리**를 돌며
# `matchMedia` 로 그때 성립하는 블록만 골라 다시 쟀다(141회 제거). 남은 것 중
# `@media print` 23회는 **인쇄 미디어를 흉내 낼 수단이 없어 손대지 않았다.**
#
# ## ⚠ `:hover` 같은 상태도 재지 않은 것이다
#
# 평상시 화면만 재면 상태에서만 하는 일이 안 보인다. `.btn-primary` 의
# `background-color !important` 는 평상시엔 순서만으로도 이기지만, 부트스트랩의
# `.btn-primary:hover` 는 명시도가 더 높아 `!important` 없이는 진다. 3차에서
# 후보 361개 중 **84개가 그런 자리**였다 — 같은 속성을 건드리는 상태 규칙이
# 같은 요소에 걸리면 후보에서 뺀다.
#
# ## ⚠ JS 가 인라인으로 쓰는 속성은 후보에서 뺀다
#
# `display` 가 대표다. jQuery `.show()`/`.hide()` 는 **인라인** 스타일을 쓰고,
# 인라인은 `!important` 아닌 규칙을 전부 이긴다. 그러니 `display: none
# !important` 는 "지금 아무 일도 안 하는" 것처럼 보여도 JS 가 인라인을 심는
# 순간부터 일을 한다. 정지 화면 스냅샷으로는 그 순간을 볼 수 없다.
#
# ## ⚠ 한꺼번에 떼서 잰 결과는 일부만 뗄 때 그대로 성립하지 않는다
#
# "전부 떼도 화면이 같다" 가 "그중 일부만 떼도 같다" 를 뜻하지 않는다. 남긴
# `!important` 가 다른 자리를 이기기 시작하기 때문이다(실제로 select 배경
# 화살표가 그렇게 되살아났다). **실제로 지울 목록을 정한 뒤 그 상태로 다시
# 대조**해야 한다.
#
# ## 새로 붙이려 할 때
#
# 상한부터 올리지 말 것. 먼저 물을 것은 "무엇을 이기려고 붙이는가" 다.
# 이기려는 상대가 우리 CSS 라면 선택자를 고치는 쪽이 답이다 — 걷어낸 306회가
# 대부분 그런 자리였다(우리가 우리 걸 덮고 있었다). 상대가 부트스트랩이면
# 정당하다. 그때는 상한을 올리되, 무엇을 이기는지 주석으로 남길 것.
_IMPORTANT = re.compile(r"!\s*important")

_IMPORTANT_BUDGET = {
    "aot-modal-modern.css": 222,
    "bootstrap-4-themes/aot.css": 211,
    "map/map.css": 183,
    "components/aot-base-ui.css": 139,
    "ai/ai_scheduler.css": 53,
    "aot-entry-ui.css": 50,
    "pages/geo-facility.css": 36,
    "aot-base.css": 15,
    "aot-settings.css": 14,
    "aot.css": 13,
    "components/aot-drawer-form.css": 9,
    "dashboard.css": 8,
    "ai/device-timeline.css": 7,
    "ai/aot-ai-global.css": 5,
    "custom.css": 5,
    "components/aot-dataviz.css": 4,
    "pages/admin-upgrade.css": 3,
    "aot-custom-ui-preview.css": 2,
    "components/aot-drawer.css": 2,
    "gridstack-custom.css": 2,
    "pages/mcp_servers.css": 2,
    "ai/ai_entry.css": 1,
    "components/aot-time-wheel.css": 1,
    "pages/logview.css": 1,
}


def _current_important_counts():
    counts = {}
    for path in _target_css():
        text = _blank_comments(path.read_text(encoding="utf-8"))
        n = len(_IMPORTANT.findall(text))
        if n:
            counts[str(path.relative_to(CSS_DIR))] = n
    return counts


def test_important_does_not_regress():
    """`!important` 가 늘지 않는다."""
    counts = _current_important_counts()
    grew = [f"{rel}: {_IMPORTANT_BUDGET.get(rel, 0)} -> {n}"
            for rel, n in sorted(counts.items())
            if n > _IMPORTANT_BUDGET.get(rel, 0)]
    assert not grew, (
        "!important 가 늘었다. 무엇을 이기려는지 먼저 볼 것 — 상대가 우리 CSS "
        "라면 선택자를 고치는 쪽이 답이다. 부트스트랩을 이기는 자리라면 상한을 "
        "올리되 무엇을 이기는지 주석으로 남길 것: " + " | ".join(grew))


def test_important_budget_is_not_stale():
    """`!important` 상한도 내려가기만 한다."""
    counts = _current_important_counts()
    stale = [f"{rel}: 상한 {cap} -> 실제 {counts.get(rel, 0)}"
             for rel, cap in sorted(_IMPORTANT_BUDGET.items())
             if counts.get(rel, 0) < cap]
    assert not stale, (
        "!important 를 걷어냈으면 _IMPORTANT_BUDGET 도 그만큼 내릴 것 "
        "(0 이 되면 항목째 지운다): " + " | ".join(stale))


def test_important_budget_entries_point_at_real_files():
    """상한 표가 실제 파일을 가리킨다."""
    known = {str(p.relative_to(CSS_DIR)) for p in _target_css()}
    missing = sorted(set(_IMPORTANT_BUDGET) - known)
    assert not missing, (
        "_IMPORTANT_BUDGET 이 이 가드의 대상이 아닌 파일을 가리킨다: "
        + ", ".join(missing))


# ---------------------------------------------------------- 레거시 별칭 소비

# ## 별칭은 왜 문제였나
#
# `--text-color-primary: var(--aot-color-text-primary)` 처럼 정본을 가리키기만
# 하면 값은 따라온다. **문제는 `/custom.css` 다** — 사용자 색을 발행할 때 별칭과
# 정본을 둘 다 쓰는데, 다크 사용자에게는 정본만 걸러낸다(`dark_overridden`,
# custom-dark.css 값을 지키려고). 그러면 **별칭에는 라이트 값이 남는다.**
# 다크에서 흰 카드가 뜨거나 어두운 배경에 어두운 글자가 앉는 원인이다.
#
# 2026-09-07 에 소비처 407곳을 정본 이름으로 옮겼다. 아래 이름들은 **소비처가
# 0 이어야 한다** — 정의는 하위호환으로 남기지만 우리 코드는 안 쓴다.
#
# ## ⚠ 여기 없는 이름 여덟 개
#
# `--gray` `--gray-hard` `--light` `--primary` `--secondary` `--success`
# `--warning` `--danger` 는 **이름만 별칭이고 값이 다르다.** `aot.css` 가
# 별칭으로 선언하지만 그 파일은 화면에 안 실리고, 대신 테마 파일이 같은 이름을
# 다른 리터럴로 정의한다(`--gray` #eeebeb vs 정본 #5E6B64 등). 옮기면 색이
# 바뀌므로 정리가 아니라 **디자인 결정**이다. 손대지 않았다.
_MIGRATED_ALIASES = (
    "--text-color-primary", "--text-color-secondary", "--text-color-tertiary",
    "--text-primary", "--text-secondary", "--text-tertiary",
    "--brand-primary", "--brand-secondary", "--brand-accent",
    "--border-neutral", "--border-form-control", "--border-form-focus",
    "--gray-dark", "--dark", "--info",
    "--bd-primary", "--bd-secondary", "--bd-tertiary", "--bd-border",
    "--bd-btn-border", "--bd-btn-primary", "--bd-btn-secondary",
    "--bd-btn-tertiary",
    "--bg-active", "--bg-inactive", "--bg-pause", "--bg-hold", "--bg-on",
    "--bg-off", "--bg-upgrade", "--bg-llm", "--bg-mcp",
    "--bg-btn-on", "--bg-btn-off", "--bg-btn-active", "--bg-btn-inactive",
    "--bg-btn-pause", "--bg-btn-hold", "--bg-btn-upgrade",
    "--font-family-sans-serif", "--font-family-monospace",
)
_VAR_USE = re.compile(r"var\(\s*(--[a-z][a-z0-9-]*)")
_ALIAS_SCAN_SKIP = {"node_modules", "__pycache__", "dist", "vendor",
                    _GENERATED_TEMPLATE_DIR}
_ALIAS_SCAN_EXT = (".css", ".html", ".py", ".js")


def _alias_consumers():
    import os
    root = CSS_DIR.parent.parent.parent          # .../aot
    names = set(_MIGRATED_ALIASES)
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _ALIAS_SCAN_SKIP]
        for f in sorted(files):
            if not f.endswith(_ALIAS_SCAN_EXT):
                continue
            path = os.path.join(base, f)
            with open(path, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    for m in _VAR_USE.finditer(line):
                        if m.group(1) in names:
                            out.append(f"{os.path.relpath(path, root)}:{i} {m.group(1)}")
    return out


def test_legacy_aliases_have_no_consumers():
    """이관한 별칭 이름을 다시 쓰지 않는다.

    라이트에서는 값이 같아 보이지만 **다크에서 갈린다** — `/custom.css` 가
    별칭에는 라이트 값을 남기고, 정본은 custom-dark.css 의 다크 값을 지키기
    때문이다. 새 코드가 별칭을 쓰면 그 자리만 다크에서 어긋난다.
    """
    bad = _alias_consumers()
    assert not bad, (
        "레거시 별칭을 다시 쓰고 있다. 정본 --aot-* 이름을 쓸 것 "
        "(다크에서 값이 갈린다): " + " | ".join(bad[:8]))


# ------------------------------------------------- var() 폴백이 정본과 다른 것

# ## 왜 보는가
#
# `var(--aot-color-info, #007bff)` 처럼 **폴백에 다른 색을 적어 둔 자리**가
# 있다. 폴백은 토큰이 정의되지 않았을 때만 쓰이고 `aot-theme-variables.css` 는
# 모든 페이지에 실리므로, 지금 화면에 그 색이 나오지는 **않는다**. 그래서
# 이것은 렌더 버그가 아니라 **문서 버그**다 — 코드를 읽는 사람(그리고 색을
# 훑는 도구)에게 "이 자리의 색은 부트스트랩 파랑" 이라고 잘못 말한다.
#
# 실제로 그렇게 새어 나갔다. 2026-09-07 에 디자인 시스템을 claude.ai/design 에
# 올렸더니 저쪽 에이전트가 `#007bff` 를 팔레트 밖의 색으로 보고했다. 값이
# 안 쓰이는 것과 안 읽히는 것은 다르다.
#
# 그리고 언젠가는 렌더 버그가 된다. 토큰 이름을 바꾸거나(방금 `--modal-focus-ring`
# → `--aot-focus-ring` 이 그랬다) 토큰 파일이 안 실리는 조각을 만들면 그 순간
# 폴백이 켜지고, 그때 나오는 색은 팔레트 밖이다.
#
# ## 규칙
#
# 폴백 자리에 리터럴 색을 적을 거라면 **그 토큰의 정본 값을 그대로** 적는다.
# `#fff` 처럼 줄여 써도 된다(3자리는 펴서 비교한다). 다크 값이 따로 있는
# 토큰이라도 폴백은 정본(라이트) 값이다 — 다크는 custom-dark.css 가 덮는다.
#
# ## 상한
#
# 311곳이 남아 있다. 대부분 부트스트랩 기본색(`#6c757d` `#212529` `#dc3545`)
# 이거나 정본이 정해지기 전의 손색이다. 한 번에 고칠 값어치는 없고, **늘지만
# 않으면 된다.** 토큰별로 세고 내려가기만 한다.
_FALLBACK = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*,\s*(#[0-9A-Fa-f]{3,8})\s*\)")
_HEX_DEF = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*(#[0-9A-Fa-f]{3,8})\s*;")

_FALLBACK_BUDGET = {
    "--aot-color-text-secondary": 110,
    "--aot-color-text-primary": 94,
    "--aot-border-neutral": 22,
    "--aot-surface-body": 16,
    "--aot-color-danger": 11,
    "--aot-border-light": 8,
    "--aot-color-warning": 8,
    "--aot-btn-border-primary": 4,
    "--aot-color-success": 4,
    "--color-zone-mode": 4,
    "--text-medium-gray": 4,
    "--aot-surface-card": 3,
    "--aot-surface-input": 3,
    "--aot-tint-info-bg": 3,
    "--aot-tint-info-fg": 3,
    "--aot-color-dark": 2,
    "--aot-bg-pause": 1,
    "--aot-border-form": 1,
    "--aot-btn-bg-hold": 1,
    "--aot-btn-bg-inactive": 1,
    "--aot-btn-bg-pause": 1,
    "--aot-color-brand-primary": 1,
    "--aot-color-text-tertiary": 1,
    "--aot-tint-danger-bg": 1,
    "--aot-tint-success-bg": 1,
    "--aot-tint-success-fg": 1,
    "--aot-tint-warning-bg": 1,
    "--aot-tint-warning-fg": 1,
}


def _norm_hex(value):
    """`#fff` 와 `#ffffff` 는 같은 색이다. 3자리를 펴서 비교한다."""
    h = value.lower().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def _canonical_hex():
    """`aot-theme-variables.css` 가 리터럴 색으로 정의한 토큰들.

    같은 이름이 여러 번 나오면 **처음 것**이 정본이다 — 뒤의 것은 같은 파일
    안의 조건부/주석 예시일 수 있고, 정의 순서상 앞이 기준이다.
    """
    text = (CSS_DIR / "aot-theme-variables.css").read_text(encoding="utf-8")
    out = {}
    for m in _HEX_DEF.finditer(text):
        out.setdefault(m.group(1), _norm_hex(m.group(2)))
    return out


def _fallback_mismatches():
    import os
    root = CSS_DIR.parent.parent.parent          # .../aot
    canon = _canonical_hex()
    # 자기 자신은 뺀다. 위 주석이 `var(--aot-color-info, #007bff)` 를 **예시로**
    # 적고 있어서, 빼지 않으면 이 가드가 자기 설명문을 위반으로 잡는다.
    # (`check_dead_css.py` 도 같은 데 걸렸다 — 코퍼스에 자기를 넣지 말 것.)
    myself = os.path.abspath(__file__)
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _ALIAS_SCAN_SKIP]
        for f in sorted(files):
            if not f.endswith(_ALIAS_SCAN_EXT):
                continue
            path = os.path.join(base, f)
            if os.path.abspath(path) == myself:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    for m in _FALLBACK.finditer(line):
                        token = m.group(1)
                        if token not in canon:
                            continue
                        if canon[token] == _norm_hex(m.group(2)):
                            continue
                        rel = os.path.relpath(path, root)
                        out.append((token, f"{rel}:{i} {m.group(2)} != {canon[token]}"))
    return out


def _current_fallback_counts():
    counts = {}
    for token, _ in _fallback_mismatches():
        counts[token] = counts.get(token, 0) + 1
    return counts


def test_var_fallback_matches_the_token():
    """`var()` 폴백에 토큰의 정본과 다른 색을 새로 적지 않는다."""
    counts = _current_fallback_counts()
    where = {}
    for token, loc in _fallback_mismatches():
        where.setdefault(token, []).append(loc)
    grew = [f"{t} ({_FALLBACK_BUDGET.get(t, 0)} -> {n}) 예: {where[t][0]}"
            for t, n in sorted(counts.items())
            if n > _FALLBACK_BUDGET.get(t, 0)]
    assert not grew, (
        "var() 폴백이 토큰의 정본 값과 다르다. 폴백에는 그 토큰의 정본을 그대로 "
        "적을 것 (부트스트랩 기본색을 적지 말 것): " + " | ".join(grew[:6]))


def test_fallback_budget_is_not_stale():
    """폴백 상한도 내려가기만 한다."""
    counts = _current_fallback_counts()
    stale = [f"{t}: 상한 {cap} -> 실제 {counts.get(t, 0)}"
             for t, cap in sorted(_FALLBACK_BUDGET.items())
             if counts.get(t, 0) < cap]
    assert not stale, (
        "폴백을 정본으로 맞췄으면 _FALLBACK_BUDGET 도 그만큼 내릴 것 "
        "(0 이 되면 항목째 지운다): " + " | ".join(stale))


def test_fallback_budget_entries_are_real_tokens():
    """상한 표가 실제로 정의된 토큰을 가리킨다."""
    canon = _canonical_hex()
    missing = sorted(set(_FALLBACK_BUDGET) - set(canon))
    assert not missing, (
        "_FALLBACK_BUDGET 이 aot-theme-variables.css 에 없는 토큰을 가리킨다: "
        + ", ".join(missing))


# ------------------------------------------------------ 테두리는 정본 하나로

# 모달 CSS 가 테두리를 부트스트랩 변수 `--gray`(테마가 `#eeebeb` 로 덮은 값)로
# 그리고 있었다 — 나머지 147곳이 쓰는 `--aot-border-neutral` 과 같은 용도에 두
# 색이었다. **다크에서는 결함이었다**: `--gray` 는 다크 오버라이드가 없어
# `#eeebeb` 로 남고, 어두운 모달(`#1e1e1e`) 위에 거의 흰 선이 그어졌다.
# `--aot-border-neutral` 은 다크에서 `#444444` 로 뒤집힌다.
#
# 2026-09-07 에 테두리 14곳을 정본으로 옮겼다. 남은 `var(--gray)` 두 곳은
# 테두리가 아니다(드롭다운 선택 배경 · 채널 구분자 글자색) — 그 둘은 다크에서
# 어떤 값이어야 하는지가 정리가 아니라 디자인 결정이라 그대로 두었다.
_GRAY_BORDER = re.compile(
    r"\bborder(?:-(?:top|right|bottom|left|color))?\s*:[^;{}]*var\(\s*--gray\s*\)")


def test_borders_do_not_use_the_bootstrap_gray():
    """테두리를 `--gray` 로 그리지 않는다. 정본은 `--aot-border-neutral` 이다."""
    import os
    root = CSS_DIR.parent.parent.parent          # .../aot
    myself = os.path.abspath(__file__)
    bad = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _ALIAS_SCAN_SKIP]
        for f in sorted(files):
            if not f.endswith(_ALIAS_SCAN_EXT):
                continue
            path = os.path.join(base, f)
            if os.path.abspath(path) == myself:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if _GRAY_BORDER.search(line):
                        bad.append(f"{os.path.relpath(path, root)}:{i}")
    assert not bad, (
        "테두리에 --gray 를 쓰고 있다. 정본 --aot-border-neutral 을 쓸 것 "
        "(--gray 는 다크 오버라이드가 없어 어두운 바탕에 흰 선이 된다): "
        + " | ".join(bad[:8]))


# ------------------------------------------ 대시보드 탭바 아래 여백 (회귀 가드)

# `.aot-sticky-tabs` 는 다섯 화면이 함께 쓴다(대시보드·입력·출력·함수·프로그램).
# 그중 **대시보드만** 여백이 0 이어야 한다 — 위젯 격자가 `padding: 1em` 을 이미
# 갖고 있어서, 공용 50px 이 얹히면 탭바와 첫 위젯 사이가 14px → 64px 이 된다.
#
# 예전에는 양쪽 다 `!important` 였고, `!important` 끼리는 특이도가 가르므로
# ID 인 `#dash-sticky` 가 이겼다. 2026-09 에 "아무 일도 안 하는 `!important`"
# 를 걷어내면서 `#dash-sticky` 쪽만 떼자 공용 규칙이 이겨 대시보드가 벌어졌다.
# **한쪽만 떼면 승자가 뒤집히는 짝이었다.**
#
# 지금은 둘 다 평범한 선언이고 특이도만으로 갈린다. 공용 쪽에 `!important` 가
# 다시 붙으면 그 순간 대시보드가 도로 벌어지므로, 그것을 막는다.
_STICKY_TABS_RULE = re.compile(r"\.aot-sticky-tabs\s*\{([^}]*)\}")


def test_shared_sticky_tabbar_margin_has_no_important():
    """공용 탭바 여백에 `!important` 를 붙이지 않는다 — 대시보드가 벌어진다."""
    text = _blank_comments(
        (CSS_DIR / "bootstrap-4-themes" / "aot.css").read_text(encoding="utf-8"))
    m = _STICKY_TABS_RULE.search(text)
    assert m, ".aot-sticky-tabs 규칙을 찾지 못했다"
    decls = [d.strip() for d in m.group(1).split(";") if "margin" in d]
    assert decls, ".aot-sticky-tabs 에 margin 선언이 없다"
    bad = [d for d in decls if _IMPORTANT.search(d)]
    assert not bad, (
        "공용 .aot-sticky-tabs 의 여백에 !important 가 붙었다. 대시보드의 "
        "#dash-sticky(margin 0)가 평범한 선언이라 이 순간 지고, 탭바와 첫 "
        "위젯 사이가 14px -> 64px 로 벌어진다: " + " | ".join(bad))


def test_dashboard_sticky_keeps_zero_margin():
    """대시보드 탭바는 자기 여백을 0 으로 유지한다."""
    text = _blank_comments(
        (CSS_DIR / "dashboard.css").read_text(encoding="utf-8"))
    bodies = [m.group(1) for m in
              re.finditer(r"#dash-sticky\s*\{([^}]*)\}", text)]
    assert bodies, "#dash-sticky 규칙을 찾지 못했다"
    margins = [d.strip() for b in bodies for d in b.split(";")
               if d.strip().startswith("margin")]
    assert margins, "#dash-sticky 에 margin 선언이 없다 — 공용 50px 이 그대로 얹힌다"
    for d in margins:
        assert re.search(r":\s*0(px)?\s*(!important)?$", d), (
            f"#dash-sticky 의 여백이 0 이 아니다: {d}")
