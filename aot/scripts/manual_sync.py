#!/usr/bin/env python3
"""매뉴얼 동기화 — 코드 주석으로 매뉴얼 절을 잇고, 코드가 바뀌면 그 절을 다시 쓴다.

## 왜 있는가

`check_docs_reminder.py` 는 폴더 접두사로 "이 영역에 매뉴얼이 있다" 만 알았고,
같은 커밋에 `docs/` 아래 파일이 하나라도 바뀌면 조용히 통과했다. 알림은 그
커밋에서 한 번 뜨고 사라져서, 2026-09-18 감사 때 geo·공지 매뉴얼이 최대
4개월 밀려 있었다. 이 도구는 두 가지를 바꾼다.

  1. **어느 코드가 어느 절을 설명하는지** 를 코드 옆 주석으로 적는다(아래 문법).
  2. 절마다 연결된 코드의 지문을 장부(`docs/.manual-sync.json`)에 적어 둔다.
     코드가 바뀌면 그 절은 **문서가 갱신될 때까지 계속 '오래됨'** 이다 —
     한 번 뜨고 잊히는 알림이 아니라 해소될 때까지 남는 상태다.

오래된 절은 커밋 직후(post-commit 훅) 백그라운드에서 이 Mac 의 `claude` CLI 가
en·ko·ja 세 언어로 다시 쓴다. 결과는 **커밋하지 않은 문서 변경**으로 작업 폴더에
남고, 사람이(또는 세션이) 검토해 다음 커밋에 넣는다. 커밋은 막지 않고,
공개 발행(`publish_public.sh`)에서만 오래된 절이 있으면 멈춘다.

## 주석 문법

대상은 `docs/` 기준 쪽 경로(확장자 생략) + `#앵커`. 앵커를 빼면 쪽 전체다.
쉼표로 여러 개를 적을 수 있다.

    def create_poll(...):
        \"\"\"투표를 만든다.

        @manual Notices#poll
        \"\"\"

    # @manual Notices#poll, Notices#widget      ← def/class·최상위 상수 바로 위 = 그것만
    # @manual geo/plots#stages                   ← 그 밖의 자리 = 파일 전체
    # @manual Notices#list                        ← 블록: 짝이 되는 @manual-end 까지
    ...
    # @manual-end

JS(`//`)·Jinja(`{# #}`)·HTML(`<!-- -->`)·YAML(`#`) 주석도 같은 문법이다
(파이썬이 아닌 파일은 '파일 전체' 와 '블록' 두 가지만 있다).

**지문**: 파이썬 함수·클래스·모듈은 AST(독스트링 제외)로 떠서 주석·공백·줄바꿈만
바뀐 커밋은 오래됨을 만들지 않는다. 그 밖의 파일은 줄 앞뒤 공백·빈 줄·
`@manual` 줄을 걷어낸 본문으로 뜬다.

**앵커**: 연결된 절의 제목에는 `## 제목 { #anchor }` 명시 앵커를 달 것.
ko·ja 쪽은 자동 슬러그가 영어와 달라 명시 앵커로만 같은 절을 찾는다.

## 명령

    python3 aot/scripts/manual_sync.py status [--source worktree|index|REV] [--strict] [--json]
    python3 aot/scripts/manual_sync.py stamp TARGET... | --all     # "문서가 코드와 맞다" 고 기록
    python3 aot/scripts/manual_sync.py update [TARGET...] [--dry-run]   # claude 로 다시 쓰기(전경)
    python3 aot/scripts/manual_sync.py autodraft    # post-commit 훅 진입점(백그라운드 update)
    python3 aot/scripts/manual_sync.py precommit    # pre-commit 훅 진입점(경고만)

문서를 사람이 직접 고쳤거나 코드 변경이 문서와 무관하면(리팩터링 등)
`stamp Notices#poll` 로 장부를 맞춘다.

환경변수:
  AOT_SKIP_MANUAL_AUTODRAFT=1   post-commit 자동 갱신 끄기
  AOT_MANUAL_SYNC_CLAUDE        claude 실행 파일(기본 'claude')
  AOT_MANUAL_SYNC_MODEL         claude --model 값(기본: CLI 기본값)
  AOT_MANUAL_SYNC_NOTIFY=0      macOS 알림 끄기
"""
import argparse
import ast
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tokenize
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER_PATH = "docs/.manual-sync.json"
STATE_DIR = ".local/manual_sync"
LANGS = ("en", "ko", "ja")

# 주석을 찾는 범위. 산출물(번들)·매뉴얼 사본·테스트(픽스처에 주석 문자열이 있다)·
# 이 파일 자신(문법 예시)은 뺀다.
SCAN_PATHS = ["aot"]
SCAN_EXCLUDES = [
    ":(exclude)aot/tests",
    ":(exclude)aot/scripts/manual_sync.py",
    ":(exclude,glob)aot/**/dist/**",
    ":(exclude,glob)aot/**/*.min.js",
    ":(exclude)aot/aot_flask/static/manual",
    ":(exclude)aot/aot_flask/translations",
]
SCAN_EXTS = (".py", ".js", ".mjs", ".html", ".j2", ".jinja", ".yaml", ".yml", ".css")

