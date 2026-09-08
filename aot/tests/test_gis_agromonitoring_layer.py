# coding=utf-8
"""Agromonitoring 레이어 — 단위·폴리곤 매칭 (2026-09-07).

## 왜 만들었나

토양 수분·지온을 **숫자로** 주는 유일한 레이어다. SMAP 오버레이는 9km 그림이고,
NASA GIBS 범례의 토양 수분 숫자는 Open-Meteo 모델값을 빌려 온 것이다.

## 이 테스트가 지키는 것

**① 단위.** 지온이 **켈빈**으로 온다(문서 명시). 변환을 빠뜨리면 지온 300 이
그대로 화면에 뜬다 — 에러가 없어 화면만 봐서는 "이상하네" 로 끝난다.

**② 폴리곤 매칭.** 이 API 는 좌표가 아니라 등록된 폴리곤 id 로 조회한다.
링이 닫혀 있든(첫 점 = 끝 점) 열려 있든 같은 답이 나와야 한다 — 열린 링에
예외를 던지는 판정기(turf `booleanPointInPolygon`)로 한 번 데인 적이 있다.

⚠ 네트워크를 쓰지 않는다. 상류 응답은 문서의 예시를 그대로 쓴다.
"""
import time

import pytest

from aot.inputs_gis import gis_agromonitoring as ag


def polygon(pid, ring, center=None):
    return {
        'id': pid,
        'center': center or list(ring[0]),
        'geo_json': {'geometry': {'type': 'Polygon', 'coordinates': [ring]}},
    }


CLOSED = [[127.0, 35.0], [127.1, 35.0], [127.1, 35.1], [127.0, 35.1], [127.0, 35.0]]
OPEN = CLOSED[:-1]
FAR = [[128.0, 36.0], [128.1, 36.0], [128.1, 36.1], [128.0, 36.1], [128.0, 36.0]]


class TestUnits:
    """① 켈빈으로 온다."""

    def test_문서_예시값_변환(self):
        """문서 예시: t10 281.96 K, t0 279.02 K."""
        assert ag._kelvin_to_c(281.96) == 8.81
        assert ag._kelvin_to_c(279.02) == 5.87

    def test_망가진_값은_None(self):
        assert ag._kelvin_to_c(None) is None
        assert ag._kelvin_to_c('') is None

    def test_토양_조회가_섭씨로_돌려준다(self, monkeypatch):
        """변환을 빠뜨리면 지온 300 이 화면에 그대로 뜬다."""
        captured = {}

        class FakeResp:
            status_code = 200

            @staticmethod
            def json():
                return {'dt': 1522108800, 't10': 281.96,
                        'moisture': 0.175, 't0': 279.02}

        def fake_get(url, params=None, timeout=None):
            captured['url'] = url
            captured['params'] = params
            return FakeResp()

        monkeypatch.setattr(ag.requests, 'get', fake_get)
        soil = ag.fetch_soil('KEY', 'POLY')

        assert soil['t10'] == 8.81 and soil['t0'] == 5.87
        assert soil['moisture'] == 0.175
        assert captured['params']['polyid'] == 'POLY'
        assert captured['url'].endswith('/soil')

    def test_상류_실패는_빈_결과다(self, monkeypatch):
        class FakeResp:
            status_code = 401
            text = 'Invalid API key'

        monkeypatch.setattr(ag.requests, 'get',
                            lambda *a, **k: FakeResp())
        assert ag.fetch_soil('KEY', 'POLY') == {}


class TestPolygonMatching:
    """② 링이 닫혀 있든 열려 있든 같은 답."""

    @pytest.mark.parametrize('ring', [CLOSED, OPEN])
    def test_안에_있는_점(self, ring):
        assert ag._polygon_contains(polygon('p', ring), 35.05, 127.05)

    @pytest.mark.parametrize('ring', [CLOSED, OPEN])
    def test_밖에_있는_점(self, ring):
        assert not ag._polygon_contains(polygon('p', ring), 36.0, 127.05)
        assert not ag._polygon_contains(polygon('p', ring), 35.05, 128.0)

    def test_MultiPolygon_도_본다(self):
        poly = {'geo_json': {'geometry': {
            'type': 'MultiPolygon', 'coordinates': [[FAR], [CLOSED]]}}}
        assert ag._polygon_contains(poly, 35.05, 127.05)

    def test_망가진_도형에_죽지_않는다(self):
        assert not ag._polygon_contains({}, 35.0, 127.0)
        assert not ag._polygon_contains(
            {'geo_json': {'geometry': {'type': 'Point',
                                       'coordinates': [127.0, 35.0]}}},
            35.0, 127.0)
        assert not ag._polygon_contains(
            {'geo_json': {'geometry': {'type': 'Polygon',
                                       'coordinates': [[[127.0, 35.0]]]}}},
            35.0, 127.0)


