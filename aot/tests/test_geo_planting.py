# coding=utf-8
"""식생 구획(작기)의 불변식과 계약을 고정한다.

설계 정본: docs/design/geo-vegetation-planting.md

여기서 지키는 것 중 **깨져도 조용한 것**이 여럿이다:

- 겹침을 막는 제약이 나중에 들어오면(유니크 인덱스·검증) 간작·혼작이
  저장에서 거부된다. 정상 기능이 DB 에서 막히는 형태라 원인 도달이 늦다.
- 식생 구획이 `device_membership._CONTAINER_TYPES` 에 끼면 장치의 **소속**이
  작기마다 바뀌고, 작기가 끝나는 순간 그 장치가 무소속이 된다. 지도는
  멀쩡해 보이고 소속만 조용히 흔들린다.
- `typesToSync` 에 'vegetation' 이 들어가면 GeoShape 전량교체 저장 경로가
  식생을 자기 것으로 착각한다.
- `theme_keys` 화이트리스트에 'theme_vegetation' 이 없으면 색 피커는 색이
  바뀐 것처럼 보이고 새로고침하면 되돌아온다(2026-08-08 device_unit 이 그랬다).
- 미배정 면적을 단순 합으로 빼면 겹친 만큼 이중으로 빠져 음수가 된다.

DB 를 쓰는 것은 저장 경로 검증뿐이고, 나머지는 순수 계산·소스 검사다.
"""
import ast
import json
import os
import unittest
from datetime import date, timedelta

_HERE = os.path.dirname(__file__)
_ROOT = os.path.join(_HERE, '..')

_MEMBERSHIP = os.path.join(_ROOT, 'aot_flask', 'geo', 'device_membership.py')
_MIGRATION = os.path.join(_ROOT, '..', 'alembic_db', 'alembic', 'versions',
                          'p6_34_geo_planting_20260813.py')
_ROUTES_GEO = os.path.join(_ROOT, 'aot_flask', 'routes_geo.py')
_DESIGN_JS = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                          'aot-geo-design-v3.js')
_THEME_JS = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'common',
                         'aot-geo-theme-colors.js')
_MODEL = os.path.join(_ROOT, 'databases', 'models', 'geo_planting.py')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _square(x0, y0, size):
    """(x0,y0) 에서 시작하는 정사각형 Polygon geometry."""
    return {
        'type': 'Polygon',
        'coordinates': [[
            [x0, y0], [x0 + size, y0], [x0 + size, y0 + size],
            [x0, y0 + size], [x0, y0],
        ]],
    }


# ---------------------------------------------------------------------------
# 1. 면적 — 겹침이 있어도 미배정이 음수가 되지 않는다
# ---------------------------------------------------------------------------

class TestAreaMath(unittest.TestCase):
    def setUp(self):
        from aot.aot_flask.geo import planting_context
        self.ctx = planting_context

    def _sh(self, geom):
        from shapely.geometry import shape
        return shape(geom)

    def test_area_of_known_square_is_close_to_expected(self):
        """0.001도 정사각형(적도 부근) ≈ 111.32m × 111.32m."""
        area = self.ctx.shapely_area_m2(self._sh(_square(0.0, 0.0, 0.001)))
        expected = 111.32 * 111.32
        self.assertAlmostEqual(area, expected, delta=expected * 0.02)

    def test_interior_ring_is_subtracted(self):
        """구멍을 빼지 않으면 미배정 면적이 실제보다 작게(음수까지) 나온다."""
        from shapely.geometry import Polygon

        outer = [(0, 0), (0.001, 0), (0.001, 0.001), (0, 0.001), (0, 0)]
        hole = [(0.0002, 0.0002), (0.0008, 0.0002),
                (0.0008, 0.0008), (0.0002, 0.0008), (0.0002, 0.0002)]
        donut = Polygon(outer, [hole])
        solid = Polygon(outer)

        self.assertLess(self.ctx.shapely_area_m2(donut),
                        self.ctx.shapely_area_m2(solid))

    def test_union_of_overlapping_plots_counts_overlap_once(self):
        """겹친 구획 둘의 합집합 < 단순 합. 이것이 미배정 계산의 근거다."""
        from shapely.ops import unary_union

        a = self._sh(_square(0.0, 0.0, 0.001))
        b = self._sh(_square(0.0005, 0.0, 0.001))     # 절반 겹침

        simple_sum = (self.ctx.shapely_area_m2(a) +
                      self.ctx.shapely_area_m2(b))
        union = self.ctx.shapely_area_m2(unary_union([a, b]))

        self.assertLess(union, simple_sum)
        # 겹친 만큼 정확히 차이가 난다 (오차 2%)
        overlap = self.ctx.shapely_area_m2(a.intersection(b))
        self.assertAlmostEqual(simple_sum - union, overlap,
                               delta=overlap * 0.02)

    def test_empty_geometry_is_zero_not_error(self):
        self.assertEqual(self.ctx.shapely_area_m2(None), 0.0)


# ---------------------------------------------------------------------------
# 1b. 치수·식재량 — 면적 하나로 답할 수 없는 질문
# ---------------------------------------------------------------------------

# 김제(북위 약 35.8도). 경도 1도가 위도 1도의 0.81배로 줄어드는 위도라, 투영을
# 빼먹거나 도(degree) 공간에서 사각형을 구하면 폭과 길이가 눈에 띄게 갈린다.
_KIMJE_LAT = 35.8
_KIMJE_LNG = 126.88


def _rect_at(lng, lat, width_m, length_m, rot_deg=0.0):
    """(lng, lat) 를 좌하단으로 하는 width_m × length_m 직사각형 Polygon.

    `rot_deg` 로 비스듬히 놓을 수 있다 — 실제 두둑은 축에 정렬돼 있지 않고,
    축 정렬 bounding box 로 재면 그때 실제보다 크고 뚱뚱하게 나온다.
    """
    import math

    m_lat = 111320.0
    m_lng = m_lat * math.cos(math.radians(lat))
    t = math.radians(rot_deg)
    corners_m = [(0.0, 0.0), (width_m, 0.0), (width_m, length_m), (0.0, length_m)]
    ring = []
    for x, y in corners_m:
        rx = x * math.cos(t) - y * math.sin(t)
        ry = x * math.sin(t) + y * math.cos(t)
        ring.append([lng + rx / m_lng, lat + ry / m_lat])
    ring.append(ring[0])
    return {'type': 'Polygon', 'coordinates': [ring]}


class _FakeRow(object):
    """`dimensions()` 는 행에서 `feature` 만 읽는다 — DB 를 켤 이유가 없다."""

    def __init__(self, geometry):
        self.feature = {'type': 'Feature', 'properties': {},
                        'geometry': geometry}


