# coding=utf-8
"""오버레이지도 타일 프록시의 캐시 계약을 고정한다.

지도 위젯에서 화면을 회전하면 뷰포트 종횡비가 바뀌어 MapLibre 가 새 타일
집합을 요구한다. 그 자체는 정상인데, 예전 프록시 헤더(`max-age=300`, ETag
없음)로는 5분만 지나면 **이미 받았던 타일까지 전량 재다운로드**됐다.
실측(2026-08-13, 로컬 · ISRIC SoilGrids 타일 1장):

    상류 왕복      1,107ms / 27,425바이트
    서버 캐시 적중     14ms / 27,425바이트   (브라우저 캐시 우회)
    조건부 요청(304)   13ms /      0바이트
    브라우저 캐시       2ms /      0바이트

깨져도 조용하다 — 헤더가 짧아지거나 ETag 가 빠져도 그림은 그대로 나온다.
느려질 뿐이다. 그래서 사람 대신 이 테스트가 본다.

여기서 고정하는 것 넷:

1. `utils_http.tile_conditional()` 의 의미 — ETag 를 달고, 일치하면 304.
2. 두 프록시 라우트가 그 헬퍼를 실제로 쓴다는 것.
3. **304 를 돌려주는 라우트에 `@cache.cached` 가 붙지 않는다는 것.**
   flask-caching 은 뷰가 돌려준 응답을 그대로 캐시하므로, 캐시된 304 가
   ETag 를 보내지 않은 다음 사람에게 나가면 타일이 영영 안 뜬다.
4. 실패 응답(빈 타일)은 캐시되지 않는다 — 상류의 일시 장애를 몇 시간짜리
   빈 화면으로 굳히지 않기 위해서다.
"""
import ast
import os
import re
import unittest

from flask import Flask, request

from aot.aot_flask.utils import utils_http

_ROUTES_GEO = os.path.join(os.path.dirname(__file__), '..',
                           'aot_flask', 'routes_geo.py')

_MAP_WIDGET_JS = os.path.join(
    os.path.dirname(__file__), '..', 'aot_flask', 'static', 'js',
    'widgets', 'AoT_map', 'aot-map-widget-vector.js')

#: 타일 바이트를 내보내는 라우트. 새 타일 프록시를 만들면 여기에도 넣을 것.
_TILE_ROUTES = ('api_geo_proxy_wms', 'api_geo_tile_proxy')


def _routes_geo_tree():
    with open(_ROUTES_GEO, encoding='utf-8') as handle:
        return ast.parse(handle.read())


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError('%s 를 routes_geo.py 에서 찾지 못했습니다' % name)


def _called_names(node):
    """`node` 하위에서 호출되는 이름들 (`f()` 와 `a.b()` 의 `b` 둘 다)."""
    out = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            out.add(func.id)
        elif isinstance(func, ast.Attribute):
            out.add(func.attr)
    return out


class TestTileConditional(unittest.TestCase):
    """헬퍼 자체의 의미."""

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self, payload, content_type='image/png', max_age=86400,
              if_none_match=None):
        headers = {}
        if if_none_match is not None:
            headers['If-None-Match'] = if_none_match
        with self.app.test_request_context('/tile', headers=headers):
            return utils_http.tile_conditional(
                request, payload, content_type, max_age)

    def test_first_response_carries_etag_and_long_max_age(self):
        response = self._call(b'\x89PNG-tile-bytes')

        self.assertEqual(200, response.status_code)
        self.assertEqual(b'\x89PNG-tile-bytes', response.get_data())
        self.assertEqual('image/png', response.mimetype)
        self.assertTrue(response.headers.get('ETag'),
                        'ETag 가 없으면 만료 후 재검증이 전량 재다운로드가 된다')
        self.assertEqual('public, max-age=86400',
                         response.headers.get('Cache-Control'))

    def test_matching_etag_returns_304_with_no_body(self):
        first = self._call(b'tile-bytes')
        etag = first.headers['ETag']

        second = self._call(b'tile-bytes', if_none_match=etag)

        self.assertEqual(304, second.status_code)
        self.assertEqual(b'', second.get_data())
        self.assertEqual('public, max-age=86400',
                         second.headers.get('Cache-Control'),
                         '304 에도 수명을 실어야 다음 만료까지 다시 조용해진다')

    def test_changed_bytes_do_not_match_the_old_etag(self):
        first = self._call(b'tile-bytes')

        second = self._call(b'other-bytes', if_none_match=first.headers['ETag'])

        self.assertEqual(200, second.status_code)
        self.assertEqual(b'other-bytes', second.get_data())

    def test_compressed_etag_suffix_still_matches(self):
        """Flask-Compress 가 붙이는 `:br` 접미사를 벗기고 비교해야 한다.

        안 벗기면 서버가 계산한 해시와 절대 일치하지 않아 **항상 200** 이 나간다
        — 에러 없이, ETag 를 붙여 놓고 아무것도 아껴지지 않는 상태로 굴러간다.
        `json_conditional` 이 겪었던 것과 같은 함정이다.
        """
        first = self._call(b'tile-bytes')
        raw = first.headers['ETag'].strip('"')

        second = self._call(b'tile-bytes', if_none_match='W/"%s:br"' % raw)

        self.assertEqual(304, second.status_code)

    def test_max_age_is_per_call(self):
        response = self._call(b'tile-bytes', max_age=3600)

        self.assertEqual('public, max-age=3600',
                         response.headers.get('Cache-Control'))