_TARGET = r"[A-Za-z0-9_][A-Za-z0-9_./-]*(?:#[A-Za-z0-9_-]+)?"
ANN_RE = re.compile(r"@manual(?!-end)[:\s]\s*(" + _TARGET + r"(?:\s*,\s*" + _TARGET + r")*)")
END_RE = re.compile(r"@manual-end\b")
GREP_PATTERN = r"@manual[: ]"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
EXPLICIT_ANCHOR_RE = re.compile(r"\{\s*#([A-Za-z0-9_-]+)[^}]*\}\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _git(*args, cwd=None, check=False):
    r = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


# ──────────────────────────────────────────────────────────────────────────
# 읽기 원천 — 작업 폴더 / 인덱스(pre-commit) / 커밋(발행 게이트)
# ──────────────────────────────────────────────────────────────────────────

class Source:
    """같은 질문(주석이 있는 파일 목록, 파일 내용)을 세 원천에 묻는다."""

    def __init__(self, spec="worktree", root=ROOT):
        self.spec = spec
        self.root = root

    def annotated_files(self):
        args = ["grep", "-l", "-I", "-E", "-e", GREP_PATTERN]
        if self.spec == "worktree":
            args.insert(1, "--untracked")
        elif self.spec == "index":
            args.insert(1, "--cached")
        else:
            args.append(self.spec)
        args += ["--", *SCAN_PATHS, *SCAN_EXCLUDES]
        r = _git(*args, cwd=self.root)
        if r.returncode not in (0, 1):
            raise RuntimeError(f"git grep 실패: {r.stderr.strip()}")
        out = []
        for ln in r.stdout.splitlines():
            if self.spec not in ("worktree", "index"):
                ln = ln.split(":", 1)[1] if ":" in ln else ln
            if ln.endswith(SCAN_EXTS):
                out.append(ln)
        return sorted(set(out))

    def read(self, path):
        if self.spec == "worktree":
            full = os.path.join(self.root, path)
            if not os.path.isfile(full):
                return None
            with open(full, encoding="utf-8", errors="replace") as f:
                return f.read()
        ref = f":{path}" if self.spec == "index" else f"{self.spec}:{path}"
        r = subprocess.run(["git", "show", ref], cwd=self.root, capture_output=True)
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", errors="replace")


# ──────────────────────────────────────────────────────────────────────────
# 코드 쪽 — 주석을 읽어 '단위'(함수·클래스·블록·파일)와 지문을 뽑는다
# ──────────────────────────────────────────────────────────────────────────

class Unit:
    __slots__ = ("id", "path", "targets", "fingerprint", "excerpt")

    def __init__(self, id, path, targets, fingerprint, excerpt):
        self.id = id
        self.path = path
        self.targets = list(targets)
        self.fingerprint = fingerprint
        self.excerpt = excerpt


def parse_targets(s):
    return [t.strip() for t in s.split(",") if t.strip()]


def normalize_target(t):
    page, _, anchor = t.partition("#")
    if page.endswith(".md"):
        page = page[:-3]
    return f"{page}#{anchor}" if anchor else page


def _norm_text(lines):
    kept = []
    for ln in lines:
        s = ln.strip()
        if not s or "@manual" in s:
            continue
        kept.append(s)
    return "\n".join(kept)


class _StripDocstrings(ast.NodeTransformer):
    def _strip(self, node):
        self.generic_visit(node)
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
        return node

    visit_Module = visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _strip


def _py_fingerprint(node):
    import copy
    return _h(ast.dump(_StripDocstrings().visit(copy.deepcopy(node)), include_attributes=False))


def _node_first_line(node):
    decs = getattr(node, "decorator_list", None) or []
    return min([node.lineno] + [d.lineno for d in decs])


def _excerpt(lines, start, end, limit=6000):
    text = "\n".join(lines[start - 1:end])
    return text if len(text) <= limit else text[:limit] + "\n… (잘림)"


def _add(units, unit):
    """같은 id 는 한 단위로 합치고 대상만 더한다."""
    for u in units:
        if u.id == unit.id:
            for t in unit.targets:
                if t not in u.targets:
                    u.targets.append(t)
            return
    units.append(unit)


def _block_units(path, lines, starts, units, whole_file_fp, whole_excerpt):
    """(줄번호, 대상들) 목록을 블록 또는 파일 전체 단위로 바꾼다."""
    ends = [i + 1 for i, ln in enumerate(lines) if END_RE.search(ln)]
    used_ends = set()
    for n, (line_no, targets) in enumerate(starts):
        nxt_start = starts[n + 1][0] if n + 1 < len(starts) else len(lines) + 1
        end = next((e for e in ends if line_no < e < nxt_start and e not in used_ends), None)
        if end:
            used_ends.add(end)
            body = lines[line_no:end - 1]
            _add(units, Unit(f"{path}#L{line_no}", path, targets,
                             _h(_norm_text(body)), _excerpt(lines, line_no, end)))
        else:
            _add(units, Unit(path, path, targets, whole_file_fp(), whole_excerpt()))


def units_from_python(path, text):
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return units_from_generic(path, text)

    units = []
    whole_fp = lambda: _py_fingerprint(tree)
    whole_ex = lambda: _excerpt(lines, 1, len(lines), limit=12000)

    # 1) 독스트링 안의 @manual
    defs = {}  # 첫 줄(데코레이터 포함) → (노드, 한정 이름)

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}{child.name}"
                defs[_node_first_line(child)] = (child, qual)
                doc = ast.get_docstring(child, clean=False) or ""
                for m in ANN_RE.finditer(doc):
                    _add(units, Unit(f"{path}::{qual}", path,
                                     [normalize_target(t) for t in parse_targets(m.group(1))],
                                     _py_fingerprint(child),
                                     _excerpt(lines, _node_first_line(child), child.end_lineno)))
                walk(child, qual + ".")

    walk(tree, "")
    # 모듈 최상위 상수(예: 위젯 WIDGET_INFORMATION, 재질표 MATERIALS)도 바로 위 주석이면
    # 그 대입문 하나를 단위로 본다 — 동작이 함수가 아니라 표에만 있는 경우가 있다.
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in tgts if isinstance(t, ast.Name)]
            if names:
                defs.setdefault(node.lineno, (node, names[0]))
    mod_doc = ast.get_docstring(tree, clean=False) or ""
    for m in ANN_RE.finditer(mod_doc):
        _add(units, Unit(path, path, [normalize_target(t) for t in parse_targets(m.group(1))],
                         whole_fp(), whole_ex()))

    # 2) 주석 속 @manual — 문자열 안의 예시를 잘못 줍지 않도록 토큰으로 본다.
    comment_anns = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                m = ANN_RE.search(tok.string)
                if m:
                    comment_anns.append((tok.start[0],
                                         [normalize_target(t) for t in parse_targets(m.group(1))]))
    except (tokenize.TokenError, IndentationError):
        pass

    has_end = any(END_RE.search(ln) for ln in lines)
    blockish = []
    for line_no, targets in comment_anns:
        # def/class 바로 위(빈 줄·다른 주석은 건너뜀)면 그 함수·클래스
        j = line_no + 1
        while j <= len(lines) and (not lines[j - 1].strip() or lines[j - 1].strip().startswith("#")):
            j += 1
        if j in defs and not (has_end and _block_closes(lines, line_no)):
            node, qual = defs[j]
            _add(units, Unit(f"{path}::{qual}", path, targets, _py_fingerprint(node),
                             _excerpt(lines, j, node.end_lineno)))
        else:
            blockish.append((line_no, targets))
    if blockish:
        _block_units(path, lines, blockish, units, whole_fp, whole_ex)
    return units


