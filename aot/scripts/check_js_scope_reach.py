#!/usr/bin/env python3
# coding=utf-8
"""바깥 함수가 **안쪽 스코프에만 있는** 이름을 부르는 것을 잡는다.

## 왜 필요한가

형제 검사(`check_js_undefined_calls.py`)는 "정의가 **있는가**" 를 본다. 이쪽은
"그 정의에 **닿는가**" 를 본다. 둘은 다른 실패다.

2026-09-06 에 실제로 났다. `loadGeoJSONLayers`(5,500줄) 안에서 장치 상세 모달
11개를 IIFE 최상위로 끌어올렸는데, 그 중 `_renderDeviceBody` 가 부르는
`_wireUpBtn` 은 **아직 그 함수 안**에 있었다. 최상위 함수는 안쪽 스코프를 볼
수 없으므로 장치 모달을 여는 순간 ReferenceError 가 난다.

그때 통과한 것들:

- `node --check` — 문법은 멀쩡하다.
- 번들 빌드 — esbuild 는 이름 해석을 실행 시점에 맡긴다.
- `check_js_undefined_calls` — 같은 **파일** 안에 정의가 있으므로 통과한다.
- 옛/새 번들을 iframe 에 로드해 전역을 비교한 검증 — **로드는 멀쩡하다.**
  함수 정의는 다 실리고, **부를 때** 터진다.

즉 그 시점에 돌릴 수 있는 검사가 전부 통과했다. 화면에서 모달을 실제로
열어 봐야만 드러나는데, 모든 모달을 매번 열어 보기를 기대할 수는 없다.

## 무엇을 보나

이 저장소의 JS 는 파일 하나가 IIFE 하나이고, 그 안에 `function _name()` 이
들여쓰기 4칸으로 모여 있다. 더 깊은 들여쓰기는 그 함수들 **안**이다. 그래서
들여쓰기로 스코프 깊이를 읽는다 — 파서 없이도 이 관례에서는 정확하다.

  · 깊이 4  → IIFE 최상위. 다른 최상위 이름을 자유롭게 부를 수 있다.
  · 깊이 8+ → 어떤 함수 안. **최상위에서는 이 이름이 안 보인다.**

깊이 4 함수의 본문이 깊이 8+ 에만 정의된 `_name` 을 부르면 위반이다.

## 오탐을 내지 않으려고 하는 것

**오탐 나는 검사는 아무도 보지 않는다.** 그래서 아래를 전부 제외한다:

  · 주석과 문자열 (줄 구조를 보존하며 지운다 — `_mask` 참조)
  · 그 함수가 자기 안에서 선언한 이름, 그리고 인자
  · 최상위에도 같은 이름이 있는 경우 (그쪽이 잡힌다)
  · `x._name(` 같은 메서드 호출
  · 들여쓰기가 관례를 벗어난 파일 (탭 들여쓰기 등) — 판정하지 않는다

사용:
    python3 aot/scripts/check_js_scope_reach.py            # 워킹트리
    python3 aot/scripts/check_js_scope_reach.py --staged   # 인덱스(pre-commit)
    python3 aot/scripts/check_js_scope_reach.py --json
"""
import json
import os
import re
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JS_ROOT = os.path.join(_ROOT, 'aot_flask', 'static', 'js')

# 형제 검사와 같은 제외 목록 — 산출물·벤더는 우리 관례를 따르지 않는다.
_SKIP = ('/dist/', '/vendor/', '/node_modules/', '/notes/', '/user_js/',
         '/three.min.js', '/three-mesh-bvh.js', '/gltf_loader.js',
         '/three-gltf-exporter.js')

_TOP_FN = re.compile(r'^    (?:async )?function (_?[A-Za-z][\w$]*)\s*\(')
_TOP_VAR = re.compile(r'^    (?:var|let|const) (_?[A-Za-z][\w$]*)')
_IN_FN = re.compile(r'^ {8,}(?:async )?function (_[A-Za-z][\w$]*)\s*\(')
_IN_VAR = re.compile(r'^ {8,}(?:var|let|const) (_[A-Za-z][\w$]*)\s*=')
_CALL = re.compile(r'(?<![\w.$])(_[A-Za-z][\w$]*)\s*\(')


