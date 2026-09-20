#!/usr/bin/env python3
"""패키지 간 import 방향 검사기 — ARCHITECTURE.md §4 의존 방향 규칙을 지킨다.

`aot_flask` 는 데몬을 RPC 로만 부르고, 데몬 쪽 패키지(`controllers`·
`functions`·`inputs`·`outputs`·`actions`)는 Flask 를 모르고, MCP 서버는
in-app 어시스턴트(`ai/`)에 기대지 않고, DB 모델은 앱 계층을 모른다 —
ARCHITECTURE.md §4 의 규칙 1~4. 이 경계가 무너지면 daemon 을 web 프로세스
없이 못 띄우거나, 모델을 import 하는 순간 Flask 앱 컨텍스트가 딸려 오는
식으로 프로세스 분리가 이름뿐이게 된다.

오늘 이 규칙은 100% 지켜지고 있지 않다(§4 본문에 적힌 대로). 이 검사기는
지금 있는 위반을 전부 고치라고 막는 게 아니라 — 그러면 아무도 못 켠다 —
`import_layers_baseline.txt` 에 적힌 것만 눈감고 **새 위반**만 막는다.
기존 위반을 줄이고 싶으면 코드를 고치고 나서 baseline 에서 그 줄을 지운다
(반대로 하면 안 된다 — 코드는 그대로 두고 baseline 만 지우면 다음 실행에서
바로 실패한다).

검사 5종(rule id → 대상 → 금지 import):
  web-no-controllers  aot/aot_flask/**                              → aot.controllers
  daemon-no-flask     aot/{controllers,functions,inputs,outputs,actions}/** → flask, aot.aot_flask
  mcp-no-ai           aot/mcp_server/**, aot/aot_mcp_server.py       → aot.ai
  tools-no-ai         aot/tools/**                                   → aot.ai
  models-no-app       aot/databases/models/**                       → aot.aot_flask.routes,
                                                                        aot.aot_flask.utils, aot.ai,
                                                                        aot.services, aot.controllers,
                                                                        aot.functions

판정은 `ast` 로 각 파일을 파싱해 모든 `import`/`from ... import`(함수 안
지연 import 포함)를 본다. 상대 import(`from . import x`)는 항상 대상 밖 —
패키지 경계를 벗어날 수 없기 때문이다. 모듈명이 금지 접두와 정확히 같거나
`접두.` 로 시작하면 위반이다(예: 금지가 `flask` 면 `flask` 와
`flask.json` 은 걸리고, `flask_babel` 은 안 걸린다 — 별개 패키지다).
대상 경로 아래의 `tests` 디렉터리는 제외한다(테스트는 경계 검증을 위해
반대편을 import 할 수 있어야 한다). 파싱에 실패한 파일은 경고만 남기고
건너뛴다.

사용:
    python3 aot/scripts/check_import_layers.py                  # 워킹트리
    python3 aot/scripts/check_import_layers.py --staged         # 인덱스 (pre-commit 훅)
    python3 aot/scripts/check_import_layers.py --json           # 기계 판독
    python3 aot/scripts/check_import_layers.py --quiet          # 요약만
    python3 aot/scripts/check_import_layers.py --write-baseline # baseline 갱신

`--write-baseline` 은 지금 워킹트리의 위반을 그대로 baseline 파일에 다시
쓴다. **CI 는 이 옵션을 절대 쓰지 않는다** — CI 가 쓰면 새 위반이 생길
때마다 baseline 이 따라 늘어나 검사가 항상 통과하는 장식이 된다. 이
옵션은 사람이 로컬에서, "이 위반들은 지금 시점의 사실이다" 라고 확인한
뒤에만 쓴다.

종료 코드 0 = 새 위반 없음(해소된 baseline 항목 경고는 있을 수 있음),
1 = 새 위반 발견, 2 = 검사 자체 실패.

`--staged` 는 check_alembic_head.py 와 같은 방식으로 인덱스에서 읽는다
(`git ls-files --cached` 로 추적 파일을 나열하고 `git show :path` 로
내용을 읽는다) — 워킹트리에 손대지 않은 채 "이 커밋이 만드는 스냅샷"을
검사한다.

@phase active
@stability stable
"""
import argparse
import ast
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
BASELINE_PATH = os.path.join('aot', 'scripts', 'import_layers_baseline.txt')