def _block_closes(lines, start):
    """start 줄의 @manual 뒤, 다음 @manual 이 나오기 전에 @manual-end 가 있으면 블록이다."""
    for i in range(start, len(lines)):
        if END_RE.search(lines[i]):
            return True
        if ANN_RE.search(lines[i]):
            return False
    return False


def units_from_generic(path, text):
    lines = text.splitlines()
    starts = []
    for i, ln in enumerate(lines, 1):
        m = ANN_RE.search(ln)
        if m:
            starts.append((i, [normalize_target(t) for t in parse_targets(m.group(1))]))
    units = []
    if starts:
        _block_units(path, lines, starts, units,
                     lambda: _h(_norm_text(lines)),
                     lambda: _excerpt(lines, 1, len(lines), limit=12000))
    return units


def units_from_file(path, text):
    return units_from_python(path, text) if path.endswith(".py") else units_from_generic(path, text)


def collect_units(source):
    units = []
    for path in source.annotated_files():
        text = source.read(path)
        if text is not None:
            units.extend(units_from_file(path, text))
    return units


def target_code_hash(unit_fps):
    return _h("\n".join(f"{k}={v}" for k, v in sorted(unit_fps.items())))


# ──────────────────────────────────────────────────────────────────────────
# 문서 쪽 — 쪽·절 찾기
# ──────────────────────────────────────────────────────────────────────────

def page_file(page, lang):
    return f"docs/{page}.md" if lang == "en" else f"docs/{page}.{lang}.md"


def _slugify(text):
    # Python-Markdown toc 기본 슬러그(mkdocs.yml 은 슬러그 함수를 바꾸지 않는다).
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def iter_headings(text):
    """코드 펜스 밖의 제목만 (줄 인덱스, 수준, 제목 글, 명시 앵커) 로 낸다."""
    in_fence = False
    for i, ln in enumerate(text.split("\n")):
        if FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(ln)
        if m:
            title = m.group(2)
            am = EXPLICIT_ANCHOR_RE.search(title)
            anchor = am.group(1) if am else None
            if am:
                title = title[:am.start()].strip()
            yield i, len(m.group(1)), title, anchor


def find_section(text, anchor, allow_slug=True):
    """앵커가 가리키는 절의 줄 범위 [start, end) — 없으면 None. anchor 가 없으면 쪽 전체."""
    lines = text.split("\n")
    if not anchor:
        return 0, len(lines)
    heads = list(iter_headings(text))
    for n, (i, level, title, explicit) in enumerate(heads):
        if explicit == anchor or (allow_slug and not explicit and _slugify(title) == anchor):
            end = len(lines)
            for j, lv, _t, _a in heads[n + 1:]:
                if lv <= level:
                    end = j
                    break
            while end > i + 1 and not lines[end - 1].strip():
                end -= 1
            return i, end
    return None


def section_text(text, anchor, lang):
    rng = find_section(text, anchor, allow_slug=(lang == "en"))
    if rng is None:
        return None
    lines = text.split("\n")
    return "\n".join(lines[rng[0]:rng[1]])


def replace_section(text, anchor, new_section, lang):
    rng = find_section(text, anchor, allow_slug=(lang == "en"))
    if rng is None:
        raise ValueError(f"#{anchor} 절을 찾지 못했습니다")
    lines = text.split("\n")
    new_lines = new_section.rstrip("\n").split("\n")
    return "\n".join(lines[:rng[0]] + new_lines + lines[rng[1]:])


def structure_signature(md):
    """언어와 무관하게 같아야 하는 골격(제목 수준·표 행·목록 항목·코드 블록)."""
    sig = {"headings": [], "table_rows": 0, "list_items": 0, "fences": 0}
    in_fence = False
    for ln in md.split("\n"):
        if FENCE_RE.match(ln):
            sig["fences"] += 1
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(ln)
        if m:
            sig["headings"].append(len(m.group(1)))
        elif ln.lstrip().startswith("|"):
            sig["table_rows"] += 1
        elif re.match(r"^\s*([-*+]|\d+\.)\s+", ln):
            sig["list_items"] += 1
    return sig


# ──────────────────────────────────────────────────────────────────────────
# 장부와 상태
# ──────────────────────────────────────────────────────────────────────────

def load_ledger(source):
    raw = source.read(LEDGER_PATH)
    if not raw:
        return {"version": 1, "targets": {}}
    data = json.loads(raw)
    data.setdefault("targets", {})
    return data


