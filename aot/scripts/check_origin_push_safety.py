#!/usr/bin/env python3
# coding=utf-8
"""origin(GitHub) 에는 스쿼시 동기화 커밋만 올라가야 한다 — pre-push 훅의 실제 검사.

2026-08-15 사고: 로컬 main(Gitea 용 전체 상세 히스토리)에서 만든 태그를 그대로
`git push origin <tag>` 로 올렸다. GitHub 의 main 은 스쿼시된 별도 이력이라,
그 태그가 가리키는 로컬 커밋의 조상 828개(2026-05-14 최초 커밋부터, 과거
STATS_PASSWORD 유출 구간 포함)가 그대로 origin 으로 전송됐다.

**태그(참조)를 지워도 객체는 안 지워진다.** 사고 직후 실측: 태그 삭제 후에도
`git fetch origin <그 커밋 해시>` 가 여전히 성공했고 828개 커밋 전부 받아졌다
— 해시를 아는 사람이면 지금도 받을 수 있다는 뜻이다. 그래서 이 검사는
"지운 뒤 확인"이 아니라 **push 되기 전에 막는 것**을 목표로 한다.

검사는 두 겹이다. **모양**(스쿼시 커밋 1개인가)과 **내용**(그 트리에 공개하면 안 되는
것이 들어 있지 않은가). 모양만 보던 때는, 절차를 거치지 않고 손으로 commit-tree 한
트리를 그대로 올려도 통과했다 — JS 원본 전체가 그렇게 나갈 수 있었다.

origin 에 실제로 필요한 것은 매번 정확히 하나의 커밋뿐이다 —
`git commit-tree <tree> -p origin/main -m ...` 로 만든 스쿼시 동기화 커밋
(CLAUDE.md 'Git 전략 > origin(GitHub) 동기화 절차'). 이 스크립트는 그
불변식을 push 시점에 강제한다: origin 으로 향하는 모든 참조(브랜치·태그)는
(a) origin/main 에 이미 있는 커밋을 가리키거나, (b) origin/main 을 유일한
부모로 갖는 새 커밋을 정확히 1개만 추가해야 한다. 그 밖의 모든 push 는
로컬 상세 히스토리가 새는 것으로 간주해 막는다.

    git push 훅 안에서: python3 check_origin_push_safety.py <remote_name> <remote_url>
        (stdin 으로 git 표준 pre-push 프로토콜 — "local-ref local-sha remote-ref remote-sha" 줄들)
    수동 테스트:        python3 check_origin_push_safety.py --simulate-sha <sha> \
                            --simulate-remote-main <sha> [--expect-block]

종료 0=정상(또는 대상 아님), 1=차단, 2=검사 실패(원격 조회 실패 등 — 열어
둔다, 네트워크 장애로 정당한 push 가 막히면 안 된다).
"""
import argparse
import subprocess
import sys

GITHUB_MARKERS = ('github.com/AoT-inc/AoT', 'github.com:AoT-inc/AoT')
ZERO_SHA = '0' * 40


def _run(args):
    return subprocess.run(args, capture_output=True, text=True)


def is_github_origin(remote_url):
    return any(m in (remote_url or '') for m in GITHUB_MARKERS)


def fetch_remote_main_sha(remote_url):
    r = _run(['git', 'ls-remote', remote_url, 'refs/heads/main'])
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.split()[0]


def ensure_local_object(sha):
    """원격 main 커밋을 로컬에서 조사할 수 있도록, 없으면 얕게 가져온다."""
    r = _run(['git', 'cat-file', '-e', sha + '^{commit}'])
    if r.returncode == 0:
        return True
    r = _run(['git', 'fetch', '--depth=1', 'origin', sha])
    return r.returncode == 0


