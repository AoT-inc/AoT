#!/usr/bin/env python3
"""정적 자산 참조가 캐시 무효화 수단을 갖췄는지 검사한다.

**왜 있는가.** 2026-08-13, 지도에서 도형을 지워도 새로고침하면 되살아났다. 원인은 지도
코드가 아니라 브라우저가 옛 파일을 실행하고 있었던 것이다:

    geo_design.html:  <script src="/static/js/geo/aot-map-data.js"></script>   ← 버전 없음
    정적 응답 헤더 :  Cache-Control: public, max-age=31536000                  ← 1년

버전이 없으면 URL 이 영원히 같고, 1년 캐시라 브라우저는 서버에 묻지도 않는다. 08-03 에
그 파일이 바뀌었지만(삭제 목록을 싣는 코드 추가) 그 전에 방문한 브라우저는 계속 옛 사본을
돌렸다. 같은 날 서버가 "페이로드에 없음 = 삭제" 를 폐지해서, 목록을 못 싣는 옛 클라이언트의
삭제 요청은 **정상 응답을 받으며 아무것도 지우지 않았다.**

화면에도 로그에도 테스트에도 드러나지 않는다 — 개발자는 늘 새 코드를 보고, 옛 코드가 도는
것은 사용자 브라우저다. 그래서 사람이 아니라 검사가 지킨다.

**무엇을 통과시키는가.**
  - `url_for('static', filename=...)`  → 앱이 `url_defaults` 로 버전을 자동 주입한다.
  - `asset('name')`                     → 번들 manifest 해시가 붙는다.
  - 리터럴 `/static/...?v=...`          → 손으로 붙인 버전.
  - 면제 명부에 오른 경로               → 아래 EXEMPT 참조.

**무엇을 막는가.**
  - 리터럴 `/static/...` 에 `?v=` 가 없는 것. 이것이 위 사고의 형태다.

사용:
    python3 aot/scripts/check_static_cache_busting.py            # 워킹트리
    python3 aot/scripts/check_static_cache_busting.py --staged   # 인덱스(pre-commit)
    python3 aot/scripts/check_static_cache_busting.py --json
    python3 aot/scripts/check_static_cache_busting.py --quiet

종료 0=정상, 1=버전 없는 리터럴 참조 발견, 2=검사 실패.
표준 라이브러리만 쓴다 — 설치가 깨져도 이 검사는 돌아야 한다.
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 검사 대상. user_templates/ 는 자동 생성물(gitignore)이라 제외한다 — 정본은 widgets/*.py 이고
# 거기를 고치지 않으면 다음 재생성에 되돌아간다.
SCAN_SPECS = [
    (os.path.join("aot", "aot_flask", "templates"), (".html",)),
    (os.path.join("aot", "widgets"), (".py",)),
    (os.path.join("aot", "aot_flask", "static", "js"), (".js",)),
]
EXCLUDE_DIR_PARTS = (
    os.sep + "user_templates" + os.sep,   # 자동 생성물
    os.sep + "dist" + os.sep,             # 번들 산출물 — 소스를 고치고 재빌드한다
    os.sep + "vendor" + os.sep,           # 서드파티 원본
)
EXCLUDE_NAME_PARTS = (".bundle.js", ".min.js")

# 리터럴 참조. 뒤에 ?v= 가 붙었는지까지 한 번에 본다.
# 앞의 negative lookbehind 는 **파일시스템 경로**를 걸러낸다 — 위젯의 설치 안내에
# `/opt/AoT/aot/aot_flask/static/js/...` 같은 문자열이 있는데 그건 URL 이 아니라 경로다
# (`aot_flask` 의 'k' 가 바로 앞에 오므로 여기서 탈락한다).
LITERAL_RE = re.compile(
    r"""(?<![A-Za-z0-9_.\-])/static/([A-Za-z0-9_./\-]+\.[A-Za-z0-9]+)(\?[^"'\s)]*)?""")

# 면제 — **"판단해서 뺐다" 가 드러나야 한다.** 접두사에 안 걸려서 통과한 것과 구분한다.
# 이미지·아이콘은 스테일해도 기능이 깨지지 않는다(잘못된 그림이 잠깐 보일 뿐).
# 코드(.js/.css)는 절대 여기 넣지 말 것 — 그것이 이 검사가 막으려는 대상이다.
EXEMPT_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
                   ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".wav")