class TestPolygonResolution:
    """어느 폴리곤으로 조회할지 고르는 규칙."""

    @pytest.fixture(autouse=True)
    def seed_cache(self):
        ag._polygon_cache['KEY'] = (
            [polygon('near', CLOSED), polygon('far', FAR)],
            time.time() + 60)
        yield
        ag._polygon_cache.pop('KEY', None)

    def test_명시한_id_가_우선이다(self):
        assert ag.resolve_polygon_id(
            'KEY', 35.05, 127.05, explicit_id='manual') == 'manual'

    def test_점을_포함하는_폴리곤을_고른다(self):
        assert ag.resolve_polygon_id('KEY', 35.05, 127.05) == 'near'

    def test_어디에도_안_들어가면_가장_가까운_중심(self):
        """필지 옆을 눌렀다고 값이 아예 안 나오는 것보다 낫다."""
        assert ag.resolve_polygon_id('KEY', 35.2, 127.05) == 'near'
        assert ag.resolve_polygon_id('KEY', 36.2, 128.05) == 'far'

    def test_등록된_폴리곤이_없으면_None(self):
        ag._polygon_cache['EMPTY'] = ([], time.time() + 60)
        try:
            assert ag.resolve_polygon_id('EMPTY', 35.05, 127.05) is None
        finally:
            ag._polygon_cache.pop('EMPTY', None)


class TestLayerShape:
    """타일 없이 값만 그린다."""

    class FakeDev:
        unique_id = 'agro-uid'
        name = 'Field NDVI'
        log_level_debug = False

    def make_layer(self, **options):
        opts = {'api_key': 'SECRETKEY', 'polygon_id': '',
                'active_channels': [0, 1, 2], 'ndvi_window_days': '30'}
        opts.update(options)
        inst = ag.InputModule(self.FakeDev(), testing=True)
        # 운영에서는 AbstractInput 이 채워 주는 값. 범례의 프록시 URL 이 이걸
        # 쓰므로 테스트에서도 같게 둔다.
        inst.unique_id = self.FakeDev.unique_id
        inst.custom_options = opts
        inst.get_custom_option = lambda opt, default=None: opts.get(opt, default)
        return inst

    def test_타일_레이어가_아니다(self):
        """무료 등급의 호출 한도가 공개돼 있지 않아 그림은 붙이지 않는다."""
        assert ag.INPUT_INFORMATION['layer_type'] == 'none'
        assert self.make_layer().get_url() == ''

    def test_범례가_프록시를_거치고_키를_노출하지_않는다(self):
        legend = self.make_layer().get_legend()
        assert '/api/geo/proxy/agromonitoring/agro-uid' in legend['content']
        assert 'SECRETKEY' not in legend['content']

    def test_범례_항목이_채널_키와_맞는다(self):
        """`data-api-param` 이 응답 필드명과 어긋나면 값이 영영 '--' 다."""
        legend = self.make_layer(active_channels=[0, 1, 2, 3]).get_legend()
        for info in ag.CHANNELS.values():
            assert 'data-api-param="%s"' % info['options']['key'] in legend['content']

    def test_키가_없으면_상류를_부르지_않는다(self, monkeypatch):
        def explode(*_a, **_k):
            raise AssertionError('네트워크를 타면 안 된다')

        monkeypatch.setattr(ag.requests, 'get', explode)
        assert self.make_layer(api_key='').get_data_at_location(35.05, 127.05) is None


class TestRegistration:
    def test_필수_키가_있다(self):
        for key in ('input_name_unique', 'input_name', 'key_field',
                    'global_key_field', 'custom_options'):
            assert key in ag.INPUT_INFORMATION, key

    def test_OpenWeather_와_전역키를_섞지_않는다(self):
        """같은 계정이라도 키 저장 칸은 별개다 — 한쪽을 지우면 다른 쪽이 죽는다."""
        assert ag.INPUT_INFORMATION['global_key_field'] == 'agromonitoring'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