def save_ledger(ledger, root=ROOT):
    ledger["targets"] = dict(sorted(ledger["targets"].items()))
    with open(os.path.join(root, LEDGER_PATH), "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
        f.write("\n")


def compute_state(source, units=None):
    """대상마다 {status, units, code, entry, problems} 를 낸다.

    status: ok | stale(코드가 장부와 다름) | new(장부에 없음 = 아직 대조한 적 없음)
    problems: 쪽·앵커가 없는 등 링크 자체의 오류(상태와 별개로 항상 고쳐야 함)
    """
    units = collect_units(source) if units is None else units
    ledger = load_ledger(source)
    by_target = {}
    for u in units:
        for t in u.targets:
            by_target.setdefault(t, {})[u.id] = u
    state = {}
    page_cache = {}
    for target, umap in sorted(by_target.items()):
        page, _, anchor = target.partition("#")
        fps = {uid: u.fingerprint for uid, u in umap.items()}
        code = target_code_hash(fps)
        entry = ledger["targets"].get(target)
        problems = []
        for lang in LANGS:
            key = (page, lang)
            if key not in page_cache:
                page_cache[key] = source.read(page_file(page, lang))
            text = page_cache[key]
            if text is None:
                if lang == "en":
                    problems.append(f"쪽이 없습니다: {page_file(page, 'en')}")
                continue
            if anchor and find_section(text, anchor, allow_slug=(lang == "en")) is None:
                problems.append(f"{page_file(page, lang)} 에 {{ #{anchor} }} 절이 없습니다")
        if entry is None:
            status = "new"
        elif entry.get("code") != code:
            status = "stale"
        else:
            status = "ok"
        changed_units = []
        if entry is not None:
            old = entry.get("units", {})
            changed_units = sorted([uid for uid in fps if old.get(uid) != fps[uid]]
                                   + [uid for uid in old if uid not in fps])
        state[target] = {"status": status, "units": umap, "code": code, "entry": entry,
                         "problems": problems, "changed_units": changed_units}
    orphans = sorted(set(ledger["targets"]) - set(by_target))
    return state, orphans


def stamp(targets, state, ledger, commit):
    today = datetime.date.today().isoformat()
    for t in targets:
        st = state[t]
        ledger["targets"][t] = {
            "code": st["code"],
            "units": {uid: u.fingerprint for uid, u in sorted(st["units"].items())},
            "commit": commit,
            "stamped": today,
        }


def _head():
    r = _git("rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else ""


# ──────────────────────────────────────────────────────────────────────────
# claude 로 다시 쓰기
# ──────────────────────────────────────────────────────────────────────────

PROMPT_HEAD = """\
당신은 AoT 사용자 매뉴얼(mkdocs, docs/)을 코드에 맞춰 고치는 편집자입니다.
아래 '매뉴얼 절'들은 주석(@manual)으로 코드와 연결돼 있고, 연결된 코드가 장부에
적힌 뒤로 바뀌었거나(stale) 아직 한 번도 대조된 적이 없습니다(new).

할 일: 각 절을 현재 코드와 대조해, 사용자에게 보이는 동작·화면·설정·제약이
문서와 어긋나면 고치고, 새로 생긴 것은 넣고, 없어진 것은 뺍니다. 필요하면
Read·Grep·Glob 으로 저장소의 코드를 더 읽어도 됩니다(파일 수정은 하지 않습니다).

규칙:
- 독자는 시스템을 운영하는 사람입니다. 함수명·파일명·내부 구현은 쓰지 않습니다
  (그 쪽이 원래 API 참조처럼 식별자를 다루는 쪽이면 그 관례를 따릅니다).
- 코드로 확인한 것만 씁니다. 추측으로 기능을 만들지 않습니다.
- 사용자에게 보이는 변화가 없으면(리팩터링·내부 수정) changed=false 로 두고 본문은 생략합니다.
- 고칠 때도 바뀐 부분만 고치고 나머지 문장·순서·어조는 그대로 둡니다.
- 절의 첫 줄(제목)과 그 끝의 `{ #앵커 }` 는 반드시 남깁니다. 앵커 이름은 번역하지 않습니다.
- en 이 정본입니다. ko·ja 는 en 과 같은 내용을 같은 골격(제목 수·수준, 표 행 수,
  목록 항목 수, 코드 블록 수)으로 씁니다. 원래 없는 언어(null)는 쓰지 않습니다.
- 다른 절·쪽으로 가는 링크와 이미지 경로는 그대로 둡니다.
- 특정 업종(농장·작물·생육 등)을 전제하는 단어를 새로 넣지 않습니다. 이미 있는 표현은 둡니다.

출력: 설명 없이 대상마다 아래 표식 블록만 냅니다(마크다운을 그대로 쓰고 따옴표·역슬래시를
이스케이프하지 않습니다). 표식 줄은 글자 그대로 씁니다.
@@@SECTION <대상>
@@@CHANGED true|false
@@@REASON <한 문장, 한국어>
@@@EN
<절 전체 마크다운 — changed=false 면 이 아래 언어 블록은 생략>
@@@KO
<...>
@@@JA
<...>
@@@END
"""


def _diff_since(commit, path, limit=8000):
    if not commit:
        return ""
    r = _git("diff", "--no-color", "-U3", commit, "--", path)
    out = r.stdout if r.returncode == 0 else ""
    return out if len(out) <= limit else out[:limit] + "\n… (잘림)"


def build_prompt(page, targets, state, docs):
    """절은 대상마다, 코드는 쪽 전체에서 한 번씩만 싣는다(여러 절이 같은 코드를 공유한다)."""
    parts = [PROMPT_HEAD, f"\n# 쪽: {page}\n"]
    code_units = {}
    diffs = {}  # path → (commit, diff)
    for t in targets:
        st = state[t]
        anchor = t.partition("#")[2]
        parts.append(f"\n## 대상 {t}  (상태: {st['status']})\n")
        parts.append("연결된 코드: " + ", ".join(sorted(st["units"])) + "\n")
        for lang in LANGS:
            text = docs.get(lang)
            if text is None:
                parts.append(f"\n### 매뉴얼 절 [{lang}]: null (이 언어 파일 없음)\n")
                continue
            parts.append(f"\n### 매뉴얼 절 [{lang}]\n```markdown\n"
                         f"{section_text(text, anchor, lang) or ''}\n```\n")
        commit = (st["entry"] or {}).get("commit")
        for uid, u in st["units"].items():
            code_units[uid] = u
            if st["status"] == "stale" and uid in st["changed_units"] and u.path not in diffs:
                diffs[u.path] = (commit, _diff_since(commit, u.path))
    parts.append("\n# 연결된 코드 (현재)\n")
    for uid, u in sorted(code_units.items()):
        parts.append(f"\n## {uid}\n```\n{u.excerpt}\n```\n")
    for path, (commit, d) in sorted(diffs.items()):
        if d:
            parts.append(f"\n## {path} 의 변경분 (장부 기록 {commit[:9]} 이후)\n```diff\n{d}\n```\n")
    return "".join(parts)


MAX_PROMPT_CHARS = int(os.environ.get("AOT_MANUAL_SYNC_MAX_PROMPT", "120000"))


def _batches(page, targets, state, source):
    """한 번에 보낼 대상 묶음. 프롬프트가 MAX_PROMPT_CHARS 를 넘지 않게 앞에서부터 채운다
    (대상 하나가 혼자 넘으면 그 하나만으로 한 묶음 — 코드 발췌는 이미 잘려 있다)."""
    docs = {lang: source.read(page_file(page, lang)) for lang in LANGS}
    out, cur = [], []
    for t in targets:
        trial = cur + [t]
        if cur and len(build_prompt(page, trial, state, docs)) > MAX_PROMPT_CHARS:
            out.append(cur)
            cur = [t]
        else:
            cur = trial
    if cur:
        out.append(cur)
    return out


def _child_env():
    env = dict(os.environ)
    # Claude Code 세션 안의 커밋에서 불려도 독립된 headless 실행이 되도록.
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(k, None)
    return env


def run_claude(prompt, timeout=1800):
    exe = os.environ.get("AOT_MANUAL_SYNC_CLAUDE", "claude")
    cmd = [exe, "-p", "--output-format", "json",
           "--allowedTools", "Read", "Grep", "Glob",
           "--disallowedTools", "Edit", "Write", "Bash", "NotebookEdit", "WebFetch", "WebSearch"]
    model = os.environ.get("AOT_MANUAL_SYNC_MODEL")
    if model:
        cmd += ["--model", model]
    last_err = None
    for attempt in range(3):  # 병렬 실행 중 일시 오류(과부하·속도 제한)가 실측됐다 — 두 번 더 시도
        if attempt:
            time.sleep(30 * attempt)
        r = subprocess.run(cmd, input=prompt, cwd=ROOT, capture_output=True, text=True,
                           timeout=timeout, env=_child_env())
        envelope = None
        try:
            envelope = json.loads(r.stdout) if r.stdout.strip() else None
        except ValueError:
            pass
        if r.returncode == 0 and envelope and not envelope.get("is_error"):
            break
        detail = (r.stderr.strip() or (str(envelope.get("result")) if envelope else r.stdout.strip()))
        last_err = f"claude 실패({r.returncode}, 시도 {attempt + 1}/3): {detail[-500:]}"
    else:
        raise RuntimeError(last_err)
    return parse_response(envelope.get("result", ""))


_BLOCK_RE = re.compile(r"^@@@SECTION[ \t]+(\S+)[ \t]*\n(.*?)^@@@END[ \t]*$", re.S | re.M)
_TAG_RE = re.compile(r"^@@@(CHANGED|REASON|EN|KO|JA)\b[ \t]*(.*)$", re.M)


def parse_response(text):
    """표식 블록(@@@SECTION … @@@END)을 읽는다. 옛 JSON 모양도 받는다.

    JSON 을 버린 이유: API 참조처럼 본문에 JSON 예시·따옴표가 많은 절에서 모델이
    이스케이프를 빠뜨려 응답 전체가 파싱 실패했다(26-09-26 실측). 표식 블록은
    마크다운을 날것 그대로 담으니 이스케이프할 것이 없다.
    """
    blocks = list(_BLOCK_RE.finditer(text))
    if blocks:
        sections = []
        for b in blocks:
            sec = {"target": b.group(1).strip()}
            body = b.group(2)
            tags = list(_TAG_RE.finditer(body))
            for n, m in enumerate(tags):
                key, inline = m.group(1), m.group(2).strip()
                end = tags[n + 1].start() if n + 1 < len(tags) else len(body)
                if key == "CHANGED":
                    sec["changed"] = inline.lower() == "true"
                elif key == "REASON":
                    sec["reason"] = inline
                else:
                    sec[key.lower()] = body[m.end():end].strip("\n")
            sections.append(sec)
        return {"sections": sections}
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.S)
    if fence:
        s = fence.group(1)
    else:
        a, b = s.find("{"), s.rfind("}")
        if a < 0 or b < 0:
            raise ValueError("응답에 @@@SECTION 블록도 JSON 도 없습니다")
        s = s[a:b + 1]
    data = json.loads(s)
    if not isinstance(data.get("sections"), list):
        raise ValueError("응답에 sections 목록이 없습니다")
    return data


def validate_section(target, lang, new_md, old_md):
    """적용 전 기계 검사 — 통과 못 하면 그 대상은 적용하지 않는다."""
    anchor = target.partition("#")[2]
    first = new_md.lstrip("\n").split("\n", 1)[0]
    if anchor:
        m = HEADING_RE.match(first)
        if not m:
            return "첫 줄이 제목이 아닙니다"
        am = EXPLICIT_ANCHOR_RE.search(m.group(2))
        old_first = old_md.split("\n", 1)[0]
        old_m = HEADING_RE.match(old_first)
        if not old_m:
            return "원래 절을 찾지 못했습니다"
        if len(m.group(1)) != len(old_m.group(1)):
            return "제목 수준이 바뀌었습니다"
        if EXPLICIT_ANCHOR_RE.search(old_first) and (not am or am.group(1) != anchor):
            return f"{{ #{anchor} }} 앵커가 사라졌습니다"
    return None


def apply_page(page, targets, state, response, dry_run=False):
    """응답을 쪽 파일에 적용한다. (적용된 대상, 변경 없음 대상, 실패 [(대상, 이유)])"""
    files = {lang: page_file(page, lang) for lang in LANGS}
    before = {}
    for lang, rel in files.items():
        full = os.path.join(ROOT, rel)
        before[lang] = open(full, encoding="utf-8").read() if os.path.isfile(full) else None
    new_docs = dict(before)
    applied, unchanged, failed = [], [], []
    by_target = {s.get("target"): s for s in response["sections"]}
    for t in targets:
        sec = by_target.get(t)
        if not sec:
            failed.append((t, "응답에 이 대상이 없습니다"))
            continue
        if not sec.get("changed"):
            unchanged.append((t, sec.get("reason", "")))
            continue
        anchor = t.partition("#")[2]
        err = None
        trial = dict(new_docs)
        sigs = {}
        for lang in LANGS:
            if before[lang] is None:
                continue
            md = sec.get(lang)
            if not md:
                err = f"{lang} 본문이 비었습니다"
                break
            old = section_text(new_docs[lang], anchor, lang)
            err = validate_section(t, lang, md, old or "")
            if err:
                err = f"{lang}: {err}"
                break
            sigs[lang] = structure_signature(md)
            trial[lang] = replace_section(new_docs[lang], anchor, md, lang)
        if not err and len({json.dumps(v, sort_keys=True) for v in sigs.values()}) > 1:
            err = "언어별 골격(제목·표 행·목록·코드 블록 수)이 다릅니다: " + json.dumps(sigs)
        if err:
            failed.append((t, err))
            continue
        new_docs = trial
        applied.append((t, sec.get("reason", "")))

    if applied and not dry_run:
        # 그 사이 사람이 같은 파일을 고쳤으면 덮어쓰지 않는다.
        for lang, rel in files.items():
            full = os.path.join(ROOT, rel)
            if before[lang] is None or new_docs[lang] == before[lang]:
                continue
            cur = open(full, encoding="utf-8").read()
            if cur != before[lang]:
                raise RuntimeError(f"{rel} 가 초안 작성 중에 바뀌었습니다 — 덮어쓰지 않습니다")
        for lang, rel in files.items():
            if before[lang] is not None and new_docs[lang] != before[lang]:
                with open(os.path.join(ROOT, rel), "w", encoding="utf-8") as f:
                    f.write(new_docs[lang])
    return applied, unchanged, failed, before


def _restore(page, before):
    for lang, text in before.items():
        if text is not None:
            with open(os.path.join(ROOT, page_file(page, lang)), "w", encoding="utf-8") as f:
                f.write(text)


def _docs_health_ok(log):
    script = os.path.join(ROOT, "aot/scripts/check_docs_health.py")
    if not os.path.isfile(script) or not shutil.which("mkdocs"):
        log("  (mkdocs 가 없어 i18n 빌드 검사는 건너뜀)")
        return True
    r = subprocess.run([sys.executable, script, "--only", "i18n"], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        log(r.stdout[-2000:] + r.stderr[-1000:])
    return r.returncode == 0


# ──────────────────────────────────────────────────────────────────────────
# 명령
# ──────────────────────────────────────────────────────────────────────────

STATUS_KO = {"ok": "최신", "stale": "오래됨", "new": "미대조"}


def cmd_status(args):
    source = Source(args.source)
    state, orphans = compute_state(source)
    bad = {t: s for t, s in state.items() if s["status"] != "ok" or s["problems"]}
    if args.json:
        print(json.dumps({
            "targets": {t: {"status": s["status"], "problems": s["problems"],
                            "changed_units": s["changed_units"]} for t, s in state.items()},
            "orphans": orphans}, ensure_ascii=False, indent=2))
    else:
        print(f"연결된 매뉴얼 절 {len(state)}개 — "
              + ", ".join(f"{STATUS_KO[k]} {sum(1 for s in state.values() if s['status'] == k)}"
                          for k in ("ok", "stale", "new")))
        for t, s in bad.items():
            print(f"  [{STATUS_KO[s['status']]}] {t}")
            for uid in s["changed_units"][:5]:
                print(f"      바뀐 코드: {uid}")
            for p in s["problems"]:
                print(f"      ! {p}")
        for o in orphans:
            print(f"  [연결 끊김] {o} — 장부에만 있습니다(stamp --all 이 정리)")
    if args.strict and bad:
        print("\n오래됐거나 대조되지 않은 매뉴얼 절이 있습니다. "
              "`python3 aot/scripts/manual_sync.py update` 로 갱신하거나, "
              "문서가 이미 맞으면 `stamp <대상>` 으로 기록하세요.", file=sys.stderr)
        return 1
    return 0


def cmd_stamp(args):
    source = Source("worktree")
    state, orphans = compute_state(source)
    targets = sorted(state) if args.all else [normalize_target(t) for t in args.targets]
    missing = [t for t in targets if t not in state]
    if missing:
        print("연결된 코드가 없는 대상입니다: " + ", ".join(missing), file=sys.stderr)
        return 2
    broken = [t for t in targets if state[t]["problems"]]
    if broken:
        for t in broken:
            print(f"{t}: " + "; ".join(state[t]["problems"]), file=sys.stderr)
        print("링크 오류부터 고치세요.", file=sys.stderr)
        return 2
    ledger = load_ledger(source)
    stamp(targets, state, ledger, _head())
    if args.all:
        for o in orphans:
            ledger["targets"].pop(o, None)
    save_ledger(ledger)
    print(f"장부에 기록했습니다: {len(targets)}개" + (f", 정리 {len(orphans)}개" if args.all and orphans else ""))
    return 0


class _Lock:
    def __init__(self):
        self.path = os.path.join(ROOT, STATE_DIR, "lock")

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.exists(self.path):
            try:
                pid = int(open(self.path).read().strip() or 0)
                os.kill(pid, 0)
                raise RuntimeError(f"다른 갱신이 진행 중입니다(pid {pid})")
            except (ValueError, ProcessLookupError, PermissionError):
                pass
        with open(self.path, "w") as f:
            f.write(str(os.getpid()))
        return self

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass


def cmd_update(args):
    log_lines = []

    def log(msg):
        print(msg, flush=True)
        log_lines.append(msg)

    with _Lock():
        source = Source("worktree")
        state, _ = compute_state(source)
        if args.targets:
            wanted = [normalize_target(t) for t in args.targets]
            unknown = [t for t in wanted if t not in state]
            if unknown:
                log("연결된 코드가 없는 대상입니다: " + ", ".join(unknown))
                return 2
        else:
            wanted = [t for t, s in state.items() if s["status"] != "ok"]
        skipped = [t for t in wanted if state[t]["problems"]]
        for t in skipped:
            log(f"건너뜀 {t}: " + "; ".join(state[t]["problems"]))
        wanted = [t for t in wanted if t not in skipped]
        if not wanted:
            log("갱신할 매뉴얼 절이 없습니다.")
            return 0

        pages = {}
        for t in wanted:
            pages.setdefault(t.partition("#")[0], []).append(t)
        ledger = load_ledger(source)
        commit = _head()
        report = []
        mutex = threading.Lock()  # 파일 쓰기·빌드 검사·장부 저장은 한 번에 하나씩

        def run_batch(page, targets):
            with mutex:
                docs = {lang: source.read(page_file(page, lang)) for lang in LANGS}
            prompt = build_prompt(page, targets, state, docs)
            if args.dry_run and args.show_prompt:
                log(prompt)
            try:
                resp = run_claude(prompt)
            except Exception as e:  # noqa: BLE001 — 한 묶음 실패가 나머지를 막지 않게
                with mutex:
                    log(f"[{page}] 실패: {e}")
                    report.append((page, [], [], [(t, str(e)) for t in targets]))
                return
            with mutex:
                try:
                    applied, unchanged, failed, before = apply_page(page, targets, state, resp,
                                                                    dry_run=args.dry_run)
                except RuntimeError as e:
                    log(f"[{page}] 적용 중단: {e}")
                    _save_draft(page, resp)
                    report.append((page, [], [], [(t, str(e)) for t in targets]))
                    return
                if applied and not args.dry_run and not _docs_health_ok(log):
                    _restore(page, before)
                    path = _save_draft(page, resp)
                    failed += [(t, f"문서 빌드 검사 실패 — 되돌리고 초안만 {path} 에 저장")
                               for t, _ in applied]
                    applied = []
                for t, why in applied:
                    log(f"[{page}] 고침   {t}: {why}")
                for t, why in unchanged:
                    log(f"[{page}] 그대로 {t}: {why}")
                for t, why in failed:
                    log(f"[{page}] 실패   {t}: {why}")
                done = [t for t, _ in applied + unchanged]
                if done and not args.dry_run:
                    stamp(done, state, ledger, commit)
                    save_ledger(ledger)
                report.append((page, applied, unchanged, failed))

        def run_page(page, targets):
            # 같은 쪽의 묶음은 차례로 — 앞 묶음이 고친 본문을 다음 묶음이 읽어야 한다.
            for batch in _batches(page, targets, state, source):
                with mutex:
                    log(f"\n== {page}: {', '.join(batch)}")
                run_batch(page, batch)

        jobs = max(1, args.jobs)
        if jobs == 1:
            for page, targets in pages.items():
                run_page(page, targets)
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=jobs) as ex:
                for fut in [ex.submit(run_page, p, t) for p, t in pages.items()]:
                    fut.result()
        if not args.dry_run and any(a for _, a, _, _ in report):
            # 절 제목이 바뀌면 AI 가 읽는 매뉴얼 색인도 어긋난다(docs-health ai-index 가 잡는다).
            gen = os.path.join(ROOT, "aot/scripts/generate_ai_doc_index.py")
            if os.path.isfile(gen):
                r = subprocess.run([sys.executable, gen], cwd=ROOT, capture_output=True, text=True)
                log("AI 매뉴얼 색인 재생성" + ("" if r.returncode == 0 else f" 실패: {r.stderr[-300:]}"))
        all_failed = [x for _, _, _, f in report for x in f]
        if all_failed and not args.dry_run:
            _record_failed(all_failed, state)
        _write_report(report, log_lines)
        n_fixed = sum(len(a) for _, a, _, _ in report)
        n_fail = sum(len(f) for _, _, _, f in report)
        _notify(f"매뉴얼 {n_fixed}절 갱신" + (f", {n_fail}절 실패" if n_fail else "")
                + " — 작업 폴더에서 검토 후 커밋하세요")
        return 1 if n_fail else 0


FAILED_PATH = os.path.join(STATE_DIR, "failed.json")


def _load_failed():
    try:
        with open(os.path.join(ROOT, FAILED_PATH), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _record_failed(failed_targets, state):
    """실패한 대상을 그때의 코드 지문과 함께 적는다 — autodraft 는 코드가 다시
    바뀌기 전까지 같은 대상을 재시도하지 않는다(커밋마다 claude 를 헛돌리지 않게)."""
    data = _load_failed()
    for t, why in failed_targets:
        if t in state:
            data[t] = {"code": state[t]["code"], "reason": why[:300],
                       "at": datetime.datetime.now().isoformat(timespec="seconds")}
    os.makedirs(os.path.join(ROOT, STATE_DIR), exist_ok=True)
    with open(os.path.join(ROOT, FAILED_PATH), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _save_draft(page, resp):
    d = os.path.join(ROOT, STATE_DIR, "drafts")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, page.replace("/", "__") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(resp, f, ensure_ascii=False, indent=2)
    return os.path.relpath(path, ROOT)


def _write_report(report, log_lines):
    d = os.path.join(ROOT, STATE_DIR)
    os.makedirs(d, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"# 매뉴얼 자동 갱신 {now}", ""]
    for page, applied, unchanged, failed in report:
        out.append(f"## {page}")
        out += [f"- 고침 `{t}` — {w}" for t, w in applied]
        out += [f"- 그대로 `{t}` — {w}" for t, w in unchanged]
        out += [f"- 실패 `{t}` — {w}" for t, w in failed]
        out.append("")
    out += ["## 로그", "```", *log_lines, "```", ""]
    with open(os.path.join(d, "last-run.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def _notify(msg):
    if sys.platform != "darwin" or os.environ.get("AOT_MANUAL_SYNC_NOTIFY") == "0":
        return
    if not shutil.which("osascript"):
        return
    safe = msg.replace('"', "'")
    subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "AoT 매뉴얼"'],
                   capture_output=True)


def _git_dir_busy():
    gd = _git("rev-parse", "--git-dir").stdout.strip()
    gd = gd if os.path.isabs(gd) else os.path.join(ROOT, gd)
    return any(os.path.exists(os.path.join(gd, n)) for n in
               ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"))


def cmd_autodraft(args):
    """post-commit 훅: 오래된 절이 있으면 update 를 백그라운드로 띄우고 바로 돌아온다."""
    if os.environ.get("AOT_SKIP_MANUAL_AUTODRAFT") or os.environ.get("CI"):
        return 0
    if _git_dir_busy():
        return 0  # 리베이스·머지 도중의 커밋마다 돌지 않는다
    exe = os.environ.get("AOT_MANUAL_SYNC_CLAUDE", "claude")
    if not shutil.which(exe):
        return 0
    try:
        state, _ = compute_state(Source("worktree"))
    except Exception as e:  # noqa: BLE001 — 훅은 커밋을 방해하지 않는다
        print(f"[manual-sync] 상태 계산 실패: {e}")
        return 0
    failed = _load_failed()
    todo = [t for t, s in state.items()
            if s["status"] != "ok" and not s["problems"]
            and failed.get(t, {}).get("code") != s["code"]]
    if not todo:
        return 0
    lock = os.path.join(ROOT, STATE_DIR, "lock")
    if os.path.exists(lock):
        print("[manual-sync] 이미 갱신이 진행 중이라 이번 커밋은 건너뜁니다.")
        return 0
    d = os.path.join(ROOT, STATE_DIR)
    os.makedirs(d, exist_ok=True)
    logpath = os.path.join(d, datetime.datetime.now().strftime("run-%Y%m%d-%H%M%S.log"))
    with open(logpath, "w") as logf:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "update"],
                         cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True, env=_child_env())
    print(f"[manual-sync] 매뉴얼 {len(todo)}절을 백그라운드에서 갱신합니다 "
          f"→ {os.path.relpath(logpath, ROOT)}")
    return 0


def cmd_precommit(args):
    """pre-commit 훅: 이번 커밋(인덱스) 기준 상태를 알리기만 한다. 항상 0."""
    if os.environ.get("AOT_SKIP_MANUAL_SYNC_CHECK"):
        return 0
    try:
        state, orphans = compute_state(Source("index"))
    except Exception as e:  # noqa: BLE001
        print(f"[manual-sync] 상태 계산 실패(무시): {e}")
        return 0
    staged = set(_git("diff", "--cached", "--name-only").stdout.split())
    touched = {t: s for t, s in state.items()
               if any(u.path in staged for u in s["units"].values())}
    broken = {t: s for t, s in state.items() if s["problems"]}
    pending = {t: s for t, s in touched.items() if s["status"] != "ok"}
    if not (pending or broken):
        return 0
    print()
    print("[manual-sync] 이 커밋이 매뉴얼 절의 코드를 바꿉니다 — 차단은 아닙니다.")
    for t, s in pending.items():
        print(f"  [{STATUS_KO[s['status']]}] {t}")
    for t, s in broken.items():
        for p in s["problems"]:
            print(f"  ! {t}: {p}")
    if pending:
        print("  커밋 직후 백그라운드에서 claude 가 초안을 씁니다(AOT_SKIP_MANUAL_AUTODRAFT=1 로 끔).")
        print("  문서와 무관한 변경이면: python3 aot/scripts/manual_sync.py stamp <대상>")
    print()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status", help="연결된 절의 상태")
    p.add_argument("--source", default="worktree", help="worktree | index | 커밋/브랜치")
    p.add_argument("--strict", action="store_true", help="오래됨·미대조·링크 오류가 있으면 1")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("stamp", help="문서가 코드와 맞다고 장부에 기록")
    p.add_argument("targets", nargs="*")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("update", help="오래된 절을 claude 로 다시 쓰기")
    p.add_argument("targets", nargs="*")
    p.add_argument("--dry-run", action="store_true", help="파일·장부를 바꾸지 않음")
    p.add_argument("--show-prompt", action="store_true")
    p.add_argument("--jobs", type=int, default=1, help="쪽 단위로 동시에 돌릴 claude 수(기본 1)")
    sub.add_parser("autodraft", help="post-commit 훅 진입점")
    sub.add_parser("precommit", help="pre-commit 훅 진입점")
    args = ap.parse_args(argv)
    if args.cmd == "stamp" and not (args.all or args.targets):
        ap.error("대상을 적거나 --all 을 주세요")
    return {"status": cmd_status, "stamp": cmd_stamp, "update": cmd_update,
            "autodraft": cmd_autodraft, "precommit": cmd_precommit}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
