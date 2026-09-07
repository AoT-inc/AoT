# coding=utf-8
"""죽은 CSS 검사기(`aot/scripts/check_dead_css.py`)가 스스로 틀리지 않게 한다.

이 검사들은 전부 **실제로 밟은 지뢰**에서 나왔다. 2026-09-07 정리 때 세 번
파일을 깨뜨렸고, 그때마다 원인은 규칙 판정이 아니라 **잘라내는 자리**였다:

  · 쉼표 목록을 통째로 지워 살아 있는 선택자까지 죽였다
  · 프리루드 시작이 여는 중괄호 바로 뒤라 앞 규칙과 한 줄로 붙었다(`}body {`)
  · 이웃한 두 규칙의 삭제 범위가 겹쳐 글자가 깎였다

도구가 다음에 쓰일 때 같은 자리에서 또 깨지지 않게 못을 박는다.
"""
import re

from aot.scripts.check_dead_css import (
    CONCAT_PATTERNS,
    apply_edits,
    attached_comment_start,
    blank_comments,
    make_unreachable,
    plan_for_source,
    split_selectors,
)

# 시험용 판정: `dead` 로 시작하는 이름만 죽은 것으로 본다
DEAD = (lambda t: t.startswith("dead"))


def run(src):
    edits, whole, partial = plan_for_source(src, DEAD)
    return apply_edits(src, edits), whole, partial


def test_comma_lists_keep_the_living_selector():
    """`.살아있음, .죽음` 에서 죽은 쪽만 뺀다 — 통째로 지우면 둘 다 죽는다."""
    out, whole, partial = run(".alive, .dead-x {\n  color: red;\n}\n")
    assert not whole and len(partial) == 1
    assert ".alive" in out and "dead-x" not in out
    assert "color: red" in out


def test_deleting_a_rule_does_not_glue_it_to_the_previous_one():
    """프리루드 시작은 여는 중괄호 바로 뒤일 수 있다 — `}body {` 가 됐던 자리."""
    out, _, _ = run(".keep {\n  color: red;\n}\n\n.dead-x {\n  color: blue;\n}\n")
    for line in out.split("\n"):
        assert not re.search(r"\}\S", line), line
    assert "color: blue" not in out
    assert "color: red" in out


def test_neighbouring_dead_rules_do_not_eat_each_other():
    """이웃한 삭제 범위가 겹쳐도 글자가 깎이지 않는다."""
    src = (".dead-a {\n  a: 1;\n}\n.dead-b {\n  b: 2;\n}\n.keep-me {\n  c: 3;\n}\n")
    out, whole, _ = run(src)
    assert len(whole) == 2
    assert out.strip() == ".keep-me {\n  c: 3;\n}"


def test_a_comment_inside_a_declaration_block_is_left_alone():
    """선언 블록 안 주석은 지은이의 말이다 — 검사기가 건드리지 않는다."""
    src = ".keep {\n  color: red;\n  /* 밑줄 제거 유지 */\n}\n.dead-x { a: 1; }\n"
    out, _, _ = run(src)
    assert "밑줄 제거 유지" in out
    assert "dead-x" not in out


def test_the_short_comment_above_a_dead_rule_goes_with_it():
    """규칙만 지우면 아무것도 안 가리키는 설명이 남는다."""
    out, _, _ = run("/* 24px */\n.dead-x {\n  a: 1;\n}\n")
    assert "24px" not in out


def test_a_section_banner_survives():
    """구획 배너는 뒤따르는 규칙 여럿을 묶는 제목이라 하나 지웠다고 없애지 않는다."""
    src = ("/* ------------------------------------------------------------\n"
           "   3. 공용\n"
           "------------------------------------------------------------ */\n"
           ".dead-x {\n  a: 1;\n}\n\n.keep {\n  b: 2;\n}\n")
    out, _, _ = run(src)
    assert "3. 공용" in out
    assert "dead-x" not in out


def test_attached_comment_start_leaves_a_banner_where_it_is():
    src = "/* ====== 구획 ====== */\n.x {}\n"
    begin = src.index(".x")
    assert attached_comment_start(src, begin) == begin


def test_commas_inside_not_are_not_split():
    """`:not(a, b)` 안의 쉼표는 선택자 구분이 아니다."""
    assert split_selectors(".a:not(.x, .y), .b") == [".a:not(.x, .y)", ".b"]


def test_concat_prefix_is_found_at_the_end_of_a_longer_string():
    """앞자락은 따옴표 안 통째가 아니라 **문자열 끝에 붙은 조각**인 일이 많다.

    처음에 통째만 보다가 `lv-`·`zone-c`·`aot-hz--` 를 전부 놓쳤다.
    """
    samples = [
        (b"""html += '<div class="zone-bay-cell zone-c' + (zi % 6) + '">';""", "zone-c"),
        (b"""var cls = level ? (' lv-' + level.toLowerCase()) : '';""", "lv-"),
        (b"""className: `task-status-${task.status}`,""", "task-status-"),
        (b"""'<span class="aot-adv-dot aot-adv-lvl-' + lvl.cls + '">'""", "aot-adv-lvl-"),
    ]
    for text, want in samples:
        found = set()
        for pat in CONCAT_PATTERNS:
            for m in re.finditer(pat, text):
                found.add(m.group(1).decode())
        assert want in found, (want, sorted(found))


def test_blank_comments_keeps_length_and_lines():
    """길이나 줄이 바뀌면 뒤에서 계산한 위치가 통째로 어긋난다."""
    src = "a{}\n/* 여러\n   줄 */\nb{}\n"
    out = blank_comments(src)
    assert len(out) == len(src)
    assert out.count("\n") == src.count("\n")
    assert "여러" not in out


def test_contract_names_are_never_proposed_for_deletion():
    """마크업에 없어도 계약으로 있어야 하는 이름은 후보가 아니다."""
    unreachable = make_unreachable(words=set(), pref=set())
    assert unreachable("aot-zzz-nobody-uses-this")
    assert not unreachable("aot-notice-box-info")   # 네 톤 한 벌 계약
    assert not unreachable("maplibregl-ctrl-zoom")  # 라이브러리가 붙인다


def test_names_the_code_builds_are_not_candidates():
    unreachable = make_unreachable(words=set(), pref={"lv-"})
    assert not unreachable("lv-critical")
    assert unreachable("lx-critical")