# 각 규칙: 대상 경로(디렉터리는 재귀, .py 로 끝나면 단일 파일) → 금지 import 접두.
RULES = [
    {
        'id': 'web-no-controllers',
        'paths': ['aot/aot_flask'],
        'forbidden': ['aot.controllers'],
    },
    {
        'id': 'daemon-no-flask',
        'paths': ['aot/controllers', 'aot/functions', 'aot/inputs',
                  'aot/outputs', 'aot/actions'],
        'forbidden': ['flask', 'aot.aot_flask'],
    },
    {
        'id': 'mcp-no-ai',
        'paths': ['aot/mcp_server', 'aot/aot_mcp_server.py'],
        'forbidden': ['aot.ai'],
    },
    {
        'id': 'tools-no-ai',
        'paths': ['aot/tools'],
        'forbidden': ['aot.ai'],
    },
    {
        'id': 'models-no-app',
        'paths': ['aot/databases/models'],
        'forbidden': ['aot.aot_flask.routes', 'aot.aot_flask.utils',
                      'aot.ai', 'aot.services', 'aot.controllers',
                      'aot.functions'],
    },
]


class CheckError(Exception):
    """검사 자체를 수행할 수 없음 (종료 코드 2)."""


# ── 소스 읽기 ────────────────────────────────────────────────────────────────
# 워킹트리와 인덱스를 같은 인터페이스로 다룬다. aot 패키지를 import 하지
# 않는다 — 훅에서 도는 검사가 앱 전체 import 사슬에 묶이지 않도록.

def _git(args):
    return subprocess.run(['git'] + args, cwd=ROOT, capture_output=True, text=True)


def _read_worktree(rel_path):
    full = os.path.join(ROOT, rel_path)
    if not os.path.isfile(full):
        return None
    with open(full, encoding='utf-8') as fh:
        return fh.read()


def _read_index(rel_path):
    res = _git(['show', ':' + rel_path.replace(os.sep, '/')])
    return res.stdout if res.returncode == 0 else None


def _in_tests_dir(rel_path):
    return 'tests' in rel_path.replace(os.sep, '/').split('/')


_TRACKED_CACHE = None


def _tracked_paths():
    """저장소가 추적하는 .py 경로 집합(슬래시). git 을 못 쓰면 None.

    **추적되지 않는 파일은 검사하지 않는다.** 사용자가 자기 설치본에만 두는
    확장(예: 비공개로만 배포하는 출력 모듈)이 `aot/outputs/custom_outputs/`
    같은 자리에 놓이는데, 그것까지 세면 저장소에 없는 파일 때문에 검사가
    빨간불이 된다(2026-09-20 실제로 겪음: 추적되지 않는 로컬 출력 모듈 하나가
    daemon-no-flask 위반으로 잡혀 pytest 경로만 실패했다). CI 와 `--staged` 는
    애초에 추적 파일만 보므로 이 필터로 잃는 검사는 없다.
    """
    global _TRACKED_CACHE
    if _TRACKED_CACHE is None:
        res = _git(['ls-files', '--cached'])
        _TRACKED_CACHE = (set(res.stdout.splitlines())
                          if res.returncode == 0 else set())
    return _TRACKED_CACHE


def _list_worktree_files(rel_path):
    """rel_path 아래 **추적된** .py 파일 목록(tests/·__pycache__ 제외)."""
    tracked = _tracked_paths()
    full = os.path.join(ROOT, rel_path)
    if rel_path.endswith('.py'):
        rel = rel_path.replace(os.sep, '/')
        return [rel] if os.path.isfile(full) and rel in tracked else []
    if not os.path.isdir(full):
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(full):
        dirnames[:] = [d for d in dirnames if d not in ('tests', '__pycache__')]
        for name in filenames:
            if not name.endswith('.py'):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
            rel = rel.replace(os.sep, '/')
            if rel in tracked:
                out.append(rel)
    return sorted(out)


def _list_index_files(rel_path):
    """rel_path 아래 추적된 .py 파일 목록(tests/ 제외), 인덱스 기준."""
    res = _git(['ls-files', '--cached', rel_path])
    if res.returncode != 0:
        raise CheckError('git ls-files 실패 — 저장소 안에서 실행하세요.')
    out = [p for p in res.stdout.splitlines()
           if p.endswith('.py') and not _in_tests_dir(p)]
    return sorted(out)


def _list_files(rel_path, staged):
    files = _list_index_files(rel_path) if staged else _list_worktree_files(rel_path)
    return [f for f in files if not _in_tests_dir(f)]


# ── import 추출 ──────────────────────────────────────────────────────────────