def _mask(src):
    """주석과 문자열을 지우되 **줄 구조는 한 글자도 흔들지 않는다.**

    지운 자리는 같은 길이의 공백으로 바꾸고 개행은 그대로 둔다 — 이 검사는
    스코프 깊이를 들여쓰기로 읽으므로, 줄이 하나라도 밀리면 판정이 통째로
    뒤집힌다.

    **줄 단위로 처리한다.** 파일 전체를 한 문자열로 훑는 방식은 이 저장소에서
    실제로 무너졌다: JS 정규식 리터럴(`.replace(/"/g, '&quot;')`)의 `"` 를
    문자열 시작으로 오인해 그 뒤 수백 줄을 통째로 삼켰고, 그래서 최상위에
    멀쩡히 있는 `_tr` 정의를 "없다" 고 읽었다. 줄 단위면 그런 오인의 피해가
    그 줄 안에 갇힌다.

    여러 줄 템플릿 리터럴만 상태를 이어서 추적한다(백틱은 정규식과 헷갈릴
    일이 없다).
    """
    out, in_block, in_tpl = [], False, False
    for line in src.split('\n'):
        buf, i, n = [], 0, len(line)
        while i < n:
            c = line[i]
            if in_block:
                if line.startswith('*/', i):
                    in_block = False
                    buf.append('  '); i += 2
                else:
                    buf.append(' '); i += 1
            elif in_tpl:
                if c == '`':
                    in_tpl = False
                buf.append(' '); i += 1
            elif line.startswith('//', i):
                buf.append(' ' * (n - i)); break
            elif line.startswith('/*', i):
                in_block = True
                buf.append('  '); i += 2
            elif c == '`':
                in_tpl = True
                buf.append(' '); i += 1
            elif c in '"\'':
                # 같은 줄에서 닫히는 따옴표만 문자열로 본다. 안 닫히면
                # (정규식 리터럴 안의 따옴표 등) 그 줄만 포기한다.
                q, j = c, i + 1
                while j < n and line[j] != q:
                    j += 2 if line[j] == '\\' else 1
                if j < n:
                    buf.append(' ' * (j - i + 1)); i = j + 1
                else:
                    buf.append(' ' * (n - i)); break
            else:
                buf.append(c); i += 1
        out.append(''.join(buf))
    return '\n'.join(out)


def _block_end(lines, start):
    """`start` 줄에서 시작하는 블록이 닫히는 줄(포함)."""
    depth, opened = 0, False
    for j in range(start, len(lines)):
        depth += lines[j].count('{') - lines[j].count('}')
        if '{' in lines[j]:
            opened = True
        if opened and depth <= 0:
            return j
    return len(lines) - 1


def _scan(src):
    """(위반 목록) — src 는 주석·문자열을 지운 코드."""
    lines = src.split('\n')

    top_names, inner_names = set(), set()
    for l in lines:
        m = _TOP_FN.match(l) or _TOP_VAR.match(l)
        if m:
            top_names.add(m.group(1))
        m2 = _IN_FN.match(l) or _IN_VAR.match(l)
        if m2:
            inner_names.add(m2.group(1))

    # 안쪽에만 있는 이름 — 최상위에서 부르면 안 되는 것들
    only_inner = inner_names - top_names
    if not only_inner:
        return []

    out = []
    for i, l in enumerate(lines):
        m = _TOP_FN.match(l)
        if not m:
            continue
        end = _block_end(lines, i)
        body = '\n'.join(lines[i:end + 1])

        # 이 함수가 자기 안에서 선언한 것과 인자는 제외
        local = set(re.findall(r'(?:var|let|const|function)\s+([\w$]+)', body))
        for mm in re.finditer(r'function[^(]*\(([^)]*)\)', body):
            for p in mm.group(1).split(','):
                p = p.strip().split('=')[0].strip()
                if p:
                    local.add(p)

        for mm in _CALL.finditer(body):
            name = mm.group(1)
            if name not in only_inner or name in local:
                continue
            line = i + body.count('\n', 0, mm.start()) + 1
            out.append({'line': line, 'caller': m.group(1), 'name': name})
    return out


def _files(staged):
    repo = os.path.dirname(_ROOT)
    if staged:
        got = subprocess.run(['git', 'diff', '--cached', '--name-only',
                              '--diff-filter=ACMR'],
                             capture_output=True, text=True, cwd=repo).stdout.split('\n')
        return [os.path.join(repo, f) for f in got
                if f.endswith('.js') and 'static/js' in f
                and not any(k in '/' + f for k in _SKIP)]
    found = []
    for base, _dirs, names in os.walk(_JS_ROOT):
        for n in names:
            if not n.endswith('.js'):
                continue
            path = os.path.join(base, n)
            if any(k in '/' + os.path.relpath(path, _JS_ROOT) for k in _SKIP):
                continue
            found.append(path)
    return found


def run(staged=False):
    problems, files = [], _files(staged)
    for path in files:
        try:
            src = open(path, encoding='utf-8').read()
        except (IOError, UnicodeDecodeError):
            continue
        # 관례를 벗어난 들여쓰기(탭 등)면 판정하지 않는다 — 오탐만 낸다.
        if '\t' in src[:20000]:
            continue
        for p in _scan(_mask(src)):
            p['file'] = os.path.relpath(path, os.path.dirname(_ROOT))
            problems.append(p)
    return problems, len(files)


def main():
    problems, n = run('--staged' in sys.argv)
    if '--json' in sys.argv:
        print(json.dumps({'problems': problems, 'files': n}, ensure_ascii=False))
        return 1 if problems else 0
    if not problems:
        print('OK: JS %d개 — 안쪽 스코프의 이름을 바깥에서 부르는 곳 없음.' % n)
        return 0
    print('바깥에서 안쪽 스코프의 이름을 부르는 곳 %d건:' % len(problems))
    for p in problems:
        print('  %s:%d  %s() 안에서 %s()  ← 그 이름은 더 깊은 함수 안에만 있습니다'
              % (p['file'], p['line'], p['caller'], p['name']))
    print('\n로드는 멀쩡하고 그 함수를 부를 때 ReferenceError 가 납니다.')
    print('함수를 밖으로 옮겼다면, 그것이 부르는 것도 함께 옮겨야 합니다.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