class TestTileRoutesUseTheHelper(unittest.TestCase):
    """라우트가 계약을 실제로 따르는지 (소스 기준)."""

    def setUp(self):
        self.tree = _routes_geo_tree()

    def test_every_tile_route_returns_through_tile_conditional(self):
        for name in _TILE_ROUTES:
            with self.subTest(route=name):
                self.assertIn('tile_conditional', _called_names(_function(self.tree, name)),
                              '%s 가 utils_http.tile_conditional 을 거치지 않습니다 — '
                              'ETag/장기 max-age 가 빠집니다' % name)

    def test_every_tile_route_consults_the_server_cache(self):
        """서버 캐시가 빠지면 브라우저 캐시가 빈 순간마다 상류 왕복(초 단위)이 산다."""
        for name in _TILE_ROUTES:
            with self.subTest(route=name):
                called = _called_names(_function(self.tree, name))
                self.assertIn('_tile_cache_get', called)
                self.assertIn('_tile_cache_set', called)

    def test_tile_routes_are_not_wrapped_in_cache_cached(self):
        """304 를 돌려주는 뷰를 `@cache.cached` 로 감싸면 그 304 가 캐시된다.

        그 다음 사람은 `If-None-Match` 를 보내지도 않았는데 본문 없는 304 를
        받는다 — 타일이 안 뜨는데 서버 로그에는 아무 이상도 없다.
        """
        for name in _TILE_ROUTES:
            with self.subTest(route=name):
                node = _function(self.tree, name)
                for decorator in node.decorator_list:
                    self.assertNotIn(
                        'cached', _called_names(decorator),
                        '%s 에 @cache.cached 가 다시 붙었습니다 — '
                        '캐시 대상은 응답이 아니라 타일 바이트여야 합니다' % name)


class TestFailuresAreNotCached(unittest.TestCase):
    """상류 장애를 굳히지 않는다."""

    def setUp(self):
        self.tree = _routes_geo_tree()

    def test_error_paths_send_no_cache(self):
        """빈 타일(투명 PNG)을 돌려주는 자리는 전부 `no-cache` 여야 한다.

        `_TRANSPARENT_1X1_PNG` 가 실린 응답에 장기 수명이 붙으면, 상류가 잠깐
        흔들린 대가로 그 타일이 몇 시간 동안 빈 채로 남는다 — 상류가 복구돼도
        사용자 화면은 복구되지 않는다.
        """
        found = 0
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            uses_blank = any(
                isinstance(arg, ast.Name) and arg.id == '_TRANSPARENT_1X1_PNG'
                for arg in node.args)
            if not uses_blank:
                continue
            found += 1
            source = ast.dump(node)
            self.assertIn('no-cache', source,
                          '빈 타일 응답에 no-cache 가 없습니다 (routes_geo.py '
                          '%d 행 부근)' % node.lineno)
        self.assertGreater(found, 0, '빈 타일 응답 자체를 찾지 못했습니다 — '
                                     '검사가 아무것도 안 보고 있습니다')


