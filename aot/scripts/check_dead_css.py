#!/usr/bin/env python3
# coding=utf-8
"""마크업 어디에도 나타나지 않는 CSS 규칙을 찾는다 (기본 읽기 전용).

## 왜 있는가

CSS 는 지워지지 않고 쌓인다. 화면이 바뀌어도 규칙은 남고, 남은 규칙이 다음
사람에게는 "쓰이는 것" 으로 보인다. 2026-09-07 감사에서 규칙 2,694개 중
**181개**가 어느 마크업에도 안 걸리는 것으로 확인됐다(1,342줄).

**브라우저로는 죽음을 증명할 수 없다.** 화면을 아무리 돌아도 "이 화면에는
없다" 까지만 말할 수 있다 — `:hover` 상태, JS 가 붙이는 클래스, 안 들른 화면,
동적으로 만들어지는 요소가 전부 빠진다. 없다는 것을 보이려면 **저장소 전체**를
봐야 한다. 그래서 반대로 센다:

  ① CSS 선택자에서 클래스·id 이름을 모은다
  ② 마크업을 만들 수 있는 **모든 파일**(템플릿·파이썬·JS 소스·번들·벤더)에서
     식별자를 뽑아 낱말 집합을 만든다
  ③ 낱말 집합에 없는 이름만 후보로 남긴다
  ④ 후보에서 **조립되는 이름**과 **라이브러리가 붙이는 이름**을 뺀다

## 쓰는 법

    python3 aot/scripts/check_dead_css.py            # 보고만 한다
    python3 aot/scripts/check_dead_css.py --verbose  # 규칙까지 전부
    python3 aot/scripts/check_dead_css.py --apply    # 실제로 지운다

`--apply` 뒤에는 **반드시 전체 테스트를 돌린다.** 계약 테스트가 "안 쓰이지만
있어야 하는 것" 을 잡아 준다 — 실제로 `.aot-notice-box-info` 가 그렇게 살아
돌아왔다(성공·위험·경고·정보 네 톤 한 벌 계약).

## 이 검사가 틀릴 수 있는 자리

  · 저장소 밖에서 오는 마크업(사용자가 붙여 넣은 HTML 등)
  · 이 파일의 `VENDOR_*` 목록에 없는 새 라이브러리
  · 앞자락이 너무 짧은 조립(`'aot-' + type`) — `GENERIC_PREFIX` 참고

그래서 **결과는 삭제 목록이 아니라 조사 목록**이다. 종료 코드 1 은 "봐야 할
것이 있다" 지 "실패" 가 아니다.
"""
import os
import re
import sys
import collections

# aot/scripts/check_dead_css.py -> 저장소 뿌리는 세 단계 위
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSSDIR = os.path.join(ROOT, "aot", "aot_flask", "static", "css")

# 말뭉치에 넣을 확장자 — 마크업을 **만들 수 있는** 것 전부.
# 번들(dist/)과 벤더도 넣는다: 거기 이름이 있으면 런타임에 붙는다는 뜻이다.
CORPUS_EXT = (".html", ".htm", ".py", ".js", ".mjs", ".jsx", ".ts", ".json",
              ".jinja", ".jinja2", ".svg", ".xml", ".md", ".txt")
SKIP_DIR = {".git", "node_modules", "__pycache__", ".local", ".design-sync"}

# ⚠ 말뭉치에서 **자기 자신을 빼야 한다.** 이 파일의 설명이 클래스 이름을
# 인용하는 순간 그 이름이 "마크업에 있다" 로 잡혀 검사가 스스로를 속인다
# (`.aot-notice-box-info` 를 이 설명에 적었더니 후보에서 사라졌다).
# `.local/`(감사 보고서)과 `.design-sync/`(디자인 시스템 규약 문서)도 같은
# 이유로 뺀다 — 둘 다 클래스 이름을 예시로 잔뜩 인용하므로, 두면 실제로는
# 아무 데도 안 쓰이는 이름이 "마크업에 있다" 로 잡힌다(2026-09-07 실측 확인).
SKIP_FILES = {os.path.abspath(__file__)}