class TestDimensions(unittest.TestCase):
    def setUp(self):
        from aot.aot_flask.geo import planting_context
        self.ctx = planting_context

    def test_rectangular_plot_reports_its_two_sides(self):
        """40m × 46m ≈ 1837m² — 상추 구획 '앞두둑' 규모."""
        dims = self.ctx.dimensions(
            _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, 40.0, 46.0)))

        self.assertAlmostEqual(dims['width_m'], 40.0, delta=0.5)
        self.assertAlmostEqual(dims['length_m'], 46.0, delta=0.5)
        # 네모난 구획은 외접사각형을 거의 다 채운다 → 경고가 뜨면 안 된다.
        self.assertGreater(dims['rect_fill_pct'], 95.0)
        self.assertIsNone(dims['shape_note'])

    def test_width_is_always_the_short_side(self):
        """줄 수를 짧은 변에서 세는 약속이 깨지면 '몇 줄' 의 답이 뒤집힌다."""
        for w, l in ((12.0, 60.0), (60.0, 12.0)):
            dims = self.ctx.dimensions(
                _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, w, l)))
            self.assertLess(dims['width_m'], dims['length_m'])
            self.assertAlmostEqual(dims['width_m'], 12.0, delta=0.3)

    def test_rotated_plot_measures_its_own_sides_not_the_axes(self):
        """비스듬한 두둑 — 축 정렬로 재면 폭이 두 배 가까이 부풀어 오른다."""
        dims = self.ctx.dimensions(
            _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, 10.0, 50.0, rot_deg=35.0)))

        self.assertAlmostEqual(dims['width_m'], 10.0, delta=0.5)
        self.assertAlmostEqual(dims['length_m'], 50.0, delta=0.5)
        self.assertIsNone(dims['shape_note'])

    def test_dimensions_agree_with_area(self):
        """`width × length` 와 `area_m2` 가 같은 평면에서 재어져야 한다.

        투영 기준 위도가 갈리면 두 값이 설명 없이 어긋나고, 화면에서 그것을
        본 사람은 어느 쪽이 맞는지 알 방법이 없다.
        """
        row = _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, 40.0, 46.0))
        dims = self.ctx.dimensions(row)
        product = dims['width_m'] * dims['length_m']
        self.assertAlmostEqual(product, self.ctx.area_m2(row),
                               delta=product * 0.02)

    def test_triangle_raises_the_shape_warning(self):
        """삼각형은 외접사각형의 절반만 채운다 — 경고가 없으면 AI 가 두 배로 센다."""
        import math

        m_lat = 111320.0
        m_lng = m_lat * math.cos(math.radians(_KIMJE_LAT))
        tri = {'type': 'Polygon', 'coordinates': [[
            [_KIMJE_LNG, _KIMJE_LAT],
            [_KIMJE_LNG + 40.0 / m_lng, _KIMJE_LAT],
            [_KIMJE_LNG, _KIMJE_LAT + 46.0 / m_lat],
            [_KIMJE_LNG, _KIMJE_LAT],
        ]]}
        dims = self.ctx.dimensions(_FakeRow(tri))

        self.assertAlmostEqual(dims['rect_fill_pct'], 50.0, delta=3.0)
        self.assertIsNotNone(dims['shape_note'])
        self.assertIn('FEWER', dims['shape_note'])

    def test_l_shaped_plot_also_warns(self):
        """ㄱ자 밭 — 삼각형만 잡고 끝나는 임계값이면 쓸모가 없다."""
        import math

        m_lat = 111320.0
        m_lng = m_lat * math.cos(math.radians(_KIMJE_LAT))

        def _p(x, y):
            return [_KIMJE_LNG + x / m_lng, _KIMJE_LAT + y / m_lat]

        ell = {'type': 'Polygon', 'coordinates': [[
            _p(0, 0), _p(40, 0), _p(40, 12), _p(12, 12), _p(12, 46), _p(0, 46),
            _p(0, 0),
        ]]}
        dims = self.ctx.dimensions(_FakeRow(ell))
        self.assertIsNotNone(dims['shape_note'])

    def test_missing_geometry_is_none_not_error(self):
        self.assertIsNone(self.ctx.dimensions(_FakeRow(None)))
        self.assertIsNone(self.ctx.dimensions(
            _FakeRow({'type': 'Point', 'coordinates': [1, 2]})))


class TestCapacityEstimate(unittest.TestCase):
    def setUp(self):
        from aot.aot_flask.geo import planting_context
        self.ctx = planting_context
        self.dims = self.ctx.dimensions(
            _FakeRow(_rect_at(_KIMJE_LNG, _KIMJE_LAT, 4.0, 20.0)))

    def test_counts_rows_across_the_short_side(self):
        """폭 4m 를 40cm 간격으로 → 10줄.

        11줄이 아니다. 기둥 세기(구간 수+1)로 세면 맨 바깥 두 줄이 경계선
        **위에** 서고, 그것은 밭에서 성립하지 않는다.
        """
        cap = self.ctx.capacity_estimate(self.dims, 40, 15)

        self.assertEqual(cap['rows_possible'], 10)
        self.assertEqual(cap['plants_per_row'], int(2000 // 15))
        self.assertEqual(cap['total_plants'],
                         cap['rows_possible'] * cap['plants_per_row'])

    def test_half_spacing_stays_free_at_each_edge_by_default(self):
        """여백을 안 줘도 칸 세기가 양쪽에 간격 절반씩을 남긴다.

        10줄 × 40cm = 400cm 로 폭을 정확히 채우고, 줄은 각 칸의 가운데(20cm,
        60cm … 380cm)에 선다 — 경계에서 20cm 떨어진다.
        """
        cap = self.ctx.capacity_estimate(self.dims, 40, 15)
        self.assertEqual(cap['edge_margin_cm'], 0.0)
        used_cm = cap['rows_possible'] * cap['row_spacing_cm']
        self.assertLessEqual(used_cm, self.dims['width_m'] * 100.0)

    def test_basis_always_says_it_is_approximate(self):
        """근사임을 말하지 않으면 이 숫자가 그대로 모종 주문량이 된다."""
        cap = self.ctx.capacity_estimate(self.dims, 40, 15)
        self.assertIn('Approximate', cap['basis'])
        self.assertIn('bounding rectangle', cap['basis'])
        # 여백을 안 줬을 때는 줄 수 있다는 사실을 알려야 한다.
        self.assertIn('edge_margin_cm', cap['basis'])

    def test_shape_warning_is_carried_into_basis(self):
        """capacity 만 읽는 호출자에게도 형상 경고가 닿아야 한다."""
        import math

        m_lat = 111320.0
        m_lng = m_lat * math.cos(math.radians(_KIMJE_LAT))
        tri = {'type': 'Polygon', 'coordinates': [[
            [_KIMJE_LNG, _KIMJE_LAT],
            [_KIMJE_LNG + 4.0 / m_lng, _KIMJE_LAT],
            [_KIMJE_LNG, _KIMJE_LAT + 20.0 / m_lat],
            [_KIMJE_LNG, _KIMJE_LAT],
        ]]}
        cap = self.ctx.capacity_estimate(
            self.ctx.dimensions(_FakeRow(tri)), 40, 15)
        self.assertIn('FEWER', cap['basis'])

    def test_edge_margin_eats_into_both_axes(self):
        """농기계 선회 공간 1m — 간격 절반으로는 감당되지 않는 크기."""
        cap = self.ctx.capacity_estimate(self.dims, 40, 15, edge_margin_cm=100)

        # 폭 4m 에서 양쪽 1m 씩 → 2m 만 남는다.
        self.assertEqual(cap['usable_width_m'], 2.0)
        self.assertEqual(cap['usable_length_m'], 18.0)
        self.assertEqual(cap['rows_possible'], 5)
        self.assertEqual(cap['plants_per_row'], 120)

    def test_edge_margin_is_reported_so_the_number_is_auditable(self):
        cap = self.ctx.capacity_estimate(self.dims, 40, 15, edge_margin_cm=100)
        self.assertEqual(cap['edge_margin_cm'], 100.0)
        self.assertIn('100 cm was taken off each edge', cap['basis'])

    def test_margin_larger_than_the_plot_yields_zero_not_a_negative_count(self):
        """여백이 밭을 다 먹으면 0 이라고 말한다 — 음수 줄 수는 답이 아니다."""
        cap = self.ctx.capacity_estimate(self.dims, 40, 15, edge_margin_cm=300)

        self.assertEqual(cap['rows_possible'], 0)
        self.assertEqual(cap['total_plants'], 0)
        self.assertIn('Nothing fits', cap['basis'])

    def test_zero_margin_is_allowed_and_means_zero(self):
        """0 은 '안 줬다' 가 아니라 '여백 없이 심겠다' 는 유효한 선택이다."""
        cap = self.ctx.capacity_estimate(self.dims, 40, 15, edge_margin_cm=0)
        self.assertEqual(cap['edge_margin_cm'], 0.0)
        self.assertEqual(cap['rows_possible'], 10)

    def test_flat_layout_tells_the_caller_to_settle_the_bed_spec(self):
        """두둑 규격 없이 낸 숫자를 그대로 답으로 쓰면 20~30% 과다추정이다.

        그 사실이 응답 어디에도 없으면 AI 는 균일 배치 숫자를 확신하고 답한다.
        """
        cap = self.ctx.capacity_estimate(self.dims, 40, 15)

        self.assertEqual(cap['layout'], 'flat')
        self.assertIn('ask_user', cap)
        self.assertIn('bed_width_cm', cap['ask_user'])
        self.assertNotIn('beds_possible', cap)

    def test_bed_layout_counts_beds_and_rows_per_bed(self):
        """폭 4m 에 두둑 120 + 고랑 40 → 두둑 2개, 두둑당 3줄 = 6줄.

        균일 배치의 10줄과 크게 다르다 — 고랑에는 아무것도 안 심고, 남은
        120cm 는 앞에 고랑 40 을 두면 두둑이 들어가지 않는다.
        """
        cap = self.ctx.capacity_estimate(self.dims, 40, 15,
                                         bed_width_cm=120, path_width_cm=40)

        self.assertEqual(cap['layout'], 'beds')
        self.assertEqual(cap['beds_possible'], 2)
        self.assertEqual(cap['rows_per_bed'], 3)
        self.assertEqual(cap['rows_possible'], 6)
        self.assertNotIn('ask_user', cap)

    def test_last_bed_needs_no_trailing_furrow(self):
        """n 두둑은 `n·두둑 + (n-1)·고랑` 을 쓴다 — 마지막 두둑 뒤는 밭 끝이다.

        폭 4m 에 두둑 100 + 고랑 50 이면 100·3 + 50·2 = 400 으로 3개가 정확히
        들어간다. `n·(두둑+고랑)` 으로 세면 400/150 = 2 개가 되어 두둑 하나가
        통째로 사라진다.
        """
        cap = self.ctx.capacity_estimate(self.dims, 40, 15,
                                         bed_width_cm=100, path_width_cm=50)
        self.assertEqual(cap['beds_possible'], 3)

    def test_bed_narrower_than_row_spacing_is_zero_with_a_reason(self):
        """두둑 30cm 에 40cm 간격 줄은 한 줄도 안 선다."""
        cap = self.ctx.capacity_estimate(self.dims, 40, 15,
                                         bed_width_cm=30, path_width_cm=40)
        self.assertEqual(cap['rows_possible'], 0)
        self.assertIn('narrower than', cap['basis'])

    def test_bed_wider_than_the_plot_is_zero_with_a_reason(self):
        cap = self.ctx.capacity_estimate(self.dims, 40, 15,
                                         bed_width_cm=600, path_width_cm=40)
        self.assertEqual(cap['beds_possible'], 0)
        self.assertEqual(cap['total_plants'], 0)
        self.assertIn('not enough for one', cap['basis'])

    def test_bed_and_path_must_come_together(self):
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, 40, 15, bed_width_cm=120)
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, 40, 15, path_width_cm=40)

    def test_zero_furrow_is_allowed(self):
        """고랑 0 = 두둑을 붙여 만드는 배치. 유효한 선택이다."""
        cap = self.ctx.capacity_estimate(self.dims, 40, 15,
                                         bed_width_cm=100, path_width_cm=0)
        self.assertEqual(cap['beds_possible'], 4)

    def test_bed_spec_combines_with_edge_margin(self):
        """여백을 먼저 빼고 남은 폭에 두둑을 놓는다."""
        cap = self.ctx.capacity_estimate(self.dims, 40, 15, edge_margin_cm=50,
                                         bed_width_cm=100, path_width_cm=50)
        self.assertEqual(cap['usable_width_m'], 3.0)
        self.assertEqual(cap['beds_possible'], 2)

    def test_no_spacing_means_not_asked(self):
        self.assertIsNone(self.ctx.capacity_estimate(self.dims))

    def test_bed_spec_without_spacing_is_an_error(self):
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, bed_width_cm=120,
                                       path_width_cm=40)

    def test_one_spacing_alone_is_an_error_not_a_silent_skip(self):
        """간격을 말했는데 답에 계산이 없으면 무시된 것을 아무도 모른다."""
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, 40, None)
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, None, 15)

    def test_margin_without_spacing_is_an_error_too(self):
        """여백만 주면 계산이 안 되는데, 조용히 넘기면 반영된 줄 안다."""
        with self.assertRaises(ValueError):
            self.ctx.capacity_estimate(self.dims, edge_margin_cm=100)

    def test_non_positive_or_garbage_spacing_is_rejected(self):
        for bad in (0, -40, 'abc', None):
            with self.assertRaises(ValueError):
                self.ctx.capacity_estimate(self.dims, bad, 15)

    def test_negative_or_garbage_margin_is_rejected(self):
        for bad in (-10, 'abc'):
            with self.assertRaises(ValueError):
                self.ctx.capacity_estimate(self.dims, 40, 15, edge_margin_cm=bad)