EXEMPT_PATHS = {
    # 여기에 경로를 넣는 것은 "이 파일은 스테일해도 된다" 는 안전 판단이다.
    #
    # css/bootstrap-4-themes/aot.css — 이 리터럴은 `<link href=...>` 가 아니라
    # `{% set effective_theme = ... else '/static/css/bootstrap-4-themes/aot.css' %}`
    # 의 **기본값**이다. 실제로 태그가 되는 자리(layout_default.html 의
    # `<link href="{{ effective_theme }}?v=...">`)에서 버전이 붙으므로 스테일하지 않다.
    # 기본값 쪽에 ?v= 를 넣으면 사용처에서 `?v=A?v=B` 가 되어 깨진다.
    "css/bootstrap-4-themes/aot.css",
}


def _iter_files(staged_paths=None):
    if staged_paths is not None:
        for rel in staged_paths:
            path = os.path.join(ROOT, rel)
            for base, exts in SCAN_SPECS:
                if rel.startswith(base) and rel.endswith(exts):
                    if _excluded(path):
                        break
                    if os.path.exists(path):
                        yield rel, path
                    break
        return
    for base, exts in SCAN_SPECS:
        for dp, _dirs, fns in os.walk(os.path.join(ROOT, base)):
            for fn in fns:
                if not fn.endswith(exts):
                    continue
                path = os.path.join(dp, fn)
                if _excluded(path):
                    continue
                yield os.path.relpath(path, ROOT), path


def _excluded(path):
    norm = os.sep + os.path.relpath(path, ROOT)
    if any(part in norm for part in EXCLUDE_DIR_PARTS):
        return True
    return any(norm.endswith(part) for part in EXCLUDE_NAME_PARTS)


def _staged_paths():
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "git diff --cached 실패")
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


# 주석 줄은 URL 을 만들지 않는다. 문서화 주석에 예시 경로를 적어 둔 곳이 많아
# (`* <script src="/static/js/...">` 같은) 이걸 안 걸러내면 오탐이 실제 결함을 묻는다.
_COMMENT_RE = re.compile(r"""^\s*(\*|//|#|<!--)""")


def _is_comment(line):
    return bool(_COMMENT_RE.match(line))


def _read(path, rel, staged):
    if not staged:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    out = subprocess.run(["git", "show", f":{rel}"], cwd=ROOT,
                         capture_output=True, text=True)
    if out.returncode != 0:      # 인덱스에 없으면(삭제 등) 워킹트리로
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return out.stdout


def scan(staged=False):
    findings = []
    scanned = 0
    paths = _staged_paths() if staged else None
    for rel, path in _iter_files(paths):
        try:
            text = _read(path, rel, staged)
        except OSError:
            continue
        scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            if _is_comment(line):
                continue
            for m in LITERAL_RE.finditer(line):
                asset, query = m.group(1), m.group(2) or ""
                if asset.lower().endswith(EXEMPT_SUFFIXES):
                    continue
                if asset in EXEMPT_PATHS:
                    continue
                if "v=" in query:
                    continue
                findings.append({
                    "file": rel, "line": lineno, "asset": "/static/" + asset,
                    "snippet": line.strip()[:120],
                })
    return findings, scanned


def main():
    ap = argparse.ArgumentParser(description="정적 참조 캐시 무효화 검사")
    ap.add_argument("--staged", action="store_true", help="인덱스만 검사(pre-commit)")
    ap.add_argument("--json", action="store_true", help="기계 판독")
    ap.add_argument("--quiet", action="store_true", help="요약만")
    args = ap.parse_args()

    try:
        findings, scanned = scan(staged=args.staged)
    except Exception as exc:                      # noqa: BLE001
        print(f"검사 실패: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"ok": not findings, "scanned": scanned,
                          "findings": findings}, ensure_ascii=False, indent=1))
        return 1 if findings else 0

    if not findings:
        if not args.quiet:
            print(f"OK: 파일 {scanned}개 — 버전 없는 정적 리터럴 참조 없음.")
        else:
            print("OK: 0건")
        return 0

    print(f"버전 없는 정적 리터럴 참조 {len(findings)}건 (파일 {scanned}개 검사)")
    if not args.quiet:
        print()
        for f in findings:
            print(f"  {f['file']}:{f['line']}  {f['asset']}")
            print(f"      {f['snippet']}")
        print()
        print("고치는 법 — 리터럴 대신 다음 중 하나를 쓴다:")
        print("  템플릿/위젯 : {{ url_for('static', filename='js/foo.js') }}")
        print("                (앱이 url_defaults 로 버전을 자동 주입한다)")
        print("  번들        : {{ asset('aot-map-widget') }}")
        print("  JS 안에서   : '/static/css/x.css?v=' + window.AOT_ASSET_V")
        print()
        print("우회: AOT_SKIP_STATIC_CACHE_CHECK=1 git commit ...")
    return 1


if __name__ == "__main__":
    sys.exit(main())
