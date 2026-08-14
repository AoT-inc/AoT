# coding=utf-8
"""지도 거리 도구(`nearest`/`distance_between`)의 계약을 고정한다.

정본: aot/utils/geo_distance.py · docs/design/geo-vegetation-planting.md

여기서 지키는 것 중 **깨져도 조용한 것**이 여럿이다:

- 해석 못 한 후보가 결과 목록에서 그냥 빠지면, 짧아진 목록을 두고 "그건
  멀어서 빠졌나" 라고 읽게 된다. 없는 것과 먼 것은 다르다.
- 구획의 `name` 은 분할로 만들면 비어 있는 것이 **정상**이다. 표시명 폴백이
  없으면 결과가 `null` 다섯 줄이 된다(실제로 그런 데이터가 있다).
- 이 도구가 이름을 받기 시작하면 작물명이 구획이 아니라 소속 zone 으로
  해석되어, 한 zone 을 나눠 심은 품종들이 **전부 같은 거리**로 나온다.
  형식은 멀쩡하고 숫자만 틀리는 종류다.

DB 를 켜지 않는다 — 거리 계산과 정렬은 순수 함수이고, 개체 해석은
`resolve_point` 를 갈아 끼워 검증한다.
"""
import math
import unittest

from aot.utils import geo_distance


_KIMJE_LAT = 35.8
_KIMJE_LNG = 126.88


class _FakeRow(object):
    """`geometry_of()` 는 행에서 `feature` 만 읽는다 — DB 를 켤 이유가 없다."""

    def __init__(self, geometry, name=None, crop=None, variety=None,
                 unique_id='abcdef12-0000-0000-0000-000000000000'):
        self.feature = {'type': 'Feature', 'properties': {},
                        'geometry': geometry}
        self.name = name
        self.crop = crop
        self.variety = variety
        self.unique_id = unique_id


def _square_at(lng, lat, size_m):
    """(lng, lat) 를 좌하단으로 하는 size_m 정사각형."""
    m_lat = 111320.0
    m_lng = m_lat * math.cos(math.radians(lat))
    d_lat = size_m / m_lat
    d_lng = size_m / m_lng
    return {'type': 'Polygon', 'coordinates': [[
        [lng, lat], [lng + d_lng, lat], [lng + d_lng, lat + d_lat],
        [lng, lat + d_lat], [lng, lat],
    ]]}


class TestDistanceMath(unittest.TestCase):
    def test_known_north_south_distance(self):
        """위도 1도 = 111320 m — 저장소가 여섯 곳에서 쓰는 상수와 같아야 한다."""
        d = geo_distance.distance_m(_KIMJE_LAT, _KIMJE_LNG,
                                    _KIMJE_LAT + 1.0, _KIMJE_LNG)
        self.assertAlmostEqual(d, 111320.0, delta=1.0)

    def test_east_west_distance_shrinks_with_latitude(self):
        """경도 1도는 위도 35.8도에서 cos 만큼 짧다. 이 보정이 빠지면
        동서 거리가 23% 부풀고, 그 숫자가 그대로 배치 결정이 된다."""
        d = geo_distance.distance_m(_KIMJE_LAT, _KIMJE_LNG,
                                    _KIMJE_LAT, _KIMJE_LNG + 1.0)
        expected = 111320.0 * math.cos(math.radians(_KIMJE_LAT))
        self.assertAlmostEqual(d, expected, delta=1.0)

    def test_distance_is_symmetric_and_zero_at_same_point(self):
        a = geo_distance.distance_m(_KIMJE_LAT, _KIMJE_LNG, 35.81, 126.89)
        b = geo_distance.distance_m(35.81, 126.89, _KIMJE_LAT, _KIMJE_LNG)
        self.assertAlmostEqual(a, b, places=6)
        self.assertEqual(
            geo_distance.distance_m(_KIMJE_LAT, _KIMJE_LNG,
                                    _KIMJE_LAT, _KIMJE_LNG), 0.0)


