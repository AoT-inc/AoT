# coding=utf-8
"""위치 조회 문(aot_flask/geo/geo_lookup.py) — 주소 → 좌표를 GIS 입력의 검색 API 로 푸는 단일 입구.

공급자 호출은 가짜로 바꾼다(외부 호출 없음). 문이 하는 일만 본다: 공급자 고르기, 결과 모양 맞추기,
실패 이유 나누기, 지도 검색창·MCP 가 같은 문을 쓰는지.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from aot.aot_flask.geo import geo_lookup as G


class _FakeProvider:
    def __init__(self, raw):
        self.raw = raw
        self.calls = []

    def search(self, query, search_type='address', **kw):
        self.calls.append((query, search_type, kw))
        return self.raw


def _gate(raw, layer_type='gis_vworld'):
    prov = _FakeProvider(raw)
    patcher = patch.object(G, '_load_provider', return_value=(prov, layer_type))
    return prov, patcher


class TestFindLocation(unittest.TestCase):

    def setUp(self):
        p = patch.object(G, 'chosen_provider_id', return_value='layer-1')
        p.start()
        self.addCleanup(p.stop)
        p2 = patch.object(G, 'search_providers', return_value=[{'id': 'layer-1', 'type': 'gis_vworld'}])
        p2.start()
        self.addCleanup(p2.stop)

    def test_normalizes_and_dedups(self):
        prov, patcher = _gate([
            {'name': '영양군청', 'lat': '36.6667', 'lng': 129.1124, 'address': '경북 영양군 영양읍', 'meta': {'x': 1}},
            {'name': '중복', 'lat': 36.6667, 'lng': 129.1124, 'address': '같은 좌표'},
            {'name': '영점', 'lat': 0, 'lng': 0},
            {'name': '범위 밖', 'lat': 95, 'lng': 10},
            {'lat': 36.5, 'lng': 129.0, 'address': '이름 없음'},
        ])
        with patcher:
            out = G.find_location('  영양군청 ')
        self.assertEqual('ok', out['status'])
        self.assertEqual(2, out['count'])
        first = out['results'][0]
        self.assertEqual({'name', 'lat', 'lng', 'address', 'provider'}, set(first))
        self.assertEqual((36.6667, 129.1124), (first['lat'], first['lng']))
        self.assertEqual('gis_vworld', first['provider'])
        self.assertEqual('이름 없음', out['results'][1]['name'])      # 이름이 없으면 주소
        self.assertEqual('영양군청', prov.calls[0][0])               # 앞뒤 공백 제거
        self.assertEqual({'id': 'layer-1', 'type': 'gis_vworld'}, out['provider'])

    def test_limit_is_clamped_and_forwarded(self):
        rows = [{'name': str(i), 'lat': 30 + i * 0.01, 'lng': 120} for i in range(30)]
        prov, patcher = _gate(rows)
        with patcher:
            out = G.find_location('x', limit=999)
        self.assertEqual(G.MAX_RESULTS, out['count'])
        self.assertEqual(G.MAX_RESULTS, prov.calls[0][2]['limit'])
        prov2, patcher2 = _gate(rows)
        with patcher2:
            out2 = G.find_location('x', limit='abc')
        self.assertEqual(G.DEFAULT_RESULTS, out2['count'])

    def test_explicit_provider_wins_over_chosen(self):
        prov, patcher = _gate([{'name': 'a', 'lat': 1, 'lng': 2}])
        with patcher as m:
            out = G.find_location('x', provider='gis_google')
        m.assert_called_once_with('gis_google')
        self.assertEqual('gis_google', out['provider']['id'])

    def test_chosen_provider_used_when_none_given(self):
        prov, patcher = _gate([{'name': 'a', 'lat': 1, 'lng': 2}])
        with patcher as m:
            G.find_location('x')
        m.assert_called_once_with('layer-1')

    def test_no_match_is_not_an_error(self):
        _prov, patcher = _gate([])
        with patcher:
            out = G.find_location('없는 곳')
        self.assertEqual('no_match', out['status'])
        self.assertEqual([], out['results'])

    def test_missing_key_and_provider_error_codes(self):
        _p, patcher = _gate({'error': 'API Key Missing'})
        with patcher:
            out = G.find_location('x')
        self.assertEqual(('error', 'no_key'), (out['status'], out['code']))
        self.assertIn('providers', out)                              # 쓸 수 있는 입력을 알려 준다
        _p, patcher = _gate({'error': 'Nominatim API Error (403)'})
        with patcher:
            self.assertEqual('failed', G.find_location('x')['code'])

    def test_provider_unusable(self):
        with patch.object(G, '_load_provider', side_effect=G.GeoLookupError('provider_not_found', 'Provider not found', 404)):
            out = G.find_location('x', provider='nope')
        self.assertEqual('provider_not_found', out['code'])
        with patch.object(G, '_load_provider', side_effect=RuntimeError('boom')):
            out = G.find_location('x')
        self.assertEqual(('error', 'failed'), (out['status'], out['code']))
        _p, patcher = _gate(None)
        with patcher:
            self.assertEqual('not_supported', G.find_location('x')['code'])

    def test_empty_query(self):
        self.assertEqual('missing_query', G.find_location('   ')['code'])
        self.assertEqual('missing_query', G.find_location(None)['code'])


class TestFindAddress(unittest.TestCase):
    """좌표 → 주소 — 같은 문, 같은 오류 이름."""

    def _with(self, raw, layer_type='gis_osm'):
        prov = type('P', (), {'reverse': lambda self_, lat, lng: raw})()
        return patch.object(G, '_load_provider', return_value=(prov, layer_type))

    def setUp(self):
        for target, val in (('_reverse_provider_id', 'gis_osm'), ('reverse_providers', [])):
            p = patch.object(G, target, return_value=val)
            p.start()
            self.addCleanup(p.stop)

    def test_ok(self):
        with self._with({'address': ' 1 Main St ', 'type': 'road'}):
            out = G.find_address('37.5', 127)
        self.assertEqual(('ok', '1 Main St', 'road'), (out['status'], out['address'], out['type']))
        self.assertEqual((37.5, 127.0), (out['lat'], out['lng']))
        self.assertEqual({'id': 'gis_osm', 'type': 'gis_osm'}, out['provider'])

    def test_errors(self):
        with self._with({'error': 'Token Missing', 'code': 'no_key'}):
            self.assertEqual('no_key', G.find_address(37.5, 127)['code'])
        with self._with({'error': 'no result'}):
            self.assertEqual('failed', G.find_address(37.5, 127)['code'])
        with self._with(None):
            self.assertEqual('not_supported', G.find_address(37.5, 127)['code'])
        self.assertEqual('bad_coordinates', G.find_address('x', 127)['code'])
        self.assertEqual('bad_coordinates', G.find_address(91, 127)['code'])

    def test_explicit_provider(self):
        with self._with({'address': 'a'}) as m:
            G.find_address(37.5, 127, provider='gis_google')
        m.assert_called_once_with('gis_google')


class TestReverseProviderOrder(unittest.TestCase):
    """지도 설정의 검색 공급자(역방향 가능) → 등록된 켜진 역방향 입력(옛 VWorld 설치 유지) → 기본."""

    def _order(self, setting, candidates):
        sett = type('S', (), {'providers': '{"search_provider": "%s"}' % setting if setting else '{}'})()
        with patch('aot.databases.models.GeoSetting') as gs, \
                patch.object(G, 'reverse_providers', return_value=candidates):
            gs.query.first.return_value = sett
            return G._reverse_provider_id()

    def test_order(self):
        vw = {'id': 'lay-vw', 'type': 'gis_vworld', 'name': 'v', 'activated': True}
        off = {'id': 'lay-off', 'type': 'gis_google', 'name': 'g', 'activated': False}
        self.assertEqual('lay-off', self._order('lay-off', [vw, off]))        # 고른 공급자가 역방향을 하면 그것
        self.assertEqual('lay-vw', self._order('lay-search-only', [vw, off]))  # 못 하면 등록된 켜진 것
        self.assertEqual('lay-vw', self._order(None, [off, vw]))
        self.assertEqual(G.DEFAULT_PROVIDER, self._order(None, [off]))         # 켜진 게 없으면 기본


class TestOneGate(unittest.TestCase):
    """호출처가 공급자 이름이나 키 읽기를 따로 갖지 않는다."""

    def test_service_tool_goes_through_gate(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        with patch.object(G, 'find_location', return_value={'status': 'ok'}) as m:
            AoTDataToolService.find_location(query='영양', provider='', limit='3')
        m.assert_called_once_with('영양', provider=None, limit='3')

    def test_map_search_route_uses_gate(self):
        import inspect
        from aot.aot_flask.api import geo
        src = inspect.getsource(geo.GeoSearch.post)
        self.assertIn('geo_lookup.raw_search', src)
        self.assertNotIn('load_module_from_file', src)

    def test_tool_is_registered_as_domain_op(self):
        from aot.tools import tool_registry as R
        from aot.tools.domain.registry_data import OPS
        self.assertIn('find_location', R.DOMAIN_ONLY_TOOLS)
        op = next(o for o in OPS if (o.tool, o.op) == ('find', 'location'))
        self.assertEqual({'none': 'find_location'}, op.inner)
        self.assertEqual('read', op.effect)
        self.assertNotIn('find_location', R.approval_required_tools())


class TestProviderLoading(unittest.TestCase):
    """실제 GIS 입력 모듈과 DB 로: 키는 레이어 옵션 → 지도 전역 키 순, 종류 이름으로도 부른다."""

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import GeoLayer, GeoSetting

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(cls._tmp.name, 'lookup.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()
        db.session.add(GeoLayer(unique_id='lay-own', name='내 VWorld', type='gis_vworld',
                                options='{"api_key": "OWN-KEY"}', is_activated=True))
        db.session.add(GeoLayer(unique_id='lay-nokey', name='키 없는 구글', type='gis_google',
                                options='{}', is_activated=True))
        db.session.add(GeoSetting(keys='{"google_maps": "GLOBAL-KEY"}',
                                  providers='{"search_provider": "lay-own"}'))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def test_chosen_provider_from_map_settings(self):
        self.assertEqual('lay-own', G.chosen_provider_id())

    def test_layer_key_and_type_name_lookup(self):
        inst, layer_type = G._load_provider('lay-own')
        self.assertEqual('gis_vworld', layer_type)
        self.assertEqual('OWN-KEY', inst.get_custom_option('api_key'))
        inst2, type2 = G._load_provider('gis_vworld')                 # 종류 이름 → 등록된 레이어 옵션 물려받기
        self.assertEqual('gis_vworld', type2)
        self.assertEqual('OWN-KEY', inst2.get_custom_option('api_key'))

    def test_global_key_fallback(self):
        from aot.utils.inputs import parse_input_information
        kf = parse_input_information().get('gis_google', {}).get('key_field')
        if not kf:
            self.skipTest('gis_google declares no key_field')
        inst, _t = G._load_provider('lay-nokey')
        self.assertEqual('GLOBAL-KEY', inst.get_custom_option(kf))

    def test_unknown_provider(self):
        with self.assertRaises(G.GeoLookupError) as cm:
            G._load_provider('definitely-not-a-provider')
        self.assertEqual(404, cm.exception.status)

    def test_new_provider_is_usable_without_touching_the_gate(self):
        """나라·공급자와 무관 — search_capabilities 선언 + search() 만 있으면 목록·조회에 그대로 나온다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoLayer
        src = os.path.join(self._tmp.name, 'gis_dummy.py')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(
                "from aot.inputs_gis.base_input_gis import AbstractGisInput\n"
                "class InputModule(AbstractGisInput):\n"
                "    search_capabilities = ['address']\n"
                "    def search(self, query, search_type='address', **kw):\n"
                "        if query == 'nokey':\n"
                "            return {'error': 'needs a token', 'code': 'no_key'}\n"
                "        return [{'name': query, 'lat': -33.8688, 'lng': 151.2093, 'address': 'Sydney NSW'}]\n")
        db.session.add(GeoLayer(unique_id='lay-dummy', name='Dummy Geocoder', type='gis_dummy',
                                options='{}', is_activated=True))
        db.session.commit()
        self.addCleanup(lambda: (GeoLayer.query.filter_by(unique_id='lay-dummy').delete(), db.session.commit()))
        from aot.utils.inputs import parse_input_information
        real = parse_input_information()
        patched = dict(real, gis_dummy={'file_path': src})
        with patch('aot.utils.inputs.parse_input_information', return_value=patched):
            self.assertIn('lay-dummy', {p['id'] for p in G.search_providers()})
            for ref in ('lay-dummy', 'gis_dummy', 'Dummy Geocoder'):        # id · 종류 · 이름 어느 쪽으로도
                out = G.find_location('Sydney Opera House', provider=ref)
                self.assertEqual('ok', out['status'], ref)
                self.assertEqual(-33.8688, out['results'][0]['lat'])
            self.assertEqual('no_key', G.find_location('nokey', provider='lay-dummy')['code'])   # 공급자가 준 code 통과

    def test_search_providers_lists_only_address_capable(self):
        ids = {p['id'] for p in G.search_providers()}
        self.assertIn('lay-own', ids)


if __name__ == '__main__':
    unittest.main()
