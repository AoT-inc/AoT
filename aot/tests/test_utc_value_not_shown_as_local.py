"""wall_to_utc 가 돌려준 UTC aware 값을 **그대로** 지역 시각처럼 isoformat/strftime/date/hour 하지 않는다.

회귀 유형(2026-11-03, screen_follow): `tz.localize(x)`(지역 시각 aware)를 `wall_to_utc(x, tz)`(UTC aware)로 바꾸면
계산(차이·timestamp·비교)은 같지만 `.isoformat()` 이 `+00:00` 으로, `.strftime('%H:%M')` 이 UTC 시각으로 바뀐다.
표시·날짜 추출은 `to_tz(값, 장소)` 를 한 번 지나야 한다. 시험이 없는 경로에서 조용히 틀리므로 소스로 막는다.

한 함수 안에서 `이름 = wall_to_utc(...)` 로 묶인 이름에 `.isoformat/.strftime/.date/.hour/.weekday/.day` 를 바로 부르면 실패.
`이름 = to_tz(이름, ...)` 처럼 다시 묶으면 통과. 한 줄 예외는 `# tz-ok: 이유`.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHOW = {'isoformat', 'strftime', 'date', 'hour', 'weekday', 'day', 'minute', 'time'}
UTC_MAKERS = {'wall_to_utc'}
LOCALIZERS = {'to_tz', 'iso_at', 'tz_of'}


def _call_name(node):
    f = getattr(node, 'func', None)
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _wraps(value, names):
    """값 식이 maker 호출로 시작해 지역화 없이 그대로 이름에 묶이는가."""
    return isinstance(value, ast.Call) and _call_name(value) in names


def _scan(path):
    src = path.read_text(encoding='utf-8')
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    hits = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        events = []                      # (lineno, kind, name)
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                n = node.targets[0].id
                if _wraps(node.value, UTC_MAKERS):
                    events.append((node.lineno, 'utc', n))
                else:
                    events.append((node.lineno, 'other', n))
            elif isinstance(node, ast.Attribute) and node.attr in SHOW and isinstance(node.value, ast.Name):
                events.append((node.lineno, 'show', node.value.id))
        state = {}
        for lineno, kind, name in sorted(events):
            if kind == 'utc':
                state[name] = True
            elif kind == 'other':
                state[name] = False
            elif state.get(name):
                if 'tz-ok' not in lines[lineno - 1]:
                    hits.append('%s:%d  %s — wall_to_utc 결과(UTC)를 지역 시각처럼 표시/날짜 추출' % (
                        path.relative_to(ROOT.parent), lineno, name))
    return hits


def test_wall_to_utc_result_is_not_shown_as_a_local_time():
    hits = []
    for p in ROOT.rglob('*.py'):
        if '/tests/' in p.as_posix() or p.name == 'timekit.py':
            continue
        hits += _scan(p)
    assert not hits, '\n' + '\n'.join(hits)


def test_scanner_catches_the_screen_follow_shape(tmp_path):
    bad = tmp_path / 'bad.py'
    bad.write_text("def f(a, tz):\n    at = wall_to_utc(a, tz)\n    return at.isoformat()\n")
    ok = tmp_path / 'ok.py'
    ok.write_text("def f(a, tz):\n    at = wall_to_utc(a, tz)\n    at = to_tz(at, tz)\n    return at.isoformat()\n")
    global ROOT
    old, ROOT = ROOT, tmp_path.parent
    try:
        assert _scan(bad) and not _scan(ok)
    finally:
        ROOT = old