# 우리가 쓴 CSS 만 본다 — 받아 온 것은 우리가 지울 것이 아니다
CSS_SKIP_DIR = {"vendor", "datatables_2_2_2", "node_modules"}
THEME_DIR = "bootstrap-4-themes"
OUR_THEME = "aot.css"
VENDOR_CSS = {"daterangepicker.css", "gridstack.css"}

# 라이브러리가 런타임에 붙이는 이름. 그 라이브러리 소스가 CDN 이라 저장소에
# 없으면 "마크업에 없음" 으로 잡히지만 살아 있다.
VENDOR_PREFIX = ("maplibregl-", "leaflet-", "mapbox", "gs-", "grid-stack",
                 "ui-resizable", "bootstrap-select", "gridstack", "highcharts-",
                 "fa-", "dt-")
VENDOR_EXACT = {"no-gutters", "col-3", "container-sm", "container-md",
                "container-lg", "container-xl", "form-check-inline",
                "input-group-btn", "gap-4", "gap-5", "icon-fw", "btn-info",
                "panel-body", "text-gradient",
                "dropdown-upgrade", "dropdown-item-upgrade"}

# 너무 짧아서 거의 모든 이름을 "조립됨" 으로 만들어 버리는 앞자락.
# `aot-` 는 지도 컨트롤 두 곳(`'aot-' + type`)에서만 쓴다 — 그 둘 때문에
# `aot-*` 전체를 못 지우게 되므로 뺀다.
GENERIC_PREFIX = {"aot-"}

# 마크업에는 없지만 **계약으로 있어야 하는** 이름.
#
# 안 쓰인다는 것과 있어선 안 된다는 것은 다르다. 그 경계를 정하는 것은
# 계약(테스트)이다. 여기 적는 이름은 반드시 그 계약을 가리키는 주석을 단다 —
# 근거 없이 늘어나면 이 검사는 아무것도 못 잡는 목록이 된다.
CONTRACT_KEEP = {
    # 성공·위험·경고·정보 네 톤 한 벌. 하나만 빠지면 계약이 깨진다 —
    # aot/tests/test_notice_box_theme_integration.py
    "aot-notice-box-info",
}

TOKEN = re.compile(r"[.#](-?[A-Za-z_][A-Za-z0-9_-]*)")
WORD = re.compile(rb"[A-Za-z_][A-Za-z0-9_-]*")
COMMENT = re.compile(r"/\*.*?\*/", re.S)
BANNER = re.compile(r"[-=*─═]{6,}")

# 코드가 클래스 이름을 이어 붙이는 자리.
#
# ⚠ 앞자락은 따옴표 안 **통째**가 아니라 **문자열 끝에 붙은 조각**인 경우가
#   훨씬 많다. 처음에 통째만 보다가 `lv-`·`zone-c`·`aot-hz--`·`aot-adv-lvl-`
#   을 전부 놓쳤다:
#
#       '<div class="zone-bay-cell zone-c' + (zi % 6) + '">'
#                                   ^^^^^^ 이것
_STEM = rb"([A-Za-z][A-Za-z0-9_-]{2,})"
CONCAT_PATTERNS = [
    _STEM + rb"['\"]\s*\+",      # ... 'zone-c' +
    _STEM + rb"\$\{",            # `task-status-${
    _STEM + rb"\{\{",            # class="lv-{{ level }}"
    _STEM + rb"\{",              # f"lv-{level}"
    _STEM + rb"%[sd(]",          # "lv-%s"
    rb"\+\s*['\"]\s*" + _STEM,   # + 'aot-lvl-'
]


def blank_comments(src):
    """주석을 공백으로 덮되 **줄 수와 길이를 보존한다.**

    길이가 바뀌면 뒤에서 계산한 위치가 통째로 어긋난다.
    """
    return COMMENT.sub(
        lambda m: "".join(c if c == "\n" else " " for c in m.group(0)), src)


