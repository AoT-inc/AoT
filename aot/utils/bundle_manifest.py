# -*- coding: utf-8 -*-
"""JS 번들 해시 매니페스트 읽기 — layout 의 ``asset()`` 과 서버 응답이 **같은 출처**를 쓴다.

``static/js/dist/manifest.json``(번들 이름 → 내용 해시, tools/bundle.mjs 가 쓴다)을 파일 수정 시각으로
캐시한다. app.py 의 ``asset()``·``bundle_manifest()`` 와 ``/api/v1/screen/sync`` 의 ``bundle`` 이 이 모듈을 부른다
(오래 열어 둔 탭이 자기 번들 해시와 서버의 현재 해시를 비교해 "화면이 오래됐습니다" 를 띄운다, 2026-10-20).
"""
import json
import os

MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'aot_flask', 'static', 'js', 'dist', 'manifest.json')

_cache = {'data': None, 'mtime': 0}


def load():
    """번들명 → 해시 전체. 파일이 없거나 깨졌으면 빈 dict(앞서 읽은 값이 있으면 그것)."""
    try:
        st = os.stat(MANIFEST_PATH)
        if _cache['data'] is None or st.st_mtime != _cache['mtime']:
            with open(MANIFEST_PATH, encoding='utf-8') as fh:
                _cache['data'] = json.load(fh)
            _cache['mtime'] = st.st_mtime
    except Exception:
        pass
    return _cache['data'] or {}


def hash_of(name):
    """한 번들의 현재 내용 해시. 모르면 None."""
    h = load().get(name)
    return str(h) if h else None
