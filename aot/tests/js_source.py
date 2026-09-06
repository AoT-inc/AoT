# coding=utf-8
"""JS 소스에서 함수 본문을 **구조에 기대지 않고** 잘라낸다.

## 왜 있는가

여러 테스트가 함수 본문을 이렇게 잘랐다:

    body = src.split('function _attachPlotControl', 1)[1] \\
              .split('\\n        function ', 1)[0]      # 들여쓰기 8칸을 함수 경계로

이 방식은 **그 함수가 어디에 있느냐에 기댄다.** 2026-09-06 에 `loadGeoJSONLayers`
(5,585줄)를 가르면서 107개 함수를 IIFE 최상위(들여쓰기 4칸)로 옮겼더니, 경계
문자열을 못 찾아 파일 끝까지가 "본문" 이 되었고 세 테스트가 빨개졌다 — **동작은
하나도 안 바뀌었는데**. 같은 전제를 쓰는 자리가 아홉 곳 더 있었다.

들여쓰기가 아니라 **중괄호 균형**으로 자르면 함수가 어디로 가든 같은 답이 나온다.

## 문자열·주석 안의 중괄호

`{` 를 세는 것이 전부라면 `'}'` 같은 리터럴에 속는다. 그래서 세기 전에 주석과
문자열을 지운다(줄 구조는 보존한다 — 줄 번호로 보고할 일이 있다).
같은 이유로 만든 `check_js_scope_reach._mask` 와 규칙이 같다.
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JS = os.path.join(_ROOT, 'aot_flask', 'static', 'js')


def mask(src):
    """주석·문자열을 같은 길이의 공백으로. 줄 구조는 그대로."""
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


def function_body(src, name):
    """`function <name>(` 의 여는 `{` 부터 짝이 맞는 `}` 까지 (원본 문자열).

    못 찾으면 AssertionError — 이름이 바뀐 것을 조용히 지나치지 않는다.
    """
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\(', src)
    assert m, '그런 함수가 없습니다: %s' % name
    masked = mask(src)
    i = masked.find('{', m.end())
    assert i >= 0, '%s 의 본문 시작을 못 찾았습니다' % name
    depth = 0
    for j in range(i, len(masked)):
        if masked[j] == '{':
            depth += 1
        elif masked[j] == '}':
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError('%s 의 본문이 닫히지 않았습니다' % name)


def widget_source(*parts):
    """static/js 아래 파일을 읽는다. 예: widget_source('widgets','AoT_map','x.js')"""
    with open(os.path.join(_JS, *parts), encoding='utf-8') as f:
        return f.read()


def has_code(body, snippet):
    """공백 차이를 무시하고 코드 조각이 들어 있는가.

    들여쓰기를 그대로 박아 둔 단정은 함수가 한 단계 밖으로 나가기만 해도
    깨진다(실제로 그랬다). 공백은 하나로 접어 비교한다.
    """
    norm = lambda s: re.sub(r'\s+', ' ', s).strip()
    return norm(snippet) in norm(body)