def our_css():
    out = []
    for base, dirs, files in os.walk(CSSDIR):
        dirs[:] = [d for d in dirs if d not in CSS_SKIP_DIR]
        for f in sorted(files):
            if not f.endswith(".css") or f.endswith(".min.css"):
                continue
            if f in VENDOR_CSS:
                continue
            if os.path.basename(base) == THEME_DIR and f != OUR_THEME:
                continue
            out.append(os.path.join(base, f))
    return sorted(out)


def corpus():
    """(마크업에 등장하는 낱말, 이름 조립 앞자락, 읽은 파일 수)"""
    words, chunks, n = set(), [], 0
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR]
        for f in files:
            if not f.endswith(CORPUS_EXT):
                continue
            full = os.path.join(base, f)
            if os.path.abspath(full) in SKIP_FILES:
                continue
            try:
                data = open(full, "rb").read()
            except OSError:
                continue
            n += 1
            chunks.append(data)
            for m in WORD.finditer(data):
                words.add(m.group(0).decode("ascii", "ignore"))
    text = b"\n".join(chunks)
    pref = set()
    for pat in CONCAT_PATTERNS:
        for m in re.finditer(pat, text):
            p = m.group(1).decode("ascii", "ignore")
            if p not in GENERIC_PREFIX:
                pref.add(p)
    return words, pref, n


def split_selectors(prelude):
    """최상위 쉼표로만 자른다 — `:not(a, b)` 안의 쉼표는 두고."""
    out, depth, buf = [], 0, []
    for ch in prelude:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


def scan(flat):
    """(프리루드 시작, 여는 중괄호, 닫는 중괄호, 프리루드) — 모든 깊이."""
    out, stack, start = [], [], 0
    for i, c in enumerate(flat):
        if c == "{":
            stack.append((start, i))
            start = i + 1
        elif c == "}":
            if stack:
                s, o = stack.pop()
                out.append((s, o, i, flat[s:o].strip()))
            start = i + 1
        elif c == ";" and not stack:
            start = i + 1
    return out


def attached_comment_start(src, begin):
    """규칙 바로 앞에 붙어 있던 설명 주석의 시작 위치.

    규칙만 지우면 아무것도 안 가리키는 문장이 남는다(`/* 24px */` 만 넉 줄).
    바로 앞에 공백만 두고 붙어 있는 주석은 그 규칙의 것으로 보고 같이 지운다.

    단 `/* ----- 구역 이름 ----- */` 같은 **구획 배너는 남긴다** — 뒤따르는
    규칙 여럿을 묶는 제목이라 하나 지웠다고 없앨 것이 아니다.
    """
    i = begin
    while i > 0 and src[i - 1] in " \t\n\r":
        i -= 1
    if i < 2 or src[i - 2:i] != "*/":
        return begin
    j = src.rfind("/*", 0, i)
    if j < 0:
        return begin
    body = src[j:i]
    if BANNER.search(body) or body.count("\n") >= 4:
        return begin
    k = src.rfind("\n", 0, j) + 1
    if src[k:j].strip():
        return begin                       # 같은 줄에 코드가 있으면 둔다
    return k


def make_unreachable(words, pref):
    def unreachable(tok):
        return (tok not in words
                and tok not in CONTRACT_KEEP
                and tok not in VENDOR_EXACT
                and not tok.startswith(VENDOR_PREFIX)
                and not any(tok.startswith(p) and p != tok for p in pref))
    return unreachable


