# coding=utf-8
"""aot/scripts/manual_sync.py — 코드 주석(@manual)으로 매뉴얼 절을 잇는 장치.

이 장치가 틀리면 조용히 두 가지로 샌다: 코드가 바뀌었는데 '최신' 으로 남거나
(문서 밀림이 다시 보이지 않게 된다), 주석·공백만 바뀌어도 '오래됨' 이 떠서
매 커밋 claude 가 헛돈다. 둘 다 여기서 막는다.
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import manual_sync as ms  # noqa: E402


class FakeSource(object):
    def __init__(self, files):
        self.files = dict(files)

    def annotated_files(self):
        return sorted(p for p, t in self.files.items()
                      if p.startswith("aot/") and re.search(ms.GREP_PATTERN, t))

    def read(self, path):
        return self.files.get(path)


PAGE_EN = """# Notice Board

Intro.

## Poll { #poll }

Poll text.

```bash
## not a heading
```

### Sub detail

More.

## List View { #list }

- item
"""

PAGE_KO = PAGE_EN.replace("## Poll { #poll }", "## 투표 { #poll }").replace(
    "## List View { #list }", "## 목록 보기 { #list }")

PY = '''import os


def helper():
    return 1


# @manual Notices#poll
@decorator
def vote(x):
    """Vote."""
    return x + 1


def listing():
    """List.

    @manual Notices.md#list, Notices#poll
    """
    return [1]
'''


def _ids(units):
    return {u.id: sorted(u.targets) for u in units}


# ── 주석 읽기 ──────────────────────────────────────────────────────────────

def test_python_comment_above_decorated_def_and_docstring():
    got = _ids(ms.units_from_python("aot/a.py", PY))
    assert got == {
        "aot/a.py::vote": ["Notices#poll"],
        "aot/a.py::listing": ["Notices#list", "Notices#poll"],  # .md 는 떼고 정규화
    }


def test_python_comment_elsewhere_means_whole_file():
    text = "# @manual Notices#widget\nimport json\n\ndef f():\n    return 1\n"
    assert _ids(ms.units_from_python("aot/w.py", text)) == {"aot/w.py": ["Notices#widget"]}


def test_python_block_until_end_marker():
    text = ("x = 1\n# @manual Notices#list\nA = 2\nB = 3\n# @manual-end\nC = 4\n")
    units = ms.units_from_python("aot/b.py", text)
    assert _ids(units) == {"aot/b.py#L2": ["Notices#list"]}
    # 블록 밖(C)은 지문에 들어가지 않는다
    other = ms.units_from_python("aot/b.py", text.replace("C = 4", "C = 5"))
    assert units[0].fingerprint == other[0].fingerprint


def test_python_comment_above_module_constant_is_that_constant():
    text = ("import os\n\n# @manual Notices#widget\nINFO = {'a': 1}\n\nOTHER = 2\n")
    units = ms.units_from_python("aot/w.py", text)
    assert _ids(units) == {"aot/w.py::INFO": ["Notices#widget"]}
    # 다른 상수만 바뀐 경우는 오래됨이 아니다
    other = ms.units_from_python("aot/w.py", text.replace("OTHER = 2", "OTHER = 3"))
    assert units[0].fingerprint == other[0].fingerprint
    changed = ms.units_from_python("aot/w.py", text.replace("'a': 1", "'a': 2"))
    assert units[0].fingerprint != changed[0].fingerprint


def test_annotation_inside_string_literal_is_ignored():
    text = 'EXAMPLE = "# @manual Notices#poll"\n\ndef f():\n    return 1\n'
    assert ms.units_from_python("aot/s.py", text) == []


def test_generic_template_whole_file_and_multiple_targets():
    text = '{% extends "x" %}\n{# @manual Notices#replies, Notices#poll #}\n<div>hi</div>\n'
    assert _ids(ms.units_from_generic("aot/t.html", text)) == {
        "aot/t.html": ["Notices#poll", "Notices#replies"]}


# ── 지문: 주석·공백·독스트링은 무시, 코드는 잡는다 ─────────────────────────

def _fp(text, uid):
    return {u.id: u.fingerprint for u in ms.units_from_python("aot/a.py", text)}[uid]


def test_python_fingerprint_ignores_comments_whitespace_docstrings():
    base = _fp(PY, "aot/a.py::vote")
    cosmetic = PY.replace('    """Vote."""', '    """Vote — reworded."""\n    # a comment') \
                 .replace("return x + 1", "return  x+1")
    assert _fp(cosmetic, "aot/a.py::vote") == base


def test_python_fingerprint_changes_on_behaviour_change():
    assert _fp(PY.replace("x + 1", "x + 2"), "aot/a.py::vote") != _fp(PY, "aot/a.py::vote")


def test_generic_fingerprint_ignores_indentation_but_not_content():
    a = "{# @manual Notices#list #}\n<div>\n  <p>x</p>\n</div>\n"
    b = "{# @manual Notices#list #}\n<div>\n<p>x</p>\n\n</div>\n"
    c = "{# @manual Notices#list #}\n<div>\n<p>y</p>\n</div>\n"
    fa, fb, fc = (ms.units_from_generic("aot/t.html", t)[0].fingerprint for t in (a, b, c))
    assert fa == fb != fc


# ── 절 찾기 ────────────────────────────────────────────────────────────────

def test_find_section_includes_subheadings_and_skips_fenced_headings():
    sec = ms.section_text(PAGE_EN, "poll", "en")
    assert sec.startswith("## Poll { #poll }")
    assert "### Sub detail" in sec and "More." in sec
    assert "List View" not in sec


def test_non_english_needs_explicit_anchor():
    ko = PAGE_KO.replace("## 목록 보기 { #list }", "## 목록 보기")
    assert ms.find_section(ko, "list", allow_slug=False) is None
    # 영어는 자동 슬러그도 받는다
    en = PAGE_EN.replace("## List View { #list }", "## List View")
    assert ms.section_text(en, "list-view", "en").startswith("## List View")


def test_replace_section_keeps_the_rest_of_the_page():
    out = ms.replace_section(PAGE_EN, "poll", "## Poll { #poll }\n\nNew text.", "en")
    assert "New text." in out and "Sub detail" not in out
    assert out.startswith("# Notice Board") and "## List View { #list }" in out


# ── 상태와 장부 ─────────────────────────────────────────────────────────────

def _repo(py=PY, ledger=None, ko=PAGE_KO):
    files = {"aot/a.py": py, "docs/Notices.md": PAGE_EN, "docs/Notices.ko.md": ko}
    if ledger is not None:
        files[ms.LEDGER_PATH] = json.dumps(ledger)
    return FakeSource(files)


def _stamped_ledger():
    state, _ = ms.compute_state(_repo())
    ledger = {"version": 1, "targets": {}}
    ms.stamp(sorted(state), state, ledger, "abc123")
    return ledger


def test_new_then_ok_then_stale_lifecycle():
    state, _ = ms.compute_state(_repo())
    assert {t: s["status"] for t, s in state.items()} == {"Notices#list": "new", "Notices#poll": "new"}

    ledger = _stamped_ledger()
    state, _ = ms.compute_state(_repo(ledger=ledger))
    assert all(s["status"] == "ok" for s in state.values())

    # 주석만 바뀐 커밋 → 그대로 최신
    state, _ = ms.compute_state(_repo(py=PY.replace('"""Vote."""', '"""Vote!"""'), ledger=ledger))
    assert all(s["status"] == "ok" for s in state.values())

    # 동작이 바뀐 커밋 → 그 함수가 걸린 절만 오래됨, 무엇이 바뀌었는지 남는다
    state, _ = ms.compute_state(_repo(py=PY.replace("x + 1", "x + 2"), ledger=ledger))
    assert state["Notices#poll"]["status"] == "stale"
    assert state["Notices#poll"]["changed_units"] == ["aot/a.py::vote"]
    assert state["Notices#list"]["status"] == "ok"


def test_missing_anchor_in_translation_is_a_problem():
    ko = PAGE_KO.replace("## 투표 { #poll }", "## 투표")
    state, _ = ms.compute_state(_repo(ko=ko))
    assert any("Notices.ko.md" in p for p in state["Notices#poll"]["problems"])
    assert state["Notices#list"]["problems"] == []


def test_missing_language_file_is_not_a_problem():
    src = _repo()
    del src.files["docs/Notices.ko.md"]
    state, _ = ms.compute_state(src)
    assert all(not s["problems"] for s in state.values())


def test_orphans_are_reported():
    ledger = _stamped_ledger()
    ledger["targets"]["Gone#x"] = {"code": "0", "units": {}}
    _, orphans = ms.compute_state(_repo(ledger=ledger))
    assert orphans == ["Gone#x"]


# ── 응답 적용 ──────────────────────────────────────────────────────────────

def test_parse_response_accepts_fenced_json():
    data = ms.parse_response('설명\n```json\n{"sections": []}\n```\n')
    assert data == {"sections": []}


def test_parse_response_marker_blocks_keep_raw_markdown():
    raw = (
        "@@@SECTION geo/api-reference#design-maps\n"
        "@@@CHANGED true\n"
        "@@@REASON 필드명 정정\n"
        "@@@EN\n"
        "## Design Maps { #design-maps }\n\n```json\n{\"map_uuid\": \"a\\\\b\"}\n```\n"
        "@@@KO\n"
        "## 설계 지도 { #design-maps }\n\n```json\n{\"map_uuid\": \"a\\\\b\"}\n```\n"
        "@@@END\n"
        "@@@SECTION geo/api-reference#search\n"
        "@@@CHANGED false\n"
        "@@@REASON 일치\n"
        "@@@END\n")
    secs = ms.parse_response(raw)["sections"]
    assert secs[0]["target"] == "geo/api-reference#design-maps" and secs[0]["changed"] is True
    assert '{"map_uuid": "a\\\\b"}' in secs[0]["en"]
    assert secs[0]["ko"].startswith("## 설계 지도")
    assert secs[1] == {"target": "geo/api-reference#search", "changed": False, "reason": "일치"}


@pytest.fixture
def tree(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "Notices.md").write_text(PAGE_EN)
    (tmp_path / "docs" / "Notices.ko.md").write_text(PAGE_KO)
    monkeypatch.setattr(ms, "ROOT", str(tmp_path))
    state, _ = ms.compute_state(_repo())
    return tmp_path, state


def _resp(**sec):
    base = {"target": "Notices#list", "changed": True, "reason": "r"}
    base.update(sec)
    return {"sections": [base]}


def test_apply_writes_all_languages(tree):
    root, state = tree
    resp = _resp(en="## List View { #list }\n\n- item\n- search box",
                 ko="## 목록 보기 { #list }\n\n- 항목\n- 검색창")
    applied, unchanged, failed, _ = ms.apply_page("Notices", ["Notices#list"], state, resp)
    assert [t for t, _ in applied] == ["Notices#list"] and not failed
    assert "search box" in (root / "docs" / "Notices.md").read_text()
    assert "검색창" in (root / "docs" / "Notices.ko.md").read_text()


def test_apply_rejects_lost_anchor(tree):
    root, state = tree
    resp = _resp(en="## List View\n\n- item", ko="## 목록 보기 { #list }\n\n- 항목")
    applied, _, failed, _ = ms.apply_page("Notices", ["Notices#list"], state, resp)
    assert not applied and "앵커" in failed[0][1]
    assert (root / "docs" / "Notices.md").read_text() == PAGE_EN


def test_apply_rejects_structure_mismatch_between_languages(tree):
    root, state = tree
    resp = _resp(en="## List View { #list }\n\n- item\n- search box",
                 ko="## 목록 보기 { #list }\n\n- 항목")
    applied, _, failed, _ = ms.apply_page("Notices", ["Notices#list"], state, resp)
    assert not applied and "골격" in failed[0][1]
    assert (root / "docs" / "Notices.ko.md").read_text() == PAGE_KO


def test_apply_unchanged_touches_nothing(tree):
    root, state = tree
    applied, unchanged, failed, _ = ms.apply_page(
        "Notices", ["Notices#list"], state, _resp(changed=False, reason="리팩터링"))
    assert unchanged == [("Notices#list", "리팩터링")] and not applied and not failed
    assert (root / "docs" / "Notices.md").read_text() == PAGE_EN