# ---------------------------------------------------------------------------
# 2. 상위 zone 을 받지도, 자르지도 않는다 (equipment 와 같은 모델)
# ---------------------------------------------------------------------------

class TestNoParentSelection(unittest.TestCase):
    """구획을 만들 때 사용자가 zone 을 고르는 절차가 없어야 한다.

    equipment 는 상위를 사람이 고르지 않는다 — 그냥 그리고
    `recalculateSpatialRelationships()` 가 공간 포함으로 파생한다. 식생도 같다.

    예전에는 `zone_uuid` 를 받아 경계로 자르고 밖이면 거부했는데, 식생 모드에서
    zone 도형은 **클릭조차 되지 않아**(다른 모드의 레이어다) 사용자가 고를 방법이
    없었다. 할 수 없는 일을 요구하는 절차였다. 되살리지 말 것.
    """

    def test_write_path_takes_no_zone_and_no_clip(self):
        import inspect
        from aot.aot_flask.geo import planting_io

        sig = inspect.signature(planting_io.save_planting)
        self.assertEqual(list(sig.parameters), ['data'],
                         'save_planting 에 clip 같은 축이 되살아났다')

        code = '\n'.join(
            l for l in _read(planting_io.__file__.replace('.pyc', '.py')).splitlines()
            if not l.lstrip().startswith('#'))
        self.assertNotIn('clip_to_zone', code)
        self.assertNotIn("data.get('zone_uuid')", code)

    def test_client_does_not_send_zone_uuid_when_creating(self):
        js = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                          'design', 'aot-geo-vegetation.js')
        code = '\n'.join(
            line for line in _read(js).splitlines()
            if not line.lstrip().startswith(('*', '//', '/*')))
        self.assertNotIn('zone_uuid:', code,
                         '생성 페이로드에 zone_uuid 가 되살아났다')
        self.assertNotIn('_selectedZoneUuid', code)

    def test_zone_is_still_derived_for_reading(self):
        """저장 때 안 받을 뿐, 읽을 때는 여전히 공간 포함으로 파생한다."""
        from aot.aot_flask.geo import planting_context
        self.assertTrue(hasattr(planting_context, 'zone_for_planting'))


# ---------------------------------------------------------------------------
# 3. 쓰기 검증 (VP-1 · VP-2 · VP-4)
# ---------------------------------------------------------------------------

class TestWriteValidation(unittest.TestCase):
    def setUp(self):
        from aot.aot_flask.geo import planting_io
        self.io = planting_io

    def test_geometry_must_be_polygon(self):
        for geom in ({'type': 'Point', 'coordinates': [1, 2]},
                     {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]}):
            err = self.io._validate_geometry({'geometry': geom})
            self.assertIsNotNone(err, '%s 가 통과했다' % geom['type'])

    def test_polygon_passes(self):
        self.assertIsNone(
            self.io._validate_geometry({'geometry': _square(0, 0, 0.001)}))

    def test_forbidden_props_are_stripped(self):
        feature = {'properties': {'device_id': 'abc', 'channel_id': '0',
                                  'color': '#fff', 'name': '두둑1'}}
        cleaned, removed = self.io._strip_forbidden(feature)
        self.assertEqual(cleaned['properties'], {'name': '두둑1'})
        self.assertEqual(set(removed), {'device_id', 'channel_id', 'color'})

    def test_date_parsing_rejects_garbage(self):
        value, err = self.io._parse_date('2026-13-99', 'planted_on')
        self.assertIsNone(value)
        self.assertIsNotNone(err)

    def test_date_parsing_accepts_iso_and_empty(self):
        value, err = self.io._parse_date('2026-08-13', 'planted_on')
        self.assertEqual(value, date(2026, 8, 13))
        self.assertIsNone(err)

        value, err = self.io._parse_date('', 'ended_on')
        self.assertIsNone(value)
        self.assertIsNone(err)


