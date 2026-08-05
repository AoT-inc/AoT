#!/usr/bin/env python3
"""Alembic 리비전 체인 검사기 — 체인 무결성과 ALEMBIC_VERSION 일치를 본다.

업그레이드는 `head` 가 아니라 `config.ALEMBIC_VERSION` 을 목표로 실행된다
(폐기된 p5 계보가 두 번째 head 로 남아 있어 'head' 를 쓰면 "Multiple head
revisions" 로 실패하기 때문 — alembic_upgrade_db() 주석 참조). 그래서 새
마이그레이션을 추가하고 이 상수를 올리지 않으면 **그 마이그레이션은 영원히
실행되지 않는다.** 에러도 경고도 없다: 앱은 "up to date" 라고 로그를 남기고
정상 기동하며, 모델·라우트는 존재하지 않는 컬럼을 참조한 채로 돈다.

이 사고는 두 번 났다.
  - 2026-08-03 `6550f41` : p6_21·p6_22 자동 실행 누락
  - 2026-08-05 v26.08.2  : p6_25(battery_type) 누락 — 릴리스 점검 중 사람이 발견

두 번 다 사람이 눈으로 찾았다. 같은 검사가 test_env_summary.py 에 이미 있었지만
테스트 스위트는 커밋 시점에 돌지 않아 잡히지 않았다 — 이 스크립트는 그 검사를
훅과 CI 가 부를 수 있는 자리로 옮긴 것이고, 테스트는 이제 이 모듈을 호출한다
(구현은 여기 하나뿐이다).

검사 4종:
  single-root      뿌리(down_revision=None)가 베이스라인 하나뿐인가
  no-dangling      down_revision 이 실재하는 리비전을 가리키는가
  single-head      아무도 가리키지 않는 리비전(head)이 하나뿐인가
  constant-matches ALEMBIC_VERSION 이 그 head 와 같은가

사용:
    python3 aot/scripts/check_alembic_head.py            # 워킹트리
    python3 aot/scripts/check_alembic_head.py --staged   # 인덱스 (pre-commit 훅)
    python3 aot/scripts/check_alembic_head.py --json     # 기계 판독
    python3 aot/scripts/check_alembic_head.py --quiet    # 요약만

종료 코드 0 = 정상, 1 = 문제 발견, 2 = 검사 실패.

`--staged` 는 인덱스에서 읽는다. 워킹트리를 보면 "마이그레이션만 stage 하고
상수 수정은 stage 하지 않은" 커밋을 통과시켜 버린다 — 그게 바로 막으려는
드리프트다.

@phase active
@stability stable
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
VERSIONS_DIR = os.path.join('alembic_db', 'alembic', 'versions')
CONFIG_PATH = os.path.join('aot', 'config', '__init__.py')

# 26.06.0 재베이스라인에서 115개 리비전을 접어 만든 단일 뿌리.
BASELINE_REVISION = 'p6_00_rebaseline_20260720'

_REVISION_RE = re.compile(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", re.M)
_DOWN_REVISION_RE = re.compile(
    r"^down_revision\s*=\s*(?:['\"]([^'\"]+)['\"]|None)", re.M)
_ALEMBIC_VERSION_RE = re.compile(
    r"^ALEMBIC_VERSION\s*=\s*['\"]([^'\"]+)['\"]", re.M)


class CheckError(Exception):
    """검사 자체를 수행할 수 없음 (종료 코드 2)."""


# ── 소스 읽기 ────────────────────────────────────────────────────────────────
# 워킹트리와 인덱스를 같은 인터페이스로 다룬다. aot.config 를 import 하지
# 않는다 — 훅에서 도는 검사가 앱 전체 import 사슬(번역 카탈로그·sys.path 조작)
# 에 묶이면 느려지고, config 가 깨졌을 때 검사기까지 같이 죽는다.

def _git(args):
    return subprocess.run(['git'] + args, cwd=ROOT, capture_output=True, text=True)


def _read_worktree(rel_path):
    full = os.path.join(ROOT, rel_path)
    if not os.path.exists(full):
        return None
    with open(full, encoding='utf-8') as fh:
        return fh.read()


def _read_index(rel_path):
    res = _git(['show', ':' + rel_path.replace(os.sep, '/')])
    return res.stdout if res.returncode == 0 else None


def _list_worktree_versions():
    d = os.path.join(ROOT, VERSIONS_DIR)
    if not os.path.isdir(d):
        raise CheckError(f'리비전 디렉터리가 없습니다: {VERSIONS_DIR}')
    return sorted(os.path.join(VERSIONS_DIR, f) for f in os.listdir(d)
                  if f.endswith('.py') and f != '__init__.py')


def _list_index_versions():
    res = _git(['ls-files', '--cached', VERSIONS_DIR + '/*.py'])
    if res.returncode != 0:
        raise CheckError('git ls-files 실패 — 저장소 안에서 실행하세요.')
    return sorted(p for p in res.stdout.splitlines()
                  if p.endswith('.py') and not p.endswith('__init__.py'))


# ── 체인 구성 ────────────────────────────────────────────────────────────────

def revision_chain(staged=False):
    """{revision: down_revision} — down_revision 이 None 이면 뿌리."""
    read = _read_index if staged else _read_worktree
    paths = _list_index_versions() if staged else _list_worktree_versions()
    chain, problems = {}, []
    for path in paths:
        text = read(path)
        if text is None:
            continue
        name = os.path.basename(path)
        rev = _REVISION_RE.search(text)
        down = _DOWN_REVISION_RE.search(text)
        if not rev:
            problems.append(f'{name}: revision 식별자를 찾을 수 없습니다')
            continue
        if not down:
            problems.append(f'{name}: down_revision 식별자를 찾을 수 없습니다')
            continue
        if rev.group(1) in chain:
            problems.append(f'{name}: revision 이 중복됩니다 — {rev.group(1)}')
            continue
        chain[rev.group(1)] = down.group(1)   # 'None' 리터럴이면 group(1) 이 None
    return chain, problems


def chain_heads(chain):
    parents = {down for down in chain.values() if down is not None}
    return sorted(rev for rev in chain if rev not in parents)


def alembic_version_constant(staged=False):
    read = _read_index if staged else _read_worktree
    text = read(CONFIG_PATH)
    if text is None:
        raise CheckError(f'{CONFIG_PATH} 를 읽을 수 없습니다.')
    m = _ALEMBIC_VERSION_RE.search(text)
    if not m:
        raise CheckError(
            f'{CONFIG_PATH} 에서 ALEMBIC_VERSION 을 찾을 수 없습니다 — '
            '상수 이름이나 형식이 바뀌었다면 이 검사기도 함께 고쳐야 합니다.')
    return m.group(1)


# ── 검사 ─────────────────────────────────────────────────────────────────────

def run_checks(staged=False):
    """[{kind, message, hint}] — 비어 있으면 정상."""
    chain, findings_raw = revision_chain(staged=staged)
    findings = [{'kind': 'unparsable', 'message': m, 'hint': ''}
                for m in findings_raw]

    if not chain:
        raise CheckError(f'{VERSIONS_DIR} 에 마이그레이션이 하나도 없습니다.')

    roots = sorted(rev for rev, down in chain.items() if down is None)
    if roots != [BASELINE_REVISION]:
        findings.append({
            'kind': 'single-root',
            'message': f'뿌리가 {roots} 입니다 (기대: [{BASELINE_REVISION!r}])',
            'hint': '새 마이그레이션의 down_revision 을 비워두지 않았는지 확인하세요.',
        })

    dangling = {rev: down for rev, down in chain.items()
                if down is not None and down not in chain}
    if dangling:
        findings.append({
            'kind': 'no-dangling',
            'message': f'down_revision 이 없는 리비전을 가리킵니다: {dangling}',
            'hint': '리비전 파일을 지웠다면 그것을 가리키던 자식의 down_revision 도 고치세요.',
        })

    heads = chain_heads(chain)
    if len(heads) != 1:
        findings.append({
            'kind': 'single-head',
            'message': f'head 가 {len(heads)}개입니다: {heads}',
            'hint': '두 갈래로 갈라진 마이그레이션을 한 줄로 이어 붙이세요.',
        })

    # head 가 하나일 때만 상수 비교가 의미 있다.
    if len(heads) == 1:
        constant = alembic_version_constant(staged=staged)
        if constant != heads[0]:
            findings.append({
                'kind': 'constant-matches',
                'message': (f'ALEMBIC_VERSION={constant!r} 이 체인 head '
                            f'{heads[0]!r} 와 다릅니다'),
                'hint': (f"aot/config/__init__.py 의 ALEMBIC_VERSION 을 "
                         f"'{heads[0]}' 로 올리세요 — 올리지 않으면 그 사이 "
                         f"마이그레이션이 업그레이드에서 조용히 건너뛰어집니다."),
            })

    return findings, chain, heads


def main():
    ap = argparse.ArgumentParser(
        description='Alembic 체인 무결성 + ALEMBIC_VERSION 일치 검사')
    ap.add_argument('--staged', action='store_true',
                    help='워킹트리 대신 인덱스(스테이지된 내용)를 검사')
    ap.add_argument('--json', action='store_true', help='기계 판독용 JSON 출력')
    ap.add_argument('--quiet', action='store_true', help='요약만 출력')
    args = ap.parse_args()

    try:
        findings, chain, heads = run_checks(staged=args.staged)
    except CheckError as err:
        if args.json:
            print(json.dumps({'ok': False, 'error': str(err)}, ensure_ascii=False))
        else:
            print(f'검사 실패: {err}', file=sys.stderr)
        return 2

    scope = '인덱스' if args.staged else '워킹트리'

    if args.json:
        print(json.dumps({
            'ok': not findings, 'scope': scope, 'revisions': len(chain),
            'heads': heads, 'findings': findings,
        }, ensure_ascii=False, indent=1))
        return 1 if findings else 0

    if not findings:
        if not args.quiet:
            print(f'OK: {scope} 리비전 {len(chain)}개, head={heads[0]}, '
                  f'ALEMBIC_VERSION 일치.')
        else:
            print('OK: 0건')
        return 0

    print(f'문제 {len(findings)}건 ({scope}, 리비전 {len(chain)}개):')
    for f in findings:
        print(f'  [{f["kind"]}] {f["message"]}')
        if f['hint'] and not args.quiet:
            print(f'      → {f["hint"]}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