class TestPlantingPoint(unittest.TestCase):
    def test_centroid_of_a_square(self):
        row = _FakeRow(_square_at(_KIMJE_LNG, _KIMJE_LAT, 100.0))
        lat, lng = geo_distance._planting_point(row)
        m_lat = 111320.0
        self.assertAlmostEqual(lat, _KIMJE_LAT + 50.0 / m_lat, places=6)

    def test_concave_plot_point_stays_inside(self):
        """면적 중심이 도형 밖으로 나가는 ㄷ자 구획. 밖의 점을 "이 구획의
        위치" 라고 말할 수는 없다."""
        from shapely.geometry import shape

        m_lat = 111320.0
        m_lng = m_lat * math.cos(math.radians(_KIMJE_LAT))

        def _p(x, y):
            return [_KIMJE_LNG + x / m_lng, _KIMJE_LAT + y / m_lat]

        u = {'type': 'Polygon', 'coordinates': [[
            _p(0, 0), _p(60, 0), _p(60, 40), _p(40, 40), _p(40, 10),
            _p(20, 10), _p(20, 40), _p(0, 40), _p(0, 0),
        ]]}
        poly = shape(u)
        self.assertFalse(poly.contains(poly.centroid), 'ㄷ자 전제가 깨졌다')

        lat, lng = geo_distance._planting_point(_FakeRow(u))
        from shapely.geometry import Point
        self.assertTrue(poly.contains(Point(lng, lat)),
                        '대표점이 구획 밖에 있다')

    def test_no_geometry_gives_none(self):
        self.assertIsNone(geo_distance._planting_point(_FakeRow({})))


class TestPlantingLabel(unittest.TestCase):
    """분할로 만든 구획은 `name` 이 비어 있다 — 작물명이 실질적 정체성이다."""

    def test_name_wins_when_present(self):
        self.assertEqual(
            geo_distance._planting_label(_FakeRow({}, name='앞두둑', crop='상추')),
            '앞두둑')

    def test_crop_and_variety_when_unnamed(self):
        self.assertEqual(
            geo_distance._planting_label(_FakeRow({}, crop='콩', variety='검정콩')),
            '콩 (검정콩)')

    def test_crop_alone_when_unnamed(self):
        self.assertEqual(
            geo_distance._planting_label(_FakeRow({}, crop='대선')), '대선')

    def test_falls_back_to_short_uuid_never_null(self):
        """`null` 다섯 줄을 내놓느니 uuid 앞자리라도 낸다."""
        label = geo_distance._planting_label(_FakeRow({}))
        self.assertTrue(label)
        self.assertEqual(label, 'abcdef12')


class _PointStub(object):
    """`resolve_point` 를 갈아 끼워 DB 없이 정렬·집계만 검증한다."""

    def __init__(self, mapping):
        self.mapping = mapping

    def __call__(self, target_id):
        return self.mapping.get(str(target_id))


def _pt(tid, lat, lng, name, ttype='planting'):
    return {'target_id': tid, 'target_type': ttype, 'resolved_name': name,
            'lat': lat, 'lng': lng}


class TestNearest(unittest.TestCase):
    def setUp(self):
        m_lat = 111320.0
        # 기준점에서 정북으로 100m, 200m, 300m — 일부러 뒤섞어 넣는다.
        self.points = {
            'ref': _pt('ref', _KIMJE_LAT, _KIMJE_LNG, '관리사무소', 'facility'),
            'far': _pt('far', _KIMJE_LAT + 300.0 / m_lat, _KIMJE_LNG, '새바람'),
            'near': _pt('near', _KIMJE_LAT + 100.0 / m_lat, _KIMJE_LNG, '대선'),
            'mid': _pt('mid', _KIMJE_LAT + 200.0 / m_lat, _KIMJE_LNG, '태청'),
        }
        self._orig = geo_distance.resolve_point
        geo_distance.resolve_point = _PointStub(self.points)

    def tearDown(self):
        geo_distance.resolve_point = self._orig

    def test_sorted_closest_first(self):
        out, err = geo_distance.nearest('ref', ['far', 'near', 'mid'])
        self.assertIsNone(err)
        self.assertEqual([r['resolved_name'] for r in out['results']],
                         ['대선', '태청', '새바람'])
        self.assertAlmostEqual(out['results'][0]['distance_m'], 100.0, delta=1.0)
        self.assertEqual(out['count'], 3)

    def test_unresolved_candidates_are_reported_not_dropped(self):
        """없는 것과 먼 것은 다르다 — 조용히 빠지면 구분할 방법이 없다."""
        out, err = geo_distance.nearest('ref', ['near', 'ghost-uuid'])
        self.assertIsNone(err)
        self.assertEqual(out['count'], 1)
        self.assertEqual(out['unresolved'], ['ghost-uuid'])

    def test_all_resolved_reports_none_not_empty_list(self):
        out, _err = geo_distance.nearest('ref', ['near', 'mid'])
        self.assertIsNone(out['unresolved'])

    def test_unknown_reference_is_an_error_not_an_empty_result(self):
        out, err = geo_distance.nearest('ghost', ['near'])
        self.assertIsNone(out)
        self.assertIn('could not locate', err)

    def test_empty_candidates_is_refused(self):
        out, err = geo_distance.nearest('ref', [])
        self.assertIsNone(out)
        self.assertIn('candidates is required', err)

    def test_too_many_candidates_is_refused_not_truncated(self):
        """조용히 자르면 호출자는 자기가 본 것이 전부인 줄 안다."""
        out, err = geo_distance.nearest('ref', ['near'] * 201)
        self.assertIsNone(out)
        self.assertIn('more than this tool compares', err)

    def test_coordinates_are_not_returned(self):
        """좌표를 돌려주면 호출자가 그것으로 다시 계산하기 시작한다 —
        거리를 서버가 내는 이유가 사라진다."""
        out, _err = geo_distance.nearest('ref', ['near'])
        for entry in out['results'] + [out['reference']]:
            self.assertNotIn('lat', entry)
            self.assertNotIn('lng', entry)

    def test_basis_says_centre_to_centre(self):
        """맞닿은 두 구획도 중심이 떨어져 있으면 그만큼으로 답한다 —
        경계 사이 최단거리로 오해하면 안 된다."""
        out, _err = geo_distance.nearest('ref', ['near'])
        self.assertIn('centre point', out['basis'])
        self.assertIn('NOT the shortest gap', out['basis'])