# ---------------------------------------------------------------------------
# 4. 수명 판정 — 30일부터 30년까지 같은 구조
# ---------------------------------------------------------------------------

class TestLifetime(unittest.TestCase):
    def _row(self, planted, ended=None):
        from aot.databases.models import GeoPlanting
        return GeoPlanting(geo_id='m', feature={}, crop='c',
                           planted_on=planted, ended_on=ended)

    def test_open_ended_is_active_for_decades(self):
        """종료일이 없는 행 하나가 과수 30년을 담는다."""
        row = self._row(date.today() - timedelta(days=365 * 30))
        self.assertTrue(row.is_active())

    def test_ended_in_past_is_inactive(self):
        row = self._row(date.today() - timedelta(days=60),
                        date.today() - timedelta(days=1))
        self.assertFalse(row.is_active())

    def test_ends_today_is_already_inactive(self):
        """종료일 당일부터 활성이 아니다.

        `>= on` 으로 두면 "재배 종료"를 누른 사람이 화면에서는 사라진 구획을
        새로고침하면 다시 보게 된다. 하루만 어긋나는 종류라 신고되기 어렵다.
        `active_plantings` 의 쿼리와 같은 부등호를 써야 한다.
        """
        row = self._row(date.today() - timedelta(days=30), date.today())
        self.assertFalse(row.is_active())

    def test_ends_tomorrow_is_still_active(self):
        row = self._row(date.today() - timedelta(days=30),
                        date.today() + timedelta(days=1))
        self.assertTrue(row.is_active())

    def test_future_planting_is_not_active_yet(self):
        row = self._row(date.today() + timedelta(days=7))
        self.assertFalse(row.is_active())


# ---------------------------------------------------------------------------
# 5. 겹침 허용 (VP-3) — 막는 장치가 생기지 않았는지 소스로 확인
# ---------------------------------------------------------------------------

class TestNoHardcodedLocale(unittest.TestCase):
    """AI 에게 보내는 문구에 특정 나라의 관행을 박지 않는다.

    첫 판에 "Most **Korean** open-field vegetables…" 라고 적었다. 이 제품은
    ko/ja 를 함께 쓰고 설치처의 나라도 고정이 아니라, 다른 지역 사용자에게는
    틀린 근거가 된다. 두둑 농사 자체는 어디서나 흔하므로 나라 이름 없이도
    같은 말이 된다.
    """

    def test_ask_user_text_names_no_country(self):
        from aot.aot_flask.geo import planting_context
        text = planting_context._FLAT_LAYOUT_ASK
        for banned in ('Korea', 'Korean', 'Japan', 'Japanese'):
            self.assertNotIn(banned, text)

    def test_ui_strings_are_translated_in_both_catalogs(self):
        """번역 없는 문구는 ja 화면에서 영어로 남는다 — 조용한 종류다."""
        from babel.messages.pofile import read_po

        needed = ('Bed layout', 'Bed width (cm)', 'Furrow width (cm)',
                  'Not known')
        for lang in ('ko', 'ja'):
            path = os.path.join(_ROOT, 'aot_flask', 'translations', lang,
                                'LC_MESSAGES', 'messages.po')
            with open(path, encoding='utf-8') as fh:
                cat = read_po(fh)
            for msgid in needed:
                self.assertIn(msgid, cat, '%s: %r 가 카탈로그에 없다' % (lang, msgid))
                self.assertTrue(cat[msgid].string,
                                '%s: %r 가 번역되지 않았다' % (lang, msgid))

    def test_compiled_catalog_is_not_stale(self):
        """.po 만 고치고 .mo 를 안 만들면 화면은 그대로다 — 에러도 안 난다."""
        import gettext

        for lang in ('ko', 'ja'):
            path = os.path.join(_ROOT, 'aot_flask', 'translations', lang,
                                'LC_MESSAGES', 'messages.mo')
            with open(path, 'rb') as fh:
                tr = gettext.GNUTranslations(fh)
            self.assertNotEqual(tr.gettext('Bed width (cm)'), 'Bed width (cm)',
                                '%s: .mo 가 .po 보다 오래됐다' % lang)


class TestOverlapStaysAllowed(unittest.TestCase):
    def test_migration_has_no_uniqueness_on_geometry(self):
        """겹침 유일성 인덱스가 추가되면 간작·혼작이 DB 에서 거부된다."""
        src = _read(_MIGRATION)
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, 'attr', getattr(fn, 'id', ''))
            if name != 'create_index':
                continue
            # 인덱스 대상 컬럼 목록(3번째 인자)에 기하·작물이 끼면 안 된다.
            if len(node.args) >= 3 and isinstance(node.args[2], ast.List):
                cols = [e.value for e in node.args[2].elts
                        if isinstance(e, ast.Constant)]
                self.assertNotIn('feature', cols)
                self.assertNotIn('crop', cols)

        self.assertNotIn('UniqueConstraint(\'geo_id\'', src)

    def test_no_overlap_check_in_write_path(self):
        """저장 경로에 겹침 거부가 들어오면 정상 기능이 막힌다."""
        from aot.aot_flask.geo import planting_io
        src = _read(planting_io.__file__.replace('.pyc', '.py'))
        lowered = src.lower()
        for banned in ('overlaps(', 'is_overlapping', 'reject_overlap'):
            self.assertNotIn(banned, lowered,
                             '저장 경로에 겹침 검사가 생겼다 — VP-3 위반')

    def test_integrity_checker_does_not_flag_overlap(self):
        checker = os.path.join(_ROOT, 'scripts', 'check_geo_integrity.py')
        src = _read(checker)
        self.assertNotIn("'planting-overlap'", src)
        self.assertNotIn('planting-overlapping', src)


# ---------------------------------------------------------------------------
# 6. 소속에 끼지 않는다 — 참조와 소속은 다른 축
# ---------------------------------------------------------------------------

class TestNotAContainer(unittest.TestCase):
    def test_container_types_excludes_vegetation(self):
        """식생이 컨테이너가 되면 장치 소속이 작기마다 바뀐다."""
        from aot.aot_flask.geo import device_membership
        self.assertEqual(device_membership._CONTAINER_TYPES, ('site', 'zone'))

    def test_planting_has_no_zone_column(self):
        """소속을 물질화하면 map_overlay_id 가 겪은 오염 계열이 되살아난다."""
        from aot.databases.models import GeoPlanting
        cols = set(GeoPlanting.__table__.columns.keys())
        for banned in ('zone_uuid', 'zone_id', 'parent_id', 'device_id'):
            self.assertNotIn(banned, cols)

    def test_no_binding_written_for_plantings(self):
        """센서는 참조일 뿐이다 — geo_binding 행을 만들면 안 된다."""
        from aot.aot_flask.geo import planting_io, planting_context
        for mod in (planting_io, planting_context):
            src = _read(mod.__file__.replace('.pyc', '.py'))
            self.assertNotIn('GeoBinding', src)
            self.assertNotIn('device_binding.bind', src)


# ---------------------------------------------------------------------------
# 7. 저장처 분리 — GeoShape 경로에 실리지 않는다
# ---------------------------------------------------------------------------

