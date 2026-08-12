#!/usr/bin/env python3
"""JS 번들 드리프트 체커.

정적 JS 중 일부는 빌드 산출물(번들)이고 git 에 추적된다. 소스만 고치고 재빌드
없이 커밋하면 배포된 앱은 계속 옛 코드를 실행한다 — 테스트도 참조 체커도
잡지 못하는 조용한 실패다(2026-07-27 f8090ce 통신상태 레이어가 지도·시설
위젯에서 실제로는 죽어 있던 사건).

빌드 그룹 3종을 다룬다:
  esbuild  static/js/tools/bundles.json  -> static/js/dist/*.bundle.js
  rollup   static/js/geo/rollup.config.js -> static/js/geo/dist/*.bundle.js
  vite     static/apps/notes-widget/src   -> static/js/notes/*

모드:
  (기본)      워킹트리(스테이지+비스테이지)에서 입력만 고치고 산출물은 그대로인 번들
  --staged    인덱스에 올라간 변경만 검사 (pre-commit 훅용)
  --history   전 히스토리 커밋시각 비교 — 자문용(항상 종료 0). 소스를 고쳤지만
              산출물이 바뀌지 않는 정상 케이스(빌드 결과 동일)도 걸리므로
              최종 판정은 --rebuild 로 한다.
  --rebuild   임시 트리에 실제로 재빌드해 바이트 비교 — 유일한 확정 판정.
              세 그룹 전부를 검증한다(vite 는 2026-08-13 재현성 실측 후 편입).
              node + 설치된 node_modules 필요. CI 게이트용.
  --range B..H 커밋 범위의 변경집합 검사. 깨끗한 체크아웃(CI·클론)에서는 워킹트리
              ·인덱스가 비어 기본/--staged 모드가 "변경 없음"으로 통과하므로,
              그 환경에서 변경집합을 보려면 이 모드가 필요하다. 다만 CI 게이트는
              --rebuild 다 — 변경집합 모드는 "빌드 결과가 실제로 같은 정상 변경"
              도 드리프트로 올린다(--history 와 같은 한계). 지금은 로컬 포렌식용.

종료 코드 0 = 정상, 1 = 드리프트/검증 불가.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# aot/scripts/check_js_bundles.py -> repo root is three levels up
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC = os.path.join(ROOT, "aot", "aot_flask", "static")
JS = os.path.join(STATIC, "js")
NOTES_SRC = os.path.join(STATIC, "apps", "notes-widget")


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def git(*args, cwd=ROOT):
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return out.stdout


# --------------------------------------------------------------------------
# 번들 레지스트리
# --------------------------------------------------------------------------

class Bundle:
    def __init__(self, name, group, outputs, inputs, rebuild=True):
        self.name = name
        self.group = group          # esbuild | rollup | vite
        self.outputs = outputs      # 절대경로 list
        self.inputs = inputs        # 절대경로 list
        self.rebuild = rebuild      # --rebuild 로 바이트 검증 가능한가


def esbuild_bundles():
    """tools/bundles.json 의 선언 그대로. 입력에 빌더/설정 자신도 포함한다."""
    cfg_path = os.path.join(JS, "tools", "bundles.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    builder = [cfg_path, os.path.join(JS, "tools", "bundle.mjs")]
    out = []
    for name, b in cfg.items():
        # dist/manifest.json 은 산출물로 세지 않는다 — 어떤 번들을 빌드하든 같이
        # 바뀌므로, 산출물 목록에 넣으면 "다른 번들만 재빌드한 커밋"이 이 번들의
        # 드리프트를 가려버린다(실제 f8090ce 누락이 이 방식이면 안 잡혔다).
        out.append(Bundle(
            name, "esbuild",
            outputs=[os.path.join(JS, b["output"])],
            inputs=[os.path.join(JS, i) for i in b["inputs"]] + builder,
        ))
    return out


_IMPORT_RE = re.compile(r"""^\s*import\s+(?:[^'"]*?\bfrom\s+)?['"](\.[^'"]+)['"]""", re.M)


def _module_graph(entry):
    """엔트리에서 상대경로 import 를 따라간 모듈 집합(자기 자신 포함)."""
    seen, stack = set(), [os.path.abspath(entry)]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        if not os.path.exists(cur):
            # 그래프가 조용히 좁아지면 이 체커 자신이 드리프트를 놓친다.
            # (확장자 생략 import·디렉터리 import 는 지원하지 않는다 — 현재 geo
            #  소스는 전부 './x.js' 형태. 형태가 바뀌면 여기서 시끄럽게 알린다.)
            print(f"warn: 모듈 그래프에서 해석 실패 — {rel(cur)} "
                  f"(check_js_bundles.py 의 import 해석 보강 필요)", file=sys.stderr)
            continue
        seen.add(cur)
        try:
            src = open(cur, encoding="utf-8").read()
        except OSError:
            continue
        for spec in _IMPORT_RE.findall(src):
            stack.append(os.path.abspath(os.path.join(os.path.dirname(cur), spec)))
    return sorted(seen)


def geo_bundles():
    """rollup.config.js 의 엔트리별 모듈 그래프.

    엔트리마다 그래프가 다르다 — mcp_servers 는 src/mcp_servers.js 단독이라
    geo/src 전체를 입력으로 잡으면 대량 오탐이 난다.
    """
    geo = os.path.join(JS, "geo")
    cfgs = [os.path.join(geo, "rollup.config.js"), os.path.join(geo, "package.json")]
    entries = [
        # (번들명, 산출물 목록, 엔트리)
        ("geo:aot-geo-all", ["dist/aot-geo-all.bundle.js",
                             "dist/aot-geo-all.bundle.min.js"], "src/index.js"),
        ("geo:mcp_servers", ["dist/mcp_servers.bundle.js"], "src/mcp_servers.js"),
    ]
    out = []
    for name, outs, entry in entries:
        out.append(Bundle(
            name, "rollup",
            outputs=[os.path.join(geo, o) for o in outs],
            inputs=_module_graph(os.path.join(geo, entry)) + cfgs,
        ))
    return out


def notes_bundle():
    """vite build (outDir=../../js/notes).

    재현성 실측 완료(2026-08-13) — 세 축 모두 바이트 동일이라 --rebuild 대상이다:
    같은 경로 2회 · 서로 다른 경로(절대경로 누출 없음) · macOS/Node25 대
    linux/Node22 + 새 `npm ci`. 커밋된 산출물도 그 빌드와 바이트 동일했다.
    재현되는 이유는 설정에 있다 — entry/chunk/assetFileNames 가 콘텐츠 해시 없이
    고정 파일명이고 소스맵이 꺼져 있어 절대경로가 실릴 자리가 없다.
    **vite.config.js 에서 파일명에 [hash] 를 넣거나 sourcemap 을 켜면 이 전제가
    깨진다** — 그때는 다시 rebuild=False 로 내리고 그 근거를 여기 적을 것.

    public/ 도 입력이고 그 복사본도 산출물이다(vite.svg). 예전에는 둘 다 목록에
    없어서, public/ 을 고쳐도 어느 검사에도 걸리지 않았다.
    """
    srcs = []
    for sub in ("src", "public"):
        for dp, _, fns in os.walk(os.path.join(NOTES_SRC, sub)):
            for fn in fns:
                srcs.append(os.path.join(dp, fn))
    srcs += [os.path.join(NOTES_SRC, f)
             for f in ("index.html", "vite.config.js", "package.json")]
    outs = [os.path.join(JS, "notes", f)
            for f in ("notes-widget.js", "notes-widget.css", "index.html",
                      "vite.svg")]
    return [Bundle("notes-widget", "vite", outputs=outs, inputs=sorted(srcs))]


def registry():
    return esbuild_bundles() + geo_bundles() + notes_bundle()


# --------------------------------------------------------------------------
# 변경집합 기반 검사 (--staged / 워킹트리)
# --------------------------------------------------------------------------

def changed_paths(staged_only, commit_range=None):
    if commit_range:
        names = git("diff", "--name-only", commit_range)
    elif staged_only:
        names = git("diff", "--cached", "--name-only")
    else:
        # 스테이지 + 비스테이지 (추적 파일 기준)
        names = git("diff", "--name-only", "HEAD")
    return {p for p in names.splitlines() if p}


def check_changeset(staged_only, commit_range=None):
    changed = changed_paths(staged_only, commit_range)
    if commit_range:
        label = f"커밋 범위({commit_range}) 변경"
    else:
        label = "스테이지된 변경" if staged_only else "워킹트리 변경"
    if not changed:
        print(f"{label} 없음 — 검사 생략.")
        return 0
    problems = 0
    for b in registry():
        hit_in = sorted(rel(p) for p in b.inputs if rel(p) in changed)
        hit_out = [rel(p) for p in b.outputs if rel(p) in changed]
        if hit_in and not hit_out:
            problems += 1
            print(f"  - [{b.name}] 소스는 바뀌었는데 산출물이 그대로:")
            for p in hit_in:
                print(f"        수정됨  {p}")
            for p in b.outputs:
                print(f"        미변경  {rel(p)}")
            print(f"        고치기: {build_hint(b)}")
    if problems:
        print(f"FAIL: {label}에서 재빌드 누락 번들 {problems}개.")
        return 1
    print(f"OK: {label} {len(changed)}건 — 재빌드 누락 없음.")
    return 0


def check_manifest():
    """dist/manifest.json 의 해시가 디스크의 번들 내용과 맞는지.

    node 없이 도는 순수 파이썬 검사라 모든 모드에서 같이 돈다. 소스 드리프트는
    못 잡지만(번들·매니페스트가 함께 낡으면 서로 일관됨), 번들만 커밋하고
    매니페스트를 빠뜨린 경우 = asset() 캐시버스팅이 옛 URL 을 계속 내보내는
    상황을 잡는다.
    """
    import hashlib
    mpath = os.path.join(JS, "dist", "manifest.json")
    try:
        manifest = json.load(open(mpath, encoding="utf-8"))
    except OSError as e:
        print(f"  - manifest 읽기 실패: {e}")
        return 1
    problems = 0
    for b in esbuild_bundles():
        out = b.outputs[0]
        if not os.path.exists(out):
            print(f"  - [{b.name}] 산출물 없음: {rel(out)}")
            problems += 1
            continue
        want = hashlib.sha256(open(out, "rb").read()).hexdigest()[:10]
        got = manifest.get(b.name)
        if got != want:
            print(f"  - [{b.name}] manifest 해시 불일치: manifest={got} 실제={want}")
            print(f"        고치기: {build_hint(b)}")
            problems += 1
    return problems


def build_hint(b):
    if b.group == "esbuild":
        return f"cd aot/aot_flask/static/js && npm run build:bundles {b.name}"
    if b.group == "rollup":
        return "cd aot/aot_flask/static/js && npm run build:geo"
    return "cd aot/aot_flask/static/js && npm run build:notes"


# --------------------------------------------------------------------------
# 히스토리 검사 (--history, 자문용)
# --------------------------------------------------------------------------

def last_commit(path):
    line = git("log", "-1", "--format=%ci|%h|%s", "--", rel(path)).strip()
    return line.split("|", 2) if line else None


def check_history():
    print("히스토리 커밋시각 비교 (자문용 — 확정 판정은 --rebuild):\n")
    suspects = 0
    for b in registry():
        outs = [c for c in (last_commit(p) for p in b.outputs) if c]
        if not outs:
            print(f"  [{b.name}] 산출물이 git 에 없음 — 건너뜀")
            continue
        newest_out = max(outs, key=lambda c: c[0])
        newer = []
        for p in b.inputs:
            c = last_commit(p)
            if c and c[0] > newest_out[0]:
                newer.append((c, rel(p)))
        if newer:
            suspects += 1
            print(f"  SUSPECT [{b.name}]")
            print(f"      산출물 최종: {newest_out[0]}  {newest_out[1]} {newest_out[2]}")
            for c, p in sorted(newer, reverse=True):
                print(f"      이후 소스 : {c[0]}  {c[1]} {p}")
            print()
    if suspects:
        print(f"{suspects}개 번들이 의심됨. `--rebuild` 로 실제 바이트 비교 후 판정할 것.")
    else:
        print("의심 번들 없음.")
    return 0  # 자문용이므로 항상 0


# --------------------------------------------------------------------------
# 재빌드 검증 (--rebuild, 확정 판정)
# --------------------------------------------------------------------------

def _copy_tree(src, dst, node_modules_link):
    """node_modules 는 복사 대신 심링크(수십 MB)."""
    shutil.copytree(src, dst, symlinks=True,
                    ignore=shutil.ignore_patterns("node_modules"))
    for sub in node_modules_link:
        real = os.path.join(src, sub, "node_modules") if sub else os.path.join(src, "node_modules")
        link = os.path.join(dst, sub, "node_modules") if sub else os.path.join(dst, "node_modules")
        if os.path.isdir(real):
            os.symlink(real, link)


def check_rebuild():
    for d in (os.path.join(JS, "node_modules"),
              os.path.join(JS, "geo", "node_modules"),
              os.path.join(NOTES_SRC, "node_modules")):
        if not os.path.isdir(d):
            print(f"FAIL: node_modules 없음({rel(d)}) — 먼저 "
                  f"`cd aot/aot_flask/static/js && npm run install:all`.")
            return 1
    tmp = tempfile.mkdtemp(prefix="aot-bundle-verify-")
    try:
        # 임시 트리는 static/ 의 구조를 그대로 흉내낸다: vite 의 outDir 이 소스 기준
        # 상대경로(../../js/notes)라, apps/notes-widget 과 js 가 형제로 있어야
        # 산출물이 work_js/notes 로 떨어진다. (그래서 tmp/js 가 아니라 tmp/static/js)
        static = os.path.join(tmp, "static")
        os.makedirs(static)
        work = os.path.join(static, "js")
        _copy_tree(JS, work, ["", "geo"])
        work_notes_src = os.path.join(static, "apps", "notes-widget")
        os.makedirs(os.path.dirname(work_notes_src))
        _copy_tree(NOTES_SRC, work_notes_src, [""])
        r = subprocess.run(["node", "tools/bundle.mjs"], cwd=work,
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("FAIL: esbuild 번들 재빌드 실패\n" + (r.stderr or r.stdout))
            return 1
        r = subprocess.run(["npx", "rollup", "-c"], cwd=os.path.join(work, "geo"),
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("FAIL: geo rollup 재빌드 실패\n" + (r.stderr or r.stdout))
            return 1
        r = subprocess.run(["npx", "vite", "build"], cwd=work_notes_src,
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("FAIL: notes-widget vite 재빌드 실패\n" + (r.stderr or r.stdout))
            return 1

        problems = 0
        checked = 0
        for b in registry():
            if not b.rebuild:
                print(f"  skip  [{b.name}] 재현성 미검증 빌더({b.group}) — 변경집합 모드로만 검사")
                continue
            for out in b.outputs:
                cur = os.path.join(work, os.path.relpath(out, JS))
                checked += 1
                if not os.path.exists(cur):
                    print(f"  - [{b.name}] 재빌드 산출물 없음: {rel(out)}")
                    problems += 1
                    continue
                if open(out, "rb").read() != open(cur, "rb").read():
                    print(f"  - [{b.name}] 커밋된 산출물이 재빌드 결과와 다름: {rel(out)}")
                    print(f"        고치기: {build_hint(b)}")
                    problems += 1
        if problems:
            print(f"FAIL: 재빌드 불일치 {problems}건 / 검사 {checked}건.")
            return 1
        print(f"OK: 산출물 {checked}건 전부 소스와 일치(바이트 동일).")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true", help="인덱스 변경만 검사(pre-commit)")
    g.add_argument("--history", action="store_true", help="히스토리 커밋시각 비교(자문용)")
    g.add_argument("--rebuild", action="store_true", help="실제 재빌드 후 바이트 비교(확정)")
    g.add_argument("--range", dest="commit_range", metavar="BASE..HEAD",
                   help="커밋 범위의 변경집합 검사(CI). --rebuild 가 건너뛰는 "
                        "재현성 미검증 그룹(vite)을 CI 에서 지키는 유일한 수단이다 — "
                        "깨끗한 체크아웃에서는 워킹트리·인덱스가 비어 있어 기본 모드가 "
                        "'변경 없음'으로 통과해 버린다.")
    a = ap.parse_args()
    mp = check_manifest()
    if mp:
        print(f"FAIL: manifest 불일치 {mp}건.")
        return 1
    if a.history:
        return check_history()
    if a.rebuild:
        return check_rebuild()
    return check_changeset(staged_only=a.staged, commit_range=a.commit_range)


if __name__ == "__main__":
    sys.exit(main())