class TestDistanceBetween(unittest.TestCase):
    def setUp(self):
        m_lat = 111320.0
        self.points = {
            'a': _pt('a', _KIMJE_LAT, _KIMJE_LNG, '관리사무소', 'facility'),
            'b': _pt('b', _KIMJE_LAT + 150.0 / m_lat, _KIMJE_LNG, '대선'),
        }
        self._orig = geo_distance.resolve_point
        geo_distance.resolve_point = _PointStub(self.points)

    def tearDown(self):
        geo_distance.resolve_point = self._orig

    def test_reports_distance_and_both_ends(self):
        out, err = geo_distance.distance_between('a', 'b')
        self.assertIsNone(err)
        self.assertAlmostEqual(out['distance_m'], 150.0, delta=1.0)
        self.assertEqual(out['a']['resolved_name'], '관리사무소')
        self.assertEqual(out['b']['target_type'], 'planting')

    def test_either_end_unknown_is_an_error(self):
        for pair in (('a', 'ghost'), ('ghost', 'b')):
            out, err = geo_distance.distance_between(*pair)
            self.assertIsNone(out)
            self.assertIn('could not locate', err)


class TestResolvePointGuards(unittest.TestCase):
    """DB 없이도 확인되는 입구 조건."""

    def test_blank_ids_resolve_to_nothing(self):
        for bad in (None, '', '   ', 'none', 'None'):
            self.assertIsNone(geo_distance.resolve_point(bad))


class _Shape(object):
    """`_point_from_shape` 는 행에서 feature/type/unique_id 만 읽는다."""

    def __init__(self, name, uid, stype='zone', lat=_KIMJE_LAT, lng=_KIMJE_LNG):
        self.unique_id = uid
        self.type = stype
        self._c = (lat, lng)
        self.feature = {'type': 'Feature',
                        'properties': {'name': name},
                        'geometry': None}

    def get_centroid(self):
        return self._c


class _NameFixture(object):
    """이름 해석 3층(도형·구획·장치)을 DB 없이 갈아 끼운다."""

    def __init__(self, test, shapes=(), plantings=(), devices=()):
        self.t = test
        self.shapes = list(shapes)
        self.plantings = list(plantings)
        self.devices = list(devices)

    def __enter__(self):
        g = geo_distance
        self._orig = (g._named_shapes, g._active_planting_rows,
                      g._named_devices, g.resolve_point)
        g._named_shapes = lambda: [
            (s, (s.feature['properties']['name'] or '').lower())
            for s in self.shapes]
        g._active_planting_rows = lambda: list(self.plantings)
        g._named_devices = lambda: list(self.devices)
        # uuid 경로는 등록된 행에서만 맞는다 — 이름 층위를 검증하려는 것이므로
        # 실제 DB 조회는 타지 않게 한다.
        by_id = {s.unique_id: geo_distance._point_from_shape(s)
                 for s in self.shapes}
        by_id.update({r.unique_id: geo_distance._point_from_planting(r)
                      for r in self.plantings})
        g.resolve_point = lambda tid: by_id.get(str(tid or '').strip())
        return self

    def __exit__(self, *exc):
        (geo_distance._named_shapes, geo_distance._active_planting_rows,
         geo_distance._named_devices, geo_distance.resolve_point) = self._orig
        return False