class TestStorageSeparation(unittest.TestCase):
    def test_types_to_sync_excludes_vegetation(self):
        """typesToSync 에 들어가면 전량교체 저장이 식생을 GeoShape 로 만든다."""
        src = _read(_DESIGN_JS)
        for line in src.splitlines():
            if 'typesToSync' in line and '[' in line:
                self.assertNotIn("'vegetation'", line)

    def test_valid_shape_types_excludes_vegetation(self):
        """GeoShape 어휘에 넣으면 두 저장처가 생긴다."""
        from aot.databases.geo_integrity_ddl import VALID_SHAPE_TYPES
        self.assertNotIn('vegetation', VALID_SHAPE_TYPES)
        self.assertNotIn('planting', VALID_SHAPE_TYPES)

    def test_vegetation_module_does_not_call_save_overlays(self):
        js = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                          'design', 'aot-geo-vegetation.js')
        # 주석은 뺀다 — 이 파일의 머리말이 "saveOverlays 를 쓰지 않는다" 라고
        # 적고 있어서, 문자열만 세면 그 설명 자체가 위반으로 잡힌다.
        code = '\n'.join(
            line for line in _read(js).splitlines()
            if not line.lstrip().startswith(('*', '//', '/*')))
        self.assertNotIn('saveOverlays', code)
        self.assertNotIn('saveDesign', code)


# ---------------------------------------------------------------------------
# 8. 테마색 — 화이트리스트에 없으면 저장이 조용히 버려진다
# ---------------------------------------------------------------------------

class TestThemeKey(unittest.TestCase):
    def test_server_whitelist_has_theme_vegetation(self):
        src = _read(_ROUTES_GEO)
        self.assertIn("'theme_vegetation'", src,
                      "theme_keys 에 없으면 색 피커가 저장되지 않는다")

    def test_defaults_has_single_vegetation_entry(self):
        """기본값은 DEFAULTS 한 벌뿐 — 새 폴백을 만들지 않는다."""
        src = _read(_THEME_JS)
        self.assertEqual(src.count('vegetation:'), 1)


# ---------------------------------------------------------------------------
# 9. 저장 경로 통합 — DB 를 실제로 쓴다
# ---------------------------------------------------------------------------

class TestSaveRoundTrip(unittest.TestCase):
    """save → end → copy 흐름. 임시 DB(파일)만 쓰고 라이브를 건드리지 않는다."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'planting.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _save(self, **over):
        from aot.aot_flask.geo import planting_io
        payload = {
            'map_uuid': 'map-test',
            'feature': {'type': 'Feature', 'properties': {},
                        'geometry': _square(0.0, 0.0, 0.001)},
            'crop': '상추',
            'planted_on': date.today().isoformat(),
        }
        payload.update(over)
        return planting_io.save_planting(payload)

    def test_create_then_end_keeps_the_row(self):
        from aot.databases.models import GeoPlanting
        from aot.aot_flask.geo import planting_io

        created, err = self._save()
        self.assertIsNone(err)
        uid = created['unique_id']

        ended, err = planting_io.end_planting(uid, reason='harvested')
        self.assertIsNone(err)
        self.assertIsNotNone(ended['ended_on'])

        # 종료는 삭제가 아니다 — 이력이 남아야 연작 장해를 판단할 수 있다.
        self.assertIsNotNone(
            GeoPlanting.query.filter_by(unique_id=uid).first())

    def test_end_before_planted_is_rejected(self):
        from aot.aot_flask.geo import planting_io
        created, _ = self._save(planted_on=date.today().isoformat())
        _, err = planting_io.end_planting(
            created['unique_id'],
            ended_on=(date.today() - timedelta(days=5)).isoformat())
        self.assertIsNotNone(err, 'VP-2 가 강제되지 않았다')

    def test_geometry_frozen_after_end(self):
        """VP-6 — 종료된 작기의 기하가 바뀌면 과거 이력이 거짓말이 된다."""
        from aot.aot_flask.geo import planting_io
        created, _ = self._save()
        planting_io.end_planting(created['unique_id'])

        _, err = planting_io.save_planting({
            'unique_id': created['unique_id'],
            'feature': {'type': 'Feature', 'properties': {},
                        'geometry': _square(0.5, 0.5, 0.001)},
        })
        self.assertIsNotNone(err)

    def test_name_change_still_allowed_after_end(self):
        """날짜 정정·이름 변경까지 막으면 오기입을 고칠 수 없다."""
        from aot.aot_flask.geo import planting_io
        created, _ = self._save()
        planting_io.end_planting(created['unique_id'])

        updated, err = planting_io.save_planting({
            'unique_id': created['unique_id'], 'name': '고친 이름',
        })
        self.assertIsNone(err)
        self.assertEqual(updated['name'], '고친 이름')

    def test_partial_update_does_not_wipe_untouched_fields(self):
        """페이로드에 없는 키를 None 으로 덮으면 부분 저장이 값을 지운다."""
        from aot.aot_flask.geo import planting_io
        created, _ = self._save(variety='청치마', name='두둑1')

        updated, err = planting_io.save_planting({
            'unique_id': created['unique_id'], 'crop': '배추',
        })
        self.assertIsNone(err)
        self.assertEqual(updated['crop'], '배추')
        self.assertEqual(updated['variety'], '청치마')
        self.assertEqual(updated['name'], '두둑1')

    def test_copy_carries_geometry_and_marks_source(self):
        from aot.aot_flask.geo import planting_io
        created, _ = self._save()
        copied, err = planting_io.copy_planting(created['unique_id'])

        self.assertIsNone(err)
        self.assertEqual(copied['source_kind'], 'copied')
        self.assertEqual(copied['source_ref'], created['unique_id'])
        self.assertEqual(json.dumps(copied['feature']['geometry'], sort_keys=True),
                         json.dumps(created['feature']['geometry'], sort_keys=True))
        self.assertNotEqual(copied['unique_id'], created['unique_id'])

    def test_bed_spec_round_trips(self):
        created, err = self._save(bed_width_cm=120, path_width_cm=40)
        self.assertIsNone(err)
        self.assertEqual(created['bed_width_cm'], 120)
        self.assertEqual(created['path_width_cm'], 40)

    def test_bed_spec_defaults_to_unknown_not_flat(self):
        """None 은 "평평하다" 가 아니라 "모른다" — 그 구분이 조회를 좌우한다."""
        created, _ = self._save()
        self.assertIsNone(created['bed_width_cm'])
        self.assertIsNone(created['path_width_cm'])

    def test_zero_furrow_is_stored_not_treated_as_empty(self):
        """0 은 유효한 배치(두둑을 붙여 만듦)다. None 으로 뭉개면 안 된다."""
        created, err = self._save(bed_width_cm=100, path_width_cm=0)
        self.assertIsNone(err)
        self.assertEqual(created['path_width_cm'], 0)

    def test_half_a_bed_spec_is_rejected(self):
        _, err = self._save(bed_width_cm=120)
        self.assertIsNotNone(err)

    def test_editing_only_the_furrow_of_a_stored_spec_is_allowed(self):
        """병합 후 값으로 검사하지 않으면 이 정상 수정이 막힌다."""
        from aot.aot_flask.geo import planting_io
        created, _ = self._save(bed_width_cm=120, path_width_cm=40)

        updated, err = planting_io.save_planting({
            'unique_id': created['unique_id'], 'path_width_cm': 50,
        })
        self.assertIsNone(err)
        self.assertEqual(updated['bed_width_cm'], 120)
        self.assertEqual(updated['path_width_cm'], 50)

    def test_bed_spec_survives_an_unrelated_partial_update(self):
        from aot.aot_flask.geo import planting_io
        created, _ = self._save(bed_width_cm=120, path_width_cm=40)

        updated, err = planting_io.save_planting({
            'unique_id': created['unique_id'], 'crop': '배추',
        })
        self.assertIsNone(err)
        self.assertEqual(updated['bed_width_cm'], 120)

    def test_bed_spec_editable_after_end_unlike_geometry(self):
        """나중에 규격을 알게 되어 채우는 것은 이력을 고치는 일이 아니다."""
        from aot.aot_flask.geo import planting_io
        created, _ = self._save()
        planting_io.end_planting(created['unique_id'])

        updated, err = planting_io.save_planting({
            'unique_id': created['unique_id'],
            'bed_width_cm': 150, 'path_width_cm': 50,
        })
        self.assertIsNone(err)
        self.assertEqual(updated['bed_width_cm'], 150)

    def test_copy_carries_the_bed_spec(self):
        """같은 자리를 다시 심는 것이므로 두둑도 그대로다."""
        from aot.aot_flask.geo import planting_io
        created, _ = self._save(bed_width_cm=120, path_width_cm=40)
        copied, err = planting_io.copy_planting(created['unique_id'])

        self.assertIsNone(err)
        self.assertEqual(copied['bed_width_cm'], 120)
        self.assertEqual(copied['path_width_cm'], 40)

    def test_stored_bed_spec_is_used_without_being_passed(self):
        """저장해 뒀는데 매번 다시 물으면 저장한 의미가 없다."""
        from aot.databases.models import GeoPlanting
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        created, _ = self._save(bed_width_cm=120, path_width_cm=40)
        row = GeoPlanting.query.filter_by(unique_id=created['unique_id']).first()

        brief = S._planting_brief(row, row_spacing_cm=40, plant_spacing_cm=15)
        cap = brief['capacity_estimate']

        self.assertEqual(cap['layout'], 'beds')
        self.assertEqual(cap['bed_spec_source'], 'stored')
        self.assertNotIn('ask_user', cap)

    def test_passed_bed_spec_overrides_the_stored_one(self):
        """"이번엔 150 으로 잡으면?" 은 저장값을 건드리지 않고 계산만 바꾼다."""
        from aot.databases.models import GeoPlanting
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        created, _ = self._save(bed_width_cm=120, path_width_cm=40)
        row = GeoPlanting.query.filter_by(unique_id=created['unique_id']).first()

        cap = S._planting_brief(row, row_spacing_cm=40, plant_spacing_cm=15,
                                bed_width_cm=150)['capacity_estimate']

        self.assertEqual(cap['bed_width_cm'], 150)
        self.assertEqual(cap['path_width_cm'], 40)   # 저장값에서 옴
        self.assertEqual(cap['bed_spec_source'], 'given')
        self.assertEqual(row.bed_width_cm, 120)      # 저장값은 그대로

    def test_plain_read_of_a_plot_with_a_stored_spec_does_not_error(self):
        """저장된 규격이 '묻지 않은 조건' 자리로 새면 그냥 조회가 깨진다.

        실제로 한 번 깨뜨렸다: 두둑 규격을 기록한 구획을
        `get_planting(planting_id)` 로만 불렀더니 "간격이 있어야 계산할 수
        있다" 는 오류가 났다 — 아무것도 묻지 않았는데.
        """
        from aot.databases.models import GeoPlanting
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        created, _ = self._save(bed_width_cm=120, path_width_cm=40)
        out = S.get_planting(planting_id=created['unique_id'])

        self.assertNotIn('error', out)
        self.assertEqual(out['planting']['bed_width_cm'], 120)
        # 아무것도 안 물었으므로 식재량 계산은 붙지 않는다.
        self.assertNotIn('capacity_estimate', out['planting'])

    def test_bed_spec_alone_without_spacings_still_errors(self):
        """저장값을 안 끌어오는 것과, 호출자 실수를 눈감는 것은 다르다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        created, _ = self._save()
        out = S.get_planting(planting_id=created['unique_id'], bed_width_cm=120)
        self.assertIn('error', out)

    def test_plot_without_a_bed_spec_still_asks(self):
        from aot.databases.models import GeoPlanting
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        created, _ = self._save()
        row = GeoPlanting.query.filter_by(unique_id=created['unique_id']).first()

        cap = S._planting_brief(row, row_spacing_cm=40,
                                plant_spacing_cm=15)['capacity_estimate']
        self.assertEqual(cap['layout'], 'flat')
        self.assertIn('ask_user', cap)

    def test_overlapping_plantings_both_save(self):
        """VP-3 — 간작·혼작. 겹친다고 거부하면 실제 농사를 담지 못한다."""
        a, err_a = self._save(crop='토마토')
        b, err_b = self._save(crop='바질',
                              feature={'type': 'Feature', 'properties': {},
                                       'geometry': _square(0.0005, 0.0, 0.001)})
        self.assertIsNone(err_a)
        self.assertIsNone(err_b)
        self.assertNotEqual(a['unique_id'], b['unique_id'])