def _imported_modules(text, path):
    """(module, ) 튜플의 리스트 — 상대 import 는 제외, 파싱 실패 시 None."""
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as err:
        print(f'경고: {path} 파싱 실패, 건너뜁니다 ({err})', file=sys.stderr)
        return None
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # 상대 import — 패키지 경계를 못 벗어난다.
            if node.module:
                modules.append(node.module)
    return modules


def _violates(module, forbidden_prefix):
    return module == forbidden_prefix or module.startswith(forbidden_prefix + '.')


# ── 검사 ─────────────────────────────────────────────────────────────────────

def find_violations(staged=False):
    """{(rule_id, path, module)} 위반 집합."""
    read = _read_index if staged else _read_worktree
    violations = set()
    for rule in RULES:
        files = set()
        for p in rule['paths']:
            files.update(_list_files(p, staged))
        for path in sorted(files):
            text = read(path)
            if text is None:
                continue
            modules = _imported_modules(text, path)
            if modules is None:
                continue
            for module in modules:
                for forbidden in rule['forbidden']:
                    if _violates(module, forbidden):
                        violations.add((rule['id'], path, module))
    return violations


def load_baseline():
    full = os.path.join(ROOT, BASELINE_PATH)
    if not os.path.isfile(full):
        return set()
    baseline = set()
    with open(full, encoding='utf-8') as fh:
        for line in fh:
            line = line.rstrip('\n')
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) != 3:
                raise CheckError(f'{BASELINE_PATH}: 형식이 잘못된 줄 — {line!r}')
            baseline.add(tuple(parts))
    return baseline


def write_baseline(violations):
    full = os.path.join(ROOT, BASELINE_PATH)
    lines = sorted('\t'.join(v) for v in violations)
    with open(full, 'w', encoding='utf-8') as fh:
        for line in lines:
            fh.write(line + '\n')
    return len(lines)


def run_checks(staged=False):
    """(new, resolved) — new 는 baseline 에 없는 위반, resolved 는 이제 위반이 아닌 baseline 항목."""
    current = find_violations(staged=staged)
    baseline = load_baseline()
    new = current - baseline
    resolved = baseline - current
    return new, resolved


def _fmt(v):
    rule_id, path, module = v
    return f'  [{rule_id}] {path} → {module}'


def main():
    ap = argparse.ArgumentParser(
        description='패키지 간 import 방향 검사 (ARCHITECTURE.md §4)')
    ap.add_argument('--staged', action='store_true',
                     help='워킹트리 대신 인덱스(스테이지된 내용)를 검사')
    ap.add_argument('--json', action='store_true', help='기계 판독용 JSON 출력')
    ap.add_argument('--quiet', action='store_true', help='요약만 출력')
    ap.add_argument('--write-baseline', action='store_true',
                     help='현재 위반을 baseline 파일에 다시 씀 — CI 에서는 절대 쓰지 말 것')
    args = ap.parse_args()

    try:
        if args.write_baseline:
            current = find_violations(staged=args.staged)
            n = write_baseline(current)
            if not args.quiet:
                print(f'{BASELINE_PATH} 를 위반 {n}건으로 다시 썼습니다.')
            return 0

        new, resolved = run_checks(staged=args.staged)
    except CheckError as err:
        if args.json:
            print(json.dumps({'ok': False, 'error': str(err)}, ensure_ascii=False))
        else:
            print(f'검사 실패: {err}', file=sys.stderr)
        return 2

    scope = '인덱스' if args.staged else '워킹트리'

    if args.json:
        print(json.dumps({
            'ok': not new,
            'scope': scope,
            'new_violations': sorted(list(v) for v in new),
            'resolved_baseline_entries': sorted(list(v) for v in resolved),
        }, ensure_ascii=False, indent=1))
        return 1 if new else 0

    if resolved and not args.quiet:
        print(f'해소됨 — baseline 에서 지울 것 ({scope}, {len(resolved)}건):')
        for v in sorted(resolved):
            print(_fmt(v))

    if not new:
        if not args.quiet:
            print(f'OK: {scope} 에 새 import 방향 위반 없음.')
        else:
            print('OK: 0건')
        return 0

    print(f'새 import 방향 위반 {len(new)}건 ({scope}, {BASELINE_PATH} 에 없음):')
    for v in sorted(new):
        print(_fmt(v))
    if not args.quiet:
        print(f'  → 되돌릴 수 없다면 검토 후 --write-baseline 으로 새 사실을 반영하세요.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