class TestWmsTileTtl(unittest.TestCase):
    """레이어별 수명 오버라이드."""

    def test_default_is_the_long_ttl(self):
        from aot.aot_flask import routes_geo

        self.assertEqual(routes_geo._WMS_TILE_TTL,
                         routes_geo._wms_tile_ttl({}))
        self.assertEqual(routes_geo._WMS_TILE_TTL,
                         routes_geo._wms_tile_ttl(None))

    def test_layer_can_shorten_its_own_ttl(self):
        """시간에 따라 변하는 WMS(기상 등)를 붙일 때의 탈출구."""
        from aot.aot_flask import routes_geo

        self.assertEqual(300, routes_geo._wms_tile_ttl({'cache_seconds': 300}))
        self.assertEqual(300, routes_geo._wms_tile_ttl({'cacheSeconds': '300'}))

    def test_garbage_falls_back_instead_of_disabling_the_cache(self):
        from aot.aot_flask import routes_geo

        for bad in ({'cache_seconds': 'soon'}, {'cache_seconds': 0},
                    {'cache_seconds': -1}, {'cache_seconds': None}):
            with self.subTest(value=bad):
                self.assertEqual(routes_geo._WMS_TILE_TTL,
                                 routes_geo._wms_tile_ttl(bad))


class TestDesktopOnlyTileCacheGarden(unittest.TestCase):
    """`maxTileCacheZoomLevels` 는 데스크탑에서만 켠다.

    MapLibre 4.1.2 의 화면 밖 타일 캐시 정원은
    `(한 화면분 타일 수) × maxTileCacheZoomLevels`(기본 5)다. 정원을 넓히면
    보관 텍스처 메모리 상한이 그대로 따라 오르므로(256×256 RGBA ≈ 256KB/장)
    폰에서는 켜지 않는다.

    **판정은 뷰포트 폭으로 하면 안 된다.** 폰을 가로로 눕히면 폭이 844px 가 되어
    `innerWidth > 768` 같은 기준은 그 순간 데스크탑이라고 답한다 — 이 값이 가장
    없어야 할 상황에서 켜지는 셈이다. 그래서 회전으로 뒤집히지 않는 신호만 쓴다.
    (배포 번들에서 판정 함수를 꺼내 실측: 폰 세로 390×844 · 폰 가로 844×390 둘 다
    False, 데스크탑 1920×1080 True.)
    """

    @classmethod
    def setUpClass(cls):
        with open(_MAP_WIDGET_JS, encoding='utf-8') as handle:
            cls.src = handle.read()
        match = re.search(
            r'function _isDesktopClass\(\) \{.*?\n    \}', cls.src, re.S)
        assert match, '_isDesktopClass 를 찾지 못했습니다'
        cls.predicate = match.group(0)

    def test_zoom_levels_option_is_gated_by_the_predicate(self):
        """설정하는 자리가 `_isDesktopClass()` 안에 있어야 한다."""
        self.assertIn('maxTileCacheZoomLevels', self.src)
        gate = re.search(
            r'if \(_isDesktopClass\(\)\) \{[^}]*maxTileCacheZoomLevels[^}]*\}',
            self.src, re.S)
        self.assertIsNotNone(
            gate, 'maxTileCacheZoomLevels 가 _isDesktopClass() 게이트 밖에 있습니다')

    def test_predicate_never_reads_orientation_dependent_sizes(self):
        """회전하면 값이 뒤집히는 신호를 쓰면 안 된다."""
        for banned in ('innerWidth', 'innerHeight', 'outerWidth', 'outerHeight',
                       'clientWidth', 'clientHeight', 'getBoundingClientRect'):
            with self.subTest(signal=banned):
                self.assertNotIn(
                    banned, self.predicate,
                    '%s 는 화면 회전으로 값이 바뀝니다 — 폰을 눕히면 데스크탑으로 '
                    '분류됩니다' % banned)

    def test_predicate_reads_screen_through_max(self):
        """`screen.width`/`height` 는 브라우저에 따라 회전 시 서로 바뀐다.

        `Math.max(...)` 로 긴 변을 잡으면 어느 쪽이든 같은 값이 된다.
        """
        self.assertIn('Math.max', self.predicate)
        self.assertIn('screen', self.predicate)

    def test_predicate_defaults_to_mobile_when_it_cannot_tell(self):
        """판정 불가(예외·신호 없음)면 기본값 유지 쪽으로 떨어져야 한다."""
        self.assertRegex(self.predicate, r'catch\s*\([^)]*\)\s*\{\s*return false;')
        self.assertRegex(self.predicate, r'if \(!longEdge \|\|')


if __name__ == '__main__':
    unittest.main()