# ── 내용 검사: 공개 트리에 들어가면 안 되는 것 ────────────────────────────
# 공개본에는 빌드 산출물만 올린다(정책: .local/plans/2609_github_js_publish_policy.md).
# 목록(aot/scripts/publish/exclude.txt)에만 기대면 목록이 낡는 순간 뚫리므로,
# 목록과 무관하게 성립하는 **구조 규칙**을 먼저 본다.
JS_ROOT = 'aot/aot_flask/static/js/'

# 산출물·외부 라이브러리라 공개해도 되는 것들.
_ALLOWED_PREFIX = (JS_ROOT + 'dist/', JS_ROOT + 'geo/dist/',
                   JS_ROOT + 'vendor/', JS_ROOT + 'notes/')
_ALLOWED_EXACT = {
    # three.js 애드온(각 라이브러리 라이선스라 손대지 않는다)
    JS_ROOT + 'widgets/AoT_facility/GLTFLoader.js',
    JS_ROOT + 'widgets/AoT_facility/OrbitControls.js',
    JS_ROOT + 'widgets/AoT_facility/three-gltf-exporter.js',
    JS_ROOT + 'widgets/AoT_facility/three-mesh-bvh.js',
}


def _tree_paths(sha):
    r = _run(['git', 'ls-tree', '-r', '--name-only', sha])
    if r.returncode != 0:
        return None
    return r.stdout.splitlines()


def _is_public_js_source(path):
    """공개하면 안 되는 AoT 자작 JS 원본인가."""
    if not path.startswith(JS_ROOT) or not path.endswith('.js'):
        return False
    if path.startswith(_ALLOWED_PREFIX) or path in _ALLOWED_EXACT:
        return False
    if path.endswith('.min.js'):
        return False
    return True


def check_tree_contents(sha):
    """(통과여부, 사유) — 트리에 JS 원본·소스맵·제외 목록의 경로가 있으면 False."""
    paths = _tree_paths(sha)
    if paths is None:
        return None, 'ls-tree 실패'

    offenders = [p for p in paths if _is_public_js_source(p)]
    offenders += [p for p in paths
                  if p.startswith(JS_ROOT) and p.endswith('.map')
                  and not p.startswith(JS_ROOT + 'vendor/')]

    # 보조: 목록에 적힌 것이 남아 있으면 그것도 잡는다(빌드 도구·테스트 등 .js 가 아닌 것들).
    try:
        with open('aot/scripts/publish/exclude.txt', encoding='utf-8') as fh:
            listed = {l.strip() for l in fh
                      if l.strip() and not l.lstrip().startswith('#')}
        present = set(paths)
        offenders += sorted(listed & present - set(offenders))
    except OSError:
        pass  # 목록이 없으면 구조 규칙만으로 판단한다

    if offenders:
        uniq = sorted(set(offenders))
        return False, ('공개하면 안 되는 파일 %d개가 트리에 있습니다(예: %s).'
                       % (len(uniq), ', '.join(uniq[:3])))
    return True, None


def check_ref_update(local_sha, remote_main_sha):
    """(통과여부, 사유) — 통과여부는 True/False/None(검사 자체 실패)."""
    if local_sha == ZERO_SHA:
        return True, None  # 삭제 push

    r = _run(['git', 'merge-base', '--is-ancestor', local_sha, remote_main_sha])
    if r.returncode == 0:
        return True, None  # 이미 origin 에 있는 커밋을 재사용(태그 등) — 정상
    if r.returncode not in (0, 1):
        return None, 'merge-base 검사 실패: %s' % r.stderr.strip()

    r = _run(['git', 'rev-list', local_sha, '--not', remote_main_sha])
    if r.returncode != 0:
        return None, 'rev-list 실패: %s' % r.stderr.strip()
    new_commits = [c for c in r.stdout.splitlines() if c]

    if len(new_commits) == 1:
        r2 = _run(['git', 'rev-parse', new_commits[0] + '^'])
        parent = r2.stdout.strip() if r2.returncode == 0 else None
        if parent == remote_main_sha:
            return True, None  # 정상: commit-tree 스쿼시 동기화 커밋 1개

    return False, (
        '%s 가(이) origin/main 스쿼시 이력 밖의 커밋을 %d개 담고 있습니다.'
        % (local_sha[:12], len(new_commits)))


