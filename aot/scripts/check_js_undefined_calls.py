#!/usr/bin/env python3
# coding=utf-8
"""정의 없이 불리는 내부 함수를 잡는다.

## 왜 필요한가

이 저장소의 JS 는 IIFE 안에 `function _name()` 들이 모여 있고, 큰 함수를 잘라
옮기는 편집이 잦다. **앵커로 잘라 붙이다 이웃 함수를 통째로 삼키는 실수**가
실제로 두 번 났다(2026-08-19: `_kindRow` 하나, 그 뒤 `_plotGddRows` 등 5개).

에러가 안 난다는 것이 이 실패의 전부다:

- `node --check` 는 통과한다 — 문법은 멀쩡하다.
- 번들 빌드도 통과한다 — esbuild 는 이름 해석을 실행 시점에 맡긴다.
- 정적 참조 검사·번들 드리프트 검사도 통과한다 — 파일은 다 있고 최신이다.
- 화면에서는 **그 모달이 그냥 안 열린다.** 예외가 promise 안에서 삼켜져
  콘솔에도 안 남는 경로가 있다.

두 번째 사고 때는 사용자가 "안 열려" 라고 알려 줄 때까지 몰랐다.

## 무엇을 보나

파일마다 `_` 로 시작하는 이름의 **호출**을 모으고, 같은 파일에서
`function _name(` / `var _name = function` / `const _name = (`  로 정의됐는지 본다.
`_` 로 시작하는 것만 보는 이유는 그것이 이 저장소의 파일 내부 헬퍼 관례이기
때문이다 — 전역·외부 API 를 여기서 판정하려 들면 오탐만 쏟아진다.

**메서드 호출(`x._name(`)과 전역 속성(`root._name =`)은 제외한다** — 정의가
다른 파일이나 객체에 있는 것이 정상이다.

사용:
    python3 aot/scripts/check_js_undefined_calls.py            # 워킹트리
    python3 aot/scripts/check_js_undefined_calls.py --staged   # 인덱스(pre-commit)
    python3 aot/scripts/check_js_undefined_calls.py --json
"""
import json
import os
import re
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JS_ROOT = os.path.join(_ROOT, 'aot_flask', 'static', 'js')

# 빌드 산출물·서드파티는 보지 않는다.
# 빌드 산출물·서드파티는 보지 않는다. `AoT_facility` 밑의 three.* 는 벤더 사본이라
# 우리 관례(파일 내부 `_` 헬퍼)를 따르지 않는다 — 여기서 판정하면 오탐만 낸다.
_SKIP = ('/dist/', '/vendor/', '/node_modules/', '/notes/', '/user_js/',
         '/three.min.js', '/three-mesh-bvh.js', '/gltf_loader.js')

_CALL = re.compile(r'(?<![\w.$])(_[A-Za-z][A-Za-z0-9_$]*)\s*\(')
_DEF = (
    re.compile(r'function\s+(_[A-Za-z][A-Za-z0-9_$]*)\s*\('),
    re.compile(r'(?:var|let|const)\s+(_[A-Za-z][A-Za-z0-9_$]*)\s*='),
    re.compile(r'(_[A-Za-z][A-Za-z0-9_$]*)\s*:\s*function'),
    re.compile(r'(_[A-Za-z][A-Za-z0-9_$]*)\s*=\s*(?:function|\()'),
    # 클래스 메서드·인자 이름도 정의로 본다(오탐을 줄이는 쪽으로 넉넉히).
    re.compile(r'^\s*(_[A-Za-z][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{', re.M),
    re.compile(r'\(([^)]*)\)\s*=>'),
)


def _strip(src):
    """주석과 문자열을 지운다.

    **오탐 나는 검사는 아무도 보지 않는다.** 주석에 함수 이름을 적는 것은 이
    저장소의 흔한 관례라(`_rehydrateFromCache() 가 …을 부른다`), 걷어내지 않으면
    18건 중 15건이 주석이다.
    """
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            j = src.find('\n', i)
            i = n if j < 0 else j
        elif c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            i = n if j < 0 else j + 2
        elif c in '"\'`':
            q, j = c, i + 1
            while j < n:
                if src[j] == '\\':
                    j += 2
                    continue
                if src[j] == q:
                    break
                j += 1
            i = j + 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def _defined(src):
    out = set()
    for pat in _DEF[:-1]:
        out |= set(pat.findall(src))
    # 함수 인자에 실린 `_name` 도 정의로 본다.
    for m in re.finditer(r'function[^(]*\(([^)]*)\)', src):
        for part in m.group(1).split(','):
            name = part.strip().split('=')[0].strip()
            if name.startswith('_'):
                out.add(name)
    for m in _DEF[-1].finditer(src):
        for part in m.group(1).split(','):
            name = part.strip().split('=')[0].strip()
            if name.startswith('_'):
                out.add(name)
    return out


def _files(staged):
    if staged:
        out = subprocess.run(['git', 'diff', '--cached', '--name-only',
                              '--diff-filter=ACMR'],
                             capture_output=True, text=True,
                             cwd=os.path.dirname(_ROOT)).stdout.split('\n')
        return [os.path.join(os.path.dirname(_ROOT), f) for f in out
                if f.endswith('.js') and 'static/js' in f
                and not any(k in '/' + f for k in _SKIP)]
    found = []
    for base, _dirs, names in os.walk(_JS_ROOT):
        for n in names:
            if not n.endswith('.js'):
                continue
            path = os.path.join(base, n)
            rel = '/' + os.path.relpath(path, _JS_ROOT)
            if any(k in rel for k in _SKIP):
                continue
            found.append(path)
    return found


def run(staged=False):
    problems = []
    files = _files(staged)
    for path in files:
        try:
            src = open(path, encoding='utf-8').read()
        except (IOError, UnicodeDecodeError):
            continue
        code = _strip(src)
        defined = _defined(src)          # 정의는 원본에서 (주석 안엔 정의가 없다)
        for m in _CALL.finditer(code):
            name = m.group(1)
            if name in defined:
                continue
            # `root._x = ...` / `window._x` 처럼 전역에 심는 것은 제외
            if re.search(r'[\w$]\.' + re.escape(name) + r'\b', code):
                continue
            line = code.count('\n', 0, m.start()) + 1
            problems.append({'file': os.path.relpath(path, os.path.dirname(_ROOT)),
                             'line': line, 'name': name})
    return problems, len(files)


def main():
    staged = '--staged' in sys.argv
    problems, n = run(staged)
    if '--json' in sys.argv:
        print(json.dumps({'problems': problems, 'files': n}, ensure_ascii=False))
        return 1 if problems else 0
    if not problems:
        print('OK: JS %d개 — 정의 없이 불리는 내부 함수 없음.' % n)
        return 0
    print('정의 없이 불리는 내부 함수 %d건:' % len(problems))
    for p in problems:
        print('  %s:%d  %s()' % (p['file'], p['line'], p['name']))
    print('\n큰 함수를 잘라 옮기다 이웃 함수를 함께 지운 적이 있습니다.')
    print('문법·번들 검사는 전부 통과하고, 화면에서는 그 모달이 안 열립니다.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
