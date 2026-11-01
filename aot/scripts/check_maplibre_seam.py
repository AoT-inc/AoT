#!/usr/bin/env python3
"""MapLibre 이음매 검사기 — 지도 생성과 내부 필드 읽기를 한 파일로 모은다.

MapLibre 5 전환에서 깨진 곳은 대부분 내부 필드나 폐기된 필드를 직접 읽던 자리였고,
지도 생성은 13개 파일에 흩어져 있어 옵션·WebGL 실패 처리가 제각각이었다. 그래서
두 가지를 `geo/aot-maplibre-seam.js`(`AoTMapSeam`) 한 곳에 모았다.

  · 지도 생성   `new maplibregl.Map(...)`            → `AoTMapSeam.createMap(...)`
  · 내부 필드   `style._layers` · `style._order` · `_controls`
               · `sourceCaches` · `tileManagers` · `<map>.transform`
                                                    → AoTMapSeam 의 읽기 함수

이 검사는 위 모양의 **새 직접 사용**을 막는다. 기준선(허용 명부)은 없다 — 기존 사용은
전부 옮겼으므로 이음매 파일 밖의 모든 사용이 위반이다.

사용:
    python3 aot/scripts/check_maplibre_seam.py          # 전체 검사
종료 코드 0 = 위반 없음, 1 = 위반 발견.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS = os.path.join(ROOT, 'aot', 'aot_flask', 'static', 'js')
SEAM = 'geo/aot-maplibre-seam.js'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_js_scope_reach import _mask, _SKIP  # noqa: E402  (주석·문자열 지우기, 제외 목록 공유)

# 문자열·주석을 지운 뒤에 대조한다. (이름, 정규식, 대신 쓸 것)
RULES = (
    ('new maplibregl.Map', re.compile(r'\bnew\s+(?:window\.)?maplibregl\.Map\s*\('),
     'AoTMapSeam.createMap(options)'),
    ('style._<내부>', re.compile(r'\.style\._[A-Za-z]\w*'),
     'AoTMapSeam.styleLayers / styleLayerIds / layerOrder'),
    ('_controls', re.compile(r'\._controls\b'), 'AoTMapSeam.hasControl(map, control)'),
    ('sourceCaches/tileManagers', re.compile(r'\b(?:sourceCaches|tileManagers)\b'),
     'AoTMapSeam.tileSources(map)'),
    ('map.transform', re.compile(r'\b\w*[mM]ap\w*\.transform\b'),
     'AoTMapSeam 에 읽기 함수를 추가'),
)


def _files():
    for base, dirs, names in os.walk(JS):
        dirs[:] = [d for d in dirs if d not in ('node_modules', 'dist', 'vendor')]
        for n in names:
            if not n.endswith('.js') or n.endswith('.min.js'):
                continue
            path = os.path.join(base, n)
            rel = os.path.relpath(path, JS).replace(os.sep, '/')
            if rel == SEAM or any(s in '/' + rel for s in _SKIP):
                continue
            yield rel, path


def scan(src):
    """masked 소스에서 (줄, 이름, 대안) 목록."""
    hits = []
    for no, line in enumerate(_mask(src).split('\n'), 1):
        for name, rx, hint in RULES:
            if rx.search(line):
                hits.append((no, name, hint))
    return hits


def main():
    bad = []
    for rel, path in _files():
        with open(path, encoding='utf-8') as fh:
            for no, name, hint in scan(fh.read()):
                bad.append('  %s:%d  %s  →  %s' % (rel, no, name, hint))
    if bad:
        print('MapLibre 이음매 위반 %d건 (%s 를 거치세요):' % (len(bad), SEAM))
        print('\n'.join(bad))
        return 1
    print('OK: MapLibre 생성·내부 필드 직접 사용 없음')
    return 0


if __name__ == '__main__':
    sys.exit(main())
