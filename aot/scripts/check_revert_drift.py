#!/usr/bin/env python3
"""되돌림 드리프트 검사기 — 방금 커밋한 것을 조용히 지우는 변경을 잡는다.

## 무엇을 잡나

**오래된 base 에서 편집한 파일이 최근 작업을 덮어쓰는 것.** 워킹트리(또는
인덱스)가 지우는 줄을 `git blame` 으로 HEAD 에서 되짚어, 그 줄을 **최근
커밋이 넣은 것**이면 의심으로 올린다.

에러가 나지 않는다는 점이 이 실패의 전부다. 파일은 문법적으로 멀쩡하고,
테스트는 지워진 기능을 안 부르니 통과하고, diff 는 정상적인 편집처럼 보인다.
지워진 쪽이 구현이 아니라 **선언·등록·문서**면 더 조용하다 — 구현과 테스트는
그대로 남아 아무도 고아가 된 줄 모른다.

2026-08-14 에 실제로 그랬다. 워킹트리의 `tool_registry.py` 가 직전 두
커밋(`6f83a31e`·`69f5e22c`)이 넣은 AI 도구 2개(`distance_between`·`nearest`)
선언과 MCP manifest 를 통째로 지우고 있었는데, 같은 커밋들이 넣은 구현 595줄 ·
테스트 500줄 · SSOT 스냅샷은 전부 그대로였다. 설계문서와 CHANGELOG 도 같은
되돌림을 갖고 있었다. 커밋했다면 구현이 고아가 되고 도구는 AI 에서 사라졌을
것이다. 그때 이것을 잡은 것은 우연히 돌려 본 `test_tool_registry_ssot` 였고,
**도구 레지스트리 밖에서 같은 일이 나면 잡을 수단이 없었다.**

## 어떻게 가르나 — "몇 줄" 이 아니라 "그 커밋의 몇 %"

최근 줄을 지우는 것 자체는 정상이다. 어제 쓴 코드를 오늘 다듬으면 당연히
어제 줄이 지워진다. 그래서 줄 수만 세면 오탐이 쏟아진다.

가르는 기준은 **한 커밋이 그 파일에 남긴 줄 중 이번에 몇 %가 사라지는가** 다.

    3줄 고침  : 그 커밋의 200줄 중 3줄  → 1.5%  → 정상(다듬기)
    되돌림    : 그 커밋의  50줄 중 44줄 → 88%   → 의심

즉 "그 커밋이 한 일이 통째로 없어지는가" 를 본다. 되돌림은 한 커밋의 기여를
집중적으로 걷어내고, 다듬기는 넓게 조금씩 건드린다.

## 오탐을 줄이려고 뺀 것

- **파일 삭제(`git rm`)는 보지 않는다.** 파일을 통째로 지우는 것은 명시적
  행위라 조용하지 않다 — 이 검사가 잡으려는 것은 내용이 소리 없이 덮이는 쪽이다.
- **빌드 산출물은 보지 않는다**(`dist/`, `static/js/notes/`). 매번 통째로
  다시 쓰이므로 blame 이 의미를 갖지 않는다. 그쪽은 `check_js_bundles.py` 담당.
- **바이너리는 보지 않는다**(`.mo` 등). 줄 개념이 없다. `.po`↔`.mo` 는
  `check_po_mo_sync.py` 담당.
- 새로 추가된 파일(A)·이름만 바뀐 파일(R)은 대상이 아니다. 지울 옛 줄이 없다.

**이 검사는 판정이 아니라 질문이다.** 되돌림과 "내가 쓴 것을 내가 다시 쓰는
것" 은 diff 만 봐서는 구분되지 않는다 — 그래서 막을 때 **어느 커밋의 무엇이
사라지는지** 를 같이 찍는다. 사람이 그것을 보고 "맞다, 다시 쓰는 중이다" 면
우회하면 된다. 목적은 결정이 아니라 **그 결정이 있었다는 사실**을 만드는 것이다.

사용:
    python3 aot/scripts/check_revert_drift.py            # 워킹트리
    python3 aot/scripts/check_revert_drift.py --staged   # 인덱스 (pre-commit 훅)
    python3 aot/scripts/check_revert_drift.py --json     # 기계 판독
    python3 aot/scripts/check_revert_drift.py --quiet    # 요약만
    python3 aot/scripts/check_revert_drift.py --days 14 --min-ratio 0.5

종료: 0=정상, 1=의심 발견, 2=검사 실패.
표준 라이브러리만 쓴다.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

# 최근으로 볼 기간(일). 이보다 오래된 커밋의 줄이 지워지는 것은 평범한 편집이다.
DEFAULT_DAYS = 7
# 이보다 적게 지워지면 보고하지 않는다 — 한두 줄은 늘 다듬는다.
DEFAULT_MIN_LINES = 12
# 한 커밋이 그 파일에 남긴 줄 중 이 비율 이상이 사라지면 의심.
DEFAULT_MIN_RATIO = 0.55
# 기여분이 **하나도 안 남고** 사라지는 경우는 신호가 더 강하므로 하한을 낮춘다.
# 부분 삭제는 "고쳐 쓰는 중" 일 수 있지만, 통째로 없어지는 것은 그 커밋이
# 한 일 자체가 사라진다는 뜻이다. 실제 사고에서 두 커밋이 각각 32줄·11줄이었고
# 둘 다 100% 였다 — 11줄짜리가 기본 하한에 걸려 안 보이면 "한 커밋만 되돌렸나"
# 로 잘못 읽힌다.
FULL_WIPE_MIN_LINES = 8

# blame 이 의미를 갖지 않는 경로(매번 통째로 재생성되는 산출물).
SKIP_PREFIXES = (
    'aot/aot_flask/static/js/dist/',
    'aot/aot_flask/static/js/geo/dist/',
    'aot/aot_flask/static/js/notes/',
)

_HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@')


def _git(args, cwd=None):
    r = subprocess.run(['git'] + args, cwd=cwd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError('git %s: %s' % (' '.join(args),
                                           r.stderr.decode('utf-8', 'replace').strip()))
    return r.stdout.decode('utf-8', 'replace')


def _repo_root():
    return _git(['rev-parse', '--show-toplevel']).strip()


def changed_files(root, staged):
    """수정된(M) 텍스트 파일 목록. 추가·삭제·이름변경은 대상이 아니다."""
    args = ['diff', '--name-only', '--diff-filter=M']
    if staged:
        args.append('--cached')
    args.append('HEAD')
    out = _git(args, cwd=root)
    files = []
    for name in out.splitlines():
        name = name.strip()
        if not name or name.startswith(SKIP_PREFIXES):
            continue
        files.append(name)
    return files


def deleted_ranges(root, path, staged):
    """이번 변경이 지우는 **HEAD 쪽 줄 번호** 구간 [(start, end), ...]."""
    args = ['diff', '-U0', '--no-color']
    if staged:
        args.append('--cached')
    args += ['HEAD', '--', path]
    out = _git(args, cwd=root)
    if '\0' in out[:4000] or 'Binary files' in out[:4000]:
        return None                      # 바이너리 — 줄 개념이 없다
    ranges = []
    for line in out.splitlines():
        m = _HUNK.match(line)
        if not m:
            continue
        start = int(m.group(1))
        count = 1 if m.group(2) is None else int(m.group(2))
        if count > 0:                    # 0 이면 순수 삽입 — 지워지는 것이 없다
            ranges.append((start, start + count - 1))
    return ranges


def blame_lines(root, path):
    """HEAD 의 그 파일을 blame → {줄번호: (sha, committer_time)}.

    파일당 한 번만 부른다. 구간마다 부르면 큰 파일에서 호출이 구간 수만큼 는다.
    """
    out = _git(['blame', 'HEAD', '--line-porcelain', '--', path], cwd=root)
    lines = {}
    sha = None
    ctime = None
    lineno = None
    for raw in out.split('\n'):
        if not raw:
            continue
        if raw[0] == '\t':               # 내용 줄 — 앞서 모은 헤더를 확정한다
            if sha is not None and lineno is not None:
                lines[lineno] = (sha, ctime)
            sha = ctime = lineno = None
            continue
        parts = raw.split(' ')
        if len(parts[0]) == 40 and all(c in '0123456789abcdef' for c in parts[0]):
            sha = parts[0]
            if len(parts) >= 3:
                try:
                    lineno = int(parts[2])   # 최종 파일에서의 줄 번호
                except ValueError:
                    lineno = None
        elif raw.startswith('committer-time '):
            try:
                ctime = int(raw.split(' ', 1)[1])
            except ValueError:
                ctime = None
    return lines


def commit_meta(root, sha):
    out = _git(['show', '-s', '--format=%h%x00%an%x00%ad%x00%s', '--date=short', sha],
               cwd=root)
    short, author, date, subject = out.rstrip('\n').split('\0', 3)
    return {'short': short, 'author': author, 'date': date, 'subject': subject}


def analyse(root, staged, days, min_lines, min_ratio):
    cutoff = time.time() - days * 86400
    findings = []
    scanned = 0

    for path in changed_files(root, staged):
        ranges = deleted_ranges(root, path, staged)
        if not ranges:
            continue
        try:
            blame = blame_lines(root, path)
        except RuntimeError:
            continue                     # blame 불가(바이너리 등)는 조용히 건너뛴다
        scanned += 1

        # 그 커밋이 이 파일에 **지금 남겨 둔** 줄 수 (분모)
        total = {}
        for sha, _ct in blame.values():
            total[sha] = total.get(sha, 0) + 1

        deleted = {}
        times = {}
        for start, end in ranges:
            for ln in range(start, end + 1):
                hit = blame.get(ln)
                if not hit:
                    continue
                sha, ct = hit
                deleted[sha] = deleted.get(sha, 0) + 1
                if ct is not None:
                    times[sha] = ct

        for sha, gone in deleted.items():
            ct = times.get(sha)
            if ct is None or ct < cutoff:
                continue                 # 오래된 줄을 지우는 것은 평범한 편집이다
            have = total.get(sha, 0)
            if not have:
                continue
            ratio = gone / float(have)
            full_wipe = gone >= have                      # 남는 줄이 없다
            if full_wipe:
                if gone < FULL_WIPE_MIN_LINES:
                    continue
            elif gone < min_lines or ratio < min_ratio:
                continue
            meta = commit_meta(root, sha)
            findings.append({
                'file': path,
                'commit': meta['short'],
                'subject': meta['subject'],
                'date': meta['date'],
                'author': meta['author'],
                'deleted': gone,
                'commit_lines_in_file': have,
                'ratio': round(ratio, 3),
            })

    findings.sort(key=lambda f: (-f['deleted'], f['file']))
    return findings, scanned


def main():
    ap = argparse.ArgumentParser(description='최근 커밋을 되돌리는 변경을 잡는다.')
    ap.add_argument('--staged', action='store_true',
                    help='인덱스를 검사 (pre-commit 훅이 쓰는 모드)')
    ap.add_argument('--json', action='store_true', help='기계 판독')
    ap.add_argument('--quiet', action='store_true', help='요약만')
    ap.add_argument('--days', type=int, default=DEFAULT_DAYS,
                    help='이 기간 안의 커밋을 "최근" 으로 본다 (기본 %d)' % DEFAULT_DAYS)
    ap.add_argument('--min-lines', type=int, default=DEFAULT_MIN_LINES,
                    help='이보다 적게 지우면 보고하지 않는다 (기본 %d)' % DEFAULT_MIN_LINES)
    ap.add_argument('--min-ratio', type=float, default=DEFAULT_MIN_RATIO,
                    help='그 커밋 기여분의 이 비율 이상이면 의심 (기본 %.2f)' % DEFAULT_MIN_RATIO)
    a = ap.parse_args()

    try:
        root = _repo_root()
        _git(['rev-parse', '--verify', 'HEAD'], cwd=root)
    except RuntimeError as exc:
        print('검사 실패: %s' % exc, file=sys.stderr)
        return 2

    try:
        findings, scanned = analyse(root, a.staged, a.days, a.min_lines, a.min_ratio)
    except Exception as exc:                      # noqa: BLE001 — 검사기가 커밋을 막으면 안 된다
        print('검사 실패: %s' % exc, file=sys.stderr)
        return 2

    if a.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
        return 1 if findings else 0

    where = '인덱스' if a.staged else '워킹트리'
    if not findings:
        if not a.quiet:
            print('OK: %s 파일 %d개 — 최근 %d일 커밋을 되돌리는 변경 없음.'
                  % (where, scanned, a.days))
        return 0

    if a.quiet:
        print('되돌림 의심 %d건(%s).' % (len(findings), where))
        return 1

    print('최근 커밋이 넣은 줄이 이번 변경에서 통째로 사라집니다 (%s):\n' % where)
    for f in findings:
        print('  - %s' % f['file'])
        print('      %s (%s, %s) "%s"'
              % (f['commit'], f['date'], f['author'], f['subject']))
        print('      그 커밋이 이 파일에 남긴 %d줄 중 %d줄(%.0f%%)이 지워집니다.'
              % (f['commit_lines_in_file'], f['deleted'], f['ratio'] * 100))
        print('      확인: git diff %s HEAD -- %s'
              % ('--cached' if a.staged else '', f['file']))
    print()
    print('되돌리려는 것이 맞다면 그대로 진행하시면 됩니다. 이 검사가 가리는 것은')
    print('"지우려던 것" 이 아니라 **지우는 줄 모르고 지우는 것** 입니다.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