def _plot(crop, uid, lat=_KIMJE_LAT, lng=_KIMJE_LNG, name=None, variety=None):
    return _FakeRow(_square_at(lng, lat, 10.0), name=name, crop=crop,
                    variety=variety, unique_id=uid)


class TestNameResolution(unittest.TestCase):
    """이름은 받되, **모호하면 고르지 않는다**.

    쓰기 리졸버(`_resolve_note_target`)는 작물명을 소속 zone 으로 치환하므로
    한 zone 을 나눠 심은 품종들이 전부 같은 좌표가 된다. 여기는 읽기전용이라
    구획 자신을 가리킬 수 있고, 여러 개면 후보를 돌려줄 수 있다.
    """

    def test_zone_name_resolves_to_the_shape(self):
        with _NameFixture(self, shapes=[_Shape('3-1', 'zone-uuid-1')]):
            point, cands = geo_distance.resolve_query('3-1')
            self.assertEqual(cands, [])
            self.assertEqual(point['target_id'], 'zone-uuid-1')
            self.assertEqual(point['target_type'], 'zone')

    def test_crop_name_resolves_to_the_PLOT_not_its_zone(self):
        """이 도구가 존재하는 이유 — 쓰기 리졸버였다면 zone 이 나온다."""
        with _NameFixture(self,
                          shapes=[_Shape('3-2', 'zone-uuid-2')],
                          plantings=[_plot('대선', 'plot-uuid-1')]):
            point, cands = geo_distance.resolve_query('대선')
            self.assertEqual(cands, [])
            self.assertEqual(point['target_id'], 'plot-uuid-1')
            self.assertEqual(point['target_type'], 'planting')

    def test_same_crop_in_several_plots_is_ambiguous_not_guessed(self):
        """검정콩을 다섯 조각에 심었으면 "검정콩까지 거리" 는 답이 없다.

        하나를 골라 답하면 그 숫자가 조용히 틀린다. 실제로 1-4 구역이
        이 상태다(같은 작물, 다섯 구획).
        """
        plots = [_plot('검정콩', 'p%d' % i) for i in range(5)]
        with _NameFixture(self, plantings=plots):
            point, cands = geo_distance.resolve_query('검정콩')
            self.assertIsNone(point)
            self.assertEqual(len(cands), 5)

    def test_shape_name_wins_over_a_plot_with_the_same_name(self):
        """지도의 정식 어휘가 항상 이긴다 — 층위가 섞이면 안 된다."""
        with _NameFixture(self,
                          shapes=[_Shape('3-1', 'zone-uuid-1')],
                          plantings=[_plot('콩', 'plot-uuid-1', name='3-1')]):
            point, _c = geo_distance.resolve_query('3-1')
            self.assertEqual(point['target_id'], 'zone-uuid-1')

    def test_uuid_still_wins_over_name_search(self):
        """도구 체이닝(앞선 호출이 낸 uuid)이 이름 검색을 거치면 안 된다."""
        with _NameFixture(self, plantings=[_plot('대선', 'plot-uuid-1')]):
            point, _c = geo_distance.resolve_query('plot-uuid-1')
            self.assertEqual(point['target_id'], 'plot-uuid-1')

    def test_ended_plantings_are_not_searched(self):
        """작년 배추가 올해 거리 질문을 끌고 가면 안 된다 — `_active_planting_rows`
        가 활성만 내는 것에 의존한다(그 계약을 여기서 고정한다)."""
        import inspect
        src = inspect.getsource(geo_distance._active_planting_rows)
        self.assertIn('active_plantings', src)

    def test_one_character_query_does_not_fuzzy_match(self):
        """'마' 가 '고구마' 에 걸리면 오매치가 기본값이 된다."""
        with _NameFixture(self, plantings=[_plot('고구마', 'plot-uuid-1')]):
            point, cands = geo_distance.resolve_query('마')
            self.assertIsNone(point)
            self.assertEqual(cands, [])

    def test_substring_match_when_nothing_exact(self):
        with _NameFixture(self, shapes=[_Shape('1포장 남측', 'zone-uuid-9')]):
            point, _c = geo_distance.resolve_query('남측')
            self.assertEqual(point['target_id'], 'zone-uuid-9')

    def test_unknown_name_is_not_found_not_ambiguous(self):
        with _NameFixture(self, shapes=[_Shape('3-1', 'zone-uuid-1')]):
            point, cands = geo_distance.resolve_query('없는이름')
            self.assertIsNone(point)
            self.assertEqual(cands, [])