# ---------------------------------------------------------------------------
# 10. sensors_for_planting — Output(액추에이터)이 섞이면 안 된다
# ---------------------------------------------------------------------------

class TestSensorsExcludeOutputs(unittest.TestCase):
    """구획 sensors 필드(in_plot/from_zone)에 Output이 섞이지 않는다.

    2026-08-13 실측: virtual_on_off_single 밸브(Output) 마커가 폴리곤 안에
    있으면 in_plot/from_zone 에 그대로 나가 AI가 밸브를 센서로 읽으려 시도했다
    (get_sensor_reading 이 "no directly connected sensors" 로 실패).
    device_ids_in_geometry/device_ids_in_shape 은 Input·Output 구분 없이
    장치 참조 전부를 돌려주는 범용 계약이므로(device_membership 모듈
    docstring), 걸러야 할 지점은 그 이름이 'sensors' 인 여기다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'sensors.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _marker(self, geo_id, device_id, lng, lat):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoShape
        shape = GeoShape(geo_id=geo_id, device_id=device_id, type='aot_device',
                         feature={'type': 'Feature', 'properties': {},
                                 'geometry': {'type': 'Point',
                                             'coordinates': [lng, lat]}})
        db.session.add(shape)
        db.session.commit()
        return shape

    def test_output_marker_in_plot_is_not_reported_as_sensor(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlanting, Input, Output
        from aot.aot_flask.geo import planting_context

        sensor = Input(name='온도계')
        valve = Output(name='v331')
        db.session.add_all([sensor, valve])
        db.session.commit()

        self._marker('map-sensors', sensor.unique_id, 0.0004, 0.0004)
        self._marker('map-sensors', valve.unique_id, 0.0006, 0.0006)

        planting = GeoPlanting(
            geo_id='map-sensors', crop='상추', planted_on=date.today(),
            feature={'type': 'Feature', 'properties': {},
                    'geometry': _square(0.0, 0.0, 0.001)})
        db.session.add(planting)
        db.session.commit()

        sensors = planting_context.sensors_for_planting(planting)

        self.assertIn(sensor.unique_id, sensors['in_plot'])
        self.assertNotIn(valve.unique_id, sensors['in_plot'])
        self.assertNotIn(valve.unique_id, sensors['from_zone'])


# ---------------------------------------------------------------------------
# 11. 작물명으로 구역을 찾는다 — 관리인은 '3-1' 이 아니라 '콩밭' 이라 부른다
# ---------------------------------------------------------------------------

class TestCropNameTargetResolution(unittest.TestCase):
    """`_resolve_note_target` 의 작물명 폴백.

    2026-08-13 실측: `resolve_target('콩밭')` 이 needs_disambiguation 을 내고
    후보로 zone 이름('1포장','3-1',...)만 늘어놓았다 — 지도 이름을 모르는
    사람에게는 답이 없는 되물음이다.

    이 폴백은 **쓰기 도구**(add_schedule·create_note)의 타깃 해석에도 그대로
    쓰인다. 그래서 여기서 고정하는 것 중 진짜 위험한 것은 "찾는다"가 아니라
    **"애매하면 안 찾는다"** 쪽이다: 같은 작물이 두 구역에 있을 때 하나를
    골라버리면 엉뚱한 밭에 조용히 기록이 남는다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        from flask_babel import Babel

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'croptarget.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        # aot_data_tool_service → config_translations 의 모듈 레벨 lazy_gettext.
        # Babel 미등록 상태에서 처음 문자열화되면 KeyError('babel') 이 난다.
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        # 김제 지도를 본뜬 최소 구성: zone 둘, 그 안에 콩과 상추.
        from aot.databases.models import GeoMap, GeoShape, GeoPlanting
        db.session.add(GeoMap(name='김제', unique_id='map-crop'))

        def _zone(name, x0):
            db.session.add(GeoShape(
                geo_id='map-crop', type='zone',
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': _square(x0, 0.0, 0.001)}))

        _zone('3-1', 0.0)      # 콩
        _zone('3-2', 0.01)     # 상추
        _zone('3-3', 0.02)     # 콩 (같은 작물 두 번째 구역 — 모호성 테스트용)
        db.session.commit()

        def _plot(crop, x0, **over):
            row = GeoPlanting(
                geo_id='map-crop', crop=crop, planted_on=date.today(),
                feature={'type': 'Feature', 'properties': {},
                         'geometry': _square(x0 + 0.0002, 0.0002, 0.0004)})
            for k, v in over.items():
                setattr(row, k, v)
            db.session.add(row)
            return row

        _plot('콩', 0.0)
        _plot('상추', 0.01, variety='청치마')
        cls._second_bean = _plot('콩', 0.02)
        db.session.commit()
        # 두 번째 콩은 개별 테스트에서만 살린다(기본은 콩 = 3-1 하나).
        cls._second_bean.ended_on = date.today() - timedelta(days=1)
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _resolve(self, name):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService._resolve_note_target(name)

    def test_crop_with_place_suffix_resolves_to_its_zone(self):
        """'콩밭' → 콩이 심긴 zone. 이 폴백이 없던 시절의 실패 사례 그대로."""
        target_id, target_type, name, _, _ = self._resolve('콩밭')
        self.assertEqual(name, '3-1')
        self.assertEqual(target_type, 'zone')
        self.assertTrue(target_id)

    def test_spaced_suffix_also_resolves(self):
        """'상추 재배지' — 붙여 쓰든 띄어 쓰든 같은 답이어야 한다."""
        self.assertEqual(self._resolve('상추 재배지')[2], '3-2')
        self.assertEqual(self._resolve('상추재배지')[2], '3-2')

    def test_bare_crop_name_resolves(self):
        self.assertEqual(self._resolve('콩')[2], '3-1')

    def test_variety_name_resolves(self):
        """품종으로 부르는 사람도 있다 — '청치마'는 상추 구획의 품종."""
        self.assertEqual(self._resolve('청치마')[2], '3-2')

    def test_zone_name_still_wins_over_crop(self):
        """폴백은 **최후**다. 지도 이름이 맞으면 그것이 답이어야 한다."""
        self.assertEqual(self._resolve('3-2')[2], '3-2')

    def test_unknown_word_still_fails(self):
        """폴백이 아무거나 주워 담으면 엉뚱한 곳에 쓰기가 일어난다."""
        self.assertIsNone(self._resolve('없는이름12345')[0])

    def test_ended_planting_does_not_resolve(self):
        """작년 작물이 올해 노트를 끌고 가면 안 된다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlanting

        row = GeoPlanting(
            geo_id='map-crop', crop='배추', planted_on=date.today() - timedelta(days=200),
            ended_on=date.today() - timedelta(days=10),
            feature={'type': 'Feature', 'properties': {},
                     'geometry': _square(0.0003, 0.0003, 0.0003)})
        db.session.add(row)
        db.session.commit()
        try:
            self.assertIsNone(self._resolve('배추밭')[0])
        finally:
            db.session.delete(row)
            db.session.commit()

    def test_same_crop_in_two_zones_refuses_to_guess(self):
        """모호하면 매치하지 않는다 — 이 리졸버는 쓰기 도구가 함께 쓴다."""
        from aot.aot_flask.extensions import db

        self._second_bean.ended_on = None       # 3-3 의 콩을 되살린다
        db.session.commit()
        try:
            self.assertIsNone(self._resolve('콩밭')[0])
        finally:
            self._second_bean.ended_on = date.today() - timedelta(days=1)
            db.session.commit()

    def test_plot_outside_every_zone_is_not_a_target(self):
        """zone 밖 구획은 쓸 대상이 없다 — GeoPlanting 자신은 쓰기 대상이 아니다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlanting

        row = GeoPlanting(
            geo_id='map-crop', crop='들깨', planted_on=date.today(),
            feature={'type': 'Feature', 'properties': {},
                     'geometry': _square(0.5, 0.5, 0.0003)})
        db.session.add(row)
        db.session.commit()
        try:
            self.assertIsNone(self._resolve('들깨밭')[0])
        finally:
            db.session.delete(row)
            db.session.commit()

    def test_failure_response_points_at_crop_names(self):
        """되물음이 zone 이름만 늘어놓으면 사용자는 여전히 답할 수 없다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        r = AoTDataToolService.resolve_target_tool('없는이름12345')
        self.assertEqual(r['status'], 'needs_disambiguation')
        crops = {c['crop'] for c in r['crop_targets']}
        self.assertIn('콩', crops)
        self.assertIn('상추', crops)


class TestSubstringFallbackIsNotGreedy(unittest.TestCase):
    """3단계(부분문자열)가 짧은 이름을 아무 문장에나 붙이지 않는다.

    2026-08-13 로컬 실측: 이름이 '2' 인 zone 이 있는 지도에서
    `resolve_target('비닐하우스 2동 옆 창고')` 가 그 zone 을 `status: success` 로
    확정하고 "정확히 한 엔티티로 해석됐다" 는 note 까지 달았다. 호출부에는
    의심할 근거가 하나도 없고, 이 리졸버는 `add_schedule`·`create_note` 가
    함께 쓴다 — 조용히 엉뚱한 구역에 쓰기가 일어난다.

    작물명 폴백(위)보다 앞 단계라, 여기서 아무거나 잡아채면 폴백은 도달조차
    하지 못한다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'substring.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        from aot.databases.models import GeoShape
        for name, x0 in (('2', 0.0), ('1포장', 0.01), ('2포장', 0.02),
                         ('3포장', 0.03), ('육묘장', 0.04)):
            db.session.add(GeoShape(
                geo_id='map-sub', type='zone',
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': _square(x0, 0.0, 0.001)}))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _resolve(self, name):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService._resolve_note_target(name)

    def test_one_char_zone_name_does_not_swallow_a_sentence(self):
        self.assertIsNone(self._resolve('비닐하우스 2동 옆 창고')[0])

    def test_one_char_query_does_not_pick_among_names(self):
        """반대 방향도 같다 — 한 글자는 지도 이름 절반 안에 들어 있다."""
        self.assertIsNone(self._resolve('장')[0])

    def test_exact_one_char_name_still_resolves(self):
        """1단계 정확일치는 그대로다 — 길이 제한은 3단계에만 건다."""
        self.assertEqual(self._resolve('2')[2], '2')

    def test_ambiguous_substring_refuses_instead_of_taking_the_first(self):
        """'포장' → 1·2·3포장. 하나를 골라버리면 고른 사실조차 말하지 않는다."""
        self.assertIsNone(self._resolve('포장')[0])

    def test_unambiguous_substring_still_resolves(self):
        """이름 하나만 걸리면 종전대로 답한다 — 과잉 차단이 아니다."""
        self.assertEqual(self._resolve('육묘')[2], '육묘장')

    def test_korean_particle_attached_to_a_name_still_resolves(self):
        """'1포장에서' — 조사가 붙어도 찾아야 한다(어절 경계로 막으면 안 되는 이유)."""
        self.assertEqual(self._resolve('1포장에서')[2], '1포장')


class TestPlaceSuffixStripping(unittest.TestCase):
    """접미사 제거는 작물 매칭이 실패한 뒤에만 도는 보조 수단이다."""

    def _strip(self, text):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService._strip_place_suffix(text)

    def test_common_suffixes(self):
        self.assertEqual(self._strip('콩밭'), '콩')
        self.assertEqual(self._strip('상추 재배지'), '상추')
        self.assertEqual(self._strip('토마토하우스'), '토마토')

    def test_suffix_alone_is_not_stripped_to_nothing(self):
        """'밭' 만 들어오면 남는 게 없다 — 빈 문자열로 전체 매칭을 열면 안 된다."""
        self.assertIsNone(self._strip('밭'))
        self.assertIsNone(self._strip('재배지'))

    def test_no_suffix_returns_none(self):
        self.assertIsNone(self._strip('콩'))
        self.assertIsNone(self._strip('3-1'))


if __name__ == '__main__':
    unittest.main()


# ---------------------------------------------------------------------------
# 10. 시설 bay 흡수 (Phase 2) — 기하는 참조가 아니라 스냅샷
# ---------------------------------------------------------------------------

class TestBayBackfill(unittest.TestCase):
    """`bays[].crop` → GeoPlanting 백필의 판정 규칙.

    실제 이관은 운영 데이터에서만 일어나므로(개발 DB 에는 bay 작물이 없다),
    **무엇을 옮기고 무엇을 건너뛰는지**를 여기서 고정한다. 조용히 잘못 옮기면
    지도에 안 그려지는 유령 구획이 생기거나 같은 작물이 두 벌이 된다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'bay.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility, GeoPlanting, GeoShape
        for model in (GeoPlanting, GeoShape, GeoFacility):
            model.query.delete()
        db.session.commit()

    def _facility_with_bay(self, crop, with_geometry=True, bay_id='bay_1'):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFacility, GeoShape

        # 시설 외곽 도형 — GeoFacility.shape_uuid 는 필수다.
        outer = GeoShape(geo_id='map-bay', type='facility',
                         feature={'type': 'Feature', 'properties': {},
                                  'geometry': _square(0.0, 0.0, 0.002)})
        db.session.add(outer)
        db.session.flush()

        shape_uuid = None
        if with_geometry:
            shape = GeoShape(geo_id='map-bay', type='facility_bay',
                             parent_id=outer.id,
                             feature={'type': 'Feature', 'properties': {},
                                      'geometry': _square(0.0, 0.0, 0.0005)})
            db.session.add(shape)
            db.session.flush()
            shape_uuid = shape.unique_id

        fac = GeoFacility(name='온실1', geo_id='map-bay',
                          shape_uuid=outer.unique_id, bays=[{
            'id': bay_id, 'name': '1동', 'crop': crop,
            'polygon_shape_uuid': shape_uuid,
        }])
        db.session.add(fac)
        db.session.commit()
        return fac

    def _plan(self):
        from aot.scripts.backfill_facility_bay_crops import _plan
        return _plan(None)

    def test_bay_with_crop_and_geometry_is_planned(self):
        self._facility_with_bay('토마토')
        planned, skipped = self._plan()
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]['crop'], '토마토')
        self.assertIn(':', planned[0]['source_ref'])   # <facility>:<bay>

    def test_bay_without_geometry_is_skipped_not_created(self):
        """기하 없이 만들면 지도에 안 그려지는 유령 구획이 된다."""
        self._facility_with_bay('상추', with_geometry=False)
        planned, skipped = self._plan()
        self.assertEqual(planned, [])
        self.assertEqual(skipped[0]['why'], 'no-geometry')

    def test_bay_without_crop_is_ignored(self):
        self._facility_with_bay('')
        planned, skipped = self._plan()
        self.assertEqual(planned, [])
        self.assertEqual(skipped, [])

    def test_rerun_does_not_duplicate(self):
        """재실행해도 두 벌이 되지 않는다 — source_ref 로 알아본다."""
        from aot.scripts.backfill_facility_bay_crops import _apply

        self._facility_with_bay('오이')
        planned, _ = self._plan()
        made, failed = _apply(None, planned)
        self.assertEqual(len(made), 1)
        self.assertEqual(failed, [])

        planned2, skipped2 = self._plan()
        self.assertEqual(planned2, [])
        self.assertEqual(skipped2[0]['why'], 'already-migrated')

    def test_migrated_plot_is_a_snapshot_not_a_reference(self):
        """bay 기하가 바뀌어도 옮긴 구획은 따라 움직이지 않는다.

        따라 움직이면 "작년에 여기 뭐가 있었나" 의 답이 조용히 달라진다.
        """
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlanting, GeoShape
        from aot.scripts.backfill_facility_bay_crops import _apply

        self._facility_with_bay('딸기')
        planned, _ = self._plan()
        _apply(None, planned)

        before = json.dumps(GeoPlanting.query.first().feature['geometry'],
                            sort_keys=True)

        # bay 를 다시 나눈 것처럼 원본 도형의 기하를 바꾼다
        shape = GeoShape.query.filter_by(type='facility_bay').first()
        shape.feature = {'type': 'Feature', 'properties': {},
                         'geometry': _square(9.0, 9.0, 0.0005)}
        db.session.commit()

        after = json.dumps(GeoPlanting.query.first().feature['geometry'],
                           sort_keys=True)
        self.assertEqual(before, after, '스냅샷이 아니라 참조로 붙어 있다')

    def test_source_kind_marks_origin(self):
        from aot.databases.models import GeoPlanting
        from aot.scripts.backfill_facility_bay_crops import _apply

        self._facility_with_bay('가지')
        planned, _ = self._plan()
        _apply(None, planned)
        self.assertEqual(GeoPlanting.query.first().source_kind, 'bay_snapshot')


# ---------------------------------------------------------------------------
# 11. 관수 밸브 교차 (Phase 3) — 계층이 아니라 교차
# ---------------------------------------------------------------------------

class TestValveIntersection(unittest.TestCase):
    """밸브와 식생은 소속 관계가 아니다.

    밸브 하나가 두 작물을 적시고, 한 작물이 두 밸브에 걸친다. 그래서 "이
    구획의 밸브" 를 하나로 정하지 않고 **겹치는 면적**을 낸다. 여기서 관수량을
    계산하지 않는 것도 같은 이유다 — 겹친 곳에서 물은 공유되므로 작물별
    요구량을 합산하면 물리적으로 틀린 숫자가 된다.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'valve.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlanting, GeoShape
        GeoPlanting.query.delete()
        GeoShape.query.delete()
        db.session.commit()

    def _plot(self, x0=0.0, size=0.001):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlanting
        row = GeoPlanting(geo_id='m-valve', crop='상추',
                          planted_on=date.today(),
                          feature={'type': 'Feature', 'properties': {},
                                   'geometry': _square(x0, 0.0, size)})
        db.session.add(row)
        db.session.commit()
        return row

    def _valve_area(self, x0, size=0.001, name='밸브구역'):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoShape
        shape = GeoShape(geo_id='m-valve', type='device',
                         feature={'type': 'Feature',
                                  'properties': {'name': name},
                                  'geometry': _square(x0, 0.0, size)})
        db.session.add(shape)
        db.session.commit()
        return shape

    def _valves(self, row):
        from aot.aot_flask.geo import planting_context
        return planting_context.valves_for_planting(row)

    def test_no_overlap_no_valve(self):
        row = self._plot()
        self._valve_area(5.0)                 # 멀리 떨어진 구역
        self.assertEqual(self._valves(row), [])

    def test_coverage_is_relative_to_the_plot_not_the_valve(self):
        """사람이 알고 싶은 것은 "내 두둑이 얼마나 젖는가" 다."""
        row = self._plot(size=0.001)
        self._valve_area(0.0005, size=0.001)   # 절반 겹침
        v = self._valves(row)
        self.assertEqual(len(v), 1)
        self.assertAlmostEqual(v[0]['coverage_pct'], 50.0, delta=2.0)

    def test_two_valves_on_one_plot(self):
        """한 작물이 두 밸브에 걸치는 것은 정상이다."""
        row = self._plot(size=0.001)
        self._valve_area(-0.0004, name='A')
        self._valve_area(0.0006, name='B')
        v = self._valves(row)
        self.assertEqual(len(v), 2)
        # 많이 덮는 것이 먼저 온다
        self.assertGreaterEqual(v[0]['overlap_m2'], v[1]['overlap_m2'])

    def test_unassigned_valve_area_is_reported_not_hidden(self):
        """밸브가 안 정해진 구역에 걸친 것도 알아야 한다 — 물 줄 수단이 없다."""
        row = self._plot()
        self._valve_area(0.0)
        v = self._valves(row)
        self.assertEqual(len(v), 1)
        self.assertTrue(v[0]['unassigned'])
        self.assertIsNone(v[0]['device_id'])

    def test_no_water_amount_is_computed(self):
        """관수량을 내지 않는다 — 겹친 곳에서 물은 공유된다."""
        row = self._plot()
        self._valve_area(0.0)
        for key in ('water_l', 'liters', 'demand', 'amount'):
            self.assertNotIn(key, self._valves(row)[0])