def _report_block(local_ref, local_sha, reason):
    print(file=sys.stderr)
    print('차단: %s' % local_ref, file=sys.stderr)
    print('  %s' % reason, file=sys.stderr)
    print('  대상 커밋: %s' % local_sha, file=sys.stderr)
    print('  origin 에는 aot/scripts/publish/publish_public.sh 가 만든', file=sys.stderr)
    print('  스쿼시 동기화 커밋만 올릴 것(모양도 내용도 그 절차가 맞춰 준다).', file=sys.stderr)
    print('  정말 의도한 것이면: AOT_SKIP_ORIGIN_HISTORY_CHECK=1 git push ...', file=sys.stderr)
    print(file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('remote_name', nargs='?', default=None)
    parser.add_argument('remote_url', nargs='?', default=None)
    parser.add_argument('--simulate-sha', help='테스트용: stdin 대신 이 sha 하나만 검사')
    parser.add_argument('--simulate-remote-main', help='테스트용: 원격 조회를 건너뛰고 이 sha 를 remote main 으로 쓴다')
    parser.add_argument('--check-tree', metavar='TREEISH',
                        help='내용 검사만 단독 수행(공개 절차가 push 前에 쓴다)')
    args = parser.parse_args()

    if args.check_tree:
        ok, reason = check_tree_contents(args.check_tree)
        if ok is None:
            print('경고: 내용 검사 실패(%s).' % reason, file=sys.stderr)
            return 2
        if not ok:
            print('차단: %s' % reason, file=sys.stderr)
            return 1
        print('OK: 트리에 JS 원본·소스맵·제외 대상이 없습니다.')
        return 0

    simulating = bool(args.simulate_sha)

    if not simulating:
        if not is_github_origin(args.remote_url):
            print('OK: GitHub(origin) 대상이 아님 — 검사 생략.')
            return 0

        remote_main = args.simulate_remote_main or fetch_remote_main_sha(args.remote_url)
        if remote_main is None:
            print('경고: origin 의 main 을 조회하지 못해 검사를 건너뜁니다.', file=sys.stderr)
            return 2
        if not ensure_local_object(remote_main):
            print('경고: origin/main 커밋을 로컬로 가져오지 못해 검사를 건너뜁니다.', file=sys.stderr)
            return 2
    else:
        remote_main = args.simulate_remote_main
        if not remote_main:
            print('오류: --simulate-sha 는 --simulate-remote-main 과 함께 써야 합니다.', file=sys.stderr)
            return 2

    if simulating:
        updates = [('simulate', args.simulate_sha, 'refs/heads/main', ZERO_SHA)]
    else:
        updates = []
        for raw in sys.stdin:
            parts = raw.split()
            if len(parts) != 4:
                continue
            updates.append(tuple(parts))
        if not updates:
            print('OK: 검사할 참조 업데이트가 없습니다.')
            return 0

    blocked = False
    for local_ref, local_sha, _remote_ref, _remote_sha in updates:
        ok, reason = check_ref_update(local_sha, remote_main)
        if ok is None:
            print('경고: %s 검사 실패(%s) — 통과시킵니다.' % (local_ref, reason), file=sys.stderr)
        elif not ok:
            blocked = True
            _report_block(local_ref, local_sha, reason)
            continue

        if local_sha == ZERO_SHA:
            continue
        ok2, reason2 = check_tree_contents(local_sha)
        if ok2 is None:
            print('경고: %s 내용 검사 실패(%s) — 통과시킵니다.' % (local_ref, reason2), file=sys.stderr)
        elif not ok2:
            blocked = True
            _report_block(local_ref, local_sha, reason2)

    if blocked:
        return 1
    print('OK: origin 으로 향하는 참조가 스쿼시 이력 안에 있고, 트리에 원본이 없습니다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