class TestAmbiguitySurfacing(unittest.TestCase):
    """모호함이 도구 응답까지 그대로 올라와야 되물을 수 있다."""

    def test_distance_between_returns_candidates_with_ids(self):
        """후보를 uuid 와 함께 내야 다음 호출이 uuid 로 되물을 수 있다 —
        이름으로 되물으면 같은 자리에 다시 걸린다."""
        plots = [_plot('검정콩', 'p%d' % i) for i in range(3)]
        with _NameFixture(self, shapes=[_Shape('관리사무소', 'fac-1', 'facility')],
                          plantings=plots):
            out, err = geo_distance.distance_between('관리사무소', '검정콩')
            self.assertIsNone(out)
            self.assertIsInstance(err, dict)
            self.assertTrue(err['needs_disambiguation'])
            self.assertEqual(err['candidates_total'], 3)
            for c in err['candidates']:
                self.assertTrue(c['target_id'])

    def test_nearest_separates_ambiguous_from_unresolved(self):
        """없는 것과 못 고른 것은 다르다 — 후자는 되물으면 해결된다."""
        plots = [_plot('검정콩', 'p1'), _plot('검정콩', 'p2'),
                 _plot('대선', 'p3')]
        with _NameFixture(self, shapes=[_Shape('관리사무소', 'fac-1', 'facility')],
                          plantings=plots):
            out, err = geo_distance.nearest(
                '관리사무소', ['대선', '검정콩', '없는이름'])
            self.assertIsNone(err)
            self.assertEqual(out['count'], 1)
            self.assertEqual(out['unresolved'], ['없는이름'])
            self.assertEqual(len(out['ambiguous']), 1)
            self.assertEqual(out['ambiguous'][0]['query'], '검정콩')
            self.assertEqual(out['ambiguous'][0]['candidates_total'], 2)

    def test_clean_run_reports_none_not_empty_lists(self):
        with _NameFixture(self, shapes=[_Shape('관리사무소', 'fac-1', 'facility')],
                          plantings=[_plot('대선', 'p1')]):
            out, _err = geo_distance.nearest('관리사무소', ['대선'])
            self.assertIsNone(out['unresolved'])
            self.assertIsNone(out['ambiguous'])


class TestWriteResolverIsNotBorrowed(unittest.TestCase):
    """쓰기 리졸버를 끌어다 쓰면 작물명이 zone 으로 뭉개지는 함정이 그대로
    들어온다. 그 리졸버는 `add_schedule`·`create_note` 가 쓰는 것이라
    고칠 수도 없다(target 은 쓸 수 있는 GeoShape 여야 한다)."""

    def test_note_target_resolver_is_not_called(self):
        import inspect

        src = inspect.getsource(geo_distance)
        self.assertNotIn('_resolve_note_target(', src)
        self.assertNotIn('_resolve_target_by_crop(', src)

    def test_tool_schema_accepts_names(self):
        from aot.ai.services import tool_registry

        payloads = {p['tool_name']: p
                    for p in tool_registry._MCP_TOOL_PAYLOADS
                    if 'tool_name' in p}
        for name in ('distance_between', 'nearest'):
            self.assertIn(name, payloads, '%s 가 MCP 매니페스트에서 사라졌다' % name)
            desc = payloads[name]['description']
            # 모호할 때 고르지 말라는 지시가 설명에서 사라지면, 모델이 하나를
            # 골라 답하기 시작한다.
            self.assertTrue(
                'ambiguous' in desc.lower() or 'disambiguation' in desc.lower(),
                '%s 설명에 모호성 처리 지시가 없다' % name)


if __name__ == '__main__':
    unittest.main()