def plan_for_source(src, unreachable):
    """한 파일분 (편집 목록, 통째 삭제 목록, 선택자만 빼는 목록).

    편집 목록은 `(시작, 끝, 대신 넣을 글자)` 이고 **겹치지 않게 합쳐져 있다.**
    """
    flat = blank_comments(src)
    edits, whole, partial = [], [], []
    for s, o, c, prelude in scan(flat):
        if not prelude or prelude.startswith("@"):
            continue
        parts = split_selectors(prelude)
        dead = [x for x in parts
                if any(unreachable(t) for t in TOKEN.findall(x))]
        if not dead:
            continue
        # 프리루드 시작은 여는 중괄호 **바로 뒤**(= 줄바꿈)일 수 있다.
        # 첫 글자로 옮기지 않으면 앞 규칙과 한 줄로 붙는다(`}body {`).
        b = s
        while b < o and flat[b] in " \t\n\r":
            b += 1
        if len(dead) == len(parts):
            begin = attached_comment_start(src, src.rfind("\n", 0, b) + 1)
            end = c + 1
            while end < len(src) and src[end] in " \t":
                end += 1
            if end < len(src) and src[end] == "\n":
                end += 1
            edits.append((begin, end, ""))
            whole.append((flat.count("\n", 0, b) + 1, prelude))
        else:
            keep = [x for x in parts if x not in dead]
            sep = ",\n" if "\n" in prelude else ", "
            edits.append((b, o, sep.join(keep) + " "))
            partial.append((flat.count("\n", 0, b) + 1, prelude, dead))
    return merge(edits), whole, partial


def apply_edits(src, edits):
    for a, b, rep in sorted(edits, reverse=True):
        src = src[:a] + rep + src[b:]
    return re.sub(r"\n{3,}", "\n\n", src)


def plan(words, pref):
    """파일별 (편집 목록, 통째 삭제 목록, 선택자만 빼는 목록)."""
    unreachable = make_unreachable(words, pref)
    out = {}
    for path in our_css():
        edits, whole, partial = plan_for_source(
            open(path, encoding="utf-8").read(), unreachable)
        if edits:
            out[os.path.relpath(path, CSSDIR)] = (edits, whole, partial)
    return out


def merge(edits):
    """겹치는 삭제 범위를 합친다 — 겹친 채로 잘라내면 글자가 깎인다."""
    edits.sort()
    out = []
    for a, b, rep in edits:
        if out and rep == "" and out[-1][2] == "" and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b), "")
        else:
            out.append((a, b, rep))
    return out


def main(argv):
    verbose = "--verbose" in argv or "-v" in argv
    apply_changes = "--apply" in argv
    words, pref, nfiles = corpus()
    print(f"말뭉치 {nfiles:,}개 파일 · 식별자 {len(words):,}종 · "
          f"이름 조립 앞자락 {len(pref):,}종")
    todo = plan(words, pref)
    if not todo:
        print("OK: 마크업에 안 나타나는 규칙 없음.")
        return 0

    nw = sum(len(w) for _, w, _ in todo.values())
    np_ = sum(len(p) for _, _, p in todo.values())
    print(f"\n마크업 어디에도 안 나타나는 규칙 {nw}개 · "
          f"쉼표 목록에서 뺄 선택자 {np_}건\n")
    for rel in sorted(todo, key=lambda r: -len(todo[r][1])):
        edits, whole, partial = todo[rel]
        print(f"  통째 {len(whole):3d}  일부 {len(partial):2d}   {rel}")
        if verbose:
            for line, sel in whole:
                print(f"        {line:5d}  {sel[:88]}")
            for line, sel, dead in partial:
                print(f"        {line:5d}  {sel[:60]}  ← 뺌 {dead}")

    if not apply_changes:
        print("\n지우려면 --apply. 지운 뒤에는 **전체 테스트를 반드시 돌린다** — "
              "안 쓰이지만 계약으로 있어야 하는 규칙을 테스트가 잡아 준다.")
        return 1

    for rel, (edits, whole, partial) in todo.items():
        path = os.path.join(CSSDIR, rel)
        src = open(path, encoding="utf-8").read()
        open(path, "w", encoding="utf-8").write(apply_edits(src, edits))
    print(f"\n{len(todo)}개 파일에서 지웠다. 이제 전체 테스트를 돌릴 것.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
